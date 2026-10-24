# -*- coding: utf-8 -*-
"""「秘书」：每个智能体自带的随员（`draft/53` v3 定位 · `draft/55` 接口规范 · `draft/54 §2`）。
它不是一个同级角色：不占 `schema.ROLES`、不加注册工具、不改权限面声明、不改 `llmseam` 的
enum、不重冻快照 ⇒ 一个计数都不变。同一个类，每角色一份配置（自己的定位 + 收发箱）。
## 四条职责（用户 2026-10-06 逐字裁定，`draft/53` §2）
| # | 职责 | 谁的秘书做 | 本模块的落点 |
|---|---|---|---|
| 1 | 格式与内容优化 | 发件方 | :meth:`Secretary.optimize_outbound`（对齐参数表/必填/工具真名；不替本体承诺） |
| 2 | 委派评估 | 发件方 | :meth:`Secretary.assess_delegation`（收件方真做得到吗 + 该不该派） |
| 4 | 委托加工 | 收件方 | :meth:`Secretary.rework_inbound`（按本角色定位改说法，不加码不减码） |
| 3 | 闭环提醒 | 收件方 | :meth:`Secretary.remind_closure`（未接手 / 未反馈；经 M） |
两条实质性红线（`draft/53` §2）：格式补不全、或加工后发现实质缺陷 ⇒ 与对方协商、不静默修
（:meth:`Secretary.negotiate` ≤2 轮 + 台账留痕）—— 它从不替本体表态。手稿通道的增/改/查也在
这里（`draft/55` §3）：`handoff_add` / `handoff_revise` / `handoff_query`，智能体侧只留"查"。
## 权限与失败姿态（`draft/55` §4）
库表只读（写集 ∅）；文件两处写：手稿通道 + 自己的台账 `out/secretary/<role>.jsonl`；不使用注册
工具；信息面 ≤ 本体，且 V 的秘书不读 F 的叙述（I12 的独立性不许被绕过）。fail-open：超时/出错
⇒ 原样放行 + 留痕，唯一例外是手稿执笔失败必须报错留痕。它是判断者不是仪表盘：不做任何统计
（用户 2026-10-06：那套统计是坏设计），成本靠 :meth:`Secretary.should_engage` 的机器预筛控制
（只在预筛报警 / 重复候选 / 闭环逾期 / 首次遇见该形态时才叫秘书；默认路径确定性）。
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import re
import threading
import time
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from . import manuscripts as MS
from . import proofloc as _PL
from . import propositionkey as _PK
from . import refusals as R
from . import schema as S
from . import statementbody as _SB

#: 台账落点：`<工作区>/out/secretary/<role>.jsonl`（追加式、脚本发号，`draft/53` §11.2）。
SECRETARY_DIR = ("out", "secretary")
#: 发件/收件的单次模型调用上限（`draft/55` §5.2：1 次调用、≤3 秒，超时放行）。
DEFAULT_DEADLINE_SEC = 3.0
#: 秘书 ⇄ 秘书协商的轮数上限（`draft/55` §5.2：最多 2 轮，之后上报本体）。
MAX_NEGOTIATION_ROUNDS = 2
#: 一次最多几条闭环提醒（`draft/55` §5.2：默认 5，避免刷屏）。
MAX_REMINDERS = 5
#: 六种事件名（`draft/55` §5.1）—— 常量在这里是为了让"冒充本体"这件事结构上不可能：
#: 秘书发出的每一条都带 `secretary/` 前缀。
KIND_OPTIMIZED = "secretary_optimized"
KIND_HANDOFF = "secretary_handoff"
KIND_NOTICE = "secretary_notice"
KIND_PROPOSAL = "secretary_proposal"
KIND_QUESTION = "secretary_question"
KIND_NEGOTIATION = "secretary_negotiation"
KIND_DECISION = "secretary_decision"
#: 秘书的判断结论词表（`draft/55` §2 的 B 类）——派活那一轴的结论。
DECISIONS = ("可派", "建议重排", "建议改派", "建议不派", "已优化", "已提醒", "已执笔")

# ---------------------------------------------------------------- 两段式：洗 → 请示 → 确认
#
# 业主裁定（2026-10-21）：派活时的"委托秘书洗一遍格式"是两段，不是一段：
#
# | 段 | 谁做 | 产物 |
# |---|---|---|
# | ① 洗 + 请示 | 发件方秘书 | `washed == original` ⇒ 无事发生（直接执行，不多花一轮）；有差异 ⇒ 不执行，出一份受控的请示读数（`outcome=wash_proposed` + `proposal_id` + 逐字段 diff） |
# | ② 确认 | 发起方（父） | `accept_proposal=<id>` ⇒ 用 `washed` 执行；`reject_proposal=<id>` ⇒ 用 `original` 执行并留痕 |
#
# 为什么不是"直接应用"（S1g 的旧形态）：那等于秘书替本体表态（`draft/53` §2 的两条红线），
# 而与它相对的那一版（"永远只建议"）又把洗格式变成摆设（`draft/90` E5 的差）。
# 两段式把"洗"与"要不要按洗过的派"分开：洗是格式面的确定性命中，要不要是父的事。
#
# 受控词：确认/拒绝的字段名、请示的 `outcome` 取值 —— 三者都只有这一份定义。
ACCEPT_PROPOSAL = "accept_proposal"
REJECT_PROPOSAL = "reject_proposal"
PROPOSAL_KEYS: tuple[str, ...] = (ACCEPT_PROPOSAL, REJECT_PROPOSAL)
#: 第一段的受控 `outcome` 值（步骤结果里就这一个词说"这一步没有派活"）。
OUTCOME_WASH_PROPOSED = "wash_proposed"
#: 执行那一趟台账 `decision` 那一格的受控取值（请示 / 接受 / 拒绝，只有这三个词）。
#: 三个都只在 :meth:`Secretary.optimize_outbound` 那一处产生，且与步骤结果的
#: `outcome` / `accepted` 一一对应（读台账的人不必再去猜"这一行是请示还是确认"）。
DECISION_PROPOSED = "洗出格式差异 ⇒ 请示"
DECISION_ACCEPTED = "接受了秘书的格式洗"
DECISION_REJECTED = "拒绝了秘书的格式洗"

#: 「这条命题够不够格入库」的结论词表（业主 2026-10-14 裁决第 12 条前半）。
#:
#: 为什么要另一张词表而不是往 `DECISIONS` 里加两个字：那是两根不同的轴 ——
#: `DECISIONS` 说的是"这条委托派不派、怎么派"，这张说的是"这条命题值不值得收"。
#: 折进一张表里，"可派"与"太平凡"就会被下游当成同一栏的取值，而它们回答的问题不同
#: （本仓把这种事叫"同一件事两个名字"的老毛病）。
#: 三态：判不了是正经结论之一（没缝 / 开关关着 / 模型没回），不是"先收了再说"。
STATEMENT_VERDICTS = ("合格", "太平凡", "判不了")

#: 非平凡性的五档（业主 2026-10-21 定 T1–T4；2026-10-23 补 T0）：它回答"多不平凡"，
#: 与 `STATEMENT_VERDICTS`（"收不收"）是两根轴。
#:
#: 2026-10-23 业主裁定的要点（逐字）：「只是加一个档位叫 T0（和 T1 到 T4 是一个性质），
#: T0 叫基础定理或初步结论，T1 重新定位为有一定价值的非平凡结论，T2 到 T4 定位不变」。
#: 所以 T0 不是"次品档"、不是"未评级"，它是同一根轴上的第一档：
#: 平凡但真的那些（`a+b=b+a` 那一类，以及由数值实验直接穷举出来的基础事实）落在 T0，
#: 而它们"能进表"这件事由 T0 这一档保证（改前是"平凡 ⇒ 当场拒收"）。
#:
#: | 档 | 语义（业主原话） |
#: |---|---|
#: | 0 | 基础定理或初步结论（平凡但真；含由数值实验直接穷举得出的那些） |
#: | 1 | 有一定价值的非平凡结论 |
#: | 2 | 证明方法都是平凡的，但工作量较大 |
#: | 3 | 需要用较多的技巧或跨领域工具 |
#: | 4 | 需要天才般的洞察力，或思维链极长，或是偏离主流研究方向的神奇构造 |
#:
#: "判不了"不再用 0 表示（0 从这一天起是一档真的档位）：见 :data:`NONTRIVIALITY_UNJUDGED`。
NONTRIVIALITY_LEVELS: tuple[int, ...] = (0, 1, 2, 3, 4)

#: "这一格没判成"的取值（三态里的第三态）。它不在 `NONTRIVIALITY_LEVELS` 里：
#:
#: 改前用 `0` 表示它，而 2026-10-23 起 `0` 是 T0（真的档位）—— 两个意思折进同一个值，
#: 读的人会把"没人判过"读成"基础定理"。所以这一档挪到 `None`（JSON 里是 null）。
NONTRIVIALITY_UNJUDGED: None = None

#: 档位台账的刻度的标记（写在每一行里）。
#:
#: 为什么需要它：`out/secretary/nontriviality.jsonl` 是 append-only 的，改前那些行里
#: `nontriviality: 0` 的意思是"判不了"（那时 0 不是档位）。没有这个标记，读侧就会把
#: 历史行 0 读成 T0 —— 那是把"没人判过"冒充成一条基础定理。所以：
#: 有 `scale == NONTRIVIALITY_SCALE` 的行按新刻度读（0 = T0）；
#: 没有这一格的历史行按旧刻度读（0 = 判不了）。
NONTRIVIALITY_SCALE = "T0-T4"

#: 判档位那一趟交给模型的材料（user 消息那一段）最多多少字。
#:
#: 2026-10-24 之前是 4000，而且没有任何一格说"被截了"。真机读数（sylow4）：一条正文
#: 8375 字，材料 JSON 在 4000 字处被切断，模型读到半句证明，于是给出"证明截断，无法
#: 定档"，台账落成 `nontriviality: null` + basis "材料不足"。业主裁定（2026-10-24）：
#: 正文被截断要显式报 `text_truncated`，并说清"档位判不了是因为输入不完整，不是因为
#: 材料不足"。所以这里两件事一起改：上限抬到与逐字段上限同量级（20 000），且超限时
#: 必须由 :func:`material_truncation` 报出精确的截断点。
JUDGE_MATERIAL_CAP = 24_000

#: 判档位读"力气"的那份正文最多读多少字（超出 ⇒ 这一趟的档位落「判不了 + 被截断」）。
#:
#: 与 :data:`JUDGE_MATERIAL_CAP` 分开：前者是"材料 JSON 有多长"，后者是"证明正文有多长"。
#: 两个数都必须显式，且都必须被 :func:`proof_effort_readings` 读到 —— 一处截断、另一处
#: 不知道，就是 2026-10-24 之前那个形态。
PROOF_BODY_CAP = 20_000

#: 空命题正文的受控码（写侧 `register_statement` 与判档位这一侧共用一个字面量）。
#:
#: 为什么不是复用 `bad_statement`：那一个管的是"只有短版（statement_text）、没有含完整
#: 假设的正文"，这一档管的是"0 字"（连短版都没有）。两种输入的处置相同（整笔不写），
#: 但读数必须分得开 —— 前者是"你给错了栏"，后者是"没有可判的对象"。
#: 字面量的真身住在 `refusals.py`：同一句拒绝在写侧与判档位这一侧必须说同一个词。
EMPTY_STATEMENT_TEXT = R.EMPTY_STATEMENT_TEXT

#: 档位的显示名（`0 -> "T0"`）。读侧一律调 :func:`nontriviality_label`，不各写一份。
_NONTRIVIALITY_LABELS: dict[int, str] = {level: f"T{level}" for level in NONTRIVIALITY_LEVELS}


def nontriviality_label(level: Any) -> str:
    """档位号 → 显示名（`0 -> "T0"` … `4 -> "T4"`；判不了 ⇒ 空串）。"""
    got = _nontriviality_level(level)
    return _NONTRIVIALITY_LABELS.get(got, "") if got is not None else ""


def _is_trivial_verdict(decision: Any) -> bool:
    """这一次判断的结论是不是「太平凡」（唯一口径）。

    为什么要单独一个函数：2026-10-23 之后"太平凡"这个结论有两个后果（落 T0 +
    不在入库口拒收），两处必须问同一个问题。而这一条是"把'懂平凡'这一档打桩"
    的注射点 —— 判据要把"恒判平凡"打进去看非平凡那一支会不会红，就得有一个名字。
    """
    return str(decision or "") == "太平凡"

#: 「这一条与在册的哪一条是同一条命题」的结论词表（业主 2026-10-24 的准绳）。
#:
#: 业主逐字：「定理描述一致（什么条件推出什么结论），就是一个定理」。所以这一问只有三个
#: 结论：同一组条件推出同一组结论（same）/ 不是（different）/ 条件或结论有一侧写不清、
#: 判不了（unknown）。三态不是"两态 + 一个兜底"：unknown 的处置是"不并、留凭据"，它与
#: different（"判过了，确实不是"）在台账上必须分得开 —— 折平就会把"没人判过"读成"判过
#: 了、不同"，于是同一条定理又被拆成两条。
PROPOSITION_VERDICTS: tuple[str, ...] = ("same", "different", "unknown")

#: 命题同一性判定的旁支台账（append-only）：一行一次判定，键是命题正文的 sha256。
#:
#: 为什么按正文 sha 缓存而不是按本次登记：同一段正文被交上来第二遍（改个标签、换个人重交、
#: 重试）时，判定不会有别的结论 —— 而每一次都要真发一次模型调用。真机 sylow4 的形态正好是
#: "同一条定理交了三遍"，没有这一层就是三笔钱买同一句话。
PROPOSITION_VERDICT_LEDGER = "proposition_verdicts.jsonl"

#: 交给秘书的候选上限（"按主题粗筛一小批"）：4 条。
#:
#: 为什么不给更多：一次判定要在提示词里同时放下这一条的正文与每条候选的正文/定理名。
#: 候选越多，每条能分到的字数越少 —— 而对"条件与结论是否一致"这件事，半条命题没有用。
PROPOSITION_VERDICT_CANDIDATES = 4

#: 一次判定里这一条正文最多看多少字符（每条候选各自也有同样的上限）。
PROPOSITION_VERDICT_TEXT_CHARS = 1200

#: 证明的"路子"说明住在哪：行 JSON 里一个 `{证明号: 一句话}` 的字典。
#:
#: 业主要求（2026-10-24）：「路线写在证明这一层」。它不能待在命题的 label 里 ——
#: 那条 label 是定理名（`Sylow 三定理`），带"（路线一：…）"之后，同一条定理的三种证法
#: 就成了三条不同的命题（真机 sylow4 的三行正是这么来的）。所以：
#: 定理名归 label，路子归证明号（这一格），依赖的路径分组归 `Dependency.path_group`。
#: 键是证明号的字符串形式（JSON 的键只能是字符串），读侧一律走 :func:`proof_route_of`。
PROOF_ROUTES_KEY = "_proof_routes"

#: 判断类别 → 它允许的结论词表（唯一一处把"哪类判断有哪些结论"写下来的地方）。
#:
#: 加一类判断时只加一行：`Secretary.JUDGE_KINDS` 与 `judge()` 的校验都从这张表派生，
#: 于是"新类别悄悄用了别的轴的词"这件事在结构上就发生不了。
JUDGE_VERDICTS: dict[str, tuple[str, ...]] = {
    "duplicate_retry": DECISIONS,
    "tool_name": DECISIONS,
    "rearrange": DECISIONS,
    "statement_aesthetic": STATEMENT_VERDICTS,
    # 命题同一性（业主 2026-10-24：「让秘书洗定理名，让秘书判」）：结论词表就是三态。
    "proposition_identity": PROPOSITION_VERDICTS,
}


def decisions_path(root: str | Path, role: str, task_id: str = "") -> Path:
    """这一名秘书的决定台账路径。

    - `task_id` 空 ⇒ 老文件 `out/secretary/<role>.jsonl`（每角色一份，绝不混写 —— `draft/53` §5 的防错①）：
      历史行仍然在这里，读侧必须继续读得到；
    - `task_id` 给了 ⇒ 分片 `out/secretary/<role>-<task_id>.jsonl`（S1m）：一实例一片、一个写者一片，于是
      同角色的并发实例（`summon_many` 的多 `instance`）不再往同一个文件里挤（D106/D107 的修法）。
    注意：名字刻意不叫 `ledger_path` —— 那个名字在 `artifacts.py`（产物归属台账）与 `signatures.py`（签名
    台账）里各有一份独立实现，而秘书的决定台账与它们不是同一件事 —— 合并它们会把三件不同的事折成一个
    （lint R003 的口径是"同一判据的两份实现必须合并"，这里恰恰不是同一判据，所以正确的做法是改名字而不是合并）。
    """
    name = f"{role}-{task_id}.jsonl" if str(task_id or "") else f"{role}.jsonl"
    return Path(root).joinpath(*SECRETARY_DIR, name)


#: 同一进程里按路径复用的追加锁（与 `sessions.append` 同一做法）。
_APPEND_LOCKS: dict[str, Any] = {}
_APPEND_LOCKS_GUARD = threading.Lock()


def _append_lock(path: Path) -> Any:
    """同一路径的进程内锁（`filelock` 在同进程里不是线程安全的，两层都要）。"""
    key = str(path)
    with _APPEND_LOCKS_GUARD:
        lock = _APPEND_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _APPEND_LOCKS[key] = lock
        return lock


def _append_locked(path: str | Path, rec: Mapping[str, Any], *,
                   stamp_field: str = "", stamp_prefix: str = ""
                   ) -> tuple[bool, str, dict[str, Any]]:
    """追加一行的真身：锁内取号（可选：顺手把 `stamp_field` 也发成号）。

    返回 `(写成了吗, 问题, 落盘那一行)`。三件事只在这一处做：进程内锁、跨进程锁、
    `seq = max+1`。`stamp_field` 非空时，那一格的值 = `stamp_prefix + 锁内 seq`
    —— 这是"编号由秘书发"的唯一落点（`draft/90` §1.2 的请示编号，
    见 :meth:`Secretary.note_decision` 的 `proposal`）：同一个 seq 既是行号也是号源，
    于是"这个编号指向哪一行"在结构上不可能漂。

    `seq` 的宽度从 `schema.format_id` 取（与 `store.alloc_id` / 手稿号 / 留言号同一个
    发号形态）：本文件此前自己按"四位 + 冒号补零"的写死宽度拼号，于是业主 2026-10-14 把宽度
    定成六位之后，请示编号是唯一还在发四位的那一处（判据
    `tests/test_id_width.py::test_no_four_digit_mint_remains_in_the_source` 咬的就是它）。
    宽度只有一处可改这件事，靠的就是每个发号点都走 `format_id`。

    为什么要发号而不是让调用方拼一个：拼号的两种写法（时间戳、载荷哈希）都在
    锁外取值 —— 并发下会重号，而重号的请示意味着"接受 A 的编号却执行了 B 的洗"。
    """
    from filelock import FileLock

    target = Path(path)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return False, f"{type(exc).__name__}: {exc}", {}
    # 2026-10-17（真机 T2r/T5e 两趟同一个崩溃）：这里原本 `json.dumps(dict(rec))` 没有
    # `default=`、且在 try 之外 ⇒ 交接行里一旦带 `TopicalityReport` 这类冻结 dataclass，
    # 就直接冒泡成「A 执行中异常 TypeError: … is not JSON serializable」。
    # 序列化边界上把未知对象折成字符串（读数照旧、语义不变），绝不让"写一行台账"炸掉整步执行。
    try:
        line = json.dumps(dict(rec), ensure_ascii=False, sort_keys=True, default=str) + "\n"
    except Exception as exc:  # noqa: BLE001 —— 与本函数契约一致：写不成要如实报
        return False, f"{type(exc).__name__}: {exc}", {}
    with _append_lock(target):
        try:
            with FileLock(str(target) + ".lock", timeout=30.0):
                seq = 1
                if target.is_file():
                    text = target.read_text(encoding="utf-8", errors="replace")
                    for raw in text.splitlines():
                        raw = raw.strip()
                        if not raw:
                            continue
                        try:
                            row = json.loads(raw)
                        except Exception:  # noqa: BLE001 —— 坏行不参与取号
                            continue
                        if isinstance(row, dict):
                            seq = max(seq, int(row.get("seq") or 0) + 1)
                out = dict(rec)
                out["seq"] = seq
                if stamp_field:
                    out[str(stamp_field)] = f"{stamp_prefix}{S.format_id(seq)}"
                line = json.dumps(out, ensure_ascii=False, sort_keys=True, default=str) + "\n"
                with target.open("a", encoding="utf-8", newline="\n") as fh:
                    fh.write(line)
        except Exception as exc:  # noqa: BLE001 —— 写不成要如实报（调用方留痕）
            return False, f"{type(exc).__name__}: {exc}", {}
    return True, "", out


def append_jsonl(path: str | Path, rec: Mapping[str, Any]) -> tuple[bool, str]:
    """唯一的秘书台账追加口（S1m）：进程内锁 + 跨进程 `filelock`，`seq` 在锁内算。

    返回 `(写成了吗, 问题)`。为什么必须集中到一处（`draft/91` §7 的 D107）：旧写法是
    "先读全表算 `seq = max+1`、再 `path.open("a")` 追加" —— 读与写之间没有锁，
    同角色的两个实例并发时会拿到同一个 `seq`（与 `_write_new_row` 修过的那个缺陷同族）。

    `seq` 的口径是每片自增（片就是"一个实例的账"），所以两片之间 `seq` 可以重复 ——
    合并视图（`Secretary.merged_decisions`）按 `at` 排序，不靠 `seq` 全局唯一。
    """
    ok, problem, _row = _append_locked(path, rec)
    return ok, problem


def append_jsonl_stamped(path: str | Path, rec: Mapping[str, Any], *,
                         field: str, prefix: str = "") -> tuple[bool, str, str]:
    """同一条追加口，另把 `field` 一格发成 `prefix + 锁内 seq`（编号由秘书发）。"""
    ok, problem, row = _append_locked(path, rec, stamp_field=field, stamp_prefix=prefix)
    return ok, problem, str(row.get(str(field)) or "")


def _pid_alive(pid: int) -> bool:
    """这个 pid 还活着吗 —— 复用 `stopctl.alive`（一处实现，不抄第二份）。

    为什么不自己写：探活在 Windows 上有两个坑，`stopctl.alive` 的 docstring 逐字记着 ——
    `tasklist` 在沙箱里拿不到读数（本机实测：登记了自己的 pid 也判"不活着"），
    而 `os.kill(pid, 0)` 在 Windows 上不是探活、它会 `TerminateProcess`。
    本模块第一版正是踩了第一个坑（自己起 `tasklist` + 管子拿输出 ⇒ 沙箱里 EPERM），
    冒烟时就判出自己的 pid "不活着"。
    """
    try:
        from . import stopctl

        return bool(stopctl.alive(int(pid)))
    except Exception:  # noqa: BLE001 —— 查不成 ⇒ "不知道"，由调用方的三态说
        return False


# ---------------------------------------------------------------- 名册与对照表（S1k）
#
# 落点：`out/roster/<owner>.jsonl`（名册）、`<owner>-index.jsonl`（电话簿）、
# `<owner>-retired.jsonl`（销号名单）。三份都 append-only，读侧折叠。
# 为什么不放 `out/secretary/`：`webui/readers.py` 是目录 glob（`*.jsonl`），
# 同目录会把名册行混进"秘书决定台账"那一面（`draft/92` §2 的落点说明）。

ROSTER_DIR: tuple[str, ...] = ("out", "roster")


def roster_path(root: str | Path, owner: str) -> Path:
    """名册（`owner` = 父的绝对编码）。"""
    return Path(root).joinpath(*ROSTER_DIR, f"{owner}.jsonl")


def roster_index_path(root: str | Path, owner: str) -> Path:
    """对照表（电话簿）：本地名 → 当前调用行。"""
    return Path(root).joinpath(*ROSTER_DIR, f"{owner}-index.jsonl")


def retired_path(root: str | Path, owner: str) -> Path:
    """销号名单（业主 B1：名字一经退役永久不复用；后续版本的新功能读它）。"""
    return Path(root).joinpath(*ROSTER_DIR, f"{owner}-retired.jsonl")


#: 名册目录里"不是名册正文"的那几种后缀（`<父>-index.jsonl` / `<父>-surfaces.jsonl` /
#: `<父>-retired.jsonl`）。全工作区口径的读数按它排除，而不是按"文件名里有没有横线"猜 ——
#: 父的编号本身不含横线，但靠猜迟早会把一种新后缀算成一份名册。
_ROSTER_SIDECAR_SUFFIXES: tuple[str, ...] = ("-index.jsonl", "-surfaces.jsonl",
                                             "-retired.jsonl")


def roster_owners(root: str | Path) -> tuple[list[str], str]:
    """`out/roster/` 下有哪些父名册（`(父编号列表, 问题)`）。

    只认 `<父>.jsonl`：三种旁支（对照表 / 面池 / 销号名单）按
    `_ROSTER_SIDECAR_SUFFIXES` 排除。目录不存在 ⇒ `([], "")`（那是"还没有人派过活"，
    不是读失败）；目录读不出来 ⇒ `([], 理由)`（三态，不折成"一份名册都没有"）。
    """
    folder = Path(root).joinpath(*ROSTER_DIR)
    if not folder.is_dir():
        return [], ""
    try:
        names = [p.name for p in folder.iterdir() if p.is_file()]
    except Exception as exc:  # noqa: BLE001 —— 读不成是"没查成"
        return [], f"名册目录读不成（{type(exc).__name__}: {exc}）"
    out: list[str] = []
    for name in names:
        if not name.endswith(".jsonl"):
            continue
        if any(name.endswith(s) for s in _ROSTER_SIDECAR_SUFFIXES):
            continue
        owner = name[: -len(".jsonl")]
        if owner:
            out.append(owner)
    return sorted(out), ""


# ---------------------------------------------------------------- 读写面与槽位池（S1n）
#
# 业主 T23：子代理只能读写父切割给它的面；父原则上必须把各子代理的面拆开（不重叠）；
# 面内的新文件允许。退役之后面归还"可分配池"（名字不回收，面回收）。
# 落点：`out/surfaces/<owner>/<slot>/`（面本体）、`out/roster/<owner>-surfaces.jsonl`（池事件）、
# `out/surfaces/archive/<owner>-<name>/`（归还前的归档）。

SURFACES_DIR: tuple[str, ...] = ("out", "surfaces")

#: 哪些工具的哪些参数是"落在盘上的路径"（`draft/90` §1.11 / §2 的 E22）。
#:
#: 默认规则：`fs.*` 的 `path`。名字不叫 `path` 的逐条登记在这里 —— 今天只有
#: `fs.move`（它的 schema 是 `{'src','dst'}`，没有 `path`，于是它在 S1n-b 的硬拦里
#: 整个漏掉了：子代理可以用它把面外的文件搬进自己的面）。
#:
#: 这张表只有一处，两个时机共用：预看（`Secretary.surface_fit`）与硬拦
#: （`AgentLoop._surface_refusal`）。分两份写迟早出现"预看说越界、硬拦放过去"
#: 这种自相矛盾，而两边的判据都会是绿的。
SURFACE_PATH_ARGS: dict[str, tuple[str, ...]] = {"fs.move": ("src", "dst")}


def surface_path_args(action: str) -> tuple[str, ...]:
    """某个工具/动作里"是路径"的那几个参数名（空元组 = 这个动作没有可判的盘上路径）。

    读不到名字（空串）⇒ 空元组；非 `fs.` 的动作一律空元组（面这一维今天只说 `fs.*`，
    与 `AgentLoop._surface_refusal` 同一条范围）。
    """
    name = str(action or "")
    if not name.startswith("fs."):
        return ()
    return ("path",) + tuple(SURFACE_PATH_ARGS.get(name, ()))


def surfaces_path(root: str | Path, owner: str) -> Path:
    """池事件流（`alloc` / `release` / `archive_failed`），append-only。"""
    return Path(root).joinpath(*ROSTER_DIR, f"{owner}-surfaces.jsonl")


def surface_dir(root: str | Path, owner: str, slot: str) -> Path:
    """一个槽位的面（目录）。"""
    return Path(root).joinpath(*SURFACES_DIR, owner, str(slot))


def archive_dir(root: str | Path, owner: str, name: str) -> Path:
    """归还前把面里的东西归档到这里（业主口径的反面：新子代理不该看到前任的文件）。"""
    return Path(root).joinpath(*SURFACES_DIR, "archive", f"{owner}-{name}")


def _fold_surfaces(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """把池事件流折叠成"每个槽位此刻在哪一档"（空闲 / 在用 / 待释放）。"""
    items: dict[str, dict[str, Any]] = {}
    for raw in rows:
        r = dict(raw)
        slot = str(r.get("slot") or "")
        if not slot:
            continue
        item = items.setdefault(slot, {"slot": slot, "name": "", "state": "空闲"})
        kind = str(r.get("kind") or "")
        if kind == "alloc":
            item["name"] = str(r.get("name") or "")
            item["state"] = "在用"
        elif kind == "release":
            item["name"] = ""
            item["state"] = "空闲"
            item.pop("reason", None)
        elif kind == "archive_failed":
            item["name"] = str(r.get("name") or "")
            item["state"] = "待释放"
            item["reason"] = str(r.get("reason") or "")
    return [items[k] for k in sorted(items)]


def _fold_roster(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """把名册事件流折叠成"当前状态"（一项一条 = 一个常驻子代理）。

    口径：`add` 建项（一项 = 一个子代理的身份：名字 / 角色 / 简介 / 面）；
    `bind` 只推这一项"最近一次接的活"的编号读数；`retire` 标退役；`keep_alive` 只记
    那一格。名字是身份：同一个名字不会有两项。

    `task_id` / `first_task_id` 是"调用流水读数"（这一项是为哪件活建的、最近一次
    是哪件活），不是身份，也不是归属键 —— 一个子代理可以接 N 件活，名册里仍是
    一项（业主 2026-10-24：「一个子代理可接收多个任务」「不可按照任务号记录名册」）。
    """
    items: dict[str, dict[str, Any]] = {}
    for raw in rows:
        r = dict(raw)
        name = str(r.get("name") or "")
        if not name:
            continue
        item = items.setdefault(name, {"name": name, "role": str(r.get("role") or ""),
                                       "brief": "", "brief_source": "", "task_id": "",
                                       "retired": False})
        kind = str(r.get("kind") or "")
        if str(r.get("role") or ""):
            item["role"] = str(r.get("role") or "")
        if kind == "add":
            item["brief"] = str(r.get("brief") or "")
            # 简介是谁写的（业主 2026-10-20：「简介没写，秘书帮忙写」）：
            # `parent` = 父给的原话；`secretary` = 秘书从任务原文派生的一句；
            # `""` = 这一格是改前落的行（那时还没有这一格，不许倒填成"父给的"）。
            item["brief_source"] = str(r.get("brief_source") or "")
            item["task_id"] = str(r.get("task_id") or "")
            item["first_task_id"] = str(r.get("first_task_id") or r.get("task_id") or "")
            item["surface"] = str(r.get("surface") or "")
        elif kind == "bind":
            item["task_id"] = str(r.get("task_id") or item.get("task_id") or "")
        elif kind == "retire":
            item["retired"] = True
            item["retired_branch"] = str(r.get("branch") or "")
        elif kind == "keep_alive":
            item["keep_alive"] = bool(r.get("value"))
    return [items[k] for k in sorted(items)]


def _fold_index(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """把对照表折叠成"名字 → 当前调用（+ 第一次那个）"。

    `bind` 推当前；`retire` 标退役（行保留：编码不回收，反查还要用）。
    """
    items: dict[str, dict[str, Any]] = {}
    for raw in rows:
        r = dict(raw)
        name = str(r.get("name") or "")
        if not name:
            continue
        item = items.setdefault(name, {"name": name, "role": str(r.get("role") or ""),
                                       "task_id": "", "first_task_id": "",
                                       "retired": False})
        if str(r.get("role") or ""):
            item["role"] = str(r.get("role") or "")
        if str(r.get("kind") or "") == "retire":
            item["retired"] = True
            continue
        item["task_id"] = str(r.get("task_id") or item.get("task_id") or "")
        if r.get("first") or not item.get("first_task_id"):
            item["first_task_id"] = str(r.get("task_id") or item.get("first_task_id") or "")
    return [items[k] for k in sorted(items)]


#: 名册简介的字数上限 —— 与内容闸是同一个数（`roster_add` 里 `len(text) > 60` 那一档）。
#: 代写那一支必须自己截到这个长度以内：否则秘书写出来的那句话会被秘书自己的闸拒，
#: "没给简介"就变成"永远登记不上"（死角）。
BRIEF_MAX = 60

#: 句末标点（取"第一句"时截到它为止，含它）。刻意不收 `.`：小数（`1.5`）、
#: 文献号、相对路径（`../x`）里的点会把一句话切碎，而任务原文的句末几乎总是这几个。
_SENTENCE_END: tuple[str, ...] = ("。", "！", "？", "!", "?", "；", ";")


def brief_from_task(task: str, *, limit: int = BRIEF_MAX) -> str:
    """从任务原文派生一句名册简介（确定性：不调模型、不花钱、不随机）。

    业主 2026-10-20 裁定逐字：「简介没写，则秘书帮忙写，秘书的重要职责就是辅助通讯」⇒ 名册里那一句不再
    只能由父给：父没给而写了 `task` 时，由秘书代写并留痕（`brief_source="secretary"`），不许静默冒充"父给的"。
    规则（五步，逐条可复算；判据见 `tests/test_secretary_writes_the_brief.py`）：
    1. 折平：`str.split()` —— 换行 / 制表 / 连续空白一律折成一个半角空格、首尾去净（结果不含换行）；
    2. 取第一句：扫到第一个句末标点（`_SENTENCE_END`，含该标点）为止；一个都没有就取全文；
    3. 截断：`limit` 个字符（缺省 `BRIEF_MAX` = 内容闸的同一个数 60）；
    4. 去尾：`strip()` 掉截断留下的尾巴空白；
    5. 空就是空：给的全是空白 ⇒ `""` —— 调用方据此走"没给一句任务简介"那一档，不许编。
    """
    flat = " ".join(str(task or "").split())
    if not flat:
        return ""
    cut = len(flat)
    for i, ch in enumerate(flat):
        if ch in _SENTENCE_END:
            cut = i + 1
            break
    return flat[:min(cut, int(limit))].strip()


def _state_from(branch: str, retired: bool, cond: Any, task_id: str) -> str:
    """四态折叠（`draft/92` §2）：活跃 / 待命 / 已停 / 已退役。

    `branch` 来自 `conductor.retire_ready`（`active` / `waiting_with_children` /
    `waiting_no_children`）；"待命"再看 `keep_alive_of`（那一格只回答"声明过待命没有"）。
    两个读侧正交，折叠只在这一处做（不许让它们互相猜）。
    """
    if retired:
        return "已退役"
    if branch == "active":
        return "活跃"
    if not branch:
        return "未登记"
    try:
        ka = cond.keep_alive_of(task_id)
    except Exception:  # noqa: BLE001
        ka = {"checked": False}
    if ka.get("checked") and ka.get("keep_alive"):
        return "待命"
    return "已停"


def _status_enum(facts: Mapping[str, Any], *, retired: bool) -> str:
    """`status` 那一格（S-H，裁定 14）。前三档照 DSH `list-agents.js:24-29` 逐字。

    - 不在 live registry（我们这边 = 台账里没有它正在跑的行）⇒ `ready`；
    - 在且 `status in (pending, running)` ⇒ `running`；
    - 否则 ⇒ `idle`（DSH 的 `maintenance`（正在收尾）也算 idle，我们这边 `closing`
      那一档同理 —— 收尾不是"在干活"）。

    第四档 `retired` 是如实加的一档（我们的销号名字永久不复用）：
    DSH 的 `ready` 逐字意思是"没有活着的 Agent、但仍可续"，把销号读成它会让模型
    去叫一个再也叫不醒的名字 ⇒ 那个错法的代价比"多一个取值"大。
    """
    if retired:
        return "retired"
    if not facts:
        # 台账里没有它这一行（未登记 / 已被清）⇒ `ready`：那一档的语义正是
        # "不在活的登记表里"，而"能不能续"由旁边那格 `state` 回答。
        return "ready"
    if str(facts.get("status") or "") in ("pending", "running"):
        return "running"
    return "idle"


def _diagnose_line(problem: str) -> dict[str, Any]:
    """一条坏行读数 → 逐行 diagnostic（DSH `list-agents.js:30-47` 的三档）。

    `corrupt` = 那一行不是合法 JSON / 不是对象；`unavailable` = 整个文件读不出来
    （IO 层失败）；`unsupported` = 其余（形状能读、但我们不认这一行的内容）——
    第三档留着是因为把"没见过的东西"折进前两档会让"这一行到底坏在哪"失去分辨率。
    """
    text = str(problem or "")
    if "读不出来（" in text and "第 " not in text:
        kind = "unavailable"
    elif "第 " in text and "行" in text:
        kind = "corrupt"
    else:
        kind = "unsupported"
    return {"line": text, "kind": kind}


def _clip_text(text: str, limit: int) -> str:
    """剪一段可读的正文（多余部分写清"还有多少字没进来"，不许静默截断）。"""
    body = str(text or "").strip()
    if len(body) <= limit:
        return body
    return body[:limit] + f"…（还有 {len(body) - limit} 字没进来，全文用 manuscripts.read 读）"


def _as_mapping(value: Any) -> dict[str, Any]:
    """把一个"看起来像声明"的对象读成 dict（`RoleBrief` 是 dataclass，不是 Mapping）。

    读不出来（`None` / 别的类型）就返回空表，且只在最后一个分支返回它 ——
    调用方必须把"空表"读成"这一格判不了"，不是"没有定位"。
    """
    import dataclasses

    if isinstance(value, Mapping):
        return dict(value)
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: getattr(value, f.name) for f in dataclasses.fields(value)}
    return {}


def declarations_candidates(name: str, names: Iterable[str], *, limit: int = 3) -> list[str]:
    """错名的并列候选（薄转发到 `tools.base.candidate_tool_names`，判据只有一份）。

    为什么在这里再包一层：秘书不使用注册工具，但它必须能回答
    "这个名字是不是真名"（职责 1）。转发而不是重写 —— 两份候选算法必然分叉，
    而分叉的形态是"机器给的候选与秘书给的候选不是同一批"。
    """
    from .tools.base import candidate_tool_names

    return candidate_tool_names(name, names, limit=limit)


#: 秘书的写集（业主 2026-10-09：B 交内容、秘书落盘）。只有这两张表，
#: 且只经 `Secretary.record_statement` 一处 —— 声明与实现同一位。
STATEMENT_WRITE_TABLES: tuple[str, str] = ("statements", "dependencies")
#: 谁可以交命题内容给这一条路径（写入侧是 B 的活，别的人交 ⇒ 受控拒绝）。
STATEMENT_WRITER_ROLES: tuple[str, ...] = ("B",)
#: `deps_missing` 的三档（三态：不把「不适用」折成「缺」，也不把「缺」折成「零依赖」）。
DEPS_MISSING_PRESENT = "present"
DEPS_MISSING_ABSENT = "missing"
DEPS_MISSING_NOT_APPLICABLE = "not_applicable"
DEPS_MISSING_STATES: tuple[str, ...] = (DEPS_MISSING_PRESENT, DEPS_MISSING_ABSENT,
                                        DEPS_MISSING_NOT_APPLICABLE)
#: 一条命题载荷认得的字段（正名）。别名表见 `STATEMENT_KEY_ALIASES`。
STATEMENT_PARAM_KEYS: frozenset[str] = frozenset({
    "statement_full", "statement_text", "kind", "label", "proof_text", "origin",
    "source_lit_id", "doc_id", "page_range", "line_range", "evidence_kind",
    "quote_verified", "quote_reason", "derived_from", "aliases", "bits",
    # 2026-10-14（业主：「回验……保持语义相同即可」+「语义那一档必须留证据」）：
    # 方式与证据三栏必须能过秘书这一道 —— 否则 B 传给 `register_statement` 的
    # `quote_mode` 会被这一层的白名单静默丢掉（那一栏就白填了）。
    "quote_mode", "quote_span", "quote_call_sha256",
    "deps", "concepts",
    # 2026-10-21（本批缺陷一）：概念行"确实是我们自己定义的新概念"的显式声明。
    # 它必须能过这一层的白名单 —— 否则调用方在概念条目里写的那一句
    # `self_authored=True` 会被静默丢掉，于是"声明了"与"没声明"落成同一件事，
    # 而 `origin="own_result"` 的受控判据（`conceptrows.concept_origin_problem`）
    # 就永远只能拒绝、无法放行。
    "self_authored",
    # 多段可选证明：B 自己分的段（每段一组 `path_group`）。不给就把
    # "定理内容 + 证明过程"当一段 —— 秘书不按空行/字样猜 B 想分几段（`draft/97` §14.11）。
    "proof_paths",
    # 2026-10-24（业主：表述几乎相同的定理要认出是同一个；证明方式几乎相同的视为同种
    # 证明，可选"各取所长混合成一份、重拿 V 签"）：`merge=True` 是那一档可选项的开关。
    # 它必须能过这一层的白名单 —— 否则调用方交上来的合并稿会被静默当成"另一份新证明"。
    "merge",
})
#: 键名别名 ⇒ 正名（每一列的别名必须唯一，否则 `_statement_key_candidate` 返回空 =
#: "不猜"）。写在这里而不是散在代码里，是为了让"认哪些写法"可被一条判据逐条读出来。
STATEMENT_KEY_ALIASES: dict[str, tuple[str, ...]] = {
    "statement_full": ("full", "statement", "theorem", "content", "claim"),
    "statement_text": ("short", "text", "summary"),
    "kind": ("type", "statement_kind"),
    "label": ("name", "title"),
    "proof_text": ("proof", "proof_process"),
    "source_lit_id": ("lit_id", "lit"),
    "doc_id": ("document_id",),
    "page_range": ("pages",),
    "line_range": ("lines",),
    "evidence_kind": ("evidence",),
    "derived_from": ("uses",),
    "aliases": ("aka",),
    "deps": ("dependencies", "dep_groups", "paths"),
    "proof_paths": ("proof_groups", "proof_segments"),
    "concepts": ("definitions",),
}
#: 同一命题的判据（业主 2026-10-24）：命中键或命中相似度 ⇒ 这一笔不是新命题，
#: 而是那条命题的第 N 份证明。缺省阈值与唯一实现都在 `propositionkey`，
#: 这里只是把它们摆到秘书这一层（可注入：构造参数 `same_proposition_jaccard`）。
SAME_PROPOSITION_JACCARD = _PK.SAME_PROPOSITION_JACCARD
#: 同种证明的判据（同一命题下的第 N 份证明）：命中 ⇒ 不新增证明号，受控拒绝
#: `proof_same_kind`（或 `merge=True` 合成一份并重拿 V 签）。
PROOF_SAME_JACCARD = _PK.PROOF_SAME_JACCARD
#: 同一命题命中的两条依据（进返回值与拒信：读的人要能分辨"凭什么并的"）。
MERGED_BY_KEY = _PK.BASIS_KEY
MERGED_BY_SIMILARITY = _PK.BASIS_SIMILARITY
#: 第三种依据（2026-10-24 晚）：秘书那一趟模型判定说"同一条"（`adjudicate_proposition`）。
#:
#: 它必须与上面两条分开命名：键相同 / 相似度兜底都是机械读数，而这一条是"读了条件与结论
#: 之后判的" —— 三者的可信度、可复核方式、以及"凭什么并的"那句话都不一样。
MERGED_BY_ADJUDICATION = "secretary_adjudication"
#: 同种证明的拒收码（写侧与拒信共用这一个字面量）。
PROOF_SAME_KIND = "proof_same_kind"
#: 参与"同一命题"判定的 kind（命题性的那几档）。
#:
#: 为什么需要这一格：`Statement.kind` 刻意是自由文本（`schema.Statement` 的类 docstring
#: 写明"不参与任何判据分支"），于是"两条表述几乎相同的命题是同一个"这句话不能对所有
#: kind 都成立 —— 一条 `definition` 不是命题，把一条定理并进一条定义（或反过来）会让
#: 台账上少掉一整类条目，而"并了"这件事在盘上看起来完全合法。真机反例就在本仓的判据里：
#: `tests/test_agent_b_concept_registration_carries_kind.py` 用"同一条正文、只换
#: theorem / definition"核对五个位是否逐字相同 —— 那两条本来就该是两行。
#: 反过来，`theorem` 与 `lemma` 之间要能并：同一份东西在两篇文献里被叫成两种名字是常态，
#: 而那不是"两条命题"。
#: 认不出的 kind 一律不并（保守：并错一条的代价比漏并大）。
PROPOSITION_KINDS: tuple[str, ...] = ("theorem", "lemma", "proposition", "corollary",
                                      "conjecture")


def _is_proposition_kind(kind: Any) -> bool:
    """这个 kind 算不算"命题性的"（决定它参不参与同一命题判定）。"""
    return str(kind or "").strip().lower() in PROPOSITION_KINDS
#: 一步依赖认得的来源键 ⇒ `(来源字段, 表, 表的 id 字段, 该给的 `kind` 缺省)`。
#: 顺序就是"先认哪一个"：一步最多给一个来源（`Dependency.validate` 的"四选一"）。
STEP_SOURCE_KEYS: tuple[tuple[str, str, str, str, str], ...] = (
    ("stmt_id", "source_stmt_id", "statements", "stmt_id", "theorem"),
    ("experiment_id", "source_experiment_id", "experiments", "experiment_id", "experiment"),
    ("lit_id", "source_lit_id", "literature", "lit_id", "theorem"),
    ("doc_id", "source_doc_id", "documents", "doc_id", "theorem"),
)
#: 一步依赖的键名别名（与 `STATEMENT_KEY_ALIASES` 同一套纪律：不唯一就不猜）。
STEP_KEY_ALIASES: dict[str, tuple[str, ...]] = {
    "stmt_id": ("stmt", "statement_id", "statement"),
    "experiment_id": ("exp", "exp_id", "experiment"),
    "lit_id": ("lit", "literature_id"),
    "doc_id": ("doc", "document_id"),
    "kind": ("type",),
    "label": ("name", "title"),
    "quote": ("quote_text",),
}


def _statement_key_candidate(key: str) -> str:
    """别名 ⇒ 正名；没有唯一候选时返回空串（不猜：两条正名都收它，就是歧义）。"""
    hits = [canon for canon, alts in STATEMENT_KEY_ALIASES.items() if key in alts]
    return hits[0] if len(hits) == 1 else ""


def _wash_dep_groups(raw: Any) -> tuple[list[list[dict[str, Any]]], list[str]]:
    """把 `deps` 洗成二维列表（外层 = 可选路径，内层 = 一条路径上的步骤）。

    一维列表（一串步骤）⇒ 包成 `[一层]`：那是"只有一条路径"的写法，语义不变；
    非列表 / 空 ⇒ `[]`（不补默认值：补一条空的路径等于替 B 编一条依赖）。
    每一步的键名按 `STEP_KEY_ALIASES` 归一（id 本身一个字不动）。
    """
    changes: list[str] = []
    if raw in (None, "", []):
        return [], changes
    if not isinstance(raw, (list, tuple)):
        changes.append("deps: 不是列表 ⇒ 按'没有依赖'读（不猜）")
        return [], changes
    groups_raw = list(raw)
    flat = all(isinstance(g, Mapping) for g in groups_raw)
    if flat:
        groups_raw = [groups_raw]
        changes.append("deps: 一维列表 ⇒ 包成一条路径（外层 = 可选路径）")
    groups: list[list[dict[str, Any]]] = []
    for grp in groups_raw:
        if not isinstance(grp, (list, tuple)):
            if isinstance(grp, Mapping):
                grp = [grp]
            else:
                changes.append("deps: 有一层不是列表（跳过这一层，不猜）")
                continue
        steps: list[dict[str, Any]] = []
        for st in grp:
            if not isinstance(st, Mapping):
                changes.append("deps: 有一步不是对象（跳过这一步，不猜）")
                continue
            step: dict[str, Any] = {}
            for k, v in dict(st).items():
                key = str(k)
                if key not in STEP_KEY_ALIASES and key not in (
                        "stmt_id", "experiment_id", "lit_id", "doc_id", "kind", "label", "quote"):
                    hits = [canon for canon, alts in STEP_KEY_ALIASES.items() if key in alts]
                    if len(hits) != 1:
                        step[key] = v
                        continue
                    changes.append(f"deps[].{key} → {hits[0]}")
                    key = hits[0]
                step[key] = v.strip() if isinstance(v, str) else v
            steps.append(step)
        groups.append(steps)
    return groups, changes


def _dep_label(step: Mapping[str, Any]) -> str:
    """一步依赖没给标签时，用"来源种类:号"顶一格（`Dependency.validate` 要求非空）。

    刻意不写人话标签：这一步的语义（它是哪条定理）只有 B 知道，
    替它编一个名字等于把"没写"变成"写了"。
    """
    for key, prefix in (("source_stmt_id", "stmt"), ("source_experiment_id", "exp"),
                        ("source_lit_id", "lit"), ("source_doc_id", "doc")):
        if str(step.get(key) or "").strip():
            return f"{prefix}:{step[key]}"
    return "依赖"


def _deps_missing_reading(*, proof_text: Any, deps_written: int,
                          derived_from: Any = (), stmt_id: str = "",
                          proof_no: int = 0, scan: Mapping[str, Any] | None = None) -> dict:
    """这一行"带证明正文、却一条依赖都没落"时的三态读数（`state` 只有三档）。

    为什么需要这一格（真机 sylow3，2026-10-24）：七条命题各自带 2700 到 6300 字的证明，
    而 `dependencies` 全表 0 行 —— 证明里写的是中文散文式的"引理 1 / 引理 4"，
    引用扫描只认 `stmt:` / `lit:` / `exp:` / `doc:` 四种前缀，于是一条都扫不出来，
    `deps_state="none_in_proof"`、`deps_written=0`。这两个读数都只活在这一次调用的
    返回值里，收工门不数 `dependencies`、读侧也没有一格问过这件事 ⇒ 依赖面 0 行
    是静默的，C 的"按依赖面追几条不同证明路径"因此无从谈起。

    三态（不猜）：
    :data:`DEPS_MISSING_PRESENT` —— 落了至少一条依赖，依赖面建起来了；
    :data:`DEPS_MISSING_ABSENT` —— 带证明正文而零依赖。两条子因分开写：
        `derived_from` 非空 ⇒ 依赖信息其实在盘上的另一处（命题行的 `derived_from`），
        只是没落成 `dependencies` 行；`derived_from` 也空 ⇒ 证明正文里确实没有一条
        在册引用（自足证明合法，但读的人要能看出"扫了、确实是空"）；
    :data:`DEPS_MISSING_NOT_APPLICABLE` —— 这一行没有证明正文（概念行 / 还没写证明），
        依赖面这一格不适用。
    """
    text = str(proof_text or "")
    chars = len(text.strip())
    derived = [str(x) for x in (derived_from or ())]
    refs = int((scan or {}).get("refs") or 0)
    out: dict[str, Any] = {
        "state": DEPS_MISSING_NOT_APPLICABLE,
        "stmt_id": str(stmt_id or ""),
        "proof_no": int(proof_no or 0),
        "proof_chars": chars,
        "deps_written": int(deps_written or 0),
        "scanned_refs": refs,
        #: 依赖信息的另一处落点（命题行的 `derived_from`）：它非空而依赖表 0 行，
        #: 就是"信息在盘上、依赖面没建起来"的那一档。
        "derived_from": derived,
        "why": "",
        "next_step": "",
    }
    if chars <= 0:
        out["why"] = ("这一行没有证明正文（概念行 / 还没写证明）⇒ 依赖面这一格不适用"
                      "（既不是「缺依赖」，也不是「依赖为零」）")
        return out
    if int(deps_written or 0) > 0:
        out["state"] = DEPS_MISSING_PRESENT
        out["why"] = f"这一行落了 {int(deps_written)} 条依赖，依赖面建起来了"
        return out
    out["state"] = DEPS_MISSING_ABSENT
    if derived:
        out["why"] = (
            f"这一行有 {chars} 字证明正文，却一条 `dependencies` 行都没有；"
            f"而它的 `derived_from` 点名了 {derived} —— 依赖信息在盘上的另一处，"
            "没有落成依赖边（依赖表里读不到，按依赖面追证明路径的人就看不到）")
        out["next_step"] = (
            "把这些号写成依赖边：`B.register_statement` 交 `derived_from` 的同时"
            "把证明里的引用写成 `stmt:NNNNNN`（扫描只认带前缀的写法），"
            "或由 G 走 `doc.register_dependency` 逐条登记")
    else:
        out["why"] = (
            f"这一行有 {chars} 字证明正文，而引用扫描一条在册引用都没扫到"
            f"（扫了 {refs} 条）⇒ 依赖表 0 行。自足的证明合法，但「扫了、确实是空」"
            "与「没扫」必须分开读：`deps_state` 给的就是这个三态")
        out["next_step"] = (
            "如果这份证明其实引用了在册的命题 / 文献 / 实验，请把引用写成带前缀的样子"
            "（`stmt:` / `lit:` / `exp:` / `doc:`）再交一次，或在证明正文里逐条点名；"
            "如果它确实自足，这一格就是如实的「零依赖」")
    return out


def _resolve_dep_steps(groups: Iterable[Iterable[Mapping[str, Any]]],
                       tx: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """把二维列表解析成可落盘的一步一行（只读：解析完再决定写不写）。

    返回 `(steps, missing)`：`steps` 每项带 `path_group`（外层下标，从 1 起）与那一个来源字段；
    `missing` 是"这一步落不了"的那些（给出为什么），非空 ⇒ 调用方整笔不写。
    三态：`missing` 不是空的时候，不许退化成"少写一条边就算了" ——
    依赖图上少一环没有任何地方会报错（这正是 `draft/97` §13.3 要堵的形态）。
    """
    steps: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    for gi, grp in enumerate(groups, start=1):
        for st in grp:
            #: 组号：这一步自己带了 `path_group` 就用它（多证明清单那一档里
            #: "一份证明 = 一条可选路径"，组号就是证明号）；没带就用它在二维列表里
            #: 的位置 —— 老写法（`deps` / `proof_paths`）的读数因此逐字不变。
            try:
                group_no = int(st.get("path_group") or 0) or gi
            except (TypeError, ValueError):
                group_no = gi
            found = [(key, field, table, idf, dkind)
                     for key, field, table, idf, dkind in STEP_SOURCE_KEYS
                     if str(st.get(key) or "").strip()]
            if len(found) != 1:
                missing.append({"path_group": group_no, "step": dict(st),
                                "why": ("一步依赖必须恰好给一个来源（stmt_id / "
                                        "experiment_id / lit_id / doc_id 四选一）")})
                continue
            key, field, table, idf, dkind = found[0]
            sid = str(st[key]).strip()
            if tx.find(table, **{idf: sid}) is None:
                missing.append({"path_group": group_no, "step": dict(st),
                                "why": f"{table} 表里没有 {idf}={sid!r}"})
                continue
            kind = str(st.get("kind") or dkind)
            if kind not in S.DEP_KINDS:
                missing.append({"path_group": group_no, "step": dict(st),
                                "why": f"kind 必须是 {S.DEP_KINDS} 之一，收到 {kind!r}"})
                continue
            step = {"path_group": group_no, "kind": kind, "label": str(st.get("label") or ""),
                    "quote": str(st.get("quote") or "")}
            #: 这一步属于第几份证明（多证明清单那一档才会带）：不往这里搬的话，
            #: `_write_dep_steps` 只能按 `body["proof_no"]` 落 `used_by`，
            #: 于是 #p2 / #p3 的依赖会全被记到 #p1 名下（依赖面又混成一维）。
            try:
                step_no = int(st.get("proof_no") or 0)
            except (TypeError, ValueError):
                step_no = 0
            if step_no >= 1:
                step["proof_no"] = step_no
            step[field] = sid
            steps.append(step)
    return steps, missing


def _concept_statement(c: Mapping[str, Any], *, stmt_id: str, doc_id: str,
                       actor: str) -> Any:
    """一个概念 ⇒ 一条 `statements` 行 —— 转发到唯一构造口 `conceptrows`。

    这一格此前是本文件里的第二份实现（与并表过渡层那份同口径）：留着两份，
    "定义待补落哪一档"就会有两处可改，而它们漂了不会有任何地方红。
    现在只有 `conceptrows.concept_statement` 一处（本函数是薄转发，保住既有调用点）。
    """
    from . import conceptrows as CR   # 惰性：并表过渡层的唯一读写口

    return CR.concept_statement(stmt_id=stmt_id, label=str(c.get("name") or ""),
                                definition=str(c.get("definition") or ""),
                                aliases=c.get("aliases") or (),
                                source_lit_id=str(c.get("source_lit_id") or ""),
                                proof_text=str(c.get("proof_text") or ""),
                                doc_id=doc_id, actor=actor)


class Secretary:
    """一名智能体的秘书（`draft/53` v3 §4：一个共享类 + 每角色一个实例）。

    参数
    ----
    role : 它服务的那名智能体（`"M"` / `"A"`…/`"V"`）。台账按它分文件。
    root : 工作区根（手稿通道与台账都挂在它下面）。
    store : 可选的 `Store`（只读：`tasks` / 会话事件）。给了就读，不给就跳过那一层读数。
    registry : 可选的工具注册表（只读：判"工具名是不是真名"）。
    seam : 可选的 `LlmSeam`（用本智能体自己的缝，`scope="secretary"`）；不给 ⇒ 判断那一格判不了
        （`judge()` 返回 `checked=False`），预筛与留痕照常。生产装配把它打开是一行的事
        （`Secretary(..., seam=<本体的缝>, enable_model=True)`）。
    enable_model : 要不要用模型做"判断"（见 :meth:`judge`）。默认 False：确定性预筛是机器该做的，而
        "要不要为此花钱"是一次明确的取舍（`P-09` 的粒度）；生产装配把它打开是一行的事。
    log : 可选日志口子（失败留痕的第二个落点）。
    写集只有两格（业主 2026-10-09：「写入侧应该都是B的活，让B的秘书帮它洗格式、拿编号、改表、查重…B 纯粹
    负责消化理解」）：`statements` 与 `dependencies` —— 都只经 :meth:`record_statement` 一处（B 交内容、秘书
    落盘）；它不写别的库表、不改任何受保护文件。两类产物分得很清（这是本项目最忌的那种折平）：
    | 类 | 判据 | 形态 | 例子 |
    |---|---|---|---|
    | 预筛 | 确定性、来自既有声明 | 报警清单（字符串） | 参数缺必填 / 工具名不是真名 / 动作不在能力表 |
    | 判断 | 需要语义、"该不该" | :meth:`judge` 一次模型调用 + 台账 | 重复候选算不算正当重试 / 错名映到哪个 / 建议重排成什么 |
    """

    def __init__(self, role: str, *, root: str | Path, store: Any = None,
                 registry: Any = None, seam: Any = None, log: Any = None,
                 deadline_sec: float = DEFAULT_DEADLINE_SEC,
                 enable_model: bool = False, sid: str | None = None,
                 same_proposition_jaccard: float = SAME_PROPOSITION_JACCARD,
                 proof_same_jaccard: float = PROOF_SAME_JACCARD) -> None:
        self.role = str(role)
        self.root = Path(str(root))
        self.store = store
        self.registry = registry
        self.seam = seam
        self.log = log
        self.deadline_sec = float(deadline_sec)
        #: 同一命题 / 同种证明的两个阈值（业主 2026-10-24）。可注入的理由：这两条判据的
        #: 松紧是口径问题，不是实现问题 —— 不同工作区的表述习惯不同（sylow3 那种带
        #: 长尾注的登记与短句式的登记），阈值该能被一次实验性调参改掉，而不必改代码。
        self.same_proposition_jaccard = float(same_proposition_jaccard)
        self.proof_same_jaccard = float(proof_same_jaccard)
        #: 会话号（花销归因要读 `llm_call` 事件；`None` = 缺省会话，与 `llmseam` 同一口径）。
        self.sid = sid
        #: 判断类要不要真发一次模型调用（`draft/53` §12 / `draft/55` §5.2）。
        #: 关着的时候 :meth:`judge` 仍然返回三态中的"没查成"（`checked=False` + 理由），
        #: 于是"判断没做"与"判断过了、可派"在台账上永远分得开。
        #:
        #: 生产装配由 `agent_loop._secretary_for` 打开它（主控裁定 A5）。
        #: 2026-10-14 起那一口还会按业主的裁定换一把 key：设置文件里配了
        #: `secretary` 档 ⇒ 秘书走全角色共用的那一档模型
        #: （`llmseam.LlmSeam.for_secretary`）；没配 ⇒ 退回本体那一个缝。
        self.enable_model = bool(enable_model)
        #: 秘书这一趟的模型是从哪一档来的（读数：`secretary（…）` / `body（…）`）。
        #: 它回答"这次判断花的是共用那把 key，还是本体那把" —— 而这正是
        #: 「所有智能体的秘书另外共用一个 api key」这条裁定生效与否的唯一机器读数。
        self.model_source: str = ""
        #: 写集的声明式落点：它让"秘书有没有写集、写哪几张表"成为一个可读的事实，
        #: 而不是"读遍本文件找不到 store.tx 所以大概没有"。
        #: 2026-10-09 起不是空集：B 的写入代理要落 `statements`（含概念行）与
        #: `dependencies`（业主那两句裁定），只走 :meth:`record_statement` 一处。
        self.writes: frozenset[str] = frozenset(STATEMENT_WRITE_TABLES)
        self._negotiations: list[dict[str, Any]] = []
        #: 这个秘书服务的实例（台账号）。由 `bind_task` 在循环开跑时绑上（S1m）：
        #: 绑上之后台账分片到 `out/secretary/<role>-<task_id>.jsonl`，于是同角色的并发实例
        #: 各写各的片（今天只有角色维度 ⇒ 两个 D 实例会把记录写进同一个文件，读的人分不出是谁）。
        self.task_id: str = ""
        #: 最近一次判断的墙钟（秒）与最近一次闭环该不该介入的读数 —— 都是读数，
        #: 不是判据（fail-open 的代价要看得见，但不许拿它去卡任何一条委托）。
        self._last_judge_elapsed = 0.0
        self._last_closure_engage = False
        #: 入库审美的同题不重判表（2026-10-14 第五趟真机读数）。
        #:
        #: 真机上同一份 `statement_full`（21 字）被提交了 6 次：每一次都真的发了一次
        #: 模型调用、都得到同一个「太平凡」，而一次 run 因此烧掉 20/26 次调用与 $0.226，
        #: 最后 `statements` 仍是 0 行。判断的对象只有那段文本（加一句自证不平凡的说明），
        #: 所以同一份文本问第二遍不会有别的结论 —— 记下来，省掉那几次调用，也让"再交一遍"
        #: 这件事在读数上立刻变便宜且答案不变（于是没有理由反复试）。
        #:
        #: 键 = `(statement_full, why_this_is_not_trivial)` 的摘要；值 = 第一次的结论。
        #: 只记 `checked=True` 的结论：没查成（没缝 / 超时 / 坏 JSON）不许缓存 ——
        #: 那会把"这一次没查成"变成"以后都别查了"，而缝是可能好起来的。
        self._statement_verdicts: dict[str, dict[str, Any]] = {}
        #: 命题同一性的同题不重判表（业主 2026-10-24：「让秘书洗定理名，让秘书判」）。
        #:
        #: 键 = 命题正文的 sha256（见 `_proposition_verdict_key`）；值 = 第一次的判定。
        #: 这一层只是进程内的快表：盘上那份 append-only 台账
        #: （`out/secretary/proposition_verdicts.jsonl`，见 `proposition_verdict_of`）才是
        #: 跨进程/跨趟的缓存 —— 没有盘上那一份，"同一条正文第二次进来不再花钱"这句话只在
        #: 同一个秘书实例活着的时候成立。
        self._proposition_verdicts: dict[str, dict[str, Any]] = {}

    # ------------------------------------------------------------ 台账（E 类：记录）

    def bind_task(self, task_id: str) -> None:
        """把这一名秘书绑到它服务的实例上（S1m）。绑上之后台账分片。

        为什么必须有这一步：秘书的台账先前只有角色维度
        （`out/secretary/<role>.jsonl`），而同角色的并发实例（`summon_many` 的多 `instance`）
        会写进同一个文件 —— 读的人分不出哪一行是哪一个代理写的（`draft/91` §7 的 D106）。
        绑定之后每一实例一片（`<role>-<task_id>.jsonl`），一个写者一片。
        同时写一份存活标记（`secretary_alive` 读它）——"与它同生同死"的第一半。
        """
        self.task_id = str(task_id or "")
        if not self.task_id:
            return
        try:
            path = self.decisions_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            alive = self.alive_path()
            alive.write_text(json.dumps({"role": self.role, "task_id": self.task_id,
                                         "pid": __import__("os").getpid(),
                                         "at": _now_iso()}, ensure_ascii=False, default=str) + "\n",
                             encoding="utf-8", newline="\n")
        except OSError as exc:  # 留痕失败不许带走这一趟（但也不静默）
            self._log(f"秘书存活标记没写成：{type(exc).__name__}: {exc}")

    def close(self) -> dict[str, Any]:
        """收尾：注销存活标记，返回读数（"同生同死"的第二半）。失败也如实报。"""
        out: dict[str, Any] = {"checked": True, "closed": False, "reason": "", "task_id": self.task_id}
        if not self.task_id:
            out["checked"] = False
            out["reason"] = "这一名秘书没绑定实例（没有分片、也没有存活标记）"
            return out
        try:
            self.alive_path().unlink(missing_ok=True)
            out["closed"] = True
        except OSError as exc:  # 删不掉不影响"这一趟结束了"这个事实，但要留痕
            out["reason"] = f"{type(exc).__name__}: {exc}"
            self._log(f"秘书存活标记没删掉：{out['reason']}")
        return out

    def alive_path(self) -> Path:
        """存活标记的路径（按实例分片，与台账同一命名规则）。"""
        return Path(str(self.decisions_path()) + ".alive")

    def secretary_alive(self) -> dict[str, Any]:
        """这一名秘书"还活着吗"（三态）：`{"checked","alive","pid","at","reason"}`。

        口径：标记在 = 绑过；`pid` 还活着 = 真的在跑（进程死了但标记还在 ⇒
        `alive=False` 且 `stale=True`，"上次没善终"是看得见的事实）。读不到标记 ⇒
        `checked=False`（"没查成"与"没绑过"分开）。
        """
        out: dict[str, Any] = {"checked": False, "alive": False, "pid": 0, "at": "",
                               "stale": False, "reason": ""}
        try:
            raw = self.alive_path().read_text(encoding="utf-8")
        except FileNotFoundError:
            out["checked"] = True
            out["reason"] = "没有存活标记（没绑过实例，或已经注销）"
            return out
        except OSError as exc:
            out["reason"] = f"{type(exc).__name__}: {exc}"
            return out
        try:
            got = json.loads(raw.strip().splitlines()[0])
        except Exception as exc:  # noqa: BLE001 —— 标记坏了 = 没读成，不许折成"死"
            out["reason"] = f"标记读不成：{type(exc).__name__}: {exc}"
            return out
        out["checked"] = True
        out["pid"] = int(got.get("pid") or 0)
        out["at"] = str(got.get("at") or "")
        out["alive"] = _pid_alive(out["pid"])
        out["stale"] = not out["alive"]
        return out

    def decisions_path(self, task_id: str | None = None) -> Path:
        """这一名秘书的台账路径（S1m 起分片）：绑了实例 ⇒ 分片，没绑 ⇒ 老文件。

        `task_id` 显式给了就用它；不给就用 `self.task_id`（`bind_task` 绑的那个）。
        """
        return decisions_path(self.root, self.role, task_id if task_id is not None else self.task_id)

    def decisions(self) -> list[dict[str, Any]]:
        """本角色台账里的全部行（坏行读不出来 ⇒ 如实报，不折成"没有决定"）。

        `read_jsonl` 把坏行单独报出来；这里只交回行，坏行由 :meth:`decision_problems` 报。
        口径（S1m）：老文件 + 本实例分片（绑了才读第二份）—— 这是"这一名秘书"的视角；
        整角色的合并视图是 `merged_decisions`（WebUI 直接 glob 目录，读得到全部片）。
        """
        return self._read_ledger()[0]

    def merged_decisions(self) -> list[dict[str, Any]]:
        """整角色视图：老文件 + 全部 `<role>-*.jsonl` 分片（按 `at`/`seq` 排序）。

        为什么要它：分片之后"这个角色的秘书都决定过什么"需要一处读侧
        （`knowledge()` 与 WebUI 那一面都靠它），否则读的人会以为"分片 = 记录变少了"。
        坏行照样只报不折。
        """
        from . import jsonlfile as JF

        rows: list[dict[str, Any]] = []
        base = Path(self.root).joinpath(*SECRETARY_DIR)
        paths = []
        for name in (f"{self.role}.jsonl", *(p.name for p in
                                            sorted(base.glob(f"{self.role}-*.jsonl")))):
            p = base / name
            if p.is_file() and p not in paths:
                paths.append(p)
        for p in paths:
            got, _bad = JF.read_jsonl(p)
            rows.extend(got)
        rows.sort(key=lambda r: (str(r.get("at") or ""), int(r.get("seq") or 0)))
        return rows

    def decision_problems(self) -> list[str]:
        """台账里的坏行说明（空列表 = 全都读得出来）。"""
        return self._read_ledger()[1]

    def _read_ledger(self) -> tuple[list[dict[str, Any]], list[str]]:
        from . import jsonlfile as JF

        rows, problems = JF.read_jsonl(decisions_path(self.root, self.role))
        if self.task_id:
            got, bad = JF.read_jsonl(self.decisions_path())
            rows = rows + got
            problems = problems + bad
        return rows, problems

    def note_decision(self, *, duty: int, kind: str = KIND_DECISION, decision: str = "",
                      reason: str = "", basis: Sequence[str] = (), target: Any = None,
                      before: str = "", after: str = "", mid: str = "",
                      changes: Sequence[Mapping[str, Any]] = (),
                      negotiation: Sequence[Mapping[str, Any]] = (), fail_open: bool = False,
                      error: str = "", judge: Mapping[str, Any] | None = None,
                      proposal: str | None = None,
                      fingerprint: str = "") -> dict[str, Any]:
        """追加一行台账（`draft/55` §5.3 的字段表）。

        原文与加工后并列（`before` / `after`）：只留结论会让复核无从下手 —— "过程"是这一层唯一能自证的东西。
        `changes`（S1g）：逐格写"洗了什么"（`[{"field","from","to","why"}]`）。只留 `before`/`after` 两份全文也能
        diff 出来，但"哪几格是秘书动的"必须一眼可读 —— 否则"模型写错了"与"秘书替它补对了"在纸上长得一样
        （`draft/90` §1.2）。`proposal`（两段式）：三态，不许折平 ——
        | 值 | 这一行是什么 | `proposal_id` 那一格 |
        |---|---|---|
        | `None`（默认） | 普通台账行（老行为逐字不变，不多一个键） | 不写 |
        | `""` | 一条新请示 ⇒ 编号由本秘书在锁内发（与这一行的 `seq` 同源） | `W-<role>-<task>-<seq>` |
        | `"<id>"` | 确认/拒绝那一行 ⇒ 指向原来那条请示 | 原样记 `"<id>"` |
        为什么编号必须在这里发（而不是调用方拼）：见 :func:`_append_locked` 的 docstring —— 拼号都在锁外取值，
        并发下重号的请示意味着"接受 A 的编号、执行 B 的洗"。`fingerprint`（两段式）：这一行是对哪一份载荷发的
        （12 hex），它让"接受/拒绝"那一步在台账里就能核"这个编号是不是对这份载荷发的" —— 不给的话，接受方可以
        拿 A 的编号去确认 B 的载荷。空串 = 不写这一格（老行逐字不变）。写入走 `append_jsonl`（S1m）：锁内算
        `seq`、进程内 + 跨进程两层锁；旧写法（先读全表算 `seq`、再裸 `open("a")`）在并发下会重号（D107）。
        """
        rec: dict[str, Any] = {
            "at": _now_iso(),
            "role": self.role,
            "task_id": self.task_id,
            "duty": int(duty),
            "kind": str(kind or KIND_DECISION),
            "from": f"secretary/{self.role}",
            "fail_open": bool(fail_open),
        }
        if target is not None:
            rec["target"] = target
        if before:
            rec["before"] = str(before)
        if after:
            rec["after"] = str(after)
        if decision:
            rec["decision"] = str(decision)
        if reason:
            rec["reason"] = str(reason)
        if basis:
            rec["basis"] = [str(x) for x in basis]
        if negotiation:
            rec["negotiation"] = [dict(x) for x in negotiation]
        if changes:
            # S1g：逐格写"秘书动了哪几格"。只留 before/after 两份全文也能 diff，
            # 但读的人要的是"哪几格是秘书动的"（否则模型写错与秘书补对分不开）。
            rec["changes"] = [dict(x) for x in changes]
        if judge is not None:
            # 判断类的那一格：`checked` / `decision` / `reason` 一起落台账 ——
            # 只落结论会让"没查成"与"查过了没问题"在纸上长得一样。
            rec["judge"] = dict(judge)
        if mid:
            rec["mid"] = str(mid)
        if error:
            rec["error"] = str(error)
        if fingerprint:
            rec["proposal_fingerprint"] = str(fingerprint)
        path = self.decisions_path()
        resolved = str(proposal or "")
        if proposal == "":
            # 新请示：编号在锁内发（与写这一行同一个临界区）⇒ 发号与落行不可能分叉。
            ok, problem, resolved = append_jsonl_stamped(
                path, rec, field="proposal_id", prefix=self.proposal_prefix())
            if resolved:
                rec["proposal_id"] = resolved
            else:
                self._log(f"秘书台账没发成号（请示没有编号）：{problem}")
        else:
            if resolved:
                rec["proposal_id"] = resolved
            ok, problem = append_jsonl(path, rec)
        if not ok:
            # 台账写不成不许带走秘书的判断（fail-open 的第一层：留痕是手段不是目的）。
            # 但也不静默：日志口子与返回值两条路都留下这件事。
            self._log(f"秘书台账没写成：{problem}")
            rec["ledger_problem"] = problem
            if resolved:
                rec["proposal_id"] = resolved
            return rec
        # 写成了：把锁内定的 `seq` 读回来（`append_jsonl` 返回的是"写成没写成"；
        # 这里再读一次只为把 `seq` 放进返回值 —— 与旧行为对齐，读侧仍然只认盘上的那一行）。
        rows, _bad = self._read_ledger()
        for row in reversed(rows):
            if (str(row.get("at") or "") == str(rec.get("at") or "")
                    and str(row.get("kind") or "") == str(rec.get("kind") or "")):
                rec["seq"] = int(row.get("seq") or 0)
                break
        return rec

    # ------------------------------------------------------------ 知识面（只读，§1）

    def knowledge(self) -> dict[str, Any]:
        """秘书能读什么（全部只读，`draft/55` §1）。

        四层：硬性要求 / 全角色的定位（组织图全开）/ 委托事实 / 读数。
        返回一个可读的事实表（不是权限授予）：`writes` 恒为 `∅`，
        `reads_narrative` 回答"它读不读研究叙事正文"（一般角色不读、V 更严）。
        """
        briefs: dict[str, dict[str, Any]] = {}
        emphasis: dict[str, Any] = {}
        # 业主 2026-10-22（「在Lean开关没开时隔绝L」）：这份事实表是读数面，
        # 开关关着时不存在的角色不许在这里留一行（"存在但没用到"正是要去掉的噪音）。
        # 判定读 `leanscope`（唯一入口），这里只过滤。
        from . import leanscope as _LEANSCOPE

        _visible = _LEANSCOPE.visible_roles(S.ROLES)
        for role in _visible:
            one = self._role_brief(role)
            if one:
                briefs[role] = dict(one)
        actions = self._action_table()
        return {
            "roles": sorted(set(_visible) | {S.CONDUCTOR_ROLE}),
            "briefs": briefs,
            "emphasis": emphasis,
            "actions": actions,
            "tools": self._tool_names(),
            "writes": self.writes,
            "reads_narrative": False,
            "ledger": str(decisions_path(self.root, self.role)),
            #: S1m 的两格：绑过实例 ⇒ 分片路径非空（"我这一名秘书"的账在这儿）；
            #: `ledger_legacy` 是历史那一份（老工作区里全部决定都在它里面）。
            #: 三格都给，是因为分片之后"这个角色的账在哪"必须读得出来（否则读侧会以为记录变少了）。
            "ledger_instance": str(self.decisions_path()) if self.task_id else "",
            "ledger_legacy": str(decisions_path(self.root, self.role)),
        }

    def may_read_narrative(self, role: str) -> bool:
        """本秘书能不能读 `role` 的叙述（研究数据面，不是定位面）。

        `draft/55` §1.5 ②：一般角色的秘书"数据面 ≤ 本体"；而 V 的秘书另有更严的
        隔离 —— 不读 F 的叙述、不读被审证明之外的上下文。理由逐字：
        I12 靠"冷启动不给 store 句柄、不给 F 的叙述"保证审校独立性 ⇒ 若 V 的秘书
        读全库（含 `handoffs` 正文、会话叙事），它就成了绕过 I12 的暗通道。

        本方法只回答"读不读得到"，不回答"读了要不要用" —— 后者是判断。
        """
        want = str(role or "")
        if self.role == "V":
            return False
        return want == self.role

    def _role_brief(self, role: str) -> Mapping[str, Any]:
        """某角色的六字段 brief（`agent_prompts.ROLE_BRIEFS` 真身；读不到 ⇒ 空表）。

        这里读的是定位（岗位定义），不是研究数据 —— 组织图对每名秘书全开
        （用户 2026-10-06 口径），而数据面另有约束（见 :meth:`may_read_narrative`）。

        `ROLE_BRIEFS` 的值是 `agent_prompts.RoleBrief`（dataclass，不是 Mapping）；
        两种形态都收，因为"它是 dataclass"是实现细节，而秘书要的是那六个字段。
        """
        try:
            from . import agent_prompts as AP

            got = (AP.ROLE_BRIEFS or {}).get(str(role))
        except Exception:  # noqa: BLE001 - 读不到定位不该让整条委托过不去
            return {}
        return _as_mapping(got)

    def _all_briefs(self) -> dict[str, dict[str, Any]]:
        """全部角色的 brief（组织图全开；读不到就空表 —— 空表 ≠ 没有角色）。"""
        try:
            from . import agent_prompts as AP

            table = AP.ROLE_BRIEFS or {}
        except Exception:  # noqa: BLE001 - 同上
            return {}
        out: dict[str, dict[str, Any]] = {}
        for role, got in dict(table).items():
            one = _as_mapping(got)
            if one:
                out[str(role)] = one
        return out

    def _action_table(self) -> dict[str, list[str]]:
        """每个角色声明了哪些动作（`capabilities.CAPABILITIES`：`{角色: (ActionSpec,…)}`）。"""
        out: dict[str, list[str]] = {}
        try:
            from . import capabilities as C

            table = getattr(C, "CAPABILITIES", None) or {}
            for role, specs in dict(table).items():
                names = [str(getattr(s, "action", "") or "") for s in specs]
                out[str(role)] = sorted({n for n in names if n})
        except Exception:  # noqa: BLE001 - 读不到声明 ⇒ 空表（"没读到"不许读成"没有动作"）
            return {}
        return out

    def _tool_names(self) -> list[str]:
        """注册表里的真名（判"工具名写错了没有"的唯一依据）。

        ## 口径：预筛的准确度取决于装配时给它的那份注册表：秘书只用已有声明判（注册表的真名 +
        `specs/<role>.py` 的参数表），不新增机器判据（`draft/55` §4）。所以"这份真名表全不全"直接决定预筛
        对不对：给错一份残缺的注册表，就会把真名报成"不是真名"（假阳性）。
        ## 为什么 fallback 必须带 `store`（2026-10-04 主控探针实测的缺陷）：没有 `registry` 时的 fallback 原先
        是 `build_registry()` —— 不带 `store`。实测：`build_registry()` 出 68 件真名且 `fs.read` 不在里面；
        `build_registry(store=...)` 出 81 件、`fs.read` 在里面。于是任何 `registry=None` 的调用方
        （`for_role(..., registry=None)` 是默认）都会对 `fs.read` 这种真名报警
        `'fs.read' 不是注册表里的真名；并列候选：['manuscripts.read','table.create']`
        （真名被判成错名 ⇒ 预筛的第一类假阳性，而 `self.store` 就在手边）。三态：`store` 也没有 ⇒ 保持
        "造不出来就给空表"的老行为（`[]`），空表在调用方那一侧只能是"没读到"，不许读成"没有真名"。
        """
        if self.registry is not None:
            try:
                return sorted(str(x) for x in self.registry.names())
            except Exception:  # noqa: BLE001 - 注册表坏了不该让委托过不去
                return []
        if self.store is None:
            # 空表在这里只有一个含义：这一格没读成（不是"没有真名"）。
            # 调用方 `prescreen` 只在真名表非空时才判错名 ⇒ 空表绝不会被读成
            # "这些名字都不存在"，所以这不是把"没做"折叠成"没有"。
            return []
        try:
            from .tools import build_registry

            return sorted(str(x) for x in build_registry(store=self.store).registry.names())
        except Exception:  # noqa: BLE001 - 造不出来 ⇒ 空表（"没读到"不许读成"没有真名"）
            return []

    # ------------------------------------------------------------ 机器预筛（§6）

    def prescreen(self, *, to: str, action: str, params: Mapping[str, Any],
                  tool: str = "") -> list[str]:
        """确定性预筛：返回"报警"清单（空 = 没有报警）。

        判据全部来自已有声明（`specs/<role>.py` 的参数表 / 注册表的真名），
        这里不新造机器判据（`draft/55` §4 末：秘书不新增机器判据）。
        它是"要不要叫秘书"的输入，不是判决 —— 报警之后仍然由秘书判断。
        """
        alarms: list[str] = []
        want_role = str(to or "")
        # 职责 2 的前提是读得到收件方的定位（`draft/55` §1.2：组织图全开）。
        # 读不到 ≠ 没问题：空 brief 与"这个角色没定位"是两件事，如实报成"这一格判不了"。
        if want_role and not self._role_brief(want_role) and self._all_briefs():
            alarms.append(f"读不到 {want_role} 的角色定位 ⇒ 『收件方真做得到吗』这一格判不了"
                          "（没读成不是没问题）")
        table = self._action_table()
        # 2026-10-16（业主口径 S2「M 只派活」）：`action` 为空时跳过这一条。
        # 空动作 = 派一件活、由被派者自己选动作 ⇒ 没有动作可核；照旧核就会报警
        # "{角色} 的动作表里没有 ''"，于是那条派活被吞掉。真机读数（T5 第 12 趟 `p8l`）：
        # M 六次发出 `{"role":"A","action":"","task":…}`，而 `tasks` 表里空动作的行
        # = 0 —— 六次全死在这一行；M 于是退回"点名动作+自己写参数"，那一趟 12 条被拒。
        # 其他地方同一套改法见 `policy.check` 第 [1] 步与 `LlmBackend.call`。
        if (str(action) and table and want_role in table
                and str(action) not in table.get(want_role, [])):
            close = declarations_candidates(str(action), table.get(want_role, []))
            alarms.append(f"{want_role} 的动作表里没有 {action!r}"
                          + (f"；并列候选：{close}" if close else ""))
        if tool:
            names = self._tool_names()
            if names and str(tool) not in names:
                close = declarations_candidates(str(tool), names)
                alarms.append(f"{tool!r} 不是注册表里的真名"
                              + (f"；并列候选：{close}" if close else ""))
        alarms += self._required_alarms(want_role, str(action), params)
        return alarms

    def _required_alarms(self, role: str, action: str, params: Mapping[str, Any]) -> list[str]:
        """必填字段：按 `specs/<role>.py` 的参数表核。

        三态（R002 的口径）：读不到参数声明不是"没有必填参数" —— 前者是"这一格
        判不了"，所以它返回一条 alarm，而不是空列表。空列表只有一个含义：读到了
        声明、而且必填项一个不缺。
        """
        problem = ""
        try:
            from . import capabilities as C

            # 2026-10-16（业主口径 S2）：`action` 为空时这一格不适用、不算报警 ——
            # 没有动作就没有"参数声明"可读，报警会让"只派活"那一路整条被判成"判不了"。
            # 真机/判据现场：`test_the_secretary_washes_the_format_face` 的读数逐字是
            # `读不到 E. 的参数声明（能力表里没有这个动作）⇒ 必填这一格判不了`。
            spec = C.find_action(role, action) if str(action) else None
            if not str(action):
                return []
        except Exception as exc:  # noqa: BLE001 - 读不到声明 ⇒ 这一格判不了
            spec, problem = None, f"{type(exc).__name__}: {exc}"
        else:
            if spec is None:
                problem = "能力表里没有这个动作"
        if problem:
            return [f"读不到 {role}.{action} 的参数声明（{problem}）⇒ 必填这一格判不了"]
        props = dict(getattr(spec, "params", None) or {}).get("properties") or {}
        required = list(dict(getattr(spec, "params", None) or {}).get("required") or [])
        got = set(params or {})
        missing = [k for k in required if k not in got]
        if not missing:
            return []
        return [f"{role}.{action} 缺必填参数 {missing}（声明里的键：{sorted(props)}）"]

    def should_engage(self, *, alarms: Sequence[str], duplicates: int = 0,
                      overdue: int = 0, novel: bool = False) -> bool:
        """要不要叫秘书（`draft/53` §6：花销与问题量成正比，不与委托量成正比）。

        四条任一成立就叫：预筛报警 / 出现重复候选 / 闭环逾期 / 首次遇见该形态。

        它有真调用点（否则"按需介入"就是一句空话）：:meth:`optimize_outbound`、
        :meth:`assess_delegation`、:meth:`remind_closure` 三处都是先算这四个数、
        再由本方法决定要不要走 :meth:`judge`（一次模型调用）。四个数全不成立 ⇒
        确定性路径直接给结论，一次模型调用都不发。
        """
        return bool(alarms) or int(duplicates) > 0 or int(overdue) > 0 or bool(novel)

    #: 判断类（`draft/55` §2 的 B 类；用户口径"切勿全写死成机器判据"）。
    #:
    #: 从 `JUDGE_VERDICTS` 派生（不是另抄一份名单）：那一张表同时管着"这一类允许哪些结论"，
    #: 两处各写一份的话，"加了一类判断却忘了给它词表"会静默落进 `DECISIONS` 的校验里。
    JUDGE_KINDS = tuple(JUDGE_VERDICTS)

    def judge(self, kind: str, context: Mapping[str, Any], *, task_id: str = "") -> dict[str, Any]:
        """判断类：用本智能体自己的缝做一次模型调用，把结论落台账。

        判断类别（`draft/53` §10 的三条"改判给秘书"，加业主 2026-10-14 裁决第 12 条前半）：`duplicate_retry`
        （同 key 的既有终态行算重复还是正当重试）、`tool_name`（错名映到哪一个候选，或一个都不映）、
        `rearrange`（建议重排成什么，改派权仍在 M）、`statement_aesthetic`（B 的秘书专属：这条待入库的命题够不够
        格 —— 三态 `合格` / `太平凡` / `判不了`，词表见 :data:`STATEMENT_VERDICTS`）。每一类只认自己那张词表
        （:data:`JUDGE_VERDICTS`）：把"可派"填进审美那一栏，在这一层就被拒 —— 两根轴的结论混进同一栏是查不出来
        的那种错。三态（`R002`/P16 的口径）：
        | 结局 | 返回 |
        |---|---|
        | 判断做了 | `{"checked": True, "decision": …, "reason": …, "basis": […]}` |
        | 没缝 / 没开 / 超时 / 坏 JSON | `{"checked": False, "reason": …}` |
        "没查成"绝不被读成"可派"：调用方（:meth:`assess_delegation`）只在 `checked=True` 时才采信 `decision`。
        每一次真的发起过调用的结局都带 `cost`（见 :meth:`last_judge_cost`）："这次判断花了哪一笔钱"必须能从
        台账追回账本，否则它是一笔不可归因的花销。
        """
        if kind not in self.JUDGE_KINDS:
            return {"checked": False,
                    "reason": f"不认识的判断类别 {kind!r}（认 {list(self.JUDGE_KINDS)}）",
                    "cost": {"ledger": "", "reason": "没发调用（类别不认识）"}}
        if self.seam is None:
            return {"checked": False,
                    "reason": "没有装配模型缝（本智能体自己的 llmseam）⇒ 这一格没查成",
                    "cost": {"ledger": "", "reason": "没发调用（没有缝）"}}
        if not self.enable_model:
            return {"checked": False,
                    "reason": "enable_model=False（判断类的模型调用被显式关掉）⇒ 这一格没查成",
                    "cost": {"ledger": "", "reason": "没发调用（开关关着）"}}
        t0 = time.monotonic()
        try:
            # ---- 2026-10-21：稳定头进 system，材料留在 user（前缀缓存那一轴）
            #
            # 改前这里只有一条 user 消息（`ask_json(_judge_prompt(kind, context))`）：
            # 抬头 + 问题 + 材料全在同一格里，而材料每问一次都变 ⇒ 两趟之间的公共
            # 前缀只剩"抬头 + 问题"之前的那点字节，而它又不在 system 位上。真机实测
            # （2026-10-21，`scripts/warm_prompt_cache.py --roles secretary --hit-sample
            # secretary`）：连发两趟都是 `hit=0 / miss=175` —— 那 175 token 的稳定头
            # 一次都没进过索引。
            #
            # 现在：`_judge_system(kind)` 是逐字稳定的那一半（抬头 + 这一类自己的问题），
            # 走 `llmseam` 早就有的 `system=` 通道（`LlmSeam.ask` 的 `system` 参数，
            # `modelgw.ModelGateway.complete` 把它放进 messages 的第一条 `system` 位）；
            # `_judge_material(context)` 只装这一趟的材料。没有新造通道 ——
            # 十个角色的循环那条路（`agent_loop`）用的就是同一个参数。
            data, call = self.seam.ask_json(_judge_material(context),
                                            system=_judge_system(kind),
                                            task_id=task_id, note=f"secretary:{kind}")
        except Exception as exc:  # noqa: BLE001 - fail-open：超时/出错 ⇒ 没查成 + 留痕
            return self._record_judge(kind, context, {
                "checked": False, "reason": f"调用失败：{type(exc).__name__}: {exc}",
                "cost": self.last_judge_cost(kind)})
        finally:
            self._last_judge_elapsed = round(time.monotonic() - t0, 3)
        cost = self.last_judge_cost(kind)
        if not getattr(call, "ok", False) or data is None:
            return self._record_judge(kind, context, {
                "checked": False,
                "reason": f"没查成（{getattr(call, 'problem', '') or 'no_reply'}）："
                          f"{str(getattr(call, 'detail', '') or '')[:200]}",
                "cost": cost})
        decision = str(data.get("decision") or "").strip()
        allowed = JUDGE_VERDICTS[kind]
        if decision not in allowed:
            return self._record_judge(kind, context, {
                "checked": False,
                "reason": f"模型给的结论 {decision!r} 不在 {kind} 的词表 {list(allowed)} 里 ⇒ 不采信",
                "cost": cost})
        out = {
            "checked": True, "decision": decision,
            "reason": str(data.get("reason") or "")[:500],
            "basis": [str(x) for x in (data.get("basis") or [])][:5],
            "elapsed_sec": self._last_judge_elapsed, "cost": cost}
        if kind == "statement_aesthetic":
            # ---- 2026-10-23：档位是同一趟判断的第二个输出（业主 2026-10-21），
            # 而这一层此前把模型给的 `nontriviality` 丢掉了（只白名单了四格）⇒
            # `judge_statement` 永远读到 None、台账里永远落"判不了"。
            # 真机读数（r34 的 `out/secretary/nontriviality.jsonl`）：5 行全是
            # `nontriviality: 0` / `basis: ""` —— 那正是这条丢失的形态（"没人判过"
            # 与"判过但丢了"在盘上同形）。所以这里按类别把它放行，原样交给上层收敛。
            # 注意这里不做校验（收敛与三态在 `judge_statement` 一处做）：
            # 这一层只管"别把它丢了"。
            out["nontriviality"] = data.get("nontriviality", data.get("tier"))
            out["nontriviality_basis"] = str(data.get("nontriviality_basis") or "")[:500]
        if kind == "proposition_identity":
            # ---- 2026-10-24：同一趟判断的第二组输出（业主：让秘书洗定理名，让秘书判）。
            #
            # 这一类的判词不止一个词：还要把名字洗出来（canonical_name）、把标签里那条
            # 路线挪到证明那一层（route），并把"条件是什么 / 结论是什么"各自留一句比对
            # （condition / conclusion）。这一层只做放行与截断，不校验语义（校验与三态在
            # `adjudicate_proposition` 一处做）—— 与 `nontriviality` 那一支同一条纪律：
            # 这一格只管"别把它丢了"（丢了之后盘上只剩一个 same，人看不出凭什么）。
            out["canonical_name"] = str(data.get("canonical_name") or "")[:200]
            out["same_as"] = str(data.get("same_as") or data.get("same_stmt_id") or "")[:64]
            out["route"] = str(data.get("route") or "")[:500]
            out["condition"] = str(data.get("condition") or "")[:500]
            out["conclusion"] = str(data.get("conclusion") or "")[:500]
        return self._record_judge(kind, context, out)

    def _record_judge(self, kind: str, context: Mapping[str, Any],
                      result: dict[str, Any]) -> dict[str, Any]:
        """把这次判断自己记一行台账（主控裁定 A5 的第 ③ 条）。

        为什么判断要独立成行（而不是只搭在 `assess_delegation` 的提案行上）：
        那份花销的归因（`cost.ledger`）与三态只在这一刻是完整的，
        而"这次判断花了哪一笔钱"必须总能从台账追回账本 —— 不论调用方是谁
        （`optimize_outbound` / `assess_delegation` / 直接调用）。
        `before` 落的是判断的输入（材料摘要），`after` 落结论：人看过程、本体看结果。
        """
        basis = list(result.get("basis") or [])
        if result.get("cost"):
            basis = basis + [f"cost.ledger={result['cost'].get('ledger') or '查不到'}"]
        self.note_decision(
            duty=2, kind=KIND_DECISION,
            decision=str(result.get("decision") or "建议重排"),
            reason=str(result.get("reason") or ""),
            basis=basis, target={"judge": kind}, judge=result,
            before=json.dumps(dict(context), ensure_ascii=False, sort_keys=True,
                              default=str)[:2000],
            fail_open=False,
        )
        return result

    def judge_statement(self, *, statement_full: str, statement: str = "",
                        source: str = "", basis_hint: str = "",
                        proof_text: str = "", proofs: list | None = None,
                        task_id: str = "") -> dict[str, Any]:
        """B 的秘书专属：这条待入库的命题落在非平凡性的哪一档（业主 2026-10-14 裁决第 12 条前半）。

        原话：「第十二条作为 B 的秘书的任务，判断一个待入库的命题是否太平凡有没有资格入库，且让 B 在挑定理和
        命题提交入库时要有审美。」为什么是"秘书"而不是"又一条机器判据"：平凡与否不是字符串能判的事
        （`a+b=b+a` 与一条真定理的字面形态可能很像），它属于本仓划给秘书的那一类判断（`draft/55` §2 的 B 类：
        机器只摆材料，结论由本体自己的缝给）。三态，且"没查成"不许读成"合格"：

        | 结局 | 返回 |
        |---|---|
        | 判了 | `checked=True` + `decision ∈ {"合格","太平凡","判不了"}` + `reason` + `basis` |
        | 不是 B 的秘书 | `checked=False` + 理由（这一问只属于 B） |
        | 没缝 / 开关关着 / 超时 / 坏 JSON | `checked=False` + 理由（`judge` 的那几支） |
        | 正文 0 字 | `checked=False` + `code=empty_statement_text`（不进判档流程，不发调用，不落台账） |

        ## 2026-10-24（业主裁定 B2）：判据换成"这份证明花了多大力气"
        业主原话：「不一定一条定理后面要用，也不一定存在"已知那条"，看证明花的力气就能判非平凡度」。
        于是这一趟的材料里多一格 `effort`：机器数好的四项读数（体量 / 步骤 / 引理 / 工具簇跨度）
        外加绕路与分数（:func:`proof_effort_readings`）。档位由分数落格
        （:data:`EFFORT_TIER_BANDS`），`nontriviality_from_effort` 是唯一那个落格函数。

        三个"谁是权威"的取舍写在这里，读的人不用去猜：
        1. 读数完整 ⇒ 档位按读数给定；秘书自报的 `nontriviality` 只作交叉核对，
           不一致时以读数为准，并把两边都写进 `nontriviality_basis`。
        2. 读数缺项（没有证明正文）或正文被截断 ⇒ 档位是 `None` + 原因点名缺哪一项 ——
           不许落 0 冒充"基础定理"，也不许把"输入不完整"写成"材料不足"。
        3. `decision` 跟着档位走（两栏不许自相矛盾）：读数给出 T1 以上而秘书判了「太平凡」⇒
           改记「合格」；读数一项都拿不到或输入被截断而秘书判了「太平凡」⇒ 改记「判不了」。
           两次改写都在结果里留 `decision_overridden_from`。

        `proof_text` / `proofs` 是可选的：`specs/b.py` 规定证明交在 `proof_text` 那一栏，
        而 `agent_loop._statement_filing_tier` 这一趟只转交命题正文（那一行不在本文件，
        见 `_statement_filing_tier` 的调用点）——所以正文里自带证明小节时（真机上 B 有时
        整段写进 `statement_full`），读数照样读得到；真读不到就是"缺证明正文"那一支。
        """
        if str(self.role) != "B":
            return {"checked": False, "decision": "", "basis": [],
                    "reason": f"这一问只属于 B 的秘书（本条秘书属于 {self.role!r}）⇒ 这一格没查成",
                    "cost": {"ledger": "", "reason": "没发调用（不是 B 的秘书）"}}
        # ---- 0 字命题：不进判档流程（B2 的第 1 条，2026-10-24）
        #
        # 真机读数（sylow4 的 `out/secretary/nontriviality.jsonl`）：11 行里有 1 行的
        # `statement_chars` 是 0，档位 None、basis "无任何命题或证明内容，无法定档"。
        # 那一行根本不该存在：空正文不是一个"判不了的对象"，它是"没有对象" ——
        # 判它一次要花一次模型调用，而结论只能是"没东西可判"。所以这一格在取材料之前
        # 就受控拒绝：不发调用、不落台账（判不了的读数也不留 —— 它会被读成"有人判过"）。
        body_full = str(statement_full or "")
        if not body_full.strip():
            return {"checked": False, "decision": "", "basis": [],
                    "code": EMPTY_STATEMENT_TEXT,
                    "reason": ("这一条命题的正文是 0 字 ⇒ 不进判档位（受控拒绝）。"
                               "空正文不是「材料不足」：它没有可判的对象，四项力气读数"
                               "（体量/步骤/引理/跨度）一项都取不到。把含完整假设的正文"
                               "交上来再判；`kind=\"concept\"` 的空定义走登记那条路，"
                               "不经过这一问"),
                    "nontriviality": NONTRIVIALITY_UNJUDGED, "label": "",
                    "nontriviality_tri": "unjudged", "nontriviality_basis": "",
                    "effort": {}, "text_truncated": False,
                    "cost": {"ledger": "", "reason": "没发调用（正文 0 字 ⇒ 不进判档位）"}}
        # ---- 力气读数（B2 的机器侧，判档位的唯一判据）
        #
        # `proofs` 是 B 一次交上来的多份证明（多证明模型）：任一份都算这份证明的力气，
        # 所以拼成一段一起读。`statement_full` 在它像一份证明正文时也参与（见
        # `_looks_like_a_proof`：真机上 B 有时把整段证明写进这一栏）。
        proof_bodies = [str(proof_text or "")]
        for item in (proofs or []):
            if isinstance(item, Mapping):
                proof_bodies.append(str(item.get("text") or item.get("proof_text") or ""))
        proof_joined = "\n\n".join(x for x in proof_bodies if str(x).strip())
        readings = proof_effort_readings(statement_full=body_full, proof_text=proof_joined,
                                         basis_hint=basis_hint)
        # 2026-10-15 业主裁定 D4：这几格此前是 `[:2000] / [:500] / [:300] / [:500]`
        # —— 一条静默截断，而且截的恰好是判据的输入：秘书要判的是"这条命题
        # 平不平凡"，而命题的长尾（限定条件、量词顺序）正是决定平凡与否的部分。
        # 截到 2000 字符意味着它可能在对半条命题下结论，而那个结论会变成
        # "这条别收"（`agent_loop._statement_filing_refusal`）。
        # 裁定标准：「限制输入…删或把触发水平抬高到几乎不可能触发」⇒ 抬 10 倍以上。
        # 注意 `statement_full` 同时是缓存键的输入（见下面的 sha256）：键必须
        # 跟着一起变 —— 它变了是好事，"同一命题问第二遍不重复花钱"仍然成立，
        # 而两条前 2000 字符相同、之后不同的命题不再被误认成同一条。
        #
        # 2026-10-24：多一格 `effort`（力气读数）。它按 `sort_keys` 排在材料最前面 ——
        # 万一材料真的被截断，模型至少已经看到读数本身，而不是只看到半句正文。
        context = {
            "effort": {k: readings.get(k) for k in
                       ("chars", "steps", "lemmas", "clusters", "cluster_names",
                        "detour", "score", "missing", "text_truncated", "truncated_at")},
            "statement_full": body_full[:20_000],
            "statement": str(statement or "")[:20_000],
            "source": str(source or "")[:4_000],
            "why_this_is_not_trivial": str(basis_hint or "")[:8_000],
        }
        # 截断读数：正文超上限、或材料 JSON 超上限，两种都算"输入不完整"。
        material_cut = material_truncation(context)
        body_cut = bool(readings.get("text_truncated"))
        text_truncated = bool(body_cut or material_cut["truncated"])
        if body_cut:
            at = int(readings.get("truncated_at") or PROOF_BODY_CAP)
            trunc_note = (f"这一条正文在 {at} 字处被截断（正文共 "
                          f"{int(readings.get('body_chars') or 0)} 字，判档位读的上限是 "
                          f"{at} 字）—— 档位判不了是因为输入不完整，不是因为材料不足")
        elif material_cut["truncated"]:
            trunc_note = (f"这一条正文在 {material_cut['at']} 字处被截断（材料共 "
                          f"{material_cut['chars']} 字，材料上限是 {material_cut['at']} 字）"
                          "—— 档位判不了是因为输入不完整，不是因为材料不足")
        else:
            trunc_note = ""
        # 缓存键：命题正文 + B 写的素材 + 证明正文的摘要。第三项是 2026-10-24 加的 ——
        # 同一条定理的第二份证明是另一次判断（力气不同），拿正文键去沿用会把它判成第一次那一档。
        key = hashlib.sha256(
            (context["statement_full"] + "\x00" + context["why_this_is_not_trivial"]
             + "\x00" + hashlib.sha256(proof_joined.encode("utf-8")).hexdigest())
            .encode("utf-8")).hexdigest()
        prior = self._statement_verdicts.get(key)
        if prior is not None:
            # 同一个命题问第二遍：不花钱、结论不变（并在台账里留一行说清是沿用）。
            self.note_decision(
                duty=2, decision=str(prior.get("decision") or ""), fail_open=False,
                target="statement_aesthetic",
                before=json.dumps({"statement_full": context["statement_full"],
                                   "why_this_is_not_trivial": context["why_this_is_not_trivial"]},
                                  ensure_ascii=False, default=str)[:2000],
                after=str(prior.get("reason") or ""),
                reason="沿用本趟第一次的判断（同一个命题不重复花钱；结论与第一次逐字相同）",
                basis=[f"reused_sha256={key[:12]}"],
            )
            return {**prior, "reused": True, "reused_key": key[:12],
                    "cost": {"ledger": "", "reason": "没发调用（沿用本趟第一次的结论）"}}
        got = self.judge("statement_aesthetic", context, task_id=task_id)
        if got.get("checked"):
            # 2026-10-21：同一趟判断的第二个输出 —— 非平凡性档位（0–4；判不了 = None）。
            # 2026-10-23 业主裁定：判「太平凡」不再意味着"拒收"，而是"落 T0"。
            # 2026-10-24 业主裁定（B2）：档位与"太平凡"都改由力气读数定。
            #
            # 三态纪律：判不了（None）不许读成 T0 —— 所以只有"读数给出 0 档"才写 0；
            # 读数一项都取不到时，秘书若判了「太平凡」，那一判断没有依据（改前正是
            # 这样把每一条都压成 T0），改记「判不了」。
            decided = str(got.get("decision") or "")
            model_level = _nontriviality_level(got.get("nontriviality"))
            model_note = str(got.get("nontriviality_basis") or "")
            verdict = nontriviality_from_effort(readings)
            level = verdict["level"]
            notes: list[str] = []
            if text_truncated:
                level = None
                notes.append(trunc_note)
                if _is_trivial_verdict(decided):
                    got["decision_overridden_from"] = decided
                    got["decision"] = "判不了"
                    notes.append("秘书判了「太平凡」，但这一趟看到的是被截断的正文 ⇒ "
                                 "那一判断不采信，改记「判不了」")
                if model_note:
                    notes.append(f"秘书原报档位依据（输入不完整，只留痕不作判据）：{model_note}")
            elif level is None:
                notes.append(str(verdict["why"]))
                if _is_trivial_verdict(decided):
                    got["decision_overridden_from"] = decided
                    got["decision"] = "判不了"
                    notes.append("秘书判了「太平凡」，但这一趟一项力气读数都取不到 ⇒ "
                                 "「力气小」没有依据，改记「判不了」")
                if model_level is not None:
                    notes.append(f"秘书自报 {nontriviality_label(model_level)}，"
                                 "但这一趟一项力气读数都取不到 ⇒ 档位落「未判」")
                if model_note:
                    notes.append(f"秘书原报档位依据：{model_note}")
            else:
                # 读数完整：档位按读数给定（秘书自报只作交叉核对）。
                if _is_trivial_verdict(decided):
                    if level == 0:
                        notes.append(f"降为 {nontriviality_label(0)}：" + str(verdict["why"])
                                     + f"；秘书原话：{str(got.get('reason') or '')[:200]}")
                    else:
                        got["decision_overridden_from"] = decided
                        got["decision"] = "合格"
                        notes.append("秘书判了「太平凡」，但" + str(verdict["why"])
                                     + " ⇒ 档位不压低（判据只有力气那一组，"
                                     "「没人用得上 / 不比已知强」不作判据）")
                else:
                    notes.append(str(verdict["why"]))
                if model_level is not None and model_level != level:
                    notes.append(f"秘书自报 {nontriviality_label(model_level)}，"
                                 "与力气读数不一致 ⇒ 以读数为准")
                if model_note:
                    notes.append(f"秘书原报档位依据：{model_note}")
            basis_note = "；".join(n for n in notes if n)[:900]
            got = {**got, "nontriviality": level, "label": nontriviality_label(level),
                   "nontriviality_basis": basis_note,
                   "nontriviality_tri": "computed" if level is not None else "unjudged",
                   "effort": readings, "effort_score": int(readings.get("score") or 0),
                   "text_truncated": bool(text_truncated)}
            root = getattr(self, "root", None)
            if root is not None:
                try:
                    append_nontriviality(root, statement_full=body_full,
                                         level=level, basis=basis_note,
                                         role=str(self.role or ""), task_id=str(task_id or ""),
                                         effort=readings, text_truncated=bool(text_truncated))
                except Exception as exc:  # noqa: BLE001 - 落盘失败不影响判断本身
                    got["nontriviality_tri"] = f"unrecorded:{type(exc).__name__}"
            # 只记判过的结论（没查成不缓存，见 `_statement_verdicts` 的说明）。
            self._statement_verdicts[key] = dict(got)
        return got

    def last_judge_cost(self, kind: str) -> dict[str, Any]:
        """上一次该类别判断的花销归因（主控裁定 A5 的第 ③ 条）。

        权威来源是缝自己落的那条审计事件：`llmseam._land` 把"这次的钱记进账本了吗、记成哪一行"写进
        `llm_call` 事件的 `ledger` 字段（`usage_id` / `reason`），所以这里读那条事件，而不是让秘书猜花销。
        三态（取不到就如实写，不许折成"花了 0"）：
        | 情形 | 返回 |
        |---|---|
        | 入账了 | `ledger = "<usage_id>"` |
        | 没入账（`no_meter` / `duplicate` / 没发请求） | `ledger = ""` + `reason` 逐字来自事件 |
        | 读不到事件 / 读不出会话 | `ledger = ""` + `reason = "查不到：…"` |
        `call_index` 是与 `usage_id` 并列的第二归因口径（缝的幂等键就用它），两者都给，读的人才能把"账本行"
        与"第几次调用"对上。
        """
        from . import sessions as SS

        want = f"secretary:{kind}"
        try:
            events, problems = SS.read_session(self.root, self.sid)
        except Exception as exc:  # noqa: BLE001 - 归因读不到就如实报
            return {"ledger": "", "reason": f"查不到：{type(exc).__name__}: {exc}"}
        calls = [e for e in events if e.get("kind") == "llm_call"]
        hit = [e for e in calls if str(e.get("note") or "") == want]
        if not hit:
            extra = f"（会话读不出：{problems[0]}）" if problems else ""
            return {"ledger": "", "reason": f"查不到：会话里没有这次判断的 llm_call 事件{extra}",
                    "call_index": len(calls)}
        ev = hit[-1]
        led = ev.get("ledger") if isinstance(ev.get("ledger"), Mapping) else {}
        out: dict[str, Any] = {
            "ledger": str((led or {}).get("usage_id") or ""),
            "charged": bool((led or {}).get("charged")),
            "ledger_reason": str((led or {}).get("reason") or ""),
            "call_index": len(calls) - 1,
            "prompt_sha256": str(ev.get("prompt_sha256") or ""),
            "tokens": int(ev.get("tokens_in") or 0) + int(ev.get("tokens_out") or 0),
            "usd": ev.get("usd"),
        }
        if not out["ledger"]:
            out["reason"] = (f"取不到 usage_id（{out['ledger_reason'] or '未知'}）"
                             "⇒ 用 call_index 归因")
        return out

    # ------------------------------------------------------------ 职责 1 / 2（发件侧）

    def _message_alarms(self, payload: Mapping[str, Any], *, admission: Any = None) -> list[str]:
        """`message`（跨智能体的结构化交互）的预筛：准入判据 + 两个必填字段。

        三态纪律：判据没接上时如实报"这一格判不了（没查成不是没问题）"，绝不因为拿不到判据就当它通过。
        为什么不自己判协作边：判据本体只有一份（`agent_loop.message_admission`），由 `AgentLoop._outbound_hook`
        通过 `admission=` 注入进来。本文件里再查一次协作边（`agent_prompts` 那一支）就是长出了第二份实现，而
        两份漂了没有任何东西会红（判据：`tests/test_secretary.py` 里那条 AST 扫描 —— 它扫的是调用，不是措辞）。
        缺 `subject`/`body` 只报警、不替它编内容（职责 1 的既有纪律：秘书给建议，不改实质、不代笔）。
        """
        out: list[str] = []
        to = str(payload.get("to") or "")
        reply_to = str(payload.get("reply_to") or "")
        if admission is None:
            out.append("message 的协作边准入判据没接上 ⇒ 这一格判不了（没查成不是没问题）")
        else:
            try:
                reason = str(admission(self.role, to, reply_to) or "")
            except Exception as exc:  # noqa: BLE001 - 判据自己坏了也是"判不了"
                reason = f"message 的准入判据自己出错了（{type(exc).__name__}: {exc}）⇒ 这一格判不了"
            if reason:
                out.append(reason)
        for field in ("subject", "body"):
            value = payload.get(field)
            if not isinstance(value, str) or not value.strip():
                out.append(f"message 的 `{field}` 要是非空字符串（缺了不替它编内容）")
        return out

    def optimize_outbound(self, shape: str, payload: Mapping[str, Any], *,
                          admission: Any = None, base: str = "") -> dict[str, Any]:
        """职责 1：格式与内容优化（发件前）。

        不改变实质主张：不替本体承诺、不改结论、不加证据（`draft/53` §2 的"不许做"）。所以这里的产物是
        "建议 + 并列候选"，而不是改写后的载荷：本体读到的仍是它自己那一份（改不改由它决定）。两段分得很清
        （这是"切勿全写死成机器判据"的落点）：
        - 第一段是预筛（确定性）：参数表 / 必填 / 工具真名的检查，来自既有声明；
        - 第二段是判断（只有 :meth:`should_engage` 说该介入时才走）：错名映到哪一个候选（:meth:`judge` 的
          `tool_name` 一类，一次模型调用 + 台账）。判断没查成 ⇒ 结论仍是预筛那一份，且台账里
          `judge.checked=False` 写明。
        fail-open：超时/自己出错 ⇒ 原样放行 + 台账留痕（`fail_open=True`）。
        """
        original = dict(payload)
        # ---- 两段式（业主 2026-10-21 裁定）：确认/拒绝那两个字段是协议字段，
        # 不进洗格式的输入、也不进"原稿/洗后"这两份被并列记录的内容面载荷。
        # 分开取而不是洗完之后再删：`original` 与 `washed` 必须是同一件事的两份，
        # 否则"逐字段 diff"会把一个协议字段算成内容差异。
        accept = str(payload.get(ACCEPT_PROPOSAL) or "")
        reject = str(payload.get(REJECT_PROPOSAL) or "")
        body = {k: v for k, v in original.items() if k not in PROPOSAL_KEYS}
        t0 = time.monotonic()
        try:
            if time.monotonic() - t0 > self.deadline_sec:
                raise TimeoutError("秘书超过单次调用上限")
            # ---- S1g：洗格式（E5 的落地）。位置：判"该不该介入"之前 ——
            # 预筛要核的是洗过之后那一份（否则"错名"永远是错的，洗了白洗）。
            # 内容面一个字不动（`wash_delegation` 的边界逐条写在它的 docstring 里）。
            wash = self.wash_delegation(shape, body)
            if wash.get("refused"):
                # 硬拒也要把预筛读数算出来：这一趟是死了，但"它另外还把工具名写错了、
                # 候选是这几个"是有用的东西（真机上模型下一步就得靠它改）。
                # 只是不判（不叫模型）：没有可发的载荷，判断没有意义。
                r_to = str(original.get("to") or original.get("role") or "")
                r_params = (original.get("params") if isinstance(original.get("params"),
                                                                 Mapping) else {})
                r_tool = str(original.get("name") or original.get("tool") or "")
                alarms = self.prescreen(to=r_to, action=str(original.get("action") or ""),
                                        params=r_params or {}, tool=r_tool)
                rec = self.note_decision(
                    duty=1, kind=KIND_OPTIMIZED, decision="洗不动 ⇒ 受控拒绝",
                    reason="；".join([str(wash.get("reason") or ""), *alarms]).strip("；"),
                    basis=["specs/<role>.py 的参数表", "tools.build_registry() 的真名"],
                    target={"to": r_to, "action": str(original.get("action") or "")},
                    before=json.dumps(original, ensure_ascii=False, sort_keys=True, default=str)[:2000],
                    changes=list(wash.get("changes") or ()), fail_open=False)
                return {"problem": "；".join([str(wash.get("reason") or ""), *alarms]).strip("；"),
                        "payload": original, "after": original, "wash": wash, "changes": [],
                        "washed": False, "refused": True, "alarms": alarms,
                        "surface": self.surface_readings(shape, original, base=base),
                        "judge": {"checked": False, "reason": "硬拒：没有可判的载荷"},
                        "engaged": False, "fail_open": False, "seq": rec.get("seq")}
            washed = dict(wash.get("payload") or body) if wash.get("checked") else body
            # ---- 两段式的判据本体（纯决定，不写盘）：这一次执行哪一份 / 要不要请示。
            # 编号在下面那一行台账里发（同一个临界区），所以这里只拿到"要不要发"。
            plan = self.plan_wash(original=body, wash=wash, accept=accept, reject=reject)
            to = str(washed.get("to") or washed.get("role") or "")
            action = str(washed.get("action") or "")
            params = (washed.get("params") if isinstance(washed.get("params"), Mapping) else {})
            tool = str(washed.get("name") or washed.get("tool") or "")
            if shape == "message":
                # `R8`：`message` 是跨智能体的结构化交互 ⇒ 秘书接管（所有者裁定逐字
                # "如果有些形状涉及到结构化交互，则需要秘书接管"）。接管 = 预筛报警 +
                # 建议 + 台账（不替代 `_do_message` 的硬闸，也不改载荷）。
                #
                # 为什么这一支不跑上面那条委派预筛：`message` 没有 `action`/`params`/`tool`
                # 三件，而预筛会把 `to` 当角色名去查能力表 —— 对 `to=#public` 会报出两条
                # "读不到 #public 的角色定位"的假警（频道名不是角色）。它的整个预筛面
                # 就是下面这两格：共用准入判据 + 两个必填字段。
                alarms = self._message_alarms(body, admission=admission)
            else:
                alarms = self.prescreen(to=to, action=action, params=params or {}, tool=tool)
            # 预筛报警不是"判决"：它只说"照声明看不合规"，改法（映到哪个名字、
            # 补哪个字段）是判断 ⇒ 只有该介入时才叫模型。
            judged: dict[str, Any] = {"checked": False, "reason": "预筛没有报警 ⇒ 不必判断"}
            engage = self.should_engage(alarms=alarms, duplicates=0, overdue=0, novel=bool(tool))
            # 请示/受控拒绝/确认这三档都没有要发出去的载荷 ⇒ 不叫模型判
            # （判断的对象是"这次派活该怎么写"，而这次派活根本不发生）。
            if not plan["outcome"] and not plan["problem"] and plan["accepted"] is None:
                if engage and tool and any("真名" in a for a in alarms):
                    judged = self.judge("tool_name", {"tool": tool, "to": to,
                                                      "candidates": declarations_candidates(
                                                          tool, self._tool_names())})
            decision = ("已优化" if not alarms else "建议重排")
            if judged.get("checked"):
                decision = str(judged.get("decision") or decision)
            changes = list(wash.get("changes") or ())
            # ---- 台账那一行（一次调用一行；两段式的三档各带自己的 `decision`/`kind`）
            proposal_arg: str | None = None
            fingerprint = ""
            reason = "；".join(alarms) or "没有触发预筛报警（原样放行）"
            if plan["outcome"]:
                # 第一段：请示。编号由本秘书在锁内发（`proposal=""` 那一档）；
                # 同一份载荷已经请示过 ⇒ 复用那个编号（`proposal="<id>"` 那一档），
                # 于是"同一件事的两步"在读数上逐字相同（否则原地打转判不出来）。
                decision = DECISION_PROPOSED
                # 指纹随行落账：确认那一步要拿它核"这个编号是对哪份载荷发的"。
                fingerprint = self.proposal_fingerprint(body)
                prior = self.find_proposal_by_fingerprint(fingerprint)
                if prior is not None:
                    proposal_arg = str(prior.get("proposal_id") or "")
                    plan["proposal_id"] = proposal_arg
                else:
                    proposal_arg = ""
                reason = ("；".join(plan["changes"]) or "（改了格式格）"
                          ) + "｜**没有执行**：等父用 accept_proposal / reject_proposal 表态"
            elif plan["problem"]:
                decision = "洗格式请示：这个编号不成立 ⇒ 受控拒绝"
                proposal_arg = plan["proposal_id"] or None
                reason = plan["problem"]
            elif plan["accepted"] is True:
                decision = DECISION_ACCEPTED
                proposal_arg = plan["proposal_id"]
                reason = "按洗过的那一份执行（parent 接受了格式洗）"
            elif plan["accepted"] is False:
                decision = DECISION_REJECTED
                proposal_arg = plan["proposal_id"]
                reason = "按原稿执行（parent 拒绝了秘书的格式洗）"
            rec = self.note_decision(
                duty=1,
                kind=KIND_PROPOSAL if plan["outcome"] else KIND_OPTIMIZED,
                decision=decision,
                reason=reason,
                basis=["specs/<role>.py 的参数表", "tools.build_registry() 的真名"],
                target={"to": to, "action": action}, judge=judged,
                before=json.dumps(original, ensure_ascii=False, sort_keys=True, default=str)[:2000],
                # S1g：洗过的那一份与原稿并列落账（`before`/`after` + 逐格 `changes`）。
                # 只有一份摆在那里时，"模型说错了"与"秘书替它补对了"在纸上分不开。
                after=json.dumps(washed, ensure_ascii=False, sort_keys=True, default=str)[:2000],
                changes=changes,
                fail_open=False,
                proposal=proposal_arg,
                fingerprint=fingerprint,
            )
            if plan["issue"]:
                # 编号从落盘那一行回来（同一个 `seq`）⇒ "这个编号指向哪一行"不可能漂。
                plan["proposal_id"] = str(rec.get("proposal_id") or "")
                if not str(rec.get("proposal_id") or ""):
                    # 发号失败（台账写不成）⇒ 不许回一个"无法确认"的请示：
                    # 受控拒绝，并把原因写清（fail-open 只剩这一档是安全的）。
                    plan.update(outcome="", issue=False, proposal_id="", problem=(
                        "请示编号没能发出（台账写不成）⇒ 这一趟没有派活："
                        f"{rec.get('ledger_problem') or '未知原因'}"))
            ret = {"problem": "；".join(alarms), "payload": original, "after": washed,
                   "wash": wash, "changes": changes,
                   "washed": bool(wash.get("washed")), "refused": False,
                   "alarms": alarms, "judge": judged, "engaged": bool(engage),
                   "surface": self.surface_readings(shape, washed, base=base),
                   "fail_open": False, "seq": rec.get("seq")}
            if plan["outcome"] or plan["problem"] or plan["accepted"] is not None:
                # 只在真的进了第二段时给这一格：老载荷的键集因此一个字节不变
                # （没差异的那条路不是"两段式"，多一格会让人以为它也请示过）。
                ret["wash_proposal"] = plan
            return ret
        except Exception as exc:  # noqa: BLE001 - fail-open：超时/出错一律放行
            self.note_decision(duty=1, kind=KIND_OPTIMIZED, decision="已优化",
                               reason="秘书没跑成 ⇒ 原样放行", fail_open=True,
                               error=f"{type(exc).__name__}: {exc}",
                               before=json.dumps(original, ensure_ascii=False, sort_keys=True, default=str)[:2000])
            self._log(f"秘书优化没跑成（原样放行）：{type(exc).__name__}: {exc}")
            return {"problem": f"{type(exc).__name__}: {exc}", "payload": original,
                    "after": original, "wash": {"checked": False, "washed": False,
                                                "refused": "", "changes": [],
                                                "reason": f"没跑成：{type(exc).__name__}"},
                    "changes": [], "washed": False, "refused": False,
                    "alarms": [], "fail_open": True,
                    "surface": {"checked": False, "fits": None,
                                "reason": "秘书没跑成 ⇒ 面这一维没查成（不是通过）"}}

    # ------------------------------------------------------------ 洗格式（S1g）

    #: 洗格式只管派活这两个形状（`draft/90` §1.2 的格式面）：
    #: `handoff` / `message` 的 `to` 是内容面（"派给谁"一个字不许动）⇒ 只报不改。
    WASH_SHAPES: tuple[str, ...] = ("summon", "summon_many")

    #: 形状自己的键（不是 `params` 的键）：顶层折叠时要跳过它们，
    #: 否则一个恰好叫 `name` 的动作参数会把名册那一格（S1k）偷走。
    #: 两段式的确认/拒绝两个字段也在这里：它们是协议字段，既不是动作参数、
    #: 也不许被"顶层折叠"搬进 `params`（否则一次派活会带一个叫 `accept_proposal` 的参数
    #: 撞闸门，而"接受"这件事在语义上根本不是那件活的参数）。
    _SHAPE_KEYS: tuple[str, ...] = ("role", "action", "params", "brief", "name", "reuse",
                                    "input_key", "instance", "targets", "notify", "why",
                                    *PROPOSAL_KEYS)

    def wash_delegation(self, shape: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        """洗一遍格式面（S1g / E5），内容面一个字不动。

        返回（三态必须分得开，这是本仓最忌折平的一处）：
        | 结局 | 返回 |
        |---|---|
        | 洗过了、本来就是受控形状 | `{"checked": True, "washed": False, "changes": []}` |
        | 洗过了、改了格式格 | `{"checked": True, "washed": True, "changes": [...]}` |
        | 这一格没洗成 | `{"checked": False, "reason": …}`（原样发出去，闸门照旧） |
        | 硬拒 | `{"checked": True, "refused": "<受控理由码>"}`（调用方一行都不落） |
        ## 可以洗什么（`draft/90` §1.2，逐条）：动作真名（`action` 不在该角色动作表里、而
        `declarations_candidates` 只给出唯一候选 ⇒ 映过去；多条 ⇒ 不猜，留给闸门拒）；`params` 键名（声明里
        没有这个键、而候选唯一 ⇒ 改名，值原样跟着走）；顶层折叠（动作声明的参数被摆在了顶层 ⇒ 收进 `params`）；
        `input_key` 归一（去空白 + 内部空白并成一个空格，它是环检测键）；`name` / `reuse` / `instance` / `role` /
        `action` 去首尾空白。一个字不许动什么（内容面）：`params` 里任何值、`role`（派给谁）、`notify` 的正文
        与主张、证据与结论 —— 只搬键、只去空白，从不把 `None`/缺键补成默认值。
        ## 硬拒只有一格（为什么这么窄）："洗不动 ⇒ 受控拒绝，一行都不落"（`draft/90` §1.2 步骤 1）落在
        `summon` 连"派给谁/做什么"都不全这一格：没有角色或没有动作时，一次派活在语义上不成立。其余"洗不动"
        （缺必填参数、参数值不对）照旧交给 `conductor` 的闸门去拒 —— 那一档今天会落一行 `refused` 并且可能转成
        "请主控代唤"（`_needs_relay`），秘书抢在它前面拒掉会把那条出路和那行证据一起弄丢。`summon_many` 不用硬拒：
        一批是 N 次派活，整批拒掉会把好的那几项一起带走（逐项 `refused` 行仍由闸门落）。为什么 `params` 只动顶层
        一层、且不深拷：噪声载荷里有自引用字典（`SELF_REF`）与 60 层深嵌套（`test_secretary_noise.py`），递归走一遍
        会当场炸掉这一次派活 —— 只搬顶层键、只去字符串空白，永远碰不到那些结构。
        """
        before = dict(payload or {})
        out: dict[str, Any] = {"checked": False, "washed": False, "refused": "",
                               "reason": "", "payload": before, "before": before,
                               "changes": []}
        if shape not in self.WASH_SHAPES:
            out["reason"] = (f"{shape} 不在洗格式的面上（派活以外只报不改："
                             "`to` 是内容面）")
            return out
        try:
            if shape == "summon_many":
                return self._wash_summon_many(before, out)
            return self._wash_one(before, out, field="")
        except Exception as exc:  # noqa: BLE001 —— 洗不动不许打断这一次派活
            out.update(checked=False, washed=False, refused="", payload=before,
                       reason=f"洗格式没跑成（{type(exc).__name__}: {exc}）⇒ 原样发出去")
            return out

    def _wash_one(self, payload: dict[str, Any], out: dict[str, Any],
                  *, field: str, refuse: bool = True) -> dict[str, Any]:
        """洗一次派活的格式面（`field` 给了就把这一份摆在那个字段名下，用于批量）。"""
        where = f"{field}：" if field else ""
        after = dict(payload)
        changes: list[dict[str, Any]] = list(out.get("changes") or [])
        for key in ("role", "action", "name", "reuse", "instance"):
            got = after.get(key)
            if isinstance(got, str):
                stripped = got.strip()
                if stripped != got:
                    after[key] = stripped
                    changes.append({"where": field, "field": key, "why": "去首尾空白"})
        key_val = after.get("input_key")
        if isinstance(key_val, str):
            folded = " ".join(key_val.split())
            if folded != key_val:
                after["input_key"] = folded
                changes.append({"where": field, "field": "input_key", "why": "归一（空白并一个）"})
        # 角色那一格有两个写法（`role` 是派活形状的、`to` 是老调用方的）：
        # `optimize_outbound` 与 `prescreen` 都认两个 ⇒ 这里也认两个，
        # 否则一个用 `to=` 的调用方会被判成"没给角色"（真机判据当场抓出来的）。
        role = after.get("role")
        if not (isinstance(role, str) and role.strip()):
            role = after.get("to") if isinstance(after.get("to"), str) else ""
        else:
            role = role.strip()
        action = after.get("action") if isinstance(after.get("action"), str) else ""
        # 2026-10-16（业主口径 S2「M 只派活」）：硬拒那一格从"没有角色或没有动作"
        # 收窄成"没有角色 或 既没有动作也没有活"。
        # 原话逐字：「一致改成 task 必填，action 不填」「action 完全不用父代理填」。
        # 真机读数（T5 第 12/13 趟）：M 六次/两次发出 `{"role":"A","task":…}`，而 `tasks`
        # 表里空动作的行 = 0 —— 全死在这一行（它不落行，所以连证据都没留下）。
        # 2026-10-16：活的写法有两处 —— 顶层的 `task`（形状/工具那一面），
        # 以及 `params["task"]`（派活那条路为了给被派者那一趟循环取用而并进去的那一份）。
        # 真机/判据现场：批量派活被拒的理由码是 `unknown_action`，而它其实写了活
        # （只是写在 `params` 里）⇒ 这一格必须两处都认，否则"派活"永远过不去。
        work = str(after.get("task") or (after.get("params") or {}).get("task") or "").strip()
        if not role or not (action or work):
            missing = ("角色（派给谁）" if not role
                       else ("动作（做什么）" if action else "活（做什么）"))
            # 理由码与闸门那一侧同名（`schema.REFUSAL_REASONS`）：空动作名字在
            # 闸门那里就是 `unknown_action`（红前读数见 S1g 的提交信息），这一档只是
            # "不落行"、码不改 —— 换一个码会让读了半年日志的人以为另出了一类拒绝。
            code = "unknown_role" if not role else "unknown_action"
            if refuse:
                out.update(payload=payload, changes=changes, checked=True, washed=False,
                           refused=code,
                           reason=f"{where}没给{missing} ⇒ 一次派活在语义上不成立（不落行）")
                return out
            out.update(payload=after, changes=changes, checked=True,
                       washed=bool(changes), reason=f"{where}没给{missing} ⇒ 这一项洗不了")
            return out
        spec = self._action_spec(role, action)
        table = self._action_table().get(role, [])
        note = ""
        # 2026-10-16（业主口径 S2）：`action` 为空时没有可映的动作 ⇒ 这一步跳过，
        # 不记 `note`。原先空动作会走到下面那个 `elif`，记成
        # "动作表里没有 ''（没有候选 ⇒ 不猜，留给闸门拒）" ⇒ "只派活"那一路被挂上一条
        # 无意义的格式说明（判据现场：`test_the_secretary_washes_the_format_face` 读到它）。
        if spec is None and str(action):
            close = declarations_candidates(action, table) if table else []
            if len(close) == 1:
                after["action"] = close[0]
                changes.append({"where": field, "field": "action",
                                "from": action, "to": close[0], "why": "动作真名（唯一候选）"})
                action = close[0]
                spec = self._action_spec(role, action)
            elif table:
                note = (f"{where}动作表里没有 {action!r}"
                        + (f"；并列候选 {close} ⇒ 不猜（留给闸门拒）" if close
                           else "（没有候选 ⇒ 不猜，留给闸门拒）"))
        # ---- `params` 键名归一 + 顶层折叠 —— 一次做完，因为它们是同一件事的两半：
        # 值在哪一格不重要，重要的是它得落在声明的那个键下面。
        props = self._param_props(spec)
        raw_params = after.get("params")
        if props and (raw_params is None or isinstance(raw_params, Mapping)):
            fixed = dict(raw_params or {})
            for key in list(fixed):
                if key in props:
                    continue
                cand = declarations_candidates(str(key), props)
                if len(cand) == 1 and cand[0] not in fixed:
                    # 目标键已经在 `params` 里 ⇒ 不改（改名会覆盖一个真值：
                    # 那是动内容面，不是洗格式）。
                    fixed[cand[0]] = fixed.pop(key)
                    changes.append({"where": field, "field": f"params.{key}",
                                    "to": f"params.{cand[0]}", "why": "键名归一（唯一候选）"})
            for key in list(after):
                if key in fixed or key in self._SHAPE_KEYS or key == "params":
                    continue
                if key in props:
                    fixed[key] = after.pop(key)
                    changes.append({"where": field, "field": f"<顶层>.{key}",
                                    "to": f"params.{key}", "why": "顶层折叠"})
                    continue
                # 顶层的错名键：候选唯一 ⇒ 改名并收进 `params`（与 `params` 里
                # 那一支同一条口径）；候选不唯一 ⇒ 一个字节都不动，留在顶层
                # （它照样落在步骤记录里，"没洗"看得见）。
                cand = declarations_candidates(str(key), props)
                if len(cand) == 1 and cand[0] not in fixed:
                    fixed[cand[0]] = after.pop(key)
                    changes.append({"where": field, "field": f"<顶层>.{key}",
                                    "from": str(key), "to": f"params.{cand[0]}",
                                    "why": "顶层折算：键名归一（唯一候选）"})
            if fixed or raw_params is not None:
                if fixed != dict(raw_params or {}):
                    after["params"] = fixed
        elif raw_params is not None and not isinstance(raw_params, Mapping):
            note = note or f"{where}params 不是键值对 ⇒ 这一格没洗（原样发出去）"
        # 三态：读到了声明（表非空）就是"查过了"；表读不到才是"这一格没读成"。
        checked = bool(spec or table)
        out.update(payload=after, changes=changes, checked=checked,
                   washed=bool(changes), refused="",
                   reason=note if not changes else "")
        return out

    def _wash_summon_many(self, payload: dict[str, Any], out: dict[str, Any]) -> dict[str, Any]:
        """批量：逐项洗，不整批硬拒（一批是 N 次派活）。"""
        targets = payload.get("targets")
        after = dict(payload)
        changes: list[dict[str, Any]] = []
        bad: list[str] = []
        if not isinstance(targets, (list, tuple)):
            out.update(reason="targets 不是数组 ⇒ 这一格没洗（原样发出去）", payload=payload)
            return out
        washed: list[Any] = []
        for i, item in enumerate(targets):
            if not isinstance(item, Mapping):
                washed.append(item)
                bad.append(f"targets[{i}] 不是键值对")
                continue
            sub: dict[str, Any] = {"changes": [], "washed": False}
            got = self._wash_one(dict(item), sub, field=f"targets[{i}]", refuse=False)
            if got.get("reason") and not got.get("washed"):
                bad.append(str(got["reason"]))
            changes.extend(list(got.get("changes") or []))
            washed.append(dict(got.get("payload") or {}))
        after["targets"] = washed
        out.update(payload=after, changes=changes, checked=True, washed=bool(changes),
                   refused="",
                   reason="；".join(bad[:3]) if bad else "")
        return out

    # ------------------------------------------------------------ 两段式：请示 / 确认（S1g-2）

    def proposal_prefix(self) -> str:
        """请示编号的前缀：`W-<role>-<实例>-`，编号本身由台账锁内的 `seq` 发。

        为什么带实例：台账是分片的（`out/secretary/<role>-<task_id>.jsonl`），
        `seq` 只在片内唯一 ⇒ 只带角色的话，同角色两个并发实例会发出同名编号。
        （判据：新判据文件里"编号唯一 + 指得回那一行"那一条。）
        """
        return f"W-{self.role}-{self.task_id or 'x'}-"

    def proposal_fingerprint(self, payload: Mapping[str, Any]) -> str:
        """这份载荷的指纹（12 hex）：确认那一步用它判"这个编号是不是对这份载荷发的"。

        为什么要有它：只按编号回查，接受方就可以拿 A 的编号去确认 B 的载荷 ——
        编号存在、执行成立、接受的那份内容却不是它看过的那份。
        为什么让它抛（而不是把算不出来的折成空串）：空串会与另一份同样算不出来的载荷
        撞成同一个指纹 ⇒ 冒充成同一份。调用方在 try 里 ⇒ 成环/怪对象一律 fail-open 原样放行。
        """
        text = json.dumps(dict(payload or {}), ensure_ascii=False, sort_keys=True, default=str)
        return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]

    def find_proposal(self, proposal_id: str) -> dict[str, Any] | None:
        """按编号回查那条请示（回查范围 = 本实例的账：老文件 + 本片）。

        只认"请示行"—— 也就是带着指纹的那一行（`:meth:`note_decision` 的 `fingerprint=`）。
        为什么必须这么筛：接受/拒绝/受控拒绝那几行也带同一个 `proposal_id`（那是留痕，
        让"这个编号后来被谁接受过"读得回来）。若不筛，倒序扫到的第一行会是最近那次确认，
        它没有指纹 ⇒ "指纹对不上"这一格永远轮不到判 ⇒ 拿 A 的编号确认 B 的载荷会静默通过。
        （实测：本函数第一版就是这样，探针第 6 格读不到"指纹不一致"。）

        三态不折平：没有这一行 返回 `None`（调用方必须按受控拒绝处理），
        而"台账读不成"由 `_read_ledger` 的坏行读数另行报出 —— 不许把读不成当成"没有"。
        """
        want = str(proposal_id or "")
        if not want:
            return None
        rows, _bad = self._read_ledger()
        for row in reversed(rows):
            if (str(row.get("proposal_id") or "") == want
                    and str(row.get("proposal_fingerprint") or "")):
                return row
        return None

    def find_proposal_by_fingerprint(self, fingerprint: str) -> dict[str, Any] | None:
        """同一份载荷已经请示过 ⇒ 把那条请示找回来（编号复用，不另发一个）。

        为什么必须复用：模型很可能"看到了请示、但下一步又把同一句话重说一遍"
        （它没有改格式，只是没表态）。若每一步都新发一个号，步骤结果的读数就每步不同
        ⇒ 循环那一层的"同一条路 + 同一读数"判据（`_call_reading`）永远判不出原地打转
        （实测：本函数还没有时，同一份载荷在两步里拿到 `…-0001` 与 `…-0004` 两个号）。
        "一次派活一个"也是业主的原话：同一份载荷的同一次请示，编号就该是同一个。
        """
        want = str(fingerprint or "")
        if not want:
            return None
        rows, _bad = self._read_ledger()
        for row in reversed(rows):
            if (str(row.get("proposal_fingerprint") or "") == want
                    and str(row.get("proposal_id") or "")):
                return row
        return None

    @staticmethod
    def _value_at(payload: Mapping[str, Any], field: str) -> Any:
        """从 `changes[].field` 的那种写法里取值（`params.k` / `<顶层>.k` / `k`）。"""
        text = str(field or "")
        if text.startswith("<顶层>."):
            return payload.get(text[len("<顶层>."):])
        if text.startswith("params."):
            params = payload.get("params")
            return params.get(text[len("params."):]) if isinstance(params, Mapping) else None
        return payload.get(text)

    def _same_value(self, a: Any, b: Any) -> bool:
        """两个值是不是同一份（成环对象只认 `is`，绝不递归比）。"""
        if a is b:
            return True
        try:
            return bool(a == b)
        except Exception:  # noqa: BLE001 —— 比不了就按"不同"处理（宁可多报一处差异）
            return False

    def _wash_diff(self, original: Mapping[str, Any], washed: Mapping[str, Any],
                   changes: Sequence[Mapping[str, Any]]) -> tuple[list[str], dict[str, Any]]:
        """逐字段 diff：只列改了哪几个键（值原样摆出来，供人核"值其实没动"）。

        为什么从 `changes` 反推、而不是递归比两棵载荷：`changes` 是洗函数自己记的
        "我动了哪几格"（唯一事实），而递归比一份 60 层深/成环的载荷会当场炸掉
        （`test_secretary_noise.py` 的那两口噪声）。
        """
        keys: list[str] = []
        diff: dict[str, Any] = {}
        for c in changes or ():
            where = str(c.get("where") or "").strip("：: ")
            field = str(c.get("field") or "")
            path = f"{where}.{field}" if where else field
            why = str(c.get("why") or "")
            #: 每一条洗出来的改动都只可能在格式面上（真名 / 键名 / 位置）——
            #: 内容面那一半由 `tests/test_the_wash_is_proposed_not_applied.py` 的
            #: `_boundary_problems` 逐个值核（值多重集不变、正文逐字不变）。
            line: dict[str, Any] = {"why": why, "face": "格式面"}
            if "from" in c:
                line["from"] = c.get("from")
            if "to" in c:
                line["to"] = c.get("to")
            before = self._value_at(original, field)
            # `to` 有两种写法：键路径（`params.statement_text`）与值（动作真名
            # `register_statement`）。按有没有路径分隔判，别把后者当键名去查
            # （第一版就是这么错的：`value_after` 恒为 null，"改了真名"看起来像"值被清了"）。
            target = str(c.get("to") or field)
            if "." not in target and "<顶层>" not in target:
                target = field
            after = self._value_at(washed, target)
            if before is not None or after is not None:
                # `value_changed=False` 是关键读数：键换了位置而值逐字没动
                line["value_before"] = before
                line["value_after"] = after
                line["value_changed"] = not self._same_value(before, after)
            keys.append(path)
            diff[path] = line
        return keys, diff

    def _change_line(self, change: Mapping[str, Any]) -> str:
        """一条改动写成一句话（业主给的形状：`动作名 own.register_statement → register_statement`）。"""
        where = str(change.get("where") or "").strip("：: ")
        field = str(change.get("field") or "")
        to = str(change.get("to") or "")
        why = str(change.get("why") or "")
        frm = str(change.get("from") or change.get("field") or "")
        head = f"{where} " if where else ""
        if "动作真名" in why:
            return f"{head}动作名 {frm} → {to}"
        if "折叠" in why or "键名归一" in why:
            return f"{head}参数键 {field} → {to}"
        if why:
            return f"{head}{field}：{why}"
        return f"{head}{field} → {to}"

    def plan_wash(self, *, original: Mapping[str, Any], wash: Mapping[str, Any],
                  accept: str = "", reject: str = "") -> dict[str, Any]:
        """两段式的判据本体：这一次派活执行哪一份、要不要先请示。

        判决表（每一格都只有一种结局，三态不折平）：
        | 输入 | 结局 | 谁执行 |
        |---|---|---|
        | 没带确认键、`washed == original` | `outcome=""`（无事发生） | 直接执行原稿（不进第二段） |
        | 没带确认键、`washed != original` | `outcome="wash_proposed"` + `issue=True` | 谁都不执行（0 行新任务、0 次子任务调用） |
        | `accept_proposal=<id>` 且编号与载荷都对得上 | `accepted=True` | 用 `washed` |
        | `reject_proposal=<id>` 且编号与载荷都对得上 | `accepted=False` | 用 `original` |
        | 编号查不到 / 指纹对不上 / 两个都给了 | `problem` 非空 | 谁都不执行（受控拒绝） |
        "洗不动/没洗成"（`wash.checked=False`）按"没有差异"处理 —— 这一格秘书什么都没主张，本来也不该挡下一步
        （`fail-open` 的同一条纪律）。
        """
        body = dict(original or {})
        checked = bool(wash.get("checked"))
        washed = dict((wash.get("payload") or body) if checked else body)
        changes = [dict(c) for c in (wash.get("changes") or ())]
        keys, diff = self._wash_diff(body, washed, changes)
        plan: dict[str, Any] = {
            "outcome": "", "proposal_id": "", "issue": False,
            "original": body, "washed": washed,
            "accepted": None, "executed_with": "", "execute": {},
            "changes": [self._change_line(c) for c in changes],
            "changed_keys": keys, "diff": diff,
            "problem": "",
        }
        want_accept = str(accept or "").strip()
        want_reject = str(reject or "").strip()
        if want_accept and want_reject:
            plan["problem"] = (f"同一步同时给了 {ACCEPT_PROPOSAL} 与 {REJECT_PROPOSAL} "
                               "⇒ 不知道该按哪一份派（两份都没派）")
            return plan
        want = want_accept or want_reject
        if want:
            row = self.find_proposal(want)
            if row is None:
                plan["problem"] = (f"台账里没有请示 {want!r}（编号由秘书发，不许自己拼）"
                                   "⇒ 这一趟没有派活")
                plan["proposal_id"] = ""
                return plan
            got_fp = str(row.get("proposal_fingerprint") or "")
            try:
                want_fp = self.proposal_fingerprint(body)
            except Exception as exc:  # noqa: BLE001 —— 算不出指纹 ⇒ 判不了，不许当成"对得上"
                plan["problem"] = (f"这份载荷算不出指纹（{type(exc).__name__}）⇒ "
                                   "确认不成立，这一趟没有派活")
                return plan
            if got_fp and got_fp != want_fp:
                plan["problem"] = (f"请示 {want!r} 是对**另一份**载荷发的（指纹不一致）⇒ "
                                   "不能拿它确认这一份，这一趟没有派活")
                plan["proposal_id"] = want
                return plan
            plan["proposal_id"] = want
            plan["accepted"] = bool(want_accept)
            plan["execute"] = dict(washed if want_accept else body)
            plan["executed_with"] = "washed" if want_accept else "original"
            return plan
        if checked and keys and washed != body:
            plan["outcome"] = OUTCOME_WASH_PROPOSED
            plan["issue"] = True
        return plan

    def _action_spec(self, role: str, action: str) -> Any:
        """该角色该动作的声明（读不到 ⇒ `None`，调用方按"这一格没洗成"处理）。"""
        try:
            from . import capabilities as C

            return C.find_action(role, action)
        except Exception:  # noqa: BLE001 —— 声明读不到不是"没有这个动作"
            return None

    def _param_props(self, spec: Any) -> list[str]:
        """该动作声明的参数键名（空列表 = 这一格判不了，绝不读成"没有参数"）。"""
        try:
            props = dict(getattr(spec, "params", None) or {}).get("properties") or {}
        except Exception:  # noqa: BLE001
            return []
        return [str(k) for k in props]

    def assess_delegation(self, *, to: str, action: str, params: Mapping[str, Any],
                          input_key: str = "", duplicates: Sequence[Mapping[str, Any]] = (),
                          novel: bool = False, reuse: str = "", base: str = "") -> dict[str, Any]:
        """职责 2：委派评估（"收件方真做得到吗、该不该派"）。

        结论 ∈ :data:`DECISIONS` 的四档（`draft/55` §2 的 B 类）+ 理由 + 依据。不擅自改派（改派权在 M）：它只给
        建议，本体可拒绝并写明理由。同 key 的既有终态行是最重要的一条输入（`draft/53` §10：派活去重归发件方
        秘书，"该不该派"含"是不是重复"）—— 机器只把那些行摆出来，判"算重复还是正当重试"由秘书做。不止"任务
        是否符合角色设计"（业主 2026-10-09）：`surface` 那一格是"这件活在被派人的读写面里做不做得成"
        （`draft/90` §1.11）。`reuse` 给了一个名册名（复用已有子代理）时它的面是已知的 ⇒ 判得最准；新起一个时
        槽位还没分，但"越界"与"父视角有、面内没有"两档仍判得出来。`fits=False` 时它进 `reason`（当成一条"该不该
        派"的理由），但不拦（处置权在父）。
        """
        dups = [dict(r) for r in duplicates]
        alarms = self.prescreen(to=to, action=action, params=params)
        mismatch = [a for a in alarms if "动作表里没有" in a or "缺必填参数" in a]
        face = self._face_of_name(owner=str(self.task_id or ""), name=reuse) if reuse else ""
        surface = self.surface_readings("summon", {"action": action, "params": dict(params or {})},
                                        face=face, base=base)
        face_bad = surface.get("fits") is False
        if dups and not mismatch:
            decision, reason = "建议重排", (f"同 (role={to}, action={action}, "
                                          f"input_key={input_key}) 已有 {len(dups)} 条终态行"
                                          "（先看一眼是不是同一件事的重试）")
        elif mismatch:
            decision, reason = "建议重排", "；".join(mismatch)
        elif not str(action or "").strip():
            # 2026-10-21 真机缺陷（业主："秘书拦了好几回派活，看看到底是真的派活不准确还是系统缺陷"）：
            # 这一条没有点名具体动作（role 级派活：把一件活派给某个角色，而不是"调某个动作"），
            # 而下面那条判据是"这个动作在不在你的动作表里" —— 拿空动作去查，答案必然是"不在"，
            # 于是每一次 role 级派活都被建议改派。真机上 M 派 A/E/D 全被判「能力面里没有 」，
            # 而它们其实都派成了（`tasks` 里那四行就是证据）。这不是派活不准，是判据用错了对象。
            #
            # 口径：没点名动作时不拿动作表卡它（动作表管的是"调什么"，不是"派给谁"）；
            # 角色存在性与可召唤性由 `prescreen` 那一侧管。判"可派"，并在 basis 里说清为什么没查动作。
            decision, reason = "可派", ("这一条没点名具体动作（role 级派活）⇒ "
                                        "不拿动作表去卡它；角色存在性由预筛管")
            basis_note = "没点名动作 ⇒ 跳过动作表那一格（动作表管「调什么」，不管「派给谁」）"
        elif face_bad:
            # 面这一维与"能力面"是两回事：能力面说"这个动作你能做"，面说"那块盘
            # 不在你手里"—— 后者今天没有任何别的地方能在派活那一刻看出来。
            decision, reason = "建议改派", (f"{to} 这趟的面里做不成这一件："
                                          f"{surface.get('reason')}"
                                          "（要它做，就把它要用的那一块切进它的面，"
                                          "或者把这一件记成『职责之外』那一档）")
        else:
            decision, reason = "可派", "没有发现重复候选，能力面与参数都对得上"
        basis = ["specs/<role>.py 的动作表", "tasks: 同 key 的既有终态行"]
        if not str(action or "").strip():
            basis.append("没点名动作 ⇒ 动作表那一格不适用")
        if surface.get("checked"):
            basis.append("out/surfaces/<父>/<槽位>：这件活点名的路径在不在里面")
        # ---- 判断类：只有该介入时才叫模型（"切勿全写死成机器判据"的落点）。
        # 两条判断分开问，因为它们是两个问题：同 key 那些行算不算重复（`duplicate_retry`）、
        # 以及该把这条委托重排成什么（`rearrange`）。
        judged: dict[str, Any] = {"checked": False, "reason": "预筛没有报警、也没有重复候选 ⇒ 不必判断"}
        engaged = self.should_engage(alarms=alarms, duplicates=len(dups), overdue=0,
                                    novel=bool(novel))
        if engaged:
            kind = "duplicate_retry" if dups else "rearrange"
            judged = self.judge(kind, {"to": to, "action": action, "params": dict(params or {}),
                                       "input_key": input_key, "duplicates": dups[:5],
                                       "alarms": alarms,
                                       "preliminary": decision})
            if judged.get("checked"):
                # 模型的结论覆盖"预筛给的初步结论"，但它只能给建议（改派权在 M），
                # 而且只在 `checked=True` 时才被采信 —— "没查成"不冒充"可派"。
                decision = str(judged.get("decision") or decision)
                if judged.get("reason"):
                    reason = f"{reason}；判断：{judged['reason']}"
                basis = list(basis) + list(judged.get("basis") or [])
        rec = self.note_decision(
            duty=2, kind=KIND_PROPOSAL, decision=decision, reason=reason, basis=basis,
            target={"to": to, "action": action, "input_key": input_key},
            judge=judged, fail_open=False,
        )
        return {"decision": decision, "reason": reason, "basis": basis,
                "duplicates": dups, "alarms": alarms, "novel": bool(novel),
                "surface": surface,
                "judge": judged, "engaged": bool(engaged), "seq": rec.get("seq")}

    def _can_take(self, role: str, action: str) -> bool:
        """`role` 的动作表里有没有 `action`（读不到声明 ⇒ 判"能"：不冤枉）。"""
        table = self._action_table()
        if not table or str(role) not in table:
            return True
        return str(action) in table[str(role)]

    # ------------------------------------------------------------ 职责 4 / 3（收件侧）

    def rework_inbound(self, item: Mapping[str, Any]) -> dict[str, Any]:
        """职责 4：按本角色定位把收到的委托加工成贴切版本。

        不加码不减码（`draft/53` §2 的"不许做"）：只改"怎么说"，不改"要什么"。
        所以产物是"补上下文 + 明确产出物与验收口径"的补充段，原文一字不动
        （并列留痕：`draft/55` §5.1 第 3 条）。
        """
        original = dict(item)
        try:
            brief = self._role_brief(self.role)
            tail = []
            deliverable = str(brief.get("deliverable") or "").strip()
            if deliverable:
                tail.append(f"我的产出物口径：{deliverable}")
            duty = str(brief.get("duty") or "").strip()
            if duty:
                tail.append(f"我在本条线上的位置：{duty}")
            note = "\n".join(tail)
            problem = ""
            if not tail:
                problem = ("读不到本角色的 `deliverable`/`duty` ⇒ 这一格判不了"
                           "（没读成不是没问题）")
            self.note_decision(duty=4, kind=KIND_OPTIMIZED, decision="已优化",
                               reason=problem or "按本角色定位补上下文（不加码不减码）",
                               basis=["agent_prompts.ROLE_BRIEFS"],
                               before=json.dumps(original, ensure_ascii=False, sort_keys=True, default=str)[:2000],
                               after=note[:2000])
            return {"item": original, "addendum": note, "problem": problem, "fail_open": False}
        except Exception as exc:  # noqa: BLE001 - fail-open
            self.note_decision(duty=4, kind=KIND_OPTIMIZED, fail_open=True,
                               error=f"{type(exc).__name__}: {exc}",
                               reason="秘书没跑成 ⇒ 原样交给本体")
            return {"item": original, "addendum": "", "problem": f"{type(exc).__name__}: {exc}",
                    "fail_open": True}

    def inbox_todos(self, *, limit: int = 20) -> dict[str, Any]:
        """F-05 的消费端：把"还没有处理 / 还没有反馈"的委托摆出来（只读）。

        `draft/53` §10 的口径：F-05 待办/待核队列的生产端是机器（`search_requests` / `reprocess_requests` 的
        pending，以及降级/待核那些三态行），消费端是各角色自己的秘书（自己的收件箱）+ M 的秘书（全局）。本方法
        只做"摆出来"这一半，判断归 :meth:`remind_closure`。三态（R002 的口径）：`checked=False` + `reason` 表示
        "这一格没读成"（没有 store / 表读不出来），与 `todos=[]`（读成了、确实没有待办）分开报。返回值：
        `{"checked", "reason", "todos": [...], "count", "by_kind"}`，每条 `todo` 是 `{"kind", "id", "who", "state", "since"}` —— `state` 说的是"为什么它算待办"（`pending` 没做完 / `unclaimed` 没人接 / `running` 没有终态）。
        """
        if self.store is None:
            return {"checked": False, "reason": "没有 store ⇒ 收件箱这一格没读成",
                    "todos": [], "count": 0, "by_kind": {}}
        todos: list[dict[str, Any]] = []
        problems: list[str] = []
        for table, kind in (("search_requests", "search_request"),
                            ("reprocess_requests", "reprocess_request")):
            try:
                rows = self.store.rows(table)
            except Exception as exc:  # noqa: BLE001 - 读不出来如实报，不折成"没有待办"
                problems.append(f"{table}: {type(exc).__name__}: {exc}")
                continue
            for row in rows:
                if row.get("done"):
                    continue
                who = str(row.get("claimed_by") or "")
                todos.append({
                    "kind": kind,
                    "id": str(row.get("request_id") or ""),
                    "who": who or S.CONDUCTOR_ROLE,
                    "state": "pending" if who else "unclaimed",
                    "since": str(row.get("timestamp") or ""),
                    "attempts": int(row.get("attempts") or 0),
                })
        excluded_top = 0
        try:
            for row in self.store.rows("tasks"):
                if str(row.get("status") or "") not in ("pending", "running"):
                    continue
                # 顶趟行（`action="run"`，F1 加的）不算待办：它是"用户发起的那一趟
                # 正在跑"，不是"有人提交了却没人接手"——后者才是这份收件箱要摆出来的东西。
                # 排除了几行要留在读数里（`excluded_top_level`），否则"少了几行"会被读成
                # "本来就没有"（静默漂移的另一种形态）。
                if str(row.get("action") or "") == "run":
                    excluded_top += 1
                    continue
                todos.append({"kind": "task", "id": str(row.get("task_id") or ""),
                              "who": str(row.get("role") or ""), "state": "running",
                              "since": str(row.get("started_at") or "")})
        except Exception as exc:  # noqa: BLE001 - 同上
            problems.append(f"tasks: {type(exc).__name__}: {exc}")
        todos = todos[:max(1, int(limit))]
        by_kind: dict[str, int] = {}
        for t in todos:
            by_kind[t["kind"]] = by_kind.get(t["kind"], 0) + 1
        return {"checked": not problems, "reason": "；".join(problems),
                "excluded_top_level": excluded_top,
                "todos": todos, "count": len(todos), "by_kind": by_kind}

    #: `pending_inbox` 认的既有标记（不许新造字段/词表/工具）。
    PENDING_KINDS = ("missing_bit", "missing_proof", "unverified_quote")

    def pending_inbox(self, *, scope: str = "self", window_sec: int = 86400,
                      limit: int = 50) -> dict[str, Any]:
        """F-05 的消费端：待办/待核队列（只读扫表；落进决定台账）。

        `draft/53:181` 逐字："消费端 = 各角色秘书（自己的收件箱）+ M 的秘书（全局）" ⇒ 这就是那两个口径：
        | `scope` | 看什么 |
        |---|---|
        | `"self"` | 与本角色有关的那些行（按接手方过滤） |
        | `"global"` | 全部（M 的秘书的全局视图） |
        条目只来自既有标记（不新增表/字段/工具/`status` 取值，主控裁定）：
        1. `missing_bit`：`statements` 行的 `bits` 里那一位没有值（等级由 `evidencebits.derive_grade` 现算，
           所以缺位 = 等级会降，不是"没有等级"）；
        2. `missing_proof`：`origin="own_result"` 而 `proof_text` 空（自产命题没有证明 ⇒ 现算等级是"猜想"）；
        3. `unverified_quote`：`quote_verified is None` 且这一行已经过了窗口（够久了还"没核"= 待核；
           `quote_reason` 是它自己写的"为什么还没核"）。
        每条给出 `(表, 行 id, 缺什么, 谁该接手)`：接手方从声明派生（`capabilities.WRITE_SETS` 里谁能写这张表 /
        `evidencebits.BIT_OWNERS`），不另造一张路由表。三态（R002 口径）：`checked=False` + `reason` = 这一格没
        读成（表读不出来），与"读成了、确实没有待办"（`items=[]`）分开报。有内容时逐条落 :meth:`note_decision`
        —— 只记录，不写任何库表。
        """
        if str(scope) not in ("self", "global"):
            return {"checked": False, "reason": f"scope 只能是 'self' / 'global'，收到 {scope!r}",
                    "items": [], "count": 0, "by_kind": {}}
        if self.store is None:
            return {"checked": False, "reason": "没有 store ⇒ 收件箱这一格没读成",
                    "items": [], "count": 0, "by_kind": {}}
        try:
            from . import evidencebits as EB

            bit_names = tuple(EB.BIT_NAMES)
            bit_owners = dict(EB.BIT_OWNERS or {})
            #: 位的已定取值（`evidencebits.BIT_STATES`）：`na` / `failed` / `verified`
            #: 都是"这一位问过了、有结论" ⇒ 不是待办；只有 `pending`（以及没写）才待办。
            #: 这一格如果不看状态而只看"有没有值"，`na`（不适用）会被误报成待办。
            resolved = tuple(s for s in tuple(EB.BIT_STATES) if s != "pending")
        except Exception:  # noqa: BLE001 - 位表读不到 ⇒ 那一条判据不做（不许猜位的含义）
            bit_names, bit_owners, resolved = (), {}, ()
        try:
            from . import capabilities as C

            writers: dict[str, list[str]] = {}
            for role, tables in dict(C.WRITE_SETS or {}).items():
                for table in tables:
                    writers.setdefault(str(table), []).append(str(role))
        except Exception:  # noqa: BLE001 - 同上：不知道谁接手就如实写空串
            writers = {}

        def _who(table: str, bit: str = "") -> str:
            if bit and bit_owners.get(bit):
                return str(bit_owners[bit])
            cands = sorted(writers.get(table) or [])
            return cands[0] if cands else ""

        try:
            rows = self.store.rows("statements")
        except Exception as exc:  # noqa: BLE001 - 读不出来如实报，不折成"没有待办"
            return {"checked": False,
                    "reason": f"statements 读不出来：{type(exc).__name__}: {exc}",
                    "items": [], "count": 0, "by_kind": {}}
        now = _now_iso()
        items: list[dict[str, Any]] = []
        for row in rows:
            sid = str(row.get("stmt_id") or "")
            bits = row.get("bits") if isinstance(row.get("bits"), Mapping) else {}
            for bit in bit_names:
                state = (bits or {}).get(bit)
                if isinstance(state, Mapping):
                    # 二维位（第 4 位：`{证明号: 状态}`，业主 2026-10-22）。判据是
                    # "任一条路径有结论 ⇒ 这一位问过了 ⇒ 不待办；全都 pending ⇒ 待办"。
                    # 改前这里读 `state.get("state", state.get("value"))` —— 那是给
                    # 另一种形状留的口子，对 `{证明号: 状态}` 只会取到空 ⇒ 二维位一律
                    # 被读成待办（而它可能已经验过了）。
                    settled = [EB._path_state(item) for item in state.values()]
                    settled = [one for one in settled if one != "pending"]
                    state = settled[0] if settled else "pending"
                if str(state or "") in resolved:
                    continue
                who = _who("statements", bit)
                if scope == "self" and who and who != self.role:
                    continue
                items.append({"kind": "missing_bit", "table": "statements", "id": sid,
                              "missing": bit, "who": who, "state": "pending",
                              "since": str(row.get("created_at") or ""),
                              "why": f"证据位 {bit!r} 没有值 ⇒ 等级现算会降（`derive_grade`）"})
            if str(row.get("origin") or "") == "own_result" \
                    and not str(row.get("proof_text") or "").strip():
                who = _who("statements")
                if not (scope == "self" and who and who != self.role):
                    items.append({"kind": "missing_proof", "table": "statements", "id": sid,
                                  "missing": "proof_text", "who": who, "state": "pending",
                                  "since": str(row.get("created_at") or ""),
                                  "why": "自产命题没有证明 ⇒ 现算等级是『猜想』而不是证明级",
                                  "quote_reason": str(row.get("quote_reason") or "")})
            if row.get("quote_verified") is None and _older_than(row.get("created_at"), now,
                                                                int(window_sec)):
                who = _who("statements")
                if not (scope == "self" and who and who != self.role):
                    items.append({"kind": "unverified_quote", "table": "statements", "id": sid,
                                  "missing": "quote_verified", "who": who, "state": "pending",
                                  "since": str(row.get("created_at") or ""),
                                  "why": "过了窗口还没核（`quote_verified is None`）⇒ 待核",
                                  "quote_reason": str(row.get("quote_reason") or "")})
        items = items[:max(1, int(limit))]
        by_kind: dict[str, int] = {}
        for it in items:
            by_kind[it["kind"]] = by_kind.get(it["kind"], 0) + 1
        if items:
            # 职责 3 的闭环提醒就从这里取活：只记录，不改任何库表。
            self.note_decision(
                duty=3, kind=KIND_NOTICE, decision="已提醒",
                reason=f"F-05 待办 {len(items)} 条（scope={scope}，分档 {by_kind}）",
                basis=["statements.bits / proof_text / quote_verified（只读扫表）",
                       "capabilities.WRITE_SETS 派生接手方"],
                target={"scope": str(scope), "items": items[:10]}, fail_open=False)
        return {"checked": True, "scope": str(scope), "items": items,
                "count": len(items), "by_kind": by_kind}

    def remind_closure(self, items: Sequence[Mapping[str, Any]] | None = None) -> list[dict[str, Any]]:
        """职责 3：闭环提醒（收件方盯自己的收件箱；经 M）。

        判据只有"有没有处理、有没有反馈"两条事实（`draft/53` §2 的"不许做"：
        不替本体做事、不伪造反馈）。异步、不阻塞本体；
        一次最多 :data:`MAX_REMINDERS` 条（默认 5，避免刷屏）。

        `items=None` ⇒ 自己读待办（:meth:`inbox_todos`，F-05 的消费端）；
        给了就按给的那一份判 —— "谁盯哪个收件箱"由调用方决定（M 的秘书看全局）。
        """
        if items is None:
            got = self.inbox_todos()
            items = list(got["todos"])
            if not got["checked"]:
                # 读不成不是"没有待办"：如实留痕，绝不当成清零。
                self.note_decision(duty=3, kind=KIND_NOTICE, decision="已提醒",
                                   reason=f"待办那一格没读成：{got['reason']}",
                                   basis=["tasks / search_requests / reprocess_requests"],
                                   target={"role": self.role}, fail_open=True,
                                   error=str(got["reason"]))
                return []
        out: list[dict[str, Any]] = []
        for it in list(items)[:MAX_REMINDERS]:
            task_id = str(it.get("task_id") or it.get("id") or "")
            state = str(it.get("state") or "")
            if state in ("handled", "feedback_seen", "closed"):
                continue
            if not state:
                state = "unknown"
            out.append({"task_id": task_id, "state": state,
                        "kind": str(it.get("kind") or ""),
                        "to": str(it.get("by") or it.get("who") or S.CONDUCTOR_ROLE),
                        "note": "这一条委托没有终态 / 没有反馈 ⇒ 提醒本体（经 M）"})
        if out:
            self.note_decision(duty=3, kind=KIND_NOTICE, decision="已提醒",
                               reason=f"{len(out)} 条未闭环（留痕 ≠ 被处理）",
                               basis=["tasks: 无终态行 / sessions: 无 task_end"],
                               target={"role": self.role}, fail_open=False)
            # 逐条落台账（2026-10-04 主控裁定的第 1 条："每条进决定台账"）：
            # 只落一行摘要的话，"提醒了谁、什么事、什么状态"在纸上查不到 ——
            # 而这一层唯一能自证的就是台账（`draft/55` §5.3）。
            for one in out:
                self.note_decision(
                    duty=3, kind=KIND_NOTICE, decision="已提醒",
                    reason=f"未闭环：{one['state']}（{one['task_id'] or '无 id'}）",
                    basis=["tasks: 无终态行 / sessions: 无 task_end"],
                    target={"task_id": one["task_id"], "state": one["state"],
                            "kind": one["kind"], "to": one["to"]},
                    fail_open=False)
            # 闭环提醒是异步的（`draft/55` §5.2）：不阻塞本体，所以这一格只记
            # "该不该叫秘书"的读数（要不要真叫由调用方按 `should_engage` 走）。
        self._last_closure_engage = self.should_engage(alarms=[], duplicates=0,
                                                      overdue=len(out), novel=False)
        return out

    def negotiate(self, *, with_role: str, point: str,
                  rounds: Sequence[Mapping[str, Any]] = ()) -> dict[str, Any]:
        """秘书 ⇄ 秘书协商（`draft/53` §3）：最多 2 轮，之后上报本体、再上报 M。

        本方法只记录协商这件事本身（轮次 + 结论）：真正的来回由两侧真身驱动，
        而"协商结论必须抄送本体"是硬要求（`draft/55` §5.1 第 2 条）——
        否则"任务是变过形的"这件事对本体不可见。
        """
        done = [dict(x) for x in rounds]
        if len(done) >= MAX_NEGOTIATION_ROUNDS:
            outcome, escalate = "上报本体", True
        else:
            outcome, escalate = "待回应", False
        rec = {"round": len(done) + 1, "with": f"secretary/{with_role}",
               "point": str(point), "outcome": outcome, "escalate_to_body": escalate}
        self._negotiations.append(rec)
        self.note_decision(duty=2, kind=KIND_NEGOTIATION, decision="建议重排",
                           reason=f"与 secretary/{with_role} 协商：{point}",
                           basis=["draft/53 §3"], negotiation=done + [rec],
                           target={"with": f"secretary/{with_role}"}, fail_open=False)
        return rec

    # ------------------------------------------------------------ 手稿通道（增 / 改 / 查）

    def handoff_add(self, *, to: str, summary: str, body: str, refs: Iterable[str] = (),
                    task_id: str = "", sid: str = "", note: str = "") -> dict[str, Any]:
        """增：替本体执笔一行交接手稿（`manuscripts.write`）。

        这一格不许 fail-open：写失败必须报错留痕（`draft/55` §5.2）。
        静默放行的后果是"手稿缺行"，而缺行与"没交接"在账本上长得一样 ——
        那会让下一次"这条是不是已经交接过"判错。所以这里 `raise` 之后再留痕。
        """
        try:
            rec = MS.write(self.root, sender=self.role, recipient=str(to).upper(),
                           summary=str(summary), body=str(body), refs=list(refs),
                           task_id=str(task_id), sid=str(sid), note=str(note))
        except Exception as exc:
            self.note_decision(duty=1, kind=KIND_HANDOFF, decision="已执笔",
                               reason="手稿执笔失败（这一格不许静默放行）",
                               basis=["draft/55 §5.2"], mid="", fail_open=False,
                               error=f"{type(exc).__name__}: {exc}",
                               target={"to": str(to)})
            raise
        self.note_decision(duty=1, kind=KIND_HANDOFF, decision="已执笔",
                           reason="替本体执笔一行交接手稿（sender 仍是被服务的角色）",
                           basis=["draft/55 §4 归属与审计"], mid=str(rec.get("id") or ""),
                           target={"to": str(to)}, fail_open=False)
        return rec

    def handoff_revise(self, *, mid: str, summary: str = "", body: str = "",
                       task_id: str = "", reason: str = "", note: str = "") -> dict[str, Any]:
        """改：追加一条修订行（`manuscripts.revise`，旧行保留）。

        与 :meth:`handoff_add` 同一条纪律：写失败必须报错留痕。
        `task_id`（2026-10-08 晚补）：一实例一秘书之后，每一行都要能对回实例 ——
        真机读数（`draft/89` §3）是 1562 行里 593 行没有这一格，而它们正是走
        `agent_loop._do_handoff` 那条路的（形参本来就在 `handoff_add` / `manuscripts.revise`
        上，缺的是调用点不传）。
        """
        try:
            rec = MS.revise(self.root, mid=str(mid), summary=str(summary), body=str(body),
                            task_id=str(task_id),
                            reason=str(reason), note=str(note))
        except Exception as exc:
            self.note_decision(duty=1, kind=KIND_HANDOFF, decision="已执笔",
                               reason="手稿订正失败（这一格不许静默放行）",
                               basis=["draft/55 §5.2"], mid=str(mid), fail_open=False,
                               error=f"{type(exc).__name__}: {exc}")
            raise
        self.note_decision(duty=1, kind=KIND_HANDOFF, decision="已执笔",
                           reason=f"追加修订行（订正 {mid}，旧行保留）",
                           basis=["draft/53 §2.1 改", "draft/55 §3.1"],
                           mid=str(rec.get("id") or ""), target={"revises": str(mid)})
        return rec

    def handoff_query(self, *, mid: str = "", to: str = "", sender: str = "",
                      refs: str = "", revises: str = "") -> list[dict[str, Any]]:
        """查：判"这条是不是重复委派 / 是不是已经交接过"（用户点名的"至少要能读 handoffs"）。

        纯只读；`revises` 非空时只回"订正过某一号"的那些行。
        """
        if revises:
            return MS.revisions_of(self.root, revises)
        if mid:
            got = MS.row_of(self.root, mid)
            return [got] if got else []
        out = MS.list_all(self.root, to=str(to), sender=str(sender), limit=50)
        if refs:
            out = [r for r in out if any(str(refs) in str(x) for x in (r.get("refs") or []))]
        return out

    def handoffs_digest(self, *, limit: int = 5) -> str:
        """一小段读数：最近几份交接（判重复时的起点，进提示词用）。"""
        return MS.digest(self.root, limit=limit)

    # ------------------------------------------------------------ 名册 / 对照表 / 退役（S1k）

    def _conductor(self) -> Any:
        """能读台账的那个句柄（`store` 造一个只读用的 `Conductor`）。

        为什么不要求调用方传：秘书的读面本来就是"`store` + 手稿 + registry"
        （`draft/91` §2），名册要读台账里的代理行 ⇒ 用同一把 `store` 现造一个即可。
        造不出来 ⇒ 返回 `None`，调用方按三态如实报（不许当"名下没有子代理"）。
        """
        if self.store is None:
            return None
        from .conductor import Conductor, LocalBackend

        try:
            return Conductor(self.store, policy=None, backend=LocalBackend({}))
        except Exception:  # noqa: BLE001
            return None

    def roster_rows(self, owner: str) -> tuple[list[dict[str, Any]], list[str]]:
        """名册的折叠后状态（`(项列表, 坏行)`）：一项 = 名字 / 角色 / 简介 / 状态。

        事件流折叠口径：`add` 建项；`bind` 只推当前调用；`retire` 标退役；
        `keep_alive` 只改那一格读数。只追加、不物理删（`draft/92` I-8）。
        """
        from . import jsonlfile as JF

        rows, bad = JF.read_jsonl(roster_path(self.root, owner))
        return _fold_roster(rows), bad

    def roster_index(self, owner: str) -> tuple[list[dict[str, Any]], list[str]]:
        """对照表（电话簿）的折叠后状态：一项 = 名字 → `first_task_id` / `task_id`（当前）。"""
        from . import jsonlfile as JF

        rows, bad = JF.read_jsonl(roster_index_path(self.root, owner))
        return _fold_index(rows), bad

    def retired_names(self, owner: str) -> tuple[list[dict[str, Any]], list[str]]:
        """销号名单（业主 B1）：名字一经退役永久不复用。`(行列表, 坏行)`。"""
        from . import jsonlfile as JF

        return JF.read_jsonl(retired_path(self.root, owner))

    def _used_names(self, owner: str) -> dict[str, str]:
        """该父名下"用过的所有名字"：名字 → 角色（含已收口、已销号、只在对照表里的）。

        三份盘上事实的并集，一处都不许漏：
        - 名册正文 `<父>.jsonl`（折叠后的一项一条：这是名册项的正文来源）；
        - 对照表 `<父>-index.jsonl` 的每一条调用记录里的 `name`（名册正文缺行时，
          名字只活在这里 —— D-66 的现场就是那个形态）；
        - 销号名单 `<父>-retired.jsonl`（销号的名字仍然"用过"，绝不回收）。

        为什么发号与占用判断都必须读这三份（业主 2026-10-24 的最终口径）：
        「如果一个子代理（例如 G1）被销号，且有 G2，再派 G 时追加写成 G3（不可复用 G1）」
        —— 只读正文会把"正文里没有、但确实用过"的名字算成空号，于是同一个名字被发给
        两个不同的子代理。名字是身份，用过的名字就不再是空号。
        """
        out: dict[str, str] = {}
        rows, _bad = self.roster_rows(owner)
        for row in rows:
            name = str(row.get("name") or "")
            if name:
                out.setdefault(name, str(row.get("role") or ""))
        index, _bad2 = self.roster_index(owner)
        for row in index:
            name = str(row.get("name") or "")
            if name:
                out.setdefault(name, str(row.get("role") or ""))
        for name in self._retired_used(owner):
            out.setdefault(name, "")
        return out

    def _retired_used(self, owner: str) -> list[str]:
        """销号名单里的名字（"扫已销号的名字"这一步单独一处，判据可以把它打桩成跳过）。"""
        rows, _bad = self.retired_names(owner)
        return [str(r.get("name") or "") for r in rows if str(r.get("name") or "")]

    def next_name(self, owner: str, role: str) -> tuple[str, str]:
        """下一个可用的本地名（`<角色><序号>`；用过的名字绝不回收）。返回 `(名字, 问题)`。

        序号 = 该 owner 名下该角色"用过的最大序号 + 1"。"用过"包括活跃、已收口、
        已销号，以及只在对照表里留下调用记录的名字（见 :meth:`_used_names`）——
        这正是业主 2026-10-24 的最终口径：「G1 被销号，且有 G2，再派 G 时追加写成
        G3（不可复用 G1）」。
        """
        used = self._used_names(owner)
        seen = []
        for name in used:
            if name.startswith(role) and name[len(role):].isdigit():
                seen.append(int(name[len(role):]))
        return f"{role}{max(seen, default=0) + 1}", ""

    def _reuse_refusal(self, owner: str, name: str) -> str:
        """`reuse=<名>` 这个目标能不能接活：空串 = 能，否则是一句受控拒绝的理由。

        判据只有一条（业主 2026-10-24 的最终口径）："在册且未销号"就能再接活。
        「已收口子代理可再接收活，但已销号不可用」——
        - 收口（上一件活已交差、状态 done/ended，但名册项还在册）⇒ 只是闲下来了，
          可以再接一件活；
        - 销号（名册项标了 retired、名字进了销号名单）⇒ 这个子代理退场了，名字永久
          不复用（`reuse` 指向它一律受控拒绝）。

        这一处刻意单独成一个方法：判据把它打桩成"只要在册就行"⇒ 销号那一档必须红；
        打桩成"只认活跃任务"⇒ 收口那一档必须红（`tests/test_roster_ownership_...`）。
        """
        if not self._name_exists(owner, name):
            return f"名册里没有 {name} ⇒ 不猜（复用必须父先看名册）"
        if self._is_retired(owner, name):
            return f"{name} 已销号（名字永久不复用，业主 B1）"
        return ""

    def roster_add(self, *, owner: str, role: str, task_id: str, brief: str,
                   task: str = "", task_id_first: str = "", want_name: str = "",
                   reuse: str = "", surface: str = "", new: str = "") -> dict[str, Any]:
        """名册登记（增那一支）：`{"name","role","task_id","brief","brief_written","problem"}`。

        ## 两个入口，语义不同（业主 2026-10-24）
        名册项是"一个常驻子代理"的身份（名字 / 角色 / 简介 / 读写面），不是一件活。
        一个子代理可以接好几件活，所以写入侧只有两条路：

        - `reuse=<名>`："同一个子代理再接一件活"。名册项一个字不动，只在对照表里
          追加一条调用记录（哪一件活落到了这个名字上）。合法目标 = 在册且未销号
          （收口了也可以再接活；已销号 ⇒ 受控拒绝，见 :meth:`_reuse_refusal`）。
        - `new=<角色>`（或 `want_name=<名>`，或两样都不给）："新建一个同类子代理"。
          名字由秘书发号（:meth:`next_name`）：用过的最大序号 + 1，用过的名字绝不回收
          （含已销号的）；`want_name` 点了一个用过的名字 ⇒ 受控拒绝并写清它是活跃 /
          已收口 / 已销号。要再派一个同类子代理时用这一支，不要拿旧名字挂新活。

        两个入口不许混着给（`reuse` 与 `new` / `want_name` 同时给 ⇒ 受控拒绝：那是
        两句互相矛盾的话，猜哪一句都会替调用方改主意）。

        ## 盘上落什么（`task_id` 是调用流水读数，不是归属键）
        - 名册正文 `<父>.jsonl`：`kind="add"` 一行建项（名字、角色、简介、面、创建时间）；
          `kind="retire"` 一行销号；
        - 对照表 `<父>-index.jsonl`：`kind="bind"` 一条调用记录（名字 + 这一件活的编号
          + 时间）。`task_id` / `task_name_first` 这类字段只回答"这一条/这一项是为哪件
          活落的"，不回答"这个名册项是谁" —— 名册项的身份是 `owner` + `name`
          （读侧按名字归组：一个节点 + N 件活，见 `webui.readers.roster_face`）。

        ## 简介（业主 2026-10-20）
        `brief` 缺失（空 / 纯空白）而 `task` 非空 ⇒ 秘书代写：由 `brief_from_task` 从
        任务原文派生一句（确定性、不调模型、不花钱，≤60 字、单行），登记行里那一格记
        `brief_source="secretary"`、返回 `brief_written=True`；父给的那一句记
        `brief_source="parent"`、`brief_written=False` —— 不许静默冒充"父给的"。
        `brief` 与 `task` 都空 ⇒ 拒（那句话是退役时认人的唯一依据，秘书不替它编）；
        父给的 `brief` 超长 / 多行 ⇒ 照旧拒（"超长属于内容，秘书不替它删"）。
        """
        text = str(brief or "").strip()
        source = "parent"
        if not text:
            text = brief_from_task(task)
            source = "secretary"
        if not text:
            return {"name": "", "role": str(role), "task_id": str(task_id),
                    "brief": "", "brief_written": False,
                    "problem": "没给一句任务简介（它进名册：退役时读的人靠它认人）"}
        if len(text) > BRIEF_MAX or "\n" in text:
            return {"name": "", "role": str(role), "task_id": str(task_id),
                    "brief": text, "brief_written": source == "secretary",
                    "problem": "任务简介必须是单行、不超过 60 字（超长属于内容，秘书不替它删）"}
        given = [key for key, value in
                 (("reuse", reuse), ("new", new), ("want_name", want_name)) if str(value or "")]
        if len(given) > 1:
            return {"name": str(reuse or want_name or ""), "role": str(role),
                    "task_id": str(task_id), "brief": text,
                    "brief_written": source == "secretary",
                    "problem": (f"{'、'.join(given)} 不能同时给：reuse 是「同一个子代理"
                                "再接一件活」，new / want_name 是「新建一个同类子代理」"
                                " —— 两句话互相矛盾，秘书不替调用方猜哪一句算数")}
        if str(new or "") and str(new) != str(role):
            return {"name": "", "role": str(role), "task_id": str(task_id), "brief": text,
                    "brief_written": source == "secretary",
                    "problem": f"new={new} 与 role={role} 对不上（新建的是哪个角色就写哪个）"}
        at = _now_iso()
        if reuse:
            name = str(reuse)
            refusal = self._reuse_refusal(owner, name)
            if refusal:
                return {"name": name, "role": str(role), "task_id": str(task_id),
                        "brief": text, "brief_written": source == "secretary",
                        "problem": refusal}
            bind: dict[str, Any] = {"kind": "bind", "owner": owner, "name": name,
                                    "role": str(role), "task_id": str(task_id), "at": at}
            if source == "secretary":
                # 复用支不写名册项 ⇒ 这一次代写的那句话也得留痕（否则"谁写的"就丢了）。
                # 只在代写时补这两格：父给的那一支落盘逐字不变。
                bind.update({"brief": text, "brief_source": "secretary"})
            ok, why = append_jsonl(roster_index_path(self.root, owner), bind)
            if not ok:
                return {"name": name, "role": str(role), "task_id": str(task_id),
                        "problem": f"对照表没写成：{why}"}
            return {"name": name, "role": str(role), "task_id": str(task_id),
                    "brief": text, "brief_written": source == "secretary", "problem": ""}

        if want_name:
            name = str(want_name)
            if self._name_exists(owner, name):
                status = ("已销号" if self._is_retired(owner, name) else "已收口或还在用")
                problem = (f"{name} 已经用过（{status}）⇒ 受控拒绝：用过的名字不再发给"
                           "另一个子代理（要新建一个同类子代理，让秘书顺延发号，"
                           "或显式给一个没用过的名字）")
                return {"name": name, "role": str(role), "task_id": str(task_id),
                        "problem": problem}
        else:
            name, problem = self.next_name(owner, role)
            if problem:
                return {"name": "", "role": str(role), "task_id": str(task_id),
                        "problem": problem}
        # S1n（业主 T23 / B2）：造一个新子代理时同时预订一个读写面（父可以点名要哪个槽位）。
        # 拿不到面 ⇒ 受控拒绝（不许先给名字后没有面：那会造出一个"能说话但不能干活"的项）。
        got_surface = self.surface_alloc(owner=owner, want=str(surface or ""), name=name)
        if got_surface.get("problem"):
            return {"name": name, "role": str(role), "task_id": str(task_id),
                    "problem": f"读写面没定下来：{got_surface['problem']}"}
        ok, why = append_jsonl(roster_index_path(self.root, owner),
                               {"kind": "bind", "owner": owner, "name": name,
                                "role": str(role), "task_id": str(task_id), "at": at,
                                "first": True})
        if not ok:
            return {"name": name, "role": str(role), "task_id": str(task_id),
                    "problem": f"对照表没写成：{why}"}
        ok2, why2 = append_jsonl(roster_path(self.root, owner),
                                 {"kind": "add", "owner": owner, "name": name,
                                  "role": str(role), "task_id": str(task_id),
                                  "first_task_id": str(task_id_first or task_id),
                                  "brief": text, "brief_source": source,
                                  "surface": str(got_surface.get("slot") or ""),
                                  "at": at})
        if not ok2:
            return {"name": name, "role": str(role), "task_id": str(task_id),
                    "problem": f"名册没写成（对照表那一行已经落了 ⇒ 读侧会报'半份登记'）：{why2}"}
        return {"name": name, "role": str(role), "task_id": str(task_id),
                "brief": text, "brief_written": source == "secretary",
                "surface": str(got_surface.get("slot") or ""), "problem": ""}

    def open_solo_entry(self, *, task_id: str, task: str = "", brief: str = "") -> dict[str, Any]:
        """给"用户指定单条执行"开一条名册行与一个读写面槽位（`owner` = 它自己的任务号）。

        ## 为什么需要这一格（业主 2026-10-22 的 B-5 裁定）

        B-5：「L 的形式化验证成本极高 ⇒ 在全部研究和论文落定之后，用户指定有形式化验证
        需求时，要一条才做一条」。B-5 之后业主 2026-10-22 晚的最终裁定又给了它一条入口
        （「只有 B 可以派 L」），所以这一格今天不只在 `run-agent L` 上用到：被 B 派的那一趟
        走父的秘书登记，而用户指定单条起的那一趟没有父，走本方法。而业主要求"单条执行时
        同样有台账号、名册行、读写面" —— 那三样在"被父派活"那一档是由父的秘书在
        `Conductor._register_roster` 里落的，单条执行时没有父，于是没有任何人落它们。

        这里补的就是那一个缺失：把"这一趟"登记进它自己名下的名册（`owner` 与
        `task_id` 都是这一趟的绝对编号），并从池里取一个槽位。语义上它不是"父子关系"，
        而是"这一趟的名册里只有我一个"—— 退役、寻址、读写面切割读的都是同一份行，
        与派活那一档逐字同形（键集由 `roster_add` 决定，本方法不另写一份）。

        fail-open：拿不到面 / 登记被拒 ⇒ 返回 `problem`，不抛（少一份名册不许带走这一趟）。
        """
        owner = str(task_id or "").strip()
        if not owner:
            return {"name": "", "surface": "", "problem": "没有任务号 ⇒ 名册上没地方登记"}
        got = self.roster_add(owner=owner, role=str(self.role), task_id=owner,
                              brief=str(brief or ""), task=str(task or ""))
        return {"name": str(got.get("name") or ""),
                "surface": str(got.get("surface") or ""),
                "problem": str(got.get("problem") or "")}

    # ---- 读写面与槽位池（S1n）
    def surface_rows(self, owner: str) -> tuple[list[dict[str, Any]], list[str]]:
        """池的折叠视图（`(槽位列表, 坏行)`）。"""
        from . import jsonlfile as JF

        rows, bad = JF.read_jsonl(surfaces_path(self.root, owner))
        return _fold_surfaces(rows), bad

    def surface_state(self, owner: str) -> dict[str, Any]:
        """池的三态读数：`{"checked","in_use":[{slot,name}],"free":[…],"pending_release":[…],"reason"}`。

        读不成 ⇒ `checked=False`（不许返回空池冒充"都空闲"）。
        """
        try:
            rows, bad = self.surface_rows(owner)
        except Exception as exc:  # noqa: BLE001
            return {"checked": False, "in_use": [], "free": [], "pending_release": [],
                    "reason": f"{type(exc).__name__}: {exc}"}
        if bad:
            return {"checked": False, "in_use": [], "free": [], "pending_release": [],
                    "reason": f"池事件有 {len(bad)} 行读不出来：{bad[0]}"}
        return {"checked": True,
                "in_use": [{"slot": r["slot"], "name": r["name"]} for r in rows
                           if r["state"] == "在用"],
                "free": [r["slot"] for r in rows if r["state"] == "空闲"],
                "pending_release": [{"slot": r["slot"], "name": r["name"],
                                     "reason": r.get("reason", "")} for r in rows
                                    if r["state"] == "待释放"],
                "reason": ""}

    def surface_alloc(self, *, owner: str, want: str = "", name: str = "") -> dict[str, Any]:
        """从池里取一个干净的槽位给 `name` 用（派活那一刻，与 `roster_add` 同一趟）。

        - `want` 给了 ⇒ 要求它是空闲的（在用 / 待释放 ⇒ 受控拒绝，不静默换一个）；
        - 没给 ⇒ 取"空闲里最小的"；池里没有空闲 ⇒ 新建一个（`S<两位数>`，序号只增不减）；
        - 返回 `{"slot","path","problem"}`；拿不到 ⇒ `problem` 非空（调用方按受控拒绝处理）。
        """
        state = self.surface_state(owner)
        if not state.get("checked"):
            return {"slot": "", "path": "", "problem": f"池没读成（{state.get('reason')}）"}
        in_use = {str(x["slot"]) for x in state["in_use"]}
        pend = {str(x["slot"]) for x in state["pending_release"]}
        if want:
            slot = str(want)
            if slot in in_use or slot in pend:
                return {"slot": slot, "path": "",
                        "problem": f"槽位 {slot} 不在空闲池里（在用或待释放）⇒ 受控拒绝"}
        else:
            free = sorted(state["free"])
            if free:
                slot = free[0]
            else:
                used = in_use | pend | {str(x) for x in state["free"]}
                n = 1
                while f"S{n:02d}" in used:
                    n += 1
                slot = f"S{n:02d}"
        path = surface_dir(self.root, owner, slot)
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return {"slot": slot, "path": "", "problem": f"面建不出来：{type(exc).__name__}: {exc}"}
        ok, why = append_jsonl(surfaces_path(self.root, owner),
                               {"kind": "alloc", "owner": owner, "slot": slot,
                                "name": str(name), "at": _now_iso()})
        if not ok:
            return {"slot": slot, "path": str(path), "problem": f"池事件没写成：{why}"}
        return {"slot": slot, "path": str(path), "problem": ""}

    def surface_release(self, *, owner: str, name: str, slot: str) -> tuple[str, str]:
        """归还一个槽位：先归档面里的东西，再写 `release`；归档失败 ⇒ `archive_failed`
        （槽位停在"待释放"、不入池）。返回 `(落成的状态, 问题)`。"""
        src = surface_dir(self.root, owner, slot)
        dst = archive_dir(self.root, owner, name)
        state = "空闲"
        if src.is_dir() and any(src.iterdir()):
            try:
                dst.parent.mkdir(parents=True, exist_ok=True)
                if dst.exists():
                    import shutil

                    shutil.rmtree(dst)
                import shutil

                shutil.move(str(src), str(dst))
                src.mkdir(parents=True, exist_ok=True)
            except Exception as exc:  # noqa: BLE001 —— 没归档干净就不许放回池
                state, why = "待释放", f"{type(exc).__name__}: {exc}"
                append_jsonl(surfaces_path(self.root, owner),
                             {"kind": "archive_failed", "owner": owner, "slot": slot,
                              "name": str(name), "reason": why, "at": _now_iso()})
                return state, why
        ok, why2 = append_jsonl(surfaces_path(self.root, owner),
                                {"kind": "release", "owner": owner, "slot": slot,
                                 "name": str(name), "at": _now_iso()})
        if not ok:
            return "待释放", f"池事件没写成：{why2}"
        return state, ""

    def surface_of(self, *, owner: str, task_id: str) -> dict[str, Any]:
        """某个调用行「此刻」该用的读写面：`{"checked","name","slot","path","reason"}`。

        为什么必须两步查（实测踩过）：`task_id` 的当前值在对照表里（`_fold_index`
        认 `bind`），而名册的 `add` 行记的是第一次那个调用 ⇒ 只读名册会把
        "复用过的名字"（`draft/92` I-12）判成"这一行没有面"，于是那一趟静默不切面。
        顺序：对照表 `task_id → name`，再名册 `name → surface`。

        已退役 ⇒ `checked=False`：退役时槽位已经归还池里，可能已经分给别人了，
        照旧读出那个槽位就等于让两个人的面重叠（跨代理写同一份文件）。
        读不成一律 `checked=False`（调用方按"没切面"处理，不许假装切过）。
        """
        name, why = self.name_of(owner=owner, task_id=str(task_id))
        if not name:
            return {"checked": False, "name": "", "slot": "", "path": "",
                    "reason": why or f"对照表里没有 {task_id!r}"}
        rows, bad = self.roster_rows(owner)
        if bad:
            return {"checked": False, "name": name, "slot": "", "path": "",
                    "reason": f"名册有 {len(bad)} 行读不出来：{bad[0]}"}
        item = next((r for r in rows if str(r.get("name") or "") == name), None)
        if item is None:
            return {"checked": False, "name": name, "slot": "", "path": "",
                    "reason": f"名册里没有 {name}（对照表里有 ⇒ 半份登记）"}
        if item.get("retired"):
            return {"checked": False, "name": name, "slot": "", "path": "",
                    "reason": f"{name} 已退役 ⇒ 面已归还池里（不照旧读，免得与别人重叠）"}
        slot = str(item.get("surface") or "")
        if not slot:
            return {"checked": False, "name": name, "slot": "", "path": "",
                    "reason": f"{name} 名下没登记读写面（老项或补登记）"}
        return {"checked": True, "name": name, "slot": slot,
                "path": str(surface_dir(self.root, owner, slot)), "reason": ""}

    # ------------------------------------------------- 命题的写入代理（S1o）

    def wash_statement(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """洗一条命题载荷的格式面（业主 2026-10-09 四件活的第一件）。

        业主逐字：「写入侧应该都是B的活，让B的秘书帮它洗格式、拿编号、改表、查重，即B不直接用增工具，秘书实际
        操作增、改（比如一个定理在两个文献中都有证明，可以互相借鉴把证明写好点；如果证明路径不唯一，可增另一组
        依赖，实现用二维列表）、查工具，B纯粹负责消化理解。」返回（三态必须分得开，与 :meth:`wash_delegation` 同族）：
        | 结局 | 返回 |
        |---|---|
        | 洗过了、本来就是受控形状 | `{"checked": True, "washed": False, "changes": []}` |
        | 洗过了、改了格式格 | `{"checked": True, "washed": True, "changes": [...]}` |
        | 这一格没洗成 | `{"checked": False, "reason": …}`（调用方按"洗不动"处理） |
        ## 可以洗什么（只动格式面）：键名归一（`STATEMENT_KEY_ALIASES` 里的别名 ⇒ 正名；正名已在 ⇒ 不覆盖，
        两条同名写法并存时原样留着，交给写入那一层去判"重复"）；顶层折叠（`params` / `statement` / `payload` 里
        裹着的那一份命题字段摊上来）；去空白（字符串值的首尾空白）；`deps` 摊平（二维列表是正形，给一维列表
        ⇒ 包成 `[一层]`）；每一步的键名归一（`stmt`/`stmt_id`/`statement_id` ⇒ `stmt_id`，`exp`/`experiment_id`
        ⇒ `experiment_id`，`lit`/`lit_id` ⇒ `lit_id`，`doc`/`doc_id` ⇒ `doc_id`）。
        ## 一个字不许动什么（内容面）：`statement_full` / `proof_text` / `label` / 别名 / 每一步的 id 本身。
        所以这里只搬键、只去空白，从不把缺键补成默认值（补默认值 = 替 B 编内容）。
        """
        before = dict(payload or {})
        out: dict[str, Any] = {"checked": True, "washed": False, "changes": [],
                               "payload": before, "before": before, "refused": "",
                               "reason": ""}
        try:
            folded = self._fold_statement(before, out)
            keyed, changes = self._normalize_statement_keys(folded, out)
            keyed["deps"], dep_changes = _wash_dep_groups(keyed.get("deps"))
            out["changes"].extend(dep_changes)
            out["payload"] = keyed
            out["washed"] = bool(out["changes"])
            return out
        except Exception as exc:  # noqa: BLE001 —— 洗不动不许打断这一次写入
            out.update(checked=False, washed=False, payload=before,
                       reason=(f"洗命题的格式没跑成（{type(exc).__name__}: {exc}）"
                               "⇒ 这一笔不写（写入路径上'洗不动'按受控拒绝处理，"
                               "不许拿没洗过的载荷去落盘）"))
            return out

    def _fold_statement(self, payload: dict[str, Any],
                        out: dict[str, Any]) -> dict[str, Any]:
        """把裹在 `params`/`statement`/`payload` 里的那一份摊到顶层（只摊认得的键）。"""
        folded = dict(payload)
        for wrapper in ("params", "statement", "payload", "result"):
            inner = folded.get(wrapper)
            if not isinstance(inner, Mapping):
                continue
            moved: list[str] = []
            for key, value in dict(inner).items():
                name = str(key)
                if name in STATEMENT_PARAM_KEYS and name not in folded:
                    folded[name] = value
                    moved.append(name)
            if moved:
                folded.pop(wrapper, None)
                out["changes"].append(f"{wrapper}: 顶层折叠 {sorted(moved)}")
        return folded

    def _normalize_statement_keys(self, payload: dict[str, Any],
                                  out: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
        """键名归一 + 字符串去空白（正名已在 ⇒ 不覆盖）。"""
        keyed: dict[str, Any] = {}
        changes: list[str] = []
        for raw_key, value in payload.items():
            key = str(raw_key)
            if key not in STATEMENT_PARAM_KEYS:
                candidate = _statement_key_candidate(key)
                if candidate:
                    if candidate in payload:
                        keyed[key] = value          # 两种写法并存 ⇒ 两条都留着，让写入层去判
                        continue
                    changes.append(f"{key} → {candidate}")
                    key = candidate
            if isinstance(value, str):
                stripped = value.strip()
                if stripped != value:
                    changes.append(f"{key}: 去首尾空白")
                value = stripped
            keyed[key] = value
        out["changes"].extend(changes)
        return keyed, changes

    # ------------------------------------------------------------ 命题同一性（模型判）

    def _proposition_candidates(self, full: str, *,
                                rows: Iterable[Mapping[str, Any]] | None = None
                                ) -> list[dict[str, Any]]:
        """粗筛交给秘书看的候选（命题性的、可用的、有号有正文的那几行）。

        过滤的三条与 `_same_proposition_candidate` 逐字同源（它守的是同一件事，只是那一格
        在"没有模型"时兜底）：只留命题性的 kind（`PROPOSITION_KINDS`：概念/定义不是命题）、
        跳过 `schema.STATEMENT_UNUSABLE_STATUSES` 的行（被否证/被取代的行不能当并入口）、
        跳过没号或正文空的行。排序与截断交给 `propositionkey.candidates_for`（唯一一处）。
        """
        pool = rows if rows is not None else None
        if pool is None:
            store = getattr(self, "store", None)
            if store is None:
                return []
            try:
                pool = store.rows("statements")
            except Exception as exc:  # noqa: BLE001 —— 读不到就没有候选（调用方据 basis 说清）
                self._log(f"命题候选读不出来：{type(exc).__name__}: {exc}")
                return []
        keep: list[dict[str, Any]] = []
        for r in pool:
            if not str(r.get("stmt_id") or "").strip():
                continue
            if not _is_proposition_kind(r.get("kind")):
                continue
            if str(r.get("status") or "") in S.STATEMENT_UNUSABLE_STATUSES:
                continue
            if not str(r.get("statement_full") or "").strip():
                continue
            keep.append(dict(r))
        # 候选里也带上"这条已有几份证明"：秘书凭它一眼看出"这是同一个定理的第几种证法"。
        from . import verifications as VR   # 惰性：证明清单的唯一读口径

        picks = _PK.candidates_for(full, keep, limit=PROPOSITION_VERDICT_CANDIDATES)
        by_id = {str(r.get("stmt_id") or ""): r for r in keep}
        for pick in picks:
            row = by_id.get(str(pick.get("stmt_id") or ""), {})
            pick["proof_nos"] = [int(no) for no, _t in VR.proof_list(row)] if row else []
            pick["statement_full"] = str(pick.get("statement_full") or "")[
                :PROPOSITION_VERDICT_TEXT_CHARS]
        return picks

    def adjudicate_proposition(self, stmt_like: Mapping[str, Any] | str, *,
                               rows: Iterable[Mapping[str, Any]] | None = None,
                               task_id: str = "") -> dict[str, Any]:
        """这一条与在册的哪一条是同一个定理（一次模型调用，三态，按正文 sha256 缓存）。

        业主 2026-10-24 的两句（唯一权威）：「不用机械判据，让秘书洗定理名，让秘书判」；
        「定理描述一致（什么条件推出什么结论），就是一个定理」。

        所以这一格做两件事，一次调用做完：
        ① 洗定理名：`Sylow 三定理（路线一：类方程/强归纳 + 共轭作用，自证草稿，待 V 审签）`
           ⇒ `canonical_name = "Sylow 三定理"`，被洗掉的"路线一：…"进 `route`
           （它不丢：落进证明那一层，见 :func:`proof_route_of`）；
        ② 判是不是同一个命题：读条件与结论，给 same / different / unknown，
           判 same 时点名并进哪一条（`same_as`）。

        ## 三态与依据（返回）
        | 结局 | 返回 |
        |---|---|
        | 判同一 | `checked=True` + `verdict="same"` + `same_as=<stmt_id>` + `canonical_name` |
        | 判不同 | `checked=True` + `verdict="different"`（不并，新建） |
        | 判不了 | `checked=True` + `verdict="unknown"`（不并，留 `basis`） |
        | 没查成 | `checked=False` + `reason`（没缝 / 开关关着 / 超时 / 坏 JSON / 词表外结论） |

        `basis` 是那一趟的判词（条件一句 + 结论一句 + 一句理由），三态都要有：
        "判不了"也必须留下"缺的是条件还是结论"，否则下一次还是判不了。
        `same` 而 `same_as` 指不出一个候选号 ⇒ 当场降成 `unknown`：凭一个指不出来的号
        合并，等于替它编一条依据（与"模型给的结论不在词表里就不采信"同一条纪律）。

        ## 为什么按正文 sha256 缓存（`out/secretary/proposition_verdicts.jsonl`）
        判定的对象是那段正文；同一条正文换个标签、重试、换个人再交一次，结论不会有别的
        答案，而每一次都要真发一次调用。真机 sylow4 的形态正好是"同一条定理交了三遍"——
        没有这一层就是三笔钱买同一句话。只缓存判过的（`checked=True`）：没查成不许缓存，
        那会把"这一次没查成"变成"以后都别查了"。
        `reused=True` + `cost.reason="没发调用（沿用缓存）"` 是"这一趟没花钱"的唯一读数。
        """
        if isinstance(stmt_like, str):
            stmt_like = {"statement_full": stmt_like}
        full = str(stmt_like.get("statement_full") or "")
        label = str(stmt_like.get("label") or "")
        kind = str(stmt_like.get("kind") or "theorem")
        out: dict[str, Any] = {
            "checked": False, "verdict": _PK.STATE_UNKNOWN, "canonical_name": "",
            "same_as": "", "route": "", "condition": "", "conclusion": "",
            "basis": "", "reason": "", "label": label, "kind": kind,
            "candidates": [], "cost": {"ledger": "", "reason": "没发调用（还没判）"},
            "reused": False, "cached": False, "statement_sha256": "",
            #: 这一格到底有没有"试过"：有缝且开关开着才是试过。
            #:
            #: 它与 `checked` 是两根轴（三态之外再分一层）：`attempted=False` 是"这一名
            #: 秘书根本没有判同一性这一路"（没缝），`attempted=True` + `checked=False` 是
            #: "试了、没查成"（超时 / 坏 JSON）。盘上要不要留痕由它决定 —— 没有缝的秘书
            #: 写出来的行必须与改前逐字节相同（否则"这一段正文之前长什么样"被一个从来
            #: 没发生过的判定改写了）。
            "attempted": bool(self.seam is not None and self.enable_model),
        }
        if not _is_proposition_kind(kind):
            out["reason"] = (f"kind={kind!r} 不在命题性的那几档 {list(PROPOSITION_KINDS)} 里 "
                             "⇒ 不是命题，不参与同一性判定（也不洗它的名字）")
            return out
        if not full.strip():
            out["reason"] = "命题正文是空的 ⇒ 没有可判的东西（不洗名、不并）"
            return out
        key = _proposition_verdict_key(full)
        out["statement_sha256"] = key
        cached = self._proposition_verdicts.get(key) or proposition_verdict_of(self.root, full)
        if cached:
            out.update(
                checked=True,
                verdict=str(cached.get("verdict") or _PK.STATE_UNKNOWN),
                canonical_name=str(cached.get("canonical_name") or ""),
                same_as=str(cached.get("same_as") or ""),
                route=str(cached.get("route") or ""),
                condition=str(cached.get("condition") or ""),
                conclusion=str(cached.get("conclusion") or ""),
                basis=str(cached.get("basis") or ""),
                reused=True, cached=True,
                cached_at=str(cached.get("at") or ""),
                cached_label=str(cached.get("label") or ""),
                cost={"ledger": "", "reason": "没发调用（沿用缓存：同一段正文判过一遍）"},
                # 候选表照旧摆出来：读的人要能核对"沿用这一次判定的那批候选还在不在"。
                candidates=self._proposition_candidates(full, rows=rows))
            return out
        candidates = self._proposition_candidates(full, rows=rows)
        out["candidates"] = candidates
        context = {
            # 这一条给三倍于候选的篇幅：它是要被判的那一条，缺了一半就没法判。
            "statement_full": full[: PROPOSITION_VERDICT_TEXT_CHARS * 3],
            "label": label,
            "kind": kind,
            "candidates": [{"stmt_id": c["stmt_id"], "label": c["label"],
                            "proof_nos": c.get("proof_nos") or [],
                            "statement_full": c["statement_full"]} for c in candidates],
            "how_to_judge": ("只比条件与结论；条件强弱不同 ⇒ different；"
                             "条件只是记号/等价改写 ⇒ same；写不清 ⇒ unknown"),
        }
        got = self.judge("proposition_identity", context, task_id=task_id)
        out["cost"] = dict(got.get("cost") or {})
        out["judged_elapsed_sec"] = got.get("elapsed_sec")
        if not got.get("checked"):
            out["checked"] = False
            out["reason"] = str(got.get("reason") or "这一格没查成（原因不明）")
            return out
        out["checked"] = True
        out["verdict"] = str(got.get("decision") or _PK.STATE_UNKNOWN)
        out["canonical_name"] = str(got.get("canonical_name") or "").strip()
        out["same_as"] = str(got.get("same_as") or "").strip()
        out["route"] = str(got.get("route") or "").strip()
        out["condition"] = str(got.get("condition") or "").strip()
        out["conclusion"] = str(got.get("conclusion") or "").strip()
        out["reason"] = str(got.get("reason") or "")
        parts = [str(x).strip() for x in (got.get("basis") or []) if str(x).strip()]
        out["basis"] = "；".join(parts + ([out["reason"]] if out["reason"] else []))
        if out["verdict"] == _PK.STATE_SAME:
            ids = [str(c["stmt_id"]) for c in candidates]
            if out["same_as"] not in ids:
                out["verdict"] = _PK.STATE_UNKNOWN
                out["reason"] = (
                    f"模型判 same，但 same_as={out['same_as']!r} 不是候选表里的号"
                    f"（候选 {ids or '空'}）⇒ 不并：凭一个指不出来的号合并，等于替它编一条依据")
                out["basis"] = "；".join(parts + [out["reason"]])
        try:
            row = append_proposition_verdict(
                self.root, statement_full=full, verdict=out["verdict"],
                canonical_name=out["canonical_name"], same_as=out["same_as"],
                route=out["route"], label=label, condition=out["condition"],
                conclusion=out["conclusion"], basis=out["basis"],
                role=str(self.role or ""), task_id=str(task_id or self.task_id or ""))
            self._proposition_verdicts[key] = dict(row)
            out["cached"] = True
            out["cached_at"] = str(row.get("at") or "")
        except OSError as exc:
            # 缓存写不成不影响这一趟的结论（结论已经在返回值里），但必须说出来：
            # 写不成意味着下一趟还要再花一次钱。
            out["cache_problem"] = f"{type(exc).__name__}: {exc}"
            self._log(f"命题判定台账没写成：{out['cache_problem']}")
        return out

    @staticmethod
    def _annotate_proposition(row: dict[str, Any], adj: Mapping[str, Any], *,
                              proof_no: int = 1, route: str = "") -> dict[str, Any]:
        """把"这一次判定"与"这条路子"落到命题行上（只加读数键，不动 schema）。

        ## 两格，各管一件事
        - `_proof_routes = {证明号: 一句话}`：这条路线的说明。业主 2026-10-24：
          「路线写在证明这一层」—— 它从此不住在 label 里，也不再丢（洗名不是丢信息）。
        - `_proposition_adjudication = {verdict, basis, ...}`：这一条是凭哪一次判定落成
          现在这样的。判 different / unknown 的也要落：只落 same 的记录，读的人就分不出
          "判过了、不同"与"没人判过"（三态纪律在盘上也要分得开）。
        这两个键都不在 `schema.Statement` 里 —— store 落的是 JSON 行，`row_from_dict` 只取
        它认识的键（与 `_proposition_matches` / `proof_history` 同一做法），所以不必动 schema。
        """
        out = dict(row)
        if str(route or "").strip():
            routes = dict(out.get(PROOF_ROUTES_KEY) or {})
            routes[str(int(proof_no or 1) or 1)] = str(route).strip()
            out[PROOF_ROUTES_KEY] = routes
        if adj and (adj.get("checked") or adj.get("attempted")):
            out["_proposition_adjudication"] = {
                "checked": bool(adj.get("checked")),
                "attempted": bool(adj.get("attempted")),
                "verdict": str(adj.get("verdict") or ""),
                "canonical_name": str(adj.get("canonical_name") or ""),
                "same_as": str(adj.get("same_as") or ""),
                "basis": str(adj.get("basis") or ""),
                "reason": str(adj.get("reason") or ""),
                "reused": bool(adj.get("reused")),
                "at": S.now_iso(),
            }
        return out

    def record_statement(self, payload: Mapping[str, Any], *, role: str = "B",
                         force_new: bool = False) -> dict[str, Any]:
        """B 交内容 ⇒ 秘书落盘（洗格式 / 拿编号 / 查重 / 改表四件一次做完）。

        业主逐字见 :meth:`wash_statement`。B 自己一次写工具都不调：这里是一笔事务（`statements` +
        `dependencies`），B 那一侧只交内容。## 返回（读的人要能分辨"没写"的四种原因）：
        | 结局 | 返回 |
        |---|---|
        | 写成了 | `{"checked": True, "created": True, "stmt_id": …, "deps_written": n, "path_groups": k}` |
        | 同内容已有一条 | `{"checked": True, "created": False, "duplicate": True, "stmt_id": <既有>}` |
        | 同内容 + 更强的证据档（有凭据） | `{"checked": True, "created": False, "upgraded": True, "stmt_id": <既有>, "changes": [...]}` |
        | 受控拒绝（一行都不落） | `{"checked": False, "refused": "<理由码>", "reason": …}` |
        理由码：`secretary_unavailable`（没装 store）、`not_statement_writer`（不是 B 的活）、`wash_failed`（格式
        洗不动）、`unresolved_dependency`（依赖指着一个不在册的 id）、`unknown_lit_id`（出处不在册）、
        `empty_statement`（命题缺 `statement_full` —— 只有短版不算数）。概念的定义空着不是拒绝：它落成
        `pending_definition` + 待补标记（`D12` 甲）。
        ## 同一命题 / 同种证明（业主 2026-10-24）
        登记时先按 `statement_full` 的规范化值查重（老口径，逐字不变）；老口径没命中时再判
        "是不是同一条命题"（`propositionkey.same_proposition`：确定性键相同，或词面相似度
        ≥ `same_proposition_jaccard`）。命中 ⇒ 不新建命题行，而是那条命题的第 N 份证明：证明
        落 `proofs` 清单（canonical 空时落 `proof_text`）、依赖落 `used_by="stmt:#pN"`。
        没有证明正文的重复登记不进这一支（它不产生"第 N 份证明"，老口径原样保留）。
        同一命题下新交来的证明与在册某一份同种（`proof_same_kind`，相似度 ≥
        `proof_same_jaccard`）⇒ 不新增证明号，受控拒绝并点名第几份；调用方给 `merge=True`
        并交合并稿时，合并稿成为那一份证明的新版本、旧正文进 `proof_history`，且要求 V 重签
        （`resign_required=True`，未重签前读侧现算为未成立）。
        ## 为什么"洗不动"在这里是硬拒（而在派活那条路上不是）：派活洗不动可以原样发出去，让下游闸门去拒
        （`refused` 行本身就是证据）；写入这条路上没有下游闸门：`Statement.validate` 只查形状，而"键名是别名"这种错会让内容静默落成空字段。
        写是不可逆的，所以这里选"不写"（与 `draft/90` §1.2 对"硬拒"的取舍同一条理由：拒绝是受控的，静默写坏不是）。
        ## 依赖的二维列表（业主指定形状）：`deps` 外层 = 可选路径、内层 = 一条路径上的步骤 ⇒ 外层下标（从 1 起）
        写进 `Dependency.path_group`（组内 AND / 组间 OR，见 `draft/97` §12.1）。每一步的 `kind` 决定它落哪一格
        来源（`source_stmt_id` / `source_experiment_id` / `source_lit_id` / `source_doc_id`）；指向的 id 必须在册，
        否则整笔不写（不许留一条挂空号的依赖 —— 那正是"依赖图静默少一环"的成因）。
        """
        out: dict[str, Any] = {"checked": False, "created": False, "duplicate": False,
                               "upgraded": False, "merged": False, "merged_into": "",
                               "merged_same_kind": False, "proof_no": 0,
                               "matched_by": "", "similarity": 0.0, "same_kind": [],
                               "proposition_state": "", "proposition_reason": "",
                               #: 命题同一性判定的三态读数（见 `_adjudication_reading`）。
                               #: 空字典 = 这一笔没走到那一格（例如 `force_new` 早退）。
                               "adjudication": {},
                               #: 洗过的定理名与"洗掉了什么"（业主 2026-10-24：让秘书洗定理名）。
                               "canonical_name": "", "label_washed": {},
                               #: 这一笔的证明自己的路子说明（路线住在证明这一层）。
                               "proof_route": "",
                               "resign_required": False, "reviewed": False,
                               "stmt_id": "", "deps_written": 0, "path_groups": 0,
                               #: 依赖面建起来没有（三态；见 `_deps_missing_reading`）。
                               #: 键一直在，值只有真写到那一格时才填 —— 拒绝那一档是空字典，
                               #: 不拿"没走那一格"冒充"依赖不缺"。
                               "deps_missing": {},
                               "tables": [], "washed": False, "changes": [],
                               "refused": "", "reason": "", "pending": []}
        if self.store is None:
            out.update(refused="secretary_unavailable",
                       reason=("这一名秘书没有 store ⇒ 写不了（B 交内容、秘书落盘是唯一"
                               "一条路：不许退回'B 自己写'）"))
            return out
        if str(role) not in STATEMENT_WRITER_ROLES:
            out.update(refused="not_statement_writer",
                       reason=(f"命题的写入侧是 B 的活（收到 role={role!r}）——"
                               f"只有 {STATEMENT_WRITER_ROLES} 能交内容给这一条路径"))
            return out
        washed = self.wash_statement(payload)
        out["washed"] = bool(washed.get("washed"))
        out["changes"] = list(washed.get("changes") or [])
        if not washed.get("checked"):
            out.update(refused="wash_failed", reason=str(washed.get("reason") or "洗格式没跑成"))
            return out
        body = dict(washed.get("payload") or {})
        full = str(body.get("statement_full") or "")
        kind = str(body.get("kind") or "theorem")
        if not full.strip():
            if kind == "concept":
                # D12 已裁（2026-10-09，业主选甲）：定义还没抽到的概念行照落 ——
                # 落成 `pending_definition`（不是依据）+ 待补标记（谁去补写在 reason 里）。
                # 不许折成 `active` + 空定义（`Statement.validate` 当场拒），
                # 也不许"干脆不落"（那样这个概念并表之后查不到）。
                return self._record_pending_concept(body, out=out)
            out.update(refused="empty_statement",
                       reason=("statement_full 是空的 ⇒ 不写（只有短版不算数：省掉假设的"
                               "命题会被下游当成无条件成立）"))
            return out
        # ---- D1（2026-10-22）：语义那一档的证据缺了就不写，并给具名理由。
        #
        # 这一格此前落到 `Statement.validate()` 里抛 `ValueError`（"标了 semantic 而缺
        # span/call"），而它抛在事务内 ⇒ 调用方拿到的是 `write_failed` 这个通用码，
        # 分不清"参数没给齐"与"盘坏了"。判据仍是同一处（`_normalize_quote_mode`），
        # 这里只是把它提前成一条写库前的可读拒绝。
        _mode = str(body.get("quote_mode") or "")
        if _mode == "semantic":
            _span = str(body.get("quote_span") or "").strip()
            _call = str(body.get("quote_call_sha256") or "").strip()
            if not _span or not _call:
                _miss = "quote_span（来源那一段逐字正文）" if not _span else \
                    "quote_call_sha256（那次语义判定的调用记录）"
                out.update(refused="quote_evidence_missing",
                           reason=(f"标了 quote_mode='semantic' 但缺 {_miss} —— 语义那一档"
                                   "必须留证据：说不出对着哪一段、哪一次判的，就不算通过。"
                                   "补上这两栏，或把 quote_verified 改成 None/False 并写明"
                                   "为什么（三态纪律：没查不许折成查过了没问题）"))
                return out
        # ---- 命题同一性：让秘书洗定理名、让秘书判（业主 2026-10-24）。
        #
        # 位置在"落盘之前、事务之外"：这一步会发一次模型调用（可以慢、可以超时），
        # 把它放进 `store.tx` 就是拿网络等待去占着写锁，而锁里不该有网络等待。
        # 读候选用的是 `self.store.rows`（只读），事务里那一份快照由 `_record_statement_tx`
        # 自己再用 `tx.rows` 核（合并前它必须确认那一条还在、还可并）。
        adjudication = self.adjudicate_proposition(
            {"statement_full": full, "label": str(body.get("label") or ""), "kind": kind})
        out["adjudication"] = self._adjudication_reading(adjudication)
        out["canonical_name"] = str(adjudication.get("canonical_name") or "")
        try:
            return self._record_statement_tx(body, full=full, kind=kind,
                                             force_new=bool(force_new), out=out,
                                             adjudication=adjudication)
        except Exception as exc:  # noqa: BLE001 —— 落盘失败必须回三态，不许半笔
            out.update(checked=False, created=False, refused="write_failed",
                       reason=f"落盘没成（{type(exc).__name__}: {exc}）⇒ 这一笔按'没写成'读")
            return out

    @staticmethod
    def _adjudication_reading(adj: Mapping[str, Any]) -> dict[str, Any]:
        """命题同一性判定的读数（进返回值与台账；不把内部候选表整份甩出去）。

        三态在这一格里必须一眼能分辨：`checked=False` 是"没查成"（没缝 / 超时），
        `verdict="unknown"` 是"查过了、判不了"。折平这两个会让"没人判过"看起来像
        "判过了、确实不同"。
        """
        got = dict(adj or {})
        return {
            "checked": bool(got.get("checked")),
            "attempted": bool(got.get("attempted")),
            "verdict": str(got.get("verdict") or _PK.STATE_UNKNOWN),
            "canonical_name": str(got.get("canonical_name") or ""),
            "same_as": str(got.get("same_as") or ""),
            "route": str(got.get("route") or ""),
            "condition": str(got.get("condition") or ""),
            "conclusion": str(got.get("conclusion") or ""),
            "basis": str(got.get("basis") or ""),
            "reason": str(got.get("reason") or ""),
            "reused": bool(got.get("reused")),
            "cached": bool(got.get("cached")),
            "candidates": [str(c.get("stmt_id") or "") for c in (got.get("candidates") or [])],
            "cost": dict(got.get("cost") or {}),
        }

    def _upgrade_evidence_kind(self, existing: Mapping[str, Any],
                               body: Mapping[str, Any]) -> dict[str, Any]:
        """同一份内容再交一次、这一回来的 `evidence_kind` 更强 ⇒ 返回"改哪几格"。

        ## 为什么必须有这一格（2026-10-19 晚，`projects/mp2` 的 `stmt:000003`）：`mp2` 那条真机读数：B 先把主
        命题落成 `heuristic`（那时 V 还没签，这是如实的降档），随后 V 签了 `verifications/000003.jsonl#v-000001`
        （verdict=成立、`proof_sha256` 与现行正文相符）—— 而那一行的档位再也没升上去，因为"升档"当时只有一条路：
        `table.update("statements")`。那条路是野路（`store.direct_write_refusal` 现在拒它），因为它同时能改
        `bits` / `proof_text` / `quote_verified`，而没有任何东西核过那些字段。关掉野路就必须给正路一条同样的
        出口，否则 `evidence_kind` 在结构上永远到不了 `proof_review`（`weaker_than_evidence` 会永远报 warning，
        而它要的出口"把这一行升成 proof_review"没人走得到）。这一格就是那条出口：内容一个字不动、只把档位改强，
        且判据用的是 `verifications.proof_review_gap`（写入期闸、审计期、收工门读的是同一处口径）。
        ## 三态（凭据不够就不升，而且把原因说出来）：
        | 结局 | 返回 |
        |---|---|
        | 升了 | `{"upgraded": True, "row": …, "changes": [...], "reason": …}` |
        | 该升而凭据不够 | `{"upgraded": False, "reason": "（…；V 那一签还差…）"}` |
        | 不该升（方向不对/同档） | `{"upgraded": False, "reason": ""}` |
        "凭据不够"与"不该升"都不写库：前者留在重复读数那一支，并把 `proof_review_gap` 的原话附进 `reason`。只允许
        弱 → 强（`verifications.WEAKER_THAN_PROOF_REVIEW` → `proof_review` 或 `proof`）：反方向（把 `proof_review` 降成
        `heuristic`）不在这一格 —— 降档是另一个决定，它需要的不是"同一份内容再交一次"这件事，而是写清为什么降（`quote_reason`）。
        ## 只动档位与留痕，不动 bits（与 F 的 `_promote_if_understated` 同一口径）：`agent_f/core._promote_if_understated`
        在攻坚那一侧做的是同一件事（复用既有行时就地升到 `proof_review`），它也只改 `evidence_kind`。五元位的
        第 3 位（`reviewed`）是 V 的签名面，由 `verifications.bit3_payload(那一行)` 现读，不在这一格里抄进来 ——
        抄进来就有第二份"谁审过了"的账，而两份账迟早会分家。

        ## D-37（2026-10-24 真机 cube）：`kind` 也跟着证据升
        现场那一行早就升到了 `proof_review`（`have == want`），而 `kind` 仍写着 `conjecture` ⇒
        "档位还要不要升"这一支根本进不来。所以 `kind` 那一格独立算：判据只有一处
        （`evidencebits.kind_following_grade`，纯读；B 同步第 4 位那一支共用同一个），依据要么是 `verifications/`
        里一条盖住现行正文、判「成立」的签，要么是第 4 位逐条里一条 `verified`。
        只抬 `conjecture → theorem / lemma`（`body.kind` 只在两档之间选落点），作者写下的
        别的 kind 一个字不动；`bits` 仍然一个字节不写（五元位由现算派生，不抄第二份账）。
        升档依据落 `_kind_upgrade`（from / to / basis / grade / by / at），与 `_evidence_kind_upgrade`
        同一套留痕形态。证据不够时这一行不改，`reason` 里附 `_kind_follow_note` 的原话
        （"还差什么"），不许折成"已经升了"。
        """
        from . import evidencebits as EB   # 惰性：D-37 的 kind 口径只有一处
        from . import verifications as VR   # 惰性：只在重复读数这一支才需要

        out: dict[str, Any] = {"upgraded": False, "row": {}, "changes": [], "reason": ""}
        want = str(body.get("evidence_kind") or "")
        have = str(existing.get("evidence_kind") or "")
        row = dict(existing)
        changes: list[str] = []
        # ---- D-37（2026-10-24 真机 cube 的现场）：kind 跟着证据升。
        #
        # 与下面 `evidence_kind` 那一支各自独立：现场那一行早就升到了 `proof_review`
        # （`have == want`），缺的只是 `kind` 那一步 —— 所以这一格不能挂在"档位还要不要
        # 升"的条件下面。判据只有一处（`evidencebits.kind_following_grade`，纯读；B 同步
        # 第 4 位那一支与它共用同一个），这里只做两件本层的事：改那一格、把依据留痕。
        kind_read = EB.kind_following_grade(
            existing, root=self.store.root, requested=str(body.get("kind") or ""))
        kind_upgraded = False
        if str(kind_read.get("state") or "") == "upgraded":
            target = str(kind_read.get("kind") or "")
            before_kind = str(existing.get("kind") or "")
            if target in EB.KIND_UPGRADE_TARGETS and target != before_kind:
                row["kind"] = target
                # 留痕：只改 kind 的那一笔也要读得出来"凭什么"（与
                # `_evidence_kind_upgrade` 同一套：from / to / 依据 / 谁 / 何时）。
                row["_kind_upgrade"] = {
                    "from": before_kind, "to": target,
                    "basis": str(kind_read.get("basis") or ""),
                    "grade": str(kind_read.get("grade") or ""),
                    "by": f"secretary-{self.role}", "at": S.now_iso(),
                }
                changes.append(
                    f"kind: {before_kind or '（空）'} → {target}"
                    f"（升档依据：{str(kind_read.get('basis') or '')}）")
                kind_upgraded = True
        #: 这一格能升到的两档：`proof_review`（V 逐行走查/会审签过）与 `proof`
        #: （穷举型证据：E 的程序 + ②③ 加上 V 那一签 —— 业主 2026-10-23 晚「穷举能拿
        #: proof」）。两档的凭据是同一份读数（V 签成立 + `proof_sha256` 与现行正文相符），
        #: 所以判据仍然只走 `verifications.proof_review_gap` 一处，不另立一套。
        #: 为什么要开 `proof` 这一档：B 的第三方签字闸（`numericproof.filing_problems`）
        #: 要求 proof 必须有一份盖住这一条命题的 V 签，而 V 只审在册的命题 ⇒
        #: 「先按猜想落库、签完再升成定理级 proof」是唯一正路；这一格不通的话那条路在
        #: 秘书这一层就断了（`duplicate_statement`），穷举证明永远进不了定理证明库。
        evidence_upgraded = False
        evidence_gap = ""
        if (want in (VR.PROOF_REVIEW_KIND, "proof") and have != want
                and have in VR.WEAKER_THAN_PROOF_REVIEW):
            probe = dict(existing)
            probe["evidence_kind"] = want
            gap = VR.proof_review_gap(self.store.root, probe)
            if not gap.get("ok"):
                evidence_gap = (
                    f"（这一行没有升到 {want}：`verifications.proof_review_gap` 判"
                    f"凭据不够 —— {str(gap.get('why') or '查不到凭据')[:240]}）")
            else:
                row["evidence_kind"] = want
                row["_evidence_kind_upgrade"] = {
                    "from": have, "to": want,
                    "verification_id": str(gap.get("verification_id") or ""),
                    "ledger": str(gap.get("ledger") or ""),
                    "proof_sha256_matched": bool(gap.get("sha_matches")),
                    "by": f"secretary-{self.role}", "at": S.now_iso(),
                }
                changes.append(f"evidence_kind: {have} → {want}"
                               f"（凭据：{gap.get('ledger') or ''}"
                               f"#{gap.get('verification_id') or ''}）")
                evidence_upgraded = True
        if not (kind_upgraded or evidence_upgraded):
            # 三态：一行都没改，而"还差什么"必须留在读数里（D-37）。
            out["reason"] = evidence_gap + self._kind_follow_note(kind_read)
            out["kind_reading"] = dict(kind_read)
            return out
        out.update(upgraded=True, row=row, changes=changes,
                   kind_reading=dict(kind_read))
        if evidence_upgraded:
            out["reason"] = (
                f"同一份内容再交一次、且这一回带了 `{want}` 的凭据 ⇒ 秘书"
                f"改那一行（不新建）：`{str((row.get('_evidence_kind_upgrade') or {}).get('ledger') or '')}` 里 "
                f"{str((row.get('_evidence_kind_upgrade') or {}).get('verification_id') or '')} 签「成立」、"
                "`proof_sha256` 与现行正文相符（判据与写入期那道闸同一处）。内容面一个字没动。")
        else:
            out["reason"] = (
                "同一份内容再交一次 ⇒ 秘书改那一行（不新建）："
                + "；".join(changes) + "。内容面一个字没动。")
        if not evidence_upgraded and evidence_gap:
            out["reason"] += evidence_gap
        return out

    @staticmethod
    def _kind_follow_note(reading: Mapping[str, Any]) -> str:
        """D-37 的"还差什么"那一句（三态里 `held` / `unreadable` 的那一半）。

        为什么必须说出来：证据不够时"没升"与"升了但没变化"在返回值上同形，
        而调用方要能分辨"再去拿一份证据"与"不用再交一次"。`upgraded` 与 `not_applicable`
        都不产出这句话 —— 前者已经写在 `changes` 里，后者是"本来就不该改"。
        """
        state = str((reading or {}).get("state") or "")
        if state == "held":
            return ("（`kind` 仍是 conjecture：要升成 theorem / lemma 还差 —— "
                    + str((reading or {}).get("shortfall") or "凭据不够") + "）")
        if state == "unreadable":
            return ("（`kind` 升不升判不了："
                    + str((reading or {}).get("shortfall") or "五元位算不出来") + "）")
        return ""

    def _record_pending_concept(self, body: dict[str, Any], *,
                                out: dict[str, Any]) -> dict[str, Any]:
        """交来的就是一条还没抽到定义的概念 ⇒ 落成 `pending_definition`（D12 甲）。

        与 `_record_statement_tx` 分开的理由：那一条路要求 `statement_full` 非空
        （命题没有"内容待补"这一档），而概念有 —— 混在一处会把"命题缺假设"
        与"概念缺定义"折成同一件事（前者该拒，后者该落）。
        查重按概念标签的规范化值（同名的概念不重复建行；改名由人/秘书那一层决定）。
        """
        from . import conceptrows as CR   # 惰性：并表过渡层的唯一读写口
        from . import textutil as T       # 惰性：查重键的唯一实现

        name = str(body.get("label") or "")
        if not name.strip():
            out.update(refused="empty_statement",
                       reason="一条概念至少要有 label（名字）—— 没有名字的行谁也认不出它")
            return out
        legacy = CR.legacy_present(self.store)
        tables = list(STATEMENT_WRITE_TABLES) + ([CR.LEGACY_TABLE] if legacy.get("present") else [])
        with self.store.tx(*tables, actor=f"secretary-{self.role}",
                           note="record_statement:concept_pending") as tx:
            key = T.normalize(name)
            dup = next((r for r in tx.rows("statements")
                        if str(r.get("kind") or "") == "concept"
                        and T.normalize(str(r.get("label") or "")) == key), None)
            if dup is not None:
                out.update(checked=True, created=False, duplicate=True,
                           stmt_id=str(dup.get("stmt_id") or ""),
                           reason=("同一个概念标签已在册 ⇒ 不新建行（秘书查重；"
                                   "定义到了去改那一行，而不是再起一条）"))
                return out
            # 过渡期的号空间只有一个权威：老表还在的时候就是 `concept`（B 的 pipeline
            # 从那儿发号），迁移之后才是 `stmt` —— 两边各发各的会让同一张表出现
            # `id_gap`（分配了号却没建行），而两张表还要同号。
            concept_kind = (S.TABLES[CR.LEGACY_TABLE]["id_kind"] if legacy.get("present")
                            else S.TABLES["statements"]["id_kind"])
            cid = tx.alloc_id(concept_kind)
            # `origin` 按来源分档（本批缺陷一的第二处）：交来的概念有出处 ⇒ external_lit；
            # 没有出处 ⇒ 我们自己定义的新概念（own_result，推断，不要求调用方另声明）。
            src_lit = str(body.get("source_lit_id") or "")
            concept_origin = CR.resolve_concept_origin(source_lit_id=src_lit)
            problem = CR.concept_origin_problem(origin=concept_origin,
                                                source_lit_id=src_lit,
                                                self_authored=(concept_origin == "own_result"))
            if problem:
                out.update(refused="concept_origin_refused", reason=problem)
                return out
            # 过渡期两处同号（`conceptrows` 的契约 1）：老表那份镜像沿用这个号
            data = CR.write_concept(tx, stmt_id=cid, label=name, definition="",
                                    aliases=body.get("aliases") or [],
                                    source_lit_id=src_lit,
                                    doc_id=str(body.get("doc_id") or ""),
                                    actor=f"secretary-{self.role}",
                                    origin=concept_origin,
                                    self_authored=(concept_origin == "own_result"),
                                    mirror=bool(legacy.get("present")))
        out.update(checked=True, created=True, stmt_id=cid, row=data,
                   tables=tables, mirrored=bool(legacy.get("present")), pending_concepts=1,
                   reason=("概念行已落成 pending_definition（定义待补）—— 它不是依据；"
                           "概念行不带 `proof_text`（概念不参与等级链，"
                           "要补的是定义，不是证明）"))
        return out

    #: 扫出来的引用前缀 ⇒ `(STEP_SOURCE_KEYS` 里那一步的键名, `kind` 缺省)。
    #: 键名而不是来源字段名：`_resolve_dep_steps` 读的是 `st.get(key)`
    #: （`lit_id` / `stmt_id` / `experiment_id` / `doc_id`），来源字段名是它再翻译过去的。
    #:
    #: `rel` / `eval` 刻意不在表里：`Dependency` 的"四选一"（`STEP_SOURCE_KEYS`）
    #: 里没有指向关系表/评测表的格子 ⇒ 它们进 `deps_unmappable` 读数并点名，
    #: 不许静默丢（丢掉一条引用 = 依赖图静默少一环，而那正是 FC-23 那个病的成因）。
    _SCAN_SOURCE: dict[str, tuple[str, str]] = {
        "stmt": ("stmt_id", "theorem"),
        "exp": ("experiment_id", "experiment"),
        "lit": ("lit_id", "theorem"),
        "doc": ("doc_id", "theorem"),
    }

    def _scan_proof_deps(self, body: Mapping[str, Any]) -> dict[str, Any]:
        """从"定理内容 + 证明过程"里扫出依赖（业主 `draft/97` §14.11 乙：B 只交这两样）。

        ## 路径分组（`Dependency.path_group`）：载荷给了显式的 `proof_paths`（多段可选证明，B 自己分的段）⇒
        每段一组，下标从 1 起（组内 AND / 组间 OR，见 `draft/97` §12.1）；载荷给了 `proofs`（多证明清单，
        业主 2026-10-22）⇒ 一份证明一组，组下标就是它在清单里的位次，并且这一组的每一步都带上它的
        `proof_no`（于是 `used_by` 落成 `stmt:<号>#pN`，第 2 份及以后的依赖面不再与 #p1 混在一起）。
        两样都没给 ⇒ 把 `statement_full` + `proof_text` 当一段（全归第 1 组）—— 刻意"不猜"：
        不按空行、不按"证明一/证明二"这种字样去猜 B 想分几段。
        ## 三态（`state`）：
        | 取值 | 什么时候 | 为什么必须分开 |
        |---|---|---|
        | `from_proof` | 扫到了至少一条在册引用 | 这是"扫到了" |
        | `none_in_proof` | 证明过程给了（键在）、一条引用也没有 | 这是"扫了、确实是空的" |
        | `unknown` | 证明过程这一格根本没给、也没扫到引用 | 这是"没扫成" —— 与"空"折平就等于把"B 没交证明过程"读成"这条定理不依赖任何东西" |
        扫的范围是定理内容 + 证明过程两张脸（业主的口径："证明过程/定理内容里出现的引用"），去重按 `(前缀, 代号)`
        （`lit:0003#p.4` 与 `lit:0003` 是同一条）。
        """
        from . import textutil as T   # 惰性：引用扫描的唯一实现

        raw_paths = body.get("proof_paths")
        #: 一条路径 = `(proof_no, 要扫的正文)`；`proof_no=0` 表示"这一笔没说它是第几份证明"，
        #: 于是 `_write_dep_steps` 照旧按 `body["proof_no"]`（缺省 canonical）落 `used_by`。
        #:
        #: 多证明清单排在 `proof_paths` 之前：`proofs` 是"这条定理有几份证明"的声明面，
        #: 而 `proof_paths` 是"某一份证明里有几条可选路径"的声明面 —— 两者都给时，
        #: 一份证明一组比"整份证明被切成几段"更不容易把依赖挂错证明号。
        proof_plan = self._proof_dep_plan(body)
        if proof_plan:
            paths = [text for _no, text in proof_plan]
        elif isinstance(raw_paths, (list, tuple)) and raw_paths:
            proof_plan = [(0, str(p or "")) for p in raw_paths]
            paths = [text for _no, text in proof_plan]
        else:
            proof_plan = [(0, str(body.get("statement_full") or "") + "\n"
                           + str(body.get("proof_text") or ""))]
            paths = [text for _no, text in proof_plan]
        groups: list[list[dict[str, Any]]] = []
        unmappable: list[dict[str, str]] = []
        seen_unmappable: set[str] = set()
        found = 0
        for gi, (plan_no, text) in enumerate(proof_plan, 1):
            steps: list[dict[str, Any]] = []
            for ref in T.find_citations(text):
                found += 1
                mapping = self._SCAN_SOURCE.get(ref["prefix"])
                if mapping is None:
                    # 在册、但没有承载格（`rel:` / `eval:`）⇒ 点名，不静默丢
                    if ref["raw"] not in seen_unmappable:
                        seen_unmappable.add(ref["raw"])
                        unmappable.append({
                            "ref": ref["raw"], "table": ref["table"],
                            "why": (f"`{ref['prefix']}:` 在册（指向 {ref['table']}），但 "
                                    "`Dependency` 没有指向这张表的来源格 ⇒ 这条引用落不进依赖边，"
                                    "列在这里点名（不许静默丢）")})
                    continue
                field, dep_kind = mapping
                #: 路径组：多证明清单那一档里"一份证明 = 一条可选路径"，于是组号就是
                #: 证明号（第 2 份证明的依赖落在 `path_group=2`）；老写法（没有 `proofs`）
                #: 仍按段落下标，`proof_paths` 的第 N 段就是第 N 组 —— 老读数逐字不变。
                group_no = int(plan_no) if plan_no >= 1 else gi
                step = {"kind": dep_kind, "label": ref["raw"], "code": ref["code"],
                        "table": ref["table"], field: ref["code"], "path_group": group_no,
                        "_from": "proof_scan"}
                if plan_no >= 1:
                    # 这一组属于第几份证明：`_write_dep_steps` 据此落
                    # `used_by="stmt:<号>#pN"`（第 1 份不加尾巴，老写法逐字不变）。
                    step["proof_no"] = int(plan_no)
                steps.append(step)
            if steps:
                groups.append(steps)
        if found:
            state = "from_proof"
        elif "proof_text" in body or body.get("proofs"):
            state = "none_in_proof"
        else:
            state = "unknown"
        return {"state": state, "groups": groups, "unmappable": unmappable,
                "paths": len(paths), "refs": found}

    @staticmethod
    def _proof_dep_plan(body: Mapping[str, Any]) -> list[tuple[int, str]]:
        """多证明载荷 ⇒ "一份证明一组"的扫描计划（`[(proof_no, 正文)]`，按证明号升序）。

        为什么要这一格：第 2 份及以后的证明正文原先根本不进扫描（`_scan_proof_deps` 只看
        `statement_full` + `proof_text`），于是 `proofs=[#p1,#p2,#p3]` 交上去之后
        依赖面只有 #p1 那一条 —— 第 2、3 份证明引用的东西静默不进依赖图，
        而 `used_by="stmt:#pN"` 也就一次都没被写出来过（真机 sylow3 正是这个读数：
        `proof_no` 全 1、依赖 0 行）。

        三态：
        - 载荷没有 `proofs`（或不是列表 / 空）⇒ 空列表 = "这一笔不是多证明"，
          调用方照老路把整份 `statement_full + proof_text` 当一段（老读数逐字不变）；
        - `proofs` 里有条目而 `proof_text` 非空 ⇒ #p1 用 `proof_text` 的正文
          （它是 canonical 的唯一权威），其余按清单里的号与正文；
        - 条目认不出证明号 / 正文为空 ⇒ 跳过那一条（不猜它是第几份；`B.register_statement`
          的预检已经会整笔拒收，这里只是不让脏载荷把扫描带崩）。
        """
        raw = body.get("proofs")
        if not isinstance(raw, (list, tuple)) or not raw:
            return []
        plan: dict[int, str] = {}
        for item in raw:
            if not isinstance(item, Mapping):
                continue
            try:
                no = int(item.get("proof_no") or 0)
            except (TypeError, ValueError):
                continue
            text = str(item.get("text") or item.get("proof_text") or "")
            if no < 1 or not text.strip():
                continue
            plan[no] = text
        if not plan:
            return []
        canon = str(body.get("proof_text") or "")
        if canon.strip():
            plan[1] = canon
        return [(no, plan[no]) for no in sorted(plan)]

    def _record_statement_tx(self, body: dict[str, Any], *, full: str, kind: str,
                             force_new: bool, out: dict[str, Any],
                             adjudication: Mapping[str, Any] | None = None
                             ) -> dict[str, Any]:
        """一笔事务把命题（+ 概念行 + 依赖组）落盘（`record_statement` 的写那一半）。

        `adjudication` 是事务之外那一次模型判定（见 `adjudicate_proposition`）：
        它决定这一笔是"并进在册的那一条"还是"新建"，并把定理名洗成 `canonical_name`。
        事务里不再发调用 —— 锁里不许有网络等待。
        """
        from . import conceptrows as CR   # 惰性：并表过渡层的唯一读写口
        from . import textutil as T       # 惰性：查重键的唯一实现

        adj = dict(adjudication or {})
        # ---- 洗定理名（业主 2026-10-24）：「Sylow 三定理（路线一：…）」⇒「Sylow 三定理」。
        # 落点是 label；被洗掉的路线进证明那一层（见下面 `_proof_routes` 那一格）。
        # 这里只动"写进这一行的那份 body 副本"：调用方交上来的原文一个字不改
        # （`out["label_washed"]` 留着 from / to 两格，静默改名是不许的）。
        if adj.get("checked") and str(adj.get("canonical_name") or "").strip():
            was = str(body.get("label") or "")
            now = str(adj.get("canonical_name") or "").strip()
            if was != now:
                body = dict(body)
                body["label"] = now
                out["canonical_name"] = now
                out["label_washed"] = {"from": was, "to": now}
        route = str(adj.get("route") or "").strip() if adj.get("checked") else ""
        out["proof_route"] = route

        groups = [list(g) for g in (body.get("deps") or [])]
        # 显式给了 `deps` ⇒ 走严格那一条（指着一个不在册的号 = 整笔不写：那是 G 的
        # `register_dependency` 那一族的契约）。没给 ⇒ 从证明文本里扫（业主 §14.11：
        # B 只交"定理内容 + 证明过程"），而扫出来的悬空引用按那一条的判据不整笔拒，
        # 落成 `dangling` 并点名。
        scan = {"state": "", "groups": [], "unmappable": [], "paths": 0, "refs": 0}
        if not groups:
            scan = self._scan_proof_deps(body)
            groups = [list(g) for g in scan["groups"]]
        out["deps_state"] = scan["state"]
        out["deps_from"] = "proof" if scan["refs"] else ("explicit" if body.get("deps") else "")
        out["deps_unmappable"] = list(scan["unmappable"])
        out["deps_dangling"] = []
        concepts = [dict(c) for c in (body.get("concepts") or []) if isinstance(c, Mapping)]
        # ---- 概念行（`kind="concept"` 那一条自身）：本批缺陷一的写入侧 -----------------
        # 两件事在这个入口上也要做（它不经过 `conceptrows.write_concept`）：
        # ① `proof_text` 不许写（概念不参与等级链；真机 mp3 的 1143 条概念行每一条都
        #    带着哨兵 `concept:primitive`，把"有没有证明"的读数全顶高了）；
        # ② `origin` 按来源分档：有出处 ⇒ external_lit；没有 ⇒ 自己的概念；
        #    显式写 own_result 必须带 `self_authored`（判据在 `conceptrows`，不抄第二份）。
        if kind == "concept":
            if str(body.get("proof_text") or "").strip():
                out["concept_proof_text_dropped"] = [str(body.get("label") or "")]
                body = dict(body)
                body["proof_text"] = ""
            _src = str(body.get("source_lit_id") or "")
            _want = str(body.get("origin") or "")
            _self_auth = bool(body.get("self_authored"))
            _resolved = CR.resolve_concept_origin(
                origin=_want, source_lit_id=_src, self_authored=_self_auth)
            _self_auth = _self_auth or (_resolved == "own_result" and not _want)
            _problem = CR.concept_origin_problem(
                origin=_resolved, source_lit_id=_src, self_authored=_self_auth)
            if _problem:
                out.update(refused="concept_origin_refused", reason=_problem)
                return out
            body = dict(body)
            body["origin"] = _resolved
        legacy = CR.legacy_present(self.store)
        with self.store.tx(*STATEMENT_WRITE_TABLES, "literature", "experiments",
                           "documents",
                           *([CR.LEGACY_TABLE] if legacy.get("present") else ()),
                           actor=f"secretary-{self.role}",
                           note="record_statement") as tx:
            key = T.normalize(full)
            existing = next((r for r in tx.rows("statements")
                             if T.normalize(str(r.get("statement_full") or "")) == key), None)
            if existing is not None and not force_new:
                upgraded = self._upgrade_evidence_kind(existing, body)
                if upgraded.get("upgraded"):
                    # 同一份内容、这一回带来的证据档更强 ⇒ 改那一行（不新建）。
                    # 这是"改表"那一件活的正路，也是 `evidence_kind` 从弱档走到
                    # `proof_review` 的唯一一条路（通用写口 `table.update` 已在
                    # `store.direct_write_refusal` 那一层被拒）。
                    tx.upsert("statements", upgraded["row"],
                              note="record_statement:upgrade")
                    out.update(checked=True, created=False, duplicate=False,
                               upgraded=True, stmt_id=str(existing.get("stmt_id") or ""),
                               row=dict(upgraded["row"]), tables=["statements"],
                               changes=list(upgraded.get("changes") or []),
                               reason=str(upgraded.get("reason") or ""))
                    return out
                out.update(checked=True, created=False, duplicate=True,
                           stmt_id=str(existing.get("stmt_id") or ""),
                           # 2026-10-26：这一句改前写着"确实要另起一条，请给 force_new"，
                           # 而走到这里的每一条路（B 的 `register_statement`、被通用写口
                           # 路由过来的 `table.create`）都没有 force_new 这个参数 ——
                           # 拒信因此指了一条不存在的路（`duplicate` 那一档的拒信要能
                           # 把模型指回正路，指的必须是这条路上真有的做法）。
                           reason=("同一条 statement_full 已在册 ⇒ 重复读数，不新建行"
                                   "（要引用既有那一行，用返回里的 stmt_id 即可；"
                                   "确实是另一条命题时把差异写进 statement_full —— "
                                   "正文按规范化比不同才会落新的一行）"
                                   + str(upgraded.get("reason") or "")))
                return out
            # ---- 2026-10-24（业主：表述几乎相同的两条命题是同一个；证明方式几乎相同的
            # 视为同种证明）：同一命题 ⇒ 并成第 N 份证明；同种证明 ⇒ 受控拒绝或合并。
            merged = self._merge_into_proposition(tx, body, full=full, kind=kind,
                                                  groups=groups,
                                                  force_new=bool(force_new), out=out,
                                                  adjudication=adj)
            if merged is not None:
                return merged
            steps = self._resolve_write_steps(tx, body, out, groups)
            if steps is None:
                return out
            lit = str(body.get("source_lit_id") or "")
            if lit and tx.find("literature", lit_id=lit) is None:
                lit_rows = tx.rows("literature")
                ids = [str(r.get("lit_id") or "") for r in lit_rows[:8]]
                out.update(refused="unknown_lit_id",
                           reason=(f"literature 表里没有 lit_id={lit!r} ⇒ 这条命题的出处不存在，"
                                   f"整笔不写库。表里现有 {len(lit_rows)} 行，lit_id："
                                   f"{ids or '（一个都没有 —— 表是空的）'}"),
                           literature_rows=len(lit_rows), available_lit_ids=ids)
                return out
            stmt_kind = S.TABLES["statements"]["id_kind"]
            # 过渡期的号空间只有一个权威（老表还在时是 `concept`，迁移之后是 `stmt`）
            concept_kind = (S.TABLES[CR.LEGACY_TABLE]["id_kind"] if legacy.get("present")
                            else stmt_kind)
            stmt_id = tx.alloc_id(stmt_kind)
            row = self._statement_from(body, full=full, kind=kind, stmt_id=stmt_id)
            row.validate()
            if (row.origin == "own_result" and not str(body.get("quote_reason") or "").strip()
                    and body.get("quote_verified") is not True):
                # 读数：`quote_reason` 是秘书补的（B 只交两样，见 `_statement_from`）——
                # 补了必须看得见，否则"这一格为什么有值"在盘上无从分辨。
                out["quote_reason_filled"] = True
            data = self._annotate_proposition(row.to_dict(), adj, proof_no=1,
                                              route=route)
            tx.upsert("statements", data, note="record_statement")
            if kind == "concept" and legacy.get("present"):
                # 交来的就是一条概念（`kind="concept"`）⇒ 它自己那一行也要镜像：
                # 漏掉这一支，B 用"整条交一条概念"的写法时老读侧就看不见它
                # （而盘上看起来一切正常 —— 这正是"两处同号"最容易漏的一格）。
                mirror = S.Concept(
                    concept_id=stmt_id, name=str(body.get("label") or ""),
                    definition=full, related_concepts=[],
                    normalized_name=T.normalize(str(body.get("label") or "")),
                    aliases=[str(a) for a in (body.get("aliases") or []) if str(a).strip()],
                    definition_source_lit_id=str(body.get("source_lit_id") or "") or None,
                    created_at=S.now_iso(), updated_at=S.now_iso())
                mirror.validate()
                tx.upsert(CR.LEGACY_TABLE, mirror.to_dict(), note="record_statement:mirror")
            written = ["statements"]
            pending_concepts = 0
            # ---- 概念的三道闸（2026-10-21，本批缺陷一） -------------------------
            # ① 概念行不带证明文本（`proof_text` 是"这段证明被审过"的比对对象，
            #    概念不参与等级链）⇒ 载荷里带了也不写，并且留痕（静默丢是另一种坏）；
            # ② `origin` 口径：有出处 ⇒ external_lit；没有 ⇒ 自己定义的概念；
            #    显式写 own_result 必须带 self_authored（判据在 conceptrows）；
            # ③ 每轮上限（`conceptrows.CONCEPTS_PER_ROUND_MAX`）：超出的受控拒绝、
            #    读数可见、已写的保留。
            quota = CR.ConceptQuota()
            dropped_proof: list[str] = []
            refused_concepts: list[dict] = []
            for c in concepts:
                name = str(c.get("name") or "")
                if str(c.get("proof_text") or "").strip():
                    dropped_proof.append(name)
                src_lit = str(c.get("source_lit_id") or body.get("source_lit_id") or "")
                origin = str(c.get("origin") or "")
                self_authored = bool(c.get("self_authored"))
                resolved_origin = CR.resolve_concept_origin(
                    origin=origin, source_lit_id=src_lit, self_authored=self_authored)
                problem = CR.concept_origin_problem(
                    origin=resolved_origin, source_lit_id=src_lit,
                    self_authored=(self_authored
                                   or (resolved_origin == "own_result"
                                       and not str(origin or "").strip())))
                if problem:
                    refused_concepts.append({"name": name, "why": problem})
                    continue
                if not quota.admit(name):
                    refused_concepts.append({"name": name, "why": quota.reading()["why"]})
                    continue
                # 与上面同一口径：老表还在的时候号空间的权威是 `concept`（两张表要同号，
                # 而各自发号会让两边的号不连续 —— `verify` 的 `id_gap` 会报出来）
                cid = tx.alloc_id(concept_kind)
                # 过渡期两处同号 + 老表镜像（`conceptrows` 的契约 1）：走同一处写口。
                # `proof_text` 刻意不转发：概念行不许带它（见上面①）。
                crow_data = CR.write_concept(
                    tx, stmt_id=cid, label=name,
                    definition=str(c.get("definition") or ""),
                    aliases=c.get("aliases") or (),
                    source_lit_id=src_lit,
                    doc_id=str(body.get("doc_id") or ""), actor=f"secretary-{self.role}",
                    origin=resolved_origin,
                    self_authored=(self_authored
                                   or (resolved_origin == "own_result"
                                       and not str(origin or "").strip())),
                    mirror=bool(legacy.get("present")))
                if str(crow_data.get("status") or "") == "pending_definition":
                    pending_concepts += 1
            if dropped_proof:
                out["concept_proof_text_dropped"] = dropped_proof[:20]
            if refused_concepts:
                out["concepts_refused"] = refused_concepts[:20]
            out["concept_quota"] = quota.reading()
            dep_count = self._write_dep_steps(tx, steps, stmt_id=stmt_id, body=body)
            written.append("dependencies")
            #: 依赖面到底建起来没有：带证明正文而一条依赖都没落 ⇒ 这一格说 `missing`
            #: （改前只有返回值里的 `deps_written=0`，而没有任何一格问过这件事 ——
            #: 真机 sylow3 七条命题、依赖全表 0 行，就是这样静默过去的）。
            out["deps_missing"] = _deps_missing_reading(
                proof_text=body.get("proof_text") or "", deps_written=dep_count,
                derived_from=body.get("derived_from") or (), stmt_id=stmt_id, scan=scan)
        out.update(checked=True, created=True, duplicate=False, stmt_id=stmt_id,
                   row=data, tables=written, deps_written=len(steps),
                   path_groups=len(groups), pending_concepts=pending_concepts)
        return out

    def _resolve_write_steps(self, tx: Any, body: Mapping[str, Any],
                             out: dict[str, Any], groups: list[list[dict[str, Any]]]
                             ) -> list[dict[str, Any]] | None:
        """把依赖组解析成可落盘的步骤；判不了就返回 `None`（调用方据此整笔不写）。

        从 :meth:`_record_statement_tx` 里拆出来是因为 2026-10-24 之后有两个调用点：
        "新建一条命题"与"并进已有命题的第 N 份证明"。两处必须用同一套判据 ——
        各写一份的形态是"两条路径对同一条悬空依赖给出两种处置"，而那种漂移没有
        任何读数会响（与 `_resolve_dep_steps` 的注释同一条理由）。
        三态：`None` = 拒（显式给的依赖指着不在册的号）；列表 = 可写（悬空边落
        `dangling` 并点名，扫不动的进 `deps_unmappable`）。
        """
        steps, missing = _resolve_dep_steps(groups, tx)
        if missing and body.get("deps"):
            # 显式给的依赖指着不在册的号 ⇒ 整笔不写（G 那一族的契约）
            out.update(refused="unresolved_dependency",
                       reason=("依赖里有一条指着不在册的 id ⇒ 整笔不写（不许留一条挂空号的"
                               "依赖：那正是'依赖图静默少一环'的成因）"),
                       unresolved=missing)
            return None
        if not missing:
            return steps
        # 从证明文本里扫出来的引用：业主 §14.11 的判据是"那条边落 `dangling`
        # 并在读数里点名，不整笔拒" —— 拒了等于把整条定理丢掉，而"证明里引了
        # 一个还不存在的号"正是最该留下痕迹的那件事。
        #
        # 两档必须分开（`_resolve_dep_steps` 的 `why` 把它们区分开）：
        # "表里没有这个号" ⇒ 落一条 `dangling` 边；"这一步本身不合法"
        # （来源不是四选一 / kind 不在词表里）⇒ 不落边，但进 `deps_unmappable`
        # 点名 —— 把后者也写成 `dangling` 会造出一条形状就不对的依赖行，
        # 而"写一条坏行"比"少写一条并点名"更坏。
        kept = list(steps)
        for m in missing:
            stp = dict(m.get("step") or {})
            why = str(m.get("why") or "")
            if "表里没有" in why:
                stp["status"] = "dangling"
                # 来源要从键名翻到字段名：`_resolve_dep_steps` 成功那一路
                # 已经翻过了（它返回的 step 带 `source_*`），而走 `missing` 这一路的
                # step 是输入的副本（只有 `stmt_id` 这种键名）⇒ 不翻的话
                # 悬空边会落成"四选一个来源都没有"的行（实测抓到：`source_stmt_id=None`）。
                for _key, _field, _table, _idf, _dkind in STEP_SOURCE_KEYS:
                    if str(stp.get(_key) or "").strip():
                        stp[_field] = str(stp[_key]).strip()
                        break
                # `Dependency.validate` 的硬要求：`status="dangling"` 必须写
                # `status_reason`（"只标状态不说原因 = 记了一笔没人能接手"）。
                stp["status_reason"] = (
                    f"证明文本里引用了 {stp.get('label') or stp.get('code')}，"
                    f"而{why} ⇒ 这条依赖边留着并标 `dangling`（不整笔拒、也不丢掉它："
                    "丢掉等于依赖图静默少一环）；等那一行进库之后由下一次核对闭合")
                kept.append(stp)
                out["deps_dangling"].append(
                    {"ref": str(stp.get("label") or stp.get("code") or ""),
                     "path_group": int(m.get("path_group") or 1), "why": why})
            else:
                out["deps_unmappable"].append({
                    "ref": str(stp.get("label") or stp.get("code") or ""),
                    "path_group": int(m.get("path_group") or 1),
                    "why": f"扫出来的这一步落不了：{why}"})
        return kept

    def _write_dep_steps(self, tx: Any, steps: Iterable[Mapping[str, Any]], *,
                         stmt_id: str, body: Mapping[str, Any]) -> int:
        """把解析好的步骤写成 `dependencies` 行，返回写了几条。

        多证明模型（业主 2026-10-22）：这条命题的依赖属于它的第几条证明。载荷没写
        ⇒ canonical（第 1 条）⇒ 生成出来的 `used_by` 与改前逐字相同
        （`proofloc.used_by_of` 对第 1 条不写 `#pN` 尾巴）。
        `path_group` 由扫描那一格给：老写法下它是"第几条路径"（`proof_paths` 的段落下标），
        多证明清单下它是"第几份证明"（组内 AND / 组间 OR 的语义不变：几份证明就是几条
        可选的路径）。
        """
        count = 0
        for step in steps:
            dep_id = tx.alloc_id(S.TABLES["dependencies"]["id_kind"])
            proof_no = step.get("proof_no") or body.get("proof_no") or _PL.DEFAULT_PROOF_NO
            try:
                proof_no = int(proof_no)
            except (TypeError, ValueError):
                proof_no = _PL.DEFAULT_PROOF_NO
            dep = S.Dependency(
                dep_id=dep_id,
                used_by=_PL.used_by_of(f"stmt:{stmt_id}", proof_no),
                kind=str(step.get("kind") or "theorem"),
                label=str(step.get("label") or "") or _dep_label(step),
                source_lit_id=step.get("source_lit_id"),
                source_experiment_id=step.get("source_experiment_id"),
                source_stmt_id=step.get("source_stmt_id"),
                source_doc_id=step.get("source_doc_id"),
                quote=str(step.get("quote") or ""),
                status=str(step.get("status") or "closed"),
                # `status != "closed"` 时 `Dependency.validate` 要求非空理由
                # （扫出来的悬空引用在 `_resolve_write_steps` 里已经写好了这一格）。
                status_reason=str(step.get("status_reason") or ""),
                page_range=S.PageRange(),
                path_group=int(step["path_group"]),
                created_at=S.now_iso(), created_by=f"secretary-{self.role}")
            dep.validate()
            tx.upsert("dependencies", dep.to_dict(), note="record_statement:dependency")
            count += 1
        return count

    def record_proof_deps(self, stmt_id: str,
                          entries: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
        """把"已经挂到某条命题上的第 N 份证明"的依赖写成 `dependencies` 行。

        ## 为什么需要第二个入口（同一个写入方，同一套判据）
        `record_statement` 只看得见这一笔交上来的 `proof_text`（#p1）。第 2 份及以后的
        证明是 `B.register_statement` 在 `_attach_proofs` 里挂到既有行上的，那一笔只动
        `statements`（B 的写集里没有 `dependencies`）⇒ 那几份证明引用的东西原先一条都
        不进依赖图，`used_by="stmt:#pN"` 因此一次都没被写出来过（真机 sylow3：
        依赖 0 行、`proof_no` 全 1）。这一格是那条路的补写口：判据（扫引用 / 悬空边点名 /
        "四选一"来源）全部复用 `_scan_proof_deps` 与 `_resolve_write_steps`，一行都没有
        另写一份 —— 两条路上"同一条悬空引用怎么处置"必须是同一个答案。

        三态（不进依赖表的两种原因分开）：
        - `checked=True` ＋ `deps_written>0` ⇒ 写成了；
        - `checked=True` ＋ `deps_written=0` ⇒ 扫了，这几份证明确实没有在册引用
          （自足证明合法，读数在 `deps_missing` 里）；
        - `checked=False` ⇒ 没写（没有 store / 依赖指着不在册的号 / 落盘失败），`reason` 说清。
        """
        out: dict[str, Any] = {"checked": False, "stmt_id": str(stmt_id or ""),
                               "deps_written": 0, "path_groups": 0, "proof_nos": [],
                               "deps_dangling": [], "deps_unmappable": [],
                               "deps_missing": {}, "refused": "", "reason": ""}
        proofs = []
        for item in (entries or ()):
            if not isinstance(item, Mapping):
                continue
            try:
                no = int(item.get("proof_no") or 0)
            except (TypeError, ValueError):
                continue
            text = str(item.get("text") or item.get("proof_text") or "")
            if no < 1 or not text.strip():
                continue
            proofs.append({"proof_no": no, "text": text})
        out["proof_nos"] = [int(e["proof_no"]) for e in proofs]
        if not proofs:
            out.update(checked=False,
                       reason="没有可扫的证明正文（第 2 份及以后的证明清单是空的）")
            return out
        if self.store is None:
            out.update(refused="secretary_unavailable",
                       reason="这一名秘书没有 store ⇒ 依赖写不了")
            return out
        body = {"proofs": proofs}
        scan = self._scan_proof_deps(body)
        out["deps_unmappable"] = list(scan["unmappable"])
        out["path_groups"] = len(scan["groups"])
        try:
            with self.store.tx(*STATEMENT_WRITE_TABLES, actor=f"secretary-{self.role}",
                               note="record_proof_deps") as tx:
                if tx.find("statements", stmt_id=out["stmt_id"]) is None:
                    out.update(refused="unknown_statement",
                               reason=(f"`statements` 里没有 {out['stmt_id']} ⇒ 这几份证明的"
                                       "依赖没有落点（清单挂不上时也没有行可挂）"))
                    return out
                steps = self._resolve_write_steps(tx, body, out, scan["groups"])
                if steps is None:
                    return out
                out["deps_written"] = self._write_dep_steps(tx, steps, stmt_id=out["stmt_id"],
                                                            body=body)
        except Exception as exc:  # noqa: BLE001 —— 落盘失败必须回三态，不许半笔
            out.update(checked=False, refused="write_failed",
                       reason=f"依赖落盘没成（{type(exc).__name__}: {exc}）⇒ 这一笔按'没写成'读")
            return out
        out["checked"] = True
        out["deps_missing"] = _deps_missing_reading(
            proof_text="\n".join(str(e["text"]) for e in proofs),
            deps_written=int(out["deps_written"] or 0),
            stmt_id=out["stmt_id"], proof_no=int(proofs[0]["proof_no"]),
            scan={"refs": int(scan.get("refs") or 0)})
        return out

    def _same_proposition_candidate(self, tx: Any, full: str, *,
                                    kind: str = "") -> dict[str, Any] | None:
        """在册的命题里找"同一条"：命中就返回那一条（含依据与读数），否则 `None`。

        判据只有一处（`propositionkey.same_proposition`）：先比确定性键，键不同再比
        词面相似度。本函数只做"在哪儿找、怎么选"这两件本层的事：
        - 只在命题性的 kind 之间判（`PROPOSITION_KINDS`；定义/概念/认不出的 kind 不并，
          理由见 `PROPOSITION_KINDS`）；
        - 跳过概念行（概念不是命题，键与相似度对它没有意义）；
        - 跳过 `schema.STATEMENT_UNUSABLE_STATUSES` 里的行（被否证/被取代的行不许
          当依据用，"并进一条已经被取代的命题"等于把新证明挂在一条废行上）；
        - 多条命中时取相似度最高的、同分取号最小的（确定性：同一次登记不能因为
          行的物理顺序不同而并进不同的一条）。
        """
        if not _is_proposition_kind(kind):
            return None
        candidates: list[dict[str, Any]] = []
        for r in tx.rows("statements"):
            sid = str(r.get("stmt_id") or "")
            if not sid:
                continue
            if not _is_proposition_kind(r.get("kind")):
                continue
            if str(r.get("status") or "") in S.STATEMENT_UNUSABLE_STATUSES:
                continue
            other = str(r.get("statement_full") or "")
            if not other.strip():
                continue
            verdict = _PK.same_proposition(full, other,
                                           threshold=self.same_proposition_jaccard)
            if str(verdict.get("state") or "") != _PK.STATE_SAME:
                continue
            candidates.append({"similarity": float(verdict.get("similarity") or 0.0),
                               "stmt_id": sid, "row": dict(r), "verdict": verdict})
        if not candidates:
            return None
        candidates.sort(key=lambda c: (-c["similarity"], str(c["stmt_id"])))
        return candidates[0]

    def _same_kind_hits(self, row: Mapping[str, Any], proof: str) -> list[dict[str, Any]]:
        """这条命题在册的证明里，与新交来的这一份同种的那些（相似度降序）。

        判据只有一处（`propositionkey.same_kind_proof`）。`unknown`（太短/纯符号）
        不算命中：那是"判不了"，把它读成"同种"会让一份真的另一种短证明被拒。
        """
        from . import verifications as VR   # 惰性：证明清单的唯一读口径

        hits: list[dict[str, Any]] = []
        if not str(proof or "").strip():
            return hits
        for no, text in VR.proof_list(row):
            got = _PK.same_kind_proof(proof, text, threshold=self.proof_same_jaccard)
            if str(got.get("state") or "") != _PK.STATE_SAME:
                continue
            hits.append({"proof_no": int(no), "similarity": float(got.get("similarity") or 0.0),
                         "detail": dict(got.get("detail") or {}),
                         "reason": str(got.get("reason") or "")})
        hits.sort(key=lambda h: (-h["similarity"], int(h["proof_no"])))
        return hits

    def _merge_into_proposition(self, tx: Any, body: Mapping[str, Any], *, full: str,
                                groups: list[list[dict[str, Any]]], kind: str = "",
                                force_new: bool, out: dict[str, Any],
                                adjudication: Mapping[str, Any] | None = None
                                ) -> dict[str, Any] | None:
        """同一命题 / 同种证明两道判断的落点（业主 2026-10-24）。

        这不是"新建一条命题"那一支：命中之后这一笔的去向只有三种，每一种都如实写进
        `out`（三态，读的人要能分辨"并了 / 拒了 / 没命中照常新建"）：

        | 结局 | 返回里的读数 |
        |---|---|
        | 并成第 N 份证明 | `merged=True` + `merged_into` + `proof_no=N` + `matched_by` |
        | 同种证明、且没给 merge | `checked=False` + `refused="proof_same_kind"` + 点名第几份 |
        | merge=True 且命中同种 | `merged=True` + `merged_same_kind=True` + `resign_required=True` |
        | 没命中 | `None`（调用方照常新建；这一支一个字节都不写） |

        ## 为什么"并进一条命题"要落在秘书这一层
        业主 2026-10-09 的裁定是"B 交内容、秘书实际操作增改查"。判"这两条是不是同一条
        定理"正是"查重"那一件活，而查重的读数（依据是键还是相似度、读数多少）必须与
        落盘在同一笔事务里 —— 分两处就会出现"读的时候判了同一条、写的时候建了新行"。

        ## 证明号从哪来
        第 N 份：`verifications.proof_list(row)` 的最大证明号 + 1（读口径只有那一处）。
        canonical 还是空的时候（先登记命题、后补证明），这一份就是 #p1，写 `proof_text`
        那一格而不是清单 —— 同一格不许有两个权威。

        ## 依赖落在哪一维
        这一笔的依赖全部落在 `used_by="stmt:<号>#pN"`（第 N 条证明）上，`path_group`
        照旧是"第几条路径"。两条证明的依赖面因此分开，`_DepGraph.groups_of` 读出来
        是 `{1: {…}, 2: {…}}` 两维（既有机制，不在这里重写）。

        ## 谁说了算（2026-10-24 晚，业主改口径）
        业主逐字：「不用机械判据，让秘书洗定理名，让秘书判」，准绳是「定理描述一致
        （什么条件推出什么结论），就是一个定理」。所以：

        - `adjudication.checked`（秘书判成了）⇒ 它说了算：`same` ⇒ 并进它点名的
          `same_as` 那一条；`different` / `unknown` ⇒ 不并（`unknown` 也一律不许拿
          相似度去猜 —— 判不了就是不并，台账里留 basis 给人看）；
        - 没查成（没缝 / 开关关着 / 超时 / 坏 JSON）⇒ 退回既有机械判据
          （`_same_proposition_candidate`：键相同或词面相似度达阈值）。这一档必须留着：
          秘书没接上时整条写入路不能因此瘫掉，而"一模一样才并"比"什么都不并"更接近真相。
        """
        from . import verifications as VR   # 惰性：证明清单 / 签名状态的唯一读口径

        adj = dict(adjudication or {})
        # 三态读数（"这一笔被判成什么"）：没有命中时也要能读出判过了、判的是哪一种。
        # 不许把"判不了"折成"不同"—— 两者的 `reason` 不同，处置也不同。
        probe = _PK.judgeable(full)
        out["proposition_state"] = (_PK.STATE_UNKNOWN if not probe["ok"]
                                   else _PK.STATE_DIFFERENT)
        out["proposition_reason"] = str(probe["reason"] or "没命中在册的同一条命题（键不同、相似度未达阈值）")
        if force_new:
            # 调用方明确要"另起一条" ⇒ 不并（`force_new` 的含义就是不许替它合并）。
            out["proposition_reason"] = "force_new：调用方明确要另起一条，跳过同一性合并"
            return None
        if not _is_proposition_kind(kind):
            # 一条定义/概念不是命题："表述几乎相同的两条命题是同一个"这句话对它不成立。
            out["proposition_reason"] = (
                f"kind={kind!r} 不在命题性的那几档 {list(PROPOSITION_KINDS)} 里 ⇒ "
                "不参与同一命题判定（不并）")
            return None
        proof = str(body.get("proof_text") or "")
        if not proof.strip():
            # 没有证明正文 ⇒ 这一笔不产生"第 N 份证明"，也就不进这一支：
            # 合并解决的是"两份证明被并列记录"，而没有正文的重复登记只是一次重复读数。
            # 老口径（按规范化正文精确查重）在这一支上原样保留 —— 不在这一笔里顺手
            # 改掉"命题级重复登记"的处置（那会让 `record_statement` 的返回值在
            # "带不带证明"两种情形下变成两个意思只差一个字的读数）。
            out["proposition_reason"] = (str(probe["reason"]) if not probe["ok"] else
                                         "这一笔没有带证明正文 ⇒ 不并（合并只针对第 N 份证明）")
            return None
        if adj.get("checked"):
            # ---- 秘书判过了：三种结论各自落地，机械判据一律不再插话。
            verdict_word = str(adj.get("verdict") or _PK.STATE_UNKNOWN)
            out["adjudication"] = self._adjudication_reading(adj)
            out["proposition_reason"] = (str(adj.get("basis") or "")
                                         or str(adj.get("reason") or ""))
            if verdict_word != _PK.STATE_SAME:
                out["proposition_state"] = (verdict_word if verdict_word in
                                            (_PK.STATE_DIFFERENT, _PK.STATE_UNKNOWN)
                                            else _PK.STATE_UNKNOWN)
                # 判 different / unknown ⇒ 不并，这一支一个字节都不写（调用方照常新建）。
                # `unknown` 尤其不许拿相似度去猜：那是把"没人判过"冒充"判过了、不同"的
                # 同一类错，只是方向相反。
                return None
            target_id = str(adj.get("same_as") or "")
            # 与 `_same_proposition_candidate` 同一组过滤：模型点名的是登记那一刻的候选，
            # 到了事务里它可能已经被否证/被取代/改成非命题 kind —— 那时不许把新证明挂上去。
            hit = next(({"row": dict(r), "stmt_id": str(r.get("stmt_id") or ""),
                         "verdict": {"state": _PK.STATE_SAME,
                                     "basis": MERGED_BY_ADJUDICATION,
                                     "similarity": 0.0,
                                     "reason": str(adj.get("basis") or "")}}
                        for r in tx.rows("statements")
                        if str(r.get("stmt_id") or "") == target_id
                        and _is_proposition_kind(r.get("kind"))
                        and str(r.get("status") or "") not in S.STATEMENT_UNUSABLE_STATUSES), None)
            if hit is None:
                out["proposition_state"] = _PK.STATE_UNKNOWN
                out["proposition_reason"] = (
                    f"秘书判 same 并点名 stmt:{target_id or '（空）'}，而事务快照里读不到那一条"
                    "（或它的状态已不可并）⇒ 不并、照常新建（不在一条读不到的行上写证明）")
                return None
        else:
            # ---- 没查成：退回既有机械判据（键相同 / 词面相似度达阈值）。
            out["adjudication"] = self._adjudication_reading(adj)
            hit = self._same_proposition_candidate(tx, full, kind=kind)
            if hit is None:
                # 三态：没命中也要能读出来"判过、判的是不同"，但这一支不写任何内容 ——
                # 返回值里 `merged` 保持 False 就是那个读数（`out` 的初值）。
                return None
        row = dict(hit["row"])
        sid = str(hit["stmt_id"])
        verdict = dict(hit["verdict"])
        out["proposition_state"] = _PK.STATE_SAME
        out["proposition_reason"] = str(verdict.get("reason") or "")
        basis = str(verdict.get("basis") or "")
        similarity = float(verdict.get("similarity") or 0.0)
        kind_hits = self._same_kind_hits(row, proof)
        merge = body.get("merge") is True
        existing = VR.proof_list(row)
        # ---- merge=True：合成一份，覆盖那一份证明的正文（要 V 重签）
        #
        # 这里刻意不去要求"合并稿本身与某一份同种"：合并稿是各取所长写出来的，
        # 它当然与原稿都不像（实测：两份 0.84 同种的原稿合成之后，合并稿与每一份
        # 的相似度掉到 0.67 / 0.59）。判据是"这一笔声明了自己是合并稿，而这条命题
        # 确实已在册"—— 后者由上面的同一性判定给出，前者由调用方声明。
        if merge:
            target, how = self._merge_target(row, proof, body, existing)
            if target < 1:
                out.update(checked=False, created=False, duplicate=False, merged=False,
                           refused="bad_merge_target", stmt_id=sid, merged_into=sid,
                           matched_by=basis, similarity=similarity,
                           reason=(f"`proof_no` 指的是这条命题在册的那一份证明，{how} ⇒ "
                                   "整笔不写（合并要落到一份具体的证明上：合并稿覆盖谁的正文、"
                                   "谁的旧正文进 proof_history、谁的签要重拿，都由它决定）"))
                return out
            return self._merge_same_kind_version(tx, row=row, sid=sid, full=full,
                                                 proof_no=int(target), merged_text=proof,
                                                 verdict=verdict, kind_hits=kind_hits,
                                                 merge_note=how, out=out)
        # ---- 同种证明：不新增证明号
        if kind_hits:
            top = kind_hits[0]
            others = "、".join(f"#{int(h['proof_no'])}" for h in kind_hits)
            out.update(checked=False, created=False, duplicate=False, merged=False,
                       refused=PROOF_SAME_KIND, stmt_id=sid, merged_into=sid,
                       matched_by=basis, similarity=similarity, proof_no=0,
                       same_kind=kind_hits,
                       reason=(f"这一笔要与 stmt:{sid} 的第 {others} 份证明同种（相似度 "
                               f"{float(top['similarity']):.4f} >= 阈值 "
                               f"{self.proof_same_jaccard:.2f}）⇒ 不新增证明号"
                               "（证明方式几乎相同的视为同种证明，并列记录会让一条定理"
                               "看起来有好几条独立证法）。两条处置：① 换一条真正不同的"
                               "证法再交（键不同、相似度低于阈值即可）；② 给 merge=true、"
                               f"proof_no={int(top['proof_no'])}（要合并到哪一份）并交一份"
                               "各取所长的合并正文 —— 秘书把它作为那一份证明的新版本"
                               "（旧正文进行的 proof_history），并要求 V 重签"))
            return out
        # ---- 落成第 N 份证明（或 canonical 那一格还是空的时候的 #p1）
        canonical_was_empty = not VR.proof_text_of(row, 1).strip()
        if canonical_was_empty:
            # 先登记命题、后补证明：这一份就是 #p1，写 canonical 那一格（不进清单）。
            row["proof_text"] = proof
            proof_no = 1
        else:
            proof_no = max(int(no) for no, _ in existing) + 1
            listed = [dict(p) if isinstance(p, Mapping) else p
                      for p in (row.get(VR.PROOFS_KEY) or [])]
            listed.append({"proof_no": proof_no, "text": proof,
                           "created_at": S.now_iso()})
            row[VR.PROOFS_KEY] = listed
        written = ["statements"]
        # ---- 洗定理名 + 路线进证明层（业主 2026-10-24：「路线写在证明这一层」）。
        #
        # 这一笔的 label 已经被洗成 `canonical_name`（见 `_record_statement_tx`），但并进去之后
        # label 用的是那条在册行的。所以这里两件都要做：
        # ① 在册那一条的名字如果与洗过的名字不同 ⇒ 顺手把它洗掉（真机 sylow4 的三行正是
        #    这么来的：第一条带着"（路线一：…）"落了盘，后来的两份证明并进来时把它洗净）；
        # ② 这一笔自己的路线说明落到"第 N 份证明"上（`_proof_routes`），不丢。
        route = str(adj.get("route") or "").strip() if adj.get("checked") else ""
        canonical = str(adj.get("canonical_name") or "").strip() if adj.get("checked") else ""
        if canonical and str(row.get("label") or "") != canonical:
            old_label = str(row.get("label") or "")
            # 只在"在册那个名字是本名加修饰"时洗（`Sylow 三定理（路线一：…）` ⇒ `Sylow 三定理`）。
            # 两个都干净、却不完全同名的（`Sylow 三定理` 与 `Sylow 定理`）不动它：名字不参与
            # 同一性判定（业主：「不看名称」），先落盘的那个名字赢 —— 否则每并一份证明就改名
            # 一次，而"这一条现在叫什么"会跟着最后一次提交漂。
            if canonical in old_label:
                out["label_washed"] = {"from": old_label, "to": canonical, "stmt_id": sid}
                row["label"] = canonical
        if route:
            out["proof_route"] = route
            routes = dict(row.get(PROOF_ROUTES_KEY) or {})
            routes[str(int(proof_no))] = route
            row[PROOF_ROUTES_KEY] = routes
        if canonical:
            out["canonical_name"] = canonical
        # 变体留痕：这一笔是"同一条命题的另一种写法"，盘上要读得出"它凭什么并进来"。
        # 有界（只留最近 20 条）：这是读数，不是账本；无界列表会让一行无限长大。
        matches = [dict(m) for m in (row.get("_proposition_matches") or [])
                   if isinstance(m, Mapping)]
        matches.append({"statement_full": full, "basis": basis,
                        "similarity": similarity, "proof_no": proof_no,
                        "label": str(body.get("label") or ""),
                        "route": route, "at": S.now_iso(),
                        "by": f"secretary-{self.role}"})
        row["_proposition_matches"] = matches[-20:]
        body_for_deps = dict(body)
        body_for_deps["proof_no"] = proof_no
        steps = self._resolve_write_steps(tx, body_for_deps, out, groups)
        if steps is None:
            return out
        deps_written = self._write_dep_steps(tx, steps, stmt_id=sid, body=body_for_deps)
        if deps_written:
            written.append("dependencies")
        tx.upsert("statements", row, note="record_statement:merged_proof")
        out["deps_missing"] = _deps_missing_reading(
            proof_text=proof, deps_written=deps_written,
            derived_from=body.get("derived_from") or (), stmt_id=sid,
            proof_no=proof_no,
            scan={"refs": sum(len(g) for g in (groups or []))})
        out.update(checked=True, created=False, duplicate=False, merged=True,
                   merged_into=sid, stmt_id=sid, proof_no=proof_no,
                   matched_by=basis, similarity=similarity, same_kind=[],
                   tables=written, row=row, deps_written=deps_written,
                   path_groups=len(groups or []), canonical_written=canonical_was_empty,
                   reason=(f"并入已有命题 stmt:{sid}，作为第 {proof_no} 份证明"
                           f"（依据：{self._basis_text(basis, similarity)}）；"
                           f"这一份的依赖落在 `used_by=\"stmt:{sid}#p{proof_no}\"`"
                           f"（{deps_written} 条、{len(groups or [])} 组），"
                           "与既有证明的依赖面按证明号分开；第 3 位（审过）由 V 逐份签，"
                           f"登记不等于审过（`bits.evidence.reviewed_by_proof` 支持逐份）"
                           # 洗名与路线各一句：读的人要能看出"标签被改过"与"路线去哪了"。
                           + (f"；定理名按秘书的判定洗成 {out['label_washed']['to']!r}"
                              f"（原标签 {out['label_washed']['from']!r}）"
                              if out.get("label_washed") else "")
                           + (f"；这一份的路线说明落在第 {proof_no} 份证明上"
                              f"（{route}）" if route else "")))
        return out

    @staticmethod
    def _basis_text(basis: str, similarity: float) -> str:
        """把"凭什么判成同一条"翻成一句人话（返回值与拒信共用一份措辞）。"""
        if str(basis) == _PK.BASIS_KEY:
            return "proposition_key 相同"
        if str(basis) == MERGED_BY_ADJUDICATION:
            return "秘书判的（条件与结论一致）"
        return f"prose_similarity {float(similarity):.4f}"

    def _merge_target(self, row: Mapping[str, Any], proof: str,
                      body: Mapping[str, Any],
                      existing: Sequence[tuple[int, str]]) -> tuple[int, str]:
        """合并稿要覆盖哪一份证明：显式号优先，没给就取与合并稿最像的那一份。

        返回 `(证明号, 依据说明)`；证明号 < 1 表示"指定了一个不在册的号"（调用方据此拒绝）。
        为什么允许不显式给号：合并稿与两份原稿都不像（那是"各取所长"的必然结果），
        所以"最像"只能当线索；真的指错了，`proof_history` 里留着被覆盖的旧正文，
        读的人能看出来并让它重走一次。显式号则是确定的（拒信里会把它给调用方）。
        """
        explicit = body.get("proof_no")
        if explicit not in (None, "", 0):
            try:
                no = int(explicit)
            except (TypeError, ValueError):
                no = 0
            if any(int(no) == int(n) for n, _ in existing):
                return int(no), "显式给了 proof_no"
            return 0, f"而 proof_no={explicit!r} 不在册（在册的是 {[n for n, _ in existing]}）"
        best: list[tuple[float, int]] = []
        for no, text in existing:
            if not str(text or "").strip():
                continue
            best.append((_PK.proof_similarity(proof, str(text)), int(no)))
        if not best:
            return 1, "这条命题还没有任何证明正文 ⇒ 合并稿落成 #p1"
        best.sort(key=lambda item: (-item[0], item[1]))
        score, no = best[0]
        return no, f"没给 proof_no，取与合并稿最像的那一份（#{no}，相似度 {score:.4f}）"

    def _merge_same_kind_version(self, tx: Any, *, row: dict[str, Any], sid: str,
                                 full: str, proof_no: int, merged_text: str,
                                 verdict: Mapping[str, Any],
                                 kind_hits: list[dict[str, Any]],
                                 merge_note: str,
                                 out: dict[str, Any]) -> dict[str, Any]:
        """`merge=True` 那一档：把合并稿作为"那一份证明的新版本"，并要求 V 重签。

        ## 写什么
        - 被命中的那一份（第 k 份）的正文换成调用方交来的合并稿：k=1 时是行上的
          `proof_text`（canonical 那一格），k>1 时是 `proofs` 清单里的那一条；
        - 旧正文整段留痕：进 `proof_history`，元素形状与 canonical 覆盖那一支逐字相同
          （`{text, sha, at, replaced_by}`）再加一格 `proof_no` —— 否则一条命题有多份
          证明时，"这一版是哪一份的旧稿"读不出来；
        - `_proof_merge` 记下这一笔合并了哪几份、相似度、谁做的。有界，只留最近 20 条。

        ## 为什么"合并"与"直接覆盖"必须分开（业主原话：重拿 V 签）
        直接覆盖只是改稿（`stale` 是读数）；合并是"两份同种证明合成一份"，它的正确性
        依赖 V 重新看过合并稿。所以这里不动 `bits`、也不写任何"审过了"的凭据，
        返回值里 `resign_required=True` 且把 V 的现行状态如实报出来（`proof_standing`）：
        合并稿与旧签的 sha 不同 ⇒ `review_standing` 现算是 `stale`，`reviewed` 是 False，
        "未重签之前不算成立"这句话由读侧现算，而不是由本函数说一句"已成立"。
        """
        from . import verifications as VR   # 惰性：签名状态与正文 sha 的唯一读口径

        old_text = VR.proof_text_of(row, proof_no)
        entry = {"text": old_text, "sha": VR.proof_sha(old_text), "at": S.now_iso(),
                 "replaced_by": VR.proof_sha(merged_text), "proof_no": int(proof_no)}
        history = [dict(h) if isinstance(h, Mapping) else h
                   for h in (row.get("proof_history") or [])]
        history.append(entry)
        row["proof_history"] = history
        if int(proof_no) == 1:
            row["proof_text"] = merged_text
        else:
            listed = []
            for item in (row.get(VR.PROOFS_KEY) or []):
                one = dict(item) if isinstance(item, Mapping) else item
                if isinstance(one, Mapping) and int(VR.proof_no_of(one)) == int(proof_no):
                    one["text"] = merged_text
                listed.append(one)
            row[VR.PROOFS_KEY] = listed
        merges = [dict(m) for m in (row.get("_proof_merge") or [])
                  if isinstance(m, Mapping)]
        merges.append({"proof_no": int(proof_no),
                       "from_proofs": [int(h["proof_no"]) for h in kind_hits] or [int(proof_no)],
                       "similarity": [float(h["similarity"]) for h in kind_hits],
                       "matched_by": str(verdict.get("basis") or ""),
                       "target": merge_note,
                       "statement_full": str(full),
                       "at": S.now_iso(), "by": f"secretary-{self.role}",
                       "resign_required": True})
        row["_proof_merge"] = merges[-20:]
        matches = [dict(m) for m in (row.get("_proposition_matches") or [])
                   if isinstance(m, Mapping)]
        matches.append({"statement_full": str(full),
                        "basis": str(verdict.get("basis") or ""),
                        "similarity": float(verdict.get("similarity") or 0.0),
                        "proof_no": int(proof_no), "at": S.now_iso(),
                        "by": f"secretary-{self.role}", "merged": True})
        row["_proposition_matches"] = matches[-20:]
        tx.upsert("statements", row, note="record_statement:merge_same_kind")
        standing: dict[str, Any] = {}
        try:
            standing = VR.review_standing(self.store.root, statement_id=sid,
                                          proof_text=merged_text, proof_no=int(proof_no))
        except Exception as exc:  # noqa: BLE001 —— 读不到签名状态不等于"已重签"
            standing = {"state": "unknown",
                        "why": f"签名状态读不出来（{type(exc).__name__}: {exc}）⇒ "
                               "按'未重签'处理（不许把没查成读成已成立）"}
        state = str(standing.get("state") or "unsigned")
        out.update(checked=True, created=False, duplicate=False, merged=True,
                   merged_same_kind=True, merged_into=sid, stmt_id=sid,
                   proof_no=int(proof_no), matched_by=str(verdict.get("basis") or ""),
                   similarity=float(verdict.get("similarity") or 0.0),
                   same_kind=kind_hits, tables=["statements"],
                   row=row, canonical_written=int(proof_no) == 1,
                   proof_history=list(row["proof_history"]),
                   proof_standing=standing, resign_required=True,
                   reviewed=state == "signed",
                   reason=(f"合并稿已作为 stmt:{sid} 第 {proof_no} 份证明的新版本落盘"
                           f"（{merge_note}；旧正文整段进 `proof_history`，sha 可与签名"
                           "台账的 `proof_sha256` 直接对上）；这一笔是同种证明合成一份，"
                           f"按业主口径要 V 重签 —— 现行签名状态是 `{state}`，"
                           "未重签之前不算成立（读侧现算，不由本函数声明）。合并稿不新增"
                           "依赖边：两条原稿的依赖面各自在册，要补新依赖走 G 的 "
                           "`register_dependency`"))
        return out

    def _statement_from(self, body: Mapping[str, Any], *, full: str, kind: str,
                        stmt_id: str) -> Any:
        """按白名单把载荷拼成 `Statement`（未知键不进库：它多半是拼错的字段名）。"""
        def _s(key: str) -> str:
            return str(body.get(key) or "")

        def _rng(key: str) -> Any:
            raw = body.get(key)
            return S.PageRange.from_dict(raw) if isinstance(raw, Mapping) else S.PageRange()

        def _lines(key: str) -> Any:
            """`line_range` 的既有约定是归一化后的区间（`{"start":120,"end":148}`）。

            本轮一度照 `Statement.line_range` 的注释（"如 120-148"）把它写成字符串，
            结果被 `tests/test_intake_actions.py`（`own_row["line_range"]["start"] == 120`）
            当场判红 —— 仓里早已定死这一格落的是归一化区间，而 `_normalize_range`
            就是那个唯一实现。所以回到 `_rng`：判据比注释权威，而"注释与判据对不上"
            这件事该单独记一笔，不该在这一笔里顺手改掉任何一边。
            """
            return _rng(key)

        origin = _s("origin") or "external_lit"
        reason = _s("quote_reason")
        if not reason.strip() and body.get("quote_verified") is not True:
            # 业主 `draft/97` §14.11：B 只交"定理内容 + 证明过程"，别的一概不要求它给。
            # 而 `Statement.validate` 的硬要求是"不是 True 就必须写 quote_reason" ——
            # 不给一个受控的默认值，那份两件式契约对自产命题（`own_result`）在结构上
            # 就不成立（实测：整笔以 `quote_verified=None 时必须写 quote_reason` 被拒）。
            # 这里填的是为什么这一格是空的，不是编一个"已核对"的结论：
            # 回验要做的是拿另一份文本逐字比，而自产命题没有第二份文本可比。
            # 调用方给了就照用（不覆盖）。
            reason = ("own_result（我们自己证的）：逐字回验这一格不适用（没有第二份文本可比）—— "
                      "证明过程在 proof_text 里，采信与否由审校（H）与验证（V）那一档判")
        return S.Statement(
            stmt_id=stmt_id, origin=origin, kind=kind,
            label=_s("label"),
            # ---- D2（2026-10-22）：正文只有一个真身，短版是派生值。
            #
            # 真机读数（`saxl-ws/data/statements.json`）：13 条命题的
            # `statement_text` 长度全是 0，而 `statement_full` 有正文 —— 同一份正文
            # 两个字段、一个空一个满，读侧读哪个都能给出另一种答案。真身定在
            # `statement_full`（schema 对它才是硬要求、下游都靠它），短版在这里由它
            # 派生（逐字复制，不截断：截断出来的"短版"是另一条命题）。派生规则只有
            # 这一处实现（`statementbody.derive_text`），读侧的唯一入口是
            # `statementbody.body_of`。
            statement_text=_SB.derive_text(full, _s("statement_text")),
            statement_full=full,
            proof_text=_s("proof_text"), source_lit_id=_s("source_lit_id") or None,
            page_range=_rng("page_range"), quote_verified=body.get("quote_verified"),
            quote_reason=reason,
            # ---- D1（2026-10-22）：回验的三栏证据必须能过这一层。
            #
            # 它们此前被 `STATEMENT_PARAM_KEYS` 收下、却没搬进 `Statement` ⇒ 静默丢掉。
            # 后果是实测出来的：H 的语义判定明明给了 `quote_span` 与调用指纹，盘上
            # 两栏全空，而 `schema._normalize_quote_mode` 把"只说了通过"的行记实成
            # `verbatim` —— 于是"逐字回验通过"这句话在盘上没有任何读数（D1）。
            # 这里只搬，不判：缺证据那一档由 `quoteevidence.enforce_quote_evidence`
            # 在写库前处理（`register_statement` 的写侧断言），读侧判据是
            # `quoteevidence.scan_quote_evidence`。
            quote_mode=_s("quote_mode"), quote_span=_s("quote_span"),
            quote_call_sha256=_s("quote_call_sha256"),
            evidence_kind=_s("evidence_kind") or "heuristic", status="active",
            derived_from=S.sorted_unique([str(x) for x in (body.get("derived_from") or [])]),
            aliases=[str(a) for a in (body.get("aliases") or []) if str(a).strip()],
            # `line_range` 是字符串（"120-148"），不是 `PageRange` —— 这里原先走的是
            # `_rng(...)`，于是落盘那一格是一个 `{start/end/label}` 的字典（`Statement`
            # 的声明是 `str`）。判据抓不到它（`to_dict` 照抄、`verify` 不查那一格），
            # 但下游按"行范围"读它的人会拿到一个字典。
            doc_id=_s("doc_id") or None, line_range=_lines("line_range"),
            bits=dict(body.get("bits") or {}), created_at=S.now_iso(),
            created_by=f"secretary-{self.role}")

    # ------------------------------------------------------------ 面适配（S1g-2）
    def surface_fit(self, *, action: str, params: Mapping[str, Any],
                    face: str = "", base: str = "") -> dict[str, Any]:
        """这件活落在被派人的读写面里做不做得成（三态读数，只报不改）。

        业主 2026-10-09 逐字：「"超越职责"的一个主要可能是无法在被分配的读写面内完成任务，这个秘书也要帮忙看，
        不只是看任务是否符合角色设计」（`draft/90` §1.11；符号级规格见 `draft/92` §3.3 的 S1g-2 块）。
        ## 判什么：只判声明里给出的盘上路径（参数名由 :func:`surface_path_args` 一处给出，与执行期硬拦同一张表）。
        逐条给"这一句话在两边的所指是不是同一个文件"：
        | `verdict` | 判据 | 意思 |
        |---|---|---|
        | `escapes` | 解析结果落在面外 | 越界：面内做不成 |
        | `in_face` | 解析结果在面里（面已知时才给这一档） | 做得到 |
        | `not_in_face` | 父视角那一份（`base/<raw>`）盘上有，而面内那一份盘上没有 | 错位：同一句路径在两边不是同一个文件 |
        | `unknown` | 面未定 / 盘上两边都没有 / 解析不了 | 判不了（不许折成 in_face） |
        ## 为什么 `not_in_face` 不需要知道槽位：新起一个子代理时槽位还没分（`surface_alloc` 与 `roster_add` 同一趟），
        所以"落点在这一族的面里的哪一格"判不了。但 `escapes` 与 `not_in_face` 两档的判据是"两份所指不是同一个
        文件"，与槽位无关 —— 它们正是"面内做不成"的主体，于是这条读数在派活那一刻就有用。
        ## 为什么只报不改：路径值是内容面（`draft/90` §1.2 那条红线）：把它改写成另一条路径 = 替父决定"这件事
        该在哪儿做"。秘书的活是把它变成看得见的事，处置权在父。参数：`face` 收件方这趟的面（`surface_of` 读得出）；
        `base` 本实例自己的根（父视角的基准）—— 不给 ⇒ 用 `self.root`（顶层那一趟两者相同；子代理那一趟它自己的
        根是它的面，调用方要传进来）。
        """
        out: dict[str, Any] = {"checked": False, "fits": None, "paths": [],
                               "reason": ""}
        names = surface_path_args(action)
        if not names:
            out["reason"] = (f"{action or '（没给动作）'} 不是 fs 动作 ⇒ 面这一维不适用"
                             "（不适用不是通过）")
            return out
        try:
            root = Path(str(base or self.root))
            face_dir = Path(str(face)).resolve() if str(face or "") else None
        except Exception as exc:  # noqa: BLE001 —— 读不成 ⇒ 判不了（不是"没问题"）
            out["reason"] = f"面/基准读不成（{type(exc).__name__}: {exc}）⇒ 判不了"
            out["checked"] = True
            return out
        rows: list[dict[str, Any]] = []
        for key in names:
            raw = (params or {}).get(key)
            if not isinstance(raw, str) or not raw.strip():
                continue                       # 没给这一格 ⇒ 没有可判的路径（如实记在 reason 里）
            rows.append(self._judge_one_path(key, raw.strip(), root=root, face_dir=face_dir))
        if not rows:
            out.update(checked=True,
                       reason=f"{action} 这一件没给路径参数（{'/'.join(names)}）⇒ 判不了"
                              "（不是通过）")
            return out
        verdicts = {str(r.get("verdict") or "") for r in rows}
        fits: bool | None
        if verdicts & {"escapes", "not_in_face"}:
            fits = False
        elif verdicts == {"in_face"}:
            fits = True
        else:
            fits = None                        # 全是 unknown ⇒ 判不了（三态不许折平）
        bad = [r for r in rows if str(r.get("verdict") or "") in ("escapes", "not_in_face")]
        reason = ""
        if fits is False:
            reason = "；".join(
                f"{r['where']}={r['value']!r} {r['why']}" for r in bad)
        elif fits is None:
            reason = "；".join(str(r.get("why") or "") for r in rows) or "没有可判的路径 ⇒ 判不了"
        out.update(checked=True, fits=fits, paths=rows, reason=reason)
        return out

    def _judge_one_path(self, where: str, raw: str, *, root: Path,
                        face_dir: Path | None) -> dict[str, Any]:
        """一条路径的判决（纯计算；`surface_fit` 的逐条那一半）。

        分两种情形（`face_dir` 有没有给），判据都只有一条：这一句话在两边指的是不是
        同一个文件。
        """
        row: dict[str, Any] = {"where": where, "value": raw, "face": "", "ws": "",
                               "face_exists": None, "ws_exists": None,
                               "verdict": "unknown", "why": ""}
        try:
            p = Path(raw)
            ws_path = (p if p.is_absolute() else (root / raw)).resolve()
        except Exception as exc:  # noqa: BLE001 —— 解析不了 ⇒ unknown（不许猜）
            row["why"] = f"路径解析不了（{type(exc).__name__}: {exc}）"
            return row
        row["ws"] = str(ws_path)
        if face_dir is not None:
            try:
                face_path = (p if p.is_absolute() else (face_dir / raw)).resolve()
            except Exception as exc:  # noqa: BLE001
                row["face"] = str(face_dir)
                row["why"] = f"面内落点算不出来（{type(exc).__name__}: {exc}）"
                return row
            row["face"] = str(face_path)
            row["face_exists"] = bool(face_path.exists())
            row["ws_exists"] = bool(ws_path.exists())
            try:
                face_path.relative_to(face_dir)
            except ValueError:
                row["verdict"] = "escapes"
                row["why"] = "越出了收件方这趟的读写面（面外一律不做）"
                return row
            if row["face_exists"] or face_path == ws_path:
                # 面里就有这一份（父已经把它切进面了），或两边算出来是同一个文件
                # ⇒ 做得到。面内的新文件也走这一档（T23："若子代理想新写文件，
                # 这个是允许的"）—— 见下面"两边都没有"那一格。
                row["verdict"] = "in_face"
                row["why"] = "落在面内（面内的新文件本来就允许）"
                return row
            if row["ws_exists"]:
                # 父视角那一份在工作区里（父指的就是它），而面内的落点不是同一个
                # 文件、且面里没有这一份 ⇒ 子在它那边找的是另一条路径：错位。
                row["verdict"] = "not_in_face"
                row["why"] = ("这一份在工作区里（父的视角指得到它），而收件方那趟的根是"
                              "它的面 ⇒ 子在它那边找的是另一条路径：面内做不成（要么把"
                              "这一份切进它的面，要么这一件就是『职责之外』那一档）")
                return row
            row["verdict"] = "unknown"
            row["why"] = ("两边都没有这一份 ⇒ 判不了（面内新建是允许的；若父要的是工作区"
                          "那一份，它现在还不存在）")
            return row
        # ---- 面未定（新起一个子代理）：判"父视角那一份在不在面可能覆盖的范围内"
        family = (root / "out" / "surfaces" / str(self.task_id or "")).resolve()
        try:
            ws_path.relative_to(root.resolve())
            in_workspace = True
        except ValueError:
            in_workspace = False
        row["ws_exists"] = bool(ws_path.exists())
        if not in_workspace:
            row["verdict"] = "escapes"
            row["why"] = ("落点在整个工作区之外（面是工作区里的一个子目录）⇒ 面内做不成")
            return row
        try:
            ws_path.relative_to(family)
            in_family = True
        except ValueError:
            in_family = False
        if in_family:
            row["verdict"] = "unknown"
            row["why"] = ("落点在这一族的面里，但槽位要到派活那一刻才分 ⇒ 判不了"
                          "（不是通过）")
            return row
        if row["ws_exists"]:
            row["verdict"] = "not_in_face"
            row["why"] = ("这一份在工作区里（父的视角指得到它），而收件方那趟的根是它的面"
                          "⇒ 子在它那边找的是另一条路径：面内做不成（要么把这一份切进它的"
                          "面，要么这一件就是『职责之外』那一档）")
            return row
        row["verdict"] = "unknown"
        row["why"] = "盘上没有这一份、也不在这一族的面里 ⇒ 判不了（新文件本来就允许）"
        return row

    def surface_readings(self, shape: str, payload: Mapping[str, Any],
                         *, face: str = "", base: str = "") -> dict[str, Any]:
        """派活形状 → 面适配读数（`summon` 一条；`summon_many` 逐项）。

        不派活的形状（`handoff` / `message` / `retire` / `roster`）⇒ 这一维不适用，
        如实说清（不适用不是通过）。
        """
        try:
            if shape == "summon":
                role = str(payload.get("role") or "")
                action = str(payload.get("action") or "")
                got = self.surface_fit(action=action,
                                       params=(payload.get("params")
                                               if isinstance(payload.get("params"),
                                                             Mapping) else {}),
                                       face=face, base=base)
                # 能力面那一维（业主 2026-10-14）：这个动作被派人（连同它出边上的伙伴）
                # 做不做得成。与路径面各判一维，两条一起给父看。
                return {**got, "shape": shape, "reach": reach_fit(role, action)}
            if shape == "summon_many":
                targets = payload.get("targets")
                if not isinstance(targets, (list, tuple)):
                    return {"shape": shape, "checked": False, "fits": None, "items": [],
                            "reason": "targets 不是数组 ⇒ 面这一维判不了"}
                items = []
                for i, item in enumerate(targets):
                    sub = item if isinstance(item, Mapping) else {}
                    action = str(sub.get("action") or "")
                    items.append({"index": i,
                                  **self.surface_fit(action=action,
                                                     params=(sub.get("params")
                                                             if isinstance(
                                                                 sub.get("params"), Mapping)
                                                             else {}),
                                                     face=face, base=base),
                                  "reach": reach_fit(str(sub.get("role") or ""), action)})
                fits: bool | None
                if any(x.get("fits") is False for x in items):
                    fits = False
                elif items and all(x.get("fits") is True for x in items):
                    fits = True
                else:
                    fits = None
                bad = [x for x in items if x.get("fits") is False]
                # 能力面那一维的汇总：哪几项在"被派人 + 它出边上的伙伴"里没人做得到
                reach_bad = [x for x in items
                             if (x.get("reach") or {}).get("verdict") == "unreachable"]
                return {"shape": shape, "checked": True, "fits": fits, "items": items,
                        "reach_bad": [x["index"] for x in reach_bad],
                        "reason": "；".join(f"targets[{x['index']}]：{x.get('reason')}"
                                            for x in bad),
                        "reach_reason": "；".join(
                            f"targets[{x['index']}]：{(x.get('reach') or {}).get('reason')}"
                            for x in reach_bad)}
        except Exception as exc:  # noqa: BLE001 —— 面这一维没查成不许打断派活
            return {"shape": shape, "checked": False, "fits": None,
                    "reason": f"面适配没跑成（{type(exc).__name__}: {exc}）"}
        return {"shape": shape, "checked": False, "fits": None,
                "reason": f"{shape} 不派活 ⇒ 面这一维不适用（不适用不是通过）"}

    def _face_of_name(self, *, owner: str, name: str) -> str:
        """名册名 → 它此刻的面目录（读不成 / 已退役 / 没登记 ⇒ 空串 + 不假装查过）。"""
        want = str(name or "")
        if not want:
            return ""
        try:
            rows, bad = self.roster_rows(owner)
            if bad:
                return ""
            item = next((r for r in rows if str(r.get("name") or "") == want), None)
            if item is None or item.get("retired"):
                return ""
            slot = str(item.get("surface") or "")
            if not slot:
                return ""
            return str(surface_dir(self.root, owner, slot))
        except Exception:  # noqa: BLE001
            return ""

    def roster_repair(self, *, owner: str) -> tuple[int, str]:
        """补登记（自愈）：把"台账里有、名册里没有"的代理行补上。返回 `(补了几条, 问题)`。

        只在写路径被调用（`draft/92` I-15：查只报不修）。补的时候按 `task_id` 升序，
        于是两个并发修复不会重复分配（名字在 `next_name` 里按已用最大序号推）。
        """
        cond = self._conductor()
        if cond is None:
            return 0, "没有 store ⇒ 读不到台账，补不了"
        try:
            rows = [r for r in cond._tasks()
                    if r.get("parent_task_id") == owner and not str(r.get("kind") or "")]
        except Exception as exc:  # noqa: BLE001
            return 0, f"台账读不成（{type(exc).__name__}: {exc}）"
        index, bad = self.roster_index(owner)
        if bad:
            return 0, f"对照表有 {len(bad)} 行读不出来 ⇒ 不补（免得重名）"
        known = {str(r.get("task_id") or "") for r in index}
        todo = sorted(str(r.get("task_id") or "") for r in rows
                      if str(r.get("task_id") or "") not in known)
        fixed = 0
        for tid in todo:
            row = next((r for r in rows if str(r.get("task_id") or "") == tid), {})
            role = str(row.get("role") or "")
            name, problem = self.next_name(owner, role)
            if problem:
                return fixed, problem
            ok, why = append_jsonl(roster_index_path(self.root, owner),
                                   {"kind": "bind", "owner": owner, "name": name, "role": role,
                                    "task_id": tid, "at": _now_iso(), "repaired": True})
            if not ok:
                return fixed, f"补登记没写成：{why}"
            ok2, why2 = append_jsonl(roster_path(self.root, owner),
                                     {"kind": "add", "owner": owner, "name": name, "role": role,
                                      "task_id": tid, "first_task_id": tid,
                                      "brief": "（补登记：这一条当时没写进名册）",
                                      # 这句话是秘书写的（不是父给的）⇒ 留痕那一格照写
                                      "brief_source": "secretary",
                                      "at": _now_iso(), "repaired": True})
            if not ok2:
                return fixed, f"名册补写没成：{why2}"
            fixed += 1
        return fixed, ""

    def resolve_down(self, *, owner: str, name: str) -> tuple[str, str]:
        """下行译码：我名下名册里的名字 → 当前调用行。"""
        return self._resolve(owner, name)

    def resolve_up(self, *, my_task_id: str, name: str) -> tuple[str, str]:
        """上行译码：我父名册里的名字 → 当前调用行（父的代号从我那一行读）。"""
        cond = self._conductor()
        if cond is None:
            return "", "没有 store ⇒ 读不到我那一行（不知道父是谁）"
        try:
            row = cond._task(str(my_task_id or ""))
        except Exception as exc:  # noqa: BLE001
            return "", f"台账读不成（{type(exc).__name__}: {exc}）"
        if not row:
            return "", f"台账里没有我这一行（{my_task_id!r}）"
        parent = str(row.get("parent_task_id") or "")
        if not parent:
            return "", "我是顶层发起 ⇒ 没有父名册（上行只能发给用户/主控）"
        return self._resolve(parent, name)

    def name_of(self, *, owner: str, task_id: str) -> tuple[str, str]:
        """反查：某个调用行属于这个名册里的哪一个名字。"""
        index, bad = self.roster_index(owner)
        if bad:
            return "", f"对照表有 {len(bad)} 行读不出来"
        for r in index:
            if str(r.get("task_id") or "") == str(task_id):
                return str(r.get("name") or ""), ""
        return "", f"对照表里没有 {task_id}（未登记）"

    #: `status` 那一格的取值（S-H，裁定 14）。前三档照 DSH `list-agents.js:24-29` 的算法逐字：
    #: 不在 live registry ⇒ `ready`；在且在跑 ⇒ `running`；否则 `idle`。
    #: 第四档 `retired` 是我们的如实加一档（见 `roster_view` 的 docstring）：
    #: DSH 的 `ready` 说的是"没有活着的 Agent、但仍可续"，而我们的销号名字永久不复用
    #: ⇒ 把它也读成 `ready` 会让模型去 `send_message` 一个再也叫不醒的名字。
    STATUS_VALUES: tuple[str, ...] = ("running", "idle", "ready", "retired")

    def parent_of(self, *, owner: str) -> dict[str, Any]:
        """这个台账号（`owner`）的「父代理」：`{"checked","task_id","role","name","why"}`。

        业主 2026-10-19：名册 = 「一个代理能看到的：自己的父代理是谁（含绝对编号）、自己的子代理是谁（含绝对
        编号）」。改前这一份名册只答得出后一半 —— 父是谁只躺在 `AgentLoop.parent_task_id` 那个内存字段里，盘上
        的名册一个字都没有；于是"给父发一条"在位址这一步无据可依（只能按角色名发，那就绕开了名册）。四个格：
        - `task_id`：「绝对编号」（我那一行的 `parent_task_id`）。空串 = 顶层发起（`open_top_level_run` 建的那一行
          是它自己的父 ⇒ 也当"没有父"）；
        - `role`：父那一行的 `role`（读不到 ⇒ 空串 + `why`）；
        - `name`：父的「名册名」。它记在「祖父」的名册索引里（相对名 vs 绝对编号：`name_of(owner=祖父, task_id=父)` 这一步就是换算），读不到 ⇒ 空串 + `why`；
        - `checked`：这一格读成了没有。`False` 「不等于」"没有父"（三态纪律）。
        只读（`draft/92` I-15：查只报不修）：一行都不写。
        """
        out: dict[str, Any] = {"checked": False, "task_id": "", "role": "", "name": "",
                               "why": ""}
        cond = self._conductor()
        if cond is None:
            out["why"] = "没有 store ⇒ 读不到台账（父是谁判不了）"
            return out
        mine = str(owner or "")
        if not mine:
            out["why"] = "没给台账号 ⇒ 不知道问谁的父"
            return out
        try:
            row = cond._task(mine) or {}
        except Exception as exc:  # noqa: BLE001 —— 读不成要如实说
            out["why"] = f"台账读不成（{type(exc).__name__}: {exc}）"
            return out
        if not row:
            out["why"] = f"台账里没有 {mine} 这一行 ⇒ 父是谁读不出来"
            return out
        pid = str(row.get("parent_task_id") or "")
        out["checked"] = True
        if not pid or pid == mine:
            out["why"] = "顶层发起（没有父代理）"
            return out
        out["task_id"] = pid
        try:
            prow = cond._task(pid) or {}
        except Exception as exc:  # noqa: BLE001
            out["why"] = f"父那一行读不成（{type(exc).__name__}: {exc}）"
            return out
        out["role"] = str(prow.get("role") or "")
        gp = str(prow.get("parent_task_id") or "")
        if gp and gp != pid:
            try:
                name, _why = self.name_of(owner=gp, task_id=pid)
            except Exception:  # noqa: BLE001
                name = ""
            out["name"] = name
        out["why"] = "" if out["name"] else "父的名册名读不到（它记在祖父的名册里）"
        return out

    def child_counts(self, *, owner: str = "",
                     snapshot: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """两个读数：子代理数 / 活跃子代理数（本方法是它们唯一的实现）。

        ## 两个数各自的定义（业主 2026-10-26 裁定，逐字见 `conductor` 那两个常量）
        - 子代理数 = 名册里还没销号的名册项数（在册、未退役）；
        - 活跃子代理数 = 其中"工作没做完还在做"的数量，口径只有一条：
          `active(node) = 自身有未收口的任务 or 任一直接子 active`（`conductor.activity_snapshot`
          是那一处的实现），所以"在等下级"也算活跃。

        两个数必须各自出现、不许相加也不许互相代替：前者回答"这一支还有几个名字在用"，
        后者回答"其中几个还在干活或还在等"。折成一个数之后，"名册只增不减"与
        "活都干完了"会长得一模一样。

        ## 范围
        `owner` 给了 ⇒ 只看那一个父的名册；不给 ⇒ 全工作区（`roster_owners` 扫
        `out/roster/<父>.jsonl`，三种旁支排除）。`by_owner` 是同一个口径的分父读数。

        ## 三态与"判不了"（不许折平）
        名册读不成 / 台账读不成 ⇒ `checked=False` + `reason`，两个数都是 `None`
        （`0` 是"名册空了"这个很强的结论，而"没读成"什么都不说）。
        某一项的名册行读得出来、但台账里没有它那一行 ⇒ 它的活跃判不了 ⇒ 进 `unjudged`
        且 `complete=False`，同时 `active_child_count` 只数判得了的那些（读数里
        `complete` 那一格就是这件事的显式声明，不许靠"大概都判得了"糊过去）。

        ## `waiting_only`（病态形状）
        每一项 `active and not self_busy` 的节点都进 `waiting_only`，带一句人话
        「它自己不忙，是在等 D2（active）」。那不是错，但父必须看得见 ——
        这一支的活积在下级身上，而中间那几层只是挂着名字在等。
        """
        from .conductor import (ACTIVE_CHILD_COUNT_KEY, CHILD_COUNT_KEY,
                                CHILD_COUNT_LABELS)

        labels = dict(CHILD_COUNT_LABELS)
        out: dict[str, Any] = {"checked": False, "reason": "", "owner": str(owner or ""),
                               CHILD_COUNT_KEY: None, ACTIVE_CHILD_COUNT_KEY: None,
                               "labels": labels, "waiting_only": [], "unjudged": [],
                               "complete": False, "by_owner": {}, "bad_roster_lines": [],
                               "note": ""}
        want = str(owner or "")
        if want:
            owners, why_dir = [want], ""
        else:
            owners, why_dir = roster_owners(self.root)
        if why_dir:
            out["reason"] = why_dir
            return out
        items: list[dict[str, Any]] = []
        bad_lines: list[str] = []
        for own in owners:
            rows, bad = self.roster_rows(own)
            bad_lines.extend(str(x) for x in bad)
            for it in rows:
                if it.get("retired"):
                    continue
                items.append({"owner": own, "name": str(it.get("name") or ""),
                              "role": str(it.get("role") or ""),
                              "task_id": str(it.get("task_id") or "")})
        out["bad_roster_lines"] = bad_lines
        if bad_lines and not items:
            out["reason"] = (f"名册有 {len(bad_lines)} 行读不出来、且没有任何一项读得出来："
                             f"{bad_lines[0]}")
            return out
        cond = self._conductor()
        if cond is None:
            out["reason"] = "没有 store ⇒ 读不到台账（活跃子代理数判不了）"
            return out
        snap = dict(snapshot) if snapshot is not None else cond.activity_snapshot()
        if not snap.get("checked"):
            out["reason"] = f"台账读不成（{snap.get('reason')}）⇒ 活跃子代理数判不了"
            return out
        by_task = dict(snap.get("by_task") or {})
        per_owner: dict[str, dict[str, int]] = {}
        active_count = 0
        waiting: list[dict[str, Any]] = []
        unjudged: list[dict[str, Any]] = []
        for it in items:
            slot = per_owner.setdefault(it["owner"], {CHILD_COUNT_KEY: 0,
                                                      ACTIVE_CHILD_COUNT_KEY: 0})
            slot[CHILD_COUNT_KEY] = int(slot[CHILD_COUNT_KEY]) + 1
            tid = it["task_id"]
            cell = by_task.get(tid)
            if cell is None:
                unjudged.append({"owner": it["owner"], "name": it["name"],
                                 "task_id": tid,
                                 "why": "台账里没有它那一行 ⇒ 它有没有未收口的活判不了"})
                continue
            if not cell.get("active"):
                continue
            active_count += 1
            slot[ACTIVE_CHILD_COUNT_KEY] = int(slot[ACTIVE_CHILD_COUNT_KEY]) + 1
            if not cell.get("waiting_only"):
                continue
            kids = [str(k) for k in (cell.get("waiting_for") or [])]
            wait_names: list[str] = []
            for k in kids:
                nm, _why = self.name_of(owner=tid, task_id=k)
                if nm:
                    wait_names.append(nm)
                else:
                    krow = by_task.get(k) or {}
                    wait_names.append(f"{krow.get('role') or '?'}（{k}）")
            waiting.append({"owner": it["owner"], "name": it["name"],
                            "role": it["role"], "task_id": tid,
                            "waiting_for": kids, "for_names": wait_names,
                            "note": ("它自己不忙，是在等 " + "、".join(wait_names)
                                     + "（active）")})
        note = (f"{labels[CHILD_COUNT_KEY]}={len(items)}，"
                f"{labels[ACTIVE_CHILD_COUNT_KEY]}={active_count}")
        if waiting:
            note += f"（其中 {len(waiting)} 个靠等下级才活跃）"
        if unjudged:
            note += (f"；有 {len(unjudged)} 项判不了活跃"
                     "（台账里没有它那一行）⇒ 活跃子代理数只数了判得了的那些")
        out.update({"checked": True, "reason": "",
                    CHILD_COUNT_KEY: len(items),
                    ACTIVE_CHILD_COUNT_KEY: active_count,
                    "waiting_only": waiting, "unjudged": unjudged,
                    "complete": not unjudged,
                    "by_owner": {k: dict(v) for k, v in sorted(per_owner.items())},
                    "note": note})
        return out

    def roster_view(self, *, owner: str, scope: str = "self",
                    limit: int = 20) -> dict[str, Any]:
        """名册视图（只读，不许修补 —— I-15）：`{"checked","rows","more","reason","diagnostics"}`。

        每一行：`name` / `role` / `brief` / `brief_source`（`parent` 父给的原话 / `secretary` 秘书从任务原文代写 /
        `""` 改前落的行）/ `state`（活跃 / 待命 / 已停 / 已退役 / 未登记）/ `retirable`（按 `conductor.retire_ready`
        的三分支）/ `items_open`（只报不拦）/ `task_id`（当前调用），外加 S-H（裁定 14）补的三格：`status`（机器
        可判的那一格：`running` / `idle` / `ready` / `retired` —— 中文那五档是给人读的，而"父要不要现在动手"需要
        一格能直接判的）、`in_flight`（它名下此刻还在跑的任务数，`Conductor.children_facts` 现算）、`last_reading`
        （它最近一条工作报告的摘要，`latest_report_of` 的同一份数据，但一次读一份手稿再逐行取）。DSH 的
        `list_agents` 没有这一格，我们的比它全 ⇒ 照裁定"净减一样别丢"留着。`scope="descendants"` 时给全树（每
        一行多 `parent` 与 `depth`）—— 改前只有下一层。规模：默认只回 20 项 + `more`（与 `inbox_digest` 同族口径）。
        ## 父是谁（业主 2026-10-19：「名册 = 父 + 子 + 绝对编号」）：每一份视图都带一格 `parent`（见
        :meth:`parent_of`：绝对编号 + 角色 + 名册名），`scope="descendants"` 的行另带 `parent_task_id` —— 改前
        那些行只有相对名 `parent`，而"相对名"没法拿去发消息（那正是这一轮要补的那一格）。于是"我能通话的是谁"
        这件事在同一份读数里自足了，寻址不必再另造一个视图。
        ## 逐行 diagnostic（不再一行坏就整份拒）：改前名册里有一行读不出来 ⇒ `{"checked": False, "rows": []}`
        （整体拒）。DSH 的 `list-agents.js:30-47` 是逐行报 `corrupt/unsupported/unavailable`。现在照它：好行照常
        渲染，坏行逐条落进 `diagnostics`（带行号与类别）。只有一种情形仍然整体拒：一条好行都没有而坏行有（三态纪律挡的正是"名册是空的"与"名册读不成"被折成同一句话）。
        ## 两个读数各占一格（业主 2026-10-26）
        这一份视图顶上带 `child_count`（子代理数 = 名下未销号的名册项数）与
        `active_child_count`（活跃子代理数 = 其中"工作没做完还在做"的数量，含靠等下级才
        活跃的那些），另有一格 `counts`（`Secretary.child_counts` 的整份读数：`owner` /
        `waiting_only` / `unjudged` / `note`）。两个数不许相加、不许互相代替 ——
        口径与三态都在 :meth:`child_counts` 里，这里只转发。每一行另带 `active` /
        `waiting_only` / `waiting_note`：`active` 是"按继承口径算，它算不算活跃"，
        与 `state`（它自己此刻在不在跑）是两件事（"在等"也算活跃）。
        读不成 ⇒ 两个数都是 `None`（不是 0）。
        """
        from .conductor import ACTIVE_CHILD_COUNT_KEY, CHILD_COUNT_KEY

        cond = self._conductor()
        rows, bad = self.roster_rows(owner)
        diagnostics = [_diagnose_line(line) for line in bad]
        # 「我自己的父是谁」那一格（业主 2026-10-19：名册 = 父 + 子 + 绝对编号）。
        # 改前这一份视图只有"我名下的子代理"—— 父是谁只能从 `AgentLoop.parent_task_id`
        # 那个内存字段读到，而名册自己（盘上那一份）答不上来。现在六条 return 都带上它。
        parent = self.parent_of(owner=owner)

        def _fail(reason: str) -> dict[str, Any]:
            """这一份视图"没查成"的统一形状（两个读数都是 None，不是 0）。"""
            return {"checked": False, "rows": [], "more": 0, "scope": scope,
                    "diagnostics": diagnostics, "parent": parent, "reason": reason,
                    "counts": None, CHILD_COUNT_KEY: None,
                    ACTIVE_CHILD_COUNT_KEY: None}

        if not rows and bad:
            return _fail(f"名册有 {len(bad)} 行读不出来、且没有一行读得出来：{bad[0]}")
        if cond is None:
            return _fail("没有 store ⇒ 读不到台账（状态判不了）")
        try:
            ready = cond.retire_ready(owner)
        except Exception as exc:  # noqa: BLE001
            return _fail(f"就绪读数没读成（{type(exc).__name__}: {exc}）")
        if not ready.get("checked"):
            return _fail(f"就绪读数没读成（{ready.get('reason')}）")
        # 活跃读数只取一次（逐行调 `active_reading` 会把同一张台账读 N 遍）：
        # `counts` 与逐行那三格共用这一份快照。
        snap = cond.activity_snapshot()
        counts = self.child_counts(owner=owner, snapshot=snap)
        activity = dict(snap.get("by_task") or {}) if snap.get("checked") else {}
        name_of_tid = {str(r.get("task_id") or ""): str(r.get("name") or "") for r in rows}
        by_child = {str(r["task_id"]): r for r in ready.get("ready", [])}
        # 一份手稿读数，逐行取"它最近报了什么"（每行读一次会把名册变成 N 次全表读）。
        reports: dict[str, str] = {}
        try:
            mrows, _mbad = MS.read_rows(self.root)
            for r in mrows:
                tid = str(r.get("task_id") or "")
                if tid and str(r.get("summary") or ""):
                    reports[tid] = str(r.get("summary") or "")
        except Exception:  # noqa: BLE001 —— 手稿读不成 ⇒ 那几格空着（不是"它没报过"）
            reports = {}
        targets = self._roster_targets(owner=owner, rows=rows, scope=scope, cond=cond)
        out: list[dict[str, Any]] = []
        for t in targets:
            r, parent_name, depth = t["row"], t["parent"], t["depth"]
            parent_tid = str(t.get("parent_tid") or "")
            tid = str(r.get("task_id") or "")
            branch = str(t.get("branch") or "")
            facts = t["facts"]
            state = _state_from(branch, bool(r.get("retired")), cond, tid)
            row: dict[str, Any] = {
                "name": str(r.get("name") or ""), "role": str(r.get("role") or ""),
                "brief": str(r.get("brief") or ""), "state": state,
                # 简介是谁写的（`parent` 父给的原话 / `secretary` 秘书代写 / `""` 改前的行）
                "brief_source": str(r.get("brief_source") or ""),
                "retirable": branch == "waiting_no_children",
                "items_open": int(((by_child.get(tid) or {}).get("reading") or {})
                                  .get("items_open") or 0),
                "task_id": tid,
                "status": _status_enum(facts, retired=bool(r.get("retired"))),
                "in_flight": int(facts.get("in_flight") or 0),
                "last_reading": reports.get(tid, ""),
                # 活跃按继承口径算（业主 2026-10-26：有活跃的下级，自己已收口也算活跃），
                # 与 `state` 是两件事；`waiting_note` 是"靠等"的那一句人话。
                "active": bool((activity.get(tid) or {}).get("active")),
                "waiting_only": bool((activity.get(tid) or {}).get("waiting_only")),
                "waiting_note": str((cond.active_reading(
                    tid, names=name_of_tid, snapshot=snap).get("note") or "")
                    if snap.get("checked") else ""),
            }
            if scope == "descendants":
                row["parent"] = parent_name
                # 业主 2026-10-19：`parent` 记的是相对名，而通话要的是绝对编号。
                # 两格都给（相对名给人读，绝对编号给机器判）；改前只有相对名。
                row["parent_task_id"] = parent_tid
                row["depth"] = depth
            out.append(row)
        more = max(0, len(out) - int(limit))
        return {"checked": True, "rows": out[:int(limit)], "more": more, "scope": scope,
                "diagnostics": diagnostics, "parent": parent, "reason": "",
                "counts": counts, CHILD_COUNT_KEY: counts.get(CHILD_COUNT_KEY),
                ACTIVE_CHILD_COUNT_KEY: counts.get(ACTIVE_CHILD_COUNT_KEY)}

    def _roster_targets(self, *, owner: str, rows: list[dict[str, Any]], scope: str,
                        cond: Any) -> list[dict[str, Any]]:
        """要渲染的那几行（`scope="descendants"` 时是全树，带 `parent`/`depth`）。

        深度上限 64：坏链不许把这里变成死循环（与 `inside_subtree` 的上行链同一条纪律）。
        每一层的 `facts` 现算一次（`children_facts`）—— 只在要渲染的那几行上算。
        """
        def parent_facts(tid: str) -> dict[str, Any]:
            try:
                got = cond.children_facts(tid)
            except Exception:  # noqa: BLE001
                return {"checked": False}
            return got

        out: list[dict[str, Any]] = []
        root_by = dict((parent_facts(owner).get("by_child") or {}))
        # 每一层的"可退役分支"（`branch` 是 `_state_from` 折四态的那一格）。
        #
        # 2026-10-20（真机读数驱动，`projects/tree-check`）：改前 `by_child`（在 `roster_view`
        # 里由 owner 那一层的 `retire_ready` 构造）只覆盖直接子，于是全树视图里
        # 孙代及以下的 `branch` 恒为空 ⇒ `_state_from` 落到「未登记」，而它们明明在名册上。
        # 实测那一份工作区：7 行里有 5 行（C1/F1/B1/B2/E1 --- 深度 2/3）被读成「未登记」，
        # 只有直接子 D1 读对（已停）。这与 `draft/90` §1.4「必须看到名册名 + 一句简介 +
        # 工作状态」直接冲突，也是机制②（M 看整棵树）唯一的真缺口。
        # 修法：逐层问它父那一层的 `retire_ready`（同一处实现，不另写一份分支判据），
        # 每个父只问一次（`branch_by_parent` 缓存）。
        branch_by_parent: dict[str, dict[str, str]] = {}

        def branches_of(parent_id: str) -> dict[str, str]:
            if parent_id in branch_by_parent:
                return branch_by_parent[parent_id]
            got: dict[str, Any]
            try:
                got = cond.retire_ready(parent_id)
            except Exception:  # noqa: BLE001 —— 读不成 ⇒ 这一层没有分支（状态如实落到"未登记"）
                got = {"checked": False}
            found = ({str(r.get("task_id") or ""): str(r.get("branch") or "")
                      for r in (got.get("ready") or [])} if got.get("checked") else {})
            branch_by_parent[parent_id] = found
            return found
        if scope != "descendants":
            top = branches_of(str(owner or ""))
            return [{"row": r, "parent": "", "parent_tid": "", "depth": 1,
                     "branch": top.get(str(r.get("task_id") or ""), ""),
                     "facts": dict(root_by.get(str(r.get("task_id") or "")) or {})}
                    for r in rows]
        # 全树：逐层往下，每一层的 facts 从它的父那一格里取。
        # 这一格最容易写错（第一版就是）：`children_facts(X)` 给的是"X 名下"的读数，
        # 而某一行要的是"它父名下的它自己"那一格 —— 拿 X 去查 X 只会得到空表，
        # 于是全树的每一行都会读成 `ready`（一个安静的错误：没有任何地方会报错）。
        top_branches = branches_of(str(owner or ""))
        queue: list[tuple[dict[str, Any], str, str, int, dict[str, Any], str]] = [
            (r, "", str(owner or ""), 1,
             dict(root_by.get(str(r.get("task_id") or "")) or {}),
             top_branches.get(str(r.get("task_id") or ""), "")) for r in rows]
        seen = 0
        while queue and seen < 512:
            r, parent_name, parent_tid, depth, facts, branch = queue.pop(0)
            seen += 1
            out.append({"row": r, "parent": parent_name, "parent_tid": parent_tid,
                        "depth": depth, "branch": branch, "facts": facts})
            if depth >= 64:
                continue
            tid = str(r.get("task_id") or "")
            kids, _bad = self.roster_rows(tid)
            if not kids:
                continue
            by = dict((parent_facts(tid).get("by_child") or {}))
            their = branches_of(tid)
            for k in kids:
                kt = str(k.get("task_id") or "")
                queue.append((k, str(r.get("name") or ""), tid, depth + 1,
                              dict(by.get(kt) or {}), their.get(kt, "")))
        return out

    def latest_report_of(self, *, task_id: str, role: str = "") -> dict[str, Any]:
        """某个实例最近的工作报告（退役第①支要端给父的东西）。

        口径：优先 `handoffs` 里 `task_id == 该实例` 的那些行；一条都没有时退回
        "发信人是该角色"的最新一行（历史 595 行没有 `task_id`，`draft/94` §3 ——
        这条退路要写明，否则那段历史读起来像"它从没报过"）。
        体积：默认只给摘要 + 编号 + 正文前 300 字（全文由父自己 `manuscripts.read`）。
        """
        try:
            rows, bad = MS.read_rows(self.root)
        except Exception as exc:  # noqa: BLE001
            return {"checked": False, "reason": f"手稿读不成（{type(exc).__name__}: {exc}）"}
        mine = [r for r in rows if str(r.get("task_id") or "") == str(task_id)]
        source = "task_id"
        if not mine and role:
            mine = [r for r in rows if str(r.get("sender") or "") == str(role)]
            source = "sender"
        if not mine:
            return {"checked": True, "handoff_id": "", "summary": "",
                    "head": "", "at": "", "source": "", "bad_rows": len(bad),
                    "reason": "这个实例名下没有找到报告行"}
        mine.sort(key=lambda r: (str(r.get("created_at") or ""), str(r.get("id") or "")))
        last = mine[-1]
        return {"checked": True, "handoff_id": str(last.get("id") or ""),
                "summary": str(last.get("summary") or ""),
                "head": _clip_text(str(last.get("body") or ""), 300),
                "at": str(last.get("created_at") or ""), "source": source,
                "bad_rows": len(bad), "reason": ""}

    def active_children_of(self, *, task_id: str) -> dict[str, Any]:
        """退役第②支：它自己名下的活跃子代理（代理轴，不是父的）。"""
        cond = self._conductor()
        if cond is None:
            return {"checked": False, "rows": [], "reason": "没有 store ⇒ 读不到台账"}
        try:
            return cond.active_children(task_id)
        except Exception as exc:  # noqa: BLE001
            return {"checked": False, "rows": [],
                    "reason": f"{type(exc).__name__}: {exc}"}

    def retire(self, *, owner: str, name: str, by_task_id: str = "",
               reason: str = "") -> dict[str, Any]:
        """退役（业主 §1.9 的三分支，`draft/90` §1.9 逐字）。返回：

        `{"ok","action":"retired"|"reported"|"refused","report":{…},"why":[…], "reading":{…}}`

        - `active` ⇒ `reported`：把最近的工作报告端给父，不退役；
        - `waiting_with_children` ⇒ `reported`：把那些子代理在它名册里的任务简介端给父；
        - `waiting_no_children` ⇒ `retired`：写退役事件 + 销号名单 + 对照表标退役 +
          `conductor.note_edge_release`（父侧那一笔幂等落痕）；
        - 未登记 / 读不成 / 已销号 ⇒ `refused`（没读成 ≠ 可以退役）。

        ## `reason`（D-59）：父发起销号时那一句理由，逐字落进三份台账
        销号是父的决定，而"为什么"只有父知道。改前这一句没有落点：`retired` 三行
        只记了 `branch` / `at` / `by`，于是"这个子是怎么退场的"在盘上永远读不回来
        （`by` 是编号，不是理由）。现在它原样进名册那一行、对照表那一行与销号名单那一行
        （`reason` 键，缺省空串 ⇒ 这一段对既有调用方的落盘行只多一个键，不改任何既有键）。
        """
        cond = self._conductor()
        if cond is None:
            return {"ok": False, "action": "refused", "report": {},
                    "why": ["没有 store ⇒ 读不到台账（没读成，不是'不在跑'）"]}
        tid, problem = self.resolve_down(owner=owner, name=str(name))
        if problem:
            if self._is_retired(owner, str(name)):
                return {"ok": False, "action": "refused", "report": {},
                        "why": [f"{name} 已经销号过（业主 B1：名字永久不复用）"]}
            return {"ok": False, "action": "refused", "report": {}, "why": [problem]}
        if self._is_retired(owner, str(name)):
            return {"ok": False, "action": "refused", "report": {},
                    "why": [f"{name} 已经销号过（业主 B1）"]}
        try:
            ready = cond.retire_ready(owner)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "action": "refused", "report": {},
                    "why": [f"就绪读数没读成（{type(exc).__name__}: {exc}）"]}
        if not ready.get("checked"):
            return {"ok": False, "action": "refused", "report": {},
                    "why": [f"就绪读数没读成（{ready.get('reason')}）"]}
        row = next((r for r in ready.get("ready", []) if str(r.get("task_id")) == tid), None)
        if row is None:
            return {"ok": False, "action": "refused", "report": {},
                    "why": [f"{name}（{tid}）不在就绪清单里（已经退过，或它不在这个父名下）"]}
        branch = str(row.get("branch") or "")
        reading = dict(row.get("reading") or {})
        if branch == "active":
            report = self.latest_report_of(task_id=tid, role=str(row.get("role") or ""))
            return {"ok": False, "action": "reported", "report": report,
                    "why": [f"{name} 还在跑 ⇒ 先看它最近报了什么，不退役"],
                    "reading": reading}
        if branch == "waiting_with_children":
            kids = self.active_children_of(task_id=tid)
            if not kids.get("checked"):
                return {"ok": False, "action": "refused", "report": {},
                        "why": [f"{name} 名下的活跃子代理没读成（{kids.get('reason')}）"]}
            briefs = []
            for k in kids.get("rows", []):
                kid_name, _why = self.name_of(owner=tid, task_id=str(k.get("task_id") or ""))
                child_rows, _bad = self.roster_rows(tid)
                brief = next((str(x.get("brief") or "") for x in child_rows
                              if str(x.get("name") or "") == kid_name), "")
                briefs.append({"name": kid_name or "（未登记）",
                               "role": str(k.get("role") or ""),
                               "brief": brief, "state": str(k.get("state") or "")})
            return {"ok": False, "action": "reported", "report": {"children": briefs},
                    "why": [f"{name} 名下还有活跃子代理 ⇒ 不退役（它还在干什么活见 report）"],
                    "reading": reading}
        ok, why = cond.note_edge_release(owner, child_task_id=tid, attempt=1)
        if not ok and "已经记过" not in why:
            return {"ok": False, "action": "refused", "report": {}, "why": [why],
                    "reading": reading}
        at = _now_iso()
        wrote_roster, why_r = append_jsonl(roster_path(self.root, owner),
                                           {"kind": "retire", "owner": owner, "name": str(name),
                                            "task_id": tid, "branch": branch, "by": str(by_task_id),
                                            "reason": str(reason or ""),
                                            "reading": reading, "at": at})
        wrote_index, why_i = append_jsonl(roster_index_path(self.root, owner),
                                          {"kind": "retire", "owner": owner, "name": str(name),
                                           "task_id": tid, "reason": str(reason or ""), "at": at})
        wrote_retired, why_x = append_jsonl(retired_path(self.root, owner),
                                            {"owner": owner, "name": str(name), "task_id": tid,
                                             "role": str(row.get("role") or ""), "at": at,
                                             "reason": str(reason or ""),
                                             "branch": branch})
        if not (wrote_roster and wrote_index and wrote_retired):
            return {"ok": False, "action": "refused", "report": {},
                    "why": [f"退役没写全（名册={wrote_roster}/{why_r} 对照表={wrote_index}/{why_i} "
                            f"销号={wrote_retired}/{why_x}）"],
                    "reading": reading}
        # S1n（业主补充）：退役 ⇒ 面归还"可分配池"（名字不回收、面回收）。
        # 归还前先归档；归档失败 ⇒ 槽位停在"待释放"，读数里如实写（不入池）。
        surface_note = ""
        slot = next((str(r.get("surface") or "") for r in self.roster_rows(owner)[0]
                     if str(r.get("name") or "") == str(name)), "")
        if slot:
            state, why_s = self.surface_release(owner=owner, name=str(name), slot=slot)
            surface_note = (f"面 {slot} 已归还池里" if state == "空闲"
                            else f"面 {slot} 停在待释放（{why_s}）")
        return {"ok": True, "action": "retired", "report": {},
                "why": [f"{name} 退役：{branch}（子已停 + 它名下无活跃子代理）"]
                       + ([surface_note] if surface_note else []),
                "surface": slot, "reading": reading}

    # ---- 名册的内部小工具

    def _resolve(self, owner: str, name: str) -> tuple[str, str]:
        index, bad = self.roster_index(owner)
        if bad:
            return "", f"对照表有 {len(bad)} 行读不出来 ⇒ 不译（{bad[0]}）"
        for r in index:
            if str(r.get("name") or "") == str(name) and not r.get("retired"):
                return str(r.get("task_id") or ""), ""
        return "", f"对照表里没有 {name!r}（未登记或已退役）"

    def _name_exists(self, owner: str, name: str) -> bool:
        """这个名字在这个父名下用过没有（名册正文 + 对照表 + 销号名单，三份都算）。

        为什么要三份（D-66）：名册正文缺行时，一个用过的名字可能只在对照表的调用
        记录里、或只在销号名单里；只读正文会把它算成空号，于是同一个名字被发给
        另一个子代理。名字是身份，"用过"是永久事实。
        """
        return str(name) in self._used_names(owner)

    def _is_retired(self, owner: str, name: str) -> bool:
        rows, _bad = self.retired_names(owner)
        return any(str(r.get("name") or "") == str(name) for r in rows)

    # ------------------------------------------------------------ 内部

    def _log(self, message: str) -> None:
        if self.log is None:
            return
        try:
            self.log(message)
        except Exception:  # noqa: BLE001 - 日志口子坏了不该带走秘书的判断
            pass


#: 非平凡性档位的旁支台账（不新增表、不改 schema）：一行 = 一次判断。
#: 为什么用旁支而不是 `statements` 的列：档位会随研究进展变（T4 造出梯子后要降到 T2/T3），
#: 它是时间序列不是记录属性；append-only 的旁支天然保留"降档发生过"的完整历史。
#: 键用 `statement_sha256` 而不是 `stmt_id`：判断发生在入库之前，那时还没有编号。
NONTRIVIALITY_LEDGER = "nontriviality.jsonl"


def nontriviality_path(root: str | Path) -> Path:
    """档位旁支台账的路径：`out/secretary/nontriviality.jsonl`。"""
    return Path(root) / "out" / "secretary" / NONTRIVIALITY_LEDGER


def _statement_sha(statement_full: str) -> str:
    return hashlib.sha256(str(statement_full or "").strip().encode("utf-8")).hexdigest()


def _nontriviality_level(value: Any) -> int | None:
    """把模型给的档位收敛到 `0|1|2|3|4`；别的（含缺省）一律 `None` = 判不了。

    2026-10-23 起 `0` 是一档真的档位（T0 基础定理或初步结论），所以"判不了"必须
    换一个值：`None`。这里刻意不把坏输入折成 0 —— 那会把"模型给了 `1.9`"读成
    "这是一条基础定理"，正是"静默降级"的形态。同理也不许折成 1。

    只认整数（或纯数字字符串）：`1.9` 不是"第 1 档"，它是坏输入。
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        got: Any = value
    elif isinstance(value, str) and value.strip().isdigit():
        got = int(value.strip())
    else:
        return None
    return got if got in NONTRIVIALITY_LEVELS else None


def _level_from_row(row: Mapping[str, Any]) -> int | None:
    """从一行台账读档位（含旧刻度的兼容，唯一读口）。

    旧行（没有 `scale` 标记）里 `0` 是"判不了"；新行（有标记）里 `0` 是 T0。
    这一区分只在这里做一次，理由见 :data:`NONTRIVIALITY_SCALE`。
    """
    level = _nontriviality_level(row.get("nontriviality"))
    if not str(row.get("scale") or "").strip():
        return level if level else None
    return level


def append_nontriviality(root: str | Path, *, statement_full: str, level: Any,
                         basis: str = "", role: str = "", task_id: str = "",
                         effort: Mapping[str, Any] | None = None,
                         text_truncated: bool = False) -> None:
    """追加一行档位读数（append-only；显式 LF，Windows 上不留 CRLF）。

    `level` 给 `None`（或缺省/坏值）⇒ 这一行记的是"判不了"：`nontriviality: null`
    且 `label` 空。判不了照旧落一行 —— 它也是读数（"没人判过"与"台账里没这一条"
    在盘上应当分得开）。

    ## `effort` 为什么也落下来（2026-10-24，B2）
    档位从这一天起是"证明花的力气"给的，而力气是四项读数 + 一个分数。只落档位的话，
    读的人（人、页面、复算脚本）无法判断"这一档是读数给的还是模型随口给的"——
    而后者正是改前那个形态。所以四项读数、分数与边界表里的那一档一起落进这一行：
    复算的人拿同一张 :data:`EFFORT_TIER_BANDS` 一比就能确认这一档对不对。

    `text_truncated` 同理落下来：它是"这一行判不了"的一个具体原因，与"缺某项读数"、
    "判了"三者在盘上必须分得开（三态纪律的第四格：输入不完整也是一种没查成）。
    """
    path = nontriviality_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    got = _nontriviality_level(level)
    row = {"at": _now_iso(), "statement_sha256": _statement_sha(statement_full),
           "statement_chars": len(str(statement_full or "")),
           # 刻度标记：读侧靠它区分"0 = T0"与旧行的"0 = 判不了"（见 NONTRIVIALITY_SCALE）
           "scale": NONTRIVIALITY_SCALE,
           "nontriviality": got, "label": nontriviality_label(got),
           "basis": str(basis or ""),
           "effort": dict(effort or {}), "text_truncated": bool(text_truncated),
           "role": str(role or ""), "task_id": str(task_id or "")}
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        # `default=str` 与全仓同一口径（`tests/test_json_dumps_has_a_default.py`）：这一行是
        # append-only 档位台账的唯一写口，它抛出去会丢一行读数而调用方看不出来。
        handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True, default=str) + "\n")


def nontriviality_of(root: str | Path, statement_full: str) -> dict[str, Any]:
    """这条命题当前的非平凡性档位（折叠旁支台账里同一个 sha 的最后一行）。

    三态：读到 ⇒ `{"tri": "computed", "level": 0..4, "label": "T0".."T4", "basis": …}`；
    没有记录 / 记的是判不了 ⇒ `{"tri": "unknown", "level": None, "label": "", …}`
    （不是 1，也不是 0 —— 0 从 2026-10-23 起是 T0，一档真的档位）。
    """
    path = nontriviality_path(root)
    sha = _statement_sha(statement_full)
    if not path.is_file():
        return {"tri": "unknown", "level": NONTRIVIALITY_UNJUDGED, "label": "", "basis": "",
                "at": "", "reason": f"{path} 不在盘上 ⇒ 这条命题还没有档位读数"}
    last: dict[str, Any] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if str(row.get("statement_sha256") or "") == sha:
            last = row
    if not last:
        return {"tri": "unknown", "level": NONTRIVIALITY_UNJUDGED, "label": "", "basis": "",
                "at": "", "reason": "台账里没有这条命题的档位读数",
                "effort": {}, "text_truncated": False}
    level = _level_from_row(last)
    return {"tri": "computed" if level is not None else "unknown", "level": level,
            "label": nontriviality_label(level),
            "basis": str(last.get("basis") or ""), "at": str(last.get("at") or ""),
            # 力气读数与截断标记原样带出来（写侧落进台账的那两份）：
            # 读的人要能自己按同一张边界表复算这一档，而不是只能相信 basis 那句话。
            "effort": dict(last.get("effort") or {}),
            "text_truncated": bool(last.get("text_truncated"))}


# ---------------------------------------------------------------- 判档位的"力气"读数
#
# 业主 2026-10-24 的裁定（逐字）：「"后面哪一步会用到它 / 比已知那条强在哪"这俩和非平凡度
# 有啥关系？不一定一条定理后面要用，也不一定存在"已知那条"，看证明花的力气就能判非平凡度」。
# 所以判据从"会不会被用到 / 比已知强在哪"换成这份证明花的力气。四项读数各有定义、
# 各有计分权重（唯一一处定义就在下面这张表）：
#
# | 读数 | 怎么数 | 计分 |
# |---|---|---|
# | 体量 chars | 证明正文的字符数（超过 PROOF_BODY_CAP 就判不了） | 每 2000 字 1 分 |
# | 步骤 steps | 编号步骤行 / 分节标题 / 「步骤 N」「第 N 步」三者取最大 | 每 6 步 1 分 |
# | 引理 lemmas | 正文里点名的不同引理号（引理 / 推论 / Lemma / Corollary） | 每 2 条 1 分 |
# | 跨度 clusters | 命中的工具簇个数（见 EFFORT_TOOL_CLUSTERS） | 每多一簇 1 分 |
# | 绕路 detour | 正文自述绕开了熟路（"不使用 / 绕开 / 另证 / 自足"等） | 命中 +1 分 |
#
# 四档边界（分数 = 上面五项之和，整数）：
#
# | 档 | 分数 | 典型读数 |
# |---|---|---|
# | T0 | 0–1 | 正文 < 2000 字、步骤 < 6、引理 < 2、单一工具簇、不绕路 |
# | T1 | 2–3 | 只有一项读数刚过线（例如正文 2000–4000 字） |
# | T2 | 4–7 | 体量大：约 5000 字 + 6 步 + 2 条引理 + 跨一簇 |
# | T3 | 8–15 | 技巧多或跨领域：约 8000 字 + 10 条引理 + 3 簇 |
# | T4 | 16 以上 | 极长或极偏：两万字以上，且引理与工具簇都拉满 |
#
# 三态纪律不变：一项都读不到（没有证明正文）或正文被截断 ⇒ 档位是 None，且原因必须点名
# 缺的是哪一项读数 —— 不许拿 0 冒充"判不了"，也不许拿"材料不足"冒充"输入不完整"。

#: 力气分数 → 档位的边界表（唯一一处定义；改它等于改"多不平凡"的口径）。
#:
#: 分数是五项读数之和（见上面那张表），每档的分数区间写在第一、二格，第三格是档位名。
#: 判据 `tests/test_nontriviality_is_judged_by_effort.py` 的 (c)/(d) 钉的就是这条表的
#: 两头：体量大 + 多条引理 + 跨簇的证明必须进 T2 以上，三行只用定义的证明必须落在 T0。
EFFORT_TIER_BANDS: tuple[tuple[int, int, str], ...] = (
    (0, 1, "T0"), (2, 3, "T1"), (4, 7, "T2"), (8, 15, "T3"), (16, 10 ** 9, "T4"),
)

#: "跨度"读数的单位：工具簇。一个簇 = 一类论证工具；簇的个数就是"跨了几个领域"的机器读数。
#:
#: 为什么按簇数而不是按"领域"这个名字：数学里的领域边界是人的约定，而一份证明用了哪几类
#: 工具是文本里读得出来的。判据只认后者（可复算），前者留在 basis 的一句话里。
EFFORT_TOOL_CLUSTERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("group-action", ("群作用", "轨道", "稳定化子", "共轭", "陪集", "正规化子", "中心化子")),
    ("counting", ("同余", "模 p", "mod p", "Frobenius", "Lucas", "二项式", "计数",
                  "整除", "素因子")),
    ("linear", ("线性", "矩阵", "特征值", "张量", "维数", "对角", "秩")),
    ("analysis", ("连续", "极限", "测度", "积分", "收敛", "范数", "可微")),
    ("homology", ("同调", "上同调", "范畴", "函子", "层", "谱序列")),
    ("combinatorics", ("生成函数", "容斥", "双射", "极值", "图论", "Ramsey")),
    ("probability", ("期望", "方差", "随机", "概率", "大数")),
    ("formal", ("Lean", "Coq", "Isabelle", "形式化", "证明助手")),
)

#: 步骤读数的三个模式（取各自命中数的最大值，不求和：同一行可能被两条同时数到）。
_EFFORT_STEP_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^\s*(\d+)[.、)．]\s", re.M),
    re.compile(r"^\s*#{2,4}\s", re.M),
    re.compile(r"(?:步骤|第)\s*(\d+)\s*步"),
    re.compile(r"Step\s*(\d+)", re.I),
)

#: 引理号（"引入了哪几条引理"）：引理 / 推论 / Lemma / Corollary 后面那个号。
_EFFORT_LEMMA_RE = re.compile(r"(?:引理|推论|Lemma|Corollary)\s*([0-9]+(?:\.[0-9]+)?)", re.I)

#: 引到的既有定理号（只作 basis 里的读数列出，不单独计分：它们已经通过"工具簇"与"引理数"
#: 两条读数进入了分数，再计一次就是同一个力气算两遍）。
_EFFORT_THEOREM_RE = re.compile(r"(?:定理|Theorem|命题|Proposition)\s*([0-9]+(?:\.[0-9]+)?)", re.I)

#: "绕了远路"的自述词：命中即说明这份证明自己说了"我避开了某条熟路"。
#: 它只认文本自述，不替作者判断"世上有没有更短的路"（那件事机器判不了）。
_EFFORT_DETOUR_WORDS: tuple[str, ...] = (
    "绕开", "绕远", "另证", "不依赖", "不使用", "避开", "非标准", "自足", "重新证明",
)

#: 一段文本"像不像一份证明正文"的判据（用于 statement_full 这一栏的回退读法）。
#:
#: 为什么需要它：业主写进 `specs/b.py` 的口径是"证明正文交在 proof_text 里"，而真机上
#: B 有时把整段证明写进 statement_full（sylow4 的那条 8375 字就是）。这一格只回答
#: "这段文本能不能当证明正文去读力气"，不回答"它是不是好证明"。
#:
#: ## 为什么只认结构标记、不认"证明正文"这四个字（2026-10-24 真机复算改的口径）
#: 第一版把 `证明正文` 与 `###` 也算标记，于是 sylow4 那几条 500 字上下的命题正文
#: 全被当成证明读了：它们写着"完整逐字证明见本行 proof_text""三者的证明只使用引理 0…"，
#: 于是"引理 0/1/2/3/4"被数成 5 条引理、档位凭空到 T2。提到证明不等于它是证明。
#: 现在只认真的开证/收证那一类标记；长正文（>= 2000 字）仍然直接算（真机那条 8375 字
#: 的整段证明就是这么认的）。
_EFFORT_PROOF_MARKERS: tuple[str, ...] = (
    "证明：", "证：", "证毕", "∎", "QED", "归纳法", "反证",
)


def _looks_like_a_proof(text: str) -> bool:
    """这段文本能不能当"证明正文"来读力气（判据见 :data:`_EFFORT_PROOF_MARKERS`）。

    太短的（< 40 字）一律不算：一条命题正文里出现"证："这种字眼时，40 字以下连一行
    推导都放不下，把它当证明读只会让读数虚高。
    """
    body = str(text or "")
    if len(body) >= 2000:
        return True
    if len(body.strip()) < 40:
        return False
    return any(mark in body for mark in _EFFORT_PROOF_MARKERS)


def proof_effort_readings(*, statement_full: str = "", proof_text: str = "",
                          basis_hint: str = "") -> dict[str, Any]:
    """这份证明花了多大力气（四项读数 + 绕路 + 分数），以及"哪一项读不到"。

    这是 B2 的机器侧：判档位的唯一判据。它是纯函数（不打桩、不读盘、不调模型），
    所以"档位是不是按力气判的"这件事可以被复算 —— 判据
    `tests/test_nontriviality_is_judged_by_effort.py` 的 (f) 就是把这里的输出打桩成全 0 /
    恒 T3，看 (c)/(d) 会不会跟着红。

    正文从哪来（按优先级，只取一处）：
    1. `proof_text`（`specs/b.py` 规定的"逐字证明摘录"那一栏）；
    2. `statement_full` 且它像一份证明正文（:func:`_looks_like_a_proof`）——
       真机上 B 有时把整段证明写进这一栏；
    3. 都没有 ⇒ `missing=["proof_body"]`：四项读数一项都取不到，档位必须落「判不了」。

    `basis_hint`（`why_this_is_not_trivial`）刻意不参与读数：那是 B 自己写的素材声明，
    把它当证据等于让被评的人自己报分数。它照旧进材料（模型看得到），但不进读数。

    返回的键：`chars` / `steps` / `lemmas` / `lemma_names` / `theorems` / `clusters` /
    `cluster_names` / `cluster_evidence` / `detour` / `detour_words` / `score` /
    `body_chars` / `body_from` / `missing` / `text_truncated` / `truncated_at`。
    """
    primary = str(proof_text or "")
    if primary.strip():
        body, body_from = primary, "proof_text"
    else:
        whole = str(statement_full or "")
        if _looks_like_a_proof(whole):
            body, body_from = whole, "statement_full"
        else:
            body, body_from = "", ""
    out: dict[str, Any] = {
        "chars": 0, "steps": 0, "lemmas": 0, "lemma_names": [], "theorems": 0,
        "clusters": 0, "cluster_names": [], "cluster_evidence": {},
        "detour": False, "detour_words": [], "score": 0,
        "body_chars": len(body), "body_from": body_from,
        "missing": [], "text_truncated": False, "truncated_at": 0,
    }
    if not body.strip():
        out["missing"] = ["proof_body"]
        return out
    # 截断先判：这一趟能读的只有前 PROOF_BODY_CAP 字，读不完就不许给档位
    # （业主口径：档位判不了是因为输入不完整，不是因为材料不足）。
    if len(body) > PROOF_BODY_CAP:
        out["text_truncated"] = True
        out["truncated_at"] = PROOF_BODY_CAP
    seen = body[:PROOF_BODY_CAP]
    steps = 0
    for pattern in _EFFORT_STEP_PATTERNS:
        steps = max(steps, len(pattern.findall(seen)))
    lemmas = sorted(set(_EFFORT_LEMMA_RE.findall(seen)))
    theorems = sorted(set(_EFFORT_THEOREM_RE.findall(seen)))
    evidence: dict[str, str] = {}
    for name, words in EFFORT_TOOL_CLUSTERS:
        hit = next((w for w in words if w in seen), "")
        if hit:
            evidence[name] = hit
    detour_words = [w for w in _EFFORT_DETOUR_WORDS if w in seen]
    chars = len(seen)
    score = ((chars // 2000) + (steps // 6) + (len(lemmas) // 2)
             + max(0, len(evidence) - 1) + (1 if detour_words else 0))
    out.update({
        "chars": chars, "steps": steps, "lemmas": len(lemmas),
        "lemma_names": lemmas, "theorems": len(theorems),
        "clusters": len(evidence), "cluster_names": sorted(evidence),
        "cluster_evidence": evidence, "detour": bool(detour_words),
        "detour_words": detour_words[:4], "score": score,
    })
    return out


def effort_tier_label(score: Any) -> str:
    """分数 → 档位名（`0 -> "T0"` …；坏输入 ⇒ 空串）。边界只在这里读一次。"""
    try:
        got = int(score)
    except (TypeError, ValueError):
        return ""
    for low, high, label in EFFORT_TIER_BANDS:
        if low <= got <= high:
            return label
    return ""


def nontriviality_from_effort(readings: Mapping[str, Any]) -> dict[str, Any]:
    """力气读数 → 非平凡性档位（三态：读全了给 0–4；读不到/被截断给 None + 原因）。

    为什么这一层与 :func:`proof_effort_readings` 分开：读数是"文本里数出来的东西"，
    档位是"这些数落在哪一格"。分开之后，判据可以把两者分别打桩（(f) 的反真空：
    读数全 0 ⇒ 体量大的那条必须掉档；读数恒 T3 ⇒ 三行证明必须升档），
    而"打桩之后判据会不会跟着红"正是"这一档到底是不是读数给的"的唯一证明。

    返回 `{"level": int|None, "label": "T0".."T4"|"", "band": 同 label, "score": int,
    "why": 一句话, "missing": [...]}`。三态的第一条：`missing` 非空、或 `text_truncated`
    为真 ⇒ `level` 是 None，`why` 点名缺的是哪一项 —— 不是 0。
    """
    got = dict(readings or {})
    missing = [str(x) for x in (got.get("missing") or [])]
    score = int(got.get("score") or 0)
    base = {"score": score, "missing": missing}
    truncated = bool(got.get("text_truncated"))
    if truncated:
        at = int(got.get("truncated_at") or PROOF_BODY_CAP)
        return {**base, "level": None, "label": "", "band": "",
                "why": (f"这一条正文在 {at} 字处被截断（正文共 "
                        f"{int(got.get('body_chars') or 0)} 字，读的上限是 {at} 字）"
                        "—— 档位判不了是因为输入不完整，不是因为材料不足")}
    if missing:
        names = {"proof_body": "证明正文（体量/步骤/引理/跨度四项都取不到）"}
        lack = "、".join(names.get(m, m) for m in missing)
        return {**base, "level": None, "label": "", "band": "",
                "why": f"判不了：缺的是「{lack}」这一项力气读数 —— "
                       "补上逐字证明正文（proof_text 或 statement_full 里的证明小节）再判"}
    label = effort_tier_label(score)
    if not label:
        return {**base, "level": None, "label": "", "band": "",
                "why": f"判不了：力气分数 {score!r} 落在边界表之外（EFFORT_TIER_BANDS 要改）"}
    detail = (f"力气分数 {score} = 体量 {int(got.get('chars') or 0)} 字/{int(got.get('chars') or 0) // 2000}"
              f" + 步骤 {int(got.get('steps') or 0)}/{int(got.get('steps') or 0) // 6}"
              f" + 引理 {int(got.get('lemmas') or 0)}/{int(got.get('lemmas') or 0) // 2}"
              f" + 工具簇 {int(got.get('clusters') or 0)}/{max(0, int(got.get('clusters') or 0) - 1)}"
              f" + 绕路 {'1' if got.get('detour') else '0'}")
    return {**base, "level": int(label[1:]), "label": label, "band": label,
            "why": f"按力气读数判 {label}（{detail}）"}


def material_truncation(context: Mapping[str, Any]) -> dict[str, Any]:
    """判档位的那段材料会不会被截断 ⇒ `{"truncated", "at", "chars", "cap"}`。

    与 :func:`_judge_material` 用同一个渲染与同一个上限：两处各算一次长度，是这一格
    唯一能自证"我报的截断点就是模型看到的截断点"的办法（读侧不另抄一份口径）。
    """
    body = json.dumps(dict(context), ensure_ascii=False, sort_keys=True, default=str)
    chars = len(body)
    return {"truncated": chars > JUDGE_MATERIAL_CAP, "at": JUDGE_MATERIAL_CAP,
            "chars": chars, "cap": JUDGE_MATERIAL_CAP}


# ---------------------------------------------------------------- 命题同一性的旁支台账


def proposition_verdicts_path(root: str | Path) -> Path:
    """命题同一性判定台账的路径：`out/secretary/proposition_verdicts.jsonl`。"""
    return Path(root).joinpath(*SECRETARY_DIR, PROPOSITION_VERDICT_LEDGER)


def _proposition_verdict_key(statement_full: str) -> str:
    """缓存键：命题正文的 sha256（去首尾空白之后）。

    为什么键是正文而不是（正文 + 标签）：业主口径是"定理描述一致（什么条件推出什么结论），
    就是一个定理" —— 判定的对象是那一段描述，标签只是它的名字。同一条正文换个标签再交
    一次，判定结论不会有别的答案；按（正文 + 标签）做键就会为"改了个名字"再花一次钱。
    标签带来的那点差异由命中缓存之后的重放处理：结论与洗过的定理名一起沿用，读的人从
    `cached` 与 `label` 两格看得见这一次交上来的标签是什么。
    """
    return hashlib.sha256(str(statement_full or "").strip().encode("utf-8")).hexdigest()


def append_proposition_verdict(root: str | Path, *, statement_full: str,
                               verdict: str, canonical_name: str = "",
                               same_as: str = "", route: str = "",
                               label: str = "", condition: str = "",
                               conclusion: str = "", basis: str = "",
                               role: str = "", task_id: str = "") -> dict[str, Any]:
    """追加一行判定读数（append-only；显式 LF，Windows 上不留 CRLF）。

    只记判过的结论（same / different / unknown 都算判过了）：没查成（没缝 / 开关关着 /
    超时 / 坏 JSON）不许缓存 —— 那会把"这一次没查成"变成"以后都别查了"，而缝是可能好起来
    的（与 `_statement_verdicts` 同一条纪律）。

    每行带 `statement_sha256`：读侧按它折叠出"这条正文最后一次判定是什么"，不必去猜行序。
    返回写下去的那一行（调用方拿它进返回值，不另拼一份）。
    """
    path = proposition_verdicts_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {"at": _now_iso(),
           "statement_sha256": _proposition_verdict_key(statement_full),
           "statement_chars": len(str(statement_full or "")),
           "verdict": str(verdict or ""),
           "canonical_name": str(canonical_name or ""),
           "same_as": str(same_as or ""),
           "route": str(route or ""),
           "label": str(label or ""),
           "condition": str(condition or ""),
           "conclusion": str(conclusion or ""),
           "basis": str(basis or ""),
           "role": str(role or ""), "task_id": str(task_id or "")}
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        # `default=str` 与全仓同一口径（`tests/test_json_dumps_has_a_default.py`）。
        handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True, default=str) + "\n")
    return row


def proposition_verdict_of(root: str | Path, statement_full: str) -> dict[str, Any]:
    """这条正文在台账里最后一次判定的结论（没有 ⇒ 空字典）。

    三态：返回空字典 = "没有判定过"（不是"判过不同"）；返回带 `verdict` 的行 = 判过。
    两者在调用方那里处置完全不同（前者要发一次调用，后者不许再花钱），所以这里不折成
    一个默认值。
    """
    path = proposition_verdicts_path(root)
    key = _proposition_verdict_key(statement_full)
    if not path.is_file():
        return {}
    last: dict[str, Any] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, Mapping):
            continue
        if str(row.get("statement_sha256") or "") == key and str(row.get("verdict") or ""):
            last = dict(row)
    return last


# ---------------------------------------------------------------- 证明的路子说明


def proof_routes_of(row: Mapping[str, Any]) -> dict[int, str]:
    """这一行每条证明的一句话路子说明 `{证明号: 说明}`（读侧唯一口径）。

    路子住在证明号上，不在命题的 label 里（业主 2026-10-24：「路线写在证明这一层」）。
    写侧是 `Secretary.record_statement`：标签里被洗掉的"（路线一：…）"这类修饰落到这里，
    与那条证明的 `proof_no` 对齐。没有说明的证明不在字典里（缺省是空串，不是"没交"）。
    """
    raw = row.get(PROOF_ROUTES_KEY)
    out: dict[int, str] = {}
    if not isinstance(raw, Mapping):
        return out
    for key, value in raw.items():
        try:
            no = int(str(key).strip())
        except (TypeError, ValueError):
            continue
        text = str(value or "").strip()
        if no >= 1 and text:
            out[no] = text
    return out


def proof_route_of(row: Mapping[str, Any], proof_no: Any = 1) -> str:
    """某一份证明自己的路子说明（没有 ⇒ 空串）。"""
    return proof_routes_of(row).get(int(proof_no or 0) or 1, "")


def _judge_system(kind: str) -> str:
    """判断类的稳定头（进 `system` 那一位）：契约三句 + 这一类自己的问题。

    契约三句：① 只回一个 JSON 对象；② `decision` 必须取自这一类自己那张词表（`JUDGE_VERDICTS[kind]`；
    词表外的结论一律不采信，见 :meth:`Secretary.judge`）；③ `basis` 写"你凭什么"。为什么把词表写进提示词：
    模型给的自由文本结论无法与台账的 `decision` 栏对齐，而"结论栏里出现第八种写法"正是同一件事两个名字的老毛病。
    ## 为什么它与 :func:`_judge_material` 是两段（2026-10-21 的缓存轴）：这一段只取决于 `kind` —— 同一个
    类别，任何两趟、任何一份材料，它逐字节相同。材料必须留在 user 消息里，缓存照样能在"下一次调用"时命中
    system 那一段；合成一份（改前的 `_judge_prompt`）时稳定头与材料挤在同一个 user 位里，而那个位每问一次都
    变 ⇒ 前缀命中不了（真机：`hit=0/miss=175` 连发两趟）。分开放之后，稳定头第一次就把索引建起来，第二次起 `hit>0`。
    ## 这一行必须按类别取词表（2026-10-14 真机读数）：加 `statement_aesthetic` 那一类时漏改成了按类别取
    —— 仍把 `DECISIONS`（派活那一轴：「可派」/「建议重排」…）写进提示词，而 `judge()` 的校验已经换成按类别
    取。后果在真机上一次就现形：B 的秘书被问"这条命题太平凡吗"，它照提示词答了 `建议不派`，然后被校验层当场
    判"不在 statement_aesthetic 的词表里 ⇒ 不采信"。现在两处都从 :data:`JUDGE_VERDICTS` 取。
    """
    verdicts = JUDGE_VERDICTS.get(kind, DECISIONS)
    head = (f"你是「秘书」的判断面（类别：{kind}）。只回一个 JSON 对象，字段："
            f'decision（**必须逐字取自** {list(verdicts)} —— 这是这一类的词表，'
            "别的类别的词一律不采信）、reason（一句话）、basis（字符串数组，"
            "写清你凭什么，例如 `specs/d.py` 的哪一条或 `tasks` 里的哪一行）。")
    if kind == "duplicate_retry":
        ask = ("问题：同一个 (role, action, input_key) 已经有下面这些终态行。这一次是"
               "正当的重试，还是重复委托？判『可派』= 这次该照派；判『建议不派』= 别重复派。")
    elif kind == "tool_name":
        ask = ("问题：本体写的工具名不在注册表里。要映到下面哪一个候选吗？"
               "判『建议重排』= 映到某一个（在 reason 里写清是哪一个）；"
               "判『建议不派』= 一个都不映（这次不该调工具）。")
    elif kind == "statement_aesthetic":
        # 2026-10-24 业主裁定（逐字）：「"后面哪一步会用到它 / 比已知那条强在哪"这俩和
        # 非平凡度有啥关系？不一定一条定理后面要用，也不一定存在"已知那条"，看证明花的
        # 力气就能判非平凡度」。于是这一格换了判据：从"会不会被用到 / 比已知强在哪"
        # 换成"这份证明花了多大力气"。旧那两问降级成可选说明（可以写，不作判据）。
        #
        # 为什么判据要逐字写出分数表：材料里的 `effort` 那一格是机器数好的四项读数 + 分数
        # （`secretary.proof_effort_readings`），档位是分数落格（`EFFORT_TIER_BANDS`）。
        # 模型这一趟只做"照表落格 + 写清依据"，判断的可复算部分留在机器侧 —— 否则
        # "为什么这一条是 T3"永远只能靠一句自由文本。
        ask = ("问题：本体（B）要把下面这条命题收进 `statements`（定理与证明收录表）。"
               "它落在非平凡性的哪一档（T0 到 T4）？"
               "判据只有一组：这份证明花的力气。材料里 `effort` 那一格就是机器数好的读数，"
               "四项 —— ① 体量（证明正文多少字）；② 步骤（编号步骤行与分节数）；"
               "③ 引理（正文点名了几条不同的引理）；④ 工具簇的跨度（用了几类论证工具，"
               "跨没跨领域）—— 外加一格「绕路」（正文自述避开了熟路）。"
               "分数 = 体量每 2000 字 1 分 + 步骤每 6 步 1 分 + 引理每 2 条 1 分 + 工具簇"
               "每多一簇 1 分 + 绕路 1 分。档位按分数落格：0 到 1 分是 T0（基础定理或"
               "初步结论）、2 到 3 分是 T1（有一定价值的非平凡结论）、4 到 7 分是 T2"
               "（证明方法都平凡但工作量较大）、8 到 15 分是 T3（需要较多的技巧或"
               "跨领域工具）、16 分以上是 T4（天才般的洞察力/极长思维链/偏离主流的构造）。"
               "判『太平凡』只有一个含义：力气小（分数落在 T0 那两档）—— 它不拦收录，"
               "只是把这条判成 T0 并把档位给 0。"
               "判『合格』= 力气读数大得足以不是 T0（在 basis 里把分数与四项读数写出来）。"
               "旧口径已经不作判据：后面哪一步会用到它、它比已知的那一条强在哪，"
               "这两件可写可不写 —— 写了只当说明，没写、答不上来、或者明说没有使用者，"
               "都不影响档位；档位只看力气那一组读数，不许因为它们缺就把档位压低。"
               "判『判不了』只有一个含义：这一趟的力气读数缺项（材料里 `effort.missing` "
               "非空，或 `text_truncated` 为真 —— 输入不完整）—— 判不了时给 null，"
               "并在 reason 里点名缺的是哪一项读数；不许把它写成『材料不足』。"
               "另加两个字段（同一趟判断的第二个输出，不另发调用）："
               "nontriviality（整数 0-4，逐字按上面那张分数表落格；判不了就给 null，"
               "不许拿 0 冒充「没判」；0 是真心气小的那一档）、"
               "nontriviality_basis（一句话：把分数与四项读数写出来，例如 "
               "『分数 7 = 体量 5164 字/2 + 步骤 8/1 + 引理 5/2 + 工具簇 3/2 + 绕路 0』）。")
    elif kind == "proposition_identity":
        ask = (
            "问题：下面这一条命题（条件 ⇒ 结论）与候选表里的每一条，是不是同一个定理？"
            "业主定的准绳逐字是：「定理描述一致（什么条件推出什么结论），就是一个定理」。"
            "所以判据只有一条 —— 条件组与结论组是否一致。四种情形逐条写清："
            "① 同一组条件推出同一组结论 ⇒ 判 same，并在 same_as 里给出候选的 stmt_id；"
            "② 条件是包含关系（一条更强 / 一条更弱）⇒ 判 different，basis 里写明"
            "『条件强弱不同』，不许因为『看起来是同一个主题』就判 same；"
            "③ 结论相同、条件只是同一条件的另一种记号或等价改写（换变量名、换记号、"
            "把『有限群』写成『阶有限的群』这一类）⇒ 仍判 same；"
            "④ 条件或结论有一侧写不清（缺假设、只给了名字、正文被截断）⇒ 判 unknown，"
            "并在 basis 里点名缺的是条件还是结论 —— 读不出就如实给 unknown，不许猜；"
            "候选表为空 ⇒ 判 different（没有可并的对象）。"
            "不参与判定的东西：定理叫什么名字、证明走哪条路线、证明手法、表述风格 ——"
            "这些都不是『条件 ⇒ 结论』的一部分。"
            "另加四个字段（同一趟判断的输出，不另发调用）："
            "canonical_name（把这一条的标签洗成干净的定理名：只留定理名，把"
            "『（路线一：…）』『（自证草稿，待 V 审签）』『独立证明』这类修饰去掉；"
            "两三条写法不同的同一命题要洗成同一个名字）、"
            "route（被洗掉的那句路线/草稿状态，收敛成一句话，作为证明这一层的路线说明；"
            "标签里本来没有路线就填空串）、"
            "condition（一句话：这一条的条件是什么）、"
            "conclusion（一句话：这一条的结论是什么）。"
            "basis 里必须分别对条件与结论各给一句比对（例如『条件：都是有限群 + p 是素数，"
            "一致；结论：都是 Sylow p-子群存在，一致』）—— 不许只给一个总分。")
    else:
        ask = ("问题：这条委托照声明看不合规（或与收件方的角色定位不匹配）。"
               "该重排成什么？判『建议重排』并在 reason 里给出重排后的说法；"
               "判『建议改派』= 换一个收件方更合适；判『建议不派』= 别派这条。")
    return f"{head}\n\n{ask}\n\n"


def _judge_material(context: Mapping[str, Any]) -> str:
    """判断类的可变部分（留在 user 消息里）：这一趟的材料。

    它每问一次都变（命题正文 / 候选表 / 重复行），所以不许进 system ——
    上游前缀缓存要求前缀逐字节相同，把材料写进前缀等于每一问都换一段前缀。
    与 :func:`_judge_system` 合起来逐字节等于改前那条整提示词（判据钉着这一点：
    `tests/test_secretary_system_carries_the_head.py`）。

    ## 2026-10-24：这一格不再静默截断
    改前是 `json.dumps(...)[:4000]`：一条 8375 字的正文在 4000 字处被切断，而材料里
    没有一个字说"被切了"。模型的反应是"证明截断，无法定档"，台账落成 None + basis
    "材料不足" —— 那是把"我们没给它看全"记成了"它给的材料不够"。
    现在两条：上限抬到 :data:`JUDGE_MATERIAL_CAP`；真的超了就在材料尾部写下截断点与
    那两句话（"输入不完整"不是"材料不足"），并由 :func:`material_truncation` 把同一个
    截断点交给结果与台账。两处必须同时成立：只写一句提示而不抬高上限，等于把
    "看不全"写成一句免责声明。
    """
    body = json.dumps(dict(context), ensure_ascii=False, sort_keys=True, default=str)
    total = len(body)
    if total > JUDGE_MATERIAL_CAP:
        note = (f"\n…【材料在 {JUDGE_MATERIAL_CAP} 字处被截断：这一条正文共 {total} 字，"
                f"只给了前 {JUDGE_MATERIAL_CAP} 字。档位判不了时请写「输入被截断」——"
                "这是输入不完整，不是材料不足】\n")
        return f"材料：\n{body[:JUDGE_MATERIAL_CAP]}{note}"
    return f"材料：\n{body}\n"


def _judge_prompt(kind: str, context: Mapping[str, Any]) -> str:
    """判断类的整条提示词（稳定头 + 材料，逐字节等于改前那一版）。

    保留它是为了"把两条消息念成一条"的读者（判据、审计、以及 `_judge_prompt` 的
    既有调用点）：`Secretary.judge` 自己发的是两条（system + user），
    见 :func:`_judge_system` / :func:`_judge_material`。
    """
    return _judge_system(kind) + _judge_material(context)


def for_role(role: str, *, root: str | Path, **kw: Any) -> Secretary:
    """造一名某角色的秘书（`draft/53` §5 的"批量给 A–H 装"：批量 = 配置 + 测试）。

    装配点只有两个：`agent_loop.run_role`（所有角色共用的驱动，经
    `agent_loop._secretary_for`）与 `conductor.Conductor`（M 的派活路径）——
    两者都不在 FC-27 名册。生产路径会传 `seam=<本角色自己的 LlmSeam>` 与
    `enable_model=True`（主控裁定 A5），于是三条判断真的发生、花销记在本体账上。
    """
    return Secretary(str(role), root=Path(str(root)), **kw)


def _now_iso() -> str:
    return _dt.datetime.now().astimezone().replace(microsecond=0).isoformat()


def _older_than(stamp: Any, now: str, window_sec: int) -> bool:
    """`stamp` 比 `now` 早了超过 `window_sec` 秒吗（"够久了还没核"的判据）。

    三个"不知道"都回 `False`（不列，而不是"列成待核"）：没有时间戳 / 解析不了 /
    时钟反了。理由：待核队列一旦把"判不了"也列进去，它就会变成"什么都往里塞"的
    假阳性来源（主控点名的那条负控）。
    """
    raw = str(stamp or "").strip()
    if not raw:
        return False
    try:
        then = _dt.datetime.fromisoformat(raw)
        reference = _dt.datetime.fromisoformat(str(now))
    except ValueError:
        return False
    try:
        return (reference - then).total_seconds() > float(window_sec)
    except (TypeError, ValueError):
        return False


def selftest() -> int:
    """最小自检：台账分角色、手稿增改查、fail-open 与"执笔失败必须报错"。"""
    import tempfile

    root = Path(tempfile.mkdtemp(prefix="secretary_selftest_"))
    checks: list[tuple[str, bool]] = []
    s = Secretary("D", root=root)
    rec = s.handoff_add(to="F", summary="把猜想交给你", body="证明它。")
    checks.append(("执笔的 sender 是被服务的角色", rec.get("sender") == "D"))
    rev = s.handoff_revise(mid=rec["id"], summary="交接（订正）", body="证明它（第二版）。",
                           reason="引错了一处")
    checks.append(("旧行还在", MS.row_of(root, rec["id"]) is not None))
    checks.append(("订正指回旧行", (MS.row_of(root, rev["id"]) or {}).get("revises") == rec["id"]))
    checks.append(("查得到订正", [r["id"] for r in s.handoff_query(revises=rec["id"])] == [rev["id"]]))
    checks.append(("台账分角色", decisions_path(root, "D").is_file()
                   and not decisions_path(root, "M").exists()))
    # S1m：分片之后"台账分角色"这一条要按两种落点都认（老文件 / 实例分片），
    # 并且保留一条"老文件仍可读"的反负控 —— 否则分片会悄悄改掉历史工作区的读侧口径。
    shard = Secretary("E", root=root)
    shard.bind_task("t-0007")
    shard.note_decision(duty=1, kind=KIND_OPTIMIZED, decision="已优化", reason="自检：分片写入")
    checks.append(("台账按实例分片", shard.decisions_path().is_file()
                   and shard.decisions_path().name == "E-t-0007.jsonl"))
    checks.append(("分片读得回来（且老文件仍可读）",
                   len(shard.decisions()) == 1
                   and str(shard.decisions()[0].get("task_id")) == "t-0007"
                   and decisions_path(root, "E").exists() is False))
    checks.append(("存活读数三态", shard.secretary_alive().get("checked") is True
                   and shard.secretary_alive().get("alive") is True
                   and shard.close().get("closed") is True
                   and shard.secretary_alive().get("alive") is False))
    loud = False
    try:
        s.handoff_add(to="F", summary="", body="")
    except ValueError:
        loud = True
    checks.append(("执笔失败必须报错（不静默放行）", loud))
    checks.append(("写集恒为 ∅", s.writes == frozenset()))
    for name, good in checks:
        print(f"  [{'PASS' if good else 'FAIL'}] {name}")
    return 0 if all(g for _, g in checks) else 1


def reach_fit(role: str, action: str) -> dict[str, Any]:
    """这件活由被派的人（连同它出边上的子代理们）合起来做不做得成（纯计算，只报不改）。

    业主 2026-10-14：「秘书侧……评估派发出的任务能否由子代理及子代理的出边共同完成」。`surface_fit` 判的是
    路径面，这一条判的是能力面：那个动作，被派人自己有没有？没有的话，它出边上的伙伴（再由伙伴的出边……直到
    `policy.max_depth`）里有谁有？走哪几跳？四档（与三态纪律同形，`unknown` 不许折成"做得到"）：
    | `verdict` | 意思 |
    |---|---|
    | `in_self` | 被派人自己的动作表里就有这一件（一跳都不用） |
    | `via_edges` | 要靠出边上的伙伴：`hops` 给出那条链（含每一跳的 role） |
    | `unreachable` | 它那一支闭包里没有任何人有这一件 ⇒ 「面内做不成」，该改派或走上报那一档 |
    | `unknown` | 角色或动作名认不出（`capabilities` 里没有）⇒ 判不了 |
    为什么按"闭包"而不是按"角色"="能做什么"的静态印象：真机形态是二层、三层地派（M→B→H 这种）—— 子代理
    自己拿不到某件工具，但它的伙伴拿得到，而那正是"派得出去"与"派不出去"的分界。旧口径只看被派人自己的动作
    表，于是「B 要把引文交给 H 判语义」会被读成"面内做不成"，而它其实是走得通的（`B → H` 那条边 +
    `H.judge_quote_semantics`）。与 `surface_fit` 的分工：这一条判"谁能做"，`surface_fit` 判"在哪做"（路径落点）。
    """
    from . import capabilities as C
    from . import policy as P

    who = str(role or "").strip()
    want = str(action or "").strip()
    out: dict[str, Any] = {"checked": False, "verdict": "unknown", "hops": [],
                           "reason": ""}
    roles = set(C.CAPABILITIES)
    if who not in roles:
        out["reason"] = f"角色 {who!r} 不在能力表里（{sorted(roles)}）⇒ 判不了"
        out["checked"] = True
        return out
    if want == "":
        out["reason"] = "没给动作名 ⇒ 判不了这一维（不适用不是通过）"
        out["checked"] = True
        return out
    known = {a.action for acts in C.CAPABILITIES.values() for a in acts}
    if want not in known:
        out["reason"] = f"动作 {want!r} 不在任何角色的动作表里 ⇒ 判不了"
        out["checked"] = True
        return out

    def _has(r: str) -> bool:
        return any(a.action == want for a in C.CAPABILITIES.get(r, ()))

    if _has(who):
        out.update({"checked": True, "verdict": "in_self", "hops": [who],
                    "reason": f"{who} 自己的动作表里就有 {want}"})
        return out

    # BFS：一层一层看出边上的伙伴（闭包），并把最短那条链记下来。
    # 深度上限取策略本体的默认值（唯一来源：`policy.Policy`），不从调用方另带一份。
    depth_cap = int(getattr(P.Policy(), "max_depth", 5) or 5)
    seen = {who}
    frontier: list[tuple[str, list[str]]] = [(who, [who])]
    for _step in range(max(0, depth_cap - 1)):
        nxt: list[tuple[str, list[str]]] = []
        for node, path in frontier:
            for peer in sorted(C.ALLOWED_EDGES.get(node, ())):
                if peer in seen:
                    continue
                seen.add(peer)
                chain = path + [peer]
                if _has(peer):
                    out.update({"checked": True, "verdict": "via_edges", "hops": chain,
                                "reason": (f"{who} 自己没有 {want}，但出边上的 "
                                           f"{' → '.join(chain[1:])} 有（"
                                           f"{len(chain) - 1} 跳）")})
                    return out
                nxt.append((peer, chain))
        frontier = nxt
        if not frontier:
            break
    out.update({"checked": True, "verdict": "unreachable", "hops": sorted(seen),
                "reason": (f"{who} 那一支（{'、'.join(sorted(seen))}）里没有任何角色有 "
                           f"{want} ⇒ 这一件在它的面内做不成：改派给有它的那一支，"
                           "或如实记成「职责之外」那一边")})
    return out


if __name__ == "__main__":  # pragma: no cover - 自检入口
    raise SystemExit(selftest())

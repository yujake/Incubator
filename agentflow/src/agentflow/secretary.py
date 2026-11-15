# -*- coding: utf-8 -*-
"""「秘书」：每个智能体自带的随员。
它不是一个同级角色：不占 `schema.ROLES`、不加注册工具、不改权限面声明、不改 `llmseam` 的
enum、不重冻快照 ⇒ 一个计数都不变。同一个类，每角色一份配置（自己的定位 + 收发箱）。
## 四条职责
| # | 职责 | 谁的秘书做 | 本模块的落点 |
|---|---|---|---|
| 1 | 格式与内容优化 | 发件方 | :meth:`Secretary.optimize_outbound`（对齐参数表/必填/工具真名；不替本体承诺） |
| 2 | 委派评估 | 发件方 | :meth:`Secretary.assess_delegation`（收件方真做得到吗 + 该不该派） |
| 4 | 委托加工 | 收件方 | :meth:`Secretary.rework_inbound`（按本角色定位改说法，不加码不减码） |
| 3 | 闭环提醒 | 收件方 | :meth:`Secretary.remind_closure`（未接手 / 未反馈；经 M） |
职责 1 另有一件同样是"看"的事（「秘书处理将发出的信息时，要看内容是否
与接受面相符」）：:meth:`Secretary.judge_recipient_face` —— 公告栏里点名并下指令、或一份稿子里
装了多件派活 ⇒ 这一条退回本体，一个字节都不写盘（判据机械可判、零模型调用）。
两条实质性红线：格式补不全、或加工后发现实质缺陷 ⇒ 与对方协商、不静默修
（:meth:`Secretary.negotiate` ≤2 轮 + 台账留痕）—— 它从不替本体表态。手稿通道的增/改/查也在
这里：`handoff_add` / `handoff_revise` / `handoff_query`，智能体侧只留"查"。
## 权限与失败姿态
库表只读（写集 ∅）；文件两处写：手稿通道 + 自己的台账 `out/secretary/<role>.jsonl`；不使用注册
工具；信息面 ≤ 本体，且 V 的秘书不读 F 的叙述（I12 的独立性不许被绕过）。fail-open：超时/出错
⇒ 原样放行 + 留痕，唯一例外是手稿执笔失败必须报错留痕。它是判断者不是仪表盘：不做任何统计
（那套统计是坏设计），成本靠 :meth:`Secretary.should_engage` 的机器预筛控制
（只在预筛报警 / 重复候选 / 闭环逾期 / 首次遇见该形态时才叫秘书；默认路径确定性）。
"""
from __future__ import annotations

import datetime as _dt
import functools
import hashlib
import json
import re
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from . import manuscripts as MS
from . import clock
from . import proofloc as _PL
from . import propositionkey as _PK
from . import refusals as R
from . import schema as S
from . import statementbody as _SB
from . import statementledger as SL
from . import proofregistry as _PR

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

#: 非平凡性的五档（T0–T4）：它回答"多不平凡"，同时是判档那一问的词表
#: （`STATEMENT_VERDICTS` 从它派生）—— 一根轴，不是两根。
#:
#: T0 不是"次品档"、不是"未评级"，它是同一根轴上的第一档：
#: 平凡但真的那些（`a+b=b+a` 那一类，以及由数值实验直接穷举出来的基础事实）落在 T0，
#: 而它们"能进表"这件事由 T0 这一档保证。
#:
#: | 档 | 语义 |
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
#: `0` 是 T0（真的档位），不能再用它表示"没人判过"—— 两个意思折进同一个值，
#: 读的人会把"没人判过"读成"基础定理"。所以这一档是 `None`（JSON 里是 null）。
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

def _nontriviality_level(value: Any) -> int | None:
    """把模型给的档位收敛到 `0|1|2|3|4`；别的（含缺省）一律 `None` = 判不了。

    2026-10-23 起 `0` 是一档真的档位（T0 基础定理或初步结论），所以"判不了"必须
    换一个值：`None`。这里刻意不把坏输入折成 0 —— 那会把"模型给了 `1.9`"读成
    "这是一条基础定理"，正是"静默降级"的形态。同理也不许折成 1。

    只认整数（或纯数字字符串）：`1.9` 不是"第 1 档"，它是坏输入。

    2026-11-01：`nontriviality_label` 与 `STATEMENT_VERDICTS` 在 import 期就要用它
    （词表从档位轴派生），所以它住在档位常量旁边、必须定义在它们之前。
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        got: Any = value
    elif isinstance(value, str):
        raw = value.strip()
        upper = raw.upper()
        if upper.startswith("T") and upper[1:].isdigit():
            # 2026-10-29：判档那一问的 decision 词表就是 T0..T4，这里原先只认数字
            # ⇒ 模型答 "T3" 永远解析成 None（"交给模型判"在结构上走不通）。
            got = int(upper[1:])
        elif raw.isdigit():
            got = int(raw)
        else:
            return None
    else:
        return None
    return got if got in NONTRIVIALITY_LEVELS else None


#: 档位的显示名（`0 -> "T0"`）。读侧一律调 :func:`nontriviality_label`，不各写一份。
_NONTRIVIALITY_LABELS: dict[int, str] = {level: f"T{level}" for level in NONTRIVIALITY_LEVELS}


def nontriviality_label(level: Any) -> str:
    """档位号 → 显示名（`0 -> "T0"` … `4 -> "T4"`；判不了 ⇒ 空串）。"""
    got = _nontriviality_level(level)
    return _NONTRIVIALITY_LABELS.get(got, "") if got is not None else ""


#: 判档那一问的结论词表（业主 2026-11-01 裁定：审美轴三格退场，直接只用 T0 到 T4）。
#:
#: 2026-11-01 之前这里是 `("合格", "太平凡", "判不了")`：一根"收不收"的审美轴，与
#: `NONTRIVIALITY_LEVELS`（"多不平凡"）并排。裁定之后这一问只剩一根轴 —— `decision`
#: 就是档位，三个旧词退场。从档位轴派生（不写第二份字面量）：两张表漂了，就会出现
#: "词表里有 T5、档位轴没有"这种只在提示词里成立的档位。
#:
#: ## 两态（2026-11-01 第二刀：判不了退场为"没查成"）
#: | 结局 | 盘上那一格 |
#: |---|---|
#: | 有档 | `decision` = `"T0"`…`"T4"`（决定台账同值；档位台账 `nontriviality` 0..4 + `label`） |
#: | 没查成 | `judge.checked=false`；决定台账 `decision="没查成"`；没有档位行 |
#:
#: "判不了"不是一种判定结果，是"我们没拿到判定"（模型给 null / 旧词 / 坏 JSON，
#: 调用失败，正文被截断，一项力气读数都取不到）—— 它的处置是"重试 / 重交 / 人看"，
#: 所以它必须长成"没查成"，而不是第四档，也不是一条 `nontriviality: null` 的行。
#:
#: 概念 / 定义行另有一态 `not_applicable`（见 :meth:`Secretary.not_applicable_nontriviality`）：
#: 那是"这一问对它不成立"，不是"没查成"，两回事，不许折平。
#:
#: ## 旧行怎么读（只影响读旧台账；写侧与新行一个字都不产生这三个词）
#: | 老 `decision` | 折算出的档位 | 判据 |
#: |---|---|---|
#: | `T0`…`T4` | 同名档位 | 老台账里的同名档位 |
#: | `太平凡` | T0 | 这个结论只剩"力气小 ⇒ 落 T0"这一层意思 |
#: | `合格` | 读 `judge.nontriviality`（或同号 `nontriviality.jsonl` 那一行）；都没有 ⇒ 未判 | 它当年只表示"收"，从不携带档位 |
#: | `判不了` | 未判（`None`） | 它是"该判而没判"，不是一档 |
#:
#: 唯一实现是 :func:`_tier_from_legacy_decision`（读旧行的唯一折算口）。判据
#: `tests/test_the_statement_vocabulary_is_only_the_five_tiers.py` 钉着"旧词只许出现在它里面"。
STATEMENT_VERDICTS: tuple[str, ...] = tuple(
    nontriviality_label(level) for level in NONTRIVIALITY_LEVELS)


#: 没有"证明正文"这一档、因而不做力气判档的那几档 kind（"不适用"的适用范围，唯一一处）。
#:
#: 为什么它与 :data:`CONCEPT_IDENTITY_KINDS` 分开住：那一格管"同一性按定义项
#: 判"（只有 `concept` 一档 —— `definition` 行的标签常常是空的，拿它当键会把一堆不相关的
#: 定义并到同一行），这一格管"有没有证明正文可判"（概念与定义都没有）。两件事折成一张表
#: 会让"并错了"与"判错了"互相牵制，而它们的处置完全不同：前者是多一行还是少一行，
#: 后者是多一档读数还是少一档读数。
NOT_APPLICABLE_KINDS: tuple[str, ...] = ("concept", "definition")

#: "不适用"那一格的理由（写进台账的 `basis`，也是页面上那句说明的出处，唯一一处）。
#:
#: 概念行的非平凡度不是"未判"，是"不适用（无证明）"。
#: 前者说的是"该判而没判"，后者说的是"这一问对它不成立"—— 两个词不许折平。
NONTRIVIALITY_NOT_APPLICABLE_BASIS = "不适用：概念行没有证明正文，不做力气判档"


def _is_not_applicable_kind(kind: Any) -> bool:
    """这个 kind 有没有"证明正文"这一档（概念/定义都没有 ⇒ 判档这一格不适用）。"""
    return str(kind or "").strip().lower() in NOT_APPLICABLE_KINDS


def _is_trivial_verdict(decision: Any) -> bool:
    """这一次判断的档位是不是 T0（唯一口径；不认旧词）。

    为什么要单独一个函数：T0 这一档有两个后果（落 T0 + 不在入库口拒收），两处必须问
    同一个问题。而这一条是"把'懂平凡'这一档打桩"的注射点 —— 判据要把"恒判平凡"
    打进去看非平凡那一支会不会红，就得有一个名字。

    只认档位（`"T0"` / `0` / `"0"`）。旧词到档位的折算只在读旧行时做
    （:func:`_tier_from_legacy_decision`）。
    """
    return _nontriviality_level(decision) == 0

#: 「这一条与在册的哪一条是同一条命题」的结论词表（两档）。
#:
#: 准绳：「定理描述一致（什么条件推出什么结论），就是一个定理」。这一问不许有第三种
#: 结论 —— 读不清就是没判成，不是一种判词。
#:
#: 所以这一问只有两个结论：同一组条件推出同一组结论（same）/ 不是（different）。
#: 「没有第三种结论词」：读不清（缺条件 / 结论写不清 / same 点不出候选号 / 词表外结论 /
#: 超时 / 坏 JSON / 没缝）不是一种判定，而是「没判成」 —— `checked=False`，上层按 fail-closed
#: 处置（不新建、不合并、受控拒）。"没判成"与"判过了、不同"必须在盘上分得开：
#: 前者是 `checked=False`，后者是 `checked=True` + `verdict="different"`。
PROPOSITION_VERDICTS: tuple[str, ...] = ("same", "different")

#: 命题同一性判定的旁支台账（append-only）：一行一次判定，键是命题正文的 sha256。
#:
#: 为什么按正文 sha 缓存而不是按本次登记：同一段正文被交上来第二遍（改个标签、换个人重交、
#: 重试）时，判定不会有别的结论 —— 而每一次都要真发一次模型调用。没有这一层，
#: "同一条定理交了三遍"就是三笔钱买同一句话。
PROPOSITION_VERDICT_LEDGER = "proposition_verdicts.jsonl"

#: 一次判定一页给几条候选（分页的页大小，不是截断）。
#:
#: 候选是秘书自己按关键词在台账里检索出来的命中项（查口的 `by_keywords`，
#: 唯一实现在 `statementledger`）；
#: 命中多于这个数时按页依次交给模型，问到命中或页尽为止（只把前 4 条交给模型会让
#: 第 5–N 条永不入眼，却被记成"这批都不是"）。
#: `pages_total` / `pages_judged` / `page_exhausted` / `candidates_total` 四个读数
#: 把"看了几页 / 几个候选 / 是不是页尽"与判词一起摆出来。
#: 为什么一页是 4：一次判定要在提示词里同时放下这一条的正文与每条候选的正文/定理名；
#: 候选越多，每条能分到的字数越少 —— 而对"条件与结论是否一致"这件事，半条命题没有用。
PROPOSITION_VERDICT_CANDIDATES = 4

#: 一次判定里这一条正文最多看多少字符（每条候选各自也有同样的上限）。
PROPOSITION_VERDICT_TEXT_CHARS = 1200

#: 证明的"路子"说明住在哪：行 JSON 里一个 `{证明号: 一句话}` 的字典。
#:
#: 路线写在证明这一层。它不能待在命题的 label 里 ——
#: 那条 label 是定理名（`Sylow 三定理`），带"（路线一：…）"之后，同一条定理的三种证法
#: 就成了三条不同的命题。所以：
#: 定理名归 label，路子归证明号（这一格），依赖的路径分组归 `Dependency.path_group`。
#: 键是证明号的字符串形式（JSON 的键只能是字符串），读侧一律走 :func:`proof_route_of`。
PROOF_ROUTES_KEY = "_proof_routes"

#: V 的回复有没有指出缺陷（两档）。
#:
#: 为什么另立一张表而不复用 `STATEMENT_VERDICTS`（`合格` / `太平凡` / `判不了`）：
#: 那是 B 的审美轴（这条命题够不够格入库），这里是 V 的结论轴（这段审阅回复
#: 到底有没有指出缺陷）。两根轴共用一张词表之后，"太平凡"会被当成一种"有缺陷"——
#: 而它们在台账上是两件事（前者不改任何签，后者清零连续次数）。
#:
#: 这一根轴的词表只有两格：「不可能有判不了。只要不是完全没毛病都叫有毛病」。
#: 拿不准、只挑出一处小记号问题、说"我没逐行验证"——统统算「有缺陷要指出」。
#: 模型若答词表外的值，`judge()` 判它"不在词表里 ⇒ 不采信" ⇒ `checked=False`
#: （"没查成"，见 :meth:`Secretary.judge_v_reply`），不会被当成第三种结论，也不会在
#: 台账上留下一个 `判不了` 的判词。
#: 老台账行上那个轴名也不再是一格：`verifications.SECRETARY_JUDGE_HISTORICAL_AXES` 与
#: `secretary_axis` 的兼容支都没有了，老行上那个值读出来是空轴（"这一行没有轴"）。
V_REPLY_CLEAN = "没问题"
V_REPLY_FAULT = "有缺陷要指出"

#: `v_reply_defect` 那一类的词表（两格，顺序 = 由"没问题"到"有缺陷要指出"）。
V_REPLY_VERDICTS: tuple[str, ...] = (V_REPLY_CLEAN, V_REPLY_FAULT)

#: 词表取值 ⇒ 台账上那条轴的两档（与 `verifications.SECRETARY_JUDGE_AXES` 逐字同一套）。
#: 为什么要有这一张映射而不是直接把中文写进台账：台账那一格是给代码读的
#: （`verifications._hold_run_lengths` 按 `fault` 分流），中文词表是给模型读的。
#: 两者之间只有这一处翻译，改词不改轴；这张映射里没有第三条出路 ——
#: "拿不准"落在 `V_REPLY_FAULT` 那一格（业主逐字：只要不是完全没毛病都叫有毛病）。
V_REPLY_AXIS: dict[str, str] = {V_REPLY_CLEAN: "clean", V_REPLY_FAULT: "fault"}

#: `v_reply_defect` 的第三格：缺陷类别。
#:
#: 轴仍然只有 `clean` / `fault` 两档（`V_REPLY_AXIS` 不动）；这一格回答"判 fault 时，
#: fault 的内容是哪一类" —— 词表本体只有一处（`verifications.FAULT_KINDS`），这里不抄。
#: 为什么由秘书这一问给、不给 V 加必填字段：只走"秘书语义判 `defect_kind` ＋ 写侧护栏"
#: 这一条路；给 V 加必填字段等于把句式要求换个地方钉。
V_REPLY_DEFECT_KIND_FIELD = "defect_kind"

#: 秘书这一问的"报告质量读数"那一格：判「没问题」时可以顺带记一句
#: "这份报告缺了什么记录"（例：没写反例尝试的位置）。它不是判据、不进 fault 轴，
#: 也不挡签；写侧把它原样落进 `secretary_judge.report_gap`，读侧只作质量读数。
V_REPLY_REPORT_GAP_FIELD = "report_gap"


def v_reply_fault_reading(*, decision: str, defect_kind: Any = "",
                          report_gap: Any = "", reason: Any = "") -> dict[str, Any]:
    """把 `v_reply_defect` 那一问的答案读成 `(axis, fault_kind, fault_cause, report_gap)`。

    这是写侧分类的第一半（纯函数，零 IO、不碰模型）：秘书那一问的
    `decision` / `defect_kind` / `report_gap` 三格 + 它自己的 `reason`，在这里翻译成
    台账 `secretary_judge` 格里要落的那几个键。第二半（写行处的护栏与兜底）在
    `agent_v/core.py` 的 `_write_fault_cell`：那里才拿得到 findings / defect_step。

    判据（与 D3 §3.1 / §5.3 逐条对得上）：

    1. `decision` 不在两档词表里（`判不了` / 空 / 别的写法）⇒ `axis=""`：那不是一种
       结论（"没有判不了"这条纪律），四个类别格全部留空，由调用方按"没查成"处置。
    2. `decision=没问题` ⇒ `axis="clean"`、`kind=""`；`report_gap` 非空时
       `cause="report_gap"`（报告质量读数，不影响投票）。模型若同时给了 `defect_kind`
       ⇒ 不采信（clean 行带 kind 是自相矛盾行；`is_a_vote` 会 fail-closed 把它吞掉，
       所以归一必须在写侧做 —— D3 §5.3）。
    3. `decision=有缺陷要指出` ⇒ `axis="fault"`，`kind` 只认
       `verifications.FAULT_KINDS` 里的四类；不认识的写法一律留空（写行处按 `math`
       兜底 —— 缺 kind 的新行不许静默解锁，D3 §5.3）。
    4. `defect_kind="report_gap"`（模型把"只缺反例尝试记录"写进这一格）⇒ 归到
       `kind=""`、`cause="report_gap"`：它不是缺陷。`axis` 这里仍是 `fault`，
       由写行处（拿到 findings / defect_step 之后）决定要不要翻成 clean ——
       只有"没有数学证据"时才翻（护栏只许往更严的方向折）。
    5. `kind="procedural"` ⇒ `cause="self_declared"`（V 自己说没逐行验证）；
       其余类别 `cause=""`。

    返回键固定四个，每一行都写：`fault_kind` 可以为空串、
    `fault_cause` 可以为空串，但键必须在 —— 键在不在是"新行 / 老行"的唯一分界
    （`verifications.fault_kind_of` 读的就是它）。
    """
    out: dict[str, Any] = {
        "axis": "", "fault_kind": "", "fault_cause": "", "report_gap": "",
    }
    gap = str(report_gap or "").strip()
    kind = str(defect_kind or "").strip()
    axis = V_REPLY_AXIS.get(str(decision or "").strip(), "")
    if axis == "clean":
        out.update(axis="clean", fault_kind="",
                   fault_cause=("report_gap" if gap else ""), report_gap=gap)
        return out
    if axis != "fault":
        # 词表外（`判不了` / 空串 / 历史写法）：不是一种结论 ⇒ 没有轴、没有类别。
        return out
    if kind == "report_gap":
        # 模型把"只缺反例尝试记录"写进 kind（批 1 的旧写法）：按裁定 ① 归到 cause。
        out.update(axis="fault", fault_kind="", fault_cause="report_gap",
                   report_gap=(gap or str(reason or "").strip()))
        return out
    from . import verifications as _VR   # 惰性：词表本体只有一处（`FAULT_KINDS`）

    if kind not in _VR.FAULT_KINDS:
        # 不认识的写法 / 没给：kind 留空，写行处按 math 兜底（缺 kind 的新行不许静默解锁）。
        kind = ""
    cause = "self_declared" if kind == "procedural" else ""
    out.update(axis="fault", fault_kind=kind, fault_cause=cause, report_gap=gap)
    return out


#: V 的秘书「发不发这一签」。
#:
#: 两档：`签发` / `不签发`。第三个词「判不了」不是一种
#: 决定：读数不全 / 没答上来 ⇒ `checked=False` + 理由（"没查成"由那两格说，不由
#: `decision` 冒充成第三档）。
SIGN_ISSUE = "签发"
SIGN_WITHHOLD = "不签发"

#: `sign_issuance` 那一类的词表（两档）。
SIGN_ISSUANCE_VERDICTS: tuple[str, ...] = (SIGN_ISSUE, SIGN_WITHHOLD)

#: 判定"没查成"时，台账那一行的 `decision` 该写什么。
#:
#: 「没查成」不是一种判定 ⇒ 台账上也不许写成一个结论词。这一格因此用
#: `没查成` 这个专用词：它不在任何一张 `JUDGE_VERDICTS` 里，读的人一眼看得出"这一趟没有
#: 结论"，不会把它当成某一档（也不给"判不了"留位置）。
JUDGE_UNCHECKED = "没查成"

#: 判断类别 → 它允许的结论词表（唯一一处把"哪类判断有哪些结论"写下来的地方）。
#:
#: 加一类判断时只加一行：`Secretary.JUDGE_KINDS` 与 `judge()` 的校验都从这张表派生，
#: 于是"新类别悄悄用了别的轴的词"这件事在结构上就发生不了。
#: 同种证明的判定词表（二态、语义；判不了走 `checked=False`，不设第三档）。
#: 定义必须早于 `JUDGE_VERDICTS`（那张表在模块加载期就取它）。
PROOF_KIND_VERDICTS: tuple[str, ...] = ("same", "different")

#: 「这一条派给 F 的活，是不是一个研究方向」那一轴的词表（两态、语义）。
#:
#: 业主 2026-11-13 的裁定（本批 R1/R2）：「plan由F自己决定，所以D不可能做出按plan个数派F，
#: 于是D只能按研究方向开多个F而非把一堆方向委托给一个F」——D 的秘书要审这一件事，
#: 不合适时给提醒（不是拒收）。两档：
#:   `是一个方向`   —— 这一条交给 F 的是一件事（要弄清什么、可试哪条路），一个 F 接得住；
#:   `不是一个方向` —— 一条派活里捆了多个互不相干的研究方向（该按方向拆成多个 F），
#:                    或者它其实是一张"计划列表 / 进度督办"（plan 由 F 自己决定，
#:                    派活不该点名它们）。
#: 判不了 ⇒ `checked=False`（不设第三档：第三档会被读成一个结论词）。
#:
#: 为什么不用「合适 / 不合适」：`_judge_system` 的泄漏判据是子串判的
#: （`test_the_head_is_the_one_of_that_kind_not_a_placeholder`：别的轴的词不许整张混进
#: 这一类的题面），而「合适」是「更合适」的子串（派活轴 rearrange 那一问里就有
#: "换一个收件方更合适"）⇒ 一加就会把那一问判红。这两个词是这一问自己的说法，
#: 不与任何别的轴共用字串。
DISPATCH_FIT_OK = "是一个方向"
DISPATCH_FIT_UNSUITABLE = "不是一个方向"
DISPATCH_FIT_VERDICTS: tuple[str, ...] = (DISPATCH_FIT_OK, DISPATCH_FIT_UNSUITABLE)

JUDGE_VERDICTS: dict[str, tuple[str, ...]] = {
    "duplicate_retry": DECISIONS,
    "tool_name": DECISIONS,
    "rearrange": DECISIONS,
    "statement_aesthetic": STATEMENT_VERDICTS,
    # 命题同一性：结论词表就是二态。
    "proposition_identity": PROPOSITION_VERDICTS,
    # V 的回复有没有指出缺陷。独立一张表，不复用审美轴。
    "v_reply_defect": V_REPLY_VERDICTS,
    # 这一签发不发（发签决定权在 V 的秘书）。
    "sign_issuance": SIGN_ISSUANCE_VERDICTS,
    # 这一份证明与在册各路径是不是同一套证法（二态、语义：对比证明方法，不做任何机械闸）。
    # 不加第三档：判不了走 `checked=False`（fail-closed，调用方不收录）。
    "proof_kind": PROOF_KIND_VERDICTS,
    # 这一条 D 派给 F 的活是不是一个研究方向（二态：合适 / 不合适）。
    # 独立一张表：它不复用派活轴的 `DECISIONS`（"建议重排"是处置，不是"合不合适"）。
    "dispatch_fit": DISPATCH_FIT_VERDICTS,
}

#: `dispatch_fit` 那一问的题面（模块级常量，`_judge_system` 只引用它）。
#:
#: 为什么不住在 `_judge_system` 的函数体里：那一格是软基线
#: `src_functions_gt200_lines` 盯着的函数（业主口径 92 不许抬），二十来行题面塞进函数体
#: 会把它顶过 200 行。题面本身只取决于 `kind`、与材料无关，抽成常量不改变缓存纪律
#: （它照样进 `system` 那一段）。
DISPATCH_FIT_QUESTION: str = (
    "问题：下面这一条是 D 派给 F 的活（材料里的 `task` 是派活原文，"
    "`action` / `params` 是随附的调用面，可能为空）。它是不是**一个研究方向**？\n"
    "判据只有一条：这条派活交给 F 的是**一件事**（要弄清什么、可以试哪条路），"
    "而不是**几件互不相干的事**。\n"
    "几件事（判「不是一个方向」）：\n"
    "- 一条派活里捆了几个不同的研究方向，要一个 F 同时攻几条线；\n"
    "- 它其实是一张**计划列表 / 进度督办**（点名多条计划、多个要证的命题、要求逐个推进），"
    "而 plan 由 F 自己决定 —— D 派活该按研究方向派，不该按计划个数派；\n"
    "- 它把「汇报 / 盯进度」写成了一次攻坚方向（那不是方向，是流程要求）。\n"
    "一件事（判「是一个方向」）：只写方向、约束、可试的路，没有把几个方向捆在一起，"
    "也没有替 F 决定它要开几条计划、先推哪一条。\n"
    "不参与判定的东西：这条方向难不难、值不值得做、F 能不能证出来 —— 那些是研究判断，"
    "不是这一问。\n"
    "读不清（原文被截断、只有编号、没有可读的方向文字）时不要猜：把 decision 留成空串，"
    "框架把它当「没判成」处理（这一条只提醒、不拦派活）。\n"
    "decision 取「是一个方向」/「不是一个方向」之一；reason 一句话；"
    "basis 引派活原文里的字句。"
    "判「不是一个方向」时 reason 必须写清**该拆成几件事、每件事各派一个 F 的话该怎么写**"
    "（这是给 D 的提醒，不是拒收）。"
)

#: 判断"没查成"时，台账那一行的 `decision` 该写什么（按类别）。
#:
#: 为什么需要这张小表：`_record_judge` 的缺省是 `"建议重排"`（派活那一轴的词）——
#: 对这几种判断，`checked=False` 时写"建议重排"是一句假话。这里给它们一个专用词
#: （`没查成`，不是任何一档结论），其余类别原样保留旧缺省：改它们的词会改历史读数。
#: 每一类都得在表里：漏一类，它在没查成时写的就是派活轴的"建议重排"（错轴）。
_JUDGE_UNDECIDED: dict[str, str] = {
    "v_reply_defect": JUDGE_UNCHECKED, "sign_issuance": JUDGE_UNCHECKED,
    "statement_aesthetic": JUDGE_UNCHECKED, "proof_kind": JUDGE_UNCHECKED,
    "dispatch_fit": JUDGE_UNCHECKED,
}


def decisions_path(root: str | Path, role: str, task_id: str = "") -> Path:
    """这一名秘书的决定台账路径。

    - `task_id` 空 ⇒ 老文件 `out/secretary/<role>.jsonl`（每角色一份，绝不混写）：
      历史行仍然在这里，读侧必须继续读得到；
    - `task_id` 给了 ⇒ 分片 `out/secretary/<role>-<task_id>.jsonl`：一实例一片、一个写者一片，于是
      同角色的并发实例（`summon_many` 的多 `instance`）不再往同一个文件里挤。
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


#: 名册写的 per-owner 临界区（业主 2026-11-02 口径②）：进程内一把 `threading.Lock` +
#: 跨进程一把 `FileLock`，按 `(root.resolve(), owner)` 分片。
#:
#: 为什么不复用 `_APPEND_LOCKS`：那把锁按文件名罩"一次追加（取号 + 写一行）"，
#: 罩不住"读三份文件 → 判（名字 / 槽位 / 重号）→ 写两笔"这一整段（`draft/149` §3.2）。
#: 为什么落在 `Secretary` 而不是 `Conductor`：`open_solo_entry`（用户指定单条执行）
#: 不经过 conductor（`agent_loop.py` 直接调秘书），加在 conductor 上会漏掉它。
_ROSTER_LOCKS: dict[str, Any] = {}
_ROSTER_LOCKS_GUARD = threading.Lock()
#: 同线程重入计数（roster_add → surface_alloc 会再要一次同一把锁）。
_ROSTER_DEPTH = threading.local()


@contextmanager
def _roster_section(root: str | Path, owner: str) -> Any:
    """同 `(root, owner)` 的名册写临界区（同线程可重入；跨进程用 `<owner>.jsonl.section.lock`）。

    锁序（必须写死，否则会死锁）：进这里之前先把 `tasks` 那一侧的事做完。`retire` 就是
    这样排的（`settle` 在写名册三笔之前），所以临界区里不再取任何 store 锁 ——
    只可能是 `tasks → roster`，不可能是反向。

    重入为什么必须有：`roster_add` 在临界区里调 `surface_alloc`（名字与槽位必须同一段），
    而 `surface_alloc` 自己也要这把锁；`filelock` 不可重入（`draft/149` A2 实测嵌套会
    超时），所以内层按线程计数直接放行。
    """
    from filelock import FileLock

    key = f"{Path(root).resolve()}::{str(owner or '')}"
    held = getattr(_ROSTER_DEPTH, "held", None)
    if held is None:
        held = {}
        _ROSTER_DEPTH.held = held
    if held.get(key):
        held[key] = int(held[key]) + 1
        try:
            yield
        finally:
            held[key] = int(held[key]) - 1
        return
    with _ROSTER_LOCKS_GUARD:
        lock = _ROSTER_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _ROSTER_LOCKS[key] = lock
    target = roster_path(root, owner)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
    except OSError:  # 目录建不出来时下面 FileLock 会自己报错，不在这里折成"没锁"
        pass
    with lock:
        with FileLock(str(target) + ".section.lock", timeout=30.0):
            held[key] = 1
            try:
                yield
            finally:
                held[key] = 0


def _roster_guarded(func: Any) -> Any:
    """把一次写方法的整段包进 per-owner 临界区（`owner` 从关键字参数取）。

    只给"判据 + 写盘"全在本方法里的那几支用（`roster_add` / `roster_repair` /
    `surface_alloc` / `surface_release`）。`retire` 刻意不用它：它中间有 `store.tx("tasks")`，
    整段包进来会把锁序变成 `roster → tasks`（`draft/149` §3.6 要求反过来）。
    """

    @functools.wraps(func)
    def wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
        owner = str(kwargs.get("owner") or "")
        with _roster_section(self.root, owner):
            return func(self, *args, **kwargs)

    return wrapper


#: 名册登记的「在飞」集合（`draft/159` §三-甲）：按 `(root.resolve(), owner)` 分片，
#: 与 `_ROSTER_LOCKS` 同键同址 —— 两者罩的是同一件事（这个父的名册写）。
#:
#: 语义：一个 `task_id` 从「它那一行要在这一笔 `tasks` 事务里提交」到「它自己的
#: `roster_add` 已经落盘」之间，在这个集合里。`roster_repair` 的 `known` 并上它，
#: 于是「还没登记」不会被读成「没登记」（81 趟 6 条 `repaired=true` 的根因：
#: A 线程写完了台账行、还没登记，B 线程的补登记把 A 当孤儿补了）。
#:
#: 为什么是模块级而不是挂 `Conductor`：`_ROSTER_LOCKS` 是模块级，理由是
#: 「`open_solo_entry` 不经过 conductor」；这一份罩的是同一个面，分片键必须同一份，
#: 否则同一进程里两条 `Conductor` 各拿各的集合，窗口又回来了。
#:
#: 为什么读的时候不需要再加一层锁：写入顺序是 `set.add(tid)` 先于 `tasks` 事务提交，
#: 而 `roster_repair` 先读 `_tasks()`、后读本集合 —— GIL 下「看得见那一行」的读者
#: 之后一定看得见标记。这个读序是判据（`tests/test_sibling_registration_race_is_not_backfilled.py`
#: 的读序负控），不是注释。
_ROSTER_PENDING: dict[str, set[str]] = {}


def _roster_pending_key(root: str | Path, owner: str) -> str:
    """与 `_roster_section` 同一个分片键（`(root.resolve(), owner)`）。"""
    return f"{Path(root).resolve()}::{str(owner or '')}"


def note_roster_pending(root: str | Path, owner: str, task_id: str) -> None:
    """把「这一号的台账行即将提交、名册还没登记」标进在飞集合（幂等）。"""
    tid = str(task_id or "")
    if not tid:
        return
    key = _roster_pending_key(root, owner)
    with _ROSTER_LOCKS_GUARD:
        _ROSTER_PENDING.setdefault(key, set()).add(tid)


def forget_roster_pending(root: str | Path, owner: str, task_id: str) -> None:
    """清掉在飞标记（登记结束/建行失败都走这里；清不掉 = 该号被 repair 永久跳过）。"""
    tid = str(task_id or "")
    if not tid:
        return
    key = _roster_pending_key(root, owner)
    with _ROSTER_LOCKS_GUARD:
        got = _ROSTER_PENDING.get(key)
        if got is None:
            return
        got.discard(tid)
        if not got:
            _ROSTER_PENDING.pop(key, None)


def roster_pending(root: str | Path, owner: str) -> frozenset[str]:
    """这一父名下「正在登记、名册还没落盘」的号（只读；空集时顺手删键）。"""
    key = _roster_pending_key(root, owner)
    with _ROSTER_LOCKS_GUARD:
        return frozenset(_ROSTER_PENDING.get(key) or ())


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
# 落点：`out/roster/<owner>.jsonl`（名册）、`<owner>-index.jsonl`（电话簿）、`<owner>-retired.jsonl`（销号名单）、`refusals/<owner>.jsonl`（拒绝流水，子目录）。四份都 append-only，读侧折叠。
# 为什么不放 `out/secretary/`：`webui/readers.py` 是目录 glob（`*.jsonl`），
# 同目录会把名册行混进"秘书决定台账"那一面。

ROSTER_DIR: tuple[str, ...] = ("out", "roster")


def roster_path(root: str | Path, owner: str) -> Path:
    """名册（`owner` = 父的绝对编码）。"""
    return Path(root).joinpath(*ROSTER_DIR, f"{owner}.jsonl")


def roster_index_path(root: str | Path, owner: str) -> Path:
    """对照表（电话簿）：本地名 → 当前调用行。"""
    return Path(root).joinpath(*ROSTER_DIR, f"{owner}-index.jsonl")


def retired_path(root: str | Path, owner: str) -> Path:
    """销号名单（名字一经退役永久不复用；后续版本的新功能读它）。"""
    return Path(root).joinpath(*ROSTER_DIR, f"{owner}-retired.jsonl")


def refusals_path(root: str | Path, owner: str) -> Path:
    """派活登记被拒的流水（被拒是一次有记录的决定）。

    为什么必须落一条盘上记录：拒绝当时名册三份一个字节都没写（`roster_add` 直接返回），
    跨进程唯一靠得住的证据就是这一刻落下的这条流水。收口兜底（`roster_repair`）读它，
    于是"派活时被拒的号"不会在销号那一刻被补成新名字 —— 而那等于悄悄改写那次拒绝。

    落点：`out/roster/refusals/<父>.jsonl`。放进子目录、而不是像 `-retired.jsonl` 那样
    同目录同后缀，是因为读侧按 `out/roster/*.jsonl` 的目录 glob 认"谁有一份名册"
    （`roster_owners` 与 `webui.readers._roster_files`），同目录新增一种后缀要在两处
    各登记一次；子目录两处都天然看不见（`out/surfaces/archive/` 是同一个做法）。
    """
    return Path(root).joinpath(*ROSTER_DIR, "refusals", f"{owner}.jsonl")


def registration_refusals(root: str | Path, *, owner: str = "") -> dict[str, Any]:
    """名册写口拒过的那些号 —— 只读读数。

    为什么要一个读数面：这条流水（`refusals_path`）从 2026-11-02 起就在盘上，但唯一的读者
    是收口兜底 `Secretary.roster_repair` —— "这一号曾被拒过"在人的读数面上完全不可见。
    "这一号曾被拒过"在人的读数面上必须可见。

    名字为什么叫 `registration_refusals`（而不是 `refusals`）：全仓 `refusals` 一词已有三义
    —— 动作被拒的行（`statusreport` 的 `refusal_reason`）、收工被拒的事件
    （`patrol` 的 `final_refused`）、以及这一份名册写口的拒绝流水。三件事各一个词：
    `action_refusals` / `final_refusals` / `registration_refusals`（前两个的改名与 U-07 同轮）。

    返回 `{"checked", "count", "items", "bad", "owner", "path"}`：
    - `checked=False` ⇒ 这一份流水读不出来（坏行见 `bad`）—— 不是"没人被拒"；
    - `items` 每条 `{task_id, requested_name, refusal_code, problem, at}`（原样透传流水里的格）；
    - `owner` 给空串 ⇒ 读 `out/roster/refusals/` 下全部父的流水（跨父合计）。
    """
    from . import jsonlfile as JF

    base = Path(root).joinpath(*ROSTER_DIR, "refusals")
    paths: list[Path] = []
    if str(owner or ""):
        paths = [refusals_path(root, str(owner))]
    else:
        try:
            paths = sorted(base.glob("*.jsonl"))
        except OSError:
            paths = []
    items: list[dict[str, Any]] = []
    bad: list[str] = []
    checked = True
    for path in paths:
        rows, bad_rows, state = JF.read_jsonl_state(path)
        if state == "unreadable":
            checked = False
            bad.append(f"{path.name} 读不出来（这一格不是「没人被拒」）")
        bad.extend(str(x) for x in bad_rows)
        for row in rows:
            items.append({
                "task_id": str(row.get("task_id") or ""),
                "requested_name": str(row.get("requested_name") or ""),
                "refusal_code": str(row.get("refusal_code") or ""),
                "problem": str(row.get("problem") or ""),
                "at": str(row.get("at") or ""),
            })
    return {"checked": checked and not bad, "count": len(items), "items": items,
            "bad": bad, "owner": str(owner or ""),
            "path": str(paths[0]) if len(paths) == 1 else str(base)}


#: 「真跑过」的终态（`tasks.status` 那一格）。为什么不用 `tokens > 0` 当判据：81 趟实测
#: `t-000073` 真跑了 18 分钟也 `tokens=0`（记账在 `usage_ledger` 那一侧，`tasks.tokens`
#: 回答的是"这一行抄回来多少"，不是"它跑没跑"）。`draft/160` §三-6 的丁案把它列成前提假设之一。
RAN_STATUSES: tuple[str, ...] = ("done", "failed", "cancelled")


def ran_but_unnamed(row: Mapping[str, Any],
                    known: Mapping[str, Any] | set[str] | frozenset[str]) -> bool:
    """这条台账行是不是「真跑过、名册里却没有它」—— 全仓唯一的判据。

    ## 为什么要有这一格（`draft/160` 的问题定义）

    81 趟的 `t-000106`：父点名 `E2`，而 `E2` 已被一个从没跑过的号（`t-000030`，派活闸
    `concurrency_exceeded`）占着 ⇒ 名册写口受控拒绝（`name_taken`），派活照跑、子代理
    真跑完（`done/ok`、有产物），然后两条补名路都关着（`draft/160` 一-c）⇒ 它永久没有
    名字，而盘上没有任何一格读数看得出这件事。

    ## 四个条件，一条都不能少（每一条都对着一个已堵住的洞）

    1. `status ∈ RAN_STATUSES`：跑完了（`done` / `failed` / `cancelled`）。在飞的
       （`pending` / `running`）不算 —— 那是 159 那个"台账行已落、名册还没落"的窗口，
       把它算进来就会把兄弟行报成"无名"（同一族误判，`draft/159` §一）。
    2. `outcome != "refused"`：派活闸拒掉的号不许进这一格。这是 d9ebb7fe / 1cdacbf6
       划的那条界（"没跑过"与"跑过没名"是两件事），也是本格不重开那两个洞的证明。
    3. `ended_at` 非空：与 1 互为兜底 —— 只有真的有过结束时刻才叫跑完。
    4. `task_id ∉ known`：`known` 是那个父名下「名册接过」的全部号（`add` ∪ `bind`，
       与 `Secretary._roster_history` 同一份口径）。有名字的当然不算无名。

    `known` 收 `Mapping` 或集合：前者就是 `_roster_history` 的返回值（号 → 名字），
    后者给只需要"在不在"的读者用（`webui.readers` 那一格）。
    """
    if str(row.get("kind") or ""):
        # 板项行（`message` / `notice`）不是代理：它们没有"跑过"这回事。
        return False
    tid = str(row.get("task_id") or "")
    if not tid or tid in known:
        return False
    if not str(row.get("parent_task_id") or ""):
        # 没有父的绝对编号 ⇒ 不在任何人的名册上，也无从"该有名字"（顶趟就是这样）。
        return False
    if str(row.get("status") or "") not in RAN_STATUSES:
        return False
    if str(row.get("outcome") or "") == "refused":
        return False
    return bool(str(row.get("ended_at") or ""))


def retired_row_gaps(rows: Iterable[Any], owner: str = "") -> tuple[list[str], list[dict[str, Any]]]:
    """销号名单每一行"认不认得出是哪一号 / 哪一名" ⇒ `(逐条说明, 逐条结构化读数)`。

    为什么这一档单列（`draft/145` R8/R10/R11/R18）：`jsonlfile.read_jsonl` 只回答
    "这一行是不是合法 JSON / 是不是对象"，不回答"这一行说的是谁"。于是下面这些都
    读成"这一份里没有它"、进而被叫醒（已销号却仍被叫醒是不可逆的那一边）：

    ```text
    少 task_id（只有名字）      ⇒ 唤醒闸手里只有号 ⇒ 认不出
    task_id 写成 int / name 写成 list ⇒ str(...) 出来的东西永远不等于真键 ⇒ 认不出
    owner 与所在分片不符         ⇒ 归属键自相矛盾（R19 的"张冠李戴"那一半）
    ```

    判据只说两件事（§3.1 注 2）：`task_id` 与 `name` 是不是非空字符串，
    外加 `owner` 与分片名对不对得上。刻意不校验"号看起来像不像 `t-000123`"——
    格式校验会变成第二份发号口径。

    返回第二格给"这一行可能是谁"用（按号 / 按名逐个排除）：`task_id` / `name`
    非空字符串就原样带着，否则空串（= 用不了这个键）。名字那一半要靠调用方去名册里
    换算出"这一号叫什么"才能排除（见 `Conductor._retired_names_of_key`）。
    """
    messages: list[str] = []
    rows_out: list[dict[str, Any]] = []
    for i, row in enumerate(rows or (), 1):
        if not isinstance(row, Mapping):
            # 一行就是一个号 / 一个名字（老 dict 替身、`retired_names = ["t-1"]`）
            if not str(row or "").strip():
                msg = f"第 {i} 行认不出来（空行）"
                messages.append(msg)
                rows_out.append({"line": i, "task_id": "", "name": "", "why": msg})
            continue
        tid = row.get("task_id")
        name = row.get("name")
        use_tid = str(tid).strip() if (isinstance(tid, str) and tid.strip()) else ""
        use_name = str(name).strip() if (isinstance(name, str) and name.strip()) else ""
        why = ""
        if not use_tid:
            why = f"第 {i} 行认不出来（task_id 不是非空字符串：{tid!r}）"
        elif not use_name:
            why = f"第 {i} 行认不出来（name 不是非空字符串：{name!r}）"
        elif owner and str(row.get("owner") or "") not in ("", str(owner)):
            why = (f"第 {i} 行的 owner={row.get('owner')!r} 与分片不符"
                   f"（分片是 {owner!r}）")
        if not why:
            continue
        messages.append(why)
        rows_out.append({"line": i, "task_id": use_tid, "name": use_name, "why": why})
    return messages, rows_out


#: 名册目录里"不是名册正文"的那几种后缀（`<父>-index.jsonl` / `<父>-surfaces.jsonl` /
#: `<父>-retired.jsonl`）。全工作区口径的读数按它排除，而不是按"文件名里有没有横线"猜 ——
#: 父的编号本身不含横线，但靠猜迟早会把一种新后缀算成一份名册。
#: 2026-11-02 的拒绝流水（`refusals/<父>.jsonl`）不在这张表里：它在子目录里，两处
#: `*.jsonl` 的目录 glob（`roster_owners` / `webui.readers._roster_files`）都看不见它。
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
    一项（一个子代理可以接多个任务；名册不按任务号记）。
    """
    items: dict[str, dict[str, Any]] = {}
    for raw in rows:
        r = dict(raw)
        name = str(r.get("name") or "")
        if not name:
            continue
        item = items.setdefault(name, {"name": name, "role": str(r.get("role") or ""),
                                       "brief": "", "brief_source": "", "task_id": "",
                                       "task_text": "", "retired": False})
        kind = str(r.get("kind") or "")
        if str(r.get("role") or ""):
            item["role"] = str(r.get("role") or "")
        if kind == "add":
            item["brief"] = str(r.get("brief") or "")
            # 简介是谁写的（简介没写时秘书帮忙写）：
            # `parent` = 父给的原话；`secretary` = 秘书从任务原文派生的一句；
            # `""` = 这一格缺失的行（不许倒填成"父给的"）。
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
            # 读侧先落地的那一格：今天没有任何生产者（全仓没有一处往名册写
            # `kind="keep_alive"` 的行）。
            # 「做完还待命」这条事实的唯一来源是台账那一侧的派活项（
            # `conductor.keep_alive_of` 读 `kind="delegation"` 行的 `keep_alive`），
            # `_state_reading` 走的正是那一条路。
            # 为什么留着而不是删：它是名册事件的合法一格，删掉之后
            # 将来真要写它的人会在别处再写一份 fold —— 而"同一份事件流的两种折法"正是
            # 本仓栽过的那一类。读数侧的代价为零（这一行永远不会命中）。
            # 反过来说：如果哪天有人开始写它，`keep_alive_of` 与这一格就是两份口径，
            # 那时必须合并成一处 —— 所以这一行在此点名，免得它继续静默。
            item["keep_alive"] = bool(r.get("value"))
        # 任务原文（自动以 task 填充目的）：它是父派下来的那件事
        # 本身，`add` 与 `bind` 两行都可能带着它（复用支只写 bind）。改前落的行没有
        # 这一格 => 空格（不许拿 brief 冒充：brief 是 60 字摘要，不是原文）。
        text = str(r.get("task_text") or "")
        if text:
            item["task_text"] = text
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


#: 名册里保存的任务原文上限（业主 2026-10-27：「自动以 task 填充目的」+「截断到 200 字」）。
TASK_TEXT_MAX: int = 200


def _task_text(task: Any) -> str:
    """任务原文的落盘形态：折平空白 + 截断到 `TASK_TEXT_MAX`。

    与 `brief_from_task` 的差别是口径本身：那一格是"给退役时认人的一句摘要"（60 字、
    取第一句），这一格是"父派下来的那件事"（原文，200 字）。两件不许互相顶替 ——
    把摘要当原文会让"等它的目的"读起来像另一件事。
    """
    flat = " ".join(str(task or "").split())
    return flat[:TASK_TEXT_MAX]


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


#: `state` 的五档（不许增删：`roster_view` 的对外取值域，前端与读侧都按它显示）。
#: "判不了"不是第六档 —— 它是旁边那一格 `state_checked=False`（2026-10-27）。
STATE_LABELS: tuple[str, ...] = ("活跃", "待命", "已停", "已退役", "未登记")


def _state_reading(branch: str, retired: bool, cond: Any, task_id: str, *,
                   branch_checked: bool = True) -> dict[str, Any]:
    """四态折叠（`draft/92` §2）＋ 三态位：`{"state", "state_checked", "state_reason"}`。

    `branch` 来自 `conductor.retire_ready`（`active` / `waiting_with_children` /
    `waiting_no_children`）；"待命"再看 `keep_alive_of`（那一格只回答"声明过待命没有"）。
    两个读侧正交，折叠只在这一处做（不许让它们互相猜）。

    ## 为什么多了 `state_checked`（2026-10-27）
    改前"待命声明读不成"折成 `state="已停"` —— 那是把"没查成"写成一条结论，而这一格
    会被父代理读成"它停了、可以销号"。五档取值域不改（前端与读侧都按它显示），
    改成另一格回答可不可信：
    - `state_checked=True`：`state` 是查过的结论；
    - `state_checked=False`：`state` 只是五档里的占位（落"未登记"，五档里唯一不声称
      任何结论的那一档），真读数在 `state_reason` 里（谁没读成、为什么）。
    读侧不许在 `state_checked=False` 时把 `state` 当"它停了"用（判据
    `tests/test_roster_state_is_checkable.py`）。

    ## 三态位怎么定
    - 已退役 / 活跃 / 未登记（branch 为空）：`state_checked=True` —— 这三档都是"读到了
      台账、读到了就绪读数"之后的结论；
    - `branch_checked=False`（那一层的 `retire_ready` 没读成）：`state_checked=False`；
    - 待命声明读不成（`keep_alive_of` 的 `checked=False`）：`state_checked=False`，
      且 `state` 落"未登记"（不落"已停"）。
    """
    if retired:
        return {"state": "已退役", "state_checked": True, "state_reason": ""}
    if branch == "active":
        return {"state": "活跃", "state_checked": True, "state_reason": ""}
    if not branch:
        if not branch_checked:
            return {"state": "未登记", "state_checked": False,
                    "state_reason": "这一层的就绪读数（`retire_ready`）没读成 ⇒ 它属哪一档判不了"}
        return {"state": "未登记", "state_checked": True, "state_reason": ""}
    try:
        ka = cond.keep_alive_of(task_id)
    except Exception as exc:  # noqa: BLE001
        ka = {"checked": False, "reason": f"{type(exc).__name__}: {exc}"}
    if not ka.get("checked"):
        return {"state": "未登记", "state_checked": False,
                "state_reason": (f"待命声明没读成（{ka.get('reason') or '未给理由'}）"
                                 "⇒ '待命'与'已停'分不开")}
    if ka.get("keep_alive"):
        return {"state": "待命", "state_checked": True, "state_reason": ""}
    return {"state": "已停", "state_checked": True, "state_reason": ""}


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
    if str(facts.get("status") or "") in LIVE_TASK_STATUSES:
        return "running"
    return "idle"


# ---------------------------------------------------------------- 台账行分轴（Q18，2026-10-26）
#
# 一条 `tasks` 行到底是"在跑的子代理"、"板项"还是"顶趟行"，这个判断只许有一处。
# 散在多处时各写一遍（扇出轴 / 未消项轴 / 闭环轴），而闭环轴那一份没读 `kind`：
# 30 条板项行（`status` 恒为 `pending`）会被数成"running 5 条"（`MAX_REMINDERS` 截断），
# 而那一刻 18 条代理行全部 done、台账里一个在跑的子都没有。
#
# 落点为什么在秘书而不在 conductor：收件箱一族归秘书。
#
# 上面那一处判据同时回答了两个问题 —— "这一行是什么"（轴）与
# "它还活不活"。要"所有代理行（含终态）"的读点拿不到它（终态代理行被折进 `other`），
# 要"活着的代理"的读点又得自己再写一遍 `status ∈ {pending, running}`。所以拆成两件：
# `row_axis(row)` 只回答轴（五档），
# `is_live_agent(row)` 只回答"是不是一个活着的代理"（= 轴是 agent）。判据仍然只有这一处，
# 读点调哪一个由它问的问题决定，不许再内联 `kind` / `status`。
#: 代理行：`kind` 为空、不是顶趟行、`status` 还没终态。
ROW_AXIS_AGENT = "agent"
#: 板项行：`kind` 非空且 `item_state != "done"`（还没收口）。
ROW_AXIS_ITEM_OPEN = "item_open"
#: 板项行：`kind` 非空且已经收口（`item_state == "done"`）。
ROW_AXIS_ITEM_CLOSED = "item_closed"
#: 顶趟行：`open_top_level_run` 开的那一行（`action="run"`、没有父）。
ROW_AXIS_ROOT = "root"
#: 其余（代理行的历史终态行等）：两根轴都不进。
ROW_AXIS_OTHER = "other"
#: 顶趟行的动作哨兵（`conductor.open_top_level_run` 与 `_open_consume_root` 写的）。
TOP_LEVEL_ACTION = "run"
#: "还没终态"的两档（`schema.TASK_STATUSES` 里的活档；与 conductor 的扇出判据同一批）。
#:
#: 这一行是全仓唯一的真身：conductor 的 `UNFINISHED_STATUSES` 是它对
#: 这一行的转发（`tuple(SEC.LIVE_TASK_STATUSES)`），不再是第二份字面量。方向是这样选的，
#: 不是反过来：`conductor` 顶层 import `secretary`（那一行要读 `MAX_REMINDERS`），
#: 而 `secretary` 顶层不 import `conductor` —— 这样两种导入顺序都无环。
#: 判据：`tests/test_live_statuses_single_source.py`（两个名字取到的必须是同一个元组，
#: 且这两个文件里除本行之外不再有 `("pending", "running")` 字面量）。
LIVE_TASK_STATUSES = ("pending", "running")


def row_axis(row: Mapping[str, Any]) -> str:
    """一行 `tasks` 落在哪根轴上（唯一判据，2026-10-26 Q18；Q27 起只管轴）。

    三件事实按这个次序定：

    1. `kind` 非空 ⇒ 板项行（`conductor.open_item` 建的行：`notice` / `message` /
       `report` / `delegation`）。板项行的 `status` 永远是 `pending`（`open_item` 写死、
       `_set_item` 只改 `item_state`）⇒ 拿 `status` 判"在跑"必然把它们算进去。
       "收口了没有"由 `item_state == "done"` 回答：它和"这是哪根轴"是两个问题，
       但都只在这里判（改前收口与否根本没进读数，已 ack 的板项也照样算在跑）。
    2. `kind` 为空、`action == "run"` 且没有父 ⇒ 顶趟行：它是"用户发起的那一趟"本身，
       不是谁的子代理（`open_top_level_run` 与队列认领的树根都是这个形态）。
       为什么形状这么写：真机那 18 条代理行里 16 条 `action` 是空串、1 条 `run_once`
       —— "action 属跑活的那几档"的白名单会把 16 条真代理漏掉，那是反向的谎。
       所以这里只排顶趟哨兵，而且要求"没有父"：父派给它一次 `A.run` 那种真子代理
       带着 `parent_task_id`，不许被一起排掉。
    3. 其余 `kind` 为空的行：`status` 在活档 ⇒ 代理行；否则 ⇒ 别的（历史终态行）。
       终态行不是"被排除的候选"，它已经收过工了，两根轴都不进、也不进任何一个计数。

    读不成不是"没有行"：异常由调用方折成三态，本函数只认拿到的那一行。

    与 Q18 的 `task_row_axis` 逐字同形（五档、同输入同输出）—— 这一批只是改名并把
    "活不活"那一问搬进 :func:`is_live_agent`，读数一个都不许动。判据见
    `tests/test_the_axis_and_liveness_are_asked_separately.py`。
    """
    if str(row.get("kind") or ""):
        if str(row.get("item_state") or "") == "done":
            return ROW_AXIS_ITEM_CLOSED
        return ROW_AXIS_ITEM_OPEN
    if (str(row.get("action") or "") == TOP_LEVEL_ACTION
            and not str(row.get("parent_task_id") or "")):
        return ROW_AXIS_ROOT
    if str(row.get("status") or "") in LIVE_TASK_STATUSES:
        return ROW_AXIS_AGENT
    return ROW_AXIS_OTHER


def is_live_agent(row: Mapping[str, Any]) -> bool:
    """这一行是不是"一个活着的代理"（唯一判据，2026-10-26 Q27）。

    与 :func:`row_axis` 的分工：轴回答"这一行是什么"（板项 / 顶趟 / 代理 / 别的），
    这一问回答"它还算不算在跑"。两者此前挤在同一个返回值里，于是要"所有代理行
    （含终态）"的读点拿不到、要"活着的代理"的读点只能自己再写一遍
    `kind == "" and status in {pending, running}` —— 而自己写的那几份就是 Q18 之前
    板项被数成"在跑的子代理"的来源。

    判法只有一句：轴是 `agent` 就是活着的代理（活档的判定在 :func:`row_axis` 的
    第 3 步，这里不重复写状态词表）。顶趟行、板项行、终态代理行都不是。

    改前它的三处调用方各写一遍判据，其中两处（`conductor._in_flight_children_of`
    与 `statusreport.collect`）连"哪一行是板项"都要自己判 `kind`；迁移的判据见
    `tests/test_the_axis_and_liveness_are_asked_separately.py`。
    """
    return row_axis(row) == ROW_AXIS_AGENT


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


#: 秘书的写集（B 交内容、秘书落盘）。只有这两张表，
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
    # 回验的方式与证据三栏必须能过秘书这一道（回验保持语义相同即可；语义那一档必须
    # 留证据）—— 否则 B 传给 `register_statement` 的
    # `quote_mode` 会被这一层的白名单静默丢掉（那一栏就白填了）。
    "quote_mode", "quote_span", "quote_call_sha256",
    "deps", "concepts",
    # 概念行"确实是我们自己定义的新概念"的显式声明。
    # 它必须能过这一层的白名单 —— 否则调用方在概念条目里写的那一句
    # `self_authored=True` 会被静默丢掉，于是"声明了"与"没声明"落成同一件事，
    # 而 `origin="own_result"` 的受控判据（`conceptrows.concept_origin_problem`）
    # 就永远只能拒绝、无法放行。
    "self_authored",
    # 多段可选证明：B 自己分的段（每段一组 `path_group`）。不给就把
    # "定理内容 + 证明过程"当一段 —— 秘书不按空行/字样猜 B 想分几段。
    "proof_paths",
    # 表述几乎相同的定理要认出是同一个；证明方式几乎相同的视为同种证明，
    # 可选"各取所长混合成一份、重拿 V 签"：`merge=True` 是那一档可选项的开关。
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
#: 同一命题的判据：确定性键相同 ⇒ 这一笔不是新命题，而是那条命题的第 N 份证明；
#: 词面相似度只作材料读数（`_fail_closed_reason` 报"离阈值有多远"），不决定并。
#: 缺省阈值与唯一实现都在 `propositionkey`，这里只是把它们摆到秘书这一层
#: （可注入：构造参数 `same_proposition_jaccard`）。
SAME_PROPOSITION_JACCARD = _PK.SAME_PROPOSITION_JACCARD
#: 同种证明的判据（同一命题下的第 N 份证明）：判成 `same` ⇒ 不新增证明号，受控拒绝
#: `proof_same_kind`（或 `merge=True` 合成一份并重拿 V 签）。判据是秘书的语义二态
#: （`Secretary.judge("proof_kind", …)`：语义判别，不做机械闸，结论只有一致/不同）；
#: 相似度只作材料读数，不参与收不收。
PROOF_SAME_JACCARD = _PK.PROOF_SAME_JACCARD
#: 同一命题命中的两条依据（进返回值与拒信：读的人要能分辨"凭什么并的"）。
MERGED_BY_KEY = _PK.BASIS_KEY
MERGED_BY_SIMILARITY = _PK.BASIS_SIMILARITY
#: 第三种依据：秘书那一趟模型判定说"同一条"（`adjudicate_proposition`）。
#:
#: 它必须与上面两条分开命名：键相同 / 相似度兜底都是机械读数，而这一条是"读了条件与结论
#: 之后判的" —— 三者的可信度、可复核方式、以及"凭什么并的"那句话都不一样。
MERGED_BY_ADJUDICATION = "secretary_adjudication"
#: 同种证明的拒收码（写侧与拒信共用这一个字面量）。
PROOF_SAME_KIND = "proof_same_kind"
#: 同种证明这一问"没判成"的受控码（「没有判不了」）。
#:
#: 为什么必须与 `PROOF_SAME_KIND` 分开：那一档是现象结论（"判过了、同种"），这一档
#: 没有结论（判定面回 `checked=False`：超时 / 坏 JSON / 没给可用答案都落这一档）。
#: 折平会把"没判成"读成"判过了、不同"（于是照旧新增证明号）或"同种"（于是静默拒收）
#: —— 前者是同一种证法被并列记录，后者是一份真的另一种证法被拒，两种都错。
PROOF_KIND_UNJUDGED = "proof_kind_unjudged"
#: 概念同一性"没判成"的受控码（同上）。
#:
#: 概念这一档是确定性判据（`same_concept`，零模型调用），但"两侧都抽不出定义项"仍是
#: 判不了：折成 different 就会照旧新建第二行（同一个概念两行，正是这一档要治的形态），
#: 所以调用方受控拒，不是"照常新建"。
CONCEPT_IDENTITY_UNJUDGED = "concept_identity_unjudged"
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
#:
#: `example`（玩具例子）也在这
#: 一张表里：它只是给人看的标签，处理与普通命题一致 —— 落稿 / 过形态闸 / 送 V /
#: 按五元位算等级，一条都不特殊。它进来是为了让"命题性的那几档"与"正文里能收进
#: `Example` 环境的那一档"是同一份名单：手稿头写 `- 命题类型：example`、B 收录时按它
#: 落 kind（`_declared_manuscript_kind` 只认这张表）。不是为 example 单开一个分支：
#: 这里加一个取值，`derive_grade` / `judge_proposition_form` / `verify_proof` 一个字不动。
PROPOSITION_KINDS: tuple[str, ...] = ("theorem", "lemma", "proposition", "corollary",
                                      "conjecture", "example")


def _is_proposition_kind(kind: Any) -> bool:
    """这个 kind 算不算"命题性的"（决定它参不参与同一命题判定）。"""
    return str(kind or "").strip().lower() in PROPOSITION_KINDS


def _proposition_judgment_missing(kind: Any, adj: Mapping[str, Any]) -> str:
    """这一次同一性判定能不能支撑"新建 / 合并"（返回非空 = 不能，值是为什么）。

    ## 判据（业主 2026-11-08：「没有判不了」）
    三条，顺序固定：
    1. 不是命题性的 kind ⇒ 不适用（返回空串：概念那一档走 `same_concept`，不走这一问）；
    2. 试过而没判成（`attempted=True` + `checked=False`：超时 / 坏 JSON / 词表外结论 /
       same 点不出号 / 没有检索面）⇒ 受控拒：不新建、不合并。"没判成"不等于"不是同一条"，
       拿它当 different 去新建一行，就是"既在账上又不在账上"的那种重复；
    3. 判成了、但判词不在两档里 ⇒ 同上（防御：`judge()` 已经挡了一层）。

    `attempted=False`（没缝 / 开关关着）并不在这里拒：那一档是"这一名秘书根本没有
    判同一性这一路"，沿用 2026-11-04 的确定性兜底（只认确定性键相同）—— 把"没有判断面"
    与"判定失败"折成同一档，会让裸装的测试工作区一笔都写不进去，而归因还指不到缝上。
    """
    if not _is_proposition_kind(kind):
        return ""
    if not adj.get("checked"):
        if not adj.get("attempted"):
            return ""
        return ("这一条要查「是不是在册的同一条命题」，而这一问没判成 ⇒ 受控拒："
                "不新建、不合并（没判成不等于「不是同一条」）："
                + (str(adj.get("reason") or "") or "（没有给原因）"))
    if str(adj.get("verdict") or "") not in PROPOSITION_VERDICTS:
        return (f"这一次判定的判词 {str(adj.get('verdict') or '')!r} 不在两档 "
                f"{list(PROPOSITION_VERDICTS)} 里 ⇒ 受控拒：不新建、不合并")
    return ""


#: `statements.bits` 一栏必须齐的 10 个键（写侧的唯一清单）。
#:
#: 现场（`temp/rmk90-audit/REPORT-R-mk-infinite-90-20261105.md` ② / A-3）：
#: `data/events.jsonl:3671`（20:54:32，`record_statement` sid=000019）写进去的
#: `bits` 是 `{}` —— 同一路径写其余 20 行都是这 10 键齐的 dict。于是 `statements`
#: 里 000019 的 `bits` 是空的（档位、等级全读不出来）。
#:
#: 根因不在 `bits` 的校验器（`schema.Statement.validate` 已经调
#: `evidencebits.bits_shape_problems`），而在「空表被当成没有形状问题」：
#: `bits_shape_problems({})` 返回 `[]` ⇒ 一条 `bits` 整块没填的行照样过闸。
#: 而 `_statement_from` 里那一格写的是 `dict(body.get("bits") or {})` —— 调用方
#: 没交 `bits` 时落盘的就是空表。B 那次走的是 `table.create`（`row` 里没有 `bits`），
#: 被路由到秘书的正路，于是"路由对了、内容少了一格"。
#:
#: 这张清单与 `evidencebits.bits_of` / `normalize_raw` 的产出逐键相同（那两份是
#: 构造器）；这里只在写侧回答"齐了没有"。
STATEMENT_BITS_KEYS: tuple[str, ...] = (
    "numeric", "proof", "reviewed", "formal", "audited",
    "origin", "evidence", "voided_by", "grade", "audited_badge",
)


def _complete_statement_bits(body: Mapping[str, Any], *, kind: str, origin: str,
                             ) -> dict[str, Any]:
    """把这一笔交上来的 `bits` 补成完整的 10 键（缺哪一格补哪一格）。

    ## 三条口径（「拒或补全」里的"补全"那一半）

    1. 调用方交了 `bits` ⇒ 按 `evidencebits.normalize_raw` 归一遍（四态/布尔归一、
       等级现算）。归一只补不删：`evidence` / `voided_by` 两个口袋原样保留。
    2. 没交（或交的是空表）⇒ 从这一行自己的字段现算
       （`evidencebits.bits_of`）：`origin` / `source_lit_id` / `quote_verified`
       决定第 2、3 位的引用那一档，`proof_text` 非空即第 2 位为真。
       这一档就是 000019 那一行本来该走的：它是 `own_result`、`proof_text` 为空、
       `quote_verified=None` ⇒ 第 2/3 位为假、等级现算成 `conjecture`，而不是"全空"。
    3. 补完还缺键或有 `None` ⇒ 抛 `ValueError`（「拒」那一半）。`record_statement`
       把它翻成受控拒绝 `write_failed` + 原话，一行都不落。
       `None` 也算缺：`grade=None` 与"没有 grade"在读侧长得一样，而它俩都让
       "档位、等级读不出来"这件事重新成立。
    """
    from . import evidencebits as EB   # 惰性：位的唯一实现

    raw = dict(body.get("bits") or {})
    want_origin = str(origin or body.get("origin") or "own_result")
    if raw:
        bits = EB.normalize_raw(raw, origin=want_origin, kind=kind,
                                voided_by=dict(raw.get("voided_by") or {}))
    else:
        proof_text = str(body.get("proof_text") or "")
        bits = EB.bits_of(
            origin=want_origin,
            source_lit_id=str(body.get("source_lit_id") or ""),
            quote_verified=body.get("quote_verified"),
            proof=bool(proof_text.strip()),
            proof_process=proof_text,
            kind=kind,
        )
    missing = [k for k in STATEMENT_BITS_KEYS if k not in bits or bits.get(k) is None]
    if missing:
        raise ValueError(
            "statements.bits 必须 10 键齐、且没有一格是 None；这一笔缺 "
            f"{missing}（整表只有 {sorted(bits)}）⇒ 整笔不写：落一条空 bits 的行，"
            "档位与等级就再也读不出来（现场 000019）")
    return bits



#: 证明正文进台账的唯一收口闸（2026-11-04，业主裁定：正文必须由手稿承载）。
#:
#: 规则：`proof_text` 与在册那一份不同（或这一行还不存在）⇒ 必须有一份盖住这一份正文、
#: 而且审的是手稿的 V 签。判据只认台账行上的 `manuscript` 非空（`verifications.<号>.jsonl`）：
#: 内联审出来的签（今晚 14:22 那种）没有载体，签块 / `## 依赖` / 按号寻址三样都落不了盘。
PROOF_TEXT_NEEDS_MANUSCRIPT_SIGN = "proof_text_needs_a_manuscript_sign"


def proof_text_manuscript_sign_gate(store: Any, *, proof_text: Any,
                                    statement_full: Any = "",
                                    statement_id: Any = "", proof_no: Any = 1,
                                    origin: Any = "", source_lit_id: Any = "",
                                    defer_without_sign: bool = False
                                    ) -> dict[str, Any]:
    """这一份要写进 `statements.proof_text` 的正文，有没有一份"手稿签"覆盖它。

    ## 为什么判据只在这一处
    写 `statements.proof_text` 的路不止一条：B 的 `register_statement`（新建 / 升档 /
    重复支的 canonical 覆盖）、`table.create` / `table.update` 的 `routed` 分支、
    秘书的合并支 —— 它们最后都落在同一个字段上。把判据放在字段的写入口（本函数由
    `Secretary.record_statement` 与 `B._attach_proofs` 共用），才谈得上"唯一收口"；
    每条路各写一份判据，下一支新写口就会静默漏过去。

    ## 判据（三态，不折平）
    - 这一笔没有正文 / 正文与在册逐字相同 ⇒ `required=False`（不是"查过了、有签"，是
      "这一笔没有要写的新正文"）：升档、重复读数、D 的读稿登记都走这一档，不能被堵死；
    - 文献侧占位签（`origin="external_lit"` 且有 `source_lit_id`）⇒ 放行，理由与
      `register_statement._unsigned_proof_gate` 的文献档同一条（业主 2026-11-02：
      「F 的签 或 文献编号」）；
    - 其余 ⇒ 在 `verifications/<命题号>.jsonl` 里找 `proof_sha256` 等于这一份正文、
      `proof_no` 相同、结论「成立」、`unresolved_errors=0`、且 `manuscript` 非空的
      那一行；找不到 ⇒ 受控拒绝。
    台账读不出来 ⇒ `checked=False` + 拒绝（"没查成"不是"没有签"，两者都不放行，但
    理由必须分开）。

    ## 为什么行不存在也拒绝
    新建一条命题时先落"没有正文"的猜想行拿号、V 审稿签字、再把正文交回来（今晚 14:16
    的现场就是这个顺序）；正文与命题同一次落库且没有号，就无从有"盖住它的台账签"。
    放行它等于把"先签后登记"折成"没签也能登记"。

    返回（键集合固定）：`{checked, required, ok, refused, reason, statement_id,
    proof_no, sha256, covering}`。`covering` 是命中的台账行摘要（`verification_id` /
    `manuscript`），给读的人核对"是哪一份稿上的签"。
    """
    from . import verifications as _VR

    out: dict[str, Any] = {"checked": True, "required": False, "ok": True,
                           "refused": "", "reason": "", "statement_id": "",
                           "proof_no": 0, "sha256": "", "covering": []}
    text = str(proof_text or "").strip()
    if not text:
        out["reason"] = "这一笔没有要写进 proof_text 的正文 ⇒ 这一格不适用"
        return out
    try:
        no = int(_VR.as_proof_no(proof_no) or 1)
    except (TypeError, ValueError):
        no = 1
    out["proof_no"] = no
    sha = _PR.proof_sha(text)
    out["sha256"] = sha
    sid = str(statement_id or "").strip()
    row: Mapping[str, Any] | None = None
    try:
        rows = [dict(r) for r in store.rows("statements")]
    except Exception as exc:  # noqa: BLE001 —— 读不到就不许放行
        out.update(checked=False, ok=False, refused=PROOF_TEXT_NEEDS_MANUSCRIPT_SIGN,
                   reason=(f"`statements` 读不出来（{type(exc).__name__}: {exc}）⇒ "
                           "判不了这一份正文有没有手稿签（没查成不是通过）"))
        return out
    if sid:
        # 按号定位走查口（口径一）；`rows` 是这一层刚读的那一份快照。
        row = SL.by_id(rows=rows, stmt_id=sid)["row"] or None
    elif str(statement_full or "").strip():
        # 正文规范化全等的比对口径只有一处（查口 `duplicate_hits`）。
        row = (SL.duplicate_hits(rows, text=statement_full)["hits"] or [None])[0]
    if row is not None:
        out["statement_id"] = str(row.get("stmt_id") or "")
    if row is not None and str(row.get("proof_text") or "").strip() == text:
        out["reason"] = "与在册那一份正文逐字相同 ⇒ 这一笔不写正文（升档 / 重复读数）"
        return out
    out["required"] = True
    origin_now = str(origin or (row or {}).get("origin") or "")
    lit_now = str(source_lit_id or (row or {}).get("source_lit_id") or "").strip()
    # 概念行的良定义证明不认文献占位签（2026-11-10 业主裁定 甲）：那一份正文必须
    # 由 V 对 b-稿真签过；占位签只给"命题正文摘录自文献"那一档（与
    # `_unsigned_proof_gate` 同一条分界）。
    is_concept = str((row or {}).get("kind") or "") == "concept"
    if origin_now == "external_lit" and lit_now and not is_concept:
        out["reason"] = ("文献侧：V 签位填文献编号（占位签）⇒ 允许入台账"
                         "（与 `register_statement` 的文献档同一条口径）")
        return out
    if row is None:
        if defer_without_sign:
            out["reason"] = ("命题还没在册：有没有签由 B 的 `_unsigned_proof_gate` 判"
                             "（这一道只判'签有没有手稿载体'）")
            return out
        out.update(ok=False, refused=PROOF_TEXT_NEEDS_MANUSCRIPT_SIGN,
                   reason=("这一条命题还没有在册行，而这一笔要写证明正文 ⇒ 没有可落签的号，"
                           "也没有一份盖住它的手稿签。正路：先落一条没有正文的猜想行拿号"
                           "（`kind=\"conjecture\"`）→ 让 V 审那一份手稿（带 `proof_manuscript`）"
                           "→ 再把这一份正文交回同一 `statement_full`。"))
        return out
    # ---- D268 批 2：签这一格只认 `sign_reading.state=="signed"`（可复算的凭据）----
    # 手稿载体那一道还留在下面（这一道只判"签有没有手稿载体"）：两条合起来才是这一格
    # 的原意 —— 签是真的（凭据可复算），而且它在手稿上（不是内联签）。
    from . import vsigns as _VS

    sign = _VS.sign_reading(store.root, statement_id=out["statement_id"],
                            proof_text=text, proof_no=no, store=store)
    out["sign"] = dict(sign)
    if not bool(sign.get("checked")):
        out.update(checked=False, ok=False, refused=PROOF_TEXT_NEEDS_MANUSCRIPT_SIGN,
                   reason=(f"签的读数没查成（{sign.get('why') or '没有读数'}）⇒ "
                           "判不了这一份正文有没有手稿签（没查成不是通过）"))
        return out
    if str(sign.get("state") or "") != "signed":
        votes = int(sign.get("votes") or 0)
        need = int(sign.get("need") or _VR.SIGN_STREAK_NEED)
        state = str(sign.get("state") or "")
        if defer_without_sign:
            out["reason"] = (f"这一份正文的签读数是 {votes}/{need}（state={state}）⇒ "
                             "有没有签由 B 的 `_unsigned_proof_gate` 判"
                             "（这一道只判'签有没有手稿载体'）")
            return out
        out.update(ok=False, refused=PROOF_TEXT_NEEDS_MANUSCRIPT_SIGN,
                   reason=(f"这一份正文（sha {sha[:12]}…）的签读数是 {votes}/{need}"
                           f"（state={state}）⇒ 不能进台账。"
                           f"{sign.get('why') or ''}。正路：让 V 把这一份正文审到连续 "
                           f"{need} 次「成立」并由收方秘书发签（`vsigns.issue` 写 "
                           f"`out/vsigns/<正文sha>.json`），再入库。"))
        return out
    try:
        ledger, bad = _VR.list_verifications(store.root, statement_id=out["statement_id"],
                                             limit=None)
    except Exception as exc:  # noqa: BLE001 —— 读不到不许折成"没有签"
        out.update(checked=False, ok=False, refused=PROOF_TEXT_NEEDS_MANUSCRIPT_SIGN,
                   reason=(f"验证台账读不出来（{type(exc).__name__}: {exc}）⇒ "
                           "判不了这一份正文有没有手稿签（没查成不是通过）"))
        return out
    if bad:
        out.update(checked=False, ok=False, refused=PROOF_TEXT_NEEDS_MANUSCRIPT_SIGN,
                   reason=("验证台账有读不出来的行：" + "；".join(str(b) for b in bad[:3])
                           + " ⇒ 判不了这一份正文有没有手稿签（没查成不是通过）"))
        return out
    any_cover: list[dict[str, Any]] = []
    covers: list[dict[str, Any]] = []
    for item in ledger:
        if str(item.get("proof_sha256") or "").lower() != sha:
            continue
        try:
            if int(item.get("proof_no") or 1) != no:
                continue
        except (TypeError, ValueError):
            continue
        if not _VR.row_signable(item):
            continue
        one = {"verification_id": str(item.get("verification_id") or ""),
               "manuscript": str(item.get("manuscript") or ""),
               "at": str(item.get("at") or "")}
        any_cover.append(one)
        if one["manuscript"]:
            covers.append(one)
    out["covering"] = covers[:5]
    if not covers:
        if any_cover:
            out.update(ok=False, refused=PROOF_TEXT_NEEDS_MANUSCRIPT_SIGN,
                       reason=("这一份正文（sha {sha}…）在 V 的台账里有签，但那一签是"
                               "内联审出来的（台账行上没有 `manuscript`）—— 内联签没有"
                               "载体，签块 / `## 依赖` / 按号寻址三样都落不了盘。正路：先把"
                               "正文落成一份稿（`reports/f-proof-*.md` / `notes/*.md`）→ "
                               "派 V 用 `verify.verify_proof` 带 `proof_manuscript` 审那一份"
                               "稿 → 签块落回稿 → 再入库。").format(sha=sha[:12]))
            return out
        if defer_without_sign:
            out["reason"] = ("这一份正文还没有任何覆盖它的签：有没有签由 B 的 "
                             "`_unsigned_proof_gate` 判（这一道只判'签有没有手稿载体'）")
            return out
        out.update(ok=False, refused=PROOF_TEXT_NEEDS_MANUSCRIPT_SIGN,
                   reason=("这一份正文（sha {sha}…）一次都没有被 V 签过 ⇒ 不能进台账。"
                           "正路：先把正文落成一份稿（`reports/f-proof-*.md` / `notes/*.md`）"
                           "→ 派 V 用 `verify.verify_proof` 带 `proof_manuscript` 审那一份稿"
                           "→ 签块落回稿 → 再入库。").format(sha=sha[:12]))
        return out
    out["reason"] = (f"有手稿签覆盖这一份正文（{len(covers)} 行："
                     + "、".join(str(c.get("verification_id") or "?") for c in covers[:3])
                     + "）")
    return out


def _bits_bear_evidence(bits: Any) -> bool:
    """`bits` 里有没有「调用方显式给的真凭据」（决定正文闸 defer 不 defer）。

    ## 为什么不能按 truthiness 判（2026-11-06 真退化）

    2026-11-05「等级是唯一的轴」之后，盘上每一行的 `bits` 是 10 键规范化的字典
    （`numeric/proof/reviewed/formal/audited/origin/evidence/voided_by/grade/
    audited_badge` 全在，值可以是 pending/false）—— 它恒 truthy。而
    `table.update` 的 routed 分支会把盘上整行叠进 body（`merged = dict(current)`），
    于是 `bool(body.get("bits"))` 把"盘上那一行原样带回来的空 bits"读成了
    "调用方给了证据" ⇒ 正文闸被 defer，一条没有手稿签的新行照样建出来
    （`table.update(statements, patch={statement_full, proof_text})` 实测建出 000001）。

    判据：只有第 2/3 位为真，或第 1/4 位 `verified`，才算"带真凭据"。全
    pending/false 的规范化空位不算 —— 它不是证据，只是"这一行有位记录"。
    """
    if not isinstance(bits, Mapping):
        return False
    raw = dict(bits)
    if not raw:
        return False
    if bool(raw.get("proof")) or bool(raw.get("reviewed")):
        return True
    for name in ("numeric", "formal"):
        value = raw.get(name)
        if isinstance(value, Mapping):
            if any(str(one).strip().lower() == "verified" for one in value.values()):
                return True
        elif str(value or "").strip().lower() == "verified":
            return True
    return False


def _semantic_quote_evidence_refusal(body: Mapping[str, Any]) -> dict[str, str]:
    """`quote_mode="semantic"` 但缺证据 ⇒ `{refused, reason}`；不适用/证据齐 ⇒ `{}`。

    语义那一档必须留证据：`quote_span`（来源那一段逐字正文）与
    `quote_call_sha256`（那次语义判定的调用记录）缺一不可 —— 说不出对着哪一段、
    哪一次判的，就不算通过（三态纪律：没查不许折成查过了没问题）。

    为什么单列成函数：它此前内联在 `Secretary.record_statement` 里，而那方法在
    2026-11-07 的体量读数里刚好越过 200 行基线；判据（`_normalize_quote_mode`）
    与拒码都没变，只是把这一格搬到"写库前可读拒绝"自己的函数里。
    """
    if str(body.get("quote_mode") or "") != "semantic":
        return {}
    span = str(body.get("quote_span") or "").strip()
    call = str(body.get("quote_call_sha256") or "").strip()
    if span and call:
        return {}
    miss = "quote_span（来源那一段逐字正文）" if not span else \
        "quote_call_sha256（那次语义判定的调用记录）"
    return {"refused": "quote_evidence_missing",
            "reason": (f"标了 quote_mode='semantic' 但缺 {miss} —— 语义那一档"
                       "必须留证据：说不出对着哪一段、哪一次判的，就不算通过。"
                       "补上这两栏，或把 quote_verified 改成 None/False 并写明"
                       "为什么（三态纪律：没查不许折成查过了没问题）")}


def _manuscript_upgrade_basis(*, root: Any, manuscript_text: Any = "",
                              manuscript_path: Any = "", proof_text: Any = "",
                              bits: Mapping[str, Any] | None = None
                              ) -> dict[str, Any]:
    """这一笔带来的证据里，有哪一路 V 的签 ⇒ `{checked, signed, basis, why, manuscript}`。

    ## 为什么需要这一格（2026-11-04，缺口 ②）
    同一套代码两个分支结果不一致（真机读数：`stmt 000000`）：命中在册 ⇒
    `evidence_kind` 停在 `cross_check`、`kind` 停在 `conjecture`；新建 ⇒
    `kind=theorem`、`evidence_kind=proof`。根因是 `_upgrade_evidence_kind` 只读
    `verifications.proof_review_gap`（签名台账 `verifications/<命题号>.jsonl`），
    而 E 这一签在"手稿签块 + pending 台账"里 ⇒ 读不到。

    ## 三档（两路新凭据 + 没签）
    - 手稿签块：`vsigns.manuscript_sign_standing(手稿正文, proof_sha=证明栏)` 的
      `state="signed"`（连续次数够、正文 sha 相符、块与稿不互相打脸）；
    - `bits.reviewed`：B 收录时按正文 sha 认到的签（逐份记在
      `bits.evidence.reviewed_by_proof[证明号]`），且第 2 位（proof）为真；
    - 都没有 ⇒ `signed=False`，`why` 说清"没签"（不是"没查成"）。
    手稿给了但读不出来 ⇒ `checked=False`（没查成不许折成没签）。

    这一格是纯读：不改行、不写盘。判据本体（"这一签算不算"）仍只在
    `vsigns.manuscript_sign_standing` 与 `bits` 的现算里，这里只把两路结论收拢。
    """
    out: dict[str, Any] = {"checked": True, "signed": False, "basis": "",
                           "why": "", "manuscript": {}}
    text = str(manuscript_text or "")
    proof = str(proof_text or "")
    if text.strip():
        out["checked"] = False
        try:
            from . import verifications as _VR   # 惰性：正文 sha 的口径只有一处
            from . import vsigns as _VS          # 惰性：签块读数的口径只有一处

            sha = _PR.proof_sha(proof) if proof.strip() else ""
            ms = _VS.manuscript_sign_standing(
                text, proof_sha=sha, manuscript_path=str(manuscript_path or ""))
            out["manuscript"] = {k: ms.get(k) for k in (
                "state", "signed", "streak", "need", "proof_sha256",
                "body_mismatch", "why")}
            out["checked"] = True
            if str(ms.get("state") or "") == "signed":
                out.update(
                    signed=True,
                    basis=(f"手稿签块（连续 {int(ms.get('streak') or 0)}/"
                           f"{int(ms.get('need') or 0)} 成立、正文 sha 相符）"))
                return out
        except Exception as exc:  # noqa: BLE001 —— 读不出来要如实说，不许折成"没签"
            out["checked"] = False
            out["why"] = (f"手稿签块读取失败（{type(exc).__name__}: {exc}）"
                          "⇒ 这一格没查成，不是「没签」")
    b = dict(bits or {})
    if bool(b.get("proof")) and bool(b.get("reviewed")):
        out.update(checked=True, signed=True,
                   basis=("bits.reviewed（第 3 位；B 收录时按正文 sha 认到的逐份签）"))
        return out
    if not str(out.get("why") or "").strip():
        out["why"] = ("手稿里没有 V 的签块，`bits.reviewed` 也不是真 ⇒ "
                      "这一笔没有覆盖这份正文的签（不许因为「命中在册」就升档）")
    return out


def _signed_exhaustion_terminal(*, root: Any, row: Mapping[str, Any],
                                proof_text: Any, experiments: Any
                                ) -> dict[str, Any]:
    """这一行是不是已经停在「穷举程序 + V 签 ⇒ `proof`」那个终态 —— 纯读。

    ## 为什么需要这一格（甲 的落点，2026-11-04 业主裁定）
    穷举数值证明 + 针对该穷举的 V 签 ⇒ 直接 `proof`（`schema.EVIDENCE_KINDS` 的
    口径；`proof_review` 是"V 逐行走查文字证明"，V 不能逐行走查一份程序）。于是
    `verifications._grade_recomputed_from_signature` 在 V 落签那一刻就按通道把这一行
    定到 `proof` —— 等到 B 拿着 D 的目录来登记同一条内容时，盘上那一行已经是
    `proof`，B 那一笔没有任何格可改。

    ## 这一格解决什么
    那样一笔既不是"重复登记"（东西确实在库里、就停在它该在的那一档），也不是"这次
    升了档"（盘上没动）。秘书的升档梯子只认"弱 → 强"（`WEAKER_THAN_PROOF_REVIEW`），
    `have == want == "proof"` 落不进任何一支 ⇒ 会掉进 `duplicate_statement` 的拒信里，
    让"穷举证明已经进库"被读成"没写成"。所以这里给一条只读判据：同一条内容、要的
    就是 `proof`、而盘上那一行已经是 `proof`，且凭据正是穷举程序 + V 签 ⇒ 终态，这一笔
    是空操作（`at_tier=True`）。

    ## 判据只有一处（与回填、审计同一份）
    ① 证明栏要有与它对应的、V 签下的穷举证明：`numericproof.find_signed_exhaustion_for_column`
    （与 `verify` 的 `proof_stmt_without_formal_backing` 第二条合法背书同一个函数）；
    ② 这一份正文要被 V 的签盖住：`verifications.proof_review_gap`（写入期闸 / 审计期 /
    收工门读的都是它）。两条缺一条都不认终态（保守：宁可走原来那一档读数）。

    返回 `{checked, terminal, script, experiment_id, why}`；`terminal=False` 时调用方
    保持原来的 `duplicate` 路径。
    """
    out: dict[str, Any] = {"checked": False, "terminal": False, "script": "",
                           "experiment_id": "", "why": ""}
    text = str(proof_text or row.get("proof_text") or "")
    if not text.strip():
        out["checked"] = True
        out["why"] = "这一行没有证明正文 ⇒ 没有可认的穷举证明（不认终态）"
        return out
    try:
        from . import numericproof as _NP   # 惰性：穷举判据的单一口径
        from . import verifications as _VR  # 惰性：签的判据只有一处

        hit = _NP.find_signed_exhaustion_for_column(experiments or (), text)
    except Exception as exc:  # noqa: BLE001 —— 判不了就不认终态（不是"认了"）
        out["why"] = (f"穷举判据读不出来（{type(exc).__name__}: {exc}）"
                      "⇒ 这一格没查成，按原来的重复读数走")
        return out
    out["checked"] = True
    if hit is None:
        out["why"] = ("台账里没有与这份证明栏对应的、V 签下的穷举证明 "
                      "⇒ 不是「穷举程序 + V 签」那一通道")
        return out
    out["experiment_id"] = str(hit.get("experiment_id") or hit.get("id") or "")
    try:
        out["script"] = _NP.proof_column_script(text)
        probe = dict(row)
        probe["proof_text"] = text
        probe["evidence_kind"] = _VR.PROOF_KIND
        gap = _VR.proof_review_gap(root, probe)
    except Exception as exc:  # noqa: BLE001 —— 同上：没查成就不认
        out["why"] = (f"这一份正文的签读不出来（{type(exc).__name__}: {exc}）"
                      "⇒ 这一格没查成，按原来的重复读数走")
        return out
    if not gap.get("ok"):
        out["why"] = ("这一份正文没有被 V 的签盖住"
                      f"（{str(gap.get('why') or '查不到凭据')[:240]}）⇒ 不认终态")
        return out
    out["terminal"] = True
    out["why"] = ("盘上这一行已经是「穷举程序 + V 签 ⇒ proof」的终态："
                  f"证明栏 ① 段是 {out['script'] or '（空）'}，"
                  f"台账里 exp:{out['experiment_id'] or '?'} 是 V 签下的穷举证明，"
                  f"V 的签盖住的就是这一版（{gap.get('ledger') or ''}"
                  f"#{gap.get('verification_id') or ''}）")
    return out


#: `same_as` 归一化时要剥掉的外壳字符：模型把候选号写成了 Python/JSON 列表字面量
#: （`"['000003']"`）或加了引号 / 空白（`'"000003"'` / `" 000003 "`）。
#:
#: 为什么集中成一个常量：真机 82 的 52 处坏值只出现三种外形（见
#: `temp/probe_82_errors/same_as_hits.txt`），而"外壳有哪些字符"是这件事的唯一判据；
#: 散在分支里写两遍，下一次多一种外形就会有半处漏掉。
SAME_AS_WRAPPER_CHARS = "[]'\"` \t\r\n"


def normalize_same_as(value: Any) -> tuple[str, int]:
    """把模型点名的号归一化成裸号。返回 `(裸号, 它给了几个号)`。

    真机 82（2026-11-01）：模型判 same 时把 `same_as` 写成 `"['000003']"`（本趟 52 处 /
    16 个会话行），而 `adjudicate_proposition` 的成员判据是"逐字等于某个候选号" ⇒
    判了 same 也不并、照旧落新行，造出 000001/000004、000003/000005 两个重复对。

    ## 口径（宽进严出）
    - 外层 `[]`、引号、反引号与空白一律剥掉：`"['000003']"` / `"000003"` /
      `" 000003 "` 都得到 `"000003"`；
    - 逗号分隔出多个号 ⇒ 不猜（返回 `("", n)`，n 是模型给了几个）：本趟真出现过
      `"['000001', '000004']"`，替它挑一个等于替它表态；
    - 空串 ⇒ `("", 0)`。

    归一化只在"模型给了什么"这一层做，成员判定（在候选表里）仍由调用方按裸号逐字核
    —— 这一格不是放宽，是把"外壳"与"指错号"两件事分开：前者是读数格式，后者是不许并。
    """
    raw = str(value or "").strip()
    if not raw:
        return "", 0
    body = raw.strip(SAME_AS_WRAPPER_CHARS)
    if not body:
        return "", 0
    pieces = [p.strip(SAME_AS_WRAPPER_CHARS) for p in body.split(",")]
    pieces = [p for p in pieces if p]
    if len(pieces) > 1:
        return "", len(pieces)
    if not pieces:
        return "", 0
    return pieces[0], 1



#: `table.update(table="statements")` 允许就地改的非正文三格。
#:
#: 为什么只有这三格：B 这一趟想改的三件事就是它们；改正文有专门的登记路（重交一条
#: 带新 `statement_full` / `proof_text` 的登记，旧正文进 `proof_history`）。
#: 白名单之外的键一律受控拒绝 —— 这里放宽一个词，等于放宽一整类写口，而
#: 「谁能改 statements 的哪一格」是 FC-27 的权限面（`tools/table_tools.py` 也是禁改区）。
STATEMENT_META_PATCH_KEYS: tuple[str, ...] = ("status", "kind", "quote_reason")

#: 放弃/换号时随 `status="abandoned"` 一起交上来的那几格。
#:
#: 它们不是就地改的字段（一个字节都不会落进 row 的顶层键）：它们是"理由"的
#: 结构化形状，由 `statementabandon.check_abandon_reason` 判过之后拼进
#: `quote_reason` 那一条标记里（`abandoned@<ISO8601>@<JSON>`）。所以它们在白名单里
#: （放行到这一层）却不在 `STATEMENT_META_PATCH_KEYS` 里（不被当作可写列）。
#:
#: 为什么必须在这一层就拒：`table.update` 是业主验收的通用写口，模型真会用它；
#: 而"受控拒"要求一个字节都不写 ⇒ 校验必须赶在 `tx.upsert` 之前。
STATEMENT_ABANDON_PATCH_KEYS: tuple[str, ...] = (
    "abandon_kind", "abandon_basis", "defect_ref", "difficulty", "salvaged",
    # E 侧那两档的按档证据（反例 / 枚举空间过于宏大）：
    # `experiment_id` 指一条真的证否实验；`space` 是一份结构化的枚举参数与规模读数。
    "experiment_id", "space")

#: 另外两个终态（2026-11-13 业主裁定）随 `table.update` 交上来的那几格。
#:
#: - `status="refuted"`（标记为错误）：证据三选一 —— `defect_ref` / `construction` /
#:   `experiment_id`（前两格里的 `defect_ref` / `experiment_id` 与放弃那几格同名同义，
#:   所以只在下面补 `construction` 与 `counterexample_valid`），理由正文复用
#:   `abandon_basis`；
#: - `hard_to_prove`（「难以自证」）：它的值是那句理由，另可给 `proof_no` 指哪一份
#:   （缺省 1：引文侧的行只有一份证明）。
#:
#: 与 `STATEMENT_ABANDON_PATCH_KEYS` 同一条纪律：它们不是可写列，判过之后落进
#: `bits` / `quote_reason` 的口袋里；多给一格就受控拒（一个字节都不写）。
STATEMENT_RETIRE_PATCH_KEYS: tuple[str, ...] = (
    "construction", "counterexample_valid", "hard_to_prove", "proof_no")

#: 就地改 `kind` 时认的英文词表（命题性的那几档 + 概念/定义两档）。
#:
#: 中文 kind（`定理` / `引理`）不在里面：它进不了命题性词表、
#: 也不在猜想白名单，而拒因说的是另一件事（去要 V 签）。这一格把"不是取值"说清。
STATEMENT_META_KINDS: tuple[str, ...] = PROPOSITION_KINDS + NOT_APPLICABLE_KINDS

#: 经 :meth:`Secretary.land_statement` 落盘的两类操作各自允许改哪几格（权限面，写死在这一层）。
#:
#: 为什么需要这一格（B 实际只有台账的只读权限；B 的任何"写台账"的路实际都由 B 秘书洗过）：
#: B 的写侧还有两支自己开 `store.tx("statements")`
#: 落行（追加证明 / 更新数值证据位），秘书那一层一个字都没过目。收口之后 B 只交"这一笔要
#: 改成什么"，开事务、读现行行、判"改了哪几格"、写盘四件事都在秘书这一层；这张表是第三件
#: 的判据：
#:
#: - `attach_proofs`：B 追加证明（`#p2` 及以后进 `proofs`）、换 canonical 正文（`proof_text`
#:   ＋旧正文进 `proof_history`）、按签/形式化同步五元位与等级、按证据升 `kind`、写收录回执；
#: - `numeric_evidence`：只动五元位（第 1 位 `numeric` ＋ 它的凭据流水 ＋ `grade`）。
#:
#: 不在表里的格一律改不动（`statement_patch_key_not_allowed`，一个字节都不写）：正文的真身
#: `statement_full`、出处面（`source_lit_id` / `page_range` / `doc_id` / `line_range`）、
#: 创建留痕（`stmt_id` / `created_at` / `created_by`）都在"改不动"那一侧。
#:
#: `proofs` / `_grade_recomputed` 这两格是 `verifications` 的键（`PROOFS_KEY` /
#: `GRADE_RECOMPUTED_KEY`），`_kind_upgrade` 与 `verifications._kind_upgrade_from_signature`
#: 写的是同一格；三处逐字同一套由 `tests/test_b_never_writes_statements_directly.py` 钉着
#: （本文件不在 import 期读 `verifications` —— 它会反过来读本文件）。
STATEMENT_LAND_OPS: dict[str, tuple[str, ...]] = {
    "attach_proofs": (
        "proof_text",           # #p1 的正文（canonical）
        "proof_history",        # 被换掉的旧正文
        "proofs",               # #p2 及以后的清单（`verifications.PROOFS_KEY`）
        "bits",                 # 五元位（含认签表 / 优化态 / 形式化 / `grade`）
        "kind",                 # 按证据升档（`evidencebits.kind_following_grade`）
        "_kind_upgrade",        # 升档留痕
        "proof_no",             # 收录回执（这一行现在是第几份证明）
        "proof_sha256",         # 收录回执（这一份正文的指纹）
        "manuscript_id",        # 收录回执（这份稿的 F 稿号；稿名不再与命题号绑定）
        # 逐路径的稿（2026-11-13，V1-A）：`{路径号: 稿路径}`。收录回执写 `manuscript_id`
        # 时同一笔写这一格 —— 它是"这一条命题的每条路径各是哪份稿"的落点，`manuscript_id`
        # 只有一格、会被第 2 条路径覆写。只由 `agent_b/proof_receipt.write_proof_receipt`
        # 写，读口是 `manuscriptpaths.path_reading`。
        "manuscripts",
        "_grade_recomputed",    # 按签重算等级的读数（`verifications.GRADE_RECOMPUTED_KEY`）
    ),
    "numeric_evidence": ("bits",),
}

#: 同一性按"定义项相同"判的那几档 kind（概念行没有条件 → 结论，命题那一套判据对它失效）。
#:
#: 为什么只有 `concept` 一档、不顺手带上 `definition`：这一档的判据是"标签（或正文里
#: 被定义的那个术语）规范化后相同"，而 `definition` 行在真机台账里常常把标签留着空
#: （命题本体写在 `statement_full` 里），拿它当键会把一堆不相关的定义并到同一行 ——
#: 并错一条的代价比漏并大（与 `PROPOSITION_KINDS` 的取舍同一条理由）。
CONCEPT_IDENTITY_KINDS: tuple[str, ...] = ("concept",)


def _is_concept_kind(kind: Any) -> bool:
    """这个 kind 算不算"概念行"（决定它走定义项那一档同一性判据）。"""
    return str(kind or "").strip().lower() in CONCEPT_IDENTITY_KINDS


#: 洗名洗掉的那两类（`label_washed["class"]` 的取值）—— 读的人要能分辨"哪一类触发了"。
LABEL_WASH_ROUTE = "路线/自证草稿/待审签"
LABEL_WASH_WORKING = "内部工作名"

#: 从正文里抽标签时最多留多少字（超出就截断：名字是用来念的，不是第二份正文）。
LABEL_FROM_STATEMENT_CHARS = 60

#: 内部工作名词表：`(这一类的名字, 正则)`。命中的那一段从标签里删掉，并在
#: `label_washed["class"]` 里点名这一类的名字。
#:
#: 真机读数（`projects/mp3-r2/data/statements.json` 的 000000 / 000001）：两行的 label
#: 逐字都是「F 攻坚 000000 子目标 S2」—— 派活台账里的内部工作名成了定理名，于是
#: 同一条定理的两份证明看起来是两条不同的定理。改前的洗名只洗"路线 / 自证草稿 /
#: 要 V 审签"那一类（见 `_judge_system("proposition_identity")` 里 canonical_name 那
#: 一句），工作名不在那一类里，原样落了盘。
#:
#: 为什么是一张可清空的表而不是几条 if：判据要能被反真空验证（把这张表清空 ⇒
#: 真机那两个 label 必须原样保留），而 if 链清不空，那条反真空用例就会打空炮。
LABEL_WORKING_NAME_RULES: tuple[tuple[str, str], ...] = (
    # 「<角色> 攻坚 <编号>」：角色是一两个字母（F / B2），编号可能省略。
    # 末尾那个否定前瞻是"词尾"判据：`攻坚计划` 里的"攻坚"不是工作名（后面还接着汉字）。
    ("攻坚子目标", r"[A-Za-zＡ-Ｚａ-ｚ]{1,2}\s*攻坚\s*[0-9０-９]*"
                  r"(?![\u3400-\u4dbf\u4e00-\u9fffA-Za-z0-9])"),
    # 「子目标 S<n>」（编号可能省略）
    ("子目标编号", r"子目标\s*[SＳs]?\s*[0-9０-９]*"
                  r"(?![\u3400-\u4dbf\u4e00-\u9fffA-Za-z0-9])"),
    # 「第 n 步」/「第 n 轮」：派活台账里的步号
    ("第几步", r"第\s*[0-9０-９一二三四五六七八九十百]+\s*(?:步|轮)"
              r"(?![\u3400-\u4dbf\u4e00-\u9fffA-Za-z0-9])"),
    # 「待推进」这一档状态词（贴在首尾时算修饰；整条都是它 ⇒ 那不是名字）
    ("待推进", r"(?:待推进|待办|待下一步)\s*[:：,，·—\-]?"
              r"(?![\u3400-\u4dbf\u4e00-\u9fffA-Za-z0-9])"),
    # 「草稿」这一档（「自证草稿」「待 V 审签」是它的两种写法）
    ("草稿/待审签", r"(?:自证草稿|草稿|待\s*V\s*审签|待审签)\s*[:：,，·—\-]?"
                  r"(?![\u3400-\u4dbf\u4e00-\u9fffA-Za-z0-9])"),
)


def _tidy_label(text: Any) -> str:
    """把删掉工作名之后剩下的那一截收拾成能当名字的样子。

    四件事：去掉空括号、折叠空白、削掉首尾的分隔符与句读、去掉落单的开/闭括号。
    为什么要有这一格：删掉「草稿」之后留下的 `（ ）` 与 `：` 都不是名字的一部分，
    而一个以冒号开头的标签看起来仍然像没洗过。
    """
    out = str(text or "")
    out = re.sub(r"[（(【\[]\s*[）)】\]]", " ", out)
    out = re.sub(r"\s+", " ", out).strip()
    out = out.strip(" ·—-,，;；:：、。.()（）[]【】")
    out = re.sub(r"^[（(【\[]\s*", "", out)
    out = re.sub(r"\s*[）)】\]]$", "", out)
    return out.strip()


def _readable_label(text: Any) -> bool:
    """这一截还剩不剩"能当名字念"的东西（至少两个字母或汉字，且不是一串编号）。

    为什么门槛是两个字而不是"非空"：删完之后常剩下 `S2` / `000000` 这种编号，
    它们不是名字；而把编号当名字落盘，下一次读的人只会以为这条定理就叫这个。
    """
    letters = re.findall(r"[A-Za-z\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]", str(text or ""))
    return len(letters) >= 2


def _brackets_balanced(text: Any) -> bool:
    """这一串里的括号配对了吗（圆 / 方 / 六角 / 中文括号各算各自的）。

    为什么洗名要看它：命中的那段若在括号里（真机 sylow4 的
    `Sylow 三定理（路线一：…，自证草稿，待 V 审签）`），删掉之后会剩下半只括号 ——
    那说明这一处是"路线 / 草稿状态"那一类的落点，归模型洗名（`canonical_name`），
    不是本函数的活。括号不配对就整条不动，两种洗名各管各的。
    """
    pairs = (("(", ")"), ("【", "】"), ("[", "]"), ("（", "）"))
    body = str(text or "")
    for left, right in pairs:
        if body.count(left) != body.count(right):
            return False
    return True


def _strip_working_names(text: str) -> tuple[str, list[str]]:
    """把贴在首/尾的内部工作名那几段删掉，返回 `(剩下的, 命中的类名)`。

    只删首/尾（判定：那一段前面的部分、或后面的部分已经念不出名字）：中间的命中
    不动它 —— `草稿本上的定理` 这种名字里，"草稿"是名字的一部分，不是派活台账的残留。
    """
    out = str(text or "")
    hits: list[str] = []
    changed = True
    while changed:
        changed = False
        for cls, pattern in LABEL_WORKING_NAME_RULES:
            for found in re.finditer(pattern, out, flags=re.IGNORECASE):
                before, after = out[:found.start()], out[found.end():]
                if _readable_label(_tidy_label(before)) and _readable_label(_tidy_label(after)):
                    continue
                hits.append(cls)
                out = before + " " + after
                changed = True
                break
            if changed:
                break
    return out, hits


def _first_readable_claim(statement_full: Any, *, kind: str = "") -> str:
    """从正文里抽一句能当标签念的东西（抽不出 ⇒ 空串）。

    概念行优先用「概念（X）」里那个 X（那本来就是它的名字）；其余取第一句可读的命题
    陈述，按句读切（`。` `；` `;` `!` `?` 与换行），跳过太短的、抽不出字面的、以及
    换一行还是工作名的那些。markdown 记号在这里先摘掉：名字里不该出现星号与反引号。
    """
    text = str(statement_full or "")
    if not text.strip():
        return ""
    if _is_concept_kind(kind):
        term = _PK.defined_term(text)
        if term and _readable_label(term):
            return _clip_label(_tidy_label(term))
    plain = re.sub(r"[*`#>|]+", " ", text)
    plain = re.sub(r"\s+", " ", plain).strip()
    for chunk in re.split(r"[。；;！!？?\n]+", plain):
        piece = _tidy_label(chunk)
        if len(piece) < 4 or not _readable_label(piece):
            continue
        _rest, hits = _strip_working_names(piece)
        if hits and not _readable_label(_tidy_label(_rest)):
            continue
        return _clip_label(piece)
    return ""


def _clip_label(text: str) -> str:
    """标签截断（超过 `LABEL_FROM_STATEMENT_CHARS` 就切，不补省略号）。"""
    out = str(text or "").strip()
    limit = int(LABEL_FROM_STATEMENT_CHARS)
    if len(out) <= limit:
        return out
    return out[:limit].strip()


def wash_working_name(label: Any, *, statement_full: Any = "", kind: str = "",
                      stmt_id: str = "") -> dict[str, Any] | None:
    """把标签里的内部工作名洗掉；没命中 ⇒ `None`（原标签一个字节都不动）。

    ## 洗成什么（"不许洗成空"的三级）
    1. 删掉工作名那几段之后还剩能念的东西（`待推进：Noether 环` 这种"状态 + 名字"）⇒
       剩下的那一截就是名字；
    2. 整条标签都是工作名 ⇒ 从 `statement_full` 里抽：概念行先取「概念（X）」的 X，
       否则取第一句可读的命题陈述（截断到 `LABEL_FROM_STATEMENT_CHARS`）；
    3. 正文本身也抽不出（空正文，或者第一句还是工作名）⇒ 落成
       「<kind> 待命名（stmt:NNNNNN）」，并在读数里点名"原名不可用"。

    ## 返回
    `{"from", "to", "class", "why"}`：`from` 是交上来的原标签，`to` 是洗过的名字，
    `class` 点名触发的那一类（内部工作名 + 命中的类名；见 `LABEL_WORKING_NAME_RULES`），
    `why` 是一句人话 —— 静默改名是不许的，读的人要能看出"凭什么改"与"改成了什么"。
    """
    original = str(label or "")
    if not original.strip():
        return None
    rest, hits = _strip_working_names(original)
    if not hits:
        return None
    kept = _tidy_label(rest)
    if _brackets_balanced(original) and not _brackets_balanced(kept):
        # 命中的那段在括号里（路线 / 草稿状态那一类的落点）⇒ 交给模型洗名，这里不动它。
        return None
    classes = "、".join(dict.fromkeys(hits))
    if _readable_label(kept):
        to = _clip_label(kept)
        why = (f"标签里的内部工作名（{classes}）删掉之后还剩 {to!r} ⇒ 它就是名字"
               + ("（截断过）" if len(kept) > len(to) else ""))
    else:
        from_body = _first_readable_claim(statement_full, kind=kind)
        if from_body:
            to = from_body
            why = (f"整条标签都是内部工作名（{classes}），原名不可用 ⇒ "
                   f"从 statement_full 抽第一句可读的命题陈述当名字：{to!r}")
        else:
            tag = str(kind or "命题").strip() or "命题"
            to = f"{tag} 待命名（stmt:{str(stmt_id or '').strip() or '未发号'}）"
            why = (f"整条标签都是内部工作名（{classes}），而 statement_full 也抽不出可读的"
                   f"一句 ⇒ 原名不可用，名字待定：{to!r}")
    return {"from": original, "to": to,
            "class": f"{LABEL_WASH_WORKING}（{classes}）", "why": why}


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


def _dep_step_key(row: Mapping[str, Any]) -> tuple:
    """一条依赖边的身份（幂等判据：同一使用点 + 路径组 + 来源 ⇒ 同一条边）。

    为什么需要它：`dependencies` 没有"唯一键"这回事（一张账本表，允许同一对
    (使用点, 来源) 出现在不同路径组里 —— 多证明模型）。而"同一份手稿再携带一次"
    必须不重复落边，所以身份要按"这条边说的是什么"来算，不能按 `dep_id`（每次
    分配都会变）。

    ## `kind` / `label` 不算身份（2026-11-05 走查 D3）
    改前这两格也算进身份，于是同一条边经两路描述时会落两行：`derived_from`
    那一支（证明正文扫描）落 `kind=theorem, label="stmt:000000"`，稿里 `## 依赖`
    表那一支落 `kind=proposition, label="手稿依赖段（第 22 行）：…"` —— 两行的
    `used_by` / `path_group` / 来源号三格逐字相同，只有这两格不同。同一对
    (使用点, 来源) 图上是一条边："这条引用是定理还是命题"与"它被写成哪句话"
    都是这条边的描述，不是它的身份。收紧之后 `dependencies` 不再虚高，两条不同
    的边（来源号 / 路径组 / 使用点任一不同）仍然各占一行。
    """
    return (
        str(row.get("used_by") or ""),
        int(row.get("path_group") or 1),
        str(row.get("source_stmt_id") or ""),
        str(row.get("source_lit_id") or ""),
        str(row.get("source_experiment_id") or ""),
        str(row.get("source_doc_id") or ""),
    )


def _dep_ref(step: Mapping[str, Any]) -> str:
    """一条依赖步骤在读数里的指称（形如 `stmt:000777`）。

    为什么不能只读 `label`（2026-11-05 裁定 A 的读数面）：手稿依赖段那一路的 `label`
    是人读的"手稿依赖段（第 N 行）：…"（它要落进依赖行），而 `deps_dangling` 的 `ref`
    必须点名那个号 —— 从来源字段现算，读的人一眼看到是哪一条。前缀只从
    `schema.CITATION_PREFIXES` 反查（前缀只有一处声明），查不到就退回 `label`。
    """
    for _key, field, table, _idf, _dkind in STEP_SOURCE_KEYS:
        val = str(step.get(field) or "").strip()
        if not val:
            continue
        prefix = next((p for p, t in S.CITATION_PREFIXES.items() if t == table), "")
        return f"{prefix}:{val}" if prefix else val
    return str(step.get("label") or step.get("code") or "")


def _stmt_edge_count(steps: Any) -> int:
    """这一批依赖步骤里有几条是"命题→命题"（`source_stmt_id` 非空）。

    为什么要它（2026-11-05 缺陷 1c）：台账里"依赖边 N 条"与"其中命题→命题 M 条"是两个
    数。87 真机的 3 条边全是文献来的 —— N=3、M=0，而报告/回执里只有一个 N 时，
    "依赖面建起来了"与"一条命题→命题都没有"长得一模一样
    （`temp/dep_probe/REPORT-dependency-surface.md` 第三节 B 表：五区合计 3 行、
    `source_stmt_id` 非空 0 行）。
    """
    return sum(1 for step in (steps or ())
               if isinstance(step, Mapping)
               and str(step.get("source_stmt_id") or "").strip())


def _assign_path_group_in_tx(tx: Any, *, root: Any, statement_id: str,
                             manuscript: str = "", body_sha: str = "") -> dict:
    """在事务内分配「第几条证明路径」（业主口径：路径号归 B 的秘书）。

    唯一实现是 :func:`manuscriptpaths.assign_path_group`（同一命题已有 N 条 ⇒ N+1；
    同一份正文 sha / 同一份稿重复收录 ⇒ 沿用）。这里只做两件事：把它接到事务快照
    上（`store=tx` ⇒ 读的是这一笔锁里的 `dependencies`，不是锁外的另一份快照），
    并把读数原样回传。

    为什么必须传 `tx` 而不是 `self.store`：分配与写盘要在同一把锁里。传 store 时
    `path_reading` 读的是 `store.rows(...)`（锁外的缓存快照），两个并发收录会各自
    看到"N 条" ⇒ 都开 N+1（开两个同号路径）。传 `tx` 时读的是本事务的快照，
    且本事务已经持有 `statements` + `dependencies` 的锁。
    """
    from . import manuscriptsubmission as _MSUB

    sid = str(statement_id or "").strip()
    rel = str(manuscript or "").strip().replace("\\", "/")
    if not sid:
        return {"checked": False, "path_group": 1, "existing": False, "count": 0,
                "statement_id": "", "manuscript": rel, "body_sha": str(body_sha or ""),
                "paths": [], "problems": [],
                "why": "没有命题号 ⇒ 路径号分不了（新命题那一档由收录方给号后再分）"}
    got = dict(_MSUB.assign_path_group(
        store=tx, root=root, statement_id=sid, manuscript=rel,
        body_sha=str(body_sha or "")) or {})
    got.setdefault("statement_id", sid)
    got.setdefault("manuscript", rel)
    got.setdefault("body_sha", str(body_sha or ""))
    return got


def _existing_path_group_in_tx(tx: Any, *, root: Any, statement_id: str,
                               path_group: int, manuscript: str = "",
                               body_sha: str = "") -> dict:
    """核对「调用方点名的第 n 条路径」是不是已存在、且对得上这一份稿。

    优化线（业主 2026-11-12：「换正文只允许优化这条线去换。优化线需指明命题号和
    路径。」）显式带 `(命题号, 路径号)`；这一格不分配号，只在事务里核对：
    第 n 条路径不在册 ⇒ `path_not_found`；这一份稿已经绑在别的路径上 ⇒
    `path_mismatch`；对得上才把号回给调用方。号仍归秘书（这里没有分配动作）。

    三态：`checked=False` ⇒ 路径记录读不出来（不是「没有这条路径」）；`refused`
    非空 ⇒ 受控拒、一个字节都不写；`basis` 说明这一份稿是靠什么对上的
    （`path_manuscript` / `path_body_sha` / `signed_carrier`）。
    """
    from . import manuscriptpaths as _MP
    from . import verifications as _VR

    n = int(path_group or 0)
    sid = str(statement_id or "").strip()
    rel = str(manuscript or "").strip().replace("\\", "/")
    sha = str(body_sha or "").strip().lower()
    out: dict[str, Any] = {"checked": False, "path_group": n, "existing": False,
                           "basis": "", "paths": [], "refused": "", "reason": "",
                           "why": ""}
    if n < 1:
        out.update(refused="bad_path_group",
                   reason=f"路径号必须是正整数（收到 {path_group!r}）")
        return out
    if not sid:
        out.update(refused="bad_statement_id", reason="没有命题号 ⇒ 路径核对不了")
        return out
    reading = _MP.path_reading(tx, root, statement_id=sid)
    out["paths"] = [dict(one) for one in (reading.get("paths") or ())]
    if not reading.get("checked"):
        out.update(refused="path_group_unreadable",
                   reason=("路径记录读不出来 ⇒ 核不了第几条（不猜）："
                           + str(reading.get("why") or "未知原因")))
        return out
    hit = next((one for one in out["paths"]
                if int((one or {}).get("path_group") or 0) == n), None)
    if hit is None:
        out.update(checked=True,
                   refused="path_not_found",
                   reason=(f"第 {n} 条路径还没在册（路径号只能指已存在的路径；"
                           "新路径由秘书在收录事务里分配）"))
        return out
    out.update(checked=True, existing=True)
    # 路径身份不写稿头（业主：「路径在产出侧也不标注」），稿里也没有命题号
    # （业主 2026-11-13：「稿里没有命题号，任何稿里都没有命题号」）⇒ "这份稿属于
    # 哪条命题"只由逐路径记录与同号签行回答（下面两支），不读稿头。
    hit_rel = str(hit.get("manuscript") or "").strip().replace("\\", "/")
    hit_sha = str(hit.get("body_sha") or "").strip().lower()
    if rel and hit_rel and hit_rel == rel:
        out.update(basis="path_manuscript",
                   why=f"第 {n} 条路径的稿记录点名 `{rel}`")
        return out
    if sha and hit_sha and hit_sha == sha:
        out.update(basis="path_body_sha",
                   why=f"第 {n} 条路径的正文 sha 就是这一份")
        return out
    # ---- 第一轮优化：路径记录还指着 F/E 的源稿；这一份是新落的 B 改写稿 --------
    #
    # 路径身份不写稿头（业主：「路径在产出侧也不标注」），逐路径记录要等收录成功才
    # 绑上新稿。所以第一轮只能核对两件事：这一份稿的签行已经在（优化线要求先拿签）、
    # 且它没有被绑到别的路径上。第二轮起 `path_manuscript` 那一档会命中。
    try:
        rows, _bad = _VR.list_verifications(root, statement_id=sid, limit=None)
    except Exception:  # noqa: BLE001 —— 读不到签行就按"对不上"受控拒（不猜）
        rows = []
    bound_elsewhere = 0
    signed_here = False
    for one in rows or ():
        doc = dict(one or {})
        rec = str(doc.get("manuscript") or doc.get("object_path") or "").strip().replace("\\", "/")
        row_sha = str(doc.get("proof_sha256") or "").strip().lower()
        try:
            row_group = int(doc.get("path_group") or 0)
        except (TypeError, ValueError):
            row_group = 0
        if rel and rec == rel:
            if row_group >= 1 and row_group != n:
                bound_elsewhere = row_group
            if sha and row_sha == sha:
                signed_here = True
        elif sha and row_sha == sha and row_group >= 1 and row_group != n:
            bound_elsewhere = row_group
    if bound_elsewhere:
        out.update(refused="path_mismatch",
                   reason=(f"这一份稿已经绑在第 {bound_elsewhere} 条路径上，"
                           f"不是第 {n} 条 ⇒ 不改写"))
        return out
    if signed_here:
        out.update(basis="signed_carrier",
                   why=(f"第 {n} 条路径在册；这一份稿是它有签的改写载体"
                        "（逐路径记录要等这一笔收录成功后才绑上新稿）"))
        return out
    out.update(refused="path_mismatch",
               reason=(f"第 {n} 条路径的稿记录是 `{hit_rel or '（没有稿）'}`"
                       f"（正文 sha {hit_sha[:12] or '无'}…），而这一份是 "
                       f"`{rel or '（没有稿）'}`（{sha[:12] or '无'}…）⇒ 对不上。"
                       "这一份稿要先拿 V 签，再按它自己那条路径回填"))
    return out


def _path_material_numbers(groups: Any) -> list[int]:
    """依赖组里"材料说这是第几条路径"的那几个号（手稿依赖表第 4 列 / 显式给的组号）。

    它们只是材料：产出侧 / 调用方可以写，但最终号由秘书在收录事务里分配。两者
    不一致时由调用方把读数记进 `path_group_material`（"材料说 X、秘书定为 Y"），
    不静默丢掉材料那一份说法。
    """
    seen: set[int] = set()
    for group in (groups or ()):
        for step in (group or ()):
            try:
                no = int(step.get("path_group") or 0)
            except (TypeError, ValueError):
                continue
            if no >= 1:
                seen.add(no)
    return sorted(seen)


def _note_path_material(out: dict, material: list[int], *, decided: int) -> None:
    """材料号与秘书定的号不一致 ⇒ 在回执里点名（读的人要看得出"谁说了算"）。"""
    if not material or all(int(x) == int(decided) for x in material):
        return
    out["path_group_material"] = {
        "material": [int(x) for x in material],
        "secretary": int(decided),
        "why": (f"材料说 {[int(x) for x in material]}、秘书定为 {int(decided)}"
                "（最终号以秘书分配为准；材料只作参考）"),
    }


def _stamp_path_number(steps: Any, *, path_group: int, proof_no: int,
                       single_group: bool = True) -> list[dict]:
    """把秘书分到的号盖到已解析的依赖步骤上（返回新列表，不改调用方那份载荷）。

    两格各管一件事（`_write_dep_steps` 的同一口径）：
    - `proof_no` ⇒ `used_by` 的 `#pN` 尾巴 = "这条依赖出自第几份证明正文"；
    - `path_group` ⇒ 那一列 = "同一份证明里的第几条可选路径"。

    什么时候盖 `path_group`：只有"这一份稿 = 这一条路径"（`single_group`）时才盖。
    载荷显式交了二维 `deps`（外层 = 可选路径、内层 = 一步）时，那几个组号是调用方
    对"一份证明里有几条可选路径"的声明，不是"第几份证明" —— 盖成分配号会把两条
    可选路径并成一条（`test_b_hands_content_to_the_secretary` 钉住它）。同理，
    证明正文里分段扫出来的那一路（`_from="proof_scan"`）保留段落下标（1/2…）。
    """
    out: list[dict] = []
    for step in (steps or ()):
        one = dict(step)
        if single_group:
            one["proof_no"] = int(proof_no)
            if str(step.get("_from") or "") != "proof_scan":
                one["path_group"] = int(path_group)
        out.append(one)
    return out


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
                    "quote": str(st.get("quote") or ""),
                    #: 这一步从哪来：`proof_scan` = 证明正文里扫出来的（一份证明里的
                    #: 第几条可选路径），其余 = 手稿依赖段 / 调用方显式给的（一份稿 =
                    #: 一条路径）。收录时按这条痕迹决定"路径号盖哪一格"。
                    "_from": str(st.get("_from") or "")}
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


#: 转发台账（append-only，一行 = 一次秘书转发或一次链尾交付）。
#:
#: 为什么不写进各自的 `decisions` 台账：链式转发是"一条消息走过几个秘书"这一件事，
#: 摊进 N 份按角色/实例分片的决定台账之后，读的人要 glob 整个目录再按时间拼起来
#: —— 而"每一位秘书都真的收到过一次转发"必须能一次读出来（业主的判据 a 就是它）。
#: 落点与决定台账同一个目录：`out/secretary/relay.jsonl`（`webui` 的目录 glob 认
#: `*.jsonl`，同目录会让它进"秘书台账"那一面 —— 转发记录本来就是秘书留痕）。
RELAY_LEDGER = "relay.jsonl"
#: 转发编号前缀（由 `append_jsonl_stamped` 在锁内发号；同一条消息的每一跳共用一个号，
#: 回执沿链回传时靠它把 N 跳认成同一次转发）。
RELAY_ID_PREFIX = "R-"


def relay_path(root: str | Path) -> Path:
    """转发台账的落点：`out/secretary/relay.jsonl`。"""
    return Path(root).joinpath(*SECRETARY_DIR, RELAY_LEDGER)


# ---------------------------------------------------------------- 发出口：内容与收件面相符吗
#
# 业主原话（2026-10-26，逐字）：「秘书处理将发出的信息时，要看内容是否与接受面相符，这条显然
# 该拆两条单独派活，这是秘书没有意识，未向 M 提醒」。
#
# 现场（`projects/mp3-r3` 的真机手稿 000000）：一条 `handoff(to=ALL)` 的正文里装着两件派活
# （给 A、给 D），秘书照发 —— 而同一段内容若走 `message` 会被 `public_is_not_a_conversation`
# 拒（公告栏里点名 + 指令语气），`handoff` 这条路不过那道判据 ⇒ 换个通道就绕过去了。
#
# 这里加的不是一套新码、也不是一条新通道：判断落在秘书本来就有的发出口
# （:meth:`Secretary.optimize_outbound` + :meth:`Secretary.note_decision` 那一条
# `secretary_decision` 台账），用的也是既有码（`invalid_params` 与
# `public_is_not_a_conversation`）；名册与公告那两条判据本体由调用方注入
# （与 `admission=message_admission` 同一种做法，本文件不抄第二份）。

#: 「这一条在讲派活」的机械线索词（受控词表，只有一个取值）。
DISPATCH_VERB = "派活"

#: 「点名之后跟一句说明」的括号写法（派活清单在正文里就是这种形态）。
_TARGET_OPENERS: dict[str, str] = {"（": "）", "(": ")", "【": "】", "[": "]", "〔": "〕"}

#: :func:`dispatch_targets` 认的两条线索名（进读数：判据要能回答"凭什么说它是派活对象"）。
CLUE_VERB = "紧跟派活动词"
CLUE_NOTE = "名字后跟一句括注"

#: 内容与收件面不符时那一行台账的结论。沿用 `DECISIONS` 里既有的两档，不新造词：
#: 一份稿子里装了多件派活 ⇒ 建议按收件人重排；公告里点名并下指令 ⇒ 建议改派成私聊。
DECISION_REARRANGE = "建议重排"
DECISION_READDRESS = "建议改派"


def _dispatch_clue(body: str, token: str) -> tuple[int, str]:
    """这个写法在正文里有没有落在"派活对象"位置上的形态；返回 `(第一次命中的下标, 线索名)`。

    整词判据：左右不许再粘 ASCII 字母/数字/下划线（`A1` 里的 `A`、`ACC` 里的 `A` 都不算命中，
    否则正文里每一个 `A` 都会变成"点名"）。两条位置线索（任一成立即可）：

    - :data:`CLUE_NOTE`：名字后面紧跟一个括注，且括注里不是空的（`A（派活：检索文献）`）；
    - :data:`CLUE_VERB`：名字紧跟在「派活」/「派给」后面（可带「给」与冒号，`派活：A`）。

    没有命中返回 `(-1, "")`。
    """
    want = str(token or "")
    if not want:
        return -1, ""
    pattern = re.compile(r"(?<![0-9A-Za-z_])" + re.escape(want) + r"(?![0-9A-Za-z_])")
    for hit in pattern.finditer(body):
        start, end = hit.span()
        j = end
        while j < len(body) and body[j] in " \t\u3000":
            j += 1
        if j < len(body) and body[j] in _TARGET_OPENERS:
            close = body.find(_TARGET_OPENERS[body[j]], j + 1)
            note = body[j + 1: close if close >= 0 else len(body)]
            if note.strip():
                return start, CLUE_NOTE
        if re.search(r"(?:派活|派给)\s*给?\s*[:：]?\s*$", body[:start]):
            return start, CLUE_VERB
    return -1, ""


def dispatch_targets(text: Any,
                     members: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """正文里被点名、且落在"派活对象"位置上的那些名册成员（确定性：不调模型、不花钱）。

    ## 判据（三条，全部机械可判）
    1. 正文里出现 :data:`DISPATCH_VERB`（「派活」）—— 没有这个字样，这一段就不当派活清单读；
    2. 名册成员的三种写法各算一种指称：名册名 / 绝对编号 / 角色代号（`A`…`M`），整词匹配
       （判据见 :func:`_dispatch_clue`）；
    3. 命中的位置还必须落在"派活对象"的位置上（:data:`CLUE_NOTE` 或 :data:`CLUE_VERB`）。

    返回按第一次出现排序的 `[{key, token, name, role, kind, clue, at}]`；`key` 是成员身份
    （`task_id` 优先），同一成员的两种写法（`A1` 与角色代号 `A`）折成一个对象 ——
    于是"同一件事写了两遍"不会被数成两件派活。

    角色代号那一格要单独说一句：同一个角色在名册上有两个实例（`A1` / `A2`）时，正文里的
    `A（派活：…）` 指的不是某一个实例 —— 它折成 `role:A` 这一个指称。不这么折的话，
    一个 `A（…）` 会被数成两个对象（每个 A 实例各算一个），于是一次正常的派活被误拒。

    ## 误判方向（写在这里，因为这条判据靠结构线索，不靠语义）
    - 漏判（宁漏不误拒的那一侧）：正文用散文写的（"这两件事分别交给检索组与研究组"）、
      或只写"派 B 去查"而不出现「派活」/「派给」的，判不出来 —— 这一格不猜语义。
    - 误判：一条真正的公告若逐个点名并各带一句括注（"这一轮 A（查文献）、D（做分析）各干一段"），
      而正文别处又出现了「派活」两个字，会被读成两件派活 ⇒ 退回本体。方向是有意的：
      这条闸的处置只是"按收件人拆开重发一步"，代价一步；而放过去一次就是一次
      "一条稿子里塞几件活"的静默越界（业主点名的正是那个形态）。
    - 名册读不成（`members` 是空表）⇒ 返回空表：那是"这一格没查成"，由调用方按三态处理，
      不许当成"已经相符"。
    """
    body = str(text or "")
    if DISPATCH_VERB not in body:
        return []
    rows = [dict(m) for m in (members or ()) if isinstance(m, Mapping)]
    by_key: dict[str, dict[str, Any]] = {}
    #: `(写法, 指称键)`：名册名 / 绝对编号各指一个成员；角色代号按"同角色是否唯一"折
    #: （见 docstring 里那一句）。
    tokens: list[tuple[str, str]] = []
    role_keys: dict[str, list[str]] = {}
    for m in rows:
        key = str(m.get("task_id") or m.get("name") or m.get("role") or "")
        if not key:
            continue
        by_key.setdefault(key, m)
        for token in (str(m.get("name") or ""), str(m.get("task_id") or "")):
            if token:
                tokens.append((token, key))
        role = str(m.get("role") or "")
        if role:
            role_keys.setdefault(role, []).append(key)
    for role, keys in role_keys.items():
        tokens.append((role, keys[0] if len(keys) == 1 else f"role:{role}"))
    hits: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for token, key in tokens:
        if (token, key) in seen:
            continue
        seen.add((token, key))
        at, clue = _dispatch_clue(body, token)
        if not clue:
            continue
        m = by_key.get(key) or {}
        hits.append({"key": key, "token": token, "at": at, "clue": clue,
                     "name": str(m.get("name") or ""),
                     "role": str(m.get("role") or ""),
                     "kind": str(m.get("kind") or "")})
    hits.sort(key=lambda t: (int(t.get("at") or 0), t["key"]))
    found: list[dict[str, Any]] = []
    taken: set[str] = set()
    for hit in hits:
        if hit["key"] in taken:
            continue
        taken.add(hit["key"])
        found.append(hit)
    return found


#: 稿头元信息行：`- <键>：<值>`（与 `manuscriptintake._HEAD_FIELD_RE` 同一形状）。
_MANUSCRIPT_HEAD_FIELD_RE = re.compile(r"^\s*-\s*(?P<key>[^：:]+?)\s*[：:]\s*(?P<value>.*?)\s*$")


def _manuscript_head_fields(text: Any) -> dict[str, str]:
    """稿头（第一个 `##` 之前）的 `- 键：值` ⇒ `{键: 值}`（只读；不猜、不去重语义）。

    为什么放在秘书层：`extract_manuscript` 要把稿头那几格（实验号 / 命题键 /
    命题类型）一并带给调用方，而"B 本体不自己读稿"这条边界不许在这里破例 —— 所以
    切稿头的实现只有这一处，键名的解释由调用方按用途读。
    """
    out: dict[str, str] = {}
    for line in str(text or "").split("\n"):
        if line.strip().startswith("##"):
            break
        matched = _MANUSCRIPT_HEAD_FIELD_RE.match(line)
        if not matched:
            continue
        key = matched.group("key").strip()
        if key and key not in out:
            out[key] = matched.group("value").strip()
    return out


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
        # ---- 装配期类型闸（`AGENTFLOW_STRICT_SEAM=1` 时生效；默认关）
        #
        # 为什么在这里也接一道：`Secretary(..., seam=_Seam())` 是彩排最常见的一种
        # 「构造期直接替换」——静态扫描看不见，三格也没有对象。判据本体只有一处
        # （`llmseam.assert_real_seam`），这里只报出「是谁收到的」。
        from .llmseam import assert_real_seam

        assert_real_seam(seam, where="Secretary.__init__(seam=...)")
        self.log = log
        self.deadline_sec = float(deadline_sec)
        #: 同一命题 / 同种证明的两个阈值。可注入的理由：这两条判据的
        #: 松紧是口径问题，不是实现问题 —— 不同工作区的表述习惯不同（带
        #: 长尾注的登记与短句式的登记），阈值该能被一次实验性调参改掉，而不必改代码。
        self.same_proposition_jaccard = float(same_proposition_jaccard)
        self.proof_same_jaccard = float(proof_same_jaccard)
        #: 会话号（花销归因要读 `llm_call` 事件；`None` = 缺省会话，与 `llmseam` 同一口径）。
        self.sid = sid
        #: 判断类要不要真发一次模型调用。
        #: 关着的时候 :meth:`judge` 仍然返回三态中的"没查成"（`checked=False` + 理由），
        #: 于是"判断没做"与"判断过了、可派"在台账上永远分得开。
        #:
        #: 生产装配由 `agent_loop._secretary_for` 打开它。
        #: 那一口还会按配置换一把 key：设置文件里配了
        #: `secretary` 档 ⇒ 秘书走全角色共用的那一档模型
        #: （`llmseam.LlmSeam.for_secretary`）；没配 ⇒ 退回本体那一个缝。
        self.enable_model = bool(enable_model)
        #: 秘书这一趟的模型是从哪一档来的（读数：`secretary（…）` / `body（…）`）。
        #: 它回答"这次判断花的是共用那把 key，还是本体那把" —— 而这正是
        #: 「所有智能体的秘书另外共用一个 api key」是否生效的唯一机器读数。
        self.model_source: str = ""
        #: 写集的声明式落点：它让"秘书有没有写集、写哪几张表"成为一个可读的事实，
        #: 而不是"读遍本文件找不到 store.tx 所以大概没有"。
        #: 不是空集：B 的写入代理要落 `statements`（含概念行）与 `dependencies`，
        #: 只走 :meth:`record_statement` 一处。
        self.writes: frozenset[str] = frozenset(STATEMENT_WRITE_TABLES)
        #: 最近一次销号名单读数（由 :meth:`retired_ledger` 写）。
        #:
        #: 为什么单列一格：`retired_names` 只回 `(行, 坏行)`、`_is_retired` 只回一个布尔，
        #: 于是"这一份读不全"（认不出来的行 / 整份读不出来 / 不可信的分片）在任何返回值上
        #: 都无处可报，被读成"没销号"。
        #: 形状见 :meth:`retired_ledger` 的返回值；它是读数，不是判据。
        self.last_retired_ledger: dict[str, Any] = {}
        self._negotiations: list[dict[str, Any]] = []
        #: 这个秘书服务的实例（台账号）。由 `bind_task` 在循环开跑时绑上：
        #: 绑上之后台账分片到 `out/secretary/<role>-<task_id>.jsonl`，于是同角色的并发实例
        #: 各写各的片（今天只有角色维度 ⇒ 两个 D 实例会把记录写进同一个文件，读的人分不出是谁）。
        self.task_id: str = ""
        #: 最近一次判断的墙钟（秒）—— 读数，不是判据（fail-open 的代价要看得见，
        #: 但不许拿它去卡任何一条委托）。
        #:
        self._last_judge_elapsed = 0.0
        #: 入库审美的同题不重判表。
        #:
        #: 判断的对象只有那段文本（加一句自证不平凡的说明），所以同一份文本问第二遍不会
        #: 有别的结论 —— 记下来，省掉那几次模型调用，也让"再交一遍"这件事在读数上立刻
        #: 变便宜且答案不变（于是没有理由反复试）。
        #:
        #: 键 = `(statement_full, why_this_is_not_trivial)` 的摘要；值 = 第一次的结论。
        #: 只记 `checked=True` 的结论：没查成（没缝 / 超时 / 坏 JSON）不许缓存 ——
        #: 那会把"这一次没查成"变成"以后都别查了"，而缝是可能好起来的。
        self._statement_verdicts: dict[str, dict[str, Any]] = {}
        #: 命题同一性的同题不重判表。
        #:
        #: 键 = 命题正文的 sha256（见 `_proposition_verdict_key`）；值 = 第一次的判定。
        #: 这一层只是进程内的快表：盘上那份 append-only 台账
        #: （`out/secretary/proposition_verdicts.jsonl`，见 `proposition_verdict_of`）才是
        #: 跨进程/跨趟的缓存 —— 没有盘上那一份，"同一条正文第二次进来不再花钱"这句话只在
        #: 同一个秘书实例活着的时候成立。
        self._proposition_verdicts: dict[str, dict[str, Any]] = {}
        #: 工具面真名表的缓存。`registry=None` 那一档的兜底是
        #: `build_registry(store=...)` —— 装配一整套工具要十几毫秒，而 `prescreen`
        #: 每次委派都问一遍。
        #: 工具面是静态的（`tools/_MODULES` 那张表在进程内不变），所以这份名单
        #: 只缓存"读成功了"的那一次；空表（读不成）不缓存 —— 那会把"这一次没读成"
        #: 变成"以后都没有真名"，而三态纪律不许这么折。
        self._tool_names_cache: list[str] | None = None

    # ------------------------------------------------------------ 台账（E 类：记录）

    def bind_task(self, task_id: str) -> None:
        """把这一名秘书绑到它服务的实例上。绑上之后台账分片。

        为什么必须有这一步：秘书的台账若只有角色维度
        （`out/secretary/<role>.jsonl`），同角色的并发实例（`summon_many` 的多 `instance`）
        会写进同一个文件 —— 读的人分不出哪一行是哪一个代理写的。
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
        # 2026-10-27：兜底那一支要现造一整套工具（实测 12 ms/次），而工具面是静态的
        # （`tools/_MODULES` 在进程内不变）⇒ 读成功那次的名字表留在本实例上。
        # 只缓存非空结果：空表 = "这一格没读成"，缓存它会把一次失败变成永久没有真名。
        cached = self._tool_names_cache
        if cached is not None:
            return list(cached)
        try:
            from .tools import build_registry

            names = sorted(str(x) for x in build_registry(store=self.store).registry.names())
        except Exception:  # noqa: BLE001 - 造不出来 ⇒ 空表（"没读到"不许读成"没有真名"）
            return []
        if names:
            self._tool_names_cache = list(names)
        return names

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

    def _judge_core(self, kind: str, context: Mapping[str, Any], *, task_id: str = "",
                    note: str = "") -> dict[str, Any]:
        """判断类的内核：用本智能体自己的缝做一次模型调用，不写任何台账。

        ## 为什么把"判"与"记"拆开（业主 2026-11-13 裁定 Q5）
        有的判断只该落一本轴台账（`judge_dispatch_fit` → `out/secretary/dispatch_fit.jsonl`），
        不该再往角色台账（`out/secretary/<role>.jsonl`）里抄一行 —— 双写就是"同一件事两个
        落点"，读的人分不清哪一本算数。拆法只有一种：判据、词表校验、三态全在本方法
        （一处实现），谁记账由调用方决定（:meth:`judge` 记角色台账；`judge_dispatch_fit`
        记轴台账）。判据不允许复制第二份。

        `note` 是这一次调用的读数目（缺省 `secretary:<kind>`）：同一类判定有两问
        （挑词 / 认定）时，读数要分得开哪一问花的那一笔钱。判据本身仍按 `kind`。

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
            # ---- 2026-10-26（真机 sylow5）：这一句必须把"缝从哪来"的读数一并带出来。
            #
            # 改前它只说"没有装配模型缝"，而全仓五个构造点一个都没传 `seam=` ⇒
            # 命题同一性判定这一整条链在真机上一次都没发生过，没人能从返回值里看出
            # "这不是判过了、是根本没判"。装配读数（`model_source`）现在由
            # `for_role_wired` 写在秘书身上：`none（秘书那一档没有配模型 key …）`。
            why = "没有装配模型缝（本智能体自己的 llmseam）⇒ 这一格没查成"
            if str(self.model_source or ""):
                why = f"{why}（装配读数：{self.model_source}）"
            # `_no_ledger`：这一档不落角色台账（与改前逐字相同 —— 没缝是装配
            # 事实，`model_source` 已经记了；把这一趟的材料再 dump 一遍既没信息量，
            # 材料里带环时还会抛 `Circular reference detected`，见
            # `tests/test_secretary_noise.py::test_assess_delegation_survives_noise`）。
            return {"checked": False, "reason": why, "_no_ledger": True,
                    "cost": {"ledger": "", "reason": "没发调用（没有缝）"}}
        if not self.enable_model:
            return {"checked": False, "_no_ledger": True,
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
                                            task_id=task_id,
                                            note=note or f"secretary:{kind}")
        except Exception as exc:  # noqa: BLE001 - fail-open：超时/出错 ⇒ 没查成 + 留痕
            return {
                "checked": False, "reason": f"调用失败：{type(exc).__name__}: {exc}",
                "cost": self.last_judge_cost(kind)}
        finally:
            self._last_judge_elapsed = round(time.monotonic() - t0, 3)
        cost = self.last_judge_cost(kind)
        if not getattr(call, "ok", False) or data is None:
            return {
                "checked": False,
                "reason": f"没查成（{getattr(call, 'problem', '') or 'no_reply'}）："
                          f"{str(getattr(call, 'detail', '') or '')[:200]}",
                "cost": cost}
        raw_decision = data.get("decision")
        decision = str(raw_decision or "").strip()
        allowed = JUDGE_VERDICTS[kind]
        # ---- 2026-11-01（业主裁定：审美轴三格退场，判档那一问只剩 T0–T4）
        #
        # 三态（盘上必须分得开，见 STATEMENT_VERDICTS 的注释）：
        #   档位   ⇒ decision = "T0".."T4"（原样带下去，不再回写成旧词）；
        #   判不了 ⇒ decision 键在、值 null ⇒ checked=True + nontriviality=None；
        #   没查成 ⇒ checked=False（没缝 / 超时 / 坏 JSON / 词表外）。
        # 旧词（合格 / 太平凡 / 判不了）在这一层不采信：旧行只在读台账时折算
        # （`_tier_from_legacy_decision`），写侧与新行一个字都不再产生它们。
        # 2026-11-01（第二刀）：判档只有两态 —— 有 T0..T4，或者没拿到可用判定。
        # null / 旧词 / 坏 JSON 一律走"没查成"（checked=False），不落档位行：
        # "判不了"不是第四档，是我们没拿到判定（处置是重试 / 重交 / 人看）。
        if (decision not in allowed
                and (kind != "statement_aesthetic"
                     or _nontriviality_level(decision) is None)):
            if kind == "statement_aesthetic":
                why = (f"模型没给出可用判定（decision={raw_decision!r}）：档位只认 "
                       f"{list(allowed)} ⇒ 这一格没查成")
            else:
                why = f"模型给的结论 {decision!r} 不在 {kind} 的词表 {list(allowed)} 里 ⇒ 不采信"
            return {"checked": False, "reason": why, "cost": cost}
        level = _nontriviality_level(decision) if kind == "statement_aesthetic" else None
        if level is not None:
            # 容忍模型把档位给成 2 / "2"（老形状）：台账与读侧一律写 "T2"，不写数字串。
            decision = nontriviality_label(level)
        out = {
            "checked": True, "decision": decision,
            "reason": str(data.get("reason") or "")[:500],
            "basis": [str(x) for x in (data.get("basis") or [])][:5],
            "elapsed_sec": self._last_judge_elapsed, "cost": cost}
        if kind == "statement_aesthetic":
            # 档位就是 `decision` 本身（一根轴一个字段）。这里把它作为派生读数带回
            # （`judge_statement` 与旧替身都读这一格），不再单独向模型要第二个字段 ——
            # 两个字段就是"同一件事两个名字"。
            out["nontriviality"] = level
            out["nontriviality_basis"] = str(data.get("nontriviality_basis") or "")[:500]
        if kind == "v_reply_defect":
            # ---- 判 fault 而 V 没给步号时，由秘书定出那一步 ----------------
            #
            # 判 fault 而 V 没给 defect_step ⇒ 秘书定出那一步。所以这一问要多要一格；
            # 取值只有两种：正整数（指到 V 回复里
            # 说的那一步）或 null（这一档不是按步号定位的）。坏值一律 null —— 不猜。
            raw_step = data.get("defect_step")
            step: int | None = None
            if isinstance(raw_step, int) and not isinstance(raw_step, bool) and raw_step >= 1:
                step = raw_step
            out["defect_step"] = step
            out["defect_step_basis"] = str(data.get("defect_step_basis") or "")[:500]
            # ---- D3 批 2：两格新的读数（只解析、不在这里定轴） ------------------
            #
            # `defect_kind`：判 fault 时 fault 的内容是哪一类；`report_gap`：判
            # 「没问题」时那份报告缺了什么记录（裁定 ①：它不是判据）。两格都只做
            # 形状归一（字符串、截断），语义归类在 `v_reply_fault_reading` 一处。
            out["defect_kind"] = str(data.get("defect_kind") or "").strip()[:40]
            out["report_gap"] = str(data.get("report_gap") or "").strip()[:500]
        if kind == "proposition_identity":
            # ---- 同一趟判断的第二组输出。
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
        if kind == "proof_kind":
            # 判 same 时模型要指到"哪一条在册路径"（拒信点名第 N 条）；坏值不采信，
            # 由调用方退回"第一条在册路径"（仍然拒收，不猜一条不存在的号）。
            try:
                out["same_path"] = int(data.get("same_path") or 0)
            except (TypeError, ValueError):
                out["same_path"] = 0
        return out

    def judge(self, kind: str, context: Mapping[str, Any], *, task_id: str = "",
              note: str = "") -> dict[str, Any]:
        """判断类：一次模型调用（判据与三态全在 :meth:`_judge_core`）＋ 落角色台账。

        这一层只做"记账"这一件事：`_record_judge` 把结果写成 `out/secretary/<role>.jsonl`
        的一行（花销归因与三态都在那里完整）。只落轴台账的那几问
        （:meth:`judge_dispatch_fit`）直接调 `_judge_core`、不经过这里 —— 判据只有
        一份，双写（角色台账 + 轴台账）是业主 2026-11-13 裁定 Q5 明确不要的形态。
        """
        result = self._judge_core(kind, context, task_id=task_id, note=note)
        if result.pop("_no_ledger", False):
            # 「没缝 / 开关关着」不落角色台账 —— 这一档与改前逐字相同（不是判定，
            # 是装配事实；`model_source` 已经记了它）。见 `_judge_core` 那一支。
            return result
        return self._record_judge(kind, context, result)
    def judge_dispatch_fit(self, *, task: str, to: str = "F", action: str = "",
                           params: Mapping[str, Any] | None = None,
                           task_id: str = "") -> dict[str, Any]:
        """D 的秘书专属：这一条派给 F 的活是不是一个研究方向（业主 2026-11-13）。

        业主原话（逐字）：

        > 「plan由F自己决定，所以D不可能做出按plan个数派F，于是D只能按研究方向开多个F
        >   而非把一堆方向委托给一个F（这里D秘书要审D的派活，不合适需要给出提醒）。」

        ## 它判什么、不判什么
        - 判：方向个数 —— 这一条派活交给 F 的是一件事，还是几件互不相干的事
          （或一张"计划列表 / 进度督办"，而 plan 由 F 自己决定）。
        - 不判：难不难 / 值不值得做 / F 能不能证出来（研究判断），也不判 F 该开几条计划。
        - 不用词面线索代替判断：一次模型调用，没有关键词表、没有字数阈值。

        ## 三态与"只提醒不拦"
        | 结局 | 返回 |
        |---|---|
        | 判了 | `{"checked": True, "verdict": "是一个方向"|"不是一个方向", "why", "basis", "cost"}` |
        | 判不了 | `{"checked": False, "verdict": "", "why": …}`（没缝 / 关着 / 超时 / 坏 JSON / 词表外） |
        调用方（:meth:`assess_delegation`）只在 `checked=True` 且
        `verdict==DISPATCH_FIT_UNSUITABLE` 时把结论并进建议与提醒正文 ——
        不改派活本身（业主：「不合适需要给出提醒」，不是拒收）。

        ## 台账（Q5：只落一本）
        走 :meth:`_judge_core`（判据与三态只有那一处），结果落
        `out/secretary/dispatch_fit.jsonl`（读侧 :func:`dispatch_fit_rows`），
        不写角色台账 —— 双写就是同一件事两个落点。
        """
        material = {"to": str(to or ""), "action": str(action or ""),
                    "task": str(task or "")[:JUDGE_MATERIAL_CAP],
                    "params": dict(params or {})}
        result = self._judge_core("dispatch_fit", material, task_id=task_id,
                                  note="secretary:dispatch_fit")
        checked = bool(result.get("checked"))
        verdict = str(result.get("decision") or "") if checked else ""
        why = str(result.get("reason") or "")
        root = str(getattr(self.store, "root", "") or self.root or "")
        row = append_dispatch_fit(
            root, to=to, task=task, checked=checked, verdict=verdict, why=why,
            basis=[str(x) for x in (result.get("basis") or [])],
            # 没查成时台账那一栏写 `没查成`（不是"合适"）——三态纪律。
            decision=str(result.get("decision") or _JUDGE_UNDECIDED["dispatch_fit"]),
            cost_ledger=str((result.get("cost") or {}).get("ledger") or ""),
            role=str(self.role), task_id=str(task_id or self.task_id or ""))
        return {"checked": checked, "verdict": verdict, "why": why,
                "decision": str(result.get("decision") or ""),
                "basis": [str(x) for x in (result.get("basis") or [])],
                "cost": dict(result.get("cost") or {}), "at": str(row.get("at") or "")}

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
        # 没判成时写哪个词：按类别（`_JUDGE_UNDECIDED`）。缺省仍是派活那一轴的
        # "建议重排"（历史读数逐字不变）；V 的两类与判档那一问写"没查成" —— 对它们写
        # "建议重排"是一句假话（它们里没有"重排"这件事）。
        #
        # 2026-11-01（第二刀）：判档只有两态，`checked=True` 时 `decision` 必然是
        # `"T0"`…`"T4"`；"没拿到判定"走 `checked=False`，落到这里的缺省"没查成"。
        self.note_decision(
            duty=2, kind=KIND_DECISION,
            decision=str(result.get("decision") or _JUDGE_UNDECIDED.get(kind, "建议重排")),
            reason=str(result.get("reason") or ""),
            basis=basis, target={"judge": kind}, judge=result,
            before=json.dumps(dict(context), ensure_ascii=False, sort_keys=True,
                              default=str)[:2000],
            fail_open=False,
        )
        return result

    def judge_proposition_form(self, *, statement_full: str, label: str = "",
                               kind: str = "", proof_text: str = "",
                               task_id: str = "", stmt_id: str = "") -> dict[str, Any]:
        """F 的秘书专属：这条命题描述有没有明确「从什么条件导出什么结论」。

        业主 2026-11-07 逐字：

        > 「命题登记时需过 F 秘书闸，审查命题描述是否规范，是否明确了从什么条件导出什么结论」

        ## 它判什么、不判什么（两根轴必须分开）
        - 判：这段描述的形状 —— 前提写得出来吗？结论是一个可判真假的断言吗？
          二者由"若…则…/设…则…"一类结构连起来了吗？有没有把作业/验收规格
          （"本轮产物必须是 proof"、"判据是 `manuscript_published=true`"、
          "原样提交 `reports/xxx.md`"）写成一条命题？
        - 不判：它对不对（那是 V 的轴，`verify.verify_proof`）、它是否平凡/是否已知
          （那是 `judge_statement` 的非平凡性轴）。两根轴混进同一格就是本仓反复踩过的
          "同一件事两个名字"。
        - 不用词面阈值代替判断（业主明确不要机械判据）：这里一次模型调用，没有
          关键词表、没有字数阈值。

        ## 返回（键集合固定）

        | 键 | 意思 |
        |---|---|
        | `checked` | 这一问有没有真的判成（没缝 / 关着 / 超时 / 坏 JSON / 词表外 ⇒ False） |
        | `well_formed` | 两态，没有第三档：`True` 形状合规 / `False` 不合规（只在 `checked=True` 时有意义） |
        | `conditions` | 它读出来的前提（字符串；合格时不许为空） |
        | `conclusion` | 它读出来的结论（字符串；合格时不许为空） |
        | `problems` | 逐条说缺什么（合格时为空；不合格时必须非空） |
        | `decision` | 一句话判词 |
        | `refused` | 受控码（`checked=False` 或 `well_formed=False` 时非空） |

        ## 三态（本仓最贵的那条纪律）
        `checked=False` 不是"没毛病"：调用方（F 的交稿那一步）必须 fail-closed
        当受控拒处理 —— 否则"今天没判成"会被读成"今天放行了"。

        ## 缓存
        按命题正文的 sha256 命中本台账（`out/secretary/proposition_form.jsonl`）：
        同一条正文重交一次不重复花钱，命中的结论原样带回（`cached=True`）。
        "没查成"的行不缓存（缝可能好起来，与 `proposition_verdict_of` 同一条纪律）。
        """
        out: dict[str, Any] = {
            "checked": False, "well_formed": False, "conditions": "", "conclusion": "",
            "problems": [], "decision": "", "refused": "", "reason": "", "cached": False,
            "cost": {}, "material": {}, "statement_sha256": "", "role": str(self.role),
        }
        body = str(statement_full or "")
        if not body.strip():
            out.update(refused=EMPTY_STATEMENT_TEXT,
                       reason=("这一条没有命题正文（0 字）⇒ 没有可判的对象："
                               "不进形态判定，不发调用"))
            return out
        root = str(getattr(self.store, "root", "") or self.root or "")
        key = _proposition_verdict_key(body)
        out["statement_sha256"] = key
        if root:
            cached = proposition_form_of(root, statement_full=body)
            if cached and cached.get("checked"):
                out.update(checked=bool(cached.get("checked")),
                           well_formed=bool(cached.get("well_formed")),
                           conditions=str(cached.get("conditions") or ""),
                           conclusion=str(cached.get("conclusion") or ""),
                           problems=[str(x) for x in (cached.get("problems") or [])],
                           decision=str(cached.get("decision") or ""),
                           cached=True,
                           reason=f"命中台账里那一次判定（{cached.get('at') or ''}）")
                if not out["well_formed"]:
                    out["refused"] = PROPOSITION_FORM_REFUSED
                return out
        if self.seam is None or not self.enable_model:
            # fail-closed：没有判断面 ⇒ 这一格没查成（不是"没毛病"）。
            out.update(refused=PROPOSITION_FORM_REFUSED,
                       reason=("这一名秘书没有判断面（没有缝 / 开关关着）⇒ 形态没判成。"
                               "登记这一步按受控拒处理 —— 「没判成」不许折成「没毛病」"
                               + (f"（装配读数：{self.model_source}）"
                                  if str(self.model_source or "") else "")))
            self._note_form(out, body=body, label=label, kind=kind, stmt_id=stmt_id,
                            task_id=task_id, root=root)
            return out
        material = {"label": str(label or ""), "kind": str(kind or ""),
                    "statement_full": body[:JUDGE_MATERIAL_CAP],
                    "proof_chars": len(str(proof_text or ""))}
        out["material"] = dict(material)
        try:
            data, call = self.seam.ask_json(_judge_material(material),
                                            system=_proposition_form_system(),
                                            task_id=task_id,
                                            note="secretary:proposition_form")
        except Exception as exc:  # noqa: BLE001 —— 调用失败 = 没判成（fail-closed）
            out.update(refused=PROPOSITION_FORM_REFUSED,
                       reason=f"形态判定调用失败（{type(exc).__name__}: {exc}）⇒ 没判成")
            self._note_form(out, body=body, label=label, kind=kind, stmt_id=stmt_id,
                            task_id=task_id, root=root)
            return out
        if not getattr(call, "ok", False) or not isinstance(data, Mapping):
            out.update(refused=PROPOSITION_FORM_REFUSED,
                       reason=(f"形态判定没拿到可用的 JSON（{getattr(call, 'problem', '') or 'no_reply'}:"
                               f"{str(getattr(call, 'detail', '') or '')[:160]}）⇒ 没判成"))
            self._note_form(out, body=body, label=label, kind=kind, stmt_id=stmt_id,
                            task_id=task_id, root=root)
            return out
        raw = data.get("well_formed")
        if not isinstance(raw, bool):
            out.update(refused=PROPOSITION_FORM_REFUSED,
                       reason=(f"模型给的 well_formed 不是布尔（收到 {raw!r}）⇒ 不采信："
                               "这一问只有两态，第三档会让「没判成」冒充「没毛病」"))
            self._note_form(out, body=body, label=label, kind=kind, stmt_id=stmt_id,
                            task_id=task_id, root=root)
            return out
        conditions = str(data.get("conditions") or "").strip()
        conclusion = str(data.get("conclusion") or "").strip()
        problems = [str(x).strip() for x in (data.get("problems") or []) if str(x).strip()]
        decision = str(data.get("decision") or "").strip()
        if raw and not (conditions and conclusion):
            out.update(refused=PROPOSITION_FORM_REFUSED,
                       reason=("模型判合格，却读不出前提或结论（conditions/conclusion 有空格）⇒ "
                               "这一格没判成：合格的那一档必须能复述「条件 → 结论」"))
            self._note_form(out, body=body, label=label, kind=kind, stmt_id=stmt_id,
                            task_id=task_id, root=root)
            return out
        if not raw and not problems:
            out.update(refused=PROPOSITION_FORM_REFUSED,
                       reason=("模型判不合格，却一条 problems 都没点名 ⇒ 这一格没判成："
                               "拒收必须逐条说缺什么，否则调用方不知道该改哪里"))
            self._note_form(out, body=body, label=label, kind=kind, stmt_id=stmt_id,
                            task_id=task_id, root=root)
            return out
        out.update(checked=True, well_formed=bool(raw), conditions=conditions,
                   conclusion=conclusion, problems=problems, decision=decision,
                   refused="" if raw else PROPOSITION_FORM_REFUSED,
                   reason=("形态合规：前提与结论都读得出来" if raw else
                           f"形态不合规：{len(problems)} 条 —— " + "；".join(problems[:4])))
        self._note_form(out, body=body, label=label, kind=kind, stmt_id=stmt_id,
                        task_id=task_id, root=root)
        return out

    def _note_form(self, out: Mapping[str, Any], *, body: str, label: str = "",
                   kind: str = "", stmt_id: str = "", task_id: str = "",
                   root: str = "") -> None:
        """把这一次形态判定落进台账（写不进去不许带走这一次判定的结论）。"""
        if not root:
            return
        try:
            out["ledger"] = append_proposition_form(
                root, statement_full=body, checked=bool(out.get("checked")),
                well_formed=bool(out.get("well_formed")),
                conditions=str(out.get("conditions") or ""),
                conclusion=str(out.get("conclusion") or ""),
                problems=list(out.get("problems") or ()),
                decision=str(out.get("decision") or ""),
                refused=str(out.get("refused") or ""),
                reason=str(out.get("reason") or ""), label=label, kind=kind,
                stmt_id=stmt_id, role=str(self.role), task_id=task_id)
        except Exception as exc:  # noqa: BLE001 —— 台账写不进去要看得见，但不改判定
            out["ledger_error"] = f"{type(exc).__name__}: {exc}"

    def judge_same_proposition(self, *, before: str, after: str, label: str = "",
                               kind: str = "conjecture", task_id: str = "",
                               note: str = "secretary:proposition_identity") -> dict[str, Any]:
        """同一个稿上改前 / 改后那两段命题正文，是不是同一条命题（两态；判不了 ⇒ 没判成）。

        ## 与 `adjudicate_proposition` 的分工（不是第二份判据）

        那一问是"新命题 vs 在册候选"：判 same 必须点出一个候选号（`same_as`），并落
        `proposition_verdicts` 缓存。这一问是"同一份稿的 `## 命题` 从 A 改成 B"——
        两侧都没有台账号，也没有"并进哪一条"这件事。所以：

        - 轴不新造：`judge("proposition_identity", …)` 与那一问同一类、同一份题面
          （`_judge_system("proposition_identity")`）；
        - 材料同形：`_identity_context(full=after, candidates=[before 那一条])`
          —— 模型看到的是"要判的这一条 + 一条候选"，读法一字不差；
        - 不缓存：`proposition_verdicts` 的键只有 `after` 的 sha，而这一问的答案还取决
          于 `before` ⇒ 按单一 sha 缓存会把"上次 A→B 判 same"沿用到"C→B"上。这一档不写
          那本账（这一问是修稿兜底，不是每次登记的常路，花一次调用是可接受的）。

        ## 三态（与全仓同一条纪律）

        | 结局 | 返回 |
        |---|---|
        | 判成 | `checked=True` + `decision="same"` / `"different"` + `basis` |
        | 没判成 | `checked=False` + `decision=""` + `reason`（没缝 / 开关关着 / 超时 / 坏 JSON / 词表外） |

        `same` 是"同一条命题"，`different` 是"另一条命题"——调用方（原位重写的写口）
        只在 `checked=True and decision=="same"` 时才许动稿，别的两档一律 fail-closed。
        """
        out: dict[str, Any] = {"checked": False, "decision": "", "reason": "",
                               "basis": "", "cost": {}, "before_sha256": "",
                               "after_sha256": "", "note": note}
        before_text = str(before or "")
        after_text = str(after or "")
        out["before_sha256"] = _proposition_verdict_key(before_text)
        out["after_sha256"] = _proposition_verdict_key(after_text)
        if not before_text.strip() or not after_text.strip():
            out["reason"] = ("改前或改后的命题正文是空的 ⇒ 没有可判的两段"
                             "（空的那一侧不是「同一条」）")
            return out
        if not _is_proposition_kind(str(kind or "")):
            out["reason"] = (f"kind={kind!r} 不在命题性的那几档 {list(PROPOSITION_KINDS)} 里 "
                             "⇒ 不是命题，不参与同一性判定")
            return out
        context = self._identity_context(
            full=after_text, label=str(label or ""), kind=str(kind or ""),
            candidates=[{"stmt_id": "", "label": str(label or ""),
                         "proof_nos": [], "statement_full": before_text}])
        got = self.judge("proposition_identity", context, task_id=task_id, note=note)
        out["cost"] = dict(got.get("cost") or {})
        if not got.get("checked"):
            out["reason"] = str(got.get("reason") or "这一格没查成（原因不明）")
            return out
        decision = str(got.get("decision") or "")
        if decision not in PROPOSITION_VERDICTS:
            out["reason"] = (f"模型给的结论 {decision!r} 不在两档 {list(PROPOSITION_VERDICTS)} "
                             "里 ⇒ 不采信：这一格没判成")
            return out
        parts = [str(x).strip() for x in (got.get("basis") or []) if str(x).strip()]
        out.update(checked=True, decision=decision,
                   reason=str(got.get("reason") or ""),
                   basis="；".join(parts + ([out["reason"]] if out["reason"] else [])))
        return out

    # ------------------------------------------------ 同一命题检索
    #
    # 「B秘书要学会在命题台账里按关键词搜索」「语义判定……应该是主动查询」。
    # 语义判定是主动查询，不是把全表交给模型。
    #
    # 两问，都在这一处收口：
    #   ① pick_statement_keywords：从待收命题里挑数学内容的关键词（检索的输入）；
    #   ② `adjudicate_proposition`：代码按关键词检索，再把命中候选交给判定那一趟。
    # 判定只有一处实现（`adjudicate_proposition`；两档 same / different）：
    # 每一处调用都走它，不再有第二个入口、也不再有自己的第二份题面。

    def pick_statement_keywords(self, *, statement_full: str, label: str = "",
                                kind: str = "", task_id: str = "") -> dict[str, Any]:
        """给一条待收命题挑检索关键词（一次模型调用；产物只有 keywords 与 why）。

        「B秘书要学会在命题台账里按关键词搜索」。
        这一问只回答"拿哪几个词去台账里捞"，不回答"捞到的是不是同一条"（那是
        :meth:`adjudicate_proposition` 那一趟）。两问分开的理由：关键词是检索的输入，
        判同一是检索结果的处置；混成一问会让"检索没捞到"与"判定说不是"在读数上同形。

        ## 返回
        | 键 | 意思 |
        |---|---|
        | checked | 这一问有没有真的判成（没缝 / 关着 / 超时 / 坏 JSON / 空词表 ⇒ False） |
        | keywords | 模型给出的关键词（原样，按出现顺序去重；词数由它自己定） |
        | why | 一句话：这几个词为什么能把同义的那条捞出来 |

        代码里没有"最多 N 个词"的上限：词数是判定的一部分（业主明确不许机械上限）。
        检索面多大由调用方按工程上限分批，不由这一问替它裁。
        """
        out: dict[str, Any] = {"checked": False, "keywords": [], "why": "",
                               "seam_source": str(self.model_source or ""),
                               "ledger": {}, "role": str(self.role)}
        body = str(statement_full or "")
        if not body.strip():
            out["why"] = ("命题正文是 0 字 ⇒ 没有可检索的内容（没调模型）："
                          "空正文不是「材料不足」，它没有关键词可挑")
            self._note_statement_same(stage="keywords", out=out, body=body,
                                      label=label, kind=kind, task_id=task_id)
            return out
        if self.seam is None or not self.enable_model:
            out["why"] = ("这一名秘书没有判断面（没有缝 / 开关关着）⇒ 关键词没提取成。"
                          "调用方必须 fail-closed：不新注册"
                          + (f"（装配读数：{self.model_source}）"
                             if str(self.model_source or "") else ""))
            self._note_statement_same(stage="keywords", out=out, body=body,
                                      label=label, kind=kind, task_id=task_id)
            return out
        material = {"label": str(label or ""), "kind": str(kind or ""),
                    "statement_full": body[:JUDGE_MATERIAL_CAP]}
        try:
            data, call = self.seam.ask_json(
                _judge_material(material), system=_statement_keywords_system(),
                task_id=task_id, note="secretary:statement_keywords")
        except Exception as exc:  # noqa: BLE001 —— 调用失败 = 没提取成（fail-closed）
            out["why"] = f"关键词提取调用失败（{type(exc).__name__}: {exc}）⇒ 没提取成"
            self._note_statement_same(stage="keywords", out=out, body=body,
                                      label=label, kind=kind, task_id=task_id)
            return out
        if not getattr(call, "ok", False) or not isinstance(data, Mapping):
            out["why"] = (f"关键词提取没拿到可用的 JSON（{getattr(call, 'problem', '') or 'no_reply'}:"
                          f"{str(getattr(call, 'detail', '') or '')[:160]}）⇒ 没提取成")
            self._note_statement_same(stage="keywords", out=out, body=body,
                                      label=label, kind=kind, task_id=task_id)
            return out
        raw = data.get("keywords")
        if not isinstance(raw, (list, tuple)):
            out["why"] = (f"模型给的 keywords 不是数组（收到 {raw!r}）⇒ 不采信："
                          "这一问的产物是一张词表，不是一句话")
            self._note_statement_same(stage="keywords", out=out, body=body,
                                      label=label, kind=kind, task_id=task_id)
            return out
        from . import textutil as T   # 惰性：只借既有归一化口径做去重
        words: list[str] = []
        seen: set[str] = set()
        for item in raw:
            word = str(item or "").strip()
            key = T.normalize(word)
            if not word or not key or key in seen:
                continue
            seen.add(key)
            words.append(word)
        why = str(data.get("why") or "").strip()
        if not words:
            out["why"] = "模型给的关键词表是空的 ⇒ 没提取成（空词表捞不到任何一条）"
            self._note_statement_same(stage="keywords", out=out, body=body,
                                      label=label, kind=kind, task_id=task_id)
            return out
        if not why:
            out["why"] = ("模型给了关键词却没写 why ⇒ 不采信：读的人要能看出"
                          "这几个词凭什么能把同义的那条捞出来")
            self._note_statement_same(stage="keywords", out=out, body=body,
                                      label=label, kind=kind, task_id=task_id)
            return out
        out.update(checked=True, keywords=words, why=why)
        self._note_statement_same(stage="keywords", out=out, body=body,
                                  label=label, kind=kind, task_id=task_id)
        return out

    def _note_statement_same(self, *, stage: str, out: dict[str, Any],
                             body: str = "", label: str = "", kind: str = "",
                             keywords: Sequence[str] = (), hits_total: int = 0,
                             candidates: Sequence[str] = (),
                             task_id: str = "") -> None:
        """把这一问落进台账（写不进去不许带走结论；与 `_note_form` 同一条纪律）。"""
        root = str(getattr(self.store, "root", "") or self.root or "")
        if not root:
            return
        try:
            out["ledger"] = append_statement_same(
                root, stage=stage, statement_full=body,
                checked=bool(out.get("checked")),
                keywords=list(keywords or ()), hits_total=int(hits_total or 0),
                candidates=list(candidates or ()),
                found=str(out.get("found") or ""), why=str(out.get("why") or ""),
                label=label, kind=kind,
                seam_source=str(out.get("seam_source") or ""),
                role=str(self.role), task_id=task_id)
        except Exception as exc:  # noqa: BLE001 —— 台账写不进去要看得见，但不改判定
            out["ledger_error"] = f"{type(exc).__name__}: {exc}"

    def judge_abandon_difficulty(self, *, statement: Mapping[str, Any],
                                 difficulty: Any, basis: Any, salvaged: Any = (),
                                 task_id: str = "", stmt_id: str = "") -> dict[str, Any]:
        """放弃闸的 difficulty 档：一次秘书语义判定。

        「对于 2，需指出困难，并将原先证明中可取之处拆出落成引理」。
        `difficulty` 只非空不算数（"做不动了"不是指出困难），`salvaged` 光"在册 /
        active / kind=lemma"也不算（可以是任意一条无关旧引理）。这一问同时判两件事，
        一次调用：

        1. `difficulty` 是不是在说真实的数学困难、难在哪（卡在哪条引理 / 哪一步 /
           哪条假设），而不是"做不动了"这类没有内容的话；
        2. `salvaged` 里那几条引理是不是从这条命题的原证明里拆出来的可取之处，
           而不是随便一条在册引理（或这条命题自己）。

        ## 为什么是模型判定而不是字数/关键词阈值
        「真困难」与「从旧稿拆出」都是语义判断：任何字数下限都会被一段套话满足，
        任何关键词表都会把"缺一条 K 的速降假设"判成没有关键词。不要机械判据。

        ## 三态（本仓最贵的那条纪律）
        没缝 / 关着 / 超时 / 坏 JSON / 非布尔 / 说合格却读不出"难在哪" ⇒ `checked=False`
        + `refused`（调用方按受控拒处理）。不许把"这一次没判成"折成"有理由"。

        ## 返回（键集合固定）
        `checked` / `genuine` / `where` / `salvaged_from_proof` / `problems` /
        `decision` / `refused` / `reason`。
        """
        out: dict[str, Any] = {
            "checked": False, "genuine": False, "where": "", "salvaged_from_proof": False,
            "problems": [], "decision": "", "refused": "", "reason": "",
            "cost": {}, "statement_sha256": "",
        }
        body = str((statement or {}).get("statement_full") or "")
        proof = str((statement or {}).get("proof_text") or "")
        out["statement_sha256"] = hashlib.sha256(body.encode("utf-8")).hexdigest() if body else ""
        if not str(difficulty or "").strip():
            out.update(refused="abandon_difficulty_required",
                       reason="这一档没有 `difficulty` ⇒ 没有可判的「难在哪」（不发调用）")
            return out
        if self.seam is None or not self.enable_model:
            out.update(refused="abandon_difficulty_not_judged",
                       reason=("这一名秘书没有判断面（没有缝 / 开关关着）⇒ 难度没判成；"
                               "按受控拒处理 ——「没判成」不许折成「有理由」"
                               + (f"（装配读数：{self.model_source}）"
                                  if str(self.model_source or "") else "")))
            return out
        rows = []
        for one in (salvaged or ()):
            if not isinstance(one, Mapping):
                continue
            rows.append({"stmt_id": str(one.get("stmt_id") or ""),
                         "kind": str(one.get("kind") or ""),
                         "created_at": str(one.get("created_at") or ""),
                         "label": str(one.get("label") or ""),
                         "statement_full": str(one.get("statement_full") or "")[:JUDGE_MATERIAL_CAP]})
        material = {
            "statement_full": body[:JUDGE_MATERIAL_CAP],
            "proof_text": proof[:JUDGE_MATERIAL_CAP],
            "difficulty": str(difficulty or ""),
            "abandon_basis": str(basis or ""),
            "salvaged": rows,
        }
        try:
            data, call = self.seam.ask_json(_judge_material(material),
                                            system=_abandon_difficulty_system(),
                                            task_id=task_id,
                                            note="secretary:abandon_difficulty")
        except Exception as exc:  # noqa: BLE001 —— 调用失败 = 没判成（fail-closed）
            out.update(refused="abandon_difficulty_not_judged",
                       reason=f"难度判定调用失败（{type(exc).__name__}: {exc}）⇒ 没判成")
            return out
        out["cost"] = dict(getattr(call, "cost", {}) or {})
        if not getattr(call, "ok", False) or not isinstance(data, Mapping):
            out.update(refused="abandon_difficulty_not_judged",
                       reason=(f"难度判定没拿到可用的 JSON（{getattr(call, 'problem', '') or 'no_reply'}:"
                               f"{str(getattr(call, 'detail', '') or '')[:160]}）⇒ 没判成"))
            return out
        genuine = data.get("genuine")
        from_proof = data.get("salvaged_from_proof")
        if not isinstance(genuine, bool):
            out.update(refused="abandon_difficulty_not_judged",
                       reason=(f"模型给的 genuine 不是布尔（收到 {genuine!r}）⇒ 不采信："
                               "这一问只有两态，第三档会让「没判成」冒充「有理由」"))
            return out
        if not isinstance(from_proof, bool):
            out.update(refused="abandon_difficulty_not_judged",
                       reason=(f"模型给的 salvaged_from_proof 不是布尔（收到 {from_proof!r}）"
                               "⇒ 不采信（同一档只有两态）"))
            return out
        where = str(data.get("where") or "").strip()
        problems = [str(x).strip() for x in (data.get("problems") or []) if str(x).strip()]
        decision = str(data.get("decision") or "").strip()
        if genuine and not where:
            out.update(refused="abandon_difficulty_not_judged",
                       reason=("模型判「这是真困难」，却读不出难在哪（where 是空的）⇒ "
                               "这一格没判成：合格必须能复述「难在哪」"))
            return out
        if (not genuine or not from_proof) and not problems:
            out.update(refused="abandon_difficulty_not_judged",
                       reason=("模型判不合格，却一条 problems 都没点名 ⇒ 这一格没判成："
                               "拒收必须逐条说缺什么"))
            return out
        refused = ""
        if not genuine:
            refused = "abandon_difficulty_not_genuine"
        elif not from_proof:
            refused = "abandon_salvaged_not_from_proof"
        out.update(checked=True, genuine=genuine, where=where,
                   salvaged_from_proof=from_proof, problems=problems,
                   decision=decision, refused=refused,
                   reason=(f"难度判定：{'是真困难，难在 ' + where if genuine else '不是真困难'}"
                           f"；salvaged {'取自原证明' if from_proof else '不是从原证明拆出来的'}"))
        return out

    def judge_statement(self, *, statement_full: str, statement: str = "",
                        source: str = "", basis_hint: str = "",
                        proof_text: str = "", proofs: list | None = None,
                        task_id: str = "", kind: str = "",
                        stmt_id: str = "", record: bool = False) -> dict[str, Any]:
        """B 的秘书专属：这条待入库的命题落在非平凡性的哪一档。

        ## 判与落拆成两段（NT2，2026-11-15 业主裁定）

        这个方法只判、不写盘（缺省 `record=False`）。业主口径：B 处理一条录入任务时，
        第一个动作是判非平凡度；等登记/匹配那一笔拿到 `stmt_id` 与 `path_group` 之后，
        才由 :meth:`record_nontriviality` 追加台账行。判在这里落行的旧形状有两个毛病：

        - 号还没发下来 ⇒ 真机落了 6 行 `stmt_id` 为空的孤儿读数（其中 4 行正文 sha
          对不上任何命题行，钱花了、读数读不到任何一条命题）；
        - 判档挂在"工具返回之后"（`agent_loop._do_tool`）⇒ 台账写发生在判之前，
          与业主"先判再录"的顺序正好相反。

        `record=True` 只为"没有登记这一笔动作、直调判档"的旧调用面（判据 / 存量补写）
        留着：它落一行 statement-scope 的行（`path_group=0`）。生产面（B 的收录动作、
        F 交稿、概念行的幂等补写）一律走 :meth:`record_nontriviality` —— 那条路要求
        `stmt_id` 与路径号，拿不到就不落（并留 `unrecorded` 痕迹）。

        `stmt_id` 是这条命题在 `statements` 里的号（只在 `record=True` 时被用到）：
        台账那一行靠它对上命题行（按正文 sha 关联会把"改了一个字"读成"没判过"）。

        为什么是"秘书"而不是又一条机器判据：平凡与否不是字符串能判的事（`a+b=b+a` 与一条
        真定理的字面形态可能很像），它属于本仓划给秘书的那一类判断 —— 机器只摆材料，
        结论由本体自己的缝给。

        ## 两态（判不了退场为"没查成"）

        | 结局 | 返回 |
        |---|---|
        | 有档 | `checked=True` + `decision ∈ {"T0"…"T4"}` + `nontriviality` 同值 + `label` |
        | 没查成 | `checked=False` + `reason`；不落档位行；决定台账写 `decision="没查成"` |
        | 不是 B 的秘书 | `checked=False` + 理由（这一问只属于 B） |
        | 正文 0 字 | `checked=False` + `code=empty_statement_text`（不判档、不发调用、不落台账） |

        "没查成"的来路：模型给 null / 旧词 / 坏 JSON、调用失败、正文被截断、一项力气读数都
        取不到。处置都是"重试 / 重交 / 人看" —— 所以盘上不许留一条 `nontriviality: null`
        的行冒充"判过了但没档"。

        ## 材料里的 `effort` 只是参考读数

        机器数好的四项（体量 / 步骤 / 引理 / 工具簇跨度）外加绕路与分数
        （:func:`proof_effort_readings`）只作材料；档位由秘书按五档定义判，
        `proof_effort_readings` 不落格、也不拿来补一个档位。

        三条"谁是权威"：档位由模型判；读数缺项或正文被截断 ⇒ `checked=False`（不发调用、
        不落档位行，reason 点名缺哪项，不许落 0 冒充"基础定理"）；`decision` 是唯一主字段
        （审美轴三格已退场），给 `T0`…`T4` 就是档位，给 null / 旧词一律"没查成"。

        ## 旧行怎么读

        新行只写 `T0`…`T4`；旧台账里的三个旧词由 :func:`_tier_from_legacy_decision` 折算
        （太平凡 ⇒ T0；合格 ⇒ 读 `judge.nontriviality` / 同号档位行，都没有 ⇒ 未判；
        判不了 ⇒ 未判）。2026-11-01 之前的两字段判词形状（`decision="合格"` +
        `nontriviality=2`）仍按旧别名读，decision 能解析时以 decision 为准。

        `proof_text` / `proofs` 可选：正文里自带证明小节时读数照样读得到，
        真读不到就是"缺证明正文"那一支。

        ## 概念 / 定义行：判档"不适用"

        判据是"这份证明花了多大力气"，而概念行没有证明正文（`conceptrows.concept_statement`
        明令 `proof_text` 留空）⇒ 四项读数一项都取不到。`kind` 落在
        :data:`NOT_APPLICABLE_KINDS` 时在取材料之前就早退：不发调用、不判力气，
        只落一条"不适用"（台账里 `applicable: false`）。这一支放在角色那一关之前 ——
        概念的"力气"这一问与哪一名的秘书无关。
        """
        if _is_not_applicable_kind(kind):
            return self.not_applicable_nontriviality(
                statement_full=statement_full, kind=kind, task_id=task_id,
                stmt_id=stmt_id, record=record)
        if str(self.role) != "B":
            return {"checked": False, "decision": "", "basis": [],
                    "reason": f"这一问只属于 B 的秘书（本条秘书属于 {self.role!r}）⇒ 这一格没查成",
                    "cost": {"ledger": "", "reason": "没发调用（不是 B 的秘书）"}}
        # ---- 0 字命题：不进判档流程（B2 的第 1 条，2026-10-24）
        #
        # 空正文那一行根本不该存在：空正文不是一个"判不了的对象"，它是"没有对象" ——
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
        # ---- 力气读数（B2 的机器侧：只是参考读数，判档位的是秘书的模型）
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
        # 这几格都开到判据输入够用的上限，不做静默截断：秘书要判的是"这条命题
        # 平不平凡"，而命题的长尾（限定条件、量词顺序）正是决定平凡与否的部分。
        # 截到 2000 字符意味着它可能在对半条命题下结论，而那个结论会变成
        # "这条别收"（`agent_loop._statement_filing_refusal`）。
        # 注意 `statement_full` 同时是缓存键的输入（见下面的 sha256）：键必须
        # 跟着一起变 —— 它变了是好事，"同一命题问第二遍不重复花钱"仍然成立，
        # 而两条前 2000 字符相同、之后不同的命题不再被误认成同一条。
        #
        # 多一格 `effort`（力气读数）。它按 `sort_keys` 排在材料最前面 ——
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

        def _unjudged(reason: str, *, cost_reason: str) -> dict[str, Any]:
            """这一格没查成：落一条 `decision=没查成` 的决定台账行，不落档位行。

            2026-11-01（第二刀）：判档只有两态。"没拿到判定"不是第四档，也不是一条
            `nontriviality: null` 的行 —— 后者会让"没人判过"在盘上冒充"判过了但没档"。
            """
            reason = str(reason)[:900]
            self.note_decision(
                duty=2, kind=KIND_DECISION, decision=JUDGE_UNCHECKED,
                reason=reason, target={"judge": "statement_aesthetic"}, basis=[],
                before=json.dumps({"statement_full": body_full,
                                   "why_this_is_not_trivial": str(basis_hint or "")},
                                  ensure_ascii=False, default=str)[:2000],
                fail_open=False,
            )
            return {"checked": False, "decision": "", "basis": [], "reason": reason,
                    "nontriviality": None, "label": "",
                    "nontriviality_tri": "unjudged", "nontriviality_basis": "",
                    "effort": readings, "text_truncated": bool(text_truncated),
                    "cost": {"ledger": "", "reason": cost_reason}}

        # 输入不完整 ⇒ 这一格没查成（不发调用、不落档位行）。这两支都必须在缓存/调用
        # 之前：截断的正文发去判档只会白花一次调用，而且回来也没有可用判定。
        if text_truncated:
            return _unjudged(trunc_note + "。这一格没查成：把正文拆段重交（分段登记）再判",
                             cost_reason="没发调用（正文被截断）")
        if not readings.get("chars"):
            return _unjudged(
                "这一条一项力气读数都取不到（最常见的是没有证明正文）⇒ 这一格没查成："
                "把完整证明交进 proof_text（或 statement_full 的证明小节）再判",
                cost_reason="没发调用（缺证明正文）")

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
        if not got.get("checked"):
            # `judge` 已经把这一趟落进决定台账（"没查成"），这里不再落第二条。
            return got
        # 2026-11-01（第二刀）：判档只有两态 —— 有 T0..T4，或者没查成。
        # `decision` 是唯一主字段；`nontriviality` 只剩旧形状的读别名。
        decided = str(got.get("decision") or "")
        level = _tier_from_judge_reply(got)
        if level is None:
            # checked=True 却没有可解析档位（旧替身 / 坏判词）⇒ 仍是"没查成"，不折档。
            return _unjudged(
                f"判词里没有可解析的档位（decision={decided!r}）⇒ 这一格没查成",
                cost_reason="没发调用（判词没有档位）")
        model_note = str(got.get("nontriviality_basis") or "")
        notes = [f"档位以秘书判定为准：{nontriviality_label(level)}"
                 f"（机器力气读数只作参考，score={int(readings.get('score') or 0)}）"]
        if level == 0:
            notes.append(f"降为 {nontriviality_label(0)}：力气读数只作参考"
                         f"（档位由秘书按五档定义判）；秘书原话："
                         f"{str(got.get('reason') or '')[:200]}")
        if model_note:
            notes.append(f"秘书原报档位依据：{model_note}")
        basis_note = "；".join(n for n in notes if n)[:900]
        got = {**got, "nontriviality": level, "label": nontriviality_label(level),
               "nontriviality_basis": basis_note,
               "nontriviality_tri": "computed",
               "effort": readings, "effort_score": int(readings.get("score") or 0),
               "text_truncated": False}
        # ---- 判与落拆开（NT2）：这里只判，正常路径一个字节都不写盘 -------------
        #
        # `record=True` 是旧直调面的兼容档（没有"登记这一笔"可依附）：它落一行
        # statement-scope 的行（`path_group=0`），并与旧行为逐字一致地按正文 sha 关联。
        # 生产面不许用它 —— B 的收录动作在拿到 `stmt_id` / `path_group` 之后走
        # `record_nontriviality`（见 `agent_b.register_statement._register_statement_impl`）。
        if record:
            judged_sha = _judged_body_sha(body_full, proof_joined)
            self.record_nontriviality(
                got, stmt_id=stmt_id, path_group=0, statement_full=body_full,
                landed_body_sha256=_statement_sha(body_full),
                judged_body_sha256=judged_sha)
        # 只记判过的结论（没查成不缓存，见 `_statement_verdicts` 的说明）。
        self._statement_verdicts[key] = dict(got)
        return got

    def record_nontriviality(self, reading: Mapping[str, Any], *, stmt_id: str,
                             path_group: int = 0, statement_full: str = "",
                             landed_body_sha256: str = "",
                             judged_body_sha256: str = "") -> dict[str, Any]:
        """把判过的读数落进旁支台账（"判/落拆段"的落这一半，NT2）。

        ## 落的条件（业主口径的两条，缺一不落）

        | 条件 | 拿不到时的处置 |
        |---|---|
        | `stmt_id` 非空 | `tri="unrecorded"` + 原因；决定台账留一行（钱花了，"判过"要可见） |
        | 路径级读数：`path_group >= 1` | 同上 —— 没有路径号就没法"一个路径一行"，落一行假的比不落更坏 |

        `applicable=false`（概念行）是唯一允许 `path_group=0` 的一档：它不参与命题级
        min（业主口径 ⑦：概念行的档位是 statement-scope 的"不适用"，不是一条路径）。

        ## 幂等（业主口径 B）

        同一 `(stmt_id, path_group)` 且 `judged_body_sha256` 相同 ⇒ 沿用已有读数、
        不追加一行（重复提交同一份稿不把 append-only 台账撑大）。正文变了才追加：
        逐路径"最后一行胜"（允许该路径降档/升档），命题级由读侧再取 min（永不回升）。

        ## 两枚 sha

        - `judged_body_sha256`：判的材料（命题 + 空行 + 证明，见 :func:`_judged_body_sha`）；
        - `landed_body_sha256`：落盘那一行的 `statement_full`。
        判的材料与落盘正文分开记，复核的人才能回答"判的是哪一版"。
        """
        root = getattr(self, "root", None)
        if root is None:
            return {"recorded": False, "tri": "unrecorded", "level": None, "label": "",
                    "stmt_id": str(stmt_id or ""), "path_group": int(path_group or 0),
                    "reason": "这一名秘书没有工作区根 ⇒ 判过的档位没落（不是没判）"}
        got = dict(reading or {})
        sid = str(stmt_id or "").strip()
        no = int(path_group or 0)
        applicable = bool(got.get("applicable", True))
        level = _nontriviality_level(got.get("nontriviality"))
        tri_in = str(got.get("nontriviality_tri") or "")
        if applicable and (level is None or tri_in == "unjudged"):
            # 判档本身没查成：盘上不该多一条 `nontriviality: null` 的行冒充"判过了"。
            return {"recorded": False, "tri": "unjudged", "level": None, "label": "",
                    "stmt_id": sid, "path_group": no,
                    "reason": str(got.get("reason") or "判档没查成 ⇒ 没有可落的档位行")}
        if not sid:
            return self._unrecorded_nontriviality(
                "这一笔没拿到 stmt_id ⇒ 不落档位行（判过的读数留在决定台账里）",
                stmt_id="", path_group=no)
        if applicable and no < 1:
            return self._unrecorded_nontriviality(
                "这一笔没拿到 path_group（>=1）⇒ 不落档位行（判过的读数留在决定台账里）",
                stmt_id=sid, path_group=no)
        sha = str(judged_body_sha256 or "")
        if not sha:
            sha = _judged_body_sha(statement_full, str(got.get("proof_text") or ""))
        prior = self._last_nontriviality_row(sid, no)
        if prior is not None and str(prior.get("judged_body_sha256") or "") == sha:
            return {"recorded": False, "tri": tri_in or "computed",
                    "level": level, "label": nontriviality_label(level),
                    "stmt_id": sid, "path_group": no, "reused": True,
                    "reason": ("同一 (stmt_id, path_group) 且判的是同一份正文 ⇒ "
                               "沿用已有读数，不追加一行")}
        try:
            append_nontriviality(
                root, statement_full=(statement_full
                                      or str(got.get("statement_full") or "")),
                level=level,
                basis=str(got.get("nontriviality_basis")
                          or got.get("basis") or "")[:900],
                role=str(self.role or ""), task_id=str(self.task_id or ""),
                stmt_id=sid,
                effort=(got.get("effort") if isinstance(got.get("effort"), Mapping)
                        else {}),
                text_truncated=bool(got.get("text_truncated")),
                applicable=applicable, path_group=no, judged_body_sha256=sha,
                landed_body_sha256=str(landed_body_sha256 or ""))
        except Exception as exc:  # noqa: BLE001 - 落盘失败要说出来，不许静默
            return {"recorded": False, "tri": f"unrecorded:{type(exc).__name__}",
                    "level": level, "label": nontriviality_label(level),
                    "stmt_id": sid, "path_group": no,
                    "reason": f"落盘失败：{type(exc).__name__}: {exc}"}
        return {"recorded": True,
                "tri": ("not_applicable" if not applicable else "computed"),
                "level": level, "label": nontriviality_label(level),
                "stmt_id": sid, "path_group": no, "reason": ""}

    def _last_nontriviality_row(self, stmt_id: str, path_group: int) -> dict[str, Any] | None:
        """同一 `(stmt_id, path_group)` 的最后一行（幂等判据读它，不另建索引）。"""
        root = getattr(self, "root", None)
        want = str(stmt_id or "").strip()
        if root is None or not want:
            return None
        path = nontriviality_path(root)
        if not path.is_file():
            return None
        by_id, _by_sha, why = _nontriviality_index(path)
        if why:
            return None
        rows = [r for r in (by_id.get(want) or [])
                if _row_path_group(r) == int(path_group or 0)]
        return dict(rows[-1]) if rows else None

    def _unrecorded_nontriviality(self, reason: str, *, stmt_id: str = "",
                                  path_group: int = 0) -> dict[str, Any]:
        """判过、但这一笔拿不到落行所需的两件号 ⇒ 不落，并在决定台账留一行。

        为什么决定台账也要落：这一趟的模型调用已经花掉了。盘上一条档位行都没有而
        决定台账也没有，读的人就分不清"没判"与"判了没法落"（真机的 4 条孤儿行正是
        后者，而它们连一句话都没留下）。`basis=["unrecorded"]` 是这一档的可检索标记。
        """
        reason = str(reason)[:900]
        try:
            self.note_decision(
                duty=2, decision="判过未落", reason=reason, basis=["unrecorded"],
                target={"nontriviality": str(stmt_id or ""),
                        "path_group": int(path_group or 0)},
                after="判过的读数不落档位台账（缺号）；决定台账留这一行", fail_open=True)
        except Exception:  # noqa: BLE001 - 留痕失败不许带走返回值
            pass
        return {"recorded": False, "tri": "unrecorded", "level": None, "label": "",
                "stmt_id": str(stmt_id or ""), "path_group": int(path_group or 0),
                "reason": reason}

    # ------------------------------------------------ V 的三件事（业主 2026-10-29）
    #
    # V 签门槛 = 连续 3 次没问题 + V 秘书语义判定 + 洗稿转达。三件都落在 V 的秘书身上：
    # | 方法 | 业主口径 | 返回里的三态 |
    # |---|---|---|
    # | `judge_v_reply` | V 的回复落在 clean / fault 哪一档 | `checked=False` = 没查成（不是第三档） |
    # | `decide_sign_issuance` | 这一签发不发（读连续次数 + 模型判） | `checked=False` ⇒ 不发 |
    # | `wash_v_reply` | 把 V 的意见洗成能转达给 F 的文本 | `checked/ washed / refused` |
    #
    # 三件共用同一条制度约束：材料里没有 F 的证明正文。`may_read_narrative` 对
    # role="V" 恒 False（I12），而"把证明正文当材料递进去"正是绕过那条隔离的暗通道。

    def judge_v_reply(self, *, reply: str, verdict: str = "", defect_step: Any = None,
                      statement_id: str = "", proof_no: Any = 1,
                      task_id: str = "", proof_text: str = "",
                      materials: Any = None) -> dict[str, Any]:
        """V 这段审阅回复到底有没有指出缺陷（两档不许折平）。

        ## 材料只给两样（这是本方法的判据，不是实现细节）
        V 的回复正文 + 该台账行的 `verdict` / `defect_step`。不给 F 的证明
        （I12：V 的秘书读叙述本来就被 `may_read_narrative` 禁，这里不开那个口子）。
        所以 `proof_text` / `materials` 两个形参是受控拒绝口：调用方若真把它们塞进来，
        本方法拒判（`checked=False` + `refused="proof_text_not_allowed"`），
        而不是"收了但没用"—— 后者会让"秘书看过 F 的证明"这件事在盘上查不出来。

        ## 返回
        `checked` / `answer`（模型原话那一格；没查成时是 `JUDGE_UNCHECKED`） /
        `axis`（只有 `clean` / `fault` 两档；没查成时是空串） / `unwired`（这一趟有没有
        判断面） / `reason` / `basis` / `material`（真递给模型的那一份，供判据逐字核） /
        `refused` / `cost` / `verdict`（台账那一行的结论原文）。

        「不可能有判不了…只要不是完全没毛病都叫有毛病」。
        于是结论只有两格（`没问题` / `有缺陷要指出`）：拿不准、只挑出一处小记号问题、
        只说"我没逐行验证"——每一档在题面里都明文算「有缺陷要指出」。模型若仍答历史
        那一格（`判不了`）或任何词表外的写法 ⇒ `checked=False` + `axis=""`：
        那是"没查成"（框架失败），不是一种结论，更不是"没问题"（连续计数里既不算票、
        也不清零；上层见 `agent_v.core` 的 `secretary_unjudged` 那一支）。

        ## 轴是唯一的判定来源；判 fault 时由本方法定出那一步
        「V 的判词只是陈述」「每一转的轴（clean / fault）一律由 V 秘书做语义分析后给出」
        「判 fault 而 V 没给 defect_step ⇒ 秘书定出那一步」。
        所以：① `verdict` 只作为材料里的原话递给模型，本方法不按它的字面定轴；
        ② 模型判「有缺陷要指出」时还要给出 `defect_step`（题面要求），本方法把它带回去；
        ③ V 给了步号就以 V 的为准？不 —— 轴与步号都是秘书这一问的产物：V 的 `defect_step`
        只是材料，返回值里的 `defect_step` 是秘书定下的那一步（V 给同一值时二者相同）。
        """
        from . import verifications as _VR   # 惰性：此处只借它的轴词表与 `row_signable`

        out: dict[str, Any] = {
            "checked": False, "answer": JUDGE_UNCHECKED, "axis": "",
            "unwired": bool(self.seam is None or not self.enable_model),
            "reason": "", "basis": [], "refused": "", "cost": {},
            "verdict": str(verdict or ""), "defect_step": defect_step,
            #: 这四个键每一行都写（值可以为空串）。键在不在是"新行 / 老行"的唯一分界
            #: （`verifications.fault_kind_of` 读的就是它）；没判成时它们也在，值为空。
            "fault_kind": "", "fault_cause": "", "report_gap": "",
            "statement_id": str(statement_id or ""), "proof_no": 0,
            "material": {},
        }
        try:
            out["proof_no"] = int(_VR.as_proof_no(proof_no) or 0)
        except (TypeError, ValueError):
            out["proof_no"] = 0
        if str(proof_text or "").strip() or materials is not None:
            out["refused"] = "proof_text_not_allowed"
            out["reason"] = ("材料里被塞进了 F 的证明正文（或额外的 materials）⇒ 拒判："
                             "V 的秘书只读 V 的回复与那一签的 verdict/defect_step"
                             "（I12：V 的秘书不读 F 的叙述）。请把证明正文拿掉再来问")
            self.note_decision(
                duty=2, kind=KIND_DECISION, decision=JUDGE_UNCHECKED,
                reason=out["reason"], target={"judge": "v_reply_defect"},
                judge=dict(out), fail_open=False,
                before=f"reply_chars={len(str(reply or ''))}", )
            return out
        body = str(reply or "").strip()
        if not body:
            out["reason"] = "V 的回复正文是空的 ⇒ 没有可判的对象（不是「没问题」）"
            return out
        # 递给模型的材料：只有这两样（键集合固定，判据可以逐字核）。
        material = {
            "v_reply": body[:JUDGE_MATERIAL_CAP],
            "ledger_row": {"verdict": str(verdict or ""), "defect_step": defect_step},
        }
        out["material"] = dict(material)
        got = self.judge("v_reply_defect", material, task_id=task_id)
        out["cost"] = dict(got.get("cost") or {})
        out["reason"] = str(got.get("reason") or "")
        out["basis"] = list(got.get("basis") or [])
        if not got.get("checked"):
            # 没查成 ⇒ 没有轴（不是 clean、也不是 fault）。`judge` 已经把这一趟
            # 落进决定台账了（`_record_judge`），这里不重复落。
            out["answer"] = JUDGE_UNCHECKED
            out["axis"] = ""
            return out
        answer = str(got.get("decision") or "").strip()
        if answer not in V_REPLY_AXIS:
            # 词表外（`judge` 已经挡过一次，这里是第二道：本方法的取值只由 V_REPLY_AXIS 定）。
            # `判不了` 不是一种结论 ⇒ 它落到这里（"不采信"），不许
            # 折成 fault 去凑一条判词，也不许折成 clean 放过去。
            out["answer"] = JUDGE_UNCHECKED
            out["axis"] = ""
            out["reason"] = f"结论 {answer!r} 不在 {list(V_REPLY_VERDICTS)} 里 ⇒ 不采信"
            return out
        out.update(checked=True, answer=answer, axis=V_REPLY_AXIS[answer])
        # ---- 把这一问的答案读成四个类别格（写侧分类第一半） --------------
        #
        # 轴仍由 `V_REPLY_AXIS` 定（两档不动）；这一支只多读两格 —— `defect_kind`
        # 与 `report_gap` —— 并把它们翻译成台账那一格里要落的
        # `fault_kind` / `fault_cause` / `report_gap`。"只缺反例尝试记录不算缺陷"
        # 在这里被编码成 `kind=""` + `cause="report_gap"`；要不要把它
        # 翻成 clean 轴由写行处决定（那里才拿得到 findings / defect_step —— 护栏只许
        # 往更严的方向折，见 `agent_v/core.py` 的 `_write_fault_cell`）。
        _reading = v_reply_fault_reading(
            decision=answer,
            defect_kind=got.get("defect_kind"),
            report_gap=got.get("report_gap"),
            reason=got.get("reason"))
        out.update(axis=str(_reading["axis"]),
                   fault_kind=str(_reading["fault_kind"]),
                   fault_cause=str(_reading["fault_cause"]),
                   report_gap=str(_reading["report_gap"]))
        #: p247：判 fault 时那一步由秘书这一问定（V 没给就以秘书给的为准；V 给了同一步
        #: 时二者相同）。判 clean ⇒ null（没有要改的那一步）。
        out["defect_step"] = (got.get("defect_step")
                              if V_REPLY_AXIS[answer] == "fault" else None)
        out["defect_step_basis"] = (str(got.get("defect_step_basis") or "")
                                    if V_REPLY_AXIS[answer] == "fault" else "")
        return out

    def decide_sign_issuance(self, *, statement_id: str, proof_text: str = "",
                             proof_no: Any = 1, verdict: Mapping[str, Any] | None = None,
                             task_id: str = "", row: Mapping[str, Any] | None = None,
                             within_call: int | None = None,
                             review_call: str = ""
                             ) -> dict[str, Any]:
        """这一签发不发（发签决定权在 V 的秘书）。

        ## 判据分两层，且只有一层能否决
        1. 台账那一层（机械、唯一真身）：`:func:`verifications.review_standing`` 现算的
           连续读数 —— 这一签落下去之后尾部连续「成立」几次（`streak + 1`，且必须盖着
           同一份正文）。次数不够 ⇒ `不签发`，不问模型（省一次调用，也不给它推翻门槛的机会）。
        2. 秘书那一层（语义）：次数够了，才问模型「签发 / 不签发」。
           它只能在这个前提下再否决，不能把"次数不够"判成"签发"。
        ⇒ 两层是"与"，不是"或"：门槛是地板，秘书的决定是天花板。

        ## `within_call`：单次送审内部的轮数
        「不允许跨两次送审累计成功数」。`AgentV` 的连判循环每转都把
        "这一趟的第几轮"作为 `within_call` 递进来；一旦给了它，第 1 层的地板就只看
        这个数，台账尾部历史连续数一个字节都不再参与"发不发签"的判断（连"缺口补齐"
        式的二次确认也不许：那正是后门从别处长回来的形态）。台账仍被读一次，但只作
        `reading` / `ledger_streak` 这份历史读数；`checked=False` 的台账读不成
        也不再挡住这一趟（历史读不成不是这一趟没判）。
        不给 `within_call`（旧直调路径 / 夹具）⇒ 保持原行为：地板读台账。那是历史
        兼容门，不是送审路径。

        ## 三态（"没查成"绝不被读成"没问题"）
        | 结局 | 返回 |
        |---|---|
        | 判了 | `checked=True` + `issue`（真/假）+ `decision`（中文两档） |
        | 没缝 / 开关关着 / 超时 / 台账读不成 / 坏 JSON / 词表外 | `checked=False` + `issue=False` + 理由 |

        `checked=False` ⇒ 不发签（装配没接上时秘书判定必须报
        `checked=False`，且不放签）。返回键：`checked` / `issue` / `decision` / `streak` /
        `need` / `streak_ok` / `projected` / `same_sha` / `state` / `reason` / `basis` /
        `reading` / `cost` / `material`。

        ## 落痕
        走 `note_decision`（那本账：`before` = 台账读数、`after` = 决定、`judge` = 这一趟判词）。
        判词那一行由 `judge()` 自己落（`_record_judge`），所以一次决定会留两行：
        一行"判断"、一行"决定"——它们是两件事（判了什么 / 据此发不发）。
        """
        from . import verifications as _VR   # 惰性：与 `merge_into_*` 那条同一处依赖

        v = dict(verdict or {})
        if row is not None and not v:
            # 调用方只给了台账那一行：这一签的结论与未解决 error 从行上读（同一份事实，
            # 不要求调用方抄第二遍）。
            v = {"verdict": row.get("verdict"),
                 "unresolved_errors": row.get("unresolved_errors"),
                 "defect_step": row.get("defect_step")}
        # 2026-11-11：`proof_no` 在 V 签侧退役 —— 返回值不再写这一格，但它仍是
        # 「这一趟审的是哪一份」的材料标签（递给模型的那一小段仍要说清）。
        try:
            proof_number = int(_VR.as_proof_no(proof_no) or 0)
        except (TypeError, ValueError):
            proof_number = 0
        out: dict[str, Any] = {
            "checked": False, "issue": False, "issued": False,
            "decision": JUDGE_UNCHECKED, "landed": False, "writeback": {},
            "streak": 0, "need": int(_VR.SIGN_STREAK_NEED), "streak_ok": False,
            "projected": 0, "same_sha": False, "state": "", "reason": "",
            #: 2026-11-02：单次送审内的轮数（None = 没给，走历史台账兼容门）/
            #: 那一趟的调用 id / 台账尾部的历史连续数（只作读数，不参与判定）。
            "within_call": None, "review_call": str(review_call or ""),
            "ledger_streak": 0,
            "basis": [], "reading": {}, "cost": {}, "material": {},
            "statement_id": str(statement_id or ""),
            # 2026-11-11：`proof_no` 在 V 签侧退役 —— 这一格不再写（顶层读数同口径）。
        }
        #: `within_call` 归一：负数按 0 收（"这一趟一轮都没判"不是"次数够了"）。
        within: int | None = None
        if within_call is not None:
            try:
                within = max(0, int(within_call))
            except (TypeError, ValueError):
                within = None
        out["within_call"] = within
        root = self.store.root if self.store is not None else self.root
        reading_problem = ""
        try:
            reading = _VR.review_standing(root, statement_id=str(statement_id or ""),
                                          proof_text=str(proof_text or ""),
                                          proof_no=proof_no)
        except Exception as exc:  # noqa: BLE001 —— 读不成是"没查成"，不是"没问题"
            if within is None:
                out["reason"] = (f"台账读不成（{type(exc).__name__}: {exc}）⇒ 这一格没查成："
                                 "不放签（不是「可以签」）")
                self._note_sign_issuance(out, task_id=task_id)
                return out
            # 给了 `within_call` 时台账只是历史读数 —— 历史读不成不许反过来否决这一趟
            # （台账不以任何形式参与发不发签）。
            reading_problem = f"{type(exc).__name__}: {exc}"
            reading = {}
        out["reading"] = dict(reading)
        out["ledger_streak"] = int(reading.get("streak") or 0)
        out["streak"] = out["ledger_streak"]
        out["state"] = str(reading.get("state") or "")
        sha = str(reading.get("sha") or "")
        same_sha = bool(sha) and sha == _PR.proof_sha(str(proof_text or ""))
        out["same_sha"] = same_sha
        # 这一签落下去之后的连续次数：同一份正文 ⇒ 前一票 + 这一票；换了一份 ⇒ 从 1 起。
        #
        # 两种调用顺序都要对（生产走的是第二种）：
        # · 先问后做：台账里还没有这一签 ⇒ `streak + 1`（预测）；
        # · 先落台账后问（V 的秘书这一条路：`record_verification(flip=False)` 已经把行落了）
        #   ⇒ 这一签就是尾部那一签 ⇒ 连续次数就是 `streak`，不许再加一票。
        # 判据是 `verification_id` 与尾部那一签同号（不是靠调用方自己说落没落）。
        landed = (isinstance(row, Mapping)
                  and str(row.get("verification_id") or "")
                  and str(row.get("verification_id") or "")
                  == str(reading.get("verification_id") or ""))
        out["landed"] = bool(landed)
        # ---- 候选这一签的资格只看秘书给的轴，不看 V 的 verdict 字面 ----
        #
        # 「streak / 签发只看秘书给出的轴，不看 V 自己写的那两个字」。所以这里读
        # `secretary_axis`（row 已经有这一格；直调路径可以从
        # `verdict` 的 `secretary_judge` / `axis` 带进来），不再用 `verdict == "成立"`。
        candidate_axis = ""
        if isinstance(row, Mapping):
            candidate_axis = _VR.ledger_axis(row)
        if not candidate_axis:
            got_judge = v.get(_VR.SECRETARY_JUDGE_KEY)
            if isinstance(got_judge, Mapping):
                candidate_axis = _VR.secretary_axis({_VR.SECRETARY_JUDGE_KEY: got_judge})
        if not candidate_axis and str(v.get("axis") or "") in _VR.SECRETARY_JUDGE_AXES:
            candidate_axis = str(v.get("axis") or "")
        if not candidate_axis:
            #: 老调用点 / 直调夹具：只给了 `verdict`，没有秘书那一格 ⇒ 没有轴。
            #: `historical_axis` 一律空轴（按 `verdict` 字面给 clean/fault，那正是
            #: "绕过秘书登记成立"的后半截）。这一档因此是
            #: "判不了"：`candidate_ok` 为假 ⇒ 不签发，不是"没问题"。
            candidate_axis = _VR.historical_axis(v)
        candidate_ok = (candidate_axis == "clean"
                        and int(v.get("unresolved_errors") or 0) == 0)
        if within is not None:
            # ---- 2026-11-02 定稿：地板只看这一趟送审内部的轮数。
            # 台账尾部的历史连续数（`ledger_streak`）只作读数；`same_sha` 也只作读数，
            # 不参与这一支的判定 —— 否则旧台账又能凑出一次签（要求 ④）。
            out["streak"] = within
            out["projected"] = within if candidate_ok else 0
            out["streak_ok"] = bool(out["projected"] >= int(out["need"]))
            out["basis"] = [f"within_call={within}", f"need={out['need']}",
                            f"ledger_streak={out['ledger_streak']}（历史读数，不参与判定）"]
        else:
            if landed:
                out["projected"] = out["streak"] if candidate_ok else 0
            else:
                out["projected"] = ((out["streak"] + 1) if (same_sha and candidate_ok)
                                   else (1 if candidate_ok else 0))
            out["streak_ok"] = bool(out["projected"] >= int(out["need"]))
            out["basis"] = [f"streak={out['streak']}", f"need={out['need']}",
                            f"same_sha={same_sha}"]
        if not bool(reading.get("checked")) and within is None:
            out["reason"] = (f"台账那一格没查成（{str(reading.get('why') or '')[:160]}）"
                             "⇒ 不放签（不是「没问题」）")
            self._note_sign_issuance(out, task_id=task_id)
            return out
        # 递给模型的材料：只有读数，没有证明正文（I12 同一条纪律）。
        #
        # 要求 ④（2026-11-02）：`within_call` 一旦给出，台账就是历史读数 ——
        # 材料里「不放」任何台账派生的格子（`state` / `ledger_streak_history` /
        # 台账算出来的 `same_sha`）。同一趟送审的三轮由 V 的循环保证是同一份正文，
        # 所以这里给 `same_sha=True` 是"这一趟的事实"，不是台账读数。
        if within is not None:
            material = {
                "statement_id": str(statement_id or ""), "proof_no": proof_number,
                "within_call": within,
                "streak": out["projected"], "need": out["need"],
                "projected": out["projected"], "streak_ok": out["streak_ok"],
                "same_sha": True,
                "candidate_verdict": str(v.get("verdict") or ""),
                "candidate_axis": candidate_axis,
                "candidate_defect_step": v.get("defect_step"),
                "reading_why": ("这一签的轮数由 V 的连判循环给出（同一趟送审内第几轮）；"
                                "台账历史行不参与这一趟的发签判定"),
            }
        else:
            material = {
                "statement_id": str(statement_id or ""), "proof_no": proof_number,
                "state": out["state"],
                "streak": out["streak"],
                "need": out["need"],
                "projected": out["projected"], "streak_ok": out["streak_ok"],
                "same_sha": same_sha, "candidate_verdict": str(v.get("verdict") or ""),
                "candidate_axis": candidate_axis,
                "candidate_defect_step": v.get("defect_step"),
                "reading_why": str(reading.get("why") or reading_problem)[:400],
            }
        out["material"] = dict(material)
        # ---- 没有判断面 ⇒ checked=False（业主 2026-10-29：「装配没接上时秘书判定必须报
        # checked=False 且不放签」）。这一格必须排在"地板没过"之前：那一支会报
        # `checked=True`＋"连续次数不够"，而装配缺失时票数根本不再增长（没判成的行既
        # 不算票也不清零）—— 于是"没有秘书"会被读成"再签几次就有了"。
        # 地板读数先算完再返回：调用方仍能看到 streak/need/streak_ok（那是事实），
        # 而"这一趟没有人判"由 checked=False 说。
        if self.seam is None or not self.enable_model:
            out["reason"] = ("这一名秘书没有判断面（没有缝 / 开关关着）⇒ 判定没查成："
                             "不放签（checked=False 不是「可以签」，也不是「次数不够」）")
            self._note_sign_issuance(out, task_id=task_id)
            return out
        if not out["streak_ok"]:
            # 地板没过 ⇒ 不问模型（也不给它把门槛判过去的机会）。这一句只是"这一转还
            # 不算一票"的读数，不是终局：终局由 `agent_v.core` 的循环给（签 / 打回）。
            out.update(checked=True, issue=False, decision=SIGN_WITHHOLD,
                       reason=(f"连续 clean（秘书轴）{out['projected']}/{out['need']} 次"
                               f"（{'这一趟送审内' if within is not None else '台账历史读数'}"
                               f"）⇒ 这一签不发；门槛是 {int(out['need'])} 次连续的「没问题」"
                               + ("；台账历史行不参与这一趟的判定"
                                  if within is not None else "")),
                       basis=list(out["basis"]))
            self._note_sign_issuance(out, task_id=task_id)
            return out
        got = self.judge("sign_issuance", material, task_id=task_id)
        out["cost"] = dict(got.get("cost") or {})
        if not got.get("checked"):
            out["reason"] = (f"发签决定没查成（{str(got.get('reason') or '')[:200]}）⇒ 不放签"
                             "（checked=False 不是「可以签」，也不是「不签发」这一档）")
            self._note_sign_issuance(out, task_id=task_id)
            return out
        decision = str(got.get("decision") or "").strip()
        if decision not in SIGN_ISSUANCE_VERDICTS:
            # 词表外（含历史那一格「判不了」）⇒ 不采信：判成"没查成"，不是"不签发"。
            out["reason"] = (f"结论 {decision!r} 不在 {list(SIGN_ISSUANCE_VERDICTS)} 里 ⇒ "
                             "不采信：这一格按「没查成」读（不放签）")
            self._note_sign_issuance(out, task_id=task_id)
            return out
        out.update(checked=True, decision=decision, issue=(decision == SIGN_ISSUE),
                   reason=str(got.get("reason") or ""),
                   basis=list(got.get("basis") or []))
        if out["issue"]:
            # ---- 落地那一步也在秘书这一侧（业主 2026-10-29 追加口径）----
            #
            # 原话：「由 V 的秘书判定并落盘（… 满足"连续 3 次 clean"才调
            # `verifications.sign_statement` 翻 `bits.evidence`）」。
            # `append_ledger=False`：台账那一行是 `AgentV` 先落的（正本先落），
            # 本方法只翻位 —— 同一个 verification_id 在台账上绝不出现两次。
            self._land_sign_issuance(out, proof_text=str(proof_text or ""),
                                     proof_no=proof_no, row=row)
        self._note_sign_issuance(out, task_id=task_id)
        return out

    def sign_recipient(self) -> str:
        """这一签的收方秘书（`secretary:F` / `secretary:B`；读不到 ⇒ 空串）。

        2026-11-02 业主口径：V 只颁发，手稿块与台账位由收方秘书落；收方 = V 的
        parent（谁送审谁收签）。身份只有一个来源：`conductor.current_parent()`（运行期
        `calling_as` 挂上来的那一位，不是模型给的一个参数，也不是"谁是 V 就谁落"）。
        读不到就回空串 —— 那一档能颁发、不能落块（`vsigns.land` 会受控拒绝
        `not_a_secretary`），不许拿 `self.role`（那是 V 自己的角色）去凑一个收方。
        """
        from . import conductor as _CND

        _pid, prole = _CND.current_parent()
        try:
            from . import vsigns as _VS

            return _VS.secretary_id(prole)
        except Exception:  # noqa: BLE001 —— 读不到就"没有收方秘书"，不猜
            return ""

    @property
    def actor_label(self) -> str:
        """这一名秘书在"落签"这一步的身份值（`secretary:F` / `secretary:B`；读不到 ⇒ 空串）。

        为什么不是简单的 `secretary:{self.role}`：V 的秘书不是收方 —— 收方是 V 的 parent
        那一侧（`sign_recipient()` 读的就是它）。只有收方秘书自己的实例（角色 F / B）才按
        自己的角色。V 的秘书拿 `secretary:V` 去凑一个 `by=` 会被 `vsigns.land` 受控拒绝
        `not_a_secretary`；把它折成"随便一个 F/B"更是猜。
        """
        from . import vsigns

        own = vsigns.secretary_id(self.role)
        return own or self.sign_recipient()

    def land_unregistered_sign(self, envelope: Mapping[str, Any]) -> dict[str, Any]:
        """落一份未在册的 V 签（2026-11-03 件三：落签只经秘书这一侧）。

        `envelope` = :func:`vsigns.issue` 的整份返回（不是里面那个 `envelope` 子字典）：
        V 只把这一份交过来，落点（块 + 台账位）由本方法判 ——

        - 块：签文件里的 `artifact_path`（未在册没有命题号，落点就是那一份手稿）；
        - 台账位：未在册没有命题行可翻 ⇒ `ledger_bit=False`（不在这里造一格）；
        - 落签者：`self.actor_label`（收方那一位；空串 ⇒ `vsigns.land` 的
          `not_a_secretary` 会把它拒掉，校验不绕过）。

        返回 `vsigns.land` 的读数（另带 `envelope_to` / `artifact_sha`，供调用方核对）。
        不在颁发这一档里落签：`issue` 没成功（`written` / `idempotent` 都不是真）⇒
        `code="not_issued"`、零字节 —— 盘上可能残留旧签文件，不许拿它冒充这一趟。
        """
        from . import vsigns

        issued = dict(envelope) if isinstance(envelope, Mapping) else {}
        doc = dict(issued.get("sign") or {}) if isinstance(issued.get("sign"), Mapping) else {}
        out: dict[str, Any] = {
            "checked": False, "landed": False, "state": "refused", "code": "",
            "by": self.actor_label, "artifact_sha": "", "manuscript_id": "",
            "body_mismatch": False, "manuscript_write": {}, "ledger_bit": "not_attempted",
            "ledger_why": "", "sign_recorded": False, "reason": "",
            "envelope_to": "",
        }
        if not (issued.get("written") or issued.get("idempotent")):
            out.update(code="not_issued",
                       reason=("这一份签没有颁发成功（`written` / `idempotent` 都不是真）⇒ "
                               "没有可落的东西：不落块、不翻位（零字节）"))
            return out
        if out["by"] not in vsigns.SECRETARY_OF:
            out.update(code=vsigns.NOT_A_SECRETARY,
                       reason=(f"`by={out['by']!r}` 不是收方秘书 ⇒ 不落签（一个字节都不写）："
                               f"只认 {list(vsigns.SECRETARY_OF)}"))
            return out
        sha = str(doc.get("artifact_sha") or "")
        if not sha:
            # `issue` 的返回里 `path` 是 `out/vsigns/<sha>.json`：文件名就是 sha。
            name = str(issued.get("path") or "").rsplit("/", 1)[-1]
            sha = name[:-5] if name.endswith(".json") else name
        out["artifact_sha"] = sha
        env = vsigns.sign_envelope(doc)
        out["envelope_to"] = str(env.get("to") or "")
        # 与 `vsigns.land` 同一条判据：信封写了收件人才比对；旧签没有信封（`to=""`）
        # 按落签那一侧的规矩走，不在秘书这一层凭空收紧（84 的未在册签就是旧写法）。
        if env.get("to") and env.get("to") != out["by"]:
            out.update(code="addressed_to_another_secretary",
                       reason=(f"这一签的信封写给 {out['envelope_to']!r}，不是 {out['by']!r} ⇒ "
                               "不落（零字节：别的秘书的签不许被这一位落）"))
            return out
        root = self.store.root if self.store is not None else self.root
        landed = vsigns.land(
            root, artifact_sha=sha, by=out["by"],
            manuscript_path=str(doc.get("artifact_path") or ""),
            store=None, statement_id="", proof_no=doc.get("proof_no"),
            # 未在册没有命题行可翻：台账位这一路不翻、也不许在这里造一格。
            ledger_bit=False)
        out.update(landed)
        out["by"] = str(landed.get("by") or out["by"])
        out["artifact_sha"] = str(landed.get("artifact_sha") or out["artifact_sha"])
        return out

    def _land_sign_issuance(self, out: dict[str, Any], *, proof_text: str,
                            proof_no: Any, row: Mapping[str, Any] | None) -> None:
        """把"签发"这个决定落成一份签（2026-11-08 起：不碰 `statements`）。

        三态：签颁发了（`issued=True`）/ 没有可落的那一行（没有 store 或没有 row）/
        颁发了但块没落（`vsign` / `manuscript_write` 自己报的理由）。三种都不改变
        `issue` 这一个决定 —— 决定是决定，落地是落地（`draft/125` 三态纪律）。

        为什么不再调 `verifications.sign_statement`：那条会在
        `store.tx("statements")` 里翻第 3 位、抬 `kind`、现算 `grade`。业主 2026-11-08
        的口径是「V 现在只对手稿负责，不该看台账了」「第几份证明、什么等级都是 B 秘书
        录入时关心且需负责的」⇒ V 的签只落在稿上（侧文件 + 九格块），命题行由 B 收录时
        按正文 sha 认领。`sign_statement` 保留给历史直调 / 夹具（`flip=True` 那条兼容门）。
        """
        from . import verifications as _VR

        # 这一格是"在原句上追加一句"：原先五条支各读一次 `out.get("reason")`，
        # 而它在本方法里直到写回之前没有任何一处改过 ⇒ 读一次就够。
        prior = str(out.get("reason") or "")
        if self.store is None:
            out["reason"] = (f"{prior}；但这一名秘书没有 store "
                             "⇒ 决定是「签发」，而落签那一步落不了（换装配："
                             "`for_role_wired(..., store=<本工作区的 store>)`）")
            return
        if not isinstance(row, Mapping) or not str(row.get("verification_id") or ""):
            out["reason"] = (f"{prior}；但没有可落的那一行"
                             "（`record_verification` 的返回行没递进来）⇒ 只落了决定")
            return
        try:
            writeback = _VR.land_sign_without_ledger(
                self.store, row=dict(row),
                within_call=out.get("within_call"),
                need=out.get("need"), review_call=str(out.get("review_call") or ""),
                by=self.sign_recipient(),
                manuscript=str(row.get("manuscript") or ""))
        except Exception as exc:  # noqa: BLE001 —— 落签失败要如实报（台账那一行已在盘上）
            name = type(exc).__name__
            out["writeback"] = {"written": False, "sign_issued": False,
                                "reason": f"落签没成（{name}: {exc}）"}
            out["reason"] = (f"{prior}；落签没成"
                             f"（{name}: {exc}）⇒ 签没落，台账那一行留着")
            return
        out["writeback"] = dict(writeback)
        out["manuscript_write"] = dict(writeback.get("manuscript_write") or {})
        out["issued"] = bool(writeback.get("sign_issued"))
        if not out["issued"]:
            out["reason"] = (f"{prior}；但落签没落成："
                             f"{str(writeback.get('reason') or '没有理由')}")
        elif not out["manuscript_write"].get("written"):
            out["reason"] = (f"{prior}；签已颁发，但手稿块没落"
                             f"（{str(writeback.get('reason') or '没有理由')}）")
        else:
            out["reason"] = (f"{prior}；签已颁发并由收方秘书落回手稿"
                             "（命题行由 B 收录时按正文 sha 认领）")

    def _note_sign_issuance(self, out: Mapping[str, Any], *, task_id: str = "") -> None:
        """把"发不发签"这一行落进决定台账（`before` = 台账读数，`after` = 决定）。

        为什么单独一个私有方法（而不再塞进 `decide_sign_issuance` 的每一支）：返回句有
        六条路（读不成 / 没查成 / 地板没过 / 判不了 / 词表外 / 判了），而每一条都要
        留痕 —— 六处各写一遍必然漏一处，而漏的那一处正好会是"没发签"的那条路。
        """
        self.note_decision(
            duty=2, kind=KIND_DECISION,
            decision=str(out.get("decision") or JUDGE_UNCHECKED),
            reason=str(out.get("reason") or ""),
            basis=list(out.get("basis") or []),
            target={"sign_issuance": str(out.get("statement_id") or "")},
            judge={k: out.get(k) for k in
                   ("checked", "issue", "decision", "streak", "need", "streak_ok",
                    "projected", "same_sha", "state", "reading", "cost",
                    "within_call", "ledger_streak", "review_call")},
            before=json.dumps(dict(out.get("material") or {}), ensure_ascii=False,
                              sort_keys=True, default=str)[:2000],
            after=(f"issue={bool(out.get('issue'))}；decision={out.get('decision')!r}"
                   f"；连续 {out.get('projected')}/{out.get('need')}"),
            fail_open=False,
        )

    def wash_v_reply(self, *, reply: str, verdict: str = "", defect_step: Any = None,
                     statement_id: str = "", proof_no: Any = 1,
                     task_id: str = "", label: str = "") -> dict[str, Any]:
        """把 V 的意见洗成能转达给 F 的文本（业主 2026-10-29 的 C 段）。

        仿 :meth:`wash_dependency_face` 的三态，但有一处刻意不同：那一支洗失败时
        返回原稿（那是 F 自己的稿子，退回原文不是泄露），这一支洗失败时不输出原文
        —— V 的回复正文不许原样递到 F 面前（业主口径：洗稿转达；`draft/125` §二 C
        「洗不出来 ⇒ 受控拒绝、不输出原文」）。所以 `refused=True` 时 `text` 恒空串。

        ## findings 必须逐字可回溯（`judges._ground` 的纪律）
        模型给的每条 `findings[*].quote` 都要在 V 的回复原文里逐字找到（只压空白差异），
        找不到的落进 `dropped` 并不采信；一条都没落地、而模型又给了 findings ⇒
        `refused="findings_not_grounded"`（说明这一次洗出来的话在原文里没有着落）。
        洗过的那份文本 = 模型给的 `text`（那是转述，不是原文）。

        ## 落痕
        进 `decisions_path()` 那本账（`before` = V 原文、`after` = 洗过的文本、
        `changes` = 逐条改了哪几处、`judge` = 这一趟的洗稿读数）。不写 `relay.jsonl`
        —— 那一份是转达链自己的账，两件事写在同一处会让"谁洗的"与"谁转达的"分不开。

        返回键：`checked` / `washed` / `text` / `findings` / `dropped` / `refused` /
        `reason` / `actor` / `changes` / `cost` / `material`。
        """
        from . import judges as _J   # 惰性：落地判据（`judges._ground`）的唯一实现在这里
        from . import verifications as _VR

        out: dict[str, Any] = {
            "checked": False, "washed": False,
            #: 洗不动时恒空串：这一格不许退化成"原文"（那正是要挡的那件事）。
            "text": "", "findings": [], "dropped": [], "refused": "",
            "reason": "", "actor": f"secretary-{self.role}", "changes": [], "cost": {},
            "material": {}, "statement_id": str(statement_id or ""), "proof_no": 0,
        }
        try:
            out["proof_no"] = int(_VR.as_proof_no(proof_no) or 0)
        except (TypeError, ValueError):
            out["proof_no"] = 0
        body = str(reply or "").strip()
        if not body:
            out.update(checked=True, refused="empty_reply",
                       reason="V 的回复正文是空的 ⇒ 没有可洗的东西（也就没有可转达的意见）")
            self._note_wash(out, reply="", task_id=task_id)
            return out
        if self.seam is None or not self.enable_model:
            out.update(refused="secretary_unavailable",
                       reason=("这一名秘书没有判断面（没有缝 / 开关关着）⇒ 洗不出来："
                               "受控拒绝，不输出 V 的原文（洗稿转达是这一档的唯一出口）"))
            self._note_wash(out, reply=body, task_id=task_id)
            return out
        material = {"v_reply": body[:JUDGE_MATERIAL_CAP],
                    "ledger_row": {"verdict": str(verdict or ""), "defect_step": defect_step},
                    "label": str(label or "")}
        out["material"] = dict(material)
        prompt = (
            "把下面这段验证者（V）的审阅回复改写成转达给作者（F）的工作意见。"
            "只回一个 JSON 对象，字段：\n"
            "text（改写后的正文：第三人称、按「指到哪一步 / 问题是什么 / 下一步补什么」"
            "分条写；不要照抄原文的句子，不要复述 V 的第一人称口气，"
            "不要评价作者的思路好不好；只写能据以动手的结论）、\n"
            "findings（字符串数组或对象数组：每一条给 `quote` = 你在原文里逐字引用的那一句、"
            "`why` = 它说明什么问题。`quote` 必须与原文逐字相同（只允许空白差异），"
            "改了字就不采信）、\n"
            "step（整数或 null：这一条意见指向第几步）。\n"
            "不许写原文里没有的意思；原文没指出缺陷时，text 就写「这一轮没有指出缺陷」"
            "与它实际核过的东西，findings 给空数组。\n\n"
            + _judge_material(material))
        try:
            data, call = self.seam.ask_json(prompt, system=_wash_v_system(),
                                            task_id=task_id, note="secretary:wash_v_reply")
        except Exception as exc:  # noqa: BLE001 —— 调用失败 = 洗不出来（受控拒绝）
            out.update(refused="wash_call_failed",
                       reason=f"洗稿调用失败（{type(exc).__name__}: {exc}）⇒ 不输出原文")
            self._note_wash(out, reply=body, task_id=task_id)
            return out
        if not getattr(call, "ok", False) or not isinstance(data, Mapping):
            out.update(refused="wash_no_reply",
                       reason=(f"洗稿没拿到可用的 JSON（{getattr(call, 'problem', '') or 'no_reply'}:"
                               f"{str(getattr(call, 'detail', '') or '')[:160]}）⇒ 不输出原文"))
            self._note_wash(out, reply=body, task_id=task_id)
            return out
        washed = str(data.get("text") or "").strip()
        kept, dropped = _J._ground(body, data.get("findings"))
        out["findings"] = kept
        out["dropped"] = dropped
        proposed = data.get("findings")
        if not washed:
            out.update(refused="wash_empty_text",
                       reason="模型没有给出改写后的正文 ⇒ 洗不出来（不输出原文）")
            self._note_wash(out, reply=body, task_id=task_id)
            return out
        if isinstance(proposed, (list, tuple)) and proposed and not kept:
            # 给了 findings、而一条都引不回原文 ⇒ 这一遍洗出来的话没有着落。
            out.update(refused="findings_not_grounded",
                       reason=(f"模型给了 {len(proposed)} 条 findings，没有一条能逐字落回 "
                               "V 的原文 ⇒ 不采信这一遍（不输出原文）"))
            self._note_wash(out, reply=body, task_id=task_id)
            return out
        if washed == body:
            # 逐字相同 = 没有洗过（这一档最危险：它长得像"洗好了"）。
            out.update(refused="wash_verbatim",
                       reason="改写后的正文与 V 的原文逐字相同 ⇒ 不算洗过（不输出原文）")
            self._note_wash(out, reply=body, task_id=task_id)
            return out
        out.update(checked=True, washed=True, text=washed,
                   reason=(f"洗过：{len(kept)} 条 findings 逐字落回原文"
                           + (f"，{len(dropped)} 条引不到被丢弃" if dropped else "")))
        out["changes"] = [{"field": "text", "from": "（V 的原文，不转达）", "to": washed,
                           "why": "洗稿转达：原文不外发（业主 2026-10-29 的 C 段）"}]
        out["changes"].extend(
            {"field": "findings", "from": str(d.get("quote") or ""),
             "to": "（丢弃）", "why": str(d.get("why") or "引文落不回原文")}
            for d in dropped)
        self._note_wash(out, reply=body, task_id=task_id)
        return out

    def _note_wash(self, out: Mapping[str, Any], *, reply: str, task_id: str = "") -> None:
        """把洗稿这一行落进决定台账（`before` = 原文、`after` = 洗过的文本）。

        与 :meth:`_note_sign_issuance` 同一条理由：返回句有六条路，每一条都要留痕。
        注意 `before` 落的是原文：那本账是秘书自己的账（不是给 F 看的），
        而"洗的时候原文长什么样"是复核这一遍洗得对不对的唯一依据。
        """
        self.note_decision(
            duty=2, kind=KIND_DECISION,
            decision=("已洗稿" if out.get("washed") else "洗不出来"),
            reason=str(out.get("reason") or ""),
            basis=[f"refused={out.get('refused') or '（没拒）'}",
                   f"findings={len(out.get('findings') or [])}",
                   f"dropped={len(out.get('dropped') or [])}"],
            target={"wash_v_reply": str(out.get("statement_id") or "")},
            judge={k: out.get(k) for k in
                   ("checked", "washed", "refused", "findings", "dropped",
                    "statement_id", "proof_no")},
            before=str(reply or "")[:2000],
            after=str(out.get("text") or "")[:2000],
            changes=[dict(c) for c in (out.get("changes") or [])][:20],
            fail_open=False,
        )

    def not_applicable_nontriviality(self, *, statement_full: str, kind: str = "",
                                     task_id: str = "", stmt_id: str = "",
                                     record: bool = True) -> dict[str, Any]:
        """概念 / 定义行的档位读数：`不适用`（`level=None` + 台账里 `applicable=False`）。

        ## 号（2026-10-26，D16）
        落行带 `stmt_id`（概念行在 `write_concept_row` 里已经有号）；幂等比对仍按正文
        （同一段定义只落一行），但那一行与命题行的关系靠号，不靠文本。

        ## 为什么它不是"未判"（2026-10-26，业主的口径）
        "未判"说的是"该判而没判"（没缝 / 超时 / 缺证明正文 / 正文被截断），它的处置是
        "下次再判一次"；"不适用"说的是"这一问对它不成立"——概念行没有证明正文，四项力气
        读数一项都取不到，再判一次也不会有别的结论。两件事折成同一个词，读的人就会把
        "结构上不需要判"读成"漏判了"（真机 mp3-r3：30 条概念行的非平凡度一条记录都没有，
        而读侧对"没有记录"与"不需要记录"都只印一个"未判"）。

        ## 落什么
        台账那一行：`nontriviality: null` + `label: ""` +
        `basis: "不适用：概念行没有证明正文，不做力气判档"` + `applicable: false`。
        最后那一格是给读侧的判据：:func:`nontriviality_of` 据它把 `tri` 读成
        `not_applicable`（而不是 `unknown`），于是页面能把两个词分开印。

        ## 为什么空正文也照落这一行
        `judge_statement` 对 0 字命题是受控拒绝（不落台账），因为那说明"调用方给错了栏"。
        概念行不同：待补定义的概念（`pending_definition`）本来就有一段空正文，而它的
        "不适用"与定义到没到无关（有没有定义，它都没有证明）。所以这一支按正文 sha 落行，
        空正文的 sha 与所有待补概念共用那一行 —— 它们读出来的词也确实一样。

        ## 幂等（同一段正文只落一行）
        这一档的结论不随时间变（"有没有证明正文"是结构事实），所以已经落过的那一段
        正文不再追加：台账是 append-only，同一句话抄第二遍只会让它变长而不增加任何读数
        （而 `nontriviality_of` 是逐行扫的，长度就是页面一次请求的代价）。
        反过来，这一段正文还没有那一行时照落 —— 存量概念行（改前直写进来的那些）
        因此会在它下一次经秘书那一笔时被补上这一格，不需要一次全库迁移。

        ## 判/落拆段（NT2）：`record`
        B 的收录动作在写台账之前先判一次（`record=False`，零调用、零写盘）；
        等号拿到了再由 `write_concept_row` 那一笔调这里（`record=True`），按号幂等落行。
        """
        out: dict[str, Any] = {
            "checked": True, "decision": "", "applicable": False,
            "basis": [NONTRIVIALITY_NOT_APPLICABLE_BASIS],
            "reason": (f"kind={kind or '（空）'!r} 没有证明正文 ⇒ 判档这一格不适用"
                       "（不是「判不了」：它是结构上不需要判，不是该判而没判）"),
            "nontriviality": NONTRIVIALITY_UNJUDGED, "label": "",
            "nontriviality_tri": "not_applicable",
            "nontriviality_basis": NONTRIVIALITY_NOT_APPLICABLE_BASIS,
            "effort": {}, "effort_score": 0, "text_truncated": False,
            "cost": {"ledger": "", "reason": "没发调用（概念行没有证明正文 ⇒ 判档不适用）"},
        }
        if not record:
            out["recorded"] = False
            out["record_reason"] = ("判/落拆段：这一趟只判；等 write_concept_row 拿到号"
                                    "之后才落那一行")
            return out
        root = getattr(self, "root", None)
        if root is None:
            return out
        got = self.record_nontriviality(out, stmt_id=stmt_id, path_group=0,
                                       statement_full=statement_full,
                                       judged_body_sha256=_judged_body_sha(statement_full))
        out["recorded"] = bool(got.get("recorded"))
        out["record_reason"] = str(got.get("reason") or "")
        if got.get("tri") == "unrecorded":
            out["nontriviality_tri"] = "unrecorded"
        return out

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

    #: 发出口这条判据管的两条通道（其余形状没有"内容 ↔ 收件面"这件事：
    #: `summon_many` 本来就是一次派 N 件，`summon` 的收件人是 `role` 一格）。
    FACE_SHAPES: tuple[str, str] = ("handoff", "message")

    def _face_text(self, shape: str, payload: Mapping[str, Any]) -> str:
        """这一条真正会被读的那一段正文（`handoff` 的 summary+body；`message` 的 subject+body）。

        为什么是这两段而不是整个载荷：收件人读到的是正文，JSON 的键名不是内容。
        旧名（`brief` / `title`）与正名 `summary` 一样算，判据认的是它会怎么被读。
        """
        body = payload.get("body") if isinstance(payload, Mapping) else ""
        if str(shape) == "message":
            head = str(payload.get("subject") or "")
        else:
            head = str(payload.get("summary") or payload.get("brief")
                       or payload.get("title") or "")
        return f"{head}\n{body or ''}"

    def split_dispatch_reason(self, shape: str, tokens: Sequence[str]) -> str:
        """「这一条里有 N 件派活」那一句拒信 —— 拆分方案逐字写全（给谁一条、怎么发）。

        业主点名的形态是一条稿子里装着给 A 与给 D 两件活，所以拒信必须回得出
        "给 A 一条、给 D 一条"这个形状，而不是一句"请重写"。收件人写法用原稿里的那个
        （`A` / `A1` 都行：它认得自己写的那一个）。
        """
        names = [str(t) for t in tokens]
        count = len(names)
        if count < 2:
            return ""
        if count == 2:
            options = f"`{shape}(to={names[0]})` 与 `{shape}(to={names[1]})`"
        else:
            options = ("、".join(f"`{shape}(to={t})`" for t in names[:-1])
                       + f" 与 `{shape}(to={names[-1]})`")
        given = "、".join(f"给 {t}" for t in names)
        return (f"这一条里有 {count} 件派活（{given}），一份稿子只能交给一个收件人 ⇒ "
                f"请按收件人拆成 {count} 条：{options}"
                "（或直接用 `summon` 的台账，不要在稿子里抄一遍）。")

    def judge_recipient_face(self, shape: str, payload: Mapping[str, Any], *,
                             face: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """发出口的第二件事（业主 2026-10-26）：这一份内容与它的收件面相符吗。

        它与 :meth:`judge` 那一族是同一件事的两半：:meth:`judge` 判"这活该怎么派"
        （要叫模型），这一格判"这份稿子的内容与收件面配不配"（纯机械、零模型调用）。
        判断落在发出口，所以两条通道（`handoff` 手稿 / `message` 投递）共用一份，
        不再各写一道 if 链。

        两档（都得由 :meth:`optimize_outbound` 在写盘之前问）：

        - 公告栏里点名并下指令 ⇒ 不符：`to` 是公共频道而正文点名了名册成员、又带指令语气，
          那是对一个具体代理下指令，不是公告（判据本体是 `_public_addressee` +
          `PUBLIC_DIRECTIVE_MARKS`，由调用方注入，本文件不抄第二份）；
        - 一份稿子里装了多件派活 ⇒ 不符：正文里有两个以上名册成员落在"派活对象"的位置上
          （判据见 :func:`dispatch_targets`），而一次派活只能有一个收件人。

        返回（三态不许折平，`fits` 就是那一格）：

        | 结局 | 返回 |
        |---|---|
        | 相符 | `fits=True` + `targets` / `named` 读数 |
        | 不符 | `fits=False` + `refused`（既有码）+ `reason`（给本体读的改法） |
        | 判不了 | `fits=None` + `reason`（名册读不成 / 不是这两条通道）⇒ 放行并留痕 |

        `refused` 用的是既有码：公告那一档沿用 `public_is_not_a_conversation`（与
        `message` 那条路同一个词，它同时是那条投递闸的读数取值），多件派活那一档用
        `refusals.PRECONDITION_REASON`（`invalid_params` = 这次调用本身不成立）。
        判据不新造理由码。两档的 `refusal_reason` 因此不一样：后者是任务台账那张受控词表里
        的取值，前者不是（公告那条码从来只在读数里用）—— 照各自的既有落点写，不互相冒充。
        """
        out: dict[str, Any] = {"checked": False, "fits": None, "refused": "",
                               "refusal_reason": "", "reason": "", "targets": [],
                               "named": "", "shape": str(shape), "to": "", "decision": ""}
        if str(shape) not in self.FACE_SHAPES:
            out["reason"] = (f"{shape} 不在发出口这条判据的面上（"
                             "一次派活只能有一个收件人，说的是 handoff / message）")
            return out
        body = payload if isinstance(payload, Mapping) else {}
        out["to"] = str(body.get("to") or body.get("role") or "")
        got = dict(face) if isinstance(face, Mapping) else {}
        if not got:
            out["reason"] = ("收件面没接上（调用方没有注入名册与公告那两条判据）"
                             "⇒ 这一格判不了（没查成不是相符）")
            return out
        if not got.get("checked"):
            out["reason"] = (f"收件面没读成（{got.get('problem') or '名册不可用'}）"
                             "⇒ 这一格判不了（没查成不是相符）")
            return out
        out["checked"] = True
        out["named"] = str(got.get("named") or "")
        public = got.get("public_refusal")
        public = dict(public) if isinstance(public, Mapping) else {}
        if str(public.get("refused") or ""):
            out.update(fits=False, refused=str(public["refused"]),
                       reason=str(public.get("error") or ""),
                       decision=DECISION_READDRESS)
            return out
        members = [m for m in (got.get("members") or ()) if isinstance(m, Mapping)]
        if not members:
            # 名册读成了，可上面一个人都没有（顶层还没派过活）⇒ 正文里点名谁都对不上，
            # 这一格判不了。三态：它不是"相符"（那是把没查成折成查过了）。
            out["reason"] = ("名册上没有一个可通话的人 ⇒ 正文里的派活对象一个都对不上，"
                             "这一格判不了（没查成不是相符）")
            return out
        tokens = dispatch_targets(self._face_text(shape, body), members)
        if len(tokens) >= 2:
            shown = [str(t["token"]) for t in tokens]
            out.update(fits=False, targets=shown, refused=R.PRECONDITION_REASON,
                       refusal_reason=R.PRECONDITION_REASON,
                       reason=self.split_dispatch_reason(str(shape), shown),
                       decision=DECISION_REARRANGE)
            return out
        out.update(fits=True, targets=[str(t["token"]) for t in tokens],
                   reason=("收件面相符：正文里没有第二个落在『派活对象』位置上的人"
                           if not tokens else
                           f"收件面相符：正文里只点到 {tokens[0]['token']} 一个派活对象"))
        return out

    def optimize_outbound(self, shape: str, payload: Mapping[str, Any], *,
                          admission: Any = None, base: str = "",
                          face: Mapping[str, Any] | None = None
                          ) -> dict[str, Any]:
        """职责 1：格式与内容优化（发件前）。

        不改变实质主张：不替本体承诺、不改结论、不加证据（`draft/53` §2 的"不许做"）。所以这里的产物是
        "建议 + 并列候选"，而不是改写后的载荷：本体读到的仍是它自己那一份（改不改由它决定）。两段分得很清
        （这是"切勿全写死成机器判据"的落点）：
        - 第一段是预筛（确定性）：参数表 / 必填 / 工具真名的检查，来自既有声明；
        - 第二段是判断（只有 :meth:`should_engage` 说该介入时才走）：错名映到哪一个候选（:meth:`judge` 的
          `tool_name` 一类，一次模型调用 + 台账）。判断没查成 ⇒ 结论仍是预筛那一份，且台账里
          `judge.checked=False` 写明。
        另加一件同样是判断的事：内容与收件面相符吗 ——
        :meth:`judge_recipient_face`（`face=` 是它要的收件面读数，由调用方注入；判据本体不在这里）。
        判"不符"的那一档是受控拒绝：这一条一份稿子都不出去，拒信与结论一起进返回值与台账。
        fail-open：超时/自己出错 ⇒ 原样放行 + 台账留痕（`fail_open=True`）。
        """
        original = dict(payload)
        # ---- 两段式：确认/拒绝那两个字段是协议字段，
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
            # ---- 洗格式。位置：判"该不该介入"之前 ——
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
            # ---- 发出口的第二件事（业主 2026-10-26）：这一份内容与它的收件面相符吗。
            # 纯机械、零模型调用；`face=` 是收件面读数（名册成员 + 公告里点名了谁），
            # 由调用方注入 —— 与 `admission=` 同一种做法，判据本体不在这里。
            face_reading = self.judge_recipient_face(shape, washed, face=face)
            face_refused = face_reading.get("fits") is False
            if shape == "message":
                # `R8`：`message` 是跨智能体的结构化交互 ⇒ 秘书接管（所有者裁定逐字
                # "如果有些形状涉及到结构化交互，则需要秘书接管"）。接管 = 预筛报警 +
                # 建议 + 台账（不替代 `_do_message` 的硬闸，也不改载荷）。
                #
                # 为什么这一支不跑上面那条委派预筛：`message` 没有 `action`/`params`/`tool`
                # 三件，而预筛会把 `to` 当角色名去查能力表 —— 对公共频道收件人（`ALL`）会报出
                # 两条"读不到这个收件人的角色定位"的假警（频道名不是角色）。它的整个预筛面
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
            # 内容与收件面不符时，结论沿用 `DECISIONS` 里既有的那一档
            # （建议重排 = 按收件人拆开；建议改派 = 改成给那一个人的私聊）。
            if face_refused:
                decision = str(face_reading.get("decision") or decision)
            changes = list(wash.get("changes") or ())
            # ---- 台账那一行（一次调用一行；两段式的三档各带自己的 `decision`/`kind`）
            proposal_arg: str | None = None
            fingerprint = ""
            reason = "；".join(alarms) or "没有触发预筛报警（原样放行）"
            if face_refused:
                # 这一条不出去了：台账里的那一句就是退回本体的理由（逐字含拆分方案 / 改法）。
                reason = str(face_reading.get("reason") or reason)
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
                          ) + "｜没有执行：等父用 accept_proposal / reject_proposal 表态"
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
            judge_cell = dict(judged)
            if face_reading.get("checked"):
                # 这一格与 `judge` 是同一行里的两件不同的事：判"这活该怎么派"叫了模型，
                # 判"内容与收件面配不配"没叫。`fits` 三态（True / False / None）必须原样落盘，
                # 否则"没查成"与"相符"在纸上长得一样。
                judge_cell.update({"checked": True,
                                   "fits": face_reading.get("fits"),
                                   "targets": list(face_reading.get("targets") or ()),
                                   "named": str(face_reading.get("named") or ""),
                                   "reason": str(face_reading.get("reason") or "")})
                if face_reading.get("decision"):
                    judge_cell["decision"] = str(face_reading["decision"])
            rec = self.note_decision(
                duty=1,
                kind=KIND_PROPOSAL if plan["outcome"] else KIND_OPTIMIZED,
                decision=decision,
                reason=reason,
                basis=["specs/<role>.py 的参数表", "tools.build_registry() 的真名"],
                target={"to": to, "action": action}, judge=judge_cell,
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
                   "alarms": alarms, "judge": judge_cell, "engaged": bool(engage),
                   "surface": self.surface_readings(shape, washed, base=base),
                   "fail_open": False, "seq": rec.get("seq")}
            if face_reading.get("checked"):
                # 只在真的判过时才给这一格：老载荷（不是 handoff / message、或收件面没接上）
                # 的键集因此一个字节不变。
                ret["face"] = dict(face_reading)
            if face_refused:
                # 受控拒绝：这一条一份稿子都不出去（循环据此不执行 `_do_handoff`）。
                # 三个键一起给，是因为读的人不同：`problem` 给日志、`face` 给台账、
                # 那一句拒信（`reason`）是给本体下一步照着改的。
                ret.update({"problem": str(face_reading.get("reason") or ""),
                            "refused": True})
                return ret
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

    @staticmethod
    def _unique_rename(key: Any, props: Any, fixed: Mapping[str, Any]) -> str:
        """错名 → 唯一候选键名；候选不唯一 / 目标已在 `fixed` ⇒ 空串（一个字节都不动）。

        `params` 里那一支与顶层折算那一支问的是同一条判据（唯一候选、且不覆盖真值），
        原先两处各写一遍同一段 `declarations_candidates(...) + len == 1 + not in fixed`。
        """
        cand = declarations_candidates(str(key), props)
        return cand[0] if len(cand) == 1 and cand[0] not in fixed else ""

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
            raw_to = after.get("to")
            role = raw_to if isinstance(raw_to, str) else ""
        else:
            role = role.strip()
        raw_action = after.get("action")
        action = raw_action if isinstance(raw_action, str) else ""
        raw_params = after.get("params")
        # 2026-10-16（业主口径 S2「M 只派活」）：硬拒那一格从"没有角色或没有动作"
        # 收窄成"没有角色 或 既没有动作也没有活"。
        # 原话逐字：「一致改成 task 必填，action 不填」「action 完全不用父代理填」。
        # 真机读数（T5 第 12/13 趟）：M 六次/两次发出 `{"role":"A","task":…}`，而 `tasks`
        # 表里空动作的行 = 0 —— 全死在这一行（它不落行，所以连证据都没留下）。
        # 2026-10-16：活的写法有两处 —— 顶层的 `task`（形状/工具那一面），
        # 以及 `params["task"]`（派活那条路为了给被派者那一趟循环取用而并进去的那一份）。
        # 真机/判据现场：批量派活被拒的理由码是 `unknown_action`，而它其实写了活
        # （只是写在 `params` 里）⇒ 这一格必须两处都认，否则"派活"永远过不去。
        work = str(after.get("task") or (raw_params or {}).get("task") or "").strip()
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
        if props and (raw_params is None or isinstance(raw_params, Mapping)):
            fixed = dict(raw_params or {})
            for key in list(fixed):
                if key in props:
                    continue
                target = self._unique_rename(key, props, fixed)
                if target:
                    # 目标键已经在 `params` 里 ⇒ 不改（改名会覆盖一个真值：
                    # 那是动内容面，不是洗格式）。
                    fixed[target] = fixed.pop(key)
                    changes.append({"where": field, "field": f"params.{key}",
                                    "to": f"params.{target}", "why": "键名归一（唯一候选）"})
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
                target = self._unique_rename(key, props, fixed)
                if target:
                    fixed[target] = after.pop(key)
                    changes.append({"where": field, "field": f"<顶层>.{key}",
                                    "from": str(key), "to": f"params.{target}",
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
                plan["problem"] = (f"请示 {want!r} 是对另一份载荷发的（指纹不一致）⇒ "
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
                          novel: bool = False, reuse: str = "", base: str = "",
                          task: str = "") -> dict[str, Any]:
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
        # ---- 派活审阅（业主 2026-11-13 R2）：D 派 F 的活是不是一个研究方向 ------
        #
        # 与上面那条判断分两问、两本账：
        # - 上面问"这一件该怎么派"（`duplicate_retry` / `rearrange`，落角色台账）；
        # - 这一问"这条派活是不是把一堆方向塞给了一个 F"（`dispatch_fit`，落轴台账
        #   `out/secretary/dispatch_fit.jsonl`）—— 业主：「D秘书要审D的派活，不合适需要
        #   给出提醒」。只提醒不拦：结论并进 `reason`（本体读得到），派活照发。
        # 只在 D→F 且拿到了派活原文时问：`conductor._note_delegation_quality` 那条路
        # 没有原文（`task=""`），在那里问只会拿空材料去问一次模型（白花钱，还可能编一个
        # "不合适"出来）。
        if str(self.role) == "D" and str(to) == "F" and str(task or "").strip():
            fit = self.judge_dispatch_fit(task=task, to=str(to), action=str(action or ""),
                                          params=dict(params or {}))
            if fit.get("checked") and fit.get("verdict") == DISPATCH_FIT_UNSUITABLE:
                # 处置沿用派活轴既有的词（"建议重排" = 按研究方向拆成多个 F），
                # 提醒正文由模型给（它写清了该怎么拆）。不改派活：这只是建议。
                decision = "建议重排"
                reason = f"{reason}；派活审阅：{fit.get('why')}"
                basis = list(basis) + list(fit.get("basis") or [])
        rec = self.note_decision(
            duty=2, kind=KIND_PROPOSAL, decision=decision, reason=reason, basis=basis,
            target={"to": to, "action": action, "input_key": input_key},
            judge=judged, fail_open=False,
        )
        return {"decision": decision, "reason": reason, "basis": basis,
                "duplicates": dups, "alarms": alarms, "novel": bool(novel),
                "surface": surface,
                "judge": judged, "engaged": bool(engaged), "seq": rec.get("seq")}

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
        """F-05 的消费端：把"还没有处理 / 还没有反馈"的东西摆出来（只读，两栏）。

        ## 两栏（不许混成一句）
        | 栏 | 装什么 | 截断 |
        |---|---|---|
        | `running_agents` | 此刻真的在跑的子代理（数量 + 全部编号） | 永不截断 |
        | `pending_items` | 等着接手 / 等着收口的待办项（板项 + 队列请求） | 吃 `limit` 与 :data:`MAX_REMINDERS`，截断量写进 `truncated` |

        一行 `tasks` 落在哪一栏由两处判据决定，两处都在本模块：轴归 :func:`row_axis`
        （代理行 / 板项行 / 顶趟行 / 其它），"还算不算在跑"归 :func:`is_live_agent`
        （两问拆开，才分得清"这一行是什么"与"它还活不活"）。只按
        `status ∈ {pending, running}` 与 `action != "run"` 判，板项行（`status` 恒为
        `pending`）就会被写成 `state="running"` —— 板项与在跑的子代理在读数上同形。

        口径：生产端是机器（`search_requests` / `reprocess_requests`
        的 pending + 那些三态行），消费端是各角色自己的秘书 + M 的秘书（全局）；本方法
        只做"摆出来"这一半，判断归 :meth:`remind_closure`。

        ## 三态与"少了几行"
        `checked=False` + `reason` 是"这一格没读成"（没有 store / 表读不出来），与
        `todos=[]`（读成了、确实没有待办）分开报。两个 `excluded_*` 是"确实有行、但两根轴
        都不进"的显式读数（顶趟行 / 已收口的板项行）—— 少了几行要能被读出来，否则
        "少了几行"会被读成"本来就没有"（静默漂移的另一种形态）。

        ## 返回
        `{"checked","reason","running_agents":{"count","ids","rows"},
        "pending_items":{"count","ids","by_kind","rows"},"todos","count","by_kind",
        "excluded_top_level","excluded_item_closed","truncated":{"shown","total","more"}}`。
        两栏的 `count` / `ids` 都是截断前的真数；`todos` 是两栏的合并视图（既有读点兼容），
        每条 `todo` 是 `{"kind","id","who","state","since","axis"}`。
        """
        if self.store is None:
            return {"checked": False, "reason": "没有 store ⇒ 收件箱这一格没读成",
                    "todos": [], "count": 0, "by_kind": {},
                    "running_agents": {"count": 0, "ids": [], "rows": []},
                    "pending_items": {"count": 0, "ids": [], "by_kind": {}, "rows": []},
                    "excluded_top_level": 0, "excluded_item_closed": 0,
                    "truncated": {"shown": 0, "total": 0, "more": 0}}
        agents: list[dict[str, Any]] = []
        items: list[dict[str, Any]] = []
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
                items.append({
                    "kind": kind,
                    "id": str(row.get("request_id") or ""),
                    "who": who or S.CONDUCTOR_ROLE,
                    "state": "pending" if who else "unclaimed",
                    "since": str(row.get("timestamp") or ""),
                    "attempts": int(row.get("attempts") or 0),
                    # 队列请求是"排队等接手"，不是在跑的子代理 ⇒ 归待办栏。
                    "axis": ROW_AXIS_ITEM_OPEN,
                })
        excluded_top = 0
        excluded_closed = 0
        try:
            for row in self.store.rows("tasks"):
                axis = row_axis(row)
                # "活着的代理"是另一问（`is_live_agent`，2026-10-26 Q27）：轴只说这一行
                # 是什么，"它还算不算在跑"由那个判据回答 —— 这里不许再写成 `axis == agent`，
                # 否则拆分就退化成两个名字指向同一句话（判据 d 钉的就是这件事）。
                if is_live_agent(row):
                    agents.append({"kind": "task", "id": str(row.get("task_id") or ""),
                                   "who": str(row.get("role") or ""), "state": "running",
                                   "since": str(row.get("started_at") or ""),
                                   "axis": ROW_AXIS_AGENT})
                elif axis == ROW_AXIS_ITEM_OPEN:
                    # 板项还没收口：`state` 用既有的 "pending"（没做完），不许再说 "running"
                    # —— 它没有在跑任何东西，是等着人消它。
                    items.append({"kind": "task", "id": str(row.get("task_id") or ""),
                                  "who": str(row.get("role") or ""), "state": "pending",
                                  "since": str(row.get("started_at") or ""),
                                  "axis": ROW_AXIS_ITEM_OPEN})
                elif axis == ROW_AXIS_ITEM_CLOSED:
                    excluded_closed += 1
                elif axis == ROW_AXIS_ROOT:
                    # 顶趟行是"用户发起的那一趟"本身：既不进待办栏，也不进在跑栏，
                    # 但排除了几行要留在读数里，否则"少了几行"会被读成"本来就没有"。
                    excluded_top += 1
                # 其余（代理行的历史终态行等）：两根轴都不进，也不计数 ——
                # 它们不是"被排除的候选"，是已经收过工的旧行。
        except Exception as exc:  # noqa: BLE001 - 同上
            problems.append(f"tasks: {type(exc).__name__}: {exc}")
        total = len(agents) + len(items)
        todos = (items + agents)[:max(1, int(limit))]
        shown = len(todos)
        by_kind: dict[str, int] = {}
        for t in todos:
            by_kind[t["kind"]] = by_kind.get(t["kind"], 0) + 1
        pending_by_kind: dict[str, int] = {}
        for it in items:
            pending_by_kind[it["kind"]] = pending_by_kind.get(it["kind"], 0) + 1
        return {"checked": not problems, "reason": "；".join(problems),
                "running_agents": {"count": len(agents),
                                   "ids": [str(x["id"]) for x in agents],
                                   "rows": agents},
                "pending_items": {"count": len(items),
                                  "ids": [str(x["id"]) for x in items],
                                  "by_kind": pending_by_kind,
                                  "rows": items},
                "todos": todos, "count": shown, "by_kind": by_kind,
                "excluded_top_level": excluded_top,
                "excluded_item_closed": excluded_closed,
                "truncated": {"shown": shown, "total": total,
                              "more": max(0, total - shown)}}

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
        不替本体做事、不伪造反馈）。异步、不阻塞本体。

        `items=None` ⇒ 自己读收件箱（:meth:`closure_reading`，F-05 的消费端）：
        待办项一次最多 :data:`MAX_REMINDERS` 条，在跑的子代理全列不截（业主
        2026-10-26 Q18：截断只作用于待办项 —— 在跑的子必须一个不少地点名）。
        给了 `items` ⇒ 按给的那一份判（一律当待办项那一栏，吃 `MAX_REMINDERS`）——
        "谁盯哪个收件箱"由调用方决定（M 的秘书看全局）；要报在跑的子代理就读自己的
        收件箱，别在这里另判一次（判据只有 :func:`row_axis` / :func:`is_live_agent` 一处）。
        """
        if items is None:
            return list(self.closure_reading()["reminded"])
        given = list(items)
        out: list[dict[str, Any]] = []
        for it in given[:MAX_REMINDERS]:
            one = self._reminder_of(it)
            if one is not None:
                out.append(one)
        self._note_closure(out, running_count=0, pending_count=len(given))
        return out

    def closure_reading(self) -> dict[str, Any]:
        """职责 3 的收尾读数（唯一组装点，2026-10-26 Q18）：两栏真数 + 每条提醒。

        返回 `{"checked","reason","count","running_agents","pending_items",
        "reminded","by_state","by_to","truncated"}`：

        - `running_agents` / `pending_items`：两栏截断前的真数与全部编号；
        - `reminded`：这一次真的要点名的那些（两栏合并，每条带 `axis`）—— 待办项吃
          :data:`MAX_REMINDERS`，在跑的子代理全列不截；
        - `by_state` / `by_to`：只统计待办项，而且是全部待办行（不只是点名的那些）——
          "谁没接手 / 谁没有终态"这句话说的是待办项；在跑的子代理是另一栏（那一栏的
          `state` 恒为 `running`），把它们混进同一张分组表，正是改前那句"running 5 条"
          的来源；只数点名的那几条又会让"待办项 10 条 / pending 5 条"这种加不上的数出现；
        - `truncated`：两栏各自的 `{shown, total, more}`（在跑栏的 `more` 恒为 0）。

        三态与改前逐字一致：读不成 ⇒ `checked=False` + 理由，并落一条 `fail_open=True`
        的台账（"没读成"绝不当成"没有未闭环"）。
        """
        got = self.inbox_todos()
        if not got["checked"]:
            # 读不成不是"没有待办"：如实留痕，绝不当成清零。
            self.note_decision(duty=3, kind=KIND_NOTICE, decision="已提醒",
                               reason=f"待办那一格没读成：{got['reason']}",
                               basis=["tasks / search_requests / reprocess_requests"],
                               target={"role": self.role}, fail_open=True,
                               error=str(got["reason"]))
            return {"checked": False, "reason": str(got["reason"]), "count": 0,
                    "running_agents": {"count": 0, "ids": []},
                    "pending_items": {"count": 0, "ids": [], "named": 0},
                    "reminded": [], "by_state": {}, "by_to": {},
                    "truncated": {"running_agents": {"shown": 0, "total": 0, "more": 0},
                                  "pending_items": {"shown": 0, "total": 0, "more": 0}}}
        agent_rows = [dict(x) for x in (got["running_agents"]["rows"] or ())]
        item_rows = [dict(x) for x in (got["pending_items"]["rows"] or ())]
        #: 待办项的截断只在这里发生；在跑栏一个都不减。
        named_items = item_rows[:MAX_REMINDERS]
        # 两样东西分清楚：`shaped` 是两栏全部行的形状（`by_state` / `by_to` 按它数，
        # 于是"待办项 10 条"与"pending 10 条"说的是同一批东西，不会一个 10 一个 5）；
        # `out` 是这一次真的点名的那些（待办项吃 MAX_REMINDERS，在跑的子代理全列）。
        shaped = [x for x in (self._reminder_of(it) for it in (agent_rows + item_rows))
                  if x is not None]
        out = shaped[:len(agent_rows) + len(named_items)]
        by_state: dict[str, int] = {}
        by_to: dict[str, int] = {}
        for one in shaped:
            if one["axis"] != ROW_AXIS_AGENT:
                state = str(one["state"] or "unknown")
                by_state[state] = by_state.get(state, 0) + 1
            to = str(one["to"] or S.CONDUCTOR_ROLE)
            by_to[to] = by_to.get(to, 0) + 1
        self._note_closure(out, running_count=len(agent_rows),
                           pending_count=len(item_rows))
        return {"checked": True, "reason": "", "count": len(out),
                "running_agents": {"count": len(agent_rows),
                                   "ids": [str(x.get("id") or "") for x in agent_rows]},
                "pending_items": {"count": len(item_rows),
                                  "ids": [str(x.get("id") or "") for x in item_rows],
                                  "named": len(named_items)},
                "reminded": out, "by_state": by_state, "by_to": by_to,
                "truncated": {
                    "running_agents": {"shown": len(agent_rows),
                                       "total": len(agent_rows), "more": 0},
                    "pending_items": {"shown": len(named_items),
                                      "total": len(item_rows),
                                      "more": max(0, len(item_rows) - len(named_items))}}}

    def _reminder_of(self, it: Mapping[str, Any]) -> dict[str, Any] | None:
        """一条待办 → 一条提醒（`state` 已经处理过的那几档返回 None）。

        `axis` 由来源决定：收件箱给的行带着 :func:`row_axis` 的结论；调用方直接给的
        那一份没有轴 ⇒ 一律当待办项（不在这一层另判"算不算在跑的子代理"）。
        """
        state = str(it.get("state") or "")
        if state in ("handled", "feedback_seen", "closed"):
            return None
        axis = ROW_AXIS_AGENT if str(it.get("axis") or "") == ROW_AXIS_AGENT \
            else ROW_AXIS_ITEM_OPEN
        if axis == ROW_AXIS_AGENT:
            note = "这一条子代理还没有终态（在跑）⇒ 提醒本体（经 M）"
        else:
            note = "这一条委托没有终态 / 没有反馈 ⇒ 提醒本体（经 M）"
        return {"task_id": str(it.get("task_id") or it.get("id") or ""),
                "state": state or "unknown",
                "kind": str(it.get("kind") or ""),
                "to": str(it.get("by") or it.get("who") or S.CONDUCTOR_ROLE),
                "note": note, "axis": axis}

    def _note_closure(self, out: Sequence[Mapping[str, Any]], *,
                      running_count: int, pending_count: int) -> None:
        """把这一轮闭环提醒落台账（摘要 + 逐条），并记下"该不该叫秘书"的读数。

        摘要保留"留痕 ≠ 被处理"这句（它挡的是"提醒过了就当办过了"），只把条数拆成两栏
        —— 改前那句只有一个数，读者分不出"在跑的子"与"没接手的项"。
        逐条落台账仍是 2026-10-04 主控裁定的第 1 条：只落一行摘要的话，"提醒了谁、
        什么事、什么状态"在纸上查不到，而这一层唯一能自证的就是台账（`draft/55` §5.3）。
        """
        if out:
            self.note_decision(
                duty=3, kind=KIND_NOTICE, decision="已提醒",
                reason=(f"{len(out)} 条未闭环（在跑的子代理 {running_count} 个、"
                        f"待办项 {pending_count} 条；留痕 ≠ 被处理）"),
                basis=["tasks: 代理行无终态 / 板项未收口",
                       "queue: 请求没人接手"],
                target={"role": self.role}, fail_open=False)
            for one in out:
                self.note_decision(
                    duty=3, kind=KIND_NOTICE, decision="已提醒",
                    reason=f"未闭环：{one['state']}（{one['task_id'] or '无 id'}）",
                    basis=["tasks: 代理行无终态 / 板项未收口",
                           "queue: 请求没人接手"],
                    target={"task_id": one["task_id"], "state": one["state"],
                            "kind": one["kind"], "to": one["to"],
                            "axis": one["axis"]},
                    fail_open=False)
            # 闭环提醒是异步的（`draft/55` §5.2）：不阻塞本体。
            # 2026-10-27 删掉了这里原本那一句
            # `self._last_closure_engage = self.should_engage(overdue=len(out), …)`：
            # 那个字段全仓 0 个读者（写两次、读零次），而 `should_engage` 是纯谓词
            # （`bool(alarms) or duplicates or overdue or novel`，无副作用）⇒ 这一句
            # 除了给一个没人读的字段赋值之外什么都没做。真要问"该不该叫秘书"，
            # 上面 `note_decision(duty=3, …)` 已经把那批未闭环逐条落了盘，
            # 而"要不要真叫"由调用方按 `should_engage` 自己算（三个真调用点见它的 docstring）。

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
                    task_id: str = "", sid: str = "", note: str = "",
                    to_task_id: str = "", to_task_ids: Iterable[str] | None = None,
                    ) -> dict[str, Any]:
        """增：替本体执笔一行交接手稿（`manuscripts.write`）。

        这一格不许 fail-open：写失败必须报错留痕（`draft/55` §5.2）。
        静默放行的后果是"手稿缺行"，而缺行与"没交接"在账本上长得一样 ——
        那会让下一次"这条是不是已经交接过"判错。所以这里 `raise` 之后再留痕。

        `to_task_id` / `to_task_ids`（2026-10-26，Q2「发 / 收两栏要显示绝对编码」）：
        收件人的绝对编码，原样转发给 `manuscripts.write`。本方法不算它 ——
        解析只发生在 `agent_loop._do_handoff` 那一处（它手里已经有 `_handoff_address`
        解析出来的 `task_id`，广播面还有 `_callable_members` 给的子代理编号）；
        秘书在这里再算一次就是第二份解析，而两份解析漂了不会有任何东西会响。
        """
        try:
            rec = MS.write(self.root, sender=self.role, recipient=str(to).upper(),
                           summary=str(summary), body=str(body), refs=list(refs),
                           task_id=str(task_id), sid=str(sid), note=str(note),
                           to_task_id=str(to_task_id), to_task_ids=to_task_ids)
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

        ## 为什么是同一个实例（2026-10-27）
        改前每调一次都现造一个：造一个 `Conductor` 要连 `TokenMeter` / `LocalBackend` /
        `MemoryBudgetTracker` 一起建，而秘书一拍里要问它十来次。更要紧的是读数身份：
        `roster_view` 把整段包进 `Conductor.reading_snapshot()`（一拍一份台账快照），
        而作用域挂在实例上 —— 若每次调用换一个新实例，作用域就只罩住了"造它的那一行"，
        拍内其余读照样各读一遍（实测：作用域因此从 1 次退化成 18 次）。
        缓存只保存这一个只读句柄；它的 `store` 在 `Secretary` 生命周期内不变，
        所以"哪个工作区"这件事不会变。写入口一个都不在这里走（秘书的写集是
        `STATEMENT_WRITE_TABLES`，见 `self.writes`）。
        """
        if self.store is None:
            return None
        cached = getattr(self, "_cond_cache", None)
        if cached is not None and getattr(cached, "store", None) is self.store:
            return cached
        from .conductor import Conductor, LocalBackend

        try:
            made = Conductor(self.store, policy=None, backend=LocalBackend({}))
        except Exception:  # noqa: BLE001
            return None
        self._cond_cache = made
        return made

    def roster_rows(self, owner: str) -> tuple[list[dict[str, Any]], list[str]]:
        """名册的折叠后状态（`(项列表, 坏行)`）：一项 = 名字 / 角色 / 简介 / 状态。

        事件流折叠口径：`add` 建项；`bind` 只推当前调用；`retire` 标退役；
        `keep_alive` 只改那一格读数。只追加、不物理删。
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
        """销号名单：名字一经退役永久不复用。`(行列表, 坏行)`。

        这是 :meth:`retired_ledger` 的薄包装：`bad` 的口径是"某行不是
        合法 JSON / 不是对象"，所以既有读者不受影响。"这一份名单够不够回答否"那一格
        不在这里 —— 它在 `retired_ledger` 的 `checked` / `unattributable` 上。
        """
        got = self.retired_ledger(owner, trusted_shard=True)
        return list(got.get("rows") or []), list(got.get("bad") or [])

    def retired_ledger(self, owner: str, *, trusted_shard: bool) -> dict[str, Any]:
        """销号名单的四态读数 ＋ 逐行读数。

        返回 `{"checked","state","rows","bad","unattributable","unattributable_rows",
        "reason"}`。`state` 是 `jsonlfile.READ_STATES` 之一（`absent` / `empty` / `ok` /
        `unreadable`），`checked` 的含义只有一句：这一份名单的否定结论（「这一号没
        销过」）信不信得过（整片口径）。`unattributable` 是那一档的逐条说明，
        `unattributable_rows` 是同一批行的结构化读数（哪一行、哪个键还用得了），
        给调用方"按号 / 按名逐个排除：这一行可能是谁"用（判据在
        :func:`retired_row_gaps`）。

        为什么要多出 `unattributable` 这一档（没有它，下面这些全会被读成"没销号"）：
        一行是合法 JSON、也是对象，但认不出它是哪一号 / 哪一名 —— 少 `task_id`、
        少 `name`、或两者类型不是非空字符串；
        又或者那一行的 `owner` 与它所在的分片名字对不上（"张冠李戴"那一半）。
        这种行今天既不在 `bad` 里、也不命中任何键 ⇒ 闸门读成"这一份里没有它" ⇒
        已销号的号照样被叫醒。判据只认"非空字符串"两件事，刻意不校验格式
        （格式校验会变成第二份发号口径）。

        `trusted_shard`：这个分片名是怎么来的，必须由调用方显式说。
        - `True`：来自台账那一行自己的 `parent_task_id`（或写侧的"我就是这个父"）⇒
          文件不存在就是"还没人销过号"这条查过的事实（`absent` + `checked=True`）；
        - `False`：来自扫目录 / 调用方猜的 ⇒ 文件不存在证明不了任何事（`checked=False`）。
        把这两档折在一起，就是那条洞（"读不成"被写成"查过了、没有"）。
        """
        from . import jsonlfile as JF

        rows, bad, state = JF.read_jsonl_state(retired_path(self.root, owner))
        bad = list(bad)
        unattributable, unattributable_rows = retired_row_gaps(rows, owner)
        out: dict[str, Any] = {"checked": True, "state": str(state), "rows": list(rows),
                               "bad": bad, "unattributable": unattributable,
                               "unattributable_rows": unattributable_rows, "reason": ""}
        if state == "unreadable":
            # 一个坏字节（R14）/ 一个占成目录的路径（R15）：这一片一条都读不出来。
            # 这一档绝不是"这一片里没有销号"—— 它是"整份失效"，所以 `checked=False`。
            out["checked"] = False
            out["reason"] = ("整份读不出来（这一格不是「没有销号」）："
                             + (bad[0] if bad else "读文本失败"))
        elif state == "absent" and not trusted_shard:
            out["checked"] = False
            out["reason"] = (f"{owner or '?'} 这一份名单不存在，而分片名不可信"
                             "（不是从台账那一行来的）⇒ 「没有这份名单」证明不了任何事")
        else:
            problems = bad + unattributable
            if problems:
                out["checked"] = False
                out["reason"] = f"{len(problems)} 行读不全（{problems[0]}）"
            elif state == "absent":
                out["reason"] = ("还没有人销过号（这一份名单还不存在；分片名来自台账那一行）")
        self.last_retired_ledger = dict(out)
        return out

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

    def _roster_bindings(self, owner: str) -> tuple[list[tuple[str, str]], list[str]]:
        """“哪个号绑过谁”的全部历史：正文 `add` 行 ∪ 对照表 `bind` 行，按文件序。

        返回 `([(task_id, name)], 坏行)`。这是这一份历史的唯一解析器：两个读法
        （:meth:`_roster_history` 的"号 → 名字"、:meth:`_bound_task_ids` 的"名字 → 全部号"）
        都从它派生。为什么必须只有一处（`draft/151` 三-5）：这两处分别决定
        “自愈会不会把已登记的号再补一次”与“销号漏不漏号”，两个后果都不可逆；而两份
        逐字相同的解析器今天给出相同答案，改一处不会有任何判据变红。

        不读任何折叠视图：`_fold_index` 只留每个名字最新那条 `bind`，于是"一个名字接过
        的第二件活"会把第一件活从已知集里挤出去 —— 自愈据此把已经登记过的行再补一次
        （`draft/149` §4.5 的机制 B，零并发即可复现）。
        """
        from . import jsonlfile as JF

        body, bad_body = JF.read_jsonl(roster_path(self.root, owner))
        index, bad_index = JF.read_jsonl(roster_index_path(self.root, owner))
        rows: list[tuple[str, str]] = []
        for r in body:
            if str(r.get("kind") or "") != "add":
                continue
            tid = str(r.get("task_id") or "")
            if tid:
                rows.append((tid, str(r.get("name") or "")))
        for r in index:
            if str(r.get("kind") or "") != "bind":
                continue
            tid = str(r.get("task_id") or "")
            if tid:
                rows.append((tid, str(r.get("name") or "")))
        return rows, list(bad_body) + list(bad_index)

    def _roster_history(self, owner: str) -> tuple[dict[str, str], list[str]]:
        """这个父名下「这个号历史上登记给了谁」：全部 `add` 行 ∪ 全部 `bind` 行的 `task_id` 并集。

        返回 `({task_id: name}, 坏行)`；首个名字胜（:meth:`_roster_bindings` 的顺序）。
        写侧为什么读它（而不是读某个折叠项）：唯一性判据必须读全历史。`draft/150`
        §5.1-① 的读数：116/881 个名册项在"正文的号"与"对照表的当前号"之间分叉，
        拿任一份折叠视图当已知集都会把另一份判成"不存在"。
        """
        rows, bad = self._roster_bindings(owner)
        out: dict[str, str] = {}
        for tid, name in rows:
            out.setdefault(tid, name)
        return out, bad

    def _bound_task_ids(self, owner: str, name: str) -> list[str]:
        """这个名字绑过的全部号（正文 `add` 行 ∪ 对照表 `bind` 行，按出现顺序去重）。

        销号要标死的不是"当前号"而是这一格：复用是合法的一等功能，一个名字接过
        N 件活就有 N 个号；只写最后那条 `bind` 会让早先的号在唤醒闸那里仍读成
        "没销号"（`draft/150` §5.1-③ 的读数 H：`wake(t-000002)` 仍 `started=true`）。
        历史从 :meth:`_roster_bindings` 来（同一处解析；这里只做按名过滤）。
        """
        want = str(name or "")
        if not want:
            return []
        rows, _bad = self._roster_bindings(owner)
        out: list[str] = []
        for tid, who in rows:
            if who == want and tid not in out:
                out.append(tid)
        return out

    @_roster_guarded
    def roster_refusal_note(self, *, owner: str, task_id: str, name: str = "",
                            refusal_code: str = "", problem: str = "") -> tuple[bool, str]:
        """把"这一号被写口拒了"落成一条可跨进程读到的流水（业主 2026-11-02 的裁定）。

        写侧为什么必须做这件事：拒绝的那一刻名册三份一个字节都没写，于是"被拒过"这个
        事实在盘上原本只活在调用方的 `roster_problem` 里（而它随进程消失）。没有这条
        流水，收口兜底（`roster_repair`）就把这个号当成"漏登记的孤儿"补成新名字 ——
        等于把一次有记录的拒绝悄悄改写成一个子节点（`temp/probe_h11_leftovers.py` 的
        L 读数）。返回 `(写成了没有, 没写成的理由)`；写不成不抛（拒绝本身仍要如实交回）。
        """
        return append_jsonl(refusals_path(self.root, owner),
                            {"kind": "refused", "owner": str(owner),
                             "task_id": str(task_id),
                             "requested_name": str(name or ""),
                             "refusal_code": str(refusal_code or ""),
                             "problem": str(problem or ""), "at": _now_iso()})

    def _refused_task_ids(self, owner: str) -> tuple[set[str], list[str]]:
        """这个父名下"被写口拒过"的全部号 ⇒ `(号集合, 坏行)`（三态：坏行非空 ⇒ 不许当成没被拒）。

        坏行要不要 fail-closed：要。把它读成"没有拒绝记录"会让收口兜底把被拒的号补成新名字
        —— 这一步不可逆；而"这一份流水读不出来所以这次不补"是可逆的（补一次下回还有机会）。
        """
        from . import jsonlfile as JF

        rows, bad, state = JF.read_jsonl_state(refusals_path(self.root, owner))
        out: set[str] = set()
        for r in rows:
            tid = str(r.get("task_id") or "")
            if tid:
                out.add(tid)
        bad = list(bad)
        if state == "unreadable" and not bad:
            bad = ["拒绝流水读不出来（这一格不是「没人被拒」）"]
        return out, bad

    def _retired_used(self, owner: str) -> list[str]:
        """销号名单里的名字（"扫已销号的名字"这一步单独一处，判据可以把它打桩成跳过）。

        走 :meth:`retired_ledger`（写侧的分片名就是"我这个父"，所以 `trusted_shard=True`）：
        `bad` / `unattributable` 不再被 `_bad` 丢掉 —— 它们留在 `self.last_retired_ledger`
        里，"这一格读不全"从此是一个读得出来的事实，而不是一个被吞掉的返回值。
        """
        got = self.retired_ledger(owner, trusted_shard=True)
        return [str(r.get("name") or "") for r in (got.get("rows") or [])
                if str(r.get("name") or "")]

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

    def _reuse_refusal(self, owner: str, name: str) -> tuple[str, str]:
        """`reuse=<名>` 这个目标能不能接活：`("", "")` = 能，否则是 `(一句受控拒绝的理由, 理由码)`。

        判据只有一条（业主 2026-10-24 的最终口径）："在册且未销号"就能再接活。
        「已收口子代理可再接收活，但已销号不可用」——
        - 收口（上一件活已交差、状态 done/ended，但名册项还在册）⇒ 只是闲下来了，
          可以再接一件活；
        - 销号（名册项标了 retired、名字进了销号名单）⇒ 这个子代理退场了，名字永久
          不复用（`reuse` 指向它一律受控拒绝）。

        理由码（2026-11-02 补，三态：父要能机器判"是哪种不许"）：
        - `member_retired`：这个名字销过号（与按名寻址那一档同一个词）；
        - `not_in_roster`：名册里根本没有这个名字。
        在此之前这两档只有人话、没有码，而 `Conductor._register_roster` 恰恰拿
        "有没有码"当"要不要跑兜底自愈"的开关 ⇒ 这两档拒绝之后那条子行会被自愈
        按新名字补进名册（`temp/probe_h11_leftovers.py` 的 H / I 读数：等于换个
        地方继续静默改名）。码在这里给全，那条开关才关得上。

        这一处刻意单独成一个方法：判据把它打桩成"只要在册就行"⇒ 销号那一档必须红；
        打桩成"只认活跃任务"⇒ 收口那一档必须红（`tests/test_roster_ownership_...`）。
        """
        if not self._name_exists(owner, name):
            return (f"名册里没有 {name} ⇒ 不猜（复用必须父先看名册）", "not_in_roster")
        if self._is_retired(owner, name):
            return (f"{name} 已销号（名字永久不复用，业主 B1）", "member_retired")
        return ("", "")

    @_roster_guarded
    def roster_add(self, *, owner: str, role: str, task_id: str, brief: str,
                   task: str = "", task_id_first: str = "", want_name: str = "",
                   reuse: str = "", surface: str = "", new: str = "") -> dict[str, Any]:
        """写口 + 拒绝留痕（真正的登记逻辑在 :meth:`_roster_add`，两半在同一个临界区里）。

        为什么单包这一层（业主 2026-11-02：「被拒是一次有记录的决定」）：拒绝时
        `_roster_add` 一个字节都不写，于是"被拒过"必须由写口自己在同一个 per-owner
        临界区里落一条流水（:func:`refusals_path`）—— 否则收口兜底（`roster_repair`）
        会把这个号当成"漏登记的孤儿"补成新名字，等于把一次有记录的拒绝悄悄改写成一个
        子节点（`temp/probe_h11_leftovers.py` 的 L 读数）。放在这一层而不是调用方，
        是为了让"拒了"与"记下拒了"之间没有任何时间窗。

        记录写不成不改变拒绝的结论（回执的 `problem` / `refusal_code` 逐字不变），
        只把"以后可能被收口兜底补上"写进回执的 `note`。
        """
        got = self._roster_add(owner=owner, role=role, task_id=task_id, brief=brief,
                              task=task, task_id_first=task_id_first,
                              want_name=want_name, reuse=reuse, surface=surface, new=new)
        problem = str(got.get("problem") or "")
        if not problem:
            return got
        ok, why = self.roster_refusal_note(
            owner=owner, task_id=task_id, name=str(got.get("name") or ""),
            refusal_code=str(got.get("refusal_code") or ""), problem=problem)
        if ok:
            return got
        out = dict(got)
        out["note"] = (f"拒绝记录没写成（{why}）"
                       "⇒ 收口兜底可能把这一条补成新名字")
        return out

    def _roster_add(self, *, owner: str, role: str, task_id: str, brief: str,
                    task: str = "", task_id_first: str = "", want_name: str = "",
                    reuse: str = "", surface: str = "", new: str = "") -> dict[str, Any]:
        """名册登记（增那一支）：`{"name","role","task_id","brief","brief_written","problem"}`。

        ## 两个入口，语义不同
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

        ## 受控拒绝带机器码
        拒绝时回执多一格 `refusal_code`（成功回执逐键不变），取值只有这五个，一档一个语义：
        `name_taken`（这个名字用过：活跃 / 已收口 / 已销号）、`task_id_reused`（同一个号
        已经登记在别的名字名下）、`task_id_retired`（这个号销过号，不许再 add / bind）、
        `member_retired`（`reuse` 指向一个已销号的名字）、`not_in_roster`（`reuse` 指向
        名册里没有的名字）。前两个是 `want_name` / 新号两支的闸，后三个是 `reuse` 支的闸。
        父据此决定"换一个号 / 换一个名字 / 停止"，框架不替它改主意 ——
        `Conductor._register_roster` 也按这一格决定"不跑兜底自愈"。

        ## 盘上落什么（`task_id` 是调用流水读数，不是归属键）
        - 名册正文 `<父>.jsonl`：`kind="add"` 一行建项（名字、角色、简介、面、创建时间）；
          `kind="retire"` 一行销号；
        - 对照表 `<父>-index.jsonl`：`kind="bind"` 一条调用记录（名字 + 这一件活的编号
          + 时间）。`task_id` / `task_name_first` 这类字段只回答"这一条/这一项是为哪件
          活落的"，不回答"这个名册项是谁" —— 名册项的身份是 `owner` + `name`
          （读侧按名字归组：一个节点 + N 件活，见 `webui.readers.roster_face`）。

        ## 简介
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
            refusal, refusal_code = self._reuse_refusal(owner, name)
            if refusal:
                return {"name": name, "role": str(role), "task_id": str(task_id),
                        "brief": text, "brief_written": source == "secretary",
                        "refusal_code": refusal_code, "problem": refusal}
            # ⑥（业主 2026-11-02）：已销号的号不许再绑给任何名字。名字那一侧封死
            # 而号那一侧敞开，会让"名字永久不复用"变成一句空话 —— 旧号换个名字又活了。
            retired_by = self._retired_name_of_task_id(owner, str(task_id))
            if retired_by:
                return {"name": name, "role": str(role), "task_id": str(task_id),
                        "brief": text, "brief_written": source == "secretary",
                        "refusal_code": "task_id_retired",
                        "problem": (f"{task_id} 已经销号（{retired_by}）⇒ 受控拒绝"
                                    "（task_id_retired）：已销号的号不许再绑活，也不许"
                                    "再登记给别的名字（否则它会变成永远销不掉的孤儿）")}
            # ④：一个号只属于一个名字。同一个号已经绑在别人身上 ⇒ 这不是"这件活
            # 落到这个名字上"，而是"两个名字指向同一个子代理"—— 读侧会静默取第一个。
            history, bad_hist = self._roster_history(owner)
            if bad_hist:
                return {"name": name, "role": str(role), "task_id": str(task_id),
                        "brief": text, "brief_written": source == "secretary",
                        "problem": (f"名册/对照表有 {len(bad_hist)} 行读不出来 ⇒ 不绑"
                                    f"（免得把同一个号绑给两个名字）：{bad_hist[0]}")}
            owner_name = str(history.get(str(task_id)) or "")
            if owner_name and owner_name != name:
                return {"name": name, "role": str(role), "task_id": str(task_id),
                        "brief": text, "brief_written": source == "secretary",
                        "refusal_code": "task_id_reused",
                        "problem": (f"{task_id} 已经绑在 {owner_name} 名下 ⇒ 受控拒绝"
                                    "（task_id_reused）：一个号只属于一个名字（要接这件活"
                                    "就 reuse 那个名字）")}
            bind: dict[str, Any] = {"kind": "bind", "owner": owner, "name": name,
                                    "role": str(role), "task_id": str(task_id), "at": at}
            if str(task or "").strip():
                # 任务原文跟着这一件活落盘（业主 2026-10-27：等子代理的目的自动用它填）。
                bind["task_text"] = _task_text(task)
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
                problem = (f"{name} 已经用过（{status}）⇒ 受控拒绝（name_taken）："
                           "用过的名字不再发给另一个子代理（要新建一个同类子代理，"
                           "让秘书按序号发下一个未用名，或显式给一个没用过的名字）")
                return {"name": name, "role": str(role), "task_id": str(task_id),
                        "problem": problem, "refusal_code": "name_taken"}
        else:
            name = ""
        # ⑥ 已销号的号不许再登记（名字那一侧封死，号那一侧若不封：换个新名字重新 add
        # 成功，于是这个新名字永远销不掉、成为永久孤儿，父也永远不许销号）。
        retired_by = self._retired_name_of_task_id(owner, str(task_id))
        if retired_by:
            return {"name": name, "role": str(role), "task_id": str(task_id),
                    "refusal_code": "task_id_retired",
                    "problem": (f"{task_id} 已经销号（{retired_by}）⇒ 受控拒绝"
                                "（task_id_retired）：已销号的号不许再登记给任何名字"
                                "（否则它会变成一个永远销不掉的孤儿项）")}
        # ④ 同一个号不许出现在两条 `add` 行。判据读全历史
        # （全部 add ∪ 全部 bind），不读折叠视图 —— 后者会把复用过的旧号判成"没见过"。
        history, bad_hist = self._roster_history(owner)
        if bad_hist:
            return {"name": name, "role": str(role), "task_id": str(task_id),
                    "problem": (f"名册/对照表有 {len(bad_hist)} 行读不出来 ⇒ 不登记"
                                f"（免得重名或重号）：{bad_hist[0]}")}
        owner_name = str(history.get(str(task_id)) or "")
        if owner_name:
            return {"name": name, "role": str(role), "task_id": str(task_id),
                    "refusal_code": "task_id_reused",
                    "problem": (f"{task_id} 已经登记在 {owner_name} 名下 ⇒ 受控拒绝"
                                "（task_id_reused）：同一个号不许出现在两条 add 行"
                                "（要接这件活就 reuse 那个名字）")}
        if not want_name:
            name, problem = self.next_name(owner, role)
            # 死分支·契约出口：`next_name` 今天的第二个分量恒为空串（它自己的 docstring 与
            # `tests/test_no_dead_branch_on_a_field_that_is_always_empty.py` 钉着这件事），
            # 所以这一支永远不执行。留着是给"将来发号器能拒"的显式出口 —— 与
            # `roster_repair` 里那一支是同一件事：删/留必须成对，不许只改一处。
            if problem:
                return {"name": "", "role": str(role), "task_id": str(task_id),
                        "problem": problem}
        # S1n（业主 T23 / B2）：造一个新子代理时同时预订一个读写面（父可以点名要哪个槽位）。
        # 拿不到面 ⇒ 受控拒绝（不许先给名字后没有面：那会造出一个"能说话但不能干活"的项）。
        got_surface = self.surface_alloc(owner=owner, want=str(surface or ""), name=name)
        if got_surface.get("problem"):
            return {"name": name, "role": str(role), "task_id": str(task_id),
                    "problem": f"读写面没定下来：{got_surface['problem']}"}
        bind_add: dict[str, Any] = {"kind": "bind", "owner": owner, "name": name,
                                    "role": str(role), "task_id": str(task_id), "at": at,
                                    "first": True}
        add_row: dict[str, Any] = {"kind": "add", "owner": owner, "name": name,
                                   "role": str(role), "task_id": str(task_id),
                                   "first_task_id": str(task_id_first or task_id),
                                   "brief": text, "brief_source": source,
                                   "surface": str(got_surface.get("slot") or ""),
                                   "at": at}
        if str(task or "").strip():
            # 任务原文（≤200 字，单行）：`clock` 的"目的自动填"读它（业主 2026-10-27）。
            # 落两份：名册项那一行（`add`）与对照表那一行（`bind`）—— 前者是这一项
            # 为哪件活建的，后者是这件活归了谁；读侧两条都能找到同一句原文。
            bind_add["task_text"] = _task_text(task)
            add_row["task_text"] = _task_text(task)
        ok, why = append_jsonl(roster_index_path(self.root, owner), bind_add)
        if not ok:
            return {"name": name, "role": str(role), "task_id": str(task_id),
                    "problem": f"对照表没写成：{why}"}
        ok2, why2 = append_jsonl(roster_path(self.root, owner), add_row)
        if not ok2:
            return {"name": name, "role": str(role), "task_id": str(task_id),
                    "problem": f"名册没写成（对照表那一行已经落了 ⇒ 读侧会报'半份登记'）：{why2}"}
        return {"name": name, "role": str(role), "task_id": str(task_id),
                "brief": text, "brief_written": source == "secretary",
                "surface": str(got_surface.get("slot") or ""), "problem": ""}

    def open_solo_entry(self, *, task_id: str, task: str = "", brief: str = "") -> dict[str, Any]:
        """给"用户指定单条执行"开一条名册行与一个读写面槽位（`owner` = 它自己的任务号）。

        ## 为什么需要这一格

        形式化验证成本极高 ⇒ 在全部研究和论文落定之后，用户指定有形式化验证需求时，
        要一条才做一条。而只有 B 可以派 L，所以这一格今天不只在 `run-agent L` 上用到：
        被 B 派的那一趟走父的秘书登记，而用户指定单条起的那一趟没有父，走本方法。
        "单条执行时同样有台账号、名册行、读写面"—— 那三样在"被父派活"那一档是由父的秘书在
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

    @_roster_guarded
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

    @_roster_guarded
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

    # ------------------------------------------------------------ 命题同一性（模型判）
    #
    # 检索（口径二）与可检索池都不在本文件：它们是命题台账的「查」那一族，唯一实现住在
    # `statementledger`（`by_keywords` / `pool`）。2026-11-09 之前这里是
    # `_searchable_statement_rows` + `_statements_matching_keywords` 两个私有方法，
    # 而全仓另外还有 3 处逐字同源的池过滤与 1 处第二把尺的关键词检索（工具层 `table.search`）。
    # 收口之后本文件只负责「挑词 → 问查口 → 逐页判」，三件事各归各的一处。
    # 判据：`tests/test_the_statement_ledger_has_two_ways_to_be_asked.py`。

    @staticmethod
    def _candidate_reading(hits: Sequence[Mapping[str, Any]],
                           limit: int = PROPOSITION_VERDICT_CANDIDATES
                           ) -> list[dict[str, Any]]:
        """一页命中候选 ⇒ 判定的上下文那一份（只留判定要看的格）。

        这一格只是一页的成形器（页大小
        `PROPOSITION_VERDICT_CANDIDATES`）；分页在 `_identity_pages`，问到命中或页尽，
        不再把整批截到前 4 条。
        """
        return [{"stmt_id": str(h.get("stmt_id") or ""),
                 "label": str(h.get("label") or ""),
                 "proof_nos": list(h.get("proof_nos") or []),
                 "statement_full": str(h.get("statement_full") or "")}
                for h in list(hits)[: max(0, int(limit))]]

    def adjudicate_proposition(self, stmt_like: Mapping[str, Any] | str, *,
                               rows: Iterable[Mapping[str, Any]] | None = None,
                               candidates: Sequence[Mapping[str, Any]] | None = None,
                               note: str = "secretary:proposition_identity",
                               use_cache: bool = True,
                               task_id: str = "") -> dict[str, Any]:
        """这一条与在册的哪一条是同一个定理（秘书主动查询 + 一次模型判定，两档，按正文 sha256 缓存）。

        两句准绳：「不用机械判据，让秘书洗定理名，让秘书判」；
        「定理描述一致（什么条件推出什么结论），就是一个定理」。这一问不许有第三种
        结论 —— 读不清就是没判成，不是一种判词。

        所以这一格做三件事、两次模型调用（挑词 + 判定；判定那一趟同时洗名）：
        ⓪ 「秘书自己出查询」：`pick_statement_keywords` 挑数学关键词（一次调用），
           代码按关键词在 `statements` 里检索 active 命题（`label` / `statement_full`
           包含该词，归一按 `textutil`）—— 检索只取候选，「不把全表交给模型过一遍」；
           调用方已经检索好候选（`candidates=`）时跳过这一问（兼容既有写法），
           但走的是同一处判定；
        ① 洗定理名：`Sylow 三定理（路线一：类方程/强归纳 + 共轭作用，自证草稿，待 V 审签）`
           ⇒ `canonical_name = "Sylow 三定理"`，被洗掉的"路线一：…"进 `route`
           （它不丢：落进证明那一层，见 :func:`proof_route_of`）；
        ② 判是不是同一个命题：读条件与结论，只给 same / different，
           判 same 时点名并进哪一条（`same_as`）。

        ## 检索读数（"它确实查过"必须看得见）
        `keywords` / `hits_total`（命中几条）/ `hits_named`（这一趟交给模型看的全部候选，
        带每条命中的词）/ `judged`（判定那一趟发没发）/ `same_as` / `why`。
        分页读数（缺陷 ②）：`candidates_total`（候选总数）/ `pages_total`（要问几页）/
        `pages_judged`（真问了几页）/ `candidates_seen`（已经入眼几条）/
        `page_exhausted`（问完了还没命中）。候选按 `PROPOSITION_VERDICT_CANDIDATES`
        分页，问到命中或页尽；改前只把前 4 条交给模型，第 5–N 条永不入眼却被记成
        "这批都不是"。
        台账里 0 条可检索命题、或关键词 0 命中 ⇒ `checked=True` + `verdict="different"`
        （查过、没有同一条；0 命中仍发判定那一趟洗定理名，读数里 `candidates_total=0`、
        `page_exhausted=True`）；关键词没提取成 / 台账读不成 ⇒ `checked=False`（没判成，
        上层 fail-closed；这一档不许退回"拿全表或相似度候选去猜"）。

        ## 两档与依据（返回）
        | 结局 | 返回 |
        |---|---|
        | 判同一 | `checked=True` + `verdict="same"` + `same_as=<stmt_id>` + `canonical_name` |
        | 判不同 | `checked=True` + `verdict="different"`（不并，新建） |
        | 没判成 | `checked=False` + `verdict=""` + `reason`（没缝 / 开关关着 / 超时 / 坏 JSON / 词表外结论 / same 点不出号） |

        没有第三种结论词。`basis` 是那一趟的判词（条件一句 + 结论一句 + 一句理由）；
        `same` 而 `same_as` 指不出一个候选号 ⇒ 没判成（`checked=False`，不并也不新建）：
        凭一个指不出来的号合并，等于替它编一条依据（与"模型给的结论不在词表里就不采信"
        同一条纪律）。这一档以前会降成第三种结论再照旧新建一行 —— 那正是"既在账上又不在
        账上"的形态，2026-11-08 起不许再出现。

        ## 为什么按正文 sha256 缓存（`out/secretary/proposition_verdicts.jsonl`）
        判定的对象是那段正文；同一条正文换个标签、重试、换个人再交一次，结论不会有别的
        答案，而每一次都要真发一次调用。真机 sylow4 的形态正好是"同一条定理交了三遍"——
        没有这一层就是三笔钱买同一句话。只缓存判成了的两档（`checked=True`）：没判成不许
        缓存，那会把"这一次没判成"变成"以后都别查了"。缓存行也带检索读数，于是"沿用
        那一次判定"时同样读得出它当年查过什么。
        `reused=True` + `cost.reason="没发调用（沿用缓存）"` 是"这一趟没花钱"的唯一读数。
        """
        if isinstance(stmt_like, str):
            stmt_like = {"statement_full": stmt_like}
        full = str(stmt_like.get("statement_full") or "")
        label = str(stmt_like.get("label") or "")
        kind = str(stmt_like.get("kind") or "theorem")
        out: dict[str, Any] = self._identity_out(label=label, kind=kind)
        if not _is_proposition_kind(kind):
            out["reason"] = (f"kind={kind!r} 不在命题性的那几档 {list(PROPOSITION_KINDS)} 里 "
                             "⇒ 不是命题，不参与同一性判定（也不洗它的名字）")
            return self._with_adjudication_visibility(out)
        if not full.strip():
            out["reason"] = "命题正文是空的 ⇒ 没有可判的东西（不洗名、不并）"
            return self._with_adjudication_visibility(out)
        key = _proposition_verdict_key(full)
        out["statement_sha256"] = key
        # `use_cache=False` 是"候选逐页给"那一档（调用方手里已经有候选）：按正文 sha
        # 缓存会把"这一页没查到"沿用到下一页。
        cached = ((self._proposition_verdicts.get(key)
                   or proposition_verdict_of(self.root, full)) if use_cache else {})
        cached_verdict = str((cached or {}).get("verdict") or "")
        cached_same_as, _cached_n = normalize_same_as((cached or {}).get("same_as"))
        # 只认判成了的两档：判 same 的还必须点得出号（否则那一行也不是一次判定）。
        # 历史行（2026-11-08 之前）里可能有旧的第三种结论词 —— 它不许当缓存用：
        # 那会把"那一次没判成"沿用到今天，而这一趟本来可以重新判（判据 c）。
        if (cached and cached_verdict in PROPOSITION_VERDICTS
                and (cached_verdict != _PK.STATE_SAME or bool(cached_same_as))):
            # 缓存里的坏值也要按同一把尺归一化：本趟 `proposition_verdicts.jsonl` 的
            # 第 6-9 行就是 `"['000001']"` 这一族，而同一段正文重交时读的正是它
            # （"判过一次就复用"这条纪律会让坏值一直活着）。只归一化外形，
            # 不重判 verdict —— 判词是那一趟的读数，改它等于替那一趟翻案。
            out.update(
                checked=True,
                verdict=cached_verdict,
                canonical_name=str(cached.get("canonical_name") or ""),
                same_as=cached_same_as,
                route=str(cached.get("route") or ""),
                condition=str(cached.get("condition") or ""),
                conclusion=str(cached.get("conclusion") or ""),
                basis=str(cached.get("basis") or ""),
                reused=True, cached=True,
                cached_at=str(cached.get("at") or ""),
                cached_label=str(cached.get("label") or ""),
                cost={"ledger": "", "reason": "没发调用（沿用缓存：同一段正文判过一遍）"},
                # 检索读数照旧摆出来（缓存行里存着那一次查过什么）；候选表不重算 ——
                # 重算要再花一次挑词调用，而这一次的处置不取决于候选还在不在。
                keywords=[str(x) for x in (cached.get("keywords") or ())],
                hits_total=int(cached.get("hits_total") or 0),
                hits_named=[dict(x) if isinstance(x, Mapping) else {"stmt_id": str(x)}
                            for x in (cached.get("hits_named") or ())],
                judged=bool(cached.get("judged")),
                why=str(cached.get("why") or ""),
                keyword_checked=bool(cached.get("keyword_checked")),
                candidates_total=int(cached.get("candidates_total") or 0),
                pages_total=int(cached.get("pages_total") or 0),
                pages_judged=int(cached.get("pages_judged") or 0),
                candidates_seen=int(cached.get("candidates_seen") or 0),
                page_exhausted=bool(cached.get("page_exhausted")),
                candidates=[])
            return self._with_adjudication_visibility(out)
        if cached:
            out["cache_ignored"] = (
                f"台账里那一行判词 {cached_verdict!r} 不是两档里的一次判定"
                "（历史行：旧的第三种结论词，或判 same 却没点名候选号）⇒ 不当缓存用，"
                "这一趟重新判")
        # ---- 取候选：默认路径 = 秘书自己查（业主 2026-11-08：「应该是主动查询」）------
        #
        # 两档来源，处置不同：
        # - `candidates=` 给了：调用方已经检索好（兼容既有写法），这一趟不自己查；
        # - 没给：秘书自己挑关键词、自己在台账里检索。关键词那一问没成 ⇒ 没判成
        #   （fail-closed），「不许」退回"拿全表/相似度候选去猜"。
        #
        # 没有候选（台账 0 条 / 关键词 0 命中）时「仍然发判定那一趟」：洗定理名
        # （`canonical_name` / `route`）与判定是同一趟的输出，跳过它就会让"第一条命题
        # 的 label 原样落盘"—— 那正是洗名要治的形态。这一档只省掉挑词那一问。
        if self._identity_candidates(out, candidates=candidates, rows=rows,
                                     full=full, label=label, kind=kind,
                                     task_id=task_id):
            return self._with_adjudication_visibility(out)
        if self._judge_identity_pages(out, full=full, label=label, kind=kind,
                                      note=note, task_id=task_id):
            return self._with_adjudication_visibility(out)
        if not out["checked"]:     # 防御：只有判成了的两档才许进缓存
            return self._with_adjudication_visibility(out)
        if use_cache:
            self._remember_proposition_verdict(out, full=full, label=label,
                                               task_id=task_id)
        return self._with_adjudication_visibility(out)

    def _judge_identity_pages(self, out: dict[str, Any], *, full: str,
                              label: str, kind: str, note: str,
                              task_id: str) -> bool:
        """按页判同一性（问到命中或页尽）；返回 True = 调用方应直接回读数。

        2026-11-08 缺陷 ② 的实现从 `adjudicate_proposition` 拆出（只搬移）：分页、
        命中收口、成员校验三段合起来 90 余行；拆出来之后那一格回到 200 行以内 ——
        体量基线是读数，不许为了它抬（业主口径：拆函数，不抬基线）。

        三件事与改前逐字同序：① 每页发一次判定（`judge`）；② 判 same 就在那一页
        校验 `same_as` 是页内候选号（指不出号 ⇒ 没判成）；③ 判 different 继续下一页，
        页尽时 `page_exhausted=True`。
        """
        candidates_page = list(out["candidates"])
        pages = self._identity_pages(candidates_page)
        # ---- 检索读数（2026-11-08 缺陷 ②）：候选总数 / 页数 / 实际问了几页 / 是否页尽 ----
        #
        # 改前这里只把前 4 条交给模型（`_candidate_reading` 截断），而 `hits_total`
        # 照旧报全量 ⇒ "第 5–20 条永不入眼"与"20 条都看过"在读数上同形。现在按
        # `PROPOSITION_VERDICT_CANDIDATES` 分页，问到命中或页尽为止，并把三件事写进
        # 读数：`pages_total` / `pages_judged` / `page_exhausted`（外加
        # `candidates_total` / `candidates_seen`）。
        out["candidates_total"] = len(candidates_page)
        out["pages_total"] = len(pages)
        out["pages_judged"] = 0
        out["candidates_seen"] = 0
        out["page_exhausted"] = False
        out["judged"] = False
        seen: list[str] = []
        parts: list[str] = []
        page_ids: list[str] = []
        for index, page in enumerate(pages, 1):
            context = self._identity_context(
                full=full, label=label, kind=kind, candidates=page)
            got = self.judge("proposition_identity", context, task_id=task_id,
                             note=note)
            out["judged"] = True
            out["pages_judged"] = index
            page_ids = [str(c.get("stmt_id") or "") for c in page]
            seen.extend(page_ids)
            out["candidates_seen"] = len(seen)
            out["cost"] = dict(got.get("cost") or out.get("cost") or {})
            out["judged_elapsed_sec"] = got.get("elapsed_sec")
            if not got.get("checked"):
                out["checked"] = False
                out["reason"] = str(got.get("reason") or "这一格没查成（原因不明）")
                return True
            verdict = str(got.get("decision") or "")
            if verdict not in PROPOSITION_VERDICTS:
                # `judge()` 已经按词表挡了一层；这里再挡一层是防"别的类别借这一格"：
                # 词表外的结论不是一种判定 ⇒ 没判成（不新建、不合并）。
                out.update(checked=False, verdict="",
                           reason=(f"模型给的结论 {verdict!r} 不在两档 "
                                   f"{list(PROPOSITION_VERDICTS)} 里 ⇒ 不采信：这一格没判成"))
                return True
            # 洗定理名与判同一趟（每一页的判词都带 `canonical_name` / `route`）：
            # 取"判成的那一页"—— 判 same 就在那一页收口，判 different 一直问到页尽。
            out["canonical_name"] = str(got.get("canonical_name") or "").strip()
            out["route"] = str(got.get("route") or "").strip()
            out["condition"] = str(got.get("condition") or "").strip()
            out["conclusion"] = str(got.get("conclusion") or "").strip()
            out["reason"] = str(got.get("reason") or "")
            parts = [str(x).strip() for x in (got.get("basis") or []) if str(x).strip()]
            out["basis"] = "；".join(parts + ([out["reason"]] if out["reason"] else []))
            out["checked"] = True
            out["verdict"] = verdict
            out["same_as"] = str(got.get("same_as") or "").strip()
            if verdict == _PK.STATE_SAME:
                ids = page_ids
                # ---- 先归一化外壳，再判成员（真机 82，2026-11-01）
                #
                # 现场：模型判 same 时把号写成 `"['000003']"`（52 处 / 16 个会话行），
                # 而下面这条成员判据逐字比 ⇒ 判了 same 也不并、照旧落新行
                # （重复对 000001/000004、000003/000005 就是这么来的）。
                # 纪律不改：归一化后仍指不出候选号 ⇒ 没判成（2026-11-08 起不再降成
                # 第三种结论）："凭一个指不出来的号合并，等于替它编一条依据"这句话仍然成立；
                # 多元素列表也不猜，只说清"你给了 N 个号"。
                raw_same_as = str(out["same_as"] or "")
                normalized, how_many = normalize_same_as(raw_same_as)
                out["same_as"] = normalized
                if not normalized:
                    if how_many > 1:
                        why = (f"模型判 same，但 same_as 给了 {how_many} 个号"
                               f"（收到 {raw_same_as!r}）⇒ 不猜：并进哪一条是它的判断，"
                               f"框架替它挑一个等于替它表态；要并请只点一个号"
                               f"（候选 {ids or '空'}）")
                    else:
                        why = (f"模型判 same，但 same_as 没给出可用的号"
                               f"（收到 {raw_same_as!r}）⇒ 没判成：指不出候选号的合并等于"
                               f"替它编一条依据（候选 {ids or '空'}）")
                    out.update(checked=False, verdict="", same_as="", reason=why,
                               basis="；".join(parts + [why]))
                    return True
                if normalized not in ids:
                    why = (f"模型判 same，但 same_as={normalized!r}（原文 {raw_same_as!r}）"
                           f" 不是候选表里的号（候选 {ids or '空'}）⇒ 没判成：凭一个指不出来的"
                           "号合并，等于替它编一条依据")
                    out.update(checked=False, verdict="", same_as="", reason=why,
                               basis="；".join(parts + [why]))
                    return True
                break
            # different：还有下一页就接着问；页尽就由下面那一格收口。
        out["page_exhausted"] = bool(out["verdict"] == _PK.STATE_DIFFERENT
                                     and out["pages_judged"] >= out["pages_total"])
        return False

    def _identity_context(self, *, full: str, label: str, kind: str,
                          candidates: list[dict[str, Any]]) -> dict[str, Any]:
        """判定那一趟的材料（只搬移：字面量逐字相同）。

        2026-11-08 从 `adjudicate_proposition` 拆出（体量基线是读数，不许为了它抬）。
        """
        return {
        # 这一条给三倍于候选的篇幅：它是要被判的那一条，缺了一半就没法判。
        "statement_full": full[: PROPOSITION_VERDICT_TEXT_CHARS * 3],
        "label": label,
        "kind": kind,
        "candidates": self._candidate_reading(candidates),
        "how_to_judge": ("只比条件与结论；条件强弱不同 ⇒ different；"
                         "条件只是记号/等价改写 ⇒ same；"
                         "候选表为空 ⇒ different（没有可并的对象）；"
                         "读不清就不给判词（不许猜，也不许给第三档）"),
    }

    def _identity_out(self, *, label: str, kind: str) -> dict[str, Any]:
        """这一趟的初值读数（键无条件存在：没判成由 `checked` 说，不靠少给键）。

        2026-11-08 从 `adjudicate_proposition` 拆出（只搬移，字面量逐字相同）：那一格 30 余行，
        拆出来之后 `adjudicate_proposition` 回到 200 行以内 —— 体量基线是读数，不许为了它抬。
        """
        out: dict[str, Any] = {
            #: 判词只有两档（`PROPOSITION_VERDICTS`）；空串 = 这一趟没判成（没有判词）。
            "checked": False, "verdict": "", "canonical_name": "",
            "same_as": "", "route": "", "condition": "", "conclusion": "",
            "basis": "", "reason": "", "label": label, "kind": kind,
            "candidates": [], "cost": {"ledger": "", "reason": "没发调用（还没判）"},
            "reused": False, "cached": False, "statement_sha256": "",
            #: 检索读数（2026-11-08 主动查询）：关键词 / 命中几条 / 实际交给模型看的是
            #: 哪几条（带每条命中的词）/ 判定那一趟发没发 / 一句话为什么。
            "keywords": [], "hits_total": 0, "hits_named": [], "judged": False,
            "why": "",
            #: 分页读数（2026-11-08 缺陷 ②）：候选总数 / 总页数 / 真问了几页 /
            #: 已经看过几个候选 / 是否页尽。"只看了 4 条就说都不是"与"20 条都看过"
            #: 必须在这一组数上分得开。
            "keyword_checked": False, "candidates_total": 0,
            "pages_total": 0, "pages_judged": 0, "candidates_seen": 0,
            "page_exhausted": False,
            #: 这一条判定用的是哪一条缝（`Secretary.model_source` 的三档读数：
            #: `body（…）` / `secretary（…）` / `none（…）`）。空串 = 这一名秘书是裸造的
            #: （`Secretary(...)` 没传 `seam=`），那一档就是"没有判断面"。
            #:
            #: 为什么把它放进返回值（2026-10-26 真机 sylow5）：`judge()` 那句"没有装配
            #: 模型缝"只在 `Secretary.judge` 的局部返回值里，调用方（B 的工具返回、直写
            #: 路由的 detail）看不到"缝为什么没有" —— 而 sylow5 的根因恰恰是装配处漏了
            #: 一根线，不是判据坏了。缝的来源与"判了没有"必须同时在读数上。
            "seam_source": str(self.model_source or ""),
            #: 这一格到底有没有"试过"：有缝且开关开着才是试过。
            #:
            #: 它与 `checked` 是两根轴：`attempted=False` 是"这一名秘书根本没有判同一性
            #: 这一路"（没缝），`attempted=True` + `checked=False` 是"试了、没判成"
            #: （超时 / 坏 JSON / same 点不出号 / 词表外结论）。「上层 fail-closed 的判据是
            #: 这两根轴的交集」：试过而没判成 ⇒ 不新建、不合并、受控拒（见
            #: `_merge_into_proposition`）。没有判断面的秘书走 2026-11-04 的确定性兜底
            #: （只认确定性键相同），盘上要不要留痕也由这一格决定 —— 没有缝的秘书写出来的
            #: 行必须与改前逐字节相同（否则"这一段正文之前长什么样"被一个从来没发生过的
            #: 判定改写了）。
            "attempted": bool(self.seam is not None and self.enable_model),
        }
        return out

    @staticmethod
    def _identity_pages(candidates: Sequence[Mapping[str, Any]],
                        page_size: int = PROPOSITION_VERDICT_CANDIDATES
                        ) -> list[list[dict[str, Any]]]:
        """候选表 ⇒ 判定分页（问到命中或页尽；不是截断到第一页）。

        2026-11-08 缺陷 ②：改前 `_candidate_reading` 把命中截到前 4 条，第 5–N 条
        永不入眼却记成"这批都不是"。这一格是那条纪律的唯一实现：候选按页切开，
        调用方逐页问；空候选也要给一页（洗定理名与判定是同一趟的输出）。

        独立成函数是为了留一个可打桩的判据点：反真空把这里换成"只给第一页"，
        `tests/test_one_retrieval_path_pages_until_hit_or_end.py` 必须当场红。
        """
        size = max(1, int(page_size))
        items = [dict(c) for c in (candidates or ()) if isinstance(c, Mapping)]
        return ([items[i:i + size] for i in range(0, len(items), size)] or [[]])

    @staticmethod
    def _named_hits(items: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
        """命中 / 候选的对外读数：`stmt_id` + `hit_words` 两格，逐条。

        「调用方给的候选」与「自己检索到的命中」两条来路给的是同一份形状，
        原先两处各写一遍同一段推导 —— 这里合并成一处，形状只有一份。
        """
        return [{"stmt_id": str(h.get("stmt_id") or ""),
                 "hit_words": [str(x) for x in (h.get("hit_words") or ())]}
                for h in items]

    def _identity_candidates(self, out: dict[str, Any], *,
                             candidates: Sequence[Mapping[str, Any]] | None,
                             rows: Iterable[Mapping[str, Any]] | None,
                             full: str, label: str, kind: str, task_id: str) -> bool:
        """取这一趟的候选表；返回 True = 这一趟到此为止（调用方直接回读数）。

        2026-11-08 从 `adjudicate_proposition` 拆出（只搬移，块内逐字相同）：「调用方给了候选」
        与「秘书自己挑词检索」是同一格的两条来路，合起来 50 余行；拆开之后 `adjudicate_proposition`
        回到 200 行以内 —— 体量基线是读数，不许为了它抬（业主口径：拆函数，不抬基线）。
        """
        if candidates is not None:
            supplied = [dict(c) for c in candidates
                        if isinstance(c, Mapping) and str(c.get("stmt_id") or "").strip()]
            for item in supplied:
                item.setdefault("hit_words", [])
                item.setdefault("proof_nos", [])
                item["statement_full"] = str(item.get("statement_full") or "")[
                    :PROPOSITION_VERDICT_TEXT_CHARS]
            out.update(
                keywords=[], hits_total=len(supplied),
                # 读了哪几条 = 全部（分页之后每页都会看到；这里不再截到一页）。
                hits_named=self._named_hits(supplied),
                candidates=list(supplied),
                candidates_total=len(supplied),
                why=("调用方给了候选表 ⇒ 这一趟不再自己检索" if supplied
                     else "调用方给的候选表为空 ⇒ 没有可比的条目（查过 0 条）"))
            if not supplied:
                # 兼容档：调用方已经查过一圈且明确给了空表 ⇒ 不再花一次调用（旧入口的语义）。
                out.update(checked=True, verdict=_PK.STATE_DIFFERENT, judged=False,
                           pages_total=0, pages_judged=0, candidates_seen=0,
                           page_exhausted=True,
                           reason="查过：调用方给的候选表为空（0 条）⇒ 没有同一条",
                           basis="查过：没有可比的候选 ⇒ 不同")
                self._remember_proposition_verdict(out, full=full, label=label,
                                                   task_id=task_id)
                return True
        else:
            # 检索的两件事各归一处：池过滤（`pool`）与关键词匹配（`by_keywords`）都在
            # `statementledger`；本层只负责「挑词 → 问查口」，不重写任何过滤。
            pool_rows, pool_problem = self._ledger_pool(rows)
            if pool_problem:
                out.update(checked=False, verdict="", reason=pool_problem,
                           why=pool_problem)
                return True
            if not pool_rows:
                out["why"] = ("台账里没有可检索的 active 命题（读过了，0 条）"
                              "⇒ 没有候选，判定直接判 different")
            else:
                kw = self.pick_statement_keywords(statement_full=full, label=label,
                                                  kind=kind, task_id=task_id)
                # 三格取自同一份 `kw`：checked / why 各读一次（原先 why 读两遍）。
                kw_checked = bool(kw.get("checked"))
                kw_why = str(kw.get("why") or "")
                out["keywords"] = [str(x) for x in (kw.get("keywords") or ())]
                out["keyword_checked"] = kw_checked
                out["why"] = kw_why
                if not kw_checked:
                    out.update(
                        checked=False, verdict="",
                        reason=("关键词没提取成 ⇒ 这一问没判成（不新建、不合并、受控拒）："
                                + (kw_why or "（没有给原因）")))
                    return True
                search = SL.by_keywords(rows=pool_rows, keywords=out["keywords"],
                                        text_chars=PROPOSITION_VERDICT_TEXT_CHARS)
                if not search.get("checked"):
                    out.update(checked=False, verdict="",
                               reason=str(search.get("reason")
                                          or "检索没查成 ⇒ 这一问没判成"),
                               why=str(search.get("why") or ""))
                    return True
                hits = list(search.get("hits") or [])
                out["hits_total"] = len(hits)
                # 读了哪几条 = 全部命中（分页之后每页都会看到；不再是"前 4 条"）。
                out["hits_named"] = self._named_hits(hits)
                out["candidates_total"] = len(hits)
                out["candidates"] = hits
                if not hits:
                    out["why"] = str(search.get("why") or "")
        return False

    def _ledger_pool(self, rows: Iterable[Mapping[str, Any]] | None = None
                     ) -> tuple[list[dict[str, Any]], str]:
        """本层要的那一批：可检索 / 可并的 active 命题（口径由 `statementledger.pool` 定）。

        2026-11-09 之前这里叫 `_searchable_statement_rows`，过滤三条与
        `_same_proposition_candidate` 逐字同源；现在两者都问 `statementledger.pool`。
        「这一层要哪一批」是语义决定（命题池），所以池的 kind 名单仍由这里给 ——
        名单的唯一来源是 `PROPOSITION_KINDS`，箱子里不复制它。
        """
        got, problem, _error = SL.rows_of(self.store, rows=rows)
        if problem:
            return [], problem
        return SL.pool(got or (), kinds=PROPOSITION_KINDS), ""

    def _remember_proposition_verdict(self, out: dict[str, Any], *, full: str,
                                      label: str = "", task_id: str = "") -> None:
        """把判成了的这一条落进缓存（写不成只留读数，不改这一趟的结论）。

        只该在 `out["checked"]` 为真时调用：没判成的不许缓存 —— 那会把"这一次没判成"
        变成"以后都别查了"，而缝是可能好起来的（与 `_statement_verdicts` 同一条纪律）。
        """
        if not out.get("checked"):
            return
        try:
            row = append_proposition_verdict(
                self.root, statement_full=full, verdict=str(out.get("verdict") or ""),
                canonical_name=str(out.get("canonical_name") or ""),
                same_as=str(out.get("same_as") or ""),
                route=str(out.get("route") or ""), label=label,
                condition=str(out.get("condition") or ""),
                conclusion=str(out.get("conclusion") or ""),
                basis=str(out.get("basis") or ""),
                keywords=[str(x) for x in (out.get("keywords") or ())],
                hits_total=int(out.get("hits_total") or 0),
                hits_named=list(out.get("hits_named") or ()),
                judged=bool(out.get("judged")), why=str(out.get("why") or ""),
                keyword_checked=bool(out.get("keyword_checked")),
                candidates_total=int(out.get("candidates_total") or 0),
                pages_total=int(out.get("pages_total") or 0),
                pages_judged=int(out.get("pages_judged") or 0),
                candidates_seen=int(out.get("candidates_seen") or 0),
                page_exhausted=bool(out.get("page_exhausted")),
                seam_source=str(out.get("seam_source") or ""),
                role=str(self.role or ""), task_id=str(task_id or self.task_id or ""))
            self._proposition_verdicts[_proposition_verdict_key(full)] = dict(row)
            out["cached"] = True
            out["cached_at"] = str(row.get("at") or "")
        except OSError as exc:
            # 缓存写不成不影响这一趟的结论（结论已经在返回值里），但必须说出来：
            # 写不成意味着下一趟还要再花一次钱。
            out["cache_problem"] = f"{type(exc).__name__}: {exc}"
            self._log(f"命题判定台账没写成：{out['cache_problem']}")

    @staticmethod
    def _with_adjudication_visibility(adj: Mapping[str, Any]) -> dict[str, Any]:
        """把"判了没有"那一格挂到判定返回值上（键名 `proposition_adjudication`）。

        ## 它为什么必须存在（真机 sylow5，2026-10-26）

        改前这一格只活在 `checked` / `reason` 两个平铺的键里，而它们旁边紧挨着
        `verdict` / `canonical_name` / `basis` 那一组判词 —— 读的人（尤其是模型，
        它只看工具返回的那一份 JSON）很容易把它们读成"判过了，结论是某一档"。
        真机 sylow5 的后果就是：`out/secretary/proposition_verdicts.jsonl` 一次都没
        建出来，而会话里没有任何一格说"这一条判定根本没发生"。

        所以这里把三件事收进同一格、显式命名：
        - `checked`：判成了没有（`False` 不是说"不同"，是"没判"）；
        - `attempted`：有没有真的去判（没缝 ⇒ `False`，试了没成 ⇒ `True`）；
        - `seam_source`：这一条判定用的哪条缝（`none（…）` 就是没接线）。

        检索读数（`keywords` / `hits_total` / `hits_named` / `judged`）也在这一格里：
        "它确实自己查过一圈"必须与"判了没有"同时看得见（2026-11-08 业主：
        「语义判定当前实现是秘书主动查询还是必须全过一遍？应该是主动查询」）。

        ## 为什么挂在这里而不是每个 `return` 自己写

        :meth:`adjudicate_proposition` 有五条返回路径（不是命题 / 正文空 / 沿用缓存 /
        没查成 / 判了）。让每条路径各写一次，等于把"这一格在不在"交给五处自觉 ——
        而本仓最贵的那一类缺陷正是"某一条返回路径少写一格"。所以只留一个出口。
        """
        out = dict(adj)
        out["proposition_adjudication"] = {
            "checked": bool(out.get("checked")),
            "attempted": bool(out.get("attempted")),
            "verdict": str(out.get("verdict") or ""),
            "reason": str(out.get("reason") or ""),
            "seam_source": str(out.get("seam_source") or ""),
            "reused": bool(out.get("reused")),
            "keywords": [str(x) for x in (out.get("keywords") or ())],
            "hits_total": int(out.get("hits_total") or 0),
            "hits_named": [dict(x) if isinstance(x, Mapping) else {"stmt_id": str(x)}
                           for x in (out.get("hits_named") or ())],
            "judged": bool(out.get("judged")),
            "same_as": str(out.get("same_as") or ""),
            "why": str(out.get("why") or ""),
            #: 分页读数（2026-11-08 缺陷 ②）：看了几页 / 几个候选 / 是否页尽。
            "keyword_checked": bool(out.get("keyword_checked")),
            "candidates_total": int(out.get("candidates_total") or 0),
            "pages_total": int(out.get("pages_total") or 0),
            "pages_judged": int(out.get("pages_judged") or 0),
            "candidates_seen": int(out.get("candidates_seen") or 0),
            "page_exhausted": bool(out.get("page_exhausted")),
        }
        return out

    @staticmethod
    def _annotate_proposition(row: dict[str, Any], adj: Mapping[str, Any], *,
                              proof_no: int = 1, route: str = "") -> dict[str, Any]:
        """把"这一次判定"与"这条路子"落到命题行上（只加读数键，不动 schema）。

        ## 两格，各管一件事
        - `PROOF_ROUTES_KEY` 那一格 = {证明号: 一句话}：这条路线的说明。业主 2026-10-24：
          「路线写在证明这一层」—— 它从此不住在 label 里，也不再丢（洗名不是丢信息）。
        - `_proposition_adjudication = {verdict, basis, ...}`：这一条是凭哪一次判定落成
          现在这样的。判 different 的也要落：只落 same 的记录，读的人就分不出
          "判过了、不同"与"没人判过"（没判成是 `checked=False`，与"判过了"必须分得开）。
        这两个键都不在 `schema.Statement` 里 —— store 落的是 JSON 行，`row_from_dict` 只取
        它认识的键（与命题并表痕迹 / `proof_history` 同一做法），所以不必动 schema。
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
                # 这一条判定用的是哪条缝（2026-11-08，①）：`body（…）` / `secretary（…）` /
                # `none（…）` / 空串（裸造）。收工读数按它数 `seam_source` 分布 ——
                # "整条判定链是死的"（sylow5）必须在盘上读得出来，不能只在返回值里。
                "seam_source": str(adj.get("seam_source") or ""),
                "seam_attempted": bool(adj.get("attempted")),
                "at": S.now_iso(),
            }
        return out

    def wash_dependency_face(self, manuscript: Any, *,
                             statement_rows: Any = None) -> dict[str, Any]:
        """F 的秘书那一遍洗稿：只洗依赖面（命题号 / 那一节的格式），不改证明正文。

        业主 2026-10-26 晚的原话（逐字）：「F写证明时务必加依赖面命题号，且由F的秘书对
        无引用证明忘加空依赖面的补空，对有引用证明的命题号核实（即秘书帮它洗一遍）」
        「F的秘书工作的时候是F写好了，提交证明给V前」「秘书若核出问题，要提前打回并说明」。

        所以这一笔的位置是"F 写完、提交给 V 之前"（`agent_f/core.py` 的 proof 分支在
        `_proof_outlet` 之前调它）：洗过的那一份才是提交给 V、被 D 携带、被 B 读的稿。
        打回时这一轮不提交（不花 V 的那一次调用），`deps_refused_findings` 逐条给
        F 看：哪一行、引用原话、写的是哪个号、应该是什么、为什么、怎么改。

        实现全在 `depsection.wash_dependency_section`（解析与渲染的唯一实现也在那里）；
        本方法只负责两件事：读 `statements`（核实命题号要它），以及把"没 store / 读不到"
        如实折成 `checked=False` —— 不许把"没核成"当成"核过了"。
        """
        from . import depsection as _DS

        out: dict[str, Any] = {
            "checked": False, "washed": False, "text": str(manuscript or ""),
            "deps_section_filled": "", "deps_washing": [], "deps_refused": "",
            "deps_refused_findings": [], "reason": "",
            "actor": f"secretary-{self.role}", "rows": [], "section": {},
        }
        if self.store is None:
            out["reason"] = ("这一名秘书没有 store ⇒ 读不到 `statements`，命题号核不了"
                             "（不洗、也不假装洗过）：这一份先别提交给 V")
            return out
        rows = statement_rows
        if rows is None:
            try:
                rows = [dict(r) for r in self.store.rows("statements")]
            except Exception as exc:  # noqa: BLE001 —— 读不到就不许放行
                out["reason"] = (f"`statements` 读不出来（{type(exc).__name__}: {exc}）⇒ "
                                 "这一遍没核成（没核成不等于没问题）：这一份先别提交给 V")
                return out
        got = _DS.wash_dependency_section(str(manuscript or ""), statement_rows=rows)
        out.update(dict(got or {}))
        out["checked"] = True
        out["actor"] = f"secretary-{self.role}"
        return out

    def extract_manuscript(self, rel: Any, cells: Iterable[str]) -> dict[str, Any]:
        """从一份稿里按调用方指定的格读出来（纯读；不写盘、不写台账、不判签）。

        ## 为什么在秘书层（T1，设计 `_design_T123.md` §2.1 / §2.8）

        业主的形态是「自动录入是 B 秘书的一个工具，需 B 秘书指定录入位置和录入格后，
        从稿中提取内容录入」。于是"从稿里取内容"归秘书：B 本体只把位置 + 格传下来，
        不自己切节、不自己解析表格、不自己读稿头。真正的逐格解析在
        `manuscriptintake.extract_cells`（纯函数、零 I/O），本方法只做三件这一层才有的事：
        读盘、判族/目录、把稿头那几格一并读出来。

        ## 返回（键固定）

        `{checked, path, family, tier, manuscript_id, proof_no, name_proof_no,
        canonical, head_experiment_id,
        head_statement_text, head_label, declared_kind, sha256, proof_sha256,
        proof_state, cells, why, error}`。

        稿头不再有「证明号」那一格可读（产出侧废掉了 `pN`；路径号由收录事务分配），
        所以返回里没有 `head_proof_no` —— 「第几份」唯一来源是秘书在锁里分出来的号。

        - `cells` 是 `extract_cells` 的原样读数（每格 `present / absent / unreadable`）；
        - `proof_state` 是 `## 证明` 那一节的三态（缺节 ≠ 空节）；
        - `sha256` 是整份稿的字节 sha，`proof_sha256` 是 `## 证明` 正文的 sha
          （与签的对拍尺同一把：`proofregistry.proof_sha`）。

        ## 三态（不折平）

        读不到盘 / 不是文本 ⇒ `checked=False` + `why`（这是"没读到"，不是"稿里没有"）；
        路径不在手稿族（`legacy` / `bad_name` / `unrecognized`）照样给出 `cells`
        —— `preview` 要能看清历史档里有什么；能不能收录由调用方按 `tier` 拒，
        本方法不替它做那个决定。
        """
        from . import depsection as _DS
        from . import manuscriptfamily as _MFAM
        from . import manuscriptintake as _MI
        from . import proofregistry as _PR

        path = str(rel or "").strip().replace("\\", "/")
        shape = _MFAM.classify_manuscript(path)
        out: dict[str, Any] = {
            "checked": False, "path": path,
            "family": str(shape.get("family") or ""),
            "tier": str(shape.get("tier") or ""),
            "manuscript_id": str(shape.get("manuscript_id") or ""),
            "proof_no": int(shape.get("proof_no") or 0),
            "name_proof_no": int(shape.get("proof_no") or 0),
            "canonical": str(shape.get("canonical") or ""),
            "head_experiment_id": "", "head_statement_text": "",
            "head_label": "", "declared_kind": "",
            "sha256": "", "proof_sha256": "",
            "proof_state": _MI.EXTRACT_UNREADABLE,
            "cells": {}, "why": "", "error": {},
        }
        if not path:
            out.update(why="没有给手稿路径 ⇒ 没有可读的稿（不是「稿里没有这一节」）")
            return out
        try:
            text = (self.root / path).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            out.update(why=f"读不到 `{path}`（{type(exc).__name__}: {exc}）",
                       error={"type": type(exc).__name__, "message": str(exc)})
            return out
        out["sha256"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
        family = str(shape.get("family") or _MFAM.LEGACY_FAMILY)
        try:
            readings = _MI.extract_cells(text, family, list(cells))
        except ValueError as exc:
            out.update(why=f"这一笔要读的格不合法（{exc}）⇒ 一格都没读")
            return out
        out["cells"] = readings
        proof = readings.get("proof_text") or {}
        out["proof_state"] = str(proof.get("outcome") or _MI.EXTRACT_ABSENT)
        out["proof_sha256"] = str((proof.get("source") or {}).get("sha") or "")
        head = _manuscript_head_fields(text)
        out["head_experiment_id"] = str(head.get("实验号") or "").strip()
        out["head_statement_text"] = str(head.get("命题键") or "").strip()
        try:
            entry = dict(_PR.parse_entry(text) or {})
        except Exception:  # noqa: BLE001 —— 稿头读不出来就是没有登记元信息（不猜）
            entry = {}
        out["head_label"] = str(entry.get("label") or "").strip()
        from . import manuscriptkind as _MK

        declared = str(
            entry.get("kind")
            or head.get(_MK.mark_key(_MK.PROPOSITION_KIND_MARK))
            or head.get(_MK.mark_key(_MK.LEGACY_PROPOSITION_KIND_MARK))
            or "").strip().lower()
        out["declared_kind"] = declared if declared in PROPOSITION_KINDS else ""
        out["checked"] = True
        return out

    def record_manuscript_dependency_face(self, stmt_id: str, groups: Any, *,
                                          proof_no: int = 1,
                                          path_group: int = 0,
                                          note: str = "",
                                          manuscript: str = "",
                                          body_sha: str = "",
                                          reserve: bool = False,
                                          proof_text: str = "") -> dict[str, Any]:
        """收方读稿登记：把一份手稿的依赖段落成那条在册命题的 `dependencies` 行。

        ## 为什么需要这一格（业主 2026-10-26 晚：「D 到 B 没有路吗？加」）

        F 交稿时那一行是 F 自己落的（`_proof_outlet`），于是"这条命题的依赖面"
        从来没有第二个写者：D 只能派 B，不能把稿递给 B；B 那一笔登记也只会发生在
        "新建一条命题"的时候 —— 同一条命题再交一次就走 `duplicate` 早退，
        `dependencies` 一行都不落。这条通道补的正是那一格：命题行不动，只把
        手稿里那一节 `## 依赖` 的表格落成依赖边（B 是收方、秘书是写者）。

        ## 路径号（业主口径：归秘书，在这一笔事务里分配）
        `groups` 里那几格路径号是产出侧 / 调用方给的，一律不采信：这一笔的号由
        :func:`_assign_path_group_in_tx` 在同一把锁里分（同一命题已有 N 条 ⇒ N+1；
        同一份正文 sha / 同一份稿重复携带 ⇒ 沿用原号）。回执的 `path_group` 是这一笔
        用的号，`path_group_reading` 是分配函数的原样读数。`proof_no` 参数只为兼容
        旧调用面保留，一个字节都不参与定号（给了就在 `path_group_ignored` 里点名）。

        ## 两件事一起保证
        - 幂等：同一 `used_by` + 路径组 + 来源已经有一条依赖 ⇒ 不重复落（D 每趟都
          会携带一遍，重复落会让依赖表虚高）；读数里 `duplicates` 逐条说"哪几条已经在了"；
        - 判据不另写：解析在 `depsection`、来源在册/档位在 `B.register_statement`
          那一侧（它先把 `manuscript` 与 `gate_rows` 跑完才到这里），本方法只负责
          "把已经核过的步骤写进表"（`_resolve_write_steps` + `_write_dep_steps`）。
        """
        out: dict[str, Any] = {"checked": False, "stmt_id": str(stmt_id or ""),
                               "deps_written": 0, "path_groups": 0, "duplicates": [],
                               "refused": "", "reason": "", "tables": [],
                               "deps_dangling": [], "deps_unmappable": []}
        if self.store is None:
            out.update(refused="secretary_unavailable",
                       reason="这一名秘书没有 store ⇒ 依赖面写不了")
            return out
        sid = str(stmt_id or "").strip()
        if not sid:
            out.update(refused="bad_statement_id", reason="没有命题号 ⇒ 依赖面挂不到任何一行")
            return out
        groups = [list(g) for g in (groups or []) if isinstance(g, (list, tuple))]
        if not groups and not reserve:
            out.update(checked=True, reason="这一份手稿的依赖段是空的（自足证明合法，不写边）")
            return out
        if not groups and reserve:
            # 只分号 / 只核对号、不写边（实现在 `_reserve_path_only`）。
            return self._reserve_path_only(
                sid=sid, note=note, manuscript=manuscript,
                body_sha=body_sha, path_group=path_group)
        _named_group = int(path_group or 0)
        # 优化线是"换已存在那条路径的正文"，不是新路径 ⇒ 不问同种证明那一问
        # （那一问决定的是"要不要新开一条路径"；拿它拦改写会把优化线堵死）。
        _gate = ({} if _named_group >= 1
                 else self._manuscript_dependency_refusal(sid=sid, proof_text=proof_text))
        if _gate:
            out.update(_gate)
            return out
        try:
            with self.store.tx("statements", "dependencies",
                               actor=f"secretary-{self.role}",
                               note=note or "record_manuscript_dependency_face") as tx:
                # 按号定位走查口（口径一）；事务快照传 `rows=`，锁内读失败仍照旧抛出。
                if not SL.by_id(rows=tx.rows("statements"), stmt_id=sid)["found"]:
                    out.update(refused="statement_missing",
                               reason=(f"台账里没有 stmt:{sid} ⇒ 依赖面挂不到任何一行"
                                       "（收方读稿登记的是在册命题的依赖面）"))
                    return out
                # ---- 路径号：这一笔的依赖面属于「第几条证明」，由秘书在锁里分 ----
                #
                # 只有在调用方给了这一份稿的身份（`manuscript` / `body_sha`）时才分号：
                # 没有身份就无法认"同一份正文已经在第几条路径上"，硬分号会把同一份稿的
                # 第二遍携带记成新路径（D3 的幂等就是这条）。没有身份 ⇒ 按材料给的号落
                # （老调用面 / 夹具的既定口径）。
                # 只请求依赖格（没读证明正文）时 `body_sha` 是空的 ⇒ 用这一行在册的
                # 正文补上：这一笔收的就是它那一份稿，不许因此另开一条路径。
                if not str(body_sha or "").strip():
                    from . import verifications as _VR_canon

                    _canon_row = SL.by_id(rows=tx.rows("statements"), stmt_id=sid)["row"]
                    _canon_text = str((_canon_row or {}).get("proof_text") or "")
                    if _canon_text.strip():
                        body_sha = _VR_canon.text_sha(_canon_text)
                _has_identity = bool(str(body_sha or "").strip()
                                     or str(manuscript or "").strip())
                if _named_group >= 1:
                    # 优化线：号不分配，只核对"第 n 条路径确实存在且对得上这一份稿"。
                    if not _has_identity:
                        out.update(refused="bad_path_identity",
                                   reason=("优化线要给已存在的路径号，也要给这一份稿的身份"
                                           "（`manuscript` / `body_sha`）：没有身份就核不了"
                                           "它是不是那条路径的稿"))
                        return out
                    _alloc = _existing_path_group_in_tx(
                        tx, root=self.root, statement_id=sid,
                        path_group=_named_group, manuscript=manuscript,
                        body_sha=body_sha)
                    if _alloc.get("refused"):
                        out.update(refused=str(_alloc.get("refused") or "path_group_refused"),
                                   reason=str(_alloc.get("reason") or ""))
                        return out
                    if not _alloc.get("checked"):
                        out.update(refused="path_group_unreadable",
                                   reason=("路径数读不出来 ⇒ 这一份的依赖面不落（不猜第几条）："
                                           + str(_alloc.get("why") or "未知原因")))
                        return out
                    group_no = int(_alloc.get("path_group") or _named_group)
                    _note_path_material(out, _path_material_numbers(groups),
                                        decided=group_no)
                    out["path_group"] = group_no
                    out["path_group_reading"] = dict(_alloc)
                elif _has_identity:
                    _alloc = _assign_path_group_in_tx(
                        tx, root=self.root, statement_id=sid,
                        manuscript=manuscript, body_sha=body_sha)
                    if not _alloc.get("checked"):
                        out.update(refused="path_group_unreadable",
                                   reason=("路径数读不出来 ⇒ 这一份的依赖面不落（不猜第几条）："
                                           + str(_alloc.get("why") or "未知原因")))
                        return out
                    group_no = int(_alloc.get("path_group") or 1)
                    # 材料（手稿依赖表第 4 列）与秘书定的号不一致 ⇒ 点名；号以秘书为准。
                    _note_path_material(out, _path_material_numbers(groups),
                                        decided=group_no)
                    out["path_group"] = group_no
                    out["path_group_reading"] = dict(_alloc)
                else:
                    group_no = int(proof_no or 1)
                    out["path_group"] = group_no
                    out["path_group_reading"] = {
                        "checked": False, "path_group": group_no,
                        "why": ("没有稿身份（`manuscript` / `body_sha` 都没给）"
                                "⇒ 按材料给的号落，不去认第几条")}
                if int(proof_no or 0) >= 1 and int(proof_no or 0) != group_no:
                    out["path_group_ignored"] = {
                        "given": int(proof_no), "by": "调用方",
                        "why": ("证明号 / 路径号由秘书在收录事务里分配"
                                "（`assign_path_group`）⇒ 调用方给的这个数不采信"),
                    }
                # ---- 「难以自证」的空号 ⇒ 整条替换（业主 2026-11-13 裁定）------------
                #
                # 位置在"号已经定下来、依赖边还没写"这一刻：替换要换的四样东西必须
                # 同一笔落，而号必须还是刚才在锁里分出来的那一个。返回 False ⇒ 这
                # 一行没有空号（照旧走下面的"追加 + 去重"那一路，行为逐字不变）。
                if self._fill_vacant_path_if_any(
                        tx, sid=sid, proof_text=proof_text, groups=groups,
                        out=out, manuscript=manuscript, group=group_no):
                    return out
                body = {"deps": groups, "proof_no": group_no}
                steps = self._resolve_write_steps(tx, body, out, groups)
                if steps is None:
                    return out
                # 号盖在已解析的步骤上：手稿依赖段那一路 `used_by` 尾巴与
                # `path_group` 同号（一份稿 = 一份证明 = 一条路径）。没有稿身份时
                # 不盖 —— 材料自己那几格就是这一笔要落的口径（幂等靠它们）。
                if _has_identity:
                    steps = _stamp_path_number(steps, path_group=group_no,
                                               proof_no=group_no)
                existing = set()
                for row in tx.rows("dependencies"):
                    existing.add(_dep_step_key(dict(row)))
                keep: list[dict[str, Any]] = []
                for step in steps:
                    key = _dep_step_key({
                        "used_by": _PL.used_by_of(
                            f"stmt:{sid}", int(step.get("proof_no") or group_no)),
                        "path_group": int(step.get("path_group") or group_no),
                        "kind": str(step.get("kind") or "theorem"),
                        "source_stmt_id": step.get("source_stmt_id"),
                        "source_lit_id": step.get("source_lit_id"),
                        "source_experiment_id": step.get("source_experiment_id"),
                        "source_doc_id": step.get("source_doc_id"),
                        "label": str(step.get("label") or ""),
                    })
                    if key in existing:
                        out["duplicates"].append({
                            "path_group": int(step.get("path_group") or group_no),
                            "label": str(step.get("label") or ""),
                            "why": "这一条依赖已经在表里（同一路径组、同一来源）⇒ 不重复落"})
                        continue
                    keep.append(step)
                if not keep:
                    out.update(checked=True, path_groups=len(groups),
                               reason="这一份手稿的依赖边都已经在表里（幂等：一条都没重复落）")
                    return out
                written = self._write_dep_steps(tx, keep, stmt_id=sid, body=body)
                out.update(checked=True, deps_written=int(written),
                           #: 其中"命题→命题"几条（2026-11-05 缺陷 1c：两个数分开读）。
                           deps_stmt_edges=_stmt_edge_count(keep),
                           path_groups=len(groups), tables=["dependencies"])
        except Exception as exc:  # noqa: BLE001 —— 落盘失败必须回三态，不许半笔
            out.update(checked=False, refused="write_failed",
                       reason=f"依赖面落盘没成（{type(exc).__name__}: {exc}）⇒ 这一笔按'没写成'读")
        return out

    def _reserve_path_only(self, *, sid: str, note: str, manuscript: str,
                           body_sha: str, path_group: int) -> dict[str, Any]:
        """`record_manuscript_dependency_face` 的"只分号 / 只核对号"那一支（不写边）。

        `path_group=0` ⇒ 由秘书在锁里分配"第几条"（另一条路径 / canonical）；
        `path_group>=1` ⇒ 优化线：只核对这个号已存在且对得上这一份稿（不分配）。
        一个字节的依赖行都不写；号只进回执，后面的正文写口用它。
        """
        out: dict[str, Any] = {"checked": False, "stmt_id": sid, "deps_written": 0,
                               "path_groups": 0, "duplicates": [], "refused": "",
                               "reason": "", "tables": [], "deps_dangling": [],
                               "deps_unmappable": []}
        try:
            with self.store.tx("statements", "dependencies",
                               actor=f"secretary-{self.role}",
                               note=note or "record_manuscript_dependency_face:reserve") as tx:
                if not SL.by_id(rows=tx.rows("statements"), stmt_id=sid)["found"]:
                    out.update(refused="statement_missing",
                               reason=(f"台账里没有 stmt:{sid} ⇒ 路径号分不了"))
                    return out
                _named = int(path_group or 0)
                if _named >= 1:
                    _alloc = _existing_path_group_in_tx(
                        tx, root=self.root, statement_id=sid, path_group=_named,
                        manuscript=manuscript, body_sha=body_sha)
                else:
                    _alloc = _assign_path_group_in_tx(
                        tx, root=self.root, statement_id=sid,
                        manuscript=manuscript, body_sha=body_sha)
                if _alloc.get("refused"):
                    out.update(refused=str(_alloc.get("refused") or "path_group_refused"),
                               reason=str(_alloc.get("reason") or ""))
                    return out
                if not _alloc.get("checked"):
                    out.update(refused="path_group_unreadable",
                               reason=("路径数读不出来 ⇒ 这一笔不写（不猜第几条）："
                                       + str(_alloc.get("why") or "未知原因")))
                    return out
                out.update(checked=True, deps_written=0, path_groups=0,
                           path_group=int(_alloc.get("path_group") or _named or 1),
                           path_group_reading=dict(_alloc),
                           reason=(("这一笔没有请求依赖格 ⇒ 只核对已存在的路径号（不写边）"
                                    if _named else
                                    "这一笔没有请求依赖格 ⇒ 只分配路径号（不写边）")))
        except Exception as exc:  # noqa: BLE001 —— 分号失败必须回三态，不许半笔
            out.update(checked=False, refused="write_failed",
                       reason=(f"路径号没分成（{type(exc).__name__}: {exc}）"
                               " ⇒ 这一笔按'没写成'读"))
        return out

    def _manuscript_dependency_refusal(self, *, sid: str, proof_text: str) -> dict[str, Any]:
        """同种证明那一问（事务外先问，锁内只落）：same / 判不了 ⇒ 拒收读数。

        只在"这一份正文是新的"时问：同一份正文（sha 已在册）是幂等重交，不是另一套
        证法。判 same ⇒ 点名第 N 条路径；判不了 ⇒ fail-closed；different ⇒ 空字典
        （调用方继续分号、写边）。这是 apply 那条入口的分配点（仍是秘书的唯一实现）。
        """
        if not str(proof_text or "").strip():
            return {}
        from . import verifications as _VRkind

        got_row = SL.by_id(self.store, stmt_id=sid)
        if not (got_row.get("checked") and got_row.get("found")):
            return {}
        row_now = dict(got_row.get("row") or {})
        _known = {_VRkind.text_sha(str(t)) for _n, t in
                  _VRkind.proof_list(row_now) if str(t or "").strip()}
        if _VRkind.text_sha(str(proof_text)) in _known:
            return {}
        _kind = self._same_kind_hits(row_now, str(proof_text))
        _sim = float(_kind.get("similarity") or 0.0)
        if not _kind.get("checked"):
            return {"checked": False, "refused": PROOF_KIND_UNJUDGED,
                    "vacant_reading": dict(_kind.get("vacant_reading") or {}),
                    "reason": ("这一份证明与在册各路径是不是同种没判成"
                               "（没判成 ≠ 不同）⇒ 不收录、不新增路径："
                               + str(_kind.get("reason") or "判定面没给可用结论"))}
        if str(_kind.get("decision") or "") != "same":
            return {}
        _n = int(_kind.get("same_path") or 1)
        #: 三态读数进拒信：读不出来时要点名"没把任何一条当空号"（fail-closed 的样子
        #: 必须看得见 —— 否则"读不出来"与"查过了、没有空号"在回执里长得一样）。
        _vac = dict(_kind.get("vacant_reading") or {})
        _vac_note = ""
        if not _vac.get("checked"):
            _vac_note = ("（`bits.evidence.hard_to_prove_by_proof` 那一格读不出来 ⇒ "
                         "不把任何一条路径当空号，按普通「已有证明」处置："
                         + str(_vac.get("why") or "未知原因") + "）")
        return {"checked": False, "refused": PROOF_SAME_KIND,
                "same_kind_material": {"similarity": _sim},
                #: 空号那一格的三态读数（这一笔判成"同种"时它一定是"没有空号"或
                #: "读不出来"：读得出来且记着难以自证的路径根本不会进比较）。
                "vacant_reading": _vac,
                "reason": (f"这一份证明与 stmt:{sid} 的第 {_n} 条路径同种"
                           "（秘书的语义判定：两套证法是同一路，不是两条独立路径）"
                           "⇒ 不收录、不新增路径。材料读数（只作参考）：相似度 "
                           f"{_sim:.4f}。处置：换一条真正不同的证法再交，或本次不再提交"
                           + _vac_note)}

    @staticmethod
    def _reset_optimization_column(bits: Mapping[str, Any],
                                   proof_no: int) -> dict[str, Any]:
        """把某一份的优化栏复位成「未优化」，并抹掉它的「难以自证」记录。

        业主 2026-11-13：「将优化栏更新为新稿提交一致的未优化」。两格都要动，
        缺一格都会留下旧稿的结论：

        - `bits.evidence.optimized_by_proof[号] = False`（新稿刚交上来，还没洗过）；
        - `bits.evidence.hard_to_prove_by_proof[号]` 整条删掉 —— 那一格说的是"上一份
          正文证不出来"，新正文换了，这句话就不再成立；留着它，读侧
          `evidencebits.optimized_state` 会把新稿读成第四档 `hard_to_prove`。

        只动这两格：`reviewed` / `reviewed_source` 是 V 的签名面，由
        `vsigns.bits_after_sign` 写（同一个口袋，两个写者不重叠）。
        """
        from . import evidencebits as _EB

        out = _EB.with_optimized_flag(dict(bits or {}), int(proof_no), False)
        table = {str(int(n)): dict(v)
                 for n, v in _EB.hard_to_prove_by_proof(out).items()
                 if int(n) != int(proof_no)}
        ev = dict(out.get("evidence") or {})
        if table:
            ev[_EB.HARD_TO_PROVE_KEY] = table
        else:
            ev.pop(_EB.HARD_TO_PROVE_KEY, None)
        out["evidence"] = ev
        return out

    def _fill_vacant_path_in_tx(self, tx: Any, *, row: Mapping[str, Any], sid: str,
                                proof_text: Any, groups: list[list[dict[str, Any]]],
                                out: dict[str, Any], manuscript: str = "",
                                group: int = 0) -> dict[str, Any] | None:
        """把一份带真 V 签的新稿整条替换到「难以自证」那条空号上。

        业主 2026-11-13 裁定（逐字）：「后续提交 V 签稿时应替换该路径的证明稿、
        依赖面、V 签、引文状态等等，且将优化栏更新为新稿提交一致的未优化。」
        四样东西不在同一笔里换 ⇒ 盘上会出现"新稿 + 旧依赖"或"新稿 + 引文占位签"
        这种谁也读不准的半笔；所以这里一次换完，且全在调用方那一把锁里。

        | # | 格 | 换成什么 |
        |---|---|---|
        | ① | 证明稿：`proof_text` / `proofs[n]` + `proof_history` | 新正文；旧正文按号进历史（谁都能回答"这一版之前是哪一版"） |
        | ② | 依赖面：`dependencies` 里 `path_group=n` 的那几行 | 先删旧行、再写这一份稿的边（同一把锁里，要么全换要么全不换） |
        | ③ | V 签：`bits` 的逐份表 / sha 表 / `reviewed` / `reviewed_source` | 由 `vsigns.bits_after_sign` 认签（唯一口）：占位签 ⇒ 真签 |
        | ④ | 证明稿两格：`manuscripts[n]` + `manuscript_id` | 这一份稿的路径与稿号（后者是"最近一次收录的那份"的兼容读数） |
        | ⑤ | 优化栏：`optimized_by_proof[n]` / `hard_to_prove_by_proof[n]` | 复位成未优化 + 抹掉旧的难以自证（见 :meth:`_reset_optimization_column`） |

        ## 什么时候"不是这一笔"（返回 `None`，调用方照旧）
        - 这一行没有空号（`vacant_path_reading` 没有记着的那几条）；
        - 这一笔没带证明正文，或正文与空号上那一份逐字相同（那是幂等重交，不是替换）；
        - 「难以自证」那一格读不出来 ⇒ `None`（fail-closed：按普通已有证明处置，
          绝不拿一行坏字节抹掉整道"已有证明"判断）。

        ## 什么时候受控拒（`out` 里带 `refused`，一个字节都不写）
        - 这一份正文没有真 V 签 ⇒ `proof_without_v_sign`：替换的资格就是"真签"，
          没有签的正文不许盖掉在册那一份（与优化线换正文同一条判据）；
        - 依赖面判不了（`_resolve_write_steps` 的受控拒）⇒ 原样返回，整笔不写。
        """
        from . import manuscriptpaths as _MP
        from . import verifications as _VR
        from . import vsigns as _VS

        text = str(proof_text or "")
        if not text.strip():
            return None
        vac = _MP.vacant_path_reading(row)
        out["vacant_reading"] = dict(vac)
        if not vac.get("checked"):
            # 读不出来 ⇒ 不许当成空号（fail-closed：按普通已有证明那一路处置）。
            return None
        vacant = [int(g) for g in (vac.get("groups") or [])]
        if int(group or 0) >= 1:
            if int(group) not in vacant:
                return None
            no = int(group)
        else:
            if not vacant:
                return None
            no = min(vacant)
        old = str(_VR.proof_text_of(row, no) or "")
        if old.strip() == text.strip():
            return None
        # ---- ① 真 V 签：先认签（唯一口 `vsigns.bits_after_sign`）----------------
        #
        # 位置在最前：没有签的正文不许盖掉在册那一份（否则这一笔只是"把一份没签的
        # 正文写了进去"，而替换的前提是"优化后拿 V 签"）。认签同时把第 3 位那几张表
        # 从占位改成真签 —— 这一步就是"V 签 / 引文状态"那一格的替换。
        claimed, sign = _VS.bits_after_sign(
            row.get("bits") or {}, root=self.root, proof_text=text,
            statement_id=str(sid), proof_no=no, kind=str(row.get("kind") or ""),
            store=self.store)
        out["replacement_sign"] = {
            "checked": bool(sign.get("checked")),
            "applied": bool(sign.get("applied")),
            "state": str(sign.get("state") or ""),
            "why": str(sign.get("why") or "")}
        if not sign.get("applied"):
            out.update(checked=False, refused="proof_without_v_sign",
                       reason=("第 " + str(no) + " 条路径是「难以自证」的空号：要填上它"
                               "必须交一份有真 V 签的稿，而这一份没有（"
                               + str(sign.get("state") or "unsigned") + "："
                               + str(sign.get("why") or "") + "）⇒ 不替换，一个字节没动"))
            return out
        # ---- ② 依赖面：先把这一份稿的边解出来（判不了 ⇒ 整笔不写）--------------
        body_for_deps = {"proof_no": int(no), "deps": [list(g) for g in groups]}
        steps = self._resolve_write_steps(tx, body_for_deps, out, groups)
        if steps is None:
            return out
        steps = _stamp_path_number(steps, path_group=int(no), proof_no=int(no),
                                   single_group=len(groups) <= 1)
        # ---- ③ 证明稿：旧正文按号进 `proof_history`，这一份落到同一个号上 --------
        raw_history = row.get("proof_history")
        history = ([dict(h) if isinstance(h, Mapping) else h for h in raw_history]
                   if isinstance(raw_history, (list, tuple)) else [])
        if old.strip():
            entry = {"text": old, "sha": _VR.text_sha(old), "at": S.now_iso(),
                     "replaced_by": _VR.text_sha(text), "proof_no": int(no),
                     "why": ("第 " + str(no) + " 条路径本来是「难以自证」的引文占位，"
                             "被一份带真 V 签的新稿整条替换")}
            history.append(entry)
            out["proof_history"] = [dict(entry)]
        new_row = dict(row)
        new_row["proof_history"] = history
        if int(no) == 1:
            new_row["proof_text"] = text
        else:
            listed = [dict(p) if isinstance(p, Mapping) else p
                      for p in (new_row.get(_VR.PROOFS_KEY) or [])]
            for i, one in enumerate(listed):
                if isinstance(one, Mapping) and int(one.get("proof_no") or 0) == int(no):
                    listed[i] = {**dict(one), "text": text,
                                 "proof_sha256": _VR.text_sha(text)}
                    break
            else:
                listed.append({"proof_no": int(no), "text": text,
                               "proof_sha256": _VR.text_sha(text),
                               "created_at": S.now_iso()})
            new_row[_VR.PROOFS_KEY] = listed
        # ---- ④ 优化栏复位（新稿 = 未优化；旧的难以自证不许留）--------------------
        new_row["bits"] = self._reset_optimization_column(claimed, no)
        # ---- ④b 引文状态：占位签 ⇒ 真签（第 3 位的凭据档那一格）------------------
        #
        # 认签口（`vsigns.bits_after_sign` ⇒ `_apply_review_to_bits`）写的是逐份表 /
        # sha 表 / `reviewed`；"凭什么是真"这一格（`evidence.reviewed_source`）只在
        # `bits_of` 构造时写（真签 ⇒ `v`、占位 ⇒ `citation`）。从引文占位换上来的一行
        # 因此会带着上一版的 `reviewed_source="citation"` 读下去（`reviewed=true` 而
        # "凭什么是真：文献编号"）—— 业主 2026-11-13 的"引文状态……替换"就是这一格。
        # 取值仍只有词表里那两个（`v` / `citation`），不新增一档。
        from . import evidencebits as _EB
        _ev = dict(new_row["bits"].get("evidence") or {})
        _ev["reviewed_source"] = _EB.REVIEWED_SOURCE_V
        new_row["bits"]["evidence"] = _ev
        # ---- ⑤ 证明稿的两格：`manuscripts[n]` + `manuscript_id` -------------------
        rel = str(manuscript or "").strip().replace("\\", "/")
        if rel:
            per = dict(new_row.get(_MP.PER_PATH_KEY) or {})
            per[str(int(no))] = rel
            new_row[_MP.PER_PATH_KEY] = per
            mid = str(_VS.manuscript_id_of(rel) or "")
            if mid:
                new_row["manuscript_id"] = mid
        # ---- ⑥ 依赖面：这一条路径的旧行整批换掉（同一把锁里）--------------------
        dropped = 0
        for dep in list(tx.rows("dependencies")):
            if str(dep.get("used_by") or "").split("#", 1)[0] != f"stmt:{sid}":
                continue
            if int(dep.get("path_group") or 1) != int(no):
                continue
            if tx.delete("dependencies", dep.get("dep_id"),
                         note="record_statement:fill_vacant_path:drop") is not None:
                dropped += 1
        deps_written = self._write_dep_steps(tx, steps, stmt_id=sid,
                                             body=body_for_deps)
        tx.upsert("statements", new_row, note="record_statement:fill_vacant_path")
        out.update(
            checked=True, created=False, duplicate=False, merged=True,
            merged_into=str(sid), stmt_id=str(sid), proof_no=int(no),
            proof_no_source="path_group", path_group=int(no),
            path_group_reading={
                "checked": True, "path_group": int(no), "existing": False,
                "vacant_filled": True, "statement_id": str(sid),
                "manuscript": rel, "body_sha": _VR.text_sha(text),
                "count": len(vacant), "paths": [], "problems": [],
                "vacant_paths": sorted(vacant), "vacant_reading": dict(vac),
                "why": (f"第 {no} 条路径处于「难以自证」状态 ⇒ 读成空号："
                        "这一份落在同一个路径号上（整条替换）")},
            tables=["statements", "dependencies"],
            replaced=[int(no)], deps_written=int(deps_written),
            deps_dropped=int(dropped), path_groups=len(groups or []),
            vacant_paths=sorted(vacant),
            reason=(f"第 {no} 条路径原来是「难以自证」的引文占位 ⇒ 那一号读成空号，"
                    "一份带真 V 签的新稿整条替换了它：证明稿（`manuscripts` / "
                    "`manuscript_id`）、依赖面（这一条路径的旧行全部换掉）、"
                    "V 签（逐份表 / sha 表 / `reviewed` / `reviewed_source` 由认签口"
                    "从占位改真签）、引文状态，优化栏复位成未优化"
                    "（`optimized_by_proof=false`、旧的 `hard_to_prove` 记录已抹掉）"))
        return out

    def _fill_vacant_path_if_any(self, tx: Any, *, sid: str, proof_text: Any,
                                 groups: list[list[dict[str, Any]]],
                                 out: dict[str, Any], manuscript: str = "",
                                 group: int = 0) -> bool:
        """空号替换的接线：这一笔该不该整条替换，替换了就补齐回执那几格。

        三个写入口（逐份登记那一支、并进在册命题那一支、收方读稿登记那一支）共用这
        一处接线：三处各写一遍"读行 → 换不换 → 补哪几格"，迟早有一处漏补（而漏补
        只表现为回执少一个键，没有任何判据会响）。返回 `True` = 这一笔已经替换并
        写好，调用方直接返回 `out`；`False` = 这一行没有空号（照旧走原路）。
        """
        row = SL.by_id(rows=tx.rows("statements"), stmt_id=str(sid))["row"]
        landed = self._fill_vacant_path_in_tx(
            tx, row=dict(row or {}), sid=str(sid), proof_text=proof_text,
            groups=groups, out=out, manuscript=manuscript, group=group)
        if landed is None:
            return False
        for key, value in (("duplicates", []), ("deps_dangling", []),
                           ("deps_unmappable", []),
                           ("path_groups", len(groups or [])),
                           ("tables", ["statements", "dependencies"])):
            out.setdefault(key, value)
        return True

    def _abandon_reason_gate(self, row: Mapping[str, Any], wanted: Mapping[str, Any],
                             given: Mapping[str, Any]) -> dict[str, Any]:
        """放弃命题那一步的换号理由闸（判据本体在 `statementabandon`）。

        返回 `{"refused","reason","form","quote_reason"}`：
        - 不归这道闸管（目标状态不是 abandoned / 明确非命题的 kind / 幂等重放且没交
          新理由）⇒ 空字典（一个字节都不干预）；
        - 受控拒 ⇒ `refused` + `reason`（调用方必须整笔不写）；
        - 过关 ⇒ `quote_reason` 是要落盘的那一条标记（`abandoned@<ISO>@<JSON>`），
          `form` 是判据的逐格读数。

        ## 判档读的是盘上原 kind
        读 `wanted.get("kind", row.get("kind"))` 会让同一笔 patch 里把
        `kind` 改成 `concept` 再写 `status=abandoned`，闸就按"想要的 kind"跳过。
        现在：
        1. 同一笔里改 `kind` + 把 `status` 改成 `abandoned` ⇒ 受控拒
           `abandon_kind_change_in_same_patch`（改类与放弃是两件事，拆开交）；
        2. 判档一律读盘上那一行；若盘上现在是 `concept` / `definition` 而
           `_statement_amend_history` 记着它曾经是命题（先改 kind、再放弃的
           两步走），仍按命题处理 —— 否则一行改成 concept 再一行放弃就绕过去了。

        ## 三档
        1. 明确非命题的两档（`concept` / `definition`）⇒ 不受这道闸管（概念没有
           "条件 ⇒ 结论"，谈不上"命题本身有数学错误"或"证明遇到的困难"）；
           其余一切 kind（含词表外的 `example` / `remark` / 空串）一律按命题处理
           （"认不出的 kind 不拦"就是一条一行 patch 的绕行）。
        2. 命题 ⇒ 必须给 `abandon_kind` + `abandon_basis`，判据
           `statementabandon.check_abandon_reason`（math_error 要 `defect_ref`
           指向这一条且审的是现行正文、理由要点名 `defect_step`；difficulty 要
           `difficulty` + 非空的 `salvaged`，每条在册 / active / 引理类 / 不许自指 /
           须在这笔放弃之前就在册，最后过 `judge_abandon_difficulty` 的语义判定）。
        3. 这一行早就是 `abandoned` 而这一次没交新理由、也没改 `quote_reason`
           ⇒ 幂等重放，不拦（历史行必须还能被重放）；理由要变 ⇒ 与第一次同一道闸
           （已 abandoned 不是免检通行证）。

        ## E 侧那两档
        `counterexample`（发现反例）/ `space_too_large`（枚举空间过于宏大）由同一道闸判：
        前者要 `experiment_id` 指一条真的证否实验、后者要一份结构化的 `space` 读数。
        这两格由调用方随 `status=abandoned` 一起交（走 `patch` 或完整的结构化
        `quote_reason` 标记），本函数只把它们原样递给判据 —— 不在这里写第二套判据。

        ## 为什么落盘的是 JSON 而不是自由文本
        读侧要按 `abandon_kind` 分组、要判"是否带证据"（`closing` 的换号读数），
        自由文本做不到。人类可读的那一段是 `abandon_basis` 本身，它没有被压缩。
        """
        from . import statementabandon as _SA

        target = str(wanted.get("status", row.get("status")) or "")
        if target != "abandoned":
            return {}
        # ---- 1) 放弃的同一笔里改 kind ⇒ 受控拒
        if "kind" in wanted and str(wanted.get("kind") or "") != str(row.get("kind") or ""):
            return {
                "refused": "abandon_kind_change_in_same_patch",
                "reason": ("放弃命题的那一笔不许同时改 kind（收到 "
                           f"{row.get('kind')!r} → {wanted.get('kind')!r}）：判档读的是"
                           "盘上原 kind，换个 kind 就换一把尺。要改类请单独交一笔，"
                           "再按新的 kind 走放弃"),
                "form": {}}

        def _kind_on_disk(current: Mapping[str, Any]) -> str:
            """盘上原 kind；当前是 concept/definition 而历史说它曾是命题 ⇒ 取那次原值。"""
            kind = str(current.get("kind") or "").strip().lower()
            if not _SA.is_abandon_exempt(kind):
                return kind
            for entry in (current.get("_statement_amend_history") or []):
                if not isinstance(entry, Mapping):
                    continue
                changes = entry.get("changes")
                cell = changes.get("kind") if isinstance(changes, Mapping) else None
                if not isinstance(cell, Mapping):
                    continue
                old = str(cell.get("from") or "").strip().lower()
                new = str(cell.get("to") or "").strip().lower()
                if _SA.is_abandon_exempt(new) and old and not _SA.is_abandon_exempt(old):
                    return old
            return kind

        kind_now = _kind_on_disk(row)
        if _SA.is_abandon_exempt(kind_now):
            return {}
        already = str(row.get("status") or "") == "abandoned"
        if not given:
            # 幂等重放：同一个标记原样重交 ⇒ 一个字节都不干预；
            # 要换一段理由（不管是自由文本还是完整结构化标记）⇒ 往下走闸。
            if already and "quote_reason" not in wanted:
                return {}
            if already and str(wanted.get("quote_reason") or "") == str(row.get("quote_reason") or ""):
                return {}
            parsed = (_SA.parse_abandon_reason(wanted.get("quote_reason"))
                      if "quote_reason" in wanted else {})
            if parsed.get("structured") and parsed.get("complete"):
                given = {"abandon_kind": parsed.get("abandon_kind"),
                         "abandon_basis": parsed.get("abandon_basis"),
                         "defect_ref": parsed.get("defect_ref") or "",
                         "difficulty": parsed.get("difficulty") or "",
                         "salvaged": parsed.get("salvaged") or (),
                         "experiment_id": parsed.get("experiment_id") or "",
                         "space": parsed.get("space") or {}}
        at = S.now_iso()
        if already:
            was = _SA.parse_abandon(row.get("quote_reason"))
            if was.get("checked") and str(was.get("at") or ""):
                at = str(was.get("at"))     # 补理由不改"几时放下的"那一刻
        form = _SA.check_abandon_reason(
            self.store,
            kind=given.get("abandon_kind"), basis=given.get("abandon_basis"),
            defect_ref=given.get("defect_ref", ""), difficulty=given.get("difficulty", ""),
            salvaged=given.get("salvaged") or (),
            experiment_id=given.get("experiment_id", ""),
            space=given.get("space") or None,
            statement_id=str(row.get("stmt_id") or ""),
            at=at, statement=row,
            difficulty_judge=self.judge_abandon_difficulty,
            judgment_required=True)
        if not form.get("checked"):
            return {"refused": str(form.get("refused") or "abandon_reason_missing"),
                    "reason": str(form.get("why") or "换号理由不齐 ⇒ 整笔不写"),
                    "form": form}
        marker = _SA.abandon_marker(
            at=at,
            reason=_SA.structured_reason(
                kind=str(form["abandon_kind"]), basis=str(form["abandon_basis"]),
                defect_ref=str(form.get("defect_ref") or ""),
                difficulty=str(form.get("difficulty") or ""),
                salvaged=form.get("salvaged") or (),
                experiment_id=str(form.get("experiment_id") or ""),
                space=form.get("space") or None))
        return {"quote_reason": marker, "form": form}

    def _retire_statement(self, *, sid: str, wanted: Mapping[str, Any],
                          given: Mapping[str, Any], abandon_given: Mapping[str, Any],
                          role: str, task_id: str) -> dict[str, Any]:
        """`refuted` / `hard_to_prove` 两个新终态的转调口（唯一实现不在本文件）。

        ## 为什么另立一格而不是塞进 `amend_statement_meta` 那笔事务
        两件事都要动 `bits`（作废载荷 / 优化栏口袋），而 `bits` 是派生面：
        `STATEMENT_META_PATCH_KEYS` 的白名单里没有它，也不该有（否则通用写口就能
        绕开 `evidencebits` 的推导）。所以这一格只做三件本层该做的事：判"一次只交
        一件"、判 role/task 那一侧的形状、把读数翻成本层既有的返回形状；写盘由
        `statementrefute` 在它自己的事务里做完（受控拒 = 一个字节都没写）。

        ## 三条形状拒（都在转调之前）
        - 同时给 `status="refuted"` 与 `hard_to_prove` ⇒ 拒：两个终态不能一笔办；
        - `status="refuted"` 又给 `abandon_kind` ⇒ 拒：证据格本身就是档
          （`defect_ref` / `construction` ⇒ math_error，`experiment_id` ⇒ counterexample），
          再给一个档名会让"凭哪一条"有两个说法；
        - `hard_to_prove` 的基理由空 ⇒ 拒（由 `mark_hard_to_prove` 给码，这里不另判）。
        """
        from . import statementrefute as _SR

        wants_refuted = str(wanted.get("status") or "") == "refuted"
        wants_hard = "hard_to_prove" in given
        if wants_refuted and wants_hard:
            return {"checked": False, "amended": False, "refused": "retire_two_in_one_patch",
                    "reason": ("这一笔同时要 `status=refuted` 与「难以自证」⇒ 两件事拆开交："
                               "refuted 是终态（命题错了），难以自证不是终态（命题留着、"
                               "只是这一份优化不出来）"),
                    "stmt_id": sid, "changes": [], "row": {}, "form": {}}
        if wants_refuted and "abandon_kind" in abandon_given:
            return {"checked": False, "amended": False, "refused": "refute_kind_not_needed",
                    "reason": ("标记为错误不用另给 `abandon_kind`：证据格本身就是档 —— "
                               "`defect_ref` / `construction` 是「数学错误」，"
                               "`experiment_id` 是「发现反例」。一次只认一种说法"),
                    "stmt_id": sid, "changes": [], "row": {}, "form": {}}
        actor = f"secretary-{self.role}"
        if wants_hard:
            got = _SR.mark_hard_to_prove(
                self.store, statement_id=sid, basis=given.get("hard_to_prove"),
                proof_no=given.get("proof_no") or 1, actor=actor)
        else:
            got = _SR.refute_statement(
                self.store, statement_id=sid,
                reason=abandon_given.get("abandon_basis"),
                experiment_id=abandon_given.get("experiment_id", ""),
                construction=given.get("construction", ""),
                defect_ref=abandon_given.get("defect_ref", ""),
                counterexample_valid=given.get("counterexample_valid"),
                actor=actor)
        out = dict(got)
        out.setdefault("amended", False)
        out["task_id"] = str(task_id or "")
        # 本层既有的返回键：`refused` + `reason`（`refute_statement` 另有一个 `why`，
        # 那是它自己的逐条读数，两个都留着，别把其中一个抹掉）。
        out["reason"] = str(got.get("reason") or got.get("why") or "")
        return out

    def amend_statement_meta(self, stmt_id: str, patch: Mapping[str, Any], *,
                             role: str = "B", task_id: str = "") -> dict[str, Any]:
        """就地改一条在册命题的非正文格（`status` / `kind` / `quote_reason`）。

        ## 为什么需要这一条（真机 82，2026-11-01 · A-1…A-4）

        B 四次用 `table.update(table="statements")` 想改 `kind` / `status` /
        `quote_reason`，四次都被"同一条 statement_full 已在册"拒：兜底把"盘上那一行 +
        patch"整份再交一次登记，而查重判据正是"同一条正文已在册" ⇒ 非正文 patch
        100% 落 duplicate 拒，三格于是没有任何写入口。
        这一格就是那条写口，也是"改哪一格"允许被路由过来的唯一白名单。

        ## 边界（这是权限面，必须写死）
        - 只认 `STATEMENT_META_PATCH_KEYS` 三个键；白名单之外一律受控拒绝
          （`statement_patch_key_not_allowed`），一个字节都不写；
        - `kind` 只认英文词表 `STATEMENT_META_KINDS`（中文 kind 是
          `bad_statement_kind`，不是"重复读数"）；
        - `status` 只认 `schema.STATEMENT_STATUSES`；
        - 正文 / 证据面不在这一格：要改正文请重交一条登记（旧正文进 `proof_history`）。

        ## 走的是秘书的校验与事务
        整行重建后过 `schema.Statement.validate()`（与登记那一支同一套字段校验），
        在 `store.tx("statements", ...)` 里写，并留 `_statement_amend_history`
        （谁、何时、从什么改成什么；只留最近 20 条，与 `_proposition_matches` 同一条
        有界读数纪律）。三态：改成了 / 已经是这些值（幂等，不写）/ 受控拒绝。

        ## 返回
        | 结局 | 返回 |
        |---|---|
        | 改成了 | `checked=True` + `amended=True` + `changes` + `row` |
        | 没有可改的 | `checked=True` + `amended=False`（一个字节都没写） |
        | 受控拒绝 | `checked=False` + `refused=<码>` + `reason` |
        """
        out: dict[str, Any] = {"checked": False, "amended": False,
                               "stmt_id": str(stmt_id or ""), "changes": [],
                               "before": {}, "row": {}, "tables": [],
                               "refused": "", "reason": "",
                               #: 换号理由那几格的判据读数（只有放弃命题那一笔才非空）。
                               "form": {}}
        if self.store is None:
            out.update(refused="secretary_unavailable",
                       reason="这一名秘书没有 store ⇒ 改不了（命题的写侧归秘书）")
            return out
        if str(role) not in STATEMENT_WRITER_ROLES:
            out.update(refused="not_statement_writer",
                       reason=(f"命题的写入侧是 B 的活（收到 role={role!r}）—— "
                               f"只有 {STATEMENT_WRITER_ROLES} 能经这一格改命题"))
            return out
        sid = str(stmt_id or "").strip()
        wanted = {str(k): v for k, v in dict(patch or {}).items()
                  if not str(k).startswith("_")}
        if not wanted:
            out.update(refused="empty_statement_patch",
                       reason=("patch 是空的 ⇒ 没有要改的格。这一条只改 "
                               f"{list(STATEMENT_META_PATCH_KEYS)} 之一或多个"))
            return out
        extra_keys = sorted(k for k in wanted if k not in STATEMENT_META_PATCH_KEYS
                            and k not in STATEMENT_ABANDON_PATCH_KEYS
                            and k not in STATEMENT_RETIRE_PATCH_KEYS)
        if extra_keys:
            out.update(refused="statement_patch_key_not_allowed", reason=(
                f"这一条只允许就地改 {list(STATEMENT_META_PATCH_KEYS)}"
                f"（放弃命题时另带 {list(STATEMENT_ABANDON_PATCH_KEYS)}；"
                f"标记为错误 / 难以自证时另带 {list(STATEMENT_RETIRE_PATCH_KEYS)}），"
                f"收到 {extra_keys}。"
                "改正文请把新正文写进 `statement_full` / `proof_text` 再交一次 "
                "`own.register_statement`（同一条命题会就地覆盖，旧正文进 `proof_history`）；"
                "其余格没有就地写口 —— 整笔不写，盘上一个字节都没变。"))
            return out
        #: 另外两个终态的格先摘出来（与放弃那几格同一条纪律：不是可写列）。
        retire_given = {k: wanted.pop(k) for k in list(wanted)
                        if k in STATEMENT_RETIRE_PATCH_KEYS}
        #: 换号理由那几格先摘出来：它们不是可写的列（见 `STATEMENT_ABANDON_PATCH_KEYS`），
        #: 只用来拼 `quote_reason` 那一条标记。
        abandon_given = {k: wanted.pop(k) for k in list(wanted)
                         if k in STATEMENT_ABANDON_PATCH_KEYS}
        if "status" in wanted:
            status = str(wanted["status"] or "").strip()
            if status not in S.STATEMENT_STATUSES:
                out.update(refused="bad_statement_status", reason=(
                    f"status 必须是 {S.STATEMENT_STATUSES} 之一，收到 {wanted['status']!r}"
                    "（它是命题的可信状态，不是自由文本）；建议：按这份词表里的取值改后重交"))
                return out
            wanted["status"] = status
        if "kind" in wanted:
            kind = str(wanted["kind"] or "").strip()
            if kind not in STATEMENT_META_KINDS:
                out.update(refused="bad_statement_kind", reason=(
                    f"kind 必须是英文词表 {list(STATEMENT_META_KINDS)} 之一，收到 {kind!r} —— "
                    "中文 kind（定理 / 引理）不是取值；这一格由证据派生，改它也请走证据。"
                    "建议：按英文词表取值重交；要让 kind 跟着证据走，就重交 "
                    "`own.register_statement`（`evidencebits.kind_following_grade` 现算）"))
                return out
            wanted["kind"] = kind
        if "quote_reason" in wanted:
            text = str(wanted["quote_reason"] or "")
            if not text.strip():
                out.update(refused="bad_quote_reason", reason=(
                    "quote_reason 不能改成空串 —— 三态纪律：没通过要说清为什么、"
                    "还没查也要说出来，不许留白。建议：写清「为什么没通过」或"
                    "「为什么还没查」后重交（空串不是一种理由）"))
                return out
            wanted["quote_reason"] = text
        # ---- 2026-11-13（业主裁定）：两个新终态转调唯一实现 ------------------------
        #
        # 为什么必须在这里分出去、不能落进下面那一笔：`_abandon_reason_gate` 只认
        # `status="abandoned"`（其它目标直接返回空字典）⇒ 一条 `status="refuted"` 的
        # patch 会绕过全部证据判据、把一行直接推成"被证否"而拿不出任何凭据。
        if retire_given or str(wanted.get("status") or "") == "refuted":
            return self._retire_statement(sid=sid, wanted=wanted, given=retire_given,
                                          abandon_given=abandon_given,
                                          role=role, task_id=task_id)
        try:
            with self.store.tx("statements", actor=f"secretary-{self.role}",
                               note="secretary:amend_statement_meta") as tx:
                # 按号定位走查口（口径一）；事务快照传 `rows=`，锁内读失败仍照旧抛出。
                by_id = SL.by_id(rows=tx.rows("statements"), stmt_id=sid)
                row = by_id["row"] if by_id["found"] else None
                if row is None:
                    out.update(refused="not_found",
                               reason=f"statements 里没有主键 {sid} ⇒ 没有可改的行")
                    return out
                # ---- 2026-11-07（业主裁定）：放弃/换号必须给清结构化理由 ----------
                #
                # 位置在"算 changed 之前、`tx.upsert` 之前"：受控拒要求一个字节都不写，
                # 而这一格一旦被判拒，`wanted` 里的 `status` 也不许落盘。
                gate = self._abandon_reason_gate(row, wanted, abandon_given)
                if gate.get("refused"):
                    out.update(refused=str(gate["refused"]),
                               reason=str(gate.get("reason") or ""),
                               form=dict(gate.get("form") or {}))
                    return out
                if gate.get("quote_reason"):
                    wanted["quote_reason"] = str(gate["quote_reason"])
                    out["form"] = dict(gate.get("form") or {})
                before = {k: row.get(k) for k in wanted}
                changed = {k: v for k, v in wanted.items() if row.get(k) != v}
                out["before"] = before
                if not changed:
                    out.update(checked=True, amended=False, row=row,
                               reason=("这一笔要改的格已经是这些值 ⇒ 一个字节都没写"
                                       "（幂等：不是失败，也不是改成了）"))
                    return out
                merged = dict(row)
                merged.update(changed)
                history = [dict(h) for h in (row.get("_statement_amend_history") or [])
                           if isinstance(h, Mapping)]
                history.append({
                    "at": S.now_iso(), "by": f"secretary-{self.role}",
                    "task_id": str(task_id or ""),
                    "changes": {k: {"from": before.get(k), "to": v}
                                for k, v in changed.items()}})
                merged["_statement_amend_history"] = history[-20:]
                try:
                    obj = S.row_from_dict("statements", dict(merged))
                    obj.validate()
                    canonical = obj.to_dict()
                except (TypeError, ValueError) as exc:
                    out.update(refused="validation", reason=(
                        f"改完之后这一行不是合法的命题行（{type(exc).__name__}: {exc}）"
                        " ⇒ 整笔不写（不在'改一格'里顺手写坏一行）"))
                    return out
                extra = {k: v for k, v in merged.items() if k not in canonical}
                row_out = {**extra, **canonical}
                tx.upsert("statements", row_out, note="secretary:amend_statement_meta")
                out.update(checked=True, amended=True, stmt_id=sid,
                           changes=sorted(changed), row=row_out,
                           tables=["statements"],
                           reason=("就地改了 " + "、".join(sorted(changed))
                                   + "（非正文格；正文与证据面一个字没动）"))
                return out
        except Exception as exc:  # noqa: BLE001 —— 落盘失败必须回三态，不许半笔
            out.update(checked=False, refused="write_failed",
                       reason=(f"改非正文格没成（{type(exc).__name__}: {exc}）"
                               " ⇒ 这一笔按'没写成'读"))
            return out

    def land_statement(self, stmt_id: str, transition: Any, *, op: str,
                       note: str = "", role: str = "B") -> dict[str, Any]:
        """在秘书的事务里落一次 `statements`：调用方只给"行变换"，写盘与"改了哪几格"的判据在这里。

        ## 为什么需要这一条（业主 2026-11-08，逐字）
        「我应该定过B实际只有台账的只读权限，B的任何所谓写台账的路实际上都由B秘书洗过」
        ⇒ B 本体对 `statements` 只读：它的两支写侧（`_attach_proofs` / `_update_numeric_evidence`）
        此前自己开 `store.tx("statements")` 落行，秘书那一层一个字都没过目。收口之后
        B 只说"这一笔要改成什么"，四件事归这一层：开事务、读现行行、判"改了哪几格"、写盘。

        ## 参数
        - `transition(row_or_None) -> {"write": bool, "row": {...}, "result": <调用方读数>}`：
          调用方用它拿到的事务内那一行算"这一笔要改成什么"（返回 `write=False` ⇒
          一个字都不写；返回 `refused` + `reason` 也等价于不写）。传进来的 `row` 是
          `tx.find` 读的，所以"读—判—写"仍在同一把锁里、与收口前逐字同序。
        - `op`：`STATEMENT_LAND_OPS` 的键 —— 决定这一笔允许改哪几格。

        ## 洗的是什么（不是空转的漏斗）
        落盘前逐条核：`stmt_id` 那一行在不在、`transition` 要写的行是不是把允许之外的格
        改了（越界 ⇒ `statement_patch_key_not_allowed`，一个字节都不写）。正文真身、出处面、
        创建留痕都不在任何 `op` 的白名单里 ⇒ 这一条路改不动它们。

        ## 三态（不折平）
        | 结局 | 返回 |
        |---|---|
        | 写成了 | `checked=True` + `written=True` + `row` + `changed` + `result` |
        | 调用方判定这一笔无内容 / 它自己拒了 | `checked=True` + `written=False` + `result` |
        | 秘书这一层拒（越界 / 行不在 / 没有 store / 不是 B 的活） | `checked=False` + `refused` + `reason` |

        ## 异常不吞
        事务里的异常照旧往上抛：两个调用方各有自己的异常处置（`_update_numeric_evidence`
        折 `numeric_evidence_write_failed`；`_attach_proofs` 一直是往上抛）。在这里吞掉会把
        它们的拒码换成一个泛码 —— 那是把"哪一步没写成"抹平。
        """
        out: dict[str, Any] = {"checked": False, "written": False,
                               "stmt_id": str(stmt_id or ""), "op": str(op or ""),
                               "refused": "", "reason": "", "changed": [],
                               "row": {}, "result": {}, "tables": []}
        if self.store is None:
            out.update(refused="secretary_unavailable",
                       reason="这一名秘书没有 store ⇒ 命题行写不了（写入侧归秘书）")
            return out
        if str(role) not in STATEMENT_WRITER_ROLES:
            out.update(refused="not_statement_writer",
                       reason=(f"命题的写入侧是 B 的活（收到 role={role!r}）—— "
                               f"只有 {STATEMENT_WRITER_ROLES} 能经这一格落命题行"))
            return out
        allowed = STATEMENT_LAND_OPS.get(str(op or ""))
        if allowed is None:
            out.update(refused="unknown_statement_land_op",
                       reason=(f"`op={op!r}` 不在 {sorted(STATEMENT_LAND_OPS)} 里 ⇒ "
                               "不知道这一笔允许改哪几格，整笔不写"))
            return out
        sid = str(stmt_id or "").strip()
        with self.store.tx("statements", actor=f"secretary-{self.role}",
                           note=note or f"secretary:land_statement:{op}") as tx:
            # 按号定位走查口（口径一）；事务快照传 `rows=`，锁内读失败仍照旧抛出。
            by_id = SL.by_id(rows=tx.rows("statements"), stmt_id=sid)
            found = (by_id["row"] if by_id["found"] else None)
            got = dict(transition(dict(found) if found is not None else None) or {})
            out["result"] = dict(got.get("result") or {})
            if got.get("refused"):
                out.update(checked=False, written=False,
                           refused=str(got.get("refused") or "statement_land_refused"),
                           reason=str(got.get("reason") or ""))
                return out
            if not got.get("write"):
                out.update(checked=True, written=False,
                           reason="这一笔没有要写的内容（调用方判定）⇒ 一个字节都没写")
                return out
            if found is None:
                out.update(checked=False, refused="statement_missing",
                           reason=(f"`statements` 里没有 {sid} ⇒ 这一笔没有落点"
                                   "（行没落成，改也无处可改）：一个字节都没写"))
                return out
            base = dict(found)
            row = dict(got.get("row") or {})
            changed = sorted(k for k in (set(base) | set(row))
                             if base.get(k) != row.get(k))
            bad = [k for k in changed if k not in allowed]
            if bad:
                out.update(checked=False, refused="statement_patch_key_not_allowed",
                           reason=(f"`{op}` 这一笔只许改 {list(allowed)}，而它改了 {bad} ⇒ "
                                   "整笔不写（正文真身 / 出处面 / 创建留痕都不在任何一条"
                                   "落盘白名单里）"))
                return out
            if not changed:
                out.update(checked=True, written=False,
                           reason=("这一笔要写的就是盘上这些值 ⇒ 一个字节都没写"
                                   "（幂等：不是失败，也不是写成了）"))
                return out
            tx.upsert("statements", row,
                      note=note or f"secretary:land_statement:{op}")
            out.update(checked=True, written=True, found=True, row=dict(row),
                       changed=changed, tables=["statements"],
                       reason=("落了 " + "、".join(changed) + f"（`{op}`；由秘书写盘）"))
            return out

    def _with_relabel_reading(self, landed: Mapping[str, Any] | None,
                              *, kind: str = "") -> dict[str, Any]:
        """登记成功之后，把"这一笔是不是换号（同一 label 再登记）"的读数带上。

        业主 2026-11-07 的裁决只拦放弃那一侧（`Statement` 的
        `status=abandoned` 写口），登记这一侧不拦：历史工作区里已经有一批没有
        结构化理由的 `abandoned` 行，拦它们只会把 B 卡死。所以这一格只做两件事：

        - 原件理由齐 ⇒ 返回读数 `supersedes`（原 `stmt_id` + `abandon_kind` +
          `abandon_basis` 摘要 + 证据是否在）；
        - 原件理由不齐（历史行）⇒ 返回 `superseded_without_reason`（原 `stmt_id` 列表），
          不拒 —— 让审计一眼看到"这一条换号是在没有给出理由的情况下发生的"。

        判据本体是 `statementabandon.relabel_events`（`closing` 的换号读数读同一份）。
        """
        out = dict(landed or {})
        if not out.get("created") or not str(out.get("stmt_id") or ""):
            return out            # 不是新建（已在册 / 升档 / 合并）⇒ 没有"换号"这回事
        from . import statementabandon as _SA

        sid = str(out.get("stmt_id") or "")
        label = str((out.get("row") or {}).get("label") or "").strip()
        if not label:
            return out
        try:
            events = _SA.relabel_events(self.store.rows("statements"))
        except Exception as exc:  # noqa: BLE001 —— 读数读不出来不许带走已经落盘的登记
            out["relabel"] = {"checked": False,
                              "reason": f"{type(exc).__name__}: {exc}"}
            return out
        priors = [one for one in events.get(label, []) if one.get("stmt_id") != sid]
        out["relabel"] = {"checked": True, "label": label,
                          "priors": len(priors),
                          "supersedes": [], "superseded_without_reason": []}
        if not priors:
            return out
        for one in priors:
            if one.get("complete"):
                out["relabel"]["supersedes"].append({
                    "stmt_id": one["stmt_id"], "at": one.get("at", ""),
                    "abandon_kind": one.get("abandon_kind", ""),
                    "basis": one.get("basis", ""),
                    "has_evidence": bool(one.get("has_evidence")),
                })
            else:
                out["relabel"]["superseded_without_reason"].append({
                    "stmt_id": one["stmt_id"], "at": one.get("at", ""),
                    "why": "原件没有结构化的换号理由（历史行）⇒ 只报不拦",
                })
        # 顶层也放一份：模型读的是返回值，`relabel` 里那一层太深时它会漏看。
        if out["relabel"]["supersedes"]:
            out["supersedes"] = list(out["relabel"]["supersedes"])
        if out["relabel"]["superseded_without_reason"]:
            out["superseded_without_reason"] = list(
                out["relabel"]["superseded_without_reason"])
        return out

    def record_statement(self, payload: Mapping[str, Any], *, role: str = "B",
                         force_new: bool = False,
                         candidate_id: str = "",
                         adjudication: Mapping[str, Any] | None = None
                         ) -> dict[str, Any]:
        """B 交内容 ⇒ 秘书落盘（洗格式 / 拿编号 / 查重 / 改表四件一次做完）。

        这是一笔事务（`statements` + `dependencies`），B 那一侧只交内容、不调工具。

        ## 返回（要能分辨"没写"的几种原因）

        | 结局 | 返回 |
        |---|---|
        | 写成了 | `{"checked": True, "created": True, "stmt_id": …, "deps_written": n, "path_groups": k}` |
        | 同内容已有一条 | `{"checked": True, "created": False, "duplicate": True, "stmt_id": <既有>}` |
        | 同内容 + 更强证据档（有凭据） | `{"checked": True, "created": False, "upgraded": True, "stmt_id": <既有>, "changes": [...]}` |
        | 受控拒绝（一行都不落） | `{"checked": False, "refused": "<理由码>", "reason": …}` |

        理由码：`secretary_unavailable` / `not_statement_writer` / `wash_failed` /
        `unresolved_dependency`（依赖指着一个不在册的 id）/ `unknown_lit_id` /
        `empty_statement`（缺 `statement_full` —— 只有短版不算数）。
        概念的定义空着不是拒绝：它落成 `pending_definition` + 待补标记。

        ## 同一命题 / 同种证明

        先按 `statement_full` 的规范化值查重（老口径）；没命中时再判"是不是同一条命题"：
        秘书判得成（`adjudicate_proposition`）⇒ 它说了算；没查成 ⇒ fail-closed，
        只认「确定性键相同」这一档等价改写（词面相似度只给候选表排序、不决定并）。
        命中 ⇒ 不新建命题行，而是那条命题的第 N 份证明：证明落 `proofs` 清单
        （canonical 空时落 `proof_text`）、依赖落 `used_by="stmt:#pN"`。
        没有证明正文的重复登记也判归属：判得成同一条 ⇒ 回 `duplicate=True` + `no_proof=True`
        （重复读数，不是第 N 份证明）；判不成 ⇒ 照常新建。
        同一命题下的新证明与在册某一份同种（`proof_same_kind` 阈值）⇒ 不新增证明号、
        受控拒绝并点名第几份；调用方给 `merge=True` 并交合并稿时，合并稿成为那一份的
        新版本、旧正文进 `proof_history`，且要求 V 重签（`resign_required=True`）。

        ## 概念行：同一个概念不许落成第二行

        `kind="concept"` 没有"条件 ⇒ 结论"，上面的判据在它上面等于失效（两条把同一个术语
        定义了两遍会被判成"不同"）。所以概念行另有一条确定性判据：定义项相同
        （标签规范化后相同，或正文里「概念（X）」/「定义（X）」抽出的术语相同）⇒
        不新建、返回既有 `stmt_id`（`duplicate=True` + `matched_by`）。这一档不发模型调用。

        ## 定理名里的内部工作名不许当定理名

        `F 攻坚 000000 子目标 S2` 这类派活台账里的工作名命中
        `LABEL_WORKING_NAME_RULES` 就洗掉，洗成什么由 `wash_working_name` 的三级兜底决定
        （剩下一截 / 正文第一句 / 待命名），读数在 `label_washed` 里逐条给
        「原标签 → 洗过的名字 + 触发了哪一类」。

        ## `candidate_id`：把稿名/稿头的号当候选号

        B 在"新建"这一档把稿名/稿头算出来的号当候选交进来：可用就用它发号
        （并 `raise_counter_to` 把计数器抬到它之后）；已被占 ⇒ 受控拒绝 `stmt_id_taken`，
        不另发一个号 —— 静默另发会让稿与命题的号错开。
        """
        out: dict[str, Any] = {"checked": False, "created": False, "duplicate": False,
                               "upgraded": False, "merged": False, "merged_into": "",
                               "merged_same_kind": False, "proof_no": 0,
                               "matched_by": "", "similarity": 0.0, "same_kind": [],
                               "proposition_state": "", "proposition_reason": "",
                               #: 命题同一性判定的三态读数（见 `_adjudication_reading`）。
                               #: 空字典 = 这一笔没走到那一格（例如 `force_new` 早退）。
                               "adjudication": {},
                               #: "判了没有"的一句话（见 `_with_adjudication_visibility`）：
                               #: `checked` / `attempted` / `reason` / `seam_source`。
                               #: 空字典 = 这一笔没走到那一格（同上；拒绝那几笔在
                               #: `reason` 里已经说清了为什么不写）。
                               "proposition_adjudication": {},
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
                # 定义还没抽到的概念行照落 ——
                # 落成 `pending_definition`（不是依据）+ 待补标记（谁去补写在 reason 里）。
                # 不许折成 `active` + 空定义（`Statement.validate` 当场拒），
                # 也不许"干脆不落"（那样这个概念并表之后查不到）。
                return self._record_pending_concept(body, out=out)
            out.update(refused="empty_statement",
                       reason=("statement_full 是空的 ⇒ 不写（只有短版不算数：省掉假设的"
                               "命题会被下游当成无条件成立）"))
            return out
        # ---- 语义那一档的证据缺了就不写，并给具名理由。
        #
        # 判据本体在 `_semantic_quote_evidence_refusal`（拆出来只为让本方法留在"一屏半"之内）。
        _semantic_refusal = _semantic_quote_evidence_refusal(body)
        if _semantic_refusal:
            out.update(**_semantic_refusal)
            return out
        # ---- 出处档的词表：与 B 的 `bad_origin` 同一个码（路由过来的非法载荷也要
        # 在"正文闸"之前被按这一格拒：否则拒信会说"缺手稿签"，而真正错的是 origin）。
        _origin_now = str(body.get("origin") or "")
        if _origin_now not in S.STATEMENT_ORIGINS:
            out.update(checked=False, created=False, duplicate=False, upgraded=False,
                       merged=False, refused="bad_origin",
                       reason=(f"origin 必须是 {S.STATEMENT_ORIGINS} 之一，"
                               f"收到 {_origin_now!r}"))
            return out
        # ---- 正文必须由手稿承载：`proof_text` 的唯一收口闸 ----
        #
        # 位置在"判同一性"之前：这一笔如果连正文都不该写，就不该先花一次模型调用去
        # 判它跟谁同一条；而且判词会诱导调用方以为"只差一个合并"。
        # 闸本身是纯读（`proof_text_manuscript_sign_gate`）：它只回答"这一份正文有没有
        # 一份审的是手稿、且盖住这份正文的签"，不写盘、不改正文。
        if body.get("merge") is not True and kind != "concept":
            _intake = proof_text_manuscript_sign_gate(
                self.store, proof_text=body.get("proof_text"),
                statement_full=full, proof_no=body.get("proof_no"),
                origin=body.get("origin"), source_lit_id=body.get("source_lit_id"),
                defer_without_sign=_bits_bear_evidence(body.get("bits")))
            out["proof_text_gate"] = dict(_intake)
            if _intake.get("refused"):
                out.update(checked=False, created=False, duplicate=False, upgraded=False,
                           merged=False, refused=str(_intake.get("refused") or ""),
                           reason=str(_intake.get("reason") or ""))
                return out
        # 合并那一支的 `statement_full` 是"近似写法"（逐字相同会先撞 duplicate 早退），
        # 它要落到哪一条在册行由同一性判定给出 ⇒ 这一闸必须在判定之后、拿到 `same_as`
        # 再判一次（`_merge_into_proposition` 里）。先在这里跳过，免得把一条合法的
        # 合并判成"没有在册行"。
        # ---- 命题同一性：让秘书洗定理名、让秘书判。
        #
        # 位置在"落盘之前、事务之外"：这一步会发一次模型调用（可以慢、可以超时），
        # 把它放进 `store.tx` 就是拿网络等待去占着写锁，而锁里不该有网络等待。
        # 读候选用的是 `self.store.rows`（只读），事务里那一份快照由 `_record_statement_tx`
        # 自己再用 `tx.rows` 核（合并前它必须确认那一条还在、还可并）。
        if adjudication is None:
            adjudication = self.adjudicate_proposition(
                {"statement_full": full, "label": str(body.get("label") or ""),
                 "kind": kind})
        else:
            # 调用方已经把"是不是在册的同一条"查过一圈
            # （`register_statement._resolve_same_statement`：关键词检索 + 秘书认定）。
            # 这里沿用那一趟的结论，不再发第二次模型调用 —— 同一件事两个判据会给出
            # 两个答案，而"两处各判一次"正是这条链要收掉的形态。
            adjudication = dict(adjudication)
            out["adjudication_source"] = "register_statement:same_statement"
        out["adjudication"] = self._adjudication_reading(adjudication)
        #: 没判成必须可见：`adjudication` 是那一趟的逐字读数，而这一格是
        #: "判了没有"的一句话（`checked` / `attempted` / `reason` / `seam_source`）。
        #: 为什么要两格：前者挨着 `verdict` / `basis` 那一组判词，读的人（模型只看工具
        #: 返回的那份 JSON）容易把它读成"判过了、结论是某一档"；这一格单独命名，于是
        #: "这一条判定根本没发生"在返回值里不可能被漏看。
        out["proposition_adjudication"] = dict(
            adjudication.get("proposition_adjudication") or {})
        out["canonical_name"] = str(adjudication.get("canonical_name") or "")
        # ---- 同种证明：在锁外先问一次（锁内不许发模型），结论带进事务 ----------
        _proof_kind = self._proof_kind_for_existing(
            full=full, body=body, adjudication=adjudication)
        if _proof_kind:
            out["proof_kind"] = {
                "checked": bool(_proof_kind.get("checked")),
                "decision": str(_proof_kind.get("decision") or ""),
                "same_path": int(_proof_kind.get("same_path") or 0),
                "material_similarity": float(_proof_kind.get("similarity") or 0.0),
                "reason": str(_proof_kind.get("reason") or ""),
            }
        return self._land_or_refuse(body, full=full, kind=kind,
                                    force_new=bool(force_new), out=out,
                                    adjudication=adjudication,
                                    proof_kind=_proof_kind,
                                    candidate_id=str(candidate_id or ""))


    def _land_or_refuse(self, body: Mapping[str, Any], *, full: str, kind: str,
                        force_new: bool, out: dict[str, Any],
                        adjudication: Mapping[str, Any],
                        candidate_id: str,
                        proof_kind: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """把这一笔交给事务写口；写不成按三态回一条读数（不抛、不半笔）。

        2026-11-08 从 `record_statement` 拆出（只搬移，块内逐字相同）：「交给事务写口」
        与「写不成怎么读」是同一件事的两半，合起来 20 余行；拆开之后 `record_statement`
        回到 200 行以内 —— 体量基线是读数，不许为了它抬（业主口径：拆函数，不抬基线）。
        """
        try:
            landed = self._record_statement_tx(body, full=full, kind=kind,
                                               force_new=bool(force_new), out=out,
                                               adjudication=adjudication,
                                               candidate_id=candidate_id,
                                               proof_kind=proof_kind)
            return self._with_relabel_reading(landed, kind=kind)
        except Exception as exc:  # noqa: BLE001 —— 落盘失败必须回三态，不许半笔
            # ---- 写入期闸的拒收要留住它自己的码（2026-11-05 走查 D2）------------
            #
            # 改前这一格把所有异常折成 `write_failed`，于是"升档这一笔被
            # `proof_review_without_evidence` 拒了"在返回值里只剩一个泛码 —— 调用方
            # （B）既看不出该去补哪一份签，也没法据码分辨"参数不对"与"证据不够"。
            # 判据仍是那个异常自己的码（`verifications.CODE_WRITE`），这里只做翻译。
            code = "write_failed"
            message = f"{type(exc).__name__}: {exc}"
            try:
                from . import verifications as _VR   # 惰性：只在这条异常路上需要
                if str(exc).startswith(_VR.CODE_WRITE):
                    code = _VR.CODE_WRITE
            except Exception:  # noqa: BLE001 —— 翻译失败仍回泛码（不许因此吞掉异常）
                pass
            out.update(checked=False, created=False, upgraded=False, refused=code,
                       reason=f"落盘没成（{message}）⇒ 这一笔按'没写成'读")
            return out

    @staticmethod
    def _adjudication_reading(adj: Mapping[str, Any]) -> dict[str, Any]:
        """命题同一性判定的读数（进返回值与台账；不把内部候选表整份甩出去）。

        两档在这一格里必须一眼能分辨：`checked=False` 是"没判成"（没缝 / 超时 / 坏 JSON /
        same 点不出号 / 词表外结论），`checked=True` + `verdict="different"` 是"查过了、
        确实不是"。折平这两个会让"没人判过"看起来像"判过了、确实不同"。
        """
        got = dict(adj or {})
        return {
            "checked": bool(got.get("checked")),
            "attempted": bool(got.get("attempted")),
            "verdict": str(got.get("verdict") or ""),
            "canonical_name": str(got.get("canonical_name") or ""),
            "same_as": str(got.get("same_as") or ""),
            "route": str(got.get("route") or ""),
            "condition": str(got.get("condition") or ""),
            "conclusion": str(got.get("conclusion") or ""),
            "basis": str(got.get("basis") or ""),
            "reason": str(got.get("reason") or ""),
            "reused": bool(got.get("reused")),
            "cached": bool(got.get("cached")),
            #: 这一条判定用哪条缝（三档见 `seam_for_secretary`）。没有缝时它连着为什么 ——
            #: "没判成"的原因不能只活在秘书的台账里：调用方（B 的工具返回、直写路由的
            #: detail）拿到的就是这一份读数。
            "seam_source": str(got.get("seam_source") or ""),
            "candidates": [(str(c.get("stmt_id") or "") if isinstance(c, Mapping)
                            else str(c))
                           for c in (got.get("candidates") or [])],
            #: 检索读数（"它确实自己查过"必须看得见，2026-11-08）：
            #: 关键词 / 命中几条 / 实际交给模型看的是哪几条 / 判定那一趟发没发。
            "keywords": [str(x) for x in (got.get("keywords") or ())],
            "hits_total": int(got.get("hits_total") or 0),
            "hits_named": [dict(x) if isinstance(x, Mapping) else {"stmt_id": str(x)}
                           for x in (got.get("hits_named") or ())],
            "judged": bool(got.get("judged")),
            "why": str(got.get("why") or ""),
            "cost": dict(got.get("cost") or {}),
            #: 分页读数（2026-11-08 缺陷 ②）：看了几页 / 几个候选 / 是否页尽。
            "keyword_checked": bool(got.get("keyword_checked")),
            "candidates_total": int(got.get("candidates_total") or 0),
            "pages_total": int(got.get("pages_total") or 0),
            "pages_judged": int(got.get("pages_judged") or 0),
            "candidates_seen": int(got.get("candidates_seen") or 0),
            "page_exhausted": bool(got.get("page_exhausted")),
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
        ## 只动档位与留痕，不动 bits（与 B 的登记那一笔同一口径）：`agent_f/core._proof_outlet`
        在攻坚那一侧现在把同一份内容再交给 B 的 `register_statement`（V 签完之后那一笔把档位升到
        `proof_review`），它也只改 `evidence_kind`。五元位的
        第 3 位（`reviewed`）是 V 的签名面，由 `verifications.bit3_payload(那一行)` 现读，不在这一格里抄进来 ——
        抄进来就有第二份"谁审过了"的账，而两份账迟早会分家。

        ## D-37（2026-10-24 真机 cube）：`kind` 也跟着证据升
        现场那一行早就升到了 `proof_review`（`have == want`），而 `kind` 仍写着 `conjecture` ⇒
        "档位还要不要升"这一支根本进不来。所以 `kind` 那一格独立算：判据只有一处
        （`evidencebits.kind_following_grade`，纯读；B 同步第 4 位那一支共用同一个），依据要么是 `verifications/`
        里一条盖住现行正文、判「成立」的签，要么是第 4 位逐条里一条 `verified`。
        只抬 `conjecture → theorem / lemma`（`body.kind` 只在两档之间选落点），作者写下的
        别的 kind 一个字不动；`bits` 仍然一个字节不写（五元位由现算派生，不抄第二份账）。
        升档依据落升档痕迹那一格（from / to / basis / grade / by / at），与证据档升档
        那一格同一套留痕形态。证据不够时这一行不改，`reason` 里附 `_kind_follow_note` 的原话
        （"还差什么"），不许折成"已经升了"。
        """
        from . import evidencebits as EB   # 惰性：D-37 的 kind 口径只有一处
        from . import verifications as VR   # 惰性：只在重复读数这一支才需要

        out: dict[str, Any] = {"upgraded": False, "row": {}, "changes": [],
                               "reason": "", "review_basis": {}}
        want = str(body.get("evidence_kind") or "")
        have = str(existing.get("evidence_kind") or "")
        row = dict(existing)
        changes: list[str] = []
        # ---- 2026-11-04（缺口 ②）：这一笔交付带来的 V 签是哪一路 ------------------
        #
        # 判据三路（任一路命中即可升档，与新建那一支算出来的档一致）：
        #   ① `verifications.proof_review_gap`（既有那一路：在册签名台账）；
        #   ② 手稿签块（`vsigns.manuscript_sign_standing`）；
        #   ③ `bits.reviewed`（B 收录时按正文 sha 认到的逐份签）。
        # ②③ 由 `_manuscript_upgrade_basis` 一处收拢：它们同源（B 的 `bits.reviewed`
        # 正是从手稿签块认出来的），所以反真空打桩点也只能有一个；两处各判一次会让
        # "摘掉手稿那一支"之后另一支照样升档，判据就量不到它。
        review_basis = _manuscript_upgrade_basis(
            root=self.store.root,
            manuscript_text=str(body.get("manuscript_text") or ""),
            manuscript_path=str(body.get("manuscript_path") or ""),
            proof_text=str(body.get("proof_text") or ""),
            bits=(dict(body.get("bits") or {}) or dict(existing.get("bits") or {})))
        signed_via = (str(review_basis.get("basis") or "")
                      if review_basis.get("signed") else "")
        out["review_basis"] = dict(review_basis)
        # ---- 证据侧那一行：这一笔带来的五元位比在册那一行强时，用它判 kind -------
        #
        # 为什么不能只看 `existing`：现场那一行是按"证明还空着"落成的猜想（bits.proof
        # 为空），而这一笔交来的正是那份证明 —— 判据读旧那一份会把"这一条现在有
        # 证明、也签过"读成"还差第 2 位"，于是 kind 永远升不上去（缺口 ② 的另一半）。
        probe_row = dict(existing)
        body_bits = dict(body.get("bits") or {})
        if bool(body_bits.get("proof")):
            merged_bits = dict(existing.get("bits") or {})
            merged_bits["proof"] = body_bits.get("proof")
            ev = dict(merged_bits.get("evidence") or {})
            new_ev = dict(body_bits.get("evidence") or {})
            for key in ("proof_process", "proof_source",
                        EB.REVIEWED_BY_PROOF_KEY, EB.REVIEWED_SHA_BY_PROOF_KEY,
                        "reviewed_by", "reviewed_source"):
                if key in new_ev:
                    ev[key] = new_ev[key]
            merged_bits["evidence"] = ev
            if body_bits.get("reviewed"):
                merged_bits["reviewed"] = True
            try:
                merged_bits["grade"] = EB.derive_grade(merged_bits)
            except Exception:  # noqa: BLE001 —— 等级算不出来就留给下面那一格判"判不了"
                pass
            probe_row["bits"] = merged_bits
        # ---- D-37（2026-10-24 真机 cube 的现场）：kind 跟着证据升。
        #
        # 与下面 `evidence_kind` 那一支各自独立：现场那一行早就升到了 `proof_review`
        # （`have == want`），缺的只是 `kind` 那一步 —— 所以这一格不能挂在"档位还要不要
        # 升"的条件下面。判据只有一处（`evidencebits.kind_following_grade`，纯读；B 同步
        # 第 4 位那一支与它共用同一个），这里只做两件本层的事：改那一格、把依据留痕。
        # `signed_via` 是"这一笔的 V 签在哪"（缺口 ②）：手稿签块 / `bits.reviewed`
        # 命中的那一路由调用方判完再交进来（判据仍只有一处）。
        kind_read = EB.kind_following_grade(
            probe_row, root=self.store.root, requested=str(body.get("kind") or ""),
            signed_via=signed_via)
        kind_upgraded = False
        if str(kind_read.get("state") or "") == "upgraded":
            target = str(kind_read.get("kind") or "")
            before_kind = str(existing.get("kind") or "")
            if target in EB.KIND_UPGRADE_TARGETS and target != before_kind:
                row["kind"] = target
                # 留痕：只改 kind 的那一笔也要读得出来"凭什么"（与
                # 与证据档升档那一格同一套：from / to / 依据 / 谁 / 何时）。
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
        #: proof」）。凭据三路见上面 `review_basis` 的说明：任一路命中即可升档。
        #: 为什么要开 `proof` 这一档：B 的第三方签字闸（`numericproof.filing_problems`）
        #: 要求 proof 必须有一份盖住这一条命题的 V 签，而 V 只审在册的命题 ⇒
        #: 「先按猜想落库、签完再升成定理级 proof」是唯一正路；这一格不通的话那条路在
        #: 秘书这一层就断了（`duplicate_statement`），穷举证明永远进不了定理证明库。
        evidence_upgraded = False
        evidence_gap = ""
        if (want in (VR.PROOF_REVIEW_KIND, "proof") and have != want
                and have in VR.WEAKER_THAN_PROOF_REVIEW):
            probe = dict(probe_row)
            probe["evidence_kind"] = want
            gap = VR.proof_review_gap(self.store.root, probe)
            if not gap.get("ok") and not review_basis.get("signed"):
                evidence_gap = (
                    f"（这一行没有升到 {want}：签名台账里读不到凭据"
                    f"（`verifications.proof_review_gap`：{str(gap.get('why') or '查不到凭据')[:240]}）"
                    f"；手稿签块 / `bits.reviewed` 也没有签"
                    f"（{str(review_basis.get('why') or '没有这一份交付的签')[:200]}））")
            else:
                row["evidence_kind"] = want
                ms = dict(review_basis.get("manuscript") or {})
                if gap.get("ok"):
                    how = "verification_ledger"
                    witness = (f"{gap.get('ledger') or ''}"
                               f"#{gap.get('verification_id') or ''}")
                elif str(ms.get("state") or "") == "signed":
                    how = "manuscript_sign_block"
                    witness = str(review_basis.get("basis") or "")
                else:
                    how = "bits_reviewed"
                    witness = str(review_basis.get("basis") or "")
                row["_evidence_kind_upgrade"] = {
                    "from": have, "to": want,
                    "verification_id": str(gap.get("verification_id") or ""),
                    "ledger": str(gap.get("ledger") or review_basis.get("basis") or ""),
                    "proof_sha256_matched": (bool(gap.get("sha_matches"))
                                             or bool(review_basis.get("signed"))),
                    #: 凭据是哪一路（`verification_ledger` / `manuscript_sign_block` /
                    #: `bits_reviewed`）：三路都能升档，但读的人必须分得开。
                    "basis": how,
                    "by": f"secretary-{self.role}", "at": S.now_iso(),
                }
                changes.append(f"evidence_kind: {have} → {want}（凭据：{witness}）")
                evidence_upgraded = True
        if not (kind_upgraded or evidence_upgraded):
            # ---- 已在终态（甲 的落点，2026-11-04）：穷举程序 + V 签 ⇒ proof 在落签那一刻
            # 就由 `verifications._grade_recomputed_from_signature` 定好了。B 这一次登记
            # 因此没有格可改 —— 但它不该被读成"重复登记"：这一条已经在库、就停在它该在
            # 的那一档。判据只读（`_signed_exhaustion_terminal`），与回填 / 审计同一份；
            # 只认 `want == have == "proof"`，文字证明（`proof_review`）那一路照旧走
            # `duplicate_statement`（D-37 的口径不动）。
            if want == have == VR.PROOF_KIND:
                body_text = str(body.get("proof_text") or "")
                disk_text = str(existing.get("proof_text") or "")
                if not body_text.strip() or body_text == disk_text:
                    try:
                        experiments = list(self.store.rows("experiments"))
                    except Exception:  # noqa: BLE001 —— 读不到就不认终态（保守）
                        experiments = []
                    terminal = _signed_exhaustion_terminal(
                        root=self.store.root, row=existing, proof_text=disk_text,
                        experiments=experiments)
                    out["terminal_reading"] = dict(terminal)
                    if terminal.get("terminal"):
                        out.update(upgraded=True, at_tier=True, row=row,
                                   reason=("同一份内容再交一次：盘上那一行已经是 "
                                           "`proof`（穷举程序 + V 签 —— 落签那一刻按通道"
                                           "定的档），这一笔没有新东西可写、也没有重复"
                                           "登记。"
                                           + str(terminal.get("why") or "")))
                        return out
            # 三态：一行都没改，而"还差什么"必须留在读数里（D-37）。
            out["reason"] = evidence_gap + self._kind_follow_note(kind_read)
            out["kind_reading"] = dict(kind_read)
            return out
        out.update(upgraded=True, row=row, changes=changes,
                   kind_reading=dict(kind_read))
        if evidence_upgraded:
            trace = dict(row.get("_evidence_kind_upgrade") or {})
            out["reason"] = (
                f"同一份内容再交一次、且这一回带了 `{want}` 的凭据 ⇒ 秘书"
                f"改那一行（不新建）：凭据是 {trace.get('basis') or '（没记）'}"
                f"（{trace.get('ledger') or ''}）；"
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

        ## 同一性判词在这里也要处置（2026-11-08）
        `concept_identity_gate` 在发号之前判，`concept_identity_action` 折成三档：

        - 判得 `same` ⇒ 并入那一条（不新建、不发号），读数 `concept_action="merged"`；
        - 判不了 ⇒ 这是 `D12` 甲 豁免的那一档（它豁免的正是"定义还没抽到"）：照落成
          `pending_definition`，但读数必须写明 `checked=False` / `d12_pending=True` 与原因
          —— 待补不是依据，也不是"可以落两行"；
        - `different` ⇒ 照常发号新建。

        `D12` 甲的边界写在这里：它豁免的是"定义还没抽到"这件事，不豁免"判得 same"。
        两条待补概念只差一个空格时闸看不到对手（`_same_concept_candidate` 跳过
        `pending_definition`），所以这一入口按同一把定义项键（`propositionkey.concept_keys`
        的标签那一半）把待补行也看一遍 —— 判据仍是那一处，不另写一份。

        拒绝（空标签 / 出处分档）都发生在 `alloc_id` 之前 ⇒ counters 不动、不留 `id_gap`。
        """
        from . import conceptrows as CR   # 惰性：并表过渡层的唯一读写口
        from . import textutil as T       # 惰性：查重键的唯一实现

        name = str(body.get("label") or "")
        if not name.strip():
            out.update(refused="empty_statement", concept_action="refused",
                       concept_identity={"checked": False, "state": "", "basis": "",
                                         "same_as": "", "candidates": [],
                                         "reason": "一条概念至少要有 label（名字）"},
                       reason="一条概念至少要有 label（名字）—— 没有名字的行谁也认不出它")
            return out
        legacy = CR.legacy_present(self.store)
        tables = list(STATEMENT_WRITE_TABLES) + ([CR.LEGACY_TABLE] if legacy.get("present") else [])
        with self.store.tx(*tables, actor=f"secretary-{self.role}",
                           note="record_statement:concept_pending") as tx:
            gate = concept_identity_gate(tx, label=name)
            act = concept_identity_action(gate)
            # 查重：先按规范化标签（既有口径，通用词也认），再按同一把定义项键把待补行
            # 也看一遍（闸跳过它们 —— 见 docstring 的 D12 甲 边界）。
            key = T.normalize(name)
            dup = next((r for r in tx.rows("statements")
                        if str(r.get("kind") or "") == "concept"
                        and T.normalize(str(r.get("label") or "")) == key), None)
            if dup is None:
                label_key = _PK.concept_keys(name, "")["label"]
                if label_key:
                    dup = next((r for r in tx.rows("statements")
                                if str(r.get("kind") or "") == "concept"
                                and _PK.concept_keys(str(r.get("label") or ""),
                                                     str(r.get("statement_full") or "")
                                                     )["label"] == label_key), None)
            if dup is not None:
                merged_id = str(dup.get("stmt_id") or "")
                if str(act.get("concept_action") or "") == "merged":
                    reading = dict(act)
                else:
                    reading = {"checked": True, "state": "same",
                               "basis": _PK.BASIS_CONCEPT_LABEL,
                               "same_as": merged_id, "candidates": [merged_id],
                               "reason": ("待补行不是同一性闸的合并落点（`pending_definition` "
                                          "不在可比行里）⇒ 这一入口按同一把定义项键补看一次："
                                          "标签规范化后相同（同一个概念）")}
                reading["concept_action"] = "merged"
                out.update(checked=True, created=False, duplicate=True, stmt_id=merged_id,
                           same_as=merged_id, concept_action="merged",
                           concept_identity=reading,
                           reason=(f"同一个概念已在册（stmt:{merged_id}）⇒ 并入那一行："
                                   "不新建第二行、不发号（判据："
                                   f"{str(reading.get('reason') or '').strip()}）"))
                return out
            # `origin` 按来源分档（本批缺陷一的第二处）：交来的概念有出处 ⇒ external_lit；
            # 没有出处 ⇒ 我们自己定义的新概念（own_result，推断，不要求调用方另声明）。
            # 这一判放在发号之前：拒的时候 counters 不动、不留 `id_gap`。
            src_lit = str(body.get("source_lit_id") or "")
            concept_origin = CR.resolve_concept_origin(source_lit_id=src_lit)
            problem = CR.concept_origin_problem(origin=concept_origin,
                                                source_lit_id=src_lit,
                                                self_authored=(concept_origin == "own_result"))
            if problem:
                out.update(checked=False, created=False, refused="concept_origin_refused",
                           concept_action="refused", reason=problem)
                return out
            # 过渡期的号空间只有一个权威：老表还在的时候就是 `concept`（B 的 pipeline
            # 从那儿发号），迁移之后才是 `stmt` —— 两边各发各的会让同一张表出现
            # `id_gap`（分配了号却没建行），而两张表还要同号。
            concept_kind = (S.TABLES[CR.LEGACY_TABLE]["id_kind"] if legacy.get("present")
                            else S.TABLES["statements"]["id_kind"])
            cid = tx.alloc_id(concept_kind)
            # 过渡期两处同号（`conceptrows` 的契约 1）：老表那份镜像沿用这个号。
            # `d12_pending=True` 是这一条 D12 甲 入口的身份（全仓只有这一处传）：
            # 判不了时照落成 pending_definition，别的普通调用不许走这条豁免。
            data = self.write_concept_row(tx, stmt_id=cid, label=name, definition="",
                                          aliases=body.get("aliases") or [],
                                          source_lit_id=src_lit,
                                          doc_id=str(body.get("doc_id") or ""),
                                          origin=concept_origin,
                                          self_authored=(concept_origin == "own_result"),
                                          mirror=bool(legacy.get("present")), out=out,
                                          d12_pending=True)
        d12 = bool(out.get("d12_pending"))
        out.update(checked=True, created=True, stmt_id=cid, row=data,
                   tables=tables, mirrored=bool(legacy.get("present")), pending_concepts=1,
                   concept_action="created",
                   nontriviality_not_applicable=True,
                   reason=("概念行已落成 pending_definition（定义待补）—— 它不是依据；"
                           "概念行不带 `proof_text`（概念不参与等级链，"
                           "要补的是定义，不是证明）"
                           + ("；同一性闸判不了（D12 甲 豁免的正是'定义还没抽到'这个前提）"
                              "⇒ 照落，但这一档不是'同一个概念可以落两行'"
                              if d12 else "")))
        return out

    def _concept_bits(self, *, origin: str, source_lit_id: str = "",
                      proof_text: str = "",
                      sign: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """概念行的五元位（唯一实现：`conceptrows.concept_bits`）。

        为什么概念行也要算这一格：见 `conceptrows.concept_bits` 的 docstring（空 `bits`
        不是"没有证据"，是"没有人替它算过"）—— 这一层只转调，不抄第二份理由。

        2026-11-10（业主裁定 甲）起这一格多了「良定义证明」一档：`proof_text` 有正文且
        `sign.state == "signed"`（`vsigns.sign_reading` 的结论）⇒ 第 2/3 位按同一套
        读数翻；等级仍是 `not_applicable`（概念没有等级轴，短路不改）。口径只有一处
        （`conceptrows.concept_bits`），这一层不抄第二份。
        """
        from . import conceptrows as CR   # 惰性：并表过渡层的唯一读写口

        return CR.concept_bits(origin=origin, source_lit_id=source_lit_id,
                               proof_text=proof_text, sign=sign)

    def _concept_row_payload(self, *, existing: Mapping[str, Any] | None,
                             sid: str, name: str, full: str,
                             alias_list: list[str], lit: str, doc_id: str,
                             origin: str, self_authored: bool,
                             proof_text: str) -> tuple[dict[str, Any], str]:
        """这一笔要写进 `statements` 的那份行数据，以及它的来路（`create` / `sync`）。

        `existing is None` = 新建：良定义证明这一格只在 V 签回来时保留正文（判据是既有
        唯一读口 `vsigns.sign_reading`，这里不新写一套），五元位随之现算。给了
        `existing` = 过渡同步改那一行：只改"从老表推得出来的那几格"，新标准独有的
        `proof_text` / `doc_id` / `created_at` / 已算好的 `bits` 一格不覆盖（老行里
        根本没有它们；已有的五元位也不整份重算 —— 签名那一族的凭据会被同步抹掉）。
        """
        from . import conceptrows as CR   # 惰性：并表过渡层的唯一读写口

        if existing is None:
            sign: dict[str, Any] = {}
            if str(proof_text or "").strip():
                from . import vsigns as _VS
                sign = dict(_VS.sign_reading(
                    (getattr(self.store, "root", "") or ""), statement_id=sid,
                    proof_text=str(proof_text), proof_no=1, store=self.store))
            data = CR.concept_statement(stmt_id=sid, label=name, definition=full,
                                        aliases=alias_list, source_lit_id=lit,
                                        doc_id=doc_id, actor=f"secretary-{self.role}",
                                        origin=origin, self_authored=self_authored,
                                        # 概念行不新写第二份判据：有没有签由上面那一读
                                        # 决定，构造口只按 `sign.state` 留 / 清。
                                        proof_text=proof_text, sign=sign
                                        ).to_dict()
            data["bits"] = self._concept_bits(
                origin=str(data.get("origin") or ""), source_lit_id=lit,
                proof_text=str(data.get("proof_text") or ""), sign=sign)
            return data, "create"
        data = dict(existing)
        # 只改"从老表推得出来的那几格"：新标准独有的 `proof_text` / `doc_id` /
        # `created_at` / 已算好的 `bits` 一格不覆盖（老行里根本没有它们）。
        data["label"] = name
        data["statement_text"] = full
        data["statement_full"] = full
        data["aliases"] = alias_list
        data["source_lit_id"] = lit or None
        if not dict(data.get("bits") or {}):
            # 老行本来没有五元位（这次才是它第一次经秘书的手）⇒ 补上一份；
            # 已经有了的那一份不整份重算（签名那一族的凭据会被同步抹掉）。
            _body = str(data.get("proof_text") or "")
            _sign: dict[str, Any] = {}
            if _body.strip():
                from . import vsigns as _VS
                _sign = dict(_VS.sign_reading(
                    (getattr(self.store, "root", "") or ""), statement_id=sid,
                    proof_text=_body, proof_no=1, store=self.store))
            data["bits"] = self._concept_bits(
                origin=str(data.get("origin") or ""), source_lit_id=lit,
                proof_text=_body, sign=_sign)
        return data, "sync"

    def write_concept_row(self, tx: Any, *, stmt_id: str, label: str,
                          definition: str = "", aliases: Iterable[str] = (),
                          source_lit_id: str = "", doc_id: str = "",
                          origin: str = "", self_authored: bool = False,
                          mirror: bool = False,
                          existing: Mapping[str, Any] | None = None,
                          status: str = "", quote_reason: str = "",
                          proof_text: str = "",
                          out: dict[str, Any] | None = None,
                          transition_sync: bool = False,
                          d12_pending: bool = False) -> dict[str, Any]:
        """在已开的事务里写一条概念行：洗名 + 五元位 + 概念同一性都在这一处做。

        ## 为什么不是调 `record_statement`

        `record_statement` 自己开事务，而概念行的写侧全都在一笔已经打开的事务里
        （`_record_pending_concept` / `conceptrows.write_concept` / `sync_from_legacy`）——
        事务不能嵌套（文件锁不可重入）。而且 `record_statement` 会先跑一次命题同一性判定
        （可能发模型调用），而"锁里不许有网络等待"是本仓的硬规矩；概念这一档也不发调用。
        所以这里是"同一个写入方、同一套判据、不开新事务"的那一格：两个过渡写口都调它，
        读侧与写侧的判据因此只有一份。

        ## 三件事在这里做

        1. 五元位：`_concept_bits` 现算（概念行算出来的等级是 `not_applicable`）；
           概念行不直写 `bits`，否则"五位一位都没做"的读数会对整批旧行全部成立；
        2. 洗名：`wash_working_name`（零模型调用）；洗过就把 `from`/`to`/`why` 放进
           `out["label_washed"]` —— 静默改名是不许的；
        3. 概念同一性：`_same_concept_candidate`（`propositionkey.same_concept` 的唯一调用点），
           判词进 `out["concept_identity"]`。

        ## 判到"同一个概念"时按 `concept_identity_action` 折算

        - `merged`（新建 + same + 有候选）⇒ 不写这一行，返回并入读数（`stmt_id` 即并入对象）。
          调用方给的号必须是在过闸之前没发过的 —— 这一档是最后一道网，不是发号点；
        - `refused`（判不了）⇒ 新建那一支不写、返回受控拒，拒信给改法（把定义项写出来）。
          例外：`d12_pending=True`（定义还没抽到的概念行的唯一入口）照落成
          `pending_definition`，读数里写明这个前提；
        - `created`（different / 候选 0 条）⇒ 照常写。

        改一条既有行（`existing` 给了）不新建也不并入：它本身就是那一行，读数只报
        `checked` / `state` / `same_as` / `reason`。

        `transition_sync=True` 只给 `conceptrows.sync_from_legacy`（一号一行的过渡同步，
        合并不在这一层做）；`d12_pending=True` 只给 `_record_pending_concept`。
        别的调用点传这两个中的任何一个 ⇒ 机械判据当场红。

        升档（`pending_definition` 回 `active`）与合并（老表墓碑 ⇒ `superseded` + 理由）
        都由调用方算好 `status` / `quote_reason` 再进来。
        """
        from . import conceptrows as CR   # 惰性：并表过渡层的唯一读写口
        from . import textutil as T       # 惰性：查重键的唯一实现

        sid = str(stmt_id or "")
        name = str(label or "")
        full = str(definition or "")
        alias_list = [str(a) for a in (aliases or ()) if str(a).strip()]
        lit = str(source_lit_id or "")
        # ---- 洗名（D1 的唯一实现；没命中就一个字节都不动）
        working = wash_working_name(name, statement_full=full, kind="concept", stmt_id=sid)
        if working:
            name = str(working["to"])
            if out is not None:
                out["canonical_name"] = name
                out["label_washed"] = dict(working, stmt_id=sid)
        data, creator = self._concept_row_payload(
            existing=existing, sid=sid, name=name, full=full,
            alias_list=alias_list, lit=lit, doc_id=doc_id, origin=origin,
            self_authored=self_authored, proof_text=proof_text)
        if str(status or "").strip():
            data["status"] = str(status)
        if str(quote_reason or "").strip():
            data["quote_reason"] = str(quote_reason)
        # 概念行的「良定义证明」读数（三态 + 来源）：写进来的这一笔与读回去的那一格
        # 用同一份实现（`conceptrows.well_definedness_reading`）。
        if out is not None:
            out["well_definedness"] = CR.well_definedness_reading(
                (getattr(self.store, "root", "") or ""), data, store=self.store)
        # ---- 概念同一性（唯一判据；改一条既有行时把自己排除在命中之外）
        identity = self._same_concept_candidate(tx, label=name, full=full, exclude_id=sid)
        hit = dict(identity.get("hit") or {})
        act = concept_identity_action(identity)
        #: 这一笔的最终处置：D12 甲（`_record_pending_concept`，按调用方身份传入
        #: `d12_pending=True`）把 refused 折成"照落"，其余按折算点的三档；
        #: 改既有行没有"新行"可谈，不写这一格。
        pending_exempt = (act["concept_action"] == "refused"
                          and existing is None and bool(d12_pending))
        final_action = "created" if pending_exempt else act["concept_action"]
        if out is not None:
            out["concept_identity"] = {
                "checked": bool(identity.get("checked")),
                "state": str(identity.get("state") or ""),
                "basis": str(identity.get("basis") or ""),
                "same_as": str(hit.get("stmt_id") or ""),
                "candidates": [str(x) for x in (identity.get("candidates") or [])],
                "reason": str(identity.get("reason") or ""),
            }
            if existing is None:
                out["concept_identity"]["concept_action"] = final_action
                out["concept_action"] = final_action
                out["d12_pending"] = pending_exempt
        elif hit:
            # 判到"同一个概念"而调用方没要读数（`conceptrows` 那三个写口就是这样）⇒
            # 落到秘书自己的台账上：这一笔判过、判的是哪一行必须在盘上留得住，
            # 否则这一层判了等于没判（改前连判据都没有，见 `_concept_secretary`）。
            try:
                self.note_decision(
                    duty=2, decision="concept_duplicate",
                    reason=str(identity.get("reason") or ""),
                    basis=[str(identity.get("basis") or "")],
                    target={"concept": sid, "same_as": str(hit.get("stmt_id") or "")},
                    fail_open=False)
            except Exception as exc:  # noqa: BLE001 —— 留痕失败不带走这一笔写
                self._log(f"概念同一性留痕没写成：{type(exc).__name__}: {exc}")
        # ---- 处置（默认强制；只有过渡同步那一条路只报不处置）
        if not transition_sync and existing is None:
            if act["concept_action"] == "refused" and not pending_exempt:
                why = str(identity.get("reason") or "")
                return {"concept_action": "refused", "checked": False, "state": "",
                        "same_as": "", "candidates": list(act.get("candidates") or []),
                        "refused": CONCEPT_IDENTITY_UNJUDGED, "concept_identity": dict(act),
                        "reason": (why + " ⇒ 这一笔不写（不新建、不合并）。"
                                   "改法：把定义项写出来 —— 标签写成具体术语，或正文写成"
                                   "「概念（X）」/「定义（X）」；若它确实与在册某一条不同，"
                                   "把那个不同的定义项写出来再交")}
            if act["concept_action"] == "merged":
                target = str(act.get("same_as") or "")
                why = (f"同一个概念已在册（stmt:{target}；依据："
                       f"{self._basis_text(str(act.get('basis') or ''), 0.0)}）⇒ 并入那一行："
                       "不新建第二行、不发号")
                return {"stmt_id": target, "concept_action": "merged", "checked": True,
                        "state": "same", "same_as": target,
                        "candidates": list(act.get("candidates") or []),
                        "concept_identity": dict(act), "reason": why}
        obj = S.row_from_dict("statements", data)
        obj.validate()
        data = obj.to_dict()
        tx.upsert("statements", data, note=f"secretary:concept_{creator}")
        if mirror and CR.LEGACY_TABLE in S.TABLES:
            # 过渡期两处同号（`conceptrows` 的契约 1）：老表那份镜像沿用这个号。
            # 落刀之后那张表不存在 ⇒ 这里自己判（与 `tables_for_concept_write` 同一口径）。
            crow = S.Concept(
                concept_id=sid, name=name, definition=full, related_concepts=[],
                normalized_name=T.normalize(name), aliases=alias_list,
                definition_source_lit_id=lit or None,
                created_at=S.now_iso(), updated_at=S.now_iso())
            crow.validate()
            tx.upsert(CR.LEGACY_TABLE, crow.to_dict(), note="secretary:concept_mirror")
        CR.push_counters(tx, sid)   # 一个号空间、两个计数器（见 push_counters）
        # 概念/定义行的档位读数：不适用（没有证明正文）。不落这一格时，读侧会把
        # "没有记录"与"不需要记录"都印成同一个"未判"。
        # 两支都调（新建与同步）：那一格是幂等的（同一段正文只落一行），于是存量概念行
        # 会在它下一次经秘书那一笔时被补上，不需要一次全库迁移。
        # 判/落拆段（NT2）：这一笔已经拿到号（`sid`）⇒ 判与落同在这一处、`record=True`。
        self.judge_statement(statement_full=full, kind="concept", stmt_id=sid,
                             record=True)
        return data

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
        """从"定理内容 + 证明过程"里扫出依赖（B 只交这两样）。

        ## 路径分组（`Dependency.path_group`）：载荷给了显式的 `proof_paths`（多段可选证明，B 自己分的段）⇒
        每段一组，下标从 1 起（组内 AND / 组间 OR）；载荷给了 `proofs`（多证明清单）
        ⇒ 一份证明一组，组下标就是它在清单里的位次，并且这一组的每一步都带上它的
        `proof_no`（于是 `used_by` 落成 `stmt:<号>#pN`，第 2 份及以后的依赖面不再与 #p1 混在一起）。
        两样都没给 ⇒ 把 `statement_full` + `proof_text` 当一段（全归第 1 组）—— 刻意"不猜"：
        不按空行、不按"证明一/证明二"这种字样去猜 B 想分几段。
        ## 三态（`state`）：
        | 取值 | 什么时候 | 为什么必须分开 |
        |---|---|---|
        | `from_proof` | 扫到了至少一条在册引用 | 这是"扫到了" |
        | `none_in_proof` | 证明过程给了（键在）、一条引用也没有 | 这是"扫了、确实是空的" |
        | `unknown` | 证明过程这一格根本没给、也没扫到引用 | 这是"没扫成" —— 与"空"折平就等于把"B 没交证明过程"读成"这条定理不依赖任何东西" |
        扫的范围是定理内容 + 证明过程两张脸（"证明过程/定理内容里出现的引用"），去重按 `(前缀, 代号)`
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
        #: 单段扫描的路径号（2026-11-11 收尾批）：B 逐份 inline 登记时把分配出来的
        #: 路径号放在 `body["path_group"]` 里（② 那一支也调 `assign_path_group`），
        #: 这一档没有 `proofs` / `proof_paths` 可分组 ⇒ 段落下标恒为 1，只能用这个号。
        #: 没有这一格 ⇒ 0（老路逐字不变：按段落下标，第 1 组 = 1）。
        _single_group = 0
        if proof_plan:
            paths = [text for _no, text in proof_plan]
        elif isinstance(raw_paths, (list, tuple)) and raw_paths:
            proof_plan = [(0, str(p or "")) for p in raw_paths]
            paths = [text for _no, text in proof_plan]
        else:
            try:
                _single_group = int(body.get("path_group") or 0)
            except (TypeError, ValueError):
                _single_group = 0
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
                #: 单段而 B 分配了路径号（`body["path_group"]`）⇒ 用那个号（② 的那一支）。
                group_no = int(plan_no) if plan_no >= 1 else (
                    int(_single_group) if int(_single_group) >= 1 else gi)
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
                             adjudication: Mapping[str, Any] | None = None,
                             candidate_id: str = "",
                             proof_kind: Mapping[str, Any] | None = None
                             ) -> dict[str, Any]:
        """一笔事务把命题（+ 概念行 + 依赖组）落盘（`record_statement` 的写那一半）。

        `adjudication` 是事务之外那一次模型判定（见 `adjudicate_proposition`）：
        它决定这一笔是"并进在册的那一条"还是"新建"，并把定理名洗成 `canonical_name`。
        `proof_kind` 是事务之外那一次"同种证明"判定（`_proof_kind_for_existing`）：
        事务里只读结论、只落盘 —— 锁里不许有网络等待、更不许发模型调用。
        """
        from . import conceptrows as CR   # 惰性：并表过渡层的唯一读写口
        from . import textutil as T       # 惰性：查重键的唯一实现
        from . import verifications as VR  # 惰性：新建那一支的 #pN 落点要它的 PROOFS_KEY

        adj = dict(adjudication or {})
        # ---- 洗定理名（业主 2026-10-24）：「Sylow 三定理（路线一：…）」⇒「Sylow 三定理」。
        # 落点是 label；被洗掉的路线进证明那一层（见下面 `PROOF_ROUTES_KEY` 那一格）。
        # 这里只动"写进这一行的那份 body 副本"：调用方交上来的原文一个字不改
        # （`out["label_washed"]` 留着 from / to 两格，静默改名是不许的）。
        if adj.get("checked") and str(adj.get("canonical_name") or "").strip():
            was = str(body.get("label") or "")
            now = str(adj.get("canonical_name") or "").strip()
            if was != now:
                body = dict(body)
                body["label"] = now
                out["canonical_name"] = now
                out["label_washed"] = {
                    "from": was, "to": now, "class": LABEL_WASH_ROUTE,
                    "why": ("标签里的路线 / 自证草稿 / 待 V 审签那一类修饰被洗掉了"
                            "（秘书判同一性那趟给的名字）；被洗掉的路线落进证明那一层，不丢")}
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
            # 良定义证明（2026-11-10 业主裁定 甲）：正文只在 V 已签时保留；没签就清空
            # 并留读数（`concept_proof_text_dropped`）。判据仍是唯一读口
            # `vsigns.sign_reading` —— 这一层不新写一套。
            _body = str(body.get("proof_text") or "")
            _sign: dict[str, Any] = {}
            if _body.strip():
                from . import vsigns as _VS
                _sign = dict(_VS.sign_reading(
                    str(getattr(self.store, "root", "") or ""),
                    statement_id=str(candidate_id or ""), proof_text=_body,
                    proof_no=1, store=self.store))
                if str(_sign.get("state") or "") != "signed":
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
            if not dict(body.get("bits") or {}):
                # 五元位由这一层现算（2026-10-26，D14）：改前概念行只在调用方自己带了
                # `bits` 时才有它，而 B 的 pipeline 那条路（`conceptrows` 的三个写口）
                # 从来不带 ⇒ 真机 mp3-r3 的 30 条概念行 `bits` 全空。这一格与
                # `write_concept_row` 用的是同一个 `_concept_bits`（判据不看调用方是谁）。
                body["bits"] = self._concept_bits(
                    origin=_resolved, source_lit_id=_src,
                    proof_text=str(body.get("proof_text") or ""), sign=_sign)
            if out.get("well_definedness") is None:
                out["well_definedness"] = CR.well_definedness_reading(
                    str(getattr(self.store, "root", "") or ""),
                    {"stmt_id": str(candidate_id or ""),
                     "proof_text": str(body.get("proof_text") or "")},
                    sign=_sign, store=self.store)
        legacy = CR.legacy_present(self.store)
        # ---- 调用方给的路径号：忽略，但要让读的人看见「这个号不是它给的」 --------
        #
        # 业主口径：路径号归秘书（这一笔事务里分配）；产出侧不写 `-pN`、B 的动作也
        # 不再自己算。B 若还塞了一个进来，这里不校验、也不采信 —— 校验一致只是
        # 把两套算法并排留着（两份迟早会漂，而漂的那一天没有读数会响）；直接忽略
        # 才不会出现「调用方说了算」的第二条口径。`path_group_ignored` 把收与弃都写下来。
        _given_path_group = 0
        try:
            _given_path_group = int(body.get("path_group") or 0)
        except (TypeError, ValueError):
            _given_path_group = 0
        if _given_path_group >= 1:
            out["path_group_ignored"] = {
                "given": _given_path_group,
                "by": "调用方（B 的动作）",
                "why": ("路径号由秘书在收录事务里分配（`assign_path_group`）⇒ 调用方给的"
                        "这个数一个字节都不采信；回执里的 `path_group` 才是这一笔用的号"),
            }
        with self.store.tx(*STATEMENT_WRITE_TABLES, "literature", "experiments",
                           "documents",
                           *([CR.LEGACY_TABLE] if legacy.get("present") else ()),
                           actor=f"secretary-{self.role}",
                           note="record_statement") as tx:
            # 正文规范化全等的比对口径只有一处（查口 `duplicate_hits`）；
            # 读的是事务快照（`tx.rows`），所以"读—判—写"仍在同一把锁里。
            existing = (SL.duplicate_hits(tx.rows("statements"), text=full)["hits"]
                        or [None])[0]
            if existing is not None and not force_new:
                # ---- 路径号：先算，升档那支与重复那支都要用它 ----------------------
                #
                # 同一命题已在册、而交上来的正文是它的一条新路径（或正本还空着
                # 的"先立命题、后补证明"）⇒ 号在这里分配：B 随后用这个号把正文挂成
                # 第 N 份证明（`_attach_proofs`），依赖面 / `verifications` 行也用它。
                # 号必须在锁里分（锁外分，两个并发收录会同时看到 N ⇒ 都开 N+1）。
                # 同一份正文再交一次 ⇒ 沿用原号（`_same_no`），不新增路径；改稿 /
                # 纯重复读数那两档不分号。
                _dup_proof = str(body.get("proof_text") or "")
                _dup_alloc: dict = {}
                _dup_first_fill = not str(existing.get("proof_text") or "").strip()
                # ---- 「难以自证」的空号 ⇒ 整条替换（业主 2026-11-13 裁定）------------
                #
                # 位置在"重复 / 升档"两档之前：那一格是"引文占位"的正文，不是"已有
                # 证明"的第二次提交 —— 它不许把这一份带真 V 签的新稿挤回任何一档
                # （升档那支会把优化栏打成 true 并留下旧的 hard_to_prove）。
                # 返回 None ⇒ 这一行没有空号（或这一笔就是同一份正文的重交）⇒ 照旧。
                if self._fill_vacant_path_in_tx(
                        tx, row=dict(existing), sid=str(existing.get("stmt_id") or ""),
                        proof_text=_dup_proof, groups=groups, out=out,
                        manuscript=str(body.get("manuscript_path") or "")) is not None:
                    return out
                # ---- 同种证明（业主 2026-11-12）：结论来自事务外那一问，这里只落 -----
                #
                # 只在"这一笔是同一命题的另一条证明路径"（`proof_path_kind=="new_path"）
                # 且正文确实是新的时候判：同一份正文重交是幂等（走 `_same_no`），改稿
                # （B 的改写载体）不是新路径。判不了 ⇒ fail-closed（不收录），不许折成
                # "不同"照旧开新路径。
                _verdict = dict(proof_kind or {})
                _dup_sha = VR.text_sha(_dup_proof) if _dup_proof.strip() else ""
                _known_now = {VR.text_sha(str(t))
                              for _n, t in VR.proof_list(dict(existing))
                              if str(t or "").strip()}
                if (str(body.get("proof_path_kind") or "") == "new_path"
                        and _dup_sha and _dup_sha not in _known_now):
                    _sid_now = str(existing.get("stmt_id") or "")
                    if not _verdict.get("checked"):
                        out.update(checked=False, created=False, duplicate=False,
                                   refused=PROOF_KIND_UNJUDGED, stmt_id=_sid_now,
                                   reason=("这一份证明与在册各路径是不是同种没判成"
                                           "（没判成 ≠ 不同）⇒ 不收录、不新增路径："
                                           + str(_verdict.get("reason")
                                                 or "判定面没给可用结论")))
                        return out
                    if str(_verdict.get("decision") or "") == "same":
                        _n = int(_verdict.get("same_path") or 1)
                        out.update(checked=False, created=False, duplicate=False,
                                   refused=PROOF_SAME_KIND, stmt_id=_sid_now,
                                   same_kind_material={
                                       "similarity": float(_verdict.get("similarity") or 0.0)},
                                   reason=(f"这一份证明与 stmt:{_sid_now} 的第 {_n} 条路径同种"
                                           "（秘书的语义判定：两套证法是同一路，不是两条"
                                           "独立路径）⇒ 不收录、不新增路径。材料读数"
                                           "（只作参考）：相似度 "
                                           f"{float(_verdict.get('similarity') or 0.0):.4f}。"
                                           "处置：换一条真正不同的证法再交，或本次不再提交"))
                        return out
                if ((_dup_first_fill
                     or str(body.get("proof_path_kind") or "") == "new_path")
                        and _dup_proof.strip()):
                    _dup_sha = VR.text_sha(_dup_proof)
                    _same_no = next(
                        (int(no) for no, _t in VR.proof_list(dict(existing))
                         if str(_t or "").strip() and VR.text_sha(str(_t)) == _dup_sha), 0)
                    if _same_no >= 1:
                        out["path_group"] = _same_no
                        out["path_group_reading"] = {
                            "checked": True, "path_group": _same_no, "existing": True,
                            "statement_id": str(existing.get("stmt_id") or ""),
                            "manuscript": str(body.get("manuscript_path") or ""),
                            "body_sha": _dup_sha, "count": 0, "paths": [],
                            "problems": [],
                            "why": (f"这一份正文已经是第 {_same_no} 条路径 ⇒ 沿用原号，"
                                    "不新增路径"),
                        }
                    else:
                        _dup_alloc = _assign_path_group_in_tx(
                            tx, root=self.root,
                            statement_id=str(existing.get("stmt_id") or ""),
                            manuscript=str(body.get("manuscript_path") or ""),
                            body_sha=_dup_sha)
                        if not _dup_alloc.get("checked"):
                            out.update(checked=False, created=False, duplicate=False,
                                       refused="path_group_unreadable",
                                       reason=("路径数读不出来 ⇒ 这一笔不写（不猜第几条）："
                                               + str(_dup_alloc.get("why") or "未知原因")))
                            return out
                        out["path_group"] = int(_dup_alloc.get("path_group") or 1)
                        out["path_group_reading"] = dict(_dup_alloc)
                upgraded = self._upgrade_evidence_kind(existing, body)
                if upgraded.get("upgraded"):
                    # 同一份内容、这一回带来的证据档更强 ⇒ 改那一行（不新建）。
                    # 这是"改表"那一件活的正路，也是 `evidence_kind` 从弱档走到
                    # `proof_review` 的唯一一条路（通用写口 `table.update` 已在
                    # `store.direct_write_refusal` 那一层被拒）。
                    #
                    # `at_tier` 是"盘上已经是终态档（穷举程序 + V 签 ⇒ proof）"那一支：
                    # 这一笔不写（没有格可改），但读数与"升档"分开记 ——
                    # "这次把档改上去了"与"它早就在那一档"是两件事。
                    at_tier = bool(upgraded.get("at_tier"))
                    if not at_tier:
                        tx.upsert("statements", upgraded["row"],
                                  note="record_statement:upgrade")
                    out.update(checked=True, created=False, duplicate=False,
                               upgraded=True, at_tier=at_tier,
                               stmt_id=str(existing.get("stmt_id") or ""),
                               row=dict(upgraded["row"]),
                               tables=[] if at_tier else ["statements"],
                               changes=list(upgraded.get("changes") or []),
                               reason=str(upgraded.get("reason") or ""))
                    if at_tier:
                        out["terminal_reading"] = dict(
                            upgraded.get("terminal_reading") or {})
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
                                                  adjudication=adj,
                                                  proof_kind=proof_kind)
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
            # ---- D2（2026-11-05 走查）：稿名 / 稿头的号当候选号，「不另发一个」 -------
            #
            # 现场（`temp/e2e-sign-20261105-b` 主链）：稿名 / 稿头是 000001，而计数器从 0
            # 起 ⇒ 登记拿到 000000。第 4 步靠"新命题还没有号"使 owner 判据短路才过；
            # 第 5 步同一条命令就撞 `manuscript_owner_mismatch`；收工扫盘按「稿名」开
            # `b-register@000001@…` 的义务永远收不了口（`reconcile_registrations` left=1）。
            #
            # 口径①（业主 2026-11-05 选定）：候选号可用 ⇒ 就用它（并把计数器抬到它之后，
            # 下一笔不会又撞）；已被占 ⇒ 受控拒绝 `stmt_id_taken`，绝不静默另发一个 ——
            # 错位是静默的，没有任何事后读数会报它（`verify_all` 0 error 就是那次真空的绿）。
            candidate = str(candidate_id or "").strip()
            if candidate:
                if not S.is_valid_id(candidate):
                    out.update(checked=False, created=False, refused="bad_candidate_id",
                               reason=(f"候选号 {candidate!r} 不是命题号形态"
                                       f"（{S.ID_DIGITS} 位十进制；旧四位仍可读）⇒ "
                                       "整笔不写。稿名 / 稿头要给号就给对形态"))
                    return out
                occupied = SL.by_id(rows=tx.rows("statements"), stmt_id=candidate)["row"]
                if occupied:
                    out.update(checked=False, created=False, refused="stmt_id_taken",
                               stmt_id=candidate,
                               reason=(f"稿名 / 稿头要的号 {candidate} 已被在册命题占用"
                                       f"（{str((occupied or {}).get('label') or '')[:60]!r}，"
                                       f"正文 {str((occupied or {}).get('statement_full') or '')[:80]!r}）"
                                       "⇒ 整笔不写，也不另发一个号：另发会让稿头号与登记号错位，"
                                       "而那个错位是静默的（扫盘义务、第 5 步的 owner 判据都会"
                                       "按错位后的号读）。处置：让作者把稿改成要登记的那个号，"
                                       "或确认这条命题确实已在册（用返回里那个 stmt_id）。"))
                    return out
                stmt_id = candidate
                tx.raise_counter_to(stmt_kind, candidate)
                out["stmt_id_candidate"] = candidate
                out["stmt_id_candidate_source"] = "candidate"
            else:
                stmt_id = tx.alloc_id(stmt_kind)
            # ---- 路径号（业主口径）：这一笔是新建 ⇒ 由秘书在这一笔事务里分配 ------
            #
            # 号在这里分而不是在 B 那一侧：新建的命题还没有任何路径 ⇒ 这个号必然是
            # 第 1 条；但它与"写依赖 / 写 `used_by` / 回执"必须是同一个数，且要在
            # 同一把锁里定下来。`assign_path_group` 是唯一实现（同一份正文 sha /
            # 同一份稿沿用原号 —— 对新建这一档是死路，对合并那一档才是活的）。
            _new_alloc = _assign_path_group_in_tx(
                tx, root=self.root, statement_id=stmt_id,
                manuscript=str(body.get("manuscript_path") or ""),
                body_sha=VR.text_sha(str(body.get("proof_text") or "")))
            if not _new_alloc.get("checked"):
                out.update(checked=False, created=False, refused="path_group_unreadable",
                           reason=("路径数读不出来 ⇒ 这一笔不写（不猜第几条）："
                                   + str(_new_alloc.get("why") or "未知原因")))
                return out
            _new_path_no = int(_new_alloc.get("path_group") or 1)
            _note_path_material(out, _path_material_numbers(groups)
                                if len(groups) <= 1 else [], decided=_new_path_no)
            out["path_group"] = _new_path_no
            out["path_group_reading"] = dict(_new_alloc)
            # ---- 内部工作名不许当定理名（D1；真机 mp3-r2 的 000000 / 000001）---------
            # 那两行的 label 逐字都是「F 攻坚 000000 子目标 S2」：派活台账里的工作名进了
            # 定理名，于是同一条定理的两份证明在台账上看起来是两条不同的定理。判据与词表
            # 在 `wash_working_name`（确定性、零模型调用），位置在这里而不是上面那一格，
            # 是因为兜底那两级要用到刚发下来的 `stmt_id`（第四级名字里有它）。
            # 与模型洗名不冲突：括号里那一类（路线 / 草稿状态）由上一格洗，这一格见括号
            # 不配对就整条不动（见 `_brackets_balanced`）。
            working = wash_working_name(body.get("label"), statement_full=full,
                                        kind=kind, stmt_id=stmt_id)
            if working:
                body = dict(body)
                body["label"] = str(working["to"])
                out["canonical_name"] = str(working["to"])
                out["label_washed"] = dict(working, stmt_id=stmt_id)
            row = self._statement_from(body, full=full, kind=kind, stmt_id=stmt_id)
            row.validate()
            # ---- 2026-11-05（缺陷乙的第二道闸）：10 键齐、没有 None ---------------
            #
            # `_statement_from` 已经用 `_complete_statement_bits` 把 `bits` 补全了
            # （"补全"那一半）；这一格是"拒"那一半：将来有人绕过补全、或者补全本身
            # 被改坏，落盘的就不再是空表，而是「整笔不写」—— 一条 `bits` 空的行
            # 比一条写坏的 evidence_kind 更坏：它让档位与等级同时变成"读不出来"，
            # 而 `bits_shape_problems({})` 返回的是 `[]`（空表 = 没有形状问题）。
            _bits_now = dict(getattr(row, "bits", None) or {})
            _bits_missing = [k for k in STATEMENT_BITS_KEYS
                             if k not in _bits_now or _bits_now[k] is None]
            if _bits_missing:
                raise ValueError(
                    "statements.bits 必须 10 键齐、且没有一格是 None；这一笔缺 "
                    f"{_bits_missing}（整表只有 {sorted(_bits_now)}）⇒ 整笔不写："
                    "落一条空 bits 的行，档位与等级就再也读不出来（现场 000019，"
                    "`data/events.jsonl:3671`）")
            if (row.origin == "own_result" and not str(body.get("quote_reason") or "").strip()
                    and body.get("quote_verified") is not True):
                # 读数：`quote_reason` 是秘书补的（B 只交两样，见 `_statement_from`）——
                # 补了必须看得见，否则"这一格为什么有值"在盘上无从分辨。
                out["quote_reason_filled"] = True
            try:
                requested_no = int(body.get("proof_no") or 0)
            except (TypeError, ValueError):
                requested_no = 0
            data = self._annotate_proposition(
                row.to_dict(), adj, proof_no=(requested_no if requested_no >= 1 else 1),
                route=route)
            # ---- 交付说这一份是 #pN（N>1）⇒ 它进 `proofs` 清单，不进 canonical ----
            #
            # 2026-11-04（缺口 ①）：新建那一支同样要认交付里的号。canonical（`proof_text`）
            # 只放 #p1；把第 2 份写进那一格会让 `verifications.proof_list` 读出两条 #p1
            # （一条正文、一条空），而依赖的 `used_by`、V 的逐份签、论文对应表全按号走。
            # 五元位由 B 现算并随载荷交来，逐份表已经按这个号记（`reviewed_by_proof`），
            # 这里只搬正文、不改位。
            if requested_no > 1 and str(data.get("proof_text") or "").strip():
                text_now = str(data.get("proof_text") or "")
                data["proof_text"] = ""
                listed_now = [dict(p) if isinstance(p, Mapping) else p
                              for p in (data.get(VR.PROOFS_KEY) or [])]
                listed_now.append({"proof_no": int(requested_no),
                                   "proof_text": text_now,
                                   "created_at": S.now_iso()})
                data[VR.PROOFS_KEY] = listed_now
            # ---- 167/作者（业主 2026-11-01 裁定）：登记的那一刻把"谁写的"记下来。
            #
            # 为什么必须在这里：V 回执的收件人 = 送审者（召唤 V 的那个 task），而
            # "送审者该不该是这个人"只能拿"作者是谁"来判（业主：「F 写的证明，F 送审
            # ……B 侧收录」「不存在 F 写证明 B 送审」）。盘上此前没有这一格，81 的 8 条
            # 回执只能记成 `author_not_recorded`（`vreceipts._author_of`）。
            #
            # 只加数据：不改 `bits`、不改收录行为、不改 `created_by`（那是登记口）。
            # 读不出来源 ⇒ 不写这一格（`author_not_recorded`），不许默认成 B。
            from . import proofauthors as _PAA

            author = _PAA.author_reading(body=body, root=self.root)
            if author.get("author"):
                data["proof_authors"] = _PAA.recorded(author)
            out["author_reading"] = dict(author)
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
            identity_actions: list[dict] = []
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
                    refused_concepts.append({"name": name, "why": problem,
                                             "concept_action": "refused"})
                    continue
                # ---- 同一性闸（发号之前）：`write_concept_row` 收紧之后，先发号再判
                # same / 判不了都会留下"号已发、行没建"的空洞（`verify` 的 `id_gap`）。
                # 处置口径与四个入口同一处（`concept_identity_action` 唯一折算点）。
                gate = concept_identity_gate(
                    tx, label=name, full=str(c.get("definition") or ""))
                act = concept_identity_action(gate)
                if act["concept_action"] == "refused":
                    refused_concepts.append({
                        "name": name, "why": str(act.get("reason") or ""),
                        "concept_action": "refused", "checked": False, "state": "",
                        "same_as": "", "reason": str(act.get("reason") or "")})
                    continue
                if act["concept_action"] == "merged":
                    identity_actions.append({
                        "name": name, "concept_action": "merged",
                        "same_as": str(act.get("same_as") or ""), "checked": True,
                        "state": "same",
                        "candidates": [str(x) for x in (act.get("candidates") or [])],
                        "reason": str(act.get("reason") or "")})
                    continue
                if not quota.admit(name):
                    refused_concepts.append({"name": name, "why": quota.reading()["why"],
                                             "concept_action": "refused"})
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
                identity_actions.append({
                    "name": name, "concept_action": "created",
                    "concept_id": cid, "same_as": "", "checked": True,
                    "state": str(act.get("state") or "different"), "candidates": [],
                    "reason": str(act.get("reason") or "")})
                if str(crow_data.get("status") or "") == "pending_definition":
                    pending_concepts += 1
            if dropped_proof:
                out["concept_proof_text_dropped"] = dropped_proof[:20]
            if refused_concepts:
                out["concepts_refused"] = refused_concepts[:20]
            if identity_actions:
                out["concepts_identity"] = identity_actions[:20]
            out["concept_quota"] = quota.reading()
            # 这一笔的路径号是秘书刚分配的（见上）：依赖的 `used_by` 尾巴与
            # `path_group` 都从它来 —— 产出侧不再写号，这一段是那个号唯一的落点。
            steps = _stamp_path_number(steps, path_group=_new_path_no,
                                       proof_no=_new_path_no,
                                       single_group=len(groups) <= 1)
            dep_count = self._write_dep_steps(tx, steps, stmt_id=stmt_id, body=body)
            written.append("dependencies")
            #: 依赖面到底建起来没有：带证明正文而一条依赖都没落 ⇒ 这一格说 `missing`
            #: （改前只有返回值里的 `deps_written=0`，而没有任何一格问过这件事 ——
            #: 真机 sylow3 七条命题、依赖全表 0 行，就是这样静默过去的）。
            out["deps_missing"] = _deps_missing_reading(
                proof_text=body.get("proof_text") or "", deps_written=dep_count,
                derived_from=body.get("derived_from") or (), stmt_id=stmt_id,
                # 这一行刚落成的那一份证明号：交付里给了号就是它（缺口 ①；canonical
                # 只有在没给号 / 给 1 时才是 #p1）。改前这里写死 1 ⇒ 第 2 份的依赖读数
                # 也记在 #p1 上（`used_by` 与证明号分家，读的人看不出错位）。
                proof_no=(requested_no if requested_no >= 1 else 1), scan=scan)
        out.update(checked=True, created=True, duplicate=False, stmt_id=stmt_id,
                   row=data, tables=written, deps_written=len(steps),
                   #: 其中"命题→命题"几条（2026-11-05 缺陷 1c：两个数分开读）。
                   deps_stmt_edges=_stmt_edge_count(steps),
                   path_groups=len(groups), pending_concepts=pending_concepts,
                   # 新建那一行的证明号：交付给了号就是它，没给才是 canonical（#p1）。
                   # 这一格不许留 0 —— 回执说 0，调用方就会去"修"它。
                   proof_no=(requested_no if requested_no >= 1 else 1),
                   proof_no_source=str(body.get("proof_no_source") or ""))
        if _is_not_applicable_kind(kind):
            # 概念/定义行的档位读数：不适用（没有证明正文）。落在这里而不是上面的
            # `judge_statement` 那一格，是因为这一支的命题正文通过了查重与同一性判定
            # （`kind="concept"` 的那一条走 `_merge_into_concept`，零模型调用），
            # 走的不是 `judge_statement` 那条路；两处落的是同一句话，
            # 唯一的口径在 `not_applicable_nontriviality`。
            out["nontriviality"] = self.not_applicable_nontriviality(
                statement_full=full, kind=kind, stmt_id=stmt_id)
        return out

    def _resolve_write_steps(self, tx: Any, body: Mapping[str, Any],
                             out: dict[str, Any], groups: list[list[dict[str, Any]]]
                             ) -> list[dict[str, Any]] | None:
        """把依赖组解析成可落盘的步骤；判不了就返回 `None`（调用方据此整笔不写）。

        从 :meth:`_record_statement_tx` 里拆出来是因为有两个调用点：
        "新建一条命题"与"并进已有命题的第 N 份证明"。两处必须用同一套判据 ——
        各写一份的形态是"两条路径对同一条悬空依赖给出两种处置"，而那种漂移没有
        任何读数会响（与 `_resolve_dep_steps` 的注释同一条理由）。

        ## 命题这一档：不可引 ⇒ 受控拒

        正文里点一个不可引的号（不在册 / 等级 < `pre_theorem`）不是"待接的
        悬空边"：「F 应该无法读到尚未在册的命题」「F 只可引用准定理级及以上的命题」
        ⇒ F 读不到它，不可能在引用它，所以这种正文只可能是这一笔写错了。
        判据与 F 的可引池、B 的登记入口同源（`depsection.citable_pool` /
        `uncitable_statement_problem`）；拒信逐字点名那个号。

        三态：`None` = 拒（命题不可引 / 显式给的依赖指着不在册的号）；列表 = 可写
        （"非命题"来源的悬空边落 `dangling` 并点名，扫不动的进 `deps_unmappable`）。

        ## 仍然保留 dangling 的只有"非命题来源"这一档

        文献 / 实验 / 文档这三种来源的号不在册时，边照旧落 `dangling` 并点名：
        它们不是"F 读不到的命题"，那条口径没有覆盖它们；把它们
        也改成整笔拒会顺手改掉 G 契约里那一档（`body["deps"]` 直给的那条路本来
        就更严：它整笔不写）。命题来源不走这条 —— 它在上面的 `blocked` 那一支就拒了。
        """
        steps, missing = _resolve_dep_steps(groups, tx)
        #: 可引判据的唯一定义在 `depsection`（与 F 的提示词清单、B 的登记入口同源）。
        from . import depsection as _DS
        try:
            ledger = [dict(r) for r in tx.rows("statements")]
        except Exception:  # noqa: BLE001 —— 读不到台账就不许判"可引"
            out.update(refused=str(_DS.REFUSED_LEVEL_UNREADABLE),
                       reason=("依赖的这一批来源要判可引，而 `statements` 读不出来 ⇒ "
                               "整笔不写：读不到台账就不许把一条引不成的号记成依赖"))
            return None
        blocked: list[dict[str, Any]] = []
        for stp in steps:
            sid = str(stp.get("source_stmt_id") or "").strip()
            if not sid:
                continue
            _code, _why = _DS.uncitable_statement_problem(
                sid, ledger, where="依赖步骤里")
            if _code:
                blocked.append({"path_group": int(stp.get("path_group") or 1),
                                "step": dict(stp), "code": _code, "why": _why})
        for m in missing:
            _stp = dict(m.get("step") or {})
            _sid = str(_stp.get("stmt_id") or "").strip()
            if not _sid or "表里没有" not in str(m.get("why") or ""):
                continue
            _code, _why = _DS.uncitable_statement_problem(
                _sid, ledger, where="依赖步骤里")
            if _code:
                blocked.append(dict(m, code=_code, why=_why))
        if blocked:
            first = blocked[0]
            out.update(refused=str(first.get("code") or ""),
                       reason=str(first.get("why") or ""),
                       unresolved=blocked)
            return None
        if missing and body.get("deps"):
            # 显式给的依赖指着不在册的号 ⇒ 整笔不写（G 那一族的契约）
            out.update(refused="unresolved_dependency",
                       reason=("依赖里有一条指着不在册的 id ⇒ 整笔不写（不许留一条挂空号的"
                               "依赖：那正是'依赖图静默少一环'的成因）"),
                       unresolved=missing)
            return None
        if not missing:
            return steps
        # 走到这里的 `missing` 只剩"非命题来源"这一类（文献 / 实验 / 文档的号不在册）：
        # 业主 §14.11 乙 的处置是"那条边落 `dangling` 并在读数里点名，不整笔拒"。
        # 命题这一档不在其中 —— 它在上面 `blocked` 那一支已经受控拒了（2026-11-06）。
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
                    {"ref": _dep_ref(stp),
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
            # 两个数各管一件事，不许混：
            #   · `proof_no` ⇒ `used_by` 的 `#pN` 尾巴（"这一条依赖出自哪一份证明正文"）
            #   · `path_group` ⇒ 那一列（"同一份证明里的第几条可选路径"，组内 AND / 组间 OR）
            # 手稿依赖段那一路两者同值（`deps_groups` 已赋同样的数）；证明正文里分段扫出来
            # 的那一路，`path_group` 1/2… 而 `proof_no` 仍是 1 —— 那是正常形态，不是错位。
            proof_no = step.get("proof_no") or body.get("proof_no") or _PL.DEFAULT_PROOF_NO
            try:
                proof_no = int(proof_no)
            except (TypeError, ValueError):
                proof_no = _PL.DEFAULT_PROOF_NO
            if proof_no < _PL.DEFAULT_PROOF_NO:
                proof_no = _PL.DEFAULT_PROOF_NO
            group_raw = step.get("path_group")
            try:
                path_group = int(group_raw) if group_raw not in (None, "") else proof_no
            except (TypeError, ValueError):
                path_group = proof_no
            if path_group < _PL.DEFAULT_PROOF_NO:
                path_group = _PL.DEFAULT_PROOF_NO
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
                path_group=path_group,
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
                if not SL.by_id(rows=tx.rows("statements"),
                                stmt_id=out["stmt_id"])["found"]:
                    out.update(refused="unknown_statement",
                               reason=(f"`statements` 里没有 {out['stmt_id']} ⇒ 这几份证明的"
                                       "依赖没有落点（清单挂不上时也没有行可挂）"))
                    return out
                steps = self._resolve_write_steps(tx, body, out, scan["groups"])
                if steps is None:
                    return out
                out["deps_written"] = self._write_dep_steps(tx, steps, stmt_id=out["stmt_id"],
                                                            body=body)
                #: 其中"命题→命题"几条（2026-11-05 缺陷 1c：两个数分开读）。
                out["deps_stmt_edges"] = _stmt_edge_count(steps)
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
                                    kind: str = "",
                                    key_only: bool = False) -> dict[str, Any] | None:
        """在册的命题里找"同一条"：命中就返回那一条（含依据与读数），否则 `None`。

        判据只有一处（`propositionkey.same_proposition`）：先比确定性键，键不同再比
        词面相似度。`key_only=True` 时只认"键相同"那一档 —— 秘书判定没查成时走的就是
        这一支（业主 2026-11-04：「词面相似度只许用于候选表排序，不许决定并」）。
        本函数只做"在哪儿找、怎么选"这两件本层的事：
        - 只在命题性的 kind 之间判（`PROPOSITION_KINDS`；定义/概念/认不出的 kind 不并，
          理由见 `PROPOSITION_KINDS`）；
        - 跳过概念行（概念不是命题，键与相似度对它没有意义）；
        - 跳过 `schema.STATEMENT_UNUSABLE_STATUSES` 里的行（被否证/被取代的行不许
          当依据用，"并进一条已经被取代的命题"等于把新证明挂在一条废行上）；
        - 多条命中时取相似度最高的、同分取号最小的（确定性：同一次登记不能因为
          行的物理顺序不同而并进不同的一条）。
        「哪一批」这一问不在这里：池过滤是 `statementledger.pool`（唯一实现，与
        `_ledger_pool` 同一处口径）。
        """
        if not _is_proposition_kind(kind):
            return None
        candidates: list[dict[str, Any]] = []
        for r in SL.pool(tx.rows("statements"), kinds=PROPOSITION_KINDS):
            sid = str(r.get("stmt_id") or "")
            other = str(r.get("statement_full") or "")
            verdict = _PK.same_proposition(full, other,
                                           threshold=self.same_proposition_jaccard)
            if str(verdict.get("state") or "") != _PK.STATE_SAME:
                continue
            if key_only and str(verdict.get("basis") or "") != _PK.BASIS_KEY:
                # 词面相似度那一档不决定并（业主 2026-11-04）：它只给候选表排序用。
                # 「设 p 是素数；则 p 是奇数」与「设 p 是奇素数；则 p 是奇数」相似度
                # 0.8889 —— 条件的强弱关系正是业主点名的不一致形态，不许并。
                continue
            candidates.append({"similarity": float(verdict.get("similarity") or 0.0),
                               "stmt_id": sid, "row": dict(r), "verdict": verdict})
        if not candidates:
            return None
        candidates.sort(key=lambda c: (-c["similarity"], str(c["stmt_id"])))
        return candidates[0]

    def _proposition_owner(self, tx: Any, full: str, *, kind: str,
                           adj: Mapping[str, Any],
                           out: dict[str, Any]) -> dict[str, Any] | None:
        """这一笔归属于哪一条在册命题（`None` = 不归任何一条 ⇒ 调用方照常新建）。

        判据只有两档，顺序固定（业主 2026-10-24 定、2026-11-04 收紧兜底）：

        | 档 | 谁说了算 | 命中 |
        |---|---|---|
        | `adjudication.checked`（秘书判成了） | 它：`same` + 点名的 `same_as` 且那一行还在/还可并 | 那一条 |
        | 没有判断面（没缝 / 开关关着） | 2026-11-04 的确定性兜底：只认「确定性键相同」这一档等价改写；词面相似度不决定并 | 键相同那一条 |

        "试过而没判成"（`attempted=True` + `checked=False`）与"判了 same 却指不到一条
        在册行"都不进这张表：它们由 `_merge_into_proposition` 按受控拒处置（2026-11-08
        业主：「没有判不了」⇒ 判不了就是没判成，不许拿它去新建一行）。

        读数全在这一处写（`adjudication` / `proposition_state` / `proposition_reason`）：
        判 different 与"没判成"都不许折成"并"，也不许把"没判成"折成"判过了、不同"。
        「这一笔带不带证明正文」不参与这个判断（2026-11-04：没有正文的重复登记也要
        判归属）—— 它只决定命中之后落成"第 N 份证明"还是"一次重复读数"。
        """
        if adj.get("checked"):
            verdict_word = str(adj.get("verdict") or "")
            out["adjudication"] = self._adjudication_reading(adj)
            out["proposition_reason"] = (str(adj.get("basis") or "")
                                         or str(adj.get("reason") or ""))
            if verdict_word != _PK.STATE_SAME:
                out["proposition_state"] = _PK.STATE_DIFFERENT
                # 判 different ⇒ 不并，这一支一个字节都不写（调用方照常新建）。
                return None
            target_id = str(adj.get("same_as") or "")
            # 与 `_same_proposition_candidate` 同一组过滤：模型点名的是判定那一刻的候选，
            # 到了事务里它可能已经被否证/被取代/改成非命题 kind —— 那时不许把新证明挂上去。
            # 定位走查口那唯一一处（`statementledger.by_id`）；「可不可并」是本层自己的
            # 判据（它读 kind 与 status 两格），两件事不混在一个函数里。
            # 这里传 `rows=`（事务快照）而不是 `tx`：锁内读失败必须照旧抛出、整笔不写，
            # 不许被查口折成「没查到这一条」。
            found = SL.by_id(rows=tx.rows("statements"), stmt_id=target_id)
            row = dict(found.get("row") or {})
            hit = ({"row": row, "stmt_id": str(row.get("stmt_id") or ""),
                    "verdict": {"state": _PK.STATE_SAME,
                                "basis": MERGED_BY_ADJUDICATION,
                                "similarity": 0.0,
                                "reason": str(adj.get("basis") or "")}}
                   if (found.get("found")
                       and _is_proposition_kind(row.get("kind"))
                       and str(row.get("status") or "")
                       not in S.STATEMENT_UNUSABLE_STATUSES) else None)
            if hit is None:
                # 判了 same、点名的号却读不到/不可并 ⇒ 这一笔判不成：不并，也不新建
                # （`_merge_into_proposition` 按受控拒处置）。
                out["proposition_state"] = ""
                out["proposition_reason"] = (
                    f"秘书判 same 并点名 stmt:{target_id or '（空）'}，而事务快照里读不到那一条"
                    "（或它的状态已不可并）⇒ 受控拒：不在一条读不到的行上写证明，"
                    "也不另建一行")
                out["adjudication"]["fail_closed"] = True
                return None
            return hit
        # ---- 没有判断面：确定性兜底
        #
        # 退回 `_same_proposition_candidate` 的"键相同或词面相似度达阈值"两档会把
        # 「设 p 是素数；则 p 是奇数」与「设 p 是奇素数；则 p 是奇数」（键不同、
        # 词面相似度 0.8889 ≥ 0.85）并成一行。而"素数 / 奇素数"正是
        # 「条件强弱关系」⇒ 语义不一致 ⇒ 不并。
        #
        # 现在的口径（两条，缺一条都不成立）：
        # - 确定性键相同 ⇒ 仍并：那是"条件与结论的等价改写 + 分句顺序 / 记号排版"
        #   （「条件只是等价改写 ⇒ 一致」正好落这一档），零模型、可复算，
        #   不是阈值判据；
        # - 词面相似度一个字节都不决定并：它只在读数里报"离阈值有多远"
        #   （`_fail_closed_reason`）。
        # 这一档必须留下读数（`adjudication.checked=False` + `fail_closed` +
        # `why_not_merged`）：「没有判断面」不许折成"查过了、不同"。
        out["adjudication"] = self._adjudication_reading(adj)
        hit = self._same_proposition_candidate(tx, full, kind=kind, key_only=True)
        if hit is None:
            why = self._fail_closed_reason(tx, full, kind=kind)
            out["proposition_state"] = ""
            out["proposition_reason"] = why
            out["adjudication"]["fail_closed"] = True
            out["adjudication"]["why_not_merged"] = why
            return None
        return hit

    def _fail_closed_reason(self, tx: Any, full: str, *, kind: str = "") -> str:
        """没查成时"为什么没并"的那句话（读数，不是判据；不改任何一格的去向）。

        为什么要有它：fail-closed 之后最常见的追问就是"它明明看起来是同一条，凭什么都
        不并"。答案必须落在返回值里 —— 而且要点名那个相似度读数（读的人才核得动
        "阈值那一档当年会不会并"），同时说清它现在只是读数、不决定并。

        相似度取自 `propositionkey.same_proposition`（判据唯一那一处），不另算一遍：
        同一个对子在两处给出不同的读数，是本仓反复登记过的缺陷形态。
        """
        head = ("没有判断面（adjudication.attempted=False：没有模型缝 / 开关关着）"
                " ⇒ fail-closed 不并：")
        if not _is_proposition_kind(kind):
            return head + f"kind={kind!r} 不是命题性的那几档，本来就不并"
        best: tuple[float, str] | None = None
        for r in SL.pool(tx.rows("statements"), kinds=PROPOSITION_KINDS):
            sid = str(r.get("stmt_id") or "")
            other = str(r.get("statement_full") or "")
            got = _PK.same_proposition(full, other, threshold=self.same_proposition_jaccard)
            score = float(got.get("similarity") or 0.0)
            if best is None or score > best[0]:
                best = (score, sid)
        threshold = float(self.same_proposition_jaccard)
        if best is None:
            return (head + "在册没有「键相同」的等价改写，而词面相似度不决定并"
                    "（这一条与在册各行都判不了 ⇒ 连相似度读数都没有）")
        score, sid = best
        reach = ("达到阈值" if score >= threshold else "未达阈值")
        return (head + f"在册 stmt:{sid} 与这一条的词面相似度 {score:.4f} {reach} "
                f"{threshold:.2f}，但词面相似度不参与判定、不决定并"
                "（词面重合不等于条件与结论一致）；确定性键不同 ⇒ 两条")

    def _proof_kind_for_existing(self, *, full: str, body: Mapping[str, Any],
                                 adjudication: Mapping[str, Any]) -> dict[str, Any]:
        """在事务外先问一次"这一份证明与在册各路径同种吗"，把结论带进事务。

        锁内不许发模型调用（硬规矩）：`record_statement` 这一笔在拿锁之前先读一次
        台账、问一次 `judge("proof_kind", …)`，事务里只落结论。适用范围与"新路径"
        同一档（`proof_path_kind="new_path"`，或同一性判定指到在册某一条）：
        - 同一份正文（sha 已在册）⇒ 不问（那是幂等重交，走"逐字同一份"那一支）；
        - 这一笔带来的是在册那一行自己的稿（同一份稿改正文）⇒ 不问（改稿不是新路径）；
        - 没有证明正文 / 没有在册行 ⇒ 不问（新命题 / 首份，没有同种可言）。
        返回 `_same_kind_hits` 的原样读数（空字典 = 这一档不问）。
        """
        from . import verifications as VR
        from . import vsigns as _VS

        proof = str(body.get("proof_text") or "")
        if not proof.strip():
            return {}
        try:
            rows = [dict(r) for r in self.store.rows("statements")]
        except Exception:  # noqa: BLE001 —— 读不到台账 ⇒ 这一问没查成（fail-closed）
            return {"checked": False, "decision": "", "same_path": 0, "hits": [],
                    "unjudged": [], "similarity": 0.0, "paths": [],
                    "reason": "statements 读不出来 ⇒ 同种证明这一问没查成"}
        if adjudication.get("checked") and str(adjudication.get("same_as") or ""):
            target = str(adjudication.get("same_as") or "")
            row = next((r for r in rows if str(r.get("stmt_id") or "") == target), None)
        else:
            hits = SL.duplicate_hits(rows, text=full)["hits"]
            row = dict(hits[0]) if hits else None
        if row is None:
            # 措辞不同的同一条命题：机械键相同的那一行也是"在册可比的那一条"
            # （判定归秘书；这里只定"跟哪一行比"，与 `_proposition_owner` 同一口径）。
            try:
                key = _PK.proposition_key(full)
                row = next((r for r in rows
                            if _PK.proposition_key(str(r.get("statement_full") or ""))
                            == key), None)
            except Exception:  # noqa: BLE001 —— 抽不出键 ⇒ 没有可比行（不猜）
                row = None
        if row is None:
            return {"checked": True, "decision": "different", "same_path": 0,
                    "similarity": 0.0, "paths": [], "hits": [], "unjudged": [],
                    "reason": ("在册没有可比的那一条命题（新命题 / 首份）"
                               "⇒ 没有同种可言，按 different 走")}
        known = {VR.text_sha(str(t)) for _no, t in VR.proof_list(row)
                 if str(t or "").strip()}
        if VR.text_sha(proof) in known:
            return {}
        manuscript = str(body.get("manuscript_path") or "")
        if manuscript:
            try:
                mid = _VS.manuscript_id_of(manuscript)
            except Exception:  # noqa: BLE001 —— 认不出稿号就当"不是同一份稿"
                mid = ""
            if mid and str(row.get("manuscript_id") or "") == str(mid):
                return {}
        return self._same_kind_hits(row, proof)

    def _same_kind_hits(self, row: Mapping[str, Any], proof: str) -> dict[str, Any]:
        """这一份新证明与在册各路径是不是同一套证法（秘书的二态语义判定）。

        判据只有一处：`self.judge("proof_kind", …)` —— 业主 2026-11-12：「对比证明方法
        后发现有很大差别（语义判别，千万别做任何机械闸，结论是二态的：一致/不同）」。
        改前这里是 `propositionkey.same_kind_proof` 的 Jaccard 阈值判定线；现在它只剩
        `similarity` 这一个材料读数（写进回执供人看），一个字节都不参与收不收。

        返回：
        - `checked`：这一问判成了没有；`False` ⇒ 调用方 fail-closed（不收录）；
        - `decision`：`same` / `different`（判成了才有）；
        - `same_path`：判 same 时它对应哪一条在册路径的 `path_group`（坏值退回第一条）；
        - `hits` / `unjudged`：与改前同形的两个列表（调用方只读这两个）；
        - `similarity`：逐路径 `propositionkey.proof_similarity` 的最大值，只作材料。
        """
        from . import verifications as VR   # 惰性：证明清单的唯一读口径

        out: dict[str, Any] = {"checked": False, "decision": "", "same_path": 0,
                               "similarity": 0.0, "paths": [], "hits": [],
                               "unjudged": [], "reason": "", "vacant_reading": {}}
        text = str(proof or "")
        if not text.strip():
            out.update(checked=True, decision="different",
                       reason="这一笔没有证明正文 ⇒ 没有同种可言")
            return out
        # ---- 「难以自证」的路径不进比较（业主 2026-11-13 裁定）------------------
        #
        # 判据只有一处（`manuscriptpaths.vacant_path_reading`）。它不是"在册没有证明"，
        # 而是"那一条的号是空号"：拿空号去跟新稿比"是不是同种"，正是业主担心的
        # 「后续正式 V 签稿被 B 秘书侧以已有证明拒」—— 一方是引文占位、一方是形式证明，
        # 语义判定却可能说"同一路"，于是整份正式稿被拒在门外。
        # 读不出来（`checked=False`）⇒ 一个号都不扣（fail-closed：按普通已有证明判）。
        from . import manuscriptpaths as _MPvac

        vac = _MPvac.vacant_path_reading(row)
        out["vacant_reading"] = dict(vac)
        vacant = [int(g) for g in (vac.get("groups") or [])] if vac.get("checked") else []
        paths = [{"path_group": int(no), "text": str(t)}
                 for no, t in VR.proof_list(row) if str(t or "").strip()
                 and int(no) not in vacant]
        out["paths"] = paths
        for one in paths:
            try:
                sim = float(_PK.proof_similarity(text, one["text"]))
            except Exception:  # noqa: BLE001 —— 相似度只是读数，算不出来不影响判定
                sim = 0.0
            out["similarity"] = max(out["similarity"], sim)
        if not paths:
            out.update(checked=True, decision="different",
                       reason=("在册各路径都处于「难以自证」状态 ⇒ 那些号是空号、"
                               "没有可比的证明正文：这一份是填上空号的那一份"
                               if vacant else "在册没有可比的证明正文 ⇒ 这是第一条路径"))
            return out
        got = dict(self.judge("proof_kind", {
            "statement_full": str(row.get("statement_full") or ""),
            "label": str(row.get("label") or ""),
            "proof_text": text,
            "proofs": paths,
        }, note="secretary:proof_kind") or {})
        out["reason"] = str(got.get("reason") or "")
        if not got.get("checked"):
            out["unjudged"] = [{"proof_no": p["path_group"],
                                "path_group": p["path_group"],
                                "reason": out["reason"] or "同种证明这一问没查成"}
                               for p in paths]
            return out
        out["checked"] = True
        out["decision"] = str(got.get("decision") or "")
        known = [p["path_group"] for p in paths]
        try:
            same_path = int(got.get("same_path") or 0)
        except (TypeError, ValueError):
            same_path = 0
        if out["decision"] == "same":
            out["same_path"] = same_path if same_path in known else known[0]
            out["hits"] = [{"proof_no": out["same_path"],
                            "similarity": out["similarity"],
                            "detail": {"material_similarity": out["similarity"]},
                            "reason": out["reason"]}]
        return out

    def _same_concept_candidate(self, tx: Any, *, label: str,
                                full: str, exclude_id: str = "") -> dict[str, Any]:
        """在册的概念行里找"同一个概念"：定义项相同就命中（确定性、零模型调用）。

        判据只有一处（`propositionkey.same_concept`：标签相同，或正文里被定义的那个
        术语相同）。本函数只做"在哪儿找、怎么选"这两件本层的事：

        - 只在概念行之间判（`CONCEPT_IDENTITY_KINDS`；命题那一套键与相似度对定义无效，
          反过来"标签相同"对命题也不是同一性判据）；
        - 跳过 `schema.STATEMENT_UNUSABLE_STATUSES` 里的行（被否证 / 被取代的概念不是
          合并的落点）；
        - 跳过 `exclude_id` 那一行（改一条既有的概念行时，它自己一定会命中自己 ——
          那一格问的是"另有一行是不是同一个概念"，把自己算进命中会把每次同步都读成
          发现了一条重复）；
        - 两侧都抽不出定义项的记成"没判成"（`checked=False`）：那不是命中，也不是"不同"，
          调用方据此受控拒（`concept_identity_unjudged`）；
        - 多条命中时取"标签那一档优先、同档取号最小"（确定性：同一次登记不能因为行的
          物理顺序不同而并进不同的一条）。

        返回 `{"hit": <命中|None>, "checked", "state", "basis", "reason", "candidates"}`：
        `hit` 是 `{"stmt_id", "row", "verdict"}`。没命中时两档分得开：
        `checked=True + state="different"`（判过了、不同 ⇒ 照旧新建）与
        `checked=False + state=""`（没判成 ⇒ 调用方受控拒，不许照旧新建）。
        """
        hits: list[dict[str, Any]] = []
        saw_different = False
        unknown_why: list[str] = []
        skip_id = str(exclude_id or "")
        for r in tx.rows("statements"):
            sid = str(r.get("stmt_id") or "")
            if not sid or not _is_concept_kind(r.get("kind")):
                continue
            if skip_id and sid == skip_id:
                continue
            if str(r.get("status") or "") in S.STATEMENT_UNUSABLE_STATUSES:
                continue
            other_label = str(r.get("label") or "")
            other_full = str(r.get("statement_full") or "")
            if not other_label.strip() and not other_full.strip():
                continue
            got = _PK.same_concept(label, full, other_label, other_full)
            state = str(got.get("state") or "")
            if state == _PK.STATE_SAME:
                hits.append({"stmt_id": sid, "row": dict(r), "verdict": got})
            elif state == _PK.STATE_DIFFERENT:
                saw_different = True
            else:
                unknown_why.append(sid)
        if hits:
            hits.sort(key=lambda h: (0 if str(h["verdict"].get("basis") or "")
                                     == _PK.BASIS_CONCEPT_LABEL else 1,
                                     str(h["stmt_id"])))
            top = hits[0]
            return {"hit": top, "checked": True, "state": _PK.STATE_SAME,
                    "basis": str(top["verdict"].get("basis") or ""),
                    "reason": str(top["verdict"].get("reason") or ""),
                    "candidates": [str(h["stmt_id"]) for h in hits]}
        if saw_different:
            return {"hit": None, "checked": True, "state": _PK.STATE_DIFFERENT, "basis": "",
                    "reason": ("在册的概念行里定义项都不一样 ⇒ 这是另一个概念，应当各建一行"
                               "（判据是定义项相同，不是词面相似）"),
                    "candidates": []}
        if unknown_why:
            keep = "；在册那几条抽不出定义项：" + "、".join(f"stmt:{sid}" for sid in unknown_why[:4])
            return {"hit": None, "checked": False, "state": "", "basis": "",
                    "reason": ("判不了 = 没判成：这一条或它在册的那几条抽不出定义项（标签是"
                               "空的，正文也不是一句「概念（X）」/「定义（X）」形态）⇒ 调用方"
                               "受控拒、不新建第二行（判不了不等于不同；这一档不发模型调用 ——"
                               "概念没有「条件 ⇒ 结论」，判词表里没有它那一格）。改法：把定义项"
                               "写出来 —— 标签写具体术语，或正文写成「概念（X）」/「定义（X）」；"
                               "若它确实与在册某一条不同，写出不同的定义项，判据会判 different "
                               "并照常新建" + keep),
                    "candidates": []}
        # 在册没有可比的概念行（0 条，或全被状态 / 排除项 / 空正文跳过）⇒ "没有同一个概念"
        # 是判得出来的：这是第一个概念，没有合并对象。不把它记成"判不了"——否则第一条
        # 概念永远登记不进来（fail-closed 会把整条路关死）。
        return {"hit": None, "checked": True, "state": _PK.STATE_DIFFERENT, "basis": "",
                "reason": ("在册没有可比的概念行（0 条 / 全被跳过）⇒ 这是第一个概念，"
                           "没有同一个概念可与它合并"),
                "candidates": []}

    def _merge_into_concept(self, tx: Any, *, body: Mapping[str, Any], full: str,
                            kind: str, out: dict[str, Any]) -> dict[str, Any] | None:
        """概念行那一档：同一个概念不许落成第二行（D2；真机 mp3-r2 的 000003 / 000004）。

        ## 为什么概念要有自己的一档
        命题那一档的判据是"条件 ⇒ 结论 一致"，而一条概念行只有一句定义 —— 它没有条件
        与结论，命题键与相似度在它上面等于失效（两条把同一个术语定义了两遍的行因此被判
        成"不同"）。真机读数：`000003` 与 `000004` 的 label 都是
        `finite-dimensional Lie algebra`，正文只差一句措辞。

        ## 判据与处置（确定性优先，模型不在这一档）
        判据是 `propositionkey.same_concept`（纯函数、零调用）：定义项相同 ⇒ 同一个概念。
        命中 ⇒ 不新建行，返回既有 `stmt_id`，读数里 `duplicate=True` +
        `matched_by="concept_label"/"concept_defined_term"`，并把依据那句原话写进
        `reason`（升档 / 补别名留给那一行，不在这一笔里静默改它的内容）。判过了、不同 ⇒
        `None`（调用方照常新建）；判不了 ⇒ 受控拒（`concept_identity_unjudged`）、整笔不写
        —— "判不了当不同"正是同一个概念落成两行的来路。

        ## 为什么这一档不发模型调用
        `adjudicate_proposition` 的判词表是"条件 ⇒ 结论"（`_judge_system` 的
        `proposition_identity` 那一格），概念没有这一组；把它交给模型既判不出什么，
        又会给真机上千条概念行各买一次调用（mp3 一个工作区就 1143 条）。确定性判得出的
        事不交给模型 —— 判不出的那一档受控拒（`concept_identity_unjudged`），
        不折成"不同"去新建第二行。
        """
        got = self._same_concept_candidate(tx, label=str(body.get("label") or ""), full=full)
        if not got.get("checked"):
            why = str(got.get("reason") or "")
            out.update(checked=False, created=False,
                       refused=CONCEPT_IDENTITY_UNJUDGED,
                       proposition_state="", proposition_reason=why,
                       reason=(why + " ⇒ 整笔不写（不新建、不合并）。"
                               "改法：把定义项写出来 —— 标签写成具体术语，或正文写成"
                               "「概念（X）」/「定义（X）」；若它确实与在册某一条不同，"
                               "把那个不同的定义项写出来再交"))
            return out
        out["proposition_state"] = str(got.get("state") or "")
        out["proposition_reason"] = str(got.get("reason") or "")
        hit = got.get("hit")
        if not hit:
            return None
        sid = str(hit.get("stmt_id") or "")
        out.update(checked=True, created=False, duplicate=True, stmt_id=sid,
                   matched_by=str(got.get("basis") or ""),
                   concept_candidates=list(got.get("candidates") or []),
                   reason=(f"同一个概念已在册（stmt:{sid}；依据："
                           f"{self._basis_text(str(got.get('basis') or ''), 0.0)}） ⇒ "
                           "不新建第二行，这一条就并到那一行上（同一概念升档 / 合并只落在"
                           "既有那一行，标签与定义都不在这一笔里静默改写）"))
        return out

    def _merge_into_proposition(self, tx: Any, body: Mapping[str, Any], *, full: str,
                                groups: list[list[dict[str, Any]]], kind: str = "",
                                force_new: bool, out: dict[str, Any],
                                adjudication: Mapping[str, Any] | None = None,
                                proof_kind: Mapping[str, Any] | None = None
                                ) -> dict[str, Any] | None:
        """
        同一命题 / 同种证明两道判断的落点。

        命中之后这一笔的去向只有这几种，每一种都如实写进 `out`：

        | 结局 | 返回里的读数 |
        |---|---|
        | 并成第 N 份证明 | `merged=True` + `merged_into` + `proof_no=N` + `matched_by` |
        | 同一条命题、但这一笔没有证明正文 | `duplicate=True` + `no_proof=True` + `stmt_id=<既有>` |
        | 同种证明、且没给 merge | `refused="proof_same_kind"` + 点名第几份 |
        | merge=True 且命中同种 | `merged=True` + `merged_same_kind=True` + `resign_required=True` |
        | 同一个概念（概念行） | `duplicate=True` + `matched_by="concept_label"` 或 `"concept_defined_term"` |
        | 判不了（试过而没判成） | `refused="same_statement_unjudged"` + `adjudication.fail_closed` + 原因 |
        | 同种证明这一问没判成 | `refused="proof_kind_unjudged"` + 点名哪几份判不了 |
        | 概念同一性没判成 | `refused="concept_identity_unjudged"` + 原因 |
        | 没命中 | `None`（调用方照常新建；这一支一个字节都不写） |

        概念行走 :meth:`_merge_into_concept`：它没有"条件 ⇒ 结论"，判据是"定义项相同"
        （`propositionkey.same_concept`，确定性、零模型调用）。

        ## 为什么落在秘书这一层

        "B 交内容、秘书实际操作增改查"：判"这两条是不是同一条定理"正是查重那一件活，
        而查重的读数必须与落盘在同一笔事务里 —— 分两处就会出现"读的时候判了同一条、
        写的时候建了新行"。
        """
        from . import verifications as VR   # 惰性：证明清单 / 签名状态的唯一读口径

        adj = dict(adjudication or {})
        # "这一笔被判成什么"的初值：判成了才有词，没判成是空串（不是某一档结论）。
        probe = _PK.judgeable(full)
        out["proposition_state"] = "" if not probe["ok"] else _PK.STATE_DIFFERENT
        out["proposition_reason"] = str(
            probe["reason"] or "没命中在册的同一条命题（判 different：条件与结论不同）")
        # ---- 判不了 = 没判成（业主 2026-11-08：「没有判不了」）-----------------------
        #
        # 位置在 `force_new` 之前：调用方明确要"另起一条"也不能替一次失败的判定说话 ——
        # 那一笔的语义仍是"还没查清这是不是同一条"，先查清再谈新建。
        missing = _proposition_judgment_missing(kind, adj)
        if missing:
            reading = self._adjudication_reading(adj)
            reading["fail_closed"] = True
            reading["why_not_merged"] = missing
            out.update(checked=False, refused=R.SAME_STATEMENT_UNJUDGED,
                       proposition_state="", proposition_reason=missing,
                       reason=missing, adjudication=reading)
            return out
        if force_new:
            # 调用方明确要"另起一条" ⇒ 不并（`force_new` 的含义就是不许替它合并）。
            out["proposition_reason"] = "force_new：调用方明确要另起一条，跳过同一性合并"
            return None
        if _is_concept_kind(kind):
            # ---- 概念行那一档（D2）：判据是"定义项相同"，与命题那一套不是同一件事。
            # 位置必须在这里：下面那条"没有证明正文就不并"会把概念行直接放过
            # （概念不参与等级链、本来就没有证明），而"同一概念登记两行"正是从那个
            # 缺口漏出来的（真机 mp3-r2 的 000003 / 000004）。
            return self._merge_into_concept(tx, body=body, full=full, kind=kind, out=out)
        if not _is_proposition_kind(kind):
            # 一条定义/概念不是命题："表述几乎相同的两条命题是同一个"这句话对它不成立。
            out["proposition_reason"] = (
                f"kind={kind!r} 不在命题性的那几档 {list(PROPOSITION_KINDS)} 里 ⇒ "
                "不参与同一命题判定（不并）")
            return None
        proof = str(body.get("proof_text") or "")
        # ---- 归属判断（"这一笔是不是在册某一条命题的又一次登记"）只在这一处判 ------
        #
        # 带不带证明正文都先问这一句（2026-11-04 业主裁定）：改前"没有证明正文"在下面
        # 直接返回 None，于是同一命题换一种写法、两次都没带证明时会落第二行 —— 而它
        # 并不产生第二份证明，也没有任何读数说"这是同一条"。
        hit = self._proposition_owner(tx, full, kind=kind, adj=adj, out=out)
        if (hit is None and adj.get("checked")
                and str(adj.get("verdict") or "") == _PK.STATE_SAME):
            # 判了 same、点名的号却在事务快照里读不到/不可并 ⇒ 这一笔判不成：
            # 受控拒（不新建、不合并），不拿"读不到那一条"冒充"不是同一条"。
            why = str(out.get("proposition_reason") or "") or (
                "秘书判 same 却指不到一条可并的在册行 ⇒ 受控拒：不新建、不合并")
            reading = self._adjudication_reading(adj)
            reading["fail_closed"] = True
            reading["why_not_merged"] = why
            out.update(checked=False, refused=R.SAME_STATEMENT_UNJUDGED,
                       proposition_state="", proposition_reason=why,
                       reason=why, adjudication=reading)
            return out
        if not proof.strip():
            if hit is None:
                out["proposition_reason"] = (
                    str(out.get("proposition_reason") or "")
                    + "；这一笔没有带证明正文 ⇒ 不进「第 N 份证明」那一支，"
                    "但归属判断已经做过：没命中 ⇒ 照常新建一行")
                return None
            sid = str(hit["stmt_id"])
            basis = str(dict(hit.get("verdict") or {}).get("basis") or "")
            out["proposition_state"] = _PK.STATE_SAME
            out["proposition_reason"] = str(dict(hit.get("verdict") or {}).get("reason") or "")
            out.update(checked=True, created=False, duplicate=True, stmt_id=sid,
                       matched_by=basis, no_proof=True,
                       reason=(f"同一条命题已在册（stmt:{sid}；依据："
                               f"{self._basis_text(basis, 0.0)}）⇒ 不新建第二行；"
                               "这一笔没有带证明正文，所以也不产生第 N 份证明"
                               "（没有正文的重复登记是一次重复读数，不是第 2 份证明）"))
            return out
        if hit is None:
            return None
        row = dict(hit["row"])
        sid = str(hit["stmt_id"])
        verdict = dict(hit["verdict"])
        out["proposition_state"] = _PK.STATE_SAME
        out["proposition_reason"] = str(verdict.get("reason") or "")
        basis = str(verdict.get("basis") or "")
        similarity = float(verdict.get("similarity") or 0.0)
        # ---- 「难以自证」的空号 ⇒ 整条替换（业主 2026-11-13 裁定）----------------
        #
        # 位置在"同种证明 / 合并"这两个问题之前：空号上的那一份正文不是"已有证明"，
        # 拿它去判"同种"正是业主担心的拒收（见 `_same_kind_hits` 那一格）。
        # 返回 False ⇒ 这一行没有空号（或这一笔不是替换）⇒ 下面逐字照旧。
        if self._fill_vacant_path_if_any(
                tx, sid=sid, proof_text=proof, groups=groups, out=out,
                manuscript=str(body.get("manuscript_path") or "")):
            return out
        # 同种证明这一问在事务外已经问过（锁内不许发模型）：这里只读结论。
        # `proof_kind` 为空 = 这一笔没有在册可比的证明（新命题 / 首份）⇒ 不是同种。
        kind_got = dict(proof_kind or {})
        kind_hits, unjudged_proofs = (list(kind_got.get("hits") or []),
                                      list(kind_got.get("unjudged") or []))
        merge = body.get("merge") is True
        existing = VR.proof_list(row)
        # ---- 同一份正文再交一次：不新增证明号，也不算「同种证明」（2026-11-02） ------
        #
        # 真机读数（projects/paper-rewrite-85/sessions/20261102.jsonl:2980，22:03:20）：
        # B 为了把 proof_no 落成 1，拿同一份正文（8454 字、与在册 canonical 逐字同源）
        # 以 proofs=[{proof_no:1,…}] 重交 ⇒ _same_kind_hits 拿它与在册 #1 比，
        # 相似度 1.0000 >= 0.80 ⇒ 整笔 proof_same_kind 拒。那不是"两种同门证法被并列
        # 记录"，而是同一条记录再交一次 —— 判据在这里分不开的代价是：B 再也不敢交
        # 带证明的那一笔（proofs=0 的绕行就是这么来的）。
        #
        # 判据取原样 sha（verifications.text_sha，"逐字同一份"），不比相似度：
        # "逐字同一份"是确定性的事实，不需要阈值。命中 ⇒ 一个字节都不写（那一份已经在册），
        # 回执说清"就是第几份"，调用方据此收工。
        same_sha = VR.text_sha(proof)
        same_text_no = next(
            (int(no) for no, text in existing
             if str(text or "").strip() and VR.text_sha(str(text)) == same_sha), 0)
        if same_text_no and not merge:
            out.update(checked=True, created=False, duplicate=False, merged=True,
                       merged_into=sid, stmt_id=sid, proof_no=int(same_text_no),
                       matched_by=basis, similarity=similarity, same_kind=[],
                       canonical_written=False,
                       reason=(f"这一份正文与 stmt:{sid} 的第 #{int(same_text_no)} 份证明"
                               "逐字相同（sha 一致）⇒ 不新增证明号、也不算「同种证明」："
                               "同一条记录再交一次不是第二种证法。盘上一个字节都没动"
                               "（那一份已在册）；要换这一份的正文就把新正文交上来"
                               "（proof_text 或 proofs 里那一号），旧正文会进 proof_history，"
                               "并请 V 对新正文重签（resign_required）"))
            return out
        # ---- 同种证明这一问没判成：不许折成"不同"照旧新增证明号（2026-11-08）------
        #
        # 位置：在"逐字同一份"那一档之后（那是确定性事实、不需要判定），merge 之前
        # （合并要落到具体哪一份，判不了就不许猜）。判不了不等于不同 —— 折成不同就会
        # 新增证明号，同一种证法被并列记录，正是这一轴要防的形态。
        if unjudged_proofs:
            names = "、".join(f"第 {int(h['proof_no'])} 条路径" for h in unjudged_proofs)
            out.update(checked=False, created=False, duplicate=False, merged=False,
                       refused=PROOF_KIND_UNJUDGED, stmt_id=sid, merged_into=sid,
                       matched_by=basis, similarity=similarity, same_kind=[],
                       unjudged_proofs=list(unjudged_proofs),
                       reason=(f"这一份证明与 stmt:{sid} 的 {names} 没判成是不是同种"
                               "（没判成 ≠ 不同）⇒ 不收录、不新增路径：折成不同，同一套"
                               "证法会被并列记录。这一档只在判定面没给出可用结论时出现"
                               "（超时 / 坏 JSON / 没给可用答案）。改法：重交这一份，"
                               "或换一条真正不同的证法再交"))
            return out
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
            # 合并稿也是"要进 statements.proof_text 的正文"：落到哪一条在册行已经由
            # 同一性判定给出（`sid`），这里用同一个闸判一次 —— 不满足 ⇒ 整笔不写。
            _mgate = proof_text_manuscript_sign_gate(
                self.store, statement_id=sid, proof_text=proof,
                proof_no=int(target), origin=str(body.get("origin") or ""),
                source_lit_id=str(body.get("source_lit_id") or ""))
            out["proof_text_gate"] = dict(_mgate)
            if _mgate.get("refused"):
                out.update(checked=False, created=False, duplicate=False, merged=False,
                           refused=str(_mgate.get("refused") or ""),
                           reason=str(_mgate.get("reason") or ""))
                return out
            return self._merge_same_kind_version(tx, row=row, sid=sid, full=full,
                                                 proof_no=int(target), merged_text=proof,
                                                 verdict=verdict, kind_hits=kind_hits,
                                                 merge_note=how, out=out,
                                                 body=body, groups=groups)
        # ---- 同种证明：不新增证明号
        if kind_hits:
            top = kind_hits[0]
            path_no = int(top["proof_no"])
            _sim = float(top.get("similarity") or 0.0)
            out.update(checked=False, created=False, duplicate=False, merged=False,
                       refused=PROOF_SAME_KIND, stmt_id=sid, merged_into=sid,
                       matched_by=basis, similarity=similarity, proof_no=0,
                       same_kind=kind_hits,
                       #: 相似度只作材料读数（不参与收不收）：人看得见"机械读数长什么样"。
                       same_kind_material={"similarity": _sim},
                       reason=(f"这一份证明与 stmt:{sid} 的第 {path_no} 条路径同种"
                               "（秘书的语义判定：两套证法是同一路，不是两条独立路径）"
                               "⇒ 不收录、不新增路径（并列记录会让一条定理看起来有好几条"
                               "独立证法）。材料读数（只作参考，不作判据）：相似度 "
                               f"{_sim:.4f}。两条处置：① 换一条真正不同的证法再交；"
                               "② 这一份不再提交 —— 同一套证法在册已经有一份。"
                               "参数面没有「合并到第几条路径 / 改号」这一类键："
                               "同种证法的正文修订由人看过稿之后处理"))
            return out
        # ---- 落成第 N 份证明（或 canonical 那一格还是空的时候的 #p1）
        #
        # 号由秘书在这一笔事务里分配（`assign_path_group`）：同一命题已有 N 条路径
        # ⇒ 这一份排 N+1；同一份正文 sha 重复收录 ⇒ 沿用原号（上一格"逐字同一份"
        # 已经处理了那条路，走到这里的一定是新的正文）。分配必须在锁里，理由见
        # `_assign_path_group_in_tx`。
        #
        # 交付里写的号（`body["proof_no"]`，改前从稿头 `- 证明号：` / 携带单读来）
        # 不再采信：产出侧不写那个号了，留着它当权威就是第二套口径。给了就只
        # 记读数（`proof_no_ignored`），号仍由分配给出。
        canonical_was_empty = not VR.proof_text_of(row, 1).strip()
        try:
            requested_no = int(body.get("proof_no") or 0)
        except (TypeError, ValueError):
            requested_no = 0
        if requested_no >= 1:
            out["proof_no_ignored"] = {
                "given": requested_no,
                "why": ("证明号由秘书按路径面分配（`assign_path_group`）⇒ 交付里写的"
                        "这个数一个字节都不采信；回执里的 `proof_no` 才是这一份的号"),
            }
        if canonical_was_empty:
            # 先登记命题、后补证明：这一份填 canonical 那一格（#p1），不新增路径。
            _alloc = _assign_path_group_in_tx(
                tx, root=self.root, statement_id=sid,
                manuscript=str(body.get("manuscript_path") or ""),
                body_sha=VR.text_sha(proof))
            if not _alloc.get("checked"):
                out.update(checked=False, created=False, duplicate=False, merged=False,
                           refused="path_group_unreadable",
                           reason=("路径数读不出来 ⇒ 这一份的正文不落（不猜第几条）："
                                   + str(_alloc.get("why") or "未知原因")))
                return out
            proof_no = 1
            out["path_group"] = 1
            out["path_group_reading"] = dict(_alloc, path_group=1)
            row["proof_text"] = proof
        else:
            _alloc = _assign_path_group_in_tx(
                tx, root=self.root, statement_id=sid,
                manuscript=str(body.get("manuscript_path") or ""),
                body_sha=VR.text_sha(proof))
            if not _alloc.get("checked"):
                out.update(checked=False, created=False, duplicate=False, merged=False,
                           refused="path_group_unreadable",
                           reason=("路径数读不出来 ⇒ 这一份不并、不新增证明号（不猜第几条）："
                                   + str(_alloc.get("why") or "未知原因")))
                return out
            proof_no = int(_alloc.get("path_group") or 1)
            out["path_group"] = proof_no
            out["path_group_reading"] = dict(_alloc)
            listed = [dict(p) if isinstance(p, Mapping) else p
                      for p in (row.get(VR.PROOFS_KEY) or [])]
            listed.append({"proof_no": proof_no, "text": proof,
                           "created_at": S.now_iso()})
            row[VR.PROOFS_KEY] = listed
        _note_path_material(out, _path_material_numbers(groups)
                            if len(groups) <= 1 else [], decided=proof_no)
        written = ["statements"]
        # ---- 洗定理名 + 路线进证明层（「路线写在证明这一层」）。
        #
        # 这一笔的 label 已经被洗成 `canonical_name`（见 `_record_statement_tx`），但并进去之后
        # label 用的是那条在册行的。所以这里两件都要做：
        # ① 在册那一条的名字如果与洗过的名字不同 ⇒ 顺手把它洗掉（第一条带着
        #    "（路线一：…）"落了盘，后来的两份证明并进来时把它洗净）；
        # ② 这一笔自己的路线说明落到"第 N 份证明"上（`PROOF_ROUTES_KEY`），不丢。
        route = str(adj.get("route") or "").strip() if adj.get("checked") else ""
        canonical = str(adj.get("canonical_name") or "").strip() if adj.get("checked") else ""
        if canonical and str(row.get("label") or "") != canonical:
            old_label = str(row.get("label") or "")
            # 只在"在册那个名字是本名加修饰"时洗（`Sylow 三定理（路线一：…）` ⇒ `Sylow 三定理`）。
            # 两个都干净、却不完全同名的（`Sylow 三定理` 与 `Sylow 定理`）不动它：名字不参与
            # 同一性判定（「不看名称」），先落盘的那个名字赢 —— 否则每并一份证明就改名
            # 一次，而"这一条现在叫什么"会跟着最后一次提交漂。
            if canonical in old_label:
                out["label_washed"] = {"from": old_label, "to": canonical,
                                       "class": LABEL_WASH_ROUTE, "stmt_id": sid,
                                       "why": ("在册那一行标签里的路线 / 自证草稿 / 待 V 审签"
                                               "那一类修饰被洗掉了；被洗掉的路线落进这一份"
                                               "证明的路线说明里，不丢")}
                row["label"] = canonical
        # ---- 在册那一行的名字如果是内部工作名，并这一笔时顺手洗掉（修名那一半）。
        # 为什么修名放在这一支：要修的正是在册那一行，而它与"这一笔的 label"无关。
        # 判据与新建那一支同一处
        # （`wash_working_name`），所以两处不会给出两个洗法；这一支只动 label，不动内容。
        working = wash_working_name(row.get("label"), kind=str(row.get("kind") or ""),
                                    stmt_id=sid,
                                    statement_full=str(row.get("statement_full") or ""))
        if working:
            out["label_washed"] = dict(working, stmt_id=sid)
            row["label"] = str(working["to"])
            out["canonical_name"] = str(working["to"])
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
        # 这一份的路径号由秘书刚分配（见上）：手稿依赖段那一路的 `used_by` 尾巴与
        # `path_group` 都从它来；证明正文里分段扫出来的那一路 `path_group` 保留段落
        # 下标（一份证明里的几条可选路径，不是几份证明）。
        steps = _stamp_path_number(steps, path_group=proof_no, proof_no=proof_no,
                                   single_group=len(groups) <= 1)
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
                   #: 这个号是秘书按路径面分配的（唯一来源 `assign_path_group`）。
                   proof_no_source="path_group",
                   matched_by=basis, similarity=similarity, same_kind=[],
                   tables=written, row=row, deps_written=deps_written,
                   #: 其中"命题→命题"几条（2026-11-05 缺陷 1c：两个数分开读）。
                   deps_stmt_edges=_stmt_edge_count(steps),
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
        word = str(basis)
        if word == _PK.BASIS_KEY:
            return "proposition_key 相同"
        if word == MERGED_BY_ADJUDICATION:
            return "秘书判的（条件与结论一致）"
        if word == _PK.BASIS_CONCEPT_LABEL:
            return "定义项（标签）规范化后相同"
        if word == _PK.BASIS_CONCEPT_TERM:
            return "正文里被定义的术语相同"
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
                                 out: dict[str, Any],
                                 body: Mapping[str, Any] | None = None,
                                 groups: list[list[dict[str, Any]]] | None = None
                                 ) -> dict[str, Any]:
        """`merge=True` 那一档：把合并稿作为"那一份证明的新版本"，并要求 V 重签。

        ## 写什么
        - 被命中的那一份（第 k 份）的正文换成调用方交来的合并稿：k=1 时是行上的
          `proof_text`（canonical 那一格），k>1 时是 `proofs` 清单里的那一条；
        - 旧正文整段留痕：进 `proof_history`，元素形状与 canonical 覆盖那一支逐字相同
          （`{text, sha, at, replaced_by}`）再加一格 `proof_no` —— 否则一条命题有多份
          证明时，"这一版是哪一份的旧稿"读不出来；
        - 合并痕迹那一格记下这一笔合并了哪几份、相似度、谁做的。有界，只留最近 20 条。

        ## 为什么"合并"与"直接覆盖"必须分开（业主原话：重拿 V 签）
        直接覆盖只是改稿（`stale` 是读数）；合并是"两份同种证明合成一份"，它的正确性
        依赖 V 重新看过合并稿。所以这里不动 `bits`、也不写任何"审过了"的凭据，
        返回值里 `resign_required=True` 且把 V 的现行状态如实报出来（`proof_standing`）：
        合并稿与旧签的 sha 不同 ⇒ `review_standing` 现算是 `stale`，`reviewed` 是 False，
        "未重签之前不算成立"这句话由读侧现算，而不是由本函数说一句"已成立"。
        """
        from . import verifications as VR   # 惰性：签名状态与正文 sha 的唯一读口径

        old_text = VR.proof_text_of(row, proof_no)
        entry = {"text": old_text, "sha": _PR.proof_sha(old_text), "at": S.now_iso(),
                 "replaced_by": _PR.proof_sha(merged_text), "proof_no": int(proof_no)}
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
        # ---- 2026-11-04（业主裁定）：合并稿的依赖边与正文同一次事务落盘 ----------
        #
        # 改前这一支不写依赖：`_merge_into_proposition` 收到的 `groups` 在这一支里被整份
        # 丢掉，盘上留下的是旧正文的依赖边 —— 而 `proof_text` 已经换成合并稿，"这一条
        # 证明依赖什么"与"它的正文"从此各说一件事，且没有任何读数会说它们分家了。
        # 判据与"新建 / 第 N 份证明"那两支共用 `_resolve_write_steps` + `_write_dep_steps`：
        # 显式 `deps` 指着不在册的号 ⇒ 整笔不写；扫出来的引用照旧落 `dangling` / 点名。
        # 旧边不删（它们可能仍被合并稿用到）：这一笔只追加，`used_by` 落到同一个证明号。
        body_for_deps = dict(body or {})
        body_for_deps["proof_no"] = int(proof_no)
        steps = self._resolve_write_steps(tx, body_for_deps, out,
                                          [list(g) for g in (groups or [])])
        if steps is None:
            return out
        deps_written = self._write_dep_steps(tx, steps, stmt_id=sid, body=body_for_deps)
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
                   same_kind=kind_hits,
                   tables=(["statements", "dependencies"] if deps_written else ["statements"]),
                   deps_written=deps_written,
                   #: 其中"命题→命题"几条（2026-11-05 缺陷 1c：两个数分开读）。
                   deps_stmt_edges=_stmt_edge_count(steps),
                   row=row, canonical_written=int(proof_no) == 1,
                   proof_history=list(row["proof_history"]),
                   proof_standing=standing, resign_required=True,
                   reviewed=state == "signed",
                   reason=(f"合并稿已作为 stmt:{sid} 第 {proof_no} 份证明的新版本落盘"
                           f"（{merge_note}；旧正文整段进 `proof_history`，sha 可与签名"
                           "台账的 `proof_sha256` 直接对上）；这一笔的依赖边同时落进 "
                           f"`dependencies`（{deps_written} 条，`used_by=\"stmt:{sid}#p{proof_no}\"`，"
                           "旧边不删）；这一笔是同种证明合成一份，"
                           f"按业主口径要 V 重签 —— 现行签名状态是 `{state}`，"
                           "未重签之前不算成立（读侧现算，不由本函数声明）"))
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

            判据（`tests/test_intake_actions.py`）落的是归一化区间，而 `_normalize_range`
            就是那个唯一实现 —— 所以走 `_rng`。判据比注释权威；"注释与判据对不上"
            这件事该单独记一笔，不该顺手改掉任何一边。
            """
            return _rng(key)

        origin = _s("origin") or "external_lit"
        reason = _s("quote_reason")
        if not reason.strip() and body.get("quote_verified") is not True:
            # B 只交"定理内容 + 证明过程"，别的一概不要求它给。
            # 而 `Statement.validate` 的硬要求是"不是 True 就必须写 quote_reason" ——
            # 不给一个受控的默认值，那份两件式契约对自产命题（`own_result`）在结构上
            # 就不成立（整笔会以 `quote_verified=None 时必须写 quote_reason` 被拒）。
            # 这里填的是为什么这一格是空的，不是编一个"已核对"的结论：
            # 回验要做的是拿另一份文本逐字比，而自产命题没有第二份文本可比。
            # 调用方给了就照用（不覆盖）。
            reason = ("own_result（我们自己证的）：逐字回验这一格不适用（没有第二份文本可比）—— "
                      "证明过程在 proof_text 里，采信与否由审校（H）与验证（V）那一档判")
        return S.Statement(
            stmt_id=stmt_id, origin=origin, kind=kind,
            label=_s("label"),
            # ---- 正文只有一个真身，短版是派生值。
            #
            # 同一份正文两个字段、一个空一个满，读侧读哪个都能给出另一种答案。真身定在
            # `statement_full`（schema 对它才是硬要求、下游都靠它），短版在这里由它
            # 派生（逐字复制，不截断：截断出来的"短版"是另一条命题）。派生规则只有
            # 这一处实现（`statementbody.derive_text`），读侧的唯一入口是
            # `statementbody.body_of`。
            statement_text=_SB.derive_text(full, _s("statement_text")),
            statement_full=full,
            proof_text=_s("proof_text"), source_lit_id=_s("source_lit_id") or None,
            page_range=_rng("page_range"), quote_verified=body.get("quote_verified"),
            quote_reason=reason,
            # ---- 回验的三栏证据必须能过这一层。
            #
            # 只被 `STATEMENT_PARAM_KEYS` 收下、却没搬进 `Statement` 就会被静默丢掉：
            # H 的语义判定给了 `quote_span` 与调用指纹而盘上两栏全空，
            # `schema._normalize_quote_mode` 就会把"只说了通过"的行记实成 `verbatim`
            # —— 于是"逐字回验通过"这句话在盘上没有任何读数。
            # 这里只搬，不判：缺证据那一档由 `quoteevidence.enforce_quote_evidence`
            # 在写库前处理（`register_statement` 的写侧断言），读侧判据是
            # `quoteevidence.scan_quote_evidence`。
            quote_mode=_s("quote_mode"), quote_span=_s("quote_span"),
            quote_call_sha256=_s("quote_call_sha256"),
            evidence_kind=_s("evidence_kind") or "heuristic", status="active",
            derived_from=S.sorted_unique([str(x) for x in (body.get("derived_from") or [])]),
            aliases=[str(a) for a in (body.get("aliases") or []) if str(a).strip()],
            # `line_range` 是字符串（"120-148"），不是 `PageRange` —— 走 `_rng(...)` 会让
            # 落盘那一格是一个 `{start/end/label}` 的字典（`Statement` 的声明是 `str`）。
            # 判据抓不到它（`to_dict` 照抄、`verify` 不查那一格），但下游按"行范围"
            # 读它的人会拿到一个字典。
            doc_id=_s("doc_id") or None, line_range=_lines("line_range"),
            # ---- `bits` 必须 10 键齐、没有 None -------------
            #
            # `dict(body.get("bits") or {})` 在调用方没交 `bits` 时落盘的就是 `{}`，而
            # `bits_shape_problems({})` 返回 `[]`（空表被当成"没有形状问题"）⇒ 一条
            # 整块没填 `bits` 的行照样过闸。现在"缺就现算、算不齐就拒"，
            # 判据见 `_complete_statement_bits`。
            bits=_complete_statement_bits(body, kind=kind, origin=origin),
            created_at=S.now_iso(),
            created_by=f"secretary-{self.role}")

    # ------------------------------------------------------------ 面适配（S1g-2）
    def surface_fit(self, *, action: str, params: Mapping[str, Any],
                    face: str = "", base: str = "") -> dict[str, Any]:
        """这件活落在被派人的读写面里做不做得成（三态读数，只报不改）。

        「"超越职责"的一个主要可能是无法在被分配的读写面内完成任务，这个秘书也要帮忙看，
        不只是看任务是否符合角色设计」。
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
        ## 为什么只报不改：路径值是内容面：把它改写成另一条路径 = 替父决定"这件事
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
        given = params or {}
        rows: list[dict[str, Any]] = []
        # 判定与坏路径名单同趟收：原先 rows 建好后再扫两遍（verdicts 一遍、bad 一遍）。
        verdicts: set[str] = set()
        bad: list[dict[str, Any]] = []
        for key in names:
            raw = given.get(key)
            if not isinstance(raw, str) or not raw.strip():
                continue                       # 没给这一格 ⇒ 没有可判的路径（如实记在 reason 里）
            row = self._judge_one_path(key, raw.strip(), root=root, face_dir=face_dir)
            verdict = str(row.get("verdict") or "")
            rows.append(row)
            verdicts.add(verdict)
            if verdict in ("escapes", "not_in_face"):
                bad.append(row)
        if not rows:
            out.update(checked=True,
                       reason=f"{action} 这一件没给路径参数（{'/'.join(names)}）⇒ 判不了"
                              "（不是通过）")
            return out
        fits: bool | None
        if verdicts & {"escapes", "not_in_face"}:
            fits = False
        elif verdicts == {"in_face"}:
            fits = True
        else:
            fits = None                        # 全是 unknown ⇒ 判不了（三态不许折平）
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
                raw_params = payload.get("params")
                got = self.surface_fit(action=action,
                                       params=(raw_params
                                               if isinstance(raw_params, Mapping) else {}),
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
                # 汇总与两张名单同趟收（原先同一批 items 扫四遍）：有 False ⇒ False；
                # 非空且没有"不是 True" ⇒ True；其余 ⇒ None —— 三态照旧保留。
                bad: list[dict[str, Any]] = []
                reach_bad: list[dict[str, Any]] = []
                saw_false = saw_not_true = False
                for i, item in enumerate(targets):
                    sub = item if isinstance(item, Mapping) else {}
                    action = str(sub.get("action") or "")
                    raw_params = sub.get("params")
                    fit = self.surface_fit(
                        action=action,
                        params=(raw_params if isinstance(raw_params, Mapping) else {}),
                        face=face, base=base)
                    reach = reach_fit(str(sub.get("role") or ""), action)
                    row = {"index": i, **fit, "reach": reach}
                    items.append(row)
                    if fit.get("fits") is False:
                        saw_false = True
                        bad.append(row)
                    elif fit.get("fits") is not True:
                        saw_not_true = True
                    # 能力面那一维的汇总：哪几项在"被派人 + 它出边上的伙伴"里没人做得到
                    if (reach or {}).get("verdict") == "unreachable":
                        reach_bad.append(row)
                fits: bool | None
                if saw_false:
                    fits = False
                elif items and not saw_not_true:
                    fits = True
                else:
                    fits = None
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

    @_roster_guarded
    def roster_repair(self, *, owner: str) -> tuple[int, str, list[str]]:
        """补登记（自愈）：把"台账里有、名册里没有"的代理行补上。

        返回 `(补了几条, 问题, 因为"在飞"而跳过的号)`。第三格是号清单而不是计数：
        "因为还没登记所以不补"必须在读数上看得见，否则它下次真变成"该补没补"时，
        没有任何入口能查出是哪个号、为什么被跳过。

        只在写路径被调用（查只报不修）。补的时候按 `task_id` 升序，整段（读历史 → 判 →
        两笔 append）在 `_roster_section` 的 per-owner 临界区里，于是两个并发修复既不会
        重复分配、也不会各补一行；名字在锁内由 `next_name` 按已用最大序号推。

        ## 在飞集合：分得清"还没登记"与"从没登记"

        兄弟行竞态的形态：A 已落台账行、还没走到自己的 `roster_add`，B 在登记之后跑本方法，
        把 A 当成漏行补了名；A 随后自己的登记撞 `task_id_reused`。`_roster_section` 只串行化
        "写名册"，串行化不了"台账行已落、名册还没落"这个窗口 ⇒ `todo` 再并上
        :func:`roster_pending`。

        读序是判据的一部分：必须先读 `cond._tasks()`、后读在飞集合 —— 标记在 `tasks`
        事务提交之前落进集合，"看得见那一行"的读者之后一定看得见标记；两处一对调这条保证
        就没了，而所有正题仍会是绿的（负控钉在
        `tests/test_sibling_registration_race_is_not_backfilled.py`）。

        ## 只补"该有名字"的号（判据是"没跑过的号"，不是"被拒过的号"）

        ① 派活闸拒掉的号（`outcome="refused"`）：永远不补 —— 补了就是 phantom 名册项；
        ② 名册写口拒过的号（`refusals/<父>.jsonl` 有记录）：只有"真跑过"时才补。
           "这次派活被拒"与"这次名册登记被拒"是两件事，后者是部分拒绝
           （派活成功、子代理真跑、只有名字没落）；
        ③ 从没被拒过的孤儿（实例分派 / 队列入账 / 更早的形态）：老口径照补 —— 不许因为
           ② 的改动把它一起关掉。这一档只由 `roster_pending` 挡在飞、不要求 `ended_at`：
           一条 `running` 却没有结束时刻的行是"不知道跑没跑"，而"父按名销不掉它"
           （整棵树收不了工）比"补了一个可能没跑完的号"更不可逆。

        "真跑过"的判据不另写一份：就是模块级的 :func:`ran_but_unnamed`（收工门与网页那一格
        用的是同一个函数），用同一份 `status` / `outcome` / `ended_at` 三格。

        ## 补名之后的留痕

        add 行多三格：`named_after_run`（是不是跑过之后才补的名）、`requested_name`
        （它当初点名要的那个，原样保留 —— 那是"它曾经想叫 E2"的记录）、`refusal_code`
        （哪一档拒的）。名册是 JSONL、没有 schema 契约，加键不改旧键。回执逐条说清
        "你点的 E2 被拒，它叫 E4"；`self.last_repair_named` 是这两处读的同一份读数。
        """
        cond = self._conductor()
        if cond is None:
            return 0, "没有 store ⇒ 读不到台账，补不了", []
        self.last_repair_named = []
        try:
            rows = [r for r in cond._tasks()
                    if r.get("parent_task_id") == owner and not str(r.get("kind") or "")]
        except Exception as exc:  # noqa: BLE001
            return 0, f"台账读不成（{type(exc).__name__}: {exc}）", []
        # 已知集 = 全部 `add` 行 ∪ 全部 `bind` 行的 task_id 并集。
        # 读 `roster_index` 的折叠视图不行：一个名字接过第二件活之后，第一件活从
        # `known` 里消失 ⇒ 自愈把已经登记过的行再补一次（零并发可复现）。
        known, bad = self._roster_history(owner)
        if bad:
            return 0, f"名册/对照表有 {len(bad)} 行读不出来 ⇒ 不补（免得重名）", []
        refused, bad_ref = self._refused_task_ids(owner)
        if bad_ref:
            return 0, f"拒绝流水有 {len(bad_ref)} 行读不出来 ⇒ 不补（免得把被拒的号补成新名字）", []
        # 拒绝流水里的那几格（`requested_name` / `refusal_code`）：只用来给补出来的 add 行
        # 留痕，不参与判据（判据读的是 `_refused_task_ids` 那份号集合，同一个文件）。
        asked_of: dict[str, dict[str, Any]] = {}
        try:
            for item in (registration_refusals(self.root, owner=owner).get("items") or []):
                rtid = str(item.get("task_id") or "")
                if rtid:
                    asked_of[rtid] = item
        except Exception:  # noqa: BLE001 —— 读不成只是少两格留痕（判据已由 bad_ref 先把过）
            asked_of = {}
        # 在飞集合：读序在 `cond._tasks()` 之后（见 docstring，判据钉着这一条）。
        pending = roster_pending(self.root, owner)
        cand: list[str] = []
        for r in rows:
            tid = str(r.get("task_id") or "")
            if not tid or tid in known:
                continue
            # ① 闸拒的号：永远不补（1cdacbf6，一字不动）。
            if str(r.get("outcome") or "") == "refused":
                continue
            # ② 写口拒过的号：只有真跑过才补（丁）；没跑过的照样不补（d9ebb7fe 的实质）。
            if tid in refused and not ran_but_unnamed(r, frozenset()):
                continue
            cand.append(tid)
        skipped = sorted(tid for tid in cand if tid in pending)
        todo = sorted(tid for tid in cand if tid not in pending)
        fixed = 0
        for tid in todo:
            row = next((r for r in rows if str(r.get("task_id") or "") == tid), {})
            role = str(row.get("role") or "")
            ran = ran_but_unnamed(row, frozenset())
            asked = asked_of.get(tid) or {}
            want_name = str(asked.get("requested_name") or "")
            refusal_code = str(asked.get("refusal_code") or "")
            name, problem = self.next_name(owner, role)
            # 死分支·契约出口：与 `_roster_add` 里那一支是同一件事（`next_name` 今天恒返回
            # 空问题串）。两处必须成对：删/留都一起改，并同步
            # `tests/test_no_dead_branch_on_a_field_that_is_always_empty.py` 的登记表。
            if problem:
                return fixed, problem, skipped
            # 补出来的行也要有面（`draft/158` 二-2 的副作用）：正常 add 行走 `surface_alloc`，
            # 补登记此前不带 `surface` ⇒ 81 那 13 条补登记行 13/13 无面，正常行 52/52
            # 有面；于是那 6 个真跑过的子代理在 `surface_of` 里读到空槽、一次都没切读写面。
            # 拿不到面不带走这一次补登记（fail-open）：少一个面是"这一项干不了活"，少一条
            # 名册行是"父根本销不掉它"（79 那趟的形态）；落一个空 `surface` 与改前同形，
            # 读侧读得出"名下有项、没面"。
            got_surface = self.surface_alloc(owner=owner, name=name)
            slot = str(got_surface.get("slot") or "")
            ok, why = append_jsonl(roster_index_path(self.root, owner),
                                   {"kind": "bind", "owner": owner, "name": name, "role": role,
                                    "task_id": tid, "at": _now_iso(), "repaired": True})
            if not ok:
                return fixed, f"补登记没写成：{why}", skipped
            ok2, why2 = append_jsonl(roster_path(self.root, owner),
                                     {"kind": "add", "owner": owner, "name": name, "role": role,
                                      "task_id": tid, "first_task_id": tid,
                                      "brief": "（补登记：这一条当时没写进名册）",
                                      # 这句话是秘书写的（不是父给的）⇒ 留痕那一格照写
                                      "brief_source": "secretary",
                                      "surface": slot,
                                      # 丁的三格留痕（业主 2026-11-01）：它是不是"跑过之后才补的
                                      # 名"、它当初点名要什么（原样保留 —— 那是"它曾经想叫 E2"
                                      # 的记录）、哪一档拒的。JSONL 无 schema 契约，加键不改旧键。
                                      "named_after_run": bool(ran),
                                      "requested_name": want_name,
                                      "refusal_code": refusal_code,
                                      "at": _now_iso(), "repaired": True})
            if not ok2:
                return fixed, f"名册补写没成：{why2}", skipped
            fixed += 1
            self.last_repair_named.append({
                "task_id": tid, "name": name, "role": role,
                "named_after_run": bool(ran), "requested_name": want_name,
                "refusal_code": refusal_code, "surface": slot})
        return fixed, "", skipped

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
        """反查：某个调用行属于这个名册里的哪一个名字（一个号两个名字 ⇒ 不猜）。

        为什么必须在本层拒歧义（`draft/151` 三-4）：写口从 2026-11-02 起拒"同一个号
        出现在两条 add"（`task_id_reused`），但 `projects/ 下` 里的历史名册有这一形态；
        按号寻址那一侧（`agent_loop.roster_addresses`）已经因此拒 `ambiguous_in_roster`，
        而这里改前 `return` 第一个命中 —— `surface_of` 就会按第一个名字的槽位去切
        读写面，两个人的面重叠等于跨代理写同一份文件。三态纪律：多匹配不是"查到了
        一个"，它是"这一格判不了"，回空名 + 一句点名（读者退回用编号）。
        """
        index, bad = self.roster_index(owner)
        if bad:
            return "", f"对照表有 {len(bad)} 行读不出来"
        names = sorted({str(r.get("name") or "") for r in index
                        if str(r.get("name") or "")
                        and str(r.get("task_id") or "") == str(task_id)})
        if len(names) > 1:
            return "", (f"对照表里 {task_id} 对应 {len(names)} 个名字（{'、'.join(names)}）"
                        "⇒ 不猜（同一个号两个名字；按号寻址的同一档是 "
                        "`ambiguous_in_roster`，这一份名册要人核）")
        if names:
            return names[0], ""
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

        ## 两个数各自的定义（见 `conductor` 那几个常量）
        - 子代理数 = 名册里还没销号的名册项数（在册、未退役）；
        - 活跃子代理数 = 其中非静默的数量（「活跃子代理」的定义就是非静默子代理）：
          非静默 = 在飞 + 待机，三态判定只有 `conductor.agent_state`
          一处；`unknown`（判不了）既不算活跃也不算静默，它进 `states["unknown"]`
          并让 `complete=False`。

        两个数必须各自出现、不许相加也不许互相代替：前者回答"这一支还有几个名字在用"，
        后者回答"其中几个还在干活或还在等"。折成一个数之后，"名册只增不减"与
        "活都干完了"会长得一模一样。

        ## 三态的读法（业主原话：「『在飞』的读数要随着时钟式待机进行适配」）
        `states` 是四档各几个（`flying` / `standby` / `silent` / `unknown`）＋
        `active`（= 在飞 + 待机）＋ `total`；`by_owner` 每一项同样带这四格。
        已销号的名册项不进 `items`（子代理数只数未销号的那些），所以"已销号 ⇒ 静默"
        在这一份读数里表现为"它根本不在分母里"——与 `roster_view` / 网页名册面
        逐行给 `state` 的那一处是同一条口径的两个落点。
        口径取"名册项当前那一件活那一行"（`item.task_id`）：一个常驻子代理接过 N 件活时，
        那 N 行的三态在 `activity_snapshot` 里各自可得，而"它现在在哪一态"问的是现在。
        网页名册面（`readers.roster_face`）对同一项按 `tasks[]` 里全部活取最活跃的一格
        —— 两处都是"这一层知道多少就判多少"，谁也没有把不知道的当成静默。

        ## 范围
        `owner` 给了 ⇒ 只看那一个父的名册；不给 ⇒ 全工作区（`roster_owners` 扫
        `out/roster/<父>.jsonl`，三种旁支排除）。`by_owner` 是同一个口径的分父读数。

        ## 三态与"判不了"（不许折平）
        名册读不成 / 台账读不成 ⇒ `checked=False` + `reason`，两个数都是 `None`
        （`0` 是"名册空了"这个很强的结论，而"没读成"什么都不说）。
        某一项的名册行读得出来、但台账里没有它那一行 ⇒ 它的三态判不了 ⇒ 进 `unjudged`
        且 `complete=False`，同时 `active_child_count` 只数判得了的那些（读数里
        `complete` 那一格就是这件事的显式声明，不许靠"大概都判得了"糊过去）。

        ## `waiting_only`（病态形状）
        每一项 `standby and not self_busy` 的节点都进 `waiting_only`，带一句人话
        「它自己不忙，是在等 D2（active）」。那不是错，但父必须看得见 ——
        这一支的活积在下级身上，而中间那几层只是挂着名字在等。
        """
        from .conductor import (ACTIVE_CHILD_COUNT_KEY, CHILD_COUNT_KEY,
                                CHILD_COUNT_LABELS, AGENT_STATE_LABELS,
                                AGENT_STATE_UNKNOWN, ACTIVE_AGENT_STATES,
                                state_counts)

        labels = dict(CHILD_COUNT_LABELS)
        out: dict[str, Any] = {"checked": False, "reason": "", "owner": str(owner or ""),
                               CHILD_COUNT_KEY: None, ACTIVE_CHILD_COUNT_KEY: None,
                               "labels": labels, "waiting_only": [], "unjudged": [],
                               "states": None, "state_labels": dict(AGENT_STATE_LABELS),
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
        # 全量的三态读数在下面那一趟里顺手攒下来：原先建一张 `tid -> state` 的表，
        # 再拿 items 逐条查表扫第二遍（同一批项走两趟）。逐项 append 与逐项查表同值，
        # 同号多项时也是逐项各记一次（与原来的生成器一致）。
        states_seen: list[str] = []
        waiting: list[dict[str, Any]] = []
        unjudged: list[dict[str, Any]] = []
        for it in items:
            slot = per_owner.setdefault(it["owner"], {CHILD_COUNT_KEY: 0,
                                                      ACTIVE_CHILD_COUNT_KEY: 0,
                                                      "flying": 0, "standby": 0,
                                                      "silent": 0, "unknown": 0})
            slot[CHILD_COUNT_KEY] = int(slot[CHILD_COUNT_KEY]) + 1
            tid = it["task_id"]
            cell = by_task.get(tid)
            if cell is None:
                # 台账里没有它那一行 ⇒ 三态判不了（`unknown`），而 `unknown` 不是静默：
                # 把它折成静默会让"判不了"与"它就是收工了"长得一模一样。
                states_seen.append(AGENT_STATE_UNKNOWN)
                slot["unknown"] = int(slot["unknown"]) + 1
                unjudged.append({"owner": it["owner"], "name": it["name"],
                                 "task_id": tid, "state": AGENT_STATE_UNKNOWN,
                                 "why": "台账里没有它那一行 ⇒ 它有没有未收口的活判不了"})
                continue
            state = str(cell.get("state") or AGENT_STATE_UNKNOWN)
            states_seen.append(state)
            # 词表外的取值记进 `unknown`（`conductor.state_counts` 的同一条口径）：
            # 先算出要落的键再累加 —— 直接 `slot[key] = int(slot.get(state)) + 1`
            # 会读到"另一格"的旧值，于是 `unknown` 每遇到一个词表外取值就被
            # 覆盖成 1（实测：两项判不了 + 一项词表外 ⇒ `by_owner` 说 1、`states` 说 3，
            # 而 `note` 里那句"另有 3 项判不了"用的是后者）。
            bucket = state if state in slot else AGENT_STATE_UNKNOWN
            slot[bucket] = int(slot.get(bucket) or 0) + 1
            if state not in ACTIVE_AGENT_STATES:
                continue
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
                            "role": it["role"], "task_id": tid, "state": state,
                            "waiting_for": kids, "for_names": wait_names,
                            "note": ("它自己不忙，是在等 " + "、".join(wait_names)
                                     + "（active）")})
        counts = state_counts(states_seen)
        active_count = counts["active"]
        note = (f"{labels[CHILD_COUNT_KEY]}={len(items)}，"
                f"{labels[ACTIVE_CHILD_COUNT_KEY]}={active_count}"
                f"（在飞 {counts['flying']} · 待机 {counts['standby']} · "
                f"静默 {counts['silent']}）")
        if counts["unknown"]:
            note += f"；另有 {counts['unknown']} 项判不了（{AGENT_STATE_LABELS['unknown']}）"
        if waiting:
            note += f"（其中 {len(waiting)} 个靠等下级才活跃）"
        if unjudged:
            note += (f"；有 {len(unjudged)} 项判不了活跃"
                     "（台账里没有它那一行）⇒ 活跃子代理数只数了判得了的那些")
        out.update({"checked": True, "reason": "",
                    CHILD_COUNT_KEY: len(items),
                    ACTIVE_CHILD_COUNT_KEY: active_count,
                    "states": counts,
                    "waiting_only": waiting, "unjudged": unjudged,
                    # `unknown` 非 0 就不算完整：那一档既不是活跃也不是静默，
                    # 只是"这一项没判成"，而"完整性"这一格正是这件事的显式声明。
                    "complete": (not unjudged) and counts["unknown"] == 0,
                    "by_owner": {k: dict(v) for k, v in sorted(per_owner.items())},
                    "note": note})
        return out

    def unnamed_children(self, *, owner: str = "") -> dict[str, Any]:
        """
        「真跑但无名」的逐条读数（只读，不修）。

        ## 它回答的问题

        「这一支里，有没有真跑过、却在任何一个父的名册上都找不到名字的子代理？」
        —— 真跑、`done/ok`、有产物，而名册三份里一行都没有：父永远叫不出它的名字
        （`retire(name=…)` 叫不到，只能用 `retire_child(task_id=…)` 走 unrostered 那一支认边收口，
        收完仍然没有名字）。

        ## 判据只有一处

        「真跑过」的条件全在模块级 :func:`ran_but_unnamed` 里，这里只负责取数、join、按父归组。
        网页那一格（`webui.readers._roster_unrostered_children`）用同一个函数给每条打 `ran` 标记 ——
        两个面说的是同一句话，不是各写一份。

        ## 口径：台账 join 名册历史，不读会话

        会话里那条 `roster_problem` 不可靠：可抢占派活在句柄没落定时提前返回，名册读数那一行在后面。
        所以这一格只读盘上的事实：`tasks`（谁真跑过）+ 名册三份（谁有名字）+ 拒绝流水
        （它当初点的那个名字，现在在谁手里）。

        ## 三态（`checked` 绝不折成"没有"）

        - 台账读不成 ⇒ `checked=False` + `reason`，`count=None`（不是 0：0 是"查过了，一个都没有"）；
        - 某个父的名册 / 拒绝流水有坏行 ⇒ 同样 `checked=False` + `bad` 逐条点名 ——
          "读不全"不许折成"这一支没有无名子代理"（fail-closed，与 :meth:`roster_repair` 同一条纪律）。

        ## 返回

        `{"checked","count","scanned","rows","bad","owners","reason"}`；`rows` 每一条：

        - `task_id` / `role` / `parent_task_id` / `status` / `outcome` / `started_at` / `ended_at`；
        - `artifacts`（台账里那一格原样）+ `artifacts_missing`（在盘上找不到的那几个）；
        - `edge_released`：父有没有已经认掉这条边（收口了仍然没有名字，正是这一格要让人看见的事）；
        - `requested_name` / `refusal_code`：它当初点名要的是什么、被哪一档拒绝；
        - `held_by`：那个名字现在挂在谁身上（`null` = 没人用）—— 这一格回答"是哪个号占掉了它的名字"。
        """
        out: dict[str, Any] = {"checked": False, "count": None, "scanned": 0,
                               "rows": [], "bad": [], "owners": [], "reason": ""}
        cond = self._conductor()
        if cond is None:
            out["reason"] = "没有 store ⇒ 读不到台账（这一格不是「没有无名子代理」）"
            return out
        try:
            rows = [r for r in cond._tasks() if not str(r.get("kind") or "")]
        except Exception as exc:  # noqa: BLE001 —— 读不成是"没查成"
            out["reason"] = f"台账读不成（{type(exc).__name__}: {exc}）⇒ 这一格没查成"
            return out
        out["scanned"] = len(rows)
        want = str(owner or "")
        # 先按父归组一趟：原先外层每换一个父就把整张台账再扫一遍挑自己的子行
        # （父数 × 全表）。归组只改"从哪儿取"，桶内顺序仍是台账顺序。
        by_parent: dict[str, list[Mapping[str, Any]]] = {}
        for r in rows:
            pid = str(r.get("parent_task_id") or "")
            if pid:
                by_parent.setdefault(pid, []).append(r)
        owners = [want] if want else sorted(by_parent)
        out["owners"] = list(owners)
        bad: list[str] = []
        got: list[dict[str, Any]] = []
        for own in owners:
            known, bad_hist = self._roster_history(own)
            bad.extend(f"{own}：{x}" for x in bad_hist)
            # 认边落痕写在父那一行上（`Conductor.note_edge_release` 的落点），不在子行：
            # 81 的 `t-000106` 那一条是 `t-000016.inputs` 里的 `edge-released:t-000106#1`。
            parent_row = self._task_row(rows, own)
            refusals: dict[str, dict[str, Any]] = {}
            try:
                ref = registration_refusals(self.root, owner=own)
            except Exception as exc:  # noqa: BLE001 —— 读不成按坏行处理（fail-closed）
                ref = {"checked": False, "items": [],
                       "bad": [f"拒绝流水读不成（{type(exc).__name__}: {exc}）"]}
            bad.extend(f"{own}：{x}" for x in (ref.get("bad") or []))
            for item in ref.get("items") or []:
                tid = str(item.get("task_id") or "")
                if tid:
                    refusals[tid] = item
            holders = self._name_holders(own) if refusals else {}
            for row in by_parent.get(own, ()):
                if not ran_but_unnamed(row, known):
                    continue
                tid = str(row.get("task_id") or "")
                refusal = refusals.get(tid) or {}
                asked = str(refusal.get("requested_name") or "")
                held = dict(holders.get(asked) or {}) if asked else {}
                if held:
                    hrow = self._task_row(rows, str(held.get("task_id") or ""))
                    held["task_status"] = str(hrow.get("status") or "")
                    held["task_outcome"] = str(hrow.get("outcome") or "")
                arts = [str(a) for a in (row.get("artifacts") or []) if str(a)]
                got.append({
                    "task_id": tid,
                    "role": str(row.get("role") or ""),
                    "parent_task_id": own,
                    "status": str(row.get("status") or ""),
                    "outcome": str(row.get("outcome") or ""),
                    "started_at": str(row.get("started_at") or ""),
                    "ended_at": str(row.get("ended_at") or ""),
                    "artifacts": arts,
                    "artifacts_missing": [a for a in arts if not self._artifact_on_disk(a)],
                    "edge_released": self._edge_released(parent_row, tid),
                    "requested_name": asked,
                    "refusal_code": str(refusal.get("refusal_code") or ""),
                    "held_by": held or None,
                })
        got.sort(key=lambda x: (x["parent_task_id"], x["task_id"]))
        out.update({"rows": got, "count": len(got), "bad": bad})
        if bad:
            out["reason"] = (f"名册 / 拒绝流水有 {len(bad)} 处读不出来 ⇒ 这一格不许当成"
                             f"「只有 {len(got)} 个」（读不全不是查过了）")
            return out
        out["checked"] = True
        return out

    @staticmethod
    def _task_row(rows: Iterable[Mapping[str, Any]], task_id: str) -> Mapping[str, Any]:
        """在已经读出来的台账行里找那一号（找不到回空 dict —— 名字的持有者可能是历史行）。"""
        want = str(task_id or "")
        if not want:
            return {}
        for r in rows:
            if str(r.get("task_id") or "") == want:
                return r
        return {}

    def _name_holders(self, owner: str) -> dict[str, dict[str, Any]]:
        """这个父名下「名字现在挂在谁身上」：`名字 → {name, task_id, retired, retired_task_id}`。

        口径与 `_roster_history` 同一份（`add` ∪ `bind`，首个名字胜）：名字是身份，
        一个名字只该有一个当前号。销号名单上有的再补两格 —— 81 的 `E2` 正是这一档：
        名册项 `E2/t-000030`、04:46:50 已销号 ⇒ 持有者 `retired=True`。
        """
        out: dict[str, dict[str, Any]] = {}
        rows, _bad = self._roster_bindings(owner)
        for tid, name in rows:
            if name and name not in out:
                out[name] = {"name": name, "task_id": tid, "retired": False,
                             "retired_task_id": ""}
        got = self.retired_ledger(owner, trusted_shard=True)
        for r in got.get("rows") or []:
            name = str(r.get("name") or "")
            if name in out:
                out[name]["retired"] = True
                out[name]["retired_task_id"] = str(r.get("task_id") or "")
        return out

    def _artifact_on_disk(self, rel: str) -> bool:
        """台账里那一格产物在不在盘上（相对路径按工作区根解析）。"""
        text = str(rel or "")
        if not text:
            return False
        p = Path(text)
        if not p.is_absolute():
            p = Path(self.root).joinpath(text)
        try:
            return p.is_file()
        except OSError:
            return False

    @staticmethod
    def _edge_released(row: Mapping[str, Any], task_id: str) -> bool:
        """父那一行的 `inputs` 里有没有认掉这条边（`edge-released:<子号>#<n>`）。

        落点在父行（`Conductor.note_edge_release` 写的是派活方那一行），所以调用方
        传进来的必须是父行 —— 传子行会恒为 False（81 的 `t-000106` 就是这么验的）。
        """
        want = f"edge-released:{task_id}"
        return any(str(x).startswith(want) for x in (row.get("inputs") or []))

    def roster_view(self, *, owner: str, scope: str = "self",
                    limit: int = 20) -> dict[str, Any]:
        """名册视图（只读，不许修补 —— I-15）。

        真身在 :meth:`_roster_view_body`：本方法只负责把它包进"一拍一份台账快照"那一个
        只读作用域（2026-10-27）。为什么包在这里而不是让每一处读侧自己缓存：这一份视图
        一拍里要问台账 15 次以上（逐名册项问一次"它名下最新的派活项声明过待命吗"、
        逐层问一次"这一层哪几项可退役"、还有三态快照与 `children_facts`），而它们读的是
        同一份台账的同一个时刻 —— 一拍一份快照是这条口径的唯一落点。
        `roster_view` 从 I-15 起就是"只读、不许修补"，所以作用域内不会有写（真写了会抛）。
        """
        cond = self._conductor()
        if cond is None:
            return self._roster_view_body(owner=owner, scope=scope, limit=limit)
        # 作用域开不起来也是"没读成"，不是让异常穿出去（2026-10-27）：
        # `roster_view` 的三态契约说"读不成 ⇒ checked=False + reason"，
        # 而 `reading_snapshot()` 自己要读一次台账 —— 它抛的话，穿出去就成了崩溃而不是读数
        # （判据 `test_roster_view_reports_and_never_writes` 的 `_Broken` 替身钉的正是这一档）。
        try:
            snapshot = cond.reading_snapshot()
        except Exception as exc:  # noqa: BLE001 - 读不成要有读数
            return self._roster_view_unreadable(f"名册没读成（{type(exc).__name__}: {exc}）", owner, scope, limit)
        try:
            with snapshot:
                return self._roster_view_body(owner=owner, scope=scope, limit=limit)
        except RuntimeError as exc:
            # 作用域内写台账会被 `_refuse_write_in_snapshot` 拒（程序错，不是读不成）⇒ 照旧抛；
            # 其余 RuntimeError（台账读不成）按三态降级。判据两支都要能区分，所以按拒信原话认。
            if "只读快照作用域" in str(exc):
                raise
            return self._roster_view_unreadable(f"名册没读成（{type(exc).__name__}: {exc}）", owner, scope, limit)
        except Exception as exc:  # noqa: BLE001 - 同上，读不成要有读数
            return self._roster_view_unreadable(f"名册没读成（{type(exc).__name__}: {exc}）", owner, scope, limit)

    def _roster_view_unreadable(self, reason: str, owner: str, scope: str,
                                limit: int) -> dict[str, Any]:
        """名册视图"没读成"的那一份读数（三态里的第三态，形状与真身那个分支逐键相同）。

        为什么单列一个方法而不是在 `roster_view` 里内联：那个 `checked=False` 的行有 11 个键
        ，内联一份就多一处会漂的形状；这里与 `_roster_view_body` 里的
        同形返回逐键相同，靠 `test_roster_view_reports_and_never_writes` 与
        `test_roster_state_is_checkable` 一起钉住（它们会读 `checked` / `reason` 与每格的存在性）。
        """
        from .conductor import (ACTIVE_CHILD_COUNT_KEY, CHILD_COUNT_KEY)  # 与真身同一来源
        diagnostics: dict[str, Any] = {
            "owner": owner, "scope": scope, "limit": int(limit), "unreadable": reason}
        return {"checked": False, "rows": [], "more": 0, "scope": scope,
                "diagnostics": diagnostics, "parent": owner, "reason": reason,
                "counts": None, "states": None, CHILD_COUNT_KEY: None,
                ACTIVE_CHILD_COUNT_KEY: None}

    def _roster_view_body(self, *, owner: str, scope: str = "self",
                          limit: int = 20) -> dict[str, Any]:
        """`roster_view` 的真身（口径与返回值见上一份 docstring）。：`{"checked","rows","more","reason","diagnostics"}`。

        每一行：`name` / `role` / `brief` / `brief_source`（`parent` 父给的原话 / `secretary` 秘书从任务原文代写 /
        `""` 缺这一格的行）/ `state`（活跃 / 待命 / 已停 / 已退役 / 未登记）/ `retirable`（按 `conductor.retire_ready`
        的三分支）/ `items_open`（只报不拦）/ `task_id`（当前调用），外加三格：`status`（机器
        可判的那一格：`running` / `idle` / `ready` / `retired` —— 中文那五档是给人读的，而"父要不要现在动手"需要
        一格能直接判的）、`in_flight`（它名下此刻还在跑的任务数，`Conductor.children_facts` 现算）、`last_reading`
        （它最近一条工作报告的摘要，`latest_report_of` 的同一份数据，但一次读一份手稿再逐行取）。DSH 的
        `list_agents` 没有这一格，我们的比它全 ⇒ "净减一样别丢"。`scope="descendants"` 时给全树（每
        一行多 `parent` 与 `depth`）—— 改前只有下一层。规模：默认只回 20 项 + `more`（与 `inbox_digest` 同族口径）。
        ## 父是谁（「名册 = 父 + 子 + 绝对编号」）：每一份视图都带一格 `parent`（见
        :meth:`parent_of`：绝对编号 + 角色 + 名册名），`scope="descendants"` 的行另带 `parent_task_id` —— 改前
        那些行只有相对名 `parent`，而"相对名"没法拿去发消息（那正是这一轮要补的那一格）。于是"我能通话的是谁"
        这件事在同一份读数里自足了，寻址不必再另造一个视图。
        ## 逐行 diagnostic（不再一行坏就整份拒）：改前名册里有一行读不出来 ⇒ `{"checked": False, "rows": []}`
        （整体拒）。DSH 的 `list-agents.js:30-47` 是逐行报 `corrupt/unsupported/unavailable`。现在照它：好行照常
        渲染，坏行逐条落进 `diagnostics`（带行号与类别）。只有一种情形仍然整体拒：一条好行都没有而坏行有（三态纪律挡的正是"名册是空的"与"名册读不成"被折成同一句话）。
        ## 两个读数各占一格
        这一份视图顶上带 `children_unretired`（子代理数 = 名下未销号的名册项数）与
        `active_child_count`（活跃子代理数 = 其中非静默的数量 = 在飞 + 待机），
        另有一格 `counts`（`Secretary.child_counts` 的整份读数：`owner` / `states` /
        `waiting_only` / `unjudged` / `note`）与一格 `states`（四档各几个）。
        两个数不许相加、不许互相代替 —— 口径与三态都在 :meth:`child_counts` 里，
        这里只转发。每一行另带 `agent_state`（三态：在飞 / 待机 / 静默 / 未读到 ——
        名字不叫 `state`，因为那一格已经是给人读的五档中文）、`active` /
        `waiting_only` / `waiting_note`：`active` 是"按继承口径算，它算不算活跃"，
        与 `state`（它自己此刻在不在跑）是两件事（"在等"也算活跃）。
        读不成 ⇒ 两个数与 `states` 都是 `None`（不是 0）。
        """
        from .conductor import (ACTIVE_CHILD_COUNT_KEY, AGENT_STATE_UNKNOWN,
                                CHILD_COUNT_KEY)

        cond = self._conductor()
        rows, bad = self.roster_rows(owner)
        diagnostics = [_diagnose_line(line) for line in bad]
        # 「我自己的父是谁」那一格（名册 = 父 + 子 + 绝对编号）。
        # 只有"我名下的子代理"时，父是谁只能从 `AgentLoop.parent_task_id` 那个内存字段
        # 读到，而名册自己（盘上那一份）答不上来。现在六条 return 都带上它。
        parent = self.parent_of(owner=owner)

        def _fail(reason: str) -> dict[str, Any]:
            """这一份视图"没查成"的统一形状（两个读数都是 None，不是 0）。"""
            return {"checked": False, "rows": [], "more": 0, "scope": scope,
                    "diagnostics": diagnostics, "parent": parent, "reason": reason,
                    "counts": None, "states": None, CHILD_COUNT_KEY: None,
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
        # `retired` 是本层的事实（名册项上那一格）：传给三态判定，让"已销号 ⇒ 静默"
        # 仍然只由 `conductor.agent_state` 那一处判（这里不再写第二遍）。
        retired_map = {str(r.get("task_id") or ""): True for r in rows
                       if r.get("retired") and str(r.get("task_id") or "")}
        snap = cond.activity_snapshot(retired=retired_map)
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
            # 三态位与 `state` 同出（2026-10-27）：`state` 五档不变，另给 `state_checked`
            # 与 `state_reason` —— "它停了"与"它判不了"因此在同一份读数里分得开。
            reading = _state_reading(branch, bool(r.get("retired")), cond, tid,
                                     branch_checked=bool(t.get("branch_checked", True)))
            state = str(reading["state"])
            row: dict[str, Any] = {
                "name": str(r.get("name") or ""), "role": str(r.get("role") or ""),
                "brief": str(r.get("brief") or ""), "state": state,
                "state_checked": bool(reading["state_checked"]),
                "state_reason": str(reading["state_reason"]),
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
                # 三态（`conductor.agent_state` 是唯一实现）。名字刻意不叫 `state`：
                # 上面那一格 `state` 已经是给人读的五档中文（活跃 / 待命 / 已停 /
                # 已退役 / 未登记），两个取值域共用一个键会让"活跃"与"在飞"混成一件事。
                # "已销号 ⇒ 静默"不在这一行判：`retired_map` 已经随快照传进
                # `agent_state`（那一处才是判定本体）。
                "agent_state": str((activity.get(tid) or {}).get("state")
                                   or AGENT_STATE_UNKNOWN),
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
                "counts": counts, "states": counts.get("states"),
                CHILD_COUNT_KEY: counts.get(CHILD_COUNT_KEY),
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
        # 每一层的"可退役分支"（`branch` 是 `_state_reading` 折四态的那一格）。
        #
        # 2026-10-20（真机读数驱动，`projects/tree-check`）：改前 `by_child`（在 `roster_view`
        # 里由 owner 那一层的 `retire_ready` 构造）只覆盖直接子，于是全树视图里
        # 孙代及以下的 `branch` 恒为空 ⇒ `_state_reading` 落到「未登记」，而它们明明在名册上。
        # 实测那一份工作区：7 行里有 5 行（C1/F1/B1/B2/E1 --- 深度 2/3）被读成「未登记」，
        # 只有直接子 D1 读对（已停）。这与 `draft/90` §1.4「必须看到名册名 + 一句简介 +
        # 工作状态」直接冲突，也是机制②（M 看整棵树）唯一的真缺口。
        # 修法：逐层问它父那一层的 `retire_ready`（同一处实现，不另写一份分支判据），
        # 每个父只问一次（`branch_by_parent` 缓存）。
        branch_by_parent: dict[str, dict[str, str]] = {}

        #: 每一层的就绪读数"读成了没有"（2026-10-27）：`branch` 为空有两种原因 ——
        #: 那一层真没有可退役的项，或者那一层的读数根本没读成。两者不许折成同一句话，
        #: 所以这里把三态位带出去，`roster_view` 落进 `state_checked`。
        branch_checked_by_parent: dict[str, bool] = {}

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
            branch_checked_by_parent[parent_id] = bool(got.get("checked"))
            return found
        root_id = str(owner or "")
        if scope != "descendants":
            top = branches_of(root_id)
            top_checked = bool(branch_checked_by_parent.get(root_id, False))
            for r in rows:
                tid = str(r.get("task_id") or "")
                out.append({"row": r, "parent": "", "parent_tid": "", "depth": 1,
                            "branch": top.get(tid, ""),
                            "branch_checked": top_checked,
                            "facts": dict(root_by.get(tid) or {})})
            return out
        # 全树：逐层往下，每一层的 facts 从它的父那一格里取。
        # 这一格最容易写错（第一版就是）：`children_facts(X)` 给的是"X 名下"的读数，
        # 而某一行要的是"它父名下的它自己"那一格 —— 拿 X 去查 X 只会得到空表，
        # 于是全树的每一行都会读成 `ready`（一个安静的错误：没有任何地方会报错）。
        top_branches = branches_of(root_id)
        top_checked = bool(branch_checked_by_parent.get(root_id, False))
        queue: list[tuple[dict[str, Any], str, str, int, dict[str, Any], str, bool]] = []
        for r in rows:
            tid = str(r.get("task_id") or "")
            queue.append((r, "", root_id, 1, dict(root_by.get(tid) or {}),
                          top_branches.get(tid, ""), top_checked))
        # 队列用游标取头（原先 `pop(0)` 每次把整个列表前移一格）：先来先处理
        # 的顺序一个字没变，只是取头从 O(队列长) 变成 O(1)。
        head = 0
        seen = 0
        while head < len(queue) and seen < 512:
            r, parent_name, parent_tid, depth, facts, branch, checked = queue[head]
            head += 1
            seen += 1
            out.append({"row": r, "parent": parent_name, "parent_tid": parent_tid,
                        "depth": depth, "branch": branch, "branch_checked": checked,
                        "facts": facts})
            if depth >= 64:
                continue
            tid = str(r.get("task_id") or "")
            kids, _bad = self.roster_rows(tid)
            if not kids:
                continue
            by = dict((parent_facts(tid).get("by_child") or {}))
            their = branches_of(tid)
            their_checked = bool(branch_checked_by_parent.get(tid, False))
            for k in kids:
                kt = str(k.get("task_id") or "")
                queue.append((k, str(r.get("name") or ""), tid, depth + 1,
                              dict(by.get(kt) or {}), their.get(kt, ""), their_checked))
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

    def settle_retired_row(self, task_id: str, *, name: str = "",
                           reason: str = "") -> dict[str, Any]:
        """销号落定台账那一行：还在飞的（`status ∈ {pending, running}`）⇒ 写终态 `cancelled`。

        ## 为什么销号必须动台账
        扇出名额的分子是"父名下 `status ∈ {pending, running}` 的直接子"
        （`Conductor._in_flight_children_of`，单时刻口径）。销号若只写名册 / 对照表 /
        销号名单三份 jsonl —— 台账那一行一个字节都不动，于是
        「销号一个静默子代理腾出名额」这句话在盘上是空话：占位数不变，下一次 `summon`
        照旧 `fanout_exceeded`。这一笔就是那句承诺的落点：销号 = 让它从"占位"里退出。

        ## 为什么只有"还在飞的"才写
        绝大多数静默子代理早就落了终态（`done` / `failed` / `cancelled` 带 `ended_at`），
        它们本来就不占名额 —— 那些行一个字节都不动（谁什么时候交了差是历史，不许改写）。
        真正需要落终态的是"父已记为静默、而台账行还没收口"的那一档（交差之后收尾没走完 /
        可抢占派活的后台线程被掐断 / 进程退出），它占着名额却永远不会自己返回。

        ## 三态与代价
        读不成 / 写不成 ⇒ `checked=False` + `reason`，调用方（`retire`）据此拒绝整笔销号
        （先写这一笔、再写名册：反过来的顺序会让"名册已销、台账没落终态"这种半笔无路可退）。

        与"它自己刚好收了尾"的赛跑：闸门看过之后、这一笔落下之前它自己落了终态 ⇒ 这里
        读到的是终态、一行不动；反过来（这一笔先落）由 `Task` 的"终态先到先得"兜住 ——
        两笔都是终态，读者看到的是先落的那一笔，谁也不改写历史。

        返回 `{"checked","was_occupying","status_before","status_after","task_id","reason"}`。
        """
        tid = str(task_id or "")
        out: dict[str, Any] = {"checked": False, "was_occupying": False,
                               "status_before": "", "status_after": "", "task_id": tid,
                               "reason": ""}
        if not tid:
            out["reason"] = "没有编号 ⇒ 不知道落定哪一行"
            return out
        if self.store is None:
            out["reason"] = "没有 store ⇒ 读不到台账（没查成，不是『它不占名额』）"
            return out
        try:
            rows = [r for r in self.store.rows("tasks")
                    if str(r.get("task_id") or "") == tid]
        except Exception as exc:  # noqa: BLE001 —— 读不成是"没查成"
            out["reason"] = f"台账读不成（{type(exc).__name__}: {exc}）"
            return out
        row = dict(rows[0]) if rows else {}
        status = str(row.get("status") or "")
        out["status_before"] = status
        if not row:
            out["reason"] = f"台账里没有 {tid} 这一行（查过了、确实没有）"
            return out
        if status not in LIVE_TASK_STATUSES:
            # 已经收口：不占名额，也不许改写历史。
            out.update({"checked": True, "status_after": status})
            return out
        why = ("销号退场：" + (str(reason or "").strip() or "父决定销号"))
        row["status"] = "cancelled"
        row["outcome"] = "cancelled"
        row["ended_at"] = S.now_iso()
        row["detail"] = ((str(row.get("detail") or "").strip() + "；") if str(row.get("detail") or "").strip() else "") \
            + f"销号退场（{name or tid}）：这一行由销号落定终态，腾出扇出名额（{why[:120]}）"
        try:
            S.Task(**{k: v for k, v in row.items()
                      if k in S.Task.__dataclass_fields__}).validate()
            with self.store.tx("tasks", actor=f"secretary-{self.role}",
                               note=f"retire:settle:{tid}") as tx:
                tx.upsert("tasks", row, note=f"retire:settle:{tid}")
        except Exception as exc:  # noqa: BLE001 —— 写不成 ⇒ 名额没腾出来，必须如实说
            out["reason"] = f"台账那一行没落成终态（{type(exc).__name__}: {exc}）"
            return out
        out.update({"checked": True, "was_occupying": True, "status_after": "cancelled"})
        return out

    def retire(self, *, owner: str, name: str, by_task_id: str = "",
               reason: str = "") -> dict[str, Any]:
        """退役（三分支）。返回：

        `{"ok","action":"retired"|"reported"|"refused","report":{…},"why":[…], "reading":{…}}`

        - 目标不是静默（在飞 / 待机 / 读不到）⇒ `refused`（销号只可针对静默子代理），
          带 `refusal_code`（`target_not_silent`）、`target_state` 与逐条 `blocking`；
          `report` 仍把"它最近报了什么 / 它名下的子代理在干什么"端给父 —— 拒了不等于什么都不给；
        - `active` ⇒ `reported`：把最近的工作报告端给父，不退役（静默闸之外的第二道保险）；
        - `waiting_with_children` ⇒ `reported`：把那些子代理在它名册里的任务简介端给父；
        - `waiting_no_children` ⇒ `retired`：写退役事件 + 销号名单 + 对照表标退役 +
          `conductor.note_edge_release`（父侧那一笔幂等落痕）；
        - 未登记 / 读不成 / 已销号 ⇒ `refused`（没读成 ≠ 可以退役）。

        `cascade` 在每一档都有：`{"count","ids","levels","kept"}` —— `count` 是这一笔实际
        销掉了几个（`retired` 档恒为 1），`ids` / `levels` 是编号与相对层深（目标恒为 0），
        `kept` 是"没销、还占着名册的那几个"，逐条 `{"id","name","why"}`。理由：回执要说清
        "我没销它是为了什么"，`why` 给人读、`kept` 给下一步判断用。

        ## 程序闸

        销号前先读一次"这一支还有没有程序在跑"（`conductor.programs_in_subtree`，与
        `conductor.retire_child` 读同一份），有就受控拒绝、一个字节都不落盘。它排在静默闸
        之前：静默闸的三样（无工作 / 无计时器 / 无活跃子）都读不出"一台程序还在跑"——
        无主的程序计时器（`task_id` 空）在三态里一句话都没有。拒信措辞只有
        `conductor.programs_refusal` 一处：点名 program / pid / 已跑秒数，并只指一条正路。

        ## 孤儿闸

        目标自己静默、但名下还有没销号的静默子代理 ⇒ 受控拒绝。为什么必须有：销号只发给
        直接子代理，一支的子代理只有它这一个父能销；父先销了、名字永久不复用（B1）、
        不会再有下一轮 ⇒ 那些子代理再没有任何代理有权销它们，`Conductor.retire_integrity`
        永远不 complete、`final` 被结构完整性闸永久拒。正路是 `conductor.retire_child`
        （从最深的开始把这一支一起销）。这一闸排在静默闸之后：父非静默时由静默闸先说话；
        父静默而子只是"没销"时才轮到它。它不误伤级联 —— 级联先深后浅。

        ## 静默的定义（与 `conductor.agent_state` 同一份）

        无工作 ∧ 无任何计时器 ∧ 无活跃子代理。销号不可逆（名字永久不复用），所以一律
        fail-closed：读不到是不是静默就不销。三档拒信各说各的下一步 —— 在飞就让它收工；
        待机就让那些计时器的事先发生、或显式让它停（停止 ≠ 销号）；读不到就重读一次。

        ## `reason`

        父发起销号时那一句理由，逐字落进三份台账（名册行 / 对照表行 / 销号名单行，
        `reason` 键）。缺省空串 ⇒ 对既有调用方的落盘行只多一个键、不改任何既有键。
        """
        cond = self._conductor()
        if cond is None:
            return {"ok": False, "action": "refused", "report": {},
                    "why": ["没有 store ⇒ 读不到台账（没读成，不是'不在跑'）"]}
        # ---- 收工兜底：销号之前先把"台账有、名册没有"的那几条补上。
        #
        # 分工：治本在登记侧 —— `Conductor._register_roster` 一件活登记一次；撞名字是
        # `name_taken` 受控拒绝、交父决定，框架不替它换名。兜底在这里 —— 收工/销号是
        # "这一支要收口了"还缺行，那些子代理连名字都没有，父根本无法按名册名去销它。
        # 补一行只写名册与对照表，不动台账、不动进程。
        #
        # 两件事不是同一件事：派活时不自作主张、收口时必须给得出名字。而"必须给得出"
        # 的对象是"真跑过"的号 —— 没跑过的号（被派活闸拒掉的）永远没有名字；写口拒过
        # 但真跑了的号，会在这里拿到一个从未发过的新名字（`roster_repair` 补，add 行带
        # `named_after_run` / `requested_name` / `refusal_code` 三格留痕，被拒的那个名字不复用）。
        # 下面把"谁补成了什么"原样写进回执 —— 否则读回执的人会以为名字丢了。
        repaired = 0
        try:
            repaired, _repair_why, _repair_skipped = self.roster_repair(owner=str(owner))
        except Exception as exc:  # noqa: BLE001 —— 兜底失败不许带走这次销号
            repaired, _repair_why, _repair_skipped = 0, f"{type(exc).__name__}: {exc}", []
        named_notes: list[str] = []
        for x in (getattr(self, "last_repair_named", None) or []):
            if str(x.get("requested_name") or ""):
                named_notes.append(
                    f"补名：{x.get('task_id')} 当初点名的 {x.get('requested_name')} 被拒"
                    f"（{x.get('refusal_code')}），它现在叫 {x.get('name')}"
                    "（跑过之后补的新名字；被拒的那个不复用）")
            else:
                named_notes.append(f"补名：{x.get('task_id')} 补成 {x.get('name')}")
        tid, problem = self.resolve_down(owner=owner, name=str(name))
        if problem:
            if self._is_retired(owner, str(name)):
                return {"ok": False, "action": "refused", "report": {},
                        "why": [f"{name} 已经销号过（业主 B1：名字永久不复用）"]}
            return {"ok": False, "action": "refused", "report": {}, "why": [problem]}
        if self._is_retired(owner, str(name)):
            return {"ok": False, "action": "refused", "report": {},
                    "why": [f"{name} 已经销号过（业主 B1）"]}
        # ---- 程序闸（G2，业主 2026-10-26 第 ① 条：「注销前检测的能力」）
        #
        # 这一闸挡的是"名字销了、程序还在跑"：昨晚盘上有十五个野 python 进程，谁起的、
        # 谁该停都读不出来，而销号之后连"这台程序是谁的"这个线索也没有了。
        #
        # 为什么"还在跑"这一档排在静默闸之前：静默闸读的是"无工作 ∧ 无计时器 ∧ 无活跃子"，
        # 而一台程序可以在三样都读成"没有"的情况下继续跑 —— 无主的程序计时器（`task_id`
        # 空：框架自己的八个 `program_span` 调用点一个都不传台账号）在时钟读数里是一条不挂
        # 名字的流水，在三态里一句话都没有；而"账上说收口了、进程还在"那一档连计时器都
        # 不是。所以"它名下还有程序在跑"这句话必须由读得到程序的那一格先说：静默闸的拒信
        # 会把一台程序读成"一条挂着到点时刻的计时器"（到点时刻读不到），父照着那句话
        # 处置不了它。
        #
        # 为什么"读不成"那一档反过来排在静默闸之后：时钟簿记坏掉时，静默闸与这一闸都读
        # 不成，而"读不到它是不是静默"是更根本的那一句（它连三态都定不了）。让静默闸按
        # 既有口径先说话，这一闸在后面兜底：静默闸放行了而程序那一格没查成 ⇒ 仍然不销
        # （fail-closed，把"没查成"折成"没有在跑的程序"正是这一闸最该挡的那一次折叠）。
        from .conductor import programs_refusal as _programs_refusal

        try:
            progs = cond.programs_in_subtree(tid)
        except Exception as exc:  # noqa: BLE001 —— 读侧自己炸了也是"没查成"
            progs = {"checked": False, "running_count": 0, "running": [],
                     "reason": f"{type(exc).__name__}: {exc}"}
        if progs.get("checked") and int(progs.get("running_count") or 0) > 0:
            ref = _programs_refusal(progs, lead=f"{name}（{tid}）")
            return {"ok": False, "action": "refused", "report": {},
                    "why": [ref["why"]], "reading": dict(progs),
                    "blocking": list(ref["blocking"]),
                    "missing": list(ref["missing"]),
                    # 空串：拦它的不是静默闸（三态那一格），而是"账上还有进程在跑"。
                    "refusal_code": ref["code"],
                    "programs": list(ref["programs"])}
        # ---- 静默闸（业主 2026-10-26：「销号可以也只可针对静默子代理」）
        #
        # 落点与理由：销号是不可逆的那一类动作（名字永久不复用，业主 B1），而"它还会不会
        # 醒过来"只有时钟读得出来。不静默的三档各自给人一条不同的下一步，所以拒信要分开说。
        from .conductor import (AGENT_STATE_FLYING, AGENT_STATE_STANDBY,
                                AGENT_STATE_UNKNOWN, RETIRE_REFUSAL_TARGET_NOT_SILENT,
                                retire_refusal)

        def _refused_not_silent(got: Mapping[str, Any]) -> dict[str, Any]:
            """目标不静默的拒信：措辞只有 `conductor.retire_refusal` 一处。"""
            ref = retire_refusal(got, tid=tid, name=str(name))
            report: dict[str, Any] = {}
            state = str(got.get("state") or "")
            if state == AGENT_STATE_FLYING:
                report = self.latest_report_of(task_id=tid, role=str(got.get("role") or ""))
            elif state == AGENT_STATE_STANDBY and not got.get("waiters"):
                kids = self.active_children_of(task_id=tid)
                briefs: list[dict[str, Any]] = []
                if kids.get("checked"):
                    child_rows, _bad = self.roster_rows(tid)
                    for k in kids.get("rows", []):
                        kid_name, _why = self.name_of(owner=tid,
                                                      task_id=str(k.get("task_id") or ""))
                        brief = next((str(x.get("brief") or "") for x in child_rows
                                      if str(x.get("name") or "") == kid_name), "")
                        briefs.append({"name": kid_name or "（未登记）",
                                       "role": str(k.get("role") or ""),
                                       "brief": brief, "state": str(k.get("state") or "")})
                if briefs:
                    report = {"children": briefs}
            return {"ok": False, "action": "refused", "report": report,
                    "why": [ref["why"]], "reading": dict(got),
                    "refusal_code": ref["code"],
                    "target_state": state,
                    "target_state_label": str(got.get("state_label") or ""),
                    "blocking": list(ref["blocking"])}

        try:
            gate = cond.retire_state_of(tid)
        except Exception as exc:  # noqa: BLE001 —— 读侧自己炸了也是"没读成"
            return {"ok": False, "action": "refused", "report": {},
                    "why": [f"三态读数没读成（{type(exc).__name__}: {exc}）⇒ "
                            "读不到它是不是静默，不许销（fail-closed）"],
                    "refusal_code": RETIRE_REFUSAL_TARGET_NOT_SILENT,
                    "target_state": AGENT_STATE_UNKNOWN, "blocking": []}
        if not gate.get("silent"):
            return _refused_not_silent(gate)
        # ---- 程序闸的兜底那一档：静默闸放行了，而程序那一格没查成 ⇒ 仍然不销。
        # 排在这里的理由见上面那一段（时钟坏了时"读不到它是不是静默"是更根本的那一句）。
        if not progs.get("checked"):
            return {"ok": False, "action": "refused", "report": {},
                    "why": [(f"{name}（{tid}）这一支的程序读数没查成"
                             f"（{progs.get('reason') or '没查成'}）⇒ 不知道它名下还有没有"
                             "程序在跑，不许销（fail-closed）；这一格不是『一个都没有』")],
                    "reading": dict(progs)}
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
        # ---- 孤儿闸（「最终 final 时应该是 M 下整棵树都已销号」）
        #
        # 这一闸只挡一件事：先销父、把静默的子留到以后。它必须存在，因为那种销法
        # 会永久孤儿化——销号只发给"直接子代理"（`_do_retire` 与 `conductor.retire_child`
        # 都只认自己名册里的那一层），一支的子代理只有它这一个父能销；父一销号，名字
        # 永久不复用、不会再有下一轮，那些子代理就再也没有任何代理有权限销它们。
        # 于是 `Conductor.retire_integrity` 永远不 complete、`final` 被结构完整性闸永久拒
        # —— 这就是"深树永远清不完"的真身。
        #
        # 为什么放在静默闸之后：静默闸说的是"它自己能不能销"（在飞/待机/读不到三档
        # 各有各的下一步，且各带 `refusal_code`），而这一闸说的是"销了它会不会留下孤儿"。
        # 父非静默时（名下有活跃子）根本走不到这里，所以两闸不会抢话；反过来，父静默、
        # 子也静默（子只是"没销"而不是"还在跑"）时，静默闸放行，这一闸接住。
        #
        # 为什么级联那条路不会被它误伤：级联是"先深后浅"，轮到 A1 时 B1 的名册项已经
        # 标了 retired（`retire` 先写台账、再写名册，两处都落完才返回），所以这里读到的
        # `retired` 为真、`rows` 为空、放行。判据见
        # `tests/test_cascade_retire_closes_the_tree.py::test_a_the_cascade_path_does_not_trip_the_orphan_gate`。
        left = self._children_left_behind(tid)
        if not left.get("checked"):
            return {"ok": False, "action": "refused", "report": {},
                    "why": [(f"{name}（{tid}）名下还有没有未销的子代理这一格读不成"
                             f"（{left.get('reason')}）⇒ 不知道销它会不会留下孤儿，"
                             "不许销（fail-closed）")],
                    "reading": reading,
                    "cascade": {"count": 0, "ids": [], "levels": [], "kept": []}}
        if left.get("rows"):
            rows_left = list(left["rows"])
            named = "、".join(f"{r['name']}（{r['id'] or '编号未读到'}）"
                              for r in rows_left[:8])
            more = f" 等 {len(rows_left)} 个" if len(rows_left) > 8 else ""
            return {"ok": False, "action": "refused", "report": {},
                    "why": [(f"还没销 {name}：它名下还有 {len(rows_left)} 个名册项没有销号"
                             f"（{named}{more}）。为什么不许先销父、把子留到以后：销号只发给"
                             "直接子代理，而这一支的子代理只有它这一个父能销 —— 父一旦销号，"
                             "名字永久不复用（业主 B1）、不会再有下一轮，那些子代理就再也"
                             "没有任何代理有权限销它们（别的代理都不是它们的父）⇒ 整棵树"
                             "永远清不完、`final` 被结构完整性闸永久拒。正路只有一条：用 "
                             f"`conductor.retire_child(child_name={name})` —— 那一件会从最深"
                             "的开始把这一支一起销号（先叶子后父），销完这一支就没有"
                             "「留下没销的子」了")],
                    "reading": reading,
                    "cascade": {"count": 0, "ids": [], "levels": [],
                                "kept": [{"id": str(r["id"] or r["name"]),
                                          "name": r["name"],
                                          "why": "还在它名下的名册上、没销号（父一销号，"
                                                 "就再没有任何代理有权限销它）"}
                                         for r in rows_left]}}
        # ---- 先撤兜底计时器（静默可销号，但销号必须把那条表
        #      撤掉并落抑制标记，否则"号已销、计时器又长回来"是不可逆的鬼读数）。
        #
        # 为什么放在台账那一笔之前：两个方向都会留半笔，但只有一个是可重试的 ——
        #   clock-first 失败 ⇒ "叫不醒了、名字还没销"（可重试）；
        #   settle-first 失败 ⇒ "已销号但仍会醒"（不可逆）。
        killed = clock.kill_lifeline(getattr(self.store, "root", "") or "",
                                     task_id=str(tid), reason=str(reason or ""))
        if not killed.get("checked"):
            return {"ok": False, "action": "refused", "report": {},
                    "why": [(f"{name}（{tid}）的兜底计时器没撤成"
                             f"（{killed.get('reason') or '没查成'}）⇒ 一个字节都没落盘，"
                             "重试即可（反方向会是『已销号却还会被叫醒』，不可逆）")],
                    "lifeline": killed}
        # ---- 落定台账那一行
        #
        # 顺序是判据本身：先落台账、再写名册。反过来先写名册时，台账那一笔要是炸了，
        # 盘上就是"名字已销、那一行还占着扇出名额"—— 重试会被"已经销号过"挡住，
        # 名额永远回不来。这个方向失败时两处都还没动（可重试），而它成功时
        # "销号即腾出名额"在盘上已经成立。
        settled = self.settle_retired_row(tid, name=str(name), reason=str(reason))
        if not settled.get("checked"):
            return {"ok": False, "action": "refused", "report": {},
                    "why": [(f"{name}（{tid}）的台账那一行没落定终态"
                             f"（{settled.get('reason') or '没查成'}）⇒ 名额没腾出来，"
                             "整笔销号不作数（先写台账、再写名册，两处一起才算销号）")],
                    "reading": reading, "slot_freed": False, "settle": dict(settled)}
        ok, why = cond.note_edge_release(owner, child_task_id=tid, attempt=1)
        if not ok and "已经记过" not in why:
            return {"ok": False, "action": "refused", "report": {}, "why": [why],
                    "reading": reading}
        at = _now_iso()
        # ⑤（业主 2026-11-02）：销号要标死这个名字绑过的全部号，不只当前号。
        # "读 bind 历史 + 写销号三笔"必须在同一个 per-owner 临界区：临界区外新来的
        # bind 会落在"读历史"与"写销号"之间，那个号就漏掉了（漏号 = 永久可唤醒，
        # 不可逆）。锁序不变：`settle` 与 `note_edge_release` 都在这一句之前做完。
        slot = ""
        surface_note = ""
        with _roster_section(self.root, owner):
            retired_ids = self._bound_task_ids(owner, name=str(name))
            if str(tid) not in retired_ids:
                retired_ids.append(str(tid))
            wrote_roster, why_r = append_jsonl(roster_path(self.root, owner),
                                               {"kind": "retire", "owner": owner, "name": str(name),
                                                "task_id": tid, "task_ids": retired_ids,
                                                "branch": branch, "by": str(by_task_id),
                                                "reason": str(reason or ""),
                                                "reading": reading, "at": at})
            wrote_index, why_i = append_jsonl(roster_index_path(self.root, owner),
                                              {"kind": "retire", "owner": owner, "name": str(name),
                                               "task_id": tid, "task_ids": retired_ids,
                                               "reason": str(reason or ""), "at": at})
            wrote_retired, why_x = True, ""
            for one in retired_ids:
                ok_one, why_one = append_jsonl(retired_path(self.root, owner),
                                               {"owner": owner, "name": str(name),
                                                "task_id": one,
                                                "role": str(row.get("role") or ""), "at": at,
                                                "reason": str(reason or ""),
                                                "branch": branch})
                if not ok_one:
                    wrote_retired, why_x = False, why_one
                    break
            if not (wrote_roster and wrote_index and wrote_retired):
                return {"ok": False, "action": "refused", "report": {},
                        "why": [f"退役没写全（名册={wrote_roster}/{why_r} "
                                f"对照表={wrote_index}/{why_i} "
                                f"销号={wrote_retired}/{why_x}）"],
                        "reading": reading}
            # S1n（业主补充）：退役 ⇒ 面归还"可分配池"（名字不回收、面回收）。
            # 归还前先归档；归档失败 ⇒ 槽位停在"待释放"，读数里如实写（不入池）。
            slot = next((str(r.get("surface") or "") for r in self.roster_rows(owner)[0]
                         if str(r.get("name") or "") == str(name)), "")
            if slot:
                state, why_s = self.surface_release(owner=owner, name=str(name), slot=slot)
                surface_note = (f"面 {slot} 已归还池里" if state == "空闲"
                                else f"面 {slot} 停在待释放（{why_s}）")
        return {"ok": True, "action": "retired", "report": {},
                # 级联读数（Q13）：这一笔实际销掉的只有目标本身 —— 逐层收掉静默子树
                # 那件事在 `conductor.retire_child`（先深后浅、整笔不销或整支销完）。
                # 这一格在这里给，是为了让两个入口的回执同一套键（形那一入口的模型
                # 也读得到"这一笔销了几个 / 还有谁没销"），而不是让"没级联"看起来像
                # "级联了但没读出来"。
                "cascade": {"count": 1, "ids": [tid], "levels": [0], "kept": []},
                "why": [f"{name} 退役：{branch}（子已停 + 它名下无活跃子代理）"]
                       + (["名额已腾出：它那一行还在飞（"
                           f"{settled.get('status_before')}）⇒ 已落终态 "
                           f"{settled.get('status_after')}，下一次 summon 重新算占位"]
                          if settled.get("was_occupying") else [])
                       + ([surface_note] if surface_note else [])
                       + named_notes,
                "surface": slot, "reading": reading,
                "slot_freed": bool(settled.get("was_occupying")),
                "settle": dict(settled)}

    # ------------------------------------------------------------ 链式转发（业主 2026-10-26 裁定）
    #
    # 业主原话（唯一权威）：「M的秘书发给000005的秘书消息有链000005->000012->000024，
    # 然后000005的秘书继续发给下级秘书，直到000024的秘书收到后才具体读消息内容」。
    #
    # 三个角色分工（每一跳都由某一个 Secretary 实例做，日志在 `relay.jsonl`）：
    #   - `relay_out`：发送方的秘书 —— 把正文交给链上第一跳的秘书，载荷带"剩余链"；
    #   - `relay_in`：每一跳的秘书 —— 只看剩余链的头，继续交给下一跳的秘书；
    #     `content_read=False`：正文对被转发的那一位代理本人一个字都不露；
    #   - 链尾那一跳的 `relay_in`：`deliver_local` 把正文交给它服务的那一个代理。
    # 回执沿调用栈回传（同一个 relay_id），发送方拿到 `delivered_to` 与每跳的时间。

    def relay_out(self, *, chain: Sequence[str], body: str, subject: str = "",
                  sender_role: str = "") -> dict[str, Any]:
        """发送方的秘书：把正文交给链上第一跳的秘书（载荷里的 `remaining_chain`）。

        返回三态回执（键集在所有分支上相同）：
        `checked` / `status`（`delivered` / `refused` / `unknown`）/ `relay_id` /
        `delivered_to`（链尾那一个的绝对编号；只有 `delivered` 非空）/ `hops`
        （每跳：`hop` / `of` / `at` / `elapsed_us` / `delta_us` / `secretary_task_id` /
        `secretary_role` / `mode`（`forward` / `deliver`）/ `from` / `to` /
        `remaining_chain` / `content_read` / `item_id` / `relay_id`）/ `problems` /
        `refused` / `error` / `item_id`。每跳另带两格时间：`elapsed_us`（从发送方
        秘书起手那一刻算起的累计微秒数）与 `delta_us`（这一跳自己花掉的微秒数）——
        为什么两格都给：只给累计值时"哪一跳慢"要靠相邻相减，而相减在只有这一份
        读数的人手里做不了。

        ## 为什么"转发台账写不成就不发"
        这一条链的全部可审计性就在那份台账上（谁在哪一跳收到过、正文有没有给代理本人
        看）。台账写不成而正文照样往下走，回执会说 `delivered` 而盘上一条记录都没有
        —— 那正是本仓最忌的"回执说谎"。所以第一跳的台账写不成 ⇒ `unknown` + 拒信，
        正文一步都不动（fail-closed 只落在"盘上能不能留下这件事"这一格）。
        """
        out: dict[str, Any] = {
            "checked": False, "status": "unknown", "relay_id": "", "delivered_to": [],
            "hops": [], "problems": [], "refused": "", "error": "", "item_id": "",
        }

        def _stop(code: str, why: str, *, status: str = "refused") -> dict[str, Any]:
            out.update(status=status, refused=code, error=why)
            return out

        hops = [str(x) for x in (chain or ())]
        mine = str(self.task_id or "")
        if len(hops) < 2:
            return _stop("broken_chain",
                         f"链只有 {len(hops)} 跳 ⇒ 没有可发给的下一跳（链至少要有一级下级）")
        if hops[0] != mine:
            return _stop("broken_chain",
                         f"链头是 {hops[0]}，而这一位秘书服务的是 {mine or '（没绑实例）'}"
                         " ⇒ 这条链不是从它出发的，不转")
        t0 = time.perf_counter()
        t_hop = t0
        rest = hops[1:]
        peer, why = self._peer_secretary(rest[0])
        if peer is None:
            return _stop("not_in_roster", f"第一跳 {rest[0]} 的秘书拿不到：{why}",
                         status="unknown")
        rec = self._relay_rec(hop=1, of=len(hops), mode="forward", chain=hops,
                              remaining_chain=rest[1:], content_read=False,
                              item_id="", t0=t0, t_hop=t_hop, subject=subject,
                              sender_role=sender_role, to=rest[0])
        ok, problem, rid = append_jsonl_stamped(relay_path(self.root), rec,
                                                field="relay_id", prefix=RELAY_ID_PREFIX)
        if not ok or not rid:
            return _stop("relay_unwritten",
                         f"转发台账没写成（{problem or '没有发到号'}）⇒ 正文一步都没动"
                         "（这一条链的每一跳都要在盘上留得下，回执才不是一句空话）",
                         status="unknown")
        rec["relay_id"] = rid
        out.update(checked=True, relay_id=rid)
        down = peer.relay_in(relay_id=rid, chain=rest, remaining_chain=rest[1:], body=body,
                             subject=subject, sender_role=sender_role, hops_total=len(hops),
                             t0=t0, full_chain=hops)
        out["hops"] = [dict(rec)] + list(down.get("hops") or [])
        out["problems"].extend(str(p) for p in (down.get("problems") or ()))
        out["delivered_to"] = list(down.get("delivered_to") or ())
        out["item_id"] = str(down.get("item_id") or "")
        out["status"] = str(down.get("status") or "unknown")
        out["refused"] = str(down.get("refused") or "")
        out["error"] = str(down.get("error") or "")
        return out

    def relay_in(self, *, relay_id: str, chain: Sequence[str],
                 remaining_chain: Sequence[str], body: str, subject: str = "",
                 sender_role: str = "", hops_total: int = 0,
                 t0: float = 0.0, full_chain: Sequence[str] = ()) -> dict[str, Any]:
        """某一跳的秘书收到一次转发：只看剩余链的头，链尾才把正文交给代理本人。

        `chain` 的头必须就是这一位秘书服务的那个代理（对不上 ⇒ 受控拒绝，不猜谁该读）。
        `remaining_chain` 是"还要往下走的那几跳"：本方法只读它的第一个元素，再把
        `remaining_chain[1:]` 交给下一跳的秘书 —— 这就是"只看链头"的机器形态。
        `content_read` 在除链尾以外的每一跳都是 `False`：正文只随载荷往下走，
        不进任何一位被转发的代理的板项。
        `full_chain` 是发送方写的那条完整链（只用于链尾那一句正文的抬头：读到正文的
        代理要看得见"它从哪来"，而不是只看见自己那一段）。转发逻辑不读它。
        """
        out: dict[str, Any] = {
            "checked": False, "status": "unknown", "relay_id": str(relay_id or ""),
            "delivered_to": [], "hops": [], "problems": [], "refused": "", "error": "",
            "item_id": "",
        }
        hops = [str(x) for x in (chain or ())]
        left = [str(x) for x in (remaining_chain or ())]
        mine = str(self.task_id or "")
        if not hops or hops[0] != mine:
            out.update(status="refused", refused="broken_chain",
                       error=(f"载荷的链头是 {hops[0] if hops else '（空）'}，而这一位秘书"
                              f"服务的是 {mine or '（没绑实例）'} ⇒ 不猜谁该读，退回"))
            return out
        total = int(hops_total or len(hops))
        hop_no = total - len(hops) + 1
        t0 = t0 or time.perf_counter()
        t_hop = time.perf_counter()
        if not str(relay_id or ""):
            out.update(status="unknown", refused="relay_unwritten",
                       error="载荷没有转发编号 ⇒ 这一跳落不了台账（没查成）")
            return out
        if left:
            nxt = left[0]
            peer, why = self._peer_secretary(nxt)
            rec = self._relay_rec(hop=hop_no, of=total, mode="forward", chain=hops,
                                  remaining_chain=left[1:], content_read=False,
                                  item_id="", t0=t0, t_hop=t_hop, subject=subject,
                                  sender_role=sender_role, to=nxt)
            rec["relay_id"] = str(relay_id)
            if peer is None:
                rec.update(status="unknown", refused="not_in_roster",
                           note=f"{nxt} 的秘书拿不到：{why}")
                ok, problem = append_jsonl(relay_path(self.root), rec)
                out.update(checked=ok, status="unknown", refused="not_in_roster",
                           error=(f"下一跳 {nxt} 的秘书拿不到：{why} ⇒ 链停在第 {hop_no} 跳"
                                  + ("" if ok else f"（这一跳的台账也没写成：{problem}）")))
                out["hops"] = [dict(rec)]
                return out
            ok, problem = append_jsonl(relay_path(self.root), rec)
            if not ok:
                out.update(status="unknown", refused="relay_unwritten",
                           error=(f"第 {hop_no} 跳的转发台账没写成（{problem}）⇒ 正文"
                                  "不再往下走（这一跳不可审计，就不能说它发生过）"))
                return out
            out["checked"] = True
            down = peer.relay_in(relay_id=str(relay_id), chain=left, remaining_chain=left[1:],
                                 body=body, subject=subject, sender_role=sender_role,
                                 hops_total=total, t0=t0, full_chain=list(full_chain) or hops)
            out["hops"] = [dict(rec)] + list(down.get("hops") or [])
            out["problems"].extend(str(p) for p in (down.get("problems") or ()))
            out["delivered_to"] = list(down.get("delivered_to") or ())
            out["item_id"] = str(down.get("item_id") or "")
            out["status"] = str(down.get("status") or "unknown")
            out["refused"] = str(down.get("refused") or "")
            out["error"] = str(down.get("error") or "")
            return out
        # ---- 链尾：只有这一跳把正文交给它管的那一个代理
        item_id, problem = self.deliver_local(
            body=body, chain_text="->".join(str(x) for x in (full_chain or hops)),
            origin=str(sender_role or S.CONDUCTOR_ROLE),
            subject=subject, relay_id=str(relay_id))
        rec = self._relay_rec(hop=hop_no, of=total, mode="deliver", chain=hops,
                              remaining_chain=[], content_read=True, item_id=item_id,
                              t0=t0, t_hop=t_hop, subject=subject,
                              sender_role=sender_role, to=mine)
        rec["relay_id"] = str(relay_id)
        ok, why = append_jsonl(relay_path(self.root), rec)
        if not ok:
            out["problems"].append(f"链尾那一跳的台账没写成：{why}（正文已经交给了 {mine}）")
        if item_id:
            out.update(checked=True, status="delivered", delivered_to=[mine],
                       item_id=item_id, hops=[dict(rec)])
        else:
            out.update(checked=True, status="unknown", error=problem,
                       problems=out["problems"] + [problem], hops=[dict(rec)])
        return out

    def deliver_local(self, *, body: str, chain_text: str, origin: str = "",
                      subject: str = "", relay_id: str = "") -> tuple[str, str]:
        """链尾：把正文交给这一位秘书服务的那一个代理（整条链上唯一"读内容"的一跳）。

        手法沿用既有的板项通道（`conductor.open_item` + `set_item_detail`）：收件人
        写这一个代理的台账号，于是它下一次进循环就在信箱里读到这一条；中途各跳
        一条板项都不开 —— 这是"不把内容给被转发的代理本人看"的全部实现。
        返回 `(板项编号, 问题)`；编号空 = 正文没有交给任何人（不许当"送到了"）。
        """
        cond = self._conductor()
        if cond is None:
            return "", "没有 store ⇒ 打不开板项（正文没有交给任何人）"
        mine = str(self.task_id or "")
        try:
            row = cond._task(mine) or {}
        except Exception as exc:  # noqa: BLE001 —— 读不成是"没查成"
            return "", f"台账读不成（{type(exc).__name__}: {exc}）⇒ 不知道该开给谁"
        if not row:
            return "", f"台账里没有 {mine} 那一行 ⇒ 没有收件人，正文没有交给任何人"
        role = str(row.get("role") or self.role)
        head = f"沿链 {chain_text} 传来的指导" if chain_text else "沿链传来的指导"
        who = f"（{origin} 发出）" if origin else ""
        detail = f"{head}{who}：{body}" + (f"（主题：{subject}）" if subject else "")
        try:
            item_id = cond.open_item(
                kind="notice", role=role, expects="ack", action="notice",
                summary=str(body or "")[:200], called_by=str(origin or S.CONDUCTOR_ROLE),
                parent_task_id=mine, depth=int(row.get("depth") or 1) + 1,
                input_key=f"relay@{relay_id or mine}")
        except Exception as exc:  # noqa: BLE001 —— 开不成要如实说
            return "", f"板项没开成（{type(exc).__name__}: {exc}）⇒ 正文没有交给 {mine}"
        got, problem = cond.set_item_detail(item_id, detail)
        if problem:
            return item_id, f"板项 {item_id} 的正文没写进去（{problem}）"
        return item_id, "" if got else f"板项 {item_id} 的正文是空的"

    def _relay_rec(self, *, hop: int, of: int, mode: str, chain: Sequence[str],
                   remaining_chain: Sequence[str], content_read: bool, item_id: str,
                   t0: float, t_hop: float, subject: str, sender_role: str,
                   to: str) -> dict[str, Any]:
        """一条转发记录的公共字段（`relay_out` 与 `relay_in` 共用同一张表）。

        两格时间用 `time.perf_counter`（高分辨率）：`time.monotonic` 在本机实测
        只有毫秒级粒度，一跳几十微秒的转发会被一律读成 0 —— 那等于没有"每跳时间"。
        """
        now = time.perf_counter()
        return {"kind": "relay_hop", "hop": int(hop), "of": int(of), "mode": str(mode),
                "secretary_role": self.role, "secretary_task_id": str(self.task_id or ""),
                "from": str(self.task_id or ""), "to": str(to or ""),
                "chain": [str(x) for x in chain],
                "remaining_chain": [str(x) for x in remaining_chain],
                "content_read": bool(content_read), "item_id": str(item_id or ""),
                "subject": str(subject or ""), "sender_role": str(sender_role or ""),
                "elapsed_us": int(max(0.0, now - float(t0 or now)) * 1_000_000),
                "delta_us": int(max(0.0, now - float(t_hop or now)) * 1_000_000),
                "at": _now_iso()}

    def _peer_secretary(self, task_id: str) -> tuple[Any, str]:
        """链上下一跳那一位秘书（角色从台账读；只设 `task_id`，不写存活标记）。

        为什么不调 `bind_task`：那一步会写 `<role>-<task>.alive`，把它读成"有一个
        进程正在跑"—— 而转发是一次请求，不是一次接管。存活标记只该由真正跑起来的
        循环写（`agent_loop` 那一路），秘书替它写等于伪造"它活着"。
        """
        cond = self._conductor()
        if cond is None:
            return None, "没有 store ⇒ 读不到台账号对应的角色"
        try:
            row = cond._task(str(task_id or "")) or {}
        except Exception as exc:  # noqa: BLE001 —— 读不成是"没查成"
            return None, f"台账读不成（{type(exc).__name__}: {exc}）"
        if not row:
            return None, f"台账里没有 {task_id} 这一行"
        role = str(row.get("role") or "")
        if not role:
            return None, f"{task_id} 那一行没有角色 ⇒ 不知道交给哪个秘书"
        try:
            peer = Secretary(role, root=self.root, store=self.store, sid=self.sid)
        except Exception as exc:  # noqa: BLE001 —— 造不出秘书要如实说
            return None, f"造不出 {task_id} 的秘书（{type(exc).__name__}: {exc}）"
        peer.task_id = str(task_id)
        return peer, ""

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
        """这个名字是不是销过号（写侧的复用闸）。

        走 :meth:`retired_ledger` 而不是 `retired_names`：语义一个字不改（"读到一行
        名字对得上"就是真），但坏行 / 认不出来的行现在留在 `self.last_retired_ledger`
        里。写侧的"复活"风险（`draft/145` H14：`bad` 被 `_bad` 丢掉 ⇒ 已销号的名字
        还能被 `reuse` 回来）从这里开始有了一个可读的读数；本方法仍只回那个布尔。
        """
        got = self.retired_ledger(owner, trusted_shard=True)
        return any(str(r.get("name") or "") == str(name) for r in (got.get("rows") or []))

    def _retired_name_of_task_id(self, owner: str, task_id: str) -> str:
        """这个号在销号名单里吗 ⇒ 那一行的名字（空串 = 没命中）。

        与 :meth:`_is_retired` 同一个读口（名字那一半），这一格问的是"号"那一半：
        名字可以在销号后被复用检查挡住，而号那一侧改前完全敞开（`draft/149` §1.4-④：
        已销号的号换个新名字重新登记成功 ⇒ 新名字永远销不掉 ⇒ 永久孤儿）。
        """
        tid = str(task_id or "")
        if not tid:
            return ""
        got = self.retired_ledger(owner, trusted_shard=True)
        for r in got.get("rows") or []:
            if str(r.get("task_id") or "") == tid:
                return str(r.get("name") or "")
        return ""

    def _children_left_behind(self, tid: str) -> dict[str, Any]:
        """销 `tid` 之前：它名下还有哪些"只有它这一个父能销"的名册项。

        返回 `{"checked","rows":[{"id","name","role"}],"reason"}` —— 三态：
        `checked=False` 是"读不成"（调用方一律 fail-closed 不销），空 `rows` 才是
        "一个都没落下"（那是查过了的结论）。

        ## 为什么读名册而不读台账
        能被销的对象只有名册项：`resolve_down` 只认名册名，`conductor.retire_child`
        也只用名册名指称。所以"孤儿"的精确定义就是"还在这个父的名册上、没销号的那几个"
        —— 台账里有行而名册里没名字的那一类（`unrostered`）本来就没有名字可销，
        它在工具那一侧已经逐条点名，不归这一闸管。

        ## 为什么读折叠后的 `retired` 而不是销号名单文件
        `retire` 写盘是"先台账、再名册"（那一处的注释写了为什么），名册事件的
        `retire` 那一行与销号名单是同一笔的两次落盘。读折叠状态就是读"这一项现在
        算不算销过"，而级联"先深后浅"靠的正是这个格子在轮到父时已经变真。
        """
        out: dict[str, Any] = {"checked": True, "rows": [], "reason": ""}
        try:
            kids, bad = self.roster_rows(tid)
        except Exception as exc:  # noqa: BLE001 —— 读侧自己炸了也是"没读成"
            out["checked"] = False
            out["reason"] = f"{type(exc).__name__}: {exc}"
            return out
        if bad:
            out["checked"] = False
            out["reason"] = f"它名下名册有 {len(bad)} 行读不出来"
            return out
        for kid in kids:
            if bool(kid.get("retired")):
                continue
            name = str(kid.get("name") or "")
            out["rows"].append({"id": str(kid.get("task_id") or ""), "name": name,
                                "role": str(kid.get("role") or "")})
        return out

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
#: 一行靠 `stmt_id` 与命题行对上（2026-10-26，D16）：判档发生在登记之后，号已经在手上。
#: 旧行没有这一格、只有 `statement_sha256`；读侧只为读旧行留一条按 sha 的回退，
#: 新行一律按号（见 :func:`nontriviality_of`）。
NONTRIVIALITY_LEDGER = "nontriviality.jsonl"


def nontriviality_path(root: str | Path) -> Path:
    """档位旁支台账的路径：`out/secretary/nontriviality.jsonl`。"""
    return Path(root) / "out" / "secretary" / NONTRIVIALITY_LEDGER


def _statement_sha(statement_full: str) -> str:
    return hashlib.sha256(str(statement_full or "").strip().encode("utf-8")).hexdigest()


def _tier_from_judge_reply(got: Mapping[str, Any]) -> int | None:
    """从一趟判词里读档位（2026-11-01 起 `decision` 是唯一的主字段）。

    `decision` 可解析 ⇒ 就是它（数字 `2` / `"2"` / `"T2"` 都收敛到 2）；它不是档位时
    才退到 `nontriviality` —— 那是 2026-11-01 之前"两字段两轴"形状的读别名（老结果、
    替身、历史台账），不再向模型索取。两个都读不出来 ⇒ `None` = 判不了（不是 0）。
    """
    level = _nontriviality_level(got.get("decision"))
    if level is not None:
        return level
    return _nontriviality_level(got.get("nontriviality"))


def _tier_from_legacy_decision(row: Mapping[str, Any]) -> int | None:
    """一行旧台账折算出的档位（2026-11-01 词表退场后读旧行的唯一口径）。

    业主 2026-11-01 裁定审美轴三格退场之后，写侧与新行只产生 `T0`…`T4` / `null`；
    但 `out/secretary/<角色>.jsonl` 是 append-only 的，旧行里还有三个词。读旧行时按
    这张表折算（这是"旧词"在源码里仅存的落点，判据钉着它只许出现在这里）：

    | 老 `decision` | 折算出的档位 | 判据 |
    |---|---|---|
    | `T0`…`T4` | 同名档位 | 2026-11-01 那一笔的兼容形状 |
    | `太平凡` | T0 | 这个结论只剩"力气小 ⇒ 落 T0"这一层意思 |
    | `合格` | `judge.nontriviality` / 同号 `nontriviality.jsonl` 那一行；都没有 ⇒ 未判 | 它当年只表示"收"，从不携带档位 |
    | `判不了` | 未判（`None`） | 它是"该判而没判"，不是一档 |

    优先级：decision 能解析成档位 ⇒ 用它；否则 `太平凡` ⇒ 0；否则读 `nontriviality`
    （先看行上的 `judge.nontriviality`，再看同级的 `nontriviality`）。新旧两套字段同时
    出现且冲突时 decision 胜 —— 2026-11-01 起它才是唯一的主字段。

    这一格只回答"这一行说的是哪一档"，不回答"这一行是不是判过了"：`None` 既可能是
    "判不了"也可能是"没查成"，那要读 `judge.checked`（新行）或 `fail_open`（旧行），
    不要把两者折成一档。
    """
    decision = str(row.get("decision") or "")
    level = _nontriviality_level(decision)
    if level is not None:
        return level
    if decision.strip() == "太平凡":
        return 0
    judge = row.get("judge")
    if isinstance(judge, Mapping):
        level = _nontriviality_level(judge.get("nontriviality"))
        if level is not None:
            return level
    return _nontriviality_level(row.get("nontriviality"))


def _level_from_row(row: Mapping[str, Any]) -> int | None:
    """从一行台账读档位（含旧刻度的兼容，唯一读口）。

    旧行（没有 `scale` 标记）里 `0` 是"判不了"；新行（有标记）里 `0` 是 T0。
    这一区分只在这里做一次，理由见 :data:`NONTRIVIALITY_SCALE`。
    """
    level = _nontriviality_level(row.get("nontriviality"))
    if not str(row.get("scale") or "").strip():
        return level if level else None
    return level


def _judged_body_sha(statement_full: str, proof_text: str = "") -> str:
    """判档材料（命题 + 空行 + 证明）的 sha256 —— "判的是哪一版"的唯一算法。

    与 `record_nontriviality` 落进台账的 `judged_body_sha256` 同一个公式（这里是唯一
    实现）：复核的人拿同一份稿按它重算，就能核对那一行判的到底是哪一版材料。
    它不参与关联（关联仍按 `stmt_id` / 旧行回退 sha）—— 只回答"这一次判的是哪一版"。
    """
    return hashlib.sha256(
        (str(statement_full or "") + "\n\n" + str(proof_text or "")).encode("utf-8")
    ).hexdigest()


def append_nontriviality(root: str | Path, *, statement_full: str, level: Any,
                         basis: str = "", role: str = "", task_id: str = "",
                         stmt_id: str = "",
                         effort: Mapping[str, Any] | None = None,
                         text_truncated: bool = False,
                         applicable: bool = True,
                         path_group: int = 0,
                         judged_body_sha256: str = "",
                         landed_body_sha256: str = "",
                         scope: str = "") -> None:
    """追加一行档位读数（append-only；显式 LF，Windows 上不留 CRLF）。

    `level` 给 `None`（或缺省/坏值）⇒ 这一行记的是"判不了"：`nontriviality: null`
    且 `label` 空。判不了照旧落一行 —— 它也是读数（"没人判过"与"台账里没这一条"
    在盘上应当分得开）。

    ## 一个路径一行（NT2，2026-11-15 业主裁定）

    业主口径：「非平凡度应该是一个路径一个，现在的实现是一个命题一个需要补加」。
    所以行上多三格：

    | 格 | 含义 |
    |---|---|
    | `path_group` | 这是第几条证明路径的读数（`>=1`）；`0` = statement-scope（概念行的"不适用"） |
    | `scope` | `"path"` / `"statement"`；旧行没有这一格 ⇒ 按旧语义读（无路径维 = 路径 1） |
    | `judged_body_sha256` | 判的那一刻手里的材料（命题 + 空行 + 证明，见 :func:`_judged_body_sha`） |
    | `landed_body_sha256` | 落盘那一行的 `statement_full` 的 sha —— 与上一格分开记，才能回答"判的是不是落的那一版" |

    旧行（没有 `path_group`）由读侧视为路径 1（改前判的就是 canonical 那份证明）。

    ## 为什么带号（2026-10-26，D16）
    这一行说的是"哪个命题的档位"，而命题行的身份是 `stmt_id`。按正文 sha 关联会把
    "改了一个字"读成"没判过"：真机 mp3-r3 的第 1 行（316 字）就是这样 —— 判档用的是
    登记前的入参，落盘行与它不逐字相同，于是那一档从页面上消失。所以新行必须带号；
    旧行没有这一格 ⇒ 读侧那条按 sha 的回退只为读旧行（见 :func:`nontriviality_of`）。

    `stmt_id` 缺省是空串只服务"没有登记这一笔"的旧调用面与测试直调。判/落拆段之后
    生产面只有一个落点（:meth:`Secretary.record_nontriviality`），它在落之前先要求
    号与路径号：拿不到就不落（并留 `unrecorded` 痕迹），不许再落出 `stmt_id` 为空的
    孤儿读数（真机 4 条对不上任何命题行的行就是这么来的）。

    ## `applicable` 为什么是第四根轴（2026-10-26，D15'）
    "判不了"与"不需要判"是两件事：前者说该判而没判（缺正文 / 被截断 / 没缝），
    后者说这一问对这一行不成立（概念行没有证明正文）。改前它们只能靠 `basis` 那句话
    分辨，于是读侧（`nontriviality_of` 与页面）把两者都读成"没有档位"、印同一个"未判"。
    所以这一格显式落进台账：`applicable=False` 的那一行，`level` 恒为 `None`（不适用
    不可能是某一档），`label` 恒为空串，读侧据它把 `tri` 读成 `not_applicable`。
    老行没有这一格 ⇒ 按 `True` 读（与它们写下来时的语义一致）。

    ## `effort` 为什么也落下来（2026-10-24，B2）
    档位从这一天起是"证明花的力气"给的，而力气是四项读数 + 一个分数。只落档位的话，
    读的人（人、页面、复算脚本）无法判断"这一档是读数给的还是模型随口给的"——
    而后者正是改前那个形态。所以四项读数、分数与边界表里的那一档一起落进这一行：
    复算的人拿 `proof_effort_readings` 的几项读数一比，就能看出秘书判档时手里有什么材料。

    `text_truncated` 同理落下来：它是"这一行判不了"的一个具体原因，与"缺某项读数"、
    "判了"三者在盘上必须分得开（三态纪律的第四格：输入不完整也是一种没查成）。
    """
    path = nontriviality_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    # 不适用的那一档不许同时带档位（两件事折进一行就等于把"不存在这一问"读成"判了"）
    got = _nontriviality_level(level) if applicable else None
    no = int(path_group or 0)
    row = {"at": _now_iso(), "stmt_id": str(stmt_id or ""),
           "statement_sha256": _statement_sha(statement_full),
           "statement_chars": len(str(statement_full or "")),
           # 刻度标记：读侧靠它区分"0 = T0"与旧行的"0 = 判不了"（见 NONTRIVIALITY_SCALE）
           "scale": NONTRIVIALITY_SCALE,
           "nontriviality": got, "label": nontriviality_label(got),
           # 判档这一格对这一行适不适用（见上面那一段）；缺省 True = 与老行同一读法
           "applicable": bool(applicable),
           # 路径维（见上面那一段）：0 = statement-scope；>=1 = 第几条证明路径
           "path_group": no,
           "scope": str(scope or ("path" if no >= 1 else "statement")),
           "judged_body_sha256": str(judged_body_sha256 or ""),
           "landed_body_sha256": str(landed_body_sha256 or ""),
           "basis": str(basis or ""),
           "effort": dict(effort or {}), "text_truncated": bool(text_truncated),
           "role": str(role or ""), "task_id": str(task_id or "")}
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        # `default=str` 与全仓同一口径（`tests/test_json_dumps_has_a_default.py`）：这一行是
        # append-only 档位台账的唯一写口，它抛出去会丢一行读数而调用方看不出来。
        handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True, default=str) + "\n")


def _row_matches_stmt_id(row: Mapping[str, Any], stmt_id: str) -> bool:
    """按号关联的唯一判据：号非空且与这一行的 `stmt_id` 相同（空号永不命中）。

    为什么单独一格：读侧"按号查"必须是一个能被打桩的判据（反真空判据把它打桩成
    恒不命中，看"正文一改档位还在不在"那条会不会红）；而空号不许命中空号 ——
    旧行没有 `stmt_id`，把它们当成"号为空的那一条"会让所有旧行并成一条。
    """
    want = str(stmt_id or "").strip()
    if not want:
        return False
    return str(row.get("stmt_id") or "").strip() == want


#: 路径号的读法（唯一一处）：新行读 `path_group`；旧行没有这一格 ⇒ 视为路径 1
#: （改前判的就是 canonical 那份证明）。`0` 是 statement-scope（概念行的"不适用"），
#: 它不参与命题级的 min —— 这一格的语义由调用方（`_fold_nontriviality`）先按
#: `applicable` 分出去，本函数只回答"这一行属于第几条路径"。
def _row_path_group(row: Mapping[str, Any]) -> int:
    raw = row.get("path_group")
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return 1
    try:
        no = int(raw)
    except (TypeError, ValueError):
        return 1
    return no if no >= 1 else 0


#: 档位台账的进程内索引：`路径 -> (键, (按号, 按 sha))`，键 = `(st_mtime_ns, st_size)`。
#:
#: 为什么要有它（2026-10-27，R-BE1 的 ⑥-3）：`nontriviality_of` 是逐条命题调的（收工读数与
#: 网页那一栏都是逐条问），而它每次都把整份 `out/secretary/nontriviality.jsonl` 读一遍、
#: 逐行 `json.loads` —— 400 条命题 × 400 行台账 = 每条命题 400 次解析。
#:
#: 键取 `(st_mtime_ns, st_size)`：`append_nontriviality` 是追加写 ⇒ 台账一变键就变，下一次
#: 调用立刻读到新值（判据 `tests/test_nontriviality_ledger_is_read_once.py` 两个方向都钉着）。
#: 每个路径只留最新一版（不按"每一版"累积），所以长跑里它不会无限长大。
#:
#: 两个索引都存整串行（按 append 顺序）：读侧要按 `(stmt_id, path_group)` 折叠，
#: "最后一行胜"只是折叠规则的一部分（见 `_fold_nontriviality`），不是索引的语义。
#:
#: 已知边界（刻意的）：缓存里放的是解析后的行。`nontriviality_of` 只读它，返回的 dict
#: 是新造的（`effort` 那一格也复制了），所以调用方就地改返回值不会污染缓存；但谁要是绕过
#: 本函数直接拿缓存里的行去改（本模块不导出它），改的就是"这个进程眼里的台账"。
_NT_INDEX_CACHE: dict[str, tuple[tuple[int, int],
                                tuple[dict[str, list[dict[str, Any]]],
                                      dict[str, list[dict[str, Any]]]]]] = {}


def _nontriviality_index(path: Path
                         ) -> tuple[dict[str, list[dict[str, Any]]],
                                    dict[str, list[dict[str, Any]]], str]:
    """把台账读成 `(按号, 按 sha, 读不成原因)` —— 同一份文件只解析一次（`mtime_ns+size` 键）。

    两个索引都把每一行按 append 顺序收进列表（改前是"最后一行胜"的标量）。
    为什么要整串：读侧要按 `(stmt_id, path_group)` 折叠成"路径级最后一行"与
    "命题级 = 各路径的历史最小值"，只留最后一行就把路径/历史两样信息都丢了
    （真机错读数：先 T0 后 T3 读回 T3；多路径互相覆盖）。

    坏行（不是 JSON / 不是对象）跳过，与原来一致；"文件读不出来"如实返回原因，由调用方
    落成"没有这条命题的读数"（不是"这条命题是 T1"）。
    """
    try:
        st = path.stat()
        key = (int(st.st_mtime_ns), int(st.st_size))
    except OSError as exc:
        return {}, {}, f"{path} 读不到（{type(exc).__name__}: {exc}）"
    hit = _NT_INDEX_CACHE.get(str(path))
    if hit is not None and hit[0] == key:
        return hit[1][0], hit[1][1], ""
    by_id: dict[str, list[dict[str, Any]]] = {}
    by_sha: dict[str, list[dict[str, Any]]] = {}
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return {}, {}, f"{path} 读不到（{type(exc).__name__}: {exc}）"
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, Mapping):
            continue
        sid = str(row.get("stmt_id") or "").strip()
        if sid:
            by_id.setdefault(sid, []).append(row)
        sha = str(row.get("statement_sha256") or "")
        if sha:
            by_sha.setdefault(sha, []).append(row)
    _NT_INDEX_CACHE[str(path)] = (key, (by_id, by_sha))
    return by_id, by_sha, ""


def _fold_nontriviality(rows: Sequence[Mapping[str, Any]], *, matched_by: str,
                        path_group: int | None = None,
                        path_groups: Sequence[Any] | None = None) -> dict[str, Any]:
    """把同一命题的台账行折叠成一条读数（唯一实现；读侧三处读点共用）。

    ## 折叠规则（业主 2026-11-15 的五条硬约束落到读侧）

    | 规则 | 实现 |
    |---|---|
    | 一个路径一行 | 按 `path_group` 分组；旧行（无这一格）= 路径 1 |
    | 路径级 = 该路径最后一行 | 同一路径重判允许升降（T4 造出梯子 ⇒ 降到 T2 是正常路径） |
    | 命题级 = 各路径非平凡度的最小值 | `level = min(min_of)`，`min_of` 是各路径的历史最小值 |
    | 已有值 ⇒ min(原值, 本次) | 取历史最小值 ⇒ 命题级永不回升（新增路径 / 同路径判得更难都抬不上去） |
    | 部分路径未判 ⇒ `partial=true` | `paths_unjudged` 点名；不许把"部分没判"折成"全判了" |

    为什么路径级用"最后一行"、命题级用"历史最小值"：业主口径里这两条要同时成立。
    路径换了一份更难的证明（T1→T3）⇒ 那条路径的当前值该是 T3；而"命题台账已有值取
    min"⇒ 命题级仍是 T1。两者不矛盾：`paths[].level` 给当前值，`min_of` 给命题级
    这个 min 从哪几个值来（每个路径的历史最小值），读的人能逐行复算。

    ## 返回

    `{tri, level, label, applicable, matched_by, basis, at, stmt_id, effort,
    text_truncated}`（旧键逐字不动）+ `paths` / `min_of` / `paths_unjudged` /
    `partial`。`path_group>=1` 时返回该路径的读数（`level` = 该路径最后一行），
    并把命题级另放在 `statement_level`。
    """
    want_path: int | None = None
    if path_group not in (None, "", 0):
        try:
            want_path = int(path_group)
        except (TypeError, ValueError):
            want_path = None
    expected: list[int] = []
    for raw in (path_groups or ()):
        try:
            no = int(raw)
        except (TypeError, ValueError):
            continue
        if no >= 1 and no not in expected:
            expected.append(no)
    concept: list[Mapping[str, Any]] = []
    by_path: dict[int, list[Mapping[str, Any]]] = {}
    for row in rows:
        # 老行没有 `applicable` 这一格 ⇒ 按 True 读（与它们写下来时的语义一致）
        if not bool(row.get("applicable", True)):
            concept.append(row)
            continue
        no = _row_path_group(row)
        if no < 1:
            # `path_group=0` 却标着 applicable：落行方把 statement-scope 用错了。
            # 读侧按路径 1 处置并留一个可核的读数，不静默丢掉它。
            no = 1
        by_path.setdefault(no, []).append(row)

    def _unjudged(reason: str) -> dict[str, Any]:
        return {"tri": "unknown", "level": NONTRIVIALITY_UNJUDGED, "label": "",
                "applicable": True, "matched_by": matched_by, "stmt_id": "",
                "at": "", "reason": reason, "effort": {}, "text_truncated": False,
                "paths": [], "min_of": [],
                "paths_unjudged": list(expected), "partial": bool(expected),
                "statement_level": None}

    if want_path is not None:
        seq = by_path.get(want_path) or []
        if not seq:
            got = _unjudged(f"第 {want_path} 条路径还没有档位读数")
            got["paths_unjudged"] = [want_path]
            got["partial"] = True
            return got
        last = seq[-1]
        level_here = _level_from_row(last)
        levels = [x for x in (_level_from_row(r) for r in seq) if x is not None]
        floor = min(levels) if levels else None
        floors_all = [min([x for x in (_level_from_row(r) for r in by_path[no])
                           if x is not None] or [None])
                      for no in sorted(by_path)]
        stmt_level = min([x for x in floors_all if x is not None]) if floors_all else None
        return {"tri": ("computed" if level_here is not None else "unknown"),
                "level": level_here, "label": nontriviality_label(level_here),
                "applicable": True, "matched_by": matched_by,
                "stmt_id": str(last.get("stmt_id") or ""),
                "basis": str(last.get("basis") or ""),
                "at": str(last.get("at") or ""),
                "effort": dict(last.get("effort") or {}),
                "text_truncated": bool(last.get("text_truncated")),
                "path_group": want_path,
                "paths": [{"path_group": want_path, "level": level_here,
                           "floor": floor,
                           "label": nontriviality_label(level_here),
                           "at": str(last.get("at") or ""),
                           "stmt_id": str(last.get("stmt_id") or ""),
                           "basis": str(last.get("basis") or ""),
                           "judged_body_sha256": str(last.get("judged_body_sha256") or ""),
                           "landed_body_sha256": str(last.get("landed_body_sha256") or ""),
                           "rows": len(seq)}],
                "min_of": [floor] if floor is not None else [],
                "paths_unjudged": ([] if floor is not None else [want_path]),
                "partial": bool(floor is None), "statement_level": stmt_level}

    if not by_path:
        if concept:
            last = concept[-1]
            return {"tri": "not_applicable", "level": None, "applicable": False,
                    "label": "", "basis": str(last.get("basis") or ""),
                    "at": str(last.get("at") or ""), "matched_by": matched_by,
                    "stmt_id": str(last.get("stmt_id") or ""), "effort": {},
                    "text_truncated": False, "paths": [], "min_of": [],
                    "paths_unjudged": [], "partial": False, "statement_level": None}
        return _unjudged("台账里没有这条命题的档位读数")

    path_floor: dict[int, int | None] = {}
    detail: list[dict[str, Any]] = []
    for no in sorted(by_path):
        seq = by_path[no]
        last = seq[-1]
        levels = [x for x in (_level_from_row(r) for r in seq) if x is not None]
        floor = min(levels) if levels else None
        path_floor[no] = floor
        detail.append({
            "path_group": no, "level": _level_from_row(last), "floor": floor,
            "label": nontriviality_label(_level_from_row(last)),
            "at": str(last.get("at") or ""),
            "stmt_id": str(last.get("stmt_id") or ""),
            "basis": str(last.get("basis") or ""),
            "judged_body_sha256": str(last.get("judged_body_sha256") or ""),
            "landed_body_sha256": str(last.get("landed_body_sha256") or ""),
            "rows": len(seq)})
    judged_floors = [path_floor[no] for no in sorted(by_path)
                     if path_floor[no] is not None]
    unjudged_paths = [no for no in sorted(by_path) if path_floor[no] is None]
    unjudged_paths.extend(no for no in expected
                          if no not in by_path and no not in unjudged_paths)
    level = min(judged_floors) if judged_floors else None
    # `min_of` 升序：于是 `level == min(min_of)` 是一条读得出来的恒等式，
    # 逐行复算的人不必再记得"第几个值才是命题级"。
    min_of = sorted(judged_floors)
    # 陈述这一档读数的"来源行"：取历史最小值那一行里最靠后的一条（同档取最近一次）。
    win: Mapping[str, Any] = by_path[sorted(by_path)[0]][-1]
    if level is not None:
        for no in sorted(by_path):
            for row in by_path[no]:
                if _level_from_row(row) == level:
                    win = row
    return {"tri": ("computed" if level is not None else "unknown"),
            "level": level, "label": nontriviality_label(level),
            "applicable": True, "matched_by": matched_by,
            "stmt_id": str(win.get("stmt_id") or ""),
            "basis": str(win.get("basis") or ""),
            "at": str(win.get("at") or ""),
            "effort": dict(win.get("effort") or {}),
            "text_truncated": bool(win.get("text_truncated")),
            "paths": detail, "min_of": min_of,
            "paths_unjudged": unjudged_paths,
            "partial": bool(unjudged_paths), "statement_level": level}


def nontriviality_of(root: str | Path, statement_full: str, *,
                     stmt_id: str = "",
                     path_group: int | None = None,
                     path_groups: Sequence[Any] | None = None) -> dict[str, Any]:
    """这条命题当前的非平凡性档位（折叠旁支台账里同一号 / 同一 sha 的全部行）。

    ## 三级命中（2026-10-26，D16）

    | 级 | 判据 | `matched_by` |
    |---|---|---|
    | 1 | 行上的 `stmt_id` 等于传入的号 | `"stmt_id"` |
    | 2 | 行上的 `statement_sha256` 等于正文的 sha | `"sha256"` |
    | 3 | 都没有 | `""` |

    第一级是命题行与档位之间唯一的关系真身：正文改一个字，号不变，档位照读得到。
    第二级只为读旧行（那些行写在带号之前，盘上只有 sha）；它命中时 `matched_by`
    必须说清这是回退 —— 否则"按文本兜底"会重新长成第二处真身。

    ## 折叠（NT2，2026-11-15）

    命中之后交给 :func:`_fold_nontriviality`：按 `(stmt_id, path_group)` 折叠，
    命题级 = 当前各路径的最小值（且取历史最小值 ⇒ 永不回升），并返回 `paths` /
    `min_of` / `paths_unjudged` / `partial` 供逐行复算。旧行（没有 `path_group`）
    视为路径 1 —— 迁移不读废历史（判据见 `tests/test_nontriviality_is_per_path.py`）。

    `path_group`（可选）：只问某一条路径的读数（`level` 是该路径最后一行，
    `statement_level` 另给命题级）。`path_groups`（可选）：调用方知道这一条命题
    应该有几条路径（`statements.manuscripts` 的键）⇒ 没判的那几条进 `paths_unjudged`，
    `partial=true`，不许折成"全判了"。

    ## 三态（`tri` 的三个取值不许折平）

    | 结局 | 返回 |
    |---|---|
    | 读到一档 | `{"tri": "computed", "level": 0..4, "label": "T0".."T4", …}` |
    | 该判而没判（没有记录 / 记的是判不了 / 旧刻度的 0） | `{"tri": "unknown", "level": None, "label": "", …}` |
    | 这一问对它不成立（概念行的 `applicable: false`） | `{"tri": "not_applicable", "level": None, "label": "", "applicable": False, …}` |

    `tri="unknown"` 与 `tri="not_applicable"` 在 `level` / `label` 上长得一样，区别只在
    `applicable` 这一格：前者要人再去判一次，后者再判也不会有别的结论（2026-10-26）。
    读侧（页面）据此印两个不同的词（`不适用` / `未判`）。

    ## 台账只解析一次（2026-10-27，R-BE1 的 ⑥-3）

    读盘与逐行解析在 `_nontriviality_index` 一处，索引按 `(st_mtime_ns, st_size)` 缓存：
    收工读数与网页那一栏都是逐条命题问一次的，改前每条命题都把整份台账读一遍。
    三个边界写在那儿：台账一变（追加 / 就地改 + 改 mtime）立刻读到新值；缓存里是解析后的
    行、本函数返回的是新造的 dict（就地改返回值不污染缓存）；绕开本函数去改缓存行
    则会污染"这个进程眼里的台账"（本模块不导出那个索引）。
    """
    path = nontriviality_path(root)
    sha = _statement_sha(statement_full)
    if not path.is_file():
        return {"tri": "unknown", "level": NONTRIVIALITY_UNJUDGED, "label": "", "basis": "",
                "applicable": True, "matched_by": "", "stmt_id": "",
                "at": "", "reason": f"{path} 不在盘上 ⇒ 这条命题还没有档位读数",
                "paths": [], "min_of": [],
                "paths_unjudged": [int(x) for x in (path_groups or ())
                                   if str(x).strip().isdigit()],
                "partial": bool(path_groups), "statement_level": None}
    by_id, by_sha, why = _nontriviality_index(path)
    if why:
        return {"tri": "unknown", "level": NONTRIVIALITY_UNJUDGED, "label": "", "basis": "",
                "applicable": True, "matched_by": "", "stmt_id": "",
                "at": "", "reason": why, "effort": {}, "text_truncated": False,
                "paths": [], "min_of": [], "paths_unjudged": [], "partial": False,
                "statement_level": None}
    want = str(stmt_id or "").strip()
    hit_rows = list(by_id.get(want) or []) if want else []
    # 按号那一支仍过 `_row_matches_stmt_id`：它是"按号关联"的唯一判据，也是反真空判据
    # （`tests/test_nontriviality_is_joined_by_stmt_id.py` 的 e 条）打桩的那一格。索引只是
    # "读盘/解析一次"的缓存，不许把这条判据绕过去。
    if hit_rows and not any(_row_matches_stmt_id(r, stmt_id) for r in hit_rows):
        hit_rows = []
    matched_by = "stmt_id" if hit_rows else ""
    if not hit_rows:
        cand = list(by_sha.get(sha) or [])
        if cand:
            hit_rows, matched_by = cand, "sha256"
    if not hit_rows:
        got = _fold_nontriviality([], matched_by="")
        got["reason"] = "台账里没有这条命题的档位读数"
        got["paths_unjudged"] = [int(x) for x in (path_groups or ())
                                 if str(x).strip().isdigit()]
        got["partial"] = bool(got["paths_unjudged"])
        return got
    return _fold_nontriviality(hit_rows, matched_by=matched_by,
                               path_group=path_group, path_groups=path_groups)


#: 五项力气读数 → 各自的加分台阶（唯一一处定义在 `proof_effort_readings`）。
#:
#: 为什么这张表住在这一层（NT2 从 `agent_loop` 搬来）：note 是给模型看的指路牌
#: （"补哪一项能升档"），而档位本身由秘书（模型）按五档定义判 —— 这里一个字都不算档位，
#: 只把"这一条哪几项还在 0 分"翻成一句人话。判档搬进 B 的收录动作之后，这份读数也
#: 跟着走：它是"判"的产物，不是"循环"的产物。
_EFFORT_UPGRADE_STEPS: tuple[tuple[str, str, str], ...] = (
    ("体量", "chars", "每 2000 字 +1"),
    ("步骤", "steps", "每 6 步 +1"),
    ("引理", "lemmas", "每 2 条引理 +1"),
    ("工具簇跨度", "clusters", "跨到第 2 个工具簇才 +1"),
    ("绕路", "detour", "记下走过的一段死路 +1"),
)


def filing_tier_note(got: Mapping[str, Any]) -> str:
    """落 T0 那一格读数里的指路牌：按力气口径说清"还差哪一项、补哪一项能升档"。

    为什么不再是旧的两问（业主 2026-10-24 的裁定原话）：「不一定一条定理后面要用，
    也不一定存在"已知那条"，看证明花的力气就能判非平凡度」。旧口径的两个问题留在这句
    note 里，模型就会去编"谁会用到它"来升档 —— 而档位只由五项力气读数落格，
    那两个问题一个字都不参与（B 仍可以把它们写在 `why` 里给秘书看，只是不作判据，
    也不再是这一格教给模型的升档路径）。

    两档文案：材料里没有证明正文时点名"缺「证明正文」"并指到 `proof_text` /
    `proofs`；有力气读数时点名还在 0 分的那几项（每一项各 +1）。
    """
    head = ("平凡 ⇒ 落 T0（基础定理或初步结论），照旧收录（业主 2026-10-23："
            "秘书不再因「太平凡」拦收录）。档位由秘书按五档定义判（业主 2026-10-29）："
            "五项读数 = 体量 / 步骤 / 引理 / 工具簇跨度 / 绕路")
    effort = got.get("effort")
    effort = dict(effort) if isinstance(effort, Mapping) else {}
    if not effort or list(effort.get("missing") or []):
        return (head + "。这一条缺「证明正文」这一项：五项读数一项都取不到 ⇒ 档位落「未判」。"
                "补上 proof_text（或 proofs=[{proof_no, text}] 里的正文）再交一次"
                "就能判出档位")
    chars = int(effort.get("chars") or 0)
    steps = int(effort.get("steps") or 0)
    lemmas = int(effort.get("lemmas") or 0)
    clusters = int(effort.get("clusters") or 0)
    detour = bool(effort.get("detour"))
    score = int(effort.get("score") or 0)
    label = str(got.get("label") or "") or "T0"
    still_zero = {"chars": chars // 2000 == 0, "steps": steps // 6 == 0,
                  "lemmas": lemmas // 2 == 0, "clusters": clusters < 2,
                  "detour": not detour}
    how = "、".join(f"{name}（{hint}）"
                    for name, key, hint in _EFFORT_UPGRADE_STEPS if still_zero[key])
    return (head + f"。这一条现在读到：体量 {chars} 字、步骤 {steps}、引理 {lemmas} 条、"
            f"工具簇 {clusters} 个、绕路{'有' if detour else '无'}"
            f"（力气分数 {score} ⇒ {label}）。"
            f"还在 0 分的项：{how or '（无，五项都进分了）'} —— 补哪一项就升档；"
            "证明正文写在 proof_text 里，多份证明写在 proofs=[{proof_no, text}]")


def filing_tier_reading(got: Mapping[str, Any] | None, *,
                        stmt_id: str = "") -> dict[str, Any] | None:
    """把一次判档（或一条台账读数）翻成"模型看得见的那一格"；不加档位就返回 `None`。

    业主 2026-10-23 的裁定：平凡不是"不许进"，是"进哪一档"（T0 = 基础定理或初步结论）。
    所以只在两种情形给读数：判了 T0（`tier` + 指路 note）与"没查成"（未判 + 原因，
    且拿到号之后才给 —— 没有号的那一笔本来就不会有命题行可指）。

    这里不判档、不写盘：判在 B 的收录动作里（写之前），落由
    `record_nontriviality`（拿到号之后）。这一格只做整形，所以"档位是谁给的"不会在
    这一层分叉。台账读数形状（`tri` / `level`）与判词形状（`checked` / `decision`）
    都收：前者是 `_do_tool` 从刚落的那一行读回来的，后者是 B 动作层手里的原始判词。
    """
    if not isinstance(got, Mapping) or not got:
        return None
    if "tri" in got or "nontriviality_tri" in got:
        tri = str(got.get("tri") or got.get("nontriviality_tri") or "")
        level = _nontriviality_level(got.get("level", got.get("nontriviality")))
        checked = tri in ("computed", "not_applicable")
        reason = str(got.get("reason") or "")
    else:
        checked = bool(got.get("checked"))
        # 判词形状：`decision` 是唯一主字段，`nontriviality` 只是旧别名
        # （与 `judge_statement` 同一个读法：`_tier_from_judge_reply`）。
        level = _tier_from_judge_reply(got)
        reason = str(got.get("reason") or "判档没查成")
    if not checked or level is None:
        # 没有号的那一笔本来就没有命题行可指 ⇒ 不给"未判"读数（与判/落拆段之前
        # 那一支的边界逐字一致：有号才给原因）。
        if not str(stmt_id or "").strip():
            return None
        return {"tier": "", "label": "", "nontriviality": None,
                "nontriviality_tri": "unjudged", "matched_by": "",
                "downgraded": False, "decision": "",
                "reason": reason[:300],
                "judged_by": "secretary", "judge": "statement_aesthetic"}
    # 判词形状里 `decision` 是唯一主字段（T0 才是"平凡 ⇒ 落 T0"）；台账读数形状
    # 没有 `decision`，按 `level == 0` 读。两条都过同一个判据函数
    # （`_is_trivial_verdict` 是"这一档是不是 T0"的唯一口径，也是判据的打桩点）。
    decision = str(got.get("decision") or "").strip()
    if decision:
        if not _is_trivial_verdict(decision):
            return None
    elif level != 0:
        return None
    label = str(got.get("label") or "") or nontriviality_label(level)
    effort = got.get("effort")
    effort = dict(effort) if isinstance(effort, Mapping) else {}
    return {
        "tier": label or nontriviality_label(0),
        "label": label,
        "nontriviality": level,
        "nontriviality_tri": "computed",
        # 只带判档用得上的那几格读数：note 里的指路牌与台账里那一行都是按它们写的，
        # 模型不必去猜"为什么是这一档"（`cluster_evidence` 那类明细留在秘书台账里）。
        "effort": {k: effort.get(k) for k in
                   ("chars", "steps", "lemmas", "clusters", "detour", "score",
                    "missing", "body_from")},
        "downgraded": True,
        "decision": label,
        "reason": str(got.get("reason") or "")[:300],
        "basis": list(got.get("basis") or []),
        "note": filing_tier_note(got),
        "judged_by": "secretary",
        "judge": "statement_aesthetic",
    }


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


# ---------------------------------------------------------------- 命题形态判定台账

#: 命题形态判定（"这条描述有没有明确「从什么条件导出什么结论」"）的旁支台账。
#:
#: 为什么要有这一本账：这一问的结论必须能被收工读数数出来
#: （「命题登记时需过 F 秘书闸」+ 读数要显形"被拒的条数 + 逐条码"）。而它不落
#: `statements` 行 —— F 自己不写 `statements`（登记是 B 的活），所以判定结果落在
#: 秘书自己的台账上，读侧一个口：:func:`proposition_form_of`。
PROPOSITION_FORM_LEDGER = "proposition_form.jsonl"

#: 同一命题检索的旁支台账（挑词 / 判定 / 检索各一行）。
#:
#: 为什么要有这一本账：验收口径是"B 秘书查过一圈没有"必须可审计
#: （关键词、命中数、查到哪一条、为什么没查成）。这些读数不落 `statements` 行
#: （那一行只记证据位），所以落在秘书自己的台账上，读侧一个口：
#: :func:`statement_same_rows`。
STATEMENT_SAME_LEDGER = "statement_same.jsonl"

#: 这一闸的受控码（模型读得到的那一个）。
PROPOSITION_FORM_REFUSED = "proposition_form_refused"

#: 派活审阅（"这一条派给 F 的活是不是一个研究方向"）的旁支台账（业主 2026-11-13 裁定 Q5）。
#:
#: 为什么是一本轴台账而不是再往角色台账抄一行：这一问的结论要能被"这一趟派了几个 F、
#: 各自方向"那条读数复用，也要能在派活之后逐条复核"秘书当时为什么说不合适"。Q5 的裁定是
#: 只落这一本 —— 双写会让"同一件事两个落点"，读的人分不清哪一本算数。
DISPATCH_FIT_LEDGER = "dispatch_fit.jsonl"


def dispatch_fit_path(root: str | Path) -> Path:
    """派活审阅台账的路径：`out/secretary/dispatch_fit.jsonl`。"""
    return Path(root).joinpath(*SECRETARY_DIR, DISPATCH_FIT_LEDGER)


def append_dispatch_fit(root: str | Path, *, to: str, task: str, checked: bool,
                        verdict: str = "", why: str = "", basis: Sequence[str] = (),
                        decision: str = "", cost_ledger: str = "", role: str = "",
                        task_id: str = "") -> dict[str, Any]:
    """追加一行派活审阅读数（append-only；显式 LF，与 `append_proposition_form` 同一口径）。

    每一次判定都记（含 `checked=False` 的"没查成"）：只记"不合适"的那几行，会让
    "秘书这一趟到底审过没有"在盘上消失 —— 那正是这条提醒要防的"静默放行"。
    `verdict` 只在 `checked=True` 时有值（`是一个方向` / `不是一个方向`）；
    `decision` 是台账那一栏
    的结论词（没查成时是 `没查成`，不是"合适"）。
    """
    path = dispatch_fit_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {"at": _now_iso(),
           "to": str(to or ""), "task": str(task or ""),
           "task_chars": len(str(task or "")),
           "checked": bool(checked), "verdict": str(verdict or ""),
           "why": str(why or ""), "basis": [str(x) for x in (basis or ())],
           "decision": str(decision or ""), "cost_ledger": str(cost_ledger or ""),
           "role": str(role or ""), "task_id": str(task_id or "")}
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        # `default=str` 与全仓同一口径（`tests/test_json_dumps_has_a_default.py`）。
        handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True, default=str) + "\n")
    return row


def dispatch_fit_rows(root: str | Path) -> list[dict[str, Any]]:
    """这本台账的全部行（读不出来 ⇒ 空列表，并把原因留给调用方那条三态读数去报）。"""
    path = dispatch_fit_path(root)
    if not path.is_file():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text:
            continue
        try:
            row = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(row, Mapping):
            out.append(dict(row))
    return out



def proposition_form_path(root: str | Path) -> Path:
    """命题形态判定台账的路径：`out/secretary/proposition_form.jsonl`。"""
    return Path(root).joinpath(*SECRETARY_DIR, PROPOSITION_FORM_LEDGER)


def append_proposition_form(root: str | Path, *, statement_full: str, checked: bool,
                            well_formed: bool, conditions: str = "", conclusion: str = "",
                            problems: Sequence[str] = (), decision: str = "",
                            refused: str = "", reason: str = "", label: str = "",
                            kind: str = "", stmt_id: str = "", role: str = "",
                            task_id: str = "") -> dict[str, Any]:
    """追加一行形态判定读数（append-only；显式 LF，与 `append_proposition_verdict` 同一口径）。

    每一次判定都记（含"没查成"那一档）：读数要把"被拒了几条 / 每条是什么码"数得出来，
    而只记放行的那几条会让拒收在盘上消失 —— 那正是这道闸要防的"静默放行"。
    """
    path = proposition_form_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {"at": _now_iso(),
           "statement_sha256": _proposition_verdict_key(statement_full),
           "statement_chars": len(str(statement_full or "")),
           "checked": bool(checked), "well_formed": bool(well_formed),
           "conditions": str(conditions or ""), "conclusion": str(conclusion or ""),
           "problems": [str(x) for x in (problems or ())],
           "decision": str(decision or ""), "refused": str(refused or ""),
           "reason": str(reason or ""), "label": str(label or ""),
           "kind": str(kind or ""), "stmt_id": str(stmt_id or ""),
           "role": str(role or ""), "task_id": str(task_id or "")}
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        # `default=str` 与全仓同一口径（`tests/test_json_dumps_has_a_default.py`）。
        handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True, default=str) + "\n")
    return row


def proposition_form_rows(root: str | Path) -> list[dict[str, Any]]:
    """这本台账的全部行（读不出来 ⇒ 空列表，并把原因留给调用方那条三态读数去报）。"""
    path = proposition_form_path(root)
    if not path.is_file():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text:
            continue
        try:
            row = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(row, Mapping):
            out.append(dict(row))
    return out


def proposition_form_of(root: str | Path, *, statement_full: str = "",
                        stmt_id: str = "") -> dict[str, Any]:
    """这条命题的形态判定（读侧唯一口）。

    三态：空字典 = 没有判定过（不是"判过、合格"）；非空 = 有判定行，`well_formed`
    与 `checked` 两格说清结论。能不能缓存由调用方按 `checked` 决定 —— "没查成"的行
    不许挡住下一次调用（缝是可能好起来的，与 `proposition_verdict_of` 同一条纪律）。
    """
    key = _proposition_verdict_key(statement_full) if statement_full else ""
    last: dict[str, Any] = {}
    for row in proposition_form_rows(root):
        if stmt_id and str(row.get("stmt_id") or "") == str(stmt_id):
            last = row
            continue
        if key and str(row.get("statement_sha256") or "") == key:
            last = row
    return last


# ---------------------------------------------------------------- 同一命题检索台账（2026-11-08）


def statement_same_path(root: str | Path) -> Path:
    """同一命题检索台账的路径：`out/secretary/statement_same.jsonl`。"""
    return Path(root).joinpath(*SECRETARY_DIR, STATEMENT_SAME_LEDGER)


def append_statement_same(root: str | Path, *, stage: str, statement_full: str,
                          checked: bool, keywords: Sequence[str] = (),
                          hits_total: int = 0, candidates: Sequence[str] = (),
                          found: str = "", why: str = "", label: str = "",
                          kind: str = "", seam_source: str = "", role: str = "",
                          task_id: str = "") -> dict[str, Any]:
    """追加一行检索 / 判定读数（append-only；显式 LF，与形态台账同一口径）。

    每一次都记（含"没查成"那一档）：把"没查成"也留在盘上，读的人才分得清
    "查过、没查到"与"根本没查"。只记查到的那几笔会让 fail-closed 在盘上消失。
    """
    path = statement_same_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {"at": _now_iso(), "stage": str(stage or ""),
           "statement_sha256": _proposition_verdict_key(statement_full),
           "statement_chars": len(str(statement_full or "")),
           "checked": bool(checked),
           "keywords": [str(x) for x in (keywords or ())],
           "hits_total": int(hits_total or 0),
           "candidates": [str(x) for x in (candidates or ())][:50],
           "found": str(found or ""), "why": str(why or ""),
           "seam_source": str(seam_source or ""),
           "label": str(label or ""), "kind": str(kind or ""),
           "role": str(role or ""), "task_id": str(task_id or "")}
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True, default=str) + "\n")
    return row


def statement_same_rows(root: str | Path) -> list[dict[str, Any]]:
    """这本台账的全部行（读不出来 ⇒ 空列表，与形态台账同一条读法）。"""
    path = statement_same_path(root)
    if not path.is_file():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text:
            continue
        try:
            row = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(row, Mapping):
            out.append(dict(row))
    return out


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
                               keywords: Sequence[str] = (), hits_total: int = 0,
                               hits_named: Sequence[Mapping[str, Any]] = (),
                               judged: bool = False, why: str = "",
                               keyword_checked: bool = False,
                               candidates_total: int = 0, pages_total: int = 0,
                               pages_judged: int = 0, candidates_seen: int = 0,
                               page_exhausted: bool = False,
                               seam_source: str = "",
                               role: str = "", task_id: str = "") -> dict[str, Any]:
    """追加一行判定读数（append-only；显式 LF，Windows 上不留 CRLF）。

    只记判成了的两档结论（same / different）：没判成（没缝 / 开关关着 / 超时 / 坏 JSON /
    词表外结论 / same 点不出号 / 关键词没提取成）不许缓存 —— 那会把"这一次没判成"变成
    "以后都别查了"，而缝是可能好起来的（与 `_statement_verdicts` 同一条纪律）。

    每行带 `statement_sha256`：读侧按它折叠出"这条正文最后一次判定是什么"，不必去猜行序。
    检索读数（`keywords` / `hits_total` / `hits_named` / `judged` / `why`）也落这一行：
    "沿用那一次判定"时，读的人同样看得到它当年查过什么（业主 2026-11-08：主动查询）。
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
           "keywords": [str(x) for x in (keywords or ())],
           "hits_total": int(hits_total or 0),
           "hits_named": [dict(x) if isinstance(x, Mapping) else {"stmt_id": str(x)}
                          for x in (hits_named or ())],
           "judged": bool(judged), "why": str(why or ""),
           #: 分页读数（2026-11-08 缺陷 ②）：看了几页 / 几个候选 / 是否页尽。
           "keyword_checked": bool(keyword_checked),
           "candidates_total": int(candidates_total or 0),
           "pages_total": int(pages_total or 0),
           "pages_judged": int(pages_judged or 0),
           "candidates_seen": int(candidates_seen or 0),
           "page_exhausted": bool(page_exhausted),
           "seam_source": str(seam_source or ""),
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


def proposition_verdict_rows(root: str | Path) -> list[dict[str, Any]]:
    """命题同一性判定台账的全部行（读侧唯一口；没有文件 ⇒ 空列表）。

    为什么要有这一格（2026-11-08，①）：收工读数要数"这一趟判定到底发生过几次"，
    而"判定台账有几行"是唯一可靠的落盘读数。读法与 `proposition_form_rows` /
    `statement_same_rows` 逐字同形：空行跳过、坏 JSON 跳过（读不出来由调用方的三态
    读数报"没查成"，不许折成"0 次判定"）。
    """
    path = proposition_verdicts_path(root)
    if not path.is_file():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text:
            continue
        try:
            row = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(row, Mapping):
            out.append(dict(row))
    return out


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
            f'decision（必须逐字取自 {list(verdicts)} —— 这是这一类的词表，'
            "别的类别的词一律不采信）、reason（一句话）、basis（字符串数组，"
            "写清你凭什么，例如 `specs/d.py` 的哪一条或 `tasks` 里的哪一行）")
    if kind == "statement_aesthetic":
        # ---- 2026-11-01 业主两刀：审美轴三格退场，判档那一问只剩 T0–T4；
        # "判不了"也不是第四档 —— 材料不足 / 正文被截断的情况框架在发问之前就挡住了，
        # 走到这里就必须给出一档。模型若给 null / 旧词 / 别的一律"没查成"，不落档位行。
        #
        # 为什么不再要第二个字段：2026-11-01 的 82 现场正是"两字段两轴"的形态 ——
        # 模型把档位写进 reason、decision 写了旧词、nontriviality 给了 null，
        # 读侧一个字段都认不到。一根轴一个字段，题面就不再有两套指令打架。
        head += ('；另外，decision 就是这条命题的档位：逐字取自 '
                 '"T0"/"T1"/"T2"/"T3"/"T4" 之一（材料不足的情况框架会先挡住，'
                 '不会把这一问发给你）')
    head += "。"
    if kind == "duplicate_retry":
        ask = ("问题：同一个 (role, action, input_key) 已经有下面这些终态行。这一次是"
               "正当的重试，还是重复委托？判『可派』= 这次该照派；判『建议不派』= 别重复派。")
    elif kind == "tool_name":
        ask = ("问题：本体写的工具名不在注册表里。要映到下面哪一个候选吗？"
               "判『建议重排』= 映到某一个（在 reason 里写清是哪一个）；"
               "判『建议不派』= 一个都不映（这次不该调工具）。")
    elif kind == "statement_aesthetic":
        # 业主 2026-10-29：「全交给模型判，5 个等级的自然语言描述应该还在吧」。
        # 改前这一支让模型"复述机器算好的分数"（nontriviality_basis 要写
        # 「分数 7 = 体量 5164 字/2 + …」），档位实际由分数落格决定；现在把业主
        # 那五句定义原样放进题面，判定归模型，`effort` 只作参考读数。
        ask = (
            "问题：本体（B）要把下面这条命题收进 `statements`（定理与证明收录表）。"
            "请按下面这五档的自然语言定义判它落在哪一档（业主原话）：\n"
            "- T0 基础定理或初步结论（平凡但真；含由数值实验直接穷举得出的那些）\n"
            "- T1 有一定价值的非平凡结论\n"
            "- T2 证明方法都是平凡的，但工作量较大\n"
            "- T3 需要用较多的技巧或跨领域工具\n"
            "- T4 需要天才般的洞察力，或思维链极长，或是偏离主流研究方向的神奇构造\n"
            "判的是这份证明本身：思路、承重步骤、用到的工具、有没有真技巧。\n"
            "材料里的 `effort`（体量/步骤/引理/工具簇/绕路与分数）只是机器数出来的"
            "参考读数，不要拿它当判据：写得长不等于难，步数多也不等于难；"
            "也不要只在 basis 里复述那几个数字。\n"
            "decision 就是这条命题的档位：取 \"T0\"/\"T1\"/\"T2\"/\"T3\"/\"T4\" 之一；"
            "必须给出一档（材料不全会先被框架挡住，不会走到这一问）。\n"
            "reason 一句话；basis 写清你凭证明里的哪几步这么判（可以引用正文里的步骤，"
            "但不要用分数当理由）。"
        )
    elif kind == "proposition_identity":
        ask = (
            "问题：下面这一条命题（条件 ⇒ 结论）与候选表里的每一条，是不是同一个定理？"
            "候选表是秘书从命题台账里取出来的那几条 —— 它只决定给你看哪几条，"
            "判定只看条件与结论。"
            "业主定的准绳逐字是：「定理描述一致（什么条件推出什么结论），就是一个定理」。"
            "所以判据只有一条 —— 条件组与结论组是否一致。三种情形逐条写清："
            "① 同一组条件推出同一组结论 ⇒ 判 same，并在 same_as 里给出候选的 stmt_id"
            "（只给一个号，且必须是候选表里的号）；"
            "② 条件是包含关系（一条更强 / 一条更弱）⇒ 判 different，basis 里写明"
            "『条件强弱不同』，不许因为『看起来是同一个主题』就判 same；"
            "③ 结论相同、条件只是同一条件的另一种记号或等价改写（换变量名、换记号、"
            "把『有限群』写成『阶有限的群』这一类）⇒ 仍判 same。"
            "判词只有两档：same / different —— 没有第三档，也不许自己造一个像结论的词。"
            "读不清（缺假设、只给了名字、正文被截断）时不要猜：把 decision 留成空串"
            "（或写『没判成』），框架把它当「没判成」处理（不新建、不合并、受控拒）；"
            "那不是你的判词。"
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
    elif kind == "proof_kind":
        # 业主 2026-11-12 的场景逐字：「两个 F 分别独立交了关于某个命题的证明……后录入的
        # 稿子 B 秘书识别到是同一命题，在对比证明方法后发现几乎一致，于是不收录；另一种
        # 情况：对比证明方法后发现有很大差别（语义判别，千万别做任何机械闸，结论是二态的：
        # 一致/不同），于是注册了该命题号下的第 2 路径」。
        #
        # 这一问只回答"证法是不是同一套"，不回答"命题是不是同一条"（那是
        # `proposition_identity`），也不回答"证明对不对"（那是 V 的轴）。题面刻意不提
        # 字数 / 相似度 / 关键词：机械读数不是判据（材料里的 `material_similarity` 只是
        # 给人看的参考，模型不许拿它当理由）。
        ask = (
            "问题：同一条命题下，新交来的这一份证明（材料里的 `proof_text`）与在册各条"
            "证明路径（材料里的 `proofs`，每项有 `path_group` 与 `text`）是不是同一套证法？"
            "只判『证明方法』这一件事：核心思路、承重步骤、用到的工具是否同一路；"
            "换措辞、换记号、换变量名、把同一步展开或压缩，都仍是同一套证法。"
            "结论只有两档：same（与某一条在册路径是同一套证法）/ different（是一套"
            "不同的证法，可以并列为另一条路径）——没有第三档，也不许自己造一个词。"
            "判 same 时必须在 `same_path` 里给出它对应的是哪一条在册路径的 `path_group`"
            "（整数，必须是材料里出现过的号）；判 different 时 `same_path` 给 0。"
            "读不清（正文缺关键步骤、被截断、只是重复了命题）时不要猜：把 decision 留成"
            "空串，框架把它当「没判成」处理（fail-closed，不收录），那不是你的判词。"
            "不参与判定的东西：定理叫什么名字、证明写得多长、用了哪些字词、文风、"
            "材料里机器算出的相似度读数 —— 那些都不是『证明方法』本身。"
            "reason 一句话；basis 写清你凭哪几步这么判（引证明里的步骤，不要引相似度数字）。"
        )
    elif kind == "dispatch_fit":
        # 业主 2026-11-13（本批 R1/R2 的裁定，逐字）：「plan由F自己决定，所以D不可能做出
        # 按plan个数派F，于是D只能按研究方向开多个F而非把一堆方向委托给一个F」。
        # 这一问只判方向个数这一件事：D 交给 F 的是"一件事"，还是"几件事捆在一起"。
        # 题面住在 :data:`DISPATCH_FIT_QUESTION`（模块级常量）：它只取决于 kind、与材料
        # 无关（缓存纪律同 `_judge_system` 的抬头），而且 `_judge_system` 是软基线
        # `src_functions_gt200_lines` 盯着的那一类函数 —— 把二十来行题面塞回它的函数体
        # 会把那一格 92 抬到 93（业主口径：这一格不许抬）。
        ask = DISPATCH_FIT_QUESTION
    elif kind == "v_reply_defect":
        # 题面只给两档（「不可能有判不了。你告诉我啥叫判不了？只要不是完全没毛病都叫有毛病」），
        # 并逐字写清"拿不准就按有缺陷处理"——没有中间档可退。
        # why：`verifications.parse_verdict` 只能挡住结构不合格，它挡不住"整体很好，只是有
        # 一个缺陷需要指出"——那种回复按字面读成「成立」时，它明明指出了一个缺陷。
        # 轴只由这一问给；V 的 verdict 只是陈述，不得按字面定轴；
        # 判 fault 还要给出 defect_step（V 没给时由这一问定出那一步）。
        # 把「程序性」与「数学缺陷」分开记 —— 判 fault 时还要给 defect_kind；
        # 「没记录反例尝试」不是判据（缺了写 report_gap）。
        ask = (
            "问题：下面这段是验证者（V）对一份证明的审阅回复。它到底有没有指出缺陷？"
            "只有两档，没有中间档：\n"
            "有缺陷要指出（只要不是完全没毛病，就判这一档）：\n"
            "- 「整体很好，只是有一个缺陷需要指出……」；\n"
            "- 「思路没问题，但是有一个记号问题需要强调……」；\n"
            "- 「我找不到反例，但某对象似乎没有定义」；\n"
            "- 「我觉得没问题但我没逐行验证」——没验证过就不是没问题（这一类是程序性："
            "它没有做出判定）；\n"
            "- 拿不准、说不清、只挑出一处小记号问题：一律判这一档。\n"
            "没问题：它真的逐条走查过，并且没有指出这份证明的任何缺陷"
            "（「我试了几种反例构造都失败、未发现问题」是好报告的样例；但有没有写反例"
            "尝试的记录不是判据 —— 缺了就记进 report_gap，不要因此判有缺陷）。\n"
            "它的依据落在不归 F 的那几样上（文献真伪/页码核对、实验数值复现、稿件排版"
            "与术语统一）也不是没问题 —— 那说明它没审证明本身，按有缺陷处理（文风类）。\n"
            "「判不了」不是一种结论：判不出来就说明它没有证明「没问题」，按有缺陷处理。"
            "只判这段回复说了什么：不要替它补它没说过的检查，也不要因为语气自信就判没问题。\n"
            "两个「判不了」别混：① 被审的 V 回复里写「判不了」—— 那是它的陈述，按上面"
            "这一条判「有缺陷要指出」；② 你自己（秘书）不能拿「判不了」当结论 —— 你只从"
            "「没问题」/「有缺陷要指出」两档里选一档，选不出来时按「有缺陷要指出」收。\n"
            "decision 取「没问题」/「有缺陷要指出」之一；reason 一句话；"
            "basis 里引回复原文的片段（逐字，不要改写）。\n"
            "另加三格（与 decision 同一趟给，不另发调用）：\n"
            "① defect_kind：decision=「有缺陷要指出」时必给，逐字取自 "
            '["math", "procedural", "style", "contract"] 之一：\n'
            "  · math = 证明链本身的错或洞（指到某一步、缺依据、常数矛盾、结论没覆盖）；\n"
            "  · procedural = V 自己说「我没逐行验证 / 我判不了」——它没有做出判定；\n"
            "  · style = 依据落在排版 / 术语 / 文风 / 价值判断（不归 V 判的面）；\n"
            "  · contract = 稿的形态或契约不合格（缺节、正文 sha 不符、引用不可核）。\n"
            "  decision=「没问题」⇒ defect_kind 给空串。\n"
            "② defect_step（只在 decision=「有缺陷要指出」时要，整数或 null）："
            "这段回复指到的是证明里的第几步；回复里点了步号就用它，没点就按它描述的缺陷"
            "落在哪一步给出最早的那一步；实在定位不到才给 null，并在 defect_step_basis 里"
            "写清为什么。decision=「没问题」⇒ defect_step=null。\n"
            "③ report_gap（decision=「没问题」时的一格报告质量读数，可空）：只记"
            "「V 的报告缺了什么记录」（例：没写反例尝试的位置、没写逐关核对），"
            "它不影响判定、不挡签。"
        )
    elif kind == "sign_issuance":
        # 业主 2026-10-29（V 签门槛的 A 段）：发不发签由 V 的秘书说了算。
        # 材料里只有台账读数（连续次数 / 门槛 / 正文 sha / 这一签的结论），没有证明正文
        # （V 的秘书不读 F 的叙述，`may_read_narrative` 对 role="V" 恒 False）。
        # 2026-10-30 第三次裁定：这里的词表也只有两格 —— "读数不全"不是第三档答案，
        # 那是"没查成"（框架按 checked=False 记，见 `decide_sign_issuance`）。
        ask = (
            "问题：验证者（V）刚对一个命题的某一份证明给出了结论，现在要决定"
            "这一签发不发（发签 = 把命题行的第 3 位翻成「审过」）。"
            "材料是台账现算的读数，不是证明正文。判据只有一条："
            "业主定的门槛是「同一份正文连续 3 次都判「成立」」——`streak`（尾部连续 clean 的次数）"
            "必须达到 `need`（门槛），且这几次盖的是同一份正文（那一格读数须为真）。\n"
            "p247：这里的 `candidate_axis` 是上一问（`v_reply_defect`）给出的轴 ——"
            "它是唯一判据；`candidate_verdict` 只是 V 写下的陈述，不要按它的字面改判轴。\n"
            "- 次数够了、同一份正文、这一签的 `candidate_axis` 是 clean ⇒ 判「签发」；\n"
            "- 次数不够 / 不是同一份正文 / 这一签的 `candidate_axis` 不是 clean ⇒ 判「不签发」，"
            "并在 basis 里点名差在哪一项；\n"
            "某一格读数读不出来时不要拿一个结论去凑：那是「没查成」，框架按 checked=False 记。\n"
            "decision 取「签发」/「不签发」之一；reason 一句话；"
            "basis 写明你依据的是哪几格读数。"
        )
    else:
        ask = ("问题：这条委托照声明看不合规（或与收件方的角色定位不匹配）。"
               "该重排成什么？判『建议重排』并在 reason 里给出重排后的说法；"
               "判『建议改派』= 换一个收件方更合适；判『建议不派』= 别派这条。")
    return f"{head}\n\n{ask}\n\n"


def _wash_v_system() -> str:
    """洗稿那一趟的稳定头（进 `system` 位）：纪律 + 输出形状。

    与 :func:`_judge_system` 同一条缓存纪律：这一段只取决于"这是洗稿"，不取决于材料
    （任何两趟、任何一份回复，它逐字节相同），所以它能进前缀；材料留在 user 位。
    为什么它不说"你是 V 的秘书"以外的事：洗稿的判据只有三条（逐字引、不添意思、
    不评价价值），多写只会让模型在这些轴上自由发挥。
    """
    return (
        "你是「秘书」的洗稿面：把验证者（V）的审阅回复改写成转达给作者的工作意见。"
        "纪律三条：① 只写原文里有的意思，不许添；② findings 里每一条 `quote` 必须与原文"
        "逐字相同（只允许空白差异）—— 改了字就不采信；③ 不评价作者思路好不好、不写"
        "「这篇论文有没有价值」这类价值判断（那不是 V 的判据面）。"
        "只回一个 JSON 对象，字段：text（改写后的正文）、findings（对象数组：quote + why）、"
        "step（整数或 null）。\n\n"
    )


def _proposition_form_system() -> str:
    """命题形态闸的稳定头（进 `system` 位）：只问一件事 + 输出形状。

    业主 2026-11-07 逐字：「命题登记时需过 F 秘书闸，审查命题描述是否规范，是否明确了
    从什么条件导出什么结论」。

    与 :func:`_judge_system` / :func:`_wash_v_system` 同一条缓存纪律：这一段只取决于
    "这是命题形态闸"，逐字节稳定（材料留在 user 位）。为什么把"不判什么"也写进
    稳定头：本仓反复踩过"两根轴混进同一格"（非平凡性 vs 正确性），把边界写在
    提示词里比写在注释里更能拦住下一次改动。
    """
    return (
        "你是「命题形态闸」：只回答一件事 —— 这段描述有没有明确「从什么条件导出什么结论」。"
        "**不判它对不对**（那是验证者的轴），**不判它是否平凡/是否已知**（那是另一根轴），"
        "也不评价它的价值。"
        "判据四条：① 前提（条件 / 假设 / 量词范围）在描述里写得出来；"
        "② 结论是一个**可判真假的断言**；"
        "③ 二者由「若…则…」「设…则…」一类结构连起来，而不是一段流程要求；"
        "④ 描述里没有混进作业/验收规格（「本轮产物必须是 proof」「判据是 "
        "manuscript_published=true」「原样提交 reports/xxx.md」这类不是数学断言）。"
        "只回一个 JSON 对象，字段：well_formed（布尔，只有两态，不许给 "
        "true/false 以外的值）、conditions（你读出的前提，字符串）、"
        "conclusion（你读出的结论，字符串）、problems（字符串数组：不合格时逐条说缺什么，"
        "例如「没有写清前提」「结论不是可判真假的断言」「这是流程要求，不是命题」，"
        "合格时给空数组）、decision（一句话判词）。\n\n"
    )


def _statement_keywords_system() -> str:
    """命题台账检索的挑词稳定头（进 `system` 位）。

    业主 2026-11-08 逐字：「B秘书要学会在命题台账里按关键词搜索」。
    与 :func:`_proposition_form_system` 同一条缓存纪律：这一段只取决于"这是挑检索词"，
    逐字节稳定；待收命题留在 user 位。

    为什么不设词数上限：词数是判定的一部分 —— 挑几个、挑哪些，由模型按"能不能把
    同义的那条捞出来"自己定。代码里写"最多 N 个"会把一个判定问题降成机械配额。
    """
    return (
        "你是「命题台账检索」：给一条待收命题挑能在台账里捞到同义命题的关键词。"
        "只挑数学内容：对象（群、图、矩阵、函数…）、结构（有限、交换、连通…）、"
        "关键量（阶、秩、维数、误差…）、结论形态（同构、收敛、成立、整除…）。"
        "不要挑「设」「则」「若」「对所有」这类虚词，也不要挑标点。"
        "同义的那条可能换了写法：条件写得更全或更简、结论同一 —— 请挑两边都会出现的"
        "数学词，别挑只在这一条里出现的措辞。"
        "词数由你自己定（以能把同义的那条捞出来为度）。"
        "只回一个 JSON 对象，字段：keywords（字符串数组）、"
        "why（一句话：这几个词为什么能把同义的那条捞出来）。\n\n"
    )


def _abandon_difficulty_system() -> str:
    """放弃闸 difficulty 档的稳定头（进 `system` 位）：只问两件事 + 输出形状。

    业主 2026-11-07 逐字：「对于2，需指出困难，并将原先证明中可取之处拆出落成引理」。

    与 `_proposition_form_system` 同一条缓存纪律：只取决于"这是难度判定"，
    逐字节稳定；材料（命题 / 旧证明 / difficulty / salvaged 各行）留在 user 位。
    """
    return (
        "你是「放弃命题的难度判定」：只回答两件事 —— "
        "① `difficulty` 这一段是不是在说**真实的数学困难**、难在哪（卡在哪条引理 / 哪一步 / "
        "哪条假设），而不是「做不动了」「太难了」「时间不够」这类没有内容的话；"
        "② `salvaged` 里那几条引理是不是**从这条命题的原证明里拆出来的可取之处**，"
        "而不是随便一条在册引理、更不是这条命题自己。"
        "**不判**这条命题对不对、也**不判**该不该放弃。"
        "只回一个 JSON 对象，字段：genuine（**布尔**，只有两态：这一段是不是真困难）、"
        "where（你读出的难在哪；genuine=true 时不许为空）、"
        "salvaged_from_proof（**布尔**：那几条引理是不是从原证明里拆出来的）、"
        "problems（字符串数组：genuine=false 或 salvaged_from_proof=false 时逐条说为什么，"
        "两样都为真时给空数组）、decision（一句话判词）。\n\n"
    )


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
                f"只给了前 {JUDGE_MATERIAL_CAP} 字。这是输入不完整，不是材料不足】\n")
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

    这一支自己不去造缝（`seam=None` 就是"没有判断面"，`judge()` 会如实报
    `checked=False`）。手上没有缝的构造点该调 :func:`for_role_wired` ——
    它在造秘书之前先把缝拿来，并把"缝从哪来"写进 `Secretary.model_source`。
    """
    return Secretary(str(role), root=Path(str(root)), **kw)


def _ambient_session_sid() -> str | None:
    """这一趟的会话号（`conductor.calling_as` 挂的那一个）；不知道 ⇒ `None`。

    为什么秘书装配要读它：`for_role_wired` 的调用点里有一批拿不到 host 的 `sid=`
    （`AgentV._secretary`、`AgentB._statement_secretary`、若干工具的秘书）。改前它们
    一律传 `sid=None` ⇒ 秘书档的 `llm_call` 事件落进缺省会话
    （`sessions/<当天日期>.jsonl`）：账本按 ambient task 归口，看不出少了一趟；
    但"这一笔不在本趟的审计面上"是事实（RC2 彩排实测 7 条里 4 条是这么来的）。

    为什么不把"空串"当 `sid` 传下去：`sid=""` 与 `sid=None` 在 `sessions.append`
    里同义（都落缺省会话），但调用方要能分开"这一层不知道"与"就用缺省会话"。
    所以这里只在取到会话号时替换 `None`；取不到就保持 `None`，与从前逐字同义。
    """
    try:
        from .llmseam import ambient_sid
        return ambient_sid() or None
    except Exception:  # noqa: BLE001 —— 取不到就是不知道，保持旧行为（sid=None）
        return None


def seam_for_secretary(role: str, *, root: str | Path, seam: Any = None,
                       sid: str | None = None, store: Any = None,
                       meter: Any = None) -> tuple[Any, str]:
    """秘书判断面那一条缝：`(缝 或 None, 读数)` —— 拿不到时读数就说清为什么。

    ## 为什么需要这一处

    不传 `seam=` 的 `Secretary(...)` 会让整条命题同一性判定变成死路：
    `record_statement` 调 :meth:`adjudicate_proposition`，后者调 :meth:`judge`，
    而 `judge` 的第二道闸是"没有缝 ⇒ `checked=False`"。全仓的构造点分散在
    `tools/table_tools.py` / `conductor.py` / `closing.py` / `tools/conductor_tools.py`
    等处，逐个记得传缝不现实 ⇒ 收在 `LlmSeam.for_secretary` 一处现造，
    并把"造没造出来"如实写进读数（没 key / 开关关着 / 装配器不给 ⇒ 各自的 reason）。

    ## 账本：有账本就必须接上

    `meter` 显式给了就用；没给而有 `store` ⇒ 现造 `TokenMeter(store)`；两样都没有
    （单测里的裸缝、没有工作区可落账）⇒ `meter=None`，那一档的 `no_meter` 是
    "没有账本可写"，不是漏接线 —— 漏接线的形态是"有工作区却没记账"，
    那会让一笔真实花销既不在已归口、也不在 `unattributed`，是没有下落。

    接上之后每笔都进账：在召唤上下文里 ⇒ 记到那次召唤的 `task_id`（并回写 `tasks.usd`）；
    不在任何召唤里 ⇒ `task_id=None` + `note` 写明 `unattributed`，由 `reconcile_usage`
    单列一栏点名。三态纪律：发了请求的钱只有"已归口"与"点名说清为什么归不了"两种。
    """
    if sid is None:
        sid = _ambient_session_sid()
    if seam is not None:
        return seam, "body（调用方给的缝）"
    try:
        from .llmseam import LlmSeam
    except Exception as exc:  # noqa: BLE001 —— 拿不到缝的工厂 ⇒ 读数写清，不猜
        return None, f"none（拿不到 llmseam：{type(exc).__name__}: {exc}）"
    # 账本接不接得上与缝要不要造是两件事：接不上不许把判断面关掉（fail-open），
    # 但要把"这一次的 no_meter 是账本没接上"写进读数。
    meter_problem = ""
    if meter is None and store is not None:
        try:
            from . import tokenmeter as _TM
            meter = _TM.TokenMeter(store)
        except Exception as exc:  # noqa: BLE001
            meter_problem = (f"meter 没接上（{type(exc).__name__}: {exc}）"
                             "⇒ 本条缝的调用会落 no_meter")
    try:
        got = LlmSeam.for_secretary(owner_role=str(role), session_root=Path(str(root)),
                                    sid=sid, meter=meter)
    except Exception as exc:  # noqa: BLE001 —— 造缝失败是"没接线"，不是"没有结论"
        return None, f"none（造缝失败：{type(exc).__name__}: {exc}）"
    if got is None:
        return None, "none（LlmSeam.for_secretary 返回 None：造不出秘书档的缝）"
    if not getattr(got, "wired", False):
        return None, ("none（秘书那一档没有配模型 key ⇒ for_secretary 造出来的是空缝；"
                      "这里不把空缝装上去：空缝会把『从来没有判断面』写成『试过了、没成』）")
    if meter_problem:
        return got, f"secretary（LlmSeam.for_secretary；{meter_problem}）"
    return got, "secretary（LlmSeam.for_secretary）"


def for_role_wired(role: str, *, root: str | Path, seam: Any = None,
                   store: Any = None, registry: Any = None,
                   sid: str | None = None, enable_model: bool = True,
                   **kw: Any) -> Secretary:
    """造一名"判断面接上了线"的某角色秘书（手上没有缝的构造点调这一支）。

    与 :func:`for_role` 只差一件事：造秘书之前先把缝拿来
    （:func:`seam_for_secretary`），于是 `judge()` 不会因为"没人传 seam="而永远返回
    `checked=False`。真机 sylow5 的形态就是后一种：五个构造点一个都没传 `seam=`，
    命题同一性判定一次都没发生。

    参数
    ----
    seam : 调用方手上已有的缝（`None` ⇒ 现造一条秘书档的，见 :func:`seam_for_secretary`）。
    enable_model : 与 :class:`Secretary` 同义，缺省 `True` —— 这一支的整个存在意义就是
        把判断面打开；关着的时候 `judge()` 仍然如实返回 `checked=False`（说"开关关着"），
        所以"我明确不要模型判断"也读得出来。
    kw : 其余关键字参数原样交给 :class:`Secretary`（`deadline_sec` / `log` / 两个阈值…）。

    读数：`Secretary.model_source` 记的是"缝从哪来"（三档见 :func:`seam_for_secretary`），
    没有缝时它连着为什么 —— `judge()` 的 `checked=False` 那一格会把这句话一并带出来，
    于是"判不了"在返回值与台账上都能见到原因，而不是静默退回机械判据。
    """
    if sid is None:
        sid = _ambient_session_sid()
    seam_now, source = seam_for_secretary(str(role), root=root, seam=seam, sid=sid,
                                          store=store)
    sec = Secretary(str(role), root=Path(str(root)), store=store, registry=registry,
                    seam=seam_now, sid=sid, enable_model=bool(enable_model), **kw)
    try:
        sec.model_source = source
    except Exception:  # noqa: BLE001 —— 留痕写不上不许把秘书造失败（判断面还在）
        pass
    return sec


def concept_identity_gate(tx: Any, *, label: str, full: str = "",
                          exclude_id: str = "") -> dict[str, Any]:
    """写一条新概念行之前先过这一闸（在发号之前调）：不写盘，只回判词。

    ## 为什么需要这一处（2026-11-08，D2 的后门）
    `Secretary.write_concept_row` 会算概念同一性，但它的调用方（`conceptrows.upsert` /
    `agent_b/run_once.resolve_concept`）在调用它之前就已经把号发出去了；于是"判不了
    就拒"落在那一层只会留下 `id_gap`（分配了 ID 但未建成行），而"放过"又等于概念轴
    有个后门。正确形状是"先判后分号"，而判据本体只该有一处 —— 这一格就是给调用方在
    `tx.alloc_id(...)` 之前调的那个口。

    ## 返回
    `{"checked", "state", "basis", "reason", "candidates"}`，与
    `Secretary._same_concept_candidate` 同源（唯一的 `same_concept` 调用点）：

    - `checked=True` + `state="same"`：在册已有同一个概念（`candidates` 点名）——
      调用方按 D2 并进那一行，不新建；
    - `checked=True` + `state="different"`：判过了、不同（含"在册 0 条可比行"）⇒
      照常发号新建；
    - `checked=False`：没判成 ⇒ 调用方受控拒（`concept_identity_unjudged`），
      一个号都不发。

    概念这一档是确定性判据、零模型调用，所以现造一名无缝秘书是对的（缝与本判据无关）。
    """
    store = getattr(tx, "_store", None)
    root = str(getattr(store, "root", "") or "")
    sec = Secretary("B", root=Path(root) if root else Path("."), store=store,
                    seam=None, enable_model=False)
    got = sec._same_concept_candidate(tx, label=str(label or ""),
                                      full=str(full or ""),
                                      exclude_id=str(exclude_id or ""))
    return {key: got.get(key) for key in
            ("checked", "state", "basis", "reason", "candidates")}


#: 概念同一性闸的三种处置（`concept_identity_action` 的唯一取值表）。
CONCEPT_IDENTITY_ACTIONS: tuple[str, ...] = ("created", "merged", "refused")


def concept_identity_action(gate: Mapping[str, Any]) -> dict[str, Any]:
    """把同一性闸的判词折成唯一一档处置（四个写入口共用，2026-11-08）。

    ## 为什么要有这一格（改前四个入口各判各的、也各不处置）
    `concept_identity_gate` 只回判词（`checked` / `state` / `candidates` / `reason`），
    而"判成 same 该并入哪一行、判不了该不该拒"四个入口各写各的：`conceptrows.upsert`
    只读 `checked`、`_record_pending_concept` 完全不判、`run_once.resolve_concept` 只按
    名字找 —— 于是闸判出来的 `same` 在四个落点都被丢掉（真机 mp3-r2 的 000003 / 000004）。
    把"判词 ⇒ 处置"收成这一处，四个入口只读它的 `concept_action`。

    ## 三档（题面 2026-11-08 逐字）
    | 闸的判词 | `concept_action` | 处置 |
    |---|---|---|
    | `checked=False`（判不了） | `refused` | 受控拒、不发号（counters 不动） |
    | `checked=True` + `state="same"` + 有候选 | `merged` | 并入 `same_as` 那一条，不新建行、不发号 |
    | 其余（`different` / 候选 0 条） | `created` | 照常新建 |

    `state="same"` 却没有候选（判词不自洽）按 `created` 走：没有可并入的对象时
    新建是唯一可执行的处置 —— 但这一档不静默，`reason` 原样带出去。

    返回的字典同时是那四个入口的读数：`checked` / `state` / `basis` / `same_as` /
    `candidates` / `reason` 六格齐全（并入与新建读同一份，不另写一份读数）。
    """
    got = dict(gate or {})
    checked = bool(got.get("checked"))
    state = str(got.get("state") or "")
    candidates = [str(x) for x in (got.get("candidates") or []) if str(x)]
    basis = str(got.get("basis") or "")
    reason = str(got.get("reason") or "")
    if not checked:
        return {"concept_action": "refused", "checked": False, "state": "",
                "basis": basis, "same_as": "", "candidates": candidates,
                "reason": reason}
    if state == _PK.STATE_SAME and candidates:
        return {"concept_action": "merged", "checked": True, "state": state,
                "basis": basis, "same_as": candidates[0],
                "candidates": candidates, "reason": reason}
    return {"concept_action": "created", "checked": True,
            "state": state or _PK.STATE_DIFFERENT, "basis": basis, "same_as": "",
            "candidates": candidates, "reason": reason}


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



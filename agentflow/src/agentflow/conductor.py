"""主控编队：把"一次召唤"做成可审计、可拒绝、可取消、可重建的台账行。
用户只对主控说话；它负责理解 → 拆解 → 召唤 → 汇总 → 报告，不是一个额外的"智能层"：不产出
知识、不写关系、不改稿件，产出只有 (a) 召唤、(b) 给用户的汇总。于是它的"正确性"= 召唤序列
是否满足策略与预算，而不是"它聪不聪明"；所以本模块里没有任何 LLM 调用（真 LLM 主控由
`SubagentBackend` 承担，本轮显式未接线）。
## 两个最容易写错的地方
1. 拒绝是 `status="done", outcome="refused"`：`refused` 是一次成功的执行（框架正确地说了
   "不"），写成 `failed` 会把"策略拦住了"与"代码崩了"混在一起；`schema.Task.validate` 已钉死
   （`outcome=refused` ⇒ `status` 必须 `done`）。拒绝也落台账，否则"我们拒绝过它"无可审计。
2. `finish()` 必须幂等 —— 不在 `finish` 里判断，而在事务内重读当前行：只有
   `status in ("pending","running")` 才写（FC-20"终态先到先得"，`schema.Task.validate` 兜底）。
## 三态纪律在本模块的落点
| 场景 | 禁止 | 本模块的做法 |
|---|---|---|
| 角色没有这个动作 | 只写一句人话 | `refusal_reason="unknown_action"` |
| 动作没接线 | 抛异常 / 返回空 | `refusal_reason="not_wired"`（backend=subagent 亦然） |
| handler 返回 None | 当成 `ok` | `outcome="no_result"` |
| 查询没法做 | `checked=True, empty=True` | 原样透传 `checked=False` + `reason` |
| 被 dispose 砍掉 | 记成 `failed` | `status=cancelled` + detail 写"结果未知" |
"""

from __future__ import annotations

import contextlib
import contextvars
import hashlib
import inspect
import itertools
import json
import threading
import time
from dataclasses import asdict, dataclass, field, is_dataclass, replace
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator, Mapping, Sequence

from . import capabilities as C
from . import cancellation as CX
from . import clock as CLK
from . import identity as IDENT
from . import policy as P
from . import schema as S
from .cancellation import CANCEL_CODES, CancelRequested, CancelToken, detail_of
from .canonical import json_default
from .policy import Decision
from .scheduler import MemoryBudgetTracker, TaskCall
from .store import StoreError
#: 不在这里另定义 `ParamError`。
#:
#: 判据是"同一判据两处实现"：调用方按 `except ParamError` 捕获"参数不合法"时，
#: 若两处各有一个同名类，漏掉一半没有任何报错。`tools.base.ParamError`
#: 的语义本来就是"参数不合法，与『执行中失败』分开"，与本模块要的完全一致，
#: 所以选 import 同一份，而不是换名字（换名字会留下两个概念表达同一件事）。
from .modelcost import settle_key
from .tokenmeter import Charge, TokenMeter
from .tools.base import ParamError
from .agentspec import AgentBrief, AgentSpec
# 顶层 import：本文件要从秘书那一侧转发两个常量
# （活档状态表、收工那句话的点名上限），转发比分头写一个字面量安全。
# 方向只能是这样：`secretary` 顶层不 import `conductor`（秘书那一侧是懒 import），
# 所以本行无环。
from . import secretary as SEC

#: 一次召唤的终局状态（`status`），与 `schema.TASK_STATUSES` 一致。
TERMINAL_STATUSES: tuple[str, ...] = ("done", "cancelled", "failed")

#: 「自身有未收口的任务」= 这一行还停在这些状态里（`schema.TASK_STATUSES` 的其余几格都是终态）。
#:
#: `block` 刻意不在里面：它是"停了、但这件活没做完"（`schema.TASK_STATUSES` 那一行的注释逐字）。
#: 停了就不是"还在做"，而「活跃」问的是"还在做 / 在等"，不是"欠着多少活"—— 后者由
#: `open_items_of` 与 `retire_ready` 的 `items_open` 各自回答，两轴不许折成一格。
#: 真身在 `secretary.LIVE_TASK_STATUSES`：判据就这一份，转发到这里之后"改一处忘另一处"
#: 在结构上不可能；判据 `tests/test_live_statuses_single_source.py` 钉住"两处名字取到的
#: 必须是同一个元组"与"这两个文件里不再有第二处字面量"。
UNFINISHED_STATUSES: tuple[str, ...] = tuple(SEC.LIVE_TASK_STATUSES)

#: 两个读数各自的机器键：两个数分开命名，不许混成一个数。
#:
#: 口径：「未销号的子代理数叫子代理数，工作未做完还在做的子代理数叫活跃子代理数」。
#: 键给机器，中文名给人，两者同源（`CHILD_COUNT_LABELS`）—— 名册面、收工读数与 CLI
#: 读数都从这里取措辞，不许各写一份（同一读数三处措辞迟早会漂成三个意思）。
#:
#: `children_unretired` 量的是「名册里还没销号的子」，不是「台账里挂了几个子」；后者是
#: 网页名册面那一格，叫 `children_in_ledger`（`webui.readers.roster_face`）。
#: 两个量两个名，说明各写在自己的那一处：这里 → 名册 / 未销号；那边 → 台账 / 含未落名册。
CHILD_COUNT_KEY = "children_unretired"
ACTIVE_CHILD_COUNT_KEY = "active_child_count"
CHILD_COUNT_LABELS: dict[str, str] = {CHILD_COUNT_KEY: "子代理数",
                                      ACTIVE_CHILD_COUNT_KEY: "活跃子代理数"}
#: 每个名字量的是什么的一句说明：
#: 中文名给人看（上面那张表，保持短），口径读这里。两个量各一句，谁也不许含糊：
#: - `children_unretired`：名册里还没销号的名册项数（不是台账里的子数 ——
#:   台账那一格是网页名册面的 `children_in_ledger`，含没落名册的子）；
#: - `active_child_count`：其中非静默的数量（在飞 + 待机；unknown 既不算活跃也不算静默）。
CHILD_COUNT_CALIBERS: dict[str, str] = {
    CHILD_COUNT_KEY: "名册里未销号的名册项数（不是台账里的子数；台账那一格是网页名册面的 "
                     "children_in_ledger，含没落名册的子）",
    ACTIVE_CHILD_COUNT_KEY: "上述名册项里非静默的数量（在飞 + 待机；unknown 既不算活跃也不算静默）",
}

#: 信息型板项的 `kind`：读进提示词那一拍就消费完 ⇒ "seen 即 ack"（判据与理由在
#: `Conductor` 的"工作项板"那一节，落点是 `Conductor.mark_item_seen`）。
INFORMATIONAL_ITEM_KINDS: tuple[str, ...] = ("notice", "message")

#: 例外：`kind` 落在上面那一档、但它是"要你办事"的 —— 读了不等于办了，模型必须自己 ack。
#:
#: 每条写清是哪件事、为什么不能被代 ack：
#: - `v-verdict@`：V 判「有毛病」⇒ 收件人要把第 N 步补上再重送 V（`agent_loop.deliver_v_verdicts`）。
#:   读它不等于补它；
#: - `stop-notice@`：停止通知（叫停）。它的 ack 语义是"传达到了"，由
#:   `agent_loop._ack_stop_notice` 代做并在父那一行落 `stop-acked:` 时刻；走通用路会
#:   把那一刻弄丢（`Conductor.stop_edge_readings` 的 `acked_at` 读的就是它）；
#: - `relay@`：沿链传来的指导（`Secretary.deliver_local`）。这一条还没裁定：沿链的
#:   指导有时就是要办的事，所以今天不动它的旧行为（仍要 ack）。裁定之后只改这一格。
ACK_REQUIRED_ITEM_PREFIXES: tuple[str, ...] = ("v-verdict@", "stop-notice@", "relay@")

#: 撤销通知行的 `input_key` 前缀。
#:
#: 缺省不再落这一种行（`REVOKE_POSTS_NOTICE_ROW=False`），这个前缀
#: 只剩两个用途：① 旧工作区里那些历史 `revoke-notice@…` 行仍然认得出（它们是
#: `expects=""` 的已收口行，`_void_item_gate` 的 `no_obligation` 那一档会拒撤它们）；
#: ② 反真空判据把另一档整格打开时，防环那一句仍然读它。
#:
#: 为什么需要它：
#: 1. 幂等 —— 同一条项只该有一份撤销通知（撤销本身也只能落一次）；
#: 2. 防环 —— 通知自己也是一条 `tasks` 行；没有这个前缀，撤一条通知会再生成一条
#:    通知，撤通知的通知又会生成一条……`.void_items` 用它认出"这一条是通知，不再
#:    替它发通知"。
REVOKE_NOTICE_PREFIX: str = "revoke-notice@"

#: 撤销留痕在那一行 `inputs` 里的机器前缀（与 :meth:`Conductor.void_items` 写的那一条同源）。
#:
#: 为什么读侧也要一个前缀：撤销与"作废"（`void:expired:…`）都收口成
#: `done` + `expired`，光看状态分不开"这条是被撤了"与"这条是被作废了"。撤销的正文
#: 只认 `revoke`，所以「最近被撤销」这一格只认这一条前缀。
REVOKE_MARK_PREFIX: str = "revoke:expired:"

#: 「最近被撤销」这一格一次回几条（收件人那一侧的读数与提示词共用这一个数）。
#:
#: 为什么有上界：撤销是流水，无限回会把提示词的一格撑成整本台账；N 之内足够回答
#: 「我名下最近哪几条被撤了」，更早的去台账里看（每一行 `inputs` 都留着六格）。
#: 口径是「自动提醒，且要真能提醒到」——「最近 N 条」是提醒，不是全量同步。
REVOKED_RECENT_LIMIT: int = 5

def _revoke_mark_of(row: Mapping[str, Any]) -> str:
    """这一行 `inputs` 里那条撤销留痕（没有 ⇒ 空串）。"""
    for text in row.get("inputs") or ():
        line = str(text)
        if line.startswith(REVOKE_MARK_PREFIX):
            return line
    return ""

def _parse_revoke_mark(mark: str) -> dict[str, str]:
    """把一条 `revoke:expired:…` 留痕拆回六格；拆不出的格给空串（不猜）。

    形状是固定的（写侧只有 :meth:`Conductor.void_items` 一处）：
    `revoke:expired:by=…:owner=…:from=…:to=done:at=<ISO>:reason=…`。
    `at` 是 ISO 时刻、本身带冒号，所以不能按冒号一律切：先定位 `:at=` 与
    `:reason=` 两个分隔点，再拆前面那四格。`reason` 是最后一格，其余冒号都归它。
    """
    rest = str(mark)[len(REVOKE_MARK_PREFIX):]
    at_at = rest.find(":at=")
    at_reason = rest.find(":reason=", at_at if at_at >= 0 else 0)
    out: dict[str, str] = {}
    for part in (rest[:at_at] if at_at >= 0 else rest).split(":"):
        key, sep, value = part.partition("=")
        if sep:
            out[key] = value
    # `rest` 的长度两支都要用（`at` 那一格没有 `:reason=` 时收到串尾）—— 量一次就够。
    end = len(rest)
    if at_at >= 0:
        out["at"] = rest[at_at + len(":at="):at_reason if at_reason >= 0 else end]
    if at_reason >= 0:
        out["reason"] = rest[at_reason + len(":reason="):]
    return out

def _board_item_summary(row: Mapping[str, Any], *, cap: int = 200) -> str:
    """一条板项的一句话摘要（`detail` 归一化 + 截断）—— 通知正文与「最近被撤销」共用。"""
    text = " ".join(str(row.get("detail") or "").split())[:cap]
    return text or "（没有摘要）"

# ---------------------------------------------------------------- 三态（在飞 / 待机 / 静默）
#
# 三种读数：1. 在工作叫「在飞」，2. 在等待（计时器）为「待机」，3. 已收工、无任务、
# 无计时器叫「静默」；「活跃子代理」= 非静默子代理。
#
# 加上第四档 `unknown`（读不到台账 / 名册 / 时钟 ⇒ 判不了，不许折成静默）：
# "没查成"与"查过了、它是静默的"是本项目最贵的一类折叠 —— 折成静默会让一个还挂在
# 时钟上的代理被判成收工了，而"能不能销号"正好读这一格。

#: 在工作（自己在跑一个回合）。
AGENT_STATE_FLYING = "flying"
#: 在等待：没在工作，但时钟上挂着等待（timer / alarm / periodic），或在等名下的活。
AGENT_STATE_STANDBY = "standby"
#: 已收工、无任务、无计时器（以及已销号 —— 销号即退场）。
AGENT_STATE_SILENT = "silent"
#: 判不了（台账 / 名册 / 时钟有一处读不成）。第四档，不是静默的别名。
AGENT_STATE_UNKNOWN = "unknown"

#: 销号拒信的机器码：目标不是静默（在飞 / 待机 / 未读到）。
#:
#: 口径：「销号可以也只可针对静默子代理」。这一条闸的
#: 拒绝不是"工具坏了"也不是"它不在你名下"，而是"它现在不能销"——父下一步该做的是
#: 让它收工 / 等那些计时器 / 显式让它停，所以拒信必须带这个码，让调用方按码分流。
RETIRE_REFUSAL_TARGET_NOT_SILENT = "target_not_silent"

#: 三态词表。顺序就是"前面的优先"：在飞 → 待机 → 静默；`unknown` 是三态之外的一档。
AGENT_STATES: tuple[str, ...] = (AGENT_STATE_FLYING, AGENT_STATE_STANDBY,
                                 AGENT_STATE_SILENT, AGENT_STATE_UNKNOWN)

#: 「活跃」= 非静默 = 在飞 + 待机。
#:
#: `unknown` 刻意不在这里：判不了不等于活跃，也不等于静默 —— 它自己的计数格单独给
#: （`unknown` 那一格非 0 时，`complete` 一律是 False，读数里逐条点名）。
ACTIVE_AGENT_STATES: tuple[str, ...] = (AGENT_STATE_FLYING, AGENT_STATE_STANDBY)

#: 三态的中文名（唯一一份：名册面、网页、读数都从这里取措辞，不许各写一份）。
AGENT_STATE_LABELS: dict[str, str] = {AGENT_STATE_FLYING: "在飞",
                                      AGENT_STATE_STANDBY: "待机",
                                      AGENT_STATE_SILENT: "静默",
                                      AGENT_STATE_UNKNOWN: "未读到"}

#: 一个 `status=running` 的任务多久没有新 step 就算"疑似停滞"（秒）。
#:
#: 取值理由（N = 10 分钟 = 600 秒，理由要能被读数反驳）：
#:
#: 1. 停转的一趟会以远大于 N 的间隔翻 step（分钟级到十几分钟才一步），它不是"跑得慢"，
#:    它是"没在跑"。
#: 2. 而正常一步（一次模型调用 + 一次工具执行）在本仓是秒级到 1 分钟的量级 ⇒
#:    10 分钟比"正常一步"高一个数量级，正常步进不会被读成停滞。
#: 3. 它又比那些停转的间隔低一个数量级 ⇒ 那一段里稳定读得出停滞，而不是"永远差一点"。
#: 4. 600 秒与时钟那条计时器的缺省时长同一个量级 ⇒ "停转了 11 分钟"与"等一条 11 分钟
#:    的钟"用的是同一把尺，读的人不必在两套时间尺度之间换算。
#:
#: 这一格只用来读"疑似"：它不改三态（停滞的任务仍是 `flying`），也不进销号门的判据
#: （停滞不等于静默 —— 见 `agent_state` 的 ⑩ 条与 `retire_blocking` 的单飞那一档）。
STALLED_AFTER_SEC: float = 600.0

#: 步进落痕的目录（相对工作区根）：`out/steps/<台账号>.json`，一个代理一个文件。
#:
#: 为什么另起一格而不是写进 `tasks` 台账：台账是"一次召唤一行"的终态账（FC-20 先到先得），
#: 它没有"最近一步"这一列，而且每一步都去改它会把同一条行上的并发写放大成锁竞争。
#: 一件比它便宜得多的事实（最近一步是什么时候）不值得付那个价：一个几十字节的文件、
#: 一次原子替换，读侧一次目录遍历就够。
STEPS_DIR: tuple[str, ...] = ("out", "steps")

#: 三态的强弱次序（只用于"一个代理接过好几件活 / 一整支子树"这类聚合读数）。
#:
#: `unknown` 排在 `silent` 之上：聚合时"有一格判不了"不许被"有一格是静默的"吃掉 ——
#: 那是 fail-open 在同一份读数里的另一种形态（把没查成折成静默）。
AGENT_STATE_RANK: dict[str, int] = {AGENT_STATE_FLYING: 3, AGENT_STATE_STANDBY: 2,
                                    AGENT_STATE_UNKNOWN: 1, AGENT_STATE_SILENT: 0}


def _instance_of_task(conductor: Any, task_id: str) -> str:
    """这个台账号那一趟的实例标签（K9：板项收件地址的读法，`identity` 是唯一来源）。

    台账号兜底（`source == "task_id"`）不算实例标签 —— 那一条是"这一笔没有实例身份"
    的兼容读数，拿它当地址会让同一个实例换个号就收不到自己的项。
    """
    store = getattr(conductor, "store", None)
    role = ""
    try:
        row = next((dict(r) for r in store.rows("tasks")
                    if str(r.get("task_id") or "") == str(task_id or "")), None) if store else None
        role = str((row or {}).get("role") or "")
    except Exception:  # noqa: BLE001 —— 读不成 ⇒ 没有实例标签
        return ""
    if not role or not str(task_id or ""):
        return ""
    try:
        from . import identity as _ID

        got = dict(_ID.resolve_identity(store, role, task_id=str(task_id)))
    except Exception:  # noqa: BLE001
        return ""
    if str(got.get("source") or "") == "task_id":
        return ""
    return str(got.get("instance") or "")


def state_counts(states: Iterable[str]) -> dict[str, int]:
    """四档各几个 + `active`（= 在飞 + 待机）+ `total`。词表外的取值一律记进 `unknown`。

    为什么不把词表外的取值丢掉：丢掉会让 `total` 比实际少，而"少了几个"在读数上
    看不出来（`active` 也不会因此变错，于是没有任何一处会报）。
    """
    counts: dict[str, int] = {name: 0 for name in AGENT_STATES}
    for raw in states:
        got = str(raw or "")
        counts[got if got in counts else AGENT_STATE_UNKNOWN] += 1
    counts["active"] = counts[AGENT_STATE_FLYING] + counts[AGENT_STATE_STANDBY]
    counts["total"] = sum(counts[name] for name in AGENT_STATES)
    return counts


def most_active_state(states: Iterable[str]) -> str:
    """几个三态合成一个（在飞 > 待机 > unknown > 静默；一个都没有 ⇒ unknown）。

    用在"一个代理接过好几件活"的聚合上：它现在是哪一态，由它那几行里最活跃的那一行说。
    """
    best = ""
    for raw in states:
        got = str(raw or "")
        if got not in AGENT_STATE_RANK:
            got = AGENT_STATE_UNKNOWN
        if best == "" or AGENT_STATE_RANK[got] > AGENT_STATE_RANK[best]:
            best = got
    return best or AGENT_STATE_UNKNOWN


def handoff_index(workspace: str | Path) -> dict[str, Any]:
    """交差账的索引（`{代理编号: 那一行}`）：全仓唯一读口，只读。

    ## 为什么它属于"三态"这一族
    口径：「如果已无事可做且无计时器，这意味着它交差了，需要向父代理报告，父代理把它
    记为静默子代理」。所以"交差"是静默的一条盘上证据（不是旁证），而它只有两处读法
    （`Conductor.handoffs_reading` 的 `silent` 那一格与 `agent_state` 的三态）。
    两处口径必须同源 —— 后果具体：一份"父已经记为静默"的子代理，在销号门上
    仍是"在飞"（`status=running`），于是父明明被告诉"静默子可销"，去销又吃到
    `target_not_silent`；而它占着的那个扇出名额谁也腾不出来。

    这一格只回答"账上有没有它的交差"，不回答"它现在忙不忙"：忙不忙由
    `agent_state` 按同一份事实判（交差 ≠ 满速跑 ⇒ 它不再算"自己在跑"）。

    ## 三态（与时钟簿记同一条纪律）
    读不成 ⇒ `checked=False` + `reason`，`by_task` 是空表。调用方据此按"不知道"
    处理，而不许折成"它交过差"：销号不可逆，把"没查成"读成"可以销"是错的方向。
    真正判不出来时 `agent_state` 落到"在飞"（保守方向 = 不销），见它的第 ⑥ 步。

    返回 `{"checked", "by_task", "rows", "count", "reason"}`；`by_task` 每格原样是
    交差账里的那一行（`handoff_id` / `task_id` / `parent_task_id` / `role` / `reason`
    / `at` / `timers` / `children`，父收过的那条另有 `seen_by`）。
    """
    out: dict[str, Any] = {"checked": False, "by_task": {}, "rows": [],
                           "count": 0, "reason": ""}
    try:
        got = CLK.read_handoffs(workspace)
    except Exception as exc:  # noqa: BLE001 —— 读不成是"没查成"，不是"没人交差"
        out["reason"] = f"交差账读不成（{type(exc).__name__}: {exc}）"
        return out
    rows = [dict(r) for r in (got.get("rows") or ()) if isinstance(r, Mapping)]
    by_task: dict[str, dict[str, Any]] = {}
    for row in rows:
        tid = str(row.get("task_id") or "")
        if tid and tid not in by_task:
            by_task[tid] = row
    out.update({"checked": bool(got.get("checked")), "by_task": by_task,
                "rows": rows, "count": len(rows),
                "reason": str(got.get("reason") or "")})
    return out


def steps_dir(workspace: str | Path) -> Path:
    """这个工作区的步进落痕目录（`<工作区>/out/steps`）。"""
    return Path(str(workspace or "")) / STEPS_DIR[0] / STEPS_DIR[1]


def stamp_step(workspace: str | Path, *, task_id: str, role: str = "", step: int = 0,
               sid: str = "", at: str = "") -> tuple[str, str]:
    """把一个代理"刚走了这一步"落成盘上的一个文件；返回 `(路径, 问题)`。

    写的是 `<工作区>/out/steps/<台账号>.json`：`{"task_id", "role", "step", "at", "sid"}`。
    每一次覆盖同一个文件（它不是历史，是"最近一次"的读数），并用一次原子替换落盘
    （先写 `.tmp` 再 `Path.replace`）—— 半份 JSON 在读侧会变成一个坏文件，而"读不成"
    在那一边只能按"不知道"处理，于是停滞读数会因为一次撕裂的写而丢掉一格。

    谁调它：`AgentLoop` 的步边界（每一步一次）。为什么不是"结束时写一次"：这一格
    要回答的正是"它现在还在走吗"，结束时才写的读数永远回答成"没在走"。

    失败姿态：不抛，问题随返回值回去（写不成只影响"停滞"这一格的可信度，不许拦住
    那一步本身）。
    """
    tid = str(task_id or "")
    if not tid:
        return "", "没有台账号 ⇒ 这一步没有落痕（不是「它没走过步」）"
    root = str(workspace or "")
    if not root:
        return "", "没有工作区根 ⇒ 这一步没有落痕"
    row = {"task_id": tid, "role": str(role or ""), "step": int(step),
           "at": str(at or S.now_iso()), "sid": str(sid or "")}
    target = steps_dir(root) / f"{tid}.json"
    tmp = target.with_name(target.name + ".tmp")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(row, ensure_ascii=False, sort_keys=True,
                                  default=json_default) + "\n",
                       encoding="utf-8", newline="\n")
        tmp.replace(target)
    except OSError as exc:  # noqa: BLE001 —— 写不成只影响这一格的可信度
        return "", f"步进落痕没写成（{type(exc).__name__}: {exc}）"
    return str(target), ""


def _since_sec(at: Any, now_dt: Any) -> float | None:
    """`at` 到 `now_dt` 差了多少秒（读不成 / 不是时间 ⇒ `None`，不折成 0 或负数）。"""
    from datetime import datetime, timezone   # 惰性：只在这一格用

    text = str(at or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        then = datetime.fromisoformat(text)
    except ValueError:
        return None
    if getattr(then, "tzinfo", None) is None:
        then = then.replace(tzinfo=timezone.utc)
    sec = (now_dt - then).total_seconds()
    # 盘上的时刻比读数这一拍还晚（两台机器的钟差 / 手写夹具）⇒ 按 0 读，不报负数：
    # 负数会让"已经 -3 分钟没有新步"这种读数出现在给模型看的那一句里。
    return 0.0 if sec < 0 else float(sec)


def _hhmm(at: Any) -> str:
    """ISO 时刻里那一段 `HH:MM`（读不出来就把原串还回去，绝不编一个时刻）。"""
    text = str(at or "")
    if "T" in text:
        got = text.split("T", 1)[1][:5]
        if len(got) == 5:
            return got
    return text or "（没读到时刻）"


def step_beats(workspace: str | Path, *, threshold_sec: float = STALLED_AFTER_SEC,
               now: str = "") -> dict[str, Any]:
    """每个代理最近一次 step 落在什么时候（`out/steps/`）：停滞读数的唯一读口。

    ## 这一格回答什么
    `status=running` 说的是"台账那一行还没落终态"，它不等于"它现在在跑"。真机
    `projects/mp3-r3` 的 B1（t-000006）就是反例：81 分钟里只有 4 个 step，其余时间它
    既没在跑、也没交差，状态却一直是 `running` ⇒ 页面显示"在飞"，而父那一侧的结项
    闸因为"名下还有活跃子"结不了项。这一格给那一句话一个盘上证据：最近一步是什么时候。

    ## 返回
    `{"checked", "by_task", "rows", "count", "dir", "threshold_sec", "now",
    "problems", "reason"}`；`by_task[台账号]` 是
    `{"task_id", "role", "step", "at", "sec", "sid"}`（`sec` = 距现在多少秒）。

    ## 三态
    - 目录不在盘上（这个工作区还没有任何一步落过痕）⇒ `checked=True, count=0`：
      这是"读到了、里面一个文件也没有"，不是"它没走过步" —— 一个老工作区里的行
      本来就没有这一格，调用方（`agent_state`）据此不下停滞的结论；
    - 目录在、读不出来 ⇒ `checked=False` + `reason`：调用方按"不知道"处理，
      绝不折成"没有停滞"（也不折成"停滞了"）；
    - 单个文件坏 ⇒ 进 `problems`、那个代理没有格子（同上：没有证据就不下结论）。
    """
    from datetime import datetime, timezone   # 惰性：只在这一格用

    out: dict[str, Any] = {"checked": False, "by_task": {}, "rows": [], "count": 0,
                           "dir": "", "threshold_sec": float(threshold_sec),
                           "now": "", "problems": [], "reason": ""}
    root = str(workspace or "")
    if not root:
        out["reason"] = "没有工作区根 ⇒ 步进落痕读不成（不是「一步都没走」）"
        return out
    target = steps_dir(root)
    out["dir"] = str(target)
    now_text = str(now or S.now_iso())
    try:
        now_dt = datetime.fromisoformat(now_text.replace("Z", "+00:00"))
    except ValueError:
        out["reason"] = f"这一拍的时刻读不成（{now_text!r}）⇒ 停滞读数没有基准"
        return out
    if getattr(now_dt, "tzinfo", None) is None:
        now_dt = now_dt.replace(tzinfo=timezone.utc)
    out["now"] = now_text
    try:
        files = sorted(target.glob("*.json")) if target.is_dir() else []
    except OSError as exc:  # noqa: BLE001 —— 读不成是"没查成"
        out["reason"] = f"步进落痕目录读不成（{type(exc).__name__}: {exc}）"
        return out
    rows: list[dict[str, Any]] = []
    by_task: dict[str, dict[str, Any]] = {}
    for path in files:
        try:
            got = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:  # noqa: BLE001 —— 一个坏文件不许带走整张表
            out["problems"].append(f"{path.name} 读不成（{type(exc).__name__}: {exc}）")
            continue
        if not isinstance(got, Mapping):
            out["problems"].append(f"{path.name} 不是对象 ⇒ 这一格没读成")
            continue
        tid = str(got.get("task_id") or path.stem)
        if not tid:
            out["problems"].append(f"{path.name} 没有台账号 ⇒ 这一格没读成")
            continue
        sec = _since_sec(got.get("at"), now_dt)
        if sec is None:
            out["problems"].append(
                f"{path.name} 的 `at` 读不成（{got.get('at')!r}）⇒ 停滞读数没有基准")
            continue
        row = {"task_id": tid, "role": str(got.get("role") or ""),
               "step": got.get("step"), "at": str(got.get("at") or ""),
               "sec": round(float(sec), 3), "sid": str(got.get("sid") or "")}
        rows.append(row)
        by_task[tid] = row
    out.update({"checked": True, "by_task": by_task, "rows": rows,
                "count": len(rows), "reason": ""})
    return out


def clock_waiters(workspace: str | Path) -> dict[str, Any]:
    """这个工作区的时钟上还挂着的等待，按代理编号归组（唯一实现，只读）。

    `{"checked", "by_task", "rows", "count", "reason"}`：`by_task` 是
    `{代理编号: [一条等待...]}`，每一条带 `id` / `kind` / `park_state` / `at` /
    `purpose` / `to`。

    ## 哪些算"挂着"
    - 一次性计时器 / 闹钟（`kind ∈ {timer, alarm}`）：`state == "pending"`。
      等时间的那一条（`after_sec`，`park_state` 是空串）也算挂着 —— 业主说的是
      「在等待（计时器）」，不是"只有 park 才算"；`park_state == "parked"` 是其中
      "等谁"的那一小类（挂机）。
    - 周期性巡查（`kind == "periodic"`）：`state == "running"`（还在跳）。
      到点不消耗，所以"还有下一拍"就是"还挂着"。

    ## 三态
    时钟簿记读不成（`out/clock/state.json` 坏了、权限不对）⇒ `checked=False` + `reason`，
    `by_task` 是空表。它不等于"没有等待"：调用方据此把三态判成 `unknown`，
    而不是"静默"（`Conductor.agent_state` 的判定次序第 ④ 步就是这一条）。

    ## 三份额外的读数与时钟同出（各带自己的三态位）
    `wait_any_*`（等待任意计时器的意图）、`handoff_*`（交差账）、`stall_*`（步进落痕，
    停滞读数那条链的输入）。三者都不是计时器，但都是"它现在有没有事"的证据 ⇒ 与时钟
    同一份读数交出去，于是同一次三态看到的是同一个时刻的盘。各自的 `*_checked` 分开：
    一份读不成不许把另外两份也折成"没有"。
    """
    out: dict[str, Any] = {"checked": False, "by_task": {}, "rows": [],
                           "count": 0, "reason": "",
                           # "等待任意计时器返回"的那本意图账（`out/clock/wait_any.json`）。
                           # 三态独立：时钟簿记读得成而这份读不成时，`checked=True` 而下
                           # 面那一格 `wait_any_checked=False` —— 不许把"没查成"折成"没请求过"。
                           "wait_any_checked": False, "wait_any_by_task": {},
                           "wait_any_reason": "", "pending_total": 0,
                           # 交差账（`out/clock/handoffs.json`）那一格：与时钟同一份
                           # 读数交出去（`agent_state` 的第 ⑥ 步要它：交差了的子代理
                           # 不再算"自己在跑"）。为什么与时钟放在一起：三态的两条输入
                           # （"挂着什么"与"交没交差"）都是"它现在有没有事"的证据，
                           # 分成两次读会让同一份三态看到两个时刻的盘。
                           "handoff_checked": False, "handoff_by_task": {},
                           "handoff_reason": "",
                           # 步进落痕那一格（停滞读数：`out/steps/<台账号>.json`）。
                           # 理由与上面两条相同：三态与停滞要看到同一个时刻的盘。
                           "stall_checked": False, "stall_by_task": {},
                           "stall_reason": "", "stall_problems": [],
                           "stall_threshold_sec": STALLED_AFTER_SEC,
                           "stall_now": ""}
    try:
        bucket = CLK.book(workspace)
        timers = list(bucket.all())
        periodics = list(bucket.all_periodics())
    except Exception as exc:  # noqa: BLE001 —— 读不成是"没查成"
        out["reason"] = f"时钟读不成（{type(exc).__name__}: {exc}）"
        return out
    rows: list[dict[str, Any]] = []
    lifeline_rows: list[dict[str, Any]] = []
    for timer in timers:
        if str(getattr(timer, "state", "")) != "pending":
            continue
        row = {"id": str(getattr(timer, "timer_id", "") or ""),
               "kind": str(getattr(timer, "kind", "") or ""),
               "park_state": str(getattr(timer, "park_state", "") or ""),
               "at": str(getattr(timer, "due_at", "") or ""),
               "purpose": CLK.purpose_of(timer),
               "to": str(getattr(timer, "to", "") or ""),
               "task_id": str(getattr(timer, "task_id", "") or "")}
        # 兜底计时器单列（业主 2026-10-29）：它是框架的保活账、代理对它无感，
        # 不许混进 `rows` —— 混进去会让"挂着东西"恒真、三态里的静默整档消失，
        # 而且没有任何一处会报错。
        if CLK.is_lifeline(timer):
            lifeline_rows.append(row)
            continue
        rows.append(row)
    for periodic in periodics:
        if str(getattr(periodic, "state", "")) != "running":
            continue
        rows.append({"id": str(getattr(periodic, "periodic_id", "") or ""),
                     "kind": "periodic",
                     # 周期性巡查的"等谁"也是挂机（`wait_for` 非空），与 timer 同一口径。
                     "park_state": "parked" if str(getattr(periodic, "wait_for", "") or "")
                     else "",
                     "at": str(getattr(periodic, "next_at", "") or ""),
                     "purpose": CLK.purpose_of(periodic),
                     "to": str(getattr(periodic, "to", "") or ""),
                     "task_id": str(getattr(periodic, "task_id", "") or "")})
    by_task: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        tid = str(row.get("task_id") or "")
        if not tid:
            continue
        by_task.setdefault(tid, []).append(row)
    # "等待任意计时器返回"：业主 2026-10-27 第三条裁定那一格
    #   「如果已无事可做且无计时器，这意味着它交差了……直到它认为无事可做时，
    #     可启动计时器"等待任意计时器返回"」
    # 它是一份意图（`out/clock/wait_any.json` 一行），不是计时器：所以不进 `rows`
    # （那会让 `count` 把意图算成一条到点的东西），单列 `wait_any_by_task`。
    wait_any_checked, wait_any_reason = False, ""
    wait_any_by_task: dict[str, dict[str, Any]] = {}
    try:
        want_any = dict(CLK.read_wait_any(workspace))
    except Exception as exc:  # noqa: BLE001 —— 读不成是"没查成"
        wait_any_reason = f"等待意图账读不成（{type(exc).__name__}: {exc}）"
    else:
        wait_any_checked = bool(want_any.get("checked"))
        wait_any_reason = str(want_any.get("reason") or "")
        for raw in want_any.get("rows") or ():
            if not isinstance(raw, Mapping):
                continue
            tid = str(raw.get("task_id") or "")
            if not tid:
                continue
            wait_any_by_task[tid] = {"wait_id": str(raw.get("wait_id") or ""),
                                     "purpose": str(raw.get("purpose") or ""),
                                     "at": str(raw.get("at") or ""),
                                     "role": str(raw.get("role") or "")}
    # 交差账那一格也在这里读（`handoff_index` 是唯一读口）：它与时钟同一份读数交出去，
    # 于是同一次三态里"它挂着什么"与"它交没交差"看到的是同一个时刻的盘。
    hand = handoff_index(workspace)
    # 步进落痕那一格（停滞读数，`:step_beats` 是唯一读口）：同样与时钟同一份读数
    # 交出去。"它现在有没有事"的三个证据（挂着什么 / 交没交差 / 最近一步是什么时候）
    # 分成三次读，会让同一份三态看到三个时刻的盘。
    steps = step_beats(workspace)
    # "有几条挂在钟上"只量一次：`count` 与 `pending_total` 是同一个数（判据见下面那一行
    # 注释 —— 两个键说的是同一份 `rows`），改前这一个 `len(rows)` 写了两遍。
    pending_total = len(rows)
    out.update({"checked": True, "by_task": by_task, "rows": rows,
                "count": pending_total, "reason": "",
                # 兜底计时器单列一格（业主 2026-10-29）：三态里"只挂着它"就是静默。
                "lifeline_rows": lifeline_rows,
                "lifeline_count": len(lifeline_rows),
                "lifeline_by_task": {str(r.get("task_id") or ""): r
                                     for r in lifeline_rows
                                     if str(r.get("task_id") or "")},
                "wait_any_checked": wait_any_checked,
                "wait_any_by_task": wait_any_by_task,
                "wait_any_reason": wait_any_reason,
                "handoff_checked": bool(hand.get("checked")),
                "handoff_by_task": dict(hand.get("by_task") or {}),
                "handoff_reason": str(hand.get("reason") or ""),
                "stall_checked": bool(steps.get("checked")),
                "stall_by_task": dict(steps.get("by_task") or {}),
                "stall_reason": str(steps.get("reason") or ""),
                "stall_problems": list(steps.get("problems") or ()),
                "stall_threshold_sec": float(steps.get("threshold_sec")
                                             or STALLED_AFTER_SEC),
                "stall_now": str(steps.get("now") or ""),
                # 时钟上"还有东西没回来"的总数（含不属于任何台账号的那些：程序计时器
                # 常常 `task_id=""`）。`wait_any` 那一档用它回答"还有可等的吗"。
                "pending_total": pending_total})
    return out


def waiters_of(clock: Mapping[str, Any], task_ids: Iterable[str]) -> dict[str, Any]:
    """时钟读数里属于某个代理的那几条等待（`agent_state` 的第三个输入）。

    `task_ids` 是这个代理可能用过的每一个编号（它那一行 + 名册对照表里它接过的活）——
    同一个常驻子代理接过 N 件活就有 N 个编号，只认"当前那一件"会漏掉它在上一件活上
    挂的钟，而漏掉的表现正好是"待机"被判成"静默"。

    返回里除了 `rows`（挂在时钟上的那几条）还带三格给"等待任意计时器返回"那一档：

    - `wait_any`：这个台账号的意图（`{"checked", "requested", "wait_id", "purpose", "at"}`）。
      业主口径：「如果代理没在工作，在挂着"等任何一个计时器返回"，那就是待机」——
      这一格就是这个"挂着"的证据；
    - `wait_any_checked`：那本意图账查成没查成（`False` ⇒ `agent_state` 判 `unknown`，
      不许折成"它没要求过等"）；
    - `pending_total`：时钟上还有几条没回来（含不属于任何台账号的那些）。意图账还在
      而一条计时器都没有 ⇒ 业主说的"交差"那一档。

    另带一格 `handoff`：这个代理在交差账上的那一行（没交过 / 没读成 ⇒ `None`）。
    它不属于时钟，但属于同一份"它现在有没有事"的读数 —— `agent_state` 的三态要与
    `Conductor.handoffs_reading` 的口径不分家（父"记为静默"的那件事必须让销号门也认）。
    """
    want = [str(t or "") for t in task_ids]
    wait_any_checked = bool(clock.get("wait_any_checked", True))
    wait_any_reason = str(clock.get("wait_any_reason") or "")
    hand_checked = bool(clock.get("handoff_checked", False))
    stall_checked = bool(clock.get("stall_checked", False))
    by_any = dict(clock.get("wait_any_by_task") or {})
    hand_by_task = dict(clock.get("handoff_by_task") or {})
    stall_by_task = dict(clock.get("stall_by_task") or {})
    mine_any: dict[str, Any] = {}
    mine_hand: dict[str, Any] | None = None
    mine_stall: dict[str, Any] | None = None
    # 三格（等待意图 / 交差账 / 步进落痕）问的是同一个编号表上的"第一个命中的"：
    # 原先各扫一趟 `want`，现在合成一趟 —— 三格互不依赖，各自命中次序仍是 `want` 原序
    # ⇒ 每一格拿到的还是它单独扫时的那一条。逐格口径：
    #   · 等待意图：这个编号确实挂着"等任意计时器返回"时给（账上那一行 + 它的编号）；
    #   · 交差账：只在这个编号确实在账上时给，读不成 ⇒ `None`（= 不知道，不许折成"交过差"）；
    #   · 步进落痕（停滞读数）：只在这个编号确实有落痕时给，没有 / 读不成 ⇒ `None`。
    #     它不像交差账那样"缺省即否定"：一个老工作区里的行本来就没有这一格，把它读成
    #     "它没走过步"会让每一行都变成停滞 —— 没有证据就不下结论。
    for tid in want:
        if not mine_any:
            row = by_any.get(tid)
            if row:
                mine_any = dict(row)
                mine_any["task_id"] = tid
        if mine_hand is None and hand_checked:
            got = hand_by_task.get(tid)
            if isinstance(got, Mapping):
                mine_hand = dict(got)
        if mine_stall is None and stall_checked:
            got = stall_by_task.get(tid)
            if isinstance(got, Mapping):
                mine_stall = dict(got)
    base: dict[str, Any] = {
        "checked": bool(clock.get("checked")),
        "rows": [],
        "reason": "",
        "wait_any_checked": wait_any_checked,
        "wait_any_reason": wait_any_reason,
        "handoff_checked": hand_checked,
        "handoff": mine_hand,
        "pending_total": int(clock.get("pending_total") or 0),
        "wait_any": {"checked": wait_any_checked,
                     "requested": bool(mine_any),
                     "wait_id": str(mine_any.get("wait_id") or ""),
                     "purpose": str(mine_any.get("purpose") or ""),
                     "at": str(mine_any.get("at") or ""),
                     "reason": wait_any_reason},
    }
    base.update({"stall": mine_stall,
                 "stall_checked": stall_checked,
                 "stall_reason": str(clock.get("stall_reason") or ""),
                 "stall_threshold_sec": float(clock.get("stall_threshold_sec")
                                              or STALLED_AFTER_SEC)})
    if not clock.get("checked"):
        base["reason"] = str(clock.get("reason") or "")
        return base
    by_task = dict(clock.get("by_task") or {})
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for tid in want:
        for row in by_task.get(tid) or ():
            key = f"{row.get('kind') or ''}:{row.get('id') or ''}"
            if key in seen:
                continue
            seen.add(key)
            rows.append(dict(row))
    base.update({"checked": True, "rows": rows, "reason": ""})
    return base


def agent_state(*, row: Mapping[str, Any] | None,
                item: Mapping[str, Any] | None = None,
                wait: Mapping[str, Any] | None = None,
                waiting_for: Sequence[str] = (),
                ledger_checked: bool = True,
                roster_checked: bool = True) -> dict[str, Any]:
    """一个代理的三态 —— 全仓唯一实现（纯函数：不读盘、不取时钟、不判命题）。

    输入就是盘上的两份事实：`row` = 台账里它那一行（`None` = 台账里没有它），
    `item` = 名册里那一项（`None` = 不在任何名册里 / 这一层不读名册）；
    外加两条派生的读数：`wait` = 它挂在时钟上的等待（:func:`waiters_of`），
    `waiting_for` = 它名下还在活跃的直接子（"在等下级"）。

    ## 判定次序（前面的优先）
    ```
    ① 台账读不成                      ⇒ unknown
    ② 名册读不成                      ⇒ unknown
    ③ 台账里没有它那一行               ⇒ unknown
    ④ 时钟读不成                      ⇒ unknown（在飞 / 待机 / 静默三档都定不了）
    ⑤ 等待意图账读不成                 ⇒ unknown（"它是不是挂着等任意计时器"判不了）
    ⑥ 自己在跑（status ∈ UNFINISHED_STATUSES）且没挂在时钟上、也没交过差 ⇒ 在飞
    ⑦ 已销号（名册项 retired）         ⇒ 静默（销号即退场，不在活跃集合里）
    ⑦'已交差（交差账上有它那一行）      ⇒ 静默（交差即收工；它是第 ⑥ 步的反证，所以排在
                                        第 ⑦ 步之后、计时器那两步之前 —— 交过差又挂着钟
                                        的照样待机，它会醒过来）
    ⑧ 挂了"等任意计时器返回"（意图在账上、且时钟上确实还有东西没回来）⇒ 待机
    ⑨ 挂在时钟上 / 时钟上有到点的等待 / 名下有在飞的直接子 ⇒ 待机
    ⑩ 其余                            ⇒ 静默
    ```
    三态之间的次序是"在飞 → 待机 → 静默"（⑥ ⑧⑨ ⑩）；①②③④⑤ 是"判不了"的闸，
    ⑦ 是"已退场"的闸，两者都排在它该压住的那一档之前。

    ## 为什么 ⑤ 要减掉"挂在时钟上"
    挂机的那一趟循环还活着，台账行也还是 `running`（`agent_loop._park_gate` 只是让这一拍
    不调模型、睡一拍），所以"有 running 的任务"本身分不开"在跑回合"与"挂在钟上等"。
    不减掉它，"待机"就只剩"已收工但留了个钟"那一小撮，挂机的代理一个都读不出来。

    ## 为什么"名下有在飞的直接子"也算待机
    有活跃下级的代理自己按"活跃"算，有『等』这个动作也算活跃。挂机是"等"的机制
    （`wait_for` 那一条钟），而这一格是同一个"等"在台账侧的读数：机制那一面读不到时
    （夹具没排钟、或它用别的方式在等），这一面仍然认得出来。两面都不许折成"静默"。

    ## ⑧「等任意计时器返回」也算待机
    ```
    「如果代理没在工作，在挂着"等任何一个计时器返回"，那就是待机」
    ```
    这一档与 ⑨ 的差别正是它存在的理由：⑨ 认的是"这个名字下挂着具体的钟"，而有一整类
    钟不挂在任何名字下 —— 程序计时器常常 `task_id=""`、`to="self"`
    （`clock.start_program` 由框架自己调，调用点不传台账号）。只按名字归属判，
    "它挂在等任意计时器上"会读成"它已收工、静默"，而父侧据此就能把它销号（销号不可逆）。
    所以：意图在账上 + 时钟上确实还有东西没回来 ⇒ 待机，理由串点名"等任意计时器返回"。

    ## ⑩ 的第二个理由：要求过等、而没有可等的东西
    要求过等而一条计时器都没有 ⇒ 它交差了。这一档判静默，但理由必须写清"它要求过等、
    而一条计时器都没有" —— 否则"要求过等"与"从来没要求"在读数上是同一格。

    ## 返回
    `{"state", "state_label", "reason", "task_id", "status", "self_busy", "parked",
    "retired", "waiting_only", "waiters", "waiting_for", "wait_any",
    "stalled", "stalled_sec", "stalled_reason"}`。
    `reason` 是"为什么判成这一格"的人话（`unknown` 时必有，其余可空）。

    ## 停滞（`stalled` / `stalled_sec` / `stalled_reason`）—— 只加一格，不改三态
    `status=running` 只说明"台账那一行还没落终态"，它不等于"它现在在跑"：一个只在台账上
    翻着 `running`、其余时间既没在跑也没交差的代理，页面会一直显示"在飞"。所以
    `flying` 那一档另带一格：最近一步落在
    `wait["stall"]` 上（`step_beats` 的读数），若距现在超过
    `STALLED_AFTER_SEC` ⇒ `stalled=True` + `stalled_sec` + 一句含最后一步时刻的理由。

    三条都不许越界：
    - 它不改 `state`：停滞的任务照样是 `flying`（"疑似"不是"查过了它是死的"）；
    - 它不折成静默：静默说的是"只挂着兜底计时器（已收工、没别的事）"，停滞说的是"它这一拍
      没动静"—— 折平会让它可以被销号，而销号不可逆；
    - 只有 `flying` 这一档给 `stalled`：待机（挂着钟）与静默本来就不是"该在跑而没跑"。
    `stalled` 恒有值（不是"有这一格才算"），`stalled_sec` 与 `stalled_reason` 在
    `stalled=False` 时是 `None` / 空串 —— 前端据此读一格就够。
    """
    status = str((row or {}).get("status") or "")
    tid = str((row or {}).get("task_id") or "")
    retired = bool((item or {}).get("retired"))
    clock = dict(wait or {"checked": False, "rows": [],
                          "reason": "没读时钟 ⇒ 在飞与待机分不开"})
    rows = [dict(x) for x in (clock.get("rows") or ())]
    parked = any(str(x.get("park_state") or "") == "parked" for x in rows)
    self_busy = status in UNFINISHED_STATUSES
    # 交差（`out/clock/handoffs.json` 有它那一行）：交差是静默的盘上证据
    # （"无事可做且无计时器 ⇒ 它交差了 ⇒ 父把它记为静默子代理"）。
    # 它是"自己在跑"的反证，所以只压第 ⑥ 步；计时器（⑧⑨）仍然优先 —— 交过差又挂着钟的
    # 那一档照样是待机（它会醒过来，不许销）。读不成（`handoff_checked=False`）⇒
    # 按"不知道"读成没交差 ⇒ 落在"在飞"（保守方向 = 不销）。
    raw_hand = wait.get("handoff") if isinstance(wait, Mapping) else None
    handed_off = bool(isinstance(raw_hand, Mapping) and raw_hand)
    hand = dict(raw_hand) if isinstance(raw_hand, Mapping) else {}
    # 等待意图（`out/clock/wait_any.json`）那一格。缺省 `checked=True`（调用方
    # 不给这一格 ⇒ 按"没有意图"读，不许把"这一层没读它"错判成 unknown）。
    raw_any = clock.get("wait_any")
    wa: dict[str, Any] = (dict(raw_any) if isinstance(raw_any, Mapping)
                          else {"requested": False, "wait_id": "", "purpose": "", "at": ""})
    wa.setdefault("checked", bool(clock.get("wait_any_checked", True)))
    wa.setdefault("reason", str(clock.get("wait_any_reason") or ""))
    wait_any_checked = bool(wa.get("checked"))
    wait_any_requested = bool(wa.get("requested"))
    # "时钟上还有东西没回来"的总数：含不属于任何台账号的那些（程序计时器）。
    pending_total = clock.get("pending_total")
    still_pending = (bool(rows) if pending_total is None
                     else int(pending_total or 0) > 0)
    # 停滞那一格（`out/steps/<台账号>.json`）：纯读数，输入是 `wait["stall"]`，
    # 这一层不读盘、不取时钟（与"纯函数"同一条纪律）。
    raw_stall = clock.get("stall")
    stall = dict(raw_stall) if isinstance(raw_stall, Mapping) else {}
    stall_checked = bool(clock.get("stall_checked", False))
    try:
        stall_sec = float(stall.get("sec")) if stall.get("sec") is not None else None
    except (TypeError, ValueError):
        stall_sec = None
    try:
        stall_threshold = float(clock.get("stall_threshold_sec") or STALLED_AFTER_SEC)
    except (TypeError, ValueError):
        stall_threshold = STALLED_AFTER_SEC
    # 有落痕、读得成、而且真的超了阈值 ⇒ 这一档"该在跑而没动静"。
    stall_hit = bool(stall_checked and stall_sec is not None and stall_sec >= stall_threshold)
    out: dict[str, Any] = {"state": AGENT_STATE_UNKNOWN, "state_label": "",
                          "reason": "", "task_id": tid, "status": status,
                          "self_busy": bool(self_busy), "parked": bool(parked),
                          "retired": retired, "waiting_only": False,
                          "handed_off": handed_off,
                          "handoff": hand,
                          "waiters": rows, "waiting_for": [str(x) for x in waiting_for],
                          "wait_any": wa,
                          "stalled": False, "stalled_sec": None, "stalled_reason": "",
                          # 静默要再分两档：可叫醒（号还在）与不可叫醒（已销号）——
                          # 静默是"工作完成了、彻底休息，但随叫随到"，销号是"彻底没有了"。
                          # 这一格就是那个区分，静默与已销号不许折平。
                          "wakeable": False}

    def _stall_text() -> str:
        """停滞那一句人话（必须含最后一步的时刻与"已经多少分钟没有新步"）。"""
        mins = int((stall_sec or 0.0) // 60)
        step_no = stall.get("step")
        where = f"第 {int(step_no)} 步" if isinstance(step_no, int) else "那一步"
        return (f"最近一步在 {_hhmm(stall.get('at'))}（{where}），"
                f"已经 {mins} 分钟没有新步（阈值 {int(stall_threshold // 60)} 分钟）"
                " ⇒ 疑似停滞：台账那一行仍是 running，但这一格不改三态")

    def settle(state: str, reason: str = "") -> dict[str, Any]:
        out["state"] = state
        out["state_label"] = AGENT_STATE_LABELS.get(state, "")
        out["reason"] = reason
        out["waiting_only"] = bool(state == AGENT_STATE_STANDBY and not self_busy)
        # 停滞只在"该在跑而没动静"那一档给：在飞 + 有落痕 + 超阈值。
        out["stalled"] = bool(state == AGENT_STATE_FLYING and stall_hit)
        out["stalled_sec"] = round(float(stall_sec), 3) if out["stalled"] else None
        out["stalled_reason"] = _stall_text() if out["stalled"] else ""
        # 「随叫随到」的机器形态：静默 + 未销号 + 台账行已终态 ⇒ 可叫醒。
        # 已销号那一档永远是 False（销号是彻底没有了）。
        out["wakeable"] = bool(
            state == AGENT_STATE_SILENT
            and not retired
            and bool(status)
            and status not in UNFINISHED_STATUSES)
        return out

    if not ledger_checked:
        return settle(AGENT_STATE_UNKNOWN, "台账读不成 ⇒ 它是哪一态判不了")
    if not roster_checked:
        return settle(AGENT_STATE_UNKNOWN,
                      "名册读不成 ⇒ 它有没有销号判不了（销号即退场，静默与退场分不开）")
    if row is None:
        return settle(AGENT_STATE_UNKNOWN,
                      "台账里没有它那一行 ⇒ 它有没有在跑 / 收工 判不了")
    if not clock.get("checked"):
        return settle(AGENT_STATE_UNKNOWN,
                      f"时钟读不成（{clock.get('reason') or '没查成'}）⇒ "
                      "它是在飞、待机还是静默分不开")
    if not wait_any_checked:
        return settle(AGENT_STATE_UNKNOWN,
                      "等待意图账读不成"
                      f"（{wa.get('reason') or '没查成'}）⇒ 它是不是挂着"
                      "等任意计时器返回判不了（这一格不许折成静默）")
    if self_busy and not parked and not handed_off:
        return settle(AGENT_STATE_FLYING, f"它自己在跑（status={status}）")
    if retired:
        return settle(AGENT_STATE_SILENT,
                      "已销号 ⇒ 退场（销号即退场，不在活跃集合里）")
    if wait_any_requested:
        # 有目的的等待：挂着"等任意计时器返回"是在等一个它自己点名的东西回来 ——
        # 那是待机，不是静默。静默只留给"只挂着兜底计时器"。
        # 与兜底表的分工：兜底表由框架维护、代理无感、不进 `rows`（见 clock_waiters），
        # 所以走到这里说明它自己要求过等，"时钟上一条都没有"不再是交差的证据。
        marks = "、".join(sorted({str(x.get("id") or "") for x in rows}))
        where = str(wa.get("wait_id") or "")
        detail = f"，也挂着 {marks}" if marks else ""
        return settle(
            AGENT_STATE_STANDBY,
            (f"它挂着等任意计时器返回（wait_any={where or '在账上'}{detail}；"
             "这是它自己要求的等，属于待机）"))
    if parked:
        marks = "、".join(sorted({str(x.get("id") or "") for x in rows
                                  if str(x.get("park_state") or "") == "parked"}))
        return settle(AGENT_STATE_STANDBY, f"它挂在时钟上等（{marks or 'parked'}）")
    if rows:
        marks = "、".join(sorted({str(x.get("id") or "") for x in rows}))
        return settle(AGENT_STATE_STANDBY, f"时钟上还有等待没到点（{marks}）")
    if out["waiting_for"]:
        return settle(AGENT_STATE_STANDBY,
                      "它自己没在跑，是在等 " + "、".join(out["waiting_for"]) + "（活跃）")
    if handed_off:
        # 交差是"静默"的盘上证据：它已经把这一趟交出去了。
        # 这一档只为第 ⑥ 步翻案，所以走到这里说明它没挂着任何计时器、名下也没有
        # 活跃子代理（⑧⑨ 先判过）—— 交过差、又还在 `running` 行上的那一档正是
        # "父已经把它记为静默、而台账那一行还没落终态"（异步 / 可抢占派活、或上一次
        # 收尾没走完），它占着的扇出名额只能靠销号腾出来。
        return settle(AGENT_STATE_SILENT,
                      "它已交差（交差账 "
                      f"{str(hand.get('handoff_id') or '有它那一行')}"
                      f"，{str(hand.get('at') or '时间没读到')}）⇒ 无事可做、无计时器 "
                      "⇒ 静默（业主 2026-10-27：父代理把它记为静默子代理）")
    if wait_any_requested:
        # 要求过等、而时钟上一条都没有 ⇒ 业主那句"这意味着它交差了"。
        # 仍是静默，但理由必须点名这一档：不点名就与"从来没要求过等"折平了。
        return settle(AGENT_STATE_SILENT,
                      "它要求过等任意计时器返回，而时钟上一条计时器都没有 ⇒ "
                      "无事可做、交差（静默）")
    return settle(AGENT_STATE_SILENT, "它已收工：没有任务、也没有任何计时器")


def agent_states(rows: Sequence[Mapping[str, Any]], *,
                 clock: Mapping[str, Any] | None = None,
                 retired: Mapping[str, bool] | None = None,
                 roster_checked: bool = True,
                 ledger_checked: bool = True) -> dict[str, dict[str, Any]]:
    """一组代理行的三态（按 `parent_task_id` 成树，自底向上算，含"在等下级"）。

    这就是 :func:`agent_state` 的唯一调用点（`Conductor.activity_snapshot`、
    `Secretary.child_counts` / `roster_view`、`webui.readers.roster_face` 都从这里拿）——
    判定逻辑只有上面那一份，这里只负责"谁是谁的子"与先后次序。

    `retired` 是 `{代理编号: 是否已销号}`（名册那一侧的事实；不给 ⇒ 一律 False）；
    `roster_checked=False` ⇒ 每一格都是 `unknown`（销号没销号判不了）。
    """
    clock = dict(clock or {"checked": False, "rows": [],
                           "reason": "没读时钟 ⇒ 在飞与待机分不开"})
    retired_of = dict(retired or {})
    rows_by_id: dict[str, dict[str, Any]] = {}
    kids: dict[str, list[str]] = {}
    for raw in rows:
        row = dict(raw)
        tid = str(row.get("task_id") or "")
        if not tid:
            continue
        rows_by_id[tid] = row
    for tid, row in rows_by_id.items():
        pid = str(row.get("parent_task_id") or "")
        if pid:
            kids.setdefault(pid, []).append(tid)
    order: list[str] = []
    seen: set[str] = set()
    for start in sorted(rows_by_id):
        if start in seen:
            continue
        stack: list[tuple[str, bool]] = [(start, False)]
        onstack: set[str] = {start}
        while stack:
            tid, done = stack.pop()
            if done:
                onstack.discard(tid)
                order.append(tid)
                continue
            if tid in seen:
                onstack.discard(tid)
                continue
            seen.add(tid)
            stack.append((tid, True))
            for kid in kids.get(tid, ()):
                if kid in seen or kid in onstack:
                    continue
                stack.append((kid, False))
                onstack.add(kid)
    out: dict[str, dict[str, Any]] = {}
    for tid in order:
        row = rows_by_id[tid]
        item = ({"retired": bool(retired_of.get(tid))} if tid in retired_of else None)
        wait = waiters_of(clock, [tid])
        waiting_for = [k for k in kids.get(tid, ())
                       if str((out.get(k) or {}).get("state") or "") in ACTIVE_AGENT_STATES]
        out[tid] = agent_state(row=row, item=item, wait=wait,
                               waiting_for=waiting_for,
                               ledger_checked=ledger_checked,
                               roster_checked=roster_checked)
    return out


def _agent_label(tid: str, names: Mapping[str, str] | None = None) -> str:
    """一个人话标签：有名字就写「名字（编号）」，没有就写编号（都空 ⇒ 明确的"没有编号"）。

    为什么名字与编号都写：名字是父与子之间的指称（`D1`），编号是台账里能直接查的那一格。
    只写名字会让"点名"在台账侧核不起来，只写编号会让父对不上名册。
    """
    got = str((names or {}).get(tid) or "")
    if got and got != tid:
        return f"{got}（{tid}）"
    return tid or "（没有编号）"


def retire_question_text(*, name: str, task_id: str, role: str) -> str:
    """"要不要销号这个已静默的子代理"那一句问询的正文（唯一实现，逐字可判）。

    业主 2026-10-26（同一批裁定的第三句，逐字）：

    ```
    「M 以及其它父代理都没有销号无用的静默子代理的意识，
      这个可以在子代理收工交付时系统自动问询是否销号」
    ```

    所以正文要同时给出三件事：它是谁（名册名 + 绝对编号 + 角色）、它现在是什么状态
    （已静默：已收工，只在等与它有关的消息或委托）、以及下一个动作该怎么写。最后那句"不销也行"是
    业主明确要的：问询不是催办，销号仍然只有父能决定（框架绝不代做）。

    `task_id=` 与 `child_name=` 两个写法都写出来，因为工具真正收的是这两格
    （见 `conductor_tools.conductor_retire_child` 的形参）。写成一个不存在的参数名
    （例如 `target=`）会让父照着抄一次、吃到一次参数校验失败 —— 一条问询的措辞
    不该让下一个动作当场失败。
    """
    shown = str(name or "").strip()
    tid = str(task_id or "").strip()
    who = f"{shown}（{tid}，角色 {str(role or '').strip() or '未读到'}）" if shown else (
        f"（名册上没有名字，绝对编号 {tid}，角色 {str(role or '').strip() or '未读到'}）")
    if shown:
        call = (f"`conductor.retire_child(child_name={shown})`"
                f"（等价写法 `conductor.retire_child(task_id={tid})`）")
    else:
        call = f"`conductor.retire_child(task_id={tid})`"
    return (f"子代理 {who} 已静默（已收工，只在等与它有关的消息或委托） ⇒ 要销号它吗？ {call}；"
            "不销也行，它会一直显示在名册上。")


def retire_blocking(reading: Mapping[str, Any], *,
                    names: Mapping[str, str] | None = None) -> list[dict[str, str]]:
    """把一份三态读数翻成"为什么还不能销号"的逐条清单（全仓唯一实现）。

    ## 为什么销号要读三态，而不是只读"它在不在跑"
    业主 2026-10-26 裁定逐字：「销号可以也只可针对静默子代理」。静默 = 只挂着兜底计时器（已收工、没别的事）；旧定义是：无工作 ∧
    无任何计时器 ∧ 无活跃子代理。只读 `status` 会漏掉整整一档：一个已经 `done`、
    时钟上却还挂着计时器的子代理会在那一条读数里与"收工了"长得一模一样，而它
    还会醒过来 —— 销掉它等于把一个即将发生的动作从名册上摘掉（销号不可逆，名字
    永久不复用）。

    ## 返回
    `[{"kind", "detail"}]`，`kind` 只有三档：
    - `working`：它还在干活（自己在跑，或是这一支里真正在跑的节点）⇒ 先让它收工；
    - `waiting`：它还会醒过来（挂着计时器 / 在等活跃子代理）⇒ 让那件事先发生，或显式让它停；
    - `unknown`：读不到它是不是静默 ⇒ fail-closed，重读一次再决定。
    静默 ⇒ 空表。`detail` 是逐条点名的人话（计时器的编号 / 目的 / 到点时刻、
    它在等的子代理是哪一个），`names` 是"编号 → 名册名"的对照（不给就用编号）。

    ## 为什么这里不判"能不能销"
    这里只给理由清单；"拒了"这件事由调用方按三态决定 —— 待机里"真正在跑的在下级"
    那一小档交给子树活跃闸去说（那份拒信会逐个点名整支的活跃节点），而 `unknown`
    一律拒绝。把工作流塞进这个函数，会让同一份读数在两个调用点说出两句不同的话。
    """
    def label_of(tid: str) -> str:
        return _agent_label(tid, names)

    state = str(reading.get("state") or AGENT_STATE_UNKNOWN)
    out: list[dict[str, str]] = []
    if state == AGENT_STATE_FLYING:
        status = str(reading.get("status") or "unknown")
        detail = (f"它还在干活（status={status}），"
                  "销号等于把它手上的活扔掉 —— 先让它收工")
        # 停滞是读数，不是许可（业主 2026-10-26：「销号可以也只可针对静默子代理」）：
        # 一个停了 79 分钟的子代理仍然不是静默的（静默是"只挂着兜底计时器（已收工、没别的事）"，
        # 而它工作没做完）。这一句要写在拒信里，否则"它已经不动了"会被读成"可以销了"。
        if reading.get("stalled"):
            mins = int(float(reading.get("stalled_sec") or 0.0) // 60)
            detail += (f"；不过它已经 {mins} 分钟没有新步（疑似停滞）—— "
                       "停滞不等于静默，销号仍然不许")
        out.append({"kind": "working", "detail": detail})
        return out
    if state == AGENT_STATE_STANDBY:
        for waiter in reading.get("waiters") or ():
            w = dict(waiter)
            purpose = str(w.get("purpose") or "").strip() or "（没写目的）"
            at = str(w.get("at") or "").strip() or "（没读到到点时刻）"
            out.append({"kind": "waiting",
                        "detail": (f"{w.get('id') or '（没有编号）'}"
                                   f"（{w.get('kind') or '未知种类'}）：{purpose}，到点 {at}")})
        # "等任意计时器返回"那一档：它名下可能一条钟都没有（程序计时器常常不挂名字），
        # 于是上面那一圈会一条都不吐 —— 少了这一条，一个挂着等任意表的待机代理
        # 会在销号闸上看成"没人拦"，而销号不可逆。
        wa = dict(reading.get("wait_any") or {})
        if wa.get("requested"):
            out.append({"kind": "waiting",
                        "detail": (f"它挂着等任意计时器返回"
                                   f"（wait_any={wa.get('wait_id') or '在账上'}）："
                                   "任意一条回来它还会醒 ⇒ 让那件事先发生，或显式让它停")})
        waiting_for = [str(x) for x in (reading.get("waiting_for") or ())]
        for kid in waiting_for:
            out.append({"kind": "waiting",
                        "detail": f"它在等子代理 {label_of(kid)}（那个子还活跃），它还会醒过来"})
        for busy in [str(x) for x in (reading.get("busy_roots") or ())]:
            if busy in waiting_for:
                continue
            out.append({"kind": "working",
                        "detail": f"这一支里 {label_of(busy)} 还在干活"})
        return out
    if state == AGENT_STATE_SILENT:
        return out
    why = (str(reading.get("state_reason") or "").strip()
           or str(reading.get("reason") or "").strip() or "读数里没给理由")
    out.append({"kind": "unknown", "detail": f"读不到它是不是静默（{why}）"})
    return out


def retire_refusal(reading: Mapping[str, Any], *, tid: str = "", name: str = "",
                   names: Mapping[str, str] | None = None) -> dict[str, Any]:
    """一条"目标不是静默"的拒信（`retire_blocking` 的唯一消费者：工具与秘书共用）。

    返回 `{"code","state","state_label","blocking","why","missing"}`。调用方只在
    `silent` 为假时用它；`code` 恒是 `RETIRE_REFUSAL_TARGET_NOT_SILENT`（不是空串：
    这条函数的存在前提就是"这一格不能销"）。

    ## 三档拒信各自必须说清的那一件事
    - 在飞：它还在干活（status=…），销号等于把它手上的活扔掉 —— 先让它收工；
      外加"销号 ≠ 停止"，因为父最容易把这两件事当成一件事；
    - 待机：挂着几条计时器（逐条：编号 / 种类 / 目的 / 到点时刻），它还会醒过来 ——
      要么让那些计时器等的事先发生，要么显式让它停（停止 ≠ 销号）；
    - 未读到：读不到它是不是静默 ⇒ 不许销（fail-closed）。
    待机还有一小档是"它在等活跃子代理"：那一条拒信点名是哪个子让它非静默，
    并把"级联永远是先子后父"写出来（业主同一批裁定给的不变量：有活跃子代理 ⇒
    必存在一条等待该子代理的计时器 ⇒ 父非静默 ⇒ 父不许销）。
    """
    lead = (f"{name}（{tid}）" if name and tid else (name or tid or "这个子代理"))
    label = str(reading.get("state_label") or "")
    if not label:
        label = AGENT_STATE_LABELS.get(str(reading.get("state") or ""), "") or "判不了"
    blocking = retire_blocking(reading, names=names)
    state = str(reading.get("state") or AGENT_STATE_UNKNOWN)
    waiters = [dict(x) for x in (reading.get("waiters") or ())]
    waiting_for = [str(x) for x in (reading.get("waiting_for") or ())]
    busy = [str(x) for x in (reading.get("busy_roots") or ())]
    missing: list[str] = []
    if state == AGENT_STATE_FLYING:
        why = (f"{lead}现在是{label}：{blocking[0]['detail']}；销号只针对静默子代理。"
               "销号 ≠ 停止：要它此刻停下来用停止/叫停，不是销号")
        missing = [f"{tid or lead} 还在跑"]
    elif state == AGENT_STATE_UNKNOWN:
        detail = next((b["detail"] for b in blocking if b.get("kind") == "unknown"),
                      "读不到它是不是静默")
        why = (f"{lead}现在是{label}：{detail} —— 读不到就不许销（fail-closed）；"
               "销号只针对静默子代理")
        missing = [f"读不到 {tid or lead} 是不是静默"]
    elif state == AGENT_STATE_STANDBY:
        parts: list[str] = []
        if waiters:
            listed = "；".join(f"{w.get('id') or '（没有编号）'}（{w.get('kind') or '未知种类'}）："
                               f"{str(w.get('purpose') or '').strip() or '（没写目的）'}，"
                               f"到点 {str(w.get('at') or '').strip() or '（没读到到点时刻）'}"
                               for w in waiters)
            parts.append(f"它挂着 {len(waiters)} 条计时器（{listed}），它还会醒过来 —— "
                         "要么让那些计时器等的事先发生，要么显式让它停（停止≠销号）")
            missing.extend(f"计时器 {w.get('id') or '（没有编号）'} 到点 "
                           f"{str(w.get('at') or '').strip() or '（没读到）'}" for w in waiters)
        if waiting_for:
            named = "、".join(_agent_label(k, names) for k in waiting_for)
            parts.append(f"它名下有 {len(waiting_for)} 个还活跃的子代理（{named}），"
                         "它在等它们 —— 先让那些子代理收工、或者先销它们"
                         "（级联永远是先子后父）")
            missing.extend(f"{_agent_label(k, names)} 还活跃" for k in waiting_for)
        for one in busy:
            if one in waiting_for:
                continue
            # `_agent_label` 是纯函数（只读 `names`），同一格句子与拒信各要一次。
            who = _agent_label(one, names)
            parts.append(f"这一支里 {who} 还在干活")
            missing.append(f"{who} 还在干活")
        body = "；".join(parts) or "它在待机（还在等）"
        why = f"{lead}现在是{label}：{body}；销号只针对静默子代理"
    else:
        why = (f"{lead}现在是{label}：{'; '.join(b['detail'] for b in blocking)}；"
               "销号只针对静默子代理")
    return {"code": RETIRE_REFUSAL_TARGET_NOT_SILENT, "state": state,
            "state_label": label, "blocking": blocking, "why": why,
            "missing": missing}


# ---------------------------------------------------------------- 销号前的程序检测（G2）
#
# 业主 2026-10-26 那一批的原话有两句：「重点完善子代理杀自己发出去的程序进程的工具」
# 「以及注销前检测的能力」。昨晚的真机读数是有十五个野 python 进程在跑，谁起的、谁该停、
# 销号前有没有人查过 —— 三件事都读不出来。下面这三格补的就是那个读数：
#
#   `programs_reading`       工作区里的程序进程读数（有主 / 无主 / 账与进程对不上三类）
#   `program_span_text`      一条程序读数的人话（拒信与读数共用这一处措辞）
#   `programs_refusal`       一条"这一支还有程序在跑"的拒信（秘书与工具共用，一处措辞）
#
# 为什么读侧只有一处：销号门（工具与 `Secretary.retire` 两条路）、收工门
# （`retire_integrity` / `_final_gate_reading`）与 M 的巡查（`conductor.state`）读的是
# 同一份盘。各写一份的后果不是报错，而是同一台程序在销号门上"在跑"、在收工门上说
# "没有在跑的程序" —— 三态纪律里最贵的那种折叠。


#: pid 复用判定的读数：这个 pid 现在挂着的进程映像名（小写、不含 .exe）。
#:
#: 为什么要它（业主 2026-10-28 两条裁定合起来）：口径是「收工必须所有人停、所有进程停」，
#: 闸不许放宽；而 Windows 的 pid 会被复用 —— 账上早已 `outcome=exited` 的那台脚本退了之
#: 后，这个号可能属于另一台新进程（真机 `projects/paper-rewrite-78c`：`extract_pdf.py`
#: 1.2 秒就 exit_code=0，读数却 `alive=true`）；同时业主又明令「不能为了着急收工强停」。
#: 所以只能把"活着"这个读数测准。
#:
#: 为什么用映像名而不是创建时刻：创建时刻要与计时器的 `at` 比，而 `at` 可能来自假时钟
#: （判据里就这么用）⇒ 一比就把活进程判成复用号、把闸放松（2026-10-28 全量真机踩到）。
#: 映像名与时钟无关：复用号上挂的通常是另一台程序。
def _process_image_name(pid: Any) -> str | None:
    """这个 pid 现在挂着的进程映像名（小写、去 .exe）；非 Windows / 读不到 ⇒ None。"""
    import os

    if os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        if not handle:
            return None
        try:
            size = wintypes.DWORD(1024)
            buf = ctypes.create_unicode_buffer(1024)
            ok = k32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size))
            if not ok or not buf.value:
                return None
            name = os.path.basename(buf.value).strip().lower()
            if name.endswith(".exe"):
                name = name[:-4]
            return name or None
        finally:
            k32.CloseHandle(handle)
    except Exception:  # noqa: BLE001 —— 读不到就是"没读到"
        return None


def _program_alive(pid: Any) -> bool:
    """这个 pid 还活着吗（复用 `stopctl.alive`，不在本文件另写一份探活）。

    为什么必须复用：探活在 Windows 上有两个坑，`stopctl.alive` 的 docstring 逐字记着
    （`tasklist` 在沙箱里拿不到读数；`os.kill(pid, 0)` 在 Windows 上会真的杀进程）。
    探不成（权限 / 平台）⇒ 按"不活着"读（那是 `stopctl.alive` 的既有口径），
    但那一行会在读数的 `no_pid` / `alive` 两格如实标出来 —— 这一格不许编一个"活着"。
    """
    try:
        from . import stopctl

        return bool(stopctl.alive(int(pid)))
    except Exception:  # noqa: BLE001 —— 探不了就按"不活着"读（读数里那一格仍会说）
        return False


def _program_elapsed(row: Mapping[str, Any], now_dt: Any) -> float | None:
    """这个程序已经跑了多少秒（账上给了 `elapsed_sec` 就用它，否则按登记的 `at` 现算）。"""
    given = row.get("elapsed_sec")
    if given is not None:
        try:
            return max(0.0, float(given))
        except (TypeError, ValueError):
            # 账上那一格不是数（旧行 / 手写夹具）⇒ 退回按登记的 `at` 现算，
            # 不许折成 0 秒（"跑了 0 秒"与"跑了多久没读到"是两件事）。
            pass
    return _since_sec(row.get("at"), now_dt)


def programs_reading(workspace: str | Path, *, task_ids: Iterable[str] | None = None,
                     now_dt: Any = None, blocked_reason: str = "") -> dict[str, Any]:
    """这个工作区里的程序进程读数（销号门 / 收工门 / M 的巡查共用这一份，只读）。

    ## 它回答什么
    "此刻盘上还有没有程序在跑、它是谁的"。这是昨晚那十五个野 python 进程缺的那一格：
    有程序在跑这件事今天只有 `clock.programs()` 的一份计时器流水，而流水不说"它属于
    哪一支、它是不是已经收口了却还在跑"。

    ## 三态（与时钟簿记同一条纪律）
    `clock.programs()` 读不成 ⇒ `checked=False` + `reason`，`running` 与 `unowned` 都是
    空表。它不等于"没有程序在跑"：调用方据此一律不销（fail-closed），拒信必须说"没查成"。

    ## 两档"在跑"的账上证据（缺一档就会留下昨晚那种进程）
    - `state == "pending"`：账上说它还在跑（`start_program` 登记了、`finish_program`
      还没收口）。这一档不看 pid：pid 可能还没补进来（`attach_program_pid` 是旁路，
      补不上不拦程序），而"账上说在跑"本身就是不许销的理由。
    - `state != "pending"` 而 pid 还活着：账说收口了、进程还在跑。超时 / 被杀的那一档
      最常出这个形态（宿主进程退了，它生的子进程还在）—— 昨晚那一类"没人能停"的进程
      正是这样留在盘上的。探活走 `_program_alive`（`stopctl.alive` 的唯一实现）。

    ## 归属（"按台账号归属"那一格）
    程序计时器那一行有 `task_id`（`clock.start_program` 的形参），它就是归属。`task_ids`
    给了 ⇒ 只挑落在里面的那几条（这一支的程序）；没给 ⇒ 全部有主的都算。
    `task_id` 空的是无主程序（`unowned`）：框架自己的八个 `program_span` 调用点今天
    一个都不传台账号，所以"无主"是常态不是异常 —— 它进读数、不当门（业主第 ③ 条：
    无主进程读数是给 M 的巡查用的）。

    ## 返回
    `{"checked","reason","rows","running","running_count","unowned","unowned_count",
    "orphans","orphan_count","no_pid","scope"}`：
    - `rows`：全部程序计时器行（原样 ＋ 派生三格 `live` / `alive` / `owner`；
      `elapsed_sec` 换成本次现算的值 —— 账上那一格是收口时才写的）；
    - `running`：这一支名下还在跑的那几条（`task_id` / `timer_id` / `program` / `pid` /
      `state` / `alive` / `elapsed_sec`）。它们有主：父能叫住它（先停它、或等它退出）；
    - `unowned`：没有台账号、且还在跑的那几条。它们也是"在跑"，但与上面那一档不是
      同一件事：旧账没记归属（`program_span` 那些调用点今天一个都不传台账号），
      所以没有任何一支认领它 —— 只有 M 能处置。两档都在跑，处置不同，所以分开列，
      不折成一档（折起来的后果：M 读到"还有程序在跑"却不知道该找谁去停）；
    - `orphans`：两类"账与进程对不上"的 —— `no_timer`（起了却一条计时器都没有：
      `clock.programs()["unbooked"]`，进程内读数）与 `finished_but_alive`（账已收口、
      pid 还活着）。业主第 ③ 条点名的就是这两类，它们只进读数、不进任何闸；
    - `no_pid`：`state == "pending"` 而 pid 没读到的那几条（账上在跑、探活没有对象）。

    `blocked_reason`：调用方另有一步读不成时（例如子树读不成）用它把这一格整份判成
    "没查成"—— 形状仍由本函数给，调用方不另写一份空表（一份形状两个主人，迟早漂开）。

    ## 代价
    有 pid 的那几行各做一次探活（`stopctl.alive` 是一次 `OpenProcess` +
    `WaitForSingleObject` + `CloseHandle`，本机微秒级）。巡查与收工门会反复读这一格，
    所以刻意不做逐行重试、也不缓存："这一格回答的是此刻"，缓存会让一台刚起来的程序
    在下一次读数里仍然是"没有在跑"。几百行的账上这一点代价小于一次台账读盘。
    """
    scope: set[str] | None = None
    if task_ids is not None:
        scope = {str(t) for t in task_ids if str(t)}
    out: dict[str, Any] = {
        "checked": False, "reason": "", "rows": [],
        "running": [], "running_count": 0,
        "unowned": [], "unowned_count": 0,
        "orphans": {"no_timer": [], "finished_but_alive": [], "pid_reused": []},
        "orphan_count": 0, "no_pid": [],
        "scope": sorted(scope) if scope is not None else [],
    }
    if str(blocked_reason or "").strip():
        out["reason"] = str(blocked_reason).strip()
        return out
    try:
        got = CLK.programs(workspace)
    except Exception as exc:  # noqa: BLE001 —— 读不成是"没查成"
        out["reason"] = f"程序计时器读不成：{type(exc).__name__}: {exc}"
        return out
    if not isinstance(got, Mapping):
        out["reason"] = "程序计时器的读数不是对象 ⇒ 没查成"
        return out
    if not got.get("checked"):
        out["reason"] = str(got.get("reason") or "程序计时器没读成（这一格没查成）")
        return out
    if now_dt is None:
        reading = CLK.now()
        now_dt = reading.wall
    rows: list[dict[str, Any]] = []
    for raw in got.get("rows") or ():
        if not isinstance(raw, Mapping):
            continue
        row = dict(raw)
        pid = row.get("pid")
        state = str(row.get("state") or "")
        alive = bool(_program_alive(pid)) if pid is not None else False
        # ---- pid 复用（2026-10-28）：`alive` 只认"那台进程确实是它"。
        # 口径仍是「所有进程停才许收工」—— 这一格不放松闸，只把"活着"测准：
        # 创建时刻晚于计时器落账时刻 + 容差 ⇒ 那是复用号，不是账上那一台。
        # 创建时刻读不到 ⇒ 维持 alive 为真（fail-closed，回到进闸）。
        # ---- pid 复用：判据是"这个号现在挂着的映像名与账上那台不同"。
        # 只对账上已收口的那一档判（`state != "pending"`）：账上说还在跑的程序，
        # 映像名对不上也不许降级（它可能就是另一份 python）。
        # 读不到映像名 ⇒ 维持 alive 为真（fail-closed，回到进闸）。
        pid_reused = False
        if alive and state != "pending":
            expect = str(row.get("program") or "").strip().lower()
            if expect.endswith(".exe"):
                expect = expect[:-4]
            got_name = _process_image_name(pid)
            if expect and got_name and got_name != expect:
                pid_reused = True
                alive = False
        row["pid_reused"] = pid_reused
        if pid_reused:
            # 2026-10-28（业主：「收工必须所有人停、所有进程停」，同时不许为收工强停）：
            # 这一档既不进闸（它不存在了）、也不能消失 —— 它进"账与进程对不上"那一组
            # 的第三格，M 的巡查看得见"这个号被别人占了"。
            out["orphans"]["pid_reused"].append(row)
        live = (state == "pending") or bool(alive)
        row["alive"] = alive
        row["live"] = live
        row["owner"] = str(row.get("task_id") or "")
        row["elapsed_sec"] = _program_elapsed(row, now_dt)
        rows.append(row)
        if live and not row["owner"]:
            out["unowned"].append(row)
        elif live and (scope is None or row["owner"] in scope):
            out["running"].append(row)
        if alive and state != "pending":
            out["orphans"]["finished_but_alive"].append(row)
        if state == "pending" and pid is None:
            out["no_pid"].append(row)
    unbooked = [dict(x) for x in (got.get("unbooked") or ()) if isinstance(x, Mapping)]
    out.update({
        "checked": True, "reason": "", "rows": rows,
        "running_count": len(out["running"]),
        "unowned_count": len(out["unowned"]),
        "orphan_count": (len(unbooked) + len(out["orphans"]["finished_but_alive"])
                         + len(out["orphans"]["pid_reused"])),
    })
    out["orphans"]["no_timer"] = unbooked
    return out


def program_span_text(row: Mapping[str, Any]) -> str:
    """一条程序读数的人话：`python（pid 12345，已跑 42 秒）`（唯一实现，逐字可判）。

    三个格子都必须出现，缺哪一格父都没法处置它：`program`（杀谁）、`pid`（拿什么杀）、
    已跑多久（跑了多久）。账上已经收口而进程还在跑的那一档另带一句实话 —— 否则
    "账说它完了"会被读成"它完了"。读不到的格子写"没读到"，绝不编一个 0 秒 / 一个 pid。
    """
    program = str(row.get("program") or "").strip() or "（程序名没读到）"
    pid = row.get("pid")
    try:
        pid_txt = f"pid {int(pid)}" if pid is not None else "pid 没读到"
    except (TypeError, ValueError):
        pid_txt = "pid 没读到"
    secs = row.get("elapsed_sec")
    try:
        if secs is None:
            ran = "已跑多久没读到"
        elif float(secs) < 10.0:
            ran = f"已跑 {float(secs):.1f} 秒"
        else:
            ran = f"已跑 {int(float(secs))} 秒"
    except (TypeError, ValueError):
        ran = "已跑多久没读到"
    tail = ""
    state = str(row.get("state") or "")
    if state and state != "pending":
        tail = "，账上说它已经收口了、进程还在"
    return f"{program}（{pid_txt}，{ran}{tail}）"


def programs_refusal(reading: Mapping[str, Any], *, lead: str = "",
                     limit: int = 6) -> dict[str, Any]:
    """一条"这一支还有程序在跑"的拒信（`Secretary.retire` 与工具共用这一处措辞）。

    返回 `{"code","count","why","missing","blocking","programs"}`：

    - `why`：点名 N 个程序（每个都带 `program` / `pid` / 已跑秒数）＋ 正路只有一条；
    - `missing`：逐条 `程序 <名>（pid …）还在跑`（机器读得懂的那一份）；
    - `blocking`：逐条 `{"kind": "working", "detail": …}`（与 `retire_blocking` 同形，
      所以父不必为"为什么不能销"再学一套形状）；
    - `code`：空串。这一档拦它的不是静默闸（三态那一格），而是"账上还有进程在跑"
      —— 带 `target_not_silent` 会让"它不静默"与"它名下还有程序"在读数上折成一档。
    - `programs`：被点名的那几条读数（前 `limit` 条，机器可复核）。

    ## 正路只指一条，且只写一次
    「先 `program.stop` 停掉它们再销，或等它们自己结束」—— 前者是父此刻能做的，
    后者是不做也会发生的那一条。同一句话不许在拒信里出现三次：读到第三遍的人会去
    找一个"也许还有第三条路"的余地，而这里没有。

    ## `program.stop` 是 G1 那条单落地的入口
    本批只引用它的名字（业主纪律：引用时用它将来真叫的那个名字），判据不依赖它存在
    —— 「或等它们自己结束」那一条今天就走得通。
    """
    got = dict(reading or {})
    rows = [dict(r) for r in (got.get("running") or ()) if isinstance(r, Mapping)]
    count = len(rows)
    listed = "、".join(program_span_text(r) for r in rows[:int(limit)])
    more = f" 等 {count} 个" if count > int(limit) else ""
    head = f"{lead}" if lead else "这一支"
    why = (f"{head}还有 {count} 个程序在跑：{listed}{more} ⇒ "
           "先 `program.stop` 停掉它们再销，或等它们自己结束；"
           "销号不可逆（名字永久不复用），而程序还在跑这件事就再没有人叫得住它")
    blocking = [{"kind": "working",
                 "detail": f"它名下的程序 {program_span_text(r)}还在跑"}
                for r in rows[:int(limit)]]
    missing = [f"程序 {str(r.get('program') or '（没读到程序名）')}"
               f"（pid {r.get('pid') if r.get('pid') is not None else '没读到'}）还在跑"
               for r in rows[:int(limit)]]
    return {"code": "", "count": count, "why": why, "missing": missing,
            "blocking": blocking, "programs": rows[:int(limit)]}


#: 检查器那一族动作写在 `status` 里的结论三态（与 `agent_l._support.THREE_STATES` 同一组词）。
#:
#: 它们不是任务终态：`verified` 说"检查器说通过"，`failed` 说"检查器说不通过"，
#: `unknown` 说"没查成"；而任务那一层问的是"这次召唤跑成了什么"。两者折叠的代价见
#: `Conductor._end_from_payload` 的分档表（`draft/146` D25）。
_TRI_STATE_WORDS: tuple[str, ...] = ("verified", "failed", "unknown")


def _tri_state_of(raw: Mapping[str, Any]) -> str:
    """角色返回里的结论三态（取不到给空串）。

    两处来源，显式键 `tri_state` 优先，其次 `status` —— E 与 L 的 `check_formal` /
    `formalize` / `record` 都把结论写在 `status` 里，而那个词表恰好就是这三格。

    为什么只认这三个词、而不是"凡 `status` 都是三态"：别的角色也在 `status` 里写自己的
    状态词（A 的 `content_mismatch`、F 的 `blocked`、H 的 `draft`），把它们读成三态会把
    一次成功的动作记成"没查成"。这三个词是"检查器说话了"那一族的专属词。
    """
    for key in ("tri_state", "status"):
        value = str(raw.get(key) or "").strip()
        if value in _TRI_STATE_WORDS:
            return value
    return ""


#: 标记"这一行已经结过账"（写进 `tasks.inputs`）。
#:
#: 为什么需要它：`finish()` 是幂等的（终态先到先得），而记账发生在 `finish`
#: 之后。若某一行在本轮 `finish` 之前已经是终态（另一个写者赢了），
#: 再记一次账会让 `usage_ledger` 的汇总变成 `tasks.tokens` 的两倍 ——
#: 而 `verify.py` 会（正确地）报 `usage_task_total_mismatch`。
#: 标记必须在同一事务内可读，所以它落在行上而不是内存里。
_SETTLED_MARK = "tokenmeter:settled"

#: 标记"这一行是受理过的召唤"（写进 `tasks.inputs`，与 `running` 行同一个事务写下）。它今天的用途是审计面（"这一趟累计派出去过几件"），不再是扇出判据 —— 所有者 2026-10-08 把扇出
#: 口径改成"单时刻在飞"（见 `_in_flight_children_of`），"跑过没跑过"对上限不再有影响。为什么还留着它（题 21 选 B，2026-10-07 所有者裁定）：区分"闸门拒掉、根本没跑"与"跑过又拒"。
#: 标记必须打在"受理那一刻"、且与 `running` 行同一笔事务：只有走过 `summon` 第 [5] 步的召唤才带
#: 它 —— 闸门拒绝在写 running 行之前就 `_refuse` 返回了（`inputs=[]`）；此后无论角色自己拒、记账
#: 写回炸、还是进程崩，标记都已经在盘上（挂在 `_SETTLED_MARK` 上会漏算，见 `_occupies_fanout_slot`）。
#: 落在 `inputs` 而不是给 `schema.Task` 加字段：`inputs` 是既有的 set 类数组字段，加一个元素不改变语义。
#: 派活不点动作时 `detail` 写什么（2026-10-16 业主口径 S2）：`detail` 原先逐字取 `spec.summary`，而
#: 空动作没有 spec —— 不留这一格，读台账的人会把"派活"与"没写清"混起来。
_DISPATCH_ONLY_SUMMARY = "派活（不点动作）：由该角色按自己的能力范围自己选动作"

#: 2026-10-17（真机 t5e 实测）：派 H 空动作时，它只会在只读工具面上打转，审出的发现落不了台账（`review_findings` 一行都没有）。原因不是它不干，而是"写"只发生在
#: `action=review` 那一次固定流程里。所以派 H 不点动作时，把这件事直接送回给派活的人，而不是让它自己去猜。
_DISPATCH_ONLY_NUDGE = {
    "H": ("**要 H 落库，就再派一次并点名动作 `review`（带 `doc_id`）** —— "
          "派空动作时它只能读，审出来的发现只会留在回复里，不会进 `review_findings`。"),
}


def _dispatch_only_detail(role: str) -> str:
    """空动作派活那一行 detail：基础说明 ＋ 该角色的可行动提示（没有就只给基础说明）。"""
    nudge = _DISPATCH_ONLY_NUDGE.get(str(role or "").upper())
    return f"{_DISPATCH_ONLY_SUMMARY}。{nudge}" if nudge else _DISPATCH_ONLY_SUMMARY


_ADMITTED_MARK = "conductor:admitted"

#: 消边标记的前缀（S1h）。形态：`edge-released:<子代号>#<第几次>`。
#:
#: 为什么也放 `inputs`：与 `_ADMITTED_MARK` / `_SETTLED_MARK` 同一族 —— 它是"这条边
#: 与什么打过交道"的一格，加一个元素不改变语义，也不需要动 `schema.py`（禁改区）。
#: 谁来决定消边不在这里：决定与判定在秘书那一侧（`draft/90` §1.9 的三分支，
#: S1k 落地），这里只提供幂等的那一笔写入与读侧（`edge` 的说法见 `draft/92` I-12：
#: 边是派生的读数，这一笔是"父已经认过这条边了"的落痕）。
_EDGE_RELEASED_PREFIX = "edge-released:"

#: 达到"同时在飞"上限之后，父任务等多久（秒）再放弃（所有者 2026-10-08 逐字：
#: 「当达到派活上限后，父智能体或主控只可等待子智能体返回结果」）。
#:
#: 为什么是"等"而不是"当场拒"：触顶的正常成因是"这一批还没回来"，而不是"这一趟
#: 不许再派活"—— 当场拒绝会让父任务把步数花在别处（T1 第 19 趟实测：读到"到上限了"
#: 之后 25 步全部空转），而它真正该做的是等这一批返回、腾出名额再派。
#: 900 秒是一个"够一次 Lean 检查/一次检索回来"的量级；到点仍无人返回 ⇒ 照旧拒绝
#: （拒绝报文里带上等了多久），绝不死等 —— wall clock 与取消信号都会打断等待。
DEFAULT_FANOUT_WAIT_SEC = 900.0

#: 等待时的轮询间隔（秒）。为什么轮询台账而不是条件变量：返回发生在别的线程
#: 的 `summon` 里（`finally` 段把 running 行写成终态），而"谁在飞"的唯一权威是台账；
#: 加一把跨线程条件变量等于再造一份"谁在飞"的状态，两份状态一定会漂移。
_FANOUT_WAIT_POLL_SEC = 0.5


def _admitted_inputs(params: Mapping[str, Any]) -> list[str]:
    """`tasks.inputs` 的初值：调用方给的输入清单 + 受理标记。

    受理标记必须与 `running` 行一起、在同一笔事务里写下去（调用点在 `summon` 第 [5] 步
    的 row dict 里）—— 写在之后（无论写在哪一段收尾代码里）都会重新长出"收尾失败
    ⇒ 标记丢失"这个缺陷。这里顺带按值去重：`inputs` 是 `set` 类字段，
    重复元素是坏数据，而调用方可以自己传一个同名元素进来。
    """
    raw = params.get("inputs")
    items: list[Any] = list(raw) if isinstance(raw, list) else []
    if not any(str(x) == _ADMITTED_MARK for x in items):
        items.append(_ADMITTED_MARK)
    return items


# ====================================================================== 趟次索引的生产入口
#
# `sessions.rebuild_run_index` 此前零生产调用者（2026-11-03 清点 E5：156 个工作区里
# 0 份 `index/run-index.json`），于是 `GET /api/run-index` 在真实工作区恒为
# `tri="unreadable"`。现在它有三个生产入口，都走下面这一个函数：
#   1. 顶趟收工成功那一步（:meth:`Conductor.finish_top_level_run`，
#      `stop_reason == "final"`）；
#   2. `agentflow project rebuild-run-index --workspace <工作区>`；
#   3. `agentflow closing` 通关之后（退出码 0，2026-11-03 第二笔）。
# 为什么这个函数住在 conductor.py：三个入口必须共用同一份"该不该建 / 建没建成 /
# 怎么留痕"的口径，而 `webui` 是 conductor 的下游（`webui.readers` 导入本模块），
# 反向 import 会成环；`sessions.py` 只负责"现算 + 原子落盘"，不管这三件事。
#
# 三条纪律：
# - 幂等：索引内容（`sessions` 那张表）与盘上一致就不重写 —— 索引里有
#   `generated_at`，重写一次字节就变了，而"跑两次字节相同"是那条 CLI 的判据；
# - 失败不静默：返回 `checked=False` + `reason`，调用方必须把它说出口
#   （CLI 退出码 2、收工那一步写日志）；
# - 留痕：每次尝试都往 `data/events.jsonl` 记一行 `op=info`（只在该工作区有 `data/`
#   时）—— "建没建、为什么没建成"能事后查，而不是只活在这一次的 stdout 里。


def _audit_run_index(root: Path, reading: Mapping[str, Any], *, by: str,
                     actor: str) -> tuple[str, str]:
    """把这一次建索引落成 `data/events.jsonl` 的一行（`op=info`，不改任何表）。

    返回 `(事件日志路径, 没写成的原因)`。没有 `data/` 的目录不硬造一个（那会在别人的
    目录里凭空长出 store，`store.Store.init` 的守卫就是为这件事存在的）。
    """
    if not (root / "data").is_dir():
        return "", "这个目录没有 data/（不是初始化过的工作区）⇒ 审计没落"
    from .store import Store

    try:
        store = Store(root)
        with store.tx(actor=actor, note="rebuild_run_index") as tx:
            tx.info("run_index_rebuild", checked=bool(reading.get("checked")),
                    built=bool(reading.get("built")),
                    path=str(reading.get("path") or ""),
                    reason=str(reading.get("reason") or ""), by=str(by or ""))
        return str(store.events_path), ""
    except Exception as exc:  # noqa: BLE001 - 审计写不成不许改"索引建没建成"这个结论
        return "", f"{type(exc).__name__}: {exc}"


def run_index_rebuild(root: Any, *, by: str = "",
                      actor: str = "conductor") -> dict[str, Any]:
    """现算并落 `<工作区>/index/run-index.json`，返回读数（永不抛）。

    返回的七个键：

    - `checked`：这一步真的做完了（落盘，或确认盘上那份已是最新）。`False` = 没做成，
      原因在 `reason` 里；
    - `built`：这一次真的写了盘（`False` + `checked=True` ⇒ 已是最新、字节未动）；
    - `path`：索引的落点（`sessions.run_index_path`）；
    - `reason`：`checked=False` 时非空；
    - `note`：人读的一句话（"已落盘" / "没有重写（同一份字节）"）；
    - `audit_path` / `audit_reason`：审计那一格的落点与没落成的原因。

    写失败不吞掉：`OSError` / 形状不对都折进 `checked=False` + `reason`，因为调用方
    要据此决定退出码与日志；而"写完了但读不回来"单独说清（写成功与读得出来是两件事）。
    """
    from . import sessions as SS

    root_p = Path(str(root))
    path = SS.run_index_path(root_p)
    reading: dict[str, Any] = {
        "checked": False, "built": False, "path": str(path), "reason": "",
        "audit_path": "", "audit_reason": "",
        "note": "",
    }
    try:
        fresh = SS.compute_run_index(root_p)
        stored, _why = SS.load_run_index(root_p)
        if stored is not None and stored.get("sessions") == fresh["sessions"]:
            # 内容一致 ⇒ 不重写：`generated_at` 会让每一次重写都换字节，而这条命令
            # 的判据是"跑两次字节相同"。索引是派生数据，字节不变比"时间戳新"重要。
            reading.update(checked=True,
                           note="索引已在盘上且与事件现算结果逐趟一致 ⇒ 没有重写（同一份字节）")
        else:
            SS.rebuild_run_index(root_p)
            got, why = SS.load_run_index(root_p)
            if got is None:
                reading["reason"] = f"写完了但读不回来：{why}"
            else:
                reading.update(checked=True, built=True, note="索引已落盘")
    except Exception as exc:  # noqa: BLE001 - 建索引失败不许打断收工/命令，原因进读数
        reading["reason"] = f"{type(exc).__name__}: {exc}"
    reading["audit_path"], reading["audit_reason"] = _audit_run_index(
        root_p, reading, by=by, actor=actor)
    return reading


@dataclass
class SummonResult:
    """一次召唤的结构化结果。永远不抛业务异常（设计 §2）。

    `status` 回答"跑完了没有"，`outcome` 回答"跑出了什么"。二者正交，六个组合都是有意义且必须能区分的：
    | status | outcome | 含义 |
    |---|---|---|
    | done | ok / no_result / not_applicable / refused | 跑完了（可能"确实没有"，也可能"框架拒绝了"） |
    | failed | failed | 执行中异常 |
    | cancelled | cancelled / refused | 没跑完（被取消 / 因超预算被拒） |
    `refused` 不是 `failed`：拒绝是策略的决定，失败是执行的结果。
    `task_id` 可以是 `None`：取消之后不产生新任务，此时没有台账行（没有 start 就没有 end，这与"每个 start 有且
    仅有一个 end"不冲突）；把它写成 `""` 或编一个 id 会让调用方以为"有一条对应的行"，那是谎报。
    """

    task_id: str | None = None
    role: str = ""
    action: str = ""
    status: str = "pending"
    outcome: str | None = None
    refusal_reason: str | None = None
    detail: str = ""
    error: str | None = None
    payload: Any = None
    artifacts: list[str] = field(default_factory=list)
    inputs: list[str] = field(default_factory=list)
    tokens: int = 0
    usd: float = 0.0
    depth: int = 1
    elapsed_sec: float = 0.0
    #: 本次召唤又召唤出了哪些任务（父 → 子的可读视图）。
    children: list[str] = field(default_factory=list)
    #: 三态：这个结果查过没有。`None` = 这个动作不适用"查"这个概念
    #: （例如"写一行 documents"）；`False` = 没法查（`payload` 里必须有 reason）。
    checked: bool | None = None
    #: 名册登记的三格（2026-10-21 真机缺陷的读数面，见 `Conductor._register_roster`）。
    #:
    #: `roster_considered`：这次召唤走没走过名册漏斗。`False` = 这个结果不是由
    #: `Conductor.summon` 产出的（替身 / 老实现）⇒ 调用方无从判断"登记了没有"，
    #: 而"没走过"与"走过了没登记"必须分得开（三态，不是两态）。
    #: `roster_name`：登记成功后秘书发的名册名（空 = 没登记上，理由在下一格）。
    #: `roster_problem`：没登记上的理由（空 = 登记成功或未受理那一档不适用）。
    #: `roster_state`：写侧的三态读数（2026-10-24 sylow4 真机缺陷的读数面）——
    #: "written" = 名册三份都读到这一趟的那一行；"missing" = 至少一份没写成
    #: （`roster_problem` 逐份给文件名与原因）；"unknown" = 读不到（不许折成写成了）；
    #: 空串 = 这一趟根本没有"登记"这一步（未受理 / 没走过漏斗）。
    #: `roster_note`：写成了、但父给的某几格被写侧兜底换过时的说明（不是失败）。
    roster_name: str = ""
    roster_problem: str = ""
    roster_considered: bool = False
    roster_state: str = ""
    roster_note: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def ok(self) -> bool:
        """"成功"的判据只有一处：`status=="done" and outcome=="ok"`。

        为什么 `refused` 不算 ok（它在 status 层是 done）：调用方问
        `res.ok` 时想知道的几乎总是"东西做出来了吗"，而不是"框架运转正常吗"。
        把 refusal 算成 ok 会让"越权被拦住"在调用方看来像一次成功交付。
        """
        return self.status == "done" and self.outcome == "ok"


# ---------------------------------------------------------------- 可抢占的派活
#
# D-64 的返回形状。改前只有"阻塞到全部完成"这一种拼法，于是父代理在等孩子期间
# 零回合（真机 92 分钟）。三个类型分工如下：
#
# | 类型 | 谁造 | 里面有什么 | 谁读 |
# |---|---|---|---|
# | `SummonStart` | `Conductor.summon_begin` | 前半的成果：`task_id`（已落 running 行）或预先判定的拒绝 | 只有 `summon_run` / `SummonHandle` |
# | `SummonHandle` | `Conductor.summon_preemptible` / `start_summon` | 已派出的编号 + 还在跑 + 落定后的结果 | `agent_loop`（返场点）/ 调度器 |
# | `scheduler.WaveHandle` | `scheduler.start_waves` | 一批 `SummonHandle`（同一形状，逐项一张票） | `run_plan` 的调用方 / `agent_loop` |
#
# 为什么单任务与整批是同一个形状（不是两套）：判据 f 条要求"单任务 `summon`
# 同形"—— 一批 = 一串单独的句柄，于是"爸拿到了什么"这件事在两条路上逐字同构，
# 不会出现"批量能抢占、单个仍阻塞"那种半修。


@dataclass
class SummonStart:
    """一次召唤的前半（已经派出去，或者已经被拒绝）。见 `Conductor.summon_begin`。"""

    role: str = ""
    action: str = ""
    params: dict[str, Any] = field(default_factory=dict)
    by: str = S.CONDUCTOR_ROLE
    parent_task_id: str | None = None
    input_key: str = ""
    instance: str = ""
    token: Any = None
    #: `summon_begin` 开始的那一刻（单调钟）。后半月 `elapsed_sec` 靠它。
    t0: float = 0.0
    #: 已落盘的那条 `running` 行。`None` = 没派出去（看 `refusal`）。
    task_id: str | None = None
    #: 前半的拒绝（终局已定）：越权 / 越深 / 触顶 / 预算 / 取消 / 参数。
    refusal: SummonResult | None = None
    roster: Mapping[str, Any] | None = None
    roster_rec: dict[str, Any] = field(default_factory=dict)
    started_at: str = ""


class SummonHandle:
    """一次可抢占派活的句柄：派完立刻可读，结果随后落定。

    ## 三个状态的位（三态纪律，不折平）

    - `done()`：后半跑完了没有（`False` 期间 `task_id` 已经在台账上、行是 `running`）；
    - `poll()`：不等，落地了就给出结果，没有就 `None`（"还没回来"不是"失败了"）；
    - `result(timeout=…)`：等，到点还没回来就给一个 `status="running"` 的结果 ——
      那个结果不是终态，它说的是"本步先不等了"。把它读成失败或读成成功
      都会把"还在跑"折进另一个故事（本项目最忌的那一类折叠）。

    ## 为什么线程是 daemon

    父循环可能在孩子跑完之前就收工（预算/叫停/步数上限）。那样的收工必须如实
    留痕（`agent_loop` 的退场读数），但不许把一个已经没人在等的孩子变成
    "进程退不出去"—— 进程被一个后台 handler 钉死比"这一趟少一条读数"更贵。
    """

    def __init__(self, start: SummonStart) -> None:
        self.start = start
        self._done = threading.Event()
        self._result: SummonResult | None = None
        self._error: BaseException | None = None
        self._thread: threading.Thread | None = None
        self._settled_at: float | None = None
        #: 落定回调（调度器把"这一项落定了"通知给 `WaveHandle`）。缺省 None。
        self.on_settle: Any = None

    # ---------------------------------------------------------- 只读读数
    @property
    def role(self) -> str:
        return str(self.start.role or "")

    @property
    def action(self) -> str:
        return str(self.start.action or "")

    @property
    def instance(self) -> str:
        return str(self.start.instance or "")

    @property
    def task_id(self) -> str | None:
        return self.start.task_id

    @property
    def parent_task_id(self) -> str | None:
        return self.start.parent_task_id

    def roster_reading(self) -> dict[str, str]:
        """这一笔派活的写侧名册读数（登记发生在 `summon_begin` 的 [5b]，此刻已经有值）。

        为什么句柄要带这一格（2026-10-24 sylow4 真机）：可抢占派活的孩子还在跑时，
        父代理那一步拿到的是"还在跑"，而登记早就发生了 —— 登记成没成、缺哪一份，
        过去只有等孩子落定之后才读得到。读数是四格，与 `SummonResult` 逐字同名。
        """
        rec = dict(getattr(self.start, "roster_rec", None) or {})
        return {"roster_name": str(rec.get("name") or ""),
                "roster_problem": str(rec.get("problem") or ""),
                "roster_state": str(rec.get("state") or ""),
                "roster_note": str(rec.get("note") or ""),
                "roster_considered": bool(rec.get("considered"))}

    def describe(self) -> dict[str, Any]:
        """句柄那一份（不含结果）：已派出的编号 + 还在跑 + 谁派的 + 名册读数。"""
        got = {"role": self.role, "action": self.action, "instance": self.instance,
               "task_id": self.task_id, "parent_task_id": self.parent_task_id,
               "running": self.running(), "done": self.done(),
               "started_at": str(self.start.started_at or "")}
        got.update(self.roster_reading())
        return got

    # ---------------------------------------------------------- 落定
    def attach(self, thread: Any) -> None:
        self._thread = thread

    def settle(self, result: SummonResult) -> None:
        if self._done.is_set():
            return
        self._result = result
        self._settled_at = time.monotonic()
        self._done.set()
        self._observe_submit(result)
        self._notify()

    def _observe_submit(self, result: SummonResult) -> None:
        """把"这件活收工提交了"交给时钟（业主 2026-10-25：收工提交必须被时钟观测到）。

        为什么放在这里而不是放在台账写完之后：时钟要的是"这一趟结束了"这个事实，
        它拿它去唤醒挂着等这件活的父代理（`wait_for=task:<号>` / 子代理名册名）。
        内容取结果的 `detail`（收工产出的摘要）——父代理被唤醒时那句话里要带上它。

        失败姿态：观测是旁路，它炸了不许把落定带下水（与 `_notify` 同一条纪律）。
        """
        try:
            from . import clock as _CLK

            body = str(getattr(result, "detail", "") or "")
            outcome = str(getattr(result, "outcome", "") or "")
            content = f"{outcome}：{body}" if outcome else body
            _CLK.observe_event(
                "submit",
                task_id=str(self.task_id or ""),
                from_task_id=str(self.task_id or ""),
                to_task_id=str(self.parent_task_id or ""),
                role=self.role,
                content=content,
            )
        except Exception:  # noqa: BLE001 - 旁路：见 docstring
            pass

    def fail(self, error: BaseException) -> None:
        """后半炸了（存储/记账那一层）。如实记下来，`result()` 时落成 failed 行。

        改前这条异常会一路炸给 `run_waves` 的调用方 ⇒ 那一批整批丢结果
        （列表变短或干脆没有列表）。现在它是一条 `failed` 结果：列表长度恒等
        这条不变量因此更强了，而不是更弱。
        """
        if self._done.is_set():
            return
        self._error = error
        self._settled_at = time.monotonic()
        self._done.set()
        self._notify()

    def _notify(self) -> None:
        """落定之后通知登记过的那个人（回调炸了不许把这一条结果带下水）。"""
        hook = self.on_settle
        if hook is None:
            return
        try:
            hook(self)
        except Exception:  # noqa: BLE001 - 见 docstring
            pass

    # ---------------------------------------------------------- 三态读数
    def done(self) -> bool:
        return self._done.is_set()

    def running(self) -> bool:
        """派出去、还没落定。没派出去（预判拒绝）也不算在跑。"""
        return bool(self.task_id) and not self.done()

    def finished_at(self) -> float | None:
        return self._settled_at

    def wait(self, timeout: float | None = None) -> bool:
        """等到落定（或到点）。返回"落定了没有"。

        阻塞由 `Event.wait` 完成（等的是"这一件落定"这个事件），账照样记进主时钟
        （`note_wait`）：业主 2026-10-25 要的是"所有计时类工作进同一本账"，而记一条
        "等了多久、等的是谁"不需要把 `Event.wait` 换成 `sleep`（换了会丢掉"一落定就
        返回"的语义）。实测读数在 `clock.now` 的 `waits_recorded` 里。
        """
        budget = None if timeout is None else max(0.0, float(timeout))
        started = time.monotonic()
        got = self._done.wait(budget)
        waited = time.monotonic() - started
        try:
            CLK.note_wait(budget if budget is not None else waited,
                          "等这一件活落定（SummonHandle.wait）",
                          kind="summon_wait", where="conductor.SummonHandle.wait",
                          waited_for=str(self.task_id or ""), slept=waited)
        except Exception:  # noqa: BLE001 - 记账是旁路，不许把等待本身带坏
            pass
        return got

    def poll(self) -> SummonResult | None:
        """不等：落定了就给结果，没有就 `None`。"""
        return self._result if self._done.is_set() else None

    def result(self, timeout: float | None = None) -> SummonResult:
        """等到落定再给结果；到点还没回来 ⇒ 一个 `status="running"` 的结果（非终态）。"""
        if not self.wait(timeout):
            return self._running_result()
        return self._settled_result()

    def _running_result(self) -> SummonResult:
        """还没落定的结果：名册那一格照实给（登记在 [5b] 已经发生，与孩子跑没跑完无关）。"""
        reading = self.roster_reading()
        if not reading["roster_considered"]:
            # 老构造 / 替身：连"走没走过漏斗"都无从判断 ⇒ 三态照旧不折平。
            reading = {"roster_name": "", "roster_considered": False,
                       "roster_state": "",
                       "roster_problem": "结果还没回来 ⇒ 名册读数还没读回来（不是没登记）"}
        return SummonResult(
            task_id=self.task_id, role=self.role, action=self.action,
            status="running", outcome=None,
            detail=("还在跑：本步先不等（可抢占）。它落定之后会在父代理的下一个"
                    "返场点投递；这条不是终态，读成失败或读成成功都不对"),
            roster_name=str(reading.get("roster_name") or ""),
            roster_problem=str(reading.get("roster_problem") or ""),
            roster_considered=bool(reading.get("roster_considered")),
            roster_state=str(reading.get("roster_state") or ""),
            roster_note=str(reading.get("roster_note") or ""),
        )

    def _settled_result(self) -> SummonResult:
        if self._result is not None:
            return self._result
        err = self._error
        text = f"{type(err).__name__}: {err}" if err is not None else "后半没有给出结果"
        return SummonResult(
            task_id=self.task_id, role=self.role, action=self.action,
            status="failed", outcome="failed", error=text,
            detail=f"可抢占派活的后半炸了（{text}）",
        )


def _summon_thread_main(handle: SummonHandle, ctx: Any, run: Any) -> None:
    """后台线程的入口：跑后半，把结果（或异常）落到句柄上。

    异常一律在这里收住：一个后台 handler 抛出去没有人接，症状是"线程默默死了、
    那条任务的 running 行永远不落终态"。落成 failed 结果至少留下可读的原话。
    上下文用 `ctx.run` 进（`consuming_as` / `calling_as` 是 ContextVar）：
    不带上它，这一趟在后台线程里就"不知道自己是谁"，队列认领那一步会认错父。
    """
    try:
        res = ctx.run(run, handle.start)
    except BaseException as exc:  # noqa: BLE001 - 见 docstring
        handle.fail(exc)
        return
    handle.settle(res)


# ---------------------------------------------------------------- backend


class LocalBackend:
    """在进程内调用角色的 Python 实现（确定性、离线 —— 测试与验收走这条）。

    ## 显式接线（为什么不"自动创建"角色实例）

    角色的构造签名各不相同且都需要真实依赖：`AgentA` 要 `providers`、
    `AgentB` 要 `extractor` + `extract_text`、`AgentD` 要 `tools`……
    一个"自动 new 一个 AgentB"的 backend 只能靠猜依赖，而猜错的形态是
    静默少抽取一篇文献。所以本 backend 要求调用方显式给接线
    （`registry`），没给接线就明确拒绝（`not_wired`），绝不假装成功。
    """

    name = "local"

    #: 声明注册表（`None` ⇒ 读内置那份）。类级默认值：子类若自己写 `__init__`
    #: 而没调 `super().__init__()`，仍然拿得到"用内置表"这个默认行为 ——
    #: 实测于 `tests/test_r5_orchestration_cost.py::_ProbeBackend`（三条取消语义用例）。
    _specs: Any = None

    def __init__(self, registry: Mapping[str, Any] | None = None,
                 specs: Any = None) -> None:
        self._specs = specs
        self.registry: dict[str, Any] = dict(registry or {})
        #: 缓存键是 `(角色, 实例标签)`：空标签 = 那个单例（默认行为逐字不变）；
        #: 显式标签 ⇒ 每个实例一个对象（"N 个 B 一起干活"要的是 N 个对象，
        #: 不是一个对象被 N 个线程共用）。
        self._instances: dict[tuple[str, str], Any] = {}
        self._lock = threading.Lock()

    def known_roles(self) -> list[str]:
        return sorted(self.registry)

    def resolve(self, role: str, instance: str = "") -> Any:
        """把注册项变成实例（惰性，按 `(角色, 实例)` 缓存）。

        - 传 `("factory", fn)`：按签名决定给不给 `store=` / `instance=`
          （见下面那段注释：靠 `try/except TypeError` 会把工厂内部的真错吞掉）；
        - 传 `("object", obj)`：直接用（显式实例标签下同一个对象会被复用 ——
          那是调用方自己选择"共享一个实例"，框架不替它分家）；
        - 传 `("class", cls)`：明确拒绝 —— 构造依赖无法自动满足，
          假装能建就是"猜依赖"（见类 docstring）。
        """
        key = (role, str(instance or ""))
        with self._lock:
            if key in self._instances:
                return self._instances[key]
        entry = self.registry.get(role)
        if entry is None:
            raise NotWiredError(f"{role} 没有接线（registry 里没有它）")
        kind, value = entry if isinstance(entry, tuple) and len(entry) == 2 else ("object", entry)
        if kind == "class":
            raise NotWiredError(
                f"{role} 只注册了类 {value!r}：角色的构造依赖各不相同（providers/extractor/tools…），"
                "自动 new 只能靠猜，而猜错会静默少做事。请注册一个工厂或实例"
            )
        if kind == "factory":
            # 用签名决定怎么调，而不是 `try/except TypeError`（2026-09-30 修的坑）：
            # 旧写法把"工厂内部抛的 TypeError"也当成"它不接受这个参数"，
            # 于是真正的错（实测：`agent_b` 构造 LLM 抽取器时 client 不合规）
            # 被吞掉，最后抛出一句误导性的"需要一个 store" —— 那正是本项目
            # 最忌讳的形态（把没说清的说成说清了，而且指着错的地方）。
            try:
                params = inspect.signature(value).parameters
            except (TypeError, ValueError):
                params = {}
            takes_kw = any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values())
            kwargs: dict[str, Any] = {}
            if takes_kw or "store" in params:
                kwargs["store"] = self.store
            if takes_kw or "instance" in params:
                kwargs["instance"] = key[1]
            inst = value(**kwargs) if kwargs else value()
        else:
            inst = value
        with self._lock:
            self._instances[key] = inst
        return inst

    #: 由 `Conductor` 注入（不放进构造签名，是为了让 backend 可以被单测直接建）。
    store: Any = None

    def call(self, role: str, action: str, params: Mapping[str, Any], *, token: CancelToken,
             instance: str = "", task_id: str = "") -> Any:
        """调一次 handler。

        参数名对不上就拒绝，不许静默丢弃。工具的 `ToolRegistry.call` 是按 schema 校验后再调；这里的 handler 是角色
        的真实方法，它的形参名就是它与调用方的契约。把多出来的参数丢掉会让"我传了 `submit_requests=True` 但它被忽略
        了"看起来像一次成功 —— 于是 `gaps()` 报告里说"已提交"，而请求一条也没有。
        ## `G-1`：token 不再"收下就扔"：旧版末行是 `return fn(given)` —— `token` 收了，然后一个字都没往下传，于是
        "取消"只覆盖待启动的任务：已经在跑的 handler 照样跑完、以 `done/ok` 结束（实测 `temp/auditG-probe1.txt`）。
        现在的形态：调用期间把 `token` 放进一个 `ContextVar`，handler 通过 `cancellation.current_token()` /
        `raise_if_cancelled()` 读它，起子进程时用 `cancellation.run_cancellable(..., token=...)`。为什么用 ContextVar
        而不是给实例挂属性：`resolve(role)` 按角色缓存实例，两个并发召唤会共享同一个对象 ⇒ 挂实例属性会让 A 的 token
        被 B 覆盖（静默串味：A 按了停止却停掉了 B）。ContextVar 按执行上下文隔离。调用前先查一次 token：已经取消的
        召唤不该进 handler（否则会白干一轮，还可能写半张表）。
        """
        spec = C.find_action(role, action, registry=self._specs)
        if spec is None:  # pragma: no cover - summon 已经查过，这里是纵深防御
            raise NotWiredError(f"{role} 没有动作 {action}")
        obj = self.resolve(role, instance)
        fn = getattr(obj, spec.handler_name, None)
        if not callable(fn):
            # 装配期 `assert_capabilities` 核过类上有这个方法；走到这里说明
            # 实例上被屏蔽了（属性遮蔽 / 动态删除）。必须炸，不许当成"没接"。
            raise NotWiredError(f"{role} 的实例上没有可调用的 {spec.handler_name}")
        sig = inspect.signature(fn)
        accepts_kw = any(p.kind is inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())
        declared = {n for n, p in sig.parameters.items() if p.kind in (
            inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)}
        given = dict(params or {})
        if not accepts_kw:
            unknown = sorted(set(given) - declared)
            if unknown:
                raise ParamError(
                    f"{role}.{action}（{spec.handler_name}）不认这些参数：{unknown}；"
                    f"它只接 {sorted(declared)}。静默丢弃会让'我传了但它没看'看起来像成功"
                )
        # `G-1`：把 signal 送进 handler 的执行上下文；已取消 ⇒ 不进 handler
        token.raise_if_cancelled()
        var = CX._CURRENT_TOKEN
        reset = var.set(token)
        # `R1-A1-a`：召唤号与取消令牌同构（同一个临界区、同一个 finally 复位）——
        # 角色的 handler 通过 `current_task_id()` 读它，于是"这一趟召唤花了多少"
        # 有了以 `task_id` 为键的挂点（P-09 的粒度是召唤级）。
        id_var = _CURRENT_TASK_ID
        id_reset = id_var.set(str(task_id or ""))
        # 实例轴与台账号同一个临界区（K1/K2）：确定性 handler 里的工具调用
        # （`attack.*` 一类）从 `identity.current_instance()` 读这一格。
        inst_reset = IDENT.set_current_instance(instance)
        try:
            # 显式声明了 `token` / `cancel_token` 形参的 handler 直接收到它 ——
            # 这让"这个 handler 支持取消"在签名上可见（AST 扫得出来），
            # 而不必读实现才知道。没声明的走 ContextVar（今天全部如此）。
            for name in ("token", "cancel_token"):
                if name in declared:
                    given[name] = token
                    break
            return fn(**given)
        finally:
            var.reset(reset)
            id_var.reset(id_reset)          # 异常路径也要复位（与 token 同一处）
            IDENT.reset_current_instance(inst_reset)


class SubagentBackend:
    """把同一次召唤交给 DSH 的 `subagent` / `workflow` 工具（本轮未接线）。

    ## 为什么它必须"显式拒绝"而不是"执行成功但没结果"：设计 §6 说同一个角色规格驱动两种 backend，但本会话的
    `Conductor` 是进程内、确定性的东西，它没有能力去调 DSH 的工具（那需要 harness 的权限面，而调用方是一个库）。
    于是这里只有两条诚实的路：假装跑通并返回空 ⇒ 台账里会留下 `outcome="ok"` 而 `payload=None` 的行，下游会把
    "我们没做"读成"做了但没有" —— 这正是本项目在引文校验、OCR、D 溯源、C 预算截断四处踩过的同一个坑；明确
    `refused/not_wired` ⇒ 台账里留下"这里有一个尚未接线的执行面"。选后者。`detail` 里写清由谁承担。
    """

    name = "subagent"

    def __init__(self, reason: str = "") -> None:
        self.reason = reason or "由 DSH 的 subagent/workflow 承担（本进程内的 Conductor 没有该权限面）"

    def call(self, role: str, action: str, params: Mapping[str, Any], *, token: CancelToken,
             instance: str = "", task_id: str = "") -> Any:
        """后端未接线：一律拒绝（`not_wired` 是一等状态，不是失败）。

        `instance` / `task_id` 收下但不使用（本层没有角色可建，谈实例没有意义）；
        形参必须与 `LocalBackend.call` 逐字同形 —— 两个后端共用一个契约。
        """
        raise NotWiredError(f"{role}.{action} 未接线：{self.reason}")


class NotWiredError(RuntimeError):
    """动作没有接线。不是失败 —— 对应 `refused/not_wired`（见 §2.2 的表）。"""


# ---------------------------------------------------------------- 主控


#: 角色代码故意抛出的领域错误类名 → 它们在任务台账里算"拒绝这次调用"（R-46）。
#:
#: 为什么按类名匹配而不是 import 那些类：conductor 在 import 图上位于 agent_* 之上
#: （agent 模块会 import conductor 的类型），直接 import 会成环。类名匹配的代价是
#: "改了类名这里就失效" —— 所以下面 `selftest`/用例要有一条正控真的抛一次
#: `ExperimentError` 并断言落 `refused/invalid_params`（判据不许只活在注释里）。
_BUSINESS_ERROR_NAMES = frozenset({
    "ExperimentError", "DocumentError", "PlanError", "ReviewError",
    "EvidenceError", "ConjectureError", "ToolError",
    #: 2026-10-17（子代理 agents #10）：`ParamError` 是 `ToolError` 的子类，可这张表按
    #: 类名字符串比对 ⇒ 参数类拒信（"我不认这些参数"）落成 `failed/执行中异常`，
    #: 模型拿不到 kind/reason 自救。补进来；`_business_refusal_code` 同时按 MRO 判，
    #: 于是任何 `ToolError` 子类都自动算业务拒信。
    "ParamError",
})


def _structured_payload(payload: Any) -> Any:
    """把产物投影成"能被 `json.dumps` 结构化读懂"的形状（CS-11）。

    动机只有一条：`_write_task_digest` 里 `payload_keys` 与 `readings` 两格都是按 `Mapping` 取的，而 C 的产物是
    dataclass（`AnalysisReport`）⇒ 那两格恒空、预览只剩 repr 的前 2000 字（真机 `p2-review` 的 `hottest` / `gaps`
    就是这一档，见 `draft/108` §四 CS-11 与 `draft/41-D` §1.3 的逐字读数）。三档投影：
    ① `to_dict()` 可用 ⇒ 用它（对象自己声明的机器可读视图，`AnalysisReport.to_dict()` 就是；`schema` 的行对象
    也都有这个方法）；② 是 dataclass ⇒ `dataclasses.asdict`（`AgentC` 的 `_store` 不是 dataclass 字段，因此不会
    被带进来 —— 这是 `agent_c/_support.py:231-233` 刻意留的口子）；③ 其余原样返回（`json.dumps(default=str)` 仍然是
    最后的兜底）。
    投影失败（`to_dict()` 抛、`asdict` 遇到坏字段）⇒ 原样返回：这条链路的既有纪律是"摘要写不成不许改坏任务
    终态"（`_write_task_digest` 的 docstring 逐字），所以这里既不吞异常去假装投影成功，也不让它穿出去。
    """
    if isinstance(payload, Mapping):
        return payload
    to_dict = getattr(payload, "to_dict", None)
    if callable(to_dict):
        try:
            got = to_dict()
        except Exception:  # noqa: BLE001 —— 见 docstring：失败就退回原样
            got = None
        if isinstance(got, Mapping):
            return dict(got)
    if is_dataclass(payload) and not isinstance(payload, type):
        try:
            got = asdict(payload)
        except Exception:  # noqa: BLE001 —— 同上
            got = None
        if isinstance(got, Mapping):
            return dict(got)
    return payload


#: 收工那一句里单栏点名几个编号（超出部分写"还有 N 条没点名"，不静默截断）。
#:
#: 这个上限不是一个独立的数：它就是 `secretary.MAX_REMINDERS`（同一屏的那一档）。
#: 2026-10-27 之前这里写死 `5` 并附一句"与 `secretary.MAX_REMINDERS` 对齐" —— 一句注释
#: 挡不住漂移（同一个文件里 `_roster_brief_fits` 走的就是转发 `SEC.BRIEF_MAX` 那条正路，
#: 两种写法并存迟早分家，而分家之后"收工那句话点名 5 条、待办栏点名 6 条"不会有任何
#: 判据报）。现在直接转发：`_CLOSURE_IDS_IN_LINE` 是同一个数，`secretary.MAX_REMINDERS`
#: 一改这边立刻跟着变。判据：`tests/test_the_closure_line_follows_the_secretary.py`。
_CLOSURE_IDS_IN_LINE: int = int(SEC.MAX_REMINDERS)


def _closure_ids(column: Mapping[str, Any], *, limit: int) -> str:
    """一栏的编号点名（≤ limit 个 + 显式的"还有 N 条没点名"）。

    为什么带"还有 N 条"：一句话摘要里点名是给人看的，但"少点了几个"必须能被读出来 ——
    静默截断是这一族缺陷的通用形态（业主 2026-10-26 Q18 的追加要求）。
    空栏写"无"而不是留空：留空会被读成"这一格没查"。
    """
    ids = [str(x) for x in (column.get("ids") or ()) if str(x)]
    if not ids:
        return "无"
    shown = ids[:max(1, int(limit))]
    more = len(ids) - len(shown)
    text = "、".join(shown)
    return f"{text}…还有 {more} 条没点名" if more else text


def _closure_suffix(reading: Mapping[str, Any]) -> str:
    """把职责 3 的收尾读数压成顶趟行 `detail` 里的一句话 —— 两栏，不许混成一句。

    三种情形分开写（三态纪律）：没查成（`checked=False`）不许写成"没有未闭环"，
    也不写成空串 —— 收尾行的读者要能从这一句里看出"这一格今天我到底查没查"。
    没有未闭环时给一句明确的"0 条"，而不是留空（留空会被读成"没查"）。

    ## 为什么分两栏（业主 2026-10-26 Q18）
    改前这一句是 `running N 条`：N 由 `by_state` 求和得到，而 `by_state` 的 `running` 那一档
    改前装的是板项行（`status` 恒为 `pending`，见 `secretary.row_axis` 的 docstring）
    ⇒ 真机 `projects/mp3-r3` 收工时逐字写着「闭环提醒 5 条（running 5 条…）」，而那一刻
    18 条代理行全部 done、台账里一个在跑的子都没有。分栏之后"在跑的子代理"与"待办项"
    各说各的数，两栏各自点名（单栏条数有上限，超出写"还有 N 条没点名"）。
    """
    if not reading:
        return "；闭环提醒：没查（收尾读数缺）"
    if not reading.get("checked"):
        return f"；闭环提醒没查成（{str(reading.get('reason') or '')[:60]}）"
    run = dict(reading.get("running_agents") or {})
    pending = dict(reading.get("pending_items") or {})
    run_n = int(run.get("count") or 0)
    pend_n = int(pending.get("count") or 0)
    if not run_n and not pend_n:
        return "；闭环提醒：0 条未闭环（在跑的子代理 0 个；待办项 0 条）"
    states = "、".join(f"{k} {v} 条"
                      for k, v in sorted((reading.get("by_state") or {}).items()))
    tail = f"；{states}" if states else ""
    return (f"；闭环提醒：在跑的子代理 {run_n} 个"
            f"（{_closure_ids(run, limit=_CLOSURE_IDS_IN_LINE)}）；"
            f"待办项 {pend_n} 条"
            f"（{_closure_ids(pending, limit=_CLOSURE_IDS_IN_LINE)}{tail}）")


# ---------------------------------------------------------------- 链式寻址（业主 2026-10-26 裁定）
#
# 业主原话（唯一权威）：
#   「M给绝对编码链例如000001->000005->000012->000024之类，M的秘书发给000005的秘书
#     消息有链000005->000012->000024，然后000005的秘书继续发给下级秘书，直到000024
#     的秘书收到后才具体读消息内容。M的轮查工具务必能反馈绝对编码链。」
#
# 这一节只做两件只读的事：把写法拆成逐跳 token（`parse_chain_address`），以及把
# 台账里的父子链算出来（`Conductor.chain_of`）。逐跳校验与拒信在
# `Conductor.resolve_chain`；真正逐级转发在 `secretary.Secretary.relay_out` /
# `relay_in`（一个秘书一处，不在这里替它们转）。

#: 链式寻址的分隔符。业主写的就是这两个字符；只认这一种写法（多认几种等于把
#: "这一串到底是一条链还是三个收件人"变成猜谜，`to` 那一格没有第二个分隔符）。
CHAIN_SEPARATOR = "->"

#: 链式投递的三态（业主裁定逐字：`delivered` / `refused` / `unknown`）。
#: 与既有的三态纪律同一条：`unknown` 是"读不到名册 / 链没校验"，不是"送不到"。
CHAIN_DELIVERY_STATES: tuple[str, ...] = ("delivered", "refused", "unknown")

#: 链校验的受控拒绝码（工具读数里的取值，不是 `tasks.refusal_reason` 的词表 ——
#: 链校验不落任务行，它是一句话的下发路径）。逐个都由某一行真的产出：
#: `broken_chain`（某跳不是上一跳的直接下级 / 链尾是自己 / 目标不在这一支下面）、
#: `retired_target`（链上某跳已销号）、`not_in_roster`（某一跳不在册 / 不是代理行）、
#: `no_identity`（这一趟没有台账号）、`store_unreadable`（台账读不成）、
#: `roster_unreadable`（名册读不成）、`relay_unwritten`（转发台账写不成）。
CHAIN_REFUSAL_REASONS: tuple[str, ...] = (
    "broken_chain", "retired_target", "not_in_roster", "no_identity",
    "store_unreadable", "roster_unreadable", "relay_unwritten",
)

#: 链式寻址的写法里"这一跳在不在册"的四档（不折平：名册没写过不等于不在册）。
#: 取值与产出它的那一行一一对应，见 `Conductor.resolve_chain` 的 `hops[].roster`：
#: `self`（链头就是发送方自己，它不在任何人的名册里）、`registered`（在册且没销号）、
#: `not_registered`（名册有行、但没有它 ⇒ 受控拒绝）、`unwritten`（这一支从没登记过
#: ⇒ 记下来并放行：台账才是父子关系的权威）。
CHAIN_HOP_ROSTER: tuple[str, ...] = ("self", "registered", "not_registered", "unwritten")

#: 一跳的绝对编号最多 64 层（与 `_ancestry` / `inside_subtree` 的上行链同一个上限：
#: 数据被手工改坏时不许把一条链算成死循环）。
CHAIN_MAX_HOPS = 64


def parse_chain_address(written: Any) -> tuple[list[str], str]:
    """把收件人写法拆成逐跳 token（`000001->000005->000012`）。返回 `(tokens, 问题)`。

    分隔符是 :data:`CHAIN_SEPARATOR`（业主的写法逐字）。两侧空白去掉；任一跳为空
    （`a->` / `->b` / `a->->b`）⇒ 返回已拆出的 token 与一句问题，调用方按受控拒绝
    `broken_chain` 报出来，不替它猜"空的那一跳是谁"。
    只有一个 token 时不等于"没有链"：那是"直接寻址那一个"，链条由台账的父子关系
    现算（见 :meth:`Conductor.resolve_chain`）—— 业主的原话是"M给绝对编码链"，
    而模型只写链尾时，拼链这件事该由掌握台账的这一层做，不该退回给它自己拼。
    """
    raw = str(written or "").strip()
    if not raw:
        return [], "收件人写法是空的（要写绝对编号链，例如 000001->000005->000012）"
    parts = [str(p).strip() for p in raw.split(CHAIN_SEPARATOR)]
    bad = [i for i, p in enumerate(parts, start=1) if not p]
    if bad:
        return parts, (f"{raw!r} 的第 {bad[0]} 跳是空的（分隔符 {CHAIN_SEPARATOR!r} "
                       "两边都要有编号或名册名）⇒ 链不成立")
    return parts, ""


def absolute_chain(rows: Sequence[Mapping[str, Any]], task_id: Any) -> list[str]:
    """从顶趟那一行到 `task_id` 的绝对编号链（链头是顶趟，链尾是它自己）。

    纯函数（不读盘、不碰实例）：调用方给哪一批代理行，就只在那批行里追父链。
    口径只有一条：沿 `parent_task_id` 上行，只走代理行；遇到环或断掉的父（这批行里
    没有那一行）就停在能到的最上面那一格 —— 于是"链不完整"读得出来（链头不是顶趟），
    而不是被悄悄补成一条看起来完整的链。空列表 = 这一行不在这批行里。
    """
    by_id = {str(r.get("task_id") or ""): r for r in rows
             if Conductor._is_instance_row(r)}
    out: list[str] = []
    seen: set[str] = set()
    cur = str(task_id or "")
    while cur and cur not in seen and len(out) < CHAIN_MAX_HOPS:
        row = by_id.get(cur)
        if row is None:
            break
        seen.add(cur)
        out.append(cur)
        parent = str(row.get("parent_task_id") or "")
        if parent == cur:
            break
        cur = parent
    return list(reversed(out))


#: "当前召唤号"（`R1-A1-a`）：与取消令牌（`cancellation._CURRENT_TOKEN`）同构 ——
#: 同一个临界区、同一个 `try/finally`、按执行上下文传。
#:
#: ## 为什么不能挂实例属性（`R1-A1` 的 P-09 挂点）

#: `LocalBackend.resolve(role)` 按角色缓存实例：两个并发召唤会共享同一个对象 ⇒
#: 把号挂在实例上，A 的号会盖掉 B 的（读出来的成本挂到别人的单子上）。
#: `conductor.py` 里那段给取消令牌写的理由逐字适用，所以这里用 ContextVar：
#: 号跟着这一次调用走，调用结束就复位。
_CURRENT_TASK_ID: contextvars.ContextVar[str] = contextvars.ContextVar("agentflow_task_id",
                                                                     default="")


def current_task_id() -> str:
    """这一趟召唤的号（不在任何召唤里 ⇒ 空串）。

    空串 = 没有挂点，不是"零号"：调用方（例如 `agent_d`）拿它去读 `usd_reading`
    时必须把"没号"与"挂上了但没记账"分开 —— 折成一个 0 正是本仓最贵的那个缺陷形态。
    """
    return _CURRENT_TASK_ID.get()


#: 这一趟调用是哪个角色发起的（与 `_CURRENT_TASK_ID` 同族、同一个挂点）。
#: 工具层读它（`current_caller_role()`）：工具的形状里没有"我是谁"这一格，
#: 而广播这类"发给我名下子代理"的能力必须知道发起人。
_CURRENT_ROLE: contextvars.ContextVar[str] = contextvars.ContextVar("agentflow_caller_role",
                                                                   default="")


def current_caller_role() -> str:
    """这一趟调用是哪个角色发起的（不在任何调用里 ⇒ 空串 = 没挂点，不是"没有角色"）。"""
    return _CURRENT_ROLE.get()


#: 这一趟的召唤者（父）的编号与角色 —— 由 `AgentLoop._do_tool` 从
#: `_resolve_parent(...)` 那一次的返回值挂上（业主 2026-10-19 裁定：
#: 「父子天然双向」⇒ 上行不需要在 `edges` 里登记，它跟着"谁召唤了我"走）。
#:
#: 为什么另起两个 ContextVar 而不是让工具自己去读台账：父是运行期解析出来的
#: 那一个（`_resolve_parent` 有三条分支：调用方给的 / 台账读的 / 顶层自己），
#: 工具层拿不到前三者的差别。挂上来的就是那一次解析的结果，逐字一致。
#: 空串 = 没挂点或这一趟没有父（顶层）—— 两者都由调用方分得清（`state` 不折平）。
_CURRENT_PARENT_TASK_ID: contextvars.ContextVar[str] = contextvars.ContextVar(
    "agentflow_parent_task_id", default="")
_CURRENT_PARENT_ROLE: contextvars.ContextVar[str] = contextvars.ContextVar(
    "agentflow_parent_role", default="")

#: 这一趟的会话身份（`{"root", "sid"}` 两格，由同一个挂点带下来）。
#: 为什么工具层需要它：上行的那一条留言必须落进父读的那个会话文件里 ——
#: 按缺省会话写会让"上报了"与"父没读到"在盘上长得一样（`draft/37` §63 的假绿同族）。
_CURRENT_SESSION_ROOT: contextvars.ContextVar[str] = contextvars.ContextVar(
    "agentflow_session_root", default="")
_CURRENT_SID: contextvars.ContextVar[str] = contextvars.ContextVar(
    "agentflow_session_sid", default="")

#: "这一笔框架代办的派活，父是谁"的挂点（2026-10-20，根治 `projects/tree-check` 的
#: t-000019 那一行孤儿）。与 `calling_as` 同构：号跟着这一次调用走，出作用域就复位
#: —— 不挂实例属性（`Conductor` 会被并发共用，一个属性会让 A 的号盖掉 B 的）。
#:
#: 谁用它：`AgentLoop._do_summon_many` 在调 `run_plan` 之前挂上自己的绝对编号
#: （`run_plan` 里"派活时顺手认领队列"那一步要拿它当父）；工具路径不用它 ——
#: 那条路已经由 `calling_as` 把 `task_id` 挂在 `_CURRENT_TASK_ID` 上了。
_CURRENT_OWNER_HINT: contextvars.ContextVar[str] = contextvars.ContextVar(
    "agentflow_owner_hint", default="")


@contextlib.contextmanager
def consuming_as(parent_task_id: str):
    """在 `with` 里把"这一笔派活的父"挂上（见 `_CURRENT_OWNER_HINT`）。

    用法与 `calling_as` 一样只有一处：`Conductor.run_plan` 的队列认领那一步从这里读父。
    为什么不做成 `run_plan` 的一个形参：那个函数的调用方里有一批是判据的替身
    （`lambda calls, token=None: ...`），加形参会把"登记有没有发生"的判据变成
    `TypeError` —— 那是判据坏了，不是实现坏了。
    """
    tok = _CURRENT_OWNER_HINT.set(str(parent_task_id or ""))
    try:
        yield
    finally:
        _CURRENT_OWNER_HINT.reset(tok)


#: 上行（`conductor.escalate`）的受控取值：要父代理做的那件事属于哪一类。
#:
#: 为什么是受控词表而不是自由文本（业主 2026-10-19 裁定：父子天然双向）：
#: 父下一轮读到的是一条待办，它得能按类分派 —— 五个取值正好对应父的五个动作面
#: （去取原文 / 去审一遍 / 重新路由给别的角色 / 补一份缺失输入 / 其余）。
#: 加取值等于放宽这一整根轴，所以它写在模块级常量里、由 `tool` 的 schema `enum`
#: 与 `Conductor.escalate` 各读一次（同一个对象，不是两份字面量）。
ESCALATE_KINDS: tuple[str, ...] = ("fetch_fulltext", "review", "reroute",
                                   "missing_input", "other")

#: 上行那一条留言的标题前缀（机器可识别的那一位：测试与审计按它捞）。
ESCALATE_SUBJECT = "上报召唤者"


def current_parent() -> tuple[str, str]:
    """这一趟的召唤者 `(编号, 角色)`；`("", "")` = 没有挂点（不是"父是空串"）。"""
    return _CURRENT_PARENT_TASK_ID.get(), _CURRENT_PARENT_ROLE.get()


def current_session() -> tuple[str, str]:
    """这一趟的会话身份 `(root, sid)`；空串 = 没挂点。"""
    return _CURRENT_SESSION_ROOT.get(), _CURRENT_SID.get()


def _session_for_task_end() -> tuple[str, str]:
    """`task_end` 该落哪个会话：`(sid, 为什么取不到)`（sid 空 = 退缺省，理由非空）。

    ## 为什么 `task_end` 也要读这里（2026-11-17，AH4）

    真机 `projects/lp-ball-2` 的 `sessions/` 里有两个文件：`2026-11-16.jsonl`
    （9.6 MB，真跑）与 `20261116.jsonl`（48 行，全是 `task_end`）。两个文件的
    `task_id` 交集 47、双向差集空、时刻逐条相等 —— 同一批收口，一份写进了真会话，
    一份写进了缺省日期名。根因不在谁传错了：`Conductor` 没有 `sid` 字段，而
    `finish` / `_refuse` 这两处写会话时一个 `sid=` 都没给 ⇒ `sessions.append` 落到
    `sessions.session_id()`（`%Y%m%d`）。

    号本来就在上下文里（`calling_as` 的 `sid=` 那一格：工具调用与 `run_role`
    的循环体都挂着它）—— 缺的只是"写 `task_end` 的那一笔现取一次"。所以这里不新增
    一整条传递链（`Conductor` 也不加字段），只在唯一的两个写点各读一次。

    取不到时不静默：退缺省会话可以（那是既有的合法落点），但落下的那一行
    必须自带 `sid_problem` 说明"为什么它在缺省文件里，而这一趟的真会话在别处"。
    """
    sid = str(current_session()[1] or "")
    if sid:
        return sid, ""
    return "", ("取不到这一趟的 sid（`calling_as` 的 `sid=` 那一格是空的）⇒ 这一条"
                "按缺省会话写（`sessions.session_id()`：环境变量 `AGENTFLOW_SESSION` "
                "或当天日期）。要落进本趟会话，收这一笔的那一段必须包在 "
                "`calling_as(..., sid=...)` 里")


@contextlib.contextmanager
def calling_as(task_id: str, role: str = "", *, parent_task_id: str = "",
               parent_role: str = "", session_root: str = "",
               sid: str = "", instance: str = "") -> Iterator[None]:
    """这一小段代码以某个实例的身份跑（工具调用用）。

    为什么工具调用也要带身份（S6-b；2026-11-16 起广播工具 `conductor.broadcast` 已退场，
    同一处挂点仍服务 `conductor.guide` / `conductor.escalate` / `trace.children` 这些要"我是谁"的工具）：
    广播的收件人是"我名下的直接子代理"，而工具的形状里没有
    "我是谁"这一格 —— 只有循环知道（`self.my_task_id` 与 `self.role`）。挂点与 `summon` 那一处同一个
    （`ContextVar`，不是实例属性：同一角色的两个并发实例共享对象，挂在实例上会互相盖掉，见 `_CURRENT_TASK_ID`
    的理由）。`parent_task_id` / `parent_role` / `session_root` / `sid`（2026-10-19）：`conductor.escalate` 要的
    三件事 —— 召唤者是谁（运行期 `_resolve_parent` 的返回值，不是工具自己猜的）与这条留言该落进哪个会话文件。
    四个都有默认值：不传 = "这一层不知道"，与从前逐字节同义（旧调用点一个都不用改）。退出时复位（异常也复位）。
    """
    reset = _CURRENT_TASK_ID.set(str(task_id or ""))
    reset_role = _CURRENT_ROLE.set(str(role or ""))
    reset_pid = _CURRENT_PARENT_TASK_ID.set(str(parent_task_id or ""))
    reset_prole = _CURRENT_PARENT_ROLE.set(str(parent_role or ""))
    reset_root = _CURRENT_SESSION_ROOT.set(str(session_root or ""))
    reset_sid = _CURRENT_SID.set(str(sid or ""))
    # `instance`（K1/K2）：这一笔属于哪个实例。挂点与上面五格同一个临界区 ——
    # 工具层（`attack_tools._agent_for`）与写盘面（claims / ARTIFACTS / 事件）
    # 从 `identity.current_instance()` 读它，于是「装配期拿得到 instance、落盘只剩角色」
    # 那条断链在这一层接上。空串 = 这一层没拿到（不是「实例是空」）。
    reset_inst = IDENT.set_current_instance(instance)
    try:
        yield
    finally:
        _CURRENT_TASK_ID.reset(reset)
        _CURRENT_ROLE.reset(reset_role)
        _CURRENT_PARENT_TASK_ID.reset(reset_pid)
        _CURRENT_PARENT_ROLE.reset(reset_prole)
        _CURRENT_SESSION_ROOT.reset(reset_root)
        _CURRENT_SID.reset(reset_sid)
        IDENT.reset_current_instance(reset_inst)


def _business_refusal_code(exc: BaseException) -> str | None:
    """这次异常算不算"角色拒绝了这次调用"？算就返回受控理由码，否则 `None`。

    两条来源，优先级从高到低：
    1. 异常自带 `refusal_reason`（显式协议，且必须是受控词表里的值）；
    2. 异常是上表里的领域错误类（角色故意抛的）。
    其余一律 `None` ⇒ 由调用方记 `failed`（"代码/环境崩了"）。
    """
    code = getattr(exc, "refusal_reason", None)
    if isinstance(code, str) and code in S.REFUSAL_REASONS:
        return code
    if type(exc).__name__ in _BUSINESS_ERROR_NAMES:
        return "invalid_params"
    return None


def _occupies_fanout_slot(row: Mapping[str, Any]) -> bool:
    """这条子行算不算"曾经受理过的派活"（审计面读数）。

    ## 它不判上限
    扇出上限的口径是"此刻在飞的子代理数"（`_in_flight_children_of`）；这个函数只为
    `_admitted_children_of` 那份累计读数提供一格（"这一趟总共派出去过几件"），
    不参与策略判定。

    ## 口径：受理数，不是尝试数
    闸门拒掉的召唤也落台账（`_refuse`：谁试过什么必须留痕），但它根本没跑，所以不计入
    "曾经受理过"：把这些行算进来，读数会随拒绝次数自我毒化。

    ## 判据为什么是"受理标记"，而不是"拒绝理由"、也不是"结算标记"
    拒绝理由是受控词表（`schema.REFUSAL_REASONS`），闸门与角色共用它：角色跑完之后
    自己拒绝也落 `invalid_params` —— 按理由过滤会把"跑过又拒了"误判成"没跑"。区分二者
    的是这条事实：只有走完第 [5] 步（写 `running` 行）的召唤才带 `_ADMITTED_MARK`，
    而闸门拒绝在写 running 行之前就返回了。所以：`outcome == "refused"` 且行上没有受理
    标记 ⇒ 闸门拒掉、根本没跑 ⇒ 不占名额；其余一切（`running` / `ok` / `failed` /
    `cancelled`、以及跑过又拒的）⇒ 占名额
    （负控：`tests/test_fanout_admission.py::test_ran_and_failed_child_still_counts`）。

    不用 `_SETTLED_MARK` 当主判据：那是事后的记账写回打的标记，记账一炸那一行就缺标记
    ⇒ "跑了又拒"被当成"没跑" ⇒ 扇出少算；受理标记在受理那一刻就落盘，与收尾成败无关
    （负控：`test_a_failed_charge_writeback_still_occupies_the_slot`）。没有受理标记的
    行（旧工作区落盘的）退回读 `_SETTLED_MARK` —— 历史台账里"跑过又拒"仍然算占名额。
    """
    if row.get("outcome") != "refused":
        return True
    marks = {str(x) for x in (row.get("inputs") or [])}
    return _ADMITTED_MARK in marks or _SETTLED_MARK in marks


class Conductor:
    """主控：确定性的策略执行者（本轮不做 LLM 推理，设计 §8 待决问题 1）。

    "想做什么"由调用方给出 plan（一串 `TaskCall`），主控负责：
    过策略 → 落台账 → 派给 backend → 写终态 → 汇总。
    """

    def __init__(
        self,
        store: Any,
        *,
        policy: P.Policy | None = None,
        registry: Mapping[str, Any] | None = None,
        backend: str | LocalBackend | SubagentBackend = "local",
        log: Callable[..., None] | None = None,
        token: CancelToken | None = None,
        specs: Any = None,
        secretary: Any = None,
        fanout_wait_sec: float | None = None,
        roster_sink: Any = None,
    ) -> None:
        """`secretary`（A 线）：M 的派活路径上那一个钩子（`draft/54 §2` 的第 3 个落点）。

        它是可选对象（`None` = 没装配）：给了就"同 key 的既有终态行摆出来 + 一份委派评估建议"，不给也照样派活 ——
        秘书的失败姿态是 fail-open，而"没装配"与"装配了但没判断"在读数上是两件事（前者连台账都没有）。
        `fanout_wait_sec`（所有者 2026-10-08）：「当达到派活上限后，父智能体或主控只可等待子智能体返回结果」⇒ 触顶
        时等（等到一个返回就照常派）而不是当场拒绝。默认是 0（不等），真跑批那一处显式传 `DEFAULT_FANOUT_WAIT_SEC`
        （`tools/conductor_tools.conductor_for`）。为什么不把"等"做成构造函数的默认值：它是一个会阻塞十几分钟的副
        作用，库的默认值不该藏这种东西 —— 任何"只是想看看会不会被拒"的调用方都会被它挂住。
        """
        self.store = store
        self.policy = policy or P.Policy()
        self.fanout_wait_sec = (0.0 if fanout_wait_sec is None
                                else max(0.0, float(fanout_wait_sec)))
        #: 角色声明的注册表（`goal-7f5116c1` M5）：给了就从它读"有哪些角色、
        #: 每个角色有哪些动作、谁能召唤谁"；`None` ⇒ 读内置那份（今天的行为逐字不变）。
        #: 存在的理由：新增一个角色时，闸门不该只认源码里写死的那张表。
        self.specs = specs
        self.log = log
        self.token = token or CancelToken()
        if isinstance(backend, str):
            if backend == "local":
                be: Any = LocalBackend(registry, specs=specs)
            elif backend == "subagent":
                be = SubagentBackend()
            else:
                # 未知 backend 不接受（fail-closed）：`backend="local "` 这种
                # 拼法若被当成"未知 ⇒ 大概无所谓"，就会得到一个既不本地也不
                # subagent 的执行面，而它的行为取决于后面哪一行 `if` 先命中。
                raise ValueError(
                    f"未知 backend={backend!r}（只支持 'local' / 'subagent'，或直接传 backend 对象）"
                )
        else:
            be = backend
        self.backend = be
        if isinstance(be, LocalBackend):
            be.store = store

        #: 主控（M）自己的秘书（A 线）。`None` = 没装配 ⇒ 只摆同 key 终态行、不做委派评估。
        #: 秘书不写任何库表、判断不构成任何门的通过条件（`draft/55` §4）。
        self.secretary = secretary
        #: 最近一次读销号名单的读数（由 :meth:`retired_reading_of` 写）。
        #:
        #: 为什么它是一个独立的实例格：`_is_retired_task` 只能回一个布尔，而"读成了、
        #: 它没销号"与"销号名单读不全"必须是两个读数（三态纪律）。折平的代价在这一格上
        #: 很具体 —— 盘上有一行坏行时，读的人只看到"它没销号"，而下一步（叫醒一个已销号
        #: 的名字）是不可逆的那一边。形状见 `retired_reading_of` 的返回值。
        self.last_retired_reading: dict[str, Any] = {}
        #: 最近一次派活前摆出来的"同 key 既有终态行"（读数的第二个落点：日志之外）。
        self._last_duplicates: list[dict] = []
        #: 本次 run 的即时视图（不是账）：只回答"这次 run 还能不能再召唤"。
        #: 权威账在 `usage_ledger`（由 `self.meter` 写、读）；两处口径若不一致，
        #: 以台账为准 —— 见 `MemoryBudgetTracker` 的 docstring。
        self.budget = MemoryBudgetTracker()
        #: 权威账（FC-19）。主控裁决：`usage_ledger` 是权威账，
        #: `tasks.tokens/usd` 由它派生（见 :meth:`_charge_and_settle`），
        #: 于是 `verify.py` 的 `usage_task_total_mismatch` 是由构造保证相等，
        #: 而不是"两处各算一遍但愿它们相等"。
        #:
        #: 预算上限取自 `Policy`：策略是判据的单一来源，这里只是把它交给守卫
        #: （不另写第二份上限）。只有钱这一轴（2026-10-15 业主裁定
        #: 「我们不卡 token，只卡总花销的钱」）；token 那一轴连字段一起删了。
        self.meter = TokenMeter(
            store,
            budget_usd=self.policy.usd_budget,
            log=log,
        )
        self._lock = threading.Lock()
        self._id_lock = threading.Lock()
        #: 正在运行的任务数（瞬时）。由本类维护，因为 backend 不知道全局。
        self._running: set[str] = set()
        self.peak_running = 0
        self._started_total = 0
        #: dispose 后一律拒绝新召唤（幂等）。
        self._disposed = False
        #: 名册的写入口（2026-10-21）。名册是"父与子"的地址面，而"一个子代理被建立"
        #: 这件事的唯一收口在 :meth:`summon`（所有派活路径最后都经过它：`_do_summon`、
        #: `_do_summon_many` / `run_plan`、`tools/conductor_tools` 的两个工具、队列认领、
        #: `scheduler` / `deliver` / `pipeline`）。所以登记只写一处，sink 只负责"写的人是谁"。
        #:
        #: 为什么另起一格而不是直接用 `self.secretary`：`secretary` 那一格同时兼着"派活前的
        #: 委派评估"（`_note_delegation_quality`），语义是"主控的秘书"；名册的写入口可能来自
        #: 发起这次派活的那个循环（`agent_loop` 把自己的秘书接上来）。两者在真机上是同
        #: 一个类、同一个工作区根，但"谁写名册"必须是一个显式的、可判定的接线动作 ——
        #: 否则真机出现"conductor 有秘书、循环没秘书"那一态时，名册就又静默不登记
        #: （`projects/p3-verify` 就是这么空的）。
        #:
        #: `None` = 没接（不是"名册不重要"）：:meth:`_register_roster` 会把它记成一条
        #: problem（"名册不在手上"），而这一步不抛（登记失败不许带走派活）。
        self.roster_sink: Any = roster_sink
        #: 墙钟起点与截止（`time.monotonic()`，不受 NTP 回拨影响）。
        self._start = time.monotonic()
        wall = self.policy.wall_clock_sec
        self.deadline: float | None = (self._start + float(wall)) if wall else None
        #: 第一个"停止"信号的人话说明（用于所有被它终止的任务）。
        self._cancel_detail: str | None = None
        #: 最近一次 `run_plan` 留下的并发探针（由 `scheduler.run_waves` 注入）。
        #: 它是"真并发"的观测口径 —— `peak_running` 会低估（见 `ConcurrencyProbe`）。
        self._last_probe: Any = None
        #: 本次 run 里已经开始的任务数（用于 max_tasks_per_run 判定）。
        self._started_total = 0
        #: B9 的预留令牌序号（`summon` 在锁内占位时用它造一个唯一令牌）。
        self._reserve_seq = itertools.count()
        #: 被取消而没有落台账的召唤数。必须计入总量：否则"取消了就不限次"
        #: 会成为绕过 `max_tasks_per_run` 的路径（取消一次不算数 ⇒ 取消一百万次
        #: 也不算数）。它与 `_started_total` 分开记，因为
        #: `stats()["started_total"]` 说的是"真的跑过几个"，两件事不能混。
        self._cancelled_total = 0
        #: 一拍一份台账快照的线程本地状态（2026-10-27，见 :meth:`reading_snapshot`）。
        #: `rows` 非空 = 本线程正在作用域里（`_tasks()` 命中它）；`depth` 是可重入计数。
        #: 为什么不是实例级的一份缓存：`Conductor` 是并发对象（每个召唤一条线程），
        #: 实例级缓存会让一个线程的快照变成另一个线程的旧视图。
        self._snapshot = threading.local()

    # ---------------------------------------------------------------- 路径
    @property
    def elapsed_sec(self) -> float:
        return time.monotonic() - self._start

    @property
    def deadline_hit(self) -> bool:
        """墙钟是否到点。`None` 的 deadline 表示"不限"（不是"立刻到点"）。"""
        if self.deadline is None:
            return False
        return time.monotonic() >= self.deadline

    def _log(self, message: str, **extra: Any) -> None:
        if self.log is None:
            return
        try:
            self.log(message, **extra)
        except Exception:  # noqa: BLE001 - 日志钩子坏了不该打断编排（与各 agent 的 _log 同约定）
            pass

    # ---------------------------------------------------------------- 台账读写
    def _tasks(self) -> list[dict]:
        """台账的实例行 + 板项行（整表）。

        ## 一拍一份快照（2026-10-27）
        在 :meth:`reading_snapshot` 作用域内，本方法返回作用域开头那一次读到的同一份
        列表（不再是每次现读）。这正是"同一拍里把同一张表读 N 遍"的收口点：
        `store.rows()` 每次都给一份逐行新建的副本（内存缓存的那一版是 `_load` 的文档，
        出口要逐行 `dict(r)` 拷一遍），而一拍里读 60 次与读 1 次在读数上一模一样。
        作用域外逐字回到"现读现算"（下一次调用就是一次新的读）。
        """
        snap = getattr(getattr(self, "_snapshot", None), "rows", None)
        if snap is not None:
            return snap
        return self.store.rows("tasks")

    def _snapshot_rows(self) -> list[dict] | None:
        """当前线程在不在快照作用域里、那一份快照是哪一份（判据读它，生产代码不读）。"""
        return getattr(getattr(self, "_snapshot", None), "rows", None)

    def _refuse_write_in_snapshot(self, what: str) -> None:
        """只读作用域的纪律：这一拍读的是同一份台账快照，写进去的行在作用域内看不见。

        为什么是抛而不是记一条读数：半个视图的后果不是"读到旧值"那么轻 ——
        `_set_item` / `_write_new_row` 写完再读会读不到自己刚写的那一行，于是
        "写成功了"与"没写成"在同一段代码里长得一模一样（本仓反复踩的就是这一档）。
        所以纪律做成硬的：作用域内调写入口 ⇒ 当场抛。

        `note_edge_release` 没有被本守卫覆盖（它属 O1 那一批的"事件消账"改动面，
        本轮按纪律不动它）—— 这一条写在 :meth:`reading_snapshot` 的 docstring 里，
        并由判据 `tests/test_conductor_read_snapshot.py` 的"已知未覆盖"一节点名。
        """
        if self._snapshot_rows() is not None:
            raise RuntimeError(
                f"只读快照作用域（`reading_snapshot`）内不许{what}："
                "这一拍读的是同一份台账快照，写进去的行在本作用域内读不到 —— "
                "要写就别在作用域里写，或者退出作用域再写")

    @contextlib.contextmanager
    def reading_snapshot(self) -> Iterator[None]:
        """只读快照作用域：本线程内 :meth:`_tasks` 命中作用域开头那一份台账。

        ## 三条性质（判据 `tests/test_conductor_read_snapshot.py` 逐条钉住）
        1. 作用域内只读：写入口（`_write_new_row` / `_set_item` / `set_item_detail` /
           `note_blocked` / `_mark_stop_notified_many` / `note_stop_ack` / `_set_usage` /
           `finish` / `_sweep_stale_top_running`）在作用域里调用会抛 `RuntimeError`；
        2. 可重入：嵌套进入不换快照（外层那一份一直用到最外层退出）；
        3. 出了作用域立刻回到现读现算：不在作用域里时下一个 `_tasks()` 就是一次新读
           —— 所以"作用域外写一行、紧接着读"必须看得到它。
        ## 为什么是 thread-local
        `Conductor` 是并发对象（`SummonHandle` 每个召唤一条线程，`scheduler` 还并发派活）。
        进程级缓存会让 A 线程的快照变成 B 线程的旧视图 —— 那正是"看不见刚写的行"那一档
        事故，只不过换成了跨线程版本。`threading.local()` 让每个线程各有一份，作用域只
        覆盖"本线程这一拍"。
        ## 已知未覆盖的一个写入口
        `note_edge_release` 不在守卫名单里（它属 O1 那一批"事件消账"的改动面，本轮按纪律
        不动它）。所以别在作用域里调它：它写进父行 `inputs` 的落痕在本作用域内读不到。
        哪一轮动它，就顺手在它开头加一行
        `self._refuse_write_in_snapshot("记消边（note_edge_release）")`。
        """
        depth = int(getattr(self._snapshot, "depth", 0) or 0)
        if depth == 0:
            # 先在作用域外读一次（这一句必须走现读那一支，不能命中自己）
            self._snapshot.rows = self.store.rows("tasks")
        self._snapshot.depth = depth + 1
        try:
            yield
        finally:
            self._snapshot.depth = depth
            if depth == 0:
                self._snapshot.rows = None

    def _task(self, task_id: str) -> dict | None:
        return next((r for r in self._tasks() if r.get("task_id") == task_id), None)

    def _tasks_by_id(self) -> dict[str, dict]:
        """本拍台账的"编号 → 行"索引（一次读 + 一次建表）。

        为什么要有它（2026-10-27）：`_task(tid)` 每调一次就是一次整表
        `store.rows("tasks")`（`store` 那一层没有缓存，`_load` 每次都整文件
        `json.loads`）⇒ 在"逐个子代理"的循环里调它，一拍就是 N 次全表反序列化。
        实测（`temp/r_be2_reads_per_beat2.py`）：`broadcast` / `notify_children_of_stop`
        逐子调用 `_task()` 是 N 次；换成这份索引是 1 次。
        逐条调用点的正确形状：先取一次索引，再在索引里查。
        """
        return {str(r.get("task_id") or ""): r for r in self._tasks()}

    @staticmethod
    def _is_board_item(row: Mapping[str, Any]) -> bool:
        """这一行是不是板项（工作项）—— 判据在 `secretary.row_axis` 的两个 item 档上。

        ## 为什么收在这里（2026-10-27，`secretary.row_axis` 的 Q18 那条口径）
        "这一行是代理还是工作项"此前在 conductor 里内联了二十来处
        `str(r.get("kind") or "")`，而秘书那一侧早在 Q18 就把这条判据收成了
        `secretary.row_axis`（五档：agent / item_open / item_closed / root / other），
        并在自己的注释里写着"conductor 那几处的内联判法留给下一批收"。
        本方法与 :meth:`_is_instance_row` 就是"下一批"：两处都不再自己读 `kind`，
        只取 `row_axis` 的结论 —— 于是"板项算不算在跑 / 算不算子代理"这件事在全仓
        只剩一处判据（判据：`tests/test_the_axis_is_asked_in_one_place.py`）。
        """
        return SEC.row_axis(row) in (SEC.ROW_AXIS_ITEM_OPEN, SEC.ROW_AXIS_ITEM_CLOSED)

    @classmethod
    def _is_instance_row(cls, row: Mapping[str, Any]) -> bool:
        """"实例行"（代理行 / 顶趟行 / 历史终态行）—— 即"不是板项"。

        为什么不直接叫 `is_agent`：这一类含已收工的与顶趟那一行（展示面与审计面要
        回答的是"谁试过什么"），而"还算不算在跑"是另一问（`secretary.is_live_agent`，
        Q27 把这两问拆开了）。轴仍然只有 `secretary.row_axis` 一处判。
        """
        return not cls._is_board_item(row)

    def _children_of(self, task_id: str) -> list[str]:
        """`task_id` 名下子代理的编号（展示面 / 审计面：谁试过什么都要看得见）。

        ## 为什么必须排除板项（`kind` 非空）
        `tasks` 装两类行：实例行（`kind == ""`）与工作项行（`kind` 非空）。板项那一行的
        `parent_task_id` 口径是"收件人的编号"，于是一条"某子代理已收工"的 `notice` 挂在
        父名下、一条"派给你的活"的 `delegation` 挂在子名下。按 `parent_task_id` 数行而
        不看出身，会把这两种东西算成"子代理"：交付面（`SummonResult.children` 与提示词里
        的 `{{children}}`）会把工作项当成子代理报给模型；`_in_flight_children_of(父)` 也会
        被 20 条 `notice` 读成 20 个在飞的子。
        修法就是把两轴分开：本方法只数代理（实例行），工作项那一边的唯一读数是
        `open_items_of(task_id)`（"某条边名下未消的项"）。两者一起才是消边谓词
        （实例轴 + 工作项轴），不是互相代替。
        """
        return [str(r["task_id"]) for r in self._tasks()
                if r.get("parent_task_id") == task_id and self._is_instance_row(r)]

    def _admitted_children_of(self, task_id: str) -> list[str]:
        """`task_id` 受理过的子召唤（累计读数；审计面用，不再是扇出判据）。

        ## 与 `_children_of` / `_in_flight_children_of` 的分工（刻意三个口径）：
        - `_children_of` 数"台账里有几行子行"：展示面/审计面用，含被闸门拒掉的尝试
          （`SummonResult.children` 由它填）；
        - `_admitted_children_of` 数"累计真的派出去过几件"：审计面（"这一趟用了多少派活
          额度"），不再当判据 —— 扇出口径是单时刻的（见 `_in_flight_children_of`）；
        - `_in_flight_children_of` 数"此刻还没返回的子代理"：扇出判据的分子。
        为什么不就地改 `_children_of`：它不只服务扇出（`summon` 末尾的 `res.children`
        也用它），把它的口径改窄等于顺手改坏展示面 —— 那一改没有任何地方会报错，只会让
        "谁试过什么"从台账视图里静默消失。判据见
        `tests/test_fanout_admission.py::test_display_face_still_lists_attempts`。
        占不占名额的判据在 `_occupies_fanout_slot`（含"为什么不是按拒绝理由过滤"）。
        出身过滤：本方法只数代理行（`kind == ""`）—— 板项行的 `parent_task_id` 口径是
        "收件人的编号"，把它们算进"派出去过几件"是两轴混算（20 条 `notice` 就会读成
        20，而一个代理都没有）。
        """
        return [str(r["task_id"]) for r in self._tasks()
                if r.get("parent_task_id") == task_id
                and self._is_instance_row(r)
                and _occupies_fanout_slot(r)]

    def _in_flight_children_of(self, task_id: str) -> list[str]:
        """`task_id` 派出去、此刻还没返回的子代理（= 扇出判据的分子）。

        ## 口径：单时刻，不是累计
        「派活上限不是累计的，是单时刻的，即 M 同时派出在后台运行的子代理数不超过 20，
        各角色智能体允许同时向其它智能体派活数不超过 5，智能体返回后腾出空间。」
        分子 = 子行里 `status ∈ {"pending", "running"}` 的那些；子代理一返回（`done` /
        `failed` / `cancelled` —— 三者都带 `ended_at`，互相不覆盖）就腾出名额，与它
        返回得好不好无关（`schema.TASK_STATUSES` 是状态词表的唯一来源）。闸门拒掉的召唤
        根本没跑、连 `running` 行都没有（`_refuse` 只落一行 `outcome="refused"` 的终态
        行）⇒ 天然不计。按累计算则一趟几十上百步的研究型跑批会在前几十步用完名额，此后
        重派全部进不去；而"同时在飞 20 个"在同一份 `Policy` 里由 `max_concurrency` 另管。

        ## 只数代理行（两轴分开）：分子多一个出身过滤 `kind == ""`
        板项行由 `open_item` 建、`status="pending"`，而板的状态机（`_set_item`）只改
        `item_state`、从不改 `status` ⇒ 一条已 ack 的板项永远像"在飞的子代理"；父名下挂
        20 条"子代理已收工"的 `notice`（零代理）就会把本读数读成 20 ⇒ 同一父下派活被拒
        `fanout_exceeded`。工作项那一边归 `open_items_of(task_id)`（纯读数，不参与任何
        判定）。判据：`tests/test_board_does_not_eat_the_fanout_quota.py`。

        ## 判据只有一处
        上面那两条过滤（`kind` 与"`status` 在活档"）不在这里自己写，整条交给
        `secretary.is_live_agent`。它比这里旧的判据多排一类（`action == "run"` 且没有父的
        顶趟行），而本方法的每一行都已经被 `parent_task_id == task_id` 过滤 ⇒ 那一类要求
        父为空 ⇒ 两个集合结构上不相交。判据：
        `tests/test_the_axis_and_liveness_are_asked_separately.py` 的 c 与 e 两条
        （同夹具对拍 + 把 row_axis 打桩成"status 恒活"之后必须变红）。
        """
        from .secretary import is_live_agent      # 惰性：与本模块其余几处引用秘书同姿态

        return [str(r["task_id"]) for r in self._tasks()
                if r.get("parent_task_id") == task_id and is_live_agent(r)]

    def fanout_seats_of(self, parent_task_id: str, *,
                        names: Mapping[str, str] | None = None) -> dict[str, Any]:
        """父任务此刻的扇出名额读数：占了几格、每一格坐着谁、其中谁已经可以销号腾位。

        ## 它为什么必须有（而不是让拒绝报文只说"满了"）
        触顶那一刻，父手上其实有两类名额：被"还在干活 / 还在等"的子代理占住的那些
        （只能等），与被"已经交差、但那一行还没落终态"的子代理占住的那些 —— 后者按
        三态已经是静默，父的下一步就是销号它（`conductor.retire_child`），销完名额立刻
        回来。拒信不点名这一档，父就只能干等一个永远不会返回的子代理。

        ## 口径只有一处
        占位 = `_in_flight_children_of(parent_task_id)`（`status ∈ {pending, running}` 的
        代理行，单时刻口径，与 `policy` 判据用的是同一个数）；
        每一格的三态 = `activity_snapshot()`（`agent_state` 的唯一实现，与销号门同一份），
        所以这里读出来的"静默"就是销号门认的那一个"静默"。两处口径不许分家：一旦分家，
        拒信说"静默子可销"，父去销又吃到 `target_not_silent`。

        ## 返回
        `{"checked", "count", "seats", "silent", "flying", "standby", "unknown", "reason"}`：
        - `count`：此刻占位的直接子数（= 扇出判据的分子）；
        - `seats`：每一格 `{"task_id", "name", "role", "state", "state_label",
          "occupies", "retirable", "why"}`（`retirable` = 静默 = 现在销它就能腾出这一格）；
        - `silent` / `flying` / `standby` / `unknown`：按三态分的四份名单（人话标签）；
        - 读不成 ⇒ `checked=False` + `reason`（此时 `count` 仍然是台账数：它是权威分子，
          三态只是"这一格能不能销"的判据，两者不互相冒充）。
        """
        tid = str(parent_task_id or "")
        out: dict[str, Any] = {"checked": False, "count": 0, "seats": [],
                               "silent": [], "flying": [], "standby": [],
                               "unknown": [], "reason": ""}
        try:
            occupying = self._in_flight_children_of(tid)
            rows = {str(r.get("task_id") or ""): r for r in self._tasks()
                    if self._is_instance_row(r)}
        except Exception as exc:  # noqa: BLE001 —— 读不成是"没查成"
            out["reason"] = f"{type(exc).__name__}: {exc}"
            return out
        out["count"] = len(occupying)
        try:
            snap = self.activity_snapshot()
        except Exception as exc:  # noqa: BLE001
            out["reason"] = f"三态读数没读成（{type(exc).__name__}: {exc}）"
            return out
        if not snap.get("checked"):
            out["reason"] = f"三态读数没读成（{snap.get('reason')}）"
            return out
        by_task = dict(snap.get("by_task") or {})
        name_of = dict(names or {})
        if not name_of:
            # 名册名是父与子之间的指称（`D1`）；没有对照表就写编号 —— 不猜名字。
            for one in occupying:
                try:
                    got, _why = self.secretary.name_of(owner=tid, task_id=one)
                except Exception:  # noqa: BLE001 —— 名字读不到只影响措辞
                    got = ""
                if got:
                    name_of[one] = str(got)
        for one in occupying:
            cell = dict(by_task.get(one) or {})
            state = str(cell.get("state") or AGENT_STATE_UNKNOWN)
            label = _agent_label(one, name_of)
            role = str((rows.get(one) or {}).get("role") or cell.get("role") or "")
            seat = {"task_id": one, "name": label, "role": role,
                    "state": state,
                    "state_label": str(cell.get("state_label") or "")
                                   or AGENT_STATE_LABELS.get(state, ""),
                    "occupies": True,
                    "retirable": bool(state == AGENT_STATE_SILENT),
                    "why": str(cell.get("state_reason") or "")}
            out["seats"].append(seat)
            key = state if state in (AGENT_STATE_FLYING, AGENT_STATE_STANDBY,
                                     AGENT_STATE_SILENT) else AGENT_STATE_UNKNOWN
            out[key].append(label)
        out["checked"] = True
        return out

    def _await_fanout_slot(self, parent_task_id: str, limit: int, *,
                           token: CancelToken | None) -> dict:
        """等到这个父任务的在飞子代理少于 `limit`（所有者 2026-10-08 的"只可等待"）。

        返回读数（进日志，触顶被拒时也进拒绝报文）：`waited=True/False`（有没有真的等过）；`waited_sec`（等了多久）；
        `in_flight_before` / `in_flight_after`；`reason`：`slot_freed`（等到了）/ `wait_timeout`（等到
        `fanout_wait_sec` 仍满）/ `cancel_requested`（等待期间被取消）/ `wait_disabled`（`fanout_wait_sec=0`）。
        三态纪律：超时与取消都不冒充"腾出了名额"—— 调用方按 `in_flight_after` 重新判，于是"等到了"与"没等到"在台账
        上是两件事（前者继续派、后者拒并带上读数）。
        """
        before = len(self._in_flight_children_of(parent_task_id))
        budget = self.fanout_wait_sec
        out: dict[str, Any] = {"waited": False, "waited_sec": 0.0,
                               "in_flight_before": before, "in_flight_after": before,
                               "limit": limit, "reason": "wait_disabled"}
        if budget <= 0:
            return out
        t0 = time.monotonic()
        out["waited"] = True
        while True:
            if token is not None and token.cancelled:
                out.update({"waited_sec": time.monotonic() - t0,
                            "in_flight_after": len(self._in_flight_children_of(parent_task_id)),
                            "reason": "cancel_requested"})
                return out
            now = len(self._in_flight_children_of(parent_task_id))
            if now < limit:
                out.update({"waited_sec": time.monotonic() - t0, "in_flight_after": now,
                            "reason": "slot_freed"})
                return out
            if time.monotonic() - t0 >= budget:
                out.update({"waited_sec": time.monotonic() - t0, "in_flight_after": now,
                            "reason": "wait_timeout"})
                return out
            CLK.await_io(
                min(_FANOUT_WAIT_POLL_SEC,
                    max(0.0, budget - (time.monotonic() - t0))),
                "等在飞的子代理让出一个名额（业主 2026-10-08：只可等待）",
                kind="fanout_slot", where="conductor._await_fanout_slot")

    def _ancestry(self, task_id: str | None) -> tuple[tuple[str, str, str], ...]:
        """重建 `(role, action, input_key)` 的祖先链（含起点自身）。

        为什么从台账重建而不是用调用栈：跨进程/跨会话之后调用栈就没了，
        而台账是唯一的权威来源（`schema.Task.parent_task_id` 的注释原话）。
        链上有环时（数据被手工改坏）用 `seen` 截断 —— 一个"为了报错而写死循环"
        的溯源函数是没法用的。
        """
        chain: list[tuple[str, str, str]] = []
        seen: set[str] = set()
        cur = task_id
        while cur and cur not in seen:
            seen.add(cur)
            row = self._task(cur)
            if row is None:
                break
            chain.append((str(row.get("role") or ""), str(row.get("action") or ""),
                          str(row.get("input_key") or "")))
            cur = row.get("parent_task_id")
        return tuple(reversed(chain))

    def _depth_of(self, parent_task_id: str | None) -> tuple[int, str]:
        """子任务的深度 = 父的深度 + 1（I-3：深度单调不减，resume 后不重置）。

        主控发起 = 1，所以必须从父行读，不能从"当前调用栈有几层"推 ——
        后者在 `run_plan` 并发时是错的（工作线程的栈深度与召唤链深度无关）。
        """
        if parent_task_id is None:
            return 1, S.CONDUCTOR_ROLE
        row = self._task(parent_task_id)
        if row is None:
            raise ValueError(
                f"parent_task_id={parent_task_id!r} 在 tasks 表里不存在 —— "
                "凭空挂一个父会让深度链断裂（I-3 要求子 depth 恒等于父 depth+1）"
            )
        return int(row.get("depth") or 0) + 1, str(row.get("role") or "unknown")

    # ---------------------------------------------------------------- 写台账
    def _write_new_row(self, row: dict, *, note: str,
                       roster_pending: bool = False) -> str:
        """取号 + 建行在同一个临界区内完成，返回 `task_id`。

        `roster_pending=True` 时，取号之后、行提交之前把这一号标进
        `secretary._ROSTER_PENDING`（见那个集合的 docstring）：`roster_repair`
        的已知集并上它，「台账行已落、名册还没登记」就不会被读成「漏登记」。
        清理在调用方的 `finally` 里（`_summon_preflight` 的 [5]→[5b] 整段），
        这里只负责提交失败时回滚标记。

        ## 为什么"先算号、再写行"是一个真实缺陷（不是防御性编程）：`interactions.next_prefixed_id` 是纯函数（取 max+1
        并跳过已占用），它没有计数器。所以分开做在并发下必错：
        1. 线程 C 算出 `t-0003`，还没写行就出了临界区；
        2. 线程 H 进来读 `tasks`，看不见 C 那一行（它还没被写），于是也算出 `t-0003`；
        3. 两行按主键 upsert ⇒ 后写的静默覆盖先写的。
        实测症状（`tests/test_conductor.py::test_concurrent_summons_never_share_a_task_id` 就是它的回归测试）：同一个
        `task_id` 出现在两个不同召唤的返回值里，台账里凭空少一次召唤，而没有任何地方报错。它与 `store.alloc_id`
        docstring 里记录的那次真实缺陷同族（`test_store_alloc_guard.py` 覆盖了 4 位空间那一半）。
        ## 另一个细节：`task_id` 必须是行 dict 的第一个键：传入的 `row` 必须已经带 `task_id`（值先留空也行，这里会
        覆盖）。为什么这一点重要：快照是按 dict 的键顺序序列化的，而 `rebuild()` 用 `Task.to_dict()`（= dataclass 字段
        顺序，`task_id` 在最前）重建行。如果第一次落盘时 `task_id` 被排在最后，`rebuild()` 之后键顺序会变，于是
        `tasks.json` 逐字节不一致（I-9 直接失败）—— 数据没错，但"可重建"这条承诺破了。
        """
        self._refuse_write_in_snapshot("建行（_write_new_row）")
        try:
            with self._id_lock:
                with self.store.tx("tasks", actor="conductor", note=note) as tx:
                    return self._row_with_id(tx, row, note=note,
                                             roster_pending=roster_pending)
        except BaseException:
            # 提交失败也要把在飞标记清掉：留着它，这一号会被 repair 永久跳过。
            # `row` 就地带着 task_id（`_row_with_id` 在 upsert 之前就写进去了）；
            # 取号自己就失败时它是空串，forget 是幂等 no-op。
            if roster_pending:
                SEC.forget_roster_pending(
                    self.store.root, str(row.get("parent_task_id") or ""),
                    str(row.get("task_id") or ""))
            raise

    def _row_with_id(self, tx: Any, row: dict, *, note: str,
                     roster_pending: bool = False) -> str:
        """在一笔事务里取号 + 建行（`_write_new_row` 与批量建行共用的唯一一处）。

        为什么抽出来而不是让批量那一路自己写一遍：落盘的键集与键序
        （`task_id` 必须第一）与"取号在临界区内"这两条都是逐字节级别的判据
        （`tasks.json` 重建一致），两处各写一遍的代价不是"重复代码"，而是
        "一条路径的 `task_id` 排到了最后 ⇒ `rebuild()` 之后快照变了"。
        """
        from .interactions import next_prefixed_id

        row["task_id"] = next_prefixed_id(tx.rows("tasks"), "task_id", "t")
        if roster_pending:
            # 标记落在 upsert/提交之前：别的线程读得到这一行的时刻，一定晚于这次
            # `set.add`（GIL 下同一线程的语句顺序即可见顺序）。`roster_repair` 再按
            # 「先读 `_tasks()`、后读标记」的顺序读，就得到「见行必见标记」；
            # 反过来做的失效形态由读序负控钉着。
            SEC.note_roster_pending(
                self.store.root, str(row.get("parent_task_id") or ""), row["task_id"])
        ordered = {"task_id": row["task_id"]}
        ordered.update({k: v for k, v in row.items() if k != "task_id"})
        task = S.Task(
            **{k: v for k, v in ordered.items() if k in S.Task.__dataclass_fields__}
        )
        task.validate()
        # 落盘的行一律补齐到全字段（`Task.to_dict()` = dataclass 字段顺序）。
        #
        # 为什么不是"调用方给什么就写什么"：调用方的行 dict 是手写的字面量，加列之后
        # 它们不会自动多出那几格，而 `rebuild()` 用 `Task.to_dict()` 重建 —— 于是
        # "第一次落盘的键比重建后少几格"，`tasks.json` 逐字节不一致，判据当场红
        # （`tests/test_conductor.py::test_i9_tasks_snapshot_rebuilds_byte_identical`
        # 与 `tests/test_task_instance.py` 就是抓住它的那两条）。
        # 键集与键序只留一处口径：这里，用 dataclass 自己吐出来的那一份。
        tx.upsert("tasks", task.to_dict(), note=note)
        return str(row["task_id"])

    # ---------------------------------------------------------------- 名册登记（唯一漏斗）
    #
    # 登记必须发生在"受理那一行落盘之后、`backend.call` 之前"，而不是等子代理跑完再
    # 登记：否则被杀在途中的子代理永远不登记，批量那一路还要等整批跑完才登记第一行。
    #
    # 为什么收在 `Conductor.summon` 这一处：所有派活路径最后都经过它（形状那两条、
    # `tools/conductor_tools` 的两个工具、队列认领、`scheduler` / `deliver` / `pipeline`）。
    # 谁调它不重要，重要的是"子行建立成功"这件事只有一个发生点。
    #
    # 同一处时序还决定另一件事：`LlmBackend.call` 给子代理起循环时按
    # `surface_of(owner=父, task_id=子)` 从名册里读那一趟的读写面 —— 名册行若在返回
    # 之后才建，面切割读不到它，等于从来没生效过。

    #: 名册三份（写侧兜底与"写没写成"的读数都以这三份为口径，顺序即报错顺序）。
    _ROSTER_FILES: tuple[tuple[str, str], ...] = (
        ("roster", "名册正文"), ("index", "对照表"), ("surfaces", "面池"))

    def _register_roster(self, *, task_id: str, role: str, owner: str,
                         meta: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """把"刚建立的那个子行"登记进 `owner` 的名册。

        返回 `{name, problem, considered, state, note}`（写口拒绝时另带
        `refusal_code`：`name_taken` / `task_id_reused` / `task_id_retired` /
        `member_retired` / `not_in_roster`，与 `Secretary.roster_add` 的回执同一套），后几格是
        写侧的三态读数：

        - `state="written"`：名册三份都读得到"这一趟的那一行"；
        - `state="missing"`：至少一份没写成，`problem` 逐份给文件名与原因；
        - `state="unknown"`：读不到（不许折成"写成了"，也不许折成"没写成"）；
        - `state=""`：这一趟根本没有"登记"这一步（只在调用方没走这条漏斗时出现）；
        - `note` 非空 = 走完了登记漏斗、但有下面三件"不是失败"的事之一：父给的那几句
          被写侧兜底换过（改由秘书代写简介），兜底自愈补了 N 条历史漏行，或
          兜底自愈跳过了 N 条在飞（`skipped` 号清单随 `note` 交回）。

        ## 兜底自愈与「在飞」窗口

        自愈跑在这里（`roster_add` 之后），它读的是"台账有、名册没有"，而本条自己的
        台账行在 [5] 就已经落盘 —— 若没有在飞标记，兄弟线程的这次自愈会把还没走到
        自己 `roster_add` 的那几行当成漏行补掉，并给它们打上 `repaired=true`。
        在飞标记由 `_row_with_id` 在"取号之后、行提交之前"落下，`_summon_preflight`
        的 finally 在登记之后清掉；`Secretary.roster_repair` 把它并进已知集。

        这条链的地基是一个读序：自愈必须先读台账、后读在飞集合。标记先于行
        提交落地，GIL 下"看得见行"的读者之后一定看得见标记；两处一对调，这条保证就
        没了，而所有正题仍会是绿的 —— 读序负控钉在
        `tests/test_sibling_registration_race_is_not_backfilled.py`。

        写口拒绝（`refusal_code` 非空或 `problem` 非空，即"秘书那一侧一个字都没写"）
        一律原样返回：不重试、不跑下面的兜底自愈（撞名字不再由框架顺延换名，交父决定；
        任何拒绝都算 —— 自愈会把刚被拒的这一条按新名字补进名册，那等于换个地方继续
        静默改名）。

        六条口径（与 :meth:`summon` 的第 [5] 步一起构成"恰好登记一次"）：
        1. 只在这里登记 —— 调用点一个都不许再自己调 `roster_add`（重复行会让名册里出现
           两条同名项，`Secretary.next_name` 按角色序号发号，第二条会变成 X2）；
        2. 没写入口（`roster_sink` 与 `secretary` 都空）⇒ 返回一条 problem，不抛：
           "名册不在手上"与"登记过了"必须分得开（三态，不是两态）；
        3. 秘书拒收 / 抛异常 ⇒ 返回 problem，不抛（登记失败不许带走这次派活），
           原文照抄，不替它改写成"没给简介"；
        4. 名字由框架发：调用方没给 `name` 也没给 `reuse` ⇒ 显式走"新建"那一支
           （`new=role`），名字由 `Secretary.next_name` 按用过的最大序号顺延 ——
           不靠父记得给名字，也不会把同一个名字发给两个子代理；
        5. 父给的那一句简介进不了名册（超长 / 多行）⇒ 不拿它去撞秘书的内容闸：
           改交空简介 + 任务原文，走秘书代写那一支（登记行里 `brief_source=secretary`）。
           内容闸会把整份登记拒在写盘之前 ⇒ 三份名册文件一份都没建出来（`out/roster/`
           里连 ``<父>-surfaces.jsonl`` 都没有），读侧只能落在 `unplaced`；
        6. 写没写成要读盘，不许只信返回值：秘书报了成功而盘上没有那一行，同样按
           "没写成"报。三份任一份缺，都不许让这次召唤静默通过。
        """
        meta = dict(meta or {})
        if not str(owner or "").strip():
            # 没有父的绝对编号 ⇒ 名册上没有它的位置（顶趟本来就不进任何人的名册，
            # 但一次召唤没有父是结构问题：孤儿行）。两种都要留理由，别静默。
            return {"name": "", "considered": True, "state": "missing",
                    "problem": (f"{task_id}：没有父的绝对编号 ⇒ 名册没地方登记"
                                "（`tasks.parent_task_id` 是父子关系的唯一权威来源）")}
        if not str(task_id or "").strip():
            return {"name": "", "considered": True, "state": "missing",
                    "problem": "这一笔还没有台账编号 ⇒ 名册没登记"}
        sink = self.roster_sink if self.roster_sink is not None else self.secretary
        if sink is None:
            return {"name": "", "considered": True, "state": "missing",
                    "problem": ("这一趟没有秘书 ⇒ 名册不在手上（没有登记）"
                                "（`conductor.roster_sink` 与 `conductor.secretary` 都是 None）")}
        want_name = str(meta.get("name") or "")
        reuse = str(meta.get("reuse") or "")
        note = ""
        brief = str(meta.get("brief") or "")
        task = str(meta.get("task") or "")
        brief_for_add = brief
        if not self._roster_brief_fits(brief) and str(task or "").strip():
            # 口径 5：父那一句进不了名册，但任务原文在 ⇒ 换成"秘书代写"那一支。
            # 不截断、不删改父的原文（那是秘书的内容闸管的事）：换的是"谁来写这一句"。
            brief_for_add = ""
            note = (f"父给的简介进不了名册（{self._roster_brief_why(brief)}）；"
                    "改由秘书按任务原文代写后登记（名册行里 brief_source=secretary）")
        kwargs: dict[str, Any] = {
            "owner": str(owner), "role": str(role), "task_id": str(task_id),
            "brief": brief_for_add,
            # `task` 一并交给秘书：简介没写时由它代写并留痕，
            # 所以这里不写 `brief or task`（那是"任务原文顶替"）。
            "task": task,
            "want_name": want_name,
            "reuse": reuse,
        }
        if not want_name and not reuse:
            # 口径 4：召唤即登记 —— 名字由框架发，不靠父记得给。
            kwargs["new"] = str(role)
        try:
            got = sink.roster_add(**kwargs)
        except Exception as exc:  # noqa: BLE001 —— 登记失败不许带走这次派活
            return {"name": "", "considered": True, "state": "missing",
                    "problem": f"{task_id}：名册登记没跑成：{type(exc).__name__}: {exc}"}
        got = got if isinstance(got, Mapping) else {}
        name = str(got.get("name") or "")
        raised = str(got.get("problem") or "")
        refusal_code = str(got.get("refusal_code") or "")
        # ---- 写口拒绝：任何拒绝都原样交回父决定 --------------------------------
        #
        # 不在 `want_name` 撞车时替父改主意：改发一个顺延的新名字继续登记、只把换名写进
        # note，那是换个地方继续静默改名。所以任何拒绝（不只是带码的那三种）都原样交回
        # 父决定：不重试、也不跑下面的兜底自愈。判据是"秘书那一侧有没有报 problem"而
        # 不是"有没有码"—— 自愈会把刚被拒的这一条当成"台账有、名册没有"的漏行，按一个
        # 新名字补进名册。
        #
        # 代价是"被拒的那一条这一次没有名字"—— 它由收口那一刻的收工兜底
        # （`Secretary.retire` 里的 `roster_repair`）负责补，两件事不是一个时刻：
        # 派活时不自作主张，收口时必须给得出名字。
        #
        # "给得出名字"的对象是定死的：没跑过的号（`outcome="refused"`）永远没有名字；
        # 真跑过的号（`status` 是终态、有 `ended_at`）会在自愈时补一个从未用过的新名字，
        # add 行带 `named_after_run` / `requested_name` / `refusal_code` 三格留痕
        # （被拒的那个名字不复用）。所以"交回父决定"的代价只是"这一次没有名字"，
        # 拒过但跑过的号不会永久无名。
        if raised:
            # 拒绝已在写口那一刻落成流水（`Secretary.roster_add` 的包装层，同一个
            # per-owner 临界区）；这里只把"记录没写成"那一句如实带出来
            # —— 回执的 `note` 是它唯一的落点。
            if str(got.get("note") or ""):
                note = (note + "；" if note else "") + str(got.get("note"))
            return {"name": name, "considered": True, "state": "missing",
                    "problem": (f"{task_id}：名册没登记"
                                f"（{refusal_code or 'refused'}）—— {raised}"),
                    "refusal_code": refusal_code, "note": note}
        reading = self._roster_files_reading(
            sink=sink, owner=str(owner), name=name, task_id=str(task_id),
            surface=str(got.get("surface") or ""))
        missing = [(label, cell) for key, label in self._ROSTER_FILES
                   for cell in (reading.get(key) or {},)
                   if cell.get("state") == "missing"]
        unknown = [(label, cell) for key, label in self._ROSTER_FILES
                   for cell in (reading.get(key) or {},)
                   if cell.get("state") == "unknown"]
        problem = ""
        if missing:
            problem = (f"{task_id}：名册三份没写全 —— " + "；".join(
                f"{label} {cell.get('file') or '（没有文件名）'} 没写成（{cell.get('why')}）"
                for label, cell in missing))
        elif unknown:
            problem = (f"{task_id}：名册读不到（unknown），这一处不许当成写成了 —— "
                       + "；".join(f"{label}：{cell.get('why')}"
                                   for label, cell in unknown))
        state = "missing" if missing else ("unknown" if unknown else "written")
        if not name:
            # 名字是名册项的身份：没有名字的那一项等于没登记（也绝不许两个子代理共用空名）。
            state = "missing"
            problem = (f"{task_id}：秘书没有发名（返回的 name 是空串）⇒ 名册项没有名字，"
                       "按没写成报" + (f"；{problem}" if problem else ""))
        # ---- 兜底自愈：把"台账有、名册没有"的其他代理行补上。
        #
        # 位置必须在 `roster_add` 之后：`_write_new_row` 先于 [5b] 把这一条子行写进台账，
        # 而它此刻还没进名册 —— 若自愈跑在登记之前，它会把这一条也当成"漏掉的"补一次，
        # 于是同一条子行在名册里出现两行（名字还会跳号）。
        # 放在登记之后、且只在"这一条真的写成"时跑 ⇒ 自愈只补历史漏行，不补刚被拒的这一条
        # （拒绝在上面那条早返里已经交回父了）。
        try:
            repair_named: list[dict[str, Any]] = []
            fixed, why, skipped = sink.roster_repair(  # type: ignore[attr-defined]
                owner=str(owner), named=repair_named)
        except Exception as exc:  # noqa: BLE001 —— 自愈失败不许带走这次派活
            fixed, why, skipped = 0, f"{type(exc).__name__}: {exc}", []
            repair_named = []
        if fixed:
            note = (note + "；" if note else "") + f"兜底自愈：补了 {fixed} 条当时没写进名册的代理行"
        # 补名必须说清"它当初点名要什么、现在叫什么" ——
        # 否则读回执的人只会看到"多了一行"，而名字在人的视角里像是丢了。
        named = repair_named
        if named:
            bits: list[str] = []
            for x in named[:5]:
                one = str(x.get("task_id") or "")
                if str(x.get("requested_name") or ""):
                    one += (f"（它点名的 {x.get('requested_name')} 被拒："
                            f"{x.get('refusal_code')}）⇒ 补成 {x.get('name')}")
                else:
                    one += f" ⇒ {x.get('name')}"
                bits.append(one)
            note = (note + "；" if note else "") + "补名：" + "、".join(bits)
        if skipped:
            # 读数：因为「还在飞（名册登记还没发生）」而跳过的号。不回这一格，
            # 「该补没补」在盘上就只剩一条谁也读不出来的沉默。
            note = (note + "；" if note else "") + (
                f"跳过 {len(skipped)} 条在飞（名册还没登记）：" + "、".join(skipped))
        elif why:
            note = (note + "；" if note else "") + f"兜底自愈没跑成（{why}）——不影响这一条的登记"
        return {"name": name, "considered": True, "problem": problem,
                "state": state, "note": note}

    @staticmethod
    def _roster_brief_fits(text: str) -> bool:
        """这一句进得了名册吗（口径只有一处：`secretary.BRIEF_MAX` 与它的单行要求）。"""
        from . import secretary as SEC

        one = str(text or "").strip()
        return len(one) <= SEC.BRIEF_MAX and "\n" not in one

    @staticmethod
    def _roster_brief_why(text: str) -> str:
        """那一句为什么进不了名册（给 `roster_note` 用的人话，不替秘书改它的判据）。"""
        from . import secretary as SEC

        one = str(text or "").strip()
        if "\n" in one:
            return "名册简介必须单行"
        return f"名册简介不得超过 {SEC.BRIEF_MAX} 字（读到 {len(one)} 字）"

    def _roster_files_reading(self, *, sink: Any, owner: str, name: str,
                              task_id: str, surface: str = "") -> dict[str, dict[str, str]]:
        """逐份读名册三份：这一趟的那一行在不在（`written` / `missing` / `unknown`）。

        读的路径与写的人取同一个根（`sink.root`）：换一个根去读，问的就不是同一件事了。
        读不到那三份路径（写入口没有盘上根）⇒ `unknown`，不是"没写成"。
        """
        from . import jsonlfile as JF
        from . import secretary as SEC

        root = getattr(sink, "root", None)
        if root is None:
            return {key: {"state": "unknown", "file": "", "why": "名册写入口没有盘上根"}
                    for key, _label in self._ROSTER_FILES}
        paths = {"roster": SEC.roster_path(root, owner),
                 "index": SEC.roster_index_path(root, owner),
                 "surfaces": SEC.surfaces_path(root, owner)}
        out: dict[str, dict[str, str]] = {}
        for key, _label in self._ROSTER_FILES:
            path = paths[key]
            try:
                rows, bad, state = JF.read_jsonl_state(path)
            except Exception as exc:  # noqa: BLE001 —— 读不成是 unknown，不是 missing
                out[key] = {"state": "unknown", "file": path.name,
                            "why": f"{type(exc).__name__}: {exc}"}
                continue
            if state == "unreadable":
                out[key] = {"state": "unknown", "file": path.name,
                            "why": (bad[0] if bad else "读不出来")}
                continue
            if any(self._roster_row_is_this_child(row, key=key, name=name,
                                                  task_id=task_id, surface=surface)
                   for row in rows):
                out[key] = {"state": "written", "file": path.name, "why": ""}
                continue
            out[key] = {"state": "missing", "file": path.name,
                        "why": ("文件里没有这一趟的那一行" if state != "absent"
                                else "这一趟没把它建出来")}
        return out

    @staticmethod
    def _roster_row_is_this_child(row: Mapping[str, Any], *, key: str, name: str,
                                  task_id: str, surface: str = "") -> bool:
        """这一行是不是"这个子代理的那一行"（三份的键不同：正文看 `add`、对照表看 `bind`）。

        正文与对照表只认 `task_id`：一个名字接过 N 件活是合法形态（复用），按名字认
        会把"同一个名字名下另一件活的那一行"读成"这一趟那一行写成了" —— 于是
        一件根本没登记的活被报成 `state="written"`，而"名册三份都读得到这一趟的那一行"
        这句话就变成了假话（`draft/151` 三-2；探针 H 的 `problem=""` 正是这么来的）。
        面池那一份反过来只按名字/槽位认：面的行本来就不带 `task_id`，它的键是
        `(name, slot)`。
        """
        # 这一处问的不是"轴"（是不是板项），而是"这是名册三份里哪一份的那一行"：
        # 名册正文只认 `add`、对照表只认 `bind`、面池按名字/槽位认。所以它就地读 `kind`，
        # 不走 `row_axis` —— 那一格回答的是任务台账的轴，不是名册事件的种类。
        kind = str(row.get("kind") or "")
        who = str(row.get("name") or "")
        if key == "surfaces":
            return bool((name and who == name)
                        or (surface and str(row.get("slot") or "") == str(surface)))
        if key == "roster" and kind != "add":
            return False
        if key == "index" and kind != "bind":
            return False
        return bool(task_id) and str(row.get("task_id") or "") == str(task_id)

    # ---------------------------------------------------------------- 工作项板（业主 2026-10-08 裁 A1=甲）
    #
    # 板就在 `tasks` 表上（七格见 `schema.Task` 的末尾）：`kind` 非空的行是板项，
    # `kind` 为空的行是"老行 / 纯实例行"。板读侧只认前者 —— 真机上还有另外两个模块
    # 直接写本表（`projects.py` / `runflow.py`，各两处；实测见 `draft/89` §5.4），
    # 它们不设 `kind` ⇒ 天然不进板；判据见 `tests/test_board_items.py`。
    #
    # "历史"在哪：状态是列（`item_state`），而"谁在第几步改的"在事件流里
    # （每次 `tx.upsert` 都落一条事件）—— 列给当前值，事件给来路，两处都要有。
    #
    # ## 信息型的板项"渲染即收口"（D12，业主 2026-10-27 逐字）
    #
    #   「所有 message 都是板项，我们要做的只是让 message 类的 seen=ack」
    #
    # 判据（业主口径）：「信息不该占用待办这个槽」。告知类的板项（时钟报醒 / 框架
    # 通报 / 留言）被消费在"读它"本身 —— 被拼进提示词那一拍就已经办完了，不该再要求
    # 模型写一次 `conductor.ack`。放宽它会留下一个具体形态的永久积压：真机
    # `projects/mp3-r3` 板项 12 条全部 `item_state=seen`、`conductor.ack` 调用 0 次，
    # 而销号闸（`conductor_retire_child`）读的是 `item_state != "done"` ⇒
    # 待机/在飞的代理永远清不掉（"板项没清"变成一道假拦）。
    #
    # 词表这一格不新造：`expects` 有两档（`ack` / `work`），信息型挂 `ack`，
    # 与 `item_close="acked"` 天然配对（`schema.Task.validate` 的交叉校验）。
    # 所以"seen 即 ack"落成：`item_state="done"` + `item_close="acked"`。
    #
    # 落点在 `mark_item_seen`（不是 `_set_item`）：`_set_item` 是纯状态机，
    # `ack_items` 对 `queued` 项"补记 seen"也走它 —— 那条路后面会自己写 done，
    # 在状态机里代收口会让它读到"已经到过 done"而拒（`ack_items` 的补记支）。
    # 而 `mark_item_seen` 是唯一的"被渲染"入口（两处渲染点都只经它）。

    def _board_rows(self) -> list[dict]:
        """板项（`kind` 非空的行）。读不成 ⇒ 抛（调用方折成三态，不许折成"板上没事"）。"""
        return [r for r in self._tasks() if self._is_board_item(r)]

    def open_item(self, *, kind: str, role: str, expects: str, action: str = "",
                  summary: str = "", called_by: str = "", parent_task_id: str | None = None,
                  depth: int = 1, keep_alive: bool = False, input_key: str = "",
                  recipient_instance: str = "") -> str:
        """开一行工作项（`item_state="queued"`）并返回 `task_id`（它就是 `item_id`）。

        为什么开项也走 `_write_new_row`：那一处是"取号 + 建行"的唯一临界区（并发下
        "先算号、再写行"会撞号，见它的 docstring），而且它负责把落盘行补齐到全字段
        （I-9 要求键集与键序只有一处口径）。

        `action` 的约定：`kind="delegation"` 给真正的动作名；其余三种
        （message / report / notice）没有"动作"这回事 ⇒ 用 kind 本身当哨兵值
        （`Task.validate` 要求 `action` 非空，而空串会让这一行读起来像"一次没有动作的召唤"）。

        ## `recipient_instance`：这一项投给哪个实例（K9）

        「义务属于谁」在改前只有角色地址（`role`），于是"哪一趟接"只能靠
        "唯一在飞 / 最近开始"去挑。现在板项行自己带收件实例（`Task.instance` 那一格：
        对板项而言它的含义就是收件地址），投递按它定向；空串 = 角色地址（该角色
        任一实例都能领，`open_items_for` 读得到）。地址是本行的一部分，不再从键里猜。
        """
        # 幂等键（D-07）：`clock:<timer_id>` 只该有一行。真机证据是两条 notice 的
        # input_key 完全相同、相隔 1 秒（到点投递被两个线程各投一次）。进程内那一半由
        # `clock._FIRE_LOCK` 挡住，这一层是跨进程的兜底：同键已有行 ⇒ 复用，不新建。
        # 只对 `clock:` 前缀做：那是时钟投递专用的键空间，语义就是"同一条计时器只投一次"；
        # 别的 caller 传 input_key 还没有这条约束，一并去重会改掉它们已有的行为。
        if str(input_key or "").startswith("clock:"):
            existing = next((r for r in self._tasks()
                             if str(r.get("input_key") or "") == str(input_key)), None)
            if existing is not None:
                return str(existing.get("task_id") or "")
        row = self._item_row(kind=kind, role=role, expects=expects, action=action,
                             summary=summary, called_by=called_by,
                             parent_task_id=parent_task_id, depth=depth,
                             keep_alive=keep_alive, input_key=input_key,
                             recipient_instance=recipient_instance)
        item_id = self._write_new_row(row, note=f"item:{kind}")
        # ---- 「接到消息就是叫醒」（业主 2026-10-29）
        #
        # 计时器到点与同伴发消息走到的是同一条路：都在收件人名下落一条板项
        # （`kind="notice"` / `kind="message"`）。业主的口径是——
        # 「这和计时器到点时给代理发消息唤醒一样，静默的唤醒就是接到消息被唤醒」，
        # 所以"叫醒"不是另一个动作，它就是这一刻：信落盘了，收件人得有人读。
        #
        # 这一层只做判定与留痕（读收件人那一行、决定要不要跑它），
        # 真正把循环跑起来的那一步由 `self.resume_runner` 接（默认没接 ⇒ 读数写清
        # "执行侧未接线"，不许当"它会读到"）。
        self._ensure_consumer(item_id=item_id, kind=kind,
                              recipient=str(parent_task_id or ""))
        return item_id

    def _ensure_consumer(self, *, item_id: str, kind: str, recipient: str) -> dict[str, Any]:
        """板项落盘之后：收件人得有人读它（静默的唤醒 = 接到消息）。

        三态读数 `{"attempted","started","reason"}` 写进 `self.last_consumer_reading`
        供调用点与判据读；从不抛（叫不醒不许带走这次投递）。

        判定次序（与业主 2026-10-29 的两条裁定一一对应）：
        ```text
        ① kind 不在白名单（message / notice）  ⇒ attempted=False（"板上有活"不是"来信"）
        ② 收件人空                            ⇒ attempted=False（公共频道/广播）
        ③ 台账读不成 / 没有那一行               ⇒ attempted=True + 理由
        ④ 已销号                              ⇒ 不跑它（"已销号是彻底没有了"；寻址那关已拦，这里双保险）
        ⑤ 还在跑（status ∈ UNFINISHED_STATUSES）⇒ 不动它（下一拍它自己读到）
        ⑥ 终态且未销号                          ⇒ 该跑起来：status 由终态改回 running，
                                                 交给 `self.resume_runner`（同号、不新建行）
        ```
        """
        out: dict[str, Any] = {"attempted": False, "started": False, "reason": "",
                               "item_id": item_id, "recipient": recipient}
        try:
            if str(kind or "") not in ("message", "notice"):
                out["reason"] = f"kind={kind} 不是来信（只有 message / notice 才算叫醒）"
                return out
            if not recipient:
                out["reason"] = "没有收件人（公共频道/广播）⇒ 没有要跑的人"
                return out
            out["attempted"] = True
            row = self._task(recipient) or {}
            if not row:
                out["reason"] = f"{recipient} 在台账里没有那一行 ⇒ 它不存在（不是'已叫醒'）"
                return out
            # 已销号 ⇒ 不跑它（"已销号是彻底没有了"）；销号名单读不全 ⇒ 也不跑
            # （`unknown`，fail-closed：业主 2026-10-31）。
            # 这一格是投递路上的双保险：`parent` 由 `retired_reading_of` 自己从台账那一行
            # 取（多一次 0.2 ms 的台账读，换掉"调用方必须知道销号名单按父存"这条隐含约定）。
            # 判据 `test_a_message_runs_a_silent_agent.py` 把这一格读的布尔口打桩成单参数
            # lambda，所以 `retired_verdict` 在 `parent` 为空时只传号。
            verdict = self.retired_verdict(recipient)
            if verdict == "retired":
                out["reason"] = (f"{recipient} 已销号 ⇒ 彻底没有了（业主 2026-10-29）。"
                                 "投递本应被秘书拦；要它干活就重新派一个")
                return out
            if verdict == "unknown":
                out["reason"] = (f"{recipient} 的销号名单读不全（{self._retired_reason()}）⇒ "
                                 "不叫它（fail-closed）；信已经落在它收件箱里，等这一格"
                                 "读得出来再叫")
                return out
            status = str(row.get("status") or "")
            if status in UNFINISHED_STATUSES:
                out["reason"] = f"{recipient} 还在跑（status={status}）⇒ 板项它下一拍自己读到"
                return out
            role = str(row.get("role") or "")
            runner = getattr(self, "resume_runner", None)
            if not callable(runner):
                # 2026-10-29 业主：「静默……随叫随到」「静默的唤醒就是接到消息被唤醒」。
                # 规则是框架的规则；但默认接线这一步先按住，理由是实测到一条时序竞态：
                # 一旦 `open_item` 立刻把收件人改成 running 并起后台线程，
                # "开一条 message ⇒ 马上销它"这类既有流程会读到 running（拒），
                # 而线程落定之后又读到 silent（放行）—— 同一笔动作两个结果，
                # 实测 `test_ack_is_the_hand_and_retire_needs_a_clean_board` 时红时绿。
                # 要开默认接线，先得有"已叫起但还没开始跑"这一格（pending wake），
                # 让销号读到的是确定的一档，而不是跟线程抢时序。
                # 在那之前：真实装配（`host.wired_conductor`）已经接上执行侧，
                # 替身/判据构造保持"未接线"，读数写清。
                out["reason"] = (f"{recipient} 已完成（status={status}）⇒ 该把它跑起来，"
                                 "但这一趟没有接执行侧（`resume_runner` 未接线）")
                return out
            try:
                runner(recipient, role=role, item_id=item_id, kind=kind,
                       previous_status=status)
            except Exception as exc:  # noqa: BLE001
                out["reason"] = f"{recipient} 的执行侧起不来（{type(exc).__name__}: {exc}）"
                return out
            out["started"] = True
            out["reason"] = (f"{recipient} 已按同号继续（status 由 {status} 改回 running，"
                             f"因为收到了 {kind} {item_id}）")
            return out
        except Exception as exc:  # noqa: BLE001 —— 判定自己坏了也是"没叫成"
            out["reason"] = f"叫醒判定没跑成（{type(exc).__name__}: {exc}）"
            return out
        finally:
            self.last_consumer_reading = dict(out)

    def resume_dispatched(self, task_id: str, *, role: str = "", item_id: str = "",
                          kind: str = "", previous_status: str = "") -> dict[str, Any]:
        """把一条已终态但未销号的代理行按同一号继续跑起来（业主 2026-10-29）。

        这是"静默的唤醒 = 接到消息"的执行侧：板项已经在它名下（`open_item` 落的），
        这里只做两件事 —— 把 status 由终态改回 running，用既有派活下半
        （`backend.call(..., task_id=同号)` + `_end_from_payload`）在后台把它跑起来。
        不新建 tasks 行、不动名册与名字（业主：「它的号还在就一直用」）。

        返回 `{"started","role","task_id","item_id","reason"}`；从不抛。
        """
        out: dict[str, Any] = {"started": False, "task_id": task_id, "role": str(role or ""),
                              "item_id": str(item_id or ""), "reason": ""}
        try:
            row = self._task(task_id) or {}
            if not row:
                out["reason"] = f"{task_id} 在台账里没有那一行 ⇒ 没得跑"
                return out
            role = str(role or row.get("role") or "")
            upd = dict(row)
            upd["status"] = "running"
            upd["outcome"] = None
            upd["ended_at"] = None
            task = S.Task(**{k: v for k, v in upd.items()
                             if k in S.Task.__dataclass_fields__})
            task.validate()
            with self.store.tx("tasks", actor="conductor",
                               note=f"resume:{kind or '-'}:{item_id or '-'}") as tx:
                tx.upsert("tasks", task.to_dict(),
                          note=f"resume:{kind or '-'}:{item_id or '-'}")
        except Exception as exc:  # noqa: BLE001 —— 改不回 running 就不假装跑起来了
            out["reason"] = f"{task_id} 改不回 running（{type(exc).__name__}: {exc}）"
            return out

        def _run() -> None:
            try:
                # `token` 必须跟着走：`LlmBackend.call` 把它列为必填关键字参数（取消信号
                # 一路传到子循环与每一次出网）。改前这里只传 `task_id` ⇒ 研究跑那条
                # LlmBackend 一旦接上执行侧，第一次唤醒就落
                # `TypeError: LlmBackend.call() missing 1 required keyword-only argument: 'token'`
                # （2026-11-15 CC4 缺陷 1 的接线实测：`started=True` 但 owner 行 failed）。
                # 这个 token 就是主控自己的那一个：唤醒是同一条链上的继续，共用一个取消信号。
                raw = self.backend.call(role, "", {}, token=self.token, task_id=task_id)
                res = self._end_from_payload(task_id, raw)
                # ---- 花销写回：唤醒走的是"直接 backend.call + _end_from_payload"这条
                # 短路，不经过 `summon_run` 的 `_charge_and_settle`。LlmBackend 的每一笔
                # 真调用已经把行写进了 `usage_ledger`，但 `tasks.tokens/usd` 只在
                # `_charge_and_settle` 里从账本抄回 ⇒ 不补这一步，研究跑一旦接上执行侧，
                # `verify` 的 `usage_task_total_mismatch` 立刻红（2026-11-16 实测：
                # ledger 5.4e-05 / tasks 4.8e-05）。这里只抄账本累计值，不另记一笔
                # （召唤级结算行已由 LlmSeam 的调用行走过；再 charge 一次就是双记）。
                try:
                    self._set_usage(task_id, self.meter.tokens_for(task_id),
                                    self.meter.usd_for(task_id))
                except Exception as exc:  # noqa: BLE001 —— 记账写回失败不许把一次跑完的唤醒翻成失败
                    self._log(f"唤醒后的花销写回失败（{task_id}）：{type(exc).__name__}: {exc}",
                              task_id=task_id)
            except Exception as exc:  # noqa: BLE001 —— 跑坏了要落终态，不许僵尸 running
                self._end(task_id, status="failed", outcome="failed",
                          error=f"{type(exc).__name__}: {exc}",
                          detail="被一条来信叫起来之后跑坏了")

        # 上下文必须跟着线程走（2026-10-29 第 18 轮，G8 抓到的空归属）：被叫醒的代理在
        # 这个后台线程里跑 `backend.call` / `_end_from_payload`，而 `run_as` / `calling_as`
        # 是 contextvar —— 不起一份拷贝，它在新线程里读到的是空的，落盘的行就没有归属。
        # 与 `start_summon` 同一个做法（同一个坑在那边已经踩过一次）。
        _ctx = contextvars.copy_context()
        threading.Thread(target=_ctx.run, args=(_run,),
                         name=f"agentflow-resume-{task_id}",
                         daemon=True).start()
        out["started"] = True
        out["reason"] = (f"{task_id} 已按同号继续（status 由 "
                         f"{previous_status or '终态'} 改回 running，因为收到了 "
                         f"{kind or '来信'} {item_id or '-'}）")
        return out

    def wake_on_lifeline(self, task_id: str) -> dict[str, Any]:
        """兜底表被打掉时把那个代理叫起来（同一个号继续）。

        口径（业主 2026-10-29）：兜底表的作用是"保证一个代理不是真的死了、接住所有的事件"。
        已销号 ⇒ 叫不醒（"彻底没有了"）；销号名单读不全 ⇒ 也不叫（`unknown`，交人看）——
        2026-10-31 业主裁定的方向是 fail-closed：这一格读不出它销过没有，就不把"叫醒"
        这件事当结论（改前那一档被折成"没销号"⇒ 已销号的号照样被叫起来）。
        """
        tid = str(task_id or "").strip()
        if not tid:
            return {"started": False, "task_id": "", "reason": "没有台账号 ⇒ 叫不起来"}
        # 2026-10-29 实测的自我唤醒：兜底表是在这一趟循环里被打掉的，这时再
        # `resume_dispatched` 就会另起一个同号循环 —— 两个自己互相喂事件，直到把进程挂死
        # （`test_timers_and_handoff_semantics` 超时那次）。它自己在跑 ⇒ 不叫它：
        # 那条消息本来就会进到它自己的收件箱。
        try:
            row = next((r for r in self._tasks() if str(r.get("task_id") or "") == tid), None)
        except Exception:  # noqa: BLE001 - 读不成不拦（宁可叫它）
            row = None
        # 已销号 ⇒ 叫不醒（"彻底没有了"）；销号名单读不全 ⇒ 也不叫（fail-closed，
        # 业主 2026-10-31）。销号名单按父存，`parent` 就取刚读到的这一行；
        # 台账读不成时留空，`retired_reading_of` 会退回"自己读 / 扫名册目录"。
        verdict = self.retired_verdict(tid, parent=str((row or {}).get("parent_task_id") or ""))
        if verdict == "retired":
            return {"started": False, "task_id": tid,
                    "reason": f"{tid} 已销号 ⇒ 彻底没有了，叫不醒（要它干活就重新派一个）"}
        if verdict == "unknown":
            return {"started": False, "task_id": tid,
                    "reason": (f"{tid} 的销号名单读不全（{self._retired_reason()}）⇒ 不叫"
                               "（fail-closed）；这一格既不是「已销号」也不是「没销号」")}
        if str((row or {}).get("status") or "") in UNFINISHED_STATUSES:
            return {"started": False, "task_id": tid,
                    "reason": (f"{tid} 它自己在跑（status={(row or {}).get('status')}）⇒ "
                               "不另起一个同号循环；那条消息会进它自己的收件箱")}
        runner = getattr(self, "resume_runner", None)
        if not callable(runner):
            return {"started": False, "task_id": tid,
                    "reason": "这一趟没有接执行侧（resume_runner 未接线）"}
        try:
            got = runner(tid, kind="lifeline")
        except Exception as exc:  # noqa: BLE001 - 叫不醒要如实回，不许炸掉投递
            return {"started": False, "task_id": tid,
                    "reason": f"叫醒失败（{type(exc).__name__}: {exc}）"}
        out = dict(got) if isinstance(got, Mapping) else {}
        out.setdefault("started", False)
        out["task_id"] = tid
        return out

    def _retired_trusted_shard(self, task_id: str, parent: str = "") -> str:
        """这个号"该读哪一份销号名单"——可信的那一份（名单按父分文件）。

        次序：调用方给的父 → 台账那一行的 `parent_task_id`。两者都没有 ⇒ `""`：
        这时只能扫名册目录，而扫出来的分片名不算可信（"这一份里没有它"证明不了
        "别的分片里也没有它"，`draft/145` R19/B1）。

        为什么"哪个分片"与"信不信这个分片名"要分开（§3.1 注 1）：`absent` 这一档只在
        分片名可信时才是"还没人销过号"这条查过的事实；分片名是猜的 / 扫来的时，
        "文件不存在"什么都证明不了。这一格必须由调用方显式说清 ——
        `retired_ledger(..., trusted_shard=...)`，不在这里猜。
        """
        pid = str(parent or "").strip()
        if pid:
            return pid
        try:
            row = self._task(str(task_id or "")) or {}
        except Exception:  # noqa: BLE001 —— 读不到台账那一行就不拿它当父（往下走扫目录）
            row = {}
        return str(row.get("parent_task_id") or "").strip()

    def _retired_shards_on_disk(self) -> tuple[list[str], str]:
        """扫名册目录里所有 `<父>-retired.jsonl` ⇒ `(分片名, 扫不成时的理由)`。

        为什么最后要扫全目录（R19）：一个号可能被记在别的父的分片里（分片错配 /
        台账那一行的父被改过 / 老工作区的盘）。改前"给了 `parent` 就只问那一份"
        ⇒ 一次错配就是永久盲区：`state=absent`、`checked=True`、回执一个字不提读不全。

        第二格是三态纪律：扫不成 ≠ 一份都没有。`([], 理由)` 是"没查成"
        （`draft/145` B2/R20：名册目录本身读不成 / 被占成一个同名文件）；
        只有"目录读得出来、里面确实没有一份"才是 `([], "")`（一条查过的事实）。
        """
        try:
            root = str(getattr(self.store, "root", "") or "")
            if not root:
                return [], ""
            folder = Path(root).joinpath(*SEC.ROSTER_DIR)
            if not folder.exists():          # 还没人派过活：合法初态，不是"没查成"
                return [], ""
            suffix = "-retired.jsonl"
            return sorted(p.name[: -len(suffix)] for p in folder.iterdir()
                          if p.is_file() and p.name.endswith(suffix)), ""
        except Exception as exc:  # noqa: BLE001 —— 扫不动是"没查成"（禁止折成空表）
            return [], f"名册目录读不成（{type(exc).__name__}: {exc}）"

    @staticmethod
    def _retired_rows_of(got: Any) -> tuple[list[Any], list[str]]:
        """把读口的返回值归一成 `(行, 坏行)`（只归一形状，不解释语义）。

        四种形状（它们都是"某处真的这么写过"的形态，不是设想）：

        ```text
        ① (rows, bad)         真身 `Secretary.retired_names(owner)` 的返回
        ② [行 / 名字 / 号 …]   只说"有这些"的序列（`list` 或 `tuple`）
        ③ {号或名字: 理由}     Mapping：键既当 task_id 也当 name（两种键都认）
        ④ 单行 / 单个名字      也收（一个对象不包在表里）
        ```
        """
        if got is None:
            return [], []
        if isinstance(got, Mapping):
            return [{"task_id": str(k), "name": str(k)} for k in got], []
        if isinstance(got, (list, tuple, set, frozenset)):
            items = list(got)
            if (len(items) == 2
                    and isinstance(items[0], (list, tuple, set, frozenset))
                    and isinstance(items[1], (list, tuple, set, frozenset))):
                return list(items[0]), [str(x) for x in items[1]]
            return items, []
        return [got], []

    def _retired_names_of(self, holder: Any, owner: str) -> tuple[list[Any], list[str]]:
        """销号名单 → `(行, 坏行)`（读口适配那一层：形状由 :meth:`_retired_rows_of` 归一）。

        ## 为什么这一层必须存在（2026-10-31 实测的不可逆缺陷）

        改前那一句是 `got = holder() if callable(holder) else holder` —— 它假定
        `retired_names` 是无参的。真身是
        `secretary.py: def retired_names(self, owner: str) -> tuple[list[dict], list[str]]`：
        无参调 ⇒ `TypeError` ⇒ 被"读不到就当没销号"的 `except` 吞掉 ⇒ 闸门在真秘书下
        永远返回 False ⇒ 已销号的号被判 resume、落 `wake:` 痕、被叫醒两次
        （`draft/143` §7.3 逐字读数）。签名与返回形状是两处独立的错，任一都够让它失效。

        所以这里先看签名再调（要 `owner` 就传、不要就不传），`inspect` 取不到签名
        （内置 / C 实现）或两种调法各错一次时，两个方向都试一次；返回的形状交给
        `_retired_rows_of`。读口自己抛异常不在这里吞：调用方（`retired_reading_of`）
        要把它落成"没查成"，而不是"没有销号"。
        """
        if not callable(holder):
            return self._retired_rows_of(holder)
        takes_owner = True
        try:
            params = inspect.signature(holder).parameters
        except (TypeError, ValueError):  # 取不到签名 ⇒ 当它要（下面还会再试另一边）
            params = None
        if params is not None:
            takes_owner = any(p.kind in (inspect.Parameter.POSITIONAL_ONLY,
                                         inspect.Parameter.POSITIONAL_OR_KEYWORD,
                                         inspect.Parameter.VAR_POSITIONAL)
                              for p in params.values())
        first = (owner,) if takes_owner else ()
        other = () if takes_owner else (owner,)
        try:
            return self._retired_rows_of(holder(*first))
        except TypeError:
            return self._retired_rows_of(holder(*other))

    @staticmethod
    def _retired_row_keys(row: Any) -> set[str]:
        """一行销号名单里"可指的键"：`task_id` 与 `name` 两个都认。

        为什么两个都要认：真身那一行是
        `{"owner","name","task_id","role","at","reason","branch"}` —— `name` 是名册名
        （`D1`）、`task_id` 是台账号（`t-000002`）。调用点手里有时只有号、有时只有名；
        只认一个键的那一半会静默地永远不命中，而"永远不命中"在"已销号"这一格上就是
        "已销号却仍会被叫醒"（不可逆）。
        """
        if isinstance(row, Mapping):
            return {str(row.get("task_id") or "").strip(),
                    str(row.get("name") or "").strip()} - {""}
        return {str(row or "").strip()} - {""}

    @staticmethod
    def _retired_gaps_of(rows: Any, owner: str) -> tuple[list[str], list[dict[str, Any]]]:
        """替身读口那一档的"行认不出来"（真身由 `Secretary.retired_ledger` 给）。

        判据只有一份实现（`secretary.retired_row_gaps`）：替身那四种壳（`(rows, bad)` /
        `list` / 无参可调 / 老 `{号: 理由}` dict）走的是同一条口径 —— 真身严、替身松
        等于给下一份判据留一条"换个壳就绿"的路。
        """
        return SEC.retired_row_gaps(rows, owner)

    def _retired_names_of_key(self, who: str, task_id: str) -> tuple[set[str], bool]:
        """这一号在 `who` 这份名册里叫什么 ⇒ `(名字集合, 查成了没有)`。

        为什么需要它：一份销号行是按名册名字写的（`Secretary.retire` 先按名字
        `_resolve`，再落 `{"name","task_id",…}`）。所以"少了 `task_id`、只剩名字"那一行
        能不能是这一号，取决于这一号叫什么 —— 不知道名字就只能说"不知道"。

        `checked=False`（名册 / 对照表读不出来）时不能排除任何一行，调用方按 fail-closed
        处理。名册正文与对照表都读（两处都可能缺行：H7 的半份登记、H17 的 `unrostered`），
        任一处读不全 ⇒ `checked=False`。
        """
        sec = getattr(self, "secretary", None)
        names: set[str] = set()
        checked = True
        got_any = False
        for reader in ("roster_rows", "roster_index"):
            fn = getattr(sec, reader, None)
            if not callable(fn):
                continue
            got_any = True
            try:
                rows, bad = fn(who)
            except Exception:  # noqa: BLE001 —— 读不成 ⇒ 不能排除
                return set(), False
            if bad:
                return set(), False
            for row in rows or ():
                row = row if isinstance(row, Mapping) else {}
                if str(row.get("task_id") or "") == str(task_id) or \
                        str(row.get("first_task_id") or "") == str(task_id):
                    name = str(row.get("name") or "").strip()
                    if name:
                        names.add(name)
        return names, (checked and got_any)

    def _retired_gap_may_be_key(self, gap: Mapping[str, Any], *, who: str,
                                tid: str, want: str) -> bool:
        """这一行"认不出来"的记录有没有可能是这一号 / 这一名（`draft/145` §3.1）。

        为什么逐个键判，而不是"一片里有一行认不出来就整片不算数"：销号行是按名册名字写
        的，所以一行"少了 `task_id`、名字是 `D1`"的记录可能是 `D1` 那一号，不可能是
        别的号 —— 把整片都判成读不全，会让同一个父名下每一个还活着的号都叫不醒
        （那是另一种不可逆：`draft/145` §3.4 的反真空那一半）。

        判法（只往前排除，排不掉就是"可能是"）：
        ```text
        两个键都用不了（都空）        ⇒ 可能是任何号 ⇒ True
        号对得上                      ⇒ True（那一行可能就是这一号，只是没读全）
        名对得上（调用方给的 / 名册里换出来的）⇒ True
        名用不了、号用不了            ⇒ True
        名用不了、号对不上            ⇒ False（号已经把它排除掉了）
        名对不上、而这一号的名字读不出来 ⇒ True（不能排除）
        名对不上、这一号的名字读出来了   ⇒ False
        ```
        """
        row_tid = str(gap.get("task_id") or "").strip()
        row_name = str(gap.get("name") or "").strip()
        if not row_tid and not row_name:
            return True
        if row_tid and tid and row_tid == tid:
            return True
        names, names_checked = self._retired_names_of_key(who, tid) if tid else (set(), False)
        keys = (names | {want}) - {""}
        if row_name and row_name in keys:
            return True
        if not row_name:
            return not row_tid
        return not names_checked

    def _read_retired_shard(self, who: str, *, trusted: bool) -> dict[str, Any]:
        """读一份销号名单 ⇒ `{checked,state,rows,bad,unattributable,
        unattributable_rows,file_problem,reason}`。

        读口从两个里挑：秘书的 :meth:`Secretary.retired_ledger`（四态 ＋ 逐行读数，
        分片可信度显式传进去）优先；只有 `retired_names` 的替身退回老读法（那一档没有
        `state`，逐行读数由 :meth:`_retired_gaps_of` 现算）。

        `file_problem` 是"这一份名单自己没查成"（整份读不出来 / 分片名不可信）：
        那一档对任何号都是"不知道"；而"某一行的内容认不出来"只对"可能是它"的号
        才是"不知道"（那是 `unattributable_rows`，判法见 :meth:`_retired_gap_may_be_key`）。

        读口自己抛异常不在这里吞：调用方要把它落成"没查成"，而不是"没有销号"。
        """
        sec = getattr(self, "secretary", None)
        ledger = getattr(sec, "retired_ledger", None)
        if callable(ledger):
            raw = ledger(who, trusted_shard=trusted)
            got = dict(raw) if isinstance(raw, Mapping) else {}
            state = str(got.get("state") or "")
            bad = [str(x) for x in (got.get("bad") or [])]
            unattr = [str(x) for x in (got.get("unattributable") or [])]
            reason = str(got.get("reason") or "")
            file_problem = ""
            if state == "unreadable":
                file_problem = reason or "整份读不出来（这一格不是「没有销号」）"
            elif not bad and not unattr and got.get("checked") is False:
                file_problem = reason or "这一份销号名单没查成"
            return {"checked": got.get("checked") is not False,
                    "state": state,
                    "rows": list(got.get("rows") or []),
                    "bad": bad,
                    "unattributable": unattr,
                    "unattributable_rows": [dict(x) for x in
                                            (got.get("unattributable_rows") or [])
                                            if isinstance(x, Mapping)],
                    "file_problem": file_problem,
                    "reason": reason}
        holder = getattr(sec, "retired_names", None)
        rows, bads = self._retired_names_of(holder, who)
        messages, gaps = self._retired_gaps_of(rows, who)
        return {"checked": not (bads or messages),
                "state": "ok" if rows else "empty",
                "rows": list(rows),
                "bad": [str(x) for x in bads],
                "unattributable": messages,
                "unattributable_rows": gaps,
                "file_problem": "",
                "reason": ""}

    def retired_reading_of(self, task_id: str, *, parent: str = "",
                           name: str = "") -> dict[str, Any]:
        """这个号是不是已销号：四态读数（`checked` / `retired` / `bad` / `reason`）。

        返回 `{"checked","retired","task_id","name","owners","rows","bad",
        "unattributable","unknown_reasons","state","matched_by","matched_owner","reason"}`：

        - `retired`：读到了匹配行才是真（读到就是读到，同一份名单里的坏行不改变它）；
        - `checked`：这一份名单的否定结论（「这一号没销过」）信不信得过。
          读不全（坏行 / 认不出来的行 / 分片不可信 / 扫不成）/ 读口抛了 / 没有秘书 /
          没有这个读口 ⇒ `False`，而 `reason` 如实写是哪一档；
        - `unknown_reasons`：这一号自己的否定结论信不信得过（非空 ⇒ 不许说"没销号"）。
          它比 `checked` 窄：一片里另有一行"整行读不出来"时，那一行进 `bad`、回执逐字
          带着，但不冻结别的号；只有"可能是这一号"的读不全（整份读不成 / 分片不可信 /
          扫不成 / 认不出来的行按名册名字换算出可能命中它）才进这一格。
        - `bad`：坏行原样带着（`[第 1 行读不出来（…）]`），不折成"没有销号"；
        - `unattributable`：行读得出来但认不出是哪一号 / 哪一名（少 `task_id` /
          少 `name` / 类型不对 / `owner` 与分片不符）—— 这一档改前不存在，于是
          R8/R10/R11/R19 全被读成"这一份里没有它"；
        - `owners`：问过哪几份名单（先问可信分片，读不到匹配行时回溯扫目录）；
        - `matched_by` / `matched_owner`：命中的是哪个键（`task_id` / `name`）、在哪一份名单里。

        ## 分片（R19）：先读可信的那一份，读不到就扫目录回溯
        这份名单按父分文件（`out/roster/<父>-retired.jsonl`），而"哪个父"来自台账那一行
        的 `parent_task_id`。分片名可信时，文件不存在就是"还没人销过号"（`checked=True`）；
        分片名是扫来的 / 猜的时，那一档是"读不全"。两种情况都要再扫一遍目录：
        一行内容完全正确、只是落在别的父的分片里时，只问那一份会读成"没销号"。

        ## 方向（2026-10-31 业主裁定：fail-closed）
        这一份读数本身只回答"读到了没有 / 查成了没有"，不替动作侧决定叫不叫；
        动作侧看的是 :meth:`retired_verdict` 那个三态，`unknown` ⇒ 不叫醒。
        `checked=False` 再也不等于"没销号"：它是"这一格读不出来"。
        """
        tid = str(task_id or "").strip()
        want = str(name or "").strip()
        out: dict[str, Any] = {"checked": False, "retired": False, "task_id": tid,
                               "name": want, "owners": [], "rows": 0, "bad": [],
                               "unattributable": [], "unknown_reasons": [], "state": "",
                               "matched_by": "", "matched_owner": "", "reason": ""}
        self.last_retired_reading = out
        if not tid and not want:
            out.update(checked=True, reason="没有号也没有名字 ⇒ 没有可销的对象（查过了）")
            return out
        sec = getattr(self, "secretary", None)
        if sec is None:
            # 没有秘书 ≠ 读不全：销号名单只有一个写者（`Secretary.retire`），这一趟连
            # 秘书都没接 ⇒ 这个工作区里没有能销号的机制，也就没有"读不出来的销号"。
            # 折成 `unknown` 会让"没接秘书的装配"从此叫不醒任何人（另一种不可逆），
            # 而既有判据（`test_the_block_table_wakes_one_by_one` 等）钉的正是"没秘书时
            # 该叫得起来"。真正该 fail-closed 的是"有读口、但这份名单读不全"。
            out.update(checked=True,
                       reason="这一趟没有接秘书 ⇒ 没有销号名单可读（也没有人能写它）")
            return out
        ledger = getattr(sec, "retired_ledger", None)
        holder = getattr(sec, "retired_names", None)
        if not callable(ledger) and holder is None:
            out["reason"] = (f"{type(sec).__name__} 没有 retired_ledger / retired_names "
                             "这个读口 ⇒ 读不到销号名单（不是「没销号」）")
            out["unknown_reasons"] = [f"销号名单读不全 ⇒ {out['reason']}"]
            return out
        wanted = {tid, want} - {""}
        split = callable(ledger) or callable(holder)   # 真读口按父分文件；替身是一整份
        trusted = self._retired_trusted_shard(tid, parent) if split else ""
        plan: list[tuple[str, bool]] = ([(trusted, True)] if trusted else []) \
            if split else [("", False)]
        asked: list[str] = []
        notes: list[tuple[str, str, list[str]]] = []       # (坏行 / 认不出来, 分片, 逐条)
        files: list[tuple[str, str]] = []                  # (分片, 这一份自己没查成)
        gaps_all: list[tuple[str, dict[str, Any]]] = []    # (分片, 逐行读数)
        states: list[str] = []
        rows_total = 0

        def _absorb(who: str, got: dict[str, Any]) -> None:
            """把一份分片的读数收进总读数（行照读、问题分档记）。"""
            nonlocal rows_total
            asked.append(who)
            states.append(str(got.get("state") or ""))
            rows = list(got.get("rows") or [])
            rows_total += len(rows)
            bads = [str(x) for x in (got.get("bad") or [])]
            unattr = [str(x) for x in (got.get("unattributable") or [])]
            if bads:
                notes.append(("bad", who, bads))
            if unattr:
                notes.append(("unattributable", who, unattr))
            file_problem = str(got.get("file_problem") or "")
            if file_problem:
                files.append((who, file_problem))
            for gap in (got.get("unattributable_rows") or []):
                if isinstance(gap, Mapping):
                    gaps_all.append((who, dict(gap)))
            for row in rows:
                hit = self._retired_row_keys(row) & wanted
                if not hit:
                    continue
                out["retired"] = True
                out["matched_by"] = "、".join(sorted(hit))
                out["matched_owner"] = who

        def _read_one(who: str, trust: bool) -> None:
            try:
                got = self._read_retired_shard(who, trusted=trust)
            except Exception as exc:  # noqa: BLE001 —— 读口自己炸了也是"没查成"
                got = {"checked": False, "state": "unreadable", "rows": [],
                       "bad": [], "unattributable": [], "unattributable_rows": [],
                       "file_problem": f"读不出来（{type(exc).__name__}: {exc}）",
                       "reason": ""}
            _absorb(who, got)

        for who, trust in plan:
            _read_one(who, trust)
        scan_error = ""
        if split and not out["retired"]:
            # R19 的回溯：可信分片里没有它 ⇒ 还要看别的父的分片（那些分片名不可信，
            # 所以 `trusted_shard=False`：它们的 `absent` 不算"查过了、没有"）。
            shards, scan_error = self._retired_shards_on_disk()
            for who in shards:
                if who in asked:
                    continue
                _read_one(who, False)
        out["owners"] = list(asked)
        out["rows"] = rows_total
        multi = len(asked) > 1
        bad: list[str] = []
        unattributable: list[str] = []
        for kind, who, msgs in notes:
            for msg in msgs:
                text = msg if (not multi or not who) else f"{who}：{msg}"
                (bad if kind == "bad" else unattributable).append(text)
        if scan_error:
            bad.append(scan_error)
        out["bad"] = bad
        out["unattributable"] = unattributable
        for one in ("unreadable", "ok", "empty", "absent"):
            if one in states:
                out["state"] = one
                break
        problems = bad + unattributable
        out["checked"] = not problems          # 整片口径（§3.1）
        # ---- 这一号自己的否定结论（`unknown_reasons` 非空 ⇒ 不许说"没销号"）----
        #
        # 两档要分开（否则要么"一个坏字节冻结整棵树"，要么"认不出来的行放走已销号"）：
        # · 文件级（读不成 / 分片不可信 / 扫不成 / 没有读口）⇒ 对任何号都是"不知道"；
        # · 行级（一行读得出来、但认不出是哪一号）⇒ 只对"它可能是"的那些号才是
        #   "不知道"（判法 `_retired_gap_may_be_key`）：一行"少了 task_id、名字是 D1"的
        #   记录可能是 D1 那一号，不可能是别的号 —— 把整片都判成读不全会让同一个父名下
        #   每一个还活着的号都叫不醒（`draft/145` §3.4 的反真空那一半）。
        # 至于"整行读不出来"（半行 / 非法 JSON）那一档：它进 `bad`、回执里逐字带着，
        # 但不冻结别的号（`tests/test_a_retired_name_is_never_woken.py::w12` 与
        # `test_an_unreadable_retired_list_is_not_an_empty_one.py::w14` 的反真空钉住
        # 的正是这一格；"整份读不出来"是另一档，见上面 `file_problem`）。
        unknown: list[str] = []
        for who, msg in files:
            text = msg if (not multi or not who) else f"{who}：{msg}"
            unknown.append(f"销号名单读不全 ⇒ {text}")
        if scan_error:
            unknown.append(f"销号名单读不全 ⇒ {scan_error}")
        for who, gap in gaps_all:
            try:
                may = self._retired_gap_may_be_key(gap, who=who, tid=tid, want=want)
            except Exception:  # noqa: BLE001 —— 判不了就当它可能是（fail-closed）
                may = True
            if not may:
                continue
            detail = str(gap.get("why") or "这一行认不出来")
            text = detail if (not multi or not who) else f"{who}：{detail}"
            unknown.append(f"销号名单读不全 ⇒ {text}；这一行可能就是这一号")
        out["unknown_reasons"] = unknown
        if out["retired"]:
            out["reason"] = ("" if not problems else
                             f"销号名单读不全（{len(problems)} 行：{problems[0]}）—— "
                             "但这一号已读到销号行")
        elif problems:
            out["reason"] = (f"销号名单读不全（{len(problems)} 行：{problems[0]}）⇒ "
                             "不能据此说「没销号」")
        elif not asked:
            out["reason"] = "名册目录里一份销号名单都没有（查过了）⇒ 没有销号"
        return out

    def _retired_unchecked_note(self) -> str:
        """销号名单没查成时附在理由串后面的那一句（查成了就是空串）。

        为什么必须附：`resume` 那一档的措辞里有"未销号"三个字。销号名单读不全时那三个字
        是没有根据的 —— 附一句"读不全（…）"才让回执与盘上一致（`draft/143` §7.3：
        盘上说它已销号、回执说它"owner 静默、未销号"，正是本仓最忌的那一类。）

        2026-10-31 起本方法在正常路径上恒为空串：`retired_verdict` 判 `unknown` 时
        `wake_blocked` 走 `review` 那一支、根本走不到 `resume`，所以到这里的读数一定
        `checked=True`。留着它是给"外部打桩/覆写了布尔口"那一档的兜底 —— 那种情况下
        读数可能与布尔口不一致，而这一句就是"不许把没查成写成没销号"的最后一道措辞。
        """
        got = dict(getattr(self, "last_retired_reading", {}) or {})
        if got.get("checked") is not False:
            return ""
        why = str(got.get("reason") or "没查成")
        return f"（销号名单这一格没查成：{why}；按业主 2026-10-31 的裁定这一档不该叫醒）"

    def _is_retired_task(self, task_id: str, *, parent: str = "") -> bool:
        """这个台账号对应的名册项是不是已销号（只回"读到了匹配行没有"）。

        读不到 ⇒ 返回 False。这个布尔不改语义，也不承担"叫不叫"的决定：`False` 里
        混着"读过了、没销号"与"读不全、不知道"两档，而那两档的下一步相反
        （照叫 / 不叫）。动作侧看的是 :meth:`retired_verdict` 那个三态。

        已销号那一档的权威读数在秘书的销号名单里（`Secretary.retired_ledger(owner,
        trusted_shard=...)`，按父分文件）。`parent` 是"谁名下的那份名单"：四个调用点
        都能从台账那一行拿到它；拿不到时 `retired_reading_of` 自己按 `parent_task_id`
        找，再不行扫名册目录（并回溯别的分片）。读不成 / 读不全的读数在
        `self.last_retired_reading` 里（`checked=False` ＋ 原样带着 `bad` /
        `unattributable`）。
        """
        return bool(self.retired_reading_of(task_id, parent=parent).get("retired"))

    def retired_verdict(self, task_id: str, *, parent: str = "",
                        name: str = "") -> str:
        """`retired` / `live` / `unknown` —— 动作侧只看这一个字符串（`draft/145` §3.2）。

        三档的判据（都在 :meth:`retired_reading_of` 的读数上，不另立口径）：
        ```text
        retired  读到了匹配行（读到就是读到；同一份名单里的坏行不改变它）
        live     这一号/这一名的否定结论查成了（没有一行可能是它，且名单读得成）
        unknown  这一号/这一名自己读不全：整份读不出来 / 分片不可信 / 扫不成 /
                 读口抛了 / 有一行认不出是哪一号而它可能就是这一号
        ```
        业主 2026-10-31 的裁定是 fail-closed：`unknown` ⇒ 不叫醒（交人看）。
        改前那一格是反的（"读不全"被折成"没销号"⇒ 已销号的号照样被叫起来）。

        两处刻意的分界（都是判据钉住的，不是随手放的）：
        - 「已销号」仍由布尔口 :meth:`_is_retired_task` 回答（语义与签名都不变：判据里
          有一处把它打桩成单参数 lambda），所以那一处打桩照样生效；
        - 判 `unknown` 用的是读数的 `unknown_reasons`（这一号自己的否定结论信不信
          得过），不是整片的 `checked`：一片里另有一行"整行读不出来"时，那一行进
          `bad`、回执逐字带着，但不冻结别的号（`wake_blocked` 的 `review` 那一档只留
          给"可能就是这一号"的读不全）。
        """
        tid = str(task_id or "").strip()
        want = str(name or "").strip()
        try:
            hit = bool(self._is_retired_task(tid, parent=parent) if parent
                       else self._is_retired_task(tid))
        except TypeError:
            # 布尔口被外部打桩成单参数 / 无参时照原样问一次（`test_a_message_runs_a_silent_agent`）
            hit = bool(self._is_retired_task(tid))
        if hit:
            return "retired"
        got = dict(getattr(self, "last_retired_reading", {}) or {})
        if want and (str(got.get("task_id") or "") != tid
                     or str(got.get("name") or "") != want):
            got = dict(self.retired_reading_of(tid, parent=parent, name=want))
        return "unknown" if (got.get("unknown_reasons") or []) else "live"

    def _retired_reason(self) -> str:
        """最近一次销号名单读数里"这一号自己"的那一句理由（`unknown` 的回执要带上它）。"""
        got = dict(getattr(self, "last_retired_reading", {}) or {})
        unknown = [str(x) for x in (got.get("unknown_reasons") or [])]
        if unknown:
            return unknown[0]
        return str(got.get("reason") or "没查成")

    def _retired_first_problem(self) -> str:
        """最近一次读数里第一个"读不全"的细节（回执里"先看哪一行"的那一句）。"""
        got = dict(getattr(self, "last_retired_reading", {}) or {})
        problems = [str(x) for x in (got.get("bad") or [])]
        problems += [str(x) for x in (got.get("unattributable") or [])]
        return problems[0] if problems else self._retired_reason()


    #: 逐条审批唤醒写进板项那一行 `inputs` 的落痕前缀：`wake:<谁>@<iso>|<为什么>`。
    #:
    #: 与 `blocked:` / `stop-notified:` / `stop-acked:` / `edge-released:` /
    #: `void:expired:` 同一族：`inputs` 是"这一行与什么打过交道"那一格，加一个元素不改变
    #: 语义，也不需要动 `schema.py`（禁改区）。事后必须能回答"谁批的、什么时候、凭什么"
    #: —— 唤醒是不可逆的那一类动作（醒来之后它会接着跑、接着花钱）。
    _WAKE_PREFIX = "wake:"

    def wake_blocked(self, ids: Sequence[str] | None = None, *, approve: str = "",
                     dry_run: bool = True) -> dict[str, Any]:
        """读 block 行、逐条审计、批准了才逐条直写并唤醒。

        口径是「直接读 block 表，并把自动审计与 block 表结合起来做逐个审批唤醒」。

        ## 它读哪几行（按 `item_state` 筛，不按 `status`）
        `tasks` 里 `item_state == "block"` 的行 —— 那是 `stopctl.block_remaining_tasks`
        停下来的委托项（同一次写入把 `status` 与 `item_state` 两根轴一起翻成 `block`）。
        刻意不按 `status == "block"` 筛：`status` 会被单向翻（`done` 之后不再回 `block`），
        于是"板项早已 done、`status` 还停在 block"的老板项会混进来 —— 读它们等于去唤醒
        一件早就做完了的活。要唤醒的那个号是这一行的 `parent_task_id`（收件人），
        不是板项自己的号：板项不是代理，叫它没有对象。

        ## 三档（缺读数一律不许猜）
        ```text
        resume  owner 静默 且 未销号 且 仍在册 且 该板项未终态 且 子树无在跑
        review  任一读数没查成（销号名单 / 静默 / 子树活跃 / 名册）—— 交人看，不猜
        skip    已销号 / owner 在飞 / 板项已终态 / 子树有在跑 / 不是静默 / 没批准
        ```
        逐条给理由码（`refusal_code`），八格回执项一个不多一个不少（见下）。
        销号名单读不全那一档是 `review` ＋ `unknown_retired`（不叫醒，fail-closed）；
        一笔里所有候选都停在 `review` 时顶层 `state="unknown"`（"没查成"，不是"叫不动"）。

        ## 批：`approve="yes"` 才算有令牌
        `approve` 是"允许按审计结论动作"的令牌，不是"要不要真写"的开关。没有令牌的那
        一趟连"它能唤醒"这个结论都不给（全记 `skip` + `not_approved`）：一张"没批准但
        可唤醒"的清单等于把绕开批准的路递到调用方手里。`dry_run=True` 才是"别真动"：
        审计照跑、回执照给，但一个字节都不写、一次都不叫。

        ## 写（绕过状态机，照 `stopctl.block_remaining_tasks` 的样板）
        `block` 在 `ITEM_MOVES` 里没有出边（四条全 `back`）⇒ 不能走 `_set_item`，只能
        `store.tx("tasks")` 直写。同一次写入翻两根轴，一次只动一条：
        ```text
        status      block -> running
        item_state  block -> queued    （渲染只认 queued）
        item_close  保持 ""            （schema：只在 item_state='done' 时有意义）
        seen_by / seen_step  一并清空  （schema：要么都在、要么都不在）
        ended_at    None               （schema：pending/running 不许带 ended_at）
        outcome     None               （上一趟的结局不属于这一趟）
        inputs      追加 wake:<谁>@<iso>|<为什么>
        ```
        写后立刻 `S.Task.validate()` 自校：这一层绕开了状态机，它是剩下的唯一一道闸。
        直写与唤醒是两步：直写落盘了而唤醒没成时，回执是 `refusal_code="wake_failed"`
        而那一行已经翻过来了 —— 下一步该做的是再叫一次，不是以为它还停着。

        ## 醒：只调 `wake_on_lifeline`
        它是唯一带"已销号 / 在飞"双闸的那一层。绝不直接调 `resume_dispatched`：
        那条路没有闸，绕过它就等于允许同号起第二个循环（两个自己互相喂事件，直到把进程
        挂死）。owner 在飞 ⇒ 本方法按 `skip` 记 `refusal_code="in_flight"` 并且一次都不叫
        —— 那条消息会进它自己的收件箱。

        ## 三条必须写在明面上的后果
        1. 唤醒清不掉板项本身：它把 `item_state` 从 `block` 翻成 `queued`，板项还在板上
           （要收口得由收件人自己 ack）。所以本方法的回执不承诺"作废"、也不承诺"消项"。
        2. `expects="work"` 的 block 项作废不掉（`void_items` 只收 `expects="ack"`）——
           所以"审批之后作废"不是唤醒的替代品，本方法不许诺它。
        3. `block` 会被"等谁"那个读口当成已收口（`tools/clock_tools.CLOSED_ITEM_STATES`
           = `("done", "block")`）⇒ 一条挂在它上面的等待计时器会提前报醒。这是既有
           读口的口径，本方法不改它、也不许假装它不存在。

        ## 回执（抄 `ack_items` 的形状）
        `{"checked", "state", "items", "count", "requested", "reason"}`：

        - `state`：`woken`（至少叫起来一条）/ `refused`（有候选、一条都没叫起来）/
          `nothing`（一条 block 行都没有，或没给 `ids`）/ `unknown`（台账读不成，
          `checked=False`）—— 它说的是"这一笔有没有叫醒"，逐条的审计结论在
          `items[].verdict`；
        - `items[]`：每项 `{item_id, task_id, owner, verdict, started, refusal_code,
          why, mark}`（逐项同形同集）—— `item_id` 是板项号，`task_id` 是要唤醒的那个号，
          `owner` 是它的角色，`mark` 是写进 `inputs` 的那条落痕（没写就是空串）。
          `task_id` / `owner` 在每一档都给（`skip` 那几档也一样）；
          只有"台账里根本没有那一行"（`no_such_item`）时这两格是空串 —— 那一档读不出来，
          不许拿 `item_id` 顶替（那会让"点错了"看起来像"叫对了"）；
        - `count` 数的是真正被叫起来的条数（`started=True`）；`requested` 是给了几个号；
        - 三态：台账读不成 ⇒ `checked=False` + `state="unknown"`，绝不折成"没有 block 行"。

        逐条隔离：一条失败只影响它自己（写失败 / 叫不醒都逐条记，不中断整趟）。
        """
        asked = [str(x) for x in (ids or ()) if str(x).strip()]
        out: dict[str, Any] = {"checked": True, "state": "nothing", "items": [],
                               "count": 0, "requested": len(asked), "reason": ""}
        try:
            rows = [dict(r) for r in self._tasks()]
        except Exception as exc:  # noqa: BLE001 —— 读不成是"没查成"
            out["checked"] = False
            out["state"] = "unknown"
            out["reason"] = (f"tasks 台账读不成（{type(exc).__name__}: {exc}）⇒ 本次没查成"
                             "（不是「板上没有 block 行」）")
            return out
        by_id = {str(r.get("task_id") or ""): r for r in rows}
        picked: list[tuple[str, dict | None]] = []
        if asked:
            picked = [(tid, by_id.get(tid)) for tid in asked]
        else:
            # `rows` 已经是本方法自己拷的一份（`dict(r) for r in self._tasks()`），
            # 循环里一个字段都不写回 ⇒ 这里不再逐行复制第二遍。
            picked = sorted(((str(r.get("task_id") or ""), r) for r in rows
                             if str(r.get("item_state") or "") == "block"),
                            key=lambda x: x[0])
        allowed = str(approve or "").strip().lower() == "yes"
        # 谁批的：生产里是这一趟的台账号（`calling_as` 挂的），夹具里退回顶趟号，
        # 都没有才落主控代号 —— 落痕要能回答"谁批的"，所以不许留空。
        who = str(self._owner_task_id() or S.CONDUCTOR_ROLE)
        woken = 0
        for item_id, row in picked:
            cell: dict[str, Any] = {"item_id": item_id, "task_id": "", "owner": "",
                                    "verdict": "skip", "started": False,
                                    "refusal_code": "", "why": "", "mark": ""}
            out["items"].append(cell)
            if row is None:
                cell["refusal_code"] = "no_such_item"
                cell["why"] = (f"台账里没有 {item_id} 这一行 ⇒ 这个号点错了"
                               "（不是「已经唤醒了」）")
                continue
            # 先回填"哪一条、谁的"：`item_id` 是板项号，`task_id` 是要唤醒的那个号，
            # `owner` 是它的角色。这三格必须在每一档回执里都齐 —— 包括下面那几个早退档
            # （已终态 / 不是 block）。漏到早退之后，那两档的 `task_id` / `owner` 就是
            # 空串：读的人只能拿板项号去叫，而板项不是代理，叫它没有对象。给某一档单独
            # 补一句也不行 —— 那会把"逐项同形同集"拆成两份实现，下一档早退时又会漏。
            owner = str(row.get("parent_task_id") or "")
            cell["task_id"] = owner
            owner_row = by_id.get(owner) or {}
            cell["owner"] = str(owner_row.get("role") or "")
            item_state = str(row.get("item_state") or "")
            if item_state == "done":
                cell["refusal_code"] = "item_closed"
                cell["why"] = (f"{item_id} 的板项已经终态（item_state=done，"
                               f"item_close={row.get('item_close')!r}）⇒ 活已经收口，"
                               "不许再叫它（叫起来也没有活给它）")
                continue
            if item_state != "block":
                cell["refusal_code"] = "not_blocked"
                cell["why"] = (f"{item_id} 现在不是 block 板项（item_state={item_state!r}）"
                               "⇒ 它没被停掉，这一层没有对象")
                continue
            if not owner:
                cell["refusal_code"] = "no_owner"
                cell["why"] = (f"{item_id} 没有 parent_task_id（顶层项）⇒ "
                               "没有可唤醒的号（板项不是代理，叫它没有对象）")
                continue
            if not allowed:
                cell["refusal_code"] = "not_approved"
                cell["why"] = ("没批准：approve 不是 \"yes\" ⇒ 不审也不动（一个字节都没写、"
                               "一次都没叫）；要看审计结论就带 approve=\"yes\" 再跑一趟"
                               "预览（dry_run=True）")
                continue
            # ---- 逐条审计：已销号 / 在册 / 在飞 / 子树 / 静默（每一条都要有读数）----
            # 销号名单按父存：`owner` 的父就是"该读哪一份名单"（`owner_row` 在读侧已经拿到了）。
            owner_parent = str(owner_row.get("parent_task_id") or "")
            verdict = self.retired_verdict(owner, parent=owner_parent)
            if verdict == "retired":
                cell["refusal_code"] = "retired"
                cell["why"] = (f"{owner} 已销号 ⇒ 彻底没有了（业主 2026-10-29）：叫不醒，"
                               "也不该动它名下的行；要它干活就重新派一个")
                continue
            if verdict == "unknown":
                # 销号名单读不全 ⇒ 不叫醒，交人看（fail-closed）。
                # 这一档的下一步不是"别叫了"，而是"去看那一份名单的那几行" ——
                # 那正是 `review` 的既有定义（"任一读数没查成 ⇒ 交人看，不猜"）。
                # 理由码单列 `unknown_retired`（不复用 `unknown_reading`）：同一项上可能
                # 同时坏两格（子树读数 ＋ 销号名单），复用会让"哪一格坏"读不出来。
                cell["verdict"] = "review"
                cell["refusal_code"] = "unknown_retired"
                cell["why"] = (f"{owner} 的销号名单这一格没查成"
                               f"（{self._retired_reason()}）⇒ 不叫醒（fail-closed）："
                               "这一格读不出它销过没有，就不把叫醒这件事当结论。"
                               f"先看 out/roster/{owner_parent or '?'}-retired.jsonl 的"
                               f"那几行（{self._retired_first_problem()}）。")
                continue
            # 销号名单这一格查成了（`live`）⇒ 后面每一句"未销号"都有根据。
            # （局部名不叫 `roster_note`：本模块里那个名字已经指"名册写入的兜底说明"。）
            retired_note = self._retired_unchecked_note()
            if not owner_row:
                cell["refusal_code"] = "owner_missing"
                cell["why"] = (f"{item_id} 的收件人 {owner} 在台账里没有那一行 ⇒ 它不在册"
                               "（不是「已经收工」）⇒ 这个号叫不起来")
                continue
            if str(owner_row.get("status") or "") in UNFINISHED_STATUSES:
                cell["refusal_code"] = "in_flight"
                cell["why"] = (f"{owner} 它自己在跑（status={owner_row.get('status')}）⇒ "
                               "那条消息/委托会进它自己的收件箱，另起就是第二个同号循环"
                               "（业主 2026-10-29 的自我唤醒事故）")
                continue
            sub = self.active_in_subtree(owner)
            if not sub.get("checked"):
                cell["verdict"] = "review"
                cell["refusal_code"] = "unknown_reading"
                cell["why"] = (f"{owner} 这一支有没有在跑的程序读不成"
                               f"（{sub.get('reason') or '没查成'}）⇒ 交人看（不猜）")
                continue
            # 这一支的活跃节点数：判据与拒信那一句读的是同一个数，转一次就够。
            active_count = int(sub.get("active_count") or 0)
            if active_count > 0:
                busy = "、".join(str(r.get("task_id")) for r in (sub.get("rows") or ()))
                cell["refusal_code"] = "subtree_active"
                cell["why"] = (f"{owner} 这一支还有 "
                               f"{active_count} 个节点在活跃（{busy}）"
                               "⇒ 它不是静默：叫起来会与它们抢同一份活")
                continue
            gate = self.retire_state_of(owner)
            state = str(gate.get("state") or AGENT_STATE_UNKNOWN)
            if not gate.get("checked") or state == AGENT_STATE_UNKNOWN:
                cell["verdict"] = "review"
                cell["refusal_code"] = "unknown_reading"
                cell["why"] = (f"{owner} 是不是静默读不成（"
                               f"{gate.get('state_reason') or gate.get('reason') or '没查成'}"
                               "）⇒ 交人看（不猜）")
                continue
            if not gate.get("silent"):
                waited = "、".join(str(x) for x in (gate.get("waiting_for") or ()))
                busy = "、".join(str(x) for x in (gate.get("busy_roots") or ()))
                where = (f"在等 {waited}" if waited else
                         f"名下有在跑的 {busy}" if busy else
                         str(gate.get("state_reason") or "它还挂着东西"))
                cell["refusal_code"] = "not_silent"
                cell["why"] = (f"{owner} 此刻不是静默（{gate.get('state_label') or state}："
                               f"{where}）⇒ 叫起来就是第二个同号循环")
                continue
            cell["verdict"] = "resume"
            why_wake = (f"逐条审批唤醒（审计判 resume：owner 静默、未销号、板项 {item_id} "
                        f"未终态、子树无在跑）⇒ 批准后直写并唤醒 {owner}{retired_note}")
            if dry_run:
                cell["why"] = ("预览（dry_run=True）：判为 resume（可唤醒）—— 批准后才会"
                               "直写这一行并叫它；这一趟一个字节都没写、一次都没叫"
                               + retired_note)
                continue
            # ---- 直写（绕过状态机，一次只动这一条）------------------------------
            mark = f"{self._WAKE_PREFIX}{who}@{S.now_iso()}|{why_wake[:160]}"
            self._refuse_write_in_snapshot("逐条审批唤醒（wake_blocked）")
            trouble = ""
            try:
                with self.store.tx("tasks", actor="conductor", note="item:wake") as tx:
                    now = tx.find("tasks", task_id=item_id)
                    if now is None:
                        trouble = f"直写时 {item_id} 在台账里已经没有了"
                    elif str(now.get("item_state") or "") != "block":
                        trouble = (f"直写读了第二遍：{item_id} 已经不是 block 板项"
                                   f"（item_state={now.get('item_state')!r}）⇒ 这一条不动")
                    else:
                        patch = dict(now)
                        # 不改 status：直写跑在唤醒之前，而 wake_on_lifeline 的闸门正是
                        # "目标在跑就不叫"。先写 running，闸门立刻判 in_flight，一条都叫不起来。
                        # status 留给执行侧 resume_dispatched 去翻，它翻的同时起线程。
                        patch["item_state"] = "queued"
                        patch["item_close"] = ""
                        patch["seen_by"] = ""
                        patch["seen_step"] = None
                        patch["outcome"] = None
                        patch["ended_at"] = None
                        patch["started_at"] = (str(now.get("started_at") or "")
                                              or S.now_iso())
                        patch["inputs"] = ([str(x) for x in (now.get("inputs") or ())]
                                           + [mark])
                        task = S.Task(**{k: v for k, v in patch.items()
                                         if k in S.Task.__dataclass_fields__})
                        task.validate()
                        tx.upsert("tasks", task.to_dict(), note="item:wake")
                if not trouble:
                    cell["mark"] = mark
            except Exception as exc:  # noqa: BLE001 —— 写不进去就如实回，不假装叫了
                trouble = f"直写 {item_id} 没成（{type(exc).__name__}: {exc}）"
            if trouble:
                cell["refusal_code"] = "write_failed"
                cell["why"] = trouble + " ⇒ 没叫它（写不进去就不许假装叫了）"
                continue
            # ---- 醒：只走 wake_on_lifeline（唯一带"已销号 / 在飞"双闸的那一层）----
            got = self.wake_on_lifeline(owner)
            started = bool(got.get("started")) if isinstance(got, Mapping) else False
            cell["started"] = started
            if started:
                woken += 1
                # 回执措辞的硬要求：这一句是模型读到的唯一一句"接下来该做什么"。
                # 只写"翻成 queued 了"会让它以为板项没了 ——
                # 板项还在板上，收口要收件人自己 ack，销号闸照旧挡着。
                cell["why"] = (f"{owner} 已按同号叫起：板项 {item_id} 已由 block 翻成 "
                               "queued，它醒来就能在板上读到这一条。板项仍在板上：收口要"
                               "收件人自己 ack（`conductor.ack`），销号闸照旧挡着 —— "
                               "唤醒解除的是「叫不醒」，不是「挡住销号」" + retired_note)
            else:
                why_not = str(got.get("reason") or "") if isinstance(got, Mapping) else ""
                cell["refusal_code"] = "wake_failed"
                cell["why"] = (f"直写已经落盘（{item_id} 已 queued、落痕在 inputs），但叫不醒"
                               f"它（{why_not or '没给理由'}）⇒ 下一步：再叫一次，或重新派活")
        out["count"] = woken
        if not picked:
            out["state"] = "nothing"
            out["reason"] = ("板上没有 item_state=block 的行 ⇒ 这一层没有对象"
                             "（查过了、没有，不是「没查成」）")
        elif woken:
            out["state"] = "woken"
            out["reason"] = f"叫起来 {woken} 条（其余逐条理由见 items）"
        elif out["items"] and all(str(c.get("verdict") or "") == "review"
                                  for c in out["items"]):
            # 每一条都停在 `review`（读数没查成）⇒ 这一笔的顶层结论是"没查成"，
            # 不是"叫不动"。折进 `refused` 会让读的人以为"查过了、它们都叫不醒"，
            # 而真相是"一条都没查成"。
            out["state"] = "unknown"
            n_retired = sum(1 for c in out["items"]
                            if str(c.get("refusal_code") or "") == "unknown_retired")
            out["reason"] = ((f"{n_retired} 条的销号名单读不全 ⇒ 一条都没叫"
                              "（不是「都叫不动」）") if n_retired else
                             "每一条都有读数没查成 ⇒ 一条都没叫（交人看，不是「都叫不动」）")
        else:
            out["state"] = "refused"
            if not allowed:
                out["reason"] = "没批准（approve 不是 \"yes\"）⇒ 不审也不动，一条都没叫"
            elif dry_run:
                out["reason"] = ("预览（dry_run=True）：一个字节都没写、一次都没叫"
                                 "（逐条的审计结论见 items[].verdict）")
            else:
                out["reason"] = "一条都没叫起来（逐条理由见 items）"
        return out

    @staticmethod
    def _item_row(*, kind: str, role: str, expects: str, action: str = "",
                  summary: str = "", called_by: str = "",
                  parent_task_id: str | None = None, depth: int = 1,
                  keep_alive: bool = False, input_key: str = "",
                  recipient_instance: str = "") -> dict:
        """一条板项行的形状（`open_item` 与 `open_items_many` 共用的唯一一处）。

        为什么共用：`open_item` 的手写行 dict 是"甲形态那七格"的唯一落点，而批量建行
        必须写出逐字节相同的行（判据 `tests/test_board_batch_write.py` 比
        `tasks.json` 的 sha256）。两处各写一份的代价不是重复代码，而是"批量那一路
        少了 `item_close` 一格"——那种偏差不会让任何判据从绿变红。

        `instance` 对板项的含义是收件实例（K9）：空串 = 角色地址。实例行 (
        `kind == ""`) 的 `instance` 仍是"这一趟是谁"，两轴同名不同义，靠 `kind` 分。
        """
        return {
            "role": role, "action": action or kind, "called_by": called_by or S.CONDUCTOR_ROLE,
            "parent_task_id": parent_task_id, "depth": max(1, int(depth)),
            "input_key": input_key, "status": "pending", "outcome": None,
            "refusal_reason": None, "instance": str(recipient_instance or ""),
            "detail": summary or f"工作项（{kind}）", "error": None,
            "started_at": "", "ended_at": None, "tokens": 0, "usd": 0.0,
            "artifacts": [], "inputs": [],
            "kind": kind, "expects": expects, "item_state": "queued", "item_close": "",
            "seen_by": "", "seen_step": None, "keep_alive": bool(keep_alive),
        }

    #: 改板项状态的两个有权限档（`_item_authority` 的读数）。
    #:
    #: 为什么只有两档：权限面只有两句话 ——「父代理可以更改子代理板项状态」与
    #: 「M 可通过审计工具更改任意代理的板项状态」。除此之外「没有人」有权改别人的板项
    #: （收件人自己走 `ack_items`，那条路一个字都没放宽）。
    ITEM_AUTHORITY_PARENT = "parent"
    ITEM_AUTHORITY_CONDUCTOR = "conductor"

    #: 撤销时要不要另落一条通知行（缺省关掉）。
    #:
    #: 为什么关：撤销动作自身若再落 N 条新 `notice` 行（`kind="notice"`、done/expired），
    #: 清理动作就让 `tasks` 行数变多，而板项行的 `status` 恒为 `pending`（`_item_row`
    #: 写死）⇒ 那 N 行在状态报告/网页上又变成"N 条待办"（叠上信息型板项"渲染即收口"
    #: 的观感就是"越清越多"）。
    #:
    #: 关掉之后提醒并没有消失：被撤那一行自己的 `inputs` 落了六格留痕
    #: （`revoke:expired:by=…:owner=…:from=…:to=done:at=…:reason=…`，append-only），
    #: 收件人那一侧的读口 :meth:`revoked_recent_of` 读的就是它，`agent_loop.mailbox_digest`
    #: 每一拍把最近 N 条渲染成【最近被撤销的项】。于是「谁撤的 / 为什么 / 你不需要再处理它」
    #: 一个字都没少，而新增 notice 行 = 0。
    #:
    #: 为什么留这一格而不是把另一条分支删干净：反真空判据要能整格打开它
    #: （`tests/test_revocation_posts_no_new_notice_rows.py` 的 ③），证明"新增行数 = 0"
    #: 这条判据真的在数行、不是在读一个恒空的表。默认 `False`。
    REVOKE_POSTS_NOTICE_ROW: bool = False

    def _item_authority(self, rows: Mapping[str, Mapping[str, Any]], *,
                        by_task_id: str, row: Mapping[str, Any]) -> dict[str, Any]:
        """谁有权改「这一条板项」的状态（唯一判据）。

        判据只有两句话，落在这一处、不再在工具层抄第二份：

        1. 父：`row["parent_task_id"]`（收件人）那一行的 `parent_task_id` 是
           `by_task_id` ⇒ 改的人是收件人的「直接父代理」，可以改它名下的板项。
           只认直接父：祖父 / 兄弟 / 更远的层都不行（权限面是「子代理的板项」，
           不是「子树里任何一项」）—— 越权一档由 `not_authorized` 逐条拒。
        2. M（主控）：`by_task_id` 那一行的 `role == "M"` ⇒ 可改「任意代理」的板项，
           不限直接子。一格刻意的收窄：如果那条项归属的收件人自己也是 `role=M` 的
           顶趟行，M 也不改它 —— 口径是「任意代理」，而顶趟与顶趟之间不是父子/代理
           关系；那两条 M 行谁也不知道"别人"是谁
           （`test_an_item_that_belongs_to_someone_else_is_refused` 正是这一档）。

        三态：`checked=False` 是"判不了"（没有台账号 / 台账里没有这一行 / 那一行
        自己是板项），不许折成"没权限"；`allowed=False` 且 `checked=True` 才是"查过了、
        你没有权限"。拒信带机器码（`no_actor` / `unknown_actor` / `not_authorized`）。

        返回 `{"checked","allowed","mode","by","owner","code","why"}`；`mode` 是
        允许的那一档（`parent` / `conductor`，见上面两个常量）—— 刻意不叫 `kind`：
        这一格回答的是"凭什么允许"，不是"这一行是哪根轴"，免得把两件事读混。
        `owner` 是板项的收件人（`row["parent_task_id"]`）—— 留痕里的 `owner` 就是这一格。
        """
        by = str(by_task_id or "")
        owner = str(row.get("parent_task_id") or "")
        out: dict[str, Any] = {"checked": True, "allowed": False, "mode": "",
                               "by": by, "owner": owner, "code": "", "why": ""}
        if not by:
            out.update(checked=False, code="no_actor",
                       why=("没有台账号 ⇒ 判不了谁在改（不猜一个改的人；"
                            "留痕里的 by 必须是台账上真有的那一行）"))
            return out
        actor = rows.get(by)
        if actor is None:
            out.update(checked=False, code="unknown_actor",
                       why=(f"台账里没有 {by} 这一行 ⇒ 不知道你是谁，不许改别人的板项"
                            "（fail-closed：查不到≠有权限）"))
            return out
        if self._is_board_item(actor):
            # 消息里回显 kind 只是为了让人读得懂这条拒信（`actor["kind"]` 原样打出，
            # 不做判据 —— 判据是上面那一行 `_is_board_item`）。
            out.update(code="not_authorized",
                       why=(f"{by} 自己是一条板项（kind={actor['kind']}），不是代理"
                            " ⇒ 板项不能改别人的板项"))
            return out
        role = str(actor.get("role") or "")
        owner_row = rows.get(owner) if owner else None
        owner_role = str((owner_row or {}).get("role") or "")
        if role == S.CONDUCTOR_ROLE and owner_role != S.CONDUCTOR_ROLE:
            out.update(allowed=True, mode=self.ITEM_AUTHORITY_CONDUCTOR,
                       why=f"{by} 是主控 M：可改任意代理的板项（业主 2026-11-06 裁定 ①）")
            return out
        if (owner_row is not None and self._is_instance_row(owner_row)
                and str(owner_row.get("parent_task_id") or "") == by):
            out.update(allowed=True, mode=self.ITEM_AUTHORITY_PARENT,
                       why=(f"{by} 是 {owner} 的直接父代理：可改它名下的板项"
                            "（业主 2026-11-06 裁定 ①）"))
            return out
        if role == S.CONDUCTOR_ROLE and owner_role == S.CONDUCTOR_ROLE:
            out.update(code="not_authorized",
                       why=(f"{by} 是主控 M，但 {owner} 也是顶趟行（role=M）⇒ "
                            "裁定说的是「任意代理」，两个顶趟之间不是这项的父子关系；"
                            "这一条不许改（要改由人处置）"))
            return out
        out.update(code="not_authorized",
                   why=(f"{by} 不是 {owner or '（顶层）'} 的直接父代理、也不是主控 M ⇒ "
                        "只有它的直接父代理或 M 能改别人的板项（兄弟 / 祖父 / 更远的层都不行）"))
        return out

    #: 撤销该用的动作（`revocation_cell` 的 `action` 格）。与工具面同名，不另造一个名字：
    #: 模型看到的就是注册表里能调的那一件（`conductor.void_items`，它在工具层固定带
    #: `revoke=True`）。
    REVOKE_ACTION = "conductor.void_items"

    def revocation_cell(self, row: Mapping[str, Any], *, by_task_id: str = "",
                        rows: Mapping[str, Mapping[str, Any]] | None = None) -> dict[str, Any]:
        """「这一条能不能被你撤、撤它该用哪个动作」—— 甲件。

        为什么要有这一格：`conductor.board` / `conductor.patrol` 的每一项都要直接回答
        "这一条能不能撤"，否则模型得把 id 搬到 `conductor.void_items` 再被拒一次才知道
        —— 试错是两步，而第一步（搬 id）没有任何读数。现在每一步都直接带出可否与动作。

        判据就是 :meth:`_item_authority`（唯一判据，三态见那里）：不可撤的每一档都折算成
        `revocable=False`，`code` / `why` 原样带出、分得开。

        返回的键集固定（`revoke` 这一格在 board / patrol 的每一项上都长这样）：
        `{"revocable","action","call","mode","code","why"}`。

        - `revocable=True` ⇒ `action="conductor.void_items"`，`call` 是照抄就能用的
          参数骨架 `{"item_ids": [这一条的编号], "why": "<一句话为什么撤>"}`（`why`
          必填，进留痕；模型只需要补那一句）；
        - `revocable=False` ⇒ `action` / `call` 是空表/空串，`why` 说清凭什么不可撤
          （权限拒信原样带出，或"已经终态" / "它不要求任何动作"）。
        """
        out: dict[str, Any] = {"revocable": False, "action": "", "call": {},
                               "mode": "", "code": "", "why": ""}
        iid = str(row.get("task_id") or "")
        if not self._is_board_item(row):
            out.update(code="not_board_item",
                       why="它不是板项（kind 为空）⇒ 不归撤销管")
            return out
        if str(row.get("item_state") or "") == "done":
            out.update(code="already_done",
                       why="它已经是终态（item_state=done）⇒ 没有可撤的东西")
            return out
        if str(row.get("expects") or "") == "":
            out.update(code="no_obligation",
                       why="它不要求任何动作（expects 为空）⇒ 没有可撤的义务")
            return out
        if rows is None:
            try:
                rows = self._tasks_by_id()
            except Exception as exc:  # noqa: BLE001 —— 读不成是"没查成"
                out.update(code="unknown_actor",
                           why=f"台账读不成（{type(exc).__name__}: {exc}）⇒ 判不了谁有权撤")
                return out
        authority = self._item_authority(rows, by_task_id=by_task_id, row=row)
        if not authority.get("checked"):
            out.update(code=str(authority.get("code") or "unknown_actor"),
                       why=str(authority.get("why") or "权限读不成（fail-closed）"))
            return out
        if not authority.get("allowed"):
            out.update(code="not_authorized",
                       why=str(authority.get("why") or "没有权限撤这一条"))
            return out
        out.update(revocable=True, action=self.REVOKE_ACTION,
                   call={"item_ids": [iid],
                         "why": "<一句话为什么撤：必填，逐字进那一行的 inputs>"},
                   mode=str(authority.get("mode") or ""),
                   why=str(authority.get("why") or ""))
        return out

    def _revocation_notice_row(self, *, row: Mapping[str, Any], item_id: str,
                               owner: str, by_task_id: str, reason: str,
                               depth: int) -> dict | None:
        """撤销通知那一条行的形状（乙件；唯一一处，判据可整格替换它做反真空）。

        ## 它只在 `REVOKE_POSTS_NOTICE_ROW=True` 时才被调用

        缺省这一档是死代码（暂留，不删）。三句话写死它的身份：

        1. 生产路径永不许调它 —— `void_items(revoke=True)` 的默认分支在
           `REVOKE_POSTS_NOTICE_ROW=False` 时根本走不到这里；
        2. 它留着的唯一用途是反真空：判据把那个开关整格打开，证明"新增行数 = 0"这条
           结论真的在数行、不是在一张恒空的表上读出来的；
        3. 彻底删它要等 `tasks` 拆表 / 加 `row_kind` 列那一批：届时反真空换成直接数
           「被撤行的 `inputs` 里有没有那条 `revoke:expired:` 留痕」，不再需要一条
           "旧行为"当对照。

        口径是「撤销动作不再自己生成待 ack 通知」，判据是撤销 N 条之后新增 notice 行 = 0。
        所以默认路径不经这里：提醒由被撤行自己的 `revoke:expired:…` 留痕承担
        （`revoked_recent_of` 读它）。

        ## 正文

            撤销时自动投一条通知给收件人（系统发出、不要 ack）：
            「你名下 t-xxxxx（<summary>）已被 <by> 撤销（理由：…），你不需要再处理它」

        ## 为什么它是已收口的一行（`done` + `expired`），而不是一条开着的新待办

        `ITEM_EXPECTS` 只有 `ack` / `work` 两档（冻结面）。一条开着的通知只能是
        `expects="ack"`（收件人欠一个回执 —— 与「不需要 ack」正相反，而且它会在销号闸
        里冒充"名下还有未消的板项"）或新造一档 expects（不许）。所以通知以已收口的一行
        落账：它是一份记录，不是待办 —— `open_items_of` 看不见它、`ack_items` 收不到
        它，板的两个计数一个都不动（既有判据
        `test_the_board_readings_drop_the_revoked_item_at_once` 要求撤销后计数恰好少 1，
        它同时守着"通知不许冒充待办"）。

        `called_by="system"`：这一条不是撤销的人（`by_task_id`）以自己名义投的，是框架替
        这次撤销发的；`by` 出现在正文里，读的人不用猜。`expects` 为空（那一行不欠任何
        动作）—— `schema.Task.validate` 的空 `expects` 窄门正好开在 done/expired 上。

        返回 `None` = 这一条不该投（没有收件人，或它自己就是一条撤销通知 ⇒ 防环）。
        """
        if not owner:
            return None
        if str(row.get("input_key") or "").startswith(REVOKE_NOTICE_PREFIX):
            # 通知自己也是 tasks 行：撤它会再生成一条通知，撤通知的通知再生成一条……
            return None
        summary = _board_item_summary(row)
        text = (f"你名下 {item_id}（{summary}）已被 {by_task_id} 撤销"
                f"（理由：{reason}），你不需要再处理它")
        notice = self._item_row(kind="notice", role=str(row.get("role") or ""),
                                expects="", action="notice", summary=text,
                                called_by="system", parent_task_id=owner,
                                depth=max(1, int(depth)),
                                input_key=f"{REVOKE_NOTICE_PREFIX}{item_id}")
        notice["item_state"] = "done"
        notice["item_close"] = "expired"
        notice["inputs"] = [f"notice:revoked:{item_id}:by={by_task_id}"]
        return notice

    def void_items(self, item_ids: Sequence[str], *, by_task_id: str, why: str,
                   revoke: bool = False) -> dict[str, Any]:
        """把"永远不会再被收件人处理"的板项作废（`item_close="expired"`）。

        为什么必须有这一条：到点通知是 `expects="ack"` 的板项，父不许代 ack，而收件人
        （子代理）已经静默/退役 ⇒ 它永远不会被 ack。可另一头，销号闸要求"名下没有未消的
        板项"、收工闸要求"整棵树都已销号" ⇒ 四个环节互锁，那一趟会连续被拒满
        `max_final_refused` 拍后以 `final_refused` 收尾、final 为空。

        出口是作废 —— 今天它的正当性只剩一条：这个号叫不醒了（已销号 / 兜底表被永久
        抑制）。"只是静默"不够，那一档在下面边界 2 逐项判。

        `revoke=False` 那一档（缺省）的三条硬边界（少一条就等于把这条路变成"父代 ack"）：
        1. 只处理 `expects="ack"` 的项 —— 要交付的活（`expects="work"`）不许作废；
        2. 调用方必须已经证明收件人叫不醒（已销号，或兜底表被永久抑制）：只是静默
           不够 —— 一条消息或一次委托就会把它叫起来，那时它自己能 ack（本方法逐项核
           `retire_state_of` 与 `lifeline_suppressed` / `retired_verdict`，两个读数都
           不是"叫不醒"就拒）—— 不许把还可能被叫醒的活清掉。销号名单读不全
           （`unknown`）也不算"叫不醒"：那一档的拒信带理由码 `unknown_retired`，
           因为"读不出来"证明不了"它叫不醒"（fail-closed）；
        3. 作废不经过状态机（`item_move` 描述的是"有人读过/办过"，作废恰恰是
           "不会有人读"），但一律过 `schema.Task.validate`；来路写进 `inputs`
           （`void:expired:<父台账号>:<理由>`），于是事后能回答"谁作废的、为什么"。

        ## 按权限撤销（`revoke=True`）

        上面那三条是"作废"（`revoke=False`，缺省）的口径；`revoke=True` 换一条正当性：
        改的人是「直接父代理」或「M」（`_item_authority` 判，判据只有那一处）⇒ 可以撤
        "不再需要做"的板项，不再要求证明"收件人叫不醒" —— 权限替代了那道证明。
        但「必须留痕」，而且留痕是六格：

        - `by`（谁改的，台账号）/ `owner`（这条项原来归谁）/ `reason`（为什么，理由串）
        - `from`（原状态）/ `to="done"`（新状态）/ `at`（时刻）

        六格同时落两处：行的 `inputs` 追加一条
        `revoke:expired:by=…:owner=…:from=…:to=done:at=…:reason=…`（append-only，
        事后读行就能复核），事件 note 记 `item:expired:revoke:…`（事件流带 ts）；
        写入口的返回里另有 `traces`（逐条同一套六格）。「不许默默改」：`refused`
        逐条说为什么没改，`voided` 只列真写成了的编号。

        权限是这一档的全部正当性：兄弟 / 祖父 / 任何非直接父、非 M 的人改别人的项
        ⇒ 受控拒绝 `not_authorized`，一个格都不动。收件人自己那条路不受影响 ——
        他仍是 `ack_items`（`conductor.ack`），不是这里。

        ## 撤销要一并做完的两件（乙件 / 丙件）

        乙件：撤销成功后要提醒收件人，且那条提醒不欠任何动作。提醒的正文是那条留痕
        本身：`REVOKE_POSTS_NOTICE_ROW=False`（缺省）时不另落 `notice` 行 —— 撤 N 条就
        多 N 行，而板项行的 `status` 恒为 `pending`，于是清理动作在读数上让"待办"变多。

        - 提醒的正文仍在，但载体是被撤那一行自己的 `inputs`
          （`revoke:expired:by=…:owner=…:from=…:to=done:at=…:reason=…`，上一节那六格）；
        - 收件人那一侧的读法是 :meth:`revoked_recent_of`（`agent_loop.mailbox_digest`
          每拍投一次，渲染成【最近被撤销的项】）——它只读那条留痕，不进任何 open 计数；
        - 返回的 `notified` 逐条给 `{item_id, owner, kind, expects, carrier, text}`：
          缺省这一档没有 `notice_id` 这一格（撤销不落通知行 ⇒ 那一格只能是空串，而空串是
          一句谎：它暗示"曾经有过一条通知行"），`carrier` 写明提醒从哪儿读得到
          （`revoked_recent@<收件人>`），`text` 是那句正文。没有收件人的项（顶层项）进
          `notification_problems`，撤销本身不回滚。`REVOKE_POSTS_NOTICE_ROW=True` 那一档
          落的是真通知行，所以它那一档才带 `notice_id`（那时它指得出是哪一行）。

        丙件：撤销后 `expects` 清空、原值写进 `expects_was`（`schema.Task` 末尾那一格；
        `validate` 只允许 `done` + `expired` 的行为空）。留着 `expects="ack"` 会让读侧
        看着它像还欠一个 ack，而盘上只许留"账上不欠"这一句。

        返回：`{"checked","voided":[id],"refused":[{"id","why"}],"traces":[…],
        "notified":[…],"notification_problems":[…],"reason"}`；
        拒信只有 `unknown_retired` 那一档多一个 `code` 格（`{"id","code","why"}` ——
        理由码是机器读的那一格：只写一句"它只是静默"是没有根据的结论、也没有理由码）；
        权限拒绝那一档也带 `code`（`no_actor` / `unknown_actor` / `not_authorized`）；
        `expects` 为空的行带 `no_obligation`（它没有可撤的义务）。
        三态：读不成 ⇒ `checked=False`，不许折成"没有要作废的"。
        """
        self._refuse_write_in_snapshot("作废板项（void_items）")
        ids = [str(x) for x in item_ids if str(x).strip()]
        if not ids:
            return {"checked": True, "voided": [], "refused": [], "traces": [],
                    "notified": [], "notification_problems": [],
                    "reason": "没有给要作废的项"}
        reason_text = " ".join(str(why).split())[:120]
        at = S.now_iso()
        # 边界 2：收件人必须静默/已退役（只对 `revoke=False` 那一档成立）。
        # `revoke=True` 那一档的正当性是权限，不是"它叫不醒" —— 见 docstring。
        out: dict[str, Any] = {"checked": True, "voided": [], "refused": [],
                               "traces": [], "notified": [],
                               "notification_problems": [], "reason": ""}
        with self.store.tx("tasks", actor="conductor",
                           note=("item:expired" if not revoke
                                 else "item:expired:revoke")) as tx:
            rows = {str(r.get("task_id")): r for r in tx.rows("tasks")}
            for iid in ids:
                row = rows.get(iid)
                refusal, cur, authority = self._void_item_gate(
                    iid=iid, row=row, rows=rows, by_task_id=by_task_id, revoke=revoke)
                if refusal is not None:
                    out["refused"].append(refusal)
                    continue
                self._void_item_apply(
                    tx=tx, row=row, rows=rows, iid=iid, cur=cur, authority=authority,
                    out=out, by_task_id=by_task_id, reason_text=reason_text, at=at,
                    revoke=revoke)
        verb = "撤销" if revoke else "作废"
        if out["refused"] and not out["voided"]:
            out["reason"] = f"一条都没{verb}（拒绝理由见 refused）"
        elif out["refused"]:
            out["reason"] = f"{verb} {len(out['voided'])} 条、拒 {len(out['refused'])} 条"
        elif revoke and out["traces"]:
            # 撤销那一档的读数里要能直接查到这一笔（六格）—— 不要求读的人再去翻行。
            shown = "；".join(
                f"{t['item_id']} by={t['by']} owner={t['owner'] or '（顶层）'} "
                f"from={t['from']} to={t['to']} at={t['at']} reason={t['reason']}"
                for t in out["traces"][:5])
            out["reason"] = f"撤销 {len(out['voided'])} 条（留痕：{shown}）"
        return out

    def _void_item_gate(self, *, iid: str, row: Mapping[str, Any] | None,
                        rows: Mapping[str, Mapping[str, Any]], by_task_id: str,
                        revoke: bool) -> tuple[dict[str, Any] | None, str, dict[str, Any]]:
        """`void_items` 的逐项前置判据。

        返回 `(refusal, cur, authority)`：`refusal` 非 None ⇒ 这一条不改，原样进
        `out["refused"]` 并跳过；否则 `cur` 是写之前的状态、`authority` 是权限读数
        （写盘那一段的留痕要用它）。刻意用元组而不是再定义一种 dict 返回形状：
        它只在 `void_items` 的一次循环里活着。
        """
        if row is None:
            return {"id": iid, "why": "没有这一项（不是'已经作废'）"}, "", {}
        if not self._is_board_item(row):
            return {"id": iid, "why": "不是板项（kind 为空）⇒ 不归作废管"}, "", {}
        cur = str(row.get("item_state") or "queued")
        if cur == "done":
            return {"id": iid, "why": "已经是终态（重复作废不改任何格）"}, cur, {}
        # ---- 权限：两档都先过这一关 -------------
        # 顺序刻意的：先判"你是谁、能不能动这一条"，再判"这一条该不该作废"。
        # 反过来（先判 deaf 再判权限）会让没有权限的人也能把一条项"推进到
        # 某个分支"，读数上分不清"它没权限"与"它没证明"。
        authority = self._item_authority(rows, by_task_id=by_task_id, row=row)
        if not authority.get("checked"):
            return {"id": iid,
                    "code": str(authority.get("code") or "unknown_actor"),
                    "why": str(authority.get("why") or "权限读不成（fail-closed）")}, cur, authority
        if not authority.get("allowed"):
            return {"id": iid, "code": "not_authorized",
                    "why": str(authority.get("why") or "没有权限改这一条")}, cur, authority
        if str(row.get("expects") or "") == "":
            # 撤销后的行（`done` + `expired`）已经在上面被终态那一档拦下；走到
            # 这里的空 expects 只可能是"通知"那种本来就不要求任何动作的行 ——
            # 没有义务可撤。旧工作区里那些 `revoke-notice@…` 行也正是这一档：它们出生
            # 就是 done+expired、expects 为空 ⇒ 撤不动，于是"撤通知又生成通知"的环在
            # 结构上已经不成立。
            return {
                "id": iid, "code": "no_obligation",
                "why": ("它不要求任何动作（expects 为空）⇒ 没有可撤的义务"
                        "（撤销不是删行）")}, cur, authority
        if not revoke:
            # 作废那一档：只收 expects=ack 的通知，而且收件人必须叫不醒。
            if str(row.get("expects") or "") != "ack":
                return {"id": iid,
                        "why": f"expects={row.get('expects')!r}：要交付的活不许作废"
                               "（只许作废'知道了就好'的通知）"}, cur, authority
            who = str(row.get("role") or "")
            try:
                gate = self.retire_state_of(str(row.get("parent_task_id") or ""))
            except Exception as exc:  # noqa: BLE001 —— 读不成 ⇒ 不许作废（fail-closed）
                gate = {"checked": False, "reason": f"{type(exc).__name__}: {exc}"}
            if not gate.get("checked"):
                return {"id": iid, "why": (
                    f"收件人状态读不成（{gate.get('reason') or '没查成'}）⇒ 不知道它是不是静默，"
                    "不许作废（fail-closed）")}, cur, authority
            if not gate.get("silent"):
                return {"id": iid, "why": (
                    f"{who} 还在跑（state={gate.get('state')}）⇒ 它自己会 ack，不许代它作废")}, cur, authority
            # 静默不等于"永远不会再处理这条通知" —— 兜底表被打掉就会把它叫起来，
            # 它自己能 ack。所以作废的正当性只剩一条：这个号叫不醒了
            # （已销号 / 兜底表被永久抑制）。
            receiver = str(row.get("parent_task_id") or "")
            # 销号名单按父存：收件人自己的父就是"该读哪一份名单"（`rows` 里就有那一行，
            # 不必在事务里再读一趟台账）。它与 `lifeline_suppressed` 各答一半：
            # 一半是"号销了"，一半是"兜底表被打掉了"。
            receiver_parent = str((rows.get(receiver) or {}).get("parent_task_id") or "")
            # `deaf` 只在读成了的"已销号"（或兜底表被永久抑制）上成立。
            # 销号名单读不全（`unknown`）⇒ 证明不了"它叫不醒" ⇒ 不作废：
            # 作废不可逆，而"读不出来"不是"它叫不醒"（fail-closed）。
            verdict = "unknown"
            suppressed = False
            try:
                verdict = self.retired_verdict(receiver, parent=receiver_parent)
                suppressed = bool(CLK.lifeline_suppressed(
                    str(getattr(self.store, "root", "") or ""), receiver))
            except Exception:  # noqa: BLE001 —— 判不了就当它还会醒（不可逆动作取保守侧）
                verdict = "unknown"
                suppressed = False
            if not (suppressed or verdict == "retired"):
                if verdict == "unknown":
                    return {"id": iid, "code": "unknown_retired", "why": (
                        f"{who} 的销号名单读不全（{self._retired_reason()}）⇒ "
                        "证明不了「它叫不醒」，不代作废（作废不可逆）")}, cur, authority
                return {"id": iid, "why": (
                    f"{who} 只是静默，但一条消息或一次委托就会把它叫醒"
                    "（它叫不醒才轮得到代作废）⇒ 先销号，或让它自己 ack"
                    "；作废不可逆，不许拿『它不会再看』当理由")}, cur, authority
        return None, cur, authority

    def _void_item_apply(self, *, tx: Any, row: Mapping[str, Any],
                         rows: Mapping[str, Mapping[str, Any]], iid: str, cur: str,
                         authority: Mapping[str, Any], out: dict[str, Any],
                         by_task_id: str, reason_text: str, at: str,
                         revoke: bool) -> None:
        """`void_items` 的写盘那一段（`out` 就是调用方的返回体：`voided` / `traces` /
        `notified` / `notification_problems` 由这里按原有顺序追加）。
        """
        # ---- 写盘：两档共用"直写 + 终态"，留痕各记各的 -------------------
        owner = str(row.get("parent_task_id") or "")
        new = dict(row)
        new["item_state"] = "done"
        new["item_close"] = "expired"
        if revoke:
            # 丙件：撤销之后这一行不再欠任何动作 ——
            # `expects` 清空、原值进 `expects_was`（schema 只允许 done/expired
            # 的行为空）。留着 `expects="ack"` 会让读的人看着它像还欠一个 ack，
            # 而读侧（open_items_of / board / ack_items）其实都已经不数它了。
            new["expects_was"] = str(row.get("expects") or "")
            new["expects"] = ""
        inputs = list(new.get("inputs") or [])
        if revoke:
            # 六格：谁（by）/ 归谁（owner）/ 为什么（reason）/ 原状（from）/
            # 新状（to）/ 何时（at）。append-only，事后读行就能复核这一笔。
            mark = (f"revoke:expired:by={by_task_id}:owner={owner or '（顶层）'}:"
                    f"from={cur}:to=done:at={at}:reason={reason_text}")
            note = (f"item:expired:revoke:by={by_task_id}:"
                    f"owner={owner or '（顶层）'}:from={cur}:to=done:at={at}")
        else:
            mark = f"void:expired:{by_task_id}:{reason_text}"
            note = "item:expired"
        inputs.append(mark)
        new["inputs"] = inputs
        task = S.Task(**{k: v for k, v in new.items()
                         if k in S.Task.__dataclass_fields__})
        task.validate()
        tx.upsert("tasks", task.to_dict(), note=note)
        out["voided"].append(iid)
        trace = {
            "item_id": iid, "by": str(by_task_id), "owner": owner,
            "reason": reason_text, "from": cur, "to": "done", "at": at,
            "close": "expired", "mode": ("revoke" if revoke else "void"),
            "authority": str(authority.get("mode") or ""),
            # 刻意没有 `notice_id` 这一格：缺省这一档不落通知行，留一个恒空的键等于
            # 说"曾经有过一条通知行"。`REVOKE_POSTS_NOTICE_ROW=True` 那一档真落了行，
            # 它才补上这一格。
        }
        out["traces"].append(trace)
        if not revoke:
            return
        # ---- 乙件：缺省只留痕，不另落通知行 --------------------------------------
        #
        # 口径是「撤销时自动提醒收件人，且不要 ack」。另落一条新 `tasks` 行
        # （`kind="notice"`、`done`/`expired`）会让撤 N 条就多 N 行：清理动作让 `tasks`
        # 行数变多，而板项行的 `status` 恒为 `pending`，于是那 N 行在状态报告/网页上又
        # 变成"N 条待办"。
        #
        # 所以提醒不走新行：被撤那一行自己的 `inputs` 已经落了六格留痕
        # （`revoke:expired:…`，上面那一笔 append-only 的 `mark`），收件人那一侧的
        # 读口 `revoked_recent_of` 读的就是它，`agent_loop.mailbox_digest` 每一拍把最近
        # N 条渲染成【最近被撤销的项】。于是新增 notice 行 = 0，而"谁撤的 / 为什么 /
        # 你不需要再处理它"一个字都没少。
        if not self.REVOKE_POSTS_NOTICE_ROW:
            if not owner:
                # 顶层项没有收件人 ⇒ 没有要提醒的人。如实记读数，不编一个收件人。
                out["notification_problems"].append(
                    f"{iid}：这一条没有收件人（顶层项）⇒ 没有要提醒的人（撤销本身照旧）")
                return
            out["notified"].append({
                "item_id": iid, "owner": owner,
                "kind": "", "expects": "",
                # 载体：不是一行新台账，而是被撤行自己的留痕 + 收件人那一侧的读口。
                "carrier": f"revoked_recent@{owner}",
                "text": (f"你名下 {iid}（{_board_item_summary(row)}）已被 {by_task_id} 撤销"
                         f"（理由：{reason_text}），你不需要再处理它"),
            })
            return
        # ---- `REVOKE_POSTS_NOTICE_ROW=True` 那一档：另落一条 done+expired 的通知行 ----
        # 保留的唯一理由是反真空（判据把 `REVOKE_POSTS_NOTICE_ROW` 打开，证明"新增行数
        # = 0"真的在数行）；正文与"为什么它必须落成 done + expired"见
        # `_revocation_notice_row` 的 docstring。
        owner_depth = int((rows.get(owner) or {}).get("depth") or 0) + 1
        notice = self._revocation_notice_row(
            row=row, item_id=iid, owner=owner, by_task_id=str(by_task_id),
            reason=reason_text, depth=owner_depth)
        if notice is None:
            out["notification_problems"].append(
                f"{iid}：没有投撤销通知（没有收件人，或它本身是一条撤销通知）")
        else:
            try:
                notice_id = self._row_with_id(tx, notice,
                                              note="item:notice:revoked")
            except Exception as exc:  # noqa: BLE001 —— 通知没开成要如实报
                out["notification_problems"].append(
                    f"{iid}：撤销通知没开成（{type(exc).__name__}: {exc}）"
                    "⇒ 撤销照旧（它是正文），但收件人不会收到这条通知")
            else:
                trace["notice_id"] = notice_id
                out["notified"].append({
                    "item_id": iid, "notice_id": notice_id,
                    "owner": owner, "kind": "notice", "expects": "",
                    "text": str(notice.get("detail") or ""),
                })

    def open_items_many(self, items: Sequence[Mapping[str, Any]], *,
                        details: Sequence[str] | None = None) -> list[str]:
        """一笔事务开 N 条工作项（广播 / 停止通知那一族）。返回的编号顺序与 `items` 一致。

        `items` 的每一格与 :meth:`open_item` 的关键字参数同名；`details` 给了就逐条
        把那一句写进 `detail`（与逐条调 :meth:`set_item_detail` 的落盘结果相同）。

        ## 为什么要有它（2026-10-27 实测）
        改前"给 N 个人各开一条 ack 板项"= 每人两笔事务（`open_item` + `set_item_detail`），
        每笔都是一次取锁 + 一次整表读 + 一次整表写 + 一次事件追加。实测
        （`temp/r_be2_board_write_cost.py`）：42 ms/条（50 行台账）→ 93 ms/条（500 行），
        于是 `broadcast` 给 12 个人要 0.5–1.1 s，而这 12 条写的是同一张表、同一个时刻。

        ## 与逐条路径的关系（判据：落盘逐字节一致）
        表内容与"逐条 `open_item` + 逐条 `set_item_detail`"逐字节相同；事件流也逐条
        相同（每条两项：`item:<kind>` 与 `item:detail`）。差别只有提交标记：一笔事务
        一条 `commit` 行，逐条路径是 2N 条 —— 而 `commit` 行带 `ts` / `batch`（pid + 进程内
        序号），任何两次运行都不相同，所以判据按"归一化之后的事件序列"比
        （`tests/test_board_batch_write.py`）。
        ## 全成或全不成
        一笔事务 ⇒ 批内任何一条抛（`schema.Task.validate` 不过、取号失败）⇒ 整批不落盘：
        `store.tx` 的提交块在异常时不写任何表、不追加任何事件。逐条路径没有这个性质 ——
        它写到一半失败会在盘上留下前几条，而调用方只看到一次异常。
        """
        specs = [dict(x) for x in items]
        if not specs:
            return []
        texts: list[str] = ["" for _ in specs]
        if details is not None:
            if len(details) != len(specs):
                raise ValueError(
                    f"details 与 items 必须一一对应（收到 {len(details)} / {len(specs)}）")
            # 与 `set_item_detail` 同一条口径：空说明等于"没有说明"，不写第二笔。
            texts = [str(t or "").strip() for t in details]
        self._refuse_write_in_snapshot("批量建行（open_items_many）")
        out: list[str] = []
        with self._id_lock:
            with self.store.tx("tasks", actor="conductor", note="items:batch") as tx:
                for spec, text in zip(specs, texts):
                    row = self._item_row(**spec)
                    note = f"item:{row.get('kind')}"
                    tid = self._row_with_id(tx, row, note=note)
                    if text:
                        row["detail"] = text
                        task = S.Task(**{k: v for k, v in row.items()
                                         if k in S.Task.__dataclass_fields__})
                        task.validate()
                        tx.upsert("tasks", task.to_dict(), note="item:detail")
                    out.append(tid)
        return out

    def open_retire_question(self, *, parent_task_id: str, child_task_id: str,
                             parent_role: str = "", child_role: str = "",
                             name: str = "", depth: int | None = None,
                             reading: Mapping[str, Any] | None = None
                             ) -> dict[str, Any]:
        """子代理已静默 ⇒ 在父名下开一条"要不要销号它"的问询板项（只问，绝不代做）。

        业主 2026-10-26 逐字（见 `retire_question_text` 的模块那一份）：父代理没有
        "处置静默子"的意识，所以这件事由框架在子代理交差之后问一次。三条边界：

        1. 只问不销：本方法一个字节都不碰名册，`conductor.retire_child` 仍是唯一入口，
           而且它自己那道"只对静默生效"的闸一个字没改（这里不给它开后门）；
        2. 问的前提必须是真的：先读 `retire_state_of` 的三态，只有读成了、而且真的是
           `silent` 才开这一条 —— 一个还挂着计时器 / 还在跑的子代理不该收到"已静默"
           这句话（那是把读数写成谎）；
        3. 三态：读不成 ⇒ `checked=False, opened=False` + 理由，不问（"要不要销号"
           这个问题问错一次，代价是父照着一个不成立的结论去销号）。

        `expects="work"` 是刻意的（见 `EXPECT` 那一段的取舍）：这条项不是"读一下就算办完"
        的通报 —— 它要父做一个决定（销 / 不销），所以不许被"渲染即收口"那一档代收
        （`_settle_if_informational` 只在 `expects == "ack"` 时收口）。不处理它就会一直
        留在板上，而那正是业主点名的"拖着结不了项"。

        幂等：同一个子代理只开一条（判据是 `input_key`：`retire-ask@<子编号>`），
        板项已消之后再问才会再开一条 —— 那时是父真的没有处置，重问是对的。

        返回 `{"checked","opened","item_id","silent","state","state_label","text",
        "duplicate","why","reason"}`。
        """
        out: dict[str, Any] = {"checked": False, "opened": False, "item_id": "",
                               "silent": False, "state": AGENT_STATE_UNKNOWN,
                               "state_label": "", "text": "", "duplicate": False,
                               "why": "", "reason": ""}
        pid = str(parent_task_id or "")
        cid = str(child_task_id or "")
        if not pid or not cid:
            out["reason"] = "没有父 / 子的台账号 ⇒ 这条问询没有落点（不问）"
            return out
        if pid == cid:
            out["reason"] = "父与子是同一个编号 ⇒ 不问（自己销自己这件事没有对象）"
            return out
        got = dict(reading) if isinstance(reading, Mapping) else self.retire_state_of(cid)
        out.update({"checked": bool(got.get("checked")),
                    "silent": bool(got.get("silent")),
                    "state": str(got.get("state") or AGENT_STATE_UNKNOWN),
                    "state_label": str(got.get("state_label") or ""),
                    "reason": str(got.get("reason") or "")})
        if not out["checked"]:
            out["why"] = (f"读不到 {cid} 是不是静默（{out['reason'] or '没查成'}）"
                          " ⇒ 不问（问的前提是「已静默」这句话是真的）")
            return out
        if not out["silent"]:
            out["why"] = (f"{cid} 现在不是静默（{out['state_label'] or out['state']}）"
                          " ⇒ 不问，也不能销")
            return out
        try:
            child_row = self._task(cid) or {}
        except Exception as exc:  # noqa: BLE001 —— 读不到那一行只影响措辞
            child_row = {}
            out["reason"] = f"行读不成（{type(exc).__name__}: {exc}）"
        role_text = str(child_role or child_row.get("role") or "")
        shown = str(name or "")
        if not shown:
            shown = self._roster_name_of(owner=pid, task_id=cid)
        text = retire_question_text(name=shown, task_id=cid, role=role_text)
        out["text"] = text
        key = f"retire-ask@{cid}"
        try:
            open_now = [dict(r) for r in self.open_items_of(pid)
                        if str(r.get("input_key") or "") == key]
        except Exception as exc:  # noqa: BLE001 —— 读不成不许猜"已经问过了"
            out["why"] = f"板上有没有问过这一条读不成（{type(exc).__name__}: {exc}）⇒ 不问"
            return out
        if open_now:
            out["duplicate"] = True
            out["item_id"] = str(open_now[0].get("task_id") or "")
            out["opened"] = False
            out["why"] = (f"名下已经有一条没消的问询（{out['item_id']}）⇒ 不重复开"
                          "（同一个子代理只问一条，消了之后才会再问）")
            return out
        parent_row: dict[str, Any] = {}
        try:
            parent_row = self._task(pid) or {}
        except Exception:  # noqa: BLE001 —— 只影响 depth 的缺省
            parent_row = {}
        want_depth = int(depth or 0) or (int(parent_row.get("depth") or 1) + 1)
        try:
            item_id = self.open_item(
                kind="notice", role=str(parent_role or parent_row.get("role")
                                       or S.CONDUCTOR_ROLE),
                expects="work", action="notice", summary=text,
                # 这一条是框架发起的（不是某个角色冒充用户）：`called_by="conductor"`
                # 与 `open_top_level_run` 的构造行同一个口径。
                called_by="conductor", parent_task_id=pid, depth=max(1, want_depth),
                input_key=key)
        except Exception as exc:  # noqa: BLE001 —— 开不成要如实说，不许静默
            out["why"] = f"问询项没开成（{type(exc).__name__}: {exc}）"
            return out
        out.update({"opened": True, "item_id": str(item_id), "why": ""})
        return out

    def _roster_name_of(self, *, owner: str, task_id: str) -> str:
        """`task_id` 在 `owner` 那份名册上的名字（读不到 ⇒ 空串，绝不编一个名字）。

        名册名的读法只有一处（`secretary.name_of`）：在这里另写一份"按行猜名字"
        会与它漂成两套，而两套读法对"它叫什么"给出不同答案时没有任何地方会报错。
        """
        sink = self.roster_sink if self.roster_sink is not None else self.secretary
        if sink is None:
            return ""
        look = getattr(sink, "name_of", None)
        if not callable(look):
            return ""
        try:
            got, _why = look(owner=str(owner), task_id=str(task_id))
        except Exception:  # noqa: BLE001 —— 名字读不到只影响措辞（用编号照样能销号）
            return ""
        return str(got or "")

    # ------------------------------------------------------------- 迁移图（Q24）
    #: 合法迁移图的三列判词（前进 / 幂等 / 倒退）。
    ITEM_MOVE_FORWARD: str = "forward"
    ITEM_MOVE_SAME: str = "same"
    ITEM_MOVE_BACK: str = "back"

    #: 合法迁移图本体：逐对给判词，键是 `(现态, 想去)`，值只能是上面三档之一。
    #:
    #: 为什么逐对写、而不是"比一下 `schema.ITEM_STATES` 里的序数"（2026-10-26 Q24 的原病）：
    #: 序数比较只有两列（往后 / 不往后），"同一终态重复设置"必然被折进"不往后"那一支 ——
    #: 于是 `done → done` 撞上"不许倒退或重复迁移"。而"重复设置是不是错"根本不是一条单调性：
    #: 终态重复是幂等（D12 之后信息型板项渲染那一拍就收口成 `done`，随后 ack 再推一次是
    #: 正常次序），非终态的重复是丢读数（`seen → seen`：每一步的 `seen_by` / `seen_step`
    #: 都不一样），两者只能由这张表逐对说清。
    #:
    #: 判据里也不许补一句 `want == have ⇒ ok` 兜底：这张表是穷举的，缺哪一对由
    #: `tests/test_setting_the_same_terminal_state_is_idempotent.py` 当场报出来。
    #: `block` 不是"没有写入者"的状态：优雅停止由 `stopctl.block_remaining_tasks` 把它写下
    #: （status 与名下板项两根轴一起翻），而"从 block 出去"在这张表里一律 `back`。
    #: 唤醒走的是另一条路：`Conductor.wake_blocked` 直写两根轴（block → running / queued）
    #: 并立刻 `S.Task.validate()` 自校。所以这张表守的是"状态机不许倒退"，
    #: 它不守"停在这里就永远出不去" —— 那个说法在 2026-10-29 之后是旧口径。
    ITEM_MOVES: dict[tuple[str, str], str] = {
        # queued：起点，只能往前
        ("queued", "queued"): ITEM_MOVE_BACK,      # 非终态的同一格重复：不是幂等（每一步的读数会变）
        ("queued", "claimed"): ITEM_MOVE_FORWARD,
        ("queued", "seen"): ITEM_MOVE_FORWARD,
        ("queued", "done"): ITEM_MOVE_FORWARD,     # 空口 ack 的闸另判（见 `_set_item` 第 2 条）
        ("queued", "block"): ITEM_MOVE_FORWARD,
        # claimed：接手之后同样只能往前
        ("claimed", "queued"): ITEM_MOVE_BACK,
        ("claimed", "claimed"): ITEM_MOVE_BACK,    # 同上：非终态的重复设置不是幂等
        ("claimed", "seen"): ITEM_MOVE_FORWARD,
        ("claimed", "done"): ITEM_MOVE_FORWARD,    # 空口 ack 的闸另判
        ("claimed", "block"): ITEM_MOVE_FORWARD,
        # seen：读进来了，只差收口
        ("seen", "queued"): ITEM_MOVE_BACK,
        ("seen", "claimed"): ITEM_MOVE_BACK,
        ("seen", "seen"): ITEM_MOVE_BACK,          # 重复读：每一步的读数都不一样 ⇒ 拒（既有口径）
        ("seen", "done"): ITEM_MOVE_FORWARD,
        ("seen", "block"): ITEM_MOVE_FORWARD,
        # done：终态。重复设置同一格是幂等命中（零写入），倒退回任何一格都拒
        ("done", "queued"): ITEM_MOVE_BACK,
        ("done", "claimed"): ITEM_MOVE_BACK,
        ("done", "seen"): ITEM_MOVE_BACK,
        ("done", "done"): ITEM_MOVE_SAME,
        ("done", "block"): ITEM_MOVE_FORWARD,
        # block：停在这里。写下它的是 `stopctl.block_remaining_tasks`，把一条停住的项翻回
        # queued 的是 `Conductor.wake_blocked`（直写，不走这张表）。"从 block 出去"在这张表里
        # 一律拒；同一格重复设置同样是幂等。
        ("block", "queued"): ITEM_MOVE_BACK,
        ("block", "claimed"): ITEM_MOVE_BACK,
        ("block", "seen"): ITEM_MOVE_BACK,
        ("block", "done"): ITEM_MOVE_BACK,
        ("block", "block"): ITEM_MOVE_SAME,
    }

    @staticmethod
    def _evidence_closed_item_prefixes() -> tuple[str, ...]:
        """只能由框架凭证据收口的义务项前缀（`b-register@` / `v-resubmit@`）。

        为什么是这两族（业主 2026-11-05）：「必须收录」与「必须重送」都是 `expects=work`
        的活，它们的收口条件是盘上的事实（正文 + `reviewed=true` / 更新的干净「成立」行），
        不是收件人的一句话。前缀的定义只有一处（`obligations.REGISTER_PREFIX` /
        `RESUBMIT_PREFIX`），这里惰性读过去，不抄第二份字符串。
        """
        from . import obligations as _OBL   # 惰性：conductor 是底层，模块顶层不引它

        return (str(_OBL.REGISTER_PREFIX), str(_OBL.RESUBMIT_PREFIX))

    @staticmethod
    def item_move(cur: str, state: str) -> str:
        """合法迁移图的唯一读数：`(现态, 想去)` ⇒ `forward` / `same` / `back`。

        三列都由上面那一张表判出来，这里只做取表这件事（顺序不在这里、也不在 `_set_item`
        里另算一份）。两条口径：

        - 认不出的现态（老行 / 坏值）按 `queued` 算 —— 与 `_set_item` 从前的口径一致；
        - 目标态不在 `schema.ITEM_STATES` 里 ⇒ `ValueError`（那是调用方的编程错误，
          从前由 `list.index` 抛同一个类型；折成"倒退"会让一句假话盖住它）。

        缺表的一对按 `back` 处理：宁可拒，也不许在没判过的边上写字。
        """
        if state not in S.ITEM_STATES:
            raise ValueError(f"目标态必须是 {S.ITEM_STATES} 之一，收到 {state!r}")
        have = cur if cur in S.ITEM_STATES else "queued"
        return Conductor.ITEM_MOVES.get((have, state), Conductor.ITEM_MOVE_BACK)

    def _set_item(self, task_id: str, *, state: str, close: str = "",
                  by_task_id: str = "", step: int | None = None,
                  note: str = "", by_evidence: bool = False,
                  ) -> tuple[str, str, bool]:
        """工作项状态迁移的唯一写入点。返回 `(落成的状态, 问题, changed)`。

        第三格 `changed` 是"真写了行"与"命中同一终态、零写入"的分界（2026-10-26 Q24）：
        - `True`：真迁移 —— 落了一行、记了一笔事件；
        - `False`：没有真迁移（幂等命中 / 被拒 / 空口 ack）—— 一行都没写、一笔事件
          都没记、任何一个计数都没动；返回的状态要么是原样那个终态，要么是空串（被拒）。

        判决只有一个来源：`Conductor.item_move`（逐对迁移图，三列 forward / same / back）。
        `_set_item` 不再自己比序数，四条按顺序判：

        1. `back`（倒退，或非终态的重复设置）⇒ 零写入，返回 `("", 那一句, False)`；
        2. 空口 ack（业主 A5 的闸，不拆）：目标 `done` 而现态还没到 `seen` ——
           判据就是图里 `(现态, "seen")` 是不是 `forward` ⇒ 返回
           `("ack_unbacked", 那一句, False)`，只记读数、不写状态（`by_evidence=True` 只给
           框架凭证据收口的调用方 —— 那不是"收件人 ack"，A5 那条判据对它不成立；
           收件人自己那一条路一个字都没放宽，缺省 `False`）；
        3. `same`（同一终态重复设置）⇒ 返回 `(state, "", False)`，零写入。
           这不是错误：D12 之后信息型板项在渲染那一拍就收口成 `done`，随后
           `close_item` / `conductor.ack` 再推一次 `done` 是正常次序；
        4. `forward` ⇒ 写列 → `schema.Task.validate` → `tx.upsert`，返回 `(state, "", True)`。

        ## `note`（D-68）：这一笔事件自己的来路
        状态是列（给当前值），事件才是历史（给来路）。消项那一侧要落"谁在第几步确认的"
        —— 那一格装不进 `tasks`（列里没有"确认步号"这一格），所以它落在事件 note 上。
        缺省空串 ⇒ 沿用从前的 `item:<state>`，既有调用方的事件逐字不变。
        """
        self._refuse_write_in_snapshot("改板项状态（_set_item）")
        with self.store.tx("tasks", actor="conductor") as tx:
            row = next((r for r in tx.rows("tasks")
                        if str(r.get("task_id")) == str(task_id)), None)
            if row is None:
                return "", f"没有这一项（task_id={task_id!r}）—— 不是'已经做完'", False
            if not self._is_board_item(row):
                return "", f"{task_id} 不是板项（kind 为空）⇒ 它的状态不由状态机管", False
            cur = str(row.get("item_state") or "queued")
            move = self.item_move(cur, state)
            if move == self.ITEM_MOVE_BACK:
                return "", f"{task_id} 已经到过 {cur!r}（不许倒退或重复迁移）", False
            if (state == "done" and not by_evidence
                    and self.item_move(cur, "seen") == self.ITEM_MOVE_FORWARD):
                return "ack_unbacked", (f"{task_id} 还没有 seen（没被读进任何一步）就收到 ack ⇒ "
                                        "空口 ack：读数留着，状态不动（业主 A5）"), False
            if move == self.ITEM_MOVE_SAME:
                return state, "", False
            row["item_state"] = state
            if state == "seen":
                # `seen_by` 与 `seen_step` 必须"都在或都不在"（`schema.Task.validate`
                # 逐字要求：半份读数比没有更糟）⇒ 没有步号时连 `seen_by` 一起不写。
                if step is None:
                    row["seen_by"], row["seen_step"] = "", None
                else:
                    row["seen_by"], row["seen_step"] = str(by_task_id), int(step)
                # K9：角色地址的项在被读进某一步的那一刻领取——把收件实例写上行。
                # 这不是"挑一个"：读它的人就是它现在的收件人；此后 `open_items_of`
                # 按实例那一格认它，销号闸也看得见（不再有无主的项永远悬着）。
                if not str(row.get("instance") or ""):
                    claimed = _instance_of_task(self, str(by_task_id or ""))
                    if claimed:
                        row["instance"] = claimed
            if state == "done":
                row["item_close"] = str(close)
            task = S.Task(**{k: v for k, v in row.items() if k in S.Task.__dataclass_fields__})
            task.validate()
            tx.upsert("tasks", task.to_dict(), note=note or f"item:{state}")
        return state, "", True

    def claim_item(self, task_id: str, *, by_task_id: str = "") -> tuple[str, str]:
        """`queued → claimed`（接手：这一项被某个实例接下了）。"""
        state, why, _changed = self._set_item(task_id, state="claimed",
                                              by_task_id=by_task_id)
        return state, why

    def mark_item_seen(self, task_id: str, *, by_task_id: str, step: int) -> tuple[str, str]:
        """`→ seen`（渲染：这一项被读进某一步的提示词）。

        信息型（`INFORMATIONAL_ITEM_KINDS`）在这一拍就收口 —— "seen 就是 ack"，
        见 `_settle_if_informational`。返回落成的状态：收口了是 `"done"`，其余是 `"seen"`
        （调用方今天只判"空串 = 没标成"与 `"ack_unbacked"`，两档都不受影响）。
        """
        state, why, _changed = self._set_item(task_id, state="seen", by_task_id=by_task_id,
                                              step=step)
        if state != "seen":
            return state, why
        return self._settle_if_informational(task_id, step=step)

    def _settle_if_informational(self, task_id: str, *, step: int) -> tuple[str, str]:
        """信息型的板项：读进某一步的提示词 ⇒ 同拍收口（`done` + `acked`）。

        三条都得成立才收口，缺一条就不动它（宁可留在 `seen`，也不把"要办事的"读成"办完了"）：
        1. `kind ∈ INFORMATIONAL_ITEM_KINDS`；
        2. `input_key` 不在 `ACK_REQUIRED_ITEM_PREFIXES`（那几档要模型自己 ack）；
        3. `expects == "ack"`（`item_close="acked"` 只与它配对；`work` 项要 `completed`，
           那不是"读一下就完了"的东西）。

        返回 `(落成的状态, 问题)`：收口了是 `("done", "")`，不属于信息型就是 `("seen", "")`。
        读不成 / 写不成 ⇒ 也是 `("seen", 那一句)` —— 留在 `seen` 是可见的（板上
        `by_state["seen"]`、`open_items_of` 与销号门的拒信都还看得见它），不折成"已经收口"。
        """
        try:
            row = self._task(str(task_id)) or {}
        except Exception as exc:  # noqa: BLE001 —— 读不成不猜，留在 seen
            return "seen", f"{task_id} 收口前读不成（{type(exc).__name__}: {exc}）"
        # 问的是"哪一类板项"（信息型的那几类在渲染那一拍就收口），不是"是不是板项" ——
        # 轴由 `_is_board_item` 判，这里只按 kind 取值分流，所以就地读 `kind` 是对的。
        if str(row.get("kind") or "") not in INFORMATIONAL_ITEM_KINDS:
            return "seen", ""
        key = str(row.get("input_key") or "")
        if any(key.startswith(prefix) for prefix in ACK_REQUIRED_ITEM_PREFIXES):
            return "seen", ""
        if str(row.get("expects") or "") != "ack":
            return "seen", ""
        # 这里从前还有一句 `item_state == "done" ⇒ ("done", "")` 的幂等前置：它是"同一终态
        # 重复设置"在状态机外面的第二份实现。2026-10-26 Q24 把它删了，因为改后它不可达 ——
        # 走到这一行说明 `mark_item_seen` 的 `_set_item(seen)` 已经把状态改成了 `seen`
        # （已在 `done` 的项在那一步就被迁移图判成 `back`、根本进不到收口这一支）。
        state, why, _changed = self._set_item(
            task_id, state="done", close="acked",
            note=(f"item:done:close=acked（信息型：第 {int(step)} 步渲染即收口，"
                  "业主 2026-10-27）"))
        if state != "done":
            return "seen", why
        return "done", ""

    def set_item_detail(self, task_id: str, detail: str) -> tuple[str, str]:
        """把一句人可读的说明写进板项（`detail` 位）。返回 `(落成的说明, 问题)`。

        为什么正文不落这里：甲形态那七格里没有正文字段 —— 交差正文的正式落点是
        `handoffs.jsonl`（一行一份、有编号、`manuscripts.read` 读得回全文，真机 1562 行都在那儿）。
        板项只需要回答"有没有一条回报"以及"它说了什么 / 没留下什么"
        （框架通报那一档的 body 是逐字那句「（它没有留下结论）」）。
        """
        text = str(detail or "").strip()
        if not text:
            return "", "说明是空的 ⇒ 什么都不写（空说明与没有说明是两件事）"
        self._refuse_write_in_snapshot("改板项说明（set_item_detail）")
        with self.store.tx("tasks", actor="conductor") as tx:
            row = next((r for r in tx.rows("tasks")
                        if str(r.get("task_id")) == str(task_id)), None)
            if row is None:
                return "", f"没有这一项（task_id={task_id!r}）"
            row["detail"] = text
            task = S.Task(**{k: v for k, v in row.items() if k in S.Task.__dataclass_fields__})
            task.validate()
            tx.upsert("tasks", task.to_dict(), note="item:detail")
        return text, ""

    def re_address_item(self, task_id: str, *, parent_task_id: str,
                        recipient_instance: str = "") -> tuple[str, str]:
        """把一条未收口的板项改投给另一个收件人。返回 `(落成的说明, 问题)`。

        现场（SGN1 的「签落地 ⇒ 真把 B 叫醒」）：未在册那一支要先开板项（信先落在板上，
        B 一起来就读得到），再看有没有 B 的台账号可投；一个都没有时真召一趟 ——
        那一趟的 `task_id` 是这一步才有的，于是板项要补上「收件人的台账号」
        （`parent_task_id` 那一格的口径，见 `_item_authority` / `open_items_of`）。
        不补这一格，板项就开成无主：召来的 B 看不到自己为什么被叫起来（lp-ball 的
        `b-register@` 两条至今 `parent_task_id=None` 就是这一档）。

        只动板项行的地址：`kind` 空的行是台账号，它的父子关系是派活时定的，不改；
        深度按新父那一行 +1 重算（`capabilities.audit_task_ledger` 按这条链核）。
        """
        tid = str(task_id or "")
        parent = str(parent_task_id or "")
        if not tid:
            return "", "没有板项号 ⇒ 什么都不改"
        if not parent:
            return "", "没有收件人的台账号 ⇒ 不把板项改成无主"
        self._refuse_write_in_snapshot("改板项收件人（re_address_item）")
        with self.store.tx("tasks", actor="conductor") as tx:
            rows = list(tx.rows("tasks"))
            row = next((r for r in rows if str(r.get("task_id")) == tid), None)
            if row is None:
                return "", f"没有这一项（task_id={tid!r}）"
            if not Conductor._is_board_item(row):
                return "", "这一行不是板项 ⇒ 不改它的父（台账号的父子关系是派活时定的）"
            if str(row.get("item_state") or "") == "done":
                return "", "这一项已经收口 ⇒ 不改收件人"
            prow = next((r for r in rows if str(r.get("task_id")) == parent), None)
            if prow is None:
                return "", f"收件人 {parent!r} 在台账里没有那一行 ⇒ 不改"
            row["parent_task_id"] = parent
            row["instance"] = str(recipient_instance or "")
            row["depth"] = max(1, int(prow.get("depth") or 1)) + 1
            task = S.Task(**{k: v for k, v in row.items()
                             if k in S.Task.__dataclass_fields__})
            task.validate()
            tx.upsert("tasks", task.to_dict(), note="item:re-address")
        return (f"板项 {tid} 改投到 {parent} 名下"
                + (f"（实例 {recipient_instance}）" if str(recipient_instance or "") else "")), ""

    def close_item(self, task_id: str, *, close: str, by_task_id: str = "") -> tuple[str, str]:
        """`→ done`（行为完成）：`close="acked"`（知道了）或 `"completed"`（做完了）。

        已经在 `done` 的项再推一次 `done` 是幂等命中（`_set_item` 的 `changed=False`）：
        于是"渲染那一拍就收口、随后 ack 再推一次"这条正常次序不再被当成倒退（Q24）。
        """
        state, why, _changed = self._set_item(task_id, state="done", close=close,
                                              by_task_id=by_task_id)
        return state, why

    def close_item_by_evidence(self, task_id: str, *, close: str,
                               why: str = "") -> tuple[str, str]:
        """框架凭证据收口一项（不是收件人 ack）：`close="completed"` / `"expired"`。

        为什么需要它（业主 2026-11-01 的裁定把"打回"变成一条义务之后）：
        `v-resubmit@` 那条义务的收口条件是"同一条命题出现更新的干净「成立」行"，
        放弃原命题时则要把它作废 —— 两种都不是"收件人读过了"，而
        `_set_item` 的空口 ack 闸（业主 A5）只对"目标 done 而现态还没 seen"生效，
        于是凭证据收口会一头撞在 `ack_unbacked` 上、那条项永远留在板上，
        反过来把销号（`retire_integrity`）锁死。这一条只做一件事：把那道闸按
        `by_evidence=True` 关掉，收件人自己那条路一个字节都没放宽。

        `why` 只进事件 note（"谁凭哪条证据收的"），不写进 `detail`：那一格是给
        收件人读的，不该被框架读数盖掉。返回 `(落成的状态, 问题)`。
        """
        state, problem, _changed = self._set_item(
            task_id, state="done", close=str(close or ""), by_evidence=True,
            note=(f"item:done:close={str(close or '')}:evidence"
                  + (f"（{str(why)[:120]}）" if why else "")))
        return state, problem

    def ack_items(self, item_ids: Sequence[str], *, by_task_id: str, note: str = "",
                  close: str = "acked") -> dict[str, Any]:
        """收件人自己把名下的板项推到 `done`（`conductor.ack` 的唯一判定与写入点）。

        业主 D-68 逐字：「就做手，不兜底。在"销号"时，如果 task_board 没清，发提醒，
        不准直接销号」。改前这个动作在代码里根本不存在 —— `close_item` 只有一个调用者
        （`agent_loop._ack_stop_notice`，只 ack 停止通知），于是模型只能在回复里说
        "已处理"，而盘上那条项永远停在 `seen`（真机 `projects/sylow3`：45 条 seen
        + 3 条 queued）。这一件补的就是那只手。

        返回 `{"checked","ok","state","acked","already_done","refused","unknown",
        "missing","not_yours","refusal_codes","results","count","requested",
        "by_task_id","note","reason"}`，几档 `state`：

        - `acked`：给到的每一条都到 `done`；
        - `partial`：成了一些、拒了一些（`refused` 逐条给 `item_id` / `code` / `reason`）；
        - `refused`：一条都没成（`refusal_codes` 去重给出理由码）；
        - `nothing`：调用方一条都没给（一个字节都不写）；
        - `unknown`：台账读不成（`checked=False`）—— 这是"没查成"，不是"都拒了"。

        三条判定（每一条都对应一种真实的错手）：
        1. 只许 ack 收件人是自己的项（`parent_task_id == by_task_id`）⇒ 否则 `not_yours`。
           父代理最容易犯的那一手就是"看见孩子名下挂着项、顺手替它确认"，
           那会让「孩子还没看」这件事实消失 —— 而它正是 ack 存在的理由；
        2. 只许 ack 板项（`kind` 非空）⇒ 否则 `not_board_item`（代理行不归状态机管）；
        3. 状态机仍然只往后走：没 `seen` 的项先补记一次 `seen`（见下面那一段），
           绝不跳过 `seen` 直接 `done`（业主 A5 的空口 ack 闸不拆）。

        ## 为什么 `queued` 的项也能 ack（这一条是 D-68 的关键取舍）
        ack 是收件人的动作，不是投递器的：真机那 3 条 `queued` 是旧代码没投出去的项，
        若 ack 只认 `seen`，它们就永远清不掉 ⇒ 销号门与 final 门会把整棵树永久卡死。
        所以对还没 `seen` 的项先补记一次 `seen`（`seen_by` = 本次的收件人），
        而"这一项从没被投递过"这件事逐字写进那条 done 事件的 note（`step=未读`）——
        状态机的列上给了一个合法的占位（`seen_step=0`，`schema` 要求两格都在），
        真相在事件里，不在列上。

        ## `already_done` 从哪来（2026-10-26 Q24）
        入口不另判一次 `item_state == "done"`：那只手会把"同一终态重复设置"这条判断
        抄成第二份。这里照状态机的结论 —— `_set_item` 回 `changed=False` 就是"它本来就在
        这个终态"，于是读数是 `already_done`、`acked` 照旧算成、事件与计数一个字节都不动。
        """
        ids = [str(x) for x in (item_ids or ())]
        out: dict[str, Any] = {
            "checked": True, "ok": False, "state": "refused",
            "acked": [], "already_done": [], "refused": [], "unknown": [],
            "missing": [], "not_yours": [], "refusal_codes": [], "results": [],
            "count": 0, "requested": len(ids), "by_task_id": str(by_task_id or ""),
            "note": str(note or ""), "reason": "",
        }
        me = str(by_task_id or "")
        if not me:
            out["checked"] = False
            out["state"] = "unknown"
            out["reason"] = ("没有收件人（by_task_id 是空的）⇒ 不知道该确认谁名下的项"
                             "（不猜一个收件人）")
            return out
        if close not in S.ITEM_CLOSES:
            out["refusal_codes"] = ["bad_close"]
            out["reason"] = f"收口方式必须是 {S.ITEM_CLOSES} 之一，收到 {close!r}"
            return out
        try:
            rows = self._tasks()
        except Exception as exc:  # noqa: BLE001 —— 读不成是"没查成"，不许折成"都拒了"
            out["checked"] = False
            out["state"] = "unknown"
            out["reason"] = f"tasks 台账读不成（{type(exc).__name__}: {exc}）⇒ 本次没查成"
            return out
        by_id = {str(r.get("task_id") or ""): r for r in rows}
        # 两族义务前缀是模块级常量（`obligations.REGISTER_PREFIX` / `RESUBMIT_PREFIX`），
        # 一次 ack 里不会变 ⇒ 问到第一次就存下来（原先逐条重新去 Import 一遍）。
        # 仍然是"用到才问"：没有一条项走到那一格时，这一次惰性 Import 照旧不发生。
        _obligation_prefixes: tuple[str, ...] | None = None
        for tid in ids:
            row = by_id.get(tid)
            if row is None:
                out["missing"].append(tid)
                out["refused"].append({"item_id": tid, "code": "no_such_item",
                                       "reason": f"台账里没有 {tid} 这一项"})
                continue
            if not self._is_board_item(row):
                out["refused"].append({"item_id": tid, "code": "not_board_item",
                                       "reason": (f"{tid} 不是板项（kind 为空）⇒ "
                                                  "它的状态不由状态机管")})
                continue
            owner_of = str(row.get("parent_task_id") or "")
            if owner_of != me:
                # 收件地址也可以只写在行上（K9）：`instance` == 我这个实例 ⇒ 这一项
                # 就是投给我的（父台账号可能为空：那一趟不在飞，地址仍然成立）。
                mine_instance = _instance_of_task(self, me)
                addressed = str(row.get("instance") or "")
                if not (addressed and mine_instance and addressed == mine_instance):
                    out["not_yours"].append(tid)
                    out["refused"].append({
                        "item_id": tid, "code": "not_yours",
                        "reason": (f"{tid} 的收件人是 {owner_of or '（顶层）'}"
                                   f"{('/实例 ' + addressed) if addressed else ''}，不是你 ⇒ "
                                   "只有收件人自己能确认（替别人 ack 会让'它还没看'消失）")})
                    continue
            before = str(row.get("item_state") or "queued")
            # 2026-10-29：收口方式与 expects 的配对必须在动盘之前校验。
            # 改前 `close="acked"` 给一条 `expects="work"` 的项：seen 那笔已经落盘，
            # 到 `_set_item(done)` 才被 `S.Task.validate()` 抛出来 ⇒ 工具回 unknown
            # （"落没落盘不知道"），而盘上其实已经半笔写好。这是本仓最忌讳的形态：
            # 半笔事务 + 读数说不知道。所以先判、再写；判不过就逐条拒，一个字节不动。
            expects_of = str(row.get("expects") or "")
            if (close == "acked" and expects_of != "ack") or \
                    (close == "worked" and expects_of != "work"):
                out["refused"].append({
                    "item_id": tid, "code": "bad_close",
                    "reason": (f"{tid} 的 expects={expects_of or '（空）'} 与 close={close!r} "
                               "不配对（acked 只收 ack 类、completed 只收 work 类）⇒ "
                               "这一条一个字都没动")})
                continue
            # ---- 2026-11-05（业主）：义务项不许被 ack 关掉 --------------------
            #
            # 现场（`temp/rmk90-audit/REPORT-R-mk-infinite-90-20261105.md` §A-4）：
            # 6 条 `b-register@`「必须收录」义务从 20:5x 起一直 queued，收工时 30 条
            # notice 未 ack —— 义务排在队里没人跑。业主的裁定：
            #
            #   「ack 只表示"看到了"」（`expects=ack` 的语义），而
            #   `b-register@` / `v-resubmit@` 是"要交付的活"（`expects=work`）；
            #   收口只有两条路：① 正文 + `reviewed=true`（框架凭证据收：`obligations` 的
            #   `ensure_registration` / `settle_resubmitted` 调 `close_item_by_evidence`）；
            #   ② 明确放弃 + 理由（`statement.abandon` → 那两条义务带 `expired` 收口）。
            #
            # 所以 `completed` / `expired` 这两个"看起来像办完了 / 作废了"的收口方式，
            # 对这两族一律在这里拒：收件人自报"我办完了"不是证据。`acked` 那一档已被
            # 上面的配对判据拒掉（acked 只配 ack 类），这里补的是"换个 close 自报完成"。
            if _obligation_prefixes is None:
                _obligation_prefixes = self._evidence_closed_item_prefixes()
            item_key = str(row.get("input_key") or "")
            if (item_key.startswith(_obligation_prefixes)
                    and close in ("completed", "expired")):
                out["refused"].append({
                    "item_id": tid, "code": "obligation_needs_evidence",
                    "reason": (f"{tid} 是「必须收录 / 必须重送」义务"
                               f"（`{item_key}`）⇒ 收件人不能自己把它"
                               f"收成 {close!r}：ack 只表示看到了，办完与否由框架按盘上的事实"
                               "核（正文 + `reviewed=true`），放弃要 `statement.abandon` 并"
                               "带理由。这一条一个字都没动")})
                continue
            # 已在终态的项不在这里另判一次（2026-10-26 Q24）：那只手是"同一终态重复
            # 设置"在状态机外面的第二份实现。改后照状态机的结论 —— `_set_item` 把它判成
            # 幂等命中（`changed=False`），那一支就在下面 `if not changed` 里。
            # 补记 `seen` 只对"真的还没到 seen、且迁移图里还走得过去"的项做。
            backfilled = (before != "seen"
                          and self.item_move(before, "seen") == self.ITEM_MOVE_FORWARD)
            if backfilled:
                state, why, _changed = self._set_item(tid, state="seen", by_task_id=me, step=0)
                if state != "seen":
                    code = "ack_unbacked" if state == "ack_unbacked" else "state_error"
                    out["refused"].append({"item_id": tid, "code": code,
                                           "reason": f"{tid} 补记 seen 没成（{why}）"})
                    continue
            step = by_id[tid].get("seen_step")
            step_txt = "未读" if step is None else str(int(step))
            event_note = f"item:done:by={me}:step={step_txt}:close={close}"
            if backfilled:
                event_note += "（这一项从没被投递过，ack 补记了 seen）"
            if str(note or "").strip():
                event_note += f"；{str(note).strip()}"
            state, why, changed = self._set_item(tid, state="done", close=close, by_task_id=me,
                                                 note=event_note)
            if state != "done":
                code = "ack_unbacked" if state == "ack_unbacked" else "state_error"
                out["refused"].append({"item_id": tid, "code": code,
                                       "reason": f"{tid} 没推到 done（{why}）"})
                continue
            if not changed:
                # 幂等命中：它本来就在 `done`（`item_move` 的 `same` 那一列）。不追加事件、
                # 不动计数 —— `_set_item` 一个字节都没写，读数仍报"已经收口"。
                out["already_done"].append(tid)
                out["acked"].append(tid)
                out["results"].append({"item_id": tid, "ok": True, "code": "already_done",
                                       "state_before": before, "state_after": "done",
                                       "step": None, "seen_backfilled": False})
                continue
            out["acked"].append(tid)
            out["results"].append({"item_id": tid, "ok": True, "code": "",
                                   "state_before": before, "state_after": "done",
                                   "step": step, "seen_backfilled": bool(backfilled)})
        n = len(out["acked"])
        out["ok"] = n > 0
        if not ids:
            out["state"] = "nothing"
        elif n and out["refused"]:
            out["state"] = "partial"
        elif n:
            out["state"] = "acked"
        else:
            out["state"] = "refused"
        out["count"] = n
        out["refusal_codes"] = list(dict.fromkeys(str(x.get("code") or "")
                                                 for x in out["refused"]))
        return out

    def open_items_of(self, task_id: str) -> list[dict]:
        """挂在 `task_id` 名下、还没消的工作项（板项轴）。

        ## 它只是一个读数，不是判据（2026-10-08 深夜 S1e 改名 + 降级）：旧名字 `in_flight_items`，注释写成"T2 消边
        谓词的第二把尺" —— 那句话是主控发明出来的，不是设计里的：`draft/84` §T2 的谓词只有 `open_children == 0`
        （实例轴）。而且它建在"板项行 `status` 永远是 `pending`"的同一批行上，拿它当判据会与 `E1` 犯同一个错（拿永不
        终态的读数当判据 ⇒ 判据永不成立）。所以名字改成"未消项"，语义降成纯读数，不参与任何判定；业主 T22 的退役
        算法（`draft/90` §1.9）也不引用它 —— "还有几条项没消"只作为 `roster_view` 回报里的一格（`items_open`）。
        判据：`tests/test_board_does_not_eat_the_fanout_quota.py` 里那一条负控。

        ## 两格地址（K9）：父台账号 + 收件实例

        「挂在我名下」有两种：`parent_task_id == 我`（按父投递），或板项行的
        `instance` == 我的实例标签（按实例投递 —— 那个实例领下的、或一开就点名投给它
        的）。只按父读会让"父为空但地址是我"的项永远没人收（lp-ball 两条
        `b-register@` 至今 `parent_task_id=None`）。两格合成一份，去重按 `task_id`。
        """
        tid = str(task_id or "")
        base = list(self.open_items_by_parent().get(tid, ()))
        if not tid:
            return base
        instance = _instance_of_task(self, tid)
        if not instance:
            return base
        have = {str(r.get("task_id") or "") for r in base}
        try:
            extra = [r for r in self._board_rows()
                     if str(r.get("item_state") or "") != "done"
                     and str(r.get("instance") or "") == instance]
        except Exception:  # noqa: BLE001 —— 读不成不改变已经读到的这一部分
            return base
        return base + [r for r in extra if str(r.get("task_id") or "") not in have]

    def open_items_for(self, role: str, instance: str) -> list[dict]:
        """「投给这个实例 / 这个角色」的未消板项（K9 的收件面；纯读）。

        与 :meth:`open_items_of` 的分工：那一格按父台账号取（"挂在我名下"），
        这一格按收件地址取（板项行 `instance` 那一格，见 `_item_row`）：

        - 行上 `instance == instance` ⇒ 投给这个实例（定向投递的落点）；
        - 行上 `instance == ""` 且 `role == role` ⇒ 角色地址（该角色的任一实例都能领）。

        为什么需要它：一条义务的收件人若只能是"父台账号"，那一趟一结束这条项就再也
        没有读者（lp-ball 的两条 `b-register@` 至今 `parent_task_id=None`）；若只能按
        角色广播，两个实例又会都当自己的活。地址写在行上，两种投递才分得开。
        """
        want_role = str(role or "")
        want = str(instance or "")
        out: list[dict] = []
        for row in self._board_rows():
            if str(row.get("item_state") or "") == "done":
                continue
            row_role = str(row.get("role") or "")
            row_inst = str(row.get("instance") or "")
            if want and row_inst == want:
                out.append(row)
                continue
            if not row_inst and row_role == want_role:
                out.append(row)
        return out

    def open_items_by_parent(self,
                             rows: Sequence[Mapping[str, Any]] | None = None
                             ) -> dict[str, list[dict]]:
        """「父 → 名下未消的板项」一次算完（`open_items_of` 与 `tree()` 共用这一份判据）。

        为什么要有这个方法：`tree()` 要给每一行带一格"我名下还有几条没消"，
        逐行调 `open_items_of` 会把同一张表扫 N 遍；而两处各写一遍过滤条件，
        迟早一处改了另一处没改。判据本身只有这里一处：`kind` 非空、`item_state != "done"`、
        按 `parent_task_id` 归到收件人。

        `rows` 给了就在那一份快照上算（`tree()` 用：它已经读了整表，再读一次是
        同一拍对同一张表的第二次整文件反序列化）；不给就照旧现读。
        注意：传进来的必须是含板项行的整表快照（`_tasks()`），不是"只留实例行"
        的那一份 —— 板项行的 `kind` 非空，被过滤掉的快照会让这份读数恒为空。
        """
        out: dict[str, list[dict]] = {}
        src = self._tasks() if rows is None else rows
        for row in src:
            if not self._is_board_item(row):
                continue
            if str(row.get("item_state") or "") == "done":
                continue
            out.setdefault(str(row.get("parent_task_id") or ""), []).append(row)
        return out

    def revoked_recent_of(self, task_id: str, *,
                          limit: int = REVOKED_RECENT_LIMIT) -> list[dict[str, Any]]:
        """挂在 `task_id` 名下、最近被撤销的那几条（收件人那一侧的读数，2026-11-06）。

        ## 它补的是什么（读口，不是第二份账）

        撤销的提醒没有第二个落点了（2026-11-09 D13：改前那条 `notice` 行已不再写，
        见 `REVOKE_POSTS_NOTICE_ROW`）。本方法只读 `void_items(revoke=True)` 写下的
        `revoke:expired:` 留痕，由 `agent_loop.mailbox_digest` 的增量段渲染。
        也就是说：这里读得到的东西，与被撤那一行自己的 `inputs` 是同一份，
        没有"通知行"这一层中间物。

        ## 它不进任何 open 计数（业主 2026-11-06 的第二笔，硬约束）

        `open_items_of` / `board_view` 的 `board_open_count` / patrol 的
        `child_open_count` / `board_digest` 的读数一个都不动：这一格是另开的，
        只由本方法与调用它的那一处渲染。判据：`tests/test_revoked_items_reach_the_recipient.py`
        的 b 条把四个读数在"有 / 没有这一格"两种情况下逐字比。

        ## 判据只有一处

        `item_state="done"`、`item_close="expired"`，且那一行 `inputs` 里有一条
        `revoke:expired:` 留痕（`void_items(revoke=True)` 写的）。旧口径的
        `void:expired:` 不算撤销（那是"作废"，业主这一笔裁定的正文只认 revoke）。

        返回（按 `at` 从新到旧，最多 `limit` 条，形状固定）
        `{"item_id","by","reason","at","summary"}`；读不成 ⇒ 抛（调用方按三态处理：
        "没读成"不是"我名下没有被撤项"）。
        """
        want = str(task_id or "")
        if not want:
            return []
        cap = max(1, int(limit))
        found: list[dict[str, Any]] = []
        for row in self._tasks():
            if not self._is_board_item(row):
                continue
            if str(row.get("parent_task_id") or "") != want:
                continue
            if str(row.get("item_state") or "") != "done":
                continue
            if str(row.get("item_close") or "") != "expired":
                continue
            mark = _revoke_mark_of(row)
            if not mark:
                continue
            parsed = _parse_revoke_mark(mark)
            found.append({
                "item_id": str(row.get("task_id") or ""),
                "by": str(parsed.get("by") or ""),
                "reason": str(parsed.get("reason") or ""),
                "at": str(parsed.get("at") or ""),
                "summary": _board_item_summary(row),
            })
        found.sort(key=lambda r: (r["at"], r["item_id"]), reverse=True)
        return found[:cap]

    # ---------------------------------------------------------------- 三态与幂等（S1h）
    def active_children(self, task_id: str) -> dict[str, Any]:
        """`task_id` 名下代理行的两态快照（三态返回）。业主 T22 的"活跃 / 在等待"。

        `{"checked": bool, "rows": [{"task_id","role","state","active","waiting_only",
        "waiting_for","note"}], "reason": ""}`

        - `state == "活跃"`：那一行 `status ∈ {pending, running}`（此刻在跑一次调用）；
        - `state == "在等待"`：那一行已是终态但还挂在这个父名下（退役与否由名册层说，
          见 `draft/90` §1.9 —— conductor 这一层不知道 `keep_alive` 与名字）；
        - `active`：按继承口径算出来的"算不算活跃"（业主 2026-10-26：有活跃的下级，
          自己已经收口也还是活跃的）；`waiting_only`：它是不是靠等下级才活跃
          （病态形状的布尔），`note` 是那句话人话。`state` 与 `active` 是两件事：
          前者是"它自己此刻在不在跑"，后者是"这一支的活算不算没做完"。

        只数代理行（`kind == ""`）：工作项（板项）走 `open_items_of`。
        读不成 ⇒ `checked=False` + `reason`，不许折成 `rows=[]`
        （那会让调用方把"没查成"当成"名下没有子代理"从而误退役，`draft/90` E9）。
        """
        try:
            rows = self._tasks()
        except Exception as exc:  # noqa: BLE001 —— 读不成是"没查成"
            return {"checked": False, "rows": [], "reason": f"{type(exc).__name__}: {exc}"}
        # 活跃是向上继承的（`activity_snapshot` 是那条口径的唯一实现）：`state` 仍是原来的
        # 两档（它自己此刻在不在跑），另两格 `active` / `waiting_only` 回答"按继承口径算，
        # 它算不算活跃、是不是靠等下级才活跃"。两格分开而不是把 `state` 改成三档：
        # `state` 已经有消费者（退役第②支的报文），改它的取值域等于悄悄改那一段的语义。
        snap = self.activity_snapshot()
        by_task = dict(snap.get("by_task") or {}) if snap.get("checked") else {}
        out: list[dict[str, Any]] = []
        for r in rows:
            if r.get("parent_task_id") != task_id or self._is_board_item(r):
                continue
            tid = str(r.get("task_id") or "")
            state = ("活跃" if str(r.get("status") or "") in UNFINISHED_STATUSES
                     else "在等待")
            cell = by_task.get(tid) or {}
            got = self.active_reading(tid, snapshot=snap) if by_task else {}
            out.append({"task_id": tid,
                        "role": str(r.get("role") or ""), "state": state,
                        "active": bool(cell.get("active")),
                        "waiting_only": bool(cell.get("waiting_only")),
                        "waiting_for": list(cell.get("waiting_for") or []),
                        "note": str(got.get("note") or "")})
        out.sort(key=lambda x: x["task_id"])
        return {"checked": True, "rows": out, "reason": ""}

    # -------------------------------------------------- 不变量：活跃子代理 ⇒ 有一条等它的计时器
    def arm_child_waiter(self, child_task_id: str, *, parent_task_id: str = "",
                         role: str = "", task_text: str = "",
                         where: str = "conductor.summon") -> dict[str, Any]:
        """派活成功那一刻给父代理起一条 `wait_for=<子>` 的计时器（业主 2026-10-27 第五条）。

        业主原话（唯一权威）：

            「如果一个子代理还有活跃子代理，必存在一个等待该子代理的计时器，
              所以"静默"定义良好」

        这条不变量必须在写侧保证，不能只在读侧判：所以 `_summon_preflight` 在建好子行、
        登记完名册之后立刻起表。读侧判据是 :meth:`child_wait_invariant`。

        目的按业主第二条裁定自动填：这里刻意不给 `reason`，让 `clock` 的"等谁"
        读口把名册里那一行 task 原文填进去（`purpose_source="target_task"`）。
        读口拿不到原文时才用 `task_text`（派活载荷里的那一句）兜底 —— 兜底这一支只在
        "名册还没写成"时发生，来源仍是 `target_task`（它就是那件活的 task 原文，
        只是换了一条路取到），读数里由 `note` / 事件流分得开这两条路。

        失败姿态：起表炸了不许带走这次派活（子行已经在盘上、活已经派出去了），
        但必须把理由交回调用方记进日志 —— "不变量没成立"不许静默。
        """
        tid = str(child_task_id or "")
        pid = str(parent_task_id or "")
        if not tid or not pid:
            return {"armed": False, "timer_id": "",
                    "reason": (f"派活时缺编号（子={tid or '空'}，父={pid or '空'}）"
                               "⇒ 这条不变量没有被建立")}
        from . import clock as _CLK

        root = str(getattr(self.store, "root", "") or "")
        if not root:
            return {"armed": False, "timer_id": "",
                    "reason": "没有工作区根 ⇒ 计时器登记不了（不变量没成立）"}
        # 让"等谁"的读口能读到台账/名册（它按工作区取绑定；没绑上就查不成）。
        try:
            from .tools.clock_tools import bind_workspace

            bind_workspace(root, self.store, self)
        except Exception:  # noqa: BLE001 - 绑不上只影响目的自动填，不影响起表
            pass
        try:
            timer = _CLK.start_timer(root, wait_for=f"task:{tid}", to=pid,
                                     task_id=pid, role=str(role or ""))
        except Exception as exc:  # noqa: BLE001 - 见 docstring 的失败姿态
            return {"armed": False, "timer_id": "",
                    "reason": (f"给 {tid} 起等待计时器没成：{type(exc).__name__}: {exc}"
                               "（派活照常：子行已在台账上）")}
        if timer.purpose_missing and str(task_text or "").strip():
            # 兜底：名册那一行的原文还没落盘（名册没写成 / 读口查不成）时，用派活载荷里的
            # 那一句补上同一个编号（`set_purpose` 补的是同一条，不是新建一条）。
            # 来源仍记 `target_task`：这一句就是"被等对象那件活的 task 原文"，只是换了一条
            # 路取到它；记成 `given` 会让"目的自动填到底成没成"在读数上漂掉（p210）。
            try:
                entry, _state = _CLK.set_purpose(root, timer.timer_id,
                                                 str(task_text).strip()[:200],
                                                 source="target_task")
                if isinstance(entry, _CLK.Timer):
                    timer = entry
            except Exception:  # noqa: BLE001 - 补不上就留着 purpose_missing（追问照旧）
                pass
        return {"armed": True, "timer_id": timer.timer_id,
                "wait_for": timer.wait_for, "purpose": timer.purpose,
                "purpose_source": timer.purpose_source,
                "purpose_missing": timer.purpose_missing, "where": str(where)}

    def child_wait_invariant(self, parent_task_id: str = "") -> dict[str, Any]:
        """判据：父的每一个"非静默直接子"都有一条 `wait_for` 等它的计时器。

        口径由业主 2026-10-27 那一句定死（"活跃子代理 ⇒ 必存在一个等待该子代理的计时器"）。
        两处都是现读的盘上事实：

        - 活跃子代理：`agent_states` 里 `state ∈ {flying, standby}` 的直接子（业主
          2026-10-26：「更新"活跃子代理"的定义为非静默子代理」，待机也算活跃）；
        - 等它的计时器：这个父名下 `state="pending"`、`wait_for` 解析成 `task:<子>` 的
          那几条（程序的计时器不算：它等的是程序，不是子代理）。

        返回 `{"checked", "parent", "active_children", "waited", "unwaited", "problems",
        "reason"}`。`unwaited` 逐字点名"哪个子代理没人等" —— 这条判据的价值就在这一格：
        一个笼统的"不变量不成立"没法让人去修。

        三态：台账/时钟读不成 => `checked=False`（不是"不变量成立"）。
        """
        pid = str(parent_task_id or "")
        out: dict[str, Any] = {"checked": False, "parent": pid, "active_children": [],
                               "waited": {}, "unwaited": [], "problems": [],
                               "reason": ""}
        try:
            rows = [r for r in self._tasks() if self._is_instance_row(r)]
        except Exception as exc:  # noqa: BLE001 —— 读不成是"没查成"
            out["reason"] = f"tasks 台账读不成（{type(exc).__name__}: {exc}）"
            return out
        if not pid:
            out["reason"] = "没给父的编号 ⇒ 判不了（不是「不变量成立」）"
            return out
        snap = self.activity_snapshot()
        if not snap.get("checked"):
            out["reason"] = (f"活跃读数没读成（{snap.get('reason') or '没查成'}）⇒ "
                             "不变量判不了")
            return out
        by_task = dict(snap.get("by_task") or {})
        active: list[str] = []
        for row in rows:
            if str(row.get("parent_task_id") or "") != pid:
                continue
            tid = str(row.get("task_id") or "")
            cell = dict(by_task.get(tid) or {})
            if str(cell.get("state") or "") in ACTIVE_AGENT_STATES:
                active.append(tid)
        root = str(getattr(self.store, "root", "") or "")
        try:
            bucket = CLK.book(root) if root else None
            timers = list(bucket.all()) if bucket is not None else []
        except Exception as exc:  # noqa: BLE001
            out["reason"] = f"时钟簿记读不成（{type(exc).__name__}: {exc}）"
            return out
        waited: dict[str, list[str]] = {}
        for timer in timers:
            if str(timer.state or "") != "pending" or not str(timer.wait_for or ""):
                continue
            if str(timer.task_id or "") != pid:
                continue
            try:
                kind, ref = CLK.parse_wait_for(timer.wait_for_resolved or timer.wait_for)
            except CLK.ClockError:
                continue
            if kind != "task":
                continue
            waited.setdefault(ref, []).append(timer.timer_id)
        out.update(checked=True, active_children=sorted(active),
                   waited={k: sorted(v) for k, v in sorted(waited.items())})
        unwaited = [t for t in sorted(active) if t not in waited]
        out["unwaited"] = unwaited
        out["problems"] = [f"活跃子代理 {t} 名下没有任何一条等它的计时器"
                           "（业主 2026-10-27：活跃子代理 ⇒ 必存在一个等待该子代理的计时器）"
                           for t in unwaited]
        return out

    def handoffs_reading(self, parent_task_id: str = "") -> dict[str, Any]:
        """父代理侧的交差读数：谁向我交了差、我把谁记成了静默（业主 2026-10-27 第四条）。

        业主原话：「如果已无事可做且无计时器，这意味着它交差了，需要向父代理报告，
        父代理把它记为静默子代理」。

        数据在 `clock.read_handoffs` 那一份账上（子代理交差时落的行，`parent_task_id`
        就是这里要的归属键）。这里把它折成父代理读得懂的三格：`count`（交了几个）、
        `silent`（因此被记为静默的那些编号）、`rows`（原样）。三态：读不成 =>
        `checked=False`（不是"没人交差"）。
        """
        got = CLK.read_handoffs(str(getattr(self.store, "root", "") or ""),
                                parent_task_id=str(parent_task_id or ""))
        rows = [dict(r) for r in (got.get("rows") or ())]
        return {"checked": bool(got.get("checked")), "parent": str(parent_task_id or ""),
                "count": len(rows), "rows": rows,
                "silent": [str(r.get("task_id") or "") for r in rows],
                "reason": str(got.get("reason") or "")}

    # -------------------------------------------------- 活跃判定（向上继承）与树遍历
    def activity_snapshot(self, *,
                          retired: Mapping[str, bool] | None = None) -> dict[str, Any]:
        """全树每一个代理行的活跃读数（一次台账快照算完，含"在等"的向上继承）。

        ## 口径（业主 2026-10-26 原话，逐字见模块头那一节）
            active(node) = 自身有未收口的任务 or 任一直接子 active
        「自身有未收口的任务」= 它自己那一行 `status ∈ UNFINISHED_STATUSES`
        （`pending` / `running`）。`schema.TASK_STATUSES` 的其余几格都是终态，其中
        `block` 是"停了、但这件活没做完"—— 停了就不算还在做（理由逐字在
        `UNFINISHED_STATUSES` 的注释里）。

        ## "等"也算活跃（这一条最容易写错）
        业主逐字：「若一子代理自身不活跃，但有活跃的子代理甚至孙代理，它还是叫活跃的，
        但这是病态形状（应该是这个孙辈或重孙辈的父代理在等它，爷爷辈在等父，
        有"等"这个动作还是算活跃的）」。所以一个已经收口、名下却还有活跃子代理的节点
        仍然是活跃的；同时它是"靠等下级才活跃"（`waiting_only`），那是病态形状而不是错 ——
        真在干活的是那些下级，标出来是为了让父看见"我这一支的活积在下面"。

        ## 返回
        `{"checked", "by_task", "waiting_only", "states", "clock", "reason"}`，
        `by_task` 每一格：
        - `self_busy`：它自己有没有未收口的任务；
        - `active`：按上面的继承口径算出来的那一位；
        - `waiting_only`：`active and not self_busy`（病态形状的布尔）；
        - `waiting_for`：直接子里活跃的那几个（`waiting_only` 时非空）；
        - `busy_roots`：把它撑成活跃的那些"真在跑"的节点的编号（自己忙 ⇒ 就是它自己）；
        - `status` / `role`：台账原值（读数要能对着台账核）；
        - `state` / `state_label` / `state_reason` / `parked` / `waiters`：三态读数
          （判定只有 `agent_state` 一处；`state` 的取值域见 `AGENT_STATES`）；
        - `stalled` / `stalled_sec` / `stalled_reason`：疑似停滞（`agent_state` 的同一格）。
          `state` 仍是 `flying` —— 停滞不改三态、也不进销号门；
        `states` 是四档各几个（外加 `active` = 在飞 + 待机 与 `total`），`stalled` 是
        疑似停滞的那些编号（点名，不只给个数）；
        `clock` 是这一次读时钟簿记的三态（`checked` / `count` / `reason`）——
        时钟读不成时每一格 `state` 都是 `unknown`，而那一句理由就在这里。

        `active` 与 `state` 是两条轴，刻意不折成一格：前者是销号门读的"这一支的活
        算不算没做完"（业主 2026-10-26 的继承口径），后者是"它此刻是哪一态"。
        折起来会让'销号要不要拒'跟着一个新读数走 —— 而销号是不可逆的那一类动作。

        `retired` 是名册那一层的事实（`{代理编号: 是否已销号}`）：本类只认台账，
        名字与退役都在秘书那一侧，所以默认 `None`（= 这一层不知道）。知道的那一层
        （`Secretary.roster_view`）把它传进来，于是"已销号 ⇒ 静默"仍然只由
        `agent_state` 那一处判，不在调用方再写一遍。

        读不成 ⇒ `checked=False` + `reason`：把它折成"都不活跃"会让一整棵子树被误销，
        而销号是不可逆的那一类动作（这正是"没查成"与"查过了没问题"被折平的代价）。
        """
        try:
            rows = [r for r in self._tasks() if self._is_instance_row(r)]
        except Exception as exc:  # noqa: BLE001 —— 读不成是"没查成"
            return {"checked": False, "by_task": {}, "waiting_only": [],
                    "stalled": [],
                    "states": None, "clock": {"checked": False, "count": 0,
                                              "reason": f"{type(exc).__name__}: {exc}"},
                    "reason": f"{type(exc).__name__}: {exc}"}
        # 时钟簿记只读一次：三态里的"待机"问的就是它（`clock_waiters` 是那一处的唯一实现）。
        clock = clock_waiters(self.store.root)
        three = agent_states(rows, clock=clock, retired=retired)
        role_of: dict[str, str] = {}
        status_of: dict[str, str] = {}
        kids: dict[str, list[str]] = {}
        # 身份三格（角色 / 状态）与父子边在同一趟里建：两条判据都只看这一行自己，
        # 而 `kids[父]` 的追加次序仍按 `rows` 的原序（逐个子代理的"等谁"读的就是它）。
        for r in rows:
            tid = str(r.get("task_id") or "")
            if not tid:
                continue
            role_of[tid] = str(r.get("role") or "")
            status_of[tid] = str(r.get("status") or "")
            pid = str(r.get("parent_task_id") or "")
            if pid:
                kids.setdefault(pid, []).append(tid)
        self_busy = {tid: (status_of[tid] in UNFINISHED_STATUSES
                           and not bool((three.get(tid) or {}).get("handed_off")))
                     for tid in status_of}
        active: dict[str, bool] = {}
        busy_roots: dict[str, list[str]] = {}
        # 迭代后序（显式栈 + 在栈集合）：深链 / 坏链（环）都不许把这里变成爆栈或死循环，
        # 而"谁把谁撑成活跃"必须自底向上算完才能定 —— 递归的写法在这里只是一行更短。
        for start in sorted(status_of):
            if start in active:
                continue
            stack: list[tuple[str, bool]] = [(start, False)]
            onstack: set[str] = {start}
            while stack:
                tid, done = stack.pop()
                if done:
                    onstack.discard(tid)
                    if self_busy.get(tid):
                        active[tid] = True
                        busy_roots[tid] = [tid]
                    else:
                        live = [k for k in kids.get(tid, ()) if active.get(k)]
                        active[tid] = bool(live)
                        busy_roots[tid] = sorted({x for k in live
                                                  for x in busy_roots.get(k, ())})
                    continue
                if tid in active:
                    onstack.discard(tid)
                    continue
                stack.append((tid, True))
                for k in kids.get(tid, ()):
                    if k in active or k in onstack:
                        continue
                    stack.append((k, False))
                    onstack.add(k)
        by_task: dict[str, dict[str, Any]] = {}
        waiting_only: list[str] = []
        for tid in sorted(status_of):
            waiting_for = sorted(k for k in kids.get(tid, ()) if active.get(k))
            wo = bool(active.get(tid)) and not self_busy.get(tid)
            cell = dict(three.get(tid) or {})
            by_task[tid] = {"task_id": tid, "role": role_of.get(tid, ""),
                            "status": status_of.get(tid, ""),
                            "self_busy": bool(self_busy.get(tid)),
                            "handed_off": bool(cell.get("handed_off")),
                            "active": bool(active.get(tid)),
                            "waiting_only": wo,
                            "waiting_for": waiting_for,
                            "busy_roots": list(busy_roots.get(tid) or []),
                            # 三态（`agent_state` 是唯一实现）：`state` 的取值域是
                            # `AGENT_STATES`，与上面那一格 `active` 是两条轴。
                            "state": str(cell.get("state") or AGENT_STATE_UNKNOWN),
                            "state_label": str(cell.get("state_label") or ""),
                            "state_reason": str(cell.get("reason") or ""),
                            "parked": bool(cell.get("parked")),
                            "waiters": list(cell.get("waiters") or []),
                            # 停滞读数（`agent_state` 的同一格）：`state` 仍是 flying，
                            # 只是"它这一拍没动静"。它不是第四态、也不进销号门。
                            "stalled": bool(cell.get("stalled")),
                            "stalled_sec": cell.get("stalled_sec"),
                            "stalled_reason": str(cell.get("stalled_reason") or "")}
            if wo:
                waiting_only.append(tid)
        return {"checked": True, "by_task": by_task, "waiting_only": waiting_only,
                "states": state_counts(str(v.get("state") or "") for v in by_task.values()),
                # 疑似停滞的那些编号（"在飞"里读不出动静的那几个）—— 名字读数之外的
                # 一份点名，父代理的拒信用它说"其中 M 个已停滞"。
                "stalled": sorted(tid for tid, v in by_task.items() if v.get("stalled")),
                "clock": {"checked": bool(clock.get("checked")),
                          "count": int(clock.get("count") or 0),
                          "reason": str(clock.get("reason") or "")},
                # 交差读数（业主 2026-10-27 第四条）：这一支里有几个子代理向我交了差
                # （= 因此被记为静默的那几个）。它是"父代理把它记为静默"在父自己读数里的那一格。
                "handoffs": self._handoffs_summary(),
                "reason": ""}

    def _handoffs_summary(self) -> dict[str, Any]:
        """交差账的汇总（`activity_snapshot` 与父的读共用这一份）。

        正文只有一处：`handoffs_reading` 是这份交差读数的唯一读口（'父侧那一格'与
        '整支的汇总'读的是同一本账），这里只是从它的六格里摘出汇总要的四格 ——
        `parent` / `rows` 不进汇总。改前这里自己又把 `CLK.read_handoffs` 读一遍、
        把四个键各算一遍，那是同一判据的第二份实现（一处改了另一处不会报）。
        """
        got = self.handoffs_reading()
        return {"checked": got["checked"], "count": got["count"],
                "silent": got["silent"], "reason": got["reason"]}

    def active_reading(self, task_id: str, *, names: Mapping[str, str] | None = None,
                       snapshot: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """一个节点的活跃读数（三态）＋"靠等"的那一句人话。

        `names` 是"编号 → 名册名"的对照（秘书那一侧给得出；不给就用角色 + 编号）。
        `snapshot` 可复用一次 :meth:`activity_snapshot` 的结果 —— 级联销号要对整个子树
        逐个判，重算 N 遍等于把同一张表读 N 遍。

        返回 `{"checked","task_id","active","self_busy","waiting_only","waiting_for",
        "busy_roots","status","role","state","state_label","state_reason","parked",
        "stalled","stalled_sec","stalled_reason","waiters","note","reason"}`。
        `note` 是给人读的那一句：
        靠等 ⇒ 「它自己不忙，是在等 D2（active）」；自己在跑 ⇒ 「它自己在跑（status=running）」；
        两样都没有 ⇒ 「它自己不忙，名下也没有活跃的下级」。
        三态那几格（`state` ∈ `AGENT_STATES`）直接来自 `activity_snapshot` 的同名格 ——
        本方法不另判一遍（同一判据两处实现，迟早会一处改了另一处没改）。
        """
        tid = str(task_id or "")
        snap = dict(snapshot) if snapshot is not None else self.activity_snapshot()
        blank = {"checked": False, "task_id": tid, "active": False, "self_busy": False,
                 "waiting_only": False, "waiting_for": [], "busy_roots": [],
                 "status": "", "role": "", "state": AGENT_STATE_UNKNOWN,
                 "state_label": "", "state_reason": "", "parked": False,
                 "stalled": False, "stalled_sec": None, "stalled_reason": "",
                 "note": ""}
        if not snap.get("checked"):
            blank["reason"] = str(snap.get("reason") or "台账读不成")
            return blank
        by_task = dict(snap.get("by_task") or {})
        cell = by_task.get(tid)
        if cell is None:
            blank["reason"] = f"台账里没有 {tid!r} 这一行代理 ⇒ 活跃判不了"
            return blank

        def label(other: str) -> str:
            got = str((names or {}).get(other) or "")
            if got:
                return got
            row = by_task.get(other) or {}
            return f"{row.get('role') or '?'}（{other}）"

        if cell.get("waiting_only"):
            note = ("它自己不忙，是在等 "
                    + "、".join(label(k) for k in cell.get("waiting_for") or [])
                    + "（active）")
        elif cell.get("self_busy"):
            note = f"它自己在跑（status={cell.get('status') or 'unknown'}）"
        else:
            note = "它自己不忙，名下也没有活跃的下级"
        return {"checked": True, "task_id": tid, "active": bool(cell.get("active")),
                "self_busy": bool(cell.get("self_busy")),
                "waiting_only": bool(cell.get("waiting_only")),
                "waiting_for": list(cell.get("waiting_for") or []),
                "busy_roots": list(cell.get("busy_roots") or []),
                "status": str(cell.get("status") or ""),
                "role": str(cell.get("role") or ""),
                "state": str(cell.get("state") or AGENT_STATE_UNKNOWN),
                "state_label": str(cell.get("state_label") or ""),
                "state_reason": str(cell.get("state_reason") or ""),
                "parked": bool(cell.get("parked")),
                "waiters": list(cell.get("waiters") or []),
                # 疑似停滞（`agent_state` 的同一格）：它是读数，不是第四态 ——
                # 销号门照样按"在飞"拒绝（见 `retire_blocking` 的那一条）。
                "stalled": bool(cell.get("stalled")),
                "stalled_sec": cell.get("stalled_sec"),
                "stalled_reason": str(cell.get("stalled_reason") or ""),
                "note": note, "reason": ""}

    def retire_state_of(self, task_id: str, *, names: Mapping[str, str] | None = None,
                        snapshot: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """目标此刻是不是静默 —— 销号前置那一格的唯一读数。

        业主 2026-10-26 同一批裁定逐字：「销号可以也只可针对静默子代理」。销号的
        两个落点（`conductor.retire_child` 与 `Secretary.retire`）都只读这一格，
        判定本身只有 `agent_state` 一处 —— 这里只把它的读数与 `retire_blocking`
        拼成销号门要的那一份。

        返回 `{"checked","task_id","state","state_label","state_reason","status","role",
        "silent","blocking","waiters","waiting_for","busy_roots","deferred",
        "stalled","stalled_sec","reason"}`：
        - `silent`：`state == silent` 且这一格真的读成了（`unknown` 一律 False，
          所以"读不到"在销号门上就是"不许销"，fail-closed）；
        - `blocking`：`retire_blocking` 的逐条清单（静默时是空表）；
        - `stalled` / `stalled_sec`：疑似停滞（`agent_state` 的同一格）。它是读数：
          停滞不等于静默，`silent` 一个字都不看它（折平会让它可销 —— 销号不可逆）；
        - `state_reason`：为什么判成这一格（`unknown` 时就是"读不到什么"的那一句，
          拒信里"读不到它是不是静默（…）"用到的就是它）；
        - `deferred`：待机、但真正在跑的是下级的下级（不是它的直接子）—— 这一档
          仍由子树活跃闸拒绝（那份拒信逐个点名整支的活跃节点），本格只是把
          "这一笔该由哪一句话去说"写成读数；
        - `reason`：读不成时的那一句（读成了就是空串）。
        """
        tid = str(task_id or "")
        got = self.active_reading(tid, names=names, snapshot=snapshot)
        blocking = retire_blocking(got, names=names)
        state = str(got.get("state") or AGENT_STATE_UNKNOWN)
        waiters = [dict(w) for w in (got.get("waiters") or ())]
        waiting_for = [str(x) for x in (got.get("waiting_for") or ())]
        busy = [str(x) for x in (got.get("busy_roots") or ())]
        checked = bool(got.get("checked"))
        deferred = bool(state == AGENT_STATE_STANDBY and not waiters and busy
                        and (set(busy) - set(waiting_for)))
        return {"checked": checked, "task_id": tid, "state": state,
                "state_label": str(got.get("state_label") or ""),
                "state_reason": str(got.get("state_reason") or got.get("reason") or ""),
                "status": str(got.get("status") or ""),
                "role": str(got.get("role") or ""),
                "silent": bool(checked and state == AGENT_STATE_SILENT),
                "blocking": blocking, "waiters": waiters,
                "waiting_for": waiting_for, "busy_roots": busy,
                "deferred": deferred,
                "stalled": bool(got.get("stalled")),
                "stalled_sec": got.get("stalled_sec"),
                "reason": "" if checked else str(got.get("reason") or "")}

    def programs_in_subtree(self, root_task_id: str, *, now_dt: Any = None) -> dict[str, Any]:
        """这一支（含根那一行）名下还在跑的程序 —— 销号门与收工门的唯一读数。

        业主 2026-10-26 那一批的第二句：「注销前检测的能力」。此前销号门读三样东西
        （板项 / 三态 / 名册里没销的子），一样都不是"还有没有进程在跑"，于是昨晚那类
        进程可以一路留到父销号、父收工之后，盘上再没有谁的名字与它相关。

        ## 口径
        `programs_reading` 是唯一实现（本方法只做两件事：算出这一支的编号集合、
        把读不成的三态翻出来）。归属取 `task_id ∈ 这一支`，含根那一行 —— 目标自己起的
        程序也算"它的程序"，那正是"子代理杀自己发出去的程序"这句话的对象。

        ## 三态
        子树读不成 / 程序计时器读不成 ⇒ `checked=False` + `reason`。调用方一律不销
        （fail-closed），而且拒信必须写"没查成"，不许写成"没有在跑的程序"。
        """
        root = str(root_task_id or "")
        order: dict[str, Any]
        try:
            order = self.subtree_postorder(root)
        except Exception as exc:  # noqa: BLE001 —— 读侧自己炸了也是"没读成"
            order = {"checked": False, "order": [],
                     "reason": f"{type(exc).__name__}: {exc}"}
        if not order.get("checked"):
            got = programs_reading(
                self.store.root, task_ids=(),
                blocked_reason=(f"子树读不成（{order.get('reason') or '没查成'}）⇒ "
                                "这一支有没有程序在跑判不了"))
            got.update({"root": root, "subtree_size": 0})
            return got
        nodes = [str(x) for x in (order.get("order") or ())]
        got = programs_reading(self.store.root, task_ids=nodes, now_dt=now_dt)
        got["root"] = root
        got["subtree_size"] = len(nodes)
        return got

    def subtree_postorder(self, root_task_id: str) -> dict[str, Any]:
        """子树的销号次序：从最深到最浅（先叶子后父）。

        返回 `{"checked","order","depth_of","parent_of","rows","reason"}`：`order` 含根
        自己，深度严格不升；同一深度按编号升序（确定性让"次序"这件事可以被逐条断言）。
        `depth_of` 是从根算起的相对深度，不信台账里的 `depth` 字段 —— 历史行有缺这一格
        或写错的，而销号次序要的只是"在这一支里谁比谁深"。

        为什么"后序"就等于"深度降序"：子节点一定比父更深，所以深度降序的每一种线性化
        都是合法的后序。这条等价关系是本方法与"先叶子后父"那句原话之间的桥。
        根不在台账里 / 台账读不成 ⇒ `checked=False` + `reason`（不猜一棵树出来）。
        """
        root = str(root_task_id or "")
        try:
            rows = [r for r in self._tasks() if self._is_instance_row(r)]
        except Exception as exc:  # noqa: BLE001
            return {"checked": False, "order": [], "depth_of": {}, "parent_of": {},
                    "rows": [], "reason": f"{type(exc).__name__}: {exc}"}
        parent_of: dict[str, str] = {}
        for r in rows:
            tid = str(r.get("task_id") or "")
            if tid:
                parent_of[tid] = str(r.get("parent_task_id") or "")
        if root not in parent_of:
            return {"checked": False, "order": [], "depth_of": {}, "parent_of": {},
                    "rows": [],
                    "reason": f"台账里没有 {root!r} 这一行代理 ⇒ 子树判不了"}
        kids: dict[str, list[str]] = {}
        for tid, pid in parent_of.items():
            if pid:
                kids.setdefault(pid, []).append(tid)
        depth_of: dict[str, int] = {root: 0}
        queue: list[str] = [root]
        while queue:                                  # 广度下行：环不会把这里变成死循环
            cur = queue.pop(0)
            for k in sorted(kids.get(cur, ())):
                if k in depth_of:
                    continue
                depth_of[k] = depth_of[cur] + 1
                queue.append(k)
        order = sorted(depth_of, key=lambda x: (-depth_of[x], x))
        inside = set(order)
        return {"checked": True, "order": order, "depth_of": dict(depth_of),
                "parent_of": {k: parent_of.get(k, "") for k in order},
                "rows": [dict(r) for r in rows if str(r.get("task_id") or "") in inside],
                "reason": ""}

    def active_in_subtree(self, root_task_id: str, *,
                          names: Mapping[str, str] | None = None) -> dict[str, Any]:
        """子树里还在活跃的节点（受控拒绝要点名的那一份读数）。

        返回 `{"checked","rows","active_count","subtree_size","busy_root_ids",
        "children_unretired","active_child_count","reason"}`：
        - `rows`：只放活跃的节点，次序照 :meth:`subtree_postorder`（最深的在前）；
          每行带 `task_id` / `role` / `status` / `self_busy` / `waiting_only` / `note`
          与 `busy`（把它撑成活跃的那些"真在跑"的节点，含它们在做什么）——
          "点名它卡在哪件任务上"要的就是 `busy` 这一格；
        - `active_count` / `subtree_size`：这一支里活跃几个、一共几行代理；
        - `busy_root_ids`：去重后的"真在跑"的编号。

        两个读数（`child_count` / `active_child_count`）在这里刻意留空值：它们问的是
        "名册里未销号的名册项"，与"台账里这一支的代理行"是两个量 —— 见
        `secretary.Secretary.child_counts` 的 docstring（销号要看的是前者）。
        """
        order = self.subtree_postorder(root_task_id)
        if not order.get("checked"):
            return {"checked": False, "rows": [], "active_count": 0, "subtree_size": 0,
                    "busy_root_ids": [], "children_unretired": None,
                    "active_child_count": None,
                    "reason": str(order.get("reason") or "子树判不了")}
        snap = self.activity_snapshot()
        if not snap.get("checked"):
            return {"checked": False, "rows": [], "active_count": 0,
                    "subtree_size": len(order.get("order") or []), "busy_root_ids": [],
                    "children_unretired": None, "active_child_count": None,
                    "reason": str(snap.get("reason") or "活跃读数没读成")}
        by_task = dict(snap.get("by_task") or {})
        row_of = {str(r.get("task_id") or ""): r for r in order.get("rows") or []}
        out: list[dict[str, Any]] = []
        busy_ids: set[str] = set()
        for tid in order.get("order") or []:
            cell = by_task.get(tid) or {}
            if not cell.get("active"):
                continue
            busy = []
            for bid in cell.get("busy_roots") or []:
                busy_ids.add(bid)
                brow = row_of.get(bid) or {}
                busy.append({"task_id": bid,
                             "role": str(brow.get("role") or cell.get("role") or ""),
                             "status": str(brow.get("status") or ""),
                             "action": str(brow.get("action") or "")})
            got = self.active_reading(tid, names=names, snapshot=snap)
            out.append({"task_id": tid, "role": str(cell.get("role") or ""),
                        "status": str(cell.get("status") or ""),
                        "self_busy": bool(cell.get("self_busy")),
                        "waiting_only": bool(cell.get("waiting_only")),
                        "state": str(cell.get("state") or AGENT_STATE_UNKNOWN),
                        "state_label": str(cell.get("state_label") or ""),
                        "note": str(got.get("note") or ""),
                        "busy": busy})
        return {"checked": True, "rows": out, "active_count": len(out),
                "subtree_size": len(order.get("order") or []),
                "busy_root_ids": sorted(busy_ids),
                "children_unretired": None, "active_child_count": None, "reason": ""}

    def inside_subtree(self, root_task_id: str, task_id: str) -> dict[str, Any]:
        """`task_id` 是不是在 `root_task_id` 这一支下面（含它自己）。三态。

        用途（S4，`draft/90` E7）：一把子树停机开关（`stopctl.stop_scope` = `"subtree"`）只对那一支生效 —— 每个循环
        在决定"这把开关管不管我"时问这一格。实现是纯粹的上行链（`parent_task_id` 逐级往上），不枚举子树（枚举子树是
        另一件事：`descendants_of`；这一格只回答"我在不在里面"）。到顶还没遇到 `root` ⇒ 不在里面。
        三态：台账读不成 / 我这一行不在台账里 ⇒ `checked=False` + `reason`；调用方据此不停（判不了 ≠ 适用）—— 这一
        条与 `draft/92` E9 同族：把"没读成"折成"不在里面"会让一次子树叫停静默失效，折成"在里面"会让一次局部叫停
        变成全停。
        """
        root_tid = str(root_task_id or "")
        me = str(task_id or "")
        if not root_tid or not me:
            return {"checked": False, "inside": False,
                    "reason": ("没给子树根或没给我的编号 ⇒ 『我在不在这一支里』判不了"
                               if not (root_tid and me) else "")}
        try:
            rows = {str(r.get("task_id")): r for r in self._tasks()}
        except Exception as exc:  # noqa: BLE001 —— 读不成 ≠ 不在里面
            return {"checked": False, "inside": False,
                    "reason": f"台账读不成（{type(exc).__name__}: {exc}）"}
        if me not in rows:
            return {"checked": False, "inside": False,
                    "reason": f"台账里没有我这一行（{me!r}）⇒ 判不了"}
        path: list[str] = []
        cur = me
        for _ in range(64):                    # 深度上限：坏链不许把这里变成死循环
            path.append(cur)
            if cur == root_tid:
                return {"checked": True, "inside": True, "path": path, "reason": ""}
            row = rows.get(cur) or {}
            nxt = str(row.get("parent_task_id") or "")
            if not nxt or nxt not in rows:
                break
            cur = nxt
        return {"checked": True, "inside": False, "path": path, "reason": ""}

    def children_facts(self, parent_task_id: str) -> dict[str, Any]:
        """父名下每一个子代理的"此刻在飞几件 / 名下几条未消的项 / 台账状态"（S-H）。

        `{"checked", "by_child": {<子台账号>: {"in_flight","items_open","status","role"}},
          "reason"}`

        为什么单独一个读侧、而不复用 `retire_ready`：那一张表跳过已经记过消边的
        子代理（它回答的是"现在能不能退役"），而名册要的是"每一个孩子此刻在飞几件" ——
        拿退役表当名册会让已销号的那些读成"0 件在飞"，那是两件事被折成一格。
        一次 `_tasks()` 快照算完（名册每步都可能被查一次）。
        读不成 ⇒ `checked=False`（不许返回一串 0：那会让父以为"孩子们都闲着"）。
        """
        try:
            rows = self._tasks()
        except Exception as exc:  # noqa: BLE001
            return {"checked": False, "by_child": {}, "reason": f"{type(exc).__name__}: {exc}"}
        by_child: dict[str, dict[str, Any]] = {}
        for r in rows:
            if r.get("parent_task_id") != parent_task_id:
                continue
            tid = str(r.get("task_id") or "")
            if not tid:
                continue
            if self._is_board_item(r):
                # 板项行（`kind` 非空）：它的 `parent_task_id` 是收件人的编号，
                # 与"谁派出去的"是两轴 —— 只把未消的项计到收件人名下。
                if str(r.get("item_state") or "") != "done":
                    cur = by_child.setdefault(tid, {"in_flight": 0, "items_open": 0,
                                                    "status": "", "role": ""})
                    cur["items_open"] = int(cur.get("items_open") or 0) + 1
                continue
            cur = by_child.setdefault(tid, {"in_flight": 0, "items_open": 0,
                                            "status": "", "role": ""})
            cur["status"] = str(r.get("status") or "")
            cur["role"] = str(r.get("role") or "")
            if cur["status"] in UNFINISHED_STATUSES:
                cur["in_flight"] = int(cur.get("in_flight") or 0) + 1
        return {"checked": True, "by_child": by_child, "reason": ""}

    def poke_generation(self) -> str:
        """台账的"世代"读数（S-G，裁定 15）：读数期间它变了 ⇒ 结论要重算。

        搬的是 DSH `settlementState`（`dsh-subagent/lib/index.js:1192-1198`）里我们缺的
        那一格 `retry`（它的 `poke` 世代比较）：拿一份旧快照下"孩子们都停了"的结论，
        而读的过程中恰好有一个孩子交差 —— 那个结论在写下它的那一刻就已经过期了。
        世代取三样拼起来（行数 / 在飞数 / 最晚的结束时刻），任何一样变了就是另一代。
        读不成 ⇒ 空串（那是"判不了"，`settlement_reading` 会如实说没重算成）。
        """
        try:
            rows = self._tasks()
        except Exception:  # noqa: BLE001 —— 读不成 ⇒ 没有世代可比（不许编一个）
            return ""
        ends = [str(r.get("ended_at") or "") for r in rows]
        running = sum(1 for r in rows
                      if str(r.get("status") or "") in UNFINISHED_STATUSES)
        return f"{len(rows)}:{running}:{max(ends) if ends else ''}"

    def settlement_reading(self, parent_task_id: str) -> dict[str, Any]:
        """父的结算读数（S-G，裁定 15）：此刻还有几条在飞 + 逐条是谁 + 世代 + 重算过没有。

        `{"checked", "in_flight", "rows", "generation", "retried", "reason"}`

        用途：① 收工那一刻写一条读数（读数，不拦 —— 裁定 1「收工由 M 判」与裁定 15
        的"超时 ⇒ 记读数继续收工"）；② 将来"等"那条路用它获知还有谁没回来。

        `retried` 那一格是这一批的重点：读一遍台账（`children_facts`）前后各取一次
        世代，两次不同 ⇒ 重算一遍并如实报 `retried=True`。不重算的后果很具体：父会把
        "孩子们都回来了"写进结论，而有一个孩子的 `done` 行是在读的中间落下的。
        """
        gen1 = self.poke_generation()
        got = self.children_facts(parent_task_id)
        if not got.get("checked"):
            return {"checked": False, "in_flight": 0, "rows": [], "generation": gen1,
                    "retried": False, "reason": str(got.get("reason") or "台账读不成")}
        gen2 = self.poke_generation()
        retried = bool(gen1 and gen2 and gen1 != gen2)
        if retried:
            again = self.children_facts(parent_task_id)
            if again.get("checked"):
                got = again
                gen2 = self.poke_generation()
        by = dict(got.get("by_child") or {})
        rows = [{"task_id": tid, "role": str(v.get("role") or ""),
                 "status": str(v.get("status") or ""),
                 "in_flight": int(v.get("in_flight") or 0),
                 "items_open": int(v.get("items_open") or 0)}
                for tid, v in sorted(by.items())]
        in_flight = sum(1 for r in rows if r["in_flight"] > 0)
        return {"checked": True, "in_flight": in_flight, "rows": rows,
                "generation": gen2, "retried": retried, "reason": ""}

    def interrupt_child(self, *, parent_task_id: str, child_task_id: str,
                        reason: str = "", by: str = "") -> dict[str, Any]:
        """父叫停某一个子代理的当前那一轮（S-H，裁定 14；照 DSH `interrupt_agent`）。

        返回 `{"ok","accepted","code","target_task_id","no_op","why","signal"}`。
        ## 四条语义照抄（DSH 的几条 no-op 逐条）：
        1. 只停当前那一轮：信号只被精确的那一个目标读到，读到即消费（`stopctl.interrupt_applies` / `consume_interrupt`）；
        2. 队列保留：本方法一个字节都不碰收件箱与板项 —— 被中断的孩子下一次被唤醒时照旧看到它排队时收到的那些消息
           （DSH `{keepInbox:true}` 的对应物）；
        3. 不递归：它已 claim 的活不重排、它自己起的子代理继续跑（DSH 逐字：`interrupt` 不递归）；
        4. 不在册 / 已结束 ⇒ 静默 no-op：`accepted=True` + `no_op=True` + 一句读数（工具描述逐字「interrupting an agent
           that already finished is an accepted no-op」）。
        ## 授权（DSH `:853-866` 的三条）：叫停者必须是精确活着的祖先；不许停自己；目标非后代 ⇒ `UNAUTHORIZED`。判据
        用的是已经是三态的 :meth:`inside_subtree`：`checked=False`（判不了）时拒绝 —— 把"没读成"折成"不是后代"会让
        一次正当的叫停静默失效，折成"是后代"会让越权通过（`draft/92` E9 同族）。
        ## 为什么它是新增而不是给 `cancel` 加参数：`cancel`（:meth:`Conductor.cancel`）"一个共享 token 覆盖全部在飞
        与待启动任务"的语义被 41 处调用依赖 ⇒ 给它加一个"只停某一个"的参数等于顺手改掉全局停机的语义。所以 `cancel`
        一个字都不动，逐子代理的中断走这里 + `stopctl` 那份一个目标一份的信号（为什么不能共用工作区那把开关：见
        `stopctl` 里那段注释 —— 一个文件装不下 N 个目标）。
        """
        by_tid = str(parent_task_id or "")
        child = str(child_task_id or "")
        base: dict[str, Any] = {"ok": False, "accepted": False, "code": "",
                                "target_task_id": child, "no_op": False, "why": [],
                                "signal": {}}
        if not by_tid or not child:
            base["code"] = "bad_request"
            base["why"] = ["没给叫停者或目标的台账号 ⇒ 不受理（判不了 ≠ 放行）"]
            return base
        if by_tid == child:
            base["code"] = "unauthorized"
            base["why"] = [f"不许停自己（{by_tid}）：要停的是当前那一轮，"
                           "而「当前那一轮」就是叫停这件事本身"]
            return base
        inside = self.inside_subtree(by_tid, child)
        if not inside.get("checked"):
            base["code"] = "unauthorized"
            base["why"] = [f"判不了 {child} 在不在 {by_tid} 这一支里 ⇒ 拒绝："
                           f"{inside.get('reason')}（判不了 ≠ 不是后代）"]
            return base
        if not inside.get("inside"):
            base["code"] = "unauthorized"
            base["why"] = [f"{child} 不在 {by_tid} 这一支里（祖先链：{inside.get('path')}）"
                           "⇒ 越权的叫停当面拒绝"]
            return base
        try:
            rows = {str(r.get("task_id")): r for r in self._tasks()}
        except Exception as exc:  # noqa: BLE001 —— 读不成不是"它已经结束了"
            base["code"] = "unknown"
            base["why"] = [f"台账读不成（{type(exc).__name__}: {exc}）⇒ 不受理"
                           "（没读成 ≠ 不在飞）"]
            return base
        row = rows.get(child)
        if row is None:
            base.update({"ok": True, "accepted": True, "code": "no_op", "no_op": True,
                         "why": [f"台账里没有 {child} 这一行 ⇒ 它不在册，"
                                 "静默 no-op（DSH 逐字：已经结束的中断是 accepted no-op）"]})
            return base
        status = str(row.get("status") or "")
        if status not in UNFINISHED_STATUSES:
            base.update({"ok": True, "accepted": True, "code": "no_op", "no_op": True,
                         "why": [f"{child} 此刻 status={status!r}（不是 pending/running）"
                                 "⇒ 已经结束了，静默 no-op"]})
            return base
        from . import stopctl as SC

        state = SC.request_interrupt(self.store.root, child,
                                     reason=str(reason or SC.INTERRUPT_REASON),
                                     by=str(by or ""), by_task_id=by_tid)
        base.update({"ok": True, "accepted": True, "code": "accepted", "signal": state,
                     "why": [f"信号已落盘：只停 {child} 当前那一轮；"
                             "排队消息留在收件箱里、它自己起的子代理继续跑"]})
        return base

    #: 停机通知的落痕前缀（父那一行的 `inputs` 里）：`stop-notified:<子>@<iso>|<通知项>`
    _STOP_NOTIFIED_PREFIX = "stop-notified:"
    #: 停止通知被确认的落痕前缀（同上；时间只能落在这里，见 `note_stop_ack`）
    _STOP_ACKED_PREFIX = "stop-acked:"
    #: "这一支卡住了"的落痕前缀（父那一行的 `inputs` 里）：`blocked:<子>@<iso>|<一句为什么>`
    _BLOCKED_PREFIX = "blocked:"

    def note_blocked(self, parent_task_id: str, child_task_id: str, *,
                     what: str = "", why: str = "") -> tuple[str, str]:
        """子代理声明"我这趟卡住了（干不了、也派不出去）" ⇒ 在父那一行留一行落痕。

        业主 2026-10-09 的第四句：「上述层层上报困难也会带来一种停机状态，即所有活跃子代理的
        状态都是 blocked」⇒ 先要有"某个子是 blocked"这个可读的事实：
        `blocked:<子>@<时间>|<为什么>`。落痕写在父那一行的 `inputs`（与 `stop-notified:` /
        `edge-released:` 同一族，不动 `schema.py`）；幂等：同一条边已经有落痕 ⇒ 不写第二份。

        `what`（卡在哪件事）不进落痕的键 —— 完整的"卡在哪、试过什么"由子代理自己那条
        上行报文承载（业主第三句：上报父；M 上报用户）。它在这里只用来记一句 why。
        """
        mark = f"{self._BLOCKED_PREFIX}{child_task_id}@{S.now_iso()}|{str(why or '')[:120]}"
        try:
            self._refuse_write_in_snapshot("记阻塞（note_blocked）")
            with self.store.tx("tasks", actor="conductor", note="edge:blocked") as tx:
                parent = tx.find("tasks", task_id=parent_task_id)
                if parent is None:
                    return "", f"没有这一行（parent_task_id={parent_task_id!r}）"
                marks = [str(x) for x in (parent.get("inputs") or [])]
                if any(m.startswith(f"{self._BLOCKED_PREFIX}{child_task_id}@") for m in marks):
                    return "", "已经记过（幂等：不写第二份）"
                parent["inputs"] = sorted(set(marks) | {mark})
                task = S.Task(**{k: v for k, v in parent.items()
                                 if k in S.Task.__dataclass_fields__})
                task.validate()
                tx.upsert("tasks", task.to_dict(), note="edge:blocked")
        except Exception as exc:  # noqa: BLE001 —— 落痕失败不该带走这一趟
            return "", f"{type(exc).__name__}: {exc}"
        del what
        return mark, ""

    def subtree_blocked(self, parent_task_id: str) -> dict[str, Any]:
        """这一支是不是整支卡住了（业主 2026-10-09 第四句）：三态读数。

        「所有活跃子代理的状态都是 blocked」= 我名下还在飞的直接子代理每一个都声明过"卡住"（父那一行上有
        `blocked:<它>` 的落痕）。它是一个停机状态：委派这条路也堵死了 ⇒ 这一趟只能停，并把情况上报父（M 上报用户）。
        返回 `{"checked","in_flight","blocked","all_blocked","details","reason"}`：没有在飞的子 ⇒ `all_blocked=false` +
        `reason` 说清（"没有活跃子"既不是"整支卡住"，也不是"都做完了"——后者是 `final` 说的话）；有一个还在跑、或没
        声明卡住 ⇒ `all_blocked=false`（还留着一条路）；台账读不成 ⇒ `checked=false`（"没读成"不许折成"都卡住了"，
        也不许折成"没卡"）。
        """
        mine = str(parent_task_id or "")
        if not mine:
            return {"checked": False, "in_flight": [], "blocked": [], "all_blocked": False,
                    "details": [], "reason": "不知道我是谁（没有台账号）⇒ 子树卡不卡判不了"}
        try:
            kids = [str(x) for x in self._in_flight_children_of(mine)]
            parent = self._task(mine) or {}
        except Exception as exc:  # noqa: BLE001 —— 读不成 ≠ 都卡住了
            return {"checked": False, "in_flight": [], "blocked": [], "all_blocked": False,
                    "details": [], "reason": f"台账读不成（{type(exc).__name__}: {exc}）"}
        marks = [str(x) for x in (parent.get("inputs") or [])]
        blocked: list[str] = []
        details: list[dict[str, Any]] = []
        for raw in marks:
            if not raw.startswith(self._BLOCKED_PREFIX):
                continue
            body = raw[len(self._BLOCKED_PREFIX):]
            child, _, rest = body.partition("@")
            _at, _, why = rest.partition("|")
            if child in kids:
                blocked.append(child)
                details.append({"child_task_id": child, "why": why})
        all_blocked = bool(kids) and set(blocked) == set(kids)
        reason = ""
        if not kids:
            reason = ("我名下此刻没有在飞的子代理 ⇒ 不是『整支卡住』"
                      "（也不是『都做完了』：那是 `final` 说的话）")
        return {"checked": True, "in_flight": kids, "blocked": sorted(set(blocked)),
                "all_blocked": all_blocked, "details": details, "reason": reason}

    def notify_children_of_stop(self, parent_task_id: str, *, reason: str = "",
                                by: str = "") -> dict[str, Any]:
        """停止沿边下发：给我还在飞的直接子代理各开一条 `notice`/`ack` 板项。

        `draft/84` §2.2 的第 1、2.a 步：父把通知沿自己的出边传下去（不是"大家读同一个文件"），每条边留一行读数和一条
        "要 ack"的板项 —— ack 才算传达到（T16）。收件人 = `_in_flight_children_of(我)`（此刻还没返回的那几个）；已经
        收工的子代理不必通知。落痕写进父那一行的 `inputs`（与 `note_edge_release` 同一族，不动 `schema.py`）：
        `stop-notified:<子代号>@<时间>|<通知项号>` —— 幂等：同一条边已经有通知 ⇒ 不写第二份。返回
        `{"checked","notified":[{child_task_id,item_id,at}],"skipped":[{child,why}],"reason"}`。没有在飞的子 ⇒
        `notified=[]` + `note` 说清（不许假装通知过）。
        """
        mine = str(parent_task_id or "")
        if not mine:
            return {"checked": False, "notified": [], "skipped": [],
                    "reason": "不知道我是谁（没有台账号）⇒ 沿边下发判不了"}
        try:
            kids = [str(x) for x in self._in_flight_children_of(mine)]
        except Exception as exc:  # noqa: BLE001 —— 读不成 ≠ 没有在飞的子
            return {"checked": False, "notified": [], "skipped": [],
                    "reason": f"台账读不成（{type(exc).__name__}: {exc}）"}
        # 父那一行与每个子那一行都从同一份索引里取（2026-10-27）：改前是 1 + N 次
        # `_task()` = 1 + N 次整表读。循环里只新增板项行、只改父行的 `inputs`，
        # 而父行已在循环之前读进 `parent`，所以这份索引不陈旧。
        by_id = self._tasks_by_id()
        parent = by_id.get(mine) or {}
        marks = [str(x) for x in (parent.get("inputs") or [])]
        already = {m[len(self._STOP_NOTIFIED_PREFIX):].split("@", 1)[0]
                   for m in marks if m.startswith(self._STOP_NOTIFIED_PREFIX)}
        notified: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        todo: list[dict[str, Any]] = []
        for tid in kids:
            if tid in already:
                skipped.append({"child_task_id": tid, "why": "这条边已经通知过（幂等）"})
                continue
            row = by_id.get(str(tid)) or {}
            todo.append({"tid": tid, "at": S.now_iso(),
                         "role": str(row.get("role") or ""),
                         "depth": int(row.get("depth") or 1) + 1})
        # 一笔事务开完 N 条通知项 + 一笔事务记完 N 条落痕（2026-10-27）：改前是每条边
        # 三笔事务（开项 + 写说明 + 记落痕）。落盘结果与逐条路径逐字节一致，理由与
        # 判据见 `open_items_many` 的 docstring 与 `tests/test_board_batch_write.py`。
        # 代价换成一条新纪律：整批同成同败（一条边开不成 ⇒ 这一批一条都不开）。
        if todo:
            detail = (f"停止通知（{reason or 'stop'}）沿边下发；"
                      f"收到即 ack（ack 才算传达到，`draft/84` §2.2）")
            try:
                item_ids = self.open_items_many(
                    [{"kind": "notice", "role": t["role"], "expects": "ack",
                      "action": "notice",
                      "summary": f"停止通知（{reason or 'stop'}）：请收工并停掉你起的子进程",
                      "called_by": str(by or S.CONDUCTOR_ROLE),
                      "parent_task_id": t["tid"], "depth": t["depth"],
                      "input_key": f"stop-notice@{mine}->{t['tid']}"} for t in todo],
                    details=[detail for _ in todo])
            except Exception as exc:  # noqa: BLE001 —— 整批不落盘，逐条如实报"没开成"
                for t in todo:
                    skipped.append({"child_task_id": t["tid"],
                                    "why": f"通知项没开成（整批回滚）："
                                           f"{type(exc).__name__}: {exc}"})
                item_ids = []
            if item_ids:
                pairs = [(t["tid"], t["at"], item_id)
                         for t, item_id in zip(todo, item_ids)]
                self._mark_stop_notified_many(mine, pairs)
                for t, item_id in zip(todo, item_ids):
                    notified.append({"child_task_id": t["tid"], "item_id": item_id,
                                     "at": t["at"]})
        out: dict[str, Any] = {"checked": True, "notified": notified, "skipped": skipped,
                               "reason": ""}
        if not kids:
            out["note"] = ("我名下此刻没有在飞的直接子代理 ⇒ 这一趟没有边要通知"
                           "（不是『通知过了』）")
        return out

    def _mark_stop_notified_many(self, parent_task_id: str,
                                 pairs: Sequence[tuple[str, str, str]]) -> list[tuple[str, str]]:
        """批量记"这几条边通知过了"（一笔事务；返回逐条 `(mark, 问题)`）。

        `pairs` 是 `(子代号, 时刻, 通知项号)`。为什么一笔事务能写出与逐条同样的事件：
        `Tx.upsert` 每次调用记一条事件，所以本方法逐条 `upsert` 父那一行的推进中的
        `inputs` —— 事件条数、`op`、`note`（`edge:stop-notified`）与逐条路径逐条相同，
        差的只有提交标记（一笔一条）。幂等与"父行没有 ⇒ 报问题"逐字照旧。
        为什么要批量（2026-10-27）：改前每条边一笔事务，而它们改的是同一行、
        同一拍 —— 12 条边 = 12 次整表读 + 12 次整表写。
        """
        out: list[tuple[str, str]] = []
        self._refuse_write_in_snapshot("批量记停止通知（_mark_stop_notified_many）")
        try:
            with self.store.tx("tasks", actor="conductor", note="edge:stop-notified") as tx:
                parent = tx.find("tasks", task_id=parent_task_id)
                if parent is None:
                    why = f"没有这一行（parent_task_id={parent_task_id!r}）"
                    return [("", why) for _ in pairs]
                marks = [str(x) for x in (parent.get("inputs") or [])]
                for child_task_id, at, item_id in pairs:
                    mark = f"{self._STOP_NOTIFIED_PREFIX}{child_task_id}@{at}|{item_id}"
                    if any(m.startswith(f"{self._STOP_NOTIFIED_PREFIX}{child_task_id}@")
                           for m in marks):
                        out.append(("", "已经记过（幂等：不写第二份）"))
                        continue
                    marks = sorted(set(marks) | {mark})
                    parent["inputs"] = marks
                    task = S.Task(**{k: v for k, v in parent.items()
                                     if k in S.Task.__dataclass_fields__})
                    task.validate()
                    tx.upsert("tasks", task.to_dict(), note="edge:stop-notified")
                    out.append((mark, ""))
        except Exception as exc:  # noqa: BLE001 —— 落痕失败不该让"通知"这件事失效
            return [(("" if i >= len(out) else out[i][0]), f"{type(exc).__name__}: {exc}")
                    for i in range(len(pairs))]
        return out

    def note_stop_ack(self, parent_task_id: str, child_task_id: str, *,
                      at: str = "") -> tuple[str, str]:
        """把"这条边的停止通知被确认了"写进父那一行的 `inputs`（S4-b）。

        为什么时间不写在通知项上：`schema` 把 `item_close` 收成受控词表
        （只许 `acked` / `completed`）—— "知道了"与"做完了"是两种收口，不许含糊。
        于是 ack 的时刻落在父那一行的落痕里（与 `stop-notified:` 同一族，不动 schema）：
        `stop-acked:<子代号>@<时间>`。幂等：同一条边已经有 ack 落痕 ⇒ 不写第二份。
        """
        mark = f"{self._STOP_ACKED_PREFIX}{child_task_id}@{str(at or S.now_iso())}"
        try:
            self._refuse_write_in_snapshot("记停止确认（note_stop_ack）")
            with self.store.tx("tasks", actor="conductor", note="edge:stop-acked") as tx:
                parent = tx.find("tasks", task_id=parent_task_id)
                if parent is None:
                    return "", f"没有这一行（parent_task_id={parent_task_id!r}）"
                marks = [str(x) for x in (parent.get("inputs") or [])]
                if any(m.startswith(f"{self._STOP_ACKED_PREFIX}{child_task_id}@")
                       for m in marks):
                    return "", "已经记过（幂等：不写第二份）"
                parent["inputs"] = sorted(set(marks) | {mark})
                task = S.Task(**{k: v for k, v in parent.items()
                                 if k in S.Task.__dataclass_fields__})
                task.validate()
                tx.upsert("tasks", task.to_dict(), note="edge:stop-acked")
        except Exception as exc:  # noqa: BLE001 —— 落痕失败不该让 ack 这件事失效
            return "", f"{type(exc).__name__}: {exc}"
        return mark, ""

    def stop_edge_readings(self, parent_task_id: str) -> dict[str, Any]:
        """每条开着的边一行：`{edge, notified_at, acked_at, settled_at, timeout}`（三态）。

        - `notified_at`：沿边下发那一刻（父那一行的 `inputs` 落痕里）；
        - `acked_at`：那条通知项被 ack 的时刻（`item_close` 写成 `acked@<时间>`）；
          空串 = 还没 ack —— 于是"通知了"与"通知到了"在读数上分得开；
        - `settled_at`：子那一行写终态的时刻（`ended_at`）；
        - `timeout`：通知了、但子到此刻还没写终态（有界等待到点后的那一档）。

        `reported_at`（交差边）这一批不算：交差边与委派边不是一条边（`draft/84` §2.2
        的坑②），它要看手稿行 —— 留待下一批，不在这里编一个近似值。
        读不成 ⇒ `checked=False`（不许把"没读成"报成"没有边"）。
        """
        try:
            rows = {str(r.get("task_id")): r for r in self._tasks()}
        except Exception as exc:  # noqa: BLE001
            return {"checked": False, "edges": [], "reason": f"{type(exc).__name__}: {exc}"}
        parent = rows.get(str(parent_task_id))
        if parent is None:
            return {"checked": False, "edges": [],
                    "reason": f"台账里没有 {parent_task_id!r}"}
        item_state = {str(r.get("task_id")): r for r in rows.values()}
        acked_marks: dict[str, str] = {}
        for raw in (parent.get("inputs") or []):
            text = str(raw)
            if text.startswith(self._STOP_ACKED_PREFIX):
                body = text[len(self._STOP_ACKED_PREFIX):]
                child, _, at = body.partition("@")
                acked_marks[child] = at
        out: list[dict[str, Any]] = []
        for raw in (parent.get("inputs") or []):
            text = str(raw)
            if not text.startswith(self._STOP_NOTIFIED_PREFIX):
                continue
            body = text[len(self._STOP_NOTIFIED_PREFIX):]
            child, _, rest = body.partition("@")
            at, _, item_id = rest.partition("|")
            item = item_state.get(item_id) or {}
            kid = item_state.get(child) or {}
            ended = str(kid.get("ended_at") or "")
            # 读数与 `note_edge_release` 同一口径（RETIREFIX）：落痕记在"被通知的子"上，
            # 或者（更早的写法）记在"读到并 ack 它的那个台账号"上 —— 后者由通知项自己的
            # `seen_by` 指出来。两处读法必须一致，否则"门放行了、读数说没 ack"。
            acked_at = str(acked_marks.get(child)
                           or acked_marks.get(str(item.get("seen_by") or "")) or "")
            out.append({"edge": {"parent_task_id": str(parent_task_id),
                                 "child_task_id": child},
                        "notified_at": at, "acked_at": acked_at,
                        "settled_at": ended, "item_id": item_id,
                        "item_state": str(item.get("item_state") or ""),
                        "timeout": bool(at and not ended)})
        out.sort(key=lambda x: str(x["edge"]["child_task_id"]))
        return {"checked": True, "edges": out, "reason": ""}

    def note_edge_release(self, parent_task_id: str, *, child_task_id: str,
                          attempt: int = 1) -> tuple[str, str]:
        """记一笔"这条边已经认过了"（幂等键 = `(子代号, 第几次)`）。返回 `(落痕, 问题)`。

        ## 为什么是"标记"而不是"删一行"（`draft/92` I-12）：边是派生的读数（子行的 `parent_task_id` + 状态），没有一张
        可删的边表；所以"删边"落到盘上是"父已经认过这条边"的落痕，写在父那一行的 `inputs`（与 `_ADMITTED_MARK` /
        `_SETTLED_MARK` 同一族，不动 `schema.py`）。
        ## 三条结构判据（判定与决定不在这里）：子必须真实存在、且 `parent_task_id` 就是这位父；子必须是代理行
        （`kind == ""`）—— 工作项不是代理（两轴分开）；子必须不在跑（`status ∉ {pending, running}`）—— 还在跑就记
        "已经消过"是最坏的一种假成功（业主 §1.9 第①支：活跃 ⇒ 先把最近报告端给父，不退役）。
        幂等：同一 `(子代号, 第几次)` 第二次 ⇒ 返回 `("", "已经记过")`，不写第二份。谁、什么时候、依据哪几条（"工作"
        层面的读数）由调用方（秘书的 `retire`）写进会话事件 —— 这一笔只管"父侧认过"这件事本身。
        """
        mark = f"{_EDGE_RELEASED_PREFIX}{child_task_id}#{int(attempt)}"
        with self.store.tx("tasks", actor="conductor", note="edge:released") as tx:
            parent = tx.find("tasks", task_id=parent_task_id)
            if parent is None:
                return "", f"没有这一行（parent_task_id={parent_task_id!r}）"
            child = tx.find("tasks", task_id=child_task_id)
            if child is None:
                return "", f"没有这个子（child_task_id={child_task_id!r}）"
            if str(child.get("parent_task_id") or "") != str(parent_task_id):
                return "", (f"{child_task_id} 不是 {parent_task_id} 的子"
                            f"（它的父是 {child.get('parent_task_id')!r}）")
            if str(child.get("kind") or ""):
                return "", f"{child_task_id} 是工作项（kind={child.get('kind')!r}），不是代理"
            if str(child.get("status") or "") in UNFINISHED_STATUSES:
                return "", (f"{child_task_id} 还在跑（status={child.get('status')!r}）"
                            "⇒ 不许记消边（先把它的最近报告端给父）")
            # S4-b（`draft/84` §2.2）：停止通知要 ack 才算传达到 —— 这条边如果被
            # 沿边下发过一条 notice，而那条通知还没 ack ⇒ 不许消边（负控：抹掉 ack ⇒ 拒）。
            # 只在"通知过"的边上要求（正常退役那些边没有通知项，照旧）。
            #
            # RETIREFIX（2026-11-21）：落痕的"子代号"有两种历史写法 —— `stop-acked:<被通知
            # 的那条边的子>`（2026-11-21 之后的写侧，`_ack_stop_notice` 已改对）与更早的
            # `stop-acked:<读到并 ack 它的那个台账号>`（名册名复用时两者不同：真机
            # lp-ball-15 的通知项 t-000151 收件人是 t-000147，ack 它的是 t-000128）。
            # 两种写法都证明"这一条通知被 ack 了"，所以两种都认；都不在 ⇒ 照旧拒。
            marks_now = [str(x) for x in (parent.get("inputs") or [])]
            pending = [m for m in marks_now
                       if m.startswith(f"{self._STOP_NOTIFIED_PREFIX}{child_task_id}@")]
            if pending:
                item_id = pending[-1].split("|", 1)[1] if "|" in pending[-1] else ""
                item = tx.find("tasks", task_id=item_id) if item_id else None
                close = str((item or {}).get("item_close") or "")
                acked_marks = {str(x)[len(self._STOP_ACKED_PREFIX):].split("@", 1)[0]
                               for x in marks_now if str(x).startswith(self._STOP_ACKED_PREFIX)}
                # 通知项自己记着"谁读的"（`seen_by`）：那一格也认，理由见上面那一段。
                reader = str((item or {}).get("seen_by") or "")
                acked = (child_task_id in acked_marks
                         or (reader and reader in acked_marks))
                if close != "acked" or not acked:
                    return "", (f"{child_task_id} 的停止通知还没被确认（通知项 "
                                f"{item_id or '未记'}：item_close={close!r}、"
                                f"ack 落痕={'有' if acked else '没有'}）"
                                "⇒ 不许消边：ack 才算传达到（`draft/84` §2.2）")
            marks = [str(x) for x in (parent.get("inputs") or [])]
            if mark in marks:
                return "", "已经记过（幂等：不写第二份）"
            # `inputs` 是集合类字段：schema 的不变量要求升序去重
            # （`check_array_invariants` 会当场拒；实测：直接 append 会报
            # "inputs 声明为集合但未升序去重"）⇒ 这里排一次序。
            parent["inputs"] = sorted(set(marks) | {mark})
            task = S.Task(**{k: v for k, v in parent.items()
                             if k in S.Task.__dataclass_fields__})
            task.validate()
            tx.upsert("tasks", task.to_dict(), note="edge:released")
        return mark, ""

    @staticmethod
    def _released_pairs(row: Mapping[str, Any]) -> list[dict[str, Any]]:
        """一行代理里"父已经销过哪些子"的落痕（逐条 `(子代号, 第几次)`）。

        为什么抽成静态方法：落痕的格式只有一处（`note_edge_release` 写的那个前缀），
        而读侧已经有两处（`released_edges` 与 `retire_integrity`）—— 两处各写一遍
        解析，迟早一处改了另一处没改，而分叉的形态是"销号门说干净、final 门说没销"。
        """
        out: list[dict[str, Any]] = []
        for raw in ((row or {}).get("inputs") or []):
            text = str(raw)
            if not text.startswith(_EDGE_RELEASED_PREFIX):
                continue
            child, _, attempt = text[len(_EDGE_RELEASED_PREFIX):].partition("#")
            out.append({"child_task_id": child, "attempt": int(attempt or 0)})
        out.sort(key=lambda x: (x["child_task_id"], x["attempt"]))
        return out

    def released_edges(self, parent_task_id: str) -> dict[str, Any]:
        """读回父侧认过的那些边（三态）：`{"checked", "edges": [{"child_task_id","attempt"}], "reason"}`。

        读不成（或没有那一行）⇒ `checked=False` + `reason`；不许返回空表冒充满足
        （"没查成"与"一条都没认过"在本仓是两件事）。
        """
        try:
            row = self._task(parent_task_id)
        except Exception as exc:  # noqa: BLE001
            return {"checked": False, "edges": [], "reason": f"{type(exc).__name__}: {exc}"}
        if row is None:
            return {"checked": False, "edges": [],
                    "reason": f"台账里没有 {parent_task_id!r}"}
        return {"checked": True, "edges": self._released_pairs(row), "reason": ""}

    def retire_integrity(self, root_task_id: str) -> dict[str, Any]:
        """`root_task_id` 名下整棵树是不是已经全部销号（M 收工前的结构完整性闸）。

        口径：「最终 final 时应该是 M 下整棵树都已销号，否则不记 final」。
        没有这条读数时，M 名下有几十个还在册的代理，与它收工那件事毫无关系 ——
        整棵树没销号而 final 照记。

        返回 `{"checked","complete","root","nodes","dirty","count","total",
        "root_open_items","states","stalled","stalled_count","clock","programs","reason"}`：

        - `checked`：台账读到没有（读不成 ⇒ `False` + `reason`，绝不折成"干净"）；
        - `complete`：这一支是否全部销号（`nodes` 与 `dirty` 都空才算）；
        - `nodes`：还在册的节点，逐条给 `task_id` / `role` / `status` / `retired` /
          `open_items` / `open_item_ids`（前 8 条）/ `open_item_expects` 与
          `open_item_states`（同一批前 8 条的逐条读数，RETIREFIX 加）/ `state` /
          `state_label` / `blocking` / `stalled` / `stalled_sec` ——
          这就是拒信里那份清单；
        - `dirty`：已经销号、可名下还有未消项的节点（结构矛盾那一档，同样算不干净）；
        - `count` / `total`：还在册几个 / 这一支一共有几个节点（不含根自己）；
        - `root_open_items`：根自己名下的未消项条数（读数，不参与判定 —— 根没有父，
          销号对它没有对象，而那句判据说的是"它下面那棵树"）；
        - `states`：这一支每个非根节点的三态合计（`state_counts`：四档 + `active` +
          `total`），`clock`：这一次读时钟簿记的三态。两者都是读数，不参与判定 ——
          `complete` 的定义一个字没动（「整棵树都已销号」就是它）；
        - `stalled` / `stalled_count`：疑似停滞的那些编号 / 几个。它是读数（父代理结项
          被拦时，拒信要点名"名下有 N 个在飞子，其中 M 个已停滞超过 N 分钟"），
          同样不参与 `complete` 的判定 —— 停滞不等于静默（见 `agent_state`）；
        - `programs`：这一支名下（含根那一行）还在跑的程序（`programs_in_subtree`
          那一份：`checked` / `running` / `unowned` / `orphans` / `reason`）。它也是读数，
          同样不参与 `complete` 的判定 —— 程序不是名册项，"整棵树都已销号"数的是名册。
          那一条"程序还在跑就不许收工"由 `_final_gate_reading` 说（两轴分开、各说各的那一句）。

        ## 销号变难之后，final 的门没有变
        销号只可针对静默子代理之后，一个挂着计时器的子代理不再能被销掉。所以这一份
        读数多了一层用途 —— 谁在等、等的是哪一条钟，`nodes[].state` /
        `nodes[].blocking` 逐条给出来。但"整棵树已销号"这个判据仍然只是"还在册的都是
        0"，不因为读数变多而变宽或变窄。

        ## 销号的判据取哪一处
        取父行 `inputs` 里的 `edge-released:` 落痕（`Secretary.retire` 每次销号都会先写它，
        写不成就不许销号）—— 它与名册三份台账同源，而这一层读得到、不必去翻 N 份名册文件。
        判据本身只有 `_released_pairs` 一处（`released_edges` 与这里共用）。

        ## 三态与代价
        台账读不成、根那一行不存在 ⇒ `checked=False`。把这两种折成"干净"的代价是
        整棵树没销号而 final 照记（那句话正好要挡住这一档）。
        """
        out: dict[str, Any] = {
            "checked": True, "complete": False, "root": str(root_task_id or ""),
            "nodes": [], "dirty": [], "count": 0, "total": 0,
            "root_open_items": 0, "states": None,
            "stalled": [], "stalled_count": 0,
            "clock": {"checked": False, "count": 0, "reason": ""}, "reason": "",
            # 程序读数：这一支名下（含根那一行）还有几个程序在跑。它是本方法的读数
            # 格子，不参与 `complete` 的判定 ——"整棵树都已销号"这个判据一个字没动，
            # 程序那一半由 `_final_gate_reading` 与收工门自己说（那里才是"不许静默"的落点）。
            "programs": {"checked": False, "running": [], "running_count": 0,
                         "unowned": [], "unowned_count": 0,
                         "orphans": {"no_timer": [], "finished_but_alive": []},
                         "orphan_count": 0, "reason": ""},
        }
        root = str(root_task_id or "")
        if not root:
            out["checked"] = False
            out["reason"] = "没给根台账号 ⇒ 不知道该看哪一棵树（不猜）"
            return out
        try:
            rows = self._tasks()
        except Exception as exc:  # noqa: BLE001 —— 读不成是"没查成"
            out["checked"] = False
            out["reason"] = f"tasks 台账读不成（{type(exc).__name__}: {exc}）⇒ 本次没查成"
            return out
        agents = {str(r.get("task_id") or ""): r for r in rows
                  if self._is_instance_row(r)}
        if root not in agents:
            out["checked"] = False
            out["reason"] = f"台账里没有 {root!r} 这一行代理 ⇒ 判不了它名下那棵树"
            return out
        kids: dict[str, list[str]] = {}
        for tid, row in agents.items():
            pid = str(row.get("parent_task_id") or "")
            if pid:
                kids.setdefault(pid, []).append(tid)
        # 显式栈（深链与坏链都不许把这里变成爆栈或死循环）；环上的节点只认一次。
        order: list[str] = []
        seen = {root}
        stack = [root]
        while stack:
            pid = stack.pop()
            for kid in sorted(kids.get(pid, ())):
                if kid in seen:
                    continue
                seen.add(kid)
                order.append(kid)
                stack.append(kid)
        open_items: dict[str, list[dict[str, str]]] = {}
        for row in rows:
            if not self._is_board_item(row):
                continue
            if str(row.get("item_state") or "") == "done":
                continue
            open_items.setdefault(str(row.get("parent_task_id") or ""), []).append(
                {"task_id": str(row.get("task_id") or ""),
                 "expects": str(row.get("expects") or ""),
                 "item_state": str(row.get("item_state") or "")})
        # 三态：整棵树一次算完（`agent_states` 是唯一实现；名册那一侧的事实只用到
        # "已销号"这一格 —— 收工闸说的"整棵树都已销号"就是 `_released_pairs` 那一条）。
        clock = clock_waiters(self.store.root)
        retired_of: dict[str, bool] = {}
        released_by_parent: dict[str, set[str]] = {}
        for tid, row in agents.items():
            pid = str(row.get("parent_task_id") or "")
            if pid not in released_by_parent:
                released_by_parent[pid] = {p["child_task_id"]
                                           for p in self._released_pairs(agents.get(pid, {}))}
            retired_of[tid] = tid in released_by_parent[pid]
        three = agent_states([agents[t] for t in sorted(agents)], clock=clock,
                             retired=retired_of)
        for tid in order:
            row = agents[tid]
            pid = str(row.get("parent_task_id") or "")
            released = released_by_parent.get(pid) or set()
            retired = tid in released
            mine = sorted(open_items.get(tid, ()), key=lambda x: x["task_id"])
            # 三态那一格只取一次：这个节点的 `state` / `state_label` / `stalled` /
            # `stalled_sec` 与 `blocking` 读的是同一格读数（原先每次 `three.get(tid)`
            # 再加一次 `or {}`，一个节点七遍）。判据一个字没动 —— `three` 在这之后只读。
            three_of = three.get(tid) or {}
            cell = {"task_id": tid, "role": str(row.get("role") or ""),
                    "status": str(row.get("status") or ""), "retired": bool(retired),
                    "open_items": len(mine),
                    "open_item_ids": [x["task_id"] for x in mine[:8]],
                    # RETIREFIX（2026-11-21）：dirty 那一档的逐条读数。收尾前自动收尾
                    # 只对"已被停止翻成 block 的 ack 通知"作废（`autoretire.dirty_voidables`），
                    # 判据需要逐条的 `expects` / `item_state`；`open_item_ids` 仍只给前 8 条，
                    # 条数对不上时那一侧一律不碰（fail-closed）。
                    "open_item_expects": {x["task_id"]: x["expects"] for x in mine[:8]},
                    "open_item_states": {x["task_id"]: x["item_state"] for x in mine[:8]},
                    "state": str(three_of.get("state") or AGENT_STATE_UNKNOWN),
                    "state_label": str(three_of.get("state_label") or ""),
                    # 疑似停滞：读数（拒信拿它说"其中 M 个已停滞"），不参与 complete。
                    "stalled": bool(three_of.get("stalled")),
                    "stalled_sec": three_of.get("stalled_sec"),
                    "blocking": retire_blocking(three_of)}
            if retired and mine:
                cell["why"] = "已经销号，可名下还有没消的项（结构矛盾那一档）"
                out["dirty"].append(cell)
                continue
            if not retired:
                cell["why"] = "还在册（它的父还没给它销号）"
                out["nodes"].append(cell)
        out["total"] = len(order)
        out["count"] = len(out["nodes"])
        out["root_open_items"] = len(open_items.get(root, ()))
        out["states"] = state_counts(str((three.get(tid) or {}).get("state") or "")
                                     for tid in order)
        out["stalled"] = sorted(tid for tid in order
                                if (three.get(tid) or {}).get("stalled"))
        out["stalled_count"] = len(out["stalled"])
        out["clock"] = {"checked": bool(clock.get("checked")),
                        "count": int(clock.get("count") or 0),
                        "reason": str(clock.get("reason") or "")}
        # 程序读数：收工门要的是"这一支还有没有进程在跑"，而那件事
        # 三态（无工作 / 无计时器 / 无活跃子）读不出来 —— 一台程序可以在一个
        # 被读成"静默"的节点名下继续跑（计时器根本没登记到它名下时就是这样）。
        # 这一格读的那一份与销号门是同一份（`programs_in_subtree`），不另判一遍。
        try:
            progs = self.programs_in_subtree(root)
        except Exception as exc:  # noqa: BLE001 —— 读不成是"没查成"
            progs = programs_reading(self.store.root, task_ids=(),
                                     blocked_reason=f"{type(exc).__name__}: {exc}")
        out["programs"] = {
            "checked": bool(progs.get("checked")),
            "running": list(progs.get("running") or ()),
            "running_count": int(progs.get("running_count") or 0),
            "unowned": list(progs.get("unowned") or ()),
            "unowned_count": int(progs.get("unowned_count") or 0),
            "orphans": dict(progs.get("orphans") or {}),
            "orphan_count": int(progs.get("orphan_count") or 0),
            "reason": str(progs.get("reason") or ""),
        }
        out["complete"] = not out["nodes"] and not out["dirty"]
        return out

    def keep_alive_of(self, task_id: str) -> dict[str, Any]:
        """这一项/这个代理声明的"做完还待命"（A6=丙）。`{"checked","keep_alive","reason"}`。

        ## 声明落在派活项上，不在代理行上：`schema.Task.validate` 只允许 `kind == "delegation"` 的行带 `keep_alive`
        （"只有派活项才谈得上待命"）。所以对代理行问这一格时，读的是它名下最新的那条派活项（= 父最后一次派给它那件
        活时的声明）。## 判据用的是哪一半（`draft/92` §15.6 的订正）：主控先前把它读成"待命的父不许消边"——读错了：
        业主 §1.9 的三分支里"在等待"正是可以退役的那一支，只要它自己名下没有活跃子代理。所以这一格只回答"它是不是
        声明过待命"，不参与"能不能退役"的判定（那一条由秘书的三分支说，S1k；"活跃 / 在等待"由 `active_children`
        说）。三态：没有那一行 / 读不成 ⇒ `checked=False`（不许折成"没声明过"）。

        ## 一拍只读一次台账（2026-10-27）
        改前这一格对同一张 `tasks` 表读了两遍：先 `_task(task_id)`（整表 `rows()` + 线性扫），
        再为"它名下最新的那条派活项"扫第二遍 `_tasks()`。而 `store.rows()` 没有缓存
        （`store._load` 每次都整文件 `json.loads`），所以单价 = 一次全表反序列化。
        调用它的秘书名册那一层是逐名册项跑的 ⇒ 名册 N 项就有 2N 次全表读。
        实测（`temp/r_be2_reads_per_beat2.py`，12 项名册 / 13 行台账）：`roster_view` 一拍
        `store.rows("tasks")` 31 次 = 2N+7；这一格收成一次读之后是 N+7。
        判据一字不动（三态、`kind == "delegation"` 的早退、取"最新那条"的排序键都没改）。
        """
        try:
            rows = self._tasks()
        except Exception as exc:  # noqa: BLE001
            return {"checked": False, "keep_alive": False,
                    "reason": f"{type(exc).__name__}: {exc}"}
        row = next((r for r in rows if r.get("task_id") == task_id), None)
        if row is None:
            return {"checked": False, "keep_alive": False,
                    "reason": f"台账里没有 {task_id!r}"}
        # 问的是"这一行是不是一条派活项"（待命声明只落在 `kind="delegation"` 的行上，
        # `schema.Task.validate` 的受控条件），不是"它是不是板项" —— 轴不走 row_axis。
        if str(row.get("kind") or "") == "delegation":
            return {"checked": True, "keep_alive": bool(row.get("keep_alive")), "reason": ""}
        items = [r for r in rows
                 if r.get("parent_task_id") == task_id
                 and str(r.get("kind") or "") == "delegation"]
        if not items:
            return {"checked": True, "keep_alive": False, "reason": ""}
        items.sort(key=lambda r: (str(r.get("started_at") or ""), str(r.get("task_id") or "")))
        return {"checked": True, "keep_alive": bool(items[-1].get("keep_alive")), "reason": ""}

    def reusable_children_of(self, parent_task_id: str, *, role: str = "") -> dict[str, Any]:
        """父名下可复用的活跃子代理（业主 "派活不一定是增"）。三态返回：

        `{"checked": bool, "rows": [{"task_id","role","state"}], "reason": ""}`
        ## 口径（`draft/92` §3.1 与 §7-②）：只数代理行（`kind == ""`）：工作项不是代理（两轴分开）；`role` 给了就只看
        那个角色，没给 ⇒ 全给（不替调用方猜"大概想复用谁"）；复用资格 = 那一行此刻活跃（在跑一次调用 ⇒ 可以再派
        一件）或是待命（无活跃调用，且 `keep_alive_of` 说它名下最新那条派活项声明过待命，A6=丙）；已停且没声明待命
        ⇒ 不许复用（要派活就新起一个）；"已退役"这一档不在这一层判（那是名册/对照表的事，S1k）—— 本方法只回答"台账
        上此刻有没有可以再接一件活的子代理"。
        ## 为什么它只给候选、不给"就是它"：复用必须是父点名（`reuse:"D1"`，业主 B2），而名字到代号的译码在秘书那一
        侧（S1k）。所以这里返回候选清单；不"挑一个最合适的" —— 猜错就是把一件活派给了别人。
        ## 三态：台账读不成、或某一行 `keep_alive_of` 读不成 ⇒ `checked=False` + `reason`，不许折成"没有可复用的"
        （那会把复用静默变成新起，而新起的代价是白烧一次钱）。
        """
        try:
            rows = self._tasks()
        except Exception as exc:  # noqa: BLE001
            return {"checked": False, "rows": [], "reason": f"{type(exc).__name__}: {exc}"}
        out: list[dict[str, str]] = []
        for r in rows:
            if r.get("parent_task_id") != parent_task_id or self._is_board_item(r):
                continue
            tid = str(r.get("task_id") or "")
            row_role = str(r.get("role") or "")
            if role and row_role != role:
                continue
            if str(r.get("status") or "") in UNFINISHED_STATUSES:
                out.append({"task_id": tid, "role": row_role, "state": "活跃"})
                continue
            try:
                ka = self.keep_alive_of(tid)
            except Exception as exc:  # noqa: BLE001 —— 读侧自己炸了也是"没读成"
                return {"checked": False, "rows": out,
                        "reason": f"{tid} 的待命声明没读成（{type(exc).__name__}: {exc}）"}
            if not isinstance(ka, dict):
                return {"checked": False, "rows": out,
                        "reason": f"{tid} 的待命声明没读成（读数不是对象）"}
            if not ka.get("checked"):
                return {"checked": False, "rows": out,
                        "reason": f"{tid} 的待命声明没读成（{ka.get('reason')}）"}
            if ka.get("keep_alive"):
                out.append({"task_id": tid, "role": row_role, "state": "待命"})
        out.sort(key=lambda x: x["task_id"])
        return {"checked": True, "rows": out, "reason": ""}

    def retire_ready(self, parent_task_id: str) -> dict[str, Any]:
        """父名下那几项现在可以退役了 —— 只报不动作（业主 T22 与 §1.9 的三分支）。

        `{"checked": bool, "ready": [{"task_id","role","branch","reading"}], "reason": ""}`
        逐项分类（与 `draft/90` §1.9 的分支逐字对齐，一处实现）：
        - `branch="active"`：这一项还在跑（`status ∈ {pending, running}` 且没有交差）⇒ 父该做的是"先看它最近报了什么"，不许退役；
        - `branch="waiting_no_children"`：它不在跑，且它自己名下没有活跃子代理 ⇒ 可以退役（业主那一句的"无活跃子代理
          且自身完全停止"说的是它自己，不是父 —— 见 `draft/92` §15.6 的订正）；
        - `branch="waiting_with_children"`：它不在跑，但它自己名下还有活跃子代理 ⇒ 不退役，父该看的是"它还在干什么活"。
        `reading` 里附一格 `items_open`（它名下未消的项有几条）—— 只报不拦（业主的算法里没有这一条；主控不加隐藏的
        拦截条件，C2 的裁定）。RETIREFIX（2026-11-21）起另附三格 `items_open_ids`（逐条编号）/
        `items_open_expects`（编号 → `expects`）/ `items_open_states`（编号 → `item_state`）：收尾前自动收尾要靠它们
        判"这几条是不是框架自己在优雅停止时翻成 `block` 的 ack 通知"，而 `items_open` 那一个数判不出来
        （`expects=work` 的义务项、`seen` 的通知、`block` 的通知在"几条"上是同一个数）。
        ## 交差那一档为什么不算"还在跑"
        交差账（`handoff_index`）上有它 ⇒ 业主 2026-10-27 第四条把它记为静默；同一份事实
        在 `agent_state` 第 ⑥ 步里也是"它不再自己跑"。两处必须同一口径，否则销号门上
        "可以销"与"不可以销"会各说各的（父读到"可销"、去销又吃到 `target_not_silent`，
        而它占着的扇出名额谁也腾不出来）。所以这里的 `active` 也读那一格。## 为什么它只报不动作：业主逐字：「子代理宣布收工后，由父代理决定是否消边」。所以框架
        给的是就绪读数，写盘那一步在 `Secretary.retire`（S1k，父说了才做）。本方法零写入。
        ## 三态与代价：读不成 ⇒ `checked=False` + `reason`（不许折成"没有可退役的"：那会让父以为"还没到时候"）。整个
        方法只读一次台账快照（`_tasks()`），逐项判据都在这份快照上做，不嵌套调用别的读侧。已经记过消边的那些
        （`released_edges`）直接跳过：它们不再是"可退役"的候选。
        """
        try:
            rows = self._tasks()
        except Exception as exc:  # noqa: BLE001
            return {"checked": False, "ready": [], "reason": f"{type(exc).__name__}: {exc}"}
        # 销过的边就在上面这一份快照里读（2026-10-27）：改前这里调
        # `released_edges(parent_task_id)`，而它内部是 `_task()` ⇒ 同一拍对 `tasks`
        # 表再读一次（`store.rows` 无缓存，单价 = 一次全表 `json.loads`）。
        # 解析仍然只走 `_released_pairs` 那一处（落痕格式的唯一读法），
        # 三态也一字不动：父那一行不在 ⇒ 与 `released_edges` 的 `checked=False` 同一条
        # 结果（下面 `done` 为空集 ⇒ 没有哪条边算销过）。
        parent_row = next((r for r in rows if r.get("task_id") == parent_task_id), None)
        # 只需"这个名字销过没有"：改前先把边收成 `(子, 第几次)` 的集合、再逐行
        # `any(c == tid for c, _a in done)`（O(行数 × 销过的边数)），而它问的正是
        # 下面这个集合 —— 落痕格式仍然只走 `_released_pairs` 那一处解析。
        done_children = {e["child_task_id"]
                         for e in (self._released_pairs(parent_row) if parent_row else [])}
        # 交差账（唯一读口）：账上有它 ⇒ 不算"还在跑"（业主 2026-10-27 第四条把它记为
        # 静默；与 `agent_state` 第 ⑥ 步同一份事实）。读不成 ⇒ 空集：维持既有判法
        # （"在飞"是保守方向 = 不退役）。
        hand = handoff_index(str(getattr(self.store, "root", "") or ""))
        handed = set(hand.get("by_task") or ()) if hand.get("checked") else set()
        active_by_parent: dict[str, int] = {}
        #: RETIREFIX（2026-11-21）：未消项从"只数条数"改成"逐条带 `expects`"。
        #: 为什么不多一个读数、也不改 `items_open` 的类型：`items_open` 是既有口径
        #: （只报不拦，业主 C2），收尾前自动收尾要判的是另一件事 —— "这几条是不是
        #: 只剩 ack 通知"，而那一格必须有逐条的 `expects` 才判得出（`b-register@`
        #: 那种 `expects=work` 的义务项一个字节都不许被自动作废）。见 `autoretire`。
        items_by_parent: dict[str, list[dict[str, str]]] = {}
        for r in rows:
            pid = str(r.get("parent_task_id") or "")
            if not pid:
                continue
            if self._is_board_item(r):
                if str(r.get("item_state") or "") != "done":
                    items_by_parent.setdefault(pid, []).append(
                        {"task_id": str(r.get("task_id") or ""),
                         "expects": str(r.get("expects") or ""),
                         "item_state": str(r.get("item_state") or "")})
                continue
            if (str(r.get("status") or "") in UNFINISHED_STATUSES
                    and str(r.get("task_id") or "") not in handed):
                active_by_parent[pid] = active_by_parent.get(pid, 0) + 1
        ready: list[dict[str, Any]] = []
        for r in rows:
            if r.get("parent_task_id") != parent_task_id or self._is_board_item(r):
                continue
            tid = str(r.get("task_id") or "")
            if tid in done_children:
                continue
            if (str(r.get("status") or "") in UNFINISHED_STATUSES
                    and tid not in handed):
                branch = "active"
            elif active_by_parent.get(tid, 0) > 0:
                branch = "waiting_with_children"
            else:
                branch = "waiting_no_children"
            ready.append({"task_id": tid, "role": str(r.get("role") or ""),
                          "branch": branch,
                          "reading": {"items_open": len(items_by_parent.get(tid, [])),
                                      "items_open_ids": [x["task_id"] for x in
                                                         items_by_parent.get(tid, [])],
                                      "items_open_expects": {x["task_id"]: x["expects"]
                                                             for x in
                                                             items_by_parent.get(tid, [])},
                                      "items_open_states": {x["task_id"]: x["item_state"]
                                                            for x in
                                                            items_by_parent.get(tid, [])}}})
        ready.sort(key=lambda x: x["task_id"])
        return {"checked": True, "ready": ready, "reason": ""}

    def board_readings(self) -> dict[str, Any]:
        """板上读数（三态：读不成 ⇒ `checked=False`，不许返回一串 0）。"""
        try:
            rows = self._board_rows()
        except Exception as exc:  # noqa: BLE001 —— 读不成是"没查成"，与"板上没事"两件事
            return {"checked": False, "reason": f"{type(exc).__name__}: {exc}"}
        by_state: dict[str, int] = {s: 0 for s in S.ITEM_STATES}
        by_close: dict[str, int] = {c: 0 for c in S.ITEM_CLOSES}
        for r in rows:
            st = str(r.get("item_state") or "")
            if st in by_state:
                by_state[st] += 1
            cl = str(r.get("item_close") or "")
            if cl in by_close:
                by_close[cl] += 1
        return {"checked": True, "board_rows": len(rows), "by_state": by_state,
                "by_close": by_close,
                "old_instance_rows": len(self._tasks()) - len(rows)}

    def board_view(self, *, limit: int = 20, by_task_id: str = "") -> dict[str, Any]:
        """给主控/父级看的"还挂着什么"（只读，不含建议）。

        口径（甲形态的一条硬约束）：`tasks` 现在有两类行 —— 板项（`kind` 非空）与老实例行
        （`kind` 为空）。两边不许混：这个视图只数板项，"派了几件活"那一类旧读数只数后者。

        两个数各一个名（153-U-05，业主 2026-11-03 的裁决 4）—— 它们不同源，不许并：
        - `board_open_count` / `board_open_items`：这个名字量的是真板项（`tasks` 里
          `kind` 非空且 `item_state != done`）的件数与明细，落台账、可复算；
        - `pending_attack_count` / `pending_search_count`（+ 对应的 `*_items`）：量的是合成项
          —— 由猜想与文献现状每拍现造、不落台账 ⇒ 并进上面那个数就再也说不清"板上还剩几件活"。

        ## `by_task_id`：每一项的 `revoke` 格按看的人算（甲件，业主 2026-11-06）

        改前每一项只有 `task_id`：模型得把 id 搬到 `conductor.void_items`、被拒一次，
        才知道"这一条我撤不撤得动"。现在每一项带一格 `revoke`（形状与判据见
        :meth:`revocation_cell`）：能不能撤、该用哪个动作、参数骨架是什么。
        `by_task_id` 不给 ⇒ 读调用上下文（`calling_as` 挂的台账号）；两处都没有 ⇒
        每一项的 `revoke` 都是 `checked=False` 那一档（"不知道你是谁"，不是"你没有权限"）。
        """
        viewer = str(by_task_id or "") or current_task_id()
        try:
            all_rows = [dict(r) for r in self._tasks()]
        except Exception as exc:  # noqa: BLE001
            return {"checked": False, "reason": f"{type(exc).__name__}: {exc}",
                    "board_open_items": [], "board_open_count": 0}
        by_id = {str(r.get("task_id") or ""): r for r in all_rows}
        board_items = [r for r in all_rows
                       if self._is_board_item(r)
                       and str(r.get("item_state") or "") != "done"]
        # 2026-10-17（T5 第 2 趟真机读数驱动）：把"登记了但没人立项"的猜想
        # 变成板上的待办。为什么放在这里：D 的手册已经逐字写了"登记完猜想请接着把
        # 这一腿开出去"（且自己记着"第 10 趟 T5 这一环整环为 0"），可第 2 趟 T5 又是 0
        # —— 说明"再补一句说明"这条路无效。改成：让它在主控看得见的地方挂着，
        # 由派活的那一层决定要不要开（这里只亮出来、不点名动作，守"主控只派活"）。
        pending = self._pending_attack_items()
        # 2026-10-17（T5 第 2 趟）：文献缺口也亮出来（#3 的同一机制）。
        # 那趟的答案自己写着"Frey 曲线：未核到"，而它没有任何后续动作 —— 因为
        # "缺一篇"这件事当时只存在于模型的文字里，台账上看不见。现在变成板项：
        # `path` 空（只有元数据）或 `download.status` 不是 ok ⇒ 一条 `pending_search`。
        gaps = self._pending_search_items()
        board_items.sort(key=lambda r: (str(r.get("started_at") or ""),
                                        str(r.get("task_id") or "")))
        shown: list[dict[str, Any]] = []
        for r in board_items[:max(1, int(limit))]:
            row = dict(r)
            # 甲件：每一项直接带出"这一条能不能被你撤、撤它该用哪个动作"。
            row["revoke"] = self.revocation_cell(row, by_task_id=viewer, rows=by_id)
            shown.append(row)
        out = {"checked": True, "board_open_items": shown,
               "board_open_count": len(board_items), "readings": self.board_readings()}
        if pending:
            out["pending_attack_count"] = len(pending)
            out["pending_attack_items"] = pending[:max(1, int(limit))]
            out["pending_attack_note"] = ("这些是**已登记的猜想但还没有立项**"
                                          "（谁去立项由你派，别自己动手）；"
                                          "它们不计入 `board_open_count`（合成项不落台账）")
        if gaps:
            out["pending_search_count"] = len(gaps)
            out["pending_search_items"] = gaps[:max(1, int(limit))]
            out["pending_search_note"] = ("这些文献**只有元数据、没有全文**（或下载没成）"
                                          "—— 要补全文就派检索的那一位，别自己去找；"
                                          "它们不计入 `board_open_count`（合成项不落台账）")
        return out

    def _pending_search_items(self) -> list[dict[str, Any]]:
        """文献缺口：在册但没有全文（`path` 空或 `download.status` 不是 ok）⇒ 板项。

        读不成 ⇒ 空（宁可少一条待办，也不编造）。
        """
        try:
            lits = [dict(r) for r in self.store.rows("literature")]
        except Exception:  # noqa: BLE001
            return []
        items: list[dict[str, Any]] = []
        for r in lits:
            lid = str(r.get("lit_id") or "")
            if not lid:
                continue
            path = str(r.get("path") or "").strip()
            dl = r.get("download") if isinstance(r.get("download"), dict) else {}
            status = str((dl or {}).get("status") or "")
            if path and status in ("", "ok"):
                continue
            why = ("只有元数据（没有 path）" if not path
                   else f"下载未成（status={status or '空'}）")
            items.append({"task_id": f"pending-search-{lid}", "kind": "pending_search",
                          "item_state": "todo", "item_close": "", "lit_id": lid,
                          "detail": f"文献 {lid} {why} ⇒ 要补全文就派检索的那一位去取"})
            if len(items) >= 20:
                break
        return items

    def _pending_attack_items(self) -> list[dict[str, Any]]:
        """猜想已登记、但还没有对应的攻坚计划 ⇒ 一条板项（读不成 ⇒ 空，不假装）。"""
        try:
            cons = [dict(r) for r in self.store.rows("conjectures")]
            plans = [dict(r) for r in self.store.rows("attack_plans")]
        except Exception:  # noqa: BLE001 —— 读不成时不编造待办（宁可少一条）
            return []
        planned = set()
        for p in plans:
            # 两族键都当"已计划"（`problem_key` 与 `conjecture_id`）：一次遍历收完，
            # 集合语义不变（原先两个集合推导再并起来，同一批 plans 走了两遍）。
            planned.add(str(p.get("problem_key") or ""))
            planned.add(str(p.get("conjecture_id") or ""))
        items: list[dict[str, Any]] = []
        for c in cons:
            cid = str(c.get("conjecture_id") or "")
            # FIX186-E（2026-11-19）：已登记进命题台账的猜想不算「待登记」——
            # 「待登记」视图读的是行上落盘的 `registered_stmt_id`（B 收录成功即写），
            # 而不是"它现在叫什么状态"：一条猜想可以同时是 supported/refuted 且已毕业。
            if str(c.get("registered_stmt_id") or "").strip():
                continue
            # 2026-10-17（T2b 真机读数）：状态机是
            # `proposed → testing → (supported_not_proved | refuted | proved) → promoted`。
            # 原先只认 `proposed`，而 T2b 里那条猜想停在 `testing` 且没有任何计划 ——
            # 那同样是"该有人攻它却没有计划"，看板却一声不响。所以改成：
            # 未终态（没被证伪/证成/升格）且无计划 ⇒ 亮出来。
            if not cid or str(c.get("status") or "") in ("refuted", "proved", "promoted"):
                continue
            if cid in planned:
                continue
            items.append({"task_id": f"pending-attack-{cid}", "kind": "pending_attack",
                          "item_state": "todo", "item_close": "",
                          "conjecture_id": cid,
                          "detail": (f"猜想 {cid} 已登记（status=proposed）但**还没有攻坚计划**"
                                     f"—— 决定要不要开一条（该找的角色：能建计划的那一位）")})
        return items

    def item_readings(self, item_ids: Sequence[str]) -> dict[str, Any]:
        """这一批板项"开了几条 / seen 几条 / acked 几条"（三态；开了 ≠ 读到了）。

        为什么必须分开报（`draft/96` 的功能 15）：广播最容易撒的谎是"展开成功 = 都收到了"，
        而"板项开出来了"只说明框架写下了这件事，收件人有没有读进任何一步是另一回事
        （`item_state` 自己就是一串状态）。
        读不成 ⇒ `checked=False`（不许把"没读成"报成 0 条已读）。
        """
        want = {str(x) for x in item_ids}
        try:
            rows = [r for r in self._board_rows() if str(r.get("task_id")) in want]
        except Exception as exc:  # noqa: BLE001 —— 读不成 ≠ 都没读
            return {"checked": False, "opened": len(want), "seen": 0, "acked": 0,
                    "reason": f"板读不成（{type(exc).__name__}: {exc}）⇒ seen/acked 判不了"}
        # 两档计数一趟数完（原先这批行被走三遍：一遍取行、`seen` 一遍、`acked` 一遍），
        # `item_state` 每行只取一次。判据未动：`seen` 认 seen/claimed/done，
        # `acked` 只认 done（done 同时算进 seen —— 与两个 sum 各自的写法逐字等价）。
        seen = 0
        acked = 0
        for r in rows:
            state = str(r.get("item_state") or "")
            if state == "done":
                seen += 1
                acked += 1
            elif state in ("seen", "claimed"):
                seen += 1
        return {"checked": True, "opened": len(rows), "seen": seen, "acked": acked,
                "note": ("opened = 开出来的板项数；seen/acked = 此刻真的到了那两档的条数"
                         "（展开了不等于读到了）")}

    def broadcast(self, *, subject: str, body: str = "", by: str = "",
                  parent_task_id: str = "") -> dict[str, Any]:
        """一件广播能力：把一条通告投给我名下的直接子代理（业主 T20/T21）。

        口径（`draft/86` §14.1b，T21 之后的统一形态）：
        1. 收件人 = `_children_of(我)`（实例轴，`kind == ""`）—— 没有 `scope="tree"` 特权档：M 与其他角色完全一样，
           要全树就逐层向下（级联是收件人的动作，框架不代任何一层转发 ⇒ `cascade` 恒为 `children_decide`）；
        2. 每个收件人一条板项：`kind="message"`、`expects="ack"`、`parent_task_id = 收件人的编号`、
           `role = 收件人的角色`；正文进 `detail`（"每句话都要有行为"：内容是 detail、行为是 ack）；
        3. 不知道我是谁（没给编号、调用上下文里也没有）⇒ 不广播（三态：不许猜一个父号）；
        4. 我名下没有子代理 ⇒ 如实 `recipients=[]` + `note` 说清（不是"发出去了"）；
        5. `readings` 把"开了几条 / seen 几条 / acked 几条"分开报（展开了 ≠ 读到了）。
        返回 `{"checked","ok","broadcast","recipients","items","cascade","readings","note"}`。
        """
        mine = str(parent_task_id or "") or current_task_id()
        if not mine:
            return {"checked": True, "ok": False, "broadcast": "未发出", "recipients": [],
                    "items": [], "cascade": "children_decide",
                    "readings": {"checked": True, "opened": 0, "seen": 0, "acked": 0},
                    "error": ("不知道我是谁（没给父账号，调用上下文里也没有）⇒ 不广播："
                              "『我名下的子代理』枚举不出来（三态：不许猜一个父号）")}
        try:
            kids = [str(x) for x in self._children_of(mine)]
        except Exception as exc:  # noqa: BLE001 —— 读不成 ≠ 没有子代理
            return {"checked": False, "ok": False, "broadcast": "未发出", "recipients": [],
                    "items": [], "cascade": "children_decide",
                    "readings": {"checked": False, "opened": 0, "seen": 0, "acked": 0},
                    "error": (f"台账读不成（{type(exc).__name__}: {exc}）⇒ 不广播："
                              "『没读成』不是『我名下没有子代理』")}
        if not kids:
            return {"checked": True, "ok": True, "broadcast": "没有收件人", "recipients": [],
                    "items": [], "cascade": "children_decide",
                    "readings": {"checked": True, "opened": 0, "seen": 0, "acked": 0},
                    "note": ("我名下没有直接子代理 ⇒ 这一条没有收件人（不是『发出去了』）；"
                             "要覆盖全树得逐层向下转发")}
        who = str(by or "") or current_caller_role() or S.CONDUCTOR_ROLE
        stamp = hashlib.sha1(str(subject or "").encode("utf-8")).hexdigest()[:8]
        # 收件人那一行的 `role` / `depth` 只读一次索引（2026-10-27）：改前是逐子
        # `self._task(tid)` = 逐子一次整表读。
        by_id = self._tasks_by_id()
        # 一笔事务开完 N 条（2026-10-27）：改前每人两笔事务（开项 + 写说明），
        # 实测 42–93 ms/条 ⇒ 12 个人 0.5–1.1 s。落盘结果与逐条路径逐字节一致
        # （判据 `tests/test_board_batch_write.py`），而"全成或全不成"也一并有了。
        detail = (str(subject or "") + "\n" + str(body or "")).strip()[:400]
        items = self.open_items_many(
            [{"kind": "message", "role": str((by_id.get(str(tid)) or {}).get("role") or ""),
              "expects": "ack", "action": "message",
              "summary": str(subject or "")[:200], "called_by": who,
              "parent_task_id": tid,
              "depth": int((by_id.get(str(tid)) or {}).get("depth") or 1) + 1,
              "input_key": f"broadcast@{who}:{tid}:{stamp}"} for tid in kids],
            details=[detail for _ in kids])
        return {"checked": True, "ok": True, "broadcast": "已投递到名下子代理",
                "recipients": kids, "items": items, "cascade": "children_decide",
                "readings": self.item_readings(items),
                "note": ("每人一条 ack 板项（它们下次进循环时会渲染到）；"
                         "级联由它们各自决定 —— 框架不代转，要全树就逐层向下")}

    # ---------------------------------------------------------------- 上行（业主 2026-10-19）
    def _escalation_roster_check(self, *, mine: str, to: str, who: str,
                                 root: str) -> dict[str, Any]:
        """上行收件人的名册判据（与 `message` 同一份实现：`agent_loop.roster_addresses`）。

        业主 2026-10-19：「代理之间的通信必须经名册」；`escalate` 发的是父，但路径上必须真经过校验 —— "它本来就发给
        父"不是跳过校验的理由（改前这一支信任调用方给的 `parent_task_id`：给一个堂兄弟的编号，这条上行就写进了堂兄弟
        的收件箱）。三个取舍：只读名册、不另造判据（`roster_addresses` 是这件事的唯一实现，这里再写一遍"是不是我的
        父"就是第二份判据）；按绝对编号寻址（`to=父的台账号`）：角色名在同名多实例时是歧义的，而歧义在这里的代价是
        "这条上行投给了别人的父"；名册读不成 ⇒ 返回 `how="roster_unavailable"` 并把读数原样带出来（2026-10-22 起
        `roster_addresses` 在那一档给 `refused="roster_unavailable"`：私聊按它是受控拒绝，而上行在 `escalate` 里被
        显式放行 —— 见那里的注释。这一档不是"校验通过"，读数标着它）。
        """
        from . import agent_loop as AL

        out: dict[str, Any] = {"checked": False, "how": "roster_unavailable", "refused": "",
                               "error": "", "why": "", "to": str(to), "task_id": "",
                               "name": "", "kind": "", "role": "", "callable": "",
                               #: 这一趟用的秘书是哪一条缝（三档见 `secretary.seam_for_secretary`）。
                               #: 空串 = 沿用本实例已装配的那一名秘书（不在这里现造）。
                               "secretary_seam": "",
                               "candidates": []}
        sec = getattr(self, "secretary", None)
        if sec is None or not hasattr(sec, "roster_view"):
            try:
                # ---- 2026-10-26（真机 sylow5）：这一支也要带缝造秘书。
                #
                # 改前是裸的 `Secretary(...)`：没传 `seam=` ⇒ 这一名临时的秘书没有判断面
                # （`judge()` 永远 `checked=False`）。这条路上今天只读名册、不判命题，但
                # 「构造点漏了 seam=」正是 sylow5 那条死链的根因形态 —— 让它与别的构造点
                # 走同一支（`for_role_wired`），下一个把判据挂到这里的人不必再踩一次。
                # 缝从哪来写进读数 `addressing.secretary_seam`（拿不到时它连着为什么）。
                from .secretary import for_role_wired

                sec = for_role_wired(str(who or S.CONDUCTOR_ROLE), root=str(root),
                                     store=getattr(self, "store", None))
                out["secretary_seam"] = str(getattr(sec, "model_source", "") or "")
            except Exception as exc:  # noqa: BLE001 —— 拿不到名册 ⇒ 读数标出来（fail-open）
                out["why"] = f"名册拿不到（{type(exc).__name__}: {exc}）⇒ 退回运行期解析出的父"
                return out
        try:
            got = AL.roster_addresses(sec, to=str(to), owner=str(mine),
                                      my_task_id=str(mine), sender=str(who))
        except Exception as exc:  # noqa: BLE001 —— 判据自己坏了也是"没查成"
            out["why"] = f"名册寻址没跑成（{type(exc).__name__}: {exc}）⇒ 退回运行期解析出的父"
            return out
        return {**out, **dict(got)}

    def escalate(self, *, need: str, kind: str, evidence: Sequence[str] = (),
                 by: str = "", my_task_id: str = "", parent_task_id: str = "",
                 parent_role: str = "", session_root: str = "", sid: str = "",
                 ) -> dict[str, Any]:
        """把「我要召唤者做什么」写进父的收件箱（业主 2026-10-19 裁定：父子天然双向）。

        ## 为什么这条通道不属于"边"：父子身份在运行期已经解析出来了（`AgentLoop._resolve_parent`：调用方给的 / 台账
        读的 / 顶层自己），而 `edges` 是权限面（谁能召唤谁）。上行不是召唤、也不是新权限 —— 它就是"孩子跟召唤它的人
        说话"。于是这条入口不要求在 `edges` 里登记，收件人一律是 `_resolve_parent` 当次解析出的那一个。真机代价
        （`t5-run2`）：B 想找 A 说话只能借 `B→H` 绕两跳，因为"向上"没有入口 —— 这一格补的就是那个入口。
        ## 落点：父的收件箱（复用既有机制，不新造表）：`agent_message` 事件本来就是收件箱（`agent_loop.read_messages` /
        `inbox_digest` / `mark_delivered` 三件套）：私聊按 `to == 角色` 进收件人面，父下一趟进循环时会在开场提示词里
        看到它，读一次即由 `mark_delivered` 登记已读。所以这里没有新表、没有新文件：一条 `agent_message`，外加在同一
        行上带一格结构化的 `escalation`（`need` / `kind` / `evidence`）—— 键名写在同一条记录里，父与审计面都能机器读。
        它同时落一条 `agent_escalation` 事件（可审计的"这一趟为什么停在这里"）；停的那一半在循环里
        （`stop_reason="escalated"` ⇒ 退出码 5，见 `cli`）。## 三态（受控拒绝，不许静默成功）：
        | 情形 | `reason` | 写不写 |
        |---|---|---|
        | 没有父（顶层 M / 这一趟的父就是它自己） | `not_caller` | 一行都不写 |
        | 父的编号有、角色读不出来 | `parent_unknown` | 一行都不写（不猜一个收件人） |
        | 没有会话身份（root/sid 都没挂上） | `no_session` | 一行都不写（写进错的会话 = 没写） |
        | `need` 空 / 超 300 字 / `kind` 不在词表里 | `invalid_params` | 一行都不写 |
        | 留言写盘失败 | `inbox_write_failed` | 写没成，如实报（不是"已上报"） |
        成功那一档返回 `state="escalated"`（循环据此收工），失败那一档 `state="refused"`。
        """
        from . import agent_loop as AL          # 局部导入：`agent_loop` 顶层 import 本模块
        from . import schema as S

        mine = str(my_task_id or "") or current_task_id()
        pid = str(parent_task_id or "") or current_parent()[0]
        prole = str(parent_role or "") or current_parent()[1]
        who = str(by or "") or current_caller_role()
        base: dict[str, Any] = {"checked": True, "ok": False, "state": "refused",
                                "to": "", "to_task_id": "", "need": "", "kind": "",
                                "evidence": [], "msg_id": "", "reason": "", "error": "",
                                "note": ""}

        def _refuse(reason: str, why: str) -> dict[str, Any]:
            out = dict(base)
            out.update({"reason": reason, "error": why})
            self._log(f"上行被拒（{reason}）：{why}", task_id=mine)
            return out

        text = str(need or "").strip()
        if not text:
            return _refuse("invalid_params", "need 不能为空：一句话说清要父代理做什么")
        if len(text) > 300:
            return _refuse("invalid_params", f"need 有 {len(text)} 字，超过 300 字的上限："
                                             "说不清就说明还没想清要父代理做什么")
        kind_name = str(kind or "").strip()
        if kind_name not in ESCALATE_KINDS:
            return _refuse("invalid_params",
                           f"kind={kind_name!r} 不在受控取值里（{list(ESCALATE_KINDS)}）")
        ev = [str(x).strip() for x in (evidence or ()) if str(x).strip()][:20]

        # ---- 父 = 运行期解析出的召唤者。没有父 / 父就是我自己 ⇒ 受控拒绝（顶层 M 走这一支）
        if not pid or (mine and pid == mine):
            return _refuse(
                "not_caller",
                "这一趟没有召唤者（顶层发起，或父那一行就是我自己）⇒ 没有可上报的对象。"
                "顶层 M 该用 `ask_user` 问人、或直接把判断写进收尾，而不是「上报给父」")

        # ---- 收件人的角色：台账那一行是权威（父可能不是 M），运行期解析出的角色是退路
        role, row_note = "", ""
        try:
            row = self._task(pid) or {}
            role = str(row.get("role") or row.get("called_by") or "")
        except Exception as exc:  # noqa: BLE001 —— 读不成要如实说，不许当成"没有父"
            row_note = f"父那一行（{pid}）没读成（{type(exc).__name__}: {exc}）"
        if not role:
            role = prole
            row_note = row_note or f"父那一行（{pid}）没有 role"
        if not role:
            return _refuse("parent_unknown",
                           f"父的编号是 {pid!r}，但它的角色读不出来（{row_note}）⇒ 不猜一个收件人")

        root = str(session_root or "") or current_session()[0]
        csid = str(sid or "") or current_session()[1]
        if not root:
            return _refuse("no_session",
                           "没有会话根（root）⇒ 收件箱落在哪个会话都不确定："
                           "按缺省会话写等于把这条上报丢进一个父不会读的文件")

        # ---- 名册校验（业主 2026-10-19：上行与 `message` 同一条判据）。
        # 收件人是"运行期解析出的父"，但路径上必须真的过一遍名册：
        # `not_in_roster`（给了不是父的编号）/ `member_retired` / `not_upward`（给了子）
        # 一律受控拒绝、一行都不写；`roster_unavailable` 不是这一条上行的拒绝（见下一段）。
        addr = self._escalation_roster_check(mine=mine, to=pid, who=who, root=root)
        refused = str(addr.get("refused") or "")
        if refused == "roster_unavailable":
            # 2026-10-22（fail-closed 的边界）：私聊在名册不可用时一律受控拒绝，上行不跟着停 ——
            # 收件人在结构上就是运行期解析出来的父（`pid`），名册这一趟没读成不改变"发给谁"；
            # 而父子是唯一的结构性通道，停掉它等于把整条链掐死（业主口径：这一条保留）。
            # 读数照旧标出来：`roster_unavailable` 那一格与 `addressing.roster_probe`。
            refused = ""
        if refused:
            bad = _refuse(refused, f"上行收件人不在名册上（{addr.get('error') or refused}）"
                                   "⇒ 这一条一行都没写")
            bad["addressing"] = addr
            return bad
        if str(addr.get("how") or "") == "child":
            bad = _refuse("not_upward",
                          "上行只能发给父：这个编号在你的名册上是**子**"
                          "（`escalate` 是向上，不是向下）⇒ 这一条一行都没写")
            bad["addressing"] = addr
            return bad

        subject = f"{ESCALATE_SUBJECT}（{kind_name}）：{text[:40]}"
        body_lines = [
            f"来自：{who or '（未知角色）'}（台账号 {mine or '未拿到'}）",
            f"要父代理做什么：{text}",
            f"类别：{kind_name}",
            f"相关台账：{'、'.join(ev) if ev else '（没有点名的台账 id）'}",
            "这一趟已停在交出判断的那一步之后（stop_reason=escalated）——"
            "它不会自己往下做，等你处理完再续。",
            "读一次即视为已处理（收件箱的『已读』标记由 `mark_delivered` 登记）。",
        ]
        if row_note:
            body_lines.append(f"读数：{row_note} ⇒ 收件人按运行期解析出的角色写（{role}）")
        msg_id, problem = AL.send_message(
            Path(root), sender=who or S.CONDUCTOR_ROLE, to=role, subject=subject,
            body="\n".join(body_lines), sid=(csid or None), from_task_id=mine,
            extra={"escalation": {"need": text, "kind": kind_name, "evidence": ev,
                                  "from_task_id": mine, "to_task_id": pid}},
        )
        if problem or not msg_id:
            return _refuse("inbox_write_failed",
                           f"留言没写成（{problem or '没有 msg_id'}）⇒ 这不算已上报")
        # 可审计的那一条（与 `definition_ask` 同族：`message_id` 指向真的那行留言）
        try:
            from . import sessions as _SS

            _SS.append(Path(root), {"kind": "agent_escalation", "role": who or "",
                                    "from_task_id": mine, "to_role": role,
                                    "to_task_id": pid, "msg_id": msg_id,
                                    "need": text, "escalate_kind": kind_name,
                                    "evidence": ev, "stamp": hashlib.sha1(
                                        f"{mine}:{msg_id}".encode()).hexdigest()[:8]},
                       sid=(csid or None))
        except Exception as exc:  # noqa: BLE001 —— 留痕失败不许把"已经写进收件箱"改口
            problem = f"{type(exc).__name__}: {exc}"
        out = dict(base)
        out.update({"ok": True, "state": "escalated", "to": role, "to_task_id": pid,
                    "need": text, "kind": kind_name, "evidence": ev, "msg_id": msg_id,
                    "reason": "", "error": "",
                    # 成功那一档只讲"这条上行落进了谁的收件箱"；名册探针的 refused / error
                    # 挪进 `roster_probe`（缺陷 1 的同一条纪律：成功的一步里不许留着"被拒"）。
                    "addressing": AL.delivery_addressing({}, addr),
                    "roster_unavailable": str(addr.get("how") or "") == "roster_unavailable",
                    "note": (f"已写进 {role} 的收件箱（msg_id={msg_id}）⇒ 这一趟以 "
                             "stop_reason=escalated 收工，等父处理"
                             + (f"；留痕没写成（{problem}）" if problem else ""))})
        self._log(f"上行：{who or '?'} → {role}（{kind_name}）：{text[:60]}", task_id=mine)
        return out

    # ---------------------------------------------------------------- 顶趟（F1）
    def open_top_level_run(self, role: str, task: str, *, by: str = "user",
                           input_key: str = "") -> str:
        """给一次顶趟（不是被召唤的那些）开一条 `tasks` 行，返回它的 `task_id`。

        ## 为什么必须有它（F1 / `44 J-32` 的"往前走"半）：真机读数：`usage_ledger` 里 51%~66% 的行 `task_id` 为空，而
        `agent_loop.run_role` 给顶趟传的是 `my_task_id=""` ⇒ `llmseam._charge_ledger` 把空串归一成 `None` ⇒ 那些钱
        读不出"属于哪一次召唤"。只填 `task_id` 而不先建行是负收益（`44 J-32` 逐字）：按 `verify.py` 的
        `dangling_usage_task`，每一行都会变成一条 error 级读数 ⇒ 一次改动制造几千行 error。所以这两件事必须同批：先
        建行（本方法），再让这一趟的每一次 `seam.ask` 带上它。历史不回填：盘上存量那些 null 行是历史事件
        （`store.rebuild` 重放同一批），改代码不改写历史；而 `None` 不进 `dangling_usage_task` 的判据（`verify.py` 逐字
        `if tk is not None and str(tk) not in task_by_id:`）⇒ 那是一条已知基线，不是红。这条行不占并发/总量配额
        （`max_concurrency` 约束的是"同时在跑的召唤"，而顶趟是那个正在派活的人本身）；它只是让"这一趟"在台账上有
        一个身份。
        """
        started = S.now_iso()
        key = str(input_key or "").strip() or f"top:{role}:{abs(hash(str(task))) & 0xFFFFFFFF:08x}"
        row = {
            "task_id": "",
            "role": role, "action": "run", "called_by": str(by),
            "parent_task_id": None, "depth": 1, "input_key": key,
            "status": "running", "outcome": None, "refusal_reason": None,
            "instance": "", "detail": str(task or "")[:200], "error": None,
            "started_at": started, "ended_at": None, "tokens": 0, "usd": 0.0,
            "artifacts": [], "inputs": [],
        }
        # 2026-10-18（缺陷 ⑫）：上一趟若被 kill/崩溃，它的 `running` 行会永远停在
        # running ⇒「谁还没收工」「running 有几个」这类读数全部说谎。
        # 真机 `projects/t2s`：`t-000001`（03:01）与 `t-000005`（03:19）是我 kill 掉的两趟
        # 留下的僵尸，而 `t-000006` 才是真正在跑的那一趟 —— 三行同角色同时 running。
        # 同一工作区里同一角色的顶趟是互斥的（一个进程一趟），所以开新行前把同角色
        # 遗留的 running 顶趟标成 `failed`（带原因）是安全的：它们的进程已经不在。
        self._sweep_stale_top_running(role)
        tid = self._write_new_row(row, note=f"top:{role}")
        # 顶趟的绝对编号记下来：框架自己发起的派活（队列认领）拿它当父（见 `_top_task_id`）。
        self._top_task_id = tid
        self._log(f"顶趟开行 {role} → {tid}", task_id=tid)
        return tid

    def _sweep_stale_top_running(self, role: str) -> int:
        """把同一角色遗留的 `running` 顶趟行标成 `failed`（缺陷 ⑫）。

        返回清掉的行数（读数用）。只碰 `called_by == 主控` 的顶趟行：子代理的行由
        它们自己的收尾逻辑负责，这里不动，免得把"同时在跑的子任务"误判成僵尸。
        """
        n = 0
        self._refuse_write_in_snapshot("清扫遗留顶趟（_sweep_stale_top_running）")
        with self.store.tx("tasks", actor=S.CONDUCTOR_ROLE, note="sweep-stale-top-running") as tx:
            for r in tx.rows("tasks"):
                # 2026-10-18（⑫ 的补丁，真机 `projects/t3a` 抓到）：顶趟行的 `called_by`
                # 是 用户（`by=user`），不是我原先筛的「主控」⇒ 旧条件永远匹配不到，
                # 于是 `running` 里能同时躺着三个 M（两次 kill + 一次 resume）。
                # 改成按拓扑判顶趟：没有 parent 的那一行就是顶趟（子代理行都不动）。
                if (str(r.get("role")) != role
                        or str(r.get("status")) != "running"
                        or r.get("parent_task_id")):
                    continue
                r["status"] = "failed"
                r["outcome"] = "failed"   # schema：status=failed ⇒ outcome 必须是 failed
                r["ended_at"] = S.now_iso()
                r["error"] = ("上一个进程已不在（被 kill 或崩溃），开新顶趟时清理 —— "
                              "这不是这一次的失败")
                tx.upsert("tasks", r)
                n += 1
        if n:
            self._log(f"清理僵尸顶趟 {role} × {n}")
        return n

    #: `consume_pending_search_requests` 的两处消费计数（"派活时 N 条 / 收尾时 M 条"）。
    #: 它是读数：让 (乙) 形态对"即"字的折扣可度量（主控批 (乙) 的条件之一）。
    _consume_counts: dict[str, int]

    #: 队列认领那一路的名册登记问题（非空 ⇒ 有名册外子代理的候选，读侧可查）。
    _consume_roster_problems: list[str]

    #: 最近一次 `open_top_level_run` 拿到的绝对编号（台账发的，不是这里拼的）。
    #:
    #: 为什么需要它（2026-10-20，真机 `projects/tree-check` 的 t-000019）：框架自己
    #: 发起的那几条派活（队列认领 `consume_pending_search_requests`）不属于任何
    #: 代理调用的调用栈，于是 `summon` 的 `parent_task_id` 走到了默认值 `None`
    #: ⇒ 台账里出现一行 `role=A / called_by=M / parent_task_id=None / depth=1` 的孤儿：
    #: 它不在任何名册里（`roster_view(owner=任一父)` 都读不到它），也不占任何父的扇出。
    #: 口径（`draft/90` §1.1 / `draft/104` §2.5「父子关系的唯一权威来源是台账」）：
    #: 子行的父亲必须是父的绝对编号；顶层（M 自己那一趟）就用顶趟编号，
    #: 只有顶趟那一行才允许 `parent=None`（它是树根）。
    _top_task_id: str = ""

    def _owner_task_id(self, given: str = "") -> str:
        """这一笔派活的父的绝对编号（空串 = 连顶趟都没有 ⇒ 调用方要自己造一个树根）。

        三个来源，按权威性排序（都是台账/上下文里已有的值，没有一处是自己拼的）：
        ① 调用方显式给的（`finish_top_level_run` 给它自己那一行）；② `consuming_as`
           挂上的 owner 提示（`_do_summon_many` 那一支）与当前调用上下文
           （`calling_as` 挂的 `task_id`，工具路径走这一格）；③ 本进程最近一次顶趟
           （`open_top_level_run` 记下的）。
        """
        for cand in (given, _CURRENT_OWNER_HINT.get(), current_task_id(),
                     getattr(self, "_top_task_id", "")):
            if str(cand or "").strip():
                return str(cand)
        return ""

    def consume_pending_search_requests(self, *, by: str = S.CONDUCTOR_ROLE,
                                        limit: int = 1, trigger: str = "dispatch",
                                        parent_task_id: str = "") -> list[Any]:
        """S-03（队列认领 · 乙形态）：把还没做完的检索请求交给 A 的 `run_once`。

        ## "即"字的折扣（写在明面上，不许藏）：这里的"提交即被消费"读作"下一次 M 侧派活（`run_plan`）或 M 收尾时被
        消费"。若 M 之后不再动，请求会留着 pending —— 让它可见的两条链：
        1. F-05 的消费端（`secretary.pending_inbox` / `inbox_todos`，秘书职责 3 会提醒 M）；
        2. `closing` 的研究链缺口读数（E-04b 那一档）。
        所以"不可见地挂着"这个最坏形态不成立。为什么不是"提交那一刻"就消费（`44 J-07` 之外的设计题）：那要给 C/D
        塞 `conductor` ⇒ 变成处理体内的递归召唤（深度/预算/并发语义现在都按"M 是唯一派活方"设计），还要动 `host.py`
        （FC-27）。让"提交那一刻"就消费的正确做法是改派活权的归属，那是另一个设计题、要人裁。
        ## 幂等（"无意义/重复的委托"那一类）：同一条 `request_id` 只唤起一次：判据是 `tasks` 里已经有
        `input_key == "consume:<rid>"` 的行（含 running —— 已经消费过就别再来一次）。`input_key` 同时是幂等键的可见
        形态，测试与审计都按它查。而"被拒过"不算"做过"（D80，2026-10-08）：幂等只在真的被受理过的行上成立。闸门拒掉
        的召唤也落一行台账（`_refuse`），而那一行带着 `input_key` —— 改前 `seen` 收全部行，于是一趟在墙钟/预算/总量
        到顶那一刻扫队的跑批，只要有一条 `consume:<rid>` 被拒一次，那条 `done=false` 的检索请求就永久留在 `seen` 里、
        从此再也不会被认领（跨趟也一样：`tasks` 是追加式台账，`seen` 每次都从全表重建）。判据与
        `_occupies_fanout_slot` 同源：只有走完第 [5] 步（写 `running` 行）的召唤才带 `_ADMITTED_MARK`。
        ## 父是谁（2026-10-20；根因见 `_top_task_id` 的注释）：认领出来的那个 `A` 也是派活，所以它必须有父
        （`draft/90` §1.1：名册项 = 子代理，`tasks` 行 = 一次调用；`draft/104` §2.5：父子关系的唯一权威来源是台账）。
        父按 `_owner_task_id` 取，优先级：显式 `parent_task_id` → 当前调用上下文 → 本进程顶趟。三者都没有（例如判据里
        裸造了一个 `Conductor`、连顶趟都没开）⇒ 当场造一个真树根（`_write_new_row`，编号由台账发，`parent=None` 是
        树根的合法形态）并把它收行 —— 宁可多一行树根，也不许再出现 `parent_task_id=None` 的子行（真机 t-000019 就是
        那一行孤儿）。认领完顺手登记进那个 owner 的名册（名字与读写面都由秘书发号 —— 这一条正是"名册外子代理"那个
        洞：改前 `conductor.summon` 直连后端，一次登记都没有）。
        """
        out: list[Any] = []
        owner = ""
        opened_root = ""
        roster_problems: list[str] = []
        try:
            rows = list(self.store.rows("search_requests"))
        except Exception as exc:  # noqa: BLE001 - 扫不到队就如实留痕（不当成"队是空的"）
            self._log(f"扫队失败（{trigger}）：{type(exc).__name__}: {exc}")
            return out
        # 只把"真的被受理过"的行算进幂等键（D80）：见上面那一段。
        # 复用同一个谓词而不是就地写 `outcome != "refused"` —— "跑过又拒"与
        # "闸门拒掉、根本没跑"的分野只有一处实现（`_occupies_fanout_slot`）。
        seen = {str(r.get("input_key") or "") for r in self._tasks()
                if _occupies_fanout_slot(r)}
        for row in rows:
            if row.get("done"):
                continue
            rid = str(row.get("request_id") or "")
            if not rid:
                continue
            key = f"consume:{rid}"
            if key in seen:
                continue                      # 幂等：这一条已经消费过（含正在跑的那一次）
            if not owner:
                # 父的绝对编号（见本方法 docstring 最后一段）。真的连顶趟都没有 ⇒
                # 造一个树根：`parent=None` 只在树根上是合法的。
                owner = self._owner_task_id(parent_task_id)
                if not owner:
                    owner = self._open_consume_root(trigger)
                    opened_root = owner
            try:
                res = self.summon("A", "run_once", {}, by=by, input_key=key,
                                  parent_task_id=owner,
                                  # 名册登记要用的那句任务原文（简介由秘书据它代写并留痕）：
                                  # 登记本身发生在 `summon` 的 [5b]，这里只把材料交过去。
                                  roster={"task": f"认领检索请求 {rid}"})
            except Exception as exc:  # noqa: BLE001 - 一条消费失败不许拖住其余
                self._log(f"队列认领失败（{trigger}，{rid}）：{type(exc).__name__}: {exc}")
                continue
            out.append(res)
            seen.add(key)
            self._register_consumed(owner, res, rid=rid, problems=roster_problems)
            if len(out) >= max(1, int(limit)):
                break
        if opened_root:
            self._close_consumed_root(opened_root, trigger=trigger)
        if out:
            counts = getattr(self, "_consume_counts", None)
            if counts is None:
                counts = {}
                self._consume_counts = counts
            counts[str(trigger)] = counts.get(str(trigger), 0) + len(out)
            self._log(f"队列认领（{trigger}）：消费 {len(out)} 条",
                      task_ids=[str(getattr(r, "task_id", "")) for r in out])
        if roster_problems:
            self._consume_roster_problems = roster_problems
            self._log(f"队列认领的名册登记有 {len(roster_problems)} 处没写进去："
                      f"{roster_problems[0]}")
        return out

    def _open_consume_root(self, trigger: str) -> str:
        """给"没有任何父在场"的队列认领造一个真树根行（编号由台账发）。

        为什么不用 `open_top_level_run`：它会顺手把同角色遗留的 running 顶趟标成
        `failed`（`_sweep_stale_top_running`）。队列认领跑在 M 那一趟的内部，
        用 M 这个角色去开行会把正在跑的那一趟 M 标死 —— 那是比孤儿更坏的错。
        所以这里直接走 `_write_new_row`（与 `summon` 同一个建行临界区），
        角色记框架（`M`）、`called_by="conductor"`（不是冒充某个角色发起的）。
        """
        tid = self._write_new_row({
            "task_id": "", "role": S.CONDUCTOR_ROLE, "action": "run",
            "called_by": "conductor", "parent_task_id": None, "depth": 1,
            "input_key": f"top:{S.CONDUCTOR_ROLE}:consume:{trigger}",
            "status": "running", "outcome": None, "refusal_reason": None,
            "instance": "", "detail": f"队列认领（{trigger}）：框架自发起的一趟（树根）",
            "error": None, "started_at": S.now_iso(), "ended_at": None,
            "tokens": 0, "usd": 0.0, "artifacts": [], "inputs": [],
        }, note=f"top:{S.CONDUCTOR_ROLE}:consume")
        self._log(f"队列认领（{trigger}）没有父在场 ⇒ 开一条树根 {tid}", task_id=tid)
        return tid

    def _close_consumed_root(self, tid: str, *, trigger: str) -> None:
        """收掉 `_open_consume_root` 那一行（不许在台账上留一条永远 running 的树根）。"""
        try:
            self._end(tid, status="done", outcome="no_result",
                      detail=f"队列认领（{trigger}）的树根行：认领已完成")
        except Exception as exc:  # noqa: BLE001 - 收行失败只留日志（认领本身已经发生）
            self._log(f"队列认领的树根行没收成（{tid}）：{type(exc).__name__}: {exc}")

    def _register_consumed(self, owner: str, res: Any, *, rid: str,
                           problems: list[str]) -> None:
        """把认领那一路的名册读数收进 `problems`。登记本身不在这里（唯一漏斗是
        `Conductor.summon` 的 [5b] 一步，见 :meth:`_register_roster`）。

        为什么这个方法还留着：认领是唯一一条"框架自己发起、调用方不看返回值"的派活
        （`finish_top_level_run` / `run_plan` 顺手扫队），它的名册问题没有别的地方能读到。
        改前它在自己这一处调 `roster_add` —— 那是第三个登记点，与漏斗同源时会让同一个
        子代理有两条同名项；收口的做法是"只读数、不写字"。

        三态照旧：没登记上就留一条问题（不许静默）；登记上了 `roster_problem` 是空串。
        谁没登记上、为什么，原文在 `roster_problem` 里（漏斗已经写全了 owner/原因）。
        """
        problem = str(getattr(res, "roster_problem", "") or "")
        if problem:
            problems.append(f"{rid}：{problem}")

    def finish_top_level_run(self, task_id: str, *, stop_reason: str,
                             detail: str = "",
                             cut_off_children: Sequence[str] = ()) -> SummonResult:
        """收一次顶趟（与 :meth:`open_top_level_run` 配对）。

        三态（2026-11-02 改成三档，83 的真机读数）：

        | 档 | 判据 | `(status, outcome)` | `detail` 开头 |
        |---|---|---|---|
        | 收工成功 | `stop_reason == "final"` | `done / ok` | `顶趟收工：final` |
        | 收工被叫停 | `stop_reason ∈ stopctl.USER_STOP_REASONS` | `done / cancelled` | `顶趟收工被叫停：<reason>` |
        | 收工没做成 | 其余 | `done / no_result` | `收工没做成：<reason>` |

        为什么必须分三档（改前后两档折在一个 `no_result` 里 —— 这是第三次三态折平，
        前两次是 na/unknown 与判不了/没查成）：83 那一趟是 `stop_file`（人按的停），
        而"它自己没做成"（撞步数、判停、协议连击）也是 `no_result` —— 于是"谁按的停"
        与"它自己不行"在台账上长得一模一样，读的人只能去翻 `stop-history.jsonl`。
        `failed` 仍不在这里出现：那是"代码崩了"，顶趟行的 `failed` 只有
        `_sweep_stale_top_running` 那一档（进程已经不在）。

        ## 花销必须从账本抄回这一行（否则制造一条 `usage_task_total_mismatch`）：这一趟的账挂在这一行的 `task_id` 上
        （F1 的另一半），所以 `tasks.tokens/usd` 必须由账本派生（与 `_charge_and_settle` 同一条纪律：`tokens_for()`
        抄回，而不是自己累加）。实测过缺这一步的后果：库里 `tasks.tokens=0` 而账本 150 ⇒ `verify_all` 报一条 warning
        `usage_task_total_mismatch`（"两处对同一次召唤的花销给出不同数字"）—— 判据见
        `tests/test_agent_loop.py::test_f1_...`。
        """
        tokens_of_top = 0
        usd_of_top = 0.0
        try:
            tokens_of_top = int(self.meter.tokens_for(task_id))
            usd_of_top = float(self.meter.usd_for(task_id))
        except Exception as exc:  # noqa: BLE001 - 抄不回来就留日志（不阻断收行）
            self._log(f"顶趟花销没抄回来（{task_id}）：{type(exc).__name__}: {exc}")
        reason = str(stop_reason or "")
        done = reason == "final"
        # ---- 三档映射（唯一判据在这里，见 docstring 那张表）
        from . import stopctl as _STOP        # 惰性：不让 conductor 在导入期依赖停机模块
        if done:
            status, outcome, head = "done", "ok", f"顶趟收工：{reason}"
        elif reason in _STOP.USER_STOP_REASONS:
            status, outcome, head = "done", "cancelled", f"顶趟收工被叫停：{reason}"
        else:
            status, outcome, head = "done", "no_result", f"收工没做成：{reason}"
        # S-03 的第二个消费点（主控补的）：收尾前扫一次队 —— 只挂"下一次派活"的话，
        # 最需要它的时候（这一趟就要结束了）反而不会消费。计数分 trigger 记，
        # 于是"即"的折扣在读数上可度量（"派活时 N 条 / 收尾时 M 条"）。
        try:
            # 父 = 这一趟自己的绝对编号（2026-10-20：改前这里不给 ⇒ 认领出来的 A 行
            # `parent_task_id=None`，成了名册外的孤儿 t-000019）。
            # R9FIX-D3：认领内部会再调 `summon("A", …)`；置上防递归标记，否则
            # `summon` 那一层的扫队又会在收尾点里再扫一轮。
            self._queue_sweeping = True
            try:
                self.consume_pending_search_requests(trigger="finish", parent_task_id=task_id)
            finally:
                self._queue_sweeping = False
        except Exception as exc:  # noqa: BLE001 - 扫队失败不许带走收行
            self._log(f"收尾扫队失败：{type(exc).__name__}: {exc}")
        # 秘书职责 3（闭环提醒）的生产调用点（`draft/53` §2；主控 2026-10-04 裁定"接上"）：
        # 与上面那处收尾消费同址 —— 理由见 `remind_closure_at_finish` 的 docstring。
        closure = self.remind_closure_at_finish()
        # ---- D22：父行必须点名"我退出时掐断了哪几个还在跑的子"
        #
        # 为什么这一句组装在这里（而不是 `agent_loop` 那侧拼好再传进来）：父行只有这一处
        # 组装 `detail`。改前 `final_refused` 那一趟的 `run.final` 是空的（D-68 的
        # "不记 final"），于是父行只剩"顶趟收工：final_refused；闭环提醒 …" —— 5 个被掐断的
        # 子与正常交付的子在同一张台账上长得一模一样。调用方只传"原料"（编号列表），
        # 措辞与计数都在这一处。
        killed = [str(x) for x in (cut_off_children or ()) if str(x)]
        killed_text = (f"；我退出时掐断了 {len(killed)} 个还在跑的子：{'、'.join(killed)}"
                       if killed else "")
        result = self._end(task_id, status=status, outcome=outcome,
                           detail=(head
                                   + (f"；{detail[:200]}" if detail else "")
                                   + killed_text
                                   + _closure_suffix(closure)),
                           tokens=tokens_of_top, usd=usd_of_top)
        # ---- E5 第二半（2026-11-03）：顶趟收工成功那一步落一次趟次索引。
        #
        # 「收工成功」= `stop_reason == "final"`（与上面 `done` 同一判据）；不完整那一档
        # 不建、也不覆盖已有索引 —— 半截运行建出来的索引会让页面把"没跑完"读成
        # "已经对过账"。失败不静默：`checked=False` 的原因进日志（审计在
        # `run_index_rebuild` 里另落一行）。
        if done:
            reading = run_index_rebuild(getattr(self.store, "root", "."),
                                        by=f"顶趟收工（{task_id}）")
            if not reading["checked"]:
                self._log(f"趟次索引没建成：{reading['reason']}", task_id=task_id)
        return result

    #: 职责 3（闭环提醒）最近一次的收尾读数（`stats()` 与测试读它）。
    _closure_reading: dict[str, Any]

    def remind_closure_at_finish(self) -> dict[str, Any]:
        """秘书职责 3（闭环提醒）的生产调用点：收尾时问一次"谁没接手 / 谁没反馈"。

        ## 为什么接在这里，而不是 `agent_loop` 每趟的收尾：
        1. 职责 3 的形态是「经 M」（`draft/53` §2）：它问的是链条级的事实 —— "提交了却没人接手"、"有人接手却没有终态"
           —— 而顶趟收尾是唯一能看见整条链的收尾点；`agent_loop` 那一层只看得到本角色这一趟。
        2. 与 S-03 的收尾消费点同址（上面那一次 `consume_pending_search_requests(trigger="finish")`）：一个收尾点只做
           一轮扫描，"认领"与"提醒"落在一起。
        3. "这一趟的读数"有现成的落点：顶趟行的 `detail`（一句话摘要）与 :meth:`stats` 的 `closure_reminders`（全量），
           每条提醒另进决定台账（`secretary.remind_closure` 逐条落 duty=3）。
        ## 三态与 fail-open（与其余四职责同姿态）：没装配秘书 ⇒ `checked=False` + 理由："没查成"不是"没有未闭环"；
        秘书自己抛异常 ⇒ 记 `fail_open=True` 并照常收尾 —— 提醒绝不许打断收尾；读成了、确实没有未闭环 ⇒
        `checked=True, count=0, reminded=[]`（反负控：这一格不许凭空列人）。
        ## 两栏（业主 2026-10-26 Q18）
        读数带 `running_agents` / `pending_items` 两格（各自 `count` + `ids`）：判据只有
        `secretary.row_axis` / `secretary.is_live_agent` 一处，这里只搬数与点名，不再判一次
        "算不算在跑的子代理"。
        `by_state` 只统计待办项（`unclaimed` = 提交了没人接手；`pending` = 有人接手但没有终态）——
        在跑的子代理是另一栏，把它混进同一张分组表，就是改前那句"running 5 条"的来源。
        """
        sec = getattr(self, "secretary", None)
        reader = getattr(sec, "closure_reading", None) if sec is not None else None
        if callable(reader):
            try:
                got = dict(reader() or {})
                reading: dict[str, Any] = {
                    "checked": bool(got.get("checked")),
                    "reason": str(got.get("reason") or ""),
                    "count": int(got.get("count") or 0),
                    "running_agents": dict(got.get("running_agents") or {}),
                    "pending_items": dict(got.get("pending_items") or {}),
                    "reminded": [dict(x) for x in (got.get("reminded") or ())],
                    "by_state": dict(got.get("by_state") or {}),
                    "by_to": dict(got.get("by_to") or {}),
                    "truncated": dict(got.get("truncated") or {}),
                    "two_column": True,
                    "note": ("只报事实（谁没接手 / 谁没有终态）与条数，两栏各自给截断前的真数；"
                             "不替本体做事、不伪造反馈；要不要真叫由调用方按 "
                             "`should_engage` 走。")}
                if got.get("fail_open"):
                    reading["fail_open"] = True
            except Exception as exc:  # noqa: BLE001 - 秘书坏了不许打断收尾（fail-open）
                self._log(f"秘书的闭环提醒没跑成（照常收尾）：{type(exc).__name__}: {exc}")
                reading = {
                    "checked": False, "fail_open": True,
                    "reason": f"秘书的闭环提醒没跑成：{type(exc).__name__}: {exc}",
                    "count": 0, "reminded": [], "by_state": {}, "by_to": {},
                    "running_agents": {"count": 0, "ids": []},
                    "pending_items": {"count": 0, "ids": []},
                    "two_column": False}
        elif sec is None or not callable(getattr(sec, "remind_closure", None)):
            reading = {
                "checked": False, "reason": "没有装配秘书 ⇒ 这一格没查成",
                "count": 0, "reminded": [], "by_state": {}, "by_to": {},
                "running_agents": {"count": 0, "ids": []},
                "pending_items": {"count": 0, "ids": []},
                "two_column": False}
        else:
            try:
                reminded = [dict(x) for x in (sec.remind_closure() or [])]
                # 老形态（只认 `remind_closure` 的秘书）没有两栏真数：按提醒自带的轴分，
                # 没带轴的一律算待办项。轴名从秘书那一处取，别在这里另立一份名字。
                from . import secretary as _SEC

                agent_axis = str(getattr(_SEC, "ROW_AXIS_AGENT", ""))
                agents = [x for x in reminded
                          if agent_axis and str(x.get("axis") or "") == agent_axis]
                pend = [x for x in reminded if x not in agents]
                by_state: dict[str, int] = {}
                by_to: dict[str, int] = {}
                for item in pend:
                    state = str(item.get("state") or "unknown")
                    by_state[state] = by_state.get(state, 0) + 1
                for item in reminded:
                    to = str(item.get("to") or S.CONDUCTOR_ROLE)
                    by_to[to] = by_to.get(to, 0) + 1
                reading = {
                    "checked": True, "reason": "", "count": len(reminded),
                    "reminded": reminded, "by_state": by_state, "by_to": by_to,
                    "running_agents": {"count": len(agents),
                                       "ids": [str(x.get("task_id") or "") for x in agents]},
                    "pending_items": {"count": len(pend),
                                      "ids": [str(x.get("task_id") or "") for x in pend]},
                    "two_column": False,
                    "note": ("只报事实（谁没接手 / 谁没有终态）与条数；这一份来自只认 "
                             "`remind_closure` 的秘书（没有截断前的两栏真数），"
                             "条数按提醒列表算。")}
            except Exception as exc:  # noqa: BLE001 - 秘书坏了不许打断收尾（fail-open）
                self._log(f"秘书的闭环提醒没跑成（照常收尾）：{type(exc).__name__}: {exc}")
                reading = {
                    "checked": False, "fail_open": True,
                    "reason": f"秘书的闭环提醒没跑成：{type(exc).__name__}: {exc}",
                    "count": 0, "reminded": [], "by_state": {}, "by_to": {},
                    "running_agents": {"count": 0, "ids": []},
                    "pending_items": {"count": 0, "ids": []},
                    "two_column": False}
        self._closure_reading = reading
        return reading

    # ---------------------------------------------------------------- 委托质量（A 线）
    def duplicate_candidates(self, role: str, action: str, input_key: str) -> list[dict]:
        """同 `(role, action, input_key)` 的既有终态行（只读；不阻断派活）。

        `draft/53` §10 的口径：派活去重归发件方秘书（职责 2 的"该不该派"含
        "是不是重复"），机器只把同 key 的既有终态行摆出来。为什么机器不硬拦：

        - "同 key"不是"同一件事"的充分条件（正当重试、参数微调后的重派都同 key），
          硬拦会把合法重试也拦掉 —— 那正是 #1 的另一半（把该做的活拦住）；
        - 而"摆出来"是确定性的、可复核的：调用方与秘书看到的是同一份读数。

        `input_key` 为空 ⇒ 空列表（没有键就没有"同 key"，不许把"没给键"读成"重复"）。
        """
        want = str(input_key or "").strip()
        if not want:
            return []
        out: list[dict] = []
        for row in self._tasks():
            if str(row.get("role") or "") != str(role):
                continue
            if str(row.get("action") or "") != str(action):
                continue
            if str(row.get("input_key") or "") != want:
                continue
            if str(row.get("status") or "") not in TERMINAL_STATUSES:
                continue
            out.append(dict(row))
        return out

    def budget_note(self, *, scope: str = "summon") -> dict[str, Any]:
        """预算读数（F2 的"只记录"半）：记录得到，但判决不因此改变。

        真机基线（`draft/44` 的 E-02）：`tasks.tokens` 4127 行只有 15 行非零、
        `usage_ledger` 51% 的行 `task_id=null` —— "没有代价可读"与"花得少"分不开。

        这一格刻意不参与任何判决：预算判据只有一处（`_meter_guard` → `guard()`），
        这里只是把同一份读数取出来（`recorded_only=True` 是它的自证标记）——
        多一处判决会让"一处说还能花、另一处说不能"漂移。
        """
        try:
            spent = self.meter.spent()
        except Exception as exc:  # noqa: BLE001 - 读数拿不到如实报，不折成 0
            return {"recorded_only": True, "scope": str(scope), "checked": False,
                    "reason": f"预算读数没取到：{type(exc).__name__}: {exc}"}
        state = dict(P.budget_state(self.policy, spent_tokens=int(spent.get("tokens") or 0),
                                    spent_usd=float(spent.get("usd") or 0.0)))
        state["recorded_only"] = True
        state["checked"] = True
        state["scope"] = str(scope)
        state["over_budget"] = bool(
            (state.get("usd_left") is not None and state["usd_left"] <= 0)
        )
        return state

    def _note_delegation_quality(self, role: str, action: str, params: Mapping[str, Any], *,
                                 input_key: str, by: str) -> None:
        """派活前：摆同 key 既有终态行 + 让秘书给一份委派评估（全 fail-open）。"""
        try:
            dups = self.duplicate_candidates(role, action, input_key)
            self._last_duplicates = dups
            if dups:
                self._log(
                    f"{by} 要派 {role}.{action}，而同一 input_key 已有 {len(dups)} 条终态行"
                    "（机器只摆出来、不阻断；是不是重复由发件方秘书判断）",
                    input_key=str(input_key),
                    existing=[str(r.get("task_id") or "") for r in dups[:5]],
                )
            note = self.budget_note()
            self._log("预算读数（只记录，不阻断）", **{k: note.get(k) for k in
                                                    ("usd_left", "over_budget", "spent_tokens")})
        except Exception as exc:  # noqa: BLE001 - 留痕/读数坏了不许带走派活
            self._log(f"派活前的质量读数没取到（照常派活）：{type(exc).__name__}: {exc}")
            self._last_duplicates = []
            return
        if self.secretary is None:
            return
        try:
            self.secretary.assess_delegation(to=role, action=action, params=dict(params or {}),
                                             input_key=str(input_key), duplicates=dups)
        except Exception as exc:  # noqa: BLE001 - 秘书自己出错 ⇒ fail-open + 留痕
            self._log(f"秘书的委派评估没跑成（照常派活）：{type(exc).__name__}: {exc}")

    # ---------------------------------------------------------------- 拒绝
    def _refuse(
        self,
        role: str,
        action: str,
        *,
        reason: str,
        detail: str,
        by: str,
        parent_task_id: str | None,
        input_key: str,
        params: Mapping[str, Any],
        depth: int,
        instance: str = "",
    ) -> SummonResult:
        """写一条"拒绝"的台账行并返回。拒绝也落台账（否则无可审计）。

        `status="done"` 是刻意的：拒绝是一次成功的执行 —— 框架正确地说了"不"。
        把它写成 `failed` 会让"策略拦住了"与"代码崩了"需要不同处置的这两件事
        长得一样（`schema.Task.validate` 会把 `outcome=refused` 且 `status!=done`
        直接判为非法，所以这里也没有第二种写法）。
        """
        started = S.now_iso()
        row = {
            # `task_id` 放第一个键：快照按 dict 的键顺序序列化，而 `rebuild()`
            # 用 `Task.to_dict()`（dataclass 字段顺序）重建 —— 顺序不一致会让
            # `tasks.json` 在 rebuild 后逐字节不同（I-9）。见 `_write_new_row`。
            "task_id": "",
            "role": role if role in (*S.ROLES, S.CONDUCTOR_ROLE) else S.CONDUCTOR_ROLE,
            "action": action or "unknown",
            "called_by": by,
            "parent_task_id": parent_task_id,
            "depth": max(1, depth),
            "input_key": input_key,
            "status": "done",
            "outcome": "refused",
            "refusal_reason": reason,
            # `instance` 的位置必须与 `Task` 的字段顺序一致（见上面 `task_id` 那条注记）：
            # 它在 `refusal_reason` 之后、`detail` 之前。
            "instance": instance,
            "detail": detail,
            "error": None,
            # 拒绝没有真的跑，所以 started_at == ended_at。为什么不留空：
            # `status="done"` 要求 `ended_at` 非空（每个 start 有且仅有一个 end），
            # 而"它一毫秒也没跑"这件事由 detail 里的人话说明，不靠留空表达
            # （留空是非法行，会被 schema 直接拒）。
            "started_at": started,
            "ended_at": started,
            "tokens": 0,
            "usd": 0.0,
            "artifacts": [],
            "inputs": [],
        }
        # 取号与建行同一临界区（见 `_write_new_row` 的缺陷说明）——
        # 被拒的召唤也是并发写台账的（拒绝不需要抢策略的并发配额）。
        tid = self._write_new_row(row, note=f"refused:{reason}")
        self._log(f"拒绝 {by} → {role}.{action}：{reason}", detail=detail)
        # ---- E-03 的机器半（A 线）：拒绝也必须写 `task_end`
        #
        # 真机基线（`44 J-27` 复核过的数）：refused 905 行里 361 行没有 `task_end`
        # 会话事件。后果不是"少一条日志"，而是"留痕"与"被处理"分不开：
        # `_refuse` 走的是"还没有 running 行"的那条路（它自己在 `_write_new_row`
        # 里建行），于是它绕开了 `finish` 里唯一的 `task_end` 落点 ——
        # 读会话的人看到的是"这一趟从来没结束过"，而读台账的人看到的是"它 done/refused"。
        # 三态纪律在这里：`status`/`outcome`/`refusal_reason` 三格都要在叙事里。
        #
        # 闭环（谁去处理这条拒绝）不在这里：那是收件方秘书的职责 3（"留痕" ≠ "被处理"）。
        # 写失败绝不改终态（与 `finish` 同一条纪律），原因进日志。
        from . import sessions as _SESS

        sid, sid_why = _session_for_task_end()
        _path, _problem = _SESS.append(getattr(self.store, "root", "."), {
            "kind": "task_end", "task_id": tid, "by": by, "role": row["role"],
            "action": action or "unknown", "status": "done", "outcome": "refused",
            "refusal_reason": reason, "detail": detail[:200], "artifacts": [],
            # 取不到 sid 时这一行落在缺省会话里 —— 为什么，写在行上（不许静默）。
            **({"sid_problem": sid_why} if sid_why else {}),
        }, sid=(sid or None))
        if sid_why:
            self._log(f"会话记录落在缺省会话（拒绝那一行 {tid}）：{sid_why}", task_id=tid)
        if _problem:
            self._log(f"会话记录没写成（拒绝那一行）：{_problem}", task_id=tid)
        return SummonResult(
            task_id=tid, role=row["role"], action=action, status="done", outcome="refused",
            refusal_reason=reason, detail=detail, depth=row["depth"],  # type: ignore[arg-type]
            # 名册那三格：被拒的那一次不登记（它没跑，没有可登记的子代理）。
            # 为什么 `roster_problem` 留空：拒绝的理由已经在 `refusal_reason` / `detail`
            # 上（那是它的正式落点）；把"一次正常的拒绝"也记成"名册出了一个问题"，
            # 会让收工门那一格（`roster_registration`：数 `roster_problem` 条数）
            # 把策略拒绝读成名册故障。`roster_considered=True` 让人分得开
            # "走过了、结论是不登记"与"根本没走过"。
            roster_considered=True,
        )

    # ---------------------------------------------------------------- 派活前看停机开关（A / B2）
    def _dispatch_stop_gate(self, *, parent_task_id: str | None) -> dict[str, Any]:
        """派活前读一次停机开关：这一趟还该不该产生新的子代理（A / B2，2026-11-15）。

        判据本体在 `stopctl.dispatch_stop_reading`（`read_stop` + `stop_scope` +
        `stop_reason_of`）—— 与步首 `AgentLoop._user_stop_reason` 同一把尺，这里不新造
        第二套。`inside` 用主控自己的 `inside_subtree`：子树开关只停那一支。

        为什么要有这一格：改前 `conductor` 的派活四入口（`summon_begin` /
        `summon_run` / `summon_many` / `start_summon`）对停机开关零命中，于是父在飞的
        那一步里仍能派新孩子，孩子起来后才在自己的第 0 步读到开关 —— 真机读数
        `t-000095`（22:01:10）与 `t-000102`（22:01:35）都在开关落盘（22:00:27）之后
        被创建，各跑 0 步就停，但落 running 行 / 开线程 / 写 run_start / 结算
        usage_ledger 这几笔已经发生。

        反真空（判据 `test_dispatch_refuses_after_the_stop_switch.py`）：把本方法打桩成
        恒 `{"stopped": False}` ⇒ 开关在盘上时派活照常发生 ⇒ 那一条判据必红。
        """
        try:
            from . import stopctl
        except Exception as exc:  # noqa: BLE001 —— 模块都导不进来 ⇒ 这一格没查成
            return {"checked": False, "stopped": False, "state": "unknown_scope",
                    "reason": "", "path": "",
                    "why": f"stopctl 没导进来（{type(exc).__name__}: {exc}）⇒ 没查成"}
        return stopctl.dispatch_stop_reading(
            getattr(self.store, "root", "."),
            parent_task_id=str(parent_task_id or ""),
            inside=getattr(self, "inside_subtree", None))

    def _stop_refusal(self, role: str, action: str, *, by: str,
                      parent_task_id: str | None, gate: Mapping[str, Any]) -> SummonResult:
        """停机开关在 ⇒ 受控拒：不落 running 行、不开线程、不调后端（A / B2）。

        为什么是 `cancelled` 而不是 `refused`：拒绝要带 `schema.REFUSAL_REASONS` 里的
        一个理由码，而那张词表（`schema.py`，禁改区）里没有"停机"这一档；借一个现成
        的码（`budget_exceeded` / `invalid_params`）等于在台账上写一句假原因。取消这条路
        本来就有"未启动、不产生新任务"的既有语义（`token.cancelled` 那一支与它同形），
        理由逐字进 `detail`，调用方读得到"停机开关在，不派新活"这句话。
        """
        path = str(gate.get("path") or ".agentflow-stop")
        reason = str(gate.get("reason") or "stop_file")
        detail = (f"停机开关在（`{path}`，{reason}）：不派新活 —— "
                  f"停机之后不再产生子代理（{by} → {role}.{action} 未启动；"
                  "这不是执行失败，也不是没查成）")
        self._log(f"停机拒派 {by} → {role}.{action}：{detail}", detail=detail)
        return SummonResult(
            task_id=None, role=str(role), action=str(action),
            status="cancelled", outcome="cancelled", detail=detail, elapsed_sec=0.0,
            roster_considered=True,
            roster_problem=(f"未受理（停机开关在：{reason}）⇒ 名册不登记"
                            "（没有子行就没有名册项）"),
        )

    # ---------------------------------------------------------------- 记账（FC-19）
    def _meter_guard(self, role: str, budget: Mapping[str, Any] | None) -> Any:
        """开工前的预算守卫。返回 `tokenmeter.MeterReading`。

        ## 判据只有一处：全局已花 vs 全局预算（2026-10-15 业主裁定 B2/B4）：这里此前是"双重预算"，而且第二重是坏的：
        token 那一半（`budget={"max_tokens": …}`）已随裁定 A1/A2/A3 整条删掉（连同 `Policy.token_budget` 与
        `Decision.tokens_left` 两格）；钱那一半此前写成"给这一单限额"，实现却是 `TokenMeter(store, budget_usd=X).guard()`
        —— 而那个 meter 读的是同一本全局账（`usage_ledger`），于是 `X` 是拿去和全局已花比的。也就是说：`max_usd` 从来
        不是每单限额，它只是"全局阈值的第二个落点"。同一件事两处各判一次，还都不是调用方以为的那个意思 —— 这正是
        B2 的形态。现在收成一处：判的是 `self.meter`（全局账）对 `self.meter.budget_usd`（全局预算，取自
        `Policy.usd_budget`），也就是业主那句「只卡总花销的钱」。`budget={"max_usd": X}` 这个参数仍然受理，但语义改成
        了它在字面上该有的意思："这一单预计最多花 X" ⇒ 判"剩下的钱够不够 X"（`X > 剩余` ⇒ 开工前拒）。它不再能绕过
        全局（剩余就是全局剩余），也不再被误当成阈值。
        """
        grant = self.meter.guard(0, role=role, scope="summon")
        want: float | None = None
        if budget and budget.get("max_usd") is not None:
            try:
                want = float(budget["max_usd"])
            except (TypeError, ValueError):
                want = None
        if (want is not None and grant.allowed and grant.remaining_usd is not None
                and want > grant.remaining_usd):
            # 预计吃掉的钱比剩下的还多 ⇒ 开工前拒（这正是"预计值"该有的判据：
            # 此前那一版判的是 `已花 >= X`，与"这一单要花多少"毫无关系）。
            from .tokenmeter import MeterReading as _MR

            return _MR(
                limited=True, allowed=False,
                spent_tokens=grant.spent_tokens, spent_usd=grant.spent_usd,
                budget_usd=grant.budget_usd, remaining_usd=grant.remaining_usd,
                estimate_tokens=0,
                reason=(f"这一单预计最多花 {want:.6f} 美元，而全局只剩 "
                        f"{grant.remaining_usd:.6f}（已花 {grant.spent_usd:.6f} / 上限 "
                        f"{grant.budget_usd:.6f}）⇒ **在开工前拒绝**"
                        "（而不是做到一半再停）"),
            )
        return grant

    def _charge_and_settle(self, res: SummonResult, *, role: str) -> SummonResult:
        """把这次召唤的花销记进权威账，再把账上的累计值写回 `tasks`。

        零值也记（`tokenmeter` 的设计②）：一次"跑了但没花 token"的召唤必须留下一条零值行，否则"没记账"与"花了零"无法
        区分，而"预算还剩多少"就永远答不准。`UsageEntry.validate` 要求零值必须带 `note`，所以这里无条件给一个说明。
        ## 幂等键同时进 `note` 与 `idem_key` 字段：键由 `modelcost.settle_key(task_id)` 生成（幂等键的唯一生成处），由
        `charge_once` 同时写进那一行的 `note` token 与 `idem_key` 字段。少了字段那一层，`schema.validate_table` 的字段
        级唯一性断言与 `verify.duplicate_idem_key` 在真实路径上就永远没有输入 —— 它们会在测试里常绿而在生产上不生效。
        ## 接线各 agent 的 `_call` 时必须读这一段（否则会双记）：现在的粒度是召唤级：这一条
        `Charge(scope="summon", tokens_out=res.tokens)` 是这一次召唤的唯一一笔。等各 agent 的 `_call` 也接上 `charge()`
        之后，这里必须改成"只记零值兜底"：`_call` 记的细账已经进了台账 ⇒ `summon` 再记一次会让 `usage_ledger` 的汇总
        变成真实花销的两倍（而 `tasks.tokens` 是从台账派生的，所以两边会一起虚高 —— 它们仍然"相等"，但相等的是错的
        数，这比不等更危险）；正确的形态：`_call` 记细账；`summon` 只在这一 task 还一条账都没有时补一条零值行
        （`tokens_for(task_id) == 0`），理由是"零值也要记"。记账失败不许让一次已经完成的召唤变成失败（钱已经花了、
        活已经干完了）：这里兜住异常并写进日志。但这不是静默失败 —— 后果（`tasks.tokens` 与台账不等）会由 `verify.py`
        的 `usage_task_total_mismatch` 报出来，而那正是"两处口径不一致"该被看见的地方。
        """
        note = f"{role}.{res.action} via {res.status}/{res.outcome}"
        spent = int(res.tokens or 0)
        try:
            # 恰好记一次。`finish()` 是幂等的（终态先到先得）：若这一行
            # 在本次 `finish` 之前已经是终态（另一个写者赢了），那么
            # 它当初就该被记过一次账 —— 再记一次会让 `usage_ledger` 的汇总
            # 变成 `tasks.tokens` 的两倍，而 `verify.py` 会（正确地）报
            # `usage_task_total_mismatch`。判据落在台账行的 `inputs` 里，
            # 因为那是一个能在同一事务内读到的既有标记位。
            row = self._task(res.task_id) if res.task_id else None
            already = bool(row and any(str(x) == _SETTLED_MARK for x in (row.get("inputs") or [])))
            if already:
                self._log(f"跳过重复记账（{res.task_id} 已结算）", task_id=res.task_id)
                return res
            charge = Charge(
                role=role if role in (*S.ROLES, S.CONDUCTOR_ROLE) else S.CONDUCTOR_ROLE,
                scope="summon",
                tokens_out=spent,          # 召唤层只知道总量；in/out 的细分由各 agent 的 _call 记
                usd=float(res.usd or 0.0),
                task_id=res.task_id,
                note=note,
            )
            if res.task_id:
                # 判重的权威在账本里（`charge_once` 的锁内比对），不在
                # `tasks.inputs` 的标记上。那个标记读得早（`self._task()` 是无锁
                # 快照读），两个实例同时结算同一行时两边都会读到"还没结算"，
                # 于是两笔账都落下去 —— 而两行的 `usage_id` 不同，按主键去重救不了。
                # `charge_once` 把判重搬进 `charge` 本来就持有的那把锁，
                # 后到的那个一定看得见前一笔。标记保留为便宜的快速通道。
                #
                # 键由 `modelcost.settle_key` 生成（幂等键的唯一生成处），
                # `charge_once` 会把它同时写进 `note` 的 token 与 `idem_key` 字段：
                # `note` 那一层跨版本可用，字段那一层有表级唯一性断言。
                outcome = self.meter.charge_once(charge, idem_key=settle_key(res.task_id))
                if outcome["duplicate"]:
                    # `G-8`：这一支不许早退。
                    #
                    # 走到这里说明账上已经有这一笔 —— 典型现场是"账已落、
                    # `tasks` 还没写回就崩了"（或两个写者竞争，其中一个先落了账）。
                    # 早退会把下面的 `tokens_for()` 抄回与 `_set_usage()` 一起跳过，
                    # 于是 `tasks.tokens` 停在旧值（0）而账本是 1500：
                    # `verify_all` 报 `usage_task_total_mismatch`，
                    # `stats()['budget']` 也跟着与权威账分家 —— 同一件事两个数字。
                    #
                    # 修法是"落到同一条路径上"：`tokens_for()` 与 `_set_usage()`
                    # 读写的都是账本上的值（不是累加），所以重放是幂等的 ——
                    # "先 charge 再抄回"这条构造性等式因此在重放路径上也成立。
                    self._log(
                        f"重复记账（{res.task_id} 的账已存在）⇒ 不再落账，"
                        f"但仍把账上的值抄回 tasks（`G-8`）",
                        task_id=res.task_id,
                    )
            else:
                # 没有 `task_id` ⇒ 没有稳定的身份 ⇒ 构不成幂等键。
                # 如实退化成"每次都记"（与既有行为一致），不假装它幂等。
                self.meter.charge(charge)
            if res.task_id:
                # 从账本读回来写进 tasks ⇒ 两处按构造相等
                res.tokens = self.meter.tokens_for(res.task_id)
                res.usd = self.meter.usd_for(res.task_id)
        except Exception as e:  # noqa: BLE001 - 见 docstring：不许让记账问题翻转一次完成的召唤
            self._log(f"记账失败（{res.task_id}）：{type(e).__name__}: {e}",
                      task_id=res.task_id, tokens=spent)
            return res
        self.budget.spend(res.tokens, res.usd)   # 即时视图（唯一消费者：stats/观测）
        if res.task_id:
            self._set_usage(res.task_id, res.tokens, res.usd)
        return res

    def _set_usage(self, task_id: str, tokens: int, usd: float) -> None:
        """把账本上的花销写回 `tasks` 行，并打上"已结算"标记。

        为什么单独一个方法而不是在 `finish` 里写：一次召唤的花销只有跑完才知道，
        而 `finish` 在它之前就调了（终态必须先写下去 —— 中途崩溃时台账要能回答
        "它跑到哪一步了"）。所以这里是"终态已定，补上花销"的一步，它不是终态改写
        （`status`/`outcome`/`ended_at` 一个都不碰），`Task.validate` 允许。

        `_SETTLED_MARK` 写进 `inputs`：它是"这一行已经结过账"的可读证据，
        让重复结算变成可判定的事（见 `_charge_and_settle` 的说明）。
        用 `inputs` 而不是新开字段：它是审计用的"这次召唤读过什么"，
        加一个 `tokenmeter:settled` 元素不改变语义，也不需要动 schema（禁改区）。
        """
        self._refuse_write_in_snapshot("记花销（_set_usage）")
        with self.store.tx("tasks", actor="conductor", note="charge") as tx:
            row = tx.find("tasks", task_id=task_id)
            if row is None:  # pragma: no cover - finish 刚写过，走到这里说明表被清了
                raise ValueError(f"记账写回失败：{task_id} 不在 tasks 表里")
            row["tokens"] = int(tokens or 0)
            row["usd"] = float(usd or 0.0)
            inputs = [str(x) for x in (row.get("inputs") or [])]
            if _SETTLED_MARK not in inputs:
                row["inputs"] = inputs + [_SETTLED_MARK]
            S.Task(**{k: v for k, v in row.items() if k in S.Task.__dataclass_fields__}).validate()
            tx.upsert("tasks", row, note="charge")
    # ---------------------------------------------------------------- 召唤
    def summon(
        self,
        role: str,
        action: str,
        params: Mapping[str, Any] | None = None,
        *,
        by: str = S.CONDUCTOR_ROLE,
        parent_task_id: str | None = None,
        input_key: str = "",
        budget: Mapping[str, Any] | None = None,
        token: CancelToken | None = None,
        lineage: Sequence[tuple[str, str, str]] | None = None,
        instance: str = "",
        roster: Mapping[str, Any] | None = None,
    ) -> SummonResult:
        """唯一的召唤入口 —— 阻塞式拼法（`summon_begin` 再 `summon_run`）。

        它只是两种拼法里的那一种：`summon_preemptible` 派完就给句柄，
        这一种派完就等到孩子跑完。两者是同一段实现（前半在 `summon_begin`、
        后半在 `summon_run`），所以"可抢占版"与"阻塞版"不可能漂移 —— 判据
        `tests/test_summon_is_preemptible.py` 的 e 条（结果集/顺序/refusal 一致）
        就是靠这条构造性等式。

        参数说明在 `summon_begin`（唯一的一份）。
        """
        # ---- R9FIX-D3：单件派活也要扫一次待认领队列 -------------------------
        #
        # 改前只有 `summon_many` / `run_plan` 与顶趟收尾扫队。真机 lp-ball-9
        # （08:53:39，`r-000009`）是 M 在初始批次之后一直用单件 `conductor.summon`
        # 派活（09:11 / 09:14 / 09:19 三次），于是 D 提交的那一条检索请求到收工
        # 都没人认领（`attempts=0`）⇒ R11 红。
        # 判据只挂在"M 自己发起的单件派活"上：`run_plan` / `summon_many` 已经扫过
        # （`_consume_queue_before_dispatch`），子角色派活不替 M 收研究链的队列。
        # `_queue_sweeping` 防递归：认领本身就是一次 `summon("A","run_once")`。
        if (not getattr(self, "_queue_sweeping", False)
                and current_caller_role() == S.CONDUCTOR_ROLE):
            self._queue_sweeping = True
            try:
                self._consume_queue_before_dispatch()
            finally:
                self._queue_sweeping = False
        return self.summon_run(self.summon_begin(
            role, action, params, by=by, parent_task_id=parent_task_id,
            input_key=input_key, budget=budget, token=token, lineage=lineage,
            instance=instance, roster=roster))

    def summon_preemptible(
        self,
        role: str,
        action: str,
        params: Mapping[str, Any] | None = None,
        *,
        by: str = S.CONDUCTOR_ROLE,
        parent_task_id: str | None = None,
        input_key: str = "",
        budget: Mapping[str, Any] | None = None,
        token: CancelToken | None = None,
        lineage: Sequence[tuple[str, str, str]] | None = None,
        instance: str = "",
        roster: Mapping[str, Any] | None = None,
    ) -> "SummonHandle":
        """派完就返回句柄（不等到孩子跑完）—— 这就是"可抢占"。

        与 `summon` 的差别只有一处：后半段（执行 handler、写终态、记账）跑在
        一个后台线程里，句柄立刻可读（`task_id` / `running` / `done`）。
        前半段（判据、落 running 行、名册登记）仍在调用线程里同步做完 ——
        它是"派活真的发生了没有"的判据，必须与调用方的因果顺序一致：
        派出去的编号在 `summon_preemptible` 返回那一刻就已经在台账上，
        而不是"过一会儿可能会出现"。

        为什么必须可抢占：阻塞式派活会让父代理在等待期间零回合，后果不是"慢"，
        而是"下一次 ask_step 之前的任何投递都只能在阻塞结束时才出手" ——
        等待越长，迟到的消息越多。
        """
        return self.start_summon(self.summon_begin(
            role, action, params, by=by, parent_task_id=parent_task_id,
            input_key=input_key, budget=budget, token=token, lineage=lineage,
            instance=instance, roster=roster))

    def open_handle(self, start: "SummonStart", *, on_settle: Any = None) -> "SummonHandle":
        """造一个句柄，但不起线程（调度器自己管线程与并发闸）。

        为什么要这一层：`scheduler` 的每一张票要自己决定"什么时候跑后半、
        跑在哪个线程、包不包信号量与探针"。它需要的是同一个 `SummonHandle`
        类型（判据 f 条：单任务与整批同一个形状），但不是 `start_summon`
        那条线程。
        """
        handle = SummonHandle(start=start)
        handle.on_settle = on_settle
        if start.refusal is not None:
            handle.settle(start.refusal)
        return handle

    def start_summon(self, start: "SummonStart", *, on_settle: Any = None,
                     run: Any = None) -> "SummonHandle":
        """把 `summon_begin` 的产物挂到一个后台线程上，并立刻返回句柄。

        两个可选钩子（缺省 = 常规行为）：

        - `run`：跑哪一段（缺省 `self.summon_run`）。调度器传一个把
          `Semaphore` 与 `ConcurrencyProbe` 包好的版本 —— 并发上限与探针
          必须包住"真的执行"那一段，而它在后台线程里；
        - `on_settle`：落定时回调（调度器用它把"这一波这一项落定了"通知给
          `WaveHandle` 的条件变量）。它可能在调用线程上被同步调用
          （预先判定的拒绝不占线程）。

        线程是 daemon：一次派活的线程不该把进程钉死（父循环可能在它跑完之前
        就收工 —— 那种情况由 `agent_loop` 的收工门与退场读数如实交代）。
        """
        handle = self.open_handle(start, on_settle=on_settle)
        if start.refusal is not None:
            # 预先判定的拒绝（越权/超深/触顶/预算/取消）：终局已定，不占线程。
            return handle
        # ---- [0b] 停机开关（A / B2）：不为"开关落盘之前就已建好的那一趟"起线程 ------
        #
        # `summon_begin` 已经查过一次；走到这里仍是"没停"说明这一趟的前半发生在开关
        # 落盘之前。再一次读盘，停了就不起线程 —— 否则线程一起来仍会写 run_start /
        # 结算 usage_ledger（B2 的现场就是这种 0 步子循环）。
        _stop = self._dispatch_stop_gate(parent_task_id=start.parent_task_id)
        if _stop.get("stopped"):
            start = replace(
                start, refusal=self._stop_refusal(
                    start.role, start.action, by=str(start.by),
                    parent_task_id=start.parent_task_id, gate=_stop))
            return self.open_handle(start, on_settle=on_settle)
        ctx = contextvars.copy_context()
        th = threading.Thread(
            target=_summon_thread_main,
            args=(handle, ctx, run or self.summon_run),
            name=f"agentflow-summon-{start.task_id or 'x'}", daemon=True)
        handle.attach(th)
        th.start()
        return handle

    def summon_begin(
        self,
        role: str,
        action: str,
        params: Mapping[str, Any] | None = None,
        *,
        by: str = S.CONDUCTOR_ROLE,
        parent_task_id: str | None = None,
        input_key: str = "",
        budget: Mapping[str, Any] | None = None,
        token: CancelToken | None = None,
        lineage: Sequence[tuple[str, str, str]] | None = None,
        instance: str = "",
        roster: Mapping[str, Any] | None = None,
    ) -> "SummonStart":
        """召唤的前半：判据 + 落 running 行 + 名册登记（不含执行）。见模块 docstring。

        返回 `SummonStart`：`refusal` 非空 = 这一趟没派出去（终局已定，理由就是
        那个 `SummonResult`）；否则 `task_id` 非空、`tasks` 行已经是 `running`、
        名册那一格已经登记过。参数说明在 `_summon_preflight`。
        """
        got = self._summon_preflight(
            role, action, params, by=by, parent_task_id=parent_task_id,
            input_key=input_key, budget=budget, token=token, lineage=lineage,
            instance=instance, roster=roster)
        if isinstance(got, SummonStart):
            return got
        # 前半的终局是"没派出去"（越权/超深/触顶/预算/取消/参数）：包成同一个
        # 返回类型，于是调用方只需要判 `refusal is not None`，不必判两个类型。
        # 折成两个返回类型就是那种漂移：总有一处忘了判第二个。
        return SummonStart(role=str(getattr(got, "role", "") or role),
                           action=str(getattr(got, "action", "") or action),
                           params=dict(params or {}), by=str(by),
                           parent_task_id=parent_task_id, input_key=str(input_key),
                           instance=str(instance), token=token, refusal=got)

    def _summon_preflight(
        self,
        role: str,
        action: str,
        params: Mapping[str, Any] | None = None,
        *,
        by: str = S.CONDUCTOR_ROLE,
        parent_task_id: str | None = None,
        input_key: str = "",
        budget: Mapping[str, Any] | None = None,
        token: CancelToken | None = None,
        lineage: Sequence[tuple[str, str, str]] | None = None,
        instance: str = "",
        roster: Mapping[str, Any] | None = None,
    ) -> Any:
        """召唤的前半本体：八道判据，全部通过才落 running 行、登记名册。

        返回 `SummonStart`（派出去了）或 `SummonResult`（没派出去，终局已定）。
        两个返回类型只在这一层出现：公开面 `summon_begin` 已经收敛成一种。

        参数
        ----
        lineage : 祖先链（含父自身）。`scheduler` 会带过来；直接调用时可省略，此时从 `tasks` 表按 `parent_task_id`
            重建。两者必须一致：前者是纯调度（无 store）场景的表达，后者是正常运行时的权威来源。
        instance : 实例标签。空串 = 这个角色只有那一个实例。显式给不同的标签 ⇒
            被 `LocalBackend` 解析成不同的对象，并允许同波并发（`policy.estimate_write_conflict`）。它只影响"哪个实例
            干活"，不进 `tasks` 行 —— `tasks` 的字段是 schema 契约（禁改区），实例身份落在数据行的 `actor` 上（由
            `host` 按实例造对象时写死），那才是可审计的那一份。
        roster : 名册登记要用的那几格（`brief` / `task` / `name` / `reuse`），缺省 `None` = 一个都没给。
            为什么走形参而不是从 `tasks` 行读：`schema.Task` 里没有 `brief` / `task` 两格（它是禁改区的
            schema 契约），而"父给的那句简介"只活在派活的那个载荷里（`agent_loop._do_summon` 的 `brief`、
            `summon_many` 每个 target 的那一格）。从行里读这两格只会恒为空 ⇒ `roster_add` 用"没给一句任务
            简介"拒收每一条（名册照样空，只是 problem 变多）。
            没给 `brief` 是合法的：秘书从 `task` 代写一句并留痕。
        """
        params = dict(params or {})
        token = token or self.token
        t0 = time.monotonic()

        # ---- [0] 取消 / 销毁：不产生新任务
        #
        # 这一条与"拒绝也落台账"不冲突：拒绝是策略对一次召唤说的"不"
        # （那次召唤真的被提出过），而"取消之后不产生新任务"说的是
        # 不再有新的召唤发生。给被取消的召唤补一行台账，恰恰违反了它。
        # 返回 `task_id=None` 而不是编一个号：没有 start 就没有 end，
        # 编一个号会让调用方去查一条不存在的行。
        #
        # 名册那三格照旧要写：没被受理 ⇒ 不登记，但要留理由（"没跑成"与"不需要登记"
        # 与"登记过了"是三件事，折平了就没法读数）。
        if token.cancelled:
            r = token.reason
            with self._lock:
                self._cancelled_total += 1
            return SummonResult(
                task_id=None, role=role, action=action, status="cancelled", outcome="cancelled",
                detail=f"未启动：{detail_of(r)}", elapsed_sec=time.monotonic() - t0,
                roster_considered=True,
                roster_problem=f"未受理（取消：{detail_of(r)}）⇒ 名册不登记"
                               "（没有子行就没有名册项）",
            )
        if self._disposed:
            with self._lock:
                self._cancelled_total += 1
            return SummonResult(
                task_id=None, role=role, action=action, status="cancelled", outcome="cancelled",
                detail="未启动：Conductor 已 dispose（dispose 之后不再产生新任务）",
                elapsed_sec=time.monotonic() - t0,
                roster_considered=True,
                roster_problem="未受理（Conductor 已 dispose）⇒ 名册不登记",
            )

        # ---- [0b] 停机开关：停了就不再产生新任务（A / B2，2026-11-15）--------------
        #
        # 位置是判据的一部分：排在取消/dispose 之后（那两条的结论比"停机"更具体：
        # 这个主控已经明确不产生新任务）、落在 [1] 之前与写任何台账之前 —— 开关在盘上
        # 时这一趟连一行 tasks 都不落（真机那两笔是 0 步的 running 行）。
        _stop = self._dispatch_stop_gate(parent_task_id=parent_task_id)
        if _stop.get("stopped"):
            return self._stop_refusal(
                role, action, by=by, parent_task_id=parent_task_id, gate=_stop)

        # ---- [1] 角色 / 动作存在性（不落台账的只有"取消"这一种，见上）
        #
        # [1a] 不可召唤要先于动作表判。`summon(role="M")` 若先撞上 `unknown_action`
        # （"这个角色没这个动作"），真相是"召唤主控这件事本身不允许"（`NON_SUMMONABLE`）。
        # 两者的处置相反：前者让人去查名字，后者要求改设计。专用判据 `policy.check`
        # 一直是对的，是这条入口曾把顺序放反了。
        if str(role) == S.CONDUCTOR_ROLE:
            return self._refuse(
                role, action, reason="forbidden_edge",
                detail=(f"{S.CONDUCTOR_ROLE} 不可被召唤（NON_SUMMONABLE）：主控就是派活方，"
                        "没有『召唤 M』这条边"),
                by=by, parent_task_id=parent_task_id, input_key=input_key, params=params, depth=1,
                instance=instance,
            )
        # 口径「M 只派活」：`action` 为空时跳过这一格 ——
        # 「一致改成 task 必填，action 不填」「action 完全不用父代理填」⇒ 没有动作名可核。
        # 这里若直接调 `P.check_action`，空动作会被判 `unknown_action`
        # （"{{role}} 没有动作 ''"），于是"派活"在落行之前就被拒，连"越权 ⇒ 代唤"
        # 那条路都走不到。角色存在性与边由下面的 `P.check` 照旧把关。
        if str(action):
            edge = P.check_action(role, action, registry=self.specs)
            if edge is not None:
                return self._refuse(
                    role, action, reason=edge.reason, detail=edge.detail, by=by,
                    parent_task_id=parent_task_id, input_key=input_key, params=params, depth=1,
                    instance=instance,
                )

        # ---- [2] 参数（结构问题在写 running 行之前判掉：跑一个注定炸的
        #          参数会让台账里多一条 failed，而它其实从来没被执行过）
        #
        # 口径「M 只派活」：`action` 为空 = 派活而不点动作 ——
        # 没有动作的 schema 可核（`find_action("", …)` 当然是 None），所以这一格跳过；
        # 交给接活的那个角色自己的循环按它自己的工具面校验。
        spec = C.find_action(role, action, registry=self.specs) if str(action) else None
        if spec is not None:
            bad = self._check_params(spec, params)
            if bad is not None:
                # 理由码是 `invalid_params` 而不是 `unknown_action`：
                # "参数不合法"与"角色没这个动作"是两件事，前者要改参数，后者要查能力表。
                return self._refuse(
                    role, action, reason="invalid_params", detail=bad, by=by,
                    parent_task_id=parent_task_id, input_key=input_key, params=params, depth=1,
                    instance=instance,
                )

        # ---- [2b] 委托质量（A 线）：同 key 既有终态行摆到派活前 + 秘书的委派评估
        #
        # 位置是判据的一部分：在参数过关之后、写 running 行之前。参数不过关的召唤
        # 已经在上一步落成 `invalid_params`，不必再摆一次重复候选（那只会让读数变吵）；
        # 而写在 running 行之前，是为了让"这条既有终态行是我自己"这件事不可能发生
        # （同 key 的重复候选里永远不该出现本次的 task_id）。
        self._note_delegation_quality(role, action, params, input_key=input_key, by=by)

        # ---- [3] 深度链
        try:
            depth, parent_role = self._depth_of(parent_task_id)
        except ValueError as e:
            # 父任务不存在 = 这次调用本身不成立（结构问题），同样落 `invalid_params`
            return self._refuse(
                role, action, reason="invalid_params", detail=str(e), by=by,
                parent_task_id=parent_task_id, input_key=input_key, params=params, depth=1,
                instance=instance,
            )

        # ---- [4] 策略判定（边 / 深度 / 循环 / 扇出 / 并发 / 总量 / 预算 / 墙钟）
        chain = tuple(lineage) if lineage is not None else self._ancestry(parent_task_id)
        # 扇出 = 此刻在飞的直接子数（单时刻，不是累计；直接子返回即腾出名额）
        # —— 判据见 `_in_flight_children_of`。
        # 只数直接子，不管隔着几层的子：孙辈挂在子自己名下，算子的格。
        # 累计读数（`_admitted_children_of`）仍在台账/审计面，但不参与策略判定。
        # 上限那一档按发起方角色取（`by`），默认档与主控档都在 `policy` 里。
        direct_children = len(self._in_flight_children_of(parent_task_id)) if parent_task_id else 0
        # ---- [4-pre] 触顶就等（只可等待子智能体返回结果）
        #
        # 等在这里、而不是等在第 [5] 步之后：占位令牌（`self._running`）此刻还没拿，
        # 等的时候不会把全局并发名额攥在手里（拿在手里会让别的线程也派不动）。
        fanout_wait: dict[str, Any] | None = None
        direct_children_limit = P.direct_children_limit_for(self.policy, by)
        if parent_task_id and direct_children >= direct_children_limit:
            fanout_wait = self._await_fanout_slot(
                parent_task_id, direct_children_limit, token=token)
            direct_children = len(self._in_flight_children_of(parent_task_id))
            self._log(f"扇出触顶：等 {fanout_wait.get('waited_sec', 0):.1f}s"
                      f"（在飞 {fanout_wait.get('in_flight_before')} → "
                      f"{fanout_wait.get('in_flight_after')}，上限 {direct_children_limit}，"
                      f"{fanout_wait.get('reason')}）")
        # ---- 判据与占位必须在同一个临界区里
        #
        # 锁外判的写法是"锁内读 `running`/`total` → 锁外判 → 写完 running 行（一次 fsync
        # 事务）之后才 `_running.add`"。于是同一瞬间有 N 个线程都读到 `running=3` 时
        # 会全部放行，`max_concurrency` 被超过 (N-1)；`Semaphore` 只在单次
        # `run_waves` 内生效，跨 plan / 跨进程都不约束。
        #
        # 修法：把"占位"提到锁内、与读计数同一临界区（判 + 预留 + 失败回滚），
        # I/O 仍留在锁外（"事务绝不包 handler"以及"锁内不做 I/O"两条纪律都不动）。
        # 预留用的是一个唯一的占位令牌（不是 task_id —— 那个要 `_write_new_row`
        # 拿到锁才分配）：于是 `len(self._running)` 的含义从"真的在跑的"扩成
        # "已接受、还没结束的"，而这正是上限想约束的那个量。
        with self._lock:
            # 两个数都按旧语义取：`running` 是"已经接受、还没结束"的条数
            # （不含本次自己），`total` 是"已经发生过"的次数（不含本次）——
            # 这样 `policy.check` 的 `>=` 边界一个字节都不动（改了语义等于偷偷收紧上限）。
            # 与锁外判的唯一差别是：别的线程的预留也在这个集合里了 ⇒ 那个窗口没了。
            running = len(self._running)
            total = self._started_total + self._cancelled_total
            self._started_total += 1                # 预留：与下面的令牌同进同出
            reserve = f"__reserving__{next(self._reserve_seq)}"
            self._running.add(reserve)
            self.peak_running = max(self.peak_running, len(self._running))

        def _release_reservation() -> None:
            """把这次预留还回去（判据说不、或建行失败时）。幂等。"""
            with self._lock:
                if reserve in self._running:
                    self._running.discard(reserve)
                    self._started_total = max(0, self._started_total - 1)

        want_usd = None
        if budget and budget.get("max_usd") is not None:
            want_usd = float(budget["max_usd"])
        # ---- [4a] 预算守卫：在开工之前问一句"还允不允许"。
        #
        # 顺序是判据的一部分：`guard()` 必须在写 `running` 行之前跑。
        # "干完再拒"不是同一个功能 —— 它的后果是钱已经花掉了才说不该花，
        # 而且台账里会多一条 `failed`（看起来像执行出错，其实是策略拦截）。
        # 拒绝理由走现成的 `budget_exceeded`：拒绝是一次成功的执行
        # （框架正确地说"不"），不是失败。
        grant = self._meter_guard(role, budget)
        if not grant.allowed:
            _release_reservation()
            return self._refuse(
                role, action, reason="budget_exceeded", detail=grant.reason, by=by,
                parent_task_id=parent_task_id, input_key=input_key, params=params, depth=depth,
                instance=instance,
            )
        # 触顶那一刻才去读"每一格坐着谁"：它是拒绝报文里那份名单的唯一来源
        # （口径见 `fanout_seats_of`）。平时不读 —— 一次整树三态快照不值得每派一件活都做。
        seats: Sequence[Mapping[str, Any]] = ()
        if parent_task_id and direct_children >= direct_children_limit:
            seats = tuple(self.fanout_seats_of(parent_task_id).get("seats") or ())
        d = Decision(
            frm=by, to=role, action=action, depth=depth, direct_children=direct_children,
            direct_children_seats=seats,
            running=running,
            total=total, ancestry=chain, key=(role, action, input_key),
            # 预算不再在这里判：`Decision.tokens_left/usd_left` 用的是
            # 本次 run 的即时视图，而权威账在 `usage_ledger`。
            # 同一件事两处判会漂移（一处说还能花、另一处说不能），
            # 所以预算只由上面那一次 `guard()` 判 —— 单一来源。
            deadline_hit=self.deadline_hit,
        )
        refusal = P.check(self.policy, d, registry=self.specs)
        if refusal is not None:
            # 墙钟到点：除了拒绝，还要协作式取消在跑的
            # （设计 §3.2："已在跑的协作式取消"）。
            if refusal.reason == "deadline_exceeded":
                self._signal_stop("deadline", refusal.detail, by="deadline")
            refusal_detail = refusal.detail
            if refusal.reason == "fanout_exceeded" and fanout_wait is not None:
                # 触顶是"等过之后仍然满"—— 把等的那一段读数带上，否则读台账的人
                # 分不清"当场就满"与"等了 900 秒都没人回来"。
                refusal_detail += (
                    f"（触顶后等了 {fanout_wait.get('waited_sec', 0):.1f}s：在飞 "
                    f"{fanout_wait.get('in_flight_before')} → "
                    f"{fanout_wait.get('in_flight_after')}，"
                    f"{fanout_wait.get('reason')}）")
            _release_reservation()
            return self._refuse(
                role, action, reason=refusal.reason, detail=refusal_detail, by=by,
                parent_task_id=parent_task_id, input_key=input_key, params=params, depth=depth,
                instance=instance,
            )

        # ---- [5] 写 running 行（带 started_at），然后放掉锁再去跑 handler
        #
        # 事务只包台账那一行，绝不包 handler。理由有两条，任一条都足够：
        # (a) handler 可能要跑几分钟（实验脚本、网络检索），持锁会让所有其它
        #     角色饿死 —— 那是"并发"变成"排队"的最隐蔽形态；
        # (b) handler 内部自己会 `store.tx(...)`，在锁内重入锁是死锁。
        #
        # 但取号与建行必须在同一个临界区里（见 `_write_new_row`）——
        # 那是本次实现里真实修掉的一个并发缺陷：分开做会让两个线程拿到同一个
        # `task_id`，后写的静默覆盖先写的。
        started = S.now_iso()
        row = {
            "task_id": "",
            "role": role, "action": action, "called_by": by,
            "parent_task_id": parent_task_id, "depth": depth, "input_key": input_key,
            "status": "running", "outcome": None, "refusal_reason": None,
            # 与 `Task` 的字段顺序一致（`refusal_reason` 之后、`detail` 之前）——
            # 顺序不一致会让 `tasks.json` 在 `rebuild()` 之后逐字节不同。
            "instance": instance,
            "detail": (spec.summary if spec is not None else _dispatch_only_detail(str(role or ""))),
            "error": None, "started_at": started, "ended_at": None,
            "tokens": 0, "usd": 0.0,
            "artifacts": [],
            # `inputs` 的初值同时打上受理标记：它与 `status="running"` 这一行同一笔事务
            # 落盘，因此累计审计读数（`_occupies_fanout_slot` / `_admitted_children_of`）
            # 不再依赖后续任何一步（角色自己的拒绝、记账写回、甚至崩溃）是否成功。
            # 理由与负控见 `_ADMITTED_MARK`。扇出上限本身只看
            # `status ∈ {pending,running}`，与本标记无关。
            "inputs": _admitted_inputs(params),
        }
        # 「在飞」标记的寿命就是 [5]→[5b] 这一段：登记已经发生（或已经带理由地
        # 没发生）之后才清。用 finally 而不是几个清理点 —— 漏一条路径，这一号就会被
        # `roster_repair` 永久跳过（静默欠补），比多几行 diff 严重得多。
        tid = ""
        try:
            try:
                tid = self._write_new_row(row, note=f"start:{role}.{action}",
                                          roster_pending=True)
            except BaseException:
                # 建行失败（store 抛了什么）⇒ 预留必须还回去，否则"已接受、还没结束"的
                # 计数会永久高一个，后续每一次召唤都被自己上次的失败挤掉配额。
                _release_reservation()
                raise
            with self._lock:
                # 把占位令牌换成真 task_id：计数一个不增不减（预留已经计过了）。
                self._running.discard(reserve)
                self._running.add(tid)
            self._log(f"召唤 {by} → {role}.{action}（{tid}, depth={depth}"
                      + (f", instance={instance}" if instance else "") + "）")

            # ---- [5b] 名册登记：子行已经落盘、子代理还没跑。这是唯一的登记点。
            #
            # 位置就是判据本身（三条，缺一条都会重现"没跑完的都不在名册上"）：
            # ① 在 `_write_new_row` 之后 —— 只有真的建了子行才登记（被拒的召唤在
            #    `_refuse` 里另有一条路，它不经过这里 ⇒ 不会登记）；
            # ② 在 `backend.call` 之前 —— 子代理可能跑很久、也可能被强停，等它返回再
            #    登记等于"没跑完的都不在名册上"；
            # ③ 只在这里 —— 调用点（`_do_summon` / `_do_summon_many` / 队列认领 / 两个工具）
            #    一个都不许再自己调 `roster_add`，否则同一个子代理会有两条同名项。
            #
            # 失败姿态：`_register_roster` 从不抛（没秘书/秘书拒收/抛异常都变成一条 problem），
            # 所以登记不会带走这次派活；读数随 `SummonResult.roster_*` 交回调用方。
            #
            # 这里还要读盘（`roster_rec["state"]`），并把"没写成"与"兜底换过"都打进
            # 日志。理由：可抢占派活的父代理那一步拿到的是"还在跑"，读不到名册那几格
            # （`_do_summon` 在 handle 没落定时提前返回）⇒ 若这里不记，一次整份漏写就
            # 只剩读侧的 `unplaced` 这一个事后读数。
            roster_rec = self._register_roster(task_id=tid, role=role,
                                               owner=str(parent_task_id or ""), meta=roster)
            if roster_rec.get("problem"):
                self._log(f"名册没写成：{roster_rec['problem']}", task_id=tid)
            elif roster_rec.get("note"):
                self._log(f"名册写成（{roster_rec['note']}）", task_id=tid)
        finally:
            SEC.forget_roster_pending(
                self.store.root, str(parent_task_id or ""), tid)
        # ---- [5c] 等这条子代理的计时器（不变式：「一个子代理还有活跃子代理，必存在
        # 一个等待该子代理的计时器」，所以"静默"定义良好）。位置是判据本身：
        # ① 在 `_write_new_row` 与 `_register_roster` 之后 —— 子行与名册行都已在盘上，
        #    "等谁"的读口（台账/名册）此刻读得到它，目的才填得出原文；
        # ② 在 `backend.call` 之前 —— 子代理可能跑很久，甚至一跑完就交差；起表晚一步
        #    就正好漏掉那一档（与名册登记同一条理由，见 [5b]）；
        # ③ 只在这里 —— 调用点一个都不许自己起这条表，否则同一个子代理会被等两次。
        parent_row = self._task(str(parent_task_id or "")) or {}
        waiter_rec = self.arm_child_waiter(
            tid, parent_task_id=str(parent_task_id or ""),
            role=str(parent_row.get("role") or ""),
            task_text=str((roster or {}).get("task") or ""))
        if not waiter_rec.get("armed"):
            self._log(f"等子代理的计时器没起成：{waiter_rec.get('reason')}", task_id=tid)
        return SummonStart(
            role=str(role), action=str(action), params=params, by=str(by),
            parent_task_id=parent_task_id, input_key=str(input_key),
            instance=str(instance), token=token, t0=t0, task_id=tid,
            roster=dict(roster) if roster else None,
            roster_rec=dict(roster_rec or {}), started_at=str(started),
        )

    def summon_run(self, start: "SummonStart") -> SummonResult:
        """召唤的后半：执行 handler、写终态、记账（可以直接在别的线程里跑）。

        与 `summon_begin` 成对：`summon` = 两段在同一条调用栈上顺序跑；
        `summon_preemptible` = 前半在调用线程、后半在后台线程。
        这里的每一句都不碰"派活成不成立"的判据（那是前半的事），
        只回答"这一趟跑出了什么"。
        """
        if start.refusal is not None:
            return start.refusal
        tid = str(start.task_id or "")
        if not tid:  # pragma: no cover - 前半要么落行要么落拒绝，走到这里说明它坏了
            return SummonResult(role=start.role, action=start.action, status="failed",
                                outcome="failed", error="summon_begin 既没落行也没拒绝",
                                detail="内部错误：派活前半没有给出 task_id")
        role, action, params = start.role, start.action, start.params
        token, instance = start.token, start.instance
        roster, roster_rec, t0 = start.roster, start.roster_rec, start.t0

        # ---- [5d] 停机开关：开关落盘之前建好的那一趟，也不许真的开跑（A / B2）------
        #
        # 这一支与 `_summon_preflight` 的那一闸是同一个判据的第二次读：前半已经落过
        # running 行（开关当时还没落盘），所以这里不能像前半那样"什么都不留"——
        # 按取消收口（`S.child_ending` 的唯一判定点），如实说"不是执行失败"。
        _stop = self._dispatch_stop_gate(parent_task_id=start.parent_task_id)
        if _stop.get("stopped"):
            refusal = self._stop_refusal(role, action, by=str(start.by),
                                         parent_task_id=start.parent_task_id, gate=_stop)
            _closing = S.child_ending(stop_code=str(_stop.get("reason") or "stop_file"))
            self._log(f"停机收口 {role}.{action}（{tid}）：前半建行早于开关落盘，"
                      "按取消结束、不开跑", task_id=tid)
            return self.finish(
                tid, status=_closing["status"], outcome=_closing["outcome"],
                detail=(refusal.detail
                        + f"（前半在开关落盘之前已建行 {tid}；按取消收口，不算执行失败）"))

        # ---- [6] 执行
        try:
            # `task_id` 传下去：并发多实例时"按角色找那条 running 行"
            # 会同时找到 N 条 ⇒ 后端拿不到自己的台账号。台账号是这一次召唤刚写下的，
            # 这里就是它唯一的权威来源，直接给，别让后端去猜。
            raw = self.backend.call(role, action, params, token=token, instance=instance,
                                    task_id=tid)
            res = self._end_from_payload(tid, raw)
        except CancelRequested as e:
            # ---- 被叫停是"一个子代理结局"的第二档，判定只在 `S.child_ending` 一处
            # （字面量不许在这里另拼一份：这里若写死 `cancelled`/`cancelled`，与
            # `dispose` 那一处各写一份，"被停"这一档就有两个定义）。
            _code = str(getattr(getattr(e, "reason", None), "code", "") or "cancelled")
            _stop = S.child_ending(stop_code=_code)
            res = self._end(tid, status=_stop["status"], outcome=_stop["outcome"],
                            detail=f"被协作式取消：{e.reason}")
        except NotWiredError as e:
            # 未接线不是失败：它是一次拒绝（框架正确地说了"这里还没接"）。
            res = self._end(tid, status="done", outcome="refused", refusal_reason="not_wired",
                            detail=str(e))
        except Exception as e:  # noqa: BLE001 —— 这里必须兜住一切，否则僵尸 running
            # ---- 业务拒绝 ≠ 崩溃
            #
            # 角色代码故意抛出的领域错误（`ExperimentError` / `DocumentError` /
            # `PlanError` / `ReviewError` / `EvidenceError` / `ToolError`）表示
            # "这次调用不成立" —— 与 `refused` 同族；而 `TypeError` / `KeyError` /
            # `AttributeError` / `OSError` 这些是代码或环境崩了，必须留 `failed`。
            # 两者一律落 `failed / 执行中异常` 的话，一次参数拒绝会被记成"崩了" ——
            # 读台账的人会去查代码，而该改的是调用。
            #
            # 刻意不把裸 `ValueError` 算进拒绝：它既可能是校验（业务），
            # 也可能是判据自身的 bug；宁可把它留在 `failed`（过度报失败比把 bug
            # 伪装成"策略说不"安全）。
            code = _business_refusal_code(e)
            if code is not None:
                res = self._end(tid, status="done", outcome="refused", refusal_reason=code,
                                detail=f"{role}.{action} 拒绝了这次调用：{e}")
            else:
                res = self._end(tid, status="failed", outcome="failed",
                                error=f"{type(e).__name__}: {e}",
                                # 详情里也要带原话：只写一句"执行中异常"，主控修不了脚本 ——
                                # 不知道是导入失败、语法错、还是脚本自己抛的。
                                # 三态纪律在这一层：失败要留下能据以改的原话。
                                detail=f"{role}.{action} 执行中异常"
                                       f"（{type(e).__name__}: {e}）")
        finally:
            with self._lock:
                self._running.discard(tid)
        # ---- [7] 记账：权威账是 `usage_ledger`，`tasks.tokens/usd` 由它派生
        #
        # 为什么"先 charge、再把账本的值抄进 tasks"，而不是 `summon` 自己累加一遍：
        # `verify.verify_all` 的 `dangling_usage_task`（账本行挂不到任务行）与
        # `usage_task_total_mismatch`（`tasks.tokens` 与 `usage_ledger` 里该 task 的
        # 汇总不等，文案是"预算判断会按哪一份？"）两条检查都在这条链上 ——
        # 它们要的是同一件事：两处对同一次召唤的花销必须给出同一个数字。
        # 自己累加的那个相等只是"两处各算一遍但愿它们相等" —— 任何一条漏记
        # （一次重试、一个还没接线的 `_call`）都会让它静默不等。
        # 现在的写法让相等由构造保证。
        res = self._charge_and_settle(res, role=role)
        if res.tokens:
            # 这里只是记读数（2026-10-15 业主裁定 A1/A2/A3：「我们不卡 token，
            # 只卡总花销的钱」）。此前它写着"共享取消信号也吃 token 预算"——
            # 那条路（`CancelToken(budget_tokens=…)` ⇒ `cancelled` 变 True ⇒
            # 在跑的 handler 被掀掉）连同那一格一起删了。
            # 会拒绝的地方现在只有一处：`_meter_guard`（钱）。
            self.token.consume_tokens(res.tokens)
        # 展示面：`children` 列的是全部子行（含被闸门拒掉的尝试，谁试过什么要看得见），
        # 与扇出判据（`_in_flight_children_of`，只看还没返回的）刻意两个口径
        # —— 判据面不许把展示面改窄。
        res.children = self._children_of(tid)
        res.elapsed_sec = time.monotonic() - t0
        # 名册三格：登记发生在 [5b]（跑之前），读数在这里交回 —— 登记与结局是两件事，
        # 所以一个 failed 的结局不会改写"它被建立过、也进过名册"这个事实（台账里
        # `outcome=failed` 回答"跑成没有"，名册回答"有没有它"）。
        res.roster_considered = bool(roster_rec.get("considered"))
        res.roster_name = str(roster_rec.get("name") or "")
        res.roster_problem = str(roster_rec.get("problem") or "")
        res.roster_state = str(roster_rec.get("state") or "")
        res.roster_note = str(roster_rec.get("note") or "")
        return res

    # ---------------------------------------------------------------- 参数校验
    @staticmethod
    def _check_params(spec: C.ActionSpec, params: Mapping[str, Any]) -> str | None:
        """按 `ActionSpec.params` 校验。返回错误说明或 `None`。

        判据只有一份：`tools.base.validate_params`（与工具层同一套）。
        为什么不在 `summon` 里另写一遍校验：两套校验必然漂移，而漂移的形态是
        "主控放行了工具层会拒的参数"，那不会报错 —— 它会一路跑到 handler 里。
        """
        try:
            from .tools.base import validate_params

            validate_params(spec.params, dict(params))
        except Exception as e:  # noqa: BLE001 - ParamError 及子 schema 的错误都归为"这次没这么调"
            return f"{spec.role}.{spec.action} 的参数不合法：{e}"
        return None

    # ---------------------------------------------------------------- 结束态
    def _end_from_payload(self, tid: str, raw: Any) -> SummonResult:
        """把 handler 的返回值映射成终态。三态纪律在这里的落点。

        | handler 返回 | status | outcome |
        |---|---|---|
        | `None` | done | `no_result`（跑完了，确实没有） |
        | dict 带 `status/outcome` | 取它（角色自己更清楚） | 取它 |
        | 其它任何值 | done | `ok` |

        `None` 不许映射成 `ok`：那正是"把『没做』与『做了没结果』
        折叠成同一个值"—— 本项目在引文校验、OCR、D 溯源、C 预算截断四处
        踩过它，每一次的后果都是下游把"我们没查"读成了"查了没有"。

        ## 角色返回的 `status` 不是任务终态

        检查器那一族动作（E / L 的 `check_formal` / `formalize` / `record`）把 `status`
        写成三态词（`verified` / `failed` / `unknown`）—— 那是"检查器说了什么"，不是
        "这次召唤跑成了什么"。把 `raw["status"]` 直接当终态会落出两个缺陷：

        - `status="failed"` ⇒ 任务 failed，而 `schema.Task.validate` 要求 failed 必须写
          `error`；角色把检查器原话写在 `detail` 里（L 的键就叫 `detail`）⇒ 写台账那一刻
          抛 `ValueError` ⇒ 整步落 `failed / 执行中异常` 且 payload 丢失。一次有证据的
          "命题没核过"被记成"框架崩了"，证据全丢；
        - `status="unknown"`（受控拒绝 / 漏步 / 自检不过）一律折成 `done/ok` ⇒ 动作日志
          （`out/tasks/<id>.json`）上"拒绝 / 没查成 / 成功"三者同形。

        现在的分档按"有没有异常 / 有没有产出 / 有没有结论"排，不按 `status` 这个词排：

        | 角色返回 | 任务终态 | 为什么 |
        |---|---|---|
        | `refused=True` / `status="refused"` / 受控 `refusal_reason` | done/`refused` | 角色自报"这次调用不成立"：拒绝是策略的决定 |
        | `ok is False` | `refused` 或 `failed` | 见下面那一段 |
        | `failed`（`status` 或 `tri_state`） | failed/`failed` | 检查器说不行 ⇒ 这一趟没干成；`error` 从 `detail` 兜底 |
        | `unknown` | done/`no_result` + `[handler_not_checked …]` | 没查成：跑完了，但没给出结论 |
        | `verified` / 其它 | done/`ok` | 跑完了且给出了结论 |

        三档在动作日志上的机器可读位是 `outcome`（`ok` / `refused` / `no_result`）——
        不是三处都印 `status=done`。`refusal_reason` 只收受控词表里的取值（角色自己的
        理由码留在 `detail`），`tri_state` 与 `refused` 各自决定上面哪一行。
        """
        if raw is None:
            return self._end(tid, status="done", outcome="no_result",
                             detail="执行完成，本动作没有产出（no_result）")
        if isinstance(raw, Mapping):
            tri = _tri_state_of(raw)
            declared_status = str(raw.get("status") or "done")
            # 角色返回的 status 只认终态词表；三态词（verified/failed/unknown）与角色
            # 自己的状态词（A 的 content_mismatch、F 的 blocked）都不是任务终态。
            status = declared_status if declared_status in TERMINAL_STATUSES else "done"
            outcome = raw.get("outcome")
            detail = str(raw.get("detail") or raw.get("summary") or "")
            error = str(raw["error"]) if raw.get("error") else None
            refusal = str(raw["refusal_reason"]) if raw.get("refusal_reason") else None
            # 角色自己那个理由码（`reason` / `kind`）：自由文本，只进 detail 点名，
            # 不进受控词表 —— 行上的 `refusal_reason` 只接受 REFUSAL_REASONS 里的取值。
            handler_reason = refusal or str(raw.get("reason") or raw.get("kind") or "")
            if refusal is not None and refusal not in S.REFUSAL_REASONS:
                # 自由文本当拒绝理由：不许进受控词表。原来的写法是把它透传给
                # `Task.validate` ⇒ 那里抛 `ValueError` ⇒ 整步落 failed
                # —— 一次"拒绝"被记成"崩溃"，理由反而看不见了。
                detail = f"[handler_refusal_reason={refusal!r} 不在受控词表] {detail}".strip()
                refusal = None
            # 角色声明"拒绝"的三处口子（`refused=True` / `status="refused"` / 受控
            # `refusal_reason`）。三态纪律里"拒绝"是第三态位（`agent_l._support` 的
            # `RECORD_REASONS` 逐字论证过）：它既不是 unknown（没查成），也不是 failed（崩了）。
            #
            # 为什么只认角色自己声明的那三处、不替它从别的键里猜：与"取不到唯一声明名
            # 就拒绝"同一条纪律 —— 框架不替角色判断"这一趟算不算拒绝"。只写
            # `status="unknown"` 而没声明拒绝的，一律落"没查成"。
            declared_refusal = (raw.get("refused") is True or declared_status == "refused"
                                or refusal is not None)
            if status == "done" and raw.get("ok") is False:
                # ---- handler 自己说了"这次没做成"，就不许记成 ok。
                # 不接住的后果：台账把它们全记成 `outcome=ok`（detail 还写着"按有产出
                # 处理"）⇒ 主控以为活干完了，而下游那一张表是 0 行，那条链就在这一步
                # 静默停住。
                # 分档：handler 声明了受控的 `refusal_reason` ⇒ `refused`（词表定义就是"这次调用本身不成立"）；只说
                # `ok=False` 而没分类 ⇒ `failed`（"执行了、没成功"，理由合成在 error 上）。声明的 `outcome` 无论
                # 是不是任务级词表，都不许把 `ok=False` 洗成 ok —— 那正是下面那条"外来判定折叠成 ok"会做的事，
                # 所以这里必须先接住（判据：自相矛盾与外来判定两条负控）。
                kind = str(raw.get("kind") or "")
                declared = str(outcome or "")
                stamp = f"[handler_ok=False kind={kind or '未声明'}]"
                if declared == "ok":
                    stamp += "[同时声明 outcome=ok：自相矛盾，按没做成分档]"
                elif declared:
                    stamp += f"[同时声明 outcome={declared}：不是任务级词表，按没做成分档]"
                detail = f"{stamp} {detail or error or ''}".strip()
                if refusal is not None:
                    outcome = "refused"
                else:
                    status = "failed"
                    outcome = "failed"
                    error = error or f"{stamp} handler 返回 ok=False，未声明受控的 refusal_reason"
            elif status == "done" and declared_refusal:
                # ---- 角色声明了"拒绝"⇒ 必须落 `refused`，且行上的理由在受控词表里。
                # L 的 `formalize` / `record` 拒绝时给的是 `refused=True` + 它自己的理由码
                # （`statement_not_found` / `reading_mismatch` …），那些不在 `REFUSAL_REASONS`
                # 里：框架不替它再造一套词表 —— 行上落 `invalid_params`（词表定义正是
                # "参数/前置条件不满足：这次调用本身不成立"），L 的原话留在 detail 里。
                stamp = f"[handler_refused reason={handler_reason or '未声明'}]"
                detail = f"{stamp} {detail or error or '角色拒绝了这次调用（没给说明）'}".strip()
                status, outcome = "done", "refused"
                refusal = refusal or "invalid_params"
            elif status == "done" and tri == "failed":
                # ---- 三态说"检查器说不行"⇒ 这一趟没干成；`error` 从 `detail` 兜底，
                # payload 不丢。
                status = "failed"
            elif status == "done" and tri == "unknown":
                # ---- `unknown` 是"没查成"，不是 ok（受控拒绝走上面那一支）。
                # 落 `done/no_result` 而不是新造一个 `tasks.outcome` 取值：`TASK_OUTCOMES`
                # 是被 `cycles.outcome` / `audits.outcome` 复用的受控词表（`schema.py`
                # 还是禁改区），为一次映射把它改宽是把整张词表改宽。`no_result` 说的是
                # "跑完了、没给出结论"，而"没查成"由这个 stamp 与 payload 里的
                # `checked` / `status` / `reason` 三格承担（不是只靠一句自然语言）。
                stamp = (f"[handler_not_checked tri_state=unknown "
                         f"reason={handler_reason or '未声明'}]")
                detail = f"{stamp} 没查成：{detail or error or '角色没给说明'}".strip()
                status, outcome = "done", "no_result"
            # ---- 收口：下面三条对每一条分支都成立，顺序是有意的
            if status == "done" and outcome is None:
                outcome = "ok"
                detail = detail or "执行完成（handler 未声明 outcome，按有产出处理）"
            if outcome is not None and (
                    str(outcome) not in S.TASK_OUTCOMES
                    or str(outcome) in S.FRAMEWORK_ONLY_OUTCOMES):
                # ---- 两套词表不许折叠
                #
                # 角色有自己的判定词表（F 的子目标判定是 `progress` / `no_change` /
                # `blocked` …），而这里要的是任务级结果词表
                # （`TASK_OUTCOMES = ok/no_result/not_applicable/refused/failed/cancelled`）。
                # 把角色的判定原样透传 ⇒ `Task.validate` 抛 `ValueError` ⇒ 整步落
                # failed，而活其实已经干完了（事务已提交）—— 台账说"失败"、实际成功，
                # 那直接毁掉"台账能重建 M 的决策序列"。
                #
                # 处置：任务级结果按"执行完成"记 `ok`，角色的判定原样留在 detail 里
                # （可见，不是静默丢弃 —— 静默丢弃是本项目最忌的形态）。
                # 另一半：`FRAMEWORK_ONLY_OUTCOMES`（`cut_off_by_parent`）虽然在词表里，
                # 却只有父代理的退场结算能写 —— handler 声明它不算数
                # （否则一行会凭空变成"被掐断"，而读侧会把它的产出当作"未并入"丢掉）。
                detail = f"[handler_outcome={outcome}] {detail}".strip()
                outcome = "ok"
            if status == "failed":
                outcome = "failed"
                # ---- `status=failed` 必须写 `error`（`Task.validate` 逐字要求"失败的原因
                # 不能是空白"），而角色把检查器的原话写在 `detail` 里（L/E 的键名就叫
                # `detail`）⇒ 从这里兜底。只认 `raw["error"]` 的话，L 的每一次真失败都在
                # 写台账那一刻抛 ValueError，payload 一起丢。
                error = error or detail or (
                    "handler 声明 status=failed 但没写原因（框架按无理由失败记录）")
                detail = detail or error
            if status == "cancelled":
                outcome = outcome if outcome in ("cancelled", "refused") else "cancelled"

            return self._end(
                tid, status=status, outcome=str(outcome) if outcome else None,
                detail=detail or "执行完成",
                error=error,
                # 角色拒绝时它的理由必须能传到行上：`Task.validate` 逐字要求
                # `outcome=refused` 带受控的 `refusal_reason`，而不透传它
                # ⇒ 角色一拒绝就落 `failed`（"策略说不"被记成"代码崩了"）。
                # 判据：`test_refused_outcome_is_not_rewritten` 咬的就是这一条。
                refusal_reason=refusal,
                payload=raw.get("payload", raw.get("data", raw)),
                artifacts=list(raw.get("artifacts") or []),
                checked=raw.get("checked", None),
                tokens=int(raw.get("tokens") or 0),
                usd=float(raw.get("usd") or 0.0),
            )
        # 返回值不是 Mapping 时，也认它自己声明的 `outcome` / `detail`：`BRunResult`
        # 这一类结果对象本来就带着 `outcome` / `detail` 两个属性，而这一支若一律记
        # `ok`，"这一趟什么都没产出"与"干得漂亮"在台账上就同形了。只认受控词表里的
        # 取值（角色自己的判定词表，例如 F 的 `no_change`，不在 `TASK_OUTCOMES` 里 ⇒
        # 不采信，仍记 `ok` 并把话留在 `payload` 里），这样这条口子不会把两套词表折叠
        # 起来。
        declared = getattr(raw, "outcome", None)
        if (isinstance(declared, str) and declared in S.TASK_OUTCOMES
                and declared not in S.FRAMEWORK_ONLY_OUTCOMES):
            return self._end(tid, status="done", outcome=declared,
                             detail=str(getattr(raw, "detail", "") or "执行完成"), payload=raw)
        return self._end(tid, status="done", outcome="ok", detail="执行完成", payload=raw)

    def _end(
        self,
        task_id: str,
        *,
        status: str,
        outcome: str | None,
        detail: str = "",
        error: str | None = None,
        refusal_reason: str | None = None,
        payload: Any = None,
        artifacts: Sequence[str] = (),
        checked: bool | None = None,
        tokens: int = 0,
        usd: float = 0.0,
    ) -> SummonResult:
        """写终态。幂等：见 :meth:`finish`。"""
        return self.finish(
            task_id, status=status, outcome=outcome, detail=detail, error=error,
            refusal_reason=refusal_reason, payload=payload, artifacts=list(artifacts),
            checked=checked, tokens=tokens, usd=usd,
        )

    # ---------------------------------------------------------------- finish
    def _write_task_digest(self, row: Mapping[str, Any], *, payload: Any, status: str,
                           outcome: str | None, detail: str) -> str:
        """把一次召唤的返回值摘要写成 `<workspace>/out/tasks/<task_id>.json`；返回相对路径。

        `payload is None` ⇒ 返回空串（没产出就不写文件，免得留下"看起来有产出"的空壳）。
        写失败不影响终态：原因记进日志并返回空串 —— "有产出但摘要没写成"
        与"没有产出"必须分得开，而终态那一行不能因为日志写不了就丢掉。
        """
        if payload is None:
            return ""
        task_id = str(row.get("task_id") or "")
        if not task_id:
            return ""
        root = Path(getattr(self.store, "root", ".") or ".")
        rel = f"out/tasks/{task_id}.json"
        try:
            # 非 Mapping 的产物先投影成结构化 dict（CS-11）：C 的 `AnalysisReport` 是个
            # dataclass，不投影的话下面那两格（`payload_keys` / `readings`）恒空、
            # 整份产物只剩 repr 前 2000 字（真机 p2-review 的 hottest/gaps 就是这一档）。
            shaped = _structured_payload(payload)
            blob = json.dumps(shaped, ensure_ascii=False, sort_keys=True, default=str)
            doc = {
                "task_id": task_id,
                "role": str(row.get("role") or ""),
                "action": str(row.get("action") or ""),
                "status": status,
                "outcome": outcome,
                "detail": detail,
                "at": S.now_iso(),
                "payload_sha256": hashlib.sha256(blob.encode("utf-8")).hexdigest(),
                "payload_bytes": len(blob.encode("utf-8")),
                # 键集是"这一步产出了什么形状的东西"的最小可读证据；
                # 预览截断到 2 KB，避免把大对象整份塞进产物。
                "payload_keys": sorted(str(k) for k in shaped) if isinstance(shaped, Mapping) else [],
                "payload_preview": blob[:2000],
                # ---- 读数键提到顶层（`R1-A2`，真机回放抓出来的）
                #
                # 口径：凡 payload 里以 `_reading` 结尾的键（今天是 `llm_reading`，
                # 角色 D 那三类三态读数都在里面）原样放在这一格，不截断。
                # 为什么必须这样：`payload_preview` 的天花板是 2000 字，而读数的作用
                # 就是被读到 —— 放进预览等于"有时读得到、有时读不到"（真机实测：
                # `t-0056` 那一趟 `payload_keys` 里有 `llm_reading`，而 preview 里没有，
                # 于是"这次到底问没问模型、问成没问成"在盘上读不出来）。
                # 空的时候给 `{}` 而不是省略这个键：省略会让"这一步没有读数"与
                # "这是旧格式的摘要"长得一样（三态纪律：没读到与没有要分得开）。
                "readings": ({str(k): v for k, v in shaped.items()
                              if str(k).endswith("_reading")}
                             if isinstance(shaped, Mapping) else {}),
            }
            target = root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(doc, ensure_ascii=False, sort_keys=True, indent=1, default=str) + "\n",
                              encoding="utf-8")
        except (OSError, TypeError, ValueError) as e:  # noqa: BLE001 - 见 docstring
            self._log(f"任务产出摘要没写成：{type(e).__name__}: {e}", task_id=task_id)
            return ""
        return rel

    def _write_completion_manuscript(self, row: Mapping[str, Any], *, task_id: str, status: str,
                                     outcome: str | None, detail: str, error: str | None,
                                     payload: Any) -> None:
        """动作驱动的一趟结束时，按已发生的事实代写一份交接手稿（`draft/39` §6.6 F1）。

        写什么：任务号 / 角色.动作 / 状态与结论 / 详情 / 产物路径 / 参数摘要；
        `to` = 召唤者（`called_by`），`note` 明写"框架据动作结果派生"。
        纪律三条：
        ① 不重复：同一 `task_id` 下已经有该角色的行（循环驱动那一趟自己填的 `notify`）⇒ 跳过；
        ② 不带走向：留痕失败只进日志，绝不改变任务的终态（与会话记录/产物登记同一条纪律）；
        ③ `cancelled` 不写：没干完的活不是"交接"（这一条由调用方保证）。
        """
        root = getattr(self.store, "root", ".")
        role = str(row.get("role") or "")
        caller = str(row.get("called_by") or "")
        if not role or not caller:
            return
        from . import manuscripts as _MS

        try:
            if _MS.rows_for_task(root, task_id, sender=role):
                return
            action = str(row.get("action") or "")
            verdict = str(outcome or status or "")
            one_line = f"{action}：{verdict}" + (f"（{detail[:60]}）" if detail else "")
            lines = [f"## 这一趟干了什么", "",
                     f"- 任务号：`{task_id}`", f"- 角色.动作：{role}.{action}",
                     f"- 状态：`{status}` / 结论：`{verdict}`"]
            if detail:
                lines.append(f"- 详情：{detail[:400]}")
            if row.get("refusal_reason"):
                lines.append(f"- 拒绝理由：`{row['refusal_reason']}`")
            if error:
                lines.append(f"- 错误：{str(error)[:300]}")
            arts = list(row.get("artifacts") or [])
            if arts:
                lines += ["", "## 产物", ""] + [f"- `{a}`" for a in arts[:10]]
            params = dict(row.get("params") or {})
            if params:
                lines += ["", "## 参数摘要",
                          f"```json\n{json.dumps(params, ensure_ascii=False, default=str)[:600]}\n```"]
            if payload is not None:
                lines += ["", "## 返回值摘要",
                          f"```json\n{json.dumps(payload, ensure_ascii=False, default=str)[:600]}\n```"]
            lines += ["", "## 这一行是怎么来的",
                      "这一趟是**动作驱动**（框架代跑 Python 技能），没有模型收工那一刻，"
                      "所以框架按动作结果派生这一行：内容全部取自 `tasks` 那一行与它的返回值。"]
            _MS.write(root, sender=role, recipient=caller, summary=one_line,
                      body="\n".join(lines) + "\n", task_id=task_id,
                      note="留痕来源：框架据动作结果派生（动作驱动的一趟没有 final 可填）")
        except Exception as e:  # noqa: BLE001 - 留痕不是判据本身，绝不许带走终态
            self._log(f"交接留痕没写成：{type(e).__name__}: {e}", task_id=task_id)

    def finish(
        self,
        task_id: str,
        *,
        status: str,
        outcome: str | None,
        detail: str = "",
        error: str | None = None,
        refusal_reason: str | None = None,
        payload: Any = None,
        artifacts: Sequence[str] = (),
        checked: bool | None = None,
        tokens: int = 0,
        usd: float = 0.0,
    ) -> SummonResult:
        """把任务写成终态。幂等：对已结束的任务再调 ⇒ 零变更（逐字节）。

        实现上不看内存状态，而是在事务里重读那一行：只有当前 `status in ("pending","running")` 才写。为什么不信内存：
        `finish` 的调用方可能有多个（worker 正常返回、dispose 的兜底、deadline 的取消），它们并发跑在不同的线程里；
        靠一个内存标志去串行化，等于把正确性押在"锁的粒度刚好够"上。重读磁盘的代价是一次文件读，收益是"终态先到
        先得"变成结构事实。`status` 与 `outcome` 的合法性由 `schema.Task.validate` 保证（例如 `outcome=refused` 时
        status 必须是 done、cancelled 时 outcome 只能是 cancelled/refused）—— 本方法不替它兜底，非法就抛。
        """
        if status not in TERMINAL_STATUSES:
            raise ValueError(
                f"finish 只接受终态 {TERMINAL_STATUSES}，收到 {status!r}。"
                "中间态由 summon 在开始时写（那时才有 started_at）"
            )
        ended = S.now_iso()
        self._refuse_write_in_snapshot("写终态（finish）")
        with self.store.tx("tasks", actor="conductor", note=f"finish:{status}") as tx:
            row = tx.find("tasks", task_id=task_id)
            if row is None:
                raise ValueError(f"finish 的任务 {task_id!r} 不在 tasks 表里（没有 start 就没有 end）")
            if row.get("status") in TERMINAL_STATUSES:
                # ---- 幂等分支：什么都不做（连事件都不追加）
                existing = dict(row)
                return SummonResult(
                    task_id=task_id, role=str(existing.get("role") or ""),
                    action=str(existing.get("action") or ""),
                    status=str(existing.get("status")), outcome=existing.get("outcome"),
                    refusal_reason=existing.get("refusal_reason"),
                    detail=str(existing.get("detail") or ""), error=existing.get("error"),
                    artifacts=list(existing.get("artifacts") or []),
                    tokens=int(existing.get("tokens") or 0), usd=float(existing.get("usd") or 0.0),
                    depth=int(existing.get("depth") or 1),
                )
            if not row.get("started_at"):
                row["started_at"] = ended
            row["status"] = status
            row["outcome"] = outcome
            row["refusal_reason"] = refusal_reason if outcome == "refused" else None
            row["detail"] = detail
            row["error"] = error
            row["ended_at"] = ended
            row["tokens"] = int(tokens or 0)
            row["usd"] = float(usd or 0.0)
            # ---- D22：`settled_at_parent_exit` 由 `outcome` 派生（一格口径，不加形参）
            #
            # 为什么不给 `finish` 加一个形参：加了就是"调用方可以自己声明这一行是父结算的"，
            # 而它能声明的只有 outcome 那一格 —— 两个入口说同一件事，迟早出现
            # "outcome=cut_off_by_parent 而标记没给"的半笔。`schema.Task.validate`
            # 还把这条等式反向钉住了（标了记就必须是那一档），于是这一行是唯一写点。
            # 位置在最后：新键追加在末尾，`Task.to_dict()` 的键序才对得上（I-9 逐字节）。
            row["settled_at_parent_exit"] = str(outcome or "") == "cut_off_by_parent"
            # ---- R-47：把这次调用的返回值摘要落成产物，并把路径记进 `artifacts`（`tasks` 表不存 payload ⇒
            # `outcome=ok` 无法自证有产出，见 `draft/28` §154 的 S3/R-47）。摘要落
            # `<workspace>/out/tasks/<task_id>.json`（键集 + 规范化哈希 + 截断预览），表里只多一个 artifacts 引用。
            # ---- B12（`draft/41-A`）：已决定的"锁内写盘"例外 —— 这次 I/O 被本事务体内的一次读-判门住
            # （`if row.get("status") in TERMINAL_STATUSES: return`），挪到事务之前会把这个门去掉（后到的写者也能改摘要）。
            # 规则精确化：事务体内不做 I/O 的例外是"这次 I/O 的内容取决于事务内的读-判结果"，判据
            # `tests/test_e13_concurrency.py::test_b12_the_digest_write_stays_inside_the_winner_transaction`
            # （幂等 `finish` 重写摘要 + 台账 append-only ⇒ `closing` 第八格记 unknown、`can_close` 为假，`draft/83` §8 的 T1c）。
            digest_rel = self._write_task_digest(row, payload=payload, status=status,
                                                 outcome=str(outcome) if outcome else None,
                                                 detail=detail)
            if digest_rel:
                artifacts = list(artifacts) + [digest_rel]
            if artifacts:
                # 合并而不是覆盖：`artifacts` 是 append-only 的产出引用。
                # 覆盖会让"分两次登记产出"的第二次抹掉第一次。
                merged = list(row.get("artifacts") or []) + [a for a in artifacts if a]
                row["artifacts"] = S.sorted_unique(merged)
            S.Task(**{k: v for k, v in row.items() if k in S.Task.__dataclass_fields__}).validate()
            tx.upsert("tasks", row, note=f"finish:{status}")
        # ---- 会话记录（按项目存放）：一次终态 = 一条叙事行（`agentflow.sessions`）。
        #
        # 为什么在这里写：`tasks` 是运行时状态，而"这次运行的叙事"（谁在何时对谁说了什么、
        # 产出了什么）以前只活在会话里。落进 `<项目根>/sessions/<会话号>.jsonl` 之后，
        # 每个项目自带一段可读历史，翻 p2-review 不必读全局目录（学 harness 的按工作区存放）。
        # 写失败不改变终态：叙事不是判据本身，原因进日志。
        from . import sessions as _SESS

        sid, sid_why = _session_for_task_end()
        _path, _problem = _SESS.append(getattr(self.store, "root", "."), {
            "kind": "task_end",
            "task_id": task_id,
            "by": str(row.get("called_by") or ""),
            "role": str(row.get("role") or ""),
            "action": str(row.get("action") or ""),
            "status": status,
            "outcome": outcome,
            "refusal_reason": row.get("refusal_reason"),
            "detail": detail[:200],
            "artifacts": list(row.get("artifacts") or []),
            # 取不到 sid 时这一行落在缺省会话里 —— 为什么，写在行上（不许静默）。
            **({"sid_problem": sid_why} if sid_why else {}),
        }, sid=(sid or None))
        if sid_why:
            self._log(f"会话记录落在缺省会话（task_end {task_id}）：{sid_why}",
                      task_id=task_id)
        if _problem:
            self._log(f"会话记录没写成：{_problem}", task_id=task_id)
        # ---- 产物归属登记（`R-52` 余；`draft/28` §153 的 A3/A4）。
        #
        # 为什么在这里而不是每个智能体自己记：`tasks.artifacts` 只回答"这次召唤产出了
        # 哪些引用"，不回答"这个路径归谁产" —— A3（两份断言台账同义不同物）与
        # A4（六个产生验收读数的脚本既非 experiments 行也非 documents 行）都是这个缺口
        # 的形态，而两条都发生在"框架自己落下的产物"上。摘要是这条链路上唯一由框架
        # own 的产物落点，登记它就有了第一条真记录（而不是一个空转的模块）。
        # 纪律与会话记录逐条相同：写失败不改终态，原因进日志。
        if digest_rel:
            from . import artifacts as _ART

            try:
                _ART.record(getattr(self.store, "root", "."), path=digest_rel,
                            producer=str(row.get("role") or "M"), kind="task-result",
                            task_id=task_id, note=f"outcome={outcome}")
            except Exception as e:  # noqa: BLE001 - 登记不是判据本身，不许带走终态
                self._log(f"产物归属没登记成：{type(e).__name__}: {e}", task_id=task_id)
        # ---- 交接留痕：动作驱动的一趟结束。
        #
        # 2026-10-06 改（`draft/39` §6.49 的 D64，用户裁定）：这里不再代写交接手稿。
        # 原来的理由（`draft/39` §6.6 F1）是"动作驱动的趟没有 final 可填，账本会缺这一格"；
        # 真机把它证伪了：T1–T5 五趟的 `manuscripts/handoffs.jsonl` 里 92 / 96 / 118 / 62 / 94
        # 行全是框架派生的模板，`refs` 逐行全空、正文是"从/到/一句话/时间/引用"的填空 ——
        # 用户的原话是「handoffs 里面没有几条有效信息全在强调纪律」。
        # 这类行的信息与 `tasks` / `out/tasks/*.json` 逐字重复 ⇒ 它的落点是那里，不是交接账本。
        # 账本从此只装"模型自己写的、带编号的"交接（派活时带 `notify`、收工时 `final.notify`）；
        # 谁在什么时候把什么交给了谁，靠那些行才查得出来。
        return SummonResult(
            task_id=task_id, role=str(row.get("role") or ""), action=str(row.get("action") or ""),
            status=status, outcome=outcome, refusal_reason=row.get("refusal_reason"),
            detail=detail, error=error, payload=payload, artifacts=list(row.get("artifacts") or []),
            tokens=int(tokens or 0), usd=float(usd or 0.0),
            depth=int(row.get("depth") or 1), checked=checked,
        )

    # ---------------------------------------------------------------- 计划
    def summon_many(self, plan: Sequence[TaskCall], *, token: CancelToken | None = None,
                    probe: Any = None) -> Any:
        """派一批（可抢占）：派完立刻返回 `scheduler.WaveHandle`（D-64）。

        句柄上读得到"已派出的 task_id 列表"与"还在跑的列表"，不必等到全部完成：
        `handle.dispatched()` / `handle.running()` / `handle.settled()` /
        `handle.wait_any(timeout)` / `handle.results()`。

        它与 `run_plan` 是同一台引擎的两种拼法（`run_plan` = 这个句柄的阻塞读法），
        所以"可抢占"与"阻塞"两条路的结果集、顺序、refusal 由构造而相同。
        """
        from . import scheduler as SC

        token = token or self.token
        P.assert_policy_complete(self.policy)
        self._log(f"summon_many：{len(plan)} 个召唤（可抢占），policy={self.policy.to_dict()}")
        # ---- [0b] 停机开关（A / B2，2026-11-15）：这一批的每一项都会在 `summon_begin`
        # 的前半被同一条判据拒掉；这里先读一遍是为了两件事：① 停机时不"顺手认领队列"
        # （认领本身会造出新活）；② 这一条入口也在盘上留下"为什么不派"的读数，
        # 而不是让读日志的人只看每一张票各自被拒。
        _stop = self._dispatch_stop_gate(
            parent_task_id=str(getattr(plan[0], "parent_task_id", "") or "")
            if len(plan) else "")
        if _stop.get("stopped"):
            self._log(f"停机拒派（整批 {len(plan)} 个）：{_stop.get('why')}")
        # S-03 的消费点在这里（不在 `run_plan`）：两条拼法都要"派活时顺手认领队列"，
        # 放在这条唯一的分派入口上，就不会出现"可抢占那条不认领"的半边。
        if not _stop.get("stopped"):
            self._consume_queue_before_dispatch()
        return SC.start_waves(list(plan), conductor=self, policy=self.policy,
                              token=token, probe=probe)

    def run_plan(self, plan: Sequence[TaskCall], *, token: CancelToken | None = None,
                 preemptible: bool = False) -> Any:
        """把一串 call 派出去。两种拼法共用一台引擎，由 `preemptible` 选。

        - `preemptible=False`（默认，改前逐字不变）：等到全部落定，返回
          `list[SummonResult]`。列表长度恒等于 `len(plan)` 且顺序与 plan 一致
          （I-10），并发度不改变结果顺序 —— 这是"可复现"的判据本身。
          禁改区的 `tools/conductor_tools.conductor_summon_many`、`pipeline` /
          `deliver` 与一批判据的替身都走这一档。
        - `preemptible=True`（D-64）：派完立刻返回 `scheduler.WaveHandle`
          （`dispatched()` / `running()` / `settled()` / `wait_any()`），
          父代理不必等到全部完成；`agent_loop._do_summon_many` 走这一档。
          要那一份完整列表时就 `handle.results()`（列表兼容的读法）。

        为什么默认仍是阻塞：把默认改掉等于让所有既有调用方一夜之间从"拿到结果"
        变成"拿到句柄"，而它们多半只是 `for r in res` —— 那种改动不会报错，
        只会在别处变成"结果集空了一半"（实测：`tests/test_scheduler.py` 的两条
        时序判据当场变绿，因为总耗时读成了 0）。要可抢占的地方显式要。

        父是谁（2026-10-20）：plan 里那些 call 自己带着 `parent_task_id`（一件一件
        各归各的父）；而"派活时顺手认领队列"那一步的父不在这里传 —— 它由调用方用
        :func:`consuming_as` 挂上（工具路径已经有 `calling_as`，shape 路径由
        `_do_summon_many` 挂），见 `consume_pending_search_requests` 的最后一段。
        """
        token = token or self.token
        self._log(f"run_plan：{len(plan)} 个召唤"
                  f"{'（可抢占）' if preemptible else '（阻塞）'}，"
                  f"policy={self.policy.to_dict()}")
        handle = self.summon_many(plan, token=token)
        return handle if preemptible else handle.results()

    def _consume_queue_before_dispatch(self) -> None:
        """`run_plan` / `summon_many` / 单件 `summon` 共用的那一步：派活之前扫一次待认领的队列。

        抽成一个方法是因为三条拼法都要它（D-64；R9FIX-D3 补单件那一档）：只给
        `run_plan` 会变成"阻塞式派活顺手认领、可抢占派活不认领" —— 同一件事两条口径；
        只给批量那两档时，主控在初始批次之后改走单件 `conductor.summon`，队列就永远
        没人扫（真机 lp-ball-9 的 `r-000009`）。
        """
        try:
            self.consume_pending_search_requests(trigger="dispatch")
        except Exception as exc:  # noqa: BLE001 - 见上
            self._log(f"派活前扫队失败：{type(exc).__name__}: {exc}")

    # ---------------------------------------------------------------- 停止
    def _signal_stop(self, code: str, detail: str, *, by: str) -> str:
        """喊一次停：设置共享 token，并记下第一次的说明。

        为什么记"第一次"：FC-20 第 2 条（终态先到先得）。后来者不能改写
        "为什么停的" —— 两个答案等于没有答案。`CancelToken.cancel` 自身
        已经是 first-wins，这里再记一份是为了让 dispose 能拿到它写进
        `detail`（token 的 reason 是受控对象，而台账要的是人话）。
        """
        if code not in CANCEL_CODES:
            raise ValueError(f"未知取消原因 {code!r}（受控词表 {CANCEL_CODES}）")
        r = self.token.cancel(code, detail=detail, by=by)
        with self._lock:
            if self._cancel_detail is None:
                self._cancel_detail = detail or detail_of(r)
            return self._cancel_detail

    def cancel(self, reason: str = "user", *, detail: str = "", by: str = "user") -> dict:
        """一个共享 signal 覆盖所有在飞与待启动的任务（FC-20 第 1 条）。

        不逐个取消 —— 逐个会漏。返回此刻的在飞任务列表（供调用方观察，
        但不需要拿它去做什么：取消是协作式的，任务自己会读到同一个 token）。
        """
        text = self._signal_stop(reason, detail, by=by)
        with self._lock:
            inflight = sorted(self._running)
        self._log(f"取消：{text}", inflight=inflight)
        return {"reason": reason, "detail": text, "inflight": inflight}

    def cancel_inflight(self) -> list[str]:
        """给当前在飞任务合成的取消说明的便捷入口（dispose 用）。

        它不逐个写终态：在飞任务的 worker 会在自己的 `except CancelRequested`
        里写下终态（那是"每个 start 恰好一个 end"的正常路径）。
        `dispose()` 只处理没人再管的那些（进程要走了）。
        """
        with self._lock:
            return sorted(self._running)

    # ---------------------------------------------------------------- dispose
    def dispose(self) -> dict:
        """幂等销毁：把仍在 `pending`/`running` 的任务合成 end 事件（`cancelled`）。

        三条纪律全在这里落地：每个 start 有且仅有一个 end —— 即使是被强杀的任务，也必须合成一个 `cancelled` 的 end
        （否则台账里会有永远"在跑"的僵尸）；结果未知 —— `detail` 必须写明"因 dispose 而终止，结果未知"，一个被中途
        砍掉的实验可能已经写了半张表，声称它"失败"是过度声称（设计 §4 第 4 条）；不自动重试 —— 本方法只是写终态。
        幂等：第二次调用时已经没有任何 `pending/running` 的行（第一次全写完了），于是返回
        `{"disposed": ..., "closed": []}` —— 且零字节变更（`finish` 的幂等分支连事件都不追加）。
        ## 只收代理行，不碰板项（2026-10-08 深夜 S1e）：旧实现在这里遍历所有 `pending/running` 的行，而板项行的
        `status` 恰好是 `pending` ⇒ 一次 dispose 会把工作项也写成 `cancelled`。实测
        （`temp/_probe_board_vs_fanout_and_dispose.py`）：那一条板项在 dispose 之后是 `status=cancelled / outcome=cancelled / item_state=queued / item_close=''`，而板面（`board_view` / `board_readings`）只读 `item_state` ⇒ 读的人看不见它
        被取消；同时"在飞"读数从 20 掉回 0（名额被"顺带"还回来了，而不是因为消边）。两套状态机在同一行上互相污染，是
        A1=甲 之后必须避免的形态。所以板项行原样留着（它的收口只由"父决定退役"那一路发生，见 `draft/90` §1.9），并在
        读数里补一格 `board_items_left`："进程要走了，还有几条项没被谁消掉" —— 如实说，不折成"都消了"。
        """
        first = not self._disposed
        self._disposed = True
        text = self._signal_stop("dispose", "因 dispose 而终止，结果未知", by="conductor.dispose")
        closed: list[str] = []
        board_left: list[str] = []
        for row in self._tasks():
            if row.get("status") not in UNFINISHED_STATUSES:
                continue
            tid = str(row["task_id"])
            if self._is_board_item(row):
                # 工作项：不是僵尸（它没有"一次调用"要收口），留给父决定退役那一路
                board_left.append(tid)
                continue
            # ---- D22：`dispose` 写的是"被叫停"那一档，判定交给 `S.child_ending` 一处
            # （改前这里写死 `cancelled`/`cancelled`，`summon_run` 的取消支再写一份）。
            _stop = S.child_ending(stop_code="dispose")
            self.finish(
                tid, status=_stop["status"], outcome=_stop["outcome"],
                detail=f"{text}（dispose 时该任务仍在 {row.get('status')}，结果未知）",
            )
            closed.append(tid)
        # 在飞集合由 worker 的 `finally` 清空；dispose 不替它们清 ——
        # 清了会让一个仍在跑的 worker 在自己写终态时找不到那一行吗？不会：
        # 它写的是磁盘上的行，而这里已经把它写成终态，于是 `finish` 走幂等分支。
        with self._lock:
            still = sorted(self._running)
        self._log(f"dispose：关闭 {len(closed)} 个未完成任务"
                  f"（板项留 {len(board_left)} 条未消，交给退役那一路）", closed=closed)
        return {"disposed_was_first": first, "closed": closed,
                "board_items_left": len(board_left), "still_running": still}

    # ---------------------------------------------------------------- 链式寻址（裁定 2026-10-26）
    def agent_rows(self) -> list[dict]:
        """只数代理行的台账视图（`kind` 非空的是板项，`parent_task_id` 是收件人）。

        父子关系只认代理行：板项行的 `parent_task_id` 口径是"收件人的编号"
        （`draft/84` §T21 附二 / D89），把它算进链里会让一条指导的链条突然经过
        某个收件人 —— 那正是本仓反复治的那类两轴混算。读不成 ⇒ 抛（调用方折三态）。
        """
        return [r for r in self._tasks() if self._is_instance_row(r)]

    def chain_of(self, task_id: Any, *, rows: Sequence[Mapping[str, Any]] | None = None
                 ) -> list[str]:
        """从顶趟那一行到 `task_id` 的绝对编号链（链头是顶趟，链尾是它自己）。

        口径在 :func:`absolute_chain` 一处（纯函数）：本方法只负责把"要读哪些行"定下来
        —— 给了 `rows` 就用它，否则现读代理行。`agenttrace` 那边要按同一口径给每个
        节点带链，读的是同一个函数（不另写第二份追父链的代码）。
        """
        pool = list(rows) if rows is not None else self.agent_rows()
        return absolute_chain(pool, task_id)

    @staticmethod
    def chain_text(chain: Sequence[str]) -> str:
        """绝对编号链的可读写法（`000001->000005->000012`，与写法的分隔符同一处）。"""
        return CHAIN_SEPARATOR.join(str(x) for x in chain)

    def direct_children_text(self, task_id: Any) -> str:
        """某个代理的直接下级（`名册名（编号）` 逐项；没有就一句明确的"没有"）。

        为什么要有这一句：链断了的拒信必须回答"那它的下级到底是谁"（业主逐字：
        「它的直接下级是 …」）—— 只报"这一跳不对"会让读的人还得自己去查一遍。
        """
        rows = list(self.agent_rows())
        index_names: dict[str, str] = {}
        reader = self._roster_reader()
        if reader is not None:
            try:
                index, _bad = reader.roster_index(str(task_id or ""))
            except Exception:  # noqa: BLE001 —— 名册读不成时拒信退回纯编号（不静默丢下级）
                index = []
            index_names = {str(r.get("task_id") or ""): str(r.get("name") or "")
                           for r in index}
        kids = [r for r in rows if str(r.get("parent_task_id") or "") == str(task_id or "")]
        if not kids:
            return "（没有直接下级）"
        parts: list[str] = []
        for r in sorted(kids, key=lambda x: str(x.get("task_id") or "")):
            tid = str(r.get("task_id") or "")
            name = index_names.get(tid, "")
            parts.append(f"{name}（{tid}）" if name else tid)
        return "、".join(parts)

    def _roster_reader(self) -> Any:
        """读名册的那一个句柄（秘书；没有 store / root 就造不出 ⇒ `None`）。

        为什么不把名册读法抄进本模块：名册的三份文件与折叠规则只在 `secretary` 一处
        （`roster_path` / `_fold_roster` / `_fold_index`）；在这里另写一份"读名册"
        迟早与它漂成两套，而两套读法对"谁在册"给出不同答案时没有任何地方会报错。
        """
        if self.store is None:
            return None
        root = str(getattr(self.store, "root", "") or "")
        if not root:
            return None
        from . import secretary as SEC

        try:
            # 带缝的那一支（`for_role_wired`）：裸 `Secretary(...)` 不传 `seam=`，于是
            # 这一位秘书的 `judge()` 永远返回"没有判断面"——名册今天只读，但那是
            # `_secretary` 的三处构造点之一，漏一次缝就是 sylow5 的复发形态。
            return SEC.for_role_wired(S.CONDUCTOR_ROLE, root=root, store=self.store)
        except Exception:  # noqa: BLE001 —— 造不出读侧句柄 ⇒ 调用方按"名册读不成"报未知
            return None

    def resolve_chain(self, written: Any, *, sender_task_id: str = "",
                      sender_role: str = "") -> dict[str, Any]:
        """把收件人写法解析成绝对编号链，并逐跳校验（业主 2026-10-26 裁定）。

        ## 三种写法（都先解析成绝对编号链，读数里一律给 `chain`）

        | 写法 | 例子 | 链怎么来 |
        |---|---|---|
        | 绝对编号链 | `t-000001->t-000005->t-000012` | 逐跳解析，第一跳必须是发送方自己 |
        | 名册名混写 | `M->D1->F2->V1` | 第一跳是发送方；其余按"上一跳的名册"逐跳译码 |
        | 只写链尾 | `t-000012` / `D1` | 由台账的父子关系现算"从发送方到它"那一条链 |

        ## 校验（每一跳都要过，不过就受控拒绝，逐跳点名）

        1. 每一跳必须是上一跳的直接下级（`parent_task_id` 逐跳相等），否则
           `broken_chain`，拒信写「X 不是 Y 的直接下级（它的直接下级是：…）」；
        2. 每一跳都要在册：名册里读得到那一项、且没销号（销号 ⇒ `retired_target`）。
           名册文件根本没写过（这一支从没登记过）记 `unwritten` 并放行 —— 台账才是
           父子关系的权威，"名册没写"不是"不在册"的证据（三态不许折平）；
        3. 链上最多 :data:`CHAIN_MAX_HOPS` 跳（防坏数据把这里变成死循环）。

        ## 返回值（所有分支同一套键，`status` 三档见 `CHAIN_DELIVERY_STATES`）
        `checked` / `status`（`resolved` / `refused` / `unknown`）/ `written` / `tokens` /
        `chain` / `chain_text` / `names` / `roles` / `hops` / `skipped` / `refused` /
        `error` / `callable` / `note`。`hops` 每项：`hop` / `task_id` / `name` / `role` /
        `parent` / `depth` / `roster` / `retired` / `children`（它自己的直接下级，
        拒信要用的就是这一格）。
        """
        out: dict[str, Any] = {
            "checked": False, "status": "unknown", "written": str(written or ""),
            "tokens": [], "chain": [], "chain_text": "", "names": [], "roles": [],
            "hops": [], "skipped": [], "refused": "", "error": "", "callable": "",
            "note": "",
        }

        def _stop(code: str, why: str, *, status: str = "refused") -> dict[str, Any]:
            out.update(status=status, refused=code, error=why)
            return out

        sender = str(sender_task_id or "")
        if not sender:
            return _stop("no_identity",
                         "这一趟没有台账号（`calling_as` 没挂上）⇒ 不知道是谁在发，"
                         "也就拼不出从它到目标的那条链（没查成，不是「链不存在」）",
                         status="unknown")
        try:
            rows = self.agent_rows()
        except Exception as exc:  # noqa: BLE001 —— 读不成是"没查成"
            return _stop("store_unreadable",
                         f"tasks 台账读不成（{type(exc).__name__}: {exc}）⇒ 链没校验",
                         status="unknown")
        by_id = {str(r.get("task_id") or ""): r for r in rows}
        sender_row = by_id.get(sender)
        if sender_row is None:
            return _stop("no_identity",
                         f"台账里没有发送方 {sender} 那一行（代理行）⇒ 拼不出链："
                         "没有自己那一行就说不清「从谁出发」", status="unknown")
        role = str(sender_role or sender_row.get("role") or "")
        tokens, problem = parse_chain_address(written)
        out["tokens"] = tokens
        if problem:
            return _stop("broken_chain", problem)

        reader = self._roster_reader()

        def _index_names(owner: str) -> tuple[dict[str, str], str]:
            """`{名册名: 编号}` 与一句问题（名册读不成时那一句非空）。"""
            if reader is None:
                return {}, "名册读侧造不出来（没有 store 或 root）"
            try:
                index, bad = reader.roster_index(str(owner or ""))
            except Exception as exc:  # noqa: BLE001 —— 读不成是"没查成"
                return {}, f"{owner} 的名册读不成（{type(exc).__name__}: {exc}）"
            if bad:
                return {}, f"{owner} 的名册有 {len(bad)} 行读不出来（{bad[0]}）"
            return ({str(r.get("name") or ""): str(r.get("task_id") or "")
                     for r in index if str(r.get("name") or "")}, "")

        def _as_id(token: str) -> str:
            """这一跳写的是绝对编号吗（编号原样，或裸六位数 `000012` ⇒ `t-000012`）。"""
            tok = str(token or "").strip()
            if tok in by_id:
                return tok
            if tok.isdigit():
                cand = f"t-{S.format_id(int(tok))}"
                if cand in by_id:
                    return cand
            return ""

        # ---- 第一跳：发送方自己，或直接寻址的那个实例
        first = str(tokens[0])
        head = ""
        if _as_id(first):
            head = _as_id(first)
        elif role and first.upper() == role.upper():
            head = sender
        else:
            names, why = _index_names(sender)
            if why:
                return _stop("roster_unreadable", why, status="unknown")
            if first in names and names[first] in by_id:
                head = names[first]
            else:
                out["callable"] = self.direct_children_text(sender)
        if not head:
            return _stop(
                "not_in_roster",
                f"{first or '（空）'} 既不是绝对编号、也不是发送方 {sender}（{role}）"
                f"名册上的名字 ⇒ 受控拒绝：链的第一跳必须是发送方自己（写它的编号或角色），"
                f"或直接写你要发给的那一个实例。发送方的名册上是：{out['callable']}")
        if len(tokens) > 1 and head != sender:
            # 链写了好几个但第一跳不是发送方：补上发送方，让"某一跳不是它的直接下级"
            # 那一档如实报出来（而不是替模型猜它想把谁当链头）。
            out["note"] = (f"链的第一跳是 {head}，不是发送方 {sender} ⇒ 已把 {sender} "
                           "补成链头，再逐跳校验")
            out["callable"] = self.direct_children_text(sender)
        if len(tokens) == 1:
            chain = self.chain_of(head, rows=rows)
            if sender not in chain:
                return _stop(
                    "broken_chain",
                    f"{head} 不在发送方 {sender} 这一支下面（从它往上追不到 {sender}）"
                    f"⇒ 受控拒绝：M 只能沿自己这一棵树往下发。{sender} 的直接下级是："
                    f"{self.direct_children_text(sender)}")
            chain = chain[chain.index(sender):]
            skipped: list[str] = []
        else:
            chain = [sender] if head == sender else [sender, head]
            skipped = []
            owner = chain[-1]
            for pos, token in enumerate(tokens[1:], start=2):
                got = _as_id(token)
                if not got:
                    names, why = _index_names(owner)
                    if why:
                        return _stop("roster_unreadable", why, status="unknown")
                    got = names.get(str(token), "")
                if not got or got not in by_id:
                    skipped = tokens[pos - 1:]
                    return _stop(
                        "not_in_roster",
                        f"链的第 {pos} 跳 {token!r} 在 {owner} 的名册/台账里找不到 ⇒ "
                        f"受控拒绝：{owner} 的直接下级是："
                        f"{self.direct_children_text(owner)}")
                chain.append(got)
                owner = got
        if len(chain) > CHAIN_MAX_HOPS:
            return _stop("broken_chain",
                         f"链有 {len(chain)} 跳（上限 {CHAIN_MAX_HOPS}）⇒ 受控拒绝")
        out["chain"] = chain
        out["chain_text"] = self.chain_text(chain)

        # ---- 逐跳校验（父子关系必须在册；销号与名册状态逐跳点名）
        names: list[str] = []
        roles: list[str] = []
        hops: list[dict[str, Any]] = []
        for i, tid in enumerate(chain):
            row = by_id.get(tid) or {}
            parent = str(row.get("parent_task_id") or "")
            name = ""
            if i > 0:
                prev = chain[i - 1]
                names_prev, why = _index_names(prev)
                if why:
                    return _stop("roster_unreadable", why, status="unknown")
                if parent != prev:
                    out["skipped"] = chain[i:]
                    return _stop(
                        "broken_chain",
                        f"{tid} 不是 {prev} 的直接下级（它的直接下级是："
                        f"{self.direct_children_text(prev)}）")
                name = next((n for n, t in names_prev.items() if t == tid), "")
                roster_rows, bad = ([], [])
                if reader is not None:
                    try:
                        roster_rows, bad = reader.roster_rows(prev)
                    except Exception as exc:  # noqa: BLE001 —— 读不成是"没查成"
                        return _stop("roster_unreadable",
                                     f"{prev} 的名册读不成（{type(exc).__name__}: {exc}）",
                                     status="unknown")
                if bad:
                    return _stop("roster_unreadable",
                                 f"{prev} 的名册有 {len(bad)} 行读不出来（{bad[0]}）",
                                 status="unknown")
                mine = next((r for r in roster_rows
                             if str(r.get("task_id") or "") == tid), None)
                if mine is None:
                    roster_state = "unwritten" if not roster_rows else "not_registered"
                else:
                    roster_state = "registered"
                    retired = bool(mine.get("retired"))
                    if retired:
                        out["skipped"] = chain[i:]
                        tail = i == len(chain) - 1
                        return _stop(
                            "retired_target",
                            (f"{tid}（{name or '无名册名'}）已销号 ⇒ 链尾不能再收消息"
                             "（业主 B1：名字永久不复用）") if tail else
                            (f"{tid}（{name or '无名册名'}）已销号 ⇒ 这一跳已经退场、"
                             "没有秘书能继续转发，链断了"))
                if roster_state == "not_registered":
                    out["skipped"] = chain[i:]
                    label = f"{name}（{tid}）" if name else tid
                    return _stop(
                        "not_in_roster",
                        f"{label} 不在 {prev} 的名册里（{prev} 名册上在册的是："
                        f"{self.direct_children_text(prev)}）")
            else:
                roster_state = "self"
                if row.get("parent_task_id"):
                    names_up, _why_up = _index_names(parent)
                    name = next((n for n, t in names_up.items() if t == tid), "")
            names.append(name)
            roles.append(str(row.get("role") or ""))
            hops.append({"hop": i + 1, "task_id": tid, "name": name,
                         "role": str(row.get("role") or ""), "parent": parent,
                         "depth": int(row.get("depth") or 0),
                         "roster": roster_state, "retired": False,
                         "children": self.direct_children_text(tid) if row else ""})
        out.update(checked=True, status="resolved", names=names, roles=roles, hops=hops,
                   error="")
        out["note"] = out["note"] or (f"{len(chain)} 跳，链尾是 "
                                      f"{names[-1] + '（' + chain[-1] + '）' if names[-1] else chain[-1]}")
        return out

    # ---------------------------------------------------------------- 可读视图
    def tree(self, root_task_id: str | None = None) -> list[dict]:
        """父子链视图（从 `tasks` 表读出来，不碰内存状态）。

        为什么从表读：跨会话恢复之后内存里什么都没有，而表才是权威。
        返回的是扁平的行列表（每行带 `children`），而不是嵌套结构 ——
        台账天然是扁平的，"嵌套"只是展示层的事，库不应该替展示层做决定。

        ## 两轴分家（D9）：`children` 只数实例行，`items` 才是我名下未消的板项
        `tasks` 从业主 A1=甲 起装两类行：实例行（`kind == ""`，一个 agent 一行）与
        板项行（`kind` 非空：`message` / `notice` / `report` / `delegation`）。板项行的
        `parent_task_id` 口径是"收件人的编号"（`draft/84` §T21 附二 / D89），于是按
        `parent_task_id` 建树而不看出身，一条"某子代理已收工"的 `notice` 就会被当成
        一个子代理（实测：父名下 20 条 `notice` ⇒ 父的 `children` 报 20，而它一个子
        代理都没有）。同仓另外三处权威读侧（`_children_of` / `active_children` /
        `stats`）都带这一条出身过滤，只有本方法漏了 —— 这里补上。

        "我名下还有几条没消"这个读数因此另立一格 `items`（条数）+ `item_ids`（点名），
        判据与 `open_items_of` 同一处（`open_items_by_parent`）。为什么不把它折进
        `children`：那是两轴（实例轴 + 工作项轴），`draft/84` §T2 的消边谓词要两者
        一起看，合成一格就再也分不开"没子代理"与"有 20 条没消的通报"。

        ## 每一行都带绝对编号链（业主 2026-10-26）
        两格 `chain`（从顶趟那一行到这个节点自己的绝对编号列表）与 `chain_text`
        （`000001->000005->000012`）。链由 `chain_of` 现算，不读缓存：深层节点
        不许只给"父是谁"让调用方自己拼 —— 拼错一个号，消息就会投到另一支。
        """
        # 只拿实例行建树：板项行的 `parent_task_id` 是收件人，不是父代理（D9）。
        # 整表只读一次（2026-10-27）：改前这里读一次、`open_items_by_parent()` 再读一次、
        # 有 `root_task_id` 时 `_task(root)` 又读一次 = 一拍最多 3 次整表反序列化。
        all_rows = self._tasks()
        rows = [r for r in all_rows if self._is_instance_row(r)]
        open_by_parent = self.open_items_by_parent(all_rows)
        by_parent: dict[str | None, list[dict]] = {}
        for r in rows:
            by_parent.setdefault(r.get("parent_task_id"), []).append(r)
        # 每一行的绝对编号链只算一次（业主 2026-10-26：轮查读数必须给链，深层节点
        # 不许只给"父是谁"让调用方自己拼）。
        chains = {str(r.get("task_id") or ""): self.chain_of(str(r.get("task_id") or ""),
                                                             rows=rows)
                  for r in rows}

        def chain_cell(tid: Any) -> dict[str, Any]:
            """这一行的 `chain` 与 `chain_text`（从顶趟到它自己的绝对编号链）。"""
            got = list(chains.get(str(tid or ""), ()))
            return {"chain": got, "chain_text": self.chain_text(got)}

        out: list[dict] = []

        def items_cell(tid: Any) -> dict[str, Any]:
            open_rows = open_by_parent.get(str(tid or ""), [])
            return {"items": len(open_rows),
                    "item_ids": sorted(str(x.get("task_id") or "") for x in open_rows)}

        def walk(tid: str | None, level: int) -> None:
            for r in sorted(by_parent.get(tid, []), key=lambda x: str(x.get("task_id"))):
                kids = by_parent.get(r.get("task_id"), [])
                out.append({
                    "task_id": r.get("task_id"), "role": r.get("role"), "action": r.get("action"),
                    "status": r.get("status"), "outcome": r.get("outcome"),
                    "depth": r.get("depth"), "level": level,
                    "called_by": r.get("called_by"), "parent_task_id": r.get("parent_task_id"),
                    "children": [k.get("task_id") for k in kids],
                    **items_cell(r.get("task_id")),
                    **chain_cell(r.get("task_id")),
                    "detail": r.get("detail"),
                })
                walk(r.get("task_id"), level + 1)

        if root_task_id is not None:
            # 在同一份快照里找根（2026-10-27；改前是 `self._task(...)` = 第三次整表读）。
            root = next((r for r in all_rows if r.get("task_id") == root_task_id), None)
            if root is None:
                raise ValueError(f"tree(root_task_id={root_task_id!r})：台账里没有这个任务")
            # 从 root 自己开始（而不是它的子树）—— "这棵树的根"包含根。
            out.append({
                "task_id": root.get("task_id"), "role": root.get("role"), "action": root.get("action"),
                "status": root.get("status"), "outcome": root.get("outcome"),
                "depth": root.get("depth"), "level": 0, "called_by": root.get("called_by"),
                "parent_task_id": root.get("parent_task_id"),
                "children": [k.get("task_id") for k in by_parent.get(root_task_id, [])],
                **items_cell(root_task_id),
                **chain_cell(root_task_id),
                "detail": root.get("detail"),
            })
            walk(root_task_id, 1)
        else:
            walk(None, 0)
        return out

    def stats(self) -> dict:
        """台账的可读统计。每一项都从表里数出来，不缓存。

        为什么 `unknown_outcome` 单列：它不是"失败"，是"我们不知道"
        （例：dispose 的取消）。把它并进 `cancelled` 的计数里，
        "有几件事我们其实不知道结果"这个数字就永远看不见了。

        只数实例行（`kind` 为空；业主 2026-10-08 裁 A1=甲之后，板项与实例行同表）：
        `total` / `by_role` / `by_status` 这些格问的是"派了几件活、跑成什么样"，
        板项（终态回报的 `notice`、传话的 `message`）不属于这个问题 ——
        混进来会让"顶趟恰好一行 M"这类读数凭空多一条（实测：加板之后
        `tests/test_agent_loop.py` 的 F1 判据当场红过）。板自己的读数在 `board` 那一格里。
        """
        rows = [r for r in self._tasks() if self._is_instance_row(r)]
        # 视图与权威账对账（以账为准）：`stats()` 是唯一读这个视图的地方，
        # 每次问都先对齐 —— 这样"本次 run 花了多少"不会因为某条路径漏推视图
        # 而与台账给出不同的数字。
        #
        # `G-8`：对账的来源必须是权威账（`usage_ledger`），不是 `tasks` 求和。
        # `tasks.tokens/usd` 是派生列，而"派生"不等于"随时同步"：
        # 崩溃窗口（账已落、写回没做）里它停在旧值 —— 拿它去 reconcile
        # 等于"把视图对齐到另一份可能过期的派生数据"，而
        # `MemoryBudgetTracker` 的契约逐字是"以账为准"（见它的 docstring
        # 与 `reconcile()` 的说明）。`TokenMeter.spent()` 每次都从
        # `usage_ledger` 现读，是账本口径的唯一读取口。
        ledger = self.meter.spent()
        self.budget.reconcile(tokens=int(ledger["tokens"]),
                              usd=round(float(ledger["usd"]), 6))
        by_role: dict[str, int] = {}
        by_outcome: dict[str, int] = {}
        by_status: dict[str, int] = {}
        by_depth: dict[str, int] = {}
        refused_reasons: dict[str, int] = {}
        # 五行计数 + `unknown_outcome` + `top_level_runs` 一趟数完（原先这张表被走了
        # 三遍：主循环一遍、`unknown` 一遍、`top_level_runs` 一遍）。三个读数的判据一个
        # 字没改：`by_role` / `by_status` / `by_depth` 按 `str(...)` 记账（`None` ⇒ "None"），
        # `unknown_outcome` 认"`status` 原值等于 cancelled 且 detail 里写着结果未知"，
        # `top_level_runs` 认"`action` 转成字符串后等于 run"。
        unknown = 0
        top_level_runs = 0
        for r in rows:
            role_key = str(r.get("role"))
            by_role[role_key] = by_role.get(role_key, 0) + 1
            status_key = str(r.get("status"))
            by_status[status_key] = by_status.get(status_key, 0) + 1
            oc = r.get("outcome")
            key = str(oc) if oc is not None else "<未结束>"
            by_outcome[key] = by_outcome.get(key, 0) + 1
            depth_key = str(r.get("depth"))
            by_depth[depth_key] = by_depth.get(depth_key, 0) + 1
            if r.get("refusal_reason"):
                rr = str(r["refusal_reason"])
                refused_reasons[rr] = refused_reasons.get(rr, 0) + 1
            if r.get("status") == "cancelled" and "结果未知" in str(r.get("detail") or ""):
                unknown += 1
            if str(r.get("action") or "") == "run":
                top_level_runs += 1
        return {
            "total": len(rows),
            "by_role": by_role,
            "by_status": by_status,
            "by_outcome": by_outcome,
            "by_depth": by_depth,
            "refusal_reasons": refused_reasons,
            "unknown_outcome": unknown,
            "peak_running": self.peak_running,
            "started_total": self._started_total,
            # ---- 两套口径并存，必须写明（F1 之后它们不再相等）
            #
            # F1 之后 `tasks` 里多了顶趟行（`action="run"`，由 `open_top_level_run` 开、
            # `finish_top_level_run` 收）。于是这一屏上：
            #
            # - `total` / `by_role` / `by_status` / `by_outcome` / `by_depth`
            #   = 台账全量（上面 `rows = self._tasks()` ⇒ 含顶趟行）；
            # - `started_total` / `peak_running` = 本实例发起的召唤数（只在 `summon`
            #   里自增；顶趟不占并发/总量配额，所以它不进这两个数）。
            #
            # 两个数不一样不是 bug，是两件事：一个问"台账里有什么"，一个问"我派了几次活"。
            # 但不写清就会变成"同一屏里两个读数各说一件事"——本项目最忌的形态，
            # 所以把口径连同 `top_level_runs` 这个分类计数一起给出来（读者不必自己减）。
            "calibers": {
                "total / by_*": "tasks 台账全量（含顶趟行 action=run）",
                "started_total / peak_running": "本实例发起的召唤数（顶趟不计）",
            },
            "top_level_runs": top_level_runs,
            # 板自己的读数（业主 2026-10-08 裁 A1=甲、T16）：既有那些格只数实例行，
            # 板项在这里单列 —— "派了几件活"与"板上还挂着什么"是两个问题，不许混。
            "board": self.board_readings(),
            # S-03：两处消费点各消费了几条（"派活时 N / 收尾时 M"）——让"即"的折扣可度量。
            "consume_counts": dict(getattr(self, "_consume_counts", {}) or {}),
            # 队列认领那一路名册登记的失败清单（2026-10-27 接线）：改前它只写进日志，
            # 而日志没人逐行读 —— `_consume_counts` 有读数格、它的兄弟格却没有，是漏，不是取舍。
            "consume_roster_problems": list(getattr(self, "_consume_roster_problems", []) or []),
            # 最近一次派活前摆出来的"同 key 既有终态行"（2026-10-27 接线）：它的 docstring
            # 一直写着"读数的第二个落点：日志之外"，但改前全仓没有一个读者 —— 于是
            # "派活时看见了几条同 key 的终态行"这件事只在日志里有，读数里没有。
            "last_duplicates": [dict(x) for x in (getattr(self, "_last_duplicates", []) or [])],
            # 职责 3（闭环提醒）：最近一次顶趟收尾时的读数（谁没接手 / 谁没反馈 / 各几条）。
            # 它是一格读数，不是门（`draft/55` §4：秘书不新增机器判据）。
            "closure_reminders": dict(getattr(self, "_closure_reading", {}) or {}),
            "budget": self.budget.state(self.policy),
            "policy": self.policy.to_dict(),
            "disposed": self._disposed,
            "deadline_hit": self.deadline_hit,
        }

    # ---------------------------------------------------------------- 自检
    def task_issues(self) -> list[C.TaskIssue]:
        """台账问题的结构化视图（带机器可读的码）。

        判据只有一份：`capabilities.audit_task_ledger`。为什么收在那里 ——
        `verify_all`（全库离线审计）与 `verify_tasks`（刚跑完一次 run 的即时自检）
        问的是同一个问题，两处各写一份判据必然漂移，而漂移的形态是
        "其中一处永远说没问题"。`tests/test_conductor.py::test_task_ledger_audit_matches_verify_all`
        钉住两者的码集合相等（`DEVELOPMENT.md` §10 点名的那条）。
        """
        with self._lock:
            in_flight = frozenset(self._running)
        return C.audit_task_ledger(self._tasks(), store=self.store, in_flight=in_flight)

    def verify_tasks(self) -> list[str]:
        """本模块的不变式自检：返回人可读的问题说明列表（空 = 自洽）。

        与 `verify.py` 的分工：`verify_all` 是全库审计、由 CLI 跑；
        这里回答"我刚跑完一次 run，台账是否自洽"，不需要跑全库。
        判据不在这里 —— 它来自 `capabilities.audit_task_ledger`（唯一实现，
        见 :meth:`task_issues`）。

        任何一条不成立就返回说明列表（不抛）：调用方决定要不要当成失败
        （"拒绝 ≠ 失败"的同一条纪律：把"台账有可疑行"变成异常，会逼调用方
        用 try/except 包住它，而 try/except 会连真正的编程错误一起吞掉）。
        """
        return [
            # 码在前、行号在后：`verify.Issue` 也是这个形态，便于机器比对与人工定位
            f"{i.task_id}: [{i.code}] {i.message}" for i in self.task_issues()
        ]
#: 本角色的声明（`goal-7f5116c1` M3）。
#:
#: 真身在 `specs/m.py` —— 那里就是权限面的落点（`.noai-paths` 保护它）。
#: 这里只做再导出：`agentspec.builtin_registry()`、判据与调用方都按 `mod.SPEC` 取，
#: 于是"角色模块里能读到自己的声明"这件事仍然成立，而不会多出第二份拷贝。
from .specs.m import SPEC  # noqa: E402,F401




# ---------------------------------------------------------------- S-02 的读数


#: `uncalled_actions_reading` 的口径（2026-10-02 主控现场更正，逐字的意思）：
#: 它数的是 `store.rows("tasks")` —— tasks 台账的落盘行，而不是全量召唤流水。
#: 权威读数是 `sessions/*.jsonl` 里的 `events`（重放能重建 tasks）。实测：某个工作区的
#: `tasks.json` 只有 2 行，而同目录的 `events.jsonl` 有 1161 行 ⇒ 两个口径的数
#: 差得很远，谁也不是"数据缩水"。所以这条读数把自己的口径印在返回里：
#: 凡"数召唤行数"的读数都必须自带口径，跨口径比大小是错的那种用法。
_UNCALLED_ACTIONS_CALIBER = (
    "按 store.rows(\"tasks\") 数（tasks 台账的落盘行，可能只是缓存/最近一次落盘）；"
    "权威读数是 sessions/*.jsonl 的 events 重放 —— 两个口径的数不许互相比"
)


def uncalled_actions_reading(store: Any) -> dict:
    """S-02 的读数：声明了、但一条召唤行都没有的动作（只读，不加闸门）。

    ## 它回答的那个问题（`44 S-02`）：D 的五个核心动作（`assess`/`submit_gaps`/`adjudicate`/`trace_question`/
    `trace_l3`）都在声明表里、各有 handler，而真机 4127 行 `tasks` 里一次都没被召唤过。"声明了但没人召唤过"这件事
    今天没有任何读数在说：`Conductor.stats()` 只有 `by_role`/`by_status`/`by_outcome`/`by_depth`，没有
    `by_action` —— 于是真机 0 次调用只能在临时探针里看见。这是一条纯读数：它服务的是 #1（无意义/重复的委托）的
    可见性，不是判决 —— "该不该派这个动作"归秘书（`J-37`/`J-40`：切勿全写死成机器判据），所以这里不接 handler、
    不进工具面、不加任何闸门。
    ## 口径（2026-10-02 主控现场更正）：数的是 `store.rows("tasks")`（台账的落盘行），不是全量召唤流水；权威读数
    是 `sessions/*.jsonl` 里的 `events` 重放。返回里的 `caliber` 逐字写这件事 —— 跨口径比大小是错的用法（实测
    某个工作区 `tasks.json` 2 行、同目录 `events.jsonl` 1161 行，两者谁也不是"数据缩水"）。
    ## 三态：`checked=True`（声明表与 `tasks` 都读到了，`uncalled` 是做差的结果）；`checked=False` + `reason`
    （读不到 ⇒ 不许折成"全都没被调用"—— 那是一个很强的结论，只有真读到两边才配下）。`called` 是"至少有一条召唤
    行"的那个集合（`refused` 也算 —— 它是一次真的提出过的召唤）；`declared_total` / `called_total` 给分母。
    """
    try:
        rows = list(store.rows("tasks"))
    except Exception as exc:  # noqa: BLE001 - 读不出来如实报
        return {"checked": False, "reason": f"tasks 读不出来：{type(exc).__name__}: {exc}",
                "uncalled": [], "declared_total": 0, "called_total": 0,
                "caliber": _UNCALLED_ACTIONS_CALIBER}
    try:
        from . import capabilities as _C

        table = dict(getattr(_C, "CAPABILITIES", None) or {})
    except Exception as exc:  # noqa: BLE001 - 同上
        return {"checked": False, "reason": f"声明表读不出来：{type(exc).__name__}: {exc}",
                "uncalled": [], "declared_total": 0, "called_total": 0,
                "caliber": _UNCALLED_ACTIONS_CALIBER}
    declared = {(str(role), str(getattr(spec, "action", "") or ""))
                for role, specs in table.items() for spec in specs}
    declared.discard(("", ""))
    called = {(str(r.get("role") or ""), str(r.get("action") or "")) for r in rows}
    uncalled = sorted(p for p in declared - called if p[1])
    return {
        "checked": True,
        "reason": "",
        "caliber": _UNCALLED_ACTIONS_CALIBER,
        "uncalled": [{"role": role, "action": action} for role, action in uncalled],
        "count": len(uncalled),
        "declared_total": len(declared),
        "called_total": len(declared & called),
        "note": ("这条读数只回答\"声明了但没被召唤过\"：为什么没人派、该不该派，"
                 "归秘书判断（`J-37`）；本读数不构成任何门的通过条件。"),
    }

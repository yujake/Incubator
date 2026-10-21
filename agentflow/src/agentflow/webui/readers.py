# -- coding: utf-8 --
"""只读面的读模型（`draft/73` §2.3 的本体；属于 B 线那一批）。

## 这一层是什么

六个面的适配器，一个面一个函数：只读、三态、不吞异常。

| 面 | 函数 | 端点（`draft/75 §1.1` 的 C1 第 1–6 行） | 读什么（既有实现，不另写一份） |
|---|---|---|---|
| 快照 | :func:`state_face` | `GET /api/state` | `webui.state.snapshot()`（键集合一字不改） |
| 一趟详情 | :func:`run_view` | `GET /api/run/{sid}` | `sessions.read_session` + `runs/agent-<角色>-<sid>.json` |
| 逐条事件 | :func:`run_events` | `GET /api/run/{sid}/events` | `sessions.read_session`（只读；不另写第二份解析） |
| 证据链 | :func:`evidence_chain` | `GET /api/evidence` | `store.rows(...)` 七张表 + `verifications.list_verifications` |
| 产物 | :func:`artifacts_face` | `GET /api/artifacts` | `artifacts.read_ledger` · `manuscripts.read_rows` · `closing` 的验收行 · `secretary.decisions_path` · `runflow.ARTIFACTS` |
| 收工门 | :func:`acceptance_face` | `GET /api/acceptance` | `reviewaccept.check_review` |
| 本机 | :func:`machine_face` | `GET /api/machine` | `toolchain.toolchain_report` + `settings.load_settings` |

## 逐条事件的编号口径（题 T2-a；`tests/test_webui_readers.py` 逐条钉着它）

`run_events` 的 `EventRow.index` 与 `webui.state.snapshot()` 里 `runs[].start_index` /
`end_index` 是同一套编号：都是"这一段会话里解析成功的事件行在
`sessions.read_session()` 返回的那个列表里的下标，0 起"（`webui/state.py` 的 `_scan`
与 `sessions.runs_in_session` 都是对同一个列表 `enumerate`，坏行不占位）。于是
`start_index <= index <= end_index` 的那些行正好是那一趟的事件 —— `index` 不是文件行号，
也不是 `EventRow` 自己的序号。

`from_index` / `to_index` 是这一次返回的游标区间（左闭右开）：`from_index` 等于钳过的
`since_index`，`to_index` 等于 `from_index + len(events)`，于是
`to_index - from_index == len(events)`、`truncated == (to_index < total)`，
而下一次续取的 `since_index` 直接填 `to_index` 就行。到末尾之后（`since_index >= total`）
回一页空的（`from_index == to_index == total`、`truncated=false`），那不是错误。

## 三态纪律（裁定 N1 + `draft/74` 的证据规则）

每一面都带 `tri` 与 `reason`，取值是 `computed` / `unreadable` / `not_applicable`
（`reviewaccept` 那一套词表；「交付说明」那一格用 `ok`/`missing`/`unknown`，两套
不许互相顶替）：

- 数据源不可读（无效 JSON、无权限、把目录当文件读）⇒ `tri="unreadable"` + `reason`；
- 数据源不在盘上（还没写过）⇒ 计数栏写 `None`、`tri="not_applicable"`
  + 一句"还没写过"的 `reason`。绝不把它折成 `0` 或空数组或 `false`；
- 读到了 ⇒ `tri="computed"`，计数栏是真数字（可能是 0，那是"读到了，里面是 0 行"）。

为什么 `not_applicable` 不写成 `unknown`：`Tri` 的三个词里没有 `unknown`，
而"这个工作区还没有那一族数据"正是 `not_applicable` 的字面意思 —— 用 `reason`
补上"是还没写过、不是没查成"。`readers` 的直属判据
（`tests/test_webui_readers.py`）逐面钉这三档。

## 为什么 JSONL 一律走 `read_jsonl_state`

`jsonlfile.read_jsonl` 把"文件不在"与"文件在但读不出来"折成同一个二元组
（`([], [])` 与 `([], [problem])` 只差第二栏）。三态纪律要的正是这两档分开，
所以本模块用 `read_jsonl_state`（`:58`，四态 `absent` / `empty` / `ok` / `unreadable`）
再映射到本模块的三态。这一条是这一层存在的理由之一。

## 接缝（`draft/78 §3`）：本模块自己声明自己那一份

- :data:`ROUTES` —— 本模块挂到总路由表上的只读端点。`webui/routes.py` 的总表是
  `自有 + READER_ROUTES + WRITE_ROUTES` 拼出来的，所以这里加一条端点不需要去改
  A 线的文件。
- :func:`type_decls` —— 本模块那一段 TS 声明文本，被
  `agentflow/web/emit_types.py` 拼进 `ui/src/types.ts`。
- :data:`MISSING_TYPES` —— 本模块还欠的接口与理由。补完一个就删掉它那一行。

处理器的落点（A 线已落地的那条接缝）：`routes.py` 的第三格是处理器名字，
而 `WebHandler` 住在 A 线的 `webui/server.py` 里（B 线不许碰）。所以六个面的 HTTP
外壳写成模块级函数（签名 `(handler, params, query)`，`handler` 是 `WebHandler` 实例），
在文件末登记进 :data:`HANDLERS`（`{名字: 可调用对象}`）—— `routes.handler_for(name)`
按名字来取，`server._invoke()` 先找 `WebHandler` 的方法、再找子表。
于是"加一个端点"这件事只发生在 B 线自己的文件里，`server.py` 一个字节都不用动。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

from .. import sessions as SS
from ..jsonlfile import read_jsonl_state

__all__ = [
    "CHECKED_TYPES", "EVENTS_LIMIT_DEFAULT", "EVENTS_LIMIT_MAX", "HANDLERS",
    "LEDGER_EVENT_SCAN_BYTES", "LEDGER_EVENT_SCAN_KINDS", "LEDGER_EVENT_SCAN_SESSIONS",
    "LEDGER_ROLE_FIELDS", "LEDGER_TASK_TRI_EVENT", "LEDGER_TASK_TRI_MISSING",
    "MISSING_TYPES", "PENDING_ENDPOINTS", "ROUTES", "ROSTER_INBOX_ITEMS",
    "ROSTER_NODES_MAX",
    "RUN_ROW_KEYS", "UNCHECKED_TYPES", "acceptance_face", "artifacts_face",
    "chat_face", "evidence_chain", "handle_acceptance", "handle_artifacts",
    "handle_chat", "handle_evidence",
    "handle_machine", "handle_roster", "handle_run_events", "handle_run_view",
    "handle_state",
    "machine_face", "roster_face", "run_events", "run_products", "run_view",
    "state_face",
    "ts_fields", "type_decls",
]

# ====================================================================== 三态词表
#: `Tri` 的三个取值（`reviewaccept` 那一套；与 `ok/missing/unknown` 不许互相顶替）。
TRI_COMPUTED = "computed"
TRI_UNREADABLE = "unreadable"
TRI_NOT_APPLICABLE = "not_applicable"

#: 六个面（外加 `/api/state` 与 `/api/stream`）挂到总路由表上的端点。第三个元素是 B 线里
#: 那个处理器的名字（`routes.handler_for` 会去 `HANDLERS` 里按这个名字取它）。
#:
#: `/api/stream` 那一条的处理器真身在 `webui/sse.py`（`handle_stream`）—— 它登记在
#: 这张表里的理由是一条硬事实：`routes.py` 的总表是 `自有 + READER_ROUTES +
#: WRITE_ROUTES` 三个子表拼出来的，而 `sse.py` 不是其中任何一个子表的主人；
#: 把表项写进 sse.py 会得到一个"声明了却永远进不了总表"的端点。所以 B 线对外只有
#: 一张子表，它住在 `readers.py` 里：表项按"哪个端点"列，处理器按"它住在哪个
#: 模块"实现（两张 `HANDLERS` 字典由 `routes.handler_for` 一起查）。
#:
#: `/api/state` 那一条是裁定 2b 从 A 线的 `_OWN` 迁过来的（A 同时删掉自己那一行、
#: 并把 `WebHandler.handle_state` 退成转发）。迁的是路由的归属，不是公开面：
#: `handle_state` 回的还是 `snapshot()` 那张裸快照，与迁之前逐键同值 ——
#: 所以交接那一刻（两边都还在表里）跑起来的 HTTP 行为逐字节相同。
ROUTES: tuple[tuple[str, str, str], ...] = (
    ("GET", "/api/state", "handle_state"),
    ("GET", "/api/run/{sid}", "handle_run_view"),
    # 题 T2-a：一趟的逐条事件（旧壳那张"逐条事件卡片"退场之后唯一能给它的只读面）。
    # `{sid}` 只匹配一段路径，所以它与上面那条 `/api/run/{sid}` 不会互相吃掉。
    ("GET", "/api/run/{sid}/events", "handle_run_events"),
    ("GET", "/api/evidence", "handle_evidence"),
    ("GET", "/api/artifacts", "handle_artifacts"),
    ("GET", "/api/acceptance", "handle_acceptance"),
    ("GET", "/api/machine", "handle_machine"),
    # 业主 2026-10-12 的两条：预算窗口（②）与多智能体监控（①）。
    # 它们与六个面同族（读盘现算、三态、不缓存），所以落在同一张子表里。
    ("GET", "/api/budget", "handle_budget_view"),
    ("GET", "/api/live", "handle_live"),
    ("GET", "/api/usage", "handle_usage"),
    ("GET", "/api/status-reports", "handle_status_reports"),
    # 业主 2026-10-13 的对话框：一段会话里"用户 ↔ 主控"的来回（对话页那一面）。
    ("GET", "/api/chat", "handle_chat"),
    # 2026-10-21（业主的「名册监视」）：当前工作区的整棵名册树 —— 父是谁、子有哪些、
    # 每个成员的绝对编号／名册名／角色／深度，外加"收件箱积压"那一格。
    # 只读一条：这个端点的消费者是只读面板，写面为零（表里没有与它配对的 POST，
    # 判据 `tests/test_webui_roster_panel.py` 的第三条就钉着这一条）。
    ("GET", "/api/roster", "handle_roster"),
    # 真身在 `webui/sse.py`（`GET /api/stream` 的推送流）。
    ("GET", "/api/stream", "handle_stream"),
)

#: 处理器的落点（`draft/78 §3` 的接缝之一）：键 = `ROUTES` 第三元素，
#: 值 = `(handler, params, query)` 签名的函数，`handler` 是 `WebHandler` 实例。
#: 有了它，B 线加端点只改这个文件，不必碰 A 线的 `server.py`（也不用往
#: `WebHandler` 上猴补丁）。`webui/routes.py:handler_for()` 会来读它。
#:
#: `handle_stream` 的真身在 `sse.py`（那里还管广播器、心跳、续传），这里登记的是
#: 同一个可调用对象 —— 一张表里读得出"哪些端点由 B 线实现"，实现按模块分居。
HANDLERS: dict[str, Any] = {}


#: 契约判据 C 的两份登记：本模块声明、而且在夹具上真读得出来的接口写进
#: `CHECKED_TYPES`（判据会逐键比对）；声明了但还没有读数的写进 `UNCHECKED_TYPES`
#: （`{接口名: 理由}`）。两份都住在本模块里 ⇒ B 线补一个接口时只删自己文件里的一行。
#:
#: 这一份是 B1 落地后的实况（夹具见 `tests/conftest.py` 的 `make_artifacts_sample`）。
CHECKED_TYPES: tuple[str, ...] = (
    "RunProduct", "CheckpointView", "CheckpointSpendView", "CheckpointCacheView",
    "ReportReadingView",
    "RunView", "EventRow", "RunEventsView",
    "EvidenceView", "ArtifactsView", "AcceptanceView", "SettingsReading",
    "MachineView", "ArtifactRow", "LedgerVerifyRow", "HandoffRow", "SecretaryDecision",
    "AcceptanceCheck", "ReportStyle", "TaskRow", "VerificationRow",
    # 2026-10-12（业主的预算窗口与监控）：这四面的顶层键在任何工作区上都在
    # （寄存器缺席、账本为空、没有进程都只是三态里的另一档，不是"读不出键"），
    # 所以它们进受核对名单；行一级的类型见 `UNCHECKED_TYPES` 的理由。
    "BudgetView", "LiveView", "UsageView", "StatusReportsView",
    # 2026-10-13（业主的对话框）：`ChatView` 的键在任何工作区上都在（"还没有会话"
    # 与"没查成"都只是三态里的另一档）；夹具那一段会话里有主控的 run_start 与一条
    # 提问，所以行一级的 `ChatLine` / `ChatSession` 也读得出键。
    "ChatView", "ChatLine", "ChatSession", "ChatOption",
    # 2026-10-21（业主的「名册监视」）：`RosterView` 的顶层键在每一档上都在
    # （名册目录不在 ⇒ `answer=unknown` 也是同一批键，见 `roster_face` 里那张表），
    # 所以它进受核对名单；行一级的五个类型见 `UNCHECKED_TYPES` 的理由。
    "RosterView",
)

#: 声明了、但夹具上还读不出键的接口（`{接口名: 理由}`）。判据不许它们同时出现在
#: 两份登记里，也不许一份都不在 —— 这张表是"为什么还没有读数"的唯一落点。
UNCHECKED_TYPES: dict[str, str] = {
    "StatementRow": "夹具没有造 statements 行（真机 p9b/data/statements.json 也是 0 行）"
                    "⇒ 字段以 `schema.Statement` 的 dataclass 为准，无真读数可对账",
    "ReviewFindingRow": "夹具没有造 review_findings 行（同上：真机 0 行）",
    "RelationRow": "夹具没有造 relations 行 ⇒ 以 `schema.Relation` 为准",
    "ConjectureRow": "夹具没有造 conjectures 行 ⇒ 以 `schema.Conjecture` 为准",
    "ExperimentRow": "夹具没有造 experiments 行 ⇒ 以 `schema.Experiment` 为准",
    "UsageRow": "夹具没有造 usage_ledger 行（真机 p9b/data/usage_ledger.json 有 37 行，"
                "但那是运行数据面、不入库）",
    "SearchRequestRow": "夹具没有造 search_requests 行（同上）",
    # 2026-10-12 三条：它们的行是运行期数据，夹具上恒为空数组。
    # 三态纪律在这里的落点与 `UsageRow` 同一条：没有读数就登记"为什么没有"，
    # 不是把接口从 types.ts 里删掉假装不存在。
    "BudgetEntry": "夹具没有预算寄存器（`budget.json` 由用户设过一次才有）"
                   "⇒ `added[]` 是空数组，行形状以 `budget._write` 为准",
    "UsageBucket": "夹具的 `usage_ledger` 是空的（真机 T2 那本有几十行）"
                   "⇒ 两个归口的格子读不出来，形状以 `tokenmeter.by_role/by_scope` 为准",
    "StatusReportRow": "夹具没有 `out/review/STATUS-*`（那是跑过一趟之后才写的）"
                       "⇒ `reports[]` 是空数组，形状以 `statusreport.status_report_paths` 为准",
    # 2026-10-21（名册那一棵树）：夹具工作区里没有 `out/roster/`（名册只在有人被派活
    # 时才落盘）⇒ `nodes[]` 恒为空数组。行一级的五个形状以 `roster_face` 的真读数为准，
    # 而"为什么这里没有读数"就写在上面这一句里（三态纪律：不是把接口删掉假装不存在）。
    "RosterNode": "夹具没有 `out/roster/<父编号>.jsonl`（名册只在派人时落）"
                  "⇒ `nodes[]` 是空数组，形状以 `roster_face` 在真工作区上的读数为准",
    "RosterChild": "同 `RosterNode`：`nodes[].children[]` 在夹具上是空的"
                   "⇒ 形状以 `roster_face` 的 `children` 为准",
    "RosterInbox": "同 `RosterNode`：夹具上没有名册节点，`inbox` 一栏没有读数"
                   "⇒ 形状以 `roster_face` 的 `inbox` 为准",
    "RosterInboxItem": "同 `RosterNode`：`inbox.items[]` 在夹具上是空数组"
                       "⇒ 形状以 `_roster_inbox` 的 `items` 为准",
    "RosterCoverage": "同 `RosterNode`：夹具上没有名册文件，`coverage` 三个计数都是 null"
                      "⇒ 形状以 `roster_face` 的 `coverage` 为准",
    # 2026-10-21（台账行带"角色 + 绝对编号"）：验收面的 `rows[]` 在任何工作区上都有
    # 五行（判据是现算的、不依赖盘上数据），但它没有进契约判据 C 的读数清单
    # （`tests/test_webui_contracts.py::_backend_keys` 只取验收面的顶层键）⇒ 判据 C
    # 没有对账面。行形状由 `tests/test_ledger_faces_carry_role_and_id.py` 逐键钉着。
    "AcceptanceRow": "契约判据 C 的 `_backend_keys` 只读验收面的顶层键、没读 `rows[]`"
                     "⇒ 形状以 `_acceptance_rows` 与 `AcceptanceRow` 的声明为准"
                     "（逐键判据在 tests/test_ledger_faces_carry_role_and_id.py）",
}

#: 契约判据 D 的例外面：本模块声明、但后端还没落地的端点（`{端点: 理由}`）。
#: 落地之后必须删掉这一行 —— 判据有一条反向断言专门抓"永不生效的豁免"。
#: B1/B3 之后这一张表是空的：六个面与 `/api/stream` 都真的在总表里了。
PENDING_ENDPOINTS: dict[str, str] = {}

#: 本模块还欠的 TS 接口（`(名字, 缺哪个消费者)`）。生成器逐条写成 TODO 注释 ——
#: 于是"这个类型为什么还没有"在生成物里是看得见的，而不是一份空话。
#: 这一张表现在是空的：`RunIndex` / `RunIndexDrift` 那两条欠的是"页面消费端"，
#: 而 A 线的 Run 页在 W1 接上了（`GET /api/run-index` + `state.py` 里那三个接口）
#: ⇒ 按这张表自己的规矩，补完就该把行删掉。
MISSING_TYPES: tuple[tuple[str, str], ...] = ()



# ====================================================================== 取值帮手
#: `schema.TABLES` 的 `{表名: 文件名}` 缓存（惰性建一次；`TABLES` 是常量）。
_TABLE_FILES: dict[str, str] = {}


def _table_files() -> dict[str, str]:
    """`{表名: 文件名}`（从 `schema.TABLES` 反查，不另抄一份 —— 抄一份会静默漂移）。"""
    if not _TABLE_FILES:
        try:
            from ..schema import TABLES

            for name, spec in TABLES.items():
                _TABLE_FILES[str(name)] = str((spec or {}).get("file") or "")
        except Exception:  # noqa: BLE001 - 只为判"在不在盘上"，查不到就按"在"处置
            return {}
    return _TABLE_FILES


def _table_state(store: Any, table: str) -> tuple[list[dict], str]:
    """读一张 store 表：返回 `(行, tri)`。

    `Store.rows` 对"表文件不在盘上"返回空表 —— 那是"还没写过"，不是"读到了 0 行"。
    两档必须分开（三态纪律），所以这里在 `rows` 之外另看一眼表文件在不在：
    不在 ⇒ `not_applicable`（还没写过）；在 ⇒ `computed`（读到了，行数可以是 0）。
    读的时候抛异常（未知表、坏 JSON、无权限）⇒ `unreadable`（由调用方带回 reason）。
    """
    rel = _table_files().get(table, "")
    data = Path(str(getattr(store, "data", Path("."))))
    absent = bool(rel) and not (data / rel).is_file()
    rows = store.rows(table)
    return rows, (TRI_NOT_APPLICABLE if absent else TRI_COMPUTED)


def _read_state(path: Path) -> tuple[list[dict], str, str]:
    """读一个 JSONL 文件：返回 `(记录, 四态, 说明)`。

    四态是 `jsonlfile` 的 `absent` / `empty` / `ok` / `unreadable`；本模块再把它们
    映射成三态。这一层不许把 `unreadable` 折成空表：折了之后"读不出来"与
    "读到了 0 行"在读数上一模一样，而那正是本项目最贵的一类缺陷。
    """
    records, problems, state = read_jsonl_state(path)
    return records, state, "；".join(problems)


def _read_json_file(path: Path) -> tuple[Any, str, str]:
    """读一个 JSON 文件：返回 `(内容, 四态, 说明)`（三态口径同 :func:`_read_state`）。"""
    if not path.exists():
        return None, "absent", f"{path} 不在盘上"
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return None, "unreadable", f"{type(exc).__name__}: {exc}"
    if not raw.strip():
        return None, "empty", f"{path} 是空文件"
    try:
        return json.loads(raw), "ok", ""
    except ValueError as exc:
        return None, "unreadable", f"{type(exc).__name__}: {exc}"


def _face(records: list[dict], state: str, why: str, *, what: str) -> dict[str, Any]:
    """把一个 JSONL 源的四态读成一面读数的三态头（`{tri, reason, what}`）。

    为什么把映射收在一处：六个面各自把四态翻成三态时，只要有一个面写错一档，
    就会出现"读不出来"与"还没写过"互换 —— 那种错在别处看不出来。

    坏行一律算 `unreadable`：`read_jsonl_state` 的 `state` 只说"读到了几条记录"
    （全是坏行时它是 `empty`），而"有坏行"这件事只有 `problems` 那一栏说得出口。
    折过去就等于把"文件坏了"读成"还没写过" —— 正是三态纪律要挡的那一档。
    """
    del records
    if why:
        return {"tri": TRI_UNREADABLE, "reason": f"{what} 有读不出来的行：{why}"}
    if state == "unreadable":
        return {"tri": TRI_UNREADABLE, "reason": f"{what} 读不出来"}
    if state == "absent":
        return {"tri": TRI_NOT_APPLICABLE,
                "reason": f"{what} 不在盘上（还没写过；合法初态，不是没查成）"}
    if state == "empty":
        return {"tri": TRI_NOT_APPLICABLE,
                "reason": f"{what} 是空文件（还没写过；合法初态，不是没查成）"}
    return {"tri": TRI_COMPUTED, "reason": ""}


def _all_computed(*faces: Mapping[str, Any]) -> dict[str, Any]:
    """把若干面的三态头合成一个（任一 `unreadable` ⇒ 整面 `unreadable`；其余取最弱）。"""
    reasons = [str(f.get("reason") or "") for f in faces if f.get("tri") == TRI_UNREADABLE]
    if reasons:
        return {"tri": TRI_UNREADABLE, "reason": "；".join(r for r in reasons if r)}
    if all(f.get("tri") == TRI_NOT_APPLICABLE for f in faces):
        return {"tri": TRI_NOT_APPLICABLE,
                "reason": "；".join(str(f.get("reason") or "") for f in faces)}
    return {"tri": TRI_COMPUTED, "reason": ""}


# ====================================================================== 1 快照
def state_face(root: str | Path) -> dict[str, Any]:
    """`GET /api/state` 的读模型：`{tri, snapshot, reason}`。

    `snapshot` 就是 `webui.state.snapshot()` 的返回值逐字（键集合与拆包前一致，
    主控用 `temp/_verify_w0.py` 对账过）；本函数只在外层加三态头，不重排、不改名。
    为什么要外挂一层而不是改 `snapshot()`：`snapshot()` 的键是既有判据与旧壳渲染
    共用的公开面（`tests/test_webui.py` 逐条读它），签名稳定比"少一层包装"重要。

    三态：`snapshot()` 自己不抛异常（它把读不到的东西收进 `problems`），所以这一面
    的 `tri` 只有两档 —— 有 `problems` ⇒ `unreadable`（说清是"没查成"），
    没有 ⇒ `computed`。空的但可读的工作区仍然是 `computed`（那是"读到了，里面是空的"）。
    """
    from .state import snapshot

    snap = snapshot(root)
    problems = [str(p) for p in (snap.get("problems") or [])]
    if problems:
        return {"tri": TRI_UNREADABLE, "reason": "；".join(problems[:5]), "snapshot": snap}
    return {"tri": TRI_COMPUTED, "reason": "", "snapshot": snap}


# ====================================================================== 2 一趟详情
#: 检查点文件名的主干（`agent_loop.run_checkpoint_path`：`runs/agent-<角色>-<sid>.json`）。
_CHECKPOINT_DIR = "runs"


def _checkpoint_of(root: Path, sid: str) -> dict[str, Any]:
    """这一趟的检查点读成 `{tri, reason, checkpoint}`（`checkpoint` 读不到就是 `None`）。

    文件名按 `runs/agent-<角色>-<sid>.json` 找：角色是文件名中间那一段，
    同一个会话可能有多个角色的检查点，所以这里取"最后被写改过的那一个"
    （`stat().st_mtime` 最大的），并在 `reason` 里说清是哪一份。
    """
    d = root / _CHECKPOINT_DIR
    if not d.is_dir():
        return {"tri": TRI_NOT_APPLICABLE,
                "reason": f"{_CHECKPOINT_DIR}/ 不在盘上（这一趟还没落过检查点）",
                "checkpoint": None}
    want_suffix = f"-{sid}.json"
    hits = [p for p in sorted(d.glob("agent-*.json"))
            if p.name.endswith(want_suffix) and p.is_file()]
    if not hits:
        return {"tri": TRI_NOT_APPLICABLE,
                "reason": f"{_CHECKPOINT_DIR}/ 里没有 agent-*-{sid}.json（这一趟还没落过检查点）",
                "checkpoint": None}
    newest = max(hits, key=lambda p: p.stat().st_mtime)
    data, state, why = _read_json_file(newest)
    if state != "ok" or not isinstance(data, dict):
        return {"tri": TRI_UNREADABLE,
                "reason": f"检查点 {newest.name} 读不出来：{why}",
                "checkpoint": None}
    return {"tri": TRI_COMPUTED, "reason": f"检查点取自 {newest.name}",
            "checkpoint": data}


def run_view(root: str | Path, sid: str) -> dict[str, Any]:
    """`GET /api/run/{sid}` 的读模型：`RunView` = `Run` + `report` + `checkpoint`。

    - `runs`：这一趟会话里的每一趟（`sessions.runs_in_session`，与 `webui.state._scan`
      的 20 键逐字同形）；
    - `report`：`out/review/REPORT.md` 的读数，两栏 `{status, text}`，`status` 是
      `ok`/`missing`/`unknown`（另一套词表，见裁定 N1）；
    - `checkpoint`：`runs/agent-<角色>-<sid>.json` 的内容（读不到就是 `None`）。

    三态：会话文件不在盘上 ⇒ `unreadable`（`sid` 是调用方给的，找不到就是"没查成"，
    不是"这一趟没有事件"）；会话在但有坏行 ⇒ `unreadable` + `reason` 里带坏行数。
    """
    from .state import _read_report

    root_p = Path(str(root))
    problems: list[str] = []
    path = SS.session_path(root_p, sid)
    if not path.is_file():
        return {"tri": TRI_UNREADABLE,
                "reason": f"会话文件不在盘上：{path}",
                "sid": sid, "runs": [], "report": {"status": "missing", "text": ""},
                "checkpoint": None, "checkpoint_reason": "", "path": str(path)}
    events, bad = SS.read_session(root_p, sid=sid)
    runs = SS.runs_in_session(events, sid=sid)
    rstatus, rtext = _read_report(root_p)
    ckpt = _checkpoint_of(root_p, sid)
    if bad:
        problems.append(f"会话有 {len(bad)} 条坏行：" + "；".join(bad[:3]))
    if ckpt["tri"] == TRI_UNREADABLE:
        problems.append(str(ckpt["reason"]))
    return {
        "tri": TRI_UNREADABLE if problems else TRI_COMPUTED,
        "reason": "；".join(problems),
        "sid": sid,
        "runs": runs,
        "report": {"status": rstatus, "text": rtext},
        "checkpoint": ckpt["checkpoint"],
        "checkpoint_reason": str(ckpt["reason"]),
        "path": str(path),
    }


# ====================================================================== 2b 逐条事件
#: `GET /api/run/{sid}/events` 的默认页大小与硬上限（题 T2-a：上限是硬边界，
#: 超了按上限截断并在 `reason` 里说明 —— "不吐无限"这一条由判据钉着）。
EVENTS_LIMIT_DEFAULT = 50
EVENTS_LIMIT_MAX = 500

#: `EventRow` 从事件行里挑出来的那些"有就带上"的字段（键 -> TS 类型）。
#: 逐字对着题 T2-a 给的那一行形状；`index` / `kind` / `ts` / `role` 四个必带的键
#: 在 :func:`_event_row` 里单列（它们不在这一张表里）。
#:
#: `stopped` 今天没有任何生产者（`sessions.append` 那一路的事件里搜不到这个键）：
#: 它是"有就带上"的那一档，留着是为了与 T2-a 的字段表逐字对齐 —— 真有事件带它时
#: 会自动出现在读数里，没有时不出现（不会伪造一个 `false`）。
_EVENT_FIELDS: tuple[tuple[str, str], ...] = (
    ("shape", "string"), ("ok", "boolean"), ("usd", "number | null"),
    ("tokens_in", "number"), ("tokens_out", "number"),
    ("payload", "Record<string, unknown>"), ("result", "Record<string, unknown>"),
    ("text", "string"), ("stopped", "boolean"),
)


def _event_row(index: int, event: Mapping[str, Any]) -> dict[str, Any]:
    """一条事件行 → `EventRow`（`index` 由调用方给，见模块 docstring 的编号口径）。

    四个必带的键读不到就写空串（前端 `Table.cell()` 把空串渲染成 `unknown`，
    不折成 0 / false）；"有就带上"的那几个键只在原行真有它时出现 ——
    补一个 `null`/`false` 就等于把"这一行没有这一栏"说成"这一栏读到了、是空的"。
    """
    row: dict[str, Any] = {
        "index": index,
        "kind": str(event.get("kind") or ""),
        "ts": str(event.get("ts") or ""),
        "role": str(event.get("role") or ""),
    }
    for key, _ts in _EVENT_FIELDS:
        if key in event:
            row[key] = event[key]
    return row


def run_events(root: str | Path, sid: str, *, since_index: int = 0,
               limit: int = EVENTS_LIMIT_DEFAULT) -> dict[str, Any]:
    """`GET /api/run/{sid}/events` 的读模型：一趟的逐条事件（游标分页）。

    形状见 :data:`_TS_TYPES` 里的 `RunEventsView` 与 `EventRow`；编号口径见模块
    docstring 的"逐条事件的编号口径"那一节（`index` 与 `snapshot()` 的
    `start_index`/`end_index` 是同一套）。

    数据来源只有一处：`sessions.read_session(root, sid=...)` —— 与
    `webui.state.snapshot()` 读的是同一个入口、同一份解析（不新写第二份）。

    三态（裁定 N1，不许折平）：

    - 会话文件不在盘上 ⇒ `unreadable` + 一句点名那个路径的理由：`sid` 是调用方给的，
      找不到就是"没查成"，不是"这一趟没有事件"（更不是 500、也不是一页空读数）；
    - 会话文件在盘上但是空的 ⇒ `not_applicable` + "还没写过"那一档的理由；
    - 有坏行 ⇒ `unreadable` + 坏行数，而读得出来的那些行照常给（少给行会让
      "这一趟只有 3 条事件"变成一句假话）；
    - 读到了 ⇒ `computed`，计数栏是真数字（`total` 可能是 0 之外的真值）。

    计数栏与三态的关系（`None` 与 `0` 是两件事，`0` 只属于 `computed`）：

    - 文件不在盘上 / 文件是空的 ⇒ 计数栏一律 `None`（`total` / `from_index` /
      `to_index`）—— 按本模块的三态纪律，"还没写过"与"没查成"都不许折成 0；
    - 有坏行 ⇒ 那一页照常给（读得出来的行是真读到的），计数栏也是真数字，而 `tri` 是
      `unreadable`、理由里带坏行数：少给行会让"这一趟只有 3 条事件"变成一句假话，
      而只报 `tri` 又会让"有坏行"这件事在读数里消失。

    分页是有界的：`limit` 钳进 `[1, EVENTS_LIMIT_MAX]`，被钳过就在 `reason` 里点名；
    `since_index` 钳进 `[0, total]`（越过末尾回一页空的，那不是错误）。
    """
    root_p = Path(str(root))
    path = SS.session_path(root_p, sid)
    if not path.is_file():
        return {"tri": TRI_UNREADABLE,
                "reason": f"会话文件不在盘上：{path}（这是「没查成」，不是「这一趟没有事件」）",
                "sid": sid, "total": None, "from_index": None, "to_index": None,
                "truncated": False, "events": []}
    records, bad = SS.read_session(root_p, sid=sid)
    total = len(records)
    if total == 0 and not bad:
        return {"tri": TRI_NOT_APPLICABLE,
                "reason": f"会话文件在盘上但是空的（{path}）：还没写过事件，合法初态，"
                          "不是没查成",
                "sid": sid, "total": None, "from_index": None, "to_index": None,
                "truncated": False, "events": []}
    notes: list[str] = []
    want_limit = int(limit)
    if want_limit > EVENTS_LIMIT_MAX:
        notes.append(f"limit={want_limit} 超上限 {EVENTS_LIMIT_MAX}，已按上限截断")
        want_limit = EVENTS_LIMIT_MAX
    if want_limit < 1:
        notes.append(f"limit={want_limit} 小于 1，已按 1 条取")
        want_limit = 1
    start = max(0, min(int(since_index), total))
    page = records[start:start + want_limit]
    rows = [_event_row(start + i, e) for i, e in enumerate(page)]
    to_index = start + len(rows)
    problems: list[str] = []
    if bad:
        problems.append(f"会话有 {len(bad)} 条坏行（读得出来的 {total} 条照常给）："
                        + "；".join(bad[:3]))
    return {
        "tri": TRI_UNREADABLE if problems else TRI_COMPUTED,
        "reason": "；".join(problems + notes),
        "sid": sid,
        "total": total,
        "from_index": start,
        "to_index": to_index,
        "truncated": to_index < total,
        "events": rows,
    }


# ====================================================================== 3 证据链
#: 证据面读的那七族（表名 / 它是不是 store 表 / 给前端的那一栏）。
_EVIDENCE_TABLES: tuple[tuple[str, str, str], ...] = (
    ("statements", "statements", "store.rows(\"statements\")"),
    ("conjectures", "conjectures", "store.rows(\"conjectures\")"),
    ("experiments", "experiments", "store.rows(\"experiments\")"),
    ("review_findings", "review_findings", "store.rows(\"review_findings\")"),
    ("relations", "relations", "store.rows(\"relations\")"),
)

#: 证据面那七栏的名字（逐行注解时的遍历顺序；与 `_EVIDENCE_TABLES` 的键 + 两栏非表来源）。
_LEDGER_EVIDENCE_COLUMNS: tuple[str, ...] = (
    "statements", "conjectures", "experiments", "review_findings", "relations",
    "verifications", "secretary",
)


# ============================================================== 台账行：谁写的、哪一趟写的
# 这一节是"读模型的 join"：三张台账面（证据 / 产物 / 收工门）返回的每一行都补三格 ——
# `by_role` / `by_task_id` / `by_task_id_tri`。磁盘格式一个字节都不变（`schema.py` 不在
# 这一批的改动面里），补的是"给页面读的那一刻"的派生字段。
#
# 为什么不做成"写侧多写一列"：那是一处不可逆的磁盘格式变更（禁改区），而"这一行是哪一趟
# 写的"在事件流里已经有痕迹 —— 缺的只是一个有界、不猜的 join。做在写侧等于用一次迁移
# 换一个可以现算的读数；做在读侧则连历史数据都一起变得读得出来。

#: 反查"这一行是哪一趟写的"时，只扫最近这么多段会话（`sessions/<sid>.jsonl`）。
#:
#: 为什么给死一个数：这一层挂在 `GET /api/evidence` 与 `GET /api/artifacts` 上，
#: 每次请求都会跑一遍。会话是 append-only 的，一个跑久的工作区能有几十段、单段几兆
#: （真机 `projects/t5-run2` 的一段 4.3MB）—— 每次请求全盘扫会把这两个面拖成秒级。
#: 窗口之外的东西不会"看起来没有"：那一档落在 `missing` 上，而这一格的 `missing`
#: 就是"查过了、扫描窗口内没有"（口径写死在 :func:`_ledger_by_task_id` 的 docstring 里）。
LEDGER_EVENT_SCAN_SESSIONS = 6

#: 一份会话文件最多读多少字节；超了只读尾巴（并丢掉被截断的那半行）。
LEDGER_EVENT_SCAN_BYTES = 8 * 1024 * 1024

#: 反查只认这些 kind（其余事件连 JSON 都不解析）。
#:
#: 为什么是这五个，以及为什么 `agent_run_start` / `llm_call` 不在里面：后两者的正文里
#: 经常出现台账编号（`agent_run_start.task` 是任务书，`llm_call` 的 prompt 里装着整段
#: 证据包）—— 拿它们当"写入的那条事件"，编号会被贴给"读它的人"。反查要认的是"写进去
#: 了"这件事的痕迹：工具结果（`agent_step`）、产物登记（`agent_run_artifact`）、
#: 收工读到的证据与交付（`agent_run_end`）、笔记（`agent_note`）、派活收尾（`task_end`）。
LEDGER_EVENT_SCAN_KINDS: tuple[str, ...] = (
    "agent_step", "agent_run_artifact", "agent_run_end", "agent_note", "task_end",
)

#: `by_task_id_tri` 里"这一栏是写入"的两档（第三档是 `Tri` 的 `not_applicable`，
#: 表示"这一栏的行不是某条写入"）。三档不许互相顶替：把 `missing` 显示成
#: `not_applicable`，"查过了没找到"就变成"用不着"。
LEDGER_TASK_TRI_EVENT = "event"
LEDGER_TASK_TRI_MISSING = "missing"

#: 每一栏台账行的反查口令：`栏名 -> (行里的编号在哪一格, 引用前缀)`。
#:
#: 前缀取自 `schema.CITATION_PREFIXES`（引用前缀的唯一声明面，这里只读它）——
#: `stmt:` / `exp:` / `rel:` 这三种写法在事件正文里真的出现，所以它们是精确口令。
#: 裸编号（六位十进制）到处都有（sha256 里、时间戳里、计数里），拿它当口令会误命中，
#: 因此这类表只认带前缀的写法。
#:
#: 不在本表里的栏一律 `not_applicable`（这一栏的行不是"某条写入"）。已经定死的几类：
#: - `conjectures` / `review_findings`：`schema.CITATION_PREFIXES` 里没有它们的引用前缀，
#:   于是事件正文里没有一个能唯一定位的写法（裸六位号会误命中）。要让这两栏也有编号，
#:   必须先在 `schema.CITATION_PREFIXES` 里登记 `conj:` / `find:` —— 那在禁改区
#:   （`schema.py`，FC-27 人审），本批刻意不动；
#: - `handoffs`：手稿号是裸号（编号空间就是账本行号），同一个问题；
#: - `secretary` / `checks` / `products`：秘书台账没有稳定的行编号，验收表是配置行
#:   （`C1`–`C8`），六件产物是文件清单 —— 它们都不是"某一条写入"。
_LEDGER_ROW_TOKENS: dict[str, tuple[str, str]] = {
    "statements": ("stmt_id", "stmt"),
    "experiments": ("experiment_id", "exp"),
    "relations": ("relation_id", "rel"),
    "verifications": ("verification_id", ""),
    "ledger": ("path", ""),
    "ledger_verify": ("path", ""),
    "tasks": ("task_id", ""),
}

#: `by_role` 的有序取值来源（第一个非空的赢）与它同时公开的 `by_role_source`。
#:
#: 为什么允许回退：严格只认 `created_by` 时产物面每一行都是空串（`ARTIFACTS.jsonl`、
#: `handoffs.jsonl`、`tasks` 都没有那一栏，它们的角色写在 `producer` / `sender` /
#: `role` 里），而业主的原话是"台账里也要看到角色和编号" —— 整面全是"（未记录角色）"
#: 等于没做到。回退仍然可复核，因为"这一格是从哪个字段来的"同时公开在
#: `by_role_source` 里：读的人知道它是原始字段还是派生结论，判据也据此断言。
#:
#: 次序按"这个字段离'谁写的'最近"排：`created_by` 是写入者自己的署名；`role` 是这一行
#: 归属的角色；`producer` 是产出这件东西的程序/角色；`sender` 是发件人；`verifier` 是
#: 签字的人；`author` 是作者。六格全空 ⇒ `by_role=""`、`by_role_source=""`
#: （页面显示"（未记录角色）"），不退到 `task_id` / `path` 这类非角色字段上。
LEDGER_ROLE_FIELDS: tuple[str, ...] = (
    "created_by", "role", "producer", "sender", "verifier", "author",
)


def _recent_session_files(root_p: Path,
                          limit: int = LEDGER_EVENT_SCAN_SESSIONS) -> list[Path]:
    """最近的那几段会话文件（新 -> 旧；`limit <= 0` 给空列表）。

    排序口径是 `(mtime, 文件名)` 倒序。为什么不按文件名：真机上的 sid 有两种形态
    （日期 `20261021` 与自取名 `p3-1`），按名字排会把"今天这一段"排到某个旧的自取名
    下面。文件名只做同 mtime 时的次序键，于是排序结果确定、判据可复现。

    读不到时间戳的那一段不进窗口（它没法排新旧）：那是"这一段没查成"，不是"这一段
    没有内容"—— 所以它不会伪装成命中，只会让相关的行落在 `missing` 上。
    """
    d = SS.sessions_dir(root_p)
    if not d.is_dir():
        return []
    found: list[tuple[float, str, Path]] = []
    for p in d.glob("*.jsonl"):
        try:
            mtime = p.stat().st_mtime
        except OSError:
            continue
        found.append((mtime, p.name, p))
    found.sort(key=lambda one: (one[0], one[1]), reverse=True)
    return [p for _m, _n, p in found[:max(0, int(limit))]]


def _session_tail(path: Path, budget: int = LEDGER_EVENT_SCAN_BYTES) -> str:
    """读一段会话的正文（超过 `budget` 字节时只读尾巴，并丢掉被截断的那半行）。

    为什么允许"只读尾巴"：这是有界反查的第二道尺子。台账写入几乎都发生在这一段会话的
    后半段（前面是开场与读料），而一个 4MB 的会话单是解析就要几百毫秒。截断是规模的界、
    不是读失败 —— 被挡在窗口外的行照旧落在 `missing` 上，不会变成一条假命中。
    """
    try:
        size = path.stat().st_size
        with path.open("rb") as fh:
            if int(budget) > 0 and size > int(budget):
                fh.seek(size - int(budget))
                fh.readline()          # 丢掉被截断的那半行
            raw = fh.read()
    except OSError:
        return ""
    return raw.decode("utf-8", errors="replace")


def _ledger_token(field_name: str, prefix: str, row: Mapping[str, Any]) -> str:
    """一行台账的反查口令（空串 = 这一行没有可反查的编号）。"""
    bare = str(row.get(field_name) or "").strip()
    if not bare:
        return ""
    return f"{prefix}:{bare}" if prefix else bare


def _ledger_by_task_id(root_p: Path, tokens: Sequence[str]) -> dict[str, str]:
    """口令 -> 绝对编号：在一段有界的事件流里反查"这一行是哪一趟写的"。

    口径四条，每一条都是"不猜"的一条边：

    1. 只扫最近 `LEDGER_EVENT_SCAN_SESSIONS` 段会话、只认 `LEDGER_EVENT_SCAN_KINDS`；
    2. 一条事件只有自己带着非空 `task_id` 时才可能成为答案。"相邻那条 `llm_call` 的编号"
       不算：`agent_step` 记着工具结果（写入的真身）却不带编号，拿旁边的编号顶上就是把
       "我推的"混进"盘上写的" —— 于是这一档在写侧补编号之前会大面积落在 `missing` 上，
       那正是这一格的读数，不是缺陷；
    3. 口令按词边界匹配（`stmt:000001` 不许命中 `stmt:0000012`），否则一个更长的编号会把
       编号贴到它的前缀那一行上；
    4. 同一个口令出现在多条事件里时，取扫描顺序上的第一条（新会话优先、会话内按文件顺序），
       不合并、不投票、不猜。

    它只回答"哪条事件提到过这个编号、而那条事件自己说它是哪一趟"。对于交付型事件
    （`agent_run_end.final` 里逐条点名它写了哪些行），这个答案是那一趟；对于转述型正文
    （别的事后引用别人的编号），这个答案可能是"引用者"—— 这是本口径的已知边界，写在
    `missing` 之外的读数要按这一条读。
    """
    wanted = sorted({str(t) for t in tokens if str(t)}, key=len, reverse=True)
    if not wanted:
        return {}
    pattern = re.compile("|".join(
        f"(?<![0-9A-Za-z_])(?:{re.escape(one)})(?![0-9A-Za-z_])" for one in wanted))
    kinds = set(LEDGER_EVENT_SCAN_KINDS)
    found: dict[str, str] = {}
    for path in _recent_session_files(root_p):
        text = _session_tail(path)
        if not text:
            continue
        for line in text.splitlines():
            if '"task_id"' not in line:
                continue          # 便宜的预筛：没有编号的事件不可能是答案
            hits = pattern.findall(line)
            if not hits:
                continue
            try:
                event = json.loads(line)
            except ValueError:
                continue          # 坏行：这一段里它算没读到（不猜）
            if str(event.get("kind") or "") not in kinds:
                continue
            task_id = str(event.get("task_id") or "").strip()
            if not task_id:
                continue
            for token in hits:
                found.setdefault(token, task_id)
    return found


def _ledger_role(row: Mapping[str, Any]) -> tuple[str, str]:
    """这一行是谁写的：返回 `(角色, 这一格取自哪个字段)`；六格全空 ⇒ `("", "")`。

    有序回退的口径与理由写在 :data:`LEDGER_ROLE_FIELDS` 上。这里只做一件事：按那个次序
    取第一个非空值，并把"取到了哪一格"一起返回 —— 于是"派生的角色"永远带着它的出处，
    读的人与判据都不必猜。

    只认角色字段：`task_id` / `path` / `kind` 这些即使非空也不算角色（"这一行属于哪一趟"
    与"这一行是谁写的"是两根轴，混一根轴会让两个读数同时失真）。
    """
    for field_name in LEDGER_ROLE_FIELDS:
        got = str(row.get(field_name) or "").strip()
        if got:
            return got, field_name
    return "", ""


def _annotate_ledger_row(column: str, row: Mapping[str, Any],
                         index: Mapping[str, str]) -> dict[str, Any]:
    """把一行台账补上 `by_role` / `by_role_source` / `by_task_id` / `by_task_id_tri`。

    `by_role` 走 `LEDGER_ROLE_FIELDS` 那六格的有序回退，`by_role_source` 说清它取自哪一格
    （全空则两格都是空串）。为什么必须公开来源：回退一旦不给出来源，"这一行确实记录了角色"
    与"我们从一个邻近字段推出来的"在读的人眼里长得一样 —— 而那正是这一格最容易变假话的
    地方（三态纪律在"角色"这一轴上的落点）。
    """
    got = dict(row)
    role, role_source = _ledger_role(row)
    got["by_role"] = role
    got["by_role_source"] = role_source
    spec = _LEDGER_ROW_TOKENS.get(column)
    if spec is None:
        got["by_task_id"] = ""
        got["by_task_id_tri"] = TRI_NOT_APPLICABLE
        return got
    token = _ledger_token(spec[0], spec[1], row)
    task_id = str(index.get(token) or "") if token else ""
    got["by_task_id"] = task_id
    got["by_task_id_tri"] = LEDGER_TASK_TRI_EVENT if task_id else LEDGER_TASK_TRI_MISSING
    return got


def _annotate_ledger_rows(root_p: Path,
                          columns: Mapping[str, Sequence[Mapping[str, Any]]]
                          ) -> dict[str, list[dict[str, Any]]]:
    """一整面里每一栏台账行都补上那四格（反查只做一遍：一次请求一次有界扫描）。

    为什么按"面"而不是按"栏"：一面上有五到七栏，每栏各扫一遍事件流就是五到七次全文件
    读。口令先收集齐、扫一遍、再回填 —— 于是"这一面一次请求一次扫描"是结构上的事实，
    不是记在文档里的一句提醒。
    """
    tokens: list[str] = []
    for column, rows in columns.items():
        spec = _LEDGER_ROW_TOKENS.get(column)
        if spec is None:
            continue
        for row in rows:
            if isinstance(row, Mapping):
                token = _ledger_token(spec[0], spec[1], row)
                if token:
                    tokens.append(token)
    index = _ledger_by_task_id(root_p, tokens)
    return {str(column): [_annotate_ledger_row(str(column), row, index)
                          if isinstance(row, Mapping) else row
                          for row in rows]
            for column, rows in columns.items()}


def evidence_chain(root: str | Path, store: Any = None) -> dict[str, Any]:
    """`GET /api/evidence` 的读模型：证据链七栏 + 三态。

    `statements` / `conjectures` / `experiments` / `review_findings` / `relations`
    逐行来自 `store.rows(...)`（不另写一份读法）；`verifications` 来自
    `verifications.list_verifications`（一命题一份 `verifications/<4 位>.jsonl`）；
    `secretary` 来自 `out/secretary/<角色>.jsonl`。

    三态：`store` 读不出来（未知表、坏 JSON、无权限）⇒ `unreadable` + `reason`；
    表是空文件 / 还没写过 ⇒ 对应栏 `[]` 而整面 `tri="computed"`（读到了，
    里面是 0 行 —— 这与"没读到"是两件事，前者不报 `unreadable`）。
    每一栏另有一个 `<栏>_tri`，于是"哪一栏没读成"不会被整面的一个词吞掉。
    """
    from ..store import Store
    from ..verifications import list_verifications

    root_p = Path(str(root))
    out: dict[str, Any] = {"reason": "", "store_problems": []}
    problems: list[str] = []
    absent: list[str] = []
    if store is None:
        store = Store(root_p)
    for table, key, source in _EVIDENCE_TABLES:
        try:
            rows, tri = _table_state(store, table)
        except Exception as exc:  # noqa: BLE001 - 读数层：读不到就如实说没查成
            out[key] = []
            out[f"{key}_tri"] = TRI_UNREADABLE
            problems.append(f"{source} 读不出来：{type(exc).__name__}: {exc}")
            continue
        out[key] = rows
        out[f"{key}_tri"] = tri
        if tri == TRI_NOT_APPLICABLE:
            absent.append(key)
    try:
        proofs, bad = list_verifications(root_p, limit=None)
        out["verifications"] = proofs
        out["verifications_tri"] = _verifications_tri(root_p, proofs, bad)
        out["store_problems"].extend(bad)
    except Exception as exc:  # noqa: BLE001
        out["verifications"] = []
        out["verifications_tri"] = TRI_UNREADABLE
        problems.append(f"verifications.list_verifications 读不出来："
                        f"{type(exc).__name__}: {exc}")
    sec = _secretary_rows(root_p)
    out["secretary"] = sec["rows"]
    out["secretary_tri"] = sec["tri"]
    if sec["tri"] == TRI_UNREADABLE:
        problems.append(str(sec["reason"]))
    # ---- 逐行补"是谁、在哪一趟写的"（读模型的 join；磁盘格式一个字节都不变）
    out.update(_annotate_ledger_rows(root_p, {
        key: out.get(key) or [] for key in _LEDGER_EVIDENCE_COLUMNS}))
    if problems:
        out["tri"] = TRI_UNREADABLE
    elif len(absent) == len(_EVIDENCE_TABLES):
        out["tri"] = TRI_NOT_APPLICABLE
        out["reason"] = ("这几张表一张都没落过盘（" + "、".join(absent)
                         + "）—— 合法初态：这个工作区还没有证据链")
    else:
        out["tri"] = TRI_COMPUTED
    out["reason"] = "；".join(problems) if problems else str(out["reason"] or "")
    return out


def _verifications_tri(root: Path, rows: list[dict], problems: list[str]) -> str:
    """验证台账那一栏的三态：目录不在 ⇒ `not_applicable`；坏行 ⇒ `unreadable`。"""
    if problems:
        return TRI_UNREADABLE
    if not (root / "verifications").is_dir():
        return TRI_NOT_APPLICABLE
    del rows
    return TRI_COMPUTED


def _secretary_rows(root: Path) -> dict[str, Any]:
    """`out/secretary/<角色>.jsonl` 全部读回来（按角色名排序，逐条带 `role`）。

    目录不在 ⇒ `not_applicable`（还没写过秘书台账）；某一份读不出来 ⇒ `unreadable`
    并点名是哪个角色（整面因此变红 —— 少一个角色的账就是少一段审计）。
    """
    from ..secretary import decisions_path

    d = root / "out" / "secretary"
    if not d.is_dir():
        return {"tri": TRI_NOT_APPLICABLE, "rows": [],
                "reason": "out/secretary/ 不在盘上（这个工作区还没有秘书台账）"}
    rows: list[dict] = []
    problems: list[str] = []
    for path in sorted(d.glob("*.jsonl")):
        got, state, why = _read_state(path)
        face = _face(got, state, why, what=f"{path.name}")
        if face["tri"] == TRI_UNREADABLE:
            problems.append(str(face["reason"]))
            continue
        rows.extend(got)
    if problems:
        return {"tri": TRI_UNREADABLE, "rows": rows, "reason": "；".join(problems)}
    if not rows:
        return {"tri": TRI_NOT_APPLICABLE, "rows": [],
                "reason": "out/secretary/ 里一份非空台账都没有（合法初态）"}
    return {"tri": TRI_COMPUTED, "rows": rows, "reason": ""}


# ====================================================================== 4 产物
def run_products(root: str | Path, run_dir: str | Path | None = None) -> dict[str, Any]:
    """六件产物（裁定 J2）：`runflow.ARTIFACTS` 逐个读「在不在 / 多大 / 几行 / sha」。

    落点是 `<工作区>/out/run-N/`（`runflow._phase_6` 写的那六件）。`run_dir` 可以
    显式给（相对工作区或绝对路径都行）；不给时取 `out/` 下编号最大的 `run-N`
    （与 `projects._next_run_index` 的命名对齐 —— 但这里只读，不分配新编号）。

    三态：`out/` 下没有一个 `run-N/`（本机真机读数就是这样：六件产物没有真机样本）
    ⇒ 整面 `not_applicable` + 理由里明说"这一路（run/project run）本机还没跑过"，
    而不是把六件都写成 `exists=false` 让人以为"跑过但文件丢了"。
    """
    from ..artifacts import sha256_of
    from ..runflow import ARTIFACTS

    root_p = Path(str(root))
    chosen, why = _pick_run_dir(root_p, run_dir)
    if chosen is None:
        return {"tri": TRI_NOT_APPLICABLE, "reason": why, "run_dir": "",
                "products": [{"name": name, "path": "", "exists": False,
                              "bytes": None, "lines": None, "sha256": "",
                              "tri": TRI_NOT_APPLICABLE} for name in ARTIFACTS]}
    products: list[dict[str, Any]] = []
    for name in ARTIFACTS:
        p = chosen / name
        if not p.is_file():
            products.append({"name": name, "path": str(p), "exists": False,
                             "bytes": None, "lines": None, "sha256": "",
                             "tri": TRI_NOT_APPLICABLE})
            continue
        try:
            size = p.stat().st_size
            digest = sha256_of(p)
        except OSError as exc:
            products.append({"name": name, "path": str(p), "exists": True,
                             "bytes": None, "lines": None, "sha256": "",
                             "tri": TRI_UNREADABLE})
            products[-1]["reason"] = f"{type(exc).__name__}: {exc}"
            continue
        lines: int | None = None
        if p.suffix == ".jsonl":
            lines = len([x for x in p.read_text(encoding="utf-8",
                                                errors="replace").splitlines()
                         if x.strip()])
        products.append({"name": name, "path": str(p), "exists": True,
                         "bytes": size, "lines": lines, "sha256": digest,
                         "tri": TRI_COMPUTED})
    return {"tri": TRI_COMPUTED, "reason": "", "run_dir": str(chosen),
            "products": products}


def _pick_run_dir(root: Path, run_dir: str | Path | None) -> tuple[Path | None, str]:
    """挑一个运行目录：显式给的优先，否则 `out/run-N` 里编号最大的那个。"""
    if run_dir:
        p = Path(str(run_dir))
        if not p.is_absolute():
            p = root / p
        if not p.is_dir():
            return None, f"给的运行目录不在盘上：{p}"
        return p, ""
    out = root / "out"
    if not out.is_dir():
        return None, ("out/ 不在盘上 —— 六件产物（run-manifest.json 那一路）"
                      "本机还没有跑过（裁定 J2：无真机样本，判据用夹具造）")
    numbered: list[tuple[int, Path]] = []
    for p in out.iterdir():
        if not p.is_dir() or not p.name.startswith("run-"):
            continue
        tail = p.name[4:]
        if tail.isdigit():
            numbered.append((int(tail), p))
    if not numbered:
        return None, ("out/ 下没有一个 run-N/ 目录 —— 六件产物那一路"
                      "（agentflow run / project run）本机还没有跑过"
                      "（裁定 J2：无真机样本，判据用夹具造）")
    return max(numbered)[1], ""


def _acceptance_checks(root: Path, project_dir: str = "") -> dict[str, Any]:
    """`out/paper/ACCEPTANCE-CHECKS.json` 的读数（`closing.ACCEPTANCE_CHECKS_NAME`）。

    它接受两种形状：顶层数组，或 `{"checks": [...]}`（`closing._check_acceptance`
    两种都认，这里照同一条口径读）。真机读数：8 行 C1–C8，键 `id/kind/min/name/note`。
    """
    from ..closing import ACCEPTANCE_CHECKS_NAME

    base = Path(project_dir) if project_dir else root
    if project_dir and not base.is_absolute():
        base = root / project_dir
    path = base / ACCEPTANCE_CHECKS_NAME
    data, state, why = _read_json_file(path)
    if state in ("absent", "empty"):
        return {"tri": TRI_NOT_APPLICABLE, "reason": f"验收表还没写：{path}", "checks": []}
    if state == "unreadable":
        return {"tri": TRI_UNREADABLE, "reason": f"验收表读不出来：{why}", "checks": []}
    if isinstance(data, list):
        rows = data
    elif isinstance(data, dict) and isinstance(data.get("checks"), list):
        rows = data["checks"]
    else:
        return {"tri": TRI_UNREADABLE,
                "reason": f"验收表的形状不认识：顶层是 {type(data).__name__}"
                          "（只认数组或 {checks: [...]}）", "checks": []}
    return {"tri": TRI_COMPUTED, "reason": "", "checks": [r for r in rows
                                                          if isinstance(r, dict)]}


def _report_style(root: Path, project_dir: str = "") -> dict[str, Any]:
    """`out/review/REPORT-STYLE.json` 的读数：`{tri, reason, sections}`。"""
    base = Path(project_dir) if project_dir else root
    if project_dir and not base.is_absolute():
        base = root / project_dir
    path = base / "out" / "review" / "REPORT-STYLE.json"
    data, state, why = _read_json_file(path)
    if state in ("absent", "empty"):
        return {"tri": TRI_NOT_APPLICABLE, "reason": f"体例文件还没写：{path}",
                "sections": []}
    if state == "unreadable":
        return {"tri": TRI_UNREADABLE, "reason": f"体例文件读不出来：{why}", "sections": []}
    if not isinstance(data, dict) or not isinstance(data.get("sections"), list):
        return {"tri": TRI_UNREADABLE,
                "reason": "体例文件的形状不认识（只认 {sections: [...]}）", "sections": []}
    return {"tri": TRI_COMPUTED, "reason": "",
            "sections": [str(s) for s in data["sections"]]}


def artifacts_face(root: str | Path, store: Any = None, *,
                   run_dir: str | Path | None = None,
                   project_dir: str = "") -> dict[str, Any]:
    """`GET /api/artifacts` 的读模型：台账 + 交接 + 验收行 + 体例 + 秘书 + 六件产物 + 任务。

    - `ledger`：`artifacts.read_ledger`（行键 9 个：`at/path/sha256/bytes/producer/`
      `kind/task_id/exit_code/note`）；另给 `ledger_verify`（`artifacts.verify_entries`，
      逐行"盘上现在的 sha 与台账里记的一样吗"）；
    - `handoffs`：`manuscripts.read_rows`（行键见 `tests/conftest.py` 的夹具）；
    - `checks` / `style`：`out/paper/ACCEPTANCE-CHECKS.json` 与 `out/review/REPORT-STYLE.json`；
    - `secretary`：`out/secretary/*.jsonl`；
    - `products`：六件产物（见 :func:`run_products`）；
    - `tasks`：`store.rows("tasks")`。

    三态是逐栏的（`ledger_tri` / `handoffs_tri` / ...）：一整面里有一栏读不出来时，
    整面 `unreadable` 并把这些栏点名，而读得出来的那些栏照常给行 —— 少给一栏会让
    "这一栏没读成"变成"这一栏是空的"，那两者在界面上必须分得开。
    """
    from .. import manuscripts as MS
    from ..artifacts import read_ledger, verify_entries
    from ..store import Store

    root_p = Path(str(root))
    out: dict[str, Any] = {"reason": ""}
    problems: list[str] = []
    # ---- 台账
    led_path = root_p / "ARTIFACTS.jsonl"
    rows, state, why = _read_state(led_path)
    face = _face(rows, state, why, what="产物台账 ARTIFACTS.jsonl")
    out["ledger"] = rows
    out["ledger_tri"] = face["tri"]
    if face["tri"] == TRI_UNREADABLE:
        problems.append(str(face["reason"]))
    try:
        out["ledger_verify"] = verify_entries(root_p, rows) if rows else []
        out["ledger_verify_tri"] = TRI_COMPUTED if rows else face["tri"]
    except Exception as exc:  # noqa: BLE001
        out["ledger_verify"] = []
        out["ledger_verify_tri"] = TRI_UNREADABLE
        problems.append(f"artifacts.verify_entries 读不出来：{type(exc).__name__}: {exc}")
    # ---- 交接手稿
    try:
        got_ms, ms_bad = MS.read_rows(root_p)
        out["handoffs"] = got_ms
        ms_path = MS.handoffs_path(root_p)
        ms_state = "ok" if got_ms else ("absent" if not Path(ms_path).is_file()
                                        else "empty")
        ms_face = _face(got_ms, ms_state, "；".join(ms_bad),
                        what="交接台账 manuscripts/handoffs.jsonl")
        out["handoffs_tri"] = ms_face["tri"]
        if ms_face["tri"] == TRI_UNREADABLE:
            problems.append(str(ms_face["reason"]))
    except Exception as exc:  # noqa: BLE001
        out["handoffs"] = []
        out["handoffs_tri"] = TRI_UNREADABLE
        problems.append(f"manuscripts.read_rows 读不出来：{type(exc).__name__}: {exc}")
    # ---- 验收行 / 体例 / 秘书
    checks = _acceptance_checks(root_p, project_dir)
    style = _report_style(root_p, project_dir)
    sec = _secretary_rows(root_p)
    out["checks"] = checks["checks"]
    out["checks_tri"] = checks["tri"]
    out["style"] = {"sections": style["sections"]}
    out["style_tri"] = style["tri"]
    out["secretary"] = sec["rows"]
    out["secretary_tri"] = sec["tri"]
    for name, got in (("验收表", checks), ("体例", style), ("秘书台账", sec)):
        if got["tri"] == TRI_UNREADABLE:
            problems.append(f"{name}：{got['reason']}")
    # ---- 六件产物 / 任务
    prod = run_products(root_p, run_dir)
    out["products"] = prod["products"]
    out["products_tri"] = prod["tri"]
    out["run_dir"] = prod["run_dir"]
    out["products_reason"] = prod["reason"]
    if store is None:
        store = Store(root_p)
    try:
        rows, tasks_tri = _table_state(store, "tasks")
        out["tasks"] = rows
        out["tasks_tri"] = tasks_tri
    except Exception as exc:  # noqa: BLE001
        out["tasks"] = []
        out["tasks_tri"] = TRI_UNREADABLE
        problems.append(f"store.rows(\"tasks\") 读不出来：{type(exc).__name__}: {exc}")
    # ---- 逐行补"是谁、在哪一趟写的"（读模型的 join；磁盘格式一个字节都不变）。
    # 台账与台账核对两栏用同一个口令（`path`），于是同一行在两栏里不会有两种归属。
    out.update(_annotate_ledger_rows(root_p, {
        key: out.get(key) or []
        for key in ("ledger", "ledger_verify", "handoffs", "checks", "secretary",
                    "products", "tasks")}))
    # 整面的三态：有一条读不出来 ⇒ `unreadable`；七栏全是"还没写过" ⇒ `not_applicable`
    # （一个还没跑过的工作区不该被读成"产物面都是空的"）；其余 ⇒ `computed`。
    per_column = [str(out[k]) for k in ("ledger_tri", "handoffs_tri", "checks_tri",
                                        "style_tri", "secretary_tri", "products_tri",
                                        "tasks_tri")]
    if problems:
        out["tri"] = TRI_UNREADABLE
        out["reason"] = "；".join(problems)
    elif all(t == TRI_NOT_APPLICABLE for t in per_column):
        out["tri"] = TRI_NOT_APPLICABLE
        out["reason"] = ("产物面的七栏一张都没落过盘 —— 合法初态："
                         "这个工作区还没有产物台账、交接、验收表、体例、秘书账、"
                         "六件产物或任务行")
    else:
        out["tri"] = TRI_COMPUTED
        out["reason"] = ""
    return out


# ====================================================================== 5 收工门
def _acceptance_rows(criteria: Mapping[str, str],
                     details: Mapping[str, str]) -> list[dict[str, Any]]:
    """验收面的逐条行：一条判据一行，另带"谁 / 哪一趟"那四格（编号不适用）。

    为什么这一面也要有"行"：业主那句"台账面每一行都带角色加编号"里，收工门是最像台账
    的一面（C1–C8 那几条读数是人一条条看的）。它每一条判据都带 `by_role` /
    `by_role_source` / `by_task_id` / `by_task_id_tri`，三档的处置于是与另外两面同一套。

    这一面的行不是"某条写入"：判据是现算的，不落任何台账行，所以 `by_task_id` 恒为空串、
    `by_task_id_tri` 恒为 `not_applicable`。把它们写成 `missing` 会让每一行永远挂着一个
    假红的缺口（"查过了没找到"），而这里事实上是"编号用不着"。`by_role` 与
    `by_role_source` 也恒为空串：验收判据不属于任何一个角色，也没有一个角色字段可退
    （这一行本来就没有那六格里的任何一格）。三态不折平的另一半在这四格的定义里，
    不在这句注释里。
    """
    from ..reviewaccept import CRITERIA

    out: list[dict[str, Any]] = []
    for key, title in CRITERIA:
        out.append({
            "key": str(key), "title": str(title),
            "value": str(criteria.get(str(key), "unknown")),
            "detail": str(details.get(str(key), "")),
            "by_role": "", "by_role_source": "",
            "by_task_id": "", "by_task_id_tri": TRI_NOT_APPLICABLE,
        })
    return out


def acceptance_face(root: str | Path, store: Any = None, *, project_dir: str = "",
                    report_path: str = "", cap_usd: float | None = None,
                    sid: str | None = None) -> dict[str, Any]:
    """`GET /api/acceptance` 的读模型：内容级验收的逐条读数（`AcceptanceView`）。

    形状照 `draft/75 §1.3`：`criteria`（5 条，键名逐字来自 `reviewaccept.CRITERIA`）
    与 `auxiliary`（5 条，键名逐字来自 `AUXILIARY_SIGNALS`）。值都收成字符串：
    `criteria[k]` 是 `pass`/`fail`/`unknown`，`auxiliary[k]` 是人看的读数
    （读不出来就写 `""`，不是 `0`）。

    四档输入各自的三态（与 `reviewaccept` 同一口径，这里只做搬运与说明）：

    - 不给 `cap_usd` ⇒「在成本上限内」那一格是 `unknown`（没查成，不是"通过了"）；
    - 不给 `sid` ⇒ `triage_branch_recorded` 是 `unknown`（不知道读哪一段会话）；
    - `store` / `reviewaccept` 抛异常 ⇒ 整面 `unreadable` + `reason`。
    """
    from ..reviewaccept import AUXILIARY_SIGNALS, CRITERIA, check_review
    from ..store import Store

    root_p = Path(str(root))
    if store is None:
        store = Store(root_p)
    try:
        acc = check_review(store, project_dir=project_dir, report_path=report_path,
                           session_root=root_p, cost_cap_usd=cap_usd, sid=sid)
    except Exception as exc:  # noqa: BLE001 - 读数层：读不到就如实说没查成
        return {"tri": TRI_UNREADABLE, "reason": f"reviewaccept.check_review 读不出来："
                                                f"{type(exc).__name__}: {exc}",
                "criteria": {}, "auxiliary": {}, "details": {}, "failed": [],
                "rows": _acceptance_rows({}, {}),
                "auxiliary_note": ""}
    criteria = {str(k): str((acc.criteria or {}).get(k, "unknown")) for k, _d in CRITERIA}
    details = {str(k): str((acc.details or {}).get(k, "")) for k, _d in CRITERIA}
    aux = {str(k): _as_text((acc.auxiliary or {}).get(k)) for k, _d in AUXILIARY_SIGNALS}
    unresolved = sorted(k for k, v in criteria.items() if v == "unknown")
    return {"tri": TRI_COMPUTED,
            "reason": ("这些格子没查成（不是通过）：" + "、".join(unresolved)
                       if unresolved else ""),
            "criteria": criteria, "details": details, "auxiliary": aux,
            # 逐条行（每一行带"谁 / 哪一趟"那三格，这一面的三格恒为"编号不适用"）
            "rows": _acceptance_rows(criteria, details),
            "failed": sorted(acc.failed), "auxiliary_note": str(
                (acc.to_dict() or {}).get("auxiliary_note", ""))}


def _as_text(value: Any) -> str:
    """辅助读数收成字符串：`None`（读不出来）⇒ 空串，数字/布尔的字面量照写。"""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(value, ensure_ascii=False, default=str)


# ====================================================================== 6 本机
def _settings_reading() -> tuple[dict[str, Any], str, str]:
    """设置文件的三段读数（`settings.load_settings` + `settings.settings_path`）。

    设置是机器级的，不是工作区级的：落点由 `settings.settings_path()` 决定
    （`--path` → 环境变量 `AGENTFLOW_SETTINGS` → 包根下的 `settings.json`），
    与工作区根无关。所以本函数不吃 `root` 参数 —— 这一点写在这里免得读的人
    以为"设置读的是工作区里的那一份"。

    返回 `(读数, tri, reason)`。key 永远不出现在这里：`model.api_key` 只写
    "配没配"（`configured`）与掩码后的 `redacted()`（`modelgw.ModelSpec.redacted`
    在 key 非空时给 `***`）。判据 `tests/test_webui_readers.py` 有一条逐字符断言
    真 key 不在读数里。
    """
    from ..modelgw import ModelSpec, key_source, spec_for
    from ..settings import (MODELS_SECTION, SECRETARY_SECTION, TOOLCHAIN_KEYS,
                            WORKSPACE_KEYS, load_settings, model_settings, settings_path,
                            toolchain_settings, workspace_settings)

    path = settings_path()
    on_disk = bool(path is not None and Path(path).is_file())
    try:
        raw = load_settings()
    except Exception as exc:  # noqa: BLE001 - 设置文件坏掉 = 没查成，不是"没配"
        return ({"path": str(path) if path else "", "exists": on_disk,
                 "toolchain": {}, "model": {}, "workspace": {},
                 MODELS_SECTION: {}, SECRETARY_SECTION: {}},
                TRI_UNREADABLE, f"settings.load_settings 读不出来："
                                f"{type(exc).__name__}: {exc}")
    tool = {k: str(v) for k, v in toolchain_settings().items()}
    model = {k: str(v) for k, v in model_settings().items()}
    work = {k: str(v) for k, v in workspace_settings().items()}
    # 按角色 / 秘书那两档（业主 2026-10-14）：只给掩码后的形态 + "配没配"
    # （真 key 一个字都不进读数，与 `model.api_key` 同一条纪律）。
    slots: dict[str, Any] = {}
    for slot in sorted((raw.get(MODELS_SECTION) or {}) if isinstance(raw, dict) else {}):
        try:
            spec_slot, where = spec_for(str(slot))
        except Exception:  # noqa: BLE001 —— 单独一档坏掉不带走整份读数
            slots[str(slot)] = {"configured": False, "key_source": "", "problem": "读不出来"}
            continue
        red_slot = spec_slot.redacted()
        slots[str(slot)] = {"api_key": red_slot["api_key"], "base_url": red_slot["base_url"],
                            "name": red_slot["model"],
                            "vendor": red_slot["vendor"],
                            "reasoning_effort": red_slot["reasoning_effort"],
                            # 这一格必须取这一档自己的 `key_source`（`spec_for` 已经
                            # 按这一档算过 env/settings）。此前这里调的是全局 `key_source()` ——
                            # 它读的是 `model` 段 ⇒ 每一档都报同一个来源：`models.A` 的 key
                            # 明明是从这一档取的，读数却说"看的是 model 段"。
                            # 缺陷形态与"读数说谎"同族：数字自洽、没有任何地方会报错。
                            "key_source": spec_slot.key_source, "configured": spec_slot.configured,
                            "source": where}
    sec_cell: dict[str, Any] = {}
    try:
        sec_spec, sec_where = spec_for(secretary=True)
        red_sec = sec_spec.redacted()
        sec_cell = {"api_key": red_sec["api_key"], "base_url": red_sec["base_url"],
                    "name": red_sec["model"], "vendor": red_sec["vendor"],
                    "reasoning_effort": red_sec["reasoning_effort"],
                    "key_source": sec_spec.key_source,
                    "configured": sec_spec.configured, "source": sec_where,
                    "own_slot": (raw.get(SECRETARY_SECTION) or {}) if isinstance(raw, dict) else {}}
    except Exception as exc:  # noqa: BLE001
        sec_cell = {"configured": False, "problem": f"{type(exc).__name__}: {exc}"}
    if isinstance(sec_cell.get("own_slot"), Mapping):
        # 那一档自己的 key 也只以掩码出现
        from ..settings import MASKED_KEY as _MASK

        sec_cell["own_slot"] = {k: (_MASK if k == "api_key" and v else v)
                                for k, v in sec_cell["own_slot"].items()}
    # 推理强度（2026-10-10 所有者裁定「所有智能体都要能 thinking，默认 High」）：
    # 它同属"这台机器上的模型配置"，所以机器面必须报它 —— 否则台面上默认写着
    # 一切正常，而 `settings.json` 里那个值可能是 `off`。
    effort_raw = model.get("reasoning_effort", "") or ""
    effort_problem = ""
    try:
        spec = ModelSpec(base_url=model.get("base_url", "") or "",
                         model=model.get("name", "") or "",
                         api_key=model.get("api_key", "") or "",
                         # `vendor` 必须一起传（2026-10-14）：这一格的读数取自
                         # `spec.redacted()`，不传就等于"盘上写了厂商、机器面说没有"
                         # —— 而面板上那一格的初值正是从这份读数取的。
                         vendor=model.get("vendor", "") or "",
                         reasoning_effort=effort_raw)
        effort_shown = spec.redacted()["reasoning_effort"]
    except ValueError as exc:
        # 词表外的强度：这是"查过了、那格里是坏的"，不是崩溃，也不是"没配"。
        # 所以照旧给出成形的读数，只把这一段判成 unreadable 并把原值原样回显
        # （回显成缺省会让人以为配置生效了）。
        spec = ModelSpec(base_url=model.get("base_url", "") or "",
                         model=model.get("name", "") or "",
                         api_key=model.get("api_key", "") or "",
                         vendor=model.get("vendor", "") or "")
        effort_shown = effort_raw
        effort_problem = f"{type(exc).__name__}: {exc}"
    red = spec.redacted()
    reading = {
        "path": str(path) if path is not None else "",
        "exists": on_disk,
        "toolchain": {k: tool.get(k, "") for k in TOOLCHAIN_KEYS},
        "model": {"api_key": red["api_key"], "base_url": red["base_url"],
                  "name": red["model"],
                  # 厂商（2026-10-14）：`type_decls()` 里一直声明着这一格，而这里没给 ——
                  # 于是 `types.ts` 的 `SettingsReading.model.vendor` 名存实亡，
                  # 面板上那一格的初值永远取不到（盘上写了也不显示）。
                  # 这是"声明与读数差一格"，两个方向都该由判据管住（见
                  # `tests/test_role_models.py` 的读数那三条）。
                  "vendor": red["vendor"],
                  "reasoning_effort": effort_shown,
                  # key 是从哪一档取到的（`"env"` / `"settings"` / 空串）。
                  # 所有者 2026-10-10 的裁定是"key 从 config 里面接"——
                  # 这一格就是那句话在机器面上的读数：`settings` 才算成立，
                  # `env` 说明有一个环境变量盖住了配置文件（写错了也不会有人发现）。
                  "key_source": key_source(),
                  "configured": spec.configured},
        "workspace": {k: work.get(k, "") for k in WORKSPACE_KEYS},
        # 按角色那一档与秘书那一档（业主 2026-10-14）：`key_source` 报的是
        # 那份设置文件里 key 的来源，`configured` 是"这一档到底有没有 key"。
        MODELS_SECTION: slots,
        SECRETARY_SECTION: sec_cell,
        "raw_keys": sorted(raw) if isinstance(raw, dict) else [],
    }
    if effort_problem:
        return reading, TRI_UNREADABLE, ("settings.json 的 model.reasoning_effort 不是合法取值："
                                         + effort_problem)
    reason = ""
    if not on_disk:
        reason = (f"设置文件不在盘上（{path}）：三段全是『没配』这一档，"
                  "而不是『没查成』")
    return reading, (TRI_COMPUTED if on_disk else TRI_NOT_APPLICABLE), reason


def machine_face(root: str | Path = "", *, env: Mapping[str, str] | None = None) -> dict[str, Any]:
    """`GET /api/machine` 的读模型：`toolchain_report()` 的键 + 设置三段。

    `toolchain.toolchain_report` 的顶层键逐字保留（`model` / `provers` / `lean_ready` /
    `lean_path` / `lean_version` / `mathlib` / `can_do_formal`），另加 `settings`
    （见 :func:`_settings_reading`）与 `tri` / `reason`。

    三态：`provers.checked is False` ⇒ 探测没跑完 ⇒ 整面 `unreadable` + `reason`
    （不是 `available=[]` —— 那是"探测过了，一个都没找到"，两者必须分得开）；
    设置文件不在盘上 ⇒ 那一栏 `not_applicable`，而整面在工具链读得出来时仍是
    `computed`（一部分没配不等于整面没查成）。
    """
    from ..toolchain import toolchain_report

    problems: list[str] = []
    try:
        report = dict(toolchain_report(env))
    except Exception as exc:  # noqa: BLE001
        # 工具链那一趟读不出来 ⇒ 整面 `unreadable`，但设置那一段照样给出来：
        # 病因常常就在那一段里。最现成的一例是 `settings.json` 的
        # `model.reasoning_effort` 拼成了词表外的值 —— `toolchain_report` 会经
        # `_model_spec`（`spec_from_env`）把它抛上来，于是这一格若不保留，
        # 台面只会说"工具链探测读不出来"，把排查方向指到 Lean 上去，
        # 而真正要改的是模型那一格。
        report = {}
        problems.append(f"toolchain.toolchain_report 读不出来：{type(exc).__name__}: {exc}")
    provers = report.get("provers") or {}
    if provers.get("checked") is False:
        problems.append("工具链探测没跑完（provers.checked=false）："
                        + str(provers.get("reason") or "没给理由"))
    settings, set_tri, set_reason = _settings_reading()
    if set_tri == TRI_UNREADABLE:
        problems.append(set_reason)
    out = dict(report)
    out["settings"] = settings
    out["settings_tri"] = set_tri
    out["settings_reason"] = set_reason
    out["tri"] = TRI_UNREADABLE if problems else TRI_COMPUTED
    out["reason"] = "；".join(problems)
    return out


# ====================================================================== 7 预算
def budget_face(root: str | Path) -> dict[str, Any]:
    """`GET /api/budget` 的读模型：总额度 / 已花 / 剩余 / 追加历史 + 两个归口。

    两件事刻意来自两个地方（`budget` 模块的 docstring 逐字）：

    - 总额度来自盘上的寄存器（`<工作区>/budget.json`，`budget.reading`）；
    - 已花永远来自 `usage_ledger`（`TokenMeter.spent()`/`by_role()`/`by_scope()`）——
      寄存器里不记花销，两处记账必然漂移。

    三态：账本读不出来 ⇒ `spent_tri="unreadable"` 且 `spent_usd=None`
    （不是 0 —— "没查成"与"一分钱没花"在本仓是两个词）；寄存器读不出来
    ⇒ `tri="unreadable"` + `problem` 原样带出（`budget.reading` 那一档已经这么做了，
    这一层只透传，不二次判断）。寄存器不在盘上 ⇒ `not_applicable`（还没设过预算，
    合法初态），而不是"没查成"。
    """
    from .. import budget as B
    from ..store import Store
    from ..tokenmeter import TokenMeter

    root_p = Path(str(root))
    spent: dict[str, Any] = {}
    by_role: dict[str, Any] = {}
    by_scope: dict[str, Any] = {}
    spent_problem = ""
    try:
        meter = TokenMeter(Store(root_p))
        spent = dict(meter.spent() or {})
        by_role = dict(meter.by_role() or {})
        by_scope = dict(meter.by_scope() or {})
    except Exception as exc:  # noqa: BLE001 - 读数层：读不到就如实说没查成
        spent_problem = (f"usage_ledger 读不出来：{type(exc).__name__}: {exc}"
                         "（已花那一栏记「没查成」，不记 0）")
    snap = B.reading(root_p,
                     spent_usd=(float(spent["usd"]) if spent else None))
    snap.update({
        "spent_tri": TRI_UNREADABLE if spent_problem else TRI_COMPUTED,
        "spent_reason": spent_problem,
        "entries": int(spent.get("entries") or 0) if spent else None,
        "tokens": int(spent.get("tokens") or 0) if spent else None,
        "attempts": int(spent.get("attempts") or 0) if spent else None,
        "added_count": len(snap.get("added") or []),
        "by_role": by_role,
        "by_scope": by_scope,
    })
    if spent_problem and snap.get("tri") != TRI_UNREADABLE:
        snap["tri"] = TRI_UNREADABLE
        snap["reason"] = "；".join(x for x in (str(snap.get("reason") or ""),
                                               spent_problem) if x)
    return snap


# ====================================================================== 8 在飞
def live_face(root: str | Path) -> dict[str, Any]:
    """`GET /api/live` 的读模型：在飞的循环 + 活进程 + 停机开关 + 近几条停机历史。

    为什么这三样在一格里（业主 2026-10-12：「特别照顾……对多智能体系统的监控能力」）：
    用户问"现在到底还有没有人在跑"时，`running_loops` 的会话面与 `live_pids` 的
    进程面缺一路都会漏（那边 docstring 逐字写了两个方向的漏法），而停机开关是
    "我按过停没有/谁按的"的唯一盘上事实 —— 三者分开成三条端点，页面就得自己拼，
    拼错的那一版会把"有进程在跑"显示成"没事"。

    行一律用 `stopctl` 自己的字典逐字透传（`running` / `live` / 历史行）：
    在这一层再抄一份字段表就是第二份形状定义，必然与那边漂移。
    """
    from .. import stopctl as SC

    root_p = Path(str(root))
    problems: list[str] = []
    loops: dict[str, Any] = {"running": [], "live": [], "unreadable_sessions": [],
                             "answer": "没查成"}
    try:
        got = SC.running_loops(root_p)
        loops = dict(got) if isinstance(got, Mapping) else loops
    except Exception as exc:  # noqa: BLE001
        problems.append(f"stopctl.running_loops 读不出来：{type(exc).__name__}: {exc}")
    switch: dict[str, Any] = {}
    try:
        got_switch = SC.read_stop(root_p)
        switch = dict(got_switch) if isinstance(got_switch, Mapping) else {}
    except Exception as exc:  # noqa: BLE001
        problems.append(f"stopctl.read_stop 读不出来：{type(exc).__name__}: {exc}")
    history: list[dict[str, Any]] = []
    try:
        history = [dict(r) for r in SC.stop_history(root_p, limit=5)]
    except Exception as exc:  # noqa: BLE001
        problems.append(f"stopctl.stop_history 读不出来：{type(exc).__name__}: {exc}")
    interrupts: list[dict[str, Any]] = []
    try:
        interrupts = [dict(r) for r in SC.interrupt_history(root_p, limit=5)]
    except Exception as exc:  # noqa: BLE001
        problems.append(f"stopctl.interrupt_history 读不出来：{type(exc).__name__}: {exc}")
    return {
        "tri": TRI_UNREADABLE if problems else TRI_COMPUTED,
        "reason": "；".join(problems),
        "root": str(root_p),
        "answer": str(loops.get("answer") or ""),
        "running": list(loops.get("running") or []),
        "live": list(loops.get("live") or []),
        "unreadable_sessions": list(loops.get("unreadable_sessions") or []),
        "switch": switch,
        "switch_present": bool(switch.get("present") or switch.get("path")),
        "history": history,
        "interrupts": interrupts,
    }


# ====================================================================== 9 用量
def usage_face(root: str | Path) -> dict[str, Any]:
    """`GET /api/usage` 的读模型：`usage_ledger` 的汇总（总计 + 两个归口 + 最近几笔）。

    「最近几笔」按文件顺序取尾部（`usage_ledger` 是 append-only 的 JSON 表）——
    不排序、不猜时间戳：那一列的名字由 `schema.UsageEntry` 定，这一层不改口径。
    """
    from ..store import Store
    from ..tokenmeter import TokenMeter

    root_p = Path(str(root))
    try:
        meter = TokenMeter(Store(root_p))
        rows = Store(root_p).rows("usage_ledger")
        recent = [dict(r) for r in rows[-10:]]
        return {
            "tri": TRI_COMPUTED, "reason": "",
            "path": str(root_p / "data" / "usage_ledger.json"),
            "entries": len(rows),
            "spent": dict(meter.spent() or {}),
            "by_role": dict(meter.by_role() or {}),
            "by_scope": dict(meter.by_scope() or {}),
            "retry_overhead": dict(meter.retry_overhead() or {}),
            "recent": recent,
        }
    except Exception as exc:  # noqa: BLE001 - 读不到就是没查成，不许折成 0
        return {"tri": TRI_UNREADABLE,
                "reason": f"usage_ledger 读不出来：{type(exc).__name__}: {exc}",
                "path": str(root_p / "data" / "usage_ledger.json"),
                "entries": None, "spent": {}, "by_role": {}, "by_scope": {},
                "retry_overhead": {}, "recent": []}


# ====================================================================== 10 状态报告
def status_reports_face(root: str | Path) -> dict[str, Any]:
    """`GET /api/status-reports` 的读模型：`out/review/STATUS-*.md|json` 最近几份。

    这一条补的是一个真缺口（`draft/112` §4.2 第 3 条）：`statusreport` 一直在写
    `STATUS-<ts>.{md,json}`，而盘上没有任何消费者 —— 写了没人读，等于没写。
    """
    root_p = Path(str(root))
    out_dir = root_p / "out" / "review"
    try:
        mds = sorted(out_dir.glob("STATUS-*.md"))
        jsons = {p.stem: p for p in out_dir.glob("STATUS-*.json")}
    except OSError as exc:
        return {"tri": TRI_UNREADABLE, "reason": f"读 {out_dir} 失败：{exc}",
                "dir": str(out_dir), "count": None, "reports": []}
    reports: list[dict[str, Any]] = []
    for md in mds[-5:]:
        stem = md.stem
        js = jsons.get(stem)
        row: dict[str, Any] = {
            "name": md.name, "stem": stem, "path": str(md),
            "json_path": str(js) if js is not None else "",
            "bytes": None, "ts": "",
        }
        try:
            row["bytes"] = md.stat().st_size
        except OSError:
            row["bytes"] = None
        row["ts"] = stem[len("STATUS-"):] if stem.startswith("STATUS-") else stem
        reports.append(row)
    return {"tri": TRI_COMPUTED if reports else TRI_NOT_APPLICABLE,
            "reason": "" if reports else "out/review 下还没有 STATUS-* 报告（还没写过）",
            "dir": str(out_dir), "count": len(mds), "reports": reports}


# ====================================================================== HTTP 外壳
def _json_of(handler: Any, obj: Any) -> None:
    """按 `WebHandler._json` 的形态回一份 JSON（A 线的那个方法在这里被复用）。"""
    handler._json(200, obj)  # noqa: SLF001 - 处理器与 handler 是同一族的约定接口


def handle_state(handler: Any, params: Mapping[str, str],
                 query: Mapping[str, Sequence[str]]) -> None:
    """`GET /api/state`：快照那份 JSON（裁定 2b 之后这条端点的归属在这里）。

    回的是 :func:`state_face` 里那张 `snapshot` —— 也就是 `webui.state.snapshot(root)`
    的返回值本身，不是外面那层三态包装：`/api/state` 是既有公开面，
    `temp/_verify_w0.py` 对账的顶层 10 键与页面形状都是按它量的（迁路由不许动它）。

    `handle_state_face`（回 `{tri, snapshot, reason}`）那个三态形态刻意没有留下：
    同一个端点上摆两个形状只差一个字的处理器，早晚有人把错的那个登记进表里。
    要三态读数的地方读 `readers.state_face` 这个函数（它是读模型，不是端点）。
    """
    del params, query
    _json_of(handler, state_face(handler.root)["snapshot"])


def handle_run_view(handler: Any, params: Mapping[str, str],
                    query: Mapping[str, Sequence[str]]) -> None:
    """`GET /api/run/{sid}`：一趟详情的 JSON（`Run` + `report` + `checkpoint`）。"""
    del query
    _json_of(handler, run_view(handler.root, str(params.get("sid", ""))))


def _query_text(query: Mapping[str, Sequence[str]], name: str) -> str:
    """查询串里的一个值（缺省 = 空串；同名给多次时取第一个，与既有处理器同一条口径）。"""
    vals = query.get(name) or []
    return str(vals[0]) if vals else ""


def _read_cursor(query: Mapping[str, Sequence[str]], name: str,
                 default: int) -> tuple[int | None, str]:
    """把 `?since_index=` / `?limit=` 读成一个非负整数；读不成返回 `(None, 理由)`。

    空串与"这个参数没给"同档（用 `default`）：`?since_index=` 这种空值不该被读成 0
    还是"非法"这件事没有必要让调用方猜。非整数、负数各给一句点名的理由 ——
    由调用方回 400（`/api/*` 一律 JSON，裁定 Q1）。
    """
    raw = _query_text(query, name).strip()
    if raw == "":
        return default, ""
    try:
        value = int(raw)
    except ValueError:
        return None, f"{name} 必须是整数，给的是 {raw!r}"
    if value < 0:
        return None, f"{name} 不能是负数，给的是 {value}"
    return value, ""


def handle_run_events(handler: Any, params: Mapping[str, str],
                      query: Mapping[str, Sequence[str]]) -> None:
    """`GET /api/run/{sid}/events`：一趟的逐条事件（`?since_index=` 与 `?limit=`）。

    参数校验收在这一格（HTTP 那一层），读模型自己只做钳位：非法参数回 400 + JSON
    （`/api/*` 一律 JSON，裁定 Q1）—— 今天这个服务里 400 是头一份，所以形状照
    `handle_unknown` 那份 JSON 404 写（`ok` / `tri` / `reason`），另外把两个参数原样
    回显：读的人一眼看得出是哪一个被拒了。

    三条"非法"：

    - `since_index` / `limit` 不是整数，或是负数；
    - `limit=0`：要 0 行的话就没有一页可取，而"回一页空的"会与"会话里已经没有更多事件"
      （合法结果）在读数上长得一样 —— 所以这一档写 400，不写"空的一页"。

    `limit` 超上限不是非法：按上限截断并在 `reason` 里说明（题 T2-a 的口径）。
    """
    sid = str(params.get("sid", ""))
    since, why_since = _read_cursor(query, "since_index", 0)
    limit, why_limit = _read_cursor(query, "limit", EVENTS_LIMIT_DEFAULT)
    problems = [w for w in (why_since, why_limit) if w]
    if limit == 0:
        problems.append("limit 必须 >= 1（要 0 行的话没有一页可取）")
    if problems or since is None or limit is None:
        handler._json(400, {  # noqa: SLF001 - 与 handler 是同一族的约定接口
            "ok": False, "tri": TRI_NOT_APPLICABLE,
            "reason": "；".join(problems) or "端点参数不合法",
            "sid": sid,
            "since_index": _query_text(query, "since_index"),
            "limit": _query_text(query, "limit"),
        })
        return
    _json_of(handler, run_events(handler.root, sid, since_index=since, limit=limit))


def handle_evidence(handler: Any, params: Mapping[str, str],
                    query: Mapping[str, Sequence[str]]) -> None:
    """`GET /api/evidence`：证据链七栏的 JSON。"""
    del params, query
    _json_of(handler, evidence_chain(handler.root))


def handle_artifacts(handler: Any, params: Mapping[str, str],
                     query: Mapping[str, Sequence[str]]) -> None:
    """`GET /api/artifacts`：产物面的 JSON（可带 `?run_dir=`）。"""
    del params
    vals = query.get("run_dir") or []
    run_dir = str(vals[0]) if vals else None
    _json_of(handler, artifacts_face(handler.root, run_dir=run_dir))


def handle_acceptance(handler: Any, params: Mapping[str, str],
                      query: Mapping[str, Sequence[str]]) -> None:
    """`GET /api/acceptance`：收工门的 JSON（`?project_dir=` `?report_path=` `?cap_usd=`）。"""
    del params

    def one(name: str) -> str:
        vals = query.get(name) or []
        return str(vals[0]) if vals else ""

    cap_raw = one("cap_usd").strip()
    try:
        cap: float | None = float(cap_raw) if cap_raw else None
    except ValueError:
        cap = None
    _json_of(handler, acceptance_face(handler.root, project_dir=one("project_dir"),
                                      report_path=one("report_path"), cap_usd=cap))


def handle_machine(handler: Any, params: Mapping[str, str],
                   query: Mapping[str, Sequence[str]]) -> None:
    """`GET /api/machine`：本机读数的 JSON。"""
    del params, query
    _json_of(handler, machine_face(handler.root))


def handle_budget_view(handler: Any, params: Mapping[str, str],
                       query: Mapping[str, Sequence[str]]) -> None:
    """`GET /api/budget`：预算读数（总额度 / 已花 / 剩余 / 追加历史）。

    名字末尾那个 view 后缀不是装饰（2026-10-12 判据当场抓到的）：写面 `writes.py` 里
    也有一个同名的 `handle_budget`（`POST /api/budget`，追加额度），而
    `routes.handler_for` 是按名字在三条子表里找处理器的 —— 两个模块用同一个
    名字时，先被查到的那个（readers）会吃掉写请求：实测 `POST /api/budget` 回了
    一份读数的 JSON 和 200，`--allow-writes` 那一道闸门一步都没走。
    """
    del params, query
    _json_of(handler, budget_face(handler.root))


def handle_live(handler: Any, params: Mapping[str, str],
                query: Mapping[str, Sequence[str]]) -> None:
    """`GET /api/live`：在飞的循环 / 活进程 / 停机开关与历史。"""
    del params, query
    _json_of(handler, live_face(handler.root))


def handle_usage(handler: Any, params: Mapping[str, str],
                 query: Mapping[str, Sequence[str]]) -> None:
    """`GET /api/usage`：用量台账的汇总（总计 + 按角色 + 按归口 + 最近几笔）。"""
    del params, query
    _json_of(handler, usage_face(handler.root))


def handle_status_reports(handler: Any, params: Mapping[str, str],
                          query: Mapping[str, Sequence[str]]) -> None:
    """`GET /api/status-reports`：`out/review/STATUS-*` 最近几份。"""
    del params, query
    _json_of(handler, status_reports_face(handler.root))


# ====================================================================== 2c 对话（R92）
#: 一条对话线最多印多少字（超了截断并把"截过"写在正文里）。
#:
#: 为什么必须有界：`agent_run_end.final` 与 `agent_message.body` 动辄上万字
#: （本机实测：M 的一份 final 一万六千字），一次几十条塞进浏览器既慢又没人看。
#: 截断这件事不许静默（本项目的三态纪律）：截过的线自己带着那句话。
CHAT_LINE_CLIP = 4000

#: 一次最多给多少条对话线（取最近的这么多条，总数照实报）。
CHAT_LINES_MAX = 300

#: 对话线的三种身份。业主 2026-10-13 要的是"用户 ↔ 主控"的对话框，所以前两档是主角；
#: 其余角色在公共频道/私有频道说的话单列 `team` 一档（它们对看的人有用，但不是"对话"，
#: 页面默认把它们折起来）。
CHAT_WHO = ("user", "conductor", "team")


def _chat_clip(raw: Any, limit: int = CHAT_LINE_CLIP) -> tuple[str, bool]:
    """一条对话正文（截断时把总字数写进正文里 —— 截了多少要看得见）。"""
    text = "" if raw is None else str(raw)
    if limit <= 0 or len(text) <= limit:
        return text, False
    return (text[:limit] + f"\n……（这一条共 {len(text)} 字，这里只印前 {limit} 字）",
            True)


#: 允许"从同岗的 `agent_run_start` 回填编号"的那几个 kind（见 :func:`_single_run_start_ids`）。
#:
#: 为什么只这几个：回填出来的编号是一句"这一条属于那一趟"的断言，只有当这一条的 `role`
#: 就是说话那一方时才成立。`agent_run_end` / `agent_message` 的 `role` 是说话的角色；
#: `user_question` 的 `role` 是"问的人"（三处 `userio` 的注释逐字：那是"回答归谁"的归属
#: 字段），也是说话那一方 ⇒ 三个都可以回填。
#:
#: 刻意不在里面的两类：`user_answer`（它的 `role` 是"谁问的"，而说话的是用户 ——
#: 把用户的回答回填成某一趟的编号，等于说"这句话是那一趟说的"）与 `agent_interjection`
#: （`from` 是插话的人，`role` 在这条事件里没有口径）。这两类的 `missing` 是事实，
#: 不是缺口：它们本来就不属于任何一趟。
CHAT_INHERIT_KINDS = ("agent_run_end", "agent_message", "user_question")


def _single_run_start_ids(events: Sequence[Mapping[str, Any]]) -> dict[str, str]:
    """每一岗在这次会话里"唯一那一趟"的绝对编号；拿不准的岗不进结果。

    业主 2026-10-21（"全面接入"第二步的兼容半）：老事件（写侧补 `task_id` 之前落盘的
    `agent_run_end`）盘上没有编号，于是"某某交付"那条线只能一直标 `missing`。这一条
    函数算的是"能回填到什么程度"：

    口径（三档，逐条都能在盘上对上）：

    - 同一会话内，取该 `role` 的 `agent_run_start` 事件的 `task_id`；
    - 这些编号去重后恰好一个，且每一条 start 都带着编号 ⇒ 回填它（`inherited`）；
    - 去重后有两个以上不同编号 ⇒ 不猜（那一段里这一岗跑过不止一趟，收工那一行属于
      哪一趟盘上没有证据）；
    - 只要有一条 start 没记编号 ⇒ 也不猜（"老的那一趟"与"新的那一趟"分不开）。

    "被拒的续跑"（带 `resume_refused`）不参与计数：它也落一条 `agent_run_start`，但它
    一步都没跑、不会有配对的收工事件 —— 让它参与就会把"某一次被拒过续跑"的整段会话
    回填全部否掉（那是把一个不相关的读数折成 missing）。

    返回 `{role: task_id}`，只含拿得准的岗（空串 / 空角色不进结果）。
    """
    seen: dict[str, list[str]] = {}
    for ev in events:
        if str(ev.get("kind") or "") != "agent_run_start":
            continue
        if str(ev.get("resume_refused") or ""):
            continue
        role = str(ev.get("role") or "")
        seen.setdefault(role, []).append(str(ev.get("task_id") or ""))
    out: dict[str, str] = {}
    for role, ids in seen.items():
        if not role or not ids or any(not one for one in ids):
            continue
        distinct = sorted(set(ids))
        if len(distinct) == 1:
            out[role] = distinct[0]
    return out


def _chat_role(event: Mapping[str, Any]) -> tuple[str, str]:
    """这条事件里"说话的那个角色"，以及这一格是从哪来的（`role_source` 三档）。

    取值口径（三档，与 `task_id_source` 同一套纪律）：

    - `event`：事件自带 `role`（绝大多数事件都这样，`agent_run_start` / `agent_run_end`
      / `user_question` / `user_answer` 都是）⇒ 原样用；
    - `from`：事件没有 `role` 而 `kind` 是 `agent_message` ⇒ 用 `from`。那条记录写的是
      "这条报文是谁发的"，`from` 是它唯一的身份格（`send_message` 只写
      `from` / `to` / `channel`），于是用它补齐是可复核的，不是猜；
    - `missing`：两格都没有 ⇒ `("", "missing")`。页面据此显示「（未记录角色）」，
      绝不替它编一个。

    为什么只对 `agent_message` 看 `from`：别的 kind 的 `from` 不是角色 ——
    `agent_interjection` 的 `from` 是用户（`userio.USER`），拿它当角色会让"用户的插话"
    在角色那一格印成 `user`，而角色是 A–H / M / V 那个编号空间里的东西。用户那几条线
    "谁在说话"由 `who="user"` 那一格说（页面印"你"），不需要角色来重复。
    """
    role = str(event.get("role") or "")
    if role:
        return role, "event"
    if str(event.get("kind") or "") == "agent_message":
        sender = str(event.get("from") or "")
        if sender:
            return sender, "from"
    return "", "missing"


def _chat_line(index: int, event: Mapping[str, Any]) -> dict[str, Any] | None:
    """一条会话事件 → 一条对话线；不是"对话"的事件回 `None`。

    映射口径（逐条都能在盘上对上，不许靠猜）：

    | 盘上的 kind | 谁的线 | 印什么 |
    |---|---|---|
    | `agent_run_start`（role=M 且不是被别的角色召唤的） | `user` | 那一句话任务（`resumed_from>0` ⇒ 标"接着上一步说"） |
    | `user_answer` | `user` | 用户的回答 |
    | `agent_interjection`（`from` = 用户） | `user` | 插话正文 |
    | `user_question` | `conductor` | 主控问的话 + 选项 + qid |
    | `agent_message`（`from`=M） | `conductor` | 主控发给谁/公共频道的那段话 |
    | `agent_message`（别的角色） | `team` | 同上 |
    | `agent_run_end`（role=M，有 final） | `conductor` | 主控这一趟的交付 |
    | `agent_run_end`（别的角色，有 final） | `team` | 那个角色的交付 |

    刻意不进对话的两类：`agent_note`（协议层的步级留痕，如"system 重发：第 1 步"）与
    `agent_step`/`llm_call`（工具与模型调用）—— 它们留在「一趟详情」的逐条事件里。
    """
    from .. import userio as U
    from ..schema import CONDUCTOR_ROLE as M

    kind = str(event.get("kind") or "")
    role, role_source = _chat_role(event)
    who = ""
    title = ""
    text = ""
    qid = ""
    options: list[dict[str, str]] = []
    if kind == "agent_run_start":
        if role != M or str(event.get("summoned_by") or "") not in ("", M):
            return None
        who = "user"
        title = "接着上一步说" if int(event.get("resumed_from") or 0) else "起一趟"
        text = str(event.get("task") or "")
    elif kind == U.ANSWER_KIND:
        who = "user"
        qid = str(event.get("qid") or "")
        title = f"回答 {qid}".strip()
        text = str(event.get("answer") or "")
    elif kind == "agent_interjection":
        if str(event.get("from") or "") != U.USER:
            return None
        who = "user"
        title = str(event.get("subject") or "插话")
        text = str(event.get("body") or "")
    elif kind == U.ASK_KIND:
        who = "conductor"
        qid = str(event.get("qid") or "")
        title = f"问你（{qid}）" if qid else "问你"
        text = str(event.get("text") or "")
        for raw in event.get("options") or ():
            view = U.option_view(raw)
            options.append({"label": str(view.get("label") or ""),
                            "description": str(view.get("description") or "")})
    elif kind == "agent_message":
        who = "conductor" if str(event.get("from") or "") == M else "team"
        title = (f"{event.get('from') or '?'} → {event.get('to') or '?'}"
                 f"（{event.get('channel') or '?'}）")
        text = str(event.get("body") or "")
    elif kind == "agent_run_end":
        text = str(event.get("final") or "")
        if text.strip() == "":
            return None          # 没有交付的那一趟不进对话（它没有"话"）
        who = "conductor" if role == M else "team"
        title = "主控交付" if who == "conductor" else f"{role} 交付"
    else:
        return None
    body, clipped = _chat_clip(text)
    # 业主 2026-10-21（"全面接入"）：每一条对话线都要能回答"是哪个绝对编号的哪个角色在说话"。
    # 绝对编号从事件里取（`task_id`；`agent_message` 那一路写的是 `from_task_id`），
    # 两个都没有就留空串 —— 空串在页面上显示成"（未记录编号）"，比编一个假编号好。
    #
    # 这一层只认两种来源：`event`（事件里真有）与 `missing`（这条事件没记）。"从同一岗的
    # `agent_run_start` 推出来"的那一档（`inherited`）刻意不在这里做：那是 `chat_face`
    # 的事 —— 它要看整段会话才判得准，而本函数的输入只有一条事件。于是直接调本函数的人
    # 永远读不到 `inherited`；要拿回填后的读数就调 `chat_face`（见 `_single_run_start_ids`）。
    task_id = str(event.get("task_id") or event.get("from_task_id") or "")
    line: dict[str, Any] = {"index": index, "who": who, "role": role, "kind": kind,
                            # 角色那一格的来路（见 `_chat_role`）：`event`（事件自带
                            # `role`）/ `from`（`agent_message` 只有 `from`，读侧用它补）/
                            # `missing`（两格都没有 —— 页面显示"（未记录角色）"，判据据此
                            # 要求"不许留空、也不许猜一个"）。
                            "role_source": role_source,
                            "task_id": task_id,
                            # 三档口径（值域）：`event`（事件里真有）/ `inherited`
                            # （`chat_face` 从同岗唯一那一趟的 start 回填的，本函数不产它）/
                            # `missing`（这条事件确实没记 —— 页面显示"（未记录编号）"，
                            # 判据据此要求"不许悄悄空着不标"）。
                            "task_id_source": "event" if task_id else "missing",
                            "ts": str(event.get("ts") or ""), "title": title,
                            "text": body, "clipped": clipped}
    if qid:
        line["qid"] = qid
    if options:
        line["options"] = options
    return line


def chat_face(root: str | Path, sid: str = "", *,
              lines_max: int = CHAT_LINES_MAX) -> dict[str, Any]:
    """`GET /api/chat` 的读模型：一段会话里的"用户 ↔ 主控"对话（逐条、有界）。

    业主 2026-10-13：「用户和主控的对话不应该只做成只能一句话启动任务，应该是能对话的」。
    这一面就是那句话的读侧 —— 把一段会话里属于对话的事件投影成逐条线，
    与「一趟详情」的逐条事件分开：后者是"盘上发生了什么"（含工具与模型调用），
    这一面是"谁对谁说了什么"。

    口径四条：

    - `sid` 不给 ⇒ 取最近的那一段（按 `last_ts`），并在 `reason` 里写明这件事
      （那是替用户做的选择，不许无声无息）；
    - 没有会话 ⇒ `not_applicable` + "还没有会话（合法初态）"，不是错误；
    - 会话文件不在盘上 ⇒ `unreadable`（`sid` 是调用方给的，找不到就是"没查成"）；
    - 有坏行 ⇒ `unreadable` + 坏行数，读得出来的那些线照常给（与 `run_events` 同一条）；
    - 线是有界的：只给最近 `lines_max` 条，`total`/`shown` 照实报，截断逐条标明。

    编号那一格（业主 2026-10-21「全面接入」第二步的兼容半）：每条线都有 `task_id` 与
    `task_id_source`，来源分三档 —— `event`（事件里真有）、`inherited`（老事件没记，但
    同一岗在这段会话里唯一那一趟的 `agent_run_start` 有编号 ⇒ 用它，判据在
    :func:`_single_run_start_ids`）、`missing`（拿不准或确实没记）。回填只在唯一时发生：
    同一岗跑过两趟以上（或有一条 start 自己没记编号）就照实标 `missing`，不猜。

    角色那一格：每条线都有 `role` 与 `role_source`，来源同样三档 —— `event`（事件自带
    `role`）、`from`（`agent_message` 只记了 `from`，读侧用它补齐，见 :func:`_chat_role`）、
    `missing`（两格都没有 ⇒ 页面显示「（未记录角色）」，不猜）。这一格补的是真机读数里
    `E → D（private）` 那条线"哪个角色"空着的缺口：那条记录只有 `from`，而 `from` 就是
    发信人的角色。为什么不交给前端去解析标题里的 `E → D` —— 标题是给人看的一句话，
    不是数据（改一次文案就会把它悄悄拆掉，而没有任何判据会红）。
    """
    root_p = Path(str(root))
    sessions = [{"sid": str(s.get("sid") or ""),
                 "last_ts": str(s.get("last_ts") or ""),
                 "events": int(s.get("events") or 0),
                 "bad_lines": int(s.get("bad_lines") or 0)}
                for s in SS.list_sessions(root_p)]
    chosen = str(sid or "")
    notes: list[str] = []
    if chosen == "":
        if not sessions:
            return {"tri": TRI_NOT_APPLICABLE, "sid": "", "lines": [], "total": 0,
                    "shown": 0, "clipped": False, "sessions": [],
                    "reason": "这个工作区还没有会话（合法初态，不是没查成）"}
        # 默认选哪一段（R94 实测的坑）：不能只看 `last_ts` —— 框架自己会往"今天那段
        # 缺省会话"里写结算类事件（`task_end`，没有 sid），它的 `last_ts` 往往比真跑过的
        # 那一段还新，于是对话框一打开就停在一段几乎没有来回的会话上。
        # 口径：先在最近的若干段里找最近起过一趟（有 `agent_run_start` 的对话线）
        # 的那一段，找不到才退回"最近有动静的那一段"，并把这次选择写进 `reason`。
        def _has_run_start(row: dict[str, str]) -> bool:
            events, _bad = SS.read_session(root_p, sid=row["sid"])
            return any(_chat_line(i, ev) is not None and str(ev.get("kind") or "")
                       == "agent_run_start" for i, ev in enumerate(events))

        newest_first = sorted(sessions, key=lambda s: s["last_ts"], reverse=True)
        pick = next((s for s in newest_first[:10] if _has_run_start(s)), None)
        if pick is None:
            pick = newest_first[0]
            notes.append(f"没指定会话 ⇒ 取了最近有动静的那一段（{pick['sid']}）")
        else:
            notes.append(f"没指定会话 ⇒ 取了最近起过一趟的那一段（{pick['sid']}）")
        chosen = pick["sid"]
    path = SS.session_path(root_p, chosen)
    if not path.is_file():
        return {"tri": TRI_UNREADABLE, "sid": chosen, "lines": [], "total": 0,
                "shown": 0, "clipped": False, "sessions": sessions,
                "reason": f"会话文件不在盘上：{path}"}
    events, bad = SS.read_session(root_p, sid=chosen)
    mapped = [line for i, ev in enumerate(events)
              if (line := _chat_line(i, ev)) is not None]
    # 老数据的有把握回填（`inherited`）：只补"某个代理说的话"那两类线，且只在同一岗
    # 唯一那一趟有编号时才补 —— 判据与理由全在 `_single_run_start_ids` 里。
    # 不补的三类：`event`（本来就有）、用户那几条（用户的话不属于任何一趟）、
    # 以及 `missing` 但拿不准的岗（两趟以上 / start 自己没记编号）。
    inheritable = _single_run_start_ids(events)
    if inheritable:
        for line in mapped:
            if str(line.get("task_id_source")) != "missing":
                continue
            if str(line.get("kind") or "") not in CHAT_INHERIT_KINDS:
                continue
            one = str(inheritable.get(str(line.get("role") or "")) or "")
            if not one:
                continue
            line["task_id"] = one
            line["task_id_source"] = "inherited"
    total = len(mapped)
    shown = mapped[-int(lines_max):] if int(lines_max) > 0 else mapped
    if total > len(shown):
        notes.append(f"只给最近的 {len(shown)} 条对话（这一段共 {total} 条）")
    if bad:
        notes.append(f"会话有 {len(bad)} 条坏行：" + "；".join(bad[:3]))
    return {"tri": TRI_UNREADABLE if bad else TRI_COMPUTED,
            "sid": chosen, "lines": shown, "total": total, "shown": len(shown),
            "clipped": any(bool(l["clipped"]) for l in shown),
            "sessions": sessions, "reason": "；".join(notes)}


def handle_chat(handler: Any, params: Mapping[str, str],
                query: Mapping[str, Sequence[str]]) -> None:
    """`GET /api/chat?sid=<会话号>&lines=<最多几条>`：对话页那一段来回。"""
    del params
    sid = str((query.get("sid") or [""])[0])
    raw = str((query.get("lines") or [""])[0])
    try:
        lines_max = int(raw) if raw.strip() else CHAT_LINES_MAX
    except ValueError:
        lines_max = CHAT_LINES_MAX
    _json_of(handler, chat_face(handler.root, sid, lines_max=lines_max))


# ====================================================================== 11 名册（roster）
#: 一棵名册树最多给几个节点（超了截断，并在 `reason` 里说清截了多少）。
#:
#: 为什么要有这个闸：一个端点得有自己的规模上限 —— 真机最大的工作区今天只有几十个
#: 节点，但"名册是 append-only 的事件流"意味着它只增不减，而这一页是给人看的。
ROSTER_NODES_MAX = 500

#: 一个节点的收件箱最多列几条（条数照实报，列表截断写在 `inbox.more` 里）。
ROSTER_INBOX_ITEMS = 10

#: 收件箱一条正文最多印多少字（超了截断并把"截过"写进正文）。
ROSTER_INBOX_CLIP = 160

#: 名册目录（与 `secretary.ROSTER_DIR` 同一个落点；这一层只读它）。
#:
#: 为什么是 `out/roster/` 而不是 `data/`：名册是秘书写的 append-only 事件流
#: （`<父的绝对编号>.jsonl`），与库表不是一回事 —— `secretary.py` 的注释逐字写了
#: 这个落点，以及"为什么不放 `out/secretary/`"（会被 `*.jsonl` 的目录 glob 混进
#: 秘书决定台账那一面）。
_ROSTER_DIR: tuple[str, ...] = ("out", "roster")

#: 名册目录里的三个旁支文件（与 `<父>.jsonl` 同目录、同后缀，但不是"某个父名下的
#: 子代理"）：电话簿 `-index` / 槽位池事件 `-surfaces` / 销号名单 `-retired`。
#: 折叠这一棵树时不许把它们混进去 —— 混进去一个名字就会变成两个节点。
_ROSTER_SIDE_SUFFIX: tuple[str, ...] = ("-index.jsonl", "-surfaces.jsonl",
                                        "-retired.jsonl")


def _roster_files(dir_p: Path) -> tuple[list[tuple[str, Path]], str]:
    """名册目录里"哪个父有哪一份名册"：`([(父的绝对编号, 路径)], 问题)`。

    文件名就是父的绝对编号（`t-000001.jsonl`），文件里每一行是一个子（`task_id`
    是子的绝对编号）。这条布局是 `secretary.roster_path()` 定的，这里只按它读 ——
    不另立第二份命名约定（两处命名漂移的后果是"名册在盘上、页面说没有"）。
    """
    try:
        entries = sorted(dir_p.glob("*.jsonl"))
    except OSError as exc:  # noqa: BLE001 - 列不出来是"没查成"，不是"没有名册"
        return [], f"{dir_p} 列不出来：{type(exc).__name__}: {exc}"
    found: list[tuple[str, Path]] = []
    for path in entries:
        name = path.name
        if name.endswith(_ROSTER_SIDE_SUFFIX):
            continue
        owner = name[: -len(".jsonl")]
        if not owner:
            return [], f"{name} 的文件名里读不出父的绝对编号"
        found.append((owner, path))
    return found, ""


def _roster_clip(text: str, limit: int = ROSTER_INBOX_CLIP) -> str:
    """一条正文截到 `limit` 字（截了就写一句"截过"，不许静默截断）。"""
    body = str(text or "")
    if len(body) <= int(limit):
        return body
    return body[:int(limit)] + f"……（截断：全文 {len(body)} 字）"


def _roster_inbox(rows: list[dict[str, Any]], *, tasks_tri: str,
                  limit: int = ROSTER_INBOX_ITEMS) -> dict[str, Any]:
    """一个节点的「收件箱积压」：它名下还没消的板项（`{tri, open, by_state, ...}`）。

    ## 收件箱的盘上真身
    `data/tasks.json` 里有两类行：实例行（`kind == ""`，一个 agent 一行）与
    板项行（`kind` 非空：`message` 一条消息 / `notice` 一条通知）。板项行的
    `parent_task_id` 口径是"收件人的编号"（不是派活方）—— 所以
    "`parent_task_id == 这个节点` 且 `item_state != "done"`"就是这个人名下还没消的
    东西。这与 `conductor.open_items_of()` 是同一条判据（那一处 docstring 逐字写了
    板项行与实例行是两轴，不许混算）。

    ## 三态
    台账读不出来 ⇒ `tri="unreadable"` + `open=None`，不是 0 条（把"没查成"读成
    "收件箱是空的"会让监控面板在真出事时最安静）；台账还没写过 ⇒ `not_applicable`
    + `open=None`（合法初态）；读到了 ⇒ `computed`，`open` 是真数字（可以是 0）。
    """
    if tasks_tri == TRI_UNREADABLE:
        return {"tri": TRI_UNREADABLE, "open": None, "by_state": {}, "by_kind": {},
                "items": [], "more": 0,
                "reason": "tasks 台账读不出来 ⇒ 这个人的收件箱积压读不到（不是 0 条）"}
    if tasks_tri != TRI_COMPUTED:
        return {"tri": TRI_NOT_APPLICABLE, "open": None, "by_state": {}, "by_kind": {},
                "items": [], "more": 0,
                "reason": "tasks 台账还没写过（合法初态）⇒ 收件箱积压未读到"}
    by_state: dict[str, int] = {}
    by_kind: dict[str, int] = {}
    for row in rows:
        state = str(row.get("item_state") or "")
        kind = str(row.get("kind") or "")
        by_state[state] = int(by_state.get(state) or 0) + 1
        by_kind[kind] = int(by_kind.get(kind) or 0) + 1
    shown = rows[:max(0, int(limit))]
    return {"tri": TRI_COMPUTED, "open": len(rows), "by_state": by_state,
            "by_kind": by_kind, "more": max(0, len(rows) - len(shown)),
            "items": [{"task_id": str(r.get("task_id") or ""),
                       "kind": str(r.get("kind") or ""),
                       "state": str(r.get("item_state") or ""),
                       "called_by": str(r.get("called_by") or ""),
                       "detail": _roster_clip(str(r.get("detail") or ""))}
                      for r in shown],
            "reason": ""}


def roster_face(root: str | Path, *, limit: int = ROSTER_NODES_MAX,
                inbox_items: int = ROSTER_INBOX_ITEMS) -> dict[str, Any]:
    """`GET /api/roster` 的读模型：当前工作区整棵名册树（只读、三态）。

    ## 一个节点是什么（业主 2026-10-19：「名册 = 父 + 子 + 绝对编号」）
    一个 agent 一个节点，字段逐个来自盘上：

    | 字段 | 盘上来源 |
    |---|---|
    | `task_id`（绝对编号） | `out/roster/<父>.jsonl` 那一行的 `task_id`；根那一行 = 文件名本身 |
    | `name`（名册名） | 同一行的 `name`（根不在任何人的名册里 ⇒ 空串） |
    | `role` | 同一行的 `role`（读不到 ⇒ 台账 `tasks` 的 `role`） |
    | `parent_task_id` | 名册文件名（`secretary.roster_path` 的 `<owner>.jsonl`） |
    | `parent_name` | 祖父那份名册里父那一行的 `name`（现算，不另存） |
    | `children[]` | 它自己那份 `<task_id>.jsonl` 的每一行（`task_id` + `name` + `role` + `retired`） |
    | `retired` / `retired_branch` | 折叠后的 `retired` / 那一行的 `branch` |
    | `brief` / `brief_source` / `surface` | 同一行的 `brief` / `brief_source` / `surface` |
    | `status` / `task_found` / `in_flight` | `data/tasks.json` 里它自己那一行（`status`；在飞 = `pending`/`running`） |
    | `inbox` | `data/tasks.json` 的板项行（见 :func:`_roster_inbox`） |
    | `depth` | 名册链现算：根 = 1（口径写在下面） |

    ## 深度：`depth` 是"这一棵树里的距离"，不是 `tasks.depth`
    `tasks.depth` 是全局召唤深度（主控发起 = 1，`schema.Task.depth` 的 docstring
    逐字如此）；本函数的 `depth` 是"离这棵树根的层数，根 = 1"。两者在"根就是顶趟那股"
    时相等，而在"根是某一支子树的头"时差一个常数 —— 混用会让读的人以为看见了两个
    不同的深度。前端只显示这一个（树里的相对位置才是名册树要说的事）。

    折叠口径与写侧同一处实现（`secretary._fold_roster`：`add` 建项、`bind` 推
    当前调用、`retire` 标退役、`keep_alive` 只记那一格）。这里不另写一份折叠 ——
    两份折叠意味着"名册在盘上是一回事、页面读出来是另一回事"，而那种错没有任何
    东西会报。

    ## 三态（这一条是端点的主要纪律）
    - `answer`：`"ok"`（名册真读成了）或 `"unknown"`。名册目录不在、目录里一个名册
      文件都没有、名册读不出来、有一条读不出来——四档一律 `unknown`，并在 `reason`
      里逐档说清。不许用 `nodes: []` 冒充"这个工作区没有子代理"（那是把"读不到"折成
      "没有"，本项目最贵的一类缺陷）。
    - `tri`：`computed` / `unreadable` / `not_applicable`（本模块统一词表）。名册目录
      还没写过 ⇒ `not_applicable` + `answer="unknown"`："还没写过"也不等于"名册上是
      空的"，因为名册只在有人被派活时才落盘。
    - `count`：`None` = 一行都没读到（下面那些 `answer="unknown"` 的分支）；读到一部分
      时它是真数字，而 `answer` 照旧是 `"unknown"` 并说明哪一份没读成。
    - `tasks_tri` / `tasks_reason`：台账那一栏自己的三态（树照样给，`inbox` 与
      `status` 逐节点标 `unreadable`）。

    ## 规模
    节点上限 `limit`（默认 :data:`ROSTER_NODES_MAX`），超了截断并置 `truncated`；
    一个节点的收件箱只列 `inbox_items` 条（`inbox.more` 报剩下几条）。`nodes` 是
    前序遍历（父一定在子前面）—— 前端按 `depth` 缩进就能画出树，不必自己递归。
    """
    from ..secretary import _fold_roster      # noqa: PLC0415 - 折叠口径的唯一实现
    from ..store import Store                 # noqa: PLC0415 - 台账那一栏

    root_p = Path(str(root))
    dir_p = root_p.joinpath(*_ROSTER_DIR)
    #: 顶层键集合在每一档都一模一样（契约判据 C 拿 `set(RosterView)` 与 TS 比对，
    #: 而"某档少一个键"会让那条判据红在一件与类型毫无关系的事上）。
    out: dict[str, Any] = {
        "answer": "unknown", "tri": TRI_NOT_APPLICABLE, "reason": "",
        "root": str(root_p), "dir": str(dir_p),
        "nodes": [], "roots": [], "count": None, "max_depth": None,
        "files": [], "diagnostics": [], "truncated": False,
        "coverage": {"tasks_agents": None, "roster_nodes": None, "unrostered": None},
        "tasks_tri": TRI_NOT_APPLICABLE, "tasks_reason": "",
    }

    if not dir_p.exists():
        fb = _roster_from_tasks(root_p)
        out.update({k: fb[k] for k in ("nodes", "roots", "count", "max_depth", "coverage")})
        out["reason"] = (
            f"{dir_p} 不在盘上 ⇒ 名册那一格没读到。answer=unknown："
            "这是「没读到」，不是「名册上一个子代理都没有」。"
            + (fb["reason"] if fb["nodes"] else "台账里也没有带父的代理行"))
        out["diagnostics"].append(out["reason"])
        return out
    if not dir_p.is_dir():
        out["tri"] = TRI_UNREADABLE
        out["reason"] = f"{dir_p} 不是目录（同名的文件在盘上）⇒ 名册读不出来"
        return out

    found, why = _roster_files(dir_p)
    if why:
        out["tri"] = TRI_UNREADABLE
        out["reason"] = why
        return out
    if not found:
        fb = _roster_from_tasks(root_p)
        out.update({k: fb[k] for k in ("nodes", "roots", "count", "max_depth", "coverage")})
        out["reason"] = (
            f"{dir_p} 在盘上但一个 <父编号>.jsonl 都没有（还没有人往名册里写过一行）⇒ "
            "answer=unknown。" + fb["reason"])
        out["diagnostics"].append(out["reason"])
        return out

    diagnostics: list[str] = []
    problems: list[str] = []
    children_by_owner: dict[str, list[dict[str, Any]]] = {}
    for owner, path in found:
        rows, bad, state = read_jsonl_state(path)
        if state == "unreadable":
            problems.append(f"{path.name} 读不出来：{bad[0] if bad else '未知原因'}")
            continue
        folded = _fold_roster(rows)
        if bad:
            # 坏行一律算「没查成」（本模块 `_face` 的同一条口径：把"文件坏了"读成
            # "还没写过"是本项目最贵的一类缺陷）。好行照常渲染 —— 与 `artifacts_face`
            # 的"整面 unreadable 并点名，读得出来的栏照常给行"同一条做法。
            problems.append(f"{path.name} 有 {len(bad)} 行读不出来（{bad[0]}）")
        if not folded:
            diagnostics.append(f"{path.name} 里一条子代理记录都没有（文件在、读成了 0 行）")
            continue
        children_by_owner[owner] = folded
        out["files"].append(path.name)

    if not children_by_owner:
        out["tri"] = TRI_UNREADABLE if problems else TRI_NOT_APPLICABLE
        out["reason"] = ("；".join(problems) if problems else
                         f"{dir_p} 下的名册文件里一条子代理记录都没有 ⇒ answer=unknown")
        out["diagnostics"] = diagnostics
        return out

    # ---- 父 → 子 索引（一个子只认先读到的那一份；同一编号挂两个父是坏链，如实报）
    parent_of_child: dict[str, str] = {}
    row_of_child: dict[str, dict[str, Any]] = {}
    for owner in sorted(children_by_owner):
        for row in children_by_owner[owner]:
            tid = str(row.get("task_id") or "")
            if not tid:
                diagnostics.append(f"{owner} 的名册里有一行没有 task_id"
                                   f"（名册名 {row.get('name')!r}）")
                continue
            if tid in row_of_child:
                diagnostics.append(f"{tid} 同时挂在 {parent_of_child[tid]} 与 {owner} "
                                   "两份名册上（只认先读到的那一份）")
                continue
            parent_of_child[tid] = owner
            row_of_child[tid] = row
    #: 根 = 名册文件的主人里"没有出现在任何别人名册上"的那些（多根是合法的：一个工作区
    #: 可以有好几趟顶趟；每一趟自己是一棵树）。
    roots = [owner for owner in sorted(children_by_owner) if owner not in parent_of_child]
    if not roots:
        roots = [sorted(children_by_owner)[0]]
        diagnostics.append("名册链成环（每一份名册的父都是别人的子）⇒ 从字典序最小的"
                           "那一份起读，深度按链上第一次见到的位置算")

    # ---- 台账（`status` / `in_flight` / 收件箱那一栏的唯一来源）
    tasks_by_tid: dict[str, dict[str, Any]] = {}
    in_flight_by_tid: dict[str, int] = {}
    board_by_recipient: dict[str, list[dict[str, Any]]] = {}
    try:
        rows, tasks_tri = _table_state(Store(root_p), "tasks")
        out["tasks_tri"] = tasks_tri
        for row in rows:
            tid = str(row.get("task_id") or "")
            if not tid:
                continue
            if str(row.get("kind") or ""):
                # 板项行：`parent_task_id` 是收件人（`conductor._children_of` 的
                # docstring 逐字写了这条"两轴"口径）。`item_state == "done"` 才算消了。
                if str(row.get("item_state") or "") != "done":
                    board_by_recipient.setdefault(
                        str(row.get("parent_task_id") or ""), []).append(row)
                continue
            tasks_by_tid[tid] = row
            in_flight_by_tid[tid] = (1 if str(row.get("status") or "")
                                     in ("pending", "running") else 0)
    except Exception as exc:  # noqa: BLE001 - 台账读不出来 ⇒ 那几栏 unknown，树照给
        out["tasks_tri"] = TRI_UNREADABLE
        out["tasks_reason"] = f"tasks 台账读不出来：{type(exc).__name__}: {exc}"

    # ---- 前序遍历（父一定在子前面；深度上限 64 与 `conductor.inside_subtree` 同一条纪律）
    nodes: list[dict[str, Any]] = []
    seen: set[str] = set()
    max_depth = 0
    queue: list[tuple[str, str, int]] = [(owner, "", 1) for owner in roots]
    while queue and len(nodes) < max(1, int(limit)):
        tid, parent_tid, depth = queue.pop(0)
        if tid in seen:
            continue
        seen.add(tid)
        row = row_of_child.get(tid) or {}
        trow = tasks_by_tid.get(tid) or {}
        parent_row = row_of_child.get(parent_tid) or {}
        kids = [k for k in (children_by_owner.get(tid) or [])
                if str(k.get("task_id") or "")]
        node: dict[str, Any] = {
            "task_id": tid,
            "name": str(row.get("name") or ""),
            "role": str(row.get("role") or trow.get("role") or ""),
            "depth": int(depth),
            "parent_task_id": str(parent_tid),
            "parent_name": str(parent_row.get("name") or ""),
            "children": [{"task_id": str(k.get("task_id") or ""),
                          "name": str(k.get("name") or ""),
                          "role": str(k.get("role") or ""),
                          "retired": bool(k.get("retired"))} for k in kids],
            "retired": bool(row.get("retired")),
            "retired_branch": str(row.get("retired_branch") or ""),
            "brief": str(row.get("brief") or ""),
            "brief_source": str(row.get("brief_source") or ""),
            "surface": str(row.get("surface") or ""),
            "status": str(trow.get("status") or ""),
            "task_found": bool(trow),
            "in_flight": (in_flight_by_tid.get(tid) if out["tasks_tri"] == TRI_COMPUTED
                          else None),
            "inbox": _roster_inbox(board_by_recipient.get(tid) or [],
                                   tasks_tri=out["tasks_tri"], limit=inbox_items),
        }
        nodes.append(node)
        max_depth = max(max_depth, int(depth))
        if depth >= 64:
            diagnostics.append(f"{tid} 已经到深度 {depth} ⇒ 不再往下展开（坏链不许变成死循环）")
            continue
        for k in kids:
            kid = str(k.get("task_id") or "")
            if kid and kid not in seen:
                queue.append((kid, tid, depth + 1))

    truncated = bool(queue)
    if truncated:
        # 截断是规模的界，不是读失败：它不进 `problems`（`answer` 照旧是 "ok"），
        # 但必须在读数里说得出口 —— 静默截断等于让"树只有这么大"与"树被砍了"一样。
        diagnostics.append(f"名册节点超过上限 {int(limit)} ⇒ 只给了前 {len(nodes)} 个"
                           f"（`truncated=true`，还有 {len(queue)} 个没展开）")

    out["nodes"] = nodes
    out["roots"] = roots
    out["count"] = len(nodes)
    out["max_depth"] = max_depth
    out["diagnostics"] = diagnostics
    out["truncated"] = truncated
    # `answer` 说的是名册这一棵树读成了没有：每一份名册文件都折叠干净、且至少
    # 有一个节点 ⇒ "ok"。台账那一栏的失败不进这里（它有自己的 `tasks_tri`）。
    out["answer"] = "ok" if not problems else "unknown"
    if problems or out["tasks_tri"] == TRI_UNREADABLE:
        out["tri"] = TRI_UNREADABLE
    else:
        out["tri"] = TRI_COMPUTED
    out["reason"] = "；".join(problems)
    if out["tasks_tri"] == TRI_UNREADABLE:
        out["reason"] = "；".join(x for x in (out["reason"], out["tasks_reason"]) if x)

    # ---- 对账读数（名册覆盖到台账的哪一步）：三个数都是"读到了才是数字"
    if out["tasks_tri"] == TRI_COMPUTED:
        with_parent = {tid: r for tid, r in tasks_by_tid.items()
                       if str(r.get("parent_task_id") or "")}
        unrostered = sorted(tid for tid in with_parent if tid not in row_of_child)
        out["coverage"] = {"tasks_agents": len(tasks_by_tid),
                           "roster_nodes": len(nodes),
                           "unrostered": len(unrostered)}
        if unrostered:
            diagnostics.append(
                f"台账里有 {len(unrostered)} 个「有父的代理行」不在任何名册里（头几个："
                + "、".join(unrostered[:5])
                + "）—— 名册机制上线之前落的行；这不是「名册上少了几个人」")
    return out


def handle_roster(handler: Any, params: Mapping[str, str],
                  query: Mapping[str, Sequence[str]]) -> None:
    """`GET /api/roster`：整棵名册树（只读）。

    消费者只有一个：前端那几张只读面板（「在飞」页里的名册面板）。所以这个端点
    在路由表里只有一条 GET —— 没有配对的 POST，也没有任何写路径（写名册是秘书的事，
    走 `secretary.roster_add`，不经过 HTTP）。
    """
    del params, query
    _json_of(handler, roster_face(handler.root))


# ====================================================================== 类型声明
# 前端唯一类型来源（`ui/src/types.ts`）由 `agentflow/web/emit_types.py` 生成，它把三条
# 零交线各自的 `type_decls()` 拼起来（`draft/78 §3`）。本模块这一份是六个只读面。
#
# 一条纪律：字段名逐字等于后端自己的键，不许改名、不许把后端一定会给的键写成可选。
# 出处写的是"这个键是从哪段程序读出来的"，不是行号（行号会漂）。
_TS_TYPES: tuple[tuple[str, str, tuple[tuple[str, str], ...]], ...] = (
    ("RunProduct",
     "run_products() —— 六件产物里的一件（`runflow.ARTIFACTS` 那六个名字）",
     (("name", "string"), ("path", "string"), ("exists", "boolean"),
      ("bytes", "number | null"), ("lines", "number | null"), ("sha256", "string"),
      ("tri", "Tri"),
      # 2026-10-21（业主「每一行都要带角色 + 绝对编号」）：六件产物是文件清单、不是某条
      # 写入 ⇒ 编号那一格恒为 `not_applicable`，但三格照样在每一行上（页面处置同一套）。
      ("by_role", "string"), ("by_role_source", "string"),
      ("by_task_id", "string"), ("by_task_id_tri", "string"))),
    ("CheckpointSpendView",
     "检查点的花销子树（`llmseam.SeamSpend.to_dict()`：calls/tokens_in/tokens_out/usd/"
     "unknown_usd_calls）",
     (("calls", "number"), ("tokens_in", "number"), ("tokens_out", "number"),
      ("usd", "number | null"), ("unknown_usd_calls", "number"))),
    ("CheckpointView",
     "检查点文件 `runs/agent-<角色>-<sid>.json`（`agent_loop.save_run_checkpoint`）",
     (("role", "string"), ("sid", "string"), ("task", "string"),
      ("fingerprint", "string"), ("step", "number"), ("stop_reason", "string"),
      ("waiting_for", "string"), ("spend", "CheckpointSpendView | Record<string, never>"),
      ("prompt_cache", "CheckpointCacheView | Record<string, never>"),
      ("at", "string"))),
    # 2026-10-19：顶趟的缓存汇总（`promptstability.summarize_prompt_cache` 的 11 格）。
    # 为什么它必须是声明出来的而不是 `Record<string, unknown>`：这一格是
    # "提示词改动到底省了多少"在盘上唯一的读数（顶趟不写产出文件），
    # 顶层键含糊了，前端就只能把它当黑盒渲染 —— 而 C 条判据会把它与夹具上
    # 真读出来的键集合逐条对齐（键多一个、少一个都红）。
    ("CheckpointCacheView",
     "检查点的缓存汇总（`promptstability.summarize_prompt_cache` 的 11 格）",
     (("calls", "number"), ("no_request_calls", "number"), ("hit", "number"),
      ("miss", "number"), ("unknown_calls", "number"), ("tokens_in", "number"),
      ("hit_rate", "number | null"), ("mismatched_calls", "number"),
      ("saved_usd", "number | null"), ("saved_unknown_calls", "number"), ("why", "string"))),
    ("ReportReadingView",
     "run_view() 的 `report` —— 交付说明 `out/review/REPORT.md` 的读数",
     (("status", "ReportTri"), ("text", "string"))),
    ("RunView",
     "run_view() —— 一趟详情（`Run` + `report` + `checkpoint`）",
     (("tri", "Tri"), ("reason", "string"), ("sid", "string"), ("runs", "RunRow[]"),
      ("report", "ReportReadingView"), ("checkpoint", "CheckpointView | null"),
      ("checkpoint_reason", "string"), ("path", "string"))),
    ("EventRow",
     "run_events() 的一行 —— 会话里的一条事件（`index` 与 `RunRow.start_index`/"
     "`end_index` 同一套编号：解析成功后的事件列表下标，0 起）",
     (("index", "number"), ("kind", "string"), ("ts", "string"), ("role", "string"),
      ("shape?", "string"), ("ok?", "boolean"), ("usd?", "number | null"),
      ("tokens_in?", "number"), ("tokens_out?", "number"),
      ("payload?", "Record<string, unknown>"), ("result?", "Record<string, unknown>"),
      ("text?", "string"), ("stopped?", "boolean"))),
    ("RunEventsView",
     "run_events() —— 一趟的逐条事件（游标分页：`from_index` 闭、`to_index` 开，"
     "`to_index` 直接可当下一次的 `since_index`）",
     (("tri", "Tri"), ("reason", "string"), ("sid", "string"),
      ("total", "number | null"), ("from_index", "number | null"),
      ("to_index", "number | null"), ("truncated", "boolean"),
      ("events", "EventRow[]"))),
    ("EvidenceView",
     "evidence_chain() —— 证据链七栏（各栏另带 `<栏>_tri`）",
     (("tri", "Tri"), ("reason", "string"), ("store_problems", "string[]"),
      ("statements", "StatementRow[]"), ("statements_tri", "Tri"),
      ("conjectures", "ConjectureRow[]"), ("conjectures_tri", "Tri"),
      ("experiments", "ExperimentRow[]"), ("experiments_tri", "Tri"),
      ("review_findings", "ReviewFindingRow[]"), ("review_findings_tri", "Tri"),
      ("relations", "RelationRow[]"), ("relations_tri", "Tri"),
      ("verifications", "VerificationRow[]"), ("verifications_tri", "Tri"),
      ("secretary", "SecretaryDecision[]"), ("secretary_tri", "Tri"))),
    ("ArtifactsView",
     "artifacts_face() —— 产物面（各栏另带 `<栏>_tri`）",
     (("tri", "Tri"), ("reason", "string"),
      ("ledger", "ArtifactRow[]"), ("ledger_tri", "Tri"),
      ("ledger_verify", "LedgerVerifyRow[]"), ("ledger_verify_tri", "Tri"),
      ("handoffs", "HandoffRow[]"), ("handoffs_tri", "Tri"),
      ("checks", "AcceptanceCheck[]"), ("checks_tri", "Tri"),
      ("style", "ReportStyle"), ("style_tri", "Tri"),
      ("secretary", "SecretaryDecision[]"), ("secretary_tri", "Tri"),
      ("products", "RunProduct[]"), ("products_tri", "Tri"), ("run_dir", "string"),
      ("products_reason", "string"),
      ("tasks", "TaskRow[]"), ("tasks_tri", "Tri"))),
    ("AcceptanceView",
     "acceptance_face() —— 内容级验收（键名逐字来自 reviewaccept.CRITERIA 与 "
     "AUXILIARY_SIGNALS）",
     (("tri", "Tri"), ("reason", "string"),
      ("criteria", "Record<string, string>"), ("details", "Record<string, string>"),
      # 2026-10-21：逐条行（与 `criteria` 同一批判据，只是形状是"一行一条"）。
      # 加它的理由只有一条：业主那句"台账面每一行都带角色 + 绝对编号"里，收工门
      # 也得有"行"这个东西可挂那三格（`criteria` 是 Record，挂不上）。
      ("rows", "AcceptanceRow[]"),
      ("auxiliary", "Record<string, string>"), ("failed", "string[]"),
      ("auxiliary_note", "string"))),
    ("AcceptanceRow",
     "acceptance_face() 的 rows[] —— 一条验收判据一行（键名来自 reviewaccept.CRITERIA；"
     "编号那一格恒为 not_applicable：判据是现算的、不落任何台账行）",
     (("key", "string"), ("title", "string"), ("value", "string"), ("detail", "string"),
      ("by_role", "string"), ("by_role_source", "string"),
      ("by_task_id", "string"), ("by_task_id_tri", "string"))),
    ("SettingsReading",
     "machine_face() 的 `settings` —— 设置文件的各段（key 只给掩码后的那一份）",
     (("path", "string"), ("exists", "boolean"),
      ("toolchain", "Record<string, string>"),
      ("model", "{ vendor: string; api_key: string; base_url: string; name: string; "
                "reasoning_effort: string; key_source: string; "
                "configured: boolean }"),
      # 按角色那一档（业主 2026-10-14）：槽 → 那一档的读数（key 一律掩码）。
      ("models", "Record<string, { api_key: string; base_url: string; name: string; "
                 "vendor: string; reasoning_effort: string; key_source: string; "
                 "configured: boolean; source: string }>"),
      # 秘书那一档（全角色共用）：读数同上一格 + 那一档自己的原文（key 也掩码）。
      ("secretary", "{ api_key: string; base_url: string; name: string; vendor: string; "
                    "reasoning_effort: string; key_source: string; configured: boolean; "
                    "source: string; own_slot?: Record<string, string> }"),
      ("workspace", "Record<string, string>"), ("raw_keys", "string[]"))),
    ("MachineView",
     "machine_face() —— toolchain.toolchain_report() 的键 + 设置三段",
     (("tri", "Tri"), ("reason", "string"), ("model", "Record<string, unknown>"),
      ("provers", "Record<string, unknown>"),
      # 业主 2026-10-12 的开关（`toolchain.lean_enabled`）：与 `lean_ready`（机器上有
      # 没有装）是两条独立的事实 —— 台面必须两条都看得见，否则"关掉了"会被读成"没装"。
      ("lean_enabled", "boolean"), ("lean_enabled_source", "string"),
      ("formal_mode", "string"),
      ("lean_ready", "boolean | null"),
      ("lean_path", "string"), ("lean_version", "string"),
      ("mathlib", "Record<string, unknown>"), ("can_do_formal", "boolean | null"),
      ("settings", "SettingsReading"), ("settings_tri", "Tri"),
      ("settings_reason", "string"))),
    ("BudgetEntry",
     "budget.reading() 的 `added[]` 一行（`budget._write` 写进寄存器的那一笔）",
     (("kind", "string"), ("usd", "number"), ("by", "string"), ("at", "string"),
      ("note", "string"))),
    ("BudgetView",
     "budget_face() —— 总额度（寄存器）+ 已花（`usage_ledger`）与两个归口",
     (("tri", "Tri"), ("reason", "string"), ("path", "string"), ("exists", "boolean"),
      ("source", "string"), ("total_usd", "number | null"),
      ("spent_usd", "number | null"), ("remaining_usd", "number | null"),
      ("exceeded", "boolean"), ("added", "BudgetEntry[]"), ("problem", "string"),
      ("spent_tri", "Tri"), ("spent_reason", "string"),
      ("entries", "number | null"), ("tokens", "number | null"),
      ("attempts", "number | null"), ("added_count", "number"),
      ("by_role", "Record<string, UsageBucket>"),
      ("by_scope", "Record<string, UsageBucket>"))),
    ("UsageBucket",
     "tokenmeter.by_role() / by_scope() 的一格（`{tokens, usd, entries, attempts[, roles]}`）",
     (("tokens", "number"), ("usd", "number"), ("entries", "number"),
      ("attempts", "number"), ("roles?", "Record<string, number>"))),
    ("LiveView",
     "live_face() —— 在飞的循环 / 活进程 / 停机开关与历史（行逐字来自 stopctl）",
     (("tri", "Tri"), ("reason", "string"), ("root", "string"), ("answer", "string"),
      ("running", "Array<Record<string, unknown>>"),
      ("live", "Array<Record<string, unknown>>"),
      ("unreadable_sessions", "string[]"),
      ("switch", "Record<string, unknown>"), ("switch_present", "boolean"),
      ("history", "Array<Record<string, unknown>>"),
      ("interrupts", "Array<Record<string, unknown>>"))),
    ("UsageView",
     "usage_face() —— usage_ledger 的汇总（总计 + 两个归口 + 重试开销 + 最近几笔）",
     (("tri", "Tri"), ("reason", "string"), ("path", "string"),
      ("entries", "number | null"), ("spent", "Record<string, unknown>"),
      ("by_role", "Record<string, UsageBucket>"),
      ("by_scope", "Record<string, UsageBucket>"),
      ("retry_overhead", "Record<string, unknown>"),
      ("recent", "Array<Record<string, unknown>>"))),
    ("StatusReportRow",
     "status_reports_face() 的一行 —— `out/review/STATUS-<ts>.{md,json}` 的一份",
     (("name", "string"), ("stem", "string"), ("path", "string"),
      ("json_path", "string"), ("bytes", "number | null"), ("ts", "string"))),
    ("StatusReportsView",
     "status_reports_face() —— 状态报告最近几份（`statusreport` 写了没人读的那个缺口）",
     (("tri", "Tri"), ("reason", "string"), ("dir", "string"),
      ("count", "number | null"), ("reports", "StatusReportRow[]"))),
    # 2026-10-13（业主的对话框）：一段会话里"用户 ↔ 主控"的来回。
    # `qid` / `options` 是"有就带上"的两栏（只有提问那一条线才有），所以写成可选。
    ("ChatOption",
     "chat_face() 的 options[] 一项（`userio.option_view` 渲染视图里的两栏）",
     (("label", "string"), ("description", "string"))),
    ("ChatLine",
     "chat_face() —— 一条对话线（`who` 只有 user / conductor / team 三档，见 CHAT_WHO）。"
     "`task_id` 是说话那一方的绝对编号，`task_id_source` 只说这个编号从哪来："
     "event（事件里真有）/ inherited（老事件没记，同一岗在本段唯一那一趟的 "
     "agent_run_start 有编号 ⇒ 回填）/ missing（拿不准或确实没记，页面显示"
     "「（未记录编号）」，绝不编一个假编号）。`role` 是说话那一方的角色，`role_source` "
     "同一条纪律：event（事件自带）/ from（`agent_message` 只记了 `from`，读侧用它补齐，"
     "页面括注「承自发件人」）/ missing（两格都没有，页面显示「（未记录角色）」）",
     (("index", "number"), ("who", "string"), ("role", "string"), ("kind", "string"),
      ("ts", "string"), ("title", "string"), ("text", "string"),
      ("role_source", "string"),
      ("task_id", "string"), ("task_id_source", "string"),
      ("clipped", "boolean"), ("qid?", "string"), ("options?", "ChatOption[]"))),
    ("ChatSession",
     "chat_face() 的 sessions[] —— 供对话页挑会话（`sessions.list_sessions` 的四栏）",
     (("sid", "string"), ("last_ts", "string"), ("events", "number"),
      ("bad_lines", "number"))),
    ("ChatView",
     "chat_face() —— 一段会话的对话读数（有界：只给最近的 lines_max 条，截断逐条标明）",
     (("tri", "Tri"), ("reason", "string"), ("sid", "string"),
      ("lines", "ChatLine[]"), ("total", "number"), ("shown", "number"),
      ("clipped", "boolean"), ("sessions", "ChatSession[]"))),
    ("StatementRow",
     "store.rows(\"statements\")（无真机样本 ⇒ 权威来源是 `schema.Statement`）",
     (("stmt_id", "string"), ("origin", "string"), ("kind", "string"),
      ("label", "string"), ("statement_text", "string"), ("statement_full", "string"),
      ("proof_text", "string"), ("source_lit_id", "string"),
      ("page_range", "string"), ("quote_verified", "boolean | null"),
      ("quote_reason", "string"), ("evidence_kind", "string"), ("bits", "number"),
      ("status", "string"), ("derived_from", "string"), ("doc_id", "string"),
      ("line_range", "string"), ("created_at", "string"), ("created_by", "string"),
      # 2026-10-21（业主「每一行都要带角色 + 绝对编号」）：后三格是读模型的 join
      # （`_annotate_ledger_row`），不是 `schema.Statement` 的字段。
      ("by_role", "string"), ("by_role_source", "string"),
      ("by_task_id", "string"), ("by_task_id_tri", "string"))),
    ("ReviewFindingRow",
     "store.rows(\"review_findings\")（无真机样本 ⇒ 权威来源是 `schema.ReviewFinding`）",
     (("finding_id", "string"), ("doc_id", "string"), ("kind", "string"),
      ("level", "string"), ("target", "string"), ("evidence", "string"),
      ("message", "string"), ("round", "number"), ("suggestion", "string"),
      ("status", "string"), ("resolution_note", "string"), ("created_at", "string"),
      ("created_by", "string"), ("axis", "string"), ("line", "number | null"),
      ("verbatim_quote", "string"), ("maths", "string"),
      ("line_unavailable_reason", "string"),
      ("by_role", "string"), ("by_role_source", "string"),
      ("by_task_id", "string"),
      ("by_task_id_tri", "string"))),
    ("RelationRow",
     "store.rows(\"relations\")（无真机样本 ⇒ 权威来源是 `schema.Relation`）",
     (("relation_id", "string"), ("concept_ids", "string[]"),
      ("description", "string"), ("lit_id", "string"), ("page_range", "string"),
      ("quote", "string"), ("quote_normalized", "string"),
      ("quote_verified", "boolean | null"), ("statement", "string"),
      ("concept_group_key", "string"), ("dedup_key", "string"), ("status", "string"),
      ("duplicate_of", "string"), ("created_at", "string"),
      ("supporting_lit_ids", "string[]"),
      ("by_role", "string"), ("by_role_source", "string"),
      ("by_task_id", "string"),
      ("by_task_id_tri", "string"))),
    ("VerificationRow",
     "verifications.list_verifications()（裁定 K2：无真机样本 ⇒ 夹具造一行）",
     (("verification_id", "string"), ("statement_id", "string"), ("verifier", "string"),
      ("verdict", "string"), ("defect_step", "string"), ("quote", "string"),
      ("why", "string"), ("findings", "Record<string, unknown>[]"),
      ("unresolved_errors", "number"), ("proof_sha256", "string"),
      ("proof_chars", "number"), ("round", "number"), ("used_faces", "string[]"),
      ("submission_id", "string"), ("at", "string"),
      ("by_role", "string"), ("by_role_source", "string"),
      ("by_task_id", "string"),
      ("by_task_id_tri", "string"))),
    ("ArtifactRow",
     "artifacts.read_ledger() 的行（`artifacts.FIELDS` 九个键，真机 ARTIFACTS.jsonl 同形）",
     (("at", "string"), ("path", "string"), ("sha256", "string"), ("bytes", "number"),
      ("producer", "string"), ("kind", "string"), ("task_id", "string"),
      ("exit_code", "number | null"), ("note", "string"),
      # 台账行没有 `created_by`（`artifacts.FIELDS` 里没有那一栏）⇒ `by_role` 是空串。
      # `by_task_id` 按 `path` 反查（`agent_run_artifact` 事件同时带 path 与编号）。
      ("by_role", "string"), ("by_role_source", "string"),
      ("by_task_id", "string"),
      ("by_task_id_tri", "string"))),
    ("LedgerVerifyRow",
     "artifacts.verify_entries() 的行 —— 台账钉的 sha 与盘上现在这一版是不是同一版",
     (("path", "string"), ("sha256", "string"), ("producer", "string"),
      ("at", "string"), ("sha256_now", "string"), ("status", "string"),
      ("by_role", "string"), ("by_role_source", "string"),
      ("by_task_id", "string"),
      ("by_task_id_tri", "string"))),
    ("HandoffRow",
     "manuscripts.read_rows() 的行（`manuscripts.write` 写的 14 个键；"
     "`revises`/`kind`/`ref_problems` 是「有就带上」的三栏）",
     (("id", "string"), ("to", "string"), ("sender", "string"), ("summary", "string"),
      ("body", "string"), ("refs", "string[]"), ("sha256", "string"),
      ("sid", "string"), ("task_id", "string"), ("format", "string"),
      ("bytes", "number"), ("path", "string"), ("note", "string"),
      ("created_at", "string"), ("revises?", "string"), ("kind?", "string"),
      ("ref_problems?", "Record<string, string>"),
      # 手稿号是裸号（编号空间就是账本行号）⇒ 拿它当事件口令会误命中，
      # 所以这一栏的 `by_task_id_tri` 是 `not_applicable`（见 `_LEDGER_ROW_TOKENS`）。
      ("by_role", "string"), ("by_role_source", "string"),
      ("by_task_id", "string"),
      ("by_task_id_tri", "string"))),
    ("SecretaryDecision",
     "out/secretary/<角色>.jsonl（老文件）与 out/secretary/<角色>-<实例号>.jsonl（S1m 起的分片）"
     "的行（`secretary.Secretary.note_decision` 写的；"
     "`decision`/`reason`/`basis` 等是「有就带上」的几栏）。"
     "`task_id` 是 S1m 补的那一格：分片之后「这一行是哪一个实例写的」必须读得出来",
     (("role", "string"), ("seq", "number"), ("at", "string"), ("kind", "string"),
      ("duty", "number"), ("from", "string"), ("fail_open", "boolean"),
      ("task_id?", "string"),
      ("decision?", "string"), ("judge?", "Record<string, unknown>"),
      ("reason?", "string"), ("basis?", "string[]"), ("before?", "string"),
      ("target?", "string"),
      # 这一栏没有稳定的行编号（分片之后 `seq` 只在一个文件内唯一）⇒ 编号那一格
      # 是 `not_applicable`；角色也照业主的口径只认 `created_by`（这一栏没有它）。
      ("by_role", "string"), ("by_role_source", "string"),
      ("by_task_id", "string"),
      ("by_task_id_tri", "string"))),
    ("AcceptanceCheck",
     "out/paper/ACCEPTANCE-CHECKS.json 的一行（真机 8 行 C1–C8；"
     "`closing.ACCEPTANCE_CHECKS_NAME`）",
     (("id", "string"), ("kind", "string"), ("min", "number"), ("name", "string"),
      ("note", "string"),
      # 验收表是配置行（`C1`–`C8`），不是某条写入 ⇒ 编号那一格是 `not_applicable`。
      ("by_role", "string"), ("by_role_source", "string"),
      ("by_task_id", "string"),
      ("by_task_id_tri", "string"))),
    ("ReportStyle",
     "out/review/REPORT-STYLE.json 的 `sections`（真机四节名字）",
     (("sections", "string[]"),)),
    ("TaskRow",
     "store.rows(\"tasks\")（真机 p9b/data/tasks.json 19 键 + 工作项板那 7 格；"
     "板那 7 格是 S0/S1b 扩列之后补进来的 —— 真机上它们今天全是空值"
     "（`draft/94` §4：2276 行里 `kind` 非空 0 行），但列**在**，所以类型必须跟上）",
     (("task_id", "string"), ("role", "string"), ("action", "string"),
      ("called_by", "string"), ("parent_task_id", "string | null"),
      ("depth", "number"), ("input_key", "string"), ("status", "string"),
      ("outcome", "string"), ("refusal_reason", "string"), ("detail", "string"),
      ("error", "string"), ("started_at", "string"), ("ended_at", "string | null"),
      ("tokens", "number | null"), ("usd", "number | null"),
      ("instance", "string"), ("artifacts", "string[]"), ("inputs", "string[]"),
      ("kind", "string"), ("expects", "string"), ("item_state", "string"),
      ("item_close", "string"), ("seen_by", "string"), ("seen_step", "number | null"),
      ("keep_alive", "boolean"),
      # 任务行的编号就是它自己的 `task_id`（按它反查，命中的是这一趟自己的收尾事件）。
      # 角色这一格照业主的口径只认 `created_by`（Task 没有那一栏）⇒ 空串。
      ("by_role", "string"), ("by_role_source", "string"),
      ("by_task_id", "string"),
      ("by_task_id_tri", "string"))),
    ("ConjectureRow",
     "store.rows(\"conjectures\")（真机 p9b/data/conjectures.json；无样本时以 "
     "`schema.Conjecture` 为准）",
     (("conjecture_id", "string"), ("statement", "string"), ("status", "string"),
      ("form", "string"), ("testable", "boolean | null"), ("origin", "string"),
      ("created_by", "string"), ("created_at", "string"), ("updated_at", "string"),
      ("experiment_ids", "string[]"),
      ("counterexample_experiment_id", "string | null"),
      ("proof_experiment_id", "string | null"), ("negation_statement", "string"),
      ("known_lit_id", "string"), ("notes", "string"), ("promoted_to", "string"),
      ("withdraw_reason", "string"), ("duplicate", "boolean | null"),
      # `conj:` 不是 `schema.CITATION_PREFIXES` 登记的前缀，裸六位号又会误命中
      # ⇒ 这一栏的编号那一格是 `not_applicable`（见 `_LEDGER_ROW_TOKENS`）。
      ("by_role", "string"), ("by_role_source", "string"),
      ("by_task_id", "string"),
      ("by_task_id_tri", "string"))),
    ("ExperimentRow",
     "store.rows(\"experiments\")（真机 p9b/data/experiments.json；无样本时以 "
     "`schema.Experiment` 为准）",
     (("experiment_id", "string"), ("method", "string"), ("result", "string"),
      ("evidence_kind", "string"), ("negation_kind", "string"), ("claim", "string"),
      ("claim_key", "string"), ("certificate", "string"),
      ("counterexample", "string"), ("search_bound", "string"),
      ("verifier_output", "string"), ("verifier_subject_key", "string"),
      ("code_path", "string"), ("code_hash", "string"),
      ("exit_code", "number | null"), ("artifact_paths", "string[]"),
      ("observations", "string"), ("params", "Record<string, unknown>"),
      ("runtime_sec", "number | null"), ("notes", "string"),
      ("created_at", "string"), ("created_by", "string"),
      ("for_question_id", "string"),
      # `exp:` 是 `schema.CITATION_PREFIXES` 登记的前缀 ⇒ 这一栏的编号真反查得出来。
      ("by_role", "string"), ("by_role_source", "string"),
      ("by_task_id", "string"),
      ("by_task_id_tri", "string"))),
    ("UsageRow",
     "store.rows(\"usage_ledger\")（真机 p9b/data/usage_ledger.json 37 行）",
     (("usage_id", "string"), ("at", "string"), ("role", "string"),
      ("scope", "string"), ("task_id", "string"), ("idem_key", "string"),
      ("tokens_in", "number"), ("tokens_out", "number"), ("tokens_total", "number"),
      ("usd", "number | null"), ("attempts", "number"), ("note", "string"))),
    ("SearchRequestRow",
     "store.rows(\"search_requests\")（真机 p9b/data/search_requests.json 17 键）",
     (("request_id", "string"), ("topic", "string"), ("mode", "string"),
      ("content_description", "string"), ("providers", "string[]"),
      ("done", "boolean"), ("outcome", "string"), ("priority", "string"),
      ("submitted_by", "string"), ("submit_note", "string"),
      ("for_question_id", "string"), ("claimed_by", "string"),
      ("lease_until", "string | null"), ("attempts", "number"),
      ("last_error", "string"), ("result_lit_ids", "string[]"),
      ("timestamp", "string"))),
    # 2026-10-21（业主的「名册监视」）：`out/roster/<父编号>.jsonl` 折出来的那棵树。
    # 逐字段的盘上出处写在 `roster_face` 的 docstring 里那张表上（这里不抄第二份）。
    ("RosterView",
     "roster_face() —— 当前工作区整棵名册树（`out/roster/<父编号>.jsonl` 折叠 + "
     "`data/tasks.json` 的 status/收件箱读数）",
     (("answer", "string"), ("tri", "Tri"), ("reason", "string"),
      ("root", "string"), ("dir", "string"), ("nodes", "RosterNode[]"),
      ("roots", "string[]"), ("count", "number | null"),
      ("max_depth", "number | null"), ("files", "string[]"),
      ("diagnostics", "string[]"), ("coverage", "RosterCoverage"),
      ("tasks_tri", "Tri"), ("tasks_reason", "string"), ("truncated", "boolean"))),
    ("RosterNode",
     "roster_face() 的一个节点 —— 一个 agent（名册里它那一行 + 台账里它那一行；"
     "`depth` 是名册链上的相对深度，根 = 1）",
     (("task_id", "string"), ("name", "string"), ("role", "string"),
      ("depth", "number"), ("parent_task_id", "string"), ("parent_name", "string"),
      ("children", "RosterChild[]"), ("retired", "boolean"),
      ("retired_branch", "string"), ("brief", "string"), ("brief_source", "string"),
      ("surface", "string"), ("status", "string"), ("task_found", "boolean"),
      ("in_flight", "number | null"), ("inbox", "RosterInbox"))),
    ("RosterChild",
     "roster_face() 的 nodes[].children[] 一项 —— 名册里的一个子（绝对编号 + 名册名）",
     (("task_id", "string"), ("name", "string"), ("role", "string"),
      ("retired", "boolean"))),
    ("RosterInbox",
     "roster_face() 的 nodes[].inbox —— 收件箱积压（板项：`kind` 非空、"
     "`parent_task_id` = 收件人、`item_state != \"done\"` 的那些行）",
     (("tri", "Tri"), ("open", "number | null"),
      ("by_state", "Record<string, number>"), ("by_kind", "Record<string, number>"),
      ("items", "RosterInboxItem[]"), ("more", "number"), ("reason", "string"))),
    ("RosterInboxItem",
     "roster_face() 的 nodes[].inbox.items[] 一项 —— 一条还没消的消息/通知",
     (("task_id", "string"), ("kind", "string"), ("state", "string"),
      ("called_by", "string"), ("detail", "string"))),
    ("RosterCoverage",
     "roster_face() 的 coverage —— 台账里的代理行与名册节点的对账（读不到就是 null）",
     (("tasks_agents", "number | null"), ("roster_nodes", "number | null"),
      ("unrostered", "number | null"))),
)

# （`MISSING_TYPES` 在文件头声明：那是"这一层有哪些约定"的那一处，本处不再重复一份 —
#  同一个名字两份定义会让读的人以为有两张表。）


def ts_fields() -> dict[str, tuple[str, ...]]:
    """本模块每个接口的字段名（按声明顺序，可选的那几个去掉 `?`）。

    它是 :func:`type_decls` 的同一份数据的另一种投影 —— 于是"我声明的键"与"我读出来的
    键"能在一处比（判据 `tests/test_webui_readers.py` 与契约 C 都用它）。
    为什么不各写一份：合约的字段名只有一个来源，多一份就会漂移。
    """
    return {name: tuple(field.rstrip("?") for field, _ts in fields)
            for name, _source, fields in _TS_TYPES}


#: `RunRow` 的 20 个键（`draft/75 §1.3` 的 C3 表；`webui/state.py:_scan` 与
#: `sessions.runs_in_session` 逐字同形）。`RunRow` 那个接口由 A 线的 `state.py` 声明，
#: 所以这里的键名只能自己列一份 —— 判据 `test_the_run_row_keys_match_sessions`
#: 会断言这一份与 `sessions.runs_in_session` 真给出的键集合相同（漂移当场红）。
RUN_ROW_KEYS: tuple[str, ...] = (
    "sid", "role", "task", "start_index", "start_ts", "steps", "llm_calls", "usd",
    "unknown_usd", "stop_reason", "final_chars", "summons", "messages", "elapsed_sec",
    "last_shape", "end_index", "end_ts", "waiting_on", "waiting", "events_in_run",
)


def type_decls() -> str:
    """本模块（六个只读面）那一段 TS 声明文本。

    形状是 `draft/78 §3` 的接缝之一：`agentflow/web/emit_types.py` 把三条零交线
    各自的 `type_decls()` 拼成 `ui/src/types.ts`。于是加接口这件事永远发生在
    自己那一行里。
    """
    parts: list[str] = []
    for name, source, fields in _TS_TYPES:
        lines = [f"/** 出处：{source}。 */", f"export interface {name} {{"]
        lines += [f"  {field}: {ts};" for field, ts in fields]
        parts.append("\n".join(lines + ["}"]) + "\n")
    return "\n".join(parts)


# ====================================================================== 接缝的落点
# `HANDLERS` 在文件头声明为空的字典（那个位置放的是"这一层有哪些约定"），实体在
# 这里登记：函数得先存在。`routes.handler_for(name)` 会按 `ROUTES` 第三元素来取。
HANDLERS.update({
    "handle_state": handle_state,
    "handle_run_view": handle_run_view,
    "handle_run_events": handle_run_events,
    "handle_evidence": handle_evidence,
    "handle_artifacts": handle_artifacts,
    "handle_acceptance": handle_acceptance,
    "handle_machine": handle_machine,
    "handle_budget_view": handle_budget_view,
    "handle_live": handle_live,
    "handle_usage": handle_usage,
    "handle_status_reports": handle_status_reports,
    "handle_chat": handle_chat,
    "handle_roster": handle_roster,
})

def _roster_from_tasks(root_p: Path) -> dict[str, Any]:
    """台账兜底：名册读不到时，从 `data/tasks.json` 建一棵树（标成 `unregistered`）。

    业主 2026-10-21（"网页完整接入名册机制!!"）：名册是"父 + 子 + 绝对编号"的唯一真身，
    但当登记没发生时，页面上不该是"什么都没有" —— 那会让读的人以为"这次没派活"。
    台账里明明有 A/E/D 这些带父的代理行，它们就是"存在、但不在名册上"的证据。

    所以这一档三件事一起给：
    1. `nodes` 照给（`task_id` / `role` / `parent_task_id` / `depth` / `status`），
       每个节点带 `registered=False` 与 `name=""`（它确实没有名册名）；
    2. `coverage.unrostered` 点名这些编号（"名册上没有它们"是结论，不是缺省）；
    3. `answer` 仍然是 `"unknown"`（名册那一格没读到），但 `reason` 里说清
       "下面这棵树来自台账，不是名册" —— 三态不折平，页面上却看得见人。
    """
    path = root_p / "data" / "tasks.json"
    try:
        rows = list((json.loads(path.read_text(encoding="utf-8")) or {}).get("rows") or [])
    except (OSError, json.JSONDecodeError):
        return {"nodes": [], "roots": [], "count": None, "max_depth": None,
                "coverage": {"tasks_agents": None, "roster_nodes": 0, "unrostered": None},
                "reason": f"{path} 读不出来 ⇒ 台账兜底也读不到"}
    agents = [r for r in rows if str(r.get("kind") or "") == "" and str(r.get("task_id") or "")]
    by_parent: dict[str, list[dict[str, Any]]] = {}
    for r in agents:
        by_parent.setdefault(str(r.get("parent_task_id") or ""), []).append(r)
    ids = {str(r.get("task_id")) for r in agents}
    roots = [str(r.get("task_id")) for r in agents
             if str(r.get("parent_task_id") or "") not in ids]
    depth_of: dict[str, int] = {}

    def depth(tid: str, seen: set[str] | None = None) -> int:
        if tid in depth_of:
            return depth_of[tid]
        seen = (seen or set()) | {tid}
        row = next((r for r in agents if str(r.get("task_id")) == tid), None)
        parent = str((row or {}).get("parent_task_id") or "")
        got = 1 if parent not in ids or parent in seen else 1 + depth(parent, seen)
        depth_of[tid] = got
        return got

    nodes: list[dict[str, Any]] = []

    def walk(tid: str) -> None:
        row = next((r for r in agents if str(r.get("task_id")) == tid), None)
        if row is None:
            return
        parent = str(row.get("parent_task_id") or "")
        kids = [{"name": "", "role": str(k.get("role") or ""), "task_id": str(k.get("task_id")),
                 "retired": False} for k in by_parent.get(tid, [])]
        status = str(row.get("status") or "")
        nodes.append({
            "task_id": tid, "name": "", "role": str(row.get("role") or ""),
            "parent_task_id": parent, "parent_name": "",
            "children": kids, "retired": False, "retired_branch": "",
            "brief": "", "brief_source": "", "surface": "",
            "status": status, "task_found": True,
            "in_flight": 1 if status in ("pending", "running") else 0,
            "inbox": {"tri": "not_applicable", "open": None, "by_state": {}, "by_kind": {},
                      "items": [], "more": 0,
                      "reason": "名册没读到 ⇒ 这一档按台账兜底，收件箱未查"},
            "depth": depth(tid), "registered": False,
        })
        for kid in kids:
            walk(kid["task_id"])

    for rid in roots:
        walk(rid)
    # 三态纪律：一条代理行都没有 ⇒ `count` 是 None（读不到），不是 0
    # （判据 `test_webui_roster_panel` 的"无名册 ⇒ count 为 null"那一档钉着这一点）。
    empty = not agents
    return {"nodes": nodes, "roots": roots, "count": None if empty else len(nodes),
            "max_depth": None if empty else max((n["depth"] for n in nodes), default=None),
            "coverage": {"tasks_agents": None if empty else len(agents),
                         "roster_nodes": None if empty else 0,
                         "unrostered": None if empty else len(agents)},
            "reason": (f"名册那一格没读到，但台账里有 {len(agents)} 个带父的代理行"
                       f"（头几个：{sorted(ids)[:5]}）⇒ 下面这棵树来自 `data/tasks.json`，"
                       "它们**存在、但不在名册上**（名册登记没有发生）")}

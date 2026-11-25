# -- coding: utf-8 --
"""只读面的读模型（`draft/73` §2.3 的本体）。

## 这一层是什么

一个面一个适配器函数：只读、三态、不吞异常。下表是 C1 那几行；后来加的 package /
roster / library / errors / cache / run-digest 几条同形（读既有实现，不另写一份）。

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

处理器的落点：`routes.py` 的第三格是处理器名字，而 `WebHandler` 住在 A 线的
`webui/server.py` 里（B 线不碰）。所以每个面的 HTTP
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

from .. import manuscripts as _MS
from .. import sessions as SS
from .. import statementledger as SL   # 命题台账的查口（全表→索引，只读、零模型）
# 板项行"状态"那一格的投影（D12 ②）：与状态报告是同一个函数，不许在网页这一侧
# 再写一份（两份 = 同一行在报告与页面上有两种状态）。按模块取属性而不是
# `from ..statusreport import tasks_row_reading`：判据要能整格替换它做反真空
# （`tests/test_a_board_item_shows_its_item_state.py` 的 ③）。
from .. import statusreport as _SRP
from ..conductor import (AGENT_STATE_LABELS, AGENT_STATE_UNKNOWN, AGENT_STATES,
                         agent_states, clock_waiters, most_active_state, state_counts)
from ..jsonlfile import read_jsonl_state
from . import facecache
from . import state as _state
from .. import proofregistry as _PR

__all__ = [
    "ADMISSION_BASIS_CANDIDATE",
    "CHECKED_TYPES", "CODE_CONSISTENCY_REVOKED", "DIGEST_SCOPE_SESSION",
    "DIGEST_SCOPE_WORKSPACE", "EVENTS_LIMIT_DEFAULT", "EVENTS_LIMIT_MAX",
    "HANDLERS",
    "LEDGER_EVENT_SCAN_BYTES", "LEDGER_EVENT_SCAN_KINDS", "LEDGER_EVENT_SCAN_SESSIONS",
    "LEDGER_ROLE_FIELDS", "LEDGER_TASK_TRI_EVENT", "LEDGER_TASK_TRI_MISSING",
    "LEDGER_TASK_TRI_NOT_RECORDED", "LEDGER_TASK_TRI_ROW",
    "LIBRARY_NO_LEDGER_REASON", "LIBRARY_STATE_COMPUTED", "LIBRARY_STATE_UNKNOWN",
    "MISSING_TYPES", "NONTRIVIALITY_NOT_APPLICABLE_WORD", "NONTRIVIALITY_UNJUDGED_WORD",
    "PENDING_ENDPOINTS",
    "PROBLEM_ADMISSION_UNDECIDABLE", "PROBLEM_ADMITTED_WITHOUT_ROW",
    "PROBLEM_BULK_ADMISSION_SUSPECTED",
    "PROBLEM_DOWNLOAD_CLAIMED_ABSENT",
    "PROBLEM_LITERATURE_UNREADABLE", "PROBLEM_USES_UNREADABLE", "ROUTES",
    "ROSTER_INBOX_ITEMS",
    "ROSTER_NODES_MAX",
    "RUN_ROW_KEYS", "SHA_MATCH", "SHA_MISMATCH", "SHA_UNKNOWN", "UNCHECKED_TYPES",
    "acceptance_face", "annotate_errors_readout", "artifacts_face",
    "chat_face", "code_consistency", "evidence_chain", "experiment_spots",
    "handle_acceptance", "handle_artifacts",
    "handle_chat", "handle_evidence",
    "handle_library", "handle_machine", "handle_package", "handle_roster",
    "handle_run_events", "handle_run_view", "handle_source", "handle_state",
    "library_face", "machine_face", "package_face", "roster_face", "run_events",
    "run_digest", "run_products", "run_view", "sha_consistency", "source_window",
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
    # 论文包三块一次读 + 原文窗口。两条都只读：
    # `/api/package` 是 A/B/C 三块（三块总是一起看，一次请求才有同一份快照）；
    # `/api/source` 是每格 `source` 的落地（路径闸在 `source_window` 里，四条判据）。
    ("GET", "/api/package", "handle_package"),
    ("GET", "/api/source", "handle_source"),
    ("GET", "/api/machine", "handle_machine"),
    # 预算窗口（②）与多智能体监控（①）两条：与六个面同族（读盘现算、三态、
    # 不缓存），所以落在同一张子表里。
    ("GET", "/api/budget", "handle_budget_view"),
    ("GET", "/api/live", "handle_live"),
    ("GET", "/api/usage", "handle_usage"),
    ("GET", "/api/status-reports", "handle_status_reports"),
    # 对话框（对话页那一面）：一段会话里"用户 ↔ 主控"的来回。
    ("GET", "/api/chat", "handle_chat"),
    # 名册监视：当前工作区的整棵名册树 —— 父是谁、子有哪些、
    # 每个成员的绝对编号／名册名／角色／深度，外加收件箱那三格（未读 / 已读未 ack /
    # 未消总数，见 `_roster_inbox`）。
    # 只读一条：这个端点的消费者是只读面板，写面为零（表里没有与它配对的 POST，
    # 判据 `tests/test_webui_roster_panel.py` 的第三条就钉着这一条）。
    ("GET", "/api/roster", "handle_roster"),
    # 板上义务的收件人读数（族由 `families[]` 现取；今天四族：b-register /
    # v-resubmit / b-awake / d-handoff）：只读一条，
    # 没有配对的 POST（销号只发生在 conductor 的收口那一路）。
    ("GET", "/api/obligations", "handle_obligations"),
    # 真身在 `webui/sse.py`：`GET /api/stream` 是 SSE 流（`text/event-stream`，
    # 连上就一直推，处理器不返回）。它不能用"普通 GET 读完即返"的断言去测 ——
    # 必超时。分类真身是 `routes.ROUTE_KINDS["/api/stream"] = "stream"`；
    # `routes.route_kind()` / `endpoint_inventory()` / `--list-routes` 都读那一格。
    ("GET", "/api/stream", "handle_stream"),
    # 文献库那一面（业主报过「ui侧文献库无法读出，请确认」）。
    # 只收「正式入库」的那一档，每条带「被哪些命题／哪一份证明用过」。只读一条：
    # 这一条端点没有任何写面（表里没有配对的 POST，也不需要 --allow-writes）。
    ("GET", "/api/literature", "handle_library"),
    # 网页操作台账的读侧（AUDIT F11）：`<工作区>/web-actions.jsonl` 从 W3 起就有人在写
    # （每一笔网页写操作一行，被拒的尝试也留一行），但全仓没有读侧 —— 于是写侧文件头
    # 里那句「网页上那一栏『操作历史』」一直没有落地。这一条只读（不需要
    # `--allow-writes`），行序是最新的在前，分页 `?limit=` / `?offset=`。
    ("GET", "/api/actions", "handle_actions"),
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
    "RunView", "RunDigestView", "EventRow", "RunEventsView",
    # `run_digest()` 的 `signs` 那一块（签文件 / 签台账分开数）：键在任何工作区上都在
    # （目录不在 ⇒ 0 / `ledger_present=False`，键集合不变），所以进受核对名单。
    "SignsView",
    "EvidenceView", "ArtifactsView", "AcceptanceView", "SettingsReading",
    # 成本对账那一格（`ClosingView.cost.reconciliation`）的键在任何工作区上都在
    # （归口读不出来 ⇒ 各值 null，键集合不变），所以进受核对名单。
    "CostReconciliation",
    "MachineView", "ArtifactRow", "LedgerVerifyRow", "HandoffRow", "SecretaryDecision",
    "AcceptanceCheck", "ReportStyle", "TaskRow", "VerificationRow",
    # 服务与工作区（AUDIT F8）：五格在任何一个工作区上都在（根为空也是同一批键），
    # 所以进受核对名单；行一级没有它。
    "ServingWorkspace",
    # DATAHYGIENE（2026-11-22）：库表档案那三格在任何工作区上都在（登记面是
    # `schema` 的模块级常量，读不出来只是 `checked=false` 的另一档，键集合同一批），
    # 所以外壳与两种行都进受核对名单（`_backend_keys` 里现读 `machine_face()["tables"]`）。
    "TableArchiveView", "TableRetiredRow", "TableNotEnabledRow",
    # SEEDFIX（2026-11-22）：种子读数（`library_face()["data"]["seed"]`）的键在任何
    # 工作区上都在（没投过种子是 `count=0` 的另一档；`library_unregistered=null`
    # 是"没查成"的另一档）⇒ 进受核对名单。
    "LibrarySeed",
    # 网页操作台账（AUDIT F11）：十格外壳在任何一档上都在（台账读不出来是 `tri`
    # 的另一档，键集合同一批），所以进受核对名单；`ActionRow` 见 `UNCHECKED_TYPES`。
    "ActionsView",
    # 这四面的顶层键在任何工作区上都在（寄存器缺席、账本为空、没有进程都只是
    # 三态里的另一档，不是"读不出键"），所以它们进受核对名单；行一级的类型见
    # `UNCHECKED_TYPES` 的理由。
    "BudgetView", "LiveView", "UsageView", "StatusReportsView",
    # `ChatView` 的键在任何工作区上都在（"还没有会话"
    # 与"没查成"都只是三态里的另一档）；夹具那一段会话里有主控的 run_start 与一条
    # 提问，所以行一级的 `ChatLine` / `ChatSession` 也读得出键。
    "ChatView", "ChatLine", "ChatSession", "ChatOption",
    # `RosterView` 的顶层键在每一档上都在
    # （名册目录不在 ⇒ `answer=unknown` 也是同一批键，见 `roster_face` 里那张表），
    # 所以它进受核对名单；行一级的五个类型见 `UNCHECKED_TYPES` 的理由。
    "RosterView",
    # 板上义务（族由 `families[]` 现取；今天四族）的收件人读数：顶层键在任何
    # 工作区上都在（表不在 ⇒ not_applicable；families 恒为四族），所以进受核对名单。
    "ObligationsView", "ObligationFamily",
    # 文献库那一面的五键外壳在每一档上都是同一批键
    # （表不在盘上 / 坏 JSON / 空表都只是 `state` 的另一档，不是"读不出键"），
    # 所以它进受核对名单；`data` 与三条行一级的类型见 `UNCHECKED_TYPES` 的理由。
    "LibraryView",
    # 错误动作那一面的两面顶层键在任何工作区上都在
    # （`state="unknown"` 也是同一批键：`checked` / `state` / `reason` / `data` /
    # `problems`），所以它们进受核对名单 —— 这是搬进生成物之后真正想要的收益：
    # C 条从现在起核对那批键名。缓存那一族留在 `UNCHECKED_TYPES`（理由见那一处）。
    "RoleErrorsView", "ErrorStatsData",
    # `/api/package` 的三块 + 外壳。顶层键在任何工作区上都在
    # （没有正文 ⇒ `structure.tri=not_applicable`；门读不成 ⇒ `closing.tri=unreadable`，
    # 键集合同一批），所以它们进受核对名单；行一级/子块类型见 `UNCHECKED_TYPES`。
    "PackageView", "ProofView", "StructureView", "ClosingView", "SourceWindow",
)

#: 声明了、但夹具上还读不出键的接口（`{接口名: 理由}`）。判据不许它们同时出现在
#: 两份登记里，也不许一份都不在 —— 这张表是"为什么还没有读数"的唯一落点。
UNCHECKED_TYPES: dict[str, str] = {
    "StatementRow": "夹具没有造 statements 行（真机 p9b/data/statements.json 也是 0 行）"
                    "⇒ 字段以 `schema.Statement` 的 dataclass 为准，无真读数可对账",
    "DocumentRow": "夹具没有造 documents 行（判据 C 的夹具工作区里稿件台账是空的）"
                   "⇒ 字段以 `schema.Document` 的 dataclass 为准，无真读数可对账",
    "ReviewFindingRow": "夹具没有造 review_findings 行（同上：真机 0 行）",
    "RelationRow": "夹具没有造 relations 行 ⇒ 以 `schema.Relation` 为准",
    "ActionRow": "夹具不跑网页写面（`tests/conftest.py` 的夹具从不 POST 那七条写端点）"
                 "⇒ `web-actions.jsonl` 不在夹具里、`rows[]` 是空数组；形状以写侧"
                 "`webui/audit.record_action` 造的那一行（十个键）为准",
    "ConjectureRow": "夹具没有造 conjectures 行 ⇒ 以 `schema.Conjecture` 为准",
    "ExperimentRow": "夹具没有造 experiments 行 ⇒ 以 `schema.Experiment` 为准",
    "UsageRow": "夹具没有造 usage_ledger 行（真机 p9b/data/usage_ledger.json 有 37 行，"
                "但那是运行数据面、不入库）",
    "SearchRequestRow": "夹具没有造 search_requests 行（同上）",
    # `BudgetEntry` / `UsageBucket` / `StatusReportRow` 三条：它们的行是运行期数据，
    # 夹具上恒为空数组。三态纪律在这里的落点与 `UsageRow` 同一条：没有读数就
    # 登记"为什么没有"，
    # 不是把接口从 types.ts 里删掉假装不存在。
    "BudgetEntry": "夹具没有预算寄存器（`budget.json` 由用户设过一次才有）"
                   "⇒ `added[]` 是空数组，行形状以 `budget._write` 为准",
    "UsageBucket": "夹具的 `usage_ledger` 是空的（真机 T2 那本有几十行）"
                   "⇒ 两个归口的格子读不出来，形状以 `tokenmeter.by_role/by_scope` 为准",
    "StatusReportRow": "夹具没有 `out/report/STATUS-*`（那是跑过一趟之后才写的）"
                       "⇒ `reports[]` 是空数组，形状以 `statusreport.status_report_paths` 为准",
    # 名册那一棵树：夹具工作区里没有 `out/roster/`（名册只在有人被派活
    # 时才落盘）⇒ `nodes[]` 恒为空数组。行一级的五个形状以 `roster_face` 的真读数为准，
    # 而"为什么这里没有读数"就写在上面这一句里（三态纪律：不是把接口删掉假装不存在）。
    "RosterNode": "夹具没有 `out/roster/<父编号>.jsonl`（名册只在派人时落）"
                  "⇒ `nodes[]` 是空数组，形状以 `roster_face` 在真工作区上的读数为准",
    # 义务板项：夹具的 `tasks` 行里没有义务（四族）的板项 ⇒ `rows[]` 是空数组；
    # 族级形状（`families[]`）夹具上有，所以它进受核对名单。
    "ObligationRow": "夹具没有义务族的板项行 ⇒ `rows[]` 是空数组；"
                     "形状以 `obligations_face` 在真工作区上的读数为准",
    # 错误动作那一页的三组读数：下面四个是 `ErrorStatsData` 的
    # 子形状，夹具（`artifacts_ws`）没有 `verifications/` / `out/roster/refusals/` /
    # `out/secretary/` 的拒信与判词，也没有收工门的 blocker ⇒ 样本 / blocker 数组是空的。
    # 三态纪律在这里的落点与 `RosterNode` 同一条：登记"为什么没有读数"，不把接口删掉。
    "ErrorBlocker": "夹具的收工门没有 blocker（`closing.check_closing` 在夹具上八格干净）"
                    "⇒ `sources.closing.blockers[]` 是空数组，形状以 `check_closing` 为准",
    "ErrorSignalSample": "夹具没有 `out/secretary/` 的判词行与 `out/roster/refusals/`"
                         "⇒ `classes[].samples[]` 是空数组，形状以 `errorstats._bump` 的留样为准",
    "ErrorClassRow": "同 `ErrorSignalSample`：`classes[]` 的行在夹具上与真机是同一份代码产出，"
                     "但夹具上多数类目是 0 条、没有样本可对账 ⇒ 形状以 `ErrorStats.by_class()` 为准",
    "ErrorClassState": "同 `ErrorClassRow`：逐类三态的键在夹具上齐全（checked/state/reason），"
                       "但夹具上每个源都读到了，没有 unknown 那一档可对账",
    "RosterChild": "同 `RosterNode`：`nodes[].children[]` 在夹具上是空的"
                   "⇒ 形状以 `roster_face` 的 `children` 为准",
    "RosterInbox": "同 `RosterNode`：夹具上没有名册节点，`inbox` 一栏没有读数"
                   "⇒ 形状以 `roster_face` 的 `inbox` 为准",
    "RosterInboxItem": "同 `RosterNode`：`inbox.items[]` 在夹具上是空数组"
                       "⇒ 形状以 `_roster_inbox` 的 `items` 为准",
    "RosterCoverage": "同 `RosterNode`：夹具上没有名册文件，`coverage` 三个计数都是 null"
                      "⇒ 形状以 `roster_face` 的 `coverage` 为准",
    # 一个子代理可以接好几件活：节点下面那一串活与"拼不上的那些代理行"都是
    # 行一级的形状，夹具工作区里没有名册 ⇒ 两者恒为空数组。
    "RosterTask": "同 `RosterNode`：夹具上没有名册节点，`nodes[].tasks[]` 是空数组"
                  "⇒ 形状以 `roster_face` 的 `tasks` 为准",
    "RosterUnplaced": "同 `RosterNode`：夹具上没有名册文件，`unplaced[]` 是空数组"
                      "⇒ 形状以 `roster_face` 的 `unplaced` 为准",
    # 「子 N」按台账数、未落名册的子挂在父节点下：同一档 —— 夹具上没有名册节点，
    # 这一格自然也是空数组，形状以 `roster_face` 的真读数为准。
    "RosterUnrostered": "同 `RosterNode`：`nodes[].unrostered_children[]` 在夹具上是空数组"
                        "⇒ 形状以 `roster_face` 的 `unrostered_children` 为准",
    # 台账行带"角色 + 绝对编号"：验收面的 `rows[]` 在任何工作区上都有
    # 五行（判据是现算的、不依赖盘上数据），但它没有进契约判据 C 的读数清单
    # （`tests/test_webui_contracts.py::_backend_keys` 只取验收面的顶层键）⇒ 判据 C
    # 没有对账面。行形状由 `tests/test_ledger_faces_carry_role_and_id.py` 逐键钉着。
    "AcceptanceRow": "契约判据 C 的 `_backend_keys` 只读验收面的顶层键、没读 `rows[]`"
                     "⇒ 形状以 `_acceptance_rows` 与 `AcceptanceRow` 的声明为准"
                     "（逐键判据在 tests/test_ledger_faces_carry_role_and_id.py）",
    # 命题标注非平凡度 / 第 4 位按路径 / sha 只报一致：这三行的
    # 行一级类型在夹具上读不出键 —— 夹具的 statements 是 0 行，也没有 out/experiments/
    # 与 code/exp/。形状以各自那一个读数函数为准，逐键判据在
    # `tests/test_webui_readings_format.py`（它自造工作区，把这三种形态都造出来）。
    "FormalPath": "夹具没有 statements 行（真机 p9b/data/statements.json 也是 0 行）"
                  "⇒ `formal_paths[]` 恒为空数组；形状以 `evidencebits.formal_by_proof`"
                  " 的读数为准（逐键判据在 tests/test_webui_readings_format.py）",
    "ReviewedPath": "同 `FormalPath`：夹具没有 statements 行 ⇒ `reviewed_paths[]` 恒为空"
                    "数组（而真行上它一条证明一行）；形状以 "
                    "`evidencebits.reviewed_by_proof` 的读数为准（逐键判据同上）",
    "OptimizedPath": "同 `ReviewedPath`：夹具没有 statements 行 ⇒ `optimized_paths[]` "
                     "恒为空数组（而真行上它一条证明一行）；形状以 "
                     "`evidencebits.optimized_state` 的读数为准"
                     "（逐键判据在 tests/test_webui_optimized_column.py）",
    # NT2（2026-11-15）：非平凡度的逐路径行。夹具工作区没有 statements 行（即便有，
    # 也是一条路径、`nontriviality_paths[]` 为空或只有一行），所以判据 C 的
    # `_backend_keys` 读不出它的键。形状以 `secretary._fold_nontriviality` 的
    # `paths[]` 为准，逐键判据在 `tests/test_nontriviality_is_per_path.py` 的 P1/P7。
    "NontrivialityPath": "契约判据 C 的夹具工作区没有多路径的 statements 行 "
                         "⇒ `nontriviality_paths[]` 读不出键；形状以 "
                         "`secretary._fold_nontriviality` 的 `paths[]` 为准",
    "ExperimentSpot": "夹具工作区没有 `out/experiments/<号>/`（实验跑过之后才落盘）"
                      "⇒ `experiment_spots[]` 恒为空数组；形状以 `experiment_spots()`"
                      " 的读数为准（同上那份判据文件）",
    "CodeExpFile": "同 `ExperimentSpot`：夹具没有 `code/exp/` ⇒ `code_exp[]` 恒为空数组；"
                   "形状以 `experiment_spots()` 的 `code_exp` 为准（同上）",
    # 文献库那一面：`artifacts_ws` 夹具里 `literature` 是 0 行
    # ⇒ `data.works[]` / `data.problems[]` 恒为空数组，三个行一级的形状以本模块
    # 的读数为准（判据 `tests/test_library_face_only_counts_admitted_works.py`
    # 自己造工作区，把 5 条入库文献与两种被引形态都造出来）。
    "LibraryData": "契约判据 C 的 `_backend_keys` 只读这一面的五键外壳，没读 `data` "
                   "（夹具工作区里 `literature` 是 0 行）⇒ 形状以 `library_face` 的 `data` 为准",
    "LibraryWork": "夹具工作区里没有入库文献（`data/works[]` 是空数组）⇒ 一条行都读不出键；"
                   "形状以 `_library_work` 的读数为准（逐键判据见上面那份判据文件）",
    "LibraryUse": "同 `LibraryWork`：没有入库文献，也就没有「被谁用过」的行可读；"
                  "形状以 `_library_uses` 的读数为准（同上）",
    "LibraryProblem": "干净的工作区上 `problems[]` 是空数组（没有可留痕的问题）"
                      "⇒ 形状以 `library_face` 里那几处 `add_problem(` 的读数为准（同上）",
    # 两档提示词缓存那一族搬进生成物之后仍留在本名单里 —— 不是因为它读不出来，
    # 而是因为 C 条的读盘步骤够不到它：`cachectl.status()` 要现渲染两档提示词
    # （切 `AGENTFLOW_LEAN_ENABLED`、重置工具链读数、跑一遍 `render_prompts`），
    # 那是一条有副作用的慢路径（本机实测首次约 1.1 秒），把判据的读盘步骤变成
    # "顺手改了进程的环境变量"不值得。
    # 顶层那两面（`RoleErrorsView` / `ErrorStatsData`）没有这个问题，已进受核对名单。
    # 这一族的形状仍只有一个来源（`types.ts` 的生成物），只是核对深度浅一档。
    "CacheView": "C 条的读盘步骤不跑 `cachectl.status()`（它要现渲染两档提示词）"
                 "⇒ 形状以 `cachectl.status()` / `cacheface.warm_job()` 的返回为准",
    "CacheTier": "同 `CacheView`：`tiers[档]` 的一格由 `cachectl.tier_reading()` 给",
    "CacheKeyCell": "同 `CacheView`：`tiers[档].key` 由 `cachectl.tier_reading()` 给",
    "CacheKeyReading": "同 `CacheView`：`key` 由 `cachectl.key_reading()` 给",
    "CacheTargetCell": "同 `CacheView`：`tiers[档].per_target[目标]` 由 `tier_reading` 给",
    "CacheActive": "同 `CacheView`：`active` 由 `cachectl.active_reading()` 给",
    "CacheReminder": "同 `CacheView`：`reminder` 由 `cachectl.status()` 给",
    "CacheWarmJob": "同 `CacheView`：`warm` 由 `cacheface.warm_job()` 给",
    "ErrorStatsSource": "逐源读数的键随源不同（事件流 / 会话记录 / 码命中），"
                        "所以每一格都可选；C 条只核对 `ErrorStatsData` 的五个顶层键",
    "ReadoutProblem": "夹具上 `problems[]` 是空数组（没有可留痕的问题）"
                      "⇒ 形状与 `LibraryProblem` 同形（`code` + `detail`）",
    "ErrorCategoryGlossary": "真身是一张常量表（`errorstats.ERROR_CATEGORIES`），"
                             "不在盘上、也不经读模型 ⇒ C 条的读盘步骤取不到它",
    "ErrorCategoryMeaning": "同 `ErrorCategoryGlossary`：一行两格（`name` + `meaning`）",
    # 在飞面那两格有了具名行类型，但 C 条核不了它们 ——
    # 夹具工作区里没有在跑的循环、也没有登记过的活进程 ⇒ 两格恒为空数组，
    # 对着空数组核等于没核。登记在这里，"造一套 live 夹具"是另一件事（见报告）。
    "LiveLoopRow": "夹具工作区里没有在跑的循环（`running[]` 是空数组）"
                   "⇒ 形状以 `stopctl.running_loops()` 的返回为准；"
                   "要核对它得先造一套 live 夹具（在跑的会话 + 活着的进程登记）",
    "LivePidRow": "夹具工作区里没有进程登记（`live[]` 是空数组）"
                  "⇒ 形状以 `stopctl.live_pids()` 的 `pid/role/sid/started_at/path` 为准；"
                  "同上，要核对它得先造 live 夹具",
    # `/api/package` 的行一级/子块类型。夹具造不出这些行（没有
    # statements-with-proofs、没有 `out/vsigns/`、没有 `out/roster/`、也没有一份
    # 带 findings 的正文），所以 C 条只能核三块顶层键；行形状以 `package_face` 的
    # 返回与 `_TS_TYPES` 的声明为准。真机 81 副本上逐格核过（A 52 行 /
    # B 5 条 findings / C 8 格）。
    "ProofRow": "夹具没有带 `proof_text` 的命题行（`make_artifacts_sample` 不造 statements）"
                "⇒ `proofs.rows[]` 是空数组；形状以 `package_face` 的返回为准",
    "ProofItem": "同 `ProofRow`：没有命题行就没有逐条证明；形状同上",
    "VsignView": "夹具没有 `out/vsigns/`（签只在 V 真签过之后才落）"
                 "⇒ 只有 `tri=not_applicable` 那一档的读数，逐键核不成",
    "ReceiptView": "夹具的 `verifications` 台账没有「有毛病」行 ⇒ 回执计数全 0，"
                   "与「台账读不成」不同形但键集相同；逐键核对留给真机 81 副本",
    "C3View": "夹具的 `ACCEPTANCE-TARGETS.json` 没有 C3 行（C1–C8 是另一批 id）"
              "⇒ `got/min` 是 null；形状以 `package_face` 的返回为准",
    "PaperFacts": "夹具没有 `out/package/main.tex`（产物夹具只造验收表与报告）"
                  "⇒ `exists=false`、其余是 null；形状以真机 81 副本的读数为准",
    "StructureCheck": "七类扫描在夹具上没有正文 ⇒ 每一类都是 `checked=false`；"
                      "逐类键集在真机 81 副本上核过",
    "StructureFinding": "夹具上没有正文 ⇒ `findings[]` 是空数组；"
                        "形状以 `texaudit.scan_tex` 的九键 finding 为准",
    "LedgerFacts": "夹具的 statements 是空表 ⇒ 五个数全是 0/null；"
                   "形状以真机 81 副本的读数为准",
    "GateTable": "夹具上八格都会跑，但 `paper` / `acceptance` 的 detail 与真机不同；"
                 "顶层键由 `ClosingView` 覆盖，行级 `GateCell` 见下一条",
    "GateCell": "八格在夹具上真有 8 行（C 条按 `ClosingView.gates.cells` 取），"
                "但这里只登记顶层；行形状以 `closing.DEFAULT_CHECKS` 为准",
    "GateBlocker": "夹具的收工门没有 blocker（`closing.check_closing` 在夹具上八格干净）"
                   "⇒ `gates.blockers[]` 是空数组；形状以 `closing.Finding.to_dict()` 为准",
    "MachineCaliber": "夹具的 retire/programs 读数存在但节点/程序为空；"
                      "形状以 `closing.machine_caliber` 的返回为准",
    "ClosingVerdict": "嵌套在 `GateTable.closing_verdict` 里；夹具上收工门不一定按"
                      "完整八格 + 项目根/报告路径问过 ⇒ 这一份是部分读数（unknown），"
                      "形状以 `closing.closing_verdict` 的返回为准",
    "ClosingVerdictCell": "`GateTable.closing_verdict.cells[]`；同上（夹具上是部分读数）",
    "CostView": "夹具只有一条 usage 行、没有 llm_call 事件 ⇒ 三源里两源是 0/null；"
                "形状以 `sessions.runs_in_session` / `unattributed_usd_of` 为准",
    "RuntimeView": "夹具只有一趟会话、没有名册 ⇒ 时间轴与名册计数大多是 0/null；"
                   "形状以 `package_face` 在真机 81 副本上的返回为准",
    "ContentAcceptance": "夹具上五条判据都读得出来（有 REPORT.md / 一条提问），"
                         "但 `failed`/`unchecked` 的分档只有真机会同时出现两档；"
                         "形状以 `reviewaccept.CRITERIA` 为准",
    # READOUT-FIX（2026-11-22）：第六档那一格的外壳在夹具上读得出来（`checked=true`、
    # `count=0`），但 `stmt_ids` 恒为空数组 —— 夹具的 statements 是空表，造不出
    # "签不背书这一行"那一行；逐条形状以 `closing.statements_unsigned_reading` 为准。
    "UnsignedSignBacking": "夹具的 statements 空表 ⇒ `stmt_ids` 是空数组；"
                           "形状以 `closing.statements_unsigned_reading` 的 "
                           "`sign_does_not_back_the_row` 那一格为准",
    "SourceRef": "出处那一格是常数形状（path/line/match/label），"
                 "C 条不需要逐行核；用 `/api/source` 的四条路径闸判据兜底",
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


# ====================================================================== 1 快照
def state_face(root: str | Path, *, sid: str = "",
               writes_allowed: bool | None = None,
               writes_reason: str = "") -> dict[str, Any]:
    """`GET /api/state` 的读模型：`{tri, snapshot, reason}`。

    `snapshot` 就是 `webui.state.snapshot()` 的返回值逐字（键集合与拆包前一致，
    主控用 `temp/_verify_w0.py` 对账过）；本函数只在外层加三态头，不重排、不改名。
    为什么要外挂一层而不是改 `snapshot()`：`snapshot()` 的键是既有判据与旧壳渲染
    共用的公开面（`tests/test_webui.py` 逐条读它），签名稳定比"少一层包装"重要。

    `sid` 是这一趟服务被交代的「当前会话」（`serve(sid=…)`，`start --watch` 交下来的
    那一个）。它一路透传给 `snapshot(current=…)` —— 于是页面上的 `current.sid` /
    `current.round` 与命令行 `--watch` 印出来的两个数逐字相同，且都在
    `webui.state.round_of()` 一处算。不传（直接 `agentflow web`）⇒ 快照退回"最近一段
    会话"，并把这件事写进 `current.source`，不假装是命令行交代的那一段。

    三态：`snapshot()` 自己不抛异常（它把读不到的东西收进 `problems`），所以这一面
    的 `tri` 只有两档 —— 有 `problems` ⇒ `unreadable`（说清是"没查成"），
    没有 ⇒ `computed`。空的但可读的工作区仍然是 `computed`（那是"读到了，里面是空的"）。
    """
    from .state import snapshot

    snap = snapshot(root, sid=sid, writes_allowed=writes_allowed,
                    writes_reason=writes_reason)
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


def _checkpoint_spend(checkpoint: Any) -> dict[str, Any] | None:
    """检查点里那一棵花销子树（读不到 / 形状不对 ⇒ `None`，不是空 dict）。

    口径与页面的 `spendOf` 同一处判定（`usd` 与 `calls` 两个键都在才算读到）：
    检查点里的 `spend` 可能是空对象（老检查点、或还没花过钱），那时"没有这一栏"
    与"这一栏是 0"必须分得开。

    为什么判断权放在这里：页面要比"同一趟"的两个数，而"检查点有没有花销读数"
    这件事若在 TS 里判一次、Python 里没人判 —— 两个数一个来自这里、一个来自
    `runs[]`，谁都不许自己再猜一遍形状。
    """
    if not isinstance(checkpoint, Mapping):
        return None
    spend = checkpoint.get("spend")
    if isinstance(spend, Mapping) and "usd" in spend and "calls" in spend:
        return dict(spend)
    return None


def _usd_of(value: Any) -> float | None:
    """一格金额收成 `float | None`（布尔与字符串不算金额，读不到就是 `None`）。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def run_view(root: str | Path, sid: str) -> dict[str, Any]:
    """`GET /api/run/{sid}` 的读模型：`RunView` = `Run` + `report` + `checkpoint`。

    - `runs`：这一趟会话里的每一趟（`sessions.runs_in_session`，与 `webui.state._scan`
      的 25 键逐字同形）；
    - `report`：交付说明（`cli.DEFAULT_REPORT_REL`，今天 = `out/report/REPORT.md`）的读数，
      两栏 `{status, text}`，`status` 是 `ok`/`missing`/`unknown`（另一套词表，见裁定 N1）；
    - `checkpoint`：`runs/agent-<角色>-<sid>.json` 的内容（读不到就是 `None`）。

    花销那几格回答的是"同一趟花了两遍算的两处是不是同一个数"：

    - `checkpoint_role`：被选中的那一份检查点属于哪个角色（`""` = 没有检查点）；
    - `checkpoint_spend_usd`：那一份检查点自己的累计（`spend.usd`，读不到 `null`）；
    - `same_run_spend_usd`：这一段会话里同角色的最后一趟的事件求和（找不到 `null`）；
    - `same_run_unknown_usd` / `same_run_start_index`：同一趟里算不出价钱的那部分、
      以及那一趟的起始下标（页面用它说清"比的是哪一趟"）；
    - `unattributed_usd`（162 ②）：这一段会话里"事件流有、而「没有任何一趟」的自报账
      认得"的钱 —— 也就是 `llm_call.usd` 合计减掉各趟 `spend_usd` 合计。它回答的是
      "那批没人认领的调用去哪了"，「不许摊进任何一趟」（81 上那 80 条 / $0.136779
      就在这一格里，而不是被某一趟的 `usd` 吃掉）。会话文件不在盘上时它是 `null`
      （"没查成"，不是"0 元没人认领"）。

    为什么 `same_run_spend_usd` 仍然读 `usd`（事件求和）而不是 `spend_usd`（162 ② 之后
    行里两格都有）：那一格的全部意义是"「另一个来源」算出来的同一个数"。把它换成
    `spend_usd`，它就与检查点那一格同源（都是这一趟自己的缝），那张并排卡从此永远绿 ——
    而它是这个数唯一的独立交叉验证。

    为什么要有这两格（页面若拿"整段会话每一趟之和"去比"一份检查点"）：会话跑过
    两趟、或跑过子代理时两者结构上必然不等，于是页面恒挂一条红徽标"两处不一致"，
    而那两个数根本不是同一件事。跨趟的合计另有其数（`runs[]` 逐趟给），不许拿来比。

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
                "checkpoint": None, "checkpoint_reason": "", "path": str(path),
                "checkpoint_role": "", "checkpoint_spend_usd": None,
                "same_run_spend_usd": None, "same_run_unknown_usd": 0,
                "same_run_start_index": None, "unattributed_usd": None}
    events, bad = SS.read_session(root_p, sid=sid)
    runs = SS.runs_in_session(events, sid=sid)
    # 未收尾的循环（82 的定格数据）：`sessions.runs_in_session` 是纯会话
    # 读数（盘上格式不动），`stale_loop` 由 `webui.state` 现算 —— 与 `/api/state` 的
    # `runs[]` 同一个函数、同一套判据（顶趟已收尾 + 这一趟没收到 end）。
    _state.mark_stale_loops(runs)
    rstatus, rtext = _read_report(root_p)
    ckpt = _checkpoint_of(root_p, sid)
    spend_tree = _checkpoint_spend(ckpt["checkpoint"])
    ckpt_role = ""
    if isinstance(ckpt["checkpoint"], Mapping):
        ckpt_role = str(ckpt["checkpoint"].get("role") or "")
    # 同一趟 = 这一段会话里 role 与检查点相同的那一趟（取最后一趟：`runs` 已按
    # `start_index` 排过序，同一个角色可能跑过不止一次，检查点是最后写的那一份）。
    same_run: dict[str, Any] | None = None
    if ckpt_role:
        for one in runs:
            if str(one.get("role") or "") == ckpt_role:
                same_run = one
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
        "checkpoint_role": ckpt_role,
        "checkpoint_spend_usd": _usd_of(None if spend_tree is None else spend_tree.get("usd")),
        "same_run_spend_usd": _usd_of(None if same_run is None else same_run.get("usd")),
        "same_run_unknown_usd": (0 if same_run is None
                                 else int(same_run.get("unknown_usd") or 0)),
        "same_run_start_index": (None if same_run is None
                                 else int(same_run.get("start_index") or 0)),
        # 162 ②：没人认领的那笔钱。它「不」进任何一趟的 `usd`（三态纪律：不许把一个
        # 没有主人的数摊给某一个主人）。
        "unattributed_usd": SS.unattributed_usd_of(events, runs),
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


# ====================================================================== 2c 趟次档案（裁定 甲）
# 为什么要有这一面（业主裁定「甲」，逐字）：
#
#   `index/run-index.json` 的口径一字不改 —— 只在"收工成功"时建；收工没做成 /
#   被叫停 ⇒ 那一格如实 `unreadable`（没建就是没建，不许拿一份半截索引冒充"已对账"）。
#   但"没建索引"不等于"这一趟没有可读的档案"：事件流还在，起止、步数、花销、派活、
#   验签与停止理由全都在会话文件里。所以另给一条只读读数，从事件流现算。
#
# 三条硬纪律：
# 1. 不落盘：`index/run-index.json` 一个字节都不写、也不读（`run_digest` 的调用链里
#    没有 `SS.rebuild_run_index` / `SS.load_run_index`；判据 a/d 从两头钉着它）；
# 2. 三态：`computed` / `unreadable` / `not_applicable` —— 没有事件流的工作区是
#    `not_applicable`（"用不着"），不是 0；指定的会话文件被删掉是 `unreadable`
#    （"没查成"），也不是 0；
# 3. 两格不互相顶替：这一面的每一个数都从事件流现算，索引被手改/被删都不会让
#    它动一个字节（判据 d）。

#: `/api/run-digest` 在两种作用域下的 `scope` 取值。
DIGEST_SCOPE_SESSION = "session"
DIGEST_SCOPE_WORKSPACE = "workspace"

#: 签文件的落点（与 `vsigns.SIGNS_DIR` 同一个目录；这里只数文件、不读内容）。
DIGEST_SIGNS_DIR = "out/vsigns"


def _digest_sign_files(root: Path) -> int | None:
    """`out/vsigns/*.json` 的个数（逐份签 + 派生归档 `issued.json`）。

    为什么把归档也算进来：84 的现场读数就是"3 个签文件（2 份签 + issued.json）"，
    这个数字回答的是"签文件目录里有几份文件"，不是"签了几个证明位"。
    三态：目录不在 ⇒ 0（这个工作区还没有签，是事实不是"没查成"）；
    目录在而列不出来 ⇒ `None`（没查成，绝不折成 0）。

    它不是"签了几份"的读数：那个数只在 `signs.recomputable` 那一格
    （见 :func:`_digest_sign_reading`）。前一版网页把这一格当成签数 ⇒
    "3 份签 + 1 份台账"被读成 4 份签（真机 lp-ball-10 的现场）。
    """
    folder = Path(str(root)) / DIGEST_SIGNS_DIR
    if not folder.is_dir():
        return 0
    try:
        return sum(1 for p in folder.glob("*.json") if p.is_file())
    except OSError:
        return None


def _digest_sign_reading(root: Path) -> dict[str, Any]:
    """签文件与签台账分开的读数（`out/vsigns/` 里的两类 `.json`）。

    目录里有两类东西，形状相同、含义不同：

    - 逐份签文件 `<artifact_sha>.json`：证据（一份稿一份签，B 收录时只读它）；
    - 派生归档 `issued.json`：台账 / 索引（"V 侧发过哪些签"的一眼清单，
      `vsigns.INDEX_NAME`；它谁都不许拿来下结论，也不参与"签了几份"）。

    把两者一起数会把"3 份签 + 1 份台账"读成"4 份签" —— 那正是本函数存在的理由：
    `files` 只数逐份签文件（口径的单一来源是 `vsigns.credentials_reading`，它自己
    就排除了 `INDEX_NAME`；本层不另写一份 glob 过滤），`ledger_present` 单独回答
    "盘上有没有那份台账"，两者不许折成一格。

    三态：目录不在 ⇒ `checked=True` / `files=0` / `ledger_present=False`
    （这个工作区还没有签，是事实不是"没查成"）；目录在而列不出来 ⇒
    `checked=False` / `files=None`（不折成 0）。
    """
    from .. import vsigns as _VS

    got = _VS.credentials_reading(root)
    folder = Path(str(root)) / DIGEST_SIGNS_DIR
    ledger = folder / _VS.INDEX_NAME
    try:
        present = bool(ledger.is_file())
    except OSError:
        present = False
    checked = bool(got.get("checked"))
    return {
        "checked": checked,
        "dir": DIGEST_SIGNS_DIR,
        "files": (int(got.get("files") or 0) if checked else None),
        "recomputable": (int(got.get("recomputable") or 0) if checked else None),
        "unbacked": (int(got.get("unbacked") or 0) if checked else None),
        "ledger_present": present,
        "ledger_path": f"{DIGEST_SIGNS_DIR}/{_VS.INDEX_NAME}",
        "why": str(got.get("why") or ""),
    }


def _is_step_count(value: Any) -> bool:
    """`agent_run_end.steps` 的合法形状：非负整数（bool 不算；负数不算）。"""
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _physical_runs(SS: Any, events: Sequence[Mapping[str, Any]], *, sid: str) -> list[dict]:
    """同一份事件、摘掉收工行自报的 `steps` 之后再切一次趟 —— 得到「物理步数」。

    为什么这么做而不是在这一层重写一遍归属/配对：`sessions.runs_in_session` 的
    三档归属（task_id 精确 / 空编号按 role / 单趟兜底）是唯一实现；在这里再写一份
    计数，两个数迟早会漂（`draft/191`：判据对齐设计，读数的来源也只能有一处）。
    摘掉 `steps` 不改变任何配对与别的字段，只让 `steps` 退回逐条 `agent_step` 数。
    """
    stripped: list[Mapping[str, Any]] = []
    for event in events:
        if (str(event.get("kind") or "") == "agent_run_end"
                and _is_step_count(event.get("steps"))):
            copy = dict(event)
            copy["steps"] = None
            stripped.append(copy)
        else:
            stripped.append(event)
    return SS.runs_in_session(stripped, sid=sid)


def _digest_groups(root_p: Path, sid: str) -> tuple[
        list[tuple[list[dict], list[dict], list[dict]]], list[str],
        tuple[str, str] | None]:
    """`run_digest` 的读盘那一段：返回 `(每段事件与两套 runs, problems, 早退档)`。

    `runs` 与 `physical_runs` 是同一份事件切两遍（后者摘掉收工行自报的 `steps`，
    见 :func:`_physical_runs`）；两者必须同长（配对规则不因 `steps` 而变）。

    `early`：非 `None` 时 `(tri, reason)` —— 调用方直接 `{**face, tri, reason}` 返回。
    三态在这里分档（删除事件流 = unreadable，没有事件流 / 空文件 = not_applicable）；
    "整段会话都读不出来"（有 problems 而一条事件都没读到）落在 `unreadable`。
    """
    problems: list[str] = []
    groups: list[tuple[list[dict], list[dict], list[dict]]] = []
    if sid:
        path = SS.session_path(root_p, sid)
        if not path.is_file():
            # 两档必须分开：这个工作区连 sessions/ 都没有 ⇒ "没有事件流"（用不着，
            # 合法初态）；sessions/ 在、独独这一段不在 ⇒ "没查成"（被删 / 编号错了），
            # 后者是裁定 ④c 要抓的"删掉事件流 ⇒ unreadable，不是 0"。
            if not SS.sessions_dir(root_p).is_dir():
                return [], [], (TRI_NOT_APPLICABLE,
                                "这个工作区没有事件流（sessions/ 目录都不在）："
                                "没有可现算的源，不是 0")
            return [], [], (TRI_UNREADABLE,
                            f"会话文件不在盘上：{path}"
                            "（这是「没查成」，不是「这一趟没有事件」）")
        events, bad = SS.read_session(root_p, sid=sid)
        if not events and not bad:
            return [], [], (TRI_NOT_APPLICABLE,
                            f"会话文件在盘上但是空的（{path}）：还没写过事件，"
                            "合法初态，不是没查成")
        if bad:
            problems.append(f"会话有 {len(bad)} 条坏行（读得出来的事件照常算）："
                            + "；".join(bad[:3]))
        groups.append((events, SS.runs_in_session(events, sid=sid),
                       _physical_runs(SS, events, sid=sid)))
    else:
        cache: dict[str, tuple[list[dict], list[str]]] = {}
        rows = SS.list_sessions(root_p, read_cache=cache)
        if not rows:
            return [], [], (TRI_NOT_APPLICABLE,
                            "这个工作区没有事件流（sessions/ 下没有 .jsonl）："
                            "没有可现算的源，不是 0")
        for row in rows:
            one_sid = str(row.get("sid") or "")
            events, bad = cache.get(one_sid, ([], []))
            if bad:
                problems.append(f"会话 {one_sid} 有 {len(bad)} 条坏行（照常算读得出来的）："
                                + "；".join(bad[:2]))
            groups.append((events, SS.runs_in_session(events, sid=one_sid),
                           _physical_runs(SS, events, sid=one_sid)))
    if problems and not any(events for events, _rows, _phys in groups):
        # 一句都没读出来（整段会话/整个工作区的文件都读不成）⇒ 计数栏是 None。
        # 这是三态纪律里"没查成"那一档：把它折成 0 会让"读不出来"读成"一趟都没有"。
        return [], problems, (TRI_UNREADABLE, "；".join(problems))
    return groups, problems, None


def _dispatched_reading(runs: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """「派了多少活」那一组读数：`dispatched` 与缺格的趟数（两档）+ 一句口径说明。

    口径只有一个来源：`agent_run_end.summons`（`LoopRun.summons` 落的那一份）——
    它是"落地了 `task_id` 的 `summon` 步"，取值是角色名。板项不在里面：
    `action=notice` / `kind=notice` 那些非运行任务由 `conductor.open_item` 建行，
    不是任何一步 `summon`。

    缺格那一格拆成两档，因为读者会把一个数读成两件事：
    `dispatched_missing_unfinished` 是还没收工的趟（按构造没有 `summons`），
    `dispatched_missing_no_summons` 是收工行没带这一格。它们都不是"派了没跑"。
    """
    n = len(runs)
    sent = [len(run["summons"]) for run in runs
            if isinstance(run.get("summons"), list)]
    dispatched = sum(sent) if sent else (0 if n == 0 else None)
    missing = [run for run in runs if not isinstance(run.get("summons"), list)]
    unfinished = sum(1 for run in missing if run.get("end_index") is None)
    no_field = len(missing) - unfinished
    missing_runs = 0 if n == 0 else len(missing)
    if not n:
        note = ("这个工作区/这一段会话还没有趟 ⇒ `dispatched` 没有对象"
                "（不是「派了 0 次」）。")
    else:
        note = ("`dispatched` 只数收工行 `summons` 里「真的派出去的召唤」"
                "（`LoopRun.summons`：落地了 `task_id` 的 `summon` 步，取值是角色名）"
                "—— 不含板项：`action=notice` / `kind=notice` 那些非运行任务"
                "（板项、到点通知、接力通知）由 `conductor.open_item` 建行，"
                "不是任何一步 `summon`，不进这个数。"
                f"`dispatched_missing_runs={missing_runs}` 是「没有 `summons` 这一格」"
                f"的趟数：其中 {unfinished} 趟是还没收工（没有 `agent_run_end`），"
                f"{no_field} 趟是收工行没带这一格 —— 它不是「派了 {missing_runs} 次活没跑」。")
    return {"dispatched": dispatched, "dispatched_missing_runs": missing_runs,
            "dispatched_missing_unfinished": (0 if n == 0 else unfinished),
            "dispatched_missing_no_summons": (0 if n == 0 else no_field),
            "dispatched_note": note}


def _steps_note(steps: int, physical: int | None, reported: int | None,
                missing: int | None, runs: int) -> str:
    """`steps` 是混合口径时，把「自报 / 物理 / 并起来」这几个数并排写清（NUMCLAIM-②）。

    不另算一遍：传进来的就是返回体上那几格。`runs == 0`（还没有趟）时物理与自报
    都是"0 趟"的定义值，不是"没查成"；某一格真的没查成，这里就明说没查成，
    不拿另一个数顶替它。
    """
    physical_text = (f"物理逐条合计 {physical}" if physical is not None else
                     ("物理逐条合计 0" if runs == 0 else "物理那一格没查成"))
    reported_text = ("自报合计 0（一趟都没有自报）" if runs == 0 else
                     (f"自报合计 {reported}（缺自报 {missing} 趟）"
                      if reported is not None else "自报那一格没查成"))
    return (f"steps 是混合口径：收工行带 steps 的趟用自报值、缺自报的趟按逐条 "
            f"agent_step 数 —— {reported_text}、{physical_text}，"
            f"并起来的这一格是 {steps}。")


def run_digest(root: str | Path, sid: str = "") -> dict[str, Any]:
    """`GET /api/run-digest` 的读模型：从会话事件流现算的一份"趟次档案"。

    与 `sessions.load_run_index` / `run_index_report` 是两件东西：

    - 索引是派生数据，只在收工成功那一刻落盘；本面不读也不写它；
    - 本面每次调用都从 `sessions/*.jsonl` 现算，所以"没建索引"的趟也有档案。

    ## 两个作用域

    - 给了 `sid`：只读那一段会话（页面的档案格就是这一档）。会话文件不在盘上 ⇒
      `unreadable`（调用方点名要这一段，找不到就是"没查成"）；但整个工作区连
      `sessions/` 目录都没有 ⇒ `not_applicable`（从没有事件流，用不着）；文件在但还
      没有任何事件 ⇒ `not_applicable`（合法初态）。删掉事件流落在前一档，不是 0；
    - 没给 `sid`：读整个工作区的事件流。`sessions/` 下没有任何 `*.jsonl` ⇒
      `not_applicable`（没有可现算的源，不是 0）。

    ## 计数口径（逐个说清，免得"同一个词两处含义"）

    - `runs`：`sessions.runs_in_session` 切出来的趟数（`agent_run_start` 到它自己的
      `agent_run_end`，或文件尾）；
    - `unfinished`：没有收到 `agent_run_end` 的趟数（`end_index is None`）；
    - `start_ts` / `end_ts`：各趟 `start_ts` 的第一个 / `end_ts` 的最后一个（空串 = 没读到）；
    - `steps`：`Σ runs[].steps`（历史口径：收工行带 `steps` 时用自报值，否则用逐条
      `agent_step` 数出来的值 —— 两个来源混在同一格）；
    - `steps_physical` / `steps_self_reported`：「同一原型的两个数」（READFIX-E）。
      `steps_physical` 是逐条 `agent_step` 数出来的（把收工行自报的 `steps` 摘掉再跑一次
      `sessions.runs_in_session` —— 归属/配对规则与 `steps` 那一格逐句同源，不在这一层
      另写一份计数）；`steps_self_reported` = `Σ agent_run_end.steps`（没有自报的趟由
      `steps_self_reported_missing_runs` 点名，不是把它当 0 加进去）。
      `steps_source`（self_report / physical）说 `steps` 这一格取自哪一档 ——
      改前只给 `steps`，页面看不出 348 是自报的（物理 339），拿它对账会差 9；
    - `steps_note`：把上面几个数并排说清的一句（自报合计 / 缺自报几趟 / 物理逐条合计 /
      并起来的 `steps` 是几）—— `steps_source` 指出的来源与 `steps` 不相等时，
      页面读这一句就能复算混合口径，不必猜；
    - `usd` / `unknown_usd_calls`：事件求和（`llm_call.usd` 归到各趟后的合计；
      `unknown_usd_calls` 是算不出价钱的调用次数）。没有一条算得出价钱的调用 ⇒ `None`；
    - `spend_usd` / `spend_missing_runs`：收工行自报账的合计（`agent_run_end.spend.usd`）
      与"没有这一格"的趟数。它不顶替 `usd`：两个来源并排，是同一笔钱的两条独立读数；
    - `dispatched` / `dispatched_missing_runs`：`Σ len(agent_run_end.summons)`（真派出去
      的活）与"没有 `summons` 这一格"的趟数。这个数不含板项：`notice` / `message`
      那些 `action=notice` 的非运行任务由 `conductor.open_item` 建行，不是任何一步
      `summon`（`LoopRun.summons` 只收落地了 `task_id` 的召唤步）⇒ 不进 `dispatched`。
      `dispatched_missing_runs` 也不是"派了没跑"：它由两档组成 —— 还没收工的趟
      （没有 `agent_run_end`，按构造没有 `summons`）与收工行没带这一格的趟，
      两档各有自己的名字（`dispatched_missing_unfinished` / `dispatched_missing_no_summons`）；
    - `verified` / `signed_proofs` / `gaps_missing_runs`：收工行 `final_gaps_reading` 的
      `total` 合计（这一趟名下带证明、查过 V 签那一栏的命题数）与
      `total - unsigned` 合计（其中签住的证明位数），以及"收工行没带这一格"的趟数。
      这里不是"签了几个签文件"：`signed_proofs` 数的是收工读数里的已签证明位；
    - `sign_files`：签文件的个数（`out/vsigns/*.json`，含派生归档 `issued.json`）。
      它确实是"文件个数"，保留原名；它与 `signed_proofs` 是两个数、两套口径
      （84 的现场：前者 3、后者 31 —— 两件事曾共用 `signed` 一格，读的人会把 31 读成
      "签了 31 份"）。目录不在 ⇒ 0；目录在而列不出来 ⇒ `None`（没查成，不是 0）；
      它不是"签了几份"：那一问问 `signs.recomputable`（见下一格）；
    - `signs`：签文件与签台账分开的读数（`vsigns.credentials_reading` 逐字）：
      `files` 是逐份签文件数（不含 `issued.json`）、`recomputable` 是复算通过
      （"签数"的唯一读数）、`unbacked` 是文件在而复算不上的份数、
      `ledger_present` / `ledger_path` 单独回答"盘上那份台账在不在"。前一版把
      `issued.json` 当成第 4 份签（"3 份签 + 1 份台账 ⇒ 4"）就是少了这一格；
    - `recomputable_signs`：复算通过的凭据份数（"签数"的唯一读数）。
      与 `sign_files` 的区别：文件在但 `passes` 点不出 need 行（自指签 / 无轴 / 不齐）
      不计入。目录不在 ⇒ 0；读不出来 ⇒ `None`。前端改读这一格；
    - `stop_reasons`：`{停止理由: 趟数}`（空字典 = 一趟都没有停止理由可数）。

    有坏行时 `tri=unreadable` 而读得出来的那些行照常算（少给数会让"这一趟 0 步"
    变成一句假话），`reason` 里带坏行数；这与 `run_events` 同一口径。
    """
    root_p = Path(str(root))
    sid = str(sid or "")
    scope = DIGEST_SCOPE_SESSION if sid else DIGEST_SCOPE_WORKSPACE
    from .. import vsigns as _VS

    _creds = _VS.credentials_reading(root_p)
    face: dict[str, Any] = {
        "tri": TRI_NOT_APPLICABLE, "reason": "", "scope": scope, "sid": sid,
        "runs": None, "unfinished": None, "start_ts": "", "end_ts": "",
        "steps": None, "usd": None, "unknown_usd_calls": None,
        # READFIX-E：`steps` 的出处与两个分量（同一原型的两个数并排）。
        "steps_source": "", "steps_physical": None, "steps_self_reported": None,
        "steps_self_reported_missing_runs": None,
        # NUMCLAIM-②：`steps` 是混合口径（自报优先、缺自报的趟按逐条数），
        # 这一格把它点名的几个数并排写出来 —— 页面不给这一句，读者无法复算。
        "steps_note": "",
        "spend_usd": None, "spend_missing_runs": None,
        "dispatched": None, "dispatched_missing_runs": None,
        #: `dispatched_missing_runs` 的两档拆分 + 这个数"含什么 / 不含什么"的一句话。
        "dispatched_missing_unfinished": None,
        "dispatched_missing_no_summons": None,
        "dispatched_note": "",
        "verified": None, "signed_proofs": None,
        "sign_files": _digest_sign_files(root_p),
        "signs": _digest_sign_reading(root_p),
        "recomputable_signs": (_creds.get("recomputable")
                               if _creds.get("checked") else None),
        "gaps_missing_runs": None,
        "stop_reasons": {},
    }

    groups, problems, early = _digest_groups(root_p, sid)
    if early is not None:
        return {**face, "tri": early[0], "reason": early[1]}

    runs = [run for _events, rows_, _phys in groups for run in rows_]
    physical_runs = [run for _events, _rows, phys in groups for run in phys]
    if len(physical_runs) != len(runs):
        # 摘掉自报 `steps` 不该改变配对；真变了就明说"物理那一格没查成"，不拿
        # 自报值冒充物理值（折平比缺一格更贵）。
        face["steps_physical"] = None
        problems.append("步数的物理读数没对上趟（摘掉自报 steps 之后趟数变了）"
                        "⇒ steps_physical 记 unknown，不自报值顶替")
        physical_runs = []
    # 只把"真的闭合了某一趟"的收工行算进档案：轮次之外的零散 end（没有对应 start）
    # 不是任何一趟的收工读数，把它算进来会让"派活 / 验签"多出没有主人的数。
    ends: list[dict] = []
    for events, rows_, _phys in groups:
        closing = sorted({int(run["end_index"]) for run in rows_
                          if isinstance(run.get("end_index"), int)})
        ends.extend(events[index] for index in closing if 0 <= index < len(events))
    n = len(runs)
    face["runs"] = n
    face["unfinished"] = sum(1 for run in runs if run.get("end_index") is None)
    face["start_ts"] = next((str(run.get("start_ts") or "") for run in runs
                             if str(run.get("start_ts") or "")), "")
    end_stamps = [str(run.get("end_ts") or "") for run in runs
                  if str(run.get("end_ts") or "")]
    face["end_ts"] = max(end_stamps) if end_stamps else ""
    face["steps"] = sum(int(run.get("steps") or 0) for run in runs)
    # READFIX-E：同一原型的两个数并排（`steps` 那一格是"自报优先"的混合值）。
    # 物理那一半来自同一份事件、同一套配对规则（见 `_physical_runs`）；自报那一半
    # 逐趟去它自己的收工行取 `steps`（缺 ⇒ 该趟记进 missing，不当 0 加）。
    if physical_runs:
        face["steps_physical"] = sum(int(run.get("steps") or 0) for run in physical_runs)
    reported: list[int] = []
    for events, rows_, _phys in groups:
        for run in rows_:
            idx = run.get("end_index")
            if not isinstance(idx, int) or not (0 <= idx < len(events)):
                continue
            event = events[idx]
            if str(event.get("kind") or "") != "agent_run_end":
                continue
            if _is_step_count(event.get("steps")):
                reported.append(int(event["steps"]))
    face["steps_self_reported"] = (sum(reported) if reported
                                   else (0 if n == 0 else None))
    face["steps_self_reported_missing_runs"] = 0 if n == 0 else n - len(reported)
    face["steps_source"] = "self_report" if reported else "physical"
    # NUMCLAIM-② 的判据（`tests/test_numclaim_notes_match_their_numbers.py::
    # test_run_digest_steps_names_which_number_it_is`）要的两种合格形态之一：
    # `steps` 不等于它点名的来源时，返回体必须带一句把这几个数都摆出来的说明。
    face["steps_note"] = _steps_note(
        int(face["steps"]), face["steps_physical"], face["steps_self_reported"],
        face["steps_self_reported_missing_runs"], n)

    def _num(value: Any) -> bool:
        return isinstance(value, (int, float)) and not isinstance(value, bool)

    usd_values = [float(run["usd"]) for run in runs if _num(run.get("usd"))]
    face["usd"] = round(sum(usd_values), 6) if usd_values else (0.0 if n == 0 else None)
    face["unknown_usd_calls"] = (0 if n == 0 else
                                 sum(int(run.get("unknown_usd") or 0) for run in runs))
    spend_values = [float(run["spend_usd"]) for run in runs if _num(run.get("spend_usd"))]
    face["spend_usd"] = (round(sum(spend_values), 6) if spend_values
                         else (0.0 if n == 0 else None))
    face["spend_missing_runs"] = 0 if n == 0 else sum(
        1 for run in runs if not _num(run.get("spend_usd")))

    face.update(_dispatched_reading(runs))

    totals = signeds = seen = 0
    for event in ends:
        reading = event.get("final_gaps_reading")
        if not isinstance(reading, Mapping):
            continue
        total, unsigned = reading.get("total"), reading.get("unsigned")
        if _num(total) and _num(unsigned):
            seen += 1
            totals += max(0, int(total))
            signeds += max(0, int(total) - int(unsigned))
    face["verified"] = totals if seen else (0 if n == 0 else None)
    face["signed_proofs"] = signeds if seen else (0 if n == 0 else None)
    face["gaps_missing_runs"] = 0 if n == 0 else len(ends) - seen

    reasons: dict[str, int] = {}
    for run in runs:
        why = str(run.get("stop_reason") or "")
        if why:
            reasons[why] = reasons.get(why, 0) + 1
    face["stop_reasons"] = reasons

    if problems:
        return {**face, "tri": TRI_UNREADABLE, "reason": "；".join(problems)}
    return {**face, "tri": TRI_COMPUTED, "reason": ""}


# ====================================================================== 3 证据链
#: 证据面读的那几族（表名 / 给前端的那一栏 / 真身出处）。
_EVIDENCE_TABLES: tuple[tuple[str, str, str], ...] = (
    ("statements", "statements", "store.rows(\"statements\")"),
    ("conjectures", "conjectures", "store.rows(\"conjectures\")"),
    ("experiments", "experiments", "store.rows(\"experiments\")"),
    ("review_findings", "review_findings", "store.rows(\"review_findings\")"),
    ("relations", "relations", "store.rows(\"relations\")"),
    # 2026-11-14 补：稿件台账（`documents`）此前只有命令行读得到
    # （`doc.list_documents` 工具 / `table.list documents`），网页端一栏都没有 ——
    # 于是业主盯页面时看不到"已经写了几份稿、最近几份是什么状态"。
    # 与上面四张表同一条口径：读的是同一处 `store.rows("documents")`，
    # 计数就是这份列表的长度（页面不另算一遍）。
    ("documents", "documents", "store.rows(\"documents\")"),
)

#: 会被逐行注解的栏（遍历顺序）：`_EVIDENCE_TABLES` 里除 `documents` 之外的五栏，再加两栏
#: 非表来源（`verifications` / `secretary`）。注意它是「注解面」的 7 栏、不是证据面的 8 栏 ——
#: `documents` 要不要进注解面是另一次改动（进了会改行形状：多出 `by_role` / `by_task_id` 几格）。
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
#: 台账行自己带了 `task_id`（`ARTIFACTS.jsonl` 的写侧 `artifacts.record(task_id=...)`
#: 真的落了这一格）。它比"按路径反查事件"强：反查是推断，这一格是写入时记下的归属。
LEDGER_TASK_TRI_ROW = "row"
#: 这一行是写入，但写入方没记归属：行的 `task_id` 是空串，按路径反查也没有命中。
#: 它与 `missing` 不同：`missing` 是"查过了、没找到"（该有却没有），而这一档是
#: "这一行的写入路径本来就没带归属可记"（真机：`agent_loop.write_note` /
#: `manuscriptopen.open_manuscript` / `agent_e.run_experiment` 的框架产物行，
#: 行上 `task_id=""`）。面板据此写"这一档没有归属"，不写"缺任务号"。
LEDGER_TASK_TRI_NOT_RECORDED = "not_recorded"

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
#:   （`schema.py`，FC-27 人审），这里刻意不动；
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


def _token_pattern(tokens: Sequence[str]) -> re.Pattern[str]:
    """把一批反查口令编成一条正则（词边界那一条见 :func:`_ledger_by_task_id` 第 3 条）。

    口令按长度倒序进交替：`re` 在同一个起点上按书写顺序试候选，长的排在前才不会被
    自己的前缀抢走（`stmt:000001` 与它后面更长的编号是两条口令）。
    """
    return re.compile("|".join(
        f"(?<![0-9A-Za-z_])(?:{re.escape(one)})(?![0-9A-Za-z_])" for one in tokens))


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

    ## 为什么先解析、再跑正则，且正则只跑"这一行里真有的那些口令"

    "先 `findall`、命中才 `json.loads`"这个次序在原理上省的是 JSON 解析，实测却把
    99% 的时间花在那条 168/293 路交替的巨正则上（真机 81：`findall` 5,604 ms /
    9,995 ms，而把这 1,045 条候选行全部 `json.loads` 只要 19–21 ms，见
    `temp/161_scan_variants.py` 与同目录的 161 报告）。所以现在两件事的次序反过来：
    先解析（便宜，而且能拿到 `kind` 做确定性过滤），只对那五种 kind 的行跑正则。

    第三件事是"按行窄化候选"：一条口令的匹配文本就是它自己，所以一行里根本没有的那条
    口令结构上匹配不到 —— 把它从交替里去掉不改变任何一个命中。窄化只在"这一行真有的
    那几条"上重建那条正则（`found.setdefault` 只关心集合，行内次序不影响结果），
    真正决定命中与否的仍是上面四条。真机 83 上这一面从 13,900 ms 降到 90 ms
    （`temp/probe_o5_ledger.py`：同一批行、同一个 `found`）。

    口径一个字没改：决定"哪一行能成为答案"的仍是上面那四条。两个次序的输入集合
    完全相同（先 kind 后正则 vs 先正则后 kind，取的是同一个交集；`findall` 的输入
    文本也还是那一行原文），只有通过 kind 的行才会被收，所以 `found` 逐号相同 ——
    真机 81 上实测 68/68、176/176 逐号一致（`temp/161_scan_variants.py` 的 B 口径），
    窄化这一刀在 83 / t5b / chain-v1 / p9b 四份真机上也是逐号一致。
    """
    wanted = sorted({str(t) for t in tokens if str(t)}, key=len, reverse=True)
    if not wanted:
        return {}
    pattern = _token_pattern(wanted)
    kinds = set(LEDGER_EVENT_SCAN_KINDS)
    found: dict[str, str] = {}
    for path in _recent_session_files(root_p):
        text = _session_tail(path)
        if not text:
            continue
        for line in text.splitlines():
            if '"task_id"' not in line:
                continue          # 便宜的预筛：没有编号的事件不可能是答案
            try:
                event = json.loads(line)
            except ValueError:
                continue          # 坏行：这一段里它算没读到（不猜）
            if str(event.get("kind") or "") not in kinds:
                continue          # 先 kind 后正则：正则只跑在会进答案的那几行上
            task_id = str(event.get("task_id") or "").strip()
            if not task_id:
                continue
            present = [one for one in wanted if one in line]
            if not present:
                continue          # 这一行一条口令都不含 ⇒ 正则在那条上不可能命中
            rx = pattern if len(present) == len(wanted) else _token_pattern(present)
            for token in rx.findall(line):
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
    if str(column) == "ledger":
        # 2026-11-19（K1/K2 之后）：`artifacts.FIELDS` 多了 `instance` /
        # `identity_conflict` / `family` 三格，而台账是追加式 JSONL —— 老行上没有它们。
        # 读模型按 `FIELDS` 补齐（缺 = 空串）：生成物 `ui/src/types.ts` 的 `ArtifactRow`
        # 声明的是"后端真读得到的键"，老行漏三格就等于声明与实际不符（契约 C 是双向的）。
        from ..artifacts import FIELDS as _ARTIFACT_FIELDS

        for key in _ARTIFACT_FIELDS:
            # B2d：`kind_unknown` 是「这一行有没有那个标记」的事实，不是"缺了补空串"
            # 的普通栏位 —— 补成 `""` 会让读侧再也分不清 `legacy`（老行没有这一格）
            # 与 `unknown`（新写带着这一格）。它在 `types.ts` 里也声明成可选的
            # （`kind_unknown?: boolean`），所以不补也不违反契约 C 的键集合。
            if key == "kind_unknown":
                continue
            got.setdefault(key, "")
    role, role_source = _ledger_role(row)
    got["by_role"] = role
    got["by_role_source"] = role_source
    # 产物台账（`ledger`）的行自己就带 `task_id`（写侧 `artifacts.record` 的入参）。
    # 有它就采用它：那是写入时记下的归属，比"按路径反查事件"更硬，也解释了为什么
    # 真机 60 行里有 40 行明明有台账号、旧读法却全报 `missing`（旧读法只按路径反查，
    # 从不看行上的这一格）。
    own = str(row.get("task_id") or "").strip()
    if column in ("ledger", "ledger_verify") and own:
        got["by_task_id"] = own
        got["by_task_id_tri"] = LEDGER_TASK_TRI_ROW
        return got
    spec = _LEDGER_ROW_TOKENS.get(column)
    if spec is None:
        got["by_task_id"] = ""
        got["by_task_id_tri"] = TRI_NOT_APPLICABLE
        return got
    token = _ledger_token(spec[0], spec[1], row)
    task_id = str(index.get(token) or "") if token else ""
    got["by_task_id"] = task_id
    if task_id:
        got["by_task_id_tri"] = LEDGER_TASK_TRI_EVENT
    elif column in ("ledger", "ledger_verify"):
        # 写入方没记归属：行上 `task_id` 空、反查也没有。它不是"缺任务号"
        # （`missing` 读起来像该有却没有），而是"这一档没有归属"。
        got["by_task_id_tri"] = LEDGER_TASK_TRI_NOT_RECORDED
    else:
        got["by_task_id_tri"] = LEDGER_TASK_TRI_MISSING
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
                # 行上自己带 task_id 的（产物台账）不必再进反查口令：那一格是写入时
                # 记下的归属，比推断强，也省掉一次无用的路径扫描。
                if (column in ("ledger", "ledger_verify")
                        and str(row.get("task_id") or "").strip()):
                    continue
                token = _ledger_token(spec[0], spec[1], row)
                if token:
                    tokens.append(token)
    index = _ledger_by_task_id(root_p, tokens)
    return {str(column): [_annotate_ledger_row(str(column), row, index)
                          if isinstance(row, Mapping) else row
                          for row in rows]
            for column, rows in columns.items()}


# ============================================================ 3.5 呈现读数
#
# 这一节只做一件事：把判据层已经有的读数换成"人要看的那一格"，不改任何判定语义。
# 三条口径（「对于 sha 值用户并不关心，只用显示是否一致即可」「对于命题的显示要标注
# 非平凡度等级」「证据链第 4 位按路径显示」）：
#
# 1. sha 一律不出原文，只出一致性读数：:data:`SHA_MATCH` / :data:`SHA_MISMATCH` /
#    :data:`SHA_UNKNOWN`。三档里"没得比"必须与"不一致"分开 —— 折平就等于把
#    "没有第二份可核"读成"两份不一样"，那是本项目的三态纪律最忌的一折；
# 2. 非平凡度：档位与显示名一律调 `secretary.nontriviality_of` /
#    `nontriviality_label`（本模块不另写一份读口），这里只补 hover 用的那句说明；
#    判不了是 `None` + 空 label，页面显示"未判"，绝不折成 T0（T0 是一档真的档位）；
# 3. 五元位第 4 位是二维的（`{证明号: 状态}`）：逐路径给出来（`formal_by_proof`），
#    汇总留给等级派生 —— 折成一条汇总就等于让 `#p2` 借 `#p1` 的光。

#: sha 一致性的三档（`match` / `mismatch` / `unknown`）。
SHA_MATCH = "match"
SHA_MISMATCH = "mismatch"
SHA_UNKNOWN = "unknown"

#: 实验的「代码一致」那一格多出的一档：这一行在台账上已经撤销（脚本改过）。
#:
#: 裁定（逐字）：「改脚本后应该重新登记并把老登记撤销」。
#: 为什么它不能并进 `mismatch`：「不一致」说的是"这一行还挂着，但它钉的脚本已经不是
#: 盘上那一份"——那是一处异常，要人去处理；「已撤销」说的是"这件事已经处置过：
#: 老登记作废、新登记接上"。前者是红，后者不是红。折平之后，读者看见一片红，
#: 分不清哪一条要动手、哪一条已经被撤过（现场：`projects/sylow3` 的 000000 与 000001）。
CODE_CONSISTENCY_REVOKED = "revoked"

#: 非平凡度"判不了"在页面上的写法（不是 T0 —— T0 是一档真的档位）。
NONTRIVIALITY_UNJUDGED_WORD = "未判"

#: 非平凡度"不适用"在页面上的写法（概念 / 定义行没有证明正文，判档这一问对它不成立）。
#:
#: 这一格与 :data:`NONTRIVIALITY_UNJUDGED_WORD` 必须是两个词。
#: "判不了"说的是"该判而没判"（没缝 / 缺正文 / 正文被截断），处置是"再去判一次"；
#: "不适用"说的是"这一问对它不成立"（`kind="concept"` / `"definition"` 没有证明正文），
#: 再判一次也不会有别的结论。词只有一个来源：`nontriviality_of` 的 `tri` 三档 +
#: 档位那五档（T0–T4）—— 页面上因此是"三个词"（档位 / 不适用 / 未判），不许折平。
#: 真机读数（`projects/mp3-r3`）：30 条概念行的非平凡度一条记录都没有，而读侧对
#: "没有记录"与"不需要记录"都只印一个"未判"。
NONTRIVIALITY_NOT_APPLICABLE_WORD = "不适用"

#: 档位号 → hover 里那句说明（逐条对着 `secretary.NONTRIVIALITY_LEVELS` 与它上面那张
#: 语义表；档位只有 0..4 这五个取值，`nontriviality_label` 负责 T0 这四个字符）。
_NONTRIVIALITY_MEANINGS: dict[int, str] = {
    0: "T0 基础定理或初步结论（含由数值实验直接穷举得出的那些）",
    1: "T1 有一定价值的非平凡结论",
    2: "T2 证明方法都在常规范围内，但工作量较大",
    3: "T3 需要用较多的技巧或跨领域工具",
    4: "T4 需要天才般的洞察力，或思维链极长，或是偏离主流研究方向的神奇构造",
}


def sha_consistency(want: Any, now: Any) -> str:
    """两份 sha 是不是同一份：`match` / `mismatch` / `unknown`（任一边拿不出来 = 没得比）。

    为什么这一格不显示 sha 原文：业主的口径是"用户并不关心 sha 值，只用显示是否
    一致即可"。于是这一层把"两份十六进制串相不相等"收成一个词，页面只印那个词。
    绝不截断显示前 8 位那种 —— 半截哈希既不能核也不能读。

    三档不许折平：任一边是空串（没记 sha、文件不在盘上、那一栏不适用）⇒ `unknown`，
    它与 `mismatch` 是两件事（"没得比"不是"不一致"）。大小写与首尾空白不算差异
    （盘上的 sha 有时带大写或空格，那是同一个值）。

    这一条是"sha 一致性打桩"的注射点：把所有调用点都走这里，才能用一个桩把
    "恒一致"打进去看 `mismatch` 那一支的判据会不会红
    （`tests/test_webui_readings_format.py` 的第⑤条）。
    """
    left = str(want or "").strip().lower()
    right = str(now or "").strip().lower()
    if not left or not right:
        return SHA_UNKNOWN
    return SHA_MATCH if left == right else SHA_MISMATCH


def code_consistency(row: Mapping[str, Any], now: Any) -> str:
    """实验行的「代码一致」四档：`match` / `revoked` / `mismatch` / `unknown`。

    四档的语义（判据逐条钉在
    `tests/test_experiment_is_revoked_when_its_script_changes.py`）：

    - `match`：台账钉的 sha 与盘上现在这一份脚本是同一份；
    - `revoked`：这一行已经撤销（`schema.experiment_is_voided`）—— 它钉的是旧脚本，
      撤销理由与两个 sha 前缀在行上（`void_reason` / `code_sha_from` / `code_sha_to`）。
      撤销优先于 sha 比较：撤销是台账上的既成事实，与盘上现在有没有那个文件无关；
    - `mismatch`：仍有效，但 sha 对不上 —— 这一条是异常（脚本改过却没重新登记）；
    - `unknown`：没得比（行上没记 sha / 脚本不在盘上 / 读不出来），不许冒充 `mismatch`。

    写侧记的哈希只有前 16 位（`verify_tools.code_hash` 的定义就是「前 16 位」），
    所以「同一份脚本」在这里必须是前缀关系而不是逐字相等 —— 直接逐字比会把每一行都
    判成 `mismatch`（真机 `projects/sylow3` 的两行就是这样，而 `exp 000001` 明明一致）。
    前缀比较的口径就只有这一句：一方是另一方的前缀即是同一份（`sha_consistency` 只比值、
    不截断；这里只把短的那一边对齐，不另写第二套「同一份」的判据）。
    比值本身仍然只走 :func:`sha_consistency`（一处口径）：这一层只把短的那一边对齐，
    并多加一档状态。
    """
    from .. import schema as S

    if S.experiment_is_voided(dict(row)):
        return CODE_CONSISTENCY_REVOKED
    want = str(row.get("code_hash") or "").strip().lower()
    got = str(now or "").strip().lower()
    if want and got and len(want) < len(got):
        return sha_consistency(want, got[:len(want)])
    return sha_consistency(want, got)


def _ledger_verify_consistency(row: Mapping[str, Any]) -> str:
    """台账核对行的一致性：拿那一行的两份 sha 真比一次（`sha_consistency`）。

    为什么不从 `status` 折过来：`status` 是 `artifacts.STATUSES` 的五档（ok / changed /
    missing / unreadable / not_a_file），它说的是"这一条核对是怎么结束的"；而"一致吗"
    问的是两份 sha 相不相等。两者在 `missing` / `unreadable` 这两档上会分家 ——
    那时 `sha256_now` 是空串，一致性那一格必须是 `unknown`（没得比），不是"不一致"。
    比一次 sha 就把这条口径落在唯一一处（`sha_consistency`），于是"把一致性打桩成
    恒一致 ⇒ 不一致那一支必红"这个注射点也真的能覆盖这一栏。
    """
    return sha_consistency(row.get("sha256"), row.get("sha256_now"))


def _statement_tier_reading(root: str | Path, row: Mapping[str, Any]) -> dict[str, Any]:
    """一条命题当前的非平凡度：`{level, label, meaning, tri, word, matched_by}`。

    读口只有一处：`secretary.nontriviality_of`（按 `stmt_id` 折叠旁支台账
    `out/secretary/nontriviality.jsonl`；旧行才回退到正文 sha）。这里只做四件事：
    把这一行的号传下去、把 hover 那句说明补上、把"判不了"写成 `level=None` + 空
    `label`、把"不适用"与"判不了"写成两个词。

    ## 按号，不按正文
    命题行的身份是 `stmt_id`。按正文 sha 关联有一个后果：正文改一个字，档位就读成
    "未判"。所以号从行上取、原样传给读口；`matched_by` 跟着回来，读的人能分辨这一
    档是按号命中的，还是读旧行时按 sha 回退的。

    ## 三个词
    `word` 是页面上印出来的那一个词，取值只有三类：

    | 结局 | `tri` | `word` |
    |---|---|---|
    | 读到一档 | `computed` | `T0`…`T4`（`secretary.nontriviality_label` 给的，不自己拼） |
    | 这一问对它不成立（概念 / 定义行没有证明正文） | `not_applicable` | :data:`NONTRIVIALITY_NOT_APPLICABLE_WORD` |
    | 该判而没判（台账里没有 / 记的是判不了 / 读不出来） | `unknown` | :data:`NONTRIVIALITY_UNJUDGED_WORD` |

    为什么必须分开：`level` / `label` 在这后两档上长得一样（都是 `None` + 空串），
    折平就把"再判一次就会有结论"与"再判一次也不会有结论"印成同一个词 ——
    真机 `projects/mp3-r3` 的 30 条概念行正是这样：它们结构上不需要判，
    而页面与它们的读数都只说"未判"。

    `meaning` 在不是 `computed` 时是空串：hover 里编一句"这是 T0"正是要防的那种假话。

    代价：一条命题读一遍旁支台账（`nontriviality_of` 的读法就是逐行扫）。命题行在
    真机上是个位数（p9b 7 行）、台账是几十行，一次请求的可接受代价就在这里。
    要再省就得在 `secretary` 那边加一个批量读口（一次读完建索引）—— 那会动一个
    那会动 `secretary.py`，这里刻意不动：这一层只搬运，不给别处添新的读法。
    """
    from .. import statementbody as SB

    body = SB.body_of(row)
    stmt_id = str(row.get("stmt_id") or "")
    level: int | None = None
    label = ""
    tri = "unknown"
    matched_by = ""
    paths: list[dict[str, Any]] = []
    min_of: list[int] = []
    partial = False
    paths_unjudged: list[int] = []
    try:
        from ..secretary import nontriviality_of

        got = nontriviality_of(root, body, stmt_id=stmt_id,
                               path_groups=_expected_path_groups(row))
        raw = got.get("level")
        level = raw if isinstance(raw, int) and not isinstance(raw, bool) else None
        label = str(got.get("label") or "") if level is not None else ""
        matched_by = str(got.get("matched_by") or "")
        paths = [dict(p) for p in (got.get("paths") or []) if isinstance(p, Mapping)]
        min_of = [int(x) for x in (got.get("min_of") or []) if isinstance(x, int)]
        partial = bool(got.get("partial"))
        paths_unjudged = [int(x) for x in (got.get("paths_unjudged") or [])]
        if got.get("tri") == TRI_NOT_APPLICABLE:
            # 「不适用」不是「判不了」：`level`/`label` 都是空，只有一个可判的标记
            # （`applicable=False`）能把两者分开 —— 它就是这一格的 `tri`。
            tri = TRI_NOT_APPLICABLE
        else:
            tri = "computed" if (level is not None and label) else "unknown"
    except Exception:  # noqa: BLE001 - 读数层：取不到就是"判不了"，不是 T0
        level, label, tri, matched_by = None, "", "unknown", ""
    meaning = _NONTRIVIALITY_MEANINGS.get(level, "") if level is not None else ""
    if tri == "computed":
        word = label
    elif tri == TRI_NOT_APPLICABLE:
        word = NONTRIVIALITY_NOT_APPLICABLE_WORD
    else:
        word = NONTRIVIALITY_UNJUDGED_WORD
    return {"level": level, "label": label, "meaning": meaning, "tri": tri, "word": word,
            "matched_by": matched_by,
            # ---- 逐路径（NT2）：命题级是各路径 min，两条路径各自可核 ------------
            # `paths` 一条路径一行（`path_group` / 该路径当前档位 / 历史最小 / 判的材料 sha）；
            # `min_of` 是命题级这个 min 从哪几个值来（逐路径历史最小，按路径号升序）；
            # `partial` + `paths_unjudged` 说"还有路径没判" —— 不许折成"全判了"。
            "paths": paths, "min_of": min_of, "partial": partial,
            "paths_unjudged": paths_unjudged}


def _expected_path_groups(row: Mapping[str, Any]) -> list[int]:
    """这一条命题应该有哪几条路径（`statements.manuscripts` 的键，升序）。

    读侧拿它判"部分路径未判"：台账里只判了第 1 条、而这一行有两条路径的稿 ⇒
    `partial=true` + `paths_unjudged=[2]`，不许把"只判了一条"折成"命题级已经算全了"。
    没有 `manuscripts`（老行 / 概念行）⇒ 空清单（读侧只知道台账里那几条）。
    """
    books = row.get("manuscripts")
    out: list[int] = []
    if not isinstance(books, Mapping):
        return out
    for key in books:
        try:
            no = int(str(key))
        except (TypeError, ValueError):
            continue
        if no >= 1 and no not in out:
            out.append(no)
    return sorted(out)


def _bit_word(value: Any) -> str:
    """一个标量位的状态词（`evidencebits.BIT_STATES` 的同一批词，不另造一套）。

    位在盘上是两种形状：第 1 位是四态字符串（`pending` / `na` / `failed` /
    `verified`），第 2/3/5 位是布尔。布尔在这里折成写侧那两档（`True` ⇒ `verified`、
    `False` ⇒ `pending`），于是页面上五位的词是同一套 —— 而不是四格一串 true/false。
    词表外的字符串原样返回（不折成 `pending`：读不出来与"没做"是两件事）。
    """
    if isinstance(value, bool):
        return "verified" if value else "pending"
    return str(value or "")


def _per_proof_numbers(row: Mapping[str, Any]) -> list[int]:
    """这一条命题在盘上认得出来的证明号：三张逐证明表的并集（升序）。

    为什么要并集、而不是只看 `optimized_by_proof`：那一格只回答"记过的那几份各是
    什么"，缺格的那一份根本不在表里 —— 只看它，"这一份还没记"就会从屏幕上
    消失，而那正是三态里的 `not_recorded`（缺格不许折成 false）。
    所以逐份的编号取自三张同形表（`reviewed_by_proof` / `reviewed_sha_by_proof` /
    `optimized_by_proof`）：任一张认得这一份，这一份就在命题台账里占一行 —— 于是
    「优化」与签过 / 签的正文那两张表按 `proof_no` 并排，缺哪一格就写哪一档，
    不借相邻那一份的光。

    为什么不把 `formal_by_proof` 也并进来：那一格在老行 / 单路径行上是标量，
    读侧按文档把它读成 `{1: 那个四态}` —— 连"没有任何证明表"的概念行都会因此
    凭空多出 `#p1`，页面上会写"#p1 未记录"（暗示这一条有一份证明）。这一批只
    「并排签的那两张表」，形式化那条路径由它自己那一列（`formal_paths`）负责。

    一张表读不出来只跳过它（另外两张照给）；证明号认不出的键本来就进不了那几张表。
    """
    from .. import evidencebits as EB

    numbers: set[int] = set()
    for reader in (EB.reviewed_by_proof, EB.reviewed_sha_by_proof,
                   EB.optimized_by_proof):
        try:
            table = reader(row)
        except Exception:  # noqa: BLE001 - 一张读不出来不拖累另外两张
            continue
        for raw_no in table:
            try:
                no = int(raw_no)
            except (TypeError, ValueError):
                continue
            if no >= 1:
                numbers.add(no)
    return sorted(numbers)


def _bit_readings(row: Mapping[str, Any],
                  bits: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """命题行的五元位逐位读数。

    页面若只展开第 4 位（按路径），第 1/2/3/5 位在屏幕上根本不存在 ——
    于是"这一条到没到定理"只能从派生的等级那一格去猜。这里把四位各自的读数
    摆出来，第 4 位仍然是 `formal_paths`（二维的，一位多行，见
    :func:`_statement_readings`），不在这里压成一句汇总。

    第 3 位另给 `reviewed_paths`：`reviewed_by_proof` 那张表说"这一份签过没有"，
    一条证明一行（`#p2` 不许借 `#p1` 的光）。它回答的是"签没签过"，"签的是不是
    现在这一份正文"由 `verifications` 的 `proof_sha_consistency` 回答 ——
    两件事各有各的落点，这一格不替另一件事说话。

    「是否优化」再给一格 `optimized_paths`，
    与 `reviewed_paths` 并排、同一条证明一行。三态由
    `evidencebits.optimized_state` 给（唯一读口，本处不另判一次）：
    `true` / `false` / `not_recorded`。缺格就是 `not_recorded`，不许折成
    `false` —— 折平会让整库存量行一次全变「未优化」（真机 3000+ 行），
    而折成 `true` 更坏（等于自报洗过）。逐份编号见 :func:`_per_proof_numbers`
    （三张表的并集，所以"只有签的那张表认得、优化那张表还没记"的那一份也在）。

    读出不来时四格都是空串（页面按 `unknown` 处置），不冒充 `pending`；
    `optimized_paths` 读不出来时是空数组（页面写「未记录（说不出是哪一份）」，
    不写「未优化」）。

    `bits` 是调用方已经读出来的那份位读数（`evidencebits.bits_from_row`）——
    同一行在 :func:`_statement_readings` 里还要拿它派生等级，读一次就够；
    不给（`None`）就在本函数里读，读不出来仍按上面那一条处置。
    """
    from .. import evidencebits as EB

    out: dict[str, Any] = {"bit_numeric": "", "bit_proof": "", "bit_reviewed": "",
                           "bit_audited": "", "reviewed_paths": [], "optimized_paths": []}
    if bits is None:
        try:
            bits = EB.bits_from_row(row)
        except Exception:  # noqa: BLE001 - 位读不出来 ⇒ 空串（页面写 unknown，不冒充 pending）
            return out
    out["bit_numeric"] = _bit_word(bits.get("numeric"))
    out["bit_proof"] = _bit_word(bits.get("proof"))
    out["bit_reviewed"] = _bit_word(bits.get("reviewed"))
    out["bit_audited"] = _bit_word(bits.get("audited"))
    try:
        per = EB.reviewed_by_proof(row)
    except Exception:  # noqa: BLE001 - 逐条那张表读不出来 ⇒ 一条都不列（不是"没签"）
        per = {}
    out["reviewed_paths"] = [{"proof_no": int(no), "reviewed": bool(flag)}
                             for no, flag in sorted(per.items())]
    try:
        out["optimized_paths"] = [{"proof_no": no, "state": EB.optimized_state(row, no)}
                                  for no in _per_proof_numbers(row)]
    except Exception:  # noqa: BLE001 - 逐份优化态读不出来 ⇒ 一条都不列（页面按未记录处置）
        out["optimized_paths"] = []
    return out


def _statement_readings(root: Path, rows: list[dict]) -> list[dict[str, Any]]:
    """命题行补四组呈现读数：引文五档、非平凡度、第 4 位的逐路径表、五位的逐位格。

    - `quote_state`：引文的唯一读口径 `evidencebits.quote_state`（verbatim / semantic /
      mismatch / unchecked / no_evidence）—— 页面不再拿 `quote_verified` 这个布尔量
      去猜"没查"与"没证据"的区别；
    - `nontriviality*`：见 :func:`_statement_tier_reading`；
    - `formal_paths`：`[{proof_no, state}]`，二维位逐路径（`evidencebits.formal_by_proof`）；
    - `grade` / `grade_label`：五元位派生的等级（任一路径通过即正式定理，
      `evidencebits.derive_grade`）—— 页面上"这一条到没到定理"与"哪条路径撑起来的"
      于是分得开；
    - `bit_numeric` / `bit_proof` / `bit_reviewed` / `bit_audited` 与 `reviewed_paths`：
      见 :func:`_bit_readings`（第 4 位不在这里，它仍是逐路径那一格）；
    - `optimized_paths`：`[{proof_no, state}]`，「是否优化」按证明逐份（三态
      `true` / `false` / `not_recorded`，缺格不折成 false）—— 与 `reviewed_paths`
      并排，同一条证明一行；编号取自三张逐证明表的并集。

    一个都不许自己算：每种读数各自只有一个出处，这里只搬运。
    """
    from .. import evidencebits as EB

    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            out.append(row)
            continue
        got = dict(row)
        try:
            got["quote_state"] = EB.quote_state(row)
        except Exception:  # noqa: BLE001 - 引文那一格读不出来 ⇒ 按没查处置
            got["quote_state"] = "unchecked"
        tier = _statement_tier_reading(root, row)
        got["nontriviality"] = tier["level"]
        got["nontriviality_label"] = tier["label"]
        got["nontriviality_meaning"] = tier["meaning"]
        got["nontriviality_tri"] = tier["tri"]
        # 页面直接印这一个词：`T0`…`T4` / `不适用` / `未判`（三个词，见
        # :func:`_statement_tier_reading`）。`label` 仍只装档位名 —— 让 `不适用`
        # 借那一格会抹掉"这一行有没有档位"这个判据。
        got["nontriviality_word"] = tier["word"]
        # 这一档是按号命中的、还是读旧行时按 sha 回退的：
        # 读的人要能分辨"正文改了档位还在"与"按文本碰巧对上"，两件事不许折平。
        got["nontriviality_matched_by"] = tier["matched_by"]
        # ---- 逐路径（NT2）：一个路径一行 + 命题级 min 可复算 --------------------
        # `nontriviality_paths` = `[{path_group, level, floor, at, ...}]`（一条路径一行，
        # 旧行无 `path_group` ⇒ 路径 1）；`nontriviality_min_of` = 命题级 min 的来源值；
        # `nontriviality_partial` + `nontriviality_paths_unjudged` = "还有路径没判"，
        # 不许把部分读数折成"命题级已算全"。
        got["nontriviality_paths"] = list(tier.get("paths") or [])
        got["nontriviality_min_of"] = list(tier.get("min_of") or [])
        got["nontriviality_partial"] = bool(tier.get("partial"))
        got["nontriviality_paths_unjudged"] = list(tier.get("paths_unjudged") or [])
        # 这五位读数与下面派生的等级读的是同一份位数据（`bits_from_row`）：
        # 读一次、两处共用 —— 原来同一行要读两遍，而两次之间没有任何东西会变。
        bits: Mapping[str, Any] | None
        try:
            bits = EB.bits_from_row(row)
        except Exception:  # noqa: BLE001 - 位读不出来 ⇒ 空串（页面按 unknown 处置）
            bits = None
        got.update(_bit_readings(row, bits))
        try:
            per = EB.formal_by_proof(row)
        except Exception:  # noqa: BLE001 - 第 4 位读不出来 ⇒ 一条路径都不列（不是"没验过"）
            per = {}
        got["formal_paths"] = [{"proof_no": int(no), "state": str(state)}
                               for no, state in sorted(per.items())]
        grade = ""
        try:
            grade = EB.derive_grade(bits if bits is not None else EB.bits_from_row(row),
                                    kind=str(row.get("kind") or ""))
        except Exception:  # noqa: BLE001 - 等级算不出来 ⇒ 空串（页面按 unknown 处置）
            grade = ""
        got["grade"] = grade
        got["grade_label"] = EB.GRADE_LABELS.get(grade, "")
        # ---- 读侧投影（KINDREAD，2026-11-20）：盘上 kind 与"按登记判据该叫什么"并列 ----
        # 历史行（写侧判据落地之前入库的文献定理）盘上写着 `conjecture`，物理改写
        # 等于让"当时交上去的那个名字"消失。所以读模型只现算一个并列值：`kind` 永远是
        # 盘上原值，`kind_projected` 由 `evidencebits.kind_projection` 给（它调的仍是
        # 写侧那唯一一处判据 `kind_at_registration`）。判据算不出来时两格都留着原值，
        # `kind_projection_checked=False` + basis 说明"这一问没判成"（三态，不折平）。
        try:
            projection = EB.kind_projection(row)
        except Exception:  # noqa: BLE001 - 投影算不出来 ⇒ 没判成（不猜一个更强的词）
            projection = {"checked": False, "kind": str(row.get("kind") or ""),
                          "changed": False, "basis": "",
                          "why": "读侧投影没算成（按盘上原值显示）"}
        got["kind_projected"] = str(projection.get("kind") or "")
        got["kind_projection_changed"] = bool(projection.get("changed"))
        got["kind_projection_checked"] = bool(projection.get("checked"))
        got["kind_projection_basis"] = str(projection.get("basis")
                                            or projection.get("why") or "")
        # ---- 现行性（业主 2026-11-20 ④）：active 是补集兜底名，页面不印「活跃」；
        # 非 active 那一档要带具体原因与所指编号（取代者 / 反例实验 / 放弃理由）。
        got.update(_currentness_reading(row, bits))
        # ---- 自产结果才有的两格：有没有稿 / 稿上有无 V 签（文献命题没有自产稿）。
        # 它们只在 origin=own_result 上行取值，其余行留空串（页面不摆那两列）。
        got.update(_own_result_readings(root, row))
        out.append(got)
    return out


def _superseded_ref(row: Mapping[str, Any]) -> str:
    """「被谁取代」那一个编号：行上有 `superseded_by` 就用它，否则读墓碑理由。

    `statements` 没有 `superseded_by` 这一列（那是判词表 ReviewFinding 的字段），
    台账里被老表墓碑同步过来的行把目标号写在 `quote_reason` 的「已并入 <号>」里
    （`conceptrows._apply_merge_tombstone` 的唯一写法）。两处都读不出就返回空串，
    调用方写「盘上没记被谁取代」，不编一个号。
    """
    direct = str(row.get("superseded_by") or "").strip()
    if direct:
        return direct
    got = _SUPERSEDED_REF.search(str(row.get("quote_reason") or ""))
    return got.group(1) if got else ""


#: 老表墓碑同步留下的那一句：「已并入 000123（同步自老表的 merged_into）」。
_SUPERSEDED_REF = re.compile(r"已并入\s*([0-9A-Za-z_-]+)")


def _refutation_word(bits: Mapping[str, Any] | None) -> str:
    """错误那一档的现行性词：已证否 + 它能指出的那个凭据（实验号 / 判词 / 证伪签）。

    凭什么读 `bits.voided_by` 而不是另找一处：作废载荷是 `evidencebits.void` 写的
    唯一落点（证据路三选一），本层只把它翻译成人话，不重判一次。
    """
    payload = dict(bits.get("voided_by") or {}) if isinstance(bits, Mapping) else {}
    kind = str(payload.get("kind") or "")
    if kind == "numeric_counterexample":
        exp = str(payload.get("experiment_id") or "").strip()
        return f"已证否（反例 实验 {exp}）" if exp else "已证否（反例没记实验号）"
    if kind == "refutation_sign":
        from .. import evidencebits as _EB

        got = _EB.refutation_reading(bits or {})
        sign = dict(got.get("sign") or {})
        if got.get("checked") and sign:
            return f"已证否（证伪签 {sign.get('ledger') or '（没记台账）'}）"
        return "已证否（证伪签读不出来）"
    if kind == "defect_ref":
        ref = str(payload.get("defect_ref") or "").strip()
        return f"已证否（判词 {ref}）" if ref else "已证否（判词凭据没记）"
    if kind == "construction":
        return "已证否（构造）"
    return "已证否（盘上没记凭什么）"


def _abandon_word(row: Mapping[str, Any]) -> str:
    """放弃那一档的现行性词：已放弃 + 标记里那条理由（结构化时取 `abandon_basis`）。"""
    from .. import statementabandon as _SA

    got = _SA.parse_abandon(row.get("quote_reason"))
    if not got.get("checked"):
        return "已放弃（理由读不出来）"
    reason = str(got.get("reason") or "")
    structured = _SA.parse_abandon_reason(row.get("quote_reason"))
    if structured.get("structured") and str(structured.get("abandon_basis") or ""):
        reason = str(structured.get("abandon_basis") or "")
    reason = " ".join(reason.split())
    if len(reason) > 80:
        reason = reason[:80] + "…"
    return f"已放弃（{reason}）" if reason else "已放弃（理由读不出来）"


def _currentness_reading(row: Mapping[str, Any],
                         bits: Mapping[str, Any] | None = None) -> dict[str, str]:
    """命题行的「现行性」呈现读数：`{current_state, current_word, current_detail}`。

    为什么要有这一格（业主 2026-11-20 ④ 逐字：「为什么命题台账上还有一栏说状态
    是否活跃？都登记上了什么叫活跃」）：`status=active` 是"没被取代、没被证否、
    没被放弃"的补集兜底名。十三行全是它时，那一列一个字的信息都没有。

    所以三态读数（`lifecycle.state_of_statement`，唯一入口）原样保留在
    `current_state` 里给计算用；页面上印的那一格（`current_word`）只对非 active
    行给词，active 行是空串（页面写 `—`）。三档结束各带它能指出的编号：

    - `completed`（被取代）：`已取代（被 <编号>）`；
    - `abandoned` 且 status 是错误那一档（`errorstate.ERROR_WORDS`）：
      `已证否（反例 <实验号>）` / `已证否（证伪签 …）` / `已证否（判词 …）`；
    - `abandoned` 其余：`已放弃（<理由>）`。

    `current_detail` 是 hover 那一句：原始 status + 它的中文词 + 三态。
    三态读数读不出来（status 不在词表里）⇒ 一句「判不了」，不折成活跃。
    """
    from .. import errorstate as _ES
    from .. import lifecycle as _LC

    out: dict[str, str] = {"current_state": "", "current_word": "", "current_detail": ""}
    got = _LC.state_of_statement(row)
    state = str(got.get("state") or "")
    raw = str(row.get("status") or "")
    word = STATEMENT_STATUS_WORDS.get(raw, raw)
    out["current_state"] = state
    if not got.get("checked"):
        out["current_word"] = f"判不了（status={raw or '（空）'} 不在词表里）"
        out["current_detail"] = str(got.get("why") or "")
        return out
    if state == _LC.ACTIVE:
        # active = 补集兜底名：页面写 `—`，不印「活跃」。
        out["current_detail"] = f"status={raw}（{word}）；三态=活跃：还在活跃集里"
        return out
    if state == _LC.COMPLETED:
        ref = _superseded_ref(row)
        out["current_word"] = (f"已取代（被 {ref}）" if ref
                               else "已取代（盘上没记被谁取代）")
        out["current_detail"] = f"status={raw}（{word}）；三态=完工（被后来的一条取代）"
        return out
    if raw in _ES.ERROR_WORDS:
        out["current_word"] = _refutation_word(bits)
        out["current_detail"] = f"status={raw}（{word}）；三态=放弃（错误那一档）"
        return out
    out["current_word"] = _abandon_word(row)
    out["current_detail"] = f"status={raw}（{word}）；三态=放弃"
    return out


def _manuscript_paths(row: Mapping[str, Any]) -> list[str]:
    """这一行记着的稿路径（只收看起来是工作区相对稿路径的那些值）。

    为什么不是"有字就算"：`manuscripts` / `line_range.label` 这一族格子在真机上
    也放引用（lp-ball-11 的 000006 写的是 `exp:000008` —— 一个实验引用，不是稿）。
    把引用当路径会印出「稿没落盘（exp:000008）」，那是把"没有稿"说成了"稿丢了"。
    所以只收同时满足三条的值：非空、不含冒号（引用前缀）、以 `.md` 结尾；工作区相对
    路径正是这三条。顺序按 `manuscripts` 的插入序，再补 `line_range.label`。
    """
    out: list[str] = []

    def _keep(raw: Any) -> None:
        rel = str(raw or "").strip().replace("\\", "/")
        if not rel or ":" in rel or not rel.endswith(".md"):
            return
        if rel not in out:
            out.append(rel)

    books = row.get("manuscripts")
    if isinstance(books, Mapping):
        for rel in books.values():
            _keep(rel)
    line = row.get("line_range")
    if isinstance(line, Mapping):
        _keep(line.get("label"))
    return out


def _own_result_readings(root: str | Path,
                         row: Mapping[str, Any]) -> dict[str, str]:
    """自产结果的两格：`{manuscript_state, manuscript_path, vsign_state, vsign_detail}`。

    读的是"有没有稿"与"稿上有无 V 签"这两件对自产命题才有意义的事：

    - 稿路径取 `statements.manuscripts` 的值（真机 `{"1": "reports/f-proof-<号>.md"}`），
      缺这一格再退回 `line_range.label`（老行把稿路径写在那里）；两者都没有 ⇒ `none`，
      有路径而盘上没有那份文件 ⇒ `missing`（"记了稿而稿丢了"与"没记稿"是两件事）；
    - V 签走 `vsigns.signed_manuscripts(statement_id=...)`（签台账是唯一权威；
      不重读稿里的签块 —— 两处读法会分家），三态：`signed` / `unsigned` / `unknown`。

    非自产行四格都是空串（页面不摆那两列）。每一行读一次签表；自产行在真机上
    是几十行量级，与同页 `nontriviality_of` 的逐行扫描同一条代价口径。
    """
    out: dict[str, str] = {"manuscript_state": "", "manuscript_path": "",
                           "vsign_state": "", "vsign_detail": ""}
    if str(row.get("origin") or "") != "own_result":
        return out
    root_p = Path(str(root))
    candidates = _manuscript_paths(row)
    existing = next((rel for rel in candidates if (root_p / rel).is_file()), "")
    if existing:
        out["manuscript_state"] = "found"
        out["manuscript_path"] = existing
    elif candidates:
        out["manuscript_state"] = "missing"
        out["manuscript_path"] = candidates[0]
    else:
        out["manuscript_state"] = "none"
    sid = str(row.get("stmt_id") or "")
    try:
        from .. import vsigns as _VS

        signed = _VS.signed_manuscripts(str(root_p), statement_id=sid)
    except Exception as exc:  # noqa: BLE001 - 签表读不出来 = 这一格没查成，不是「没签」
        out["vsign_state"] = "unknown"
        out["vsign_detail"] = f"{type(exc).__name__}: {exc}"
        return out
    if not signed.get("checked"):
        out["vsign_state"] = "unknown"
        out["vsign_detail"] = str(signed.get("why") or "签表没查成")
    elif signed.get("found"):
        out["vsign_state"] = "signed"
        latest = dict(signed.get("latest") or {})
        at = str(latest.get("at") or "")
        out["vsign_detail"] = (f"{int(signed.get('count') or 0)} 份签"
                               + (f"，最近 {at}" if at else ""))
    else:
        out["vsign_state"] = "unsigned"
    return out


def _quote_state_rows(rows: list[dict]) -> list[dict[str, Any]]:
    """关系行补 `quote_state`（引文五档：逐字 / 语义 / 不一致 / 未查 / 无复核区间）。

    与命题行同一个读口（`evidencebits.quote_state`）。为什么关系行也要这一格：
    页面上的「引文回验」那一卡按状态分档计数，只有布尔的话 `no_evidence` 那一档
    会被算进"未查"—— 而它欠的东西不同（欠一次重核，不是欠一次回验）。
    """
    from .. import evidencebits as EB

    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            out.append(row)
            continue
        got = dict(row)
        try:
            got["quote_state"] = EB.quote_state(row)
        except Exception:  # noqa: BLE001 - 读不出来 ⇒ 按"还没查"处置（不冒充通过）
            got["quote_state"] = "unchecked"
        out.append(got)
    return out


# ================================================================ 状态：三态 + 人话 + 原 token
# 证据面那几张表的 `status` 列一直是原始英文 token（`refuted` / `supported_not_proved`
# / `voided` / `needs_evidence` …）并排印在屏幕上，没有三态、也没有中文（WEBCAP B5）。
#
# 两条口径，只有这两条：
#   · 命题面的"它还占不占活跃集"只读 `lifecycle.state_of_statement`（唯一入口，
#     本文件不另写一份 `if status == ...`）⇒ `lifecycle_state` = active / completed /
#     abandoned（读不出来是空串 + `lifecycle_checked=False`）；
#   · 其余几张表没有 lifecycle 入口，就只译词（`status_word`），不编三态 ——
#     "译成人话"与"发明一个新状态机"是两件事，后者该由人裁定。
#
# 词表外的 token 原样印（不折成 unknown：读不出来与不认识是两件事）。

#: 命题的 lifecycle 三态词（`lifecycle.STATES` 的呈现面；页面印这个词，不印英文）。
LIFECYCLE_WORDS: dict[str, str] = {
    "active": "活跃",
    "completed": "完工",
    "abandoned": "放弃",
}

#: 命题原始 `status` 的中文（`schema.STATEMENT_STATUSES` 全覆盖；原文进 tooltip）。
STATEMENT_STATUS_WORDS: dict[str, str] = {
    "active": "活跃",
    "disputed": "争议中",
    "refuted": "已证否",
    "superseded": "已被取代",
    "pending_definition": "定义待补",
    "abandoned": "已放弃",
}

#: 猜想状态的中文（`schema.CONJECTURE_STATUSES` 全覆盖）。
CONJECTURE_STATUS_WORDS: dict[str, str] = {
    "proposed": "刚提出",
    "needs_evidence": "待证据",
    "testing": "检验中",
    "supported_not_proved": "有支持未证明",
    "refuted": "已否证",
    "proved": "已证明",
    "promoted": "已升格",
    "known_in_literature": "文献已知",
    "withdrawn": "已撤回",
}

#: 实验状态的中文（`schema.EXPERIMENT_STATUSES` 全覆盖）。
EXPERIMENT_STATUS_WORDS: dict[str, str] = {
    "active": "有效",
    "voided": "已作废",
}

#: 稿件状态的中文（`schema.DOC_STATUSES` 全覆盖）。
DOCUMENT_STATUS_WORDS: dict[str, str] = {
    "draft": "草稿",
    "in_review": "审校中",
    "revised": "已修订",
    "accepted": "已接收",
    "rejected": "已退回",
    "unresolved_review": "审校未决",
}

#: 审校发现状态的中文（`schema.FINDING_STATUSES` 全覆盖）。
FINDING_STATUS_WORDS: dict[str, str] = {
    "open": "未处理",
    "fixed": "已修",
    "wontfix": "不修",
    "disputed": "有争议",
    "superseded": "已被取代",
}

#: 表名 → 那一张状态词表（键集合必须等于 `schema` 里对应的 `*_STATUSES`；
#: 判据 `tests/test_webui_pages_show_the_words_the_backend_gives.py` 的
#: `test_the_status_words_cover_the_vocabulary_exactly` 逐个钉住）。
STATUS_WORDS: dict[str, dict[str, str]] = {
    "statements": STATEMENT_STATUS_WORDS,
    "conjectures": CONJECTURE_STATUS_WORDS,
    "experiments": EXPERIMENT_STATUS_WORDS,
    "documents": DOCUMENT_STATUS_WORDS,
    "review_findings": FINDING_STATUS_WORDS,
}


def _status_reading(table: str, row: Mapping[str, Any]) -> dict[str, Any]:
    """一行状态的呈现读数：`{status_word, lifecycle_state, lifecycle_checked}`。

    - `status_word`：给人读的那个词（词表见 :data:`STATUS_WORDS`；词表外的 token
      原样返回 —— 不认识不等于没读到）；
    - `lifecycle_state` / `lifecycle_checked`：只有命题面有（`lifecycle.state_of_statement`
      是唯一入口）；其余表分别是 `""` / `None`（"这张表没有三态入口"，不是"判成活跃"）。

    判据：`tests/test_webui_pages_show_the_words_the_backend_gives.py`
    （`test_the_status_words_cover_the_vocabulary_exactly` / `test_a_row_carries_its_word_and_only_the_statement_has_a_lifecycle_state`）。
    """
    raw = str(row.get("status") or "")
    word = (STATUS_WORDS.get(table) or {}).get(raw, raw)
    out: dict[str, Any] = {"status_word": word, "lifecycle_state": "",
                           "lifecycle_checked": None}
    if table != "statements":
        return out
    from .. import lifecycle as _LC

    got = _LC.state_of_statement(row)
    state = str(got.get("state") or "")
    out["lifecycle_state"] = state
    out["lifecycle_checked"] = bool(got.get("checked"))
    # 有 lifecycle 读数时，页面上印的那一格用三态词（命题的"结束"只有两种：完工 / 放弃）；
    # 读不出来时退回原始 token 的译名，并把 `lifecycle_checked=False` 一起给出去。
    if state in LIFECYCLE_WORDS:
        out["status_word"] = LIFECYCLE_WORDS[state]
    return out


def _status_readings(table: str, rows: list[dict]) -> list[dict[str, Any]]:
    """整张表逐行补状态呈现读数（非 Mapping 的行原样返回，不猜）。"""
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            out.append(row)
            continue
        got = dict(row)
        got.update(_status_reading(table, row))
        out.append(got)
    return out


def _verification_consistency(rows: list[dict],
                              statements: Mapping[str, Mapping[str, Any]]
                              ) -> list[dict[str, Any]]:
    """验证行补 `proof_sha_consistency`：V 签的那一份证明 vs 命题现在那一份。

    比的两边各自只有一个出处：签的那一份是这一行的 `proof_sha256`，现在那一份是
    `proofregistry.proof_sha(proof_text_of(命题行, 这个证明号))`。命题行不在读到的
    statements 里（被引用的外部命题 / 那一行还没落盘）⇒ `unknown`：没得比。

    为什么按这一行的 `proof_no` 取（那一行没记就按 canonical `#p1`）而不是按"最新一份"：
    多证明模型下每一条路径各签各的，拿错的路径去比会让另一条路径的改稿把这一条判成
    "不一致"。
    """
    from .. import verifications as VR

    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            out.append(row)
            continue
        got = dict(row)
        sid = str(row.get("statement_id") or row.get("stmt_id") or "")
        stmt = statements.get(sid)
        now = ""
        if stmt is not None:
            try:
                text = VR.proof_text_of(stmt, row.get("proof_no") or 1)
                now = _PR.proof_sha(text) if text else ""
            except Exception:  # noqa: BLE001 - 取不到现在的正文 ⇒ 没得比
                now = ""
        got["proof_sha_consistency"] = sha_consistency(row.get("proof_sha256"), now)
        out.append(got)
    return out


def _experiment_code_consistency(root: Path, rows: list[dict]) -> list[dict[str, Any]]:
    """实验行补五格：`code_sha_consistency`（代码一致，四档）、两个 sha 前缀与撤销理由，
    以及 `exhaustion_path` / `exhaustion_tri`（报告）。

    代码那一格比的是 `code_path` 指向的那个文件（相对工作区根）。四档语义与优先级
    见 :func:`code_consistency`：`match` / `revoked` / `mismatch` / `unknown`。
    「已撤销」不是红，而且它要能说清"从哪一份换到哪一份" ⇒ 同一行另给
    `code_sha_from` / `code_sha_to`（各 16 位，不印整串）与 `void_reason`（那句人话）。
    三种"没得比"都要落 `unknown` 而不是 `mismatch`：`code_path` 空、那一格 `code_hash`
    空、文件不在盘上/读不出来。
    超过 `_CODE_HASH_MAX_BYTES` 的脚本不读（有界：一个实验的脚本不该有几十兆，
    而一次请求把整盘大文件哈希一遍会把这一面拖成秒级）。

    报告那两格（业主：证据链的实验表没挂穷举论证报告）：
    `out/experiments/<号>/exhaustion.md` 是 ②③ 的唯一落点
    （`exhaustionreport.report_relpath` —— 落点的口径只有那一处，这里只转发）。
    - 盘上有 ⇒ `exhaustion_path` 是仓库相对的落点、`exhaustion_tri="computed"`；
    - 没有（实验号不成形，或报告还没落盘）⇒ `exhaustion_path=""`、
      `exhaustion_tri="not_applicable"`（页面写「无」，不是空白）；
    - 读不出来（权限 / 路径解析出错）⇒ `unreadable`（"没查成"不是"没有"）。
    """
    import hashlib

    from ..exhaustionreport import report_relpath

    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            out.append(row)
            continue
        got = dict(row)
        rel = str(row.get("code_path") or "").strip()
        want = str(row.get("code_hash") or "")
        now = ""
        if rel and want:
            path = Path(rel)
            if not path.is_absolute():
                path = root / path
            try:
                if path.is_file() and path.stat().st_size <= _CODE_HASH_MAX_BYTES:
                    now = hashlib.sha256(path.read_bytes()).hexdigest()
            except OSError:
                now = ""
        got["code_sha_consistency"] = code_consistency(row, now)
        # 撤销的那一行要把"从哪一份换到哪一份"印出来（两个 sha 前 16 位 + 那句话）。
        # 有效行这三格是空串：页面据此不印"已撤销"的细节（空串不是"没读到"）。
        got["code_sha_from"] = str(row.get("code_hash") or "").strip()[:16]
        got["code_sha_to"] = str(row.get("voided_code_to") or "").strip()[:16]
        got["void_reason"] = str(row.get("void_reason") or "")
        got["exhaustion_path"] = ""
        got["exhaustion_tri"] = TRI_NOT_APPLICABLE
        try:
            report = report_relpath(row.get("experiment_id"))
        except Exception:  # noqa: BLE001 - 落点算不出来 ⇒ 没得说（不是"没有报告"）
            report = ""
            got["exhaustion_tri"] = TRI_UNREADABLE
        if report:
            got["exhaustion_path"] = report
            try:
                if (root / report).is_file():
                    got["exhaustion_tri"] = TRI_COMPUTED
            except OSError:
                got["exhaustion_tri"] = TRI_UNREADABLE
        out.append(got)
    return out


#: 代码 sha 对照的规模上限（8 MiB）：超过它就不读，落 `unknown`（"没得比"，不是"不一致"）。
_CODE_HASH_MAX_BYTES = 8 * 1024 * 1024

#: 实验产物的落点（`agent_e` / `exhaustionreport` 写的那些目录与文件）。
_EXPERIMENT_SPOT_DIR = ("out", "experiments")
#: 原始输出日志的落点：一个实验号一份文件（`out/exp-logs/<号>.log`），不是每实验一个目录。
#:
#: 写点只有一处：`agent_e.run_experiment` 的 `log_rel = f"out/exp-logs/{eid}.log"`。
#: 2026-11-22 起读侧只认这一处 —— 旧口径 `out/experiments/<号>/*.log` 已经没有任何写点，
#: 继续去那里 glob 的后果是产物页那一格永远空着（夹具就是这种形态：盘上只有
#: `out/exp-logs/000000.log`），而"空着"与"这一趟还没写日志"在页面上分不开。
_EXPERIMENT_LOG_DIR = ("out", "exp-logs")
_CODE_EXP_DIR = ("code", "exp")
#: 一个实验号下要报的那几份（`.md` 是"读得懂的读法"；日志另算，见 `_EXPERIMENT_LOG_DIR`）。
_EXPERIMENT_SPOT_FILES: tuple[tuple[str, str], ...] = (
    ("exhaustion.md", "穷举论证（程序设计 / 穷举论证 / 运行环境三块；缺它拿不到 proof）"),
)


def experiment_spots(root: str | Path) -> dict[str, Any]:
    """实验产物的落点读数：`code/exp/` 与 `out/experiments/<号>/exhaustion.md`，
    外加原始输出日志 `out/exp-logs/<号>.log`。

    这一面是"产物页要补的那两处落点"（业主：产物那一栏略有过时）。
    它只报盘上真有什么，不编"应该有但还没写"的行：

    - `rows[]`：一个落点一行 —— `{kind, path, exists, bytes, tri}`；
      `kind` 是 `exhaustion` / `log` / `code`；
    - `code_exp[]`：`code/exp/` 下的脚本（相对路径 + 字节数）；
    - 三态：`out/experiments/` 与 `out/exp-logs/` 都还没落过 ⇒ `not_applicable` + 理由
      （合法初态），读不出来 ⇒ `unreadable`。不把"还没跑过实验"读成"实验产物是空的"。

    实验号取两处的并集：`out/experiments/<号>/` 的目录名与 `out/exp-logs/<号>.log`
    的号。只按目录走的话，日志搬走之后 `out/exp-logs/000000.log` 那一份永远不出现在产物页
    （真实形态：工作区里只有一个 `out/exp-logs/000000.log`）；只按日志走的话，有报告没日志
    的实验号会从那一栏消失。

    日志那一格恒占一行：那一份没落盘 ⇒ `exists=false`（页面写"不在"），而不是整行不
    出现 —— "没有日志"要说出口，不能让读的人从"没有这一行"里自己猜。

    规模是有界的：实验号按名字排序取前 `_EXPERIMENT_SPOT_MAX` 个，脚本同理；
    截断在 `truncated` 里说出口（静默截断等于让"只有这么多"与"被砍了"一样）。
    """
    root_p = Path(str(root))
    base = root_p.joinpath(*_EXPERIMENT_SPOT_DIR)
    logs_dir = root_p.joinpath(*_EXPERIMENT_LOG_DIR)
    code_dir = root_p.joinpath(*_CODE_EXP_DIR)
    out: dict[str, Any] = {"tri": TRI_NOT_APPLICABLE, "reason": "", "dir": str(base),
                           "rows": [], "code_exp": [], "truncated": False}
    rows: list[dict[str, Any]] = []
    problems: list[str] = []
    found: list[Path] = []
    if base.is_dir():
        try:
            found = sorted((p for p in base.iterdir() if p.is_dir()),
                           key=lambda p: p.name)
        except OSError as exc:
            problems.append(f"{base} 读不出来：{type(exc).__name__}: {exc}")
    log_ids: list[str] = []
    if logs_dir.is_dir():
        try:
            log_ids = sorted(p.stem for p in logs_dir.glob("*.log") if p.is_file())
        except OSError as exc:
            problems.append(f"{logs_dir} 读不出来：{type(exc).__name__}: {exc}")
    dir_ids = [one.name for one in found]
    ids = sorted(set(dir_ids) | set(log_ids))
    numbered = ids[:_EXPERIMENT_SPOT_MAX]
    for eid in numbered:
        if eid in dir_ids:
            for name, _why in _EXPERIMENT_SPOT_FILES:
                rows.append(_spot_row(base / eid / name, root_p, name.split(".")[0]))
        rows.append(_spot_row(logs_dir / f"{eid}.log", root_p, "log"))
    code_exp: list[dict[str, Any]] = []
    if code_dir.is_dir():
        try:
            files = sorted(p for p in code_dir.rglob("*") if p.is_file())
        except OSError as exc:
            problems.append(f"{code_dir} 读不出来：{type(exc).__name__}: {exc}")
            files = []
        for path in files[:_EXPERIMENT_SPOT_MAX]:
            got = _spot_row(path, root_p, "code")
            code_exp.append({"path": got["path"], "bytes": got["bytes"]})
    out["rows"] = rows
    out["code_exp"] = code_exp
    out["truncated"] = len(ids) > len(numbered) or (
        bool(code_dir.is_dir()) and len(code_exp) >= _EXPERIMENT_SPOT_MAX)
    if problems:
        out["tri"] = TRI_UNREADABLE
        out["reason"] = "；".join(problems)
    elif rows or code_exp:
        out["tri"] = TRI_COMPUTED
    else:
        out["reason"] = (f"{base} 与 {logs_dir} 都没有实验产物、{code_dir} 也没有脚本"
                         "（还没跑过实验；合法初态：这一趟没有实验产物，不是「读不出来」）")
    return out


#: 落点那一面的规模上限（实验号目录数与 `code/exp` 脚本数各一个）。
_EXPERIMENT_SPOT_MAX = 50


def _spot_row(path: Path, root: Path, kind: str) -> dict[str, Any]:
    """一个落点一行：`{kind, path, exists, bytes, tri}`。

    路径一律写成工作区相对、正斜杠分隔（`out/experiments/000001/design.md`）：
    这一格是给人看的、也会被贴着读，Windows 的反斜杠会把同一处落点在两处写法下
    印成两个样子。
    """
    rel = str(path)
    try:
        rel = path.resolve().relative_to(root.resolve()).as_posix()
    except (OSError, ValueError):  # noqa: BLE001 - 取不到相对路径就印绝对路径（读数不为空即可）
        pass
    if not path.is_file():
        return {"kind": kind, "path": rel, "exists": False, "bytes": None,
                "tri": TRI_NOT_APPLICABLE}
    try:
        size = path.stat().st_size
    except OSError as exc:
        return {"kind": kind, "path": rel, "exists": True, "bytes": None,
                "tri": TRI_UNREADABLE, "reason": f"{type(exc).__name__}: {exc}"}
    return {"kind": kind, "path": rel, "exists": True, "bytes": size,
            "tri": TRI_COMPUTED}


#: 首屏摘要默认每栏给多少行（`GET /api/evidence?summary=1` / `?artifacts` 同一条）。
#:
#: 为什么要有它（AUDIT F12：真机 56 MB 工作区上 `/api/evidence` 2.1 MB / 2.6 s、
#: `/api/artifacts` 1.3 MB / 2.0 s，一进页面就卡）：这两面是"全量行 + 逐行注解"的
#: 形状，行数随工作区线性涨。首屏只画得下几十行（前端本来就分页），把整本台账
#: 先塞进浏览器是纯浪费。所以 HTTP 那一层可以要"摘要"：「每栏前 N 行」，另把
#: 每栏的真实总行数留在 `rows_total` 里 —— 页面因此既快、又不会把"首屏只给了 N 行"
#: 读成"一共就 N 行"。
#:
#: 为什么是 20（实测，`temp/webfix3/after-ro.json`，真机 lp-ball-15 那份副本）：
#: `/api/evidence?limit=40` 是 586 KB、25 是 492 KB、20 是 457 KB、15 是 417 KB。
#: 首屏的目标是 「< 500 KB」，而 25 那一档已经贴线（盘再长一点就超），所以取 20。
#: 注意行数不是唯一成本：`experiments` 每行约 17 KB（9 行就 150 KB），而那几栏本来
#: 就不到 20 行 ⇒ 再往下压 N 也压不掉它们。真正的下一刀在"逐行注解扫会话"那一步
#: （冷调用约 3.6 s 几乎全在那里），不在这个 N 上 —— 写在这里，免得下一个人把
#: "时间没怎么变"当成这一改没生效。
#:
#: 缺省仍是全量（`limit=0`）：读模型自己的既有调用方（判据、CLI、`/api/package`）
#: 一个字节都不变 —— 分页是「调用方显式开口」才发生的事，不是偷偷收窄。
SUMMARY_ROWS = 20

#: `?limit=` 的上限（再多就不叫"首屏"了，而且它不该成为导出通道）。
PAGE_ROWS_MAX = 500


def page_columns(out: dict[str, Any], keys: Sequence[str], *,
                 limit: int = 0, offset: int = 0) -> None:
    """把 `out` 里那几栏行按 `(offset, limit)` 切一份，并把三格分页读数写回 `out`（就地）。

    三格是「恒在」的（`limit=0` 也写），这样页面不必猜"这一份读数是全量还是摘要"：

    - `rows_mode`：`"full"`（全量）/ `"page"`（切过）；
    - `rows_limit` / `rows_offset`：这一次用的窗口（全量档 `0 / 0`）；
    - `rows_total`：`{栏名: 这一栏「真实」有多少行}` —— 与 `len(out[栏])` 不是同一个数
      （切过之后后者是"这一页几行"）。"首屏只给了 40 行、一共 190 行"这件事必须
      有机器读数，否则页面只能把 40 当总数印上去。

    为什么用 `rows_total` 一个 Record 而不是每栏一个 `<栏>_total`：十几个新键会把
    `EvidenceView` / `ArtifactsView` 的键集合撑成一片噪声，而"哪一栏、共几行"本来
    就是一个映射。三态不动：切行只改「给多少行」，不改任何一栏的 `tri`。
    """
    total: dict[str, int] = {}
    for key in keys:
        rows = out.get(key)
        if not isinstance(rows, list):
            total[key] = 0
            continue
        total[key] = len(rows)
        if limit > 0:
            out[key] = rows[offset:offset + limit]
    out["rows_mode"] = "page" if limit > 0 else "full"
    out["rows_limit"] = int(limit)
    out["rows_offset"] = int(offset)
    out["rows_total"] = total


#: 字段档的两个取值（与 `rows_mode` 的 `full` / `page` 是两个独立的轴，别混）：
#: `full` = 读模型的全部字段；`compact` = 只给面板要用的列，长字段留给 `?full=1`。
ROWS_FIELDS_FULL = "full"
ROWS_FIELDS_COMPACT = "compact"

#: `compact` 档里长字段的缺省截断长度。截断不静默：行上另给
#: `<字段>_truncated=true` 与 `<字段>_chars=<原长>`，顶层 `rows_clipped` 点名是哪几栏。
#: 400 与 `Artifacts.tsx` / `state.CLIP` 的页面截断同一口径。
#: 任务 `detail` 的截断长度（比 400 更短：真机 84 行 × 400 仍是 34 KB，占默认响应
#: 的大头；页面那一列本来就只当一句话读）。`rows_clipped` 会点名它，`detail_chars`
#: 给原文长度 —— 不把"截了"读成"就这些"。
COMPACT_DETAIL_CHARS = 80

#: `/api/evidence` 的 compact 档逐栏保留哪些字段。
#:
#: 取舍口径只有一条：面板上真的有这一格（`Evidence.tsx` 的列 / tooltip /
#: `statementLedger.ts` 的取值器），或三态/归属读数（`*_tri` 在顶层，行上那几格
#: `by_role` / `by_task_id` 是「谁写的、哪一趟」）。其余一律进 `rows_omitted`，
#: 要读全文就 `?full=1` —— 那一条与 compact 是同一份读模型，不是第二套读法。
_EVIDENCE_COMPACT_FIELDS: dict[str, tuple[str, ...]] = {
    "statements": (
        "stmt_id", "origin", "kind", "kind_projected", "kind_projection_changed",
        "label", "statement_text", "statement_full", "proof_text", "source_lit_id",
        "page_range", "quote_verified", "quote_state", "status", "status_word",
        "lifecycle_checked", "created_at", "created_by", "nontriviality_label",
        "nontriviality_meaning", "nontriviality_tri", "nontriviality_word",
        "formal_paths", "bit_numeric", "bit_proof", "bit_reviewed", "bit_audited",
        "reviewed_paths", "optimized_paths", "grade", "grade_label", "current_word",
        "manuscript_state", "manuscript_path", "vsign_state", "vsign_detail",
        "by_role", "by_role_source", "by_task_id", "by_task_id_tri",
    ),
    "conjectures": (
        "conjecture_id", "status", "status_word", "form", "testable", "statement",
        "counterexample_experiment_id", "experiment_ids", "by_role", "by_task_id",
    ),
    "experiments": (
        "experiment_id", "status", "status_word", "method", "result",
        "evidence_kind", "negation_kind", "exit_code", "code_path",
        "code_sha_consistency", "exhaustion_path", "exhaustion_tri",
        "artifact_paths", "void_reason", "code_sha_from", "code_sha_to",
        "created_at", "runtime_sec", "owner_task",
        "by_role", "by_role_source", "by_task_id", "by_task_id_tri",
    ),
    "relations": (
        "relation_id", "lit_id", "quote", "statement", "quote_state",
        "quote_verified", "page_range", "status", "status_word",
        "by_role", "by_task_id",
    ),
    "documents": (
        "doc_id", "kind", "title", "status", "status_word", "review_rounds",
        "review_verdict", "revision", "updated_at", "created_at", "markdown_path",
        "content_sha256", "owner_task", "owner_instance", "created_by",
        "lifecycle_state", "lifecycle_checked",
        "by_role", "by_role_source", "by_task_id", "by_task_id_tri",
    ),
    "review_findings": (
        "finding_id", "doc_id", "kind", "level", "target", "evidence", "message",
        "round", "suggestion", "status", "resolution_note", "created_at",
        "status_word", "lifecycle_state", "lifecycle_checked", "created_by",
        "axis", "line", "verbatim_quote", "maths", "line_unavailable_reason",
        "by_role", "by_role_source", "by_task_id", "by_task_id_tri",
    ),
    "verifications": (
        "verification_id", "statement_id", "stmt_id", "verifier", "verdict",
        "defect_step", "quote", "unresolved_errors", "proof_chars", "round",
        "proof_sha_consistency", "manuscript", "path_group", "at", "landed",
        "producer_role", "producer_code", "findings", "citation_checks",
        "by_role", "by_role_source", "by_task_id", "by_task_id_tri",
    ),
    "secretary": (
        "role", "seq", "duty", "decision", "judge", "reason", "fail_open", "at",
    ),
}

#: `/api/artifacts` 的 compact 档逐栏保留哪些字段。口径同上：面板列 + 归属读数。
#: `ledger_verify` 只留页面那四列（路径 / 一致吗 / 结论 / 谁产出）—— sha 原文本来
#: 就不上屏（页面自己的说明写着），compact 档不再整段送两份 sha。
_ARTIFACTS_COMPACT_FIELDS: dict[str, tuple[str, ...]] = {
    "ledger": (
        "path", "producer", "kind", "kind_state", "kind_unknown", "sha_consistency",
        "bytes", "task_id", "at", "by_task_id", "by_task_id_tri",
    ),
    "ledger_verify": ("path", "producer", "status", "sha_consistency",
                      "by_task_id", "by_task_id_tri"),
    "handoffs": (
        "id", "sender", "sender_label", "to", "to_label", "summary", "refs", "sid",
        "task_id", "to_task_id", "format", "sha256", "body",
        "by_role", "by_role_source", "by_task_id", "by_task_id_tri",
    ),
    "checks": (
        "id", "kind", "kind_reading", "kind_deprecated", "name", "min", "max",
        "na", "got", "state", "ok", "note", "path", "exists", "lines", "tri",
        "by_role", "by_role_source", "by_task_id", "by_task_id_tri",
    ),
    "secretary": (
        "role", "seq", "duty", "decision", "judge", "reason", "fail_open", "at",
    ),
    "products": (
        "name", "path", "exists", "bytes", "lines", "sha256", "tri",
        "by_role", "by_role_source", "by_task_id", "by_task_id_tri",
    ),
    "experiment_spots": (
        "kind", "path", "exists", "bytes", "tri", "reason",
    ),
    "code_exp": ("path", "bytes"),
    "tasks": (
        "task_id", "role", "instance", "action", "called_by", "seen_step",
        "status", "status_reading", "outcome", "usd", "detail",
    ),
}

#: compact 档要截断的字段（不是删掉）：页面还画这一列，只是不必整段送来。
#: 截断标记与截断动作都在 `_project_compact_face` 一处做，免得两栏各写一份口径。
_EVIDENCE_CLIP_FIELDS: dict[str, tuple[tuple[str, int], ...]] = {
    "statements": (("statement_full", 160), ("proof_text", 160)),
}
_ARTIFACTS_CLIP_FIELDS: dict[str, tuple[tuple[str, int], ...]] = {
    "handoffs": (("body", 200),),
    "tasks": (("detail", COMPACT_DETAIL_CHARS),),
}

#: compact 档里做子对象投影的字段（顶层还在，里面只留页面真读的那几格）。
#: `judge` 在真机上一行最多几百字节（`checked` / `cost` / `decision` / `reason` …），
#: 页面只用 `checked` 与 `cost.usd`；全文在 `?full=1`。
_EVIDENCE_NESTED_FIELDS: dict[str, tuple[str, ...]] = {"secretary": ("judge",)}
_ARTIFACTS_NESTED_FIELDS: dict[str, tuple[str, ...]] = {"secretary": ("judge",)}


def _compact_judge(value: Any) -> Any:
    """`judge` 的 compact 形状：只留 `checked` 与 `cost.usd`（其余在 `?full=1`）。

    形状不是"另一个类型"：还是 `judge` 这个键，还是一个对象；只是里面少了页面
    从来不读的键。`cost` 不在时返回 `{}`（不是 `null`：`null` 在页面上有专门含义
    ——「这一行不经判据」）。
    """
    if not isinstance(value, Mapping):
        return value
    out: dict[str, Any] = {}
    if "checked" in value:
        out["checked"] = value.get("checked")
    cost = value.get("cost")
    if isinstance(cost, Mapping):
        out["cost"] = {"usd": cost.get("usd")} if "usd" in cost else {}
    return out


def _project_compact_face(
    out: dict[str, Any],
    fields: Mapping[str, Sequence[str]],
    *,
    clip_fields: Mapping[str, Sequence[tuple[str, int]]] | None = None,
    nested_fields: Mapping[str, Sequence[str]] | None = None,
) -> None:
    """把一份读模型就地投影成 compact 档，并把"少了什么 / 截了什么"写成机器读数。

    三样读数（都进响应顶层，页面与判据读它们，不用猜）：

    - `rows_fields`：`"full"` / `"compact"`；
    - `rows_omitted`：`{栏: [被省掉的字段名]}`（compact 档才有内容）；
    - `rows_clipped`：`{栏: [被截断的字段名]}`（行上另有 `<字段>_truncated` 与
      `<字段>_chars` 两格，所以"截了"不会被读成"原文就这么长"）；
    - `rows_nested`：`{栏: [做了子对象投影的字段名]}`（`judge` 那一格）。

    为什么在分页之后做：`rows_total` 由 `page_columns` 在切行之前算好，投影只
    改"这一页的每一行带哪些字段"，不改"一共多少行"。切行与切字段是两根独立的轴，
    两根都有机器读数（`rows_mode` / `rows_fields`），页面不会把一根读成另一根。
    """
    clip_fields = clip_fields or {}
    nested_fields = nested_fields or {}
    omitted: dict[str, list[str]] = {}
    clipped: dict[str, list[str]] = {}
    nested_hit: dict[str, list[str]] = {}
    for col, keep in fields.items():
        rows = out.get(col)
        if not isinstance(rows, list):
            continue
        keep_set = set(keep)
        clip_specs = dict(clip_fields.get(col) or ())
        nested_set = set(nested_fields.get(col) or ())
        omitted_keys: set[str] = set()
        clipped_keys: set[str] = set()
        nested_keys: set[str] = set()
        projected: list[Any] = []
        for row in rows:
            if not isinstance(row, Mapping):
                projected.append(row)
                continue
            new = {k: v for k, v in row.items() if k in keep_set}
            for name, limit in clip_specs.items():
                value = new.get(name)
                if isinstance(value, str) and len(value) > limit:
                    new[name] = (value[:limit]
                                 + f"…（截断：全文 {len(value)} 字符；`?full=1` 取全文）")
                    new[f"{name}_truncated"] = True
                    new[f"{name}_chars"] = len(value)
                    clipped_keys.add(name)
            for name in nested_set:
                if name in new:
                    new[name] = _compact_judge(new[name])
                    nested_keys.add(name)
            omitted_keys.update(k for k in row if k not in keep_set)
            projected.append(new)
        out[col] = projected
        if omitted_keys:
            omitted[col] = sorted(omitted_keys)
        if clipped_keys:
            clipped[col] = sorted(clipped_keys)
        if nested_keys:
            nested_hit[col] = sorted(nested_keys)
    out["rows_fields"] = ROWS_FIELDS_COMPACT
    out["rows_omitted"] = omitted
    out["rows_clipped"] = clipped
    out["rows_nested"] = nested_hit


def _mark_full_fields(out: dict[str, Any]) -> None:
    """`?full=1` 那一档的四格读数（键恒在，于是两档的顶层键集合一致）。"""
    out["rows_fields"] = ROWS_FIELDS_FULL
    out["rows_omitted"] = {}
    out["rows_clipped"] = {}
    out["rows_nested"] = {}


def evidence_chain(root: str | Path, store: Any = None, *,
                   limit: int = 0, offset: int = 0,
                   compact: bool = False) -> dict[str, Any]:
    """`GET /api/evidence` 的读模型：证据链八栏 + 三态。

    `statements` / `conjectures` / `experiments` / `documents` / `review_findings` /
    `relations` 逐行来自 `store.rows(...)`（不另写一份读法）；`verifications` 来自
    `verifications.list_verifications`（一命题一份 `verifications/<4 位>.jsonl`）；
    `secretary` 来自 `out/secretary/<角色>.jsonl`。

    三态：`store` 读不出来（未知表、坏 JSON、无权限）⇒ `unreadable` + `reason`；
    表是空文件 / 还没写过 ⇒ 对应栏 `[]` 而整面 `tri="computed"`（读到了，
    里面是 0 行 —— 这与"没读到"是两件事，前者不报 `unreadable`）。
    每一栏另有一个 `<栏>_tri`，于是"哪一栏没读成"不会被整面的一个词吞掉。

    ## 业主的三条显示口径多加的那几格

    行形状变了，判定一个字没改（这一层仍然只是搬运）：

    - 命题行：`quote_state`（引文五档，含 `no_evidence`）、`nontriviality` /
      `nontriviality_label` / `nontriviality_meaning` / `nontriviality_tri` /
      `nontriviality_word`（非平凡度：判不了是 `None` + 空 label，页面写"未判"，
      不是 T0；概念 / 定义行是 `tri="not_applicable"`，页面写"不适用"）、
      `formal_paths`（第 4 位逐路径：`[{proof_no, state}]`）、
      `grade` / `grade_label`（五元位派生的等级）；
    - 关系行：`quote_state`（同一个读口，引文那一卡按五档计数）；
    - 实验行：`code_sha_consistency`（台账钉的代码 sha vs 盘上现在这一份脚本；
      四档 `match` / `revoked` / `mismatch` / `unknown`）＋ 撤销那一档的
      `code_sha_from` / `code_sha_to` / `void_reason`（业主：改脚本要重新登记并
      撤销老登记 —— 「已撤销」不是红，要能说出从哪一份换到哪一份）；
    - 验证行：`proof_sha_consistency`（V 签的那一份 vs 命题现在那一份，
      按 `proof_no` 逐条比）。

    ## 字段档（`compact`）：默认读模型给全字段，HTTP 默认给 compact

    `compact=True` 是给页面的那一档：每栏只留 `Evidence.tsx` 真的会画的列与归属
    读数，`statement_full` / `proof_text` 按 `_EVIDENCE_CLIP_FIELDS` 的逐栏上限截断，
    `quote_reason` / `_quote_check` / `_conflict_check` / `bits` / `proof_history`
    等长字段整格省掉。省了哪些、截了哪些写在 `rows_omitted` / `rows_clipped` /
    `rows_nested` 三格；`?full=1` 走的是同一条读模型（`compact=False`），
    字段一个不少。

    缺省 `compact=False`：命令行、`/api/package`、契约判据 C 与既有调用方读的
    还是全字段读模型 —— 分页与投影都只是「调用方显式开口」才发生的事。
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
    # ---- 业主的三条显示口径：引文五档 / 非平凡度 / 第 4 位逐路径。
    # 顺序有讲究：命题行先补，验证行才能拿它比"V 签的那一份 vs 现在这一份"。
    out["statements"] = _statement_readings(root_p, out.get("statements") or [])
    out["relations"] = _quote_state_rows(out.get("relations") or [])
    out["experiments"] = _experiment_code_consistency(root_p,
                                                      out.get("experiments") or [])
    # ---- 状态列：三态（只有命题面有 lifecycle 入口）+ 人话 + 原文留 tooltip。
    # 放在最后：它只加三格呈现读数，不改上面任何一格的判定。
    for _table, _key, _src in _EVIDENCE_TABLES:
        out[_key] = _status_readings(_table, out.get(_key) or [])
    # 索引的构造只有一处（查口 `index_by_id`）：非 Mapping / 没号的行由它跳过。
    by_sid = SL.index_by_id(out["statements"])
    out["verifications"] = _verification_consistency(out.get("verifications") or [],
                                                     by_sid)
    if problems:
        out["tri"] = TRI_UNREADABLE
    elif len(absent) == len(_EVIDENCE_TABLES):
        out["tri"] = TRI_NOT_APPLICABLE
        out["reason"] = ("这几张表一张都没落过盘（" + "、".join(absent)
                         + "）—— 合法初态：这个工作区还没有证据链")
    else:
        out["tri"] = TRI_COMPUTED
    out["reason"] = "；".join(problems) if problems else str(out["reason"] or "")
    # 分页在「最后」：三格读数（`rows_mode` / `rows_limit` / `rows_offset` / `rows_total`）
    # 恒在，而各栏的 `tri`、注解、三态判定一个都不动 —— 切行只改"给多少行"。
    # `store_problems` 不切：它是坏行说明（几行到几十行），切了会让"哪几行坏了"缺页。
    page_columns(out, _EVIDENCE_PAGE_COLUMNS, limit=limit, offset=offset)
    # 字段档在分页之后（`rows_total` 已按切行前的真实行数记好；投影只改这一页的字段）。
    if compact:
        _project_compact_face(out, _EVIDENCE_COMPACT_FIELDS,
                              clip_fields=_EVIDENCE_CLIP_FIELDS,
                              nested_fields=_EVIDENCE_NESTED_FIELDS)
    else:
        _mark_full_fields(out)
    return out


#: 证据面会被 `?limit=` / `?offset=` 切的那几栏（行级；`store_problems` 不在其中）。
_EVIDENCE_PAGE_COLUMNS: tuple[str, ...] = (
    "statements", "conjectures", "experiments", "documents", "review_findings",
    "relations", "verifications", "secretary",
)


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

    三态：`out/` 下没有一个 `run-N/` ⇒ 整面 `not_applicable` + 理由明说"这一档是
    `start` 流水线、没有 `run-N/` 目录"（它不断言"本机跑没跑过"：真机 lp-ball-22
    正在跑，走的是 `start` 不走 `run`；把"没有目录"说成"机器没跑过"是两句不同的事实），
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
        return None, ("out/ 不在盘上 —— 六件产物只落在 `run` / `project run` 的 "
                      "`out/run-N/` 里；这一档没有它（与「本机跑没跑过」是两件事）")
    numbered: list[tuple[int, Path]] = []
    for p in out.iterdir():
        if not p.is_dir() or not p.name.startswith("run-"):
            continue
        tail = p.name[4:]
        if tail.isdigit():
            numbered.append((int(tail), p))
    if not numbered:
        return None, ("out/ 下没有一个 `run-N/` 目录 —— 这一档是 `start` 流水线"
                      "（不走 `run` / `project run`），六件产物不在这一档；"
                      "要看产物见「台账 / 交接 / out/package」那几栏")
    return max(numbered)[1], ""


def _acceptance_checks(root: Path, project_dir: str = "") -> dict[str, Any]:
    """验收表的读数（路径的唯一来源是 `closing.ACCEPTANCE_TARGETS_NAME`）。

    2026-11-22 那一趟把这一份从 `out/paper/` 挪到了 `out/package/` —— 所以这里
    不写死路径：`path` 原样回给调用方（页面印它，而不是自己再抄一份字面量）。
    它接受两种形状：顶层数组，或 `{"checks": [...]}`（`closing._check_acceptance`
    两种都认，这里照同一条口径读）。真机读数：8 行 C1–C8，键 `id/kind/min/name/note`。
    """
    from ..closing import (ACCEPTANCE_TARGETS_NAME, HANDOFF_LEG_DEPRECATED,
                           canonical_leg_kind)

    base = Path(project_dir) if project_dir else root
    if project_dir and not base.is_absolute():
        base = root / project_dir
    path = base / ACCEPTANCE_TARGETS_NAME
    data, state, why = _read_json_file(path)
    if state in ("absent", "empty"):
        return {"tri": TRI_NOT_APPLICABLE, "reason": f"验收表还没写：{path}",
                "path": str(path), "checks": []}
    if state == "unreadable":
        return {"tri": TRI_UNREADABLE, "reason": f"验收表读不出来：{why}",
                "path": str(path), "checks": []}
    if isinstance(data, list):
        rows = data
    elif isinstance(data, dict) and isinstance(data.get("checks"), list):
        rows = data["checks"]
    else:
        return {"tri": TRI_UNREADABLE,
                "reason": f"验收表的形状不认识：顶层是 {type(data).__name__}"
                          "（只认数组或 {checks: [...]}）",
                "path": str(path), "checks": []}
    # ---- 读数键的正名（B3，2026-11-22）----------------------------------------
    # 盘上那一格 `kind` 是写表的人当时写下的名字（可能是旧名 `manuscript_rows`）——
    # 它原样留着（盘是历史，读侧不改写）。另起一格 `kind_reading` 给「读数正名」：
    # 交接手稿那一档是 `handoff_rows`，其余档与 `kind` 逐字相同。旧名那一行另带
    # `kind_deprecated = "use handoff_rows"`，页面显示正名、把旧名放 title 里。
    # 名字映射只有一处真身（`closing.LEG_KIND_RENAMES`），这里不另写一份字面量。
    checks: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        one = dict(row)
        declared = str(one.get("kind") or "")
        canonical = canonical_leg_kind(declared)
        one["kind_reading"] = canonical
        if canonical != declared:
            one["kind_deprecated"] = HANDOFF_LEG_DEPRECATED
        checks.append(one)
    return {"tri": TRI_COMPUTED, "reason": "", "path": str(path), "checks": checks}


def _report_style(root: Path, project_dir: str = "") -> dict[str, Any]:
    """报告体例声明（`<报告目录>/REPORT-STYLE.json`）的读数：`{tri, reason, sections}`。

    落点只认 `closing.REPORT_STYLE_NAME`（门读体例时用的就是这一份，含目录）：
    页面再抄一份字面量，迁移当天就会读空而说"M 没声明体例"。
    """
    from ..closing import REPORT_STYLE_NAME

    base = Path(project_dir) if project_dir else root
    if project_dir and not base.is_absolute():
        base = root / project_dir
    path = base / str(REPORT_STYLE_NAME)
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


# ============================================ 4.4 交接手稿的「发 / 收」怎么显示
# 业主逐字：「交接手稿『发 / 收』两栏只显示角色名（M / ALL / A），要显示绝对编码」。
# 真机读数（`projects/mp3-r3/manuscripts/handoffs.jsonl`）：14 个行键里发信人的编号
# 就在 `task_id`（发信人的台账号），收件人的编号落在写侧补的 `to_task_id` /
# `to_task_ids` 两格（见 `manuscripts.write`）。
#
# 于是读侧只做展示，三档不许折平（折平之后"没有编号"会变成"有一个看起来像编号的东西"，
# 而那个东西是猜的）：
#
# | 盘上有什么 | 页面写什么 |
# |---|---|
# | `to_task_id`（具体收件人） | `A（t-000002）` |
# | `to_task_ids` 非空（`to=ALL`） | `ALL（t-000002、t-000003）` |
# | `to_task_ids` 是空列表 | `ALL（广播；无直接子代理）` |
# | 两格都没有（旧账落的那一批） | `A（旧账无号）` / `ALL（广播；旧账无编号）` |
#
# 为什么角色名与编号各留一格（`sender` / `to` 一个字都不改写）：那两格是台账的键
# （`handoff_query(to=…)` / `manuscripts.read` 的过滤都按它们），把它们改写成
# `A（t-000002）` 就等于把台账的口径搞脏；渲染另起两格，页面读那两格。
#: 这一行没记下编号时写的那句（旧账那批行都在这一档：不假装有，也不报错）。
HANDOFF_NO_CODE_WORD = "旧账无号"
#: 广播行没记下编号时写的那句（与"具体收件人没有编号"分开：它同时还说了"这是广播"）。
HANDOFF_NO_BROADCAST_WORD = "广播；旧账无编号"
#: 广播行记下了编号、但发信人此刻一个直接子代理都没有（写了空列表也是结论，照实说）。
HANDOFF_EMPTY_BROADCAST_WORD = "广播；无直接子代理"
#: 广播面那个收件人写法 —— 唯一来源是 `manuscripts.ALL`，这里只读它，不另写一份字面量。
HANDOFF_BROADCAST = _MS.ALL


def handoff_sender_label(row: Mapping[str, Any]) -> str:
    """发件人那一格：`M（t-000001）`（发信人的台账号就在 `task_id` 那一格）。

    为什么"发"这一栏也要编号：只印 `sender` 读起来像角色级的公告；而台账里
    `task_id` 一直有值 —— 缺的只是把它摆到同一格里。
    """
    who = str(row.get("sender") or "")
    code = str(row.get("task_id") or "").strip()
    return f"{who}（{code or HANDOFF_NO_CODE_WORD}）"


def handoff_to_label(row: Mapping[str, Any]) -> str:
    """收件人那一格：具体收件人 `A（t-000002）`；`ALL` 按它自己的记法（编号列表）。

    判据是"收件人是不是广播"（`to == ALL`，写法只有一个来源
    :data:`HANDOFF_BROADCAST`）：具体收件人的编号在 `to_task_id`（字符串），
    广播面的编号列表在 `to_task_ids`（列表）—— 两种形状不混用，混了之后
    "一个实例"与"一批实例"就读不开了。
    """
    who = str(row.get("to") or "")
    if who.upper() == HANDOFF_BROADCAST:
        if "to_task_ids" not in row:
            return f"{who}（{HANDOFF_NO_BROADCAST_WORD}）"
        codes = [str(x) for x in (row.get("to_task_ids") or []) if str(x).strip()]
        return f"{who}（{'、'.join(codes) if codes else HANDOFF_EMPTY_BROADCAST_WORD}）"
    code = str(row.get("to_task_id") or "").strip() if "to_task_id" in row else ""
    return f"{who}（{code or HANDOFF_NO_CODE_WORD}）"


def _handoff_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """交接行补两格给人看的「发 / 收」，并把两个编号格归一成"永远给得出"的形状。

    为什么要归一：声明面（`HandoffRow`）里那两格是必填的，而盘上它们是"有就带上"
    （旧行两格都没有）。归一成 `""` / `[]` 之后，"没有编号"这件事仍然由
    :func:`handoff_sender_label` / :func:`handoff_to_label` 说清 —— 它们按盘上的原样
    算，所以"那一格在不在"这条三态在渲染里没有丢。
    """
    out: list[dict[str, Any]] = []
    for row in rows:
        one = dict(row)
        one["sender_label"] = handoff_sender_label(one)
        one["to_label"] = handoff_to_label(one)
        one.setdefault("to_task_id", "")
        one.setdefault("to_task_ids", [])
        out.append(one)
    return out


def _kind_state_reading(rows: Sequence[Any], out: dict[str, Any]) -> list[str]:
    """产物台账逐行的类别三态计数：`artifacts_face` 里"类别三态"那一块的装配。

    判据只有一处真身：`artifacts.kind_state`（取值不在 `ARTIFACT_KINDS` 里、
    且这一行有没有 `kind_unknown` 这一格 ⇒ canonical / legacy / unknown）。
    本层只做计数，不另写一份判定：`legacy`（词表生效前的老行，照读）与
    `unknown`（词表生效后新写、行上带受控标记）在页面上必须分得开 ——
    把两者折成"有个类别没见过"会让"历史宽容"与"今天写错了"长得一模一样。
    `kind_flag_mismatch` 是标记与取值不一致（写了 `kind_unknown=false` 却不在词表里）：
    读法不变，但写侧那一笔标记算错了，要有人看见。

    注意：逐行状态必须在 `_annotate_ledger_rows` 补格之前算完并存下来 ——
    `_annotate_ledger_rows` 会按 `artifacts.FIELDS` 给老行补上缺失的格（含
    `kind_unknown: ""`；本文件已把这一格从补格清单里摘掉，见
    `_annotate_ledger_row`）。补完再调 `kind_state`，老行就会被读成 `unknown`
    （它凭"这一行有没有这一格"判 `legacy` / `unknown`）。那一补是为了契约 C 的
    键集合，不该改写历史行的语义。

    三格计数写进 `out`（`kind_states` / `unknown_kinds` / `kind_flag_mismatch`），
    返回逐行的 `kind_state_of`（与 `rows` 按行序一一对应；非对象的行占一位空串
    —— 少一位就会让后面每一行都错位一格），供后面 `ledger` 的 `kind_state`
    那一格取用。
    """
    # `artifacts` 在调用期才导入：与 `artifacts_face` 原来的函数内导入同一个
    # 时相（判据要能整格替换 `artifacts.kind_state` 做反真空，不能提前绑死）。
    from ..artifacts import KIND_STATES, kind_state

    out["kind_states"] = {state: 0 for state in KIND_STATES}
    out["unknown_kinds"] = {}
    out["kind_flag_mismatch"] = 0
    kind_state_of: list[str] = []
    for row in rows:
        if not isinstance(row, Mapping):
            # 非对象的行（形状不认识）不参与三态，但要占一位：下面按行序取状态，
            # 少一位就会让后面每一行都错位一格。
            kind_state_of.append("")
            continue
        state = kind_state(row)
        kind_state_of.append(state)
        out["kind_states"][state] = int(out["kind_states"].get(state) or 0) + 1
        if state != "canonical":
            odd = str(row.get("kind") or "")
            out["unknown_kinds"][odd] = int(out["unknown_kinds"].get(odd) or 0) + 1
        if state == "unknown" and row.get("kind_unknown") is not True:
            out["kind_flag_mismatch"] = int(out["kind_flag_mismatch"]) + 1
    return kind_state_of


def _carry_task_attribution(
    ledger_rows: Sequence[Mapping[str, Any]],
    verify_rows: Sequence[Mapping[str, Any]],
) -> list[Any]:
    """把台账行那一格 `by_task_id` / `by_task_id_tri` 搬到同一行的对账行上。

    `verify_entries` 的行形状里没有 `task_id`；旧读法两栏各自按路径反查，于是两栏
    一起落在 `missing`。归属只该有一个来源：台账行自己的那一格（`row` / `event` /
    `not_recorded`），对账行照抄。

    按下标对齐优先（`verify_entries(root, rows)` 就是逐行返回的）；同路径可能有多条
    台账行（真机：同一份手稿被登记两次），按路径建映射会把两行的归属折成一格。
    只有长度对不上时才退回路径映射。
    """
    if len(verify_rows) == len(ledger_rows):
        paired: list[Any] = []
        for lrow, vrow in zip(ledger_rows, verify_rows):
            if isinstance(lrow, Mapping) and isinstance(vrow, Mapping):
                paired.append({**dict(vrow),
                               "by_task_id": str(lrow.get("by_task_id") or ""),
                               "by_task_id_tri": str(lrow.get("by_task_id_tri") or "")})
            else:
                paired.append(vrow)
        return paired
    task_by_path: dict[str, tuple[str, str]] = {}
    for row in ledger_rows:
        if isinstance(row, Mapping):
            task_by_path[str(row.get("path") or "")] = (
                str(row.get("by_task_id") or ""), str(row.get("by_task_id_tri") or ""))
    return [
        ({**dict(row),
          "by_task_id": task_by_path.get(str(row.get("path") or ""), ("", ""))[0] or
                        str(row.get("by_task_id") or ""),
          "by_task_id_tri": task_by_path.get(str(row.get("path") or ""), ("", ""))[1] or
                            str(row.get("by_task_id_tri") or "")})
        if isinstance(row, Mapping) else row
        for row in verify_rows]


def artifacts_face(root: str | Path, store: Any = None, *,
                   run_dir: str | Path | None = None,
                   project_dir: str = "",
                   limit: int = 0, offset: int = 0,
                   compact: bool = False) -> dict[str, Any]:
    """`GET /api/artifacts` 的读模型：台账 + 交接 + 验收行 + 体例 + 秘书 + 六件产物 + 任务。

    - `ledger`：`artifacts.read_ledger`（行键 = `artifacts.FIELDS`：`at/path/sha256/bytes/`
      `producer/kind/task_id/exit_code/note/instance/identity_conflict/family`，老行缺的
      三格在这里补空串）；另给 `ledger_verify`（`artifacts.verify_entries`，
      逐行"盘上现在的 sha 与台账里记的一样吗"）；
    - `handoffs`：`manuscripts.read_rows`（行键见 `tests/conftest.py` 的夹具），另补
      `sender_label` / `to_label` 两个给人看的格子（`A（t-000002）` 那种形态，见
      :func:`handoff_to_label`）—— 角色名与编号各占一格，谁也不覆盖谁；
    - `checks` / `style`：验收表（路径的单一口径是 `closing.ACCEPTANCE_TARGETS_NAME`，
      今天 = `out/package/ACCEPTANCE-TARGETS.json`；本面另给一格 `checks_path`）与
      体例声明（单一口径是 `closing.REPORT_STYLE_NAME`，今天 = `out/report/REPORT-STYLE.json`）；
    - `secretary`：`out/secretary/*.jsonl`；
    - `products`：六件产物（见 :func:`run_products`）；
    - `tasks`：`store.rows("tasks")`。

    三态是逐栏的（`ledger_tri` / `handoffs_tri` / ...）：一整面里有一栏读不出来时，
    整面 `unreadable` 并把这些栏点名，而读得出来的那些栏照常给行 —— 少给一栏会让
    "这一栏没读成"变成"这一栏是空的"，那两者在界面上必须分得开。

    ## sha 原文不显示，只显示一致不一致
    两栏台账各多一格 `sha_consistency`（`match` / `mismatch` / `unknown`）：
    `ledger_verify` 那一格由 `artifacts.STATUSES` 的五档折过来，`ledger` 那一格取
    同一路径的核对行的读数（没有对应核对行 ⇒ `unknown`：没得比）。
    另外补了实验产物的落点两栏：`experiment_spots`（`out/experiments/<号>/exhaustion.md`
    与 `out/exp-logs/<号>.log` —— 日志与报告从 2026-11-22 起不在同一个父目录下）
    与 `code_exp`（`code/exp/` 下的脚本）。
    sha 原文仍然留在数据里（`sha256` / `sha256_now` 一个字没动）—— 改的只是渲染。

    ## 字段档（`compact`）：与 `/api/evidence` 同一套

    `compact=True` 按 `Artifacts.tsx` 真的会画的列投影：`handoffs.body` 与
    `tasks.detail` 按 `_ARTIFACTS_CLIP_FIELDS` 的逐栏上限截断，`ledger_verify` 的两份 sha 与
    行级归属读数省掉（页面只画路径 / 一致吗 / 结论 / 谁产出），`secretary` 那一栏
    页面根本不画、只留最基本的几格。省了哪些、截了哪些写在 `rows_omitted` /
    `rows_clipped` / `rows_nested`；`?full=1` 走同一条读模型（`compact=False`），
    字段一个不少。

    缺省 `compact=False`：契约判据 C、`/api/package` 与既有调用方读的仍是全字段
    读模型。
    """
    from .. import manuscripts as MS
    from ..artifacts import kind_state, read_ledger, verify_entries
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
    # ---- 类别三态（B2d，2026-11-22）：`kind` 在词表里 ⇔ `canonical`。
    # 判定与计数都在 `_kind_state_reading`（判据真身仍是 `artifacts.kind_state`）；
    # 逐行状态必须在 `_annotate_ledger_rows` 补格之前算完，所以在这里取一次。
    kind_state_of = _kind_state_reading(rows, out)
    # ---- 交接手稿
    try:
        got_ms, ms_bad = MS.read_rows(root_p)
        out["handoffs"] = _handoff_rows(got_ms)
        ms_path = MS.handoffs_path(root_p)
        ms_state = "ok" if got_ms else ("absent" if not Path(ms_path).is_file()
                                        else "empty")
        ms_face = _face(got_ms, ms_state, "；".join(ms_bad),
                        what="交接台账 work/handoffs.jsonl")
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
    # 验收表在盘上的位置（唯一来源 `closing.ACCEPTANCE_TARGETS_NAME`）：页面印这一格，
    # 不自己抄一份字面量 —— 那一份 2026-11-22 刚从 `out/paper/` 挪到 `out/package/`。
    # 印工作区相对路径：绝对路径在页面上既长又不可读，而"哪一份"由文件名与子目录说清。
    _checks_abs = Path(str(checks.get("path") or ""))
    try:
        out["checks_path"] = _checks_abs.resolve().relative_to(
            root_p.resolve()).as_posix()
    except (ValueError, OSError):
        out["checks_path"] = str(checks.get("path") or "")
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
    # 对账行取台账行那一格（同一行在两栏里必须是同一种归属）。拆在
    # `_carry_task_attribution` 里：这一面已经到 200 行软基线，搬移不改行为。
    out["ledger_verify"] = _carry_task_attribution(
        out.get("ledger") or [], out.get("ledger_verify") or [])
    # ---- sha 原文不显示，只显示一致不一致：
    # 台账行的一致性取自同一路径的核对行（`verify_entries` 已经把两份 sha 读出来了），
    # 核对行自己的一致性由 `sha_consistency` 真比一次（见 `_ledger_verify_consistency`）。
    out["ledger_verify"] = [
        {**dict(r), "sha_consistency": _ledger_verify_consistency(r)}
        if isinstance(r, Mapping) else r for r in out.get("ledger_verify") or []]
    consistency_by_path = {str(r.get("path") or ""): str(r.get("sha_consistency") or SHA_UNKNOWN)
                           for r in out["ledger_verify"] if isinstance(r, Mapping)}
    out["ledger"] = [
        {**dict(r), "sha_consistency": consistency_by_path.get(
            str(r.get("path") or ""), SHA_UNKNOWN),
         # 用上面「补格之前」算好的状态（见类别三态那一段）。
         "kind_state": (kind_state_of[i] if i < len(kind_state_of) else kind_state(r))}
        if isinstance(r, Mapping) else r for i, r in enumerate(out.get("ledger") or [])]
    # ---- 板项行的"状态"按 `item_state`/`item_close` 投影。
    # 与状态报告同一个函数（`statusreport.tasks_row_reading`）：`tasks` 表里板项行的
    # `status` 恒为 `pending`（`conductor._item_row` 建行写死），于是网页「任务产物」
    # 那一栏把 71 条 `item_state=done` 的 notice 全印成 pending —— 与 `.md` 报告是
    # 同一个错。新增一格而不是改写 `status`：盘上那一格确实是 `pending`，把 API 里的
    # `status` 换成投影值等于让读数与盘对不上（三态纪律的反面），而且那会动
    # `tasks.status` 的语义 —— 那是业主明令不动的边界。
    out["tasks"] = [
        {**dict(r), "status_reading": _SRP.tasks_row_reading(r)}
        if isinstance(r, Mapping) else r
        for r in (out.get("tasks") or [])]
    # ---- 实验产物的落点（产物页补的那两处：`code/exp/` 与 `out/experiments/<号>/`，
    #      日志另在 `out/exp-logs/<号>.log` —— 由 `experiment_spots` 一处读）。
    spots = experiment_spots(root_p)
    out["experiment_spots"] = spots["rows"]
    out["experiment_spots_tri"] = spots["tri"]
    out["experiment_spots_reason"] = spots["reason"]
    out["code_exp"] = spots["code_exp"]
    if spots["tri"] == TRI_UNREADABLE:
        problems.append(f"实验产物落点：{spots['reason']}")
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
    # 分页同 `evidence_chain`：三格分页读数恒在，行级的 `tri` 与一致性判定不动。
    # 注意切行发生在「一致性 join 之后」（`ledger` 的 `sha_consistency` 取自同一份
    # `ledger_verify`，两份都按同一个窗口切，逐行对得上）。
    page_columns(out, _ARTIFACTS_PAGE_COLUMNS, limit=limit, offset=offset)
    if compact:
        _project_compact_face(out, _ARTIFACTS_COMPACT_FIELDS,
                              clip_fields=_ARTIFACTS_CLIP_FIELDS,
                              nested_fields=_ARTIFACTS_NESTED_FIELDS)
    else:
        _mark_full_fields(out)
    return out


#: 产物面会被 `?limit=` / `?offset=` 切的那几栏（行级）。`style` 是对象、`run_dir`
#: 是一格路径，都不是行，不切。
_ARTIFACTS_PAGE_COLUMNS: tuple[str, ...] = (
    "ledger", "ledger_verify", "handoffs", "checks", "secretary", "products",
    "experiment_spots", "code_exp", "tasks",
)


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

    ## 「在成本上限内」是收工门的入参，不是预算寄存器（2026-11-24）

    这一格的上限由调用方给（`agentflow closing --cap-usd` / 网页「成本上限」格）。
    `/api/budget` 的 `spent_usd` / `total_usd` 是预算闸（可随时追加），不是这份交付
    契约里的成本上限 —— 拿它顶上去会把"没给上限"读成"没超上限"（把没查成折成通过）。
    所以没给上限时这一格仍是 `unknown`，但 `details.within_cost_cap` 与 `cap_note`
    把"为什么算不出来、去哪给"写清（改前只有一句"没给成本上限"，读的人会以为是在说
    预算页那两个数）。

    ## `failed` 只装"真不过"，"没查成"单列（2026-11-20，WEBCLEAN）

    上游 `reviewaccept.check_review` 的 `acc.failed` 把 `unknown` 与 `fail` 混装在同一
    个清单里（它的 docstring 说的是"没过的那些"）。同一个工作区、同一组入参，
    `/api/package` 的 `closing.content` 一直是 `failed=1 / unchecked=2`，而这一条端点
    给出 `failed=3` —— 两个出口对"几条真不过"说两句话。口径的真身在
    `_closing_block` 的 `content` 那一段（`failed = v=="fail"` / `unchecked = v=="unknown"`），
    这里改成逐格判 `criteria` 的同一条算式：不再透传 `acc.failed`。

    判据：`tests/test_webui_acceptance_failed_is_not_unchecked.py`。

    ## 报告路径的缺省（2026-11-22）

    不给 `report_path` 时取「项目根 / `cli.DEFAULT_REPORT_REL`」，与 `agentflow closing`
    同一份缺省。改前这里把空串原样传下去 ⇒ `attachment_is_honest` 永远是 `unknown`
    （"没查成"），页面把它显示成一条不过的读数。
    """
    from ..closing import resolve_under_workspace
    from ..reviewaccept import AUXILIARY_SIGNALS, CRITERIA, check_review
    from ..store import Store

    root_p = Path(str(root))
    if store is None:
        store = Store(root_p)
    project_root = resolve_under_workspace(store, project_dir)
    report = report_path or (str(Path(project_root) / _report_rel()) if project_root else "")
    try:
        acc = check_review(store, project_dir=project_dir, report_path=report,
                           session_root=root_p, cost_cap_usd=cap_usd, sid=sid)
    except Exception as exc:  # noqa: BLE001 - 读数层：读不到就如实说没查成
        return {"tri": TRI_UNREADABLE, "reason": f"reviewaccept.check_review 读不出来："
                                                f"{type(exc).__name__}: {exc}",
                "criteria": {}, "auxiliary": {}, "details": {}, "failed": [],
                "unchecked": [],
                "rows": _acceptance_rows({}, {}),
                "note": ("`failed` 是真不过，`unchecked` 是没查成 —— 两档不许折平"
                         "（与 `/api/package` 的 `closing.content` 同一算式）"),
                "auxiliary_note": "",
                "cap_usd": cap_usd, "cap_note": ""}
    criteria = {str(k): str((acc.criteria or {}).get(k, "unknown")) for k, _d in CRITERIA}
    details = {str(k): str((acc.details or {}).get(k, "")) for k, _d in CRITERIA}
    aux = {str(k): _as_text((acc.auxiliary or {}).get(k)) for k, _d in AUXILIARY_SIGNALS}
    unresolved = sorted(k for k, v in criteria.items() if v == "unknown")
    # `failed` 只装"判过了、不过"；"没查成"单列 —— 与 `_closing_block` 的 `content`
    # 同一算式（`v=="fail"` / `v=="unknown"`）。上游 `acc.failed` 把两档混装，
    # 透传它会让同参数下这里报 3 条、收工面报 1 fail + 2 unchecked。
    failed = sorted(k for k, v in criteria.items() if v == "fail")
    unchecked = sorted(k for k, v in criteria.items() if v == "unknown")
    if cap_usd is None:
        cap_note = ("这一格是收工门的入参：只有调用方给了 `--cap-usd`（网页「成本上限」格 / "
                    "`agentflow closing --cap-usd`）才算。`/api/budget` 的 spent/total 是"
                    "预算闸（可随时追加），不是这份交付的成本上限 —— 不拿它顶，所以这里"
                    "记「没查成」，不是「通过」。")
        details["within_cost_cap"] = (
            "没给成本上限（收工门入参 `--cap-usd` / 网页「成本上限」格没填）⇒ 这一条"
            "没查成（不是通过）；预算页的 spent/total 不是这一格的判据")
    else:
        cap_note = (f"成本上限取调用方给的 {float(cap_usd):.6f}（收工门入参 / 网页那一格），"
                    "不是预算寄存器里的 `total_usd`。")
    return {"tri": TRI_COMPUTED,
            "reason": ("这些格子没查成（不是通过）：" + "、".join(unresolved)
                       if unresolved else ""),
            "criteria": criteria, "details": details, "auxiliary": aux,
            # 逐条行（每一行带"谁 / 哪一趟"那三格，这一面的三格恒为"编号不适用"）
            "rows": _acceptance_rows(criteria, details),
            "failed": failed, "unchecked": unchecked,
            "note": ("`failed` 是真不过，`unchecked` 是没查成 —— 两档不许折平"
                     "（与 `/api/package` 的 `closing.content` 同一算式）"),
            "auxiliary_note": str(
                (acc.to_dict() or {}).get("auxiliary_note", "")),
            # 成本上限那两格：`cap_usd` 是调用方给的值（没给就是 null），`cap_note` 说清
            # 这一格的上限从哪来、以及为什么预算页那两个数不能顶它。
            "cap_usd": cap_usd, "cap_note": cap_note}


# ====================================================================== 7 论文包三块
# 三块回答三个问题（A 证明完整吗 / B 结构合规吗 / C 能不能收工）。它们共用一次
# `GET /api/package`：这一页三块总是一起看，一次请求才有同一份快照；分成三个端点
# 会让"已签 0 条"与"八格 pass"来自两个瞬间。
#
# 三块各自带 `tri` + `reason`：读不到写"没查成"，不写 0。每一行带 `source`
# （path / line / match），网页用 `/api/source` 点开原文。

#: 一块最多返回多少行（`counts` 仍是盘上真总数）。
PACKAGE_ROWS_MAX = 200

#: `/api/source` 一次最多回多少行 / 多少字节（26MB 的会话不许整份吐出去）。
SOURCE_LINES_MAX = 200
SOURCE_BYTES_MAX = 64 * 1024

#: `/api/source` 只认这些后缀（文本；PDF / 图片 / 可执行文件一律不认）。
SOURCE_SUFFIXES: tuple[str, ...] = (
    ".tex", ".md", ".json", ".jsonl", ".txt", ".bib", ".yaml", ".yml",
    ".cfg", ".ini", ".toml", ".py", ".log", ".csv",
)


def _now_iso() -> str:
    """本机时区的 ISO 时刻（读数头那一格；与 `state._now_iso` 同一口径）。"""
    import datetime as _dt

    return _dt.datetime.now().astimezone().replace(microsecond=0).isoformat()


def _checks_rel() -> str:
    """验收表的工作区相对路径（唯一来源 `closing.ACCEPTANCE_TARGETS_NAME`）。

    2026-11-22 这一份从 `out/paper/` 挪到了 `out/package/` —— 页面上的"原文"链
    （`/api/source`）若抄一份字面量，就会在改名那一天指向一个不存在的路径，
    链在、原文点不开。所以出处一律现取。
    """
    from ..closing import ACCEPTANCE_TARGETS_NAME

    return str(ACCEPTANCE_TARGETS_NAME)


def _report_rel() -> str:
    """交付说明的工作区相对路径（唯一来源 `cli.DEFAULT_REPORT_REL`）。

    2026-11-22（`draft/197` §十四 ①）：写侧已按新教法写到 `out/report/REPORT.md`，
    而网页这一层此前自算了一份 `report_path or "out/review/REPORT.md"` ⇒
    `/api/package` 的 `report_shape` 读退役目录、说"报告没写"。这里现取，
    不在页面上另算一份缺省：`cli` 那一份是出口的判据，反真空也打在它身上
    （`tests/test_webui_paths_migration.py` 把常量改回旧值 ⇒ 判据必红）。
    """
    from ..cli import DEFAULT_REPORT_REL

    return str(DEFAULT_REPORT_REL)


def _report_dir_rel() -> str:
    """报告目录的工作区相对路径（唯一来源 `review_tools.DEFAULT_REPORT_SUBDIR`）。

    状态报告与体例声明都写在"报告目录"里，而那个目录的真身是 `statusreport` /
    `review_tools` 的写侧常量；`_report_rel()` 是那一份文件（缺省由 `cli` 给）。
    两处同源、不许各写一个字面量（判据里有一条把两边对账）。
    """
    from ..tools.review_tools import DEFAULT_REPORT_SUBDIR

    return str(DEFAULT_REPORT_SUBDIR)


def _paper_rel(name: str = "") -> str:
    """论文包里一个文件的工作区相对路径（目录唯一来源 `papercompile.PACKAGE_REL`）。

    2026-11-22 这一份从 `out/paper/` 挪到了 `out/package/`。链接与"原文出处"
    若各抄一份字面量，迁移当天就会指向不存在的路径（`/api/source` 点不开）——
    与 `_checks_rel` 同一条口径：出处一律现取。
    """
    from .. import papercompile as _PC

    parts = [*_PC.PACKAGE_REL, *([name] if name else [])]
    return "/".join(str(part) for part in parts)


def _m_verdict_rel() -> str:
    """M 判据的工作区相对路径（唯一来源 `closing.M_VERDICT_FILE`）。"""
    from ..closing import M_VERDICT_FILE

    return "/".join(str(part) for part in M_VERDICT_FILE)


def _src(path: Any, *, line: Any = 0, match: str = "", label: str = "") -> dict[str, Any]:
    """一格读数的原文出处（`/api/source` 的三个入参 + 一个给人看的标签）。"""
    return {"path": str(path or ""), "line": int(line or 0),
            "match": str(match or ""), "label": str(label or "")}


def _seconds_between(first: str, last: str) -> float | None:
    """两个 ISO 时刻之间几秒（读不出来 ⇒ `None`，不编一个 0）。"""
    if not first or not last:
        return None
    import datetime as _dt

    try:
        a = _dt.datetime.fromisoformat(first)
        b = _dt.datetime.fromisoformat(last)
    except ValueError:
        return None
    try:
        return max(0.0, round((b - a).total_seconds(), 1))
    except TypeError:  # 一个带时区、一个不带 ⇒ 判不了
        return None


def _paper_facts(project: str) -> dict[str, Any]:
    """论文包的体量与编译回执（B 块的一行背景 + `pdf_pages` 降级后的落点）。

    落点只认 `papercompile.package_dir()`（`<项目根>/out/package`）：
    2026-11-22 起旧布局 `out/paper/` 退役，这里不再读它、也不静默退回 ——
    新落点没有正文时 `reason` 逐字写「旧布局不再支持」，而不是一句空的
    "没有论文包"（`tests/test_webui_paths_migration.py` 的 b 钉这一句）。
    """
    from .. import papercompile as PC

    pkg = PC.package_dir(project)
    tex = pkg / PC.TEX_NAME
    tex_rel = _paper_rel(PC.TEX_NAME)
    pkg_rel = _paper_rel()
    env_names = ("theorem", "lemma", "proposition", "corollary")
    empty = {"tex_path": tex_rel, "exists": False,
             "lines": None, "sections": None, "subsections": None,
             "env_counts": {name: 0 for name in env_names}, "proof_envs": None,
             "pdf_pages": None, "pdf_exists": False, "compile_receipt": False,
             "receipt_verdict": "unknown", "reason": ""}
    if not tex.is_file():
        empty["reason"] = (f"{tex_rel} 不在盘上 ⇒ 还没有可查的正文"
                           f"（合法初态，不是 0 行）；旧布局不再支持：论文包要写到 {pkg_rel}/")
        return empty
    try:
        text = tex.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        empty["reason"] = f"{tex_rel} 读不出来（{type(exc).__name__}: {exc}）"
        return empty
    pages: int | None = None
    pdf = pkg / PC.PDF_NAME
    if pdf.is_file():
        try:
            from ..extract import page_count

            pages = int(page_count(pdf))
        except Exception:  # noqa: BLE001 —— 页数是读数，读不到就 None
            pages = None
    matched, why = PC.receipt_matches_tex(str(project))
    verdict = ("consistent" if matched is True else
               ("drifted" if matched is False else "unknown"))
    # 行数与 `/api/source` 的 `total` 同口径（物理行；末尾换行不再多算一行）。
    return {"tex_path": tex_rel, "exists": True,
            "lines": text.count("\n") + (0 if text.endswith("\n") else 1),
            "sections": text.count("\\section{"),
            "subsections": text.count("\\subsection{"),
            "env_counts": {name: text.count("\\begin{%s}" % name) for name in env_names},
            "proof_envs": text.count("\\begin{proof}"),
            "pdf_pages": pages, "pdf_exists": pdf.is_file(),
            "compile_receipt": (pkg / PC.RECEIPT_NAME).is_file(),
            "receipt_verdict": verdict,
            "reason": "" if matched is not None else why}


def _structure_block(root_p: Path, project: str) -> dict[str, Any]:
    """B 块：正文结构（`texaudit.scan_tex` 七类 + 论文包体量）。

    正文的落点由 `papercompile.PACKAGE_REL` 现取（见 `_paper_rel`）：这一块里的
    `source` 是 `/api/source` 的入参，抄一份字面量就会在落点迁移后点不开原文。
    """
    from .. import papercompile as _PC
    from .. import papermapping as _PM
    from .. import texaudit as TEX

    paper = _paper_facts(project)
    tex_rel = _paper_rel(_PC.TEX_NAME)
    empty_ledger = {"statement_envs": None, "proof_envs": None, "statement_ledger_rows": None,
                    "ledger_propositions": None, "ledger_theorem_kinds": None,
                    "ledger_theorem_kinds_projected": None,
                    "mapping_rows": None, "statement_surplus": [], "mapping_state": ""}
    empty_checks = {kind: {"checked": False, "reason": "还没扫", "findings": 0, "counts": {}}
                    for kind in TEX.SCAN_KINDS}
    if not paper["exists"]:
        return {"tri": TRI_NOT_APPLICABLE,
                "reason": f"{tex_rel} 不在盘上 ⇒ 结构那一块还没有可查的正文（旧布局不再支持）",
                "source": _src(tex_rel),
                "paper": paper, "checks": empty_checks, "ledger": empty_ledger,
                "findings": []}
    try:
        from ..tools import review_tools as RT

        raw = [rel for rel in (tex_rel, _paper_rel(_PM.APPENDIX_FILE_NAME))
               if (root_p / rel).is_file()]
        scan = TEX.scan_tex(root_p, kinds=list(TEX.SCAN_KINDS), project=project,
                            raw_paths=raw, text_integrity=RT.scan_text_integrity)
    except Exception as exc:  # noqa: BLE001 —— 扫描抛了 ⇒ 这一块没查成
        return {"tri": TRI_UNREADABLE,
                "reason": f"texaudit.scan_tex 没跑成（{type(exc).__name__}: {exc}）",
                "source": _src(tex_rel),
                "paper": paper, "checks": empty_checks, "ledger": empty_ledger,
                "findings": []}
    facts = dict((scan.get("counts") or {}).get("facts") or {})
    by_kind = dict((scan.get("counts") or {}).get("by_kind") or {})
    detail = {str(d.get("kind")): d for d in (scan.get("detail") or [])}
    checks: dict[str, dict[str, Any]] = {}
    for kind in TEX.SCAN_KINDS:
        d = detail.get(kind) or {}
        counts: dict[str, int] = {}
        if kind == "text_integrity":
            counts = {name: int(facts.get(name) or 0)
                      for name in ("cjk", "control", "zero_width",
                                   "replacement", "bidi", "nbsp")}
        checks[kind] = {"checked": bool(d.get("checked")),
                        "reason": str(d.get("reason") or ""),
                        "findings": int(by_kind.get(kind) or 0), "counts": counts}
    findings = [{"kind": str(f.get("kind") or ""),
                 "severity": str(f.get("severity") or ""),
                 "file": str(f.get("file") or ""),
                 "line": int(f.get("line") or 0),
                 "ref": str(f.get("ref") or ""),
                 "why": str(f.get("why") or ""),
                 "text": str(f.get("text") or ""),
                 "source": _src(f.get("file") or "", line=f.get("line") or 0,
                                label=str(f.get("ref") or ""))}
                for f in (scan.get("findings") or [])][:PACKAGE_ROWS_MAX]
    ledger = {"statement_envs": facts.get("statement_envs"),
              "proof_envs": facts.get("proof_envs"),
              "statement_ledger_rows": facts.get("statement_ledger_rows"),
              "ledger_propositions": facts.get("ledger_propositions"),
              "ledger_theorem_kinds": facts.get("ledger_theorem_kinds"),
              # 读侧投影之后的定理类条数（KINDREAD）：与上面那一格并列，
              # 原值仍是盘上 `kind` 数出来的（两个数不同 = 历史行还没改）。
              "ledger_theorem_kinds_projected": facts.get("ledger_theorem_kinds_projected"),
              "mapping_rows": facts.get("mapping_rows"),
              "statement_surplus": list(facts.get("statement_surplus") or []),
              "mapping_state": str(facts.get("mapping_state") or "")}
    return {"tri": TRI_COMPUTED if scan.get("checked") else TRI_UNREADABLE,
            "reason": "" if scan.get("checked") else str(scan.get("reason") or "正文扫描没查成"),
            "source": _src(tex_rel),
            "paper": paper, "checks": checks, "ledger": ledger, "findings": findings}


def _empty_proofs(reason: str) -> dict[str, Any]:
    return {"tri": TRI_UNREADABLE, "reason": reason,
            "source": _src(_checks_rel()),
            "paper_theorem_envs": None, "propositions_with_proof": None,
            "ledger_theorem_kinds": None, "ledger_theorem_kinds_projected": None,
            "signed": None,
            "coverage_note": "分母读不到 ⇒ 不给比例（0 不是「没有」）。",
            "review_states": {}, "rows": [],
            "vsign": {"tri": TRI_UNREADABLE, "reason": reason, "files": 0,
                      "recomputable": None,
                      "signed": [], "backed": [], "without_sign": [], "orphan_signs": [],
                      # RECONFIX2：逐份 `sign_reading.state` 的分布，以及
                      # `sign_does_not_back_the_row` 的份数（整块没查成 ⇒ None）。
                      "sign_states": {}, "sign_does_not_back_row": None,
                      # 整块没查成时"台账在不在"是 `None`（不知道），不是 `False`（不在）。
                      "ledger_present": None,
                      "ledger_path": "out/vsigns/issued.json",
                      "note": ("「签了几份」只认复算通过的 `<sha>.json`（`recomputable`）；"
                               "`signed` 是第 3 位为真的命题，`without_sign` 是其中盘上补不出"
                               "侧文件的那几条（子集，不是另一个签数）；`issued.json` 是索引。"),
                      "source": _src("out/vsigns/", label="签文件（逐份 <sha>.json）")},
            "receipt": {"checked": False, "reason": reason, "receipts": 0,
                        "statements": 0, "delivered": 0, "dispatched": 0,
                        "not_dispatched": 0, "undelivered": 0, "undelivered_ids": [],
                        "steps": {}, "submitter_is_not_author": 0,
                        "author_not_recorded": 0,
                        "source": _src("verifications/", label="回执")},
            "c3": {"id": "C3", "name": "", "got": None, "min": None, "ok": False,
                   "detail": "", "source": _src(_checks_rel())}}


def _proofs_block(root_p: Path, store: Any, rep: Any,
                  structure: Mapping[str, Any]) -> dict[str, Any]:
    """A 块：每条 statement 的 review state / streak / defect_step + V 签覆盖率 + 回执。"""
    from .. import verifications as VR
    from .. import vsigns as VSP

    ledger = dict(structure.get("ledger") or {})
    try:
        rows = list(store.rows("statements"))
    except Exception as exc:  # noqa: BLE001
        return _empty_proofs(f"statements 台账读不出来（{type(exc).__name__}: {exc}）")
    states = {str(s): 0 for s in VR.REVIEW_STATES}
    proof_rows: list[dict[str, Any]] = []
    with_proof = 0
    for r in rows:
        if str(r.get("kind") or "") == "concept":
            continue
        if not str(r.get("proof_text") or "").strip():
            continue
        with_proof += 1
        sid = str(r.get("stmt_id") or r.get("statement_id") or "")
        try:
            got = VR.statement_review_reading(root_p, r)
        except Exception as exc:  # noqa: BLE001 —— 这一条没查成，不影响别的行
            got = {"state": "unreadable", "proofs": [], "reviewed": False,
                   "grade": "", "why": f"{type(exc).__name__}: {exc}"}
        state = str(got.get("state") or "unreadable")
        states[state] = int(states.get(state, 0)) + 1
        items = []
        for p in (got.get("proofs") or []):
            no = int(p.get("proof_no") or 1)
            vid = str(p.get("verification_id") or "")
            items.append({
                "proof_no": no, "state": str(p.get("state") or ""),
                "streak": int(p.get("streak") or 0), "need": int(p.get("need") or 0),
                "streak_ok": bool(p.get("streak_ok")),
                "grade": str(p.get("grade") or ""), "verification_id": vid,
                "defect_steps": [],  # 下面用回执台账补（同一批签，不在两处各判一遍）
                "source": _src(f"verifications/{sid}.jsonl",
                               match=vid or sid, label=f"{sid}#p{no}"),
            })
        proof_rows.append({
            "stmt_id": sid, "label": str(r.get("label") or ""),
            "kind": str(r.get("kind") or ""), "status": str(r.get("status") or ""),
            "state": state, "grade": str(got.get("grade") or ""),
            "reviewed": bool(got.get("reviewed")), "proofs": items,
            "source": _src("data/statements.json", match=f'"stmt_id": "{sid}"',
                           label=sid),
        })
    try:
        receipt = VSP.receipt_digest(root_p, store, limit=PACKAGE_ROWS_MAX, times=False)
    except Exception as exc:  # noqa: BLE001
        receipt = {"checked": False, "reason": f"回执台账没查成（{type(exc).__name__}: {exc}）",
                   "receipts": 0, "statements": 0, "delivered": 0, "dispatched": 0,
                   "not_dispatched": 0, "undelivered": 0, "undelivered_ids": [],
                   "steps": {}, "submitter_is_not_author": 0, "author_not_recorded": 0}
    defect_by_label = {str(r.get("label") or ""): list(r.get("defect_steps") or [])
                       for r in (receipt.get("rows") or [])}
    for row in proof_rows:
        for p in row["proofs"]:
            label = f"{row['stmt_id']}#p{int(p.get('proof_no') or 1)}"
            p["defect_steps"] = [int(x) for x in
                                 defect_by_label.get(label, [])]
    try:
        backed = VSP.backed_reading(root_p, rows, store=store)
    except Exception as exc:  # noqa: BLE001
        backed = {"checked": False, "tri": TRI_UNREADABLE,
                  "reason": f"签的侧文件没查成（{type(exc).__name__}: {exc}）",
                  "signed": [], "backed": [], "without_sign": [], "orphan_signs": []}
    sign_dir = VSP.signs_dir(root_p)
    files = 0
    if sign_dir.is_dir():
        files = len([p for p in sign_dir.glob("*.json") if p.name != "issued.json"])
    creds = VSP.credentials_reading(root_p)
    recomputable = creds.get("recomputable") if creds.get("checked") else None
    c3 = {"id": "C3", "name": "", "got": None, "min": None, "ok": False,
          "detail": "", "source": _src(_checks_rel())}
    readings = getattr(rep, "readings", {}) or {}
    # ---- 逐份签读数（RECONFIX2，2026-11-22）：`sign_does_not_back_the_row` 的落点
    #
    # 这一档只在 `vsigns.sign_reading` 里判（签真、地址真，但这一行结构上不可能持有
    # 这份正文 —— 概念行 + 非 `b-proof` 稿），页面不能自己再判一遍。唯一带它的
    # 现成读数是收工报告里的同一份 `statements_unsigned`（`closing` 逐份读过
    # `sign_reading`，把 `state` 原样留在每份 `proofs[].state` 上）—— 这里只计数
    # 那个受控词，不重跑判定：
    #   · 它不进 `signed`（哪怕凭据复算通过）—— 页面上必须与"签过"分开；
    #   · 也不折进 `unbacked`（那一档凭据自己复算不上）—— 两档的病因不同；
    #   · `checked=false` ⇒ `None`（没查成），绝不折成 0。
    _su = dict(readings.get("statements_unsigned") or {})
    _sign_states: dict[str, int] = {}
    for _one in (_su.get("rows") or []):
        for _p in (_one.get("proofs") or []):
            _st = str(_p.get("state") or "")
            if _st:
                _sign_states[_st] = int(_sign_states.get(_st) or 0) + 1
    _does_not_back = (int(_sign_states.get("sign_does_not_back_the_row") or 0)
                      if bool(_su.get("checked")) else None)
    for row in ((readings.get("acceptance") or {}).get("rows") or []):
        if str(row.get("id") or "") != "C3":
            continue
        c3.update({"name": str(row.get("name") or ""),
                   "got": row.get("got"), "min": row.get("min"),
                   "ok": bool(row.get("ok")),
                   "detail": str(row.get("detail") or "")[:400]})
        break
    signed = states.get("signed", 0)
    envs = ledger.get("statement_envs")
    note = ("正文定理类环境 / 有证明的命题 / 台账定理类三个分母并列："
            "签覆盖率不合成一个比例（分母不同，合成会撒谎）。")
    # ---- 签的读数只认 `<sha>.json`（2026-11-20，WEBCLEAN）
    # 上一版这一块的 `source.path` 指向 `out/vsigns/issued.json` —— 那是派生台账
    # （索引），`vsigns.INDEX_NAME` 的 docstring 逐字说"谁都不许拿它下结论，也不参与
    # 『签了几份』"。而同一块里 `signed`（第 3 位为真，含历史签）与 `without_sign`
    # （其中盘上没有侧文件的那些）并排印，读者读成两个互相打架的签数。
    # 这一版把三件事分开放：
    #   · `recomputable` = 复算通过的签文件份数 —— 唯一的"签了几份"口径；
    #   · `signed` / `backed` / `without_sign` = 第 3 位为真的命题（含历史签），
    #     `without_sign` 是 `signed` 的子集（"签过、但盘上补不出侧文件"），不是另一个签数；
    #   · `ledger_present` / `ledger_path` = 台账在不在（索引，不是签）。
    ledger_path = "out/vsigns/issued.json"
    vsign = {"tri": str(backed.get("tri") or TRI_UNREADABLE),
             "reason": str(backed.get("reason") or ""), "files": files,
             "recomputable": recomputable,
             "signed": list(backed.get("signed") or []),
             "backed": list(backed.get("backed") or []),
             "without_sign": list(backed.get("without_sign") or []),
             "orphan_signs": list(backed.get("orphan_signs") or []),
             "ledger_present": (root_p / "out" / "vsigns" / "issued.json").is_file(),
             "ledger_path": ledger_path,
             "sign_states": _sign_states,
             "sign_does_not_back_row": _does_not_back,
             "note": ("「签了几份」只认复算通过的 `<sha>.json`（`recomputable`）；"
                      "`signed` 是第 3 位为真的命题（含历史签 / 直调写的签），"
                      "`without_sign` 是其中盘上补不出侧文件的那几条 —— 它是 `signed` 的"
                      "子集，不是另一个签数；`issued.json` 是索引，不是签。"
                      "另：proofs.signed 是 review 状态为 signed 的命题数（阅签台账口径），"
                      "与这里的 `signed`（第 3 位）是两个读数，不许互相顶替。"
                      "`sign_does_not_back_row` = 受控读数 `sign_does_not_back_the_row`"
                      "（签真、地址真，但这一行不持有这份正文）的份数：它不算签，"
                      "也不折进 `unbacked`；`null` = 那一格没查成，不是 0。"),
             "source": _src(_newest_sign_file(root_p) or "out/vsigns/",
                            label="签文件（逐份 <sha>.json）")}
    return {"tri": TRI_COMPUTED, "reason": "",
            "source": _src(_checks_rel(), label="C3"),
            "paper_theorem_envs": envs, "propositions_with_proof": with_proof,
            "ledger_theorem_kinds": ledger.get("ledger_theorem_kinds"),
            "ledger_theorem_kinds_projected": ledger.get("ledger_theorem_kinds_projected"),
            "signed": signed, "coverage_note": note,
            "review_states": states, "rows": proof_rows[:PACKAGE_ROWS_MAX],
            "vsign": vsign,
            "receipt": {"checked": bool(receipt.get("checked")),
                        "source": _src(_newest_file(root_p, "verifications")
                                       or "verifications/", label="回执"),
                        "reason": str(receipt.get("reason") or ""),
                        "receipts": int(receipt.get("receipts") or 0),
                        "statements": int(receipt.get("statements") or 0),
                        "delivered": int(receipt.get("delivered") or 0),
                        "dispatched": int(receipt.get("dispatched") or 0),
                        "not_dispatched": int(receipt.get("not_dispatched") or 0),
                        "undelivered": int(receipt.get("undelivered") or 0),
                        "undelivered_ids": list(receipt.get("undelivered_ids") or []),
                        "steps": dict(receipt.get("steps") or {}),
                        "submitter_is_not_author": int(receipt.get("submitter_is_not_author") or 0),
                        "author_not_recorded": int(receipt.get("author_not_recorded") or 0)},
            "c3": c3}


def _newest_file(root_p: Path, rel: str, pattern: str = "*.jsonl") -> str:
    """目录里最新的一个文件（工作区相对路径；没有 ⇒ 空串，调用方退回目录名）。

    `/api/source` 只读文件、不收目录；没有这一层时 `sessions/` 这类出处点开会得到
    「不是文件」的拒绝 —— 链接在、原文看不到，等于没有出处。
    """
    folder = root_p / rel
    if not folder.is_dir():
        return ""
    files = sorted((p for p in folder.glob(pattern) if p.is_file()),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    return str(files[0].relative_to(root_p)).replace("\\", "/") if files else ""


def _newest_sign_file(root_p: Path) -> str:
    """`out/vsigns/` 里最新的逐份签文件（工作区相对路径；没有 ⇒ 空串）。

    为什么不能直接 `_newest_file(root_p, "out/vsigns")`：那个 glob 会把 `issued.json`
    （派生台账）也算进来。台账是本目录里最常被重写的文件，按 mtime 取最新必然选它 ——
    "签"这一格的原文出处于是指着一份谁都不许拿来下结论的索引
    （`vsigns.INDEX_NAME` 的 docstring 逐字如此）。这一格只认 `<artifact_sha>.json`。

    判据：`tests/test_webui_sign_reading_is_side_files_only.py`。
    """
    from .. import vsigns as _VSP

    folder = root_p / "out" / "vsigns"
    if not folder.is_dir():
        return ""
    files = sorted((p for p in folder.glob("*.json")
                    if p.is_file() and p.name != _VSP.INDEX_NAME),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    return str(files[0].relative_to(root_p)).replace("\\", "/") if files else ""


def _gate_source(name: str, root_p: Path) -> dict[str, Any]:
    """八格各自的原文落点（没有单一文件的格子给它的主表；`match` 是给人看的）。

    每一格的落点都现取真身（`_report_rel` / `_paper_rel` / `_checks_rel` /
    `_m_verdict_rel`）：这些路径同时是 `/api/source` 的入参，抄字面量就会在
    落点迁移后变成"链在、原文点不开"。
    """
    from .. import papercompile as _PC

    session = _newest_file(root_p, "sessions")
    table = {
        "paper": _src(_paper_rel(_PC.RECEIPT_NAME), label="编译回执"),
        "contradictions": _src("data/relations.json", label="矛盾闭环"),
        "load_bearing": _src(_paper_rel(_PC.TEX_NAME), label="承重结论"),
        "report_shape": _src(_report_rel(), label="交付说明"),
        "user_pending": _src(session or "sessions/", label="待答问题"),
        "substance": _src("data/statements.json", label="实质产出"),
        "acceptance": _src(_checks_rel(), label="验收表 C1–C16"),
        "artifact_ledger": _src("ARTIFACTS.jsonl", label="产物台账"),
        # 2026-11-16（Q1）：第八格读的是待入库文献表本身（以及它的归档目录）。
        "literature_pending": _src("data/lit_candidates.json", label="待入库文献表"),
    }
    return table.get(name, _src(""))


def _closing_gates(rep: Any, root_p: Path) -> dict[str, Any]:
    """八格四态 + `machine_pass` 的三条来源 + 每格的 warning。

    不变式：`cells` 逐格取自 `readouts.gate_cells(rep)`（与 `readouts.gates_readout`
    同一份计数，本层不另数 —— 判据 `tests/test_the_gate_table_is_computed_once.py`
    用反真空钉住这一点）；`machine_pass` 变假的三条来源各自点名，几栏不许因为
    "另一栏空着"而合流，逻辑上到不了的形态显式记 `unknown`。

    ## `na` 不叫「blocking」（READFIX-D-10）

    改前 `blocking_cells = status != "pass"` 把 `na` 也点成"blocking"，而
    `closing.closing_verdict` 的判据是 `fail` / `unknown` / 至少一格 `pass`，
    `na` 不进分母、不拦权威结论（`closing.py` 的 `fail_cells` 那一段逐字）。
    同一份 `gates` 里两栏对"na 拦不拦"说两句话，读的人会把「user_pending=na」
    当成"它把门拦住了"。现在 `blocking_cells` 只收 `fail` / `unknown`，
    `na_cells` 单列，`machine_pass_cause` 多一档 `na`（只由 na 造成 false 时）。

    ## 每格的 warning（READFIX-B）

    `artifact_ledger` 的口径是"`changed` ⇒ pass + warning"（`closing.py` 的 D9）。
    改前 warning 只混在 `detail` 那一栏里，而 `status=pass` 的绿色 badge 一上屏，
    "有 1 条被改写"就被盖住了。这里把同一批 finding 按 `level=="warning"` 收进
    `warnings`（`{格名: [原话]}`），页面在绿 badge 旁边照样显它。

    为什么 warning 不挂进 `cell` 本身：`cells` 必须与 `readouts.gate_cells` 逐字相等
    （判据 `tests/test_the_gate_table_is_computed_once.py` 用反真空钉住"八格只有一份
    实现"）。`source` 早就是"网页在共享读数之外补的呈现面"——warning 走同一条缝。
    """
    from .. import readouts as RD

    cells, counts = RD.gate_cells(rep)
    warnings_of: dict[str, list[str]] = {}
    for finding in (getattr(rep, "findings", []) or []):
        if str(getattr(finding, "level", "") or "") != "warning":
            continue
        warnings_of.setdefault(str(getattr(finding, "check", "")), []).append(
            str(getattr(finding, "detail", "") or ""))
    # `source` 是网页自己的呈现面（每格的原文落点），在共享读数之外补，
    # 不改格形状 —— 改了，两个出口的 `cells` 就不再逐字相等。
    for cell in cells:
        name = str(cell.get("name") or "")
        cell["source"] = _gate_source(name, root_p)
    verdict = getattr(rep, "m_verdict", None) or {}
    #: `machine_pass` 是"八格全 pass 且没有 blocker"的合取（`closing.ClosingReport`），
    #: 所以它变假有三条来源：`fail`/`unknown` 格、`na` 格（不是 pass，但不拦权威结论）、
    #: 与 blocker（不进八格、却拦门，如 `statements_unsigned`）。84 的现场：
    #: counts={pass:6,fail:1,na:1}、machine_pass=false、blockers=[] —— 两种格各占一份。
    blockers = [dict(f.to_dict()) for f in (getattr(rep, "blockers", []) or [])
                if hasattr(f, "to_dict")]
    blocking_cells = [dict(c) for c in cells
                      if str(c.get("status") or "") in ("fail", "unknown")]
    na_cells = [dict(c) for c in cells if str(c.get("status") or "") == "na"]
    machine_pass = bool(getattr(rep, "machine_pass", False))
    if machine_pass:
        cause = "pass"
    elif blockers and blocking_cells:
        cause = "blockers+cells"
    elif blockers:
        cause = "blockers"
    elif blocking_cells:
        cause = "cells"
    elif na_cells:
        # 只剩 na 格：machine_pass 按定义是假（na 不是 pass），但它们不拦权威结论。
        cause = "na"
    else:
        # 逻辑上到不了（machine_pass 的定义就是这三条的合取）；真到了也不许静默：
        # 页面会把这一档显成"缺陷读数"，而不是空白。
        cause = "unknown"
    return {"cells": cells, "counts": counts,
            "machine_pass": machine_pass,
            "m_says_done": bool(getattr(rep, "m_says_done", False)),
            "can_close": getattr(rep, "can_close", None),
            "can_close_reason": str(getattr(rep, "can_close_reason", "") or ""),
            "closable": bool(getattr(rep, "closable", False)),
            # 一份权威结论（ROOTGATE-②）：verdict + 八格逐格 + 红格的 why + 机器读数；
            # 页面必须并列显示它，不许让一个绿色 badge 盖住红格。
            "closing_verdict": dict(getattr(rep, "verdict", {}) or {}),
            "verdict_at": str(verdict.get("at") or ""),
            "verdict_met": (bool(verdict.get("met")) if verdict else None),
            # 几条来源分开点名：一个空 `blockers` 不等于"门没拦住"，
            # 也不等于"格失败"—— 读的人必须能看出是哪一半把 machine_pass 打假的。
            "blockers": blockers,
            "blocking_cells": blocking_cells,
            # `na` 单列：它让 machine_pass=false，但按 closing_verdict 不拦结论。
            "na_cells": na_cells,
            # 每格的 warning 原话（只收 level=="warning" 的 finding；空 = 没有）。
            "warnings": {name: [w for w in items if w]
                         for name, items in warnings_of.items()},
            "machine_pass_cause": cause}


def _closing_machine(feed: Mapping[str, Any], rep: Any,
                     root_p: Path) -> dict[str, Any]:
    """机器口径：退场（retire）与程序（programs）两组读数。

    不变式：两组各自带 `checked`，且 `checked=False` 时读数原样保留（本层不把
    "没查成"折成 0 / 空清单）；`retire` 的 `source` 指向本次运行那份台账文件，
    文件不在才回落到目录 —— 两种落点都必须读得出来。
    """
    retire = dict(feed.get("retire") or {})
    programs = dict(feed.get("programs") or {})
    caliber = dict((getattr(rep, "readings", {}) or {}).get("machine_caliber") or {})
    return {"checked": bool(caliber.get("checked")),
            "value": caliber.get("value"), "reason": str(caliber.get("reason") or ""),
            "retire_checked": bool(retire.get("checked")),
            "retire_complete": bool(retire.get("complete")),
            "retire_projected": bool(retire.get("projected")),
            "retire_auto_retire": dict(retire.get("auto_retire") or {}),
            "retire_open_items": int(retire.get("root_open_items") or 0),
            "retire_nodes": int(retire.get("total") or 0),
            "retire_states": dict(retire.get("states") or {}),
            "programs_checked": bool(programs.get("checked")),
            "programs_ok": (bool(programs.get("checked"))
                            and int(programs.get("running_count") or 0) == 0
                            and not programs.get("unowned")),
            "programs_running_count": int(programs.get("running_count") or 0),
            "programs_unowned": list(programs.get("unowned") or []),
            "source": _src(
                (f"out/roster/{retire.get('root')}.jsonl"
                 if retire.get("root") and (root_p / "out" / "roster" /
                                            f"{retire.get('root')}.jsonl").is_file()
                 else "out/roster/"), label="retire_integrity")}


def _closing_sessions(root_p: Path) -> tuple[list[Any], list[Any], bool, str]:
    """会话事件 → (原始记录, 本趟 runs, 查成没有, 原因)。

    不变式：读不成时 `records=[]`、`runs=[]`、`checked=False`（原因随行），绝不返回
    "0 趟"这种看起来像读数的形态 —— 下游四个成本数与时间轴因此一起变 None，而不是 0。
    """
    try:
        records, info = SS.read_all_sessions(root_p)
        runs = SS.runs_in_session(records)
    except Exception as exc:  # noqa: BLE001
        return [], [], False, f"会话读不出来（{type(exc).__name__}: {exc}）"
    if bool(info.get("checked")):
        return list(records), list(runs), True, ""
    return list(records), list(runs), False, str(info.get("reason") or "会话没查成")


def _closing_last_at(rep: Any) -> str:
    """最后收工时刻：M 判据的 `at`，缺了回落到 `readings.verdict_source.at`。

    不变式：只算一次、只从这两处取（读不到就是空串）；顶层的 `source.match` 与
    时间轴的 `last_closing_at` 用的是同一个值，"这份判据指向哪一版"与"最后收工
    什么时候"不许各说各话。
    """
    verdict = getattr(rep, "m_verdict", None) or {}
    at = str(verdict.get("at") or "")
    if not at:
        at = str(((getattr(rep, "readings", {}) or {})
                  .get("verdict_source") or {}).get("at") or "")
    return at


def _closing_cost(store: Any, records: Sequence[Any], runs: Sequence[Any],
                  sessions_ok: bool, sessions_reason: str) -> dict[str, Any]:
    """成本四数（事件求和 / 收工行自报 / 无人认领 / 账本）+ 对账。

    不变式：每个成本数只在会话读成时给值（否则 None，不是 0）；"账本 − 事件"的
    差额解释只由 `tokenmeter.TokenMeter.by_scope()` 提供，本层不另算一遍分组 ——
    归口只有一个出处，两个数（账本行数 / 事件调用数）不许互相顶替。
    """
    event_usd = round(sum(float(r.get("usd") or 0) for r in runs), 6) if sessions_ok else None
    spend_usd = round(sum(float(r.get("spend_usd") or 0) for r in runs), 6) if sessions_ok else None
    runs_without_spend = sum(1 for r in runs if r.get("spend_usd") is None)
    unattributed = SS.unattributed_usd_of(records, runs) if sessions_ok else None
    # 账本那一格的三态（READFIX-D-5）：改前 `store.rows("usage_ledger")` 对"不在盘上"
    # 回 []、对坏 JSON 抛异常被吞成 `ledger_usd=None` —— 缺文件那一档于是折成
    # `ledger_usd=0` + `checked=True` + `reason=""`（"还没花过钱"与"没查成"长成一个样）。
    try:
        usage_rows, ledger_tri = _table_state(store, "usage_ledger")
    except Exception:  # noqa: BLE001 - 读不成就是没查成（不是 0）
        usage_rows, ledger_tri = [], TRI_UNREADABLE
    ledger_usd = (round(sum(float(r.get("usd") or 0) for r in usage_rows), 6)
                  if ledger_tri == TRI_COMPUTED else None)
    if ledger_tri == TRI_COMPUTED:
        ledger_reason = ""
    elif ledger_tri == TRI_NOT_APPLICABLE:
        ledger_reason = ("usage_ledger 不在盘上（还没写过）⇒ 账本那一格记 not_applicable，"
                         "不是 0：这个工作区还没有花钱的账本")
    else:
        ledger_reason = ("usage_ledger 读不出来（坏 JSON / 坏表）⇒ 账本那一格记 unreadable，"
                         "不是 0")
    checked = bool(sessions_ok and ledger_tri == TRI_COMPUTED)
    reason = "" if checked else "；".join(x for x in (
        "" if sessions_ok else str(sessions_reason or "会话没查成"),
        ledger_reason if ledger_tri != TRI_COMPUTED else "") if x)
    cost = {"checked": checked,
            "reason": reason,
            "event_usd": event_usd, "spend_usd": spend_usd,
            "spend_unknown_usd_calls": (sum(int(r.get("spend_unknown_usd_calls") or 0)
                                            for r in runs) if sessions_ok else None),
            "unattributed_usd": unattributed, "runs_without_spend": runs_without_spend,
            "ledger_usd": ledger_usd,
            # 账本那一格的三态与原因（READFIX-D-5）：`checked=True` 不再能盖住
            # "账本没读过"这件事 —— 页面读这两格把"还没写过"显出来。
            "ledger_tri": ledger_tri,
            "ledger_reason": ledger_reason,
            # 键名曾叫 `ledger_rows`，与验收辅助读数 / statements 台账行数同名不同物。
            "usage_ledger_rows": (len(usage_rows)
                                  if ledger_tri == TRI_COMPUTED else None),
            "source": _src("data/usage_ledger.json", label="usage_ledger")}
    # ---- 成本对账（2026-11-20，WEBCLEAN）：四个数并排却不给差额的解释
    # 真机 lp-ball-11 的现场：事件求和 2.422720 / 自报 2.271637 / 无人认领 0.151083 /
    # usage_ledger 2.543759。前两只差恰好是无人认领那一笔（自洽），而
    # `账本 − 事件 = 0.121039 = by_scope.extract.usd` —— 账本里有 14 行 extract，
    # 事件流里没有这 14 笔调用。页面上没有这句话，读者只能说"四个数里三个对不上"。
    #
    # 归口的唯一出处是 `tokenmeter.TokenMeter.by_scope()`（本层不另算一遍分组）；
    # 事件里的调用数取 `Σ runs[].llm_calls`（与 "账本行数" 是两个数，见 budget_face）。
    by_scope: dict[str, Any] = {}
    try:
        from ..tokenmeter import TokenMeter

        by_scope = dict(TokenMeter(store).by_scope() or {})
    except Exception:  # noqa: BLE001 - 读数层：读不到就如实说没查成（不写 0）
        by_scope = {}
    extract_usd = (round(float((by_scope.get("extract") or {}).get("usd") or 0), 6)
                   if by_scope else None)
    ledger_minus_event = (round(ledger_usd - event_usd, 6)
                          if (ledger_usd is not None and event_usd is not None) else None)
    explained = (None if (ledger_minus_event is None or extract_usd is None)
                 else abs(ledger_minus_event - extract_usd) < 1e-6)
    cost["reconciliation"] = {
        "by_scope": by_scope,
        "extract_usd": extract_usd,
        "extract_entries": (int((by_scope.get("extract") or {}).get("entries") or 0)
                            if by_scope else None),
        "event_llm_calls": (sum(int(r.get("llm_calls") or 0) for r in runs)
                            if sessions_ok else None),
        "ledger_minus_event_usd": ledger_minus_event,
        "explained_by_extract": explained,
        "note": ("账本 − 事件 = 归口里 extract 那几笔（事件流里没有这些调用）；"
                 "`usage_ledger_rows` 是 usage_ledger 的账本行数，`event_llm_calls` 是"
                 "事件里的调用数 —— 一次调用可能记 0..n 行，两个数不许互相顶替。"),
    }
    return cost


def _closing_runtime(root_p: Path, store: Any, runs: Sequence[Any], sessions_ok: bool,
                     last_closing_at: str) -> dict[str, Any]:
    """时间轴（起止 / 趟数 / 在飞）+ 名册两个读数 + 子项计数。

    不变式：每个读数读不到时是 None（不是 0）；`first` / `last` 取自同一批 runs
    （`first_start_ts ≤ last_event_ts` 由构造保证）；名册与子项计数各自 try，坏一个
    不许把另一个也拖成 0。
    """
    starts = [str(r.get("start_ts") or "") for r in runs if r.get("start_ts")]
    ends = [str(r.get("end_ts") or r.get("start_ts") or "") for r in runs]
    first, last = (min(starts) if starts else ""), (max(ends) if ends else "")

    # ---- 名册两个读数（`children_unretired` 与 `children_in_ledger` 是两个量）
    roster_nodes = 0
    children_in_ledger: int | None = None
    roster_child_count: int | None = None
    unplaced = 0
    try:
        face = roster_face(root_p)
        nodes = list(face.get("nodes") or [])
        roster_nodes = len(nodes)
        if nodes:
            children_in_ledger = nodes[0].get("children_in_ledger")
            roster_child_count = nodes[0].get("roster_child_count")
        unplaced = len(face.get("unplaced") or [])
    except Exception:  # noqa: BLE001 —— 名册读不到 ⇒ 那几格 None，不是 0
        pass
    try:
        from .. import schema as _S
        from ..secretary import Secretary

        child = Secretary(_S.CONDUCTOR_ROLE, root=root_p, store=store).child_counts()
    except Exception:  # noqa: BLE001
        child = {"checked": False, "children_unretired": None, "active_child_count": None}
    return {"first_start_ts": first, "last_event_ts": last,
            "elapsed_sec": _seconds_between(first, last),
            "runs_total": len(runs) if sessions_ok else None,
            "open_runs": (sum(1 for r in runs if r.get("end_index") is None)
                          if sessions_ok else None),
            "in_flight_agents": (sum(1 for r in runs if r.get("end_index") is None)
                                 if sessions_ok else None),
            "last_closing_at": last_closing_at,
            "roster_nodes": roster_nodes,
            "children_in_ledger": children_in_ledger,
            "roster_child_count": roster_child_count,
            "children_unretired": child.get("children_unretired"),
            "active_child_count": child.get("active_child_count"),
            "unplaced": unplaced,
            "source": _src(_newest_file(root_p, "sessions") or "sessions/",
                           label="runs")}


def _closing_content(acc: Mapping[str, Any], root_p: Path) -> dict[str, Any]:
    """内容级验收（五条；只读、不进机器门）。

    不变式：`fail` 与 `unknown` 分两栏（`failed` / `unchecked`），`passed` 是"有判据
    且全 pass" —— "没查成"不许折成"不过"（三态纪律），两档也不许折平成一档。
    """
    from ..reviewaccept import CRITERIA

    criteria = {str(k): str(v) for k, v in (acc.get("criteria") or {}).items()}
    details = {str(k): str(v) for k, v in (acc.get("details") or {}).items()}
    content_sources = {
        "attachment_is_honest": _src(_report_rel(), label="交付说明"),
        "triage_branch_recorded": _src(_newest_file(root_p, "sessions") or "sessions/",
                                       label="提问记录"),
        "within_cost_cap": _src("data/usage_ledger.json", label="成本台账"),
        "hops_have_readable_prompts": _src("data/tasks.json", label="召唤台账"),
        "statements_have_assumptions_and_source": _src("data/statements.json",
                                                       label="命题台账"),
    }
    return {"tri": str(acc.get("tri") or TRI_UNREADABLE),
            "reason": str(acc.get("reason") or ""),
            "criteria": criteria, "details": details,
            "titles": {str(k): str(t) for k, t in CRITERIA},
            "sources": content_sources,
            "failed": sorted(k for k, v in criteria.items() if v == "fail"),
            "unchecked": sorted(k for k, v in criteria.items() if v == "unknown"),
            "passed": bool(criteria) and all(v == "pass" for v in criteria.values()),
            "note": ("内容级验收只读、不进机器门；`failed` 是真不过，"
                     "`unchecked` 是没查成 —— 两档不许折平。")}


def _closing_unsigned_signs(rep: Any) -> dict[str, Any]:
    """C 块：`sign_does_not_back_the_row` 那一档的读数（只数、不另判）。

    ## 为什么 C 块要单独读这一格

    改前收工读数把这一档归进 `never_submitted`，验收页 C 块照抄 warning 原话，
    于是"签在、判决地址也对得上、只是签不背书这一行"被读成"没送过 V"（B5 §5 上报）。
    收工读数现在把它单列（`statements_unsigned.sign_does_not_back_the_row`），
    这一层只从同一份收工报告里取数：判定在 `vsigns.sign_reading`（一处），
    本层不重跑、也不自己再判一次"这份签背不背这一行"。

    ## 三态

    `checked=False` ⇒ `count=None`（没查成，不是 0）。报告里没有这一格（更早那一版的
    读数形状）同样记 `None` —— "报告没给这一格"不是"这一档没有"。
    """
    su = dict((getattr(rep, "readings", {}) or {}).get("statements_unsigned") or {})
    checked = bool(su.get("checked"))
    rows = [one for one in (su.get("sign_does_not_back_the_row") or [])
            if isinstance(one, Mapping)]
    ids: list[str] = []
    for one in rows:
        sid = str(one.get("stmt_id") or "")
        if sid and sid not in ids:
            ids.append(sid)
    raw = su.get("sign_does_not_back_the_row_count")
    if not checked or raw is None:
        count = None
    else:
        count = int(raw)
    return {"checked": checked, "count": count,
            "class": "sign_does_not_back_the_row",
            "stmt_ids": ids[:PACKAGE_ROWS_MAX],
            "note": ("黄档：签在、判决地址对得上、但签不背书这一行 —— 它不算签，也不并进"
                     "「没送过 V」；凭据本身复算通过、V 没做错。`count=null` 是这一格"
                     "没查成（不是 0）。")}


def _closing_block(rep: Any, feed: Mapping[str, Any], acc: Mapping[str, Any],
                   structure: Mapping[str, Any], proofs: Mapping[str, Any],
                   root_p: Path, store: Any) -> dict[str, Any]:
    """C 块：八格四态 + 机器口径 + 回执 + 成本 + 时间轴/名册 + 内容级验收（折叠）。

    这一层只做装配：六块各由上面一个单元算（每块自己的不变式写在各函数 docstring），
    这里钉的是顺序与共用读数 —— 八格 → 机器口径 → 会话（成本与时间轴共用同一批
    runs，只读一次盘）→ 内容；顶层 `tri` / `reason` 仍由 `rep.refusal` 一处决定。
    """
    gates = _closing_gates(rep, root_p)
    machine = _closing_machine(feed, rep, root_p)
    records, runs, sessions_ok, sessions_reason = _closing_sessions(root_p)
    last_closing_at = _closing_last_at(rep)
    cost = _closing_cost(store, records, runs, sessions_ok, sessions_reason)
    runtime = _closing_runtime(root_p, store, runs, sessions_ok, last_closing_at)
    content = _closing_content(acc, root_p)

    tri = TRI_COMPUTED
    reason = ""
    if getattr(rep, "refusal", None):
        tri = TRI_UNREADABLE
        reason = str((getattr(rep, "refusal", {}) or {}).get("detail") or "门受控拒绝")
    return {"tri": tri, "reason": reason,
            "source": _src(_m_verdict_rel(), match=last_closing_at,
                           label="M 判据"),
            "gates": gates, "machine": machine,
            # READOUT-FIX：第六档（签不背书这一行）在 C 块的独立落点 —— 黄档，
            # 与「没送过 V」分开读。
            "unsigned_signs": _closing_unsigned_signs(rep),
            "undelivered": dict(proofs.get("receipt") or {}), "cost": cost,
            "runtime": runtime, "content": content}


def package_face(root: str | Path, store: Any = None, *, project_dir: str = "",
                 report_path: str = "", cap_usd: float | None = None,
                 sid: str | None = None) -> dict[str, Any]:
    """`GET /api/package` 的读模型：论文包三块（A 证明 / B 结构 / C 收工）。

    一次调用读一次盘、算一次门：三块共用同一份快照（分成三个端点会让“已签 0 条”
    与“八格 pass”来自两个瞬间）。`project_dir` / `report_path` 缺省取工作区根与
    `cli.DEFAULT_REPORT_REL`（`out/report/REPORT.md`）—— 页面必须把它们传下来；
    不传时 `_structure_block` 的 `tex_sha256` / `pdf_pages` / `receipt_matches_tex`
    三格会按构造永远是空/unknown。

    ## 缺省不许自算（2026-11-22，`draft/197` §十四 ①）

    改前这里写着 `report_path or "out/review/REPORT.md"`：写侧已按新教法写到
    `out/report/`，而网页这一层自算的缺省还指退役目录 ⇒ 同一个工作区在 CLI 说
    “报告：通过”、在 `/api/package` 的 `report_shape` 说“报告不在盘上”。
    所以缺省一律 `_report_rel()`（真身 `cli.DEFAULT_REPORT_REL`），
    三块的原文出处也各自现取（`_paper_rel` / `_m_verdict_rel`）。

    每块的 `tri` 独立：`texaudit` 抛异常不会把八格一起打成 unknown。顶层 `tri`
    只在三块全部没查成时才是 `unreadable`（部分没查成时逐块看 `reason`）。
    """
    from .. import closing as CL
    from .. import papercompile as _PC

    root_p = Path(str(root))
    try:
        if store is None:
            from ..store import Store

            store = Store(root_p)
        project = CL.resolve_under_workspace(store, project_dir or ".")
        # 缺省是「项目根 / 真身」而不是「工作区根 / 真身」：子项目（`project_dir`
        # 给 `projects/x`）的报告落在那个项目里，与 `cli.cmd_closing` 的
        # `Path(project) / DEFAULT_REPORT_REL` 同一口径。
        report = (CL.resolve_under_workspace(store, report_path) if report_path
                  else str(Path(project) / _report_rel()))
        structure = _structure_block(root_p, project)
        feed = CL.machine_feeders(store)
        rep = CL.check_closing(store, project_dir=project, report_path=report,
                               session_root=root_p, sid=sid,
                               retire=feed.get("retire"), programs=feed.get("programs"))
        acc = acceptance_face(root_p, store, project_dir=project,
                              report_path=report, cap_usd=cap_usd, sid=sid)
        proofs = _proofs_block(root_p, store, rep, structure)
        closing = _closing_block(rep, feed, acc, structure, proofs, root_p, store)
    except Exception as exc:  # noqa: BLE001 —— 整面没查成：三块都写“没查成”，不写 0
        reason = f"论文包读数没跑成（{type(exc).__name__}: {exc}）"
        return {"tri": TRI_UNREADABLE, "reason": reason,
                "generated_at": _now_iso(),
                "proofs": _empty_proofs(reason),
                "structure": {"tri": TRI_UNREADABLE, "reason": reason,
                              "source": _src(_paper_rel(_PC.TEX_NAME)),
                              "paper": _paper_facts(str(root_p)),
                              "checks": {}, "ledger": {}, "findings": []},
                "closing": {"tri": TRI_UNREADABLE, "reason": reason,
                            "source": _src(_m_verdict_rel()),
                            "gates": {"cells": [], "counts": {"pass": 0, "fail": 0,
                                                              "unknown": 0, "na": 0},
                                      "machine_pass": False, "m_says_done": False,
                                      "can_close": None, "can_close_reason": reason,
                                      "closable": False, "verdict_at": "",
                                      "verdict_met": None,
                                      "closing_verdict": None,
                                      "blockers": [], "blocking_cells": [],
                                      "na_cells": [], "warnings": {},
                                      "machine_pass_cause": "unknown"},
                            "machine": {"checked": False, "value": None, "reason": reason,
                                        "retire_checked": False, "retire_complete": False,
                                        "retire_projected": False, "retire_auto_retire": {},
                                        "retire_open_items": 0, "retire_nodes": 0,
                                        "retire_states": {}, "programs_checked": False,
                                        "programs_ok": False,
                                        "programs_running_count": 0, "programs_unowned": [],
                                        "source": _src("")},
                            # 整面没查成 ⇒ 这一格也是"没查成"（`count=None`，不是 0）。
                            "unsigned_signs": {"checked": False, "count": None,
                                               "class": "sign_does_not_back_the_row",
                                               "stmt_ids": [], "note": reason},
                            "undelivered": dict(_empty_proofs(reason)["receipt"]),
                            "cost": {"checked": False, "reason": reason, "event_usd": None,
                                     "spend_usd": None, "spend_unknown_usd_calls": None,
                                     "unattributed_usd": None, "runs_without_spend": 0,
                                     "ledger_usd": None, "usage_ledger_rows": None,
                                     "ledger_tri": TRI_UNREADABLE,
                                     "ledger_reason": "整面没查成 ⇒ 账本那一格也没查成",
                                     "reconciliation": {
                                         "by_scope": {}, "extract_usd": None,
                                         "extract_entries": None, "event_llm_calls": None,
                                         "ledger_minus_event_usd": None,
                                         "explained_by_extract": None,
                                         "note": "整面没查成 ⇒ 成本对账也算不出来（不是 0）"},
                                     "source": _src("data/usage_ledger.json")},
                            "runtime": {"first_start_ts": "", "last_event_ts": "",
                                        "elapsed_sec": None, "runs_total": None,
                                        "open_runs": None, "in_flight_agents": None,
                                        "last_closing_at": "", "roster_nodes": 0,
                                        "children_in_ledger": None,
                                        "roster_child_count": None,
                                        "children_unretired": None,
                                        "active_child_count": None, "unplaced": 0,
                                        "source": _src("sessions/")},
                            "content": {"tri": TRI_UNREADABLE, "reason": reason,
                                        "criteria": {}, "details": {}, "titles": {},
                                        "sources": {},
                                        "failed": [], "unchecked": [], "passed": False,
                                        "note": ""}}}
    tris = [str(structure.get("tri") or ""), str(proofs.get("tri") or ""),
            str(closing.get("tri") or "")]
    tri = TRI_UNREADABLE if all(t == TRI_UNREADABLE for t in tris) else TRI_COMPUTED
    reasons = [str(part.get("reason") or "") for part in (structure, proofs, closing)
               if str(part.get("tri") or "") == TRI_UNREADABLE
               and str(part.get("reason") or "")]
    return {"tri": tri, "reason": "；".join(reasons), "generated_at": _now_iso(),
            "proofs": proofs, "structure": structure, "closing": closing}


#: `/api/source` 读文件时最多先读这么多字节来定位行/needle（大文件不许整份转）。
SOURCE_SCAN_BYTES = 2 * 1024 * 1024

#: 窗口前后各留几行（`line` 定位时；第一行/最后一行会被夹住）。
SOURCE_CONTEXT_LINES = 10


def _source_refusal(path: str, reason: str) -> dict[str, Any]:
    """受控拒绝：`tri=unreadable` + 理由，`lines` 永远为空（不回内容）。"""
    return {"tri": TRI_UNREADABLE, "reason": reason, "path": str(path or ""),
            "line": 0, "start_line": 0, "lines": [], "total": None,
            "truncated": False}


def source_window(root: str | Path, path: str, *, line: int = 0,
                  match: str = "", max_lines: int = SOURCE_LINES_MAX) -> dict[str, Any]:
    """`GET /api/source` 的读模型：工作区内一个文本文件的原文窗口。

    五条闸（缺一条都等于把工作区文件读给浏览器）：

    1. 相对路径：绝对路径一律拒（`Path.is_absolute()`；Windows 盘符路径同样命中）；
    2. 不许越界：路径分量里出现 `..` 直接拒，不做"resolve 之后再看"的侥幸；
    3. 工作区内：`resolve()` 之后必须 `relative_to(workspace)`，符号链接跳出去也算越界；
    4. 文本后缀：只认 `SOURCE_SUFFIXES`（PDF / 图片 / 可执行文件不认）；
    5. 大文件截断：只先读 `SOURCE_SCAN_BYTES`，窗口最多 `max_lines` 行；总行数只在
       没截断时给（截断时 `total=None` + `truncated=True`，不编一个假总数）。

    三态：任何一条闸不过 ⇒ `tri="unreadable"` + `reason` + 空 `lines`（不是 200 的空文件）。
    """
    base = Path(str(root)).resolve()
    raw = str(path or "").strip()
    if not raw:
        return _source_refusal(raw, "没给 path ⇒ 不知道要读哪一份原文")
    p = Path(raw)
    if p.is_absolute():
        return _source_refusal(raw, "绝对路径一律拒（只收工作区内的相对路径）")
    if any(part == ".." for part in p.parts):
        return _source_refusal(raw, "路径里有 `..` ⇒ 越界拒绝")
    try:
        target = (base / p).resolve()
    except OSError as exc:
        return _source_refusal(raw, f"路径解析失败（{type(exc).__name__}: {exc}）")
    try:
        target.relative_to(base)
    except ValueError:
        return _source_refusal(raw, "路径解析后在工作区外 ⇒ 拒绝（不回内容）")
    if not target.is_file():
        return _source_refusal(raw, "不是工作区内的一个文件（不存在或不是文件）")
    if target.suffix.lower() not in SOURCE_SUFFIXES:
        return _source_refusal(raw, f"这个后缀不认（只收 {', '.join(SOURCE_SUFFIXES)}）")
    try:
        size = target.stat().st_size
    except OSError as exc:
        return _source_refusal(raw, f"读不到文件大小（{type(exc).__name__}: {exc}）")
    truncated = size > SOURCE_SCAN_BYTES
    try:
        with target.open("rb") as fh:
            raw_bytes = fh.read(SOURCE_SCAN_BYTES)
    except OSError as exc:
        return _source_refusal(raw, f"读不出来（{type(exc).__name__}: {exc}）")
    text = raw_bytes.decode("utf-8", errors="replace")
    lines = text.splitlines()
    total: int | None = None if truncated else len(lines)
    want = max(1, int(max_lines or SOURCE_LINES_MAX))
    start = 0
    if match:
        needle = str(match)
        found = next((i for i, one in enumerate(lines) if needle in one), -1)
        if found >= 0:
            start = max(0, found - SOURCE_CONTEXT_LINES)
            line = found + 1
        else:
            return _source_refusal(
                raw, f"文件里没有找到 {needle!r}"
                     + ("（这个文件已截断，needle 可能在后半段）" if truncated else ""))
    elif line and int(line) > 0:
        start = max(0, int(line) - 1 - SOURCE_CONTEXT_LINES)
    window = lines[start:start + want]
    return {"tri": TRI_COMPUTED, "reason": "", "path": raw,
            "line": int(line or 0), "start_line": start + 1,
            "lines": window, "total": total, "truncated": truncated}


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
def _settings_cells(raw: Mapping[str, Any], red: Mapping[str, Any],
                    effort_shown: str, temperature_shown: str,
                    sec_cell: Mapping[str, Any]) -> tuple[
                        dict[str, Any], dict[str, Any], dict[str, Any]]:
    """SETTINGS-RAW 的 `raw` / `effective` / `source` 三格（`_settings_reading` 的帮手）。

    为什么单独一个函数：`_settings_reading` 已经在一个 200 行的体量边上，把这三格
    塞进去会跨过体量门（三格只许降）。这里每一格都走既有梯子，不另造判据：

    - 工具链与 `workspace.projects_dir` 用 `settings.env_or_setting` /
      `settings.lean_enabled` / `projects` 的既有档位（env > settings > 缺省）；
    - 模型三档（`model` / `models.<角色>` / `secretary`）走 `modelgw.spec_for` 的
      既有梯子（`models.<角色>` → `models.default` → `model` → env → 缺省）；
    - 来源词表只有三个：`settings` / `env` / `default`（空串那一档记成 default）。

    返回 `(raw_cells, effective, source)`，形状与机器面 `settings` 的五段逐字对齐。
    """
    from ..formalgw import ENV_MATHLIB_ROOT
    from ..modelgw import (ENV_BASE, ENV_EFFORT, ENV_KEY, ENV_NAME, ENV_TEMPERATURE,
                           spec_for)
    from ..projects import DEFAULT_PROJECTS_DIR, ENV_PROJECTS_DIR
    from ..settings import (DEFAULT_MODEL_SLOT, LEAN_ENABLED_KEY, MODEL_KEYS,
                            MODELS_SECTION, ROLE_SLOTS, SECRETARY_SECTION, TOOLCHAIN_KEYS,
                            WORKSPACE_KEYS, env_or_setting, lean_enabled)
    from ..toolchain import ENV_COQ_BIN, ENV_ISABELLE_BIN, ENV_LEAN_BIN
    from . import settingsraw as SRAW

    raw_cells = SRAW.raw_sections(raw)
    raw_models = raw_cells.get(MODELS_SECTION) or {}
    raw_model = raw_cells.get("model") or {}
    raw_sec = raw_cells.get(SECRETARY_SECTION) or {}
    default_slot_raw = raw_models.get(DEFAULT_MODEL_SLOT) or {}
    # ---- 工具链 / 工作区：env > settings > 缺省
    tool_eff: dict[str, str] = dict(raw_cells.get("toolchain") or {})
    tool_src: dict[str, str] = {}
    tool_env = {"lean_bin": ENV_LEAN_BIN, "coq_bin": ENV_COQ_BIN,
                "isabelle_bin": ENV_ISABELLE_BIN, "mathlib_root": ENV_MATHLIB_ROOT}
    for k in TOOLCHAIN_KEYS:
        if k == LEAN_ENABLED_KEY:
            try:
                on, src = lean_enabled()
            except Exception:  # noqa: BLE001 - 坏值由工具链一侧报，这一格不炸读数
                on, src = str(tool_eff.get(k, "")).lower() in (
                    "1", "true", "yes", "on", "y", "t"), ""
            tool_eff[k] = "true" if on else "false"
            tool_src[k] = src or "default"
            continue
        env_name = tool_env.get(k, "")
        if env_name:
            value, src = env_or_setting(env_name, tool_eff.get(k, ""))
            tool_eff[k] = value
            tool_src[k] = src or "default"
        else:
            tool_src[k] = "settings" if tool_eff.get(k) else "default"
    proj_value, proj_src = env_or_setting(
        ENV_PROJECTS_DIR, (raw_cells.get("workspace") or {}).get("projects_dir", ""))
    work_eff: dict[str, str] = dict(raw_cells.get("workspace") or {})
    work_src: dict[str, str] = {}
    work_eff["projects_dir"] = proj_value or str(DEFAULT_PROJECTS_DIR)
    work_src["projects_dir"] = proj_src or "default"
    for k in WORKSPACE_KEYS:
        if k != "projects_dir":
            work_eff.setdefault(k, "")
            work_src[k] = "settings" if work_eff[k] else "default"
    # ---- 模型三档：来源逐格问答，判据与 `modelgw.key_source` 同一条梯子
    model_env = {"api_key": ENV_KEY, "base_url": ENV_BASE, "name": ENV_NAME,
                 "reasoning_effort": ENV_EFFORT, "temperature": ENV_TEMPERATURE}

    def cell_source(own_raw: str, env_name: str,
                    inherited: tuple[str, ...] = ()) -> str:
        """这一格从哪来：`env` > 盘上（本格或继承的档）> `default`。"""
        if env_name:
            _value, src = env_or_setting(env_name, own_raw)
            if src:
                return src
        if str(own_raw or "").strip():
            return "settings"
        if any(str(x or "").strip() for x in inherited):
            return "settings"
        return "default"

    model_eff = {"vendor": red["vendor"], "api_key": red["api_key"],
                 "base_url": red["base_url"], "name": red["model"],
                 "reasoning_effort": effort_shown, "temperature": temperature_shown}
    model_src = {k: cell_source(raw_model.get(k, ""), model_env.get(k, ""))
                 for k in MODEL_KEYS}
    models_eff: dict[str, dict[str, str]] = {}
    models_src: dict[str, dict[str, str]] = {}
    for slot in sorted(set(ROLE_SLOTS) | set(raw_models)):
        own = raw_models.get(str(slot)) or {}
        try:
            slot_spec, _where = spec_for(str(slot))
            slot_red = slot_spec.redacted()
            slot_eff = {"api_key": slot_red["api_key"],
                        "base_url": slot_red["base_url"],
                        "name": slot_red["model"],
                        "vendor": slot_red["vendor"],
                        "reasoning_effort": slot_red["reasoning_effort"],
                        "temperature": str(slot_red["temperature"])}
        except Exception:  # noqa: BLE001 - 坏掉一档不带走整份读数
            slot_eff = {k: "" for k in MODEL_KEYS}
        models_eff[str(slot)] = slot_eff
        models_src[str(slot)] = {
            k: cell_source(own.get(k, ""), model_env.get(k, ""),
                           (default_slot_raw.get(k, ""), raw_model.get(k, "")))
            for k in MODEL_KEYS
        }
    sec_eff = {k: _as_text(sec_cell.get(k, "")) for k in MODEL_KEYS}
    sec_src = {k: cell_source(raw_sec.get(k, ""), model_env.get(k, ""),
                              (default_slot_raw.get(k, ""), raw_model.get(k, "")))
               for k in MODEL_KEYS}
    effective = {"toolchain": tool_eff, "model": model_eff, "workspace": work_eff,
                 MODELS_SECTION: models_eff, SECRETARY_SECTION: sec_eff}
    source = {"toolchain": tool_src, "model": model_src, "workspace": work_src,
              MODELS_SECTION: models_src, SECRETARY_SECTION: sec_src}
    return raw_cells, effective, source


def _settings_reading() -> tuple[dict[str, Any], str, str]:
    """设置文件的三段读数（`settings.load_settings` + `settings.settings_path`）。

    设置是机器级的，不是工作区级的：落点由 `settings.settings_path()` 决定
    （`--path` → 环境变量 `AGENTFLOW_SETTINGS` → 包根下的 `settings.json`），
    与工作区根无关。所以本函数不吃 `root` 参数 —— 这一点写在这里免得读的人
    以为"设置读的是工作区里的那一份"。

    返回 `(读数, tri, reason)`。key 永远不出现在这里：`model.api_key` 只写
    "配没配"（`configured`）与掩码后的 `redacted()`（`modelgw.ModelSpec.redacted`
    在 key 非空时给 `*`）。判据 `tests/test_webui_readers.py` 有一条逐字符断言
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
                 MODELS_SECTION: {}, SECRETARY_SECTION: {},
                 # 三个新字段与正常档同形（坏文件不是"没有这三格"）：
                 # 读不出来时它们是空壳，页面据此知道"这一档没读到"。
                 "raw": {n: {} for n in ("toolchain", "model", "workspace",
                                         MODELS_SECTION, SECRETARY_SECTION)},
                 "effective": {n: {} for n in ("toolchain", "model", "workspace",
                                               MODELS_SECTION, SECRETARY_SECTION)},
                 "source": {n: {} for n in ("toolchain", "model", "workspace",
                                            MODELS_SECTION, SECRETARY_SECTION)}},
                TRI_UNREADABLE, f"settings.load_settings 读不出来："
                                f"{type(exc).__name__}: {exc}")
    tool = {k: str(v) for k, v in toolchain_settings().items()}
    model = {k: str(v) for k, v in model_settings().items()}
    work = {k: str(v) for k, v in workspace_settings().items()}
    # 按角色 / 秘书那两档：只给掩码后的形态 + "配没配"
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
                            # 采样温度：按角色那一档也要报，
                            # 否则"能给 V 配 1.0"这件事在机器面上看不见。
                            "temperature": str(red_slot["temperature"]),
                            # 这一格必须取这一档自己的 `key_source`（`spec_for` 已经
                            # 按这一档算过 env/settings）。用全局 `key_source()` 会读
                            # `model` 段 ⇒ 每一档报同一个来源：`models.A` 的 key 明明
                            # 是从这一档取的，读数却说"看的是 model 段" —— 缺陷形态与
                            # "读数说谎"同族：数字自洽、没有任何地方会报错。
                            "key_source": spec_slot.key_source, "configured": spec_slot.configured,
                            "source": where}
    sec_cell: dict[str, Any] = {}
    try:
        sec_spec, sec_where = spec_for(secretary=True)
        red_sec = sec_spec.redacted()
        sec_cell = {"api_key": red_sec["api_key"], "base_url": red_sec["base_url"],
                    "name": red_sec["model"], "vendor": red_sec["vendor"],
                    "reasoning_effort": red_sec["reasoning_effort"],
                    # 采样温度：秘书那一档的形状与上面两处逐字相同。
                    "temperature": str(red_sec["temperature"]),
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
    # 推理强度（所有者裁定「所有智能体都要能 thinking，默认 High」）：
    # 它同属"这台机器上的模型配置"，所以机器面必须报它 —— 否则台面上默认写着
    # 一切正常，而 `settings.json` 里那个值可能是 `off`。
    effort_raw = model.get("reasoning_effort", "") or ""
    # 采样温度：与强度同一条纪律 —— 盘上写了什么，机器面就报什么；
    # 区间外的值判成 unreadable 并把原值原样回显（回显成缺省会让人以为配置生效了）。
    temperature_raw = model.get("temperature", "") or ""
    effort_problem = ""
    try:
        spec = ModelSpec(base_url=model.get("base_url", "") or "",
                         model=model.get("name", "") or "",
                         api_key=model.get("api_key", "") or "",
                         # `vendor` 必须一起传：这一格的读数取自
                         # `spec.redacted()`，不传就等于"盘上写了厂商、机器面说没有"
                         # —— 而面板上那一格的初值正是从这份读数取的。
                         vendor=model.get("vendor", "") or "",
                         reasoning_effort=effort_raw,
                         temperature=temperature_raw)
        effort_shown = spec.redacted()["reasoning_effort"]
        temperature_shown = str(spec.redacted()["temperature"])
    except ValueError as exc:
        # 词表外/区间外的取值：这是"查过了、那格里是坏的"，不是崩溃，也不是"没配"。
        # 所以照旧给出成形的读数，只把这一段判成 unreadable 并把原值原样回显
        # （回显成缺省会让人以为配置生效了）。
        spec = ModelSpec(base_url=model.get("base_url", "") or "",
                         model=model.get("name", "") or "",
                         api_key=model.get("api_key", "") or "",
                         vendor=model.get("vendor", "") or "")
        effort_shown = effort_raw
        temperature_shown = temperature_raw
        effort_problem = f"{type(exc).__name__}: {exc}"
    red = spec.redacted()
    # SETTINGS-RAW 的三格：盘上原样 / 生效值 / 每格来源（形状见 `_settings_cells`）。
    raw_cells, effective_cells, source_cells = _settings_cells(
        raw, red, effort_shown, temperature_shown, sec_cell)
    reading = {
        "path": str(path) if path is not None else "",
        "exists": on_disk,
        "toolchain": {k: tool.get(k, "") for k in TOOLCHAIN_KEYS},
        "model": {"api_key": red["api_key"], "base_url": red["base_url"],
                  "name": red["model"],
                  # 厂商：`type_decls()` 里声明着这一格，读数不给就等于
                  # `types.ts` 的 `SettingsReading.model.vendor` 名存实亡 ——
                  # 面板上那一格的初值取不到（盘上写了也不显示）。
                  # 这是"声明与读数差一格"，两个方向都该由判据管住（见
                  # `tests/test_role_models.py` 的读数那三条）。
                  "vendor": red["vendor"],
                  "reasoning_effort": effort_shown,
                  # 采样温度：这一格与 `spec.temperature` 同源 ——
                  # 盘上没写就是缺省（0.2），写了就是那个数；区间外由上面那一支
                  # 判成 unreadable 并回显原值。
                  "temperature": temperature_shown,
                  # key 是从哪一档取到的（`"env"` / `"settings"` / 空串）。
                  # 所有者裁定"key 从 config 里面接"——
                  # 这一格就是那句话在机器面上的读数：`settings` 才算成立，
                  # `env` 说明有一个环境变量盖住了配置文件（写错了也不会有人发现）。
                  "key_source": key_source(),
                  "configured": spec.configured},
        "workspace": {k: work.get(k, "") for k in WORKSPACE_KEYS},
        # 按角色那一档与秘书那一档：`key_source` 报的是
        # 那份设置文件里 key 的来源，`configured` 是"这一档到底有没有 key"。
        MODELS_SECTION: slots,
        SECRETARY_SECTION: sec_cell,
        # 三样分开放（缺陷 SETTINGS-RAW）：盘上原样 / 生效值 / 每格来源。
        # 页面的输入框只许填 `raw`，`effective` 只进 placeholder；写侧拿 `raw`
        # 判断"这一格到底改没改"。三者同形（段 → 格 → 字符串）。
        "raw": raw_cells,
        "effective": effective_cells,
        "source": source_cells,
        "raw_keys": sorted(raw) if isinstance(raw, dict) else [],
    }
    if effort_problem:
        return reading, TRI_UNREADABLE, ("settings.json 的 model 段有一格不是合法取值"
                                         "（reasoning_effort / temperature）："
                                         + effort_problem)
    reason = ""
    if not on_disk:
        reason = (f"设置文件不在盘上（{path}）：三段全是『没配』这一档，"
                  "而不是『没查成』")
    return reading, (TRI_COMPUTED if on_disk else TRI_NOT_APPLICABLE), reason


def table_archive_reading() -> dict[str, Any]:
    """库表档案：已退役与已登记未启用两档（DATAHYGIENE，2026-11-22）。

    两档都是"这一档今天不该被当成读数读"的机器可读登记面，住在
    `schema.RETIRED_TABLES` / `schema.NOT_ENABLED_TABLES`（单一落点）：
    `eval_results` 已退役（全仓 0 个写点 + 51 个工作区全 0 行 ⇒ 从来没有产出方，
    只留读口会让「没有评测」读成「评测 0 行」）；`reprocess_requests` 未启用
    （写点与消费点都在、闸也在，只是从来没有一条请求真的跑过 ⇒ 0 行是"没启用"，
    不是"全做完了"）。

    这两句话在页面上必须与"0 行"分得开：把 `eval_results` 读成空表、或把
    `reprocess_requests` 的 `unfinished_request_rows=0` 读成"闭环达标"，都是把
    "没有产出方/没启用"折成"做完了" —— 三态纪律要防的正是这一种。

    三态：登记面读不出来 ⇒ `checked=False` + `reason`（不是"没有退役表"）；
    否则两个清单照给（各自空数组 = 盘上没有这一档的登记）。
    """
    from .. import schema as S

    try:
        retired: list[dict[str, Any]] = []
        for name in sorted(S.retired_tables()):
            spec = S.retired_table(name) or {}
            retired.append({"name": name,
                            "file": str(spec.get("file") or ""),
                            "retired_at": str(spec.get("retired_at") or ""),
                            "why": str(spec.get("why") or ""),
                            "how": str(spec.get("how") or "")})
        not_enabled: list[dict[str, Any]] = []
        for name in sorted(S.NOT_ENABLED_TABLES):
            spec = S.NOT_ENABLED_TABLES.get(name) or {}
            not_enabled.append({
                "name": name, "since": str(spec.get("since") or ""),
                "producers": [str(x) for x in (spec.get("producers") or ())],
                "consumers": [str(x) for x in (spec.get("consumers") or ())],
                "evidence": str(spec.get("evidence") or ""),
                "to_enable": str(spec.get("to_enable") or "")})
    except Exception as exc:  # noqa: BLE001 —— 登记面读不出来 = 没查成，不是"没有"
        return {"checked": False, "retired": [], "not_enabled": [],
                "reason": f"schema 的退役/未启用登记面读不出来：{type(exc).__name__}: {exc}"}
    return {"checked": True, "retired": retired, "not_enabled": not_enabled,
            "reason": ""}


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
    # AUDIT F8：这一个服务在服务哪个工作区、以及"换不了"这件事（见 serving_reading）。
    # 放在本机面而不是 `/api/state`：它是"服务进程的事实"，与"工作区里有什么"分处两根轴，
    # 而 `/api/state` 的快照形状是既有公开面（加键要动另一条线的文件）。
    out["serving"] = serving_reading(root)
    # DATAHYGIENE（2026-11-22）：库表档案两档（退役 / 未启用）。它们不是"这个工作区
    # 里有什么"，而是"这一档今天该怎么读" —— 所以放在本机面，与设置/工具链同页，
    # 不塞进产物面（那一面读的是工作区事实）。
    out["tables"] = table_archive_reading()
    out["tri"] = TRI_UNREADABLE if problems else TRI_COMPUTED
    out["reason"] = "；".join(problems)
    return out


# ====================================================================== 7 预算
def serving_reading(root: str | Path) -> dict[str, Any]:
    """这一个服务在服务哪个工作区 —— 以及"换不了"这件事（AUDIT F8 的裁定）。

    ## 为什么是一条「读数」，而不是一个"切换工作区"的入口

    业主的裁定逐字是：先取证页面上有没有切换入口；「没有入口就不要新增功能」，把
    "root 在 `serve()` 钉死"这件事诚实写出来，并加判据"页面不出现假的切换 affordance"。

    取证结论（`temp/webfix3/` 的报告里有逐条 grep）：`ui/src` 里「没有」任何切换工作区的
    按钮 / 下拉 / 链接 —— `main.tsx` 与 `Home.tsx` 只是把 `snapshot.root` 印出来。
    所以这一格给的是四件事实，让页面能如实说出口：

    - `root`：这个服务在服务的那个绝对路径（与 `/api/state.root` 同一个值）；
    - `pinned`：`True` —— 根在 `serve(root=…)` 那一刻定死，「运行期改不了」；
    - `pinned_by`：钉死的那一处（`"serve()"`），让"要改哪里"可查；
    - `switch_how`：真要换工作区时「怎么办」（停服务 + `--root` 重启）；
    - `switch_in_page`：`False` —— 页面「没有」、也不该有切换入口。这一格是判据要的
      "页面不出现假的切换 affordance"的机器读数：它是 API 说的，页面照着说。

    为什么不做成"只读的 `?root=`"（AUDIT 的建议之一）：那会变成"一个页面看多个工作区"，
    而写面仍然绑在起服务时那个根 —— 用户会在 A 工作区的页面上按下写着 B 的按钮。
    半真半假的多工作区比"没有得换"更危险，所以这一批不做（裁定：没有入口就不新增功能）。
    """
    root_p = Path(str(root)).resolve() if str(root or "").strip() else None
    return {
        "root": str(root_p) if root_p is not None else "",
        "pinned": True,
        "pinned_by": "serve()",
        "switch_in_page": False,
        "switch_how": ("工作区根在服务启动那一刻钉死（`serve(root=…)`）。"
                       "要换工作区：停掉这个服务，用 `agentflow --root <另一个工作区> web` "
                       "重启（`--root` 是全局参数，必须写在 `web` 之前）。"
                       "页面不提供切换入口 —— 那会是一个点了没反应的假按钮。"),
    }


def _unattributed_reason(events: Sequence[Mapping[str, Any]],
                         runs: Sequence[Mapping[str, Any]],
                         total: float) -> str:
    """「无人认领」那笔钱的理由：把 `sessions.unattributed_usd_of` 的差额逐档拆开。

    改前这一格只在"会话读不出来"时才有话；读到、而差额又不是 0 时它是一句空串 ——
    页面上于是出现"$0.375630 无人认领"却没有一句为什么（有数没理由）。这里不重算那个
    数，只解释它由哪几档组成（同一批事件、同一套归属规则）：

    - 还没收工的趟：事件求和里有、收工行的自报账没有（按构造全额进差额）；
    - 已收工、但「事件求和 > 自报账」的趟：两者之差；
    - 反过来「自报账 > 事件求和」的趟：负项（会把差额抵小）；
    - 归不到任何一趟的 `llm_call`：两侧都没有它（无台账号 / 在收工行之外）。

    拆出来的四档用盘上的同一批读数复算；它们不改变 `unattributed_usd`。
    """
    def _num(value: Any) -> bool:
        return isinstance(value, (int, float)) and not isinstance(value, bool)

    calls = [e for e in events if str(e.get("kind") or "") == "llm_call"
             and _num(e.get("usd"))]
    event_total = round(sum(float(e["usd"]) for e in calls), 6)
    run_total = round(sum(float(r["usd"]) for r in runs if _num(r.get("usd"))), 6)
    loose = round(event_total - run_total, 6)
    unfinished = [r for r in runs if r.get("end_index") is None]
    unfinished_usd = round(sum(float(r.get("usd") or 0.0) for r in unfinished
                               if _num(r.get("usd"))), 6)
    over = [r for r in runs if r.get("end_index") is not None
            and _num(r.get("usd")) and _num(r.get("spend_usd"))
            and float(r["usd"]) > float(r["spend_usd"]) + 1e-9]
    over_usd = round(sum(float(r["usd"]) - float(r["spend_usd"]) for r in over), 6)
    under = [r for r in runs if r.get("end_index") is not None
             and _num(r.get("usd")) and _num(r.get("spend_usd"))
             and float(r["spend_usd"]) > float(r["usd"]) + 1e-9]
    under_usd = round(sum(float(r["spend_usd"]) - float(r["usd"]) for r in under), 6)
    bits: list[str] = []
    if unfinished_usd:
        bits.append(f"未收工的 {len(unfinished)} 趟 ${unfinished_usd:.6f}"
                    "（没有收工行 ⇒ 没有自报账，不是花 0）")
    if over_usd:
        bits.append(f"已收工、但事件求和大于自报账的 {len(over)} 趟 ${over_usd:.6f}")
    if loose > 1e-6:
        bits.append(f"归不到任何一趟的 ${loose:.6f}（在收工行之外 / 无台账号的调用）")
    if under_usd:
        bits.append(f"抵减：自报账大于事件求和的 {len(under)} 趟 ${under_usd:.6f}")
    body = "、".join(bits) or "各档在舍入范围内抵平"
    spend_total = round(sum(float(r["spend_usd"]) for r in runs
                            if _num(r.get("spend_usd"))), 6)
    return (f"事件求和 ${event_total:.6f} − 各趟自报账合计 ${spend_total:.6f} "
            f"= ${float(total):.6f}：{body}。这是会话口径的差（不是账本行），"
            "它不进任何一趟的 `usd`。")


def _budget_panel_note(snap: Mapping[str, Any]) -> str:
    """预算面板这一格的人话：只回答钱，不替收工门回答「东西写没写」。

    为什么不再直接印 `budget.paperwork_first_reading()` 的 `note`：那一句是收工门的
    拒信语境（"这一格缺的是「没写」，不是「写不起」"指收工必需物），而这一页是预算
    读数页。预算寄存器写没写、上限设没设，与"验收表写没写"是两件事 —— 把它们接在同一
    句里，读的人会把"寄存器在盘上、预算已写"读成"这一趟缺东西"（真机 2026-11-24 的
    读数：`exists=true` / `added_count=1`，而 `note` 仍说"缺的是没写"）。
    收工门那一句仍原样保留在 `closing_note`（只在收工时用）。
    """
    spent = snap.get("spent_usd")
    total = snap.get("total_usd")
    remaining = snap.get("remaining_usd")
    reserve = snap.get("reserve_usd")

    def _usd(value: Any) -> str:
        return f"${float(value):.6f}" if isinstance(value, (int, float)) else "（没读到）"

    head = "预算读数（不是硬闸）："
    if remaining is None:
        return (head + f"已花 {_usd(spent)} / 上限 {_usd(total)}；剩余算不出来"
                "（没设过上限 / 账本读不出）—— 「算不出来」不等于「还剩很多」。"
                "这一句只回答钱；收工必需物写没写是收工门的问题（那一句在 `closing_note`）。")
    below = snap.get("below_reserve")
    line = (head + f"已花 {_usd(spent)} / 上限 {_usd(total)} / 还剩 {_usd(remaining)}；"
            f"收工储备线 {_usd(reserve)}（")
    line += ("余量已低于收工储备线" if below else "余量还在收工储备线之上") + "）。"
    return (line + "这一句只回答钱：收工必需物写没写是收工门的问题"
            "（那一句收在 `closing_note`，本页不替它下结论）。")


def budget_face(root: str | Path) -> dict[str, Any]:
    """`GET /api/budget` 的读模型：总额度 / 已花 / 剩余 / 追加历史 + 两个归口。

    两件事刻意来自两个地方（`budget` 模块的 docstring 逐字）：

    - 总额度来自盘上的寄存器（`<工作区>/budget.json`，`budget.reading`）；
    - 已花永远来自 `usage_ledger`（`TokenMeter.spent()`/`by_role()`/`by_scope()`）——
      寄存器里不记花销，两处记账必然漂移。

    三态：账本读不出来 ⇒ `spent_tri="unreadable"` 且 `spent_usd=None`
    （不是 0 —— "没查成"与"一分钱没花"在本仓是两个词）；账本「不在盘上」（还没写过）
    ⇒ `spent_tri="not_applicable"` + `spent_reason`（READFIX-D-6：改前这一档折成
    `spent_tri=computed`、`entries=0`、`spent.usd=0.0`，于是"还没写过"被印成"花了 0"）。
    寄存器读不出来 ⇒ `tri="unreadable"` + `problem` 原样带出（`budget.reading` 那一档
    已经这么做了，这一层只透传，不二次判断）。寄存器不在盘上 ⇒ `not_applicable`
    （还没设过预算，合法初态），而不是"没查成"。

    ## 储备线与"为什么停了"（2026-11-19 对齐）

    这一格用 `budget.paperwork_first_reading()` 而不是 `reading()`：前者在完全相同的
    那批键之外多给 `reserve_usd` / `below_reserve` / `note` / `paperwork_first_rule`
    （真实现在 `budget.py`，本层不另写一份阈值）。为什么必须给：M 自己按 $1.00
    收工储备线叫停时（`stopctl` 的口径），页面上只剩"剩余 1.32"这一个数 ——
    "为什么停"看不见。

    但那一份 `note` 是收工门拒信的语境（"这一格缺的是「没写」，不是「写不起」"
    说的是收工必需物），不是预算页的读数。2026-11-24 的现场：`budget.json` 在盘上、
    `added_count=1`、上限已设，而面板上的 `note` 仍在说"缺的是没写" —— 模板套错档。
    所以在这一层分两格：`closing_note` 逐字保留收工门那一句（前缀写明"收工门口径"），
    `note` 换成只回答钱的那一句（`_budget_panel_note`）。

    ## 无人认领那笔钱（会话口径）

    `unattributed_usd` 与 `/api/state` 的 `sessions[].unattributed_usd`、
    收工面 `closing.cost.unattributed_usd` 是同一个函数算的
    （`sessions.unattributed_usd_of`）：事件流里归不到任何一趟的那些
    `llm_call.usd`。会话读不出来 ⇒ `None` + `unattributed_reason`（不是 0）。
    读到而差额不是 0 时，`unattributed_reason` 由 `_unattributed_reason` 逐档拆开
    （未收工的趟 / 事件求和大于自报账的趟 / 归不到任何一趟的调用 / 抵减项）——
    有数就必须有理由；0 元不需要理由，所以那一档是空串。

    ## 账本行不是 llm_call 总数

    `entries` 是 `usage_ledger` 的行数；`by_scope` 把它按 `schema.USAGE_SCOPES`
    六档加 `unclassified` 拆开（真机 lp-ball-10：reason 1200 + summon 55 +
    extract 0 = 1255 行）。一次模型调用可能记 0..n 行（重试另记 `attempts`），
    所以"行数"与"调用次数"是两个数，页面不许互相顶替。
    """
    from .. import budget as B
    from ..store import Store
    from ..tokenmeter import TokenMeter

    root_p = Path(str(root))
    spent: dict[str, Any] = {}
    by_role: dict[str, Any] = {}
    by_scope: dict[str, Any] = {}
    spent_problem = ""
    spent_tri = TRI_NOT_APPLICABLE
    unknown_usd_rows: int | None = None
    try:
        store = Store(root_p)
        rows, spent_tri = _table_state(store, "usage_ledger")
        if spent_tri == TRI_COMPUTED:
            meter = TokenMeter(store)
            spent = dict(meter.spent() or {})
            by_role = dict(meter.by_role() or {})
            by_scope = dict(meter.by_scope() or {})
            # 算不出价钱的行数（`usd` 不是数字）：改前页面把 `unknownCalls` 写死成 0，
            # 于是"有几次算不出价钱"被印成"一次都没有"（READFIX-D-13）。
            unknown_usd_rows = sum(
                1 for row in rows
                if not isinstance(row.get("usd"), (int, float))
                or isinstance(row.get("usd"), bool))
        elif spent_tri == TRI_NOT_APPLICABLE:
            spent_problem = ("usage_ledger 不在盘上（还没写过）⇒ 已花那一格记 "
                             "not_applicable，不是 0：这个工作区还没有花钱的账本")
        else:  # TRI_UNREADABLE
            spent_problem = ("usage_ledger 读不出来（坏 JSON / 坏表）⇒ 已花那一格记 "
                             "unreadable，不是 0")
    except Exception as exc:  # noqa: BLE001 - 读数层：读不到就如实说没查成
        spent_tri = TRI_UNREADABLE
        spent = {}
        by_role, by_scope = {}, {}
        spent_problem = (f"usage_ledger 读不出来：{type(exc).__name__}: {exc}"
                         "（已花那一栏记「没查成」，不记 0）")
    snap = B.paperwork_first_reading(root_p,
                                     spent_usd=(float(spent["usd"])
                                                if spent_tri == TRI_COMPUTED and spent
                                                else None))
    # 无人认领的那笔钱按会话口径算（与 `/api/state` 的 `sessions[].unattributed_usd`
    # 和收工面 `closing.cost.unattributed_usd` 同一个函数：`sessions.unattributed_usd_of`）。
    # 为什么这一页也要给：预算页是"钱"的唯一落点，"账本说花了多少"与"会话说花了多少、
    # 其中多少没有任何一趟认领"必须并排 —— 只给账本那一半，读的人会把
    # "已花 3.676321" 读成"每一笔都有主"。
    unattributed: float | None = None
    unattributed_problem = ""
    unattributed_runs: list[dict[str, Any]] = []
    unattributed_events: list[dict[str, Any]] = []
    try:
        records, info = SS.read_all_sessions(root_p)
        if info.get("checked"):
            unattributed_runs = SS.runs_in_session(records)
            unattributed_events = records
            unattributed = SS.unattributed_usd_of(records, unattributed_runs)
        else:
            unattributed_problem = (f"会话读不出来（{info.get('reason') or '没查成'}）"
                                    "⇒ 无人认领那笔钱算不出来（不是 0）")
    except Exception as exc:  # noqa: BLE001 - 读数层：读不到就如实说没查成
        unattributed_problem = (f"会话读不出来（{type(exc).__name__}: {exc}）"
                                "⇒ 无人认领那笔钱算不出来（不是 0）")
    if (unattributed is not None and not unattributed_problem
            and abs(float(unattributed)) > 1e-9):
        # 有数就必须有理由：0 元不需要理由（0 是"每一分都被认领了"的读数）；
        # 非 0 时把差额逐档拆开（同一批会话事件，同一套归属规则 —— 这里只解释
        # `sessions.unattributed_usd_of` 那个数怎么来的）。
        unattributed_problem = _unattributed_reason(
            unattributed_events, unattributed_runs, float(unattributed))
    snap.update({
        "spent_tri": spent_tri,
        "spent_reason": spent_problem,
        "entries": (int(spent.get("entries") or 0)
                    if spent_tri == TRI_COMPUTED else None),
        "tokens": (int(spent.get("tokens") or 0)
                   if spent_tri == TRI_COMPUTED else None),
        "attempts": (int(spent.get("attempts") or 0)
                     if spent_tri == TRI_COMPUTED else None),
        # 算不出价钱的行数：读不到账本 ⇒ null（不是 0）；读到 ⇒ 真数字。
        "spent_unknown_usd_calls": unknown_usd_rows,
        "added_count": len(snap.get("added") or []),
        "by_role": by_role,
        "by_scope": by_scope,
        # 无人认领（会话口径）：事件流里归不到任何一趟的那些 `llm_call.usd`。
        # 三态：会话读不出来 ⇒ `None` + `unattributed_reason`，不折成 0。
        "unattributed_usd": unattributed,
        "unattributed_reason": unattributed_problem,
        "unattributed_source": "sessions.unattributed_usd_of（会话口径）",
    })
    if spent_tri == TRI_UNREADABLE and snap.get("tri") != TRI_UNREADABLE:
        snap["tri"] = TRI_UNREADABLE
        snap["reason"] = "；".join(x for x in (str(snap.get("reason") or ""),
                                               spent_problem) if x)
    # ③ 模板套错档：`paperwork_first_reading` 的 `note` 是收工门拒信那一档
    # （"缺的是「没写」，不是「写不起」"指收工必需物），不是预算页的读数。原句移到
    # `closing_note`（只在收工时用），本页 `note` 换成只回答钱的那一句。
    snap["closing_note"] = ("（收工门口径，只在问「收工必需物该不该先落盘」时用）"
                            + str(snap.get("note") or ""))
    snap["note"] = _budget_panel_note(snap)
    return snap


# ====================================================================== 8 在飞
def _tasks_running_of(root: Path) -> tuple[int | None, str, str]:
    """`tasks` 台账里 `status == "running"` 的行数 + 三态 + 原因。

    为什么只数 `running`（不数 `pending`）：业主的口径逐字是
    「在飞（tasks 里 running）」；`pending` 是「未收口的活」（`Roster.tsx` 已经把它
    单列成"未收口的活 N 件"），把它并进「在飞」会让 82 这种收工现场读出 90。

    为什么与名册三态同源：名册那一格的 `flying` 也是从 `tasks` 的 `status` 派生
    （`conductor.agent_state` 的 ⑥），两处读的是同一本台账、同一列状态 ——
    这一格只少了"挂机（parked）不算在飞"那一层细分，所以页面把它逐字标成
    「tasks 里 running」，不与名册卡上那个 `flying` 混用同一个名字。

    返回 `(行数, tri, 原因)`（READFIX-D-2：改前只回 `(None, 原因)`，调用方于是
    分不清"台账坏了"与"还没写过"，而两种都只能靠 `reason` 那一句兜底 —— 面级
    `tri` 仍是 computed）：
    - 台账读不出来 ⇒ `(None, "unreadable", 原因)`（"没查成"，不是 0）；
    - 台账不在盘上（还没写过）⇒ `(None, "not_applicable", 原因)`（也不是 0）；
    - 读到了 ⇒ `(真数字, "computed", "")`。
    """
    from ..store import Store

    try:
        rows, tri = _table_state(Store(root), "tasks")
    except Exception as exc:  # noqa: BLE001 - 读不到就是没查成，不折成 0
        return None, TRI_UNREADABLE, (
            f"tasks 台账读不出来（「在飞」那一格记「没查成」，不记 0）："
            f"{type(exc).__name__}: {exc}")
    if tri == TRI_NOT_APPLICABLE:
        return None, TRI_NOT_APPLICABLE, (
            "tasks 台账不在盘上（还没写过；「在飞」那一格是「读不到」，不是 0）")
    return (sum(1 for row in rows if str(row.get("status") or "") == "running"),
            TRI_COMPUTED, "")


def _stale_loops_of(root: Path, running: Sequence[dict[str, Any]]) -> tuple[list[str], str]:
    """给 `stopctl.running_loops().running[]` 的每一行补 `stale_loop`（就地写）。

    `running` 的行按定义都是"有 start 没 end"（`stopctl.running_loops` 只列这种），
    所以这里只需判「这场会话的顶趟收没收到 end」：顶趟已收尾 ⇒ 这些行是"被打断后
    剩下的循环记录"（宿主进程走了 / 被父叫停），不是活着的循环。判据与
    `webui.state.mark_stale_loops` 同一处（`top_run_closed`），两台读口不会各说一套。

    读不出来 ⇒ `stale_loop=False` 并把原因带回（保守方向：不替它宣布"死了" ——
    读不到只说"判不了"，不许折成"不是活着"）。返回 `(问题, 说明)`。
    """
    problems: list[str] = []
    notes: list[str] = []
    stale_by_sid: dict[str, bool] = {}
    for row in running:
        sid = str(row.get("sid") or "")
        if sid and sid not in stale_by_sid:
            try:
                events, bad = SS.read_session(root, sid=sid)
                if bad:
                    notes.append(f"{sid} 的会话有坏行 ⇒ 顶趟有没有收尾判不了"
                                 "（这些行留在「未收尾」，不替它们宣布死亡）")
                    stale_by_sid[sid] = False
                else:
                    stale_by_sid[sid] = bool(_state.top_run_closed(
                        SS.runs_in_session(events, sid=sid)))
            except Exception as exc:  # noqa: BLE001
                stale_by_sid[sid] = False
                problems.append(f"判 {sid} 的顶趟有没有收尾时读盘失败："
                                f"{type(exc).__name__}: {exc}")
        row["stale_loop"] = bool(stale_by_sid.get(sid, False))
    return problems, "；".join(notes)


def live_face(root: str | Path) -> dict[str, Any]:
    """`GET /api/live` 的读模型：未收尾的循环 + 活进程 + 停机开关 + 近几条停机历史。

    ## 两个数必须分开读（82 的定格数据）

    这一面若只给 `running`（"有 start 没 end 的循环记录"）与 `answer`（"有/没有"），
    页面就会把前者叫成「在飞」。82 上于是出现两个都"对"、合起来是假的读数：
    名册三态合计「在飞 0」，而循环表列着 2 行 D（20:38:22 / 20:38:23）并写着"结论：有"。
    那 2 行是被父叫停打断的循环记录，宿主进程已退出 —— 它们不是活着的。

    所以这一面现在给两个并列的数：

    - `tasks_running`：`tasks` 台账里 `status == "running"` 的行数（读不到 / 还没写过
      ⇒ `null` + `reason` 里说清是哪一档）—— 这才是「在飞」，与名册三态同源；
    - `unclosed_loops`：「未收尾的循环总数」 = `unclosed_running + unclosed_stale`
      （READFIX-A：改前它只数 `running`，把 `stopctl.running_loops().stale_rows`
      整批丢掉 ⇒ 真机 17 个 start − 10 个 end = 7 条未收尾，端点却回 0）；
    - `unclosed_running` / `unclosed_stale`：总数拆成两档 —— 前者是"还可能在跑"
      （`running` 且 `stale_loop=false`），后者是"已经不在跑"（宿主进程已死、
      或顶趟已收尾的循环记录）。两档分开，页面才不必用一句话既说"没在跑"又说"没这回事"。

    每一行还带一格 `stale_loop`（判据同 `webui.state.mark_stale_loops`）：顶趟已收尾
    ⇒ `true`，页面据此在行尾写"宿主进程已退出/被叫停，不是活着"。`stale_rows` 整栏
    逐字透传 `stopctl`（它已经带 `why`）并同样标 `stale_loop=true`。`answer` 也不再
    被这种行顶成「有」：只剩 stale 行、又没有活进程 ⇒ `answer="没有"`。

    行一律用 `stopctl` 自己的字典逐字透传（`running` / `stale_rows` / `live` / 历史行）：
    在这一层再抄一份字段表就是第二份形状定义，必然与那边漂移。

    ## 「进程面」说的是哪个进程（2026-11-24）

    `live[]` 的 `pid` 来自 `stopctl.register_pid` —— 它写的是父进程自己（宿主进程），
    而同一趟 run 里的多个角色是那个进程里的线程（`stopctl` 的 `running_loops` 里那句
    "子循环跑在父进程里（线程），它们没有各自的 pid 登记"）。所以多行会印同一个号。
    每一行因此带 `host_process=True` 与 `pid_note`，面级 `live_note` 把这层话写成一句
    可复算的读数：进程面证明的是"宿主还在"，不是"这一行是独立进程"。
    """
    from .. import stopctl as SC

    root_p = Path(str(root))
    problems: list[str] = []
    notes: list[str] = []
    loops: dict[str, Any] = {"running": [], "live": [], "unreadable_sessions": [],
                             "stale_rows": [], "answer": "没查成"}
    loops_ok = False
    try:
        got = SC.running_loops(root_p)
        loops = dict(got) if isinstance(got, Mapping) else loops
        loops_ok = isinstance(got, Mapping)
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
    running = [dict(r) for r in (loops.get("running") or [])]
    stale_problems, stale_note = _stale_loops_of(root_p, running)
    problems.extend(stale_problems)
    if stale_note:
        notes.append(stale_note)
    # `stopctl` 已经把"登记的进程已经不在"的那批单列在 `stale_rows` 里（带 why）。
    # 改前这一整个列表被丢掉，于是 7 条未收尾循环在 `/api/live` 上读成 0。
    stale_rows = [dict(r) for r in (loops.get("stale_rows") or [])]
    for row in stale_rows:
        # 这一栏的定义就是"不是在飞"（进程已死 / 被强杀），行尾按 `stale_loop` 分档；
        # 标成 True 才不会在页面上被画成"顶趟还在跑"。
        row["stale_loop"] = True
    live_rows = [dict(r) for r in (loops.get("live") or [])]
    # 进程面这一档要说清是"哪个进程"的号：`register_pid` 写的是父进程自己，
    # 同一趟 run 里的角色是同一进程里的线程 ⇒ 多行共用一个号（是事实，不是缺陷）。
    host_pids = sorted({
        int(row["pid"]) for row in live_rows
        if isinstance(row.get("pid"), int) and not isinstance(row.get("pid"), bool)})
    for row in live_rows:
        row["host_process"] = True
        row["pid_note"] = ("宿主进程 pid：登记它的那个 `python -m agentflow` 的进程号，"
                           "不是这一行自己的 pid（同一趟 run 里的角色是同一进程里的线程）")
    live_note = ""
    if live_rows:
        live_note = (f"进程面 {len(live_rows)} 行共用 {len(host_pids)} 个宿主进程 pid："
                     "`stopctl.register_pid` 登记的是父进程自己，同一趟 run 里的角色都在"
                     "同一个 `python -m agentflow` 进程里跑 ⇒ 同一个号出现在多行不代表它们"
                     "是同一个代理，也不代表每一行是独立进程。判「谁在跑」看 role + sid。")
    tasks_running, tasks_tri, tasks_note = _tasks_running_of(root_p)
    if tasks_note:
        notes.append(tasks_note)
    if tasks_tri == TRI_UNREADABLE:
        problems.append(tasks_note)
    # 「还可能在跑」= stopctl 的 `running` 里没被判成 stale 的那些；其余（stale_rows
    # + running 里 stale_loop=true 的）都归"已经不在跑"那一档。总数 = 两档之和。
    unclosed_running = (sum(1 for row in running if not row.get("stale_loop"))
                        if loops_ok else None)
    unclosed_stale = (sum(1 for row in running if row.get("stale_loop"))
                      + len(stale_rows)) if loops_ok else None
    unclosed_total = ((unclosed_running + unclosed_stale)
                      if unclosed_running is not None and unclosed_stale is not None
                      else None)
    answer = str(loops.get("answer") or "")
    if (answer == "有" and running and not live_rows
            and all(row.get("stale_loop") for row in running)):
        # 只有"没收到 end"的循环记录、且没有活进程 ⇒ 那不是"有人在跑"。
        # 纪律：不许把"没收到 end"说成"还在跑"（82 那 2 行就是这一档）。
        answer = "没有"
        notes.append("没有活进程；循环表里的行都是未收尾的循环记录（顶趟已收尾）"
                     "⇒ 「有/没有」读成「没有」")
    return {
        "tri": TRI_UNREADABLE if problems else TRI_COMPUTED,
        "reason": "；".join(problems + notes),
        "root": str(root_p),
        "answer": answer,
        "tasks_running": tasks_running,
        # 面级 tri 之外另给这一格的三态（READFIX-D-2）：tasks.json 坏 ⇒ face=unreadable；
        # 还没写过 ⇒ face 仍 computed，但这一格是 `not_applicable` + `tasks_running_why`。
        "tasks_running_tri": tasks_tri,
        "tasks_running_why": tasks_note,
        "unclosed_loops": unclosed_total,
        "unclosed_running": unclosed_running,
        "unclosed_stale": unclosed_stale,
        "unclosed_loops_tri": TRI_COMPUTED if loops_ok else TRI_UNREADABLE,
        "unclosed_loops_why": ("" if loops_ok else
                               "stopctl.running_loops 读不出来 ⇒ 未收尾循环记「没查成」，不记 0"),
        "running": running,
        "stale_rows": stale_rows,
        "live": live_rows,
        "live_note": live_note,
        "unreadable_sessions": list(loops.get("unreadable_sessions") or []),
        "switch": switch,
        "switch_present": bool(switch.get("present") or switch.get("path")),
        "history": history,
        "interrupts": interrupts,
    }


# ====================================================================== 8b 义务与板项
#: 四族义务：`(族名, 幂等键前缀, 负责人角色, 一句话)`。前缀的真身在
#: `obligations`（`REGISTER_PREFIX` / `RESUBMIT_PREFIX` / `REGISTER_WAKE_PREFIX` /
#: `HANDOFF_PREFIX`），本层不另写一份字面量 —— 那一份漂了，页面会显示一族不存在的义务。
#:
#: 第四族 `d-handoff` 是 2026-11-24 补的：E 把一条「有数值支持、还没证明」的猜想落成
#: `supported_not_proved` 时，`obligations.ensure_handoff` 为 D 开一条待递交义务
#: （`d-handoff@<猜想号>`，收口是 B 收录 / 猜想被推翻 / 命题被放弃）。这一族此前不在
#: 这张表里 ⇒ `/api/obligations` 的 `families` 只有三族，面板上看不见「今天新增的
#: 待递交」。空的时候也必须列出（0 是读数，「缺族」不是）。
def _obligation_families() -> tuple[tuple[str, str, str, str], ...]:
    from .. import obligations as OB

    return (
        ("b-register", OB.REGISTER_PREFIX, OB.REGISTER_ROLE,
         "签了但没人收录（收口：命题出现正文且 reviewed=true）"),
        ("v-resubmit", OB.RESUBMIT_PREFIX, "V",
         "审稿要求重送（收口：重送那一版落地并拿到新签）"),
        ("b-awake", OB.REGISTER_WAKE_PREFIX, OB.REGISTER_ROLE,
         "签落地后叫醒 B（召唤行；它本身不是义务，是「叫过没有」的读数）"),
        ("d-handoff", OB.HANDOFF_PREFIX, OB.HANDOFF_ROLE,
         "猜想要递给 B（收口：B 收录成功 / 猜想被推翻 / 命题被放弃；这一族没有召唤行，"
         "`summoned` 恒为 0，不是没叫醒）"),
    )


def _handoff_reading(store: Any) -> dict[str, Any]:
    """「待递交」义务（`d-handoff@`）的一眼读数：`obligations.d_handoff_reading` 的读数。

    ## 为什么要在这里借一个只读主控

    `d_handoff_reading` 的口径是"板上"：它先按 `conductor._board_rows()` 取项，再逐条
    用 `handoff_gap` 对着 `conjectures` / `statements` 判收口。而
    `obligations._conductor` 只认 `tools.conductor_tools.cached_conductor` —— "绝不顺手
    建一个"：运行进程里建歪了，会让后来接线的那个运行复用一个空壳。

    `web` 是另一个进程：那里面没有在飞的运行，也就没有已接线的主控。所以这一层
    借一个只读主控（`conductor_for`），用完把缓存恢复成进来那一档 —— 同进程里别人
    已经建过的那一个不动它。构造不写盘（判据
    `test_webui_batch1_readings.py::test_building_the_read_conductor_writes_nothing` 钉着）。

    构造抛 / 读不出来 ⇒ 原样返回 `checked=False` 的读数，由调用方说"没查成"（不许把它
    折成"板上 0 条"）。
    """
    from .. import obligations as OB
    from ..tools import conductor_tools as CT

    key = str(Path(str(getattr(store, "root", ""))).resolve())
    held = CT._CONDUCTORS.get(key)
    try:
        if held is None:
            CT.conductor_for(store)
        got = OB.d_handoff_reading(store)
    except Exception as exc:  # noqa: BLE001 —— 读不成是"没查成"，不是"没有待递交"
        return {"checked": False, "open": 0, "unowned": 0, "rows": [], "problems": [],
                "reason": (f"d_handoff_reading 没跑成（{type(exc).__name__}: {exc}）"
                           "⇒ 这一族的逐条读数没查成，不是「板上 0 条」")}
    finally:
        if held is None:
            CT._CONDUCTORS.pop(key, None)
    return dict(got) if isinstance(got, Mapping) else {
        "checked": False, "open": 0, "unowned": 0, "rows": [], "problems": [],
        "reason": "d_handoff_reading 没有返回读数（不是「没有待递交义务」）"}


def obligations_face(root: str | Path, store: Any = None) -> dict[str, Any]:
    """`GET /api/obligations` 的读模型：板上四族义务的收件人读数。

    为什么要有这一条：名册的收件箱按 `parent_task_id`（父台账号）分，而一条板项
    可以只带收件实例（`Task.instance`，`conductor.open_item(recipient_instance=…)`
    写进去的那一格）—— 父为空的项不挂在任何人的收件箱上，页面就看不见它，
    真机 lp-ball 的两条 `b-register@` 至今如此。这一面把"投给谁"与"谁是父"
    两条轴分开摆出来，让"没人收"变成一句看得见的读数。

    ## 两条轴（不许折成一句"有没有收件人"）

    - `recipient_instance`：板项行的 `instance` 列。它的值由
      `obligations.recipient_reading` 判（调用方点名 > 命题登记实例 > 角色地址），
      写进板项行之后就是事实；`Conductor.open_items_for(role, instance)` 正是按
      这一列取件（`instance` 相等，或 `instance` 为空且 `role` 相等）。
    - `parent_task_id`：父台账号（`open_items_of` 那一轴，名册收件箱用它）。
    两轴都空 ⇒ `addressed="unowned"`（板上的孤儿项，等主控派人）。

    ## 第四族 `d-handoff` 的计数从哪来

    前三族的 `open` / `unowned` 是这张表扫出来的（板项行按前缀归族）。`d-handoff`
    那一族另有一份唯一读数 `obligations.d_handoff_reading()`（它逐条对 `conjectures` /
    `statements` 判 gap / eligible / statement_id），所以这一族的 `open` / `unowned`
    以那份读数为准；同时拿它和台账扫出来的行数对账 —— 两个读法对不上就点名（同一块板
    的两个读法不一致，必须先查清差在哪）。那份读数没跑成时，行数照给（同一块
    `tasks` 板，不是 0），但这一族带 `tri="unreadable"` + `reason`，说明逐条的
    gap / eligible 没有。

    ## 三态

    表不在盘上 ⇒ `tri="not_applicable"` + 理由（这个工作区还没有板项，是事实）；
    表读不出来 ⇒ `tri="unreadable"` + `problems`；读到了 ⇒ `computed`（哪怕 0 行）。

    ## 只读

    本函数不写盘、不开项、不销号：销号只发生在 `conductor.open_item` / 收口那一路。
    """
    from .. import obligations as OB

    root_p = Path(str(root))
    try:
        if store is None:
            from ..store import Store

            store = Store(root_p)
        rows, tasks_tri = _table_state(store, "tasks")
    except Exception as exc:  # noqa: BLE001 —— 读不到就是没查成（不是"没有义务"）
        return {"tri": TRI_UNREADABLE,
                "reason": f"tasks 台账读不出来：{type(exc).__name__}: {exc}",
                "source": _src("data/tasks.json", label="板项"),
                "checked": False, "families": [], "rows": [], "counts": {},
                "recipient_rule": "", "addressing": {"by_instance": {},
                                                     "by_role": {}, "unowned": 0},
                "problems": [f"{type(exc).__name__}: {exc}"]}
    if tasks_tri == TRI_NOT_APPLICABLE:
        return {"tri": TRI_NOT_APPLICABLE,
                "reason": "还没有这张表：data/tasks.json 不在盘上（这个工作区还没开过项）",
                "source": _src("data/tasks.json", label="板项"),
                "checked": True, "families": [], "rows": [], "counts": {},
                "recipient_rule": "", "addressing": {"by_instance": {},
                                                     "by_role": {}, "unowned": 0},
                "problems": []}
    awake_prefix = next(pre for name, pre, _role, _why in _obligation_families()
                        if name == "b-awake")
    #: 叫醒行的落点：`{input_key: task_id}`（只看还开着的召唤行）。
    wakes: dict[str, str] = {}
    for row in rows:
        key = str(row.get("input_key") or "")
        if key.startswith(awake_prefix) and str(row.get("item_state") or "") != "done":
            wakes.setdefault(key, str(row.get("task_id") or ""))
    families: dict[str, dict[str, Any]] = {
        name: {"name": name, "role": role, "why": why,
               "prefix": pre, "open": 0, "unowned": 0, "summoned": 0,
               "instances": [], "tri": TRI_COMPUTED, "reason": ""}
        for name, pre, role, why in _obligation_families()
    }
    detail_rows: list[dict[str, Any]] = []
    by_instance: dict[str, int] = {}
    by_role: dict[str, int] = {}
    unowned = 0
    for row in rows:
        key = str(row.get("input_key") or "")
        family = next((name for name, pre, _role, _why in _obligation_families()
                       if key.startswith(pre)), "")
        if not family:
            continue
        if str(row.get("item_state") or "") == "done":
            continue
        fam = families[family]
        fam["open"] = int(fam["open"]) + 1
        role = str(row.get("role") or fam["role"])
        instance = str(row.get("instance") or "")
        parent = str(row.get("parent_task_id") or "")
        if not parent and not instance:
            fam["unowned"] = int(fam["unowned"]) + 1
            unowned += 1
        if instance:
            fam["instances"] = sorted({*fam["instances"], instance})
            by_instance[instance] = by_instance.get(instance, 0) + 1
        else:
            by_role[role] = by_role.get(role, 0) + 1
        wake_key = ""
        if family == "b-register":
            sha = OB.register_sha_of(key)
            label = key[len(OB.REGISTER_PREFIX):].partition("@")[0]
            wake_key = OB.register_wake_key(f"{label}#p1", sha)
            if wakes.get(wake_key):
                fam["summoned"] = int(fam["summoned"]) + 1
        detail_rows.append({
            "task_id": str(row.get("task_id") or ""),
            "key": key,
            "family": family,
            "role": role,
            "recipient_instance": instance,
            "parent_task_id": parent,
            "item_state": str(row.get("item_state") or ""),
            "item_close": str(row.get("item_close") or ""),
            "opened_at": str(row.get("started_at") or ""),
            "wake_task_id": wakes.get(wake_key, "") if wake_key else "",
            "addressed": ("instance" if instance else
                          ("parent" if parent else "unowned")),
            "detail": str(row.get("detail") or "")[:200],
        })
    counts = {name: {"open": f["open"], "unowned": f["unowned"],
                     "summoned": f["summoned"]} for name, f in families.items()}
    problems: list[str] = []
    #: 第四族：`open` / `unowned` 以 `obligations.d_handoff_reading()` 为准（那才是这一族
    #: 的唯一读数；台账扫出来的行数是它的第二读法，只用来对账）。
    handoff = _handoff_reading(store)
    fam = families.get("d-handoff")
    if fam is not None:
        if handoff.get("checked"):
            read_open = int(handoff.get("open") or 0)
            read_unowned = int(handoff.get("unowned") or 0)
            if (read_open != int(fam["open"])
                    or read_unowned != int(fam["unowned"])):
                problems.append(
                    "d_handoff_reading 与板项行数对不上：读数 "
                    f"open={read_open}/unowned={read_unowned}，台账扫出来 "
                    f"open={fam['open']}/unowned={fam['unowned']}"
                    "（同一块板的两个读法，差在哪要先查清）")
            fam["open"], fam["unowned"] = read_open, read_unowned
            fam["instances"] = sorted({
                str(one.get("owner_instance") or "")
                for one in (handoff.get("rows") or [])
                if str(one.get("owner_instance") or "")})
            fam["tri"], fam["reason"] = TRI_COMPUTED, ""
        else:
            # 三态：这份读数没跑成 ≠ 这一族 0 条。行数照给（同一块 tasks 板），
            # 但逐条的 gap / eligible 没有 —— 理由必须能被读到。
            fam["tri"] = TRI_UNREADABLE
            fam["reason"] = (str(handoff.get("reason") or "d_handoff_reading 没跑成")
                             + "；open/unowned 是 tasks 板项行的行数（同一块板），"
                               "逐条的 gap / eligible 没有")
            problems.append(f"d-handoff：{fam['reason']}")
        problems.extend(str(x) for x in (handoff.get("problems") or []))
        counts["d-handoff"] = {"open": fam["open"], "unowned": fam["unowned"],
                               "summoned": fam["summoned"]}
    fam_reasons = [f"{n}：{f['reason']}" for n, f in families.items() if f["reason"]]
    counts_text = "；".join(f"{n}：开 {c['open']}（没人收 {c['unowned']}）"
                           for n, c in counts.items() if c["open"])
    reason = "；".join(x for x in (counts_text, *fam_reasons) if x)
    return {
        "tri": TRI_COMPUTED,
        "reason": reason,
        "source": _src("data/tasks.json", label="板项"),
        "checked": True,
        "families": [families[name] for name in families],
        "rows": detail_rows,
        "counts": counts,
        "recipient_rule": ("收件实例 = 板项行的 `instance` 列（`conductor.open_item` 的 "
                           "`recipient_instance`，其值由 `obligations.recipient_reading` "
                           "判：调用方点名 > 命题登记实例 > 角色地址）；父台账号看 "
                           "`parent_task_id`（名册收件箱那一轴）。两轴都空 = 没人收。"),
        "addressing": {"by_instance": by_instance, "by_role": by_role,
                       "unowned": unowned},
        "problems": problems,
    }


# ====================================================================== 8c 错误面的补注
def annotate_errors_readout(face: Mapping[str, Any]) -> dict[str, Any]:
    """`/api/errors` 的补注：把 `unclassified_signal` 那条说明改成读得懂、能照做的一句。

    ## 为什么只改 detail，不改计数

    错误计数的口径与类目真身都在 `errorstats`（CLI 的 `errors` 与 `/api/errors` 读同一个
    `readouts.errors_readout`）。网页这一层若自己把某条原话映射成类目，`/api/errors`
    的 `total` 就会与 CLI 说两句话 —— 而两份漂了不会有任何地方报错。所以这里只解释
    `sources.unclassified` 那一格：改前它说"要收进来就给 errorstats 的族表补一条原话"，
    读的人会以为补一行就收得完。

    2026-11-24 的现场（`projects/lp-ball-22`，`{'tool': 15}`）：那 15 条不是一族 ——
    盘上原话至少分成"候选期抽读要给 `path`"、"<表> 没有字段 [...]"、"本次委托没有
    回读记录"、"超过该委托上限"、"槽位不在本次委托"、"没有编号的手稿"、"派活文本点名
    了猜想号"等七八族。一族一行地补 `_TOOL_REFUSAL_FAMILIES` 才收得进来，而且每一族
    归哪个类目要逐族判；本路允许改的面只有 `webui/**`，族表不在这里。

    没读到 `sources.unclassified` 时原样保留 readouts 的那句话（不编一个族数出来）。
    """
    out = dict(face)
    loose = ((face.get("data") or {}).get("sources") or {}).get("unclassified") or {}
    loose = {str(k): int(v or 0) for k, v in loose.items() if int(v or 0)}
    problems: list[dict[str, str]] = []
    for one in (face.get("problems") or []):
        item = dict(one)
        if str(item.get("code") or "") == "unclassified_signal" and loose:
            item["detail"] = (
                f"结构判据认不出族的 {loose} 条没有猜类目（各自的那一类里没加数）。"
                "这一条不在网页层收：类目与族表的唯一真身是 `errorstats`"
                "（`/api/errors` 与 CLI 的 `errors` 读同一个 `errors_readout`），"
                "网页另加一条「原话 → 类目」的映射会让两个出口的 `total` 说两句话。"
                "盘上这批原话本身也不是一族（抽读缺 `path` / 投影写了不存在的字段 / "
                "委托配额与槽位 / 手稿编号不存在 / 派活文本点名猜想号…）——"
                "一条补不进全部。补法：在 `errorstats._TOOL_REFUSAL_FAMILIES` 里逐族补"
                "原话（形态照既有条目 `(类目, (\"原话\",))`），并确认那个类目已登记在"
                "`errorstats.ERROR_CATEGORIES`。")
        problems.append(item)
    out["problems"] = problems
    return out


# ====================================================================== 9 用量
def usage_face(root: str | Path) -> dict[str, Any]:
    """`GET /api/usage` 的读模型：`usage_ledger` 的汇总（总计 + 两个归口 + 最近几笔）。

    「最近几笔」按文件顺序取尾部（`usage_ledger` 是 append-only 的 JSON 表）——
    不排序、不猜时间戳：那一列的名字由 `schema.UsageEntry` 定，这一层不改口径。

    ## 三态（READFIX-D-4）

    改前 `Store.rows("usage_ledger")` 对"表不在盘上"回 `[]`，于是这一面回
    `spent.usd=0.0` / `entries=0` / `tri=computed` —— "还没写过"被印成"查过了，是 0"。
    现在按表在不在盘上分三档：

    - 不在盘上（还没写过）⇒ `tri="not_applicable"`、`entries=None`、`spent={}`，
      `reason` 说清"不是 0"；
    - 坏 JSON / 读不出 ⇒ `tri="unreadable"`，同样 `entries=None`、`spent={}`；
    - 读到了 ⇒ `tri="computed"`（0 行也是真 0）。

    `spent_unknown_usd_calls` 是"账本里有几行算不出价钱"（`usd` 不是数字）：改前页面
    把 `unknownCalls` 写死成 0，读的人以为"一次都没有"（READFIX-D-13）。
    """
    from ..store import Store
    from ..tokenmeter import TokenMeter

    root_p = Path(str(root))
    try:
        store = Store(root_p)
        rows, ledger_tri = _table_state(store, "usage_ledger")
        if ledger_tri != TRI_COMPUTED:
            why = ("usage_ledger 不在盘上（还没写过）⇒ 用量记 not_applicable，不是 0"
                   if ledger_tri == TRI_NOT_APPLICABLE else
                   "usage_ledger 读不出来（坏 JSON / 坏表）⇒ 用量记 unreadable，不是 0")
            return {"tri": ledger_tri, "reason": why,
                    "path": str(root_p / "data" / "usage_ledger.json"),
                    "entries": None, "spent": {}, "by_role": {}, "by_scope": {},
                    "retry_overhead": {}, "recent": [],
                    "spent_unknown_usd_calls": None}
        meter = TokenMeter(store)
        recent = [dict(r) for r in rows[-10:]]
        unknown_usd_rows = sum(
            1 for row in rows
            if not isinstance(row.get("usd"), (int, float))
            or isinstance(row.get("usd"), bool))
        return {
            "tri": TRI_COMPUTED, "reason": "",
            "path": str(root_p / "data" / "usage_ledger.json"),
            "entries": len(rows),
            "spent": dict(meter.spent() or {}),
            "by_role": dict(meter.by_role() or {}),
            "by_scope": dict(meter.by_scope() or {}),
            "retry_overhead": dict(meter.retry_overhead() or {}),
            "recent": recent,
            "spent_unknown_usd_calls": unknown_usd_rows,
        }
    except Exception as exc:  # noqa: BLE001 - 读不到就是没查成，不许折成 0
        return {"tri": TRI_UNREADABLE,
                "reason": f"usage_ledger 读不出来：{type(exc).__name__}: {exc}",
                "path": str(root_p / "data" / "usage_ledger.json"),
                "entries": None, "spent": {}, "by_role": {}, "by_scope": {},
                "retry_overhead": {}, "recent": [],
                "spent_unknown_usd_calls": None}


# ====================================================================== 10 状态报告
def status_reports_face(root: str | Path) -> dict[str, Any]:
    """`GET /api/status-reports` 的读模型：`<报告目录>/STATUS-*.md|json` 最近几份。

    这一条补的是一个真缺口（`draft/112` §4.2 第 3 条）：`statusreport` 一直在写
    `STATUS-<ts>.{md,json}`，而盘上没有任何消费者 —— 写了没人读，等于没写。

    目录现取 `_report_dir_rel()`（写侧 `statusreport` 用的 `review_tools.DEFAULT_REPORT_SUBDIR`）：
    2026-11-22 起写侧落在 `out/report/`，读侧若继续 glob `out/review/`，
    就会出现"写者有、读者说 0 份"的假读数（正是这一条面要防的那件事）。
    """
    root_p = Path(str(root))
    dir_rel = _report_dir_rel()
    out_dir = root_p / dir_rel
    # 目录不在 ⇒ "还没写过"（not_applicable）：这时 `count` 是 None，不是 0
    # （READFIX-D-9：改前印「共 0 份」，而盘上根本没有这个目录）。
    if not out_dir.is_dir():
        return {"tri": TRI_NOT_APPLICABLE,
                "reason": f"{dir_rel} 目录不在盘上（还没写过；不是「写了 0 份」）",
                "dir": str(out_dir), "count": None, "reports": []}
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
            "reason": "" if reports else f"{dir_rel} 下还没有 STATUS-* 报告（还没写过）",
            "dir": str(out_dir), "count": len(mds), "reports": reports}


#: `run_index_reason()` 里给的"怎么修"那一条命令（`cli.py` 的子命令逐字，判据钉它）。
RUN_INDEX_REBUILD_CMD = "agentflow project rebuild-run-index --workspace {root}"


def run_index_reason(root: str | Path, doc: Mapping[str, Any]) -> str:
    """`/api/run-index` 非 `computed` 那一档的 `reason`：为什么 + 是不是毛病 + 怎么修（AUDIT F10）。

    这一格在真实工作区上「恒」 `unreadable`（索引只在顶趟收工成功 / `closing` 通关 /
    显式 `rebuild-run-index` 时建）。原来的 `reason` 只说"索引不在盘上"，读到的人分不清
    "常态"与"坏了"、也不知道下一步做什么 —— 三态纪律要求 `unreadable` 把这两句说出口。

    为什么住在 `readers.py` 而不是那个端点的处理器里：`/api/run-index` 的处理器在
    `webui/server.py`（A 线的 `WebHandler`），而"这一格为什么恒 unreadable"是「盘上
    事实的读法」，属读侧；放在这里，判据可以脱离 HTTP 直接把函数钉住，处理器那边
    只要一行转发（`server.py` 的 patch 见 `temp/webfix3/patches/`）。

    两种档位分开说：`not_applicable`（一场会话都没有 ⇒ 没有可建的源）与
    `unreadable`（有会话、但索引没建 / 读不出）。补进去的字是「纯追加」：
    `sessions.run_index_report` 给的那一句原样留在最前面（既有判据按子串断言它）。
    """
    base = str(doc.get("reason") or "").strip()
    tri = str(doc.get("tri") or "")
    root_shown = str(Path(str(root)).resolve()) if str(root or "").strip() else ""
    if tri == "not_applicable":
        tail = (" —— 这个工作区一场会话都没有，所以没有可对账的源（不是「对上了」）。"
                "跑过一趟之后（顶趟收工成功会顺手建索引）再回来看这一格。")
    else:
        tail = (
            " —— 为什么会这样：索引只在顶趟收工成功（`stop_reason=final`）、"
            "`agentflow closing` 通关、或显式重建时落盘（`sessions.rebuild_run_index` 没有"
            "别的生产调用者）；工作区没走过这三步就一直没有 `index/run-index.json` ——"
            "这是常态，不是出错，所以这一格在真机上几乎总是 `unreadable`。"
            "怎么修（两步任选）：① 想现在就建：跑 `"
            + RUN_INDEX_REBUILD_CMD.format(root=root_shown)
            + "`（幂等，只写 `index/run-index.json` 与一行审计）；"
            "② 不想建也行：未走完/被叫停的趟看同一页的「趟次档案」"
            "（`GET /api/run-digest`，从 `sessions/*.jsonl` 现算，不读索引）——"
            "Run 页的趟次本来就是回退现算的，索引那一格只负责对账。"
        )
    return (base + tail) if base else tail.lstrip(" ——")


# ====================================================================== 11 网页操作台账（AUDIT F11）
#: `/api/actions` 一页默认给多少行（`?limit=` 可改，上限 :data:`ACTIONS_PAGE_MAX`）。
ACTIONS_PAGE_DEFAULT = 20
#: `/api/actions` 一页的上限。
ACTIONS_PAGE_MAX = 200


def actions_face(root: str | Path, *, limit: int = ACTIONS_PAGE_DEFAULT,
                 offset: int = 0) -> dict[str, Any]:
    """`GET /api/actions` 的读模型：网页操作台账（`<工作区>/web-actions.jsonl`）的分页读数。

    ## 为什么要有这一面（AUDIT F11）

    台账从 W3 起就在写（`writes.audit.record_action`：每一笔网页写操作一行，
    被拒的尝试也留一行），但「全仓没有读侧」 —— 「谁在什么时候从网页上按了什么、
    成了没有」这个问题在页面上答不出来。写侧自己的文件头（`webui/audit.py` §一行形状）
    就写着那一栏叫「操作历史」，于是这一条端点补的就是它。

    读法只有一份实现：`audit.read_actions_state`（它已经带回四态与坏行说明）。这一层
    只做三件事 —— 「倒序」「分页」「把缺省落点写死」：

    - 倒序：台账是追加写的，读的人先要看最近一笔（`order="newest_first"` 明说）；
    - 分页：`limit` / `offset` 由调用方给（HTTP 层已经校验过非法值），`has_more` 说清
      "还有没有下一页" —— 让页面不必自己拿 `total` 与 `offset+len` 去比（比错了就是
      "看起来能翻页、翻过去是空的"）；
    - 落点：`path` 恒给绝对路径，缺省就是 `<工作区>/web-actions.jsonl`
      （`audit.actions_path(root)` 是唯一口径；读不到时也照样给，于是「路径不对」
      与「文件还没建」在读数上分得开）。

    三态原样搬，不折：台账读不出来 ⇒ `tri="unreadable"` 且 `rows=[]`
    （「不是」"没有操作"）；文件不在盘上 ⇒ `tri="not_applicable"`、0 行、`reason`
    逐字写「还没建」（合法初态，但不是「0 条动作」）；文件在、一行都没有 ⇒
    `tri="computed"` 且 `reason` 明说「在盘上但是空文件」。坏行说明在 `problems` 里，
    不在 `reason` 里被吞掉。
    """
    from . import audit as A

    got = A.read_actions_state(root)
    rows = [r for r in (got.get("rows") or []) if isinstance(r, Mapping)]
    total = len(rows)
    window = list(reversed(rows))[offset:offset + limit]
    return {
        "tri": str(got.get("tri") or TRI_COMPUTED),
        "reason": str(got.get("reason") or ""),
        "path": str(got.get("path") or A.actions_path(root)),
        "problems": [str(x) for x in (got.get("problems") or [])],
        "rows": window,
        "total": total,
        "limit": int(limit),
        "offset": int(offset),
        "has_more": offset + len(window) < total,
        # 顺序是读数的一部分：页面若按"最新的在最上面"写死一句说明，就得有一个
        # 机器读数能在它被改坏时响（判据钉这一格）。
        "order": "newest_first",
    }


# ====================================================================== HTTP 外壳
def _json_of(handler: Any, obj: Any) -> None:
    """按 `WebHandler._json` 的形态回一份 JSON（A 线的那个方法在这里被复用）。"""
    handler._json(200, obj)  # noqa: SLF001 - 处理器与 handler 是同一族的约定接口


def handle_state(handler: Any, params: Mapping[str, str],
                 query: Mapping[str, Sequence[str]]) -> None:
    """`GET /api/state`：快照那份 JSON（裁定 2b 之后这条端点的归属在这里）。

    回的是 :func:`state_face` 里那张 `snapshot` —— 也就是 `webui.state.snapshot(root)`
    的返回值本身，不是外面那层三态包装：`/api/state` 是既有公开面，
    `temp/_verify_w0.py` 对账的顶层键与页面形状都是按它量的（迁路由不许动它；
    2026-11-14 加了 `project` / `current` 两格，是加键不是改键）。

    `sid` 从 handler 上取（`serve(sid=…)` 挂上去的那个）：它让页面上的
    `current.sid` / `current.round` 与命令行 `start --watch` 印出来的两个数同源。

    `handle_state_face`（回 `{tri, snapshot, reason}`）那个三态形态刻意没有留下：
    同一个端点上摆两个形状只差一个字的处理器，早晚有人把错的那个登记进表里。
    要三态读数的地方读 `readers.state_face` 这个函数（它是读模型，不是端点）。
    """
    del params, query
    # 写权限读数（鲁棒 f）：判定口径只有 `writes.writes_allowed` 一处；
    # 关着的时候把 `writes.WRITES_OFF_REASON` 逐字带出去，页面据此禁用写按钮。
    from . import writes as WR

    allowed = WR.writes_allowed(handler)
    _json_of(handler, state_face(handler.root, sid=getattr(handler, "sid", ""),
                                 writes_allowed=allowed,
                                 writes_reason="" if allowed else WR.WRITES_OFF_REASON)["snapshot"])


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


def _page_window(query: Mapping[str, Sequence[str]]) -> tuple[int, int, str]:
    """读 `?limit=` / `?offset=` / `?summary=1` ⇒ `(limit, offset, 问题)`。

    - `?summary=1` 是"首屏摘要"的别名：`limit=SUMMARY_ROWS`、`offset=0`（显式给了
      `limit` 就按显式那个，两者不打架：后者更具体）；
    - 都不给 ⇒ `limit=0`（「全量」，既有行为一字不变）；
    - `limit` 钳在 `[0, PAGE_ROWS_MAX]`：超上限「不是」非法（按上限截断，与
      `/api/run/{sid}/events` 同一条口径），负数 / 非整数才是非法；
    - `offset` 必须 `>= 0`。

    非法值由调用方回 400（`/api/*` 一律 JSON，裁定 Q1）—— 形状与
    `handle_run_events` 那份 400 逐字同族。
    """
    limit, why_limit = _read_cursor(query, "limit", 0)
    offset, why_offset = _read_cursor(query, "offset", 0)
    problems = [w for w in (why_limit, why_offset) if w]
    if limit is None or offset is None:
        return 0, 0, "；".join(problems)
    summary = _query_text(query, "summary").strip().lower() in {"1", "true", "on", "yes"}
    if summary and _query_text(query, "limit").strip() == "":
        limit = SUMMARY_ROWS
    if limit > PAGE_ROWS_MAX:
        limit = PAGE_ROWS_MAX
    return limit, offset, "；".join(problems)


def _query_flag(query: Mapping[str, Sequence[str]], name: str) -> bool:
    """读一个布尔开关（`1/true/on/yes` 为真；不给 / 空 / 其余为假）。

    为什么不再回 400：`?full=` 是"要字段全"的开关，拼错一个值最多退回默认的
    compact 档 —— 而默认档已经把"省了哪些字段"写在 `rows_omitted` 里，读的人
    看得见；把它判成 400 反而像"这条端点坏了"。分页那两个参数不同：它们决定
    "哪一页"，错了会静默给出另一页，所以那两个仍走 400。
    """
    raw = _query_text(query, name).strip().lower()
    return raw in {"1", "true", "on", "yes"}


def _bad_page(handler: Any, what: str, why: str,
              query: Mapping[str, Sequence[str]]) -> None:
    """分页参数不合法 ⇒ 400（JSON；把两个参数原样回显，读的人一眼看得出被拒的是哪个）。"""
    handler._json(400, {  # noqa: SLF001 - 与 handler 是同一族的约定接口
        "ok": False, "tri": TRI_NOT_APPLICABLE,
        "reason": f"{what}：{why}",
        "limit": _query_text(query, "limit"),
        "offset": _query_text(query, "offset"),
        "summary": _query_text(query, "summary"),
    })


def handle_evidence(handler: Any, params: Mapping[str, str],
                    query: Mapping[str, Sequence[str]]) -> None:
    """`GET /api/evidence`：证据链八栏的 JSON。

    三组参数各管一根轴，互不顶替：

    - `?limit=` / `?offset=` / `?summary=1`：行那一轴（`rows_mode` / `rows_limit` /
      `rows_offset` / `rows_total` 四格说清是哪一档、一共多少行）；
    - `?full=1`：字段那一轴（默认 compact：只给面板会画的列；`full=1` 给全字段，
      `rows_fields` 说清是哪一档，`rows_omitted` / `rows_clipped` / `rows_nested`
      点名省了/截了哪些）；
    - 三态与各栏 `*_tri` 两档都一个不少。

    AUDIT F12：真机这一条曾回 2.1 MB / 2.6 s，页面一进来就卡。现在的缺省是
    compact（长字段不进首屏），"取全部"才带 `?full=1` —— 内容不丢，只是不在
    首屏那一次响应里。契约判据 C 读的是 `evidence_chain()` 的缺省读数（全字段
    读模型），所以它逐字不变。
    """
    del params
    limit, offset, why = _page_window(query)
    if why:
        _bad_page(handler, "/api/evidence 的分页参数不合法", why, query)
        return
    compact = not _query_flag(query, "full")
    _json_of(handler, evidence_chain(handler.root, limit=limit, offset=offset,
                                     compact=compact))


def handle_artifacts(handler: Any, params: Mapping[str, str],
                     query: Mapping[str, Sequence[str]]) -> None:
    """`GET /api/artifacts`：产物面的 JSON（可带 `?run_dir=`、分页三参与 `?full=1`）。

    读数走 `facecache.cached_face`（按盘失效，见 `webui/facecache.py`）：同一份盘、
    同一组参数（`run_dir` + `limit` + `offset` + `full`）直接复用上一份读模型，
    响应顶层多一格 `cache`（`hit` / `key_sha` / `built_at`）。`full` 必须进缓存键：
    compact 与 full 是两份字节不同的读数，共用一个键就会把"取全部"命中成"首屏那
    一份"（内容少了而 `hit=true`）。`cache` 刻意不进 `artifacts_face` 的返回值 ——
    那是读模型，与 `ui/src/types.ts` 的 `ArtifactsView` 逐格对齐。
    """
    del params
    limit, offset, why = _page_window(query)
    if why:
        _bad_page(handler, "/api/artifacts 的分页参数不合法", why, query)
        return
    vals = query.get("run_dir") or []
    run_dir = str(vals[0]) if vals else None
    compact = not _query_flag(query, "full")
    face, cache = facecache.cached_face(
        "artifacts", handler.root,
        {"run_dir": run_dir if run_dir is not None else "",
         "limit": int(limit), "offset": int(offset), "full": int(not compact)},
        lambda: artifacts_face(handler.root, run_dir=run_dir, limit=limit,
                               offset=offset, compact=compact))
    _json_of(handler, {**face, "cache": cache})


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


def handle_package(handler: Any, params: Mapping[str, str],
                   query: Mapping[str, Sequence[str]]) -> None:
    """`GET /api/package`：论文包三块（`?project_dir=` `?report_path=` `?cap_usd=` `?sid=`）。

    与 `/api/artifacts` 同一条缓存口径（`webui/facecache.py`）：失效键里装着
    `project_dir` / `report_path` / `cap_usd` / `sid` 这四格参数、工作区全部文件的
    `mtime_ns` + 大小、以及 `data/events.jsonl` 的最后序号。最后那一项同时是门结论的
    保鲜期：`closing.check_closing` 的八格算在这一次读模型里，事件流一追加（序号变）
    整份缓存就作废 —— 门结论不许跨过一次事件序号。
    """
    del params

    def one(name: str) -> str:
        vals = query.get(name) or []
        return str(vals[0]) if vals else ""

    cap_raw = one("cap_usd").strip()
    try:
        cap: float | None = float(cap_raw) if cap_raw else None
    except ValueError:
        cap = None
    project_dir, report_path = one("project_dir"), one("report_path")
    sid = one("sid") or None
    face, cache = facecache.cached_face(
        "package", handler.root,
        {"project_dir": project_dir, "report_path": report_path,
         "cap_usd": cap if cap is not None else "", "sid": sid or ""},
        lambda: package_face(handler.root, project_dir=project_dir,
                             report_path=report_path, cap_usd=cap, sid=sid))
    _json_of(handler, {**face, "cache": cache})


def handle_source(handler: Any, params: Mapping[str, str],
                  query: Mapping[str, Sequence[str]]) -> None:
    """`GET /api/source`：一个文本文件的原文窗口（只读；路径闸见 `source_window`）。"""
    del params

    def one(name: str) -> str:
        vals = query.get(name) or []
        return str(vals[0]) if vals else ""

    try:
        line = int(one("line") or 0)
    except ValueError:
        line = 0
    _json_of(handler, source_window(handler.root, one("path"), line=line,
                                    match=one("match")))


def handle_machine(handler: Any, params: Mapping[str, str],
                   query: Mapping[str, Sequence[str]]) -> None:
    """`GET /api/machine`：本机读数的 JSON。"""
    del params, query
    _json_of(handler, machine_face(handler.root))


def handle_actions(handler: Any, params: Mapping[str, str],
                   query: Mapping[str, Sequence[str]]) -> None:
    """`GET /api/actions`：网页操作台账的分页读数（AUDIT F11 的读侧）。

    `?limit=` 缺省 `ACTIONS_PAGE_DEFAULT`，`?offset=` 缺省 0；非法值回 400
    （形状与 `/api/run/{sid}/events` 那份 400 同族）。只读：这一条端点不写盘、
    不需要 `--allow-writes`（台账是写侧的事，读它不该要写权限）。
    """
    del params
    limit, why_limit = _read_cursor(query, "limit", ACTIONS_PAGE_DEFAULT)
    offset, why_offset = _read_cursor(query, "offset", 0)
    problems = [w for w in (why_limit, why_offset) if w]
    if limit == 0:
        problems.append("limit 必须 >= 1（要 0 行的话没有一页可取）")
    if problems or limit is None or offset is None:
        _bad_page(handler, "/api/actions 的分页参数不合法", "；".join(problems), query)
        return
    if limit > ACTIONS_PAGE_MAX:
        limit = ACTIONS_PAGE_MAX
    _json_of(handler, actions_face(handler.root, limit=limit, offset=offset))


def handle_budget_view(handler: Any, params: Mapping[str, str],
                       query: Mapping[str, Sequence[str]]) -> None:
    """`GET /api/budget`：预算读数（总额度 / 已花 / 剩余 / 追加历史）。

    名字末尾那个 view 后缀不是装饰（判据当场抓到的）：写面 `writes.py` 里
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
    """`GET /api/status-reports`：`out/report/STATUS-*` 最近几份。"""
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

#: 对话线的三种身份。业主的对话框要的是"用户 ↔ 主控"的来回，所以前两档是主角；
#: 其余角色在公共频道/私有频道说的话单列 `team` 一档（它们对看的人有用，但不是"对话"，
#: 页面默认把它们折起来）。
#:
#: `team` 这一档也收主控自己的公共频道广播 —— 分档判据是"这句话
#: 说给谁听"，不是"发信人是不是主控"（见 :func:`_chat_message_who`）。
CHAT_WHO = ("user", "conductor", "team")

#: 公共频道在 `to` 那一格的落库写法（`send_message` 按它把 `channel` 写成 `"public"`）。
#: 它是唯一的写法：旧行里那个 legacy 字面量由 `channel == "public"` 那一半认出来
#: （历史行同样带着 `channel`），这一层不产生新写法、也不需要第二份词表。
#:
#: 为什么不 import 写侧那一格：`readers` 读的是盘上的字面量，不是写侧的常量；为了一个
#: 字符串把整个 `agent_loop` 拉进只读层不值得（同 `_ROSTER_DIR` 的口径）。
CHAT_PUBLIC = "ALL"


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

    老事件（写侧补 `task_id` 之前落盘的
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


def _chat_message_who(event: Mapping[str, Any], conductor: str) -> tuple[str, str]:
    """一条 `agent_message` 该进哪一档，以及它那一行的标题。返回 `(who, 标题)`。

    判据是收信人，不是发信人（业主：「看M对话public形式为什么也会直接
    让用户可见」）：

    - `to == ALL`（或 `channel == "public"`）⇒ `team`：公共频道的语义是"发给树上的人"
      （`agent_loop.public_visibility` 逐条写了可见面：框架通报全树可见，代理自己发的只对
      直接父/直接子可见），它不是"对用户说的话"。发信人是主控也一样 —— 只按"发信人是
      不是 M"分档，主控的派活通告就会被印成主控对用户的回答，`channel` 只被拼进标题当装饰；
    - 主控发给用户的私聊（`to` 是 `userio.USER` 或另一个写法 `user`）⇒ `conductor`：
      这才是"用户 ↔ 主控"那一档；
    - 其余（别的角色发给主控的私聊、主控发给下级的私聊、别的角色之间的私聊）⇒ `team`：
      它们不是对用户说的话，页面把这一档默认折起来（见 `CHAT_WHO`）。

    标题要说清去向：广播那一行写成「主控广播 → 全树（public）」，不许写成
    `M → 某个人（public）` 那种"看了也不知道这一条是发给谁的"形态。
    """
    from .. import userio as U

    sender = str(event.get("from") or "")
    to = str(event.get("to") or "")
    channel = str(event.get("channel") or "")
    if to == CHAT_PUBLIC or channel == "public":
        head = "主控广播" if sender == conductor else f"{sender or '?'} 广播"
        return "team", f"{head} → 全树（public）"
    title = f"{sender or '?'} → {to or '?'}（{channel or '?'}）"
    # `userio.USER` 是"用户"这个发件人的唯一写法；`user` 是 `_known_recipient` 认的另一个
    # 收件人写法（`agent_loop` 那两处 `token in ("user", "用户")`），两个都收。
    if sender == conductor and to in (U.USER, "user"):
        return "conductor", title
    return "team", title


def _chat_delivery_who(role: str, conductor: str) -> tuple[str, str]:
    """一条 `agent_run_end` 的收工交付该进哪一档，以及标题。

    主控这一趟的 `final` 就是"主控交给用户的那段话"（业主的对话框要的正是
    它），所以它留在 `conductor`；别的角色的交付进 `team`。这一档按 `role` 取，不看有没有
    `to` / `channel`：收工事件本来就没有收件人那一栏。
    """
    if role == conductor:
        return "conductor", "主控交付"
    return "team", f"{role} 交付"


def _chat_line(index: int, event: Mapping[str, Any]) -> dict[str, Any] | None:
    """一条会话事件 → 一条对话线；不是"对话"的事件回 `None`。

    映射口径（逐条都能在盘上对上，不许靠猜）：

    | 盘上的 kind | 谁的线 | 印什么 |
    |---|---|---|
    | `agent_run_start`（role=M 且不是被别的角色召唤的） | `user` | 那一句话任务（`resumed_from>0` ⇒ 标"接着上一步说"） |
    | `user_answer` | `user` | 用户的回答 |
    | `agent_interjection`（`from` = 用户） | `user` | 插话正文 |
    | `user_question` | `conductor` | 主控问的话 + 选项 + qid |
    | `agent_message`（主控 → 用户，私聊） | `conductor` | 主控对用户的回答 |
    | `agent_message`（公共频道 `ALL`，谁发的都一样） | `team` | 一段广播（标题写"主控广播 → 全树（public）"） |
    | `agent_message`（其余私聊） | `team` | `谁 → 谁（频道）` |
    | `agent_run_end`（role=M，有 final） | `conductor` | 主控这一趟的交付 |
    | `agent_run_end`（别的角色，有 final） | `team` | 那个角色的交付 |

    分档判据是"这句话说给谁听"，不是"发信人是不是主控"：公共频道的广播
    （`to=ALL`）发给的是树上的人，它不进 `conductor` 那一档 —— 只按发信人分档会把
    主控的派活通告印成"主控对你说的话"。逐档判据见 :func:`_chat_message_who`
    与 :func:`_chat_delivery_who`。

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
        # 这一条是"用户对主控说的话"，页面必须看得到它写给谁（业主 2026-11-24：
        # 「从网页看用户插话似乎未直接绑定发送给M」）。事件的 `to` 就是收件人；
        # 它没有 `task_id`（那是"谁在跑"，插话不是谁跑的），所以编号那格留空是如实。
        role = str(event.get("to") or role)
        role_source = "to" if role else role_source
        title = f"插话 → {role}" if role else "插话"
        text = str(event.get("body") or "")
        # 插话没有台账号（它不是谁"在跑"），但它有自己的编号 i-NNNNNN：
        # 页面那一格印它，并标清这是"插话编号"而不是台账号（不编一个假台账号）。
        if str(event.get("interjection_id") or ""):
            task_id_override = str(event.get("interjection_id"))
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
        who, title = _chat_message_who(event, M)
        text = str(event.get("body") or "")
    elif kind == "agent_run_end":
        text = str(event.get("final") or "")
        if text.strip() == "":
            return None          # 没有交付的那一趟不进对话（它没有"话"）
        who, title = _chat_delivery_who(role, M)
    else:
        return None
    body, clipped = _chat_clip(text)
    # 每一条对话线都要能回答"是哪个绝对编号的哪个角色在说话"。
    # 绝对编号从事件里取（`task_id`；`agent_message` 那一路写的是 `from_task_id`），
    # 两个都没有就留空串 —— 空串在页面上显示成"（未记录编号）"，比编一个假编号好。
    #
    # 这一层只认两种来源：`event`（事件里真有）与 `missing`（这条事件没记）。"从同一岗的
    # `agent_run_start` 推出来"的那一档（`inherited`）刻意不在这里做：那是 `chat_face`
    # 的事 —— 它要看整段会话才判得准，而本函数的输入只有一条事件。于是直接调本函数的人
    # 永远读不到 `inherited`；要拿回填后的读数就调 `chat_face`（见 `_single_run_start_ids`）。
    task_id = str(event.get("task_id") or event.get("from_task_id") or "")
    if kind == "agent_interjection":
        task_id = str(event.get("interjection_id") or "")
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

    业主：「用户和主控的对话不应该只做成只能一句话启动任务，应该是能对话的」。
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

    编号那一格（兼容老事件的那一半）：每条线都有 `task_id` 与
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

    分档那一格：`who` 判的是"这句话说给谁听"，不是"发信人是
    谁"。`conductor` 只收说给用户听的那几条（主控私聊回答 / `ask` 反问 / 收工交付）；
    主控的公共频道广播（`to=ALL`）归 `team` —— 它发给的是树上的人，把它摆在
    "主控对你说的话"那一档等于对读者撒谎。`team` 那一档页面默认折叠。
    """
    root_p = Path(str(root))
    sessions = [{"sid": str(s.get("sid") or ""),
                 "last_ts": str(s.get("last_ts") or ""),
                 "events": int(s.get("events") or 0),
                 "bad_lines": int(s.get("bad_lines") or 0)}
                for s in SS.list_sessions(root_p)]
    # 这一次请求里每一段会话最多读一遍：下面是"挑哪一段"（要判它有没有起过一趟）与
    # "把它映射成对话线"两步，两步问的是同一份盘（同一个 `read_session` 入口）。
    scanned: dict[str, tuple[list[dict], list[str]]] = {}

    def _session_of(sid: str) -> tuple[list[dict], list[str]]:
        got = scanned.get(sid)
        if got is None:
            got = scanned[sid] = SS.read_session(root_p, sid=sid)
        return got

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
        from ..schema import CONDUCTOR_ROLE as _M

        def _has_run_start(row: dict[str, str]) -> bool:
            """这一段的对话线里有没有一条是"起一趟"。

            判据就是 :func:`_chat_line` 对 `agent_run_start` 的那一支（role 是主控、
            且不是被下级召唤的）—— 原来逐条调 `_chat_line` 只为拿这一个布尔量，
            等于把整段会话的每一条事件都投影一遍再丢掉。
            """
            for ev in _session_of(row["sid"])[0]:
                if str(ev.get("kind") or "") != "agent_run_start":
                    continue
                if str(ev.get("role") or "") != _M:
                    continue
                if str(ev.get("summoned_by") or "") in ("", _M):
                    return True
            return False

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
    events, bad = _session_of(chosen)
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

#: 名册目录里的两个旁支文件（与 `<父>.jsonl` 同目录、同后缀，但不是"某个父名下的
#: 子代理"）：槽位池事件 `-surfaces` / 销号名单 `-retired`。
#: 折叠这一棵树时不许把它们混进去 —— 混进去一个名字就会变成两个节点。
#:
#: 对照表 `-index.jsonl` 不属于这张表：它不是旁支，它是"这件活是谁接的"的第二份盘上
#: 事实。`secretary.roster_add` 的 reuse 支只往对照表写一行调用记录（不往
#: `<父>.jsonl` 写新的名册项，因为复用不是新建一个子代理），所以把它当旁支读掉的
#: 后果是"接过好几件活的那个子代理，它那些活根本不在树上"——而台账里明明挂着父，
#: 于是同一份读数里两栏互相打脸：`coverage.unrostered` 点名它，树又把它画成树根。
#: 本层两份都读，且按名册名归组（见 `roster_face`）。
_ROSTER_SIDE_SUFFIX: tuple[str, ...] = ("-surfaces.jsonl", "-retired.jsonl")

#: 对照表的后缀：`<父>-index.jsonl`。每一行是"某个名字此刻的编号"（`kind="bind"`，
#: 带 `first` 的那一行是第一次绑定）。它和 `<父>.jsonl` 一起折叠出"这个父名下有哪些子"。
_ROSTER_INDEX_SUFFIX = "-index.jsonl"


#: 台账兜底那一档要搬进 `RosterView` 的键（与 :func:`_roster_from_tasks` 的返回键一一
#: 对应）。为什么单列一份：`roster_face` 里两个"名册读不到"的分支搬的是同一批键，
#: 抄两遍就会漏一处 —— 而漏的那一处表现为"某一档少一个键"，前端读它时才知道少了。
_ROSTER_FALLBACK_KEYS: tuple[str, ...] = ("nodes", "roots", "children_of", "count",
                                          "max_depth", "coverage", "unplaced", "states")


def _roster_files(dir_p: Path) -> tuple[list[tuple[str, Path]], list[tuple[str, Path]], str]:
    """名册目录里"哪个父有哪一份名册 / 对照表"：`([(父, 名册)], [(父, 对照表)], 问题)`。

    文件名就是父的绝对编号（`t-000001.jsonl` / `t-000001-index.jsonl`），文件里每一行
    是一个子（`task_id` 是子的绝对编号）。这条布局是 `secretary.roster_path()` 与
    `secretary.roster_index_path()` 定的，这里只按它读 —— 不另立第二份命名约定
    （两处命名漂移的后果是"名册在盘上、页面说没有"）。

    为什么两份都要读回来（D15）：名册给"名字 + 简介 + 槽位"，对照表给"这个名字此刻的
    编号"。reuse 只写对照表，所以只读名册就会漏掉复用出来的那个实例。
    """
    try:
        entries = sorted(dir_p.glob("*.jsonl"))
    except OSError as exc:  # noqa: BLE001 - 列不出来是"没查成"，不是"没有名册"
        return [], [], f"{dir_p} 列不出来：{type(exc).__name__}: {exc}"
    found: list[tuple[str, Path]] = []
    index_found: list[tuple[str, Path]] = []
    for path in entries:
        name = path.name
        if name.endswith(_ROSTER_SIDE_SUFFIX):
            continue
        if name.endswith(_ROSTER_INDEX_SUFFIX):
            owner = name[: -len(_ROSTER_INDEX_SUFFIX)]
            if not owner:
                return [], [], f"{name} 的文件名里读不出父的绝对编号"
            index_found.append((owner, path))
            continue
        owner = name[: -len(".jsonl")]
        if not owner:
            return [], [], f"{name} 的文件名里读不出父的绝对编号"
        found.append((owner, path))
    return found, index_found, ""


def _roster_name_order(roster_rows: list[dict[str, Any]],
                       index_rows: list[dict[str, Any]]) -> dict[str, int]:
    """一个父名下"每个名册项是按第几行落的盘"：`name` → 行序（越小越先落）。

    为什么要有它（业主：「名册按树展开」）：一个父的多个子在页面上必须
    按落盘行序排，而 `secretary._fold_roster` 交回来的是按名册名排序的一项一条
    （那是秘书视图要的顺序，不是树的顺序）。这里不重排折叠结果、也不重读文件 ——
    只把上面刚读过的原始行按"这个名册名第一次出现"编个序，让并集按它稳定排序。

    行序口径（键是名册名，不是任务号）：
    - `<父>.jsonl` 的行序为主（一个名字第一次出现在第几行，它的序就是几）；
    - 只在对照表 `<父>-index.jsonl` 里出现的名字排在名册各行之后，按它们在对照表里的行序；
    - 两边都没出现过的名字（不该有）落在末尾，稳定排序保住了它们的原有相对顺序。
    """
    order: dict[str, int] = {}
    for i, row in enumerate(roster_rows):
        name = str(row.get("name") or "")
        if name and name not in order:
            order[name] = i
    base = len(roster_rows)
    for j, row in enumerate(index_rows):
        name = str(row.get("name") or "")
        if name and name not in order:
            order[name] = base + j
    return order


def _roster_work_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """对照表里的"这一件活是谁接的"：`[{name, role, task_id, brief, at}]`（按行序）。

    ## 为什么这里会出现 `task_id`（而它仍然不是归属键）
    名册项的身份是 `(owner, name)` —— 一个常驻子代理。`task_id` 在这里只是
    "这一条记录的是哪一次调用"的流水读数，和 `at` 同级：它回答"哪一件活落到了
    这个名字上"，不回答"这个名册项是谁"。所以：
    - 本函数按 `name` 归组（调用方负责），绝不按 `task_id` 建项；
    - 一行没有 `name`、只有 `task_id` 的记录会被丢掉并留一条诊断（见 `roster_face`）：
      那是"按任务号记名册"的形态，本层不认。

    为什么读原始行而不是 `_fold_index`：`_fold_index` 是电话簿视图（一个名字只留
    第一次与当前那两次调用），中间的几次调用会被折叠掉 —— 而那几次正是"同一个子代理
    接过好几件活"的证据（真机 `t-000002` 名下的 F1 接了 5 件，折叠后只剩 2 件）。
    这里读每一行，于是"一个节点 + N 件活"里的 N 是真的。
    """
    out: list[dict[str, Any]] = []
    for raw in rows:
        row = dict(raw)
        if str(row.get("kind") or "") == "retire":
            continue
        name = str(row.get("name") or "")
        tid = str(row.get("task_id") or "")
        if not name:
            continue
        out.append({"name": name, "role": str(row.get("role") or ""),
                    "task_id": tid, "brief": str(row.get("brief") or ""),
                    "at": str(row.get("at") or "")})
    return out


def _roster_children_of(kids_of: Mapping[str, list[dict[str, Any]]],
                        roots: list[str]) -> dict[str, list[str]]:
    """按父子的形状：`{父的绝对编号: [它的直接子的绝对编号...]}`（按落盘行序）。

    这就是"名册按树展开"要的那一份读数。它与 `nodes`（按层排的那一份）出自同一份
    折叠结果 `kids_of` —— 上面每份 `<父>.jsonl` 只读了一次，这里只是换个索引方式，
    不重读、不重算（业主那句「不只是简单按层展开」要的是形状，不是第二遍扫描）。

    键序：根先、其余按编号排（读的人先看见顶趟）；没有子的父不出现（空数组不是
    "这个父没有子"的读数 —— 它压根没有这一格）。

    与 `nodes` 的关系：`nodes` 是整棵树的节点读数，规模超上限时会被截断
    （`truncated=true`），而这一份仍是完整的父子关系（它只花一个数组）。所以截断
    那一档里可能点到不在 `nodes` 里的编号 —— 那是"这次没画它"，不是"它不存在"。
    """
    out: dict[str, list[str]] = {}
    seen_roots = set(roots)
    for owner in list(roots) + [o for o in sorted(kids_of) if o not in seen_roots]:
        kids = [str(row.get("task_id") or "") for row in (kids_of.get(owner) or [])]
        kids = [k for k in kids if k]
        if kids:
            out[owner] = kids
    return out


def _roster_unrostered_children(ledger_child_ids: list[str], *,
                                tasks_by_tid: Mapping[str, dict[str, Any]],
                                registered: Mapping[str, Any]) -> list[dict[str, Any]]:
    """台账里有父、名册项没接走的那些子（编号 + 角色 + 状态）。

    ## 为什么要单成一个函数（业主截图）

    父节点上的「子 N」只数名册项时，名册漏写一个，父的子树读数就比台账低一个
    （sylow4：M 名下有 6 个，页面显示「子 4」）。所以"台账里有、名册上没人接"的
    这几个必须单独列出来，挂在父节点下看得见 —— 它们同时仍进页面底部的
    `unplaced`，两处同一处判据（`registered` 就是"名册项接过的活"那张映射）。

    单成一个函数的第二个理由：判据 g（反真空）把它打桩成恒空 ⇒ 「其中 M 个未落名册」
    这一格必须当场变 0，于是"按台账数"这件事不是被空数组顺手带绿的。

    ## `ran` 那一格（`draft/160` 三-3 的丙案）

    这一份是「台账有父、名册没接过」的全集（含被派活闸拒掉、从没跑过的号，含还在
    飞的），而收工门新加的 `roster_registration.unnamed` 只数其中的「真跑过」子集。
    两处不许各写一份判据：`ran` 由 `secretary.ran_but_unnamed`（全仓唯一的四条件）现算
    —— 于是页面上"谁该有名字却没有"与收工读数说的是同一句话。81 趟的 `t-000030`
    （被闸拒、从没跑过）与 `t-000106`（真跑、被 `name_taken` 拒）在这一格里靠 `ran`
    分开：前者是"没跑过"，后者才是"跑过却没名字"。
    """
    from ..secretary import ran_but_unnamed

    out: list[dict[str, Any]] = []
    for tid in ledger_child_ids:
        if tid in registered:
            continue
        row = tasks_by_tid.get(tid) or {}
        out.append({"task_id": tid,
                    "role": str(row.get("role") or ""),
                    "status": str(row.get("status") or ""),
                    "started_at": str(row.get("started_at") or ""),
                    "ended_at": str(row.get("ended_at") or ""),
                    "ran": bool(ran_but_unnamed(row, registered)),
                    "why": "台账里有它这一行，名册正文与对照表里都没有任何名册项接过它"})
    return out


def _roster_clip(text: str, limit: int = ROSTER_INBOX_CLIP) -> str:
    """一条正文截到 `limit` 字（截了就写一句"截过"，不许静默截断）。"""
    body = str(text or "")
    if len(body) <= int(limit):
        return body
    return body[:int(limit)] + f"……（截断：全文 {len(body)} 字）"


def _roster_inbox(rows: list[dict[str, Any]], *, tasks_tri: str,
                  limit: int = ROSTER_INBOX_ITEMS) -> dict[str, Any]:
    """一个节点的收件箱：它名下还没消的板项（`{tri, unread, seen_not_acked, ...}`）。

    ## 收件箱的盘上真身
    `data/tasks.json` 里有两类行：实例行（`kind == ""`，一个 agent 一行）与
    板项行（`kind` 非空：`message` 一条消息 / `notice` 一条通知）。板项行的
    `parent_task_id` 口径是"收件人的编号"（不是派活方）—— 所以
    "`parent_task_id == 这个节点` 且 `item_state != "done"`"就是这个人名下还没消的
    东西。这与 `conductor.open_items_of()` 是同一条判据（那一处 docstring 逐字写了
    板项行与实例行是两轴，不许混算）。

    ## 拆三格（D13）：`seen` 不是"没人读"，它是"读了、还没 ack"
    这一格若只给一个 `open`（= 全部 `item_state != "done"` 的行），页面上那句
    文案把它叫「积压」。问题出在写侧：`close_item`（唯一能把板项推到 `done` 的
    入口）在全仓只有一个调用者，而那一条只 ack 停止通知 —— 于是正常流程下板项从
    `queued` 走到 `seen` 就停住了。"积压"这个数因此单调增长、永不回落，而
    "他还没看"与"他看了但框架没让他 ack"是两件完全不同的事：
    - `unread` = `queued + claimed`（还没被读进任何一步的提示词）；
    - `seen_not_acked` = `seen`（读过了，缺的是那个 ack）；
    - `open_total` = 三者之和（原来那个数，保留成读数）；
    - `other` = `open_total - unread - seen_not_acked`（`item_state` 是空串或词表外的
      行：旧账落的行。单列而不是并进上面两格 —— 那会把"不知道"折成"没读"）。

    为什么不在读侧替父 ack（把 `seen` 当 `done` 消下去）：那会让台账说一件没发生的
    事（老板：「只记读数、不拒写」），而且 `done` 之前的 `seen` 是
    `close_item` 的前置条件，读侧替它消，等于把状态机从后面掏空。读数分格就够了。

    ## 三态
    台账读不出来 ⇒ `tri="unreadable"` + 三格都是 `None`，不是 0 条（把"没查成"读成
    "收件箱是空的"会让监控面板在真出事时最安静）；台账还没写过 ⇒ `not_applicable`
    + 三格都是 `None`（合法初态）；读到了 ⇒ `computed`，三格都是真数字（可以是 0）。
    """
    if tasks_tri == TRI_UNREADABLE:
        return {"tri": TRI_UNREADABLE, "unread": None, "seen_not_acked": None,
                "open_total": None, "other": None, "by_state": {}, "by_kind": {},
                "items": [], "more": 0,
                "reason": "tasks 台账读不出来 ⇒ 这个人的收件箱读不到（不是 0 条）"}
    if tasks_tri != TRI_COMPUTED:
        return {"tri": TRI_NOT_APPLICABLE, "unread": None, "seen_not_acked": None,
                "open_total": None, "other": None, "by_state": {}, "by_kind": {},
                "items": [], "more": 0,
                "reason": "tasks 台账还没写过（合法初态）⇒ 收件箱未读到"}
    by_state: dict[str, int] = {}
    by_kind: dict[str, int] = {}
    for row in rows:
        state = str(row.get("item_state") or "")
        kind = str(row.get("kind") or "")
        by_state[state] = int(by_state.get(state) or 0) + 1
        by_kind[kind] = int(by_kind.get(kind) or 0) + 1
    unread = sum(int(by_state.get(k) or 0) for k in ("queued", "claimed"))
    seen_not_acked = int(by_state.get("seen") or 0)
    shown = rows[:max(0, int(limit))]
    return {"tri": TRI_COMPUTED, "unread": unread, "seen_not_acked": seen_not_acked,
            "open_total": len(rows), "other": len(rows) - unread - seen_not_acked,
            "by_state": by_state,
            "by_kind": by_kind, "more": max(0, len(rows) - len(shown)),
            "items": [{"task_id": str(r.get("task_id") or ""),
                       "kind": str(r.get("kind") or ""),
                       "state": str(r.get("item_state") or ""),
                       "called_by": str(r.get("called_by") or ""),
                       "detail": _roster_clip(str(r.get("detail") or ""))}
                      for r in shown],
            "reason": ""}


def _roster_states_blank(reason: str) -> dict[str, Any]:
    """三态合计"没读到"那一档：每一格是 `None`（不是 0 —— 0 是"读到了、里面是 0 个"）。

    为什么合计也要三态：网页顶部那一行「在飞 a · 待机 b · 静默 c」如果读不到时钟却显示
    0 / 0 / 0，读的人会把它当成"全都收工了" —— 那是这一批要修的那个错的反面。
    """
    return {"checked": False, "reason": str(reason or ""),
            **{name: None for name in AGENT_STATES},
            "active": None, "total": None, "labels": dict(AGENT_STATE_LABELS)}


def _roster_states_of(nodes: Sequence[Mapping[str, Any]], *,
                      reason: str = "") -> dict[str, Any]:
    """按节点的 `state` 合计四档（`conductor.state_counts` 是那四个数唯一的算法）。"""
    counts = state_counts(str(n.get("state") or "") for n in nodes)
    return {"checked": True, "reason": str(reason or ""),
            **{name: int(counts[name]) for name in AGENT_STATES},
            "active": int(counts["active"]), "total": int(counts["total"]),
            "labels": dict(AGENT_STATE_LABELS)}


def _roster_open_count(task_ids: Sequence[str], *,
                       agents: Mapping[str, Mapping[str, Any]],
                       items: Mapping[str, Mapping[str, Any]]) -> int:
    """这一项名下「还没收口」的活有几件 —— 唯一口径是 `boardrows.row_is_open`。

    ## 为什么不能数 `status ∈ {pending, running}`

    `tasks` 混着两类行：代理行（`kind` 为空，`status` 就是它的真实状态）与板项行
    （`kind` 非空，`status` 设计上恒为 `pending`，它是类型标记；真正的收口在
    `item_state` / `item_close`）。直接数 `status` 会把"已经收口的通知"读成
    "还堆着的待办"（`boardrows.py` 的模块 docstring 与 `row_is_open` 逐字写了这件事）。
    名册项名下那串编号今天都是代理行，所以旧写法在今天的盘上碰巧不出错；但口径必须是
    产品那一个 —— 板项行一旦出现在这一串里（板项/委托一类的编号被登记成"接过的活"），
    旧写法就会把它算成一件未收口的活。

    三态：两个映射都查不到（编号没有台账行）⇒ `row_is_open({})` 是 `False`
    （"没有这一行"不是"还欠着"；调用方另用 `task_found` 报"这一行不在台账里"）。
    """
    from ..boardrows import row_is_open

    return sum(1 for task_id in task_ids
               if row_is_open(agents.get(str(task_id))
                              or items.get(str(task_id)) or {}))


def _roster_root_identity(role: str, name: str) -> tuple[str, str]:
    """根节点的身份：它不在任何人的名册里，名字固定是主控。

    业主：「顶层能不能标 M 啊，unknown 很怪」—— 只按盘上原样显示，这一格就是
    「（顶层·无名册名）」加一枚 `unknown` 角色徽标，而那两格空串并不是"读坏了"：
    根是顶趟那一股，它确实不在任何人的名册里（名册只记"某个父名下有哪些子"）。

    所以读侧把它补成主控：`role` / `name` 两格空串 ⇒ `schema.CONDUCTOR_ROLE`
    （同一个常量，不另写一份字面量）。这是读侧给顶层定的身份，不是名册分配的名字：
    `roster_add` 改不了它（它只写 `<父>.jsonl` 里属于某个父的那些项，而根不是谁的子）。

    只补空串：写侧真给了名字就照写侧，本层不覆盖盘上事实。调用方只在根节点上调它
    （判据：`parent_task_id` 是空串、`depth == 1`）；子节点的空名仍然按原样交给页面。
    """
    from ..schema import CONDUCTOR_ROLE as M  # noqa: PLC0415 - 只取一个常量，不为它动模块级 import

    return (str(role or M), str(name or M))


def roster_face(root: str | Path, *, limit: int = ROSTER_NODES_MAX,
                inbox_items: int = ROSTER_INBOX_ITEMS) -> dict[str, Any]:
    """`GET /api/roster` 的读模型：当前工作区整棵名册树（只读、三态）。

    ## 一个节点是什么（D-66 更正：一个节点 = 一个常驻子代理，不是一件活）
    业主的两句口径：「一个子代理可接收多个任务」「不可按照任务号记录名册」。
    所以节点是名册项（`owner` + `name` 定的身份），它下面挂这个子代理接过的那些活：

    | 字段 | 盘上来源 |
    |---|---|
    | `task_id`（节点键） | 这一项"建项那件活"的绝对编号（只在名册项一行都读不到活编号时降级成 `<父>/<名>`）；它只是页面用的键，身份是 `owner` + `name` |
    | `name`（名册名） | `<父>.jsonl` 里这一项的 `name`（根不在任何人的名册里 ⇒ 读侧补成主控，见下） |
    | `role` | 同一行的 `role`（读不到 ⇒ 台账 `tasks` 的 `role`；根同样补成主控） |
    | `parent_task_id` | 父节点键（父那一份名册里接走父的那个名册项的节点键） |
    | `parent_name` | 父节点的 `name`（现算，不另存；父是根时它就是下一条补出来的那个名字） |
    | `children[]` | 这一项名下那些名册项（各带 `task_id` 节点键 + `name` + `role` + `retired`） |
    | `tasks[]` | 这个子代理接过的每一件活：`task_id` / `role` / `status` / `started_at` / `ended_at` / `task_found` / `brief` / `detail`（调用流水来自 `<父>-index.jsonl`，状态与时间来自 `data/tasks.json`） |
    | `retired` / `retired_branch` | 折叠后的 `retired` / 那一行的 `branch` |
    | `brief` / `brief_source` / `surface` | 这一项的 `brief` / `brief_source` / `surface` |
    | `status` / `task_found` / `in_flight` | 最近一件活的状态 / 它的活是否都在台账里 / 这一项名下有几件未收口（唯一口径 `boardrows.row_is_open`：板项按 `item_state`、代理行按 `status`） |
    | `state` / `state_reason` | 三态（在飞 / 待机 / 静默 / 未读到），判定只有 `conductor.agent_state` 一处；`state_reason` 是"为什么判成这一格"的那句人话（`unknown` 时必有） |
    | `stalled` / `stalled_sec` / `stalled_reason` | 疑似停滞（`conductor.agent_state` 的同一格）：最近一步离现在多少秒。落痕是 `out/steps/<台账号>.jsonl`（NAMEFIX-B1，2026-11-22：一行一步、追加的轨迹，`conductor.step_beats` 取最后一行；改前盘上只有一个"最后一次步号"的指针文件 `.json`，名字叫 steps 而盘上没有步）。`state` 仍是 `flying` —— 停滞不改三态，也绝不许因此销号（停滞不等于静默） |
    | `inbox` | 这一项名下所有活收到的板项行（见 :func:`_roster_inbox`） |
    | `depth` | 名册链现算：根 = 1（口径写在下面） |

    ## 根的名字固定是主控（业主：「顶层能不能标 M 啊，unknown 很怪」）
    根（`parent_task_id` 是空串、`depth == 1`）不在任何人的名册里 —— 名册只记
    "某个父名下有哪些子"，而根不是谁的子 —— 所以盘上读不到它的 `name` 与 `role`
    （两格都是空串）。这不是"读坏了"，但页面照原样画出来是「（顶层·无名册名）」
    加一枚 `unknown` 角色徽标，读的人以为这一格没查到。

    所以这一层把那两格补成主控（:func:`_roster_root_identity`，常量取
    `schema.CONDUCTOR_ROLE`）：根的名字是 `M`、角色也是 `M`。这是读侧给顶层定的
    身份，不是名册分配的名字，不能靠 `roster_add` 改（它只写 `<父>.jsonl` 里属于某个
    父的那些项）。子节点一律不补名：它们的名字只可能来自名册，空串就是"名册上没有"。

    ## 两份形状，同一份读（业主）
    业主：「名册按树展开，不只是简单按层展开。」⇒ 这个读数里有两份形状，
    都由上面那一次读盘折出来的名册项派生，不重读文件、不重算折叠：

    - `children_of`：`{父节点键: [直接子节点键...]}`，子按落盘行序
      （`<父>.jsonl` 的行序；只在对照表里出现的名字排在它后面，按对照表的行序）。
      它是"谁是谁的直接子"的那一份，页面的树照它递归。
    - `nodes`：按层排（BFS）的节点读数（`depth` / 角色 / 子数 / 状态 / 收件箱那一格 /
      `tasks`）。这一份只管"每个节点有什么读数"，不管"谁是谁的子"—— 拿它按 `depth`
      缩进画出来就是 d1 / d2 d2 d2 / d3 ... 的按层平铺，同一个名册名在两层各出现一次，
      读不出父子（`draft/146`）。

    截断那一档（`truncated=true`）只截 `nodes`：`children_of` 仍是完整的父子关系，
    所以它可能点到不在 `nodes` 里的编号 —— 那是"这次没画它"，不是"它不存在"。

    ## 归属：名册项接过的活，挂在"那件活的父"名下（D-66 的修法）
    两份盘上事实各管一半：`<父>.jsonl` 的 `add` 行说"这个父名下有哪几个子代理
    （名册项）"，`<父>-index.jsonl` 的每一条调用记录说"这一件活落到了哪个名字上"。
    把调用记录按名册名归组，就得到"一个节点 + N 件活"。

    只读折叠后的对照表会错在两处，缺一不可：
    1. 只把折叠后的对照表并进来（一个名字只剩第一次与当前两次调用）⇒ 中间那几件活
       被扔掉，而它们自己的名册文件让它们看起来像根（真机 d1 上的 `t-000039` /
       `t-000068` 就是这么来的）；
    2. 把"同一名字的两次调用"当成两个子 ⇒ 同一个子代理在树上出现好几次（"重号"的
       错觉）。

    `task_id` 在任何一层都不是归属键：名册项的身份是 `owner` + `name`；`tasks[]` 里的
    编号只是"这个子代理接过哪些活"的流水读数。

    ## 拼不上的怎么办（平铺并点名，不抬成 d1 根）
    台账里有父、可名册正文与对照表都没说"谁接过它"的那些代理行，摆进 `unplaced`
    （带自己的父、角色、状态与时间），并在 `diagnostics` 里点名。它们不进 `nodes`、
    也不进 `roots` —— 抬成树根等于替盘上事实改口径。

    ## 深度：`depth` 是"这一棵树里的距离"，不是 `tasks.depth`
    `tasks.depth` 是全局召唤深度（主控发起 = 1，`schema.Task.depth` 的 docstring
    逐字如此）；本函数的 `depth` 是"离这棵树根的层数，根 = 1"。两者在"根就是顶趟那股"
    时相等，而在"根是某一支子树的头"时差一个常数 —— 混用会让读的人以为看见了两个
    不同的深度。前端只显示这一个（树里的相对位置才是名册树要说的事）。

    折叠口径与写侧同一处实现（`secretary._fold_roster`：`add` 建项、`bind` 只推
    调用读数、`retire` 标退役、`keep_alive` 只记那一格）。这里不另写一份折叠 ——
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
    - `states`：三态合计（`flying` / `standby` / `silent` / `unknown` 各几个，
      外加 `active` = 在飞 + 待机 与 `total`）。四格是 `number | null`：
      `null` 是"没读到"（名册没读到 / 台账没读到 / 时钟读不成），不是 0。
      逐节点那一格 `state` 同样是三态，`state_reason` 说清"为什么是这一档"。
      判定（含"待机 = 时钟上挂着等待或名下有在飞的直接子"）只有
      `conductor.agent_state` 一处；本函数只做"一个节点接过好几件活 ⇒ 取最活跃的那一格"
      这一层聚合（`conductor.most_active_state`）。

    ## 规模
    节点上限 `limit`（默认 :data:`ROSTER_NODES_MAX`），超了截断并置 `truncated`；
    一个节点的收件箱只列 `inbox_items` 条（`inbox.more` 报剩下几条）。`nodes` 是
    按层排的（BFS：父一定在子前面），`children_of` 是父子关系那一份 —— 页面画树用
    后者，前者给每个节点的读数。
    """
    from ..secretary import _fold_roster    # noqa: PLC0415 - 折叠口径的唯一实现
    from ..store import Store               # noqa: PLC0415 - 台账那一栏

    root_p = Path(str(root))
    dir_p = root_p.joinpath(*_ROSTER_DIR)
    #: 顶层键集合在每一档都一模一样（契约判据 C 拿 `set(RosterView)` 与 TS 比对，
    #: 而"某档少一个键"会让那条判据红在一件与类型毫无关系的事上）。
    out: dict[str, Any] = {
        "answer": "unknown", "tri": TRI_NOT_APPLICABLE, "reason": "",
        "root": str(root_p), "dir": str(dir_p),
        "nodes": [], "roots": [], "children_of": {}, "count": None, "max_depth": None,
        "files": [], "diagnostics": [], "truncated": False,
        "coverage": {"tasks_agents": None, "roster_nodes": None, "unrostered": None},
        "tasks_tri": TRI_NOT_APPLICABLE, "tasks_reason": "", "unplaced": [],
        #: 三态合计（`conductor.state_counts`）：四档各几个 + `active`（在飞 + 待机）。
        #: 计数格是 `number | null` —— `null` 是"没读到"，`0` 是"读到了、里面是 0 个"。
        "states": _roster_states_blank("名册没读到 ⇒ 三态合计不给 0（0 是很强的结论）"),
    }

    if not dir_p.exists():
        fb = _roster_from_tasks(root_p)
        out.update({k: fb[k] for k in _ROSTER_FALLBACK_KEYS})
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

    found, index_found, why = _roster_files(dir_p)
    if why:
        out["tri"] = TRI_UNREADABLE
        out["reason"] = why
        return out
    if not found and not index_found:
        fb = _roster_from_tasks(root_p)
        out.update({k: fb[k] for k in _ROSTER_FALLBACK_KEYS})
        out["reason"] = (
            f"{dir_p} 在盘上但一个 <父编号>.jsonl 都没有（还没有人往名册里写过一行）⇒ "
            "answer=unknown。" + fb["reason"])
        out["diagnostics"].append(out["reason"])
        return out

    diagnostics: list[str] = []
    problems: list[str] = []
    #: 每份 `<父>.jsonl` 折叠出来的名册项（一项 = 一个常驻子代理：名字 / 角色 / 简介 / 面）。
    items_by_owner: dict[str, list[dict[str, Any]]] = {}
    #: 每份 `<父>.jsonl` 的原始行（按文件里的行序）。它只在这里读一次，下面用它编
    #: "落盘行序"，于是"按父子"的那一份形状不必回头再扫一遍文件。
    rows_by_owner: dict[str, list[dict[str, Any]]] = {}
    #: 名册正文有坏行 / 读不出来的那几份（owner）。那几份的"已销号"那一格判不了 ——
    #: 坏掉的那一行可能正是一条 `retire` 记录 ⇒ 三态只能是 `unknown`（不是静默）。
    roster_bad_owners: set[str] = set()
    for owner, path in found:
        rows, bad, state = read_jsonl_state(path)
        if state == "unreadable":
            problems.append(f"{path.name} 读不出来：{bad[0] if bad else '未知原因'}")
            roster_bad_owners.add(owner)
            continue
        if bad:
            # 坏行一律算「没查成」（本模块 `_face` 的同一条口径：把"文件坏了"读成
            # "还没写过"是本项目最贵的一类缺陷）。好行照常渲染 —— 与 `artifacts_face`
            # 的"整面 unreadable 并点名，读得出来的栏照常给行"同一条做法。
            problems.append(f"{path.name} 有 {len(bad)} 行读不出来（{bad[0]}）")
            roster_bad_owners.add(owner)
        items_by_owner[owner] = _fold_roster(rows)
        rows_by_owner[owner] = [dict(r) for r in rows]
        out["files"].append(path.name)
        if not items_by_owner[owner]:
            diagnostics.append(f"{path.name} 里一条子代理记录都没有（文件在、读成了 0 行）")
        # 只有任务号、没有名册名的行：本层不认（名册项的身份是 owner + name）。
        nameless = [str(r.get("task_id") or "") for r in rows
                    if str(r.get("name") or "") == "" and str(r.get("task_id") or "")]
        if nameless:
            diagnostics.append(
                f"{path.name} 有 {len(nameless)} 行只写任务号、没写名册名（头几个："
                + "、".join(nameless[:3])
                + "）⇒ 不拿任务号当名册项的身份，那几行不建项、只在这里点名")

    # ---- 对照表：`<父>-index.jsonl` 的调用记录（每一条 = 某件活落到了哪个名册项上）
    #
    # 这一层读的是"这件活是谁接的"，不是"这个父名下有哪些子"。名册项（常驻子代理）
    # 由上面那份名册正文定义；对照表只是调用流水，于是同一个名字接过 N 件活时 N 件
    # 都在这里、树里仍是那一个节点。只读折叠后的对照表（一个名字只留第一次与当前
    # 两次调用）会把中间的几次调用折叠掉 —— 真机 `t-000002` 名下的 F1 接了 5 件，
    # 被扔掉的 3 件因此被当成了树根（d1 上那一级的 `t-000039` / `t-000068`）。
    work_by_owner: dict[str, list[dict[str, Any]]] = {}
    index_rows_by_owner: dict[str, list[dict[str, Any]]] = {}
    for owner, path in index_found:
        rows, bad, state = read_jsonl_state(path)
        if state == "unreadable":
            problems.append(f"{path.name} 读不出来：{bad[0] if bad else '未知原因'}")
            continue
        if bad:
            problems.append(f"{path.name} 有 {len(bad)} 行读不出来（{bad[0]}）")
        calls = _roster_work_rows(rows)
        if calls:
            work_by_owner[owner] = calls
        index_rows_by_owner[owner] = [dict(r) for r in rows]
        out["files"].append(path.name)
        if not calls:
            diagnostics.append(f"{path.name} 里一条调用记录都没有（文件在、读成了 0 行）")
        # 只有任务号、没有名册名的行：本层不认（名册项的身份是 owner + name）。
        nameless = [str(r.get("task_id") or "") for r in rows
                    if str(r.get("name") or "") == "" and str(r.get("task_id") or "")
                    and str(r.get("kind") or "") != "retire"]
        if nameless:
            diagnostics.append(
                f"{path.name} 有 {len(nameless)} 行只写任务号、没写名册名（头几个："
                + "、".join(nameless[:3])
                + "）⇒ 不拿任务号当名册项的身份，那几行只当坏行点名")
    half = sorted(set(work_by_owner) - set(items_by_owner))
    if half:
        diagnostics.append("、".join(half)
                           + " 只有对照表 `<父>-index.jsonl`、没有名册 `<父>.jsonl`"
                           "（半份登记：名册那一笔没落成 ⇒ 名册项只能从调用记录里认出来）")

    # ---- 父 → 名册项 索引（一项 = 一个常驻子代理；它下面挂 N 件活）
    #
    # 归属的方向是"这件活属于哪个名册项"，不是"名册项里列一串任务号"：这里按
    # 名册名把调用记录归到项上，`tasks` 只是这一项的调用流水读数（每件活各带
    # 自己的时间与状态）。于是"一个节点 + N 件活"是树的常态形状。
    items_of_owner: dict[str, list[dict[str, Any]]] = {}
    for owner in sorted(set(items_by_owner) | set(work_by_owner)):
        by_name: dict[str, dict[str, Any]] = {}
        order: dict[str, int] = _roster_name_order(rows_by_owner.get(owner) or [],
                                                   index_rows_by_owner.get(owner) or [])
        for item in items_by_owner.get(owner) or []:
            name = str(item.get("name") or "")
            if not name:
                diagnostics.append(f"{owner} 的名册里有一项没有名字 ⇒ 那一项摆不出来")
                continue
            got = dict(item)
            got["tasks"] = []
            got["task_brief"] = {}
            by_name[name] = got
        # 正文里的创建那一次（`task_id` 是"它是为哪件活建的"的读数，不是身份）。
        for name, item in by_name.items():
            born = str(item.get("first_task_id") or item.get("task_id") or "")
            if born:
                item["tasks"].append(born)
                item["task_brief"][born] = str(item.get("brief") or "")
        for call in work_by_owner.get(owner) or []:
            name = str(call.get("name") or "")
            item = by_name.get(name)
            if item is None:
                item = {"name": name, "role": str(call.get("role") or ""), "brief": "",
                        "brief_source": "", "surface": "", "retired": False,
                        "tasks": [], "task_brief": {}}
                by_name[name] = item
                diagnostics.append(
                    f"{owner} 的名册正文里没有 {name} 这一项，但对照表里有它接过的活 ⇒ "
                    "按调用记录认它（半份登记：名册那一笔没落成）")
            tid = str(call.get("task_id") or "")
            if tid and tid not in item["tasks"]:
                item["tasks"].append(tid)
                item["task_brief"][tid] = str(call.get("brief") or "")
        merged: list[dict[str, Any]] = list(by_name.values())
        # 一项的节点编号 = 它是为哪件活建的（那个绝对编号）。它只是一个显示用的键：
        # 身份是 owner + name，任务号永远不当归属键（见 `_roster_work_rows`）。
        for item in merged:
            tasks = item["tasks"]
            item["task_id"] = str(tasks[0]) if tasks else f"{owner}/{item['name']}"
            if not tasks:
                diagnostics.append(
                    f"{owner} 名下的 {item['name']} 没有任何一件活的编号 ⇒ 节点键降级为 "
                    f"{item['task_id']!r}（它是什么就是什么，不猜一个编号）")
        merged.sort(key=lambda it: order.get(str(it.get("name") or ""), len(order)))
        items_of_owner[owner] = merged

    if not items_of_owner:
        out["tri"] = TRI_UNREADABLE if problems else TRI_NOT_APPLICABLE
        out["reason"] = ("；".join(problems) if problems else
                         f"{dir_p} 下的名册文件里一个名册项都没有 ⇒ answer=unknown")
        out["diagnostics"] = diagnostics
        return out

    # ---- 谁是谁的子：一个名册项挂在"它接的那件活的父"名下
    #
    # 一件活被哪个名册项接走，那一项就挂在那件活的父名册里的对应项下面。所以先把
    # 任务号 → 名册项节点 的映射建出来，再把每个 owner 的那些项挂到它的父节点上。
    owner_of_task: dict[str, str] = {}
    node_of_task: dict[str, str] = {}
    node_row: dict[str, dict[str, Any]] = {}
    #: 节点键 → 它是哪一份名册里的项（三态要问"这一份名册的正文读成了没有"）。
    owner_of_node: dict[str, str] = {}
    for owner, items in items_of_owner.items():
        for item in items:
            node = str(item.get("task_id") or "")
            if not node:
                continue
            if node in node_row and node_row[node] is not item:
                diagnostics.append(
                    f"{node} 同时是两个名册项的节点键（只认先读到的那一项；"
                    "名册项的身份是 owner + name）")
            node_row.setdefault(node, item)
            owner_of_node.setdefault(node, owner)
            for tid in item["tasks"]:
                owner_of_task.setdefault(tid, owner)
                node_of_task.setdefault(tid, node)

    def _parent_node(owner: str) -> str:
        """这个 owner 的项该挂在哪：它自己是被哪一项接走的（单条执行那一档就是它自己）。"""
        node = node_of_task.get(owner)
        if node is None:
            return owner
        if owner_of_task.get(owner) == owner:
            return owner
        return node

    def _is_root(owner: str) -> bool:
        """它是不是一棵树的顶：没有谁接过它，或者接它的就是它自己名下的那一项。"""
        if owner not in node_of_task:
            return True
        return owner_of_task.get(owner) == owner

    #: 父节点键 → 它名下的名册项（一个项 = 一个子代理）。形状与旧的"父 → 子"同构，
    #: 仍交给 `_roster_children_of` 做唯一一次"按落盘行序排 + 去掉空编号"的收口：
    #: 那一处是"谁是谁的直接子"的唯一实现，判据的反真空也打在它上面。
    kids_of_parent: dict[str, list[dict[str, Any]]] = {}
    for owner in sorted(items_of_owner):
        parent_node = _parent_node(owner)
        kids = [item for item in items_of_owner[owner]
                if str(item.get("task_id") or "") and str(item.get("task_id")) != parent_node]
        if not kids:
            continue
        # 同一个名册项可能接过好几件活，而每件活自己名下都有一份名册 ⇒ 这几份名册的
        # 子都属于那一个名册项（一个节点、它的子树是几件活各自的下级并起来）。
        bucket = kids_of_parent.setdefault(parent_node, [])
        for item in kids:
            node = str(item.get("task_id") or "")
            if node and all(str(k.get("task_id") or "") != node for k in bucket):
                bucket.append(item)
    #: 根 = 它不是任何名册项接走的活（顶趟；以及"父那一份名册读不到"的那些）。
    #: 多根是合法的：一个工作区可以有好几趟顶趟，每一趟自己是一棵树。
    roots = [owner for owner in sorted(items_of_owner) if _is_root(owner)]
    if not roots:
        roots = [sorted(items_of_owner)[0]]
        diagnostics.append("名册链成环（每一个项都是别人接走的活）⇒ 从字典序最小的"
                           "那一份起读，深度按链上第一次见到的位置算")
    children_of = _roster_children_of(kids_of_parent, roots)

    #: 节点 → 父节点（与 `children_of` 同一份 `_parent_node` 映射的另一种投影：
    #: `children_of` 说"谁挂在谁下面"，这一份说"我的父是谁"。两份都由同一处算出，
    #: 生产上不可能打架；而节点自己的 `parent_task_id` / `depth` 从这一份取，
    #: 于是"把 children_of 打桩成平的一层"这件事会当场露馅（判据 ④）。
    parent_of_node: dict[str, str] = {}
    for owner in sorted(items_of_owner):
        parent_node = _parent_node(owner)
        for item in items_of_owner[owner]:
            node = str(item.get("task_id") or "")
            if node and node != parent_node:
                parent_of_node.setdefault(node, parent_node)

    def _depth_of(node: str) -> int:
        """离根几层（根 = 1）；成环或超过 64 层 ⇒ 停在那里（坏链不许变成死循环）。"""
        depth, cur, guard = 1, node, 0
        while guard <= 64:
            parent = parent_of_node.get(cur, "")
            if not parent or parent == cur:
                return depth
            cur, depth, guard = parent, depth + 1, guard + 1
        return depth



    # ---- 台账（`status` / `in_flight` / 收件箱那一栏的唯一来源）
    tasks_by_tid: dict[str, dict[str, Any]] = {}
    in_flight_by_tid: dict[str, int] = {}
    board_by_recipient: dict[str, list[dict[str, Any]]] = {}
    #: 板项行按它自己的编号索引（`board_by_recipient` 是按收件人分的另一半）：
    #: 名册项名下那串编号里若出现一条板项，`row_is_open` 要读得到它，才不会把
    #: `status=pending` 这个类型标记当成"还欠着活"。
    board_by_tid: dict[str, dict[str, Any]] = {}
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
                board_by_tid[tid] = row
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

    # ---- 按层排的节点读数（BFS：父一定在子前面；深度上限 64 与
    # `conductor.inside_subtree` 同一条纪律）。一个节点 = 一个名册项（常驻子代理），
    # 它下面挂着"这个子代理接过的那些活"（`tasks`，每件各带自己的时间与状态）。
    # 这一份不承担"谁是谁的子"（那一件由上面的 `children_of` 说）。
    #
    # 节点上的"子 N"只数名册项 —— 名册项少一个，
    # 父的子树读数就比台账低一个，而少的那一个既不在这棵树里、也不在任何一处说
    # "它是谁的儿子"。所以每个节点补三格：`children_in_ledger`（台账里的子数 ——
    # 这个名字量的是"这个节点在台账里挂了几个子"，含没落名册的；收工读数里那个
    # `child_count` 量的是"名册里还有几个没销号的项"，两个不同量故两个名，见 153-U-13）、
    # `roster_child_count`（名册项数）、`unrostered_children`（有父、没落名册的那些：
    # 编号 + 角色 + 状态，挂在父节点下看得见，同时仍进页面底部的 `unplaced`）。
    #
    #: 台账里"谁是谁的子"（只数代理行：板项的 `parent_task_id` 是收件人，不进这张表）。
    ledger_kids: dict[str, list[str]] = {}
    for tid, r in tasks_by_tid.items():
        pid = str(r.get("parent_task_id") or "")
        if pid:
            ledger_kids.setdefault(pid, []).append(tid)
    #: 台账那一栏读成没有：读不到就一律 None / 空数组（"没查成"不是"没有子"）。
    tasks_read = out["tasks_tri"] == TRI_COMPUTED
    # ---- 三态（在飞 / 待机 / 静默 / 未读到）：判定在 `conductor.agent_state`，
    # 本层只做三件事 —— 读一次时钟簿记（`conductor.clock_waiters`）、把"这一项是
    # 哪几件活的代理"那份事实交给它（含 `retired`：已销号 ⇒ 静默在那里面判）、
    # 再把"一个节点接过好几件活"聚合成一格（`conductor.most_active_state`）。
    roster_clock = clock_waiters(root_p)
    #: 已销号的名册项用了哪些编号（名册那一层的事实，交给判定本体，这里不另判一遍）。
    retired_ids: dict[str, bool] = {}
    for _owner, _items in items_of_owner.items():
        for _item in _items:
            if not _item.get("retired"):
                continue
            for _tid in list(_item.get("tasks") or []) + [str(_item.get("task_id") or "")]:
                if _tid and _tid in tasks_by_tid:
                    retired_ids[_tid] = True
    three: dict[str, dict[str, Any]] = {}
    if tasks_read:
        three = agent_states(list(tasks_by_tid.values()), clock=roster_clock,
                             retired=retired_ids)
    #: 三态合计读不成的那一句理由（空串 = 读成了）。
    states_problem = ""
    if not tasks_read:
        states_problem = (f"台账读不成（{out['tasks_reason'] or '没查成'}）⇒ "
                          "在飞 / 待机 / 静默判不了")
    if not roster_clock.get("checked"):
        states_problem = (f"时钟读不成（{roster_clock.get('reason') or '没查成'}）⇒ "
                          "在飞 / 待机 / 静默判不了")
    nodes: list[dict[str, Any]] = []
    seen: set[str] = set()
    max_depth = 0
    queue: list[tuple[str, str, int]] = [(owner, "", 1) for owner in roots]
    while queue and len(nodes) < max(1, int(limit)):
        tid = queue.pop(0)[0]
        if tid in seen:
            continue
        seen.add(tid)
        row = node_row.get(tid) or {}
        parent_tid = parent_of_node.get(tid, "")
        depth = 1 if tid in roots else _depth_of(tid)
        parent_row = node_row.get(parent_tid) or {}
        task_ids = [str(t) for t in (row.get("tasks") or []) if str(t)]
        task_readings: list[dict[str, Any]] = []
        inbox_rows: list[dict[str, Any]] = []
        for task_id in task_ids:
            trow = tasks_by_tid.get(task_id) or {}
            if task_id in board_by_recipient:
                inbox_rows.extend(board_by_recipient[task_id] or [])
            task_readings.append({
                "task_id": task_id,
                "role": str(trow.get("role") or row.get("role") or ""),
                "status": str(trow.get("status") or ""),
                "started_at": str(trow.get("started_at") or ""),
                "ended_at": str(trow.get("ended_at") or ""),
                "task_found": bool(trow),
                "brief": str((row.get("task_brief") or {}).get(task_id)
                             or (row.get("brief") if task_id == task_ids[0] else "") or ""),
                "detail": _roster_clip(str(trow.get("detail") or ""), 80),
            })
        # 节点上的"当前状态"取最近一次接的活（`tasks` 按落盘行序，最后一条是最近的）；
        # 在飞则是"这一项名下有几件还没收口"（一个子代理可以同时有好几件在飞）。
        # 口径是 `boardrows.row_is_open`（板项按 item_state、代理行按 status），
        # 不是"status ∈ pending/running" —— 后者会把已收口的板项读成假积压。
        current = task_readings[-1] if task_readings else {}
        live = _roster_open_count(task_ids, agents=tasks_by_tid, items=board_by_tid)
        kids = [k for k in (children_of.get(tid) or []) if k]
        # 这个节点名下的台账子：节点键本身那一行（顶趟 / 名册项的建项那件活）的
        # 直接子，加上它接的每一件活（`tasks[]`）各自的直接子 —— 并起来。
        # 名册项没接走的那些是"有父、没落名册"，与页面底部的 `unplaced` 同一个判据
        # （`owner_of_task` 里没有它）：两处口径一致，不是二选一。
        ledger_child_ids: list[str] = [k for k in ledger_kids.get(tid, ()) if k]
        for one_task in task_ids:
            for kid_id in ledger_kids.get(one_task, ()):
                if kid_id not in ledger_child_ids:
                    ledger_child_ids.append(kid_id)
        unrostered_kids = (_roster_unrostered_children(
            ledger_child_ids, tasks_by_tid=tasks_by_tid, registered=owner_of_task)
            if tasks_read else [])
        # 这一项的三态：它接过好几件活 ⇒ 取最活跃的那一格（`most_active_state`）。
        # 已销号 ⇒ 静默（销号即退场，不在活跃集合里）；名册正文有坏行 ⇒ 那一格判不了。
        # 节点键本身也算一件活的编号（树根不是任何人的名册项，它的 `tasks` 是空的，
        # 而它自己那一行台账明明在 —— 不看它会把根读成"判不了"）。
        node_owner = owner_of_node.get(tid, "")
        state_ids = list(task_ids)
        if tid in tasks_by_tid and tid not in state_ids:
            state_ids.insert(0, tid)
        states_here = [str((three.get(one) or {}).get("state") or AGENT_STATE_UNKNOWN)
                       for one in state_ids]
        state = most_active_state(states_here)
        state_reason = ""
        if states_problem:
            state = AGENT_STATE_UNKNOWN
            state_reason = states_problem
        elif not state_ids or not any(one in three for one in state_ids):
            state = AGENT_STATE_UNKNOWN
            state_reason = "台账里没有这一项接过的活的任何一行 ⇒ 它有没有在跑判不了"
        elif node_owner in roster_bad_owners:
            state = AGENT_STATE_UNKNOWN
            state_reason = (f"{node_owner} 那一份名册有坏行 ⇒ 它有没有销号判不了"
                            "（坏掉的那一行可能正是一条 retire）")
        else:
            for one in state_ids:
                cell = three.get(one) or {}
                if str(cell.get("state") or "") == state and str(cell.get("reason") or ""):
                    state_reason = str(cell.get("reason") or "")
                    break
        # 疑似停滞（`conductor.agent_state` 的同一格）：一个节点接过好几件活 ⇒ 只要有一件
        # "在飞却没动静"就标出来，秒数取最大的那一件（最久没动的）。它不是第四档：
        # `state` 照旧是 flying，销号门也照旧按"在飞"拒绝 —— 停滞不等于静默。
        stalled = False
        stalled_sec: float | None = None
        stalled_reason = ""
        if not states_problem and state == "flying":
            for one in state_ids:
                cell = three.get(one) or {}
                if not cell.get("stalled"):
                    continue
                sec = cell.get("stalled_sec")
                if stalled_sec is None or (isinstance(sec, (int, float)) and sec > stalled_sec):
                    stalled_sec = sec if isinstance(sec, (int, float)) else stalled_sec
                if not stalled_reason:
                    stalled_reason = str(cell.get("stalled_reason") or "")
                stalled = True
        # 根（`parent_task_id` 是空串）不在任何人的名册里 ⇒ 它的 role / name 那两格
        # 盘上是空串，补成主控（见 :func:`_roster_root_identity` 与 docstring 那一节）。
        # 子节点一律不补：它们的空名照原样交给页面（那是"名册上没有"，不是"它是主控"）。
        node_role = str(row.get("role") or current.get("role") or "")
        node_name = str(row.get("name") or "")
        if not parent_tid:
            node_role, node_name = _roster_root_identity(node_role, node_name)
        # 父的名字现算（不另存）：父是这一棵树的根时，它就是上面补出来的那一个 ——
        # 否则"根叫 M"与"它的子说父没有名册名"会互相打脸。
        parent_name = str(parent_row.get("name") or "")
        if parent_tid and parent_tid in roots:
            _, parent_name = _roster_root_identity("", parent_name)
        node: dict[str, Any] = {
            "task_id": tid,
            "name": node_name,
            "role": node_role,
            "depth": int(depth),
            "parent_task_id": str(parent_tid),
            "parent_name": parent_name,
            "children": [{"task_id": k,
                          "name": str((node_row.get(k) or {}).get("name") or ""),
                          "role": str((node_row.get(k) or {}).get("role") or ""),
                          "retired": bool((node_row.get(k) or {}).get("retired"))}
                         for k in kids],
            # 子数按台账数（读不到台账 ⇒ null，不是 0）；名册项数是其中"落了名册"的那部分。
            "children_in_ledger": (len(ledger_child_ids) if tasks_read else None),
            "roster_child_count": len(kids),
            "unrostered_children": (unrostered_kids if tasks_read else []),
            "retired": bool(row.get("retired")),
            "retired_branch": str(row.get("retired_branch") or ""),
            "brief": str(row.get("brief") or ""),
            "brief_source": str(row.get("brief_source") or ""),
            "surface": str(row.get("surface") or ""),
            "status": str(current.get("status") or ""),
            # 三态（`conductor.agent_state` 是唯一实现）+ 那一句"为什么是这一档"。
            "state": state,
            "state_reason": state_reason,
            # 疑似停滞（业主第二条）：`state` 仍是 flying；这一格只是
            # "它最近一步离现在多久"，页面上画在徽标旁边。`stalled_sec` 是 `number | null`
            # （null = 这一格没读到，不是 0）。
            "stalled": stalled,
            "stalled_sec": stalled_sec,
            "stalled_reason": stalled_reason,
            "task_found": bool(task_readings) and all(tr["task_found"] for tr in task_readings),
            "in_flight": (live if out["tasks_tri"] == TRI_COMPUTED else None),
            "inbox": _roster_inbox(inbox_rows, tasks_tri=out["tasks_tri"],
                                   limit=inbox_items),
            "tasks": task_readings,
        }
        nodes.append(node)
        max_depth = max(max_depth, int(depth))
        if depth >= 64:
            diagnostics.append(f"{tid} 已经到深度 {depth} ⇒ 不再往下展开（坏链不许变成死循环）")
            continue
        for kid in kids:
            if kid not in seen:
                queue.append((kid, tid, depth + 1))

    truncated = bool(queue)
    if truncated:
        # 截断是规模的界，不是读失败：它不进 `problems`（`answer` 照旧是 "ok"），
        # 但必须在读数里说得出口 —— 静默截断等于让"树只有这么大"与"树被砍了"一样。
        diagnostics.append(f"名册节点超过上限 {int(limit)} ⇒ 只给了前 {len(nodes)} 个"
                           f"（`truncated=true`，还有 {len(queue)} 个没展开）")

    out["nodes"] = nodes
    out["roots"] = roots
    # 三态合计：读不成 ⇒ 每一格是 null（不是 0）+ 一句理由；读成了 ⇒ 四个真数字。
    out["states"] = (_roster_states_blank(states_problem) if states_problem
                     else _roster_states_of(nodes))
    out["children_of"] = children_of
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
    #
    # 平铺并点名（业主「找不到名册项时才平铺并点名，不许抬成 d1 根」）：
    # 台账里那些"有父、却不在任何名册项接过的活里"的代理行，摆进 `unplaced`（带
    # 自己的父、角色、状态与时间），并在诊断里逐个点名。它们不进 `nodes`、也不进
    # `roots` —— 把它们画成 d1 上的树根等于替盘上事实改口径（真机上那正是
    # `t-000039` / `t-000068` 被抬到 d1 的形态）。
    if out["tasks_tri"] == TRI_COMPUTED:
        with_parent = {tid: r for tid, r in tasks_by_tid.items()
                       if str(r.get("parent_task_id") or "")}
        unrostered = sorted(tid for tid in with_parent if tid not in owner_of_task)
        unplaced = [{"task_id": tid,
                     "parent_task_id": str(with_parent[tid].get("parent_task_id") or ""),
                     "role": str(with_parent[tid].get("role") or ""),
                     "status": str(with_parent[tid].get("status") or ""),
                     "started_at": str(with_parent[tid].get("started_at") or ""),
                     "ended_at": str(with_parent[tid].get("ended_at") or ""),
                     "why": "台账里有它这一行，名册正文与对照表里都没有任何名册项接过它"}
                    for tid in unrostered]
        out["unplaced"] = unplaced
        out["coverage"] = {"tasks_agents": len(tasks_by_tid),
                           "roster_nodes": len(nodes),
                           "unrostered": len(unrostered)}
        if unrostered:
            diagnostics.append(
                f"台账里有 {len(unrostered)} 个「有父的代理行」没有任何名册项接过（头几个："
                + "、".join(unrostered[:5])
                + "）—— 它们平铺在 `unplaced` 里，不抬成树根（名册那一格缺了它们的归属，"
                "这不是「名册上少了几个人」）")
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


def handle_obligations(handler: Any, params: Mapping[str, str],
                       query: Mapping[str, Sequence[str]]) -> None:
    """`GET /api/obligations`：板上四族义务的收件人读数（只读）。

    消费者是「在飞」页的义务卡。这个端点没有配对的 POST：收口（销号）只发生在
    `conductor` 的写路径上，网页不替人销号 —— 那样会让"这一条收过了"变成一次点击
    就能伪造的事实。
    """
    del params, query
    _json_of(handler, obligations_face(handler.root))


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
      # 业主「每一行都要带角色 + 绝对编号」：六件产物是文件清单、不是某条
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
      # `save_run_checkpoint` 补了收口三格。
      # 类型照写侧的真值（三格都是 `str(...)`，见 `save_run_checkpoint` 的 payload）：
      # `started_at` 空串 = 这一趟没真的开跑（不编）；`end_ts` 崩溃那档按写入时刻补；
      # `step_source` 是 `run` / `crash` 两档，说清 `step` 是从哪来的。
      ("step_source", "string"), ("started_at", "string"), ("end_ts", "string"),
      ("at", "string"))),
    # 顶趟的缓存汇总（`promptstability.summarize_prompt_cache` 的 11 格）。
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
     "run_view() 的 `report` —— 交付说明 `out/report/REPORT.md` 的读数",
     (("status", "ReportTri"), ("text", "string"))),
    ("RunView",
     "run_view() —— 一趟详情（`Run` + `report` + `checkpoint`）",
     (("tri", "Tri"), ("reason", "string"), ("sid", "string"), ("runs", "RunRow[]"),
      ("report", "ReportReadingView"), ("checkpoint", "CheckpointView | null"),
      ("checkpoint_reason", "string"), ("path", "string"),
      # 花销"两处一致"必须同范围比。下面四格给出
      # "同一趟"的两个数：检查点那一趟（同一 role）的累计，与这一段会话里
      # 同一 role 那一趟的事件求和。跨趟的合计另有其数（`runs`），不许拿来比。
      ("checkpoint_role", "string"),
      ("checkpoint_spend_usd", "number | null"),
      ("same_run_spend_usd", "number | null"),
      ("same_run_unknown_usd", "number"),
      ("same_run_start_index", "number | null"),
      # 162 ②：这一格里放的是"事件流有、没有任何一趟的自报账认得"的钱。它不进任何一趟的
      # `usd`（三态纪律：不许把一个没有主人的数摊给某一个主人）。
      ("unattributed_usd", "number | null"))),
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
    ("RunDigestView",
     "run_digest() —— 业主裁定「甲」的趟次档案：从会话事件流现算，不读也不落 "
     "`index/run-index.json`（收工没做成/被叫停的趟也有值；删掉事件流 ⇒ unreadable）",
     (("tri", "Tri"), ("reason", "string"),
      # `session` = 点名一段会话；`workspace` = 整个工作区的事件流。
      ("scope", "string"), ("sid", "string"),
      ("runs", "number | null"), ("unfinished", "number | null"),
      ("start_ts", "string"), ("end_ts", "string"),
      ("steps", "number | null"),
      # READFIX-E：`steps` 是"收工行自报优先"的混合值；两个分量与出处并排给，
      # 读的人才能看出 348（自报）vs 339（物理）不是同一个数。
      ("steps_source", "string"), ("steps_physical", "number | null"),
      ("steps_self_reported", "number | null"),
      ("steps_self_reported_missing_runs", "number | null"),
      # NUMCLAIM-②：`steps` 是混合口径时，这一句把「自报 / 物理 / 并起来」
      # 三个数并排说清（页面据此可复算，不靠读者猜 `steps_source` 指哪一个）。
      ("steps_note", "string"),
      # 两条独立的花销读数：`usd` 是事件求和，`spend_usd` 是收工行自报账；不互相顶替。
      ("usd", "number | null"), ("unknown_usd_calls", "number | null"),
      ("spend_usd", "number | null"), ("spend_missing_runs", "number | null"),
      # 派了多少活 / 验了几条 / 已签证明位 / 签文件几份；`*_missing_runs` 说清"没读到"的范围。
      ("dispatched", "number | null"), ("dispatched_missing_runs", "number | null"),
      # 2026-11-24：`dispatched_missing_runs` 的两档拆分（未收工 / 收工行没带 summons）
      # 与那句"这个数含什么、不含什么"（不含 notice 板项；不是"派了没跑"）。
      ("dispatched_missing_unfinished", "number | null"),
      ("dispatched_missing_no_summons", "number | null"),
      ("dispatched_note", "string"),
      ("verified", "number | null"),
      # 两个数、两套口径（84 的现场：signed_proofs=31 而 sign_files=3）：
      # `signed_proofs` 是收工读数里已签的证明位数；`sign_files` 是
      # `out/vsigns/*.json` 的文件数（含 issued.json 归档）。不共用一格。
      # `signed_proofs` 是收工读数里已签的证明位数；`sign_files` 是
      # `out/vsigns/*.json` 的文件数（含 issued.json 归档）；`recomputable_signs` 是
      # 复算通过的凭据份数（"签数"的唯一读数，前端读它）；`signs` 把签文件与签台账
      # 分开（见 `SignsView`：`files` 不含 `issued.json`，`ledger_present` 另算）。
      ("signed_proofs", "number | null"), ("sign_files", "number | null"),
      ("recomputable_signs", "number | null"), ("signs", "SignsView"),
      ("gaps_missing_runs", "number | null"),
      ("stop_reasons", "Record<string, number>"))),
    ("SignsView",
     "run_digest() 的 `signs` —— `out/vsigns/` 里两类东西分开数：逐份签文件"
     "（`files`，不含派生归档 `issued.json`）与那份台账本身"
     "（`ledger_present` / `ledger_path`）。口径单一来源是 "
     "`vsigns.credentials_reading`（它自己就排除了 INDEX_NAME）；"
     "`recomputable` 才是「签了几份」，`files` 是「目录里有几份签文件」。",
     (("checked", "boolean"), ("dir", "string"),
      ("files", "number | null"), ("recomputable", "number | null"),
      ("unbacked", "number | null"), ("ledger_present", "boolean"),
      ("ledger_path", "string"), ("why", "string"))),
    ("EvidenceView",
     "evidence_chain() —— 证据链八栏（各栏另带 `<栏>_tri`）",
     (("tri", "Tri"), ("reason", "string"), ("store_problems", "string[]"),
      ("statements", "StatementRow[]"), ("statements_tri", "Tri"),
      ("conjectures", "ConjectureRow[]"), ("conjectures_tri", "Tri"),
      ("experiments", "ExperimentRow[]"), ("experiments_tri", "Tri"),
      ("documents", "DocumentRow[]"), ("documents_tri", "Tri"),
      ("review_findings", "ReviewFindingRow[]"), ("review_findings_tri", "Tri"),
      ("relations", "RelationRow[]"), ("relations_tri", "Tri"),
      ("verifications", "VerificationRow[]"), ("verifications_tri", "Tri"),
      ("secretary", "SecretaryDecision[]"), ("secretary_tri", "Tri"),
      # 分页四格（AUDIT F12：真机 2.1 MB 一进来就卡）。「恒在」（`limit=0` 也写），
      # 于是页面不必猜"这一份是全量还是摘要"：`rows_mode="full"` ⇒ `rows_total` 与
      # 各栏 `length` 相等；`"page"` ⇒ `rows_total[栏]` 才是真实总行数。
      ("rows_mode", "string"), ("rows_limit", "number"),
      ("rows_offset", "number"), ("rows_total", "Record<string, number>"),
      # 字段档（与行那一轴独立）：`rows_fields="compact"` 时 `rows_omitted` 点名
      # 省掉的字段、`rows_clipped` 点名截断的字段（行上另有 `<字段>_truncated` /
      # `<字段>_chars`）、`rows_nested` 点名做了子对象投影的字段。`?full=1` 三格为空。
      ("rows_fields", "string"),
      ("rows_omitted", "Record<string, string[]>"),
      ("rows_clipped", "Record<string, string[]>"),
      ("rows_nested", "Record<string, string[]>"))),
    ("ArtifactsView",
     "artifacts_face() —— 产物面（各栏另带 `<栏>_tri`）",
     (("tri", "Tri"), ("reason", "string"),
      ("ledger", "ArtifactRow[]"), ("ledger_tri", "Tri"),
      ("ledger_verify", "LedgerVerifyRow[]"), ("ledger_verify_tri", "Tri"),
      ("handoffs", "HandoffRow[]"), ("handoffs_tri", "Tri"),
      ("checks", "AcceptanceCheck[]"), ("checks_tri", "Tri"),
      # 验收表在盘上的位置（`closing.ACCEPTANCE_TARGETS_NAME` 的单一口径；页面印它，
      # 不自己抄字面量 —— 这一份 2026-11-22 从 `out/paper/` 挪到了 `out/package/`）。
      ("checks_path", "string"),
      ("style", "ReportStyle"), ("style_tri", "Tri"),
      ("secretary", "SecretaryDecision[]"), ("secretary_tri", "Tri"),
      ("products", "RunProduct[]"), ("products_tri", "Tri"), ("run_dir", "string"),
      ("products_reason", "string"),
      # 产物页补的那两处落点：`code/exp/` 与 `out/experiments/<号>/`。
      ("experiment_spots", "ExperimentSpot[]"), ("experiment_spots_tri", "Tri"),
      ("experiment_spots_reason", "string"), ("code_exp", "CodeExpFile[]"),
      ("tasks", "TaskRow[]"), ("tasks_tri", "Tri"),
      # B2d（2026-11-22）：类别那一格的三态读数（判据只有 `artifacts.kind_state`
      # 一处）。`legacy` = 词表生效前的老行（照读），`unknown` = 词表生效后新写、
      # 行上带 `kind_unknown=true`；`unknown_kinds` 按取值数（两档都收进来，
      # 与 `artifacts.summarize()['unknown_kinds']` 同一条口径）。
      ("kind_states", "Record<string, number>"),
      ("unknown_kinds", "Record<string, number>"),
      # 标记与取值不一致的条数（写了 `kind_unknown=false` 却不在词表里）。
      ("kind_flag_mismatch", "number"),
      # 分页四格（与 `EvidenceView` 同一口径，见那一处）。
      ("rows_mode", "string"), ("rows_limit", "number"),
      ("rows_offset", "number"), ("rows_total", "Record<string, number>"),
      # 字段档四格（与 `EvidenceView` 同一口径，见那一处）。
      ("rows_fields", "string"),
      ("rows_omitted", "Record<string, string[]>"),
      ("rows_clipped", "Record<string, string[]>"),
      ("rows_nested", "Record<string, string[]>"))),
    ("ExperimentSpot",
     "artifacts_face() 的 experiment_spots[] —— 实验产物的一个落点"
     "（报告是 `out/experiments/<号>/exhaustion.md`，原始输出日志是另一个目录里的"
     "`out/exp-logs/<号>.log`；`kind` 是 exhaustion / log）",
     (("kind", "string"), ("path", "string"), ("exists", "boolean"),
      ("bytes", "number | null"), ("tri", "Tri"), ("reason?", "string"))),
    ("CodeExpFile",
     "artifacts_face() 的 code_exp[] —— `code/exp/` 下的一个脚本（相对工作区的路径）",
     (("path", "string"), ("bytes", "number | null"))),
    ("AcceptanceView",
     "acceptance_face() —— 内容级验收（键名逐字来自 reviewaccept.CRITERIA 与 "
     "AUXILIARY_SIGNALS）",
     (("tri", "Tri"), ("reason", "string"),
      ("criteria", "Record<string, string>"), ("details", "Record<string, string>"),
      # 逐条行（与 `criteria` 同一批判据，只是形状是"一行一条"）。
      # 加它的理由只有一条：业主那句"台账面每一行都带角色 + 绝对编号"里，收工门
      # 也得有"行"这个东西可挂那三格（`criteria` 是 Record，挂不上）。
      ("rows", "AcceptanceRow[]"),
      ("auxiliary", "Record<string, string>"), ("failed", "string[]"),
      # `failed` 只装"真不过"；"没查成"单列（两档不许折平；与收工面同一算式）。
      ("unchecked", "string[]"), ("note", "string"),
      # 2026-11-24：「在成本上限内」那一格的上限是收工门入参（不是预算寄存器）。
      # `cap_usd` 是调用方给的值（没给 ⇒ null）；`cap_note` 说清它从哪来、为什么
      # 预算页的 spent/total 不能顶它。
      ("cap_usd", "number | null"), ("cap_note", "string"),
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
                "reasoning_effort: string; temperature: string; key_source: string; "
                "configured: boolean }"),
      # 按角色那一档：槽 → 那一档的读数（key 一律掩码）。
      ("models", "Record<string, { api_key: string; base_url: string; name: string; "
                 "vendor: string; reasoning_effort: string; temperature: string; "
                 "key_source: string; "
                 "configured: boolean; source: string }>"),
      # 秘书那一档（全角色共用）：读数同上一格 + 那一档自己的原文（key 也掩码）。
      ("secretary", "{ api_key: string; base_url: string; name: string; vendor: string; "
                    "reasoning_effort: string; temperature: string; key_source: string; "
                    "configured: boolean; "
                    "source: string; own_slot?: Record<string, string> }"),
      ("workspace", "Record<string, string>"),
      # ---- SETTINGS-RAW：三样分开放（形状直接内联，不再多一个需要在契约 C 里
      # 登记的接口 —— 这三格的段名与上面五段逐字对齐）。
      ("raw", "{ toolchain: Record<string, string>; model: Record<string, string>; "
              "workspace: Record<string, string>; "
              "models: Record<string, Record<string, string>>; "
              "secretary: Record<string, string> }"),
      ("effective", "{ toolchain: Record<string, string>; model: Record<string, string>; "
                    "workspace: Record<string, string>; "
                    "models: Record<string, Record<string, string>>; "
                    "secretary: Record<string, string> }"),
      ("source", "{ toolchain: Record<string, string>; model: Record<string, string>; "
                 "workspace: Record<string, string>; "
                 "models: Record<string, Record<string, string>>; "
                 "secretary: Record<string, string> }"),
      ("raw_keys", "string[]"))),
    ("MachineView",
     "machine_face() —— toolchain.toolchain_report() 的键 + 设置三段",
     (("tri", "Tri"), ("reason", "string"), ("model", "Record<string, unknown>"),
      ("provers", "Record<string, unknown>"),
      # 开关（`toolchain.lean_enabled`）：与 `lean_ready`（机器上有
      # 没有装）是两条独立的事实 —— 台面必须两条都看得见，否则"关掉了"会被读成"没装"。
      ("lean_enabled", "boolean"), ("lean_enabled_source", "string"),
      ("formal_mode", "string"),
      ("lean_ready", "boolean | null"),
      ("lean_path", "string"), ("lean_version", "string"),
      ("mathlib", "Record<string, unknown>"), ("can_do_formal", "boolean | null"),
      ("settings", "SettingsReading"), ("settings_tri", "Tri"),
      ("settings_reason", "string"),
      # 服务与工作区（AUDIT F8 的裁定）：根在 `serve()` 钉死、页面没有切换入口 ——
      # 这两件事实必须由 API 说出来，页面才不是"自己想不出办法"而是"如实说不能换"。
      ("serving", "ServingWorkspace"),
      # DATAHYGIENE（2026-11-22）：库表档案 —— 已退役 / 已登记未启用两档。
      # 它们是"这一档今天该怎么读"，不是"工作区里有什么"（理由见 `table_archive_reading`）。
      ("tables", "TableArchiveView"))),
    ("TableArchiveView",
     "table_archive_reading() —— 库表档案：`schema.RETIRED_TABLES`（已退役）与"
     "`schema.NOT_ENABLED_TABLES`（已登记未启用）两档的登记面。`checked=false` ⇒ "
     "登记面读不出来（不是「没有退役表」）",
     (("checked", "boolean"), ("reason", "string"),
      ("retired", "TableRetiredRow[]"), ("not_enabled", "TableNotEnabledRow[]"))),
    ("TableRetiredRow",
     "table_archive_reading() 的 retired[] —— 一张已退役的表（`RETIRED_TABLES` 的一格）",
     (("name", "string"), ("file", "string"), ("retired_at", "string"),
      ("why", "string"), ("how", "string"))),
    ("TableNotEnabledRow",
     "table_archive_reading() 的 not_enabled[] —— 一张已登记未启用的表"
     "（`NOT_ENABLED_TABLES` 的一格：表在、线没跑过）",
     (("name", "string"), ("since", "string"), ("producers", "string[]"),
      ("consumers", "string[]"), ("evidence", "string"), ("to_enable", "string"))),
    ("ServingWorkspace",
     "serving_reading() —— 这一个服务在服务哪个工作区，以及“换不了”这件事"
     "（根在 `serve()` 钉死；页面没有、也不该有切换入口）",
     (("root", "string"), ("pinned", "boolean"), ("pinned_by", "string"),
      ("switch_in_page", "boolean"), ("switch_how", "string"))),
    ("ActionsView",
     "actions_face() —— 网页操作台账（`<工作区>/web-actions.jsonl`）的分页读数"
     "（AUDIT F11：写侧从 W3 起就在写，读侧在 F11 才落地）",
     (("tri", "Tri"), ("reason", "string"), ("path", "string"),
      ("problems", "string[]"), ("rows", "ActionRow[]"),
      ("total", "number"), ("limit", "number"), ("offset", "number"),
      ("has_more", "boolean"), ("order", "string"))),
    ("ActionRow",
     "actions_face() 的 rows[] —— 台账里的一行（写侧是 `webui/audit.record_action`）",
     (("at", "string"), ("kind", "string"), ("endpoint", "string"),
      ("source", "string"), ("params", "Record<string, unknown>"),
      ("params_sha256", "string"), ("result", "string"), ("tri", "string"),
      ("ok", "boolean"), ("http", "number"))),
    ("BudgetEntry",
     "budget.reading() 的 `added[]` 一行（`budget._write` 写进寄存器的那一笔）",
     (("kind", "string"), ("usd", "number"), ("by", "string"), ("at", "string"),
      ("note", "string"))),
    ("BudgetView",
     "budget_face() —— 总额度（寄存器）+ 已花（`usage_ledger`）与两个归口 + "
     "收工储备线（`budget.paperwork_first_reading` 的 reserve_usd / below_reserve / "
     "note）+ 无人认领那笔钱（会话口径，`sessions.unattributed_usd_of`）",
     (("tri", "Tri"), ("reason", "string"), ("path", "string"), ("exists", "boolean"),
      ("source", "string"), ("total_usd", "number | null"),
      ("spent_usd", "number | null"), ("remaining_usd", "number | null"),
      ("exceeded", "boolean"), ("added", "BudgetEntry[]"), ("problem", "string"),
      ("spent_tri", "Tri"), ("spent_reason", "string"),
      ("entries", "number | null"), ("tokens", "number | null"),
      ("attempts", "number | null"), ("added_count", "number"),
      # READFIX-D-13：账本里"算不出价钱"的行数（读不到账本 ⇒ null，不是 0）。
      ("spent_unknown_usd_calls", "number | null"),
      ("by_role", "Record<string, UsageBucket>"),
      ("by_scope", "Record<string, UsageBucket>"),
      # 收工储备线（M 自设 $1.00）：`below_reserve` 为 null 只可能是"剩余算不出来"
      # （没设过预算 / 账本读不成），不是"还剩很多"。
      ("reserve_usd", "number | null"), ("below_reserve", "boolean | null"),
      ("note", "string"), ("paperwork_first_rule", "string"),
      # 2026-11-24：`note` 是预算页自己的人话（只回答钱）；收工门那一句（"缺的是
      # 「没写」，不是「写不起」"）原样在 `closing_note` —— 两档不许再接在同一句里。
      ("closing_note", "string"),
      # 无人认领的钱（会话口径）：会话读不出来 ⇒ `unattributed_usd` 为 null 且
      # `unattributed_reason` 非空（不是 0）；非 0 时 `unattributed_reason` 逐档拆开。
      ("unattributed_usd", "number | null"), ("unattributed_reason", "string"),
      ("unattributed_source", "string"))),
    ("UsageBucket",
     "tokenmeter.by_role() / by_scope() 的一格（`{tokens, usd, entries, attempts[, roles]}`）",
     (("tokens", "number"), ("usd", "number"), ("entries", "number"),
      ("attempts", "number"), ("roles?", "Record<string, number>"))),
    ("LiveView",
     "live_face() —— 未收尾的循环 / 活进程 / 停机开关与历史（行逐字来自 stopctl）",
     (("tri", "Tri"), ("reason", "string"), ("root", "string"), ("answer", "string"),
      # 两个并列的数 —— 「在飞」只数 tasks 里 running
      # （与名册三态同源），「未收尾的循环」数的是会话面 start/end 配对（含 stale_rows）。
      # 读不到 / 还没写过 ⇒ `null`（不是 0）。
      ("tasks_running", "number | null"),
      # READFIX-D-2：这一格自己带三态与原因（tasks.json 坏 ⇒ unreadable；还没写过
      # ⇒ not_applicable），不让面级 `tri=computed` 把"null"画成绿。
      ("tasks_running_tri", "Tri"), ("tasks_running_why", "string"),
      # READFIX-A：未收尾总数 + 两档拆分（仍在跑 / 已不在跑）。改前只有 `unclosed_loops`
      # 且它只数 `stopctl.running`，把 `stale_rows` 整批丢掉了。
      ("unclosed_loops", "number | null"),
      ("unclosed_running", "number | null"), ("unclosed_stale", "number | null"),
      ("unclosed_loops_tri", "Tri"), ("unclosed_loops_why", "string"),
      ("running", "LiveLoopRow[]"),
      # `stopctl.running_loops().stale_rows` 逐字透传（带 `why`），并标 `stale_loop=true`。
      ("stale_rows", "LiveLoopRow[]"),
      ("live", "LivePidRow[]"),
      # 2026-11-24：进程面那几行的 pid 是宿主进程的号（`register_pid` 写父进程自己；
      # 同一趟 run 的多个角色是同一进程里的线程）⇒ 面级一句可复算的话："N 行共用 M 个"。
      ("live_note", "string"),
      ("unreadable_sessions", "string[]"),
      ("switch", "Record<string, unknown>"), ("switch_present", "boolean"),
      # 这两格没有具名行类型：它们是 `stop-history.jsonl` /
      # `interrupts.jsonl` 里自由形状的 JSONL 行（`consume_stop` 的 payload
      # 与中断记录各写各的键），声明成具名接口就是替生产者编形状。
      ("history", "Array<Record<string, unknown>>"),
      ("interrupts", "Array<Record<string, unknown>>"))),
    ("LiveLoopRow",
     "stopctl.running_loops() 的 running[] / stale_rows[] —— 一条「未收尾的循环」"
     "（有 start 没 end；`stale_loop` 由 `webui.state.mark_stale_loops` 现算，"
     "`stale_rows[]` 那一档恒为 true）",
     (("role", "string"), ("sid", "string"), ("since", "string"),
      # 这两个由 `stopctl` 给（running 与 stale_rows 都有）；`task_id` 是绝对编号，
      # `evidence` 说这一行的证据档（会话面 / 进程面）。
      ("task_id", "string"), ("evidence", "string"),
      # 顶趟已收尾 / 宿主进程已死 ⇒ 这一行是"被打断后剩下的循环记录"，
      # 不是活着的循环（页面据此写"宿主进程已退出/被叫停，不是活着"）。
      ("stale_loop", "boolean"),
      # 为什么判成不在跑（`stopctl.stale_rows[].why`；running 行没有这一格）。
      ("why?", "string"))),
    ("LivePidRow",
     "stopctl.live_pids() 的一行 —— 登记在盘上且真的还活着的一个进程"
     "（`path` 是那一份登记文件的落点，`live_pids` 会给）。`host_process` / `pid_note`"
     "是 2026-11-24 补的：那一格是宿主进程的 pid（`register_pid` 写父进程自己），"
     "不是这一行自己的 pid —— 同一趟 run 的角色共用同一个号",
     (("pid", "number"), ("role", "string"), ("sid", "string"),
      ("started_at", "string"), ("path", "string"),
      ("host_process", "boolean"), ("pid_note", "string"))),
    ("UsageView",
     "usage_face() —— usage_ledger 的汇总（总计 + 两个归口 + 重试开销 + 最近几笔）",
     (("tri", "Tri"), ("reason", "string"), ("path", "string"),
      ("entries", "number | null"), ("spent", "Record<string, unknown>"),
      # READFIX-D-13：账本里"算不出价钱"的行数（读不到账本 ⇒ null，不是 0）。
      ("spent_unknown_usd_calls", "number | null"),
      ("by_role", "Record<string, UsageBucket>"),
      ("by_scope", "Record<string, UsageBucket>"),
      ("retry_overhead", "Record<string, unknown>"),
      ("recent", "Array<Record<string, unknown>>"))),
    ("StatusReportRow",
     "status_reports_face() 的一行 —— `out/report/STATUS-<ts>.{md,json}` 的一份",
     (("name", "string"), ("stem", "string"), ("path", "string"),
      ("json_path", "string"), ("bytes", "number | null"), ("ts", "string"))),
    ("StatusReportsView",
     "status_reports_face() —— 状态报告最近几份（`statusreport` 写了没人读的那个缺口）",
     (("tri", "Tri"), ("reason", "string"), ("dir", "string"),
      ("count", "number | null"), ("reports", "StatusReportRow[]"))),
    # 对话页那一面：一段会话里"用户 ↔ 主控"的来回。
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
    ("DocumentRow",
     "store.rows(\"documents\")（夹具有 0 行 ⇒ 权威来源是 `schema.Document` 的"
     "dataclass；2026-11-14 补这一栏，网页端此前只有命令行读得到稿件台账）",
     (("doc_id", "string"), ("kind", "string"), ("title", "string"),
      ("markdown_path", "string | null"),
      ("sections", "Record<string, unknown>[]"), ("claims", "Record<string, unknown>[]"),
      ("open_problems", "string[]"), ("status", "string"),
      # 状态呈现读数（`_status_reading`）：人话 + 三态（只有命题面有 lifecycle
      # 入口，其余表 `lifecycle_state=""` / `lifecycle_checked=null`）。
      ("status_word", "string"), ("lifecycle_state", "string"),
      ("lifecycle_checked", "boolean | null"),
      ("review_rounds", "number"), ("review_verdict", "string"),
      ("reviewed_at", "string"), ("reviewed_by", "string"),
      ("created_at", "string"), ("updated_at", "string"), ("revision", "number"),
      ("content_sha256", "string"), ("created_by", "string"))),
    ("StatementRow",
     "store.rows(\"statements\")（无真机样本 ⇒ 权威来源是 `schema.Statement`）",
     (("stmt_id", "string"), ("origin", "string"), ("kind", "string"),
      ("label", "string"), ("statement_text", "string"), ("statement_full", "string"),
      ("proof_text", "string"), ("source_lit_id", "string"),
      ("page_range", "string"), ("quote_verified", "boolean | null"),
      ("quote_reason", "string"), ("evidence_kind", "string"),
      # `bits` 是五元证据位那一份对象（`evidencebits.bits_from_row` 的读数：
      # numeric / proof / reviewed / formal / audited + evidence / grade …），
      # 不是数字。声明成 `number` 时类型面读不出 `bits.reviewed`（运行时能读，
      # 于是这条错误只在 `tsc` 那一侧沉默）。
      ("bits", "Record<string, unknown>"),
      ("status", "string"), ("derived_from", "string"), ("doc_id", "string"),
      # 状态呈现读数：命题面走 `lifecycle.state_of_statement`（唯一入口）⇒
      # `lifecycle_state` 是 active / completed / abandoned（读不出来是空串 +
      # `lifecycle_checked=false`），`status_word` 是页面上印的那个人话词。
      ("status_word", "string"), ("lifecycle_state", "string"),
      ("lifecycle_checked", "boolean | null"),
      ("line_range", "string"), ("created_at", "string"), ("created_by", "string"),
      # 命题要标注非平凡度、第 4 位按路径显示、引文读数分档：
      # 这十一格都是读模型的现算读数（`_statement_readings`），不是 `schema.Statement`
      # 的字段。`nontriviality` 是 `number | null` —— `null` 是"未判"，不是 T0。
      # 多一格 `nontriviality_word`：页面直接印的那个词
      # （`T0`…`T4` / `不适用` / `未判`）。`nontriviality_tri` 多第三个取值
      # `not_applicable`（概念 / 定义行没有证明正文 ⇒ 判档这一问对它不成立）。
      # 词不借 `nontriviality_label` 那一格：`label` 只装档位名，否则"有没有档位"
      # 这个判据就被一个显示词抹掉了。
      ("quote_state", "string"),
      ("nontriviality", "number | null"), ("nontriviality_label", "string"),
      ("nontriviality_meaning", "string"), ("nontriviality_tri", "string"),
      ("nontriviality_word", "string"),
      # 再一格 `nontriviality_matched_by`：档位是靠哪一格对上命题行的
      # （`stmt_id` 按号 / `sha256` 旧行回退 / 空串 = 没判过）。它是台账的来历读数，
      # 不是显示词；页面不印它，但"按号命中"与"靠正文 sha 回退"必须分得开。
      ("nontriviality_matched_by", "string"),
      # ---- 逐路径（NT2，2026-11-15 业主裁定）-------------------------------------
      # 非平凡度是「一个路径一个」：`nontriviality_paths` 一条路径一行
      # （`path_group` / 该路径当前档位 `level` / 历史最小 `floor` / `at` / 两枚 sha）；
      # `nontriviality_min_of` 是命题级 min 的来源值（各路径历史最小，升序）；
      # `nontriviality_partial` 说"还有路径没判"（不许折成已算全），
      # `nontriviality_paths_unjudged` 点名是哪几条。四格都是读模型现算的读数，
      # 不是 `schema.Statement` 的字段。
      ("nontriviality_paths", "NontrivialityPath[]"),
      ("nontriviality_min_of", "number[]"),
      ("nontriviality_partial", "boolean"),
      ("nontriviality_paths_unjudged", "number[]"),
      ("formal_paths", "FormalPath[]"),
      # 五元位每一位一格：前四格是第 1/2/3/5 位各自的状态词
      # （`evidencebits.BIT_STATES` 那四档），第 4 位不在这里 —— 它是二维的，
      # 读法是 `formal_paths`（压成一句汇总就等于让 `#p2` 借 `#p1` 的光）。
      ("bit_numeric", "string"), ("bit_proof", "string"),
      ("bit_reviewed", "string"), ("bit_audited", "string"),
      ("reviewed_paths", "ReviewedPath[]"),
      # 「是否优化」：与 `reviewed_paths` 并排的逐份那一格。三态 token 由
      # `evidencebits.optimized_state` 给（true / false / not_recorded）；
      # 缺格是 `not_recorded`，不是 `false`。页面那一列叫「优化」。
      ("optimized_paths", "OptimizedPath[]"),
      ("grade", "string"), ("grade_label", "string"),
      # ---- 读侧投影（KINDREAD，2026-11-20）------------------------------------
      # `kind` 仍是盘上原值（历史行不许物理改）；`kind_projected` 是按登记判据
      # （`evidencebits.kind_at_registration`，写侧同一处）现算的并列值。
      # `kind_projection_changed` 标两者是否不同 —— 页面必须把原值印在前面、
      # 投影印在后面（不许把投影冒充原值，判据 `test_read_side_kind_projection.py`）。
      # `kind_projection_checked=False` 是"这一问没判成"（origin 读不出来 /
      # 引文行没有命题正文），`basis` 写着这次投影拿的来路与正文形态。
      ("kind_projected", "string"), ("kind_projection_changed", "boolean"),
      ("kind_projection_checked", "boolean"), ("kind_projection_basis", "string"),
      # 现行性（业主 2026-11-20 ④）：`current_state` 是 lifecycle 三态（计算要用），
      # `current_word` 是页面上印的那一句（active 行是空串 ⇒ 页面写 `—`；
      # 非 active 行带具体原因与所指编号），`current_detail` 是 hover 那一句。
      ("current_state", "string"), ("current_word", "string"),
      ("current_detail", "string"),
      # 自产结果才有的两格（业主 2026-11-20 ③）：有没有稿 / 稿上有无 V 签。
      # 文献命题这四格是空串（页面不摆那两列）。
      ("manuscript_state", "string"), ("manuscript_path", "string"),
      ("vsign_state", "string"), ("vsign_detail", "string"),
      # 收录回执两格 —— 这一行现在这一份证明是哪一号、正文指纹是什么。
      # 它由"把正文补进在册那一行、补翻第 2 位"的那一笔
      # （`agent_b.register_statement._attach_proofs` 的 `proof_collected`）按盘上的
      # 正文现算落盘；不是 `schema.Statement` 的字段，也没有每一行都会有的承诺
      # （老行 / 新建行都没有）⇒ 声明成可选（`?`）—— C 条"可选的没出现不算漂移"那一档。
      ("proof_no?", "number"), ("proof_sha256?", "string"),
      # 后三格是读模型的 join
      # （`_annotate_ledger_row`），不是 `schema.Statement` 的字段。
      ("by_role", "string"), ("by_role_source", "string"),
      ("by_task_id", "string"), ("by_task_id_tri", "string"),
      # compact 档把 `statement_full` / `proof_text` 按逐栏上限截断时，
      # 这两个说明"截了、原文多长"。可选：`?full=1` 那一档没有它们。
      ("statement_full_truncated?", "boolean"), ("statement_full_chars?", "number"),
      ("proof_text_truncated?", "boolean"), ("proof_text_chars?", "number"))),
    ("FormalPath",
     "evidencebits.formal_by_proof() 的一行 —— 五元位第 4 位的一条路径"
     "（`proof_no` 是证明号，`state` 取 `evidencebits.FORMAL_PATH_STATES` 的五档："
     "pending / na / failed / verified / stale）。折成一条汇总就等于让 `#p2` 借 `#p1` 的光",
     (("proof_no", "number"), ("state", "string"))),
    ("ReviewedPath",
     "evidencebits.reviewed_by_proof() 的一行 —— 五元位第 3 位按证明逐条"
     "（`proof_no` 是证明号，`reviewed` 是「这一份签过没有」；签的是不是现在这一份"
     "正文由 `VerificationRow.proof_sha_consistency` 回答。只签了 `#p1` 而定理还有"
     "`#p2` 时 `#p2` 是 false —— 折成一句「审过」就等于让它借 `#p1` 的光）",
     (("proof_no", "number"), ("reviewed", "boolean"))),
    ("OptimizedPath",
     "evidencebits.optimized_state() 的一行 —— 命题台账「是否优化」按证明逐份"
     "（`proof_no` 是证明号，`state` 取 `evidencebits.OPTIMIZED_STATES` 的三档："
     "true / false / not_recorded）。缺格 ⇒ not_recorded，不折成 false：折成 false "
     "会让整库存量行一次全变「未优化」。编号取自 reviewed_by_proof / "
     "reviewed_sha_by_proof / optimized_by_proof 三张表的并集 —— "
     "于是「优化」与签过 / 验过的逐份读数按 proof_no 并排，`#p2` 不借 `#p1` 的光",
     (("proof_no", "number"), ("state", "string"))),
    ("NontrivialityPath",
     "secretary._fold_nontriviality() 的一行 —— 非平凡度按证明路径逐条（NT2，"
     "2026-11-15 业主裁定「一个路径一个」）。`path_group` 是第几条路径（旧行没有这一格"
     "⇒ 路径 1）；`level` 是该路径最后一行（允许升/降档），`floor` 是该路径历史最小值"
     "（命题级 min 的来源）；两枚 sha 是「判的材料」与「落盘正文」的指纹",
     (("path_group", "number"), ("level", "number | null"), ("floor", "number | null"),
      ("label", "string"), ("at", "string"), ("stmt_id", "string"),
      ("basis", "string"), ("judged_body_sha256", "string"),
      ("landed_body_sha256", "string"), ("rows", "number"))),
    ("ReviewFindingRow",
     "store.rows(\"review_findings\")（无真机样本 ⇒ 权威来源是 `schema.ReviewFinding`）",
     (("finding_id", "string"), ("doc_id", "string"), ("kind", "string"),
      ("level", "string"), ("target", "string"), ("evidence", "string"),
      ("message", "string"), ("round", "number"), ("suggestion", "string"),
      ("status", "string"), ("resolution_note", "string"), ("created_at", "string"),
      # 状态呈现读数（这一张表没有 lifecycle 入口 ⇒ 只译词，`lifecycle_*` 空）。
      ("status_word", "string"), ("lifecycle_state", "string"),
      ("lifecycle_checked", "boolean | null"),
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
      # 引文五档（`_quote_state_rows`；含 `no_evidence` —— 说通过而拿不出
      # 可复核区间的那一档，折进"未查"就把它欠的东西读错了）。
      ("quote_state", "string"),
      # 状态呈现读数（关系表没有 lifecycle 入口 ⇒ 只译词，`lifecycle_*` 空）。
      ("status_word", "string"), ("lifecycle_state", "string"),
      ("lifecycle_checked", "boolean | null"),
      ("by_role", "string"), ("by_role_source", "string"),
      ("by_task_id", "string"),
      ("by_task_id_tri", "string"))),
    ("VerificationRow",
     "verifications.list_verifications()（裁定 K2：无真机样本 ⇒ 夹具造一行）",
     (("verification_id", "string"), ("statement_id", "string"),
      # 多证明模型：签名行多了 `stmt_id`（被审的那条命题，与
      # `statement_id` 同值）。`proof_no` 在 V 签侧退役：一份证明的身份由
      # 正文 sha + `statement_id` + 路径回答 ⇒ 类型面不声明它（页面也不再印
      # "第几份"）。
      ("stmt_id", "string"),
      ("verifier", "string"),
      ("verdict", "string"), ("defect_step", "string"), ("quote", "string"),
      ("why", "string"), ("findings", "Record<string, unknown>[]"),
      ("unresolved_errors", "number"), ("proof_sha256", "string"),
      ("proof_chars", "number"), ("round", "number"), ("used_faces", "string[]"),
      # V 三轮送审的口径（逐字：「不允许跨两次送审累计成功数」）：
      # 新写的台账行多两格 —— `review_call` 是同一趟 `verify_proof` 的调用 id
      # （同趟三行逐字相同），`review_pass` 是这趟里的第几轮（1..need）。
      # 类型取 `verifications.record_verification` 写行的真值：前者恒为 `str(...)`，
      # 后者是 `int(...) if review_pass is not None else None` ⇒ 必填但可空。
      # 老行没有这两格（读侧按历史形态 `legacy_rows` 计，不参与新签判断），
      # 与 `citation_checks` 那一批同一条口径：声明的是新行形状，不是老盘的样子。
      ("review_call", "string"), ("review_pass", "number | null"),
      ("submission_id", "string"), ("at", "string"),
      # `proof_sha_consistency` 是
      # "V 签的那一份 vs 命题现在这一份（一份证明一行）"的三档读数。
      # `proof_sha256` 留在数据里（凭据要能复核），只是页面不再印它。
      ("proof_sha_consistency", "string"),
      # 台账行无条件写产出方格 ——
      # `producer_role` 由路径族现判（不采信调用方自报），`producer_code` 是产出方
      # 的代码/稿号；`producer_problem` 只在"路径族与名册的父角色不一致 / 路径读不出
      # 产出方"时写（条件写入 ⇒ 可选）。三格都真的读得出来（C 条逐键比）。
      ("producer_role", "string"), ("producer_code", "string"),
      ("producer_problem?", "string"),
      ("by_role", "string"), ("by_role_source", "string"),
      ("by_task_id", "string"),
      # 引用核实那一批落地后的补登记：台账那一行多了 `citation_checks`
      # 五格（`verifications.CITATION_CHECK_KEYS`：stmt_id / verdict / quote_verbatim /
      # note / in_material）。后端真的读得出它（C 条拿夹具那一行逐键比）⇒ 这里必须声明，
      # 否则类型面读不出"这条证明里的引用被逐条核成了什么"。
      # `in_material` 是补的第 5 格：材料之外的那条（V 多给的）不算挡签，
      # 而这一格必须落盘 —— 否则落盘再读回来时两个判定口给出相反结论。
      ("citation_checks",
       "{ stmt_id: string; verdict: string; quote_verbatim: boolean; note: string; "
       "in_material: boolean }[]"),
      # 「打回即站住」之后，台账写口无条件写这一格
      # （`verifications.secretary_judge_cell`：给了判定写判定，没给写"未判成"），
      # 于是夹具/真盘上的新行都读得出它 —— C 条拿行逐键比 ⇒ 这里必须声明，
      # 否则类型面读不出"这一行的轴是不是秘书给的"（轴是签发唯一来源）。
      # 形状是那一格的 `axis` / `checked` / `decision` / `reason` 加上调用方带的
      # `basis` / `source` 等，读侧只搬不解释 ⇒ 声明成开放字典。
      ("secretary_judge", "Record<string, unknown>"),
      ("by_task_id_tri", "string"))),
    ("ArtifactRow",
     "artifacts.read_ledger() 的行（`artifacts.FIELDS` 的键，真机 ARTIFACTS.jsonl 同形）",
     (("at", "string"), ("path", "string"), ("sha256", "string"), ("bytes", "number"),
      ("producer", "string"), ("kind", "string"), ("task_id", "string"),
      ("exit_code", "number | null"), ("note", "string"),
      # sha 原文不显示：这一格取同一路径的核对行读数
      # （match / mismatch / unknown），页面只印它。
      ("sha_consistency", "string"),
      # 归属三格（K1/K2/K6）：`producer` 之外再记实例标签与未归因原因，`family` 是
      # 稿的族（非稿产物是空串）。它们由 `artifacts.record` 无条件写、不是读模型的
      # join 补出来的 —— 后端真读得出（`tests/test_webui_readers.py` 的 C 条逐键比
      # 拿夹具那一行对着这张声明表核），所以这里必须声明；漏声明时 `ArtifactRow`
      # 面会对盘上真实存在的三格报"读模型多给了键"。
      ("instance", "string"), ("identity_conflict", "string"), ("family", "string"),
      # B2d（2026-11-22）：`kind_unknown` 是盘上原值，而且刻意不由读模型给老行
      # 补空串（其余 `FIELDS` 键会补）：这一格"在不在"正是 `artifacts.kind_state`
      # 分辨 `legacy` 与 `unknown` 的判据 ⇒ 老行（词表生效前落的）没有它，是事实。
      # 页面判态读 `kind_state`（补格之前算好的三态），不拿这一格猜。
      ("kind_unknown?", "boolean"), ("kind_state", "string"),
      # 台账行没有 `created_by`（`artifacts.FIELDS` 里没有那一栏）⇒ `by_role` 是空串。
      # `by_task_id` 按 `path` 反查（`agent_run_artifact` 事件同时带 path 与编号）。
      ("by_role", "string"), ("by_role_source", "string"),
      ("by_task_id", "string"),
      ("by_task_id_tri", "string"))),
    ("LedgerVerifyRow",
     "artifacts.verify_entries() 的行 —— 台账钉的 sha 与盘上现在这一版是不是同一版"
     "（`sha_consistency` 把 `status` 的五档折成 match / mismatch / unknown）",
     (("path", "string"), ("sha256", "string"), ("producer", "string"),
      ("at", "string"), ("sha256_now", "string"), ("status", "string"),
      # `changed` 那一档的读侧分类（`artifacts.CHANGE_REASONS`）：为什么变了、
      # 框架自己能否解释；不改变 `status`（五档仍是唯一判档）。
      ("reason", "string"), ("explained", "boolean"),
      ("sha_consistency", "string"),
      ("by_role", "string"), ("by_role_source", "string"),
      ("by_task_id", "string"),
      ("by_task_id_tri", "string"))),
    ("HandoffRow",
     "manuscripts.read_rows() 的行（`manuscripts.write` 写的 14 个必填键；"
     "`revises`/`kind`/`ref_problems`/`to_task_id`/`to_task_ids` 是「有就带上」的几栏）",
     (("id", "string"), ("to", "string"), ("sender", "string"), ("summary", "string"),
      ("body", "string"), ("refs", "string[]"), ("sha256", "string"),
      ("sid", "string"), ("task_id", "string"), ("format", "string"),
      ("bytes", "number"), ("path", "string"), ("note", "string"),
      ("created_at", "string"), ("revises?", "string"), ("kind?", "string"),
      ("ref_problems?", "Record<string, string>"),
      # 收件人的绝对编码：`to_task_id` = 具体收件人的台账号，
      # `to_task_ids` = 广播面（`to=ALL`）的编号列表。写侧只在这一行真有编号时才落
      # 这两个键 ⇒ 读模型把它们归一成"永远给得出"（缺 ⇒ 空串 / 空列表），而
      # 「旧账无号」那一档由下面两格说清（`handoff_to_label` 按盘上的原样算）。
      ("to_task_id", "string"), ("to_task_ids", "string[]"),
      ("sender_label", "string"), ("to_label", "string"),
      # 手稿号是裸号（编号空间就是账本行号）⇒ 拿它当事件口令会误命中，
      # 所以这一栏的 `by_task_id_tri` 是 `not_applicable`（见 `_LEDGER_ROW_TOKENS`）。
      ("by_role", "string"), ("by_role_source", "string"),
      ("by_task_id", "string"),
      ("by_task_id_tri", "string"),
      # compact 档把 `body` 按逐栏上限截断时，这两格说明"截了、原文多长"。
      # 可选：`?full=1`（全字段）那一档没有它们 —— 不截就不该多一个 `false` 噪声。
      ("body_truncated?", "boolean"), ("body_chars?", "number"))),
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
     "验收表的一行（路径的单一口径是 `closing.ACCEPTANCE_TARGETS_NAME`；"
     "真机 8 行 C1–C8）。阈值是 `min` / `max` / `na` 三选一："
     "`min` 档问「做得够不够」（`got >= min`），`max` 档问「剩下多少没做」"
     "（`got <= max`，真机 60/99 份工作区里有这种行），`na` 档是「这一档对这个项目"
     "不适用」（三态，不是通过也不是失败）⇒ 三格都写成可选，谁都不冒充必填。"
     "B3（2026-11-22）：`kind` 是盘上原值（可能是旧名），`kind_reading` 是读侧正名"
     "（交接手稿那一档 = `handoff_rows`），旧名行另带 `kind_deprecated`（弃用标记）",
     (("id", "string"), ("kind", "string"),
      ("kind_reading", "string"), ("kind_deprecated?", "string"),
      # 三格都写成可选：`min` 若必填、而 `max`/`na` 没声明，`types.ts` 里
      # `AcceptanceCheck.min` 就是必填 number，而盘上 60 份工作区的 C3/C4 是 max-only
      # 行 ⇒ `Artifacts.tsx` 的 `String(r.min)` 会印出 `undefined`。
      # 形状真身是 `closing.py` 的阈值那一段（`want_min` / `want_max` / `row["na"]`）。
      ("min?", "number | null"), ("max?", "number | null"),
      ("na?", "boolean"),
      ("name", "string"),
      ("note", "string"),
      # 验收表是配置行（`C1`–`C8`），不是某条写入 ⇒ 编号那一格是 `not_applicable`。
      ("by_role", "string"), ("by_role_source", "string"),
      ("by_task_id", "string"),
      ("by_task_id_tri", "string"))),
    ("ReportStyle",
     "out/report/REPORT-STYLE.json 的 `sections`（真机四节名字）",
     (("sections", "string[]"),)),
    ("TaskRow",
     "store.rows(\"tasks\")（真机 p9b/data/tasks.json 19 键 + 工作项板那 7 格；"
     "板那 7 格是 S0/S1b 扩列之后补进来的 —— 真机上它们今天全是空值"
     "（`draft/94` §4：2276 行里 `kind` 非空 0 行），但列在，所以类型必须跟上）",
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
      # 父代理退场结算写成的那一格（`schema.child_ending`
      # 的三档里只有"被父退场掐断"那一档为真）。它是 `Task` 的列，盘上有它就得上
      # 声明 —— 否则契约 C 会报"后端有而 types.ts 没有"，而那一格正是剪断与交付
      # 分不开的地方（跨 lane 的连带，由 Q2 这一批顺手补上）。
      ("settled_at_parent_exit", "boolean"),
      # 撤销之后 `expects` 被清空，原值落在这一格。
      # 同上一条：它是 `Task` 的列，盘上有它就得在 types.ts 里声明。
      ("expects_was", "string"),
      # 任务行的编号就是它自己的 `task_id`（按它反查，命中的是这一趟自己的收尾事件）。
      # 角色这一格照业主的口径只认 `created_by`（Task 没有那一栏）⇒ 空串。
      ("by_role", "string"), ("by_role_source", "string"),
      ("by_task_id", "string"),
      ("by_task_id_tri", "string"),
      # 板项行的"状态"读数（`statusreport.tasks_row_reading` 的
      # 投影：`板项 done/acked` / `板项 queued/未收口`；代理行仍是 `<status>/<outcome>`）。
      # 它不在 `schema.Task` 里 —— 是这一面现算的投影，与 `.md` 报告同一处口径。
      # 盘上的 `status` 一个字都不改（板项行那一格恒为 `pending`，那是类型标记）。
      ("status_reading", "string"),
      # compact 档把 `detail` 按逐栏上限截断时，这两格说明"截了、原文多长"。
      ("detail_truncated?", "boolean"), ("detail_chars?", "number"))),
    ("ConjectureRow",
     "store.rows(\"conjectures\")（真机 p9b/data/conjectures.json；无样本时以 "
     "`schema.Conjecture` 为准）",
     (("conjecture_id", "string"), ("statement", "string"), ("status", "string"),
      # `testable` 的真身是 `schema.Conjecture.testable: dict`（`{"params", "bounds",
      # "why"}`），不是 `boolean | null`。声明成标量时 `tsc` 抓不到
      # `String(r.testable)` —— 真机 13 行全印 `[object Object]`（`draft/187` P2-1）。
      ("form", "string"), ("testable", "Record<string, unknown>"), ("origin", "string"),
      ("created_by", "string"), ("created_at", "string"), ("updated_at", "string"),
      ("experiment_ids", "string[]"),
      ("counterexample_experiment_id", "string | null"),
      ("proof_experiment_id", "string | null"), ("negation_statement", "string"),
      ("known_lit_id", "string"), ("notes", "string"),
      # 真身同样是 dict（`{"kind": …, "id": …}`）；声明成 string 时页面会印
      # `[object Object]`（或 `tsc` 放行一次错误的 String()）。
      ("promoted_to", "Record<string, unknown>"),
      ("withdraw_reason", "string"), ("duplicate", "boolean | null"),
      # 状态呈现读数：这一张表没有 lifecycle 入口 ⇒ 只译词。
      ("status_word", "string"), ("lifecycle_state", "string"),
      ("lifecycle_checked", "boolean | null"),
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
      ("claim_key", "string"),
      # 这四格的真身都是 dict（`schema.Experiment`），`counterexample` / `certificate`
      # 另可为 None。声明成 string 时页面会印 `[object Object]`（或 `tsc` 放行一次
      # 错误的 String()）—— WEBCAP 的 type_drift 逐格报过这四格。
      ("certificate", "Record<string, unknown> | null"),
      ("counterexample", "Record<string, unknown> | null"),
      ("search_bound", "Record<string, unknown>"),
      ("verifier_output", "string"), ("verifier_subject_key", "string"),
      ("code_path", "string"), ("code_hash", "string"),
      ("exit_code", "number | null"), ("artifact_paths", "string[]"),
      ("observations", "Record<string, unknown>"), ("params", "Record<string, unknown>"),
      ("runtime_sec", "number | null"), ("notes", "string"),
      ("created_at", "string"), ("created_by", "string"),
      ("for_question_id", "string | null"),
      # `status` 是真身的一列（`schema.Experiment.status`：`active` / `voided`）。
      # 改前这里漏了它 ⇒ `types.ts` 里 ExperimentRow 没有 status，页面想印"状态"就
      # 得 `as unknown as`（`tsc` 抓不到的那种缺格）。作废那四格同批补上。
      ("status", "string"),
      ("voided_by", "string"), ("voided_at", "string"),
      ("void_reason_code", "string"), ("voided_code_to", "string"),
      # 归属那两格：盘上不一定有（老行），声明成可选。
      ("owner_task?", "string"), ("owner_instance?", "string"),
      # 状态呈现读数（这一张表没有 lifecycle 入口 ⇒ 只译词）。
      ("status_word", "string"), ("lifecycle_state", "string"),
      ("lifecycle_checked", "boolean | null"),
      # sha 原文不显示：`code_sha_consistency` 是"台账钉的代码 sha
      # vs 盘上现在这一份脚本"的读数（`code_hash` 留在数据里，页面不印）。
      # 改脚本后重新登记并撤销老登记 ⇒ 它多了第四档 `revoked`，
      # 另带三格 —— 两个 sha 前 16 位（`code_sha_from` / `code_sha_to`）与那句撤销理由
      # （`void_reason`，逐字「脚本 <旧> → <新>」）。有效行上这三个是空串。
      ("code_sha_consistency", "string"),
      ("code_sha_from", "string"), ("code_sha_to", "string"),
      ("void_reason", "string"),
      # 实验表没挂穷举论证报告：`exhaustion_path` 是那份
      # 报告的仓库相对落点（`out/experiments/<号>/exhaustion.md`，口径在
      # `exhaustionreport.report_relpath`），`exhaustion_tri` 是它的三态
      # （computed / not_applicable / unreadable；`not_applicable` 时路径是空串）。
      ("exhaustion_path", "string"), ("exhaustion_tri", "Tri"),
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
    # 名册监视：`out/roster/<父编号>.jsonl` 折出来的那棵树。
    # 逐字段的盘上出处写在 `roster_face` 的 docstring 里那张表上（这里不抄第二份）。
    ("RosterView",
     "roster_face() —— 当前工作区整棵名册树（`out/roster/<父编号>.jsonl` 与 "
     "`<父编号>-index.jsonl` 折叠出不落盘的名册项 + `data/tasks.json` 的状态/收件箱读数）",
     (("answer", "string"), ("tri", "Tri"), ("reason", "string"),
      ("root", "string"), ("dir", "string"), ("nodes", "RosterNode[]"),
      ("roots", "string[]"), ("children_of", "Record<string, string[]>"),
      ("count", "number | null"),
      ("max_depth", "number | null"), ("files", "string[]"),
      ("diagnostics", "string[]"), ("coverage", "RosterCoverage"),
      ("tasks_tri", "Tri"), ("tasks_reason", "string"), ("truncated", "boolean"),
      # 三态合计（业主：「『在飞』的读数要随着时钟式待机进行适配」）：
      # 四档各几个 + `active`（= 在飞 + 待机）。计数格是 `number | null`
      # （`null` = 没读到，不是 0）。刻意写成行内对象而不是另立一个接口：
      # 它是 RosterView 的一格、不是一张独立的表（前端用 `RosterView["states"]` 取）。
      ("states",
       "{ checked: boolean; reason: string; flying: number | null;"
       " standby: number | null; silent: number | null; unknown: number | null;"
       " active: number | null; total: number | null; labels: Record<string, string> }"),
      # 台账里有父、可名册正文与对照表都没说"谁接过它"的那些代理行：平铺并点名，
      # 不抬成树根（D-66）。
      ("unplaced", "RosterUnplaced[]"))),
    ("RosterNode",
     "roster_face() 的一个节点 —— 一个常驻子代理（名册里那一项；`depth` 是名册链上的"
     "相对深度，根 = 1）。`task_id` 只是页面用的节点键（建项那件活的编号），身份是"
     "`owner` + `name`；它接过哪些活见 `tasks`",
     (("task_id", "string"), ("name", "string"), ("role", "string"),
      ("depth", "number"), ("parent_task_id", "string"), ("parent_name", "string"),
      ("children", "RosterChild[]"), ("retired", "boolean"),
      ("retired_branch", "string"), ("brief", "string"), ("brief_source", "string"),
      ("surface", "string"), ("status", "string"), ("task_found", "boolean"),
      # 三态（在飞 / 待机 / 静默 / 未读到）与"为什么是这一档"的那一句人话。
      # 判定只有 `conductor.agent_state` 一处；`state_reason` 在 `unknown` 时必有。
      ("state", "string"), ("state_reason", "string"),
      # 疑似停滞（业主第二条）：`state` 仍是 flying 的那一格旁边多一个读数
      # —— 最近一步离现在多少秒。`stalled_sec` 是 `number | null`（null = 没读到，不是 0）。
      ("stalled", "boolean"), ("stalled_sec", "number | null"),
      ("stalled_reason", "string"),
      ("in_flight", "number | null"), ("inbox", "RosterInbox"),
      # 这个子代理接过的每一件活（业主：「一个子代理可接收多个任务」）。
      ("tasks", "RosterTask[]"),
      # 「子 N」只数名册项，漏掉"有父但没落名册"的那些：
      # `children_in_ledger` 是台账里的子数（台账读不到 ⇒ null，不是 0；这个名字量的
      # 是"这个节点在台账里挂了几个子"，与收工读数的 `children_unretired`（名册未销号项数）
      # 是两个量），
      # `roster_child_count` 是名册项数，`unrostered_children` 是"有父、没落名册"的那些
      # （编号 + 角色 + 状态；它们同时仍进页面底部的 `unplaced`，两处同一口径）。
      ("children_in_ledger", "number | null"), ("roster_child_count", "number"),
      ("unrostered_children", "RosterUnrostered[]"),
      # 这一格只在「台账兜底档」（`_roster_from_tasks`）出现，
      # 恒为 `False`；名册档的节点不带它 —— 不带就是"它在名册上"（那一档的名册项
      # 必然登记过，`test_roster_registration_covers_every_path.py` 逐字钉着"名册
      # 节点不带 `registered` 这一格"）。所以写成可选：写成必填，名册档的
      # `node.registered` 就是 `undefined`，正是 E4 那一类"声明比盘上硬"的形状陷阱。
      ("registered?", "boolean"))),
    ("RosterUnrostered",
     "roster_face() 的 nodes[].unrostered_children[] 一项 —— 台账里有父、名册正文与"
     "对照表里都没有任何名册项接过的那一行（它同时仍进页面底部的 `unplaced`，"
     "两处是同一处判据的两个落位）",
     (("task_id", "string"), ("role", "string"), ("status", "string"),
      ("started_at", "string"), ("ended_at", "string"), ("why", "string"))),
    ("RosterTask",
     "roster_face() 的 nodes[].tasks[] 一项 —— 这个子代理接过的一件活：编号来自"
     "`<父>-index.jsonl` 的调用记录，状态与起止时间来自 `data/tasks.json`",
     (("task_id", "string"), ("role", "string"), ("status", "string"),
      ("started_at", "string"), ("ended_at", "string"), ("task_found", "boolean"),
      ("brief", "string"), ("detail", "string"))),
    ("RosterUnplaced",
     "roster_face() 的 unplaced[] 一项 —— 台账里有父、却没有任何名册项接过的那一行"
     "（平铺并点名，不抬成树根）",
     (("task_id", "string"), ("parent_task_id", "string"), ("role", "string"),
      ("status", "string"), ("started_at", "string"), ("ended_at", "string"),
      ("why", "string"))),
    ("RosterChild",
     "roster_face() 的 nodes[].children[] 一项 —— 名册里的一个子（绝对编号 + 名册名）",
     (("task_id", "string"), ("name", "string"), ("role", "string"),
      ("retired", "boolean"))),
    ("RosterInbox",
     "roster_face() 的 nodes[].inbox —— 收件箱（板项：`kind` 非空、"
     "`parent_task_id` = 收件人、`item_state != \"done\"` 的那些行）；"
     "`unread` 是还没被读进任何一步的（queued/claimed），"
     "`seen_not_acked` 是读了但还缺 ack 的，`open_total` 是 `len(rows)` = "
     "`unread` + `seen_not_acked` + `other`（`other` 是状态读不出来的那些："
     "`item_state` 是空串或词表外的行）",
     (("tri", "Tri"), ("unread", "number | null"), ("seen_not_acked", "number | null"),
      ("open_total", "number | null"), ("other", "number | null"),
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
    # 文献库那一面（「ui侧文献库无法读出，请确认」是它的来由）。
    # 五键外壳里 `state` 只有两档（computed / unknown）：`unknown` 是"这一面没读成"
    # （表不在盘上 / 坏 JSON），而 `count` 那一格在那一档是 null —— 不是 0。
    ("ObligationFamily",
     "obligations_face() 的 families[] —— 一族义务（b-register / v-resubmit / "
     "b-awake / d-handoff）的计数。`prefix` 逐字来自 `obligations` 的四个常量；"
     "`unowned` 是「父台账号与收件实例都空」的那些（没人收）；`summoned` 只对 "
     "b-register 有意义（`d-handoff` 没有召唤行，恒为 0）。`tri` / `reason` 是这一族"
     "自己的三态：`d-handoff` 的逐条读数（gap/eligible）没跑成时是 `unreadable`，"
     "而 `open` / `unowned` 仍是同一块 tasks 板的行数（不是 0）",
     (("name", "string"), ("role", "string"), ("why", "string"),
      ("prefix", "string"), ("open", "number"), ("unowned", "number"),
      ("summoned", "number"), ("instances", "string[]"),
      ("tri", "Tri"), ("reason", "string"))),
    ("ObligationRow",
     "obligations_face() 的 rows[] —— 一条还开着的板项（收件实例 / 父台账号 / "
     "项状态 / 叫醒行）。`recipient_instance` 是板项行的 instance 列"
     "（`obligations.recipient_reading` 的落点）；`addressed` 是 instance / parent / "
     "unowned 三档",
     (("task_id", "string"), ("key", "string"), ("family", "string"),
      ("role", "string"), ("recipient_instance", "string"),
      ("parent_task_id", "string"), ("item_state", "string"),
      ("item_close", "string"), ("opened_at", "string"),
      ("wake_task_id", "string"), ("addressed", "string"), ("detail", "string"))),
    ("ObligationsView",
     "obligations_face() —— 板上四族义务的收件人读数（只读；销号不经过网页）",
     (("tri", "Tri"), ("reason", "string"), ("source", "SourceRef"),
      ("checked", "boolean"), ("families", "ObligationFamily[]"),
      ("rows", "ObligationRow[]"),
      ("counts", "Record<string, Record<string, number>>"),
      ("recipient_rule", "string"), ("addressing", "Record<string, unknown>"),
      ("problems", "string[]"))),
    ("LibraryView",
     "library_face() —— 文献库那一面：只算「正式入库」的文献 + 每篇被哪些命题／"
     "哪一份证明用过（`state` 只有 computed / unknown 两档；`unknown` 有两支 ——"
     "台账没读成、以及「没有候选台账 ⇒ 入库判不出」，两支的 `data.count` 都是 null，不是 0）",
     (("checked", "boolean"), ("state", "string"), ("reason", "string"),
      ("data", "LibraryData"), ("problems", "LibraryProblem[]"))),
    ("LibraryData",
     "library_face() 的 data —— 入库文献那几栏与判据的来源"
     "（`rows_total` 是台账里一共几行，`count` 是显示几条；两者之和不必相等："
     "待入库与判不出的都不显示。`admission_source` 只有一个取值：那一格是唯一判据）",
     (("works", "LibraryWork[]"), ("count", "number | null"), ("table", "string"),
      ("table_state", "string"), ("rows_total", "number | null"),
      ("admission_source", "string"), ("admission_tri", "Tri"),
      ("undecidable", "number | null"),
      ("uses_tri", "Tri"), ("uses_reason", "string"),
      # SEEDFIX（2026-11-22）：种子在 `reference/`、`library/` 是已登记书架。
      # `library_unregistered` 非空 = 书架上有没登记的文件（`null` = 没查成，
      # 不是"干净"）—— 这一格以前在页面上完全没有读数。
      ("seed", "LibrarySeed"))),
    ("LibrarySeed",
     "library_face() 的 data.seed —— 种子读数（`seedinject.read_seed_reading` 的"
     "工作区相对形态）：种子在 `reference/`，`library_unregistered` 是书架上没有"
     "`literature` 行引用的 PDF（`.txt` 是 `text.extract` 的设计产物，不算；"
     "`null` = 没查成）",
     (("landed", "boolean"), ("count", "number"), ("bytes", "number"),
      ("destination", "string"), ("marker", "string"),
      ("legacy_root_marker", "boolean"),
      ("library_unregistered", "string[] | null"), ("reason", "string"))),
    ("LibraryWork",
     "library_face() 的 data.works[] —— 一条「正式入库」的文献（`admitted` 恒为 true："
     "判不出的不进这个数组，而判据只有 `lit_candidates.status=admitted` 那一格）。"
     "`download_state` 是 download 那一格与盘上文件核对的三态"
     "（present / absent / unreadable），`uses` 是反查出来的「被谁用过」",
     (("lit_id", "string"), ("title", "string"), ("authors", "string[]"),
      ("doi", "string"), ("dedup_key", "string"), ("pages", "string"),
      ("matched", "string"), ("claimed_by", "string"), ("mine_attempts", "number"),
      ("last_mine_error", "string"),
      ("download_status", "string"), ("download_path", "string"),
      ("download_state", "string"), ("download_bytes", "number | null"),
      ("download_reason", "string"),
      ("admitted", "boolean"), ("admission_basis", "string"),
      ("uses", "LibraryUse[]"), ("uses_count", "number"))),
    ("LibraryUse",
     "library_face() 的 data.works[].uses[] —— 「这一篇被谁用过」的一条"
     "（`via` 只有 statement / dependency 两档：语句自己的 `source_lit_id`，"
     "与依赖的 `source_lit_id`；`proof_no` 是证明号，`#pN` 由 `proofloc` 拆）",
     (("stmt_id", "string"), ("proof_no", "number"), ("label", "string"),
      ("used_by", "string"), ("via", "string"))),
    ("LibraryProblem",
     "library_face() 的 problems[] —— 一条不拦门但要留痕的读数问题"
     "（`code` 是受控的几个码，`admission_undecidable` 就是「判不出入库/待入库」"
     "那一条：A 侧的实现问题，不显示但记一笔）",
     (("code", "string"), ("detail", "string"))),

    # ---------------------------------------------------------------- 13 两档提示词缓存
    # 这一族的真身是 `cachectl.status()` 与 `cacheface.warm_job()`。类型不手写在
    # `ui/src/api.ts`：手写的类型就是第二份口径 —— 后端加一格、`tsc` 只会觉得
    # "少了一个可选字段"，一声不吭。生成之后 `types.ts` 仍是唯一来源。
    ("CacheTargetCell",
     "cachectl.tier_reading() 的 per_target[目标] —— 一个预热目标落地/新鲜的四格",
     (("state", "string"), ("fresh", "boolean | null"),
      ("recorded_sha256", "string"), ("now_sha256", "string"),
      ("absent_reason", "string"))),
    ("CacheKeyCell",
     "cachectl.tier_reading() 的 key —— 这一档的 key 换没换（`same` / `stale` / `unknown`）",
     (("tri", "string"), ("reason", "string"), ("changed", "string[]"),
      ("affected", "string[]"), ("affected_why", "string"), ("text", "string"),
      ("recorded", "{ fingerprint: string; model: string; base_url: string }"))),
    ("CacheTier",
     "cachectl.tier_reading() —— 一档的四格读数（落地 / 新鲜 / 覆盖几个 / 缺谁）",
     (("tier", "string"), ("label", "string"), ("lean_enabled", "boolean"),
      ("tri", "string"), ("reason", "string"), ("warmed", "boolean"),
      ("fresh", "boolean | null"), ("fresh_reason", "string"),
      ("not_fresh", "string[]"), ("version_mismatch", "boolean"),
      ("covered", "number"), ("covered_fresh", "number"), ("total", "number"),
      ("missing", "string[]"), ("absent", "string[]"),
      ("absent_reason", "Record<string, string>"), ("at", "string"),
      ("prompt_version", "string"), ("readings_prompt_version", "string"),
      ("spent_usd", "number | null"), ("model", "string"),
      ("per_target", "Record<string, CacheTargetCell>"), ("key", "CacheKeyCell"))),
    ("CacheKeyReading",
     "cachectl.key_reading() —— 当前这把 key 的读数（值永不上屏：只有指纹与长度）",
     (("configured", "boolean"), ("source", "string"), ("model", "string"),
      ("base_url", "string"), ("key_chars", "number"), ("fingerprint", "string"))),
    ("CacheActive",
     "cachectl.active_reading() —— 当前这一趟会用哪一档（三层来源各自自报）",
     (("tier", "string"), ("label", "string"), ("lean", "boolean | null"),
      ("source", "string"), ("source_text", "string"), ("source_note", "string"),
      ("record_sid", "string"), ("record_at", "string"), ("record_state", "string"),
      ("strategy", "string"), ("run_at", "string"), ("prompt_version", "string"),
      ("readings_prompt_version", "string"), ("covered", "string"),
      ("covered_count", "number"), ("total", "number"), ("missing", "string[]"),
      ("absent", "string[]"), ("fresh", "boolean"), ("tri", "string"),
      ("why", "string"),
      # 这一格是"这一档的 key 换没换"（与
      # `status()["tiers"][档]["key"]` 同一份读数，形状见 `CacheKeyCell`）。
      # 读不出来时 `_active_doc` 给的是 `{}`（`dict(reading.get("key") or {})`），
      # 所以它与 `CheckpointView.spend` / `prompt_cache` 同一条写法：
      # `CacheKeyCell | Record<string, never>`，不拿必填去冒充每一档都有读数。
      ("key", "CacheKeyCell | Record<string, never>"),
      ("text", "string"))),
    ("CacheReminder",
     "cachectl.status() 的 reminder —— 换 key 那条提醒（网页顶部横幅与命令行同一句）",
     (("active", "boolean"), ("tri", "string"), ("tiers", "string[]"),
      ("text", "string"), ("affected", "string[]"), ("dismiss_key", "string"))),
    ("CacheWarmJob",
     "cacheface.warm_job() —— 最近一趟网页预热的三态"
     "（`running` / `done` / `failed` / `unknown`）",
     (("recorded", "boolean"), ("state", "string"), ("reason", "string"),
      ("log", "string"), ("log_path", "string"), ("pid", "number"),
      ("tier", "string"), ("at", "string"), ("last_line", "string"),
      ("tail", "string[]"))),
    ("CacheView",
     "GET /api/cache 的整份读数（`cachectl.status()` + 写权限读数 + 预热三态）",
     (("schema", "number"), ("at", "string"), ("readings", "string"),
      ("lean_now", "boolean"), ("prompt_version", "string"),
      ("key", "CacheKeyReading"), ("tiers", "Record<string, CacheTier>"),
      ("workspace", "string"), ("active", "CacheActive"),
      ("reminder", "CacheReminder"), ("writes_allowed", "boolean"),
      ("writes_reason", "string"), ("warm", "CacheWarmJob"),
      ("verdict",
       "{ tri: string; unknown_tiers: string[]; stale_tiers: string[];"
       " key_unknown_tiers: string[] }"))),

    # ---------------------------------------------------------------- 14 错误动作计数
    # 这一族的真身是 `readouts.errors_readout()`（口径在 `errorstats`）与
    # `errorstats.ERROR_CATEGORIES`，同样不从 `ui/src/api.ts` 手抄。
    ("ReadoutProblem",
     "errors_readout() 的 problems[] —— 一条「读到了、但人该看见」的异常"
     "（与 `LibraryProblem` 同形：两族各是各的读数，合并不省事）",
     (("code", "string"), ("detail", "string"))),
    ("ErrorStatsSource",
     "errors_readout() 的 data.sources[源] —— 逐源读数（各源的键不完全相同，"
     "所以每一格都是可选的：缺格 = 这一源没有这一栏，不是 0）",
     (("checked?", "boolean"), ("events?", "number"), ("files?", "number"),
      ("records?", "number"), ("bad_lines?", "number"),
      ("unreadable_files?", "string[]"),
      # 2026-11-24：这一格是 `{桶名: 条数}`（`tool` / `verdict` / `roster` / `secretary`），
      # 不是单个数字 —— `readouts.errors_readout` 就是按 `.items()` 读它的；声明成
      # `number` 会让类型面读不出 `{"tool": N}` 这件事（与 ⑤ 同族的"声明与真读数不符"）。
      ("unclassified?", "Record<string, number>"),
      ("table?", "string"), ("reason?", "string"), ("state?", "string"),
      ("dir?", "string"), ("path?", "string"), ("by_user?", "number"),
      ("children_unretired?", "number"), ("name_collisions?", "number"),
      ("repaired?", "number"), ("collisions?", "Record<string, number>"),
      ("blockers?", "ErrorBlocker[]"), ("status?", "Record<string, string>"),
      ("machine_pass?", "boolean"), ("can_close_reason?", "string"),
      ("source?", "string"), ("names?", "string[]"))),
    ("ErrorBlocker",
     "errors_readout() 的 data.sources.closing.blockers[] —— 收工门的一条 blocker"
     "（`closing.check_closing` 的 code / check / level 三格）",
     (("code", "string"), ("check", "string"), ("level", "string"))),
    ("ErrorClassState",
     "errors_readout() 的 data.class_state[类目] —— 那一类自己的三态"
     "（一个源读不到时只有这一类变 unknown，不许把整页拖成 0）",
     (("checked", "boolean"), ("state", "string"), ("reason", "string"))),
    ("ErrorSignalSample",
     "errors_readout() 的 data.classes[].samples[] —— 这一类的一条「去哪看」"
     "（`source` 是文件，`ref` 是文件里的记录身份，`ts` 与 `detail` 是定位与那一句原话）",
     (("role", "string"), ("code", "string"), ("source", "string"), ("ref", "string"),
      ("ts", "string"), ("detail", "string"))),
    ("ErrorClassRow",
     "errors_readout() 的 data.classes[] —— 按类的一行（四种桶各排各的，不许混排）。"
     "`computed` 只出现在现算预演那一类（`errorstats.PREVIEW_CATEGORIES`）的行上："
     "它的 `count` 不是发生次数，页面与脚本靠这一格把它分开",
     (("category", "string"), ("bucket", "string"), ("count", "number"),
      ("meaning", "string"), ("by_role", "Record<string, number>"),
      ("checked", "boolean"), ("state", "string"), ("reason", "string"),
      ("first_ts", "string"), ("last_ts", "string"), ("this_run", "number"),
      ("earlier", "number"), ("no_ts", "number"),
      ("samples", "ErrorSignalSample[]"), ("computed?", "boolean"))),
    ("ErrorStatsData",
     "errors_readout() 的 data —— 角色 × 类目的计数（只记出现过的格，缺格就是 0）。"
     "`total` 是角色侧总数；`system_total` 与 `state_readings_total` 各是另一组数，"
     "三组刻意不相加（三种单位：谁做错了 / 系统哪里坏了 / 现在积着什么）",
     (("by_role", "Record<string, Record<string, number>>"),
      ("role_total", "Record<string, number>"), ("total", "number"),
      ("categories", "Record<string, number>"),
      ("sources", "Record<string, ErrorStatsSource>"),
      ("system", "Record<string, number>"), ("system_total", "number"),
      ("state_readings", "Record<string, Record<string, number>>"),
      ("state_readings_total", "number"),
      ("classes", "ErrorClassRow[]"),
      ("class_state", "Record<string, ErrorClassState>"),
      ("samples", "Record<string, ErrorSignalSample[]>"),
      ("run_boundary", "string"))),
    ("RoleErrorsView",
     "GET /api/errors 的整份读数（`readouts.errors_readout()` 逐字）",
     (("checked", "boolean"), ("state", "string"), ("reason", "string"),
      ("data", "ErrorStatsData"), ("problems", "ReadoutProblem[]"))),
    ("ErrorCategoryMeaning",
     "errorstats.ERROR_CATEGORIES 的一行 —— 类目与它那一句含义",
     (("name", "string"), ("meaning", "string"))),
    ("ErrorCategoryGlossary",
     "GET /api/errors/categories 的整份读数（一张常量表，无三态）",
     (("categories", "ErrorCategoryMeaning[]"), ("source", "string"))),

    # ---------------------------------------------------------------- 15 论文包三块
    # `GET /api/package` 一次给三块（A 证明 / B 结构 / C 收工）。
    # 三块顶层进 `CHECKED_TYPES`；行一级与子块类型登记在 `UNCHECKED_TYPES`（夹具
    # 不逐行造 B 的 findings / A 的 proofs），理由写在那一处。
    ("PackageView",
     "package_face() —— 论文包三块（proofs / structure / closing）",
     (("tri", "Tri"), ("reason", "string"), ("generated_at", "string"),
      ("proofs", "ProofView"), ("structure", "StructureView"),
      ("closing", "ClosingView"))),
    ("ProofView",
     "package_face() 的 proofs —— A 块（review 六态 / streak / defect_step / V 签 / 回执 / C3）",
     (("tri", "Tri"), ("reason", "string"), ("source", "SourceRef"),
      ("paper_theorem_envs", "number | null"),
      ("propositions_with_proof", "number | null"),
      ("ledger_theorem_kinds", "number | null"),
      # 读侧投影之后的定理类条数（KINDREAD）：与上面那一格并列，原值不许被顶替。
      ("ledger_theorem_kinds_projected", "number | null"),
      ("signed", "number | null"),
      ("coverage_note", "string"), ("review_states", "Record<string, number>"),
      ("rows", "ProofRow[]"), ("vsign", "VsignView"), ("receipt", "ReceiptView"),
      ("c3", "C3View"))),
    ("ProofRow",
     "package_face() 的 proofs.rows[] —— 一条命题的 review 读数",
     (("stmt_id", "string"), ("label", "string"), ("kind", "string"),
      ("status", "string"), ("state", "string"), ("grade", "string"),
      ("reviewed", "boolean"), ("proofs", "ProofItem[]"), ("source", "SourceRef"))),
    ("ProofItem",
     "ProofRow.proofs[] —— 一条证明自己的读数（#p1 的票不替 #p2 数）",
     (("proof_no", "number"), ("state", "string"), ("streak", "number"),
      ("need", "number"), ("streak_ok", "boolean"), ("grade", "string"),
      ("verification_id", "string"), ("defect_steps", "number[]"),
      ("source", "SourceRef"))),
    ("VsignView",
     "package_face() 的 proofs.vsign —— `vsigns.backed_reading`（side files / 覆盖率）",
     (("tri", "Tri"), ("reason", "string"), ("files", "number"),
      # 「签了几份」的唯一口径：复算通过的 `<sha>.json` 份数。
      ("recomputable", "number | null"),
      ("signed", "string[]"), ("backed", "string[]"),
      ("without_sign", "string[]"), ("orphan_signs", "string[]"),
      # 台账（`issued.json`）是索引，不是签：在不在单独一格（整块没查成 ⇒ null）。
      ("ledger_present", "boolean | null"), ("ledger_path", "string"),
      # RECONFIX2（2026-11-22）：逐份 `sign_reading.state` 的分布，以及
      # `sign_does_not_back_the_row` 的份数（`null` = 那一格没查成，不是 0）。
      # 它不算签，也不折进 `unbacked` —— 页面用它把两者分开。
      ("sign_states", "Record<string, number>"),
      ("sign_does_not_back_row", "number | null"),
      ("note", "string"),
      ("source", "SourceRef"))),
    ("ReceiptView",
     "package_face() 的 proofs.receipt / closing.undelivered —— `vsigns.receipt_digest`",
     (("checked", "boolean"), ("reason", "string"), ("receipts", "number"),
      ("statements", "number"), ("delivered", "number"), ("dispatched", "number"),
      ("not_dispatched", "number"), ("undelivered", "number"),
      ("undelivered_ids", "string[]"), ("steps", "Record<string, number>"),
      ("submitter_is_not_author", "number"), ("author_not_recorded", "number"),
      ("source", "SourceRef"))),
    ("C3View",
     "package_face() 的 proofs.c3 —— 验收表（`closing.ACCEPTANCE_TARGETS_NAME`）的 C3 行",
     (("id", "string"), ("name", "string"), ("got", "number | null"),
      ("min", "number | null"), ("ok", "boolean"), ("detail", "string"),
      ("source", "SourceRef"))),
    ("StructureView",
     "package_face() 的 structure —— B 块（正文体量 / 七类扫描 / 台账覆盖）",
     (("tri", "Tri"), ("reason", "string"), ("source", "SourceRef"),
      ("paper", "PaperFacts"),
      ("checks", "Record<string, StructureCheck>"), ("ledger", "LedgerFacts"),
      ("findings", "StructureFinding[]"))),
    ("PaperFacts",
     "StructureView.paper —— `out/package/main.tex` 的体量与编译回执",
     (("tex_path", "string"), ("exists", "boolean"),
      ("lines", "number | null"), ("sections", "number | null"),
      ("subsections", "number | null"), ("env_counts", "Record<string, number>"),
      ("proof_envs", "number | null"), ("pdf_pages", "number | null"),
      ("pdf_exists", "boolean"), ("compile_receipt", "boolean"),
      ("receipt_verdict", "string"), ("reason", "string"))),
    ("StructureCheck",
     "StructureView.checks[七类之一] —— 这一类的三态与命中数",
     (("checked", "boolean"), ("reason", "string"), ("findings", "number"),
      ("counts", "Record<string, number>"))),
    ("StructureFinding",
     "StructureView.findings[] —— `texaudit.scan_tex` 的一条 finding（带 file:line）",
     (("kind", "string"), ("severity", "string"), ("file", "string"),
      ("line", "number"), ("ref", "string"), ("why", "string"),
      ("text", "string"), ("source", "SourceRef"))),
    ("LedgerFacts",
     "StructureView.ledger —— `texaudit._scan_ledger` 的五个数 + surplus",
     (("statement_envs", "number | null"), ("proof_envs", "number | null"),
      ("statement_ledger_rows", "number | null"), ("ledger_propositions", "number | null"),
      ("ledger_theorem_kinds", "number | null"),
      # 读侧投影（KINDREAD）：按 `evidencebits.kind_at_registration` 现算的定理类条数；
      # 上面那一格仍是盘上 `kind` 数出来的原值（两个并列，投影不冒充原值）。
      ("ledger_theorem_kinds_projected", "number | null"),
      ("mapping_rows", "number | null"), ("statement_surplus", "string[]"),
      ("mapping_state", "string"))),
    ("ClosingView",
     "package_face() 的 closing —— C 块（八格四态 / 机器口径 / 成本 / 时间轴 / 内容级）",
     (("tri", "Tri"), ("reason", "string"), ("source", "SourceRef"),
      ("gates", "GateTable"),
      ("machine", "MachineCaliber"), ("undelivered", "ReceiptView"),
      ("cost", "CostView"), ("runtime", "RuntimeView"),
      # READOUT-FIX：第六档（签不背书这一行）的独立读数（黄档；`count=null` 是没查成）。
      ("unsigned_signs", "UnsignedSignBacking"),
      ("content", "ContentAcceptance"))),
    ("GateTable",
     "ClosingView.gates —— 收工门八格的四态一张表（＋ machine_pass 的两条来源）",
     (("cells", "GateCell[]"), ("counts", "Record<string, number>"),
      ("machine_pass", "boolean"), ("m_says_done", "boolean"),
      ("can_close", "boolean | null"), ("can_close_reason", "string"),
      ("closable", "boolean"), ("verdict_at", "string"),
      ("verdict_met", "boolean | null"),
      # 一份权威结论（ROOTGATE-②）：verdict + 八格逐格 + 红格的 why 都在这一格里，
      # 页面必须与 machine_pass / m_says_done 并列显示（旧后端没有这一格时是 null）。
      ("closing_verdict", "ClosingVerdict | null"),
      # `machine_pass=false` 的几条来源分开点名 —— 只看
      # `blockers=[]` 会把"格失败"读成"门没拦住"，只看 counts 又会漏掉不进八格的
      # blocker。`machine_pass_cause` 是受控词：pass / cells / blockers / blockers+cells
      # / na / unknown（`na` 只由 na 格造成 false；最后一档是"几条都空而 machine_pass 假"
      # 的缺陷读数）。
      ("blockers", "GateBlocker[]"), ("blocking_cells", "GateCell[]"),
      # `na` 单列（READFIX-D-10）：它让 machine_pass=false，但不拦权威结论
      # （`closing.closing_verdict` 的 fail 清单不收 na）。
      ("na_cells", "GateCell[]"),
      # READFIX-B：`pass` + warning 那一档（artifact_ledger 的 changed）：
      # `{格名: [原话]}`，页面在绿 badge 旁边照样显它（不改 `cells` 的格形状）。
      ("warnings", "Record<string, string[]>"),
      ("machine_pass_cause", "string"))),
    ("ClosingVerdict",
     "GateTable.closing_verdict —— `closing.closing_verdict` 的逐字读数"
     "（一份权威结论：verdict / exit_code / 八格逐格 / 机器读数 / blockers）",
     (("verdict", "string"), ("exit_code", "number"),
      ("authoritative", "boolean"), ("cells", "ClosingVerdictCell[]"),
      ("counts", "Record<string, number>"), ("m_says_done", "boolean"),
      ("retire", "Record<string, unknown>"), ("programs", "Record<string, unknown>"),
      ("blockers", "GateBlocker[]"), ("machine_pass", "boolean"),
      ("can_close", "boolean | null"), ("reason", "string"))),
    ("ClosingVerdictCell", "GateTable.closing_verdict.cells[] —— 一格（三态 + why 原话）",
     (("check", "string"), ("status", "string"), ("why", "string"))),
    ("GateBlocker",
     "GateTable.blockers[] —— 不进八格、却拦 machine_pass 的一条 Finding"
     "（`closing.Finding.to_dict()` 的 check / code / level / detail）",
     (("check", "string"), ("code", "string"), ("level", "string"),
      ("detail", "string"))),
    ("GateCell",
     "GateTable.cells[] —— 一格（`pass` / `fail` / `unknown` / `na`）",
     (("name", "string"), ("status", "string"), ("detail", "string"),
      ("source", "SourceRef"))),
    ("MachineCaliber",
     "ClosingView.machine —— `closing.machine_caliber` + retire / programs",
     (("checked", "boolean"), ("value", "boolean | null"), ("reason", "string"),
      ("retire_checked", "boolean"), ("retire_complete", "boolean"),
      # ROOTGATE-③：retire 的"收尾前自动收尾之后"那份投影（与 final 闸同一份判据）。
      ("retire_projected", "boolean"), ("retire_auto_retire", "Record<string, unknown>"),
      ("retire_open_items", "number"), ("retire_nodes", "number"),
      ("retire_states", "Record<string, number>"), ("programs_checked", "boolean"),
      ("programs_ok", "boolean"),
      ("programs_running_count", "number"), ("programs_unowned", "string[]"),
      ("source", "SourceRef"))),
    ("CostView",
     "ClosingView.cost —— 三源并排（事件求和 / 收工行自报 / 无人认领）",
     (("checked", "boolean"), ("reason", "string"),
      ("event_usd", "number | null"), ("spend_usd", "number | null"),
      ("spend_unknown_usd_calls", "number | null"),
      ("unattributed_usd", "number | null"), ("runs_without_spend", "number"),
      ("ledger_usd", "number | null"), ("usage_ledger_rows", "number | null"),
      # READFIX-D-5：账本那一格自己的三态与原因 —— "还没写过"（not_applicable）
      # 与"读不出来"（unreadable）都不许折成 `ledger_usd=0` + `checked=true`。
      ("ledger_tri", "Tri"), ("ledger_reason", "string"),
      # 四个数并排却不给差额的解释 = 读者只能说"三个对不上"（WEBCAP B10）。
      ("reconciliation", "CostReconciliation"),
      ("source", "SourceRef"))),
    ("CostReconciliation",
     "ClosingView.cost.reconciliation —— 账本 − 事件 = extract 那几笔；账本行数 ≠ 调用数",
     (("by_scope", "Record<string, UsageBucket>"),
      ("extract_usd", "number | null"), ("extract_entries", "number | null"),
      ("event_llm_calls", "number | null"),
      ("ledger_minus_event_usd", "number | null"),
      ("explained_by_extract", "boolean | null"), ("note", "string"))),
    ("RuntimeView",
     "ClosingView.runtime —— 时间轴与名册两个读数",
     (("first_start_ts", "string"), ("last_event_ts", "string"),
      ("elapsed_sec", "number | null"), ("runs_total", "number | null"),
      ("open_runs", "number | null"), ("in_flight_agents", "number | null"),
      ("last_closing_at", "string"), ("roster_nodes", "number"),
      ("children_in_ledger", "number | null"),
      ("roster_child_count", "number | null"),
      ("children_unretired", "number | null"),
      ("active_child_count", "number | null"), ("unplaced", "number"),
      ("source", "SourceRef"))),
    ("ContentAcceptance",
     "ClosingView.content —— reviewaccept 五条（只读、不进机器门）",
     (("tri", "Tri"), ("reason", "string"),
      ("criteria", "Record<string, string>"), ("details", "Record<string, string>"),
      ("titles", "Record<string, string>"), ("sources", "Record<string, SourceRef>"),
      ("failed", "string[]"),
      ("unchecked", "string[]"), ("passed", "boolean"), ("note", "string"))),
    ("UnsignedSignBacking",
     "ClosingView.unsigned_signs —— 「签不背书这一行」那一档（黄；只数、不判）",
     (("checked", "boolean"), ("count", "number | null"), ("class", "string"),
      ("stmt_ids", "string[]"), ("note", "string"))),
    ("SourceRef",
     "每一格的原文出处（`/api/source` 的三个入参 + 一个标签）",
     (("path", "string"), ("line", "number"), ("match", "string"),
      ("label", "string"))),
    ("SourceWindow",
     "GET /api/source 的读数 —— 一个文本文件的原文窗口（受控拒绝时 lines 为空）",
     (("tri", "Tri"), ("reason", "string"), ("path", "string"),
      ("line", "number"), ("start_line", "number"), ("lines", "string[]"),
      ("total", "number | null"), ("truncated", "boolean"))),
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


#: `RunRow` 的 25 个键（`draft/75 §1.3` 的 C3 表 + 162 的五格；`webui/state.py:_scan`
#: 与 `sessions.runs_in_session` 逐字同形）。`RunRow` 那个接口由 A 线的 `state.py` 声明，
#: 所以这里的键名只能自己列一份 —— 判据 `test_the_run_row_keys_match_sessions`
#: 会断言这一份与 `sessions.runs_in_session` 真给出的键集合相同（漂移当场红）。
#:
#: ## `events_in_run` 改名 `events_span`，另加 `events_owned`
#:
#: 那一格叫「趟内事件」时，算的是 `end_index - start_index` —— 它是「下标跨度」，
#: 不是"这一趟发了几条事件"。多代理共写同一份会话文件时，整段跨度里「别人的」事件
#: 全被算进来：81 上 71 趟的合计是 70055，而真实事件只有 6514（10.75 倍）；M 那行
#: 6512 里最多只有 512 条可能是它自己的（359 条带自己的 `task_id` + 153 条空编号但
#: `role=M`），至少 6001 条是别人的。名字说"趟内事件"、数说"跨度"，这本身是一句假话，
#: 所以：「纯跨度那一格改名」（`events_span`，数一个字节都不动），「另给一格」
#: `events_owned`（按 `runs_in_session` 那三档归属只数归到这一趟的：81 上 70055 → 6254，
#: M 那行 6512 → 521）。
#:
#: 为什么「不」改成"按 `task_id` 过滤"：`agent_step` 事件里「没有」 `task_id`
#: （81 上 2419 条全都没有），按 `task_id` 过滤会把步数整族丢光 —— M 那行会读成 360，
#: 比真值 512 还小。判据 `test_events_owned_counts_the_steps_that_carry_no_task_id`
#: 就是钉这件事的反真空。
#:
#: ## `spend_usd` / `spend_unknown_usd_calls` 加进来，而 `usd` 不换
#:
#: 只有一格钱（`usd` = 把「归到这一趟的」 `llm_call.usd` 加起来）时，收工那
#: 一行自己带着这一趟的账（`agent_run_end.spend`，写侧是 `agent_loop.py` 的收工事件、
#: 形状是 `llmseam.SeamSpend.to_dict()` 的 5 格）。两处数的不是同一件事：
#:
#: - `usd`：「事件流」求和。空 `task_id` 的调用按 role 猜主人（`_owner_of` 的 ② 档），
#:   多代理交错时会算到别家头上；81 上 71 趟里 18 趟与自己的收工行有小数差
#:   （合计 5.728771 vs 5.678979，差 $0.049792）。
#: - `spend_usd`：「这一趟自己的缝」记的账。它不看 `task_id`，所以它天然认得
#:   "自己发出的、事件里没记编号"的调用 —— 那正是事件求和漏掉/抢走的那部分。
#:
#: 为什么「两个都给」而不是拿 `spend_usd` 顶替 `usd`：`webui.readers.run_view` 的
#: `same_run_spend_usd` 与 `checkpoint_spend_usd` 是页面那一栏"同一趟的两个来源并排"，
#: 而 `usd`（事件求和）是这个数「唯一」的独立第二读数。换掉它，那一栏就变成
#: "同一个来源的两次抄写"，从此永远绿 —— 那张卡的全部意义就没了。
#:
#: 三态：`spend_usd` / `spend_unknown_usd_calls` 在没有收工行（`end_index is None`）
#: 时是 「`None`，不是 `0`」 —— "这一趟没写收工行"与"这一趟花了 0 元"是两件事。
#: ## `task_id` + `task_id_source` 进契约
#:
#: 行里一直有 `task`（那一段任务文本），却没有「绝对编号」 —— 于是页面上"这一趟是谁的活"
#: 答不出来，也没法拿去和名册 / 台账对。编号在写侧一直有：`agent_run_start` 与
#: `agent_run_end` 都带 `task_id`（`agent_loop.run` 的写入口）。
#:
#: 三态：读不到写 「`""`」（不造一个假编号），并配一格 `task_id_source`
#: （`"event"` = 事件里真有 / `"missing"` = 这一趟的开场事件没有编号）。
#: 为什么只有两个取值、没有 `ChatLine` 那种 `inherited`：这一面「没有继承路径」 ——
#: 编号只能来自这一趟自己的开场事件，不从相邻事件借（借了就等于替它编一个号）。
#:
#: 实测：78–81 的 236 趟 「236/236」 都有非空唯一编号；但全仓 722 趟里
#: 27 趟没有（`p5-review-*` / `p6e` / `p6f` 等 10 月初的工作区）⇒ 必须留 `""` 这一档。
RUN_ROW_KEYS: tuple[str, ...] = (
    "sid", "role", "task", "task_id", "task_id_source",
    "start_index", "start_ts", "steps", "llm_calls", "usd",
    "unknown_usd", "spend_usd", "spend_unknown_usd_calls",
    "stop_reason", "final_chars", "summons", "messages", "elapsed_sec",
    "last_shape", "end_index", "end_ts", "waiting_on", "waiting",
    "events_span", "events_owned",
    # 「有 start 没 end」不是「还在跑」的判据（82 的定格数据）。这一格由
    # `webui.state.mark_stale_loops` 现算（与 `/api/state` 的 `runs[]` 同一处），
    # 所以它也是"两份读口逐字同形"里的那一格（判据见
    # `tests/test_the_run_row_has_two_readers_that_agree.py`）。
    "stale_loop",
)


def type_decls() -> str:
    """本模块（六个只读面）那一段 TS 声明文本。

    渲染不在本文件：唯一实现在 `webui/state.type_decls`（本文件只留这一行转发 ——
    排版改一处，三面同时跟上）。

    形状是 `draft/78 §3` 的接缝之一：`agentflow/web/emit_types.py` 把三条零交线
    各自的 `type_decls()` 拼成 `ui/src/types.ts`。于是加接口这件事永远发生在
    自己那一行里。
    """
    return _state.type_decls(_TS_TYPES, ())


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
    "handle_package": handle_package,
    "handle_source": handle_source,
    "handle_machine": handle_machine,
    "handle_budget_view": handle_budget_view,
    "handle_live": handle_live,
    "handle_usage": handle_usage,
    "handle_status_reports": handle_status_reports,
    "handle_chat": handle_chat,
    "handle_roster": handle_roster,
    "handle_obligations": handle_obligations,
    # AUDIT F11：网页操作台账（只读，最新在前，分页）。
    "handle_actions": handle_actions,
    # `handle_library` 在文件末尾单独登记（那个处理器的正文也住在后面）。
})

def _roster_from_tasks(root_p: Path) -> dict[str, Any]:
    """台账兜底：名册读不到时，从 `data/tasks.json` 建一棵树（标成 `unregistered`）。

    业主（"网页完整接入名册机制!!"）：名册是"父 + 子 + 绝对编号"的唯一真身，
    但当登记没发生时，页面上不该是"什么都没有" —— 那会让读的人以为"这次没派活"。
    台账里明明有 A/E/D 这些带父的代理行，它们就是"存在、但不在名册上"的证据。

    所以这一档三件事一起给：
    1. `nodes` 照给（`task_id` / `role` / `parent_task_id` / `depth` / `status`），
       每个节点带 `registered=False` 与 `name=""`（它确实没有名册名）；唯一的例外是
       根那一行：与名册那一侧同一条口径，它的 `role` / `name` 空串补成主控
       （见 :func:`_roster_root_identity`）；
    2. `coverage.unrostered` 点名这些编号（"名册上没有它们"是结论，不是缺省）；
    3. `answer` 仍然是 `"unknown"`（名册那一格没读到），但 `reason` 里说清
       "下面这棵树来自台账，不是名册" —— 三态不折平，页面上却看得见人。
    """
    from ..boardrows import row_is_open

    path = root_p / "data" / "tasks.json"
    try:
        rows = list((json.loads(path.read_text(encoding="utf-8")) or {}).get("rows") or [])
    except (OSError, json.JSONDecodeError):
        return {"nodes": [], "roots": [], "children_of": {}, "count": None, "max_depth": None,
                "coverage": {"tasks_agents": None, "roster_nodes": 0, "unrostered": None},
                "unplaced": [],
                "states": _roster_states_blank(f"{path} 读不出来 ⇒ 三态也判不了"),
                "reason": f"{path} 读不出来 ⇒ 台账兜底也读不到"}
    agents = [r for r in rows if str(r.get("kind") or "") == "" and str(r.get("task_id") or "")]
    # 三态：这一档的节点一个都不在任何名册里 ⇒ 没有人能给它销号（销号只发生在名册项上），
    # 所以 `retired` 一律 False 是一个成立的结论，不是猜的（`roster_checked=True`）。
    fallback_clock = clock_waiters(root_p)
    three = agent_states(agents, clock=fallback_clock)
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
        kid_rows = by_parent.get(tid, [])
        kids = [{"name": "", "role": str(k.get("role") or ""), "task_id": str(k.get("task_id")),
                 "retired": False} for k in kid_rows]
        status = str(row.get("status") or "")
        node_depth = depth(tid)
        # 与名册那一侧同一条口径：根（`depth == 1`）的 role / name 空串补成主控。
        # 这一档其余节点的 `name` 仍然是空串 —— 它们确实没有名册名（台账里没有名字）。
        node_role = str(row.get("role") or "")
        node_name = ""
        if node_depth == 1:
            node_role, node_name = _roster_root_identity(node_role, node_name)
        parent_name = ""
        if parent and parent in roots:
            _, parent_name = _roster_root_identity("", parent_name)
        nodes.append({
            "task_id": tid, "name": node_name, "role": node_role,
            "parent_task_id": parent, "parent_name": parent_name,
            "children": kids, "retired": False, "retired_branch": "",
            # 这一档整棵树都来自台账：子数就是台账子数，名册项数恒为 0，
            # 于是每一个子都"没落名册"（它们确实不在任何名册文件里）。
            "children_in_ledger": len(kid_rows), "roster_child_count": 0,
            "unrostered_children": [
                {"task_id": str(k.get("task_id") or ""),
                 "role": str(k.get("role") or ""),
                 "status": str(k.get("status") or ""),
                 "started_at": str(k.get("started_at") or ""),
                 "ended_at": str(k.get("ended_at") or ""),
                 "why": "名册那一格没读到 ⇒ 这一行只有台账，名册上没有它"}
                for k in kid_rows],
            "brief": "", "brief_source": "", "surface": "",
            "status": status, "task_found": True,
            # 与名册那一侧同一条口径（`boardrows.row_is_open`）：板项按 item_state、
            # 代理行按 status。这一档的 `agents` 已经滤掉板项行，所以结果与旧写法相同，
            # 但"读的是哪个口径"只有一个答案。
            "in_flight": 1 if row_is_open(row) else 0,
            # 三态（判定在 `conductor.agent_state`）：这一档每个节点就是台账那一行。
            "state": str((three.get(tid) or {}).get("state") or AGENT_STATE_UNKNOWN),
            "state_reason": str((three.get(tid) or {}).get("reason") or ""),
            "inbox": {"tri": "not_applicable", "unread": None, "seen_not_acked": None,
                      "open_total": None, "other": None, "by_state": {}, "by_kind": {},
                      "items": [], "more": 0,
                      "reason": "名册没读到 ⇒ 这一档按台账兜底，收件箱未查"},
            "depth": node_depth, "registered": False,
        })
        for kid in kids:
            walk(kid["task_id"])

    for rid in roots:
        walk(rid)
    # 按父子的形状（与名册那一侧同一个函数）：父必须是台账里的一行（`pid in ids`），
    # 否则根那一行（`parent_task_id` 是空串）会被画成一个叫空串的父。
    children_of = _roster_children_of(
        {pid: kids for pid, kids in by_parent.items() if pid in ids}, roots)
    # 三态纪律：一条代理行都没有 ⇒ `count` 是 None（读不到），不是 0
    # （判据 `test_webui_roster_panel` 的"无名册 ⇒ count 为 null"那一档钉着这一点）。
    empty = not agents
    return {"nodes": nodes, "roots": roots, "children_of": children_of,
            "count": None if empty else len(nodes),
            "max_depth": None if empty else max((n["depth"] for n in nodes), default=None),
            "coverage": {"tasks_agents": None if empty else len(agents),
                         "roster_nodes": None if empty else 0,
                         "unrostered": None if empty else len(agents)},
            "unplaced": [],
            "states": (_roster_states_blank("这一档一条代理行都没有 ⇒ 三态没有落脚点")
                       if empty else
                       _roster_states_of(
                           nodes, reason="名册没读到 ⇒ 这一档的三态来自台账兜底（树也是）")),
            "reason": (f"名册那一格没读到，但台账里有 {len(agents)} 个带父的代理行"
                       f"（头几个：{sorted(ids)[:5]}）⇒ 下面这棵树来自 `data/tasks.json`，"
                       "它们存在、但不在名册上（名册登记没有发生）")}


# ====================================================================== 11 文献库
# 文献库这一节的来由：「ui侧文献库无法读出，请确认」。
#
# 现场：`literature` 表在盘上、行也在盘上，而 `readers` 里没有任何文献读数函数 ——
# 前端「文献库」那格挂着的 reason 是「今天也没有别的端点给它」。所以页面读不出不是
# 坏了，是从来没接。这一节补的就是那条端点（只读，不需要 `--allow-writes`）。
#
# 业务口径（业主逐字）：「文献库按照正式入库的算，显示时可以显示被哪些定理证明使用，
# 如果分不清哪些真入库、哪些待入库（这个没读的必要），这是A侧实现问题」。
# 三句话落成三件事：只显示判得出「已正式入库」的那些；每条显示出来的都读出被谁用过；
# 判不出的不显示，但在 `problems` 里留一条 `admission_undecidable`（A 侧的实现问题，
# 留痕不拦门）。
#
# 追裁（原话「老工作区就是读不出来」）：判据只认候选台账那一格，不退回
# `literature.matched`；没有候选台账的工作区整面记「读不出来」（`count` 是 null，不是 0）。

#: 这一面外壳里 `state` 的两档。为什么不是别处的 `tri` 三档：`state` 回答的是页面
#: 那一句「这一面读到了没有」，而「没有这一档」不是第三种结论 —— 第三种情形（表在、
#: 里面 0 条）是 `computed` + 计数 0。别处的 `tri` 词表仍然管六面，两套不互相顶替。
LIBRARY_STATE_COMPUTED = "computed"
LIBRARY_STATE_UNKNOWN = "unknown"

#: 入库判据的唯一依据：`lit_candidates.status == "admitted"`。
#: 业主的裁定（原话「老工作区就是读不出来」）：没有候选台账的工作区不许
#: 退回 `literature.matched` 那一格 —— 那一格回答的是「这一篇是不是我要的那一篇」，
#: 不是「它在不在库里」；拿一个近似的格子顶替唯一的那一格，入库与待入库就又混在一起了。
ADMISSION_BASIS_CANDIDATE = "lit_candidates.status=admitted"

#: 没有候选台账时这一面那句话（业主口径逐字；这一档 `count` 是 null，不是 0）。
LIBRARY_NO_LEDGER_REASON = (
    "这个工作区没有候选台账（lit_candidates）：正式入库的判据只有那一格，读不出不算 0 条")

#: `problems[]` 的码（受控取值；页面按码分档显示，`detail` 说人话）。
PROBLEM_ADMISSION_UNDECIDABLE = "admission_undecidable"
PROBLEM_LITERATURE_UNREADABLE = "literature_unreadable"
PROBLEM_USES_UNREADABLE = "uses_unreadable"
PROBLEM_ADMITTED_WITHOUT_ROW = "admitted_without_row"
PROBLEM_DOWNLOAD_CLAIMED_ABSENT = "download_claimed_but_absent"
#: 同一秒入库条数超过阈值的读数（Q16 第 ⑥ 条的那个 N）。信息格，不是门 ——
#: 它不进 `_library_admission`、不改任何一条显示与否，只把"这一批看起来是整批搬进来的"
#: 这件事留痕（真机 `projects/mp3-r3` 正是 10 条落在同一秒、`relevance` 48/48 全空）。
PROBLEM_BULK_ADMISSION_SUSPECTED = "bulk_admission_suspected"

#: "同一秒入库超过几条"算疑似批量（Q16 第 ⑥ 条那个 N）。
#:
#: 为什么是 5 而不是 10：一次 `lit.admit` 至多 10 条，所以同一秒 6..10 条在合法情形下
#: 也可能出现（一次调用结算十行）。但 Q16 之后每一条合法的入库都必须带 `relevance`，
#: 于是"条数 > 5 且其中至少一条没有 relevance"这两个条件一起才说明是整批搬进来的。
#: 单看条数会把合法的一次批量入库也点成嫌疑，那会让这条读数变成噪音（噪音等于没有读数）。
SUSPECT_BULK_ADMITTED_PER_SECOND = 5


def _seed_reading(root_p: Path) -> dict[str, Any]:
    """种子读数（SEEDFIX，2026-11-22）：种子投 `reference/`、`library/` 只放已登记的。

    两个键都来自 `seedinject` 的唯一读口（`read_seed_reading` / 它的
    `unregistered_library_files`），本层只把绝对路径换成工作区相对路径、把
    "没查成"（`None`）与"干净"（`[]`）分开：

    - `landed` / `count` / `bytes` / `marker`：`reference/` 里那批种子；
    - `library_unregistered`：`library/` 里没有任何 `literature` 行引用的 PDF
      （`None` = 台账读不出来，没查成 —— 绝不折成 `[]` "书架干净"）。`.txt` 不算：
      `text.extract` 的声明就是"把 PDF 文字层转成同名 `.txt` 写进 `library/`"，
      那是设计产物，列成"未登记"等于把设计允许的东西读成结构异常；
    - `legacy_root_marker`：根上有没有改前形态的 `SEED-README.md`（旧工作区）。
    """
    from .. import seedinject as SI

    out: dict[str, Any] = {
        "landed": False, "count": 0, "bytes": 0,
        "destination": f"{SI.SEED_SUBDIR}/",
        "marker": SI.MARKER_REL,
        "legacy_root_marker": False,
        "library_unregistered": None,
        "reason": "",
    }
    try:
        got = SI.read_seed_reading(root_p)
    except Exception as exc:  # noqa: BLE001 —— 读不出来 = 没查成，不是"没有种子"
        out["reason"] = f"seedinject.read_seed_reading 读不出来：{type(exc).__name__}: {exc}"
        return out
    out.update({
        "landed": bool(got.get("landed")),
        "count": int(got.get("count") or 0),
        "bytes": int(got.get("bytes") or 0),
        "legacy_root_marker": bool(got.get("legacy_root_marker")),
        "library_unregistered": got.get("library_unregistered"),
    })
    return out


def _library_table(root_p: Path, table: str) -> tuple[list[dict], str, str]:
    """读一张 store 表：返回 `(行, 四态, 说明)`。

    四态是 `ok` / `empty` / `absent` / `unreadable`（与 `_read_state` 那一套同形，
    但这里读的是 `data/<表名>.json`，不是 JSONL）。`absent` 与 `empty` 必须分开：
    前者是「这份台账根本不在盘上」—— 这一面判成 unknown；后者是「读到了，里面 0 行」。
    把两者折平，就等于把「这篇工作区还没建过文献库」读成「文献库里一篇都没有」。

    坏 JSON / 非 UTF-8 / 表里混着不是对象的行，一律 `unreadable`（`Store.rows` 自己
    就抛 `StoreError`，这一层不吞）：读不出来就是没查成。
    """
    from ..store import Store

    rel = str(_table_files().get(table) or f"{table}.json")
    path = root_p / "data" / rel
    if not path.is_file():
        return [], "absent", f"data/{rel} 不在盘上（这一面没得读，不是 0 条）"
    try:
        raw = Store(root_p).rows(table)
    except Exception as exc:  # noqa: BLE001 - 读数层：读不到就如实说没查成，不折成空表
        return [], "unreadable", f"data/{rel} 读不出来：{type(exc).__name__}: {exc}"
    if not all(isinstance(row, dict) for row in raw):
        return [], "unreadable", f"data/{rel} 里有不是对象的行（共 {len(raw)} 行）"
    rows = [dict(row) for row in raw]
    if not rows:
        return [], "empty", ""
    return rows, "ok", ""


def _library_download(root_p: Path, row: Mapping[str, Any]) -> dict[str, Any]:
    """`download` 那一格与盘上文件对一次账：在 / 不在 / 读不到 三态。

    为什么必须去盘上核一次：`download.status` 是写侧的自报（`ok` 的意思只是「那次
    下载当时成功了」），而文件可以被删、被换、被挪。只看那一格，「字节还在不在」
    这个问题从来没有被问过 —— 而它恰恰是「这一篇现在还能不能读」的全部内容。

    三态：`present`（普通文件在，`download_bytes` 是真字节数）/ `absent`（路径上什么都
    没有，或者这一行根本没给 path）/ `unreadable`（有东西但读不到字节：是个目录、
    没权限、或者 path 被唯一真身拒掉 —— 那一档不按「不在」读：没核过不等于没有）。

    ## 唯一真身：`store.library_path`（2026-11-22 业主裁定「旧工作区不必兼容」）

    改前这里直接拼 `root/library/<rel>`：不判形态，于是旧写法（分目录
    `library/<lit_id>/<名>`、带 `library/` 前缀的 `library/…`）只要文件还在盘上就
    报 `present` —— 与写侧落地闸（`store.library_path` 明说「旧布局（不再支持）」）
    和工具面正好相反。现在同一份 `path` 只按那一处解析：它拒的形态在这里
    落 `unreadable` 并把那句拒信逐字写进 `download_reason`，绝不记成 `present`。
    """
    raw = row.get("download")
    download = raw if isinstance(raw, Mapping) else {}
    status = str(download.get("status") or "")
    rel = str(row.get("path") or "").strip().replace("\\", "/")
    out: dict[str, Any] = {
        "download_status": status,
        "download_path": rel,
        "download_state": "absent",
        "download_bytes": None,
        "download_reason": "",
    }
    if not rel:
        out["download_reason"] = (
            f"这一行没有 path（download.status={status or '空'}）⇒ 盘上没有可核的文件")
        return out
    from ..store import Store, StoreError

    try:
        resolved = Store(root_p).library_path(rel)
    except StoreError as exc:
        # 旧布局（不再支持）/ 越界：两种都不是「不在」，也都不是「在」。
        out["download_state"] = "unreadable"
        out["download_reason"] = f"path={rel} 读不到（{exc}）"
        return out
    if resolved is None:
        out["download_reason"] = f"path={rel!r} 解析不出绝对路径 ⇒ 盘上没有可核的文件"
        return out
    try:
        st = resolved.stat()
    except FileNotFoundError:
        out["download_reason"] = (f"library/{rel} 不在盘上"
                                  f"（download.status={status or '空'}）")
        return out
    except OSError as exc:
        out["download_state"] = "unreadable"
        out["download_reason"] = f"library/{rel} 读不到：{type(exc).__name__}: {exc}"
        return out
    if not resolved.is_file():
        out["download_state"] = "unreadable"
        out["download_reason"] = (f"library/{rel} 不是普通文件（大概是个目录）"
                                 "⇒ 字节数没有意义")
        return out
    out["download_state"] = "present"
    out["download_bytes"] = int(st.st_size)
    return out


def _library_admission(row: Mapping[str, Any], *,
                       candidates: Mapping[str, Mapping[str, Any]]
                       ) -> tuple[bool | None, str]:
    """这一篇算不算「正式入库」：`(admitted, basis)`，`None` = 判不出。

    唯一判据：候选台账（`lit_candidates`）里这一篇那一行的 `status == "admitted"`
    （schema 原话：「admitted —— 已正式入库：`lit_id` 必须非空」）。同一张词表上
    另外两档现行值 `pending` / `rejected` 一律按「没入库」处置 —— 它们与 `admitted`
    分得开，正是这张表存在的理由。

    现在状态只有三态：盘上的历史档 `withdrawn` / `cleared` 由
    `litstage.fold_legacy` 折成 `rejected`（+ `withdrawn_by_reviewer` / `over_cap`），
    所以它们本来就不是 `admitted`，这一格一个字都没改（业主 Q16 第 ④ 条：
    入库判据仍然只读 `status == "admitted"`）。这里刻意不引入"没有 relevance
    就不算入库"的读法：提交闸问的是「A 判过没有」，这一面问的是「它在不在库里」，
    两个问题；把后者改严会让真机上那 33 条已登记的文献从文献库页上消失。

    没有候选行 ⇒ 判不出（返回 `None`）：调用方不显示它，并在 `problems` 里留一条
    `admission_undecidable`。业主的裁定：不退回 `literature.matched`
    —— 那一格回答「这一篇是不是我要的那一篇」，与「它在不在库里」是两个问题；
    拿它顶替入库判据，等于用一个近似的格子冒充唯一的那一格。

    注射点：本函数是这一面唯一的入库判断（判据 `test_f_...` 拿它做反真空：打桩成
    「全收」时，那条「只算入库」的判据必须当场红）。
    """
    cand = candidates.get(str(row.get("lit_id") or ""))
    if not isinstance(cand, Mapping):
        return None, ""
    return (str(cand.get("status") or "") == "admitted"), ADMISSION_BASIS_CANDIDATE


def _bulk_admission_problems(cand_rows: Sequence[Mapping[str, Any]]) -> list[dict[str, str]]:
    """同一秒入库条数超过阈值 ⇒ 一条 `bulk_admission_suspected` 读数（Q16 第 ⑥ 条）。

    这一格只是信息：它不参与 `_library_admission`、不改变任何一条显示与否，
    所以"文献库该显示几篇"与有没有它无关。它有存在的价值，是因为真机上那条可疑的
    路径（A 的自动链路整批 truncate）留下的痕迹只有两处：`admitted_at` 落同一秒、
    `relevance` 一片空。单看任何一处都不足以说"这是整批搬进来的"，两处一起才是。

    两个条件同时成立才记（阈值 > 5 且组里至少一条没有 relevance）：一次合法的
    `lit.admit` 也能在同一秒结算 10 行，但那 10 行今天必须各带一句 relevance。
    """
    groups: dict[str, list[Mapping[str, Any]]] = {}
    for row in cand_rows:
        if str(row.get("status") or "") != "admitted":
            continue
        at = str(row.get("admitted_at") or "").strip()
        if at:
            groups.setdefault(at, []).append(row)
    out: list[dict[str, str]] = []
    for at, group in sorted(groups.items()):
        if len(group) <= SUSPECT_BULK_ADMITTED_PER_SECOND:
            continue
        bare = [row for row in group if not str(row.get("relevance") or "").strip()]
        if not bare:
            continue
        out.append({"code": PROBLEM_BULK_ADMISSION_SUSPECTED,
                    "detail": (f"{at} 这一秒入库 {len(group)} 条，其中 {len(bare)} 条没有 "
                               "relevance ⇒ 疑似批量入库（一次通过上限的整批搬入）。"
                               "这不是门：它不改本面任何一条的显示，只是留痕 —— "
                               "判定该不该在库里仍然只看 status=admitted")})
    return out


def _library_uses(*, statements: Sequence[Any],
                  dependencies: Sequence[Any]) -> dict[str, list[dict[str, Any]]]:
    """反查「这一篇被哪些命题 / 哪一份证明用过」，键 = `lit_id`。

    两条来源，各自只有一个真身：

    - 语句自己的 `source_lit_id`（`origin="external_lit"` 的那一批）—— 证明号取
      `verifications.proof_list(row)`：`#p1` 恒在，`#p2` 起来自行上的 `proofs` 清单。
      一条证明一行，绝不把多证明压成一个数字；
    - 依赖的 `source_lit_id`（G 登记的「某个使用点依赖了这一篇」）—— 证明号取
      `used_by` 尾巴上的 `#pN`，拆法只用 `proofloc`（全仓唯一的解析点）：自己 split
      就等于允许「台账上是第 2 条、读出来是第 1 条」这种错，而它不会有任何东西报。

    `used_by` 不是 `stmt:` 前缀的（`doc:` / `relation:` / `experiment:` …）照原样留在
    那一行上、`stmt_id` 是空串：那种使用点不是一条命题，硬编一个命题号等于编读数。

    注射点：这一面唯一的一次反查（判据 `test_f_...` 把它打桩成空，那条「被引反查」
    的判据必须当场红）。
    """
    from .. import proofloc as PL
    from .. import verifications as VR

    found: dict[str, dict[tuple[str, int, str], dict[str, Any]]] = {}

    def add(lit_id: str, stmt_id: str, proof_no: int, label: str,
            used_by: str, via: str) -> None:
        if not lit_id:
            return
        slot = found.setdefault(lit_id, {})
        key = (stmt_id, int(proof_no), via)
        if key in slot:
            return
        slot[key] = {"stmt_id": stmt_id, "proof_no": int(proof_no), "label": label,
                     "used_by": used_by, "via": via}

    for row in statements:
        if not isinstance(row, Mapping):
            continue
        lit_id = str(row.get("source_lit_id") or "")
        if not lit_id:
            continue
        stmt_id = str(row.get("stmt_id") or "")
        label = str(row.get("label") or "")
        try:
            numbers = [int(no) for no, _text in VR.proof_list(row)]
        except Exception:  # noqa: BLE001 - 清单读不出来 ⇒ 按单证明（canonical）处置
            numbers = [1]
        for no in (numbers or [1]):
            add(lit_id, stmt_id, no, label, f"stmt:{PL.used_by_of(stmt_id, no)}", "statement")

    for row in dependencies:
        if not isinstance(row, Mapping):
            continue
        lit_id = str(row.get("source_lit_id") or "")
        if not lit_id:
            continue
        used_by = str(row.get("used_by") or "")
        head, proof_no = PL.parse_used_by(used_by)
        stmt_id = head[len("stmt:"):] if head.startswith("stmt:") else ""
        add(lit_id, stmt_id, proof_no, str(row.get("label") or ""), used_by, "dependency")

    return {lit_id: [slot[key] for key in sorted(slot)]
            for lit_id, slot in found.items()}


def _library_work(root_p: Path, row: Mapping[str, Any],
                  uses: Sequence[Mapping[str, Any]], basis: str) -> dict[str, Any]:
    """一条入库文献的显示行（键集合逐字等于 `LibraryWork` 的声明）。"""
    download = _library_download(root_p, row)
    authors = [str(a) for a in (row.get("authors") or []) if str(a).strip()]
    try:
        attempts = int(row.get("mine_attempts") or 0)
    except (TypeError, ValueError):
        attempts = 0
    shown = [dict(use) for use in uses]
    return {
        "lit_id": str(row.get("lit_id") or ""),
        "title": str(row.get("title") or ""),
        "authors": authors,
        "doi": str(row.get("doi") or ""),
        "dedup_key": str(row.get("dedup_key") or ""),
        "pages": str(row.get("pages") or ""),
        "matched": str(row.get("matched") or ""),
        "claimed_by": str(row.get("claimed_by") or ""),
        "mine_attempts": attempts,
        "last_mine_error": str(row.get("last_mine_error") or ""),
        "download_status": download["download_status"],
        "download_path": download["download_path"],
        "download_state": download["download_state"],
        "download_bytes": download["download_bytes"],
        "download_reason": download["download_reason"],
        "admitted": True,
        "admission_basis": basis,
        "uses": shown,
        "uses_count": len(shown),
    }


def library_face(root: str | Path) -> dict[str, Any]:
    """`GET /api/literature` 的读模型：只算正式入库的文献 + 每篇被谁用过。

    ## 返回形状（五键外壳，逐键见 `LibraryView`）

    `{checked, state, reason, data, problems}` —— 五键在每一档上都在（三态纪律：
    同一面同一批键，页面不必先判有没有这一格才敢读）。

    ## 三态（业主的口径）

    - 文献表不在盘上 / 表是坏 JSON ⇒ `checked=False` + `state="unknown"` + `reason`
      （不是 0 条：折成 0 会让页面说「库里一篇文献都没有」，而真相是这一面没读成）；
    - 表读到了、入库判据也在用 ⇒ `checked=True` + `state="computed"`，`data.count`
      是真数字（可以是 0：那是「读到了，这一档里 0 条入库」）；
    - 表读到了、可是没有候选台账（`lit_candidates` 表不在、或表在但一行候选都没有）
      ⇒ `checked=True` 但 `state="unknown"` + `reason`（业主「老工作区就是读不出来」：
      正式入库的判据只有候选台账那一格，没有它就读不出来，`count` 是 null 不是 0）。

    ## 只算正式入库的那一档

    判据的真身是 :func:`_library_admission`：只认 `lit_candidates.status=admitted` 那一格。
    显示出来的每一条 `admitted` 都是 `true`；没有候选行的那几篇不显示，但
    `data.undecidable` 记个数、`problems` 里留一条 `admission_undecidable` 点名是哪几篇
    （A 侧的实现问题，留痕不拦门）。`data.rows_total` 是台账里一共几行，它与
    `data.count` 不必相等：待入库的、判不出的都不显示，而这两件事在读数上分得开。

    ## 被谁用过

    `data.works[].uses` 是 :func:`_library_uses` 的反查结果（语句的 `source_lit_id`
    与依赖的 `source_lit_id`，每条给 `stmt_id` + `proof_no`）。反查那两张表读不到时，
    `data.uses_tri` 记 `unreadable` / `not_applicable` 并在 `problems` 里留痕 ——
    那一档绝不显示成「这一篇谁都没用过」。
    """
    root_p = Path(str(root))
    problems: list[dict[str, str]] = []

    def add_problem(code: str, detail: str) -> None:
        problems.append({"code": code, "detail": detail})

    lit_rows, lit_state, lit_why = _library_table(root_p, "literature")
    lit_rel = str(_table_files().get("literature") or "literature.json")
    data: dict[str, Any] = {
        "works": [],
        "count": None,
        "table": f"data/{lit_rel}",
        "table_state": lit_state,
        "rows_total": None,
        "admission_source": ADMISSION_BASIS_CANDIDATE,
        "admission_tri": TRI_NOT_APPLICABLE,
        "undecidable": None,
        "uses_tri": TRI_NOT_APPLICABLE,
        "uses_reason": "文献表没读到 ⇒ 反查无从做起",
        # SEEDFIX（2026-11-22）：种子投 `reference/`，`library/` 是"已登记书架"。
        # 两件事都必须看得见：种子落没落（`reference/`），以及书架上有没有没登记
        # 行引用的文件（`library_unregistered`）。后者非空就是结构异常，而它
        # 以前在页面上完全没有读数 —— 25 份未登记种子直接铺在 `library/` 根那次
        # 事故，页面照样显示"文献库 0 条"，读的人看不出书架脏了。
        "seed": _seed_reading(root_p),
    }

    if lit_state in ("absent", "unreadable"):
        add_problem(PROBLEM_LITERATURE_UNREADABLE, lit_why)
        return {"checked": False, "state": LIBRARY_STATE_UNKNOWN, "reason": lit_why,
                "data": data, "problems": problems}

    # ---- 入库判据的唯一来源（候选台账）：没有它，这一面就是读不出来
    data["rows_total"] = len(lit_rows)
    cand_rows, cand_state, cand_why = _library_table(root_p, "lit_candidates")
    candidates = {str(row.get("lit_id")): row for row in cand_rows
                  if str(row.get("lit_id") or "")}
    if cand_state in ("absent", "unreadable") or not cand_rows:
        # 业主：「老工作区就是读不出来」。三档都落这里：表不在盘上 /
        # 表读不出来 / 表在但一行候选都没有。它们都不许折成"0 条入库" ——
        # 正式入库的判据只有候选台账那一格，没有它就没法判，`count` 只能是 null。
        data["admission_tri"] = (TRI_UNREADABLE if cand_state == "unreadable"
                                 else TRI_NOT_APPLICABLE)
        data["uses_tri"] = TRI_NOT_APPLICABLE
        data["uses_reason"] = "入库判据读不出来 ⇒ 这一面不显示任何一条（反查也就不做了）"
        reason = LIBRARY_NO_LEDGER_REASON
        if cand_why:
            reason = f"{LIBRARY_NO_LEDGER_REASON}（{cand_why}）"
        add_problem(PROBLEM_ADMISSION_UNDECIDABLE,
                    f"{LIBRARY_NO_LEDGER_REASON}（{cand_why or '候选表里 0 行'}）")
        return {"checked": True, "state": LIBRARY_STATE_UNKNOWN, "reason": reason,
                "data": data, "problems": problems}
    data["admission_source"] = ADMISSION_BASIS_CANDIDATE
    data["admission_tri"] = TRI_COMPUTED

    # ---- 被谁用过（反查那两张表）
    stmt_rows, stmt_state, stmt_why = _library_table(root_p, "statements")
    dep_rows, dep_state, dep_why = _library_table(root_p, "dependencies")
    readable = ("ok", "empty")
    if stmt_state in readable and dep_state in readable:
        uses = _library_uses(statements=stmt_rows, dependencies=dep_rows)
        data["uses_tri"] = TRI_COMPUTED
        data["uses_reason"] = ""
    else:
        uses = {}
        unreadable = "unreadable" in (stmt_state, dep_state)
        data["uses_tri"] = TRI_UNREADABLE if unreadable else TRI_NOT_APPLICABLE
        data["uses_reason"] = "；".join(w for w in (stmt_why, dep_why) if w) or (
            "反查要读的 statements / dependencies 不在盘上")
        add_problem(PROBLEM_USES_UNREADABLE, data["uses_reason"])

    # ---- 逐行判入库、建显示行
    works: list[dict[str, Any]] = []
    undecidable: list[str] = []
    for row in lit_rows:
        admitted, basis = _library_admission(row, candidates=candidates)
        if admitted is None:
            undecidable.append(str(row.get("lit_id") or ""))
            continue
        if not admitted:
            continue
        lit_id = str(row.get("lit_id") or "")
        work = _library_work(root_p, row, uses.get(lit_id, []), basis)
        works.append(work)
        if work["download_status"] == "ok" and work["download_state"] != "present":
            add_problem(PROBLEM_DOWNLOAD_CLAIMED_ABSENT,
                        f"{lit_id}：download.status=ok 而盘上这一份"
                        f"{'读不到' if work['download_state'] == 'unreadable' else '不在'}"
                        f"（{work['download_reason'] or '没有理由'}）")

    if undecidable:
        add_problem(PROBLEM_ADMISSION_UNDECIDABLE,
                    "这几篇在候选台账里没有对应的行（也没有 admitted 的候选行）"
                    "⇒ 判不出「正式入库 / 待入库」，本面不显示它们："
                    + "、".join(undecidable))

    lit_ids = {str(row.get("lit_id") or "") for row in lit_rows}
    dangling = sorted({str(row.get("lit_id")) for row in cand_rows
                       if str(row.get("status") or "") == "admitted"
                       and str(row.get("lit_id") or "") not in lit_ids})
    if dangling:
        add_problem(PROBLEM_ADMITTED_WITHOUT_ROW,
                    "候选台账说这几篇已入库，而 literature 表里没有它们的行："
                    + "、".join(dangling))

    # 同一秒整批入库的读数（Q16 第 ⑥ 条）。信息格，不是门 ——
    # 它加在、也只加在 `problems` 里，`works` 与 `count` 一个字都不改。
    for item in _bulk_admission_problems(cand_rows):
        add_problem(item["code"], item["detail"])

    data.update({"works": works, "count": len(works),
                 "rows_total": len(lit_rows), "undecidable": len(undecidable)})
    return {"checked": True, "state": LIBRARY_STATE_COMPUTED, "reason": "",
            "data": data, "problems": problems}


def handle_library(handler: Any, params: Mapping[str, str],
                   query: Mapping[str, Sequence[str]]) -> None:
    """`GET /api/literature`：文献库那一面（只读，不需要 `--allow-writes`）。

    消费者只有一个：产物页里的「文献库」那张卡。这一条端点在路由表里只有一条 GET
    （没有任何配对的 POST，也没有写路径）—— 判据
    `tests/test_library_face_only_counts_admitted_works.py` 的 a 条钉着这一点。
    """
    del params, query
    _json_of(handler, library_face(handler.root))


#: 接缝的第二个落点：这条端点的处理器定义在文件末尾（这一批只追加），所以登记也在这里。
#: `routes.handler_for(name)` 会按 `ROUTES` 第三元素来这张字典里取。
HANDLERS.update({"handle_library": handle_library})

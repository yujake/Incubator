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
from pathlib import Path
from typing import Any, Mapping, Sequence

from .. import sessions as SS
from ..jsonlfile import read_jsonl_state

__all__ = [
    "CHECKED_TYPES", "EVENTS_LIMIT_DEFAULT", "EVENTS_LIMIT_MAX", "HANDLERS",
    "MISSING_TYPES", "PENDING_ENDPOINTS", "ROUTES",
    "RUN_ROW_KEYS", "UNCHECKED_TYPES", "acceptance_face", "artifacts_face",
    "chat_face", "evidence_chain", "handle_acceptance", "handle_artifacts",
    "handle_chat", "handle_evidence",
    "handle_machine", "handle_run_events", "handle_run_view", "handle_state",
    "machine_face", "run_events", "run_products", "run_view", "state_face",
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
    "RunProduct", "CheckpointView", "CheckpointSpendView", "ReportReadingView",
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
                "auxiliary_note": ""}
    criteria = {str(k): str((acc.criteria or {}).get(k, "unknown")) for k, _d in CRITERIA}
    details = {str(k): str((acc.details or {}).get(k, "")) for k, _d in CRITERIA}
    aux = {str(k): _as_text((acc.auxiliary or {}).get(k)) for k, _d in AUXILIARY_SIGNALS}
    unresolved = sorted(k for k, v in criteria.items() if v == "unknown")
    return {"tri": TRI_COMPUTED,
            "reason": ("这些格子没查成（不是通过）：" + "、".join(unresolved)
                       if unresolved else ""),
            "criteria": criteria, "details": details, "auxiliary": aux,
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
    from ..modelgw import ModelSpec, key_source
    from ..settings import (MODEL_KEYS, TOOLCHAIN_KEYS, WORKSPACE_KEYS, load_settings,
                            model_settings, settings_path, toolchain_settings,
                            workspace_settings)

    path = settings_path()
    on_disk = bool(path is not None and Path(path).is_file())
    try:
        raw = load_settings()
    except Exception as exc:  # noqa: BLE001 - 设置文件坏掉 = 没查成，不是"没配"
        return ({"path": str(path) if path else "", "exists": on_disk,
                 "toolchain": {}, "model": {}, "workspace": {}},
                TRI_UNREADABLE, f"settings.load_settings 读不出来："
                                f"{type(exc).__name__}: {exc}")
    tool = {k: str(v) for k, v in toolchain_settings().items()}
    model = {k: str(v) for k, v in model_settings().items()}
    work = {k: str(v) for k, v in workspace_settings().items()}
    # 推理强度（2026-10-10 所有者裁定「所有智能体都要能 thinking，默认 High」）：
    # 它同属"这台机器上的模型配置"，所以机器面必须报它 —— 否则台面上默认写着
    # 一切正常，而 `settings.json` 里那个值可能是 `off`。
    effort_raw = model.get("reasoning_effort", "") or ""
    effort_problem = ""
    try:
        spec = ModelSpec(base_url=model.get("base_url", "") or "",
                         model=model.get("name", "") or "",
                         api_key=model.get("api_key", "") or "",
                         reasoning_effort=effort_raw)
        effort_shown = spec.redacted()["reasoning_effort"]
    except ValueError as exc:
        # 词表外的强度：这是"查过了、那格里是坏的"，不是崩溃，也不是"没配"。
        # 所以照旧给出成形的读数，只把这一段判成 unreadable 并把原值原样回显
        # （回显成缺省会让人以为配置生效了）。
        spec = ModelSpec(base_url=model.get("base_url", "") or "",
                         model=model.get("name", "") or "",
                         api_key=model.get("api_key", "") or "")
        effort_shown = effort_raw
        effort_problem = f"{type(exc).__name__}: {exc}"
    red = spec.redacted()
    reading = {
        "path": str(path) if path is not None else "",
        "exists": on_disk,
        "toolchain": {k: tool.get(k, "") for k in TOOLCHAIN_KEYS},
        "model": {"api_key": red["api_key"], "base_url": red["base_url"],
                  "name": red["model"], "reasoning_effort": effort_shown,
                  # key 是从哪一档取到的（`"env"` / `"settings"` / 空串）。
                  # 所有者 2026-10-10 的裁定是"key 从 config 里面接"——
                  # 这一格就是那句话在机器面上的读数：`settings` 才算成立，
                  # `env` 说明有一个环境变量盖住了配置文件（写错了也不会有人发现）。
                  "key_source": key_source(),
                  "configured": spec.configured},
        "workspace": {k: work.get(k, "") for k in WORKSPACE_KEYS},
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
#: 截断这件事**不许静默**（本项目的三态纪律）：截过的线自己带着那句话。
CHAT_LINE_CLIP = 4000

#: 一次最多给多少条对话线（取**最近**的这么多条，总数照实报）。
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
    role = str(event.get("role") or "")
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
    line: dict[str, Any] = {"index": index, "who": who, "role": role, "kind": kind,
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
    这一面就是那句话的读侧 —— 把一段会话里属于**对话**的事件投影成逐条线，
    与「一趟详情」的逐条事件分开：后者是"盘上发生了什么"（含工具与模型调用），
    这一面是"谁对谁说了什么"。

    口径四条：

    - `sid` 不给 ⇒ 取**最近**的那一段（按 `last_ts`），并在 `reason` 里写明这件事
      （那是替用户做的选择，不许无声无息）；
    - 没有会话 ⇒ `not_applicable` + "还没有会话（合法初态）"，不是错误；
    - 会话文件不在盘上 ⇒ `unreadable`（`sid` 是调用方给的，找不到就是"没查成"）；
    - 有坏行 ⇒ `unreadable` + 坏行数，读得出来的那些线照常给（与 `run_events` 同一条）；
    - 线是有界的：只给**最近** `lines_max` 条，`total`/`shown` 照实报，截断逐条标明。
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
        chosen = max(sessions, key=lambda s: s["last_ts"])["sid"]
        notes.append(f"没指定会话 ⇒ 取了最近的那一段（{chosen}）")
    path = SS.session_path(root_p, chosen)
    if not path.is_file():
        return {"tri": TRI_UNREADABLE, "sid": chosen, "lines": [], "total": 0,
                "shown": 0, "clipped": False, "sessions": sessions,
                "reason": f"会话文件不在盘上：{path}"}
    events, bad = SS.read_session(root_p, sid=chosen)
    mapped = [line for i, ev in enumerate(events)
              if (line := _chat_line(i, ev)) is not None]
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
      ("tri", "Tri"))),
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
      ("at", "string"))),
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
      ("auxiliary", "Record<string, string>"), ("failed", "string[]"),
      ("auxiliary_note", "string"))),
    ("SettingsReading",
     "machine_face() 的 `settings` —— 设置文件三段（key 只给掩码后的那一份）",
     (("path", "string"), ("exists", "boolean"),
      ("toolchain", "Record<string, string>"),
      ("model", "{ api_key: string; base_url: string; name: string; "
                "reasoning_effort: string; key_source: string; "
                "configured: boolean }"),
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
     "chat_face() —— 一条对话线（`who` 只有 user / conductor / team 三档，见 CHAT_WHO）",
     (("index", "number"), ("who", "string"), ("role", "string"), ("kind", "string"),
      ("ts", "string"), ("title", "string"), ("text", "string"),
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
      ("line_range", "string"), ("created_at", "string"), ("created_by", "string"))),
    ("ReviewFindingRow",
     "store.rows(\"review_findings\")（无真机样本 ⇒ 权威来源是 `schema.ReviewFinding`）",
     (("finding_id", "string"), ("doc_id", "string"), ("kind", "string"),
      ("level", "string"), ("target", "string"), ("evidence", "string"),
      ("message", "string"), ("round", "number"), ("suggestion", "string"),
      ("status", "string"), ("resolution_note", "string"), ("created_at", "string"),
      ("created_by", "string"), ("axis", "string"), ("line", "number | null"),
      ("verbatim_quote", "string"), ("maths", "string"),
      ("line_unavailable_reason", "string"))),
    ("RelationRow",
     "store.rows(\"relations\")（无真机样本 ⇒ 权威来源是 `schema.Relation`）",
     (("relation_id", "string"), ("concept_ids", "string[]"),
      ("description", "string"), ("lit_id", "string"), ("page_range", "string"),
      ("quote", "string"), ("quote_normalized", "string"),
      ("quote_verified", "boolean | null"), ("statement", "string"),
      ("concept_group_key", "string"), ("dedup_key", "string"), ("status", "string"),
      ("duplicate_of", "string"), ("created_at", "string"),
      ("supporting_lit_ids", "string[]"))),
    ("VerificationRow",
     "verifications.list_verifications()（裁定 K2：无真机样本 ⇒ 夹具造一行）",
     (("verification_id", "string"), ("statement_id", "string"), ("verifier", "string"),
      ("verdict", "string"), ("defect_step", "string"), ("quote", "string"),
      ("why", "string"), ("findings", "Record<string, unknown>[]"),
      ("unresolved_errors", "number"), ("proof_sha256", "string"),
      ("proof_chars", "number"), ("round", "number"), ("used_faces", "string[]"),
      ("submission_id", "string"), ("at", "string"))),
    ("ArtifactRow",
     "artifacts.read_ledger() 的行（`artifacts.FIELDS` 九个键，真机 ARTIFACTS.jsonl 同形）",
     (("at", "string"), ("path", "string"), ("sha256", "string"), ("bytes", "number"),
      ("producer", "string"), ("kind", "string"), ("task_id", "string"),
      ("exit_code", "number | null"), ("note", "string"))),
    ("LedgerVerifyRow",
     "artifacts.verify_entries() 的行 —— 台账钉的 sha 与盘上现在这一版是不是同一版",
     (("path", "string"), ("sha256", "string"), ("producer", "string"),
      ("at", "string"), ("sha256_now", "string"), ("status", "string"))),
    ("HandoffRow",
     "manuscripts.read_rows() 的行（`manuscripts.write` 写的 14 个键；"
     "`revises`/`kind`/`ref_problems` 是「有就带上」的三栏）",
     (("id", "string"), ("to", "string"), ("sender", "string"), ("summary", "string"),
      ("body", "string"), ("refs", "string[]"), ("sha256", "string"),
      ("sid", "string"), ("task_id", "string"), ("format", "string"),
      ("bytes", "number"), ("path", "string"), ("note", "string"),
      ("created_at", "string"), ("revises?", "string"), ("kind?", "string"),
      ("ref_problems?", "Record<string, string>"))),
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
      ("target?", "string"))),
    ("AcceptanceCheck",
     "out/paper/ACCEPTANCE-CHECKS.json 的一行（真机 8 行 C1–C8；"
     "`closing.ACCEPTANCE_CHECKS_NAME`）",
     (("id", "string"), ("kind", "string"), ("min", "number"), ("name", "string"),
      ("note", "string"))),
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
      ("keep_alive", "boolean"))),
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
      ("withdraw_reason", "string"), ("duplicate", "boolean | null"))),
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
      ("for_question_id", "string"))),
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
})

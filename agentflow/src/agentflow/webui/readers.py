# -*- coding: utf-8 -*-
"""只读面的读模型（`draft/73` §2.3 的本体；属于 B 线那一批）。

## 这一层是什么

六个面的适配器，一个面一个函数：**只读**、**三态**、**不吞异常**。

| 面 | 函数 | 端点（`draft/75 §1.1` 的 C1 第 1–6 行） | 读什么（既有实现，不另写一份） |
|---|---|---|---|
| 快照 | :func:`state_face` | `GET /api/state` | `webui.state.snapshot()`（键集合一字不改） |
| 一趟详情 | :func:`run_view` | `GET /api/run/{sid}` | `sessions.read_session` + `runs/agent-<角色>-<sid>.json` |
| 证据链 | :func:`evidence_chain` | `GET /api/evidence` | `store.rows(...)` 七张表 + `verifications.list_verifications` |
| 产物 | :func:`artifacts_face` | `GET /api/artifacts` | `artifacts.read_ledger` · `manuscripts.read_rows` · `closing` 的验收行 · `secretary.decisions_path` · `runflow.ARTIFACTS` |
| 收工门 | :func:`acceptance_face` | `GET /api/acceptance` | `reviewaccept.check_review` |
| 本机 | :func:`machine_face` | `GET /api/machine` | `toolchain.toolchain_report` + `settings.load_settings` |

## 三态纪律（裁定 N1 + `draft/74` 的证据规则）

每一面都带 `tri` 与 `reason`，取值是 `computed` / `unreadable` / `not_applicable`
（`reviewaccept` 那一套词表；「交付说明」那一格用 `ok`/`missing`/`unknown`，两套
**不许互相顶替**）：

- 数据源**不可读**（无效 JSON、无权限、把目录当文件读）⇒ `tri="unreadable"` + `reason`；
- 数据源**不在盘上**（还没写过）⇒ 计数栏写 `None`、`tri="not_applicable"`
  + 一句"还没写过"的 `reason`。**绝不**把它折成 `0` 或空数组或 `false`；
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

**处理器的落点**（A 线已落地的那条接缝）：`routes.py` 的第三格是处理器**名字**，
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
    "CHECKED_TYPES", "HANDLERS", "MISSING_TYPES", "PENDING_ENDPOINTS", "ROUTES",
    "RUN_ROW_KEYS", "UNCHECKED_TYPES", "acceptance_face", "artifacts_face",
    "evidence_chain", "handle_acceptance", "handle_artifacts", "handle_evidence",
    "handle_machine", "handle_run_view", "handle_state_face", "machine_face",
    "run_products", "run_view", "state_face", "ts_fields", "type_decls",
]

# ====================================================================== 三态词表
#: `Tri` 的三个取值（`reviewaccept` 那一套；与 `ok/missing/unknown` 不许互相顶替）。
TRI_COMPUTED = "computed"
TRI_UNREADABLE = "unreadable"
TRI_NOT_APPLICABLE = "not_applicable"

#: 六个面（外加 `/api/stream`）挂到总路由表上的端点。第三个元素是**B 线**里那个
#: 处理器的名字（`routes.handler_for` 会去 `HANDLERS` 里按这个名字取它）。
#:
#: `/api/stream` 那一条的处理器真身在 `webui/sse.py`（`handle_stream`）—— 它登记在
#: 这张表里的理由是一条硬事实：`routes.py` 的总表是 `自有 + READER_ROUTES +
#: WRITE_ROUTES` 三个子表拼出来的，而 `sse.py` **不是**其中任何一个子表的主人；
#: 把表项写进 sse.py 会得到一个"声明了却永远进不了总表"的端点。所以 B 线对外只有
#: **一张**子表，它住在 `readers.py` 里：表项按"哪个端点"列，处理器按"它住在哪个
#: 模块"实现（两张 `HANDLERS` 字典由 `routes.handler_for` 一起查）。
ROUTES: tuple[tuple[str, str, str], ...] = (
    ("GET", "/api/run/{sid}", "handle_run_view"),
    ("GET", "/api/evidence", "handle_evidence"),
    ("GET", "/api/artifacts", "handle_artifacts"),
    ("GET", "/api/acceptance", "handle_acceptance"),
    ("GET", "/api/machine", "handle_machine"),
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
    "RunView", "EvidenceView", "ArtifactsView", "AcceptanceView", "SettingsReading",
    "MachineView", "ArtifactRow", "LedgerVerifyRow", "HandoffRow", "SecretaryDecision",
    "AcceptanceCheck", "ReportStyle", "TaskRow", "VerificationRow",
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
}

#: 契约判据 D 的例外面：本模块声明、但后端还没落地的端点（`{端点: 理由}`）。
#: 落地之后必须删掉这一行 —— 判据有一条反向断言专门抓"永不生效的豁免"。
#: B1/B3 之后这一张表是空的：六个面与 `/api/stream` 都真的在总表里了。
PENDING_ENDPOINTS: dict[str, str] = {}

#: 本模块还欠的 TS 接口（`(名字, 缺哪个消费者)`）。生成器逐条写成 TODO 注释 ——
#: 于是"这个类型为什么还没有"在生成物里是看得见的，而不是一份空话。
#: 这两条不是"缺 reader"：B2 已经把 `sessions` 侧的索引函数落地了，欠的是 A 线
#: Run 页那个消费者（页面接上之后把这两行删掉）。
MISSING_TYPES: tuple[tuple[str, str], ...] = (
    ("RunIndex",
     "缺 GUI 侧的索引消费者：`sessions.rebuild_run_index` / `load_run_index` 已落地"
     "（B2），形状见 `sessions.compute_run_index`；A 线 Run 页接上之后删掉这一行"),
    ("RunIndexDrift",
     "缺 GUI 侧的索引消费者：`sessions.reconcile_run_index` 已落地（B2），"
     "返回 `{tri, drift, reason, sessions}`；A 线 Run 页接上之后删掉这一行"),
)



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
    映射成三态。**这一层不许把 `unreadable` 折成空表**：折了之后"读不出来"与
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

    `snapshot` 就是 `webui.state.snapshot()` 的返回值**逐字**（键集合与拆包前一致，
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

    文件名按 `runs/agent-<角色>-<sid>.json` 找：**角色**是文件名中间那一段，
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
    逐行来自 `store.rows(...)`（**不另写一份读法**）；`verifications` 来自
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

    三态：`out/` 下没有一个 `run-N/`（本机真机读数就是这样：六件产物**没有真机样本**）
    ⇒ 整面 `not_applicable` + 理由里明说"这一路（run/project run）本机还没跑过"，
    而**不是**把六件都写成 `exists=false` 让人以为"跑过但文件丢了"。
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

    三态是**逐栏**的（`ledger_tri` / `handoffs_tri` / ...）：一整面里有一栏读不出来时，
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
    （读不出来就写 `""`，**不是** `0`）。

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

    **设置是机器级的，不是工作区级的**：落点由 `settings.settings_path()` 决定
    （`--path` → 环境变量 `AGENTFLOW_SETTINGS` → 包根下的 `settings.json`），
    与工作区根无关。所以本函数不吃 `root` 参数 —— 这一点写在这里免得读的人
    以为"设置读的是工作区里的那一份"。

    返回 `(读数, tri, reason)`。**key 永远不出现在这里**：`model.api_key` 只写
    "配没配"（`configured`）与掩码后的 `redacted()`（`modelgw.ModelSpec.redacted`
    在 key 非空时给 `***`）。判据 `tests/test_webui_readers.py` 有一条逐字符断言
    真 key 不在读数里。
    """
    from ..modelgw import ModelSpec
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
    spec = ModelSpec(base_url=model.get("base_url", "") or "",
                     model=model.get("name", "") or "",
                     api_key=model.get("api_key", "") or "")
    red = spec.redacted()
    reading = {
        "path": str(path) if path is not None else "",
        "exists": on_disk,
        "toolchain": {k: tool.get(k, "") for k in TOOLCHAIN_KEYS},
        "model": {"api_key": red["api_key"], "base_url": red["base_url"],
                  "name": red["model"], "configured": spec.configured},
        "workspace": {k: work.get(k, "") for k in WORKSPACE_KEYS},
        "raw_keys": sorted(raw) if isinstance(raw, dict) else [],
    }
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
    （**不是** `available=[]` —— 那是"探测过了，一个都没找到"，两者必须分得开）；
    设置文件不在盘上 ⇒ 那一栏 `not_applicable`，而整面在工具链读得出来时仍是
    `computed`（一部分没配不等于整面没查成）。
    """
    from ..toolchain import toolchain_report

    problems: list[str] = []
    try:
        report = dict(toolchain_report(env))
    except Exception as exc:  # noqa: BLE001
        return {"tri": TRI_UNREADABLE,
                "reason": f"toolchain.toolchain_report 读不出来："
                          f"{type(exc).__name__}: {exc}",
                "model": {}, "provers": {}, "lean_ready": None, "lean_path": "",
                "lean_version": "", "mathlib": {}, "can_do_formal": None,
                "settings": {}}
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


# ====================================================================== HTTP 外壳
def _json_of(handler: Any, obj: Any) -> None:
    """按 `WebHandler._json` 的形态回一份 JSON（A 线的那个方法在这里被复用）。"""
    handler._json(200, obj)  # noqa: SLF001 - 处理器与 handler 是同一族的约定接口


def handle_state_face(handler: Any, params: Mapping[str, str],
                      query: Mapping[str, Sequence[str]]) -> None:
    """`GET /api/state`：快照的三态读模型（A 线的 `handle_state` 之外的 JSON 形态）。"""
    del params, query
    _json_of(handler, state_face(handler.root))


def handle_run_view(handler: Any, params: Mapping[str, str],
                    query: Mapping[str, Sequence[str]]) -> None:
    """`GET /api/run/{sid}`：一趟详情的 JSON（`Run` + `report` + `checkpoint`）。"""
    del query
    _json_of(handler, run_view(handler.root, str(params.get("sid", ""))))


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
                "configured: boolean }"),
      ("workspace", "Record<string, string>"), ("raw_keys", "string[]"))),
    ("MachineView",
     "machine_face() —— toolchain.toolchain_report() 的键 + 设置三段",
     (("tri", "Tri"), ("reason", "string"), ("model", "Record<string, unknown>"),
      ("provers", "Record<string, unknown>"), ("lean_ready", "boolean | null"),
      ("lean_path", "string"), ("lean_version", "string"),
      ("mathlib", "Record<string, unknown>"), ("can_do_formal", "boolean | null"),
      ("settings", "SettingsReading"), ("settings_tri", "Tri"),
      ("settings_reason", "string"))),
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
     "out/secretary/<角色>.jsonl 的行（`secretary.Secretary.note_decision` 写的；"
     "`decision`/`reason`/`basis` 等是「有就带上」的几栏）",
     (("role", "string"), ("seq", "number"), ("at", "string"), ("kind", "string"),
      ("duty", "number"), ("from", "string"), ("fail_open", "boolean"),
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
     "store.rows(\"tasks\")（真机 p9b/data/tasks.json 19 键）",
     (("task_id", "string"), ("role", "string"), ("action", "string"),
      ("called_by", "string"), ("parent_task_id", "string | null"),
      ("depth", "number"), ("input_key", "string"), ("status", "string"),
      ("outcome", "string"), ("refusal_reason", "string"), ("detail", "string"),
      ("error", "string"), ("started_at", "string"), ("ended_at", "string | null"),
      ("tokens", "number | null"), ("usd", "number | null"),
      ("instance", "string"), ("artifacts", "string[]"), ("inputs", "string[]"))),
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

#: 本模块还欠的 TS 接口（`(名字, 缺哪个 reader)`）。生成器逐条写成 TODO 注释。
#: 补完一个接口就删掉它那一行 —— 这张表住在本模块里，不住在生成器里。
MISSING_TYPES: tuple[tuple[str, str], ...] = (
    ("RunIndex",
     "缺 GUI 侧的索引消费者：`sessions.load_run_index` / `rebuild_run_index` 已落地"
     "（B2），但 Run 页读它那一段属于 A 线的页面；本模块只把 `RunIndexDrift` 之外的"
     "两栏留给它。索引的形状定义在 `sessions.compute_run_index`"),
    ("RunIndexDrift",
     "缺 GUI 侧的索引消费者：`sessions.reconcile_run_index` 已落地（B2），"
     "返回形状见它自己的 docstring；页面（A 线）接上之后把这一行删掉"),
)


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
    "handle_run_view": handle_run_view,
    "handle_evidence": handle_evidence,
    "handle_artifacts": handle_artifacts,
    "handle_acceptance": handle_acceptance,
    "handle_machine": handle_machine,
})

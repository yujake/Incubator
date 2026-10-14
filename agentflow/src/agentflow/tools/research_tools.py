"""D 专用工具：研究问题台账 + 知识缺口提问 + 等待集复查。

设计基线：``test/test1/DESIGN-TOOLS.md`` §2.1（``research_questions`` 表）、
§4.4（"知识不足"的可核实判据）、§1.1（工具清单的最后一行）。

## 这一层为什么必须存在

D 的核心不是"生成文本"，而是管理一个 问题 → 证据 → 缺口 → 新证据 的循环
（§4.1）。循环里每一步都是标准操作：

  列出问题 / 记笔记 / 提交查询请求 / 复查等待中的请求 / 改状态

如果让 LLM 直接手写 JSON 去改这两张表，代价有两个：一次转义错误就写坏数据；
而且每一次"改一行"都要占掉一轮思维链。把它们固化成工具之后，智能体的思维链
只花在判断该调哪个工具上。

## 三个刻意的设计

1. `research.submit_gap` 必须查重（§4.4 最后一句）。
   同一问题若已有未完成的等待请求，绝不重复提交 —— 否则每跑一轮就向 A 的
   队列里塞一条相同的请求，A 被自己的回音刷爆，而"查重"这件事只能在这里做：
   只有这里同时知道 `question` 与 `waiting_request_ids`。

2. `research.poll_waiting` 只做确定性判断，且不写盘。
   "请求是否做完"看 `outcome`，"新文献是否消化完"看 `processed`（§4.2）。
   把状态迁移留给调用方（agent_d）而不是工具内部：工具一旦偷偷改状态，
   "这一轮到底谁动了什么"就不可审计了。这也让本工具保持 `read` 副作用，
   可以被任意多次调用而无需审批。

3. 台账（``data/research_request_ledger.json``）刻意不是 schema 表。
   它是"本问题已经问过 A 什么"的去重台账，模块私有；放进 ``schema.TABLES``
   会牵动 LOCK_ORDER / verify / rebuild，而那是别人负责的公共契约。
   用同一把 ``research_questions.lock`` 保护它，是因为所有对它的读写都在
   已经持有该锁的事务里发生（见 :func:`_read_ledger` 的前置条件）。

## 与 Store / schema 的边界

- 写盘一律走 ``store.tx(...)``，先校验后落盘由 store 保证。
- 状态合法性以 ``schema`` 为准（``QUESTION_STATUSES`` 等）；本模块不另定义
  一套词表，否则"谁说了算"会出现第二个版本。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterator

from .. import schema as S
from ..interactions import IdSpaceExhausted, admit_search_request, next_prefixed_id
from .base import ToolError, ToolResult, fail, ok, spec_from_dataclass_fields, tool
from .table_tools import assert_request_id_in_space

__all__ = ["ALL_TOOLS", "LEDGER_FILE", "install", "register", "research_list_gaps"]

#: 请求去重台账的文件名（相对 ``store.data``）。见模块 docstring 第 3 条。
LEDGER_FILE = "research_request_ledger.json"

#: 视为"请求已结束"的 outcome（``schema.SEARCH_OUTCOMES``）。
#:
#: 为什么 ``search_failed`` / ``gave_up`` 也算结束：它们同样是有效结论
#: ——"这批文献查不到"。D 必须能据此继续（要么降低置信度、要么重新提问），
#: 而不是永远停在 needs_evidence 上等一个永远不会来的答案。
_TERMINAL_OUTCOMES = ("ok", "no_results", "search_failed", "gave_up")


# ---------------------------------------------------------------- 内部工具


def _sorted_unique(values: Any) -> list[str]:
    """升序去重。``ResearchQuestion`` 的数组字段全部要求升序去重，
    所以任何写回路径都必须先过这一道 —— 否则 schema 校验会拦下来，
    表现为"改个状态却报数组没排序"这种莫名其妙的错误。"""
    return sorted({str(v) for v in (values or [])})


def _ledger_path(store: Any) -> Path:
    return Path(store.data) / LEDGER_FILE


def _read_ledger(store: Any) -> dict:
    """读台账（必须在持有 ``research_questions`` 锁的事务内调用）。

    前置条件写进 docstring 而不是靠注释提醒：台账与 ``research_questions``
    必须一起被锁住，否则两个 D 实例会各自读到"没提过"，各发一条请求。
    """
    p = _ledger_path(store)
    if not p.exists():
        return {"schema_version": S.SCHEMA_VERSION, "rows": []}
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        # 台账损坏不应让"提问"这个动作彻底不可用：退化成空台账（=可能重复提问
        # 一次），但绝不静默丢数据。重建能力由 events.jsonl 之外的调用方负责。
        return {"schema_version": S.SCHEMA_VERSION, "rows": []}
    rows = doc.get("rows")
    if not isinstance(rows, list):
        rows = []
    return {"schema_version": doc.get("schema_version", S.SCHEMA_VERSION), "rows": rows}


def _write_ledger(store: Any, doc: dict) -> None:
    """原子写台账（临时文件 → ``os.replace``），与 ``Store._atomic_write`` 同法。"""
    import os

    p = _ledger_path(store)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, p)


def _ledger_row(ledger: dict, question_id: str) -> dict | None:
    for r in ledger.get("rows") or []:
        if r.get("question_id") == question_id:
            return r
    return None


def pending_requests_of(question_row: dict, request_rows: list[dict]) -> list[dict]:
    """``question_row.waiting_request_ids`` 里尚未结束的请求。

    这是 :func:`research_submit_gap` 的查重依据，也被 agent_d 复用。
    请求行不存在（被手工删了 / 事件重建丢了）时算未结束：
    宁可挡住一次重复提交，也不要往 A 的队列里灌重复请求。
    """
    index = {str(r.get("request_id")): r for r in request_rows}
    out: list[dict] = []
    for rid in question_row.get("waiting_request_ids") or []:
        row = index.get(str(rid))
        if row is None:
            out.append({"request_id": str(rid), "done": False, "outcome": None, "missing": True})
            continue
        finished = bool(row.get("done")) or row.get("outcome") in _TERMINAL_OUTCOMES
        if not finished:
            out.append(row)
    return out


def _next_request_id(rows: list[dict]) -> str:
    """给 `search_requests` 取一个 ``r-NNNN``。

    ## 这里是转发，不是第二份实现（此前的缺陷在这里）

    本函数原先自带一份"取 max+1"的副本（`interactions.next_prefixed_id` 的同族
    逻辑，但没有前缀守卫、也没有任何上限保护），于是同一个
    `search_requests` 表有两个取号器：`table.create` / CLI / C / D / F 各走
    各的，号段语义互相冲突。更糟的是副本连
    `interactions.next_prefixed_id` 那次真实事故的教训都没带上 ——
    它接受了任意前缀形态而不做校验。

    现在：取号规则只有一份实现（`interactions.next_prefixed_id`，
    `interactions.py:1134`），前缀守卫 / 形态 / 冲突跳过全部由它负责；
    `P-4` 之后上限也在它里面，末尾的 `assert_request_id_in_space` 是第二道
    守卫（覆盖"别人自己拼了一个号传进来"的情形）。

    `P-4` 的翻译：`next_prefixed_id` 越界时抛具名的 `IdSpaceExhausted`
    （继承 `ValueError`），这里精确翻成工具层的 `ToolError` —— 不翻的话它会冒到
    `ToolRegistry.call` 被兜成 `kind='unexpected'`，于是"空间用尽（已知、可处理）"
    与"工具内部有 bug"在下游同形。不翻整个 `ValueError`：前缀违规属调用方编码错误。
    """
    try:
        return assert_request_id_in_space(next_prefixed_id(rows, "request_id", "r"))
    except IdSpaceExhausted as exc:
        raise ToolError(str(exc)) from exc


def _questions(store: Any) -> list[dict]:
    """无锁快照读（仅用于列台账；要改数据必须走 tx）。"""
    try:
        return list(store.rows("research_questions"))
    except Exception as e:  # 表不存在 / 快照损坏 => 结构化失败，而不是抛断循环
        raise RuntimeError(f"读取 research_questions 失败：{type(e).__name__}: {e}") from e


# ---------------------------------------------------------------- 工具实现


@tool(
    "research.list_gaps",
    "列出研究问题台账（D 的工作台）。按 priority(high>medium>low)、question_id 稳定排序。",
    {
        "type": "object",
        "properties": {
            "status": {"type": "string", "enum": list(S.QUESTION_STATUSES)},
            "limit": {"type": "integer", "minimum": 1, "maximum": 500},
        },
        "additionalProperties": False,
    },
    side_effect="read",
    roles=("D",),
    # 键名从一个真实调用读出（`research_list_gaps`）：`status_filter` 是这次用的
    # 过滤值（没过滤时为 None）—— 它不会缺席。
    returns="{'questions','count','status_filter'}；每题带 waiting_request_ids 以便判断是否在等",
    tags=("research", "list"),
)
def research_list_gaps(store: Any, status: str | None = None, limit: int = 50) -> ToolResult:
    """列出研究问题。

    ``status`` 过滤用 schema 的受控词表校验，非法值直接 fail：
    拼错 ``needs_evidence`` 之类的状态名如果被静默忽略，调用方会以为
    "没有这类问题"，而真相是"你写错了" —— 这两件事必须能区分。
    """
    if status is not None and status not in S.QUESTION_STATUSES:
        return fail(f"status 必须是 {S.QUESTION_STATUSES} 之一，收到 {status!r}", kind="bad_status")
    try:
        rows = _questions(store)
    except RuntimeError as e:
        return fail(str(e), kind="store_error")
    if status is not None:
        rows = [r for r in rows if r.get("status") == status]
    prio_rank = {p: i for i, p in enumerate(S.PRIORITIES)}
    rows.sort(key=lambda r: (prio_rank.get(r.get("priority"), 9), str(r.get("question_id") or "")))
    rows = rows[: int(limit)]
    return ok({"questions": rows, "count": len(rows), "status_filter": status})


@tool(
    "research.submit_gap",
    "把某研究问题的知识缺口提交给 A（在 search_requests 建一行，并把 request_id 追加进该问题的等待集）。",
    {
        "type": "object",
        "properties": {
            "question_id": {"type": "string", "minLength": 4, "maxLength": S.ID_DIGITS},
            "topic": {"type": "string", "minLength": 1},
            "mode": {"type": "string", "enum": list(S.SEARCH_MODES)},
            "description": {"type": "string"},
        },
        "required": ["question_id", "topic", "mode"],
        "additionalProperties": False,
    },
    side_effect="write_local",
    roles=("D",),
    # 键名从一个真实调用读出（`research_submit_gap`）。duplicated 两支返回同一套
    # 8 个键（`G-23`）：判重支没有被提交的请求，故 `topic`/`mode` 如实给 `None`；
    # 新建支没有"为什么跳过"这件事、也没有拦下它的未完成请求，故
    # `reason` 给 `None`、`open_requests` 给空列表 —— 调用方不必先判
    # `duplicated` 才能安全读键。
    returns=(
        "{'request_id','question_id','duplicated','topic','mode','waiting_request_ids',"
        "'reason','open_requests'}"
    ),
    tags=("research", "gap", "ask-A"),
)
def research_submit_gap(
    store: Any,
    question_id: str,
    topic: str,
    mode: str,
    description: str = "",
) -> ToolResult:
    """向 A 提交查询请求。同一问题已有未完成请求时不得重复提交。

    三步（同一事务，靠 ``search_requests`` + ``research_questions`` 两把锁串行化）：

    1. 读该问题的 ``waiting_request_ids``，逐条对照 ``search_requests`` 的
       ``done`` / ``outcome``：只要有未完成的，就直接返回
       ``duplicated=True`` 而不建新行。这就是 §4.4 要求的查重。
    2. 否则发一个新的 ``r-NNNN``，按 ``S.SearchRequest`` 建行（``submitted_by="agent-D"``）。
    3. 把新 id 追加进 ``waiting_request_ids``，状态置 ``needs_evidence``
       —— 状态与等待集必须同时落盘，因为 schema 明确拒绝
       "status=needs_evidence 却没有等待集"（那会让 D 的循环接不上）。
    """
    if not S.is_valid_id(question_id):
        return fail(f"question_id 必须是 {S.ID_DIGITS} 位十进制字符串（旧数据里的 4 位号仍可读），收到 {question_id!r}", kind="bad_id")
    if mode not in S.SEARCH_MODES:
        return fail(f"mode 必须是 {S.SEARCH_MODES} 之一，收到 {mode!r}", kind="bad_mode")
    if not str(topic).strip():
        return fail("topic 不能为空（空 topic 会让 A 的查询无从构造）", kind="bad_topic")

    try:
        with store.tx("search_requests", "research_questions", actor="agent-D", note="research.submit_gap") as tx:
            qrows = tx.rows("research_questions")
            qrow = next((r for r in qrows if r.get("question_id") == question_id), None)
            if qrow is None:
                return fail(f"研究问题 {question_id} 不存在", kind="not_found")

            req_rows = tx.rows("search_requests")

            # ---- 查重（§4.4 的硬要求）
            still_open = pending_requests_of(qrow, req_rows)
            if still_open:
                # 与"新建成功"支返回同一套 8 个键（`G-23`）。本支没有提交任何请求，
                # 所以 `request_id`/`topic`/`mode` 如实给 None —— 用 None 说"没有"，
                # 而不是让键不出现（键不出现会让调用方得先判 `duplicated`）。
                return ok(
                    {
                        "request_id": None,
                        "question_id": question_id,
                        "duplicated": True,
                        "topic": None,
                        "mode": None,
                        "reason": "该问题已有未完成的查询请求，未重复提交（否则会刷爆 A 的队列）",
                        "open_requests": [
                            {"request_id": r.get("request_id"), "outcome": r.get("outcome"), "done": r.get("done")}
                            for r in still_open
                        ],
                        "waiting_request_ids": _sorted_unique(qrow.get("waiting_request_ids")),
                    }
                )

            # ---- I7 在途配额闸门（CS-1：这条路径此前是唯一不过闸门的角色面）
            #
            # 同族的另外四条（`agent_a/core.py:72`、`agent_c/core.py:663`、
            # `agent_f/core.py:914`、`agent_d/adjudicate.py:311`）都在建行之前问过
            # `admit_search_request`，只有这一条没问 ⇒ 全局在途上限（缺省 20）
            # 可以被这条路刷爆。现场读数（`draft/41-D` §3.4 的只读探针）：先塞 25 条在途
            # 再调本工具 ⇒ 闸门说 `admitted=False`（25/20），而本工具照样把在途推成 26。
            #
            # 为什么闸门加在工具层而不是 agent 层（`agent_d/submit_gaps.py`）：
            # agent 层只挡得住 D 自己；工具层是"任何调用方走这条路"的咽喉，而别的
            # 调用方确实存在（`demo.py`、`agent_c/__main__.py` 的转交路径、手敲的工具调用）。
            # 两处都加就是两份判据 —— 本仓最忌。
            gate = admit_search_request(req_rows, submitted_by="agent-D", for_question_id=question_id)
            if not gate.get("admitted"):
                # 拒绝时一行都不写（闸门自己不落盘，这里也当场返回）。
                # `duplicated` 如实给 False：这一支不是"查重挡下的"，是"配额挡下的"；
                # 两者压进同一个布尔位，调用方就再也分不开了（三态纪律）。
                # 返回的键集与另外两支逐字相同（`G-23`）：调用方不必先判标志位才能安全读键。
                return ok(
                    {
                        "request_id": None,
                        "question_id": question_id,
                        "duplicated": False,
                        "topic": None,
                        "mode": None,
                        "reason": str(gate.get("reason") or ""),
                        # 本问题没有未完成的请求（有的话上面查重那一支已经返回了）——
                        # 占着配额的是别人的在途请求，那件事的读数在 `verify` 的
                        # `inflight_over_limit` 那一条里。不在这里拿它冒充"本问题的未完成
                        # 请求"：同一个键两种含义就是口径分裂（CS-3 的教训）。
                        "open_requests": [],
                        "waiting_request_ids": _sorted_unique(qrow.get("waiting_request_ids")),
                    }
                )

            # ---- 建请求行
            req_id = _next_request_id(req_rows)
            row = S.SearchRequest(
                request_id=req_id,
                timestamp=S.now_iso(),
                topic=str(topic).strip(),
                mode=mode,
                content_description=str(description or ""),
                done=False,
                submitted_by="agent-D",
                # 优先级由闸门按 `schema.SUBMITTER_DEFAULT_PRIORITY` 现算（不再靠
                # dataclass 的默认值碰巧等于它）：闸门算出来的口径与写进行里的那个值
                # 必须是同一个，否则"谁排前面"会有两个答案。
                priority=str(gate.get("priority") or "medium"),
                # `for_question_id` 是这一行的结构化归属（`schema.py:226-228` 逐字：
                # "该请求是为哪个研究问题服务的"）—— 从前这里不写它，于是消费方
                # （I2 闭环 / 证据就绪判据 / D 自己的每问题预算）只能拿
                # `content_description` 里的 `[q:NNNN]` 做正则（CS-2/CS-3）。
                # `question_id` 在这个作用域里是现成的参数，填它零成本。
                for_question_id=str(question_id),
            )
            row.validate()  # 先校验：绝不把非法行落到盘上
            tx.upsert("search_requests", row.to_dict(), note=f"research_gap:{question_id}")

            # ---- 更新问题的等待集与状态（两者同事务、同锁）
            waiting = _sorted_unique(list(qrow.get("waiting_request_ids") or []) + [req_id])
            qrow["waiting_request_ids"] = waiting
            qrow["status"] = "needs_evidence"
            qrow["updated_at"] = S.now_iso()
            if description:
                # 缺口理由是 D 的判断依据，必须留痕：否则下一轮无法解释
                # "当初为什么觉得不够"。用追加而不是覆盖，保留判断的历史。
                old = (qrow.get("gap_reason") or "").strip()
                qrow["gap_reason"] = (f"{old}\n{description}" if old else description)[:2000]
            S.row_from_dict("research_questions", qrow).validate()
            tx.upsert("research_questions", qrow, note=f"needs_evidence:{req_id}")

            # ---- 台账：记录"这个问题问过哪条请求、问的什么"
            ledger = _read_ledger(store)
            lrow = _ledger_row(ledger, question_id)
            entry = {"request_id": req_id, "topic": str(topic).strip(), "mode": mode, "at": S.now_iso()}
            if lrow is None:
                ledger["rows"].append(
                    {"question_id": question_id, "origin": qrow.get("origin", ""), "requests": [entry]}
                )
            else:
                lrow.setdefault("requests", []).append(entry)
            _write_ledger(store, ledger)

        return ok(
            {
                "request_id": req_id,
                "question_id": question_id,
                "duplicated": False,
                "topic": str(topic).strip(),
                "mode": mode,
                "waiting_request_ids": waiting,
                # 判重支才有的两个键，这里如实给"没有"（`G-23`：两条分支同一套 8 键）。
                # `reason` 是"为什么跳过"的理由，本支没跳过；`open_requests` 是拦下
                # 提交的那批未完成请求，本支一条都没有（否则根本走不到这里）。
                "reason": None,
                "open_requests": [],
            }
        )
    except Exception as e:  # 事务提交失败（例如 schema 校验拦下）=> 结构化失败
        return fail(f"提交查询请求失败：{type(e).__name__}: {e}", kind="submit_failed")


@tool(
    "research.write_note",
    "向某研究问题追加一条研究笔记（追加而非覆盖，保留研究过程）。",
    {
        "type": "object",
        "properties": {
            "question_id": {"type": "string", "minLength": 4, "maxLength": S.ID_DIGITS},
            "note": {"type": "string", "minLength": 1},
        },
        "required": ["question_id", "note"],
        "additionalProperties": False,
    },
    side_effect="write_local",
    roles=("D",),
    # 键名从一个真实调用读出（`research_write_note`）。
    returns="{'question_id','notes_length','appended'}",
    tags=("research", "note"),
)
def research_write_note(store: Any, question_id: str, note: str) -> ToolResult:
    """追加研究笔记。

    为什么"追加"而不是"覆盖"：D 的每一条笔记都是某一轮基于当时证据的判断。
    覆盖掉它，事后就无法解释"为什么第 2 轮说证据不足、第 4 轮又说够了"。
    审计价值正是在这个时间序列里。
    """
    if not S.is_valid_id(question_id):
        return fail(f"question_id 必须是 {S.ID_DIGITS} 位十进制字符串（旧数据里的 4 位号仍可读），收到 {question_id!r}", kind="bad_id")
    text = str(note).strip()
    if not text:
        return fail('note 不能为空（空笔记会污染研究记录，无法区分"想过但没写"与"没想过"）', kind="bad_note")
    try:
        with store.tx("research_questions", actor="agent-D", note="research.write_note") as tx:
            qrow = tx.find("research_questions", question_id=question_id)
            if qrow is None:
                return fail(f"研究问题 {question_id} 不存在", kind="not_found")
            old = qrow.get("notes") or ""
            stamp = S.now_iso()
            block = f"[{stamp}] {text}"
            qrow["notes"] = (old + ("\n" if old and not old.endswith("\n") else "") + block)[:20000]
            qrow["updated_at"] = stamp
            S.row_from_dict("research_questions", qrow).validate()
            tx.upsert("research_questions", qrow, note="note_appended")
        return ok({"question_id": question_id, "notes_length": len(qrow["notes"]), "appended": len(text)})
    except Exception as e:
        return fail(f"写笔记失败：{type(e).__name__}: {e}", kind="note_failed")


@tool(
    "research.poll_waiting",
    "复查等待中的查询请求：每条请求是否结束？其 result_lit_ids 是否都已被 B 消化？返回就绪/未就绪分组。",
    {"type": "object", "properties": {}, "additionalProperties": False},
    side_effect="read",
    roles=("D",),
    # 键名从一个真实调用读出（`research_poll_waiting`）：counts 是
    # {'ready','waiting','total'} 一类的分档计数。
    returns="{'ready','waiting','counts'}；纯确定性判断，不调用 LLM、不写盘",
    tags=("research", "poll"),
)
def research_poll_waiting(store: Any) -> ToolResult:
    """检查等待中的请求。

    ## 为什么"继续"必须靠等待集（§4.2）

    没有 ``waiting_request_ids``，D 就只能看到"库里多了几篇文献"，无法判断
    新来的文献是不是我在等的那批。这一条是 D 的循环能自动接上的唯一依据，
    所以这里的判断必须全部来自落盘的数据，而不是"感觉应该有新东西了"：

    - 请求是否结束 ⇒ ``search_requests.done`` / ``outcome``（复用 A 的终局字段）；
    - 新文献是否消化完 ⇒ ``literature.processed``（B 的语义："B 处理完了"）；
    - 两者都成立 ⇒ 该问题就绪，可以由调用方拉回 ``researching``。

    全是确定性判断，不需要 LLM，因此本工具是 ``read`` 副作用：
    它可以被任意多次调用而不触发审批，也不改变任何状态（状态迁移留给 agent_d，
    这样"这一轮谁改了什么"才可审计）。
    """
    try:
        qrows = _questions(store)
        req_index = {str(r.get("request_id")): r for r in store.rows("search_requests")}
        lit_index = {str(r.get("lit_id")): r for r in store.rows("literature")}
    except Exception as e:
        return fail(f"读取台账失败：{type(e).__name__}: {e}", kind="store_error")

    ready: list[dict] = []
    waiting: list[dict] = []
    for q in qrows:
        rids = _sorted_unique(q.get("waiting_request_ids"))
        if not rids:
            continue
        details: list[dict] = []
        all_finished = True
        all_digested = True
        new_lit: list[str] = []
        for rid in rids:
            req = req_index.get(rid)
            if req is None:
                all_finished = all_digested = False
                details.append({"request_id": rid, "state": "missing", "note": "请求行不存在，无法判断"})
                continue
            outcome = req.get("outcome")
            finished = bool(req.get("done")) or outcome in _TERMINAL_OUTCOMES
            lits = [str(x) for x in (req.get("result_lit_ids") or [])]
            unprocessed = [lid for lid in lits if not (lit_index.get(lid) or {}).get("processed")]
            if not finished:
                all_finished = False
            if unprocessed:
                all_digested = False
            details.append(
                {
                    "request_id": rid,
                    "done": bool(req.get("done")),
                    "outcome": outcome,
                    "result_lit_ids": lits,
                    "unprocessed_lit_ids": unprocessed,
                    "state": "waiting" if not finished else ("waiting_b" if unprocessed else "ready"),
                }
            )
            new_lit.extend(lits)

        item = {
            "question_id": q.get("question_id"),
            "question": (q.get("question") or "")[:160],
            "status": q.get("status"),
            "priority": q.get("priority"),
            "waiting_request_ids": rids,
            "details": details,
            "new_lit_ids": _sorted_unique(new_lit),
        }
        if all_finished and all_digested:
            item["reason"] = "全部请求已结束且结果文献已被 B 消化，可以拉回 researching"
            ready.append(item)
        else:
            if not all_finished:
                item["reason"] = "仍有查询请求未结束（A 还没跑完 / 还没跑到）"
            else:
                item["reason"] = "请求已结束，但结果文献还没被 B 消化完（processed=false）"
            waiting.append(item)

    return ok(
        {
            "ready": ready,
            "waiting": waiting,
            "counts": {"ready": len(ready), "waiting": len(waiting), "questions_with_waiting": len(ready) + len(waiting)},
        }
    )


#: 合法状态迁移（§4.1 的状态机）。迁移表本身就是文档：
#: 想知道"D 能不能从 answered 回到 open"，读这里就够了，不用读实现。
LEGAL_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "open": ("needs_evidence", "researching", "dropped"),
    "needs_evidence": ("researching", "dropped"),
    "researching": ("needs_evidence", "answered", "dropped"),
    "answered": (),  # 终态
    "dropped": (),  # 终态（且必须写明理由，见 schema 校验）
}


@tool(
    "research.set_status",
    "改研究问题的状态（按 schema 状态机校验，非法迁移与非法状态一律 fail）。",
    {
        "type": "object",
        "properties": {
            "question_id": {"type": "string", "minLength": 4, "maxLength": S.ID_DIGITS},
            "status": {"type": "string", "enum": list(S.QUESTION_STATUSES)},
            "notes": {"type": "string"},
        },
        "required": ["question_id", "status"],
        "additionalProperties": False,
    },
    side_effect="write_local",
    roles=("D",),
    # 键名从一个真实调用读出（`research_set_status`）：状态迁移前后各记一个，
    # 这样"从哪来、到哪去"在返回里就自证，不必回读表。
    returns="{'question_id','from','to','waiting_request_ids'}",
    tags=("research", "status"),
)
def research_set_status(store: Any, question_id: str, status: str, notes: str | None = None) -> ToolResult:
    """改状态。

    为什么非法迁移要 fail 而不是静默接受：状态机是 D 的循环的骨架。
    如果 ``answered → open`` 被放行，"已给出结论"这件事就不再是终局，
    报告与台账之间会永久性地互相矛盾，而没有任何一处会报错。
    宁可让调用方拿到一个明确的失败并自己决定，也不要把矛盾写进盘。

    为什么要以 schema 为准：``status`` 的词表、``needs_evidence`` 必须有
    等待集、``dropped`` 必须写 notes —— 这些不变量已经在
    :class:`agentflow.schema.ResearchQuestion` 里实现过一次。这里先走本模块的
    状态机（给出"哪一步不允许"这种可读信息），再让 schema 做终审，
    两道关卡的判定权都只有一份，不会出现第二个版本。
    """
    if not S.is_valid_id(question_id):
        return fail(f"question_id 必须是 {S.ID_DIGITS} 位十进制字符串（旧数据里的 4 位号仍可读），收到 {question_id!r}", kind="bad_id")
    if status not in S.QUESTION_STATUSES:
        return fail(f"status 必须是 {S.QUESTION_STATUSES} 之一，收到 {status!r}", kind="bad_status")
    try:
        with store.tx("research_questions", actor="agent-D", note="research.set_status") as tx:
            qrow = tx.find("research_questions", question_id=question_id)
            if qrow is None:
                return fail(f"研究问题 {question_id} 不存在", kind="not_found")
            frm = qrow.get("status") or "open"
            if status != frm and status not in LEGAL_TRANSITIONS.get(frm, ()):
                return fail(
                    f"非法状态迁移：{frm} -> {status}。允许的目标状态：{LEGAL_TRANSITIONS.get(frm, ())}。"
                    "（状态机是 D 的循环骨架，静默接受会让报告与台账永久矛盾）",
                    kind="illegal_transition",
                )
            qrow["status"] = status
            if notes is not None:
                old = qrow.get("notes") or ""
                qrow["notes"] = (old + ("\n" if old and not old.endswith("\n") else "") + str(notes))[:20000]
            qrow["updated_at"] = S.now_iso()
            # schema 终审：needs_evidence 无等待集、dropped 无 notes、数组未排序都在这里炸
            S.row_from_dict("research_questions", qrow).validate()
            tx.upsert("research_questions", qrow, note=f"status:{frm}->{status}")
        return ok(
            {
                "question_id": question_id,
                "from": frm,
                "to": status,
                "waiting_request_ids": _sorted_unique(qrow.get("waiting_request_ids")),
            }
        )
    except Exception as e:
        return fail(f"改状态失败：{type(e).__name__}: {e}", kind="status_failed")


# ---------------------------------------------------------------- 注册


#: 本模块对外暴露的全部工具函数（顺序即注册顺序）。
#:
#: 这里的元素是被 ``@tool`` 标记的普通函数，不是 ``ToolSpec``：它们的
#: handler 不能带 store（见 :func:`install` 的说明），因此不能直接当
#: ``tools/__init__.py`` 里"第三种约定"（模块级 ``ALL_TOOLS: list[ToolSpec]``）用。
#: 装配请走 :func:`register` / :func:`install`。
ALL_TOOLS = (
    research_list_gaps,
    research_submit_gap,
    research_write_note,
    research_poll_waiting,
    research_set_status,
)


def register(registry: Any, *, store: Any = None) -> list[str]:
    """标准入口：``register(registry, store=...)``。没有 store 时明确报错。

    为什么要有这个薄包装：``tools/__init__.py`` 的装配器（他人负责）按
    "``register(registry, **deps)`` / ``install(...)`` / 模块级 ``ALL_TOOLS``"
    三种约定之一来装工具，而且优先找 ``register``。本模块的功能全都需要
    store（查表、建请求行），所以缺 store 时不能"装上一堆一调就炸的工具"，
    而要在装配阶段就明确报出来。
    """
    if store is None:
        raise ValueError(
            "research_tools.register() 需要 store（本模块的工具都要读写 research_questions / "
            "search_requests）；装配时请传 store=<Store 实例>。"
        )
    return install(registry, store)


def install(registry: Any, store: Any) -> list[str]:
    """把本模块的工具注册进 ``registry``，并把 store 绑进去。

    为什么要绑 store：工具签名是 ``handler(**params)``（见 ``ToolRegistry.call``），
    参数由 LLM/调用方给出，不该让它们传一个 store 对象。而 ``@tool`` 装饰器
    只接受函数本身，没有"注入依赖"的位置，所以这里用 ``functools.partial``
    在注册时把 store 绑死 —— 与 ``ToolSpec.handler`` 是"任意可调用对象"的
    设计一致，不需要改动 base.py。

    返回注册成功的工具名，便于调用方断言"工具层到底有没有装好"。
    """
    from functools import partial

    names: list[str] = []
    for fn in ALL_TOOLS:
        spec = getattr(fn, "__tool_spec__", None)
        if spec is None:  # pragma: no cover - 只有忘了 @tool 才会发生
            raise RuntimeError(f"{fn.__name__} 缺少 @tool 标记")
        bound = partial(fn, store)
        # 已注册同名工具（例如调用方自己注册过一份）时跳过而不是炸，
        # 因为"重复注册"在这里是幂等诉求，不是错误。
        if spec.name in getattr(registry, "_specs", {}):
            continue
        registry.register(
            type(spec)(
                name=spec.name,
                summary=spec.summary,
                params=spec.params,
                handler=bound,
                side_effect=spec.side_effect,
                roles=spec.roles,
                returns=spec.returns,
                tags=spec.tags,
            )
        )
        names.append(spec.name)
    return names


def iter_questions(store: Any) -> Iterator[dict]:
    """按稳定顺序迭代全部研究问题。

    稳定顺序（priority, question_id）是刻意的：D 的每一轮都按同一顺序处理，
    报告与台账对得上；否则同一份数据两次跑会得到两篇不同的报告，
    "可审计"就无从谈起。
    """
    rows = list(store.rows("research_questions"))
    prio_rank = {p: i for i, p in enumerate(S.PRIORITIES)}
    rows.sort(key=lambda r: (prio_rank.get(r.get("priority"), 9), str(r.get("question_id") or "")))
    yield from rows


# ---------------------------------------------------------------- 自检

if __name__ == "__main__":  # pragma: no cover - 手工运行的自检块
    # 运行方式：在 src/ 下执行 `python -m agentflow.tools.research_tools`（或设 PYTHONPATH=src 后在任意目录执行）
    import sys
    import tempfile

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: R001 - 自检块：控制台重配失败（老终端不支持 UTF-8）不影响自检结论
        pass

    from ..store import Store
    from .base import ToolRegistry

    print("=" * 72)
    tmp = Path(tempfile.mkdtemp(prefix="agentflow-research-"))
    st = Store(tmp)
    st.init()
    print(f"[0] 临时 store：{tmp}")

    reg = ToolRegistry(name="d-tools")
    # 绑定角色（`P-14`）：`research.*` 的声明角色只有 D。
    reg.bound_role = "D"
    installed = install(reg, st)
    print(f"[1] 注册工具：{installed}")
    assert set(installed) == {
        "research.list_gaps",
        "research.submit_gap",
        "research.write_note",
        "research.poll_waiting",
        "research.set_status",
    }

    # 造一个问题行（正常由 agent_d.ingest 建）
    with st.tx("research_questions", actor="agent-D", note="seed") as tx:
        qid = tx.alloc_id("question")
        tx.upsert(
            "research_questions",
            S.ResearchQuestion(
                question_id=qid,
                question="阿贝尔群与域之间的交换性条件是否可推广到非交换环？",
                origin="C:paths:0000->0003",
                related_concept_ids=["0000", "0003"],
                related_relation_ids=["0000"],
                priority="high",
                created_at=S.now_iso(),
                updated_at=S.now_iso(),
            ).to_dict(),
            note="seed",
        )
    print(f"[2] 建问题 {qid}")

    r = reg.call("research.submit_gap", question_id=qid, topic="非交换环 交换性", mode="topical", description="关键词命中为 0")
    print(f"[3] submit_gap(1)：ok={r.ok} data={r.data}")
    r2 = reg.call("research.submit_gap", question_id=qid, topic="非交换环 交换性", mode="topical", description="再来一次")
    print(f"[4] submit_gap(2) 查重：duplicated={r2.data.get('duplicated')} 理由={r2.data.get('reason')}")
    assert r2.data["duplicated"] is True, "查重失败：重复提交了请求"
    assert len(st.rows("search_requests")) == 1, "查重失败：请求表里出现了两条"

    p = reg.call("research.poll_waiting")
    print(f"[5] poll（A 还没跑）：ready={p.data['counts']['ready']} waiting={p.data['counts']['waiting']} 理由={p.data['waiting'][0]['reason']}")

    # 模拟 A 跑完 + B 消化
    rid = r.data["request_id"]
    with st.tx("search_requests", "literature", actor="fake-A", note="simulate") as tx:
        req = tx.find("search_requests", request_id=rid)
        req["done"] = True
        req["outcome"] = "ok"
        req["result_lit_ids"] = ["0000"]
        tx.upsert("search_requests", req, note="simulated_A")
        tx.upsert(
            "literature",
            S.Literature(lit_id="0000", title="非交换环上的交换性", type="J", summary="x", path=None,
                         processed=False, added_at=S.now_iso()).to_dict(),
            note="seed",
        )
    p2 = reg.call("research.poll_waiting")
    print(f"[6] poll（A 完成、B 未消化）：ready={p2.data['counts']['ready']} 未就绪理由={p2.data['waiting'][0]['reason']}")
    with st.tx("literature", actor="fake-B", note="simulate") as tx:
        lit = tx.find("literature", lit_id="0000")
        lit["processed"] = True
        tx.upsert("literature", lit, note="simulated_B")
    p3 = reg.call("research.poll_waiting")
    print(f"[7] poll（A+B 都完成）：ready={p3.data['counts']['ready']} 理由={p3.data['ready'][0]['reason']}")

    print("[8] 状态机：needs_evidence -> researching（合法）")
    s1 = reg.call("research.set_status", question_id=qid, status="researching")
    print(f"    ok={s1.ok} {s1.data or s1.error}")
    print("[9] 状态机：researching -> needs_evidence（合法，回到提问）")
    s2 = reg.call("research.set_status", question_id=qid, status="needs_evidence")
    print(f"    ok={s2.ok}")
    print("[10] 状态机：needs_evidence -> answered（非法，应 fail）")
    s3 = reg.call("research.set_status", question_id=qid, status="answered")
    print(f"    ok={s3.ok} error={s3.error}")
    assert s3.ok is False
    print("[11] 状态机：researching -> dropped 但不写 notes（schema 应拦下）")
    reg.call("research.set_status", question_id=qid, status="researching")
    s4 = reg.call("research.set_status", question_id=qid, status="dropped")
    print(f"    ok={s4.ok} error={s4.error}")
    assert s4.ok is False and "notes" in (s4.error or "")
    s5 = reg.call("research.set_status", question_id=qid, status="dropped", notes="证据互相矛盾且无法判定")
    print(f"[12] 带 notes 再 dropped：ok={s5.ok}")

    n1 = reg.call("research.write_note", question_id=qid, note="第 1 轮：只找到 1 条 quote_verified=None 的关系")
    print(f"[13] write_note：ok={n1.ok} 长度={n1.data['notes_length']}")
    bad = reg.call("research.write_note", question_id=qid, note="")
    print(f"[14] 空笔记应 fail：ok={bad.ok} error={bad.error}")
    print(f"[15] list_gaps：{reg.call('research.list_gaps').data['count']} 条；按非法 status 查："
          f"{reg.call('research.list_gaps', status='nope').error}")

    print(f"[16] 台账文件：{(Path(st.data) / LEDGER_FILE).name} 存在="
          f"{(Path(st.data) / LEDGER_FILE).exists()}")
    print("=" * 72)
    print("SELF-CHECK DONE（research_tools）")

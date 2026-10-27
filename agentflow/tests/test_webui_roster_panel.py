# -*- coding: utf-8 -*-
"""名册面板的判据（业主 2026-10-21：「名册（roster）机制」必须在用户端看得见）。

## 这一份守什么

名册的真身在盘上（`out/roster/<父编号>.jsonl`：一个父一份，行里是子；`data/tasks.json`
给状态与板项）。用户端此前一个字都看不到它 —— 「在飞」页只有角色名，没有绝对编号、
没有父、没有子。这一批把 `GET /api/roster` 与「在飞」页里的名册面板接上，本文件守
四件事，每件都对着一种"页面看起来没事、其实名册没接上"的形态：

| 判据 | 它守的是 | 失败时的样子 |
|---|---|---|
| ① `test_the_endpoint_returns_the_whole_tree_*` | 有真名册的工作区：父/子/绝对编号/深度/收件箱齐，且互相自洽 | 树少一层、编号不是绝对的、收件箱读成 0 |
| ② `test_a_workspace_without_a_roster_answers_unknown_*` | 没名册 ≠ 空树（负控：`answer="unknown"` 且 `count is None`） | 端点回 `{"nodes": []}` 冒充"没有子代理" |
| ③ `test_the_endpoint_refuses_post_*` | 写面为零（路由表里没有配对的 POST，HTTP 也不接受） | 只读面板配了一条能写的端点 |
| ④ `test_the_frontend_really_reads_the_roster_endpoint` | 前端源码真的引用了这条端点（防"后端做了前端没接"） | 端点绿着、页面上一个字都没有 |

## 为什么②必须写成"负控"

"没有名册"与"名册上一个人都没有"在读数上必须分得开 —— 这是本仓库最贵的一条纪律
（`readers` 的三态词表就是为它存在的）。所以②不只断言 `answer == "unknown"`，还断言
`count is None`（不是 0）、`nodes == []` 但同时有一条非空 `reason`，并且断言
"若把 `answer` 改回 `ok` 这条判据必须红"（`_empty_workspace_problems` 的负控）。

## 为什么走真 HTTP

③（不接受 POST）在函数层根本看不到：那是路由表 + `do_POST` 的行为。所以四条里前三条
都打真服务（`W.serve(port=0)`），与 `tests/test_webui_pages.py` 同一条口径。
"""

from __future__ import annotations

import http.client
import json
import pathlib
import threading
from contextlib import contextmanager
from typing import Any, Iterator, Mapping

from agentflow.secretary import Secretary
from agentflow.store import Store
from agentflow.webui import readers as R
from agentflow.webui import routes, writes

#: 交付包根（`agentflow/`）。
REPO = pathlib.Path(__file__).resolve().parents[1]
UI_SRC = REPO / "ui" / "src"
API_TS = UI_SRC / "api.ts"
ROSTER_TSX = UI_SRC / "components" / "Roster.tsx"
LIVE_TSX = UI_SRC / "pages" / "Live.tsx"

#: 这一条端点的路径（后端路由表与前端 `api.ts` 必须逐字相同）。
ROSTER_PATH = "/api/roster"


# ====================================================================== 夹具
#: 夹具里的时间戳（`schema.Task` 的"每个 start 有且仅有一个 end"要求它对得上）。
_AT = "2026-10-21T00:00:00+08:00"


def _row(task_id: str, *, role: str, parent: str | None, depth: int,
         status: str) -> dict[str, Any]:
    """一条实例行（`kind == ""`：一个 agent 一行，与 `schema.Task` 同形）。

    `started_at` / `ended_at` 按 `schema.Task.validate` 的两条硬规矩给：在飞
    （`pending`/`running`）必有 `started_at` 且 `ended_at` 为空；终态必有 `ended_at`。
    """
    ended = None if status in ("pending", "running") else _AT
    outcome = None if status in ("pending", "running") else "ok"
    detail = "夹具：这一行是名册面板判据用的台账行"
    return {"task_id": task_id, "role": role, "action": "", "called_by": "parent",
            "parent_task_id": parent, "depth": depth, "input_key": f"k@{task_id}",
            "status": status, "outcome": outcome, "refusal_reason": None, "instance": "",
            "detail": detail, "error": None, "started_at": _AT, "ended_at": ended,
            "tokens": 0, "usd": 0.0, "artifacts": [], "inputs": [],
            "kind": "", "expects": "", "item_state": "", "item_close": "",
            "seen_by": "", "seen_step": None, "keep_alive": False}


def _board_row(task_id: str, *, parent: str, kind: str, state: str,
               called_by: str, detail: str) -> dict[str, Any]:
    """一条板项行（`kind` 非空）：它的 `parent_task_id` 是收件人的编号。

    `expects="ack"` 是 `schema.Task` 对板项行的硬要求（"什么算做完"的口径）。
    """
    row = _row(task_id, role="D", parent=parent, depth=3, status="pending")
    row.update({"called_by": called_by, "kind": kind, "item_state": state,
                "expects": "ack", "detail": detail, "action": kind,
                "input_key": f"{kind}@{task_id}"})
    return row


def _roster_workspace(tmp: pathlib.Path) -> pathlib.Path:
    """造一份有真名册的最小工作区（`Secretary.roster_add` 是写侧的唯一实现）。

    为什么用真写侧而不是手写 JSONL：字段名与"哪一格是谁写的"（`brief_source`）都由
    `secretary.roster_add` 决定 —— 手抄一份就等于把盘上格式再定义一遍（两处迟早漂移）。
    """
    root = tmp / "ws"
    root.mkdir()
    Store(root).init()
    store = Store(root)
    sec = Secretary("M", root=root, store=store)
    # M（t-000001）派 D1（t-000002）；D1 再派 C1（t-000003）与 F1（t-000005）。
    assert sec.roster_add(owner="t-000001", role="D", task_id="t-000002",
                          brief="走完整链：C 关系分析 → F 攻小断言")["problem"] == ""
    assert sec.roster_add(owner="t-000002", role="C", task_id="t-000003",
                          brief="空台账上的结构缺口分析")["problem"] == ""
    assert sec.roster_add(owner="t-000002", role="F", task_id="t-000005",
                          brief="攻 P_n 独立集计数")["problem"] == ""
    with store.tx("tasks", actor="test", note="roster-panel fixture") as tx:
        tx.upsert("tasks", _row("t-000001", role="M", parent=None, depth=1,
                                status="done"), note="顶趟")
        tx.upsert("tasks", _row("t-000002", role="D", parent="t-000001", depth=2,
                                status="running"), note="在飞")
        tx.upsert("tasks", _row("t-000003", role="C", parent="t-000002", depth=3,
                                status="done"), note="已交差")
        tx.upsert("tasks", _row("t-000005", role="F", parent="t-000002", depth=3,
                                status="done"), note="已交差")
        # 一条还没消的消息挂给 D1（t-000002）⇒ 它的收件箱里 unread = 1。
        tx.upsert("tasks", _board_row("t-000004", parent="t-000002", kind="message",
                                      state="queued", called_by="C1",
                                      detail="手稿 000000：gaps 确定性结果"),
                  note="一条未消的消息")
    return root


def _bare_workspace(tmp: pathlib.Path) -> pathlib.Path:
    """一份"合法但空"的工作区：表都在盘上、`out/roster/` 一个文件都没有。"""
    root = tmp / "bare"
    root.mkdir()
    Store(root).init()
    return root


def _broken_roster_workspace(tmp: pathlib.Path) -> pathlib.Path:
    """把 `out/roster/` 里那份名册写坏一行（`item` 那一支是合法 JSON 之外的坏行）。"""
    root = _roster_workspace(tmp)
    path = root / "out" / "roster" / "t-000002.jsonl"
    with open(path, "a", encoding="utf-8", newline="\n") as fh:
        fh.write("{ 这一行不是 JSON\n")
    return root


# ====================================================================== 真服务
@contextmanager
def _server(root: pathlib.Path) -> Iterator[str]:
    """在临时端口上起一个真服务（判据走 HTTP，不走函数调用）。"""
    from agentflow import webui as W

    srv = W.serve(root, host="127.0.0.1", port=0, csrf_token="rostertoken0123456789")
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"{srv.server_address[0]}:{srv.server_address[1]}"
    finally:
        srv.shutdown()
        srv.server_close()
        thread.join(timeout=5.0)


def _request(base: str, method: str, path: str) -> tuple[int, dict[str, Any], str]:
    """一次请求：返回 `(状态码, 解出来的 JSON（不是 JSON 就是空 dict）, 正文)`。"""
    conn = http.client.HTTPConnection(base, timeout=20)
    try:
        conn.request(method, path, headers={"Accept": "application/json"})
        resp = conn.getresponse()
        raw = resp.read().decode("utf-8", errors="replace")
        try:
            body = json.loads(raw)
        except ValueError:
            body = {}
        return resp.status, (body if isinstance(body, dict) else {"_list": body}), raw
    finally:
        conn.close()


# ====================================================================== ① 树
def _tree_problems(payload: Mapping[str, Any]) -> list[str]:
    """树干那一份读数自洽吗（父/子/绝对编号/深度/收件箱）。

    逐条都是"这一格与那一格对不上"，而不是"这一格存在"：
    - 每个非根节点的 `parent_task_id` 必须真的有一个父节点，且父的 `children`
      里点着它（父子两处必须互指 —— 单向的父子是名册最容易出的那种错）；
    - `depth` 必须是父的 `depth + 1`、根是 1（深度不是装饰：它就是缩进）；
    - `task_id` 不许为空、不许重复（绝对编号是这一整套的主键）；
    - 收件箱那一格必须带三态（`computed` / `unreadable` / `not_applicable`），
      而 `computed` 时 `open` 必须是数字（读到了 0 条也是数字）。
    """
    problems: list[str] = []
    if payload.get("answer") != "ok":
        return [f"answer 不是 ok（{payload.get('answer')!r}）：{payload.get('reason')!r}"]
    nodes = payload.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        return ["nodes 是空数组（有真名册的工作区上，那说明这一层没读到东西）"]
    by_id: dict[str, dict[str, Any]] = {}
    for node in nodes:
        tid = str(node.get("task_id") or "")
        if not tid:
            problems.append("有一个节点没有 task_id（绝对编号是这一套的主键）")
            continue
        if tid in by_id:
            problems.append(f"{tid} 出现了两次")
        by_id[tid] = node
    for tid, node in by_id.items():
        pid = str(node.get("parent_task_id") or "")
        depth = node.get("depth")
        if not isinstance(depth, int):
            problems.append(f"{tid} 的 depth 不是整数：{depth!r}")
        if pid == "":
            if depth != 1:
                problems.append(f"根 {tid} 的 depth 应当是 1，读数是 {depth!r}")
            if not node.get("children"):
                problems.append(f"根 {tid} 一个子都没有（这份夹具的根应当是派活方）")
            continue
        parent = by_id.get(pid)
        if parent is None:
            problems.append(f"{tid} 的父 {pid} 不在 nodes 里（父那一层没读出来）")
            continue
        kids = [str(k.get("task_id") or "") for k in (parent.get("children") or [])]
        if tid not in kids:
            problems.append(f"{tid} 说自己父是 {pid}，而 {pid} 的 children 里没有它")
        if isinstance(depth, int) and isinstance(parent.get("depth"), int) \
                and depth != parent["depth"] + 1:
            problems.append(f"{tid} 的 depth {depth} 不等于父的 depth + 1"
                            f"（父是 {parent['depth']}）")
        kid_names = {str(k.get("task_id") or ""): str(k.get("name") or "")
                     for k in (parent.get("children") or [])}
        if not kid_names.get(tid):
            problems.append(f"{pid} 的 children 里 {tid} 没有名册名")
        inbox = node.get("inbox")
        if not isinstance(inbox, dict):
            problems.append(f"{tid} 没有 inbox 那一格")
            continue
        tri = str(inbox.get("tri") or "")
        if tri not in (R.TRI_COMPUTED, R.TRI_UNREADABLE, R.TRI_NOT_APPLICABLE):
            problems.append(f"{tid} 的 inbox.tri 不在三态词表里：{tri!r}")
        elif tri == R.TRI_COMPUTED and not isinstance(inbox.get("open_total"), int):
            problems.append(f"{tid} 的 inbox 读成了（computed）却没有数字 open："
                            f"{inbox.get('open')!r}")
    roots = [n for n in by_id.values() if str(n.get("parent_task_id") or "") == ""]
    if len(roots) != 1:
        problems.append(f"根的个数是 {len(roots)}（这份夹具只有一个根）")
    return problems


def test_the_endpoint_returns_the_whole_tree_with_parents_and_absolute_ids(
        tmp_path: pathlib.Path) -> None:
    """判据①：有真名册的工作区 ⇒ 整棵树（父/子/绝对编号/深度/收件箱）都读得出来。

    正控读的是端点（HTTP）：`GET /api/roster` 必须给出 4 个节点（M/D1/C1/F1）、
    两处父子互指、D1 的收件箱未读 1 条、D1 在飞而 C1 不在飞。负控读的是
    `_tree_problems` 的输入：把任何一格改坏都必须当场报出来。
    """
    root = _roster_workspace(tmp_path)
    with _server(root) as base:
        code, body, raw = _request(base, "GET", ROSTER_PATH)
    assert code == 200, (code, raw[:400])
    assert _tree_problems(body) == [], _tree_problems(body)

    nodes = {str(n["task_id"]): n for n in body["nodes"]}
    assert set(nodes) == {"t-000001", "t-000002", "t-000003", "t-000005"}, sorted(nodes)
    assert body["roots"] == ["t-000001"] and body["count"] == len(nodes), body["roots"]
    # 名册名就是 `secretary.roster_add` 给的那三个（D1 / C1 / F1）。
    # 根不在任何人的名册里 ⇒ 它的 role / name 由读侧补成主控（业主 2026-10-26
    # 「顶层能不能标 M 啊，unknown 很怪」）：这是读侧给顶层定的身份，不是名册分配的
    # 名字，所以 `roster_add` 改不了它（逐条判据在 `tests/test_the_root_is_named_m.py`）。
    assert nodes["t-000002"]["name"] == "D1", nodes["t-000002"]
    assert (nodes["t-000001"]["role"], nodes["t-000001"]["name"]) == ("M", "M"), \
        nodes["t-000001"]
    assert [str(k["task_id"]) for k in nodes["t-000002"]["children"]] == \
        ["t-000003", "t-000005"], nodes["t-000002"]["children"]
    # 深度是"这棵树里的距离"（根 = 1），角色与状态来自两张不同的盘上事实。
    assert (nodes["t-000001"]["depth"], nodes["t-000002"]["depth"],
            nodes["t-000003"]["depth"]) == (1, 2, 3)
    assert nodes["t-000002"]["role"] == "D" and nodes["t-000002"]["status"] == "running"
    assert nodes["t-000002"]["in_flight"] == 1, nodes["t-000002"]["in_flight"]
    assert nodes["t-000003"]["in_flight"] == 0, nodes["t-000003"]["in_flight"]
    # 收件箱：那一条 `queued` 的 message 挂在 D1 名下 ⇒ 未读 1 条，且明细给得出。
    # （D13 起这一格拆成 unread / seen_not_acked / open_total：`queued` 进 unread。）
    inbox = nodes["t-000002"]["inbox"]
    assert inbox["tri"] == R.TRI_COMPUTED and inbox["open_total"] == 1, inbox
    assert inbox["unread"] == 1 and inbox["seen_not_acked"] == 0, inbox
    assert inbox["by_kind"] == {"message": 1} and inbox["by_state"] == {"queued": 1}, inbox
    assert [i["task_id"] for i in inbox["items"]] == ["t-000004"], inbox["items"]
    assert nodes["t-000001"]["inbox"]["open_total"] == 0, "M 名下没有未消的板项（读到的是 0）"
    # 台账那一栏真读到了（不是"未读到"）。
    assert body["tasks_tri"] == R.TRI_COMPUTED, body["tasks_tri"]
    assert body["coverage"]["unrostered"] == 0, body["coverage"]


def test_the_tree_judgment_is_not_vacuous() -> None:
    """负控（①的判据本身）：把树改坏三处 ⇒ `_tree_problems` 必须逐条点名。

    没有这一条，`_tree_problems` 哪天正则/键名失配（比如后端把 `children` 改名了），
    判据会以"一条都没解析到"的形态静默变绿。
    """
    good = {"answer": "ok", "roots": ["t-1"], "count": 2, "nodes": [
        {"task_id": "t-1", "name": "", "role": "M", "depth": 1,
         "parent_task_id": "", "parent_name": "",
         "children": [{"task_id": "t-2", "name": "D1", "role": "D", "retired": False}],
         "retired": False, "retired_branch": "", "brief": "", "brief_source": "",
         "surface": "", "status": "done", "task_found": True, "in_flight": 0,
         "inbox": {"tri": "computed", "open_total": 0, "by_state": {}, "by_kind": {},
                   "items": [], "more": 0, "reason": ""}},
        {"task_id": "t-2", "name": "D1", "role": "D", "depth": 2,
         "parent_task_id": "t-1", "parent_name": "",
         "children": [], "retired": False, "retired_branch": "", "brief": "甲",
         "brief_source": "parent", "surface": "S01", "status": "done",
         "task_found": True, "in_flight": 0,
         "inbox": {"tri": "computed", "open_total": 0, "by_state": {}, "by_kind": {},
                   "items": [], "more": 0, "reason": ""}},
    ]}
    assert _tree_problems(good) == []

    dropped = json.loads(json.dumps(good))
    dropped["nodes"][0]["children"] = []
    assert _tree_problems(dropped), "父不认子，判据却一声不吭"

    wrong_depth = json.loads(json.dumps(good))
    wrong_depth["nodes"][1]["depth"] = 5
    assert any("depth" in p for p in _tree_problems(wrong_depth)), _tree_problems(wrong_depth)

    no_inbox = json.loads(json.dumps(good))
    no_inbox["nodes"][1]["inbox"] = {"tri": "computed", "open_total": None}
    assert any("inbox" in p for p in _tree_problems(no_inbox)), _tree_problems(no_inbox)


# ====================================================================== ② 没名册
def _empty_workspace_problems(payload: Mapping[str, Any]) -> list[str]:
    """②的判据本身：这一档必须明说没读到，不许拿空数组冒充"没有子代理"。

    四条一起看（少一条就能被"看起来对"的形状蒙过去）：
    `answer == "unknown"`、`count is None`（不是 0）、`nodes == []` 而 `reason` 非空、
    `tri` 说得清是哪一档（`not_applicable` = 还没写过 / `unreadable` = 没查成）。
    """
    problems: list[str] = []
    if payload.get("answer") != "unknown":
        problems.append(f"answer 应当是 unknown，读数是 {payload.get('answer')!r}"
                        " —— 空数组冒充了「没有子代理」")
    if payload.get("count") is not None:
        problems.append(f"count 应当是 null（读不到 ⇒ 不是 0），读数是 {payload.get('count')!r}")
    if payload.get("nodes") != []:
        problems.append(f"nodes 应当是空数组，读数是 {payload.get('nodes')!r}")
    if not str(payload.get("reason") or "").strip():
        problems.append("没有 reason ⇒ 读的人不知道是哪一档没读到")
    if payload.get("tri") not in (R.TRI_NOT_APPLICABLE, R.TRI_UNREADABLE):
        problems.append(f"tri 应当是 not_applicable / unreadable，读数是 {payload.get('tri')!r}")
    return problems


def test_a_workspace_without_a_roster_answers_unknown_not_an_empty_tree(
        tmp_path: pathlib.Path) -> None:
    """判据②（负控：这不是"空树"）：没有 `out/roster/` 的工作区 ⇒ `answer="unknown"`。

    两档一起钉：
    - 一个名册文件都没有（合法初态：这个工作区还没派过活）；
    - 名册文件在、但里面有一行坏掉（没查成）。
    两档都必须是 `unknown` + `count is None` + 非空 `reason`；把 `answer` 改回 `ok`
    的负控由 `_empty_workspace_problems` 自己那条断言证明会红。
    """
    bare = _bare_workspace(tmp_path)
    with _server(bare) as base:
        code, body, raw = _request(base, "GET", ROSTER_PATH)
    assert code == 200, (code, raw[:400])
    assert _empty_workspace_problems(body) == [], _empty_workspace_problems(body)
    assert body["answer"] == "unknown" and body["nodes"] == [] and body["count"] is None
    assert "roster" in body["dir"] or "roster" in body["reason"], body["dir"]

    # ②的负控：同一份读数若把 answer 改成 ok，判据必须红（不是"怎么写都绿"）。
    doctored = dict(body)
    doctored["answer"] = "ok"
    assert _empty_workspace_problems(doctored), "把 unknown 改成 ok，判据却一声不吭"
    doctored2 = dict(body)
    doctored2["count"] = 0
    assert _empty_workspace_problems(doctored2), "把 null 改成 0，判据却一声不吭"

    # 第二档：名册文件在、但有一行读不出来 ⇒ 仍然是 unknown（这一档 tri=unreadable）。
    broken = _broken_roster_workspace(tmp_path)
    got = R.roster_face(broken)
    assert got["answer"] == "unknown", got["reason"]
    assert got["tri"] == R.TRI_UNREADABLE, got["tri"]
    assert got["nodes"], "好行照常给（逐行诊断在 reason 里），不许整份折成空树"
    assert "t-000002.jsonl" in got["reason"], got["reason"]


# ====================================================================== ③ 写面为零
def test_the_endpoint_refuses_post_and_has_no_write_face(tmp_path: pathlib.Path) -> None:
    """判据③：`/api/roster` 是只读端点 —— 路由表里没有 POST，HTTP 上也不接受 POST。

    三层一起看（少一层就有一条能绕过的路）：
    1. 总路由表里这条路径只有一条 GET（`routes.match("POST", …) is None`）；
    2. 写面子表 `writes.ROUTES` 里没有任何 roster 相关的端点；
    3. 真打一次 `POST /api/roster` ⇒ 404 + JSON（不是 200、不是 500）。
    """
    got = [m for m, p, _h in routes.ROUTES if p == ROSTER_PATH]
    assert got == ["GET"], got
    assert routes.match("POST", ROSTER_PATH) is None, "它不该有 POST 这一面"
    assert routes.match("GET", ROSTER_PATH) is not None
    assert not [r for r in writes.ROUTES if "roster" in r[1]], writes.ROUTES

    ws = tmp_path / "post-probe"
    ws.mkdir()
    Store(ws).init()
    with _server(ws) as base:
        code, body, raw = _request(base, "POST", ROSTER_PATH)
    assert code == 404, (code, raw[:400])
    assert body.get("ok") is False, body
    assert "没有这个端点" in str(body.get("reason") or ""), body


# ====================================================================== ④ 前端接上
def _frontend_problems(api_text: str, panel_text: str, live_text: str) -> list[str]:
    """④的判据本身：前端源码真的引用了这条端点，而且面板是接进已有的运行态页的。

    为什么是文本级：这一条防的是"后端做了、前端没接"（那种状态下所有后端判据全绿，
    而用户界面上一个字都没有）。三处必须同时成立：
    - `api.ts`：端点字面量 + 取数函数名（端点只有一个出口）；
    - 面板：真的调 `api.getRoster(`，而且把 `answer` 那一档读出来（否则"没读到"与
      "没有子代理"在界面上会长成一个样子）；
    - 运行态页：`<RosterPanel` 真的被挂上（不是"写了一个没人用的组件"）。
    """
    problems: list[str] = []
    if f'"{ROSTER_PATH}"' not in api_text:
        problems.append(f"api.ts 里没有端点字面量 {ROSTER_PATH!r}（前端没声明这条端点）")
    if "getRoster" not in api_text:
        problems.append("api.ts 里没有 getRoster（取数函数没接）")
    if "api.getRoster(" not in panel_text:
        problems.append("名册面板没有调 api.getRoster(（声明了端点却没人用）")
    for token in ("answer", "nodes", "inbox", "depth", "parent_task_id", "children"):
        if token not in panel_text:
            problems.append(f"名册面板没有读 {token!r} 那一格")
    if "RosterPanel" not in live_text:
        problems.append("「在飞」页没有挂 RosterPanel（组件写了却没人用 = 孤立页面）")
    return problems


def test_the_frontend_really_reads_the_roster_endpoint() -> None:
    """判据④：前端源码真的引用了 `/api/roster`，而且面板接在「在飞」页里。

    正控读三个真文件；负控把三处分别改坏一次，证明这条判据不是"怎么写都绿"。
    """
    for path in (API_TS, ROSTER_TSX, LIVE_TSX):
        assert path.is_file(), f"{path.relative_to(REPO)} 不在盘上"
    api_text = API_TS.read_text(encoding="utf-8")
    panel_text = ROSTER_TSX.read_text(encoding="utf-8")
    live_text = LIVE_TSX.read_text(encoding="utf-8")
    assert _frontend_problems(api_text, panel_text, live_text) == [], (
        _frontend_problems(api_text, panel_text, live_text))

    # 负控三条：分别是"端点没声明"、"端点声明了没人用"、"面板没挂到页面上"。
    assert _frontend_problems(api_text.replace(ROSTER_PATH, "/api/none"), panel_text,
                              live_text), "端点没声明，判据却一声不吭"
    assert _frontend_problems(api_text, panel_text.replace("api.getRoster(", "api.getLive("),
                              live_text), "面板没调这条端点，判据却一声不吭"
    assert _frontend_problems(api_text, panel_text,
                              live_text.replace("RosterPanel", "Nothing")), (
        "面板没挂到页面上，判据却一声不吭")

    # 反真空：这条端点真的在总表里（④说的"端点"不是空气）。
    assert ROSTER_PATH in routes.api_paths(), routes.api_paths()
    assert routes.handler_for("handle_roster") is not None, "路由表登记的处理器不存在"


def test_the_panel_is_not_an_isolated_page() -> None:
    """判据④的第二半（业主第 3 条）：不许把它做成孤立页面。

    两条断言：
    - `main.tsx` 的客户端路由表没有因为这一批多出一条（多一条就要动 C4 契约表 ——
      而名册是运行态监控的一块，它应当在「在飞」页里）；
    - `pages/` 下没有多出 `Roster.tsx` 这样的第十页（组件在 `components/` 里）。
    """
    main_text = (UI_SRC / "main.tsx").read_text(encoding="utf-8")
    assert "/roster" not in main_text, "别把名册做成第十页（C4 表里没有这条路由）"
    assert not (UI_SRC / "pages" / "Roster.tsx").exists(), (
        "名册不该是 pages/ 下的第十页：它是「在飞」页里的一块面板")
    assert ROSTER_TSX.is_file(), "名册面板组件应当在 components/ 里"

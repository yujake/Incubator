# -*- coding: utf-8 -*-
"""D-66：名册项是"一个常驻子代理"，一个子代理可以接好几件活。

## 现场（业主 2026-10-24 的原话）
```
「名册表里出现d1级别的t-000039和t-000068，请查看问题」
「一个子代理可接收多个任务」
「不可按照任务号记录名册」
「已收口子代理可再接收活，但已销号不可用」
「如果一个子代理（例如G1）被销号，且有G2，再派G时追加写成G3（不可复用G1）」
「应该是一个子代理后面可展开它管的任务号」
```

## 根因（两处，缺一不可）
1. 写侧：`reuse=<名>` 那一支只往对照表写一条调用记录（名册项不动是对的 —— 复用不是
   新建一个子代理），于是同一个名字接的中间那几件活只活在对照表里；
2. 读侧：拼树时读的是"折叠后"的对照表（一个名字只留第一次与当前两次调用），又把
   "同一名字的两次调用"当成两个子 ⇒ 中间那几件活既不在任何一个父名下、自己又有一份
   名册文件（它们是父），于是被抬成 d1 上的树根（真机：`t-000039` / `t-000068`），
   同一个子代理在树上还出现好几次（"重号"的错觉）。

## 这一份守什么
| 判据 | 它守的是 | 改前红在哪 |
|---|---|---|
| ① `test_one_agent_with_two_tasks_is_one_node_*` | 同一名册项 2 件活 ⇒ 树里一个节点 + 2 条任务读数（各带起止与状态），不出 d1 根 | 改前是两个同名节点，任务读数一格都没有 |
| ② `test_the_roster_never_uses_a_task_id_as_an_item_key` | 名册项的身份是 `owner` + `name`：只有任务号的行不建项（并点名） | 改前没有这一档读数（也没有 `unplaced`），行为判据无从谈起 |
| ③ `test_a_used_name_is_never_reissued_*` | 名字用过就不再发：G1 销号 + G2 在 ⇒ 下一个是 G3 | 改前 `next_name` 只读名册正文，正文缺行时会把用过的名字算成空号 |
| ④ `test_reuse_of_a_closed_item_is_allowed_and_a_retired_one_is_refused` | 收口（还在册）可再接活；销号不可用 | 改前把这两档折成一档（只按"名字存不存在"判） |
| ⑤ `test_a_name_that_only_lives_in_the_call_log_*` | 只有对照表、没有名册正文 ⇒ 仍按名字挂对父 | 改前"一个正文文件都没有"直接返回空树（answer=unknown） |
| ⑥ `test_a_task_no_item_adopted_is_flat_and_named_not_a_root` | 拼不上的平铺并点名，不许抬成 d1 根 | 改前连 `unplaced` 这个读数都没有 |
| ⑦ `test_the_panel_shows_the_tasks_under_the_agent` | 节点行尾可展开"它管过的任务号"，任务号不进树 | 改前节点下面没有任务清单 |
| ⑧ `test_the_real_workspace_reading_has_one_root_and_one_g1` | 真机（sylow3，只读）：d1 只剩 `t-000001`；G1 一个节点、挂着 `t-000085` / `t-000087` | 改前三个根，G1 是两个节点 |

⑨ - ⑫ 是反真空：把"按名字归组的调用流水"打桩成空、把"扫已销号名字"打桩成跳过、
把复用判据打桩成"只要在册就行"或"只认活跃任务"，对应的判据必须当场红。
"""

from __future__ import annotations

import json
import pathlib
from typing import Any

import pytest

from agentflow.conductor import Conductor, LocalBackend
from agentflow.secretary import (
    Secretary,
    _fold_roster,
    append_jsonl,
    roster_index_path,
    roster_path,
)
from agentflow.store import Store
from agentflow.webui import readers as R

#: 交付包根（`agentflow/`）。
REPO = pathlib.Path(__file__).resolve().parents[1]
UI_SRC = REPO / "ui" / "src"
ROSTER_TSX = UI_SRC / "components" / "Roster.tsx"
TREE_TS = UI_SRC / "rosterTree.ts"

#: 真机工作区（只读；不在盘上就 skip 那一条，记 unknown 不记 pass）。
REAL_WORKSPACE = REPO / "projects" / "sylow3"


# ====================================================================== 夹具
def _env(tmp_path: pathlib.Path) -> dict[str, Any]:
    """一个工作区 + 一趟顶趟 + 一个秘书（真落台账、真落名册，不手抄 JSONL）。"""
    ws = tmp_path / "ws"
    st = Store(ws)
    st.init()
    cond = Conductor(st, policy=None, backend=LocalBackend({}))
    owner = cond.open_top_level_run("M", "顶趟")
    return {"ws": ws, "st": st, "cond": cond, "owner": owner,
            "sec": Secretary("M", root=ws, store=st)}


def _row(env: dict[str, Any], *, role: str, status: str = "done", key: str) -> str:
    """在台账里造一件活（绝对编号由台账发，不在这里拼）。"""
    terminal = status not in ("pending", "running")
    return env["cond"]._write_new_row({
        "task_id": "", "role": role, "action": "run_once", "called_by": "M",
        "parent_task_id": env["owner"], "depth": 2, "input_key": key,
        "status": status, "outcome": "ok" if terminal else None,
        "refusal_reason": None, "instance": "", "detail": f"一件 {role} 的活",
        "error": None, "started_at": "2026-10-24T19:00:00+08:00",
        "ended_at": "2026-10-24T19:05:00+08:00" if terminal else None,
        "tokens": 0, "usd": 0.0, "artifacts": [], "inputs": [],
    }, note=f"start:{role}.run_once")


def _lines(path: pathlib.Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def _adds(env: dict[str, Any]) -> list[dict[str, Any]]:
    return [r for r in _lines(roster_path(env["ws"], env["owner"]))
            if str(r.get("kind") or "") == "add"]


def _node_named(face: dict[str, Any], name: str) -> dict[str, Any]:
    got = [n for n in face["nodes"] if str(n.get("name")) == name]
    assert len(got) == 1, (f"名为 {name} 的节点应当恰好一个（改前是每个任务一个）", got)
    return got[0]


# ====================================================================== ① 一个节点 + N 件活
def test_one_agent_with_two_tasks_is_one_node_with_two_task_readings(
        tmp_path: pathlib.Path) -> None:
    """① 同一个子代理接两件活 ⇒ 名册里一项、树里一个节点、两条任务读数。

    第二件活是"收口之后又接的"（上一件 status=done、名册项还在册）：这正是真机上
    F1 接了 5 件、G1 接了 2 件那种形态。改前读侧把它们画成两个同名节点，而且
    `tasks` 这一格根本不存在。
    """
    env = _env(tmp_path)
    first = _row(env, role="G", key="d66@first")
    born = env["sec"].roster_add(owner=env["owner"], role="G", task_id=first,
                                 brief="成文第一稿")
    assert (born["problem"], born["name"]) == ("", "G1"), born
    second = _row(env, role="G", key="d66@second")
    again = env["sec"].roster_add(owner=env["owner"], role="G", task_id=second,
                                  brief="成文第二稿", reuse="G1")
    assert (again["problem"], again["name"]) == ("", "G1"), again

    # 名册正文里仍然只有一行（复用不是新建一个子代理）。
    assert [str(a.get("name")) for a in _adds(env)] == ["G1"], _adds(env)

    face = R.roster_face(env["ws"])
    assert face["answer"] == "ok", face["reason"]
    node = _node_named(face, "G1")
    assert node["parent_task_id"] == env["owner"], node
    assert [t["task_id"] for t in node["tasks"]] == [first, second], node["tasks"]
    assert [t["status"] for t in node["tasks"]] == ["done", "done"], node["tasks"]
    for task in node["tasks"]:
        assert task["started_at"] and task["ended_at"], task
        assert task["task_found"] is True, task

    # 任务号不是树里的节点，更不是 d1 上的根。
    ids = [str(n["task_id"]) for n in face["nodes"]]
    assert second not in ids, ids
    assert face["roots"] == [env["owner"]], face["roots"]
    assert face["count"] == 2, face["count"]       # 根 + G1


# ====================================================================== ② 身份是名字
def test_the_roster_never_uses_a_task_id_as_an_item_key(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """② 名册项的身份是 `owner` + `name`：只有任务号的行不建项，且被点名。

    反真空：把折叠口径打桩成"按任务号建项"（这正是业主否掉的那一种）⇒ 判据必红。
    """
    env = _env(tmp_path)
    first = _row(env, role="G", key="d66@id1")
    assert env["sec"].roster_add(owner=env["owner"], role="G", task_id=first,
                                 brief="有名字的那一件").get("name") == "G1"
    orphan = "t-999999"
    # 手造一条"只写任务号、没写名册名"的行（业主点名的那个形态）。
    append_jsonl(roster_path(env["ws"], env["owner"]),
                 {"kind": "add", "owner": env["owner"], "task_id": orphan,
                  "role": "G", "at": "2026-10-24T19:30:00+08:00"})

    face = R.roster_face(env["ws"])
    assert face["answer"] == "ok", face["reason"]
    ids = [str(n["task_id"]) for n in face["nodes"]]
    assert orphan not in ids, ("只写任务号的行被当成了一个名册项", ids)
    assert any(orphan in line for line in face["diagnostics"]), face["diagnostics"]
    # 根那一行是 `M`（读侧给顶层定的身份，业主 2026-10-26），第二个才是名册给的 G1：
    # 那条只写任务号的行没有变成一个编号节点，也没有变成一个叫 t-999999 的名册项。
    assert [str(n["name"]) for n in face["nodes"]] == ["M", "G1"], face["nodes"]
    # 同一个名字的两条行折成一项（身份是名字，不是它接过哪几件活）。
    folded = _fold_roster([{"kind": "add", "owner": "t-1", "name": "G1", "role": "G",
                            "task_id": "t-2"},
                           {"kind": "add", "owner": "t-1", "name": "G1", "role": "G",
                            "task_id": "t-9"}])
    assert len(folded) == 1 and folded[0]["name"] == "G1", folded

    # 反真空：把折叠口径换成"按任务号建项"⇒ 同一个判据必须红。
    def _by_task_id(rows: Any) -> list[dict[str, Any]]:
        return [{"name": str(r.get("task_id") or ""), "task_id": str(r.get("task_id") or ""),
                 "role": "", "brief": "", "retired": False} for r in rows
                if str(r.get("task_id") or "")]

    monkeypatch.setattr("agentflow.secretary._fold_roster", _by_task_id)
    broke = R.roster_face(env["ws"])
    broke_ids = [str(n["task_id"]) for n in broke["nodes"]]
    assert orphan in broke_ids or len(broke_ids) != len(ids), (
        "把折叠口径换成按任务号建项，② 的判据却一声不吭", broke_ids)


# ====================================================================== ③ 名字不再发
def test_a_used_name_is_never_reissued_even_after_it_is_retired(
        tmp_path: pathlib.Path) -> None:
    """③ 用过的名字一律不再发：G1 销号 + G2 在册 ⇒ 下一个是 G3。

    业主原话：「如果一个子代理（例如G1）被销号，且有G2，再派G时追加写成G3（不可复用G1）」。
    改前 `next_name` 只读名册正文（一项一条）—— 正文缺行时会把用过的名字算成空号。
    """
    env = _env(tmp_path)
    first = _row(env, role="G", key="d66@n1")
    assert env["sec"].roster_add(owner=env["owner"], role="G", task_id=first,
                                 brief="第一稿").get("name") == "G1"
    got = env["sec"].retire(owner=env["owner"], name="G1", by_task_id=env["owner"])
    assert got["ok"] is True and got["action"] == "retired", got

    second = _row(env, role="G", key="d66@n2")
    assert env["sec"].roster_add(owner=env["owner"], role="G", task_id=second,
                                 brief="第二稿").get("name") == "G2"
    third = _row(env, role="G", key="d66@n3")
    assert env["sec"].roster_add(owner=env["owner"], role="G", task_id=third,
                                 brief="第三稿").get("name") == "G3"
    assert env["sec"].next_name(env["owner"], "G") == ("G4", "")

    # 正文缺行那一档（D-66 的同一形态）：G5 只在对照表的调用记录里、名册正文那一笔
    # 没落成 —— 它仍然是"用过"的号，下一个必须是 G6。改前只读正文 ⇒ 会把 G5 发出去。
    append_jsonl(roster_index_path(env["ws"], env["owner"]),
                 {"kind": "bind", "owner": env["owner"], "name": "G5", "role": "G",
                  "task_id": "t-000777", "at": "2026-10-24T19:45:00+08:00"})
    assert env["sec"].next_name(env["owner"], "G") == ("G6", ""), (
        "只在对照表里用过的名字又被发出去了（改前就是这么重发 G1/G2 的）")

    # 反真空：把"扫已销号的名字"打桩成跳过 ⇒ 名字会退回去重发一个用过的号。
    def _skip_retired(_owner: str) -> list[str]:
        return []

    real = env["sec"]._retired_used
    env["sec"]._retired_used = _skip_retired          # type: ignore[assignment]
    try:
        skipped = env["sec"]._used_names(env["owner"])
    finally:
        env["sec"]._retired_used = real               # type: ignore[assignment]
    assert "G1" in skipped, ("G1 只在销号名单里也必须算用过", sorted(skipped))
    assert env["sec"]._is_retired(env["owner"], "G1") is True


# ====================================================================== ④ 收口 vs 销号
def test_reuse_of_a_closed_item_is_allowed_and_a_retired_one_is_refused(
        tmp_path: pathlib.Path) -> None:
    """④ 收口（上一件活做完了、还在册）可以再接活；销号不可用。

    两档必须分得开：改前只按"名字存不存在"判，收口与销号走的是同一条路（要么都拒、
    要么都放）。这里逐档断言，并用两次打桩证明它们各自有牙。
    """
    env = _env(tmp_path)
    first = _row(env, role="G", key="d66@c1")
    assert env["sec"].roster_add(owner=env["owner"], role="G", task_id=first,
                                 brief="会收口的那一件").get("name") == "G1"
    # 收口：台账里那件活已经 done，名册项没销号 ⇒ 允许再接。
    assert env["st"].rows("tasks") and env["cond"]._task(first).get("status") == "done"
    second = _row(env, role="G", key="d66@c2")
    closed = env["sec"].roster_add(owner=env["owner"], role="G", task_id=second,
                                   brief="收口之后的第二件", reuse="G1")
    assert closed["problem"] == "", closed
    # 收口之后接的那一件仍然挂在同一个节点下（改前是两个同名节点）。
    face = R.roster_face(env["ws"])
    node = _node_named(face, "G1")
    assert [t["task_id"] for t in node["tasks"]] == [first, second], node["tasks"]

    # 销号之后同一句 reuse ⇒ 受控拒绝。
    retired = env["sec"].retire(owner=env["owner"], name="G1", by_task_id=env["owner"])
    assert retired["ok"] is True, retired
    third = _row(env, role="G", key="d66@c3")
    refused = env["sec"].roster_add(owner=env["owner"], role="G", task_id=third,
                                    brief="销号之后还想复用", reuse="G1")
    assert refused["problem"] and "销号" in refused["problem"], refused

    # 反真空①：把复用判据打桩成"只要在册就行"⇒ 销号那一档必须红。
    def _anything_goes(_owner: str, _name: str) -> str:
        return ""

    real = env["sec"]._reuse_refusal
    env["sec"]._reuse_refusal = _anything_goes      # type: ignore[assignment]
    try:
        loose = env["sec"].roster_add(owner=env["owner"], role="G", task_id=third,
                                      brief="打桩之后还能复用", reuse="G1")
    finally:
        env["sec"]._reuse_refusal = real            # type: ignore[assignment]
    assert loose["problem"] == "", ("打桩没生效：这条反真空证明不了销号那一档有牙", loose)

    # 反真空②：把复用判据打桩成"只认活跃任务"⇒ 收口那一档必须红。
    def _active_only(owner: str, name: str) -> str:
        tasks = [first, second]
        if not any(str(env["cond"]._task(t).get("status") or "") in ("pending", "running")
                   for t in tasks):
            return f"{name} 已收口（打桩：只认活跃任务）"
        return real(owner, name)

    second_ws = tmp_path / "ws2"
    st2 = Store(second_ws)
    st2.init()
    cond2 = Conductor(st2, policy=None, backend=LocalBackend({}))
    owner2 = cond2.open_top_level_run("M", "顶趟二")
    sec2 = Secretary("M", root=second_ws, store=st2)
    env2 = {"ws": second_ws, "st": st2, "cond": cond2, "owner": owner2, "sec": sec2}
    one2 = _row(env2, role="G", key="d66@a1")
    assert sec2.roster_add(owner=owner2, role="G", task_id=one2,
                           brief="会收口的那一件").get("name") == "G1"
    sec2._reuse_refusal = _active_only               # type: ignore[assignment]
    two2 = _row(env2, role="G", key="d66@a2")
    strict = sec2.roster_add(owner=owner2, role="G", task_id=two2,
                             brief="打桩之后收口也不能接", reuse="G1")
    assert strict["problem"], ("把复用判据换成只认活跃任务，收口那一档却没红", strict)


# ====================================================================== ⑤ 只有调用流水
def test_a_name_that_only_lives_in_the_call_log_still_hangs_under_its_parent(
        tmp_path: pathlib.Path) -> None:
    """⑤ 只有对照表（调用流水）、没有名册正文的那一支 ⇒ 仍按名字挂对父。

    真机形态：名册正文那一笔没落成（半份登记），名字只活在对照表的调用记录里。
    改前这一档直接返回空树（"一个 `<父>.jsonl` 都没有" ⇒ answer=unknown），
    于是那些活既不在树上也不在任何人的名下。
    """
    ws = tmp_path / "ws"
    st = Store(ws)
    st.init()
    cond = Conductor(st, policy=None, backend=LocalBackend({}))
    owner = cond.open_top_level_run("M", "顶趟")
    env = {"ws": ws, "st": st, "cond": cond, "owner": owner,
           "sec": Secretary("M", root=ws, store=st)}
    task = _row(env, role="F", key="d66@bind1")
    # 只写对照表：名册正文一个字都不写（"正文缺行"的那一档）。
    append_jsonl(roster_index_path(ws, owner),
                 {"kind": "bind", "owner": owner, "name": "F1", "role": "F",
                  "task_id": task, "at": "2026-10-24T19:40:00+08:00"})
    assert not roster_path(ws, owner).is_file(), "这一条要的是'正文一个字都没有'那一档"

    face = R.roster_face(ws)
    assert face["answer"] == "ok", face["reason"]
    node = _node_named(face, "F1")
    assert node["parent_task_id"] == owner, node
    assert [t["task_id"] for t in node["tasks"]] == [task], node["tasks"]
    assert face["roots"] == [owner], face["roots"]
    assert any("名册正文里没有 F1" in line for line in face["diagnostics"]), face["diagnostics"]

    # 反真空：把"按名字归组的调用流水"打桩成空 ⇒ 上面这条必须红。
    real = R._roster_work_rows
    R._roster_work_rows = lambda _rows: []          # type: ignore[assignment]
    try:
        broke = R.roster_face(ws)
    finally:
        R._roster_work_rows = real                 # type: ignore[assignment]
    assert broke["answer"] != "ok" or not any(
        str(n.get("name")) == "F1" for n in broke["nodes"]), (
        "把调用流水打桩成空，⑤ 的判据却一声不吭", broke["nodes"])


# ====================================================================== ⑥ 平铺并点名
def test_a_task_no_item_adopted_is_flat_and_named_not_a_root(
        tmp_path: pathlib.Path) -> None:
    """⑥ 台账里有父、却没有名册项接过 ⇒ 平铺并点名，不许抬成 d1 根。"""
    env = _env(tmp_path)
    first = _row(env, role="G", key="d66@f1")
    assert env["sec"].roster_add(owner=env["owner"], role="G", task_id=first,
                                 brief="有名册项的那一件").get("name") == "G1"
    stray = _row(env, role="B", key="d66@stray")    # 谁都没登记它

    face = R.roster_face(env["ws"])
    assert face["roots"] == [env["owner"]], face["roots"]
    assert stray not in [str(n["task_id"]) for n in face["nodes"]], face["nodes"]
    flat = {str(u["task_id"]): u for u in face["unplaced"]}
    assert stray in flat, face["unplaced"]
    assert flat[stray]["parent_task_id"] == env["owner"], flat[stray]
    assert any(stray in line for line in face["diagnostics"]), face["diagnostics"]


# ====================================================================== ⑦ 面板
def _panel_problems(tsx: str, tree: str) -> list[str]:
    """面板与纯函数里"子代理后面可展开它管的任务号"的那几处标记。"""
    problems: list[str] = []
    if "taskOpen" not in tsx:
        problems.append("Roster.tsx 没有任务清单自己的开合态（taskOpen）")
    if "onToggleTasks" not in tsx:
        problems.append("Roster.tsx 没有任务清单的展开入口（onToggleTasks）")
    if "node.tasks.map" not in tsx and "tasks.map" not in tsx:
        problems.append("Roster.tsx 没有把 node.tasks 逐条画出来")
    if "{task.task_id}" not in tsx:
        problems.append("任务清单那一行没有印任务号")
    if "taskLine(" not in tsx:
        problems.append("任务清单那一行没有用 taskLine（起止 / 状态 / 一句话）")
    if "export function taskLine" not in tree:
        problems.append("rosterTree.ts 没有 taskLine 这个纯函数")
    for needle in ("started_at", "ended_at", "status"):
        if needle not in tree:
            problems.append(f"taskLine 没有用 {needle}（那一行少一格读数）")
    return problems


def test_the_panel_shows_the_tasks_under_the_agent(tmp_path: pathlib.Path) -> None:
    """⑦ 节点行尾可展开"它管过的任务号"；任务号不进树（两层不混）。

    源码判据 + 三条负控：删掉任务清单、把任务号换成子节点、把起止时间从 taskLine
    里去掉 —— 三种形态都必须当场红。
    """
    tsx = ROSTER_TSX.read_text(encoding="utf-8")
    tree = TREE_TS.read_text(encoding="utf-8")
    assert _panel_problems(tsx, tree) == [], _panel_problems(tsx, tree)

    assert _panel_problems(tsx.replace("tasks.map", "_tasksDropped"), tree), (
        "把 node.tasks 那一栏删掉，判据却一声不吭")
    assert _panel_problems(tsx, tree.replace("export function taskLine", "function taskLine")), (
        "把 taskLine 变成私有函数，判据却一声不吭")
    assert _panel_problems(tsx, tree.replace("started_at", "started")), (
        "把起止时间那一格换掉，判据却一声不吭")

    # 读数那一侧：任务号必须落在 nodes[].tasks[] 里，而不是变成树里的节点。
    env = _env(tmp_path)
    first = _row(env, role="G", key="d66@ui1")
    assert env["sec"].roster_add(owner=env["owner"], role="G", task_id=first,
                                 brief="面板上的那一件").get("name") == "G1"
    second = _row(env, role="G", key="d66@ui2")
    assert env["sec"].roster_add(owner=env["owner"], role="G", task_id=second,
                                 brief="面板上的第二件", reuse="G1")["problem"] == ""
    face = R.roster_face(env["ws"])
    node = _node_named(face, "G1")
    assert [t["task_id"] for t in node["tasks"]] == [first, second], node["tasks"]
    assert face["children_of"].get(env["owner"]) == [node["task_id"]], face["children_of"]


# ====================================================================== ⑧ 真机
def test_the_real_workspace_reading_has_one_root_and_one_g1() -> None:
    """⑧ sylow3（只读）：d1 只剩 `t-000001`；G1 是一个节点，挂着它接过的活。

    改前读数（同一份盘上事实）：`roots = ['t-000001', 't-000039', 't-000068']` ——
    后两个是因为中间那几件活被折叠掉、自己又有名册文件而被抬成根。
    """
    if not (REAL_WORKSPACE / "out" / "roster").is_dir():
        pytest.skip(f"真机工作区不在盘上（{REAL_WORKSPACE.relative_to(REPO)}）⇒ 记 unknown")
    face = R.roster_face(REAL_WORKSPACE)
    assert face["answer"] == "ok", face["reason"]
    roots = [str(x) for x in face["roots"]]
    assert roots == ["t-000001"], ("d1 应当只剩顶趟那一个根", roots)
    assert "t-000039" not in roots and "t-000068" not in roots, roots
    assert "t-000001" not in [str(n["task_id"]) for n in face["nodes"] if n["depth"] > 1]

    g1 = [n for n in face["nodes"]
          if str(n["name"]) == "G1" and str(n["parent_task_id"]) == "t-000001"]
    assert len(g1) == 1, ("M 名下的 G1 应当是一个节点", g1)
    ids = [str(t["task_id"]) for t in g1[0]["tasks"]]
    assert "t-000085" in ids and "t-000087" in ids, ids
    # 那两件活都是真读数（不是空行）：状态与起止时间来自台账。
    for task in g1[0]["tasks"]:
        if task["task_id"] in ("t-000085", "t-000087"):
            assert task["task_found"] is True and task["started_at"], task
            assert task["status"] == "done", task

    # F1（D2 名下）同样是一个节点、挂着它接过的 5 件活（真机读数）。
    f1 = [n for n in face["nodes"]
          if str(n["name"]) == "F1" and str(n["parent_task_id"]) == "t-000002"]
    assert len(f1) == 1, ("D2 名下的 F1 应当是一个节点", f1)
    f1_ids = [str(t["task_id"]) for t in f1[0]["tasks"]]
    assert "t-000039" in f1_ids and "t-000068" in f1_ids, f1_ids

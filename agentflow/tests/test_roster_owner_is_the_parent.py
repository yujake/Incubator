# -*- coding: utf-8 -*-
"""孤儿节点：`tasks.parent_task_id` 不许为 `None`（顶层那一行除外），名册 `owner` 必须等于它。真机证据（只读取证：`projects/tree-check/data/tasks.json`）：
```text t-000019 | role A | action run_once | called_by M | parent_task_id None | depth 1
| input_key consume:r-000001
```同一份台账里其它行都正常（`t-000002 D <- M t-000001`、`t-000003 C <- D t-000002`、`t-000004 D <- C t-000002` 那种"回信型"板项的父是收件人，也正常）。`t-000019` 是唯一一行 `parent_task_id=None` 的非顶层行 —— 它不在任何名册里（`projects/tree-check/out/roster/t-000001.jsonl` 只有 `D1`），也不占任何父的扇出。根因（文件:行）：`conductor.py:2453`（改前）：```python res = self.summon("A", "run_once", {}, by=by, input_key=key)``
``parent_task_id` 没传 ⇒ 走默认值 `None` ⇒ `_depth_of(None)` 给 `depth=1`。这条路是 `consume_pending_search_requests`（S-03
队列认领），它由`finish_top_level_run`（`conductor.py:2500`）与 `run_plan`（`conductor.py:3694`）各调一次 ——两处都没把"我是哪一趟"传下来。
于是框架自己发起的一次派活在台账上是树根形态的孤儿。第二条同类（批量那条）：`tools/conductor_tools.py:386-394` 的 `TaskCall` 也没带`parent_task_id` ⇒ 经
`conductor.summon_many` 工具派出去的整批子代理都是孤儿。第三处（单个派活）：`agent_loop._do_summon` /
`_do_summon_many` 原先写的是`parent_task_id=self.my_task_id or None` —— 号一空就把 `None` 落进台账。今天那两处改成"号空 ⇒
受控拒绝（`refused=no_owner`）"，宁可这一件派不出去，也不许造一行孤儿。修法（编号不自己拼）：父的号只用三个来源，按权威性取：
调用方显式给的（`finish_top_level_run` 给它自己那一行、`_do_summon_many` 给 `self.my_task_id`）→ 当前调用上下文（`calling_as` 挂的 `task_id`，
工具路径走这一格）→ 本进程顶趟（`open_top_level_run` 记下的 `_top_task_id`）。- 三者都没有（判据里裸造 `Conductor`、连顶趟都没开）⇒
当场开一条真树根（`_write_new_row`，号由台账发；`parent=None` 只在树根上合法）并把它收行。- 认领出来的那个子代理顺手登记进 `owner` 的名册 ——
名字与读写面都由秘书发号（`Secretary.roster_add` 内部的 `next_name` / `surface_alloc`），这里一个号都不拼。判据（红/绿成对）：

1. 真跑 `_do_summon` / `_do_summon_many`（桩后端）⇒ 每个子 `parent_task_id` 非空且等于父的绝对编号，名册 `owner` 与它一致；
队列认领那一路同样（`parent == 顶趟编号`）；2. 反真空：顶趟那一行 `parent=None` 仍然合法（它是树根），`_depth_of(None) == (1, "M")`；3. 负控：把 `owner` 改回
`""`（改前那一版的形态）⇒ ① 的判据必须红，并且要认出"名册落到隐藏文件 `out/roster/.jsonl`"这一形态。
"""
from __future__ import annotations

import json
import pathlib
from types import SimpleNamespace
from typing import Any

import pytest
from conftest import add_request

from agentflow import secretary as SEC
from agentflow import schema as S
from agentflow.agent_loop import AgentLoop
from agentflow.conductor import Conductor, LocalBackend
from agentflow.llmseam import LlmSeam
from agentflow.store import Store
from agentflow.tools import build_registry

SID = "s-owner"
#: 我是顶层主控（M 的出边覆盖 A–H ⇒ 派活这一层不吃边表）。
MY_ROLE = "M"
CHILD_ROLE = "E"


class _Gate:
    """seam 的替身：这一组判据只碰名册与台账，不碰模型。"""

    spec = type("Spec", (), {"model": "stub", "api_key": "x"})()

    def complete(self, prompt: str, *, scope: str = "", system: str | None = None,
                 **kw: Any) -> Any:
        return type("Reply", (), {"ok": True, "text": "{}", "tool_calls": (),
                                  "tokens_in": 1, "tokens_out": 1,
                                  "error_detail": "", "error_kind": ""})()


def _row(cond: Conductor, parent: str | None, role: str, *, key: str,
         status: str = "done", action: str = "run_once") -> str:
    """在台账里造一行（绝对编号是台账分配的，不是这里拼的）。"""
    prow = (cond._task(parent) or {}) if parent else {}
    terminal = status not in ("pending", "running")
    return cond._write_new_row({
        "task_id": "", "role": role, "action": action, "called_by": MY_ROLE,
        "parent_task_id": parent, "depth": int(prow.get("depth") or 0) + 1,
        "input_key": key, "status": status,
        "outcome": "ok" if terminal else None,
        "refusal_reason": None, "instance": "", "detail": f"一个 {role} 实例",
        "error": None, "started_at": "2026-10-19T10:00:00+08:00",
        "ended_at": "2026-10-19T10:05:00+08:00" if terminal else None,
        "tokens": 0, "usd": 0.0, "artifacts": [], "inputs": [],
    }, note=f"start:{role}.run_once")


class _FakeA:
    """A 的替身：只实现 `run_once`（队列认领的那个动作），返回"跑完了"。"""

    def __init__(self) -> None:
        self.calls = 0

    def run_once(self) -> dict:
        self.calls += 1
        return {"outcome": "ok", "detail": f"跑了一条（第 {self.calls} 次）", "checked": True,
                "payload": {"checked": True}}


def _env(tmp_path: pathlib.Path) -> dict[str, Any]:
    """一个工作区 + 一个主控顶趟 + 我这一趟（秘书自动装配，conductor 也挂同一个秘书）。"""
    ws = tmp_path / "ws"
    st = Store(ws)
    st.init()
    a = _FakeA()
    cond = Conductor(st, policy=None, backend=LocalBackend({"A": a}))
    reg = build_registry(store=st, conductor=cond).registry
    top = cond.open_top_level_run(MY_ROLE, "顶层这一趟")
    loop = AgentLoop(role=MY_ROLE, session_root=ws, registry=reg, conductor=cond,
                     seam=LlmSeam(role=MY_ROLE, session_root=ws, gateway=_Gate(),
                                  price=(0.0, 0.0), sid=SID),
                     store=st, sid=SID, max_steps=2)
    loop.my_task_id = top
    assert loop.secretary is not None, "这一组判据要的是'名册在手上'那一档"
    # `run_role` 的生产路径会这样把秘书挂到 conductor 上（`agent_loop.run_role` 那一段）。
    cond.secretary = loop.secretary
    return {"ws": ws, "st": st, "cond": cond, "reg": reg, "loop": loop,
            "sec": loop.secretary, "me": top, "a": a}


# ---------------------------------------------------------------- 判据（正控与负控共用）


def _hiding_roster_paths(root: pathlib.Path) -> list[pathlib.Path]:
    """名册落点里 `owner` 是空串的那一种：`out/roster/.jsonl`（隐藏文件形态）。"""
    d = pathlib.Path(root).joinpath(*SEC.ROSTER_DIR)
    if not d.is_dir():
        return []
    return sorted(p for p in d.glob("*.jsonl") if p.name.startswith("."))


def _roster_adds(root: pathlib.Path, owner: str) -> list[dict[str, Any]]:
    path = SEC.roster_path(root, owner)
    if not path.is_file():
        return []
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines()
            if ln.strip() and json.loads(ln).get("kind") == "add"]


def _owner_problems(root: pathlib.Path, st: Store, parent: str,
                    child_ids: list[str]) -> list[str]:
    """孤儿 / 名册 owner 不一致 / 名册落到隐藏文件 —— 这三类的全部问题（空 = 全对）。

    三个分量分开报，因为它们坏起来是三件事：子行没有父（孤儿）、名册挂在别的 owner
    名下（登记了但父看不见）、名册落到了 `owner=""` 的隐藏文件（父的名册里一条都没有）。
    """
    out: list[str] = []
    rows = {str(r.get("task_id") or ""): r for r in st.rows("tasks")}
    adds = _roster_adds(root, parent)
    by_tid = {str(a.get("task_id") or ""): a for a in adds}
    for cid in child_ids:
        row = rows.get(cid)
        if row is None:
            out.append(f"{cid} 在台账里找不到（夹具/派活没落行）")
            continue
        pid = str(row.get("parent_task_id") or "")
        if not pid:
            out.append(f"{cid} 的 parent_task_id 是空的 —— 孤儿（名册与扇出都读不到它）")
        elif pid != str(parent):
            out.append(f"{cid} 的父是 {pid}，不是 {parent} —— 父子链指错了人")
        item = by_tid.get(cid)
        if item is None:
            out.append(f"{cid} 不在 {parent} 的名册里 —— 名册外子代理")
        elif str(item.get("owner") or "") != str(parent):
            out.append(f"{cid} 的名册 owner 是 {item.get('owner')!r}，不是 {parent!r}")
    for p in _hiding_roster_paths(root):
        out.append(f"名册落到了隐藏文件 {p.name!r}（owner 是空串）—— 父的名册里一条都没有")
    return out


def _stub_summon(cond: Conductor, parent_box: dict[str, Any], *, n: dict[str, int]):
    """`Conductor.summon` 的替身：真的落台账行（号是真的），把收到的父记下来。"""
    def summon(role, action, params=None, *, by="M", parent_task_id=None, **kw):
        parent_box["parent"] = parent_task_id
        n["i"] += 1
        tid = _row(cond, parent_task_id, role, key=f"stub@{n['i']}")
        return SimpleNamespace(ok=True, task_id=tid, status="done", outcome="ok",
                              refusal_reason="", detail="跑完了", children=[],
                              payload={})
    return summon


# ---------------------------------------------------------------- ① 单个派活


def test_a_summoned_child_has_the_parents_absolute_id_and_the_roster_agrees(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    """判据①（单个）：子行的 `parent_task_id` 非空且 == 父的绝对编号，名册 `owner` 一致。"""
    env = _env(tmp_path)
    box: dict[str, Any] = {}
    monkeypatch.setattr(env["cond"], "summon", _stub_summon(env["cond"], box, n={"i": 0}))
    out = env["loop"]._do_summon({"role": CHILD_ROLE, "task": "干一件", "brief": "甲这件活"})
    assert out.get("ok") is True, out
    child = str(out.get("task_id") or "")
    assert child, out
    assert box["parent"] == env["me"], ("传给 summon 的父不是顶趟编号", box["parent"])
    assert _owner_problems(env["ws"], env["st"], env["me"], [child]) == [], \
        _owner_problems(env["ws"], env["st"], env["me"], [child])
    # 名册那一行带绝对编号（读盘，不读视图）
    adds = _roster_adds(env["ws"], env["me"])
    assert [str(a.get("task_id")) for a in adds] == [child], adds
    assert str(out.get("roster_name") or "") == "E1", out


# ---------------------------------------------------------------- ① 批量派活


def test_summon_many_gives_every_child_the_parents_absolute_id(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    """判据①（批量）：整批的每个 `TaskCall.parent_task_id` 都 == 父的绝对编号（改前是 `None`）。"""
    env = _env(tmp_path)
    seen: list[str] = []

    def run_plan(calls, token=None, parent_task_id=""):
        got = []
        for i, call in enumerate(calls):
            seen.append(str(call.parent_task_id))
            tid = _row(env["cond"], call.parent_task_id, call.role, key=f"sm@{i}")
            got.append(SimpleNamespace(task_id=tid, status="done", outcome="ok",
                                       refusal_reason="", detail="跑完了"))
        return got

    monkeypatch.setattr(env["cond"], "run_plan", run_plan)
    targets = [{"role": CHILD_ROLE, "task": f"干第 {i} 件", "brief": f"第 {i} 件活"}
               for i in (1, 2, 3)]
    out = env["loop"]._do_summon_many({"targets": targets})
    assert out.get("ok") is True, out
    ids = [str(r.get("task_id") or "") for r in out.get("results") or []]
    assert len(ids) == 3 and all(ids), out
    assert seen == [env["me"]] * 3, ("批量里每一件都该带父的绝对编号", seen)
    assert _owner_problems(env["ws"], env["st"], env["me"], ids) == [], \
        _owner_problems(env["ws"], env["st"], env["me"], ids)


# ---------------------------------------------------------------- ① 队列认领那条路（真机根因）


def test_the_consumed_claim_has_the_top_level_row_as_its_parent(tmp_path: pathlib.Path):
    """判据①（真机那条根因）：收尾扫队认领出来的 `A` ⇒ 父是顶趟编号，且进了顶趟的名册。

    这一条就是 `projects/tree-check` 的 `t-000019` 那一行的回归判据：
    改前它是 `role=A / called_by=M / parent_task_id=None / depth=1`，名册里没有它。
    """
    env = _env(tmp_path)
    add_request(env["st"], "r-0001", topic="收尾时该被认领")
    env["cond"].finish_top_level_run(env["me"], stop_reason="final", detail="收工")
    a_rows = [r for r in env["st"].rows("tasks") if str(r.get("role")) == "A"]
    assert len(a_rows) == 1, a_rows
    arow = a_rows[0]
    assert str(arow.get("input_key") or "") == "consume:r-0001", arow
    assert str(arow.get("parent_task_id") or "") == env["me"], (
        "认领出来的 A 没有父（孤儿形态，真机 t-000019）", arow)
    assert int(arow.get("depth") or 0) == 2, arow        # 顶趟(1) 的下一层
    # 名册：顶趟名下有人在，名字与面都由秘书发号
    adds = _roster_adds(env["ws"], env["me"])
    assert [str(a.get("task_id")) for a in adds] == [str(arow.get("task_id"))], adds
    assert str(adds[0].get("name") or "") == "A1", adds[0]
    assert str(adds[0].get("surface") or ""), ("面没发下来", adds[0])
    assert _owner_problems(env["ws"], env["st"], env["me"],
                           [str(arow.get("task_id"))]) == []


# ---------------------------------------------------------------- ② 反真空：顶趟的 parent=None 合法


def test_the_top_level_row_is_still_allowed_to_have_no_parent(tmp_path: pathlib.Path):
    """判据②（反真空）：树根仍然是 `parent=None`，深度 1 —— 修孤儿不许把树根也补一个父。"""
    env = _env(tmp_path)
    top = env["cond"]._task(env["me"]) or {}
    assert top.get("parent_task_id") is None, top
    assert int(top.get("depth") or 0) == 1, top
    assert env["cond"]._depth_of(None) == (1, S.CONDUCTOR_ROLE), env["cond"]._depth_of(None)
    # 树根那一行不是孤儿：它是顶趟（`open_top_level_run` 记下的绝对编号）
    assert env["cond"]._top_task_id == env["me"], env["cond"]._top_task_id


# ---------------------------------------------------------------- ③ 负控（改回 owner=""）


def test_negctl_an_empty_owner_is_caught_and_the_hidden_roster_is_named(
        tmp_path: pathlib.Path):
    """判据③（负控）：把 `owner` 改回 `""`（改前那一版）⇒ ① 的判据必红，且点名隐藏文件。

    改前的形态逐字长这样（两半都在这里复现，因为它们坏在两处）：
    ① 子行的 `parent_task_id` 落 `None`（`self.my_task_id or None`）；
    ② `roster_add(owner=self.my_task_id)` 拿空串当 owner ⇒ `out/roster/.jsonl`。
    """
    env = _env(tmp_path)
    # ① 孤儿行（改前 `parent_task_id=self.my_task_id or None` 的产物）
    kid = _row(env["cond"], None, CHILD_ROLE, key="orphan@1")
    # ② owner 空串 ⇒ 隐藏文件
    got = env["sec"].roster_add(owner="", role=CHILD_ROLE, task_id=kid, brief="孤儿那件活")
    assert got.get("problem") == "", got
    hidden = _hiding_roster_paths(env["ws"])
    assert [p.name for p in hidden] == [".jsonl"], (
        "夹具前提变了：owner 空串时名册应当落在 out/roster/.jsonl", hidden)
    problems = _owner_problems(env["ws"], env["st"], env["me"], [kid])
    assert problems, "owner 改回空串之后判据居然绿了（负控空转）"
    assert any("parent_task_id 是空的" in p for p in problems), problems
    assert any("隐藏文件" in p for p in problems), problems
    assert any("名册外子代理" in p for p in problems), problems
    # 对照：同一套判据在修好之后的那一行上必须绿（否则上面那条只是恒红）
    fixed = _row(env["cond"], env["me"], CHILD_ROLE, key="fixed@1")
    env["sec"].roster_add(owner=env["me"], role=CHILD_ROLE, task_id=fixed, brief="修好的那一件")
    hidden[0].unlink()
    assert _owner_problems(env["ws"], env["st"], env["me"], [fixed]) == []


def test_negctl_a_loop_without_a_task_id_refuses_instead_of_orphaning(tmp_path: pathlib.Path):
    """判据③（负控之二）：号一空 ⇒ 受控拒绝，一行子行都不许落（不许降级成孤儿）。

    改前那条 `or None` 把"我没有台账编号"这件事故意折成了一次合法的派活；
    现在它是一条可处置的拒绝（`refused=no_owner`），盘上不出现任何子行 ——
    于是 `_owner_problems` 那一格没有东西可看（这正是"修法"要的效果）。
    """
    ws = tmp_path / "bare"
    st = Store(ws)
    st.init()
    cond = Conductor(st, policy=None, backend=LocalBackend({}))
    reg = build_registry(store=st, conductor=cond).registry
    loop = AgentLoop(role=MY_ROLE, session_root=ws, registry=reg, conductor=cond,
                     seam=LlmSeam(role=MY_ROLE, session_root=ws, gateway=_Gate(),
                                  price=(0.0, 0.0), sid=SID),
                     store=st, sid=SID, max_steps=2)
    assert str(loop.my_task_id or "") == ""
    assert loop._summon_owner() == "", "这一格要的是'连顶趟都没有'那一档"
    out = loop._do_summon({"role": CHILD_ROLE, "task": "干一件"})
    assert out.get("ok") is False, out
    assert str(out.get("refused") or "") == "no_owner", out
    assert "parent_task_id=None" in str(out.get("error") or ""), out
    assert [r for r in st.rows("tasks") if str(r.get("role")) == CHILD_ROLE] == [], (
        "拒了却还是落了一行子行（或落了孤儿）", st.rows("tasks"))
    # 反真空：拒的是"没有号"这一件，不是"派活这件事坏了"—— 真有号时同一句话照旧派得出去
    top = cond.open_top_level_run(MY_ROLE, "顶层这一趟")
    loop.my_task_id = top
    assert loop._summon_owner() == top, loop._summon_owner()

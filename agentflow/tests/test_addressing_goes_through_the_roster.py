# -*- coding: utf-8 -*-
"""业主裁定（2026-10-19 第二版）：「名册就是可通话名单 —— 只有名册上的人能通话。」

## 诊断（改前那三句病）

1. `_do_message` 决定"这一条发给谁"靠的是「字符串启发式」：
   `to not in (*S.ROLES, M, "user", "用户")` ⇒ 当成名册名，否则走角色通道。
   名册只在"名字长得不像角色名"时被用到；「角色名那一条路从不问名册」
   ⇒ 按角色名随便发（"给 F 发一条"哪怕名下有 F1/F2 两个实例也照发，谁都能读到）。
2. `roster_view`（秘书侧）只答得出"我名下的子代理"这一半：
   每行有 `name` / `role` / `brief` / `state` / `status` / `task_id`（「绝对编号已在」），
   `scope="descendants"` 再给 `parent`（「相对名」）与 `depth`；
   「"我自己的父是谁（含绝对编号）"那一格根本不存在」 —— 它只活在
   `AgentLoop.parent_task_id` 这个内存字段里，盘上的名册一个字都没有。
3. 退役的名册成员可以寻址到"未登记「或」已退役"这一档：拒是拒了，但理由码读不出来。

## 判据（正控 7 / 负控 6 / 边界 1）

正控：① 给「父」发 ⇒ 成功，收件人 task_id == 我名册里的父编号（编号与名册名两种写法）
② 给「子」发 ⇒ 成功，收件人是那个子
③ 给「名册外的角色」（"E"：既不是父也不是子）⇒ `not_in_roster` ＋ 列出可通话名单
④ 给「退役的子」 ⇒ 拒收（`member_retired`）
⑤ 给「祖父」（父的上线）⇒ 拒收（不在"父 ∪ 子"里）
⑥ `escalate` 的上行链路仍绿 —— 见 `tests/test_escalate_goes_up_and_stops.py`
⑦ 无秘书 ⇒ 退回原来的路但读数标 `roster_unavailable`，
   且「另加一条」判据说明这一档不是"名册校验通过"（名册外的角色照样发得出去）
负控（每条都真跑一遍"坏实现"，证明同一组断言会红）：
① 去掉 `roster_view` 的父那一格 ⇒ 红
② 把父解析成"随便一个成员" ⇒ 红
③ 把守卫去掉（`not_in_roster` 放行成老通道）⇒ 红
④ 把退役当成还活着 ⇒ 红
⑤ 给祖父放行 ⇒ 红
⑦ 把"无秘书"当成解析成功 ⇒ 红
边界：按绝对编号 / 名册名发消息「不需要召唤边」（"派活要许可，说话不需要"）。
"""
from __future__ import annotations

import json
import pathlib
from typing import Any

import pytest

from agentflow import agent_loop as AL
from agentflow import capabilities as C
from agentflow import sessions as SS
from agentflow.agent_loop import AgentLoop
from agentflow.conductor import Conductor, LocalBackend
from agentflow.llmseam import LlmSeam
from agentflow.store import Store
from agentflow.tools import build_registry

SID = "addr"

#: 这一条链是四层，因为判据⑤要一个"父的上线"：
#: `M`（顶层发起行）→ `A`（祖父）→ `D`（我的父）→ `B`（**我**）→ `F1`/`F2`（我的子）
ME_ROLE, PARENT_ROLE, GRANDPARENT_ROLE = "B", "D", "A"
#: 名册外的角色：既不是父（D）也不是子（F），而 `B` 与它之间有协作边
#: （`ALLOWED_EDGES["E"]` 含 "B"）⇒ 准入不会先拒，量到的就只是"名册守卫"。
OUTSIDE_ROLE = "E"


class _Gate:
    spec = type("Spec", (), {"model": "stub", "api_key": "x"})()

    def complete(self, prompt: str, *, scope: str = "", system: str | None = None,
                 **kw: Any) -> Any:
        return type("Reply", (), {"ok": True, "text": json.dumps(
            {"final": "收工", "evidence": []}, ensure_ascii=False),
            "tool_calls": (), "tokens_in": 1, "tokens_out": 1,
            "error_detail": "", "error_kind": ""})()


def _row(cond: Conductor, parent: str, role: str, *, key: str,
         status: str = "done") -> str:
    """在台账里造一行（父/子/祖父都由它造；`depth` 按父的深度 + 1）。"""
    prow = cond._task(parent) or {}
    terminal = status not in ("pending", "running")
    return cond._write_new_row({
        "task_id": "", "role": role, "action": "run_once", "called_by": "M",
        "parent_task_id": parent, "depth": int(prow.get("depth") or 1) + 1,
        "input_key": key, "status": status,
        "outcome": "ok" if terminal else None,
        "refusal_reason": None, "instance": "", "detail": f"一个 {role} 实例",
        "error": None, "started_at": "2026-10-19T10:00:00+08:00",
        "ended_at": "2026-10-19T10:05:00+08:00" if terminal else None,
        "tokens": 0, "usd": 0.0, "artifacts": [], "inputs": [],
    }, note=f"start:{role}.run_once")


def _env(tmp_path: pathlib.Path) -> dict[str, Any]:
    """四层链 + 名册（父的名册名记在祖父那一侧）+ 我的两个子代理 F1/F2。"""
    ws = tmp_path / "ws"
    st = Store(ws)
    st.init()
    cond = Conductor(st, policy=None, backend=LocalBackend({}))
    reg = build_registry(store=st, conductor=cond).registry
    top = cond.open_top_level_run("M", "顶层这一趟")
    gp = _row(cond, top, GRANDPARENT_ROLE, key="addr@gp")
    pa = _row(cond, gp, PARENT_ROLE, key="addr@pa")
    me = _row(cond, pa, ME_ROLE, key="addr@me")
    f1 = _row(cond, me, "F", key="addr@f1")
    f2 = _row(cond, me, "F", key="addr@f2")
    loop = AgentLoop(role=ME_ROLE, session_root=ws, registry=reg, conductor=cond,
                     seam=LlmSeam(role=ME_ROLE, session_root=ws, gateway=_Gate(),
                                  price=(0.0, 0.0), sid=SID),
                     store=st, sid=SID, max_steps=2)
    loop.my_task_id = me
    loop.parent_task_id = pa
    assert loop.secretary is not None, "这一组判据要的是'名册在手上'那一档"
    sec = loop.secretary
    # 父的名册名：记在**祖父**那一侧的名册里（相对名 → 绝对编号那一步的输入）
    assert sec.roster_add(owner=gp, role=PARENT_ROLE, task_id=pa,
                          brief="我那一层的父")["name"] == "D1"
    assert sec.roster_add(owner=me, role="F", task_id=f1, brief="甲那一件")["name"] == "F1"
    assert sec.roster_add(owner=me, role="F", task_id=f2, brief="乙那一件")["name"] == "F2"
    return {"st": st, "cond": cond, "ws": ws, "loop": loop, "sec": sec,
            "top": top, "gp": gp, "pa": pa, "me": me, "f1": f1, "f2": f2}


def _messages(ws: pathlib.Path) -> list[dict[str, Any]]:
    events, _ = SS.read_session(ws, sid=SID)
    return [e for e in events if e.get("kind") == "agent_message"]


def _board(cond: Conductor, task_id: str) -> list[dict[str, Any]]:
    return [dict(r) for r in cond.open_items_of(task_id)]


def _no_side_effects(env: dict[str, Any], nobody: list[str]) -> None:
    assert _messages(env["ws"]) == [], ("一行都不许落", _messages(env["ws"]))
    for tid in nobody:
        assert _board(env["cond"], tid) == [], _board(env["cond"], tid)


# ---------------------------------------------------------------- 断言组（正控与负控共用）

def _to_parent_works(env: dict[str, Any]) -> dict[str, Any]:
    """判据①：给**父**发 ⇒ 成功，收件人 task_id == 我名册里的父编号。

    两种写法各发一条（绝对编号 / 父的名册名）—— 两种都必须落到**同一个**编号上。
    """
    loop, cond, pa = env["loop"], env["cond"], env["pa"]
    view = loop.secretary.roster_view(owner=env["me"])
    assert view["parent"]["checked"] is True, view["parent"]
    assert view["parent"]["task_id"] == pa, view["parent"]        # 名册里的父编号
    assert view["parent"]["name"] == "D1", view["parent"]         # 相对名 → 绝对编号那一步

    by_id = loop._do_message({"to": pa, "subject": "题一", "body": "文一"})
    assert by_id.get("ok") is True, by_id
    assert str(by_id.get("to_task_id") or "") == pa, by_id
    assert (by_id.get("addressing") or {}).get("how") == "parent", by_id["addressing"]
    assert (by_id.get("addressing") or {}).get("kind") == "parent", by_id["addressing"]

    by_name = loop._do_message({"to": "D1", "subject": "题二", "body": "文二"})
    assert by_name.get("ok") is True, by_name
    assert str(by_name.get("to_task_id") or "") == pa, by_name

    mine = _board(cond, pa)
    assert len(mine) == 2, mine                                   # 发给父的两条都在父板上
    assert all(str(r.get("kind")) == "message" for r in mine), mine
    assert _messages(env["ws"]) == [], ("名册通道落板项，不落 `agent_message`",
                                      _messages(env["ws"]))
    # 不许"顺手也发给别人"
    assert _board(cond, env["gp"]) == [], _board(cond, env["gp"])
    return by_id


def _to_child_works(env: dict[str, Any]) -> dict[str, Any]:
    """判据②：给**子**发 ⇒ 成功，收件人是那个子（名册名与绝对编号两种写法）。"""
    loop, cond, f1, f2 = env["loop"], env["cond"], env["f1"], env["f2"]
    by_name = loop._do_message({"to": "F1", "subject": "题", "body": "文"})
    assert by_name.get("ok") is True, by_name
    assert str(by_name.get("to_task_id") or "") == f1, by_name
    assert (by_name.get("addressing") or {}).get("kind") == "child", by_name["addressing"]
    by_id = loop._do_message({"to": f2, "subject": "题", "body": "文"})
    assert by_id.get("ok") is True, by_id
    assert str(by_id.get("to_task_id") or "") == f2, by_id

    assert len(_board(cond, f1)) == 1, _board(cond, f1)           # 板上 1 条
    assert len(_board(cond, f2)) == 1, _board(cond, f2)
    assert _messages(env["ws"]) == [], _messages(env["ws"])
    return by_name


def _outside_role_is_refused(env: dict[str, Any], role: str = OUTSIDE_ROLE
                             ) -> dict[str, Any]:
    """判据③：名册外的角色 ⇒ 受控拒绝 `not_in_roster` ＋ 可通话名单。"""
    loop, cond = env["loop"], env["cond"]
    roles = {str(r.get("role")) for r in loop.secretary.roster_view(owner=env["me"])["rows"]}
    assert roles and role not in roles, ("这一条要的就是名册外的角色", roles, role)
    got = loop._do_message({"to": role, "subject": "题", "body": "文"})

    assert got.get("ok") is False, got
    assert str(got.get("refused") or "") == "not_in_roster", got
    text = str(got.get("error") or "")
    assert role in text, text
    # 拒信里必须给出"你能通话的是：<父>、<子…>"
    assert "你能通话的是" in text, text
    for name in ("D1", "F1", "F2"):
        assert name in text, (name, text)
    assert (got.get("addressing") or {}).get("how") == "not_in_roster", got["addressing"]
    _no_side_effects(env, [env["pa"], env["f1"], env["f2"], env["gp"], env["me"]])
    assert cond is not None
    return got


def _retired_child_is_refused(env: dict[str, Any]) -> dict[str, Any]:
    """判据④：退役的子 ⇒ 拒收（理由码可读），且不牵连另一个子。"""
    loop, cond = env["loop"], env["cond"]
    done = loop.secretary.retire(owner=env["me"], name="F1")
    assert done.get("ok") is True and done.get("action") == "retired", done
    got = loop._do_message({"to": "F1", "subject": "题", "body": "文"})

    assert got.get("ok") is False, got
    assert str(got.get("refused") or "") == "member_retired", got
    text = str(got.get("error") or "")
    assert "退役" in text and "F1" in text, text
    _no_side_effects(env, [env["f1"], env["f2"], env["pa"]])
    # 另一个子照旧可用（退役不牵连别人）
    ok = loop._do_message({"to": "F2", "subject": "题", "body": "文"})
    assert ok.get("ok") is True, ok
    assert len(_board(cond, env["f2"])) == 1, _board(cond, env["f2"])
    return got


def _grandparent_is_refused(env: dict[str, Any]) -> dict[str, Any]:
    """判据⑤：给**父的上线**（祖父）发 ⇒ 拒收（不在"父 ∪ 子"里）。"""
    loop, cond = env["loop"], env["cond"]
    pa, gp = env["pa"], env["gp"]
    assert str((cond._task(pa) or {}).get("parent_task_id")) == gp, "夹具：gp 是父的上线"
    assert str((cond._task(gp) or {}).get("role")) == GRANDPARENT_ROLE, "夹具"
    got = loop._do_message({"to": GRANDPARENT_ROLE, "subject": "题", "body": "文"})
    assert got.get("ok") is False, got
    assert str(got.get("refused") or "") == "not_in_roster", got
    # 也拒"按祖父的绝对编号发"：越级不看写法
    by_id = loop._do_message({"to": gp, "subject": "题", "body": "文"})
    assert by_id.get("ok") is False and by_id.get("refused") == "not_in_roster", by_id
    _no_side_effects(env, [gp, pa, env["f1"], env["f2"]])
    return got


def _unavailable_is_flagged(bare: AgentLoop, ws: pathlib.Path) -> dict[str, Any]:
    """判据⑦：无秘书 ⇒ 退回原来的路，读数 `roster_unavailable=True`。

    **并且**这一档不是"名册校验通过"：名册外的角色照样发得出去（见调用方那条断言）。
    """
    got = bare._do_message({"to": OUTSIDE_ROLE, "subject": "题", "body": "文"})
    assert got.get("roster_unavailable") is True, got
    addr = got.get("addressing") or {}
    assert addr.get("checked") is False, addr
    assert str(addr.get("how") or "") == "roster_unavailable", addr
    assert got.get("message_sent"), ("退回的是老路：留言照发", got)
    return got


# ---------------------------------------------------------------- 正控

def test_the_roster_view_gives_parent_and_children_with_absolute_ids(tmp_path: pathlib.Path):
    """正控（第 1 件）：`roster_view` 现在同时给出"父"与"子"，且编号都是绝对的。

    改前：`rows` 已有 `task_id`（绝对编号）✅，但"我自己的父是谁"**一格都没有** ❌
    （只有 `scope="descendants"` 的相对名 `parent`）。
    """
    env = _env(tmp_path)
    view = env["loop"].secretary.roster_view(owner=env["me"])
    assert view["checked"] is True, view
    parent = view["parent"]
    assert (parent["checked"], parent["task_id"], parent["role"], parent["name"]) == (
        True, env["pa"], PARENT_ROLE, "D1"), parent
    child = {r["name"]: r for r in view["rows"]}
    assert set(child) == {"F1", "F2"}, child
    for name, tid, brief in (("F1", env["f1"], "甲那一件"), ("F2", env["f2"], "乙那一件")):
        row = child[name]
        assert (row["task_id"], row["role"], row["brief"]) == (tid, "F", brief), row
        assert row["status"] in ("running", "idle", "ready"), row      # 没退役 ⇒ 叫得应
    # 全树那一档：相对名之外再给绝对编号（通话要的是编号）
    tree = env["loop"].secretary.roster_view(owner=env["me"], scope="descendants")
    assert [r["parent_task_id"] for r in tree["rows"]] == [env["me"], env["me"]], tree["rows"]
    assert [r["parent"] for r in tree["rows"]] == ["", ""], tree["rows"]
    # 顶层没有父（`checked=True, task_id=""`：**读成了、没有父**，不是"没读成"）
    top = env["loop"].secretary.roster_view(owner=env["top"])
    assert (top["parent"]["checked"], top["parent"]["task_id"]) == (True, ""), top["parent"]
    assert "顶层" in top["parent"]["why"], top["parent"]


def test_a_message_goes_to_the_parent_in_the_roster(tmp_path: pathlib.Path):
    """正控①：给父发 ⇒ 成功，收件人 task_id == 我名册里的父编号。"""
    _to_parent_works(_env(tmp_path))


def test_a_message_goes_to_the_named_child(tmp_path: pathlib.Path):
    """正控②：给子发 ⇒ 成功，收件人是那个子。"""
    _to_child_works(_env(tmp_path))


def test_a_role_outside_the_roster_is_refused_with_the_callable_list(tmp_path: pathlib.Path):
    """正控③：名册外的角色 ⇒ `not_in_roster` ＋ 拒信列出可通话名单。"""
    _outside_role_is_refused(_env(tmp_path))


def test_a_retired_child_is_refused(tmp_path: pathlib.Path):
    """正控④：退役的子 ⇒ 拒收。"""
    _retired_child_is_refused(_env(tmp_path))


def test_the_grandparent_is_not_callable(tmp_path: pathlib.Path):
    """正控⑤：祖父（父的上线）不在"父 ∪ 子"里 ⇒ 拒收。"""
    _grandparent_is_refused(_env(tmp_path))


def test_no_secretary_is_a_fallback_not_a_roster_check(tmp_path: pathlib.Path):
    """正控⑦：无秘书 ⇒ 退回原来的路并标 `roster_unavailable`；**它不是名册校验通过**。"""
    env = _env(tmp_path)
    bare = AgentLoop(role=ME_ROLE, session_root=env["ws"], registry=env["loop"].registry,
                     conductor=env["cond"], seam=env["loop"].seam, store=env["st"],
                     sid=SID, auto_secretary=False)
    bare.my_task_id = env["me"]
    assert bare.secretary is None, "这一条判据要的就是'秘书不在手上'那一档"
    _unavailable_is_flagged(bare, env["ws"])
    # 「这不是名册校验通过」的**那一条判据**：名册外（甚至根本不是名册上任何人）的
    # 角色，在这一档照样发得出去 —— 因为它压根没查名册。
    assert _messages(env["ws"]) and str(_messages(env["ws"])[0].get("to")) == OUTSIDE_ROLE, \
        ("无秘书那一档必须露出'没查名册'这件事", _messages(env["ws"]))


# ---------------------------------------------------------------- 负控（每个都真跑一遍坏实现）

def test_negctl_dropping_the_parent_cell_is_red(tmp_path: pathlib.Path,
                                                monkeypatch: pytest.MonkeyPatch):
    """负控①：`roster_view` 不给我父那一格（改前的老样子）⇒ 判据①必红。"""
    env = _env(tmp_path)
    real = type(env["sec"]).parent_of

    def without_parent(self, *, owner):
        return {"checked": True, "task_id": "", "role": "", "name": "", "why": "（坏实现：不给我父）"}

    monkeypatch.setattr(type(env["sec"]), "parent_of", without_parent)
    assert callable(real)
    with pytest.raises(AssertionError):
        _to_parent_works(env)


def test_negctl_resolving_the_parent_to_a_child_is_red(tmp_path: pathlib.Path,
                                                       monkeypatch: pytest.MonkeyPatch):
    """负控②：把"父"解析成"名册里的随便一个成员"⇒ 判据①必红（收件人编号对不上）。"""
    env = _env(tmp_path)
    real = AL.roster_addresses

    def broken(secretary, *, to, owner="", my_task_id=""):
        got = real(secretary, to=to, owner=owner, my_task_id=my_task_id)
        if str(got.get("how") or "") == "parent":
            got = {**got, "kind": "child", "task_id": env["f1"], "name": "F1"}
        return got

    monkeypatch.setattr(AL, "roster_addresses", broken)
    with pytest.raises(AssertionError):
        _to_parent_works(env)


def test_negctl_removing_the_not_in_roster_guard_is_red(tmp_path: pathlib.Path,
                                                        monkeypatch: pytest.MonkeyPatch):
    """负控③：把守卫去掉（`not_in_roster` 放行成老通道）⇒ 判据③必红。"""
    env = _env(tmp_path)
    real = AL.roster_addresses

    def broken(secretary, *, to, owner="", my_task_id=""):
        got = real(secretary, to=to, owner=owner, my_task_id=my_task_id)
        if str(got.get("how") or "") == "not_in_roster":
            got = {**got, "how": "outside_roster", "refused": "", "error": ""}
        return got

    monkeypatch.setattr(AL, "roster_addresses", broken)
    with pytest.raises(AssertionError):
        _outside_role_is_refused(env)


def test_negctl_a_retired_child_that_still_receives_is_red(tmp_path: pathlib.Path,
                                                           monkeypatch: pytest.MonkeyPatch):
    """负控④：把退役当成还活着 ⇒ 判据④必红（板项真的会落到退役那个实例名下）。"""
    env = _env(tmp_path)
    real = AL.roster_addresses

    def broken(secretary, *, to, owner="", my_task_id=""):
        got = real(secretary, to=to, owner=owner, my_task_id=my_task_id)
        if str(got.get("how") or "") == "member_retired":
            got = {**got, "how": "child", "kind": "child", "refused": "", "error": ""}
        return got

    monkeypatch.setattr(AL, "roster_addresses", broken)
    with pytest.raises(AssertionError):
        _retired_child_is_refused(env)


def test_negctl_letting_the_grandparent_through_is_red(tmp_path: pathlib.Path,
                                                       monkeypatch: pytest.MonkeyPatch):
    """负控⑤：给祖父放行 ⇒ 判据⑤必红。"""
    env = _env(tmp_path)
    real = AL.roster_addresses

    def broken(secretary, *, to, owner="", my_task_id=""):
        got = real(secretary, to=to, owner=owner, my_task_id=my_task_id)
        if str(got.get("how") or "") == "not_in_roster":
            got = {**got, "how": "outside_roster", "refused": "", "error": ""}
        return got

    monkeypatch.setattr(AL, "roster_addresses", broken)
    with pytest.raises(AssertionError):
        _grandparent_is_refused(env)


def test_negctl_calling_the_fallback_a_successful_resolution_is_red(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    """负控⑦：把"无秘书"当成解析成功（不标 `roster_unavailable`）⇒ 判据⑦必红。"""
    env = _env(tmp_path)
    bare = AgentLoop(role=ME_ROLE, session_root=env["ws"], registry=env["loop"].registry,
                     conductor=env["cond"], seam=env["loop"].seam, store=env["st"],
                     sid=SID, auto_secretary=False)
    bare.my_task_id = env["me"]
    monkeypatch.setattr(
        AgentLoop, "_address_of",
        lambda self, to: {"to": to, "checked": True, "how": "role_no_instance",
                          "kind": "", "name": "", "task_id": "", "role": to,
                          "brief": "", "candidates": [], "callable": "",
                          "refused": "", "error": "", "why": "（坏实现：当成了解析成功）"})
    with pytest.raises(AssertionError):
        _unavailable_is_flagged(bare, env["ws"])


# ---------------------------------------------------------------- 边界（防误伤）

def test_a_message_to_a_roster_member_needs_no_summon_edge(tmp_path: pathlib.Path):
    """防误伤："派活要许可，说话不需要" —— 按编号/名册名发不吃召唤边。

    我是 B，`ALLOWED_EDGES["B"] == {C, H, V}`：**B 叫不到 F**。而 F1 是我名下的子，
    `to="F1"` 与 `to=<F1 的绝对编号>` 都必须照投（`_message_to_member` 从不问召唤边）。
    谁若把名册校验顺手接成"先查召唤边"，这一条会红。
    """
    env = _env(tmp_path)
    assert "F" not in C.ALLOWED_EDGES.get(ME_ROLE, frozenset()), (
        "这条判据要的就是一条不存在的召唤边；边表变了就得换一对角色",
        sorted(C.ALLOWED_EDGES.get(ME_ROLE, ())))
    loop, cond = env["loop"], env["cond"]
    for token in ("F1", env["f1"]):
        got = loop._do_message({"to": token, "subject": "题", "body": "文"})
        assert got.get("ok") is True, (token, got)
        assert str(got.get("to_task_id") or "") == env["f1"], (token, got)
    assert len(_board(cond, env["f1"])) == 1 or len(_board(cond, env["f1"])) == 2, \
        _board(cond, env["f1"])
    assert _messages(env["ws"]) == [], _messages(env["ws"])


def test_the_three_states_of_the_reading_are_not_flat(tmp_path: pathlib.Path):
    """读数三态：读成了 / 不在名册 / 读不成 —— 不许折成同一句话。

    直接打在 `roster_addresses` 上（它是这一层的唯一判据面）。
    """
    env = _env(tmp_path)
    sec, me = env["sec"], env["me"]
    parent = AL.roster_addresses(sec, to=env["pa"], owner=me, my_task_id=me)
    assert (parent["checked"], parent["how"]) == (True, "parent"), parent
    child = AL.roster_addresses(sec, to="F1", owner=me, my_task_id=me)
    assert (child["checked"], child["how"]) == (True, "child"), child
    outside = AL.roster_addresses(sec, to=OUTSIDE_ROLE, owner=me, my_task_id=me)
    assert (outside["checked"], outside["how"]) == (True, "not_in_roster"), outside
    blind = AL.roster_addresses(None, to="F1", owner=me, my_task_id=me)
    assert (blind["checked"], blind["how"]) == (False, "roster_unavailable"), blind
    # 角色名的便利写法：名册内唯一匹配才认（F 匹配到 F1/F2 两个 ⇒ 拒，不挑）
    ambiguous = AL.roster_addresses(sec, to="F", owner=me, my_task_id=me)
    assert (ambiguous["checked"], ambiguous["how"]) == (True, "ambiguous_in_roster"), ambiguous
    assert ambiguous["candidates"] == ["F1", "F2"], ambiguous
    unique = AL.roster_addresses(sec, to=PARENT_ROLE, owner=me, my_task_id=me)
    assert (unique["checked"], unique["how"]) == (True, "parent"), unique
    # 公共频道 / 用户不是"给某个代理发消息"⇒ 不归名册管（`_emit_settlement` 同一条边界）
    for token in (AL.PUBLIC, "ALL", "user"):
        out = AL.roster_addresses(sec, to=token, owner=me, my_task_id=me)
        assert (out["checked"], out["how"]) == (True, "outside_roster"), (token, out)

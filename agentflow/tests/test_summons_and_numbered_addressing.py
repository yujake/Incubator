# -*- coding: utf-8 -*-
"""召回收据不许说谎（`summons` 只记真派出去的）＋模型可以按名册名/绝对编号寻址。

## 现场（2026-10-22 查实，两处同族缺陷）

A. `LoopRun.summons` 与刚修好的 `messages_sent` 是同一形状的缺陷：只看
   `shape == "summon"`，不看那一步的结果。实测两种"形状对、什么也没派出去"的步：

   - C 想唤 A：被 `forbidden_edge` 拒（`ok: false`、`outcome: "refused"`），
     `Conductor._refuse` 还落了一行 `outcome=refused` 的台账（所以 `task_id` 也非空），
     一步都没派出去，而 `run.summons == ["A"]`；
   - 两段式洗格式请示：`outcome: "wash_proposed"`、`executed: false`，结果自己写着
     "这一趟没有派活（0 行新任务、0 次子任务调用）"，而 `run.summons == ["D"]`。

B. `_decode_shape` 的 `message.to` 只认角色名 / M / `#public`（`_known_recipient`），
   不认名册名与绝对台账号：模型写 `{"message": {"to": "B1"}}` 或台账号 ⇒ 判
   invalid / bad_args，一步也发不出去 —— 而 `roster_addresses` 明明支持那两种写法。
   于是业主"按编号沟通"在模型这一侧根本走不到（只有测试里直接调 `_do_message` 才走得到）。

## 判据（六条，零模型，tmp 目录）

| # | 断言 | 改前红在哪 |
|---|---|---|
| 1 | C→A 被 `forbidden_edge` 拒 ⇒ `summons == []`，`summons_refused` 点名 `{to:"A", refused:"forbidden_edge"}` | `summons == ["A"]` |
| 2 | 洗格式请示（`wash_proposed`，0 行新任务）⇒ `summons == []`，`summons_refused` 里 `outcome="wash_proposed"` | `summons == ["B"]` |
| 3 | 正控：走合法边、拿到 `task_id` ⇒ `summons == [角色]`、`summons_refused == []` | 没有 `summons_refused` 这一格 |
| 4 | 模型写 `to="B1"`（名册名）⇒ 落到 B 的收件箱（`read_messages(role="B")` 读得到，body 逐字） | 被判 invalid，一步也发不出 |
| 5 | 模型写绝对台账号 ⇒ 同上；认不出 ⇒ `unknown_roster_name` + 候选点名；歧义 ⇒ `ambiguous_in_roster` + 候选点名，两档都不落任何收件箱 | 绝对台账号被判 invalid |
| 6 | 反真空：`_summon_landed` 恒真 ⇒ 判据 1/2 必红；名册解析恒等 ⇒ 判据 4 必红 | 这一条量的就是"判据真的在看结果" |

判据体写成函数（`_forbidden_edge_is_not_a_summon` / `_wash_proposal_is_not_a_summon` /
`_roster_name_lands_in_the_role_inbox`），正控与反真空调用同一份 —— 于是"红"不是一个
断言串，而是同一个函数在坏实现上真的失败。

为什么判据 1 还要单独钉"被拒的那一行也有 task_id"：它是这个缺陷最容易修错的地方 ——
只看 `task_id` 非空会把受控拒绝重新数成"派出去了"，那只是把谎言换了个方向。

零模型：配方照 `tests/test_agent_loop.py`（`_wired` + 替身网关）、
`tests/test_children_and_parent_are_visible.py`（父/子/名册那一套夹具）与
`tests/test_the_wash_is_proposed_not_applied.py`（洗格式那一条真实链路），
不另造通道、不另造父子夹具。
"""
from __future__ import annotations

import json
import pathlib
import re
from typing import Any

import pytest

import test_agent_loop as TAL
import test_children_and_parent_are_visible as TCP
import test_the_wash_is_proposed_not_applied as TWP

from agentflow import agent_loop as AL
from agentflow.agent_loop import read_messages, run_role
from agentflow.llmseam import LlmSeam

#: 收件人那一侧要逐字回读的那一句（判据 4/5：body 不许被改写、不许被截断）。
BODY = "只在 n<=5 时成立（这一句要逐字回读）"


def _say(obj: dict[str, Any]) -> str:
    """把一句话写成 JSON（替身网关读的就是它）。"""
    return json.dumps(obj, ensure_ascii=False)


# ============================================================ 判据 1：被拒的召唤不算派出

def _run_c_summon_a(root: pathlib.Path) -> tuple[Any, Any]:
    """跑一趟 C：它的模型第一步想唤 A（C 的协作边是空的 ⇒ `forbidden_edge`）。"""
    scripts = {"C": [_say({"summon": {"role": "A", "task": "把这条定理的形式化检查做掉",
                                      "why": "我需要一条可复算的检查"}}),
                      _say({"final": "已经请主控代唤", "evidence": []})]}
    st, cond, reg, gw, ws = TAL._wired(root, scripts)
    run = run_role("C", "越权唤一次 A", store=st, registry=reg, conductor=cond,
                   seam=LlmSeam(role="C", session_root=ws, gateway=gw["C"],
                                price=(0.0, 0.0), sid="test-run"),
                   workspace_root=str(ws), sid="test-run", from_env=False)
    return run, st


def _forbidden_edge_is_not_a_summon(root: pathlib.Path) -> None:
    """判据 1 的全部断言（正控与反真空共用这一份）。"""
    run, st = _run_c_summon_a(root)
    assert run.stop_reason == "final", run.to_dict()
    assert [s.shape for s in run.steps] == ["summon", "final"], run.to_dict()
    step = run.steps[0].result
    assert step.get("ok") is False, step
    assert str(step.get("outcome") or "") == "refused", step
    assert str(step.get("refusal_reason") or "") == "forbidden_edge", step
    # 被拒的那一行也有 `task_id`（`_refuse` 真的落了台账）—— 所以判据不能只看编号。
    assert str(step.get("task_id") or ""), ("被拒的召唤也有一行台账", step)
    rows = [r for r in st.rows("tasks") if str(r.get("role")) == "A"]
    assert rows and str(rows[0].get("outcome")) == "refused", rows

    assert run.summons == [], ("被拒的那一步不是派出去了", run.to_dict())
    refused = run.summons_refused
    assert len(refused) == 1, refused
    assert refused[0]["to"] == "A", refused
    assert refused[0]["refused"] == "forbidden_edge", refused
    assert refused[0]["outcome"] == "refused", refused
    assert "允许的边" in refused[0]["error"], refused


def test_a_forbidden_edge_is_not_counted_as_a_summon(tmp_path: pathlib.Path) -> None:
    """判据 1：C→A 被 `forbidden_edge` 拒 ⇒ `summons == []`，被拒的那条逐项点名。

    改前必红：旧实现只看 `shape == "summon"`，于是 `run.summons == ["A"]`
    （而台账里那一行是 `outcome=refused`：一个子代理都没被唤起）。
    """
    _forbidden_edge_is_not_a_summon(tmp_path)


# ============================================================ 判据 2：请示不算派出

def _wash_proposal_is_not_a_summon(root: pathlib.Path) -> None:
    """判据 2 的全部断言（正控与反真空共用这一份）。"""
    got = TWP._run(root)
    run, store = got["run"], got["store"]
    steps = [s.result for s in run.steps if s.shape == "summon"]
    assert steps, run.to_dict()
    first = steps[0]
    assert str(first.get("outcome") or "") == "wash_proposed", first
    assert first.get("executed") is False, first
    assert not str(first.get("task_id") or ""), ("请示没有落点", first)
    # 0 行新任务：名册上那个 B 一行都没有
    assert [r for r in store.rows("tasks") if str(r.get("role")) == "B"] == [], \
        "请示那一档真的派了子任务"

    assert run.summons == [], ("请示不是派出去了", run.to_dict())
    refused = run.summons_refused
    assert len(refused) == len(steps), (refused, run.to_dict())
    assert refused[0]["to"] == "B", refused
    assert refused[0]["outcome"] == "wash_proposed", refused
    assert refused[0]["refused"] == "", ("这不是被拒，是在等父表态", refused)
    assert "没有派活" in refused[0]["error"], refused


def test_a_wash_proposal_is_not_counted_as_a_summon(tmp_path: pathlib.Path) -> None:
    """判据 2：洗格式请示（`wash_proposed`、0 行新任务）⇒ `summons == []`，逐条点名。

    改前必红：旧实现把这一步数成 `run.summons == ["B"]`，而结果自己写着
    "这一趟没有派活（0 行新任务、0 次子任务调用）"。
    """
    _wash_proposal_is_not_a_summon(tmp_path)


# ============================================================ 判据 3：正控（真派出去）

def test_a_real_dispatch_is_counted_and_nothing_is_refused(tmp_path: pathlib.Path) -> None:
    """判据 3（正控，别只测负向）：走合法边、真拿到 `task_id` ⇒ `summons` 记它、没有一条被拒。"""
    scripts = {"M": [_say({"summon": {"role": "D", "task": "先要一个结论",
                                      "params": {"qid": "q-0001"},
                                      "why": "这一步真的派活"}}),
                      _say({"final": "派完了", "evidence": []})],
               "D": [_say({"final": "收到", "evidence": []})]}
    st, cond, reg, gw, ws = TAL._wired(tmp_path, scripts)
    run = run_role("M", "派一环", store=st, registry=reg, conductor=cond,
                   seam=LlmSeam(role="M", session_root=ws, gateway=gw["M"],
                                price=(0.0, 0.0), sid="test-run"),
                   workspace_root=str(ws), sid="test-run", from_env=False)

    assert run.stop_reason == "final", run.to_dict()
    step = next(s.result for s in run.steps if s.shape == "summon")
    assert step.get("ok") is True, step
    assert str(step.get("task_id") or ""), ("真派出去的那一步应当有落点", step)
    assert run.summons == ["D"], run.summons
    assert run.summons_refused == [], run.summons_refused
    # 台账号里只数"真的那一环"：板项（`kind` 非空）不是召唤，先摘出去再数。
    rows = [r for r in st.rows("tasks")
            if str(r.get("role")) == "D" and str(r.get("called_by")) == "M"
            and not str(r.get("kind") or "")]
    assert len(rows) == 1 and str(rows[0].get("outcome")) == "ok", rows


# ============================================================ 判据 4/5：名册名与绝对编号

def _addressing_env(root: pathlib.Path, replies: list[str], *,
                    two_b_children: bool = False) -> dict[str, Any]:
    """父/子/名册那一套夹具（不另造）：我是 A，名册上有 B1（角色 B）与 G1（角色 G）两行。

    `two_b_children=True` 时再补一行角色 B 的子代理（名册名 B2）—— 判据 5 的"歧义"那一档
    要的就是"角色 B 在我的名册里匹配到两个"。
    """
    st, cond, reg, ws, me, kids, _other = TCP._tree(root, role="A")
    rows: list[tuple[str, str]] = [(kids[0], "B"), (kids[1], "G")]
    if two_b_children:
        rows.append((TCP._child(cond, role="B", parent=me, depth=3, key="kid3@1"), "B"))
    loop = TCP._loop(cond, reg, ws, st, TCP._Gate(replies), role="A")
    names: dict[str, str] = {}
    for n, (kid, role) in enumerate(rows, start=1):
        got = loop.secretary.roster_add(owner=me, role=role, task_id=kid,
                                        brief=f"第 {n} 件活")
        assert got["problem"] == "", got
        assert got["name"] not in names, got
        names[got["name"]] = kid
    run = loop.run("把这一条交给名册上的子代理", summoned_by="M", my_task_id=me, depth=2)
    return {"run": run, "ws": ws, "cond": cond, "names": names, "me": me, "loop": loop,
            "st": st}


def _inbox(ws: pathlib.Path, role: str) -> list[dict[str, Any]]:
    """读某个角色的收件箱（零问题；读不成要红，不许折成空）。"""
    msgs, problems = read_messages(ws, role, sid=TCP.SID)
    assert problems == [], (role, problems)
    return msgs


def _roster_name_lands_in_the_role_inbox(root: pathlib.Path) -> None:
    """判据 4 的全部断言（正控与反真空共用这一份）。"""
    env = _addressing_env(root, [_say({"message": {"to": "B1", "subject": "约束",
                                                   "body": BODY}}),
                                 _say({"final": "发好了", "evidence": []})])
    run = env["run"]
    assert run.messages_sent == ["B"], run.to_dict()
    assert run.messages_refused == [], run.to_dict()

    step = run.steps[0]
    assert step.shape == "message", step.to_dict()
    assert str(step.payload.get("to")) == "B", ("收件箱认得的角色", step.payload)
    marker = step.payload.get("roster_addressing") or {}
    assert marker.get("written") == "B1", step.payload
    assert marker.get("task_id") == env["names"]["B1"], step.payload
    assert marker.get("role") == "B", step.payload

    # 模型写的是名册名，落的是角色收件箱：body 逐字读得到。
    inbox = _inbox(env["ws"], "B")
    assert [m for m in inbox if str(m.get("body")) == BODY], (inbox, BODY)
    # 只进收件人那里（名册上的另一个子 G1 与发信人自己都不该读到）。
    assert _inbox(env["ws"], "G") == [], "留言串到了别人的收件箱"
    assert _inbox(env["ws"], "A") == [], "发信人不该读到自己的私聊"


def test_a_roster_name_addresses_the_role_inbox(tmp_path: pathlib.Path) -> None:
    """判据 4：模型写 `to="B1"`（B1 在名册里）⇒ 真的落到 B 的收件箱，body 逐字。

    改前必红：`_decode_shape` 只认角色名 / M / `#public` ⇒ 这一步被判 invalid
    （`bad_args`），一步也发不出去。
    """
    _roster_name_lands_in_the_role_inbox(tmp_path)


def test_a_numbered_address_is_refused_or_lands_in_the_role_inbox(
        tmp_path: pathlib.Path) -> None:
    """判据 5：绝对台账号同样能寻址；认不出 / 有歧义 ⇒ 明确拒绝码 + 候选点名，且一行都不落。

    三档（同一族，方向不同）：
    ① 绝对台账号（`to=<B1 的编号>`）⇒ 与判据 4 同一落点（B 的收件箱、body 逐字）；
    ② 名册上没有的名字（`B9`）⇒ `unknown_roster_name`，拒信里点名"你能通话的是"；
    ③ 角色 B 在名册里有两行（B1/B2）而模型写 `to="B"` ⇒ `ambiguous_in_roster`，
       候选点名 B1 与 B2，不替它挑一个。
    ②③ 两条都要断言"不落任何收件箱"—— 拒绝不许留下半条留言。

    改前必红：①（与 ② 的拒绝码）在旧解码线下被判 invalid，一步也发不出去；
    ③ 走的是 `roster_addresses` 已有的歧义判据（这一档旧实现就拒，放在这里是为了把
    "名字/编号解析"与"歧义"两条口径钉在一起，防止解码层把角色名解析成"随便挑一个"）。
    """
    # ---- ① 绝对台账号
    # 同一套夹具另跑一趟：这次让模型写绝对编号（只换模型写的那一句）。
    st, cond, reg, ws, me, kids, _other = TCP._tree(tmp_path / "by_id", role="A")
    kid = kids[0]
    loop = TCP._loop(cond, reg, ws, st, TCP._Gate([
        _say({"message": {"to": kid, "subject": "约束", "body": BODY}}),
        _say({"final": "发好了", "evidence": []})]), role="A")
    got = loop.secretary.roster_add(owner=me, role="B", task_id=kid, brief="第 1 件活")
    assert got["problem"] == "" and got["name"] == "B1", got
    run = loop.run("把这一条交给名册上的子代理", summoned_by="M", my_task_id=me, depth=2)
    assert run.messages_sent == ["B"], run.to_dict()
    assert run.messages_refused == [], run.to_dict()
    step = run.steps[0]
    assert step.shape == "message", step.to_dict()
    assert str(step.payload.get("to")) == "B", step.payload
    assert (step.payload.get("roster_addressing") or {}).get("written") == kid, step.payload
    inbox = _inbox(ws, "B")
    assert [m for m in inbox if str(m.get("body")) == BODY], (inbox, BODY)

    # ---- ② 认不出的名册名
    env2 = _addressing_env(tmp_path / "unknown", [
        _say({"message": {"to": "B9", "subject": "约束", "body": BODY}}),
        _say({"final": "改好了", "evidence": []})])
    run2 = env2["run"]
    assert run2.messages_sent == [], run2.to_dict()
    assert run2.messages_refused == [], ("解码层就拒了：没有落腔的 message 步", run2.to_dict())
    bad = run2.steps[0]
    assert bad.shape == "invalid", bad.to_dict()
    assert bad.result.get("shape_recognized") == "message", bad.result
    assert bad.payload.get("refused") == "unknown_roster_name", bad.payload
    problem = str(bad.result.get("problem") or "")
    assert "unknown_roster_name" in problem, problem
    for name in ("B1", "G1"):
        assert name in problem, ("认不出时要把候选点名", name, problem)
    assert run2.bad_args == 1 and run2.bad_json == 0, run2.to_dict()
    for role in ("B", "G"):
        assert _inbox(env2["ws"], role) == [], ("被拒的那一条不许落收件箱", role)

    # ---- ③ 歧义：角色 B 在名册里有两行
    env3 = _addressing_env(tmp_path / "ambiguous", [
        _say({"message": {"to": "B", "subject": "约束", "body": BODY}}),
        _say({"final": "改好了", "evidence": []})], two_b_children=True)
    run3 = env3["run"]
    amb = run3.steps[0]
    assert amb.shape == "message", amb.to_dict()
    assert amb.result.get("refused") == "ambiguous_in_roster", amb.result
    assert list(amb.result.get("candidates") or []) == ["B1", "B2"], amb.result
    assert "B1" in str(amb.result.get("error") or "") and \
        "B2" in str(amb.result.get("error") or ""), amb.result
    assert run3.messages_sent == [], run3.to_dict()
    assert [r["refused"] for r in run3.messages_refused] == ["ambiguous_in_roster"], \
        run3.messages_refused
    for role in ("B", "G"):
        assert _inbox(env3["ws"], role) == [], ("歧义被拒时不许挑一个投", role)


# ============================================================ 判据 6：反真空

def test_the_summon_receipt_rule_is_not_vacuous(tmp_path: pathlib.Path,
                                                monkeypatch: pytest.MonkeyPatch) -> None:
    """反真空：把 `_summon_landed` 换成恒真（= 旧实现的 `shape == "summon"`）⇒ 判据 1/2 必红。

    不复制一份旧实现：恒真谓词就是"只看形状"那版判据。判据体原样再跑一遍，
    它必须在同一个夹具上失败 —— 否则它量的不是"那一步的结果"。
    """
    monkeypatch.setattr(AL, "_summon_landed", lambda result: True)
    with pytest.raises(AssertionError):
        _forbidden_edge_is_not_a_summon(tmp_path / "forbidden")
    with pytest.raises(AssertionError):
        _wash_proposal_is_not_a_summon(tmp_path / "wash")


def test_the_roster_resolution_is_not_vacuous(tmp_path: pathlib.Path,
                                              monkeypatch: pytest.MonkeyPatch) -> None:
    """反真空：把名册解析换成恒等（写法原样当角色）⇒ 判据 4 必红。

    恒等解析就是"没接名册"那一版：`to` 仍是 `B1`，翻不成收件箱认得的角色 ——
    判据 4 的三条（落盘、计数、读得到）都拿不到。
    """
    def identity(secretary: Any, *, to: str, owner: str = "", my_task_id: str = "",
                 sender: str = "") -> dict[str, Any]:
        return {"to": str(to), "checked": True, "how": "child", "kind": "child",
                "name": str(to), "task_id": str(to), "role": str(to), "brief": "",
                "candidates": [], "callable": "", "refused": "", "error": "",
                "why": "（坏实现：恒等解析，没接名册）"}

    monkeypatch.setattr(AL, "roster_addresses", identity)
    with pytest.raises(AssertionError):
        _roster_name_lands_in_the_role_inbox(tmp_path / "identity")


# ============================================================ 键集自检

def test_to_dict_documents_every_key_it_returns() -> None:
    """`LoopRun.to_dict` 的 docstring 逐格清单与它真的返回的键集双向相等（含顺序）。

    为什么值得一条判据：`summons_refused` 这一格是照 `messages_refused` 那一笔加的，
    两笔的共同纪律是"回执的每一格都要在文档里，而文档里不许有没返回的格子" ——
    单向检查（只查少写）会让"文档写了但没返回"活下来，那是最难查的一种。
    """
    run = AL.LoopRun(role="D", task="对一遍键集")
    keys = list(run.to_dict())
    doc = AL.LoopRun.to_dict.__doc__ or ""
    head, _, tail = doc.partition("顶层键集合（逐格，顺序即声明序）：")
    assert head != doc and tail, "docstring 里没有那份逐格清单"
    body = tail.split("。", 1)[0]
    listed = re.findall(r"`([^`]+)`", body)
    assert listed == keys, ("逐格清单与实际键集不一致（两个方向都要相等）", listed, keys)
    assert "summons_refused" in keys and "messages_refused" in keys, keys

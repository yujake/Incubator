# -*- coding: utf-8 -*-
"""上行：`conductor.escalate` 把"我需要召唤者做什么"交给父，然后这一趟优雅停。

业主 2026-10-19 的裁定：「父子天然双向」—— 父子身份逻辑本来就是通用的（`AgentLoop._resolve_parent`
解析出这一趟的收件人、`_opening_transcript` 把它渲染给模型），但没有可调用的上行入口：子代理跑到
一半卡住时只能靠返回值等下一轮，或者借别人的边绕（真机 `t5-run2` 里 `H` 就是借边绕去找 A 的，多花
两跳）。

这一组守四件事（每条都有正控 + 负控）：① 子 escalate ⇒ 父的 `inbox` 多一条（含 `need`/`kind`/
`evidence`），子 `stop_reason="escalated"`、退出码 5 —— 负控：把"写 inbox"那一步换成只回编号、不落盘
的桩 ⇒ `inbox` 一条都没有；② 父下一轮读到这条，读一次即 `mark_delivered` 登记已读 ⇒ 同一需求不会
被重复处理 —— 负控：换成 no-op ⇒ 它仍然是 fresh；③ 顶层（M 没有父）调它 ⇒ 受控拒绝 `not_caller`，
`statements` / `inbox` 一行不写 —— 负控：守卫换成"伪造一个父" ⇒ 它照样写、照样以 escalated 收工；
④ 一条最小链：父 summon 子、子 escalate、父再 summon 另一个角色 ⇒ 全程 `stop_reason` / 退出码都对
—— 负控：`_resolve_parent` 换成返回空 ⇒ ③ 与 ④ 同时红。

为什么"退出码"要和"`stop_reason`"一起测：`cli.EXIT_CODE_BY_STOP` 是一张表，而"循环真的把
`stop_reason` 落成了 escalated"是另一件事 —— 两半合起来才是"脚本读得到这个结局"。"""
from __future__ import annotations

import json
import pathlib
from typing import Any

import pytest

from agentflow import agent_loop as AL
from agentflow import cli as CLI
from agentflow import conductor as CD
from agentflow.agent_loop import AgentLoop, read_messages
from agentflow.conductor import Conductor, LocalBackend
from agentflow.llmseam import LlmSeam
from agentflow.store import Store
from agentflow.tools import build_registry

SID = "esc1"
NEED = "取回 lit:0007 的全文第 3 页（我这边只有摘要）"
KIND = "fetch_fulltext"
EVIDENCE = ["lit:0007", "stmt:0042"]


# ============================================================ 夹具


class _Gateway:
    """照剧本回答的替身模型（`complete(prompt, *, scope, system)` 与真模型同接口）。"""

    spec = type("Spec", (), {"model": "scripted", "api_key": "fake"})()

    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)
        self.prompts: list[str] = []

    def complete(self, prompt: str, *, scope: str = "", system: str | None = None,
                 **kw: Any) -> Any:
        self.prompts.append(prompt)
        text = self.replies[min(len(self.prompts) - 1, len(self.replies) - 1)]
        return type("Reply", (), {"ok": True, "text": text, "tokens_in": 10, "tokens_out": 10,
                                  "error_detail": "", "error_kind": ""})()


def _escalate_reply(need: str = NEED, kind: str = KIND,
                    evidence: list[str] | None = None) -> str:
    import json

    return json.dumps({"tool": "conductor.escalate",
                       "args": {"need": need, "kind": kind,
                                "evidence": EVIDENCE if evidence is None else evidence}},
                      ensure_ascii=False)


def _ws(tmp_path: pathlib.Path) -> tuple[Store, pathlib.Path]:
    ws = tmp_path / "ws"
    st = Store(ws)
    st.init()
    return st, ws


def _cond(st: Store) -> Conductor:
    return Conductor(st, backend=LocalBackend({}))


def _registry(st: Store, cond: Conductor):
    return build_registry(store=st, conductor=cond).registry


def _loop(role: str, *, ws: pathlib.Path, st: Store, cond: Conductor, registry,
          replies: list[str], sid: str = SID) -> tuple[AgentLoop, _Gateway]:
    gw = _Gateway(replies)
    seam = LlmSeam(role=role, session_root=ws, gateway=gw, price=(0.0, 0.0), sid=sid)
    loop = AgentLoop(role=role, session_root=ws, registry=registry, seam=seam,
                     conductor=cond, store=st, sid=sid, auto_secretary=False)
    return loop, gw


def _parent_row(cond: Conductor, role: str = "M") -> str:
    """真的开一条顶趟行（父的台账号与角色都由台账那行给出，不由测试编）。"""
    return cond.open_top_level_run(role, "父那一趟（探针）")


def _escalations(ws: pathlib.Path, role: str, *, sid: str = SID) -> list[dict]:
    """某个角色收件箱里这一条上行（按 `escalation` 那一格捞，不按正文字面）。"""
    msgs, _problems = read_messages(ws, role, sid=sid)
    return [m for m in msgs if isinstance(m.get("escalation"), dict)]


def _raw_escalations(ws: pathlib.Path, *, sid: str = SID) -> list[dict]:
    """盘上写过几条上行（不看收件箱的可见面）。

    为什么 ③ 要用它而不是 `_escalations`：`read_messages` 刻意跳过"我自己说的"
    （`from == role`），而顶层那一趟若把需求写给 M，发信人与收件人是同一个角色 ——
    于是"写过了"在收件箱视角里看不见。③ 问的是"写没写"，所以按盘上的原始行读。
    """
    events, _problems = AL.SS.read_session(ws, sid=sid)
    return [e for e in events
            if e.get("kind") == "agent_message" and isinstance(e.get("escalation"), dict)]


class _Run:
    """最小替身：`_run_agent_exit_code` 只读 `stop_reason`。"""

    def __init__(self, stop_reason: str) -> None:
        self.stop_reason = stop_reason


# ============================================================ ① 子 escalate ⇒ 父 inbox +1、退出码 5


def test_a_child_escalation_lands_in_the_parent_inbox_and_stops_the_run(
        tmp_path: pathlib.Path) -> None:
    """正控①：需求进父的收件箱（带 need/kind/evidence），这一趟以 escalated 收工、退出码 5。"""
    st, ws = _ws(tmp_path)
    cond = _cond(st)
    pid = _parent_row(cond)
    loop, gw = _loop("B", ws=ws, st=st, cond=cond, registry=_registry(st, cond),
                     replies=[_escalate_reply()])
    run = loop.run("把这条链交给父（桩）", summoned_by="M", my_task_id="t-child",
                   parent_task_id=pid, depth=2)

    # -- 这一趟的结局：escalated + 退出码 5（两半都要对）
    assert run.stop_reason == "escalated", (run.stop_reason, run.final)
    assert CLI._run_agent_exit_code(run) == 5, run.stop_reason
    assert "已上报召唤者" in run.final, run.final
    # -- 父的收件箱里真的多了一条，且 need / kind / evidence 三格都在
    got = _escalations(ws, "M")
    assert len(got) == 1, got
    ev = got[0]["escalation"]
    assert ev["need"] == NEED, ev
    assert ev["kind"] == KIND, ev
    assert ev["evidence"] == EVIDENCE, ev
    # 同一条留言的标题/正文也要人能读（模型读的是 `inbox_digest` 那一行）
    assert "上报召唤者" in str(got[0].get("subject") or ""), got[0].get("subject")
    assert NEED in str(got[0].get("body") or ""), got[0].get("body")
    # 发信人是子（不是框架代发），收件人是父的角色
    assert got[0]["from"] == "B" and got[0]["to"] == "M", got[0]
    # -- 可审计的那一条事件也在（"这一趟为什么停在这里"事后答得出来）
    events, _ = AL.SS.read_session(ws, sid=SID)
    esc = [e for e in events if e.get("kind") == "agent_escalation"]
    assert len(esc) == 1 and esc[0]["msg_id"] == got[0]["msg_id"], esc


def test_negative_control_no_inbox_write_means_the_first_criterion_goes_red(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """负控①：把"写 inbox"那一步换成一个只回编号、不落盘的桩 ⇒ 父的 inbox 一条都没有。

    这一条证明 ① 的"父的 inbox 多一条"不是被别的东西带绿的：
    写的那一步被摘掉之后，同一趟运行仍然自称 escalated（这正是最危险的假绿形态），
    而判据在"收件箱里有没有那一条"上当场红。
    """
    import agentflow.agent_loop as ALmod

    st, ws = _ws(tmp_path)
    cond = _cond(st)
    pid = _parent_row(cond)

    def _fake_send(*a: Any, **kw: Any) -> tuple[str, str]:
        return "m9999", ""          # 编号有了，盘上什么都没有

    monkeypatch.setattr(ALmod, "send_message", _fake_send)
    loop, _gw = _loop("B", ws=ws, st=st, cond=cond, registry=_registry(st, cond),
                      replies=[_escalate_reply()])
    run = loop.run("把这条链交给父（桩）", summoned_by="M", my_task_id="t-child",
                   parent_task_id=pid, depth=2)
    # 反真空：它仍然自称上报成功（所以"看返回值"这种判法是抓不住的）
    assert run.stop_reason == "escalated", run.stop_reason
    # 而 ① 的那一条断言在这里红：父的收件箱里一条都没有
    assert _escalations(ws, "M") == [], "写那一步被摘掉之后收件箱竟然还有东西"


# ============================================================ ② 父下一轮读到、读一次即已读


def test_the_parent_reads_it_next_round_and_consumes_it_once(
        tmp_path: pathlib.Path) -> None:
    """正控②：父下一轮读到这一条；读一次即 `mark_delivered` 登记 ⇒ 不会被重复处理。"""
    st, ws = _ws(tmp_path)
    cond = _cond(st)
    pid = _parent_row(cond)
    child, _ = _loop("B", ws=ws, st=st, cond=cond, registry=_registry(st, cond),
                     replies=[_escalate_reply()])
    child.run("把这条链交给父（桩）", summoned_by="M", my_task_id="t-child",
              parent_task_id=pid, depth=2)
    assert _escalations(ws, "M"), "夹具前提：上行已经落进父的收件箱"

    # ---- 父下一轮：它的开场提示词里必须出现这条需求（"读到"= 进上下文）
    parent, p_gw = _loop("M", ws=ws, st=st, cond=cond, registry=_registry(st, cond),
                         replies=['{"final": "收到，派 A 去取全文"}'])
    p_run = parent.run("处理子代理的上报", summoned_by="", my_task_id=pid, depth=1)
    assert NEED in p_gw.prompts[0], "父那一趟的开场提示词里没有这条需求"
    assert "上报召唤者" in p_gw.prompts[0], p_gw.prompts[0][:800]
    assert p_run.stop_reason == "final", p_run.stop_reason
    # ---- 读一次即已读：同一条需求不再 fresh ⇒ 下一轮不会被重复处理
    wake = AL.pending_wake(ws, "M", sid=SID)
    assert wake["checked"] is True and wake["count"] == 0, wake
    again, fresh, _problems = AL.inbox_digest(ws, "M", sid=SID)
    assert fresh == [], f"读过了却仍然是 fresh：{fresh}（同一条需求会被再处理一遍）\n{again}"


def test_negative_control_without_the_consume_mark_the_same_need_comes_back(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """负控②：把 `marked_delivered` 那一步换成 no-op ⇒ 同一需求仍然是 fresh（会被再处理）。

    "已消费"不是装饰：去掉它之后，父每一轮都会把同一条需求当成新的 —— 于是子代理
    报了十次"我要原文"，父就派十次活。判据 `pending_wake(..., count)` 抓的就是这个。
    """
    import agentflow.agent_loop as ALmod

    st, ws = _ws(tmp_path)
    cond = _cond(st)
    pid = _parent_row(cond)
    child, _ = _loop("B", ws=ws, st=st, cond=cond, registry=_registry(st, cond),
                     replies=[_escalate_reply()])
    child.run("把这条链交给父（桩）", summoned_by="M", my_task_id="t-child",
              parent_task_id=pid, depth=2)

    monkeypatch.setattr(ALmod, "mark_delivered",
                        lambda *a, **kw: "")     # 只回"没问题"，一个字节都不记
    parent, p_gw = _loop("M", ws=ws, st=st, cond=cond, registry=_registry(st, cond),
                         replies=['{"final": "收到"}'])
    parent.run("处理子代理的上报", summoned_by="", my_task_id=pid, depth=1)
    assert NEED in p_gw.prompts[0]
    wake = AL.pending_wake(ws, "M", sid=SID)
    assert wake["count"] >= 1, (
        "没有『已消费』标记之后，同一条需求应当仍然是 fresh —— 它却是 0，"
        "那说明这条判据盯不到重复处理")


# ============================================================ ③ 顶层受控拒绝


def _assert_top_level_refusal(ws: pathlib.Path, run: Any, st: Store) -> None:
    """③ 的三条断言（正控与负控同形：负控就是让这三条在同一个夹具上失败）。"""
    assert run.stop_reason == "final", run.stop_reason          # 不许静默以 escalated 收工
    assert _raw_escalations(ws) == [], "顶层调它却写了一行收件箱"
    assert st.rows("statements") == [], "顶层调它却写了 statements"


def test_a_top_level_agent_is_refused_with_not_caller(tmp_path: pathlib.Path) -> None:
    """正控③：M 没有父 ⇒ `not_caller` 受控拒绝，且 statements / inbox 一行不写。"""
    st, ws = _ws(tmp_path)
    cond = _cond(st)
    pid = _parent_row(cond)          # M 自己的顶趟行（父=自己 ⇒ 没有召唤者）
    loop, _gw = _loop("M", ws=ws, st=st, cond=cond, registry=_registry(st, cond),
                      replies=[_escalate_reply(), '{"final": "我自己办"}'])
    run = loop.run("顶层的一趟", summoned_by="", my_task_id=pid, depth=1)

    _assert_top_level_refusal(ws, run, st)
    # 拒绝的理由码要能读出来（模型据此改做法：去 ask_user，而不是再试一次）
    def _is_escalate(step: Any) -> bool:
        # 工具调用这一档的 `shape` 是 `"tool"`（`_decode_shape` 返回 SHAPES 的键），
        # 工具真名在 payload 里 —— 写成 `step.shape == "conductor.escalate"` 会永远不成立。
        return (step.shape == "tool"
                and "conductor.escalate" in json.dumps(step.payload, ensure_ascii=False))

    step = next(s for s in run.steps if _is_escalate(s))
    assert step.result["ok"] is False, step.result
    assert step.result["meta"].get("kind") == "not_caller", step.result["meta"]
    assert step.result["meta"].get("state") == "refused", step.result["meta"]
    assert "没有召唤者" in str(step.result.get("error") or ""), step.result


def test_negative_control_without_the_guard_it_writes_and_stops(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """负控③：把守卫换成"伪造一个父" ⇒ 它照样写、照样以 escalated 收工 ⇒ ③ 那三条全红。

    2026-10-20（业主「上行也必须真过名册」之后）：`escalate` 现在有两道守卫 ——
    `not_caller`（没有父）与名册判据（伪造的那个父不在名册上 ⇒ `not_in_roster`）。
    "去掉守卫"因此要把两道都去掉（只去一道，这条负控会变成"另一道把它拦住了"，
    而那不是这条判据要证明的事）。名册那一格的坏实现就是"无论收件人是谁都返回父"。
    """
    st, ws = _ws(tmp_path)
    cond = _cond(st)
    pid = _parent_row(cond)
    real = CD.Conductor.escalate
    # 伪造一个别的父（顶层 M 的那一行就是它自己 ⇒ 必须换成一条真正的别人）
    forged = _parent_row(cond)

    def _roster_blind(self, **kw: Any) -> dict[str, Any]:
        return {"checked": True, "how": "parent", "refused": "", "error": "",
                "to": str(kw.get("to") or ""), "task_id": str(kw.get("to") or ""),
                "kind": "parent", "name": "", "role": "", "callable": "",
                "candidates": [], "why": "（坏实现：不看名册，一律当父）"}

    def _unguarded(self, **kw: Any):
        # 等价于"去掉 `not_caller` 那一支"：凭空给一个父，守卫就再也命中不了。
        kw["parent_task_id"] = forged
        return real(self, **kw)

    monkeypatch.setattr(CD.Conductor, "_escalation_roster_check", _roster_blind)
    monkeypatch.setattr(CD.Conductor, "escalate", _unguarded)
    loop, _gw = _loop("M", ws=ws, st=st, cond=cond, registry=_registry(st, cond),
                      replies=[_escalate_reply(), '{"final": "我自己办"}'])
    run = loop.run("顶层的一趟", summoned_by="", my_task_id=pid, depth=1)
    # 守卫没了 ⇒ 同一趟运行"成功"了，而且盘上多了一条上行
    assert run.stop_reason == "escalated", run.stop_reason
    assert _raw_escalations(ws), "守卫没了却仍然没写 —— 这条负控没打在守卫上"
    # 于是 ③ 的那三条断言在这里必红（逐条给出，免得"某一半恒真"看不出来）
    with pytest.raises(AssertionError):
        _assert_top_level_refusal(ws, run, st)


# ============================================================ ④ 端到端最小链


def _chain(tmp_path: pathlib.Path) -> tuple[Store, pathlib.Path, dict]:
    """父(M) summon 子(B)、子 escalate、父再 summon 另一个角色(A) —— 全程桩模型。"""
    st, ws = _ws(tmp_path)
    gateways = {
        "M": _Gateway([
            # `task` 在 summon 的顶层（S2「M 只派活」：不点动作时的那件活），
            # 不在 `params` 里 —— 放进 params 会被拒（"派活必须写清是什么活"）。
            '{"summon": {"role": "B", "action": "run_once", "task": "把这条链交给父"}}',
            '{"summon": {"role": "A", "action": "run_once", "task": "取回 lit:0007 全文"}}',
            '{"final": "B 上报的那件事已经派给 A 了"}',
        ]),
        "B": _Gateway([_escalate_reply()]),
        "A": _Gateway(['{"final": "取到了"}']),
    }
    loops = {("B", "run_once"): {"max_steps": 3}, ("A", "run_once"): {"max_steps": 3}}

    def seam_factory(role: str) -> LlmSeam:
        return LlmSeam(role=role, session_root=ws, gateway=gateways.get(role),
                       price=(0.0, 0.0), sid=SID)

    inner = LocalBackend({})
    backend = AL.LlmBackend(inner=inner, loops=loops, session_root=ws,
                            seam_factory=seam_factory, max_steps=3, store=st, sid=SID)
    cond = Conductor(st, backend=backend)
    backend.conductor = cond
    backend.registry = build_registry(store=st, conductor=cond).registry
    return st, ws, {"cond": cond, "gateways": gateways, "backend": backend}


def test_the_whole_chain_parent_child_parent(tmp_path: pathlib.Path) -> None:
    """正控④：父 summon 子 → 子 escalate → 父再 summon 另一个角色，三步的结局都对。"""
    st, ws, ctx = _chain(tmp_path)
    reg = ctx["backend"].registry
    run = AL.run_role("M", "把这条链跑起来（桩）", store=st, registry=reg,
                      conductor=ctx["cond"], seam=LlmSeam(role="M", session_root=ws,
                                                          gateway=ctx["gateways"]["M"],
                                                          price=(0.0, 0.0), sid=SID),
                      session_root=ws, workspace_root=str(ws), sid=SID, from_env=False)
    # 父这一趟自己没停（它是收上行的人，不是发上行的人）⇒ final / 退出码 0
    assert run.stop_reason == "final", (run.stop_reason, run.final)
    assert CLI._run_agent_exit_code(run) == 0, run.stop_reason
    # 父先后派了两件活：先 B（会 escalate），再 A（另一个角色）
    assert len(run.summons) >= 2, run.summons
    # 子那一趟在盘上的结局是 escalated（`agent_run_end` 那一行是权威读数）
    events, _ = AL.SS.read_session(ws, sid=SID)
    ends = [(str(e.get("role")), str(e.get("stop_reason")))
            for e in events if e.get("kind") == "agent_run_end"]
    assert ("B", "escalated") in ends, ends
    # 而它的退出码是 5（同一张表：脚本读得到"这是交出去了"而不是"这趟坏了"）
    assert CLI._run_agent_exit_code(_Run("escalated")) == 5
    # 那条上行确实在 M 的收件箱里（父下一轮会读到它 —— 见 ②）
    assert [m for m in _escalations(ws, "M")], "整条链跑完，M 的收件箱里没有那条上行"


def test_negative_control_without_a_resolved_parent_both_3_and_4_go_red(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """负控④：把 `_resolve_parent` 换成返回空 ⇒ 上行的两条判据同时红。

    逐条说清"红的是哪一半"（三态：不许把"另一条仍然绿"读成"这一条没咬人"）：

    - ④ 红：子那一趟不再以 `escalated` 收工（它连召唤者都没有 ⇒ 受控拒绝），
      整条链的 `stop_reason` / 退出码读数就错了；
    - ① 红：同一条链里"父的收件箱多一条"不成立（下面显式再跑一次 ① 的形态，
      拿到 `stop_reason != "escalated"`）；
    - ③ 仍然绿（它本来就断言"没有父 ⇒ 拒绝"，而这时所有人都"没有父"）——
      这一点必须写在明面上：③ 单独抓不住"父解析坏了"，抓它的是 ① 与 ④。
      把三档都测过一遍才是"这条通道真的依赖 `_resolve_parent`"的读数。
    """
    monkeypatch.setattr(AgentLoop, "_resolve_parent",
                        lambda self, given, summoned_by: ("", "", ""))
    # ---- ① 的形态：一个本该有父的子代理，现在也拿不到父
    st0, ws0 = _ws(tmp_path / "one")
    cond0 = _cond(st0)
    pid0 = _parent_row(cond0)
    child0, _ = _loop("B", ws=ws0, st=st0, cond=cond0, registry=_registry(st0, cond0),
                      replies=[_escalate_reply()])
    run0 = child0.run("把这条链交给父（桩）", summoned_by="M", my_task_id="t-child",
                      parent_task_id=pid0, depth=2)
    assert run0.stop_reason != "escalated", (
        f"`_resolve_parent` 返回空之后，子代理竟然还能上行（{run0.stop_reason}）")
    assert _raw_escalations(ws0) == [], "没有父却写出了上行"

    # ---- ④ 的形态：整条链
    st, ws, ctx = _chain(tmp_path / "chain")
    reg = ctx["backend"].registry
    run = AL.run_role("M", "把这条链跑起来（桩）", store=st, registry=reg,
                      conductor=ctx["cond"], seam=LlmSeam(role="M", session_root=ws,
                                                          gateway=ctx["gateways"]["M"],
                                                          price=(0.0, 0.0), sid=SID),
                      session_root=ws, workspace_root=str(ws), sid=SID, from_env=False)
    events, _ = AL.SS.read_session(ws, sid=SID)
    ends = [(str(e.get("role")), str(e.get("stop_reason")))
            for e in events if e.get("kind") == "agent_run_end"]
    # ④ 的断言在这里红：子那一趟不再是 escalated
    assert ("B", "escalated") not in ends, (
        f"`_resolve_parent` 返回空之后，子仍然以 escalated 收工：{ends}")
    # ④ 的另一半：M 的收件箱里一条上行都没有
    assert [m for m in _escalations(ws, "M")] == [], "没有父却写出了上行"
    # 而父这一趟本身照常收工（父不是发上行的那一方）
    assert run.stop_reason == "final", (run.stop_reason, run.final)


# ============================================================ 口径：escalated 不是"用户停"


def test_escalated_is_not_read_as_a_user_stop(tmp_path: pathlib.Path) -> None:
    """口径：`escalated` 不是用户叫停 —— 落盘上没有停机开关，`_user_stop_reason` 也没给过它。

    为什么值得一条：`EXIT_CODE_BY_STOP` 把"有人叫停"（4）与"它自己停"（5）分成两档，
    而这条界线的机器形态就是"有没有停机开关 / 停意是谁下的"。把 `escalated` 读成
    用户停会让父代理去等一个不存在的人。
    """
    from agentflow import stopctl

    st, ws = _ws(tmp_path)
    cond = _cond(st)
    pid = _parent_row(cond)
    loop, _gw = _loop("B", ws=ws, st=st, cond=cond, registry=_registry(st, cond),
                      replies=[_escalate_reply()])
    run = loop.run("把这条链交给父（桩）", summoned_by="M", my_task_id="t-child",
                   parent_task_id=pid, depth=2)
    assert run.stop_reason == "escalated"
    assert stopctl.read_stop(ws) is None, "上行不是叫停：却留下了一把停机开关"
    # 用户停那一档的两个取值与它不同档（4 vs 5），这条界线在表里逐条登记着
    assert CLI.EXIT_CODE_BY_STOP["stop_file"] == 4
    assert CLI.EXIT_CODE_BY_STOP["force_stop"] == 4
    assert CLI.EXIT_CODE_BY_STOP["escalated"] == 5

# -*- coding: utf-8 -*-
"""业主 2026-10-20：「名册机制必须真正跑通，它是智能体之间唯一的合法沟通方式」。

## 这一份守什么（与 `test_addressing_goes_through_the_roster.py` 的分工）

那份文件守 `message` 的寻址（`_address_of` / `roster_addresses`）—— 那一支由另一条线在改。这一份守其余通道，也就是改前「代理发给代理却不经名册」的那几条：

| # | 通道 | 改前 | 这一份要它变成 |
|---|---|---|---|
| ① | `handoff` / 收工 `notify` | `send_message(to=…)`，名册名也照发（而收件箱按角色收 ⇒ 名册名那条没人读得到） | 名册名 / 绝对编号必须落在名册上；命中 ⇒
投到那个实例的板项 |
| ② | `conductor.escalate` | 直接 `send_message`，信调用方给的 `parent_task_id`（给堂兄弟的编号就写进堂兄弟的收件箱） | 与
`message` 同一条判据（`roster_addresses`），路径上真的过一遍 |
| ③ | `#public` | 「公告栏」与「对话」不分：点名某人下指令照样进角色级收件箱 | 公告栏；点名 + 指令 ⇒ `public_is_not_a_conversation` 受控拒绝 |
| ④ | 名册登记（`summon`） | 只登记父那一侧（子那一侧靠台账换算） | `summon` 之后父与子双向都在 `roster_view` 里，且带绝对编号 |
| ⑤ | 框架通报 / 用户插话 | 本来就通 | 仍然通（反真空：收紧不许把它们一起打死） |

另加一条静态判据：`agent_loop.py` / `conductor.py` 里每一个 `send_message` 调用点都必须在已登记的落点函数里，且框架通道必须显式 `by_framework=True` ——
防止"下一次又长出一条绕过名册的路，而没有东西会红"。每条正控都配一条负控（真跑一遍坏实现，证明同一组断言会红）。
"""
from __future__ import annotations

import ast
import json
import pathlib
from typing import Any, Mapping

import pytest

from agentflow import agent_loop as AL
from agentflow import manuscripts as MS
from agentflow import sessions as SS
from agentflow import userio as U
from agentflow.agent_loop import AgentLoop, LoopRun, PUBLIC, read_interjections, read_messages
from agentflow.conductor import Conductor, LocalBackend
from agentflow.llmseam import LlmSeam
from agentflow.store import Store
from agentflow.tools import build_registry

SID = "talk"
ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "agentflow"

#: 这一条链是四层：`M`（顶层行）→ `A`（祖父）→ `D`（我的父）→ `B`（我）→ `F1`/`F2`。
#: 四层是为了让"祖父"与"父的兄弟"都真的是名册外的具体实例（不是凭空编的编号）。
ME, PARENT, GRANDPARENT = "B", "D", "A"


class _Gate:
    """替身模型（这一份判据不靠它，只有 `run()` 需要它存在）。"""

    spec = type("Spec", (), {"model": "stub", "api_key": "x"})()

    def complete(self, prompt: str, *, scope: str = "", system: str | None = None,
                 **kw: Any) -> Any:
        return type("Reply", (), {"ok": True, "text": json.dumps(
            {"final": "收工", "evidence": []}, ensure_ascii=False),
            "tool_calls": (), "tokens_in": 1, "tokens_out": 1,
            "error_detail": "", "error_kind": ""})()


def _row(cond: Conductor, parent: str, role: str, *, key: str,
         status: str = "done") -> str:
    """在台账里造一行（父/子/祖父/叔伯都由它造；`depth` 按父的深度 + 1）。"""
    prow = cond._task(parent) or {}
    terminal = status not in ("pending", "running")
    return cond._write_new_row({
        "task_id": "", "role": role, "action": "run_once", "called_by": "M",
        "parent_task_id": parent, "depth": int(prow.get("depth") or 1) + 1,
        "input_key": key, "status": status,
        "outcome": "ok" if terminal else None,
        "refusal_reason": None, "instance": "", "detail": f"一个 {role} 实例",
        "error": None, "started_at": "2026-10-20T10:00:00+08:00",
        "ended_at": "2026-10-20T10:05:00+08:00" if terminal else None,
        "tokens": 0, "usd": 0.0, "artifacts": [], "inputs": [],
    }, note=f"start:{role}.run_once")


def _env(tmp_path: pathlib.Path) -> dict[str, Any]:
    """四层链 + 名册（父的名册名记在祖父那一侧）+ 我的两个子 + 一个名册外的叔伯。"""
    ws = tmp_path / "ws"
    st = Store(ws)
    st.init()
    cond = Conductor(st, policy=None, backend=LocalBackend({}))
    reg = build_registry(store=st, conductor=cond).registry
    top = cond.open_top_level_run("M", "顶层这一趟")
    gp = _row(cond, top, GRANDPARENT, key="talk@gp")
    pa = _row(cond, gp, PARENT, key="talk@pa")
    me = _row(cond, pa, ME, key="talk@me")
    f1 = _row(cond, me, "F", key="talk@f1")
    f2 = _row(cond, me, "F", key="talk@f2")
    # 父的兄弟（我的叔伯）：它是我能看见的"名册外"实例 —— 既不是我的父也不是我的子。
    uncle = _row(cond, gp, "E", key="talk@uncle")
    loop = AgentLoop(role=ME, session_root=ws, registry=reg, conductor=cond,
                     seam=LlmSeam(role=ME, session_root=ws, gateway=_Gate(),
                                  price=(0.0, 0.0), sid=SID),
                     store=st, sid=SID, max_steps=2)
    loop.my_task_id = me
    loop.parent_task_id = pa
    loop.parent_role = PARENT
    assert loop.secretary is not None, "这一组判据要的是'名册在手上'那一档"
    sec = loop.secretary
    assert sec.roster_add(owner=gp, role=PARENT, task_id=pa,
                          brief="我那一层的父")["name"] == "D1"
    assert sec.roster_add(owner=me, role="F", task_id=f1, brief="甲那一件")["name"] == "F1"
    assert sec.roster_add(owner=me, role="F", task_id=f2, brief="乙那一件")["name"] == "F2"
    return {"ws": ws, "st": st, "cond": cond, "top": top, "gp": gp, "pa": pa, "me": me,
            "f1": f1, "f2": f2, "uncle": uncle, "loop": loop, "sec": sec}


def _messages(ws: pathlib.Path) -> list[dict[str, Any]]:
    events, _ = SS.read_session(ws, sid=SID)
    return [e for e in events if e.get("kind") == "agent_message"]


def _board(cond: Conductor, task_id: str) -> list[dict[str, Any]]:
    return [dict(r) for r in cond.open_items_of(task_id)]


def _no_side_effects(env: dict[str, Any], nobody: list[str]) -> None:
    assert _messages(env["ws"]) == [], ("一行留言都不许落", _messages(env["ws"]))
    for tid in nobody:
        assert _board(env["cond"], tid) == [], _board(env["cond"], tid)


# ============================================================ ① 名册登记双向、带绝对编号


def _summon_env(tmp_path: pathlib.Path) -> dict[str, Any]:
    """一个真跑 `summon` 的夹具：`M` 名下派一个 `D`（后端真的跑起 D 那一趟）。"""
    ws = tmp_path / "ws"
    st = Store(ws)
    st.init()
    inner = LocalBackend({})

    def seam_factory(role: str) -> LlmSeam:
        return LlmSeam(role=role, session_root=ws, gateway=_Gate(),
                       price=(0.0, 0.0), sid=SID)

    backend = AL.LlmBackend(inner=inner, loops={("D", "run_once"): {"max_steps": 2}},
                            session_root=ws, seam_factory=seam_factory, max_steps=2,
                            store=st, sid=SID)
    cond = Conductor(st, policy=None, backend=backend)
    backend.conductor = cond
    reg = build_registry(store=st, conductor=cond).registry
    backend.registry = reg
    top = cond.open_top_level_run("M", "派活的那一趟")
    loop = AgentLoop(role="M", session_root=ws, registry=reg, conductor=cond,
                     seam=LlmSeam(role="M", session_root=ws, gateway=_Gate(),
                                  price=(0.0, 0.0), sid=SID),
                     store=st, sid=SID, max_steps=2)
    loop.my_task_id = top
    return {"ws": ws, "st": st, "cond": cond, "top": top, "loop": loop,
            "sec": loop.secretary}


def test_a_summon_registers_both_directions_with_absolute_ids(tmp_path: pathlib.Path):
    """判据①：每次 `summon` 之后，父与子双向都能在 `roster_view` 里看到对方 + 绝对编号。

    父那一侧：`rows` 里有这个子，带 `task_id`（绝对编号）与名册名（`D1`，不是角色名）；
    子那一侧：`parent` 那一格带父的 `task_id` 与 `role` —— 「我自己的父是谁」原本一格都没有
    （只活在 `AgentLoop.parent_task_id` 这个内存字段里），于是"给父发一条"只能按角色名发。
    """
    env = _summon_env(tmp_path)
    loop, sec, top = env["loop"], env["sec"], env["top"]
    assert sec is not None, "这一组判据要的是'名册在手上'那一档"
    res = loop._do_summon({"role": "D", "task": "登记 Theorem 1.5"})
    child = str(res.get("task_id") or "")
    assert res.get("ok") is True and child, res
    assert res.get("roster_name") == "D1", res

    # ---- 父那一侧：看得到这个子，且带绝对编号 + 名册名
    parent_view = sec.roster_view(owner=top)
    assert parent_view["checked"] is True, parent_view
    rows = [r for r in parent_view["rows"] if str(r.get("task_id")) == child]
    assert rows, ("父的名册里没有这个子", parent_view["rows"])
    assert rows[0]["name"] == "D1", rows[0]
    assert rows[0]["role"] == "D", rows[0]
    assert rows[0]["status"] in ("running", "idle", "ready"), rows[0]

    # ---- 子那一侧：看得到自己的父（绝对编号 + 角色）
    child_view = sec.roster_view(owner=child)
    assert child_view["checked"] is True, child_view
    parent = child_view["parent"]
    assert parent["checked"] is True, parent
    assert parent["task_id"] == top, parent             # 绝对编号（不是"M"这种角色名）
    assert parent["role"] == "M", parent


def test_negctl_skipping_the_registration_leaves_the_parent_blind(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    """负控①：跳过 `roster_add` ⇒ 父那一侧的名册里根本没有这个子 ⇒ 判据①必红。

    这一条证明"双向可见"不是被台账顺手带绿的：`roster_view(owner=父)` 的 `rows`
    只来自名册文件（`roster_add` 写的那一份），台账里有这一行不算数。
    """
    from agentflow import secretary as SEC

    def skip(self: Any, **kw: Any) -> dict[str, Any]:
        # 坏实现：名字给、名册不写（这正是"登记那一步被跳过"的形态）
        return {"name": "D1", "role": str(kw.get("role")), "task_id": str(kw.get("task_id")),
                "problem": "（坏实现：跳过登记）"}

    monkeypatch.setattr(SEC.Secretary, "roster_add", skip)
    with pytest.raises(AssertionError):
        test_a_summon_registers_both_directions_with_absolute_ids(tmp_path)


# ============================================================ ② handoff：名册名必须落在名册上


def test_a_handoff_to_a_roster_member_lands_on_that_instance(tmp_path: pathlib.Path):
    """判据②（正控）：`handoff` 给父（名册名）与给子（绝对编号）⇒ 落那个实例的板上。

    改前：手稿那一行只认角色（`secretary.handoff_add` 对非角色收件人直接抛
    `ValueError`），而名册名/绝对编号是看不见实例的写法 ⇒ 名册在 handoff 这条路上
    用不上。现在：手稿写解析出的角色（台账的口径不变），通知投那个实例的板项。
    """
    env = _env(tmp_path)
    loop, cond = env["loop"], env["cond"]

    to_parent = loop._do_handoff({"to": "D1", "summary": "交给父", "body": "正文甲"})
    assert to_parent.get("ok") is True, to_parent
    addr = to_parent.get("addressing") or {}
    assert (addr.get("how"), addr.get("delivery")) == ("parent", "roster"), addr
    assert to_parent.get("notify_channel") == "roster", to_parent
    assert MS.rows(env["ws"])[0]["to"] == PARENT, MS.rows(env["ws"])[0]
    items = [r for r in _board(cond, env["pa"]) if str(r.get("kind")) == "message"]
    assert len(items) == 1 and str(items[0]["task_id"]) == str(to_parent["notified"]), (
        "这条通知没有挂在**父那个实例**的板上", _board(cond, env["pa"]))

    to_child = loop._do_handoff({"to": env["f1"], "summary": "交给子", "body": "正文乙"})
    assert to_child.get("ok") is True, to_child
    assert (to_child.get("addressing") or {}).get("kind") == "child", to_child
    assert MS.rows(env["ws"])[1]["to"] == "F", MS.rows(env["ws"])[1]
    assert len([r for r in _board(cond, env["f1"]) if str(r.get("kind")) == "message"]) == 1
    assert len(MS.rows(env["ws"])) == 2, MS.rows(env["ws"])


def test_a_handoff_without_a_collaboration_edge_is_refused(tmp_path: pathlib.Path):
    """判据②（负向）：交给一个没有协作边的角色（G）⇒ 受控拒绝 `not_an_edge`，零写入。

    这是 handoff 上的真漏洞：改前它一条准入判据都没过（`send_message` 直接写进
    角色级收件箱）⇒ 任何角色都能把一份手稿 + 一条通知塞给任何角色。
    现在角色级收件人面由协作边那一份判据（`message_admission`）守着。
    """
    env = _env(tmp_path)
    from agentflow import capabilities as CAP

    assert "G" not in CAP.ALLOWED_EDGES.get(ME, frozenset()), (
        "这条判据要一条**不存在**的边；边表变了就得换一对角色",
        sorted(CAP.ALLOWED_EDGES.get(ME, ())))
    before = len(MS.rows(env["ws"]))
    got = env["loop"]._do_handoff({"to": "G", "summary": "给 G", "body": "正文"})

    assert got.get("ok") is False, got
    assert str(got.get("refused") or "") == "not_an_edge", got
    assert len(MS.rows(env["ws"])) == before, ("受控拒绝却写了手稿", MS.rows(env["ws"]))
    assert _messages(env["ws"]) == [], _messages(env["ws"])


def test_a_handoff_to_an_unregistered_name_is_refused_before_writing(
        tmp_path: pathlib.Path):
    """判据②（负向，受控拒绝的形状）：`to="F9"`（不存在的名册名）⇒ 可读的理由码。

    改前它是 `ValueError: 收件人必须是 [A…] 之一` 被包成"秘书执笔失败"——
    读起来像 bug，而且模型不知道该改成什么。现在它是一条判据：
    `handoff_is_role_addressed` + 指路（要指定实例请用 `message`）。
    """
    env = _env(tmp_path)
    before = len(MS.rows(env["ws"]))
    got = env["loop"]._do_handoff({"to": "F9", "summary": "给谁", "body": "正文"})

    assert got.get("ok") is False, got
    assert str(got.get("refused") or "") == "handoff_is_role_addressed", got
    assert "`message`" in str(got.get("error") or ""), got.get("error")
    assert len(MS.rows(env["ws"])) == before, MS.rows(env["ws"])


def test_negctl_without_the_admission_check_a_stranger_role_gets_the_handoff(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    """负控②：把协作边判据摘掉（一律放行）⇒ G 收到手稿 ⇒ 判据②必红。"""
    env = _env(tmp_path)

    monkeypatch.setattr(AL, "message_admission", lambda role, to, reply_to="": "")
    bad = env["loop"]._do_handoff({"to": "G", "summary": "给 G", "body": "正文"})
    assert bad.get("ok") is True, ("坏实现应当让这一条成功", bad)
    assert len(MS.rows(env["ws"])) == 1, ("坏实现应当写了手稿", MS.rows(env["ws"]))
    with pytest.raises(AssertionError):
        test_a_handoff_without_a_collaboration_edge_is_refused(tmp_path)


# ============================================================ ③ escalate 与 message 同一判据


def _escalate_to_the_parent(env: dict[str, Any]) -> dict[str, Any]:
    """跑一次「上行给名册上的父」，返回 `escalate` 的返回值（正控与负控共用）。"""
    return env["cond"].escalate(need="要 lit:0007 的全文", kind="fetch_fulltext",
                                by=ME, my_task_id=env["me"], parent_task_id=env["pa"],
                                session_root=str(env["ws"]), sid=SID)


def _one_escalation_in_the_parents_inbox(env: dict[str, Any],
                                         got: dict[str, Any]) -> None:
    """判据①的全部断言（正控与负控同形：负控就是让同一组断言在坏实现上失败）。

     2026-10-20 诊断更正（原判据写错在读侧，不是写侧真的重复投递）：
    这一格原先写的是 `inbox = read_messages(...)` 之后 `len(inbox) == 1` ——
    而 `read_messages` 返回的是 `(消息, 问题)` 两元组 ⇒ `len(inbox)` 恒等于 2，
    那个 2 是元组的两格，不是两条留言。盘上的实况（读夹具 + 打点实测）是：
    `conductor.escalate` 里只有一处 `send_message`，一次上行恰好落一条
    `agent_message`；另有一条 `agent_escalation`（可审计留痕，同一个 `msg_id`），
    而 `read_messages` 只认 `kind == "agent_message"` ⇒ 它进不了收件箱。
    所以这里做两件事：① 元组解包；② 写侧与读侧各钉一次（不许只靠读侧的过滤
    去重 —— "一次上行写了两条"必须在盘上的留言条数那一格就红）。
    """
    assert got.get("ok") is True and got.get("state") == "escalated", got
    addr = got.get("addressing") or {}
    assert (addr.get("checked"), addr.get("how")) == (True, "parent"), addr
    assert addr.get("task_id") == env["pa"], addr
    assert got.get("roster_unavailable") is False, got
    # ---- 写侧：父名下的 `agent_message` 恰好一条（不过任何读侧判据，直接数盘上的行）
    landed = [e for e in _messages(env["ws"]) if str(e.get("to")) == PARENT]
    assert len(landed) == 1, ("一次上行在写侧落了不止一条留言", landed)
    assert landed[0].get("msg_id") == got.get("msg_id"), (landed, got)
    # ---- 读侧：父的收件箱里恰好那一条，且带着 `escalation` 结构
    inbox, problems = read_messages(env["ws"], PARENT, sid=SID)
    assert problems == [], problems
    assert len(inbox) == 1 and inbox[0].get("escalation"), inbox


def test_escalate_to_the_parent_goes_through_the_roster(tmp_path: pathlib.Path):
    """判据③（正控）：上行发给名册上的父 ⇒ 成功，且读数里带着名册的判定。"""
    env = _env(tmp_path)
    _one_escalation_in_the_parents_inbox(env, _escalate_to_the_parent(env))


def test_negctl_a_duplicated_escalation_would_be_red(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    """负控①：让一次上行在写侧落两条 ⇒ 判据① 的"恰好一条"必红。

    坏实现刻意做在写侧（把 `send_message` 调两遍），不在读侧按 `msg_id` /
    `to_task_id` 去重 —— 去重只是把读数抹平，"一次上行写两条"这件事还在。
    """
    env = _env(tmp_path)
    real = AL.send_message

    def twice(*a: Any, **kw: Any) -> tuple[str, str]:
        real(*a, **kw)
        return real(*a, **kw)

    monkeypatch.setattr(AL, "send_message", twice)
    got = _escalate_to_the_parent(env)
    assert got.get("ok") is True, ("坏实现应当报成功（否则这条负控抓的是别的东西）", got)
    with pytest.raises(AssertionError):
        _one_escalation_in_the_parents_inbox(env, got)


def test_escalate_to_a_non_parent_is_refused(tmp_path: pathlib.Path):
    """判据③（负向）：把父换成名册外的实例（叔伯 / 祖父）⇒ 拒，一行都不写。

    这正是改前的漏洞：`escalate` 信任调用方给的 `parent_task_id` —— 给它一个
    堂兄弟/叔伯的编号，这条上行就写进了那个人的收件箱（而"上行"应当是给父的）。
    """
    env = _env(tmp_path)
    for wrong, why in ((env["uncle"], "叔伯"), (env["gp"], "祖父")):
        got = env["cond"].escalate(need="要 lit:0007 的全文", kind="fetch_fulltext",
                                   by=ME, my_task_id=env["me"], parent_task_id=wrong,
                                   session_root=str(env["ws"]), sid=SID)
        assert got.get("ok") is False and got.get("state") == "refused", (why, got)
        assert str(got.get("reason") or "") == "not_in_roster", (why, got)
        assert (got.get("addressing") or {}).get("how") == "not_in_roster", (why, got)
    assert _messages(env["ws"]) == [], ("受控拒绝却写了收件箱", _messages(env["ws"]))


def test_escalate_upward_only_refuses_a_child(tmp_path: pathlib.Path):
    """判据③（边界）：把上行发给子（我名册上的 F1）⇒ 拒（`not_upward`），不落盘。

    "上行"是向上的动作；给子发需求应当走 `message`（父 → 子那条下行通道）。
    这一条同时证明：判据不只知道"在不在名册"，还知道"方向对不对"。
    """
    env = _env(tmp_path)
    got = env["cond"].escalate(need="要你把实验跑完", kind="fetch_fulltext",
                               by=ME, my_task_id=env["me"], parent_task_id=env["f1"],
                               session_root=str(env["ws"]), sid=SID)
    assert got.get("ok") is False and str(got.get("reason") or "") == "not_upward", got
    assert _messages(env["ws"]) == [], _messages(env["ws"])


def test_escalate_and_message_share_the_one_criterion(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    """判据③（"同一判据"的机器证明）：把唯一那份判据改成一律拒 ⇒ `escalate` 跟着拒。

    如果 `escalate` 自己另写了一份"是不是我的父"（而不是走 `roster_addresses`），
    那么改这一份判据它不会变红 —— 这一条就是抓那种形态的。
    """
    env = _env(tmp_path)
    calls: list[tuple[str, str]] = []
    real = AL.roster_addresses

    def refuse_all(secretary: Any, *, to: str, owner: str = "", my_task_id: str = "",
                   sender: str = "") -> dict[str, Any]:
        calls.append((str(to), str(owner)))
        got = real(secretary, to=to, owner=owner, my_task_id=my_task_id, sender=sender)
        return {**got, "refused": "not_in_roster", "error": "（探针：一律拒）"}

    monkeypatch.setattr(AL, "roster_addresses", refuse_all)
    got = env["cond"].escalate(need="要 lit:0007 的全文", kind="fetch_fulltext",
                               by=ME, my_task_id=env["me"], parent_task_id=env["pa"],
                               session_root=str(env["ws"]), sid=SID)
    assert calls, "escalate 没调 roster_addresses ⇒ 它走的是另一条路（第二份判据）"
    assert got.get("ok") is False and str(got.get("reason")) == "not_in_roster", got
    assert _messages(env["ws"]) == [], _messages(env["ws"])


def test_negctl_without_the_escalate_gate_the_wrong_parent_gets_it(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    """负控③：把名册那一格换成"一律当父" ⇒ 上行写给叔伯 ⇒ 判据③必红。"""
    env = _env(tmp_path)

    monkeypatch.setattr(
        Conductor, "_escalation_roster_check",
        lambda self, **kw: {"checked": True, "how": "parent", "refused": "", "error": "",
                            "to": str(kw.get("to") or ""), "task_id": str(kw.get("to") or ""),
                            "kind": "parent", "name": "", "role": "", "callable": "",
                            "candidates": [], "why": "（坏实现：不看名册）"})
    got = env["cond"].escalate(need="要 lit:0007 的全文", kind="fetch_fulltext",
                               by=ME, my_task_id=env["me"], parent_task_id=env["uncle"],
                               session_root=str(env["ws"]), sid=SID)
    assert got.get("ok") is True, ("坏实现应当让这条上行成功", got)
    assert _messages(env["ws"]), ("坏实现应当写了收件箱", _messages(env["ws"]))
    with pytest.raises(AssertionError):
        test_escalate_to_a_non_parent_is_refused(tmp_path)


# ============================================================ ④ #public 是公告栏，不是对话


def _public_is_a_bulletin(env: dict[str, Any]) -> None:
    """判据④的三条断言（正控与负控同形：负控就是让它们在同一夹具上失败）。"""
    loop, ws, cond = env["loop"], env["ws"], env["cond"]

    # ① 点名 + 指令 ⇒ 受控拒绝，且一条都不落
    bad = loop._do_message({"to": PUBLIC, "subject": "安排",
                            "body": "F1 请立刻把实验跑完，然后把结果回我"})
    assert bad.get("ok") is False, bad
    assert str(bad.get("refused") or "") == "public_is_not_a_conversation", bad
    assert "公告栏" in str(bad.get("error") or ""), bad.get("error")
    assert _messages(ws) == [], ("公告栏里的指令竟然落盘了", _messages(ws))
    for tid in (env["pa"], env["f1"], env["f2"], env["uncle"]):
        assert _board(cond, tid) == [], ("公告不许开板项", tid, _board(cond, tid))

    # ② 不点名的公告 ⇒ 照发，且记录上标着 `bulletin`（"公告"与"对话"在盘上分得开）
    ok = loop._do_message({"to": PUBLIC, "subject": "本轮口径",
                           "body": "文献已入册；实验按计划推进"})
    assert ok.get("message_sent"), ok
    assert ok.get("board_kind") == "bulletin", ok
    recs = _messages(ws)
    assert len(recs) == 1 and recs[0].get("board_kind") == "bulletin", recs

    # ③ 公告不构成对话：它不进任何人的私聊面（进去的每一条 `channel` 都是 public）；
    #    而名册外的人（叔伯）连公告栏都看不到（可见面 = 发信人的直接子代理）。
    for role, tid in ((PARENT, env["pa"]), ("F", env["f1"])):
        msgs, _ = read_messages(ws, role, sid=SID, parent_task_id=env["me"],
                                parent_role=ME)
        assert [m for m in msgs if str(m.get("channel")) != "public"] == [], (
            role, "公告栏的消息不许出现在私聊面", msgs)
    outsider, _ = read_messages(ws, "E", sid=SID, parent_task_id=env["uncle"],
                                parent_role="E")
    assert outsider == [], ("名册外的人看到了公告栏", outsider)


def test_the_public_channel_is_a_bulletin_not_a_conversation(tmp_path: pathlib.Path):
    """判据④：`#public` 保留为公告栏 —— 点名下指令被拒；不点名的公告标 `bulletin`。"""
    _public_is_a_bulletin(_env(tmp_path))


def test_negctl_without_the_addressee_check_the_directive_is_posted(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    """负控④：把"点名 + 指令"的判据摘掉 ⇒ 那条指令照样发出去 ⇒ 判据④必红。"""
    env = _env(tmp_path)
    monkeypatch.setattr(AgentLoop, "_public_addressee", lambda self, payload: "")
    got = env["loop"]._do_message({"to": PUBLIC, "subject": "安排",
                                   "body": "F1 请立刻把实验跑完，然后把结果回我"})
    assert got.get("message_sent"), ("坏实现应当把这条指令发出去", got)
    with pytest.raises(AssertionError):
        _public_is_a_bulletin(env)


# ============================================================ ⑤ 反真空：框架通报与用户插话


def _a_framework_stop_notice_gets_through(env: dict[str, Any]) -> None:
    """框架通报（`by_framework=True`）点了名、带指令语气⇒ 仍然照发、且全角色可见。

    这一格守的是公告栏判据上的显式豁免：叫停那一路是框架代表主控发的全树通知，
    它必然点名 + 用指令语气（"F1 请立刻收工"）—— 若被"点名 + 指令 ⇒ 受控拒绝"这条
    判据当作"公告栏里的对话"拦下，听不到叫停的子孙会继续烧钱跑实验。豁免的落点是
    `_message_by_channel` 里那一句（判据本体），摘掉它这条就红（负控在同文件里）。
    """
    loop, ws = env["loop"], env["ws"]
    got = loop._do_message({"to": PUBLIC, "subject": "叫停",
                            "body": "F1 请立刻收工，别再跑实验", "by_framework": True})
    assert got.get("message_sent"), ("框架通报被公告栏判据挡住了", got)
    assert got.get("board_kind") == "bulletin", got
    # 可见面：`by_framework=True` ⇒ 连"不是它子代理"的角色也读得到（叫停那一档的形态）
    seen, _ = read_messages(ws, "E", sid=SID, parent_task_id=env["uncle"], parent_role="E")
    assert [m for m in seen if m.get("channel") == "public" and m.get("by_framework")], (
        "框架通报没有按『全角色可见』送到名册外的人手上", seen)


def test_framework_notice_and_user_interjection_still_get_through(tmp_path: pathlib.Path):
    """判据⑤（反真空）：这次收紧不许把框架通报与用户插话一起打死。

    三档各一条：

    - 框架通报（`_emit_settlement`）：这一趟停在终态、模型没写 `notify` ⇒ 框架补一条
    `kind="notice"` 的板项，挂在父的实例名下（收件人由台账解析，不经名册 ——它是框架代为落的一条通报，不是代理在说话）；
    - 框架公告（`by_framework=True`）：全角色可见（叫停那一路的形态），
    即"不是发信人的子代理"也读得到 —— 证明公告栏的可见面判据没被这次收紧改坏；另外它走公告栏判据那一支也不受限（点名 + 指令语气照发，见`_a_framework_stop_notice_gets_through`）；
    - 用户插话：`user → M` 照旧可发可读（插话不是代理间通信）。
    """
    env = _env(tmp_path)
    loop, ws = env["loop"], env["ws"]

    # ① 框架通报：落一条 notice 板项在父名下
    run = LoopRun(role=ME, task="一趟停在终态的活")
    run.stop_reason = "final"
    run.final = ""
    note = loop._emit_settlement(run)
    assert "终态回报已落板" in note, note
    notices = [r for r in _board(env["cond"], env["pa"]) if str(r.get("kind")) == "notice"]
    assert len(notices) == 1, ("父名下没有那条框架通报", _board(env["cond"], env["pa"]))
    assert "没有留下结论" in str(notices[0].get("detail") or notices[0].get("body") or ""), \
        notices[0]

    # ② 框架公告：`by_framework=True` ⇒ 连"不是它子代理"的角色也看得到
    AL.send_message(ws, sender="M", to=PUBLIC, subject="叫停", body="请各自收工",
                    sid=SID, by_framework=True)
    seen, _ = read_messages(ws, "E", sid=SID, parent_task_id=env["uncle"], parent_role="E")
    assert [m for m in seen if m.get("channel") == "public"], (
        "框架公告被公告栏的可见面判据挡住了", seen)
    assert all(m.get("by_framework") for m in seen if m.get("channel") == "public"), seen
    # ②b 同一档走公告栏判据本体：点名 + 指令语气也照发（显式豁免，摘掉就红）
    _a_framework_stop_notice_gets_through(env)

    # ③ 用户插话：照旧可发、可读（且只有 M 收）
    #
    #  2026-10-20 诊断更正：这里原先没给 `sid` ⇒ `send_interjection` 落到缺省会话
    # （`sessions.session_id()`，实测 `20261020`），而读的那一侧拿的是 `SID`（"talk"）
    # ⇒ 读到的永远是空表，与"插话通道坏了"在读数上长得一样。通道本身没坏（写读同一
    # `sid` 就对得上，见 `tests/test_agent_interjection.py`），坏的是这一格的夹具。
    iid, problem = AL.send_interjection(ws, sender=U.USER, subject="注意",
                                        body="先看 lit:0007", sid=SID)
    assert iid and not problem, (iid, problem)
    mine, _ = read_interjections(ws, "M", sid=SID)
    assert [i for i in mine if i.get("interjection_id") == iid], mine
    other, _ = read_interjections(ws, PARENT, sid=SID)
    assert other == [], ("插话漏给了非主控", other)


def test_negctl_without_the_framework_exemption_the_stop_notice_is_refused(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    """负控⑤b：把公告栏判据上的框架豁免摘掉 ⇒ 那条叫停通报被当成"对话"拒掉 ⇒ 红。

    摘的就是判据本体里那一格（`_public_framework_exempt`），不是换个措辞绕过去：
    坏实现下同一条通报拿到 `public_is_not_a_conversation` 的拒信、盘上一行不落。
    """
    env = _env(tmp_path)
    monkeypatch.setattr(AgentLoop, "_public_framework_exempt", lambda self, payload: False)
    got = env["loop"]._do_message({"to": PUBLIC, "subject": "叫停",
                                   "body": "F1 请立刻收工，别再跑实验", "by_framework": True})
    assert str(got.get("refused") or "") == "public_is_not_a_conversation", (
        "坏实现应当把这条框架通报当成『公告栏里的指令』拒掉", got)
    assert _messages(env["ws"]) == [], ("受控拒绝却落了盘", _messages(env["ws"]))
    with pytest.raises(AssertionError):
        _a_framework_stop_notice_gets_through(env)


def test_negctl_a_vacuum_would_be_red(tmp_path: pathlib.Path,
                                      monkeypatch: pytest.MonkeyPatch):
    """负控⑤：把框架通报那一支掐掉 ⇒ 判据⑤立刻红（证明"仍然通"不是恒真）。"""
    env = _env(tmp_path)

    def cut(self, run: LoopRun) -> str:
        return ""      # 坏实现：终态不落任何通报

    monkeypatch.setattr(AgentLoop, "_emit_settlement", cut)
    run = LoopRun(role=ME, task="一趟停在终态的活")
    run.stop_reason = "final"
    assert env["loop"]._emit_settlement(run) == ""
    notices = [r for r in _board(env["cond"], env["pa"]) if str(r.get("kind")) == "notice"]
    assert notices == [], notices
    with pytest.raises(AssertionError):
        test_framework_notice_and_user_interjection_still_get_through(tmp_path)


# ============================================================ ⑥ 静态判据：没有第二条落点


#: `send_message` 的已登记落点（`agent_loop.py`）：函数名 → 它凭什么可以直写。
#: 加一条就是加一条通道 ⇒ 这张表是"这一趟审计过哪些路"的机器形态。
AGENT_LOOP_SEND_SITES: dict[str, str] = {
    "send_message": "本体（def）",
    "_message_by_channel": "公告栏/角色级（公告判据 + 准入判据在这条路上）",
    "_do_handoff": "手稿通知（名册名/编号走 `_handoff_address`，角色名走手稿台账的收件人面）",
    "_request_relay": "请代唤（`_roster_gate`：父的绝对编号 / 主控 M）",
    "ask_parent_for_definitions": "定义报文（同上）",
    "run": "步数上报（`_roster_gate`：父的绝对编号）",
    "selftest": "自检脚本（不跑在运行期）",
}

#: `conductor.py` 里允许直写 `send_message` 的函数。
CONDUCTOR_SEND_SITES: dict[str, str] = {
    "escalate": "上行（`_escalation_roster_check` = `roster_addresses`）",
}


def _send_sites(path: pathlib.Path) -> set[tuple[str, bool]]:
    """某个文件里每个 `send_message(...)` 调用点：`(外层函数名, 是否传了 by_framework=True)`。"""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out: set[tuple[str, bool]] = set()

    class _V(ast.NodeVisitor):
        def __init__(self) -> None:
            self.stack: list[str] = []

        def visit_FunctionDef(self, node: ast.AST) -> None:
            self.stack.append(getattr(node, "name", ""))
            self.generic_visit(node)
            self.stack.pop()

        visit_AsyncFunctionDef = visit_FunctionDef

        def visit_Call(self, node: ast.Call) -> None:
            func = node.func
            name = (func.id if isinstance(func, ast.Name)
                    else func.attr if isinstance(func, ast.Attribute) else "")
            if name == "send_message":
                framework = any(k.arg == "by_framework"
                                and isinstance(k.value, ast.Constant)
                                and k.value.value is True for k in node.keywords)
                out.add((self.stack[-1] if self.stack else "<module>", framework))
            self.generic_visit(node)

    _V().visit(tree)
    return out


def test_every_send_message_call_site_is_a_registered_landing(tmp_path: pathlib.Path):
    """判据⑥：`agent_loop.py` / `conductor.py` 的每个 `send_message` 调用点都已登记。

    为什么这条值得存在：这一轮补的四条缺口（handoff / escalate / relay / 步数上报）
    在改前都是"合法地调用 `send_message`"—— 没有任何东西会红。把一个新的
    绕过点加回来，同样不会有东西会红，除非判据盯着"落点表"本身。

    框架通道（`autonomy.py` / `conductor_tools.py`）另有一条更严的：必须显式
    `by_framework=True`（否则读者分不清"框架通报"与"代理在说话"）。
    """
    agent_loop_sites = {name for name, _fw in _send_sites(SRC / "agent_loop.py")}
    assert "<module>" not in agent_loop_sites, "模块级直写是最短的那条绕过路"
    unexpected = agent_loop_sites - set(AGENT_LOOP_SEND_SITES)
    assert not unexpected, ("这些函数在直写 send_message 而没登记落点："
                            f"{sorted(unexpected)}（加通道就要在审计表里加一行）")
    for must in ("_message_by_channel", "_do_handoff", "_request_relay",
                 "ask_parent_for_definitions", "run"):
        assert must in agent_loop_sites, (must, "已登记的落点不见了：这一支改道了？")

    conductor_sites = {name for name, _fw in _send_sites(SRC / "conductor.py")}
    assert conductor_sites == set(CONDUCTOR_SEND_SITES), (
        "conductor.py 的落点表变了", sorted(conductor_sites))

    for path in (SRC / "autonomy.py", SRC / "tools" / "conductor_tools.py"):
        for name, framework in _send_sites(path):
            assert framework, (path.name, name, "框架通道必须显式 by_framework=True")
    assert agent_loop_sites and conductor_sites and tmp_path  # 反真空：扫到了东西


def test_negctl_a_new_unregistered_send_path_is_flagged(tmp_path: pathlib.Path):
    """负控⑥：捏一个"新绕过点"的文件 ⇒ 判据⑥必红（同一个扫描器）。"""
    fake = tmp_path / "fake_loop.py"
    fake.write_text(
        "def _sneak(self, payload):\n"
        "    return send_message(self.root, sender='B', to='E', subject='s', body='b')\n",
        encoding="utf-8")
    sites = {name for name, _fw in _send_sites(fake)}
    assert sites == {"_sneak"}, sites
    assert sites - set(AGENT_LOOP_SEND_SITES), "没登记的落点应当被判据抓出来"

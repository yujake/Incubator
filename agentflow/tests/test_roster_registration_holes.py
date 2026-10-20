"""名册登记的两个真洞 + 两处地雷 + 「名册写没写」的可审读数（六条判据 + 六条负控）。

## 这一组判据守的是什么

名册（`projects/*/out/roster/*.jsonl`）是"代理之间的通信必须经名册"那条纪律的
**地址面**（父 ＋ 直接子 ＋ 绝对编号）。生产读数：名册一直在写（453 个文件 / 55 个工作区），
但两条路是**静默**的：

1. `summon_many`（`_do_summon_many`）走 `Conductor.run_plan`，**一次登记都没有** ——
   生产读数批量步 1006 次、派出 2822 个子代理，名册只登记 413 个（`p6e`/`p7e`
   那种 108/119 个批量子代理、名册 0 行）；
2. `status=failed` / `cancelled` 的那 29 次既不进名册、也不写 `roster_problem`
   （改前那个 `elif` 只覆盖"没有秘书"）⇒ 守卫的第三态被折平。

外加两处地雷：`_do_handoff` 读 `_gate["candidates"]` 而 `_handoff_address` 的 gate
没有这个键（`KeyError`）；`to="ALL"` 的内部直调**有调用点、全仓没有那个方法的 def**
（⇒ `AttributeError`）。

## 纪律（这几条是判据本身的一部分，别顺手放宽）

- `brief` **不拿 `task` 顶替**（那条放宽业主还没批）⇒ 没给简介的那一项如实报 problem；
- 一条 target 登记失败**不许**带走整批（与单个 summon 的"登记失败不许带走这次派活"同口径）；
- 名册写没写的那一格**不拦门**（只可见），所以它不进 `status`、不产生 blocker。
"""
from __future__ import annotations

import json
import pathlib
from types import SimpleNamespace
from typing import Any

import pytest

from agentflow import closing as CL
from agentflow import secretary as SEC
from agentflow import sessions as SS
from agentflow.agent_loop import AgentLoop
from agentflow.conductor import Conductor, LocalBackend
from agentflow.llmseam import LlmSeam
from agentflow.store import Store
from agentflow.tools import build_registry

SID = "s-roster-holes"
#: 我是顶层主控（`M` 的召唤边覆盖 A–H ⇒ 派活这一层不吃边表）。
MY_ROLE = "M"
CHILD_ROLE = "E"


class _Gate:
    """seam 的替身：这一组判据只碰名册/寻址/读数，不碰模型。"""

    spec = type("Spec", (), {"model": "stub", "api_key": "x"})()

    def complete(self, prompt: str, *, scope: str = "", system: str | None = None,
                 **kw: Any) -> Any:
        return type("Reply", (), {"ok": True, "text": "{}", "tool_calls": (),
                                  "tokens_in": 1, "tokens_out": 1,
                                  "error_detail": "", "error_kind": ""})()


def _row(cond: Conductor, parent: str, role: str, *, key: str,
         status: str = "done") -> str:
    """在台账里造一行（绝对编号是台账分配的，不是这里编的）。"""
    prow = cond._task(parent) or {}
    terminal = status not in ("pending", "running")
    return cond._write_new_row({
        "task_id": "", "role": role, "action": "run_once", "called_by": MY_ROLE,
        "parent_task_id": parent, "depth": int(prow.get("depth") or 1) + 1,
        "input_key": key, "status": status,
        "outcome": "ok" if terminal else None,
        "refusal_reason": None, "instance": "", "detail": f"一个 {role} 实例",
        "error": None, "started_at": "2026-10-19T10:00:00+08:00",
        "ended_at": "2026-10-19T10:05:00+08:00" if terminal else None,
        "tokens": 0, "usd": 0.0, "artifacts": [], "inputs": [],
    }, note=f"start:{role}.run_once")


def _env(tmp_path: pathlib.Path, *, child: bool = False) -> dict[str, Any]:
    """一个工作区 + 一个主控行 + 我这一趟（秘书自动装配）。"""
    ws = tmp_path / "ws"
    st = Store(ws)
    st.init()
    cond = Conductor(st, policy=None, backend=LocalBackend({}))
    reg = build_registry(store=st, conductor=cond).registry
    top = cond.open_top_level_run(MY_ROLE, "顶层这一趟")
    loop = AgentLoop(role=MY_ROLE, session_root=ws, registry=reg, conductor=cond,
                     seam=LlmSeam(role=MY_ROLE, session_root=ws, gateway=_Gate(),
                                  price=(0.0, 0.0), sid=SID),
                     store=st, sid=SID, max_steps=2)
    loop.my_task_id = top
    assert loop.secretary is not None, "这一组判据要的是'名册在手上'那一档"
    env: dict[str, Any] = {"st": st, "ws": ws, "cond": cond, "reg": reg,
                           "loop": loop, "sec": loop.secretary, "me": top}
    if child:
        kid = _row(cond, top, CHILD_ROLE, key="roster@child")
        assert env["sec"].roster_add(owner=top, role=CHILD_ROLE, task_id=kid,
                                     brief="我名下的一个子")["name"] == "E1"
        env["child"] = kid
    return env


def _stub_run_plan(cond: Conductor, parent: str):
    """`Conductor.run_plan` 的替身：**真的**落台账行（绝对编号是真的），不跑模型。

    这一组判据量的是"登记有没有发生"，不是并发引擎；真 `run_plan` 在夹具里
    没有可跑的循环（没派角色自己的 seam）⇒ 会回 `failed`，那会把判据①的
    正控变成"登记失败"而不是"登记发生"。
    """
    n = {"i": 0}

    def run_plan(calls, token=None):
        got = []
        for call in calls:
            n["i"] += 1
            tid = _row(cond, parent, call.role, key=f"sm@{n['i']}")
            got.append(SimpleNamespace(task_id=tid, status="done", outcome="ok",
                                       refusal_reason="", detail="跑完了"))
        return got

    return run_plan


def _roster_rows(ws: pathlib.Path, owner: str) -> list[dict[str, Any]]:
    """盘上那一份名册的 `add` 行（读文件，不读视图 —— 判据要的就是"写没写进去"）。"""
    path = SEC.roster_path(ws, owner)
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def _adds(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [r for r in rows if str(r.get("kind")) == "add"]


# ---------------------------------------------------------------- 判据①（正控与负控共用）

def _every_target_is_registered(out: dict[str, Any], rows: list[dict[str, Any]],
                                targets: list[dict[str, Any]], owner: str) -> None:
    """判据①：派 3 个 target ⇒ 名册里 3 条，每条带**绝对编号**与父的 `owner`。"""
    assert out.get("ok") is True, out
    assert out.get("count") == len(targets), out
    ids = [str(r.get("task_id") or "") for r in out.get("results") or []]
    assert len(ids) == len(targets) and all(ids), out

    adds = _adds(rows)
    # ← 负控（把新加的登记删掉）就红在这一行：改前这里恒为 0。
    assert len(adds) == len(targets), (f"名册里该有 {len(targets)} 条，只有 {len(adds)} 条", rows)
    assert [str(r.get("task_id") or "") for r in adds] == ids, (adds, ids)
    assert all(str(r.get("task_id") or "").startswith("t-") for r in adds), adds
    assert all(str(r.get("owner") or "") == owner for r in adds), (adds, owner)
    names = [str(r.get("name") or "") for r in adds]
    assert names and len(set(names)) == len(names), names
    assert out.get("roster_names") == names, (out.get("roster_names"), names)
    # brief 逐项是**它自己那一句**（不是 `task`，也不是第一个 target 的）
    assert [str(r.get("brief") or "") for r in adds] == \
           [str(t.get("brief") or "") for t in targets], adds
    assert "roster_problems" not in out, out


def test_summon_many_registers_every_accepted_target(tmp_path: pathlib.Path,
                                                     monkeypatch: pytest.MonkeyPatch):
    """判据①：批量派活逐项登记（改前一次都没有）。"""
    env = _env(tmp_path)
    monkeypatch.setattr(env["cond"], "run_plan", _stub_run_plan(env["cond"], env["me"]))
    targets = [{"role": CHILD_ROLE, "task": f"干第 {i} 件", "brief": f"第 {i} 件活"}
               for i in (1, 2, 3)]
    out = env["loop"]._do_summon_many({"targets": targets})
    _every_target_is_registered(out, _roster_rows(env["ws"], env["me"]), targets, env["me"])


def test_negctl_dropping_the_summon_many_registration_is_red(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    """负控①：把新加的登记删掉（`roster_add` 变成空操作）⇒ 判据①必红。

    这是"改前"那一版的形态：`_do_summon_many` 里根本没有 `roster_add(` 这个调用点。
    用 monkeypatch 把那个调用点变成空操作（返回成功、什么都不写）—— 与删掉它等价。
    """
    env = _env(tmp_path)
    monkeypatch.setattr(env["cond"], "run_plan", _stub_run_plan(env["cond"], env["me"]))
    monkeypatch.setattr(SEC.Secretary, "roster_add",
                        lambda self, **kw: {"name": "", "problem": ""})
    targets = [{"role": CHILD_ROLE, "task": f"干第 {i} 件", "brief": f"第 {i} 件活"}
               for i in (1, 2, 3)]
    out = env["loop"]._do_summon_many({"targets": targets})
    assert out.get("ok") is True, out
    with pytest.raises(AssertionError):
        _every_target_is_registered(out, _roster_rows(env["ws"], env["me"]),
                                    targets, env["me"])


# ---------------------------------------------------------------- 判据②

def _one_bad_target_does_not_take_the_batch(out: dict[str, Any],
                                            rows: list[dict[str, Any]]) -> None:
    """判据②：一条 target 登记失败（brief 超长）⇒ 其余照常、读数非空、整批**不失败**。"""
    assert out.get("ok") is True, ("整批不许因为一条登记失败而失败", out)
    assert out.get("count") == 3, out
    ids = [str(r.get("task_id") or "") for r in out.get("results") or []]
    assert len(ids) == 3 and all(ids), out                      # 三项都派了
    adds = _adds(rows)
    assert len(adds) == 2, ("其余两项照常登记", rows)            # ← 一条失败整批拒 ⇒ 这里红
    assert [str(r.get("task_id") or "") for r in adds] == [ids[0], ids[2]], (adds, ids)
    assert out.get("roster_names") == [str(r.get("name") or "") for r in adds], out
    problems = out.get("roster_problems") or []
    assert len(problems) == 1, out
    assert "60" in str(problems[0]), ("超长那句话要原样带出来", problems)


def test_one_failed_registration_does_not_take_the_batch_down(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    """判据②：brief 超长的那一项 ⇒ 只有它没登记，另一项照常登记。"""
    env = _env(tmp_path)
    monkeypatch.setattr(env["cond"], "run_plan", _stub_run_plan(env["cond"], env["me"]))
    targets = [{"role": CHILD_ROLE, "task": "甲", "brief": "甲这一件"},
               {"role": CHILD_ROLE, "task": "乙", "brief": "超" * 61},
               {"role": CHILD_ROLE, "task": "丙", "brief": "丙这一件"}]
    out = env["loop"]._do_summon_many({"targets": targets})
    _one_bad_target_does_not_take_the_batch(out, _roster_rows(env["ws"], env["me"]))


def test_negctl_one_failed_registration_rejecting_the_batch_is_red(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    """负控②：改成"一条失败整批拒"（`if problems: return {ok: False, …}`）⇒ 判据②必红。

    坏实现长什么样：登记走完之后把整批折成失败、一个名字都不留 —— 那是
    "阻塞一条委托比放行更贵"的反面（本仓 L-05e 同族），也正是改前那种"要么全成、
    要么全不成"的形态。
    """
    env = _env(tmp_path)
    monkeypatch.setattr(env["cond"], "run_plan", _stub_run_plan(env["cond"], env["me"]))
    targets = [{"role": CHILD_ROLE, "task": "甲", "brief": "甲这一件"},
               {"role": CHILD_ROLE, "task": "乙", "brief": "超" * 61},
               {"role": CHILD_ROLE, "task": "丙", "brief": "丙这一件"}]
    out = env["loop"]._do_summon_many({"targets": targets})
    rows = _roster_rows(env["ws"], env["me"])
    rejected = {**out, "ok": False, "count": 0, "roster_names": [],
                "error": "这批里有一条登记不上 ⇒ 整批拒"}
    with pytest.raises(AssertionError):
        _one_bad_target_does_not_take_the_batch(rejected, rows)


# ---------------------------------------------------------------- 判据③

def _failed_or_cancelled_is_visible(out: dict[str, Any], status: str) -> None:
    """判据③：`status` 落 `failed`/`cancelled` ⇒ 一条 `roster_problem`（不许静默）。"""
    assert str(out.get("status") or "") == status, out
    problem = str(out.get("roster_problem") or "")
    assert status in problem, ("三态折平了：没跑成也没说一句", out)   # ← 负控就红在这里
    assert "名册" in problem, out


@pytest.mark.parametrize("status", ["failed", "cancelled"])
def test_a_failed_summon_writes_a_roster_problem(tmp_path: pathlib.Path,
                                                 monkeypatch: pytest.MonkeyPatch,
                                                 status: str):
    """判据③：`failed` 与 `cancelled` 两档都要留一句（改前两档都静默，共 29 次）。"""
    env = _env(tmp_path)

    def _not_run(*a, **kw):
        return SimpleNamespace(ok=False, task_id="t-000009", status=status,
                               outcome=status, refusal_reason="boom", detail="炸了",
                               children=[], payload={})

    monkeypatch.setattr(env["cond"], "summon", _not_run)
    out = env["loop"]._do_summon({"role": CHILD_ROLE, "task": "干一件", "brief": "甲"})
    _failed_or_cancelled_is_visible(out, status)


@pytest.mark.parametrize("status", ["failed", "cancelled"])
def test_negctl_a_silent_failed_summon_is_red(status: str):
    """负控③：静默（改前那一版：这一格一个字都没有）⇒ 判据③必红。"""
    silent = {"summoned": CHILD_ROLE, "action": "", "ok": False, "status": status,
              "outcome": status, "detail": "炸了"}
    with pytest.raises(AssertionError):
        _failed_or_cancelled_is_visible(silent, status)


# ---------------------------------------------------------------- 判据④

def _old_candidates_line(gate: dict[str, Any]) -> list[str]:
    """改前那一行**逐字**（`_gate["candidates"]`）：用来证明 key 真的缺。"""
    return gate["candidates"]


def test_a_handoff_to_a_roster_name_does_not_raise_key_error(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    """判据④：手稿到名册名不再 `KeyError`（改前 `_handoff_address` 的 gate 没有 `candidates`）。

    两半都要：
    - 名册成员那一档照常写手稿（不许因为这次改动误伤正路）；
    - 解析不到的名册名 ⇒ 受控拒绝 `handoff_is_role_addressed`，且 `candidates` 是 `[]`。
    负控：对**同一份 gate** 跑改前那一行 ⇒ 必 `KeyError`（证明这个键真的缺）。
    """
    env = _env(tmp_path, child=True)
    loop = env["loop"]

    ok = loop._do_handoff({"to": "E1", "summary": "交接一句", "body": "正文"})
    assert ok.get("ok") is True, ok
    assert str(ok["addressing"].get("how")) == "child", ok["addressing"]
    assert str(ok["addressing"].get("delivery")) == "roster", ok["addressing"]
    assert str(ok.get("to")) == CHILD_ROLE, ok        # 手稿那一行写角色（台账口径）

    seen: dict[str, Any] = {}
    real = AgentLoop._handoff_address

    def spy(self, to):
        addr, gate = real(self, to)
        seen["gate"] = gate
        return addr, gate

    monkeypatch.setattr(AgentLoop, "_handoff_address", spy)
    refused = loop._do_handoff({"to": "NOPE1", "summary": "s"})
    assert refused.get("ok") is False, refused
    assert refused.get("refused") == "handoff_is_role_addressed", refused
    assert refused.get("candidates") == [], refused

    gate = seen["gate"]
    assert gate, ("这一条要的就是'gate 非空'那一档", gate)
    assert "candidates" not in gate, ("这一格本来就没有这个键", gate)
    with pytest.raises(KeyError):          # 负控：改回 `_gate["candidates"]` ⇒ 必红
        _old_candidates_line(gate)


# ---------------------------------------------------------------- 判据⑤

def _all_direct_call_is_refused(out: dict[str, Any]) -> None:
    """判据⑤：`to="ALL"` 的内部直调 ⇒ 受控拒绝（不是 `AttributeError`），且拒信指路。"""
    assert out.get("ok") is False, out
    assert str(out.get("refused") or "") == "broadcast_only", out
    assert "conductor.broadcast" in str(out.get("error") or ""), out
    assert "受控拒绝" in str(out.get("note") or ""), out


def test_a_direct_all_call_is_refused_instead_of_raising(tmp_path: pathlib.Path):
    """判据⑤：两支内部直调都改成受控拒绝（那个按名册逐项开板项的旧实现已删，不许补回）。

    负控（反过来证明）：那个方法真的不存在 ⇒ 改回"调那个方法"必抛 `AttributeError`。
    """
    env = _env(tmp_path)
    loop = env["loop"]
    _all_direct_call_is_refused(loop._do_message({"to": "ALL", "subject": "题", "body": "文"}))
    _all_direct_call_is_refused(
        loop._message_legacy({"subject": "题", "body": "文"}, "ALL", ""))
    # 一条都没发、一个板项都没开（受控拒绝不是"发出去了"）
    events, _bad = SS.read_session(env["ws"], sid=SID)
    assert [e for e in events if e.get("kind") == "agent_message"] == [], events
    # 负控：改回调用不存在的方法 ⇒ AttributeError（这正是改前那一版的形态）
    assert not hasattr(AgentLoop, "_message_my_children")
    with pytest.raises(AttributeError):
        loop._message_my_children({"to": "ALL"})


# ---------------------------------------------------------------- 判据⑥

def _roster_reading_is_visible(rep: CL.ClosingReport) -> None:
    """判据⑥：这一段会话里 `roster_problem` 非空 1 次 ⇒ 读数 1，且 summary 有一句。"""
    got = rep.readings.get("roster_registration") or {}
    assert got.get("checked") is True, got
    assert int(got.get("with_problem") or 0) == 1, ("读数丢了 ⇒ 这一行红", got)
    assert "名册有 1 处没登记" in rep.summary(), rep.summary()
    assert not rep.blockers, ("这一格只可见、不许 fail", [f.to_dict() for f in rep.findings])
    assert "roster_registration" not in rep.status, ("它不是八格之一", rep.status)


def test_the_closing_gate_counts_roster_problems(tmp_path: pathlib.Path,
                                                 monkeypatch: pytest.MonkeyPatch):
    """判据⑥：「名册写没写」可审 —— 一次 `roster_problem` 的运行 ⇒ 读数 1、summary 一句话。

    「一次运行」按真实链路造：用 `_do_summon` 真跑一次派活（`status=failed`）⇒ 它产出的
    那个 `out` 原样当成 `agent_step.result` 落进会话（`run()` 里就是这一行
    `{"kind": "agent_step", …, "result": dict(step_obj.result)}`）⇒ 收工门那一格去数。
    """
    env = _env(tmp_path)
    root = env["st"].root

    def _not_run(*a, **kw):
        return SimpleNamespace(ok=False, task_id="t-000009", status="failed",
                               outcome="failed", refusal_reason="boom", detail="炸了",
                               children=[], payload={})

    monkeypatch.setattr(env["cond"], "summon", _not_run)
    step = env["loop"]._do_summon({"role": CHILD_ROLE, "task": "干一件", "brief": "甲"})
    assert step.get("roster_problem"), step
    SS.append(root, {"kind": "agent_step", "role": MY_ROLE, "index": 1, "shape": "summon",
                     "result": step}, sid=SID)
    SS.append(root, {"kind": "agent_run_end", "role": MY_ROLE, "stop_reason": "final"},
              sid=SID)

    got = CL.roster_registration_reading(root, sid=SID)
    assert got["checked"] is True, got
    assert got["with_problem"] == 1 and got["steps"] == 1, got
    assert got["registered"] == 0, got
    assert str(got["problems"][0]["field"]) == "roster_problem", got["problems"]

    rep = CL.check_closing(env["st"], session_root=root, sid=SID, checks=())
    _roster_reading_is_visible(rep)

    # 负控：把读数删掉（`check_closing` 那一格不再算）⇒ 判据⑥必红
    monkeypatch.setattr(CL, "roster_registration_reading", lambda *a, **k: {})
    rep2 = CL.check_closing(env["st"], session_root=root, sid=SID, checks=())
    with pytest.raises(AssertionError):
        _roster_reading_is_visible(rep2)


def test_the_roster_reading_is_three_state_not_zero(tmp_path: pathlib.Path):
    """判据⑥ 的三态：一步都没有的会话 ⇒ `checked=False`，**不是** 0（"没查成"≠"都写上了"）。"""
    root = tmp_path / "ws"
    root.mkdir()
    SS.append(root, {"kind": "agent_run_end", "role": MY_ROLE, "stop_reason": "final"},
              sid=SID)
    got = CL.roster_registration_reading(root, sid=SID)
    assert got["checked"] is False, got
    assert "没查成" in str(got["reason"]), got
    assert got["with_problem"] == 0, got
    # 没有会话根也一样（不许折成"名册都写上了"）
    none = CL.roster_registration_reading(None, sid=SID)
    assert none["checked"] is False and "没查成" in str(none["reason"]), none

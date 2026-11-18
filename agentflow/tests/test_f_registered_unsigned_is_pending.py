# -*- coding: utf-8 -*-
"""INV7：已登记、还没送 V 的稿必须进「待办」读数（判据 a–e）。

## 现场（`agentflow/temp/inv7/INV7-REPORT.md`，`projects/lp-ball-7` 真机）

F 在 10:02:18 把 `reports/f-proof-000001.md` 登记进盘（`proof_mode=registered`、
正文 sha `ce0f72…`、`v_sign.state=unsigned`），但它从来没有派 V：tasks 里
`role=V` 是 0、`verifications/` 与 `out/vsigns/` 都不存在。

同一拍里两个读数互相打脸：

- `v_sign`：「这一份正文还没有一份能算数的签（state=unsigned）⇒ 派 V 审这一份」；
- `delivery`：`total=0` / `proof_count=0` / `still_unsubmitted=[]` /
  `state=researched_no_output`。

于是 10:07:19 与 10:12:20 两次 `agent_park` 读到 `pending_work=false`：
「挂着等谁且本趟无事可做……这一拍不调模型」。稿在盘上、等待审，而挂机判据
认为没有活 —— 这就是本组判据要钉的那一格。

## 口径

1. delivery 的「成果」不只认 `statements` 行（`statement_id`）：已登记（稿头有
   登记元信息）的证明稿本身就是一份成果。它没有签 ⇒ `state=waiting`（四档之一）、
   `claim=proof_unsigned`、进 `still_unsubmitted` 与 `unfinished`；
2. `proof_count` 的业主口径一个字不改（2026-11-02：「如果某命题无V签，F侧就
   不能声称自己产出了『证明』」）⇒ 未签的不计入 `proof_count`；为此另给
   `proof_output_count`（证明稿份数，含待签）—— 判据 a 钉的是这一格非零，以及
   `draft_count` / `total` 不为零；
3. 挂机判据（`agent_loop._pending_work`）对 F 多一条：名下有「已登记、V 签还没到」
   的稿 ⇒ `busy=True`，且理由逐份点名（判据 b：不许 park）；没有这样的稿时
   挂机照旧（判据 c，负控）；
4. 「派 V」是可执行的动作：`still_unsubmitted` 的每一行带 `next_action`（summon
   形状，`role="V"`、`task` 点手稿路径），并且 `attack.step(product=…)` 的封闭
   参数表现在收 `self_assessment`（F 可以把自己的下一步写进唯一那格留痕；
   判据 f —— 真机 step 5 就是被这道封闭参数表吞掉的）。

## 反真空（判据 e）

把两条读数共用的那一次扫描（`agent_f.pending.scan_registered`）打桩成空 ⇒
a 与 b 必须同时红：如果打桩之后 a 还是绿的，a 测的就不是这次扫描；如果只有 a 红、
b 不红，说明挂机判据读的是另一份口径（两份读数又分家了）。
"""
from __future__ import annotations

import pathlib
import types
from typing import Any, Mapping, Sequence

import pytest

from agentflow import clock as CLK
from agentflow import proofregistry as PR
from agentflow.agent_loop import AgentLoop
from agentflow.conductor import Conductor, LocalBackend
from agentflow.llmseam import LlmSeam
from agentflow.store import Store
from agentflow.tools import build_registry

AT = "2026-11-18T10:02:18+08:00"
SID = "probe-f-pending"
TASK = "已登记未送审的稿必须进待办"


# ---------------------------------------------------------------- 夹具


@pytest.fixture()
def bench():
    """假时钟：挂机那一拍不真睡（与 `test_a_message_breaks_the_wait_any_park` 同法）。"""
    CLK.reset()
    CLK.reset_waits()
    CLK.reset_parked()
    CLK.reset_observed_events()
    CLK.reset_programs()
    fake = CLK.use(CLK.FakeClock(wall="2026-11-18T10:00:00+08:00", monotonic=1000.0))
    try:
        yield fake
    finally:
        CLK.reset()
        CLK.reset_parked()


def _ws(tmp_path: pathlib.Path) -> tuple[Store, Conductor, pathlib.Path]:
    ws = tmp_path / "ws"
    ws.mkdir(parents=True, exist_ok=True)
    st = Store(ws)
    st.init()
    cond = Conductor(st, policy=None, backend=LocalBackend({}))
    build_registry(store=st, conductor=cond, workspace_root=ws)
    return st, cond, ws


def _loop(st: Store, cond: Conductor, ws: pathlib.Path) -> AgentLoop:
    me = cond.open_top_level_run("F", TASK)
    reg = build_registry(store=st, conductor=cond, workspace_root=ws).registry
    return AgentLoop(role="F", session_root=ws, registry=reg, conductor=cond,
                     seam=LlmSeam(role="F", session_root=ws, gateway=None,
                                  price=(0.0, 0.0), sid=SID),
                     store=st, sid=SID, max_steps=4, workspace_root=str(ws),
                     my_task_id=me)


def _child_task(cond: Conductor, parent: str) -> str:
    """名册里一条真任务（`clock.start_timer(wait_for="task:…")` 要能在台账里解析到它）。"""
    return cond._write_new_row({
        "task_id": "", "role": "E", "action": "run_once", "called_by": "F",
        "parent_task_id": parent, "depth": 2, "input_key": "inv7@E",
        "status": "running", "outcome": None, "refusal_reason": None,
        "instance": "", "detail": "夹具子代理", "error": None,
        "started_at": AT, "ended_at": None, "tokens": 0, "usd": 0.0,
        "artifacts": [], "inputs": [],
    }, note="test:child")


def _mailbox(*, msg_ids: Sequence[str] = (), item_ids: Sequence[str] = (),
             wake_ids: Sequence[str] = ()) -> dict[str, Any]:
    return {"msg_ids": list(msg_ids), "item_ids": list(item_ids),
            "wake_ids": list(wake_ids), "children": {"settled": []},
            "messages": [], "items": []}


def _run_obj() -> Any:
    return types.SimpleNamespace(park={}, notes=[], summons=[], messages_sent=[],
                                 steps=[], handed_off=None)


def _write_registered_manuscript(root: pathlib.Path, *, mid: str = "000001",
                                 proposition: str = "证明：中心化引理（夹具）",
                                 body: str = "1. 取 ε>0，按定义逐点验证。（前提）"
                                 ) -> tuple[str, str]:
    """在盘上落一份「已登记」的 F 证明稿（稿头有正文 sha / 版本行 ⇒ `parse_entry` 认）。"""
    rel = f"reports/f-proof-{mid}.md"
    sha = PR.proof_sha(body)
    fp = PR.proposition_fingerprint(proposition)
    text = (
        "# F 的证明手稿：夹具\n\n"
        f"- 计划：0000 · 子目标：s1\n"
        f"- 正文sha：{sha}\n"
        f"- 命题指纹：{fp}\n"
        "- 命题类型：conjecture\n"
        f"- 登记时间：{AT}\n"
        f"- 标签：夹具 {mid}\n"
        f"- 版本：{AT}@{sha}\n\n"
        f"## 命题\n\n{proposition}\n\n"
        f"## 证明\n\n{body}\n\n"
        "## 依赖\n\n（自足证明，空表就是声明。）\n"
    )
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return rel, sha


def _plan(*, rel: str, mid: str, sha: str) -> dict[str, Any]:
    """计划台账里那一行（history 落的是真机 step 8 的形状：有稿号 / 稿路径 / 登记，
    没有 `statement_id` —— 因为 B 的收录要等 V 签之后）。"""
    return {
        "plan_id": "0000", "problem": "夹具：判定这个族", "problem_key": "PK-INV7",
        "rounds": 3, "status": "in_progress", "depth": 0,
        "budget": {"max_rounds": 8, "max_parallel_subgoals": 3,
                   "max_persist_attempts": 1, "max_depth": 1},
        "subgoals": [{"sid": "s2", "text": "夹具子目标", "owner": "F",
                      "status": "in_progress", "evidence_ids": [],
                      "experiment_ids": [], "blocked_reason": "",
                      "attempts": 3, "negation_kind": None}],
        "history": [{
            "round": 3, "sid": "s2", "action": "proof", "outcome": "progress",
            "detail": "手稿登记", "evidence": [], "at": AT,
            "manuscript_id": mid, "manuscript_path": rel,
            "proof_mode": "registered", "proof_registered": True,
            "proof_sha256": sha,
        }],
    }


def _f(st: Store):
    from agentflow.agent_f import AgentF

    f = AgentF(st, config={"workspace_root": str(st.root), "plan_id": "0000"})
    return f


def _assert_pending_is_visible(reading: Mapping[str, Any], *, rel: str) -> None:
    """判据 a 的那组断言（e 的反真空也走它）。"""
    assert reading.get("total") == 1, reading
    assert reading.get("draft_count") == 1, reading
    # 证明稿份数（含待签）不为零 —— 「有成果」这一格不再被读成 0。
    assert reading.get("proof_output_count") == 1, reading
    # 业主口径：无 V 签不许叫「证明」⇒ proof_count 仍为 0（不是本组要改的那一格）。
    assert reading.get("proof_count") == 0, reading
    assert reading.get("state") == "outputs_unsigned", reading
    assert reading.get("legal_stop") is False, reading
    still = [dict(x) for x in (reading.get("still_unsubmitted") or [])]
    assert len(still) == 1, still
    row = still[0]
    assert str(row.get("manuscript") or "") == rel, row
    assert str(row.get("state") or "") == "unsigned", row
    assert row.get("signed") is False, row
    open_rows = [dict(x) for x in (reading.get("unfinished") or [])]
    assert len(open_rows) == 1, open_rows
    assert str(open_rows[0].get("manuscript") or "") == rel, open_rows
    assert str(open_rows[0].get("claim") or "") == "proof_unsigned", open_rows


def _assert_park_is_refused(gate: Mapping[str, Any], *, rel: str) -> None:
    """判据 b 的那组断言：这一拍必须问模型，不许 park/挂机。"""
    assert gate.get("pending_work") is True, gate
    assert gate.get("decision") != "park", gate
    assert gate.get("skip_model") is False, gate
    reason = str(gate.get("reason") or "")
    assert "f-proof" in reason, reason
    assert "送 V" in reason or "派 V" in reason or "未送审" in reason, reason


# ============================================================ a：delivery 读数与 v_sign 一致
def test_a_a_registered_unsigned_manuscript_is_a_pending_output(tmp_path):
    """a 已登记、未签 ⇒ delivery 的 total / still_unsubmitted / state 与 v_sign 一致。

    改前红：`outputs_of(history)` 只认 `statement_id`，这一行没有号（B 收录要等
    V 签之后）⇒ `total=0` / `still_unsubmitted=[]` / `state=researched_no_output`。
    """
    st, _cond, ws = _ws(tmp_path)
    rel, sha = _write_registered_manuscript(ws)
    f = _f(st)
    reading = f.delivery_reading(_plan(rel=rel, mid="000001", sha=sha))
    _assert_pending_is_visible(reading, rel=rel)


# ============================================================ a2：这一轮刚登记的那一份
def test_a2_the_current_round_is_counted_before_history_is_written(tmp_path):
    """a2 真机 step 8 的形状：稿刚登记、history 还没写 ⇒ 这一次返回就要读得到它。

    `_apply_round` 是在把这一轮 history 追加进计划「之前」读交差的；如果只认
    history 里的 `statement_id`，这一拍仍然是 `total=0`（旧口径的第二个入口）。
    """
    st, _cond, ws = _ws(tmp_path)
    rel, sha = _write_registered_manuscript(ws)
    f = _f(st)
    plan = _plan(rel=rel, mid="000001", sha=sha)
    plan["history"] = []
    reading = f._delivery_reading(plan, current={
        "statement_id": "", "manuscript": rel, "manuscript_id": "000001",
        "reading": {"state": "waiting", "label": "待签", "delivered": False,
                    "checked": True, "sha": sha, "why": "这一版没有任何台账行"},
        "round": 3, "subgoal": "s2",
    })
    _assert_pending_is_visible(reading, rel=rel)


# ============================================================ b：存在未送审稿 ⇒ 不许 park
def test_b_park_gate_refuses_to_park_with_a_registered_unsigned_manuscript(tmp_path, bench):
    """b 同一场景 ⇒ `_pending_work` 忙、`_park_gate` 不 park（改前红：park 成功）。

    计时器是必要的夹具：没有 parked waiter 时 `_park_gate` 本来就不会 park，
    那样这一条会假绿。真机那两拍正是「有 parked waiter + 本趟无事可做」。
    """
    st, cond, ws = _ws(tmp_path)
    rel, _sha = _write_registered_manuscript(ws)
    loop = _loop(st, cond, ws)
    child = _child_task(cond, loop.my_task_id)
    CLK.start_timer(ws, wait_for=f"task:{child}", task_id=loop.my_task_id,
                    reason="夹具：挂着等子代理")
    work = loop._pending_work(_mailbox())
    assert work.get("busy") is True, work
    assert "f-proof" in str(work.get("why_text") or ""), work
    assert str((work.get("manuscripts") or {}).get("count") or 0) == "1", work
    gate = loop._park_gate(step=2, run=_run_obj(), mailbox=_mailbox())
    _assert_park_is_refused(gate, rel=rel)


# ============================================================ c：没有未签稿 ⇒ 照旧可以 park
def test_c_without_an_unsigned_manuscript_park_still_works(tmp_path, bench):
    """c 负控：盘上没有未签稿 ⇒ `pending_work=False`、照旧 park（不许把正常挂机堵死）。"""
    st, cond, ws = _ws(tmp_path)
    loop = _loop(st, cond, ws)
    child = _child_task(cond, loop.my_task_id)
    CLK.start_timer(ws, wait_for=f"task:{child}", task_id=loop.my_task_id,
                    reason="夹具：挂着等子代理")
    work = loop._pending_work(_mailbox())
    assert work.get("busy") is False, work
    gate = loop._park_gate(step=2, run=_run_obj(), mailbox=_mailbox())
    assert gate.get("pending_work") is False, gate
    assert gate.get("decision") == "park", gate
    assert gate.get("skip_model") is True, gate


# ============================================================ h：收工门用的是同一份读数
def test_h_the_close_gate_also_sees_the_registered_unsigned_manuscript(tmp_path):
    """h 收工门（`_close_reading`）也走同一份交差读数：它不许把等签的稿读成「无成果」。

    真机 INV7 的第二步风险：即使挂机判据修好了，F 走到轮数用尽那一拍也可能
    `legal_stop=True` 静默收工 —— 那时同样没有任何模型回合去派 V。
    """
    st, _cond, ws = _ws(tmp_path)
    rel, sha = _write_registered_manuscript(ws)
    f = _f(st)
    pid = f.create_plan("夹具：收工门", "PK-INV7-CLOSE", subgoals=[
        {"sid": "s1", "text": "夹具子目标", "owner": "F",
         "testable": "存在反例或有限界"}],
        budget={"max_rounds": 1, "max_parallel_subgoals": 1,
                "max_persist_attempts": 1, "max_depth": 1})["plan_id"]
    row = next(dict(r) for r in st.rows("attack_plans")
               if str(r.get("plan_id")) == str(pid))
    row["history"] = [{
        "round": 1, "sid": "s1", "action": "proof", "outcome": "progress",
        "detail": "手稿登记", "evidence": [], "at": AT,
        "manuscript_id": "000001", "manuscript_path": rel,
        "proof_mode": "registered", "proof_registered": True, "proof_sha256": sha,
    }]
    row["rounds"] = 1
    f._write_plan(row, note="test:inv7-close")
    out = f.step(pid)
    assert str(out.get("action") or "") == "stop", out
    delivery = dict(out.get("delivery") or {})
    assert delivery.get("state") == "outputs_unsigned", delivery
    assert delivery.get("legal_stop") is False, delivery
    still = [dict(x) for x in (delivery.get("still_unsubmitted") or [])]
    assert any(str(x.get("manuscript") or "") == rel for x in still), still
    reason = str(out.get("reason") or "")
    assert "mss:" in reason or rel in reason, reason


# ============================================================ d：下一步有可执行动作
def test_d_the_pending_row_carries_an_actionable_summon(tmp_path):
    """d 待办那一行带 summon 形状的 `next_action`（下一拍模型读到的不是一句散文）。

    真机 step 8 的返回里只有「下一步：派 V 审这一份」这句话，而 F 的 step 5 想把
    同一件事写进 `self_assessment` 又被封闭参数表拒掉 —— 于是计划一条痕都没有。
    这一条要求：读数里有一格能直接当动作执行（`role="V"` + 要审的稿路径）。
    """
    st, _cond, ws = _ws(tmp_path)
    rel, sha = _write_registered_manuscript(ws)
    f = _f(st)
    reading = f.delivery_reading(_plan(rel=rel, mid="000001", sha=sha))
    row = dict((reading.get("still_unsubmitted") or [{}])[0])
    action = dict(row.get("next_action") or {})
    assert str(action.get("tool") or "") == "framework_summon", action
    assert str(action.get("role") or "") == "V", action
    assert rel in str(action.get("task") or ""), action
    assert str(action.get("manuscript") or "") == rel, action


# ============================================================ e：反真空
def test_e_stubbing_the_shared_scan_turns_a_and_b_red(tmp_path, bench, monkeypatch):
    """e 反真空：把共用的那一次扫描打桩回旧口径（扫不到任何登记稿）⇒ a/b 必红。

    打桩之后 a 若还是绿的，a 测的就不是这次扫描；b 若还是绿的，挂机判据读的
    就是另一份口径（两份读数又分家了）。
    """
    st, cond, ws = _ws(tmp_path)
    rel, sha = _write_registered_manuscript(ws)
    f = _f(st)
    loop = _loop(st, cond, ws)
    child = _child_task(cond, loop.my_task_id)
    CLK.start_timer(ws, wait_for=f"task:{child}", task_id=loop.my_task_id,
                    reason="夹具：挂着等子代理")

    from agentflow.agent_f import pending as FP

    monkeypatch.setattr(FP, "scan_registered", lambda _root, **_kw: {
        "checked": True, "rows": [], "problems": [], "why": "打桩：扫不到登记稿"})

    reading = f.delivery_reading(_plan(rel=rel, mid="000001", sha=sha))
    assert reading.get("total") == 0, reading          # 旧口径：没有 statement_id 就是 0
    with pytest.raises(AssertionError):
        _assert_pending_is_visible(reading, rel=rel)

    work = loop._pending_work(_mailbox())
    assert work.get("busy") is False, work
    with pytest.raises(AssertionError):
        assert work.get("busy") is True, work


# ============================================================ f：self_assessment 有入口
def test_f_self_assessment_is_accepted_in_the_handed_product():
    """f 判据 ③：`attack.step(product=…)` 收 `self_assessment`（不再被封闭参数表吞掉）。

    真机 step 5 的原话：`参数错误：出现未声明的参数：['self_assessment']`。
    """
    from agentflow import attackround as AR
    from agentflow.agent_f.core import parse_handed_product

    assert "self_assessment" in (AR.HANDED_PRODUCT_SCHEMA.get("properties") or {}), \
        "交进来的 product 参数面缺 self_assessment"
    got = parse_handed_product({
        "kind": "proof",
        "proposition": "设 f 在 [0,1] 上连续；则 f 在 [0,1] 上一致连续。",
        "steps": [{"text": "取 δ=ε，按定义逐点验证。", "cites": [], "assumption": True}],
        "self_assessment": {
            "comprehensive": "partial", "enough_output": "some_output",
            "partial_output": "partial_output",
            "next_move": "派 V 审 reports/f-proof-000001.md",
            "why": "稿已登记，等签才能交差",
        },
    })
    assert got.get("ok") is True, got
    assert (got.get("product") or {}).get("self_assessment", {}).get(
        "next_move") == "派 V 审 reports/f-proof-000001.md", got


def test_g_the_tool_declaration_exposes_the_new_cell(tmp_path):
    """f 的工具层那一半：`attack.step` 的声明里真的能看到这一格（不是只活在代码里）。"""
    from agentflow.tools import build_registry

    st, _cond, ws = _ws(tmp_path)
    reg = build_registry(store=st, conductor=None, workspace_root=ws).registry
    spec = reg.get("attack.step")
    assert spec is not None, "attack.step 不在工具面上"
    props = dict((spec.params or {}).get("properties") or {})
    product = dict(props.get("product") or {})
    assert "self_assessment" in (product.get("properties") or {}), \
        f"工具声明里看不到 self_assessment：{sorted((product.get('properties') or {}))}"

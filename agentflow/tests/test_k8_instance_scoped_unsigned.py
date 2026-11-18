# -*- coding: utf-8 -*-
"""K8 判据：待签稿 / 挂机 / 待办按实例过滤（业主 2026-11-18「谁写稿，谁就对稿负责」）。

## 缺口（`AUDIT-VD` 已钉）

`agent_f.pending.unsubmitted_reading(producer=role)` 把同族所有稿算进每一趟
同角色实例的「我名下」：两个 F 实例各有一份已登记未签稿时，每一趟都读到 `count=2`
（M 的挂机第 4 条按角色筛待签稿 ⇒ 任何 F 实例都读到 2 —— 别人的稿算自己头上）。
收工自动提交（E）与「已提交」幂等面同样按角色扫全工作区。

## 这一组守什么

a) 两个 F 实例各有一份未签稿 ⇒ 各自读到自己那 1 份（改前红：都读到 2）；
e) `researchpending.pending_reading` 的 `manuscript_unsigned` 给了实例标签就只数
   这个实例的稿（M 不给 ⇒ 仍是工作区级：主控的"我名下"就是全局）；
   没有实例归属的稿进 `unattributed`，不算给任何一个实例；
f) E 的收工自动提交只扫这个实例的稿（`signed_candidates(owner=…)` /
   `auto_submit_for(instance=…)`）；
g) 反真空：把实例过滤打桩掉（`unsubmitted_reading` 丢掉 `owner`）⇒ a 必红
   （两趟又都读到 2）—— 证明 a 的绿是这一处过滤给的，不是别的格子碰巧。

边界：全部 tmp 工作区、假时钟，零真实模型调用、不碰 `projects/`。
"""
from __future__ import annotations

import pathlib
import types
from typing import Any, Mapping

import pytest

from _credential_fixture import issue_credential
from agentflow import artifacts as A
from agentflow import clock as CLK
from agentflow import proofregistry as PR
from agentflow import researchpending as RP
from agentflow.agent_loop import AgentLoop
from agentflow.conductor import Conductor, LocalBackend
from agentflow.llmseam import LlmSeam
from agentflow.store import Store
from agentflow.tools import build_registry

AT = "2026-11-18T10:02:18+08:00"
NOW = "2026-11-18T10:32:18+08:00"
WAIT_SEC = 1800
SID = "probe-k8-instance-scoped"
TASK = "两个 F 各管自己的稿"
BODY = "1. 取 ε>0，按定义逐点验证。（前提）"


@pytest.fixture()
def bench():
    CLK.reset()
    CLK.reset_waits()
    CLK.reset_parked()
    CLK.reset_observed_events()
    CLK.reset_programs()
    fake = CLK.use(CLK.FakeClock(wall=NOW, monotonic=1000.0))
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


def _child_task(cond: Conductor, parent: str, *, instance: str) -> str:
    return cond._write_new_row({
        "task_id": "", "role": "F", "action": "attack", "called_by": "D",
        "parent_task_id": parent, "depth": 2, "input_key": f"f@{instance}",
        "status": "running", "outcome": None, "refusal_reason": None,
        "instance": instance, "detail": "夹具：F 实例", "error": None,
        "started_at": AT, "ended_at": None, "tokens": 0, "usd": 0.0,
        "artifacts": [], "inputs": [],
    }, note="test:k8")


def _loop(st: Store, cond: Conductor, ws: pathlib.Path, *, instance: str,
          task_id: str) -> AgentLoop:
    reg = build_registry(store=st, conductor=cond, workspace_root=ws).registry
    return AgentLoop(role="F", session_root=ws, registry=reg, conductor=cond,
                     seam=LlmSeam(role="F", session_root=ws, gateway=None,
                                  price=(0.0, 0.0), sid=f"{SID}-{instance}"),
                     store=st, sid=f"{SID}-{instance}", max_steps=4,
                     workspace_root=str(ws), my_task_id=task_id,
                     instance=instance)


def _mailbox() -> dict[str, Any]:
    return {"msg_ids": [], "item_ids": [], "wake_ids": [], "children": {"settled": []},
            "messages": [], "items": []}


def _run_obj() -> Any:
    return types.SimpleNamespace(park={}, notes=[], summons=[], messages_sent=[],
                                 steps=[], handed_off=None)


def _write_manuscript(ws: pathlib.Path, *, mid: str, instance: str) -> tuple[str, str]:
    """一份已登记（稿头带元信息）的 f-proof 稿 + 产物台账一行（带实例）。"""
    rel = f"reports/f-proof-{mid}.md"
    body = f"{BODY}（{instance} 的稿）"
    sha = PR.proof_sha(body)
    fp = PR.proposition_fingerprint(f"证明：中心化引理（夹具 {instance}-{mid}）")
    text = "\n".join([
        f"# F 的证明手稿：夹具 {instance}-{mid}", "",
        "- 计划：0000 · 子目标：s1",
        f"- 正文sha：{sha}", f"- 命题指纹：{fp}",
        "- 命题类型：conjecture", f"- 登记时间：{AT}",
        f"- 标签：夹具 {mid}", f"- 版本：{AT}@{sha}", "",
        f"## 命题\n\n证明：中心化引理（夹具 {instance}-{mid}）\n",
        f"## 证明\n\n{body}\n", "## 依赖\n\n（自足证明，空表就是声明。）\n",
    ])
    path = ws / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    A.record(ws, path=rel, producer=f"agent-F-{instance}", kind="f-proof-manuscript",
             task_id="", instance=instance, at=AT, note="test:k8")
    return rel, sha


def _two_instances(tmp_path: pathlib.Path) -> tuple[Store, Conductor, pathlib.Path,
                                                    dict[str, str], dict[str, str]]:
    st, cond, ws = _ws(tmp_path)
    top = cond.open_top_level_run("D", TASK)
    tasks = {"F1": _child_task(cond, top, instance="F1"),
             "F2": _child_task(cond, top, instance="F2")}
    manuscripts = {}
    for inst, mid in (("F1", "000001"), ("F2", "000002")):
        rel, sha = _write_manuscript(ws, mid=mid, instance=inst)
        manuscripts[inst] = rel
    return st, cond, ws, tasks, manuscripts


# ============================================================ a：各自读到自己那 1 份
def test_a_each_f_instance_reads_only_its_own_unsigned_manuscript(tmp_path, bench):
    """a 两个 F 实例各有一份未签稿 ⇒ 各自读到 1（改前红：两个都读到 2）。"""
    st, cond, ws, tasks, manuscripts = _two_instances(tmp_path)
    for inst in ("F1", "F2"):
        loop = _loop(st, cond, ws, instance=inst, task_id=tasks[inst])
        manuscripts_reading = dict(loop._pending_work(_mailbox()).get("manuscripts") or {})
        assert manuscripts_reading.get("checked") is True, manuscripts_reading
        assert int(manuscripts_reading.get("count") or 0) == 1, manuscripts_reading
        assert str(manuscripts_reading.get("owner_instance") or "") == inst, \
            manuscripts_reading
        items = [dict(x) for x in (manuscripts_reading.get("items") or ())]
        assert [str(x.get("manuscript") or "") for x in items] == [manuscripts[inst]], items
        # 挂机判据：第 4 条按实例成立 ⇒ 这一拍不许 park。
        gate = loop._park_gate(step=2, run=_run_obj(), mailbox=_mailbox())
        assert gate.get("pending_work") is True, gate
        assert gate.get("decision") != "park", gate


def test_a_the_unsigned_manuscript_attribution_is_instance_level(tmp_path, bench):
    """a2 归属读数本身：台账的 actor/instance 拆成实例标签，不是折回角色桶。"""
    from agentflow.agent_f import pending as FP

    _st, _cond, ws, _tasks, manuscripts = _two_instances(tmp_path)
    got = dict(FP.manuscript_producer(ws, manuscripts["F1"]))
    assert got.get("producer_role") == "F", got
    assert got.get("producer_instance") == "F1", got
    assert got.get("producer_actor") == "agent-F-F1", got
    assert got.get("instance_source") == "artifacts.instance", got
    # 无实例归属的那一份：不猜一个实例。
    rel = "reports/f-proof-000009.md"
    (ws / rel).write_text("# 稿\n", encoding="utf-8")
    A.record(ws, path=rel, producer="F", kind="f-proof-manuscript", at=AT,
             note="test:k8-old")
    old = dict(FP.manuscript_producer(ws, rel))
    assert old.get("producer_role") == "F", old
    assert old.get("producer_instance") == "", old


# ============================================================ e：M 的读数按实例
def test_e_pending_reading_counts_only_the_scoped_instance(tmp_path, bench):
    """e `manuscript_unsigned` 给了实例 ⇒ 只数它的稿；M 不给 ⇒ 工作区级（2 份）。"""
    st, _cond, _ws_, _tasks, _manuscripts = _two_instances(tmp_path)
    for inst in ("F1", "F2"):
        scoped = RP.pending_reading(st, role="F", instance=inst)
        counts = dict(scoped.get("counts") or {})
        assert int(counts.get("manuscript_unsigned") or 0) == 1, (inst, counts)
        gaps = {str(g.get("code") or ""): g for g in (scoped.get("gaps") or [])}
        assert "manuscript_unsigned" in gaps, gaps
        assert int(gaps["manuscript_unsigned"].get("count") or 0) == 1, gaps
    m_reading = RP.pending_reading(st)                      # M：工作区级
    assert int((m_reading.get("counts") or {}).get("manuscript_unsigned") or 0) == 2, \
        m_reading.get("counts")
    assert "manuscript_unsigned" in {str(g.get("code") or "")
                                     for g in (m_reading.get("gaps") or [])}


def test_e_a_manuscript_without_instance_is_not_counted_for_any_instance(tmp_path, bench):
    """e2 已登记但没有实例归属的稿 ⇒ 谁的 count 都不加，进 `unattributed`。"""
    st, _cond, ws, _tasks, _manuscripts = _two_instances(tmp_path)
    from agentflow.agent_f import pending as FP

    rel = "reports/f-proof-000009.md"
    body = f"{BODY}（无归属）"
    sha = PR.proof_sha(body)
    fp = PR.proposition_fingerprint("证明：无归属的引理")
    (ws / rel).write_text("\n".join([
        "# 无归属的稿", "", f"- 正文sha：{sha}", f"- 命题指纹：{fp}",
        "- 命题类型：conjecture", f"- 登记时间：{AT}", f"- 版本：{AT}@{sha}", "",
        f"## 命题\n\n证明：无归属的引理\n", f"## 证明\n\n{body}\n",
        "## 依赖\n\n（自足证明。）\n"]), encoding="utf-8")
    A.record(ws, path=rel, producer="F", kind="f-proof-manuscript", at=AT,
             note="test:k8-unattributed")
    scoped = dict(FP.unsubmitted_reading(ws, owner="F1", producer="F"))
    assert int(scoped.get("count") or 0) == 1, scoped
    assert [str(x.get("manuscript") or "") for x in scoped["unattributed"]] == [rel], scoped
    m = RP.pending_reading(st)
    assert int((m.get("counts") or {}).get("manuscript_unsigned") or 0) == 3, m.get("counts")
    scoped_pending = RP.pending_reading(st, role="F", instance="F1")
    counts = dict(scoped_pending.get("counts") or {})
    assert int(counts.get("manuscript_unsigned") or 0) == 1, counts
    assert int(counts.get("manuscript_unsigned_unattributed") or 0) == 1, counts


# ============================================================ f：E 的收工自动提交
def test_f_e_autosubmit_only_takes_the_instance_own_signed_manuscript(tmp_path, bench):
    """f 两个 E 实例各一份已签稿：`auto_submit_for(instance=…)` 只提交自己那一份。"""
    from agentflow import manuscriptclosing as MC

    st, cond, ws = _ws(tmp_path)
    top = cond.open_top_level_run("D", TASK)
    rows = {}
    for inst, mid in (("E1", "000001"), ("E2", "000002")):
        rows[inst] = cond._write_new_row({
            "task_id": "", "role": "E", "action": "run_once", "called_by": "D",
            "parent_task_id": top, "depth": 2, "input_key": f"e@{inst}",
            "status": "running", "outcome": None, "refusal_reason": None,
            "instance": inst, "detail": "夹具：E 实例", "error": None,
            "started_at": AT, "ended_at": None, "tokens": 0, "usd": 0.0,
            "artifacts": [], "inputs": [],
        }, note="test:k8-e")
    for inst, mid in (("E1", "000001"), ("E2", "000002")):
        rel = f"reports/e-proof-{mid}.md"
        body = f"{BODY}（{inst} 的稿）"
        text = "\n".join([
            f"# E 的证明手稿：夹具 {inst}", "", f"- 实验号：exp:{mid}",
            f"- 命题：证明：穷举引理（夹具 {inst}）", f"- 命题键：PK-{inst}",
            "- 程序：code/enum.py（sha256 " + "0" * 64 + "）", "",
            f"## 命题\n\n证明：穷举引理（夹具 {inst}）\n",
            f"## 证明\n\n{body}\n", "## 依赖\n\n（自足证明。）\n"])
        path = ws / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        A.record(ws, path=rel, producer=f"agent-E-{inst}", kind="e-proof-manuscript",
                 task_id=rows[inst], instance=inst, at=AT, note="test:k8-e")
        issue_credential(ws, proof_text=body, manuscript=rel, artifact_path=rel)

    mine = MC.auto_submit_for(store=st, root=ws, role="E",
                              families=("e-proof", "e-num"),
                              task_id=rows["E1"], instance="E1", stamp=NOW)
    assert mine.get("checked") is True, mine
    assert mine.get("auto_submitted_count") == 1, mine
    assert [x.get("manuscript_id") for x in mine["auto_submitted"]] == ["000001"], mine
    # F1 那一行拿到记号、F2 那一行一个字节都没多（别人的稿不是我的欠账）。
    by_id = {str(r.get("task_id")): r for r in st.rows("tasks")}
    assert str(by_id[rows["E1"]].get("artifacts") or []), by_id[rows["E1"]]
    assert list(by_id[rows["E2"]].get("artifacts") or []) == [], by_id[rows["E2"]]


# ============================================================ f2：签触发提交的那一行
def test_f2_sign_triggered_submission_never_picks_the_latest_row_of_the_role(tmp_path, bench):
    """f2 EM-07：签晚于收工时，找不到实例归属 ⇒ 受控失败，不写进「该角色最近的一行」。"""
    from agentflow import manuscriptsubmission as MS

    st, cond, ws = _ws(tmp_path)
    top = cond.open_top_level_run("D", TASK)
    rows = []
    for inst in ("", ""):
        rows.append(cond._write_new_row({
            "task_id": "", "role": "F", "action": "attack", "called_by": "D",
            "parent_task_id": top, "depth": 2, "input_key": "f@old",
            "status": "done", "outcome": "ok", "refusal_reason": None,
            "instance": inst, "detail": "夹具：老 F 行（无实例）", "error": None,
            "started_at": AT, "ended_at": AT, "tokens": 0, "usd": 0.0,
            "artifacts": [], "inputs": [],
        }, note="test:k8-f2"))
    rel = "reports/f-proof-000001.md"
    (ws / rel).parent.mkdir(parents=True, exist_ok=True)
    (ws / rel).write_text("# 稿\n", encoding="utf-8")
    row, why = MS._producer_row(store=st, role="F", manuscript=rel)
    assert row is None, row
    assert "不猜" in why and "2 行" in why, why
    # 唯一才认：这个角色只有一行时，「哪一行」不是选择。
    with st.tx("tasks", actor="fixture") as tx:
        tx.delete("tasks", rows[1], note="test:k8-f2")
    only, why2 = MS._producer_row(store=st, role="F", manuscript=rel)
    assert only is not None and str(only.get("task_id")) == rows[0], (only, why2)


# ============================================================ g：反真空
def test_g_dropping_the_instance_filter_turns_a_red(tmp_path, bench, monkeypatch):
    """g 把实例过滤打桩掉（`unsubmitted_reading` 丢掉 `owner`）⇒ a 必红（又都读到 2）。"""
    st, cond, ws, tasks, _manuscripts = _two_instances(tmp_path)
    from agentflow.agent_f import pending as FP

    real = FP.unsubmitted_reading

    def _no_owner(root: Any, **kw: Any) -> dict[str, Any]:
        kw.pop("owner", None)               # 打桩：实例过滤整格摘掉（改前的口径）
        return real(root, **kw)

    monkeypatch.setattr(FP, "unsubmitted_reading", _no_owner)

    counts = {}
    for inst in ("F1", "F2"):
        loop = _loop(st, cond, ws, instance=inst, task_id=tasks[inst])
        counts[inst] = int((loop._pending_work(_mailbox()).get("manuscripts") or {})
                           .get("count") or 0)
    assert counts == {"F1": 2, "F2": 2}, counts   # a 的那条断言在这一档必红
    with pytest.raises(AssertionError):
        for inst in ("F1", "F2"):
            loop = _loop(st, cond, ws, instance=inst, task_id=tasks[inst])
            got = dict(loop._pending_work(_mailbox()).get("manuscripts") or {})
            assert int(got.get("count") or 0) == 1, got

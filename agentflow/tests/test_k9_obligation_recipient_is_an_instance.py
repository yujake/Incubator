# -*- coding: utf-8 -*-
"""K9 判据：义务的收件人是显式实例地址（不再"唯一在飞 / 最近开始"挑一个）。

## 缺口（`AUDIT-VD` + 清单 K9 六条已钉）

- `b-register@` / `b-awake@` 的键与行里都没有收件实例：负责人靠
  `_live_role_task`（唯一才认）或 `_registrar_now`（≥2 趟取最近开始）挑一个。
  真机三种形态都出现过：lp-ball 两条 `parent_task_id=None` 至今没人收 /
  lp-ball-6/7 全挂同一个 B / lp-ball-4 两趟 B 同秒起跑只有"最近开始"的那个能收到。
- `v-resubmit@` 反过来把收件人钉在"送审的那一趟台账号"上：那一趟终态之后没有接手人
  （真机 3 条全 block，挂在已 done 的 t-000049）。

## 这一组守什么

b) 两个 B 在飞时按 `owner` 定向：义务行带收件实例、父是那个实例的在飞台账号，
   唤醒读数也只点名它（改前红：`_registrar_now` 取最近开始的那一趟 B2）；
   没有 owner 时不挑：行上 `instance` 为空（角色地址），两个 B 都读得到、谁也不被
   点名当负责人；
c) `v-resubmit` 的收件人 = 该稿的产出实例（产物台账 `producer`/`instance`），
   且不挂在已终态的台账号上（改前红：挂在已 done 的送审者）；
g) 反真空：把收件实例读数打桩成"永远没有实例" ⇒ b / c 必红。

边界：全部 tmp 工作区、零真实模型调用、不碰 `projects/`。
"""
from __future__ import annotations

import pathlib
from typing import Any, Mapping

import pytest

from agentflow import artifacts as A
from agentflow import obligations as OBL
from agentflow import proofregistry as PR
from agentflow import schema as S
from agentflow.store import Store
from agentflow.tools.conductor_tools import conductor_for

TS = "2026-11-18T10:00:00+08:00"
SID = "000001"
PROOF = "1. 取 ε>0，按定义逐点验证。\n2. 第 1 步只依赖 ε ⇒ 一致连续。"
SHA = PR.proof_sha(PROOF)
REL = f"reports/f-proof-{SID}.md"


def _ws(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    conductor_for(st)
    (pathlib.Path(st.root) / "reports").mkdir(parents=True, exist_ok=True)
    (pathlib.Path(st.root) / REL).write_text(
        f"# 稿\n\n## 命题\n\n夹具命题\n\n## 证明\n\n{PROOF}\n", encoding="utf-8")
    return st


def _task(st: Store, *, role: str, instance: str, started: str,
          status: str = "running", parent: str | None = "t-root") -> str:
    from agentflow.conductor import Conductor

    return Conductor._write_new_row(conductor_for(st), {
        "task_id": "", "role": role, "action": "", "called_by": "M",
        "parent_task_id": parent, "depth": 2, "input_key": f"@t:{role}:{instance}:{started}",
        "status": status, "outcome": "ok" if status == "done" else None,
        "refusal_reason": None, "instance": instance, "detail": "夹具",
        "error": None, "started_at": started,
        "ended_at": started if status == "done" else None,
        "tokens": 0, "usd": 0.0, "artifacts": [], "inputs": [],
    }, note="probe:k9")


def _statement(st: Store, *, sid: str = SID, created_by: str = "secretary-B",
               manuscripts: Mapping[str, str] | None = None) -> None:
    row = {"stmt_id": sid, "origin": "own_result", "kind": "theorem",
           "label": f"夹具 {sid}", "statement_full": "夹具命题",
           "statement_text": "夹具命题", "proof_text": PROOF,
           "proofs": [{"proof_no": 1, "proof_text": PROOF}],
           "evidence_kind": "proof", "status": "active", "quote_verified": None,
           "quote_reason": "夹具：这一条没有可比的全文 ⇒ 还没校验", "created_at": TS,
           "created_by": created_by, "manuscripts": dict(manuscripts or {})}
    with st.tx("statements", actor="test") as tx:
        tx.upsert("statements", row)


def _ledger(st: Store, *, instance: str, role: str = "F", task_id: str = "") -> None:
    A.record(st.root, path=REL, producer=f"agent-{role}-{instance}",
             kind="f-proof-manuscript", task_id=task_id, instance=instance, at=TS,
             note="probe:k9")


def _duty_items(st: Store) -> list[dict[str, Any]]:
    return [dict(r) for r in st.rows("tasks")
            if str(r.get("input_key") or "").startswith(OBL.REGISTER_PREFIX)]


def _resubmit_items(st: Store) -> list[dict[str, Any]]:
    return [dict(r) for r in st.rows("tasks")
            if str(r.get("input_key") or "").startswith("v-resubmit@")]


# ============================================================ b：两个 B 在飞 ⇒ 按 owner 定向
def test_b_two_b_in_flight_only_the_owner_gets_the_duty(tmp_path):
    """b 点名 B1 ⇒ 义务行落在 B1 名下、唤醒读数只点名 B1；B2 收不到。"""
    st = _ws(tmp_path)
    _statement(st)
    b1 = _task(st, role="B", instance="B1", started="2026-11-18T10:00:00+08:00")
    b2 = _task(st, role="B", instance="B2", started="2026-11-18T10:05:00+08:00")
    got = OBL.ensure_registration(
        store=st, root=st.root, label=f"{SID}#p1", proof_sha=SHA,
        manuscript=REL, owner=b1, wake=True)
    assert got["state"] == "opened", got
    item = _duty_items(st)[0]
    assert str(item.get("parent_task_id") or "") == b1, item
    assert str(item.get("instance") or "") == "B1", item
    assert got.get("owner_instance") == "B1", got
    # 唤醒也只点名 B1（改前 `_registrar_now` 会取最近开始的 B2）。
    wake = dict(got.get("wake") or {})
    assert str(wake.get("task_id") or "") == b1, wake
    assert wake.get("state") in ("running", "woken", "attached"), wake
    # B2 的收件箱里没有它。
    assert [r["task_id"] for r in conductor_for(st).open_items_for("B", "B2")] == []
    assert [r["task_id"] for r in conductor_for(st).open_items_for("B", "B1")] == [
        item["task_id"]]


def test_b_without_an_owner_the_duty_is_role_addressed_not_picked(tmp_path):
    """b2 两个 B 在飞而不点名 ⇒ 不挑一趟：行上 instance 为空、两趟都读得到。"""
    st = _ws(tmp_path)
    _statement(st)
    _task(st, role="B", instance="B1", started="2026-11-18T10:00:00+08:00")
    _task(st, role="B", instance="B2", started="2026-11-18T10:05:00+08:00")
    got = OBL.ensure_registration(
        store=st, root=st.root, label=f"{SID}#p1", proof_sha=SHA,
        manuscript=REL, wake=True)
    assert got["state"] == "opened", got
    item = _duty_items(st)[0]
    assert str(item.get("parent_task_id") or "") == "", item
    assert str(item.get("instance") or "") == "", item
    assert got.get("owner_known") is False, got
    assert "不按" in str(got.get("owner_why") or ""), got
    cond = conductor_for(st)
    for inst in ("B1", "B2"):
        assert [r["task_id"] for r in cond.open_items_for("B", inst)] == [item["task_id"]]
    wake = dict(got.get("wake") or {})
    assert wake.get("state") == "role_addressed", wake
    # 「挑一个」的两段已经删掉（不是加分支绕过）。
    assert not hasattr(OBL, "_registrar_now")
    assert not hasattr(OBL, "_live_role_task")


def test_b_the_registrar_instance_is_the_address_when_it_is_known(tmp_path):
    """b3 命题的登记实例写了实例标签 ⇒ 它就是要收这条义务的那个实例。"""
    st = _ws(tmp_path)
    _statement(st, created_by="agent-B-B7")
    b7 = _task(st, role="B", instance="B7", started="2026-11-18T10:00:00+08:00")
    # 另一趟 B 更晚开始：改前它会赢（"最近开始"），现在不会。
    _task(st, role="B", instance="B9", started="2026-11-18T10:09:00+08:00")
    got = OBL.ensure_registration(
        store=st, root=st.root, label=f"{SID}#p1", proof_sha=SHA,
        manuscript=REL, wake=True)
    item = _duty_items(st)[0]
    assert str(item.get("instance") or "") == "B7", item
    assert str(item.get("parent_task_id") or "") == b7, item
    assert got.get("owner_source") == "statements.created_by", got


# ============================================================ c：v-resubmit 的收件人
def test_c_resubmit_goes_to_the_manuscript_producer_instance_not_the_terminal_submitter(tmp_path):
    """c 送审者已 done ⇒ 收件人改成该稿的产出实例（此刻不在飞 ⇒ 只写实例地址）。"""
    st = _ws(tmp_path)
    _statement(st, manuscripts={"1": REL})
    # 产出实例 F1：那两趟都已经终态（真机 lp-ball-8 的形状）。
    _ledger(st, instance="F1")
    f1 = _task(st, role="F", instance="F1", started="2026-11-18T09:00:00+08:00",
               status="done")
    submitter = _task(st, role="F", instance="F1", started="2026-11-18T09:30:00+08:00",
                       status="done")
    got = OBL.ensure_resubmit(
        store=st, root=st.root, label=f"{SID}#p1", verification_id="v-000001",
        detail={"proof_sha256": SHA}, recipient=submitter, role="F", depth=2, at=TS)
    assert got["state"] == "opened", got
    item = _resubmit_items(st)[0]
    # 不挂在已终态的台账号上（改前：parent == 送审者那一趟 done）。
    assert str(item.get("parent_task_id") or "") == "", item
    assert str(item.get("parent_task_id") or "") != submitter, item
    # 收件人是产出实例：地址在行上，且它一出下一趟就被读得到。
    assert str(item.get("instance") or "") == "F1", item
    assert got.get("owner_instance") == "F1", got
    assert got.get("owner_known") is True, got
    live = _task(st, role="F", instance="F1", started="2026-11-18T11:00:00+08:00")
    assert [r["task_id"] for r in conductor_for(st).open_items_of(live)] == [
        item["task_id"]], conductor_for(st).open_items_of(live)
    assert f1  # 两趟旧的终态行都不被当地址


def test_c_resubmit_uses_the_live_task_of_that_instance_when_it_is_running(tmp_path):
    """c2 产出实例此刻在飞 ⇒ 父就是它这一趟（仍在实例地址上，不是"最近开始")."""
    st = _ws(tmp_path)
    _statement(st, manuscripts={"1": REL})
    _ledger(st, instance="F1")
    live = _task(st, role="F", instance="F1", started="2026-11-18T10:00:00+08:00")
    submitter = _task(st, role="F", instance="F2", started="2026-11-18T10:10:00+08:00",
                       status="done")
    got = OBL.ensure_resubmit(
        store=st, root=st.root, label=f"{SID}#p1", verification_id="v-000002",
        detail={"proof_sha256": SHA}, recipient=submitter, role="F", depth=2, at=TS)
    item = _resubmit_items(st)[0]
    assert str(item.get("parent_task_id") or "") == live, item
    assert str(item.get("instance") or "") == "F1", item
    assert str(item.get("parent_task_id") or "") != submitter, item


def test_c_resubmit_uses_the_manuscript_named_by_the_verdict_row(tmp_path):
    """c3 判词行给的稿路径优先（历史打回行的 sha 早不是现行正文了）。"""
    st = _ws(tmp_path)
    _statement(st, manuscripts={"1": REL})
    _ledger(st, instance="F1")
    submitter = _task(st, role="F", instance="F1",
                      started="2026-11-18T09:30:00+08:00", status="done")
    got = OBL.ensure_resubmit(
        store=st, root=st.root, label=f"{SID}#p1", verification_id="v-000009",
        detail={"proof_sha256": SHA, "manuscript": REL},
        recipient=submitter, role="F", depth=2, at=TS)
    item = _resubmit_items(st)[0]
    assert str(item.get("instance") or "") == "F1", item
    assert str(item.get("parent_task_id") or "") == "", item   # 那一趟已 done
    assert got.get("owner_instance") == "F1", got


def test_c_resubmit_never_pins_a_terminal_submitter_even_without_an_instance(tmp_path):
    """c4 认不出产出实例、送审者又已终态 ⇒ 父为空（改前红：父 = 已 done 的那一趟）。"""
    st = _ws(tmp_path)
    _statement(st)                        # 没有 manuscripts 映射 ⇒ 认不出稿
    submitter = _task(st, role="F", instance="F1",
                      started="2026-11-18T09:30:00+08:00", status="done")
    got = OBL.ensure_resubmit(
        store=st, root=st.root, label=f"{SID}#p1", verification_id="v-000010",
        detail={"proof_sha256": SHA}, recipient=submitter, role="F", depth=2, at=TS)
    item = _resubmit_items(st)[0]
    assert str(item.get("parent_task_id") or "") == "", item
    assert str(item.get("instance") or "") == "", item
    assert got.get("owner_known") is False, got
    assert "不在飞" in str(got.get("owner_why") or ""), got


# ============================================================ g：反真空
def test_g_dropping_the_instance_reading_turns_b_and_c_red(tmp_path, monkeypatch):
    """g 把收件实例读数打桩成"永远没有实例" ⇒ b 的定向与 c 的产出实例都红。"""
    # ---- b：没有实例地址 ⇒ 行上不再点名 B1、唤醒也不再点名它。
    st = _ws(tmp_path)
    _statement(st)
    b1 = _task(st, role="B", instance="B1", started="2026-11-18T10:00:00+08:00")
    _task(st, role="B", instance="B2", started="2026-11-18T10:05:00+08:00")
    real = OBL.recipient_reading
    monkeypatch.setattr(OBL, "recipient_reading", lambda *a, **k: {
        "checked": True, "role": "B", "instance": "", "task_id": "",
        "source": "role", "why": "反真空：实例地址读不出来"})
    got = OBL.ensure_registration(
        store=st, root=st.root, label=f"{SID}#p1", proof_sha=SHA,
        manuscript=REL, owner=b1, wake=True)
    item = _duty_items(st)[0]
    with pytest.raises(AssertionError):
        assert str(item.get("parent_task_id") or "") == b1
    with pytest.raises(AssertionError):
        assert str(item.get("instance") or "") == "B1"
    monkeypatch.undo()

    # ---- c：没有产出实例 ⇒ 收件人退回送审者，而那一条已经终态 ⇒ 地址空、实例空。
    st2 = _ws(tmp_path / "c")
    _statement(st2, manuscripts={"1": REL})
    _ledger(st2, instance="F1")
    submitter = _task(st2, role="F", instance="F1",
                      started="2026-11-18T09:30:00+08:00", status="done")
    monkeypatch.setattr(OBL, "_manuscript_owner", lambda *a, **k: {
        "checked": True, "manuscript": REL, "role": "F", "instance": "",
        "why": "反真空：产物归属读不出来"})
    got2 = OBL.ensure_resubmit(
        store=st2, root=st2.root, label=f"{SID}#p1", verification_id="v-000003",
        detail={"proof_sha256": SHA}, recipient=submitter, role="F", depth=2, at=TS)
    item2 = _resubmit_items(st2)[0]
    with pytest.raises(AssertionError):
        assert str(item2.get("instance") or "") == "F1"
    assert got2.get("owner_instance") == "", got2
    monkeypatch.undo()

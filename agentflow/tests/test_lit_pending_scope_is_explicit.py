# -*- coding: utf-8 -*-
"""判据：待裁行的作用域必须显式 —— 判"这一趟清完了没有"的地方都要看得见全表。

## 改前为什么红（VC1 P1-6，真机 `projects/lp-ball-3` 坐实）

2026-11-17 的收工门 blocker 逐字：「待入库文献表非空：还有 30 条 `pending`（跨委托，
不只当前那一份）」。那 30 条落在两个委托上（`r-000006` / `r-000007` 各 15 条），
而：

- `lit.stage_list` 的默认视图与提交闸（`admission_plan` 的 `_judged_gate`）都只取
  "当前委托"（`current_request_id` = 槽位号最大那一行所属的委托）⇒ 旧委托那 15 条
  对它们隐身；
- A 的 `run_once` 只认 `search_requests` 里没 done 的行，而那两条请求全是 `done=true`
  ⇒ 它报 `no_pending_request`，被派来"结清"却什么都没做；
- 收工闸看的是全表，于是一个谁也看不见、谁也清不掉的 blocker。

## 判据（正控 / 反真空）

| # | 判据 | 反真空 |
|---|---|---|
| a | 两个委托各有 pending ⇒ 提交闸与收工闸的读数里都有两者，拒信按委托分组、写明"谁能清" | 把取全表改回"只取当前委托" ⇒ a 必红 |
| b | `run_once` 不给 `request_ids` ⇒ 认领全部有 pending 的委托；逐条判完 + 逐委托提交后全表 pending=0 | 同一条打桩 ⇒ 认领集合只剩当前委托 |

"提交闸"读的是 `litstage.admission_plan(require_judged=True)` 的返回（`lit.admit_all`
与它同一份实现）；"收工闸"读的是 `closing.check_closing(checks=("literature_pending",))`。
"""
from __future__ import annotations

import pytest

from agentflow import closing as CL
from agentflow import litavail as AV
from agentflow import litread as LR
from agentflow import litstage as L
from agentflow.agent_a import AgentA
from agentflow.store import Store
from agentflow.tools import build_for_role

#: 真机那两条委托（槽位号最大的是 B ⇒ 它是"当前委托"，A 是"旧委托"）。
RID_A = "r-000006"
RID_B = "r-000007"


# ====================================================================== 夹具


@pytest.fixture(autouse=True)
def _fresh_readbacks():
    L.reset_readbacks()
    yield
    L.reset_readbacks()


@pytest.fixture
def store(tmp_path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


@pytest.fixture
def reg(store: Store):
    registry = build_for_role("A", store=store, workspace_root=store.root).registry
    registry.bound_role = "A"
    return registry


def _stage(reg, rid: str, titles: list[str], *, doi_prefix: str) -> list[str]:
    entries = [{"title": t, "doi": f"{doi_prefix}/{i}", "provider": "stub",
                "year": 2020 + i, "type_code": "J",
                "relevance": f"与本次检索相关（{t}）"}
               for i, t in enumerate(titles)]
    res = reg.call("lit.stage_add", request_id=rid, entries=entries)
    assert res.ok, res.error
    return [x["slot"] for x in res.unwrap()["staged"]]


def _readback(reg, rid: str) -> None:
    res = reg.call("lit.stage_list", request_id=rid)
    assert res.ok, res.error


def _attempt(store: Store, rid: str, slot: str) -> None:
    """一条"试过、拿不到可读文本"的抽读回执（AR1：零读取尝试不许按仅题录入库）。"""
    AV.record_read(store.root, rid, str(slot), LR.FULLTEXT_EXTRACT_FAILED,
                   source="fixture:no-bytes", note="text.extract.no_text_layer")


def _judge(reg, store: Store, rid: str, slots: list[str]) -> None:
    """判收（`qualified`：不注册、不发号），回执/可读性两张前置证据都补齐。"""
    _readback(reg, rid)
    for slot in slots:
        _attempt(store, rid, slot)
    res = reg.call("lit.admit", request_id=rid, items=[
        {"slot": s, "availability": AV.METADATA_ONLY} for s in slots])
    assert res.ok, res.error


def _submit(reg, rid: str) -> dict:
    res = reg.call("lit.admit_all", request_id=rid)
    assert res.ok, res.error
    return res.unwrap()


def _pending_total(store: Store) -> int:
    """全表 pending 的总数（用改前就有的 `judged_state` 数，判据不依赖被测的新函数）。"""
    return sum(1 for r in store.rows("lit_candidates") if L.judged_state(r) == "pending")


def _agent_a(store: Store) -> AgentA:
    """只跑"认领待裁委托"这一档：不给 provider，也不下载。"""
    return AgentA(store, providers=[], downloader=None,
                  config={"download": False, "lease_seconds": 900, "max_attempts": 3})


def _scope_of_current_only(real, rows) -> dict:
    """反真空：把"全表"缩回"当前委托"（模拟改前那条只取当前委托的取行口径）。"""
    scope = real(rows)
    current = str(scope.get("current_request_id") or "")
    groups = [g for g in scope["by_delegation"] if g["request_id"] == current]
    return {"total": sum(int(g["pending"]) for g in groups),
            "current_request_id": current, "by_delegation": groups}


# ====================================================================== a 看得见两者


def _gate_problems(plan: dict, rids: set[str]) -> list[str]:
    """提交闸的读数里缺了哪些委托（空 = 两者都看得见）。"""
    seen = {str(g.get("request_id")) for g in plan.get("pending_by_delegation") or []}
    return [f"提交闸的读数里没有委托 {rid}" for rid in sorted(rids - seen)]


def _closing_problems(rep: CL.ClosingReport, rids: set[str]) -> list[str]:
    """收工闸的读数与拒信里缺了哪些委托、缺了哪一句"谁能清"。"""
    out: list[str] = []
    reading = rep.readings.get("literature_pending") or {}
    seen = {str(g.get("request_id")) for g in reading.get("by_delegation") or []}
    out += [f"收工闸的读数里没有委托 {rid}" for rid in sorted(rids - seen)]
    detail = " ".join(str(f.detail) for f in rep.blockers if f.check == "literature_pending")
    out += [f"收工闸的拒信里没有委托 {rid}" for rid in sorted(rids) if rid not in detail]
    for needle in ("run_once", "lit.admit_all"):
        if needle not in detail:
            out.append(f"收工闸的拒信没说清谁能清（缺 {needle}）")
    return out


def test_a_both_gates_see_every_delegation_with_pending(store: Store, reg) -> None:
    """a. 两个委托各有 pending ⇒ 提交闸与收工闸都看得见两者（不是只看当前那一个）。"""
    _stage(reg, RID_A, ["Old delegation paper"], doi_prefix="10.21")
    _stage(reg, RID_B, ["Current delegation paper"], doi_prefix="10.22")
    assert _pending_total(store) == 2, _pending_total(store)

    plan = L.admission_plan(store, request_id=RID_B, slots=[], require_judged=True)
    assert plan["ok"] is False and plan["kind"] == "undecided_items", plan
    assert plan["pending_total"] == 2, plan
    assert plan["reason"].count("谁能清") == 1, plan["reason"]
    assert "r-000006" in plan["reason"] and "r-000007" in plan["reason"], plan["reason"]

    rep = CL.check_closing(store, checks=("literature_pending",))
    assert rep.status["literature_pending"] == "fail", rep.to_dict()
    assert rep.closable is False, rep.to_dict()
    assert _gate_problems(plan, {RID_A, RID_B}) == []
    assert _closing_problems(rep, {RID_A, RID_B}) == []


def test_c_reverting_the_scope_to_current_delegation_turns_a_red(
        store: Store, reg, monkeypatch: pytest.MonkeyPatch) -> None:
    """c. 反真空：把"取全表"改回"只取当前委托" ⇒ a 的两条判据都必红。"""
    _stage(reg, RID_A, ["Old delegation paper"], doi_prefix="10.21")
    _stage(reg, RID_B, ["Current delegation paper"], doi_prefix="10.22")
    assert _gate_problems(
        L.admission_plan(store, request_id=RID_B, slots=[], require_judged=True),
        {RID_A, RID_B}) == []

    real = L.pending_all_delegations
    monkeypatch.setattr(L, "pending_all_delegations",
                        lambda rows: _scope_of_current_only(real, rows))
    plan = L.admission_plan(store, request_id=RID_B, slots=[], require_judged=True)
    assert _gate_problems(plan, {RID_A, RID_B}) != [], (
        "把作用域改回当前委托之后提交闸仍看得见旧委托 —— a 不是打在作用域上")
    rep = CL.check_closing(store, checks=("literature_pending",))
    assert _closing_problems(rep, {RID_A, RID_B}) != [], (
        "把作用域改回当前委托之后收工闸的分组读数仍带着旧委托 —— a 是橡皮图章")


# ====================================================================== b run_once 跨委托


def test_b_run_once_claims_every_delegation_with_pending(store: Store, reg) -> None:
    """b. `run_once` 不给 request_ids ⇒ 认领全部有 pending 的委托；结清后全表 pending=0。"""
    _stage(reg, RID_A, ["Old delegation paper"], doi_prefix="10.21")
    _stage(reg, RID_B, ["Current delegation paper"], doi_prefix="10.22")
    slots_a = [str(r["slot"]) for r in store.rows("lit_candidates")
               if str(r.get("request_id")) == RID_A]
    slots_b = [str(r["slot"]) for r in store.rows("lit_candidates")
               if str(r.get("request_id")) == RID_B]

    res = _agent_a(store).run_once()
    assert set(getattr(res, "claimed_delegations", []) or []) == {RID_A, RID_B}, res.to_dict()
    assert res.skipped_reason == "no_pending_request", (
        "认领待裁委托不等于'取到了检索请求'：队列那一格仍要如实说 no_pending_request")
    assert getattr(res, "pending_total", None) == 2, res.to_dict()
    counts = {str(g["request_id"]): int(g["pending"])
              for g in getattr(res, "pending_by_delegation", []) or []}
    assert counts == {RID_A: 1, RID_B: 1}, res.to_dict()
    assert RID_A in res.claim_note and RID_B in res.claim_note, res.claim_note

    # A 照读数逐条判、逐委托提交 ⇒ 全表清空（这就是"结清"那一步）。
    _judge(reg, store, RID_A, slots_a)
    _judge(reg, store, RID_B, slots_b)
    _submit(reg, RID_A)
    _submit(reg, RID_B)
    assert _pending_total(store) == 0, _pending_total(store)


def test_b2_run_once_honours_explicit_request_ids(store: Store, reg) -> None:
    """b 的点名档：给了 request_ids 就只认领点名的那些（不把别的委托一起卷进来）。"""
    _stage(reg, RID_A, ["Old delegation paper"], doi_prefix="10.21")
    _stage(reg, RID_B, ["Current delegation paper"], doi_prefix="10.22")
    res = _agent_a(store).run_once(request_ids=[RID_A])
    assert list(getattr(res, "claimed_delegations", []) or []) == [RID_A], res.to_dict()
    assert {str(g["request_id"]) for g in getattr(res, "pending_by_delegation", []) or []} == {RID_A, RID_B}


def test_c2_reverting_the_scope_drops_the_old_delegation_from_run_once(
        store: Store, reg, monkeypatch: pytest.MonkeyPatch) -> None:
    """c 的第二半：作用域改回当前委托 ⇒ `run_once` 只认领当前那一份（b 必红）。"""
    _stage(reg, RID_A, ["Old delegation paper"], doi_prefix="10.21")
    _stage(reg, RID_B, ["Current delegation paper"], doi_prefix="10.22")
    first = _agent_a(store).run_once()
    assert set(getattr(first, "claimed_delegations", []) or []) == {RID_A, RID_B}

    real = L.pending_all_delegations
    monkeypatch.setattr(L, "pending_all_delegations",
                        lambda rows: _scope_of_current_only(real, rows))
    res = _agent_a(store).run_once()
    assert set(getattr(res, "claimed_delegations", []) or []) != {RID_A, RID_B}, (
        "把作用域改回当前委托之后 run_once 仍认领了两个委托 —— b 不是打在作用域上")
    assert list(getattr(res, "claimed_delegations", []) or []) == [RID_B], res.to_dict()

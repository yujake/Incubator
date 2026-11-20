# -*- coding: utf-8 -*-
"""「提交粒度是批次，不是整委托」（2026-11-17，FX3·甲）。

## 现场（真机 `projects/lp-ball-4`，A 的 final 逐字节选）

> 「② lit.admit_all 的整批门要求该委托 15 个槽全部落定，我没有为 105 个槽
> 逐条花调用的预算」

旧语义：提交闸独占「委托」粒度 —— 15 个槽要么全判完，要么一条都不能交。于是 105 个
槽全 pending、收工闸 `literature_pending` 必红，而 A 明明已经能判出其中几条。

## 改法（只改作用域，不放宽判据）

- 提交时点名 `slots`（"这一次提交覆盖哪些槽"）；不给 = 已判定的全部；
- 闸只要求这一批内全判（`_judged_gate` 的 `undecided` 只看这一批）；
- 未判的槽保持 `pending`、不打 `cleared_at`，进下一批；收工闸仍看全表；
- 报告 / 快照按"这一包提交"落；带号定稿只收已提交过的行（不含未判 pending）。

## 判据

| 判据 | 它要证明的事 |
|---|---|
| a 15 槽判完 5 槽 ⇒ 默认提交那 5 槽 | `registered == 5`、带号定稿只含 5 条、其余 10 条仍 pending 且读数可见；收工闸仍红 |
| a′ 下一批 | 判完剩下 10 槽（判拒即可）再提交 ⇒ 5 入 + 10 拒、全表清完、收工闸 pass、再提交 `already_settled` |
| b 点了未判的槽 | 整批受控拒 `undecided_items`、一条都不注册，那 5 条仍停在 `qualified` |
| c 反真空 | 把"按批"改回"整委托"（`submission_slots` 返回全部槽）⇒ a 必红 |

反真空为什么打在 `submission_slots` 上：它是"这一次提交覆盖哪些槽"的唯一实现点
（`admit_all` 与 `admission_plan` 都从它取作用域）；把它改回整委托，就是改回旧语义。
"""
from __future__ import annotations

import pathlib

import pytest

from agentflow import closing as CL
from agentflow import litavail as AV
from agentflow import litread as LR
from agentflow import litstage as L
from agentflow.store import Store
from agentflow.tools import build_for_role

RID = "r-000001"
N_TOTAL = 15
N_FIRST = 5


# ====================================================================== 夹具


@pytest.fixture(autouse=True)
def _fresh_readbacks():
    L.reset_readbacks()
    yield
    L.reset_readbacks()


@pytest.fixture
def store(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


@pytest.fixture
def reg(store: Store):
    registry = build_for_role("A", store=store, workspace_root=store.root).registry
    registry.bound_role = "A"
    return registry


def _stage(reg, n: int = N_TOTAL) -> list[str]:
    entries = [{"title": f"Batch paper {i:02d}", "doi": f"10.77/{i}", "provider": "stub",
                "year": 2020 + i, "type_code": "J",
                "relevance": f"与本次检索相关（第 {i} 条）"} for i in range(n)]
    res = reg.call("lit.stage_add", request_id=RID, entries=entries)
    assert res.ok, res.error
    return [str(x["slot"]) for x in res.unwrap()["staged"]]


def _judge(reg, store: Store, slots: list[str]) -> None:
    """判收这一批（`qualified`：不注册、不发号）；回执 + 回读 + 正文三张前置证据都补齐。

    2026-11-20（ALITCONTENT）：没有正文的候选已经不许判收，所以"前置证据"从
    `metadata_only` + 一条抽取尝试回执换成 `conftest.lit_availability` 造的
    `readable`（抽读回执 + 版本 + `fs.read` 观察 + 真正文）。这一份测的是批次粒度，
    不是"哪些档能入"（后者由 `tests/test_a_admit_needs_read_content.py` 守）。
    """
    from conftest import lit_availability

    assert reg.call("lit.stage_list", request_id=RID).ok
    lit_availability(store, RID, slots)
    res = reg.call("lit.admit", request_id=RID, items=[
        {"slot": s, "availability": AV.READABLE} for s in slots])
    assert res.ok, res.error


def _rows(store: Store) -> dict[str, dict]:
    return {str(r["slot"]): dict(r) for r in store.rows("lit_candidates")
            if str(r.get("request_id")) == RID}


def _final_text(store: Store) -> str:
    return (store.root / "reports" / f"lit-{RID}.md").read_text(encoding="utf-8")


def _closing(store: Store):
    return CL.check_closing(store, checks=("literature_pending",))


# ====================================================================== a 按批提交


def test_a_five_of_fifteen_can_be_submitted(store: Store, reg) -> None:
    """a. 15 槽里判完 5 槽 ⇒ 不点名也能只交这 5 槽；其余 10 槽仍 pending 且看得见。"""
    slots = _stage(reg)
    first, rest = slots[:N_FIRST], slots[N_FIRST:]
    _judge(reg, store, first)

    got = reg.call("lit.admit_all", request_id=RID)
    assert got.ok, ("判完 5 槽却一条都交不了 ⇒ 提交粒度还是整委托", got.error)
    data = got.unwrap()
    assert data["registered"] == N_FIRST, data
    assert data["submitted"] == first, data["submitted"]
    assert [x["slot"] for x in data["admitted"]] == first, data["admitted"]
    # 其余 10 槽还在：全表读数与逐槽状态都看得见。
    assert data["pending_total"] == len(rest), data
    assert [g["pending"] for g in data["pending_by_delegation"] if g["request_id"] == RID] \
        == [len(rest)], data["pending_by_delegation"]

    rows = _rows(store)
    for slot in first:
        assert rows[slot]["status"] == "admitted" and rows[slot]["lit_id"], rows[slot]
        assert rows[slot]["cleared_at"], rows[slot]
    for slot in rest:
        assert rows[slot]["status"] == "pending" and not rows[slot]["cleared_at"], rows[slot]

    listing = reg.call("lit.stage_list", request_id=RID).unwrap()
    assert listing["counts"]["pending"] == len(rest), listing["counts"]
    assert listing["counts"]["admitted"] == N_FIRST, listing["counts"]

    # 带号定稿只覆盖已判的那部分：5 条带号、未判的 10 条不在报告里。
    final = _final_text(store)
    assert "## 已入库（5 篇）" in final, final
    assert L.report_violations(final, phase="final") == [], L.report_violations(final)
    for slot in first:
        assert f"`lit:{rows[slot]['lit_id']}`" in final, final
    for slot in rest:
        assert rows[slot]["title"] not in final, (
            "未判的槽被写进了定稿 ⇒ 定稿不是'只覆盖已判的那部分'", final)

    # 收工闸仍看全表：还有 10 条 pending ⇒ 红（批次提交不是收工）。
    rep = _closing(store)
    assert rep.status["literature_pending"] == "fail", rep.to_dict()
    assert [f.code for f in rep.blockers] == ["undecided_candidates"], rep.to_dict()

    # ---- a′ 下一批：剩下 10 条判拒，再提交 ⇒ 全表清完、收工放行 -------------
    for slot in rest:
        rej = reg.call("lit.stage_reject", slot=slot, reason_code="rejected_off_topic",
                       note="与本次检索方向无关")
        assert rej.ok, rej.error
    second = reg.call("lit.admit_all", request_id=RID)
    assert second.ok, second.error
    assert second.unwrap()["registered"] == 0, second.unwrap()
    rows = _rows(store)
    assert all(r["cleared_at"] for r in rows.values()), rows
    assert not [r for r in rows.values() if r["status"] == "pending"], rows
    rep = _closing(store)
    assert rep.status["literature_pending"] == "pass", rep.to_dict()
    final = _final_text(store)
    assert "## 已入库（5 篇）" in final and "## 未入库（10 篇）" in final, final

    # 整份委托清完之后再提交 ⇒ 受控拒 `already_settled`（不会重复注册）。
    again = reg.call("lit.admit_all", request_id=RID)
    assert not again.ok and again.meta["kind"] == "already_settled", again.meta


# ====================================================================== b 批内全判


def test_b_naming_an_unjudged_slot_refuses_the_whole_batch(store: Store, reg) -> None:
    """b. 点名点到未判的槽 ⇒ 整批受控拒；那 5 条判收的一格都没注册。"""
    slots = _stage(reg)
    first, rest = slots[:N_FIRST], slots[N_FIRST:]
    _judge(reg, store, first)

    got = reg.call("lit.admit_all", request_id=RID, slots=first + [rest[0]])
    assert not got.ok, ("批里有未判的槽却放行了 ⇒ 批内全判是硬要求", got)
    assert got.meta["kind"] == "undecided_items", got.meta
    assert rest[0] in str(got.error), got.error
    assert [u["slot"] for u in (got.meta.get("undecided") or [])] == [rest[0]], got.meta

    assert not [r for r in store.rows("literature")], "整批被拒却写进了 literature"
    rows = _rows(store)
    for slot in first:
        assert rows[slot]["status"] == "qualified" and not rows[slot]["lit_id"], rows[slot]
        assert not rows[slot]["cleared_at"], rows[slot]


# ====================================================================== c 反真空


def test_c_reverting_the_scope_to_the_whole_delegation_turns_a_red(
        store: Store, reg, monkeypatch: pytest.MonkeyPatch) -> None:
    """c. 把"按批"改回"整委托"（唯一作用域实现返回全部槽）⇒ a 的提交必红。"""
    slots = _stage(reg)
    first, rest = slots[:N_FIRST], slots[N_FIRST:]
    _judge(reg, store, first)

    # 先确认不往回改时 a 是绿的（同一份夹具）。
    assert reg.call("lit.admit_all", request_id=RID).ok

    # 反真空夹具：每个委托重来一次（前一次已经注册并清过那 5 条）。
    root2 = store.root.parent / "ws2"
    st2 = Store(root2)
    st2.init()
    reg2 = build_for_role("A", store=st2, workspace_root=st2.root).registry
    reg2.bound_role = "A"
    slots2 = _stage(reg2)
    _judge(reg2, st2, slots2[:N_FIRST])

    monkeypatch.setattr(L, "submission_slots",
                        lambda scoped, slots=None: [str(r["slot"]) for r in scoped])
    refused = reg2.call("lit.admit_all", request_id=RID)
    assert not refused.ok, "改回整委托之后 5/15 仍能提交 ⇒ a 不是打在提交粒度上"
    assert refused.meta["kind"] == "undecided_items", refused.meta
    assert str(slots2[N_FIRST]) in str(refused.error), refused.error
    assert not [r for r in st2.rows("literature")], "整委托口径下不该注册任何一条"

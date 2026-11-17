# -*- coding: utf-8 -*-
"""「提交时才注册、报告回填号、清表后才收工」这条链的判据（Q1，2026-11-16）。

业主原话（逐字）：「审入库资格时每条待入库文献用临时文献号，写报告时不用临时文献号。
提交时系统自动为有入库资格的单据注册文献号后自动回填报告中入库文献的正式文献号，
被拒的待入库文献只留文献信息和理由没有号。收工流程：A给每个文献裁定好 → 交报告
（自动生成，入库的在一起、拒掉的在一起）→ 系统做批量注册入库并得到映射关系回填
报告的文献号 → 清空待入库文献表及文献 → 真正收工。」

| # | 判据 | 反真空 |
|---|---|---|
| a | 报告正文没有临时号（槽位号 / `cand:`） | 把一行改回「槽位 NNNNNN」⇒ `report_violations` 必红 |
| a′ | 提交后的报告 `## 待裁` 必须是（无） | 把 `undecided` 打桩成恒空 ⇒ 提交闸那条判据红（闸与报告各钉一头） |
| b | 入库组带 `lit:`、拒掉组无号有理由 | 把回填打桩成空（settlement 不写 lit_id）⇒ 提交红 |
| c | 表非空 ⇒ 收工受控拒（blocker）；清表后放行 | 把 `judged_state` 打桩成恒终态 ⇒ 那个 blocker 必消失（红） |
| d | 映射一对一：注册两次不重复、号都在库 | 打桩让第二条复用第一条的 `lit_id` ⇒ d 红 |
| e | 无号快照与带号定稿同事实（只差号） | 快照不重写（幂等）；清表后再提交 ⇒ 受控拒 `already_settled` |
"""
from __future__ import annotations

import pathlib
import re

import pytest

from agentflow import closing as CL
from agentflow import litavail as AV
from agentflow import litread as LR
from agentflow import litstage as L
from agentflow.store import Store
from agentflow.tools import build_for_role

RID = "r-000001"


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


def _stage(reg, titles: list[str], *, rid: str = RID, doi_prefix: str = "10.9") -> list[str]:
    entries = [{"title": t, "doi": f"{doi_prefix}/{i}", "provider": "stub",
                "year": 2020 + i, "type_code": "J",
                "relevance": f"与本次检索相关（{t}）"}
               for i, t in enumerate(titles)]
    res = reg.call("lit.stage_add", request_id=rid, entries=entries)
    assert res.ok, res.error
    return [x["slot"] for x in res.unwrap()["staged"]]


def _readback(reg, rid: str = RID):
    res = reg.call("lit.stage_list", request_id=rid)
    assert res.ok, res.error
    return res


def _attempt(store: Store, slot: str, *, rid: str = RID) -> dict:
    """一条"试过、拿不到可读文本"的抽读回执（AR1：零读取尝试不许按仅题录入库）。"""
    return AV.record_read(store.root, rid, str(slot), LR.FULLTEXT_EXTRACT_FAILED,
                          source="fixture:no-bytes", note="text.extract.no_text_layer")


def _judge(reg, store: Store, slots: list[str], *, rid: str = RID):
    """判收（`qualified`：不注册、不发号），回执/可读性两张前置证据都补齐。"""
    _readback(reg, rid)
    for slot in slots:
        _attempt(store, slot, rid=rid)
    res = reg.call("lit.admit", request_id=rid, items=[
        {"slot": s, "availability": AV.METADATA_ONLY} for s in slots])
    assert res.ok, res.error
    return res


def _submit(reg, rid: str = RID, slots: list[str] | None = None):
    """提交一批（`slots` 不给 = 本委托已判定的全部；FX3·甲 的批次粒度）。"""
    if slots is None:
        return reg.call("lit.admit_all", request_id=rid)
    return reg.call("lit.admit_all", request_id=rid, slots=slots)


def _snapshot_text(store: Store, rid: str = RID) -> str:
    return (store.root / "reports" / f"lit-{rid}.submitted.md").read_text(encoding="utf-8")


def _final_text(store: Store, rid: str = RID) -> str:
    return (store.root / "reports" / f"lit-{rid}.md").read_text(encoding="utf-8")


def _mapping_problems(result: dict, store: Store) -> list[str]:
    """d 的读数：`admitted[]` 的映射一对一、每一条号都在 `literature` 里、条数对得上。"""
    pairs = [(str(x["slot"]), str(x["lit_id"])) for x in result.get("admitted") or []]
    ids = [lit_id for _slot, lit_id in pairs]
    live = {str(r.get("lit_id") or "") for r in store.rows("literature")}
    problems: list[str] = []
    if not all(ids):
        problems.append(f"有槽位没拿到 lit_id：{pairs}")
    if len(set(ids)) != len(ids):
        problems.append(f"同一个 lit_id 给了两条（映射不是一对一）：{pairs}")
    missing = [i for i in ids if i not in live]
    if missing:
        problems.append(f"回填的号在 literature 里查不到：{missing}")
    return problems


# ====================================================================== a 报告没有临时号


def test_a_the_report_carries_no_temporary_id(store: Store, reg) -> None:
    """a. 判收 → 提交之后，两份报告（原件 + 定稿）都一处不印临时号。

    业主逐字：「写报告时不用临时文献号」——槽位号只活在 `lit.stage_list` 里。
    """
    slots = _stage(reg, ["Temp id one", "Temp id two"])
    _judge(reg, store, slots[:1])
    reg.call("lit.stage_reject", slot=slots[1], reason_code="rejected_off_topic",
             note="与本次检索无关")
    assert _submit(reg).ok

    snapshot = _snapshot_text(store)
    final = _final_text(store)
    for text in (snapshot, final):
        assert L.report_violations(text, phase="submitted" if text is snapshot else "final") == []
        for slot in slots:
            assert f"槽位 {slot}" not in text, text
            assert f"cand:{slot}" not in text, text

    # 反真空：把一行改回「槽位 NNNNNN」⇒ 同一条判据必红（否则 a 是恒绿）
    dirty = final.replace("《Temp id one", f"槽位 {slots[0]} 《Temp id one", 1)
    assert dirty != final, "夹具没改到那一行"
    assert L.report_violations(dirty, phase="final"), "改回带槽位号的形态却没红 ⇒ a 是橡皮图章"


# ====================================================================== a′ 待裁必须是（无）


def test_a2_after_submit_the_pending_block_is_empty(store: Store, reg) -> None:
    """a′. 提交成功 ⇒ 定稿的 `## 待裁（0 条）`，且块里只有（无）。"""
    slots = _stage(reg, ["Decided one"])
    _judge(reg, store, slots)
    assert _submit(reg).ok
    final = _final_text(store)
    assert "## 待裁（0 条）" in final, final
    tail = final.split("## 待裁", 1)[1]
    assert "（无）" in tail, tail

    # 反真空的另一半：把 `undecided` 打桩成恒空 ⇒ 提交闸那条判据失去对象（红）。
    slots2 = _stage(reg, ["Unjudged one"], rid="r-000002")
    _readback(reg, "r-000002")
    _attempt(store, slots2[0], rid="r-000002")
    # 批内全判是硬要求：点名点到未判的槽 ⇒ 整批拒（不给 slots 的默认批 = 已判定的
    # 全部，这里还没有判定的行，所以必须显式点名才撞得到这道闸）。
    refused_before = _submit(reg, "r-000002", slots=slots2)
    assert not refused_before.ok, "还有一条没判，提交居然通过了"
    assert refused_before.meta["kind"] == "undecided_items", refused_before.meta
    original = L.undecided
    try:
        L.undecided = lambda rows: []
        after = _submit(reg, "r-000002", slots=slots2)
        # 闸看不见待裁之后，报告判据必须照样拦住（"判完之后才写"这一条不是全靠闸）
        assert not after.ok, after.unwrap()
        assert after.meta["kind"] in ("report_violations", "not_registered"), after.meta
    finally:
        L.undecided = original


# ====================================================================== b 入库组带号 / 拒组无号


def test_b_admitted_rows_carry_numbers_rejected_rows_do_not(store: Store, reg) -> None:
    """b. 定稿：入库组每条带 `lit:`、拒掉组每条只有文献信息与受控理由码。"""
    slots = _stage(reg, ["Keep this one", "Drop this one"])
    _judge(reg, store, slots[:1])
    reg.call("lit.stage_reject", slot=slots[1], reason_code="rejected_low_quality",
             note="摘要只有一行")
    done = _submit(reg)
    assert done.ok, done.error
    lit_id = done.unwrap()["admitted"][0]["lit_id"]
    assert lit_id, done.unwrap()

    final = _final_text(store)
    admitted_block = final.split("## 已入库", 1)[1].split("## 待注册", 1)[0]
    rejected_block = final.split("## 未入库", 1)[1].split("## 待裁", 1)[0]
    assert f"`lit:{lit_id}`" in admitted_block, admitted_block
    assert "《Keep this one》" in admitted_block, admitted_block
    assert "`lit:" not in rejected_block, rejected_block
    assert "《Drop this one》" in rejected_block, rejected_block
    assert "理由：rejected_low_quality" in rejected_block, rejected_block

    # 反真空：把回填打桩成空（settlement 不写 lit_id）⇒ 提交必红（不能静默出定稿）
    slots2 = _stage(reg, ["Backfill stub"], rid="r-000002", doi_prefix="10.11")
    _judge(reg, store, slots2, rid="r-000002")
    original = L._decisions_from
    try:
        L._decisions_from = lambda *a, **k: []
        stubbed = _submit(reg, "r-000002")
    finally:
        L._decisions_from = original
    assert not stubbed.ok, "回填为空却交出了定稿（有入库资格的行没有号）"
    assert stubbed.meta["kind"] in ("not_registered", "report_violations"), stubbed.meta


# ====================================================================== c 收工闸


def test_c_a_non_empty_list_blocks_closing_and_clearing_releases_it(store: Store, reg) -> None:
    """c. 待入库表非空 ⇒ 收工受控拒（blocker，不是读数）；清表之后放行。"""
    rep = CL.check_closing(store, checks=("literature_pending",))
    assert rep.status["literature_pending"] == "pass", rep.to_dict()

    slots = _stage(reg, ["Gate one", "Gate two"])
    rep = CL.check_closing(store, checks=("literature_pending",))
    assert rep.status["literature_pending"] == "fail"
    assert [f.code for f in rep.blockers] == ["undecided_candidates"], rep.to_dict()
    assert rep.closable is False

    _judge(reg, store, slots[:1])
    reg.call("lit.stage_reject", slot=slots[1], reason_code="rejected_off_topic",
             note="与本次检索无关")
    rep = CL.check_closing(store, checks=("literature_pending",))
    assert rep.status["literature_pending"] == "fail"
    assert [f.code for f in rep.blockers] == ["delegation_not_cleared"], rep.to_dict()

    assert _submit(reg).ok
    rep = CL.check_closing(store, checks=("literature_pending",))
    assert rep.status["literature_pending"] == "pass", rep.to_dict()
    assert rep.readings["literature_pending"]["closed_delegations"] == 1, rep.to_dict()

    # 另一份委托还有一条 pending ⇒ 跨委托仍拦（"旧委托的残留也不许带走"）
    _stage(reg, ["Old pending"], rid="r-000002", doi_prefix="10.12")
    rep = CL.check_closing(store, checks=("literature_pending",))
    assert rep.status["literature_pending"] == "fail"
    assert [f.code for f in rep.blockers] == ["undecided_candidates"], rep.to_dict()

    # 反真空：把 `judged_state` 打桩成恒终态 ⇒ 那些 pending 行看不见了 ⇒
    # `undecided_candidates` 那条 blocker 必消失（这一格的判据长在 `litstage.judged_state` 上）。
    original = L.judged_state
    try:
        L.judged_state = lambda row: "rejected"
        rep = CL.check_closing(store, checks=("literature_pending",))
        assert "undecided_candidates" not in [f.code for f in rep.blockers], (
            "打桩成恒终态之后仍然报'还有待裁' ⇒ 这一格的判据不是长在 `litstage.judged_state` 上")
    finally:
        L.judged_state = original


def test_c2_an_unreadable_table_is_unknown_not_pass(store: Store, reg, monkeypatch) -> None:
    """c 的三态：表读不到 ⇒ `unknown`（"问不出来" ≠ "没有待裁"）。"""
    _stage(reg, ["Unreadable table"])

    def _boom(table: str):
        raise RuntimeError("表坏了（判据夹具）")

    monkeypatch.setattr(store, "rows", _boom)
    rep = CL.check_closing(store, checks=("literature_pending",))
    assert rep.status["literature_pending"] == "unknown", rep.to_dict()
    assert rep.readings["literature_pending"]["checked"] is False, rep.to_dict()

    monkeypatch.undo()
    rep = CL.check_closing(store, checks=("literature_pending",))
    assert rep.status["literature_pending"] == "fail", rep.to_dict()


# ====================================================================== d 映射一对一


def test_d_the_mapping_is_one_to_one_and_never_registers_twice(store: Store, reg) -> None:
    """d. 两条候选 ⇒ 两个不同的 lit_id、都能在 `literature` 里查到；重跑不重复注册。"""
    slots = _stage(reg, ["Map one", "Map two"])
    _judge(reg, store, slots)
    done = _submit(reg)
    assert done.ok, done.error
    data = done.unwrap()
    assert data["registered"] == 2, data
    assert _mapping_problems(data, store) == [], _mapping_problems(data, store)
    assert len(store.rows("literature")) == 2, store.rows("literature")

    # 归档里 slot → lit_id 成对（报告没有槽位，这条链只能靠归档）
    archive = (store.root / "data" / "lit_candidates" / f"archive-{RID}.jsonl")
    lines = [ln for ln in archive.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) == 2, lines
    import json as _json
    pairs = {str(_json.loads(ln)["slot"]): str(_json.loads(ln)["lit_id"]) for ln in lines}
    assert set(pairs.values()) == {x["lit_id"] for x in data["admitted"]}, pairs

    # 再提交一次 ⇒ 受控拒 `already_settled`（不会重复注册第二遍）
    again = _submit(reg)
    assert not again.ok and again.meta["kind"] == "already_settled", again.meta
    assert len(store.rows("literature")) == 2, "重跑注册了第二遍"

    # 反真空：打桩让第二条复用第一条的 lit_id ⇒ d 的读数必须红
    slots2 = _stage(reg, ["Dupe one", "Dupe two"], rid="r-000002", doi_prefix="10.13")
    _judge(reg, store, slots2, rid="r-000002")
    original = L._register

    def _reuse(plan, registrar):
        lit_ids, failures, got_all = original(plan, registrar)
        first = next(iter(lit_ids.values()), "")
        for slot in list(lit_ids):
            lit_ids[slot] = first
        return lit_ids, failures, got_all

    try:
        L._register = _reuse
        dup = _submit(reg, "r-000002")
    finally:
        L._register = original
    assert dup.ok, dup.error
    assert _mapping_problems(dup.unwrap(), store), (
        "打桩复用同一个 lit_id 之后 d 仍然通过 ⇒ 一对一这条没有对手方")


# ====================================================================== e 两个渲染时刻同事实


def test_e_the_snapshot_and_the_final_report_tell_the_same_story(store: Store, reg) -> None:
    """e. 无号原件与带号定稿同事实、只差号；快照不重写、清表后不可再生。"""
    slots = _stage(reg, ["Same fact one", "Same fact two"])
    _judge(reg, store, slots[:1])
    reg.call("lit.stage_reject", slot=slots[1], reason_code="rejected_off_topic",
             note="与本次检索无关")
    assert _submit(reg).ok

    snapshot = _snapshot_text(store)
    final = _final_text(store)
    # 只差号：把两份的"事实行"抽出来（题名 / 年 / 出处 / 拒因），它们必须逐条相同。
    def _facts(text: str) -> list[str]:
        out = []
        for line in text.splitlines():
            line = line.strip()
            if "《" not in line:
                continue
            line = line.replace("`lit:", "`")           # 号只差这一处
            line = re.sub(r"^- `[0-9]{4,6}` ", "- ", line)   # 抹掉那一格号本身
            line = re.sub(r"^\- 槽位 [0-9]{4,6} ", "- ", line)
            out.append(line)
        return out

    assert _facts(snapshot) == _facts(final), (_facts(snapshot), _facts(final))
    assert "`lit:" in final and "`lit:" not in snapshot, (snapshot, final)

    # 快照不重写：再渲染一次（模拟崩在注册之后）拿到的仍是同一份原件
    before = snapshot
    L._write_report_snapshot(store, RID, [r for r in store.rows("lit_candidates")])
    assert _snapshot_text(store) == before, "原件被'注册之后的行'覆盖了（交报告那一刻的留档丢了）"

    # 清表之后报告不可再生（受控拒 `already_settled`）
    with pytest.raises(L.LitStageError) as ei:
        L.write_report(store, RID, phase="final")
    assert ei.value.kind == "already_settled", ei.value.kind

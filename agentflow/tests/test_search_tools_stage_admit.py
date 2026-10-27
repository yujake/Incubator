"""待新增文献列表的判据（业主 2026-10-20 口径，逐条 + 负控）。

这一份守的六件事，每一条都配一个负控（把那条判据关掉 ⇒ 必须变绿，
否则"判据真的在起作用的"这句话没有证据）：

  ① 一次文献检索至多入库 10 篇（单次调用 ≤10、单委托累计 ≤10；超了整笔拒绝）；
  ② 拒收必须带受控理由码，行上的 `reject_reason` 不许为空；
  ③ DOI 完全相同 ⇒ 视为重复；标题词集 Jaccard ≥ 0.60 且无 `new_content` ⇒ 拒收；
  ④ 撤掉的槽位仍在列表里且带理由（负控：改成物理删除 ⇒ 红）；
  ⑤ 列表按委托重置（默认视图只看当前委托；负控：去掉过滤 ⇒ 红）；
  ⑥ 一键迁移 `lit.admit_all` 之后本委托全终态（不物理删），并写出委托报告
     —— 报告里"已入库 / 未入库（含受控理由）"两块都要有（负控：去掉一块 ⇒ 红）。

外加一条"野路"判据：`lit_candidates` 不许由通用写口（`table.create` / `table.update` /
`table.delete`）碰 —— 与 `store.direct_write_refusal` 同形，负控是把它关掉。
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from agentflow import litstage as L
from agentflow import schema as S
from agentflow.agent_a import AgentA
from agentflow.fetch import FetchResult
from agentflow.providers import Candidate
from agentflow.store import Store
from agentflow.tools import build_for_role

RID = "r-000001"
RID2 = "r-000002"


# ---------------------------------------------------------------- 夹具


@pytest.fixture
def store(tmp_path: Path) -> Store:
    """一个空工作区（`lit_candidates` 表由 schema 驱动，不需要额外 init）。"""
    st = Store(tmp_path / "ws")
    st.init()
    return st


@pytest.fixture
def reg(store: Store):
    """A 的工具面（真注册表 —— 判据打在工具层，不是打在 `litstage` 的内部函数上）。"""
    registry = build_for_role("A", store=store, workspace_root=store.root).registry
    registry.bound_role = "A"
    return registry


def _add_local(store: Store, *, title: str, doi: str) -> str:
    """本地库先放一篇（DOI 重复档与"标题高重叠"档都要拿它当靶子）。"""
    with store.tx("literature", "counters", actor="t", note="fixture") as tx:
        lit_id = tx.alloc_id("lit")
        row = S.Literature(
            lit_id=lit_id, title=title, type="J", summary="本地已有",
            path=None, processed=True, dedup_key=f"doi:{doi}", doi=doi,
            year=2019, added_at=S.now_iso(),
        )
        row.validate()
        tx.upsert("literature", row.to_dict(), note="fixture")
    return str(lit_id)


#: 一批互不相似的题名：判据要测的是条数上限与重叠检查，两者都会被"题名彼此太像"
#: 干扰（先入的那几条进了 literature 之后，后来的会被标题 Jaccard 判成高重叠）。
#: 所以夹具的题名一律取不同的数学主题 —— 这是夹具该做的事，不是放宽判据。
DISTINCT = [
    "Floquet band structure of periodic elliptic operators",
    "Heat kernel asymptotics on compact manifolds",
    "Semiclassical trace formulae for Schrödinger operators",
    "Spectral flow and index theory on foliations",
    "Resonances of damped wave equations",
    "Homogenization of elliptic systems with oscillating coefficients",
    "Weyl asymptotics for magnetic Laplacians",
    "Eigenvalue optimisation under volume constraints",
    "Dirichlet-to-Neumann maps on rough domains",
    "Spectral stability of travelling waves",
    "Inverse problems for anisotropic conductivities",
    "Quasimodes in periodic waveguides",
]


def _stage(reg, titles, *, request_id: str = RID, doi_prefix: str = "10.7") -> list[str]:
    entries = [{"title": t, "doi": f"{doi_prefix}/{i}", "provider": "stub", "year": 2000 + i,
                "type_code": "J", "summary": f"摘要 {i}", "relevance": f"与本次检索相关（{t}）"}
               for i, t in enumerate(titles)]
    res = reg.call("lit.stage_add", request_id=request_id, entries=entries)
    assert res.ok, res.error
    return [x["slot"] for x in res.unwrap()["staged"]]


# ---------------------------------------------------------------- ① 至多入库 10 篇


def test_at_most_ten_per_call_is_refused_as_a_whole(reg, store):
    """① 一次要入 11 条 ⇒ 整笔拒绝，一条都不入（不是"前 10 条先进"）。"""
    slots = _stage(reg, DISTINCT[:11])
    before = len(store.rows("literature"))
    res = reg.call("lit.admit", slots=slots, request_id=RID)
    assert not res.ok, "11 条一次入库居然过了"
    assert res.meta["kind"] == "over_cap_call", res.meta
    assert res.meta["call_size"] == 11 and res.meta["call_limit"] == 10, res.meta
    assert len(store.rows("literature")) == before, "整笔拒绝却写进了 literature"


def test_at_most_ten_per_delegation_refuses_the_eleventh(reg, store):
    """① 入到第 10 条之后再 admit 第 11 条 ⇒ 整笔拒绝（累计也是 10）。"""
    slots = _stage(reg, DISTINCT[:11])
    res = reg.call("lit.admit", slots=slots[:10], request_id=RID)
    assert res.ok, res.error
    assert len(res.unwrap()["admitted"]) == 10, res.unwrap()
    before = len(store.rows("literature"))
    res = reg.call("lit.admit", slots=[slots[10]], request_id=RID)
    assert not res.ok, "第 11 条居然入库了"
    assert res.meta["kind"] == "over_cap_delegation", res.meta
    assert res.meta["delegation_admitted"] == 10 and res.meta["delegation_limit"] == 10
    assert len(store.rows("literature")) == before


def test_negative_control_raising_the_cap_lets_eleven_through(reg, store, monkeypatch):
    """① 的负控：把上限放开 ⇒ 同一个调用必须能入库 11 条（判据读的是那个常量）。"""
    slots = _stage(reg, [f"Cap probe topic {i}" for i in range(11)])
    monkeypatch.setattr(L, "MAX_ADMIT_PER_CALL", 99)
    monkeypatch.setattr(L, "MAX_ADMIT_PER_DELEGATION", 99)
    res = reg.call("lit.admit", slots=slots, request_id=RID)
    assert res.ok, f"放开上限之后仍然被拒：{res.error}"
    assert len(res.unwrap()["admitted"]) == 11, res.unwrap()
    assert len(store.rows("literature")) == 11


# ---------------------------------------------------------------- ② 理由码受控


def test_reject_needs_a_registered_reason_code(reg, store):
    """② 拒收必须带登记表里的理由码（空码 / 自造码一律拒）。"""
    slots = _stage(reg, ["A paper to reject"])
    with pytest.raises(L.LitStageError) as ei:
        L.reject(store, slots[0], "")
    assert ei.value.kind == "bad_reason_code", ei.value.kind
    with pytest.raises(L.LitStageError) as ei2:
        L.reject(store, slots[0], "because I felt like it")
    assert ei2.value.kind == "bad_reason_code", ei2.value.kind
    # 受控码则通过，并把理由写进那一行（报告要用它）
    got = L.reject(store, slots[0], "rejected_off_topic", "与本次检索无关")
    assert got["status"] == "rejected" and got["reason_code"] == "rejected_off_topic"
    row = L.list_candidates(store, request_id=RID, status="rejected")["rows"][0]
    assert row["reject_reason"] == "与本次检索无关"


def test_a_rejected_row_can_never_have_an_empty_reason(store):
    """② 的结构面：`status="rejected"` 而 `reject_reason` 为空 ⇒ schema 直接拒。"""
    with pytest.raises(ValueError) as ei:
        S.LitCandidate(slot="000000", request_id=RID, batch=1, status="rejected",
                       title="t", reject_reason="", added_at=S.now_iso()).validate()
    assert "reject_reason" in str(ei.value)


def test_negative_control_turning_off_the_code_check_lets_an_empty_reason_through(
    store, monkeypatch
):
    """② 的负控：把"理由码受控 + 行上理由非空"两条判据同时关掉 ⇒ 空理由也写得进去。

    负控必须打在同一条判据上（这里就是 `litstage._check_code` 与
    `schema.LitCandidate.validate`），否则证明的是别的什么东西没生效。
    """
    with store.tx("lit_candidates", "counters", actor="t", note="fixture") as tx:
        slot = tx.alloc_id("candidate")
        row = S.LitCandidate(slot=slot, request_id=RID, batch=1, status="pending",
                             title="Negative control", added_at=S.now_iso())
        row.validate()
        tx.upsert("lit_candidates", row.to_dict(), note="fixture")
    monkeypatch.setattr(L, "_check_code", lambda code: str(code or ""))
    monkeypatch.setattr(L, "_code_label", lambda code: "")
    monkeypatch.setattr(S.LitCandidate, "validate", lambda self: None)
    got = L.reject(store, slot, "", "")
    assert got["status"] == "rejected" and got["reason_code"] == ""
    row = [r for r in store.rows("lit_candidates") if r["slot"] == slot][0]
    assert row["reject_reason"] == "", "负控没把判据真的关掉"


# ---------------------------------------------------------------- ③ 重叠检查


def test_doi_exact_duplicate_is_refused(reg, store):
    """③ DOI 与本地库完全相同 ⇒ 视为重复，拒收（给 new_content 也不放行）。"""
    dup = _add_local(store, title="A local paper about lattices", doi="10.5/local.dup")
    slots = _stage(reg, ["A completely different title about packing"], doi_prefix="10.6")
    # 让这一条的 DOI 与本地那篇相同
    with store.tx("lit_candidates", actor="t", note="fixture") as tx:
        row = [r for r in tx.rows("lit_candidates") if r["slot"] == slots[0]][0]
        row["doi"] = "10.5/local.dup"
        tx.upsert("lit_candidates", row, note="fixture")
    res = reg.call("lit.admit", items=[{"slot": slots[0],
                                       "new_content": "就算给了新内容也不许"}], request_id=RID)
    assert res.ok, res.error
    data = res.unwrap()
    assert not data["admitted"], "同一 DOI 居然入库了"
    assert [r["code"] for r in data["refused"]] == ["duplicate_doi"], data["refused"]
    assert data["refused"][0]["overlap"]["overlap_with"] == dup
    assert len(store.rows("literature")) == 1, "库里多出了第二行"


def test_high_title_overlap_requires_new_content(reg, store):
    """③ 标题词集 Jaccard ≥ 0.60 且无 `new_content` ⇒ 拒收；给了 ⇒ 可入库。"""
    _add_local(store, title="Spectral gaps of K(m) operators", doi="10.5/local.one")
    slots = _stage(reg, ["Spectral gaps of K(m) operators revisited",
                         "Spectral gaps of K(m) operators extended"], doi_prefix="10.8")
    res = reg.call("lit.admit", slots=[slots[0]], request_id=RID)
    assert res.ok, res.error
    assert not res.unwrap()["admitted"], "高重叠且无 new_content 居然入库了"
    assert res.unwrap()["refused"][0]["code"] == "overlap_without_new_content"
    assert res.unwrap()["refused"][0]["overlap"]["overlap_score"] >= L.OVERLAP_HIGH_JACCARD
    res = reg.call("lit.admit", items=[{"slot": slots[0],
                                       "new_content": "本地那篇只给有限 m，这里要 m→∞ 的渐近式"}],
                   request_id=RID)
    assert res.ok, res.error
    assert len(res.unwrap()["admitted"]) == 1, res.unwrap()


def test_negative_control_disabling_overlap_check_admits_the_high_overlap_paper(
    reg, store, monkeypatch
):
    """③ 的负控：把重叠检查换成"永远没重叠" ⇒ 高重叠那条也能入库（判据真的读它）。

    用不同 DOI 的高重叠样本：于是"关掉判据"与"不关"的差别落在
    `literature` 的行数上（多出一行），而不是被现有判重分支顺手挡掉 ——
    后者是第二道防线（`dedup.literature_keys`），不能拿来当本判据的读数。
    """
    _add_local(store, title="Spectral gaps of K(m) operators", doi="10.5/local.one")
    slots = _stage(reg, ["Spectral gaps of K(m) operators revisited"], doi_prefix="10.9")
    # 正控：不关判据 ⇒ 拒收，库里仍然只有本地那一行
    res = reg.call("lit.admit", slots=[slots[0]], request_id=RID)
    assert res.ok, res.error
    assert not res.unwrap()["admitted"]
    assert len(store.rows("literature")) == 1
    # 负控：关掉重叠检查 ⇒ 这一次进得去，库里多出一行
    monkeypatch.setattr(L, "overlap_check", lambda store, title, doi=None: {
        "checked": True, "duplicate": False, "overlap_score": 0.0,
        "overlap_kind": "title_jaccard", "overlap_with": None,
        "requires_new_content": False, "reason": "负控：把重叠检查关掉",
    })
    res = reg.call("lit.admit", slots=[slots[0]], request_id=RID)
    assert res.ok, res.error
    admitted = res.unwrap()["admitted"]
    assert admitted and admitted[0]["created"] is True, "关掉判据之后仍然没入库 —— 负控没打在真判据上"
    assert len(store.rows("literature")) == 2, "关掉判据后应该多出一行"


# ---------------------------------------------------------------- ④ 撤掉 ≠ 删掉


def test_withdrawn_slot_stays_in_the_list_with_its_reason(reg, store):
    """④ 撤掉的槽位仍在列表里，且带理由与题名（序号不复用）。

    2026-10-26（Q16）改读数：状态只有三态，撤掉不再是第四态 `withdrawn`，
    而是 `rejected` + `reason_code=withdrawn_by_reviewer`（差别落在受控理由码上）。
    行照旧不物理删除：题名、理由、序号都留着 —— 这一条判据守的东西没变。
    改前读数：`row["status"] == "withdrawn"`；改后：`"rejected"` + 理由码。
    """
    slots = _stage(reg, ["Keep me", "Withdraw me", "Keep me too"])
    res = reg.call("lit.stage_withdraw", slot=slots[1], reason_code="withdrawn_by_reviewer",
                   note="内容与本次检索无关")
    assert res.ok, res.error
    listing = L.list_candidates(store, request_id=RID)
    assert listing["count"] == 3, "撤掉之后那一槽从列表里消失了"
    row = [r for r in listing["rows"] if r["slot"] == slots[1]][0]
    assert row["status"] == "rejected", row
    assert row["withdrawn_reason"] == "内容与本次检索无关"
    assert row["reject_reason"] == "内容与本次检索无关", "三态这一侧也要说得出理由"
    assert row["reason_code"] == "withdrawn_by_reviewer"
    assert row["title"] == "Withdraw me", "撤掉的槽位必须留着题名（记下删掉的是哪一篇）"
    # 计数里不再有第四态那一格可涨（它恒为 0：撤掉折进了 rejected）
    assert listing["counts"]["withdrawn"] == 0 and listing["counts"]["rejected"] == 1, \
        listing["counts"]
    # 补位进的是新序号，旧号不复用
    new_slots = _stage(reg, ["A replacement paper"], doi_prefix="10.11")
    assert new_slots[0] > slots[2], (new_slots, slots)


def test_negative_control_physical_delete_makes_the_slot_disappear(reg, store):
    """④ 的负控：把那一行物理删掉（绕过工具、直接改表）⇒ 同一个判据立刻变红。"""
    slots = _stage(reg, ["Keep me", "Physically delete me"])
    reg.call("lit.stage_withdraw", slot=slots[1], reason_code="withdrawn_by_reviewer")
    # 撤掉的那一槽按三态读是 rejected（Q16），按老名字 withdrawn 查也还查得到它 ——
    # 两种查法都是 1，才证明"折过来"没有把这一行折丢。
    assert L.list_candidates(store, request_id=RID, status="rejected")["count"] == 1

    def check() -> list[str]:
        rows = [r for r in L.list_candidates(store, request_id=RID)["rows"]
                if r["slot"] == slots[1]]
        if not rows:
            return [f"槽位 {slots[1]} 不在列表里（被物理删掉了）"]
        if not rows[0]["withdrawn_reason"]:
            return [f"槽位 {slots[1]} 没有理由"]
        return []

    assert check() == [], "正控：撤掉之后判据应当是绿的"
    with store.tx("lit_candidates", actor="t", note="negative-control") as tx:
        assert tx.delete("lit_candidates", slots[1]) is not None
    assert check() != [], "负控没红：物理删掉之后判据仍然绿"


def test_negative_control_table_delete_is_redirected_to_withdraw_on_lit_candidates(reg):
    """野路判据：`table.delete(lit_candidates)` 不许物理删 —— 它被转交成"撤掉"。

    ## 2026-10-24 换过处置（业主裁定「自动将直写请求路由到秘书接管」）
    改前这一格是"拒 + 指路"。现在它由 `lit.stage_withdraw` 那条正路接管；
    而"撤掉必须写受控理由码"是那条正路自己的判据 ⇒ 没给理由时它拒，
    理由原样带回，行仍在列表里（既没被删，也没被悄悄改成 withdrawn）。
    """
    slots = _stage(reg, ["Try to delete me"])
    res = reg.call("table.delete", table="lit_candidates", id=slots[0])
    assert not res.ok, res
    assert res.meta["kind"] == "routed_to_backstop.literal_refused", res.meta
    assert res.meta["routed_to"] == "lit.stage_withdraw", res.meta
    assert "理由码" in str(res.meta.get("refused_by_backstop") or ""), res.meta


def test_direct_writes_are_taken_over_by_the_lister_backstops(reg, monkeypatch):
    """野路判据（2026-10-24 换过处置）：`lit_candidates` 的直写由 `lit.*` 正路接管；
    把判据关掉 ⇒ 通用写口又能自己写进去（负控证明工具层读的是那一条判据）。"""
    res = reg.call("table.create", table="lit_candidates",
                   row={"title": "hand written", "request_id": RID, "batch": 1,
                        "status": "pending"})
    assert res.ok is True, (res.error, res.meta)
    assert res.meta["backstop"] == "literal", res.meta
    assert res.meta["routed_to"] == "lit.stage_add", res.meta
    slots = _stage(reg, ["Legit row"])
    res = reg.call("table.update", table="lit_candidates", id=slots[0],
                   patch={"status": "admitted", "lit_id": "000000"})
    assert res.meta["backstop"] == "literal", res.meta
    assert res.meta["routed_to"] == "lit.admit", res.meta
    from agentflow import store as store_mod

    monkeypatch.setattr(store_mod, "direct_write_refusal", lambda table: "")
    res = reg.call("table.create", table="lit_candidates",
                   row={"title": "hand written", "request_id": RID, "batch": 1,
                        "status": "pending"})
    # 负控：判据关掉之后这一笔根本不进兜底，通用写口自己就写进去了（没有 backstop 这一格）
    assert res.ok, f"关掉判据之后通用写口仍然写不进去：{res.error}"
    assert res.meta.get("backstop") is None, res.meta


# ---------------------------------------------------------------- ⑤ 按委托重置


def test_list_defaults_to_the_current_delegation(reg, store):
    """⑤ 起第二个委托之后，`stage_list` 默认只返回第二个委托的行。"""
    _stage(reg, ["Delegation one paper A", "Delegation one paper B"])
    _stage(reg, ["Delegation two paper"], request_id=RID2, doi_prefix="10.12")
    listing = L.list_candidates(store)
    assert listing["request_id"] == RID2, listing["request_id"]
    assert listing["count"] == 1, listing["count"]
    assert [r["title"] for r in listing["rows"]] == ["Delegation two paper"]
    # 旧委托的行没被删，显式查得到（这正是"查历史可以"）
    assert L.list_candidates(store, request_id=RID)["count"] == 2
    assert listing["total_all_delegations"] == 3


def test_negative_control_dropping_the_filter_shows_the_old_delegation(reg, store, monkeypatch):
    """⑤ 的负控：把过滤去掉（`current_request_id` 恒为空 ⇒ 视图退回全表）⇒ 判据变红。

    这条负控打的是"默认视图按当前委托过滤"那条判据的唯一实现
    （`litstage.current_request_id`），所以它证明的是"过滤真的在起作用"。
    """
    _stage(reg, ["Delegation one paper A"])
    _stage(reg, ["Delegation two paper"], request_id=RID2, doi_prefix="10.12")
    assert L.list_candidates(store)["count"] == 1
    monkeypatch.setattr(L, "_scoped_rows", lambda rows, rid: [dict(r) for r in rows])
    listing = L.list_candidates(store)
    assert listing["count"] == 2, "去掉过滤之后仍然只看到 1 条 —— 负控没打在真判据上"


# ---------------------------------------------------------------- ⑥ 提交整批 + 报告


def test_the_whole_list_is_refused_until_every_item_is_judged(reg, store):
    """⑥ 提交整批（Q16 之后）：没逐条判完之前 `lit.admit_all` 整批被拒；判完之后它收口并写报告。

    改前读数：三条一起 stage、一条判拒，`lit.admit_all` 一次就把另两条搬进 literature
    （`registered == 2`）—— 那正是 Q16 要挡的"整批搬库"，而它当时是放行的。
    改后读数：同一次调用被拒（`kind=undecided_items`，拒信点名 000000 / 000001），
    literature 一行都没多；逐条 `lit.admit` 之后 `admit_all` 以 `registered == 0` 收口
    （该入的在逐条那一步已经入了），报告三块都在。
    """
    slots = _stage(reg, ["Migration one", "Migration two", "Migration three"])
    L.reject(store, slots[2], "rejected_low_quality", "只有一行摘要")

    refused = reg.call("lit.admit_all", request_id=RID)
    assert not refused.ok, "还有 2 条没判，整批居然通过了"
    assert refused.meta["kind"] == "undecided_items", refused.meta
    assert "还有 2 条没判" in str(refused.error), refused.error
    assert slots[0] in str(refused.error) and slots[1] in str(refused.error), refused.error
    assert [u["slot"] for u in (refused.meta.get("undecided") or [])] == slots[:2], refused.meta
    assert len(store.rows("literature")) == 0, "整批被拒却写进了 literature"

    for slot in slots[:2]:
        got = reg.call("lit.admit", slots=[slot], request_id=RID)
        assert got.ok, got.error
        assert len(got.unwrap()["admitted"]) == 1, got.unwrap()

    res = reg.call("lit.admit_all", request_id=RID)
    assert res.ok, res.error
    data = res.unwrap()
    assert data["registered"] == 0, data
    assert data["report_path"], data
    listing = L.list_candidates(store, request_id=RID)
    assert listing["counts"]["pending"] == 0, listing["counts"]
    assert listing["counts"]["admitted"] == 2 and listing["counts"]["rejected"] == 1
    text = Path(data["report_path"]).read_text(encoding="utf-8")
    assert L.report_violations(text) == [], L.report_violations(text)
    assert "## 已入库（2 篇）" in text and "## 未入库（1 篇）" in text, text
    assert "## 待裁（0 条）" in text, text
    assert "理由：rejected_low_quality" in text, text
    # 已入库那一块必须带"它为什么与本次检索相关"
    assert "相关性：" in text


def test_over_cap_is_folded_into_rejected_over_cap_and_leaves_no_fourth_state(reg, store):
    """⑥ 配额满那一档折进 `rejected` + `reason_code=over_cap`（Q16 第 ①/④ 条）。

    ## 改前 / 改后读数

    改前：12 条同一批 stage、`lit.admit_all` 一次收 10 条，余下 2 条落
    `status="cleared"` + `cleared_at` + `clear_reason`（第四态）；`counts["cleared"] == 2`。
    改后：同一条路先被提交闸拦下（12 条一条都没判）—— 整批搬库没有入口了；
    配额那一档本身仍然存在，但它落在 `rejected` + `over_cap` 上，盘上没有第四态。

    为了让"配额满"这条判据仍然有可测的落点，这里直接走 `litstage` 的
    truncate 档（`lit.admit_all` 现在只在"全部判完"之后才走到它，而那一步
    没有超配额可言）：`admission_plan(on_over_cap="truncate")` 的结论经
    `decisions_from_plan` + `apply_settlement` 落盘，与工具面是同一条实现。
    """
    slots = _stage(reg, [f"Over cap topic {i}" for i in range(12)])
    plan = L.admission_plan(store, request_id=RID, batch=1, on_over_cap="truncate")
    assert plan["ok"], plan
    assert len(plan["admitted"]) == 10, plan["call_size"]
    assert len(plan["cleared"]) == 2, plan["cleared"]
    with store.tx("lit_candidates", actor="t", note="over-cap settle") as tx:
        L.apply_settlement(tx, L.decisions_from_plan(plan, {
            item["slot"]: item["slot"] for item in plan["admitted"]}))
    listing = L.list_candidates(store, request_id=RID)
    assert listing["count"] == 12, "折算把行删掉了（应当只是换状态）"
    assert listing["counts"]["pending"] == 0, listing["counts"]
    assert listing["counts"]["cleared"] == 0, "盘上还有第四态 cleared"
    assert listing["counts"]["withdrawn"] == 0, "盘上还有第四态 withdrawn"
    folded = [r for r in listing["rows"] if r["reason_code"] == "over_cap"]
    assert len(folded) == 2, folded
    assert all(r["status"] == "rejected" for r in folded), folded
    assert all(r["reject_reason"] for r in folded), folded


def test_negative_control_a_report_without_the_not_admitted_block_is_red(store):
    """⑥ 的报告判据负控：把「未入库」那一块删掉 ⇒ `report_violations` 必须报出来。"""
    rows = [
        S.LitCandidate(slot="000000", request_id=RID, batch=1, status="admitted",
                       title="Admitted one", lit_id="000000", relevance="与本次相关",
                       added_at=S.now_iso()).to_dict(),
        S.LitCandidate(slot="000001", request_id=RID, batch=1, status="withdrawn",
                       title="Withdrawn one", reason_code="withdrawn_by_reviewer",
                       withdrawn_reason="内容不好", added_at=S.now_iso()).to_dict(),
    ]
    good = L.report_markdown(RID, rows)
    assert L.report_violations(good) == []
    broken = good.split("## 未入库")[0]
    viol = L.report_violations(broken)
    assert viol and "缺 `## 未入库` 块" in viol[0], viol
    # 反方向：把受控理由码换成自造的一句散文 ⇒ 也必须红
    forged = good.replace("理由：withdrawn_by_reviewer", "理由：我觉得不行")
    viol2 = L.report_violations(forged)
    assert viol2 and "不在受控取值里" in viol2[0], viol2


# ---------------------------------------------------------------- A 的接线（run_once）


class _StubProvider:
    name = "stub"

    def __init__(self, candidates):
        self.candidates = list(candidates)

    def search(self, topic, mode, description, limit):
        return list(self.candidates)


class _OkDownloader:
    def download(self, url: str, dest_dir: Path, filename_hint: str) -> FetchResult:
        dest = Path(dest_dir)
        dest.mkdir(parents=True, exist_ok=True)
        target = dest / f"{filename_hint or 'file'}.txt"
        target.write_text("An abelian group is a group in which the commutative law holds.",
                          encoding="utf-8")
        data = target.read_bytes()
        return FetchResult(ok=True, kind="", path=str(target), http_status=200,
                           bytes=len(data), sha256=hashlib.sha256(data).hexdigest(), error=None)


def _cand(i: int) -> Candidate:
    return Candidate(
        title=f"Run once candidate {i}", year=2000 + i, doi=f"10.20/run{i}",
        authors=["A. Author"], venue="V", type_code="J", summary=f"摘要 {i}",
        pdf_url=f"http://example.invalid/{i}.pdf", landing_url=None, language="en",
        provider="stub", raw={"provider": "stub"},
    )


def test_run_once_stages_and_no_longer_bulk_admits(store):
    """A 的自动链路只暂存（Q16 之后）：候选全进列表并停在 pending，报告三块都在。

    ## 改前 / 改后读数

    改前：2 条候选当场被整批入库（`registered == 2`、两条都是 `admitted` + `lit_id`、
    `literature` 多两行），而两条的 `relevance` 都是空 —— "A 读过"这件事没有任何证据。
    改后：同一次 `run_once` 一条也入不了库（`registered == 0`、两条都是 `pending`、
    `literature` 0 行），`last_error` 里写着"待裁 2 条"，委托报告的三块
    （已入库 / 未入库 / 待裁）都在。这就是业主 Q16 要的：整批搬库没有入口了，
    入库只能逐条判过。
    """
    from conftest import add_request

    add_request(store, RID)
    agent = AgentA(store, providers=[_StubProvider([_cand(0), _cand(1)])],
                   downloader=_OkDownloader(), config={"download": True})
    res = agent.run_once()
    assert res.registered == 0, res.to_dict()
    rows = [r for r in store.rows("lit_candidates") if r["request_id"] == RID]
    assert len(rows) == 2, rows
    assert all(r["status"] == "pending" for r in rows), rows
    assert all(not r["lit_id"] for r in rows), rows
    assert len(store.rows("literature")) == 0, "自动链路还是把行搬进了 literature"
    request_row = next(r for r in store.rows("search_requests") if r["request_id"] == RID)
    assert "待裁 2 条" in str(request_row["last_error"] or ""), request_row
    assert res.report_path and Path(res.report_path).is_file(), res.report_path
    assert res.report_admitted == 0, res.to_dict()
    text = Path(res.report_path).read_text(encoding="utf-8")
    assert "## 已入库（0 篇）" in text and "## 未入库（0 篇）" in text, text
    assert "## 待裁（2 条）" in text, text
    assert L.report_violations(text) == [], L.report_violations(text)


def test_run_once_cannot_bulk_admit_past_the_delegation_cap(store):
    """12 条候选：改前会是"10 条入库 + 2 条 cleared(over_cap)"，改后一条都不入库。

    ## 改前 / 改后读数

    改前：`registered == 10`、`literature` 10 行、12 条候选里 2 条 `cleared(over_cap)`
    —— 一次检索把配额用满，而"A 逐篇读过"这条路一步都没走。
    改后：`registered == 0`、12 条全 `pending`、`literature` 0 行；配额那一条仍然在
    （`tests/...::test_over_cap_is_folded_into_rejected_over_cap...` 守着），只是
    它再也轮不到"没判过的 12 条"来触发。
    """
    from conftest import add_request

    add_request(store, RID)
    agent = AgentA(store, providers=[_StubProvider([_cand(i) for i in range(12)])],
                   downloader=_OkDownloader(),
                   config={"download": True, "max_downloads_per_request": 12})
    res = agent.run_once()
    assert res.registered == 0, res.to_dict()
    assert len(store.rows("literature")) == 0
    rows = [r for r in store.rows("lit_candidates") if r["request_id"] == RID]
    assert len(rows) == 12
    codes = sorted((r["status"], r["reason_code"]) for r in rows)
    assert codes.count(("pending", "")) == 12, codes
    assert [c for c in codes if c[0] in ("cleared", "withdrawn")] == [], codes


# ---------------------------------------------------------------- ⑦ 同一委托内同一篇只占一个槽

def test_the_same_paper_is_topped_up_instead_of_staged_twice(reg, store):
    """同一委托内同一 DOI 再登记 ⇒ 补进原槽（`updated[]`），不发新号。

    改前读数（`temp/g9/g9_probe_stage.py` 实测）：同一次 `stage_add` 里两条逐字相同的
    entry 各拿一个槽；跨两次登记同一 DOI 也是两个槽 —— 于是 `lit.admit` 只能收其中一个，
    另一个永远留成 `rejected`，报告上"已入库 N 篇 / 未入库 N 篇"是同一批题名。
    真机 `mp3-r4`：5 条 admitted 对应 5 条被取代的槽。
    """
    first = reg.call("lit.stage_add", request_id=RID, entries=[
        {"title": "Same paper", "doi": "10.71/same", "provider": "stub", "year": 2020}])
    assert first.ok, first.error
    slot = first.unwrap()["staged"][0]["slot"]

    # 大小写不同的同一个 DOI：身份归一化之后是同一篇
    again = reg.call("lit.stage_add", request_id=RID, entries=[
        {"title": "Same paper", "doi": "10.71/SAME", "provider": "stub", "year": 2020,
         "relevance": "带证据补进原槽"}])
    assert again.ok, again.error
    data = again.unwrap()
    assert data["staged"] == [], data
    assert [item["slot"] for item in data["updated"]] == [slot], data
    assert data["updated"][0]["fields"] == ["relevance"], data
    rows = [r for r in store.rows("lit_candidates") if r["request_id"] == RID]
    assert len(rows) == 1 and rows[0]["status"] == "pending", rows
    assert rows[0]["relevance"] == "带证据补进原槽", rows[0]

    # 补进去之后逐条入库这条路就通了（改前必须先撤掉再重进才对得上 relevance）
    done = reg.call("lit.admit", slots=[slot], request_id=RID)
    assert done.ok and done.unwrap()["admitted"], done.unwrap()


def test_negative_control_a_blind_identity_lets_one_paper_take_two_slots(reg, store, monkeypatch):
    """反真空：把身份函数换成"每次都不同" ⇒ 同一篇立刻占两个槽（判据真的读它）。"""
    calls = {"n": 0}

    def _blind(title, doi):
        calls["n"] += 1
        return f"blind:{calls['n']}"

    monkeypatch.setattr(L, "candidate_identity", _blind)
    entry = {"title": "Same paper", "doi": "10.72/same", "provider": "stub", "year": 2020}
    first = reg.call("lit.stage_add", request_id=RID, entries=[dict(entry)])
    second = reg.call("lit.stage_add", request_id=RID, entries=[dict(entry)])
    assert first.ok and second.ok, (first.error, second.error)
    rows = [r for r in store.rows("lit_candidates") if r["request_id"] == RID]
    assert len(rows) == 2, "负控没打在真判据上：身份瞎了之后同一篇仍然只占一个槽"


# ---------------------------------------------------------------- ⑧ 重复登记只报数、报告只标注

def test_a_twin_slot_is_a_reading_and_the_report_annotates_instead_of_hiding_it(reg, store):
    """同一篇占两个槽（先收后又被登记一次）⇒ `duplicate_rows` 报数、报告加尾注、篇数不折算。

    "不许动 counts 的分子分母"在这一条上是硬约束：删掉未入库那一行会让"库里明明有"
    与"报告说没入库"的差异看不见（把真值藏起来），改篇数就是读侧悄悄少算一篇
    （往另一个方向说谎）。所以只加读数与尾注。
    """
    staged = reg.call("lit.stage_add", request_id=RID, entries=[
        {"title": "Twin paper", "doi": "10.73/twin", "provider": "stub", "year": 2021,
         "relevance": "第一次判收的理由"}])
    assert staged.ok, staged.error
    first_slot = staged.unwrap()["staged"][0]["slot"]
    admitted = reg.call("lit.admit", slots=[first_slot], request_id=RID)
    assert admitted.ok and admitted.unwrap()["admitted"], admitted.unwrap()
    lit_id = admitted.unwrap()["admitted"][0]["lit_id"]

    # 同一篇再登记一次：它已经是 admitted 槽，不并（历史不能抹），于是长出新槽
    twin = reg.call("lit.stage_add", request_id=RID, entries=[
        {"title": "Twin paper", "doi": "10.73/twin", "provider": "stub", "year": 2021}])
    assert twin.ok, twin.error
    twin_slot = twin.unwrap()["staged"][0]["slot"]
    assert reg.call("lit.stage_reject", slot=twin_slot,
                    reason_code="duplicate_doi", note="同一篇已经在库").ok

    listing = L.list_candidates(store, request_id=RID)
    assert listing["counts"] == {"pending": 0, "withdrawn": 0, "rejected": 1,
                                 "admitted": 1, "cleared": 0}, listing["counts"]
    assert listing["duplicate_rows"] == 2, listing
    assert listing["duplicate_groups"][0]["slots"] == [first_slot, twin_slot], listing

    text = L.report_markdown(RID, listing["rows"])
    assert "## 已入库（1 篇）" in text and "## 未入库（1 篇）" in text, text
    assert "属重复登记" in text and f"`lit:{lit_id}`" in text, text
    assert L.report_violations(text) == [], L.report_violations(text)


def test_one_batch_never_merges_two_entries_even_for_the_same_paper(reg, store):
    """同一批两条同 DOI ⇒ 仍各占一个槽（`len(staged) == len(entries)`）。

    这不是漏修，是 `agent_a/run_once.py` 的 zip 约定：它用
    `entry_by_slot = dict(zip(slots, fresh_entries))` 决定"哪条候选下的载、登记的哪一篇"
    （`:186-196` 与 `:219-236`）。一次调用里两条同身份的 entry 若是并成一个槽，那条 zip 就
    整体错位一格 ⇒ 下载与登记静默配上另一篇的元数据，而且看起来成功。
    所以闸只治跨调用的重复（真机 `r-000001` 的形态：自动链路一批、A 补 relevance 另一批）；
    同批的重复留在盘上，由 `lit.stage_list` 的 `duplicate_rows` 如实报出来。
    """
    got = reg.call("lit.stage_add", request_id=RID, entries=[
        {"title": "Twin in one batch", "doi": "10.74/twin", "provider": "stub", "year": 2022},
        {"title": "Twin in one batch", "doi": "10.74/twin", "provider": "stub", "year": 2022}])
    assert got.ok, got.error
    data = got.unwrap()
    assert len(data["staged"]) == 2, data
    assert data["updated"] == [], data
    listing = L.list_candidates(store, request_id=RID)
    assert listing["counts"]["pending"] == 2, listing["counts"]
    assert listing["duplicate_rows"] == 2, listing

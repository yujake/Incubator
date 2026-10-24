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
    """④ 撤掉的槽位仍在列表里，且带理由与题名（序号不复用）。"""
    slots = _stage(reg, ["Keep me", "Withdraw me", "Keep me too"])
    res = reg.call("lit.stage_withdraw", slot=slots[1], reason_code="withdrawn_by_reviewer",
                   note="内容与本次检索无关")
    assert res.ok, res.error
    listing = L.list_candidates(store, request_id=RID)
    assert listing["count"] == 3, "撤掉之后那一槽从列表里消失了"
    row = [r for r in listing["rows"] if r["slot"] == slots[1]][0]
    assert row["status"] == "withdrawn"
    assert row["withdrawn_reason"] == "内容与本次检索无关"
    assert row["reason_code"] == "withdrawn_by_reviewer"
    assert row["title"] == "Withdraw me", "撤掉的槽位必须留着题名（记下删掉的是哪一篇）"
    # 补位进的是新序号，旧号不复用
    new_slots = _stage(reg, ["A replacement paper"], doi_prefix="10.11")
    assert new_slots[0] > slots[2], (new_slots, slots)


def test_negative_control_physical_delete_makes_the_slot_disappear(reg, store):
    """④ 的负控：把那一行物理删掉（绕过工具、直接改表）⇒ 同一个判据立刻变红。"""
    slots = _stage(reg, ["Keep me", "Physically delete me"])
    reg.call("lit.stage_withdraw", slot=slots[1], reason_code="withdrawn_by_reviewer")
    assert L.list_candidates(store, request_id=RID, status="withdrawn")["count"] == 1

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


# ---------------------------------------------------------------- ⑥ 一键迁移 + 报告


def test_admit_all_migrates_clears_and_writes_the_report(reg, store):
    """⑥ 一键迁移：过筛的入 literature、其余落终态、写报告（两块都在）。"""
    slots = _stage(reg, ["Migration one", "Migration two", "Migration three"])
    L.reject(store, slots[2], "rejected_low_quality", "只有一行摘要")
    res = reg.call("lit.admit_all", request_id=RID)
    assert res.ok, res.error
    data = res.unwrap()
    assert data["registered"] == 2, data
    assert data["report_path"], data
    listing = L.list_candidates(store, request_id=RID)
    assert listing["counts"]["pending"] == 0, listing["counts"]
    assert listing["counts"]["admitted"] == 2 and listing["counts"]["rejected"] == 1
    text = Path(data["report_path"]).read_text(encoding="utf-8")
    assert L.report_violations(text) == [], L.report_violations(text)
    assert "## 已入库（2 篇）" in text and "## 未入库（1 篇）" in text, text
    assert "理由：rejected_low_quality" in text, text
    # 已入库那一块必须带"它为什么与本次检索相关"
    assert "相关性：" in text


def test_admit_all_over_cap_leaves_cleared_rows_and_no_pending(reg, store):
    """⑥ 超配额的一键迁移：只收 10 条，余下落 `cleared(over_cap)`（带 cleared_at），不物理删。"""
    slots = _stage(reg, [f"Over cap topic {i}" for i in range(12)])
    res = reg.call("lit.admit_all", request_id=RID)
    assert res.ok, res.error
    assert len(res.unwrap()["admitted"]) == 10, res.unwrap()["registered"]
    listing = L.list_candidates(store, request_id=RID)
    assert listing["counts"]["pending"] == 0, listing["counts"]
    assert listing["counts"]["cleared"] == 2, listing["counts"]
    assert listing["count"] == 12, "清空把行删掉了（应当只是换状态）"
    cleared = [r for r in listing["rows"] if r["status"] == "cleared"]
    assert all(r["cleared_at"] and r["clear_reason"] for r in cleared), cleared
    assert all(r["reason_code"] == "over_cap" for r in cleared), cleared


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


def test_run_once_stages_then_admits_and_writes_the_report(store):
    """A 的"登记文献"这一步现在是先 stage 后 admit：候选全进列表、入库的有回填、
    并且这次委托留下报告（已入库 + 未入库两块）。"""
    from conftest import add_request

    add_request(store, RID)
    agent = AgentA(store, providers=[_StubProvider([_cand(0), _cand(1)])],
                   downloader=_OkDownloader(), config={"download": True})
    res = agent.run_once()
    assert res.registered == 2, res.to_dict()
    rows = [r for r in store.rows("lit_candidates") if r["request_id"] == RID]
    assert len(rows) == 2, rows
    assert all(r["status"] == "admitted" and r["lit_id"] for r in rows), rows
    assert len(store.rows("literature")) == 2
    assert res.report_path and Path(res.report_path).is_file(), res.report_path
    assert res.report_admitted == 2, res.to_dict()
    text = Path(res.report_path).read_text(encoding="utf-8")
    # 候选没有 relevance（A 的自动链路暂存时不带它）⇒ 报告判据会记一条
    # "relevance 全空"的读数（只记读数、不拦门，见 litstage._relevance_violations）；
    # 除它之外不许有别的违规。
    assert [v for v in L.report_violations(text) if "relevance" not in v] == [], \
        L.report_violations(text)
    assert len(L.report_violations(text)) == 1, L.report_violations(text)


def test_run_once_registers_at_most_ten_and_clears_the_rest(store):
    """A 的自动链路也守"一次检索至多入库 10 篇"：12 条候选 ⇒ 10 条入库、2 条 cleared。"""
    from conftest import add_request

    add_request(store, RID)
    agent = AgentA(store, providers=[_StubProvider([_cand(i) for i in range(12)])],
                   downloader=_OkDownloader(),
                   config={"download": True, "max_downloads_per_request": 12})
    res = agent.run_once()
    assert res.registered == 10, res.to_dict()
    assert len(store.rows("literature")) == 10
    rows = [r for r in store.rows("lit_candidates") if r["request_id"] == RID]
    assert len(rows) == 12
    codes = sorted((r["status"], r["reason_code"]) for r in rows)
    assert codes.count(("admitted", "")) == 10, codes
    assert codes.count(("cleared", "over_cap")) == 2, codes

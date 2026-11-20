# -*- coding: utf-8 -*-
"""没读到正文就不许判收（业主 2026-11-20 裁定，逐字：
「读内容才能判东西，这样的话保证通过的肯定有内容，且能保证质量」）。

## 现场（lp-ball-13，2026-11-20）

`lit_candidates` 27 条 = 判收 16 + 拒收 11（off_topic 9 / duplicate_doi 2）；
`literature` 16 行里只有 3–4 篇真落地，其余 `download.status=skipped` /
`error=no_local_path` / `bytes 0`，note 逐字「本次无全文：只登记了候选源给出的定位链接
（DOI）」。一条判收候选的 `summary` 是空串、没有 `pdf_url`、`relevance` 是自由散文
（"Meyer-Pajor 关于 l_p^n 单位球截面体积的早期核心文献…"），而 `new_content` 里
写了"Meyer–Pajor 1988 … 奠基性体积估计"这种内容性断言 —— 实际是看题名/年份/provider
元数据 + 自己猜就判收了。设计与现状冲突：`specs/a.py` 的 §2 R14 要求
「把一条命题交给下游之前，必须先在抽出来的正文里定位它」。

## 这一份守五件事

| # | 守什么 | 改前红的样子 |
|---|---|---|
| a | 没有正文（仅题录，连抽取都试过）的候选调 `lit.admit` ⇒ 受控拒 `availability_not_admissible`，逐条给理由码（`metadata_only`），槽位留在候选里 | lp-ball-13：这样的候选被接受并进了库 |
| b | 有正文（真抽取 + `fs.read`，且不只是摘要）⇒ 照常判收；`admitted[].content_read` 是 `true`（正控） | —— |
| c | `content_read=false` 而 `relevance` / `new_content` 写了内容性断言（定理名 / 数值）⇒ 必红，理由码 `content_assertion_without_content` | "Meyer–Pajor 1988 … 奠基性体积估计"这种凭题名猜出来的断言没有任何东西挡 |
| d | 反真空：把 ① 的闸（`litavail.ADMITTABLE_TIERS` + 读证据闸）打桩回旧口径 ⇒ a 的同一笔必须被接受 | —— |
| e | 旧数据兼容：已入库的"仅题录"行仍读得出（`tier_of_literature` 标 `仅题录`、`lit.stage_list` 给 `content_read=false` + 原因），不炸 | —— |
| f | 摘要不算正文：把候选的摘要当正文抽出来、`fs.read` 过 ⇒ 仍拒（`abstract_only`） | "读过摘要"与"读过正文"在读数上同形 |

## 口径只此一处

"读了正文"在 `agentflow.litavail.content_read`（抽读回执 + 候选身份 + 抽读件版本 +
`fs.read` 观察台账 + 摘要之外还要有正文）；四档能不能入在 `litavail.ADMITTABLE_TIERS`；
闸在 `litstage.admission_plan` 的 `_content_assertion_gate` / `_availability_gate` /
`_read_evidence_gate`。这一份打桩打的都是上面这些真身。
"""

from __future__ import annotations

import pathlib

import pytest

from agentflow import litavail as AV
from agentflow import litread as LR
from agentflow import litstage as L
from agentflow import schema as S
from agentflow.store import Store
from agentflow.tools import build_for_role

RID = "r-000001"
BODY = ("This paper studies maximal hyperplane sections of the unit ball of l_p^n. "
        "The main theorem gives an explicit formula in dimension three, and the proof "
        "occupies the rest of the paper. " * 12)
ABSTRACT = ("We study maximal hyperplane sections of the unit ball of l_p^n and give "
            "an explicit formula in dimension three. " * 2)


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


def _stage(reg, titles: list[str], *, rid: str = RID, summaries: dict | None = None,
           relevance: str | None = None) -> list[str]:
    entries = []
    for i, title in enumerate(titles):
        # DOI 由题名派生：同一份用例里多次 `_stage` 不会因 DOI 相同被并进旧槽。
        doi = f"10.9/{abs(hash(title)) % 10_000_000}"
        entry = {"title": title, "doi": doi, "provider": "stub",
                 "year": 2020 + i, "type_code": "J",
                 "relevance": relevance or f"与本次检索相关（{title}）"}
        if summaries and title in summaries:
            entry["summary"] = summaries[title]
        entries.append(entry)
    res = reg.call("lit.stage_add", request_id=rid, entries=entries)
    assert res.ok, res.error
    return [x["slot"] for x in res.unwrap()["staged"]]


def _readback(reg, rid: str = RID):
    res = reg.call("lit.stage_list", request_id=rid)
    assert res.ok, res.error
    return res


def _admit(reg, items: list[dict], *, rid: str = RID):
    return reg.call("lit.admit", items=items, request_id=rid)


def _write_source(store: Store, slot: str, body: str) -> pathlib.Path:
    p = store.root / "downloads" / f"cand-{slot}.txt"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    return p


def _read(store: Store, reg, slot: str, body: str = BODY):
    """抽读 + fs.read（真机那两步；判据核的是"同一版、且不只是摘要"）。"""
    p = _write_source(store, slot, body)
    ext = reg.call("text.extract", path=str(p.relative_to(store.root).as_posix()),
                   lit_id=f"cand:{slot}")
    assert ext.ok, ext.error
    got = reg.call("fs.read", path=ext.unwrap()["path"])
    assert got.ok, got.error
    return ext


def _attempt(store: Store, slot: str, *, rid: str = RID) -> dict:
    """一条"试过、但拿不到可读正文"的回执（真机由失败的 `text.extract` 写）。"""
    return AV.record_read(store.root, rid, str(slot), LR.FULLTEXT_EXTRACT_FAILED,
                          source="fixture:no-bytes", note="text.extract.no_text_layer")


def _lit_titles(store: Store) -> list[str]:
    return [str(r.get("title") or "") for r in store.rows("literature")]


# ====================================================================== a 没有正文不许判收


def test_a_a_candidate_without_fulltext_is_refused_by_name(store: Store, reg) -> None:
    """a. 仅题录（试过抽取也没拿到正文）⇒ 受控拒，逐条给理由码；一行都不进库。

    改前读数（lp-ball-13）：这种候选被 `lit.admit` 接受，进了 `literature`。
    """
    slots = _stage(reg, ["Metadata only one"])
    _readback(reg)
    _attempt(store, slots[0])

    res = _admit(reg, [{"slot": slots[0], "availability": AV.METADATA_ONLY}])
    assert not res.ok, "没有正文的候选居然被接受了"
    assert res.meta["kind"] == "availability_not_admissible", res.meta
    bad = res.meta["availability_bad"]
    assert [row["slot"] for row in bad] == slots, bad
    assert bad[0]["code"] == "metadata_only", bad
    # 受控形态：槽位是"没判收"（仍在候选里），不是被静默丢掉
    unjudged = res.meta["unjudged_no_content"]
    assert [row["slot"] for row in unjudged] == slots, unjudged
    assert unjudged[0]["code"] == "metadata_only", unjudged
    row = next(r for r in store.rows("lit_candidates") if r["slot"] == slots[0])
    assert row["status"] == "pending", row
    assert _lit_titles(store) == [], "被拒却写进了 literature"

    # 没有定位符的仅题录也一样拒（连题录都登记不了）
    with store.tx("lit_candidates", "counters", actor="t", note="no locator") as tx:
        bare = tx.alloc_id("candidate")
    with store.tx("lit_candidates", actor="t", note="no locator") as tx:
        tx.upsert("lit_candidates", S.LitCandidate(
            slot=bare, request_id=RID, batch=1, status="pending",
            title="No locator paper", doi=None, url="",
            relevance="题目相关但没有可定位的号").to_dict(), note="no locator")
    reg.call("lit.stage_list", request_id=RID)
    res2 = _admit(reg, [{"slot": bare, "availability": AV.METADATA_ONLY}])
    assert not res2.ok and res2.meta["kind"] == "availability_not_admissible", res2.meta
    assert res2.meta["availability_bad"][0]["code"] in ("no_fulltext", "metadata_only"), res2.meta


# ====================================================================== b 有正文照常判收


def test_b_a_candidate_with_real_fulltext_is_admitted(store: Store, reg) -> None:
    """b. 正控：真抽取 + `fs.read`（正文比摘要长得多）⇒ 照常判收、`content_read=true`。"""
    slot = _stage(reg, ["Read after downloading"])[0]
    _readback(reg)
    _read(store, reg, slot)

    res = _admit(reg, [{"slot": slot, "availability": AV.READABLE}])
    assert res.ok, res.error
    data = res.unwrap()
    assert len(data["admitted"]) == 1, data
    assert data["admitted"][0]["content_read"] is True, data["admitted"]
    assert data["admitted"][0]["lit_id"] == "", "判收不该发号"
    submit = reg.call("lit.admit_all", request_id=RID)
    assert submit.ok, submit.error
    assert _lit_titles(store) == ["Read after downloading"]


# ====================================================================== c 内容性断言必须有 content_read


def test_c_a_content_claim_without_reading_is_red(store: Store, reg) -> None:
    """c. `content_read=false` 而 relevance 写了定理名/数值 ⇒ 必红（不是"没查"）。

    改前读数：lp-ball-13 的 relevance 写"Meyer-Pajor … 早期核心文献"、
    `new_content` 写"Meyer–Pajor 1988 … 奠基性体积估计"，而这一条从未读过正文。
    """
    slot = _stage(reg, ["Claim from the title only"],
                  relevance="Meyer-Pajor 1988 的定理给出体积上界 ≤ 常数")[0]
    _readback(reg)
    res = _admit(reg, [{"slot": slot}])
    assert not res.ok, "凭题名猜出来的内容性断言居然被接受"
    assert res.meta["kind"] == L.CONTENT_CLAIM_WITHOUT_READ, res.meta
    assert res.meta["content_assertions"][0]["slot"] == slot, res.meta
    assert res.meta["content_assertions"][0]["field"] == "relevance", res.meta
    row = next(r for r in store.rows("lit_candidates") if r["slot"] == slot)
    assert row["status"] == "pending", row

    # 对照：同样没读正文，但 relevance 只写"为什么进候选" ⇒ 不是这一档的红
    # （它落 missing_availability / availability_not_admissible，两档分得开）。
    plain = _stage(reg, ["Plain relevance"],
                   relevance="题名与本次检索相关")[0]
    _readback(reg)
    res2 = _admit(reg, [{"slot": plain}])
    assert not res2.ok and res2.meta["kind"] == "missing_availability", res2.meta


# ====================================================================== d 反真空


def test_d_negative_control_restoring_the_old_admittable_set_lets_it_in(
        store: Store, reg, monkeypatch: pytest.MonkeyPatch) -> None:
    """d. 反真空：把 ① 的闸打桩回旧口径 ⇒ a 的同一笔必须被接受。

    打的是两处真身：`litavail.ADMITTABLE_TIERS`（"哪些档能入"）与
    `litstage._read_evidence_gate`（旧口径下仅题录靠一条 `extract_failed` 回执可入）。
    只打其中一处不够 —— 那正好证明"a 的红"是这两处一起给的，不是别的原因。
    """
    slot = _stage(reg, ["Old policy probe"])[0]
    _readback(reg)
    _attempt(store, slot)

    before = _admit(reg, [{"slot": slot, "availability": AV.METADATA_ONLY}])
    assert not before.ok, before

    monkeypatch.setattr(AV, "ADMITTABLE_TIERS", (AV.READABLE, AV.METADATA_ONLY))
    monkeypatch.setattr(L, "_read_evidence_gate", lambda *a, **k: None)
    after = _admit(reg, [{"slot": slot, "availability": AV.METADATA_ONLY}])
    assert after.ok, f"打桩回旧口径之后仍被拒 ⇒ 上面那次拒绝不是这道闸给的（{after.error}）"
    assert len(after.unwrap()["admitted"]) == 1, after.unwrap()


# ====================================================================== e 旧数据兼容


def test_e_an_admitted_metadata_only_row_still_reads(store: Store, reg) -> None:
    """e. 改之前已经入库的"仅题录"行仍读得出：标注清楚、不炸。"""
    from conftest import add_literature

    add_literature(store, "000000", title="Legacy metadata-only row", doi="10.55/old",
                   path=None, download={"status": "skipped", "bytes": 0,
                                        "error": "no_local_path"})
    row = next(r for r in store.rows("literature") if r["lit_id"] == "000000")
    assert AV.tier_of_literature(row, store.root) == AV.METADATA_ONLY
    assert AV.describe_tier(AV.tier_of_literature(row, store.root)) == "仅题录（metadata_only）"

    # 旧的候选行（已判收、没有正文）也读得出来，并带上 content_read 读数 —— 不炸。
    with store.tx("lit_candidates", "counters", actor="t", note="legacy") as tx:
        slot = tx.alloc_id("candidate")
    with store.tx("lit_candidates", actor="t", note="legacy") as tx:
        tx.upsert("lit_candidates", S.LitCandidate(
            slot=slot, request_id=RID, batch=1, status="admitted",
            title="Legacy candidate", relevance="旧数据", lit_id="000000",
            admitted_at=S.now_iso()).to_dict(), note="legacy")
    listing = reg.call("lit.stage_list", request_id=RID)
    assert listing.ok, listing.error
    got = next(r for r in listing.unwrap()["rows"] if r["slot"] == slot)
    assert got["status"] == "admitted", got
    assert got["content_read"] is False, got
    assert str(got.get("content_read_why") or ""), got  # "没查"也要说得出为什么
    # 补一条仅题录判定（真机 lp-ball-13 那一档）之后，读数变成 metadata_only ——
    # 仍读得出、只标注，不炸。
    AV.record_availability(store.root, RID, slot, AV.METADATA_ONLY)
    AV.record_read(store.root, RID, slot, LR.FULLTEXT_EXTRACT_FAILED,
                   source="fixture:no-bytes", note="text.extract.no_text_layer")
    listing = reg.call("lit.stage_list", request_id=RID)
    got = next(r for r in listing.unwrap()["rows"] if r["slot"] == slot)
    assert got["content_read"] is False, got
    assert "metadata_only" in str(got.get("content_read_why") or ""), got


# ====================================================================== f 摘要不算正文


def test_f_the_abstract_alone_is_not_content(store: Store, reg) -> None:
    """f. 把摘要当正文抽出来、`fs.read` 过 ⇒ 仍拒（`abstract_only`）。

    "读过摘要"与"读过正文"必须在读数上分得开（业主裁定 ②：摘要最多用于初排/去重）。
    """
    slot = _stage(reg, ["Abstract only paper"], summaries={"Abstract only paper": ABSTRACT})[0]
    _readback(reg)
    _read(store, reg, slot, body=ABSTRACT)

    # 台账里 A 可以报 readable —— 但机器的 content_read 是 false
    res = _admit(reg, [{"slot": slot, "availability": AV.READABLE}])
    assert not res.ok, "只读了摘要居然被当成读了正文"
    assert res.meta["kind"] == "no_read_evidence", res.meta
    problems = res.meta["read_problems"]
    assert problems[0]["slot"] == slot, problems
    assert problems[0]["state"] == "abstract_only", problems
    assert AV.content_read(store.root, slot,
                           next(r for r in store.rows("lit_candidates")
                                if r["slot"] == slot))[0] is False

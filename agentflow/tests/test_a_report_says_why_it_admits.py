# -*- coding: utf-8 -*-
"""抽读回执落进 A 稿，作为批准 / 拒绝入库的理由栏（业主 2026-11-16 AR1 裁定，逐字）。

## 改前读数（VC1 核实）

| 读数 | 改前 |
|---|---|
| `metadata_only` | 零读可入（连一次抽读尝试都没有也能进库）—— 与"有回执才准入"冲突 |
| 报告「已入库」 | 只有 `相关性：` + `可得性：`；没有"判定"，也没有回执摘要（字数 / 指纹 / 抽读件 / 时间） |
| 报告「未入库」 | 只有理由码 + `可得性：`；没有"这条读过什么、凭什么拒"的回执行 |
| `data/lit_reads.jsonl` | 已经存在（AV1），但报告渲染里一次都没有读它 |

## 这一份守五件事

| # | 守什么 | 改前红的样子 |
|---|---|---|
| a | 有回执 + 批准 ⇒ 报告该行三件齐全（回执摘要 / 判定：批准入库 / 理由） | 报告只有 `相关性` 与档位名 |
| b | 有回执 + 拒绝 ⇒ 同样三件齐全（拒绝也要写理由） | 未入库块只有理由码，没有回执行 |
| c | 无回执（连尝试都没有）⇒ `no_read_evidence` 整批拒、逐槽点名；`metadata_only` 不许过 | 零读可入，10 条题录直接进库 |
| d | 反真空：把"读过"判据打桩成恒"试过" ⇒ c 必红；把回执摘要摘掉 ⇒ a 必红 | —— |
| e | 报告里的回执摘要必须与 `data/lit_reads.jsonl` 同源（不另写一份对不上的） | 报告与台账可以各说各的 |
| f | 仅题录（批准）也要在报告里写出"没拿到可读字节 + 尝试过什么" | 只有档位名，看不出试过没有 |

## 口径只此一处

"读过"在 `agentflow.litavail.check_read`（回执 + 候选身份 + 抽读件版本 + `fs.read`
观察台账）；闸在 `litstage._read_evidence_gate`；报告渲染在
`litstage.report_markdown` / `_receipt_summary`，它的输入是 `write_report` 现读的
`litavail.receipts_by_slot`。这一份打桩打的是这三个真身，不另写判据。
"""

from __future__ import annotations

import pathlib

import pytest

from agentflow import litavail as AV
from agentflow import litread as LR
from agentflow import litstage as L
from agentflow.store import Store
from agentflow.tools import build_for_role

RID = "r-000001"
BODY = ("This paper studies maximal hyperplane sections of the unit ball of l_p^n. "
        "The main theorem gives an explicit formula in dimension three. " * 12)


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
                "relevance": f"读过正文之后判断：与本次检索相关（{t}）"}
               for i, t in enumerate(titles)]
    res = reg.call("lit.stage_add", request_id=rid, entries=entries)
    assert res.ok, res.error
    return [x["slot"] for x in res.unwrap()["staged"]]


def _readback(reg, rid: str = RID):
    res = reg.call("lit.stage_list", request_id=rid)
    assert res.ok, res.error
    return res


def _admit(reg, items: list[dict], *, rid: str = RID):
    return reg.call("lit.admit", items=items, request_id=rid)


def _write_source(store: Store, slot: str, body: str = BODY) -> pathlib.Path:
    p = store.root / "downloads" / f"candidate-{slot}.txt"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    return p


def _extract(store: Store, reg, slot: str, body: str = BODY):
    p = _write_source(store, slot, body)
    res = reg.call("text.extract", path=str(p.relative_to(store.root).as_posix()),
                   lit_id=f"cand:{slot}")
    assert res.ok, res.error
    return res


def _fs_read(reg, extract_res):
    got = reg.call("fs.read", path=extract_res.unwrap()["path"])
    assert got.ok, got.error
    return got


def _submit(reg, rid: str = RID):
    """提交那一刻（2026-11-16 Q1）：批量注册 → 回填 → 清表。"""
    got = reg.call("lit.admit_all", request_id=rid)
    assert got.ok, got.error
    return got


def _report_text(store: Store, rid: str = RID) -> str:
    written = L.write_report(store, rid)
    return pathlib.Path(written["path"]).read_text(encoding="utf-8")


# ====================================================================== a 批准


def test_a_an_approved_row_carries_receipt_verdict_and_reason(store: Store, reg) -> None:
    """a. 有回执 + 批准 ⇒ 报告该行三件齐全：回执摘要 / 判定：批准入库 / 理由。

    回执摘要的每一格都要来自 `data/lit_reads.jsonl`（字数 / sha 指纹 / 抽读件路径 / 时间）。
    """
    slot = _stage(reg, ["Approved after reading"])[0]
    _readback(reg)
    ext = _extract(store, reg, slot)
    _fs_read(reg, ext)
    ok = _admit(reg, [{"slot": slot, "availability": AV.READABLE}])
    assert ok.ok, ok.error
    # Q1：判收只是"有入库资格"，报告的「批准入库」出现在提交回填之后。
    _submit(reg)

    receipt = AV.receipts_by_slot(store.root)[slot]
    assert receipt["tier"] == LR.FULLTEXT_OK and receipt["chars"] > 0, receipt
    text = pathlib.Path(L.report_path(store, RID)).read_text(encoding="utf-8")
    assert "判定：批准入库" in text, text
    assert f"读过 {receipt['chars']} 字" in text, text
    assert receipt["sha256"][:12] in text, text
    assert receipt["text"] in text, text
    assert receipt["at"] in text, text
    assert "理由（相关性）：" in text and "读过正文之后判断" in text, text

    # 反真空：把回执摘要摘掉 ⇒ a 的判据必红（否则"三件齐全"可能是别处凑出来的）
    rows = [r for r in store.rows("lit_candidates") if str(r.get("slot")) == slot]
    tiers = AV.tiers_by_slot(store.root)
    reads = AV.receipts_by_slot(store.root)
    original = L._receipt_summary
    try:
        L._receipt_summary = lambda receipt: ""
        stripped = L.report_markdown(RID, rows, availability=tiers, reads=reads)
    finally:
        L._receipt_summary = original
    assert f"读过 {receipt['chars']} 字" not in stripped, stripped
    assert receipt["sha256"][:12] not in stripped, stripped


# ====================================================================== b 拒绝


def test_b_a_rejected_row_carries_receipt_verdict_and_reason(store: Store, reg) -> None:
    """b. 有回执 + 拒绝 ⇒ 同样三件齐全：拒也要写理由（受控码 + A 自己那一句）。"""
    slot = _stage(reg, ["Rejected after reading"])[0]
    _readback(reg)
    # 抽出来是乱码 ⇒ 一条 extract_failed 的尝试回执（"试过、拿不到可读文本"）
    p = _write_source(store, slot, "ok \x00\x00 broken")
    failed = reg.call("text.extract", path=str(p.relative_to(store.root).as_posix()),
                      lit_id=f"cand:{slot}")
    assert not failed.ok and failed.meta["kind"] == "garbled_text", failed.meta
    rejected = reg.call("lit.stage_reject", slot=slot,
                        reason_code="rejected_low_quality",
                        note="抽出来的正文是乱码（NUL 字符），质量不够，判拒")
    assert rejected.ok, rejected.error

    receipt = AV.receipts_by_slot(store.root)[slot]
    text = _report_text(store)
    assert "判定：拒绝入库" in text, text
    assert "抽读档位 extract_failed（没拿到可读字节）" in text, text
    assert "尝试过" in text and "text.extract.garbled_text" in text, text
    assert f"时间 {receipt['at']}" in text, text
    assert "理由：rejected_low_quality" in text, text
    assert "质量不够，判拒" in text, text


# ====================================================================== c 无回执不许判准入


def test_c_no_attempt_means_no_admission_and_metadata_only_is_not_a_loophole(
        store: Store, reg, monkeypatch: pytest.MonkeyPatch) -> None:
    """c. 没有正文 ⇒ 受控拒、逐槽点名；`metadata_only` 不是入库券（2026-11-20）。

    改前：零读取尝试的仅题录被 `no_read_evidence` 拒，有尝试回执的可以入；
    改后：有没有尝试都不许判收 —— 拒在可读性闸上，理由码 `metadata_only`。

    反真空：把这道闸打桩回旧口径（`ADMITTABLE_TIERS` 加回仅题录 + 读证据闸放行）
    ⇒ 同一笔就进得去，于是上面那次拒绝不能来自配额 / 重叠 / 回读。
    """
    slots = _stage(reg, ["Never tried one", "Never tried two"])
    _readback(reg)
    items = [{"slot": s, "availability": AV.METADATA_ONLY} for s in slots]
    res = _admit(reg, items)
    assert not res.ok, "没有正文的仅题录居然入库了"
    assert res.meta["kind"] == "availability_not_admissible", res.meta
    assert {row["code"] for row in res.meta["availability_bad"]} == {"no_fulltext"}, res.meta
    for slot in slots:
        assert slot in str(res.error), (slot, res.error)
    assert [r for r in store.rows("literature")] == []

    # 反真空：把旧口径打回去（仅题录可入 + 读证据闸放行）⇒ 同一笔能进
    monkeypatch.setattr(AV, "ADMITTABLE_TIERS", (AV.READABLE, AV.METADATA_ONLY))
    monkeypatch.setattr(L, "_read_evidence_gate", lambda *a, **k: None)
    after = _admit(reg, items)
    assert after.ok, (f"打桩回旧口径之后仍被拒 ⇒ 闸不是长在 `litavail.ADMITTABLE_TIERS` 上"
                      f"（{after.error}）")
    # Q1：判收不发号 —— 进库要等提交那一刻（打桩仍然要开着，提交时同一道闸再核一次）。
    _submit(reg)
    assert len(store.rows("literature")) == 2


# ====================================================================== d 绑候选身份


def test_d_readable_reads_this_candidates_own_extract(store: Store, reg,
                                                      monkeypatch: pytest.MonkeyPatch) -> None:
    """d. `readable` 读的必须是这一份候选的抽读件（VC1 P1-4）。

    两种冒充都拒：
    ① 回执的身份三格不是这一条候选（题名对不上）⇒ `other_candidate`；
    ② 回执指向另一条候选的 `cand-<别的槽>.txt` ⇒ `other_text`。
    """
    slots = _stage(reg, ["Bound candidate", "Impostor receipt", "Borrowed text"])
    _readback(reg)
    first = _extract(store, reg, slots[0])
    _fs_read(reg, first)
    ok = _admit(reg, [{"slot": slots[0], "availability": AV.READABLE}])
    assert ok.ok, ok.error

    # ① 身份对不上：正文/版本都对，只是回执记的是另一篇
    for slot in slots[1:]:
        _fs_read(reg, _extract(store, reg, slot))
    good = dict(AV.receipts_by_slot(store.root)[slots[1]])
    AV.record_read(store.root, RID, slots[1], LR.FULLTEXT_OK,
                   source=good["source"], text=good["text"], text_abs=good["text_abs"],
                   text_version=good["text_version"], chars=good["chars"],
                   sha256=good["sha256"], note="伪造：另一篇的身份",
                   candidate={"request_id": RID, "title": "Another paper entirely",
                              "doi": "10.999/other"})
    forged = _admit(reg, [{"slot": slots[1], "availability": AV.READABLE}])
    assert not forged.ok and forged.meta["kind"] == "no_read_evidence", forged.meta
    assert forged.meta["read_problems"][0]["state"] == "other_candidate", forged.meta
    assert slots[1] in str(forged.error), forged.error

    # ② 正文指向另一条候选的抽读件（名字里是别的槽位）
    borrowed = dict(AV.receipts_by_slot(store.root)[slots[2]])
    other = AV.receipts_by_slot(store.root)[slots[0]]
    AV.record_read(store.root, RID, slots[2], LR.FULLTEXT_OK,
                   source=borrowed["source"], text=other["text"], text_abs=other["text_abs"],
                   text_version=other["text_version"], chars=int(other["chars"]),
                   sha256=str(other["sha256"]), note="伪造：借别人的抽读件",
                   candidate={"request_id": RID, "title": borrowed["candidate"]["title"],
                              "doi": borrowed["candidate"]["doi"]})
    stolen = _admit(reg, [{"slot": slots[2], "availability": AV.READABLE}])
    assert not stolen.ok and stolen.meta["kind"] == "no_read_evidence", stolen.meta
    assert stolen.meta["read_problems"][0]["state"] == "other_text", stolen.meta
    assert "cand-" in str(stolen.error), stolen.error


# ====================================================================== f 仅题录（批准）


def test_f_a_metadata_only_candidate_is_never_approved(store: Store, reg) -> None:
    """f. 仅题录不再被批准（2026-11-20 业主：「读内容才能判东西」）。

    改前：试过抽取、拿不到正文的仅题录可以「批准入库」，报告里写"尝试过什么"；
    改后：它没有正文 ⇒ 判收一律受控拒、行留在候选（可判拒），报告里不会出现
    「判定：批准入库」。这条判据守的就是"报告里不会再冒出这种批准"。
    """
    slot = _stage(reg, ["Attempted but no bytes"])[0]
    _readback(reg)
    p = _write_source(store, slot, "ok \x00\x00 broken")
    failed = reg.call("text.extract", path=str(p.relative_to(store.root).as_posix()),
                      lit_id=f"cand:{slot}")
    assert not failed.ok, failed.meta
    res = _admit(reg, [{"slot": slot, "availability": AV.METADATA_ONLY}])
    assert not res.ok, "没有正文的仅题录被批准了"
    assert res.meta["kind"] == "availability_not_admissible", res.meta
    assert res.meta["availability_bad"][0]["code"] == "metadata_only", res.meta
    row = next(r for r in store.rows("lit_candidates") if r["slot"] == slot)
    assert row["status"] == "pending", row
    assert [r for r in store.rows("literature")] == []

    # 判拒之后报告只说"未入库 + 为什么"，绝不会有一条批准
    assert reg.call("lit.stage_reject", slot=slot, reason_code="rejected_low_quality",
                    note="PDF 无文本层，抽出来是乱码").ok
    text = _report_text(store)
    assert "判定：批准入库" not in text, text
    assert "rejected_low_quality" in text and "乱码" in text, text


# ====================================================================== e 同源


def test_e_the_receipt_in_the_report_is_the_ledger_row(store: Store, reg) -> None:
    """e. 报告里的回执摘要与 `data/lit_reads.jsonl` 同源：换一条回执，报告跟着换。"""
    slot = _stage(reg, ["Same source reading"])[0]
    _readback(reg)
    ext = _extract(store, reg, slot)
    _fs_read(reg, ext)
    assert _admit(reg, [{"slot": slot, "availability": AV.READABLE}]).ok
    # Q1：交报告 + 批量注册 + 回填发生在提交那一刻；定稿落盘之后不再重渲染
    # （受控拒 `already_settled`，见第 ⑨ 条）。所以"报告与台账同源"用重渲染
    # 验：`report_markdown` 是纯函数，回执换了、它渲染出来的摘要就换。
    _submit(reg)

    ledger = (store.root / "data" / AV.READ_LEDGER_NAME)
    line = next(json_line for json_line in ledger.read_text(encoding="utf-8").splitlines()
                if f'"{slot}"' in json_line)
    assert str(AV.receipts_by_slot(store.root)[slot]["chars"]) in line, line

    def _render() -> str:
        rows = [r for r in store.rows("lit_candidates") if r["request_id"] == RID]
        return L.report_markdown(RID, rows, availability=AV.tiers_by_slot(store.root),
                                 reads=AV.receipts_by_slot(store.root), phase="final")

    final_text = pathlib.Path(L.report_path(store, RID)).read_text(encoding="utf-8")
    assert f"读过 {AV.receipts_by_slot(store.root)[slot]['chars']} 字" in final_text, final_text
    first = _render()
    assert f"读过 {AV.receipts_by_slot(store.root)[slot]['chars']} 字" in first, first

    # 同槽位再落一条更新的回执（真机是"过期抽读件由后写的覆盖先写的"）⇒ 重渲染必须
    # 跟着来源换，而不是继续打印写报告那一刻缓存下来的旧摘要。
    latest = AV.receipts_by_slot(store.root)[slot]
    AV.record_read(store.root, RID, slot, LR.FULLTEXT_OK,
                   source=latest["source"], text=latest["text"],
                   text_abs=latest["text_abs"], text_version=latest["text_version"],
                   chars=4242, sha256="a" * 64, note="第二次抽读",
                   candidate=latest.get("candidate"))
    second = _render()
    assert "读过 4242 字" in second, second
    assert "a" * 12 in second, second
    assert f"读过 {latest['chars']} 字" not in second, second

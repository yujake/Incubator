# -*- coding: utf-8 -*-
"""A 逐条读文本再判：`readable` 是判断，不是自报（业主 2026-11-16 裁定 3）。

## 现场（AH6，`projects/lp-ball-2`，只读回看）

| 读数 | 值 |
|---|---|
| A1 的 43 步里 `text.extract` | 0 次 |
| A1 对候选的 `fs.read` | 0 次 |
| A1 整趟 `lit.stage_list` | 0 次 |
| 07:31:29 | 一次 `lit.stage_add` 把 12 条候选连同 12 条 `relevance` 写进列表 |
| 07:32:41 | 一次 `lit.admit` 10 条通过 |
| 结果 | 12 条入库里 10 条只有题录、2 条有字节但抽取两次乱码 |

所以 AH6 的 `relevance` 不是"读过之后的判断"，是"批量写死的那一句"。AQ1 把回读与四档
做实了，但可读性那一档仍是 A 自报：没有任何一处能回答"这一条到底抽没抽出正文、A 读没读"。

## 这份判据守五件事

| # | 守什么 | 改前红的样子 |
|---|---|---|
| a | 标 `readable` 但没有任何抽读记录 ⇒ 受控拒 `no_read_evidence`，逐条点名 | 07:32:41 那 10 条就是这样进来的 |
| b | 抽过但没读（没有 `fs.read` 那份 `.txt`）也算没读 ⇒ 仍拒；读了才放行 | "抽了"被当成"读了" |
| c | 有字节（抽过）却报 `metadata_only` ⇒ 拒；零读取尝试的仅题录也拒（AR1：仅题录 = 试过一次、拿不到可读文本）—— 只有带 `extract_failed` 尝试回执的那一条可入 | 2 条乱码 PDF 被折成仅题录；零读可入 |
| d | 逐条判断落读数：可读性台账里带 `relevance` 与抽读指纹（字数/哈希），报告逐条写"读过 N 字" | 台账只有档位、报告没有"读过什么" |
| e | AH6 的批量形状（12 条 relevance 一次写死、零抽读）⇒ 拒信点名那几条；把闸打桩关掉 ⇒ 同一笔能进（反真空） | 批量写死没有任何东西挡 |

## 口径只此一处

"读过"的判据在 `agentflow.litavail.check_read`（抽读档位 + 抽读件版本 + `fs.read`
观察台账）；提交闸在 `litstage._read_evidence_gate`。这一份打桩打的是这两个真身，
不另写一份判据。
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
    """暂存一批候选（每条都带 relevance —— 这一份测的是它之外的那道证据）。"""
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


def _admit(reg, items: list[dict], *, rid: str = RID):
    return reg.call("lit.admit", items=items, request_id=rid)


def _submit(reg, *, rid: str = RID):
    """提交那一刻：批量注册 + 回填 + 清表（2026-11-16 Q1：判收不发号）。"""
    got = reg.call("lit.admit_all", request_id=rid)
    assert got.ok, got.error
    return got


def _write_source(store: Store, slot: str, body: str = BODY) -> pathlib.Path:
    p = store.root / "downloads" / f"candidate-{slot}.txt"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    return p


def _extract(store: Store, reg, slot: str, body: str = BODY):
    """把一条候选的正文抽出来（`cand:<slot>` 是"这一条候选"的绑定写法）。"""
    p = _write_source(store, slot, body)
    res = reg.call("text.extract", path=str(p.relative_to(store.root).as_posix()),
                   lit_id=f"cand:{slot}")
    assert res.ok, res.error
    return res


def _fs_read(reg, extract_res):
    got = reg.call("fs.read", path=extract_res.unwrap()["path"])
    assert got.ok, got.error
    return got


def _lit_titles(store: Store) -> list[str]:
    return [str(r.get("title") or "") for r in store.rows("literature")]


# ====================================================================== a 没抽就判 readable


def test_a_readable_claim_without_an_extract_is_refused_by_name(store: Store, reg) -> None:
    """a. 标 `readable` 却零抽读 ⇒ `no_read_evidence`，逐条点名，一条都不进库。

    改前读数（AH6）：07:32:41 一次 `lit.admit` 10 条通过，而那 10 条此前整趟
    `text.extract` 0 次。
    """
    slots = _stage(reg, ["Never extracted one", "Never extracted two"])
    _readback(reg)
    res = _admit(reg, [{"slot": s, "availability": AV.READABLE} for s in slots])
    assert not res.ok, "没有任何抽读记录，readable 居然入库了"
    assert res.meta["kind"] == "no_read_evidence", res.meta
    for slot in slots:
        assert slot in str(res.error), (slot, res.error)
    assert "text.extract" in str(res.error), res.error
    assert _lit_titles(store) == [], "被拒却写进了 literature"
    assert AV.receipts_by_slot(store.root) == {}, "没抽过却留下抽读记录"


# ====================================================================== b 抽了不读也算没读


def test_b_extracted_but_not_read_is_still_not_read(store: Store, reg) -> None:
    """b. 抽过 ≠ 读过：没有 `fs.read` 那份 `.txt` ⇒ 仍拒；读了同一版才放行。"""
    slots = _stage(reg, ["Extracted only"])
    _readback(reg)
    ext = _extract(store, reg, slots[0])
    # 抽读记录已经落盘；但 A 还没读那份正文
    receipt = AV.receipts_by_slot(store.root)[slots[0]]
    assert receipt["tier"] == LR.FULLTEXT_OK and receipt["chars"] > 0, receipt
    res = _admit(reg, [{"slot": slots[0], "availability": AV.READABLE}])
    assert not res.ok and res.meta["kind"] == "no_read_evidence", res.meta
    assert "fs.read" in str(res.error), res.error

    _fs_read(reg, ext)
    ok = _admit(reg, [{"slot": slots[0], "availability": AV.READABLE}])
    assert ok.ok, ok.error
    # Q1：判收之后要提交才进库（判收只发"有入库资格"，不发号）
    _submit(reg)
    assert _lit_titles(store) == ["Extracted only"]


# ====================================================================== c 仅题录的边界


def test_c_metadata_only_is_not_an_admission_ticket(store: Store, reg) -> None:
    """c. 仅题录不再可入（2026-11-20 业主：「读内容才能判东西」）。

    改前：零读取尝试拒绝、有 `extract_failed` 回执的仅题录可以入；
    改后：有没有抽取尝试都不许判收 —— 没有正文就没有入库资格。有字节的那一条
    可以改报 `readable`（先抽读 + `fs.read`，那是判据 b）；不改报就只能判拒，
    并把"为什么没读到"写在候选行上。
    """
    slots = _stage(reg, ["Has bytes", "No bytes"])
    _readback(reg)
    ext = _extract(store, reg, slots[0])
    _fs_read(reg, ext)

    res = _admit(reg, [
        {"slot": slots[0], "availability": AV.METADATA_ONLY},
        {"slot": slots[1], "availability": AV.METADATA_ONLY},
    ])
    assert not res.ok, "没有正文的仅题录居然都能判收"
    assert res.meta["kind"] == "availability_not_admissible", res.meta
    assert {row["code"] for row in res.meta["availability_bad"]} == {"no_fulltext"}, \
        res.meta
    assert _lit_titles(store) == []

    # 第二条真的试过一次抽取（乱码 ⇒ extract_failed 回执）—— 它仍不许判收：
    # 那条回执只说明"试过、拿不到正文"，不是入库券。
    p = _write_source(store, slots[1], "ok \x00\x00 broken")
    failed = reg.call("text.extract", path=str(p.relative_to(store.root).as_posix()),
                      lit_id=f"cand:{slots[1]}")
    assert not failed.ok and failed.meta["kind"] == "garbled_text", failed.meta
    assert AV.receipts_by_slot(store.root)[slots[1]]["tier"] == LR.FULLTEXT_EXTRACT_FAILED

    res = _admit(reg, [{"slot": slots[1], "availability": AV.METADATA_ONLY}])
    assert not res.ok and res.meta["kind"] == "availability_not_admissible", res.meta
    assert res.meta["availability_bad"][0]["code"] == "metadata_only", res.meta

    # 两条的出路都是受控判拒（行留着、理由在行上），不是判收
    for slot, note in ((slots[0], "有字节但报仅题录，按闸的读数判拒"),
                       (slots[1], "抽出来是乱码，拿不到可读正文")):
        assert reg.call("lit.stage_reject", slot=slot,
                        reason_code="rejected_low_quality", note=note).ok
    assert len([r for r in store.rows("lit_candidates")
                if r["status"] == "rejected"]) == 2
    assert _lit_titles(store) == []


# ====================================================================== d 逐条判断落读数


def test_d_every_admitted_item_leaves_its_own_reading_and_reason(store: Store, reg) -> None:
    """d. 逐条判断可查：可读性台账一行一条（档位 + relevance + 抽读字数/指纹），
    报告三块逐条列"读过 N 字"；拒收的那一条理由落在行上、报告未入库块里。"""
    slots = _stage(reg, ["Read and kept one", "Read and kept two", "Rejected one"])
    _readback(reg)
    for slot in slots[:2]:
        _fs_read(reg, _extract(store, reg, slot, BODY + slot))
    ok = _admit(reg, [{"slot": s, "availability": AV.READABLE} for s in slots[:2]])
    assert ok.ok, ok.error
    # 第三条：抽过但乱码 ⇒ 只能按 extract_failed 判拒（受控理由码 + 一句为什么）
    p = _write_source(store, slots[2], "ok \x00\x00 broken")
    garbled = reg.call("text.extract", path=str(p.relative_to(store.root).as_posix()),
                       lit_id=f"cand:{slots[2]}")
    assert not garbled.ok, "夹具应当抽失败"
    reg.call("lit.stage_reject", slot=slots[2], reason_code="rejected_low_quality",
             note="抽出来的正文是乱码（NUL 字符），不能当正文")

    # 可读性台账：每一条一行、带 relevance 与抽读指纹
    avail = [r for r in AV.read_records(store.root) if r.get("kind") == "availability"]
    by_slot = {str(r.get("slot")): r for r in avail}
    for slot in slots[:2]:
        rec = by_slot[slot]
        assert rec["tier"] == AV.READABLE, rec
        assert str(rec.get("relevance") or "").strip(), rec
        read = rec.get("read") or {}
        assert int(read.get("chars") or 0) > 0, rec
        assert str(read.get("sha256") or ""), rec
    # 报告：已入库两条各带"读过 N 字"，未入库那条带理由码与那句为什么。
    # 2026-11-16（Q1）：报告由提交那一刻落（批量注册 → 回填 → 清表），
    # 所以这里先 `lit.admit_all` 再读定稿（`stage_reject` 自己也会刷新进度报告）。
    _submit(reg)
    report = pathlib.Path(L.report_path(store, RID))
    text = report.read_text(encoding="utf-8")
    assert "读过" in text, text
    for title in ("Read and kept one", "Read and kept two"):
        assert title in text, title
    assert "Rejected one" in text and "rejected_low_quality" in text, text
    assert "乱码" in text, text
    # 行上留痕：拒收理由与受控码都在，不是物理删除
    row = next(r for r in store.rows("lit_candidates") if r["slot"] == slots[2])
    assert row["status"] == "rejected" and row["reason_code"] == "rejected_low_quality"
    assert "乱码" in str(row["reject_reason"])


# ====================================================================== e AH6 批量形状


def test_e_the_ah6_batch_shape_is_caught_and_named(store: Store, reg) -> None:
    """e. 改前现场的形状：12 条 relevance 一次写死、零抽读、一次 admit 10 条 readable。

    改前它整批通过；改后整批拒，并在拒信里点名那 10 个槽位。反真空：把这道闸打桩
    关掉 ⇒ 同一笔又能进 —— 于是"被拒"不能来自配额/重叠/回读。
    """
    slots = _stage(reg, [f"Batch candidate {i}" for i in range(12)])
    _readback(reg)
    wanted = slots[:10]
    res = _admit(reg, [{"slot": s, "availability": AV.READABLE} for s in wanted])
    assert not res.ok and res.meta["kind"] == "no_read_evidence", res.meta
    for slot in wanted:
        assert slot in str(res.error), (slot, res.error)
    assert _lit_titles(store) == []

    # 反真空：只关这一道闸 ⇒ 同一笔能进（否则上面那次拒绝说明不了"是它挡的"）
    import agentflow.litstage as LS

    original = LS._read_evidence_gate
    try:
        LS._read_evidence_gate = lambda *a, **k: None
        after = _admit(reg, [{"slot": s, "availability": AV.READABLE} for s in wanted])
        assert after.ok, f"打桩关掉之后仍然被拒 ⇒ 不是这道闸挡的（{after.error}）"
        # Q1：判收不发号（12 条里另有 2 条还没判，提交闸会整批拒 —— 它们也还停在
        # pending）。这里量的是"打桩之后这 10 条判得动"，不是"它们进库了"。
        assert len(after.unwrap()["admitted"]) == 10, after.unwrap()
        assert _lit_titles(store) == []
    finally:
        LS._read_evidence_gate = original


# ====================================================================== f/g 反真空


def test_f_negative_control_stubbing_the_read_state_lets_a_non_read_enter(
        store: Store, reg, monkeypatch: pytest.MonkeyPatch) -> None:
    """f. 反真空：把"读过"的判据打桩成恒 ok ⇒ 零抽读的 readable 混得进来。"""
    slots = _stage(reg, ["Stub me"])
    _readback(reg)
    items = [{"slot": slots[0], "availability": AV.READABLE}]
    assert not _admit(reg, items).ok

    monkeypatch.setattr(AV, "check_read",
                        lambda root, slot, receipt=None, **kw: ("ok", ""))
    # 2026-11-20：`check_read` 只回答"抽读证据在不在/读没读"；"读到的是不是正文"
    # （摘要那条线）由 `litavail.content_read` 再判一层。负控要打的是同一个判据的两层。
    monkeypatch.setattr(AV, "content_read",
                        lambda root, slot, row, *, tier="", receipt=None: (True, ""))
    after = _admit(reg, items)
    assert after.ok, (f"打桩成恒 ok 之后仍被拒 ⇒ 闸不是长在 `litavail.check_read` 上"
                      f"（{after.error}）")
    _submit(reg)
    assert _lit_titles(store) == ["Stub me"]


def test_g_a_changed_extracted_text_invalidates_the_read(store: Store, reg) -> None:
    """g. 反真空（另一半）：读的是旧版 `.txt`，抽读件后来变了 ⇒ 不算读过。"""
    slots = _stage(reg, ["Changed under me"])
    _readback(reg)
    ext = _extract(store, reg, slots[0])
    _fs_read(reg, ext)
    ok = _admit(reg, [{"slot": slots[0], "availability": AV.READABLE}])
    assert ok.ok, ok.error

    # 第二槽：读完之后正文被重写（版本变了）⇒ 提交必须拒
    slots2 = _stage(reg, ["Rewritten after read"], doi_prefix="10.11")
    _readback(reg)
    ext2 = _extract(store, reg, slots2[0])
    _fs_read(reg, ext2)
    pathlib.Path(ext2.unwrap()["abs_path"]).write_text("a different body entirely\n",
                                                       encoding="utf-8")
    res = _admit(reg, [{"slot": slots2[0], "availability": AV.READABLE}])
    assert not res.ok and res.meta["kind"] == "no_read_evidence", res.meta
    assert slots2[0] in str(res.error), res.error


# ====================================================================== h 抽读入口本身


def test_h_candidate_extraction_is_bound_to_the_slot_and_lands_a_receipt(
        store: Store, reg) -> None:
    """h. `text.extract(lit_id="cand:<slot>")`：认槽位、落在 `out/texts/`、写抽读回执；
    槽位不存在时受控拒（不许把回执写到一个不存在的候选上）。"""
    slots = _stage(reg, ["Candidate target"])
    ext = _extract(store, reg, slots[0])
    data = ext.unwrap()
    assert data["path"].startswith("out/texts/"), data
    assert (store.root / data["path"]).is_file(), data
    assert not (store.library / f"{slots[0]}.txt").exists(), "候选期不该往 library/ 写正文"

    rec = AV.receipts_by_slot(store.root)[slots[0]]
    assert rec["kind"] == "read" and rec["request_id"] == RID, rec
    assert rec["tier"] == LR.FULLTEXT_OK and rec["chars"] > 0, rec
    assert rec["text_abs"] and rec["text_version"], rec
    # 台账是 JSONL：一行一条，坏行跳过（这里只核它真的可读）
    raw = (store.root / "data" / AV.READ_LEDGER_NAME).read_text(encoding="utf-8")
    assert any(slots[0] in line for line in raw.splitlines() if line.strip())

    bad = reg.call("text.extract", path="downloads/nope.txt", lit_id="cand:999999")
    assert not bad.ok and bad.meta["kind"] == "unknown_slot", bad.meta
    assert "999999" not in AV.receipts_by_slot(store.root)

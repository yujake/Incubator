# -*- coding: utf-8 -*-
"""「A 的逐条自审」把可读性这一格做实（业主 2026-11-16 裁定 9 / 15 / 16）。

## 改前的现场（AH6 实测，`projects/lp-ball-2`，`temp/ah6/a_seq_A.jsonl`）

| 读数 | 值 |
|---|---|
| A1 整趟 `lit.stage_list` | 0 次（A2/A3 各一次，对象不是 r-000001） |
| 那 12 条 relevance | 07:31:29 同一秒整批写死，url 全空 |
| 提交闸 | 07:32:37 跑了，但它审的证据只有 relevance（`litstage.judged_state`） |
| 07:32:41 | A 一次 `lit.admit` 10 条通过 |
| `text.extract` | 对 lit:000002 两次、lit:000003 一次判 `garbled_text`（`kind` 逐字在日志里） |
| 07:44:26 | A 想把 `fulltext=pdf_no_text` 写进行 ⇒ 整笔拒（`status="downloaded"` 不在 `DOWNLOAD_STATUSES`），随后洗成 `status=ok/error=""` |
| 结果 | 12 条入库里 10 条只有题录、2 条有字节但抽取两次都乱码；概念行 0 条 |

所以这一份守的是「原来那一步」被做实以后必须成立的事：

| 判据 | 守的是 | 改前红的样子 |
|---|---|---|
| a `test_a_submit_without_readback_is_refused_by_name` | 提交前必须 `lit.stage_list` 回读；没回执 / 回执没覆盖要提交的槽位 ⇒ 受控拒 `no_readback`，逐条点名 | AH6 整趟 0 次回读，10 条照样入库 |
| b `test_b_every_candidate_needs_a_readability_verdict` | 每个要入库的候选必须有四档之一的可读性判定；没有 ⇒ `missing_availability`，一条都不入 | 闸只问 relevance，不问"拿到了什么" |
| c `test_c_extract_failed_and_unknown_never_enter_the_library` | `extract_failed` / `unknown` 不许入库（留在候选记录、写明原因）；`metadata_only` 必须指得出处 | 那 2 条乱码的照样入库（`status=ok/error=""`） |
| d `test_d_metadata_only_with_a_locator_is_admitted` | ④ 的判断：仅题录可入库，但必须带 DOI/URL | ——（这是本次做出的取舍，见交付说明） |
| e `test_e_report_lists_availability_in_all_three_blocks` | 报告三块逐条列可读性；`report_violations` 对"已入库却没有可读性栏 / 档位不许入"报违规 | 报告三块没有这一栏 |
| f `test_f_negative_control_stubbing_availability_lets_extract_failed_in` | 反真空：把可读性判定打桩成恒 `readable` ⇒ c 的判据必红 | —— |
| g `test_g_negative_control_stubbing_the_receipt_lets_a_non_readback_submit_through` | 反真空：把回执打桩成"全覆盖" ⇒ a 必红 | —— |
| h `test_h_extract_failed_is_the_fourth_tier_and_they_recognise_each_other` | ⑤：`litread` 的第四档存在；乱码判据只有一份（`text_tools._quality` 就是 `litread.garbled_text`） | 两处各一份判据、互相不认 |
| i `test_i_text_extract_lands_extract_failed_on_the_row` | ⑤ 的落点：`text.extract` 判乱码时把 `extract_failed` 写进 `download.fulltext`（不再只是一次性的返回） | 那两次乱码在行上没有任何痕迹 |
| j `test_j_b_skips_extract_failed_without_spending_an_extract_call` | ⑦：B 对 `extract_failed` 早退，不再浪费抽取调用；`metadata_only` 的早退读数点名这一档 | B 每轮重抽同一份乱码 PDF |

## 口径只此一处

四档词表与"哪些档能入库"在 `agentflow.litavail`；"乱码/抽过但失败"在
`agentflow.litread.garbled_text` / `FULLTEXT_EXTRACT_FAILED`；闸在
`litstage.admission_plan`。这一份不另写一份判据：打桩打的都是上面这些真身。
"""

from __future__ import annotations

import json
import pathlib
from typing import Any

import pytest

from agentflow import litavail as AV
from agentflow import litread as LR
from agentflow import litstage as L
from agentflow.agent_b import AgentB
from agentflow.store import Store
from agentflow.tools import build_for_role

from conftest import add_literature, write_library_file

RID = "r-000001"
TS = "2026-11-16T07:32:41+08:00"


# ====================================================================== 夹具


@pytest.fixture(autouse=True)
def _fresh_readbacks():
    """回执是进程内账：每个用例前后清空（不同 tmp 工作区本来也分开，这里再加一道）。"""
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
    """暂存一批候选（每条都带 relevance —— 这一份测的是第二道判据）。"""
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


def _lit_titles(store: Store) -> list[str]:
    return [str(r.get("title") or "") for r in store.rows("literature")]


# ====================================================================== a 回读闸


def test_a_submit_without_readback_is_refused_by_name(store: Store, reg) -> None:
    """a. 没回读就提交 ⇒ 受控拒 `no_readback`，逐条点名；回读之后同一笔就过。

    改前读数（AH6）：A1 整趟 0 次 `lit.stage_list`，07:32:41 一次 `lit.admit` 10 条通过。
    """
    slots = _stage(reg, ["Readback one", "Readback two"])
    items = [{"slot": s, "availability": AV.METADATA_ONLY} for s in slots]

    res = _admit(reg, items)
    assert not res.ok, "没有回读记录居然提交成功了"
    assert res.meta["kind"] == "no_readback", res.meta
    assert "lit.stage_list" in str(res.error) and "缺回读" in str(res.error), res.error
    for slot in slots:
        assert slot in str(res.error), (slot, res.error)
    assert _lit_titles(store) == [], "被拒却写进了 literature"

    # 回读之后（对着同一份清单）同一笔就过
    _readback(reg)
    ok = _admit(reg, items)
    assert ok.ok, ok.error
    assert len(ok.unwrap()["admitted"]) == 2, ok.unwrap()

    # 回读之后再 stage_add ⇒ 回执作废（新槽位没人读过），提交必须再拒
    extra = _stage(reg, ["Readback three"], doi_prefix="10.10")
    again = _admit(reg, [{"slot": extra[0], "availability": AV.METADATA_ONLY}])
    assert not again.ok and again.meta["kind"] == "no_readback", again.meta


# ====================================================================== b 逐条判定


def test_b_every_candidate_needs_a_readability_verdict(store: Store, reg) -> None:
    """b. 只给 slot 不给 availability ⇒ `missing_availability`（整批拒、一条都不入）。"""
    slots = _stage(reg, ["No verdict one", "No verdict two"])
    _readback(reg)
    res = _admit(reg, [{"slot": s} for s in slots])
    assert not res.ok, "没有可读性判定居然入库了"
    assert res.meta["kind"] == "missing_availability", res.meta
    assert set(res.meta["missing_availability"]) == set(slots), res.meta
    for slot in slots:
        assert slot in str(res.error), (slot, res.error)
    assert "availability" in str(res.error), res.error
    assert _lit_titles(store) == []


# ====================================================================== c 不合格不入库


def test_c_extract_failed_and_unknown_never_enter_the_library(store: Store, reg) -> None:
    """c. `extract_failed` / `unknown` 不许入库；行留在候选记录里、原因点得出。"""
    slots = _stage(reg, ["Garbled paper", "Unchecked paper", "Fine paper"])
    _readback(reg)
    res = _admit(reg, [
        {"slot": slots[0], "availability": AV.EXTRACT_FAILED},
        {"slot": slots[1], "availability": AV.UNKNOWN},
        {"slot": slots[2], "availability": AV.METADATA_ONLY},
    ])
    assert not res.ok, "两档不许入的候选居然入库了"
    assert res.meta["kind"] == "availability_not_admissible", res.meta
    bad = {row["slot"]: row["tier"] for row in res.meta["availability_bad"]}
    assert bad == {slots[0]: "extract_failed", slots[1]: "unknown"}, bad
    assert "extract_failed" in str(res.error) and "unknown" in str(res.error), res.error
    assert _lit_titles(store) == [], "一整批被拒却写进了 literature"

    # 抽过但失败的那一条按受控理由码判拒：行留着、理由写在行上（不是物理删）。
    # 可读性判定不在这里再收一次（判拒不是入库）：上面那次 `lit.admit` 带着
    # `availability=extract_failed` 被闸挡下时，台账里已经记下这一档。
    rej = reg.call("lit.stage_reject", slot=slots[0],
                   reason_code="rejected_low_quality",
                   note="PDF 文字层乱码，抽两次都失败")
    assert rej.ok, rej.error
    row = next(r for r in store.rows("lit_candidates") if r["slot"] == slots[0])
    assert row["status"] == "rejected" and row["reason_code"] == "rejected_low_quality"
    assert "乱码" in str(row["reject_reason"]), row

    # 台账里留着这一条的四档判定（报告与闸读的是同一份）
    assert AV.tiers_by_slot(store.root)[slots[0]] == AV.EXTRACT_FAILED
    # 没查的那一条仍然不入库（unknown 不是"可读"）
    res2 = _admit(reg, [{"slot": slots[1], "availability": AV.UNKNOWN}])
    assert not res2.ok and res2.meta["kind"] == "availability_not_admissible", res2.meta


# ====================================================================== d 仅题录


def test_d_metadata_only_with_a_locator_is_admitted(store: Store, reg) -> None:
    """d. ④ 的判断：仅题录可以入，但它必须指得出处（DOI 或 URL）。

    反方向也在这一条里：没有 DOI/URL 的仅题录 ⇒ `metadata_only_without_locator`。
    """
    slots = _stage(reg, ["Locator paper"])          # 夹具给了 DOI
    _readback(reg)
    ok = _admit(reg, [{"slot": slots[0], "availability": AV.METADATA_ONLY}])
    assert ok.ok and len(ok.unwrap()["admitted"]) == 1, ok.unwrap()
    assert AV.tiers_by_slot(store.root)[slots[0]] == AV.METADATA_ONLY

    # 没有定位符的仅题录：手工落一行（`stage_add` 的 title 是必填，这里绕开工具面）
    with store.tx("lit_candidates", "counters", actor="t", note="no locator") as tx:
        slot = tx.alloc_id("candidate")
    from agentflow import schema as S

    with store.tx("lit_candidates", actor="t", note="no locator") as tx:
        row = S.LitCandidate(slot=slot, request_id="r-000002", batch=1, status="pending",
                             title="No locator paper", doi=None, url="",
                             relevance="题目相关但没有可定位的号").to_dict()
        tx.upsert("lit_candidates", row, note="no locator")
    reg.call("lit.stage_list", request_id="r-000002")
    res = _admit(reg, [{"slot": slot, "availability": AV.METADATA_ONLY}], rid="r-000002")
    assert not res.ok and res.meta["kind"] == "availability_not_admissible", res.meta
    assert "metadata_only" in str(res.error), res.error


# ====================================================================== e 报告


def _report_rows() -> list[dict]:
    return [
        {"slot": "000000", "batch": 1, "status": "admitted", "title": "A paper",
         "request_id": RID, "relevance": "与本次检索相关", "lit_id": "000000",
         "admitted_at": TS, "added_at": TS},
        {"slot": "000001", "batch": 1, "status": "rejected", "title": "A garbled paper",
         "request_id": RID, "reason_code": "rejected_low_quality",
         "reject_reason": "PDF 文字层乱码", "added_at": TS},
        {"slot": "000002", "batch": 1, "status": "pending", "title": "An unchecked paper",
         "request_id": RID, "added_at": TS},
    ]


def test_e_report_lists_availability_in_all_three_blocks(store: Store, reg) -> None:
    """e. 报告三块逐条列「可得性」（可读性四档）；`report_violations` 对缺栏 / 不许入的档位报违规。"""
    text = L.report_markdown(RID, _report_rows(), generated_at=TS,
                             availability={"000000": AV.METADATA_ONLY,
                                           "000001": AV.EXTRACT_FAILED,
                                           "000002": ""})
    # 三块各有一行可得性（已入库 / 未入库 / 待裁）
    assert "可得性：仅题录（metadata_only）" in text, text
    assert "可得性：有字节但抽取失败（extract_failed）" in text, text
    assert "可得性：未查（unknown）" in text, text
    admitted_block = text.split("## 已入库", 1)[1].split("## 未入库", 1)[0]
    assert "可得性：" in admitted_block
    assert L.report_violations(text) == [], L.report_violations(text)

    # 反方向 ①：已入库的那一条没有可得性栏 ⇒ 违规
    no_col = text.replace("  可得性：仅题录（metadata_only）\n", "")
    assert any("可得性" in v for v in L.report_violations(no_col)), L.report_violations(no_col)
    # 反方向 ②：已入库的那一条被标成 extract_failed ⇒ 违规（③ 的判据在报告侧也成立）
    wrong = L.report_markdown(RID, _report_rows(), generated_at=TS,
                              availability={"000000": AV.EXTRACT_FAILED,
                                            "000001": AV.EXTRACT_FAILED,
                                            "000002": ""})
    assert any("不许入库" in v for v in L.report_violations(wrong)), L.report_violations(wrong)


# ====================================================================== f/g 反真空


def test_f_negative_control_stubbing_availability_lets_extract_failed_in(
        store: Store, reg, monkeypatch: pytest.MonkeyPatch) -> None:
    """f. 反真空：把可读性判定打桩成恒 `readable` ⇒ `extract_failed` 混得进来。

    不这么做的话，"extract_failed 被挡"可能来自别的原因（配额/重叠/回读），
    而判据 c 就成了一盏被别的原因点亮的灯。
    """
    slots = _stage(reg, ["Stub target paper"])
    _readback(reg)
    AV.record_availability(store.root, RID, slots[0], AV.EXTRACT_FAILED)

    before = _admit(reg, [{"slot": slots[0]}])
    assert not before.ok and before.meta["kind"] == "availability_not_admissible", before.meta

    monkeypatch.setattr(AV, "tiers_by_slot", lambda root: {slots[0]: AV.READABLE})
    after = _admit(reg, [{"slot": slots[0]}])
    assert after.ok, (f"打桩成恒 readable 之后仍然被拒 ⇒ 那道闸不是长在 "
                      f"`litavail.tiers_by_slot` 上（{after.error}）")
    assert _lit_titles(store) == ["Stub target paper"]


def test_g_negative_control_stubbing_the_receipt_lets_a_non_readback_submit_through(
        store: Store, reg, monkeypatch: pytest.MonkeyPatch) -> None:
    """g. 反真空：把回执打桩成"覆盖所有槽位" ⇒ 没回读也能提交（a 的判据必红）。"""
    slots = _stage(reg, ["Receipt stub paper"])
    items = [{"slot": s, "availability": AV.METADATA_ONLY} for s in slots]
    assert not _admit(reg, items).ok

    monkeypatch.setattr(L, "readback_receipt",
                        lambda store, rid: {"request_id": rid, "slots": list(slots)})
    after = _admit(reg, items)
    assert after.ok, f"打桩成已回读之后仍然被拒 ⇒ 回读闸没长在 `readback_receipt` 上（{after.error}）"


# ====================================================================== h/i 第五档


def test_h_extract_failed_is_the_fourth_tier_and_they_recognise_each_other(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """h. ⑤：四档词表里有 `extract_failed`；乱码判据只有一份（`_quality` 就是它）。"""
    assert LR.FULLTEXT_EXTRACT_FAILED == "extract_failed"
    assert LR.FULLTEXT_EXTRACT_FAILED in LR.FULLTEXT_TIERS
    assert AV.EXTRACT_FAILED in AV.AVAILABILITY_TIERS

    # 乱码 ⇒ extract_failed（抽过但失败），不是 ok / no_text_layer
    garbled, q = LR.garbled_text("正文\x00\x00乱码")
    assert garbled and q["nul_bytes"] == 2, q
    assert LR.fulltext_tier(bytes_on_disk=100, pages=None,
                            text="正文\x00\x00") == LR.FULLTEXT_EXTRACT_FAILED
    assert LR.fulltext_tier(bytes_on_disk=100, pages=None,
                            text="可读的正文") == LR.FULLTEXT_OK
    assert LR.fulltext_tier(bytes_on_disk=0, pages=["正文"]) == LR.FULLTEXT_NO_FULLTEXT
    # 有字节、什么都没抽过 ⇒ None（"没查成"，不是某一档）
    assert LR.fulltext_tier(bytes_on_disk=100, pages=None) is None

    # 互认：`text_tools._quality` 不是另一份实现 —— 打桩 `litread.garbled_text`
    # 之后它跟着变（改前两处各一份判据，打桩只动一处）
    from agentflow.tools import text_tools as TT

    monkeypatch.setattr(LR, "garbled_text", lambda text: (True, {"stub": True}))
    assert TT._quality("完全正常的正文") == (True, {"stub": True})


def test_i_text_extract_lands_extract_failed_on_the_row(store: Store, reg) -> None:
    """i. ⑤ 的落点：`text.extract` 判乱码时，`download.fulltext` 记成 `extract_failed`。

    改前读数（AH6 07:44:26）：A 手写 `fulltext=pdf_no_text` + `status=downloaded`
    ⇒ 整笔拒 ⇒ 洗成 `status=ok/error=""`，行上一点痕迹都没有。
    """
    add_literature(store, "000000", title="Garbled PDF stand-in", doi="10.55/g")
    downloads = store.root / "downloads"
    downloads.mkdir(parents=True, exist_ok=True)
    src = downloads / "garbled.txt"
    src.write_text("page one \x00\x00 page two\n", encoding="utf-8")

    res = reg.call("text.extract", path=str(src), lit_id="000000")
    assert not res.ok, "乱码居然抽成功了"
    assert res.meta["kind"] == "garbled_text", res.meta
    assert res.meta["availability"] == "extract_failed", res.meta
    assert res.meta["landed_on"] == "000000", res.meta

    row = next(r for r in store.rows("literature") if r["lit_id"] == "000000")
    assert (row.get("download") or {}).get("fulltext") == LR.FULLTEXT_EXTRACT_FAILED, row
    # 抽出的乱码一个字都没写进 library/（"不写盘"那条老判据照旧成立）
    assert not list(store.library.rglob("*.txt")), list(store.library.rglob("*"))


# ====================================================================== j B 侧早退


class _MustNotBeCalled:
    """抽取器替身：被调用即报错（"没浪费抽取调用"这件事只有这样才测得出来）。"""

    calls = 0

    def extract(self, doc, lit_id, meta):
        _MustNotBeCalled.calls += 1
        raise AssertionError("extract_failed 的行不该再进抽取器")


def _agent_b(store: Store, extractor: Any, extract: Any) -> AgentB:
    return AgentB(store, extractor=extractor, extract_text=extract,
                  config={"lease_seconds": 900, "max_attempts": 3})


def test_j_b_skips_extract_failed_without_spending_an_extract_call(store: Store) -> None:
    """j. ⑦：B 对 `extract_failed` 早退（不调抽取器/抽取器）；`metadata_only` 也点名。"""
    write_library_file(store, "0000/a.txt", "Some readable body text.")
    add_literature(store, "0000", title="Garbled one", path="0000/a.txt",
                   download={"status": "ok", "bytes": 100, "http_status": 200,
                             "error": "", "sha256": "x" * 64,
                             "fulltext": LR.FULLTEXT_EXTRACT_FAILED})
    add_literature(store, "0001", title="Metadata only one", path=None, doi="10.55/m",
                   download={"status": "skipped", "bytes": 0, "error": "no_local_path"})

    _MustNotBeCalled.calls = 0
    b = _agent_b(store, _MustNotBeCalled(),
                 extract=lambda _p: (_ for _ in ()).throw(AssertionError("不该抽")))
    first = b.run_once()
    assert first.unreadable == 1, first.details
    assert _MustNotBeCalled.calls == 0, "extract_failed 的行仍然被送进了抽取器"
    assert any(d.get("skipped") == "availability=extract_failed" for d in first.details), \
        first.details
    row = next(r for r in store.rows("literature") if r["lit_id"] == "0000")
    assert row["processed"] is True and "extract_failed" in str(row["last_mine_error"]), row

    second = b.run_once()
    assert second.unreadable == 1, second.details
    assert _MustNotBeCalled.calls == 0
    meta = next(r for r in store.rows("literature") if r["lit_id"] == "0001")
    assert "metadata_only" in str(meta["last_mine_error"]), meta
    assert "no_local_file" in str(meta["last_mine_error"]), meta

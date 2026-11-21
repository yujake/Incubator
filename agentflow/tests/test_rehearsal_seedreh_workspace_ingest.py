# -*- coding: utf-8 -*-
"""SEEDREH：A 对工作区内文献的入库彩排（真 PDF / 真盘 / 真判收闸）。

业主指令（逐字）：「需要彩排 A 对于工作区内文献的入库」—— 下一趟真机会把历史真机
下载成功的文献投到新工作区（不直接入库），所以先把这条链在盘上跑通再起真机。

## 这条链（每一步都是真工具，不是替身）

| 步 | 真工具 | 盘上事实 |
|---|---|---|
| ① 发现 | `search.ingest_local(dry_run=True)` | `source/` 里那两份 PDF 被逐份算出 sha256 / 页数 / 文本层；一个字节都不写（`literature` 与候选表都还是空的） |
| ② 入候选 | `lit.stage_add` | `lit_candidates` 两条 `pending`，`url` 指向 `source/` 里那份真文件 |
| ③ 回读 | `lit.stage_list` | 读回执记在盘上（提交闸要它） |
| ④ 抽读 + 读 | `text.extract(lit_id="cand:<槽>")` → `fs.read` | `out/texts/cand-<槽>.txt` + `data/lit_reads.jsonl` 回执 + `fs.read` 观察台账 |
| ⑤ 判收 | `lit.admit(items[].availability="readable")` | 候选 `qualified`（无号）；`data/lit_availability.jsonl` 记 `content_read=true` |
| ⑥ 提交 | `lit.admit_all` | 批量注册 + 回填 `lit_id` + 清表；`literature` 两行带 `path` / `download.fulltext=ok` |

## 素材为什么用盘上现成的真机 PDF

`agentflow/projects/` 下就是历史真机下载成功的文献（真字节）。造一份假 PDF 或手写
`%PDF-1.4` 头会让"抽读"这一步变成"抽取器拒绝"，测的就不是这条链。乱码那一份是
`tests/fixtures/garbled-symbol-layer.pdf`：有文本层、抽出来是一整页符号汤（没有
NUL/控制字符，旧口径会把它当可读）—— 这正是"抽得出字、但读不了"的真乱码形态，
负控要守的是它，而不是一份正文可读、只夹了几个 NUL 的论文（改前那两份就是被
`nul > 0` 误判的）。

## 守什么

1. 正链：两份真 PDF 走完 ①–⑥ ⇒ `literature` 行带 `path` / `fulltext=ok` / `tier=readable`，
   `content_read=true` 落在可读性台账上；候选行回填了号、`pending` 清零；
2. 负控 ①：乱码 PDF 不许进库 —— 发现层（`search.ingest_local`）与判收层（`lit.admit`）
   各受控拒一次，理由码是 `extract_failed`（不是"格式不支持"，格式认得，缺的是正文）；
3. 负控 ②：只有题录（手工行、没有 `path`）的候选 ⇒ `metadata_only` 拒，槽位留在候选里；
4. 负控 ③：与库里已登记的行 DOI 完全相同 ⇒ `duplicate_doi` 拒，不重复入库；
5. 反真空：把 `litavail.content_read` 打桩掉 ⇒ "只有摘要"那份进库（必红）；
   把 `litread.fulltext_tier` 打桩掉 ⇒ 乱码那份登记成行（必红）；
6. 下一步：A 的可见面（渲染后的提示词）里写着「收进 `literature`（`admitted > 0`）⇒
   下一步就是派 B 的 `run_once`」—— 这一格只读，不真派 B。
"""
from __future__ import annotations

import json
import pathlib
import shutil

import pytest

from agentflow import agent_prompts as AP
from agentflow import litavail as AV
from agentflow import litread as LR
from agentflow import litstage as L
from agentflow import schema as S
from agentflow.store import Store
from agentflow.tools import build_for_role

RID = "r-000001"
ROOT = pathlib.Path(__file__).resolve().parents[1]

#: 两份真·可抽读 PDF（历史真机下载；4.7 万 / 6.1 万字，`fulltext_tier=ok`）。
READABLE = (
    ROOT / "projects" / "p5-review-strict-20261012" / "library" / "0004" / "graph-subshifts.pdf",
    ROOT / "projects" / "mp3" / "library" / "000004"
    / "enveloping-algebras-of-krichever-novikov-algebras-are-not-no.pdf",
)
#: 真·乱码 PDF（有文本层，抽出来是符号汤、完整词 0 个 ⇒ `garbled`）。
GARBLED = (ROOT / "tests" / "fixtures" / "garbled-symbol-layer.pdf",)

#: 只有摘要的正文（< `litavail.MIN_BODY_BEYOND_ABSTRACT`）；刻意不含内容性断言词。
ABSTRACT_ONLY = ("We study maximal hyperplane sections of the unit ball of l_p^n and "
                 "give an explicit formula in dimension three. " * 3)

DUP_DOI = "10.1000/seedreh.duplicate"


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
    (st.root / "source").mkdir(parents=True, exist_ok=True)
    # 2026-11-21 起非 dry 档按用户声明核（fail-closed：没点名的不许入库）。
    # 这一组判的是收编链本身，所以把 source/ 整目录声明成用户点名的可靠参考文献。
    (st.root / "RELIABLE-REFERENCES.json").write_text(
        json.dumps({"paths": ["source/"], "verbatim": "source/ 里都是可靠参考文献"},
                   ensure_ascii=False),
        encoding="utf-8")
    return st


@pytest.fixture
def reg(store: Store):
    registry = build_for_role("A", store=store, workspace_root=store.root).registry
    registry.bound_role = "A"
    return registry


def _put(store: Store, files) -> list[pathlib.Path]:
    """把真 PDF 投进工作区的 `source/`（模拟"下一趟真机把历史文献投进去"）。"""
    out = []
    for src in files:
        dest = store.root / "source" / pathlib.Path(str(src)).name
        shutil.copy2(src, dest)
        out.append(dest)
    return out


def _rel(store: Store, p: pathlib.Path) -> str:
    return pathlib.Path(p).relative_to(store.root).as_posix()


# ====================================================================== ① 发现


def _discover(reg, **kwargs):
    res = reg.call("search.ingest_local", books_dir="source", dry_run=True, **kwargs)
    assert res.ok, (res.error, dict(res.meta))
    return res.unwrap()


def _stage(reg, books, *, summaries: dict | None = None) -> list[str]:
    """把发现读数变成候选：`url` 就是 `source/` 里那份真文件的绝对路径。"""
    entries = []
    for b in books:
        name = pathlib.Path(str(b["source"])).name
        entry = {
            "title": pathlib.Path(str(b["source"])).stem.replace("_", " "),
            "provider": "localpdf",
            "type_code": "J",
            "url": str(b["source"]),
            "summary": f"工作区 source/ 里的本地文件（{name}，{int(b.get('pages') or 0)} 页）",
            "relevance": "工作区 source/ 里已有的本地文献（不是检索来的）：本次收编要的那一篇",
        }
        if summaries and name in summaries:
            entry["summary"] = summaries[name]
        entries.append(entry)
    res = reg.call("lit.stage_add", request_id=RID, entries=entries)
    assert res.ok, (res.error, dict(res.meta))
    return [row["slot"] for row in res.unwrap()["staged"]]


def _readback(reg):
    res = reg.call("lit.stage_list", request_id=RID)
    assert res.ok, res.error
    return res.unwrap()


def _read_through(reg, store: Store, slot: str, source: pathlib.Path):
    """候选期抽读 + `fs.read` 同一版（判收闸核的就是这两步真发生过）。"""
    ext = reg.call("text.extract", path=_rel(store, source), lit_id=f"cand:{slot}")
    if not ext.ok:
        return ext
    got = reg.call("fs.read", path=ext.unwrap()["path"])
    assert got.ok, (got.error, dict(got.meta))
    return ext


def _admit(reg, items):
    return reg.call("lit.admit", request_id=RID, items=items)


def _submit(reg, slots=None):
    return reg.call("lit.admit_all", request_id=RID, slots=slots)


def _lit_rows(store: Store) -> list[dict]:
    return [dict(r) for r in store.rows("literature")]


# ====================================================================== 正链


def test_a_discovery_writes_nothing_to_the_ledger(store: Store, reg) -> None:
    """① 发现是只读的：`dry_run` 之后 `literature` 与候选表都必须还是空的。

    这一条挡的是"把发现当成入库"：发现读数（sha256 / 页数 / 文本层）齐了，一个字节
    都没写 —— 所以下一趟真机把历史文献投进工作区时，"不直接入库"这句话是在盘上成立的。
    """
    _put(store, READABLE)
    data = _discover(reg)
    assert data["count"] == 2 and data["ingested"] == 2, data
    assert all(b["status"] == "ingested" for b in data["books"]), data["books"]
    assert all(b["sha256"] and b["pages"] > 0 for b in data["books"]), data["books"]
    assert _lit_rows(store) == [], "发现这一步写了 literature 行"
    assert store.rows("lit_candidates") == [], "发现这一步写了候选行"
    assert (store.root / "source").is_dir() and len(list((store.root / "source").iterdir())) == 2


def test_b_the_full_chain_lands_two_real_pdfs_with_readable_fulltext(
        store: Store, reg) -> None:
    """②–⑥ 正链：发现 → 候选 → 回读 → 抽读 + fs.read → 判收 → 提交。"""
    sources = _put(store, READABLE)

    # ① 发现
    books = _discover(reg)["books"]

    # ② 入候选
    slots = _stage(reg, books)
    assert len(slots) == 2, slots

    # ③ 回读（快照：两条都 pending）
    listed = _readback(reg)
    assert listed["count"] == 2, listed
    assert listed["counts"]["pending"] == 2, listed["counts"]
    assert sorted(str(r["slot"]) for r in listed["rows"]) == sorted(slots)

    # ④ 抽读 + 读
    for slot, src in zip(slots, sources):
        ext = _read_through(reg, store, slot, src)
        assert ext.ok, (src.name, ext.error, dict(ext.meta))
        assert ext.unwrap()["chars"] > 0, ext.unwrap()

    # ⑤ 判收：每条都报 readable，闸现算 content_read
    res = _admit(reg, [{"slot": s, "availability": AV.READABLE} for s in slots])
    assert res.ok, (res.error, dict(res.meta))
    admitted = res.unwrap()["admitted"]
    assert len(admitted) == 2, admitted
    assert all(item["content_read"] is True for item in admitted), admitted
    assert all(item["lit_id"] == "" for item in admitted), "判收不该发号"
    assert _lit_rows(store) == [], "判收（lit.admit）就注册了行"

    # ⑥ 提交：批量注册 + 回填号 + 清表
    submitted = _submit(reg, slots)
    assert submitted.ok, (submitted.error, dict(submitted.meta))
    data = submitted.unwrap()
    assert data["registered"] == 2, data

    rows = _lit_rows(store)
    assert len(rows) == 2, rows
    for row in rows:
        assert str(row.get("path") or ""), row
        assert (store.root / "library" / str(row["path"])).is_file(), row
        dl = dict(row.get("download") or {})
        assert dl.get("fulltext") == LR.FULLTEXT_OK, row
        assert dl.get("status") == "ok", row
        assert AV.tier_of_literature(row, store.root) == AV.READABLE, row
    assert sorted(pathlib.Path(str(r["path"])).name for r in rows) == sorted(
        src.name for src in sources), rows

    # 回填号 + 清表：候选行是 admitted 且带 lit_id，pending 归零
    after = _readback(reg)
    assert after["counts"]["pending"] == 0, after["counts"]
    assert after["counts"]["admitted"] == 2, after["counts"]
    lits = {str(r["lit_id"]) for r in rows}
    assert {str(r.get("lit_id") or "") for r in after["rows"]} == lits, after["rows"]
    assert data["report_path"], data

    # content_read=true 落在可读性台账上（literature 行本身不带这一格）
    tiers = AV.tiers_by_slot(store.root)
    receipts = AV.receipts_by_slot(store.root)
    for slot in slots:
        assert tiers.get(slot) == AV.READABLE, (slot, tiers)
        ok, why = AV.content_read(store.root, slot,
                                  next(r for r in after["rows"] if r["slot"] == slot),
                                  tier=tiers[slot], receipt=receipts.get(slot))
        assert ok, (slot, why)


# ====================================================================== 负控 ①


def test_c_a_real_garbled_pdf_is_refused_by_the_ingest_gate(store: Store, reg) -> None:
    """负控 ①-a：乱码 PDF 走登记这条路 ⇒ `unreadable` + 理由码 `extract_failed`，零行。"""
    (src,) = _put(store, GARBLED)
    res = reg.call("search.ingest_local", books_dir="source")
    assert res.ok, (res.error, dict(res.meta))
    data = res.unwrap()
    assert data["ingested"] == 0, data
    assert data["unreadable"] == 1, data
    assert data["count"] == 1, data
    note = str(data["books"][0]["note"])
    assert note.startswith(LR.FULLTEXT_EXTRACT_FAILED), data["books"][0]
    assert _lit_rows(store) == [], "乱码 PDF 进了 literature"
    assert (store.root / "source" / src.name).is_file(), "被拒的那份不该被搬走"


def test_d_a_real_garbled_pdf_is_refused_by_the_admit_gate(store: Store, reg) -> None:
    """负控 ①-b：乱码 PDF 走判收链 ⇒ 抽读就受控失败、`lit.admit` 整笔拒，零行。"""
    (src,) = _put(store, GARBLED)
    books = _discover(reg)["books"]
    assert len(books) == 1 and books[0]["pages"] > 0, books

    (slot,) = _stage(reg, books)
    _readback(reg)
    ext = _read_through(reg, store, slot, src)
    assert not ext.ok, "乱码 PDF 的抽读居然成功了"
    assert str(dict(ext.meta).get("kind")) in ("garbled_text", "extract_error"), dict(ext.meta)
    # 抽读失败也留了回执（"试过、抽不出可读正文"），不是"没试过"
    receipt = AV.receipts_by_slot(store.root).get(slot)
    assert receipt is not None and receipt["tier"] == LR.FULLTEXT_EXTRACT_FAILED, receipt

    res = _admit(reg, [{"slot": slot, "availability": AV.READABLE}])
    assert not res.ok, "乱码候选被判收放行了"
    assert res.meta["kind"] == "no_read_evidence", res.meta
    problem = next(p for p in res.meta["read_problems"] if p["slot"] == slot)
    assert problem["state"] == "extract_failed", problem
    assert _lit_rows(store) == []
    row = next(r for r in store.rows("lit_candidates") if r["slot"] == slot)
    assert row["status"] == "pending", row


# ====================================================================== 负控 ②


def test_e_a_handmade_metadata_only_row_is_refused_as_metadata_only(
        store: Store, reg) -> None:
    """负控 ②：只有题录（手工行、没有 `path`）⇒ 拒；试过抽取的那条给 `metadata_only`。

    三态在这里也守着：一次抽取都没试过 ⇒ `no_fulltext`（"没查"不等于"查过拿不到"）；
    试过、拿不到可读文本 ⇒ `metadata_only`。两档都不许入库。
    """
    with store.tx("lit_candidates", "counters", actor="t", note="handmade") as tx:
        slot = tx.alloc_id("candidate")
        never_tried = tx.alloc_id("candidate")
    with store.tx("lit_candidates", actor="t", note="handmade") as tx:
        for got, title in ((slot, "Handmade metadata-only record"),
                           (never_tried, "Handmade record nobody tried to read")):
            tx.upsert("lit_candidates", S.LitCandidate(
                slot=got, request_id=RID, batch=1, status="pending",
                title=title, doi=f"10.1000/seedreh.metadata.{got}",
                url="", relevance="题录来自别人给的清单，盘上没有这份全文").to_dict(),
                note="handmade")
    # `slot` 这一条：试过一次抽取、拿不到可读正文（真机由失败的 `text.extract` 写）
    AV.record_read(store.root, RID, slot, LR.FULLTEXT_EXTRACT_FAILED,
                   source="fixture:no-bytes", note="text.extract.no_text_layer")
    _readback(reg)

    res = _admit(reg, [{"slot": slot, "availability": AV.METADATA_ONLY}])
    assert not res.ok, "只有题录的候选被判收放行了"
    assert res.meta["kind"] == "availability_not_admissible", res.meta
    bad = next(row for row in res.meta["availability_bad"] if row["slot"] == slot)
    assert bad["code"] == "metadata_only", bad
    assert _lit_rows(store) == []
    row = next(r for r in store.rows("lit_candidates") if r["slot"] == slot)
    assert row["status"] == "pending", row

    # 没试过抽取的那一条：理由码是 `no_fulltext`（不是"只剩题录"）
    res2 = _admit(reg, [{"slot": never_tried, "availability": AV.METADATA_ONLY}])
    assert not res2.ok, res2.unwrap()
    bad2 = next(row for row in res2.meta["availability_bad"] if row["slot"] == never_tried)
    assert bad2["code"] == "no_fulltext", bad2
    assert _lit_rows(store) == []


# ====================================================================== 负控 ③


def test_f_a_candidate_with_the_same_doi_is_refused_as_duplicate(
        store: Store, reg) -> None:
    """负控 ③：与库里已登记的行 DOI 完全相同 ⇒ 拒，不重复入库。"""
    reg.call("search.register", title="Seedreh duplicate anchor", type_code="J",
             summary="已经登记过的那个锚点", doi=DUP_DOI)
    before = _lit_rows(store)
    assert len(before) == 1, before

    _put(store, READABLE[:1])
    books = _discover(reg)["books"]
    assert len(books) == 1, books
    entries = [{
        "title": "Same DOI but a different title",
        "doi": DUP_DOI,
        "provider": "localpdf",
        "type_code": "J",
        "url": str(books[0]["source"]),
        "relevance": "这一篇与库里那条是同一篇（同 DOI）",
    }]
    staged = reg.call("lit.stage_add", request_id=RID, entries=entries)
    assert staged.ok, (staged.error, dict(staged.meta))
    (slot,) = [row["slot"] for row in staged.unwrap()["staged"]]
    _readback(reg)
    ext = _read_through(reg, store, slot, pathlib.Path(str(books[0]["source"])))
    assert ext.ok, (ext.error, dict(ext.meta))

    res = _admit(reg, [{"slot": slot, "availability": AV.READABLE}])
    assert res.ok, (res.error, dict(res.meta))
    data = res.unwrap()
    assert data["admitted"] == [], "同 DOI 的候选被判收放行了"
    refused = next(row for row in data["refused"] if row["slot"] == slot)
    assert refused["code"] == "duplicate_doi", refused
    assert len(_lit_rows(store)) == 1, "同 DOI 又入了一条"

    # 收尾：这一条拿不到号，A 判拒（受控理由码）之后提交，注册 0 条
    junk = reg.call("lit.stage_reject", slot=slot, reason_code="duplicate_doi")
    assert junk.ok, (junk.error, dict(junk.meta))
    submitted = _submit(reg, [slot])
    assert submitted.ok, (submitted.error, dict(submitted.meta))
    assert submitted.unwrap()["registered"] == 0, submitted.unwrap()
    assert len(_lit_rows(store)) == 1


# ====================================================================== 反真空


def test_g_stubbing_content_read_lets_an_abstract_only_row_in(store: Store, reg) -> None:
    """反真空（content_read 闸）：摘要当正文 ⇒ 拒；把闸打桩掉 ⇒ 进库（必红）。"""
    src = store.root / "source" / "abstract-only.txt"
    src.write_text(ABSTRACT_ONLY, encoding="utf-8")
    staged = reg.call("lit.stage_add", request_id=RID, entries=[{
        "title": "Abstract-only preprint",
        "provider": "localpdf",
        "type_code": "J",
        "url": str(src),
        "summary": ABSTRACT_ONLY,
        "relevance": "工作区里那份只有摘要的稿子",
    }])
    assert staged.ok, (staged.error, dict(staged.meta))
    (slot,) = [row["slot"] for row in staged.unwrap()["staged"]]
    _readback(reg)
    ext = _read_through(reg, store, slot, src)
    assert ext.ok, (ext.error, dict(ext.meta))

    res = _admit(reg, [{"slot": slot, "availability": AV.READABLE}])
    assert not res.ok, "只有摘要的那一条被判收放行了"
    assert res.meta["kind"] == "no_read_evidence", res.meta
    problem = next(p for p in res.meta["read_problems"] if p["slot"] == slot)
    assert problem["state"] == "abstract_only", problem
    assert _lit_rows(store) == []

    # 打桩：闸恒真 ⇒ 同一条必须被放行（红就是这道闸给的）
    original = AV.content_read

    def _always_read(*args, **kwargs):
        return True, ""

    AV.content_read = _always_read
    try:
        res2 = _admit(reg, [{"slot": slot, "availability": AV.READABLE}])
    finally:
        AV.content_read = original
    assert res2.ok, (res2.error, dict(res2.meta))
    assert [item["slot"] for item in res2.unwrap()["admitted"]] == [slot], res2.unwrap()


def test_h_stubbing_the_ingest_gate_lets_the_garbled_pdf_register(
        store: Store, reg) -> None:
    """反真空（登记闸）：乱码 PDF 被拒；把 `fulltext_tier` 打桩成 ok ⇒ 登记成行（必红）。"""
    _put(store, GARBLED)
    res = reg.call("search.ingest_local", books_dir="source")
    assert res.ok and res.unwrap()["ingested"] == 0, res.unwrap()

    original = LR.fulltext_tier

    def _always_ok(**kwargs):
        return LR.FULLTEXT_OK

    LR.fulltext_tier = _always_ok
    try:
        res2 = reg.call("search.ingest_local", books_dir="source")
    finally:
        LR.fulltext_tier = original
    assert res2.ok, (res2.error, dict(res2.meta))
    data = res2.unwrap()
    assert data["ingested"] == 1, data
    rows = _lit_rows(store)
    assert len(rows) == 1, "打桩之后乱码那份没进库（这道闸不是它给的）"
    assert dict(rows[0].get("download") or {}).get("fulltext") == LR.FULLTEXT_OK, rows[0]


# ====================================================================== 下一步


def test_i_the_next_step_after_admission_is_b_and_it_is_on_a_s_face(
        store: Store, reg) -> None:
    """下一步是派 B —— 这条规则在 A 读得到的提示词里（ALITER 的无条件祈使句）。

    只读渲染产物（不读源码串）：业主的收尾口径是"收进 literature（admitted>0）⇒ 下一步
    派 B 的 run_once 整理"，而 A 能看到的就是这一段。
    """
    prompt = AP.system_prompt("A", registry=reg, workspace_root=str(store.root))
    hits = [ln for ln in prompt.splitlines()
            if "admitted > 0" in ln and "run_once" in ln and "下一步就是派 B" in ln]
    assert hits, "A 的提示词里没有「收进 literature ⇒ 下一步派 B 的 run_once」这一条"
    line = hits[0]
    for token in ("literature", "run_once", "没转化成资产"):
        assert token in line, (token, line)
    assert "如果" not in line and "若" not in line, f"这一条被条件句前置了：{line}"


# ====================================================================== 动作面


def test_j_the_action_says_no_readable_content_instead_of_unsupported_format(
        store: Store) -> None:
    """动作 `A.ingest_local` 的 `kind`：格式认得但没有正文 ⇒ `no_readable_content`。

    这一格与"格式不支持"（`.tex` ⇒ `unsupported_format`）必须分得开：下一步相反
    （换来源 / 先 OCR vs 换 pattern）。
    """
    from agentflow.agent_a import AgentA

    (src,) = _put(store, GARBLED)
    res = AgentA(store, providers=[]).ingest_local(books_dir="source")
    assert res["ok"] is True, res
    assert res["ingested"] == 0 and res["unreadable"] == 1, res
    assert res["kind"] == "no_readable_content", res["kind"]
    assert res["books"][0]["note"].startswith(LR.FULLTEXT_EXTRACT_FAILED), res["books"][0]
    assert _lit_rows(store) == [], "动作这条路把乱码那份登记成行了"
    assert (store.root / "source" / src.name).is_file()

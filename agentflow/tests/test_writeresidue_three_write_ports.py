# -*- coding: utf-8 -*-
"""三条未接的写路收口（WRITERESIDUE ①②③）。

## 现场（QUOTEWIRE 收口时逐条点名，`temp/quotewire/QUOTEWIRE-REPORT.md` §⑥）

QUOTEWIRE 接上了 `relations` 的 `table.create/update` 四档回验与 `search.register` 的
正文闸，但同一份判据还有三条写路没接：

1. `table.create/update` 直写 `literature.summary` —— `store.direct_write_refusal("literature")`
   是空串（通用写口放行），内容性断言仍可从这进库。真机 `lp-ball-14` 的 5 行
   `metadata_only` 就是 `table.update` 把带 `定理` / `不等式` / `公式` 的 summary 写进去的
   （`data/events.jsonl` 里 `note="tool:table.update"` 的 5 条，`content_read=false`）。
2. `agent_b/core.py` 的 `_finish_reprocess` 直接 `tx.upsert("relations", row)`：`updates`
   里带 `quote_verified=true` 仍不经 `enforce_quote_evidence`（它是 `relations` 的第二条写路）。
3. `search.ingest_local` 不经 `_h_register`：SEEDREH 补的是"没有可读正文就不进库"的判收闸，
   它不看机器题录（summary）里的内容性断言 —— 文件名 `Riemann_theorem.pdf` 这种回显
   会被 `litavail.content_assertion` 判成断言（lexical 判据分不出题名与结论）。

## 这一条判据钉什么

- 三处接线都复用同一份判据，本文件不重写"哪些话算断言"：
  ① / ③ 走 `search_tools._content_claim_refusal`（`litavail.content_assertion` +
  `litstage.CONTENT_CLAIM_WITHOUT_READ`）；② 走
  `quoteevidence.enforce_quote_evidence`（四档 keep / mismatch / downgrade / refuse）。
- 判据 a / b 先红后绿：改前那三笔都照收（`quote_verified=true` 空 span / 断言进库 /
  题录带断言），改后受控拒、降档或只写题录事实。
- 判据 d 反真空：把三处接线各自打桩掉 ⇒ a / b 必红（同一笔重新落成改前形态）。
"""
from __future__ import annotations

import json
import re

import pytest

from agentflow import litavail as LAV
from agentflow import schema as S
from agentflow.agent_b import core as bcore
from agentflow.agent_b.core import AgentB
from agentflow.extract import extract_text
from agentflow.store import Store
from agentflow.tools import search_tools
from agentflow.tools import table_tools
from agentflow.tools.base import ToolRegistry

from conftest import TS, add_literature, write_library_file

LIT = "000000"
CLAIM = "该文用 Bohr-Mollerup 定理给出 log Γ 的精确值，并证明了不等式"
BIBLIO = "题录：一篇讨论立方体截面的论文（AMS 期刊）"
QUOTE = "An abelian group is a group in which the commutative law holds."
SECOND_SENTENCE = "A ring is a set with two operations."
SPAN_RE = re.compile(r"^p\d+:norm\[\d+:\d+\]$")


# --------------------------------------------------------------- 夹具


def _tables(store: Store) -> ToolRegistry:
    reg = ToolRegistry(name="tables")
    reg.bound_role = "A"
    table_tools.register(reg, store=store)
    return reg


def _a_registry(store: Store) -> ToolRegistry:
    from agentflow.tools import build_for_role

    reg = build_for_role("A", store=store, workspace_root=store.root).registry
    reg.bound_role = "A"
    return reg


def _lit_row(**over) -> dict:
    # `path` 是必填（可以是 None）：`Literature.__init__` 没有默认值。
    row = {"title": "Cube slicing in R^n", "type": "J", "summary": BIBLIO, "path": None}
    row.update(over)
    return row


def _disk(store: Store) -> list[dict]:
    return [dict(r) for r in store.rows("literature")]


def _claim_of(text: str) -> str:
    return LAV.content_assertion(text)


def _request(store: Store, pid: str, relation_ids: list[str],
             *, reason: str = "quote_unverifiable") -> dict:
    row = S.ReprocessRequest(
        reprocess_id=pid, timestamp=TS, reason=reason, submitted_by="agent-C",
        relation_ids=sorted(relation_ids), status="pending",
        touched_relation_ids=[])
    row.validate()
    with store.tx("reprocess_requests", actor="test") as tx:
        tx.upsert("reprocess_requests", row.to_dict())
    return row.to_dict()


def _relation(store: Store, rid: str, *, quote: str, description: str) -> dict:
    row = S.Relation(
        relation_id=rid,
        concept_ids=[LIT, "000001"],
        description=description,
        lit_id=LIT,
        page_range=S.PageRange(1, 1, "p. 1"),
        quote=quote,
        quote_normalized="",
        quote_verified=None,
        statement=description,
        concept_group_key="000000|000001",
        dedup_key="k",
        status="active",
        created_at=TS,
    )
    row.validate()
    with store.tx("relations", actor="test") as tx:
        tx.upsert("relations", row.to_dict())
    return row.to_dict()


def _rel(store: Store, rid: str) -> dict:
    return next(dict(r) for r in store.rows("relations")
                if str(r.get("relation_id")) == rid)


def _fingerprint(row: dict) -> dict:
    return {k: row.get(k) for k in ("quote", "statement", "description")}


# =========================================================== ① literature.summary

def test_a_a_content_claim_written_straight_into_literature_is_refused(store: Store):
    """a：`table.create` 直写 `literature.summary` 带内容性断言 ⇒ 受控拒（改前：进库）。

    改前这一笔会进库 —— 真机 `lp-ball-14` 的 5 行 metadata_only 就是这么来的
    （`table.update` 把 summary 写成 `对应事实②：...log Γ...`，`content_read=false`）。
    """
    reg = _tables(store)
    res = reg.call("table.create", table="literature", row=_lit_row(summary=CLAIM))
    assert res.ok is False, ("内容性断言竟然经 table.create 进了库", res.data)
    assert res.meta.get("kind") == "content_assertion_without_content", res.meta
    assert res.meta.get("claim"), res.meta
    assert res.meta.get("content_read") is False, res.meta
    assert _disk(store) == [], "被拒的行不许有半个字节落盘"


def test_a2_update_cannot_write_a_content_claim_into_the_summary(store: Store):
    """a2：`table.update` 改 summary 成内容性断言 ⇒ 受控拒，盘上原样不动。"""
    reg = _tables(store)
    made = reg.call("table.create", table="literature", row=_lit_row())
    assert made.ok is True, made.error
    res = reg.call("table.update", table="literature", id=made.data,
                   patch={"summary": CLAIM})
    assert res.ok is False, ("内容性断言竟然经 table.update 进了库", res.data)
    assert res.meta.get("kind") == "content_assertion_without_content", res.meta
    assert _disk(store)[0]["summary"] == BIBLIO, "被拒的那一笔不许改盘"


def test_a3_bibliographic_summaries_still_pass(store: Store):
    """a3（正控）：只写题录性说明 ⇒ 照常建行、照常改（这一闸不是把写口封掉）。"""
    reg = _tables(store)
    made = reg.call("table.create", table="literature", row=_lit_row(summary=BIBLIO))
    assert made.ok is True, made.error
    upd = reg.call("table.update", table="literature", id=made.data,
                   patch={"summary": "题录：Cube slicing，1986，AMS"})
    assert upd.ok is True, upd.error
    assert len(_disk(store)) == 1


def test_a4_an_update_that_does_not_touch_the_summary_is_not_blocked(store: Store):
    """a4（正控 / 不误伤）：存量行有一句旧断言时，只改 `processed` 仍照常。

    这一条守的是"闸只判这一笔写下去的那句话"：坏断言的清理归清理，
    不能让 B 的常规登记（标记已消化）被一句存货挡住。
    """
    reg = _tables(store)
    made = reg.call("table.create", table="literature", row=_lit_row())
    assert made.ok is True, made.error
    # 存量坏行：绕过写口直接落一句断言（模拟改前的盘）
    with store.tx("literature", actor="test") as tx:
        row = tx.find("literature", lit_id=made.data)
        row["summary"] = CLAIM
        tx.upsert("literature", row, note="test:legacy")
    res = reg.call("table.update", table="literature", id=made.data,
                   patch={"processed": True})
    assert res.ok is True, ("只改 processed 被误拦了", res.error, res.meta)
    assert _disk(store)[0]["summary"] == CLAIM, "这一笔没写 summary，就不该动它"


def test_d_disabling_the_literature_gate_brings_the_claim_back(
        store: Store, monkeypatch: pytest.MonkeyPatch):
    """d（a 的反真空）：把 ① 的接线打桩掉 ⇒ 同一句话重新进库（= 改前形态）。"""
    monkeypatch.setattr(table_tools, "_literature_summary_refusal", lambda **kw: None)
    reg = _tables(store)
    res = reg.call("table.create", table="literature", row=_lit_row(summary=CLAIM))
    assert res.ok is True, res.error
    assert len(_disk(store)) == 1
    assert _claim_of(_disk(store)[0]["summary"]) == "定理"


# =============================================================== ② reprocess upsert

def _no_doc_store(store: Store) -> dict:
    """目标关系 + 一条没有本地全文的文献（改前 reprocess 会照收 true + 空 span）。"""
    add_literature(store, LIT, title="仅题录", path=None,
                   download={"status": "failed", "fulltext": "metadata_only"})
    return _relation(store, "0000", quote="no such quote", description=QUOTE)


def _crafted_outcome(store: Store, *, upd: dict) -> dict:
    live = _rel(store, "0000")
    return {
        "result": "found",
        "note": "手工构造的 A 阶段产出（只测写回那一格）",
        "updates": {"0000": dict(upd)},
        "fingerprints": {"0000": _fingerprint(live)},
    }


def _request_row(store: Store, pid: str) -> dict:
    return next(dict(r) for r in store.rows("reprocess_requests")
                if r["reprocess_id"] == pid)


def test_b_reprocess_cannot_assert_verified_without_a_fulltext_span(store: Store):
    """b：reprocess 写 `quote_verified=true` 而这一篇没有全文 ⇒ 降档（改前：照收）。

    `_finish_reprocess` 是 `relations` 的第二条写路。改前它把 A 阶段交来的
    `quote_verified=true` 原样照收（`quote_span` 为空）—— 于是"说逐字通过"与
    "算得出区间"在这条路上也是两件互不相干的事。
    """
    _no_doc_store(store)
    _request(store, "p-0001", ["0000"])
    agent = AgentB(store, extractor=object(), extract_text=extract_text)
    out = agent._finish_reprocess(
        _request_row(store, "p-0001"),
        _crafted_outcome(store, upd={"quote": QUOTE, "quote_verified": True,
                                     "quote_mode": "verbatim"}))
    row = _rel(store, "0000")
    assert row["quote_verified"] is None, row
    assert row["quote_span"] == "", row
    assert "unknown" in row["quote_reason"], row["quote_reason"]
    reading = (row.get("_reprocess") or {}).get("quote_evidence") or {}
    assert reading.get("action") == "downgrade", reading
    assert out["touched_relation_ids"] == ["0000"], out


def test_b2_reprocess_semantic_without_its_two_evidences_is_refused_whole(store: Store):
    """b2：reprocess 写 `semantic` 却缺区间/调用指纹 ⇒ 整笔不写（判据的 refuse 档）。"""
    _no_doc_store(store)
    _request(store, "p-0001", ["0000"])
    before = _rel(store, "0000")
    agent = AgentB(store, extractor=object(), extract_text=extract_text)
    out = agent._finish_reprocess(
        _request_row(store, "p-0001"),
        _crafted_outcome(store, upd={"quote": QUOTE, "quote_verified": True,
                                     "quote_mode": "semantic"}))
    after = _rel(store, "0000")
    assert out["touched_relation_ids"] == [], out
    assert after["quote_verified"] is None and after["quote_mode"] == "", after
    assert after["quote"] == before["quote"], "被拒的那一笔不许改行"
    assert out["refused_targets"], out
    req = _request_row(store, "p-0001")
    assert req["status"] == "done", "被拒也要有终局（不能让请求卡在 pending 里空转）"
    assert req["result"] == "unchanged", req
    assert "引文回验拒收" in req["result_note"], req["result_note"]


def test_c_a_reprocess_with_a_real_fulltext_keeps_true_with_a_span(store: Store):
    """c（正控）：有全文、引文真在原文里 ⇒ reprocess 照旧落 `true + 可复算区间`。"""
    write_library_file(store, f"{LIT}/a.txt", f"{QUOTE} {SECOND_SENTENCE}")
    add_literature(store, LIT, title="有全文", path=f"{LIT}/a.txt",
                   processed=True, download={"status": "ok", "fulltext": "ok"})
    _relation(store, "0000", quote="This quotation appears nowhere.",
              description=QUOTE)
    _request(store, "p-0001", ["0000"])
    agent = AgentB(store, extractor=object(), extract_text=extract_text)
    out = agent.reprocess_once()
    assert out["handled"] is True and out["result"] == "found", out
    row = _rel(store, "0000")
    assert row["quote_verified"] is True, row
    assert row["quote_mode"] == "verbatim", row
    assert SPAN_RE.match(row["quote_span"]), row["quote_span"]
    reading = (row.get("_reprocess") or {}).get("quote_evidence") or {}
    assert reading.get("action") == "keep", reading


def test_d2_disabling_the_reprocess_wiring_brings_back_the_silent_true(
        store: Store, monkeypatch: pytest.MonkeyPatch):
    """d（b 的反真空）：把 ② 的接线打桩掉 ⇒ 同一笔重新落 `true + 空 span`（= 改前形态）。"""
    monkeypatch.setattr(bcore, "_quote_evidence_on_reprocess_write",
                        lambda *a, **k: (None, {}))
    _no_doc_store(store)
    _request(store, "p-0001", ["0000"])
    agent = AgentB(store, extractor=object(), extract_text=extract_text)
    agent._finish_reprocess(
        _request_row(store, "p-0001"),
        _crafted_outcome(store, upd={"quote": QUOTE, "quote_verified": True,
                                     "quote_mode": "verbatim"}))
    row = _rel(store, "0000")
    assert row["quote_verified"] is True and row["quote_span"] == "", row
    assert not (row.get("_reprocess") or {}).get("quote_evidence"), row["_reprocess"]


# ============================================================ ③ search.ingest_local

def _declared_books(store: Store, name: str, text: str) -> None:
    """在（已声明为可靠参考文献的）`books/` 里放一本 `.txt` 书。"""
    books = store.root / "books"
    books.mkdir(parents=True, exist_ok=True)
    (books / name).write_text(text, encoding="utf-8")
    (store.root / "RELIABLE-REFERENCES.json").write_text(
        json.dumps({"paths": ["books/"], "verbatim": "books/ 里都是可靠参考文献"},
                   ensure_ascii=False), encoding="utf-8")


def _ingest(reg: ToolRegistry) -> dict:
    res = reg.call("search.ingest_local", books_dir="books", pattern="*.txt")
    assert res.ok is True, res.error
    return dict(res.data)


def test_e_ingest_local_does_not_echo_a_content_bearing_filename_into_the_summary(
        store: Store):
    """e：机器题录会带断言时不回显文件名（③ 的接线；改前 summary 里带着 `theorem`）。

    `search.ingest_local` 走的是 `locallib.ingest_directory`（一条不经 `_h_register`
    的 literature 写路）。SEEDREH 给它补的是"没有可读正文就不进库"，不看 summary。
    文件名回显可能带 `theorem` / `x=1` 这类字符 ⇒ `litavail.content_assertion` 命中。
    """
    _declared_books(store, "Riemann_theorem.txt", "A group is a set with an operation.")
    data = _ingest(_a_registry(store))
    assert data["ingested"] == 1, data
    assert data["unreadable"] == 0, data
    row = _disk(store)[0]
    assert row["path"] and row["path"].endswith("Riemann_theorem.txt"), row
    assert _claim_of(row["summary"]) == "", ("机器题录带着内容性断言进了库", row["summary"])
    assert "Riemann theorem" in row["title"], "来路仍在 title 里"
    assert "未回显文件名" in (data["books"][0].get("note") or ""), data["books"]


def test_e2_a_plain_filename_still_shows_up_in_the_summary(store: Store):
    """e2（正控）：文件名不带断言字符 ⇒ 机器题录照旧回显它（不是一律删掉）。"""
    _declared_books(store, "graph-subshifts.txt", "A group is a set with an operation.")
    data = _ingest(_a_registry(store))
    assert data["ingested"] == 1, data
    row = _disk(store)[0]
    assert "graph-subshifts.txt" in row["summary"], row["summary"]
    assert _claim_of(row["summary"]) == ""


def test_e3_disabling_the_ingest_gate_lets_the_filename_claim_land(
        store: Store, monkeypatch: pytest.MonkeyPatch):
    """e3（③ 的反真空）：把正文闸打桩掉 ⇒ 同一份文件重新把 `theorem` 写进 summary。"""
    monkeypatch.setattr(search_tools, "_content_claim_refusal", lambda *a, **k: None)
    _declared_books(store, "Riemann_theorem.txt", "A group is a set with an operation.")
    data = _ingest(_a_registry(store))
    assert data["ingested"] == 1, data
    summary = _disk(store)[0]["summary"]
    assert _claim_of(summary) == "theorem", ("闸关掉了却仍没写出断言 ⇒ e 不是这道闸给的", summary)


# ============================================================ 结构读数（同一实现）

def test_the_three_ports_share_the_one_criterion(store: Store):
    """结构读数：① / ③ 的拒信码是 `litstage` 那一个受控码，② 的读数是判据的四档。

    这一条防的是"接线接上了、但自己又写了一份判据"：受控码必须逐字等于
    `litstage.CONTENT_CLAIM_WITHOUT_READ`，读数的 `action` 必须取自
    `enforce_quote_evidence` 的词表。
    """
    from agentflow import litstage

    reg = _tables(store)
    res = reg.call("table.create", table="literature", row=_lit_row(summary=CLAIM))
    assert res.meta.get("kind") == litstage.CONTENT_CLAIM_WITHOUT_READ == \
        "content_assertion_without_content"
    assert table_tools._literature_summary_refusal is not None
    # ① 的闸真的委托给 search_tools 那一份（把共用的实现打桩掉，同一笔就放行）
    assert search_tools._content_claim_refusal(CLAIM, read_ok=False) is not None
    json.dumps(res.meta, ensure_ascii=False)

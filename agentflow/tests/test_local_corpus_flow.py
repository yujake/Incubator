"""端到端判据（离线）：本地书架 → 材料 → 模型 → 逐字回验 → 六件产物。

这一条是本次"强化实际能力"的核心判据，因为它同时钉住了三件事：

1. 本地 PDF 真的能走到产物里（来源、页码、全文级回验都落在 `claims.json` / `evidence.json`）；
2. 一份编造的引文必须落 `not_found`（负控：回验这条防线真的在这条路上生效）；
3. 六件产物齐 + 退出码三态，与 `run_topic` 的契约一致。

全程不联网：模型用假传输层，检索用本地书架，全文用本地文件就地读。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentflow import projects as P
from agentflow.locallib import ingest_directory
from agentflow.modelgw import ModelSpec
from agentflow.runflow import ARTIFACTS, run_topic
from agentflow.store import Store

#: 造出来的那本书第 1 页上的原文（模型"逐字抄"的就是它）。
TRUE_QUOTE = "A group is a set with an operation."
FABRICATED_QUOTE = "A group is always finite and cyclic."


def _make_book(path: Path) -> None:
    fitz = pytest.importorskip("fitz", reason="没有 fitz 就造不出带文本层的 PDF")
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), TRUE_QUOTE)
    doc.save(str(path))
    doc.close()


def _transport_with(answer: str):
    calls: list[str] = []

    def _t(url: str, headers, data: bytes, timeout_sec: float):
        calls.append(data.decode("utf-8", errors="replace"))
        body = json.dumps({
            "choices": [{"message": {"role": "assistant", "content": answer}}],
            "usage": {"prompt_tokens": 21, "completion_tokens": 7},
        }, ensure_ascii=False)
        return 200, body

    _t.calls = calls  # type: ignore[attr-defined]
    return _t


# ======================================================================
# 逐页正文按内容寻址只存一份（依据 `draft/30` §T0-2/§T0-3/§T0-6）
# ======================================================================


def _run_with_store(tmp_path: Path, answer: str) -> tuple[dict, Path, Path]:
    """与 `_run` 同一套接线，但把正文存进项目根的 `.fulltext/`（引用形态）。"""
    books = tmp_path / "books"
    books.mkdir()
    _make_book(books / "甲书.pdf")

    ws = tmp_path / "projects" / "project1"
    store = Store(ws)
    store.init()
    ingest_directory(store, books)

    from agentflow.locallib import local_fetch_fn, memo_extract_fn, search_fn_for_store
    extractor = memo_extract_fn()
    out = ws / "out" / "run-1"
    store_dir = ws / ".fulltext"
    res = run_topic(
        store, topic="group operation", budget_usd=1.0, out_dir=out,
        transport=_transport_with(answer), spec=ModelSpec(api_key="selftest-key"),
        max_calls=1,
        search_fn={"localpdf": search_fn_for_store(store, extract_fn=extractor)},
        fetch_fn=local_fetch_fn(), extract_fn=extractor, fulltext=True,
        retrieval_limit=3, now="2026-01-01T00:00:00+00:00",
        text_store_dir=store_dir,
    )
    return res, out, store_dir


def test_ref_form_keeps_verification_and_stores_one_copy_per_book(tmp_path: Path):
    """引用形态：产物里只有 `text_ref`，正文在 `.fulltext/` 里只占一份，回验仍到全文级。

    这一条把三件事钉在真实管线上（而不是单元级别）：写侧真的写引用、
    读侧真的认引用、以及"同一本书只存一份"真的成立。
    """
    pytest.importorskip("fitz", reason="没有 fitz 就造不出带文本层的 PDF")
    answer = f"- 群带一个运算 || {TRUE_QUOTE}"
    res, out, store_dir = _run_with_store(tmp_path, answer)

    ev = json.loads((out / "evidence.json").read_text(encoding="utf-8"))
    sources = [s for s in ev["sources"] if s.get("fulltext", {}).get("status") == "ok"]
    assert sources, "本地书架这条路必须拿到全文"
    for s in sources:
        ft = s["fulltext"]
        assert ft["text_store"] == "ref" and "text_ref" in ft and "text_pages" not in ft

    files = sorted(store_dir.glob("*.json"))
    assert len(files) == 1, f"同一本书同一份正文只许存一份，实测 {len(files)} 份"

    rows = json.loads((out / "claims.json").read_text(encoding="utf-8"))["claims"]
    assert rows and rows[0]["verdict"] == "verified"
    assert rows[0]["level"] == "fulltext", "引用形态下回验必须仍能到全文级"
    assert "fulltext_text_unavailable" not in ev["verification"], (
        "干净时那把键不许出现（常驻空列表会被读成永远没问题）")


def test_verification_from_ledger_carries_broken_refs_and_hides_the_key_when_clean():
    """坏引用必须进产物；干净时那把键不出现（常驻空列表会被读成"永远没问题"）。"""
    from agentflow.runflow import _verification_from_ledger

    class _Split:
        def to_dict(self) -> dict:
            return {"status": "parsed", "claim_count": 1}

    rows = [{"verdict": "not_found", "level": "", "reason": "not_found"}]
    evidence = {"checked": True}
    clean = _verification_from_ledger(rows, _Split(), evidence)
    assert "fulltext_text_unavailable" not in clean["check"]
    assert "fulltext_text_unavailable" not in clean["counts"]

    broken = _verification_from_ledger(
        rows, _Split(), evidence,
        text_ref_problems=("store_file_missing：D:/x/.fulltext/ab.json",))
    assert broken["counts"]["fulltext_text_unavailable"] == 1
    assert "store_file_missing" in broken["check"]["fulltext_text_unavailable"][0]
    assert "不是'这篇没有全文'" in broken["reason"]


def _run(tmp_path: Path, answer: str) -> tuple[dict, Path, object]:
    books = tmp_path / "books"
    books.mkdir()
    _make_book(books / "甲书.pdf")

    ws = tmp_path / "projects" / "project1"
    store = Store(ws)
    store.init()
    ingest_directory(store, books)

    from agentflow.locallib import local_fetch_fn, memo_extract_fn, search_fn_for_store
    extractor = memo_extract_fn()
    out = ws / "out" / "run-1"
    transport = _transport_with(answer)
    res = run_topic(
        store, topic="group operation", budget_usd=1.0, out_dir=out,
        transport=transport, spec=ModelSpec(api_key="selftest-key"), max_calls=1,
        search_fn={"localpdf": search_fn_for_store(store, extract_fn=extractor)},
        fetch_fn=local_fetch_fn(), extract_fn=extractor, fulltext=True,
        retrieval_limit=3, now="2026-01-01T00:00:00+00:00",
    )
    return res, out, transport


def test_local_corpus_reaches_fulltext_verification(tmp_path: Path) -> None:
    res, out, _t = _run(tmp_path, f"- 群带一个运算 || {TRUE_QUOTE}")

    assert res["exit_code"] == 0, f"这一跑应当成功：{res}"
    missing = [a for a in ARTIFACTS if not (out / a).is_file()]
    assert missing == [], f"缺产物：{missing}"

    ev = json.loads((out / "evidence.json").read_text(encoding="utf-8"))
    assert ev["status"] == "ok" and ev["source_count"] == 1
    src = ev["sources"][0]
    assert src["source"] == "localpdf" and src["title"]
    assert src["fulltext"]["status"] == "ok", "本地文件必须能走到全文级"
    assert src["fulltext"]["pages"] >= 1 and src["fulltext"]["sha256"]
    assert "fulltext" in (ev["verification"]["levels_reached"] or [])

    cl = json.loads((out / "claims.json").read_text(encoding="utf-8"))
    claims = cl["claims"]
    assert [c["verdict"] for c in claims] == ["verified"]
    assert claims[0]["level"] == "fulltext", "有全文时回验必须报到全文级"
    assert claims[0]["evidence_source"] == src["source_id"]
    assert claims[0]["locator"]["page"] >= 1, "断言必须能说出在第几页"
    assert claims[0]["quote"] == TRUE_QUOTE


def test_a_fabricated_quote_is_not_verified(tmp_path: Path) -> None:
    """负控：编造的引文必须落 `not_found`。

    这条不红的话，"本地书架 + 逐字回验"就只是两句好听的话：
    模型抄不抄得对没人管，报告里照样写"verified"。
    """
    res, out, _t = _run(
        tmp_path,
        f"- 群带一个运算 || {TRUE_QUOTE}\n- 群是有限循环群 || {FABRICATED_QUOTE}",
    )
    # 两条都写在同一次答复里：一条真、一条假。
    cl = json.loads((out / "claims.json").read_text(encoding="utf-8"))
    verdicts = {c["quote"]: c["verdict"] for c in cl["claims"]}
    assert verdicts.get(TRUE_QUOTE) == "verified", f"真引文必须过：{verdicts}"
    assert verdicts.get(FABRICATED_QUOTE) == "not_found", (
        f"编造的引文被放过了 ⇒ 回验没咬住：{verdicts}"
    )
    assert res["exit_code"] == 0, "回验未通过不改退出码（那是刻意的取舍）"


def test_the_model_sees_local_text_not_the_network(tmp_path: Path) -> None:
    """正控：prompt 里必须真的带着那本书的原文（否则"依据材料作答"是空话）。"""
    _res, _out, transport = _run(tmp_path, f"- 群带一个运算 || {TRUE_QUOTE}")
    assert transport.calls, "一次模型调用都没发"
    prompt = transport.calls[0]
    assert TRUE_QUOTE in prompt, "prompt 里没有本地书的原文"
    assert "可用材料" in prompt and "localpdf" in prompt


def test_projects_layer_uses_the_same_seam(tmp_path: Path) -> None:
    """项目层与这条接缝是同一条路：`projects.run_project` 注入的 run_topic 收得到这三个接缝。"""
    books = tmp_path / "books"
    books.mkdir()
    _make_book(books / "甲书.pdf")
    seen: dict = {}

    def _fake(store, **kw):
        seen.update(kw)
        Path(kw["out_dir"]).mkdir(parents=True, exist_ok=True)
        return {"exit_code": 0}

    P.run_project(tmp_path / "projects", name="project1", start="cold",
                  topic="group operation", books_dir=books, run_topic_fn=_fake)
    assert set(seen["search_fn"]) == {"localpdf"}
    assert callable(seen["fetch_fn"]) and callable(seen["extract_fn"])


def test_the_prompt_pins_the_two_lessons_real_books_taught_us() -> None:
    """提示词里的两条硬规则必须还在 —— 它们是真跑教出来的，不是写作文。

    ① 页码一律用 `<<<PAGE n>>>` 里的 n，不许用书里印的页码。实测（2026-09-28，一本 284 页的书）：模型按印着的页码报，恒定比实际小 5（那本书有 5 页前言/目录），12 条关系的引文逐字都对、页码全错，于是全部被判 not_found；改完这条之后同一本书 10/10 页码对得上、0 条未过。② 概念/关系各最多 12 条。实测：不设上限时，417 页那本书的抽取输出被 token 上限截在半句上，解析失败，整次抽取作废（连已经正确的条目一起丢）。

    判据形状说明：这是"钉住请求内容"的判据，不是"模型会遵守"的判据 —— 后者只能靠真跑（`temp/_page_fix_ab.py` 就是那条真跑）。把规则从提示词里删掉，这条会红；模型照不照做，这条管不了，也不假装管得了。"""
    from agentflow.llm import DEFAULT_PROMPT_TEMPLATE as T

    assert "<<<PAGE n>>>" in T
    assert "不要用书里印" in T, "页码口径那条硬规则被删掉了"
    assert "最多 12 条" in T, "条数上限那条硬规则被删掉了"
    assert "not_found" in T, "规则里应当写明页码错会让回验判 not_found（否则模型不知道代价）"

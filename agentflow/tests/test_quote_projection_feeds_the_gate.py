"""引文回验的归一化必须只有一处真身，且剔除必须留名。

## 这一份判据钉的是什么

2026-11-21 真机 `projects/lp-ball-15` 的日志里连续 32 行「剔除引文无法回验的关系
（疑似幻觉）」，逐条回原文核过之后 29 条是真引文（PDF 的断行 / 断词连字符 / 连字 /
控制字符 / 括号内侧空白）。缺陷不在判据，在归一化：写侧
（`llm._locate_verbatim`）用 NFKC 口径、收工门（`quoteverify.check_quote`）用 NFC
口径，两边各差一点，于是同一句话在一边过、在另一边不过。

所以这一份判据分四组：

- a：真引文换了个排版（跨行断词、连字、控制字符、括号内侧空白）⇒ 必须回验通过。
  改前这些全红（旧口径连 `Gen- \\neralized` 都对不上 `Generalized`）。
- b：正控 —— 改词、颠倒语序、换数字、改标点 ⇒ 必须仍然不通过。
  没有这一组，"归一化修好了"就无法与"把闸门放松了"区分开。
- c：剔除必须留名（原因 + 引文 + 概念名 + 哪一本书），并且要进回执：
  `--extract` 那条路写进 `tasks` 行，真机走的 `B.run_once` 那条路写进 `details`。
  改前只有一行截到 80 字的日志，盘上无处可复核。
- d：反真空 —— 把归一化打桩回旧口径 ⇒ a 必红；把留名打桩掉 ⇒ c 必红。
"""

from __future__ import annotations

import json
import unicodedata

import pytest

from agentflow import llm as L
from agentflow import projects as P
from agentflow import quoteverify as QV
from agentflow.extract import DocumentText
from agentflow.llm import LLMExtractor
from agentflow.schema import PageRange
from agentflow.store import Store

#: 真机那一页的形态：断词连字符 + 换行 + 行末空白（`Gen- \\neralized`）。
PAGE = (
    "W. Blaschke considered a wider class of convex bodies, which is called generalized\n"
    "zonoids. Blaschke showed that all sufficiently high differentiable convex bodies are\n"
    "generalized zonoids. Gen- \neralized zonoids are dense in the space of all symmetric\n"
    "convex bodies equipped with the Hausdorff metric. Schneider has also treated them."
)

#: 模型抄回来的那一句（它把断词拼回去了，这是"同一段文字"）。
QUOTE_DEHYPHENATED = (
    "Generalized zonoids are dense in the space of all symmetric convex bodies equipped "
    "with the Hausdorff metric."
)


def _doc(page: str = PAGE) -> DocumentText:
    return DocumentText(text=page, pages=[page], source_kind="pdf")


# ------------------------------------------------------------------ a：真引文必须过


def test_a_quote_that_is_hyphenated_across_a_line_break_is_verified():
    """跨行断词（`Gen- \\neralized`）⇒ 回验通过（改前判 not_found）。"""
    chk = QV.check_quote(_doc(), QUOTE_DEHYPHENATED, PageRange(1, 1, "p. 1"))
    assert chk.verified is True, chk
    assert chk.reason == "substring_match"


@pytest.mark.parametrize(
    ("page", "quote", "why"),
    [
        # 连字（ﬁ）与连词：PDF 文本层常把 fi/fl 压成一个码位
        ("Then Ck(K) cannot be included in an (Hν, ν)-rectiﬁable subset.",
         "Then Ck(K) cannot be included in an (Hν, ν)-rectifiable subset.", "连字"),
        # 符号字体把 ">" 抽成控制字符（真机第 26 条）
        ("ξ ∈Sn−1 : ⟨η, ξ⟩>\n\x15\n1 −ϵ2} the spherical cap",
         "ξ ∈Sn−1 : ⟨η, ξ⟩>\n1 −ϵ2} the spherical cap", "控制字符"),
        # 括号内侧的空白（PDF 换行造出来的 "p\n)"、"( deﬁned"）
        ("vol(PHn Bn\np\n)\nvol(Bn−1\np\n)",
         "vol(PHn Bn p) vol(Bn−1 p)", "括号内侧空白"),
        # 断词连字符 + 真连字符在同一个词里（`(Hm, m)-\\nrectifiable`）
        ("one calls A ⊂X, with Hm(A) < ∞, (Hm, m)-\nrectiﬁable, if,",
         "one calls A ⊂X, with Hm(A) < ∞, (Hm, m)-rectifiable", "真连字符"),
    ],
)
def test_a_real_quote_survives_layout_noise(page, quote, why):
    """同一段文字换了排版 ⇒ 必须命中（每一条都是真机日志里的一类）。"""
    chk = QV.check_quote(_doc(page), quote, PageRange(1, 1, "p. 1"))
    assert chk.verified is True, (why, chk)


def test_the_write_side_and_the_gate_share_one_projection():
    """写侧（`_locate_verbatim`）与收工门（`check_quote`）对同一句给出同一判决。

    改前这两个函数各写了一份归一化：写侧 NFKC、门里 NFC。于是"连字/断词"这类
    形态在写侧过、在门里不过 —— 本判据钉的就是"两处判决不许分家"。
    """
    doc = _doc()
    hit = L._locate_verbatim(doc.text, QUOTE_DEHYPHENATED)
    assert hit is not None, "写侧没定位到：写侧与门读的可能不是同一个投影"
    assert hit in doc.text, "写侧返回的必须是原文切片（不是模型原话）"
    chk = QV.check_quote(doc, hit, PageRange(1, 1, "p. 1"))
    assert chk.verified is True, ("写侧命中的切片，门里判不通过 ⇒ 两处口径分家", chk)
    # 反过来：门里判通过的引文，写侧也必须定位得到（同一句、同一个投影）。
    assert QV.quote_match_text(QUOTE_DEHYPHENATED) in QV.quote_match_text(doc.text)


# ------------------------------------------------------------------ b：正控（不许放松）


@pytest.mark.parametrize(
    "quote",
    [
        # 颠倒语序
        "Generalized zonoids are dense in the symmetric space of all convex bodies equipped",
        # 换一个词
        "Generalized zonoids are dense in the space of all symmetric convex bodies furnished "
        "with the Hausdorff metric.",
        # 换数字（真机第 25 条附近那一类公式）
        "Generalized zonoids are dense in the space of 2 symmetric convex bodies equipped "
        "with the Hausdorff metric.",
        # 整句编造
        "The Hausdorff metric is the unique invariant of a generalized zonoid.",
    ],
)
def test_b_wrong_words_order_or_numbers_are_still_not_found(quote):
    """正控：归一化只是一次"同一化"，不是一次放松 —— 改词/颠倒/换数字仍然不命中。"""
    chk = QV.check_quote(_doc(), quote, PageRange(1, 1, "p. 1"))
    assert chk.verified is False, chk
    assert chk.reason == "not_found"
    assert L._locate_verbatim(PAGE, quote) is None


def test_b_punctuation_is_still_part_of_the_criterion():
    """标点仍算字：`holds, for` 与 `holds for` 不等价，句末 `,` 抄成 `.` 也不等价。

    这是模块 docstring 里那条"不删标点"的判据的机器版 —— 归一化扩到版式噪声，
    但一个字都没往标点上走。
    """
    page = "It converges pointwise almost everywhere to zero if and only if An →0 as n →∞, or"
    assert QV.check_quote(_doc(page), "It converges pointwise almost everywhere to zero if and "
                                      "only if An →0 as n →∞.",
                          PageRange(1, 1, "p. 1")).verified is False
    assert QV.check_quote(_doc("Commutative law holds, for every pair."),
                          "Commutative law holds for every pair.",
                          PageRange(1, 1, "p. 1")).verified is False


def test_b_a_minus_sign_is_not_a_line_break():
    """公式里的减号不是断词：把 `f −g2` 抄成 `f g2` 必须不命中（归一化不许吃运算符）。"""
    page = "We have f −g2 bounded."
    assert QV.check_quote(_doc(page), "We have f g2 bounded.",
                          PageRange(1, 1, "p. 1")).verified is False
    assert QV.check_quote(_doc(page), "We have f −g2 bounded.",
                          PageRange(1, 1, "p. 1")).verified is True


def test_the_projection_is_idempotent():
    """投影必须幂等：写侧与门里各投影一次不许得到两个串。

    `quote_span` 的区间（`p{页}:norm[起:止]`）就建在"归一化后的坐标系"上：
    投影不幂等的话，写侧算出的区间到读侧再投影一次就错位，一条真引文会因此
    被降成 unknown —— 那正是这一趟要修掉的形态之一。
    """
    for text in (PAGE, QUOTE_DEHYPHENATED, "2 −g2 and A—B, (Hm, m)-rectifiable"):
        once = QV.quote_match_text(text)
        assert QV.quote_match_text(once) == once, text


# ------------------------------------------------------------------ c：剔除必须留名

_FABRICATED = "The spectrum is always a compact set."


class _FakeClient:
    """离线假客户端：把预置字符串当模型回复。"""

    def __init__(self, payload: str) -> None:
        self.payload = payload

    def complete(self, prompt: str) -> str:  # noqa: ARG002 - 契约要求这个名字
        return self.payload


def _payload(quote: str, names: list[str] | None = None) -> str:
    return json.dumps(
        {
            "concepts": [{"name": "spectrum"}, {"name": "interval"}],
            "relations": [
                {
                    "concept_names": names or ["spectrum", "interval"],
                    "description": "谱落在区间内",
                    "quote": quote,
                    "page_range": {"start": 1, "end": 1},
                }
            ],
        },
        ensure_ascii=False,
    )


def _extract(quote: str, names: list[str] | None = None) -> LLMExtractor:
    ex = LLMExtractor(_FakeClient(_payload(quote, names)))
    ex.extract(_doc(), "0017", {})
    return ex


def test_c_a_dropped_relation_leaves_reason_quote_and_names():
    """剔除必须留痕：一条被剔掉的关系要能读出"哪一本、哪一句、为什么、两个概念"。"""
    ex = _extract(_FABRICATED)
    rep = ex.last_report
    assert rep["relations_dropped"] == 1
    assert rep["drop_reasons"] == ["quote_not_found"]
    items = rep["drop_items"]
    assert len(items) == 1, rep
    item = items[0]
    assert item["reason"] == "quote_not_found"
    # 整句都要留住（改前日志只留 80 字，事后无法拿它回原文复核）
    assert item["quote"] == _FABRICATED
    assert item["quote_chars"] == len(_FABRICATED)
    assert item["quote_truncated"] is False
    assert item["concept_names"] == ["spectrum", "interval"]


def test_c_the_receipt_names_the_dropped_relation():
    """回执（CLI / `tasks` 那一行）要点名：只给一个计数等于让它静默消失。"""
    ex = _extract(_FABRICATED)
    ex.last_report["lit_id"] = "0017"
    lines = P.drop_receipt_lines({"relations_dropped": 1, "drop_reasons": ["quote_not_found"],
                                 "dropped_items": [dict(ex.last_report["drop_items"][0],
                                                        lit_id="0017")]})
    assert len(lines) == 1, lines
    joined = " ".join(lines)
    assert "0017" in joined and "quote_not_found" in joined and "spectrum" in joined
    assert _FABRICATED[:40] in joined


def test_c_the_task_row_on_disk_carries_the_names(tmp_path):
    """`tasks.json` 是盘上的回执：抽取收尾时要把点名写进那一行（不是只打日志）。"""
    store = Store(tmp_path)
    store.init()
    task_id = P._open_extract_task(store, "lp-test", "books")
    extraction = {
        "concepts_created": 0, "relations_added": 0, "processed": 1,
        "relations_dropped": 1, "drop_reasons": ["quote_not_found"],
        "dropped_items": [{"lit_id": "0017", "reason": "quote_not_found",
                           "quote": _FABRICATED, "concept_names": ["spectrum", "interval"]}],
    }
    P._close_extract_task(store, task_id, extraction)
    row = next(r for r in store.rows("tasks") if r.get("task_id") == task_id)
    assert row["status"] == "done" and row["outcome"] == "ok"
    detail = str(row["detail"])
    assert "quote_not_found" in detail, detail
    assert "0017" in detail, detail
    assert _FABRICATED[:40] in detail, detail


class _DroppingExtractor:
    """假抽取器：一条关系都不给，但像真机那样把"剔了几条"记进 `last_report`。"""

    is_framework_fallback = False

    def __init__(self) -> None:
        self.last_report: dict = {}

    def extract(self, doc, lit_id, meta):  # noqa: ARG002 - 契约要求这三个名字
        self.last_report = {
            "lit_id": lit_id, "relations_dropped": 1,
            "drop_reasons": ["quote_not_found"],
            "drop_items": [{"reason": "quote_not_found", "quote": _FABRICATED,
                            "quote_chars": len(_FABRICATED), "quote_truncated": False,
                            "concept_names": ["spectrum", "interval"]}],
        }
        return [], []


def test_c_the_b_run_once_detail_names_the_dropped_quote(tmp_path):
    """真机走的是 `host` → `B.run_once`（不是 `--extract`）：那条路也要点名。

    改前这条路一个字节都不落盘：`last_report` 只在内存里，而 `agent_b` 从不读它
    ⇒ 32 条剔除在盘上只剩滚过去的 warning。
    """
    from agentflow.agent_b import AgentB
    from agentflow.extract import DocumentText

    store = Store(tmp_path)
    store.init()
    lib = tmp_path / "library"
    lib.mkdir(exist_ok=True)
    book = lib / "book.txt"
    book.write_text("Some source text about spectra.", encoding="utf-8")
    from conftest import add_literature

    add_literature(store, "0017", path="book.txt")
    b = AgentB(store, extractor=_DroppingExtractor(),
               extract_text=lambda p: DocumentText(text=book.read_text(encoding="utf-8"),
                                                   pages=[book.read_text(encoding="utf-8")],
                                                   source_kind="txt"),
               config={})
    res = b.run_once().to_dict()
    entry = next((d for d in res["details"]
                  if d.get("stage") == "extract" and d.get("dropped")), None)
    assert entry is not None, res["details"]
    assert entry["lit_id"] == "0017"
    assert entry["drop_reasons"] == ["quote_not_found"]
    assert entry["dropped_items"][0]["quote"] == _FABRICATED


# ------------------------------------------------------------------ d：反真空


def _old_gate_projection(text: str) -> str:
    """改前收工门的口径（NFC + 全半角 + 小写 + 连字符/引号归一 + 空白折叠）。"""
    t = unicodedata.normalize("NFC", text or "")
    t = t.translate({0x3000: " ", **{c: c - 0xFEE0 for c in range(0xFF01, 0xFF5F)}})
    t = t.lower()
    for code in ("\u2010\u2015"):
        t = t.replace(code, "-")
    return " ".join(t.split())


def test_d1_stubbing_the_projection_back_to_the_old_one_makes_a_red(monkeypatch):
    """反真空：把投影打桩回旧口径 ⇒ 判据 a 必红（证明 a 读的是投影真身）。"""
    monkeypatch.setattr(QV, "quote_match_text", _old_gate_projection)
    chk = QV.check_quote(_doc(), QUOTE_DEHYPHENATED, PageRange(1, 1, "p. 1"))
    assert chk.verified is False, ("打桩没生效：a 读的可能不是归一化真身", chk)
    assert chk.reason == "not_found"


def test_d1b_without_layout_rules_the_real_run_quotes_would_be_dropped(monkeypatch):
    """同一句话：新口径命中、旧口径不命中 —— 两个读数同时给，防"本来就不该命中"。"""
    assert QV.check_quote(_doc(), QUOTE_DEHYPHENATED,
                          PageRange(1, 1, "p. 1")).verified is True
    monkeypatch.setattr(QV, "quote_match_text", _old_gate_projection)
    assert QV.check_quote(_doc(), QUOTE_DEHYPHENATED,
                          PageRange(1, 1, "p. 1")).verified is False


def test_d2_without_the_recorder_the_drop_has_no_name(monkeypatch):
    """反真空：把留痕关掉（上限置 0）⇒ 判据 c 必红（没有名字可点）。"""
    monkeypatch.setattr(LLMExtractor, "_MAX_DROP_ITEMS", 0)
    ex = _extract(_FABRICATED)
    assert ex.last_report["relations_dropped"] == 1
    assert ex.last_report["drop_items"] == [], (
        "打桩没生效：c 读的可能不是留痕真身", ex.last_report)
    assert P.drop_receipt_lines({"relations_dropped": 1,
                                 "dropped_items": ex.last_report["drop_items"]}) == []

"""分块抽取（2026-10-15，T5 第 8 趟 `t5h` 的实测阈值）的判据。

## 这一组测试防的是什么

T5 第 8 趟里 B 连跑 11 次报 ok 却零产出。事后逐篇读数（`draft/121` §七）
给出的原因不是"模型偷懒"，而是**一整篇一次调用**这条装配：

    正文字符     结局
      10,396    ✓ 抽出来了
       2,720    ✗ 上游超时（另一档）
      22,874    ✗ `output_exhausted`（思维链 28,080 字）
      81,903    ✗（26,995 字；已被 `max_chars` 截到 60,000 再喂）
   1,319,328    ✗（32,039 字；468 页的书，同样只喂了前 60,000 字符 = 4.5%）

于是 `LLMExtractor` 改成"按页切块、一块一次调用"，并且**一块失败不拖垮整篇**。
这一组测试把这条装配的每一条性质钉住 —— 尤其是"不拖垮"那一条：
它既是这一轮修复的目的，也是最容易在重构里悄悄退回"一失败就整篇丢"的地方。
"""

from __future__ import annotations

import json

import pytest
from agentflow.extract import DocumentText
from agentflow.llm import (
    ConceptDraft,
    ExtractionError,
    LLMExtractor,
    RelationDraft,
)


class _Scripted:
    """照剧本回答的假客户端：把每次调用收到的 prompt 记下来，按序回包。"""

    def __init__(self, *replies: object) -> None:
        self.replies = list(replies)
        self.prompts: list[str] = []

    def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        idx = len(self.prompts) - 1
        reply = self.replies[idx] if idx < len(self.replies) else self.replies[-1]
        if isinstance(reply, Exception):
            raise reply
        return str(reply)


def _payload(concepts=(), relations=()) -> str:
    return json.dumps({"concepts": list(concepts), "relations": list(relations)},
                      ensure_ascii=False)


def _relation(names, quote, page=1, description="d"):
    return {"concept_names": list(names), "description": description,
            "quote": quote, "page_range": {"start": page, "end": page}}


def _pages(n: int, *, size: int = 400) -> tuple[list[str], list[str]]:
    """造 `n` 页；每页的文字是**可逐字引用**的（引文回验要靠它）。"""
    pages = [f"Page {i + 1} says: " + ("x" * (size - 20)) for i in range(n)]
    return pages, pages


# ============================================================ 切块本身


def test_a_short_document_is_still_exactly_one_chunk():
    """负控：短文献不许被无谓地切（切块本身有成本：每次调用都是一笔钱）。"""
    pages, _ = _pages(1, size=100)
    doc = DocumentText(text="\n".join(pages), pages=pages, source_kind="pdf")
    ex = LLMExtractor(_Scripted(_payload()), chunk_chars=10_000)
    assert len(ex._chunk_bodies(doc)) == 1
    ex.extract(doc, "0000", {})
    assert ex.last_report["chunks"] == 1


def test_a_long_document_is_split_into_bounded_chunks():
    """正控：一篇长文献 ⇒ 多块，且每一块都不超过 `chunk_chars`。

    上界同时是**成本上界**：块数 = ceil(总字符 / chunk_chars)，
    所以"一次调用噎死"这件事在结构上不可能再发生。
    """
    pages, _ = _pages(40, size=400)          # 16,000 字符
    doc = DocumentText(text="\n".join(pages), pages=pages, source_kind="pdf")
    ex = LLMExtractor(_Scripted(_payload()), chunk_chars=2_000)
    bodies = ex._chunk_bodies(doc)
    assert len(bodies) > 1, "16,000 字符在 2,000 的块上限下必须被切开"
    for body, _cut in bodies:
        assert len(body) <= 2_000, len(body)


def test_pages_are_never_cut_in_half():
    """一条页要么整页进某一块，要么（单页就超限时）自己单独一块。

    为什么这条是要紧的：`<<<PAGE n>>>` 标记是 `page_range` 的唯一来源，
    而 `page_range` 是引文回验的输入之一。把一页切成两半会让
    "这一段在第几页"说不清 —— 引文照样能回验，页号却是错的，
    而错页号不会让任何测试变红。

    判据写成"整页（标记 + 正文）必须是**某一块的连续子串**"：
    切碎一页会让它跨在块的边界上，于是任何一块里都找不到这一段。
    """
    pages, _ = _pages(6, size=500)
    doc = DocumentText(text="\n".join(pages), pages=pages, source_kind="pdf")
    ex = LLMExtractor(_Scripted(_payload()), chunk_chars=1_500)
    bodies = [b for b, _cut in ex._chunk_bodies(doc)]
    joined = "\n".join(bodies)
    for n, page in enumerate(pages, start=1):
        block = f"<<<PAGE {n}>>>\n{page}"
        assert any(block in b for b in bodies), f"第 {n} 页被切碎了"
        assert joined.count(f"<<<PAGE {n}>>>") == 1, f"第 {n} 页的标记出现了不止一次"
    assert joined.count("<<<PAGE ") == len(pages), "一页不许被漏掉"


def test_a_page_bigger_than_the_chunk_is_truncated_and_reported():
    """单页就超过 `chunk_chars` ⇒ 它自己一块、截断，并且 `truncated=True`。

    宁可截断并**记一笔**，也不抛：抛会让整篇文献卡住（B 那一侧会退回租约重试，
    而重试对"这一页本来就太长"毫无帮助）。
    """
    huge = "y" * 5_000
    doc = DocumentText(text=huge, pages=[huge], source_kind="pdf")
    ex = LLMExtractor(_Scripted(_payload()), chunk_chars=1_000)
    bodies = ex._chunk_bodies(doc)
    assert len(bodies) == 1 and bodies[0][1] is True, bodies
    ex.extract(doc, "0000", {})
    assert ex.last_report["truncated"] is True


# ============================================================ 一块失败不拖垮整篇


def test_one_bad_chunk_does_not_throw_away_the_good_chunks():
    """**这一组里最重要的一条**：第 2 块炸了，第 1 块的产出必须留下。

    这正是 T5 第 8 趟的真实形态 —— 一整篇一次调用时，"这一次调用失败"
    与"这一篇没救了"是同一件事；切块之后它们必须分开。
    """
    pages, _ = _pages(6, size=400)
    quote = "Page 1 says:"
    doc = DocumentText(text="\n".join(pages), pages=pages, source_kind="pdf")
    good = _payload([{"name": "spectrum"}], [_relation(["spectrum", "interval"], quote)])
    client = _Scripted(good, RuntimeError("上游 900 秒超时"), good)
    ex = LLMExtractor(client, chunk_chars=1_000)
    concepts, relations = ex.extract(doc, "0000", {})
    assert len(client.prompts) >= 2, "必须真的分了块（否则这条测试什么也证明不了）"
    assert [c.name for c in concepts] == ["spectrum"], concepts
    assert len(relations) == 1, relations
    assert ex.last_report["chunks_failed"] == 1, ex.last_report
    assert "RuntimeError" in ex.last_report["chunk_failures"][0]["error"]
    assert ex.last_report["chunk_failures"][0]["chunk"] == 1, "失败的是第 2 块（0 基）"


def test_all_chunks_failing_still_raises_so_the_caller_can_see_it():
    """负控：**全部**块都失败 ⇒ 抛 `ExtractionError`。

    为什么不能"全军覆没也返回空"：B 那一侧的失败语义是
    "不置 `processed`、留 `last_mine_error`、留给租约重试"。
    把"这一篇没抽成"折成"抽成了、只是没有概念"，会让一篇文献
    静默地永远不再被抽 —— 而它在台账上看起来是**成功**的。
    """
    pages, _ = _pages(4, size=400)
    doc = DocumentText(text="\n".join(pages), pages=pages, source_kind="pdf")
    ex = LLMExtractor(_Scripted(RuntimeError("boom")), chunk_chars=800)
    with pytest.raises(ExtractionError) as e:
        ex.extract(doc, "0000", {})
    assert "全部抽取失败" in str(e.value)


def test_a_chunk_that_returns_unparseable_json_counts_as_failed_not_as_empty():
    """坏 JSON 与"这一块确实什么都没有"必须分得开（三态纪律）。

    坏 JSON ⇒ 记成 `chunks_failed`；`{"concepts": [], "relations": []}` ⇒ 记成成功。
    折叠这两者，就等于把"抽取器坏了"写成"这本书没有概念"。
    """
    pages, _ = _pages(1, size=100)
    doc = DocumentText(text="\n".join(pages), pages=pages, source_kind="pdf")

    bad = LLMExtractor(_Scripted("这不是 JSON"), chunk_chars=10_000)
    with pytest.raises(ExtractionError):
        bad.extract(doc, "0000", {})

    empty = LLMExtractor(_Scripted(_payload()), chunk_chars=10_000)
    concepts, relations = empty.extract(doc, "0000", {})
    assert (concepts, relations) == ([], [])
    assert empty.last_report["chunks_failed"] == 0, empty.last_report


# ============================================================ 跨块合并


def test_the_same_concept_in_two_chunks_becomes_one_concept():
    """跨块同名概念只留一条（定义并起来、别名取并集）。

    为什么必须合并：agent_b 的解析是**按名字**做的，同一个名字出现两条
    会让它走到"已存在、复用"的分支；更糟的是概念表里会出现两行同名，
    而下游任何一个 `by name` 的字典都会静默丢掉其中一行。
    """
    a = ConceptDraft(name="spectrum", definition="谱", aliases=["Spectrum"],
                     source_lit_id="0000")
    b = ConceptDraft(name="spectrum", definition="算子的谱集", aliases=["sp"],
                     source_lit_id="0000")
    c = ConceptDraft(name="interval", definition="区间", aliases=[], source_lit_id="0000")
    got = LLMExtractor._merge_concepts([a, b, c])
    by_name = {d.name: d for d in got}
    assert sorted(by_name) == ["interval", "spectrum"], by_name
    assert by_name["spectrum"].definition == "谱；算子的谱集"
    assert by_name["spectrum"].aliases == ["Spectrum", "sp"]


def test_merging_an_empty_definition_never_leaves_a_dangling_separator():
    """负控：空定义合并不许留下孤零零的"；"（那会读成排版问题，不是数据问题）。"""
    got = LLMExtractor._merge_concepts([
        ConceptDraft(name="x", definition="", aliases=[], source_lit_id="0000"),
        ConceptDraft(name="x", definition="甲", aliases=[], source_lit_id="0000"),
        ConceptDraft(name="x", definition="", aliases=[], source_lit_id="0000"),
    ])
    assert got[0].definition == "甲", got[0].definition


def test_relations_dedupe_on_the_verbatim_quote_not_the_description():
    """关系的判重键是 `(概念对, 原话)`：换个说法的同一句原话合掉，
    同一对概念的两段**不同**原话是两条真关系，必须都留。"""
    drafts = [
        RelationDraft(concept_names=["a", "b"], description="说法甲",
                      quote="原话一", page_range=None),
        RelationDraft(concept_names=["b", "a"], description="说法乙（换个说法）",
                      quote="原话一", page_range=None),
        RelationDraft(concept_names=["a", "b"], description="说法甲",
                      quote="原话二", page_range=None),
    ]
    got = LLMExtractor._merge_relations(drafts)
    assert [d.quote for d in got] == ["原话一", "原话二"], [d.quote for d in got]


# ============================================================ 读数


def test_the_report_says_how_many_chunks_were_sent_and_how_many_failed():
    """读数必须能回答"这一篇被分成几块、坏了几块" —— 否则"抽得少"
    与"抽得贵"在台账上长得一样（T5 的教训之一）。"""
    pages, _ = _pages(30, size=400)
    doc = DocumentText(text="\n".join(pages), pages=pages, source_kind="pdf")
    client = _Scripted(_payload([{"name": "n"}]))
    ex = LLMExtractor(client, chunk_chars=1_000)
    ex.extract(doc, "0007", {})
    rep = ex.last_report
    assert rep["lit_id"] == "0007"
    assert rep["chunks"] == len(client.prompts) >= 2
    assert rep["chunks_failed"] == 0
    assert rep["concepts"] == 1 and rep["relations_kept"] == 0
    assert rep["truncated"] is False

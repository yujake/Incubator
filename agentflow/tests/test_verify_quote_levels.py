"""`verify --deep` 的告警分级："已知并承认的坏数据"不能永远把校验搞红。

背景（真实踩到的）：演示数据集里刻意放了一条 `quote_verified=False` 的关系
（引文确实不在原文里），用来验证 C 的信息量评分会因此降级。
但 `verify --deep` 会把"引文找不到"一律报成 error，于是这个数据集永远 verify 失败。

问题在于分级语义：
- 表里已经写了 `quote_verified=False` → 这是一个已知并被记录的缺陷，重算只是确认它。
  它不该是 error —— error 应当是"需要动手修的不一致"，否则红灯会被训练成背景噪音。
- 表里写 `quote_verified=True` 而实际找不到 → 表与现实矛盾，这才是 error。

本文件把这条分级固定下来（两个方向都要断言 —— 只测一个方向容易"修过头"）。
"""

from __future__ import annotations

from agentflow.extract import extract_text
from agentflow.verify import verify_all

from conftest import add_concept, add_literature, add_relation, sync_counters, write_library_file


def _seed(store, *, claim_verified: bool) -> None:
    """造一条引文在原文中不存在的关系；`claim_verified` 决定表里怎么记。"""
    write_library_file(store, "0000/a.txt", "An abelian group is a group in which the commutative law holds.")
    add_literature(store, "0000", title="A", path="0000/a.txt", processed=True)
    add_concept(store, "0000", "group")
    add_concept(store, "0001", "abelian group")
    add_relation(
        store, "0000", ["0000", "0001"], "0000",
        quote="THIS SENTENCE IS NOT IN THE DOCUMENT AT ALL",
        quote_verified=claim_verified,   # False = 已承认；True = 谎报
    )
    sync_counters(store)


def test_acknowledged_bad_quote_is_warning_not_error(store):
    """表里已记 `quote_verified=False` ⇒ 重算确认它是warning，不是 error。"""
    _seed(store, claim_verified=False)
    rep = verify_all(store, deep=True, extract_text=extract_text)
    codes = {i.code for i in rep.warnings}
    assert "quote_known_unverifiable" in codes
    assert "quote_not_found" not in {i.code for i in rep.errors}
    assert rep.ok, "已知并承认的缺陷不该让整库校验失败"


def test_falsely_claimed_verified_quote_is_error(store):
    """表里谎报 `quote_verified=True` ⇒ 必须仍是 error（表与现实矛盾）。"""
    _seed(store, claim_verified=True)
    rep = verify_all(store, deep=True, extract_text=extract_text)
    assert "quote_not_found" in {i.code for i in rep.errors}
    assert not rep.ok


# ============================================================ `E-11`：页码写错


#: 引文逐字出现在这一页（第 2 页），而下面的关系声明的是第 1 页。
_PAGE_TWO = "An abelian group is a group in which the commutative law holds."


def _seed_misdeclared_page(store) -> None:
    """造一条"引文逐字存在、但页码写错"的关系（`E-11` 的形态）。"""
    write_library_file(store, "0000/a.txt", "第一页：这里没有那句话。")
    add_literature(store, "0000", title="A", path="0000/a.txt", processed=True)
    add_concept(store, "0000", "group")
    add_concept(store, "0001", "abelian group")
    add_relation(
        store, "0000", ["0000", "0001"], "0000",
        quote=_PAGE_TWO,
        page_range=(1, 1),          # 实际在第 2 页（±widen=1 内命中）
        quote_verified=True,        # 逐字可达是真的 ⇒ 写入期就是这么记的
    )
    sync_counters(store)


class _MultiPageDoc:
    """两页文档替身：契约只有 `pages`（`quotecheck` 实际读的那一个）。"""

    pages = ["第一页：这里没有那句话。", _PAGE_TWO]


def test_misdeclared_page_range_is_reported_by_deep_verify(store):
    """`E-11` 正控：页码写错的引文必须被 `--deep` 报出来（修之前一声不响）。

    修之前的读数：`check_quote` 给 `verified=True +
    reason='substring_match_outside_declared_range'`，而 `--deep` 只比
    `chk.verified is not stored` —— 重算 True 与表里 True 相同 ⇒ 没有任何 issue；
    下面的 `verified is False` 那一支也不触发。于是这个信号只留在每行的
    `_quote_check` 字典里，全仓库没有检查器消费它。
    """
    _seed_misdeclared_page(store)
    rep = verify_all(store, deep=True, extract_text=lambda _p: _MultiPageDoc())
    codes = {i.code for i in rep.warnings}
    assert "page_range_mismatch" in codes, rep.to_dict()
    iss = next(i for i in rep.warnings if i.code == "page_range_mismatch")
    assert iss.row_id == "0000"
    assert "第 2 页" in iss.message, iss.message


def test_a_correct_page_range_is_not_reported(store):
    """`E-11` 负控的反面：页码正确的引文不许报 `page_range_mismatch`（防误伤）。

    没有这一条，"凡引文都报一条"的实现也能让上面那条绿 —— 而那种实现会把
    每一条正常关系都标黄，等于把这一档又变成噪音（红灯被训练成背景）。
    """
    write_library_file(store, "0000/a.txt", "占位")
    add_literature(store, "0000", title="A", path="0000/a.txt", processed=True)
    add_concept(store, "0000", "group")
    add_concept(store, "0001", "abelian group")
    add_relation(store, "0000", ["0000", "0001"], "0000",
                 quote=_PAGE_TWO, page_range=(2, 2), quote_verified=True)
    sync_counters(store)

    rep = verify_all(store, deep=True, extract_text=lambda _p: _MultiPageDoc())
    assert "page_range_mismatch" not in {i.code for i in rep.warnings}, rep.to_dict()
    assert rep.ok


def test_page_range_mismatch_is_warning_not_error(store):
    """`E-11` 分级：页码写错是 warning（引文本身是真的），不是 error。

    与"引文找不到"（`quote_not_found`，error）的分级对照是刻意的：
    两者处置不同 —— 一个改页码，一个查幻觉。
    """
    _seed_misdeclared_page(store)
    rep = verify_all(store, deep=True, extract_text=lambda _p: _MultiPageDoc())
    assert "page_range_mismatch" not in {i.code for i in rep.errors}, rep.to_dict()
    assert rep.ok, "页码标注错不该让整库校验失败（引文是真的）"

"""`verify --deep` 的告警分级：**"已知并承认的坏数据"不能永远把校验搞红**。

背景（真实踩到的）：演示数据集里刻意放了一条 `quote_verified=False` 的关系
（引文确实不在原文里），用来验证 C 的信息量评分会因此降级。
但 `verify --deep` 会把"引文找不到"一律报成 **error**，于是这个数据集**永远 verify 失败**。

问题在于分级语义：
- **表里已经写了 `quote_verified=False`** → 这是一个**已知并被记录**的缺陷，重算只是**确认**它。
  它不该是 error —— error 应当是"需要动手修的不一致"，否则红灯会被训练成背景噪音。
- **表里写 `quote_verified=True` 而实际找不到** → 表与现实**矛盾**，这才是 error。

本文件把这条分级固定下来（两个方向都要断言 —— 只测一个方向容易"修过头"）。
"""

from __future__ import annotations

from abflow.extract import extract_text
from abflow.verify import verify_all

from conftest import add_concept, add_literature, add_relation, sync_counters, write_library_file


def _seed(store, *, claim_verified: bool) -> None:
    """造一条引文**在原文中不存在**的关系；`claim_verified` 决定表里怎么记。"""
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
    """表里已记 `quote_verified=False` ⇒ 重算确认它是**warning**，不是 error。"""
    _seed(store, claim_verified=False)
    rep = verify_all(store, deep=True, extract_text=extract_text)
    codes = {i.code for i in rep.warnings}
    assert "quote_known_unverifiable" in codes
    assert "quote_not_found" not in {i.code for i in rep.errors}
    assert rep.ok, "已知并承认的缺陷不该让整库校验失败"


def test_falsely_claimed_verified_quote_is_error(store):
    """表里谎报 `quote_verified=True` ⇒ 必须仍是 **error**（表与现实矛盾）。"""
    _seed(store, claim_verified=True)
    rep = verify_all(store, deep=True, extract_text=extract_text)
    assert "quote_not_found" in {i.code for i in rep.errors}
    assert not rep.ok

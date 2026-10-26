# -*- coding: utf-8 -*-
"""集合字段写侧归一化（`draft/156` 的 D5）：排序去重后照收，并把改动记在读数上。

## 修的是什么（真机已核，同一坑连踩 3 次）
`draft/156` 的三次拒信逐字同形：

    relations 行校验失败：concept_ids 声明为集合但未升序去重：['000004', '000002']

`['000004','000002']` 与 `['000002','000002']` 表达得完全清楚 —— "这几个概念之间有关系"。
"集合的规范形态是升序去重"是我们自己的存储契约，不是模型对这件事的表态。此前写侧只有
拒收，于是模型写错次序一次、读一次拒信、再猜一次，三次都栽在同一格。

⇒ 写侧改成"排序去重后照收"，改动过的字段名回在返回值的 `meta.normalized` 上（"我改过
你的输入"可查，不是静默改）。判据只有一处：`schema.normalize_set_fields`（按
`ARRAY_FIELD_KINDS` 里声明为 `set` 的字段归一），两个写口（`table.create` /
`table.update`）都调它。

## 这一条不放宽什么（正控都在这个文件里）
- 元素类型：`'abc'` 仍拒，而且拒信现在是"concept_ids[] 必须是六位十进制"——那才是真问题
  （改前它被"未升序去重"这句挡在前面，模型会去改次序而不是改号）；
- 形状：`concept_ids="000002"`（不是数组）仍拒；
- 混类型：`[2, '000002']` 仍拒，且报的是"元素不是字符串"（判据自己不许炸，`R-05`）；
- 盘上的契约：绕过写口直接拼一行（`store.tx`）照样被 `validate_table` 拒 —— 归一是
  "替模型改输入"，不是"放宽落盘形态"。

## 反真空（没有它，这条判据是橡皮图章）
把归一步打桩成"恒不排序"（`schema.sorted_unique` 打回原样返回）⇒ 第一条判据必须变红。
"""
from __future__ import annotations

import pytest

from agentflow import schema as S
from agentflow.tools import table_tools
from agentflow.tools.base import ToolRegistry

from conftest import add_literature

#: 两条概念行的号（升序是 `["000002", "000004"]`；`["000004", "000002"]` 是模型写反的形态）。
A, B = "000002", "000004"
LIT = "000000"


@pytest.fixture
def tables(store):
    """绑定了 store 的表工具注册表（非只读角色 ⇒ 拿得到写口）。"""
    reg = ToolRegistry(name="tables")
    reg.bound_role = "A"
    table_tools.register(reg, store=store)
    return reg


@pytest.fixture
def seeded(store):
    """两条概念行 + 一篇文献：关系行要引用它们在册。"""
    for cid, label in ((A, "群"), (B, "阿贝尔群")):
        _concept(store, cid, label)
    add_literature(store, LIT, title="T", path=None, processed=True, dedup_key="doi:x")
    return store


def _concept(store, cid: str, label: str) -> None:
    """铺一条概念行（`statements` 里 `kind="concept"`）—— 走 `conceptrows` 那个写入口。

    不用 `table.create(table="statements")`：那张表已不由通用写口直写（`store.\
direct_write_refusal` 的兜底路由），本文件测的是 `relations` 那一格。
    """
    from agentflow import conceptrows as CR

    with store.tx(*CR.tables_for_concept_write(), actor="test") as tx:
        CR.write_concept(tx, stmt_id=cid, label=label, definition="")


def _relation_row(**over) -> dict:
    row = {"concept_ids": [A, B], "description": "描述", "lit_id": LIT, "quote": "q"}
    row.update(over)
    return row


def _disk(store) -> list[dict]:
    """盘上那一份 `relations` 行（读的是快照，不是工具的返回值）。"""
    return list(store.rows("relations"))


# ============================================================ ① 正控：排序去重后照收


def test_unsorted_set_is_written_in_sorted_order_and_the_readout_names_it(tables, seeded):
    """(a) `['000004','000002']` ⇒ 写入成功、落盘 `['000002','000004']`、读数点名归一化过。

    改前红：这一条会拿 `relations 行校验失败：concept_ids 声明为集合但未升序去重`。
    三处断言缺一不可 —— 只断言"写进去了"会把"静默改我输入"当成通过。
    """
    res = tables.call("table.create", table="relations",
                      row=_relation_row(concept_ids=[B, A]))
    assert res.ok, res.error
    # ① 返回值的读数点名了是哪一个字段被改过（不是静默改）
    assert res.meta.get("normalized") == ["concept_ids"], res.meta
    # ② meta.row 是实际落盘的那一份，次序已经是规范形态
    assert res.meta["row"]["concept_ids"] == [A, B], res.meta["row"]["concept_ids"]
    # ③ 盘上那一份也是（不是只在返回值里排好序）
    assert _disk(seeded)[0]["concept_ids"] == [A, B]


def test_duplicate_elements_are_deduped(tables, seeded):
    """(b) 重复元素 ⇒ 去重后写入（三个元素里 `000004` 出现两次）。"""
    res = tables.call("table.create", table="relations",
                      row=_relation_row(concept_ids=[B, A, B]))
    assert res.ok, res.error
    assert res.meta.get("normalized") == ["concept_ids"], res.meta
    assert _disk(seeded)[0]["concept_ids"] == [A, B]


def test_two_identical_elements_still_need_two_concepts(tables, seeded):
    """去重之后只剩一个概念 ⇒ 仍拒，但拒的是"至少 2 个概念"，不是"未升序去重"。

    这一条防的是"归一化把别的判据吃掉"：`['000002','000002']` 去重后是一条只有一个端点的
    关系，那不是集合形态的问题，而是这条关系不成立。改前它被"未升序去重"挡在前面，
    于是读拒信的人只知道次序错了 —— 去重一次就会撞上这条真判据。
    """
    res = tables.call("table.create", table="relations",
                      row=_relation_row(concept_ids=[A, A]))
    assert res.ok is False, res
    assert "至少要有 2 个概念" in str(res.error), res.error
    assert "未升序去重" not in str(res.error), res.error
    assert _disk(seeded) == []


def test_the_update_path_normalizes_the_same_way(tables, seeded):
    """两个写口共用一处判据：`table.update` 里写反的次序也照样被排好、读数也点名。"""
    made = tables.call("table.create", table="relations", row=_relation_row())
    assert made.ok, made.error
    rid = made.data

    upd = tables.call("table.update", table="relations", id=rid,
                      patch={"concept_ids": [B, A]})
    assert upd.ok, upd.error
    assert upd.meta.get("normalized") == ["concept_ids"], upd.meta
    assert _disk(seeded)[0]["concept_ids"] == [A, B]


def test_a_clean_row_reports_an_empty_normalized_list(tables, seeded):
    """三态：没改动 = 空列表（不是 `None`）。空列表说的是"查过、没动"，不是"没查"。"""
    res = tables.call("table.create", table="relations", row=_relation_row())
    assert res.ok, res.error
    assert res.meta.get("normalized") == [], res.meta


# ============================================================ ② 正控：没放宽真正的校验


@pytest.mark.parametrize("bad, needle", [
    (["abc", A], "concept_ids[]"),                 # 形态不成立的号
    (["12", A], "concept_ids[]"),                  # 位数不够
    ("000002", "值不是数组"),                       # 集合字段不是数组
    ([2, A], "元素不是字符串"),                     # 混类型（R-05：判据自己不许炸）
])
def test_illegal_elements_are_still_refused(tables, seeded, bad, needle):
    """(c) 非法元素 / 非法形状 ⇒ 仍拒（正控：归一化不是放宽）。

    第一档特别值得一提：`'abc'` 改前的拒信是"未升序去重"（因为 `['abc','000002']` 恰好
    不是有序的），改正它是本批的顺带收益 —— 现在拒信说的是"concept_ids[] 必须是六位
    十进制"，也就是真问题。所以这里还断言"未升序去重"不在里面：那句话会把去改次序而不是改号。
    """
    res = tables.call("table.create", table="relations",
                      row=_relation_row(concept_ids=bad))
    assert res.ok is False, res
    assert needle in str(res.error), res.error
    assert "未升序去重" not in str(res.error), res.error
    assert _disk(seeded) == [], "被拒的行不许有半个字节落盘"


def test_the_disk_contract_is_not_relaxed(seeded):
    """盘上的形态照旧：绕过写口直接拼一行，`validate_table` 仍然拒。

    为什么这一条必须有：归一的落点是"模型的手"（写口），不是 `validate_table`。后者是
    `store.tx` 的提交块与 `rebuild` 都走的落盘契约，放宽它等于让"绕过写口"变成一条
    静默通道 —— 而 `store.rebuild` 是不可逆的那条路。
    """
    with pytest.raises(ValueError, match="未升序去重"):
        with seeded.tx("relations", actor="test") as tx:
            tx.upsert("relations", {
                "relation_id": S.format_id(0), "concept_ids": [B, A],
                "description": "描述", "lit_id": LIT, "page_range": {},
                "quote": "q", "status": "active",
            })


def test_a_missing_concept_row_is_not_a_write_side_judge(tables, seeded):
    """存在性不归写侧管（今天也不归，本批没动它）—— 它归审计期的 `verify.dangling_concept`。

    `draft/156` 的验收里写着"不存在的概念号 ⇒ 仍拒"。改前实测：照收（写侧的判据是
    形态 `require_id`，不是存在性）。本批刻意不新增这条判据：新增它会把"先写关系、后落
    概念行"的那些正路（秘书 / 抽取）连带拒掉，那是另一条口径变更，不属于本批。
    于是这一条钉两件事：写侧照旧收、审计期照旧点名 —— "存在性有人管"这句话是有落点的。
    """
    from agentflow.verify import verify_all

    made = tables.call("table.create", table="relations",
                       row=_relation_row(concept_ids=[A, "999999"]))
    assert made.ok, made.error
    rep = verify_all(seeded)
    codes = {getattr(i, "code", "") for i in rep.issues}
    assert "dangling_concept" in codes, sorted(codes)


# ============================================================ ③ 判据本体（不经工具）


def test_the_normalizer_itself_only_touches_declared_set_fields() -> None:
    """归一那一步的判据本身：只动声明为 `set` 的字段，`seq` 与非法形状一个字节不碰。

    为什么要有这一层：上面那些用例走的是工具，证明的是"这条链接上了"；这一条证明的是
    "那条链上搬东西的那一步只搬该搬的"（`ARRAY_FIELD_KINDS` 是唯一的声明面）。
    """
    # 两个集合字段：都改；返回值按 `ARRAY_FIELD_KINDS` 的声明序给出
    row: dict = {"concept_ids": [B, A], "supporting_lit_ids": ["000002", "000002"]}
    assert S.normalize_set_fields("relations", row) == ["concept_ids", "supporting_lit_ids"]
    assert row["concept_ids"] == [A, B] and row["supporting_lit_ids"] == ["000002"]
    # 序列字段（`statements.aliases` 是 seq）：原样留着，也不进读数
    seq_row: dict = {"aliases": ["b", "a"]}
    assert S.normalize_set_fields("statements", seq_row) == []
    assert seq_row["aliases"] == ["b", "a"]
    # 混类型：一个字节都不动（交给 `_set_problems` 的"元素不是字符串"那一档）
    mixed: dict = {"concept_ids": [A, 2]}
    assert S.normalize_set_fields("relations", mixed) == []
    assert mixed["concept_ids"] == [A, 2]
    # tuple 收成 list（Python 调用方），这也算"改动过"，如实记一笔
    tup: dict = {"concept_ids": (B, A)}
    assert S.normalize_set_fields("relations", tup) == ["concept_ids"]
    assert tup["concept_ids"] == [A, B]
    # 载荷不是对象 / 未知表：没有可归一的东西（不是异常，也不是"改了什么"）
    assert S.normalize_set_fields("relations", None) == []
    assert S.normalize_set_fields("没有这张表", {"concept_ids": [B, A]}) == []


# ============================================================ ④ 反真空


def test_negative_control_a_normalizer_that_never_sorts_turns_the_first_case_red(
        tables, seeded, monkeypatch: pytest.MonkeyPatch):
    """反真空：把归一步打桩成"恒不排序" ⇒ (a) 必须变红。

    打的是 `schema.sorted_unique`（归一步唯一的排序/去重实现）。它一失效，
    `['000004','000002']` 原样进 `_build_row` ⇒ 被 `_set_problems` 的"未升序去重"拒掉。
    没有这一条，上面那些断言证明的只是"今天恰好写进去了"，不证明"归一化真的在干活"。
    """
    monkeypatch.setattr(S, "sorted_unique", lambda values: list(values))
    res = tables.call("table.create", table="relations",
                      row=_relation_row(concept_ids=[B, A]))
    assert res.ok is False, res
    assert "未升序去重" in str(res.error), res.error
    assert _disk(seeded) == []

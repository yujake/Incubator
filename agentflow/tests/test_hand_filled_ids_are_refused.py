# -*- coding: utf-8 -*-
"""手填主键的受控拒绝（`draft/156` 的 D4）：编号该不该手填，写侧一句话说清。

## 修的是什么（真机已核）
B 按 `rel-` 前缀的直觉给关系行填了一个号：

    relations 行校验失败：relation_id 必须是 6 位十进制字符串（如 000000…），收到 'rel-000001'

那句话只说"位数不对"。模型据此只能猜"那我该填几位"，猜不到这一格根本不该它填。
同族的直觉还有 `stmt-1` / `p-1`（按表名缩写手填）、`p-000001` 填进 `request_id`
（前缀认错了表）。

⇒ 写侧认"带前缀的号"这个形态（`schema.looks_like_prefixed_id`），先于一切校验与兜底
路由把话说清：这一格由台账分配、不要手填、去掉它即可；前缀号只有过程记录那种
人工号才用，并点名这一张表的人工号长什么样。

## 哪些编号是自动分配的（这一条也有判据，不只是文案）
`schema.id_allocator_kind(table)` 是"主键由谁发号"的机器可读读数，覆盖 `TABLES` 里
全部 17 张表，只有两种取值，没有一张表的主键是外部给的：
  - `counter`（14 张）：`ID_COUNTERS` 的编号空间 ⇒ 六位十进制，如 `000000`；
  - `prefix`（3 张）：`PROCESS_ID_PREFIXES` 的过程记录号 ⇒ `<前缀>-号码`，
    `search_requests` 是 `r-`、`reprocess_requests` 是 `p-`、`tasks` 是 `t-`。
发号点只有一处（`tools/table_tools.py::_allocate_id`，它再分派到 `store.Tx.alloc_id`
或 `interactions.next_prefixed_id`）。这一条列在 `test_every_table_key_is_ledger_allocated`
里被遍历断言 —— 文案说"所有主键都由台账分配"，而这句话有东西在核。

## 不误伤什么（正控都在这个文件里）
- 不给主键 ⇒ 照常发号建行（`000000` / `r-000001` 两种形态都核）；
- 合法的人工号照收：`search_requests` 的 `r-000001`（过程记录人工号）、`relations`
  的 `000123`（六位裸号）；
- 空串 `stmt_id=""` 不是手填（"我不填，让台账发号"），照旧走兜底路由。

## 反真空
把"前缀检测"打桩成永假（`schema.looks_like_prefixed_id` 恒 False）⇒ 第一条判据必须变红。
"""
from __future__ import annotations

import pytest

from agentflow import schema as S
from agentflow.tools import table_tools
from agentflow.tools.base import ToolRegistry

from conftest import add_literature

#: 关系行要引用的两个概念号（升序形态）与一篇文献。
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
    """两条概念行 + 一篇文献（关系行的外键要指得着）。"""
    from agentflow import conceptrows as CR

    for cid, label in ((A, "群"), (B, "阿贝尔群")):
        with store.tx(*CR.tables_for_concept_write(), actor="test") as tx:
            CR.write_concept(tx, stmt_id=cid, label=label, definition="")
    add_literature(store, LIT, title="T", path=None, processed=True, dedup_key="doi:x")
    return store


def _relation_row(**over) -> dict:
    row = {"concept_ids": [A, B], "description": "描述", "lit_id": LIT, "quote": "q"}
    row.update(over)
    return row


# ============================================================ ① 受控拒绝（真机那两格）


def test_a_hand_filled_relation_id_is_refused_with_the_actionable_sentence(tables, seeded):
    """(a) `relation_id='rel-000001'` ⇒ 拒，且拒信说清"由台账分配 / 不要手填 / 去掉它即可"。

    改前红：改前拒信是 `relation_id 必须是 6 位十进制字符串（如 000000…），收到
    'rel-000001'` —— 只谈位数，模型读不出"这一格不该它填"（真机同一句连挡 3 次）。
    """
    res = tables.call("table.create", table="relations",
                      row=_relation_row(relation_id="rel-000001"))
    assert res.ok is False, res
    assert res.meta.get("kind") == "hand_filled_id", res.meta
    err = str(res.error)
    assert "不要手填" in err, err
    assert "去掉它即可" in err, err
    assert "relation_id" in err, err
    # 读数里也带着"是哪一格、收到什么"，不必从长句里捞
    assert res.meta.get("field") == "relation_id" and res.meta.get("got") == "rel-000001", res.meta
    assert seeded.rows("relations") == [], "被拒的行不许有半个字节落盘"


def test_the_refusal_comes_before_the_backstop_route(tables, seeded):
    """同一个判据在兜底表上也先说话：`stmt-1` 不会被"路由给秘书"静默改写。

    `statements` 的直写会转交秘书（`DIRECT_WRITE_ROUTES`），而秘书自己会发一个新号并
    把行落下 —— 那正好是"系统静默改掉我填的号"。所以手填判据必须排在路由之前：
    拒信要说"这一格不该你填"，而不是"系统替你办成了、号不是你写的那个"。
    """
    res = tables.call("table.create", table="statements", row={"stmt_id": "stmt-1"})
    assert res.ok is False, res
    assert res.meta.get("kind") == "hand_filled_id", res.meta
    assert "不要手填" in str(res.error), res.error
    assert len(seeded.rows("statements")) == 2, "手填被拒之后不许再落任何新行"


def test_a_wrong_process_prefix_names_the_right_one(tables):
    """前缀认错了表（`p-000001` 填进 `request_id`）⇒ 同样受控拒绝，并点名 `r`。"""
    res = tables.call("table.create", table="search_requests",
                      row={"request_id": "p-000001",
                           "timestamp": "2026-01-01T00:00:00+00:00",
                           "topic": "群", "mode": "broad"})
    assert res.ok is False, res
    assert res.meta.get("kind") == "hand_filled_id", res.meta
    assert "不要手填" in str(res.error) and "去掉它即可" in str(res.error), res.error
    assert "`r`" in str(res.error) and "p-000001" in str(res.error), res.error


# ============================================================ ② 正控：不误伤


def test_omitting_the_id_allocates_it(tables, seeded):
    """(b) 不传 `relation_id` ⇒ 台账发号，建行成功。

    改前同样是绿的 —— 这一条是正控：它防的是"受控拒绝"变成"凡是带 id 就拒"。
    """
    res = tables.call("table.create", table="relations", row=_relation_row())
    assert res.ok, res.error
    assert res.data == S.format_id(0), res.data
    assert seeded.rows("relations")[0]["relation_id"] == S.format_id(0)


def test_a_legal_manual_process_id_still_works(tables):
    """(c1) `search_requests` 的人工号 `r-000001` 是正路 ⇒ 照常写、号就是它。"""
    res = tables.call("table.create", table="search_requests",
                      row={"request_id": "r-000001",
                           "timestamp": "2026-01-01T00:00:00+00:00",
                           "topic": "群", "mode": "broad"})
    assert res.ok, res.error
    assert res.data == "r-000001", res.data


def test_a_legal_manual_six_digit_id_still_works(tables, seeded):
    """(c2) 六位裸号是合法的人工号 ⇒ 照收（判据是"带前缀"，不是"给了主键"）。"""
    res = tables.call("table.create", table="relations",
                      row=_relation_row(relation_id="000123"))
    assert res.ok, res.error
    assert res.data == "000123", res.data
    assert seeded.rows("relations")[0]["relation_id"] == "000123"


def test_an_empty_id_is_not_a_hand_filled_one(tables, seeded):
    """空串 = "我不填，让台账发号" ⇒ 这一条不拦，照常发号（不误伤）。

    为什么单独钉这一格：`tests/test_direct_write_is_routed_to_the_secretary.py` 里有一档
    显式传 `stmt_id=""`（它必须继续走到兜底路由）。判据在那一档上不许开口子。
    端到端只用"不进兜底路由"的表（`research_questions`）：秘书那条正路的完整链路由上面
    那个文件逐步钉着，本文件不重复铺一遍（那一路要造秘书，代价是一个用例 20 秒）。
    """
    assert table_tools._hand_typed_id_refusal(
        "statements", {"stmt_id": ""}, "stmt_id") is None
    res = tables.call("table.create", table="research_questions",
                      row={"question_id": "", "question": "群为什么可交换？",
                           "origin": "fixture", "priority": "high"})
    assert res.ok, res.error
    assert res.data == S.format_id(0), res.data


# ============================================================ ③ 清单判据：主键都由台账分配


def test_every_table_key_is_ledger_allocated() -> None:
    """全部 17 张表的主键都由台账分配，且恰好落在两种发号器之一（没有第三种）。

    这条把"哪些编号自动分配"从注释变成判据：文案（`table.create` 的描述与受控拒信）
    说的就是这句话，而它必须一直被核着 —— 将来有人加一张"主键由调用方给"的表，
    `id_allocator_kind` 会返回空串，这条当场红，而不是让文案静默变假。
    """
    assert len(S.TABLES) == 17, len(S.TABLES)        # 反真空：表数不是 0，也不是"以后再说"
    kinds = {t: S.id_allocator_kind(t) for t in S.TABLES}
    assert set(kinds.values()) == {"counter", "prefix"}, kinds
    # 两种发号器的成员必须与各自的声明面逐条相等（同一件事不许有第二份名单）
    counter = {t for t, k in kinds.items() if k == "counter"}
    prefix = {t for t, k in kinds.items() if k == "prefix"}
    assert {S.TABLES[t]["id_field"] for t in counter} == set(S.ID_COUNTERS.values())
    assert {S.TABLES[t]["id_kind"] for t in prefix} == set(S.PROCESS_ID_PREFIXES)
    # 每一格的形态也说得出：counter 是六位十进制，prefix 是"前缀-号码"
    assert S.id_allocator_kind("relations") == "counter"
    assert S.id_allocator_kind("search_requests") == "prefix"
    assert S.id_allocator_kind("没有这张表") == ""


# ============================================================ ④ 判据本体（不经工具）


@pytest.mark.parametrize("value, want", [
    ("rel-000001", True),      # 真机那一格（`draft/156`）
    ("stmt-1", True),          # 按表名缩写手填（位数都不对，也要认出来）
    ("p-1", True),
    ("r-000001", True),        # 过程记录的人工号也是"带前缀的号"（是否放行由表决定）
    ("000123", False),         # 六位裸号：合法的人工号，不是这一条要拦的
    ("0000", False),           # 旧四位裸号：同上
    ("", False),
    ("rel", False),            # 只有前缀、没有号码：不是"号"，交给形态判据
    (None, False),
    (12, False),
])
def test_the_prefix_predicate_at_its_own_level(value, want) -> None:
    """检测谓词本身（`schema.looks_like_prefixed_id`）：认形态，不认合法性。

    它刻意比 `is_valid_process_id` 宽（后者要求号码是当前宽度）：`stmt-1` 这种"更直觉
    的手填"正是真机上模型写出来的形态，而拒绝要认的是这个形态本身。
    """
    assert S.looks_like_prefixed_id(value) is want, (value, want)


# ============================================================ ⑤ 反真空


def test_negative_control_a_prefix_detector_that_is_always_false_turns_the_first_case_red(
        tables, seeded, monkeypatch: pytest.MonkeyPatch):
    """反真空：把前缀检测打桩成永假 ⇒ (a) 必须变红（退回改前那句只谈位数的拒信）。

    没有这一条，上面的断言证明的只是"这些输入今天恰好被拒了"，不证明"是这条判据在拒"。
    """
    monkeypatch.setattr(S, "looks_like_prefixed_id", lambda value: False)
    res = tables.call("table.create", table="relations",
                      row=_relation_row(relation_id="rel-000001"))
    assert res.ok is False, res
    assert res.meta.get("kind") != "hand_filled_id", res.meta
    assert res.meta.get("kind") == "validation", res.meta
    assert "必须" in str(res.error) and "6 位十进制" in str(res.error), res.error
    assert "不要手填" not in str(res.error), res.error

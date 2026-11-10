# -*- coding: utf-8 -*-
"""③ F 提示词 4.1 段：概念不许被算成"等级低"那一档（审计 §6-③）。

## 改前读数（`temp/_fix_concept_probe_before.json` 的 `3_f_prompt`）

同一份工作区里只有一条概念（`grade=not_applicable`），F 的 4.1 段读数是：

```
（台账里现在没有一条站到 pre_theorem 级及以上的在册命题 ⇒ 这一轮不许引 `stmt:`；
 要声明前提就把那一步写成 `assumption: true`；
 另有 1 条的等级低于 pre_theorem（conjecture / strong_conjecture 那一档）—— 引用它们会被受控拒绝）
```

那 1 条是 concept：它既不是 conjecture 也不是 strong_conjecture。成因是
`agent_f/manuscript.py::citable_statements` 的三档分流 —— `in pool` /
`elif not _DS.statement_grade(row): unknown` / `else: below`，而 `not_applicable`
是「非空真值」，于是概念掉进 `below`。读这句话的模型会得到"库里有 1 条低档命题，抬一抬
就能引"，而真相是"这条概念没有等级轴"。

## 改后口径

三档变四档：`below`（真等级、低于门槛）/ `unknown`（等级算不出来）/ `concept`
（`GRADE_NOT_APPLICABLE`）。概念单列一句，并且那句话明说"不是档位不够"：

```
…；另有 1 条概念（`kind=concept`，不参与可引等级：概念没有等级轴，不是“档位不够”）
```

## 四条判据（含一条反真空）

| 条 | 它钉什么 | 改前红在哪 |
|---|---|---|
| a | 只有概念 ⇒ 那一句里没有"等级低于"、并且单列"1 条概念（…不参与可引等级…）" | 改前说"另有 1 条的等级低于 pre_theorem" |
| b | 混合（1 条低档 conjecture + 1 条概念）⇒ "1 条的等级低于"与"1 条概念"两句各自成立（概念没有被并进那个计数） | 改前那个计数是 2 |
| c | 反真空：把 `_non_citable_bucket` 打桩成恒 `BUCKET_BELOW`（= 改前那个 `else` 分支）⇒ b 的红当场出现（计数变 2、概念那句消失） | 证明 b 的绿是这条分流带来的 |
| d | 三档不许折平：空串 ⇒ `unknown`、`not_applicable` ⇒ `concept`、真等级 ⇒ `below`，三个常量互不相同 | 折平会把"判不了"读成"档位不够"（同一个坑的另一半） |
| e | 概念不进清单（`lines` / `ids`）这一条不变 —— 改的是"怎么说"，不是"能不能引" | 改后不许把概念塞进可引清单 |

零真实模型调用：F 只调 `citable_statements()`（纯读，不派模型）；工作区全在 `tmp_path`。
"""
from __future__ import annotations

import pytest

from agentflow import evidencebits as EB
from agentflow.agent_b import AgentB
from agentflow.agent_f import AgentF
from agentflow.agent_f import manuscript as MF
from agentflow.extract import extract_text
from agentflow.store import Store

from conftest import add_literature, seed_statement_row, write_library_file

PAPER = ("For convenience, a set of vertices K will be said to be a red interconnected "
         "set if all segments joining pairs of vertices in K are colored red.")

CONCEPT = {
    "kind": "concept",
    "label": "红色互连集（red interconnected set）",
    "origin": "external_lit",
    "source_lit_id": "000000",
    "page_range": {"start": 1, "end": 1},
    "quote_mode": "verbatim",
    "quote_verified": True,
    "statement_full": (
        "定义（红色互连集，red interconnected set）。给定顶点集 V，把完全图的每条边恰好"
        "染成红、蓝两色之一：若顶点子集 K 中任意两点之间的线段全部为红色，则称 K 为"
        "红色互连集。"),
    "statement_text": "a set of vertices K is a red interconnected set if all segments "
                      "joining pairs of vertices in K are colored red.",
}

#: 一条真的低档命题（`conjecture`：有正文、没有签 ⇒ 等级低于门槛）。
#:
#: 用 `seed_statement_row` 直接铺行、不走登记动作：2026-11-05 的严格准入闸把"没有签的
#: 证明正文"整笔拒在登记入口上（这正是 `test_fake_proof_review.py` 里那条夹具的理由）——
#: 本条判据要的是一条「已经躺在盘上」的低档行，不是一次登记。
LOW = {
    "kind": "conjecture",
    "label": "红色互连集的存在性",
    "statement_full": "设完全图的边被红蓝二染色；则存在一个二元红色互连集。",
    "statement_text": "存在一个二元红色互连集。",
    "proof_text": ("证明：\n1. 取 K = {v1, v2}，染色给定后那条线段颜色唯一确定。\n"
                   "2. 若为红则 K 是红色互连集 ⇒ 存在。"),
    "quote_reason": "夹具：直接铺行（历史形态：无 V 签）",
}


def _prepared(store: Store) -> Store:
    write_library_file(store, "000000/a.txt", PAPER + "\n")
    add_literature(store, "000000", title="Combinatorial Relations and Chromatic Graphs",
                   path="000000/a.txt")
    return store


def _b(store: Store) -> AgentB:
    return AgentB(store, extractor=None, extract_text=extract_text,
                  config={"lease_seconds": 900, "max_attempts": 3})


def _prompt(store: Store) -> tuple[list[str], list[str], str]:
    f = AgentF(store, config={}, e=None, actor="agent-F")
    return f.citable_statements()


def _only_concept(store: Store) -> str:
    out = _b(store).register_statement(**CONCEPT)
    assert out.get("ok") is True, out
    return str(out.get("stmt_id") or "")


# ---------------------------------------------------------------- 尺子


def _assert_concept_is_not_counted_as_low_grade(note: str, *, concepts: int,
                                                below: int) -> None:
    """a/b 的尺子：概念单列一句，且不进"等级低于"那个计数。

    两件事缺一不可：

    ① "另有 N 条概念（…不参与可引等级…）"这一句在，并且它明说"不是档位不够" ——
       只说"另有 N 条概念"仍会被读成"低档的那些之一"；
    ② "等级低于 pre_theorem"那一句里的数字是 `below`（真等级不够的命题数），
       不是 `below + concepts`。改前那个数字把概念一起算了进去。
    """
    assert f"另有 {concepts} 条概念" in note, (
        f"概念没有被单列一句（注：改前它藏进“等级低”那一句里）：{note!r}")
    assert "不参与可引等级" in note, note
    assert "不是“档位不够”" in note or "不是\"档位不够\"" in note, (
        f"那一句没有点明“不是档位不够” ⇒ 仍会被读成“这条能用但等级不够”：{note!r}")
    if below:
        assert f"{below} 条的等级低于" in note, (
            f"真低档命题的计数应当是 {below}（概念不许并进去）：{note!r}")
    else:
        assert "等级低于" not in note, (
            f"只有概念时不该出现“等级低于”那一句：{note!r}")


# ================================================================ a 只有概念


def test_a_a_concept_only_ledger_does_not_say_low_grade(store: Store) -> None:
    """a：只有一条概念 ⇒ 提示词说的是"1 条概念（不参与可引等级）"，不是"1 条等级低"。

    改前读数：`另有 1 条的等级低于 pre_theorem（conjecture / strong_conjecture 那一档）
    —— 引用它们会被受控拒绝`（`temp/_fix_concept_probe_before.json`）。
    """
    _prepared(store)
    cid = _only_concept(store)
    lines, ids, note = _prompt(store)

    assert lines == [] and ids == [], (lines, ids)
    assert cid not in note, note
    _assert_concept_is_not_counted_as_low_grade(note, concepts=1, below=0)


# ================================================================ b 混合


def test_b_a_low_grade_proposition_and_a_concept_are_counted_separately(
        store: Store) -> None:
    """b：1 条低档 conjecture + 1 条概念 ⇒ 两句各自的计数都是 1（改前那个数字是 2）。

    这一条是这条判据的分辨率：只测"只有概念"时，把概念从 `below` 挪走与"把 `below`
    整句删掉"长得一样。两条同时在盘上，才能看出计数有没有把概念并进去。
    """
    _prepared(store)
    cid = _only_concept(store)
    low = seed_statement_row(store, **LOW)
    assert str(low["stmt_id"]) != cid, (low, cid)

    lines, ids, note = _prompt(store)

    # 两行都不够格 ⇒ 清单是空的（这一条判据不改"谁能引"）
    assert lines == [] and ids == [], (lines, ids)
    _assert_concept_is_not_counted_as_low_grade(note, concepts=1, below=1)
    assert "2 条的等级低于" not in note, (
        f"概念被并进“等级低”那个计数了（改前就是这个读数）：{note!r}")


# ================================================================ c 反真空


def test_c_negative_control_pushing_concepts_back_into_below_turns_it_red(
        store: Store, monkeypatch: pytest.MonkeyPatch) -> None:
    """c 反真空：把 `_non_citable_bucket` 打桩成恒 `BUCKET_BELOW`（= 改前那个 `else`）⇒ b 红。

    打桩的是分流判据本体，不是重写一份提示词：于是这句话走的正是改前那条
    "两档分流、`not_applicable` 是非空真值 ⇒ 掉进 below"的路。
    """
    _prepared(store)
    _only_concept(store)
    seed_statement_row(store, **LOW)

    monkeypatch.setattr(MF, "_non_citable_bucket", lambda grade: MF.BUCKET_BELOW)
    lines, ids, note = _prompt(store)

    assert lines == [] and ids == [], (lines, ids)
    assert "2 条的等级低于" in note, (
        f"打桩之后读数没回到改前那一句 ⇒ c 证明不了 b 的红：{note!r}")
    with pytest.raises(AssertionError):
        _assert_concept_is_not_counted_as_low_grade(note, concepts=1, below=1)


# ================================================================ d 三档不许折平


def test_d_the_three_buckets_are_distinct() -> None:
    """d：空串 ⇒ `unknown`、`not_applicable` ⇒ `concept`、真等级 ⇒ `below`。

    "判不了"与"档位不够"与"没有等级轴"是三件事。改前只有两个桶（`unknown` / `below`），
    于是第三件被折进第二件 —— 这一条把三个桶的边界钉在判据本体上。

    反真空（第 ④ 半）：把 `GRADE_NOT_APPLICABLE` 改回"当成一个真等级"（= 恒 `below`）
    这一条立刻红（`concept` 那一比失效）；这里用"三个常量互不相同"把折平的另一种
    形态（两个桶同名）也挡掉。
    """
    assert MF._non_citable_bucket("") == MF.BUCKET_UNKNOWN
    assert MF._non_citable_bucket(None) == MF.BUCKET_UNKNOWN
    assert MF._non_citable_bucket(EB.GRADE_NOT_APPLICABLE) == MF.BUCKET_CONCEPT
    assert MF._non_citable_bucket("conjecture") == MF.BUCKET_BELOW
    assert MF._non_citable_bucket("strong_conjecture") == MF.BUCKET_BELOW
    assert len({MF.BUCKET_BELOW, MF.BUCKET_UNKNOWN, MF.BUCKET_CONCEPT}) == 3
    # 反向：`not_applicable` 不是 `GRADES` 里的一档（否则它就该按"档位不够"读）
    assert EB.GRADE_NOT_APPLICABLE not in EB.GRADES


# ================================================================ e 清单那一侧不变


def test_e_the_concept_still_is_not_listed_as_citable(store: Store) -> None:
    """e：概念仍然不进 `lines` / `ids` —— 这一改只改"怎么说"，不改"能不能引"。

    可引池的判据只有一处（`depsection.citable_pool` = 在册 ∧ 等级 ≥ pre_theorem），
    本条判据不许顺手把概念放进去（那会让模型照着引一条注定被拒的）。
    """
    _prepared(store)
    cid = _only_concept(store)
    lines, ids, _note = _prompt(store)
    assert ids == [] and lines == [], (lines, ids)
    assert all(cid not in line for line in lines), lines
    # 概念行的等级仍是"不适用"（池子按等级筛 ⇒ 它进不去，理由是结构性的）
    row = dict(next(r for r in store.rows("statements")
                    if str(r["stmt_id"]) == cid))
    assert str((row.get("bits") or {}).get("grade")) == EB.GRADE_NOT_APPLICABLE, row

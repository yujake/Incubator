# -*- coding: utf-8 -*-
"""判据：同一个概念只许一行（D2，真机 mp3-r2 的 000003 / 000004）。

## 真机证据（`projects/mp3-r2/data/statements.json`，只读复算，本文件不碰那个工作区）

```
000003 | concept | label = 'finite-dimensional Lie algebra'
000004 | concept | label = 'finite-dimensional Lie algebra'
```

两行的 `statement_full` 是同一句定义（"概念（有限维 Lie 代数）：设 K 为特征 0 的域 …"），
只差一句措辞（"本概念在本文中的作用是作为…" 与 "在本文中它的作用是…"）。于是同一个概念
在台账上落了两行，而下游按概念读的每一处（依赖图的术语、报告的概念表）都会各自看到两条。

## 为什么改前是红的

命题同一性的判据是"条件 ⇒ 结论 一致"，而 `kind=concept` 的行只有一句定义 —— 它没有条件
与结论，命题键与词面相似度在它上面等于失效（两条把同一个术语定义了两遍的行因此判成
"不同"）。旧口径在概念这一档上只有一条路：`statement_full` 规范化后整段相同才算重复
（`_record_statement_tx` 里那条老查重），而措辞差一句就绕过它。

## 这一份钉的三条（外加两条护栏）

| 条 | 它要证明的事 | 改前为什么是红的 |
|---|---|---|
| a | 「finite-dimensional Lie algebra」第二次登记 ⇒ 不新建行、返回既有 `stmt_id` | 改前没有概念这一档：真机落了两行 000003 / 000004 |
| a2 | 同一个定义项换个标签登记（术语那一半）⇒ 仍判同一个概念 | 同上；这一条钉的是"定义项"不只是"标签字符串" |
| b | 两个不同的概念（有限维李代数 / 幂零李代数）⇒ 必须各自新建（正控，防过度合并） | 这一条改前改后都该绿：它是"别并过头"的负控 |
| c | 反真空：把概念判据打桩成恒 different ⇒ a 必红 | 这一条证明 a 的绿是那条判据给的 |
| 护栏 | 概念这一档不发模型调用（确定性优先） | 改前概念连判定入口都进不去；这一条防"顺手把它交给模型" |

## 边界

全部 tmp 工作区、零真实模型调用（需要判定的那一格用有缝的秘书装一只计数探针，读数是
"一次调用都没发"）。不读写 `projects/`。
"""
from __future__ import annotations

import pathlib
import sys

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agentflow import propositionkey as PK
from agentflow import schema as S
from agentflow import secretary as SEC
from agentflow.secretary import Secretary
from agentflow.store import Store

#: 真机那两行的 label 逐字。
REAL_LABEL = "finite-dimensional Lie algebra"

#: 真机那两行的 `statement_full` 开头（原文的后半句略有差别，这里保留那个差别）。
REAL_DEF_1 = ("概念（有限维 Lie 代数）：设 K 为特征 0 的域，g 为 K 上的 Lie 代数。"
              "称 g 有限维，若 dim_K g < ∞。本概念在本文中的作用是作为"
              "「U(g) 为 Noetherian」的充分条件。")
REAL_DEF_2 = ("概念（有限维 Lie 代数）：设 K 为特征 0 的域，g 为 K 上的 Lie 代数。"
              "称 g 有限维，若 dim_K g < ∞。在本文中它的作用是"
              "「U(g) 为 Noetherian」的充分条件。")

#: 两个不同的概念（正控：它们必须各自一行）。
OTHER_LABEL = "幂零李代数"
OTHER_DEF = "概念（幂零李代数）：称 g 幂零，若降中心列在有限步终止。"


class _Seam:
    """一只只数调用次数的假模型缝（概念这一档一次都不该碰它）。"""

    class _Call:
        def __init__(self) -> None:
            self.ok, self.problem, self.detail = True, "", ""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def ask_json(self, prompt, **kw):
        self.calls.append(str(kw.get("note") or ""))
        return {}, self._Call()


def _ws(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _concept(sec: Secretary, label: str, full: str) -> dict:
    """登记一条概念（自产概念要走 `self_authored` 那一档，见 `conceptrows`）。"""
    return sec.record_statement(
        {"statement_full": full, "label": label, "statement_text": label,
         "kind": "concept", "origin": "own_result", "self_authored": True,
         "doc_id": S.format_id(0)}, role="B")


def _rows(st: Store) -> list[dict]:
    return [dict(r) for r in st.rows("statements")]


def _two(st: Store, seam: _Seam | None = None) -> tuple[dict, dict]:
    """同一条概念登记两次（正文差一句措辞）⇒ `(第一条, 第二条)` 的返回值。"""
    sec = Secretary("B", root=st.root, store=st, seam=seam,
                    enable_model=bool(seam is not None))
    return _concept(sec, REAL_LABEL, REAL_DEF_1), _concept(sec, REAL_LABEL, REAL_DEF_2)


# ============================================================ a) 同一概念不落第二行


def test_a_the_same_concept_is_not_registered_twice(tmp_path: pathlib.Path) -> None:
    """a：同一个概念第二次登记 ⇒ 不新建行、返回既有 `stmt_id`（并给出确定性依据）。

    改前红：那一刻概念行根本不进同一性判定，重复登记靠"整段正文规范化后相同"兜，
    而真机那两条只差一句措辞 ⇒ 两行。见
    `test_before_this_feature_exists_the_concept_lands_twice`。
    """
    st = _ws(tmp_path)
    first, second = _two(st)
    assert first.get("checked") is True and first.get("created") is True, first
    sid = str(first.get("stmt_id") or "")
    assert sid, first
    rows = _rows(st)
    assert len(rows) == 1, [r.get("label") for r in rows]
    # 第二笔：不新建、指向既有那一行、依据是定义项（确定性）。
    assert second.get("checked") is True, second
    assert second.get("created") is False and second.get("duplicate") is True, second
    assert str(second.get("stmt_id")) == sid, second
    assert second.get("matched_by") == PK.BASIS_CONCEPT_LABEL, second
    assert second.get("proposition_state") == PK.STATE_SAME, second
    assert "同一个概念已在册" in str(second.get("reason") or ""), second.get("reason")
    # 在册那一行的标签与定义都不在这一笔里被静默改写。
    (row,) = _rows(st)
    assert str(row.get("label")) == REAL_LABEL, row.get("label")
    assert str(row.get("statement_full")) == REAL_DEF_1, row.get("statement_full")


def test_a2_the_same_defined_term_under_another_label_is_one_concept(
        tmp_path: pathlib.Path) -> None:
    """a2：标签不同而正文里被定义的术语相同 ⇒ 仍是同一个概念（定义项那一半）。

    这一条钉的是判据的另一半：真机里同一个概念被写成中文标签与英文标签的各有一批，
    只按标签字符串比会漏掉它们，而正文里的「概念（有限维 Lie 代数）」是同一个术语。
    """
    st = _ws(tmp_path)
    sec = Secretary("B", root=st.root, store=st)
    first = _concept(sec, REAL_LABEL, REAL_DEF_1)
    second = _concept(sec, "有限维 Lie 代数", REAL_DEF_2)
    assert first.get("checked") is True and second.get("checked") is True, (first, second)
    assert len(_rows(st)) == 1, [r.get("label") for r in _rows(st)]
    assert second.get("duplicate") is True, second
    assert second.get("matched_by") == PK.BASIS_CONCEPT_TERM, second
    assert str(second.get("stmt_id")) == str(first.get("stmt_id")), (second, first)


# ============================================================ b) 正控：不同概念各自一行


def test_b_two_different_concepts_still_get_their_own_rows(tmp_path: pathlib.Path) -> None:
    """b（正控）：两个不同的概念必须各自新建 —— 过度合并会让一条真概念在台账上消失。

    三组都验：`有限维李代数` vs `幂零李代数`（两个真正的定义项不同）、以及两条只写着
    "概念"的行（通用词不算定义项：拿它当键会把所有没命名的概念并成一条）。
    """
    assert PK.same_concept("有限维李代数", "概念（有限维李代数）：dim < ∞。",
                           OTHER_LABEL, OTHER_DEF)["state"] == PK.STATE_DIFFERENT
    st = _ws(tmp_path)
    sec = Secretary("B", root=st.root, store=st)
    a = _concept(sec, "有限维李代数", "概念（有限维李代数）：dim_K g < ∞。")
    b = _concept(sec, OTHER_LABEL, OTHER_DEF)
    assert a.get("created") is True and b.get("created") is True, (a, b)
    assert str(a.get("stmt_id")) != str(b.get("stmt_id")), (a, b)
    assert len(_rows(st)) == 2, [r.get("label") for r in _rows(st)]
    # 通用词那一档：两条都只写"概念" ⇒ 不是同一个概念（定义项抽不出来就不许猜）。
    c = _concept(sec, "概念", "第一条：设 X 是一个集合。")
    d = _concept(sec, "概念", "第二条：设 Y 是一个拓扑空间。")
    assert c.get("created") is True and d.get("created") is True, (c, d)
    assert len(_rows(st)) == 4, [r.get("label") for r in _rows(st)]
    assert PK.concept_keys("概念", "") == {"label": "", "term": ""}


# ============================================================ 护栏：不发模型调用


def test_the_concept_criterion_costs_no_model_call(tmp_path: pathlib.Path) -> None:
    """护栏：概念这一档先走确定性判据，一次模型调用都不发。

    为什么这算一条判据而不是一条性能读数：`adjudicate_proposition` 的判词表是
    "条件 ⇒ 结论"，概念没有那一组 —— 把它交给模型既判不出什么，又会给真机上的上千条
    概念行各买一次调用（mp3 一个工作区就 1143 条）。所以"这一格没花钱"必须是可读的。
    """
    st = _ws(tmp_path)
    seam = _Seam()
    first, second = _two(st, seam)
    assert first.get("checked") is True and second.get("checked") is True, (first, second)
    assert seam.calls == [], seam.calls
    assert len(_rows(st)) == 1, [r.get("label") for r in _rows(st)]
    # 判定入口如实说"概念不进命题那一档"，而不是假装判过。
    adj = dict(first.get("adjudication") or {})
    assert adj.get("checked") is False, adj
    assert "不是命题" in str(adj.get("reason") or ""), adj
    assert second.get("matched_by") == PK.BASIS_CONCEPT_LABEL, second


# ============================================================ c) 反真空


def test_c_stubbing_the_criterion_to_different_turns_a_red(tmp_path: pathlib.Path,
                                                          monkeypatch) -> None:
    """c（反真空）：把概念判据打桩成恒 different ⇒ a 必红（真机形态：两行）。

    打桩的是判据本体（`propositionkey.same_concept`），不是另写一份假代码：它证明 a 的绿
    是"定义项相同"这条判据给的，而不是别的什么顺手拦住了第二笔。
    """
    def _always_different(*a, **k):
        return {"state": PK.STATE_DIFFERENT, "basis": "", "key_a": "", "key_b": "",
                "label_key_a": "", "label_key_b": "", "term_key_a": "", "term_key_b": "",
                "reason": "打桩：恒判 different"}

    monkeypatch.setattr(PK, "same_concept", _always_different)
    st = _ws(tmp_path)
    first, second = _two(st)
    assert first.get("created") is True and second.get("created") is True, (first, second)
    rows = _rows(st)
    assert len(rows) == 2, [r.get("label") for r in rows]
    assert [str(r.get("label")) for r in rows] == [REAL_LABEL, REAL_LABEL], rows
    assert second.get("duplicate") is not True, second


# ============================================================ 改前红


def test_before_this_feature_exists_the_concept_lands_twice(tmp_path: pathlib.Path,
                                                            monkeypatch) -> None:
    """改前红：把概念那一档摘掉（= 改前的形态）⇒ 真机那两行重现。

    `_merge_into_concept` 就是这一笔新加的概念同一性落点：把它打桩成恒 `None`，
    等价于改前"概念行不进同一性判定"那一支 —— 两笔各建一行，正是 mp3-r2 的
    000003 / 000004。
    """
    monkeypatch.setattr(Secretary, "_merge_into_concept",
                        lambda self, *a, **k: None)
    st = _ws(tmp_path)
    first, second = _two(st)
    assert first.get("created") is True and second.get("created") is True, (first, second)
    rows = _rows(st)
    assert len(rows) == 2, [r.get("label") for r in rows]
    assert [str(r.get("label")) for r in rows] == [REAL_LABEL, REAL_LABEL], rows
    assert [str(r.get("kind")) for r in rows] == ["concept", "concept"], rows


# ============================================================ 直接判据（纯函数）


def test_the_pure_criterion_is_three_state(tmp_path: pathlib.Path) -> None:
    """判据本身的三态：same / different / unknown 各一条（unknown 不许折成 different）。"""
    same = PK.same_concept(REAL_LABEL, REAL_DEF_1, REAL_LABEL, REAL_DEF_2)
    assert same["state"] == PK.STATE_SAME and same["basis"] == PK.BASIS_CONCEPT_LABEL, same
    diff = PK.same_concept(REAL_LABEL, REAL_DEF_1, OTHER_LABEL, OTHER_DEF)
    assert diff["state"] == PK.STATE_DIFFERENT, diff
    unknown = PK.same_concept("", "", "", "")
    assert unknown["state"] == PK.STATE_UNKNOWN, unknown
    assert "判不了" in str(unknown.get("reason") or ""), unknown
    # 规范化那一层：标点 / 空白 / 连字符的两种排版是同一个定义项。
    assert PK.concept_keys("finite-dimensional Lie algebra", "")["label"] == (
        PK.concept_keys("Finite Dimensional Lie-Algebra", "")["label"])
    assert PK.concept_keys("有限维 Lie 代数", "")["label"] == (
        PK.concept_keys("有限维Lie代数", "")["label"])


def test_unknown_concepts_are_registered_but_leave_a_reading(tmp_path: pathlib.Path) -> None:
    """判不了的那一档：照旧新建（不并），但读数必须说清"判不了"而不是"判过了、不同"。"""
    st = _ws(tmp_path)
    sec = Secretary("B", root=st.root, store=st)
    # 两条都只有一句很短的正文、标签是空的：定义项抽不出来 ⇒ unknown。
    first = sec.record_statement({"statement_full": "设 X 是一个集合。", "label": "",
                                  "kind": "concept", "origin": "own_result",
                                  "self_authored": True, "doc_id": S.format_id(0)}, role="B")
    assert first.get("created") is True, first
    assert first.get("proposition_state") == PK.STATE_UNKNOWN, first
    assert "判不了" in str(first.get("proposition_reason") or ""), first

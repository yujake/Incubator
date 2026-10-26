# -*- coding: utf-8 -*-
"""判据：派活台账里的内部工作名不许当定理名（D1，真机 mp3-r2 暴露）。

## 真机证据（`projects/mp3-r2/data/statements.json`，只读复算，本文件不碰那个工作区）

```
000000 | lemma | label = 'F 攻坚 000000 子目标 S2'
000001 | lemma | label = 'F 攻坚 000000 子目标 S2'
```

两行的 `statement_full` 是同一条数学命题（"逆命题：dim_k g = n < ∞ ⇒ U(g) 左右诺特 …"）。
于是同一份内容在台账上看起来是两条不同的命题，而"哪一条是哪条定理"在名字上无从读起。

## 为什么改前是红的

洗名那一步只洗"路线 / 自证草稿 / 要 V 审签"那一类（`secretary._judge_system` 的
`proposition_identity` 那一格里 canonical_name 那一句，以及 `label_washed` 那条路）——
内部工作名不在那一类里，于是原样落了盘。改前的形态可以精确复现：把
`secretary.wash_working_name` 打桩成恒 `None`（那正是改前"没有这一道确定性洗名"）。

## 这一份钉的三条（外加两条护栏）

| 条 | 它要证明的事 | 改前为什么是红的 |
|---|---|---|
| a | 真机那两个 label 喂进去 ⇒ 洗掉，落盘的 label 不再含「攻坚 / 子目标 Sx」，读数里给「原标签 → 洗过的名字」 | 改前没有这一道洗名：label 原样落盘 |
| a2 | 洗掉之后有东西可念（不许洗成空）：正文里抽一句 / 抽不出就 `<kind> 待命名（stmt:NNNNNN）` 并点名"原名不可用" | 改前不洗，所以这一档根本不存在 |
| b | 合法定理名（「有限维 ⇒ Noetherian」这类）一个字节不改（正控，防误洗） | 这一条改前改后都该绿：它是"别洗过头"的负控 |
| c | 反真空：把内部工作名词表清空 ⇒ a 必红（真机那两个 label 原样保留） | 这一条证明 a 的绿是那张表给的，不是巧合 |
| 护栏 | 路线那一类（`Sylow 三定理（路线一：…）`）不归本判据管：确定性洗名见括号不配对就整条不动 | 两种洗名各管各的，这一条防它们互相拆台 |

## 边界

全部 tmp 工作区、零真实模型调用（需要判定的那几条用没有缝的秘书：`checked=False`，
但确定性洗名照样跑）。不读写 `projects/`。
"""
from __future__ import annotations

import pathlib
import sys

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agentflow import schema as S
from agentflow import secretary as SEC
from agentflow.agent_b import AgentB
from agentflow.secretary import Secretary
from agentflow.store import Store

#: 真机那两行的 label 逐字（`000000` 与 `000001` 是同一个字符串）。
REAL_LABEL = "F 攻坚 000000 子目标 S2"

#: 真机那一行的 `statement_full` 开头两句（原文很长，这里只留判据用得上的那一段开头）。
REAL_FULL = ("逆命题：dim_k g = n < ∞ ⇒ U(g) 左右诺特。"
             "gr U(g) = k[x_1..x_n] 诺特（Hilbert 基定理）。"
             "滤环引理：设 A 为滤环、gr A 诺特，则 A 诺特。")

#: 合法定理名（正控）：这些一个字节都不许改。
CLEAN_NAMES = (
    "有限维 ⇒ Noetherian",
    "Witt 代数的泛包络代数非 Noetherian",
    "单 Z^n-分次 Lie 代数：U(g) Noetherian ⇒ 有限维",
    "finite-dimensional Lie algebra",
)

#: 路线那一类（归模型洗名）：确定性洗名必须整条不动它，否则两种洗名会互相拆台
#: （实测过的坏形态：把括号里的"自证草稿"删掉，剩下一只没配对的括号）。
ROUTE_LABEL = "Sylow 三定理（路线一：类方程/强归纳 + 共轭作用，自证草稿，待 V 审签）"

#: "同一条命题的两种写法"（`proposition_key` 相同）：并第二份证明那一支要用它。
FULL_A = "设 G 是 3-正则群；则弦长函数不是常值。"
FULL_A_KEY = "假设 G 为 3-正则群，于是弦长函数不是常值。"
PROOF = ("证明：把弦长函数记为 f，由定义直接计算每个顶点的邻域大小，弦长只依赖"
         "邻域结构，故 f 在正则性下取常值，与假设矛盾。")


def _ws(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _own(full: str, label: str) -> dict:
    """自产命题的必填件（与 `test_one_theorem_many_proofs…` 同一套；首登按猜想）。"""
    return {"statement_full": full, "statement_text": full[:24], "label": label,
            "origin": "own_result", "kind": "conjecture",
            "doc_id": S.format_id(0), "quote_reason": "我方自产命题，没有外部引文要比对"}


def _agent(st: Store) -> AgentB:
    """B 的真实现 + 一名没有缝的秘书（零模型调用；确定性洗名不依赖模型）。"""
    sec = Secretary("B", root=st.root, store=st)
    return AgentB(st, extractor=None, extract_text=None, config={}, secretary=sec)


def _labels(st: Store) -> list[str]:
    return [str(r.get("label") or "") for r in st.rows("statements")]


# ============================================================ a) 真机那两个 label 被洗掉


def test_a_the_real_mp3_work_name_never_becomes_the_theorem_name(
        tmp_path: pathlib.Path) -> None:
    """a：真机 label「F 攻坚 000000 子目标 S2」进去 ⇒ 落盘的 label 不再是工作名。

    改前红：没有这一道确定性洗名（打桩成恒 `None` 即复现改前），label 原样落盘 ——
    见 `test_before_this_feature_exists_the_work_name_lands_verbatim`。
    """
    st = _ws(tmp_path)
    got = _agent(st).register_statement(**_own(REAL_FULL, REAL_LABEL), proof_text="")
    assert got.get("ok") is True, got
    rows = [dict(r) for r in st.rows("statements")]
    assert len(rows) == 1, rows
    label = str(rows[0].get("label") or "")
    assert label != REAL_LABEL, label
    for needle in ("攻坚", "子目标"):
        assert needle not in label, label
    # 洗掉之后有东西可念：从正文里抽的第一句命题陈述（不是空、不是编号、不是工作名）。
    assert label.startswith("逆命题"), label
    assert label == SEC.wash_working_name(REAL_LABEL, statement_full=REAL_FULL,
                                         kind="lemma")["to"], label
    # 读数：原标签 → 洗过的名字 + 触发了哪一类（静默改名是不许的）。
    washed = dict(got.get("label_washed") or {})
    assert washed.get("from") == REAL_LABEL, washed
    assert washed.get("to") == label, washed
    assert str(washed.get("class") or "").startswith(SEC.LABEL_WASH_WORKING), washed
    assert str(washed.get("why") or "").strip(), washed
    assert got.get("canonical_name") == label, got.get("canonical_name")


def test_a2_the_washed_name_is_never_empty(tmp_path: pathlib.Path) -> None:
    """a2：洗掉之后必须有东西可念 —— 三级兜底逐级钉住（不许洗成空）。"""
    # 第一级：删掉工作名之后还剩能念的一截。
    got = SEC.wash_working_name("待推进：Noether 环", kind="lemma")
    assert got and got["to"] == "Noether 环", got
    # 第二级：整条都是工作名 ⇒ 从正文里抽；正文也没有 ⇒ 「<kind> 待命名（stmt:…）」。
    no_body = SEC.wash_working_name(REAL_LABEL, kind="lemma", stmt_id="000007")
    assert no_body and no_body["to"] == "lemma 待命名（stmt:000007）", no_body
    assert "原名不可用" in str(no_body.get("why") or ""), no_body
    # 第三级：正文本身也是工作名 ⇒ 同样落成待命名，并点名"原名不可用"。
    body_is_work_name = SEC.wash_working_name(REAL_LABEL, statement_full="F 攻坚 000001 子目标 S3",
                                              kind="lemma", stmt_id="000008")
    assert body_is_work_name and body_is_work_name["to"] == "lemma 待命名（stmt:000008）", (
        body_is_work_name)
    assert "原名不可用" in str(body_is_work_name.get("why") or ""), body_is_work_name
    # 概念行优先用「概念（X）」里那个 X 当名字（那本来就是它的名字）。
    concept = SEC.wash_working_name(
        REAL_LABEL, statement_full="概念（有限维 Lie 代数）：设 K 为特征 0 的域。",
        kind="concept", stmt_id="000009")
    assert concept and concept["to"] == "有限维 Lie 代数", concept


# ============================================================ b) 正控：合法定理名不改


def test_b_legitimate_theorem_names_are_not_touched_at_all(
        tmp_path: pathlib.Path) -> None:
    """b（正控）：合法定理名一个字节都不改 —— 判据直接比 utf-8 字节。

    这一条是"防误洗"的那一半：洗名的代价是静默改名，而一个洗过头的判据会把
    「有限维 ⇒ Noetherian」这种干净名字也改掉，读的人连"它原来叫什么"都看不到。
    """
    for name in CLEAN_NAMES:
        assert SEC.wash_working_name(name, statement_full=REAL_FULL, kind="lemma") is None, name
    st = _ws(tmp_path)
    b = _agent(st)
    for i, name in enumerate(CLEAN_NAMES):
        full = f"{name}。设 H 是第 {i} 个有限群；则 H 的阶有限。"
        got = b.register_statement(**_own(full, name), proof_text="")
        assert got.get("ok") is True, got
        row = next(r for r in st.rows("statements")
                   if str(r.get("stmt_id")) == str(got.get("stmt_id")))
        assert str(row.get("label") or "").encode("utf-8") == name.encode("utf-8"), (
            row.get("label"), name)
        assert got.get("label_washed") in ({}, None), got.get("label_washed")


def test_b2_the_route_class_is_left_to_the_model_wash() -> None:
    """b2（护栏）：路线那一类归模型洗名，确定性洗名整条不动它。

    为什么必须有这一条：两种洗名都盯着 label。实测过的坏形态是确定性那一把把括号里的
    「自证草稿」删掉，剩下一只没配对的括号（`Sylow 三定理（路线一：类方程`）—— 那比
    不洗更坏，因为它把一段路线信息撕成了半句。
    """
    assert SEC.wash_working_name(ROUTE_LABEL) is None
    assert SEC.wash_working_name("Sylow 三定理（路线一：类方程，草稿）") is None


# ============================================================ c) 反真空：清空词表 ⇒ a 红


def test_c_emptying_the_rule_table_turns_a_red(tmp_path: pathlib.Path,
                                               monkeypatch) -> None:
    """c（反真空）：把内部工作名词表清空 ⇒ a 必红（真机那两个 label 原样保留）。

    这一条证明 a 的绿是那张表给的：表空了，判据就一条都不命中，落盘的 label 回到
    改前那个字符串。没有这一条，"洗掉了"可能只是巧合（例如别的规则顺手改了它）。
    """
    assert SEC.wash_working_name(REAL_LABEL, statement_full=REAL_FULL, kind="lemma") is not None
    monkeypatch.setattr(SEC, "LABEL_WORKING_NAME_RULES", ())
    assert SEC.wash_working_name(REAL_LABEL, statement_full=REAL_FULL, kind="lemma") is None
    st = _ws(tmp_path)
    got = _agent(st).register_statement(**_own(REAL_FULL, REAL_LABEL), proof_text="")
    assert got.get("ok") is True, got
    assert _labels(st) == [REAL_LABEL], _labels(st)
    assert got.get("label_washed") in ({}, None), got.get("label_washed")


# ============================================================ 改前红


def test_the_on_record_work_name_is_repaired_when_a_proof_merges_in(
        tmp_path: pathlib.Path, monkeypatch) -> None:
    """护栏：已经带着工作名落了盘的那一行，下一份证明并进来时名字被修好。

    为什么要有这一条：真机 mp3-r2 那两行是在修复之前落的盘 —— 只修"新建"那一支的话，
    台账里已有的工作名要等人手工去改。这一条把"修名那一半"也钉住：并第 N 份证明时，
    在册那一行的 label 若还是工作名就一并洗掉，读数里给原标签与它落在哪一行。
    """
    st = _ws(tmp_path)
    # 第一笔：把确定性洗名打桩成恒 None，精确复现"改前落的那一行"。
    monkeypatch.setattr(SEC, "wash_working_name", lambda *a, **k: None)
    first = _agent(st).register_statement(**_own(FULL_A, REAL_LABEL), proof_text="")
    assert first.get("ok") is True, first
    assert _labels(st) == [REAL_LABEL], _labels(st)
    monkeypatch.undo()
    # 第二笔：同一条命题的另一种写法 + 一份证明 ⇒ 并进去，顺手修名。
    second = _agent(st).register_statement(**_own(FULL_A_KEY, "另一条写法"), proof_text=PROOF)
    assert second.get("ok") is True, second
    assert second.get("merged") is True, second
    (row,) = [dict(r) for r in st.rows("statements")]
    label = str(row.get("label") or "")
    assert label != REAL_LABEL, label
    assert "攻坚" not in label and "子目标" not in label, label
    washed = dict(second.get("label_washed") or {})
    assert washed.get("from") == REAL_LABEL, washed
    assert washed.get("to") == label, washed
    assert washed.get("stmt_id") == str(first.get("stmt_id")), washed


def test_before_this_feature_exists_the_work_name_lands_verbatim(
        tmp_path: pathlib.Path, monkeypatch) -> None:
    """改前红：把确定性洗名打桩成恒 `None`（= 改前没有这一道）⇒ a 当场变红。

    这不是另写一份假代码：`wash_working_name` 就是这一笔新加的确定性洗名，把它退回
    `None` 精确等于改前的形态（那时 label 只经过模型那一趟，而模型没接上就原样落盘）。
    """
    monkeypatch.setattr(SEC, "wash_working_name", lambda *a, **k: None)
    st = _ws(tmp_path)
    got = _agent(st).register_statement(**_own(REAL_FULL, REAL_LABEL), proof_text="")
    assert got.get("ok") is True, got
    assert _labels(st) == [REAL_LABEL], _labels(st)
    assert got.get("label_washed") in ({}, None), got.get("label_washed")

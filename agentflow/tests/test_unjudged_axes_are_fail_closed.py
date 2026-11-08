# -*- coding: utf-8 -*-
"""判据：概念同一性 / 同种证明两轴 —— 判不了 = 没判成，调用方 fail-closed。

业主 2026-11-08 逐字：「没有判不了」。命题同一性那一轴已在 b2efe2a1 收成两档；
这一份钉的是另外两轴（`propositionkey.same_concept` / `propositionkey.same_kind_proof`）：

| 条 | 它要证明的事 |
|---|---|
| a | 短证明不按字数预判死（照样判）；"没有可比的文本"才 `checked=False` / `state=""` |
| b | 概念同一性轴判不了 ⇒ `checked=False` + `state=""` |
| c | 调用点：判定面没给出可用结论 ⇒ 整笔受控拒 `proof_kind_unjudged`、不新增证明号 |
| d | 调用点：概念同一性判不了 ⇒ 整笔受控拒 `concept_identity_unjudged`、不新建行 |
| e | 反真空：谁把"没判成"填成 different（`checked=True`）⇒ a / b 当场红 |
| f | 正控：判得了的 same / different 照旧（这两轴不是"一律拒"） |

## 为什么不能"没判成当不同"

- 同种证明：折成 different 就是"新增一个证明号"，同一种证法被并列记录 —— 真机担心
  的正是这个形态。**但"短"本身不是没判成**：2026-11-08 主笔裁定删掉"内容单元 <
  `MIN_CONTENT_UNITS` ⇒ unknown"这条机械预判（短证明也判得出两种证法）；这一档只剩
  "没有可比的文本"。
- 概念同一性：两侧都抽不出定义项（标签空、正文不是一句定义）时折成 different，
  同一个概念就照旧落第二行 —— mp3-r2 的 `000003` / `000004` 正是这么来的。

## 边界

全部 tmp 工作区、零真实模型调用（概念这一档确定性；同种证明那一档的 V 签前提由
`signed_v_handoffs` 夹具造出，判据本体一个字都没动）。不读写 `projects/`。
"""
from __future__ import annotations

import pathlib
import sys

import pytest

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agentflow import propositionkey as PK
from agentflow import schema as S
from agentflow import secretary as SEC
from agentflow import verifications as VR
from agentflow.agent_b import AgentB
from agentflow.secretary import Secretary
from agentflow.store import Store

#: 一条长命题（键与下面那条不同、但判据判得出来）。
FULL_A = "设 G 是 3-正则群；则弦长函数不是常值。"
FULL_A_KEY = "假设 G 为 3-正则群，于是弦长函数不是常值。"

#: 两份判得出来的证明（长到过 `judgeable` 的下限）。
PROOF_A = ("证明：把弦长函数记为 f，设 G 是 3-正则群。由定义直接计算每个顶点的邻域大小，"
           "弦长只依赖邻域结构，故 f 在正则性下取常值，与假设矛盾。")
PROOF_B = ("证明：对顶点数作强归纳。取一条最长路径，用 3-正则性把端点邻域配对，"
           "再以诱导子图归结到更小的图，最终得到弦长随基图变化的递推，导出非常值。")

#: 一份"太短"的证明（内容单元 < `MIN_CONTENT_UNITS`）⇒ 同种证明那一问判不了。
SHORT_PROOF = "显然。"

#: 概念那一档的两条：一条抽得出定义项，两条抽不出定义项。
REAL_LABEL = "有限维李代数"
REAL_DEF = "概念（有限维李代数）：dim g < ∞。"
BLANK_LABEL = ""
BLANK_DEF = "设 X 是一个集合。"


def _ws(path: pathlib.Path) -> Store:
    st = Store(path / "ws")
    st.init()
    return st


def _agent(st: Store) -> AgentB:
    """B 的真实现（零模型调用：这条路只碰秘书与 store）。"""
    return AgentB(st, extractor=None, extract_text=None, config={})


def _own(full: str) -> dict:
    return {"statement_full": full, "statement_text": full[:24],
            "origin": "own_result", "kind": "conjecture",
            "doc_id": S.format_id(0), "quote_reason": "我方自产命题，没有外部引文要比对"}


def _rows(st: Store) -> list[dict]:
    return [dict(r) for r in st.rows("statements")]


def _proof_nos(row: dict) -> list[int]:
    return [int(no) for no, _ in VR.proof_list(row)]


# ============================================================ a / b：纯函数（两轴）

def test_a_short_proofs_are_still_judged(tmp_path: pathlib.Path) -> None:
    """a：短证明不按字数预判死 —— 照样判；只有"没有可比的文本"才没判成。

    2026-11-08 主笔裁定：删掉"内容单元 < `MIN_CONTENT_UNITS` ⇒ unknown"这条机械预判。
    "取 δ=ε 逐点验证"与"用有限覆盖"是两种证法，短也判得出；判不了只剩"没东西可判"
    （空文本）这一档。
    """
    short = PK.same_kind_proof("取 δ=ε，逐点验证。", "用有限覆盖。")
    assert short["checked"] is True, short
    assert short["state"] == PK.STATE_DIFFERENT, short
    for left, right in (("显然。", "由定义。"), ("x = 1", "y = 1"), ("≤ ≥ ≠", "≠ ∤ ∝")):
        got = PK.same_kind_proof(left, right)
        assert got["checked"] is True, (left, right, got)
        assert got["state"] in (PK.STATE_SAME, PK.STATE_DIFFERENT), (left, right, got)
    empty = PK.same_kind_proof("", "由定义。")
    assert empty["checked"] is False and empty["state"] == "", empty
    assert "没有可比的文本" in str(empty.get("reason") or ""), empty


def test_b_unjudgeable_concept_is_not_judged(tmp_path: pathlib.Path) -> None:
    """b：概念同一性轴判不了 ⇒ `checked=False` + `state=""`。"""
    got = PK.same_concept(BLANK_LABEL, BLANK_DEF, BLANK_LABEL, BLANK_DEF)
    assert got["checked"] is False, got
    assert got["state"] == "", got
    assert "没判成" in str(got.get("reason") or ""), got


# ============================================================ c / d：调用点 fail-closed

def test_c_judge_without_an_answer_refuses_a_new_proof_number(
        tmp_path: pathlib.Path, monkeypatch) -> None:
    """c：判定面没给出可用结论 ⇒ 受控拒 `proof_kind_unjudged`、证明号不变。

    短证明现在会照常判（见 a），所以这一档用**打桩的"没答"判定面**来造：契约是
    "判定面没答 ⇒ 不新增证明号"（未来判定面换成模型时，超时 / 坏 JSON / 没给可用
    答案都走这一档）。
    """
    monkeypatch.setattr(
        PK, "same_kind_proof",
        lambda *a, **k: {"checked": False, "state": "", "basis": "", "similarity": 0.0,
                         "reason": "打桩：判定面没给出可用结论"},
        raising=True)
    st = _ws(tmp_path)
    b = _agent(st)
    first = b.register_statement(**_own(FULL_A), proof_text=PROOF_A)
    assert first.get("ok") is True, first
    refused = b.register_statement(**_own(FULL_A_KEY), proof_text=PROOF_B)
    assert refused.get("ok") is False, refused
    assert refused.get("kind") == SEC.PROOF_KIND_UNJUDGED, refused
    assert "#1" in str(refused.get("error") or ""), refused
    rows = _rows(st)
    assert len(rows) == 1, [r.get("stmt_id") for r in rows]
    assert _proof_nos(rows[0]) == [1], _proof_nos(rows[0])


def test_d_concept_identity_unjudged_refuses_a_second_row(tmp_path: pathlib.Path) -> None:
    """d：概念同一性判不了 ⇒ 受控拒 `concept_identity_unjudged`、不新建第二行。

    在册先有一条"抽不出定义项"的概念行（`force_new` 造出，跳过一次合并判定），
    再把同形的一条交来 ⇒ 两条都抽不出定义项 ⇒ 判不了 ⇒ 整笔不写。
    """
    st = _ws(tmp_path)
    sec = Secretary("B", root=st.root, store=st)
    payload = {"statement_full": BLANK_DEF, "label": BLANK_LABEL, "statement_text": BLANK_LABEL,
               "kind": "concept", "origin": "own_result", "self_authored": True,
               "doc_id": S.format_id(0)}
    first = sec.record_statement(payload, role="B", force_new=True)
    assert first.get("created") is True, first
    refused = sec.record_statement(dict(payload, statement_full="设 Y 是一个集合。"), role="B")
    assert refused.get("checked") is False, refused
    assert refused.get("refused") == SEC.CONCEPT_IDENTITY_UNJUDGED, refused
    assert refused.get("created") is False, refused
    assert refused.get("proposition_state") == "", refused
    assert "没判成" in str(refused.get("reason") or ""), refused
    # 拒信必须给出改法（主笔 2026-11-08）：否则就是把人堵死，不是拦错。
    assert "改法" in str(refused.get("reason") or ""), refused
    assert "定义项" in str(refused.get("reason") or ""), refused
    assert len(_rows(st)) == 1, [r.get("label") for r in _rows(st)]


# ============================================================ e：反真空

def test_e_folding_unjudged_into_different_turns_the_criterion_red() -> None:
    """e（反真空）：把"判不了"填成 different（`checked=True`）⇒ a / b 的那组断言当场红。

    这两轴的反真空就是 a / b 的直接断言：谁把实现改成"判不了当不同"，`checked is False`
    与 `state == ""` 就不再成立。这里把那个错误实现的样子写出来，证明断言真的能区分：
    它给出的字典与 a / b 要求的结果恰好相反（`checked=True` / `state="different"`）。
    """
    folded_proof = {"checked": True, "state": PK.STATE_DIFFERENT}
    folded_concept = {"checked": True, "state": PK.STATE_DIFFERENT}
    for folded, want in ((folded_proof, "checked is False"), (folded_concept, "state == ''")):
        assert not (folded["checked"] is False and folded["state"] == ""), (
            f"{want}：把判不了折成 different 之后仍然被当成通过 ⇒ 反真空失败")
    # 真实现与这个错误实现逐格相反 —— 于是"改坏了"一定会被 a / b 抓住。
    real_proof = PK.same_kind_proof("", PROOF_A)
    real_concept = PK.same_concept(BLANK_LABEL, BLANK_DEF, BLANK_LABEL, BLANK_DEF)
    assert real_proof["checked"] is False and real_proof["state"] == "", real_proof
    assert real_concept["checked"] is False and real_concept["state"] == "", real_concept


# ============================================================ f：正控（不是一律拒）

def test_f_judged_verdicts_still_work(tmp_path: pathlib.Path) -> None:
    """f（正控）：判得了的 same / different 照旧 —— 两轴不是"一律拒"。"""
    same_proof = PK.same_kind_proof(PROOF_A, PROOF_A)
    assert same_proof["checked"] is True and same_proof["state"] == PK.STATE_SAME, same_proof
    diff_proof = PK.same_kind_proof(PROOF_A, PROOF_B)
    assert diff_proof["checked"] is True and diff_proof["state"] == PK.STATE_DIFFERENT, diff_proof

    same_concept = PK.same_concept(REAL_LABEL, REAL_DEF, REAL_LABEL, REAL_DEF)
    assert same_concept["checked"] is True and same_concept["state"] == PK.STATE_SAME, same_concept
    diff_concept = PK.same_concept(REAL_LABEL, REAL_DEF, "幂零李代数",
                                   "概念（幂零李代数）：降中心列在有限步终止。")
    assert diff_concept["checked"] is True, diff_concept
    assert diff_concept["state"] == PK.STATE_DIFFERENT, diff_concept

    # 命题轴的"判不了"仍是第三态（不在本件收两档的范围内）：同一条纪律在文档里写明。
    tiny = PK.same_proposition("x = 1", "y = 1")
    assert tiny["state"] == PK.STATE_UNKNOWN, tiny
    assert tiny["checked"] is False, tiny


pytestmark = pytest.mark.usefixtures("signed_v_handoffs")

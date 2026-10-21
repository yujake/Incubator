# -*- coding: utf-8 -*-
"""拒信必须点名 §3.8 的族号 + 该族正例（`draft/39` §3.11 四 D10）—— 也是 E8 的演练。

用户口径（逐字）：

> D10 拒信必须告知原因
> ……拒的时候必须给发送方理由（都是 LLM 操作，不是机械拦截）

裁定（`draft/39` §3.11 四）：拒信一律点名族号 + 违反的那一条 + 该族正例；
8 族编号就是 §3.8 那张表的编号。

为什么"族号 + 正例"是判据而不是文风：旧拒信只回一句"未通过机械检查：…"，
被拒的模型下一步只能猜该改什么（真机形态：整段结论重写一遍，结论随之漂移）。

这一组走真正会拒绝写作者的那两道门（`compose_claim` 与 `build_document`），
钉住四个代表族（1 字段存在性 / 5 免责声明 / 6 过度声称 / 7 数值证据结构），
每个都要求：拒信里有族号、有该族的正例、并且族号与 `claimanatomy` 的表逐字对得上。
"""
from __future__ import annotations

import pytest

from agentflow import claimanatomy as CA
from agentflow.store import Store
from agentflow.tools.doc_tools import (
    CROSS_CHECK_DISCLAIMER, build_document, compose_claim,
)


def _refusal_from_compose(**kw) -> str:
    """`compose_claim` 那道门：拒信原文（它先判"没有引用"这类铁律，再交给 claimanatomy）。"""
    base = dict(text="我们证明了该恒等式成立。", citations=["lit:0001"], section="§1")
    base.update(kw)
    with pytest.raises(ValueError) as exc:
        compose_claim(**base)
    return str(exc.value)


def _refusal_from_build(tmp_path, claim: dict) -> str:
    """`build_document` 那道门（落库现场）：拒信原文。"""
    ws = tmp_path / "ws"
    (ws / "data").mkdir(parents=True, exist_ok=True)
    st = Store(ws)
    st.init()
    with pytest.raises(ValueError) as exc:
        build_document(st, "paper", "标题", claims=[claim], workspace_root=str(ws))
    return str(exc.value)


def test_e8_an_overclaim_names_family_six(tmp_path):
    """第 6 族（过度声称）：证据不是 proof 却写"证明了" ⇒ 族 6。

    旧形态它与第 3 族（status × evidence_kind 交叉）共用 `inconsistent_status` ——
    两族在拒信里长得一样，而该改的栏完全不同（改措辞 vs 改证据等级）。
    """
    msg = _refusal_from_compose(evidence_kind="cross_check")
    assert "族 6" in msg, msg
    assert "过度声称" in msg and "正例" in msg, msg


def test_e8_a_missing_disclaimer_names_family_five(tmp_path):
    """第 5 族（`cross_check` 的免责声明）：走落库门（构造器会自动补声明，不该在这里判）。"""
    msg = _refusal_from_build(tmp_path, {
        "claim_id": "C1", "text": "该涨落服从中心极限定理", "evidence_kind": "cross_check",
        "citations": ["lit:0001"], "section": "§1"})
    assert "族 5" in msg, msg
    assert CROSS_CHECK_DISCLAIMER in msg, msg


def test_e8_incomplete_numeric_evidence_names_family_seven(tmp_path):
    """第 7 族（数值证据结构）：`numeric_evidence` 缺键 ⇒ 族 7（正例里带四元组）。"""
    msg = _refusal_from_build(tmp_path, {
        "claim_id": "C1", "text": "数值上支持该结论", "evidence_kind": "cross_check",
        "disclaimer": CROSS_CHECK_DISCLAIMER, "citations": ["lit:0001"], "section": "§1",
        "numeric_evidence": {"script": "code/a.py"}})
    assert "族 7" in msg, msg
    assert "n_cases" in msg and "正例" in msg, msg


def test_e8_a_missing_required_field_names_family_one(tmp_path):
    """第 1 族（字段存在性）：必填项整个不在 ⇒ 族 1。"""
    msg = _refusal_from_build(tmp_path, {
        "claim_id": "C1", "text": "一个结论", "evidence_kind": "heuristic",
        "section": "§1"})          # 刻意不给 `citations`
    assert "族 1" in msg, msg
    assert "正例" in msg, msg


def test_e8_the_refusal_carries_the_family_numbers_as_a_reading(tmp_path):
    """读数：拒信末尾带 `族号=[…]`（脚本/判据能直接读，不用正则抠中文）。"""
    msg = _refusal_from_build(tmp_path, {
        "claim_id": "C1", "text": "该涨落服从中心极限定理", "evidence_kind": "cross_check",
        "citations": ["lit:0001"], "section": "§1"})
    assert "族号=[" in msg, msg


def test_e8_every_family_has_a_name_rule_and_example():
    """反真空：8 族每一族都必须有名字、判据、正例（缺一 ⇒ 拒信里那一段会说不全）。"""
    assert sorted(CA.CLAIM_FAMILIES) == [1, 2, 3, 4, 5, 6, 7, 8], sorted(CA.CLAIM_FAMILIES)
    for num, info in CA.CLAIM_FAMILIES.items():
        assert info.get("name") and info.get("rule") and info.get("example"), (num, info)


def test_e8_every_known_code_maps_to_a_family_and_an_example():
    """反真空（判据接上了没有）：每个在用的 code 都要有族号，且族号能渲染出正例。

     2026-10-15 改：这份清单不再手写，直接迭代 `CLAIM_FAMILY_BY_CODE`。
    它此前是 12 个字符串的字面量，而 2026-10-13 新加的 `uncontrolled_disclaimer`
    没有被补进那份字面量 ⇒ 这条"反真空"判据对它一个字都没查。
    手写清单做反真空是自相矛盾的：漏登记的那个 code 正是字面量里也没有的那个，
    于是"每个 code 都查过"这句话永远为真（同族：`test_lean_switch` 只断言到
    `claimanatomy` 那一层，没人跨到落据那一步）。

    现在真身只有一个（`claimanatomy.CLAIM_FAMILY_BY_CODE`），
    末两行是负控：证明这个循环真的会失败，而不是恒真。
    """
    known = CA.CLAIM_FAMILY_BY_CODE
    assert known, "族表是空的 —— 反真空判据会退化成恒真"
    for code in known:
        fam = CA.family_of(code)
        assert fam in CA.CLAIM_FAMILIES, (code, fam)
        note = CA.family_note(code)
        assert f"族 {fam}" in note and "正例" in note, (code, note)
    # 负控①：没登记族号的 code 必须落 0（三态：不是"第 8 族"）。
    assert CA.family_of("checker_error") == 0
    # 负控②：族表里真身与新加的 code 都在（防"把表清空 ⇒ 循环空转 ⇒ 全绿"）。
    assert "uncontrolled_disclaimer" in known


def test_e8_an_unregistered_code_says_so_instead_of_guessing():
    """三态：没登记族号的 code ⇒ 明说"还没有族号"，不许猜成第 8 族。"""
    assert CA.family_of("checker_error") == 0
    note = CA.family_note("checker_error")
    assert "还没有族号" in note and "checker_error" in note, note

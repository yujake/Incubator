"""论文包专用提示词（⑥）与 24 条断言的验收判据（⑦）（`draft/28` §189）。

## 这一组守什么

`draft/28` §184.5 的第 6、7 步，以及终点门槛 A 里那两句可机械判的话
（"交付说明与 ACCEPTANCE.md 对齐"、"5 条判据无一条 judge_not_wired"）。

1. 提示词段只给该看的角色：论文包专用段里有 P1–P11 的判据表位置、claims 台账语义、
   期刊体例与五条完成定义。它给 M/G/H；给 A/B/C/E/F 是噪音 —— 而噪音会稀释它们真正
   要看的东西。这一条用"该有的都有、不该有的都没有"两个方向钉住。
2. 结论强于引文：机械半（`faculty_checks.claim_strength_findings`）逐条比对
   "这条断言说了多强"与"它挂的证据等级"，语义半（`judges` 的
   `claims.conclusion_strength`）带负控准入。两半都由判据本体检查，不靠我口头保证。
"""

from __future__ import annotations

import pathlib
import re
from typing import Any

import pytest

from agentflow import agent_prompts as AP
from agentflow import faculty_checks as FC
from agentflow import judges as JG
from agentflow import schema as S
from agentflow.deliver import gate
from agentflow.llmseam import LlmSeam
from agentflow.store import Store
from agentflow.tools import build_registry

# ============================================================ ⑥ 提示词段


def _registry(store: Store):
    return build_registry(store=store, workspace_root=store.root,
                          roles=tuple(S.ROLES)).registry


def _prompt(role: str, store: Store) -> str:
    return AP.system_prompt(role, registry=_registry(store), task="只读重放一次论文包")


def test_the_paper_pack_section_goes_to_the_roles_that_touch_the_package(store: Store):
    """正控：M（统筹交付）/ G（写稿与打包）/ H（审校）看得到这一段。"""
    for role in AP.PAPER_PACK_ROLES:
        text = _prompt(role, store)
        assert "论文包的" in text or "论文包（你参与的那份交付物）" in text, role
        assert "完成定义（五条全过才算交付" in text, role


@pytest.mark.parametrize("role", ["A", "B", "C", "D", "E", "F"])
def test_other_roles_do_not_get_the_paper_pack_section(store: Store, role: str):
    """负控（不许扩大化）：不碰论文包的角色看不到这一段 —— 噪音会稀释它们要看的东西。"""
    text = _prompt(role, store)
    assert "out/paper/ACCEPTANCE.md" not in text, role
    assert "完成定义（五条全过才算交付" not in text, role


def test_the_paper_pack_section_carries_the_four_required_facts(store: Store):
    """判据（内容）：四件必须说到的事 —— 验收表位置、台账语义、期刊体例、完成定义。

    每一条都对应一件会真实出错的事：交付说明不对齐验收表（写得像总结）、
    把 cross_check 说成证明、PDF 缺标记、把"锚漂移"当成小问题。
    """
    text = _prompt("G", store)
    for fact in ("out/paper/ACCEPTANCE.md", "P1–P11", "逐条回应那十行",
                 "cross_check", "不构成证明", "结论不许强于它挂的证据",
                 "ctexart", "五个标记", "自主评审", "断言台账", "覆盖率", "猜想表",
                 "渲染锚 0 漂移", "review_findings", "只读输入"):
        assert fact in text, f"论文包段里没有 {fact!r}"


def test_the_paper_pack_section_is_versioned(store: Store):
    """判据（可追溯）：段变了版本号就要动 —— 提示词版本是审计记录里的一栏。"""
    assert AP.PROMPT_VERSION == "p17", AP.PROMPT_VERSION


def test_the_paper_pack_says_the_package_must_follow_the_ledger(store: Store):
    """判据（§196 真机实测逼出来的）：改了台账就要让包跟上，这句必须在段里。

    实测（2026-09-30）：一轮跑出 `documents +3`、`experiments +4`，而 `out/paper/main.pdf`
    一个字节没变、`doc.paper_state` 报 `drifted` —— 台账动了、包没跟上，交付定义第 1 条
    当场不成立。G 的修订落进 documents 之后没有任何人重渲染，是这一轮真实的失败形态；
    所以"重渲染 → 重编译 → 锚回 consistent"要写成收工前的动作，而不是一句原则。
    """
    text = _prompt("G", store)
    for fact in ("doc.paper_render", "doc.paper_compile", "doc.paper_state", "drifted",
                 "包跟上"):
        assert fact in text, f"论文包段里没有 {fact!r}"
    # 负控：这句话不能只写给"读了论文包段"的角色 —— M 才是决定收工的人。
    assert "包跟上" in _prompt("M", store), "主控的提示词里没有这条收工判据"


# ============================================================ ⑥ 验收表解析（真机抓到的缺陷）


def test_the_acceptance_parser_does_not_read_not_ok_as_ok(tmp_path: pathlib.Path):
    """负控（测试当场抓到的解析缺陷）：`不成立` 不许被读成 `成立`。

    第一版判的是 `"成立" in cells[2]` —— 而 `"不成立"` 里含「成立」这个子串，
    于是写着「不成立」的那一行被数成成立（实测 2026-09-29：跑完真实验收，
    REPRO_RESULT 说 9/10，而解析出来的 `ok_count` 是 10）。这正是
    "看起来查过了、其实读反了"的形态。
    """
    from agentflow.tools.conductor_tools import _parse_acceptance

    doc = tmp_path / "ACCEPTANCE.md"
    doc.write_text(
        "# 最终验收：P1–P11 逐条读数\n\n结论：**有不成立的条目**（1/2）\n\n"
        "| 判据 | 名称 | 结论 | 读数 |\n|---|---|---|---|\n"
        "| P1 | 甲 | 成立 | 读数甲 |\n"
        "| P2 | 乙 | **不成立** | 读数乙 |\n",
        encoding="utf-8")
    got = _parse_acceptance(doc)
    assert [r["ok"] for r in got["rows"]] == [True, False], got["rows"]
    assert got["ok_count"] == 1 and got["not_ok_count"] == 1, got


def test_the_acceptance_parser_reports_a_bad_table_as_a_problem(tmp_path: pathlib.Path):
    """负控（三态）：表被写坏时 `rows` 为空而 `problems` 非空 —— 空表 ≠ 解析失败。"""
    from agentflow.tools.conductor_tools import _parse_acceptance

    doc = tmp_path / "ACCEPTANCE.md"
    doc.write_text("# 验收\n\n结论：成立\n\n这张表不见了\n", encoding="utf-8")
    got = _parse_acceptance(doc)
    assert got["rows"] == [] and got["problems"], got


# ============================================================ ⑦ 机械半


def test_claim_strength_ignores_a_theorem_name_and_a_negation():
    """负控（测试当场抓到的两个误报）：定理的名字与否定式都不算"说得比证据强"。

    第一版我自己写了一组力度词（含裸的「证明」「定理」），于是：① `服从中心极限定理`
    —— 那是一个定理的名字，不是"我证明了它"；② `不构成证明` —— 这句话明说不是证明。
    两条都会被判成超证据。修法不是把词表调细，而是不另立词表：转发
    `claimanatomy` 已有的那条判据（见 `test_the_strength_criterion_has_exactly_one_implementation`）。
    """
    got = FC.claim_strength_findings([
        {"claim_id": "N1", "text": "主坐标的涨落服从中心极限定理", "evidence_kind": "cross_check"},
        {"claim_id": "N2", "text": "数值上与公式一致（不构成证明）", "evidence_kind": "cross_check"},
        {"claim_id": "N3", "text": "该恒等式没有被证明，只是数值一致", "evidence_kind": "cross_check"},
    ])
    assert got["verdict"] == "within_evidence", got
    assert got["overclaimed"] == [] and got["problem_count"] == 0, got


def test_claim_strength_flags_a_claim_stronger_than_its_evidence():
    """正控（要抓的形态）：证据是 cross_check，正文却写着「证明了」。

    断言按"台账里已经躺着一条"来造 —— 合规的构造器会拒收它（见下面那条判据），
    而这一格要拦的正是"从别处写进来的那一行"（迁移、直接落库、判据晚于行）。
    """
    got = FC.claim_strength_findings([
        {"claim_id": "C1", "text": "我们证明了主坐标的涨落服从中心极限定理",
         "evidence_kind": "cross_check"},
    ])
    assert got["verdict"] == "overclaimed" and got["problem_count"] == 1, got
    assert got["overclaimed"][0]["claim_id"] == "C1", got
    assert got["overclaimed"][0]["codes"] == ["inconsistent_status"], got["overclaimed"][0]
    assert got["criterion_source"] == "claimanatomy.inconsistent_status", got


def test_the_strength_criterion_has_exactly_one_implementation():
    """判据（不许两份实现）：这条机械半转发 `claimanatomy`，不另立词表。

    怎么判：同一个"超证据"的文本，`claimanatomy` 的合规构造器必须拒收它，
    而 `claim_strength_findings` 必须判出它 —— 两件事指向同一份判据。
    """
    from agentflow.tools.doc_tools import compose_claim

    text = "我们证明了该涨落服从中心极限定理"
    with pytest.raises(ValueError, match="inconsistent_status"):
        compose_claim(text=text, citations=["lit:0001"], evidence_kind="cross_check",
                      section="§1")
    assert FC.claim_strength_findings(
        [{"claim_id": "C1", "text": text, "evidence_kind": "cross_check"}]
    )["verdict"] == "overclaimed"


def test_claim_strength_accepts_strong_words_only_with_proof_level():
    """负控（不许误报）：同样的措辞挂 proof 级证据时不算强于证据。"""
    got = FC.claim_strength_findings([
        {"claim_id": "C2", "text": "该恒等式已被形式化证明", "evidence_kind": "proof"},
    ])
    assert got["verdict"] == "within_evidence" and got["overclaimed"] == [], got


def test_claim_strength_separates_cannot_judge_from_within_evidence():
    """负控（三态）：没有证据等级的断言记 `unjudgeable`，不许折成"没问题"。"""
    got = FC.claim_strength_findings([{"claim_id": "C3", "text": "随便一句话"}])
    assert got["verdict"] == "unjudgeable", got
    assert got["missing_evidence"] and got["overclaimed"] == [], got
    # 两栏分开报：判不了的条数与超证据的条数不能混成一个数字
    assert got["total"] == 1, got


def test_claim_strength_is_quiet_on_a_clean_ledger():
    """正控（干净的台账）：温和措辞 + cross_check ⇒ within_evidence。"""
    got = FC.claim_strength_findings([
        {"claim_id": "C4", "text": "数值上与公式一致（不构成证明）", "evidence_kind": "cross_check"},
        {"claim_id": "C5", "text": "反例搜索未找到反例", "evidence_kind": "cross_check"},
    ])
    assert got["verdict"] == "within_evidence" and got["problem_count"] == 0, got


# ============================================================ ⑦ 语义半（判据本体）


def test_the_new_criterion_is_registered_with_negative_controls():
    """判据（准入）：新判据在表里，且带 ≥2 条负控（没有负控的判据不许进表）。

    负控不是"格式错"：两条都是真实会出现的坏形态 —— 一条把 cross_check 写成"证明"，
    一条把"数值一致"写成"对一切维数必然成立"。
    """
    assert "claims.conclusion_strength" in JG.CRITERIA, sorted(JG.CRITERIA)
    crit = JG.CRITERIA["claims.conclusion_strength"]
    assert crit.faculty == "能思辨", crit.faculty
    assert crit.pass_verdicts == ("within_evidence",), crit.pass_verdicts
    assert "{artifact}" in crit.template, "模板里没有 {artifact} ⇒ 判据看不到被审文本"
    negatives = JG.NEGATIVE_CONTROLS.get(crit.id, ())
    assert len(negatives) >= 2, negatives
    assert not JG.registry_problems(), JG.registry_problems()


def test_the_judge_is_not_wired_without_a_seam(tmp_path: pathlib.Path):
    """负控（三态）：没有接线时这条判据必须落 `judge_not_wired`（不是"通过"）。"""
    got = JG.judge("claims.conclusion_strength", "| 断言 | 证据等级 |\n|---|---|\n| A | cross_check |",
                   seam=None)
    assert got.problem == "judge_not_wired" and got.ok is False, got.to_dict()


# ============================================================ ⑦ 接进交付闸门


class _Fixed:
    """替身模型：从提示词里读出这条判据允许的判定，返回第一个（各判据的通过档）。

    为什么不写死一个判定：`deliver.gate` 默认跑全部判据，而每条判据的词表不同 ——
    写死 `within_evidence` 会让另外五条落 `judge_bad_verdict`（那正是第一版测试的样子，
    它把"替身不会答题"读成了"判据有问题"）。
    """

    spec = type("S", (), {"model": "fake"})()

    _first_verdict = re.compile(r"^\s*([a-z_]{3,}) = ", re.M)

    def complete(self, prompt: str, *, scope: str = "", system: str | None = None,
                 **kw: Any) -> Any:
        """按提示词里列出的判定词表作答（取第一个 = 该判据的通过档）。"""
        found = self._first_verdict.findall(prompt or "")
        verdict = found[0] if found else "within_evidence"
        return type("R", (), {"ok": True, "tokens_in": 3, "tokens_out": 3,
                              "error_detail": "", "error_kind": "",
                              "text": '{"verdict": "%s", "why": "替身：按词表首项作答",'
                                      ' "findings": []}' % verdict})()


def _store_with_claim(store: Store, text: str, level: str) -> Store:
    """往库里放一条带断言的文件行。

    走直接落库而不是 `doc_tools.compose_claim`：合规构造器会拒收"超证据"的断言
    （`inconsistent_status`），而闸门要拦的正是"从别处写进来的那一行"。
    这也顺带证明了这条判据不是摆设：它挡的是已经在库里的东西。
    """
    claim = {"claim_id": "C1", "text": text, "evidence_kind": level,
             "citations": ["lit:0001"], "section": "§1",
             "disclaimer": "" if level == "proof" else "数值交叉验证，不构成证明"}
    with store.tx("documents", "counters", actor="test") as tx:
        tx.upsert("documents", S.Document(
            doc_id="0000", kind="paper", title="P2 断言台账", status="draft",
            claims=[claim], markdown_path=None, created_at=S.now_iso(),
            created_by="test").to_dict())
    return store


def test_the_gate_reports_claim_strength_as_a_mechanical_finding(store: Store):
    """判据（接线）：闸门的机械半会逐条查"结论强于证据"，并把它落成工作项。"""
    _store_with_claim(store, "我们证明了该涨落服从中心极限定理", "cross_check")
    seam = LlmSeam(role="H", session_root=store.root, gateway=_Fixed(), price=(0.0, 0.0), sid="t")
    res = gate("paper-claims", "# 稿子\n\n一句。\n", session_root=store.root, seam=seam,
               criteria=["claims.conclusion_strength"], store=store)
    kinds = [m["kind"] for m in res.mechanical]
    assert "claim_strength" in kinds, res.to_dict()
    assert any(w.source == "mechanical:claim_strength" for w in res.work_items), (
        [w.to_dict() for w in res.work_items])


def test_the_gate_picks_up_the_new_criterion_by_default(store: Store):
    """判据（默认集）：不给 `--criterion` 时新判据也在里面（否则它会静默地不被跑）。"""
    seam = LlmSeam(role="H", session_root=store.root, gateway=_Fixed(), price=(0.0, 0.0), sid="t")
    res = gate("paper-default", "# 稿子\n\n一句。\n", session_root=store.root, seam=seam,
               store=store)
    judged = [c["criterion"] for c in res.criteria]
    assert "claims.conclusion_strength" in judged, judged
    assert not res.unknown_criteria, res.unknown_criteria

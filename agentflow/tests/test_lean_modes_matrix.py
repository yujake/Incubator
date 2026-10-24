# -*- coding: utf-8 -*-
"""有 Lean / 无 Lean 的模式矩阵判据（`docs/LEAN-MODES.md` 的可执行版本）。

为什么要有这一条：`tests/test_lean_switch.py` 只盯 5 个固定 face，而本矩阵覆盖
开关在两条链上的全部可观察差异 —— 提示词第一行、V 的强度声明、`check_formal` 的直拒、
`run_experiment(formal)` 的直拒、`detect_verifier` 的许可读数、以及三个角色的义务句。

## 怎么在"两种模式"之间切换

`settings` 在模块级缓存读数 ⇒ 每个用例用 `importlib.reload` 重置它，再用 `monkeypatch.setenv`
设/删 `AGENTFLOW_LEAN_ENABLED`，从而真的跑两条分支（不是断言源码文本）。
"""
from __future__ import annotations

import importlib

import pytest


def _reload_settings():
    from agentflow import settings as SET

    importlib.reload(SET)
    return SET


def _prompts():
    from agentflow import agent_prompts as AP

    importlib.reload(AP)
    return AP


def _verifications():
    from agentflow import verifications as VR

    importlib.reload(VR)
    return VR


@pytest.fixture()
def lean_off(monkeypatch):
    monkeypatch.delenv("AGENTFLOW_LEAN_ENABLED", raising=False)
    _reload_settings()
    yield
    monkeypatch.delenv("AGENTFLOW_LEAN_ENABLED", raising=False)
    _reload_settings()


@pytest.fixture()
def lean_on(monkeypatch):
    monkeypatch.setenv("AGENTFLOW_LEAN_ENABLED", "1")
    _reload_settings()
    yield
    monkeypatch.delenv("AGENTFLOW_LEAN_ENABLED", raising=False)
    _reload_settings()


# ---------------------------------------------------------------- 1. 第一行
def test_the_first_line_of_toolchain_facts_is_the_switch_state(lean_off):
    """六处提示词都写"看第一行" ⇒ 第一行必须是开关状态（S1）。"""
    first = _prompts().toolchain_facts_text().splitlines()[0]
    assert "已关闭" in first
    assert "第一行" not in first  # 它自己就是那一行


def test_the_first_line_says_explicitly_enabled_when_on(lean_on):
    """开时必须有"已开启"三个字 —— 否则六条条件句匹配不到（S1）。"""
    first = _prompts().toolchain_facts_text().splitlines()[0]
    assert "已开启" in first


# ---------------------------------------------------------------- 2. V 的强度
def test_v_is_told_its_verdict_is_never_proof_in_both_modes(lean_off, lean_on):  # noqa: ARG001
    """V 的真实入口（`cold_start_prompt`）必须写明"成立 ≠ proof"，两种模式都要（S3）。"""
    text = _verifications().cold_start_prompt("命题", "证明")
    assert "Lean 形式化" in text
    assert "不构成 `proof`" in text


# ---------------------------------------------------------------- 3. check_formal
def test_check_formal_is_a_controlled_refusal_when_off(lean_off):
    """关着时 `check_formal` 不是工具失败：`ok` 且 `reason=lean_disabled`（审计 §4）。"""
    from agentflow.tools import verify_tools as VT

    res = VT.check_formal("1 + 1 = 2")
    assert res.ok is True
    assert res.data.get("reason") == "lean_disabled"
    assert res.data.get("verified") is None


# ---------------------------------------------------------------- 4. detect_verifier
def test_detect_verifier_reports_permission_not_just_environment(lean_off):
    """`detect_verifier` 必须把"许可"一起报出来（审计 #4）：关着时 `can_do_formal=False`。"""
    from agentflow.tools import verify_tools as VT

    out = VT.detect_verifier()
    assert out["lean_enabled"] is False
    assert out["can_do_formal"] is False
    assert "许可" in str(out.get("note") or "")


# ---------------------------------------------------------------- 5. settings 读不懂
def test_an_unreadable_switch_falls_back_to_off(tmp_path, monkeypatch):
    """读不懂 ⇒ 按关处理（fail-closed，S4）。"""
    # `conftest.py` 在导入期就把 `AGENTFLOW_LEAN_ENABLED=1` 钉住了 ⇒ 这条用例必须先摘掉它，
    # 否则读到的是"环境变量说开"，根本走不到"设置文件读不懂"那一支。
    monkeypatch.delenv("AGENTFLOW_LEAN_ENABLED", raising=False)
    cfg = tmp_path / "settings.json"
    cfg.write_text('{"toolchain": {"lean_enabled": "maybe"}}', encoding="utf-8")
    monkeypatch.setenv("AGENTFLOW_SETTINGS", str(cfg))
    _reload_settings()
    first = _prompts().toolchain_facts_text().splitlines()[0]
    assert "已关闭" in first
    assert "fail-closed" in first


# ---------------------------------------------------------------- 6. 三个角色的义务句
def test_m_and_l_carry_the_formal_obligation_and_h_the_third_tier():
    """S2/S5 的文本面：M/L 有"开时义务"，H 有"开着但无检查器"这一档。

    旧期望把"开时义务"算在 E 头上（2026-10-22 改指向 L）：那时判的是
    `specs/e.py::SPEC.brief.policy` 里有「至少要真的试一次」与 `verifier_output`/`exit_code`。
    业主 2026-10-22 第四批之后形式化只由 L 做 ⇒ 这两样落在 L 那一侧：
    「至少要真的试一次」写进 L 的技能手册（`agent_skills.CATALOG["L"]`），
    `verifier_output` / `exit_code` 写进 L 的声明边界。M 那一半（"只做数值实验不算完成"）
    一个字没变 —— 它本来就是派活方的义务。
    """
    from agentflow import agent_skills as AS
    from agentflow.specs.h import SPEC as H
    from agentflow.specs.l import SPEC as L
    from agentflow.specs.m import SPEC as M

    l_txt = "\n".join(L.brief.boundary) + "\n" + "\n".join(L.brief.policy)
    assert "verifier_output" in l_txt and "exit_code" in l_txt
    l_manual = "\n".join(s.body for s in AS.CATALOG["L"])
    assert "至少要真的试一次" in l_manual, "L 的手册里没有那条「开时义务」"

    m_txt = "\n".join(M.brief.policy)
    assert "只做数值实验不算完成" in m_txt

    h_txt = "\n".join(H.brief.boundary)
    assert "开着但没有检查器" in h_txt
    assert "已形式化验证" in h_txt  # 禁令句

# ---------------------------------------------------------------- 7. 角色画像（S6）
def test_profiles_markdown_is_scrubbed_when_off(lean_off):
    """`AGENT-PROFILES.md` 的产出源必须跟着开关走（审计 S6 的真机泄漏：
    `projects/t2r/AGENT-PROFILES.md:56` 关着 Lean 仍印"数值实验与形式化验证"）。"""
    from agentflow import agent_prompts as AP

    text = AP.profiles_markdown()
    assert "可检查的形式化代码" not in text, "关着 Lean 时画像里不许还承诺「可检查的形式化代码」"
    assert "不做形式化验证" in text


def test_profiles_markdown_keeps_formal_wording_when_on(lean_on):
    from agentflow import agent_prompts as AP

    text = AP.profiles_markdown()
    assert "形式化验证" in text

# ---------------------------------------------------------------- 8. 技能索引（S6）
def test_the_skills_index_says_whose_sign_counts_when_on(lean_on):
    """开着时索引末尾补的那一句"形式化以什么为准、由谁安排"。

    历史：旧期望是"关掉时补一句做不了"（2026-10-22 翻面成"形式化见 L"）⇒
    2026-10-24（业主：是否形式化由用户指定，指定之后 M 派 B、B 派 L）改成
    "形式化以 V 的签与 B 的台账为准"：非 B 角色与 L 之间没有边，所以索引只写
    结论的落点与安排人，不写"去找谁"。
    """
    from agentflow import agent_skills as S

    block = S.index_block("M")
    assert "形式化以 V 的签与 B 的台账为准" in block, block[-400:]
    assert "指定之后每一条由 **B** 逐条安排" in block, block[-400:]
    assert "形式化见 L" not in block, "索引里又出现了「形式化见 L」（非 B 角色与它没有边）"
    # L 自己的索引不加这一句（它不需要被告知"这条路的结论记在谁那里"）
    assert "形式化以 V 的签与 B 的台账为准" not in S.index_block("L")
    # B 那一格也不加：它的收件通道写在 `specs/b.py` 的政策里（唯一该写全的地方）
    assert "形式化以 V 的签与 B 的台账为准" not in S.index_block("B")
    # E8 / E5（2026-10-25）：E 的 Lean 侧要清干净 —— 技能索引这一句也不再发给它
    # （它的工具面上 0 件 formal.* / detect_verifier，写集只有 experiments）。
    assert "形式化以 V 的签与 B 的台账为准" not in S.index_block("E")


def test_the_skills_index_has_no_trace_of_l_when_off(lean_off):
    """关着时索引里一个字都不许留 L（旧期望是那一刻补一句"Lean 形式化关闭"，2026-10-22 改成零痕迹）。"""
    import re

    from agentflow import agent_skills as S

    block = S.index_block("E")
    assert "本会话 Lean 形式化关闭" not in block
    assert not re.search(r"(?<![A-Za-z0-9_])L(?![A-Za-z0-9_])", block), block[-400:]


# ---------------------------------------------------------------- 9. H 的措辞中性
def test_h_faculty_wording_is_mode_neutral():
    """H 的"手"那条注解：形式化不许再被写死成 E 的活（2026-10-22 的指向批）。

    旧期望是"形式化或实验"（把形式化算在 E 头上）。那一批先改成"或走形式化那一岗
    （形式化那一岗是 L）"，随后并行的声明对账批把这一句整个收短（H 的手只留"找谁核实"，
    形式化那一路由技能索引那一句统一指）⇒ 这里守的东西收成两条：
    ① 注解里点着 E 的是"实验"，不是"形式化"；② 注解与 `specs/h.py` 的 local_notes 逐字同一份
    （那一半由 `tests/test_agent_spec_reconciliation.py` 守，这里只钉措辞方向）。
    """
    from agentflow import agent_prompts as AP

    notes = AP.FACULTY_LOCAL[("H", "手")]
    assert "E（实验）" in notes, notes
    assert "E（形式化" not in notes, notes


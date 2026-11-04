# -*- coding: utf-8 -*-
"""判据：`lean_file` 按这条命题的证明通道教（G/H 的可见面），并把 `file` 的两种落点与索引四格教出来。

## 真身（为什么只能这样教）

`papermapping._credential_slot` 把每一行交给 `numericproof.formal_slot`，通道只有三档：
numeric（证明栏第 ① 段是程序、台账里有 E 签的穷举）⇒ `lean_file` 必填，填的就是那份 .py 程序，
`lean_target` 填了反受控拒绝；formal ⇒ .lean 与它验的声明名两格都要有；通道为空 ⇒ 两格允许为空。
`file` 的落点分两种：理论定理行写论文包内的相对路径，数值实验定理行写程序相对仓库根的路径
（不在包里是正常的）。数值实验定理那一行另带索引四格（`numericproof.INDEX_*`，判据
`numerictheorem.evidence_index_problems`），B 顺它取正文。

改前 G/H 的可见面教的是「有 Lean 产出时每行还要写两格」与「三格齐才算写完」：前者把数值通道
也当成 Lean 那一档（那一格在数值定理上必须填 .py，关档会话里也一样），后者把索引四格漏在门外。

## 判据

a. G/H 的可见面读到「numeric ⇒ `lean_file` 是那份 .py、`lean_target` 留空」与
   「formal ⇒ .lean + `lean_target`」；
b. 读到索引四格与 `file` 的两种落点；
c. 反真空：把旧句逐处回灌 ⇒ 同一个读法必须红。
"""
from __future__ import annotations

import pathlib
import sys

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agentflow import agent_prompts as AP      # noqa: E402
from agentflow import agent_skills as AS       # noqa: E402
from agentflow import settings as SET         # noqa: E402
from agentflow.tools import build_registry    # noqa: E402


def _prompt(role: str) -> str:
    return AP.system_prompt(role, registry=build_registry().registry)


#: G 的可见面必须逐字读到的锚点（缺一条就是没教到）。
G_REQUIRED: tuple[str, ...] = (
    "按这条命题的证明通道填",
    "numeric（数值证明",
    "证明栏第 ① 段那份 `.py` 程序",
    "`lean_target` 留空",
    "formal（形式化）",
    "`lean_target` 必填",
    "`.lean`",
    "通道为空",
    "两格都可以留空",
    "`file` 有两种落点",
    "论文包内的相对路径",
    "相对仓库根",
    "evidence_kind",
    "evidence_path",
    "evidence_sha256",
    "v_signature",
)

#: 改前那两句（回灌任何一句都必须让读法报出来）。
G_STALE: tuple[str, ...] = (
    "有 Lean 产出时每行还要写",
    "「三格齐」才算这一行写完",
)


def check_g(text: str) -> list[str]:
    """G 的可见面缺什么 / 还留着哪句旧话（空 = 干净）。"""
    bad = [f"[G] 读不到 {needle!r}" for needle in G_REQUIRED if needle not in text]
    bad += [f"[G] 仍写着旧句 {needle!r}" for needle in G_STALE if needle in text]
    return bad


def test_g_teaches_lean_file_by_the_proof_channel() -> None:
    """a / b：G 的渲染提示词按通道教凭据格，并带索引四格与 file 的两种落点。"""
    text = _prompt("G")
    assert len(text) > 5000, f"G 的渲染只有 {len(text)} 字符 ⇒ 这一条没有落脚点"
    assert check_g(text) == [], "\n".join(check_g(text))
    # 通道的两半不许折成一句话：numeric 那一半与 formal 那一半各点各的。
    numeric_at = text.find("numeric（数值证明")
    formal_at = text.find("formal（形式化）")
    assert 0 <= numeric_at < formal_at, (numeric_at, formal_at)


def test_putting_the_old_lean_row_back_turns_g_red() -> None:
    """c：把「有 Lean 产出时每行还要写两格」回灌进 G 的可见面 ⇒ 必红。"""
    broken = _prompt("G") + (
        "\n有 Lean 产出时每行还要写 `lean_file` 与 `lean_target`"
        "（本会话产不出 Lean 产出 ⇒ 这两格留空）；空着不算验过。")
    problems = check_g(broken)
    assert any("有 Lean 产出时每行还要写" in one for one in problems), problems


def test_putting_the_old_three_cells_sentence_back_turns_g_red() -> None:
    """c：把「三格齐才算这一行写完」回灌 ⇒ 必红（它把索引四格与凭据格漏在门外）。"""
    broken = _prompt("G") + "\n**「三格齐」才算这一行写完**：理论定理行 = `file` 那一格。"
    problems = check_g(broken)
    assert any("「三格齐」才算这一行写完" in one for one in problems), problems


def test_the_closed_tier_still_requires_lean_file_for_the_numeric_channel(
        monkeypatch) -> None:
    """关档替身也不许把数值通道的 `lean_file` 放空（它要的是那份 .py，不是 Lean 产物）。"""
    monkeypatch.setenv(SET.ENV_LEAN_ENABLED, "0")
    AP.reset_toolchain_readings()
    try:
        text = AP.system_prompt("G", registry=build_registry().registry)
    finally:
        AP.reset_toolchain_readings()
    assert "证明栏第 ① 段那份 `.py` 程序" in text, (
        "关档的 G 提示词里，数值通道的 lean_file 也不再被要求填那份 .py 了")
    assert "`lean_target` 留空" in text, "关档的 G 提示词里丢了「numeric ⇒ lean_target 留空」"
    assert "这两格留空" not in text, (
        "关档的 G 提示词仍写着「这两格留空」—— 数值通道在关档会话里仍然必填")


# ============================================================ 手册（G / H 的按需面）

G_MANUAL_SLUG = "成稿-正文自己写"
H_MANUAL_SLUG = "审校-每条发现都要能复核"


def _manual_body(role: str, slug: str) -> str:
    return next(skill for skill in AS.CATALOG[role] if skill.slug == slug).body


G_MANUAL_REQUIRED: tuple[str, ...] = (
    "证明通道",
    "`lean_file`",
    "`lean_target` 留空",
    "`.py`",
    "`.lean`",
    "索引四格",
    "evidence_kind",
    "evidence_path",
    "evidence_sha256",
    "v_signature",
    "论文包内",
    "相对仓库根",
)

G_MANUAL_STALE: tuple[str, ...] = (
    "③ 逐行核三格齐",
    "`file` 写**论文包内的相对路径**（绝对路径",
)

H_MANUAL_REQUIRED: tuple[str, ...] = (
    "证明通道",
    "`lean_file`",
    "`.py`",
    "`lean_target` 留空",
    "`.lean`",
    "索引四格",
    "evidence_kind",
    "evidence_path",
    "evidence_sha256",
    "v_signature",
    "不在包里是正常的",
)

H_MANUAL_STALE: tuple[str, ...] = (
    "`file` 指向的那份文件在不在论文包里",
)


def check_manual(text: str, required: tuple[str, ...],
                 stale: tuple[str, ...]) -> list[str]:
    bad = [f"读不到 {needle!r}" for needle in required if needle not in text]
    bad += [f"仍写着旧句 {needle!r}" for needle in stale if needle in text]
    return bad


def test_g_manual_teaches_lean_file_by_the_proof_channel() -> None:
    """a / b（手册面）：G 的成稿手册按通道教凭据格，并带索引四格与 file 的两种落点。"""
    body = _manual_body("G", G_MANUAL_SLUG)
    assert len(body) > 2000, f"G 的成稿手册只有 {len(body)} 字符 ⇒ 这一条没有落脚点"
    assert check_manual(body, G_MANUAL_REQUIRED, G_MANUAL_STALE) == [], "\n".join(
        check_manual(body, G_MANUAL_REQUIRED, G_MANUAL_STALE))


def test_h_manual_checks_file_and_lean_file_by_the_proof_channel() -> None:
    """a / b（手册面）：H 的对应表手册也按通道核，不再只按「包内」判 file。"""
    body = _manual_body("H", H_MANUAL_SLUG)
    assert len(body) > 1000, f"H 的对应表手册只有 {len(body)} 字符 ⇒ 这一条没有落脚点"
    assert check_manual(body, H_MANUAL_REQUIRED, H_MANUAL_STALE) == [], "\n".join(
        check_manual(body, H_MANUAL_REQUIRED, H_MANUAL_STALE))


def test_putting_the_old_g_manual_lines_back_turns_it_red() -> None:
    """c：把 G 手册里那两句旧话逐句回灌 ⇒ 同一读法必须红。"""
    body = _manual_body("G", G_MANUAL_SLUG)
    for stale in G_MANUAL_STALE:
        problems = check_manual(body + "\n" + stale, G_MANUAL_REQUIRED, G_MANUAL_STALE)
        assert any(stale in one for one in problems), (stale, problems)


def test_putting_the_h_package_only_file_rule_back_turns_it_red() -> None:
    """c：把 H 手册「file 只在论文包里」那句回灌 ⇒ 必红。"""
    body = _manual_body("H", H_MANUAL_SLUG)
    for stale in H_MANUAL_STALE:
        problems = check_manual(body + "\n" + stale, H_MANUAL_REQUIRED, H_MANUAL_STALE)
        assert any(stale in one for one in problems), (stale, problems)

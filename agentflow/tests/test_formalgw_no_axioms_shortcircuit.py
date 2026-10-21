"""`E-1` 的回归判据：一句"不依赖公理"不许再清空整份公理表。

缺陷（2026-09-26 全面体检 · 子代理 E 发现，主控已复现）：`formalgw._axioms_of` 旧实现第一句是 `if _NO_AXIOMS.search(text): return []`（text = 检查器 stdout + stderr 全文）⇒ 被检查的源码里任何一处带出 `does not depend on any axioms`（一句 `#eval IO.println "..."` 就够）就丢弃整份公理表 ⇒ `axiom e_ax : P` + `theorem bad : P := e_ax`（假设结论再宣布结论）被判成 `status=verified` + `proved=True` + `evidence_kind="proof"`。同一条短路也吃掉 `"sorryAx" in axioms` 那道 sorry 判据（两者读同一个列表）。

本文件守什么：离线（不依赖 Lean，用假的 `run_fn`）公理列表优先 —— 输出里同时出现"不依赖"与"依赖 [...]"时，必须返回那份列表（fail-closed）。在线（Lean 在 PATH 时）真跑一遍 `axiom` 那段源码，必须是 `extra_axioms`；不在 PATH 时 `skip`（"不许因为环境不同就红"，与 `test_agent_e_formal_path.py` 同口径），但离线那两条仍会跑，所以判据不会因为没有 Lean 就消失。"""
from __future__ import annotations

import shutil

import pytest

from agentflow import formalgw as FG

_BOTH_FORMS = (
    "'audited_thm' does not depend on any axioms\n"
    "#eval IO.println \"does not depend on any axioms\"\n"
    "'helper' depends on axioms: [propext, Quot.sound]\n"
)


def test_reported_axioms_win_over_the_no_axioms_sentence() -> None:
    """负控（离线，核心）：两种形态同时出现时，公理列表优先 —— 短路必须不再存在。

    这条用例在改前必红（改前返回 `[]`）。它是本文件的主要价值：
    不依赖 Lean，任何机器上都能跑。
    """
    got = FG._axioms_of(_BOTH_FORMS, name="audited_thm")
    assert got == ["propext", "Quot.sound"], (
        f"公理列表被'不依赖公理'那句话清空了 ⇒ E-1 复发：{got!r}"
    )


def test_explicitly_clean_declaration_is_still_clean() -> None:
    """正控（离线）：指名说"不依赖"且没有任何公理列表 ⇒ 空列表（不许把所有情形都判成有公理）。"""
    assert FG._axioms_of("'audited_thm' does not depend on any axioms\n", name="audited_thm") == []
    # 一句没指名的"不依赖"（例如源码里的 #eval 打印）在没有公理列表时也给空 ——
    # 这一档由 verified 的其余前提（退出码 0 / 无 sorry / 声明名被检查到）兜住。
    assert FG._axioms_of('does not depend on any axioms\n', name="audited_thm") == []


def test_named_clean_line_does_not_excuse_a_listed_axiom() -> None:
    """负控（离线）：被审声明自己那一行说"不依赖"，但输出里另有公理列表 ⇒ 仍报列表。

    这正是"列表优先"的含义：公理依赖会传递，列表非空时我们无法证明二者无关；
    把它读成"没有公理"是唯一会造成假 proof 的方向。
    """
    text = (
        "'audited_thm' does not depend on any axioms\n"
        "'helper' depends on axioms: [Classical.choice]\n"
    )
    assert FG._axioms_of(text, name="audited_thm") == ["Classical.choice"]


@pytest.mark.skipif(shutil.which("lean") is None, reason="本机 PATH 没有 lean ⇒ 真跑那条跳过（离线两条仍跑）")
def test_real_lean_axiom_trick_is_not_verified() -> None:
    """负控（在线，E-1 本体）：真 Lean 上"假设结论再宣布结论 + 一句 #eval"必须不是 verified。"""
    src = (
        "axiom e1_probe_ax : (1:Nat) = 1\n"
        "theorem e1_probe_bad : (1:Nat) = 1 := e1_probe_ax\n"
        '#eval IO.println "does not depend on any axioms"\n'
    )
    r = FG.check_lean(src, name="e1_probe_bad", imports=(), timeout_sec=120)
    assert r.get("status") == "extra_axioms", r
    assert r.get("axioms") == ["e1_probe_ax"], r
    ev = FG.evidence_of(r)
    assert ev.get("proved") is False and ev.get("evidence_kind") is None, ev


@pytest.mark.skipif(shutil.which("lean") is None, reason="本机 PATH 没有 lean ⇒ 真跑那条跳过")
def test_real_lean_clean_kernel_theorem_is_still_verified() -> None:
    """正控（在线）：内核真命题仍须 `verified` + proof 级（收紧不许把真证明一起拒掉）。"""
    r = FG.check_lean("theorem e1_probe_ok : (1:Nat) + 1 = 2 := rfl\n", name="e1_probe_ok",
                      imports=(), timeout_sec=120)
    assert r.get("status") == "verified", r
    ev = FG.evidence_of(r)
    assert ev.get("proved") is True and ev.get("evidence_kind") == "proof", ev

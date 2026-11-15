# -*- coding: utf-8 -*-
"""反真空：RC2 的两条新判据必须承重（不是橡皮图章）。

判据本体与读数函数在 `tests/test_rehearsal_cli_proof_main_chain.py`：

- 判据① `_one_row_per_call_problems` —— 每笔真调用有且只有一行账；
- 判据② `_session_problems` —— 全部 `llm_call` 落在本趟 `sid`。

本文件只做一件事：把修复的每一半改回旧形态，跑同一条 CLI 真路径彩排，证明
那条判据会红，并且红出来的读数与 RC2 现场一致。它刻意不叫 `test_rehearsal_*`：
它跑的是"坏掉的产品形态"，不是一条可以拿当真机前置的彩排（`rehearsal_contract`
的静态判据对彩排文件生效，对这里不生效 —— 这里允许把产品内部函数换掉，
因为那正是反真空要造的那个"坏"）。

为什么要有这一份（TDD 的两半）：只写"修完是绿的"没有区分度 —— 一条永远绿的判据
与一条真的判据在读数上长得一样。把幂等键 / 会话归口改回旧形态之后必须红，
"绿"才重新有意义。
"""
from __future__ import annotations

import pathlib

import pytest

from test_rehearsal_cli_proof_main_chain import (
    _ledger_identity,
    _one_row_per_call_problems,
    _run,
    _session_problems,
    _session_split,
)


def _old_form_run(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, *,
                  legacy_key: bool = False, skip_v_seam: bool = False,
                  no_ambient_sid: bool = False) -> dict:
    """跑一趟彩排，按开关把修复的某几半改回旧形态。

    - `legacy_key`：幂等键命名空间回到 `task:<号>`（`llmseam._idem_namespace`）；
    - `skip_v_seam`：不登记 `role_seam("V")`（工具路径回到 env 现造第二条缝）；
    - `no_ambient_sid`：秘书装配不读 ambient sid（回到 `sid=None`）。
    """
    from agentflow import llmseam as LS
    import agentflow.secretary as SEC

    if legacy_key:
        monkeypatch.setattr(LS, "_idem_namespace",
                            lambda **kw: f"task:{kw.get('task_id') or ''}")
    if skip_v_seam:
        real = LS.set_role_seam

        def _skip_v(role: str, llm: object) -> None:
            real(str(role), None if str(role) == "V" else llm)

        monkeypatch.setattr(LS, "set_role_seam", _skip_v)
    if no_ambient_sid:
        monkeypatch.setattr(SEC, "_ambient_session_sid", lambda: None)
    return _run(tmp_path, monkeypatch, lean="0")


# ============================================================ 判据①的反真空


def test_the_one_row_criterion_goes_red_when_the_key_goes_back_to_the_task_namespace(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """只把幂等键改回旧形态 ⇒ 判据①必红（每笔一行账不成立）。

    旧命名空间只带召唤号，而序号按 `(工作区, 会话, 角色, 召唤号)` 数 ⇒ 同一个召唤上
    两条不同的缝在各自的 `idx=0` 上撞键。缝分裂修好之后，被吞的是角色之间的
    那几笔：`secretary:V` ×3、`secretary:B` ×1（V 的那两笔属于缝分裂，另见
    :func:`test_the_session_criterion_goes_red_when_the_v_role_seam_is_not_registered`
    与全旧形态那一条）。

    反真空的形态：`_one_row_per_call_problems` 返回非空，且点名的正是这 4 笔；
    `duplicate` 行的 `usage_id` 仍指向别人的账本行（"已经记过了"的那一行）。
    """
    got = _old_form_run(tmp_path, monkeypatch, legacy_key=True)
    reading = _ledger_identity(got["ws"], got["store"])
    problems = _one_row_per_call_problems(reading)
    print(f"[反真空·键] calls={reading['calls']} rows={reading['rows']} "
          f"duplicates={[(c['role'], c['session']) for c in reading['duplicates']]}")
    assert problems, "把幂等键改回 `task:<号>` 之后判据①仍然是绿的 ⇒ 这条判据不承重"
    assert [(c["role"], c["session"]) for c in reading["duplicates"]] == [
        ("secretary:V", "rc2-main-chain"), ("secretary:V", "rc2-main-chain"),
        ("secretary:V", "rc2-main-chain"), ("secretary:B", "rc2-main-chain"),
    ], reading["duplicates"]
    assert (reading["calls"], reading["rows"]) == (16, 12), reading["calls"]
    # 判据②不受影响：键改回旧形态只吞账，不改事件落在哪个会话文件上。
    assert _session_problems(_session_split(got["ws"])) == [], (
        "这一半反真空把判据②也弄红了 ⇒ 两条判据不独立，读数分不清该修哪一处")


# ============================================================ 判据②的反真空


def test_the_session_criterion_goes_red_when_the_v_role_seam_is_not_registered(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """只撤销 `role_seam("V")` 的登记 ⇒ 判据②必红（V 的 3 条落缺省会话）。

    这就是改前工具路径的形态：`AgentV._seam` 按 env 现造第二条缝（无 sid）。
    判据①仍然绿 —— 钱照记（这条缝自己带 TokenMeter），只是审计事件不在这一趟。
    两条判据各自承重、互不代偿，正是它们要分开写的理由。
    """
    got = _old_form_run(tmp_path, monkeypatch, skip_v_seam=True)
    split = _session_split(got["ws"])
    problems = _session_problems(split)
    print(f"[反真空·会话] in_run={len(split['in_run'])} "
          f"elsewhere={[(c['role'], c['session']) for c in split['elsewhere']]}")
    assert problems, "撤销 V 的按角色缝之后判据②仍然是绿的 ⇒ 这条判据不承重"
    assert [c["role"] for c in split["elsewhere"]] == ["V", "V", "V"], split["elsewhere"]
    assert all(c["session"] != "rc2-main-chain" for c in split["elsewhere"]), split["elsewhere"]
    assert _one_row_per_call_problems(_ledger_identity(got["ws"], got["store"])) == [], (
        "这一半反真空把判据①也弄红了 ⇒ 两条判据不独立")


def test_the_session_criterion_goes_red_when_the_secretaries_lose_the_ambient_sid(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """只把秘书的 ambient sid 摘掉 ⇒ 判据②必红（秘书的 4 条落缺省会话）。

    `secretary:V` ×3 + `secretary:B` ×1。它们与 V 本体的那 3 条是两处装配
    缺口（工具路径的缝、秘书的缝），所以修复与反真空都分开做。
    """
    got = _old_form_run(tmp_path, monkeypatch, no_ambient_sid=True)
    split = _session_split(got["ws"])
    problems = _session_problems(split)
    print(f"[反真空·秘书会话] in_run={len(split['in_run'])} "
          f"elsewhere={[(c['role'], c['session']) for c in split['elsewhere']]}")
    assert problems, "摘掉秘书的 ambient sid 之后判据②仍然是绿的 ⇒ 这条判据不承重"
    assert [c["role"] for c in split["elsewhere"]] == [
        "secretary:V", "secretary:V", "secretary:V", "secretary:B"], split["elsewhere"]
    assert all(c["session"] != "rc2-main-chain" for c in split["elsewhere"]), split["elsewhere"]
    assert _one_row_per_call_problems(_ledger_identity(got["ws"], got["store"])) == [], (
        "这一半反真空把判据①也弄红了 ⇒ 两条判据不独立")


# ============================================================ 全旧形态：复现 RC2 现场


def test_the_exact_rc2_readings_come_back_when_all_three_halves_are_reverted(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """三半一起改回旧形态 ⇒ 逐字复现 RC2 的 6 笔吞账 + 7 条缺省会话。

    这是"改前红"的忠实重现：16 次真调用、账本 10 行（+2 行召唤结算 = 12）、
    `duplicate` 6 笔（V ×2、secretary:V ×3、secretary:B ×1）、
    缺省会话 7 条（V ×3、secretary:V ×3、secretary:B ×1）。修复后的读数见
    `tests/test_rehearsal_cli_proof_main_chain.py` 的两条正控。
    """
    got = _old_form_run(tmp_path, monkeypatch, legacy_key=True,
                        skip_v_seam=True, no_ambient_sid=True)
    reading = _ledger_identity(got["ws"], got["store"])
    split = _session_split(got["ws"])
    print(f"[反真空·全旧] calls={reading['calls']} rows={reading['rows']} "
          f"duplicates={[c['role'] for c in reading['duplicates']]} "
          f"elsewhere={[c['role'] for c in split['elsewhere']]}")
    assert _one_row_per_call_problems(reading), "全旧形态下判据①仍绿 ⇒ 它不承重"
    assert _session_problems(split), "全旧形态下判据②仍绿 ⇒ 它不承重"
    assert reading["calls"] == 16, reading["calls"]
    assert reading["rows"] == 10, reading["rows"]
    assert [c["role"] for c in reading["duplicates"]] == [
        "V", "secretary:V", "secretary:V", "secretary:V", "secretary:B", "V"]
    assert len(split["elsewhere"]) == 7, split["elsewhere"]
    assert [c["role"] for c in split["elsewhere"]] == [
        "V", "secretary:V", "V", "secretary:V", "V", "secretary:V", "secretary:B"]

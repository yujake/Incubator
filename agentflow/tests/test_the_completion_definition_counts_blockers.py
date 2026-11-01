# -*- coding: utf-8 -*-
"""完成定义：八格全过还不够，还要「没有 blocker」（审计 174 §二 第 28 行）。

`closing` 的真身是 `machine_pass = all(status[格] == "pass") and not blockers`
（`closing.py:3634-3643`）。改前 PAPER_PACK 第五节的完成定义只写「收工门八格全过才算
交付」—— 窄了一个维度：`statements_unsigned`（既无 V 签又未放弃的命题）这类 blocker
**不落在任何一格上**，八格全绿也照样把 `machine_pass` 打成假。

这一份判据钉三件：
1. M / G / H 三格（`PAPER_PACK` 的注册面）都读到「八格全过且没有 blocker」这句；
2. 它点名 `statements_unsigned` —— 本轮新加的 blocker 里最该被说清的那一个；
3. 反真空：`closing` 的真身仍是「八格 ∧ 无 blocker」（判据不靠一句文案自证）。
"""
from __future__ import annotations

import pathlib
import sys

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agentflow import agent_prompts as AP   # noqa: E402
from agentflow.tools import build_registry  # noqa: E402

_REG = build_registry().registry


def test_paper_pack_completion_definition_includes_blockers() -> None:
    bad: list[str] = []
    for role in ("M", "G", "H"):
        text = AP.system_prompt(role, registry=_REG)
        # 反真空：这一段真的在那三格里。
        if "完成定义" not in text:
            bad.append(f"{role} 的提示词里没有「完成定义」那一段")
            continue
        if "blocker" not in text:
            bad.append(f"{role} 的完成定义没提 blocker")
        if "八格全过" not in text:
            bad.append(f"{role} 的完成定义没说「八格全过」")
        if "statements_unsigned" not in text:
            bad.append(f"{role} 的完成定义没点名 statements_unsigned 这类不落在格上的 blocker")
    assert not bad, "完成定义没覆盖 blocker 这一维：\n  " + "\n  ".join(bad)


def test_machine_pass_is_eight_cells_and_no_blocker() -> None:
    """反真空：真身必须是「八格 ∧ 无 blocker」——否则上面那条只是在追文案。"""
    from agentflow import closing

    src = pathlib.Path(closing.__file__).read_text(encoding="utf-8")
    assert "not self.blockers" in src, (
        "`closing.machine_pass` 不再看 blockers ⇒ 完成定义那句「且没有 blocker」就成了假话")
    assert len(closing.DEFAULT_CHECKS) == 8, len(closing.DEFAULT_CHECKS)

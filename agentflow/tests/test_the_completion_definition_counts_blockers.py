# -*- coding: utf-8 -*-
"""完成定义：门里的格全过还不够，还要「没有 blocker」（审计 174 §二 第 28 行）。

`closing` 的真身是 `machine_pass = all(status[格] == "pass") and not blockers`
（`closing.py` 的 `machine_pass`）。这一份判据钉三件：
1. M / G / H 三格（`PAPER_PACK` 的注册面）都读到「八格全过且没有 blocker」这句；
2. 它把 `statements_unsigned` 写成读数（不是 blocker）—— 与 `closing.py` 的真身一致；
3. 反真空：`closing` 的真身仍是「门里那八格 ∧ 无 blocker」（判据不靠一句文案自证）。

## 口径沿革（这一条是"判据口径变更"，不是放宽）

- 2026-11-14（业主裁定）：`paper` 退出收工判定 ⇒ `DEFAULT_CHECKS` 从八格变七格。
- 2026-11-15（p283）：PAPER_PACK 那一句跟着改成「七格全过」，`paper` 写明落
  `readings.paper`。
- 2026-11-16（Q1）：加回第八格 `literature_pending` ⇒ `DEFAULT_CHECKS` 又是 8 格。
- 2026-11-17（本批）：两处判据一起改口径 —— 「七格」→「八格」；`statements_unsigned`
  从「必须点名它是 blocker」改成「必须点名它是读数（不是 blocker）」。真身
  `closing.py` 早在 2026-11-16 裁定 3 + 追加裁定 B 就把它降成 `readings` 了
  （`closing.py:8589` 只写 `rep.readings["statements_unsigned"]`），本文件此前把错的那一侧
  钉着：谁把教法改对，这里就红。
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
        if "`statements_unsigned`" not in text:
            bad.append(f"{role} 的完成定义没点名 `statements_unsigned`")
        # 口径：它落在 `readings`（2026-11-16 裁定 3 + 追加裁定 B），不是格外 blocker。
        # 只要求"点名"会被「说成 blocker」也满足 —— 所以这一条钉的是读法。
        if "`statements_unsigned` 不是 blocker，是读数" not in text:
            bad.append(f"{role} 把 `statements_unsigned` 写成了 blocker（它现在是读数）")
    assert not bad, "完成定义没覆盖 blocker 这一维：\n  " + "\n  ".join(bad)


def test_machine_pass_is_eight_cells_and_no_blocker() -> None:
    """反真空：真身必须是「八格 ∧ 无 blocker」——否则上面那条只是在追文案。

    2026-11-19（ROOTGATE-①）：`machine_pass` 从 `ClosingReport` 搬到唯一的
    `closing_verdict` 里，但仍然必须是 `cells 全 pass ∧ 没有 blocker` 这个合取；
    锚点跟着搬，判据一个字不放宽。
    """
    from agentflow import closing

    src = pathlib.Path(closing.__file__).read_text(encoding="utf-8")
    assert "def closing_verdict" in src, "唯一结论入口不见了（锚点没有落脚点）"
    assert "and not blockers" in src, (
        "`closing_verdict.machine_pass` 不再看 blockers ⇒ 完成定义那句"
        "「且没有 blocker」就成了假话")
    assert len(closing.DEFAULT_CHECKS) == 8, len(closing.DEFAULT_CHECKS)

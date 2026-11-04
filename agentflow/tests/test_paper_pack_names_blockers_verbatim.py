# -*- coding: utf-8 -*-
"""判据：PAPER_PACK 第五节把三处读数名与两类 blocker 写到与实现逐字一致。

## 三处（改前都写成另一个名字）

| # | 真身 | 改前 PAPER_PACK 写的是 |
|---|---|---|
| 1 | `closing.MAPPING_NOT_WRITTEN_CODE = "mapping_not_written"`（`closing.py`） | `MAPPING_NOT_WRITTEN`（大写常量名当读数名） |
| 2 | `_check_paper`：回执不匹配 ⇒ `readings["paper"]["verdict"]="drifted"` + `status["paper"]="fail"` + `paper_pdf_is_stale` | 「回执不是它的 ⇒ `failed`」 |
| 3 | `statements_unsigned` / `mapping_not_written` 不落在八格里；`acceptance_unmet` 落 `acceptance` 格、`paper_pdf_is_stale` 落 `paper` 格 | 「同类 blocker 还有 ……」把两类混成一类 |

判据：a 三处逐字一致；b 反真空逐处回灌旧句 ⇒ 红；c 只动这三处（由提交 diff 证明，本文件只钉 a/b）。
"""
from __future__ import annotations

import pathlib
import sys

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agentflow import agent_prompts as AP      # noqa: E402
from agentflow.tools import build_registry    # noqa: E402

#: PAPER_PACK 注入的三个角色。
ROLES = ("M", "G", "H")


def _prompt(role: str) -> str:
    return AP.system_prompt(role, registry=build_registry().registry)


#: 改后必须逐字读到的锚点。
REQUIRED: tuple[str, ...] = (
    "`mapping_not_written`",
    "格外 blocker",
    "格上 blocker",
    "`acceptance_unmet` 落在 `acceptance` 那一格",
    "`paper_pdf_is_stale` 落在 `paper` 那一格",
    'verdict="drifted"',
    "那一格记 `fail`",
)

#: 改前那三句（回灌任何一句都必须让读法报出来）。
STALE: tuple[str, ...] = (
    "MAPPING_NOT_WRITTEN",
    "同类 blocker",
    "回执不是它的 ⇒ `failed`",
)


def check(text: str) -> list[str]:
    """缺哪个锚点 / 还留着哪句旧话（空 = 干净）。"""
    bad = [f"读不到 {needle!r}" for needle in REQUIRED if needle not in text]
    bad += [f"仍写着旧句 {needle!r}" for needle in STALE if needle in text]
    return bad


def test_the_paper_pack_names_the_three_readings_verbatim() -> None:
    """a：M / G / H 三格（PAPER_PACK 的注册面）都读到三处真名。"""
    bad: list[str] = []
    for role in ROLES:
        text = _prompt(role)
        if "完成定义" not in text:
            bad.append(f"{role} 的提示词里没有「完成定义」那一段 ⇒ 这一条失去对象")
            continue
        bad += [f"{role}: {one}" for one in check(text)]
    assert bad == [], "\n".join(bad)


def test_putting_the_uppercase_constant_back_turns_it_red() -> None:
    """b-1：把 `MAPPING_NOT_WRITTEN`（常量名当读数名）回灌 ⇒ 必红。"""
    broken = _prompt("M") + "\n同类 blocker 还有 `MAPPING_NOT_WRITTEN` 等。"
    assert any("MAPPING_NOT_WRITTEN" in one for one in check(broken)), check(broken)


def test_putting_the_failed_verdict_back_turns_it_red() -> None:
    """b-2：把「回执不是它的 ⇒ `failed`」回灌 ⇒ 必红（实现是 drifted + 那一格 fail）。"""
    broken = _prompt("M") + "\n有正文而回执不是它的 ⇒ `failed`（`paper_pdf_is_stale`）。"
    assert any("回执不是它的" in one for one in check(broken)), check(broken)


def test_folding_the_two_blocker_kinds_back_turns_it_red() -> None:
    """b-3：把两类 blocker 混成「同类 blocker」⇒ 必红（格上/格外必须分开写）。"""
    broken = _prompt("G") + (
        "\n同类 blocker 还有 `acceptance_unmet` / `paper_pdf_is_stale` / "
        "`mapping_not_written` 等。")
    problems = check(broken)
    assert any("同类 blocker" in one for one in problems), problems

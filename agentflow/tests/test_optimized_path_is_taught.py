# -*- coding: utf-8 -*-
"""判据：M / E 手册里的「哪份证明还没洗过」要指到真路径，不许再写不存在的映射与前缀。

## 真身

- `evidencebits.optimized_state(row, proof_no)` 返回三态字符串 `"true"` / `"false"` /
  `"not_recorded"`；盘上那一格是 `bits.evidence.optimized_by_proof[proof_no]`（布尔）。
- `closing.statements_unoptimized_reading` 的顶层键只有 `checked` / `count` / `scanned` /
  `by_class` / `rows` / `problems` / `reason` —— 没有 `optimized` 这个顶层映射；逐份读数在
  `rows[*]` 里（每行带 `proof_no` 与三态 `optimized`）。

改前 M 手册写「第二阶段只看 `optimized[proof_no]`」、E 手册写「记下还没洗过（`optimized=false`）」：
前者把 `statements_unoptimized` 读成一个不存在的顶层映射，后者把三态字符串写成了布尔。

判据：a 两本手册都不再出现 `optimized[proof_no]` 与 `optimized=false`；b 真路径出现；
c 反真空：把旧句逐处回灌 ⇒ 红。
"""
from __future__ import annotations

import pathlib
import sys

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agentflow import agent_skills as AS  # noqa: E402

#: M 的收工手册与 E 的穷举手册。
M_SLUG = "收工-一份权威结论"
E_SLUG = "穷举证明-拿签与上报收养"

#: 改后必须逐字读到的真路径（M / E 两本都要有）。
REQUIRED: tuple[str, ...] = (
    "bits.evidence.optimized_by_proof[proof_no]",
)

#: M 的收工手册还要指到读数里逐份那一栏（`statements_unoptimized` 的顶层没有 optimized 映射）。
M_REQUIRED: tuple[str, ...] = (
    "statements_unoptimized.rows",
)

#: 改前那两种错写法。
STALE: tuple[str, ...] = (
    "optimized[proof_no]",
    "optimized=false",
)


def _body(role: str, slug: str) -> str:
    return next(skill for skill in AS.CATALOG[role] if skill.slug == slug).body


def check(text: str, extra: tuple[str, ...] = ()) -> list[str]:
    bad = [f"读不到 {needle!r}" for needle in REQUIRED + extra if needle not in text]
    bad += [f"仍写着旧写法 {needle!r}" for needle in STALE if needle in text]
    return bad


def test_m_manual_points_at_the_real_optimized_path() -> None:
    """a / b（M 面）：收工手册不再写 `optimized[proof_no]`，并指到两个真落点。"""
    body = _body("M", M_SLUG)
    assert len(body) > 1000, f"M 的收工手册只有 {len(body)} 字符 ⇒ 这一条没有落脚点"
    assert check(body, M_REQUIRED) == [], "\n".join(check(body, M_REQUIRED))


def test_e_manual_points_at_the_real_optimized_path() -> None:
    """a / b（E 面）：穷举手册不再把三态写成布尔 `optimized=false`。"""
    body = _body("E", E_SLUG)
    assert len(body) > 1000, f"E 的穷举手册只有 {len(body)} 字符 ⇒ 这一条没有落脚点"
    assert check(body) == [], "\n".join(check(body))


def test_putting_the_mapping_back_turns_the_m_manual_red() -> None:
    """c-1：把「第二阶段只看 `optimized[proof_no]`」回灌 ⇒ 必红。"""
    body = _body("M", M_SLUG) + "\n第二阶段只看 `optimized[proof_no]`。"
    problems = check(body)
    assert any("optimized[proof_no]" in one for one in problems), problems


def test_putting_the_boolean_back_turns_the_e_manual_red() -> None:
    """c-2：把「记下这份证明还没洗过（`optimized=false`）」回灌 ⇒ 必红。"""
    body = _body("E", E_SLUG) + "\n并记下这份证明还没洗过（`optimized=false`）。"
    problems = check(body)
    assert any("optimized=false" in one for one in problems), problems

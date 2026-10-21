"""S4 判据：T4 必须有"造梯子"的尝试记录（业主 2026-10-21）。

口径：「出现 T4 主要是要激励研究侧造梯子把非平凡性降下来」。
所以判的是"有没有去造"，不是"降到几档"：
* 有尝试（成了、没成、只写了一条 research_question 说缺哪个工具）⇒ 合格；
* 一点记录都没有 ⇒ 不合格。

三条判据：
1. T4 且 `research_questions`/`attack_plans` 都没有点名它 ⇒ 红；
2. 有一次尝试（哪怕写着"没成"）⇒ 绿（失败不许红：只看"试过没"）；
3. T1/T2/T3 不受这一条约束 ⇒ 绿（防误伤）。
"""

from __future__ import annotations

import json
import pathlib
import sys

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agentflow import closing, secretary as SEC  # noqa: E402


def _ws(tmp_path: pathlib.Path, level: int, questions: list[dict], plans: list[dict] | None = None) -> pathlib.Path:
    text = "the free group factor is a II_1 factor"
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    (tmp_path / "data" / "statements.json").write_text(
        json.dumps({"rows": [{"stmt_id": "000009", "statement_full": text, "proof_text": "proof"}]},
                   ensure_ascii=False), encoding="utf-8")
    (tmp_path / "data" / "research_questions.json").write_text(
        json.dumps({"rows": questions}, ensure_ascii=False), encoding="utf-8")
    (tmp_path / "data" / "attack_plans.json").write_text(
        json.dumps({"rows": plans or []}, ensure_ascii=False), encoding="utf-8")
    SEC.append_nontriviality(tmp_path, statement_full=text, level=level, basis="insight")
    return tmp_path


def test_a_t4_without_any_ladder_attempt_is_red(tmp_path: pathlib.Path) -> None:
    root = _ws(tmp_path, 4, questions=[{"question": "unrelated question"}])
    problems = closing.t4_ladder_problems(root)
    assert problems and "造梯子" in problems[0], problems


def test_a_failed_attempt_still_counts_as_an_attempt(tmp_path: pathlib.Path) -> None:
    """第 2 条：尝试失败也合格（只看"试过没"，不看"成没成"）。"""
    root = _ws(tmp_path, 4, questions=[{"question": "000009", "notes": "we could not build the tool"}])
    assert closing.t4_ladder_problems(root) == []


def test_an_attempt_recorded_in_attack_plans_also_counts(tmp_path: pathlib.Path) -> None:
    root = _ws(tmp_path, 4, questions=[], plans=[{"goal": "build a ladder for the free group factor is a II_1 factor"}])
    assert closing.t4_ladder_problems(root) == []


def test_low_tiers_are_not_constrained(tmp_path: pathlib.Path) -> None:
    """第 3 条（防误伤）：T1/T2/T3 不要求任何造梯子记录。"""
    for level in (1, 2, 3):
        root = _ws(tmp_path / f"ws{level}", level, questions=[])
        assert closing.t4_ladder_problems(root) == [], f"T{level} 被误伤"

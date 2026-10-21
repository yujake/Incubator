"""S1 判据：B 的秘书在"这条命题够不够格"的那一趟判断里，**同时**给出非平凡性档位。

## 为什么这条判据存在

业主 2026-10-21 定的四档（`secretary.NONTRIVIALITY_LEVELS`）：1 刚过收录门槛 / 2 方法平凡但体量大 /
3 需较多技巧或跨领域工具 / 4 天才洞察或极长思维链或偏离主流的构造。它回答的是**"多不平凡"**，
与 `STATEMENT_VERDICTS`（"收不收"）**是两根轴** —— 把两根轴折进同一栏是查不出来的那种错。

## 判据钉的四件事

1. **同一趟判断给两个输出**：判了 ⇒ `decision` 与 `nontriviality` 都在，且档位在 1–4；
2. **判不了 ≠ 第 1 档**：`nontriviality=0` 时必须同时 `nontriviality_tri="unjudged"` ——
   三态纪律：没查成不许读成"刚过门槛"；
3. **读数落盘可查**：`append_nontriviality` 写的旁支台账能被 `nontriviality_of` 折叠回来，
   且**后写的覆盖先写的**（降档/升档都要留痕：读到的永远是最后一行，但历史行不删）；
4. **不许自己解析台账**：`nontriviality_of` 是唯一读口（这条钉的是"只有一个读函数"）。

## 反真空

第 3 条的两个负控：① 没有台账 ⇒ `unknown`（不是 1）；② 台账里有别人的 sha ⇒ 也是 `unknown`。
没有这两条，"折叠读回来"可以靠"什么都返回 1"实现。
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import sys

import pytest

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agentflow import secretary as SEC  # noqa: E402


def test_the_four_levels_are_declared_with_the_owner_semantics() -> None:
    """四档的**语义**是业主原话，不是随手写的 1..4；且 0 不在档位里（它是"判不了"）。"""
    assert SEC.NONTRIVIALITY_LEVELS == (1, 2, 3, 4)
    doc = SEC.NONTRIVIALITY_LEVELS.__doc__ if hasattr(SEC.NONTRIVIALITY_LEVELS, "__doc__") else ""
    src_text = pathlib.Path(SEC.__file__).read_text(encoding="utf-8")
    for phrase in ("刚过 B 侧的收录门槛", "工作量较大", "跨领域工具", "天才般的洞察力"):
        assert phrase in src_text, f"四档的语义丢了这一条：{phrase!r}"
    assert "0" not in dict.fromkeys(SEC.NONTRIVIALITY_LEVELS)


def test_the_level_is_normalised_and_never_falls_back_to_one() -> None:
    """① 1–4 原样；② 其它输入一律 0 —— **绝不回落到 1**（那是把"没判"读成"刚过门槛"）。"""
    assert [SEC._nontriviality_level(v) for v in (1, 2, 3, 4)] == [1, 2, 3, 4]
    assert [SEC._nontriviality_level(v) for v in (0, 5, -1, None, "", "abc", 1.9)] == [0, 0, 0, 0, 0, 0, 0]
    assert SEC._nontriviality_level("3") == 3


def test_the_ledger_round_trips_and_the_last_row_wins(tmp_path: pathlib.Path) -> None:
    """③ 落盘 ⇒ 读回来；**后写的覆盖先写的**（降档要留痕：最后一行生效，历史行不删）。"""
    root = tmp_path
    first = "命题：自由群因子是 II_1 型因子。"
    other = "另一条：Witt 代数的 U(g) 是否 Noetherian。"
    SEC.append_nontriviality(root, statement_full=first, level=4, basis="需要洞察", role="B", task_id="t-1")
    SEC.append_nontriviality(root, statement_full=other, level=2, basis="体量大", role="B", task_id="t-1")
    got = SEC.nontriviality_of(root, first)
    assert (got["tri"], got["level"], got["basis"]) == ("computed", 4, "需要洞察")
    # 造梯子之后降档：最后一行生效，但台账里两行都在
    SEC.append_nontriviality(root, statement_full=first, level=2, basis="造出工具后降档", role="B")
    got = SEC.nontriviality_of(root, first)
    assert (got["level"], got["basis"]) == (2, "造出工具后降档")
    lines = [ln for ln in SEC.nontriviality_path(root).read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) == 3, f"历史行被改写了（应保留 3 行）：{lines}"
    # 换行必须是 LF（Windows 上文本模式会写 CRLF，那是我们踩过的坑）
    assert b"\r\n" not in SEC.nontriviality_path(root).read_bytes()


def test_unknown_is_not_the_first_level(tmp_path: pathlib.Path) -> None:
    """反真空：没有台账 / 台账里没有这一条 ⇒ `unknown` 且 level=0（**不是 1**）。"""
    missing = SEC.nontriviality_of(tmp_path, "任何命题")
    assert missing["tri"] == "unknown" and missing["level"] == 0
    SEC.append_nontriviality(tmp_path, statement_full="别人的命题", level=3, basis="x")
    other = SEC.nontriviality_of(tmp_path, "我的命题")
    assert other["tri"] == "unknown" and other["level"] == 0


def test_the_tier_travels_on_the_same_judge_call_not_a_second_one(tmp_path: pathlib.Path) -> None:
    """①+②：`judge_statement` 在**同一次**判断里给出两栏；判了却没给档位 ⇒ 0 且 `unjudged`。"""
    calls: list[str] = []

    def fake_judge(kind: str, context, *, task_id: str = ""):
        calls.append(kind)
        payload = {"checked": True, "decision": "合格", "reason": "有使用者", "basis": ["step 3"]}
        payload.update(fake_judge.extra)  # type: ignore[attr-defined]
        return payload

    fake_judge.extra = {"nontriviality": 3, "nontriviality_basis": "用了跨领域工具"}
    boss = SEC.Secretary(role="B", root=tmp_path)
    boss.judge = fake_judge  # type: ignore[assignment]
    got = boss.judge_statement(statement_full="命题甲", task_id="t-9")
    assert calls == ["statement_aesthetic"], f"只该发一次判断，实际 {calls}"
    assert got["decision"] == "合格"
    assert (got["nontriviality"], got["nontriviality_tri"]) == (3, "computed")
    assert SEC.nontriviality_of(tmp_path, "命题甲")["level"] == 3

    # 判了但没给档位 ⇒ 0 + unjudged（不许当 1）
    fake_judge.extra = {}
    got = boss.judge_statement(statement_full="命题乙", task_id="t-9")
    assert (got["nontriviality"], got["nontriviality_tri"]) == (0, "unjudged")
    assert SEC.nontriviality_of(tmp_path, "命题乙")["tri"] == "unknown"

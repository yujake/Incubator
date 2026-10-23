"""S1 判据：B 的秘书在"这条命题够不够格"的那一趟判断里，同时给出非平凡性档位。

## 为什么这条判据存在

业主 2026-10-21 定的档位、2026-10-23 补了 T0（`secretary.NONTRIVIALITY_LEVELS`）：
0 = 基础定理或初步结论 / 1 = 有一定价值的非平凡结论 / 2 = 方法平凡但体量大 /
3 = 需较多技巧或跨领域工具 / 4 = 天才洞察、极长思维链或偏离主流的构造。
它回答的是"多不平凡"，与 `STATEMENT_VERDICTS`（"收不收"）是两根轴 ——
把两根轴折进同一栏是查不出来的那种错。

## 判据钉的五件事

1. 同一趟判断给两个输出：判了 ⇒ `decision` 与 `nontriviality` 都在，档位在 0–4；
2. 判不了 ≠ 第 0 档（更不是第 1 档）：`nontriviality` 是 `None` 时必须同时
   `nontriviality_tri="unjudged"` —— 三态纪律：没查成不许读成"基础定理"；
3. 判「太平凡」⇒ 档位就地落 0（业主 2026-10-23：平凡 ⇒ 落 T0，不再拒收），
   秘书自己报的档位在那一支上不算数；
4. 读数落盘可查：`append_nontriviality` 写的旁支台账能被 `nontriviality_of` 折叠回来，
   且后写的覆盖先写的（降档/升档都要留痕：读到的永远是最后一行，但历史行不删）；
5. 不许自己解析台账：`nontriviality_of` 是唯一读口（这条钉的是"只有一个读函数"）。

## 反真空

- 没有台账 ⇒ `unknown`（不是 0、也不是 1）；台账里有别人的 sha ⇒ 也是 `unknown`；
- 旧刻度的 `nontriviality: 0`（那时 0 = 判不了）⇒ 仍读成 `unknown`，
  绝不能被读成 T0（迁移守卫，判据在 `test_t0_tier_and_exhaustion_proof.py` 里另有一条）。
"""

from __future__ import annotations

import importlib
import json
import pathlib
import sys

import pytest

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agentflow import secretary as SEC  # noqa: E402


def _sec():
    return importlib.import_module("agentflow.secretary")


def test_the_five_levels_are_declared_with_the_owner_semantics() -> None:
    """五档的语义是业主原话，不是随手写的 0..4；判不了不在档位里（它是 None）。"""
    assert SEC.NONTRIVIALITY_LEVELS == (0, 1, 2, 3, 4)
    src_text = pathlib.Path(SEC.__file__).read_text(encoding="utf-8")
    for phrase in ("基础定理或初步结论", "有一定价值的非平凡结论",
                   "工作量较大", "跨领域工具", "天才般的洞察力"):
        assert phrase in src_text, f"五档的语义丢了这一条：{phrase!r}"
    assert SEC.NONTRIVIALITY_UNJUDGED is None
    assert None not in SEC.NONTRIVIALITY_LEVELS


def test_the_level_is_normalised_and_never_falls_back_to_a_tier() -> None:
    """① 0–4 原样；② 其它输入一律 None —— 绝不回落到 1（那会把"没判"读成"有价值"）。"""
    assert [SEC._nontriviality_level(v) for v in (0, 1, 2, 3, 4)] == [0, 1, 2, 3, 4]
    assert [SEC._nontriviality_level(v) for v in (5, -1, None, "", "abc", 1.9, True)] == \
        [None, None, None, None, None, None, None]
    assert SEC._nontriviality_level("3") == 3
    assert SEC._nontriviality_level("0") == 0


def test_the_ledger_round_trips_and_the_last_row_wins(tmp_path: pathlib.Path) -> None:
    """③ 落盘 ⇒ 读回来；后写的覆盖先写的（降档要留痕：最后一行生效，历史行不删）。"""
    root = tmp_path
    first = "命题：自由群因子是 II_1 型因子。"
    other = "另一条：Witt 代数的 U(g) 是否 Noetherian。"
    SEC.append_nontriviality(root, statement_full=first, level=4, basis="需要洞察", role="B", task_id="t-1")
    SEC.append_nontriviality(root, statement_full=other, level=2, basis="体量大", role="B", task_id="t-1")
    got = SEC.nontriviality_of(root, first)
    assert (got["tri"], got["level"], got["label"], got["basis"]) == ("computed", 4, "T4", "需要洞察")
    # 造梯子之后降档：最后一行生效，但台账里两行都在
    SEC.append_nontriviality(root, statement_full=first, level=2, basis="造出工具后降档", role="B")
    got = SEC.nontriviality_of(root, first)
    assert (got["level"], got["label"], got["basis"]) == (2, "T2", "造出工具后降档")
    lines = [ln for ln in SEC.nontriviality_path(root).read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) == 3, f"历史行被改写了（应保留 3 行）：{lines}"
    # 换行必须是 LF（Windows 上文本模式会写 CRLF，那是我们踩过的坑）
    assert b"\r\n" not in SEC.nontriviality_path(root).read_bytes()


def test_t0_round_trips_and_is_not_unjudged(tmp_path: pathlib.Path) -> None:
    """T0 是一档真的档位：`0` 存进去、读回来是 `T0`（不是"判不了"）。"""
    SEC.append_nontriviality(tmp_path, statement_full="a+b=b+a 在交换环里成立", level=0,
                             basis="平凡但真", role="B")
    got = SEC.nontriviality_of(tmp_path, "a+b=b+a 在交换环里成立")
    assert (got["tri"], got["level"], got["label"]) == ("computed", 0, "T0"), got
    # 而判不了是另一行、另一个结局（同一根轴上的第三态）
    SEC.append_nontriviality(tmp_path, statement_full="判不了的那条", level=None, basis="材料不足")
    bad = SEC.nontriviality_of(tmp_path, "判不了的那条")
    assert (bad["tri"], bad["level"]) == ("unknown", None), bad


def test_unknown_is_not_a_tier(tmp_path: pathlib.Path) -> None:
    """反真空：没有台账 / 台账里没有这一条 ⇒ `unknown` 且 level=None（不是 0、不是 1）。"""
    missing = SEC.nontriviality_of(tmp_path, "任何命题")
    assert missing["tri"] == "unknown" and missing["level"] is None
    SEC.append_nontriviality(tmp_path, statement_full="别人的命题", level=3, basis="x")
    other = SEC.nontriviality_of(tmp_path, "我的命题")
    assert other["tri"] == "unknown" and other["level"] is None


def test_the_tier_travels_on_the_same_judge_call_not_a_second_one(tmp_path: pathlib.Path) -> None:
    """①+②：`judge_statement` 在同一次判断里给出两栏；判了却没给档位 ⇒ None 且 `unjudged`。"""
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

    # 判了但没给档位 ⇒ None + unjudged（不许当 1，也不许当 0）
    fake_judge.extra = {}
    got = boss.judge_statement(statement_full="命题乙", task_id="t-9")
    assert (got["nontriviality"], got["nontriviality_tri"]) == (None, "unjudged")
    assert SEC.nontriviality_of(tmp_path, "命题乙")["tri"] == "unknown"


def test_a_trivial_verdict_forces_t0_on_the_same_call(tmp_path: pathlib.Path) -> None:
    """③ 判「太平凡」⇒ 档位就地落 0（T0），秘书自报的 3 档在那一支上不算数。

    业主 2026-10-23：平凡 ⇒ 落 T0，不再拒收。所以"平凡"与"档位"这两栏必须一致：
    判平凡却把档位记成 3，会让下游按 3 去读它，而收录口那边又按平凡放行。
    """

    def fake_judge(kind: str, context, *, task_id: str = ""):
        return {"checked": True, "decision": "太平凡", "reason": "两条判据都答不上",
                "basis": ["没有使用者"], "nontriviality": 3,
                "nontriviality_basis": "自报三档"}

    boss = SEC.Secretary(role="B", root=tmp_path)
    boss.judge = fake_judge  # type: ignore[assignment]
    got = boss.judge_statement(statement_full="a+b=b+a", task_id="t-9")
    assert (got["nontriviality"], got["nontriviality_tri"]) == (0, "computed"), got
    assert got["label"] == "T0", got
    assert "降为 T0" in got["nontriviality_basis"], got["nontriviality_basis"]
    assert SEC.nontriviality_of(tmp_path, "a+b=b+a")["level"] == 0


def test_the_judge_layer_still_carries_the_tier_field(tmp_path: pathlib.Path) -> None:
    """回归：`judge()` 这一层不许把模型给的档位丢掉（改前它只白名单了四格）。

    真机读数（r34 的 `out/secretary/nontriviality.jsonl`）：5 行全是
    `nontriviality: 0` / `basis: ""` —— 那正是"模型给了档位、这一层丢了"的形态，
    而它与"没人判过"在盘上同形。
    """

    class _Seam:
        def ask_json(self, prompt, **kw):
            import types

            return ({"decision": "合格", "reason": "有用", "basis": ["L3"],
                     "nontriviality": 2, "nontriviality_basis": "方法平凡但体量大"},
                    types.SimpleNamespace(ok=True, problem="", detail=""))

    boss = SEC.Secretary(role="B", root=tmp_path, seam=_Seam(), enable_model=True)
    got = boss.judge("statement_aesthetic", {"statement_full": "x"})
    assert got.get("nontriviality") == 2, got
    assert got.get("nontriviality_basis") == "方法平凡但体量大", got

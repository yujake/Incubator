# -*- coding: utf-8 -*-
"""判据：判档那一问的词表只剩 T0–T4；「判不了」是一个空位，不是第六个词。

## 业主裁定（2026-11-01，逐字）

> 「审美轴三格（合格 / 太平凡 / 判不了）是 T0 到 T4 的老设计，可以退场了，直接只用 T0 到 T4」

2026-11-01 之前 `STATEMENT_VERDICTS = ("合格", "太平凡", "判不了")` 是"收不收"的审美轴，
与 `NONTRIVIALITY_LEVELS`（"多不平凡"）并排。裁定之后这一问只剩一根轴：

- `decision` **就是档位**：`"T0"`…`"T4"`；
- 「判不了」= **这个字段的空位**（`decision` 键在、值是 JSON `null`），
  由 `checked=True` + `nontriviality=None` + `nontriviality_tri="unjudged"` 三格说清；
- 「调用失败」= `checked=False`（没缝 / 超时 / 坏 JSON / 词表外），台账那一行写 `没查成`。
  **这两件事不许混**：前者是"判过了、判不出档"，后者是"这一趟没查成"。

## 这一组钉五条

1. 词表从档位轴派生（`tuple(nontriviality_label(i) for i in NONTRIVIALITY_LEVELS)`），
   `JUDGE_VERDICTS["statement_aesthetic"]` 就是它，三个旧词一个都不在；
2. 判档那一问的题面与材料里**零命中**三个旧词（材料用超限 context 触发截断注那一支）；
3. 源码里"恰好等于"旧词的字符串常量只许出现在 `legacy_row_tier` 一个函数里
   （它是**读旧行**的唯一折算口；写侧与新行一个字都不产生它们）；
4. 反真空：把词表 monkeypatch 回三格 ⇒ 第 2 条的检查必须红（证明它真的在读词表）；
5. 盘上三态可分：T1 / null（判不了）/ 旧词（不采信）/ 调用失败（没查成）四笔各自落成
   不同的行 —— 尤其 `judge.checked` 在"判不了"与"没查成"上必须不同。

## 反真空

不调模型：全部用假缝（直接替换 `seam.ask_json`）。每条都断言盘上的那一行。
"""
from __future__ import annotations

import ast
import json
import pathlib
import types

import pytest

from agentflow import secretary as SEC

OLD = ("合格", "太平凡", "判不了")
STATEMENT = "命题：任意有限群 G 的 Sylow p-子群两两共轭。"
PROOF = "证明：先取一个 Sylow p-子群 P，再对任一 Q 用轨道计数与共轭作用证明 |G:N_G(P)| ≡ 1 mod p。∎"


class _Seam:
    """假缝：回一份预置 JSON，或直接抛异常（零模型调用）。"""

    def __init__(self, reply: dict | None = None, *, boom: bool = False) -> None:
        self.reply = dict(reply or {})
        self.boom = boom

    def ask_json(self, prompt, **kw):
        if self.boom:
            raise TimeoutError("假缝：超时")
        return dict(self.reply), types.SimpleNamespace(ok=True, problem="", detail="")


def _judge(tmp_path: pathlib.Path, seam: _Seam):
    boss = SEC.Secretary(role="B", root=tmp_path, seam=seam, enable_model=True)
    return boss.judge_statement(statement_full=STATEMENT, proof_text=PROOF,
                                task_id="t-000001")


def _tier_rows(tmp_path: pathlib.Path) -> list[dict]:
    path = SEC.nontriviality_path(tmp_path)
    if not path.is_file():
        return []
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def _decision_rows(tmp_path: pathlib.Path) -> list[dict]:
    path = SEC.decisions_path(tmp_path, "B")
    if not path.is_file():
        return []
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


# ---------------------------------------------------------------- ① 词表
def test_the_vocabulary_is_derived_from_the_tier_axis() -> None:
    """① 词表 = 档位轴的显示名；三个旧词一个都不在，且与 JUDGE_VERDICTS 是同一张表。"""
    want = tuple(SEC.nontriviality_label(level) for level in SEC.NONTRIVIALITY_LEVELS)
    assert want == ("T0", "T1", "T2", "T3", "T4"), want
    assert SEC.STATEMENT_VERDICTS == want, SEC.STATEMENT_VERDICTS
    assert SEC.JUDGE_VERDICTS["statement_aesthetic"] is SEC.STATEMENT_VERDICTS
    assert [w for w in OLD if w in SEC.STATEMENT_VERDICTS] == []


# ---------------------------------------------------------------- ② 题面
def test_the_prompt_offers_no_retired_word() -> None:
    """② 题面（system）与截断注（user）里都不许再出现那三个词。"""
    head = SEC._judge_system("statement_aesthetic")
    assert [w for w in OLD if w in head] == [], head
    big = SEC._judge_material({"statement_full": "x" * (SEC.JUDGE_MATERIAL_CAP + 10),
                               "proofs": [], "effort": {}})
    assert "截断" in big, "超限的材料没有触发截断注 ⇒ 这一支没测到"
    assert [w for w in OLD if w in big] == [], big[:800]
    # 三态的说法必须在题面里：null 是唯一允许的非档位取值。
    assert "null" in head, head[:600]


# ---------------------------------------------------------------- ③ 只许一处
def test_the_old_words_survive_only_in_the_legacy_row_reader() -> None:
    """③ 源码里恰好等于旧词的字符串常量，只许落在 `legacy_row_tier` 的区间内。"""
    tree = ast.parse(pathlib.Path(SEC.__file__).read_text(encoding="utf-8"))
    readers = [n for n in ast.walk(tree)
               if isinstance(n, ast.FunctionDef) and n.name == "legacy_row_tier"]
    assert len(readers) == 1, f"读旧行的折算口应当只有一处：{[n.name for n in readers]}"
    lo, hi = readers[0].lineno, readers[0].end_lineno
    outside = [f"{n.lineno}:{n.value!r}" for n in ast.walk(tree)
               if isinstance(n, ast.Constant) and isinstance(n.value, str)
               and n.value in OLD and not (lo <= n.lineno <= hi)]
    assert outside == [], (
        "旧词作为词表取值又出现在别处（写侧/题面/闸门）—— 它们只许在 legacy_row_tier 里被折算：\n  "
        + "\n  ".join(outside))
    # 反真空：那个函数真的在、真的能折算（不是把词删光换一个空函数）。
    assert SEC.legacy_row_tier({"decision": "太平凡"}) == 0
    assert SEC.legacy_row_tier({"decision": "合格",
                                "judge": {"nontriviality": 2}}) == 2
    assert SEC.legacy_row_tier({"decision": "判不了"}) is None
    assert SEC.legacy_row_tier({"decision": "T3"}) == 3


# ---------------------------------------------------------------- ④ 反真空
def test_a_retired_vocabulary_put_back_makes_the_prompt_check_red(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """④ 把词表 monkeypatch 回三格 ⇒ 题面立刻重新带出旧词，② 的检查必须看得见。"""
    monkeypatch.setitem(SEC.JUDGE_VERDICTS, "statement_aesthetic", OLD)
    head = SEC._judge_system("statement_aesthetic")
    assert [w for w in OLD if w in head], (
        "词表换回三格之后题面里仍然一个旧词都没有 ⇒ ② 那条检查没有在读词表")


# ---------------------------------------------------------------- ⑤ 盘上三态
def test_the_three_states_are_distinguishable_on_disk(tmp_path: pathlib.Path) -> None:
    """⑤ T1 / null / 旧词 / 调用失败 四笔各自落成不同的行；判不了与没查成的 checked 不同。"""
    # (a) 档位：decision="T1" ⇒ 1 / T1
    ok_dir = tmp_path / "ok"
    got = _judge(ok_dir, _Seam({"decision": "T1", "reason": "有一定价值"}))
    assert (got["checked"], got["decision"], got["nontriviality"]) == (True, "T1", 1), got
    assert _tier_rows(ok_dir)[0]["nontriviality"] == 1
    assert _decision_rows(ok_dir)[0]["decision"] == "T1"

    # (b) 判不了：decision=null ⇒ checked=True、nontriviality=None、台账那一行没有 decision 键
    null_dir = tmp_path / "null"
    got = _judge(null_dir, _Seam({"decision": None, "reason": "正文被截断，定不了档"}))
    assert got["checked"] is True and got["nontriviality"] is None, got
    assert got["nontriviality_tri"] == "unjudged", got
    tier_row = _tier_rows(null_dir)[0]
    assert tier_row["nontriviality"] is None, tier_row
    decision_row = _decision_rows(null_dir)[0]
    assert decision_row["judge"]["checked"] is True, decision_row
    assert "decision" not in decision_row, decision_row

    # (c) 旧词：不采信（写侧不再接受它），且落成"没查成"而不是悄悄折成某一档
    old_dir = tmp_path / "old"
    got = _judge(old_dir, _Seam({"decision": "合格", "reason": "收"}))
    assert got["checked"] is False, got
    assert _tier_rows(old_dir) == [], "旧词被折成了档位（写侧还在接受退场的词）"
    assert _decision_rows(old_dir)[0]["decision"] == SEC.JUDGE_UNCHECKED

    # (d) 调用失败：checked=False、台账"没查成"、没有档位行
    fail_dir = tmp_path / "fail"
    got = _judge(fail_dir, _Seam(boom=True))
    assert got["checked"] is False, got
    assert _tier_rows(fail_dir) == []
    assert _decision_rows(fail_dir)[0]["decision"] == SEC.JUDGE_UNCHECKED

    # (e) 最关键的一条：判不了 与 调用失败 **不是**同一格
    assert decision_row["judge"]["checked"] is True
    assert _decision_rows(fail_dir)[0]["judge"]["checked"] is False
    assert decision_row["judge"]["checked"] != _decision_rows(fail_dir)[0]["judge"]["checked"]

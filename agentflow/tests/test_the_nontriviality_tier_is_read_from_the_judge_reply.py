# -*- coding: utf-8 -*-
"""判据：档位要从判词里真正读出来（decision 与 nontriviality 两个键都认）。

## 真 bug（2026-11-01，真机 82 的 48 行台账）

`_judge_system` 的 `statement_aesthetic` 题面（2026-10-29 起）要求模型：

```
decision 取 T0/T1/T2/T3/T4 之一；reason 一句话；basis 写清你凭什么
```

题面从来没要求 `nontriviality` 这一格。而读侧（`judge_statement`）此前只做：

```
model_level = _nontriviality_level(got.get("nontriviality"))
```

⇒ 模型照题面答的 `decision="T1"` 永远读不到，台账里 48/48 全是
`nontriviality: null`。兜底那句话还反过来猜"没接模型 / 没开 model / 回不了解析"——
三个猜测一个都不成立（接了模型、开了 model、解析也成功），真实原因是读侧读了另一个键。

## 这一组守什么（①–⑤ 是任务书点名的五条，⑥ 是同一缺陷链上的词表闸）

1. 假秘书回 `{"decision":"T1",...}` ⇒ 台账 `nontriviality=1` / `label="T1"`；
2. 老形状 `{"nontriviality":2}` ⇒ 仍落 2（向后兼容，改前已绿，这一条是回归钉）；
3. 两个键都缺 ⇒ 未判，且兜底 basis 点名缺字段，不再说"没接模型 / 没开 model / 回不了解析"；
4. 坏输入 `{"decision":"T9"}` ⇒ 未判（不折档、更不许折成 0）；
5. 两个键冲突 `{"decision":"T1","nontriviality":3}` ⇒ 以显式字段 `nontriviality` 为准（3），
   并在 basis 里留痕。理由：`decision` 那一格同时是审美轴的词（合格 / 太平凡 / 判不了），
   只有它恰好是可解析档位时才当档位读；`nontriviality` 是专门的档位字段（老形状、
   替身、历史台账都用它），冲突时它的语义更窄、更不容易被误读。
6. 词表闸：模型照题面把 `decision` 答成 `"T1"` 时，`judge()` 这一层不许判成
   "词表外 ⇒ 不采信"（否则读侧修复在生产上一个字节都到不了：checked=False 时
   `judge_statement` 根本不落台账）。

## 反真空

本组用假秘书（直接替换 `judge`，不调模型），每个用例都断言盘上那一行；
"未判"必须是 `None`，不许是 0 —— 0 是 T0（基础定理或初步结论），是一档真的档位。
"""

from __future__ import annotations

import json
import types

import pytest

from agentflow import secretary as SEC

STATEMENT = "命题：任意有限群 G 的 Sylow p-子群两两共轭。"
PROOF = "证明：先取一个 Sylow p-子群 P，再对任一 Q 用轨道计数与共轭作用证明 |G:N_G(P)| ≡ 1 mod p。∎"


def _judge_with(tmp_path, reply: dict):
    """造一个假秘书：`judge` 直接回 `reply`（不接模型、不花钱）。"""
    boss = SEC.Secretary(role="B", root=tmp_path)

    def fake_judge(kind: str, context, *, task_id: str = ""):
        return {"checked": True, "reason": "按五档判过", "basis": ["证明正文里的承重步骤"],
                **reply}

    boss.judge = fake_judge  # type: ignore[assignment]
    got = boss.judge_statement(statement_full=STATEMENT, proof_text=PROOF, task_id="t-000001")
    return got


def _ledger(tmp_path) -> list[dict]:
    path = SEC.nontriviality_path(tmp_path)
    assert path.exists(), f"档位台账没有落盘：{path}"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def test_a_tier_in_decision_reaches_the_ledger(tmp_path) -> None:
    """① 题面要求的形状：decision="T1" ⇒ 台账 1 / T1。"""
    got = _judge_with(tmp_path, {"decision": "T1", "reason": "有一定价值的非平凡结论"})
    assert (got["nontriviality"], got["label"], got["nontriviality_tri"]) == (1, "T1", "computed"), got
    rows = _ledger(tmp_path)
    assert len(rows) == 1, rows
    assert (rows[0]["nontriviality"], rows[0]["label"]) == (1, "T1"), rows[0]


def test_the_old_shape_still_works(tmp_path) -> None:
    """② 向后兼容：老形状（只给 nontriviality）照旧落 2。"""
    got = _judge_with(tmp_path, {"decision": "合格", "nontriviality": 2})
    assert (got["nontriviality"], got["label"]) == (2, "T2"), got
    rows = _ledger(tmp_path)
    assert (rows[0]["nontriviality"], rows[0]["label"]) == (2, "T2"), rows[0]


def test_without_a_tier_the_basis_names_the_missing_field(tmp_path) -> None:
    """③ 两键都缺 ⇒ 未判，且兜底措辞点名缺字段（不再猜"没接模型/没开 model/回不了解析"）。"""
    got = _judge_with(tmp_path, {"decision": "合格", "reason": "没问题"})
    assert got["nontriviality"] is None, got
    assert got["nontriviality_tri"] == "unjudged", got
    basis = str(got.get("nontriviality_basis") or "")
    assert "缺字段" in basis, basis
    for lie in ("没接模型", "没开 model", "回不了解析"):
        assert lie not in basis, f"兜底措辞还在猜「{lie}」：{basis}"
    rows = _ledger(tmp_path)
    assert rows[0]["nontriviality"] is None, rows[0]


def test_a_bad_tier_is_unjudged_not_t0(tmp_path) -> None:
    """④ 坏输入（T9）⇒ 未判；不许折成某一档，尤其不许折成 0（那是 T0）。"""
    got = _judge_with(tmp_path, {"decision": "T9"})
    assert got["nontriviality"] is None, got
    assert got["nontriviality_tri"] == "unjudged", got
    # 坏输入不是"没给字段"：兜底那句话照样要点名 decision 里不是 T0–T4。
    assert "缺字段" in str(got.get("nontriviality_basis") or ""), got
    rows = _ledger(tmp_path)
    assert rows[0]["nontriviality"] is None, rows[0]


def test_the_explicit_field_wins_a_conflict_and_leaves_a_trace(tmp_path) -> None:
    """⑤ 冲突 ⇒ 以 `nontriviality` 为准，并在 basis 里写清（口径见模块 docstring）。"""
    got = _judge_with(tmp_path, {"decision": "T1", "nontriviality": 3})
    assert (got["nontriviality"], got["label"]) == (3, "T3"), got
    basis = str(got.get("nontriviality_basis") or "")
    assert "冲突" in basis and "nontriviality" in basis, basis
    rows = _ledger(tmp_path)
    assert (rows[0]["nontriviality"], rows[0]["label"]) == (3, "T3"), rows[0]


def test_the_judge_vocabulary_gate_accepts_a_tier_decision(tmp_path) -> None:
    """⑥ 模型照题面答 decision="T1" ⇒ `judge()` 采信，并把它作为第二输出带下去。

    改前这一层按 `STATEMENT_VERDICTS`（合格/太平凡/判不了）校验 ⇒ T1 被拒成
    `checked=False`，`judge_statement` 连台账那一行都不会落 —— 读侧的修复在生产上
    永远走不到。这里是同一缺陷链的另一半。
    """

    class _Seam:
        def ask_json(self, prompt, **kw):
            return ({"decision": "T1", "reason": "按五档属 T1", "basis": ["第 3 步"]},
                    types.SimpleNamespace(ok=True, problem="", detail=""))

    boss = SEC.Secretary(role="B", root=tmp_path, seam=_Seam(), enable_model=True)
    got = boss.judge("statement_aesthetic", {"statement_full": "x"})
    assert got["checked"] is True, got
    assert got["nontriviality"] == 1, got
    assert got["decision"] == "合格", f"档位与审美轴两根轴都要留：{got}"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))

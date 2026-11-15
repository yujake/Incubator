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
    """造一个假秘书：`judge` 直接回 `reply`（不接模型、不花钱），再按新口径落一行。

    NT2（2026-11-15）之后 `judge_statement` 只判、不写盘：要读台账就得显式
    `record_nontriviality`（带号与路径号）—— 这一句同时钉住"判/落拆段"的落点。
    """
    boss = SEC.Secretary(role="B", root=tmp_path)

    def fake_judge(kind: str, context, *, task_id: str = ""):
        return {"checked": True, "reason": "按五档判过", "basis": ["证明正文里的承重步骤"],
                **reply}

    boss.judge = fake_judge  # type: ignore[assignment]
    got = boss.judge_statement(statement_full=STATEMENT, proof_text=PROOF, task_id="t-000001")
    if got.get("nontriviality_tri") in ("computed", "not_applicable"):
        boss.record_nontriviality(got, stmt_id="000001", path_group=1,
                                  statement_full=STATEMENT,
                                  judged_body_sha256=SEC._judged_body_sha(STATEMENT, PROOF))
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


def test_a_reply_without_a_tier_is_unchecked(tmp_path) -> None:
    """③ 判词里没有档位 ⇒ 这一格没查成（checked=False），不落一条'未判'的行。

    2026-11-01（第二刀）之前这里会落一条 `nontriviality: null` 的行；那会让
    "没拿到判定"在盘上冒充"判过了但没档"。现在它只长成 `checked=False` + reason。
    """
    got = _judge_with(tmp_path, {"decision": "合格", "reason": "没问题"})
    assert got["checked"] is False, got
    assert got["nontriviality"] is None, got
    assert "没查成" in str(got.get("reason") or ""), got
    assert not SEC.nontriviality_path(tmp_path).exists(), "没拿到判定却落了一条档位行"


def test_a_bad_tier_is_unchecked_not_t0(tmp_path) -> None:
    """④ 坏输入（T9）⇒ 没查成；不许折成某一档，尤其不许折成 0（那是 T0）。"""
    got = _judge_with(tmp_path, {"decision": "T9"})
    assert got["checked"] is False, got
    assert got["nontriviality"] is None, got
    assert "T9" in str(got.get("reason") or ""), got
    assert not SEC.nontriviality_path(tmp_path).exists(), "坏输入却落了一条档位行"


def test_decision_wins_over_the_legacy_alias(tmp_path) -> None:
    """⑤ 一根轴：decision 能解析时它就是档位，旧字段 `nontriviality` 不再参与。

    2026-11-01 之前是"两字段两轴"，冲突时显式字段优先；裁定把审美轴三格退场之后
    `decision` 是唯一的主字段 —— 旧字段只剩"decision 读不出来时的别名"这一层。
    """
    got = _judge_with(tmp_path, {"decision": "T1", "nontriviality": 3})
    assert (got["nontriviality"], got["label"]) == (1, "T1"), got
    rows = _ledger(tmp_path)
    assert (rows[0]["nontriviality"], rows[0]["label"]) == (1, "T1"), rows[0]


def test_the_judge_vocabulary_gate_accepts_a_tier_decision(tmp_path) -> None:
    """⑥ 模型照题面答 decision="T1" ⇒ `judge()` 采信，decision 就是 "T1"。

    改前这一层按 `STATEMENT_VERDICTS`（三格旧词）校验 ⇒ T1 被拒成
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
    assert got["decision"] == "T1", f"decision 就是档位（一根轴一个字段）：{got}"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))

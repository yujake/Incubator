# -*- coding: utf-8 -*-
"""判据：档位单独占一格（nontriviality），decision 只走审美轴三格。

## 真病根（2026-11-01 裁定）

抬头说 decision 必须逐字取自审美轴三格（合格 / 太平凡 / 判不了），ask 又说
decision 取 T0–T4 —— 两条指令打架。模型两头讨好，82 的 judge 载荷实际是：

```
decision="合格"、nontriviality=null、reason="按五档属T1：…"
```

修法：两个字段各管一轴，谁也不再兼两义。

- `decision`：仍取 `STATEMENT_VERDICTS`（审美轴，词表不动）；
- `nontriviality`：必填，取 "T0"–"T4" 之一；只有 `decision` 判「判不了」时才给
  null，且必须在 reason 里写清为什么判不了。

## 这一组守什么

1. 新形状 `{decision:"合格", nontriviality:"T1"}` ⇒ 台账 1 / T1；
2. `{decision:"太平凡", nontriviality:"T0"}` ⇒ 台账 0 / T0（0 是 T0，不是"判不了"）；
3. `{decision:"判不了", nontriviality:null}` ⇒ 未判（`None` / unjudged，不是 0）；
4. 旧打架形状 `{decision:"T1"}` ⇒ 仍落 1（上一笔的向后兼容不许被这一笔打掉）；
5. 抬头/题面必须同时给出审美轴词表与 nontriviality 的取值域，旧的
   "decision 取 T0/T1/T2/T3/T4" 必须消失。

## 反真空

用假缝（直接替换 `seam.ask_json`，不调模型），每条都断言盘上那一行；"未判"必须是
`None`，不许是 0。
"""

from __future__ import annotations

import json
import types

from agentflow import secretary as SEC

STATEMENT = "命题：任意有限群 G 的 Sylow p-子群两两共轭。"
PROOF = "证明：先取一个 Sylow p-子群 P，再对任一 Q 用轨道计数与共轭作用证明 |G:N_G(P)| ≡ 1 mod p。∎"


def _judge_with(tmp_path, reply: dict):
    """造一个假缝：模型直接回 `reply`（不联网、不花钱）。"""

    class _Seam:
        def ask_json(self, prompt, **kw):
            return (dict(reply),
                    types.SimpleNamespace(ok=True, problem="", detail=""))

    boss = SEC.Secretary(role="B", root=tmp_path, seam=_Seam(), enable_model=True)
    return boss.judge_statement(statement_full=STATEMENT, proof_text=PROOF, task_id="t-000001")


def _ledger(tmp_path) -> list[dict]:
    path = SEC.nontriviality_path(tmp_path)
    assert path.exists(), f"档位台账没有落盘：{path}"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def test_a_tier_in_its_own_field_reaches_the_ledger(tmp_path) -> None:
    """① 新形状：decision="合格" + nontriviality="T1" ⇒ 台账 1 / T1。"""
    got = _judge_with(tmp_path, {"decision": "合格", "reason": "非平凡", "nontriviality": "T1"})
    assert (got["nontriviality"], got["label"], got["nontriviality_tri"]) == (1, "T1", "computed"), got
    rows = _ledger(tmp_path)
    assert (rows[0]["nontriviality"], rows[0]["label"]) == (1, "T1"), rows[0]


def test_t0_is_a_real_tier_not_unjudged(tmp_path) -> None:
    """② decision="太平凡" + nontriviality="T0" ⇒ 台账 0 / T0（0 是一档真档位）。"""
    got = _judge_with(tmp_path, {"decision": "太平凡", "reason": "平凡但真",
                                "nontriviality": "T0"})
    assert (got["nontriviality"], got["label"], got["nontriviality_tri"]) == (0, "T0", "computed"), got
    rows = _ledger(tmp_path)
    assert (rows[0]["nontriviality"], rows[0]["label"]) == (0, "T0"), rows[0]


def test_an_explicit_null_is_unjudged(tmp_path) -> None:
    """③ decision="判不了" + nontriviality=null ⇒ 未判（None，不是 0）。"""
    got = _judge_with(tmp_path, {"decision": "判不了", "reason": "输入不完整：缺证明正文",
                                "nontriviality": None})
    assert got["nontriviality"] is None, got
    assert got["nontriviality_tri"] == "unjudged", got
    rows = _ledger(tmp_path)
    assert rows[0]["nontriviality"] is None, rows[0]


def test_the_old_fighting_shape_still_lands(tmp_path) -> None:
    """④ 旧打架形状 {decision:"T1"}（没有 nontriviality）⇒ 仍落 1（向后兼容）。"""
    got = _judge_with(tmp_path, {"decision": "T1", "reason": "按五档属 T1"})
    assert (got["nontriviality"], got["label"]) == (1, "T1"), got
    rows = _ledger(tmp_path)
    assert (rows[0]["nontriviality"], rows[0]["label"]) == (1, "T1"), rows[0]


def test_the_prompt_separates_the_two_axes() -> None:
    """⑤ 抬头/题面同时给审美轴词表与 nontriviality 取值域；旧打架指令消失。"""
    text = SEC._judge_system("statement_aesthetic")
    for word in SEC.STATEMENT_VERDICTS:
        assert word in text, f"审美轴词 {word!r} 不在抬头里：{text[:600]}"
    assert "nontriviality" in text, text[:600]
    for tier in ("T0", "T1", "T2", "T3", "T4"):
        assert tier in text, f"nontriviality 的取值 {tier} 不在题面里：{text[:600]}"
    assert "null" in text, text[:600]
    assert "decision 取 T0/T1/T2/T3/T4" not in text, "旧的两头讨好指令还在（decision 不许兼档位）"
    # 词表本身不动：它仍然是审美轴那一张（这一笔只改提示词，不改口径）。
    assert SEC.JUDGE_VERDICTS["statement_aesthetic"] is SEC.STATEMENT_VERDICTS

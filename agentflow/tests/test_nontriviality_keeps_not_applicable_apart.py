# -*- coding: utf-8 -*-
"""判据：非平凡度是「五档 + 不适用 + 未判」，不适用与已放弃都不进分母（FIX186-B）。

## 现场（lp-ball-11，`temp/r11q/R11Q-REPORT.md:312`）

```text
checked=true · statements 37 行 · counts={T0:1, T1:0, T2:0, T3:0, T4:0, unjudged:36}
逐条：35 条概念行 = 「不适用：概念行没有证明正文，不做力气判档」（applicable:false，已落盘）
      000005 = T0（秘书判定 T0，score=2）
      000006 = 真没查成（E 的数值猜想，无证明正文），随后被反例放弃
CLI 复原：`非平凡性：T1 0 / T2 0 / T3 0 / T4 0 / 未判 36（共 37 条命题）`
```

三条根因：`closing.py` 把 `applicable:false` 一律计进 `unjudged`；
`_paper_statement_rows` 不过滤已放弃的行；CLI 不印 T0。

## 判据

| # | 判据 | 改前红在哪 |
|---|---|---|
| a | 同一形状的现场读成 `不适用 35 / T0 1 / 未判 1`，CLI 行里出现 T0 | 改前 `unjudged=36`、T0 不印 |
| b | 分母只算可判命题（本例 1 条）：不适用与已放弃都不进；`rows_total` 仍是 37（审计面） | 改前 `statements_total=37` |
| c | 反真空：把命题三态映射打桩成「全是活跃」⇒ 已放弃那条进分母 ⇒ b 红 | —— |
| d | 反真空：把 `nontriviality_of` 的 `tri/applicable` 打掉 ⇒ 35 条概念退回 `unjudged=36` | 证明 a 的分栏真的由那一格决定 |

## 边界

`tmp_path` 工作区；现场按 lp-ball-11 的形状造（35 概念 + 1 T0 定理 + 1 已放弃未判猜想），
不读写 `projects/`。真实副本上的复算见 `temp/fix186/judge_b_lp11.py`。
"""
from __future__ import annotations

import json
import pathlib
import sys
from typing import Any

import pytest

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agentflow import cli as CLI          # noqa: E402
from agentflow import closing as CL      # noqa: E402
from agentflow import lifecycle as L     # noqa: E402
from agentflow import secretary as SEC
import _secretary_home as HOME  # 打桩打在定义处（搬家后 SEC 那一格只是再导出）

CONCEPTS = 35
T0_ID = "000100"
ABANDONED_ID = "000200"
ABANDON_MARK = "abandoned@2026-11-19T18:01:30+08:00@夹具：反例放弃（exp:000008）"


def _seed(root: pathlib.Path, *, abandoned_status: str = "abandoned") -> None:
    """按 lp-ball-11 的形状铺一份现场（statements + nontriviality 台账）。"""
    rows: list[dict[str, Any]] = []
    for i in range(CONCEPTS):
        sid = f"{i:06d}"
        rows.append({"stmt_id": sid, "kind": "concept", "status": "active",
                     "statement_full": f"概念 {i}：夹具。"})
        SEC.append_nontriviality(
            root, statement_full=f"概念 {i}：夹具。", level=None, stmt_id=sid,
            applicable=False, path_group=0,
            basis=SEC.NONTRIVIALITY_NOT_APPLICABLE_BASIS, scope="statement")
    rows.append({"stmt_id": T0_ID, "kind": "theorem", "status": "active",
                 "statement_full": "夹具定理：初步结论。", "proof_text": "由定义直接得到。"})
    SEC.append_nontriviality(root, statement_full="夹具定理：初步结论。", level=0,
                             stmt_id=T0_ID, applicable=True, path_group=1,
                             basis="T0：基础定理或初步结论。", scope="path")
    rows.append({"stmt_id": ABANDONED_ID, "kind": "conjecture",
                 "status": abandoned_status, "statement_full": "夹具猜想：数值断言。",
                 "quote_reason": ABANDON_MARK})
    data = root / "data"
    data.mkdir(parents=True, exist_ok=True)
    (data / "statements.json").write_text(
        json.dumps({"schema_version": 1, "rows": rows}, ensure_ascii=False),
        encoding="utf-8")


def _reading(tmp_path: pathlib.Path) -> dict[str, Any]:
    root = tmp_path / "ws"
    root.mkdir()
    _seed(root)
    return CL.nontriviality_reading(root)


# ============================================================ a + b：五档 + 两栏 + 分母
def test_a_the_reading_counts_not_applicable_apart_and_prints_t0(
        tmp_path: pathlib.Path) -> None:
    """a：不适用 35 / T0 1 / 未判 1；CLI 那一行印得出 T0。"""
    got = _reading(tmp_path)
    assert got["checked"] is True, got
    assert got["counts"] == {"T0": 1, "T1": 0, "T2": 0, "T3": 0, "T4": 0,
                             "not_applicable": CONCEPTS, "unjudged": 1}, got["counts"]
    assert got["not_applicable_total"] == CONCEPTS, got
    assert got["downgraded_to_t0"] == [T0_ID], got["downgraded_to_t0"]
    line = CLI._nontriviality_line(got)
    assert "T0 1" in line and "T1 0" in line and "T4 0" in line, line
    assert "不适用 35" in line and "未判 1" in line, line


def test_b_the_denominator_is_judgeable_propositions_only(tmp_path: pathlib.Path) -> None:
    """b：分母 = 可判命题（本例 1 条）；`rows_total` 仍是 37（审计面）。"""
    got = _reading(tmp_path)
    assert got["statements_total"] == 1, got
    assert got["rows_total"] == CONCEPTS + 2, got
    assert got["abandoned_total"] == 1, got
    assert got["unjudged_abandoned"] == 1, got
    line = CLI._nontriviality_line(got)
    assert "共 1 条可判命题" in line, line
    assert "已放弃" in line, line


# ============================================================ c：反真空（放弃那一栏）
def test_c_stubbing_the_statement_mapping_puts_the_abandoned_row_back_in_the_denominator(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """c 反真空：三态映射打桩成「全是活跃」⇒ 已放弃那条进分母 ⇒ b 的红必须出现。"""
    root = tmp_path / "ws"
    root.mkdir()
    _seed(root)
    monkeypatch.setattr(L, "STATEMENT_STATE_OF",
                        {s: L.ACTIVE for s in L.STATEMENT_STATE_OF})
    got = CL.nontriviality_reading(root)
    assert got["abandoned_total"] == 0, got
    assert got["statements_total"] == 2, got
    assert got["unjudged_abandoned"] == 0, got


# ============================================================ d：反真空（不适用那一栏）
def test_d_without_the_not_applicable_mark_the_concepts_fold_back_into_unjudged(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """d 反真空：把 `tri/applicable` 打掉 ⇒ 35 条概念退回未判（改前的 36 就是它）。"""
    root = tmp_path / "ws"
    root.mkdir()
    _seed(root)
    real = SEC.nontriviality_of

    def _blind(root_arg: Any, text: Any, **kw: Any) -> dict[str, Any]:
        got = real(root_arg, text, **kw)
        got.pop("tri", None)
        got.pop("applicable", None)
        return got

    HOME.patch(monkeypatch, "nontriviality_of", _blind)
    got = CL.nontriviality_reading(root)
    assert got["counts"]["not_applicable"] == 0, got["counts"]
    assert got["counts"]["unjudged"] == CONCEPTS + 1, got["counts"]


# ============================================================ e：论文侧踢出已放弃
def test_e_the_paper_side_rows_drop_abandoned_statements(tmp_path: pathlib.Path) -> None:
    """e：`_paper_statement_rows` 是论文侧的唯一读口 —— 已放弃的行不进。"""
    root = tmp_path / "ws"
    root.mkdir()
    _seed(root)
    ids = {str(r.get("stmt_id") or "") for r in CL._paper_statement_rows(root)}
    assert ABANDONED_ID not in ids, ids
    assert T0_ID in ids and "000000" in ids, ids


if __name__ == "__main__":          # pragma: no cover - 手工跑这一份时用
    raise SystemExit(pytest.main([__file__, "-q"]))

# -*- coding: utf-8 -*-
"""块丁：只贴 `穷举论证：` 标签、钉不到实验行 ⇒ 按普通证明处理（业主 2026-11-08）。

## 缺口

`numericproof.verifier_problems` 改前把"证明栏里有「穷举论证：」这个标签"直接当成数值
证据（`parse_proof_column(...)["numeric"]`）。F 的散文证明若整段以这个标签开头，
就会被误判成数值证据 —— 于是 V 的逐行走查（`verify_proof` 那条"审每步依据"的活）
被这一格挡掉，而它本来是这段证明**唯一**的复核方式。

## 收紧后的判据（标签 + 钉得到一条 E 的穷举实验行）

| # | 情形 | 期望 |
|---|---|---|
| d1 | 证明栏以「穷举论证：」开头，台账里没有任何实验行 | `verifier_problems` 返回**空**（普通证明 ⇒ V 的逐行走查适用） |
| d1b | 同上，但台账里只有一条**普通数值**实验（`evidence_kind != "proof"`） | 仍返回空（钉不到"E 的穷举实验行"） |
| d2 | 同上 + 一条 E 的穷举实验行，命题的 `line_range.label = "exp:000000"` | 返回非空（数值证据；理由里点名实验号与凭据） |
| d2b | 同上 + 凭据是 `code_path`（证明正文里出现那条实验行的程序路径） | 返回非空（凭据 `code_path`） |
| d3 | 反真空：把钉实验那一格打桩成"总能钉到" ⇒ d1 必须变红（返回非空） | 证明 d1 的绿真的来自收紧后的判据 |

`parse_proof_column(text)["numeric"]` 在 d1 里仍然为真 —— 那是"改前会被误判"的读数；
本文件不断言它该为假（标签的认法没改），只断言**判据（V 的逐行走查覆不覆盖）**不再由它
单独决定。
"""
from __future__ import annotations

import pathlib
import sys

import pytest

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agentflow import numericproof as NP  # noqa: E402

PROSE = ("穷举论证：设 G 是有限群，按阶做归纳。归纳步里每一步都由拉格朗日定理直接给出，"
         "所以这个论证对一切有限群成立。")

EXPERIMENT = {
    "experiment_id": "000000",
    "method": "exhaustive_search",
    "evidence_kind": "proof",
    "code_path": "code/ramsey34.py",
    "claim": "R(3,4)=9",
    "observations": {"exhaustive": True,
                     "enumeration": "穷举论证：对 K_9 的全部二染色做检查。"},
}


def _statement(**extra) -> dict:
    row = {"stmt_id": "000001", "statement_full": "某个数值命题。",
           "proof_text": PROSE, "line_range": {"label": "reports/f-proof-000001.md"}}
    row.update(extra)
    return row


# ============================================================ d1 只贴标签 ⇒ 普通证明
def test_d1_a_bare_label_without_an_experiment_row_is_an_ordinary_proof() -> None:
    """d1：只有标签、台账里没有实验 ⇒ V 的逐行走查适用（空清单）。"""
    got = NP.verifier_problems(_statement(), experiments=[])
    assert got == [], got
    # 读数的另一半：标签本身仍被认成"数值证明栏"（改前就是它触发了误判）。
    assert NP.parse_proof_column(PROSE)["numeric"] is True


def test_d1b_an_experiment_that_is_not_e_exhaustion_proof_does_not_pin() -> None:
    """d1b：实验行不是"E 的穷举证明"那一档（`evidence_kind != "proof"`）⇒ 仍按普通证明。"""
    ordinary = dict(EXPERIMENT, evidence_kind="cross_check")
    got = NP.verifier_problems(_statement(line_range={"label": "exp:000000"}),
                               experiments=[ordinary])
    assert got == [], got


# ============================================================ d2 钉到实验号 ⇒ 数值证据
def test_d2_pinned_by_the_experiment_id_is_numeric_evidence() -> None:
    """d2：`line_range.label = exp:000000` 钉到 E 的穷举实验行 ⇒ 数值证据。"""
    got = NP.verifier_problems(_statement(line_range={"label": "exp:000000"}),
                               experiments=[EXPERIMENT])
    assert got, "钉到实验行之后仍被判成普通证明 —— 收紧过头了"
    text = "\n".join(got)
    assert "exp:000000" in text, text
    assert "experiment_id" in text, text
    assert "逐行走查" in text and "不适用" in text, text


# ============================================================ d2b 钉到 code_path
def test_d2b_pinned_by_the_code_path_is_numeric_evidence() -> None:
    """d2b：证明正文里出现那条实验行的 `code_path` ⇒ 也算钉到（凭据 `code_path`）。"""
    prose = PROSE + "（复跑方式：python code/ramsey34.py）"
    got = NP.verifier_problems(
        _statement(proof_text=prose), experiments=[EXPERIMENT])
    assert got, "按 code_path 钉到了实验行，却仍被判成普通证明"
    assert "code_path" in "\n".join(got), got


# ============================================================ d3 反真空
def test_d3_without_the_pin_check_the_bare_label_is_numeric_again(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """d3：把钉实验那一格打桩成"总能钉到" ⇒ d1 的同一笔必须变红。"""
    monkeypatch.setattr(
        NP, "_experiment_pins",
        lambda statement, experiments: [{"experiment": dict(EXPERIMENT),
                                         "how": "打桩", "experiment_id": "000000"}])
    got = NP.verifier_problems(_statement(), experiments=[])
    assert got, "摘掉钉实验的判据之后反而还是普通证明 ⇒ d1 的绿不是它给的"


if __name__ == "__main__":          # pragma: no cover - 手工跑这一份时用
    raise SystemExit(pytest.main([__file__, "-q"]))

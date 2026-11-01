# -*- coding: utf-8 -*-
"""判据：档位由 B 的秘书（模型）判，机械分只作参考读数。

业主 2026-10-29：「全交给模型判，5 个等级的自然语言描述应该还在吧」「历史读数不动了；
判档的还是 B 秘书」。

四档情形：
 (a) 秘书回 T3 ⇒ 落 T3，basis 里写明"以秘书判定为准"
 (b) 秘书没给（没有缝 / enable_model=False）⇒ 判不了，不是 T0
 (c) 同一条证明：机器 score 落 T0、秘书判 T3 ⇒ 落 T3（这条就是"不再机械分"的判据）
 (d) 反真空：秘书回 T0 ⇒ 落 T0
"""
from __future__ import annotations

import pathlib

from agentflow import secretary as SEC
from agentflow.secretary import NONTRIVIALITY_UNJUDGED, Secretary

# 2026-10-29：机械落格的三个真身已删（`EFFORT_TIER_BANDS` / `effort_tier_label` /
# `nontriviality_from_effort`），所以这一份判据不再 import 它们；下面第 4 条反过来断言它们不在。


class _StubSeam:
    """最小判断缝：`ask_json` 回一条固定的 JSON（或抛）。"""

    def __init__(self, data: dict | None, *, raise_exc: bool = False) -> None:
        self._data = data
        self._raise = raise_exc
        self.calls: list[tuple] = []

    def ask_json(self, material, system="", task_id="", note=""):  # noqa: ANN001, ANN201
        self.calls.append((str(material)[:120], str(system)[:120], note))
        if self._raise:
            raise RuntimeError("模型没回")
        call = type("Call", (), {"ok": True, "problem": "", "detail": ""})()
        return self._data, call


def _ws(tmp_path: pathlib.Path) -> pathlib.Path:
    ws = tmp_path / "ws"
    (ws / "data").mkdir(parents=True)
    return ws


def _secretary(tmp_path: pathlib.Path, seam: object, *, enable: bool = True) -> Secretary:
    return Secretary("B", root=_ws(tmp_path), seam=seam, enable_model=enable)


SHORT_PROOF = "证明：由 Cauchy 定理与反演公式直接得到。"     # 机械分必然落 T0
LONG_OK = {"decision": "T3", "nontriviality_basis": "引用了跨领域工具"}


def test_the_secretary_decides_the_tier(tmp_path: pathlib.Path):
    """(a)(c) 秘书判 T3 ⇒ 落 T3，即使机器力气读数落 T0。"""
    sec = _secretary(tmp_path, _StubSeam(LONG_OK))
    got = sec.judge_statement(statement_full="命题：某交叉领域结论。", proof_text=SHORT_PROOF)
    assert got.get("nontriviality") == 3, got
    assert "以秘书判定为准" in str(got.get("nontriviality_basis") or ""), got


def test_without_the_model_the_tier_is_unjudged(tmp_path: pathlib.Path):
    """(b) 秘书没给档位 ⇒ 判不了（不许是 T0）。"""
    sec = _secretary(tmp_path, None, enable=False)
    got = sec.judge_statement(statement_full="命题：某交叉领域结论。", proof_text=SHORT_PROOF)
    # 没有缝时 `judge_statement` 走的是既有的早退支：`checked=False` + 原因，
    # 档位字段根本不出现（不许补一个 T0 出来）。
    assert got.get("checked") is False, got
    assert "没查成" in str(got.get("reason") or ""), got
    assert got.get("nontriviality") is None, got


def test_the_stub_would_have_caught_a_mechanical_rule(tmp_path: pathlib.Path):
    """(d) 反真空：秘书回 T0 ⇒ 落 T0（说明 (a) 不是恒真）。"""
    sec = _secretary(tmp_path, _StubSeam({"decision": "T0",
                                          "nontriviality_basis": "平凡"}))
    got = sec.judge_statement(statement_full="命题：某交叉领域结论。", proof_text=SHORT_PROOF)
    assert got.get("nontriviality") == 0, got


def test_the_mechanical_symbols_are_gone():
    """反真空：机械落格的两个真身必须已经不在 `secretary` 上。

    （第三个 `effort_tier_label` 也一并删了；这里断言前两个，够说明"落格函数没了"。）
    """
    assert not hasattr(SEC, "EFFORT_TIER_BANDS"), "EFFORT_TIER_BANDS 还在"
    assert not hasattr(SEC, "nontriviality_from_effort"), "nontriviality_from_effort 还在"
    assert not hasattr(SEC, "effort_tier_label"), "effort_tier_label 还在"

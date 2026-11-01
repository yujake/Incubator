# -*- coding: utf-8 -*-
"""H 的扫描读数落点必须是诚实的文案（审计 C 第 ③ 条，2026-11-01 业主裁定）。

现场：H 的提示词与手册都说"要留可追踪的凭据就用 `review.report` 的 markdown
（每条带 `file` / `line` / `ref`）"，而 `review.report` 的入参收不下 scan findings
（findings 是另一个形状，markdown 是 G1–G15 门表）。这是一句做不到的承诺。

业主裁定：不改工具（那要动 review_tools = FC-27 + 重冻 golden），改文案 ——
`review.scan` 的读数本身就是凭据（findings 带 file / line / ref），不要承诺
"再落一份 markdown"；需要留痕就把读数原样写进交付。

这条判据只读声明（不跑工具、不碰 golden）：
1. 反真空：H 的 policy 与手册里都不许再出现那两句承诺；
2. 正控：两处都必须写上"读数本身就是凭据"，并点名 file / line / ref；
3. 若提到 review.report，必须同时写明它不含这批读数（不许一边提它一边暗示能落）。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

#: 这两句是审计 C 逐字引下来的旧承诺（换措辞也算：见下面的正则）。
BANNED = (
    "要留可追踪的凭据就用 `review.report`",
    "review.report` 的 markdown（每条带 `file` / `line` / `ref`）",
    "要留凭据用 `review.report`",
)


def _load():
    if str(REPO / "src") not in sys.path:
        sys.path.insert(0, str(REPO / "src"))
    from agentflow import agent_skills as SK
    from agentflow import specs as SP

    return SK, SP


def _h_policy() -> str:
    _, SP = _load()
    spec = SP.builtin_specs()["H"]
    text = "\n".join(spec.brief.policy)
    assert "review.scan" in text, "H 的 policy 里没有扫描那一段 —— 判据失去对象"
    return text


def _h_scan_skill_body() -> str:
    SK, _ = _load()
    hits = [s for s in SK.CATALOG["H"] if s.slug == "审校-机械读数先扫一遍"]
    assert len(hits) == 1, f"H 手册里应当恰好有一份『审校-机械读数先扫一遍』，找到 {len(hits)}"
    body = hits[0].body
    assert "review.scan" in body, "H 手册那一份里没有 review.scan —— 判据失去对象"
    return body


def _check_no_false_promise(text: str) -> None:
    for phrase in BANNED:
        assert phrase not in text, f"还留着旧承诺：{phrase!r}"
    # 换措辞的同义承诺：同一句里同时出现 review.report 与"凭据"、且没有否认它收不下。
    for line in text.splitlines():
        if "review.report" in line and "凭据" in line:
            assert "不含" in line, (
                "这一句一边提 review.report 一边说凭据，却没有写明它不含这批读数："
                f"{line.strip()}"
            )


def test_h_policy_does_not_promise_a_markdown_landing() -> None:
    text = _h_policy()
    _check_no_false_promise(text)
    assert "本身就是凭据" in text, "H 的 policy 没写『review.scan 的读数本身就是凭据』"
    assert "findings" in text, "H 的 policy 没点名 findings[]"
    for key in ("file", "line", "ref"):
        assert key in text, f"H 的 policy 没点名 findings 的 {key} 键"


def test_h_manual_does_not_promise_a_markdown_landing() -> None:
    body = _h_scan_skill_body()
    _check_no_false_promise(body)
    assert "本身就是凭据" in body, "H 手册没写『review.scan 的读数本身就是凭据』"
    for key in ("file", "line", "ref"):
        assert key in body, f"H 手册没点名 findings 的 {key} 键"


def test_review_report_really_cannot_carry_scan_findings() -> None:
    """反证：`review.report` 的入参里没有 findings / scan 这一格（所以承诺是做不到的）。"""
    from agentflow.tools import review_tools as RT

    spec = RT._review_report_tool.__tool_spec__  # type: ignore[attr-defined]
    props = set((spec.params or {}).get("properties") or {})
    assert not ({"findings", "scan_findings", "scan"} & props), (
        f"review.report 的入参出现了 findings 这一档：{sorted(props)} —— "
        "若真收得下，这条判据的前提要改"
    )
    assert "doc_id" in props, f"review.report 的入参形状变了：{sorted(props)}"

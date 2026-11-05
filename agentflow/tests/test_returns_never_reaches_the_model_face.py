# -*- coding: utf-8 -*-
"""C3 + errata（2026-11-05 走查）：`returns` 从不进模型面。

## 事实（三处实现，逐字可查）

- `llmseam.build_tool_face` 的 `description` 只取 `summary`（`llmseam.py:1242`）；
- `agent_prompts.tools_lines` 只渲染「名字 + summary + 必填参数 + side_effect」（`agent_prompts.py:6534`）；
- `tools/base.py:674-679` 已如实写明「`ToolFace` 的 description 不带 `returns`」。

所以 `returns` 只是台账 / 冻结快照的声明契约，模型面看不到它。这一份守三件事：

| 判据 | 守的那件事 |
|---|---|
| a | 扫 `#` 注释：凡声称"returns 进 description / 模型看得到 returns"的 ⇒ 0 处 |
| b | 反向：`base.py:674-679` 那句"不带 returns"仍在（别把正确说法删了） |
| c | 反真空：把一条注释改回错说法 ⇒ a 红（这里用同一只扫描器喂合成句子） |
| d | 模型面实测：每个 function 的 description 只等于 summary；`formal.record` 的 returns 不在里面 |
| e | `formal.record` 的拒信码是 `reason` 的取值，不是 `returns` 的键（D17 口径） |

扫描口径：`tokenize` 的 COMMENT（不含 docstring / 字符串字面量），相邻行并成注释块；
跳过 `temp/`（探针与历史副本）与缓存目录。
"""

from __future__ import annotations

import pathlib
import re
import tokenize

from agentflow import agent_prompts as AP
from agentflow.agent_l._support import RECORD_REASONS
from agentflow.llmseam import build_tool_face
from agentflow.tools import build_registry
from agentflow.tools import formal_tools

ROOT = pathlib.Path(__file__).resolve().parents[1]
SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", ".pytest-tmp", "temp",
             "node_modules", ".venv", "venv"}

#: 肯定式句子（"不拼进"/"不进"由负向后顾排除；"要不要"这类假设句整块跳过）。
_PATTERNS = (
    re.compile(r"returns[^。；]{0,40}(?<![不拼])拼进[^。；]{0,60}description"),
    re.compile(
        r"returns[^。；]{0,40}(?<![不拼])进[^。；]{0,60}"
        r"(?:function-calling|function calling|模型看得到|模型可见)[^。；]{0,30}description"
    ),
    re.compile(r"returns[^。；]{0,30}模型看得到"),
    re.compile(r"returns[^。；]{0,20}就是模型看得见的"),
)
#: 正确说法（判据 b 的那句与本次 errata 的统一措辞）：出现任一条就不算错说法。
_GOOD_MARKERS = ("声明快照", "不带 returns", "不进 description",
                 "不进 function-calling", "看不到", "要不要")


def _is_false_claim(text: str) -> bool:
    if "returns" not in text:
        return False
    if any(s in text for s in _GOOD_MARKERS):
        return False
    return any(p.search(text) for p in _PATTERNS)


def _comment_lines(path: pathlib.Path) -> list[tuple[int, str]]:
    """逐行 COMMENT：`[(行号, 去掉 # 标记的文本)]`。"""
    out: list[tuple[int, str]] = []
    try:
        with path.open("rb") as fh:
            for tok in tokenize.tokenize(fh.readline):
                if tok.type == tokenize.COMMENT:
                    out.append((tok.start[0], tok.string.lstrip("#:").strip()))
    except (OSError, SyntaxError, UnicodeDecodeError, tokenize.TokenError):
        return []
    return out


def _comment_windows(path: pathlib.Path) -> list[tuple[int, str]]:
    """相邻两行并成一个窗口：错说法常跨行，但整段合并会被远处正确说法误遮。"""
    lines = _comment_lines(path)
    out: list[tuple[int, str]] = []
    for i, (line, text) in enumerate(lines):
        window = text
        if i + 1 < len(lines) and lines[i + 1][0] == line + 1:
            window = f"{text} {lines[i + 1][1]}"
        out.append((line, window))
    return out


def _false_claims() -> list[str]:
    out: list[str] = []
    for path in sorted(ROOT.rglob("*.py")):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        for line, text in _comment_windows(path):
            if _is_false_claim(text):
                out.append(f"{path.relative_to(ROOT)}:{line}: {text}")
    return out


# ============================================================ a 扫全仓

def test_a_no_comment_claims_returns_reaches_the_model_face():
    hits = _false_claims()
    assert hits == [], ("还有注释在说 returns 进 description / 模型看得到 returns：\n"
                        + "\n".join(hits))


# ============================================================ b 正确说法仍在

def test_b_the_correct_sentence_in_base_py_is_not_deleted():
    text = (ROOT / "src/agentflow/tools/base.py").read_text(encoding="utf-8")
    assert "description 不带 `returns`" in text, (
        "`base.py:674-679` 那句正确说法被删了 —— 判据 b 失去对象")


# ============================================================ c 反真空

def test_c_the_scanner_catches_a_reverted_comment():
    bad = ("`returns` 会拼进 function-calling 的 `description`"
           "（`tools/base.py:721`）⇒ 模型看得到。")
    assert _is_false_claim(bad), "扫描器抓不到旧错说法 ⇒ 判据 a 是真空的"
    good = ("`returns` 只是台账/快照的契约（`tools/base.py:674-679`："
            "description 不带 returns），模型面看不到它。")
    assert not _is_false_claim(good), "正确说法被误判 ⇒ 扫描器会制造假红"


# ============================================================ d 模型面实测

def test_d_the_tool_face_description_is_only_the_summary():
    reg = build_registry().registry
    face = build_tool_face("L", reg)
    functions = {f["function"]["name"]: f["function"] for f in face.functions}
    checked = 0
    for san, target in face.names.items():
        if not str(target).startswith("tool:"):
            continue
        real = str(target).split(":", 1)[1]
        spec = reg.get(real)
        want = str(getattr(spec, "summary", "") or real)
        assert functions[san]["description"] == want, (real, san)
        checked += 1
    assert checked >= 3, checked


def test_e_formal_record_returns_is_not_in_the_model_face():
    reg = build_registry().registry
    face = build_tool_face("L", reg)
    functions = {f["function"]["name"]: f["function"] for f in face.functions}
    san = next(s for s, t in face.names.items() if t == "tool:formal.record")
    desc = functions[san]["description"]
    assert desc == reg.get("formal.record").summary, desc
    assert "refusal_reason" not in desc, desc
    line = next(line for line in AP.tools_lines("L", reg)
                if line.startswith("- formal.record"))
    assert reg.get("formal.record").returns not in line, line
    assert "refusal_reason" not in line, line


# ============================================================ e D17 口径

def test_f_record_refusal_codes_are_values_not_returns_keys():
    """D17：`RECORD_REASONS` 的八个拒信码是 `reason` 的取值，不是 `returns` 的键。"""
    spec = build_registry().registry.get("formal.record")
    assert "'refused'" in spec.returns and "'refusal_reason'" in spec.returns
    for code in RECORD_REASONS:
        assert code not in spec.returns, (code, spec.returns)


def test_g_register_docstring_counts_the_three_tools():
    """C3 ①：装配清单是三件，docstring 不许再写"两件"。"""
    doc = formal_tools.register.__doc__ or ""
    assert "三件工具" in doc, doc
    assert "两件工具" not in doc, doc
    assert len(formal_tools._TOOL_FUNCTIONS) == 3, formal_tools._TOOL_FUNCTIONS

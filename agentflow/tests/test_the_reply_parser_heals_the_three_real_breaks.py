# -*- coding: utf-8 -*-
"""判据：坏 JSON 的三类真机断法各有一手（补括号 / 修非法转义 / 认出 XML 形态）。

## 真机（2026-10-28，`projects/paper-rewrite-78c`，14 个坏步逐条算过括号平衡）

| 形态 | 条数 | 逐条证据 |
|---|---|---|
| 少最外层一个 `}` | 8 | 状态机（忽略字符串）算出"未闭合 1 个 `{`"，最后一字是 `}`，`json.loads` 的报错位置恰好等于文本长度 |
| 字符串里非法转义 | 2 | `E#6` char 2253 `` \`fitz\` ``；`E#16` char 4220 `**T\*(σ0)**` |
| 工具调用写成 DSML XML | 1 | `B#7` 尾部 `</｜｜DSML｜｜ parameter>…</｜｜DSML｜｜ calls>` |

`llm.parse_llm_json` 已经会修这几档：围栏、前后寒暄、多余的右花括号、多余逗号、
字符串里没转义的双引号、裸控制字符。缺的正是上面三类里的前两类（少括号、非法转义），
而第三类不该修（它根本不是 JSON）—— 该做的是把话说清楚，让下一回合别再这么写。

## 这一组守什么

1. 少最外层一个 `}`（真机原文形态）⇒ 解析成功；
2. 非法转义 `\*` / `` \` ``（真机原文形态）⇒ 解析成功；
3. 反真空：字符串没闭合 / 少两个以上括号 / 结构坏 ⇒ 仍失败（不许乱补成"看起来能解析"）；
4. DSML XML ⇒ 不修补（解析仍失败），但诊断话术点名"XML 形态"，下一回合能改；
5. 正控：正常 JSON 逐字不变（修补不许改语义）。
"""
from __future__ import annotations

import json

import pytest

from agentflow.agent_loop import _continue_hint  # noqa: F401  （保持与循环那侧的引用面一致）
from agentflow.llm import ExtractionError, parse_llm_json
from agentflow.llmseam import _json_shape_hint

#: 真机原文的骨架（`B#10`：summon_many 少最外层那个括号；内容压成占位符）
MISSING_BRACE = ('{"summon_many": {"targets": [{"role": "V", "task": "对在册命题 stmt:000005 '
                 '整体重读并签 verify_proof"}], "why": "两处修补都已落库，'
                 '同时派 V 复核以省时间"}')


def test_a_missing_outer_brace_is_repaired():
    """正题一：少最外层一个 `}` ⇒ 解析成功，且键与值逐字对得上。"""
    got = parse_llm_json(MISSING_BRACE)
    assert isinstance(got, dict), got
    assert "summon_many" in got, got
    why = got["summon_many"]["why"]
    assert why.startswith("两处修补都已落库"), why


def test_a_bad_escape_is_repaired():
    """正题二：字符串里的 `\\*` / `` \\` `` （LaTeX 与 markdown 那两处）⇒ 解析成功。"""
    text = ('{"final": "证明里写 **T\\*(σ0)**，命令是 \\`import pymupdf\\`，'
            '路径 work\\\\paper-full.txt"}')
    got = parse_llm_json(text)
    assert "T*(σ0)" in got["final"], got["final"]
    assert "`import pymupdf`" in got["final"], got["final"]


def test_an_unclosed_string_is_not_papered_over():
    """反真空：字符串没闭合 ⇒ 仍失败（补括号那一条不许把它变成"看起来能解析"）。"""
    with pytest.raises(ExtractionError):
        parse_llm_json('{"final": "写到一半就断了')


def test_only_the_outermost_single_brace_is_repaired():
    """收窄（2026-10-28）：只补最外层缺一个花括号；缺两层 / 散文照旧拒。"""
    got = parse_llm_json('{"summon": {"role": "B", "task": "登记"}')
    assert got["summon"]["role"] == "B", got
    with pytest.raises(ExtractionError):
        parse_llm_json('{"summon": {"role": "B", "task": "登记"')   # 缺两层
    with pytest.raises(ExtractionError):
        parse_llm_json("这不是 JSON，随便说了一句散文。")


def test_the_repair_does_not_touch_a_valid_reply():
    """正控：正常 JSON 逐字解析，语义不变（修补只在原样解析失败之后才试）。"""
    text = json.dumps({"tool": "fs.read", "args": {"path": "out/x.txt"}, "why": "读一下"},
                      ensure_ascii=False)
    got = parse_llm_json(text)
    assert got == {"tool": "fs.read", "args": {"path": "out/x.txt"}, "why": "读一下"}, got


def test_a_dsml_tail_is_trimmed_and_named():
    """JSON 后面跟一段 DSML 标记（真机 `B#7` 那一形）⇒ 补括号后能解析，且话术点名它。

    口径：能救的救（那一句 JSON 的意图毫无歧义，丢掉整步的代价更大），
    但"你写成了 XML"这句话必须说出去 —— 否则下一回合还会这么写。
    """
    text = ('{"summon": {"role": "B", "task": "登记"}\n'
            "</｜｜DSML｜｜ parameter>\n</｜｜DSML｜｜ invoke>\n")
    got = parse_llm_json(text)
    assert got.get("summon", {}).get("role") == "B", got
    hint = _json_shape_hint(text)
    assert "XML" in hint or "DSML" in hint, hint


def test_pure_xml_has_nothing_to_repair_but_is_still_named():
    """只有 XML 标记、一个 JSON 对象都没有 ⇒ 仍失败（不修补），但话术点名它。"""
    text = ("</｜｜DSML｜｜ invoke>\n</｜｜DSML｜｜ calls>\n")
    with pytest.raises(ExtractionError):
        parse_llm_json(text)
    hint = _json_shape_hint(text)
    assert "XML" in hint or "DSML" in hint, hint

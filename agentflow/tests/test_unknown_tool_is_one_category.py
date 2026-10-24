# -*- coding: utf-8 -*-
"""判据 ⑤：调了一个没广告过的工具名 ⇒ 两种协议记同一个类目。

## 改前是什么形态（同一件事两个码、两个类目）

- 文本协议：模型在 `tool` 字段里写一个不在面上的名字 ⇒ `tools/base.py` 那一档记
  `unknown_tool`（类目 `unknown_tool`：名字不存在）；
- 原生工具调用（`tool_calls`）：同一个动作走 `llmseam.ToolFace.to_shape`，名字认不出时
  返回的 `problem` 是 `judge_bad_json` ⇒ 记进 `judge_bad_json` 那一档。

于是"名字不存在"这一类在两种协议下各数一半，而 `judge_bad_json` 那一档的纠正话术是
"只回一行 JSON" —— 对着"你点了一个不存在的函数"说这句话，等于把模型领向更错的方向
（真机三趟 16 条 `judge_bad_json` 里 8 条是这个形态）。

## 选了哪个类目、为什么

类目取 `unknown_tool`（错误表里已有的那一档："名字不存在：工具面没有这件工具 /
该角色没有这个动作 / 角色名不存在"）—— 这正是两种协议下发生的是同一件事。
码各自保留自己的名字：文本那条是 `unknown_tool`，判据层这条新码叫
`judge_unknown_tool`。与 `judge_not_wired` 归 `not_wired` 是同一手法：
码说"哪一层看出来的"，类目说"这是个什么错"。这样 `judge_bad_json` 只留给
"真的不是 JSON"，它的纠正话术也就不会被不属于它的输入污染。

## 判据

1. 两个码在 `errorstats` 里归同一个类目；
2. 原生那条路真的产出新码（不是只在表里登记了一个没人产出的名字）；
3. 反真空：真的坏 JSON 仍然是 `judge_bad_json`（这一档没有被顺手放宽）。
"""
from __future__ import annotations

from agentflow import errorstats as ES
from agentflow import judge as J
from agentflow.llmseam import build_tool_face
from agentflow.tools import build_for_role


class _ProseLLM:
    """一个只会回散文的缝：它的输出必然是坏 JSON（反真空要用的那一档）。"""

    def complete(self, prompt: str) -> str:
        return "这不是 JSON，只是一段解释。"


def test_a_name_that_is_not_on_the_face_is_one_category_in_both_protocols() -> None:
    """⑤ 两种协议下"点了没广告过的名字"归同一个类目（`unknown_tool`）。

    改前红：`CODE_TO_CATEGORY["judge_unknown_tool"]` 不存在（原生那条路记的是
    `judge_bad_json`）⇒ "名字不存在"这一类在两个协议里各数一半。
    """
    assert ES.CODE_TO_CATEGORY["unknown_tool"] == "unknown_tool"
    assert ES.CODE_TO_CATEGORY.get("judge_unknown_tool") == "unknown_tool", (
        "判据层那条新码没有归到 `unknown_tool`："
        f"{ES.CODE_TO_CATEGORY.get('judge_unknown_tool')!r}")
    assert ES.CODE_TO_CATEGORY["judge_bad_json"] == "judge_bad_json", (
        "`judge_bad_json` 那一档被改宽了：它必须只留给真的坏 JSON")
    # 词表那一侧也要认它（判定失败码的唯一真身在 `judge.JUDGE_PROBLEMS`）
    assert "judge_unknown_tool" in J.JUDGE_PROBLEMS
    assert J.is_judge_problem("judge_unknown_tool") is True


def test_the_native_tool_face_produces_the_new_code() -> None:
    """⑤ 原生那条路真的产出 `judge_unknown_tool`（登记了却没人产出 = 死取值）。

    同一条用例里带反真空：真的坏 JSON 仍然落 `judge_bad_json`，而"参数不是对象"
    仍然是 `judge_bad_args` —— 三个码各管一件事，不许互相借。
    """
    reg = build_for_role("V", store=None, workspace_root=None).registry
    face = build_tool_face("V", reg)

    data, problem, detail = face.to_shape({"name": "no_such_tool", "arguments": "{}"})
    assert data is None
    assert problem == "judge_unknown_tool", (problem, detail)
    assert "没广告过" in detail, detail

    # 反真空一：广告过的名字 + 坏参数 ⇒ `judge_bad_args`（不是新码、也不是坏 JSON）
    some = next(iter(face.names))
    _d2, p2, _t2 = face.to_shape({"name": some, "arguments": "{不是 JSON"})
    assert p2 == "judge_bad_args", p2

    # 反真空二：真的不是 JSON ⇒ 仍旧 `judge_bad_json`（这一档没有被放宽）
    got, why = J.judge_json(_ProseLLM(), "随便问一句")
    assert got is None and why == "judge_bad_json", (got, why)

# -*- coding: utf-8 -*-
"""桥接层的工具名查找要同时认点号与下划线两种写法：三条判据 + 一条反真空。

## 现场（`draft/152` 之二，真机三趟）

`llmseam.ToolFace` 的广告名只存下划线写法（`table_get`：函数名不允许点号，所以
`build_tool_face` 用 `_sanitize` 归一化），而提示词、拒信、文档、工具面里用的都是
真名（`table.get`）。改前 `to_shape` 只按原样查一次名字表，于是模型写点号名就一定
落成"模型调用了一个没广告过的函数"，接着被 `errorstats` 计进 `judge_bad_json`。

真机读数：三趟 16 条 `judge_bad_json` 里 8 条是这个形态（`r34d:90/131/390/399/601/611/1083`、
`r34c:543`），点名到的工具都真的在那一趟的面上 —— 例如 `sessions/r34d.jsonl:611`：

    模型调用了一个没广告过的函数 'table.get'（这一趟广告的是 [...]）

而 `table.get` 就在 H 的面里。它们没有一条是坏 JSON，所以这一档的处置（"模型回了
坏 JSON"）与真实原因（名字写法对不上）完全不同。

## 判据

① `table.get` 与 `table_get` 都能通过同一张广告名（改前：点号名被拒）；
② 真的不在面上的名字仍拒，且拒信里有并列候选（负控）；
③ 反真空：把归一化打桩成恒等 ⇒ ① 必红（证明"能过"靠的正是那一次归一化查找）。
"""
from __future__ import annotations

import pytest

from agentflow import judge as J
from agentflow import llmseam as LL
from agentflow.tools import build_registry


def _face(role: str = "H") -> LL.ToolFace:
    """H 的面：`table.get` / `review.record_finding` 都在上面（真机那两条的现场）。"""
    return LL.build_tool_face(role, build_registry().registry)


def _advertised(real: str, face: LL.ToolFace) -> bool:
    return f"tool:{real}" in set(face.names.values())


# ============================================================ ① 两种写法都能过


@pytest.mark.parametrize("real,written", [
    ("table.get", "table.get"),
    ("table.get", "table_get"),
    ("review.record_finding", "review.record_finding"),
    ("review.record_finding", "review_record_finding"),
])
def test_both_spellings_resolve_to_the_same_advertised_tool(real: str, written: str):
    """① 正控：点号写法与下划线写法解出同一件工具（同一个真名）。

    改前红：点号那一半 `problem='judge_bad_json'`、`data=None`（真机 :611 的 `table.get`）。
    """
    face = _face()
    assert _advertised(real, face), f"{real} 不在 H 的面里，这条判据就没咬到真机形态"
    data, problem, detail = face.to_shape({"name": written, "arguments": "{}"})
    assert problem == "", (written, problem, detail)
    assert data == {"tool": real, "args": {}, "why": ""}, data


def test_the_advertised_form_is_still_tried_first():
    """① 的第二半：原样写法先查（模型照广告名调用是最常见的形态，不许被回退分支改义）。

    两件工具如果分别以 `a.b` 与 `a_b` 为真名，归一化查一次会撞车 —— 那一档在
    `build_tool_face` 就用 ValueError 拒了整份面，所以"先原样"这一步仍然是无歧义的。
    """
    face = _face()
    underscore = {k for k, v in face.names.items() if v == "tool:table.get"}
    assert underscore == {LL._sanitize("table.get")}, underscore
    data, problem, _detail = face.to_shape({"name": "table_get", "arguments": "{}"})
    assert problem == "" and data["tool"] == "table.get", (data, problem)


def test_the_readout_side_agrees_with_the_parse_side():
    """① 的读数面：`action_name` 与 `to_shape` 同一处口径（D-35 丢弃读数要用它）。

    改前 `action_name` 也只按原样查，于是"这一步解析得了、被丢的那条却映不回真名"
    会同时存在；两条路现在共用一个 `_resolve`。
    """
    face = _face()
    assert face.action_name({"name": "table.get"}) == "table.get"
    assert face.action_name({"name": "table_get"}) == "table.get"


# ============================================================ ② 真的不存在的名字仍拒


@pytest.mark.parametrize("written,expect_candidate", [
    ("table.gett", "table.get"),
    ("review.record_findingz", "review.record_finding"),
])
def test_a_name_that_is_not_on_the_face_is_refused_with_candidates(
        written: str, expect_candidate: str):
    """② 负控：不存在的名字照旧拒（`judge_unknown_tool`），而拒信里带并列候选。

    这一条防的是"把查找放宽成永远能找到"：认两种写法不等于认任意写法。
    """
    face = _face()
    data, problem, detail = face.to_shape({"name": written, "arguments": "{}"})
    assert data is None, data
    # 2026-10-26（第 ⑤ 条根因）：这一档的码从 `judge_bad_json` 改成 `judge_unknown_tool`
    # —— 它从来不是坏 JSON，而 `judge_bad_json` 那一档的纠正话术（"只回一行 JSON"）
    # 对着这条错说出去是把模型领向更错的方向。两个码在 `errorstats` 里归同一个类目。
    assert problem == "judge_unknown_tool", (problem, detail)
    assert J.is_judge_problem(problem), "这个码必须登记进 JUDGE_PROBLEMS"
    assert written in detail, detail
    assert "并列候选" in detail, detail
    assert expect_candidate in detail, detail


def test_a_tool_that_belongs_to_another_role_is_still_refused():
    """② 负控（权限面那一半）：`fs.read` 不在 H 的面上，两种写法都必须拒。

    这条同时钉住"归一化查找不打开权限"：`fs_read` 是 fs.read 的广告名，但它不在
    这一趟的 `names` 里，所以查不到 —— 名字解析只认"这一趟真的广告过的那些"。
    """
    face = _face()
    for written in ("fs.read", "fs_read"):
        data, problem, detail = face.to_shape({"name": written, "arguments": "{}"})
        assert data is None and problem == "judge_unknown_tool", (written, problem, detail)


# ============================================================ ③ 反真空


def test_negative_control_an_identity_sanitizer_turns_the_dotted_name_red(
        monkeypatch: pytest.MonkeyPatch):
    """③ 反真空：把 `_sanitize` 打桩成恒等 ⇒ 点号名回到了改前的命运（必红）。

    恒等打桩只改一处：查找的第二次尝试退化成"再查一遍原样"。它证明 ① 之所以能过，
    靠的就是那一次归一化查找 —— 而不是别的什么地方顺手把名字认下来了。

    面必须在打桩之前建：`build_tool_face` 用的是同一个 `_sanitize`（广告名的键就是
    它归一化出来的），先打桩会把整份面也改成点号键 —— 那就不是"查找回退失效"，
    而是"换了一张面"，测的东西就不一样了。
    """
    face = _face()
    monkeypatch.setattr(LL, "_sanitize", lambda name: str(name))
    dotted, problem, detail = face.to_shape({"name": "table.get", "arguments": "{}"})
    assert dotted is None, dotted
    assert problem == "judge_unknown_tool", (problem, detail)
    assert "没广告过" in detail, detail
    # 广告名那一半不受影响（它是原样命中的）—— 红的是"点号写法"这一条
    data, ok, _ = face.to_shape({"name": "table_get", "arguments": "{}"})
    assert ok == "" and data["tool"] == "table.get", (data, ok)

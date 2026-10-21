# -*- coding: utf-8 -*-
"""被参数拒的那一步，把声明的参数表回给模型（`draft/37` §140 的协作改进 A）。

## 为什么（T2 第 5 趟第 1 段的盘上读数）

47 次派活里 35 次被拒，绝大多数是"猜参数形状猜错"：`D.register_conjecture` 18 次
（`testable` 必须是对象、`statement` 里出现 `which`）、`F.create_plan` 4 次
（`subgoals[0]` 不是对象、`budget` 缺三键）、`G.build_document` 3 次（`kind` 非法）。

被拒的模型手上没有那份声明，只能试。这一批做两半：① 把模糊声明补上子键
（`testable`/`budget`/`subgoals`，见 `specs/{d,f}.py` 与对应的工具 schema）；
② 被参数拒时自动把那张表原样回给模型 —— 把"猜"换成"读"。这一组判据守的是 ②。
"""
from __future__ import annotations

import json
import pathlib

import test_agent_loop as TAL
from agentflow.agent_loop import looks_like_a_param_refusal, render_params, run_role
from agentflow.llmseam import LlmSeam


def _reply(obj: dict) -> str:
    return json.dumps(obj, ensure_ascii=False)


def _run(tmp_path: pathlib.Path, replies: list[str], *, max_steps: int = 6):
    scripts = {"M": replies}
    st, cond, registry, gw, root = TAL._wired(tmp_path, scripts, max_steps=max_steps)
    return run_role("M", "参数被拒时把参数表读给我", store=st, registry=registry, conductor=cond,
                    seam=LlmSeam(role="M", session_root=root, gateway=gw["M"], price=(0.0, 0.0),
                                 sid="test-run"), workspace_root=str(root), sid="test-run",
                    from_env=False)


def test_a_tool_refused_for_params_gets_its_declared_table_back(tmp_path: pathlib.Path):
    """正控：工具因为参数不合法被拒 ⇒ 同一步的结果里带那张声明表（键名/必填都读得到）。"""
    bad = {"tool": "fs.read", "args": {"nope": 1}, "why": "少写了 path"}
    run = _run(tmp_path, [_reply(bad), _reply({"final": "照表重写"})])

    first = run.steps[0]
    assert first.shape == "tool", first.to_dict()
    assert first.result.get("ok") is False, first.result
    table = str(first.result.get("参数表") or "")
    assert table, f"被参数拒了却没给参数表：{first.result}"
    assert "path" in table and "【参数表】" in table, table
    # 表里要有"必填"与类型（否则模型还是只能猜）
    assert "必填" in table and "string" in table, table


def test_a_dispatch_without_an_action_carries_no_param_table(tmp_path: pathlib.Path):
    """负控（新口径，2026-10-16）：派活那一步不带任何参数表。

    为什么改了：原命题是"唤起的动作缺必填参数 ⇒ 那一步带那个动作的参数表"，而业主口径的
    最终形态是「action 完全不用父代理填」⇒ 派活不带动作 ⇒ 没有动作的参数声明可查
    ⇒ `invalid_params` 这一档在派活路径上不可达（它现在只可能来自工具路径，
    由本文件上面那条正控覆盖）。这一条改成钉住新事实：那一步不出现 `参数表` ——
    出现了就说明框架又替它选了一个动作。
    """
    payload = {"summon": {"role": "F", "task": "给这个问题立一份攻坚计划",
                          "params": {"problem": "只给了 problem，没给 problem_key"},
                          "why": "试试看"}}
    run = _run(tmp_path, [_reply(payload), _reply({"final": "照办"})])

    first = run.steps[0]
    assert first.shape == "summon", first.to_dict()
    # 真命题两条：① 这一档不是"参数不合法"（派活没有动作 ⇒ 没有参数声明可违）；
    # ② 那一步不带参数表（带了就说明框架又替被派者选了一个动作）。
    assert str(first.result.get("refusal_reason") or "") != "invalid_params", first.result
    assert not first.result.get("参数表"), (
        "派活那一步带了参数表 ⇒ 说明这一趟又替被派者选了一个动作", first.result
    )
    assert json.dumps(first.result, ensure_ascii=False)   # 载荷可序列化（契约）


def test_a_successful_step_carries_no_param_table(tmp_path: pathlib.Path):
    """负控（不许滥发）：正常成功的步里没有 `参数表`（它只在被参数拒时出现）。"""
    run = _run(tmp_path, [_reply({"tool": "conductor.state", "args": {}}),
                          _reply({"final": "一切正常"})])
    assert run.stop_reason == "final", run.to_dict()
    assert all("参数表" not in s.result for s in run.steps), run.to_dict()


def test_the_renderer_and_the_detector_are_honest_about_what_they_see():
    """判据的判据：渲染器把 必填/枚举/说明 写出来；识别器认得嵌套拒绝、也不冤枉成功。"""
    schema = {"type": "object", "additionalProperties": False, "required": ["a"],
              "properties": {"a": {"type": "string", "description": "必填的那个"},
                             "b": {"type": "string", "enum": ["x", "y"]}}}
    text = render_params(schema)
    assert "a: string，必填，必填的那个" in text, text
    assert "枚举 [x/y]" in text and "封闭集合" in text, text
    assert render_params({}) == "" and render_params(None) == ""

    assert looks_like_a_param_refusal({"ok": False, "meta": {"kind": "invalid_params"}})
    assert looks_like_a_param_refusal({"summoned": [{"outcome": "refused",
                                                     "refusal_reason": "参数不合法"}]})
    assert not looks_like_a_param_refusal({"ok": True, "meta": {"kind": ""}})
    assert not looks_like_a_param_refusal({"ok": False, "meta": {"kind": "forbidden_edge"}})

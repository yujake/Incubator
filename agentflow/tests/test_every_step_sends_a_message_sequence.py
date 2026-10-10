"""判据：每一步发给模型的是消息序列（S-C 第 ① 步 / 业主 2026-10-10 裁定 5甲）。

## 这一批换的是什么（以及没换什么）

搬运来源：DSH 的 messages —— assistant 带 `tool_calls`、tool 带 `tool_call_id`
（`dsh-agent-loop/lib/index.js` 的 loop 消息面；判别式那一族见 `draft/100` §3）。

换的：`transcript: str` 不再是唯一历史载体。循环里那份历史现在是
`messages: list[dict]`（`role: user / assistant / tool`），assistant 那条带结构化的
`tool_calls`（`id` 由步号派生，所以从会话记录里重建得回来），tool 那条带
`tool_call_id`。`run.messages` 是这一趟的序列读数。

没换的：念出来的那份文本。`render_messages(messages) == run.transcript`
由构造保证（`_spoken_half` / `_result_half` 是那两个"半句"的唯一拼法，`_step_line`
也由它们拼出来）—— 于是 `run.transcript` 的读者（Web UI 的事件回放、续跑、`--resume`）
这一步之后拿到的东西一个字没变。整序列化与 `resume_messages`（逐条相等）是第 ② 步。

## 判据（六条）

1. 正控（四条的形态）：两步的循环里，第二步发给模型的是
   `[system, user, assistant(tool_calls), tool]`，且 tool 的 `tool_call_id` 等于
   assistant 给的 id（`system` 走 `LlmSeam` 的 `system=` 那一格，不在序列里）。
2. 负控：把 tool 挂到错的 id ⇒ 配对判据当场红（`message_sequence_problem`）。
3. 反真空：序列里 assistant 那条必须带工具调用（否则这条判据只测了拼接）。
4. 正控（渲染逐字相同）：`render_messages(run.messages) == run.transcript`。
5. 正控（插话是 user 消息）：插话进序列时是 `user` 那条 —— 它是"人对我说的"，
   不是工具结果（改前它只是拼进字符串的一段）。
6. 负控（角色词表）：序列里出现第四种角色 ⇒ 配对判据点名（词表只有三个）。
"""

from __future__ import annotations

import json
import pathlib

from agentflow import agent_loop as AL
from agentflow.agent_loop import run_role
from agentflow.llmseam import LlmSeam
from test_agent_loop import _wired


def _reply(obj: dict) -> str:
    return json.dumps(obj, ensure_ascii=False)


def _two_step_run(tmp_path: pathlib.Path, sid: str = "t-msg"):
    """跑两步：第 0 步调一个工具、第 1 步收工（第二步的序列才是要看的那一份）。"""
    st, cond, registry, gw, root = _wired(
        tmp_path, {"M": [_reply({"tool": "conductor.role_spec", "args": {"role_name": "C"},
                                 "why": "先看一眼 C 的规格"}), _reply({"final": "收工"})]},
        max_steps=3)
    run = run_role("M", "看两步的消息序列", store=st, registry=registry, conductor=cond,
                   seam=LlmSeam(role="M", session_root=root, gateway=gw["M"],
                                price=(0.0, 0.0), sid=sid),
                   workspace_root=str(root), sid=sid, from_env=False)
    return run, gw, root


def test_every_step_is_a_four_part_message_sequence(tmp_path: pathlib.Path) -> None:
    """正控（核心）：第二步发出去的是 [system, user, assistant(tool_calls), tool]。"""
    run, gw, _root = _two_step_run(tmp_path)
    assert run.stop_reason == "final", run.to_dict()
    # 序列：user(开场) + assistant(第 0 步) + tool(第 0 步) —— 第二步的调用看到的就是这三条，
    # 而 `system` 由 `LlmSeam` 单独给（第四条）⇒ 合起来正是那四条。
    kinds = [str(m.get("role")) for m in run.messages]
    assert kinds[:3] == ["user", "assistant", "tool"], kinds
    assert gw["M"].systems[-1].strip(), "system 那一格是空的 ⇒ 四条里少了一条"
    assistant, tool = run.messages[1], run.messages[2]
    ids = [str(c["id"]) for c in assistant["tool_calls"]]
    assert len(ids) == 1, assistant
    assert tool["tool_call_id"] == ids[0], (tool, assistant)
    # 反真空：assistant 那条必须真的带一次工具调用（否则这条判据只测了拼接）
    call = assistant["tool_calls"][0]
    assert call["type"] == "function" and call["function"]["name"], call
    assert call["function"]["arguments"], "arguments 是空的 ⇒ 那一步的参数没进序列"
    assert AL.message_sequence_problem(run.messages) == "", run.messages


def test_a_tool_message_on_the_wrong_id_is_caught(tmp_path: pathlib.Path) -> None:
    """负控：把 tool 挂到错的 id ⇒ 配对判据当场红（并说清是谁给的那个 id）。"""
    good = [AL.user_message("开场"), AL.assistant_message(0, {"tool": "fs.read"}, content="你说了"),
            AL.tool_message(0, "结果")]
    assert AL.message_sequence_problem(good) == ""
    wrong = list(good)
    wrong[2] = AL.tool_message(7, "结果")            # 挂到一个没人要求过的 id 上
    why = AL.message_sequence_problem(wrong)
    assert "挂错 id" in why and "call-1" in why, why
    # 另外两种坏法也要点名（缺 id / assistant 没有 tool_calls）
    assert "没有 tool_call_id" in AL.message_sequence_problem(
        [AL.user_message("u"), {"role": "tool", "content": "x"}])
    assert "没有可配对" in AL.message_sequence_problem(
        [AL.user_message("u"), {"role": "assistant", "content": "x"}])
    # 负控（角色词表）：第四种角色要被抓出来
    assert "不在" in AL.message_sequence_problem(
        [AL.user_message("u"), {"role": "system", "content": "x"}])


def test_the_rendering_is_byte_equal_to_the_retired_transcript(tmp_path: pathlib.Path) -> None:
    """正控（换载体不换文本）：`render_messages(序列)` 与 `run.transcript` 逐字相同。

    这一条是"第 ① 步不伤读者"的机器读数：`run.transcript` 的读者（Web UI 回放、
    续跑、`--resume`）在这一步之后必须拿到同一份文本。
    """
    run, _gw, _root = _two_step_run(tmp_path, sid="t-render")
    assert AL.render_messages(run.messages) == run.transcript, "渲染与那一份文本分家了"
    # 两半的唯一拼法还在（`_step_line` = `_spoken_half` + `_result_half`）：
    # 续跑那条路（`resume_transcript`）第 ① 步照旧用它，第 ② 步才换。
    assert AL._step_line(2, {"a": 1}, {"b": 2}) == \
        AL._spoken_half(2, {"a": 1}) + AL._result_half({"b": 2})
    assert "[第 1 步] 你说了：" in run.transcript and "框架执行结果：" in run.transcript, \
        run.transcript[:200]
    # 会话记录里的步事件没有多出"另存一份序列"的键：序列是从它们重建得出来的
    # （第 ② 步要做的事），不是靠多写一份来保证。这一条钉的就是"不另存一份"。
    with open(_root / "sessions" / "t-render.jsonl", encoding="utf-8") as fh:
        events = [json.loads(ln) for ln in fh if ln.strip()]
    steps = [e for e in events if e.get("kind") == "agent_step"]
    assert steps, "一步的 `agent_step` 事件都没有 ⇒ 夹具没跑到那一步"
    assert all("messages" not in e and "sequence" not in e for e in steps), \
        "步事件里另存了序列 ⇒ 那就有两份真身（可重建的东西不该另存）"


def test_an_interjection_is_a_user_message(tmp_path: pathlib.Path) -> None:
    """正控（角色归属）：插话进序列时是 `user` 那条 —— 它是"人对我说的"。"""
    seg = AL._interjection_block([{"subject": "叫停", "body": "先停下",
                                   "tone": "stop", "from": "user"}])
    msg = AL.user_message(seg)
    assert msg["role"] == "user" and seg in msg["content"], msg
    # 序列里 user 那条不掺工具配对（配对判据只认 assistant/tool 两两成对）
    assert AL.message_sequence_problem([AL.user_message(seg), AL.assistant_message(
        0, {"tool": "fs.read"}, content="x"), AL.tool_message(0, "y")]) == ""

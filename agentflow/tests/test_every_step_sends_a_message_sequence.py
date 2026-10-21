"""判据：每一步发给模型的是消息序列（S-C 第 ① 步 / 业主 2026-10-10 裁定 5甲）。

换的：`transcript: str` 不再是唯一历史载体。循环里那份历史现在是 `messages: list[dict]`
（`role: user / assistant / tool`），assistant 那条带结构化的 `tool_calls`（`id` 由步号派生，所以
从会话记录里重建得回来），tool 那条带 `tool_call_id`；`run.messages` 是这一趟的序列读数。搬运
来源是 DSH 的 messages —— assistant 带 `tool_calls`、tool 带 `tool_call_id`
（`dsh-agent-loop/lib/index.js` 的 loop 消息面；判别式那一族见 `draft/100` §3）。

没换的：念出来的那份文本。`render_messages(messages) == run.transcript` 由构造保证（`_spoken_half` /
`_result_half` 是那两个"半句"的唯一拼法，`_step_line` 也由它们拼出来）—— 于是 `run.transcript` 的
读者（Web UI 的事件回放、续跑、`--resume`）这一步之后拿到的东西一个字没变。整序列化与
`resume_messages`（逐条相等）是第 ② 步。

判据六条：1. 正控：两步的循环里，第二步发给模型的是 `[system, user, assistant(tool_calls), tool]`，
且 tool 的 `tool_call_id` 等于 assistant 给的 id（`system` 走 `LlmSeam` 的 `system=` 那一格，不在
序列里）。2. 负控：把 tool 挂到错的 id ⇒ 配对判据当场红（`message_sequence_problem`）。3. 反真空：
序列里 assistant 那条必须带工具调用（否则这条判据只测了拼接）。4. 正控（渲染逐字相同）：
`render_messages(run.messages) == run.transcript`。5. 正控（插话是 user 消息）：插话进序列时是
`user` 那条 —— 它是"人对我说的"，不是工具结果（改前它只是拼进字符串的一段）。6. 负控（角色词表）：
序列里出现第四种角色 ⇒ 配对判据点名（词表只有三个）。"""

from __future__ import annotations

import json
import pathlib

from agentflow import agent_loop as AL
from agentflow.agent_loop import run_role
from agentflow.llmseam import LlmSeam
from test_agent_loop import _events, _wired


def _reply(obj: dict) -> str:
    return json.dumps(obj, ensure_ascii=False)


def _two_step_run(tmp_path: pathlib.Path, sid: str = "t-msg",
                  price: tuple[float, float] = (0.0, 0.0)):
    """跑两步：第 0 步调一个工具、第 1 步收工（第二步的序列才是要看的那一份）。

    `price` 决定花销涨不涨 —— 裁定 J=乙 那一轴（system 里那两格会变的事实）靠它分开。
    """
    st, cond, registry, gw, root = _wired(
        tmp_path, {"M": [_reply({"tool": "conductor.role_spec", "args": {"role_name": "C"},
                                 "why": "先看一眼 C 的规格"}), _reply({"final": "收工"})]},
        max_steps=3, price=price)
    run = run_role("M", "看两步的消息序列", store=st, registry=registry, conductor=cond,
                   seam=LlmSeam(role="M", session_root=root, gateway=gw["M"],
                                price=price, sid=sid),
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


# ============================================================ 12-A：思维链原样带回去


class _ThinkingGateway:
    """照剧本回答，并在每条回复里带一段"我先想……"（12-A=乙 要带回去的那一段）。"""

    spec = type("Spec", (), {"model": "scripted-thinking", "api_key": "fake"})()

    def __init__(self, replies: list[str], thoughts: list[str]) -> None:
        self.replies = list(replies)
        self.thoughts = list(thoughts)
        self.prompts: list[str] = []
        self.systems: list[str] = []

    def complete(self, prompt: str, *, scope: str = "", system: str | None = None,
                 **kw: Any) -> Any:
        self.prompts.append(prompt)
        self.systems.append(str(system or ""))
        i = min(len(self.prompts) - 1, len(self.replies) - 1)
        thought = self.thoughts[min(len(self.prompts) - 1, len(self.thoughts) - 1)]
        return type("Reply", (), {"ok": True, "text": self.replies[i], "reasoning": thought,
                                  "tokens_in": 7, "tokens_out": 7,
                                  "error_detail": "", "error_kind": ""})()


def _thinking_run(tmp_path: pathlib.Path, thoughts: list[str], sid: str = "t-think"):
    st, cond, registry, _gw, root = _wired(
        tmp_path, {"M": [_reply({"tool": "conductor.role_spec", "args": {"role_name": "C"},
                                 "why": "先看一眼 C 的规格"}), _reply({"final": "收工"})]},
        max_steps=3)
    gw = _ThinkingGateway([_reply({"tool": "conductor.role_spec", "args": {"role_name": "C"},
                                   "why": "先看一眼 C 的规格"}), _reply({"final": "收工"})],
                          thoughts)
    run = run_role("M", "带着心里话跑两步", store=st, registry=registry, conductor=cond,
                   seam=LlmSeam(role="M", session_root=root, gateway=gw,
                                price=(0.0, 0.0), sid=sid),
                   workspace_root=str(root), sid=sid, from_env=False)
    return run, gw, root


def test_the_thinking_is_carried_back_verbatim(tmp_path: pathlib.Path) -> None:
    """正控（12-A=乙）：上一段"我先想……"下一轮原样带回去（它记得自己想过什么）。

    两处一起判：① 序列里 assistant 那条带 `reasoning_content`；② 下一个提示词里真的
    念了出来（DSH 靠消息字段带回去，我们的传输面是一段文本 ⇒ 它必须出现在 prompt 里）。
    """
    thought = "我先想：C 是只读角色，规格读一次就够，别重复问。"
    run, gw, _root = _thinking_run(tmp_path, [thought])
    assistant = run.messages[1]
    assert assistant["role"] == "assistant", assistant
    assert assistant.get("reasoning_content") == thought, assistant
    assert thought in gw.prompts[1], gw.prompts[1][:400]
    assert "[第 1 步] 我先想：" in gw.prompts[1], gw.prompts[1][:200]
    assert AL.message_sequence_problem(run.messages) == ""


def test_no_thinking_means_no_thinking_block(tmp_path: pathlib.Path) -> None:
    """负控（不许凭空造一格）：没给思维链 ⇒ 序列里没有那一格、提示词里也没有那一行。

    "它没想"与"它想了但原文丢了"必须分得开 —— 凭空写一个空的"我先想"会让两者同形。
    """
    run, gw, _root = _thinking_run(tmp_path, [""])
    assert "reasoning_content" not in run.messages[1], run.messages[1]
    assert "我先想" not in gw.prompts[1], gw.prompts[1][:300]
    assert AL.render_messages(run.messages) == run.transcript


def _budget_line(prompt: str) -> str:
    """user 提示词里那一行"剩余花销预算"（没有就空串）。"""
    return next((ln for ln in prompt.splitlines() if ln.startswith("剩余花销预算：")), "")


def test_the_changing_facts_go_to_the_user_message_not_the_system(tmp_path: pathlib.Path) -> None:
    """静态/动态分离（2026-10-19）：会变的两格走 user 消息，system 逐字节稳定。

    改前这里是裁定 J=乙 的判据：花销涨了 ⇒ system 必须换（`systems[0] != systems[1]`）。动机是对的（模型
    得看见最新余额），但它把 `budget_left` / `notebook` 留在 system 里 ⇒ 几乎每步整条前缀都变 ⇒ 上游的
    前缀缓存（`prompt_cache_hit_tokens`）结构上永不命中（实测 M 岗：54,902 字的 system 从第 35,035 个
    字符起就不同，差异正是"已用 0.000000 → 0.001200"）。现在这两格的值在每步的 user 消息尾部现读，
    system 里留一段静态指路语：两半都还在，只换了载体 ——「模型据以决策的数是新的」由 user 提示词守
    （"草稿本"也在这里现读），「前缀别每步都换」由 system 逐字节相同守（旧契约允许变，新要求更强）。

    三跳：1. 正控（前缀稳定）：非零价 ⇒ 花销每步都涨，而 system 必须逐字节相同；2. 正控（真话没丢）：
    那个数字换到了这一步的 user 消息里，而且真的是新的（第 0 步 `已用 0.000000`、第 1 步不是它）；
    3. 读数：两趟都不该出现"system 在步边界上变了"的红灯 —— 只在有人把每步会变的东西塞回 system 时才该出现（负控在新判据文件里）。"""
    run, gw, root = _two_step_run(tmp_path / "charged", sid="test-run", price=(1.0, 2.0))
    assert run.stop_reason == "final", run.to_dict()
    systems = gw["M"].systems
    prompts = gw["M"].prompts
    assert len(systems) >= 2 and len(prompts) >= 2, (systems, prompts)

    # ① 前缀稳定：花销涨了，system 却一个字节都不许变。
    assert len(set(systems)) == 1, (
        "花销涨了而 system 也变了 ⇒ 前缀每步都在变，上游前缀缓存永不命中："
        f"{[s[-120:] for s in systems]}")
    # 而且 system 里那两格不是"消失"，是换成了指路语（模型仍然知道去哪儿看）。
    assert "见每步消息末尾的「剩余花销预算」" in systems[1], systems[1][-400:]

    # ② 真话没丢：数字在 user 消息里，而且是新的。
    first, second = _budget_line(prompts[0]), _budget_line(prompts[1])
    assert first and second, (prompts[0][-400:], prompts[1][-400:])
    assert "已用 0.000000" in first, first
    assert first != second, (first, second)
    assert "已用 0.000000" not in second, second
    assert "你的草稿本（最近几条，每一步现读）：" in prompts[1], prompts[1][-400:]

    # ③ 没有红灯读数。
    red = [e for e in _events(root)
           if e.get("kind") == "agent_note" and "system 在步边界上变了" in str(e.get("note"))]
    assert not red, red

    # 负控那一半（价为 0 ⇒ 也不该有任何红灯，也不该换串）
    _run2, gw2, root2 = _two_step_run(tmp_path / "free", sid="test-run", price=(0.0, 0.0))
    assert len(set(gw2["M"].systems)) == 1, (
        "花销没变却换了 system ⇒ 前缀每步都在变，KV cache 全废："
        f"{[s[-80:] for s in gw2['M'].systems]}")
    stale = [e for e in _events(root2)
             if e.get("kind") == "agent_note" and "system 在步边界上变了" in str(e.get("note"))]
    assert not stale, stale


def test_a_long_thought_is_truncated_with_the_marker_in_itself(tmp_path: pathlib.Path) -> None:
    """正控（截断写在消息里）：超长思维链按落档那一把尺截断，标记就在那段文本里。

    施工单 §3 第 4 条：「截断这件事要写进那条消息本身」。这一条同时钉住"进消息的那一份
    与落档的那一份是同一个字符串" —— 少了这半句，重建出来的序列会与当时那份差一截。
    """
    thought = "想" * (AL.RECORD_CHARS + 500)
    run, _gw, root = _thinking_run(tmp_path, [thought], sid="t-long")
    got = run.messages[1].get("reasoning_content") or ""
    assert got.endswith("字）"), got[-40:]
    assert len(got) < len(thought), (len(got), len(thought))
    assert "落档截断" in got, got[-60:]
    rebuilt, step0 = AL.resume_messages(root, "M", "t-long", task="带着心里话跑两步")
    # 这一趟只有第 0 步落过 `agent_step`（收工那一步不落：它走的是收工那一支）
    assert step0 == 1, step0
    assert rebuilt == run.messages, "截断口径在当时与重建两边不一致"
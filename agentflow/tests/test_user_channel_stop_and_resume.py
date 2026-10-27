# -*- coding: utf-8 -*-
"""用户频道「停着」与「可续跑」的判据：问 → 停 → 答 → 续（离线，替身模型）。
## 这一组守什么（以及它是谁的判据）
用户 2026-10-03 的裁定：「就停着」—— 问了就要停在那里，不许超时之后继续往下跑。这一组把那条裁定钉成可复核的读数，一共三件事：
1. 「停」：`ask_user` 没拿到回答时，这一趟以 `stop_reason="waiting_for_user"` 停下，`waiting_for` 记下问题号，并且「不再发任何模型请求」（"停着 = 不烧钱"的判据：
数会话里的 `llm_call` 事件条数，再断言没有新的）。2. 「答」：人通过 `agentflow answer`（`--select` / `--custom` / 位置参数三条路）
写下的那句话，`--resume` 那一段看到的上下文里读得到，而且那一趟真的跑到 `final`。3. 「续」：`resume_messages` 重建出来的消息序列与循环里那一份「逐字相等」 ——
否则"续跑"会变成"换一段稍微不同的话接着问"，而没有任何判据看得见那个漂移。
## 负控清单（每一条都对着一个"看起来能用、其实是假的"形态）
- 没回答就 `--resume`：必须明确报"还在等 qid"，一步模型都不调（不许静默重跑，不许把"没答"当成默许）；- 任务指纹不符：`checkpoint_mismatch` + CLI 退出码 2 + 零模型调用；-
无人值守档（`ASK_POLICY="unattended"`，历史别名 `"never"`）：`ask_refused`、问题「不落」待答清单、循环继续；- 非主控角色问用户（`not_conductor`）：问题不落盘、
循环继续，未决问题写进结果 ——这一条是「运行时协作纪律」，出处是我们自己的 `DESIGN-CONDUCTOR.md` §1.1（"它是用户唯一面对的东西"）与
`capabilities.NON_SUMMONABLE = {"M"}`。被召唤的一环与"顶层但不是主控"（人工直接 `run-agent D`）都被拒；只有主控能问 —— 否则"人机通道归主控"这条纪律没有判据看着；- 别的
sid 的回答不算这一趟的（`read_replies(sid=…)` 隔离）。
## 用的是替身模型，不联网、不花钱
替身（`ScriptedGateway`）与真模型同接口（`complete(prompt, *, scope, system)`），照剧本回话。所以这一组验的是「框架行为」（停、答、续），
不是"模型据此改主意了"——后者要一次真机。
"""
from __future__ import annotations

import json
import pathlib
import re
from argparse import Namespace
from typing import Any

import pytest

from agentflow import agent_loop as AL
from agentflow import cli
from agentflow import sessions as SS
from agentflow import userio as U
from agentflow.conductor import Conductor, LocalBackend
from agentflow.llmseam import LlmSeam
from agentflow.store import Store
from agentflow.tokenmeter import TokenMeter
from agentflow.tools import build_registry
from agentflow.tools.conductor_tools import reset_cache

#: 由模型驱动的动作（其余动作仍走 Python 实现）。空表就够：这一组的角色动作
#: 一次都没被调用过 —— 走的是循环自己的形状（`ask_user` / `note` / `final`）。
LOOPS: dict[tuple[str, str], dict[str, Any]] = {}

#: 剧本：角色 → 一串回复（替身按次序取，取完重复最后一条）。
SCRIPTS: dict[str, list[str]] = {}


class ScriptedGateway:
    """照剧本回答的替身模型（写法照抄 `tests/test_agent_loop.py` 的 `ScriptedGateway`）。"""

    spec = type("Spec", (), {"model": "scripted", "api_key": "fake"})()

    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)
        self.prompts: list[str] = []
        self.systems: list[str] = []

    def complete(self, prompt: str, *, scope: str = "", system: str | None = None,
                 **kw: Any) -> Any:
        """记下这一问（判据要数它），回剧本里的下一条。"""
        self.prompts.append(prompt)
        self.systems.append(str(system or ""))
        text = self.replies[min(len(self.prompts) - 1, len(self.replies) - 1)]
        return type("Reply", (), {"ok": True, "text": text, "tokens_in": 7, "tokens_out": 7,
                                  "error_detail": "", "error_kind": ""})()


class _StopAfterNth(ScriptedGateway):
    """答到第 `n` 条时把停机开关写下 —— 用真实的叫停通道把这一趟停在第 `n` 步。

    为什么需要它：裁定 12-K 之后步数不再收工，于是"把一趟停在第 3 步"这件事
    不能再靠 `max_steps`。停机开关是循环里真的会停的那条路（`stop_file`），
    而且它的检查点在每一步的开头：第 `n` 条回答时写下开关 ⇒ 第 `n + 1` 步的开头
    读到它 ⇒ 恰好做完 `n` 步。
    """

    def __init__(self, replies: list[str], root: pathlib.Path, n: int) -> None:
        super().__init__(replies)
        self.root = root
        self.n = n
        self.fired = False

    def complete(self, prompt: str, *, scope: str = "", system: str | None = None,
                 **kw: Any) -> Any:
        if len(self.prompts) == self.n - 1 and not self.fired:
            from agentflow import stopctl

            stopctl.request_stop(self.root, reason="判据：够步数了")
            self.fired = True
        return super().complete(prompt, scope=scope, system=system, **kw)


def ask(text: str = "口径用哪个？", *, timeout: float | None = 0,
        options: Any = None, header: str = "口径") -> str:
    """一条 `ask_user` 剧本行；`timeout=None` 表示不给 `timeout_sec`（吃框架缺省）。"""
    body: dict[str, Any] = {"question": text, "header": header}
    if timeout is not None:
        body["timeout_sec"] = timeout
    if options is not None:
        body["options"] = options
    return json.dumps({"ask_user": body}, ensure_ascii=False)


FINISH = json.dumps({"final": "收工", "evidence": [],
                     "notify": {"to": "M", "summary": "收工：见 final",
                                "body": "## 结论\n收工。\n"}}, ensure_ascii=False)
NOTE = json.dumps({"note": "我先记一句"}, ensure_ascii=False)


def _ws(tmp_path: pathlib.Path, sid: str = "t") -> tuple[Store, Any, Conductor, pathlib.Path]:
    """一个工作区 + 主控 + 工具层（与 `test_agent_loop._wired` 同一套接线，但没有替身缝）。"""
    st = Store(tmp_path / "ws")
    st.init()
    backend = LocalBackend({})
    cond = Conductor(st, backend=backend)
    registry = build_registry(store=st, conductor=cond, workspace_root=str(st.root)).registry
    return st, registry, cond, st.root


def _run(st: Store, registry: Any, cond: Conductor, root: pathlib.Path,
         replies: list[str], *, role: str = "M", task: str = "把口径定下来",
         max_steps: int = 4, sid: str = "t", resume: bool = False,
         user_timeout_sec: float | None = 0, direct: bool = False,
         my_task_id: str = "", gateway: Any = None) -> tuple[Any, ScriptedGateway]:
    """跑一趟角色循环（用替身模型），返回 `(run, 替身)`。

    `user_timeout_sec=0` 是这一组的缺省：它对应"问了就停"（CLI 的 `--user-wait-sec 0`），
    于是每条判据都不必真的去等人 —— 而"等"这件事本身由 `userio` 的自检覆盖。

    `direct=True` 直接建 `AgentLoop`（绕过 `run_role`）：只有子角色那条判据需要它，
    因为"我有没有父任务号"是 `LlmBackend` 在真实召唤里填的，而这里要把它钉死。
    """
    gw = gateway if gateway is not None else ScriptedGateway(replies)
    seam = LlmSeam(role=role, session_root=root, gateway=gw, price=(0.0, 0.0), sid=sid)
    if direct:
        loop = AL.AgentLoop(role=role, session_root=root, registry=registry, seam=seam,
                            conductor=cond, max_steps=max_steps, sid=sid, store=st,
                            user_timeout_sec=user_timeout_sec)
        return loop.run(task, summoned_by="M", my_task_id=my_task_id, depth=2), gw
    run = AL.run_role(role, task, store=st, registry=registry, conductor=cond, seam=seam,
                      session_root=root, workspace_root=str(root), sid=sid,
                      max_steps=max_steps, from_env=False, user_timeout_sec=user_timeout_sec,
                      resume=resume)
    return run, gw


def _events(root: pathlib.Path, sid: str = "t") -> list[dict]:
    """这段会话的事件（坏行必须为空 —— 否则下面的读数都是在读一份坏文件）。"""
    events, problems = SS.read_session(root, sid=sid)
    assert not problems, problems
    return events


def _llm_calls(root: pathlib.Path, sid: str = "t") -> int:
    """这一段会话里记了几条 `llm_call`（"停着 = 不烧钱"就是数它）。"""
    return len([e for e in _events(root, sid) if e.get("kind") == "llm_call"])


def _args(tmp_path: pathlib.Path, **kw: Any) -> Namespace:
    """CLI 的参数壳（照抄 `tests/test_agent_cli.py::_args`，按需补上新开关）。"""
    base = dict(root=str(tmp_path / "ws"), sid="t", json=False, budget_usd=None, drive=[],
                rounds=1, report_every=1, resume=False, stop_file=None, user_wait_sec=0.0,
                no_ask=False, subagents=False, semantic_review=False, provider=None,
                config=None, wall_clock_sec=3600.0, max_steps=4)
    base.update(kw)
    return Namespace(**base)


def fake_seam_factory(role: str, *, root: pathlib.Path, sid: str | None,
                      usd_budget: float | None, store: Any = None):
    """替身模型工厂（签名与 `cli._agent_seam_factory` 逐字一致：多一个参数会让真机静默不记账）。"""
    gw = ScriptedGateway(SCRIPTS.get(role, [FINISH]))
    return LlmSeam(role=role, session_root=root, gateway=gw, price=(0.0, 0.0), sid=sid,
                   usd_budget=usd_budget,
                   meter=(TokenMeter(store) if store is not None else None))


# ============================================================ 一、停

def test_asking_the_user_stops_the_loop_and_stops_burning_tokens(tmp_path: pathlib.Path):
    """正控（停 + 不烧钱）：问了没人答 ⇒ 停成 `waiting_for_user`，且此后再无模型调用。

    负控写在同一个用例里：替身只被问过一次（`prompts` 长度 1）、会话里只有一条
    `llm_call`、剧本里那条 `final` 一直没被取走 —— 三条同时成立才说明"停住"了。
    旧行为（超时 30 秒后继续）会在这里消耗第二条回复：那正是要废掉的那一档。
    """
    st, registry, cond, root = _ws(tmp_path)
    run, gw = _run(st, registry, cond, root, [ask("口径用哪个？"), FINISH])

    assert run.stop_reason == "waiting_for_user", run.to_dict()
    qid = run.waiting_for
    assert qid and qid == run.steps[0].result.get("asked"), run.to_dict()
    assert run.steps[0].result.get("state") == "pending", run.steps[0].result
    assert "不许把它当成用户同意" in str(run.steps[0].result.get("note") or "")
    assert run.final.startswith(f"停在等 {qid}"), run.final
    assert [q.qid for q in U.pending_questions(root, sid="t")] == [qid]
    # 停着 = 不烧钱：一条 `llm_call`、一次模型提问，之后没有新的
    assert _llm_calls(root) == 1, "停了之后还记了模型调用"
    assert len(gw.prompts) == 1, "停在等之后又发了一次模型请求"
    # 账本读数也钉一下：这一趟的 `waiting_for` 进了 agent_run_end（给 inbox 用）
    ends = [e for e in _events(root) if e.get("kind") == "agent_run_end"]
    assert ends and ends[-1].get("waiting_for") == qid and ends[-1].get("stop_reason") == "waiting_for_user"


def test_zero_wait_through_the_cli_stops_before_the_next_round(tmp_path: pathlib.Path,
                                                               monkeypatch, capsys):
    """负控（问了就停）：`run-agent --user-wait-sec 0` ⇒ 退出码 3、一次调用、不再往下走。

    退出码 3 是"停在等待用户"这一档的落点：它既不是 0（完成）也不是 1（没给出 final
    的失败），更不是 2（没查成）—— 折进任何一档都会让 CI 把"等一个人"读成别的事。
    """
    monkeypatch.setattr(cli, "_agent_seam_factory", fake_seam_factory)
    reset_cache()
    SCRIPTS.clear()
    SCRIPTS.update({"M": [ask("口径用哪个？"), FINISH],
                    "E": [ask("另一岗也想问一句？"), FINISH]})
    rc = cli.cmd_run_agent(_args(tmp_path, role="M", task="把口径定下来"))
    out = capsys.readouterr().out
    assert rc == 3, out
    root = tmp_path / "ws"
    # 提示里给的那条命令必须是「带根、且根写在动词之前」的那一版：
    # 此前这里是 `"agentflow answer" in out`（不带根也能满足），而正是那个写法
    # 让人照抄就报 `unrecognized arguments: --root`（§77 修的三处之一）。
    assert "停在等待用户" in out, out
    assert f"agentflow --root {root} answer" in out, out
    assert _llm_calls(root) == 1, "退出码 3 那一趟不该有第二次模型调用"
    assert len(U.pending_questions(root, sid="t")) == 1
    # `--json` 那一档：退出码同样 3，而 stdout 必须仍然是一份可解析的 JSON
    rc_json = cli.cmd_run_agent(_args(tmp_path, role="M", task="换一件事再问一次",
                                      json=True, sid="t2"))
    captured = capsys.readouterr()
    assert rc_json == 3, (captured.out, captured.err)
    payload = json.loads(captured.out)
    assert payload["stop_reason"] == "waiting_for_user" and payload["waiting_for"], payload
    assert "停在等待用户" in captured.err, captured.err
    # 负控（运行时协作纪律：人机通道归主控，`DESIGN-CONDUCTOR.md` §1.1）：换一个
    # 非主控角色走同一条 CLI 路 —— 它不许停、也不许把问题落进待答清单，
    # 而是把未决问题写进自己的结果，退出码 0（跑完了）。
    rc_e = cli.cmd_run_agent(_args(tmp_path, role="E", task="非主控也想问一句", sid="t3"))
    out_e = capsys.readouterr().out
    assert rc_e == 0, out_e
    assert U.pending_questions(root, sid="t3") == [], "非主控的问题不许落进待答清单"


# ============================================================ 二、答

def test_the_custom_answer_reaches_the_resumed_run(tmp_path: pathlib.Path, capsys):
    """正控（答 → 续）：`agentflow answer <qid> <正文>` 写的那句话，续跑那一段读得到。"""
    st, registry, cond, root = _ws(tmp_path)
    first, _gw = _run(st, registry, cond, root, [ask("这次是审还是研？"), FINISH])
    assert first.stop_reason == "waiting_for_user", first.to_dict()
    qid = first.waiting_for

    rc = cli.cmd_answer(_args(tmp_path, qid=qid, text="审这篇论文", select=None, custom=None))
    assert rc == 0, capsys.readouterr().err
    assert any(r["qid"] == qid and r["answer"] == "审这篇论文"
               for r in U.read_replies(root, role="M", sid="t"))

    second, gw2 = _run(st, registry, cond, root, [FINISH], resume=True)
    assert second.stop_reason == "final", second.to_dict()
    assert second.resumed_from == 1, second.to_dict()   # 从第 2 步接着跑，不重做第 1 步
    # 续跑那一段接着上次那份对话：开场之后那几条消息逐条相同。
    # 开场那一条会变是对的（2026-10-21）：`user_replies` / `inbox` 都现读 ——
    # 用户刚答的那一句必须在续跑那一趟听得到（下一条断言），而它此前住在 system 里、
    # 所以在 transcript 里看不见；现在它进了开场那条 user 消息。
    assert second.messages[:len(first.messages)][1:] == first.messages[1:], (
        "续跑那一段没有接着上次那份对话", second.messages[:2], first.messages[:2])
    # 用户那句话进的是开场那条 user 消息里的「用户回答过的问题」那一栏
    # （2026-10-21 起它从 system 挪了出来；信息没丢，只是换了位置）。
    assert "审这篇论文" in gw2.prompts[0], "用户那句话没有进续跑那一段看到的上下文"
    assert "审这篇论文" not in gw2.systems[0], "回答还在 system 里 ⇒ 前缀跨不过 run"
    assert len(gw2.prompts) == 1, "续跑只需要问一次（接着那一步之后）"


def test_the_selected_answer_reaches_the_resumed_run(tmp_path: pathlib.Path, capsys):
    """正控（答 → 续）：`--select <label>` 那条路同样进得了续跑那一段（DSH 的 selected）。"""
    st, registry, cond, root = _ws(tmp_path)
    first, _gw = _run(st, registry, cond, root,
                      [ask("口径用哪个？", options=["n<=5", "全体"]), FINISH])
    qid = first.waiting_for
    rc = cli.cmd_answer(_args(tmp_path, qid=qid, text=None, select=["n<=5"], custom=None))
    assert rc == 0, capsys.readouterr().err
    replies = U.read_replies(root, role="M", sid="t")
    assert replies and replies[-1]["selected"] == ("n<=5",), replies
    second, gw2 = _run(st, registry, cond, root, [FINISH], resume=True)
    assert second.stop_reason == "final", second.to_dict()
    assert "n<=5" in gw2.prompts[0], "选中的 label 没有进续跑那一段看到的上下文"
    assert second.messages[:len(first.messages)][1:] == first.messages[1:], (
        second.messages[:2], first.messages[:2])
    # 负控（别名那条路的反面）：`--custom` 覆盖 selected 时读出来的就是 custom
    other = tmp_path / "ws2"
    other.mkdir()
    q = U.ask_user(other, role="M", question="口径？", options=["甲", "乙"],
                   timeout_sec=0.0, sid="t")
    assert cli.cmd_answer(Namespace(root=str(other), sid="t", qid=q.qid, text=None,
                                    select=["甲"], custom="其实选乙")) == 0
    got = [r for r in U.read_replies(other, sid="t") if r["qid"] == q.qid][0]
    assert got["answer"] == "其实选乙" and got["selected"] == ("甲",), got


def test_resume_messages_is_item_equal_to_the_live_sequence(tmp_path: pathlib.Path):
    """正控（续跑的正确性）：重建出来的消息序列与当时那份逐条相等。

    为什么这条是"最重要的一条"：续跑要给模型的，是「当时那份对话」。差一条、差一个字段，模型看到的处境就变了，而"它是不是接着上次说的往下做"就没有判据了。

    ## 判据形态换过一次（S-C 第 ② 步 / 裁定 5甲），理由留在这里

    改前这里判的是 `rebuilt == run.transcript`（两份字符串逐字节相等），因为当时的历史载体就是一段字符串。S-C 之后载体是消息序列（`run.messages`），字符串只是它的渲染 ⇒
    判据跟着换成"序列逐条相等"，渲染那一句降级成派生读数（它仍然被断言：两条序列相等时渲染必然相等，这是"我的渲染是纯函数"这个前提的读数）。名字也从
    `..._byte_equal_to_the_live_transcript` 改成 `..._item_equal_to_the_live_sequence`：名字在说一件事、断言在说另一件，是本仓反复踩过的形态。
    """
    st, registry, cond, root = _ws(tmp_path)
    # 停法换过一次（裁定 12-K）：改前这里是 `[NOTE]*3` + `max_steps=3`，靠步数闸
    # 把这一趟截停；步数不再收工之后那一支不成立了，于是改用停机开关（那条真的会停的路）：
    # 第 3 条回答时写下开关、第 4 步的开头读到它 ⇒ 做完 3 步停住。
    # 为什么不能改成"第 3 答复一条 final"：final 那一步不落 `agent_step` 事件
    # （它走的是收工那一支），重建出来的就只剩 2 步，而"重建 == 当时那一份"这条判据
    # 衡量的正是"落盘的那几步能不能拼回原样"。
    gw = _StopAfterNth([NOTE, NOTE, NOTE], root, 3)
    run, _gw = _run(st, registry, cond, root, [NOTE, NOTE, NOTE], gateway=gw)
    assert len(run.steps) == 3 and run.stop_reason == "stop_file", run.to_dict()
    rebuilt, step0 = AL.resume_messages(root, "M", "t", task="把口径定下来")
    assert step0 == 3, step0
    assert rebuilt == run.messages, "重建的序列与当时那一份不逐条相等"
    # 派生读数（渲染是纯函数）：两处渲染必须给出同一份文本。
    assert AL.render_messages(rebuilt) == run.transcript, "渲染与那一份文本分家了"
    # 序列本身要真的是序列（不是"一条大 user 消息"充数）：
    assert [m["role"] for m in rebuilt][:3] == ["user", "assistant", "tool"], rebuilt[:3]
    assert AL.message_sequence_problem(rebuilt) == "", rebuilt
    # 负控（不许张冠李戴）：任务原文不匹配 ⇒ 重建不出来，返回 ([], 0) 而不是别人的那一段
    other, other_step = AL.resume_messages(root, "M", "t", task="另一件事")
    assert (other, other_step) == ([], 0), (other[:1], other_step)
    assert AL.resume_transcript(root, "M", "t", task="另一件事") == ("", 0), \
        "薄壳那条路（transcript）与序列那条路必须给出同一档三态读数"


# ============================================================ 三、负控

def test_resuming_without_an_answer_says_it_is_still_waiting(tmp_path: pathlib.Path):
    """负控（不许静默重跑）：没人答就 `--resume` ⇒ 再停一次并点名"还在等 qid"，零调用。

    这一条挡的形态是：续跑那一段看见"我上次问了 q0001、没人答"，于是自己决定
    "按最保守的做法继续" —— 用户 2026-10-03 裁掉的正是它。框架这一层必须钉死：
    没有回答事件，就没有下一步。
    """
    st, registry, cond, root = _ws(tmp_path)
    first, _gw = _run(st, registry, cond, root, [ask("口径用哪个？"), FINISH])
    qid = first.waiting_for
    calls_before = _llm_calls(root)
    second, gw2 = _run(st, registry, cond, root, [FINISH], resume=True)
    assert second.stop_reason == "waiting_for_user", second.to_dict()
    assert second.waiting_for == qid, second.to_dict()
    assert f"还在等 {qid}" in second.final, second.final
    assert gw2.prompts == [], "还没答就续跑，却发了模型请求（把「没答」当成了默许）"
    assert _llm_calls(root) == calls_before, "没答的那一次续跑不该产生模型调用"
    # 答完之后：同一趟续跑就能接着跑（同一个 qid、同一条判据的另一面）
    assert U.answer_question(root, qid=qid, answer="审", sid="t") == ""
    third, _gw3 = _run(st, registry, cond, root, [FINISH], resume=True)
    assert third.stop_reason == "final" and third.resumed_from == 1, third.to_dict()


def test_a_different_task_is_refused_by_the_fingerprint(tmp_path: pathlib.Path,
                                                       monkeypatch, capsys):
    """负控（指纹）：任务原文变了就拒绝续跑 ⇒ 退出码 2，且一条模型调用都不产生。"""
    monkeypatch.setattr(cli, "_agent_seam_factory", fake_seam_factory)
    reset_cache()
    SCRIPTS.clear()
    SCRIPTS.update({"M": [ask("口径用哪个？"), FINISH]})
    assert cli.cmd_run_agent(_args(tmp_path, role="M", task="第一件事")) == 3
    capsys.readouterr()
    root = tmp_path / "ws"
    calls_before = _llm_calls(root)
    rc = cli.cmd_run_agent(_args(tmp_path, role="M", task="完全不同的第二件事", resume=True))
    captured = capsys.readouterr()
    assert rc == 2, (captured.out, captured.err)
    assert "checkpoint_mismatch" in (captured.out + captured.err), (captured.out, captured.err)
    assert _llm_calls(root) == calls_before, "指纹不符却发起了模型调用"
    refused = [e for e in _events(root) if e.get("resume_refused")]
    assert refused and refused[-1]["resume_refused"] == "checkpoint_mismatch", refused


def test_the_unattended_policy_refuses_and_keeps_going(tmp_path: pathlib.Path, monkeypatch):
    """负控（无人值守档）：`ASK_POLICY="unattended"` ⇒ `ask_refused`、问题不落盘、循环继续。

    历史别名 `"never"` 那一档也要照样拒（老配置/老调用方写得出来），
    所以这条判据把两个取值都跑一遍 —— 别名只许等价，不许变成"问一下试试"。
    """
    for value in ("unattended", "never"):
        monkeypatch.setattr(U, "ASK_POLICY", value)
        st, registry, cond, root = _ws(tmp_path / value)
        run, gw = _run(st, registry, cond, root, [ask("这条要不要问用户？"), FINISH])
        step = run.steps[0].result
        assert step.get("problem") == U.ASK_REFUSED and step.get("state") == "refused", (value, step)
        assert "本该问用户但没人可问" in str(step.get("note") or ""), step
        assert U.pending_questions(root, sid="t") == [], "确定性拒绝却把问题落进了待答清单"
        assert run.stop_reason == "final", "无人值守档是确定性拒绝，不是停机"
        assert len(gw.prompts) == 2, "拒绝之后循环必须继续（要一次普通工具结果）"


def test_no_ask_through_the_cli_keeps_running(tmp_path: pathlib.Path, monkeypatch, capsys):
    """负控（CLI 的无人值守档）：`run-agent --no-ask` ⇒ 提问被确定性拒绝，循环跑完（退出码 0）。

    这一条同时钉住"CLI 把档位显式传下去"这件事：`--no-ask` 不许靠改模块全局实现
    （那样一个进程里跑第二趟会继承上一趟的档位），所以这里刻意「不动」 `U.ASK_POLICY`。
    """
    monkeypatch.setattr(cli, "_agent_seam_factory", fake_seam_factory)
    reset_cache()
    SCRIPTS.clear()
    SCRIPTS.update({"M": [ask("这条要不要问用户？"), FINISH]})
    rc = cli.cmd_run_agent(_args(tmp_path, role="M", task="无人值守地做", no_ask=True))
    out = capsys.readouterr().out
    assert rc == 0, out
    root = tmp_path / "ws"
    assert U.pending_questions(root, sid="t") == [], "无人值守档却把问题落进了待答清单"
    ends = [e for e in _events(root) if e.get("kind") == "agent_run_end"]
    assert ends and ends[-1].get("stop_reason") == "final", ends
    assert U.ASK_POLICY == "ask", "CLI 的 --no-ask 不该改模块全局（会渗到同一进程的第二趟）"


def test_only_the_conductor_may_ask_the_user(tmp_path: pathlib.Path):
    """正控 + 两条负控（运行时协作纪律）：只有主控能当面问人。

    依据是我们自己的设计，不是外来的：`DESIGN-CONDUCTOR.md` §1.1 逐字"它是用户唯一面对的东西"（用户只对主控说话），而
    `capabilities.NON_SUMMONABLE = {"M"}` 让它在结构上成立（主控不可被召唤 ⇒ 永远是顶层入口）。

    三条一起判，才说明判据是"角色是不是主控"：① 被召唤的一环（有父任务号）问 ⇒ `not_conductor`，问题不落盘，循环继续；② 顶层但不是主控（人工直接 `run-agent D` 那条路）问 ⇒ 同样被拒
    ——这一条是本轮改的那个口子：旧判据只看"有没有父任务号"，于是顶层 D 被当成"用户通道"，与 §1.1 冲突（那条路是运维/测试路径）；③ 主控问 ⇒ 通到待答清单，并且这一趟停下来等人（否则"人机通道"不可达）。
    """
    st, registry, cond, root = _ws(tmp_path)
    # ① 被召唤的一环
    child, gw_child = _run(st, registry, cond, root, [ask("子角色想直接问用户？"), FINISH],
                           role="D", direct=True, my_task_id="t-0001")
    step = child.steps[0].result
    assert step.get("problem") == "not_conductor", step
    assert "交回召唤者" in str(step.get("note") or ""), step
    assert U.pending_questions(root, sid="t") == [], "非主控的提问不许落盘"
    assert child.stop_reason == "final", "这一档不许停循环"
    assert len(gw_child.prompts) == 2, "拒绝之后循环必须继续"
    # ② 顶层但不是主控（旧判据在这里放过）
    top_d, _gw_d = _run(st, registry, cond, root, [ask("顶层 D 问一句？"), FINISH],
                        role="D", direct=True, my_task_id="")
    assert top_d.steps[0].result.get("problem") == "not_conductor", top_d.steps[0].result
    assert U.pending_questions(root, sid="t") == [], "非主控的提问不许落盘"
    assert top_d.stop_reason == "final", top_d.to_dict()
    # ③ 主控
    boss, _gw_m = _run(st, registry, cond, root, [ask("口径用哪个？"), FINISH],
                       role="M", direct=True, my_task_id="")
    assert boss.stop_reason == "waiting_for_user", boss.to_dict()
    assert [q.qid for q in U.pending_questions(root, sid="t")] == [boss.waiting_for]


def test_an_answer_from_another_session_does_not_count(tmp_path: pathlib.Path):
    """负控（不许串味）：别的 sid 里写下的回答，不算这一趟的。

    这一条挡的形态是"同一件事在别的会话里被答过了"被读成"这一趟可以往下跑" ——
    真机每一趟都有自己的 sid，跨会话读回答等于把别人的决定当成自己的。
    """
    root = tmp_path / "ws"
    root.mkdir()
    q = U.ask_user(root, role="M", question="口径用哪个？", timeout_sec=0.0, sid="real1")
    # 同号回答写在另一段会话里：它在两段会话里都不算数（real2 里没人问过这个号）
    assert U.answer_question(root, qid=q.qid, answer="别的会话的答案", sid="real2") == ""
    assert U.read_replies(root, sid="real1") == [], "读到了别的会话的回答"
    assert U.read_replies(root, sid="real2") == [], "答一个没问过的号也被算成回答了"
    assert [x.qid for x in U.pending_questions(root, sid="real1")] == [q.qid], "待答状态被别的会话搅了"
    # 正控（同一段会话里它是算数的）：答在本段 ⇒ 立刻读得到，且不再待答
    assert U.answer_question(root, qid=q.qid, answer="本会话的答案", sid="real1") == ""
    assert [r["answer"] for r in U.read_replies(root, sid="real1")] == ["本会话的答案"]
    assert U.pending_questions(root, sid="real1") == []


def test_a_refused_resume_does_not_swallow_the_transcript(tmp_path: pathlib.Path):
    """负控（真机撞出来的序列）：问 → 「又续了一次（还是没人答）」 → 答 → 续 ⇒ 必须跑到 final。

    这一条是外部验收（`temp/_user_end_verify.py` 的 loop 腿）撞出来的缺陷的回归：
    "被拒的续跑"也会落一条 `agent_run_start`，而 `resume_transcript` 原来取的是
    "最后一条 run_start 之后"的步 —— 于是那条「没有步」的 run_start 把能续的那一段
    吞掉了，等用户真的答完时续跑报 `resume_no_transcript`。

    用户会走的路径恰恰是这一条（问了 → 等一下又跑了一次 → 还是没人答 → 我答了 → 续），
    所以它必须有一条判据钉住，而不是靠"重建函数看起来对"。
    """
    st, registry, cond, root = _ws(tmp_path)
    first, _gw = _run(st, registry, cond, root, [ask("审阅这篇论文，口径？"), FINISH])
    assert first.stop_reason == "waiting_for_user", first.to_dict()
    qid = first.waiting_for
    # B：没人答就再续一次 ⇒ 再停一次（不调模型、不重跑）
    again, gw_b = _run(st, registry, cond, root, [FINISH], resume=True)
    assert again.stop_reason == "waiting_for_user" and again.waiting_for == qid, again.to_dict()
    assert gw_b.prompts == [], "没答的那次续跑不该发模型请求"
    # 那两条被拒的续跑各留了一条 run_start，而它们「不是」本趟的起点
    starts = [e for e in _events(root) if e.get("kind") == "agent_run_start"]
    assert sum(1 for e in starts if e.get("resume_refused")) == 1, starts
    assert sum(1 for e in starts if "resumed_from" in e) == 1, starts
    # C：用户答了
    assert cli.cmd_answer(_args(tmp_path, qid=qid, text=None, select=None,
                                custom="全留")) == 0
    rebuilt, step0 = AL.resume_transcript(root, "M", "t", task="把口径定下来")
    assert step0 == 1, f"重建被那条没有步的 run_start 吞掉了：{step0}（{rebuilt[-80:]!r}）"
    # D：再续 ⇒ 必须接着第 2 步跑到 final
    final_run, gw_d = _run(st, registry, cond, root, [FINISH], resume=True)
    assert final_run.stop_reason == "final", final_run.to_dict()
    assert final_run.resumed_from == 1, final_run.to_dict()
    assert "全留" in gw_d.prompts[0], "用户那句话没有进续跑那一段看到的上下文"
    assert len(gw_d.prompts) == 1


def test_the_checkpoint_round_trips_and_names_the_waiting_question(tmp_path: pathlib.Path):
    """正控（检查点可读）：停下来时的那份检查点能读回，且带着"停在等谁"。

    这是 `--resume` 的输入面：读不到它（或读到的 `waiting_for` 是空的），
    上面那条"没答就续跑要报还在等"的判据就无从判起。
    """
    st, registry, cond, root = _ws(tmp_path)
    first, _gw = _run(st, registry, cond, root, [ask("口径用哪个？"), FINISH])
    cp = AL.load_run_checkpoint(root, "M", "t")
    assert cp is not None, f"检查点没写成：{AL.run_checkpoint_path(root, 'M', 't')}"
    assert cp["step"] == 1 and cp["stop_reason"] == "waiting_for_user", cp
    assert cp["waiting_for"] == first.waiting_for, cp
    assert cp["fingerprint"] == AL._task_fingerprint("M", "把口径定下来"), cp
    assert AL.run_checkpoint_path(root, "M", "t").name == "agent-M-t.json"
    # 负控（读不到就说读不到）：别的 sid 读不到这一趟的检查点
    assert AL.load_run_checkpoint(root, "M", "另一个会话") is None
    assert AL.load_run_checkpoint(root, "E", "t") is None


# ============================================================ 四、完整人机环（走 CLI 的 argv）

def _cli_factory(made: list[ScriptedGateway], *rounds: dict[str, list[str]]):
    """造一个"把每个替身也留一份"的模型缝工厂（签名与 `cli._agent_seam_factory` 逐字一致）。

    与 `fake_seam_factory` 的两点区别：

    - `made` 里留下造出来的替身，这样判据才能在「续跑那一段」上读 `systems` ——
      人答的那句话进的是系统提示那一格，不在 transcript 里（既有接线；
      `test_interaction` 里那条迟到回答的判据同源）；
    - 剧本按「第几个替身」给：`--resume` 那一段是一个「新」的替身（新进程 / 新一趟），
      它拿到的剧本是下一个 `rounds` —— 拿同一份剧本会让续跑那一段又把同一个问题问一遍
      （那正是本判据第一次跑出来的形态：退了 3 而不是 0）。
    """
    def factory(role: str, *, root: pathlib.Path, sid: str | None,
                usd_budget: float | None, store: Any = None):
        idx = min(len(made), len(rounds) - 1)
        gw = ScriptedGateway(rounds[idx].get(role, [FINISH]))
        made.append(gw)
        return LlmSeam(role=role, session_root=root, gateway=gw, price=(0.0, 0.0), sid=sid,
                       usd_budget=usd_budget,
                       meter=(TokenMeter(store) if store is not None else None))
    return factory


def _hint_commands(hint: str) -> list[str]:
    """把提示里反引号包起来的 `agentflow …` 命令摘出来（人照着敲的就是它们）。"""
    return [c for c in re.findall(r"`([^`]+)`", hint) if c.startswith("agentflow ")]


def _argv_of(cmd: str) -> list[str]:
    """把一条 `agentflow …` 命令切回 argv。

    刻意不用 `shlex.split`：Windows 路径里有反斜杠，posix 规则会把 `\\I` 当转义吃掉，
    切出来的 root 就不是原来那一个了（"判据自己把路径改坏"是最难查的形态之一）。
    """
    parts = re.findall(r'"[^"]*"|\S+', cmd)[1:]        # 去掉开头的 `agentflow`
    return [p[1:-1] if p.startswith('"') and p.endswith('"') else p for p in parts]


def test_the_whole_human_loop_runs_through_the_cli_argv(tmp_path: pathlib.Path,
                                                        monkeypatch, capsys):
    """正控（完整人机环，走 CLI 的 argv）：提问 → 停 → inbox 看到 → answer → --resume → final。

    为什么必须有一条"整环"的判据，而不是四条各自为政的：`draft/37` §73 起这一组的
    其余判据大多在库层（`AL.run_role`）验同一批语义，而人用的是命令行。分成四段之后，
    "每一段都对、连起来走不通"这种缺陷没有任何一条判据看得见 —— 例如提示里给的命令
    带了一个 argparse 不认的写法（`--root` 写在动词之后），四段判据全绿，而人照抄就报错。

    这一条把四步串起来跑，并在每一步都数一次模型调用：
    停着的时候不许烧钱（①之后是 1 条），inbox 看一眼不许烧钱，answer 那一下也不许烧钱。
    """
    task = "把口径定下来"
    ws = tmp_path / "ws"
    made: list[ScriptedGateway] = []
    monkeypatch.setattr(cli, "_agent_seam_factory",
                        _cli_factory(made, {"M": [ask("口径用哪个？", options=["n<=5", "全体"]),
                                                   FINISH]},
                                     {"M": [FINISH]}))
    reset_cache()
    head = ["--plain", "--root", str(ws)]

    # ① 提问 ⇒ 停：退出码 3，且只调过一次模型
    rc1 = cli.main(head + ["run-agent", "M", "--task", task, "--sid", "u1",
                           "--user-wait-sec", "0", "--max-steps", "4"])
    out1 = capsys.readouterr().out
    assert rc1 == 3, out1
    assert "停在等待用户" in out1, out1
    end1 = [e for e in _events(ws, "u1") if e.get("kind") == "agent_run_end"][-1]
    qid = end1["waiting_for"]
    assert end1["stop_reason"] == "waiting_for_user" and qid, end1
    stopped_calls = _llm_calls(ws, "u1")
    assert stopped_calls == 1, f"停下时已经有 {stopped_calls} 次模型调用"
    # 守的是「收到过 prompt 的缝只有一份、而且只收到一则」，不是「造出来的缝恰好一份」：
    # `run-agent` 装配期先建一份缝核对 `.wired`，循环启动时再建一份（实测两份、只有一份
    # 收到过 prompt）。造几份缝与烧钱无关，收到几条 prompt 才有关 —— 所以按"用过的缝"
    # 数，判据强度不变（有第二则可疑请求时它照样红）。
    used = [gw for gw in made if gw.prompts]
    assert len(used) == 1 and len(used[0].prompts) == 1, (
        f"停了之后又发过模型请求：造了 {len(made)} 份缝，"
        f"收到过 prompt 的有 {len(used)} 份 / {[len(gw.prompts) for gw in used]} 则")

    # ② inbox（刻意不带 --sid）：跨会话也看得到，且把选项打出来给人照抄
    rc2 = cli.main(head + ["inbox"])
    out2 = capsys.readouterr().out
    assert rc2 == 0, out2
    assert qid in out2 and "u1" in out2, out2
    assert "n<=5" in out2, f"inbox 没把选项打出来，人就无从照抄 --select：{out2}"
    assert _llm_calls(ws, "u1") == stopped_calls, "看一眼 inbox 竟然又调了模型"

    # ③ answer：写进一条回答，同样不花模型调用
    rc3 = cli.main(head + ["answer", qid, "--sid", "u1", "--custom", "三处都保留"])
    cap3 = capsys.readouterr()
    assert rc3 == 0, (cap3.out, cap3.err)
    replies = U.read_replies(ws, role="M", sid="u1")
    assert [r["qid"] for r in replies] == [qid], replies
    assert replies[0]["answer"] == "三处都保留" and replies[0]["selected"] == (), replies
    assert _llm_calls(ws, "u1") == stopped_calls, "回答这一下不该产生模型调用"
    assert U.pending_questions(ws, sid="u1") == []

    # ④ --resume：接着那一步跑到 final，退出码 0，人那句话进上下文
    rc4 = cli.main(head + ["run-agent", "M", "--task", task, "--sid", "u1",
                           "--user-wait-sec", "0", "--max-steps", "4", "--resume"])
    out4 = capsys.readouterr().out
    assert rc4 == 0, out4
    end4 = [e for e in _events(ws, "u1") if e.get("kind") == "agent_run_end"][-1]
    assert end4["stop_reason"] == "final", end4
    starts = [e for e in _events(ws, "u1") if e.get("kind") == "agent_run_start"]
    assert any("resumed_from" in e for e in starts), starts
    used4 = [gw for gw in made if gw.prompts]
    assert len(used4) == 2, f"续跑那一段没有另起一份被用过的缝（收到过 prompt 的：{len(used4)}）"
    assert "三处都保留" in used4[1].prompts[0], "人答的那句话没进续跑那一段的上下文"
    assert len(used4[1].prompts) == 1, "续跑应当只问一次（接着那一步之后）"


def test_the_commands_printed_in_the_hint_actually_run(tmp_path: pathlib.Path,
                                                       monkeypatch, capsys):
    """正控（提示里的命令必须真能跑）+ 负控（旧写法必须被 argparse 拒）。

    为什么值得单钉一条：`_waiting_notice` 打出来的三条命令是「人此刻唯一的下一步」，
    而它们不像别的东西那样会被评审看见 —— 没人会把提示里的命令抄进终端再跑一遍
    （实测：2026-10-03 才发现 `--root` 被写在动词后面，照抄得到
    `error: unrecognized arguments: --root …`、退出码 2，看着像命令不存在）。

    做法：把那一刻打出来的命令「逐条摘出来真跑」，再断言旧写法确实会被拒 ——
    后半条是这条判据的反真空：没有它，"提示对不对"就只是"我读过一遍"。
    """
    task = "把口径定下来"
    ws = tmp_path / "ws"
    made: list[ScriptedGateway] = []
    monkeypatch.setattr(cli, "_agent_seam_factory",
                        _cli_factory(made, {"M": [ask("口径用哪个？", options=["甲", "乙"]),
                                                   FINISH]}))
    reset_cache()
    rc = cli.main(["--plain", "--root", str(ws), "run-agent", "M", "--task", task,
                   "--sid", "u1", "--user-wait-sec", "0", "--max-steps", "4"])
    hint = capsys.readouterr().out
    assert rc == 3 and "停在等待用户" in hint, hint

    cmds = _hint_commands(hint)
    # 首屏那一行（`cli.py` 里逐字写着「首屏不跑自检：……完整读数请跑 `agentflow doctor`」）
    # 让同一屏多出一条整机诊断命令。它不吃 `--root`、也不看这一趟的工作区，所以下面
    # 那条「`--root` 必须写在动词之前」对它不成立 —— 照旧按工作区命令判，就会把一条
    # 真能跑的命令判成不能跑。摘出去的这一档只许是 doctor：别的没带 `--root` 的命令
    # 一条都不许从这里过（这是边界，不是豁免）。
    machine = [c for c in cmds if _argv_of(c)[:1] == ["doctor"]]
    assert all(c == "agentflow doctor" or c.startswith("agentflow doctor ")
               for c in machine), f"提示里出现了不是整机诊断的无 --root 命令：{machine}"
    cmds = [c for c in cmds if c not in machine]
    assert len(cmds) >= 3, f"提示里的命令少了（至少要 inbox / answer / run-agent 三条）：{hint}"
    # 同一个提示有两处（循环的 `结论：` 那一行 + CLI 的「停在等待用户」那一行），
    # 两边给的应当是同一批命令 ⇒ 按 argv 去重之后应当正好三条。
    unique: list[list[str]] = []
    for cmd in cmds:
        argv = _argv_of(cmd)
        if argv not in unique:
            unique.append(argv)
    # 规则一：每一条都要「自己带 --root」，而且写在动词之前。
    # 不带 --root 的那种会打到「默认工作区」上 —— 人敲下去不报错，只是在看别的地方；
    # 写在动词之后的那种直接被 argparse 拒（`unrecognized arguments`，退出码 2）。
    assert all(argv[0] == "--root" for argv in unique), (
        f"有命令没把 `--root` 写在动词之前："
        f"{[c for c in cmds if _argv_of(c)[0] != '--root']}")
    # 规则二：根就是这一趟的工作区（打印一个别处的根，等于把人送到别的工作区去）
    bad_root = [argv for argv in unique if argv[1] != str(ws)]
    assert not bad_root, (f"这几条命令的根不是这一趟的工作区：{bad_root!r}\n"
                          f"抓到的原文（前 1500 字）：{hint[:1500]!r}")
    assert len(unique) == 3, f"去重后应当正好三条（inbox / answer / run-agent）：{unique}"

    # 能直接跑的两条：把 `<回答>` 这个占位符换成真回答；`--resume …` 那条带省略号，跳过但要数出来
    runnable = [[p.replace("<回答>", "三处都保留") for p in argv]
                for argv in unique if not any("…" in p for p in argv)]
    skipped = [argv for argv in unique if any("…" in p for p in argv)]
    assert len(runnable) == 2 and len(skipped) == 1, (unique, runnable, skipped)

    for argv in runnable:
        code = cli.main(argv)
        cap = capsys.readouterr()
        assert code == 0, f"提示里的命令跑不通：{argv} ⇒ 退出码 {code}；{cap.out}{cap.err}"
    # 这两条命令真的把事办了（不是"退出码 0 但什么也没做"）
    assert U.pending_questions(ws, sid="u1") == [], "提示里的 answer 没把那条问题答掉"
    assert [r["answer"] for r in U.read_replies(ws, role="M", sid="u1")] == ["三处都保留"]

    # 负控（反真空）：旧写法必须被拒 —— 否则上面那条"命令真能跑"根本不构成判据
    with pytest.raises(SystemExit) as caught:
        cli.main(["--plain", "inbox", "--root", str(ws)])
    assert caught.value.code == 2, caught.value
    # 负控之二：光秃秃的 `--sid`（空 sid 时旧写法会打印成这样）同样跑不通
    with pytest.raises(SystemExit) as caught2:
        cli.main(["--plain", "--root", str(ws), "inbox", "--sid"])
    assert caught2.value.code == 2, caught2.value


if __name__ == "__main__":  # pragma: no cover - 手动跑这一组时的入口
    raise SystemExit(pytest.main([__file__, "-q"]))

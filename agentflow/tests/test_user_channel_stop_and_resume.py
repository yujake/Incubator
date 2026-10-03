# -*- coding: utf-8 -*-
"""用户频道「停着」与「可续跑」的判据：问 → 停 → 答 → 续（离线，替身模型）。

## 这一组守什么（以及它是谁的判据）

用户 2026-10-03 的裁定：「就停着」—— 问了就要停在那里，不许超时之后继续往下跑。
这一组把那条裁定钉成可复核的读数，一共三件事：

1. 「停」：`ask_user` 没拿到回答时，这一趟以 `stop_reason="waiting_for_user"` 停下，
   `waiting_for` 记下问题号，并且「不再发任何模型请求」（"停着 = 不烧钱"的判据：
   数会话里的 `llm_call` 事件条数，再断言没有新的）。
2. 「答」：人通过 `agentflow answer`（`--select` / `--custom` / 位置参数三条路）写下的
   那句话，`--resume` 那一段看到的上下文里读得到，而且那一趟真的跑到 `final`。
3. 「续」：`resume_transcript` 重建出来的 transcript 与循环里拼出来的那一份
   「逐字相等」 —— 否则"续跑"会变成"换一段稍微不同的话接着问"，而没有任何判据
   看得见那个漂移。

## 负控清单（每一条都对着一个"看起来能用、其实是假的"形态）

- 没回答就 `--resume`：必须明确报"还在等 qid"，一步模型都不调（不许静默重跑，
  不许把"没答"当成默许）；
- 任务指纹不符：`checkpoint_mismatch` + CLI 退出码 2 + 零模型调用；
- 无人值守档（`ASK_POLICY="never"`）：`ask_refused`、问题「不落」待答清单、循环继续；
- 子角色（有父任务号且 depth>1）问用户：`delegated_asker`、问题不落盘、循环继续；
  同一个角色在顶层（`my_task_id=""`）时提问「必须」通 —— 否则"用户端"整条路不可达；
- 别的 sid 的回答不算这一趟的（`read_replies(sid=…)` 隔离）。

## 用的是替身模型，不联网、不花钱

替身（`ScriptedGateway`）与真模型同接口（`complete(prompt, *, scope, system)`），
照剧本回话。所以这一组验的是「框架行为」（停、答、续），不是"模型据此改主意了"——
后者要一次真机。
"""
from __future__ import annotations

import json
import pathlib
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


def ask(text: str = "口径用哪个？", *, timeout: float | None = 0,
        options: Any = None, header: str = "口径") -> str:
    """一条 `ask_user` 剧本行；`timeout=None` 表示不给 `timeout_sec`（吃框架缺省）。"""
    body: dict[str, Any] = {"question": text, "header": header}
    if timeout is not None:
        body["timeout_sec"] = timeout
    if options is not None:
        body["options"] = options
    return json.dumps({"ask_user": body}, ensure_ascii=False)


FINISH = json.dumps({"final": "收工", "evidence": []}, ensure_ascii=False)
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
         replies: list[str], *, role: str = "D", task: str = "把口径定下来",
         max_steps: int = 4, sid: str = "t", resume: bool = False,
         user_timeout_sec: float | None = 0, direct: bool = False,
         my_task_id: str = "") -> tuple[Any, ScriptedGateway]:
    """跑一趟角色循环（用替身模型），返回 `(run, 替身)`。

    `user_timeout_sec=0` 是这一组的缺省：它对应"问了就停"（CLI 的 `--user-wait-sec 0`），
    于是每条判据都不必真的去等人 —— 而"等"这件事本身由 `userio` 的自检覆盖。

    `direct=True` 直接建 `AgentLoop`（绕过 `run_role`）：只有子角色那条判据需要它，
    因为"我有没有父任务号"是 `LlmBackend` 在真实召唤里填的，而这里要把它钉死。
    """
    gw = ScriptedGateway(replies)
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
    SCRIPTS.update({"D": [ask("口径用哪个？"), FINISH],
                    "E": [ask("另一岗也想问一句？"), FINISH]})
    rc = cli.cmd_run_agent(_args(tmp_path, role="D", task="把口径定下来"))
    out = capsys.readouterr().out
    assert rc == 3, out
    assert "停在等待用户" in out and "agentflow answer" in out, out
    root = tmp_path / "ws"
    assert _llm_calls(root) == 1, "退出码 3 那一趟不该有第二次模型调用"
    assert len(U.pending_questions(root, sid="t")) == 1
    # `--json` 那一档：退出码同样 3，而 stdout 必须仍然是一份可解析的 JSON
    rc_json = cli.cmd_run_agent(_args(tmp_path, role="E", task="换一个角色再问一次", json=True))
    captured = capsys.readouterr()
    assert rc_json == 3, (captured.out, captured.err)
    payload = json.loads(captured.out)
    assert payload["stop_reason"] == "waiting_for_user" and payload["waiting_for"], payload
    assert "停在等待用户" in captured.err, captured.err


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
               for r in U.read_replies(root, role="D", sid="t"))

    second, gw2 = _run(st, registry, cond, root, [FINISH], resume=True)
    assert second.stop_reason == "final", second.to_dict()
    assert second.resumed_from == 1, second.to_dict()   # 从第 2 步接着跑，不重做第 1 步
    assert second.transcript.startswith(first.transcript), "续跑那一段没有接着上次那份对话"
    # 用户那句话进的是「系统提示」（`agent_prompts.user_replies_digest` 那一格）——
    # 它不在 transcript 里，这是既有接线（`test_interaction` 里那条迟到回答的判据同源）。
    assert "审这篇论文" in gw2.systems[0], "用户那句话没有进续跑那一段看到的上下文"
    assert len(gw2.prompts) == 1, "续跑只需要问一次（接着那一步之后）"


def test_the_selected_answer_reaches_the_resumed_run(tmp_path: pathlib.Path, capsys):
    """正控（答 → 续）：`--select <label>` 那条路同样进得了续跑那一段（DSH 的 selected）。"""
    st, registry, cond, root = _ws(tmp_path)
    first, _gw = _run(st, registry, cond, root,
                      [ask("口径用哪个？", options=["n<=5", "全体"]), FINISH])
    qid = first.waiting_for
    rc = cli.cmd_answer(_args(tmp_path, qid=qid, text=None, select=["n<=5"], custom=None))
    assert rc == 0, capsys.readouterr().err
    replies = U.read_replies(root, role="D", sid="t")
    assert replies and replies[-1]["selected"] == ("n<=5",), replies
    second, gw2 = _run(st, registry, cond, root, [FINISH], resume=True)
    assert second.stop_reason == "final", second.to_dict()
    assert "n<=5" in gw2.systems[0], "选中的 label 没有进续跑那一段看到的上下文"
    assert second.transcript.startswith(first.transcript), second.transcript[:80]
    # 负控（别名那条路的反面）：`--custom` 覆盖 selected 时读出来的就是 custom
    other = tmp_path / "ws2"
    other.mkdir()
    q = U.ask_user(other, role="D", question="口径？", options=["甲", "乙"],
                   timeout_sec=0.0, sid="t")
    assert cli.cmd_answer(Namespace(root=str(other), sid="t", qid=q.qid, text=None,
                                    select=["甲"], custom="其实选乙")) == 0
    got = [r for r in U.read_replies(other, sid="t") if r["qid"] == q.qid][0]
    assert got["answer"] == "其实选乙" and got["selected"] == ("甲",), got


def test_resume_transcript_is_byte_equal_to_the_live_transcript(tmp_path: pathlib.Path):
    """正控（续跑的正确性）：重建出来的 transcript 与循环里拼出来的那一份逐字相等。

    为什么这条是"最重要的一条"：续跑要给模型的，是「当时那份对话」。差一个字，
    模型看到的处境就变了，而"它是不是接着上次说的往下做"就没有判据了。
    """
    st, registry, cond, root = _ws(tmp_path)
    run, _gw = _run(st, registry, cond, root, [NOTE, NOTE, NOTE], max_steps=3)
    assert len(run.steps) == 3 and run.stop_reason == "max_steps", run.to_dict()
    rebuilt, step0 = AL.resume_transcript(root, "D", "t", task="把口径定下来")
    assert step0 == 3, step0
    assert rebuilt == run.transcript, "重建的 transcript 与当时那一份不逐字相等"
    # 负控（不许张冠李戴）：任务原文不匹配 ⇒ 重建不出来，返回 ("", 0) 而不是别人的那一段
    other, other_step = AL.resume_transcript(root, "D", "t", task="另一件事")
    assert (other, other_step) == ("", 0), (other[:60], other_step)


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
    SCRIPTS.update({"D": [ask("口径用哪个？"), FINISH]})
    assert cli.cmd_run_agent(_args(tmp_path, role="D", task="第一件事")) == 3
    capsys.readouterr()
    root = tmp_path / "ws"
    calls_before = _llm_calls(root)
    rc = cli.cmd_run_agent(_args(tmp_path, role="D", task="完全不同的第二件事", resume=True))
    captured = capsys.readouterr()
    assert rc == 2, (captured.out, captured.err)
    assert "checkpoint_mismatch" in (captured.out + captured.err), (captured.out, captured.err)
    assert _llm_calls(root) == calls_before, "指纹不符却发起了模型调用"
    refused = [e for e in _events(root) if e.get("resume_refused")]
    assert refused and refused[-1]["resume_refused"] == "checkpoint_mismatch", refused


def test_the_unattended_policy_refuses_and_keeps_going(tmp_path: pathlib.Path, monkeypatch):
    """负控（无人值守档）：`ASK_POLICY="never"` ⇒ `ask_refused`、问题不落盘、循环继续。"""
    monkeypatch.setattr(U, "ASK_POLICY", "never")
    st, registry, cond, root = _ws(tmp_path)
    run, gw = _run(st, registry, cond, root, [ask("这条要不要问用户？"), FINISH])
    step = run.steps[0].result
    assert step.get("problem") == U.ASK_REFUSED and step.get("state") == "refused", step
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
    SCRIPTS.update({"D": [ask("这条要不要问用户？"), FINISH]})
    rc = cli.cmd_run_agent(_args(tmp_path, role="D", task="无人值守地做", no_ask=True))
    out = capsys.readouterr().out
    assert rc == 0, out
    root = tmp_path / "ws"
    assert U.pending_questions(root, sid="t") == [], "无人值守档却把问题落进了待答清单"
    ends = [e for e in _events(root) if e.get("kind") == "agent_run_end"]
    assert ends and ends[-1].get("stop_reason") == "final", ends
    assert U.ASK_POLICY == "ask", "CLI 的 --no-ask 不该改模块全局（会渗到同一进程的第二趟）"


def test_a_delegated_child_may_not_ask_the_user_but_a_top_level_role_may(
        tmp_path: pathlib.Path):
    """负控（子角色）：有父任务号且 depth>1 ⇒ `delegated_asker`，问题不落盘，循环继续。

    同一条判据的另一面也必须成立（否则"用户端"整条路不可达）：同一个角色在「顶层」
    （`my_task_id=""`，本框架给非 M 角色的缺省深度就是 2）时提问必须通到待答清单。
    这两条一起才说明判据是"我归属另一个 agent"，而不是"深度大于 1"。
    """
    st, registry, cond, root = _ws(tmp_path)
    child, gw_child = _run(st, registry, cond, root, [ask("子角色想直接问用户？"), FINISH],
                           direct=True, my_task_id="t-0001")
    step = child.steps[0].result
    assert step.get("problem") == "delegated_asker", step
    assert "由主控统一问" in str(step.get("note") or ""), step
    assert U.pending_questions(root, sid="t") == [], "子角色的提问不许落盘"
    assert child.stop_reason == "final", "子角色那一档不许停循环"
    assert len(gw_child.prompts) == 2, "拒绝之后循环必须继续"
    # 反面：同样的 depth=2，但没有父任务号（顶层运行）⇒ 走真人通道
    top, _gw_top = _run(st, registry, cond, root, [ask("顶层问一句？"), FINISH],
                        direct=True, my_task_id="")
    assert top.stop_reason == "waiting_for_user", top.to_dict()
    assert [q.qid for q in U.pending_questions(root, sid="t")] == [top.waiting_for]


def test_an_answer_from_another_session_does_not_count(tmp_path: pathlib.Path):
    """负控（不许串味）：别的 sid 里写下的回答，不算这一趟的。

    这一条挡的形态是"同一件事在别的会话里被答过了"被读成"这一趟可以往下跑" ——
    真机每一趟都有自己的 sid，跨会话读回答等于把别人的决定当成自己的。
    """
    root = tmp_path / "ws"
    root.mkdir()
    q = U.ask_user(root, role="D", question="口径用哪个？", timeout_sec=0.0, sid="real1")
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
    rebuilt, step0 = AL.resume_transcript(root, "D", "t", task="把口径定下来")
    assert step0 == 1, f"重建被那条没有步的 run_start 吞掉了：{step0}（{rebuilt[-80:]!r}）"
    # D：再续 ⇒ 必须接着第 2 步跑到 final
    final_run, gw_d = _run(st, registry, cond, root, [FINISH], resume=True)
    assert final_run.stop_reason == "final", final_run.to_dict()
    assert final_run.resumed_from == 1, final_run.to_dict()
    assert "全留" in gw_d.systems[0], "用户那句话没有进续跑那一段看到的上下文"
    assert len(gw_d.prompts) == 1


def test_the_checkpoint_round_trips_and_names_the_waiting_question(tmp_path: pathlib.Path):
    """正控（检查点可读）：停下来时的那份检查点能读回，且带着"停在等谁"。

    这是 `--resume` 的输入面：读不到它（或读到的 `waiting_for` 是空的），
    上面那条"没答就续跑要报还在等"的判据就无从判起。
    """
    st, registry, cond, root = _ws(tmp_path)
    first, _gw = _run(st, registry, cond, root, [ask("口径用哪个？"), FINISH])
    cp = AL.load_run_checkpoint(root, "D", "t")
    assert cp is not None, f"检查点没写成：{AL.run_checkpoint_path(root, 'D', 't')}"
    assert cp["step"] == 1 and cp["stop_reason"] == "waiting_for_user", cp
    assert cp["waiting_for"] == first.waiting_for, cp
    assert cp["fingerprint"] == AL._task_fingerprint("D", "把口径定下来"), cp
    assert AL.run_checkpoint_path(root, "D", "t").name == "agent-D-t.json"
    # 负控（读不到就说读不到）：别的 sid 读不到这一趟的检查点
    assert AL.load_run_checkpoint(root, "D", "另一个会话") is None
    assert AL.load_run_checkpoint(root, "E", "t") is None


if __name__ == "__main__":  # pragma: no cover - 手动跑这一组时的入口
    raise SystemExit(pytest.main([__file__, "-q"]))

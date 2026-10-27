# -*- coding: utf-8 -*-
"""Q12：final 被 D-68 拒之后还有回合 —— 销号由模型自己决定，补救拍有上限。

## 病（真机读数）

`projects/mp3-r3` 22:37:50 的 M 那一趟：`stop_reason=final_refused`、31 步、
`final=''`，`agent_run_end.notes` 里逐字写着「还没销号：t-000001 名下整棵树还有
17/17 个代理在册 …… 再用 `conductor.retire_child` 逐个销号」。而它这一趟的工具面调用
里 `conductor.retire_child` 是零次。

原因不在模型：`agent_loop.py` 的收工门那一支在 `run.stop_reason = "final_refused"`
之后紧接着 `break` —— 拒信写进了 `run.notes` 与这一步的结果，而那一步是这一趟的最后
一步。上面那行注释写着"模型下一轮读得到"，但没有下一轮。

## 改后的口径

被拒不等于这一趟结束：

1. 拒信进这一步的结果（`{"final_refused": …, "why": …}`，键集与改前逐字相同）；
2. 拒信也进消息序列（`assistant_message` + `tool_message`）与 `agent_step` 事件 ——
   于是下一拍的 prompt 里真的读得到它（改前这一支连 `messages.append` 都没有，
   只删 `break` 模型也看不见拒信）；
3. `continue`：下一拍由模型自己决定销谁（销号是一次有对象的写，谁该被销只有它自己
   按板项与静默读数判得出来 —— 框架替它销就是替它做决定）；
4. 补救窗口有上限（`AgentLoop.max_final_refused`）：连着被拒满 N 拍仍未 complete ⇒
   才以 `final_refused` 收尾，收尾那句点名"补救了 N 拍仍不完整"，并分辨
   "在册数少了（试过、没销干净）"与"一个都没少（一次都没试）"。

## 判据（每条都写清改前红在哪）

| # | 判据 | 改前红 |
|---|---|---|
| a | 被拒 ⇒ 下一拍销干净 ⇒ 这一趟以 `final` 正常收工 | 改前第一拍就 break，`stop_reason` 恒是 `final_refused` |
| b | 一直被拒 ⇒ 至多 N 拍后以 `final_refused` 结束，点名"补救了 N 拍仍不完整 / 一个都没少" | 改前没有"补救了 N 拍"这句话（它只有一拍） |
| b' | 销了 1 个但仍不完整 ⇒ 收尾说"动过销号工具、只是没销干净"（与 b 是同一句话的两半） | 改前没有这句收尾 |
| c | 正控：本来就能一次销干净 ⇒ 不多花补救拍（步数、`final_refused_beats` 都不变） | 正控在改前也是绿的（这一条守的是别把补救拍花在干净树上） |
| d | 反真空：把补救窗口压成 0（等价于改前那一 break）⇒ a 必红 | —— |
| e | 拒信真的进了下一拍的 prompt | 改前根本没有"下一拍"（`prompts` 只有一条） |
| f | 反真空：同一个桩 ⇒ a 与 e 同时红 | —— |

## 纪律

本文件只碰"收工门那一支 + 一格读数 + 一格常量"，不碰控制器、schema、store、
conductor、tools、提示词与既有判据。
"""

from __future__ import annotations

import json
import pathlib
from typing import Any

import pytest

from agentflow import sessions as SS
from agentflow.agent_loop import AgentLoop, run_role
from agentflow.conductor import Conductor, LocalBackend, calling_as
from agentflow.llmseam import LlmSeam
from agentflow.secretary import Secretary
from agentflow.store import Store
from agentflow.tools import build_registry
from agentflow.tools import conductor_tools as CT
from agentflow.tools.base import ToolRegistry

TS = "2026-01-01T00:00:00+00:00"
SID = "q12"

#: 被拒之后模型该用的那只手（判据 e 在 prompt 里找的就是它背后的清单）。
RETIRE = "conductor.retire_child"

#: 收尾那句里必须出现的两个读数（判据 b）：补救拍数与"一个都没少"。
STILL_REFUSED = "仍不完整"
NEVER_TRIED = "一个都没少"


# ====================================================================== 夹具
def _workspace(tmp_path: pathlib.Path) -> dict[str, Any]:
    """一个工作区 ＋ 一个主控行 ＋ 主控那一趟的秘书（与生产同一条取法）。"""
    root = tmp_path / "ws"
    store = Store(root)
    store.init()
    cond = Conductor(store, registry={}, backend=LocalBackend({}))
    sec = Secretary("M", root=root, store=store)
    # 生产里由 `AgentLoop._bind_roster_sink` 接上：销号与登记名册要落同一份名册文件。
    cond.roster_sink = sec
    owner = str(cond.open_top_level_run("M", "夹具：Q12 的补救拍"))
    return {"root": root, "store": store, "cond": cond, "sec": sec, "owner": owner}


def _child(cond: Conductor, owner: str, *, role: str = "D") -> str:
    """造一个已经落定的子代理行（`status="done"` ⇒ 它是静默的，销号门会让它过）。"""
    row = {
        "role": role, "action": "write_report", "called_by": "M",
        "parent_task_id": owner, "depth": 2, "input_key": f"fixture:{role}",
        "status": "done", "outcome": "ok", "refusal_reason": None, "instance": "",
        "detail": "夹具子代理", "error": None, "started_at": TS, "ended_at": TS,
        "tokens": 0, "usd": 0.0, "artifacts": [], "inputs": [],
    }
    return cond._write_new_row(row, note="fixture:child")


def _roster(env: dict[str, Any], task_id: str, *, role: str = "D") -> str:
    """登记进父的名册（销号的指称是名册名，所以这一步是前提）。"""
    got = env["sec"].roster_add(owner=str(env["owner"]), role=role, task_id=task_id,
                                brief="写研究报告")
    assert got.get("problem") == "", got
    return str(got["name"])


class _Gate:
    """按脚本回文本的替身网关（不联网）；脚本用完之后回 `{}`（与既有夹具同形）。"""

    spec = type("Spec", (), {"model": "stub", "api_key": "x"})()

    def __init__(self, script: list[dict]) -> None:
        self.script = list(script)
        self.prompts: list[str] = []

    def complete(self, prompt: str, *, scope: str = "", system: str | None = None,
                 max_tokens: int | None = None, tools: Any = None,
                 tool_choice: str = "auto") -> Any:
        self.prompts.append(prompt)
        item = self.script.pop(0) if self.script else {"text": "{}"}
        return type("R", (), {"ok": True, "text": item.get("text", ""),
                              "tool_calls": tuple(item.get("tool_calls", ())),
                              "tokens_in": 1, "tokens_out": 1, "error_detail": "",
                              "error_kind": ""})()


M_FINAL = "M 的交付：整棵树都销号了，这一趟的事做完了"
RETIRE_WHY = "板清了，销号"


def _retire_by_hand(env: dict[str, Any], name: str) -> Any:
    """以 M 的身份调一次销号（走生产那条 `ToolRegistry.call`，不直连 Secretary）。"""
    reg = ToolRegistry(name="q12")
    CT.register(reg, store=env["store"], conductor=env["cond"])
    with calling_as(str(env["owner"]), "M"):
        return reg.call(RETIRE, {"child_name": name, "reason": RETIRE_WHY}, role="M")


def _final_reply(text: str = M_FINAL) -> dict:
    return {"text": json.dumps({"final": text, "evidence": []}, ensure_ascii=False)}


def _retire_reply(name: str) -> dict:
    """一步模型输出：调 `conductor.retire_child` 把那个节点销掉。"""
    return {"text": json.dumps({"tool": RETIRE,
                                "args": {"child_name": name, "reason": RETIRE_WHY},
                                "why": "拒信点名的就是它"}, ensure_ascii=False)}


def _run_m(env: dict[str, Any], monkeypatch: pytest.MonkeyPatch,
           replies: list[dict]) -> tuple[Any, _Gate]:
    """以 M 的身份真跑一趟，返回 `(run, 替身网关)`。

    固定台账号的理由与既有判据同一条：每一趟都会发新号，而判据问的是"这一趟名下那棵
    树销号了没有" —— 号一变树就是空的，判据会变成真空绿。
    """
    store, cond = env["store"], env["cond"]
    mine = str(env["owner"])
    monkeypatch.setattr(Conductor, "open_top_level_run",
                        lambda self, role, task: mine)
    gate = _Gate(replies)
    reg = build_registry(store=store, conductor=cond).registry
    run = run_role("M", "夹具：Q12 的补救拍", store=store, registry=reg, conductor=cond,
                   seam=LlmSeam(role="M", session_root=env["root"], gateway=gate,
                                price=(0.0, 0.0), sid=SID),
                   session_root=env["root"], workspace_root=str(env["root"]),
                   sid=SID, from_env=False)
    return run, gate


def _ends(env: dict[str, Any]) -> list[dict]:
    events, problems = SS.read_session(env["root"], sid=SID)
    assert not problems, problems
    return [e for e in events if str(e.get("kind") or "") == "agent_run_end"]


def _notes(end: dict) -> str:
    return " ".join(str(x) for x in (end.get("notes") or []))


def _final_steps(run: Any) -> list[Any]:
    return [s for s in run.steps if str(s.shape or "") == "final"]


# ====================================================================== a
def _a_problems(env: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """a 的判据本体：被拒之后下一拍把树销干净 ⇒ 这一趟以 `final` 正常收工。

    返回问题清单（空 ＝ 通过）。抽成函数是为了让 d / f 打桩之后复用同一套断言
    —— 否则它们会变成"另写一份更松的判据"。
    """
    owner = str(env["owner"])
    child = _child(env["cond"], owner)
    name = _roster(env, child)
    run, _gate = _run_m(env, monkeypatch,
                        [_final_reply(), _retire_reply(name), _final_reply()])
    ends = _ends(env)
    if not ends:
        return ["盘上没有 agent_run_end（这一趟没跑起来）"]
    end = ends[-1]
    problems: list[str] = []
    if run.stop_reason != "final":
        problems.append(f"销干净之后仍不许收工：stop_reason={run.stop_reason!r}")
    if str(run.final or "") != M_FINAL:
        problems.append(f"内存里的 final 不对：{run.final!r}")
    if str(end.get("final") or "") != M_FINAL:
        problems.append(f"final 没落盘：{str(end.get('final'))[:80]!r}")
    if int(getattr(run, "final_refused_beats", -1)) != 1:
        problems.append(f"补救拍数应恰好 1 拍：{getattr(run, 'final_refused_beats', None)!r}")
    # 第一步必须真的是"被拒"（否则这条判据证不了"拒后还有回合"）。
    steps = run.steps
    if not steps or str(steps[0].shape or "") != "final":
        problems.append(f"第 0 步不是 final：{[s.shape for s in steps]}")
    elif "final_refused" not in (steps[0].result or {}):
        problems.append(f"第 0 步的 final 没被拒（这一趟没测到那道闸）：{steps[0].result}")
    if len(steps) != 3:
        problems.append(f"步数应为 3（拒 → 销号 → 收工）：{[s.shape for s in steps]}")
    if RETIRE not in [str((s.payload or {}).get("name") or "") for s in steps]:
        problems.append(f"销号那一步没落到工具上：{[s.payload for s in steps]}")
    # 盘上：这个节点真的进了销号名单（不是只在 final 里说了一句）。
    # 销号的落点是名册那一侧的 `retire` 行（`Conductor._released_pairs` 读的就是它），
    # 台账行的 `status` 不会被改写 —— 所以这里读名单，不读 `status`。
    rows, bad = env["sec"].retired_names(owner)
    if bad:
        problems.append(f"销号名单有坏行：{bad[:2]}")
    if child not in [str(r.get("task_id") or "") for r in rows]:
        problems.append(f"节点没进销号名单（它没真的被销）：{rows}")
    return problems


def test_a_refused_final_is_followed_by_a_beat_that_retires(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """a 被拒 ⇒ 下一拍销干净 ⇒ 以 `final` 正常收工。

    改前红：收工门那一支在同一拍 `break`，于是第二拍（销号）与第三拍（收工）都不存在，
    `stop_reason` 恒为 `final_refused`、`run.final` 恒为空。
    """
    env = _workspace(tmp_path)
    problems = _a_problems(env, monkeypatch)
    assert problems == [], "\n".join(problems)


# ====================================================================== b
def test_a_final_that_stays_refused_ends_after_the_remedy_window(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """b 一直被拒 ⇒ 至多 N 拍后以 `final_refused` 结束，读数点名两种形态里的哪一种。

    为什么这条必须有：补救拍是"给回合"，不是"给无限回合"。判据钉三件：
    收尾理由仍是 `final_refused`、补救拍数恰好等于上限、收尾那句把
    "补救了 N 拍仍不完整"与"在册数一个都没少（它一次都没试）"写出来。
    """
    env = _workspace(tmp_path)
    owner = str(env["owner"])
    child = _child(env["cond"], owner)
    _roster(env, child)
    # 脚本给得比上限多：多出来的那些不该被再花一次（超出上限就收尾）。
    run, _gate = _run_m(env, monkeypatch, [_final_reply()] * 6)
    ends = _ends(env)
    assert ends, "盘上没有 agent_run_end"
    end = ends[-1]
    problems: list[str] = []
    cap = int(AgentLoop.max_final_refused)
    if run.stop_reason != "final_refused":
        problems.append(f"stop_reason={run.stop_reason!r}（应 final_refused）")
    if str(run.final or ""):
        problems.append(f"被拒的这一趟不许记 final：{run.final!r}")
    if int(getattr(run, "final_refused_beats", -1)) != cap:
        problems.append(f"补救拍数应等于上限 {cap}："
                        f"{getattr(run, 'final_refused_beats', None)!r}")
    if len(_final_steps(run)) != cap + 1:
        problems.append(f"final 步数应恰好 {cap + 1} 次（{cap} 拍补救 + 最后一次收尾）："
                        f"{[s.shape for s in run.steps]}")
    notes = _notes(end)
    if STILL_REFUSED not in notes:
        problems.append(f"收尾没点名『补救了 N 拍仍不完整』：{notes[-300:]!r}")
    if f"补救了 {cap} 拍" not in notes:
        problems.append(f"收尾没把补救拍数写出来（应『补救了 {cap} 拍』）：{notes[-300:]!r}")
    if NEVER_TRIED not in notes:
        problems.append(f"一次都没试的那一形态没在读数里点名：{notes[-300:]!r}")
    assert problems == [], "\n".join(problems)


# ====================================================================== b 的第二面
def test_the_reading_tells_tried_from_never_tried(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """b 的另一半读数：销了 1 个但仍不完整 ⇒ 收尾说"它动过销号工具，只是没销干净"。

    为什么这条与 b 并列：收尾那句有两种形态，而它们下一步的处置相反（继续催 / 先问它卡在哪）。
    只测其中一种，那一句话的另一半就是没人看过的代码 —— 而"试过但没成"正是最容易被
    写成"没试"的那一档（按工具名匹配会漏掉换个写法的销号，按在册数变化判才判得准）。
    """
    env = _workspace(tmp_path)
    owner = str(env["owner"])
    first = _child(env["cond"], owner, role="D")
    second = _child(env["cond"], owner, role="E")
    name = _roster(env, first)
    _roster(env, second, role="E")
    cap = int(AgentLoop.max_final_refused)
    # 拒 → 销掉其中一个 → 之后每一拍仍然发 final（一直被拒，直到窗口用尽）。
    replies = [_final_reply(), _retire_reply(name)] + [_final_reply()] * cap
    run, _gate = _run_m(env, monkeypatch, replies)
    ends = _ends(env)
    assert ends, "盘上没有 agent_run_end"
    notes = _notes(ends[-1])
    problems: list[str] = []
    if run.stop_reason != "final_refused":
        problems.append(f"stop_reason={run.stop_reason!r}（应 final_refused）")
    if int(getattr(run, "final_refused_beats", -1)) != cap:
        problems.append(f"补救拍数应等于上限 {cap}："
                        f"{getattr(run, 'final_refused_beats', None)!r}")
    if "动过销号工具" not in notes:
        problems.append(f"销了 1 个却仍被判成『没试』：{notes[-300:]!r}")
    if f"在册从 2 个减到 1 个" not in notes:
        problems.append(f"收尾没报在册数的变化（应『在册从 2 个减到 1 个』）：{notes[-300:]!r}")
    assert problems == [], "\n".join(problems)


# ====================================================================== c
def test_a_clean_tree_costs_no_remedy_beats(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """c 正控：本来就能一次销干净 ⇒ 不多花补救拍（步数与读数都不变）。

    为什么它与 a 并列：给回合这件事最容易的过度修法就是"每次都多跑几拍"，
    于是干净的那一趟也白花一次模型调用 —— 这条判据钉住"只在被拒时才花"。
    """
    env = _workspace(tmp_path)
    owner = str(env["owner"])
    child = _child(env["cond"], owner)
    name = _roster(env, child)
    # 收工之前就把它销了（生产里这一手由模型自己做，这里只造"本来就能一次过"那一档）。
    done = _retire_by_hand(env, name)
    assert done.ok, done.error
    assert str((done.data or {}).get("state") or "") == "retired", done.data
    run, _gate = _run_m(env, monkeypatch, [_final_reply()])
    problems: list[str] = []
    if run.stop_reason != "final":
        problems.append(f"干净树上收不了工：stop_reason={run.stop_reason!r}")
    if int(getattr(run, "final_refused_beats", -1)) != 0:
        problems.append(f"干净树上花了补救拍：{getattr(run, 'final_refused_beats', None)!r}")
    if len(run.steps) != 1:
        problems.append(f"干净树上步数应仍是 1：{[s.shape for s in run.steps]}")
    if str(run.final or "") != M_FINAL:
        problems.append(f"final 不对：{run.final!r}")
    assert problems == [], "\n".join(problems)


# ====================================================================== e
def _e_problems(env: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """e 的判据本体：拒信真的进了下一步喂给模型的那份 prompt。"""
    owner = str(env["owner"])
    child = _child(env["cond"], owner)
    name = _roster(env, child)
    _run, gate = _run_m(env, monkeypatch,
                        [_final_reply(), _retire_reply(name), _final_reply()])
    problems: list[str] = []
    if len(gate.prompts) < 2:
        return [f"被拒之后没有下一拍：只问了模型 {len(gate.prompts)} 次"
                "（改前这一支同一拍就 break）"]
    second = gate.prompts[1]
    # 三样都要在：拒信的事实句、这一步的补救读数、以及被点名的那棵树。
    for want, what in ((owner, "根编号"), ("还没销号", "拒信首句"),
                       ("条未消项", "未消项读数"), (RETIRE, "处置路径"),
                       ("补救拍 1/", "补救拍读数")):
        if want not in second:
            problems.append(f"下一拍的 prompt 里读不到{what}（{want!r}）")
    return problems


def test_the_refusal_reaches_the_next_prompt(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """e 拒信真的进了下一拍的 prompt（不是只躺在 run.notes 里）。

    改前红：这一支连 `messages.append` 都没有 —— 只删 `break` 的话，模型下一拍看到的
    是一份没有这一步的对话（拒信只在盘上，不在它眼前）。
    """
    env = _workspace(tmp_path)
    problems = _e_problems(env, monkeypatch)
    assert problems == [], "\n".join(problems)


# ====================================================================== d / f 反真空
def _stub_back_to_break(monkeypatch: pytest.MonkeyPatch) -> None:
    """把补救窗口压成 0 —— 等价于改前那一支"被拒就同一拍 break"。

    为什么用这一格而不是 monkeypatch 一个内部函数：窗口 0 走的正是改前的控制流
    （第一封拒信就把这一趟收在 `final_refused`）。桩打在 `run` 的入口而不是类属性上：
    `max_final_refused` 是 dataclass 的字段（实例属性），改类属性对已经构造出来的那一趟
    没有影响 —— 那种桩会静默失效，而失效的桩看起来与"判据绿了"一模一样。
    """
    original = AgentLoop.run

    def run_with_no_remedy(self: Any, *args: Any, **kwargs: Any) -> Any:
        self.max_final_refused = 0
        return original(self, *args, **kwargs)

    monkeypatch.setattr(AgentLoop, "run", run_with_no_remedy)


def test_stubbing_the_remedy_window_to_zero_makes_a_red(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """d 反真空：补救窗口压成 0 ⇒ a 必红（否则 a 证不了"拒后还有回合"）。"""
    env = _workspace(tmp_path)
    _stub_back_to_break(monkeypatch)
    problems = _a_problems(env, monkeypatch)
    assert problems, "把补救窗口压成 0，a 却仍然绿 ⇒ 这条判据是橡皮图章"
    assert any("仍不许收工" in p or "stop_reason" in p for p in problems), problems


def test_stubbing_the_remedy_beats_back_to_break_makes_a_and_e_red(
        tmp_path: pathlib.Path) -> None:
    """f 反真空：同一个桩 ⇒ a 与 e 同时红（"给回合"与"拒信进 prompt"是一件事的两半）。

    两个工作区各用一个独立的 `monkeypatch` 上下文：`_run_m` 会把
    `Conductor.open_top_level_run` 钉在"这一趟的台账号"上，而那个桩在同一个
    `monkeypatch` 生命周期里不会自动撤 —— 带着它去建第二个工作区，台账号会串台
    （夹具会以"parent_task_id 不能指向自身"当场炸掉，那不是判据的红）。
    """
    with pytest.MonkeyPatch.context() as mp:
        a_env = _workspace(tmp_path / "a")
        _stub_back_to_break(mp)
        a_problems = _a_problems(a_env, mp)
    assert a_problems, "桩打了，a 却仍然绿"
    with pytest.MonkeyPatch.context() as mp:
        e_env = _workspace(tmp_path / "e")
        _stub_back_to_break(mp)
        e_problems = _e_problems(e_env, mp)
    assert e_problems, "桩打了，e 却仍然绿（拒信'进 prompt'这件事没被测到）"
    assert any("没有下一拍" in p for p in e_problems), e_problems

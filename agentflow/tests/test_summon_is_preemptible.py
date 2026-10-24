# -*- coding: utf-8 -*-
"""D-64 的判据：派活是可抢占的（父代理在子代理还在跑时仍拿得到回合）。

## 这一份钉的是哪一件事

真机读数（`projects/sylow3`，只读复算）：M（t-000001）第 4 步是 `invalid`（17:34:17），
第 5 步那次调用 17:34:25 起，而 `agent_step index=5` 落在 19:06:48 —— 一次阻塞式
`summon_many` 让父代理 92 分钟零回合；D1 的第 8 步同样阻塞了 29 分钟。后果不是慢，
而是「下一次 `ask_step` 之前的任何投递结构上不可能发生」（t-000031 的 notice 迟到 20m28s）。

所以这一份量的是行为，不是形状：

| 条 | 判据 | 改前红在哪 |
|---|---|---|
| a | 派 3 个长任务 ⇒ 父代理第二回合就拿到回合，且那一刻台账里 3 条子行还是 running | 改前 `summon_many` 一直阻塞到三个都跑完，第二回合只可能出现在「0 条在跑」之后 |
| b | 途中到达的 notice 在下一次返场就投到（那时孩子还在跑） | 改前下一次返场要等阻塞结束，那时孩子已经跑完 |
| c | 子全部回来之前 `final` 被拒（可抢占不等于不等子） | 改前孩子一定已经跑完（阻塞），这道门没有对象 |
| d | 把抢占打桩成不抢占 ⇒ a / b 必红（反真空） | 这一条是「a/b 真的在测抢占」的机器证明 |
| e | 预占之后最终结果与阻塞版等价（结果集 / 顺序 / refusal 一致） | 改前没有「预占」这一档，这一条没有对象 |
| f | 单任务 `summon` 与整批同形（不许只修 batch） | 改前单任务那条路根本不给句柄 |

## 夹具为什么不睡觉

「跑很久」由 `threading.Event` 造：孩子的 handler 卡在等放行上，判据自己决定什么时候
放行。用 `time.sleep` 的话，「父代理拿到了回合」就变成一个受机器快慢影响的统计量 ——
而这里要判的是结构性事实（第二回合发生在「还有子在跑」的时候）。
"""
from __future__ import annotations

import json
import pathlib
import threading
import time
from typing import Any, Callable, Mapping, Sequence

import pytest

from agentflow import agent_loop as AL
from agentflow.agent_loop import AgentLoop
from agentflow.conductor import Conductor
from agentflow.llmseam import LlmSeam
from agentflow.policy import Policy
from agentflow.store import Store
from agentflow.tools import build_registry

SID = "preempt"
TASK = "D-64 的判据夹具：派出去几个跑很久的活"
ROLE = "D"          # 父代理（D 的出边含 C ⇒ 派得动 C）
KID = "C"           # 子代理（C 没有出边 ⇒ 不会有孙辈搅进读数）

FINAL = json.dumps({"final": "都回来了，收工", "evidence": []}, ensure_ascii=False)
LOOK = json.dumps({"tool": "fs.list", "args": {"path": "."}}, ensure_ascii=False)
#: 一条根本不是 JSON 的回复 ⇒ 那一步什么都没执行（连 `_hear` 都不会跑）。
#: 用它把"通报只能在返场点被投到"这件事造干净：否则上一步收尾那只耳朵会先把它念出来，
#: 于是这条判据测到的就不是返场点了（D-52 的判据用的是同一个手法）。
BAD_JSON = "这不是 JSON：我想想再说"


class _BlockingBackend:
    """一个「派出去就卡住」的后端：它只保证子代理真的还在跑。

    为什么不用 `LocalBackend` 加一个卡住的动作：形状路的派活不点动作（口径 S2），
    于是 `LocalBackend` 会当场以 `not_wired` 拒绝 —— 那条路上的「孩子」根本不会跑，
    「父代理拿到了回合」就变成了「根本没有孩子在跑」。这一层故意只做一件事：
    每次 `call` 置一次「进入了」，然后等放行。
    """

    name = "blocks"

    def __init__(self) -> None:
        self.gate = threading.Event()
        self._lock = threading.Lock()
        self.calls: list[dict[str, Any]] = []

    # ---- Conductor 只用到这三样
    def known_roles(self) -> list[str]:
        return [KID]

    def resolve(self, role: str, instance: str = "") -> Any:  # pragma: no cover - 接口需要
        return self

    def call(self, role: str, action: str, params: Mapping[str, Any], *, token: Any,
             instance: str = "", task_id: str = "") -> Any:
        with self._lock:
            self.calls.append({"role": str(role), "action": str(action),
                               "instance": str(instance), "task_id": str(task_id)})
        if not self.gate.wait(timeout=30.0):
            return {"outcome": "no_result",
                    "detail": "判据：等放行超时（这说明有谁没有在等孩子）"}
        return {"outcome": "ok", "detail": f"{role} 的活跑完了",
                "payload": {"llm_run_path": f"out/tasks/{task_id or 'x'}.json",
                            "final": f"{role}#{instance or '-'} 的结论"}}

    # ---- 判据侧的读数
    def entered(self) -> int:
        with self._lock:
            return len(self.calls)

    def wait_entered(self, n: int, *, timeout: float = 20.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.entered() >= n:
                return True
            time.sleep(0.01)
        return self.entered() >= n

    def release(self) -> None:
        self.gate.set()


class _Gate:
    """照剧本回答的替身模型：记下每一次提示词，`on_call(i)` 在第 i 次调用返回之前跑。"""

    spec = type("Spec", (), {"model": "stub", "api_key": "x"})()

    def __init__(self, replies: Sequence[str],
                 on_call: Callable[[int], None] | None = None) -> None:
        self.replies = list(replies)
        self.on_call = on_call
        self.prompts: list[str] = []
        self.systems: list[str] = []

    def complete(self, prompt: str, *, scope: str = "", system: str | None = None,
                 **kw: Any) -> Any:
        index = len(self.prompts)
        self.prompts.append(prompt)
        self.systems.append(system or "")
        if self.on_call is not None:
            self.on_call(index)
        text = self.replies[min(index, len(self.replies) - 1)]
        return type("Reply", (), {"ok": True, "text": text, "tokens_in": 10,
                                  "tokens_out": 10, "error_detail": "",
                                  "error_kind": ""})()


# ---------------------------------------------------------------- 夹具


def _ws(tmp_path: pathlib.Path) -> tuple[pathlib.Path, Store]:
    ws = tmp_path / "ws"
    st = Store(ws)
    st.init()
    return ws, st


def _setup(tmp_path: pathlib.Path) -> tuple[pathlib.Path, Store, _BlockingBackend, Conductor, str]:
    ws, st = _ws(tmp_path)
    backend = _BlockingBackend()
    cond = Conductor(st, policy=Policy(), backend=backend)
    me = cond.open_top_level_run(ROLE, TASK)
    return ws, st, backend, cond, me


def _loop(st: Store, ws: pathlib.Path, cond: Conductor, gate: _Gate, me: str, *,
          step_wait: float = 0.05, return_wait: float = 2.0,
          drain: float = 0.2) -> AgentLoop:
    reg = build_registry(store=st, conductor=cond, workspace_root=ws).registry
    loop = AgentLoop(role=ROLE, session_root=ws, registry=reg, conductor=cond,
                     seam=LlmSeam(role=ROLE, session_root=ws, gateway=gate,
                                  price=(0.0, 0.0), sid=SID),
                     store=st, sid=SID, max_steps=12, workspace_root=str(ws))
    # 判据把三个等待都压到毫秒级：默认值是为真机定的（20s / 5min / 5s），
    # 而这里要判的是「等不等得到、等到了之后发生什么」，不是那几个数本身。
    loop.child_step_wait_sec = step_wait
    loop.child_return_wait_sec = return_wait
    loop.child_exit_drain_sec = drain
    loop.my_task_id = me
    return loop


def _run(loop: AgentLoop, me: str) -> Any:
    return loop.run(TASK, summoned_by="user", my_task_id=me, depth=1)


def _in_flight(st: Store, parent: str) -> list[str]:
    """父名下此刻还在跑的子行编号（台账现读，不读内存里的句柄）。"""
    return [str(r.get("task_id")) for r in st.rows("tasks")
            if str(r.get("parent_task_id") or "") == parent
            and str(r.get("status") or "") == "running"
            and not str(r.get("kind") or "")]


def _kids(st: Store, parent: str) -> list[dict[str, Any]]:
    return [r for r in st.rows("tasks")
            if str(r.get("parent_task_id") or "") == parent
            and not str(r.get("kind") or "")]


def _step(run: Any, shape: str) -> dict[str, Any]:
    got = [s.result for s in run.steps if s.shape == shape]
    assert got, f"这一趟没有 {shape} 那一步：{[s.shape for s in run.steps]}"
    return got[0]


TARGETS = [{"role": KID, "task": f"第 {i} 件长活", "instance": str(i)} for i in (1, 2, 3)]
MANY = json.dumps({"summon_many": {"targets": TARGETS}}, ensure_ascii=False)
ONE = json.dumps({"summon": {"role": KID, "task": "一件长活"}}, ensure_ascii=False)


# ---------------------------------------------------------------- a. 父代理拿得到回合


def test_the_parent_gets_a_turn_while_three_long_children_are_still_running(
        tmp_path: pathlib.Path) -> None:
    """判据 a：派 3 个长任务 ⇒ 第二回合时台账里 3 条子行还是 running。

    改前红：`summon_many` 一直阻塞到三个都跑完 ⇒ 第二回合只可能出现在「0 条在跑」
    之后（`in_flight` 会读成空表）。真机形态就是 sylow3 的 M：92 分钟零回合。
    """
    ws, st, backend, cond, me = _setup(tmp_path)
    seen: dict[str, Any] = {"began": time.monotonic()}

    def on_call(index: int) -> None:
        if index == 1:
            seen["elapsed"] = time.monotonic() - seen["began"]
            seen["in_flight"] = _in_flight(st, me)
            seen["entered"] = backend.entered()
            backend.release()

    gate = _Gate([MANY, LOOK, FINAL, FINAL], on_call=on_call)
    loop = _loop(st, ws, cond, gate, me)
    run = _run(loop, me)
    assert run.stop_reason == "final", run.to_dict()

    assert len(gate.prompts) >= 2, gate.prompts
    assert "elapsed" in seen, "夹具没跑到第二次模型调用 ⇒ 这条判据什么也没测到"
    # 一、那一刻孩子真的还在跑（3 个都在），并且父代理已经问过第二次。
    assert len(seen["in_flight"]) == 3, (
        "父代理第二次被问到时名下只剩 "
        f"{len(seen['in_flight'])} 个在跑（要求 3）⇒ 它是等孩子跑完才拿到回合的",
        seen)
    assert seen["entered"] == 3, ("三个孩子的 handler 没有都进去过：",
                                  seen["entered"], backend.calls)
    # 二、「N 秒内」：判据的 N 是 5 秒（夹具里等待片是 50ms，真机是 20s）。
    assert seen["elapsed"] < 5.0, (
        f"第二次模型调用花了 {seen['elapsed']:.2f}s —— 父代理又被派活阻塞住了", seen)
    # 三、派活那一步如实说出「已派出 3 个、还在跑 3 个」。
    payload = _step(run, "summon_many")
    assert payload.get("preempted") is True, payload
    assert len(payload.get("dispatched") or []) == 3, payload
    assert len(payload.get("running") or []) == 3, payload
    assert payload.get("running_count") == 3, payload
    assert {i["status"] for i in payload["results"]} == {"running"}, payload["results"]
    # 四、三个孩子最后都回来了，返场那一段的读数在 notes 里。
    kids = _kids(st, me)
    assert len(kids) == 3, kids
    assert all(str(r["status"]) == "done" for r in kids), kids
    assert any("返场" in str(n) for n in run.notes), run.notes


# ---------------------------------------------------------------- b. 途中的 notice


def test_a_notice_that_arrives_mid_wait_is_delivered_at_the_next_return(
        tmp_path: pathlib.Path) -> None:
    """判据 b：孩子还在跑时到达的 notice ⇒ 下一次返场就投到（不必等阻塞结束）。

    改前红：下一次返场要等阻塞结束（孩子跑完），于是「投到时孩子在不在跑」
    在改前的树上永远读成「已经跑完了」—— 而那正是 D-52 那一族缺陷的形态。
    """
    ws, st, backend, cond, me = _setup(tmp_path)
    marker = "承重引理 conjecture 000002 已证出"
    made: list[str] = []
    seen: dict[str, Any] = {}

    def on_call(index: int) -> None:
        if index == 1:
            # 父代理拿到回合、下一步的提示词还没拼出来的时候，孩子还在跑 ⇒ 此刻投一条通报。
            made.append(cond.open_item(
                kind="notice", role=ROLE, expects="ack", action="notice",
                summary="跑到一半才到的通报", called_by=KID, parent_task_id=me, depth=2,
                input_key="preempt@mid"))
            cond.set_item_detail(made[0], f"{marker} —— 跑到一半才到的通报")
            seen["in_flight"] = _in_flight(st, me)
        if index == 2:
            seen["in_flight_at_delivery"] = _in_flight(st, me)
            backend.release()

    # 第 1 步的回复是坏 JSON ⇒ 那一步什么都没执行（`_hear` 不跑）⇒ 那条通报
    # 只能由返场点投到。这是"返场点真的在投"的必要条件。
    gate = _Gate([MANY, BAD_JSON, LOOK, FINAL, FINAL], on_call=on_call)
    loop = _loop(st, ws, cond, gate, me)
    run = _run(loop, me)
    assert run.stop_reason == "final", run.to_dict()

    assert len(seen.get("in_flight") or []) == 3, (
        "投通报那一刻孩子已经不在跑了 ⇒ 这条判据没测到边等边投", seen)
    # 一、下一次返场（第 2 次提示词）里就有它 —— 那时孩子还在跑。
    assert marker not in gate.prompts[1], (
        "通报出现在它到达之前那一次提示词里 ⇒ 夹具的到达时刻不是「返场之前」",
        gate.prompts[1][-800:])
    assert marker in gate.prompts[2], (
        "跑到一半投的通报没有在下一次返场投到（D-52 的形态）",
        gate.prompts[2][-1500:])
    assert len(seen.get("in_flight_at_delivery") or []) == 3, (
        "投到的那一刻孩子已经跑完了 ⇒ 这次投递不是返场，而是等完了再说", seen)
    # 二、只投一次（同一段文字在后面的提示词里是历史，不是重投）。
    assert gate.prompts[2].count(marker) == 1, (
        "同一条通报在同一次投递里出现了 "
        f"{gate.prompts[2].count(marker)} 次（要求恰好一次）", gate.prompts[2][-1500:])
    assert gate.prompts[3].count(marker) == 1, (
        "同一条通报在被投到之后又投了一次", gate.prompts[3][-1500:])
    # 三、板项状态机推进（投到即 seen），而不是一直 queued。
    row = next(r for r in st.rows("tasks") if str(r.get("task_id")) == made[0])
    assert str(row.get("item_state")) == "seen", row


# ---------------------------------------------------------------- c. 收工门


def test_final_is_refused_until_every_child_is_back(tmp_path: pathlib.Path) -> None:
    """判据 c（负控）：子全部回来之前 `final` 必须被拒 —— 可抢占不等于不等子。

    改前红：改前父代理在派活那一步就被阻塞到孩子跑完，所以「孩子在跑时说 final」
    这件事结构上不可能发生，这道门也就永远不响（它没有对象）。
    """
    ws, st, backend, cond, me = _setup(tmp_path)
    seen: dict[str, Any] = {}

    def on_call(index: int) -> None:
        if index == 1:
            seen["in_flight"] = _in_flight(st, me)
        if index == 2:
            backend.release()

    gate = _Gate([MANY, FINAL, FINAL, FINAL], on_call=on_call)
    loop = _loop(st, ws, cond, gate, me)
    run = _run(loop, me)

    assert len(seen.get("in_flight") or []) == 3, (
        "说 final 那一刻孩子已经不在跑了 ⇒ 这道门在这条夹具上没有对象", seen)
    refused = [s.result for s in run.steps
               if str(s.shape) == "final" and str(s.result.get("refused") or "")]
    assert refused, ("子还在跑时的 final 没有被拒", [s.result for s in run.steps])
    assert refused[0].get("refused") == "children_running", refused[0]
    assert len(refused[0].get("running") or []) == 3, refused[0]
    assert any("收工被拒" in str(n) for n in run.notes), run.notes
    # 被拒之后父代理仍然拿得到回合；孩子回来之后才真的收工。
    assert run.stop_reason == "final", run.to_dict()
    assert "收工" in str(run.final), run.final
    assert all(str(r["status"]) == "done" for r in _kids(st, me)), _kids(st, me)


# ---------------------------------------------------------------- d. 反真空


def test_without_preemption_the_first_two_criteria_go_red(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """判据 d（反真空）：把抢占打桩成不抢占 ⇒ a 与 b 的那两个读数必红。

    这一条是「a / b 真的在测抢占」的机器证明：没有它，「父代理拿到了回合」有可能
    只是被别的东西（别的形状、别的投递通道）满足的 —— 那样的判据什么都没钉住。
    """
    monkeypatch.setattr(AL, "PREEMPTIBLE_DISPATCH", False)
    ws, st, backend, cond, me = _setup(tmp_path)
    marker = "承重引理 conjecture 000002 已证出"
    made: list[str] = []
    seen: dict[str, Any] = {}

    def on_call(index: int) -> None:
        if index == 1:
            seen["in_flight"] = _in_flight(st, me)
            seen["entered"] = backend.entered()
            seen["kids_ended"] = all(str(r.get("ended_at") or "") for r in _kids(st, me))
            made.append(cond.open_item(
                kind="notice", role=ROLE, expects="ack", action="notice",
                summary=marker, called_by=KID, parent_task_id=me, depth=2,
                input_key="vac@mid"))
            cond.set_item_detail(made[0], f"{marker} —— 阻塞期间到的通报")
            backend.release()

    gate = _Gate([MANY, LOOK, FINAL, FINAL], on_call=on_call)
    loop = _loop(st, ws, cond, gate, me)
    run = _run(loop, me)
    assert run.stop_reason == "final", run.to_dict()

    # a 红：第二次被问到时孩子已经跑完了（改前的形态）。
    assert seen.get("in_flight") == [], (
        "抢占被打桩成不抢占，第二次模型调用时却还有孩子在跑 —— "
        "这说明父代理拿到回合不是抢占带来的", seen)
    assert seen.get("entered") == 3, seen
    # a 的派活载荷也不再是「已派出 / 还在跑」那一份。
    payload = _step(run, "summon_many")
    assert not payload.get("preempted"), payload
    assert payload.get("running_count", 0) == 0, payload
    # b 红：投那条通报时，孩子已经全部落终态。
    assert seen.get("kids_ended") is True, (
        "不抢占那一趟里，投通报时还有孩子没落终态 —— 与改前的形态不符", seen)
    first_hit = next(i for i, p in enumerate(gate.prompts) if marker in p)
    assert first_hit >= 1, gate.prompts

    # c / e / f 的改前红也在这里一并钉住：不抢占那一趟里
    # ① 没有任何返场挂账（句柄这个概念不存在）；
    assert loop._child_handles == [], loop._child_handles
    # ② 收工门没有对象（孩子在说 final 之前早就跑完了）；
    assert loop._children_hold() == "", loop._children_running()
    # ③ 单任务那条路给的仍是终局，而不是「已派出 / 还在跑」。
    one = loop._do_summon({"role": KID, "task": "一件长活"})
    assert one.get("status") == "done", one
    assert not one.get("preemptible"), one
    assert not one.get("dispatched") and not one.get("running"), one


# ---------------------------------------------------------------- e. 结果等价


def _payload_rows(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    keys = ("role", "action", "instance", "status", "outcome", "refusal_reason")
    return [{k: item.get(k) for k in keys} for item in payload.get("results") or []]


def test_the_preempted_batch_ends_up_equivalent_to_the_blocking_one(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """判据 e：预占之后 `summon_many` 的最终 payload 与阻塞版等价。

    「等价」的机器形态：逐项同序、同一组 (role, action, instance, status, outcome,
    refusal_reason)。混一条会被拒的目标进去（M 不可被召唤）⇒ 拒绝也在同一个位置
    给出同一个理由码，且两次的列表长度都恒等于输入长度。
    """
    targets = [
        {"role": KID, "task": "第一件长活", "instance": "1"},
        {"role": "M", "task": "这件派不出去（M 不可被召唤）"},
        {"role": KID, "task": "第三件长活", "instance": "3"},
    ]

    def _dispatch(*, preemptible: bool, name: str):
        sub = tmp_path / name
        sub.mkdir()
        ws, st = _ws(sub)
        backend = _BlockingBackend()
        cond = Conductor(st, policy=Policy(), backend=backend)
        me = cond.open_top_level_run(ROLE, TASK)
        gate = _Gate([FINAL])
        loop = _loop(st, ws, cond, gate, me, step_wait=0.05, return_wait=2.0)
        if not preemptible:
            # 阻塞式那一趟的孩子必须先在跑起来之前放行：那一路是"等全部完成"，
            # 而这条夹具的孩子只有判据自己放行 —— 不放行就是自己把自己锁死。
            backend.release()
        monkeypatch.setattr(AL, "PREEMPTIBLE_DISPATCH", preemptible)
        out = loop._do_summon_many({"targets": targets})
        return out, st, me, loop, backend

    blocking, st1, me1, _l1, b1 = _dispatch(preemptible=False, name="block")
    preempted, st2, me2, loop2, b2 = _dispatch(preemptible=True, name="pre")
    # 预占那一趟：先确认它真的是「还没回来」的那一档，再放行、再把结果取回来。
    assert preempted.get("preempted") is True, preempted
    assert any(i["status"] in ("running", "pending") for i in preempted["results"]), preempted
    assert preempted.get("running_count", 0) >= 1, preempted
    b2.release()
    folded: list[Any] = []
    handle = loop2._child_handles[0]["handle"]
    deadline = time.monotonic() + 30.0
    while time.monotonic() < deadline:
        got = loop2._children_round_trip(step=1, run=AL.LoopRun(role=ROLE, task=TASK),
                                         wait=True)
        folded.extend(got.get("settled") or ())
        if handle.done():
            break
    assert handle.done(), ("放行之后那一批没有全部落定", handle.poll())

    # 一、把「还在跑 / 还在排队」换成落定后的那一份，逐项应与阻塞版相同。
    final_rows = list(_payload_rows(preempted))
    settled = {str(getattr(r, "task_id", "")): r for r in folded}
    for row, item in zip(final_rows, preempted["results"]):
        got = settled.get(str(item.get("task_id") or ""))
        if got is not None:
            row.update(status=got.status, outcome=got.outcome,
                       refusal_reason=got.refusal_reason)
    # 排队的那一项在预占那一趟里还没有编号 ⇒ 按"同一位置、同一结局"补上
    # （`handle.results()` 是权威的那一份，逐项按下标对齐）。
    whole = handle.results()
    for i, row in enumerate(final_rows):
        if row["status"] in ("running", "pending") and i < len(whole):
            row.update(status=whole[i].status, outcome=whole[i].outcome,
                       refusal_reason=whole[i].refusal_reason)
    assert final_rows == _payload_rows(blocking), (final_rows, _payload_rows(blocking))
    # 二、长度恒等于输入长度（两条路都不许因为「还没回来」或「被拒」而变短）。
    assert len(final_rows) == len(targets) == len(_payload_rows(blocking)), final_rows
    # 三、refusal 在同一个位置、同一个理由码。
    refused_block = [i for i, r in enumerate(_payload_rows(blocking)) if r["refusal_reason"]]
    refused_pre = [i for i, r in enumerate(final_rows) if r["refusal_reason"]]
    assert refused_block == refused_pre == [1], (refused_block, refused_pre)
    assert final_rows[1]["refusal_reason"] == "forbidden_edge", final_rows[1]
    # 四、台账：两条路都恰好 3 行（被拒的那一条也有一行终态行）。
    assert len(_kids(st1, me1)) == 3, _kids(st1, me1)
    assert len(_kids(st2, me2)) == 3, _kids(st2, me2)


# ---------------------------------------------------------------- f. 单任务同形


def test_the_single_summon_returns_a_handle_and_folds_back_like_a_batch(
        tmp_path: pathlib.Path) -> None:
    """判据 f（其一）：单任务 `summon` 与整批同形 —— 句柄读数 / 返场投递 / 收工门。

    改前红：改前 `_do_summon` 一直阻塞到孩子跑完，它那一步的返回值里只有终局
    （`status=done`），既没有「还在跑」也没有任何返场挂账。
    """
    ws, st, backend, cond, me = _setup(tmp_path)
    loop = _loop(st, ws, cond, _Gate([FINAL]), me)

    out = loop._do_summon({"role": KID, "task": "一件长活", "brief": "长活"})
    assert out.get("status") == "running", out
    assert out.get("preemptible") is True, out
    tid = str(out.get("task_id") or "")
    assert tid, out
    assert out.get("dispatched") == [tid] and out.get("running") == [tid], out
    assert _in_flight(st, me) == [tid], _in_flight(st, me)
    # 一、句柄挂上了（返场点从它取结果），收工门也认得它。
    assert loop._children_running() == [tid], loop._child_handles
    hold = loop._children_hold()
    assert "children_running" in hold and tid in hold, hold
    # 二、放行之后返场那一段把它带回来（含孩子的结论与记录路径）。
    backend.release()
    got: dict[str, Any] = {}
    deadline = time.monotonic() + 20.0
    while time.monotonic() < deadline:
        got = loop._children_round_trip(step=1, run=AL.LoopRun(role=ROLE, task=TASK),
                                        wait=True)
        if got.get("settled"):
            break
    assert got.get("settled"), ("单任务那条路没有返场投递", got)
    text = str(got.get("text") or "")
    assert tid in text and "跑完了" in text, text
    assert "out/tasks/" in text, text           # 孩子的完整记录路径
    assert "的结论" in text, text               # 孩子的结论
    assert loop._children_running() == [], loop._child_handles
    assert loop._children_hold() == "", "孩子回来了，收工门还拦着"


def test_the_single_summon_gives_the_parent_a_turn_mid_run(tmp_path: pathlib.Path) -> None:
    """判据 f（其二）：单任务那条路上父代理也拿得到回合（不许只修 batch）。"""
    ws, st, backend, cond, me = _setup(tmp_path)
    seen: dict[str, Any] = {}

    def on_call(index: int) -> None:
        if index == 1:
            seen["in_flight"] = _in_flight(st, me)
            backend.release()

    gate = _Gate([ONE, LOOK, FINAL, FINAL], on_call=on_call)
    loop = _loop(st, ws, cond, gate, me)
    run = _run(loop, me)
    assert run.stop_reason == "final", run.to_dict()
    assert len(seen.get("in_flight") or []) == 1, (
        "单任务派活仍然阻塞到孩子跑完（父代理第二次被问到时 0 条在跑）", seen)
    payload = _step(run, "summon")
    assert payload.get("preemptible") is True, payload
    assert payload.get("status") == "running", payload
    assert any("返场" in str(n) for n in run.notes), run.notes
    assert all(str(r["status"]) == "done" for r in _kids(st, me)), _kids(st, me)

"""判据：父代理"等"子代理 —— 学 DSH 的通知模型（S-G / 业主 2026-10-10 裁定 15）。

## 这一组守七件事

1. 唤醒判据只认"没投递过的"留言（正控 + 负控）：一条新留言 ⇒ 值得再开一轮；
   同一条被读过（已投递）⇒ 不再唤醒（否则"有人在说话"会把"轮次用尽"变成死循环）。
2. 唤醒有界（负控）：一次唤醒只多开一轮（`WAKE_ALLOWANCE`），
   而 `waiting_for_user`（人没答）仍然排在它前面 —— 那一档不许被"有人说话"绕过去。
3. 端到端真的多开了一轮：轮次用尽 + 有没投递的留言 ⇒ `rounds_done` 多一、
   `woke_rounds == 1`、事件里那一轮的 `woke` 为真；没有留言 ⇒ 一轮都不多开。
4. "等"这条路上没有 sleep（施工单 S-G 第 3 条逐字禁的形态）：源码级断言 +
   行为级读数（一次纯读，不是轮询）。
5. 收工读数不拦收工（裁定 1 + 15）：收工时名下有在飞的孩子 ⇒ 落一句读数
   （点名是谁、明说"不拦收工"），而这一趟照旧收工；读不成也要如实说"没读成"。
6. 结算读数会重算（DSH `settlementState` 的 `retry` 那一格）：读数期间台账又变了
   ⇒ `retried=True` 并重算，不是拿旧快照下结论。
7. 通知带上来源那一格（DSH 的 `source{kind, form, summary}`）：广播 / 普通留言 /
   框架通报在读数上分得开 —— 没有这一格，"这条是不是孩子的交差通报"只能靠猜。
"""

from __future__ import annotations

import inspect
import json
import pathlib
import time
from typing import Any

import pytest

import test_agent_loop as TAL
from agentflow import agent_loop as AL
from agentflow import autonomy as AU
from agentflow import sessions as SS
from agentflow.conductor import Conductor, LocalBackend
from agentflow.store import Store
from test_autonomy import ScriptedGateway, _finals, _ws


def _reply(obj: dict) -> str:
    return json.dumps(obj, ensure_ascii=False)


def _child_row(cond: Conductor, parent: str, *, status: str = "running", key: str = "sg@c") -> str:
    return cond._write_new_row({
        "task_id": "", "role": "D", "action": "run_once", "called_by": "M",
        "parent_task_id": parent, "depth": 2, "input_key": key, "status": status,
        "outcome": None if status in ("pending", "running") else "ok",
        "refusal_reason": None, "instance": "", "detail": "一个子代理",
        "error": None, "started_at": "2026-10-10T22:00:00+08:00",
        "ended_at": None if status in ("pending", "running") else "2026-10-10T22:05:00+08:00",
        "tokens": 0, "usd": 0.0, "artifacts": [], "inputs": [],
    }, note="start:D.run_once")


def test_a_fresh_message_wakes_and_a_delivered_one_does_not(tmp_path: pathlib.Path) -> None:
    """正控 + 负控（唤醒判据）：没投递过的留言算唤醒，投递过的不算。"""
    root = tmp_path / "ws"
    root.mkdir()
    AL.send_message(root, sender="D", to="M", subject="我这边有新消息", body="看看", sid="t")
    got = AL.pending_wake(root, "M", sid="t")
    assert got["checked"] is True and got["count"] == 1, got
    # 负控：读过之后（投递登记写下去）同一份收件箱不再是唤醒理由。
    assert AL.mark_delivered(root, "M", got["pending"], sid="t") == ""
    again = AL.pending_wake(root, "M", sid="t")
    assert again["checked"] is True and again["count"] == 0, again
    # 三态：读不成 ⇒ checked=False（不许折成"没有新消息"）
    broken = tmp_path / "nope"
    monkey = AL.inbox_digest
    try:
        AL.inbox_digest = lambda *a, **k: ("", [], ["会话读不成（PermissionError: x）"])
        bad = AL.pending_wake(broken, "M", sid="t")
    finally:
        AL.inbox_digest = monkey
    assert bad["checked"] is False and bad["count"] == 0 and "读不成" in bad["why"], bad


def test_the_wake_is_bounded_and_yields_to_waiting_for_user(tmp_path: pathlib.Path) -> None:
    """负控（有界）：一次唤醒只多开一轮；"人没答"仍然排在"有人说话"前面。"""
    base: dict[str, Any] = {"rounds": 1, "spent_usd": 0.0, "usd_budget": None,
                            "stop_path": None, "user_answer": ""}
    assert AU._stop_before_round(2, wake_pending=1, woke=0, **base) == "", \
        "有没投递的留言却不让开下一轮 ⇒ 永远不会被唤醒"
    assert AU._stop_before_round(2, wake_pending=1, woke=AU.WAKE_ALLOWANCE, **base) == "rounds", \
        "唤醒没有上限 ⇒ 只要有人在说话就永远不停"
    assert AU._stop_before_round(2, wake_pending=0, woke=0, **base) == "rounds"
    # 顺序：上一轮停在等用户、那个问题还挂着 ⇒ 即使有留言也不许开下一轮
    assert AU._stop_before_round(2, last_stop_reason="waiting_for_user",
                                 pending_qids=("q0001",), wake_pending=9, woke=0, **base) == \
        "waiting_for_user"
    # 钱与人工开关照旧优先（唤醒不是硬闸的豁免）：预算用尽 + 有留言 ⇒ 停，
    # 理由仍是文档化的那一个（`rounds` 排在 `budget` 之前，顺序一个字没改）。
    spent = AU._stop_before_round(2, wake_pending=1, woke=0,
                                  **{**base, "usd_budget": 0.0, "spent_usd": 1.0})
    assert spent in ("rounds", "budget"), spent
    assert spent != "", "唤醒把预算那一道硬闸挤掉了"


def test_the_wake_opens_exactly_one_more_round(tmp_path: pathlib.Path,
                                               monkeypatch: pytest.MonkeyPatch) -> None:
    """正控（端到端）：轮次用尽 + 有没投递的留言 ⇒ 真的多开一轮，且只多开一轮。

    这里把 `pending_wake` 换成替身（判据 1 已经把真机制测过了）⇒ 这一条只判接线：
    `_stop_reason_for` 有没有把唤醒读数交给 `_stop_before_round`、多开的那一轮有没有被计数。
    """
    st, registry, root = _ws(tmp_path)
    monkeypatch.setattr(AL, "pending_wake",
                        lambda *a, **k: {"checked": True, "pending": ["m0001"], "count": 1,
                                         "why": "", "text": ""})
    gw = ScriptedGateway(_finals("第 1 轮", "第 2 轮（被唤醒）"))
    run = AU.run_autonomous("D", "把这件事做完", store=st, registry=registry, gateway=gw,
                            rounds=1, max_steps=3, sid="t")
    assert run.rounds_done == 2, run.to_dict()
    assert run.woke_rounds == 1, run.to_dict()
    assert run.stop_reason == "rounds", run.stop_reason
    events, problems = SS.read_session(root, sid="t")
    assert not problems, problems
    rounds = [e for e in events if e.get("kind") == "autonomy_round"]
    assert [e.get("woke") for e in rounds] == [False, True], rounds
    # 负控（同一套接线）：没有留言 ⇒ 一轮都不多开
    st2, registry2, root2 = _ws(tmp_path / "second")
    monkeypatch.setattr(AL, "pending_wake",
                        lambda *a, **k: {"checked": True, "pending": [], "count": 0,
                                         "why": "", "text": ""})
    gw2 = ScriptedGateway(_finals("第 1 轮", "不该跑到这里"))
    run2 = AU.run_autonomous("D", "把这件事做完", store=st2, registry=registry2, gateway=gw2,
                             rounds=1, max_steps=3, sid="t")
    assert run2.rounds_done == 1 and run2.woke_rounds == 0, run2.to_dict()


def test_the_wait_path_never_sleeps(tmp_path: pathlib.Path) -> None:
    """负控（施工单 S-G 第 3 条逐字禁的形态）：这条路上没有 sleep，也不轮询。

    这一条钉的是调用，不是"提到过这个词"：第一版判据写成 `"sleep" not in src`，
    而 `pending_wake` 的 docstring 里正引用着施工单那句"不许 sleep 等" ⇒ 它把一句
    正确的注释判成了违规（本项目反复踩的形态：词出现过 ≠ 那件事发生了）。
    """
    for fn in (AL.pending_wake, Conductor.settlement_reading, Conductor.poke_generation,
               AU._stop_before_round):
        src = inspect.getsource(fn)
        assert "time.sleep(" not in src and ".sleep(" not in src, \
            f"{fn.__qualname__} 里有 sleep 调用 ⇒ 那是 DSH 没有的形态"
    # 行为级读数：一次纯读（不是"等一会儿再看"）—— 空工作区上必须是毫秒级。
    root = tmp_path / "ws"
    root.mkdir()
    t0 = time.monotonic()
    AL.pending_wake(root, "M", sid="t")
    assert time.monotonic() - t0 < 1.0, "一次唤醒读数不该花掉接近一秒（那是轮询的口吻）"


def test_the_closing_reading_never_blocks_the_closing(tmp_path: pathlib.Path) -> None:
    """正控（读数，不拦）：收工时名下有在飞的孩子 ⇒ 一句点名读数；读不成也如实说。"""
    st = Store(tmp_path / "ws")
    st.init()
    cond = Conductor(st, policy=None, backend=LocalBackend({}))
    loop = AL.AgentLoop(role="M", session_root=st.root, registry=None, seam=None,
                        conductor=cond, sid="t")
    loop.my_task_id = "t-top"
    assert loop._in_flight_reading() == "", "一条在飞都没有时不许落噪声"
    _child_row(cond, "t-top", status="running", key="sg@run")
    note = loop._in_flight_reading()
    assert "还有 1 条在飞" in note and "不拦收工" in note, note
    assert "D·" in note, note          # 点名是谁
    # 三态：台账读不成 ⇒ 明说没读成（不许当成"都回来了"）
    cond.reading_break = True

    class _Broken:
        def settlement_reading(self, _tid: str) -> dict:
            return {"checked": False, "reason": "台账读不成（RuntimeError: x）"}

    loop.conductor = _Broken()
    bad = loop._in_flight_reading()
    assert "没读成" in bad and "都回来" not in bad, bad
    # 这一格是读数：源码里它只在收尾那一段被调用，且不改 `stop_reason`。
    src = inspect.getsource(AL.AgentLoop.run)
    assert "_in_flight_reading()" in src, "收工读数没接进 run"
    assert "run.stop_reason =" not in src.split("_in_flight_reading()")[1][:200], \
        "收工读数那一行附近在改 stop_reason ⇒ 它就不再是读数了"


def test_the_settlement_reading_recomputes_when_the_ledger_moves(tmp_path: pathlib.Path) -> None:
    """正控（retry 那一格）：读数期间台账变了 ⇒ `retried=True` 并重算。

    搬的是 DSH `settlementState` 的 `retry`（poke 世代比较）：拿旧快照下"孩子们都回来了"
    的结论，而读的中间恰好有一个孩子交差 —— 那个结论在写下的那一刻就已经过期了。
    """
    st = Store(tmp_path / "ws")
    st.init()
    cond = Conductor(st, policy=None, backend=LocalBackend({}))
    _child_row(cond, "t-top", status="running", key="sg@a")
    calm = cond.settlement_reading("t-top")
    assert calm["checked"] is True and calm["in_flight"] == 1, calm
    assert calm["retried"] is False, calm

    real = cond._tasks
    calls = {"n": 0}

    def moving() -> list[dict]:
        calls["n"] += 1
        rows = list(real())
        if calls["n"] == 2:            # 读数中途：多出一个刚交差的孩子
            _child_row(cond, "t-top", status="done", key="sg@b")
        return rows

    cond._tasks = moving          # type: ignore[method-assign]
    moved = cond.settlement_reading("t-top")
    assert moved["retried"] is True, moved
    assert moved["checked"] is True, moved
    cond._tasks = real            # type: ignore[method-assign]
    # 三态：台账读不成 ⇒ checked=False（不是"都回来了"）
    def boom() -> list[dict]:
        raise RuntimeError("台账读不成")

    cond._tasks = boom            # type: ignore[method-assign]
    dead = cond.settlement_reading("t-top")
    assert dead["checked"] is False and "读不成" in dead["reason"], dead
    cond._tasks = real            # type: ignore[method-assign]


def test_the_notification_carries_its_source(tmp_path: pathlib.Path) -> None:
    """正控（source 那一格）：广播 / 普通留言 / 框架通报在读数上分得开。"""
    assert AL.message_source({"from": "M", "channel": "public"})["kind"] == "broadcast"
    assert AL.message_source({"from": "D", "channel": "private"})["kind"] == "message"
    assert AL.message_source({"from": "M", "by_framework": True})["kind"] == "subagent-settled"
    assert AL.message_source({"from": "user"})["kind"] == "user"
    src = AL.message_source({"from": "D", "subject": "我读到第三行"})
    assert src["form"] == "notice" and src["summary"] == "我读到第三行", src

    # 端到端：这一步听到的东西里带着 `source`（否则"这条是不是孩子的通报"只能靠猜）。
    #
    # 两处夹具要点（都是第一版踩出来的）：① 消息必须在开头那一次收件箱渲染之后才到 ——
    # 跑之前就发好的留言会在开场那一段被渲染并登记投递，`_hear` 那时候已经没得听了
    # （"投递登记推迟到模型真被问过一次"说的就是这件事）；② 剧本第一步必须是非 final
    # 的动作 —— final 那一支直接 break，走不到 `_hear`。
    st, cond, registry, gw, root = TAL._wired(
        tmp_path / "tal",
        {"M": [_reply({"tool": "conductor.role_spec", "args": {"role_name": "C"},
                       "why": "先看一眼 C 的规格"}), _reply({"final": "收工"})]},
        max_steps=3)

    class _SendsDuringTheFirstCall(TAL.ScriptedGateway):
        """第 1 次回答时把两条留言投进这一趟的工作区（模拟"跑到一半来消息"）。"""

        def complete(self, prompt: str, *, scope: str = "", system: str | None = None,
                     **kw: Any) -> Any:
            if len(self.prompts) == 0:
                AL.send_message(root, sender="D", to="#public", subject="公共一句话",
                                body="大家好", sid="t-src")
                AL.send_message(root, sender="D", to="M", subject="私聊一句",
                                body="只给你", sid="t-src")
            return super().complete(prompt, scope=scope, system=system, **kw)

    gw["M"] = _SendsDuringTheFirstCall(gw["M"].replies)
    run = AL.run_role("M", "听一句话", store=st, registry=registry, conductor=cond,
                      seam=AL.LlmSeam(role="M", session_root=root, gateway=gw["M"],
                                      price=(0.0, 0.0), sid="t-src"),
                      workspace_root=str(root), sid="t-src", from_env=False)
    heard = (run.steps[0].result.get("新消息") or []) if run.steps else []
    assert heard, "这一步一条都没听到 ⇒ 夹具没造出'跑到一半来消息'"
    # 端到端这一半只判"听到了的那条带着来源格"，且来源与它真实的信道一致。
    # 广播那一半在这里看不见：S6-a 把公共频道的可见面收窄成"发信人的直接子代理"，
    # 而 D 不是 M 的子代理 ⇒ M 看不到 D 的广播（那是另一条已判过的口径，不是这里的缺口）。
    # 所以三种 kind 的区分由上面那四行单位级判据守，这一条守"它真的被写进了听到的东西里"。
    for item in heard:
        src = item.get("source")
        assert isinstance(src, dict) and set(src) == {"kind", "form", "summary"}, item
        assert src["form"] == "notice", item
        if item.get("channel") == "private":
            assert src["kind"] == "message", item
            assert src["summary"] == item.get("subject"), item

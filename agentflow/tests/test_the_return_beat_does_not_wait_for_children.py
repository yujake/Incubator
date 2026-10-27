# -*- coding: utf-8 -*-
"""Q33：派活之后那一拍不经过子代理等待（"等不等子"与"要不要返场"同一处判）。

## 这一份钉的是哪一件事

Q22 把"派完下一拍给模型一个回合"做出来了，可那一拍之前还压着 `_deliver_mailbox`
的那一句 `wait=not bool(wakes.get("consumed"))`：`_children_round_trip` 会先等最多
`child_return_wait_sec`（缺省 `CHILD_RETURN_WAIT_SEC=300` 秒）。于是业主口径的
"派完立刻给一个回合"实际是"派完最多等 5 分钟再问"。残留是两半，不是一半：

1. 孩子跑得比那个窗口久 ⇒ 父代理白等满 300 秒才拿到第一个回合；
2. 孩子在那个窗口里回来 ⇒ 等待把句柄吃掉了（`_children_round_trip` 把落定的句柄
   从 `self._child_handles` 摘掉），`_return_reading` 事后读 `owed_batch=False`，
   返场那一拍被"手上有活（`settled` 非空）"接走 —— `reentry_turns` / `return_given`
   一次都不记，返场这件事在读数上根本不存在。

改法不在这里判：`wait` 由 `_should_wait_for_children` 一处给，而那一位只读返场判据
（`_return_reading`）的结论。这一份钉的就是"那一位真的在承重"。

## 判据（a / b 改前红，c / d 两条正控，e 反真空，f 探针两栏）

| 条 | 判据 | 改前红在哪 |
|---|---|---|
| a | 派 2 个长活 ⇒ 派活后那一拍 `wait_reason=="return"`、`waited_sec==0`、模型回合发生、那一刻两条子行都还是 running、且"派完到第一个模型回合"远小于 `child_return_wait_sec` | 那一拍先等满 `child_return_wait_sec`：`wait_reason` 是 `slice`、墙钟 ≥ 那个值 |
| b | 孩子在那个窗口里回来（父代理一开口等它、它就回来）⇒ 返场那一拍仍然发生、`reentry_turns>=1`、`return_given` 点名那一批 | 等待把句柄吃掉 ⇒ `owed_batch=False`、返场账一次都不记 |
| c | 正控：不是返场的那一拍照旧等（`waited_sec>0`、`wait_reason=="slice"`） | 改前也等（守"不许整体取消 `CHILD_RETURN_WAIT_SEC`"） |
| d | 正控：`woke` 那一支语义不变（仍 `skip_model`） | 改前也是（守 p206 第 4 条） |
| e | 反真空：把"返场 ⇒ 不等"打桩掉 ⇒ a 与 b 的读数必红 | 这一条是"a/b 真的在读那一处"的机器证明 |
| f | 探针两栏：同一趟夹具下"派完到第一个模型回合"的耗时，改前 / 改后各一列（b 那档单列"账有没有记"） | 这两列就是外推的机器读数（真机缺省 300 秒见报告） |

## 边界

全部 tmp 工作区、替身模型、替身后端（孩子的"跑很久"由 `threading.Event` 造），
零真实模型调用。等待那一段被压到毫秒级 / 秒级（`child_return_wait_sec` 在夹具里
现改），判据只比较大小关系，不依赖那几个数本身。挂机那一拍真睡的地方换成"只记账"
（与 `tests/test_park_is_a_real_stop.py` 同一档的替身缝）。
"""
from __future__ import annotations

import pathlib
import time
from typing import Any, Callable, Mapping

import pytest

from agentflow import agent_loop as AL

import test_dispatch_owes_one_return_beat as TQ

#: 判据 a / c / e 用的"长等"：夹具压到 2 秒（真机缺省 300 秒），只为让"等了多少"
#: 在墙钟上量得出来。判据只比较大小关系，这个数本身不进任何断言口径。
LONG_WAIT = 2.0
#: 判据 b / e 用的窗口：孩子"一被等就回来"，窗口给宽一点只是为了不含竞态。
SETTLE_WAIT = 2.0


# ------------------------------------------------------------------ 替身


class _MailboxSpy:
    """把 `_deliver_mailbox` 每一拍的投递读数抄一份。

    读数取的是这一拍投递时的 `{return_owed, wait{reason, waited_sec}, running,
    settled}` —— 返场判据给的那个结论与"这一拍等了多久"就在这两格上，判据 a / c
    断的是它们，不是墙钟统计量。

    2026-10-26（F1a 第 ② 条）：`return_owed` 这一格是本替身从返场判据
    （`_return_reading` 的 `owed`）上现记的，不是投递读数里的字段 —— 投递读数原来
    多抄一份 `return_beat`，全仓 0 个读者（事件里那份副本同一天删掉）。这一条判据
    要的正是"判据说欠、这一拍还是等了"那一态（e 条），所以它直接读判据本身：
    读判据的结论是准的，读一份为它而留的副本才是"为实现留一格读数"。
    """

    def __init__(self) -> None:
        self.real = AL.AgentLoop._deliver_mailbox
        self.beats: list[dict[str, Any]] = []
        self.prompts_at: Callable[[], int] = lambda: 0
        self.slices_at: Callable[[], int] = lambda: 0
        #: 返场判据最近一次给的结论（`_return_reading` 的包装写、投递那一拍读）。
        self.last_owed: bool = False

    def stub(self) -> Callable[..., dict[str, Any]]:
        def deliver(self_: Any, *, step: int, messages: list[dict[str, Any]],
                    run: Any) -> dict[str, Any]:
            out = self.real(self_, step=step, messages=messages, run=run)
            children = dict(out.get("children") or {})
            waited = dict(children.get("wait") or {})
            self.beats.append({
                "step": int(step),
                "return_owed": bool(self.last_owed),
                "wait_reason": str(waited.get("reason") or ""),
                "waited_sec": float(waited.get("waited_sec") or 0.0),
                "running": [str(x) for x in (children.get("running") or ())],
                "settled": [str(getattr(r, "task_id", ""))
                            for r in (children.get("settled") or ())],
                "calls": int(self.prompts_at()),
                "slices": int(self.slices_at()),
            })
            return out

        return deliver


def _arm_mailbox_spy(monkeypatch: pytest.MonkeyPatch, state: dict[str, Any]) -> _MailboxSpy:
    """在第一次模型调用里装上信箱读数（`_scenario` 里没有"跑之前"的钩子）。

    装在这里是准的：返场那一拍必然在第一个回合之后，而这一位只是读数抄本，
    装晚一拍不改变任何控制流。

    同时给返场判据套一层只读的抄本（`_return_reading` 的 `owed` 现记）：投递那一拍
    先调判据、再取孩子，所以投递读数返回时 `last_owed` 就是这一拍的结论。
    """
    spy = _MailboxSpy()
    spy.prompts_at = lambda: len(state["gate"].prompts)
    spy.slices_at = lambda: len(state["watch"].asked)
    real_reading = AL.AgentLoop._return_reading

    def reading(self_: Any, **kw: Any) -> dict[str, Any]:
        got = real_reading(self_, **kw)
        spy.last_owed = bool(got.get("owed"))
        return got

    monkeypatch.setattr(AL.AgentLoop, "_return_reading", reading)
    monkeypatch.setattr(AL.AgentLoop, "_deliver_mailbox", spy.stub())
    state["mailbox_spy"] = spy
    return spy


def _arm_dispatch(monkeypatch: pytest.MonkeyPatch, *,
                  stamp: dict[str, Any] | None = None,
                  release_on_wait: dict[str, Any] | None = None) -> None:
    """在"派活那一步"的出口挂两件夹具（两者都要，故只包一次 `_do_summon_many`）。

    - `stamp`：记下派完的时刻（`t0`）。判据 a 的"派完到第一个模型回合"从这一格
      算起 —— 从模型那一拍算会把派活那一步自己的耗时（写子行 / 登记名册 / 起等待表）
      算进去，那与"等子"是两件事。
    - `release_on_wait`：让孩子"一被等就回来"：释放挂在返场点那次等待的路径上，
      零延时、零竞态。为什么挂在 `rec["wait"]` 上（而不是一个 `time.sleep`）：这一档
      要造的事实是"孩子在等待窗口里回来"，而窗口打开的时刻正是父代理开口等它的
      那一刻 —— 由等待本身触发，顺序是判据造出来的，不是碰巧。

    为什么在 `_do_summon_many` 之后才装：派活那一步自己也会等 `child_step_wait_sec`
    （`_do_summon_many` 里的那一次 `_wait_for_children`，夹具里 0.02 秒），挂在它身上
    就变成"派完立刻回来"，那一档的返场判据没有对象（孩子已经落定 ⇒ `own_running` 空）。
    """
    real_many = AL.AgentLoop._do_summon_many

    def many_then_arm(self_: Any, payload: Mapping[str, Any]) -> dict[str, Any]:
        out = real_many(self_, payload)
        if stamp is not None:
            stamp["t0"] = time.monotonic()
        if release_on_wait is None:
            return out
        backend = getattr(self_.conductor, "backend", None)
        for rec in list(self_._child_handles):
            real_wait = rec.get("wait")
            if not callable(real_wait):
                continue

            def waiting(*args: Any, _rec: Mapping[str, Any] = rec,
                        _real: Callable[..., Any] = real_wait, **kw: Any) -> Any:
                release_on_wait["fired"] = True
                release = getattr(backend, "release_all", None)
                if callable(release):
                    release()
                # 等孩子真的落定："在窗口里回来"这件事是确定的（不是 50ms 的赌）。
                handle = _rec.get("handle")
                done = getattr(handle, "done", None)
                deadline = time.monotonic() + 10.0
                while callable(done) and not done() and time.monotonic() < deadline:
                    time.sleep(0.005)
                return _real(*args, **kw)

            rec["wait"] = waiting      # type: ignore[index]
        return out

    monkeypatch.setattr(AL.AgentLoop, "_do_summon_many", many_then_arm)


def _return_beats(spy: _MailboxSpy) -> list[dict[str, Any]]:
    """"判据说这一拍欠模型一个回合"的那几拍（按 `_return_reading` 的 `owed` 筛）。

    为什么按判据筛而不是按 `wait_reason == "return"` 筛：e 条要把判据打桩掉（那一拍
    照旧等），此时 `wait_reason` 变成 `slice` 而"判据说欠"这个事实没变 —— 先按 `owed`
    找到对象，再断 `wait_reason` 与 `waited_sec`，才分得出"不等是谁给的"。
    """
    return [b for b in spy.beats if b["return_owed"]]


# ------------------------------------------------------------------ a. 派活后那一拍


def test_the_dispatch_beat_asks_the_model_without_waiting(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """判据 a：派 2 个长活 ⇒ 派活后那一拍不等子就问模型，那一刻两条子行都还是 running。

    改前红：那一拍走 `wait=not wakes.consumed` ⇒ `True`（没有唤醒），而孩子刚派出去
    正在跑 ⇒ `_wait_for_children(300)` 先等满，`wait_reason` 是 `slice`、墙钟 ≥300 秒，
    之后才问模型。真机形态就是"派完最多等 5 分钟再问"。
    """
    seen: dict[str, Any] = {}
    _arm_dispatch(monkeypatch, stamp=seen)

    def on_call(index: int, prompt: str, state: dict[str, Any]) -> None:
        if index == 0:
            # 判据 a 要"孩子还在跑时父代理已经拿到回合" ⇒ 这一趟的孩子由判据在
            # 返场那拍之后再放行（放行点见 index == 1 那一支）。
            state["loop"].child_return_wait_sec = LONG_WAIT
            _arm_mailbox_spy(monkeypatch, state)
        if index == 1:
            seen["elapsed"] = time.monotonic() - seen["t0"]
            seen["in_flight"] = TQ._running(state["st"], state["me"])
            state["backend"].release_all()

    state = TQ._scenario(tmp_path, monkeypatch,
                         replies=[TQ.MANY2, TQ.LOOK, TQ.LOOK, TQ.FINAL, TQ.FINAL],
                         on_call=on_call, release_after=3)
    run = state["run"]
    spy: _MailboxSpy = state["mailbox_spy"]

    assert run.stop_reason == "final", run.to_dict()
    # 一、那一刻孩子真的还在跑（两条都在），而父代理已经被问过一次。
    assert sorted(seen.get("in_flight") or []) == sorted(
        str(r.get("task_id")) for r in TQ._rows(state["st"], state["me"])), (
            "返场那一拍被问到时名下已经没有在跑的子 ⇒ 这条判据没测到「孩子还在跑」", seen)
    assert len(seen["in_flight"]) == 2, seen
    # 二、派完到第一个模型回合：远小于 child_return_wait_sec（改前是"等满"）。
    #     阈值取一半而不是"接近 0"：那一拍自己有开销（推时钟 / 读信箱 / 判据 / 拼提示词，
    #     本机实测 ≈0.3 秒），而判据要分的是"等子"那一半（实测 ≈2.1 秒），不是这 0.3 秒。
    assert "t0" in seen, "夹具没记到派活的时刻 ⇒ 这一条没有对象"
    assert seen["elapsed"] < LONG_WAIT * 0.5, (
        f"派完到第一个模型回合花了 {seen['elapsed']:.3f}s（child_return_wait_sec={LONG_WAIT}）"
        " —— 那一拍又在等子", seen)
    # 三、读数分得开：那一拍是"为了返场没等"，不是"等了 N 秒"。
    rets = _return_beats(spy)
    assert rets, ("派活之后没有任何一拍被记成返场", spy.beats)
    first = rets[0]
    assert first["wait_reason"] == "return", first
    assert first["waited_sec"] == 0.0, first
    assert first["slices"] == 0, ("返场那一拍之前还挂机睡过", first)
    assert len(first["running"]) == 2, first
    # 四、notes 里也是同一句话（"为了返场没等"），不是"等了 N 秒"。
    assert any("为了返场没等子" in str(n) for n in run.notes), (
        "这一拍的 notes 没说清「为了返场没等」", [n for n in run.notes if "返场" in str(n)])
    # 五、返场账真的记了（Q22 的那一笔），而且孩子最后都回来了。
    assert int(run.park.get("reentry_turns") or 0) >= 1, run.park
    rows = TQ._rows(state["st"], state["me"])
    assert all(str(r.get("status") or "") == "done" for r in rows), rows
    given = [str(x) for x in (run.park.get("return_given") or ())]
    assert sorted(given) == sorted(str(r.get("task_id")) for r in rows), (given, rows)


# ------------------------------------------------------------------ b. 孩子在窗口里回来


def test_a_child_that_comes_back_inside_the_window_still_earns_the_beat(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """判据 b：孩子在那等待窗口里回来 ⇒ 返场那一拍仍然发生、账仍然记。

    改前红：那一拍先等子，父代理一开口等、孩子就回来（夹具把释放挂在等待路径上，
    顺序是判据造的）⇒ `_children_round_trip` 取走结果并把句柄摘掉 ⇒ 之后的
    `_return_reading` 读 `owed_batch=False`，于是 `reentry_turns` / `return_given`
    一次都不记：返场这一件事在读数上被"手上有活（settled 非空）"吃掉了。
    """
    seen: dict[str, Any] = {}
    _arm_dispatch(monkeypatch, release_on_wait={})

    def on_call(index: int, prompt: str, state: dict[str, Any]) -> None:
        if index == 0:
            state["loop"].child_return_wait_sec = SETTLE_WAIT
            _arm_mailbox_spy(monkeypatch, state)
        if index == 1:
            # 改后那一拍没有等 ⇒ 孩子在它之后才回来（改前那一趟由上面的等待钩子放行）。
            seen["in_flight"] = TQ._running(state["st"], state["me"])
            state["backend"].release_all()

    state = TQ._scenario(tmp_path, monkeypatch,
                         replies=[TQ.MANY2, TQ.LOOK, TQ.LOOK, TQ.FINAL, TQ.FINAL],
                         on_call=on_call, release_after=3)
    run = state["run"]
    spy: _MailboxSpy = state["mailbox_spy"]

    assert run.stop_reason == "final", run.to_dict()
    # 一、返场那一拍仍然发生、账仍然记（孩子在这窗口里回来也不许被"手上有活"接走）。
    assert int(run.park.get("reentry_turns") or 0) >= 1, (
        "孩子在这一拍之前回来了，返场账一次都没记 —— 那一拍被「手上有活」吃掉了",
        run.park, spy.beats)
    rows = TQ._rows(state["st"], state["me"])
    given = [str(x) for x in (run.park.get("return_given") or ())]
    assert sorted(given) == sorted(str(r.get("task_id")) for r in rows), (given, rows)
    # 二、那一拍是在孩子还在跑的时候发生的（账记在"还在跑"的那一批上）。
    assert len(seen.get("in_flight") or []) == 2, seen
    # 三、读数里那一拍仍是"为了返场没等"（不是"等了 N 秒"）。
    rets = _return_beats(spy)
    assert rets and rets[0]["wait_reason"] == "return", (rets, spy.beats)
    # 四、孩子确实都在这一趟里回来了（不是靠收工门的退场结算）。
    assert all(str(r.get("status") or "") == "done" for r in rows), rows


# ------------------------------------------------------------------ c / d. 两条正控


def test_the_other_beats_still_wait_and_the_woke_beat_still_skips(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """正控 c 与 d：非返场拍照旧等；`woke` 那一拍仍然不调模型。

    两条共用一趟（同一套装夹具，两个读数各取各的；拆成两趟只是把同一条夹具跑两遍）：
    - c：返场那一拍之后、孩子还在跑、又没有唤醒的那一拍 ⇒ `wait_reason=="slice"`、
      `waited_sec>0`（`CHILD_RETURN_WAIT_SEC` 那笔正常成本一个字没取消）；
    - d：孩子回来时那一拍仍记成 `woke` 且 `skip_model=True`（p206 第 4 条不破）。
    """
    released: list[int] = []

    def hook(n: int, state: dict[str, Any]) -> None:
        if not released:
            released.append(n)
            state["backend"].release_all()

    def on_call(index: int, prompt: str, state: dict[str, Any]) -> None:
        if index == 0:
            state["loop"].child_return_wait_sec = LONG_WAIT
            _arm_mailbox_spy(monkeypatch, state)

    state = TQ._scenario(tmp_path, monkeypatch,
                         replies=[TQ.MANY2, TQ.LOOK, TQ.LOOK, TQ.FINAL, TQ.FINAL],
                         on_call=on_call, hook=hook, release_after=3, spy=True)
    run = state["run"]
    spy: _MailboxSpy = state["mailbox_spy"]
    beats = state["spy"].beats

    assert run.stop_reason == "final", run.to_dict()
    assert released, "夹具没有在挂机那一拍放行孩子 ⇒ 判据 d 没有对象"
    # c：返场那一拍之后的头一拍是非返场的，它照旧等（改前也等 —— 这一条守"不许整体取消"）。
    rets = _return_beats(spy)
    assert rets, spy.beats
    first = rets[0]
    at = [i for i, b in enumerate(spy.beats) if b is first][0]
    after = spy.beats[at + 1]
    # 那一拍不是返场拍：判据没给它回合（`return_owed` 为假），而 `wait.reason`
    # 是"等子那一小段"（`slice`）。
    assert after["return_owed"] is False, after
    assert after["wait_reason"] == "slice", (
        "非返场的那一拍没有等子（那一笔正常成本被一起取消了）", after, spy.beats)
    assert after["waited_sec"] >= LONG_WAIT * 0.5, after
    # d：`woke` 那一拍仍在，且仍不调模型。
    woke = [b for b in beats if b["decision"] == "woke"]
    assert int(run.park.get("woke_turns") or 0) >= 1, (run.park, beats)
    assert woke, ("这一趟没有 woke 那一拍 ⇒ 判据 d 没有对象", beats)
    assert all(b["skip"] for b in woke), [b for b in beats if b["decision"] == "woke"]


# ------------------------------------------------------------------ e. 反真空


def test_without_the_wait_skip_the_two_red_columns_come_back(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """判据 e：把"返场 ⇒ 不等"打桩掉 ⇒ a 与 b 的读数各自回到改前那个红。

    打桩的是那一处判据本身（`_should_wait_for_children` 换回改前的表达式
    `not consumed_wake`），别的一个字节都不动。两条红分别是：

    - a 那一档：`wait_reason` 变成 `slice`、`waited_sec` 与"派完到第一个模型回合"
      都 ≥ `child_return_wait_sec`；
    - b 那一档：孩子在那次等待里回来 ⇒ 返场账一次不记（`reentry_turns == 0`、
      `return_given` 空）。

    这一条同时是判据 f 的"改前"那一列（同一趟夹具的两个数，见报告里的两栏表）。
    """
    def old_wait(self_: Any, *, back: Mapping[str, Any], consumed_wake: bool) -> bool:
        """改前那一句：`wait=not bool(wakes.get("consumed"))`（返场判据不参与）。"""
        return not bool(consumed_wake)

    monkeypatch.setattr(AL.AgentLoop, "_should_wait_for_children", old_wait)

    # ---- a 那一档：孩子不在这段窗口里回来 ⇒ 等满 child_return_wait_sec 才问模型。
    seen_a: dict[str, Any] = {}
    _arm_dispatch(monkeypatch, stamp=seen_a)

    def on_call_a(index: int, prompt: str, state: dict[str, Any]) -> None:
        if index == 0:
            state["loop"].child_return_wait_sec = LONG_WAIT
            _arm_mailbox_spy(monkeypatch, state)
        if index == 1:
            seen_a["elapsed"] = time.monotonic() - float(seen_a["t0"])
            state["backend"].release_all()

    state_a = TQ._scenario(tmp_path, monkeypatch,
                           replies=[TQ.MANY2, TQ.LOOK, TQ.LOOK, TQ.FINAL, TQ.FINAL],
                           on_call=on_call_a, release_after=3)
    run_a = state_a["run"]
    spy_a: _MailboxSpy = state_a["mailbox_spy"]

    assert run_a.stop_reason == "final", run_a.to_dict()
    rets_a = _return_beats(spy_a)
    assert rets_a, ("打桩之后没有任何一拍被记成返场 ⇒ 这条反真空没有对象", spy_a.beats)
    waited_a = rets_a[0]["waited_sec"]
    assert rets_a[0]["wait_reason"] != "return", (
        "把判据打桩掉之后仍然没等 —— 说明「不等」不是那一处给的", rets_a[0])
    assert waited_a >= LONG_WAIT * 0.9, (
        f"打桩之后那一拍只等了 {waited_a:.3f}s（应当 ≥ {LONG_WAIT}）", rets_a[0])
    assert seen_a["elapsed"] >= LONG_WAIT * 0.9, (
        f"打桩之后派完到第一个模型回合只花了 {seen_a['elapsed']:.3f}s", seen_a)
    assert int(run_a.park.get("reentry_turns") or 0) >= 1, (
        "这一档的孩子不在窗口里回来 ⇒ 返场账照旧该记（这一条不是 b 的对象）", run_a.park)

    # ---- b 那一档：孩子在那次等待里回来 ⇒ 返场账一次都不记（改前的那个红）。
    other = tmp_path / "b"
    other.mkdir()
    _arm_dispatch(monkeypatch, release_on_wait={})

    def on_call_b(index: int, prompt: str, state: dict[str, Any]) -> None:
        if index == 0:
            state["loop"].child_return_wait_sec = SETTLE_WAIT

    state_b = TQ._scenario(other, monkeypatch,
                           replies=[TQ.MANY2, TQ.LOOK, TQ.LOOK, TQ.FINAL, TQ.FINAL],
                           on_call=on_call_b, release_after=3)
    run_b = state_b["run"]
    assert run_b.stop_reason == "final", run_b.to_dict()
    assert int(run_b.park.get("reentry_turns") or 0) == 0, (
        "打桩之后孩子在那次等待里回来，返场账却还记了 —— 这一条没有量到「被吃掉」",
        run_b.park)
    assert not run_b.park.get("return_given"), run_b.park

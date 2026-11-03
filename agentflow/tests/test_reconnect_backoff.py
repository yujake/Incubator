# -*- coding: utf-8 -*-
"""判据：连接类失败的等待闸（从 DSH 的 `ClientBridgeLifecycle` 逐条移植）。

## 这一组守什么

`agent_loop` 改前在连接类失败（`judge_no_reply:<kind>`）之后立刻进入下一轮：
三次连击之间没有任何等待，网络没回来就照样把同一句话再发一遍。业主 88 那一趟的
读数是 186 步、两次 `model_unreachable`、$0.16，其中连接失败那几拍就是空转。

新行为（`reconnect.BackoffGate`，从 DSH 的 `ClientBridgeLifecycle` 移植）：
失败 ⇒ 按 cap = min(max, base * 2 ** attempt) 在 [cap/2, cap] 里随机取一段等待
⇒ 等完重试同一轮。等待期间不推进步号、不产生模型调用（于是不计入预算）。

五条判据（与施工单 a-e 一一对应）：

a 连续 3 次连接失败 ⇒ 事件流里 2 条 `kind=reconnect`（第三次失败之前先等）；
b 成功一次 ⇒ `attempt` 归零（下一次失败从 base 起算）；
c 第 k 次等待 ∈ [cap/2, cap]，且 cap 不超过 max（rng 注入 ⇒ 确定性）；
d 反真空：把闸摘掉（`reconnect=False`）⇒ 同一场景回到"连续失败无等待"；
e 总等待上限：`waited_total` 超限 ⇒ `stop_reason=model_unreachable`，停机语含
  "等过 N 秒"（区别于"根本没等"）。

零模型：替身网关照剧本把前 N 次折成 `ok=False` + `error_kind=network`，价格 0。
"""
from __future__ import annotations

import json
import pathlib
from typing import Any

import pytest

from agentflow import reconnect as RC
from agentflow import sessions as SS
from agentflow.agent_loop import run_role
from agentflow.conductor import Conductor
from agentflow.llmseam import LlmSeam
from agentflow.store import Store
from agentflow.tools import build_registry

SID = "test-run"
FINAL_TEXT = "等回来了"


class _NetworkThenReply:
    """替身模型：前 N 次返回 `ok=False` + `error_kind=network`，之后给一条合法 final。

    为什么不用抛异常的替身：真机那条路不抛 —— `modelgw.ModelGateway.complete`
    把 DNS 失败折成一次失败的结局（`error_kind="network"`），缝拿到的是 `ok=False`
    的回复。用抛异常的替身测的是另一条路（`judge._problem_of`），测不到这一格。
    """

    spec = type("Spec", (), {"model": "scripted", "api_key": "fake"})()

    def __init__(self, *, failures: int, reply: str = "") -> None:
        self.failures = int(failures)
        self.reply = reply or json.dumps({"final": FINAL_TEXT, "evidence": []},
                                         ensure_ascii=False)
        self.calls = 0

    def complete(self, prompt: str, *, scope: str = "", system: str | None = None,
                 **kw: Any) -> Any:
        self.calls += 1
        if self.calls <= self.failures:
            return type("Reply", (), {
                "ok": False, "text": "", "tokens_in": 0, "tokens_out": 0,
                "error_kind": "network",
                "error_detail": "gaierror: [Errno 11002] getaddrinfo failed"})()

        return type("Reply", (), {
            "ok": True, "text": self.reply, "tokens_in": 10, "tokens_out": 10,
            "error_kind": "", "error_detail": ""})()


def _run(tmp_path: pathlib.Path, gateway: Any, *, reconnect: Any) -> tuple[Any, pathlib.Path]:
    """跑一趟 M（零模型），把 `reconnect` 原样交给 `run_role`。"""
    root = tmp_path / "ws"
    st = Store(root)
    st.init()
    cond = Conductor(st, policy=None)
    built = build_registry(store=st, conductor=cond)
    seam = LlmSeam(role="M", session_root=root, gateway=gateway, price=(0.0, 0.0),
                   sid=SID, from_env=False)
    run = run_role("M", "等网络回来", store=st, registry=built.registry, conductor=cond,
                   seam=seam, workspace_root=str(root), sid=SID, reconnect=reconnect)
    return run, root


def _events(root: pathlib.Path) -> list[dict]:
    events, problems = SS.read_session(root, sid=SID)
    assert not problems, problems
    return events


def _reconnects(root: pathlib.Path) -> list[dict]:
    return [e for e in _events(root) if e.get("kind") == "reconnect"]


# ============================================================ c：退避单调有界

def test_each_wait_is_between_half_and_full_cap_and_cap_is_capped():
    """c：第 k 次等待 ∈ [cap/2, cap]，cap = min(max, base * 2**k) 且不超过 max。

    rng 注入成 0.5 ⇒ 等待恰好是 cap * 0.75（确定值，不用睡眠）。
    """
    gate = RC.BackoffGate(base_delay_sec=1.0, max_delay_sec=8.0,
                          total_wait_sec=100.0, rng=lambda: 0.5)
    previous_cap = 0.0
    for k in range(8):
        cap = min(8.0, 1.0 * 2 ** k)
        assert cap >= previous_cap, f"第 {k} 次的 cap 比上一次小：{cap} < {previous_cap}"
        assert cap <= 8.0, f"第 {k} 次的 cap 超过 max：{cap}"
        wait = gate.schedule()
        assert wait is not None
        assert cap / 2.0 <= wait <= cap, f"第 {k} 次等待 {wait} 不在 [{cap / 2}, {cap}]"
        gate.settle()
        previous_cap = cap
    # 抖动两端各来一次：下界与上界都落在区间内（端点是闭区间）。
    low = RC.BackoffGate(base_delay_sec=1.0, max_delay_sec=8.0, rng=lambda: 0.0)
    assert low.schedule() == pytest.approx(0.5)
    high = RC.BackoffGate(base_delay_sec=1.0, max_delay_sec=8.0, rng=lambda: 1.0)
    assert high.schedule() == pytest.approx(1.0)


# ============================================================ 单飞与关闭

def test_single_flight_does_not_stack_a_second_timer():
    """单飞：已有待触发的一次就返回 None，且不把 attempt 再加一次。"""
    gate = RC.BackoffGate(base_delay_sec=1.0, max_delay_sec=8.0, rng=lambda: 0.5)
    first = gate.schedule()
    assert first is not None
    assert gate.attempt == 1
    assert gate.schedule() is None, "已有待触发的一次，却又排了一次（叠了）"
    assert gate.attempt == 1, "被单飞挡掉的那一次不该推高 attempt"
    gate.settle()
    assert gate.schedule() is not None, "上一次结清之后必须能再排"


def test_a_closed_gate_never_schedules_again():
    """关闭之后不再排下一次（DSH：prevents reconnection after disposal）。"""
    gate = RC.BackoffGate(base_delay_sec=1.0, max_delay_sec=8.0, rng=lambda: 0.5)
    assert gate.schedule() is not None
    gate.close()
    assert gate.closed is True
    assert gate.pending is None
    assert gate.schedule() is None


# ============================================================ b：成功即归零

def test_a_success_after_three_failures_restarts_from_base():
    """b：第 4 次成功 ⇒ attempt 归零；下一次失败从 base（而不是翻倍的 cap）起算。

    三次失败各排一次等待 ⇒ attempt=3；`connected()` 之后下一次等待回到 base 那一档。
    """
    gate = RC.BackoffGate(base_delay_sec=1.0, max_delay_sec=60.0,
                          total_wait_sec=300.0, rng=lambda: 0.0)
    waits = []
    for _ in range(3):
        wait = gate.schedule()
        assert wait is not None
        gate.settle()
        waits.append(wait)
    assert waits == pytest.approx([0.5, 1.0, 2.0]), waits
    assert gate.attempt == 3 and gate.attempts == 3

    gate.connected()
    assert gate.attempt == 0, "成功一次之后 attempt 没归零"
    next_wait = gate.schedule()
    assert next_wait == pytest.approx(0.5), "成功之后的失败没有从 base 起算"


# ============================================================ 配置：settings / env

def test_config_defaults_are_five_sixty_and_three_hundred():
    """配置缺省：base=5 / max=60 / total=300（不是硬编码在业务代码里）。"""
    cfg = RC.ReconnectConfig.from_settings(env={})
    assert cfg.base_delay_sec == pytest.approx(5.0)
    assert cfg.max_delay_sec == pytest.approx(60.0)
    assert cfg.total_wait_sec == pytest.approx(300.0)


def test_env_and_settings_ladder(tmp_path: pathlib.Path):
    """环境变量压过设置文件（与 `settings.env_or_setting` 同一条梯子）。"""
    p = tmp_path / "s.json"
    p.write_text(json.dumps({"reconnect": {"base_sec": "2", "max_sec": "7",
                                           "total_sec": "9"}}), encoding="utf-8")
    from_file = RC.ReconnectConfig.from_settings(p, env={})
    assert (from_file.base_delay_sec, from_file.max_delay_sec,
            from_file.total_wait_sec) == (2.0, 7.0, 9.0)
    over = RC.ReconnectConfig.from_settings(p, env={RC.ENV_BASE_SEC: "3"})
    assert over.base_delay_sec == pytest.approx(3.0), "环境变量没有压过设置文件"
    assert over.max_delay_sec == pytest.approx(7.0)


# ============================================================ a：三次失败两次等待

def test_three_connection_failures_produce_two_reconnects(tmp_path: pathlib.Path):
    """a：连续 3 次连接失败 ⇒ 事件流里 2 条 reconnect，而不是 3 次背靠背的调用。

    同一轮里重试 ⇒ 3 次失败落在同一个步号上；第三次是上限那一次，交给外层停机。
    """
    gateway = _NetworkThenReply(failures=3)
    gate = RC.BackoffGate(base_delay_sec=0.01, max_delay_sec=0.02,
                          total_wait_sec=60.0, rng=lambda: 0.5)
    run, root = _run(tmp_path, gateway, reconnect=gate)

    events = _reconnects(root)
    assert [e.get("attempt") for e in events] == [1, 2], events
    assert gateway.calls == 3, f"第三次失败之前应当只调了 3 次，实际 {gateway.calls}"
    assert run.stop_reason == "model_unreachable", run.to_dict()
    assert run.no_reply == 3, run.to_dict()
    invalid = [s for s in run.steps if s.shape == "invalid"]
    assert len(invalid) == 3 and {s.problem for s in invalid} == {"judge_no_reply:network"}
    assert {s.step for s in invalid} == {0}, "重试必须落在同一轮（步号不许被等待推着走）"
    for event in events:
        assert event.get("step") == 0, event
        assert 0.0 < float(event.get("wait_sec") or 0.0) <= 0.02, event
        assert float(event.get("waited_total") or 0.0) > 0.0, event
    assert "等过" in run.final, run.final
    assert gate.attempts == 2, gate.attempts


# ============================================================ d：反真空（摘掉闸）

def test_without_the_gate_the_old_no_wait_behaviour_returns(tmp_path: pathlib.Path):
    """d：把闸摘掉（`reconnect=False`）⇒ 同一场景回到"连续失败无等待"。

    反真空那一半：a 的绿不能靠"凡失败都写一条 reconnect"来满足 —— 这里一条都不许有。
    """
    gateway = _NetworkThenReply(failures=3)
    run, root = _run(tmp_path, gateway, reconnect=False)

    assert _reconnects(root) == [], "闸被摘掉之后还写了 reconnect 事件"
    assert gateway.calls == 3, gateway.calls
    assert run.stop_reason == "model_unreachable", run.to_dict()
    assert run.no_reply == 3, run.to_dict()
    assert "等过" not in run.final, run.final


# ============================================================ e：总等待上限

def test_total_wait_cap_stops_with_how_long_it_waited(tmp_path: pathlib.Path):
    """e：总等待超限 ⇒ model_unreachable，且停机语说清"等过 N 秒还是没回来"。

    base=0.2 / max=0.2 / total=0.15，rng=0 ⇒ 每次等待 0.1 秒：
    第一次等完（waited=0.1），第二次再等就会越过 0.15 ⇒ 不再睡、直接停。
    """
    gateway = _NetworkThenReply(failures=99)
    gate = RC.BackoffGate(base_delay_sec=0.2, max_delay_sec=0.2,
                          total_wait_sec=0.15, rng=lambda: 0.0)
    run, root = _run(tmp_path, gateway, reconnect=gate)

    assert run.stop_reason == "model_unreachable", run.to_dict()
    assert "等过 0.1 秒" in run.final, run.final
    assert "还是没回来" in run.final, run.final
    assert gateway.calls == 2, f"总等待到顶就该停，实际调了 {gateway.calls} 次"
    events = _reconnects(root)
    assert len(events) == 1, events
    assert events[0].get("attempt") == 1, events
    assert gate.waited_total == pytest.approx(0.1, abs=1e-6)
    assert run.no_reply == 2, run.to_dict()

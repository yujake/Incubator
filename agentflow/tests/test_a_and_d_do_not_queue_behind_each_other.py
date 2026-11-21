# -*- coding: utf-8 -*-
"""WAVEFIX：A 与 D 的写集在 `search_requests` 相交，不该让三路 D 排队 63 分钟。

## 现场（`projects/lp-ball-14`，逐字复算在 `agentflow/temp/wavefix/`）

step 2 一次 `summon_many` 派 4 个（A + 三路 D），框架返回 `waves=[1,3]`、
`concurrent_peak=1`：A 的写集 `{literature, search_requests}` 与 D 的
`{research_questions, search_requests}` 的表级交集非空 ⇒ 必须分波。后果链：

1. A 跑了 63 分钟（00:27→01:31:26），三路 D 排队 44 分钟；
2. M 在 01:12:07 把 `status=pending` 读成「没落地」，用同一批 instance 名重派；
3. 排队那批在 01:31:26 自动开跑 ⇒ 同名实例双开（重叠 33s / 113s / 271s）；
4. 重复花 $0.1350、experiments 10/22 被 voided。

## 判据

| 条 | 判据 | 改前红在哪 |
|---|---|---|
| a | 那四个目标（A + 3 个 D，显式实例 2d/3d/lit-bridge）同波 | 改前 `waves=[1,3]` |
| b | 正控（冲突检测没被关掉）：共享表没登记行面的角色对仍分波；共享表里只要有一张没登记，整对仍分波 | 改后仍必须是 `[1,1]` |
| c | 重派一个还在排队的同名实例 ⇒ 受控拒（`dispatch_names_an_active_instance`），且台账里那个实例始终只有一行 | 改前第二次派活照样落行 ⇒ 双开 |
| d | 反真空：把行面判据与同名判据各打桩回改前 ⇒ a 与 c 必红 | 证明 a / c 量的就是这两步 |

## 判据 a 的夹具为什么不写成「D 只读 search_requests」

任务单里给的候选根因是「D 只读 search_requests，所以当前分波是误报冲突」。
取证结论相反：D 的动作面真的建请求行（`research.submit_gap` 与 `adjudicate`
的矛盾轮次都 `tx.upsert("search_requests", …)`），真机 r-000010/11/12 的
`submitted_by=agent-D` 是盘上的读数。所以判据 a 不能靠「把写集改小」变绿 ——
它先断言表级交集仍然非空（否则这条判据可以被一次 `WRITE_SETS` 编辑骗过），
再断言那个交集整张落在行面上。
"""
from __future__ import annotations

import pathlib
import threading
import time
from typing import Any, Mapping

import pytest

from agentflow import agent_loop as AL
from agentflow import capabilities as C
from agentflow import policy as P
from agentflow import rowscope as RS
from agentflow import scheduler as SC
from agentflow.agent_loop import AgentLoop
from agentflow.conductor import Conductor
from agentflow.llmseam import LlmSeam
from agentflow.policy import Policy
from agentflow.store import Store
from agentflow.tools import build_registry

SID = "wavefix"
#: 父 = 主控 M（现场那次派活就是 M 发的；出边 M→A / M→B 都在 `ALLOWED_EDGES` 里）。
ROLE = "M"
TASK = "WAVEFIX 判据夹具：一道 63 分钟的活把三条研究方向压住"

#: 现场那四个 target（`m_run.json:steps[2].payload.targets` 的角色与实例名逐字）。
INCIDENT = [
    {"role": "A", "task": "补文献：cube slicing", "instance": "a-lit"},
    {"role": "D", "task": "方向 2d", "instance": "2d"},
    {"role": "D", "task": "方向 3d", "instance": "3d"},
    {"role": "D", "task": "方向 lit-bridge", "instance": "lit-bridge"},
]


class _BlockingBackend:
    """派出去就卡住的后端：让"前一波没落定"这件事由判据自己控制。"""

    name = "blocks"

    def __init__(self) -> None:
        self.gate = threading.Event()
        self._lock = threading.Lock()
        self.calls: list[str] = []

    def known_roles(self) -> list[str]:
        return ["A", "B", "D"]

    def resolve(self, role: str, instance: str = "") -> Any:  # pragma: no cover - 接口需要
        return self

    def call(self, role: str, action: str, params: Mapping[str, Any], *, token: Any,
             instance: str = "", task_id: str = "") -> Any:
        with self._lock:
            self.calls.append(str(task_id))
        self.gate.wait(timeout=60.0)
        return {"outcome": "ok", "detail": f"{role} 的活跑完了",
                "payload": {"final": f"{role}#{instance or '-'} 的结论"}}

    def release(self) -> None:
        self.gate.set()


def _env(tmp_path: pathlib.Path) -> tuple[pathlib.Path, Store, Conductor, _BlockingBackend]:
    ws = tmp_path / "ws"
    st = Store(ws)
    st.init()
    backend = _BlockingBackend()
    cond = Conductor(st, policy=Policy(), backend=backend)
    return ws, st, cond, backend


def _loop(ws: pathlib.Path, st: Store, cond: Conductor, *, parent: str) -> AgentLoop:
    """一条真的 `AgentLoop`（只把"等孩子"压到毫秒：这一份判的是派活判据，不是等待）。"""
    registry = build_registry(store=st, conductor=cond, workspace_root=ws).registry
    loop = AgentLoop(role=ROLE, session_root=ws, registry=registry, conductor=cond,
                     seam=LlmSeam(role=ROLE, session_root=ws, gateway=_NoModel(),
                                  price=(0.0, 0.0), sid=SID),
                     store=st, sid=SID, max_steps=4, workspace_root=str(ws))
    loop.my_task_id = parent
    loop.child_step_wait_sec = 0.01
    return loop


class _NoModel:
    """这一份判据不该问模型：真问到了就当场炸（那不是"跑了"，是夹具走错了路）。"""

    spec = type("Spec", (), {"model": "stub", "api_key": "x"})()

    def complete(self, prompt: str, **kw: Any) -> Any:  # pragma: no cover - 不该被调用
        raise AssertionError("WAVEFIX 的判据不该问模型：派活那一步是形状层直接分派的")


def _kids(st: Store, parent: str) -> list[dict]:
    return [dict(r) for r in st.rows("tasks")
            if str(r.get("parent_task_id") or "") == parent
            and not str(r.get("kind") or "")]


def _wait(predicate: Any, *, timeout: float = 20.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


def _incident_calls() -> list[SC.TaskCall]:
    return [SC.TaskCall(role=t["role"], action="", params={"task": t["task"]},
                        instance=t["instance"])
            for t in INCIDENT]


# ============================================================ a：四个目标同波


def test_a_the_incident_four_share_one_wave_on_the_row_face(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """判据 a：现场那四个目标必须落在同一波（改前 `[1,3]`）。

    两半一起断，缺一半这条判据就可以被一次编辑骗过：
    ① 表级交集仍在（不许靠改小 `WRITE_SETS` 变绿）；
    ② 那个交集整张登记了行面 ⇒ 表级相交不等于行级相交。
    """
    calls = _incident_calls()
    shared = P._write_set("A") & P._write_set("D")
    assert shared == frozenset({"search_requests"}), (
        f"这条判据的对象变了：A 与 D 的共享写集是 {sorted(shared)}")
    assert RS.row_disjoint("search_requests", "A")
    assert RS.row_disjoint("search_requests", "D")
    assert P.estimate_write_conflict("A", "D") is False

    waves = P.waves_of(calls, limit=None)
    assert [len(w) for w in waves] == [4], f"四个目标必须同波（实际 {waves}）"
    assert waves == [[0, 1, 2, 3]], waves

    # 任务单给的那一档（「D 只读 search_requests」）也顺带钉住：把 D 的写集临时改成
    # 不含这张表 ⇒ 同样同波。现场不是这一档（取证见模块头），但两种前提都必须是同波，
    # 判据才不会因为写集声明的一次变动而反过来变成「必须分波」。
    monkeypatch.setitem(C.WRITE_SETS, "D", frozenset({"research_questions"}))
    assert [len(w) for w in P.waves_of(calls, limit=None)] == [4]


# ============================================================ b：负控（冲突没被关掉）


def test_b_a_table_without_the_row_face_still_splits(monkeypatch: pytest.MonkeyPatch) -> None:
    """判据 b：没登记行面的共享表照旧分波（正控：冲突检测一个字没松）。

    A 与 B 的共享写集是 `literature` —— 那张表没有"各写各的行"的可判定结构
    （B 的按路径占用归 `ROW_MUTEX_ACTIONS`，不是这张登记表）⇒ 必须分波。
    """
    calls = [SC.TaskCall("A", "", {"task": "补文献"}, instance="a1"),
             SC.TaskCall("B", "", {"task": "收编"}, instance="b1")]
    assert P._write_set("A") & P._write_set("B") == frozenset({"literature"})
    assert [len(w) for w in P.waves_of(calls, limit=None)] == [1, 1]

    # 共享表里只要有一张没登记双方，整对仍必须分波：Z1 只写 search_requests，
    # 而它在 `ROW_DISJOINT_WRITERS` 里没有名字（A 有）⇒ 交集不是"整张已登记"。
    monkeypatch.setitem(C.WRITE_SETS, "Z1", frozenset({"search_requests"}))
    assert RS.row_disjoint("search_requests", "A") is True
    assert RS.row_disjoint("search_requests", "Z1") is False
    pair = [SC.TaskCall("A", "", {"task": "补文献"}, instance="a1"),
            SC.TaskCall("Z1", "", {"task": "点名要查"}, instance="z1")]
    assert P.estimate_write_conflict("A", "Z1") is True
    assert [len(w) for w in P.waves_of(pair, limit=None)] == [1, 1]


# ============================================================ c：排队项的同名重派


def test_c_redispatched_queued_instance_is_refused_not_double_opened(
        tmp_path: pathlib.Path) -> None:
    """判据 c：排队项还在排队时，同名实例的第二次派活必须被受控拒。

    夹具：A 与 B 都写 `literature` ⇒ A 先跑（卡住）、B 排队。第一层断言的是
    "排队项自己交出它挡在谁后面"（`queued=true` / `queued_behind` / `expected_start`）；
    第二层断言的是"重派被拒、台账里始终只有一行"（双开的那条路被堵死）。
    """
    ws, st, cond, backend = _env(tmp_path)
    parent = cond.open_top_level_run(ROLE, TASK)
    loop = _loop(ws, st, cond, parent=parent)

    first = loop._do_summon_many({"targets": [
        {"role": "A", "task": "长活：补文献", "instance": "a-long"},
        {"role": "B", "task": "排队活：收编", "instance": "b-quote"}]})
    assert first["ok"] is True, first
    rows = first["results"]
    a_tid = str(rows[0].get("task_id") or "")
    assert a_tid and rows[0]["status"] == "running", rows[0]
    assert rows[1]["queued"] is True and rows[1]["status"] == "pending", rows[1]
    assert rows[1]["queued_behind"] == [a_tid], rows[1]
    assert a_tid in rows[1]["expected_start"], rows[1]
    assert first["queued"] == [{"role": "B", "instance": "b-quote",
                                "queued_behind": [a_tid],
                                "expected_start": rows[1]["expected_start"]}], first

    second = loop._do_summon_many({"targets": [
        {"role": "B", "task": "又派一次同一件活", "instance": "b-quote"}]})
    assert second["ok"] is False, second
    assert second["refused"] == "dispatch_names_an_active_instance", second
    assert second["violations"][0]["state"] == "queued", second["violations"]
    assert second["violations"][0]["waiting_on"] == [a_tid], second["violations"]
    assert a_tid in second["detail"], second["detail"]
    # "排队"与"没落地"必须分得开：拒信要明说它是排队，不是没派出去。
    assert "不是没落地" in second["detail"], second["detail"]

    # 被拒之后台账里一行都不许多：A 一行，B 连行都还没有（它在排队）。
    before = _kids(st, parent)
    assert len(before) == 1 and before[0]["role"] == "A", before

    backend.release()
    assert _wait(lambda: any(str(r.get("role") or "") == "B" for r in _kids(st, parent))), (
        loop._child_handles, _kids(st, parent))
    assert _wait(lambda: all(str(r.get("status") or "") == "done"
                             for r in _kids(st, parent))), _kids(st, parent)
    after = _kids(st, parent)
    b_rows = [r for r in after if str(r.get("role") or "") == "B"]
    assert len(b_rows) == 1, f"B 被派了 {len(b_rows)} 次 ⇒ 双开：{b_rows}"
    assert str(b_rows[0].get("instance") or "") == "b-quote", b_rows[0]
    assert b_rows[0]["status"] == "done" and b_rows[0]["outcome"] == "ok", b_rows[0]


# ============================================================ d：反真空


def test_d_stubbing_either_half_reddens_its_criterion(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """判据 d：把两处修法各打桩回改前 ⇒ a 与 c 必红。

    打桩用的是"改前那份读数"（行面判据恒 False / 同名判据恒空），不是抛异常：
    抛异常会让"判据坏了"与"这一步没跑"混在一起。
    """
    # ① 行面打桩 ⇒ a 的四个目标重新变成 [1,3]（= 现场读数）。
    monkeypatch.setattr(RS, "row_disjoint", lambda table, role: False)
    assert [len(w) for w in P.waves_of(_incident_calls(), limit=None)] == [1, 3], (
        "行面打桩之后仍然同波 ⇒ 判据 a 量的不是行面这一层")
    monkeypatch.undo()

    # ② 同名判据打桩 ⇒ 重派照常落行（双开回来了）。
    monkeypatch.setattr(AL.AgentLoop, "_instance_name_clash",
                        lambda self, calls, named: [])
    ws, st, cond, backend = _env(tmp_path)
    parent = cond.open_top_level_run(ROLE, TASK)
    loop = _loop(ws, st, cond, parent=parent)
    first = loop._do_summon_many({"targets": [
        {"role": "A", "task": "长活：补文献", "instance": "a-long"},
        {"role": "B", "task": "排队活：收编", "instance": "b-quote"}]})
    assert first["ok"] is True and first["results"][1]["queued"] is True, first
    second = loop._do_summon_many({"targets": [
        {"role": "B", "task": "又派一次同一件活", "instance": "b-quote"}]})
    assert second["ok"] is True, (
        "同名判据打桩之后第二次派活仍被拒 ⇒ 判据 c 量的不是这一处")
    # 第二笔立刻落了一行（第二笔只有一项，自己就是第一波）—— 双开就是这一刻成立的。
    live = [r for r in _kids(st, parent) if str(r.get("role") or "") == "B"]
    assert len(live) == 1 and live[0]["status"] == "running", live

    backend.release()
    assert _wait(lambda: len([r for r in _kids(st, parent)
                              if str(r.get("role") or "") == "B"]) == 2), _kids(st, parent)
    all_b = [r for r in _kids(st, parent) if str(r.get("role") or "") == "B"]
    assert len(all_b) == 2, f"打桩之后应当看到两条同名实例（双开）：{all_b}"
    assert {str(r.get("instance") or "") for r in all_b} == {"b-quote"}, all_b

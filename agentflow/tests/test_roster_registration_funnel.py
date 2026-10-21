"""名册登记的唯一漏斗：子行建立之后必须登记，且三态不许折平（2026-10-21 真机缺陷）。

## 事故

`projects/p3-verify` 那一趟：`tasks` 有 5 个带父的代理行，而 `out/roster/` **一个文件都没有**。
三处 `roster_add` 调用点里，conductor 那份要 `self.secretary`，而真机上 conductor 没有秘书
⇒ 整条路静默不登记。现有的 22 条名册判据**全绿**，因为它们都没问"盘上那个文件在不在"。

## 这一条钉四件事（全部用小工作区/假缝，不发模型调用）

1. **漏斗正控**：`Conductor._roster_register_row` 对一条带父的子行 → 调 `roster_sink.roster_add`
   一次，参数 `owner/role/task_id` 与行里一致；
2. **顶趟不登记**：没有 `parent_task_id` 的行（顶趟）不调 sink（名册不是"所有人的花名册"）；
3. **三态（没 sink）**：`roster_sink is None` ⇒ **不许抛**，且 `_roster_problems` 里出现"没有名册写入口"；
4. **接上 sink**：`AgentLoop._bind_roster_sink` 幂等，且当 conductor/secretary 缺失时什么都不做。
"""

from __future__ import annotations

import pathlib
import sys

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


class _FakeSink:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.problem = ""

    def roster_add(self, **kwargs):
        self.calls.append(dict(kwargs))
        return {"problem": self.problem}


def _conductor_with_sink(sink):
    from agentflow import conductor as C

    cond = C.Conductor.__new__(C.Conductor)      # 不跑 __init__（它要 store/backend）
    cond.roster_sink = sink
    cond._roster_problems = []
    return cond


def test_a_child_row_is_registered_exactly_once() -> None:
    sink = _FakeSink()
    cond = _conductor_with_sink(sink)
    row = {"task_id": "t-000002", "role": "A", "parent_task_id": "t-000001",
           "brief": "查文献", "task": "查 Krichever-Novikov"}
    cond._roster_register_row(row)
    assert len(sink.calls) == 1, sink.calls
    call = sink.calls[0]
    assert (call["owner"], call["role"], call["task_id"]) == ("t-000001", "A", "t-000002")
    assert cond._roster_problems == []


def test_a_top_level_row_is_not_registered() -> None:
    sink = _FakeSink()
    cond = _conductor_with_sink(sink)
    cond._roster_register_row({"task_id": "t-000001", "role": "M", "parent_task_id": ""})
    assert sink.calls == [], "顶趟不属于任何人的名册"
    assert cond._roster_problems == [], "顶趟不是缺陷，不该留 problem"


def test_no_sink_is_a_problem_not_a_silent_skip() -> None:
    cond = _conductor_with_sink(None)
    cond._roster_register_row({"task_id": "t-000003", "role": "E", "parent_task_id": "t-000001"})
    assert any("没有名册写入口" in p for p in cond._roster_problems), cond._roster_problems


def test_a_refusal_from_the_sink_is_recorded() -> None:
    sink = _FakeSink()
    sink.problem = "没给一句任务简介"
    cond = _conductor_with_sink(sink)
    cond._roster_register_row({"task_id": "t-000004", "role": "D", "parent_task_id": "t-000001"})
    assert any("没给一句任务简介" in p for p in cond._roster_problems), cond._roster_problems


def test_bind_sink_is_idempotent_and_tolerates_missing_parts() -> None:
    from agentflow import agent_loop as L

    class _Loop:
        pass

    loop = _Loop()
    L.AgentLoop._bind_roster_sink(loop)          # 两个属性都没有 ⇒ 不抛
    loop.conductor = _conductor_with_sink(None)
    loop.secretary = object()
    L.AgentLoop._bind_roster_sink(loop)
    first = loop.conductor.roster_sink
    L.AgentLoop._bind_roster_sink(loop)
    assert loop.conductor.roster_sink is first, "重复绑定不该换人"

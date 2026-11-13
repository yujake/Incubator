# -*- coding: utf-8 -*-
"""F 的 plan 级放弃口：`attack.abandon_plan`（业主 2026-11-13 裁定 Q2）。

业主原话（逐字）：

> 「我们依旧要说F应该有新的放弃理由为不再需要。」

## 裁定（Q2，逐条落地）

- **谁有权**：F 自己（plan 归 F）—— 动作在 `specs/f.py` 的动作表里，工具只登记给
  `_WRITE_ROLES = ("F",)`；D 没有这个动作、也没有 `attack_plans` 的写集。
- **词表**：只加「不再需要」一档（plan 级没有"失败/冲突"的对应物，不许自己编）。
- **落点**：`attack_plans.history` 一行（**不加列、不做 schema 迁移**），`status→abandoned`。
- **已终态不许再放弃**（幂等/受控拒）。

## 判据

| 判据 | 它要证明的事 | 改前红在哪 |
|---|---|---|
| a | 放弃成功：status=abandoned、history 那行含「不再需要」、plan_id 不变 | 改前没有这个动作（`abandon_plan` 不存在） |
| b | 四档终态各拒一次（受控码 `plan_already_terminal`），行一个字节不改 | 同上 |
| c | 词表外的理由受控拒（`plan_abandon_reason_not_allowed`），行不改 | 同上 |
| d | 非 F 无权重：D 的动作表 / D 的工具面都没有它；工具 roles 逐字是 `("F",)` | 同上 |
| e | 反真空：把词表打桩成含"失败" ⇒ c 必须变绿（证明 c 的红来自词表） | —— |
"""
from __future__ import annotations

import pathlib
import sys

import pytest

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agentflow import agent_f as AF
from agentflow import specs
from agentflow.agent_f import abandon_plan as AP
from agentflow.store import Store
from agentflow.tools import build_registry
from agentflow.tools import attack_tools as AT

BUDGET = {"max_rounds": 3, "max_parallel_subgoals": 2,
          "max_persist_attempts": 2, "max_depth": 2}
REASON = "不再需要"


def _ws(path: pathlib.Path) -> Store:
    st = Store(path / "ws")
    st.init()
    return st


def _f(store: Store) -> AF.AgentF:
    return AF.AgentF(store, config={"workspace_root": store.root})


def _plan(store: Store, *, key: str = "PK-1", status: str = "open") -> str:
    with store.tx("attack_plans", actor="test") as tx:
        pid = tx.alloc_id("plan")
        tx.upsert("attack_plans", {
            "plan_id": pid, "problem": "难题", "problem_key": key,
            "status": status, "rounds": 0, "budget": dict(BUDGET),
            "subgoals": [], "history": [],
            "best_partial": ("停下来时的最好部分结果" if status == "stalled" else ""),
            "created_by": "agent-F",
        })
    return pid


def _row(store: Store, pid: str) -> dict:
    return next(dict(r) for r in store.rows("attack_plans")
                if str(r.get("plan_id") or "") == pid)


# ============================================================ a：放弃成功
def test_a_abandoning_a_plan_writes_the_four_words_into_history(
        tmp_path: pathlib.Path) -> None:
    """a 判据：status→abandoned ＋ history 末行含「不再需要」，plan_id 不变。

    改前红：改前 `AgentF` 上没有 `abandon_plan`（这条会以 AttributeError 失败），
    计划台账从来只有 `open/attacking/progress/…`，没有任何一行是 `abandoned`。
    """
    store = _ws(tmp_path)
    f = _f(store)
    pid = _plan(store)
    before = _row(store, pid)
    assert before["status"] == "open" and before["history"] == []

    out = f.abandon_plan(pid, reason=REASON)

    assert out.get("ok") is True, out
    assert out.get("plan_id") == pid and out.get("status") == "abandoned", out
    assert out.get("abandoned") is True and out.get("reason") == REASON, out
    assert out.get("kind") == "" and out.get("refusal_reason") == "", out
    row = _row(store, pid)
    assert row["status"] == "abandoned", row
    assert row["plan_id"] == pid, row
    hist = list(row.get("history") or [])
    assert len(hist) == 1, hist
    assert hist[0]["action"] == "abandon" and hist[0]["outcome"] == "abandoned", hist
    assert REASON in hist[0]["detail"], hist  # 业主点名的四个字逐字在
    assert row.get("updated_at"), row


# ============================================================ b：终态不许再放弃
@pytest.mark.parametrize("status", ["resolved", "abandoned", "stalled", "supported_not_proved"])
def test_b_a_terminal_plan_cannot_be_abandoned_again(tmp_path: pathlib.Path,
                                                     status: str) -> None:
    """b 判据：四档终态各受控拒一次，行一个字节不改（幂等不是"再写一行"）。

    改前红：改前没有这个入口（同 a）。

    "受控拒"的形状 = `PlanError`（`ToolError` 子类）：召唤层落
    `refused / invalid_params`（`conductor._business_refusal_code` 认它），工具层落
    `plan_error`（`attack_tools._guard` 认它）—— 两条路都不是 `unexpected`。
    细码写在拒信正文里（`plan_already_terminal`）。
    """
    store = _ws(tmp_path)
    f = _f(store)
    pid = _plan(store, key=f"PK-{status}", status=status)
    before = _row(store, pid)

    with pytest.raises(AF.PlanError) as ei:
        f.abandon_plan(pid, reason=REASON)

    err = str(ei.value)
    assert "plan_already_terminal" in err, err
    assert str(status) in err, err
    assert _row(store, pid) == before, "终态计划被改写了"


# ============================================================ c：词表外的理由
def test_c_a_reason_outside_the_vocabulary_is_refused(tmp_path: pathlib.Path) -> None:
    """c 判据：`reason="失败"`（词表外）受控拒，行不改 —— 不拿自由文本兜底。

    改前红：改前没有这个入口（同 a）。
    """
    store = _ws(tmp_path)
    f = _f(store)
    pid = _plan(store)
    before = _row(store, pid)

    with pytest.raises(AF.PlanError) as ei:
        f.abandon_plan(pid, reason="失败")

    err = str(ei.value)
    assert "plan_abandon_reason_not_allowed" in err, err
    assert "不再需要" in err, err
    assert _row(store, pid) == before, "被拒的那一笔写了库"


def test_c2_the_tool_layer_maps_the_refusal_to_a_controlled_kind(
        tmp_path: pathlib.Path) -> None:
    """c2 判据：同一笔拒收走工具层 ⇒ 受控 `plan_error`（不滑成 `unexpected`）。"""
    from agentflow.tools.base import ToolRegistry

    store = _ws(tmp_path)
    reg = ToolRegistry(name="agent-F")
    AT.register(reg, store=store)
    reg.bound_role = "F"
    res = reg.call("attack.abandon_plan", plan_id="999999", reason=REASON)
    assert res.ok is False, res
    assert res.meta.get("kind") == "plan_error", res.meta
    assert "plan_not_found" in str(res.error or ""), res.error


def test_e_stubbing_the_vocabulary_accepts_the_same_reason(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """e 判据（反真空）：把词表打桩成含"失败" ⇒ c 的同一笔必须变绿。

    证明 c 的红来自「词表只认不再需要」，而不是来自"这一笔本来就写不成"。
    """
    store = _ws(tmp_path)
    f = _f(store)
    pid = _plan(store)
    monkeypatch.setattr(AP, "PLAN_ABANDON_REASONS", (REASON, "失败"))
    out = f.abandon_plan(pid, reason="失败")
    assert out.get("ok") is True and out.get("status") == "abandoned", out
    assert "失败" in _row(store, pid)["history"][0]["detail"]


# ============================================================ d：非 F 无权重
def test_d_only_f_has_the_abandon_action_and_tool(tmp_path: pathlib.Path) -> None:
    """d 判据：动作表里只有 F 有它；D 的工具面里没有它；工具 roles 逐字 `("F",)`。

    改前红：改前这个动作/工具根本不存在（下面两条断言都会在"F 有它"那一半失败）。
    """
    specs_map = specs.builtin_specs()
    f_actions = {a.action for a in specs_map["F"].actions}
    d_actions = {a.action for a in specs_map["D"].actions}
    assert "abandon_plan" in f_actions, sorted(f_actions)
    assert "abandon_plan" not in d_actions, sorted(d_actions)

    store = _ws(tmp_path)
    reg = build_registry(store=store).registry
    f_tools = {s.name: s for s in reg.for_role("F")}
    d_tools = {s.name for s in reg.for_role("D")}
    assert "attack.abandon_plan" in f_tools, sorted(f_tools)
    assert "attack.abandon_plan" not in d_tools, sorted(d_tools)
    assert tuple(f_tools["attack.abandon_plan"].roles) == ("F",), (
        f_tools["attack.abandon_plan"].roles)


if __name__ == "__main__":          # pragma: no cover - 手工跑这一份时用
    raise SystemExit(pytest.main([__file__, "-q"]))



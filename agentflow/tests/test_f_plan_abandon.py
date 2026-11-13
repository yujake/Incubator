# -*- coding: utf-8 -*-
"""F 的 plan 级放弃口：`attack.abandon_plan`（业主 2026-11-13 裁定，含更正后的三档）。

业主原话（逐字）：

> 「我们依旧要说F应该有新的放弃理由为不再需要。」

业主更正（逐字）：

> 「`math_error` 和 `difficulty` 是正确的，不再需要是正确的，需要调整是错误的，
>   需要调整在放弃中应该是不再需要放弃掉原 plan 再开一个新 plan。」

## 裁定（逐条落地）

- 谁有权：F 自己（plan 归 F）—— 动作在 `specs/f.py` 的动作表里，工具只登记给
  `_WRITE_ROLES = ("F",)`；D 没有这个动作、也没有 `attack_plans` 的写集。
- 词表三档：`math_error` / `difficulty` / `不再需要`（前两档沿用命题级的标识符与
  证据口径，见 `planabandon`）；「需要调整」不是一档理由，是组合操作。
- 落点：`attack_plans.history` 一行（不加列、不做 schema 迁移），`status→abandoned`。
- 已终态不许再放弃（幂等/受控拒）。

## 判据

| 判据 | 它要证明的事 | 改前红在哪 |
|---|---|---|
| a | 「不再需要」放弃成功：status=abandoned、history 含四字、plan_id 不变 | 改前没有这个动作（`abandon_plan` 不存在） |
| a2 | `math_error` 档能落，`basis` 写进 history 的 `abandon_kind`/`detail` | 同上 |
| a3 | `difficulty` 档能落，`difficulty` 与归一后的 `salvaged` 写进 history | 同上 |
| b | 四档终态各拒一次（`plan_already_terminal`），行一个字节不改 | 同上 |
| c | 词表外（含「需要调整」）受控拒（`plan_abandon_reason_not_allowed`），行不改 | 同上 |
| c2 | 工具层把拒绝映射成受控 `plan_error`（不滑成 `unexpected`） | 同上 |
| c3 | 两档证据缺格 ⇒ 用命题级那三个形状码拒（`abandon_reason_missing` / `abandon_difficulty_required` / `abandon_salvaged_missing`） | 同上 |
| d | 非 F 无权重：D 的动作表 / D 的工具面都没有它；工具 roles 逐字是 `("F",)` | 同上 |
| e | 反真空：把词表打桩成含「需要调整」⇒ c 的同一笔必须变绿 | —— |
| f | 「调整」的端到端：放弃原 plan（不再需要）＋ 新设一条 plan，两条都在盘上、旧的是 terminal | 同上 |
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
from agentflow import statementabandon as SA
from agentflow.agent_f import abandon_plan as AP
from agentflow.store import Store
from agentflow.tools import build_registry
from agentflow.tools import attack_tools as AT

BUDGET = {"max_rounds": 3, "max_parallel_subgoals": 2,
          "max_persist_attempts": 2, "max_depth": 2}
REASON = "不再需要"
NOT_A_REASON = "需要调整"


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


# ============================================================ a：不再需要
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
    assert hist[0]["action"] == "abandon", hist
    assert hist[0]["abandon_kind"] == REASON, hist
    # 放弃不是"一轮推进"：这一行刻意不写 `outcome`（`history` 的 outcome 是
    # `STEP_OUTCOMES` 三档、停滞检测读它；`tests/test_agent_f_step_outcomes.py`
    # 的 AST 普查盯着 agent_f 里每一个 outcome 字面量）。
    assert "outcome" not in hist[0], hist
    assert REASON in hist[0]["detail"], hist  # 业主点名的四个字逐字在
    assert row.get("updated_at"), row


# ============================================================ a2/a3：前两档
def test_a2_math_error_tier_lands_with_its_basis(tmp_path: pathlib.Path) -> None:
    """a2 判据：`math_error` 档能落，`basis` 与档位都进 history。"""
    store = _ws(tmp_path)
    f = _f(store)
    pid = _plan(store)
    out = f.abandon_plan(pid, reason=SA.ABANDON_KIND_MATH_ERROR,
                         basis="第 3 步把 n=2 的情形当成一般情形，结论不成立")
    assert out.get("ok") is True and out.get("status") == "abandoned", out
    hist = _row(store, pid)["history"]
    assert hist[-1]["abandon_kind"] == SA.ABANDON_KIND_MATH_ERROR, hist
    assert "第 3 步" in hist[-1]["detail"], hist


def test_a3_difficulty_tier_lands_with_difficulty_and_salvaged(tmp_path: pathlib.Path) -> None:
    """a3 判据：`difficulty` 档能落，`difficulty` 与归一后的 `salvaged` 都进 history。"""
    store = _ws(tmp_path)
    f = _f(store)
    pid = _plan(store)
    out = f.abandon_plan(
        pid, reason=SA.ABANDON_KIND_DIFFICULTY,
        basis="卡在紧性估计：需要一条与主链独立的界",
        difficulty="卡在紧性引理，现有工具拿不到一致常数",
        salvaged=[{"label": "部分紧性", "stmt_id": "000051"}])
    assert out.get("ok") is True and out.get("status") == "abandoned", out
    hist = _row(store, pid)["history"][-1]
    assert hist["abandon_kind"] == SA.ABANDON_KIND_DIFFICULTY, hist
    assert "紧性" in hist["difficulty"], hist
    assert hist["salvaged"] == [{"label": "部分紧性", "stmt_id": "000051"}], hist


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


# ============================================================ c：词表外（含「需要调整」）
def test_c_a_reason_outside_the_vocabulary_is_refused(tmp_path: pathlib.Path) -> None:
    """c 判据：词表外的理由受控拒，行不改 —— 不拿自由文本兜底。

    特别钉「需要调整」：它不是一档理由，是"不再需要放弃原 plan + 新开一条"的组合
    操作（业主更正原话）。
    """
    store = _ws(tmp_path)
    f = _f(store)
    pid = _plan(store)
    before = _row(store, pid)

    for bad in (NOT_A_REASON, "失败"):
        with pytest.raises(AF.PlanError) as ei:
            f.abandon_plan(pid, reason=bad)
        err = str(ei.value)
        assert "plan_abandon_reason_not_allowed" in err, err
        assert REASON in err, err   # 拒信把三档词表念出来
    # 「需要调整」那一笔要额外说清"它是操作，不是理由"
    with pytest.raises(AF.PlanError) as ei2:
        f.abandon_plan(pid, reason=NOT_A_REASON)
    assert "组合操作" in str(ei2.value), str(ei2.value)
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


def test_c3_the_two_evidence_tiers_refuse_when_a_cell_is_missing(
        tmp_path: pathlib.Path) -> None:
    """c3 判据：两档证据缺格 ⇒ 用命题级那三个形状码拒（同一个码，不是新造）。"""
    store = _ws(tmp_path)
    f = _f(store)
    pid = _plan(store)
    before = _row(store, pid)
    cases = [
        (dict(reason=SA.ABANDON_KIND_MATH_ERROR), SA.ABANDON_REASON_MISSING),
        (dict(reason=SA.ABANDON_KIND_DIFFICULTY, basis="难"),
         SA.ABANDON_DIFFICULTY_REQUIRED),
        (dict(reason=SA.ABANDON_KIND_DIFFICULTY, basis="难", difficulty="很难"),
         SA.ABANDON_SALVAGED_MISSING),
    ]
    for kwargs, code in cases:
        with pytest.raises(AF.PlanError) as ei:
            f.abandon_plan(pid, **kwargs)
        assert code in str(ei.value), (code, str(ei.value))
    assert _row(store, pid) == before, "被拒的那几笔写了库"


# ============================================================ e：反真空
def test_e_stubbing_the_vocabulary_accepts_the_excluded_reason(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """e 判据（反真空）：把词表打桩成含「需要调整」⇒ c 的同一笔必须变绿。

    证明 c 的红来自"三档词表里没有它"，而不是来自"这一笔本来就写不成"。
    """
    store = _ws(tmp_path)
    f = _f(store)
    pid = _plan(store)
    monkeypatch.setattr(AP, "PLAN_ABANDON_REASONS", (REASON, NOT_A_REASON))
    out = f.abandon_plan(pid, reason=NOT_A_REASON)
    assert out.get("ok") is True and out.get("status") == "abandoned", out
    assert _row(store, pid)["history"][-1]["abandon_kind"] == NOT_A_REASON


# ============================================================ f：调整的端到端
def test_f_adjust_is_abandon_plus_a_new_plan(tmp_path: pathlib.Path) -> None:
    """f 判据（业主口径）：「需要调整」= 用「不再需要」放弃原 plan ＋ 新设一条 plan。

    两条都在盘上，旧的那条是 terminal（`abandoned`），新的那条是 open。
    """
    store = _ws(tmp_path)
    f = _f(store)
    old = f.create_plan("原方向", "PK-ADJUST-OLD", budget=dict(BUDGET))["plan_id"]
    out = f.abandon_plan(old, reason=REASON, basis="目标已改为新方向")
    assert out.get("ok") is True, out
    new = f.create_plan("新方向", "PK-ADJUST-NEW", budget=dict(BUDGET))["plan_id"]
    assert new and new != old, (old, new)
    assert _row(store, old)["status"] == "abandoned", _row(store, old)
    assert _row(store, new)["status"] == "open", _row(store, new)
    assert len(store.rows("attack_plans")) == 2, store.rows("attack_plans")


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

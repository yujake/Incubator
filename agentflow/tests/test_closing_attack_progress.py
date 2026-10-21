# -*- coding: utf-8 -*-
"""判据：「攻（攻坚推进）」那一格 (`plan_progress_rows`) 量的是真的推进，不是"被 step 过"。

## 改前的读数（`draft/44` 的 P1-1）

`closing._leg_reading` 里那一档只有一行判据：`advanced = [r for r in rows if list(r.get("history") or [])]`。于是两轮全 `no_change` 的计划（`dead_end` 逐轮落库、子目标一条没动）与四轮全 `progress` 的计划在收工门上等值（真机 mp3：`000000` 读到的数与 `000001` 一样）。那一格是「攻」这一环节的唯一读数 —— 等值就等于这一格什么都没量到。

## 改后的口径

判据本体是 `closing._round_advanced`，三条缺一不可：① `outcome == "progress"`（`no_change` / `blocked` 都不是推进）；② 有据可依：产物里有 `cites`（`proof.steps[].cites` / `dead_end.best_partial[].ids`）；③ 或者产出了新东西：`reduction.new_subgoals` / `counterexample_request` 派出 E 子目标 / `run_experiment` 落了一行实验。

②③是"或"；只派检索/重抽取请求的那种轮两条都不满足 ⇒ 不算推进（那是「闭」那一档的事）。

## 判据的形状

- 正控：两份计划（全 `no_change` / 有 `progress`）在同一张台账里，读数必须是 `0` 与 `1`，而且不得相等；
- 负控①（证明改前会红）：把口径换回"`history` 非空即算" ⇒ 两份计划的读数变成相等，这正是改前那一格的形态；
- 负控②：只派检索请求的轮不算（`submit_search_request` 那种"把活递出去"的轮）；
- 读数可见：一份读到 0 的计划，`why` 要能说清"为什么不算"（三态纪律：0 与读不到必须分得开）。"""
from __future__ import annotations

import pathlib
from typing import Any

import pytest

from agentflow import closing as CL
from agentflow.store import Store

TS = "2026-10-19T00:00:00+08:00"


def _plan(store: Store, plan_id: str, history: list[dict[str, Any]], *,
          problem: str = "把界推到 n≤20") -> None:
    """往台账里写一份形状合法的攻坚计划（`history` 由调用方给）。"""
    with store.tx("attack_plans", actor="test", note="attack-progress probe") as tx:
        tx.upsert("attack_plans", {
            "plan_id": plan_id, "problem": problem, "problem_key": f"key-{plan_id}",
            "status": "attacking",
            "budget": {"max_rounds": 6, "max_parallel_subgoals": 2,
                       "max_persist_attempts": 2, "max_depth": 1},
            "subgoals": [{"sid": "s1", "text": "判定这条命题", "owner": "F",
                          "status": "in_progress", "evidence_ids": [],
                          "experiment_ids": [], "proof_experiment_ids": [],
                          "blocked_reason": "", "attempts": 1, "negation_kind": None}],
            "history": history, "created_at": TS, "created_by": "test",
        })


def _dead_round(n: int) -> dict[str, Any]:
    """一轮 `dead_end`：`outcome=no_change`、`cites` 为空、没产出任何新东西。"""
    return {"round": n, "sid": "s1", "action": "dead_end", "outcome": "no_change",
            "detail": "这一轮走不下去（方法不适用）",
            "evidence": [], "at": TS,
            "product": "dead_end", "strategy": "套用已知定理",
            "best_partial": [{"what": "已把范围缩到 k=6", "ids": [], "why_partial": "不是进展"}],
            "product_detail": {"product": "dead_end", "strategy": "套用已知定理",
                               "why_strategy": "九招都落不下去", "reason": "方法不适用",
                               "evidence": "没有可判定的有限形式",
                               "best_partial": [{"what": "已把范围缩到 k=6", "ids": [],
                                                 "why_partial": "不是进展"}]},
            "dead_end_reason": "方法不适用"}


def _proof_round(n: int) -> dict[str, Any]:
    """一轮成形的 `proof`：`outcome=progress`，且每一步都有 `cites`。"""
    return {"round": n, "sid": "s1", "action": "proof", "outcome": "progress",
            "detail": "论证（反证）：3 步；这一轮是**论证**不是机器核验 ⇒ 子目标不关闭",
            "evidence": [], "at": TS,
            "product": "proof", "strategy": "反证",
            "product_detail": {"product": "proof", "strategy": "反证",
                               "why_strategy": "反设存在反例",
                               "steps": [{"n": 1, "text": "反设存在反例", "cites": ["stmt:000000"],
                                          "assumption": True},
                                         {"n": 2, "text": "由谱半径估计得界",
                                          "cites": ["exp:000001"], "assumption": False}]}}


def _request_round(n: int) -> dict[str, Any]:
    """一轮只把检索请求递出去的轮（`submit_search_request`）：不是攻坚推进。"""
    return {"round": n, "sid": "s1", "action": "submit_search_request", "outcome": "progress",
            "detail": "已向 A 提交检索请求 r-000001", "evidence": ["r-000001"], "at": TS}


@pytest.fixture()
def store(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _got(store: Store) -> tuple[int, dict[str, Any]]:
    return CL._leg_reading(store, "plan_progress_rows", pathlib.Path(store.root))


def test_a_no_change_plan_never_reads_the_same_as_a_progressing_one(store: Store):
    """正控：全 `no_change` 的计划读 0，有 `progress` 的计划读 1 —— 且两者不相等。"""
    _plan(store, "000000", [_dead_round(1), _dead_round(2)])
    _plan(store, "000001", [_proof_round(1), _proof_round(2), _proof_round(3),
                            _proof_round(4)])
    got, detail = _got(store)

    assert got == 1, detail
    by_id = {p["id"]: p for p in detail["plans"]}
    assert by_id["000000"]["progress_rounds"] == 0, by_id["000000"]
    assert by_id["000001"]["progress_rounds"] == 4, by_id["000001"]
    assert [p["id"] for p in detail["advanced_plans"]] == ["000001"], detail["advanced_plans"]
    # 改前那一格的核心症状：两份计划等值
    assert by_id["000000"]["progress_rounds"] != by_id["000001"]["progress_rounds"]


def test_the_dead_plan_alone_reads_zero_and_says_why(store: Store):
    """反真空 + 读数可见：只有死路计划时读 0，且 `why` 说得清"为什么不算"。"""
    _plan(store, "000000", [_dead_round(1), _dead_round(2)])
    got, detail = _got(store)
    assert got == 0, detail
    assert detail["total_plans"] == 1
    assert detail["advanced_plans"] == []
    gone = detail["plans"][0]
    assert gone["history_len"] == 2 and gone["no_progress_rounds"] == 2, gone


def test_the_old_criterion_would_make_the_two_plans_equal(store: Store, monkeypatch):
    """负控（证明修好前会红）：口径换回"`history` 非空即算" ⇒ 两份计划读数相等。"""
    _plan(store, "000000", [_dead_round(1), _dead_round(2)])
    _plan(store, "000001", [_proof_round(1)])

    def old(rec):
        return (bool(rec), "旧口径：history 里有记录就算")

    monkeypatch.setattr(CL, "_round_advanced", old)
    got_old, detail_old = _got(store)
    assert got_old == 2, detail_old           # 改前：两份都算"推进过"（= 台账里有几份就数几份）
    by_id = {p["id"]: p for p in detail_old["plans"]}
    assert by_id["000000"]["progress_rounds"] == 2, by_id["000000"]   # 两轮死路全算成"推进"
    assert by_id["000001"]["progress_rounds"] == 1, by_id["000001"]
    assert got_old == detail_old["total_plans"], detail_old

    monkeypatch.undo()
    got_new, detail_new = _got(store)
    assert got_new == 1, detail_new           # 修好之后：只剩真有推进的那一份
    assert got_new != got_old


def test_a_round_that_only_hands_a_request_out_is_not_attack_progress(store: Store):
    """负控②：只派检索请求的轮不算「攻」的推进（那是「闭」那一档的读数）。"""
    _plan(store, "000002", [_request_round(1)])
    got, detail = _got(store)
    assert got == 0, detail
    assert "请求" in detail["note"], detail["note"]
    # 单独判在轮上：`progress` 但没有 cites / 新子目标 / 新实验 ⇒ 不算
    ok, why = CL._round_advanced(_request_round(1))
    assert ok is False and "请求" in why, why


def test_a_reduction_round_counts_because_the_plan_really_gained_subgoals(store: Store):
    """正控（②/③的"或"那一半）：归约出新子目标的轮算推进 —— 它的 `cites` 是空的。"""
    rec = {"round": 1, "sid": "s1", "action": "reduction", "outcome": "progress",
           "detail": "归约（归约）：新子目标 ['s2', 's3']", "evidence": ["s2", "s3"], "at": TS,
           "product": "reduction", "strategy": "归约",
           "product_detail": {"product": "reduction", "strategy": "归约",
                              "why_strategy": "先缩小范围",
                              "new_subgoals": [{"goal": "判定 n≤12", "testable": "枚举"},
                                               {"goal": "给出族公式", "testable": "参数族"}]}}
    ok, why = CL._round_advanced(rec)
    assert ok is True and "新子目标" in why, why
    # 同一条记录的 `outcome` 改成 `no_change` ⇒ 立刻不算（①那一半不许被跳过）
    assert CL._round_advanced({**rec, "outcome": "no_change"})[0] is False

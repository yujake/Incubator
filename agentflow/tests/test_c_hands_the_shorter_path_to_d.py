# -*- coding: utf-8 -*-
"""C → D：C 能把「候选的更短路径」交给 D（2026-10-19 业主裁定）。

## 裁定与它要落的东西

业主逐字：「**C 要能把"候选的更短路径"交给 D**」。改前 `src/agentflow/specs/c.py`
那一行是 `edges=()`，于是 C 的图读数（哪条链绕远路）只能写进自己的回复里，
要变成一条猜想必须借别人的边绕两跳（真机 `t5-run2` 里 B 就是借 `H` 绕去找 A 的形态）。
现在 C 有一条出边，目标是唯一能立猜想的那一环：D。

## 这一组守什么（正控 2 / 负控 1 / 反真空 1）

- 正控①：**两层都读得到**这条边 —— 声明层（`specs` 表里的 `edges`）与派生层
  （`capabilities.ALLOWED_EDGES`，导入期交叉断言由前者派生）；
- 正控②（端到端）：C **真的**派得动 D —— 走 `Conductor.summon(..., by="C")`，
  即真机那条路（边闸门 / 台账 / backend 三处都跑），只用桩替模型、不调任何 API；
- 负控：把 C 的边改回空（改前那一版）⇒ 同一次 summon 必须被 `forbidden_edge` 拒 ⇒
  正控② 那条判据当场红（证明它真的在守这条边，而不是"恰好通过"）；
- 反真空：加边**只加了这一条** —— C 仍然是只读角色，`read_only` / `write_set` /
  `actions` 一个字没动（裁定只给"请求"，不给"写入"）。

为什么"能 summon"这一条必须端到端跑一次而不是只断言表里有个字符串：
`ALLOWED_EDGES` 由 specs 派生这件事是导入期交叉断言保证的，它保证的是"两层一致"，
**不保证**这条边在召唤那一刻真的被闸门放行（`policy.check` 还会看
`NON_SUMMONABLE` / 深度 / 动作表）。真机 `t5-run2` 的教训正是"表里写了、路上不通"。
"""
from __future__ import annotations

import pathlib

import pytest

from agentflow import capabilities as C
from agentflow.conductor import Conductor
from agentflow.specs import builtin_specs
from agentflow.store import Store

#: C 交给 D 的那件事的动作名。挑 `register_conjecture` 而不是随便一个 D 的动作：
#: 裁定的语义是"把候选路径交给 D **立猜想**"，而它自己那条 `run_round` 的参数字典里
#: 早就写着「一份 C 的分析报告（`analysis_reports` 那行的对象；**C→D 那条路就是这么传的**）」
#: —— 这条边是设计里等着的，不是新发明。
CANDIDATE_ACTION = "register_conjecture"


class _FakeD:
    """D 的替身：只实现这一条无副作用的动作，用来验证「C 派得动 D」。"""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def register_conjecture(self, statement: str, origin: str, **kw) -> dict:
        self.calls.append({"statement": statement, "origin": origin, **kw})
        return {"conjecture_id": "c-0001", "statement": statement, "origin": origin}


def _wired(tmp_path: pathlib.Path) -> tuple[Store, Conductor, _FakeD]:
    ws = tmp_path / "ws"
    store = Store(ws)
    store.init()
    d = _FakeD()
    cond = Conductor(store, registry={"D": d})
    return store, cond, d


# ============================================================ 正控① 两层都读得到


def test_the_spec_and_the_derived_table_both_say_c_to_d() -> None:
    """正控①：声明层与派生层都写着 `C → D`（导入期交叉断言由声明层派生派生层）。"""
    spec = builtin_specs()["C"]
    assert "D" in tuple(spec.edges), f"specs 里 C 的出边是 {spec.edges!r}，没有 D"
    assert C.ALLOWED_EDGES["C"] == frozenset({"D"}), C.ALLOWED_EDGES["C"]


def test_the_new_edge_did_not_widen_c_s_write_face() -> None:
    """反真空：只加了这一条边 —— C 的只读面一个字节没动（裁定给的是"请求"，不是"写入"）。"""
    spec = builtin_specs()["C"]
    assert spec.read_only is True, "C 掉了只读标记 —— 裁定只允许它**请求** D"
    assert spec.write_set == frozenset({"analysis_reports", "search_requests"}), spec.write_set
    assert C.WRITE_SETS["C"] == frozenset({"analysis_reports", "search_requests"}), C.WRITE_SETS["C"]
    # 出边只有这一条（不是"顺手放开"）：多一条都是一个没人审过的权限。
    assert tuple(spec.edges) == ("D",), spec.edges


# ============================================================ 正控② 端到端：真的派得动


def test_c_can_actually_summon_d(tmp_path: pathlib.Path) -> None:
    """正控②（端到端）：`summon(..., by="C")` 一路走通 —— 边闸门放行、台账落行、D 真的被唤起。

    这条是裁定的落地读数：C 的"候选更短路径"在**运行期**有出路，不必再借别人的边。
    """
    store, cond, d = _wired(tmp_path)
    res = cond.summon(
        "D", CANDIDATE_ACTION,
        {"statement": "这条链比现有那条短一跳", "origin": "C 的图读数：绕行长度 4 → 2"},
        by="C",
    )
    assert res.outcome == "ok", (res.outcome, res.detail, res.refusal_reason)
    assert res.role == "D" and res.action == CANDIDATE_ACTION
    assert res.task_id, "被受理的召唤必须落一个台账号（拒绝也落行，但这一条是 ok）"
    # 台账里真的有一行，且发起方是 C（不是 M 代发）
    row = cond._task(str(res.task_id))                                   # noqa: SLF001
    assert row and row.get("called_by") == "C", row
    # D 的替身真的被调用了一次（不是"台账说派了"）
    assert d.calls and d.calls[0]["statement"] == "这条链比现有那条短一跳", d.calls
    # 落表的行也在（"派了"与"做了什么"是两件事，都要看得见）
    assert len(store.rows("tasks")) == 1, store.rows("tasks")


# ============================================================ 负控：边改回空 ⇒ 红


def test_negative_control_emptying_the_edge_refuses_the_same_summon(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """负控：把 C 的边改回空（= 改前那一版）⇒ 同一次 summon 被 `forbidden_edge` 拒。

    它证明上面那条端到端判据真的在守这条边：闸门读的就是这张表，
    表里没有边的时候**没有任何别的东西**会把这次召唤放行（`NON_SUMMONABLE` /
    动作表都不管这一格）。改回去（不再 patch）必须立刻恢复 `ok` —— 负控的负控。
    """
    store, cond, d = _wired(tmp_path)
    original = C.ALLOWED_EDGES["C"]
    monkeypatch.setattr(C, "ALLOWED_EDGES", {**C.ALLOWED_EDGES, "C": frozenset()})
    try:
        refused = cond.summon(
            "D", CANDIDATE_ACTION,
            {"statement": "这条链比现有那条短一跳", "origin": "C 的图读数"},
            by="C",
        )
        assert refused.outcome != "ok", refused
        assert refused.refusal_reason == "forbidden_edge", (
            f"边被抹掉之后拒的理由码是 {refused.refusal_reason!r}，不是 forbidden_edge —— "
            "那说明这次召唤是被别的闸门挡下的，这条负控就没打在边表上")
    finally:
        monkeypatch.undo()
    assert C.ALLOWED_EDGES["C"] == original, "负控收尾：边表必须原样还回去"
    # 负控的负控：还回去之后同一次召唤必须重新走通（门不能变成永远关着）
    ok_res = cond.summon(
        "D", CANDIDATE_ACTION,
        {"statement": "这条链比现有那条短一跳", "origin": "C 的图读数"},
        by="C",
    )
    assert ok_res.outcome == "ok", (ok_res.outcome, ok_res.detail, ok_res.refusal_reason)
    assert d.calls, "边恢复之后 D 的替身应当真的被唤起"

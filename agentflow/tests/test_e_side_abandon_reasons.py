# -*- coding: utf-8 -*-
"""E 侧数值证明路线的两道闸之第一道：放弃命题的两个 E 侧理由档（业主 2026-11-07 第二刀）。

业主原话（逐字，这就是本文件的验收标准）：

> 「F侧的注册+放弃闸需同步到E侧的数值证明路线，只不过E侧放弃的理由为：
>   1.发现反例；2.枚举空间过于宏大以致难以在合理成本内实现。」

## 这一档与 F 侧那两档的关系

判定口只有一处：`statementabandon.check_abandon_reason`（F 侧的 `math_error` /
`difficulty` 与 E 侧的 `counterexample` / `space_too_large` 都从它出结论）。
本文件不另写一份"像不像反例 / 空间大不大"的判据 —— 每一格都打桩数过调用次数
（`test_d_*`）：两个写口（`apply_abandonment` / `Secretary.amend_statement_meta`）
都只经过那一个函数。

## 判据

| # | 判据 | 用例 |
|---|---|---|
| a | counterexample：真反例实验 ⇒ 过；引用不存在的实验 ⇒ 拒；引用一条没反驳它的实验 ⇒ 拒；引用另一条命题的反例 ⇒ 拒 | `test_a_*` |
| b | space_too_large：带真空间读数 ⇒ 过；缺 `space` / 读不到 ⇒ 拒（fail-closed）；`space` 填自由文本 / 只有文字没有规模 ⇒ 拒 | `test_b_*` |
| d | 共用一处判定：两个写口都只调 `check_abandon_reason`（打桩计数） | `test_d_*` |
| e | 反真空：把 counterexample 档的证据校验摘掉 ⇒ a 红 | `test_e_*` |
"""
from __future__ import annotations

import pathlib

import pytest
from agentflow import closing as CL
from agentflow import conductor as CND
from agentflow import schema as S
from agentflow import secretary as SEC
from agentflow import statementabandon as SA
from agentflow.store import Store

TS = "2026-11-07T12:00:00+08:00"
SID = "000001"
FULL = "对任意正整数 n，R(3,4)=9。"
LABEL = "ramsey34"

CFX = {"kind": "counterexample", "n": 9, "value": "[9, 9] 的二染色里 R(3,4) 的那一格"}


def _ws(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _put_statement(st: Store, sid: str = SID, *, kind: str = "conjecture",
                   label: str = LABEL, status: str = "active",
                   statement_full: str = FULL) -> dict:
    row = {
        "stmt_id": sid, "origin": "own_result", "kind": kind, "label": label,
        "statement_full": statement_full, "statement_text": statement_full,
        "proof_text": "数值算过一遍。", "evidence_kind": "heuristic",
        "status": status, "quote_verified": None, "quote_reason": "夹具：自产命题",
        "created_at": TS, "created_by": "test", "bits": {},
    }
    with st.tx("statements", actor="test") as tx:
        tx.upsert("statements", row)
    return row


def _put_experiment(st: Store, eid: str = "000001", *, claim: str = FULL,
                    claim_key: str = LABEL, result: str = "refutes",
                    counterexample: dict | None = None,
                    negation_kind: str = "disproved") -> dict:
    row = {
        "experiment_id": eid, "claim": claim, "claim_key": claim_key,
        "method": "numeric", "evidence_kind": "cross_check", "result": result,
        "negation_kind": negation_kind if result == "refutes" else "not_proved",
        "counterexample": CFX if (result == "refutes" and counterexample is None)
        else counterexample,
        "code_path": "code/probe.py", "code_hash": "0" * 16,
        "observations": {}, "certificate": None, "search_bound": {},
        "exit_code": 0, "runtime_sec": 0.1, "created_at": TS, "created_by": "test",
    }
    S.Experiment(**{k: v for k, v in row.items()
                    if k in S.Experiment.__dataclass_fields__}).validate()
    with st.tx("experiments", actor="test") as tx:
        tx.upsert("experiments", row)
    return row


def _abandon(st: Store, sid: str = SID, **kw):
    """走生产写口（`Secretary.amend_statement_meta`，即 `table.update` 的兜底方）。"""
    sec = SEC.Secretary("B", root=st.root, store=st)
    return sec.amend_statement_meta(sid, {"status": "abandoned", **kw}, role="B")


def _row(st: Store, sid: str = SID) -> dict:
    return next(dict(r) for r in st.rows("statements") if str(r.get("stmt_id")) == sid)


def _count(st: Store) -> int:
    return len(list(st.rows("statements")))


def _abandoned(st: Store) -> dict:
    return CL.statements_abandoned_reading(st)


# ---------------------------------------------------------------- a counterexample

def test_a_a_real_counterexample_experiment_lets_the_abandonment_through(tmp_path):
    """a 正控：真反例实验（result=refutes + 非空 counterexample）⇒ 过，标记可读回。"""
    st = _ws(tmp_path)
    _put_statement(st)
    _put_experiment(st, "000001")
    got = _abandon(st, SID, abandon_kind="counterexample",
                   abandon_basis="n=9 的那一组参数让命题为假：R(3,4) 的实际值是 9，"
                                 "而命题写成了 9 的另一个方向。",
                   experiment_id="000001")
    assert got.get("checked") is True and got.get("amended") is True, got
    row = _row(st)
    assert row["status"] == "abandoned", row
    parsed = SA.parse_abandon_reason(row["quote_reason"])
    assert parsed.get("checked") is True and parsed.get("complete") is True, parsed
    assert parsed["abandon_kind"] == "counterexample", parsed
    assert parsed["experiment_id"] == "000001", parsed
    assert parsed["abandon_basis"], parsed
    read = _abandoned(st)
    assert read["count"] == 1, read
    assert read["rows"][0]["abandon_kind"] == "counterexample", read["rows"][0]
    assert read["rows"][0]["structured"] is True, read["rows"][0]


def test_a_an_experiment_that_does_not_exist_is_refused(tmp_path):
    """a 负控 1：引用一行不存在的实验 ⇒ 拒，盘上一个字节都不写。"""
    st = _ws(tmp_path)
    _put_statement(st)
    before = _row(st)
    got = _abandon(st, SID, abandon_kind="counterexample",
                   abandon_basis="某个参数组让它为假", experiment_id="999999")
    assert got.get("checked") is False, got
    assert got.get("refused") == "abandon_counterexample_experiment_missing", got
    assert _row(st) == before, "受控拒必须一个字节都不写"
    assert _count(st) == 1


def test_a_an_experiment_that_did_not_refute_it_is_refused(tmp_path):
    """a 负控 2：引用一条"没反驳它"的实验（supports、没有 counterexample）⇒ 拒。"""
    st = _ws(tmp_path)
    _put_statement(st)
    _put_experiment(st, "000002", result="supports", counterexample=None)
    got = _abandon(st, SID, abandon_kind="counterexample",
                   abandon_basis="我看它不对", experiment_id="000002")
    assert got.get("checked") is False, got
    assert got.get("refused") == "abandon_counterexample_not_refuting", got
    assert _row(st)["status"] == "active"


def test_a_an_experiment_about_another_statement_is_refused(tmp_path):
    """a 负控 3：那一行确实证否了另一条断言 ⇒ 不是这条命题的反例。"""
    st = _ws(tmp_path)
    _put_statement(st)
    _put_experiment(st, "000003", claim="另一条完全无关的断言", claim_key="other")
    got = _abandon(st, SID, abandon_kind="counterexample",
                   abandon_basis="它反驳了那条", experiment_id="000003")
    assert got.get("checked") is False, got
    assert got.get("refused") == "abandon_counterexample_other_statement", got


def test_a_missing_experiment_id_is_refused(tmp_path):
    """a 负控 4：只说"发现了反例"、不给 `experiment_id` ⇒ 拒（词面不是证据）。"""
    st = _ws(tmp_path)
    _put_statement(st)
    got = _abandon(st, SID, abandon_kind="counterexample",
                   abandon_basis="我找到了一个反例")
    assert got.get("checked") is False, got
    assert got.get("refused") == "abandon_counterexample_required", got


def test_a_through_the_generic_table_update_port(tmp_path):
    """a 的第二半：`table.update`（业主验收的通用写口）也能把两格带进来。"""
    from agentflow.tools import table_tools
    from agentflow.tools.base import ToolRegistry

    st = _ws(tmp_path)
    _put_statement(st)
    _put_experiment(st, "000001")
    reg = ToolRegistry(name="tables")
    reg.bound_role = "B"
    table_tools.register(reg, store=st)
    with CND.calling_as("t-b1", "B"):
        res = reg.call("table.update", table="statements", id=SID,
                       patch={"status": "abandoned", "abandon_kind": "counterexample",
                              "abandon_basis": "n=9 那一格让它为假",
                              "experiment_id": "000001"})
    assert res.ok is True, res.error
    parsed = SA.parse_abandon_reason(_row(st)["quote_reason"])
    assert parsed["abandon_kind"] == "counterexample", parsed
    assert parsed["experiment_id"] == "000001", parsed


# ---------------------------------------------------------------- b space_too_large

def _space_kwargs() -> dict:
    return {"abandon_kind": "space_too_large",
            "abandon_basis": "对 n>=14 的全枚举要 10^12 个对象；每个对象一次同构判定，"
                             "按现有机器 10^4/s 要 10^8 秒，合理成本内做不到。",
            "space": {"N_range": [2, 14], "D_range": [2, 10], "cells": 1000000000000,
                      "per_cell": 10 ** 12}}


def test_b_a_real_space_reading_lets_the_abandonment_through(tmp_path):
    """b 正控：带真空间读数（各维区间 + 枚举量）⇒ 过，读数原样落进标记。"""
    st = _ws(tmp_path)
    _put_statement(st)
    got = _abandon(st, SID, **_space_kwargs())
    assert got.get("checked") is True and got.get("amended") is True, got
    parsed = SA.parse_abandon_reason(_row(st)["quote_reason"])
    assert parsed.get("complete") is True, parsed
    assert parsed["abandon_kind"] == "space_too_large", parsed
    assert parsed["space"]["N_range"] == [2, 14], parsed
    read = _abandoned(st)
    assert read["rows"][0]["abandon_kind"] == "space_too_large", read["rows"][0]


def test_b_missing_space_is_refused_fail_closed(tmp_path):
    """b 负控 1：不给 `space` ⇒ 拒（读数读不到 ⇒ fail-closed）。"""
    st = _ws(tmp_path)
    _put_statement(st)
    got = _abandon(st, SID, abandon_kind="space_too_large",
                   abandon_basis="空间太大了，做不完")
    assert got.get("checked") is False, got
    assert got.get("refused") == "abandon_space_required", got
    assert _row(st)["status"] == "active"


def test_b_free_text_in_space_is_refused(tmp_path):
    """b 负控 2：`space` 填"太大了"这种自由文本 ⇒ 拒（不许用词面代替读数）。"""
    st = _ws(tmp_path)
    _put_statement(st)
    got = _abandon(st, SID, abandon_kind="space_too_large",
                   abandon_basis="太大了", space="太大了")
    assert got.get("checked") is False, got
    assert got.get("refused") == "abandon_space_unreadable", got
    got2 = _abandon(st, SID, abandon_kind="space_too_large",
                    abandon_basis="太大了", space={"space": "太大了"})
    assert got2.get("checked") is False, got2
    assert got2.get("refused") == "abandon_space_not_a_reading", got2


def test_b_a_space_object_without_any_scale_is_refused(tmp_path):
    """b 负控 3：`space` 是对象但没有区间 / 枚举量 ⇒ 读不出"多宏大"，拒。"""
    st = _ws(tmp_path)
    _put_statement(st)
    got = _abandon(st, SID, abandon_kind="space_too_large",
                   abandon_basis="复杂度爆炸", space={"note": "too large to enumerate"})
    assert got.get("checked") is False, got
    assert got.get("refused") == "abandon_space_not_a_reading", got


def test_b_the_reading_can_come_from_an_experiment_row_shape(tmp_path):
    """b 正控 2：给实验行那三格（`observations` / `certificate` / `search_bound`）也认。"""
    st = _ws(tmp_path)
    _put_statement(st)
    space = {"observations": {"search_space": {"n_cases": 10 ** 12, "dims": 5}},
             "search_bound": {"N_range": [2, 14]}}
    got = _abandon(st, SID, abandon_kind="space_too_large",
                   abandon_basis="10^12 个对象，成本不允许", space=space)
    assert got.get("checked") is True, got
    parsed = SA.parse_abandon_reason(_row(st)["quote_reason"])
    assert parsed["space"], parsed
    assert parsed["space"]["N_range"] == [2, 14], parsed


# ---------------------------------------------------------------- d 共用一处判定

def test_d_both_write_ports_go_through_the_one_check(monkeypatch):
    """d：两个写口都只调 `check_abandon_reason`（打桩计数，只此一份实现）。"""
    calls: list[str] = []
    real = SA.check_abandon_reason

    def _counting(*a, **kw):
        calls.append(str(kw.get("kind") or ""))
        return real(*a, **kw)

    monkeypatch.setattr(SA, "check_abandon_reason", _counting)
    import tempfile

    root = pathlib.Path(tempfile.mkdtemp(prefix="abandon-d-"))
    st = Store(root / "ws")
    st.init()
    _put_statement(st, "000001")
    _put_experiment(st, "000001", claim=FULL, claim_key=LABEL)
    got = _abandon(st, "000001", abandon_kind="counterexample",
                   abandon_basis="n=9 那一格", experiment_id="000001")
    assert got.get("checked") is True, got
    # 第二个写口：`apply_abandonment`（低层直调）
    _put_statement(st, "000002", label="other")
    got2 = SA.apply_abandonment(st, statement_id="000002", reason="x",
                                at=TS, abandon_kind="space_too_large",
                                abandon_basis="太大了，做不完",
                                space={"N_range": [2, 14]})
    assert got2.get("checked") is True, got2
    assert calls == ["counterexample", "space_too_large"], calls


# ---------------------------------------------------------------- f 读数按档

def _seed_abandoned(st: Store, sid: str, label: str, kind: str, **parts) -> None:
    """直接落一条 abandoned 行（读侧用例：不走写口，只造读数）。"""
    marker = SA.abandon_marker(at=TS, reason=SA.structured_reason(
        kind=kind, basis="夹具：理由是结构化 JSON", **parts))
    row = {"stmt_id": sid, "origin": "own_result", "kind": "conjecture", "label": label,
           "statement_full": f"夹具命题 {sid}。", "statement_text": f"夹具命题 {sid}。",
           "proof_text": "", "evidence_kind": "heuristic", "status": "abandoned",
           "quote_verified": None, "quote_reason": marker, "created_at": TS,
           "created_by": "test", "bits": {}}
    with st.tx("statements", actor="test") as tx:
        tx.upsert("statements", row)


def test_f_the_reading_counts_every_kind_and_the_relabeled_events(tmp_path):
    """f：`statements_abandoned_reading` 能按四档分别统计（含 `relabeled.kinds`）。"""
    st = _ws(tmp_path)
    _seed_abandoned(st, "000001", "same", "math_error", defect_ref="verifications/000001.jsonl#v-000001")
    _seed_abandoned(st, "000002", "same", "counterexample", experiment_id="000001")
    _seed_abandoned(st, "000003", "diff", "space_too_large",
                    space={"N_range": [2, 14]})
    # 历史自由文本行：读不出档，但不许被折成"没有理由"
    row = {"stmt_id": "000004", "origin": "own_result", "kind": "conjecture",
           "label": "legacy", "statement_full": "夹具", "statement_text": "夹具",
           "proof_text": "", "evidence_kind": "heuristic", "status": "abandoned",
           "quote_verified": None,
           "quote_reason": "abandoned@2026-11-01T00:00:00+08:00@那时候的一句散文",
           "created_at": TS, "created_by": "test", "bits": {}}
    with st.tx("statements", actor="test") as tx:
        tx.upsert("statements", row)
    read = _abandoned(st)
    assert read["checked"] is True and read["count"] == 4, read
    assert read["abandon_kinds"] == {"math_error": 1, "difficulty": 0,
                                     "counterexample": 1, "space_too_large": 1}, read
    assert read["unstructured"] == 1, read
    assert read["relabeled"]["repeated"] == 1, read["relabeled"]
    assert read["relabeled"]["kinds"]["math_error"] == 1, read["relabeled"]
    assert read["relabeled"]["kinds"]["counterexample"] == 1, read["relabeled"]
    assert read["relabeled"]["kinds"]["space_too_large"] == 1, read["relabeled"]
    by_id = {row["stmt_id"]: row for row in read["rows"]}
    assert by_id["000002"]["experiment_id"] == "000001", by_id["000002"]
    assert by_id["000003"]["space"]["N_range"] == [2, 14], by_id["000003"]
    assert "按档" in read["reason"], read["reason"]


# ---------------------------------------------------------------- e 反真空

def test_e_removing_the_counterexample_check_makes_a_red(tmp_path, monkeypatch):
    """e：把 counterexample 档的证据校验摘掉 ⇒ 引一行不存在的实验也会"过"。"""
    real = SA._counterexample_refusal

    def _always_ok(store, eid, target):
        return {"experiment_id": eid}, "", ""

    monkeypatch.setattr(SA, "_counterexample_refusal", _always_ok)
    st = _ws(tmp_path)
    _put_statement(st)
    got = _abandon(st, SID, abandon_kind="counterexample",
                   abandon_basis="某个参数组让它为假", experiment_id="999999")
    assert got.get("checked") is True, (
        "反真空失效：摘掉证据校验之后仍然被拒 ⇒ 这条用例证明不了那道校验在起作用")
    monkeypatch.setattr(SA, "_counterexample_refusal", real)

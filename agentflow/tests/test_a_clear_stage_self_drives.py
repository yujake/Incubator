# -*- coding: utf-8 -*-
"""判据：A 的收尾是自驱的（清表 + 未消化理由），不靠模型再想起来补一步。

## 业主口径（2026-11-21，逐字）

    A 的 run_once 出口自驱清表（与 B 的 stage_two 同形）：每拍结束前查"有没有委托
    还有未终态候选"，有就自己 lit.admit_all 逐委托提交（幂等、留痕：清了几条 /
    哪个委托 / 归档在哪），回执点名；不许在任务上下文缺失时静默跳过，要写 why。

真机 `projects/lp-ball-15` 的现场（只读取证）：收工门 6 pass / 2 fail，其中一格是
`literature_pending` 的 `delegation_not_cleared` —— 委托 `r-000008` 的 6 行候选里
只有判收的 1 行有 `cleared_at`，另外 5 行判拒的既没有清表也没有归档（A 在
15:46:29 调 `lit.admit_all` 时 `slots` 只点名了判收的那 1 个槽，而清表作用域
就是"这一批覆盖的槽"）。`run_once` 的出口只读待裁行，判完但没清表的委托对它隐身。

## 这一份钉什么（a / b / c / d，每条都能单独红）

| # | 判据 | 反真空 / 改前读数 |
|---|---|---|
| a | 夹具：一个委托 6 行候选已裁完（判拒）、没有一行清过表 ⇒ `run_once` 出口自己 `lit.admit_all`：6 行都有 `cleared_at`、归档在盘上、回执点名"6 条 / 这个委托 / 归档在哪"；再跑一拍幂等（不重复提交） | 改前：`cleared_at` 全空、无归档、收工门 `delegation_not_cleared` 红 |
| b | 夹具：一条 `literature.processed=false` 但已是消化过的（2 statements + 1 relations 挂着），验收行没写 `unprocessed_reason` ⇒ `run_once` 出口给那一行自己写理由，收工门 C9 从 `fail` 变 `unknown`（不是 pass） | 改前：行上没有理由，C9 以 `acceptance_unmet` 红 |
| c | 正控：还有 2 条 `pending` ⇒ 仍然不许清表（不清、不归档，回执点名"还剩 2 条没判"） | 把闸关掉的话这一条会红 |
| d | 反真空：把 a / b 的自驱打桩成关 ⇒ a 的 `cleared_at` 与 b 的理由都必须复现改前的红 | —— |

零模型调用：夹具直接铺候选行 / 文献行 / 消化面，A 的 `run_once` 在空队列上跑一拍
（这正是真机现场的那个出口）。
"""
from __future__ import annotations

import json
import pathlib

import pytest

from agentflow import closing as CL
from agentflow import schema as S
from agentflow.agent_a import AgentA
from agentflow.agent_a import clear_stage as CS
from agentflow.store import Store

from conftest import TS, add_literature, add_relation, seed_statement_row, sync_counters

RID = "r-000008"
LIT_ID = "000018"


# ------------------------------------------------------------------ 夹具

def _agent(store: Store) -> AgentA:
    """空队列上的 A（真机 lp-ball-15 的下一拍就是这个出口：检索请求全 done）。"""
    return AgentA(store, providers=[], downloader=None,
                  config={"download": False, "lease_seconds": 900, "max_attempts": 3})


def _candidate(slot: str, status: str, request_id: str = RID) -> dict:
    """一行合法的候选（判拒的那一档带受控理由码 + 理由原文）。"""
    row = S.LitCandidate(
        slot=slot, batch=1, status=status, title=f"夹具候选 {slot}",
        request_id=request_id, provider="stub", year=2020, type_code="J",
        reason_code=("not_screened" if status == "rejected" else ""),
        reject_reason=("夹具：这一条判拒（没读到正文）" if status == "rejected" else ""),
        relevance=("与本次检索直接相关" if status in ("admitted", "qualified") else ""),
        lit_id=("000001" if status == "admitted" else None),
        added_at=TS,
    )
    row.validate()
    return row.to_dict()


def _seed_candidates(store: Store, statuses: list[str], request_id: str = RID) -> list[dict]:
    """铺一个委托的候选行（槽位号从 000000 起）。"""
    rows = [_candidate(f"{i:06d}", status, request_id=request_id)
            for i, status in enumerate(statuses)]
    with store.tx("lit_candidates", actor="test", note="fixture") as tx:
        for row in rows:
            tx.upsert("lit_candidates", row, note="fixture")
    sync_counters(store)
    return rows


def _seed_digested_literature(store: Store) -> dict:
    """一条"已经消化过、但 processed 仍为假"的文献行（B 手工登记的那一形）。"""
    add_literature(store, LIT_ID, title="q,k-Generalized Gamma and Beta Functions",
                   processed=False, path=None)
    for i in (0, 1):
        seed_statement_row(
            store, stmt_id=f"00014{7 + i}", kind="concept", origin="external_lit",
            statement_full=f"夹具概念 {i}", label=f"概念 {i}", source_lit_id=LIT_ID)
    add_relation(store, "000136", ["000147", "000148"], LIT_ID,
                 quote="Euler beta integral", quote_verified=True)
    return next(dict(r) for r in store.rows("literature") if r["lit_id"] == LIT_ID)


def _acceptance_file(store: Store, rows: list[dict]) -> pathlib.Path:
    path = pathlib.Path(store.root) / "out" / "paper" / "ACCEPTANCE-CHECKS.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"checks": rows}, ensure_ascii=False), encoding="utf-8")
    return path


def _close_row(maximum: int = 0, **extra) -> dict:
    row = {"id": "C9", "name": "闭：请求闭环（未闭环上限 0）",
           "kind": "unfinished_request_rows", "max": maximum}
    row.update(extra)
    return row


def _acceptance_gate(store: Store) -> CL.ClosingReport:
    """只跑 `acceptance` 那一格的现算（不需要报告 / 会话那两格）。"""
    rep = CL.ClosingReport()
    CL._check_acceptance(rep, store, ".")
    return rep


def _candidate_rows(store: Store, request_id: str = RID) -> list[dict]:
    return [dict(r) for r in store.rows("lit_candidates")
            if str(r.get("request_id") or "") == request_id]


# ============================================================ a 自驱清表

def test_a_run_once_submits_a_judged_but_uncleared_delegation(tmp_path: pathlib.Path) -> None:
    """a：6 行判完、没清表 ⇒ 出口自己提交；清表 + 归档 + 回执点名，第二拍幂等。"""
    store = Store(tmp_path / "ws")
    store.init()
    _seed_candidates(store, ["rejected"] * 6)

    # 改前读数（这一条的红点）：表里一行都没有 cleared_at，收工门那一格拦着。
    before = CL.ClosingReport()
    CL._check_literature_pending(before, store)
    assert before.status["literature_pending"] == "fail", before.to_dict()
    assert "delegation_not_cleared" in [f.code for f in before.findings], before.to_dict()

    res = _agent(store).run_once()
    stage = dict(res.clear_stage or {})
    assert stage.get("checked") is True, stage
    assert stage.get("enabled") is True, stage
    assert len(stage.get("cleared") or []) == 1, stage
    one = stage["cleared"][0]
    assert one["request_id"] == RID, one
    # 回执点名：清了几条 / 哪个委托 / 归档在哪。
    assert one["cleared"] == 6 and len(one["slots"]) == 6, one
    assert one["archive_rel_path"].endswith(f"archive-{RID}.jsonl"), one
    assert "清 6 条" in str(stage.get("note") or ""), stage.get("note")
    assert RID in str(stage.get("note") or ""), stage.get("note")

    rows = _candidate_rows(store)
    assert len(rows) == 6, rows
    assert all(str(r.get("cleared_at") or "").strip() for r in rows), rows
    archive = pathlib.Path(store.root) / one["archive_rel_path"]
    assert archive.is_file(), archive
    assert len([ln for ln in archive.read_text(encoding="utf-8").splitlines()
                if ln.strip()]) == 6, archive.read_text(encoding="utf-8")

    # 收工门那一格现在 pass（与真机现盘同一格）。
    after = CL.ClosingReport()
    CL._check_literature_pending(after, store)
    assert after.status["literature_pending"] == "pass", after.to_dict()

    # 幂等：同一批再跑一拍不再提交（那个委托已经在 settled 里）。
    again = dict(_agent(store).run_once().clear_stage or {})
    assert again.get("cleared") == [], again
    assert RID in (again.get("settled") or []), again


# ============================================================ b 自驱写未消化理由

def test_b_the_self_drive_writes_the_unprocessed_reason_on_the_row(
        tmp_path: pathlib.Path) -> None:
    """b：消化过、processed 仍为假、验收行没理由 ⇒ 自驱在行上写理由，C9 降 unknown。"""
    store = Store(tmp_path / "ws")
    store.init()
    lit_row = _seed_digested_literature(store)
    assert lit_row["processed"] is False, lit_row
    assert not str(lit_row.get("unprocessed_reason") or ""), lit_row
    _acceptance_file(store, [_close_row()])

    before = _acceptance_gate(store)
    assert before.status["acceptance"] == "fail", before.to_dict()
    codes = [f.code for f in before.findings if f.check == "acceptance"]
    assert "acceptance_unmet" in codes, before.to_dict()

    res = _agent(store).run_once()
    got = dict(res.unprocessed_reasons or {})
    assert got.get("checked") is True, got
    assert got.get("enabled") is True, got
    assert got.get("unprocessed") == 1, got
    assert [x["lit_id"] for x in got.get("written") or []] == [LIT_ID], got
    written = got["written"][0]
    assert written["statements"] == 2 and written["relations"] == 1, written
    assert LIT_ID in str(got.get("note") or ""), got.get("note")

    row = next(dict(r) for r in store.rows("literature") if r["lit_id"] == LIT_ID)
    reason = str(row.get("unprocessed_reason") or "")
    assert "statements" in reason and "relations" in reason, reason
    assert "2 条 statements" in reason and "1 条 relations" in reason, reason
    assert row["processed"] is False, "自驱不许替 B 翻 processed（那是 B 的证据位）"

    after = _acceptance_gate(store)
    assert after.status["acceptance"] == "unknown", after.to_dict()
    close = next(r for r in after.readings["acceptance"]["rows"] if r["id"] == "C9")
    assert close["state"] == "unknown" and close["ok"] is False, close
    assert close["detail"]["literature_unprocessed"] == 1, close["detail"]
    assert close["detail"]["unprocessed_reason_source"] == "literature_rows", close["detail"]
    assert "acceptance_unprocessed_carried" in [f.code for f in after.findings], after.to_dict()

    # 幂等：第二拍不覆盖已有理由。
    again = dict(_agent(store).run_once().unprocessed_reasons or {})
    assert again.get("written") == [], again
    assert [x["lit_id"] for x in again.get("kept") or []] == [LIT_ID], again


# ============================================================ c 正控：还没判完就不清

def test_c_a_delegation_with_pending_rows_is_never_cleared(tmp_path: pathlib.Path) -> None:
    """c：还有 2 条没判 ⇒ 这一拍不清表、不归档，回执点名还剩几条。"""
    store = Store(tmp_path / "ws")
    store.init()
    _seed_candidates(store, ["rejected"] * 4 + ["pending"] * 2)

    res = _agent(store).run_once()
    stage = dict(res.clear_stage or {})
    assert stage.get("checked") is True, stage
    assert stage.get("cleared") == [], stage
    assert len(stage.get("pending") or []) == 1, stage
    assert stage["pending"][0]["request_id"] == RID, stage["pending"][0]
    assert stage["pending"][0]["pending"] == 2, stage["pending"][0]
    assert "还剩 2 条没判" in str(stage.get("note") or ""), stage.get("note")

    rows = _candidate_rows(store)
    assert not any(str(r.get("cleared_at") or "").strip() for r in rows), rows
    archive = pathlib.Path(store.root) / "data" / "lit_candidates" / f"archive-{RID}.jsonl"
    assert not archive.is_file(), "还有没判的行却写了归档"
    # 待裁读数照旧：2 条（不是被这一格静默折成 0）。
    assert res.pending_total == 2, res.to_dict()


# ============================================================ d 反真空

def test_c2_a_refused_submit_is_written_down_not_silently_skipped(
        tmp_path: pathlib.Path) -> None:
    """c2：判收未注册的委托缺回读 ⇒ 自驱提交被受控拒，回执逐条写 why、不清表。"""
    store = Store(tmp_path / "ws")
    store.init()
    _seed_candidates(store, ["rejected"] * 5 + ["qualified"])

    res = _agent(store).run_once()
    stage = dict(res.clear_stage or {})
    assert stage.get("cleared") == [], stage
    assert len(stage.get("refused") or []) == 1, stage
    refused = stage["refused"][0]
    assert refused["request_id"] == RID, refused
    assert refused["kind"] == "no_readback", refused
    assert "回读" in str(refused.get("why") or ""), refused
    assert "r-000008" in str(stage.get("note") or ""), stage.get("note")
    assert "no_readback" in str(stage.get("note") or ""), stage.get("note")

    rows = _candidate_rows(store)
    assert not any(str(r.get("cleared_at") or "").strip() for r in rows), rows
    archive = pathlib.Path(store.root) / "data" / "lit_candidates" / f"archive-{RID}.jsonl"
    assert not archive.is_file(), "提交被受控拒却写了归档"


def test_d1_stubbing_the_clear_stage_drive_out_reproduces_the_red(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """d1：清表自驱打桩成关 ⇒ `cleared_at` 全空、归档不在、收工门那一格红。"""
    store = Store(tmp_path / "ws")
    store.init()
    _seed_candidates(store, ["rejected"] * 6)
    monkeypatch.setattr(CS, "_clear_stage_self_drive_enabled", lambda: False)

    res = _agent(store).run_once()
    stage = dict(res.clear_stage or {})
    assert stage.get("checked") is True, stage
    assert stage.get("enabled") is False, stage
    assert stage.get("cleared") == [], stage
    assert "反真空打桩" in str(stage.get("why") or ""), stage.get("why")

    rows = _candidate_rows(store)
    assert not any(str(r.get("cleared_at") or "").strip() for r in rows), rows
    archive = pathlib.Path(store.root) / "data" / "lit_candidates" / f"archive-{RID}.jsonl"
    assert not archive.is_file(), "自驱被打桩成关之后仍然清了表 ⇒ a 的读数不是这条自驱给的"
    rep = CL.ClosingReport()
    CL._check_literature_pending(rep, store)
    assert rep.status["literature_pending"] == "fail", rep.to_dict()
    assert "delegation_not_cleared" in [f.code for f in rep.findings], rep.to_dict()


def test_d2_stubbing_the_reason_drive_out_reproduces_the_red(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """d2：理由自驱打桩成关 ⇒ 行上没有理由，C9 仍以 `acceptance_unmet` 红。"""
    store = Store(tmp_path / "ws")
    store.init()
    _seed_digested_literature(store)
    _acceptance_file(store, [_close_row()])
    monkeypatch.setattr(CS, "_unprocessed_reason_self_drive_enabled", lambda: False)

    res = _agent(store).run_once()
    got = dict(res.unprocessed_reasons or {})
    assert got.get("checked") is True, got
    assert got.get("enabled") is False, got
    assert got.get("written") == [], got
    row = next(dict(r) for r in store.rows("literature") if r["lit_id"] == LIT_ID)
    assert not str(row.get("unprocessed_reason") or ""), row

    rep = _acceptance_gate(store)
    assert rep.status["acceptance"] == "fail", rep.to_dict()
    assert "acceptance_unmet" in [f.code for f in rep.findings], rep.to_dict()


if __name__ == "__main__":  # pragma: no cover - 手工复跑用
    raise SystemExit(pytest.main([__file__, "-q"]))

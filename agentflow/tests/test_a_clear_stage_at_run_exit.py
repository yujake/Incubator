# -*- coding: utf-8 -*-
"""判据：A 这一拍一次 `own.run_once` 都不调时，退场也会自己清表 / 写未消化理由。

## 为什么要有这一份（ACLEAR 的覆盖边界，2026-11-21）

ACLEAR 把"逐委托清表 + 未消化理由"的自驱挂在 `agent_a/run_once.py` 的三个出口上。
真机 `projects/lp-ball-15` 的 A 做了 221 步，`own.run_once` 被调了 0 次
（同文件里 B 是 23 次）：模型直接用 `lit.*` 工具把判收做完，于是那一份自驱一次都
没触发 —— `r-000003` / `r-000004` / `r-000008` 三个"判完没清表"的委托留到了收工门。
两格红（`literature_pending` 的 `delegation_not_cleared` + `acceptance` 的
`acceptance_unmet`）就是这么来的。

所以这一份钉的是另一条路：模型只用 `lit.*`，一拍结束（`agent_loop.run()` 退场）
时必须走同一份自驱（`agent_a/clear_stage.drive_at_run_exit`）。

## 这一份钉什么（a / b / c / d，每条都能单独红）

| # | 夹具 | 改后读数 |
|---|---|---|
| a | A 只用 `lit.stage_reject`（5 槽）+ `lit.admit`（1 槽）判完一个委托的 6 行，全程不调 `own.run_once` ⇒ 一拍退场后：6 行都有 `cleared_at`、归档在盘上、回执点名"清 6 条 / 注册 1 条 / 归档在哪"；收工门那一格 pass | 改前（d1）：判完但没清表、无归档，收工门 `delegation_not_cleared` 红 |
| b | A 只用 `lit.*`（`lit.stage_list` 回读）+ 一条"确实消化过、`processed` 仍为假"的文献行 ⇒ 一拍退场后那一行自己有了 `unprocessed_reason`，收工门 C9 从 `fail` 变 `unknown`（不是 pass） | 改前（d2）：行上没有理由，C9 `acceptance_unmet` 红 |
| c | 正控：4 行判拒 + 2 行 `pending` ⇒ 不清表、不归档，回执点名"还剩 2 条没判"（提交闸没被关掉） | 若把闸关掉，这一条会红 |
| d | 反真空：把 ② 的接线（`clear_stage.drive_at_run_exit`）打桩掉 ⇒ a / b 各自复现改前的红 | —— |

三条纪律：零模型调用（替身模型照剧本回答，走真实的工具层与循环）、真盘读数
（`cleared_at` / 归档 / 收工门现算，不读内存标志）、反真空（打桩掉接线，绿必须变红）。
"""
from __future__ import annotations

import json
import pathlib

import pytest

from agentflow import closing as CL
from agentflow import schema as S
from agentflow.agent_a import clear_stage as CS
from agentflow.agent_loop import run_role
from agentflow.conductor import Conductor
from agentflow.llmseam import LlmSeam
from agentflow.store import Store
from agentflow.tools import build_registry

from conftest import TS, lit_availability, lit_readback, sync_counters

RID = "r-000008"
LIT_ID = "000018"
SLOTS = [f"{i:06d}" for i in range(6)]


# ------------------------------------------------------------------ 替身模型

class ScriptedGateway:
    """照剧本回答的替身模型：每次 `complete` 取剧本里的下一条，取完就重复最后一条。"""

    spec = type("Spec", (), {"model": "scripted", "api_key": "fake"})()

    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)
        self.prompts: list[str] = []

    def complete(self, prompt: str, *, scope: str = "", system: str | None = None,
                 **kw: object) -> object:
        self.prompts.append(prompt)
        text = self.replies[min(len(self.prompts) - 1, len(self.replies) - 1)]
        return type("Reply", (), {"ok": True, "text": text, "tokens_in": 10,
                                  "tokens_out": 10, "error_detail": "",
                                  "error_kind": ""})()


# ------------------------------------------------------------------ 夹具

def _candidate(slot: str, status: str) -> dict:
    """一行合法的候选（判拒的那一档带受控理由码 + 理由原文）。"""
    row = S.LitCandidate(
        slot=slot, batch=1, status=status, title=f"夹具候选 {slot}",
        request_id=RID, provider="stub", year=2020, type_code="J",
        reason_code=("not_screened" if status == "rejected" else ""),
        reject_reason=("夹具：这一条判拒（与本次检索无关）" if status == "rejected" else ""),
        relevance=("与本次检索直接相关（夹具）" if status != "rejected" else ""),
        added_at=TS)
    row.validate()
    return row.to_dict()


def _seed_candidates(store: Store, statuses: list[str]) -> list[dict]:
    rows = [_candidate(slot, status) for slot, status in zip(SLOTS, statuses)]
    with store.tx("lit_candidates", actor="test", note="fixture") as tx:
        for row in rows:
            tx.upsert("lit_candidates", row, note="fixture")
    sync_counters(store)
    return rows


def _seed_digested_literature(store: Store) -> dict:
    """一条"已经消化过、但 processed 仍为假"的文献行（B 手工登记的那一形）。"""
    from conftest import add_literature, add_relation, seed_statement_row

    add_literature(store, LIT_ID, title="q,k-Generalized Gamma and Beta Functions",
                   processed=False, path=None)
    for i in (0, 1):
        seed_statement_row(
            store, stmt_id=f"00014{7 + i}", kind="concept", origin="external_lit",
            statement_full=f"夹具概念 {i}", label=f"概念 {i}", source_lit_id=LIT_ID)
    add_relation(store, "000136", ["000147", "000148"], LIT_ID,
                 quote="Euler beta integral", quote_verified=True)
    return next(dict(r) for r in store.rows("literature") if r["lit_id"] == LIT_ID)


def _acceptance_file(store: Store) -> pathlib.Path:
    path = pathlib.Path(store.root) / "out" / "paper" / "ACCEPTANCE-CHECKS.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"checks": [
        {"id": "C9", "name": "闭：请求闭环（未闭环上限 0）",
         "kind": "unfinished_request_rows", "max": 0}]}, ensure_ascii=False),
        encoding="utf-8")
    return path


def _acceptance_gate(store: Store) -> CL.ClosingReport:
    rep = CL.ClosingReport()
    CL._check_acceptance(rep, store, ".")
    return rep


def _literature_pending_gate(store: Store) -> CL.ClosingReport:
    rep = CL.ClosingReport()
    CL._check_literature_pending(rep, store)
    return rep


def _wired(tmp_path: pathlib.Path) -> tuple[Store, Conductor, object, pathlib.Path]:
    """一个空工作区 + 主控 + 工具层（与 `test_agent_loop._wired` 同形，只留 A 要的那几件）。"""
    root = tmp_path / "ws"
    store = Store(root)
    store.init()
    cond = Conductor(store, policy=None, backend=None)
    built = build_registry(store=store, conductor=cond, workspace_root=str(root),
                           session_root=str(root), sid="test-run")
    return store, cond, built.registry, root


def _run_a(store: Store, cond: Conductor, registry: object, root: pathlib.Path,
           replies: list[str], *, max_steps: int = 8) -> object:
    """跑 A 的一拍（零真模型：替身按剧本回答，工具全是真注册表里的实现）。"""
    seam = LlmSeam(role="A", session_root=root, gateway=ScriptedGateway(replies),
                   price=(0.0, 0.0), sid="test-run")
    return run_role("A", "审这一批待入库候选", store=store, registry=registry,
                    conductor=cond, seam=seam, session_root=root,
                    workspace_root=str(root), sid="test-run", max_steps=max_steps,
                    from_env=False)


def _reject_reply(slots: list[str]) -> str:
    return json.dumps({"tool": "lit.stage_reject",
                       "args": {"slots": slots, "reason_code": "rejected_off_topic",
                                "note": "夹具：与本次检索无关"}}, ensure_ascii=False)


def _admit_reply(slot: str) -> str:
    return json.dumps({"tool": "lit.admit",
                       "args": {"request_id": RID, "slots": [slot],
                                "items": [{"slot": slot, "availability": "readable"}]}},
                      ensure_ascii=False)


def _final_reply(text: str) -> str:
    return json.dumps({"final": text}, ensure_ascii=False)


def _no_run_once(run: object) -> None:
    """这一拍真的没调 `own.run_once`（否则测的还是 ACLEAR 那条路）。"""
    called = [str(step.payload.get("name") or "") for step in run.steps
              if step.shape == "tool"]
    assert called, "这一拍一个工具都没调 ⇒ 夹具没在测 lit.* 那条路"
    assert "own.run_once" not in called, called


def _rows(store: Store) -> list[dict]:
    return [dict(r) for r in store.rows("lit_candidates")
            if str(r.get("request_id") or "") == RID]


def _archive(store: Store) -> pathlib.Path:
    return pathlib.Path(store.root) / "data" / "lit_candidates" / f"archive-{RID}.jsonl"


# ============================================================ a 判完没清表 ⇒ 退场自清

def test_a_run_without_run_once_still_submits_the_judged_delegation(
        tmp_path: pathlib.Path) -> None:
    """a：6 行判完（5 判拒 + 1 判收）、没清过表 ⇒ 一拍退场自己提交：清表 + 归档 + 回执点名。"""
    store, cond, registry, root = _wired(tmp_path)
    _seed_candidates(store, ["pending"] * 6)
    lit_readback(registry.scoped_to("A"), RID)
    lit_availability(store, RID, SLOTS)

    run = _run_a(store, cond, registry, root, [
        _reject_reply(SLOTS[:5]),
        json.dumps({"tool": "fs.read", "args": {"path": "downloads/cand-000005.txt"}},
                   ensure_ascii=False),
        _admit_reply(SLOTS[5]),
        _final_reply("6 行判完（1 收 5 拒）"),
    ])
    _no_run_once(run)

    stage = dict(run.clear_stage or {})
    assert stage.get("checked") is True, stage
    assert stage.get("enabled") is True, stage
    assert len(stage.get("cleared") or []) == 1, stage
    one = stage["cleared"][0]
    assert one["request_id"] == RID, one
    assert one["cleared"] == 6 and one["registered"] == 1, one
    assert one["archive_rel_path"].endswith(f"archive-{RID}.jsonl"), one
    assert "清 6 条" in str(stage.get("note") or ""), stage.get("note")
    assert RID in str(stage.get("note") or ""), stage.get("note")
    # 回执跟着这一趟落盘（`runs/A-*.json` 的可复核面）。
    assert "收尾自驱" in "\n".join(run.notes), run.notes

    rows = _rows(store)
    assert len(rows) == 6, rows
    assert all(str(r.get("cleared_at") or "").strip() for r in rows), rows
    archive = pathlib.Path(store.root) / one["archive_rel_path"]
    assert archive.is_file(), archive
    assert len([ln for ln in archive.read_text(encoding="utf-8").splitlines()
                if ln.strip()]) == 6, archive.read_text(encoding="utf-8")

    after = _literature_pending_gate(store)
    assert after.status["literature_pending"] == "pass", after.to_dict()


# ============================================================ b 退场自写未消化理由

def test_b_run_without_run_once_still_writes_the_unprocessed_reason(
        tmp_path: pathlib.Path) -> None:
    """b：消化过、processed 仍为假、验收行没理由 ⇒ 一拍退场自己写理由，C9 降 unknown。"""
    store, cond, registry, root = _wired(tmp_path)
    _seed_digested_literature(store)
    _acceptance_file(store)

    before = _acceptance_gate(store)
    assert before.status["acceptance"] == "fail", before.to_dict()
    assert "acceptance_unmet" in [f.code for f in before.findings], before.to_dict()

    run = _run_a(store, cond, registry, root, [
        json.dumps({"tool": "lit.stage_list", "args": {}}, ensure_ascii=False),
        _final_reply("这一趟只回读了候选表"),
    ])
    _no_run_once(run)

    got = dict(run.unprocessed_reasons or {})
    assert got.get("checked") is True, got
    assert got.get("enabled") is True, got
    assert got.get("unprocessed") == 1, got
    assert [x["lit_id"] for x in got.get("written") or []] == [LIT_ID], got
    written = got["written"][0]
    assert written["statements"] == 2 and written["relations"] == 1, written

    row = next(dict(r) for r in store.rows("literature") if r["lit_id"] == LIT_ID)
    reason = str(row.get("unprocessed_reason") or "")
    assert "2 条 statements" in reason and "1 条 relations" in reason, reason
    assert row["processed"] is False, "自驱不许替 B 翻 processed（那是 B 的证据位）"

    after = _acceptance_gate(store)
    assert after.status["acceptance"] == "unknown", after.to_dict()
    close = next(r for r in after.readings["acceptance"]["rows"] if r["id"] == "C9")
    assert close["state"] == "unknown" and close["ok"] is False, close
    assert close["detail"]["unprocessed_reason_source"] == "literature_rows", close


# ============================================================ c 正控：还有 pending 就不清

def test_c_a_delegation_with_pending_rows_is_never_cleared_at_run_exit(
        tmp_path: pathlib.Path) -> None:
    """c：还有 2 条没判 ⇒ 这一拍不清表、不归档，回执点名还剩几条（闸没关掉）。"""
    store, cond, registry, root = _wired(tmp_path)
    _seed_candidates(store, ["pending"] * 6)
    lit_readback(registry.scoped_to("A"), RID)
    lit_availability(store, RID, SLOTS)

    run = _run_a(store, cond, registry, root, [
        _reject_reply(SLOTS[:4]),
        _final_reply("判了 4 条，还有 2 条没判"),
    ])
    _no_run_once(run)

    stage = dict(run.clear_stage or {})
    assert stage.get("checked") is True, stage
    assert stage.get("cleared") == [], stage
    assert len(stage.get("pending") or []) == 1, stage
    assert stage["pending"][0]["request_id"] == RID, stage["pending"][0]
    assert stage["pending"][0]["pending"] == 2, stage["pending"][0]
    assert "还剩 2 条没判" in str(stage.get("note") or ""), stage.get("note")

    rows = _rows(store)
    assert not any(str(r.get("cleared_at") or "").strip() for r in rows), rows
    assert not _archive(store).is_file(), "还有没判的行却写了归档"
    rep = _literature_pending_gate(store)
    assert rep.status["literature_pending"] == "fail", rep.to_dict()
    reading = rep.readings["literature_pending"]
    assert reading["pending"] == 2, reading
    groups = {str(g.get("request_id") or ""): int(g.get("pending") or 0)
              for g in reading["by_delegation"]}
    assert groups == {RID: 2}, reading


# ============================================================ d 反真空：打桩掉接线就红

def test_d1_stubbing_the_run_exit_wiring_reproduces_the_red_on_a(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """d1：把退场接线打桩成空操作 ⇒ a 的夹具复现真机那一形（判完、没清表、收工门红）。"""
    store, cond, registry, root = _wired(tmp_path)
    _seed_candidates(store, ["pending"] * 6)
    lit_readback(registry.scoped_to("A"), RID)
    lit_availability(store, RID, SLOTS)
    monkeypatch.setattr(CS, "drive_at_run_exit", lambda agent, run=None: {})

    run = _run_a(store, cond, registry, root, [
        _reject_reply(SLOTS[:5]),
        json.dumps({"tool": "fs.read", "args": {"path": "downloads/cand-000005.txt"}},
                   ensure_ascii=False),
        _admit_reply(SLOTS[5]),
        _final_reply("6 行判完（1 收 5 拒）"),
    ])
    _no_run_once(run)

    assert dict(run.clear_stage or {}) == {}, "接线被打桩掉之后 run.clear_stage 不该有读数"
    rows = _rows(store)
    # 判收那一条停在 `qualified`（判过、未注册：注册本来由提交时做），判拒的五条是终态。
    assert [r["status"] for r in rows] == ["rejected"] * 5 + ["qualified"], rows
    assert not any(str(r.get("cleared_at") or "").strip() for r in rows), rows
    assert not _archive(store).is_file(), "自驱被打桩成关之后仍然清了表 ⇒ a 的读数不是这条自驱给的"
    rep = _literature_pending_gate(store)
    assert rep.status["literature_pending"] == "fail", rep.to_dict()
    assert "delegation_not_cleared" in [f.code for f in rep.findings], rep.to_dict()


def test_d2_stubbing_the_run_exit_wiring_reproduces_the_red_on_b(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """d2：同上打桩 ⇒ b 的夹具复现改前：行上没有理由，C9 仍以 `acceptance_unmet` 红。"""
    store, cond, registry, root = _wired(tmp_path)
    _seed_digested_literature(store)
    _acceptance_file(store)
    monkeypatch.setattr(CS, "drive_at_run_exit", lambda agent, run=None: {})

    run = _run_a(store, cond, registry, root, [
        json.dumps({"tool": "lit.stage_list", "args": {}}, ensure_ascii=False),
        _final_reply("这一趟只回读了候选表"),
    ])
    _no_run_once(run)

    assert dict(run.unprocessed_reasons or {}) == {}, (
        "接线被打桩掉之后 run.unprocessed_reasons 不该有读数")
    row = next(dict(r) for r in store.rows("literature") if r["lit_id"] == LIT_ID)
    assert not str(row.get("unprocessed_reason") or ""), row
    rep = _acceptance_gate(store)
    assert rep.status["acceptance"] == "fail", rep.to_dict()
    assert "acceptance_unmet" in [f.code for f in rep.findings], rep.to_dict()


if __name__ == "__main__":  # pragma: no cover - 手工复跑用
    raise SystemExit(pytest.main([__file__, "-q"]))

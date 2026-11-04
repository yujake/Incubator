# -*- coding: utf-8 -*-
"""167 判据：B 登记的那一刻把"谁写的这份证明"记下来（业主 2026-11-01 裁定）。

## 为什么需要这一组

业主的口径是「F 写的证明，F 送审，F 拿到 V 签，B 侧收录」「不存在 F 写证明 B 送审」。
于是"送审者该不该是这个人"只能拿"作者是谁"来判 —— 而在这一笔之前，statements 行上
没有作者：81 的 8 条回执只能记成 `author_not_recorded`，运行期永远判不出替人送审。

## 三条判据

| # | 它要证明的事 | 它能怎么红 |
|---|---|---|
| 1 | 三种来源各一条 ⇒ `proof_authors` 分别 F / G / B | 路径规则只管 F ⇒ G/B 两条落空 |
| 2 | 读不出来源 ⇒ 不写这一格（`author_not_recorded`），不默认 B | 默认成 B ⇒ 这一格永远有值 |
| 3 | 落盘之后 V 的回执能判出"替人送审"，且回执仍投送审者 | 只写不读 ⇒ `submitter_is_not_author` 仍是 None |

## 边界

只加数据：不改 `bits`、不改收录行为、不改 `created_by`、`schema.Statement` 一个字段
未加（`proof_authors` 是行上的附加键，判据 4 钉住它能原样读回）。
"""
from __future__ import annotations

from conftest import TS

from agentflow import conductor as CND
from agentflow import evidencebits as EB
from agentflow import secretary as SEC
from agentflow import vreceipts as VRC
from agentflow import vsigns as VSP
from agentflow.tools.conductor_tools import conductor_for, reset_cache


def _sec(store) -> SEC.Secretary:
    return SEC.Secretary("B", root=store.root, store=store, enable_model=False)


def _payload(**kw) -> dict:
    base = dict(
        origin="own_result", kind="conjecture", label="探针引理",
        statement_full="若 n ≥ 3 则弦长函数不是常值。",
        statement_text="弦长函数不是常值",
        proof_text="1. 取 G = C_n：它是 2-正则、围长为 n。\n2. 由第 1 步直接得到结论。",
        evidence_kind="heuristic",
        quote_verified=None, quote_reason="自产命题：没有第二份文本可比对",
        # 生产里这一格由 B 的 `register_statement` 算好交来；直接调秘书的夹具带一份
        # 合法的 bits，正文闸才按"B 已经判过"那一档让路（`defer_without_sign`）。
        bits=EB.bits_of(origin="own_result", proof=True,
                        proof_process="1. 取 G = C_n：它是 2-正则、围长为 n。\n2. 由第 1 步直接得到结论。",
                        quote_verified=None, kind="conjecture"),
    )
    base.update(kw)
    return base


def _stmt(store, stmt_id: str) -> dict:
    return next(dict(r) for r in store.rows("statements")
                if str(r.get("stmt_id")) == stmt_id)


# ------------------------------------------------------------------ 1 三种来源

def test_three_source_families_are_recorded_as_f_g_b(store):
    """reports/ ⇒ F；out/paper/ ⇒ G；显式 proof_authors ⇒ B。"""
    sec = _sec(store)
    cases = [
        ("reports/blocks/block-01-continuation.md 第 325–331 行", None, "F"),
        ("out/paper/main.tex 第 978–1027 行", None, "G"),
        (None, ["B"], "B"),
    ]
    for label_range, explicit, want in cases:
        payload = _payload()
        if label_range:
            payload["line_range"] = {"start": 1, "end": 2, "label": label_range}
        if explicit is not None:
            payload["proof_authors"] = explicit
        got = sec.record_statement(payload, role="B", force_new=True)
        assert got.get("created") is True, got
        row = _stmt(store, got["stmt_id"])
        assert row.get("proof_authors") == [want], (want, row.get("proof_authors"), got)
        assert got["author_reading"]["author"] == want, got["author_reading"]


def test_a_backslash_path_is_recognised(store):
    """Windows 写法的来源路径照样认（同一套规则，不做第二份）。"""
    got = _sec(store).record_statement(
        _payload(line_range={"label": r"reports\drafts\block02-41-arithmetic.md 第 193–222 行"}),
        role="B")
    assert got.get("created") is True, got
    assert _stmt(store, got["stmt_id"]).get("proof_authors") == ["F"], got


# ------------------------------------------------------------------ 2 读不出来源

def test_an_unreadable_source_writes_no_author(store):
    """没有来源、没有显式作者 ⇒ 这一格不写（`author_not_recorded`），不猜。"""
    got = _sec(store).record_statement(_payload(), role="B")
    assert got.get("created") is True, got
    row = _stmt(store, got["stmt_id"])
    assert "proof_authors" not in row, row
    assert got["author_reading"]["checked"] is False, got["author_reading"]
    assert "不猜" in got["author_reading"]["reason"], got["author_reading"]
    # 读侧也不许把它折成"作者 = 送审者"。
    assert VRC.statement_author_of(store, f"{got['stmt_id']}#p1")["checked"] is False


# ------------------------------------------------------------------ 3 落盘之后能判

def test_the_recorded_author_makes_the_flag_work_end_to_end(store):
    """作者落盘之后：B 替 F 送审 ⇒ `submitter_is_not_author` 出现，回执仍投 B。"""
    sec = _sec(store)
    got = sec.record_statement(
        _payload(line_range={"label": "reports/blocks/block-01-continuation.md 第 325–331 行"}),
        role="B")
    assert got.get("created") is True, got
    sid = got["stmt_id"]
    a = VRC.statement_author_of(store, f"{sid}#p1")
    assert (a["checked"], a["author"], a["source"]) == (True, "F", "proof_authors"), a

    # 送审者 B 的台账号（真台账行；conductor 与生产同形）。
    reset_cache()
    cond = conductor_for(store)
    b_task = cond._write_new_row({
        "task_id": "", "role": "B", "action": "", "called_by": "M",
        "parent_task_id": "t-root", "depth": 2, "input_key": "@t:B:1",
        "status": "running", "outcome": None, "refusal_reason": None,
        "instance": "B#1", "detail": "探针", "error": None,
        "started_at": TS, "ended_at": None,
        "tokens": 0, "usd": 0.0, "artifacts": [], "inputs": [],
    }, note="probe:agent")

    # 台账那一行（回执的读侧从它来）。
    from agentflow import verifications as VR

    row = VR.record_verification(
        store.root, statement_id=sid,
        proof_text="1. 取 G = C_n：它是 2-正则、围长为 n。\n2. 由第 1 步直接得到结论。",
        verdict={"verdict": "有毛病", "defect_step": 2,
                 "findings": [{"level": "error", "step": 2, "kind": "无依据的步骤",
                               "detail": "第 2 步直接用了结论"}]},
        verifier="agent-V", store=store, proof_no=1)
    vid = str(row["verification_id"])
    detail = {
        "stmt_id": sid, "proof_no": 1, "label": f"{sid}#p1", "verdict": "有毛病",
        "unresolved_errors": 1, "verification_id": vid,
        "ledger": f"verifications/{sid}.jsonl", "steps": [2], "defect_step": 2,
        "finding": {"step": 2, "kind": "无依据的步骤", "detail": "第 2 步直接用了结论"},
        "in_sync": True, "proof_sha256": "", "washed": "", "via": "verdict",
    }
    with CND.calling_as("t-v1", "V", parent_task_id=b_task, parent_role="B"):
        out = VRC._publish(store=store, root=str(store.root), label=f"{sid}#p1",
                           verification_id=vid, recipient=b_task, role="B",
                           depth=2, detail=detail, at=TS,
                           author=VRC.statement_author_of(store, f"{sid}#p1"))
    assert out["submitter_is_not_author"] is True, out
    item = next(dict(r) for r in store.rows("tasks")
                if str(r.get("input_key") or "").startswith("v-verdict@"))
    assert str(item.get("parent_task_id")) == b_task, "回执被改投给了作者（F）"
    assert "替人送审" in str(item.get("detail") or ""), item.get("detail")
    assert VSP.receipt_digest(store.root, store)["submitter_is_not_author"] == 1


# ------------------------------------------------------------------ 4 附加键能读回

def test_proof_authors_survives_a_round_trip(store):
    """这一格不在 `schema.Statement` 的字段表里，但 upsert 之后能原样读回（不重冻 schema）。"""
    got = _sec(store).record_statement(
        _payload(line_range={"label": "reports/drafts/block02-41-arithmetic.md 第 1–9 行"}),
        role="B")
    row = _stmt(store, got["stmt_id"])
    assert row.get("proof_authors") == ["F"], row.get("proof_authors")
    # 再读一次（走读路径缓存）仍是同一份。
    assert _stmt(store, got["stmt_id"]).get("proof_authors") == ["F"]

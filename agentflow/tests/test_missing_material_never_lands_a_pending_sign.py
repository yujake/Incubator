# -*- coding: utf-8 -*-
"""判据 P0-1：「缺材料 ⇒ 成立」不许再产假证据（未在册那一支）。

## 现场（`draft/172` §三 P0-1，审计 R25 / R38 / R39–R42）

命题还没在册时，V 对穷举型证据走的是 `AgentV._review_without_statement`
（`agent_v/core.py`）：会审（`exhaustionreport.review`）跑完、结论原样交给
`verifications.record_pending_sign`。缺材料时会审给的是 `VERDICT_UNKNOWN`
（`看不出来`），而 `record_pending_sign` 内部过 `parse_verdict` —— 它把这一族措辞
折成 `verdict="成立"` ⇒ 一行「成立」写进 `verifications/pending/<sha>.jsonl`。

这是产假证据：盘上留下"V 判过成立"的正本行，而 V 实际上什么都没查成。
V 的冷启动逐字禁止这么做（`verifications.py:974-976`：缺材料 ⇒ 没查成、台账里不留行），
在册那一支也已经有护栏（`agent_v/core.py:629-647`，`checked=False` + `reason="missing_material"`），
只有未在册这一支漏了。

## 三条判据

| # | 它守什么 | 改前为什么红 |
|---|---|---|
| ① | 「未在册 + 缺材料」⇒ `verifications/pending/` 不新增行 | `record_pending_sign` 照样落一行，`verdict="成立"` |
| ② | 同一次调用返回 `checked=False`、`reason="missing_material"`，且 detail 点名缺哪一块 | 返回 `checked=True`、`verdict="成立"`、`signed_bit3=False` |
| ③ | 反真空：材料齐 + 判成立 ⇒ 照旧落 pending 行（`kind="numeric_evidence_unregistered"`） | —（这一条改前改后都绿；它挡的是"把这一档整个关掉"这种修法） |

①② 的护栏必须与在册那一支同一判据、同一文案：判据取 `ER.VERDICT_UNKNOWN`，
文案取同一条 detail 常量（`agent_v/core.py::_missing_material_detail`）。

全部用例在 `tmp_path` 里自建工作区，一个模型调用都不发（会审是机械七项）。
"""
from __future__ import annotations

import json
import pathlib

from conftest import add_literature  # noqa: E402

from agentflow import exhaustionreport as ER
from agentflow import schema as S
from agentflow import verifications as VR
from agentflow.agent_v import AgentV

#: 与 `test_d34_evidence_index_chain` 同一套真夹具（E 真跑一次穷举实验并落 ②③）。
from test_d34_evidence_index_chain import _run_exhaustive, _store  # noqa: E402

SID = S.format_id(0)


def _pending_files(store) -> list[pathlib.Path]:
    """`verifications/pending/` 下现存的 pending 台账文件（0 个 = 一行都没有）。"""
    base = pathlib.Path(store.root) / VR.VERIFICATIONS_DIR / VR.PENDING_DIR_NAME
    return sorted(base.glob("*.jsonl")) if base.is_dir() else []


def _missing_material_scene(tmp_path: pathlib.Path) -> tuple[object, dict]:
    """「未在册 + 缺材料」的现场：E 的穷举实验跑完、②③ 也落了，再把报告删掉。

    为什么要删报告而不是干脆不跑实验：报告落地之后"缺材料"才是只有一块缺的那种
    真实现场（缺的是报告本身，实验行与程序都还在）—— 这正是审计复现出来的那一条。
    """
    store = _store(tmp_path / "ws")
    add_literature(store, S.format_id(0))
    env = _run_exhaustive(store)
    report = pathlib.Path(store.root) / env["report_rel"]
    assert report.is_file(), f"夹具前提：报告得先落地（{env['report_rel']}）"
    report.unlink()
    assert list(store.rows("statements")) == [], "夹具前提：这一条命题还没在册"
    return store, env


# ------------------------------------------------------------------ ① + ②

def test_1_missing_material_lands_no_pending_row_and_says_so(tmp_path: pathlib.Path) -> None:
    """①② 未在册 + 缺材料 ⇒ pending 台账不新增行；返回 checked=False + 点名缺材料。

    两半各断一次（少一半这条判据就只是"它没写成立"）：
    ① 盘上：`verifications/pending/` 的文件与调用前逐字相同（改前这里多出 `<sha>.jsonl`）；
    ② 返回：`checked=False`、`reason="missing_material"`、`verdict` 里没有「成立」，
       且 detail 点名缺的那一块（不是一句"没查成"了事）。
    """
    store, env = _missing_material_scene(tmp_path)
    before = _pending_files(store)
    assert before == [], f"夹具前提：pending 台账一开始是空的（实际 {before}）"

    # 2026-11-08：V 只对手稿负责 ⇒ "未在册"由空命题号选支（不是"册里查不到"）。
    # 载体同样是 E 的按号手稿（`reports/e-proof-<实验号>.md`）；报告被删掉 ⇒ 缺材料。
    got = AgentV(store, workspace_root=store.root).verify_proof(
        "", proof_text=env["column"],
        proof_manuscript=ER.proof_manuscript_relpath(env["experiment_id"]))

    # ① pending 台账不新增行（这一条判据的原文）
    after = _pending_files(store)
    assert after == before, (
        f"缺材料却往 pending 台账落了行：{after}（改前的形态就是把「看不出来」"
        "经 parse_verdict 折成「成立」写进去）")
    rows, problems = VR.pending_rows(store.root)
    assert problems == [], problems
    assert rows == [], f"pending 台账里有行：{rows}"

    # ② 返回值的读数：没查成，且点名缺什么
    assert got["checked"] is False, got
    assert got["reason"] == "missing_material", got["reason"]
    assert got.get("verdict") in (None, ""), got.get("verdict")
    assert got.get("verdict") != "成立", "缺材料被写成了「成立」" + json.dumps(
        got, ensure_ascii=False, default=str)[:600]
    assert got.get("signed_bit3") is False, got
    detail = str(got.get("detail") or "")
    assert "缺材料" in detail, f"detail 没有点名「材料缺」：{detail!r}"
    assert "缺材料" in detail and ("报告" in detail or "落盘" in detail), detail
    # 会审的七项读数仍在（那是机械读数的正本；detail 里承诺了它在 exhaustion_review 里）
    reviewed = dict(got.get("exhaustion_review") or {})
    assert reviewed.get("missing"), reviewed
    assert str(reviewed.get("verdict") or "") == "看不出来", reviewed


# ------------------------------------------------------------------ ③ 反真空

def test_2_complete_material_is_reviewed_and_signed_without_a_statement_id(
        tmp_path: pathlib.Path) -> None:
    """③ 反真空：材料齐 + 判成立 ⇒ 会审照跑、三转三行 pending、签落稿上（没号也签）。

    2026-11-05 晚（业主）：「V 就不能假定有号，全签在稿上」—— `命题号=未在册` 是合法
    形态（真机 `f-proof-000019.md`）。这一条防两头：
    ① 护栏别把这一档整个关掉 —— 会审七项照跑、`verdict=成立`、pending 三行照落；
    ② 别把"审过"冒充成"三票齐全的签" —— 每一行都要有 `verification_id` / `at` /
       `proof_sha256`，签文件的 `passes` 就是那三行。
    """
    store = _store(tmp_path / "ws")
    add_literature(store, S.format_id(0))
    env = _run_exhaustive(store)
    assert _pending_files(store) == []

    got = AgentV(store, workspace_root=store.root).verify_proof(
        "", proof_text=env["column"],
        # 2026-11-04（业主裁定 甲）：E 的穷举证据要签，载体是 `reports/e-proof-<实验号>.md`
        # （`E.run_experiment` 的返回值里 `proof_manuscript` 就是这一格）。
        proof_manuscript=ER.proof_manuscript_relpath(env["experiment_id"]))

    assert got["checked"] is True, got
    assert got["kind"] == "proof_unregistered_signed", got
    assert got["verdict"] == "成立", got
    assert got["signed_bit3"] is False, got   # 没有命题行可翻
    # 会审的记录仍在（那是"审过"的证据）：pending 台账按对象 sha 落行，一转一行。
    landed = _pending_files(store)
    assert landed, "材料齐、会审判成立，却连会审记录都没有（护栏把这一档整个关掉了）"
    rows = [json.loads(ln) for ln in
            landed[0].read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(rows) == int(VR.SIGN_STREAK_NEED), rows
    for row in rows:
        assert row["verdict"] == "成立", row
        assert len(str(row.get("object_sha256") or "")) == 64, row
        for key in ("verification_id", "at", "proof_sha256"):
            assert str(row.get(key) or "").strip(), (key, row)
    # 签文件的三票就是那三行（不是三个空对象）。
    sign = json.loads(
        (pathlib.Path(store.root) / "out" / "vsigns" / f"{got['proof_sha256']}.json")
        .read_text(encoding="utf-8"))
    assert [p["verification_id"] for p in sign["passes"]] == [
        r["verification_id"] for r in rows], sign["passes"]
    assert sign["ledger"].startswith("verifications/pending/"), sign["ledger"]

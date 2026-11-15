# -*- coding: utf-8 -*-
"""D 的携带单收下「已提交、已签、尚未收录」的拿签稿（业主 2026-11-11 裁定 ①③）。

## 这一份判据钉什么

| # | 造什么 | 期望 |
|---|---|---|
| a | F 收工自动提交过一份拿签稿、B 还没收录 ⇒ 跑 `_carried_manuscripts` | 携带单里有一行 `mss:f-proof-<稿号>`（族在键里、地址 + 文件字节 sha256）；B 能按正文 sha 寻址到它 |
| b | 同一份稿已经收录（`statements` 行上 `manuscript_id` = 该稿号） | 仍然只上原来那一行（`stmt:<命题号>`），不因新增来源重复 |
| c | 反真空：把新增来源摘掉 | a 必须红（那一行不是恰好从别处来的） |

## 不新建表

新增来源只读 F 的 `tasks.artifacts` 里那条提交记号（`mss:<稿号>`，由
`agent_f.delivery` 定义 / 由 F 收工时框架写入），与 `statements` 行、手稿登记条目
三条来源共用同一张携带单。
"""
from __future__ import annotations

import pathlib

import pytest
from agentflow import depsection as DS
from agentflow import schema as S
from agentflow.agent_d import AgentD
from agentflow.store import Store

from conftest import seed_statement_row
from test_f_auto_submits_signed_manuscripts import (
    _close,
    _f,
    _plan_used_up,
    _signed_manuscript,
    _task,
    _ws,
)


def _d(st: Store) -> AgentD:
    return AgentD(st, config={"workspace_root": st.root})


def _submitted_manuscript(tmp_path: pathlib.Path) -> tuple[Store, AgentD, str]:
    """造一份「F 已收工自动提交、B 还没收录」的拿签稿。"""
    st = _ws(tmp_path)
    f = _f(st)
    _task(st)
    mid = "000000"
    rel = _signed_manuscript(st, mid)
    out = _close(f, _plan_used_up(f))
    assert out.get("auto_submitted_count") == 1, out
    assert str(out["auto_submitted"][0].get("manuscript_id")) == mid, out
    return st, _d(st), rel


def _rows_for(rows: list[dict], rel: str) -> list[dict]:
    return [dict(r) for r in rows if str(r.get("path") or "") == rel]


# ============================================================ a：未收录的拿签稿
def test_a_an_unfiled_signed_manuscript_reaches_the_carried_sheet(tmp_path):
    st, d, rel = _submitted_manuscript(tmp_path)
    rows, note = d._carried_manuscripts()
    mine = _rows_for(rows, rel)
    assert len(mine) == 1, (rows, note)
    one = mine[0]
    assert str(one.get("statement_id") or "") == "", one
    assert str(one.get("manuscript_id") or "") == "000000", one
    import hashlib

    blob = (pathlib.Path(st.root) / rel).read_bytes()
    assert one["sha256"] == hashlib.sha256(blob).hexdigest(), one
    # 渲染出来的携带单读得懂（`mss:` 是第三档键；键带族 —— 四族同号是常态）
    section = DS.render_carried_section(rows)
    assert f"| mss:f-proof-000000 | {rel} |" in section, section
    parsed = DS.carried_manuscripts(section)
    assert parsed["refused"] == "" and parsed["problems"] == [], parsed
    assert [r["manuscript_id"] for r in parsed["rows"]] == ["000000"], parsed
    assert [r["family"] for r in parsed["rows"]] == ["f-proof"], parsed


def test_a_b_can_address_it_by_the_proof_sha(tmp_path):
    """a 的后半：B 那侧按正文 sha 在携带单里寻址到这一份（号还不知道也能认）。"""
    st, d, rel = _submitted_manuscript(tmp_path)
    rows, _note = d._carried_manuscripts()
    report = pathlib.Path(st.root) / "reports" / "RESEARCH.md"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text("# D 的研究报告\n\n" + DS.render_carried_section(rows),
                      encoding="utf-8")
    text = pathlib.Path(st.root, rel).read_text(encoding="utf-8")
    body = DS.proof_body(text).strip("\n")
    got = DS.read_carried_manuscript(st.root, proof_text=body)
    assert got.get("source") == DS.SOURCE_CARRIED, got
    assert got.get("path") == rel, got
    assert got.get("matched_by") == "proof_sha", got
    assert DS.proof_body(str(got.get("text") or "")).strip("\n") == body, got


# ============================================================ b：已收录不重复
def test_b_an_already_filed_manuscript_still_rides_its_original_row(tmp_path):
    st, d, rel = _submitted_manuscript(tmp_path)
    text = pathlib.Path(st.root, rel).read_text(encoding="utf-8")
    body = DS.proof_body(text).strip("\n")
    seeded = seed_statement_row(
        st, proof_text=body, statement_full="设 f 在 [0,1] 上连续；则 f 一致连续。",
        statement_text="一致连续", kind="theorem", label="一致连续",
        origin="own_result", manuscript_id="000000")
    sid = str(seeded["stmt_id"])
    rows, _note = d._carried_manuscripts()
    mine = _rows_for(rows, rel)
    assert len(mine) == 1, ("同一份文件上了两行", rows)
    one = mine[0]
    assert str(one.get("statement_id") or "") == sid, one
    assert not str(one.get("manuscript_id") or ""), one


# ============================================================ c：反真空
def test_c_removing_the_new_source_turns_a_red(tmp_path, monkeypatch):
    st, d, rel = _submitted_manuscript(tmp_path)
    real = AgentD._auto_submitted_carried

    def _dropped(self, statements, known_stmt_ids):
        return [], ""

    monkeypatch.setattr(AgentD, "_auto_submitted_carried", _dropped)
    rows, _note = d._carried_manuscripts()
    assert _rows_for(rows, rel) == [], (
        "摘掉新增来源之后那一行还在 —— 它不是从 `tasks.artifacts` 那条记号来的", rows)


if __name__ == "__main__":          # pragma: no cover - 手工跑这一份时用
    raise SystemExit(pytest.main([__file__, "-q"]))

# -*- coding: utf-8 -*-
"""判据：命题行能指回它的稿，放弃命题 ⇒ 稿从活跃集消失（FIX186-C）。

## 现场（lp-ball-11，`draft/186` §4）

```text
stmt:000006 status=abandoned（合法：B 按 exp:000008 反例放弃，理由/时间/证据齐）
但它的数值稿 reports/e-num-000008.md 被 lifecycle.state_of_manuscript 读成 active
原因：000006 行上没有 manuscript_id / manuscripts，manuscriptretire 三源反查不到
```

## 判据

| # | 判据 | 改前红在哪 |
|---|---|---|
| a | `register_statement` 落库同笔写 `manuscript_id` / `manuscripts`（命题行能指回稿） | 改前只在"往在册行追加证明"那一笔写；新建那一笔不写 |
| b | 放弃这条命题之后，它的稿必须从活跃集消失；反真空：未放弃的仍活跃 | 改前 `state_of_manuscript` 读成 active |
| c | 「由命题反查」第四源：老行没有那两格时，`line_range.label = exp:<号>` ⇒ `reports/e-num-<号>.md`；只认这一条命名约定 | 改前三源全空 ⇒ 稿不在册，判据对它不说话 |
| d | 反真空：把第四源打桩掉 ⇒ 老行那份稿回到 active | 证明 c 的绿来自这一源 |

## 边界

`tmp_path` 工作区；不读写 `projects/`。真实副本上的复算见 `temp/fix186/judge_c_lp11.py`。
"""
from __future__ import annotations

import pathlib
import sys

import pytest

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import conftest                                    # noqa: E402
from agentflow import lifecycle as L               # noqa: E402
from agentflow import manuscriptretire as MR       # noqa: E402
from test_the_first_sign_before_registration_still_lifts_the_kind import (  # noqa: E402
    FULL, LABEL, MANUSCRIPT_ID, PROOF, _b, _manuscript, _pending_sign, _put, _row, _store,
)

ABANDON_MARK = "abandoned@2026-11-19T18:01:30+08:00@夹具：反例放弃（exp:000008）"


def _abandon(st: object, sid: str) -> None:
    """把一条命题改成「明确放弃」（写侧的唯一正路是秘书，夹具直接铺行）。"""
    with getattr(st, "tx")("statements", actor="test") as tx:
        row = dict(tx.find("statements", stmt_id=sid) or {})
        row["status"] = "abandoned"
        row["quote_reason"] = ABANDON_MARK
        tx.upsert("statements", row)


# ============================================================ a：登记同笔写两格
def test_a_registration_writes_the_manuscript_link_in_the_same_row(
        tmp_path: pathlib.Path) -> None:
    """a：新建那条命题的行上就有 `manuscript_id` / `manuscripts`（改前两格都空）。"""
    st = _store(tmp_path)
    rel, text = _manuscript()
    _put(st, rel, text)
    _pending_sign(st, rel=rel)
    filed = _b(st).register_statement(
        statement_full=FULL, statement_text=LABEL, label=LABEL,
        origin="own_result", derived_from=["999999"], kind="conjecture",
        doc_id="000000", line_range={"start": 1}, quote_verified=False,
        quote_reason="own_result：我方推导，没有第二份文本可比对",
        proof_text=PROOF, proof_manuscript=rel)
    assert filed.get("ok") is True, filed
    row = _row(st, str(filed.get("stmt_id") or ""))
    assert str(row.get("manuscript_id") or "") == MANUSCRIPT_ID, row
    assert dict(row.get("manuscripts") or {}) == {"1": rel}, row


# ============================================================ b：放弃 ⇒ 稿出活跃集
def test_b_abandoning_the_statement_takes_its_manuscript_out_of_the_active_set(
        tmp_path: pathlib.Path) -> None:
    """b：放弃命题 ⇒ 它的稿读成放弃；反真空：放弃之前它是活跃的。"""
    st = _store(tmp_path)
    rel, text = _manuscript()
    _put(st, rel, text)
    _pending_sign(st, rel=rel)
    filed = _b(st).register_statement(
        statement_full=FULL, statement_text=LABEL, label=LABEL,
        origin="own_result", derived_from=["999999"], kind="conjecture",
        doc_id="000000", line_range={"start": 1}, quote_verified=False,
        quote_reason="own_result：我方推导，没有第二份文本可比对",
        proof_text=PROOF, proof_manuscript=rel)
    sid = str(filed.get("stmt_id") or "")
    assert filed.get("ok") is True, filed

    before = L.state_of_manuscript(st, rel)
    assert before["checked"] is True and before["state"] == L.ACTIVE, before
    _abandon(st, sid)
    after = L.state_of_manuscript(st, rel)
    assert after["state"] == L.ABANDONED, after
    assert after["stmt_id"] == sid, after
    assert MR.retire_reading(st, rel)["retired"] is True, MR.retire_reading(st, rel)


# ============================================================ c：由命题反查（第四源）
def _seed_exp_statement(st: object, *, exp: str, status: str) -> str:
    """铺一条「E 的数值稿」形状的命题行：没有那两格，只有 `line_range.label=exp:<号>`。"""
    seeded = conftest.seed_statement_row(
        st, statement_full=f"夹具数值命题（exp:{exp}）。", kind="conjecture",
        status=status, quote_reason=(ABANDON_MARK if status == "abandoned"
                                     else "夹具：还没放弃"),
        line_range={"start": None, "end": None, "label": f"exp:{exp}"})
    return str(seeded["stmt_id"])


def _put_numeric(st: object, exp: str) -> str:
    rel = f"reports/e-num-{exp}.md"
    path = pathlib.Path(getattr(st, "root")) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"# 数值手稿（夹具 exp:{exp}）\n\n## 命题\n\n夹具。\n\n## 数值结果\n\n夹具。\n",
                    encoding="utf-8")
    return rel


def test_c_the_provenance_source_links_an_old_row_to_its_numeric_manuscript(
        tmp_path: pathlib.Path) -> None:
    """c：老行没有两格，但 `exp:<号>` ⇒ 它的数值稿读得出「所属命题」。"""
    st = _store(tmp_path)
    live_rel = _put_numeric(st, "000008")
    keep_rel = _put_numeric(st, "000009")
    live_sid = _seed_exp_statement(st, exp="000008", status="active")
    keep_sid = _seed_exp_statement(st, exp="000009", status="active")

    assert L.state_of_manuscript(st, live_rel)["state"] == L.ACTIVE
    assert L.state_of_manuscript(st, keep_rel)["state"] == L.ACTIVE
    _abandon(st, live_sid)
    assert L.state_of_manuscript(st, live_rel)["state"] == L.ABANDONED
    # 反真空：没放弃的那一条的稿仍活跃。
    assert L.state_of_manuscript(st, keep_rel)["state"] == L.ACTIVE
    assert MR.retire_reading(st, live_rel)["stmt_id"] == live_sid
    assert MR.retire_reading(st, keep_rel)["stmt_id"] == keep_sid


# ============================================================ d：反真空（第四源）
def test_d_without_the_provenance_source_the_old_row_manuscript_stays_active(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """d 反真空：把第四源打桩掉 ⇒ 老行那份稿回到「不在册」⇒ 仍然活跃。"""
    st = _store(tmp_path)
    rel = _put_numeric(st, "000008")
    sid = _seed_exp_statement(st, exp="000008", status="active")
    _abandon(st, sid)
    monkeypatch.setattr(MR, "_exp_id_of", lambda row: "")
    got = MR.statement_of_manuscript(st, rel=rel)
    assert got["found"] is False, got
    assert L.state_of_manuscript(st, rel)["state"] == L.ACTIVE


if __name__ == "__main__":          # pragma: no cover - 手工跑这一份时用
    raise SystemExit(pytest.main([__file__, "-q"]))


# -*- coding: utf-8 -*-
"""判据：在册命题那条分支也要升档，且与"新建同一条"逐字一致。

## 缺口（2026-11-04 已核实的两个缺口之一）

同一套代码两个分支结果不一致（真机读数：`stmt 000000`）：

- 命中在册 ⇒ `evidence_kind` 停在 `cross_check`、`kind` 停在 `conjecture`；
- 新建 ⇒ `kind=theorem`、`evidence_kind=proof`。

根因：`Secretary._upgrade_evidence_kind` 判"该不该升档"时只读
`verifications.proof_review_gap`（签名台账 `verifications/<命题号>.jsonl`），
而 E 这一签在"手稿签块 + pending 台账"里 ⇒ 读不到。于是"先落成猜想、再交签过的
证明"这条正路在秘书这一层断了：新建那一笔能叫定理，补交那一笔永远停在猜想。

## 判据

| # | 判据 | 改前为什么红 |
|---|---|---|
| e | 在册命题 + 带 V 签的手稿交付 ⇒ `kind` / `evidence_kind` 与"新建同一份"逐字相同（都是 `theorem` / `proof`） | 在册那一支只读签名台账 ⇒ `conjecture` / `cross_check` |
| f | 反真空：把升档的三路凭据全打桩成"没签"（手稿签块 / `bits.reviewed` ＋ 台账 / pending）⇒ e 必须回落到 `cross_check` / `conjecture` | 没有那一支可打桩（`AttributeError`）⇒ 先红 |
| g | negative：手稿没签 ⇒ 两边都不升档（不许因为"命中在册"就升） | 绿（负控）：这一条守的是新支不许把"有稿"读成"签过" |

## 口径

`Secretary._upgrade_evidence_kind` 读三路凭据，命中任一路即升到该有的档
（与新建分支算出来的 kind / evidence_kind 一致）：

1. `verifications.proof_review_gap`（既有那一路：签名台账）；
2. 手稿签块 `vsigns.manuscript_sign_standing(手稿正文, proof_sha=证明栏)`；
3. `bits.reviewed`（B 这一笔按正文 sha 认到的签，逐份记在
   `bits.evidence.reviewed_by_proof[证明号]`）。

2 与 3 同源（B 的 `bits.reviewed` 正是从手稿签块认出来的），所以它们由同一个
读数函数 `_manuscript_upgrade_basis` 给出。反真空打桩的是这三路全部：B 的预写那一格
与秘书同口径（任一路命中即可升档），只摘 2/3 时 1 照样能把档位顶上去（判据
`test_f_...` 的打桩点因此跟着判据走，断言的强度不变）。

全部用例在 `tmp_path` 里自建工作区；V 的穷举会审是机械七项 ⇒ 零模型调用。
"""
from __future__ import annotations

import pathlib
import sys

import pytest

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agentflow import schema as S  # noqa: E402
from agentflow import secretary as SEC  # noqa: E402
from agentflow import verifications as VR  # noqa: E402

from test_e_gets_its_v_sign_like_f import (  # noqa: E402
    FULL, _column, _env, _manuscript, _register, _submitted_by_e,
)


def _row(env: dict) -> dict:
    rows = [dict(r) for r in env["store"].rows("statements")]
    assert len(rows) == 1, rows
    return rows[0]


def _register_conjecture(env: dict) -> str:
    """先在册一条"证明还空着"的同一条命题（缺口读数里那个 `stmt 000000` 的现场）。"""
    first = env["b"].register_statement(
        origin="own_result", kind="conjecture", label="R(3,4)=9",
        statement_full=FULL, statement_text="R(3,4)=9", proof_text="",
        evidence_kind="cross_check", doc_id=S.format_id(0),
        line_range={"start": 1}, quote_verified=False,
        quote_reason="own_result：我方推导")
    assert first.get("ok") is True, first
    return str(first.get("stmt_id") or "")


def _signed_delivery(env: dict) -> tuple[str, str]:
    """E 的稿先拿 V 签（未在册那一路），再读回盘上那份带签块的全文。"""
    rel, _before = _manuscript(env)
    with _submitted_by_e():
        got = env["v"].verify_proof(proof_manuscript=rel)
    assert got.get("kind") == "proof_unregistered_signed", got
    text = (pathlib.Path(env["store"].root) / rel).read_text(encoding="utf-8")
    return rel, text


# ============================================================ e 在册 = 新建
def test_e_the_registered_branch_upgrades_to_the_new_row_result(
        tmp_path: pathlib.Path) -> None:
    """e：在册命题 + 带 V 签的手稿交付 ⇒ kind / evidence_kind 与新建逐字相同。"""
    # ---- 新建（对照）：同一份签字稿，直接落成一行 ----
    fresh_env = _env(tmp_path / "fresh")
    _rel_f, fresh_text = _signed_delivery(fresh_env)
    fresh = _register(fresh_env, text=fresh_text, column=_column(fresh_env))
    assert fresh.get("ok") is True, fresh
    fresh_row = _row(fresh_env)
    fresh_pair = (str(fresh_row.get("kind") or ""),
                  str(fresh_row.get("evidence_kind") or ""))
    assert fresh_pair == ("theorem", "proof"), fresh_pair

    # ---- 在册（本案）：先落成猜想、证明空着，再交同一份签字稿 ----
    env = _env(tmp_path / "registered")
    sid = _register_conjecture(env)
    _rel_r, text = _signed_delivery(env)
    filed = _register(env, text=text, column=_column(env))
    assert filed.get("ok") is True, filed
    assert str(filed.get("stmt_id") or "") == sid, filed
    row = _row(env)
    pair = (str(row.get("kind") or ""), str(row.get("evidence_kind") or ""))
    assert pair == fresh_pair, (
        f"在册那一支是 {pair}，新建那一支是 {fresh_pair} —— 同一套代码两个结果")


# ============================================================ f 反真空
def _no_gap(*_a, **_kw) -> dict:
    """`verifications.proof_review_gap` 的"没有凭据"读数（台账 / pending 那一支不存在）。"""
    return {"ok": False, "checked": True, "why": "打桩：台账 / pending 那一支不存在",
            "state": "unsigned", "verification_id": "", "ledger": "",
            "sha_matches": None, "proof_no": None, "rows": 0,
            "problems": [], "checklist": []}


def test_f_stubbing_the_manuscript_evidence_falls_back_to_conjecture(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """f：把升档的三路凭据全打桩成"没签"（手稿签块 / `bits.reviewed` ＋ 台账 /
    pending）⇒ e 回落到猜想 / cross_check。

    2026-11-05 补：B 的预写那一格改成与秘书同口径（三路任一路命中）之后，只摘手稿
    那一支不再足以让 e 回落 —— 这份交付的 pending 台账里也有一签。反真空的打桩点
    跟着判据走：两路全摘；断言与 e 同一组，一个字没放宽。
    """
    def _absent(**kw):
        return {"checked": True, "signed": False, "basis": "",
                "why": "打桩：这一支不存在", "manuscript": {}}

    monkeypatch.setattr(SEC, "_manuscript_upgrade_basis", _absent)
    monkeypatch.setattr(VR, "proof_review_gap", _no_gap)

    # 在册那一支：签过的稿也升不上去（回落）
    env = _env(tmp_path / "registered")
    _register_conjecture(env)
    _rel, text = _signed_delivery(env)
    filed = _register(env, text=text, column=_column(env))
    assert filed.get("ok") is True, filed
    row = _row(env)
    assert (str(row.get("kind") or ""),
            str(row.get("evidence_kind") or "")) == ("conjecture", "cross_check"), (
        row.get("kind"), row.get("evidence_kind"))

    # 新建那一支不受影响（同一份稿仍然叫定理、proof）—— 于是"回落"只落在在册那一支
    fresh_env = _env(tmp_path / "fresh")
    _rel_f, fresh_text = _signed_delivery(fresh_env)
    fresh = _register(fresh_env, text=fresh_text, column=_column(fresh_env))
    assert fresh.get("ok") is True, fresh
    fresh_row = _row(fresh_env)
    assert (str(fresh_row.get("kind") or ""),
            str(fresh_row.get("evidence_kind") or "")) == ("theorem", "proof")


# ============================================================ g negative
def test_g_an_unsigned_manuscript_upgrades_neither_branch(
        tmp_path: pathlib.Path) -> None:
    """g：手稿没签 ⇒ 两边都不升档（"命中在册"不是升档凭据）。"""
    # 在册：先落猜想，再交一份没签的稿
    env = _env(tmp_path / "registered")
    _register_conjecture(env)
    rel, _before = _manuscript(env)
    unsigned = (pathlib.Path(env["store"].root) / rel).read_text(encoding="utf-8")
    filed = _register(env, text=unsigned, column=_column(env))
    assert filed.get("ok") is False, filed
    # 拒在哪一道闸都行（第三方签字闸 / 无签闸），关键是"这一笔没有落盘、没有升档"。
    assert filed.get("kind") in ("proof_without_v_sign",
                                 "proof_needs_third_party_signature"), filed
    row = _row(env)
    assert (str(row.get("kind") or ""),
            str(row.get("evidence_kind") or "")) == ("conjecture", "cross_check"), (
        "没签的交付把在册那一行升档了 —— 命中在册不是升档凭据")

    # 新建：同一份没签的稿也进不了台账（两边一致）
    fresh_env = _env(tmp_path / "fresh")
    rel_f, _before_f = _manuscript(fresh_env)
    unsigned_f = (pathlib.Path(fresh_env["store"].root) / rel_f).read_text(encoding="utf-8")
    fresh = _register(fresh_env, text=unsigned_f, column=_column(fresh_env))
    assert fresh.get("ok") is False, fresh
    assert fresh.get("kind") in ("proof_without_v_sign",
                                 "proof_needs_third_party_signature"), fresh
    assert [dict(r) for r in fresh_env["store"].rows("statements")] == [], (
        "没签的那一份不该落成命题行")


if __name__ == "__main__":          # pragma: no cover - 手工跑这一份时用
    raise SystemExit(pytest.main([__file__, "-q"]))

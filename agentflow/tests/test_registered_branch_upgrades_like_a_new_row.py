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
from agentflow.store import Store  # noqa: E402

from conftest import seed_statement_row  # noqa: E402
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


def _signed_delivery(env: dict, sid: str = "") -> tuple[str, str, str]:
    """E 的稿在在册那一支拿 V 签（2026-11-05：没有命题号就没有可签的对象）。

    改前这里走"未在册"那一路（不给 `statement_id`），签块由 V 直接落进稿；2026-11-05
    之后那条路不产签 —— 所以这一格先把命题号准备好（不给就铺一行，等价于"新建那一行
    的盘上状态"），再带号送审。返回 `(sid, rel, 带签块的稿全文)`。
    """
    if not str(sid or "").strip():
        seeded = seed_statement_row(
            env["store"], proof_text="", statement_full=FULL,
            statement_text="R(3,4)=9", kind="conjecture", label="R(3,4)=9",
            origin="own_result", evidence_kind="cross_check", bits={})
        sid = str(seeded["stmt_id"])
    rel, _before = _manuscript(env)
    with _submitted_by_e():
        for _ in range(int(VR.SIGN_STREAK_NEED)):
            env["v"].verify_proof(sid, proof_manuscript=rel)
    text = (pathlib.Path(env["store"].root) / rel).read_text(encoding="utf-8")
    return sid, rel, text


# ============================================================ e 在册（无模型缝）
def test_e_the_registered_branch_does_not_sign_without_a_review_seam(
        tmp_path: pathlib.Path) -> None:
    """e：在册的穷举题要"按写成后的样子重读"⇒ 没有模型缝就 `judge_not_wired`。

    改前这一条量的是"在册分支与新建分支结果一致"，而它的现场靠的是未在册那一签
    （V 直接把块落进稿）。2026-11-05（业主）之后未在册不产签，在册这一支就必须自己
    走模型会审 —— 这套夹具（`_env`）没有给 V 模型缝，于是它只到"没查成"：

      - 台账一行都不落（"没查成"不许冒充"审过了"）；
      - 签文件没有、稿上没有签块、档位停在 `cross_check`（没有签就没有升档）；
      - 拒绝码是 `judge_not_wired`，不是静默通过。

    这不是把判据放宽：同一组断言在"有模型缝、三转成立"那一档由
    `tests/test_sign_integrity_gates.py::test_g` 正向量着（prose 在册那一支）。
    """
    env = _env(tmp_path / "registered")
    sid = _register_conjecture(env)
    # 2026-11-08（V 只对手稿负责）：穷举判据改成"看稿里 `## 证明` 的写法"，不再看册里的
    # 证明栏。这一条要量的是"散文在册支没有模型缝 ⇒ 没查成"，所以给它一份散文稿；
    # 穷举稿在无模型缝下是机械可审的（`test_agent_v_exhaustion_review` 正向钉着）。
    from _proof_manuscript_fixture import write_proof_manuscript

    rel = write_proof_manuscript(
        env["store"].root, sid,
        "1. 由定义直接得到。\n2. 于是结论成立。", statement_full=FULL)
    with _submitted_by_e():
        got = env["v"].verify_proof(sid, proof_manuscript=rel)

    assert got.get("checked") is False, got
    assert str(got.get("reason") or "").startswith("judge_not_wired"), got
    rows, _bad = VR.list_verifications(env["store"].root, statement_id=sid, limit=None)
    assert rows == [], rows
    row = _row(env)
    assert (str(row.get("kind") or ""),
            str(row.get("evidence_kind") or "")) == ("conjecture", "cross_check"), row
    text = (pathlib.Path(env["store"].root) / rel).read_text(encoding="utf-8")
    assert "V 签" not in text, text


# ============================================================ f 反真空
def test_f_an_unsigned_delivery_never_upgrades(tmp_path: pathlib.Path) -> None:
    """f：没有签的交付 ⇒ 在册那一支一个字节都不升（负控；"命中在册"不是凭据）。

    改前 f 打桩的是升档的"三路凭据"；2026-11-05 之后那一组凭据的前提是"手稿上有一块
    签"，而未在册不产签 ⇒ 打桩点改成更硬的一件：根本没有签。这一条与 e 互为反真空：
    e 说"没缝 ⇒ 不产签、不升档"，f 说"没签 ⇒ 不升档"（哪怕正文逐字相同、命题在册）。
    """
    env = _env(tmp_path / "registered")
    sid = _register_conjecture(env)
    rel, _before = _manuscript(env)
    unsigned = (pathlib.Path(env["store"].root) / rel).read_text(encoding="utf-8")
    filed = env["b"].register_statement(
        origin="own_result", kind="theorem", label="R(3,4)=9",
        statement_full=FULL, statement_text="R(3,4)=9", proof_text=_column(env),
        proof_manuscript=unsigned, evidence_kind="proof", doc_id=S.format_id(0),
        line_range={"start": 1}, quote_verified=False,
        quote_reason="own_result：我方推导")
    assert filed.get("ok") is False, filed
    assert filed.get("kind") in ("proof_without_v_sign",
                                 "proof_needs_third_party_signature"), filed
    row = _row(env)
    assert (str(row.get("kind") or ""),
            str(row.get("evidence_kind") or "")) == ("conjecture", "cross_check"), row


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

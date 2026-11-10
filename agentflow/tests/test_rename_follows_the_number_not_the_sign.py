# -*- coding: utf-8 -*-
"""稿号是稿号：收录不改名（p272 改写；原判据钉的是已停用的「拿到命题号就改名」）。

## 改前 → 改后

改前（业主 2026-11-04）：「登记成功（拿到命题号）就改名」—— 判据钉的是
`publish_manuscript` 把 `f-proof-plan-<计划>.md` 改名成 `f-proof-<命题号>.md`。
2026-11-10 业主裁定：「F 的稿自己维护一套号源，不依赖命题号和计划号。停掉错误的口径。」
⇒ 改名这一笔整段停用；同一份稿从写到收录始终叫 `reports/f-proof-<稿号>.md`。

## 这一份钉什么（强度不降）

| # | 判据 |
|---|---|
| a | `publish_manuscript` 收不到命题号（签名里没有那一格，递进去是 `TypeError`）、也不改名（`published=False`、`path` 原样、`why` 说清） |
| a2 | F 的登记条目落在 `f-proof-<稿号>.md`；B 收录拿到命题号之后盘上仍只有这一份、名字不变 |
| b | 同一份正文的 V 签块在收录前后仍认得上（按正文 sha，不按号） |
| c | 盘上只有稿名的稿（没有签）读成「未签」，不冒充已签 |
| d | 未签的草稿不许覆盖已签的那一版（`target_holds_a_signed_version`，零写入） |

零模型调用。
"""
from __future__ import annotations

import pathlib

import pytest

from agentflow import depsection as DS
from agentflow import proofregistry as PR
from agentflow import vsigns as VS
from agentflow.agent_b import AgentB
from agentflow.agent_f import AgentF
from agentflow.store import Store

MANUSCRIPT_DIR = "reports"
MID = "000123"
SID = "000001"
STATEMENT = "若 n 为大于 2 的整数，则 n 与 n+2 不能同时为素数。"
PROOF = "1. 反设两者都是素数（前提）\n2. 由整除性推出矛盾（前提）"


def _f(store: Store) -> AgentF:
    return AgentF(store, config={"workspace_root": store.root})


def _round(store: Store) -> dict:
    got = _f(store).proof_manuscript(
        {"product": "proof", "strategy": "反证", "why_strategy": "由整除性",
         "steps": [{"n": 1, "text": "反设两者都是素数", "cites": []},
                   {"n": 2, "text": "由整除性推出矛盾", "cites": []}]},
        sg={"sid": "s1", "text": STATEMENT, "testable": ""},
        plan={"plan_id": "000004"}, manuscript_id=MID, label="夹具", proof_no=1)
    assert got.get("ok") is True, got
    return got


def _read(store: Store, rel: str) -> str:
    return (pathlib.Path(store.root) / rel).read_text(encoding="utf-8")


# ------------------------------------------------------------------ a 不改名

def test_a_publish_never_renames(store: Store) -> None:
    """a：拿到命题号也不改名（`published=False`、path 原样）。

    2026-11-10 第二刀把这一条从"拿到号也不改名"升成"根本收不到号"：
    `publish_manuscript` 的签名里没有 `statement_id`，递进去是 `TypeError`。
    """
    got = _round(store)
    out = _f(store).publish_manuscript(got, manuscript_id=MID)
    assert out.get("published") is False, out
    assert out.get("path") == got["path"], out
    assert str(out.get("renamed_from") or "") == "", out
    assert "不改稿名" in str(out.get("why") or ""), out
    with pytest.raises(TypeError):
        _f(store).publish_manuscript(got, statement_id=SID)


# ------------------------------------------------------------------ a2 收录不改名

def test_a2_f_registration_lands_an_entry_and_b_does_not_rename_it(store: Store) -> None:
    """a2：登记条目在稿号上；B 收录拿到命题号之后名字一个字不动。"""
    from conftest import sign_before_registration

    got = _round(store)
    rel = str(got["path"])
    assert rel == f"{MANUSCRIPT_DIR}/f-proof-{MID}.md", got
    # F 的登记条目（与 `F.step` 同一笔；这里用同一条写口，gate 打桩成"形态合规"）
    landed = PR.register_or_rewrite(
        store.root, family="F", label="夹具", proposition=STATEMENT,
        proof_text=PROOF, statement_id="", plan_id="000004", sid="s1",
        manuscript_id=MID, kind="conjecture", template=_read(store, rel),
        gate=lambda **_kw: {"checked": True, "well_formed": True,
                            "submittable": True, "problems": [],
                            "refused": "", "reason": "夹具：形态合规"})
    assert landed.get("ok") is True, landed
    entry = PR.parse_entry(_read(store, rel))
    assert entry.get("checked") is True, entry

    body = DS.proof_body(_read(store, rel)).strip("\n")
    sign_before_registration(store.root, proof_text=body)
    out = AgentB(store, extractor=None, extract_text=None).register_statement(
        statement_full=STATEMENT, statement_text=STATEMENT[:20], origin="own_result",
        kind="conjecture", label="夹具", proof_text=body, proof_manuscript=rel,
        evidence_kind="heuristic", line_range={"label": rel},
        quote_reason="夹具：稿号是稿号")
    assert out.get("ok") is True, out
    # 收录之后：同一份稿还在原路径；没有按命题号命名的第二份
    assert (pathlib.Path(store.root) / rel).is_file(), rel
    assert not (pathlib.Path(store.root) / f"{MANUSCRIPT_DIR}/f-proof-{out['stmt_id']}.md").exists(), (
        "收录按命题号改名了 ⇒ 停用的口径回来了")
    row = next(dict(r) for r in store.rows("statements")
               if str(r.get("stmt_id")) == str(out["stmt_id"]))
    assert str(row.get("manuscript_id") or "") == MID, row


# ------------------------------------------------------------------ b 签按 sha

def test_b_the_sign_still_matches_after_collection(store: Store) -> None:
    """b：签块按正文 sha 认 —— 收录前后是同一份正文，签仍然成立。"""
    from conftest import sign_before_registration

    got = _round(store)
    rel = str(got["path"])
    body = DS.proof_body(_read(store, rel)).strip("\n")
    sign_before_registration(store.root, proof_text=body)
    out = AgentB(store, extractor=None, extract_text=None).register_statement(
        statement_full=STATEMENT, statement_text=STATEMENT[:20], origin="own_result",
        kind="conjecture", label="夹具", proof_text=body, proof_manuscript=rel,
        evidence_kind="heuristic", line_range={"label": rel},
        quote_reason="夹具：签按 sha")
    assert out.get("ok") is True, out
    v_sign = dict(out.get("v_sign") or {})
    assert v_sign.get("checked") is True, v_sign
    assert v_sign.get("found") is True and v_sign.get("applied") is True, v_sign


# ------------------------------------------------------------------ c 没签就是没签

def test_c_a_numbered_manuscript_without_a_sign_reads_unsigned(store: Store) -> None:
    """c：盘上有稿、没有签 ⇒ 读「未签」，不冒充已签。"""
    got = _round(store)
    rel = str(got["path"])
    reading = VS.manuscript_sign_reading(_read(store, rel), manuscript_path=rel)
    assert reading.get("found") is False, reading
    assert reading.get("signed") is False, reading


# ------------------------------------------------------------------ d 不覆盖已签版

def test_d_an_unsigned_draft_does_not_overwrite_a_signed_version(store: Store) -> None:
    """d：目标名上签住的是另一版正文 ⇒ 受控拒、零写入（不毁签）。"""
    got = _round(store)
    rel = str(got["path"])
    signed = (pathlib.Path(store.root) / rel).read_text(encoding="utf-8")
    # 这一份就是签住的那一版（块盖的是它自己的 `## 证明`）
    stamped = VS.stamp_manuscript_sign(
        signed, proof_sha=PR.proof_sha(PROOF), streak=3, need=3, verdict="成立",
        at="2026-11-10T00:00:00+08:00", ledger="verifications/pending/x.jsonl#v-000001",
        statement_id="", manuscript_id=MID)
    (pathlib.Path(store.root) / rel).write_text(stamped, encoding="utf-8")

    # 另一版正文（没有为它签过）想覆盖同一个名字
    new_text = stamped.replace(PROOF, "1. 另一版正文（前提）\n2. 结论（前提）")
    assert new_text != stamped

    from agentflow import manuscriptform as MF

    out = MF.commit_manuscript(store.root, family="F", text=new_text,
                               manuscript_id=MID, retitle="none")
    assert out.get("ok") is False, out
    assert out.get("refused") == "target_holds_a_signed_version", out
    assert (pathlib.Path(store.root) / rel).read_text(encoding="utf-8") == stamped, (
        "受控拒却动了盘上那一份已签的稿")

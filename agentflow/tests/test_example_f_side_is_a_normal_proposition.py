# -*- coding: utf-8 -*-
"""a：F 侧落一条 `kind=example`（玩具例子）—— 手稿条目、形态闸一次、送 V、等级按文字论证算。

业主原话（逐字，`_canon_F_manuscript_protocol.md` 第六节）：

    「登记里 `kind=example` 的行（玩具例子）：正文用 `Example` 环境，不用 Lemma/Theorem；
      其余按既有映射。example 只是给人看的标签，处理与普通命题一致。」

这一条量的是普通命题那一条链一个字节都没分叉：落稿仍走
`proofregistry.register_or_rewrite`、形态闸仍是 `Secretary.judge_proposition_form`
（跑一次、只在新命题那一档跑）、送审仍是 V 的 `verify_proof`（按正文 sha，一份一签）、
等级仍是 `evidencebits.derive_grade` 按五元位现算（有证明 + V 签 ⇒ `pre_theorem`）。
没有为 example 新开分支：`secretary.PROPOSITION_KINDS` 只是多了一个取值，
`derive_grade` / `judge_proposition_form` / `verify_proof` 一个字没动。

零模型调用：形态闸的缝给预置 JSON；V 的审阅缝按剧本回答；B 的登记不发模型请求。
"""
from __future__ import annotations

from agentflow import attackround as AR
from agentflow import evidencebits as EB
from agentflow import proofregistry as PR
from agentflow import secretary as SEC
from agentflow import verifications as VR
from agentflow.agent_f import core as FCORE
from agentflow.agent_f.core import AgentF

from _example_chain import (
    PLAN, SID_SLOT, FULL, manuscript_text, row_of, run_f_example, verification_rows,
    well_formed_seam, ws,
)


def test_a_f_registers_an_example_and_its_grade_is_by_the_textual_proof(tmp_path):
    """a：F 落 example ⇒ 手稿 `kind=example`、形态闸一次、送 V（按 sha）、等级 `pre_theorem`。"""
    st = ws(tmp_path)
    env = run_f_example(st)
    entry = PR.parse_entry(env["signed_text"])
    # 落稿：手稿条目就是登记条目，kind 是 example（不是 conjecture / lemma）
    assert entry["kind"] == "example", entry
    assert entry["proof_no"] == 1, entry
    # 形态闸：真的只跑了一次，且它看到的 kind 是 example
    calls = list(env["seam"].prompts)
    assert len(calls) == 1, calls
    form = SEC.proposition_form_rows(st.root)
    assert len(form) == 1, form
    assert form[0]["role"] == "F" and form[0]["kind"] == "example", form[0]
    assert form[0]["checked"] is True and form[0]["well_formed"] is True, form[0]
    # 送 V：在册那一支三转三行，签块按正文 sha 落在稿上
    rows = verification_rows(st, env["sid"])
    assert len(rows) == VR.SIGN_STREAK_NEED, rows
    assert all(str(r.get("proof_sha256") or "") == VR.text_sha(env["body"])
               for r in rows), rows
    assert env["block"]["signed"] is True, env["block"]
    assert env["block"]["proof_sha256"] == VR.text_sha(env["body"]), env["block"]
    # 等级：按文字论证算（有证明 + 有 V 签 ⇒ pre_theorem）
    row = row_of(st, env["sid"])
    assert row["kind"] == "example", row
    assert EB.derive_grade(dict(row["bits"]), kind=row["kind"]) == "pre_theorem", row["bits"]
    upgrade = dict(env["filed"].get("kind_upgraded_from_manuscript") or {})
    assert upgrade.get("to") == "example", upgrade
    assert upgrade.get("grade") == "pre_theorem", upgrade


def test_a2_the_proof_product_can_declare_example_and_the_registry_lands_it(tmp_path):
    """a2：`_reason_self` 那一支能按 `kind="example"` 落条目（产物上的可选 `kind`）。

    业主 2026-11-07：「example即玩具例子在实现时尽可能复用F和E原先的产出逻辑」。
    F 是作者，能表达「这一条是玩具例子」的既有落点是这一轮 `proof` 产物里的一个可选
    字段（不新增动作参数、不改 `attack_plans` 的行形状）；读到就由 `_proof_outlet`
    送进手稿登记，写进 `- 证据种类：example`，与 a 的链完全同一条。
    """
    # 提示词那一面：模型看得见这个可选字段（`parse_round` 只认四档，故在 `_reason_self`
    # 里从原样 JSON 取出；教学写在 `PRODUCT_SPECS`，`_attack_prompt` 逐字印它）。
    assert "可选 `kind`" in AR.PRODUCT_SPECS["proof"], AR.PRODUCT_SPECS["proof"]
    assert "example" in AR.PRODUCT_SPECS["proof"], AR.PRODUCT_SPECS["proof"]
    # 只认 `PROPOSITION_KINDS`；大小写归一到小写；词表外读成"没声明"（不猜）
    assert FCORE.product_kind({"kind": "Example"}) == "example"
    assert FCORE.product_kind({"kind": "example"}) == "example"
    assert FCORE.product_kind({"kind": "whatever"}) == ""
    assert FCORE.product_kind({}) == ""

    st = ws(tmp_path)
    seeded = SEC.Secretary("B", root=st.root, store=st, seam=None, enable_model=False)
    first = seeded.record_statement({
        "origin": "own_result", "kind": "conjecture", "label": "夹具",
        "statement_full": FULL, "statement_text": FULL,
        "evidence_kind": "heuristic", "quote_verified": None,
        "quote_reason": "夹具：先立猜想（等待证明）",
    }, role="B")
    assert first.get("created") is True, first
    sid = str([r for r in st.rows("statements")][0]["stmt_id"])

    seam = well_formed_seam()
    f = AgentF(st, config={"workspace_root": str(st.root), "plan_id": PLAN})
    f.f_secretary = SEC.Secretary("F", root=st.root, store=st, seam=seam,
                                  enable_model=True)
    product = {"product": "proof", "kind": "example",
               "steps": [{"n": 1, "text": "由 Sylow 定理，n_3=1。", "cites": [],
                          "assumption": False}]}
    got = f._proof_outlet(product, {"sid": SID_SLOT, "text": FULL, "testable": ""},
                          plan={"plan_id": PLAN, "problem_key": "k1"})
    assert got.get("ok") is True, got
    rel = str(got.get("manuscript_path") or "")
    assert rel == f"reports/f-proof-{sid}.md", rel
    text = manuscript_text(st, rel)
    assert PR.parse_entry(text)["kind"] == "example", text[:400]
    form = dict(got.get("proposition_form") or {})
    assert form.get("checked") is True and form.get("well_formed") is True, form
    rows = SEC.proposition_form_rows(st.root)
    assert len(rows) == 1 and rows[0]["kind"] == "example", rows

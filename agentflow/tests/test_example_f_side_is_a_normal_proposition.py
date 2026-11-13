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
    F_MID, PLAN, SID_SLOT, FULL, manuscript_text, pending_rows, row_of,
    run_f_example, well_formed_seam, ws,
)


def test_a_f_registers_an_example_and_its_grade_is_by_the_textual_proof(tmp_path):
    """a：F 落 example ⇒ 手稿 `kind=example`、形态闸一次、送 V（按 sha）、等级 `pre_theorem`。"""
    st = ws(tmp_path)
    env = run_f_example(st)
    entry = PR.parse_entry(env["signed_text"])
    # 落稿：手稿条目就是登记条目，kind 是 example（不是 conjecture / lemma）；
    # 2026-11-11 业主裁定：`- 证明号：` 在手稿产出侧退役 ⇒ 新稿头没有这一行。
    assert entry["kind"] == "example", entry
    assert "- 证明号：" not in env["signed_text"], env["signed_text"][:600]
    assert entry["proof_no"] == 0, entry
    # 形态闸：真的只跑了一次，且它看到的 kind 是 example
    calls = list(env["seam"].prompts)
    assert len(calls) == 1, calls
    form = SEC.proposition_form_rows(st.root)
    assert len(form) == 1, form
    assert form[0]["role"] == "F" and form[0]["kind"] == "example", form[0]
    assert form[0]["checked"] is True and form[0]["well_formed"] is True, form[0]
    # 送 V：命题号由 B 收录时现取 ⇒ V 走「未在册」那一支：三票按正文 sha 进 pending
    # 台账、签块盖回同一份稿（第 9 格稿号）；B 收录时按同一个 sha 认领那一签。
    # 2026-11-10（稿号口径）改的是「三票记在哪本账」：旧断言要求
    # `verifications/<命题号>.jsonl` 三行 —— 那需要稿名等于命题号，与「F 的稿只按稿号
    # 命名」不可兼得。强度没降：三票仍然真跑、sha 仍然逐票相符，另两条更硬的读数
    # （B 收录后第 3 位翻真、`reviewed_by` 指回 pending 那一行）一并断在这里。
    pending = pending_rows(st)
    assert len(pending) == VR.SIGN_STREAK_NEED, pending
    want_sha = VR.text_sha(env["body"])
    assert all(str(r.get("proof_sha256") or r.get("object_sha256") or "") == want_sha
               for r in pending), pending
    assert env["passes"].get("kind") == "proof_unregistered_signed", env["passes"]
    assert env["block"]["signed"] is True, env["block"]
    assert env["block"]["proof_sha256"] == want_sha, env["block"]
    _filed_bits = dict(row_of(st, env["sid"]).get("bits") or {})
    assert _filed_bits.get("reviewed") is True, _filed_bits
    assert str(((dict(_filed_bits.get("evidence") or {})).get("reviewed_by") or {}
                ).get("proof_sha256") or "") == want_sha, _filed_bits
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
               "proposition": "设 G 是有限群；则 |G|=p^2 时 G 交换。",
               "steps": [{"n": 1, "text": "由 Sylow 定理，n_3=1。", "cites": [],
                          "assumption": False}]}
    got = f._proof_outlet(product, {"sid": SID_SLOT, "text": FULL, "testable": ""},
                          plan={"plan_id": PLAN, "problem_key": "k1"},
                          manuscript_id=F_MID)
    assert got.get("ok") is True, got
    rel = str(got.get("manuscript_path") or "")
    # 2026-11-10（稿号口径）：登记条目落在 F 自己的稿号上（夹具显式给号），
    # 不按命题号 / 计划号命名。
    assert rel == f"reports/f-proof-{F_MID}.md", rel
    assert str(got.get("manuscript_id") or "") == F_MID, got
    assert str(got.get("manuscript_id_source") or "") == "given", got
    # 反向：稿名里不含命题号（旧口径 `f-proof-<命题号>` 不许出现）。
    assert f"f-proof-{sid}" not in rel, (rel, sid)
    assert "f-proof-plan-" not in rel, rel
    text = manuscript_text(st, rel)
    assert PR.parse_entry(text)["kind"] == "example", text[:400]
    form = dict(got.get("proposition_form") or {})
    assert form.get("checked") is True and form.get("well_formed") is True, form
    rows = SEC.proposition_form_rows(st.root)
    assert len(rows) == 1 and rows[0]["kind"] == "example", rows

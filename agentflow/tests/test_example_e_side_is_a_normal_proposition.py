# -*- coding: utf-8 -*-
"""b / c：E 侧的玩具例子走既有 e-proof 产出；处理与普通命题一致（四处读数）。

业主原话（逐字，`_canon_F_manuscript_protocol.md` 第六节 + 本批任务书）：

    「对于玩具例子，F和E会协同或独立产出，类型为example，但处理时也可按照statement处理，
      一样落稿，一样审，一样有条件和结论。如果是E侧产出，通常是穷举论证」
    「example这个标签只是给人看的，和普通命题一致」

## b（E 侧那一条链）

`run_experiment(kind="example")` → 同一个形态闸（`Secretary.judge_proposition_form`，
`kind=example`）→ 落 `reports/e-proof-<实验号>.md`（首页多一行 `- 证据种类：example`，
与 F 的手稿同一个头标记）→ B 收录时按它落 `statements.kind=example` → V 三转会审
（穷举通道）→ 第 1 位（numeric）翻真 ⇒ 等级 `theorem`。没有另起一套 e-proof 产出。

## c（与普通命题一致）

同一份 example 用普通命题的判据链能过：落稿（`proofregistry` 条目 / e-proof 文件）、
审（形态闸台账 + `verifications` 三行）、等级（`derive_grade`；同一份 bits 换成
`kind=theorem` 得**同一个**等级）、收工读数（`closing.proposition_form_reading` /
`type_ahead_of_grade_rows`）四处各一条读数。
"""
from __future__ import annotations

import pathlib

from agentflow import closing as CL
from agentflow import evidencebits as EB
from agentflow import exhaustionreport as ER
from agentflow import numericproof as NP
from agentflow import proofregistry as PR
from agentflow import secretary as SEC
from agentflow import verifications as VR

from _example_chain import (
    pending_rows, row_of, run_e_example, run_f_example, verification_rows, ws,
)


# ============================================================ b E 侧 example

def test_b_e_registers_an_example_through_the_existing_e_proof_route(tmp_path):
    """b：E 的穷举 example 走既有 e-proof 产出、过同一道形态闸、V 签后等级 `theorem`。"""
    st = ws(tmp_path)
    env = run_e_example(st)
    # 既有 e-proof 产出：手稿落点 + `- 证据种类：example`
    assert env["rel"] == ER.proof_manuscript_relpath(env["out"]["experiment_id"]), env["rel"]
    assert "- 证据种类：example" in env["signed_text"], env["signed_text"][:400]
    assert PR.parse_entry(env["signed_text"])["kind"] == "example"
    # 同一个形态闸（F 与 E 是同一个判定口），且它拿到的 kind 是 example
    form = SEC.proposition_form_rows(st.root)
    assert len(form) == 1, form
    assert form[0]["role"] == "E" and form[0]["kind"] == "example", form[0]
    assert form[0]["checked"] is True and form[0]["well_formed"] is True, form[0]
    # V 签（按正文 sha，一份一签）：未在册那一支先落 pending，在册三转后落 verifications
    pending = pending_rows(st)
    assert pending, pending
    assert all(str(r.get("proof_sha256") or "") == VR.proof_sha(env["column"])
               for r in pending), pending
    ledger = verification_rows(st, env["sid"])
    assert len(ledger) == VR.SIGN_STREAK_NEED, ledger
    assert all(str(r.get("proof_sha256") or "") == VR.proof_sha(env["column"])
               for r in ledger), ledger
    assert env["passes"][-1].get("signed_bit3") is True, env["passes"][-1]
    # 等级：按穷举算（numeric verified + proof ⇒ theorem）
    row = row_of(st, env["sid"])
    assert row["kind"] == "example", row
    bits = dict(row.get("bits") or {})
    assert bits.get("numeric") == "verified", bits
    assert EB.derive_grade(bits, kind=row["kind"]) == "theorem", bits
    # 证明栏就是 E 的那三段（既有 `numericproof.compose_proof_column`，不是新写的）
    assert NP.parse_proof_column(str(row.get("proof_text") or ""))["problems"] == [], (
        row.get("proof_text"))


# ============================================================ c 与普通命题一致

def test_c_the_same_example_passes_the_identical_chain(tmp_path):
    """c：同一份 example 用普通命题的判据链能过 —— 落稿 / 审 / 等级 / 收工四处读数。

    四处都**不读 kind 做分支**：落稿读 `proofregistry` 条目、审读两张台账
    （形态闸 + V 的 verifications）、等级读 `derive_grade`（同一份 bits 换 kind 得同值）、
    收工读数读 `closing.proposition_form_reading` 与 `type_ahead_of_grade_rows`。
    """
    st = ws(tmp_path)
    f_env = run_f_example(st)
    e_env = run_e_example(st)
    f_row = row_of(st, f_env["sid"])
    e_row = row_of(st, e_env["sid"])

    # ① 落稿：F 的登记条目在册、kind=example；E 的 e-proof 文件在盘上
    entries = {str(x.get("statement_id")): x for x in PR.entries_on_disk(st.root)
               if str(x.get("family")) == "F"}
    assert entries[f_env["sid"]]["kind"] == "example", entries[f_env["sid"]]
    assert entries[f_env["sid"]]["sha256"] == f_env["got"]["proof_sha256"], (
        entries[f_env["sid"]], f_env["got"]["proof_sha256"])
    assert (pathlib.Path(st.root) / e_env["rel"]).is_file()

    # ② 审：形态闸两个角色各一次；V 的台账两条链各三票
    read = CL.proposition_form_reading(st)
    assert read["checked"] is True and read["judged"] == 2, read
    assert read["by_role"]["F"]["well_formed"] == 1, read["by_role"]
    assert read["by_role"]["E"]["well_formed"] == 1, read["by_role"]
    assert len(verification_rows(st, f_env["sid"])) == VR.SIGN_STREAK_NEED
    assert len(verification_rows(st, e_env["sid"])) == VR.SIGN_STREAK_NEED
    assert len(pending_rows(st)) >= 1

    # ③ 等级：现算，且**换掉标签不改等级**（example 与 theorem 对同一份 bits 同值）
    f_bits, e_bits = dict(f_row["bits"]), dict(e_row["bits"])
    assert EB.derive_grade(f_bits, kind="example") == EB.derive_grade(f_bits, kind="theorem")
    assert EB.derive_grade(e_bits, kind="example") == EB.derive_grade(e_bits, kind="theorem")
    assert EB.derive_grade(f_bits, kind="example") == "pre_theorem", f_bits
    assert EB.derive_grade(e_bits, kind="example") == "theorem", e_bits

    # ④ 收工读数：两条都算"有记录且不被判成类型先于等级"
    ahead = CL.type_ahead_of_grade_rows(st)
    assert ahead["state"] == "computed", ahead
    assert ahead["rows"] == [], ahead
    grades = {}
    for row in st.rows("statements"):
        if str(row.get("kind")) != "example":
            continue
        grades[str(row.get("stmt_id"))] = EB.derive_grade(dict(row.get("bits") or {}),
                                                         kind="example")
    assert grades == {f_env["sid"]: "pre_theorem", e_env["sid"]: "theorem"}, grades

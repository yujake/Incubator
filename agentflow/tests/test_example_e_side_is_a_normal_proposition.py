# -*- coding: utf-8 -*-
"""b / c：E 侧的玩具例子走既有 e-proof 产出；处理与普通命题一致（四处读数）。

业主原话（逐字，`_canon_F_manuscript_protocol.md` 第六节 + 本批任务书）：

    「对于玩具例子，F和E会协同或独立产出，类型为example，但处理时也可按照statement处理，
      一样落稿，一样审，一样有条件和结论。如果是E侧产出，通常是穷举论证」
    「example这个标签只是给人看的，和普通命题一致」

## b（E 侧那一条链）

`run_experiment(kind="example")` → 同一个形态闸（`Secretary.judge_proposition_form`，
`kind=example`）→ 落 `reports/e-proof-<实验号>.md`（首页多一行 `- 命题类型：example`，
与 F 的手稿同一个头标记）→ B 收录时按它落 `statements.kind=example` → V 三转会审
（穷举通道）→ 第 1 位（numeric）翻真 ⇒ 等级 `theorem`。没有另起一套 e-proof 产出。

## c（与普通命题一致）

同一份 example 用普通命题的判据链能过：落稿（`proofregistry` 条目 / e-proof 文件）、
审（形态闸台账 + `verifications` 三行）、等级（`derive_grade`；同一份 bits 换成
`kind=theorem` 得同一个等级）、收工读数（`closing.proposition_form_reading` /
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
from agentflow import vsigns as VS

from _example_chain import (
    pending_rows, row_of, run_e_example, run_f_example, verification_rows, ws,
)


# ============================================================ b E 侧 example

def test_b_e_registers_an_example_through_the_existing_e_proof_route(tmp_path):
    """b：E 的穷举 example 走既有 e-proof 产出、过同一道形态闸、V 签后等级 `theorem`。"""
    st = ws(tmp_path)
    env = run_e_example(st)
    # 既有 e-proof 产出：手稿落点 + `- 命题类型：example`
    assert env["rel"] == ER.proof_manuscript_relpath(env["out"]["experiment_id"]), env["rel"]
    assert "- 命题类型：example" in env["signed_text"], env["signed_text"][:400]
    assert PR.parse_entry(env["signed_text"])["kind"] == "example"
    # 同一个形态闸（F 与 E 是同一个判定口），且它拿到的 kind 是 example
    form = SEC.proposition_form_rows(st.root)
    assert len(form) == 1, form
    assert form[0]["role"] == "E" and form[0]["kind"] == "example", form[0]
    assert form[0]["checked"] is True and form[0]["well_formed"] is True, form[0]
    # V 签（按正文 sha，一份一签）：未在册那一支先落 pending，在册三转后落 verifications
    pending = pending_rows(st)
    assert pending, pending
    assert all(str(r.get("proof_sha256") or "") == VR.text_sha(env["column"])
               for r in pending), pending
    ledger = verification_rows(st, env["sid"])
    assert len(ledger) == VR.SIGN_STREAK_NEED, ledger
    assert all(str(r.get("proof_sha256") or "") == VR.text_sha(env["column"])
               for r in ledger), ledger
    # 2026-11-08（业主：「V 现在只对手稿负责」）：V 不再翻命题行的第 3 位
    # （`signed_bit3` 恒 False），签落在这一份 e-proof 稿上。原来那一句断的是
    # "签真的发生了"；新契约下同一件事由两处读数回答，而且更硬：
    # ① 收方秘书把九格块落回稿了没有（`review_write.manuscript_signed`）；
    # ② 稿上那一块自己读出来是不是 signed（`vsigns.manuscript_sign_reading`，
    #    连 `streak` / `need` 一起对上门槛）。只把 `signed_bit3` 改成 False 是没断言的，
    # 所以这两处缺一不可。
    last = env["passes"][-1]
    assert last.get("signed_bit3") is False, last
    assert dict(last.get("review_write") or {}).get("manuscript_signed") is True, last
    block = VS.manuscript_sign_reading(env["signed_text"], manuscript_path=env["rel"])
    assert block.get("signed") is True, block
    assert (block.get("streak"), block.get("need")) == (VR.SIGN_STREAK_NEED,
                                                        VR.SIGN_STREAK_NEED), block
    # 等级：按穷举算（numeric verified + proof ⇒ theorem）
    row = row_of(st, env["sid"])
    assert row["kind"] == "example", row
    bits = dict(row.get("bits") or {})
    assert bits.get("numeric") == "verified", bits
    assert EB.derive_grade(bits, kind=row["kind"]) == "theorem", bits
    # 证明栏就是 E 的那一段穷举论证（既有 `numericproof.compose_proof_column`，不是新写的）；
    # 程序路径在实验行的 `code_path`（2026-11-08）
    exp = [dict(r) for r in st.rows("experiments")][0]
    assert NP.parse_proof_column(str(row.get("proof_text") or ""),
                                 code_path=exp["code_path"])["problems"] == [], (
        row.get("proof_text"))


# ============================================================ c 与普通命题一致

def test_c_the_same_example_passes_the_identical_chain(tmp_path):
    """c：同一份 example 用普通命题的判据链能过 —— 落稿 / 审 / 等级 / 收工四处读数。

    四处都不读 kind 做分支：落稿读 `proofregistry` 条目、审读两张台账
    （形态闸 + V 的 verifications）、等级读 `derive_grade`（同一份 bits 换 kind 得同值）、
    收工读数读 `closing.proposition_form_reading` 与 `type_ahead_of_grade_rows`。
    """
    st = ws(tmp_path)
    f_env = run_f_example(st)
    e_env = run_e_example(st)
    f_row = row_of(st, f_env["sid"])
    e_row = row_of(st, e_env["sid"])

    # ① 落稿：F 的登记条目在册、kind=example；E 的 e-proof 文件在盘上
    #
    # 2026-11-10（稿号口径）：F 的稿名 / 登记条目按 F 自己的稿号命名，与命题号无关 ⇒
    # 不能再用命题号去 entries_on_disk 里取那一条（`statement_id` 那一格在 F 还没被收录
    # 时本来就是空的）。这里改成按路径取，并把"稿名里不含命题号"一并量出来 ——
    # 强度没降：仍是"那一份稿的登记条目在册 / kind / sha 三格对得上"。
    f_entries = [x for x in PR.entries_on_disk(st.root)
                 if str(x.get("family")) == "F"]
    assert len(f_entries) == 1, f_entries
    f_entry = f_entries[0]
    assert str(f_entry.get("path") or "") == f_env["rel"], f_entry
    assert f_entry["kind"] == "example", f_entry
    assert f_entry["sha256"] == f_env["got"]["proof_sha256"], (
        f_entry, f_env["got"]["proof_sha256"])
    assert f"f-proof-{f_env['sid']}" not in f_env["rel"], (f_env["rel"], f_env["sid"])
    assert (pathlib.Path(st.root) / e_env["rel"]).is_file()

    # ② 审：形态闸两个角色各一次；V 的三票两条链都真跑
    #
    # 2026-11-10（稿号口径）：F 的命题号由 B 收录时现取 ⇒ V 先按「未在册」那一支把三票
    # 记进 pending 台账（按正文 sha），B 收录时认领；E 那条仍走在册那一本
    # `verifications/<命题号>.jsonl`（e-proof 按实验号寻址，本来就是两个号段）。
    # 断言没降：F 三票仍在盘上、sha 仍逐票相符，且第 3 位在 B 收录后为真。
    read = CL.proposition_form_reading(st)
    assert read["checked"] is True and read["judged"] == 2, read
    assert read["by_role"]["F"]["well_formed"] == 1, read["by_role"]
    assert read["by_role"]["E"]["well_formed"] == 1, read["by_role"]
    f_pending = [r for r in pending_rows(st)
                 if str(r.get("proof_sha256") or r.get("object_sha256") or "")
                 == VR.text_sha(f_env["body"])]
    assert len(f_pending) == VR.SIGN_STREAK_NEED, f_pending
    assert dict(f_row["bits"] or {}).get("reviewed") is True, f_row["bits"]
    assert len(verification_rows(st, e_env["sid"])) == VR.SIGN_STREAK_NEED

    # ③ 等级：现算，且换掉标签不改等级（example 与 theorem 对同一份 bits 同值）
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

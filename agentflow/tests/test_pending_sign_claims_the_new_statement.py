# -*- coding: utf-8 -*-
"""「先有签、后登记」：新建命题时认领 pending 台账里的那一签（五元位第 3 位）。

## 这一组守什么

`vsigns.bits_after_sign` 是 B 收录时"认签"的那一步（业主 2026-11-01：
「B 侧自己写的证明想要 V 签时一样是拿到 V 签，B 再录入」）。它此前只认
`out/vsigns/<sha>.json` 那一份签，而且要求签文件里的 `statement_id` 等于入参
`statement_id`；新建命题时那个号还不存在（`register_statement.py` 传的是
`stmt_id_now`，新建时是空串）⇒「先签后登记」这一半永远认不到签：同一份正文，
若 V 在命题还没在册时审过（落在 `verifications/pending/<sha>.jsonl`），登记上之后
第 3 位仍然是假。同一个仓库里 `_v_signature_for`（B 的入库闸）已经按这一份正文的
sha 去 pending 里认领过 —— 两处两把尺。

## 判据

| # | 造什么 | 期望 |
|---|---|---|
| ① | 先落一条 pending 签，再登记同一份正文 | 行的 `bits.reviewed` 为真；pending 台账行回写了 `statement_id` |
| ② | 同一份正文再登记一次 | 不认领第二次（台账行仍绑在第一条上；只有一行命题） |
| ③ | 反真空：正文改一个字 | 不认领（`bits.reviewed` 为假，台账行仍没有 `statement_id`） |
| ④ | 反真空：没有 pending 签 | 不认领（同上） |

零模型调用；夹具走生产的写口（`verifications.record_pending_sign` +
`AgentB.register_statement`），不手写台账。
"""
from __future__ import annotations

import pathlib

import pytest
from agentflow import verifications as VR
from agentflow import vsigns as VS
from agentflow.agent_b import AgentB
from agentflow.store import Store

TS = "2026-11-02T09:00:00+08:00"
FULL = "设 f 在 [0,1] 上连续，则 f 一致连续。"
PROOF = "取 δ=ε，逐点验证：|x-y|<δ ⇒ |f(x)-f(y)|<ε。"
#: 改一个字（`ε` → `ε/2`）的同一份命题的另一版正文。
PROOF_CHANGED = "取 δ=ε/2，逐点验证：|x-y|<δ ⇒ |f(x)-f(y)|<ε。"
OK = {"verdict": "成立", "why": "逐步核过，没有缺陷"}


def _ws(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _pending_row(st: Store, proof: str = PROOF) -> dict:
    path = VR.pending_ledger_path(st.root, VR.text_sha(proof))
    rows, problems = VR.JF.read_jsonl(path)
    assert problems == [], problems
    assert len(rows) == 1, rows
    return dict(rows[0])


def _manuscript(full: str, proof: str) -> str:
    """B 登记这一笔必须带的手稿（2026-11-04 甲之后在册也要稿）。"""
    from agentflow import depsection as DS

    return ("# F 的证明手稿（夹具）\n\n- 计划：0000\n\n"
            "## 命题\n\n" + full + "\n\n## 证明\n\n" + proof + "\n\n"
            + DS.render_dependency_section([]) + "\n")


def _register(st: Store, *, proof: str = PROOF, full: str = FULL) -> dict:
    b = AgentB(st, extractor=None, extract_text=None)
    return b.register_statement(
        statement_full=full, statement_text=full, proof_text=proof,
        proof_manuscript=_manuscript(full, proof),
        kind="conjecture", label="探针命题", origin="own_result",
        evidence_kind="heuristic", quote_verified=None,
        quote_reason="夹具：自产证明，没有第二份文本可比对",
        line_range={"label": "reports/probe.md"})


def _row_of(st: Store, stmt_id: str) -> dict:
    return next(dict(r) for r in st.rows("statements")
                if str(r.get("stmt_id") or "") == str(stmt_id))


# ---------------------------------------------------------------- ① 先签后登记
def test_a_pending_sign_is_claimed_by_the_statement_that_gets_registered(tmp_path):
    """① 先有 pending 签（命题还没在册时审的）⇒ 再登记同一份正文时第 3 位认到它。"""
    st = _ws(tmp_path)
    VR.record_pending_sign(st.root, proof_text=PROOF, verdict=dict(OK), object_path="reports/f-proof-000000.md", secretary_judge={"checked": True, "axis": "clean", "decision": "没问题", "reason": "夹具：秘书判 clean"})

    got = _register(st)
    assert got.get("ok") is True, got
    sid = str(got["stmt_id"])
    row = _row_of(st, sid)
    bits = dict(row.get("bits") or {})
    assert bits.get("reviewed") is True, bits
    ev = dict(bits.get("evidence") or {})
    assert str((ev.get("reviewed_by") or {}).get("verification_id") or "").startswith(
        VR.PENDING_PREFIX), ev
    # 台账行回写了 statement_id（同一份正文只认领一次的那把锁）
    pending = _pending_row(st)
    assert str(pending.get("statement_id") or "") == sid, pending
    assert str(pending.get("stmt_id") or "") == sid, pending
    # 读数透出来（调用方看得到"这一格认到了哪一签"）
    v_sign = dict(got.get("v_sign") or {})
    assert v_sign.get("applied") is True, got
    assert str((v_sign.get("claim") or {}).get("bound_id") or "") == sid, v_sign


# ---------------------------------------------------------------- ② 不许认领两次
def test_the_same_body_registered_twice_does_not_claim_the_sign_twice(tmp_path):
    """② 同一份正文登记两次 ⇒ 只认领一次（第二次不许把同一签再认给另一条命题）。"""
    st = _ws(tmp_path)
    VR.record_pending_sign(st.root, proof_text=PROOF, verdict=dict(OK), object_path="reports/f-proof-000000.md", secretary_judge={"checked": True, "axis": "clean", "decision": "没问题", "reason": "夹具：秘书判 clean"})
    first = _register(st)
    assert first.get("ok") is True, first
    sid = str(first["stmt_id"])

    second = _register(st)
    # 第二次是"已在册"（不新建行）：命题行数不变，台账行仍绑在第一条上。
    assert len(st.rows("statements")) == 1, st.rows("statements")
    pending = _pending_row(st)
    assert str(pending.get("statement_id") or "") == sid, pending
    # 第二次的认签读数是"没认"（不是"又认给了一条新命题"）
    v2 = dict(second.get("v_sign") or {})
    assert v2.get("applied") is not True, second
    row = _row_of(st, sid)
    assert dict(row.get("bits") or {}).get("reviewed") is True, row


# ---------------------------------------------------------------- ③ 反真空：改一个字
def test_one_changed_character_is_not_claimed(tmp_path):
    """③ 反真空：pending 签盖的是旧正文；改一个字之后登记 ⇒ 不认领（sha 不符）。

    2026-11-02 准入闸默认 strict 之后，"不认领"的最终形态是「整笔被拒」
    （`proof_without_v_sign`）：没有一份盖住这一份正文的签，它就不许进台账。
    所以这一条读的是"拒收 + pending 那一行仍然没有绑号"，不再是"写进去了但没认签"。
    """
    st = _ws(tmp_path)
    VR.record_pending_sign(st.root, proof_text=PROOF, verdict=dict(OK), object_path="reports/f-proof-000000.md", secretary_judge={"checked": True, "axis": "clean", "decision": "没问题", "reason": "夹具：秘书判 clean"})
    got = _register(st, proof=PROOF_CHANGED)
    assert got.get("ok") is False, got
    assert got.get("kind") == "proof_without_v_sign", got
    assert st.rows("statements") == [], st.rows("statements")
    pending = _pending_row(st)
    assert str(pending.get("statement_id") or "") == "", pending
    v_sign = dict(got.get("v_sign") or {})
    assert v_sign.get("applied") is not True, got


# ---------------------------------------------------------------- ④ 反真空：没有签
def test_no_pending_sign_means_no_claim(tmp_path):
    """④ 反真空：pending 里没有这一份 ⇒ 签不上去、整笔被拒（"没签过"不是"认到了一签"）。"""
    st = _ws(tmp_path)
    got = _register(st)
    assert got.get("ok") is False, got
    assert got.get("kind") == "proof_without_v_sign", got
    assert st.rows("statements") == [], st.rows("statements")
    assert VR.pending_rows(st.root)[0] == [], VR.pending_rows(st.root)


# ---------------------------------------------------------------- ⑤ 同一把尺
def test_a_pending_sign_that_cannot_sign_bit3_is_not_claimed(tmp_path):
    """⑤ pending 那一签也要过 `row_signable`（成立 + 无未解决 error）——
    与 V 那条 pending 台账同一把尺：签不住的签不许被认领，于是这一笔不许进台账。"""
    st = _ws(tmp_path)
    VR.record_pending_sign(st.root, proof_text=PROOF, verdict={
        "verdict": "成立",
        "findings": [{"level": "error", "step": 2, "kind": "无依据的步骤",
                      "detail": "第 2 步直接用了结论"}]},
        object_path="reports/f-proof-000000.md", secretary_judge={"checked": True, "axis": "clean", "decision": "没问题", "reason": "夹具：秘书判 clean"})
    got = _register(st)
    assert got.get("ok") is False, got
    assert got.get("kind") == "proof_without_v_sign", got
    assert st.rows("statements") == [], st.rows("statements")
    pending = _pending_row(st)
    assert str(pending.get("statement_id") or "") == "", pending
    # 拒收那一笔把闸的读数带回来了：这一份正文在闸眼里仍然"没有签"
    # （签不住的 pending 行没有被认领成第 3 位）。
    gate = dict(got.get("proof_gate") or {})
    assert gate.get("applicable") is True, gate
    assert gate.get("proofs") and gate["proofs"][0]["signed"] is False, gate


def test_the_claim_names_a_ledger_that_really_exists(tmp_path):
    """可达性：认领读数点名的那个台账文件真的在盘上（不是编一句"认到了"）。"""
    st = _ws(tmp_path)
    VR.record_pending_sign(st.root, proof_text=PROOF, verdict=dict(OK), object_path="reports/f-proof-000000.md", secretary_judge={"checked": True, "axis": "clean", "decision": "没问题", "reason": "夹具：秘书判 clean"})
    got = _register(st)
    v_sign = dict(got.get("v_sign") or {})
    ledger = str(v_sign.get("claim", {}).get("ledger") or "")
    assert ledger, v_sign
    rel = ledger.split("#", 1)[0]
    path = pathlib.Path(st.root) / rel
    assert path.is_file(), (rel, got)
    assert VR.PENDING_PREFIX in ledger, ledger


# ---------------------------------------------------------------- ⑥ 洞 2：在册台账读得到
def test_the_claimed_sign_is_readable_in_the_registered_ledger(tmp_path):
    """洞 2（2026-11-10）：收录之后 `list_verifications` 必须读到那一行。

    ## 量到的形态（HEAD 9a075327，真 store）

    pending 三行在盘上、行行回写了 `statement_id`，签块与签文件都指着
    `verifications/pending/<正文sha>.jsonl#u-…`；而 `list_verifications` 只 glob
    `verifications/*.jsonl` 顶层（pending 是子目录）⇒ 不带过滤也返回 0 行。
    台账里"这条命题有谁审过"读出来是空的 —— 任何按这个读口出的报告/收工读数
    都会说"没有审核记录"。

    ## 口径（读侧并入，唯一入口）

    `verifications._claimed_pending_rows`：pending 行有 `statement_id`/`stmt_id`
    ⇒ 已经属于那一条命题 ⇒ 算在册台账；两个都空 ⇒ 还没被收录 ⇒ 不算任何命题的
    记录（仍由 `pending_rows` / `pending_sign` 读）。物理位置与签的锚点都不动。
    """
    st = _ws(tmp_path)
    VR.record_pending_sign(st.root, proof_text=PROOF, verdict=dict(OK), object_path="reports/f-proof-000000.md", secretary_judge={"checked": True, "axis": "clean", "decision": "没问题", "reason": "夹具：秘书判 clean"})
    got = _register(st)
    assert got.get("ok") is True, got
    sid = str(got["stmt_id"])
    proof_sha = VR.text_sha(PROOF)

    rows, problems = VR.list_verifications(st.root, statement_id=sid, limit=None)
    assert problems == [], problems
    assert len(rows) >= 1, rows
    for row in rows:
        assert str(row.get("statement_id") or "") == sid, row
        assert str(row.get("verification_id") or "").startswith(VR.PENDING_PREFIX), row
        assert row.get("verdict") == "成立", row
        assert str(row.get("proof_sha256") or "") == proof_sha, row
    # 不带过滤也至少一行（同一份在册台账；未认领的 pending 行不会混进来）
    all_rows, all_bad = VR.list_verifications(st.root, limit=None)
    assert all_bad == [] and len(all_rows) >= 1, (all_bad, all_rows)
    assert {str(r.get("statement_id") or "") for r in all_rows} == {sid}, all_rows
    # 读数面（收工门读的那一格）要把"它在哪"说清，而不是"文件 0 份、3 行"。
    lr = VR.ledger_reading(st.root, store=st)
    assert int(lr.get("rows") or 0) >= 1, lr
    assert int(lr.get("claimed_pending") or 0) >= 1, lr
    # 锚点按行的真实落点拼：`list_verifications` 并入了它，`vsigns.ledger_anchor`
    # 不许把它写成 `verifications/<号>.jsonl#u-…`（那串路径在盘上打不开）。
    anchor = VS.ledger_anchor(st.root, statement_id=sid, proof_no=1,
                              artifact_sha=proof_sha, clean_only=True)
    assert anchor.get("found") is True, anchor
    href = str(anchor.get("ledger") or "")
    assert href.startswith(f"{VR.VERIFICATIONS_DIR}/{VR.PENDING_DIR_NAME}/"), href
    ledger_file = pathlib.Path(st.root) / href.split("#", 1)[0]
    assert ledger_file.is_file(), (href, anchor)
    assert href.endswith(f"#{anchor.get('verification_id')}"), (href, anchor)


def test_the_read_side_union_is_what_makes_the_claimed_row_visible(tmp_path, monkeypatch):
    """⑥ 的反真空：把读侧的并入口摘掉 ⇒ 上面那条判据当场红（0 行）。

    这一条量的是"那一行真的由 `_claimed_pending_rows` 读出来"，不是别处凑巧
    又写了一份到顶层台账。盘上顶层依然没有 `verifications/<号>.jsonl`。
    """
    st = _ws(tmp_path)
    VR.record_pending_sign(st.root, proof_text=PROOF, verdict=dict(OK), object_path="reports/f-proof-000000.md", secretary_judge={"checked": True, "axis": "clean", "decision": "没问题", "reason": "夹具：秘书判 clean"})
    got = _register(st)
    sid = str(got["stmt_id"])
    assert len(VR.list_verifications(st.root, statement_id=sid, limit=None)[0]) >= 1

    monkeypatch.setattr(VR, "_claimed_pending_rows",
                        lambda *_a, **_kw: ([], []))
    rows, problems = VR.list_verifications(st.root, statement_id=sid, limit=None)
    assert rows == [], rows
    assert problems == [], problems
    # 物理事实仍是"顶层没有那一份文件"：一行都读不到只因为并入口被摘掉。
    assert not (pathlib.Path(st.root) / "verifications" / f"{sid}.jsonl").exists()

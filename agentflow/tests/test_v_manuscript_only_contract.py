# -*- coding: utf-8 -*-
"""V 只对手稿负责：五处读取下线的"改前能过、改后不能过"读数 + 写侧反真空。

2026-11-08 业主：
    「V现在只对手稿负责，不该看台账了」
    「第几份证明、什么等级都是B秘书录入时关心且需负责的」

这一组把"来源换掉了"钉成可量的事：台账里写 A、手稿里写 B ⇒ V 读到的必须是 B；
再把旧的 statements 写路径放回去 ⇒ "statements 字节不变"这条判据必须红。
"""
from __future__ import annotations

import json
import pathlib

from agentflow import depsection as DS
from agentflow import evidencebits as EB
from agentflow import secretary as SEC
from agentflow import verifications as VR
from agentflow import vsigns as VS
from agentflow.agent_v import AgentV
from agentflow.store import Store

from conftest import seed_statement_row


def _ws(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _put(st: Store, *, proof_text: str = "1. 台账里的旧证明。",
         statement_full: str = "台账里的命题正文。") -> dict:
    return seed_statement_row(
        st, proof_text=proof_text, statement_full=statement_full,
        statement_text=statement_full[:24], kind="theorem", label="契约夹具",
        origin="own_result", evidence_kind="heuristic",
        bits=EB.bits_of(proof=True, proof_process=proof_text, kind="theorem"),
        stmt_id="000000")


def _manuscript(st: Store, *, proof: str, full: str) -> str:
    rel = "reports/f-proof-000000.md"
    path = pathlib.Path(st.root) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"# 证明手稿\n\n\n## 命题\n\n{full}\n\n"
        f"## 证明\n\n{proof}\n\n" + DS.render_dependency_section([]),
        encoding="utf-8")
    return rel


class _Seam:
    """只记提示词、回一行「成立」的替身（零模型钱）。"""

    wired = True

    def __init__(self) -> None:
        self.prompts: list[str] = []

    def ask(self, prompt: str = "", **_kw):
        self.prompts.append(prompt)

        class _Call:
            ok = True
            problem = ""
            detail = ""
            text = json.dumps({"verdict": "成立", "findings": []}, ensure_ascii=False)

        return _Call()


def test_prompt_and_read_proof_take_the_manuscript_not_the_ledger(
        tmp_path: pathlib.Path) -> None:
    """读 1/4/5：命题正文与证明全文都以手稿为准（台账里的旧值一个字都不出现）。"""
    st = _ws(tmp_path)
    _put(st, proof_text="1. 台账里的旧证明。", statement_full="台账里的命题正文。")
    proof = "1. 手稿里的新证明。\n2. 于是结论成立。"
    full = "手稿里的命题正文。"
    rel = _manuscript(st, proof=proof, full=full)

    seam = _Seam()
    v = AgentV(st, workspace_root=st.root, llm=seam)   # 不接秘书：只量读数来源
    v.verify_proof("000000", proof_manuscript=rel)

    assert seam.prompts, "V 没有被问过"
    prompt = seam.prompts[0]
    assert full in prompt, "提示词里的命题正文不是手稿的 `## 命题`"
    assert "台账里的命题正文" not in prompt, "提示词里混进了 statements.statement_full"
    assert "手稿里的新证明" in prompt, "提示词里的证明不是手稿的 `## 证明`"
    # 读 1：提示词里的"只读读数"只剩手稿事实 —— 台账的 kind/status/evidence_kind
    # 一格都不许出现（改前 `_read_only_facts` 会把它们印进来）。
    assert "kind=" not in prompt and "evidence_kind=" not in prompt, prompt
    assert "手稿：" in prompt and "签块：" in prompt, prompt

    got = v.read_proof("000000")
    assert got["source"] == "manuscript", got
    assert "手稿里的新证明" in got["proof_text"], got
    assert "台账里的旧证明" not in got["proof_text"], got


def test_old_statement_write_restored_makes_the_byte_criterion_red(
        tmp_path: pathlib.Path, monkeypatch) -> None:
    """写侧反真空：旧 `sign_statement` 一放回 V 的落地那一步 ⇒ statements 字节必变。

    正控：正常 V 送审（带秘书、三转 clean + 发签）之后 `data/statements.json` 逐字节
    不变、命题位仍是假、稿上有签。反真空：把 `land_sign_without_ledger` 包一层，落块
    之后再走一次旧的 `sign_statement` ⇒ 字节变、位翻真（于是上面那条字节判据会红）。
    """
    from agentflow import conductor as CND
    from test_v_reviews_three_times_before_signing import (
        CLEAN_REPLY, _ReviewSeam, _Seam as _SecSeam, _axis, _secretary)

    def _run(store: Store) -> dict:
        seam = _SecSeam({"v_reply_defect": [_axis(SEC.V_REPLY_CLEAN)],
                         "sign_issuance": [_axis(SEC.SIGN_ISSUE)]})
        v = AgentV(store, workspace_root=store.root,
                   llm=_ReviewSeam([CLEAN_REPLY]), secretary=_secretary(store, seam))
        with CND.calling_as("t-v-000001", "V", parent_task_id="t-f-000001",
                            parent_role="F"):
            return v.verify_proof("000000", proof_text=PROOF, proof_manuscript=REL)

    PROOF = "1. 由定义直接得到。\n2. 于是结论成立。"
    REL = "reports/f-proof-000000.md"

    # ---- 正控：V 只签稿，不写 statements。
    st = _ws(tmp_path / "clean")
    _put(st, proof_text=PROOF, statement_full="设 G 是有限群；则结论成立。")
    _manuscript(st, proof=PROOF, full="设 G 是有限群；则结论成立。")
    before = (pathlib.Path(st.root) / "data" / "statements.json").read_bytes()
    got = _run(st)
    after = (pathlib.Path(st.root) / "data" / "statements.json").read_bytes()
    assert got.get("checked") is True, got
    assert got.get("review_write", {}).get("manuscript_signed") is True, got["review_write"]
    assert after == before, "V 的送审改了 data/statements.json（新契约下这是 B 收录的活）"
    row = dict(st.rows("statements")[0])
    assert row["bits"].get("reviewed") is False, row["bits"]
    assert len(VR.list_verifications(st.root, statement_id="000000", limit=None)[0]) == 3

    # ---- 反真空：把旧写口放回落地那一步。
    real_land = VR.land_sign_without_ledger

    def _with_old_write(store, *, row, within_call=None, need=None,
                        review_call="", by="", manuscript=""):
        out = real_land(store, row=row, within_call=within_call, need=need,
                        review_call=review_call, by=by, manuscript=manuscript)
        VR.sign_statement(
            store, row=dict(row), proof_text=PROOF, append_ledger=False,
            sign_issuance={"checked": True, "issue": True,
                           "within_call": int(within_call or 0),
                           "need": int(need or VR.SIGN_STREAK_NEED),
                           "review_call": review_call}, by=by)
        return out

    monkeypatch.setattr(VR, "land_sign_without_ledger", _with_old_write)
    st2 = _ws(tmp_path / "restored")
    _put(st2, proof_text=PROOF, statement_full="设 G 是有限群；则结论成立。")
    _manuscript(st2, proof=PROOF, full="设 G 是有限群；则结论成立。")
    before2 = (pathlib.Path(st2.root) / "data" / "statements.json").read_bytes()
    got2 = _run(st2)
    after2 = (pathlib.Path(st2.root) / "data" / "statements.json").read_bytes()
    assert got2.get("checked") is True, got2
    assert after2 != before2, (
        "把旧的 sign_statement 放回去之后 statements 字节都没变 ⇒ 字节判据测不到它")
    assert dict(st2.rows("statements")[0])["bits"].get("reviewed") is True, (
        "旧写口放回去却没翻位 ⇒ 反真空没造对")


def test_citation_material_comes_from_the_manuscripts(tmp_path: pathlib.Path) -> None:
    """读 2/3：引用材料与依赖面审计都以手稿 `## 依赖` + 被引手稿签块为准。

    台账里故意放一条"引用了 999999"的依赖（V 不读它）；手稿的依赖表引用的是 000001。
    ⇒ V 的材料里只能出现 000001，且 000001 的手稿有签 ⇒ 可引；999999 不出现。
    """
    from agentflow import proofloc as PL

    st = _ws(tmp_path)
    _put(st, proof_text="1. 由引理得结论。", statement_full="主命题。")
    rel = "reports/f-proof-000000.md"
    path = pathlib.Path(st.root) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "# 证明手稿\n\n\n## 命题\n\n主命题。\n\n"
        "## 证明\n\n1. 由 stmt:000001 得结论（依据：stmt:000001）。\n\n"
        + DS.render_dependency_section([
            {"quote": "由引理，条件成立", "stmt_id": "000001", "step": "第 1 步",
             "path_group": 1}]),
        encoding="utf-8")
    # 被引命题的手稿 + 签名（够格被引）。
    lemma_rel = "reports/f-proof-000001.md"
    lemma_body = "1. 引理的证明。"
    (pathlib.Path(st.root) / lemma_rel).write_text(
        "# 引理手稿\n\n\n## 命题\n\n引理正文。\n\n"
        f"## 证明\n\n{lemma_body}\n\n" + DS.render_dependency_section([]),
        encoding="utf-8")
    raw = (pathlib.Path(st.root) / lemma_rel).read_text(encoding="utf-8")
    (pathlib.Path(st.root) / lemma_rel).write_text(
        VS.stamp_manuscript_sign(
            raw, proof_sha=VR.text_sha(lemma_body), streak=3, need=3,
            verdict="成立", signer="secretary:F", at="2026-11-08T00:00:00+08:00",
            ledger="verifications/000001.jsonl#v-000001",
            statement_id="000001", manuscript_id="000001"),
        encoding="utf-8")
    # 台账里的那条"引用了 999999"（V 不该读它）。
    with st.tx("dependencies", actor="test") as tx:
        tx.upsert("dependencies", {
            "dep_id": "000099", "used_by": PL.used_by_of("stmt:000000", 1),
            "kind": "lemma", "label": "台账里的假引用", "source_stmt_id": "999999",
            "status": "closed", "quote": "台账里的假引用", "path_group": 1,
            "created_at": "2026-11-08T00:00:00+08:00", "created_by": "test"})

    from agentflow import conductor as CND

    seam = _Seam()
    v = AgentV(st, workspace_root=st.root, llm=seam)
    with CND.calling_as("t-v-000001", "V", parent_task_id="t-f-000001",
                        parent_role="F"):
        got = v.verify_proof("000000", proof_manuscript=rel)
    ids = [str(c.get("stmt_id")) for c in got.get("citations") or []]
    assert ids == ["000001"], got.get("citations")
    assert "999999" not in json.dumps(got.get("citations"), ensure_ascii=False)
    assert got["citations"][0]["admissible"] is True, got["citations"][0]
    assert got["citations"][0]["manuscript"] == lemma_rel, got["citations"][0]


def test_dependency_audit_admits_by_manuscript_sign_not_by_statements_bits(
        tmp_path: pathlib.Path) -> None:
    """读 3：依赖面审计的可引资格读被引命题的手稿签块，不读 statements 的等级位。

    三档一条链（改前 V 读 statements.bits ⇒ 第一档会放行；改后必须按稿判）：
    a. 册里那一条 write_verified=True（旧口径够格），而盘上没有它的手稿 ⇒ 有毛病；
    b. 手稿在、但没有 V 签 ⇒ 仍然有毛病（等级不到门）；
    c. 手稿上盖了签 ⇒ 放行（过依赖面这一关）。
    """
    from agentflow import conductor as CND

    main = "000000"
    lemma = "000002"
    body = f"1. 由 stmt:{lemma} 得结论（依据：stmt:{lemma}）。"

    def _scene(tag: str) -> tuple[Store, str, dict]:
        st = _ws(tmp_path / tag)
        _put(st, proof_text=body, statement_full="主命题（依赖面夹具）。")
        rel = "reports/f-proof-000000.md"
        path = pathlib.Path(st.root) / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            f"# 证明手稿\n\n\n## 命题\n\n主命题（依赖面夹具）。\n\n"
            f"## 证明\n\n{body}\n\n"
            + DS.render_dependency_section([
                {"quote": "由引理得结论", "stmt_id": lemma, "step": "第 1 步",
                 "path_group": 1}]),
            encoding="utf-8")
        seed_statement_row(
            st, proof_text="1. 引理的证明。", statement_full="引理正文。",
            statement_text="引理正文。", kind="theorem", label="引理",
            origin="own_result", evidence_kind="proof",
            bits=EB.bits_of(proof=True, proof_process="1. 引理的证明。",
                            reviewed=True,
                            reviewed_by={"verification_id": "v-000001"},
                            kind="theorem"),
            stmt_id=lemma)
        v = AgentV(st, workspace_root=st.root, llm=_Seam())
        with CND.calling_as("t-v-000001", "V", parent_task_id="t-f-000001",
                            parent_role="F"):
            return st, rel, v.verify_proof(main, proof_manuscript=rel)

    # a：册里够格、盘上没有手稿 ⇒ 有毛病（挡签的点名里写"盘上没有…手稿"）。
    _st, _rel, got_a = _scene("no-manuscript")
    assert got_a.get("verdict") == "有毛病", got_a
    assert any((lemma in str(f.get("detail") or "") and "盘上没有" in str(f.get("detail") or ""))
               for f in (got_a.get("findings") or [])), got_a.get("findings")

    # b：手稿在、没有签 ⇒ 仍然有毛病（不是"在册就够格"）。
    st, rel, _ = _scene("unsigned")
    lemma_rel = "reports/f-proof-000002.md"
    (pathlib.Path(st.root) / lemma_rel).write_text(
        "# 引理手稿\n\n\n## 命题\n\n引理正文。\n\n"
        "## 证明\n\n1. 引理的证明。\n\n" + DS.render_dependency_section([]),
        encoding="utf-8")
    v = AgentV(st, workspace_root=st.root, llm=_Seam())
    with CND.calling_as("t-v-000001", "V", parent_task_id="t-f-000001",
                        parent_role="F"):
        got_b = v.verify_proof("000000", proof_manuscript=rel)
    assert got_b.get("verdict") == "有毛病", got_b
    assert any((lemma in str(f.get("detail") or "") and "V 签" in str(f.get("detail") or ""))
               for f in (got_b.get("findings") or [])), got_b.get("findings")

    # c：手稿上盖了签 ⇒ 依赖面这一关放行（至少不再出现那条 error）。
    raw = (pathlib.Path(st.root) / lemma_rel).read_text(encoding="utf-8")
    (pathlib.Path(st.root) / lemma_rel).write_text(
        VS.stamp_manuscript_sign(
            raw, proof_sha=VR.text_sha("1. 引理的证明。"), streak=3, need=3,
            verdict="成立", signer="secretary:F", at="2026-11-08T00:00:00+08:00",
            ledger="verifications/000002.jsonl#v-000001",
            statement_id=lemma, manuscript_id=lemma),
        encoding="utf-8")
    v2 = AgentV(st, workspace_root=st.root, llm=_Seam())
    with CND.calling_as("t-v-000001", "V", parent_task_id="t-f-000001",
                        parent_role="F"):
        got_c = v2.verify_proof("000000", proof_manuscript=rel)
    assert not [f for f in (got_c.get("findings") or [])
                if str(f.get("stmt_id") or "") == lemma], got_c.get("findings")
    assert got_c.get("verdict") == "成立", got_c

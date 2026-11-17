# -*- coding: utf-8 -*-
"""经审核的自证定理 ⇒ 进定理库并作证明链的根（业主 2026-10-17 口径）。

> *"自证定理在审核后要能进定理库。"*（并据此成为后续定理可引的根）

## 现场（长跑预演，`draft/136`）

一条 `origin="own_result"` 的自证命题（零文献依赖）：
- V 审过、判 成立（签第 3 位）⇒ 它应当进库、可作根、链闭合；
- 判 有毛病 / 没审 ⇒ 不许作根（三态不许折平）。

## 2026-11-02 的次序（业主：「V 签先放在 F 的手稿里，让 B 录入」）

正控不再走「B 登记 → V 判」，而是：先把手稿（`## 命题` / `## 证明`）交给 V 连判
三转、签块盖回稿，再让 B 拿着「稿里正文 + 手稿签块」收录。strict 准入闸下，
无签的证明正文经 `register_statement` 整笔写不进去，所以负控要的
"在册、有证明、还没签"这一历史形态由夹具直接铺行（真机 3134 行 own_result
正是这么来的）。

这一组用注入的假 seam（离线、确定，不调上游）：一个稳定返回 `{"verdict": "成立"}`，
另一个稳定返回 `{"verdict": "有毛病", "defect_step": 1}` ⇒ 两边都钉住。
"""

from __future__ import annotations

import json
import pathlib

import pytest

from _proof_manuscript_fixture import write_proof_manuscript

from agentflow import evidencebits as EB
from agentflow import verifications as VR
from agentflow import vsigns as VS
from agentflow.agent_b import AgentB
from agentflow.agent_c import AgentC
from agentflow.agent_v import AgentV
from agentflow.store import Store

from conftest import CleanVerdictSecretary, seed_statement_row, ensure_basis_stmt
from conftest import ensure_basis_lit

PROOF = "Proof. n^2+n=n(n+1)，相邻两数必有一偶。"
FULL = "若 n≥3 则 n^2+n 是偶数（自证）。"

#: 与 `agent_f/manuscript.py::proof_manuscript` 同一个形状（V 只读 `## 证明` 那一节）。
MANUSCRIPT = ("# F 的证明手稿：n^2+n 是偶数\n\n"
              "- 计划：0000 · 子目标：s1\n\n"
              f"## 命题\n\n{FULL}\n\n"
              f"## 证明\n\n{PROOF}\n\n"
              "## 依赖\n\n"
              "| 引用（F 的原话） | 命题号（stmt:NNNNNN） | 用在哪一步 | 路径号（第几条证明） |\n"
              "|---|---|---|---|\n"
              "（这一份证明没有引用任何在册命题 —— 空表就是声明。）\n")
#: 未在册时没有号。旧注释说计划稿 `f-proof-plan-*` "是合法落稿名、不是签的载体" ——
#: 2026-11-10 裁定之后它也是合法载体（老盘只读兼容；新稿不再写这种名字），拿它送审
#: 一样落签。这一份夹具仍用按号名：这一组测的是「稿名带号、签块第 8 格仍是 `未在册`」
#: 的现场（计划号不是命题号），且 `doc_id=000000` 与稿名同一形态。
REL = "reports/f-proof-000000.md"


class _FixedSeam:
    """假 seam：每次 `complete` 都回同一段 JSON（判据要的是可复现的审校）。"""

    def __init__(self, verdict: str) -> None:
        self.verdict = verdict
        self.calls = 0

    def complete(self, prompt: str, **kw) -> str:
        self.calls += 1
        payload = {"verdict": self.verdict, "findings": [], "proof_sha256": "0" * 64}
        if self.verdict != "成立":
            payload["defect_step"] = 1
        return json.dumps(payload, ensure_ascii=False)


def _store(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _write_manuscript(st: Store) -> pathlib.Path:
    path = pathlib.Path(st.root) / REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(MANUSCRIPT, encoding="utf-8")
    return path


def _seed_statement(st: Store) -> str:
    """造一条"在册、有证明、还没有 V 签"的命题（历史形态：直接铺行）。

    2026-11-02 准入闸默认 strict 之后，这个状态不能再经 `register_statement` 造出来
    （无签的证明正文整笔拒 `proof_without_v_sign`）—— 而这一组负控测的正是
    "这一行没审过 ⇒ 作不作根"。期望值与判据一个字都没改。
    """
    seeded = seed_statement_row(
        st, proof_text=PROOF, statement_full=FULL, statement_text=FULL,
        kind="conjecture", label="n^2+n 是偶数", origin="own_result",
        doc_id="000000", line_range={"start": 1}, quote_verified=False,
        quote_reason="自证：无外部引文",
        bits=EB.bits_of(origin="own_result", proof=True, proof_process=PROOF,
                        kind="conjecture"))
    return str(seeded.get("stmt_id") or "")


def _audited_statement(st: Store) -> str:
    """正控的现场：V 先审手稿（3 转成立 ⇒ 签块落稿）→ B 再收录。"""
    path = _write_manuscript(st)
    v = AgentV(st, llm=_FixedSeam("成立"), secretary=CleanVerdictSecretary("clean", st))
    # 2026-11-03 件一：未在册正判的块由收方秘书落 —— 先挂上"V 由 F 派出来"的身份。
    from agentflow import conductor as CND

    with CND.calling_as("t-v-000001", "V", parent_task_id="t-f-000001",
                        parent_role="F"):
        signed = v.verify_proof(proof_manuscript=REL)
    assert signed.get("checked") is True, signed
    assert signed.get("kind") == "proof_unregistered_signed", signed
    block = VS.manuscript_sign_standing(path.read_text(encoding="utf-8"),
                                        proof_sha=VR.text_sha(PROOF))
    assert block.get("state") == "signed", block

    b = AgentB(st, extractor=None, extract_text=None)
# 2026-11-17（业主裁定 ②）：own_result 必须写清来路；这一份夹具不测承重链，用形状合法的占位号。
    got = b.register_statement(origin="own_result", source_lit_id=ensure_basis_lit(st), statement_full=FULL,
                               statement_text=FULL, kind="conjecture",
                               proof_text=PROOF,
                               proof_manuscript=path.read_text(encoding="utf-8"),
                               line_range={"start": 1}, doc_id="000000",
                               quote_verified=False, quote_reason="自证：无外部引文")
    row = got if isinstance(got, dict) else got.to_dict()
    assert row.get("ok"), row
    sid = str(row.get("stmt_id") or "")
    bits = dict(next(r for r in st.rows("statements")
                     if str(r.get("stmt_id")) == sid).get("bits") or {})
    assert bits.get("reviewed") is True, bits
    # ---- 同一次审校的另一半：台账那一行 ----
    #
    # `AgentC` 的「经审核」判据只读台账（`proof_chain._verified_ok`：`verifications/<号>.jsonl`
    # 里有没有「成立」）；手稿签块是 B 收录时的凭据，不是台账行。两处是同一个写口
    # （V 的 `record_verification`）的两个落点 —— 三转签要各写各的，否则"经审核"这句
    # 话在 C 那一侧读不到。
    for _ in range(int(VR.SIGN_STREAK_NEED)):
        VR.record_verification(
            st.root, statement_id=sid, proof_text=PROOF,
            verdict={"verdict": "成立", "findings": []},
            verifier="agent-V", store=st, secretary_judge={"checked": True, "axis": "clean", "decision": "没问题", "reason": "夹具：秘书判 clean"})
    return sid


def _own_result_statement(st: Store) -> str:
    return _audited_statement(st)


def test_an_audited_self_proved_theorem_is_a_closed_root(tmp_path: pathlib.Path) -> None:
    """正控：审核判成立 ⇒ 该自证定理作根、链闭合。"""
    st = _store(tmp_path)
    sid = _own_result_statement(st)
    rep = AgentC(st).proof_chain(target=sid)
    data = rep if isinstance(rep, dict) else rep.to_dict()
    payload = data.get("payload") or {}
    assert payload.get("closed") is True, data.get("summary")
    assert payload.get("roots") == [sid], payload


def test_an_unaudited_statement_is_not_a_root(tmp_path: pathlib.Path) -> None:
    """负控：没审核 ⇒ 不作根、链不闭合（三态不许折平）。"""
    st = _store(tmp_path)
    sid = _seed_statement(st)
    rep = AgentC(st).proof_chain(target=sid)
    data = rep if isinstance(rep, dict) else rep.to_dict()
    payload = data.get("payload") or {}
    assert payload.get("closed") is False, data.get("summary")
    assert payload.get("roots") == [], payload


def test_a_flawed_verdict_does_not_make_it_a_root(tmp_path: pathlib.Path) -> None:
    """负控：审成有毛病 ⇒ 同样不许作根。"""
    st = _store(tmp_path)
    sid = _seed_statement(st)
    # 2026-11-04（业主裁定 甲）：在册命题送审必须带手稿（按号命名的那一份）。
    # 这一条判的是"有毛病 ⇒ 不作根"，判据一个字没改；补的只是签的载体。
    rel = write_proof_manuscript(st.root, sid, PROOF, statement_full=FULL)
    v = AgentV(st, llm=_FixedSeam("有毛病"), secretary=CleanVerdictSecretary("fault", st))
    got = v.verify_proof(sid, PROOF, proof_manuscript=rel)
    got = got if isinstance(got, dict) else got.to_dict()
    assert got.get("verdict") == "有毛病", got
    rep = AgentC(st).proof_chain(target=sid)
    data = rep if isinstance(rep, dict) else rep.to_dict()
    payload = data.get("payload") or {}
    assert payload.get("closed") is False, data.get("summary")

# -*- coding: utf-8 -*-
"""经审核的自证定理 ⇒ 进定理库并作证明链的根（业主 2026-10-17 口径）。

> *"自证定理在审核后要能进定理证明库。"*（并据此成为后续定理可引的根）

## 现场（长跑预演，`draft/136`）

一条 `origin="own_result"` 的自证命题（零文献依赖）：
- `V.verify_proof` 判 成立（签第 3 位）时 ⇒ 它应当进库、可作根、链闭合；
- 判 有毛病 / 没审 ⇒ 不许作根（三态不许折平）。

这一组用注入的假 seam（离线、确定，不调上游）：一个稳定返回 `{"verdict": "成立"}`，
另一个稳定返回 `{"verdict": "有毛病", "defect_step": 1}` ⇒ 两边都钉住。
"""

from __future__ import annotations

import json
import pathlib

import pytest

from agentflow.agent_b import AgentB
from agentflow.agent_c import AgentC
from agentflow.agent_v import AgentV
from agentflow.store import Store

PROOF = "Proof. n^2+n=n(n+1)，相邻两数必有一偶。"


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


def _own_result_statement(st: Store) -> str:
    b = AgentB(st, extractor=None, extract_text=None)
    got = b.register_statement(origin="own_result",
                               statement_full="若 n≥3 则 n^2+n 是偶数（自证）。",
                               kind="theorem", proof_text=PROOF,
                               line_range={"start": 1}, doc_id="000000",
                               quote_verified=False, quote_reason="自证：无外部引文")
    row = got if isinstance(got, dict) else got.to_dict()
    assert row.get("ok"), row
    return str(row.get("stmt_id") or "")


def test_an_audited_self_proved_theorem_is_a_closed_root(tmp_path: pathlib.Path) -> None:
    """正控：审核判成立 ⇒ 该自证定理作根、链闭合。"""
    st = _store(tmp_path)
    sid = _own_result_statement(st)
    v = AgentV(st, llm=_FixedSeam("成立"))
    out = v.verify_proof(sid, PROOF)
    got = out if isinstance(out, dict) else out.to_dict()
    assert got.get("verdict") == "成立", got
    rep = AgentC(st).proof_chain(target=sid)
    data = rep if isinstance(rep, dict) else rep.to_dict()
    payload = data.get("payload") or {}
    assert payload.get("closed") is True, data.get("summary")
    assert payload.get("roots") == [sid], payload


def test_an_unaudited_statement_is_not_a_root(tmp_path: pathlib.Path) -> None:
    """负控：没审核 ⇒ 不作根、链不闭合（三态不许折平）。"""
    st = _store(tmp_path)
    sid = _own_result_statement(st)
    rep = AgentC(st).proof_chain(target=sid)
    data = rep if isinstance(rep, dict) else rep.to_dict()
    payload = data.get("payload") or {}
    assert payload.get("closed") is False, data.get("summary")
    assert payload.get("roots") == [], payload


def test_a_flawed_verdict_does_not_make_it_a_root(tmp_path: pathlib.Path) -> None:
    """负控：审成有毛病 ⇒ 同样不许作根。"""
    st = _store(tmp_path)
    sid = _own_result_statement(st)
    v = AgentV(st, llm=_FixedSeam("有毛病"))
    v.verify_proof(sid, PROOF)
    rep = AgentC(st).proof_chain(target=sid)
    data = rep if isinstance(rep, dict) else rep.to_dict()
    payload = data.get("payload") or {}
    assert payload.get("closed") is False, data.get("summary")

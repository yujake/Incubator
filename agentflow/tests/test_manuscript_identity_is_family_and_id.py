# -*- coding: utf-8 -*-
"""稿的身份 = `(族, 稿号)`，不是单号（2026-11-15，EC 路）。

## 这一份钉什么

| # | 造什么 | 期望 |
|---|---|---|
| a | E 同号跨族：`e-proof-000000`（已签）+ `e-num-000000` | `signed_candidates` 两个候选、各自一个状态、不 `ambiguous_path`；E 的收工门 `complete=True` |
| a2 | 门里 `cands` 的索引：e-proof 未签在前、e-num 在后 | 门必须仍看见 e-proof 那份欠签（`complete=False`）—— 只修分桶不够，门内索引也要按 `(族, 号)` |
| b | F/B 同号跨族：`f-proof-000040` + `b-proof-000040`（都真签） | 两个族各一个候选、各自 `state="signed"`、不 `ambiguous_path`；F / B 两道门都放行 |
| c | E 的 `e-proof-000000` 没签 + `e-num-000000` 有稿 | 仍受控拒（`complete=False`）—— 修掉假 ambiguity 不许把「真缺签」也改宽 |
| d | 同族同号两份不同字节的文件 | 仍 `state="ambiguous_path"`（真 ambiguity 保护不许被改宽） |

## 为什么 a / a2 在改前会红

`signed_candidates` 原来按 `manuscript_id` 单键分桶：E 的 `e-proof` 与 `e-num` 各有
独立号段、都从 `000000` 起 ⇒ `reports/e-proof-000000.md` 与 `reports/e-num-000000.md`
被折进同一个桶 ⇒ `len(paths)>1` ⇒ `ambiguous_path` ⇒ E 的 final 被收工门拒。
`agent_loop._v_wait_gate_reading` 的 `cands[mid]` 也同键覆盖：两处都改，a 只覆盖
第一处；a2 把第二处单独钉住（把门退回 `cands[mid]`，a2 实测红）。V 的签与 B 的收编
不受影响，只有 E 自己收不了工。

## d 的造法（以及为什么需要那一格桩）

族表（`manuscriptfamily`）只认 `reports/<族>-<号>.md` 这一种名字，所以在大小写
不敏感的文件系统上，「同一族、同一号、两份不同文件」本来造不出来 —— 这不是本判据
要放过的情形，而是名字表的边界。d 因此把第二份文件的名字→`(族, 号)` 这一格用桩
接上（`classify_manuscript` 只对该测试路径返回同一族/号），分桶与 ambiguity 判据
本体一个字节没改；两份文件是真的不同字节。把 `len(paths)>1` 那一条删掉，d 会红。
"""
from __future__ import annotations

import hashlib
import json
import pathlib

from agentflow import agent_loop as AL
from agentflow import depsection as DS
from agentflow import manuscriptclosing as MC
from agentflow import proofregistry as PR
from agentflow import verifications as VR
from agentflow import vsigns as VS
from agentflow.store import Store

TS = "2026-11-15T10:00:00+08:00"
FULL = "对 n <= 40 的偶数 n，n^2 + 2 都不是 3 的倍数。"
BODY = ("1. 逐个枚举 n<=40 的偶数，命中全部。\n"
        "2. 枚举覆盖区间两端，没有遗漏。")


# ---------------------------------------------------------------- 夹具
def _ws(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _text(family: str, *, body: str = BODY, experiment_id: str = "000000") -> str:
    """一行稿头 + 命题 + 该族该有的那一节（e-num 没有 `## 证明`）。"""
    head = [f"# E 的{'数值' if family == 'e-num' else '证明'}手稿：夹具", "",
            f"- 实验号：exp:{experiment_id}", ""]
    if family == "e-num":
        return "\n".join(head + ["## 命题", "", FULL, "", "## 数值结果", "",
                                 "supports（n<=40 的偶数逐个检查）", ""])
    return "\n".join(head + ["## 命题", "", FULL, "", "## 证明", "", body, "",
                             DS.render_dependency_section([])])


def _write(st: Store, family: str, mid: str, *, body: str = BODY,
           experiment_id: str = "000000") -> str:
    rel = f"reports/{family}-{mid}.md"
    path = pathlib.Path(st.root) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_text(family, body=body, experiment_id=experiment_id),
                    encoding="utf-8")
    return rel


def _sign(st: Store, rel: str, *, body: str = BODY) -> dict:
    """走 V 那条真路（三行 pending 台账 + `vsigns.issue`），不写假签块。"""
    text = (pathlib.Path(st.root) / rel).read_text(encoding="utf-8")
    rows = [VR.record_pending_sign(
        st.root, proof_text=body, verdict={"verdict": "成立", "findings": []},
        verifier="agent-V", object_path=rel,
        secretary_judge={"checked": True, "axis": "clean", "decision": "没问题",
                         "reason": "夹具：clean"}) for _ in range(3)]
    key = str(rows[0].get("object_sha256") or rows[0].get("proof_sha256") or "")
    passes = [{"verification_id": r["verification_id"], "at": r["at"],
               "proof_sha256": r["proof_sha256"]} for r in rows]
    return VS.issue(st.root, artifact_sha=PR.proof_sha(text), streak=3, need=3,
                    artifact_path=rel,
                    ledger=f"verifications/pending/{key}.jsonl"
                           f"#{rows[-1]['verification_id']}",
                    statement_id="", passes=passes, by="secretary:E", store=st)


def _experiment(st: Store, eid: str = "000000") -> None:
    with st.tx("experiments", actor="fixture") as tx:
        tx.upsert("experiments", {
            "experiment_id": eid, "claim": FULL, "claim_key": f"K-{eid}",
            "method": "numeric", "params": {}, "exit_code": 0,
            "result": "supports", "evidence_kind": "cross_check",
            "negation_kind": "not_proved", "observations": {"n": 40},
            "status": "active", "created_at": TS, "created_by": "fixture",
        })


class _Shell:
    """把收工门挂到一个只有四格属性的壳上（与 `test_yi_...` 同一手法）。"""

    max_final_refused = 3
    conductor = None

    def __init__(self, st: Store, role: str) -> None:
        self.role = role
        self.my_task_id = "t-000001"
        self.store = st
        self.workspace_root = str(st.root)

    def _v_wait_gate_reading(self) -> dict:
        return AL.AgentLoop._v_wait_gate_reading(self)


def _by_family(scan: dict) -> dict[str, dict]:
    return {str(c.get("family") or ""): dict(c) for c in (scan.get("candidates") or [])}


# ============================================================ a：E 同号跨族
def test_a_e_proof_and_e_num_with_the_same_id_are_two_manuscripts(tmp_path):
    """a：`e-proof-000000`（已签）+ `e-num-000000` ⇒ 两个对象、E 收工门放行。"""
    st = _ws(tmp_path)
    _experiment(st, "000000")
    proof = _write(st, "e-proof", "000000")
    num = _write(st, "e-num", "000000")
    assert _sign(st, proof).get("written") is True

    scan = MC.signed_candidates(st.root, families=("e-proof", "e-num"))
    assert len(scan["candidates"]) == 2, scan["candidates"]
    got = _by_family(scan)
    assert set(got) == {"e-proof", "e-num"}, got
    assert got["e-proof"]["manuscript_id"] == "000000", got["e-proof"]
    assert got["e-num"]["manuscript_id"] == "000000", got["e-num"]
    assert got["e-proof"]["manuscript"] == proof, got["e-proof"]
    assert got["e-num"]["manuscript"] == num, got["e-num"]
    assert got["e-proof"]["state"] == "signed" and got["e-proof"]["signed"] is True
    # e-num 永远 unsigned（绿色通道不签），但它是另一份稿、不是 ambiguous。
    assert got["e-num"]["state"] == "unsigned" and got["e-num"]["signed"] is False
    assert all(one["state"] != "ambiguous_path" for one in got.values()), got

    gate = _Shell(st, "E")._v_wait_gate_reading()
    assert gate.get("applicable") is True, gate
    assert gate.get("checked") is True, gate
    assert gate.get("complete") is True, gate
    assert gate.get("problems") == [], gate
    assert {m["family"] for m in gate["manuscripts"]} == {"e-proof", "e-num"}, gate


# ============================================================ a2：门内索引也按 (族, 号)
def test_a2_the_gate_indexes_candidates_by_family_and_id(tmp_path, monkeypatch):
    """a2：只修 `signed_candidates` 不够 —— 门里的 `cands` 也必须按 `(族, 号)` 索引。

    造法：把 `signed_candidates` 的返回按「e-proof 先、e-num 后」的顺序钉死
    （e-proof 未签、e-num 无签正常）。单号索引会让后到的 e-num 覆盖 e-proof，
    门于是看不见「e-proof 未签」而放行；`(族, 号)` 索引必须挡住。
    """
    st = _ws(tmp_path)
    proof = _write(st, "e-proof", "000000")
    num = _write(st, "e-num", "000000")
    fake = {
        "checked": True, "problems": [], "why": "夹具：两个不同族的同号稿",
        "candidates": [
            {"family": "e-proof", "manuscript_id": "000000", "manuscript": proof,
             "state": "unsigned", "signed": False, "why": "未签"},
            {"family": "e-num", "manuscript_id": "000000", "manuscript": num,
             "state": "unsigned", "signed": False, "why": "未签"},
        ],
    }
    monkeypatch.setattr(MC, "signed_candidates", lambda *a, **k: fake)

    gate = _Shell(st, "E")._v_wait_gate_reading()
    assert gate.get("complete") is False, gate
    assert any("e-proof-000000" in str(p.get("where") or "")
               for p in (gate.get("problems") or [])), gate
    assert {m["family"] for m in gate["manuscripts"]} == {"e-proof", "e-num"}, gate


# ============================================================ b：F / B 同号跨族
def test_b_f_proof_and_b_proof_with_the_same_id_are_two_manuscripts(tmp_path):
    """b：`f-proof-000040` 与 `b-proof-000040` 各自可签、不 ambiguous。"""
    st = _ws(tmp_path)
    f_body = BODY + "\n3. F 这一条路径的收尾标记。"
    b_body = BODY + "\n3. B 这一条路径的收尾标记。"
    f_rel = _write(st, "f-proof", "000040", body=f_body)
    b_rel = _write(st, "b-proof", "000040", body=b_body)
    assert _sign(st, f_rel, body=f_body).get("written") is True
    assert _sign(st, b_rel, body=b_body).get("written") is True

    scan = MC.signed_candidates(st.root, families=("f-proof", "b-proof"))
    assert len(scan["candidates"]) == 2, scan["candidates"]
    got = _by_family(scan)
    assert set(got) == {"f-proof", "b-proof"}, got
    assert got["f-proof"]["manuscript_id"] == got["b-proof"]["manuscript_id"] == "000040"
    assert got["f-proof"]["manuscript"] == f_rel, got["f-proof"]
    assert got["b-proof"]["manuscript"] == b_rel, got["b-proof"]
    assert got["f-proof"]["state"] == "signed" and got["f-proof"]["signed"] is True
    assert got["b-proof"]["state"] == "signed" and got["b-proof"]["signed"] is True
    assert all(one["state"] != "ambiguous_path" for one in got.values()), got

    for role in ("F", "B"):
        gate = _Shell(st, role)._v_wait_gate_reading()
        assert gate.get("complete") is True, (role, gate)
        assert gate.get("problems") == [], (role, gate)


# ============================================================ c：真缺签仍拒
def test_c_an_unsigned_e_proof_next_to_an_e_num_is_still_refused(tmp_path):
    """c：修掉假 ambiguity ≠ 把「e-proof 真没签」改宽 —— 它必须仍然受控拒。"""
    st = _ws(tmp_path)
    _experiment(st, "000000")
    _write(st, "e-proof", "000000")
    _write(st, "e-num", "000000")
    gate = _Shell(st, "E")._v_wait_gate_reading()
    assert gate.get("applicable") is True, gate
    assert gate.get("complete") is False, gate
    why = str(gate.get("why") or "")
    assert "e-proof-000000" in why, why
    assert "unsigned" in why, why
    assert "ambiguous_path" not in why, why


# ============================================================ d：真 ambiguity 仍判
def test_d_two_different_files_with_the_same_family_and_id_are_still_ambiguous(
        tmp_path, monkeypatch):
    """d：同族 + 同号 + 两份不同字节的文件 ⇒ 仍 `ambiguous_path`（不许改宽）。

    族表只认 `reports/<族>-<号>.md`，所以同族同号两份文件在正常命名下造不出来；
    这里只把第二份文件名的「名字→(族, 号)」那一格用桩接上，分桶与 ambiguity 判据
    本体不动。两份文件真的不同字节（下面先断言这一点）。
    """
    st = _ws(tmp_path)
    first = "reports/e-proof-000000.md"
    second = "reports/e-proof-000000-dup.md"
    _write(st, "e-proof", "000000", body=BODY)
    pathlib.Path(st.root, second).write_text(
        _text("e-proof", body=BODY + "\n3. 这一份是另一份文件（不同字节）。"),
        encoding="utf-8")
    sha_first = hashlib.sha256(pathlib.Path(st.root, first).read_bytes()).hexdigest()
    sha_second = hashlib.sha256(pathlib.Path(st.root, second).read_bytes()).hexdigest()
    assert sha_first != sha_second, "夹具前提：两份文件必须不同字节"

    real = MC._MFAM.classify_manuscript

    def _one_family(rel):
        if str(rel).replace("\\", "/") == second:
            reading = dict(real(first))
            reading.update(name=pathlib.PurePosixPath(second).name,
                           canonical=second, directory="reports")
            return reading
        return real(rel)

    monkeypatch.setattr(MC._MFAM, "classify_manuscript", _one_family)

    # 两份签（文件名 = 各自正文 sha），各指一份文件；复算不上不影响分桶与 ambiguous 判定。
    signs = VS.signs_dir(st.root)
    signs.mkdir(parents=True, exist_ok=True)
    for sha, rel in ((sha_first, first), (sha_second, second)):
        (signs / f"{sha}.json").write_text(json.dumps({
            "artifact_sha": sha, "artifact_path": rel, "verdict": "成立",
            "at": TS, "streak": 3, "need": 3, "statement_id": "",
        }, ensure_ascii=False), encoding="utf-8")

    scan = MC.signed_candidates(st.root, families=("e-proof",))
    assert len(scan["candidates"]) == 1, scan["candidates"]
    cand = dict(scan["candidates"][0])
    assert cand["family"] == "e-proof", cand
    assert cand["manuscript_id"] == "000000", cand
    assert cand["state"] == "ambiguous_path", cand
    assert cand["signed"] is False, cand
    assert first in cand["why"] and second in cand["why"], cand["why"]

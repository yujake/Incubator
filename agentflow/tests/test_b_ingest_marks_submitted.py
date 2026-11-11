# -*- coding: utf-8 -*-
"""丙：B 收录时置「已提交」+ 多证明路径号（业主 2026-11-11 裁定 ③ 与追加裁定）。

业主逐字：
    「如果产出方是 B，则该在它将稿存进台账时更新状态为已提交。」
    「多证明路径是 B 秘书需要关注的。如果对它判断同一的命题提交了多份证明，
      则排进不同路径。」

## 这一份钉什么

| # | 造什么 | 期望 |
|---|---|---|
| a | B 收录一份已签的 `b-proof-*` | B 那一行 `artifacts` 出现一枚 `mss:<稿号>`；`submission_reading` 读 `submitted` / `via=ingested_to_ledger` |
| b | 同一份稿再收录一次 | 幂等：不重复写；`b_submission.already` |
| c | 收录受控拒（未签） | 不置已提交（artifacts 不变） |
| d | 反真空：摘掉这一笔 | a 必须红 |
| e | 同一命题收第二份不同正文的证明 | 两条路径（1 与 2），依赖行与 verification 行同号 |
| f | 重复收录同一份稿（同 sha） | 仍是 1/2 条路径，不新增 |
| g | 反真空：把「分配新路径」改成「永远 1」 | e 必须红 |
| h | 同一命题两份都已签的证明收录之后 | `reviewed_by_proof` 有 1 与 2、sha 表两格各记自己那份；两个号都认得出 `signed`（缺陷：改前只有 `{1: True}`） |
| i | 路径号三处对齐 | `dependencies.path_group` / `used_by` 的号 / `verifications` 行的 `path_group` 是同一个号 |
| j | 反真空：把 `borrowed` 改回按号比 | 第二笔收录受控拒，且 h 的判据报出 #2（新签不写 `proof_no`，按号比必然借光） |

收取走 `ingest_manuscript(mode="apply")`（签回来之后 B 的收录正路），
签用 conftest 的真写口（零模型调用）。
"""
from __future__ import annotations

import pathlib

import pytest
import conftest
from agentflow import conductor as CND
from agentflow import depsection as DS
from agentflow import evidencebits as EB
from agentflow import manuscriptsubmission as MS
from agentflow import schema as S
from agentflow import verifications as VR
from agentflow.agent_b import AgentB
from agentflow.store import Store

SID = "000001"
DEP_SID = "000002"
PROPOSITION = "对任意有限群 G，若 p 整除 |G|，则 G 有 p 阶元。"
PROOF1 = ("1. 取 G 的一个 Sylow p-子群 P（二阶 Sylow 定理）。\n"
          "2. |P| = p^a > 1 ⇒ 取 1 ≠ x ∈ P，由拉格朗日定理 ord(x) 是 p 的幂。")
PROOF2 = ("1. 对 |G| 归纳：取中心元 z，把 G 分成若干共轭类。\n"
          "2. 每个共轭类大小被 p 整除或与 p 互素，计数给出 p 阶元。")
OTHER_PROOF = "1. n^2 - n = n(n-1)。\n2. 相邻两整数一奇一偶 ⇒ 乘积是偶数。"


def _ws(tmp_path: pathlib.Path) -> tuple[Store, AgentB]:
    st = Store(tmp_path / "ws")
    st.init()
    return st, AgentB(st, extractor=None, extract_text=None, config={})


def _task(st: Store, *, task_id: str = "t-000001") -> dict:
    row = S.Task(task_id=task_id, role="B", action="ingest_manuscript",
                 called_by="D", depth=1, status="running", started_at=S.now_iso(),
                 input_key="b-ingest-fixture")
    row.validate()
    with st.tx("tasks", actor="fixture") as tx:
        tx.upsert("tasks", row.to_dict())
    return row.to_dict()


def _manuscript(*, sid: str = SID, proof: str = PROOF1, dep: str = "",
                proof_no: int = 0) -> str:
    deps = ("| 引用（F 的原话） | 命题号（stmt:NNNNNN） | 用在哪一步 | 路径号（第几条证明） |\n"
            "|---|---|---|---|\n")
    if dep:
        deps += f"| 引理 | stmt:{dep} | 1 | 1 |\n"
    head = f"- 命题号：stmt:{sid}\n- 证据种类：theorem\n"
    suffix = f"-p{proof_no}" if proof_no >= 2 else ""
    return (head + "\n## 命题\n\n" + PROPOSITION + "\n\n"
            "## 证明\n\n" + proof + "\n\n## 依赖\n\n" + deps)


def _write(st: Store, rel: str, text: str) -> pathlib.Path:
    path = pathlib.Path(st.root) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _citable(st: Store) -> None:
    conftest.seed_statement_row(st, stmt_id=DEP_SID, statement_full="引理：…",
                                kind="lemma", proof_text="引理：…")
    conftest.sign_for_the_gate(st.root, statement_id=DEP_SID,
                               proof_text="引理：…", store=st)
    row = next(dict(r) for r in st.rows("statements")
               if str(r.get("stmt_id")) == DEP_SID)
    bits = dict(row.get("bits") or {})
    bits["proof"] = True
    ev = dict(bits.get("evidence") or {})
    ev.setdefault("proof_process", str(row.get("proof_text") or "（夹具：引理）"))
    bits["evidence"] = ev
    bits["grade"] = EB.derive_grade(bits, kind="lemma")
    with st.tx("statements", actor="夹具") as tx:
        tx.upsert("statements", dict(row, bits=bits))


def _signed_proof(st: Store, rel: str, proof: str) -> None:
    conftest.sign_for_the_gate(st.root, statement_id=SID, proof_text=proof,
                               store=st, manuscript=rel)


def _ingest(b: AgentB, rel: str, *, cells: list[str], task_id: str = "t-000001") -> dict:
    with CND.calling_as(task_id, "B", parent_task_id="t-000009", parent_role="D"):
        return b.ingest_manuscript(manuscript=rel, target_stmt_id=SID,
                                   cells=cells, mode="apply")


def _artifacts(st: Store, task_id: str = "t-000001") -> list[str]:
    row = next(dict(r) for r in st.rows("tasks")
               if str(r.get("task_id")) == task_id)
    return [str(x) for x in (row.get("artifacts") or [])]


# ============================================================ a：收录即提交
def test_a_ingest_marks_the_b_manuscript_submitted(tmp_path):
    st, b = _ws(tmp_path)
    _task(st)
    conftest.seed_statement_row(st, stmt_id=SID, statement_full=PROPOSITION,
                                kind="theorem")
    rel = "reports/b-proof-000001.md"
    _write(st, rel, _manuscript())
    _signed_proof(st, rel, PROOF1)
    got = _ingest(b, rel, cells=["proof_text"])
    assert got.get("ok") is True, got
    assert got.get("b_submission", {}).get("written") is True, got.get("b_submission")
    tokens = MS.submissions_of(_artifacts(st))
    assert "000001" in tokens[0], tokens
    read = MS.submission_reading(st, st.root, manuscript_id="000001")
    assert read["state"] == "submitted", read
    assert read["via"] == MS.VIA_INGEST, read
    assert read["producer_role"] == "B", read
    assert read["submitted_at"], read
    assert read["token"].startswith("mss:000001"), read


# ============================================================ b：幂等
def test_b_a_second_ingest_does_not_write_again(tmp_path):
    st, b = _ws(tmp_path)
    _task(st)
    conftest.seed_statement_row(st, stmt_id=SID, statement_full=PROPOSITION,
                                kind="theorem")
    rel = "reports/b-proof-000001.md"
    _write(st, rel, _manuscript())
    _signed_proof(st, rel, PROOF1)
    first = _ingest(b, rel, cells=["proof_text"])
    assert first.get("b_submission", {}).get("written") is True, first
    before = list(_artifacts(st))
    second = _ingest(b, rel, cells=["proof_text"])
    assert second.get("ok") is True, second
    assert second.get("b_submission", {}).get("already") is True, second.get("b_submission")
    assert list(_artifacts(st)) == before, "第二次收录又写了一遍提交记号"


# ============================================================ c：受控拒不置已提交
def test_c_a_refused_ingest_does_not_mark_submitted(tmp_path):
    st, b = _ws(tmp_path)
    _task(st)
    conftest.seed_statement_row(st, stmt_id=SID, statement_full=PROPOSITION,
                                kind="theorem")
    rel = "reports/b-proof-000001.md"
    _write(st, rel, _manuscript(proof=OTHER_PROOF))  # 没签
    got = _ingest(b, rel, cells=["proof_text"])
    assert got.get("ok") is False, got
    assert _artifacts(st) == [], "受控拒的收录被写成了已提交"
    assert got.get("b_submission", {}).get("written") is False, got.get("b_submission")


# ============================================================ d：反真空
def test_d_stubbing_the_marker_turns_a_red(tmp_path, monkeypatch):
    st, b = _ws(tmp_path)
    _task(st)
    conftest.seed_statement_row(st, stmt_id=SID, statement_full=PROPOSITION,
                                kind="theorem")
    rel = "reports/b-proof-000001.md"
    _write(st, rel, _manuscript())
    _signed_proof(st, rel, PROOF1)

    def _noop(store, root, *, manuscript, out, family="", task_id="", stamp=""):
        out["b_submission"] = {"checked": False, "written": False,
                              "why": "打桩：不置已提交"}
        return out

    monkeypatch.setattr(MS, "mark_ingested", _noop)
    got = _ingest(b, rel, cells=["proof_text"])
    assert got.get("ok") is True, got
    assert _artifacts(st) == [], (
        "摘掉置「已提交」这一笔之后 artifacts 仍然有记号 —— 那不是这一笔写的")
    with pytest.raises(AssertionError):
        assert "000001" in MS.submissions_of(_artifacts(st))[0]


# ============================================================ e/f：路径号
def _path_fixture(tmp_path):
    st, b = _ws(tmp_path)
    _task(st)
    conftest.seed_statement_row(st, stmt_id=SID, statement_full=PROPOSITION,
                                kind="theorem")
    _citable(st)
    rel1 = "reports/b-proof-000001.md"
    rel2 = "reports/b-proof-000002.md"
    _write(st, rel1, _manuscript(proof=PROOF1, dep=DEP_SID))
    _signed_proof(st, rel1, PROOF1)
    _write(st, rel2, _manuscript(proof=PROOF2, dep=DEP_SID))
    _signed_proof(st, rel2, PROOF2)
    first = _ingest(b, rel1, cells=["proof_text", "dependencies"])
    second = _ingest(b, rel2, cells=["proof_text", "dependencies"])
    assert first.get("ok") is True, first
    assert second.get("ok") is True, second
    return st, b, rel1, rel2


def test_e_two_different_proofs_get_two_paths(tmp_path):
    st, _b, _rel1, _rel2 = _path_fixture(tmp_path)
    deps = [dict(r) for r in st.rows("dependencies")]
    groups = sorted({int(r.get("path_group") or 1) for r in deps})
    assert groups == [1, 2], deps
    assert {str(r.get("used_by")) for r in deps} == {f"stmt:{SID}",
                                                    f"stmt:{SID}#p2"}, deps
    rows, _bad = VR.list_verifications(st.root, statement_id=SID, limit=None)
    by_sha = {str(r.get("proof_sha256")): int(r.get("path_group") or 0) for r in rows}
    from agentflow import proofregistry as PR

    assert by_sha[PR.proof_sha(PROOF1)] == 1, by_sha
    assert by_sha[PR.proof_sha(PROOF2)] == 2, by_sha
    reading = MS.path_reading(st, st.root, statement_id=SID)
    assert reading["checked"] is True and reading["count"] == 2, reading
    assert {p["manuscript_id"] for p in reading["paths"]} == {"000001", "000002"}, reading
    # c：渲染出来的依赖表两行在「路径号」列可区分
    render_rows = [{"stmt_id": str(r.get("source_stmt_id") or ""),
                    "quote": str(r.get("label") or ""), "step": 1,
                    "path_group": int(r.get("path_group") or 1)} for r in deps]
    section = DS.render_dependency_section(render_rows)
    lines = [ln for ln in section.splitlines() if f"stmt:{DEP_SID}" in ln]
    assert len(lines) == 2, section
    assert "| 1 |" in lines[0] and "| 2 |" in lines[1], lines


def test_f_re_ingesting_the_same_proof_does_not_add_a_third_path(tmp_path):
    st, b, rel1, rel2 = _path_fixture(tmp_path)
    before = MS.path_reading(st, st.root, statement_id=SID)
    again = _ingest(b, rel2, cells=["proof_text", "dependencies"])
    assert again.get("ok") is True, again
    after = MS.path_reading(st, st.root, statement_id=SID)
    assert after["count"] == before["count"] == 2, (before, after)
    deps = [dict(r) for r in st.rows("dependencies")]
    assert sorted({int(r.get("path_group") or 1) for r in deps}) == [1, 2], deps


# ============================================================ g：反真空
def test_g_forcing_path_one_turns_e_red(tmp_path, monkeypatch):
    st, b = _ws(tmp_path)
    _task(st)
    conftest.seed_statement_row(st, stmt_id=SID, statement_full=PROPOSITION,
                                kind="theorem")
    _citable(st)
    rel1 = "reports/b-proof-000001.md"
    rel2 = "reports/b-proof-000002.md"
    _write(st, rel1, _manuscript(proof=PROOF1, dep=DEP_SID))
    _signed_proof(st, rel1, PROOF1)
    _write(st, rel2, _manuscript(proof=PROOF2, dep=DEP_SID))
    _signed_proof(st, rel2, PROOF2)
    assert _ingest(b, rel1, cells=["proof_text", "dependencies"]).get("ok") is True

    def _always_one(**_kw):
        return {"checked": True, "path_group": 1, "existing": False, "count": 1,
                "paths": [], "why": "打桩：永远第 1 条"}

    monkeypatch.setattr(MS, "assign_path_group", _always_one)
    second = _ingest(b, rel2, cells=["proof_text", "dependencies"])
    assert second.get("ok") is False, (
        "把「分配新路径」改成「永远 1」之后第二份证明仍然收进去了", second)
    deps = [dict(r) for r in st.rows("dependencies")]
    groups = sorted({int(r.get("path_group") or 1) for r in deps})
    assert groups == [1], deps


# ============================================================ a/b：路径号一路到底
def _per_path_problems(st: Store) -> list[str]:
    """判据 a 的本体（正控与反真空共用同一份读数）。

    两条路径都已签 ⇒ 收录之后：`reviewed_by_proof` 两格都真、`reviewed_sha_by_proof`
    两格各记自己那份正文的 sha、`sign_reading` 对两个号都说 `signed`。空清单 = 都对。

    抽成函数是为了让反真空打同一份判据：把 `borrowed` 改回按号比，它必须报出 #2
    那一份（否则"两条路径都签"这句话可能只是没真的比过）。
    """
    problems: list[str] = []
    row = next(dict(r) for r in st.rows("statements")
               if str(r.get("stmt_id")) == SID)
    per = EB.reviewed_by_proof(row)
    if per != {1: True, 2: True}:
        problems.append(f"逐条表不是两条路径都真：{per!r}（期望 {{1: True, 2: True}}）")
    sha_by = EB.reviewed_sha_by_proof(row)
    from agentflow import proofregistry as PR
    from agentflow import vsigns as VS

    for no, text in ((1, PROOF1), (2, PROOF2)):
        want = PR.proof_sha(text)
        if sha_by.get(no) != want:
            problems.append(f"#{no} 的 sha 表不是这一份正文（{sha_by.get(no)!r}）")
        got = VS.sign_reading(st.root, statement_id=SID, proof_text=text,
                              proof_no=no, store=st)
        if str(got.get("state") or "") != "signed":
            problems.append(f"#{no} 的认签不是 signed：{got.get('state')!r}"
                            f"（{got.get('why') or ''}）")
    return problems


def test_h_both_signed_paths_are_in_the_per_proof_table(tmp_path):
    """a) 同一命题的两份已签证明收录后：逐条表有 1 和 2，各自 verdict 对。

    改前红：`reviewed_by_proof` 只有 `{1: True}` —— B 收录第 2 份时用 canonical 号
    重放证据（`_ingest_apply_evidence(proof_no=want_no)`），读的是 #p1 的正文；
    而认签按号比又把第 2 条路径读成 `borrowed`（签文件里没有 `proof_no`）。
    """
    st, _b, _rel1, _rel2 = _path_fixture(tmp_path)
    assert _per_path_problems(st) == [], _per_path_problems(st)


def test_i_the_path_number_is_the_same_on_dependencies_and_verifications(tmp_path):
    """b) B 写的 `dependencies.path_group` 与 `verifications` 行同号（同一份证明一个号）。

    依赖行的 `used_by`（`stmt:…` / `stmt:…#p2`）与 `path_group` 是同一个号；台账里
    覆盖那一份正文的行也必须是同一个号 —— 三处任一处按 canonical 号写，G 的映射表
    就会把两条路径读成一维。
    """
    st, _b, _rel1, _rel2 = _path_fixture(tmp_path)
    from agentflow import proofregistry as PR

    deps = [dict(r) for r in st.rows("dependencies")]
    assert {str(r.get("used_by")) for r in deps} == {f"stmt:{SID}", f"stmt:{SID}#p2"}
    deps_by_group = {int(r.get("path_group") or 1): r for r in deps}
    assert sorted(deps_by_group) == [1, 2], deps
    rows, bad = VR.list_verifications(st.root, statement_id=SID, limit=None)
    assert not bad, bad
    ver_by_sha = {str(r.get("proof_sha256")): int(r.get("path_group") or 0)
                  for r in rows}
    for group, text in ((1, PROOF1), (2, PROOF2)):
        assert int(deps_by_group[group].get("path_group") or 1) == group, deps_by_group
        assert ver_by_sha.get(PR.proof_sha(text)) == group, (group, ver_by_sha)


def test_j_restoring_the_number_comparison_turns_a_red(tmp_path, monkeypatch):
    """f) 反真空：把 `borrowed` 的判据改回"按号比" ⇒ a 必红。

    2026-11-11 之前 `vsigns._reading_with_credential` 比的是
    `int(sign.get("proof_no") or 1) != no`；新签文件不写 `proof_no`，于是 #2 会被
    读成 `borrowed`。这里把那一条打桩回老形态，走同一条收录路：第二笔必须受控拒，
    且 a 的判据必须报出 #2。
    """
    st, b = _ws(tmp_path)
    _task(st)
    conftest.seed_statement_row(st, stmt_id=SID, statement_full=PROPOSITION,
                                kind="theorem")
    _citable(st)
    rel1 = "reports/b-proof-000001.md"
    rel2 = "reports/b-proof-000002.md"
    _write(st, rel1, _manuscript(proof=PROOF1, dep=DEP_SID))
    _signed_proof(st, rel1, PROOF1)
    _write(st, rel2, _manuscript(proof=PROOF2, dep=DEP_SID))
    _signed_proof(st, rel2, PROOF2)
    assert _ingest(b, rel1, cells=["proof_text", "dependencies"]).get("ok") is True

    def _by_number(sign, *, sid, no):
        cred_sid = str(sign.get("statement_id") or "").strip()
        try:
            cred_no = int(sign.get("proof_no") or 1)
        except (TypeError, ValueError):
            cred_no = 0
        if (sid and cred_sid and cred_sid != sid) or cred_no != no:
            return False, f"打桩：按号比（{cred_no} != {no}）"
        return True, ""

    from agentflow import vsigns as VS

    monkeypatch.setattr(VS, "_sign_is_for_this_path", _by_number)
    second = _ingest(b, rel2, cells=["proof_text", "dependencies"])
    assert second.get("ok") is False, (
        "把 borrowed 改回按号比之后第二份已签证明仍然收进去了", second)
    problems = _per_path_problems(st)
    assert problems, "把 borrowed 改回按号比之后判据 a 仍然全绿 ⇒ 它没有真的比过"
    assert any("#2" in p for p in problems), problems

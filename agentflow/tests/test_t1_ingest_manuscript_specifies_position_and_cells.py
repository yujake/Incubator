# -*- coding: utf-8 -*-
"""T1：`own.land_manuscript` + `own.ingest_manuscript` 的判据（设计 `_design_T123.md` §2）。

## 这一份钉什么（业主 2026-11-09 的目标形态，逐字）

> 「自动录入是 B 秘书的一个工具，需 B 秘书指定录入位置和录入格后，从稿中提取内容录入」

于是判据拆成五组：

| 组 | 判据 |
|---|---|
| a | 两个动作逐条绿：preview 零写 / apply 逐格回填 / register 新命题 / 位置优先 |
| b | 参数证明：「位置」——target 与稿头不一致 ⇒ 受控拒 `manuscript_points_elsewhere`（不重定向）；「格」——只请求 `proof_text` ⇒ 其它格一个字节不动；请求派生列 ⇒ 受控拒 |
| c | 冲突矩阵四态（空 / 相同 / 不同 / append）各一条；I1/I2 两条不变量（构造"填了没请求" ⇒ 报错） |
| d | 反真空 3 条：apply 顺手跑同一性判定 ⇒ 红；派生列放行 ⇒ 红；preview 写了盘 ⇒ 红 |
| e | 唯一写口 / 签闸不松 / legacy 只可 preview / 工具面声明 |

全部用例在 `tmp_path` 里自建工作区；签走 conftest 的真写口（零模型调用）。
"""
from __future__ import annotations

import hashlib
import pathlib
import sys

import pytest

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import conftest  # noqa: E402
from _credential_fixture import issue_credential  # noqa: E402
from agentflow import evidencebits as EB  # noqa: E402
from agentflow import manuscriptintake as MI  # noqa: E402
from agentflow import specs as SPECS  # noqa: E402
from agentflow.agent_b import AgentB  # noqa: E402
from agentflow.store import Store  # noqa: E402

PROPOSITION = "对任意有限群 G，若 p 整除 |G|，则 G 有 p 阶元。"
OTHER_PROPOSITION = "对任意整数 n，n^2 - n 是偶数。"
PROOF = ("1. 取 G 的一个 Sylow p-子群 P（二阶 Sylow 定理）。\n"
         "2. |P| = p^a > 1 ⇒ 取 1 ≠ x ∈ P，由拉格朗日定理 ord(x) 是 p 的幂。\n"
         "3. 结论：x 的某个幂就是 p 阶元。")
OTHER_PROOF = "1. n^2 - n = n(n-1)。\n2. 相邻两整数一奇一偶 ⇒ 乘积是偶数。"
DEP_TARGET = "群论引理"


def _manuscript(*, sid: str = "000001", proposition: str = PROPOSITION,
                proof: str = PROOF, proof_no: int = 0,
                dep_stmt: str = "") -> str:
    """一份三节齐全的手稿（`-pN` 由文件名给，不写进稿头）。"""
    deps = ("| 引用（F 的原话） | 命题号（stmt:NNNNNN） | 用在哪一步 | 路径号（第几条证明） |\n"
            "|---|---|---|---|\n")
    if dep_stmt:
        deps += f"| {DEP_TARGET} | stmt:{dep_stmt} | 1 | 1 |\n"
    head = f"- 命题号：stmt:{sid}\n- 证据种类：conjecture\n"
    return (head + "\n## 命题\n\n" + proposition + "\n\n"
            "## 证明\n\n" + proof + "\n\n## 依赖\n\n" + deps)


def _ws(tmp_path: pathlib.Path) -> tuple[Store, AgentB]:
    st = Store(tmp_path / "ws")
    st.init()
    return st, AgentB(st, extractor=None, extract_text=None, config={})


def _write(st: Store, rel: str, text: str) -> pathlib.Path:
    path = pathlib.Path(st.root) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _row(st: Store, sid: str = "000001") -> dict:
    return next((dict(r) for r in st.rows("statements")
                 if str(r.get("stmt_id") or "") == sid), {})


def _rows(st: Store) -> list[dict]:
    return [dict(r) for r in st.rows("statements")]


def _signed_row(st: Store, *, sid: str = "000001", proof: str = PROOF,
                proof_no: int = 1, rel: str = "", row_proof: str = "") -> dict:
    """铺一行在册命题 + 让 V 的签盖住这一份正文（真写口，零模型）。

    `row_proof` 给"这一行现在已经有第 1 份证明"的现场（append 那一档要用）。
    """
    row = conftest.seed_statement_row(
        st, stmt_id=sid, statement_full=PROPOSITION, kind="conjecture",
        proof_text=row_proof)
    conftest.sign_for_the_gate(
        st.root, statement_id=sid, proof_text=proof, proof_no=proof_no,
        store=st, manuscript=rel or f"reports/f-proof-{sid}.md")
    return row


def _issue_proof_sign(st: Store, sid: str, proof_text: str, proof_no: int,
                      rel: str) -> dict:
    """把 V 对第 N 份证明的签真落成 `out/vsigns/<sha>.json`。

    append 那一档要构造的正是「#p2 还没进台账、签已经盖在正文上」这个前提
    （设计 §4.2 O2：签先于台账正文），所以这里用批 2 自己那份夹具
    （`_credential_fixture.issue_credential`：三票同源 + `vsigns.issue`），
    与 `V.verify_proof` 写签文件那一步同源。
    """
    return issue_credential(st.root, proof_text=proof_text, statement_id=sid,
                            manuscript=rel, proof_no=proof_no)


def _sha_of(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _make_citable(st: Store, sid: str, *, kind: str = "theorem") -> dict:
    """把一条在册命题推到可引池（`pre_theorem`）：五元位里 `proof` 翻真。

    可引门槛读等级（`depsection.citable_pool`），不读历史列 —— 只改 `evidence_kind`
    在现算下仍是 conjecture，依赖闸会拒（既有口径，这里照它造现场）。
    """
    row = dict(_row(st, sid))
    bits = dict(row.get("bits") or {})
    bits["proof"] = True
    ev = dict(bits.get("evidence") or {})
    ev.setdefault("proof_process", str(row.get("proof_text") or "（夹具：证明正文）"))
    bits["evidence"] = ev
    bits["grade"] = EB.derive_grade(bits, kind=kind)
    with st.tx("statements", actor="夹具") as tx:
        tx.upsert("statements", dict(row, kind=kind, bits=bits))
    return dict(_row(st, sid))


# ===================================================== a1 preview 零写
def test_a1_preview_writes_nothing(tmp_path: pathlib.Path,
                                   monkeypatch: pytest.MonkeyPatch) -> None:
    """preview：statements / dependencies / 盘上稿三者一个字节都不变，写口一次没调。"""
    st, b = _ws(tmp_path)
    _signed_row(st)
    path = _write(st, "reports/f-proof-000001.md", _manuscript())
    before_rows = _rows(st)
    before_deps = [dict(r) for r in st.rows("dependencies")]
    before_disk = _sha_of(path)

    calls: list[str] = []
    real_attach = AgentB._attach_proofs
    real_dep = type(b._statement_secretary()).record_manuscript_dependency_face

    def _attach(self, *a, **k):
        calls.append("attach")
        return real_attach(self, *a, **k)

    def _dep(self, *a, **k):
        calls.append("dependencies")
        return real_dep(self, *a, **k)

    monkeypatch.setattr(AgentB, "_attach_proofs", _attach)
    monkeypatch.setattr(type(b._statement_secretary()),
                        "record_manuscript_dependency_face", _dep)

    got = b.ingest_manuscript(
        manuscript="reports/f-proof-000001.md", target_stmt_id="000001",
        cells=["proof_text", "dependencies"], mode="preview")
    assert got["ok"] is True, got
    assert calls == [], calls
    assert got["write"]["written"] is False, got["write"]
    assert _rows(st) == before_rows
    assert [dict(r) for r in st.rows("dependencies")] == before_deps
    assert _sha_of(path) == before_disk
    assert got["diff"]["filled_not_requested"] == []
    assert got["cells"]["proof_text"]["outcome"] == "filled"


# ===================================================== a2 apply 逐格回填
def test_a2_apply_fills_the_requested_cells_only(tmp_path: pathlib.Path) -> None:
    """apply 只填 `proof_text`：正文落行、依赖表 0 行、盘上稿不变、未请求格一个没动。"""
    st, b = _ws(tmp_path)
    _signed_row(st)
    path = _write(st, "reports/f-proof-000001.md", _manuscript())
    before_disk = _sha_of(path)

    got = b.ingest_manuscript(
        manuscript="reports/f-proof-000001.md", target_stmt_id="000001",
        cells=["proof_text"], mode="apply")
    assert got["ok"] is True, got
    assert got["cells"]["proof_text"]["outcome"] == "filled"
    assert _row(st)["proof_text"] == PROOF
    assert st.rows("dependencies") == []
    assert _sha_of(path) == before_disk
    for cell in ("statement_full", "dependencies", "kind", "numeric_evidence"):
        assert got["cells"][cell]["outcome"] == "not_requested", (cell, got["cells"][cell])
    assert got["diff"] == {"requested_not_filled": [],
                           "filled_not_requested": []}
    assert got["write"]["statements"] is True
    assert got["write"]["dependencies"] is False


def test_a2b_apply_dependencies_appends_without_touching_the_row(
        tmp_path: pathlib.Path) -> None:
    """apply 只填 `dependencies`：依赖边落表、statements 的正文一个字节不动。"""
    st, b = _ws(tmp_path)
    _signed_row(st)
    # 被引命题要在册且等级 ≥ pre_theorem（五元位里 proof 翻真之后才可引）
    conftest.seed_statement_row(st, stmt_id="000002", statement_full="引理：…",
                                kind="lemma", proof_text="引理：…")
    conftest.sign_for_the_gate(st.root, statement_id="000002",
                               proof_text="引理：…", store=st)
    _make_citable(st, "000002", kind="lemma")
    _write(st, "reports/f-proof-000001.md", _manuscript(dep_stmt="000002"))
    before_row = _row(st)

    got = b.ingest_manuscript(
        manuscript="reports/f-proof-000001.md", target_stmt_id="000001",
        cells=["dependencies"], mode="apply")
    assert got["ok"] is True, got
    assert got["write"]["dependencies"] is True, got["write"]
    deps = [dict(r) for r in st.rows("dependencies")]
    assert len(deps) == 1 and str(deps[0].get("source_stmt_id")) == "000002", deps
    assert _row(st) == before_row


# ===================================================== a3 register 新命题
def test_a3_register_creates_a_new_statement(tmp_path: pathlib.Path) -> None:
    """`mode=register`：新命题入账、命题/证明逐字取自稿、`pointer` 读数保留。"""
    st, b = _ws(tmp_path)
    _write(st, "reports/f-proof-000000.md",
           _manuscript(sid="（待登记）", proposition=OTHER_PROPOSITION,
                       proof=OTHER_PROOF))
    conftest.sign_before_registration(st.root, proof_text=OTHER_PROOF)

    got = b.ingest_manuscript(
        manuscript="reports/f-proof-000000.md", mode="register",
        cells=["statement_full", "proof_text", "dependencies"])
    assert got["ok"] is True, got
    rows = _rows(st)
    assert len(rows) == 1, rows
    assert rows[0]["statement_full"] == OTHER_PROPOSITION
    assert rows[0]["proof_text"] == OTHER_PROOF
    assert got["register"]["pointer"]["d_gave_only_pointers"] is True, got["register"]
    # 稿里那张依赖表是空表 ⇒ 这一格是 not_applicable（自足证明合法），I2 仍要理由。
    assert set(got["requested_cells"]) == {
        "statement_full", "proof_text", "dependencies"}
    assert got["diff"]["filled_not_requested"] == []
    assert got["cells"]["dependencies"]["outcome"] == "not_applicable"
    assert got["cells"]["dependencies"]["reason"]
    for cell in ("statement_full", "proof_text"):
        assert got["cells"][cell]["outcome"] == "filled", (cell, got["cells"][cell])


def test_a3b_register_refuses_an_incomplete_cell_set(tmp_path: pathlib.Path) -> None:
    """register 要整行落库：只点一格的登记 ⇒ 受控拒 `cells_incomplete_for_register`。"""
    st, b = _ws(tmp_path)
    _write(st, "reports/f-proof-000000.md", _manuscript(sid="（待登记）"))
    got = b.ingest_manuscript(manuscript="reports/f-proof-000000.md",
                              mode="register", cells=["statement_full"])
    assert got["ok"] is False
    assert got["refused"] == "cells_incomplete_for_register", got


# ===================================================== b1 位置优先 / 不重定向
def test_b1_position_is_authoritative_and_not_redirected(
        tmp_path: pathlib.Path) -> None:
    """稿头指 B、target 指 A ⇒ 受控拒 `manuscript_points_elsewhere`，零写入、不录到 B。"""
    st, b = _ws(tmp_path)
    _signed_row(st)
    conftest.seed_statement_row(st, stmt_id="000009", statement_full="另一条命题")
    _write(st, "reports/f-proof-000009.md", _manuscript(sid="000009"))
    before_rows = _rows(st)
    before_deps = [dict(r) for r in st.rows("dependencies")]

    got = b.ingest_manuscript(
        manuscript="reports/f-proof-000009.md", target_stmt_id="000001",
        cells=["proof_text"], mode="apply")
    assert got["ok"] is False, got
    assert got["refused"] == "manuscript_points_elsewhere", got
    assert "stmt:000009" in got["reason"] and "stmt:000001" in got["reason"]
    assert _rows(st) == before_rows, "被拒的这一笔改了台账（不许重定向）"
    assert [dict(r) for r in st.rows("dependencies")] == before_deps
    assert _row(st, "000009").get("proof_text") == "", "录到了调用方没点名的行"


def test_b2_proof_no_must_agree_with_the_manuscript_name(
        tmp_path: pathlib.Path) -> None:
    """稿名 `-p2` 而参数说 #p1 ⇒ 受控拒 `proof_no_mismatch`（不就近取一个）。"""
    st, b = _ws(tmp_path)
    _signed_row(st)
    _write(st, "reports/f-proof-000001-p2.md", _manuscript(sid="000001"))
    got = b.ingest_manuscript(
        manuscript="reports/f-proof-000001-p2.md", target_stmt_id="000001",
        cells=["proof_text"], mode="preview", proof_no=1)
    assert got["ok"] is False
    assert got["refused"] == "proof_no_mismatch", got
    assert _row(st).get("proof_text") == ""


# ===================================================== b2 格：其它格一个字节不动
def test_b3_only_the_requested_cell_is_read(tmp_path: pathlib.Path) -> None:
    """只请求 `proof_text` ⇒ 提取读数里只有这一格；其它格连读都没读。"""
    st, b = _ws(tmp_path)
    _signed_row(st)
    _write(st, "reports/f-proof-000001.md", _manuscript())
    got = b.ingest_manuscript(
        manuscript="reports/f-proof-000001.md", target_stmt_id="000001",
        cells=["proof_text"], mode="preview")
    assert got["ok"] is True, got
    assert got["requested_cells"] == ["proof_text"]
    assert got["cells"]["proof_text"]["requested"] is True
    for cell in ("statement_full", "dependencies", "kind", "numeric_evidence"):
        one = got["cells"][cell]
        assert one["requested"] is False and one["outcome"] == "not_requested"


def test_b4_derived_cells_are_never_requestable(tmp_path: pathlib.Path) -> None:
    """派生列（label / bits / proof_no / sha …）请求即受控拒，一个字节不写。"""
    st, b = _ws(tmp_path)
    _signed_row(st)
    _write(st, "reports/f-proof-000001.md", _manuscript())
    for cell in ("label", "bits", "proof_no", "proof_sha256", "stmt_id",
                 "evidence_kind", "origin", "line_range"):
        got = b.ingest_manuscript(
            manuscript="reports/f-proof-000001.md", target_stmt_id="000001",
            cells=[cell], mode="preview")
        assert got["ok"] is False, (cell, got)
        assert got["refused"] == "derived_cell_not_requestable", (cell, got)
        assert cell in got["reason"]
    with pytest.raises(ValueError):
        MI.extract_cells("## 命题\nP\n", "f-proof", ["label"])


def test_b5_statement_full_is_read_only_on_a_registered_row(
        tmp_path: pathlib.Path) -> None:
    """在册行的命题正文只读：稿里命题不同 ⇒ 拒 `proposition_locked`、零写入。"""
    st, b = _ws(tmp_path)
    _signed_row(st)
    _write(st, "reports/f-proof-000001.md",
           _manuscript(proposition="另一条完全不同的命题。"))
    before = _row(st)
    got = b.ingest_manuscript(
        manuscript="reports/f-proof-000001.md", target_stmt_id="000001",
        cells=["statement_full"], mode="apply")
    assert got["ok"] is False
    assert got["refused"] == "proposition_locked", got
    assert _row(st) == before


# ===================================================== c1 冲突矩阵四态
def test_c1_conflict_matrix_empty_same_different_append(
        tmp_path: pathlib.Path) -> None:
    """proof_text 四态：空 ⇒ filled；同 sha ⇒ unchanged；不同 ⇒ refused；-p2 ⇒ 追加。"""
    # 空
    st, b = _ws(tmp_path / "empty")
    _signed_row(st)
    _write(st, "reports/f-proof-000001.md", _manuscript())
    empty = b.ingest_manuscript(
        manuscript="reports/f-proof-000001.md", target_stmt_id="000001",
        cells=["proof_text"], mode="apply")
    assert empty["ok"] is True and empty["cells"]["proof_text"]["outcome"] == "filled"
    assert _row(st)["proof_text"] == PROOF

    # 相同
    st, b = _ws(tmp_path / "same")
    _signed_row(st, proof=PROOF)
    _write(st, "reports/f-proof-000001.md", _manuscript())
    with st.tx("statements", actor="夹具") as tx:
        tx.upsert("statements", dict(_row(st), proof_text=PROOF,
                                     proof_sha256=hashlib.sha256(
                                         PROOF.encode("utf-8")).hexdigest()))
    same = b.ingest_manuscript(
        manuscript="reports/f-proof-000001.md", target_stmt_id="000001",
        cells=["proof_text"], mode="apply")
    assert same["ok"] is True
    assert same["cells"]["proof_text"]["outcome"] == "unchanged", same
    assert same["write"]["written"] is False

    # 不同（默认 refuse）
    st, b = _ws(tmp_path / "different")
    _signed_row(st, proof="另一份正文")
    _write(st, "reports/f-proof-000001.md", _manuscript())
    with st.tx("statements", actor="夹具") as tx:
        tx.upsert("statements", dict(_row(st), proof_text="另一份正文",
                                     proof_sha256=hashlib.sha256(
                                         "另一份正文".encode("utf-8")).hexdigest()))
    diff = b.ingest_manuscript(
        manuscript="reports/f-proof-000001.md", target_stmt_id="000001",
        cells=["proof_text"], mode="apply")
    assert diff["ok"] is False
    assert diff["refused"] == "proof_text_exists_different", diff
    assert _row(st)["proof_text"] == "另一份正文"

    # append：-p2 且 #p1 已在
    st, b = _ws(tmp_path / "append")
    _signed_row(st, proof=PROOF, proof_no=1, row_proof=PROOF)
    _issue_proof_sign(st, "000001", "第二份证明正文", 2,
                      "reports/f-proof-000001-p2.md")
    _write(st, "reports/f-proof-000001-p2.md",
           _manuscript(proof="第二份证明正文"))
    appended = b.ingest_manuscript(
        manuscript="reports/f-proof-000001-p2.md", target_stmt_id="000001",
        cells=["proof_text"], mode="apply", proof_no=2)
    assert appended["ok"] is True, appended
    assert appended["cells"]["proof_text"]["outcome"] == "filled", appended
    proofs = [dict(x) for x in (_row(st).get("proofs") or [])]
    assert any(int(x.get("proof_no") or 0) == 2 for x in proofs), proofs


def test_c2_i1_i2_are_machine_checks_not_commentary() -> None:
    """I1/I2：喂一份"填了没请求"的读数 ⇒ 判据报错；正常读数 ⇒ 空串。"""
    good = {
        "requested_cells": ["proof_text"],
        "derived_write": ["bits"],
        "cells": {
            "proof_text": {"requested": True, "outcome": "filled", "reason": ""},
            "statement_full": {"requested": False, "outcome": "not_requested"},
        },
        "diff": {"requested_not_filled": [], "filled_not_requested": []},
    }
    assert AgentB._ingest_invariant_problem(good) == ""

    bad_i1 = {**good, "cells": {
        **good["cells"],
        "statement_full": {"requested": False, "outcome": "filled", "reason": ""}}}
    assert "I1" in AgentB._ingest_invariant_problem(bad_i1)

    bad_i2 = {**good, "requested_cells": ["proof_text"],
              "cells": {"proof_text": {"requested": True, "outcome": "refused",
                                       "reason": ""}}}
    assert "I2" in AgentB._ingest_invariant_problem(bad_i2)


def test_c3_a_doctored_plan_is_refused_by_the_tool(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """反真空：把 plan 打桩成"顺手填了没请求的格" ⇒ 工具整笔受控拒。"""
    st, b = _ws(tmp_path)
    _signed_row(st)
    _write(st, "reports/f-proof-000001.md", _manuscript())
    real = MI.plan_cells

    def doctored(*a, **k):
        got = real(*a, **k)
        got["cells"]["statement_full"] = {
            "requested": True, "writable": True, "outcome": "filled",
            "reason": "", "source": {}}
        return got

    monkeypatch.setattr(MI, "plan_cells", doctored)
    got = b.ingest_manuscript(
        manuscript="reports/f-proof-000001.md", target_stmt_id="000001",
        cells=["proof_text"], mode="preview")
    assert got["ok"] is False, got
    assert got["refused"] == "ingest_invariant_violated", got
    assert "statement_full" in got["reason"]


def test_c3b_kind_only_upgrades_after_a_sign_and_never_downgrades(
        tmp_path: pathlib.Path) -> None:
    """`kind`：没有签 ⇒ kept（不写）；稿头更弱于台账 ⇒ 整笔拒 `kind_downgrade`。"""
    st, b = _ws(tmp_path)
    _signed_row(st)
    _write(st, "reports/f-proof-000001.md",
           _manuscript().replace("- 证据种类：conjecture", "- 证据种类：lemma"))
    kept = b.ingest_manuscript(
        manuscript="reports/f-proof-000001.md", target_stmt_id="000001",
        cells=["kind"], mode="apply")
    assert kept["ok"] is True, kept
    assert kept["cells"]["kind"]["outcome"] == "kept", kept["cells"]["kind"]
    assert kept["cells"]["kind"]["code"] == "kind_not_upgraded_without_sign"
    assert _row(st)["kind"] == "conjecture"

    st, b = _ws(tmp_path / "down")
    conftest.seed_statement_row(st, stmt_id="000001",
                                statement_full=PROPOSITION, kind="theorem")
    _write(st, "reports/f-proof-000001.md",
           _manuscript().replace("- 证据种类：conjecture", "- 证据种类：conjecture"))
    down = b.ingest_manuscript(
        manuscript="reports/f-proof-000001.md", target_stmt_id="000001",
        cells=["kind"], mode="apply")
    assert down["ok"] is False
    assert down["refused"] == "kind_downgrade", down
    assert _row(st)["kind"] == "theorem"


# ===================================================== c4 签闸不松
def test_c4_apply_still_needs_a_covering_sign(tmp_path: pathlib.Path) -> None:
    """没有覆盖这一份正文的签 ⇒ `proof_without_v_sign`，台账一个字节不写。"""
    st, b = _ws(tmp_path)
    conftest.seed_statement_row(st, stmt_id="000001",
                                statement_full=PROPOSITION, kind="conjecture")
    _write(st, "reports/f-proof-000001.md", _manuscript())
    got = b.ingest_manuscript(
        manuscript="reports/f-proof-000001.md", target_stmt_id="000001",
        cells=["proof_text"], mode="apply")
    assert got["ok"] is False
    assert got["refused"] == "proof_without_v_sign", got
    assert got["cells"]["proof_text"]["outcome"] == "refused"
    assert _row(st)["proof_text"] == ""


# ===================================================== d 反真空：apply 不跑同一性判定
def test_d_apply_never_runs_the_identity_judgement(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """apply 一旦"顺手跑同一性判定"就必须红：这里把两处判定打成炸弹。"""
    st, b = _ws(tmp_path)
    _signed_row(st)
    _write(st, "reports/f-proof-000001.md", _manuscript())

    def _boom(*a, **k):
        raise AssertionError("apply 跑了同一性判定 —— 它可能把这一笔并到调用方没点名的行")

    monkeypatch.setattr(AgentB, "_resolve_same_statement", _boom)
    monkeypatch.setattr(AgentB, "_existing_statement_for", _boom)
    got = b.ingest_manuscript(
        manuscript="reports/f-proof-000001.md", target_stmt_id="000001",
        cells=["proof_text"], mode="apply")
    assert got["ok"] is True, got
    assert _row(st)["proof_text"] == PROOF


# ===================================================== e land_manuscript
def test_e_land_manuscript_is_idempotent_and_gated(tmp_path: pathlib.Path) -> None:
    """显式落稿：第一次写、第二次 preserved（一个字节不动）；sha 不符 ⇒ stale_target。"""
    st, b = _ws(tmp_path)
    conftest.seed_statement_row(st, stmt_id="000001",
                                statement_full=PROPOSITION, kind="conjecture")
    first = b.land_manuscript(statement_id="000001", proof_text=PROOF)
    assert first["ok"] is True, first
    path = pathlib.Path(st.root) / str(first["path"])
    assert path.is_file()
    before = _sha_of(path)
    second = b.land_manuscript(statement_id="000001", proof_text=PROOF)
    assert second["ok"] is True and second["preserved"] is True, second
    assert _sha_of(path) == before
    stale = b.land_manuscript(statement_id="000001", proof_text=PROOF,
                              if_match_sha256="0" * 64)
    assert stale["ok"] is False and stale["refused"] == "stale_target", stale
    assert _sha_of(path) == before


def test_e2_land_manuscript_takes_the_registered_proposition(
        tmp_path: pathlib.Path) -> None:
    """`statement_full` 可以不给：命题取台账那一行（落出来的稿头/正文对得上）。"""
    st, b = _ws(tmp_path)
    conftest.seed_statement_row(st, stmt_id="000001",
                                statement_full=PROPOSITION, kind="conjecture")
    got = b.land_manuscript(statement_id="000001", proof_text=PROOF)
    assert got["ok"] is True, got
    text = (pathlib.Path(st.root) / str(got["path"])).read_text(encoding="utf-8")
    assert PROPOSITION in text and PROOF in text


# ===================================================== f legacy 只可 preview
def test_f_legacy_is_preview_only(tmp_path: pathlib.Path) -> None:
    """`notes/…` 是历史档：可 preview（读数给得出），apply 受控拒。"""
    st, b = _ws(tmp_path)
    _signed_row(st)
    _write(st, "notes/f-proof-000001.md", _manuscript())
    preview = b.ingest_manuscript(
        manuscript="notes/f-proof-000001.md", target_stmt_id="000001",
        cells=["proof_text"], mode="preview")
    assert preview["ok"] is True, preview
    assert preview["cells"]["proof_text"]["outcome"] == "not_applicable"
    assert preview["cells"]["proof_text"]["value"] == PROOF
    apply = b.ingest_manuscript(
        manuscript="notes/f-proof-000001.md", target_stmt_id="000001",
        cells=["proof_text"], mode="apply")
    assert apply["ok"] is False and apply["refused"] == "manuscript_legacy_name"


def test_f2_cells_are_narrowed_per_family(tmp_path: pathlib.Path) -> None:
    """每族再收窄一次：e-num 请求 `proof_text` ⇒ `cell_not_applicable_for_family`。"""
    st, b = _ws(tmp_path)
    _write(st, "reports/e-num-000001.md",
           "- 实验号：exp:000001\n\n## 命题\n\nP\n\n## 数值结果\n\n- 方法：numeric\n- 结果：ok\n")
    got = b.ingest_manuscript(
        manuscript="reports/e-num-000001.md", target_stmt_id="000001",
        cells=["proof_text"], mode="preview")
    assert got["ok"] is False
    assert got["refused"] == "cell_not_applicable_for_family", got


# ===================================================== g 工具面声明
def test_g_both_actions_are_declared_as_tools() -> None:
    """`specs/b.ACTIONS` 里有这两件、handler 在类上、参数面是闭集（派生列进不了 enum）。"""
    actions = {spec.action: spec for spec in SPECS.b.ACTIONS}
    for name in ("land_manuscript", "ingest_manuscript"):
        assert name in actions, sorted(actions)
        spec = actions[name]
        assert callable(getattr(AgentB, spec.handler_name, None))
        assert spec.side_effect == "write_local"
        assert spec.external == "none"
    cells = actions["ingest_manuscript"].params["properties"]["cells"]
    assert cells["items"]["enum"] == list(MI.INGEST_CELLS)
    assert "label" not in cells["items"]["enum"]
    assert actions["ingest_manuscript"].params["properties"]["mode"]["enum"] == \
        list(MI.INGEST_MODES)

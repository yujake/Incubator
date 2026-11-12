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
from _same_statement_stub import wire_for_secretary  # noqa: E402
from agentflow import evidencebits as EB  # noqa: E402
from agentflow import manuscriptintake as MI  # noqa: E402
from agentflow import schema as S  # noqa: E402
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


def test_a3c_register_receipt_reports_the_dependency_rows_it_really_wrote(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """register 的写回执按盘上实际写了几行报：`dependencies=True` + `deps_written=1`。

    现场（被引面那条 lane）：`mode=register` 真落了 1 条依赖行（`used_by='stmt:…'`、
    `source_stmt_id='000090'`），而回执写死 `dependencies=False` ⇒ 调用方读到
    "依赖面没写"，盘上却有那一行（D15/D16 那类"读数与事实不符"）。

    反真空：把回执算点打桩回改前那个常量 ⇒ 同一条断言必须红 —— 否则
    "回执说真话"这件事没有人检验过。
    """
    st, b = _ws(tmp_path)
    wire_for_secretary(monkeypatch)
    conftest.seed_statement_row(st, stmt_id="000002", statement_full="引理：…",
                                kind="lemma", proof_text="引理：…")
    conftest.sign_for_the_gate(st.root, statement_id="000002",
                               proof_text="引理：…", store=st)
    _make_citable(st, "000002", kind="lemma")
    _write(st, "reports/f-proof-000000.md",
           _manuscript(sid="（待登记）", proposition=OTHER_PROPOSITION,
                       proof=OTHER_PROOF, dep_stmt="000002"))
    conftest.sign_before_registration(st.root, proof_text=OTHER_PROOF)

    got = b.ingest_manuscript(
        manuscript="reports/f-proof-000000.md", mode="register",
        cells=["statement_full", "proof_text", "dependencies"])
    assert got["ok"] is True, got
    write = dict(got.get("write") or {})
    assert write.get("dependencies") is True, write
    assert write.get("deps_written") == 1, write
    deps = [dict(r) for r in st.rows("dependencies")]
    assert len(deps) == 1, deps
    assert str(deps[0].get("source_stmt_id")) == "000002", deps
    assert str(deps[0].get("used_by") or "").startswith(
        f"stmt:{got['register']['stmt_id']}"), deps

    # 反真空：打桩回改前那个常量 False ⇒ 同一条读数必须红。
    monkeypatch.setattr(
        AgentB, "_ingest_write_receipt",
        staticmethod(lambda _got: {"statements": True, "dependencies": False,
                                   "written": True,
                                   "sink": "record_statement（登记新命题）"}))
    st2, b2 = _ws(tmp_path / "anti")
    conftest.seed_statement_row(st2, stmt_id="000002", statement_full="引理：…",
                                kind="lemma", proof_text="引理：…")
    conftest.sign_for_the_gate(st2.root, statement_id="000002",
                               proof_text="引理：…", store=st2)
    _make_citable(st2, "000002", kind="lemma")
    _write(st2, "reports/f-proof-000000.md",
           _manuscript(sid="（待登记）", proposition=OTHER_PROPOSITION,
                       proof=OTHER_PROOF, dep_stmt="000002"))
    conftest.sign_before_registration(st2.root, proof_text=OTHER_PROOF)
    bad = b2.ingest_manuscript(
        manuscript="reports/f-proof-000000.md", mode="register",
        cells=["statement_full", "proof_text", "dependencies"])
    assert bad["ok"] is True, bad
    bad_write = dict(bad.get("write") or {})
    assert bad_write.get("dependencies") is False, bad_write
    assert len([dict(r) for r in st2.rows("dependencies")]) == 1, (
        "盘上确实写了 1 条依赖，而回执说 False —— 这就是要判红的那条读数")


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


def test_b2_an_old_pn_name_is_no_longer_a_manuscript(
        tmp_path: pathlib.Path) -> None:
    """`…-p2.md` 不再是手稿名（对齐之后只有一种名字）⇒ 收录受控拒。"""
    st, b = _ws(tmp_path)
    _signed_row(st)
    _write(st, "reports/f-proof-000001-p2.md", _manuscript(sid="000001"))
    got = b.ingest_manuscript(
        manuscript="reports/f-proof-000001-p2.md", target_stmt_id="000001",
        cells=["proof_text"], mode="preview", proof_no=1)
    assert got["ok"] is False
    assert got["refused"] == "bad_manuscript_name", got
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
    # 未签 ⇒ 证据面一个字节都不许动（第 2 位 / 等级 / kind 都还是现场那一档）。
    assert (dict(_row(st).get("bits") or {}).get("proof") is not True), _row(st)
    assert _row(st)["kind"] == "conjecture", _row(st)


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


# ===================================================== h 收录证据（T1 真洞）
def _evidence_cells(st: Store) -> dict:
    """盘上那一行的三个证据格（apply 与 register 的对照读数）。"""
    row = _row(st)
    bits = dict(row.get("bits") or {})
    return {"proof": bool(bits.get("proof")),
            "grade": str(bits.get("grade") or ""),
            "kind": str(row.get("kind") or "")}


def _collect_through(tmp_path: pathlib.Path, mode: str) -> tuple[dict, dict, Store]:
    """同一份已签稿、同一条在册猜想，分别走 apply / register 收录。"""
    st, b = _ws(tmp_path / mode)
    _signed_row(st)
    _write(st, "reports/f-proof-000001.md", _manuscript())
    if mode == "apply":
        got = b.ingest_manuscript(
            manuscript="reports/f-proof-000001.md", target_stmt_id="000001",
            cells=["proof_text"], mode="apply")
    else:
        got = b.ingest_manuscript(
            manuscript="reports/f-proof-000001.md", mode="register",
            cells=["statement_full", "proof_text", "dependencies"])
    return got, _evidence_cells(st), st


def test_h_apply_collects_the_same_evidence_as_register(
        tmp_path: pathlib.Path) -> None:
    """b：apply 收录已签证明 ⇒ 三格与 register 路逐字相同（proof / grade / kind）。

    这是关键对照：两条路读同一份签、写同一条在册行，派生格不许有任何差别。
    apply 这一笔只请求 `proof_text`（不请求 `kind`）—— `kind` 是证据的派生格，
    没请求也必须按证据升上去。
    """
    got_apply, cells_apply, _ = _collect_through(tmp_path, "apply")
    got_register, cells_register, _ = _collect_through(tmp_path, "register")
    assert got_apply["ok"] is True, got_apply
    assert got_register["ok"] is True, got_register
    assert cells_apply == cells_register, (cells_apply, cells_register)
    assert cells_apply == {"proof": True, "grade": "pre_theorem",
                           "kind": "theorem"}, cells_apply
    # 回执里读得到"重算了什么"（不是只有盘上对）：三个派生格各有来源。
    evidence = dict(got_apply.get("evidence") or {})
    assert evidence.get("checked") is True and evidence.get("written") is True, evidence
    assert evidence.get("proof") is True, evidence
    assert (evidence.get("grade_recomputed") or {}).get("to") == "pre_theorem", evidence
    assert (evidence.get("kind_upgraded") or {}).get("to") == "theorem", evidence


def test_h2_removing_the_evidence_recompute_brings_the_field_shape_back(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """d：反真空 —— 把 apply 的证据重算摘掉 ⇒ h 必须红（回到现场那个自相矛盾形状）。

    摘掉的正是"正文写完之后的证据重算"这一笔：正文照旧落行、签照旧在，而
    `proof=false ∧ grade=conjecture ∧ kind=conjecture` 回来 —— 工具说"收录成功"，
    台账里的证据状态没变。h 的三格断言在这一形状下逐条不成立。
    """
    monkeypatch.setattr(
        AgentB, "_ingest_apply_evidence",
        lambda *a, **k: {"checked": True, "written": False,
                         "reason": "反真空：摘掉 apply 的证据重算"})
    got, cells, _ = _collect_through(tmp_path, "apply")
    assert got["ok"] is True, got
    assert cells == {"proof": False, "grade": "conjecture",
                     "kind": "conjecture"}, cells
    assert cells != {"proof": True, "grade": "pre_theorem", "kind": "theorem"}, cells


def test_h3_kind_trace_names_the_same_credential_on_both_routes(
        tmp_path: pathlib.Path) -> None:
    """裁量 ②：两条路的 `_kind_upgrade.basis` 都点名"签文件 + 台账那一行"，逐字相同。"""
    _, _, st_apply = _collect_through(tmp_path, "apply")
    _, _, st_register = _collect_through(tmp_path, "register")
    trace_apply = dict(_row(st_apply).get("_kind_upgrade") or {})
    trace_register = dict(_row(st_register).get("_kind_upgrade") or {})
    assert trace_apply.get("to") == trace_register.get("to") == "theorem"
    assert trace_apply.get("basis") == trace_register.get("basis"), (
        trace_apply, trace_register)
    basis = str(trace_apply.get("basis") or "")
    assert "out/vsigns/" in basis, basis
    assert "verifications/000001.jsonl#" in basis, basis
    assert trace_apply.get("grade") == trace_register.get("grade") == "pre_theorem"


def _drop_the_sign(st: Store) -> None:
    """把签从盘上删掉（台账 + `out/vsigns/`；`issued.json` 是索引，留着）。"""
    for pattern in ("verifications/000001.jsonl", "out/vsigns/*.json"):
        for path in pathlib.Path(st.root).glob(pattern):
            if path.name != "issued.json":
                path.unlink()


def test_h4_replay_recomputes_derived_evidence_after_the_sign_is_gone(
        tmp_path: pathlib.Path) -> None:
    """裁量 ①：幂等重放（正文 unchanged）也按现行事实重算派生证据。

    先 apply 一次（有签）⇒ theorem；删签；再 apply 同一份正文（outcome=unchanged）
    ⇒ 证据位跟着现行事实落回：`reviewed=false`、`grade=conjecture`、`kind=conjecture`，
    而 `write.written` 仍是 False（正文没被重写）。

    `proof` 仍是 True：第 2 位是"这一行有没有证明正文"，正文还在；它是正文的读数，
    不是签的读数（签的有无由 `reviewed` 回答）。
    """
    st, b = _ws(tmp_path)
    _signed_row(st)
    _write(st, "reports/f-proof-000001.md", _manuscript())
    first = b.ingest_manuscript(
        manuscript="reports/f-proof-000001.md", target_stmt_id="000001",
        cells=["proof_text"], mode="apply")
    assert first["ok"] is True, first
    assert _evidence_cells(st) == {"proof": True, "grade": "pre_theorem",
                                   "kind": "theorem"}, _evidence_cells(st)

    _drop_the_sign(st)
    replay = b.ingest_manuscript(
        manuscript="reports/f-proof-000001.md", target_stmt_id="000001",
        cells=["proof_text"], mode="apply")
    assert replay["ok"] is True, replay
    assert replay["cells"]["proof_text"]["outcome"] == "unchanged", replay["cells"]
    assert replay["write"]["written"] is False, replay["write"]
    assert replay["write"]["evidence"] is True, replay["write"]
    row = _row(st)
    bits = dict(row.get("bits") or {})
    assert bits.get("proof") is True, bits
    assert bits.get("reviewed") is False, bits
    assert bits.get("grade") == "conjecture", bits
    assert row.get("kind") == "conjecture", row
    trace = dict(row.get("_kind_upgrade") or {})
    assert trace.get("downgraded") is True, trace
    assert trace.get("to") == "conjecture", trace


def test_h5_replay_anti_vacuum_without_recompute_the_old_theorem_stays(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """裁量 ① 的反真空：把重放的证据重算摘掉 ⇒ 签删了、旧 theorem 仍留在盘上。"""
    st, b = _ws(tmp_path)
    _signed_row(st)
    _write(st, "reports/f-proof-000001.md", _manuscript())
    assert b.ingest_manuscript(
        manuscript="reports/f-proof-000001.md", target_stmt_id="000001",
        cells=["proof_text"], mode="apply")["ok"] is True
    _drop_the_sign(st)
    monkeypatch.setattr(
        AgentB, "_ingest_apply_evidence",
        lambda *a, **k: {"checked": True, "written": False,
                         "reason": "反真空：摘掉重放的证据重算"})
    replay = b.ingest_manuscript(
        manuscript="reports/f-proof-000001.md", target_stmt_id="000001",
        cells=["proof_text"], mode="apply")
    assert replay["ok"] is True, replay
    assert replay["write"]["written"] is False, replay["write"]
    # 旧读数留住了 ⇒ h4 的"跟着降"逐条不成立。
    assert _evidence_cells(st) == {"proof": True, "grade": "pre_theorem",
                                   "kind": "theorem"}, _evidence_cells(st)


def test_h6_kind_cell_receipt_reports_the_derived_upgrade(
        tmp_path: pathlib.Path) -> None:
    """裁量 ④：稿头没有 `- 证据种类：` ⇒ kind 格 outcome 记 kept（没从稿里写），
    同一格带 `kind_upgraded={from,to,basis}`，且不再进 `diff.requested_not_filled`
    （派生证据已经把它满足了；diff 只留真的没满足的格）。"""
    st, b = _ws(tmp_path)
    _signed_row(st)
    _write(st, "reports/f-proof-000001.md",
           _manuscript().replace("- 证据种类：conjecture\n", ""))
    got = b.ingest_manuscript(
        manuscript="reports/f-proof-000001.md", target_stmt_id="000001",
        cells=["proof_text", "kind"], mode="apply")
    assert got["ok"] is True, got
    kind_cell = dict(got["cells"]["kind"])
    assert kind_cell["outcome"] == "kept", kind_cell
    assert kind_cell.get("writable") is False, kind_cell
    assert "kind_upgraded" in str(kind_cell.get("reason") or ""), kind_cell
    upgraded = dict(kind_cell.get("kind_upgraded") or {})
    assert upgraded.get("from") == "conjecture", kind_cell
    assert upgraded.get("to") == "theorem", kind_cell
    assert "out/vsigns/" in str(upgraded.get("basis") or ""), upgraded
    assert "verifications/000001.jsonl#" in str(upgraded.get("basis") or ""), upgraded
    assert "kind" not in got["diff"]["requested_not_filled"], got["diff"]


def test_h6b_removing_the_derived_satisfied_rule_puts_kind_back_in_diff(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """裁量 ④ 的反真空：把"派生格满足"这一格摘掉 ⇒ h6 第一条必红（kind 回到 diff）。"""
    def _run(base: pathlib.Path) -> dict:
        st, b = _ws(base)
        _signed_row(st)
        _write(st, "reports/f-proof-000001.md",
               _manuscript().replace("- 证据种类：conjecture\n", ""))
        return b.ingest_manuscript(
            manuscript="reports/f-proof-000001.md", target_stmt_id="000001",
            cells=["proof_text", "kind"], mode="apply")

    baseline = _run(tmp_path / "a")
    assert baseline["ok"] is True, baseline
    assert "kind" not in baseline["diff"]["requested_not_filled"], baseline["diff"]
    monkeypatch.setattr(AgentB, "_ingest_derived_satisfied",
                        staticmethod(lambda cells: set()))
    got = _run(tmp_path / "b")
    assert "kind" in got["diff"]["requested_not_filled"], got["diff"]
    # 差别只在那一条排除规则：格读数仍是 kept + kind_upgraded（不是被改回了异常）。
    cell = dict(got["cells"]["kind"])
    assert cell["outcome"] == "kept", cell
    assert (cell.get("kind_upgraded") or {}).get("to") == "theorem", cell


# ===================================================== i numeric_evidence（apply 的第 1 位）
def _numeric_manuscript(*, sid: str = "000007", exp: str = "000001") -> str:
    """e-num 稿：稿头实验号 + `## 数值结果`（这一格唯一的来源）。"""
    return (f"- 实验号：exp:{exp}\n- 证据种类：conjecture\n\n"
            "## 命题\n\n设 n<=3，则 P(n) 成立。\n\n"
            "## 数值结果\n\n- 方法：numeric\n- 结果：ok\n")


def _seed_experiment(st: Store, eid: str = "000001") -> dict:
    """落一条真的 `experiments` 行（普通数值档的凭据必须指到它）。"""
    row = S.Experiment(
        experiment_id=eid, claim="P(n) 对 n=1..3 成立", claim_key="P(n)",
        method="numeric", evidence_kind="cross_check", result="supports",
        negation_kind="not_proved", code_path="code/exp.py",
        code_hash="deadbeefdeadbeef", exit_code=0, created_at=conftest.TS)
    row.validate()
    with st.tx("experiments", actor="夹具") as tx:
        tx.upsert("experiments", row.to_dict())
    return row.to_dict()


def test_i1_apply_writes_the_numeric_bit_and_points_at_the_experiment(
        tmp_path: pathlib.Path) -> None:
    """正控：e-num 稿 + 真实验行 ⇒ apply 请求 `numeric_evidence` ⇒ 第 1 位落盘。

    回执（`cells.numeric_evidence`）与盘上那几格都要指得回那条实验行：
    稿头的号 = `experiments` 的号 = 第 1 位凭据里的 `experiment_id` / `exp:` 尾巴。
    """
    st, b = _ws(tmp_path)
    conftest.seed_statement_row(st, stmt_id="000007",
                                statement_full="设 n<=3，则 P(n) 成立。",
                                kind="conjecture")
    _seed_experiment(st, "000001")
    _write(st, "reports/e-num-000007.md", _numeric_manuscript())

    got = b.ingest_manuscript(
        manuscript="reports/e-num-000007.md", target_stmt_id="000007",
        cells=["numeric_evidence"], mode="apply")

    assert got["ok"] is True, got
    assert got["refused"] == "", got
    cell = dict(got["cells"]["numeric_evidence"])
    assert cell["outcome"] == "filled" and cell["written"] is True, cell
    # 回执这一格自己指得出实验行（号与稿头一致）。
    assert (cell.get("value") or {}).get("experiment_id") == "000001", cell
    assert got["write"]["statements"] is True, got["write"]
    assert got["write"]["cells"] == ["numeric_evidence"], got["write"]
    assert got["derived_write"] == ["bits", "grade"], got["derived_write"]

    row = _row(st, "000007")
    bits = dict(row.get("bits") or {})
    assert bits.get("numeric") == "verified", bits
    numeric = dict((bits.get("evidence") or {}).get("numeric") or {})
    assert numeric.get("experiment_id") == "000001", numeric
    assert [str(x) for x in (numeric.get("experiments") or [])] == ["000001"], numeric
    entry = dict((numeric.get("entries") or [{}])[0])
    assert entry.get("exp") == "exp:000001", entry
    assert entry.get("script") == "code/exp.py", entry
    assert bits.get("grade") == "strong_conjecture", bits
    # 正文 / kind / 依赖三格一个字节不动：这一笔只写第 1 位与它的凭据。
    assert row.get("proof_text") == "" and row.get("kind") == "conjecture", row
    assert [dict(x) for x in st.rows("dependencies")] == []


def test_i2_a_missing_experiment_row_is_refused_with_zero_writes(
        tmp_path: pathlib.Path) -> None:
    """反控：稿头的实验号指不到真的 `experiments` 行 ⇒ `numeric_experiment_missing`、零写。

    受控拒要在 apply 那一侧发生（preview 只读稿、核不了台账）；被拒之后
    statements / dependencies / 第 1 位全是原样。
    """
    st, b = _ws(tmp_path)
    conftest.seed_statement_row(st, stmt_id="000007",
                                statement_full="设 n<=3，则 P(n) 成立。",
                                kind="conjecture")
    _write(st, "reports/e-num-000007.md", _numeric_manuscript())
    before_rows = _rows(st)
    before_deps = [dict(r) for r in st.rows("dependencies")]

    preview = b.ingest_manuscript(
        manuscript="reports/e-num-000007.md", target_stmt_id="000007",
        cells=["numeric_evidence"], mode="preview")
    assert preview["ok"] is True, preview  # preview 不核台账：拒发生在 apply

    got = b.ingest_manuscript(
        manuscript="reports/e-num-000007.md", target_stmt_id="000007",
        cells=["numeric_evidence"], mode="apply")
    assert got["ok"] is False, got
    assert got["refused"] == "numeric_experiment_missing", got
    assert got["cells"]["numeric_evidence"]["outcome"] == "refused", got["cells"]
    assert got["write"]["statements"] is False, got["write"]
    assert got["write"]["written"] is False, got["write"]
    assert _rows(st) == before_rows, "被拒的这一笔改了 statements"
    assert [dict(r) for r in st.rows("dependencies")] == before_deps
    assert dict(_row(st, "000007").get("bits") or {}) == {}, _row(st, "000007")


def test_i3_removing_the_numeric_cell_gate_makes_i1_red(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """反真空：把这一格的凭据核 + 写口摘掉 ⇒ i1 的"第 1 位落盘"逐条不成立。

    `_ingest_apply_numeric_evidence` 就是这一格唯一的实现（读 `experiments`、
    核凭据、写第 1 位）。换成"什么都不写、也不报错"的替身之后，工具照样回
    `ok=True`（fail-open 的形状），而 `bits.numeric` / 回执 / `write.statements`
    全是"没写"—— 这正是 i1 要挡的那种假成功。
    """
    st, b = _ws(tmp_path)
    conftest.seed_statement_row(st, stmt_id="000007",
                                statement_full="设 n<=3，则 P(n) 成立。",
                                kind="conjecture")
    _seed_experiment(st, "000001")
    _write(st, "reports/e-num-000007.md", _numeric_manuscript())

    monkeypatch.setattr(
        AgentB, "_ingest_apply_numeric_evidence",
        lambda *a, **k: {"written": False, "code": "", "why": ""})
    got = b.ingest_manuscript(
        manuscript="reports/e-num-000007.md", target_stmt_id="000007",
        cells=["numeric_evidence"], mode="apply")

    assert got["ok"] is True, got
    assert got["write"]["statements"] is False, got["write"]
    assert got["write"]["cells"] == [], got["write"]
    assert got["cells"]["numeric_evidence"].get("written") is not True, got["cells"]
    bits = dict(_row(st, "000007").get("bits") or {})
    assert bits == {}, f"第 1 位被写了 —— i1 的断言失去了对象：{bits}"

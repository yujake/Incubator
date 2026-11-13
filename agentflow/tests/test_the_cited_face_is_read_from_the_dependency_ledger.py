# -*- coding: utf-8 -*-
"""命题台账的「被引面」：谁引了我（`statementledger.cited_by`，业主 2026-11-10）。

## 业主口径（逐字）

「在命题台账加被引面读数，是手稿录入时获取依赖面和将注册的命题号，把命题号打进
各依赖面的被引面，是自动维护，暂不研究消费者」。

⇒ 被引面 不是 一张新表、也不是新列：`dependencies` 里 `source_stmt_id` 是
被引方、`used_by` 是引用方，所以「谁引了我」= `source_stmt_id == 我` 的那些行的
`used_by`。写侧一个字都不用改：B 登记时先拿号（`secretary._record_statement_tx`
的 `tx.alloc_id`）、再按那个号写依赖行（`Secretary._write_dep_steps`）。这一份
判据钉住的正是这条链，而不是一个新入口。

## 判据（每条都写明"为什么它守得住"）

| # | 判据 | 它钉住什么 |
|---|---|---|
| a | 正控：A（kind=conjecture）在册 ⇒ 再登记 B，B 的手稿 `## 依赖` 引 A ⇒ A 的被引面「录入前 0 条 / 录入后 1 条」，且引用方号 = 这一笔刚拿到的号 | 号先发、行后写；被引面自动维护 |
| b | 正控（第二条录入入口）：C 已在册 ⇒ `mode=apply` 只录 dependencies 那一格 ⇒ A 的被引面 +1 | 两条手稿录入入口走同一份依赖账 |
| c | 多引用：A 被 B、C 各引一次 ⇒ 2 条，逐条带 `used_by` / `kind` / `status` / `created_at`；`by_status` 与 `citers` 与逐条读数对得上 | 读数不是只给一个数 |
| d | 三态：`dependencies` 读不出来 ⇒ `checked=False` + `found=None`（不折成「没人引」）；查成了没人引 ⇒ `found=0`；空表 ⇒ `checked=True` + 0 | 三态不折平 |
| e | 反真空（依赖行不落表）：把 `_write_dep_steps` 换成写 0 条 ⇒ a 的那一句断言红 | 读数不是凭空的 |
| f | 反真空（不盖被引方）：依赖行照写、但 `source_stmt_id` 不写 ⇒ a 的那一句断言红 | 被引面确实派生自 `source_stmt_id` |
| g | concept 负控（现行口径）：concept 行不可被引 ⇒ 手稿录入受控拒 `citation_below_proof_review`，且 A 的被引面仍是 0 条（没被静默写进来） | 本批没有放宽引用门 |
| h | 只读 + 零模型：`statementledger.py` 里没有写盘 / 开事务 / 发判定的调用，也没有 import 秘书 | 它是读数，不是写口 |

## 为什么 A 的 kind 是 conjecture 却能进「可引池」

引用门读的是等级（`depsection.uncitable_statement_finding` → `statement_grade`），
不读 `kind`。所以夹具按 `test_t1_ingest_manuscript_specifies_position_and_cells.py`
自己的那一手（`_make_citable`：真签 + 五元位 `proof` 翻真）把 A 抬到 `pre_theorem`，
kind 仍登记为 `conjecture` —— 门一个字没动，只是把"够格现场"造出来。

`concept` 那一档没有这条造法：`evidencebits.derive_grade` 对 `kind="concept"` 直接
短路成 `not_applicable`（概念没有真值、没有等级）⇒ 它按现行口径永远不可被引。
g 把现状钉住；"概念行该不该能进被引面"是另一个决定（放宽引用门），留给业主裁。

零模型调用：同一性判定那一趟（`pick_statement_keywords` + `judge`）在本文件里打桩
成「不同」—— 只替代模型那一趟，检索 / 判定 / 落表一个字都没动。
"""
from __future__ import annotations

import pathlib
import sys

import pytest

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import conftest  # noqa: E402
from agentflow import depsection as DS  # noqa: E402
from agentflow import evidencebits as EB  # noqa: E402
from agentflow import schema as S  # noqa: E402
from agentflow import secretary as SEC  # noqa: E402
from agentflow import statementledger as SL  # noqa: E402
from agentflow.agent_b import AgentB  # noqa: E402
from agentflow.store import Store  # noqa: E402

#: 被引的那一条（显式号：夹具要能一眼认出谁引了谁）。
A_ID = "000090"
#: `mode=apply` 那条正控的录入位置。
C_ID = "000091"
#: concept 负控里那一条（概念行）。
CONCEPT_ID = "000092"

A_FULL = "引理：对任意整数 n，n^2 - n 是偶数。"
A_PROOF = "证明：n^2 - n = n(n-1)，相邻两整数一奇一偶。"
B_FULL = "定理：对任意整数 n，n^2 + n 是偶数。"
B_PROOF = "证明：n^2 + n = n(n+1)，相邻两整数一奇一偶。"
C_FULL = "定理：对任意整数 n，2 整除 n^2 + 3n。"
C_PROOF = "证明：2 整除 n^2 + 3n = n(n+3)（同奇偶）。"
CONCEPT_FULL = "概念：n 与 n+1 互素。"

#: 手稿 `## 依赖` 的四列表头（老盘形态；`depsection` 的解析侧仍收路径号那一列）。
_DEP_HEAD = ("## 依赖\n\n"
             "| 引用（F 的原话） | 命题号（stmt:NNNNNN） | 用在哪一步 | 路径号（第几条证明） |\n"
             "|---|---|---|---|\n")
_DEP_ROW = "| 由引理甲，n(n-1) 是偶数 | stmt:{sid} | 第 1 步 | 1 |\n"


def _ws(tmp_path: pathlib.Path) -> tuple[Store, AgentB]:
    st = Store(tmp_path / "ws")
    st.init()
    return st, conftest.b_form_gate_ok(
        AgentB(st, extractor=None, extract_text=None, config={}))


def _write(st: Store, rel: str, text: str) -> pathlib.Path:
    path = pathlib.Path(st.root) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _manuscript(proposition: str, proof: str, *, dep_sid: str,
                head_sid: str) -> str:
    """三节齐全的手稿；`## 依赖` 里引 `stmt:<dep_sid>`。"""
    head = f"- 命题号：stmt:{head_sid}\n- 证据种类：conjecture\n"
    return (head + "\n## 命题\n\n" + proposition + "\n\n"
            + "## 证明\n\n" + proof + "\n\n"
            + _DEP_HEAD + _DEP_ROW.format(sid=dep_sid))


def _row(st: Store, sid: str) -> dict:
    return next((dict(r) for r in st.rows("statements")
                 if str(r.get("stmt_id") or "") == sid), {})


def _deps(st: Store) -> list[dict]:
    return [dict(r) for r in st.rows("dependencies")]


def _make_citable(st: Store, sid: str, *, kind: str) -> dict:
    """把一条在册命题推到可引池（`pre_theorem`）：真签 + 五元位 `proof` 翻真。

    与 `test_t1_ingest_manuscript_specifies_position_and_cells.py::_make_citable`
    同一手（同一套夹具口径，不另发明一种"够格"）：引用门读等级，不读 kind。
    """
    conftest.sign_for_the_gate(st.root, statement_id=sid,
                               proof_text=str(_row(st, sid).get("proof_text") or ""),
                               store=st, manuscript=f"reports/f-proof-{sid}.md")
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


@pytest.fixture
def identity_says_different(monkeypatch: pytest.MonkeyPatch) -> None:
    """同一性判定那一趟答「不同」（夹具里没有模型；只替代模型那一趟）。

    走的是 `Secretary.adjudicate_proposition` 的既有两问（挑词 + 判定），打桩点与
    `test_the_statement_ledger_has_two_ways_to_be_asked.py::test_g` 同一形态：
    检索、候选、落表都是真的，只有那一次模型回答是夹具给的。
    """
    monkeypatch.setattr(
        SEC.Secretary, "pick_statement_keywords",
        lambda self, **_kw: {"checked": True, "keywords": ["量子引力"],
                             "why": "夹具：挑一个不命中任何命题的词"})
    monkeypatch.setattr(
        SEC.Secretary, "judge",
        lambda self, kind, context, *, task_id="", note="": {
            "checked": True, "decision": "different", "same_as": "",
            "canonical_name": "", "route": "", "condition": "", "conclusion": "",
            "basis": ["夹具"], "reason": "夹具：不同", "cost": {}, "elapsed_sec": 0.0})


def _seed_a_statement(st: Store) -> dict:
    """A：登记成 conjecture，再抬到 `pre_theorem`（可引）。"""
    conftest.seed_statement_row(st, stmt_id=A_ID, statement_full=A_FULL,
                                kind="conjecture", proof_text=A_PROOF)
    return _make_citable(st, A_ID, kind="conjecture")


def _register_b_citing_a(st: Store, b: AgentB) -> tuple[dict, str]:
    """B 那一笔手稿录入（`mode=register`）：命题/证明/依赖全部都从稿里读。

    返回 `(ingest 读数, 这一笔刚拿到的号)`。`## 依赖` 引 A ⇒ 依赖行按这个新号
    落 `used_by`，被引面立刻看得见。
    """
    _write(st, "reports/f-proof-000000.md",
           _manuscript(B_FULL, B_PROOF, dep_sid=A_ID, head_sid="（待登记）"))
    conftest.sign_before_registration(st.root, proof_text=B_PROOF)
    got = b.ingest_manuscript(manuscript="reports/f-proof-000000.md", mode="register",
                              cells=["statement_full", "proof_text", "dependencies"])
    return got, str((got.get("register") or {}).get("stmt_id") or "")


def _positive_control_assertion(reading: dict, citer_id: str) -> None:
    """正控的那一句（e / f 的反真空逐字复用它：降级下它必须抛 AssertionError）。"""
    assert reading["checked"] is True, reading
    assert reading["found"] == 1, reading
    one = reading["citations"][0]
    assert one["used_by"] == f"stmt:{citer_id}", one
    assert one["citer_stmt_id"] == citer_id, one
    assert one["kind"] == "proposition", one


# ===================================================== a 正控：登记拿号 → 落边 → 被引面
def test_a_registering_b_puts_b_into_as_cited_face(
        tmp_path: pathlib.Path, identity_says_different) -> None:
    """a：录入前 0 条 / 录入后 1 条，且引用方号就是这一笔刚拿到的号。"""
    st, b = _ws(tmp_path)
    _seed_a_statement(st)

    before = SL.cited_by(st, stmt_id=A_ID)
    assert before["checked"] is True, before
    assert before["found"] == 0 and before["hits_total"] == 0, before
    assert before["citations"] == [] and before["by_status"] == {}, before
    assert before["scanned"] == 0, before

    got, new_id = _register_b_citing_a(st, b)
    assert got["ok"] is True, got
    assert new_id == str((got.get("register") or {}).get("stmt_id")), got
    # 「这一笔刚拿到的号」不是调用方给的：录入前台账里只有 A。
    assert len([r for r in st.rows("statements")]) == 2, _deps(st)
    assert _row(st, new_id)["statement_full"] == B_FULL

    after = SL.cited_by(st, stmt_id=A_ID)
    _positive_control_assertion(after, new_id)
    assert after["scanned"] == 1, after
    assert after["citers"] == [f"stmt:{new_id}"], after
    assert after["by_status"] == {"closed": 1}, after
    one = after["citations"][0]
    assert one["status"] == "closed", one
    assert one["created_at"], one
    assert one["label"], one
    assert one["dep_id"] and one["path_group"] == 1 and one["proof_no"] == 1, one
    assert one["used_by_problem"] == "", one


# ===================================================== b 正控：apply 那一格也进同一本账
def test_b_applying_the_dependencies_cell_also_reaches_the_cited_face(
        tmp_path: pathlib.Path, identity_says_different) -> None:
    """b：C 已在册 ⇒ `mode=apply` 只录 dependencies ⇒ A 的被引面 +1。"""
    st, b = _ws(tmp_path)
    _seed_a_statement(st)
    corpus, b_id = _register_b_citing_a(st, b)
    assert corpus["ok"] is True, corpus
    assert SL.cited_by(st, stmt_id=A_ID)["found"] == 1

    conftest.seed_statement_row(st, stmt_id=C_ID, statement_full=C_FULL,
                                kind="conjecture", proof_text=C_PROOF)
    _write(st, f"reports/f-proof-{C_ID}.md",
           _manuscript(C_FULL, C_PROOF, dep_sid=A_ID, head_sid=C_ID))
    got = b.ingest_manuscript(manuscript=f"reports/f-proof-{C_ID}.md",
                              target_stmt_id=C_ID, mode="apply",
                              cells=["dependencies"])
    assert got["ok"] is True, got
    assert got["write"]["dependencies"] is True, got["write"]

    reading = SL.cited_by(st, stmt_id=A_ID)
    assert reading["checked"] is True, reading
    assert reading["found"] == 2, reading
    assert reading["scanned"] == 2, reading
    got_ids = sorted(one["citer_stmt_id"] for one in reading["citations"])
    assert got_ids == sorted([b_id, C_ID]), reading
    assert all(one["kind"] == "proposition" for one in reading["citations"]), reading
    assert reading["by_status"] == {"closed": 2}, reading
    assert reading["citers"] == [f"stmt:{b_id}", f"stmt:{C_ID}"], reading
    assert reading["citers_total"] == 2, reading


# ===================================================== c 多引用：逐条带四格
def test_c_every_citation_carries_its_own_four_cells(
        tmp_path: pathlib.Path, identity_says_different) -> None:
    """c：A 被 B、C 各引一次 ⇒ 2 条，逐条带 used_by / kind / label / status / created_at。"""
    st, b = _ws(tmp_path)
    _seed_a_statement(st)
    _register_b_citing_a(st, b)
    conftest.seed_statement_row(st, stmt_id=C_ID, statement_full=C_FULL,
                                kind="conjecture", proof_text=C_PROOF)
    _write(st, f"reports/f-proof-{C_ID}.md",
           _manuscript(C_FULL, C_PROOF, dep_sid=A_ID, head_sid=C_ID))
    assert b.ingest_manuscript(manuscript=f"reports/f-proof-{C_ID}.md",
                               target_stmt_id=C_ID, mode="apply",
                               cells=["dependencies"])["ok"] is True

    reading = SL.cited_by(st, stmt_id=A_ID)
    assert reading["found"] == 2, reading
    for one in reading["citations"]:
        # 「带每条依赖行的 kind / label / status / created_at」——这四格一格不许缺。
        assert one["kind"] and one["label"] and one["status"] and one["created_at"], one
        assert one["used_by"] == f"stmt:{one['citer_stmt_id']}", one
        assert one["kind"] in S.DEP_KINDS, one
    # 逐条与台账对得上（读数不是另算一份）。
    rows = {str(r.get("dep_id")): r for r in _deps(st)}
    for one in reading["citations"]:
        row = rows[one["dep_id"]]
        assert one["used_by"] == str(row.get("used_by"))
        assert one["kind"] == str(row.get("kind"))
        assert one["status"] == str(row.get("status"))
        assert one["created_at"] == str(row.get("created_at"))


# ===================================================== d 三态
class _Unreadable:
    """一个读 `dependencies` 必炸的来源（证明「读不到」与「没人引」分得开）。"""

    @staticmethod
    def rows(table: str):  # noqa: ARG004
        raise RuntimeError("依赖账文件坏了")


def test_d_unreadable_is_not_nobody_cites(tmp_path: pathlib.Path) -> None:
    """d：读不出来 ⇒ checked=False + found=None；查成了没人引 ⇒ found=0。"""
    st, _b = _ws(tmp_path)
    broken = SL.cited_by(_Unreadable(), stmt_id=A_ID)
    assert broken["checked"] is False, broken
    assert broken["found"] is None, broken
    assert broken["hits_total"] == 0 and broken["citations"] == [], broken
    assert "没查成" in broken["reason"], broken
    assert "不是「没人引它」" in broken["reason"], broken
    assert broken["error"]["type"] == "RuntimeError", broken

    # 没给来源 / 没给号：也是「没查成」，不是「0 条」。
    assert SL.cited_by(None, stmt_id=A_ID)["checked"] is False
    assert SL.cited_by(None, stmt_id=A_ID)["found"] is None
    blank = SL.cited_by(st, stmt_id="  ")
    assert blank["checked"] is False and blank["found"] is None, blank
    assert "没给编号" in blank["reason"], blank

    # 空表：查成了、0 条（不是「读不到」）。
    empty = SL.cited_by(st, stmt_id=A_ID)
    assert empty["checked"] is True and empty["found"] == 0, empty
    assert empty["scanned"] == 0 and empty["why"], empty


# ===================================================== e 反真空：依赖行不落表
def test_e_without_dependency_rows_the_positive_control_goes_red(
        tmp_path: pathlib.Path, identity_says_different, monkeypatch) -> None:
    """e：把 `_write_dep_steps` 换成「一条都不写」⇒ 正控那一句断言红。"""
    st, b = _ws(tmp_path)
    _seed_a_statement(st)
    monkeypatch.setattr(SEC.Secretary, "_write_dep_steps",
                        lambda self, *a, **k: 0)
    got, new_id = _register_b_citing_a(st, b)
    assert got["ok"] is True, got          # 登记本身照旧成功（只少了依赖行）
    assert new_id, got
    reading = SL.cited_by(st, stmt_id=A_ID)
    assert reading["checked"] is True and reading["found"] == 0, reading
    with pytest.raises(AssertionError):
        _positive_control_assertion(reading, new_id)


# ===================================================== f 反真空：写行但不盖被引方
def test_f_without_source_stmt_id_the_positive_control_goes_red(
        tmp_path: pathlib.Path, identity_says_different, monkeypatch) -> None:
    """f：依赖行照写、但 `source_stmt_id` 不写（不盖被引面）⇒ 正控那一句断言红。"""
    def _write_rows_without_cited_face(self, tx, steps, *, stmt_id, body):
        count = 0
        for step in steps:
            dep = S.Dependency(
                dep_id=tx.alloc_id(S.TABLES["dependencies"]["id_kind"]),
                used_by=f"stmt:{stmt_id}",
                kind=str(step.get("kind") or "theorem"),
                label=str(step.get("label") or "夹具：这一笔故意不写 source_stmt_id"),
                status="dangling",
                status_reason="夹具：摘掉写入被引面那一步（不写 source_stmt_id）",
                path_group=int(step["path_group"]),
                created_at=S.now_iso(), created_by="夹具")
            dep.validate()
            tx.upsert("dependencies", dep.to_dict(), note="夹具：不盖被引方")
            count += 1
        return count

    st, b = _ws(tmp_path)
    _seed_a_statement(st)
    monkeypatch.setattr(SEC.Secretary, "_write_dep_steps",
                        _write_rows_without_cited_face)
    got, new_id = _register_b_citing_a(st, b)
    assert got["ok"] is True, got
    deps = _deps(st)
    assert len(deps) == 1, deps              # 依赖行在，但被引方那一格是空的
    assert deps[0]["used_by"] == f"stmt:{new_id}", deps
    assert deps[0]["source_stmt_id"] is None, deps
    reading = SL.cited_by(st, stmt_id=A_ID)
    assert reading["checked"] is True and reading["found"] == 0, reading
    with pytest.raises(AssertionError):
        _positive_control_assertion(reading, new_id)


# ===================================================== g concept 负控（现行口径）
def test_g_a_concept_row_is_not_citable_so_its_cited_face_stays_empty(
        tmp_path: pathlib.Path) -> None:
    """g：concept 行按现行口径不可被引 ⇒ 手稿录入受控拒，被引面仍 0 条。

    这条钉的是现状（概念没有真值、没有等级 ⇒ `evidencebits.derive_grade` 对
    `kind="concept"` 短路成 `not_applicable` ⇒ 引用门拒它），不是"概念本来就该被拒"。
    将来业主若裁定"概念也能被依赖面引用"，这一条会被改成正控（同一个 A 被引之后
    被引面 1 条）—— 那时要改的是引用门本身，不是这条判据的口径。
    """
    st, b = _ws(tmp_path)
    conftest.seed_statement_row(st, stmt_id=CONCEPT_ID, statement_full=CONCEPT_FULL,
                                kind="concept", label="互素")
    conftest.seed_statement_row(st, stmt_id=C_ID, statement_full=C_FULL,
                                kind="conjecture", proof_text=C_PROOF)
    _write(st, f"reports/f-proof-{C_ID}.md",
           _manuscript(C_FULL, C_PROOF, dep_sid=CONCEPT_ID, head_sid=C_ID))
    got = b.ingest_manuscript(manuscript=f"reports/f-proof-{C_ID}.md",
                              target_stmt_id=C_ID, mode="apply",
                              cells=["dependencies"])
    assert got["ok"] is False, got
    assert got["refused"] == DS.REFUSED_LEVEL_TOO_LOW, got
    assert SL.cited_by(st, stmt_id=CONCEPT_ID)["found"] == 0
    assert _deps(st) == [], _deps(st)


# ===================================================== h 只读 + 零模型
def test_h_the_cited_face_is_read_only_and_model_free() -> None:
    """h：`statementledger.py` 里没有写盘 / 开事务 / 发判定的调用（结构判据）。"""
    import ast

    tree = ast.parse((_SRC / "agentflow" / "statementledger.py").read_text(encoding="utf-8"))
    banned = {"tx", "upsert", "alloc_id", "judge", "write_sign", "mark_dirty", "commit"}
    used = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    assert not sorted(banned & used), f"查口里出现了写盘 / 判定调用：{sorted(banned & used)}"
    imports = {node.module for node in ast.walk(tree)
               if isinstance(node, ast.ImportFrom) and node.module}
    assert all(not str(m).endswith("secretary") for m in imports), imports
    # 反真空：被引面确实走的是唯一取数口（`rows_of(table=...)`），不是自己又扫一遍。
    src = (_SRC / "agentflow" / "statementledger.py").read_text(encoding="utf-8")
    assert "TABLE_DEPENDENCIES" in src and "rows_of(source, rows=rows, table=TABLE_DEPENDENCIES)" in src


# ===================================================== i 快照入参 + 坏尾巴留痕
def test_i_a_snapshot_is_read_as_given_and_a_bad_tail_is_kept(
        tmp_path: pathlib.Path) -> None:
    """i：`rows=` 直接给一批依赖行 ⇒ 不读 store；坏尾巴只留痕，不折成 canonical 号。"""
    st, _b = _ws(tmp_path)
    rows = [
        {"dep_id": "000000", "used_by": "stmt:000005#p2", "source_stmt_id": A_ID,
         "kind": "lemma", "label": "夹具：第 2 份证明", "status": "closed",
         "created_at": "2026-11-10T00:00:00+08:00", "path_group": 2},
        {"dep_id": "000001", "used_by": "stmt:000006#pabc", "source_stmt_id": A_ID,
         "kind": "theorem", "label": "夹具：坏尾巴", "status": "refuted",
         "created_at": "2026-11-10T00:00:01+08:00", "path_group": 1},
        {"dep_id": "000002", "used_by": "doc:0001#claim-1", "source_stmt_id": "999999",
         "kind": "theorem", "label": "夹具：不指向 A", "status": "closed",
         "created_at": "2026-11-10T00:00:02+08:00", "path_group": 1},
    ]
    got = SL.cited_by(st, rows=rows, stmt_id=A_ID)
    assert got["checked"] is True and got["source"] == "rows", got
    assert got["scanned"] == 3 and got["found"] == 2, got
    first, second = got["citations"]
    assert first["used_by"] == "stmt:000005#p2", first
    assert first["citer_stmt_id"] == "000005" and first["proof_no"] == 2, first
    assert second["used_by"] == "stmt:000006#pabc", second
    # 坏尾巴：不给引用方号（不猜第几条证明），原文留痕。
    assert second["used_by_problem"] == "stmt:000006#pabc", second
    assert second["citer_stmt_id"] == "", second
    assert got["by_status"] == {"closed": 1, "refuted": 1}, got


if __name__ == "__main__":          # pragma: no cover - 手工跑这一份时用
    raise SystemExit(__import__("pytest").main([__file__, "-q"]))

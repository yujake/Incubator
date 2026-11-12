# -*- coding: utf-8 -*-
"""B 侧能收录新形式下的稿件（业主追加的硬验收）。

## 新形式是什么（产出侧口径）

- 稿名不带 `-pN`：一个稿号 = 一份文件 = 一份证明（`reports/b-proof-000123.md`）；
- 稿头没有 `- 证明号：` 那一行；
- `## 依赖` 表只有 `引用 / 命题号 / 步` 三列，没有「路径号」列。

路径号由 B 的秘书在收录那一笔事务里分配（`manuscriptpaths.assign_path_group`），
B 的动作既不算也不传。

## 判据

| # | 造什么 | 期望 |
|---|---|---|
| a | 一份新形式稿交给 B（正文支：命题正文 + 手稿） | 收录成功：命题落行、依赖落表、`path_group=1`、`used_by` 不带 `#p1`（与路径号一致） |
| b | 同一命题再交第二份新形式稿（另一个稿号、稿名不带 `-pN`） | 秘书分配 `path_group=2`；两条路径各自可读（证明清单 + 依赖面 + `verifications` 同号） |
| c | 反真空：把唯一的分配实现打成"永远第 1 条" | b 的 `path_group=2` 断言必须红 |
| e | 对齐（源码面 + 行为面） | `_proof_no_from_delivery` 不存在；`record_statement` / 登记支不再按稿头 / `-pN` 定路径号；`proof_no_mismatch` 不再产生 |

零模型调用：登记与收录都走确定性路径；签用 conftest 的真写口。
"""
from __future__ import annotations

import inspect
import pathlib

import pytest

import conftest
from agentflow import evidencebits as EB
from agentflow import manuscriptsubmission as MS
from agentflow import proofregistry as PR
from agentflow import schema as S
from agentflow import verifications as VR
from agentflow.agent_b import AgentB
from agentflow.secretary import Secretary
from agentflow.store import Store

DEP_SID = "000002"
#: 第一份新形式稿的稿号由秘书发（候选号来自稿头），夹具不写死。
PROPOSITION = "对任意有限群 G，若 p 整除 |G|，则 G 有 p 阶元。"
P1 = ("1. 取 G 的一个 Sylow p-子群 P（二阶 Sylow 定理）。\n"
      "2. |P| = p^a > 1 ⇒ 取 1 ≠ x ∈ P，由拉格朗日定理 ord(x) 是 p 的幂。")
P2 = ("1. 对 |G| 归纳：取中心元 z，把 G 分成若干共轭类。\n"
      "2. 每个共轭类大小被 p 整除或与 p 互素，计数给出 p 阶元。")
REL1 = "reports/b-proof-000123.md"
REL2 = "reports/b-proof-000124.md"


def _ws(tmp_path: pathlib.Path) -> tuple[Store, AgentB]:
    st = Store(tmp_path / "ws")
    st.init()
    return st, AgentB(st, extractor=None, extract_text=None, config={})


@pytest.fixture(autouse=True)
def _proof_kind_default(monkeypatch):
    """同种证明那一问（`proof_kind`）的默认回答：`different`（另一条路径）。

    2026-11-12 起"同种证明"改由秘书的语义判定给（禁机械闸）：没有判定面时按
    fail-closed 拒收（`proof_kind_unjudged`），会把 b/c 这里的第二份证明拒掉 ——
    而这一份量的是"新形式稿能不能落成第 2 条路径"，不是语义判别。真正的剧本桩
    （same / different / 没判成）在
    `tests/test_rehearsal_two_f_independent_proofs.py` 与
    `tests/test_unjudged_axes_are_fail_closed.py`。
    """
    import agentflow.secretary as _SEC

    real = _SEC.Secretary.judge

    def _judge(self, kind, context, **kw):
        if kind == "proof_kind":
            return {"checked": True, "decision": "different", "same_path": 0,
                    "reason": "夹具：不同种（这一份不量语义判别）", "basis": [], "cost": {}}
        return real(self, kind, context, **kw)

    monkeypatch.setattr(_SEC.Secretary, "judge", _judge)


def _citable(st: Store) -> None:
    """一条够可引档的在册命题（依赖段的引用门槛：`pre_theorem` 及以上）。"""
    conftest.seed_statement_row(st, stmt_id=DEP_SID, statement_full="引理：p 阶元",
                                kind="lemma", proof_text="引理：p 阶元")
    conftest.sign_for_the_gate(st.root, statement_id=DEP_SID,
                               proof_text="引理：p 阶元", store=st)
    row = next(dict(r) for r in st.rows("statements")
               if str(r.get("stmt_id")) == DEP_SID)
    bits = dict(row.get("bits") or {})
    bits["proof"] = True
    ev = dict(bits.get("evidence") or {})
    ev.setdefault("proof_process", str(row.get("proof_text") or ""))
    bits["evidence"] = ev
    bits["grade"] = EB.derive_grade(bits, kind="lemma")
    with st.tx("statements", actor="夹具") as tx:
        tx.upsert("statements", dict(row, bits=bits))


def _new_form_manuscript(sid: str, proof: str, *, head_proof_no: int = 0) -> str:
    """新形式稿：稿名不带 `-pN`、稿头没有「证明号」、依赖表只有三列。

    `head_proof_no` 只在 e 那一档用来造一行老形式的 `- 证明号：N`（证明它不采信）。
    依赖表的列名与 `depsection.COLUMN_KEYS` 同一套关键词（顺序不限；「路径」列省略）。
    """
    head = ""
    if head_proof_no >= 1:
        head += f"- 证明号：{head_proof_no}\n"
    head += f"- 命题号：stmt:{sid}\n"
    deps = ("| 引用 | 命题号 | 步 |\n|---|---|---|\n"
            f"| 引理：p 阶元 | stmt:{DEP_SID} | 1 |\n")
    return ("# B 的证明手稿\n\n" + head + "\n## 命题\n\n" + PROPOSITION + "\n\n"
            "## 证明\n\n" + proof + "\n\n## 依赖\n\n" + deps)


def _write(st: Store, rel: str, text: str) -> None:
    path = pathlib.Path(st.root) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _register_proposition(st: Store, b: AgentB) -> str:
    """先立命题、后补证明（新形式下证明由另一份稿承载）。"""
    made = b.register_statement(
        statement_full=PROPOSITION, statement_text="p 阶元", label="p 阶元",
        origin="own_result", kind="conjecture", doc_id=S.format_id(0),
        quote_reason="自产命题，没有外部引文要比对")
    assert made.get("ok") is True, made
    sid = str(made["stmt_id"])
    assert not str(_row(st, sid).get("proof_text") or "").strip(), _row(st, sid)
    return sid


def _deliver(st: Store, b: AgentB, sid: str, rel: str, proof: str, *,
             head_proof_no: int = 0) -> dict:
    """写一份新形式稿、签上，再走 B 的收录入口（→ 秘书 `record_statement`）。

    `statement_full` 与在册那一行逐字相同 ⇒ 这一笔是"给在册命题补一份证明"，
    走的正是 `Secretary.record_statement` 那一笔事务（命题行 / 依赖 / 路径号）。
    """
    _write(st, rel, _new_form_manuscript(sid, proof, head_proof_no=head_proof_no))
    conftest.sign_for_the_gate(st.root, statement_id=sid, proof_text=proof,
                               store=st, manuscript=rel)
    return b.register_statement(
        statement_full=PROPOSITION, statement_text="p 阶元", label="p 阶元",
        origin="own_result", kind="conjecture", doc_id=S.format_id(0),
        quote_reason="自产命题，没有外部引文要比对",
        proof_manuscript=rel)


def _deps(st: Store, sid: str) -> list[dict]:
    return [dict(r) for r in st.rows("dependencies")
            if str(r.get("used_by") or "").split("#", 1)[0] == f"stmt:{sid}"]


def _row(st: Store, sid: str) -> dict:
    return next(dict(r) for r in st.rows("statements") if str(r.get("stmt_id")) == sid)


def _ver_groups(st: Store, sid: str, text: str) -> list[int]:
    rows, bad = VR.list_verifications(st.root, statement_id=sid, limit=None)
    assert bad == [], bad
    sha = PR.proof_sha(text)
    return [int(r.get("path_group") or 0) for r in rows
            if str(r.get("proof_sha256") or "") == sha]


# ============================================================ a 新形式稿 = 第 1 条
def test_a_a_new_form_manuscript_is_ingested_as_the_first_path(tmp_path):
    st, b = _ws(tmp_path)
    _citable(st)
    sid = _register_proposition(st, b)
    got = _deliver(st, b, sid, REL1, P1)
    assert got.get("ok") is True, got
    sid = str(got.get("stmt_id") or "")
    assert sid and sid.isdigit(), got
    # 命题在册（一共两行：这一条 + 被引的引理）
    assert len(list(st.rows("statements"))) == 2, "只该多出这一条命题（外加引理）"
    # 证明正文落进那一行（canonical）
    assert PR.proof_sha(P1) == PR.proof_sha(str(_row(st, sid).get("proof_text") or ""))
    # 依赖行落表：一条，路径号 1，`used_by` 不带 #p1（与路径号一致）
    deps = _deps(st, sid)
    assert len(deps) == 1, deps
    assert int(deps[0].get("path_group") or 0) == 1, deps
    assert str(deps[0].get("used_by")) == f"stmt:{sid}", deps
    assert set(_ver_groups(st, sid, P1)) == {1}, _ver_groups(st, sid, P1)


# ============================================================ b 第二份 = 第 2 条
def test_b_a_second_new_form_manuscript_is_the_second_path(tmp_path):
    st, b = _ws(tmp_path)
    _citable(st)
    sid = _register_proposition(st, b)
    assert _deliver(st, b, sid, REL1, P1).get("ok") is True
    second = _deliver(st, b, sid, REL2, P2)
    assert second.get("ok") is True, second
    # 路径号由秘书分配：第二条 = 2
    reading = MS.path_reading(st, st.root, statement_id=sid)
    assert reading["checked"] is True and reading["count"] == 2, reading
    groups = sorted({int(d.get("path_group") or 0) for d in _deps(st, sid)})
    assert groups == [1, 2], _deps(st, sid)
    assert {str(d.get("used_by")) for d in _deps(st, sid)} == {
        f"stmt:{sid}", f"stmt:{sid}#p2"}, _deps(st, sid)
    # 两份证明各自可读（证明清单两条 + 各自一份 verification 行同号）
    proof_nos = [int(no) for no, _text in VR.proof_list(_row(st, sid))]
    assert proof_nos == [1, 2], proof_nos
    assert set(_ver_groups(st, sid, P1)) == {1}, _ver_groups(st, sid, P1)
    assert set(_ver_groups(st, sid, P2)) == {2}, _ver_groups(st, sid, P2)
    # 两份稿都在盘上、文件名都不带 `-pN`
    for rel in (REL1, REL2):
        assert "-p" not in pathlib.PurePosixPath(rel).stem.split("-")[-1], rel
        assert pathlib.Path(st.root, rel).is_file(), rel


# ============================================================ c 反真空
def test_c_stubbing_the_allocation_turns_b_red(tmp_path, monkeypatch):
    real = MS.assign_path_group

    def _always_one(**_kw):
        return {"checked": True, "path_group": 1, "existing": False, "count": 1,
                "paths": [], "why": "打桩：永远第 1 条"}

    monkeypatch.setattr(MS, "assign_path_group", _always_one)
    st, b = _ws(tmp_path)
    _citable(st)
    sid = _register_proposition(st, b)
    assert _deliver(st, b, sid, REL1, P1).get("ok") is True
    second = _deliver(st, b, sid, REL2, P2)
    ok = bool(second.get("ok"))
    groups = sorted({int(d.get("path_group") or 0) for d in _deps(st, sid)})
    assert (not ok) or groups != [1, 2], (
        "把分配打成永远第 1 条之后，第二份新形式稿仍然落在第 2 条路径上 ⇒ "
        f"这条判据没在看分配：ok={ok} groups={groups}")
    monkeypatch.setattr(MS, "assign_path_group", real)


# ============================================================ e 对齐
def test_e_the_path_number_no_longer_comes_from_the_delivery(tmp_path):
    from agentflow.agent_b import register_statement as RS

    # ---- 源码面：交付里那个号的两条读路径都不在了 ------------------------------
    assert not hasattr(AgentB, "_proof_no_from_delivery"), (
        "`_proof_no_from_delivery` 还在 ⇒ 稿头 / 携带单仍有一条读路径")
    assert not hasattr(RS._RegisterStatement, "_proof_no_from_delivery")
    assert not hasattr(RS._RegisterStatement, "_pointer_path_reading")
    assert not hasattr(RS._RegisterStatement, "_inline_path_reading")
    for fn in (Secretary.record_statement, Secretary._record_statement_tx,
               Secretary._merge_into_proposition, Secretary.extract_manuscript,
               RS._RegisterStatement._register_statement_impl):
        text = inspect.getsource(fn)
        assert "manuscript_proof_no" not in text, (
            f"{fn.__name__} 仍在读稿头「证明号」")
        assert "_proof_no_from_delivery" not in text, fn.__name__
    # 稿名里的 `-pN` 与参数对拍那一档整条退役：不再产 `proof_no_mismatch`。
    assert RS._RegisterStatement._ingest_proof_no({"name_proof_no": 2}, 1) == (1, "", "")
    # ---- 行为面：稿头写「证明号：2」也不会把第 1 条顶成第 2 条 ------------------
    st, b = _ws(tmp_path)
    _citable(st)
    sid = _register_proposition(st, b)
    got = _deliver(st, b, sid, REL1, P1, head_proof_no=2)
    assert got.get("ok") is True, got
    deps = _deps(st, sid)
    assert [int(d.get("path_group") or 0) for d in deps] == [1], deps
    assert {str(d.get("used_by")) for d in deps} == {f"stmt:{sid}"}, deps

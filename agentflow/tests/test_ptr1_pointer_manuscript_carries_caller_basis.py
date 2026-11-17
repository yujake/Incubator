# -*- coding: utf-8 -*-
"""PTR1：指针收录必须把调用方给的来路带上，而不是只认稿里抽出来的 `stmt:` 引用。

## 现场（MIG1 逐字报告）

`register_statement(proof_manuscript=...)` 的指针支只把本稿 `## 证明` 里的 `stmt:`
引用当 `derived_from` 传下去，调用方给的 `source_lit_id`（以及可选的 `derived_from`）
在这一层被丢掉 ⇒ 稿里不引用在册命题时，新的 own_result 来路闸
（`missing_own_result_basis`，判据在 `statementledger.own_result_basis_missing`）
必然拒 ⇒ 「自足、无引用」的 F 稿按指针收录没有任何诚实的来路可写。

这是产品口子，不是夹具问题：三条 tests-only 绕法都不成立（引用要过
`citation_below_proof_review` 门槛 + 补 `## 依赖` 表；先落前置命题会触发
`same_statement_unjudged`；给 `source_lit_id` 会被指针分支丢掉）。

## 改法与判据（先红后绿）

改法：指针支把调用方给的 `source_lit_id` 与 `derived_from` 透传进
`_register_pointer_manuscript` → `_register_statement_impl`，与稿里抽出来的
`derived_from` 合并（`_merged_derived_from`：调用方在前、稿里在后、去重；
落库前仍经 `schema.sorted_unique` 升序）。其余闸一个字不动。

| # | 判据 | 改前为什么红 |
|---|---|---|
| a | 指针收录 + 调用方给 `source_lit_id`（真 literature 行）⇒ 登记成功，行上 `source_lit_id` 就是那个号 | 指针分支丢掉 `source_lit_id` ⇒ `missing_own_result_basis`、零行 |
| b | 指针收录 + 调用方给 `derived_from`（真在册命题）⇒ 行上 `derived_from` 含它 | 同上（指针分支只传稿里的引用，稿里没有引用 ⇒ 空链） |
| c | 稿里引用 + 调用方也给 ⇒ 两者合并、去重、顺序确定 | 同上（调用方那一条被丢掉；合并这件事根本不存在） |
| d | 两者都空且稿里无引用 ⇒ 仍按新闸拒（`missing_own_result_basis`）、零行 | 改前也拒（这一条是"透传不许放宽闸"的负控，改后必须仍红） |
| e | 反真空：把透传打桩去掉 ⇒ a / b 必红 | ——（证明 a / b 的绿真的来自透传，不是"恰好别处放行"） |

## 不碰的闸（负控写在同一份文件里）

- 没有覆盖正文的 V 签 ⇒ 仍拒 `proof_without_v_sign`（签闸不许被来路透传绕过）；
- D 交稿仍只许递指针：D 传 `source_lit_id` ⇒ 仍拒
  `d_gives_manuscript_pointers_only`（正文闸不许被这一笔放宽）。

全部用例在 `tmp_path` 里自建工作区；签是 `conftest.sign_before_registration` 落的真
pending 台账（改一个字就认不到）⇒ 零模型调用；`projects/` 一个字不读写。
"""
from __future__ import annotations

import pathlib
import sys

import pytest

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from conftest import (add_literature, b_form_gate_ok,  # noqa: E402
                      seed_statement_row, sign_before_registration)
import _same_statement_stub as _SAME  # noqa: E402
from agentflow import conductor as CND  # noqa: E402
from agentflow import depsection as DS  # noqa: E402
from agentflow import evidencebits as EB  # noqa: E402
from agentflow.agent_b import AgentB  # noqa: E402
from agentflow.agent_b import register_statement as _RS  # noqa: E402
from agentflow.store import Store  # noqa: E402

MANUSCRIPT = "reports/f-proof-000000.md"
PROPOSITION = ("对任意有限群 G，若 p 是 |G| 的最小素因子，则 G 的每个子群的指数"
               "都不是 p 的倍数。")
PROOF = ("1. 取 G 的一个 Sylow p-子群 P（二阶 Sylow 定理）。\n"
         "2. |P| = p^a > 1 ⇒ 取 1 ≠ x ∈ P，由拉格朗日定理 ord(x) 是 p 的幂。\n"
         "3. 结论：x 的某个幂就是 p 阶元，故子群指数不可能是 p 的倍数。")

#: 夹具里的两格"真来路"：一条真文献行（`literature` 表里查得到）、两条真在册命题。
LIT_ID = "000888"
BASIS_STMT = "000777"      # 稿里引用它；预先补到可引门槛（pre_theorem）
OTHER_STMT = "000778"      # 只由调用方显式给出（不进稿）


@pytest.fixture(autouse=True)
def _offline_same_statement(monkeypatch: pytest.MonkeyPatch):
    """给"是不是在册的同一条命题"那一问接一个只答两件事的离线替身。

    工作区里铺了真在册命题（来路必须是真行）⇒ `_resolve_same_statement` 会走到
    "秘书挑检索词 + 两档判定"那一问；没有模型缝时它 fail-closed
    （`same_statement_unjudged`，不新建）—— 那是对的行为，但会把这一份判据要量的
    来路透传顶到前面。替身只替代"模型说了什么"（挑词 / 判不同），检索面与三态仍走
    生产实现（见 `tests/_same_statement_stub.py` 的口径）。
    """
    _SAME.wire_for_secretary(monkeypatch)


def _citable_bits() -> dict:
    """一条够"可引门槛"（`pre_theorem` = proof ∧ reviewed）的五元位。"""
    return EB.bits_of(
        proof=True, proof_process="前置命题的证明正文（夹具：真签过的那一版）",
        reviewed=True, reviewed_by={"verification_id": "v-ptr1-basis"},
        origin="own_result", kind="lemma")


def _seed_basis(store: Store) -> None:
    """铺两格真来路：真 literature 行 + 两条真在册命题（一条够可引门槛）。"""
    add_literature(store, LIT_ID, title="PTR1 夹具：真文献行", year=2026)
    seed_statement_row(
        store, stmt_id=BASIS_STMT, kind="lemma", origin="own_result",
        label="前置命题（夹具：真在册、够可引门槛）",
        statement_text="任意两个自然数的最大公约数唯一。",
        statement_full="任意两个自然数的最大公约数唯一（夹具脚手架，真在册的一行）。",
        bits=_citable_bits())
    seed_statement_row(
        store, stmt_id=OTHER_STMT, kind="lemma", origin="own_result",
        label="前置命题乙（夹具：真在册）",
        statement_text="自然数的加法满足交换律。",
        statement_full="自然数的加法满足交换律（夹具脚手架，真在册的一行）。")


def _workspace(tmp_path: pathlib.Path, *, proof_text: str = PROOF,
               deps_rows: tuple = (), sign: bool = True) -> dict:
    """自建工作区：真 literature 行 + 两条真在册命题 + 一份 F 手稿（可带依赖表）。"""
    st = Store(tmp_path / "ws")
    st.init()
    _seed_basis(st)
    deps = DS.render_dependency_section(list(deps_rows))
    text = (
        "# F 的证明手稿：PTR1\n\n"
        "- 依赖面洗稿：已洗=true；执行者=secretary:F\n\n"
        f"## 命题\n\n{PROPOSITION}\n\n"
        f"## 证明\n\n{proof_text}\n\n" + deps)
    target = pathlib.Path(st.root) / MANUSCRIPT
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    if sign:
        sign_before_registration(st.root, proof_text=proof_text)
    return {"store": st,
            "b": b_form_gate_ok(AgentB(st, extractor=None, extract_text=None,
                                       config={}))}


def _rows(env: dict) -> list[dict]:
    return [dict(r) for r in env["store"].rows("statements")
            if str(r.get("stmt_id")) not in (BASIS_STMT, OTHER_STMT)]


def _refusal(got: dict) -> str:
    """这一笔的受控码：真登记路给 `kind`，`ingest_manuscript` 包一层后给 `refused`。"""
    return str(got.get("kind") or got.get("refused") or "")


def _why(got: dict) -> str:
    return str(got.get("error") or got.get("why") or got.get("reason") or "")


def _as_d(task_id: str = "t-d-ptr1-000001"):
    return CND.calling_as(task_id, "D", parent_task_id="t-m-000001",
                          parent_role="M")


# ============================================================ a 文献来路透传
def test_a_pointer_with_source_lit_id_keeps_it_on_the_row(
        tmp_path: pathlib.Path) -> None:
    """a：指针收录 + 调用方给真 `source_lit_id` ⇒ 收下，行上就是那个号。"""
    env = _workspace(tmp_path)
    got = env["b"].register_statement(proof_manuscript=MANUSCRIPT,
                                      source_lit_id=LIT_ID)
    assert got.get("ok") is True, got
    rows = _rows(env)
    assert len(rows) == 1, f"应当只落一行，读到 {len(rows)}：{rows}"
    assert rows[0]["source_lit_id"] == LIT_ID, (
        "指针收录把调用方给的 source_lit_id 丢了（行上不是那个号）：\n"
        f"盘上 {rows[0].get('source_lit_id')!r}，调用方给的 {LIT_ID!r}")
    assert list(rows[0].get("derived_from") or []) == [], (
        "这一笔没有 derived_from 可写，行上不该冒出承重链："
        f"{rows[0].get('derived_from')!r}")
    assert dict(got.get("pointer") or {}).get("path") == MANUSCRIPT, got


# ============================================================ b 承重链透传
def test_b_pointer_with_derived_from_keeps_it_on_the_row(
        tmp_path: pathlib.Path) -> None:
    """b：指针收录 + 调用方给真在册命题 ⇒ 行上 derived_from 含它。"""
    env = _workspace(tmp_path)
    got = env["b"].register_statement(proof_manuscript=MANUSCRIPT,
                                      derived_from=[BASIS_STMT])
    assert got.get("ok") is True, got
    rows = _rows(env)
    assert len(rows) == 1, f"应当只落一行，读到 {len(rows)}：{rows}"
    assert list(rows[0].get("derived_from") or []) == [BASIS_STMT], (
        "指针收录把调用方给的 derived_from 丢了：\n"
        f"盘上 {rows[0].get('derived_from')!r}，调用方给的 {[BASIS_STMT]!r}")
    assert not str(rows[0].get("source_lit_id") or ""), (
        "这一笔没有给文献来路，行上不该冒出 source_lit_id："
        f"{rows[0].get('source_lit_id')!r}")


# ============================================================ c 合并、去重、顺序
def test_c_caller_and_manuscript_refs_are_merged_deduped_and_ordered(
        tmp_path: pathlib.Path) -> None:
    """c：稿里引用 + 调用方也给 ⇒ 两者合并、去重、顺序确定。"""
    proof = PROOF.replace(
        "2. |P| = p^a > 1",
        f"2. 由前置命题（stmt:{BASIS_STMT}），|P| = p^a > 1")
    deps_rows = ({"quote": "由前置命题（夹具）", "stmt_id": BASIS_STMT,
                  "step": "第 2 步"},)
    env = _workspace(tmp_path, proof_text=proof, deps_rows=deps_rows)
    # 调用方给的次序是 `OTHER_STMT` 在前；稿里抽出来的是 `BASIS_STMT`。
    # 合并 = 调用方在前、稿里在后；落库前升序 ⇒ 盘上必须是升序去重的两条。
    got = env["b"].register_statement(
        proof_manuscript=MANUSCRIPT,
        derived_from=[OTHER_STMT, BASIS_STMT])
    assert got.get("ok") is True, got
    rows = _rows(env)
    assert len(rows) == 1, f"应当只落一行，读到 {len(rows)}：{rows}"
    assert list(rows[0].get("derived_from") or []) == [BASIS_STMT, OTHER_STMT], (
        "调用方给的与稿里抽出来的没有合并 / 去重 / 定序：\n"
        f"盘上 {rows[0].get('derived_from')!r}，"
        f"期望 {[BASIS_STMT, OTHER_STMT]!r}")
    # 合并次序本身（去重保留第一次出现）在 helper 上是确定的：调用方在前。
    assert _RS._merged_derived_from(
        [OTHER_STMT, BASIS_STMT], [BASIS_STMT, "000999"]) == [
            OTHER_STMT, BASIS_STMT, "000999"]


# ============================================================ d 两格全空 ⇒ 仍拒
def test_d_both_basis_cells_empty_is_still_refused(
        tmp_path: pathlib.Path) -> None:
    """d：两者都空且稿里无引用 ⇒ 仍按来路闸拒、零行（透传不许放宽这道闸）。"""
    env = _workspace(tmp_path)
    before = _rows(env)
    got = env["b"].register_statement(proof_manuscript=MANUSCRIPT)
    assert got.get("ok") is False, got
    assert _refusal(got) == "missing_own_result_basis", got
    error = _why(got)
    assert "derived_from" in error and "source_lit_id" in error, error
    assert _rows(env) == before, "被来路闸拒掉的这一笔居然写了 statements"


# ============================================================ e 反真空：摘掉透传 ⇒ a/b 红
def test_e_stubbing_out_the_pass_through_makes_a_and_b_red(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """e：把指针支的透传打桩成"只传稿里的引用" ⇒ a / b 的同一笔必红。

    打桩打在最后一跳（`_register_pointer_manuscript`）：这是改前那一版的语义 ——
    调用方给的 `source_lit_id` / `derived_from` 到了这里被丢掉。a / b 变红证明它们
    的绿真的来自这一跳的透传，不是"恰好别处放行"。
    """
    real = AgentB._register_pointer_manuscript

    def _drop_basis(self, rel, *, provenance=None, reading=None,
                    nontriviality=None, **_kw):
        return real(self, rel, provenance=provenance, reading=reading,
                    nontriviality=nontriviality)

    monkeypatch.setattr(AgentB, "_register_pointer_manuscript", _drop_basis)

    for kwargs in ({"source_lit_id": LIT_ID}, {"derived_from": [BASIS_STMT]}):
        env = _workspace(tmp_path / f"stub-{sorted(kwargs)[0]}")
        before = _rows(env)
        got = env["b"].register_statement(proof_manuscript=MANUSCRIPT, **kwargs)
        assert got.get("ok") is False, (
            f"透传被打掉之后这一笔仍然收下了 ⇒ 判据没有咬住透传：{kwargs} / {got}")
        assert _refusal(got) == "missing_own_result_basis", (kwargs, got)
        assert _rows(env) == before, f"被拒的这一笔写了 statements：{kwargs} / {got}"


# ============================================================ 负控：其余闸不放宽
def test_no_other_gate_is_relaxed_the_sign_gate_still_bites(
        tmp_path: pathlib.Path) -> None:
    """来路透传不是签闸的通行证：没有覆盖正文的 V 签 ⇒ 仍拒、零行。"""
    env = _workspace(tmp_path, sign=False)
    before = _rows(env)
    got = env["b"].register_statement(proof_manuscript=MANUSCRIPT,
                                      source_lit_id=LIT_ID)
    assert got.get("ok") is False, got
    assert _refusal(got) == "proof_without_v_sign", got
    assert _rows(env) == before, "被签闸拒掉的这一笔居然写了 statements"


def test_no_other_gate_is_relaxed_d_still_gives_only_pointers(
        tmp_path: pathlib.Path) -> None:
    """D 交稿仍只许递指针：D 传 `source_lit_id` ⇒ 仍拒（正文闸一个字没动）。"""
    env = _workspace(tmp_path)
    before = _rows(env)
    with _as_d():
        got = env["b"].register_statement(proof_manuscript=MANUSCRIPT,
                                          source_lit_id=LIT_ID)
    assert got.get("ok") is False, got
    assert got.get("kind") == "d_gives_manuscript_pointers_only", got
    assert _rows(env) == before, "被 D 指针闸拒掉的这一笔居然写了 statements"


# ============================================================ f 工具面：来路递得进来
def test_f_tool_params_accept_the_pointer_plus_its_basis() -> None:
    """工具面（`own.register_statement` 的声明 params）收得下"指针 + 来路"这一形态。

    这一条不测登记，只测"模型按真实入口交这一笔时参数门不会把它挡在门外"：
    `source_lit_id` / `derived_from` 与 `proof_manuscript` 同时给，参数面必须通过。
    """
    import copy

    from agentflow.specs import b as SPEC_B
    from agentflow.tools.base import validate_params

    for spec in SPEC_B.ACTIONS:
        if spec.action == "register_statement":
            params = copy.deepcopy(dict(spec.params))
            break
    else:  # pragma: no cover —— 动作表里没有这一条：判据本身失效
        raise AssertionError("specs/b.py 的动作表里没有 register_statement")
    validate_params(params, {"statement_full": "",
                             "proof_manuscript": MANUSCRIPT,
                             "source_lit_id": LIT_ID,
                             "derived_from": [BASIS_STMT]})

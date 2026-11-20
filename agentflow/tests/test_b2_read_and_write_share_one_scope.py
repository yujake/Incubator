# -*- coding: utf-8 -*-
"""CLOSENARROW 判据：B-2 的读侧与写侧必须是同一份射程（2026-11-20）。

## 现场

`closing.type_ahead_of_grade_rows` 自称是 B-2 的读侧一半，而它改前只判"kind 超前于
现算等级"、不看这一行的来路。B-2 的写侧判据是三件一齐（`origin=own_result` +
无 `source_lit_id` + 没有一条回验通过的引文），所以文献里引来的定理在写侧从来进不了
这一档；读侧却会把它点名成"声明强于证据"。KINDGRADE 把那 6 行从 `conjecture` 改成
`theorem` 之后，lp-ball-13 的收工读数 `readings["statement_grade"]` 会点名 6 条。

## 这一笔把射程收成一处

三件搬进 `evidencebits.b2_scope_reading`：写侧的两个调用点（`register_statement.py`
的 `_b2_hits` 与登记收尾那一闸）与读侧 `type_ahead_of_grade_rows` 都调它。判据与被判的
对象是同一份实现 —— 两侧各写一份，就是"改了一侧、另一侧还按旧口径读数"。

## 判据

| 判据 | 守什么 | 改前 |
|---|---|---|
| a | 6 条 external_lit 的 theorem 行（带出处、引文回验通过）⇒ 这一格不点名 | 红（点名 6 条） |
| b | 正控：own_result + 无出处 + 无回验引文 + kind 超前 ⇒ 仍点名 | 绿（不许被收窄掉） |
| c | 三件缺一（origin / source_lit_id / 回验引文）⇒ 不点名（逐个位验） | 红（各自点名 1 条） |
| d | 反真空：把共判别据打桩成"永远在射程内" ⇒ a 必红 | — |
| e | 写侧的 B-2 拒收走的是同一个函数（打桩 ⇒ 拒收码改口） | — |
| f | 两个写侧调用点都调共判别据；"三件"在写侧文件里没有第二份抄本 | — |

改前读数（同一支探针，`temp/closenarrow/before.txt`）：a 点名 6 条、b 点名 1 条、
c 三格各点名 1 条、lp-ball-13 按 KINDGRADE 判据投影 kind 之后点名 6 条。
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from agentflow import closing
from agentflow import evidencebits as EB
from agentflow.store import Store

#: 与 `type_ahead_of_grade_rows` 里 `class` 那一格同一个受控名字。
CODE = closing.TYPE_AHEAD_OF_GRADE_CODE

#: 写侧 / 读侧两份源文件（判据 f 读它们的调用点；按路径读，不 import 写侧那一串
#: 依赖 —— 这一条判的是源码形态，不该被别的模块的瞬时状态拖红）。
REPO = pathlib.Path(__file__).resolve().parents[1]
RS_PATH = REPO / "src" / "agentflow" / "agent_b" / "register_statement.py"
CL_PATH = pathlib.Path(closing.__file__).resolve()

TS = "2026-11-20T00:00:00+08:00"


def _put(st: Store, stmt_id: str, *, kind: str, origin: str,
         source_lit_id: str | None = None, quote_verified=None,
         label: str = "") -> None:
    """落一条命题行（形状照盘上那 13 行：kind / origin / 出处 / 引文四栏齐全）。

    引文回验通过的行给 `quote_mode` 与 `quote_span`：读侧认"通过"要拿得出位置
    （`evidencebits.quote_state`），只写一个 `quote_verified=true` 的裸字段不算
    回验通过 —— 那一条也由本文件的 c3 反向钉住。

    `source_lit_id` 为空时不写这一格：schema 里"空串"不是"没有出处"（`require_id`
    会把它当格式错误拒掉），没有出处就是没有这一格。
    """
    row = {
        "stmt_id": stmt_id,
        "kind": kind,
        "origin": origin,
        "quote_verified": quote_verified,
        "quote_reason": ("" if quote_verified is True
                         else "探针：这一行没有一条回验通过的引文"),
        "statement_full": f"探针命题 {stmt_id}：这一行只用来读 B-2 的射程。",
        "label": label or stmt_id,
        "status": "active",
        "created_at": TS,
        "created_by": "test",
    }
    if source_lit_id:
        row["source_lit_id"] = source_lit_id
    if quote_verified is True:
        row["quote_mode"] = "verbatim"
        row["quote_span"] = "p1:norm[0:24]"
    with st.tx("statements", actor="test") as tx:
        tx.upsert("statements", row)


def _six_cited_theorems(st: Store) -> None:
    """KINDGRADE 改后那 6 行文献定理的形态（external_lit + 出处 + 引文回验通过）。"""
    for i in range(6):
        _put(st, f"{i:06d}", kind="theorem", origin="external_lit",
             source_lit_id="000002", quote_verified=True, label=f"文献定理 {i}")


def _reading(st: Store) -> dict:
    got = closing.type_ahead_of_grade_rows(st)
    assert got["state"] == "computed", got
    return got


def _assert_cited_theorems_are_not_named(st: Store) -> None:
    """a 的断言本体（d 的反真空直接复用它：打桩之后它必须红）。"""
    got = _reading(st)
    assert [r for r in got["rows"] if r["class"] == CODE] == [], got["rows"]
    assert got["scope"]["in_scope"] == 0, got["scope"]
    assert got["scope"]["out_of_scope"] == 6, got["scope"]


# ------------------------------------------------------------------ a 文献定理不点名
def test_a_a_cited_theorem_is_not_named_by_the_b2_read_side(store: Store) -> None:
    """a：6 条 external_lit 的 theorem 行 ⇒ 这一格一条都不点名（改前点名 6 条）。

    为什么这 6 行正是现场：它们 `origin=external_lit`、`source_lit_id` 非空、
    `quote_verified=true`（还带着可复核的区间）—— 三件里有两件直接写在行上。B-2 问的是
    "这一条是不是我们自产、又没有任何引文撑着"，文献定理两问都是否；改前读侧只数
    kind 与 grade，于是把它们读成"声明强于证据"。
    """
    _six_cited_theorems(store)
    _assert_cited_theorems_are_not_named(store)
    got = _reading(store)
    assert got["scope"]["predicate"] == "evidencebits.b2_scope_reading", got["scope"]


# ------------------------------------------------------------------ b 正控：仍被点名
def test_b_our_own_unbacked_claim_is_still_named(store: Store) -> None:
    """b（正控）：own_result + 无出处 + 无回验引文 + kind 超前 ⇒ 仍被点名。

    没有这一条，a 可以靠"把整张表都筛掉"变绿 —— 收窄不是把 B-2 的射程取消。
    """
    _put(store, "000000", kind="lemma", origin="own_result",
         quote_verified=None)
    got = _reading(store)
    assert [r["stmt_id"] for r in got["rows"]] == ["000000"], got["rows"]
    assert got["rows"][0]["kind"] == "lemma", got["rows"][0]
    assert got["rows"][0]["grade"] == "conjecture", got["rows"][0]
    assert got["scope"]["in_scope"] == 1, got["scope"]


# ------------------------------------------------------------------ c 三件缺一
#: (case, 落盘的行, 判据函数的入参, 应报出的那一件)
#:
#: origin 这一格拆成两份：schema 不允许 `external_lit` 没有出处（那种行在写侧更上面
#: 就被拒了），所以落盘那一份带出处（于是它也缺 source，不点名是双保险）；而
#: `b2_scope_reading` 单独喂"external_lit + 无出处"评一次，钉住它缺的确实是 origin
#: 这一件（三件互不吞并）。
_C_MISSING_ONE = (
    ("origin",
     {"kind": "theorem", "origin": "external_lit", "source_lit_id": "000002",
      "quote_verified": True},
     {"origin": "external_lit", "source_lit_id": "", "quote_verified": None},
     "origin"),
    ("source_lit_id",
     {"kind": "lemma", "origin": "own_result", "source_lit_id": "000002",
      "quote_verified": None},
     {"origin": "own_result", "source_lit_id": "000002", "quote_verified": None},
     "source_lit_id"),
    ("quote_verified",
     {"kind": "lemma", "origin": "own_result", "quote_verified": True},
     {"origin": "own_result", "source_lit_id": "", "quote_verified": True},
     "quote_verified"),
)


@pytest.mark.parametrize("case,fields,scope_kwargs,missing_word", _C_MISSING_ONE,
                         ids=[x[0] for x in _C_MISSING_ONE])
def test_c_each_missing_condition_keeps_the_row_out(
        store: Store, case: str, fields: dict, scope_kwargs: dict,
        missing_word: str) -> None:
    """c：三件缺一件 ⇒ 不点名；缺口必须由对应那一件说出（逐个位验）。

    只断言"不点名"是不够的：三件里任意一件写反（例如把 origin 判成 external_lit
    也算）都会让这条判据绿，而射程已经换了意思。所以这里同时读
    `b2_scope_reading` 的 `missing`，钉住是哪一件把它挡在外面。
    """
    _put(store, "000001", **fields)
    scope = EB.b2_scope_reading(**scope_kwargs)
    assert scope["in_scope"] is False, (case, scope)
    assert any(missing_word in line for line in scope["missing"]), (case, scope["missing"])
    got = _reading(store)
    assert got["rows"] == [], (case, got["rows"])
    assert got["scope"]["out_of_scope"] == 1, (case, got["scope"])


# ------------------------------------------------------------------ d 反真空
def test_d_anti_vacuum_stubbing_the_scope_turns_a_red(
        store: Store, monkeypatch: pytest.MonkeyPatch) -> None:
    """d（反真空）：把共判别据打桩成"永远在射程内" ⇒ a 的断言必红。

    打桩的是判据本体（`evidencebits.b2_scope_reading`），不是读侧的循环：这样红出来
    才证明 a 量的就是这条收窄，而不是"恰好没有 theorem 行"之类的别的原因。
    """
    _six_cited_theorems(store)
    real = EB.b2_scope_reading

    def always_in_scope(**kw):
        return {**real(**kw), "in_scope": True, "missing": [],
                "basis": "STUB：假装三件一齐（反真空）"}

    monkeypatch.setattr(EB, "b2_scope_reading", always_in_scope)
    assert len(_reading(store)["rows"]) == 6, "打桩之后 6 行没被点名 ⇒ a 什么也没量"
    with pytest.raises(AssertionError):
        _assert_cited_theorems_are_not_named(store)


# ------------------------------------------------------------------ e 写侧同一函数
def test_e_the_write_side_refusal_flows_through_the_shared_scope(
        store: Store, monkeypatch: pytest.MonkeyPatch) -> None:
    """e：写侧的 B-2 拒收由共判别据给出（不是它在自己文件里另写的那一份）。

    怎么判：先拿一笔真的应当被 B-2 拒的登记（own_result + 无出处 + 无回验引文 +
    `kind=lemma`）读一次拒收码；再把共判别据打桩成"永远不在射程"重交一条同形态的
    登记 —— 若写侧调的是这个函数，它的拒收码就必须改口（B-2 让路，落到 B-3 的
    `self_authored_needs_v`）；若写侧用的是自己那份抄本，打桩不会影响它。
    """
    # 写侧那一串依赖（AgentB / 秘书 / 缝）只在需要它的这一条里装配：别的判据量的是
    # 读侧与源码形态，不该因为写侧某条依赖的瞬时状态一起红。
    from test_b1_b2_b4_rulings import _b, _ok, _own, _with_manuscript

    first = _ok(_b(store).register_statement(
        **_with_manuscript(store, _own(kind="lemma"), statement_id="000000")))
    assert first.get("kind") == "must_start_as_conjecture", first

    real = EB.b2_scope_reading

    def never_in_scope(**kw):
        return {**real(**kw), "in_scope": False, "missing": ["STUB"],
                "basis": "STUB：永远不在射程（反真空）"}

    monkeypatch.setattr(EB, "b2_scope_reading", never_in_scope)
    second = _ok(_b(store).register_statement(
        **_with_manuscript(store, _own(kind="lemma", statement_full="另一条探针命题。"),
                           statement_id="000001")))
    assert second.get("kind") != "must_start_as_conjecture", second
    assert second.get("kind") == "self_authored_needs_v", second


# ------------------------------------------------------------------ f 没有第二份抄本
def _calls(path: pathlib.Path, name: str) -> list[ast.Call]:
    """这个文件里对 `name` 的调用点（AST：注释里的名字不算）。"""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out: list[ast.Call] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if isinstance(fn, ast.Attribute) and fn.attr == name:
            out.append(node)
        elif isinstance(fn, ast.Name) and fn.id == name:
            out.append(node)
    return out


def test_f_the_three_conditions_have_only_one_home() -> None:
    """f：两个写侧调用点 + 读侧一处都调共判别据；写侧没有第二份"三件"抄本。

    这一条盯的是"改了一侧、另一侧还按旧口径"的退化形态。写侧的 B-2 判据原先在两个
    调用点各写了一遍三件（一个在用、一个是兜底），读侧又只判 kind 与 grade ——
    三处三个口径。现在调用点数固定，且写侧文件里不再出现那串"origin 与无出处"的
    合取式；多一处或少一处都要有人来解释。
    """
    assert len(_calls(RS_PATH, "b2_scope_reading")) == 2, (
        "写侧的 B-2 判据不是两个调用点都调共判别据（改一处漏一处？）")
    assert len(_calls(CL_PATH, "b2_scope_reading")) == 1, (
        "读侧没有（或多于一处）调共判别据")
    text = RS_PATH.read_text(encoding="utf-8")
    old = 'str(origin) == "own_result" and not lit_id'
    assert old not in text, "写侧还有一份三件的抄本（旧合取式仍在）"

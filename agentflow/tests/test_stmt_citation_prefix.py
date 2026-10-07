# -*- coding: utf-8 -*-
"""`documents.claims[].citations` 的 `stmt:<命题号>` 前缀（`draft/68` 题 1，裁定 A）。

## 这一组守什么

改前（实测）：`closing` 的污染面只覆盖命题之间的 `derived_from`；正文断言的
`citations` 只认 `lit:` / `exp:` / `rel:`，没有引用命题的形式 ⇒
"哪几条正文断言压在这条命题上"判不了（那时它是一句写进读数的边界文字）。

2026-10-07 所有者裁定 `draft/68` 题 1 选 A，本次改动由所有者授权、主控代改：
`stmt:<命题号>` 成了一种合法写法，于是那句话从"判不了"变成一条真读数。

## 三态（本文件的核心判据结构）

"合法 / 不存在 / 没查到"三态各有落点，一条都不许折平：

```text
合法      前缀认得（`schema.CITATION_PREFIXES`）+ 目标在 `statements` 里
不存在    目标不在账本里 ⇒ 悬空引用：写入期与审计期各自报 error，不许静默放过
没查到    台账读不到 ⇒ `state="unreadable"`（不是"没有断言压着"）
```

## 判据的三条纪律

1. 前缀的唯一声明面是 `schema.CITATION_PREFIXES`，别处一律从它派生：
   `verify.CITATION_KINDS` 是算出来的，`doc_tools._CITATION_TABLES` 也是。
   ## 这一条口径的升级（题 18 选 A，2026-10-07 所有者裁定）

   改前 `verify` 侧那一份是逐字重抄的第二份字面量，于是这条判据只能把两边钉成
   "集合相等" —— 而"集合相等"对"两处各抄一份、恰好抄得一样"是恒真的：把 `stmt`
   从两处同时删掉，判据照样绿。升级后它问的是"只有一处来源"：`verify` 的源码里
   除了逐档分支那一侧的实现声明（`_BRANCH_KINDS`），不许再出现任何
   "抄了一整份前缀"的字面量容器；而 `CITATION_KINDS` 的取值必须真的引用声明面。
   判据只加不松：原来那条集合相等仍然在里面（现在是等式，连次序都钉住）。
2. 负控打在"目标不存在必须拒绝"与"污染面真的能顺着 claim 找到命题"上 ——
   不是"跑通了"。
3. 反真空：新增的读数不许恒为空（把 `stmt:` 引用从夹具里去掉之后，
   同一格必须变成 0，而"扫到多少条断言"那一格不许跟着变成 0）。
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from agentflow import claimanatomy as CA
from agentflow import closing as CL
from agentflow import gates as G
from agentflow import schema as S
from agentflow import verify as V
from agentflow.store import Store
from agentflow.tools import doc_tools as DT

from conftest import TS, sync_counters


# ============================================================ 夹具


def _claim(**over: object) -> dict:
    """一条八字段老形态的合法断言（判据层唯一的入口形态）。"""
    claim = {
        "claim_id": "claim-1",
        "section": "主要结果",
        "text": "谱落在区间内。",
        "evidence_kind": "proof",
        "citations": ["rel:0000"],
        "is_negative": False,
        "negation_kind": None,
        "disclaimer": "",
    }
    claim.update(over)
    return claim


def _stmt(store: Store, sid: str, **kw: object) -> dict:
    """一条命题（默认 active + external_lit + 逐字已核）。"""
    base = dict(stmt_id=sid, origin="external_lit", kind="theorem", label=f"Theorem {sid}",
                statement_text="命题短版", statement_full="若假设 A 成立，则结论 B 成立",
                proof_text="Proof. 逐字摘录……", source_lit_id="0000",
                quote_verified=True, quote_reason="逐字比对通过", evidence_kind="cross_check",
                status="active", created_at=TS)
    base.update(kw)
    row = S.Statement(**base)
    row.validate()
    with store.tx("statements", actor="test") as tx:
        tx.upsert("statements", row.to_dict())
    sync_counters(store)
    return row.to_dict()


def _doc(store: Store, doc_id: str, citations: list[str], **kw: object) -> dict:
    """一份带一条断言的稿件（`citations` 就是这条断言引的东西）。"""
    row = S.Document(
        doc_id=doc_id, kind="paper", title=f"稿件 {doc_id}",
        claims=[{"claim_id": "c1", "text": "谱落在区间内。", "citations": list(citations),
                 "evidence_kind": "proof", "section": "主要结果"}],
        status="draft", created_at=TS, **kw)
    row.validate()
    with store.tx("documents", actor="test") as tx:
        tx.upsert("documents", row.to_dict())
    sync_counters(store)
    return row.to_dict()


def _store(tmp_path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _rows_of(tables: dict[str, list[dict]]):
    """`check_citations` 要的读表能力（给假表，不碰文件系统）。"""
    return lambda table: tables.get(table, [])


class _UnreadableStore:
    """一个读盘就抛的 store（"这一趟没查成"的机械形态）。"""

    def rows(self, table: str):  # noqa: D401 - 夹具
        raise RuntimeError(f"盘坏了：{table}")


# ============================================================ 声明面：一处真身，三处一致


# ---------------------------------------------------------------- 源码形态：只有一处来源


def _verify_source() -> str:
    """`verify.py` 的源码（判据要读的是它的源码形态，不只是运行期取值）。"""
    return Path(V.__file__).read_text(encoding="utf-8")


def _assigned_value(tree: ast.AST, name: str) -> ast.expr | None:
    """模块里 `name = ...` / `name: T = ...` 的右值（最后一处赋值）。"""
    found: ast.expr | None = None
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], ast.Name) and node.targets[0].id == name:
            found = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) \
                and node.target.id == name:
            found = node.value
    return found


def _container_strings(value: ast.expr) -> tuple[str, ...] | None:
    """字面量容器里的全部字符串元素（不是字符串容器就返回 None）。

    `dict` 按它的键读：`{"rel": ...}` 这种"前缀 -> 某物"的表也算一份清单。
    """
    if isinstance(value, (ast.Tuple, ast.List, ast.Set)):
        if not all(isinstance(e, ast.Constant) and isinstance(e.value, str) for e in value.elts):
            return None
        return tuple(e.value for e in value.elts)
    if isinstance(value, ast.Dict):
        if not all(isinstance(k, ast.Constant) and isinstance(k.value, str) for k in value.keys):
            return None
        return tuple(k.value for k in value.keys)
    return None


def _prefix_literal_collections(tree: ast.AST) -> list[tuple[str, tuple[str, ...]]]:
    """`verify.py` 里"抄了一整份前缀"的字面量赋值（`(名字, 元素)` 列表）。

    判据的形态为什么是 AST 而不是"文本里搜 rel"：逐档判据本身是
    `elif kind == "rel" and ...` 这样一档一档写的，那些单字符串字面量是实现、
    不是清单；要被抓住的是"一个容器里装着若干个前缀"这种第二份抄件。
    所以这里只走赋值的右值（任何名字、任何作用域），且要求元素全部落在声明面里、
    去重后至少两个 —— 于是"换个变量名再抄一份"也会被抓住。
    """
    prefixes = set(S.CITATION_PREFIXES)
    out: list[tuple[str, tuple[str, ...]]] = []
    for node in ast.walk(tree):
        target: str | None = None
        if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], ast.Name):
            target = node.targets[0].id
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            target = node.target.id
        if target is None:
            continue
        elems = _container_strings(node.value)
        if elems and len(set(elems)) >= 2 and set(elems) <= prefixes:
            out.append((target, elems))
    return out


def _single_source_problems(tree: ast.AST) -> list[str]:
    """`verify.py` 是否只从声明面取前缀（空 = 是）。正控与负控走同一段逻辑。"""
    out: list[str] = []
    copies = sorted(name for name, _ in _prefix_literal_collections(tree))
    if "CITATION_KINDS" in copies:
        out.append("CITATION_KINDS 又被写成了字面量容器 ⇒ verify 里出现了第二份前缀清单")
    if copies != ["_BRANCH_KINDS"]:
        out.append("抄了一整份前缀的赋值应当只有 _BRANCH_KINDS（逐档分支那一侧），"
                   f"实际是 {copies}")
    value = _assigned_value(tree, "CITATION_KINDS")
    if value is None:
        out.append("找不到 CITATION_KINDS 的赋值")
    elif "CITATION_PREFIXES" not in ast.unparse(value):
        out.append(f"CITATION_KINDS 的取值 {ast.unparse(value)!r} 没有引用声明面 "
                   "schema.CITATION_PREFIXES ⇒ 它可能又是一份抄件")
    return out


def test_the_citation_prefix_registry_is_the_single_source():
    """前缀声明面：`schema.CITATION_PREFIXES` 是唯一真身，别处一律从它派生。

    改前是几处各写一份（`verify.CITATION_KINDS` 一张元组、`doc_tools._CITATION_TABLES`
    一张 dict、`gates.gate_g2` 内联的四个前缀），于是 `stmt:` 在 `verify`/`doc_tools`
    侧已经被认（`R-03` 那次代改），而 G2 仍报"不在可解析的种类里"、`closing` 仍说
    "判不了" —— 同一个字符串四个结论，没有任何读数会响。

    ## 口径（题 18 选 A 之后）：不是"两边相等"，是"只有一处来源"

    只断言集合相等，对"两处各抄一份、恰好抄得一样"是恒真的。现在钉三件事：
    `verify.CITATION_KINDS` 与声明面逐字相等（含次序）、它的取值真的引用声明面、
    以及 `verify.py` 源码里除了逐档分支那一侧的 `_BRANCH_KINDS` 再无第二份清单。

    反真空：这张表必须真的指向 `TABLES` 里存在的表（否则"一致"可以靠两边都错来达成），
    且 `stmt` 那一格必须在（它是 `draft/68` 题 1 的落点）。
    """
    assert S.CITATION_PREFIXES["stmt"] == "statements", S.CITATION_PREFIXES
    assert len(S.CITATION_PREFIXES) >= 4, S.CITATION_PREFIXES
    for prefix, table in S.CITATION_PREFIXES.items():
        assert table in S.TABLES, f"{prefix!r} 指向的表 {table!r} 不在 TABLES 里"
        assert S.TABLES[table]["id_field"], f"{table} 没有 id_field ⇒ 谁也核不了它的存在性"
        assert S.citation_prefix_table(prefix) == table, prefix
    assert S.citation_prefix_table("zzz") is None, "不认识的前缀必须是 None（不是猜一张表）"
    # 派生值：与声明面逐字相等（改前只钉集合，次序漂了看不出来）
    assert V.CITATION_KINDS == tuple(S.CITATION_PREFIXES), (
        f"verify.CITATION_KINDS={V.CITATION_KINDS} 不是声明面 "
        f"{tuple(S.CITATION_PREFIXES)} 的派生值 ⇒ 写入期与审计期会对同一个前缀给出"
        "两个结论（或同一条拒绝消息给出两种词表次序）")
    # 只有一处来源：源码形态上不许再有第二份前缀清单
    assert _single_source_problems(ast.parse(_verify_source())) == [], (
        "verify.py 里出现了第二份前缀清单 ⇒ 声明面不再是唯一来源"
        f"（源码检查结果：{_single_source_problems(ast.parse(_verify_source()))}）")
    assert dict(S.CITATION_PREFIXES) == DT._CITATION_TABLES, (
        f"声明面 {S.CITATION_PREFIXES} 与 doc_tools._CITATION_TABLES "
        f"{DT._CITATION_TABLES} 分家（前者是真身，后者是派生）")
    assert set(S.CITATION_PREFIXES) <= set(_citation_kinds_g2_uses()), (
        "G2 的可解析前缀不是从声明面派生的 ⇒ `stmt:` 会在写入期合法、在这道门上被报")


def test_the_single_source_checker_catches_a_second_literal_copy():
    """负控：把 `CITATION_KINDS` 换回字面量抄件 ⇒ 同一个检查必须报出来。

    没有这一条，"只有一处来源"这句话可能只是恒真（检查器没牙）：改前那种形态
    （`CITATION_KINDS = ("rel", "lit", "exp", "eval", "doc", "stmt")`）必须被抓住，
    而改后的真实源码必须干净。注入用源码替换，盘上的文件一个字节都不动。
    """
    src = _verify_source()
    assert _single_source_problems(ast.parse(src)) == [], "改后的真实源码应当干净"
    assert [n for n, _ in _prefix_literal_collections(ast.parse(src))] == ["_BRANCH_KINDS"], \
        "逐档分支那一侧的实现声明（`_BRANCH_KINDS`）不见了 ⇒ 判据的锚点变了"

    anchor = "CITATION_KINDS: tuple[str, ...] = tuple(S.CITATION_PREFIXES)"
    assert anchor in src, "负控锚点不在源码里（那一行的写法变了）⇒ 这条负控没生效"
    bad = src.replace(anchor, 'CITATION_KINDS: tuple[str, ...] = ("rel", "lit", "exp", '
                              '"eval", "doc", "stmt")')
    problems = _single_source_problems(ast.parse(bad))
    assert problems, "第二份字面量抄件没被报出来 —— 上面那条判据在这个形态上没有牙"
    assert any("CITATION_KINDS" in p for p in problems), problems


def _citation_kinds_g2_uses() -> tuple[str, ...]:
    """G2 实际认得的前缀集合（逐个喂进这道门，读它自己的 `counts`）。

    为什么不 import 门里的私有常量：那样会把"门从声明面派生"这件事测成
    "门里那个常量恰好等于声明面"——门改成内联一份同值表，判据照样绿。
    喂一个前缀进去、读 `前缀可解析` 是不是 1，测的才是门的行为。
    """
    kinds: list[str] = []
    for kind in S.CITATION_PREFIXES:
        doc = {"doc_id": "0000", "kind": "paper", "title": "t", "status": "draft",
               "claims": [_claim(citations=[f"{kind}:0001"])]}
        r = G.gate_g2(G.GateContext.build(doc))
        if r.counts["前缀可解析"] == 1 and r.counts["前缀不可解析"] == 0:
            kinds.append(kind)
    return tuple(kinds)


def test_the_registry_contract_catches_a_prefix_pointing_at_no_table(monkeypatch):
    """负控：把声明面改坏 ⇒ 导入期那条对账必须红（两种坏法各一次）。

    为什么必须有它：`assert_citation_prefix_contract()` 是这条契约唯一的机器读数 ——
    没有它，往表里塞一个"谁也核不了"的前缀（或把 `stmt` 摘掉）不会有任何东西响。
    """
    import agentflow.schema as SS

    monkeypatch.setitem(SS.CITATION_PREFIXES, "zzz", "no_such_table")
    with pytest.raises(AssertionError, match="TABLES 里没有的表"):
        SS.assert_citation_prefix_contract()
    monkeypatch.delitem(SS.CITATION_PREFIXES, "zzz")

    monkeypatch.delitem(SS.CITATION_PREFIXES, "stmt")
    with pytest.raises(AssertionError, match="stmt"):
        SS.assert_citation_prefix_contract()
    monkeypatch.setitem(SS.CITATION_PREFIXES, "stmt", "statements")


# ============================================================ 判据层：真前缀


def test_the_judge_layer_accepts_stmt_and_rejects_unresolvable_forms():
    """判据层（G 与 H 共用的唯一入口）：`stmt:` 合法；不认识的前缀与裸号是 error。

    改前 `claimanatomy` 对 citations 只判"非空、非空串"⇒ 裸号与 `zzz:` 一路放行，
    直到写入期 `doc_tools.check_citations` 才被拒 —— 两个判据两个结论。
    """
    ok = CA.validate_claim(_claim(citations=["stmt:0004"]))
    assert "bad_citation_prefix" not in {i.code for i in ok.issues}, ok.issues

    for bad in ("zzz:0004", "0004", "rel:"):
        spec = CA.validate_claim(_claim(citations=[bad]))
        codes = {i.code for i in spec.issues}
        assert "bad_citation_prefix" in codes, (bad, spec.issues)
        assert spec.error_count >= 1, (bad, spec.issues)
    # 空元素走的是另一条既有判据（`bad_type`）—— 两条不重叠，也不许互相吞掉
    blank = CA.validate_claim(_claim(citations=["  "]))
    assert {i.code for i in blank.issues} >= {"bad_type"}, blank.issues
    # 裸号的拒信要可操作（告诉作者写成哪一种）：这一档与"未知前缀"分开处置
    bare = CA.validate_claim(_claim(citations=["0004"]))
    msg = "；".join(i.message for i in bare.issues if i.code == "bad_citation_prefix")
    assert "stmt:0004" in msg and "lit:0004" in msg, msg


# ============================================================ 存在性：三态不许折平


def test_a_missing_statement_target_is_rejected_not_silently_allowed():
    """负控（本组最要紧的一条）：`stmt:<不存在的命题>` 必须被拒，不许静默放行。

    三态在这里逐格分开：合法（422 次命中）/ 不存在（`missing` 逐条列出）/
    没查到（`rows_of is None` ⇒ `checked=False`，绝不许读成"引用都存在"）。
    """
    tables = {"statements": [{"stmt_id": "0004", "status": "active"}],
              "documents": [], "relations": [], "literature": [], "experiments": [],
              "eval_results": []}
    good = DT.check_citations(_rows_of(tables), [_claim(citations=["stmt:0004"])])
    assert good["checked"] is True and good["missing"] == [] and good["resolved"] == 1, good

    bad = DT.check_citations(_rows_of(tables), [_claim(citations=["stmt:9999"])])
    assert bad["checked"] is True and bad["resolved"] == 0, bad
    assert [m["kind"] for m in bad["missing"]] == ["stmt"], bad
    assert "statements 表里没有 stmt_id='9999'" in bad["missing"][0]["why"], bad

    # 第三态：没查到（不是"引用都存在"，也不是"引用都不存在"）
    unchecked = DT.check_citations(None, [_claim(citations=["stmt:0004"])])
    assert unchecked["checked"] is False and "没查" in unchecked["reason"], unchecked
    assert unchecked["missing"] == [] and unchecked["resolved"] == 0, unchecked


def test_gate_g2_resolves_a_statement_citation():
    """G2（引用解析门）：`stmt:0004` 是可解析前缀（改前它被报"不在可解析的种类里"）。"""
    doc = {"doc_id": "0000", "kind": "paper", "title": "t", "status": "draft",
           "claims": [_claim(citations=["stmt:0004"])]}
    r = G.gate_g2(G.GateContext.build(doc))
    assert r.counts["前缀可解析"] == 1 and r.counts["前缀不可解析"] == 0, r.counts
    assert r.verdict == "pass", (r.verdict, r.reason)

    # 防误伤（负控的另一半）：真正不认识的前缀照样只 warning，不许升级成 fail
    doc2 = {"doc_id": "0000", "kind": "paper", "title": "t", "status": "draft",
            "claims": [_claim(citations=["doi:10.1000/x"])]}
    r2 = G.gate_g2(G.GateContext.build(doc2))
    assert r2.verdict == "pass" and r2.counts["前缀不可解析"] == 1, (r2.verdict, r2.counts)


# ============================================================ 污染面：读数与级联


def test_the_pollution_reading_finds_the_claims_pressing_on_a_statement(tmp_path):
    """污染面真的能顺着 claim 找到命题：读数、级联与处置三格都在。

    改前这一格是 `not_judged`（数据形式都没有）；现在它是现算读数，而且
    `contradiction_pollution` 这条 blocker 第一次能因为稿件里的断言而亮。
    """
    st = _store(tmp_path)
    _stmt(st, "0001", status="refuted", quote_reason="原文条件少了正性假设")
    _stmt(st, "0002", derived_from=["0001"])
    _doc(st, "0001", ["stmt:0001", "stmt:0002"])

    rep = CL.check_closing(st, checks=("contradictions",))
    r = rep.readings["contradictions"]
    lvl = r["pollution_assertion_level"]
    assert lvl["state"] == "computed", lvl
    assert lvl["claims_total"] == 1 and lvl["claims_citing_a_statement"] == 1, lvl
    assert lvl["statements_cited"] == 2, lvl
    # 逐条读数只跟"被证否的那些命题"走（与 `pollution` 同一口径）：0002 是 active，
    # 所以它不在这一格里 —— 要问"谁引了 0002"用 `assertions_pressing_on`（它对任何命题都答）。
    assert r["pollution_assertions"] == {
        "0001": [{"doc_id": "0001", "claim_id": "c1",
                  "citation": "stmt:0001", "stmt_id": "0001"}],
    }, r["pollution_assertions"]
    assert r["pollution_dangling_statements"] == [], r["pollution_dangling_statements"]

    reading = CL.pollution_reading(st, "0001")
    assert reading["state"] == "computed", reading
    assert reading["downstream"] == ["0002"], reading
    assert [x["claim_id"] for x in reading["assertions"]] == ["c1"], reading
    one = CL.assertions_pressing_on(st, "0001")
    assert one["state"] == "computed" and len(one["assertions"]) == 1, one
    other = CL.assertions_pressing_on(st, "0002")
    assert other["state"] == "computed", other
    assert [x["citation"] for x in other["assertions"]] == ["stmt:0002"], other
    assert CL.assertions_pressing_on(st, "0001")["dangling"] == [], "没有悬空引用"

    # 级联：被证否的命题下面压着正文断言 ⇒ blocker 必须亮（改前只有 downstream 才亮）
    assert "contradiction_pollution" in {f.code for f in rep.findings}, [f.code for f in rep.findings]
    detail = " ".join(f.detail for f in rep.findings if f.code == "contradiction_pollution")
    assert "0001#c1" in detail and "正文断言" in detail, detail
    assert "G 改稿" in detail, detail


def test_a_dangling_statement_citation_is_its_own_bucket(tmp_path):
    """负控：`stmt:9999`（目标不存在）不许被静默算成"压在 9999 上"，也不许被丢掉。

    三态各一格：目标不存在（`dangling` 那一栏）/ 命题本身不在账本里
    （`assertions_pressing_on` 的 `no_such_statement`）/ 没查到（`unreadable`）。
    """
    st = _store(tmp_path)
    _doc(st, "0001", ["stmt:9999"])
    cited = CL.statements_cited_by_claims(st)
    assert cited["state"] == "computed", cited
    assert cited["by_statement"] == {}, cited
    assert [x["stmt_id"] for x in cited["dangling"]] == ["9999"], cited

    rep = CL.check_closing(st, checks=("contradictions",))
    r = rep.readings["contradictions"]
    assert [x["citation"] for x in r["pollution_dangling_statements"]] == ["stmt:9999"], r
    assert r["pollution_assertion_level"]["claims_citing_a_statement"] == 1, r

    missing = CL.assertions_pressing_on(st, "9999")
    assert missing["state"] == "no_such_statement", missing
    assert missing["assertions"] is None, missing

    unreachable = CL.assertions_pressing_on(_UnreadableStore(), "0001")
    assert unreachable["state"] == "unreadable", unreachable
    assert unreachable["assertions"] is None, unreachable


def test_the_assertion_level_reading_is_not_vacuous(tmp_path):
    """反真空：新增的那一格读数不许恒为空 —— 去掉 `stmt:` 引用它必须变成 0。

    只配一条 `lit:` 引用的稿件：`claims_total` 仍是 1（扫到了断言），
    而 `claims_citing_a_statement` 是 0（真的没有 `stmt:` 引用）——
    两格分开给，才分得清"这一层干净"与"这一层根本没扫到东西"。
    """
    st = _store(tmp_path)
    _stmt(st, "0001", status="refuted", quote_reason="原文条件少了正性假设")
    _doc(st, "0001", ["lit:0000"])
    rep = CL.check_closing(st, checks=("contradictions",))
    lvl = rep.readings["contradictions"]["pollution_assertion_level"]
    assert lvl["state"] == "computed", lvl
    assert lvl["claims_total"] == 1 and lvl["claims_citing_a_statement"] == 0, lvl
    # `{'0001': []}` 不是"没有读数"：那条被证否的命题查过了、确实没有断言引它
    # （空字典才是"这一趟没有一条被证否的命题"）。
    assert rep.readings["contradictions"]["pollution_assertions"] == {"0001": []}, \
        rep.readings["contradictions"]["pollution_assertions"]
    # 而且这条 blocker 不许因为"有一条被证否的命题"就自己亮（那会是假报警）
    assert "contradiction_pollution" not in {f.code for f in rep.findings}, \
        [f.code for f in rep.findings]

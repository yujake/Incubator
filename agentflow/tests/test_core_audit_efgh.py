"""后半段模块（E/F/G/H + llm/extract/pipeline/quoteverify）的审计回归。

本文件里每一条用例都对应 `temp/inventory/INVENTORY.md` 第 4 节落在
`agent_e.py` / `agent_f.py` / `agent_g.py` / `agent_h.py` / `pipeline.py` /
`llm.py` / `extract.py` / `quoteverify.py` 上的一条条目，或者对应本次审计
新发现的一条缺陷。纪律：

- 每条修复都配一条负控。只断言"该拒的拒了"是不够的：一个永远拒绝的实现
  也能通过所有正向断言。所以每条"修好了"的用例旁边都有一条"不该拒的没被拒"。
- 两条职责边界写成结构性断言（扫源码 AST），而不是"读一遍觉得没问题"：
  - H 只读：`agent_h.py` 里除了它自己的 `review_findings` 与 `documents.status`，
    不许写任何表；`AgentH` 类体内一个 `store.tx` 都不许有。
  - G 每条断言必须带引用：`agent_g.py` 里每一处写 `documents` 的事务都必须
    先跑 `normalize_claims`（引用存在性由 `check_citations` 复用同一判据）。
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest
from conftest import add_concept, add_literature, add_relation

from agentflow import schema as S
from agentflow.agent_e import AgentE, ExperimentError, build_experiment, install_e_tools
from agentflow.agent_f import AgentF, PlanError, install_f_tools
from agentflow.agent_g import AgentG, DocumentError, install_g_tools
from agentflow.agent_h import AgentH, ReviewError, _SELFTEST_HARNESS
from agentflow.extract import DocumentText, page_count
from agentflow.llm import LLMExtractor, _locate_verbatim, parse_llm_json
from agentflow.llm import ExtractionError
from agentflow.quoteverify import check_quote
from agentflow.store import Store
from agentflow.tools import review_tools as RV
from agentflow.tools.base import ToolError

# ============================================================ 公共小工具

P1 = "Group theory studies algebraic structures."
P2 = "An abelian group is a group in which the commutative law holds."
P3 = "The identity element is unique in every group."


def _doc(pages: list[str]) -> DocumentText:
    return DocumentText(text="\n".join(pages), pages=list(pages), source_kind="pdf")


def _src_dir() -> Path:
    import agentflow

    return Path(agentflow.__file__).resolve().parent


def _read_source(name: str) -> str:
    return (_src_dir() / name).read_text(encoding="utf-8")


#: `goal-7f5116c1` M6/M7：八个角色模块改成了包（一个动作一个文件）。
#: 下面几条结构性判据原本只读一个文件；它们现在必须读整包，
#: 而且要把动作 mixin（`_Review` / `_Revise` 这类）里的方法算回角色类名下 ——
#: 否则"`AgentH` 类体内不许写盘"会在拆包后变成真空：动作方法搬进了 mixin，
#: `startswith("AgentH.")` 再也匹配不到任何东西，判据看起来还是绿的。
def _role_files(name: str) -> list[Path]:
    """角色的落点：拆包后是包（按名排好序），未拆包时是单个模块。"""
    pkg = _src_dir() / name.removesuffix(".py")
    if pkg.is_dir():
        return sorted(pkg.glob("*.py"))
    return [_src_dir() / name]


def _role_mixins(name: str) -> set[str]:
    """角色类的直接基类里那些"动作 mixin"（去掉 `_Core`）。"""
    role_cls = "Agent" + name.split("_")[1][0].upper()
    core = _src_dir() / name.removesuffix(".py") / "core.py"
    if not core.is_file():
        return set()
    tree = ast.parse(core.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == role_cls:
            return {ast.unparse(b).split(".")[-1] for b in node.bases} - {"_Core"}
    return set()


def _role_scan_writes(name: str) -> list[tuple[str, tuple[str, ...], int, str]]:
    """整包扫写盘；mixin 里的方法归到角色类名下（保持拆包前那几条断言的含义）。"""
    role_cls = "Agent" + name.split("_")[1][0].upper()
    mixins = _role_mixins(name)
    out: list[tuple[str, tuple[str, ...], int, str]] = []
    for f in _role_files(name):
        for fname, tables, lineno, kind in _scan_writes(f):
            head, _, tail = fname.partition(".")
            if head in mixins:
                fname = f"{role_cls}.{tail}"
            out.append((fname, tables, lineno, kind))
    return out


def _role_calls_by_function(name: str) -> dict[str, set[str]]:
    """整包的"每个函数调了哪些属性名"（同名函数取并集；跨文件拼装成一个视图）。"""
    out: dict[str, set[str]] = {}
    for f in _role_files(name):
        for fname, names in _calls_by_function(f).items():
            out.setdefault(fname, set()).update(names)
    return out


def _role_claim_literal_lines(name: str) -> list[str]:
    """整包里"手搓 claim 字面量"的落点（`文件:行号`）。"""
    hits: list[str] = []
    for f in _role_files(name):
        tree = ast.parse(f.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Dict):
                continue
            keys = {k.value for k in node.keys
                    if isinstance(k, ast.Constant) and isinstance(k.value, str)}
            if {"text", "evidence_kind"} <= keys:
                hits.append(f"{f.name}:{node.lineno}")
    return hits


# ============================================================ 1. llm.py：引文定位（B 的唯一自动幻觉防线）


def test_locate_verbatim_composes_a_decomposed_accent():
    """INVENTORY（llm.py 引文定位）：分解形与预组合形必须认作同一串。

    PDF/LaTeX 抽取常给出 ``e`` + U+0301（分解形），而模型抄的是 ``é``（预组合形）。
    整串 NFKC 下两者相等；逐字符 NFKC 下不等 —— 于是真引文被当成幻觉剔除。
    """
    text = "Spe\u0301ctrum of K(m) lies in [\u2212m, m]."
    got = _locate_verbatim(text, "Sp\u00e9ctrum of K(m)")
    assert got is not None, "真引文被判成幻觉"
    assert got in text, "返回的必须是原文切片（fail-closed 的一半）"
    assert got == "Spe\u0301ctrum of K(m)"


def test_locate_verbatim_still_rejects_a_different_word_after_the_fix():
    """负控：修 NFKC 不许把"多认几个字"变成"什么都认"。"""
    text = "Spe\u0301ctrum of K(m) lies in [\u2212m, m]."
    assert _locate_verbatim(text, "sp\u00e9ctrum of K(n)") is None
    assert _locate_verbatim(text, "Spectrum of L(m)") is None
    # 组合记号挂错基字符（"c"+´ = ć ≠ "e"+´ = é）必须仍然不认 ——
    # 这保证上面的"认得出来"不是因为规范化把两个不同的字糊在了一起。
    assert _locate_verbatim("Spec\u0301ctrum", "Sp\u00e9ctrum") is None


def test_locate_verbatim_deletes_a_soft_hyphen_instead_of_inserting_a_space():
    """INVENTORY（llm.py 引文定位）：软连字符是零宽字符，不是空白。

    把它当空白会凭空插入一个空格（``abel\\u00adian`` → ``abel ian``），
    于是 PDF 断词处的一句真引文永远匹配不上。
    """
    text = "An abel\u00adian group is commutative."
    got = _locate_verbatim(text, "abelian group is commutative")
    assert got is not None
    assert got in text and got == "abel\u00adian group is commutative"


def test_locate_verbatim_never_returns_something_outside_the_text():
    """性质断言：无论走哪条匹配路径，返回值要么是 ``None``，要么是 ``text`` 的子串。

    这条是"fail-closed"的形式化表达：调用方拿到的东西不需要再相信谁。
    """
    cases = [
        ("a b", "a  b"),
        ("a\n\nb", "a b"),
        ("Spe\u0301ctrum", "Sp\u00e9ctrum"),
        ("abel\u00adian", "abelian"),
        ("\uff21\uff22", "AB"),  # 全角 → 半角
        ("x", "y"),
        ("", "a"),
    ]
    for text, quote in cases:
        got = _locate_verbatim(text, quote)
        assert got is None or got in text, (text, quote, got)


class _FakeClient:
    """离线假客户端：把预置字符串当 LLM 回复。"""

    def __init__(self, payload: str) -> None:
        self.payload = payload

    def complete(self, prompt: str) -> str:  # noqa: ARG002 - 契约要求这个名字
        return self.payload


def _llm_payload(quote: str) -> str:
    return json.dumps(
        {
            "concepts": [{"name": "spectrum"}, {"name": "interval"}],
            "relations": [
                {
                    "concept_names": ["spectrum", "interval"],
                    "description": "谱落在区间内",
                    "quote": quote,
                    "page_range": {"start": 1, "end": 1},
                }
            ],
        },
        ensure_ascii=False,
    )


def test_llm_extractor_keeps_a_real_quote_that_differs_only_by_unicode_form():
    """端到端：`_ground_relations` 不许因为 Unicode 表示形式把真引文剔除。"""
    page = "Spe\u0301ctrum of K(m) lies in [\u2212m, m]."
    doc = DocumentText(text=page, pages=[page], source_kind="pdf")
    ex = LLMExtractor(_FakeClient(_llm_payload("Sp\u00e9ctrum of K(m) lies in [\u2212m, m]")))
    _, rels = ex.extract(doc, "0000", {})
    assert len(rels) == 1, ex.last_report
    assert rels[0].quote in page, "存下去的必须是原文切片，不是模型原话"
    assert "quote_not_found" not in ex.last_report["drop_reasons"]


def test_llm_extractor_still_drops_a_fabricated_quote():
    """负控（幻觉防线的核心）：编造的引文一条都不许进库。

    没有这条负控，"修好了假阴性"就无法与"把闸门整个拆了"区分开。
    """
    page = "Spe\u0301ctrum of K(m) lies in [\u2212m, m]."
    doc = DocumentText(text=page, pages=[page], source_kind="pdf")
    ex = LLMExtractor(_FakeClient(_llm_payload("The spectrum is always a compact set.")))
    _, rels = ex.extract(doc, "0000", {})
    assert rels == []
    assert ex.last_report["relations_dropped"] == 1
    assert ex.last_report["drop_reasons"] == ["quote_not_found"]


def test_parse_llm_json_tolerates_decoration_but_not_garbage():
    """INVENTORY 4.2：`llm.parse_llm_json` 零提及 —— 它决定入库内容，必须钉住。

    正向：围栏 / 寒暄 / 结尾多余逗号都容忍。
    负控：解析不出对象就抛，绝不"从文本里猜几个概念"。
    """
    assert parse_llm_json('```json\n{"a": 1,}\n```') == {"a": 1}
    assert parse_llm_json('好的，结果如下：\n{"a": 1}\n希望有帮助') == {"a": 1}
    assert parse_llm_json('```json\n{"a": [1, 2,],}\n```') == {"a": [1, 2]}
    for bad in ("", "   ", "没有任何 JSON", "[1, 2]", '"just a string"'):
        with pytest.raises(ExtractionError):
            parse_llm_json(bad)


# ============================================================ 2. extract.py：page_count 的 None 分支


def test_page_count_returns_none_for_non_pdf_and_for_unreadable_pdf(tmp_path):
    """INVENTORY 4.2：`extract.page_count` 明确承诺"读不出来返回 None"，零提及。

    - 非 PDF ⇒ `None`（文本类文件没有"页"这个概念，返回 1 会诱导调用方以为页码可定位）
    - 读不出来 ⇒ `None`（诊断性函数，不许让调用方崩）
    """
    txt = tmp_path / "a.txt"
    txt.write_text("hello", encoding="utf-8")
    assert page_count(txt) is None
    assert page_count(tmp_path / "missing.txt") is None

    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"this is definitely not a pdf")
    assert page_count(broken) is None, "坏 PDF 不许抛，只许如实返回 None"
    assert page_count(tmp_path / "missing.pdf") is None


# ============================================================ 3. agent_f.py


def _f_store(tmp_path: Path) -> tuple[Store, AgentF]:
    st = Store(tmp_path / "ws")
    st.init()
    return st, AgentF(st)


def _abandon_first_plan(st: Store) -> None:
    with st.tx("attack_plans", actor="test", note="force_terminal") as tx:
        rows = tx.rows("attack_plans")
        rows[0]["status"] = "abandoned"
        tx.upsert("attack_plans", rows[0])


def test_list_plans_treats_explicit_null_as_the_declared_default(tmp_path):
    """INVENTORY 4.5#13：`include_terminal` 传显式 `null` 时静默反转了默认值。

    schema 声明默认 `True`；`null` 能通过参数校验（`validate_params` 对 `None`
    跳过类型检查）。修之前 `if not include_terminal:` 把 `None` 当成 `False`
    —— 同一个意图在"省略键"与"显式 null"两条输入路径上给出相反答案，且不报错。
    """
    st, f = _f_store(tmp_path)
    f.create_plan("难题 A", "k-a")
    f.create_plan("难题 B", "k-b")
    _abandon_first_plan(st)

    assert f.list_plans()["total"] == 2, "省略键 = 声明的默认值 True"
    assert f.list_plans(include_terminal=True)["total"] == 2
    assert f.list_plans(include_terminal=None)["total"] == 2, "显式 null 也必须等于默认值"
    assert f.list_plans(include_terminal=False)["total"] == 1, "**负控**：要过滤必须明确写 False"


def test_attack_list_plans_tool_agrees_with_omission_on_null(tmp_path):
    """工具层同样：`attack.list_plans(include_terminal=null)` 的 reason 不许自相矛盾。"""
    st, f = _f_store(tmp_path)
    f.create_plan("难题 A", "k-a")
    f.create_plan("难题 B", "k-b")
    _abandon_first_plan(st)
    reg = install_f_tools(st)

    omitted = reg.call("attack.list_plans")
    explicit_null = reg.call("attack.list_plans", include_terminal=None)
    only_alive = reg.call("attack.list_plans", include_terminal=False)

    assert omitted.ok and explicit_null.ok and only_alive.ok
    assert omitted.data["total"] == explicit_null.data["total"] == 2
    assert only_alive.data["total"] == 1
    assert "include_terminal=True" in explicit_null.data["reason"], (
        "reason 必须回报**生效的**取值，不许回报调用方写的 null"
    )


def test_plan_error_does_not_escape_as_unexpected_and_keeps_its_own_kind(tmp_path):
    """INVENTORY 4.3(b)：`attack.*` 的失败此前逃出工具层被兜成 `kind="unexpected"`。

    本用例的断言被改过一次（改的是期望值，不是判据），逐字留痕：

    - 旧：`assert bad.meta.get("kind") == "tool_error"`，并且第一句 docstring 写着
      *"`attack_tools.py` 没有 `guard_result`（该文件不属于本次交付），所以
      `agent_f.PlanError` 必须自己继承 `ToolError`，让工具层给出 `kind="tool_error"`"*；
    - 新：`assert bad.meta.get("kind") == "plan_error"`。

    为什么旧断言是错的（不是"因为它变红了"）：`PlanError` 继承 `ToolError`
    只是让失败不再无声——它把"攻坚计划层面的拒绝"和"工具层自己的异常"
    （参数错 / 未接线）压进了同一个 `tool_error` 档。而调用方要靠 kind 决定
    "重试还是改输入"：计划不存在 ⇒ 改 plan_id；表坏了 ⇒ 先修表。
    工具层现在有了守卫（`attack_tools._guard`，与 `doc_tools.guard_result` 同形），
    守卫把 `PlanError` 映射成它自己那一档 `plan_error`，消息逐字保留。
    判据没变：不许是 `unexpected`，且原因必须可读（下面两句仍在）。
    改名是为了让"它断言的是什么"与"实现给的是什么"重新对齐 ——
    名字里留着 `is_a_tool_error` 会继续教下一个人"这一档就该是笼统的"。
    """
    st, _ = _f_store(tmp_path)
    reg = install_f_tools(st)

    bad = reg.call("attack.create_plan", problem="x", problem_key="k1", subgoals=[{"sid": "s1", "text": "t"}])
    assert bad.ok is False
    assert bad.meta.get("kind") != "unexpected"
    assert bad.meta.get("kind") == "plan_error"
    assert "缺少 owner" in bad.error

    missing = reg.call("attack.step", plan_id="9999")
    assert missing.meta.get("kind") == "plan_error" and "不存在" in missing.error


def test_plan_error_stays_compatible_with_callers_that_catch_it(tmp_path):
    """负控：改基类不许破坏既有调用约定。

    `PlanError` 仍然是 `PlanError`（`except PlanError` 照旧命中），
    也仍然是 `RuntimeError`（既有 `except RuntimeError` 的调用点行为不变）。
    """
    st, f = _f_store(tmp_path)
    assert issubclass(PlanError, ToolError)
    assert issubclass(PlanError, RuntimeError)
    with pytest.raises(PlanError):
        f.create_plan("", "k")
    with pytest.raises(RuntimeError):
        f.status  # noqa: B018 - 仅确认符号存在
        f.create_plan("x", "")


def test_attack_create_plan_schema_violation_is_reported_with_a_reason(tmp_path):
    """schema 的 `ValueError` 也必须被换成带原因的受控 kind（而不是 `unexpected`）。

    本用例的断言被改过一次（改的是期望值，不是判据），逐字留痕：

    - 旧：`assert res.ok is False and res.meta.get("kind") == "tool_error"`；
    - 新：`assert res.ok is False and res.meta.get("kind") == "plan_error"`。

    为什么旧断言是错的：`AgentF.create_plan` 把 schema 的 `ValueError`
    包成了 `PlanError`（`agent_f.py:1088`，语义正确的包装），所以这一支
    实际走的是 `PlanError`。旧断言只能说出"笼统的 tool_error"，
    而它真正要钉住的判据是"非法计划不许落库，且原因（哪个字段、什么取值）
    必须逐字可见" —— 下面两句正是那句判据，它们没有变。
    工具层现在把 `PlanError` 单列成 `plan_error`（守卫只此一份，
    `attack_tools._guard`），比"笼统的 tool_error"更能回答
    "该重试还是该改输入"。
    """
    st, _ = _f_store(tmp_path)
    reg = install_f_tools(st)
    res = reg.call(
        "attack.create_plan",
        problem="x",
        problem_key="k2",
        budget={"max_rounds": "abc", "max_parallel_subgoals": 1, "max_persist_attempts": 1, "max_depth": 1},
    )
    assert res.ok is False and res.meta.get("kind") == "plan_error"
    assert "schema" in res.error and "k2" in res.error
    assert st.rows("attack_plans") == [], "非法计划不许落库"


# ============================================================ 4. agent_g.py：引用闸门（本次新发现）


def _g_store(tmp_path: Path) -> tuple[Store, AgentG]:
    st = Store(tmp_path / "ws")
    st.init()
    add_literature(st, "0000", title="T")
    return st, AgentG(st)


def test_revise_rejects_a_claim_whose_citation_does_not_exist(tmp_path):
    """INVENTORY 4.3②/职责边界（新发现的绕过路径）：`revise` 绕过了引用存在性闸门。

    `build_document` 有两道闸（`normalize_claims` 查"有没有引用"、
    `check_citations` 查"引用的东西在不在"），`revise` 此前只过了第一道 ——
    于是"修订"成了一条把假引用写进 `documents.claims` 的后门。
    """
    st, g = _g_store(tmp_path)
    good = g.compose_claim("谱落在区间内。", citations=["lit:0000"], evidence_kind="heuristic",
                           section="s", claim_id="claim-1")
    doc_id = g.build_document("note", "标题", claims=[good])["doc_id"]

    dangling = g.compose_claim("另一条断言。", citations=["lit:9999"], evidence_kind="heuristic",
                               section="s", claim_id="claim-1")
    with pytest.raises(DocumentError) as ei:
        g.revise(doc_id, new_claims=[dangling])
    assert "不存在" in str(ei.value)


def test_revise_rejection_leaves_the_document_completely_untouched(tmp_path):
    """负控（原子性）：被拒的修订不许留下半成品（claims / review_rounds 都不动）。"""
    st, g = _g_store(tmp_path)
    good = g.compose_claim("谱落在区间内。", citations=["lit:0000"], evidence_kind="heuristic",
                           section="s", claim_id="claim-1")
    doc_id = g.build_document("note", "标题", claims=[good])["doc_id"]
    before = json.loads((st.data / "documents.json").read_text(encoding="utf-8"))

    dangling = g.compose_claim("坏引用。", citations=["lit:9999"], evidence_kind="heuristic",
                               section="s", claim_id="claim-1")
    with pytest.raises(DocumentError):
        g.revise(doc_id, new_claims=[dangling])

    after = json.loads((st.data / "documents.json").read_text(encoding="utf-8"))
    assert after == before, "整笔必须回滚"
    assert st.rows("documents")[0]["review_rounds"] == 0


def test_revise_still_accepts_a_properly_cited_claim(tmp_path):
    """负控（防误伤）：引用真实存在的修订必须照旧能过。"""
    st, g = _g_store(tmp_path)
    good = g.compose_claim("谱落在区间内。", citations=["lit:0000"], evidence_kind="heuristic",
                           section="s", claim_id="claim-1")
    doc_id = g.build_document("note", "标题", claims=[good])["doc_id"]
    better = g.compose_claim("谱落在区间内（改写版）。", citations=["lit:0000"], evidence_kind="heuristic",
                             section="s", claim_id="claim-1")
    out = g.revise(doc_id, new_claims=[better])
    assert out["status"] == "revised" and out["review_rounds"] == 1
    assert st.rows("documents")[0]["claims"][0]["text"] == "谱落在区间内（改写版）。"


def test_revise_rejects_a_claim_without_any_citations(tmp_path):
    """职责边界（G）：无引用的断言不许进稿 —— 修订路径同样如此。"""
    st, g = _g_store(tmp_path)
    good = g.compose_claim("谱落在区间内。", citations=["lit:0000"], evidence_kind="heuristic",
                           section="s", claim_id="claim-1")
    doc_id = g.build_document("note", "标题", claims=[good])["doc_id"]
    with pytest.raises(ValueError, match="没有任何 citations"):
        g.revise(doc_id, new_claims=[
            {"claim_id": "claim-2", "section": "s", "text": "无引用", "evidence_kind": "heuristic",
             "citations": []}
        ])


# ---- 结构性断言：G 的每一条断言都必须带引用 --------------------------------


def _calls_by_function(path: Path) -> dict[str, set[str]]:
    """扫出每个函数（含 ``Class.method``）体内被调用的属性名集合。"""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out: dict[str, set[str]] = {}

    def visit(node: ast.AST, fname: str, cls: str | None) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                visit(child, fname, child.name)
                continue
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                visit(child, f"{cls}.{child.name}" if cls else child.name, None)
                continue
            if isinstance(child, ast.Call):
                fn = child.func
                name = fn.attr if isinstance(fn, ast.Attribute) else (fn.id if isinstance(fn, ast.Name) else "")
                if name:
                    out.setdefault(fname, set()).add(name)
            visit(child, fname, cls)

    visit(tree, "<module>", None)
    return out


def test_agent_g_writes_documents_only_through_normalize_claims():
    """职责边界（G）：`agent_g.py` 里每一处写 `documents` 的事务都必须先跑
    `normalize_claims`（"有没有引用"）+ `check_citations`（"引用的东西在不在"）。

    `revise` 曾经只跑了前者 —— 这条断言把"两条路复用同一判据"变成机械可查的事实，
    而不是靠读代码记得。
    """
    calls = _role_calls_by_function("agent_g.py")
    checked = 0
    for fname, names in calls.items():
        if "tx" not in names or fname == "_selftest":  # 自检的夹具播种，不是写稿路径
            continue
        checked += 1
        assert "normalize_claims" in names, f"{fname} 写 documents 却没跑 normalize_claims"
        assert "check_citations" in names, f"{fname} 写 documents 却没核引用是否存在"
    assert checked >= 1, "扫描没找到任何写库事务 —— 断言本身失效了"


def test_agent_g_source_never_builds_a_claim_literal_without_citations():
    """职责边界（G）的结构形式：`agent_g`（包）里不许出现任何"手搓 claim"的字面量。

    所有断言都必须经由 `DT.compose_claim` / `DT.normalize_claims` 构造，
    这样"没有 citations 的断言"在结构上就无处可写。
    """
    built = _role_claim_literal_lines("agent_g.py")
    assert built == [], f"agent_g 里这些地方手搓了 claim 字面量（应走 compose_claim）：{built}"


# ============================================================ 5. agent_h.py：H 只读（结构性）


def _scan_writes(path: Path) -> list[tuple[str, tuple[str, ...], int, str]]:
    """扫出所有"写盘"调用：``(所属函数, 表名字面量, 行号, 种类)``。

    种类覆盖两条通道：
    - ``tx``：经 `Store.tx` 写表（受 schema 校验）；
    - ``write_text`` / ``write_bytes`` / ``_atomic_write``：绕过 store 直接改盘
      （`_inject_raw_document` 用的就是这条 —— 它必须被同样地钉住，
      否则"绕过 schema 写一行坏数据"就成了结构断言看不见的后门）。
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    kinds = {"tx", "write_text", "write_bytes", "_atomic_write"}
    found: list[tuple[str, tuple[str, ...], int, str]] = []

    def visit(node: ast.AST, fname: str, cls: str | None) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                visit(child, fname, child.name)
                continue
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                visit(child, f"{cls}.{child.name}" if cls else child.name, None)
                continue
            if isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute) and child.func.attr in kinds:
                tables = tuple(
                    a.value for a in child.args if isinstance(a, ast.Constant) and isinstance(a.value, str)
                )
                found.append((fname, tables, child.lineno, child.func.attr))
            visit(child, fname, cls)

    visit(tree, "<module>", None)
    return found


def test_agent_h_class_never_writes_any_table_directly():
    """职责边界（H）：`AgentH` 类体内不许有任何一处写盘调用。

    这是"H 只能提发现、不能改稿"的最强形式：H 的落库动作必须全部走
    `self.writers`（落点被钉死在 `review_findings` 与 `documents.status`）。
    类体内出现 `store.tx` / `write_text` 就意味着有一条绕过落库代理的写路径。
    """
    calls = [c for c in _role_scan_writes("agent_h.py") if c[0].startswith("AgentH.")]
    assert calls == [], f"AgentH 类体内出现了直接写盘：{calls}"


def test_agent_h_module_writes_tables_only_inside_the_declared_fixture_harness():
    """职责边界（H）：模块级的写盘调用必须全部落在声明的自检夹具里。

    INVENTORY 第 3 节的判据是"除 `review_findings`/`documents` 之外的表为空"。
    实测该判据在本文件上不成立：自检夹具要造 concepts/relations/literature/
    dependencies 才能让"审校前后逐字节不变"这条运行期只读断言非空、有意义。

    所以这里把豁免显式穷举，并且把两条通道分别钉死：
    经 `store.tx` 的只有 `_seed_document` / `_selftest`；
    绕过 store 直接改盘的只有 `_inject_raw_document`。
    模块里的 `_SELFTEST_HARNESS` 必须正好是这两者的并集 —— 声明与实际不一致
    就说明有人加了一处没登记的写入（这正是"降级必须显式"的形态）。
    """
    writes = _role_scan_writes("agent_h.py")
    outside = [c for c in writes if not c[0].startswith("AgentH.") and c[0] not in _SELFTEST_HARNESS]
    assert outside == [], f"自检夹具之外出现了写盘调用：{outside}"

    tx_funcs = {f for f, _t, _ln, k in writes if k == "tx"}
    raw_funcs = {f for f, _t, _ln, k in writes if k != "tx"}
    assert tx_funcs == {"_seed_document", "_selftest"}, f"经 store.tx 写表的函数变了：{sorted(tx_funcs)}"
    assert raw_funcs == {"_inject_raw_document"}, f"绕过 store 直接改盘的函数变了：{sorted(raw_funcs)}"
    assert set(_SELFTEST_HARNESS) == tx_funcs | raw_funcs, (
        f"豁免清单与实际情况不一致：声明 {sorted(_SELFTEST_HARNESS)}，"
        f"实际 tx={sorted(tx_funcs)} raw={sorted(raw_funcs)}。"
        "清单必须穷举 —— 否则它就是一张会自动变成空头的许可证"
    )


def test_agent_h_source_never_assigns_documents_claims():
    """职责边界（H）：`agent_h.py` 里不许有任何一处给 `...["claims"]` 赋值。

    这条是本文件最有价值的一条。修之前本文件里有两处：
    1. `_selftest` 里 ``row = tx.find("documents", ...); row["claims"] = ...``
       （actor 写着 "fake-G"）—— 一份明文可抄的"绕过 H 只读、直接改稿"的写法，
       就写在"证明 H 只读"的那个文件里；
    2. `_selftest` 里 ``bad = dict(clean); bad["claims"] = [...]`` —— 同样是
       "拿一行稿件改掉它的断言"的形状。

    第 1 处改成调用真正的改写方 `AgentG.revise`；第 2 处改成整行字面量
    （构造一份坏输入喂给 H，而不是改动一行已有稿件）。现在任何一处
    ``X["claims"] = ...`` 都会让这条变红 —— 包括"我只是想在自检里顺手改一下数据"。
    """
    hits: list[str] = []
    for f in _role_files("agent_h.py"):
        tree = ast.parse(f.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            targets = node.targets if isinstance(node, ast.Assign) else (
                [node.target] if isinstance(node, (ast.AugAssign, ast.AnnAssign)) else []
            )
            for t in targets:
                if (isinstance(t, ast.Subscript) and isinstance(t.slice, ast.Constant)
                        and t.slice.value == "claims"):
                    hits.append(f"{f.name}:{node.lineno}")
    assert hits == [], f"agent_h 里这些地方改动了 documents.claims（那是 G 的活）：{hits}"

def test_agent_h_writers_registry_exposes_exactly_the_declared_write_tools(tmp_path):
    """职责边界（H）的运行期形式：H 的落库代理里能写的只有这三个工具。

    本轮从 2 个变成 3 个：新增 `review.report`（G1–G15 审校报告，
    markdown 落盘）。它不是对"H 只读"的放宽 —— 它的落点仍被钉死在一个报告
    文件上，不碰任何数据表、不碰 `claims`（`tests/test_gates.py` 有一条
    逐字节断言）。这条用例的判据因此从"数量"改成"逐个点名"：
    数量会随着正当的新增而漂移，而"落点清单"必须是人逐条写下来的。
    """
    st = Store(tmp_path / "ws")
    st.init()
    h = AgentH(st)
    writers = [t["name"] for t in h.writers.describe() if t["side_effect"] in ("write_local",)]
    assert sorted(writers) == [
        "review.report",
        "review.review_document",
        "review.verify_fixes",
    ], writers
    free = {t["side_effect"] for t in h.tools.describe()}
    assert free <= {"none", "read"}, f"H 的自由工具箱出现了写工具：{free}"


def test_agent_h_refuses_a_writers_registry_carrying_another_write_tool(tmp_path):
    """职责边界（H）的负控：注入一个能改表的落库代理必须 fail-closed 拒绝启动。

    `tools=` 有装配期断言，而 `writers=` 此前完全没有校验 —— 传进来一个带
    `table.update` 的注册表，"落点被钉死"就只剩一句注释。这条用例把那个洞钉住。
    """
    from agentflow.tools import table_tools
    from agentflow.tools.base import ToolRegistry as _Reg

    st = Store(tmp_path / "ws")
    st.init()
    poisoned = _Reg(name="poisoned-writers")
    table_tools.register(poisoned, store=st, roles=("H",))
    assert "table.update" in poisoned.names(), "夹具没有真的放进一个写工具"
    with pytest.raises(ReviewError, match="落库代理"):
        AgentH(st, writers=poisoned)

    # 负控的负控：只有那两个钉死的写工具时，必须照常启动。
    ok_reg = _Reg(name="ok-writers")
    RV.register(ok_reg, store=st, include_writers=True)
    assert AgentH(st, writers=ok_reg).writers is ok_reg


def _h_fixture(tmp_path: Path) -> tuple[Store, str]:
    """造一份审校应当干净的最小数据集（知识表非空 ⇒ 字节比对才有意义）。"""
    st = Store(tmp_path / "ws")
    st.init()
    add_literature(st, "0000", title="Commutativity in abelian groups", processed=True)
    add_concept(st, "0000", "group", related_concepts=["0001"])
    add_concept(st, "0001", "abelian group", related_concepts=["0000"])
    add_relation(st, "0000", ["0000", "0001"], "0000",
                 quote="An abelian group is a group in which the commutative law holds.",
                 group_key="0000|0001", quote_verified=True)
    row = S.Document(
        doc_id="0000",
        kind="paper",
        title="H 只读的负控稿件",
        markdown_path=None,
        claims=[
            {
                "claim_id": "claim-1",
                "section": "主要结果",
                "text": "阿贝尔群是满足交换律的群。",
                "evidence_kind": "heuristic",
                "citations": ["rel:0000", "lit:0000#p.1-1"],
                "is_negative": False,
                "negation_kind": None,
                "disclaimer": "",
            }
        ],
        status="draft",
        created_at=S.now_iso(),
        updated_at=S.now_iso(),
    )
    row.validate()
    with st.tx("documents", actor="seed", note="fixture") as tx:
        tx.upsert("documents", row.to_dict())
    return st, "0000"


def test_agent_h_review_changes_only_status_and_never_the_claims(tmp_path):
    """职责边界（H）的负控：跑一遍完整审校，知识表与 `claims` 必须逐字节不变。

    只做结构扫描是不够的：结构扫描证明"没有明文的写路径"，
    这条证明"运行时真的什么都没写"。
    """
    st, doc_id = _h_fixture(tmp_path)
    knowledge = ("statements.json", "relations.json", "literature.json")
    before_bytes = {n: (st.data / n).read_bytes() for n in knowledge}
    before_docs = json.loads((st.data / "documents.json").read_text(encoding="utf-8"))

    h = AgentH(st, config={"max_review_rounds": 2})
    h.review(doc_id, dependencies=[])
    h.verify_fixes(doc_id, round_no=2)

    for n in knowledge:
        assert (st.data / n).read_bytes() == before_bytes[n], f"{n} 被 H 改动了"
    after_docs = json.loads((st.data / "documents.json").read_text(encoding="utf-8"))
    for rb, ra in zip(before_docs["rows"], after_docs["rows"]):
        assert ra.get("claims") == rb.get("claims"), "H 改了 documents.claims —— 那是 G 的活"
        changed = {k for k in set(rb) | set(ra) if rb.get(k) != ra.get(k)}
        # 2026-10-17（业主：「H 审过和通过是完全不同的状态」）：同一次事务里还会写审核轴
        # 三字段（`review_verdict`/`reviewed_at`/`reviewed_by`）—— 仍然不许碰 claims
        # 与任何知识表（上面两条已分别断言），这只是"多记了谁在何时判了什么"。
        assert changed <= {"status", "review_rounds",
                           "review_verdict", "reviewed_at", "reviewed_by"}, (
            f"H 改动了不该动的字段：{sorted(changed)}")


# ============================================================ 6. pipeline.py：I1（D 必须拿到 C 实例）


REQUEST = "查询 群 与 域 之间的关系"


@pytest.fixture
def demo_store(tmp_path) -> Store:
    from demo_dataset_helper import build_demo

    return Store(build_demo(tmp_path / "demo"))


def _spy_on_d(monkeypatch) -> dict:
    """把 `pipeline.AgentD` 换成抓参数的探针。"""
    import agentflow.pipeline as P

    captured: dict = {}
    real = P.AgentD

    def spy(store, **kw):
        captured.update(kw)
        captured["_store"] = store
        captured["_obj"] = real(store, **kw)
        return captured["_obj"]

    monkeypatch.setattr(P, "AgentD", spy)
    return captured


def test_run_pipeline_passes_c_explicitly_to_agent_d(demo_store, tmp_path, monkeypatch):
    """I1：`run_pipeline` 构造 `AgentD` 时必须显式传 C 实例（D 要能"按需向 C 点菜"）。"""
    captured = _spy_on_d(monkeypatch)
    import agentflow.pipeline as P

    P.run_pipeline(
        demo_store, request=REQUEST, gap_rounds=1, agent_a=None, agent_b=None,
        d_report_path=tmp_path / "demo" / "r.md",
    )
    assert "c" in captured, "必须**显式**传 c= 关键字（隐式兜底会让 I1 静默退化）"
    assert captured["c"] is not None, "D 拿到的 C 是 None ⇒ I1 失效"
    assert captured["_obj"].c is not None


def test_run_pipeline_builds_c_once_and_gives_that_same_instance_to_d(demo_store, tmp_path, monkeypatch):
    """装配点唯一：C 只装配一次，且交给 D 的就是跑分析的那个实例。

    修之前这里装配了两个 AgentC（`_c_for_d`（非指代：已删的旧装配点名）一个、第 1 步的 `agent_c` 一个），
    而注释却写着"装配点唯一、可审计" —— 注释与实现相反。
    """
    import agentflow.pipeline as P

    built: list = []
    real_load = P._load_agent_c

    def spy_load(store, cfg):
        obj = real_load(store, cfg)
        built.append(obj)
        return obj

    monkeypatch.setattr(P, "_load_agent_c", spy_load)
    captured = _spy_on_d(monkeypatch)
    out = P.run_pipeline(
        demo_store, request=REQUEST, gap_rounds=1, agent_a=None, agent_b=None,
        d_report_path=tmp_path / "demo" / "r.md",
    )
    assert out["mode"] == "analyze"
    assert len(built) == 1, f"C 被装配了 {len(built)} 次（应为 1 次）"
    assert captured["c"] is built[0], "交给 D 的 C 不是跑分析的那个实例"


def test_run_pipeline_c_config_keys_cannot_diverge(demo_store, tmp_path, monkeypatch):
    """I1 的配置分叉：`auto_build_c=False` + `build_agent_c=True` 时 C 在跑，D 也必须拿到它。

    修之前注入 D 的判据只看 `auto_build_c`，第 1 步却看三个键的并集 ——
    于是这个配置会得到"C 在跑、D 手里却没有 C"，连一行警告都不会有。
    """
    import agentflow.pipeline as P

    captured = _spy_on_d(monkeypatch)
    out = P.run_pipeline(
        demo_store,
        request=REQUEST,
        gap_rounds=1,
        config={"auto_build_c": False, "build_agent_c": True},
        agent_a=None,
        agent_b=None,
        d_report_path=tmp_path / "demo" / "r.md",
    )
    assert out["mode"] == "analyze", "C 应当被装配并跑分析"
    assert captured["c"] is not None, "C 明明在跑，D 却拿不到它 ⇒ I1 静默退化"


def test_run_pipeline_replay_mode_still_allows_c_to_be_absent(demo_store, tmp_path, monkeypatch):
    """负控：显式关掉自动装配时，D 拿到 `None` 是有意的（replay 模式）。"""
    import agentflow.pipeline as P

    # 先正常跑一次，把 C 报告登记进 analysis_reports（replay 模式需要已有报告）。
    P.run_pipeline(
        demo_store, request=REQUEST, gap_rounds=1, agent_a=None, agent_b=None,
        d_report_path=tmp_path / "demo" / "r1.md",
    )
    captured = _spy_on_d(monkeypatch)
    out = P.run_pipeline(
        demo_store, request=REQUEST, gap_rounds=1, config={"auto_build_c": False},
        agent_a=None, agent_b=None, d_report_path=tmp_path / "demo" / "r2.md",
    )
    assert out["mode"] == "replay"
    assert captured["c"] is None


# ============================================================ 7. quoteverify.py：三态不许被折成布尔


def test_quote_check_verified_is_three_state_and_never_coerced():
    """INVENTORY（quoteverify）：`QuoteCheck.verified` 必须是 `True`/`False`/`None` 三态。

    这里逐条钉住三种状态，并断言 `to_dict()` 原样透传（不许 `bool(...)` 折叠，
    否则"没能校验"会以 JSON `false` 的形式流到报告里，被读成"引文是假的"）。
    """
    doc = _doc([P1, P2, P3])
    cases = [
        (check_quote(doc, P2, S.PageRange(2, 2, "p. 2")), True),
        (check_quote(doc, "This sentence appears nowhere at all.", S.PageRange(1, 2, "pp. 1-2")), False),
        (check_quote(_doc([]), P2, S.PageRange(1, 1, "p. 1")), None),
        (check_quote(doc, "", S.PageRange(1, 1, "p. 1")), None),
    ]
    for chk, expected in cases:
        assert chk.verified is expected, (chk, expected)
        assert chk.to_dict()["verified"] is expected, "to_dict 把三态折成了布尔"
        assert chk.to_dict()["verified"] is chk.verified


def test_quote_check_unknown_page_records_that_nothing_was_searched():
    """未决项（需要人裁决，本次刻意不改行为）：页码未知且不许全文兜底。

    此时 `tried == ("no_window",)` —— 一个窗口都没搜过，但 `verified` 是
    `False`（"校验失败"）而不是 `None`（"没能校验"）。按模块自己的三条判定原则
    （`quoteverify.py` 第 13-14 行："'没校验'和'校验失败'是两件不同的事"），
    这一支的取值是可疑的。

    不改的理由有三条，都写在这里以免以后被当成疏漏：
    1. `quoteverify.py` 在 `.noai-paths` 的 prover-bridge 禁改区，改判据需要
       2 名 reviewer 批准（FC-27）；
    2. `tests/test_quoteverify.py::test_unknown_page_without_fallback_is_false`
       已经把 `False` 编码成契约，不许放宽/改写既有断言来掩盖；
    3. 调用方并非无法区分 —— `reason="not_found_page_unknown"` 与
       `tried=("no_window",)` 已经把"没搜过"如实写在同一份返回值里。

    所以本用例钉住当前契约并把问题显式登记出来。
    """
    doc = _doc([P1, P2, P3])
    chk = check_quote(doc, P2, S.PageRange(None, None, ""), allow_fulltext_fallback=False)
    assert chk.verified is False
    assert chk.reason == "not_found_page_unknown"
    assert chk.tried == ("no_window",), "返回值必须自我说明'一个窗口都没搜'"


def test_quote_check_empty_page_window_is_reported_not_silently_passed():
    """负控：窗口收窄到不含目标页时，一个字母都不许"因为窗口小所以算过"。"""
    doc = _doc([P1, P2, P3])
    chk = check_quote(doc, P3, S.PageRange(1, 1, "p. 1"))  # P3 在第 3 页，±1 窗口只到第 2 页
    assert chk.verified is False and chk.reason == "not_found"
    assert chk.tried == ("declared:1-1", "widened:1-2")


# ============================================================ 8. agent_e.py / 零测试公开函数


def test_build_experiment_is_a_pure_function_and_keeps_schema_strictness(store):
    """INVENTORY 4.2：`agent_e.build_experiment` 零提及。它是纯函数（不碰 store）。

    负控：`numeric` + `proof` 的组合必须让 `Experiment.validate` 抛出来 ——
    推导规则与 schema 打架时最该炸，`build_experiment` 刻意不兜底。
    """
    derived = {
        "result": "supports",
        "evidence_kind": "cross_check",
        "negation_kind": "not_proved",
        "observations": {"n": 3},
        "counterexample": None,
        "notes": ["脚本自报 cross_check"],
    }
    row = build_experiment(
        "0000", "K(m)=[-m,m]", "K(m)", method="numeric", code_path="p.py", code_hash="h",
        derived=derived, exit_code=0, runtime_sec=0.5, params={"n": 3}, extra_notes=["额外说明"],
    )
    assert row.result == "supports" and row.evidence_kind == "cross_check"
    assert "额外说明" in row.notes and "脚本自报 cross_check" in row.notes
    assert store.rows("experiments") == [], "build_experiment 必须是纯函数"

    with pytest.raises(ValueError):
        build_experiment(
            "0001", "c", "k", method="numeric", code_path="p.py", code_hash="h",
            derived={**derived, "evidence_kind": "proof"}, exit_code=0, runtime_sec=0.1,
        )


def _write_probe(store: Store, rel: str, body: str) -> None:
    p = Path(store.root) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")


def test_run_script_experiment_is_a_faithful_alias(store):
    """INVENTORY 4.6：`AgentE.run_script_experiment` 是别名转发（零测试）。"""
    _write_probe(store, "probes/ok.py", "print('REPRO_RESULT: {\"result\": \"supports\"}')\n")
    e = AgentE(store)
    a = e.run_experiment("命题", "k-alias", "probes/ok.py")
    b = e.run_script_experiment("命题", "k-alias", "probes/ok.py")
    assert a["experiment_id"] != b["experiment_id"]
    for key in ("recorded", "result", "evidence_kind", "negation_kind", "exit_code"):
        assert a[key] == b[key], key


def test_agent_e_resolve_accepts_absolute_inside_and_refuses_outside(tmp_path):
    """INVENTORY 4.7⑩ 的核查结论：E 与 `verify_tools._resolve` 其实口径一致。

    可疑清单说"`verify_tools._resolve` 连工作区内的绝对路径也拒，于是 code_hash
    会拒绝一个 run_experiment 乐意执行的路径"。实测两边都接受工作区内的绝对路径
    （`Path(base) / <绝对路径>` 在 pathlib 里就是那个绝对路径），
    见本用例：E 接受、`verify.code_hash` 也接受、两者同样拒绝工作区外的路径。
    """
    st = Store(tmp_path / "ws")
    st.init()
    _write_probe(st, "probes/a.py", "print(1)\n")
    e = AgentE(st)
    inside = Path(st.root) / "probes" / "a.py"

    assert e._resolve("probes/a.py") == inside
    assert e._resolve(str(inside)) == inside, "工作区内的绝对路径应当被接受"

    reg = install_e_tools(st)
    assert reg.call("verify.code_hash", path="probes/a.py").ok
    assert reg.call("verify.code_hash", path=str(inside)).ok, "两边口径一致：都接受"

    outside = tmp_path / "outside.py"
    outside.write_text("print(2)\n", encoding="utf-8")
    with pytest.raises(ExperimentError):
        e._resolve(str(outside))
    assert reg.call("verify.code_hash", path=str(outside)).ok is False


def test_install_e_f_g_tools_are_all_wired(store):
    """INVENTORY 4.2：`install_e_tools` / `install_f_tools` / `install_g_tools` 零提及。

    三者的共同契约：装配出来的角色面必须非空且包含该角色赖以工作的那批工具
    （静默少一只手是本项目最忌讳的降级形态）。
    """
    e_names = set(install_e_tools(store).names())
    assert {"verify.run_experiment", "verify.check_formal", "verify.evidence_for"} <= e_names

    f_names = set(install_f_tools(store).names())
    assert {"attack.create_plan", "attack.step", "attack.status", "attack.list_plans"} <= f_names

    g_names = set(install_g_tools(store).names())
    assert any(n.startswith("doc.") for n in g_names), g_names


def test_agent_g_refresh_markdown_rewrites_from_the_store(tmp_path):
    """INVENTORY 4.2：`AgentG.refresh_markdown` 零提及（依赖是写稿之后才登记的）。"""
    st, g = _g_store(tmp_path)
    claim = g.compose_claim("谱落在区间内。", citations=["lit:0000"], evidence_kind="heuristic",
                            section="s", claim_id="claim-1")
    doc_id = g.build_document("note", "标题", claims=[claim])["doc_id"]
    # 依赖后登记（used_by 必须等 doc_id 存在）
    g.register_dependency(f"doc:{doc_id}#claim-1", "theorem", "某定理", source_lit_id="0000", status="closed")

    path = g.refresh_markdown(doc_id)
    assert path is not None and Path(path).exists()
    assert "某定理" in Path(path).read_text(encoding="utf-8"), "重渲染必须把依赖表画进去"

    # 负控：稿件不存在 ⇒ 显式失败，不许静默返回 None
    with pytest.raises(DocumentError):
        g.refresh_markdown("9999")


# ============================================================ 9. `__main__` 自检块（结构性缺口）


@pytest.mark.parametrize(
    "module",
    ["agentflow.agent_e", "agentflow.agent_f", "agentflow.agent_g", "agentflow.agent_h", "agentflow.pipeline"],
)
def test_module_selftest_exits_zero(module):
    """`python -m <module>` 的自检块必须以退出码 0 结束。

    ## 为什么要把它写进测试套件

    `DEVELOPMENT.md:2124` 把"`agent_g` 的自检块完全跑不起来"标成高严重度，理由
    正是"测试套件不会发现它 —— `_selftest` 在 `__main__` 里"。一个只在手工敲
    命令时才跑、而且没人敲的门，等于没有门：schema 新增一条硬约束之后，
    `agent_g._selftest` 的 fixture 静默过时了好几轮，退出码 1 却没有任何东西变红。

    这五个模块的自检合计约 5 秒，代价远低于"又一次静默过时"。
    """
    import os
    import subprocess
    import sys

    src = Path(__file__).resolve().parents[1] / "src"
    env = dict(os.environ)
    env["PYTHONPATH"] = str(src) + os.pathsep + env.get("PYTHONPATH", "")
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.run(
        [sys.executable, "-m", module],
        cwd=str(src), capture_output=True, text=True, encoding="utf-8", errors="replace",
        env=env, timeout=300,
    )
    assert proc.returncode == 0, (
        f"`python -m {module}` 自检失败（退出码 {proc.returncode}）：\n"
        f"--- stdout 末尾 ---\n{(proc.stdout or '')[-1500:]}\n"
        f"--- stderr 末尾 ---\n{(proc.stderr or '')[-1500:]}"
    )


# ============================================================ `parse_llm_json` 的两档宽容（§200）

def test_parse_llm_json_tolerates_a_trailing_extra_brace():
    """真机撞到的第一种坏 JSON：末尾多一个 `}`（M 与 G 的循环各十几次）。

    判据：多一个 `}` 能解析出同一个对象；而"结构上真的坏了"仍然拒绝
    （只容忍语法噪声，不容忍语义含糊）。
    """
    good = '{"concepts": [{"name": "group", "definition": "d"}]}'
    assert parse_llm_json(good) == parse_llm_json(good + "}")
    with pytest.raises(ExtractionError):
        parse_llm_json(good[:-2])          # 少一个 `}`：不补，直接拒绝


def test_parse_llm_json_tolerates_a_raw_control_character_in_a_string():
    """真机撞到的第二种：模型把定义里的换行直接写了进去（没转义）。

    `project run --extract` 实测：一本书的抽取整轮作废，报
    `Invalid control character at: line 80 column 168` —— 2 本里废 1 本。
    `strict=False` 是标准库自带的宽容档；它只放行字符串里的裸控制字符。
    """
    raw = '{"definition": "line1\nline2"}'.replace("\\n", "\n")   # 真的裸换行
    got = parse_llm_json(raw)
    assert got["definition"].strip().startswith("line1")
    assert "\n" in got["definition"] or "line1" in got["definition"]
    # 顶层不是对象时仍然拒绝（宽容不等于接受任何东西）
    with pytest.raises(ExtractionError):
        parse_llm_json("[1, 2, 3]")


def test_parse_llm_json_tolerates_an_unescaped_quote_inside_a_string():
    """真机撞到的第三种：长文本里的双引号没转义（`draft/39` §6.26 的 D36）。

    真机读数（2026-10-05 T2 第 6/7/8 趟）：M 把长命题 / 长 `claim` 内联进 `summon_many`，
    回复只有几百个 token 却连着三次 `Expecting ',' delimiter` ⇒ `bad_json_limit`，
    最短的一趟只走了 24 步就整趟作废。判据：这个双引号后面跟的不是 `,`/`:`/`}`/`]`
    ⇒ 它是字符串内部的引号，补上转义；而真的坏了（少一个 `}`）仍然拒绝。
    """
    raw = ('{"summon_many": {"targets": [{"role": "D", "action": "register_conjecture", '
           '"params": {"statement": "every edge lies in at least two "distinct" k-cycles"}}]}}')
    got = parse_llm_json(raw)
    target = got["summon_many"]["targets"][0]
    assert target["params"]["statement"] == \
        "every edge lies in at least two \"distinct\" k-cycles", got
    # 合法的转义一个都不许动
    legit = '{"a": "he said \\"hi\\"", "b": 1}'
    assert parse_llm_json(legit) == {"a": 'he said "hi"', "b": 1}
    # 结构真的坏了仍然拒绝（这条修补不是"什么都能救"）
    with pytest.raises(ExtractionError):
        parse_llm_json('{"a": "x" "b": 2')


def test_parse_llm_json_takes_the_first_complete_object_when_more_follows():
    """真机撞到的第四种：第一个完整对象后面还跟着东西（`draft/39` §6.28 的 D40）。

    真机读数（T2 第 10 趟 `p6l` 第 26 步）：报错是 `Extra data: line 1 column 2894`
    —— 模型把两个 JSON 对象连着写了。意图毫无歧义（第一个就是这一步），
    而"丢掉整步"的代价是整条链停摆：那一趟后 33 步全废、以 `bad_json_limit` 收工。
    """
    assert parse_llm_json('{"a": 1} {"b": 2}') == {"a": 1}
    assert parse_llm_json('{"a": 1} 后面还有一句散文') == {"a": 1}
    assert parse_llm_json('{"tool": {"name": "fs.read"}}  \n') == {"tool": {"name": "fs.read"}}
    # 第一个对象自己就坏了时不许拿它糊弄（仍然拒绝）
    with pytest.raises(ExtractionError):
        parse_llm_json('{"a": } {"b": 2}')

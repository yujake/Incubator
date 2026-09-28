"""`roles-2` 的回归判据：只读角色的两张例外表必须由机器判据相连。

## 缺陷（2026-09-26 全面体检 · 子代理 A 发现）

只读角色能写哪些表这件事有两个互相独立、可以各自漂移的落点：

- 工具级：`tools.base.READONLY_CALL_EXCEPTIONS`（H → 3 个 `review.*`）；
- 表级：`capabilities.READ_ONLY_WRITE_EXCEPTIONS`（H → `documents` + `review_findings`）。

`capabilities.py` 全文不出现 `READONLY_CALL_EXCEPTIONS`，两者的对应关系只写在
自然语言理由里 ⇒ 往工具级表加一个能写 `claims` 的工具不会触发任何断言：
工具层会放行、表级例外不认，没有任何东西会红。这正是 FC-27 第七类理由里
"测试全绿、上线即越权"的破口形态。

## 修法

在 `capabilities.assert_capabilities` 里加第 `[5c]` 条（导入期执行），三条判据：
① 两表的角色键集必须对齐；② 每个例外工具必须解析到动作，比不了的要显式登记；
③ 解析到的动作能写的表必须是表级例外的子集。外加一条反向守卫：`agent_h._H_WRITABLE_TOOLS`
必须是从表派生的（用 AST 判，不是字符串匹配）。

## 本文件的判据怎么"证明注入生效"

`assert_capabilities()` 是导入期跑的，进程内再调一次即可重跑全部断言。
所以负控的形态是：改掉表里的一条，再调一次 `assert_capabilities()`，必须抛。
每条负控都先断言"注入真的改到了那张表"（否则测的是空操作）。
"""
from __future__ import annotations

import ast
import pathlib
import re

import pytest

from agentflow import capabilities as C
from agentflow.tools import base as TB

CAP_PY = pathlib.Path(C.__file__)
AGENT_H = pathlib.Path(C.__file__).parent / "agent_h.py"


def test_the_assertion_passes_on_the_real_tree() -> None:
    """正控：现状下断言通过（否则整个包都 import 不了，那也是"注入生效"的反面）。"""
    C.assert_capabilities()


def test_adding_an_overreaching_tool_to_the_tool_level_table_is_caught() -> None:
    """负控（核心）：例外工具的逐工具写集若越出表级例外 ⇒ 断言必须红。

    注入走 `assert_capabilities` 的注入形参（见它的 docstring：第 `[5c]` 条是
    导入期判据，不注入就没法在进程内给它做负控）。
    这里把表级例外的 H 收窄成只剩 `review_findings` ⇒ `review.verify_fixes` /
    `review.review_document` 的写集里有 `documents` ⇒ 必须报越界。

    措辞断言为什么放宽（`R4-4` 的修法之后）：老版本只认 `[5c]` ③ 的那句
    "越权写表"，而那之所以成立，是因为 `[4]` 当时读的是模块全局
    `READ_ONLY_WRITE_EXCEPTIONS` —— 注入形参在第 `[4]` 条那里根本没生效
    （同一个值被检查两遍，第二遍才是活的，第一遍是死的全局表）。
    `R4-4` 把 `_rowe` 接到第 `[4]` 条之后，同一个注入会先在 `[4]` 报出来
    （"只读角色 H 的写集里出现了未登记的 ['documents']"）—— 那是更早、更准
    的同一结论，不是漏判。所以这里断"必须抛 + 必须点名 documents + 必须来自
    例外表这两道闸之一"，并把 `[5c]` ③ 单独钉在下面那条用例里
    （否则放宽措辞就真的没人守 ③ 了）。
    """
    narrow = {"H": frozenset({"review_findings"}),
              "C": C.READ_ONLY_WRITE_EXCEPTIONS["C"]}
    assert "documents" not in narrow["H"], "注入没生效"
    with pytest.raises(AssertionError) as ei:
        C.assert_capabilities(read_only_write_exceptions=narrow)
    msg = str(ei.value)
    assert "documents" in msg, msg
    assert ("越权写表" in msg) or ("未登记的" in msg), msg


def test_the_subset_check_itself_still_fires(monkeypatch) -> None:
    """负控（`R4-5` 补）：第 `[5c]` ③ 那条"写越界"必须仍然独立会红。

    为什么单独一条：上面那条注入现在会被第 `[4]` 条先接住（`R4-4` 之后
    `_rowe` 在第 `[4]` 条就是活的），于是 ③ 有可能在没人注意的时候烂掉。
    这里换成"角色级写集与表级例外一致、而逐工具写集多了一张表"的注入 ——
    它绕不过 ③：只需往 `review.verify_fixes` 的写集里加一张 `claims`，
    第 `[4]`/`[6]` 条都看不见（`_ws["H"]` 没变），只有 ③ 会红。
    """
    tws = dict(C.TOOL_WRITE_SETS)
    tws["review.verify_fixes"] = frozenset({"review_findings", "documents", "claims"})
    monkeypatch.setattr(C, "TOOL_WRITE_SETS", tws, raising=True)
    assert "claims" in C.TOOL_WRITE_SETS["review.verify_fixes"], "注入没生效"
    with pytest.raises(AssertionError) as ei:
        C.assert_capabilities()
    msg = str(ei.value)
    assert "claims" in msg, msg
    assert "越权写表" in msg, msg


def test_a_missing_per_tool_write_set_is_caught(monkeypatch) -> None:
    """负控 1b：`TOOL_WRITE_SETS` 漏登记一个例外工具 ⇒ 必须红（不许静默跳过）。

    这一条防的是"判据退化成空头支票"：例外表里有这个工具，而没人登记它会写什么。
    """
    injected = dict(C.TOOL_WRITE_SETS)
    injected.pop("review.report")
    monkeypatch.setattr(C, "TOOL_WRITE_SETS", injected, raising=True)
    assert "review.report" not in C.TOOL_WRITE_SETS, "注入没生效"
    with pytest.raises(AssertionError) as ei:
        C.assert_capabilities()
    assert "TOOL_WRITE_SETS" in str(ei.value), str(ei.value)


def test_a_stale_per_tool_write_set_is_caught(monkeypatch) -> None:
    """负控 1c：`TOOL_WRITE_SETS` 里留着已经不存在的工具 ⇒ 必须红（登记表自我清理）。"""
    injected = dict(C.TOOL_WRITE_SETS)
    injected["review.早就删掉的那个"] = frozenset()
    monkeypatch.setattr(C, "TOOL_WRITE_SETS", injected, raising=True)
    with pytest.raises(AssertionError) as ei:
        C.assert_capabilities()
    assert "早就删掉的那个" in str(ei.value), str(ei.value)


def test_the_subset_check_has_its_own_precedence() -> None:
    """判据的分工：[5c] 与 [4] 各自报各自的错（不互相掩盖）。

    把 `documents` 也登记进表级例外的角色级写集一关（[4]/[6]）不受影响，
    而 [5c] 这一跑必须通过 —— 它证明这条链真的在跑、而且不是"永远红"。
    """
    rowe = dict(C.READ_ONLY_WRITE_EXCEPTIONS)
    C.assert_capabilities(read_only_write_exceptions=rowe)


def test_a_tool_level_role_missing_from_the_table_level_is_caught(monkeypatch) -> None:
    """负控 2：工具级表里出现一个表级表没登记的角色 ⇒ 必须红（键集对齐那一条）。

     第一版把 `READ_ONLY_WRITE_EXCEPTIONS["C"]` 去掉当成"角色缺登记"的注入 ——
    它没红，因为 `READONLY_CALL_EXCEPTIONS` 今天只有 `H` 一个键（C 的表级例外
    是为"动作轴与写集"那一族断言登记的，不是为工具级例外）。判据要按事实造。
    真正的注入是往工具级表里加一个角色键（表级表里没有它）。
    """
    injected = dict(TB.READONLY_CALL_EXCEPTIONS)
    injected["C"] = (("review.随便一个", "注入用"),)
    monkeypatch.setattr(TB, "READONLY_CALL_EXCEPTIONS", injected, raising=True)
    with pytest.raises(AssertionError) as ei:
        C.assert_capabilities(read_only_write_exceptions={"H": C.READ_ONLY_WRITE_EXCEPTIONS["H"]})
    assert "C" in str(ei.value), str(ei.value)
    assert injected["C"], "注入没生效"


def test_an_unresolvable_tool_must_be_explicitly_registered(monkeypatch) -> None:
    """负控 3：比不了的例外工具必须显式登记 —— 没登记的 ⇒ 必须红（不许静默跳过）。

    这一条防的是"判据退化成真空"：如果解析不到就 `continue`，那么将来所有
    新加的工具都解析不到、判据一条都不比，而门照样绿。

    注意两条闸的先后：这个工具先会撞上"没有逐工具写集登记"（③），
    所以注入要同时给它一个写集，才轮得到 ② 那一格。
    这本身是好事（两道闸独立），但也说明判据的顺序必须写清 —— 见本文件末尾。
    """
    injected = dict(TB.READONLY_CALL_EXCEPTIONS)
    injected["H"] = (*injected["H"], ("review.这个工具不存在", "注入用"))
    monkeypatch.setattr(TB, "READONLY_CALL_EXCEPTIONS", injected, raising=True)
    tws = dict(C.TOOL_WRITE_SETS)
    tws["review.这个工具不存在"] = frozenset()
    monkeypatch.setattr(C, "TOOL_WRITE_SETS", tws, raising=True)
    assert any(n == "review.这个工具不存在" for n, _ in TB.READONLY_CALL_EXCEPTIONS["H"]), "注入没生效"
    with pytest.raises(AssertionError) as ei:
        C.assert_capabilities()
    assert "解析不到动作" in str(ei.value), str(ei.value)


def test_the_reverse_guard_catches_a_literal_second_copy(monkeypatch, tmp_path) -> None:
    """负控 4：`agent_h._H_WRITABLE_TOOLS` 若被写成字面量 ⇒ 反向守卫必须红。

    造法：把 `_h_writable_tools_is_derived` 读的那个文件换成一个临时副本，
    里面把派生式改回三个字面量。这是 `G-45`（同一个概念两个名字）的形态。
    """
    src = AGENT_H.read_text(encoding="utf-8")
    derived = (
        '_H_WRITABLE_TOOLS: tuple[str, ...] = tuple(\n'
        '    name for name, _why in READONLY_CALL_EXCEPTIONS["H"]\n'
        ")"
    )
    assert derived in src, "派生式不见了 —— 判据的落点变了，请更新本用例"
    literal = (
        '_H_WRITABLE_TOOLS: tuple[str, ...] = (\n'
        '    "review.review_document",\n'
        '    "review.verify_fixes",\n'
        '    "review.report",\n'
        ")"
    )
    fake = tmp_path / "agent_h.py"
    fake.write_text(src.replace(derived, literal), encoding="utf-8")

    real_read = pathlib.Path.read_text
    #  第一版在替身里调了 `fake.read_text(...)`（自己）⇒ `RecursionError`。
    # 必须把原始方法绑到一个局部变量上再调它。
    def fake_read(self, *a, **kw):
        if self.name == "agent_h.py":
            return real_read(fake, *a, **kw)
        return real_read(self, *a, **kw)

    monkeypatch.setattr(pathlib.Path, "read_text", fake_read, raising=True)
    try:
        assert C._h_writable_tools_is_derived() is False, "字面量形态没有被判成非派生"
        with pytest.raises(AssertionError) as ei:
            C.assert_capabilities()
        assert "_H_WRITABLE_TOOLS" in str(ei.value), str(ei.value)
    finally:
        monkeypatch.setattr(pathlib.Path, "read_text", real_read, raising=True)


def test_the_reverse_guard_accepts_the_derived_form() -> None:
    """正控：真树上那个派生形态必须被判成"派生"（否则反向守卫恒红）。"""
    assert C._h_writable_tools_is_derived() is True


# ============================================================ `R4-3` / `R4-4` / `R4-5`


def test_the_first_version_scanner_is_gone() -> None:
    """`R4-3`：零调用点的第一版残骸（`_tables_written_by_action`）必须被删掉。

    它是"只扫一层 handler 函数体里字面出现过的表名"的启发式，实测接近真空
    （`review.verify_fixes` 只算出 `{review_findings}`，漏掉 `documents`），
    而且当时已经没有任何调用点。留着它就是留第二份不再被调用的实现：
    下一个人改写集时可能改到这里，而它不影响任何断言。

    判据是 AST 级"这个符号不存在"，不是"源码里搜不到字符串"：
    后者会被新加的一行注释满足（`R3-7` 踩过的那个形态）。
    """
    src = CAP_PY.read_text(encoding="utf-8")
    tree = ast.parse(src)
    names = {n.name for n in ast.walk(tree)
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    assert "_tables_written_by_action" not in names, sorted(names)
    assert not hasattr(C, "_tables_written_by_action")


def test_the_source_scan_actually_computes_the_declared_write_sets() -> None:
    """正控（`R4-5`）：三个例外工具的登记写集必须等于从实现里算出来的。

    这条断言同时是"扫描器不是真空"的证据：`review.verify_fixes` 的写集
    含 `documents`，而 `documents` 是它的下层调用点 `_set_doc_status` 写的 ——
    第一版那个只扫一层的实现算不出它（这正是 `R4-3` 判它残骸的理由）。
    """
    real = {t: sorted(C._tool_write_set_from_source(t) or []) for t in C.TOOL_WRITE_SETS}
    assert real["review.verify_fixes"] == ["documents", "review_findings"], real
    assert real["review.review_document"] == ["documents", "review_findings"], real
    assert real["review.report"] == [], real
    for tool, tables in real.items():
        assert sorted(C.TOOL_WRITE_SETS[tool]) == tables, (tool, tables)


def test_emptying_a_registered_write_set_is_caught(monkeypatch) -> None:
    """负控（核心，`R4-5`）：把逐工具写集改成空集 ⇒ 断言必须红。

    这正是重审实测的形态：`TOOL_WRITE_SETS['review.review_document']` 改成
    `frozenset()`（真实写集是 `{documents, review_findings}`），
    改前 `assert_capabilities()` 仍然通过 —— 因为 ② 只保证"能解析到一个动作"，
    而 ③ 的子集检查对"少写"方向天然免疫。现在 ②′ 从实现里算写集再逐个比。
    """
    tws = dict(C.TOOL_WRITE_SETS)
    tws["review.review_document"] = frozenset()
    monkeypatch.setattr(C, "TOOL_WRITE_SETS", tws, raising=True)
    assert C.TOOL_WRITE_SETS["review.review_document"] == frozenset(), "注入没生效"
    from agentflow import capabilities as C2
    assert C2.TOOL_WRITE_SETS["review.review_document"] == frozenset(), "注入没生效"
    with pytest.raises(AssertionError) as ei:
        C.assert_capabilities()
    msg = str(ei.value)
    assert "review.review_document" in msg, msg
    assert "review_findings" in msg or "documents" in msg, msg


def test_the_write_sets_injection_parameter_is_live(monkeypatch) -> None:
    """负控（`R4-4`）：`assert_capabilities(write_sets=…)` 必须真的换掉判据读的那张表。

    改前 `_ws` 赋值之后从未被读（AST load=0），第 [1]/[4]/[6] 条读的是模块全局
    `WRITE_SETS` ⇒ 把注入的 `H` 写集改坏、断言照样通过。现在 `_ws` 在第 [4] 条
    就被读了，所以"给 H 加一张未登记的表"必须在导入期红。
    """
    bad = dict(C.WRITE_SETS)
    bad["H"] = frozenset({"review_findings", "documents", "claims"})
    assert bad["H"] != C.WRITE_SETS["H"], "注入没生效"
    with pytest.raises(AssertionError) as ei:
        C.assert_capabilities(write_sets=bad)
    msg = str(ei.value)
    assert "claims" in msg, msg
    # 键集不完整也必须被 [1] 抓住（同一张注入表的另一个方向）
    with pytest.raises(AssertionError):
        C.assert_capabilities(write_sets={"H": frozenset()})


def test_no_file_line_evidence_left_in_capabilities() -> None:
    """`R4-6`：`capabilities.py` 里不许再用"`文件:行号`"当证据（改用符号名）。

    行号易失：实测那批 `review_tools.py:274/296` 指向的是无关代码
    （274 是一条 finding 的字典字面量、296 是 `seen_ids[cid] = text`），
    而 `R4-6` 点名的正是"按注释去核对的人会看到无关代码"。
    判据分两半：注释行里 0 命中 `xxx.py:NNN`，以及所有 docstring 里 0 命中。
    """
    pat = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\.py:\d+")
    offenders: list[str] = []
    src = CAP_PY.read_text(encoding="utf-8")
    for lineno, line in enumerate(src.splitlines(), 1):
        if line.strip().startswith("#"):
            offenders += [f"注释 {lineno}:{m}" for m in pat.findall(line)]
    for node in ast.walk(ast.parse(src)):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        doc = ast.get_docstring(node, clean=False)
        if doc:
            offenders += [f"docstring {getattr(node, 'name', '<module>')}:{m}"
                          for m in pat.findall(doc)]
    assert offenders == [], f"capabilities.py 里又出现了行号证据：{offenders}"

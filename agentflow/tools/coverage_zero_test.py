#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""机械地算出 `src/agentflow/**` 里"零直接测试"的公开函数，并按风险等级分档。
`DEVELOPMENT.md` §1.4 逐字警告：`INVENTORY.md` / `tools.json` 普查的是 `D:\\Incubator\\test\\test1\\`（包名 `abflow`）而不是本包，"103 个公开函数零测试"不能直接搬 —— 本脚本在
agentflow 上重算，同一条命令 ⇒ 同一个数字。
口径是"名字在 tests/ 里出现过"，不是"真被调用"：遍历同 `scripts/lint_rules.py` 的 R007（同一个 `ast.walk` + `FunctionDef` / `AsyncFunctionDef` + 不以 `_` 开头）。三个假阴性：
间接调用（上界见 `--json` 的 `indirect_only`）、名字只出现在注释或字符串里、同名顶包（`register` 出现在 11 个模块，规模可核 `tested_by`）；唯一会误报的方向是间接调用。权威读数只有
`totals.public_functions` / `totals.zero_test`。
等级全在 AST 里、逐条可复跑：实现是 `_classify`（判据表 `_CRITERIA` 的 1a–4c）与 `_propagate_levels`（`--propagate` 的传递闭包），`_EXONERATED` 是逐条登记的豁免，`--json` 的
`level_why` 记下每个函数命中了哪一条。1 写路径（1a `@tool(side_effect=...)` ∈ `SIDE_EFFECTS_WRITE`，取自 `tools/__init__.py` 并在运行期断言一致；1b `*.tx(...)`；1c
`open(...,'w')` / `write_text` / `write_bytes`；1d `subprocess.*` / `os.system` / `urlopen`）；2 判据（2a 决策词缀
decide/check/validate/verify/gate/judge/admit/resolve/classify，按名称边界切分 —— `negated` 不因 gate 命中；2b `return {` 里的判定键 verdict/reason/checked）；3
只读（3a `side_effect="read"`；3b `store.rows` / `read_text` / `json.load`）；4 呈现（4a render/format/to_dict/to_md；4b f-string；4c 兜底）。
1e/2c 只在 `--propagate` 下开，默认关闭：第一版打开后等级 1 涨到 13、等级 2 涨到 55，多半是假报 —— `ToolRegistry.register_all` 因
`self.register(...)`、`Store.library_path` 因 `LocalBackend.resolve`、`Conductor.run_plan` / `table_tools.show` 因 `*.to_dict()` 被升级（同名顶包，同 R006
第一版 19 条噪音被忽略的教训）；那些增量数字已过期（`G-44`），重跑校准前不许引用。
刻意不计入：祖先链上有 `_` 开头类的私有嵌套方法（如 `AgentC.selftest` 体内的 `_FakeLLM.judge_gaps`），被排除者在 `--json` 的 `excluded` 里列出 —— 排除也要可见。退出码 `0` / `1` / `2` =
没有等级 ≤ `--level`（默认 2）的零测试函数 / 有（清单打到 stdout）/ 脚本自己没跑成（找不到 `src/`、`tests/`、AST 解析失败、`SIDE_EFFECTS_WRITE` 漂移）；同 R008 逐字：不然分不开"检查通过"与"根本没跑成"。
用法：`python tools/coverage_zero_test.py`（人读清单）、`--json`（逐模块 + 假阴性上界）、`--level 4`、`--quiet`、`--selftest`（对判据本身跑一正一反，证明它不会永远返回同一档）。
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------- 常量

#: 仓库根。脚本在 `<root>/tools/` 下。
ROOT = Path(__file__).resolve().parents[1]
SRC_REL = Path("src/agentflow")
TESTS_REL = Path("tests")

#: 写副作用等级。刻意在这里写死一份，但配一条运行期自检（`_selfcheck_side_effects`）：
#: 真正的单一来源是 `src/agentflow/tools/__init__.py` 的 `SIDE_EFFECTS_WRITE`，
#: 本脚本 import 它并断言与这里一致 —— 差异会以退出码 2 报出来，
#: 而不是静默地用错的判据分类（那正是 R008 说的失败形态）。
_EXPECT_SIDE_EFFECTS_WRITE = frozenset({"write_local"})

#: 决策词缀（等级 2 的判据 2a）。这是判据的一部分，写在这里便于复跑。
_DECISION_TOKENS = (
    "decide", "check", "validate", "verify", "gate", "judge", "admit", "allow",
    "refuse", "reject", "accept", "can_", "should_", "is_", "has_", "needs_",
    "must_", "resolve", "classify", "detect", "select", "pick", "choose",
)

#: 呈现词缀（等级 4 的判据 4a）。
_PRESENT_TOKENS = (
    "render", "format", "to_dict", "to_text", "to_md", "to_markdown", "summary",
    "describe", "catalog", "markdown", "explain", "display", "print", "dump",
)

#: 判定键（等级 2 的判据 2b）：函数 `return` 的字典字面量含这些键 ⇒ 它给出判定。
_VERDICT_KEYS = frozenset({
    "verdict", "reason", "checked", "ok", "approved", "allowed", "keep",
    "insufficient", "conflict", "should_write",
})

#: 只读原语名（等级 3 的判据 3b）。
_READ_CALLS = frozenset({
    "rows", "find", "read_text", "read_bytes", "load", "loads", "similarity",
    "ratio", "jaccard", "page_count",
})

#: 子进程 / 联网的调用名（等级 1 的判据 1d）。
_NET_PROC_CALLS = frozenset({
    "system", "Popen", "check_output", "check_call", "urlopen", "urlretrieve",
    "get", "post", "put", "request",
})

#: 子进程 / 联网的模块名（等级 1 的判据 1d）。只有"模块名也在调用集里"才算，
#: 避免把任意一个叫 `get` 的本地方法误判成联网。
_NET_PROC_MODULES = frozenset({"subprocess", "requests", "httpx", "urllib", "socket"})

#: 这些目录下的 `Call` 名字不足以构成"写"的证据（`get`/`post` 太常见）。
_LOOSE_CALLS = frozenset({"get", "post", "put", "request"})


# ---------------------------------------------------------------- 数据结构


@dataclass
class FuncInfo:
    """一个公开函数/方法的静态事实。"""

    module: str          # src 相对路径，例如 "src/agentflow/tools/table_tools.py"
    qualname: str        # 类方法带类名，例如 "ToolRegistry.for_role"
    bare: str            # 裸名，例如 "for_role"
    lineno: int
    is_method: bool
    tool_name: str | None = None      # @tool(...) 的第一个参数
    side_effect: str | None = None    # @tool(side_effect=...)
    has_docstring: bool = False
    level: int = 4
    level_why: list[str] = field(default_factory=list)
    tested: bool = False
    tested_by: list[str] = field(default_factory=list)
    calls: tuple[str, ...] = ()       # 函数体里出现过的被调用裸名（去重排序）
    indirect_only: bool = False       # 只被 src 内部调用、名字从未出现在测试里


# ---------------------------------------------------------------- AST 小工具


def _iter_py(base: Path) -> list[Path]:
    if not base.is_dir():
        return []
    return sorted(p for p in base.rglob("*.py") if "__pycache__" not in p.parts)


def _decorator_tool(node: ast.FunctionDef | ast.AsyncFunctionDef) -> tuple[str | None, str | None]:
    """从 `@tool(...)` 装饰器里取出 (工具名, side_effect)。

    只认 `@tool` / `@base.tool` 这一族；取不到返回 (None, None)。
    这是等级 1/3 判据的输入 —— 它读的是声明（`ToolSpec.side_effect` 的来源），
    而不是猜。
    """
    for dec in node.decorator_list:
        call = dec if isinstance(dec, ast.Call) else None
        if call is None:
            continue
        f = call.func
        fname = f.attr if isinstance(f, ast.Attribute) else (f.id if isinstance(f, ast.Name) else None)
        if fname != "tool":
            continue
        name = se = None
        if call.args and isinstance(call.args[0], ast.Constant) and isinstance(call.args[0].value, str):
            name = call.args[0].value
        for kw in call.keywords:
            if kw.arg == "side_effect" and isinstance(kw.value, ast.Constant):
                se = kw.value.value
        return name, se
    return None, None


def _called_names(node: ast.AST) -> set[str]:
    """函数体里出现过的"被调用名字"的集合（属性名与裸名都收）。

    不含递归进入嵌套函数体之外的部分 —— 但 `ast.walk` 会进嵌套函数，
    这对"传递"判据（1e/2c）是保守方向：把嵌套函数的调用也算进父函数，
    只会多报风险而不会少报。这里选择保守，并如实记在 `level_why` 里。
    """
    out: set[str] = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Call):
            f = n.func
            if isinstance(f, ast.Attribute):
                out.add(f.attr)
            elif isinstance(f, ast.Name):
                out.add(f.id)
    return out


#: 判据函数表 —— 刻意做成可替换的表，只为一件事：`--selftest` 的变异试验。
#:
#: 为什么不能直接 `global _open_write_modes; _open_write_modes = ...`：
#: Python 的全局名在调用点解析，但 `_classify` 体里写的是 `_open_write_modes(...)`，
#: 那是模块全局查找，`global` 赋值确实能改到它 —— 可是本模块的 `_classify`
#: 若在别处被 `from ... import` 走了局部引用就失效。更直接的问题是：一个
#: "改了却不生效"的变异试验会永远通过，那比不写更糟。
#: 做成显式的表之后，"注入错误实现"这件事本身是可验证的：表变了，
#: `_classify` 的行为必然跟着变（下面 `_crit` 每次调用读表）。
_CRITERIA: dict[str, object] = {}


def _crit(name: str):
    """取判据函数（供 `_classify` 调用；表可被 `--selftest` 替换）。"""
    return _CRITERIA[name]


def _open_write_modes_direct(node: ast.AST) -> list[str]:
    """函数体里 `open(...)` 的写模式。

    这里踩过一次真实的坑：第一版判据写成"模式字符串里含 w/a/x/+ 之一"，
    于是任何把变量或领域值当第二位置参数传给 `open` 的调用都会被误判
    （实测：`agent_d.submit_gaps` 里的 `open(..., "topical")` 曾被算成写模式）。
    修正后的判据是白名单：模式字符串必须恰好属于下面这个集合之一
    （`r+`/`rb+` 也写盘，所以收）。白名单不会漏掉合法写模式，
    也不会把领域参数吃进来。
    """
    allowed = {"w", "a", "x", "w+", "a+", "x+", "wb", "ab", "xb", "wt", "at", "xt",
               "r+", "rb+", "wb+", "ab+", "r+b", "w+b", "a+b"}
    out: list[str] = []
    for n in ast.walk(node):
        if not isinstance(n, ast.Call):
            continue
        f = n.func
        nm = f.attr if isinstance(f, ast.Attribute) else (f.id if isinstance(f, ast.Name) else None)
        if nm != "open":
            continue
        cands: list[str] = []
        if len(n.args) >= 2 and isinstance(n.args[1], ast.Constant) and isinstance(n.args[1].value, str):
            cands.append(n.args[1].value)
        for kw in n.keywords:
            if kw.arg == "mode" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                cands.append(kw.value.value)
        for c in cands:
            if c in allowed:
                out.append(c)
    return out


def _open_write_modes(node: ast.AST) -> list[str]:
    """`_open_write_modes_direct` 的可变异入口（见 `_CRITERIA`）。"""
    return _crit("open_write_modes")(node)


_CRITERIA["open_write_modes"] = _open_write_modes_direct


def _returned_dict_keys(node: ast.AST) -> set[str]:
    """函数体里 `return {...}` 的字典字面量键集合（含嵌套 return）。"""
    out: set[str] = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Return) and isinstance(n.value, ast.Dict):
            for k in n.value.keys:
                if isinstance(k, ast.Constant) and isinstance(k.value, str):
                    out.add(k.value)
    return out


def _has_joinedstr(node: ast.AST) -> bool:
    return any(isinstance(n, ast.JoinedStr) for n in ast.walk(node))


def _has_raise(node: ast.AST) -> bool:
    return any(isinstance(n, ast.Raise) for n in ast.walk(node))


def _token_hits(bare: str, tokens: tuple[str, ...]) -> list[str]:
    """词缀命中。按名称的词边界切分，不做朴素子串。

    为什么必须这样（实测误报）：`negated`（`interactions.py:151`）含子串 `gate`，
    朴素子串匹配会把它判成"决策函数" —— 而它只是一个否定词检测工具。
    改成按 `_` 与大小写边界切分后，`negated` 的片段是 `["negated"]`，
    不含 `gate`，于是不再命中；而 `gate_g7` 的片段是 `["gate","g7"]`，仍然命中。
    """
    parts = [p for p in re.split(r"[^0-9A-Za-z]+|(?<=[a-z0-9])(?=[A-Z])", bare) if p]
    low = [p.lower() for p in parts]
    hits = []
    for t in tokens:
        # 无尾下划线的词缀（gate/judge/…）：按片段等于或前缀匹配。
        if not t.endswith("_"):
            if any(p == t or p.startswith(t) for p in low):
                hits.append(t)
        else:
            # 带尾下划线的词缀（is_/has_/can_/should_/needs_/must_）是前缀词：
            # 它们的语义是"后面还跟着一个词"，所以判据是"这个词干作为某个非末尾
            # 片段出现"（`is_valid` 的 `is`、`check_is_valid` 的 `is` 都算；
            # 末尾的 `is`（`check_is`）不算 —— 那不是一个谓词前缀）。
            #
            # 这里曾经写成 `any(p.startswith(t) for p in low)`，而 `parts` 是按
            # `[^0-9A-Za-z]+` 切的、`_` 已被吃掉 ⇒ `p.startswith("is_")` 永远为假
            # ⇒ 六个词缀全部失效（实测 `_token_hits("is_valid") == []`）。
            # 外部审查第 1 条：这是"判据 2a 的一半从没生效"。修完由自检里的
            # `is_ready` 正例守着。
            stem = t[:-1]
            if any(p == stem for p in low[:-1]) or bare.lower().startswith(t):
                hits.append(t)
    return hits


# ---------------------------------------------------------------- 分类


def _classify(
    info: FuncInfo,
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    write_sides: frozenset[str],
) -> None:
    """判风险等级。把判据写进 `level_why`，这样报告可以逐条复跑。"""
    calls = _called_names(node)
    bare = info.bare
    info.calls = tuple(sorted(calls))
    why: list[str] = []

    # ---------------- 等级 1：写路径
    lvl1: list[str] = []
    if info.side_effect is not None and info.side_effect in write_sides:
        lvl1.append(f"1a:@tool(side_effect={info.side_effect!r}) 是写副作用 handler")
    if "tx" in calls:
        lvl1.append("1b:函数体调用 *.tx(...)（写事务）")
    wmodes = _open_write_modes(node)
    if wmodes:
        lvl1.append(f"1c:open(...) 写模式 {sorted(set(wmodes))}")
    if calls & {"write_text", "write_bytes"}:
        lvl1.append("1c:调用 write_text/write_bytes")
    proc = sorted(calls & _NET_PROC_CALLS)
    mods = sorted(calls & _NET_PROC_MODULES)
    strong_proc = [c for c in proc if c not in _LOOSE_CALLS]
    if mods and (strong_proc or (proc and mods)):
        lvl1.append(f"1d:子进程/联网调用 {strong_proc or proc}（模块 {mods}）")
    elif strong_proc and "system" in strong_proc:
        lvl1.append(f"1d:os.system 类调用 {strong_proc}")
    if lvl1:
        info.level = 1
        info.level_why = lvl1
        return

    # ---------------- 等级 2：判据/决策
    lvl2: list[str] = []
    hit_tokens = _token_hits(bare, _DECISION_TOKENS)
    if hit_tokens:
        lvl2.append(f"2a:裸名含决策词缀 {hit_tokens}")
    ret_keys = sorted(_returned_dict_keys(node) & _VERDICT_KEYS)
    if ret_keys:
        lvl2.append(f"2b:return 的字典含判定键 {ret_keys}")
    if info.tool_name and info.side_effect == "read" and _has_raise(node) and hit_tokens:
        # 标签叫 `2a+` 而不是 `2c`（外部审查第 3 条）：这一行不可能是 2a 之外的
        # 第一触发点（它要求 `hit_tokens` 非空，而那正是 2a 的条件），它只是给已经判 2
        # 的函数多凑一条理由。而 docstring 表里的 `2c` 指的是另一件事
        # （`--propagate` 下"直接调用了等级 2 的函数"），同名会让读 `level_why` 的人误判。
        lvl2.append("2a+:read 工具 + raise + 决策词缀")
    if lvl2:
        info.level = 2
        info.level_why = lvl2
        return

    # ---------------- 等级 3：只读读取
    lvl3: list[str] = []
    if info.tool_name and info.side_effect in (None, "read", "none"):
        lvl3.append(f"3a:@tool({info.tool_name!r}) 的 side_effect={info.side_effect or 'none'}")
    read_calls = sorted(calls & _READ_CALLS)
    if read_calls:
        lvl3.append(f"3b:调用只读原语 {read_calls}")
    if lvl3:
        info.level = 3
        info.level_why = lvl3
        return

    # ---------------- 等级 4：呈现/格式（兜底）
    lvl4: list[str] = []
    ptoks = _token_hits(bare, _PRESENT_TOKENS)
    if ptoks:
        lvl4.append(f"4a:裸名含呈现词缀 {ptoks}")
    if _has_joinedstr(node):
        lvl4.append("4b:函数体含 f-string 拼接")
    if not lvl4:
        lvl4.append("4c:兜底档（无任何等级 1/2/3 标记）")
    info.level = 4
    info.level_why = lvl4


# ---------------------------------------------------------------- src 侧扫描


def _parent_map(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    """子节点 → 父节点。`ast.walk` 不带父信息，而下面两条判据都需要它。"""
    parents: dict[ast.AST, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[child] = parent
    return parents


def _is_main_block(node: ast.AST | None) -> bool:
    """`node` 是不是 `if __name__ == "__main__":` 这条语句？"""
    if not isinstance(node, ast.If):
        return False
    test = node.test
    if isinstance(test, ast.Compare) and isinstance(test.left, ast.Name):
        return test.left.id == "__name__"
    return False


def _enclosing_scope(tree: ast.AST, node: ast.AST) -> tuple[str, str] | None:
    """`node` 是否定义在另一个函数体、私有类体或 `__main__` 自检块内？返回 (种类, 宿主限定名)。

    ## 为什么需要（三个实测的例子，不是假想）

    1. `agent_e.py:758` 的 `put_script` 定义在 `main()` 体内（自检用的局部辅助）；2. `agent_c.py:3112` 的 `_FakeLLM` 定义在 `AgentC.selftest` 的函数体里，
    它的方法 `judge_gaps` 不以 `_` 开头；3. `agent_c.py:2913` 的 `build_dataset` 定义在模块级的`if __name__ == "__main__":`（第 2873 行）自检块里 ——
    它不在任何函数里，所以前两条判据都抓不到它。这个例子是"我以为已经排除干净、实际漏了 1 个"的实测证据：漏掉它会让等级 1 的清单里出现一个给自检写 fixture 的函数，而它的"测试"就是它自己所在的那个自检块。按 R007
    的遍历口径这三者都会被算成"公开函数"，但它们不是生产公开面。给它们补测试是荒谬的，而且会稀释真正需要的测试。排除必须可见：被排除者逐条进 `--json` 的 `excluded`，汇总行给出条数。静默排除正是本项目最忌讳的失败形态。只排除不是
    `@tool` 的：`tools/graph_tools.py` 的 `register.graph_build`等 8 个 handler 也是嵌套定义，但它们是货真价实的工具面（带 `side_effect` 声明），
    一刀切会把这些工具从清单里静默抹掉。这条例外在 `collect_src` 里落实。
    """
    parents = _parent_map(tree)
    cur = parents.get(node)
    while cur is not None:
        if isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return ("function", cur.name)
        if isinstance(cur, ast.ClassDef):
            if cur.name.startswith("_"):
                return ("private_class", cur.name)
            # 公开类里的方法：不排除（那才是真正的公开面）。
            return None
        if _is_main_block(cur):
            return ("main_block", "__main__")
        if isinstance(cur, ast.Module):
            return None
        cur = parents.get(cur)
    return None


def collect_src(root: Path, write_sides: frozenset[str]) -> tuple[list[FuncInfo], list[dict]]:
    """扫描 src，返回 (全部公开函数/方法的静态信息, 被排除者清单)。"""
    out: list[FuncInfo] = []
    excluded: list[dict] = []
    for p in _iter_py(root / SRC_REL):
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except SyntaxError as e:
            raise CoverageError(f"解析失败：{p}：{e}") from e
        rel = str(p.relative_to(root)).replace("\\", "/")
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if node.name.startswith("_"):
                continue
            priv = _enclosing_scope(tree, node)
            tool_name, se = _decorator_tool(node)
            if priv is not None and tool_name is None:
                # 只排除不是工具的嵌套函数。为什么这条狭窄的例外必须有：
                # `tools/graph_tools.py:836` 的 `register.graph_build` 等 4 个
                # 与 `tools/trace_tools.py` 的 `register.trace_*` 4 个都是
                # 在 register() 体内定义的 @tool handler —— 它们是货真价实的
                # 工具面（`side_effect` 声明也在），只是恰好写在函数体里。
                # 一刀切把嵌套函数全排除，会把这些工具从清单里静默抹掉 ——
                # 而"静默"正是本项目最忌讳的失败形态。带了 `@tool` 就按公开面算。
                kind, host = priv
                why = {
                    "function": f"定义在函数 {host}() 体内（自检/局部辅助/闭包），不是生产公开面",
                    "private_class": f"定义在私有类 {host} 内（测试替身/内部实现），不是生产公开面",
                    "main_block": f"定义在 {host} 自检块（`if __name__ == \"__main__\"`）内，"
                                  "不是生产公开面（它的测试就是它自己所在的那个自检块）",
                }[kind]
                excluded.append({
                    "module": rel,
                    "qualname": f"{host}.{node.name}",
                    "lineno": node.lineno,
                    "kind": kind,
                    "why": why,
                })
                continue
            qual = node.name
            is_method = False
            for parent in ast.walk(tree):
                if isinstance(parent, ast.ClassDef) and node in parent.body:
                    qual = f"{parent.name}.{node.name}"
                    is_method = True
                    break
            tool_name, se = _decorator_tool(node)
            info = FuncInfo(
                module=rel,
                qualname=qual,
                bare=node.name,
                lineno=node.lineno,
                is_method=is_method,
                tool_name=tool_name,
                side_effect=se,
                has_docstring=bool(ast.get_docstring(node)),
            )
            _classify(info, node, write_sides)
            out.append(info)
    return out, excluded


class CoverageError(RuntimeError):
    """本脚本自身的失败（⇒ 退出码 2）。"""


# ---------------------------------------------------------------- 传递判据（等级 1e / 2c）


def _propagate_levels(funcs: list[FuncInfo]) -> None:
    """把等级 1/2 沿"函数体直接呼调"的边传递，取最大值（1 比 2 高）。

    为什么需要：`AgentD.write_report` 自己只调 `write_text`（已判 1），
    但一个只调"别的写路径函数"的编排函数同样是写路径 —— 只按自身 AST 判会漏掉它。

    传递只用于升级（把低估的档升上去），不用于降级；
    且每次升级都在 `level_why` 里留下 `1e:`/`2c:` 一行，说明是哪条边导致的。
    """
    by_bare: dict[str, list[FuncInfo]] = {}
    for f in funcs:
        by_bare.setdefault(f.bare, []).append(f)

    # 不动点迭代：一条边可能把 A 升到 2，A 再把它自己的调用者升到 2。最多迭代到稳定。
    for _ in range(6):
        changed = False
        for f in funcs:
            if f.level == 1:
                # 只有"已经是 1"才是终态。这里曾经写 `f.level <= 2`（外部审查第 4 条）：
                # 那会把"等级 2 的函数调用了等级 1 的函数"这条边整条砍掉，
                # 而按 1e 的定义（"直接调用了一个等级 1 的函数"）它应当升到 1。
                # 方向上也必须这么改：等级 1 是"写路径"、是最该被盯的一档，
                # 漏升是危险方向的错（把一个会写盘的函数留在"判据/决策"档）。
                continue  # 已经是 1，不需要升级
            hits1: set[str] = set()
            hits2: set[str] = set()
            for c in f.calls:
                for callee in by_bare.get(c, ()):
                    if callee is f:
                        continue
                    if callee.level == 1:
                        hits1.add(callee.qualname)
                    elif callee.level == 2:
                        hits2.add(callee.qualname)
            # 只有在等级真的变了的时候才写 `level_why` 与 `changed`。
            #
            # 为什么必须有这个前置条件（外部审查第二轮第 1 条，我实测复核过）：
            # 把上面的 `f.level <= 2` 改成 `== 1` 之后，等级 2 的函数每次迭代都会被
            # 重新处理，而 `f.level = 2` 对它们是个 no-op ⇒ 却仍然 prepend 一行
            # `2c:` 并把 `changed` 置真 ⇒ 实测 `level_why` 里堆了 6 条一模一样的
            # `2c:直接调用判据函数 ['G']`，而且不动点循环因为 `changed` 永远为真而
            # 跑满 6 轮、永不提前 `break`。
            # 这不会改分档结果（level 值不变），但会污染 `--json` 的 `level_why`，
            # 并让"迭代到稳定"这句话变成假话。
            if hits1 and f.level != 1:
                f.level = 1
                f.level_why = [f"1e:直接调用写路径函数 {sorted(hits1)[:4]}"] + f.level_why
                changed = True
            elif hits2 and f.level != 2:
                f.level = 2
                f.level_why = [f"2c:直接调用判据函数 {sorted(hits2)[:4]}"] + f.level_why
                changed = True
        if not changed:
            break


# ---------------------------------------------------------------- 已核实覆盖（豁免名单）


#: 已人工核实有直接测试、但本脚本的"按名出现"判据看不到的函数（逐条豁免，且豁免必须可核）。 为什么需要这张表而不是放宽判据：判据是"名字出现在 tests/ 里"，它有一类结构性假阴性 —— 测试间接调用
#: 某个函数时那个名字可能从未出现（实测：`interactions.adjudicate_contradiction` 在
#: `tests/test_interactions.py` 里有 9 条测试直接调它，覆盖 side_removed / side_superseded /
#: no_longer_conflicting / unresolved / persistent / new_contradiction 六个分支 ⇒ 把它列为"零测试"
#: 是把假阴性当成了缺口）。放宽判据（例如"任何以 `test_` 开头的名字就算"）会让判据失去分辨力，所以选
#: 显式豁免：表里每条写 `(模块, 限定名) -> (覆盖它的测试函数名, 一句理由)`，而 `_selfcheck_exonerations()`
#: 会断言那些测试函数名真的存在 —— 改了测试名或删了那条测试 ⇒ 退出码 2 报出来，而不是静默抹掉缺口。
#: 表只放已核实有直接测试的（必须写得出至少一个直接调用它的测试函数名），不许放"我觉得它不重要"的。
_EXONERATED: dict[tuple[str, str], tuple[tuple[str, ...], str]] = {
    ("src/agentflow/interactions.py", "adjudicate_contradiction"): (
        (
            "test_adjudicate_resolved_when_a_side_is_gone",
            "test_adjudicate_resolved_when_both_sides_gone",
            "test_adjudicate_resolved_when_side_superseded_by_dedup",
            "test_adjudicate_resolved_when_text_no_longer_conflicts",
            "test_adjudicate_unresolved_within_budget",
            "test_adjudicate_persistent_when_budget_exhausted",
            "test_adjudicate_new_contradiction_takes_priority_over_unresolved",
        ),
        "tests/test_interactions.py 里 7 条测试**直接**调用 I.adjudicate_contradiction(...)，"
        "覆盖裁决五选一的全部分支与 rounds/max_rounds 的三态"
        "（`FINAL-R7-06` 更正：本条今天已是二次登记 —— G-34 补的 alias_direct 判据"
        "（`_QUALIFIED_TMPL`）已经能自己命中它；保留它是为了留下『谁在直接调用它』这份证据，"
        "而不是因为判据看不见它。`_selfcheck_exonerations` 现在会逐条核引用到的测试"
        "函数体里是否真的出现目标名，所以这段理由必须与盘上的测试逐字对得上）",
    ),
}


def _selfcheck_exonerations(root: Path) -> None:
    """豁免名单里的每个测试函数名必须真的存在于 tests/ 里，且真的调用目标。否则退出码 2。

    为什么这条自检是这张表能被信的前提：豁免的语义是"我核实过它被直接测试了"。
    若被引用的测试名不存在（改名 / 被删），那份核实已经过期，
    此时继续豁免等于把缺口静默抹掉 —— 所以它必须是硬失败，不是 warning。

    `FINAL-R7-07`：改前这里只核"测试函数名存在"。副本实测：伪造一条豁免
    （引用 5 个真实存在、但从不调用目标的测试名）可以通过自检，并把一个零测试的
    等级 1 写路径从门里摘掉（门由红转绿）。现在再加一层：
    被引用的每个测试函数，其函数体里必须出现目标函数的名字（按 `_name_pattern`
    的同一口径 —— 它与"算不算被测试"用的是同一处实现，不另立一套）。
    """
    blob = _test_text(root)
    defined = set(re.findall(r"\bdef (test_[0-9A-Za-z_]+)\s*\(", blob))
    bodies = _test_bodies(root)
    bad: list[str] = []
    for (mod, qual), (tests, _why) in sorted(_EXONERATED.items()):
        if not (root / mod).exists():
            bad.append(f"{mod} 不存在（豁免条目已失效）")
        target_name = qual.rsplit(".", 1)[-1]
        # 体检查用允许属性访问的形态（`I.adjudicate_contradiction(...)` 也算调用）：
        # `_name_pattern` 的左边界刻意排除了前置的 `.`（那是为全仓文本扫描服务的，
        # 那边另有 `_QUALIFIED_TMPL` 管属性访问），照搬过来会把"通过模块别名调用"
        # 整类测试误判成"没调用目标" —— 实测：本项目 7 条 test_adjudicate_* 里有 3 条
        # 是 `I.adjudicate_contradiction(...)` 这种写法。
        pattern = re.compile(r"(?<![\w])" + re.escape(target_name) + r"(?![0-9A-Za-z])")
        for t in tests:
            if t not in defined:
                bad.append(f"{mod}::{qual} 的豁免引用了不存在的测试 {t}()")
                continue
            body = bodies.get(t, "")
            if not body:
                bad.append(f"{mod}::{qual} 的豁免引用了 {t}()，但读不到它的函数体（无法核实）")
            elif not pattern.search(body):
                bad.append(
                    f"{mod}::{qual} 的豁免引用了 {t}()，但那个测试的函数体里没有调用 "
                    f"{target_name} —— 引用一个真实存在却与目标无关的测试名，"
                    "等于用一句话把缺口摘掉（`FINAL-R7-07`）"
                )
    if bad:
        raise CoverageError(
            "豁免名单过期或不实（这正是它必须硬失败的理由：过期豁免 = 静默抹掉缺口）：\n  - "
            + "\n  - ".join(bad)
        )


def _test_bodies(root: Path) -> dict[str, str]:
    """`{测试函数名: 函数体源码}`（AST 取 `def test_*` 的 body 段）。

    与 `_test_text`/`_name_pattern` 同源：判"有没有引用目标"用的是同一处口径，
    不另写一套（否则"算被测试"与"算豁免合格"会漂移）。
    """
    out: dict[str, str] = {}
    for p in _iter_py(root / TESTS_REL):
        if not _readable(p):
            continue
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
                out[node.name] = ast.unparse(node)
    return out


def _exoneration_for(info: FuncInfo) -> tuple[tuple[str, ...], str] | None:
    return _EXONERATED.get((info.module, info.qualname))


# ---------------------------------------------------------------- tests 侧扫描


def _test_text(root: Path) -> str:
    """把 tests/ 下所有 py 文件读成一大段文本。"""
    return "\n".join(p.read_text(encoding="utf-8") for p in _iter_py(root / TESTS_REL) if _readable(p))


def _readable(p: Path) -> bool:
    try:
        p.read_text(encoding="utf-8")
        return True
    except (OSError, UnicodeDecodeError):
        return False


def _name_pattern(needle: str) -> re.Pattern[str]:
    """`needle` 作为标识符位置出现的正则。这里改过一次，改的原因是一个实测的假阴性（不是推测）：第一版判据是 `(?<![\\w.])needle(?![\\w])` —— 两侧都必须是"非词字符"。它把
    `parse` 与 `parse_work` 正确分开了，但同时把项目的测试命名约定整类漏掉了：本项目的测试名是 `test_<函数名>_rejects_...`，而
    `adjudicate_contradiction` 后面紧跟的正是 `_`（一个词字符）⇒`tests/test_interactions.py` 里明明直接调用了
    `adjudicate_contradiction`六次，第一版却把它报成"零测试"。实测规模：修正前后等级 2 的零测试函数从 31 个降到 19 个 ——也就是第一版把 12 个有直接测试的函数误报成了零测试（39%
    的假报率）。这正是本任务要求"实现者反驳简报"的那类问题：判据本身有假报。修正后的规则（两侧不对称，且不对称是刻意的）：左边界：`(?<![\\w.]*[\\w]?)` 用 `(?<![\\w.])` ——
    `needle` 不能是某个更长标识符的尾部。所以 `needle="parse_work"` 不匹配 `_parse_work`（前面是 `_`，是词字符），`needle="parse"` 也不匹配
    `subparse`。- 右边界：`(?![\\w]*[\\w]?)` 即 `(?![0-9A-Za-z])` —— 允许后面是 `_`。于是
    `def test_adjudicate_contradiction_rejects_x` 里的名字能命中。如实写清右边界不管什么（外部审查第 2 条，我实测复核过）：因为`_` 不在
    `[0-9A-Za-z]` 里，`needle="parse"` 会命中 `x = parse_work()`。本文件早先的注释曾逐字说"`needle="parse"` 不匹配 `parse_work`" ——
    那句是假的（实测 `_name_pattern("parse").search("x = parse_work()")` 命中）。同一个性质在 `_TEST_NAME_TMPL`（`test_parse` 命中
    `test_parse_work`）与`_QUALIFIED_TMPL`（`I.parse_work(` 让 `parse` 命中）上同样成立。这是刻意的欠报方向（"算它有测试"），不是 bug；但不许再写成相反的性质。
    但这条正则认不出"别名限定调用"（`G-34`，实测）：左边界排除 `.` 是刻意的（`parse` 不许匹配 `parse_work` 的尾巴），代价是`I.adjudicate_contradiction(` /
    `G.gateway_main(` / `FG.evidence_of(` 这类限定的成员调用一个都拿不到。本文件早先的注释曾逐字说"`I.adjudicate_contradiction(` 都能命中" —— 那句是假的，
    实测命中 0 次。它造成的不是"清单短一点"，而是发布门上的两条假红：`modelgw.gateway_main`与 `formalgw.evidence_of` 明明有直接调用，却被报成"零测试"并让
    `coverage` 判 `fail`。修法是补一个 needle 形态（`_QUALIFIED_TMPL`，把证据单独记成 `via:alias_direct`），而不是放宽这里的左边界 ——
    放宽会牵连既有判据（`parse` vs `parse_work` 的区分）。代价（如实写清）：`needle="register"` 会命中 `register_graph_tools(` —— 那是另一个函数。
    所以本判据仍然偏向"算它有测试"（欠报而非过报）。这个方向的偏差是刻意的：本脚本的产出是"待补测试清单"，过报会让人去做无用功，欠报只会让清单更短。两侧偏差的规模都由 `--json` 的 `indirect_only` 与
    `tested_by` 字段给出，可人工核对。
    """
    return re.compile(rf"(?<![\w.]){re.escape(needle)}(?![0-9A-Za-z])")


def _name_occurrences(blob: str, needle: str) -> int:
    """`needle` 作为标识符位置在 blob 里出现的次数（规则见 `_name_pattern`）。"""
    return len(_name_pattern(needle).findall(blob))


#: 本项目的测试命名约定：`def test_<被测函数名>_<预期>` 或 `def test_<被测函数名>(`。
#: 为什么单独一条判据：`_name_pattern` 的左侧要求"非词字符"，于是 `def test_validate_claim_rejects_x`
#: 里紧挨在 `validate_claim` 左边的 `_` 让它匹配不上 —— 这不是调正则能顺手解决的：`_` 既是标识符字符
#: 又是词分隔符，文本上无法区分"作为后缀出现的 `validate_claim`"与"作为前缀出现的 `parse`（在 `parse_work` 里）"。
#: 所以做成按项目约定命名的显式判据：只有 `needle` 前面正好是 `test_` 且后面不是字母数字时才算命中 ——
#: 不会让 `needle="parse"` 命中 `parse_work`、不会让 `process` 命中 `reprocess_once`、会让
#: `validate_claim` 命中 `def test_validate_claim_rejects_...`。它仍可能被"某个测试恰好叫这个名字、但测的
#: 是别的东西"骗到，所以命中它的函数在 `--json` 里标成 `via: "test_name"`（与 `via: "direct"` 分开）：把 两者混成一个布尔值，就等于把"有直接调用"与"有个名字像的测试"当成同一件事。
_TEST_NAME_TMPL = r"\btest_{n}(?![0-9A-Za-z])"


def _test_name_occurrences(blob: str, needle: str) -> int:
    """`needle` 是否出现在项目约定的测试名 `test_<needle>_...` 里。"""
    return len(re.findall(_TEST_NAME_TMPL.format(n=re.escape(needle)), blob))


#: 限定名形态：`别名.函数(`、`模块.函数(`、`对象.方法(`。
#:
#: 为什么必须单独一条判据（`G-34`，实测）：`_name_pattern` 的左边界把 `.` 排除，
#: 于是"别名限定调用"整类拿不到 `via:direct`。实测两处直接调用被报成"零测试"：
#: `tests/test_modelgw.py` 的 `assert G.gateway_main([]) == 0` 与
#: `tests/test_formalgw.py` 的 `ev = FG.evidence_of({...})` —— 而这两个假缺口
#: 正好卡在发布门 `coverage` 的等级 2 上，构成了那条唯一的 `fail`。
#:
#: 修法不是改左边界（会牵连 `parse` vs `parse_work` 的既有区分），
#: 而是补一个 needle 形态并把它单独记成 `via:alias_direct`：
#: 本判据不做别名解析，所以"前缀是谁"要靠人核 —— 这也正是它单独记一档的理由。
_QUALIFIED_TMPL = r"(?:[A-Za-z_]\w*\.)+{n}(?![0-9A-Za-z])"


def _qualified_occurrences(blob: str, needle: str) -> int:
    """`needle` 以"被点号限定的成员"形态出现的次数（如 `I.foo(` / `mod.sub.foo(`）。"""
    return len(re.findall(_QUALIFIED_TMPL.format(n=re.escape(needle)), blob))


def mark_tested(funcs: list[FuncInfo], root: Path) -> None:
    """标出每个函数是否"有测试"。判据由三条可分辨的分量组成，三条都记进 `tested_by`（带 `via:` 前缀）：`via:direct` —— 裸名/限定名作为独立标识符出现在 tests/ 里（`adjudicate_contradiction(` 这种）。注意
    `_name_pattern` 的左边界排除 `.`，所以"别名限定调用"不在这一档；- `via:alias_direct` —— 以被点号限定的成员形态出现（`I.foo(`、`mod.foo(`）；- `via:test_name` —— 出现在项目约定的测试名
    `test_<名字>_...` 里；- `via:tool_name` —— 只在测试里出现过一次这个 `@tool` 的点号名（`conductor.stop` / `fs.move`）。`L-13`（`draft/52` F7）
    把它从前一档（`via:direct tool:…`）拆出来单独记：它是四个分量里最弱的一个 ——"在测试里写一次工具名"与"真的构造上下文并调用它"是两件事，而等级 1（写路径，最高风险档）的零测试数全靠它从 7 变成 0（`draft/43-D` §2.2）。
    拆出来只加读数、不改判据强度（`info.tested` 照旧为真）：收紧那一半必须等 `host.py:86` 的 `host-wiring` 落地之后再做（`draft/56` §4.3 的硬序）。为什么分量必须分开记：
    它们的证据强度不同。`direct` 是"测试里出现了这个独立标识符"；`alias_direct` 是"有人用某个前缀调用了这个名字"（前缀是谁要靠人核，本判据不做别名解析）；`test_name` 是"有个测试叫这个名字"（名义覆盖，
    可能测的是别的东西）；`tool_name` 是"测试里出现过这个工具名串"（最弱）。L-13 收紧（`draft/52` F7 + J-45）：`tool_name` 单独一条不构成"有测试"：
    收紧前后唯一的差别就是这一句：`info.tested` 要求至少有一条`direct` / `alias_direct` / `test_name` / `exonerated` 的证据；只在测试里写过一次点号工具名（`conductor.stop`）不算。
    为什么（`draft/43-D` §2.2 逐字）：等级 1（写路径，最高风险档）的零测试数，在"把工具名串算作有测试"的口径下是 0（发布门看到的绿灯），在不算它的口径下是 7 —— 也就是说最高风险档的绿灯是被一个字符串满足的。J-45 的两条硬边界：①
    历史那批（不可消除的）走登记基线；② 负控必须证明"新造一个真无测试的写路径 handler 仍会被判"（红），否则收紧退化成一句口号。三种证据分量仍原样记进 `tested_by`（读数不许丢）：收紧改的是判据强度，不是"看不见工具名串"。
    """
    blob = _test_text(root)
    for info in funcs:
        hits: list[str] = []
        for needle in dict.fromkeys([info.qualname, info.bare]):
            n = _name_occurrences(blob, needle)
            if n:
                hits.append(f"via:direct {needle}×{n}")
        for needle in dict.fromkeys([info.qualname, info.bare]):
            n = _qualified_occurrences(blob, needle)
            if n:
                hits.append(f"via:alias_direct {needle}×{n}")
        if info.tool_name:
            n = _name_occurrences(blob, info.tool_name)
            if n:
                hits.append(f"via:tool_name tool:{info.tool_name}×{n}")
        for needle in dict.fromkeys([info.bare]):
            n = _test_name_occurrences(blob, needle)
            if n:
                hits.append(f"via:test_name test_{needle}×{n}")
        exo = _exoneration_for(info)
        if exo is not None:
            hits.append(f"via:exonerated {len(exo[0])} 条测试：{'、'.join(exo[0])}")
        info.tested_by = hits
        # L-13 收紧：只靠 `via:tool_name` 的那一条不算有测试（见 docstring）。
        info.tested = any(not h.startswith("via:tool_name") for h in hits)


def production_caller_reading(funcs: list[FuncInfo], zero: list[FuncInfo],
                              level: int) -> dict[str, Any]:
    """F7 / L-13 的读数（`draft/52` F7；收紧已落地 ⇒ 见 `mark_tested` 的 docstring）。
    ## 为什么必须有这个读数（`draft/43-D` §2.2 逐字）
    "发布门看到的读数是 0，而忽略'工具名串'那一条判据后是 7（等级 1，写路径，最高风险档）" —— 也就是说最高风险档上那条绿灯，是被一个字符串满足的。
    ## 三个口径并列（不许只选一个）
    1. `tightened_zero_test` —— 本工具现在的口径（`via:tool_name` 单独一条不算）；
    2. `loose_zero_test` —— 收紧之前那个更宽的口径（把工具名串也算"有测试"）；
    `loose_gate` 就是发布门历史上看到的那个 0；
    3. `registered_other_gauges` —— 别处登记过的两个更宽读数
    （`41-G` 的台账口径 82、未复算的 113 / 153）。它们是外部读数、本次未复算。
    `tool_name_only`（只靠工具名串"过关"的函数）与其按等级分布仍然报：它是 ①② 两栏之差，也是"谁被这次收紧打回来"的逐条清单。
    """
    tool_only = [f for f in funcs
                 if f.tested_by
                 and all(h.startswith("via:tool_name") for h in f.tested_by)]
    loose_zero = [f for f in funcs if not f.tested and f not in tool_only]
    return {
        "tightened_zero_test": len(zero),
        "tightened_by_level_zero": {str(lv): len([f for f in zero if f.level == lv])
                                    for lv in (1, 2, 3, 4)},
        "tightened_gate": len([f for f in zero if f.level <= level]),
        "loose_zero_test": len(loose_zero),
        "loose_by_level_zero": {str(lv): len([f for f in loose_zero if f.level == lv])
                                for lv in (1, 2, 3, 4)},
        "loose_gate": len([f for f in loose_zero if f.level <= level]),
        "tool_name_only": len(tool_only),
        "tool_name_only_by_level": {str(lv): len([f for f in tool_only if f.level == lv])
                                    for lv in (1, 2, 3, 4)},
        "tool_name_only_names": [f.qualname for f in tool_only][:32],
        "registered_other_gauges": {
            "41-G 台账口径": {"value": 82, "source": "draft/43-G（登记数，本次未复算）"},
            "未复算甲": {"value": 113, "source": "draft/52 F7 登记（本次未复算）"},
            "未复算乙": {"value": 153, "source": "draft/52 F7 登记（本次未复算）"},
        },
        # 登记的"零生产调用者但不许删"（不是豁免表：有署名、依据、与守它的测试文件）
        "registered_no_production_caller": registered_no_production_caller_reading(funcs),
        # F7 的口径自明（主控 2026-10-06）：两档读的不是同一件事，混读会得出相反结论。
        "gauge": {
            "function_level": ("判据用的这一档：公开函数的**裸名/限定名**作为独立标识符"
                               "出现在 tests/ 里 ⇒ 问的是「这个函数有没有被测试碰到」"),
            "string_level": ("`via:tool_name`：只在测试里出现过该工具的**点号名串**"
                             "（`conductor.stop`）⇒ 它数的是**字符串**，不是一次调用；"
                             "`tool_name_only*` 报的就是这一筐，**不构成**「有生产调用者」"),
            "production_caller": ("生产调用者 = 该工具的 **handler 函数**被生产路径调用"
                                  "（**函数级**）。生产路径常常**直调工具体**而不写工具名串"
                                  "（`agent_a/shelf_search.py` 调 `_h_shelf`/`_h_local`，"
                                  "`agent_g/_support.py`、`paper_package.py` 同族）"
                                  "⇒ 拿字符串级那一档读「有没有被接线」会读反"),
            "gate_basis": "function_level（收紧后已把 string_level 从「有测试」里剔除）",
        },
        "note": ("三个口径并列（收紧后 / 收紧前 / 别处登记的更宽读数）—— 不许只报一个。"
                 "`loose_*` 就是发布门历史上看到的那个 0（被一个字符串满足的绿灯）；"
                 "`tightened_*` 是现在的判据强度。历史那批不可消除的读数见 "
                 "`draft/52` J-45（事件重放不因改代码而消失）"),
    }


#: 已登记的「零生产调用者但不许删」的落点（`draft/48-09 §4.10` + 主控 2026-10-06 裁定）。
#:
#: 这不是豁免表：它出现在读数里、带署名与依据（静默豁免是本项目最忌的形态）。
#: 与 `_EXONERATED` 的区别：那张表管"这个函数不需要直接测试"，这张表管
#: "这个模块被裁定保留、而它在生产面上没有调用者" —— 读者看到的是一件事，
#: 不是一个被抹掉的空格。
#:
#: 为什么必须有它（F7 收紧的现成负控素材）：如果收紧后的判据对这些落点一声不响，
#: 那说明收紧只数了一半 —— 而下一个读读数的人会把"零调用者"读成"可以删"。
REGISTERED_NO_PRODUCTION_CALLER: tuple[dict[str, str], ...] = (
    {
        "target": "src/agentflow/deliver.py",
        "why": ("第二套交付闸门（与收工门 `closing` 同族重叠，`draft/46-05` 并谈）—— "
                "再接新入口会造出「两套闸门各说一套」"),
        "status": "零生产调用者（`cli` 的 `gate` 子命令退场之后；目前唯一入口是它）",
        "guarded_by": "tests/test_deliver.py",
        "decision": "主控裁定：**保留 + 登记为例外**（不删；`draft/48-09 §4.10` 逐字不许删）",
        "source": "draft/48-09 §4.10 + 主控 2026-10-06 裁定",
    },
)


def registered_no_production_caller_reading(funcs: list[FuncInfo]) -> list[dict[str, Any]]:
    """把 :data:`REGISTERED_NO_PRODUCTION_CALLER` 变成带实测数的读数（不是一句声明）。

    每条附上该模块在本工具口径下的公开函数数与零测试数 —— 这样读者一眼能分清
    "登记项"与"漏掉的缺陷"：登记项有署名、有依据、有守它的测试文件。
    """
    out: list[dict[str, Any]] = []
    for entry in REGISTERED_NO_PRODUCTION_CALLER:
        name = str(entry["target"]).rsplit("/", 1)[-1]
        mine = [f for f in funcs if f.module.endswith(name)]
        out.append({
            **entry,
            "module_public_functions": len(mine),
            "module_zero_test": len([f for f in mine if not f.tested]),
        })
    return out


def mark_indirect_only(funcs: list[FuncInfo]) -> int:
    """算"只被 src 内部调用、名字从未出现在测试里"的函数（假阴性上界）。

    做法：从"名字出现在测试里"的种子出发，沿 src 内部的调用边反向扩散；
    扩散不到的零测试函数，就是"可能被间接覆盖但名字从未出现"的那一批。
    这是"按名出现算"这条口径的误报上界 —— 真值只会更小（因为扩散用的是
    名字匹配，同名会互相顶包，把范围算大）。
    """
    by_bare: dict[str, list[FuncInfo]] = {}
    for f in funcs:
        by_bare.setdefault(f.bare, []).append(f)

    reached: set[int] = {id(f) for f in funcs if f.tested}
    # 种子：任何 tested 的函数。然后迭代：若 X 被某个 reached 的函数调用，则 X 也 reached。
    for _ in range(10):
        changed = False
        for f in funcs:
            if id(f) in reached:
                continue
            for caller in funcs:
                if id(caller) in reached and f.bare in caller.calls:
                    reached.add(id(f))
                    changed = True
                    break
        if not changed:
            break
    n = 0
    for f in funcs:
        if f.tested or id(f) in reached:
            continue
        f.indirect_only = True
        n += 1
    return n


# ---------------------------------------------------------------- 自检


def _selfcheck_side_effects(root: Path) -> frozenset[str]:
    """`SIDE_EFFECTS_WRITE` 必须只有一处定义。不一致 ⇒ 退出码 2。

    为什么这条自检必须有：本脚本要按"哪些 side_effect 算写"来分类风险。
    若它自己写死一份而 src 漂了，分类会静默地用错判据 ——
    而"静默用错判据"正是本项目最忌讳的失败形态。
    """
    src = str(root / "src")
    if src not in sys.path:
        sys.path.insert(0, src)
    try:
        from agentflow.tools import SIDE_EFFECTS_WRITE  # type: ignore
    except Exception as e:  # noqa: BLE001
        raise CoverageError(f"无法 import agentflow.tools.SIDE_EFFECTS_WRITE：{type(e).__name__}: {e}") from e
    got = frozenset(SIDE_EFFECTS_WRITE)
    if got != _EXPECT_SIDE_EFFECTS_WRITE:
        raise CoverageError(
            "SIDE_EFFECTS_WRITE 漂移：src 里是 "
            f"{sorted(got)}，本脚本的判据写的是 {sorted(_EXPECT_SIDE_EFFECTS_WRITE)}。"
            "请同步本脚本的 `_EXPECT_SIDE_EFFECTS_WRITE`（并重跑全量分档）。"
        )
    return got


#: `--selftest` 用的合成源码：每个等级各一个已知答案的函数。
#: 这是对判据本身的一正一反 —— 详见 `_selftest()`。
_SELFTEST_SRC = '''
def writes_a_table(store):
    """写路径：调用 store.tx。"""
    with store.tx("t", actor="x") as tx:
        tx.upsert("t", {})

def writes_a_file(path):
    """写路径：write_text。"""
    path.write_text("x", encoding="utf-8")

def writes_via_open(path):
    """写路径：open(..., "w")。"""
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("x")

def reads_a_topic(path, topic):
    """不是写路径：open 的第二个参数是领域值 'topical'，不是模式。"""
    with open(path, "topical", encoding="utf-8") as fh:
        return fh.read()

def validate_row(row):
    """判据：名字含 validate，返回带 reason 的字典。"""
    return {"verdict": "ok", "reason": "fine"}

def is_ready(row):
    """判据：`is_` 是前缀词（后面还跟着东西）⇒ 必须命中 2a。

    为什么要单独放这个正例（外部审查第 1/6 条）：`_token_hits` 的 `parts` 那一步按
    `[^0-9A-Za-z]+` 切分，会把 `_` 一起吃掉，于是 `is_valid` 只剩 ["is","valid"]，
    `p.startswith("is_")` 永远为假 —— 六个带尾下划线的词缀
    （`is_`/`has_`/`can_`/`should_`/`needs_`/`must_`）全部失效，
    而当时的自检里没有一个这种命名的函数 ⇒ 自检全绿却漏掉一整类。
    """
    return {"ok": True, "reason": "ready"}

def negated(text):
    """不是判据：negated 含子串 gate，但按词边界不命中。"""
    return text

def reads_rows(store):
    """只读：调用 store.rows。"""
    return store.rows("t")

def render_markdown(rows):
    """呈现：名字含 markdown，且拼 f-string。"""
    return "\\n".join(f"- {r}" for r in rows)

def orchestrates(store):
    """编排：自己不写盘，只调用 writes_a_table。默认档下**不**算写路径。"""
    return writes_a_table(store)

class _FakeLLM:
    """私有测试替身：它的方法不应被算成公开面。"""
    def judge_gaps(self, payload):
        return {"checked": True, "reason": "fake"}
'''


def _selftest(root: Path) -> int:
    """对分类器跑一正一反。返回 0=全对 / 1=有判据失败 / 2=没跑成。

    一正：每个等级各有一个已知答案的函数被分到正确的档。
    一反：`reads_a_topic` 必须不被判成写路径（这是实测踩过的误报），
    且 `negated` 必须不被判成判据（同样是实测误报）。
    再加一条永远命中等级 1 的假实现的负控：把 `_open_write_modes` 换成
    "永远返回 ['w']" 的实现后，`reads_a_topic` 必须变成红的 —— 这证明这条
    测试不是永远通过。
    """
    try:
        write_sides = _selfcheck_side_effects(root)
        _selfcheck_exonerations(root)
    except CoverageError as e:
        print(f"[selftest] 退出码 2：{e}", file=sys.stderr)
        return 2

    tree = ast.parse(_SELFTEST_SRC)
    got: dict[str, FuncInfo] = {}
    excluded: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) or node.name.startswith("_"):
            continue
        priv = _enclosing_scope(tree, node)
        if priv is not None:
            excluded.append(f"{priv[1]}.{node.name}")
            continue
        info = FuncInfo("selftest", node.name, node.name, node.lineno, False)
        tool_name, se = _decorator_tool(node)
        info.tool_name, info.side_effect = tool_name, se
        _classify(info, node, write_sides)
        got[node.name] = info

    expect = {
        "writes_a_table": 1, "writes_a_file": 1, "writes_via_open": 1,
        "reads_a_topic": 4, "validate_row": 2, "negated": 4,
        # `is_ready` 是"带尾下划线词缀"那一族的正例（外部审查第 1/6 条：
        # 六个这类词缀曾经全部失效，而当时的自检里一个这种命名的函数都没有）。
        "is_ready": 2,
        "reads_rows": 3, "render_markdown": 4,
        # 默认档：编排函数不因调用写路径而升级（1e 默认关闭）。
        # 这条断言本身就是"传递判据默认关闭"这条决定的钉子。
        "orchestrates": 4,
    }
    fails: list[str] = []
    for name, lv in expect.items():
        if name not in got:
            fails.append(f"{name}: 没被收集到")
        elif got[name].level != lv:
            fails.append(f"{name}: 期望等级 {lv}，实得 {got[name].level}（判据 {got[name].level_why}）")
    if excluded != ["_FakeLLM.judge_gaps"]:
        fails.append(f"私有类方法排除不对：{excluded}")

    # ---- 2a 必须被单独钉住（外部审查第二轮第 2 条，我复核成立）。
    # `is_ready` 的体返回 `{"ok":…, "reason":…}`，而这两个键都在 `_VERDICT_KEYS` 里
    # ⇒ 它同时命中 2b。于是"把 `_token_hits` 的 `is_` 分支整个删掉"这件事，光看等级
    # 仍然是 2 ⇒ 自检照样绿 —— 那条正例测不了它声称要测的东西（与被删掉的
    # `writes_a_table` 断言同型）。所以额外断言"这个等级 2 是靠 2a 来的"。
    for name in ("is_ready", "validate_row"):
        why = got[name].level_why if name in got else []
        if not any(w.startswith("2a:") for w in why):
            fails.append(
                f"{name}: 判到等级 2 了，但不是靠 2a（level_why={why}）—— "
                "这正是『is_/has_/can_/should_/needs_/must_ 六个词缀全失效』那条 bug 会通过的形态"
            )

    # ---- 传递判据的正控：打开 `--propagate` 后，`orchestrates` 必须升到等级 1。
    # 为什么这条也要有：1e 是"默认关闭"的，若它的实现坏了，默认档下看不出任何差别
    # —— "关掉的功能坏了没人知道"正是本项目最忌讳的静默失败。
    prop = list(got.values())
    _propagate_levels(prop)
    orch = {f.bare: f.level for f in prop}
    if orch.get("orchestrates") != 1:
        fails.append(
            f"传递判据 1e 坏了：--propagate 下 orchestrates 期望等级 1，实得 {orch.get('orchestrates')}"
        )
    if orch.get("reads_a_topic") != 4:
        fails.append(f"传递判据过度触发：reads_a_topic 被升到 {orch.get('reads_a_topic')}")

    # ---- 负控（变异试验）：把 `open_write_modes` 判据换成"永远返回 ['w']"的假实现，
    # `reads_a_topic` 必须变红。
    # 为什么这条必须有：`reads_a_topic` 期望等级 4 这条断言，若判据被换成
    # "永远判写"，它就必须失败 —— 否则那条断言不依赖判据，是永远通过的。
    real = _CRITERIA["open_write_modes"]
    try:
        _CRITERIA["open_write_modes"] = lambda node: ["w"]
        fake_tree = ast.parse(_SELFTEST_SRC)
        fake_got: dict[str, int] = {}
        for node in ast.walk(fake_tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) or node.name.startswith("_"):
                continue
            if _enclosing_scope(fake_tree, node) is not None:
                continue
            info = FuncInfo("selftest", node.name, node.name, node.lineno, False)
            _classify(info, node, write_sides)
            fake_got[node.name] = info.level
    finally:
        _CRITERIA["open_write_modes"] = real
    if fake_got.get("reads_a_topic") != 1:
        fails.append(
            "变异试验失败：把 `open_write_modes` 换成『永远返回 [\"w\"]』之后，"
            f"`reads_a_topic` 仍是等级 {fake_got.get('reads_a_topic')} —— "
            "说明『它不是写路径』这条断言不依赖判据，是永远通过的"
        )
    # 变异试验的第二半（外部审查第 5 条）：原来这里断言的是 `writes_a_table != 1`，
    # 而它是靠 1b（`store.tx(...)`）判到等级 1 的，根本不走 `open_write_modes`
    # ⇒ 把那个判据换掉对它没有任何影响 ⇒ 那条断言永远为假（永远通过）。
    # 换成真正依赖该判据的那两个：`writes_via_open`（应仍为 1）与
    # `reads_a_topic`（应被误升为 1，上面已单独断言）。
    if fake_got.get("writes_via_open") != 1:
        fails.append(
            "变异试验失败：假实现下 `writes_via_open` 不再是等级 1 ⇒ "
            "`open_write_modes` 这条判据没有真的接在 1c 上"
        )
    if fake_got.get("reads_a_topic") == 4:
        fails.append(
            "变异试验失败：把 `open_write_modes` 换成『永远返回 [\"w\"]』之后 "
            "`reads_a_topic` 仍是等级 4 ⇒ 假实现没有生效（注入本身没做出来）"
        )

    if fails:
        print("[selftest] 退出码 1：判据自检失败", file=sys.stderr)
        for f in fails:
            print(f"  - {f}", file=sys.stderr)
        return 1
    print("[selftest] 退出码 0：分类器与『按名出现』判据的正反用例全部通过"
          f"（{len(expect)} 个已知答案 + 1 个变异负控 + 1 个私有类排除"
          " + 1 个豁免名单可核性检查）")
    return 0


# ---------------------------------------------------------------- 报告


_LEVEL_NAMES = {1: "写路径", 2: "判据/决策", 3: "只读读取", 4: "呈现/格式"}


def _group_by_module(items: list[FuncInfo]) -> dict[str, list[FuncInfo]]:
    out: dict[str, list[FuncInfo]] = {}
    for i in items:
        out.setdefault(i.module, []).append(i)
    return dict(sorted(out.items()))


def _as_dict(items: list[FuncInfo]) -> list[dict]:
    return [
        {
            "module": i.module,
            "qualname": i.qualname,
            "bare": i.bare,
            "lineno": i.lineno,
            "is_method": i.is_method,
            "tool": i.tool_name,
            "side_effect": i.side_effect,
            "has_docstring": i.has_docstring,
            "level": i.level,
            "level_name": _LEVEL_NAMES[i.level],
            "level_why": i.level_why,
            "indirect_only": i.indirect_only,
            "tested_by": i.tested_by,
        }
        for i in items
    ]


def _pin_utf8() -> None:
    """钉住 stdout/stderr 的编码。

    内联的理由与 `scripts/lint_rules.py` 同：门脚本必须在本包 import 不了时也能跑。
    规范实现见 `src/agentflow/console.py::pin_utf8`；两处行为由
    `tests/test_cli_console_encoding.py` 的普查用例统一守着。
    不钉的后果（实测）：GBK 重定向下打印含 `⇒` 的行抛 UnicodeEncodeError，
    进程以 1 结束，而 1 是"发现问题"的码。
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            # 可以忽略：被重定向或被替换过的流可能没有 reconfigure，不该让门崩掉。
            pass


def main(argv: list[str] | None = None) -> int:
    _pin_utf8()
    ap = argparse.ArgumentParser(
        description="机械地算出 agentflow 的『零直接测试公开函数』并按风险等级分档",
    )
    ap.add_argument("--json", action="store_true", help="输出机器可读的 JSON（逐模块清单）")
    ap.add_argument("--level", type=int, default=2, choices=[1, 2, 3, 4],
                    help="报告/退出码的等级阈值：等级 ≤ N 的零测试函数。默认 2（等级 1+2）")
    ap.add_argument("--quiet", action="store_true", help="只打汇总行")
    ap.add_argument("--selftest", action="store_true", help="只跑分类器/判据的自检（一正一反）")
    ap.add_argument("--propagate", action="store_true",
                    help="额外打开传递判据 1e/2c（探索用；默认关闭，理由见模块 docstring）")
    ap.add_argument("--root", default=str(ROOT), help="仓库根（默认脚本的上一级）")
    args = ap.parse_args(argv)

    root = Path(args.root).resolve()
    if not (root / SRC_REL).is_dir():
        return _die(f"找不到 {root / SRC_REL}")
    if not (root / TESTS_REL).is_dir():
        return _die(f"找不到 {root / TESTS_REL}")

    if args.selftest:
        try:
            return _selftest(root)
        except Exception as e:  # noqa: BLE001
            return _die(f"selftest 内部异常：{type(e).__name__}: {e}")

    try:
        write_sides = _selfcheck_side_effects(root)
        _selfcheck_exonerations(root)
        funcs, excluded = collect_src(root, write_sides)
        if args.propagate:
            _propagate_levels(funcs)
        mark_tested(funcs, root)
        n_indirect = mark_indirect_only(funcs)
    except CoverageError as e:
        return _die(str(e))
    except Exception as e:  # noqa: BLE001 - 任何内部异常都必须变成退出码 2，不能是 0
        return _die(f"内部异常：{type(e).__name__}: {e}")

    total = len(funcs)
    zero = [f for f in funcs if not f.tested]
    zero_by_level = {lv: [f for f in zero if f.level == lv] for lv in (1, 2, 3, 4)}
    all_by_level = {lv: [f for f in funcs if f.level == lv] for lv in (1, 2, 3, 4)}
    gate = [f for f in zero if f.level <= args.level]
    callers = production_caller_reading(funcs, zero, args.level)

    if args.json:
        print(json.dumps({
            "root": str(root),
            "level_threshold": args.level,
            "totals": {
                "public_functions": total,
                "zero_test": len(zero),
                "by_level_all": {str(lv): len(all_by_level[lv]) for lv in (1, 2, 3, 4)},
                "by_level_zero": {str(lv): len(zero_by_level[lv]) for lv in (1, 2, 3, 4)},
                "gate": len(gate),
                "excluded_private_class_methods": len(excluded),
                # F7：生产调用者读数（三个口径并列 + 只靠工具名串过关的那些）
                "production_callers": callers,
            },
            "level_names": {str(k): v for k, v in _LEVEL_NAMES.items()},
            "indirect_only_total": n_indirect,
            "indirect_only_by_level": {
                str(lv): len([f for f in zero if f.indirect_only and f.level == lv])
                for lv in (1, 2, 3, 4)
            },
            "excluded": excluded,
            "by_module_zero": {m: _as_dict(v) for m, v in _group_by_module(zero).items()},
        }, ensure_ascii=False, indent=2))
        return 1 if gate else 0

    print(f"[coverage_zero_test] 仓库根={root}")
    print(f"[coverage_zero_test] 公开函数 {total} 个；零直接测试 {len(zero)} 个")
    for lv in (1, 2, 3, 4):
        print(f"  等级 {lv}（{_LEVEL_NAMES[lv]}）：全部 {len(all_by_level[lv])} 个，"
              f"其中零测试 {len(zero_by_level[lv])} 个")
    print(f"[coverage_zero_test] 判据：按名出现（限定名或裸名，作为独立标识符出现在 tests/**/*.py 里）")
    print(f"[coverage_zero_test] 口径假阴性上界：零测试函数里 {n_indirect} 个属于"
          f"『名字从未出现在测试、但可能被 src 间接调用』（逐条见 --json 的 indirect_only）")
    print(f"[coverage_zero_test] 已排除 {len(excluded)} 个嵌套定义（测试替身/局部闭包；"
          f"带 @tool 的嵌套 handler **不**排除），逐条见 --json 的 excluded")
    print(f"[coverage_zero_test] 阈值 --level {args.level} ⇒ 需要补测试的零测试函数 {len(gate)} 个")
    # ---- F7 / L-13 的读数（收紧之后）：三个口径并列
    print(f"[coverage_zero_test] 生产调用者读数（三个口径**并列**，不许只选一个）：")
    print("  口径（两档分开，别混读）：① **函数级** = 这个 handler 函数的裸名/限定名"
          "出现在 tests/ 里（判据与 gate 用这一档）；"
          "② **字符串级** = 只在测试里出现过该工具的**点号名串**（`conductor.stop`）"
          "—— 它数的是字符串，不是调用。"
          "生产路径常**直调工具体**（`agent_a/shelf_search.py` 调 `_h_shelf`/`_h_local`）"
          "而不写 `registry.call(\"search.shelf\")` ⇒ 拿②读「有没有被接线」会读反")
    print(f"  ① 收紧后（本工具现在的口径，`via:tool_name` 单独一条不算）：零测试 "
          f"{callers['tightened_zero_test']} 个，按档 {callers['tightened_by_level_zero']}"
          f" ⇒ gate={callers['tightened_gate']}")
    print(f"  ② 收紧前（发布门历史上看到的那个口径）：零测试 {callers['loose_zero_test']} 个，"
          f"按档 {callers['loose_by_level_zero']} ⇒ gate={callers['loose_gate']}")
    print(f"  ③ 别处登记的更宽读数（**外部读数、本次未复算**）："
          + "、".join(f"{k}={v['value']}（{v['source']}）"
                      for k, v in callers["registered_other_gauges"].items()))
    print(f"  只靠「工具名串」过关的函数 {callers['tool_name_only']} 个，按档 "
          f"{callers['tool_name_only_by_level']}（裁决 8 点名的 7 个写路径 handler 原本在这里；"
          f"补了真调用测试的那些已回到 ①）")
    for entry in callers.get("registered_no_production_caller") or []:
        print(f"  【登记】{entry['target']}：{entry['status']}；{entry['decision']}"
              f"（守它的测试：{entry['guarded_by']}；本工具口径下该模块公开函数 "
              f"{entry['module_public_functions']} 个、零测试 {entry['module_zero_test']} 个）")

    if not args.quiet:
        for lv in range(1, args.level + 1):
            items = zero_by_level[lv]
            if not items:
                continue
            print(f"\n===== 等级 {lv}（{_LEVEL_NAMES[lv]}）的零测试函数 {len(items)} 个 =====")
            for mod, group in _group_by_module(items).items():
                print(f"\n-- {mod}（{len(group)} 个）")
                for i in group:
                    tool = f" [tool={i.tool_name} side_effect={i.side_effect}]" if i.tool_name else ""
                    mark = " (可能间接覆盖)" if i.indirect_only else ""
                    print(f"   L{i.lineno:<5} {i.qualname}{tool}{mark}")
                    print(f"          判据：{'；'.join(i.level_why)}")

    if gate:
        print(f"\n[coverage_zero_test] 退出码 1：等级 ≤ {args.level} 的零测试函数有 {len(gate)} 个（见上）")
        return 1
    print(f"\n[coverage_zero_test] 退出码 0：等级 ≤ {args.level} 的零测试函数为 0")
    return 0


def _die(msg: str) -> int:
    print(f"[coverage_zero_test] 退出码 2（脚本自己没跑成）：{msg}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())

"""接线判据：今晚这批新功能必须挂在真机调用图上，且这件事要有一条会红的判据。

## 这一份守的是什么

业主 2026-10-27 的话是这一类缺陷的唯一权威：「有极大概率你的那些子代理们把功能实现好
以后未接线，请务必检查接线」。它描述的是一个具体的失败形态：

    函数写好了、单测也绿了，可是没有任何真机路径会调它。

这种形态在任何一条既有判据里都看不见 —— 单测自己塞调用方，所以它永远是绿的。已经
量到过的实例：`clock.park_state`（只作为读数被读，从不参与控制流，见
`docs/WIRING-AUDIT-2026-10-27.md`）。2026-10-27 晚的另两只是
`secretary.proof_route_of` / `proof_routes_of`（读侧唯一口径，全仓 0 个非测试调用点）
—— 它们已在本轮接上读侧，台账因此清空。

本文件把「谁在活着的那条路上调它」做成源码级判据：一张表（`WIRED`）+ 一个走一遍
AST 就能算出来的可达集 + 一个反向核对（发现的空集必须等于 `KNOWN_ORPHANS`）。

## 边的四种形态（少算一种就会误报 ORPHAN）

真机里"被调用"不只是 `f(...)` 这一种写法。本仓实测有四种，四种都要算边：

1. 调用：`f(...)` / `obj.f(...)`；
2. 裸引用：`sessions.set_append_hook(_observe_session_event)`、`clock.set_due_handler(_deliver_due)`
   —— 挂点型接线，函数体以后再被调用。只算调用会把 `observe_work` 判成孤儿
   （它唯一的入口就是这个挂点）；
3. 工厂默认值：`sleep = sleep or self._default_sleep` —— 引用之后经 `self._sleep(...)` 调用。
   只算调用会把 `fetch._default_sleep` 判成孤儿。
4. 字符串接缝（2026-10-26，F1a）：`getattr(cond, "open_retire_question", None)` —— 名字是
   一个字符串字面量，源码里没有任何调用边能连到那份定义。第二实参是字面量时按那个
   名字记一条边（种类 `getattr`），解析走紧口径：按文件指不到唯一一份就一个都不给、
   只留一条 problem（否则一条 `getattr(args, "run")` 能替三十个死 `run` 作证）。

## 入口集（真机可达的起点）

- `cli.py` 里 `cmd_*` 那些子命令处理器（`set_defaults(func=cmd_xxx)` 是 argparse 的挂点，
  静态看不见）；
- `host.py` 的全部函数（装配线本身）；
- 带 `tool` 装饰器的函数（模型按名字从注册表里取，静态也看不见）；
- 模块级派发表点名的那些函数（2026-10-26，F1a）：`readers.ROUTES` 这种
  `("GET", "/api/state", "handle_state")` 三元组表、`readers.HANDLERS.update({...})` /
  `writes.HANDLERS` 这种"名字 → 函数对象"登记表。`routes.handler_for` 是按字符串取函数
  的（`table.get(name)`），源码里一条调用边都没有 ⇒ 不种的话 B/C 两条线的 HTTP 处理器
  在图上全是孤儿。实测补之前 `webui/readers.py` 只有 7 个 def 可达（≈60 个里的 7 个），
  于是"这一片到底接上没有"这件事在这个判据上读不出来。

  两种形状都按结构认，不按表名认（表名叫什么靠不住，而形状只有那两种）：
  路由表 = 容器里每一行都是"至少两格、每格都是字符串"的元组；处理器登记表 = 字典、
  键全是字符串、值是裸名字（或字符串）。`__all__` 与 `_TS_TYPES` 都不长这样 ——
  声明面不是调用面，把 `__all__` 当种子等于让"申明了就活着"。

## 误差方向（这一条必须写清，否则判据会骗人）

- 边按 (文件, 限定名) 收，不再只按名字（2026-10-27 晚第二处修，理由见下面"图的边"那一节）；
  一个调用点上的名字解析不出唯一一份文件时会退回按名字，并记一条 problem
  （`resolution_problems`），台账里每一个名字都不许走到那一档；
- 两条路的方向不同，两条都要写清（2026-10-26，F1a）：
  漏报（会误报 ORPHAN）—— 经反射 / 运行时拼出来的名字（`getattr(obj, name)` 里 `name`
  是变量）仍然看不见；字符串接缝只收"第二实参是字面量"那一半。
  漏报的反面（会误报 WIRED）—— 派发表按形状认（路由表 / 登记表），一张"长得像表、
  其实不是派发表"的字面量会给它点名的函数发一张假入口。这一档的兜底是台账：每条
  `KNOWN_ORPHANS` 都带一句理由，且台账必须与实测集合相等 —— 有人真把它接上，这一条会红
  （接线事件要人看见），有人新造一条孤儿，这一条也会红；名字对不上时先查"它是不是被
  哪张假表种进去了"，而不是先把台账改宽。
"""
from __future__ import annotations

import ast
import functools
import pathlib

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "agentflow"


# ============================================================ 图的边
#
# 2026-10-27 晚的第二处修：这张图原来按名字建边，于是同名的另一条活函数会把可达性
# 借给孤儿（漏报方向）—— 一条死函数只要与某条活函数同名，`is_live` 就替它说"活"，
# 而"孤儿"与"活着的那条同名函数"在读数上一模一样。这正是本文件最贵的那种坏法：
# 判据绿着、缺陷静默地留在树里。
#
# 修法：一个调用点上的名字按下面四档解析成 (文件, 限定名)：
#   1. 本文件里的同名定义（方法也算，`self.x()` 落在同一个文件里）；
#   2. 本文件 `from .mod import name` 指到的那份文件里的同名定义；
#   3. 全树唯一的那一条（没有歧义，按名字认是可以的）；
#   4. 同名多定义、前两档也指不到唯一一份 ⇒ 退回按名字，并记一条 problem。
# 第 4 档是"留痕"那一格：静默借可达性就是漏报的入口，所以它必须被台账看见
# （`test_every_ledger_name_is_resolved_by_file_not_by_name`）。
#
# 不建的边：`import a.b` 形态（本仓的工具/角色模块一律走 `from .x import y`），
# 以及任何经反射/字符串表拿到的调用 —— 方向都是漏报（会把可达读成不可达），
# 兜底是 `KNOWN_ORPHANS` 那本台账必须逐条写清差哪一根线。

def _parse(path: pathlib.Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _import_base(rel: str, level: int) -> pathlib.PurePosixPath:
    """`from ..tools import x` 这样的相对层级 -> 被导入模块所在的目录。"""
    base = pathlib.PurePosixPath(rel).parent
    for _ in range(max(level - 1, 0)):
        base = base.parent
    return base


def _module_files(base: pathlib.PurePosixPath, module: str) -> list[str]:
    """模块名 -> 图里的候选相对路径（`a/b.py` 与 `a/b/__init__.py` 两种形态）。"""
    target = base if not module else base / module.replace(".", "/")
    text = target.as_posix()
    while text.startswith("./"):
        text = text[2:]
    if text in ("", "."):
        return ["__init__.py"]
    return [f"{text}.py", f"{text}/__init__.py"]


#: 字符串接缝记的边（`getattr(obj, "名字")`）：这类边是"按名字查一次"，不是"调用同一份
#: 定义"。它们按同一套名字解析走，但解析不出唯一一份时不借可达性（见 `_resolve` 的
#: `strict`），否则一个 `getattr(args, "run")` 就能把全树三十份 `run` 一起点亮。
_STRING_SEAM_KINDS: frozenset[str] = frozenset({"getattr"})


def _is_str(node: ast.AST) -> bool:
    """这个节点是不是一个字符串常量。"""
    return isinstance(node, ast.Constant) and isinstance(node.value, str)


def _module_table_nodes(stmt: ast.stmt) -> list[ast.expr]:
    """一条模块级语句里、那些"可能是派发表"的字面量容器（元组 / 列表 / 字典）。

    只认三种写法：赋值右侧、类型注解赋值右侧、以及 `X.update({...})` 的实参
    （`readers.HANDLERS.update({...})` 就是第三种）。刻意不下钻普通调用：
    `ROUTES = compose(a, b, c)` 这种"算出来的表"由它自己那段源码给出落点，
    这一层不替它猜。
    """
    cand: list[ast.expr] = []
    if isinstance(stmt, ast.Assign):
        cand = [stmt.value]
    elif isinstance(stmt, ast.AnnAssign):
        cand = [stmt.value] if stmt.value is not None else []
    elif isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
        cand = list(stmt.value.args)
    return [c for c in cand if isinstance(c, (ast.Tuple, ast.List, ast.Dict))]


def _route_rows(container: ast.expr) -> list[str]:
    """路由子表（`("GET", "/api/state", "handle_state")` 这种三元组）里点名的名字。

    形状判据（少一条就会把 `__all__` 那种"声明面"当成派发表）：容器里每一行都是一个
    元组 / 列表，每一行至少两格，且每一格都是字符串常量。`__all__` 是"一串字符串"、
    `_TS_TYPES` 是"字符串键 → 元组"，两者都不长这样，于是都不会被误当成派发表 ——
    声明面不是调用面，把它当种子等于让"申明了就活着"。
    """
    rows = container.elts if isinstance(container, (ast.Tuple, ast.List)) else []
    if not rows:
        return []
    names: list[str] = []
    for row in rows:
        if not isinstance(row, (ast.Tuple, ast.List)) or len(row.elts) < 2:
            return []
        if not all(_is_str(e) for e in row.elts):
            return []
        names.extend(str(e.value) for e in row.elts)
    return names


def _handler_rows(container: ast.expr) -> list[str]:
    """处理器登记表（`{"handle_state": handle_state}`）里点名的名字。

    形状判据：字典、键全是字符串、值全是"裸名字"或字符串。值是别的东西（比如
    `_TS_TYPES` 那种"字符串键 → 元组"）就说明它不是登记表。
    """
    if not isinstance(container, ast.Dict) or not container.keys:
        return []
    names: list[str] = []
    for key, value in zip(container.keys, container.values):
        if not _is_str(key):
            return []
        if isinstance(value, ast.Name):
            names.append(value.id)
        elif _is_str(value):
            names.append(str(value.value))
        else:
            return []
    return names


def _action_rows(container: ast.expr) -> list[str]:
    """动作表（`ACTIONS = (ActionSpec(...), ...)`）里点名的那些名字。

    形状判据：容器里每一行都是一次调用，且每一行都带字符串字面量实参。
    `ActionSpec("G", "revise", "改一条…", ..., handler_name="revise")` 这种表是角色动作的
    真机派发表：`capabilities` 从它派生 `CAPABILITIES`，`host.build_role_registry` 按
    `handler_name` 找到实现类上的那个方法。源码里没有一条调用边能连到那些方法 ——
    实测（2026-10-26，F1a）：不种它时 `agent_g/revise.py:_Revise.revise`、
    `agent_h/review.py:_Review.review` 这些动作实现在图上都是孤儿，而它们是真机入口。
    """
    rows = container.elts if isinstance(container, (ast.Tuple, ast.List)) else []
    if not rows:
        return []
    names: list[str] = []
    for row in rows:
        if not isinstance(row, ast.Call):
            return []
        got = [str(e.value) for e in list(row.args) + [k.value for k in row.keywords]
               if _is_str(e)]
        if not got:
            return []
        names.extend(got)
    return names


#: 三档派发表。值 = 这个名字解析不出唯一一份时的口径（`entries()` 用）：
#: - `routes` / `handlers`：表在一个已知模块里点了一个函数的名（`HANDLERS.get(name)`），
#:   所以"按文件指不到唯一一份"就是这张表坏了 ⇒ 紧口径：种不进去，只留 problem；
#: - `actions`：表点的是"角色动作的实现方法名"，而实现类落在哪个文件不由表说
#:   （`host.build_role_registry` 按角色装配），静态不知道 ⇒ 只能按名字（所有同名定义
#:   都算入口）。这是过近似的那一侧，代价写在模块 docstring 的「误差方向」里。
_DISPATCH_KINDS: dict[str, bool] = {"routes": True, "handlers": True, "actions": False}


def _table_entries(container: ast.expr) -> tuple[str, list[str]] | None:
    """一个模块级字面量容器是哪种派发表、点名的那些名字（认不出就返回 None）。"""
    if isinstance(container, ast.Dict):
        got = _handler_rows(container)
        return ("handlers", got) if got else None
    got = _route_rows(container)
    if got:
        return ("routes", got)
    got = _action_rows(container)
    return ("actions", got) if got else None


class _Collect(ast.NodeVisitor):
    """一遍 AST 收五样：定义点、调用边、裸引用边、`from ... import` 的落点表、派发表。"""

    def __init__(self, rel: str) -> None:
        self.rel = rel
        self.stack: list[str] = []
        self.defs: list[dict] = []
        self.edges: list[tuple[str, str, int, str, tuple[str, ...]]] = []
        # (caller_qual, callee, line, kind, 别名指到的候选文件)
        self.imports: dict[str, list[str]] = {}            # 本地名 -> 候选文件
        self.tables: list[tuple[int, str, list[str]]] = []  # (行号, 档, 点名的那些名字)

    def _qual(self) -> str:
        return ".".join(self.stack) or "<module>"

    def _enter(self, name: str) -> None:
        self.stack.append(name)

    def visit_Module(self, node: ast.Module) -> None:
        # 模块级派发表（2026-10-26 F1a）：入口那一侧的一张表 —— 见模块 docstring「入口集」
        # 的第 4 条。这里只收"点名的名字"，解析（名字 → 定义点）留给 `entries()`：
        # 名字可能指到别的文件（`routes._OWN` 的第三元素是 `server.py` 上的方法名）。
        for stmt in node.body:
            for container in _module_table_nodes(stmt):
                got = _table_entries(container)
                if got:
                    kind, names = got
                    self.tables.append((int(container.lineno), kind, list(names)))
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.defs.append({"rel": self.rel, "line": node.lineno, "name": node.name,
                          "qual": ".".join(self.stack + [node.name]),
                          "decos": [ast.unparse(d) for d in node.decorator_list]})
        self._enter(node.name)
        self.generic_visit(node)
        self.stack.pop()

    visit_AsyncFunctionDef = visit_FunctionDef  # type: ignore[assignment]

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._enter(node.name)
        self.generic_visit(node)
        self.stack.pop()

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        base = _import_base(self.rel, node.level or 0)
        module = node.module or ""
        for alias in node.names:
            # 两档候选（2026-10-26 F1a，第二处修）：`from .pkg import 名字` 里的"名字"
            # 可能是 `pkg` 里的一个定义，也可能是 `pkg` 下的一个子模块。
            # 只按前者记时，`from . import stopctl as SC` 会指到包的 `__init__.py`，
            # 于是 `SC.acquire(...)` 按文件解析不出来、退回按名字 —— 而"退回按名字"
            # 正是本文件第一处修要挡掉的那个漏报方向（同名借用可达性）。
            cands = list(_module_files(base, module))
            cands.extend(_module_files(base / module.replace(".", "/") if module else base,
                                       alias.name))
            self.imports[alias.asname or alias.name] = cands
        self.generic_visit(node)

    def _alias_files(self, node: ast.expr) -> tuple[str, ...]:
        """`X.attr` 里 `X` 是 `from . import mod as X` 那种别名时，那个别名指到的候选文件。

        这一格是 alias 那条接缝的另一半（2026-10-26，F1a）：`from . import clock as CLK`
        之后写 `CLK.start_timer(...)`，源码里那条边的名字是 `start_timer`，而
        `import` 表里记的键是别名 `CLK` —— 两个名字对不上，于是按文件永远解析不出来，
        每次都退回按名字。把别名指到的文件带在边上，`_resolve` 才真的按文件解析。
        """
        if isinstance(node, ast.Name) and not isinstance(node.ctx, ast.Store):
            return tuple(self.imports.get(node.id, ()))
        return ()

    def visit_Call(self, node: ast.Call) -> None:
        name = None
        hint: tuple[str, ...] = ()
        if isinstance(node.func, ast.Name):
            name = node.func.id
        elif isinstance(node.func, ast.Attribute):
            name = node.func.attr
            hint = self._alias_files(node.func.value)
        if name:
            self.edges.append((self._qual(), name, node.lineno, "call", hint))
        # 字符串接缝（2026-10-26 F1a）：`getattr(cond, "open_retire_question", None)` 这一档
        # 是"按名字取一个函数、再调它"，静态看不见落点。第二实参是字符串字面量时按那个
        # 名字记一条边 —— 这是"这个名字在真机上被查了一次"的唯一书面证据。
        if isinstance(node.func, ast.Name) and node.func.id == "getattr" \
                and len(node.args) >= 2 and _is_str(node.args[1]):
            self.edges.append((self._qual(), str(node.args[1].value),  # type: ignore[attr-defined]
                               node.lineno, "getattr", ()))
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        # 裸引用（`f` 作为值被传出去）。`Load` 才算：`Store` 是赋值目标，不是边。
        if isinstance(node.ctx, ast.Load):
            self.edges.append((self._qual(), node.id, node.lineno, "ref", ()))
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        # `obj.attr` 里 attr 作为值被取出（`self._default_sleep` / `SS.set_append_hook`）。
        if isinstance(node.ctx, ast.Load):
            self.edges.append((self._qual(), node.attr, node.lineno, "ref",
                               self._alias_files(node.value)))
        self.generic_visit(node)


def _graph_of(pairs: list[tuple[str, ast.Module]]) -> dict:
    """把若干（相对路径, AST）收成与 `graph()` 同形的接线图。

    为什么抽出这一层：反真空那一条要拿"语义相反的两棵树"去喂 `entries()` /
    `reachable()` / `is_live()` 本身。喂 AST 而不是喂现成的图，是为了让被量的
    那几步（收边、种入口、闭包）真的跑一遍，而不是用例自己手搭一份图再自证。
    """
    defs: dict[str, list[dict]] = {}
    out_edges: dict[tuple[str, str], dict[str, tuple[str, tuple[str, ...]]]] = {}
    in_edges: dict[str, list[tuple[str, str, int, str]]] = {}
    imports: dict[str, dict[str, list[str]]] = {}
    dispatch: dict[str, list[tuple[int, str, list[str]]]] = {}   # 文件 -> [(行号, 档, 名字)]
    for rel, tree in pairs:
        got = _Collect(rel)
        got.visit(tree)
        for d in got.defs:
            defs.setdefault(d["name"], []).append(d)
        for caller, callee, line, kind, hint in got.edges:
            slot = out_edges.setdefault((rel, caller), {})
            old = slot.get(callee)
            # 同一个名字既是普通调用、又被字符串接缝查过时，记"普通"那一档：两档的
            # 解析宽严不同（字符串接缝不借可达性），宽的优先 —— 否则一条紧挨着的调用
            # 会被另一条 getattr 的紧口径拖死。
            if old is None or (old[0] in _STRING_SEAM_KINDS and kind not in _STRING_SEAM_KINDS):
                slot[callee] = (kind, hint)
            in_edges.setdefault(callee, []).append((rel, caller, line, kind))
        imports[rel] = dict(got.imports)
        if got.tables:
            dispatch[rel] = list(got.tables)
    return {"defs": defs, "out": out_edges, "in": in_edges, "imports": imports,
            "dispatch": dispatch}


@functools.lru_cache(maxsize=1)
def graph() -> dict:
    """整棵 `src/agentflow` 的接线图（只读盘，不 import 任何模块）。"""
    return _graph_of([(path.relative_to(SRC).as_posix(), _parse(path))
                      for path in sorted(SRC.rglob("*.py"))])


def _resolve(g: dict, caller_rel: str, name: str, *, strict: bool = False,
             files: tuple[str, ...] = ()) -> tuple[set[tuple[str, str]], str]:
    """把一个调用点上的名字解析成 `(文件, 限定名)` 定义点；解析不出唯一一份时返回一句 problem。

    `files`：调用点自己带来的候选文件（`CLK.start_timer` 里 `CLK` 指向的那几份）。
    它排在最前面，因为它是调用点自己给出来的证据；没有它时 `import` 表只能按
    被调的名字查，而别名写法（`from . import clock as CLK`）里被调的名字是 `start_timer`、
    `import` 表的键是 `CLK`，两者对不上 ⇒ 每次都退回按名字。

    `strict=True` 是字符串接缝那一档的紧口径（2026-10-26 F1a）：按文件指不到唯一一份
    就一个都不给，只留 problem。理由：`getattr(obj, "run", None)` 是"按名字查一次"，
    查的是哪个 `run` 静态不知道；把全树三十份 `run` 一起点亮，等于让一条
    `getattr(args, "run")` 替三十个死函数作证 —— 那是本文件最贵的那种坏法。
    """
    rows = g["defs"].get(name, [])
    for candidate in files:
        there = {(d["rel"], d["qual"]) for d in rows if d["rel"] == candidate}
        if there:
            return there, ""
    here = {(d["rel"], d["qual"]) for d in rows if d["rel"] == caller_rel}
    if here:
        return here, ""
    for candidate in g["imports"].get(caller_rel, {}).get(name, ()):
        there = {(d["rel"], d["qual"]) for d in rows if d["rel"] == candidate}
        if there:
            return there, ""
    everywhere = {(d["rel"], d["qual"]) for d in rows}
    if len(everywhere) == 1:
        return everywhere, ""
    if not everywhere:
        return set(), ""
    problem = (f"{caller_rel} 里的调用点 {name!r} 有 {len(everywhere)} 个同名定义点，"
               f"按文件指不到唯一一份，退回按名字：{sorted(everywhere)}")
    if strict:
        return set(), problem.replace("退回按名字", "按紧口径一个都不给")
    return everywhere, problem


def entries(g: dict) -> set[tuple[str, str]]:
    """真机入口集（见模块 docstring 那四条），元素是 `(文件, 限定名)`。

    第 4 条（模块级派发表，2026-10-26 F1a）在 `g["dispatch"]` 里：那里面是"表里点名的
    名字"，名字 → 定义点的解析仍走 `_resolve`，宽严按表的档位给（`_DISPATCH_KINDS`）。
    为什么要从表里种：`routes.handler_for` / `HANDLERS.get(name)` 是"按字符串取函数"，
    源码里没有任何调用边能连到 `readers.handle_state` 那一片 —— 不种的话整个 B 线
    读侧（一百来个 def）在图上都是孤儿（实测补之前 7/103 可达）。
    """
    seeds: set[tuple[str, str]] = set()
    for name, rows in g["defs"].items():
        for d in rows:
            if d["rel"] == "cli.py" and name.startswith("cmd_"):
                seeds.add((d["rel"], d["qual"]))
            elif d["rel"] == "host.py":
                seeds.add((d["rel"], d["qual"]))
            elif any("tool" in deco for deco in d["decos"]):
                seeds.add((d["rel"], d["qual"]))
    for rel, tables in g.get("dispatch", {}).items():
        for _line, kind, names in tables:
            strict = _DISPATCH_KINDS.get(kind, True)
            for name in names:
                targets, _problem = _resolve(g, rel, name, strict=strict)
                seeds.update(targets)
    return seeds


def _walk(g: dict) -> tuple[set[tuple[str, str]], list[tuple[str, str, str, str]]]:
    """从入口集顺边闭包；顺手把"解析不出唯一一份"的那些调用点收下来（每个图只算一遍）。"""
    cached = g.get("_walk")
    if cached is not None:
        return cached
    seen: set[tuple[str, str]] = set()
    problems: list[tuple[str, str, str, str]] = []
    todo = list(entries(g))
    while todo:
        rel, qual = todo.pop()
        if (rel, qual) in seen:
            continue
        seen.add((rel, qual))
        for callee, (kind, hint) in sorted(g["out"].get((rel, qual), {}).items()):
            targets, problem = _resolve(g, rel, callee,
                                        strict=kind in _STRING_SEAM_KINDS, files=hint)
            if problem:
                problems.append((rel, qual, callee, problem))
            for target in targets:
                if target not in seen:
                    todo.append(target)
    g["_walk"] = (seen, problems)
    return seen, problems


def reachable(g: dict) -> set[tuple[str, str]]:
    """可达的定义点集合（`(文件, 限定名)`；同名不再互相借可达性）。"""
    return _walk(g)[0]


def resolution_problems(g: dict) -> list[tuple[str, str, str, str]]:
    """退回按名字解析的那些调用点：`(调用者文件, 调用者限定名, 名字, 一句说明)`。"""
    return list(_walk(g)[1])


def callers(g: dict, name: str) -> list[tuple[str, str, int, str]]:
    """非测试调用/引用点（本图只收 src，所以全是非测试）。"""
    return list(g["in"].get(name, ()))


def is_live(g: dict, name: str, *, rel: str | None = None) -> bool:
    """这个名字有没有至少一个"本身可达"的调用/引用点。

    `rel=None`：名字级读数（台账 `KNOWN_ORPHANS` 的记账单位）；
    `rel="x.py"`：只问那份文件里的那一个定义 —— 同名的两份定义必须能分开量。
    """
    rows = [d for d in g["defs"].get(name, []) if rel is None or d["rel"] == rel]
    if not rows:
        return False
    live = reachable(g)
    return any((d["rel"], d["qual"]) in live for d in rows)


# ============================================================ 表

#: 今晚这一批（15 项）里每一项在代码上的那个落点。值是一句"谁在活着的那条路上调它"，
#: 空串 = 这一项今天是孤儿（必须同时出现在 `KNOWN_ORPHANS` 里，否则反真空那一条会红）。
#:
#: 2026-10-27 第二批（业主四条裁定的六件）追加在末尾，判据同一条：有真机调用点、
#: 调用者本身可达、且有一条运行探针读数（读数在
#: `docs/WIRING-AUDIT-2026-10-27.md` 第六节；探针脚本零模型钱）。
#:
#: 注意这张表只收"靠调用/引用边接起来"的那些。模型按名字调的工具走的是另一条面
#: （注册表），它们的判据在下面 `WIRED_BY_REGISTRY` —— 把工具混进这张表会让判据误报，
#: 因为工具函数在源码里本来就没有调用点（那是注册表的活，不是调用图的活）。
WIRED: dict[str, str] = {
    # 2 挂机：登记 / 读数 / 事件观测 / 唤醒消费
    "_register_parked": "clock.start_timer + clock.start_alarm",
    "waiters": "clock_now + clock_timer_list（只作读数）",
    "observe_work": "clock_tools._observe_session_event（会话写路径的旁路钩子）",
    "observe_message": "clock_tools._observe_session_event",
    "pending_wakes": "agent_loop._wake_pending + clock_now",
    "consume_wakes": "agent_loop.consume_clock_wakes（_take_wakes 调它）",
    # 3 秘书链转发
    "relay_out": "conductor_tools.conductor_guide（conductor.guide）",
    "relay_in": "Secretary.relay_out + Secretary.relay_in（逐跳递归）",
    "deliver_local": "Secretary.relay_in（链尾那一跳）",
    "relay_path": "Secretary.relay_out / relay_in（三处落台账）",
    # 4 链式寻址
    "parse_chain_address": "Conductor.resolve_chain",
    "resolve_chain": "conductor_tools.conductor_guide",
    "chain_of": "Conductor.resolve_chain + Conductor.tree",
    "chain_text": "Conductor.resolve_chain + Conductor.tree 的 chain 格",
    # 6 依赖面：F 写稿 / 秘书洗稿 / 打回
    "wash_dependency_face": "_Core._wash_manuscript",
    "_wash_manuscript": "_Core._apply_round 的 proof 分支（在 _proof_outlet 之前）",
    # 7 D 携带
    "_deliver_carried_to_b": "_WriteReport.write_report",
    "read_carried_manuscript": "_RegisterStatement.register_statement（两处探测）",
    "carried_manuscripts": "depsection.read_carried_manuscript",
    # 8 B 读稿落依赖
    "read_manuscript": "_RegisterStatement.register_statement 的兜底读盘",
    "record_manuscript_dependency_face": "_RegisterStatement._receive_carried_manuscript",
    # 9 V 引用核实
    "citation_material": "agent_v.core._citation_material",
    "reconcile_citation_checks": "AgentV._citation_checks",
    "apply_citation_gate": "AgentV.verify_proof",
    "signs_bit3": "verifications.record_verification 等七处",
    # 10 保留产物闸
    "_reserved_artifact": "fs_tools._reserved_refusal（fs_write / fs_edit 两道闸共用）",
    # 12 非平凡度
    "proof_effort_readings": "Secretary.judge_statement",
    "nontriviality_from_effort": "Secretary.judge_statement",
    "material_truncation": "Secretary.judge_statement",
    # 13 命题同一性
    "adjudicate_proposition": "Secretary.record_statement",
    "append_proposition_verdict": "Secretary.adjudicate_proposition",
    "proposition_verdict_of": "Secretary.adjudicate_proposition（缓存读回）",
    # 13（续）证明的路子说明：写侧 `record_statement` 落 `secretary.PROOF_ROUTES_KEY`，
    # 读侧 2026-10-27 起接在 `table_tools._with_proof_routes`（`table.get` /
    # `table.list` 的 statements 行带 `route` 与 `proof_routes` 两格）。
    # 改前这两只是孤儿：写进去之后全仓 0 个非测试调用点读回来。
    "proof_routes_of": "table_tools._with_proof_routes（两条读侧工具共用它）",
    "proof_route_of": "table_tools._with_proof_routes（同一处的 `route` 格）",
    # 15 时钟账
    "await_io": "fetch / providers / store / conductor / userio 共十三处",
    "note_wait": "clock.await_io + conductor.SummonHandle.wait + scheduler.WaveHandle",
    "coverage": "clock_now（clock.now 的 waits_outside_clock 那一格）",
    "raw_wait_census": "clock.coverage",
    # ---------------------------------------------------------------- 第二批（业主 2026-10-27 四条裁定）
    # ① 等程序：起外部程序的唯一入口是 `program_span`，进作用域就 `start_program`
    #    登记一条 kind="program" 的计时器，出作用域 `finish_program` 收口。
    "program_span": "cancellation.run_cancellable:519 等六处（起程序并等它的唯一入口）",
    "start_program": "clock.ProgramSpan.open:1854（进作用域那一刻）",
    "finish_program": "clock.ProgramSpan.finish:1883（出作用域那一刻）",
    # ② 目的自动填：装配期把"等谁"的读口挂上，读口从名册/台账里抄那一行 task 原文。
    "set_target_probe": "tools/clock_tools.py:1211 register（装配期挂口）",
    "_target_probe": "tools/clock_tools.py:1211 register（挂给 clock.set_target_probe）",
    "_roster_task_text": "tools/clock_tools.py:339 _target_probe（名册那一行 task 原文）",
    # ③ 等待任意计时器返回：读侧接在循环的判据上（`wait_any_reading`）；写侧
    #    `request_wait_any` 原先只有框架内部入口、模型面没有那一格（这就是第二批里
    #    唯一的 UNREACHABLE）。第二段① 把它做成 `clock.wait_any` 之后两条都通了 ——
    #    `clock.wait_any` 本身在 `WIRED_BY_REGISTRY`（工具面），它的 handler 调
    #    `request_wait_any`，于是这里写的是那条新的活边。
    "wait_any_reading": "agent_loop._wait_any_reading:4898 + agent_loop._hand_off:5090",
    "request_wait_any": "tools/clock_tools.py:1163 clock_wait_any（clock.wait_any 的 handler）",
    # ④ 计时器不阻塞动作：判据只有一处（`_park_gate`），"手上有活"由 `_pending_work` 现算。
    "_park_gate": "AgentLoop.run:6125（_deliver_mailbox 之后、ask_step 之前）",
    "_pending_work": "agent_loop._park_gate:4981",
    "_wait_any_reading": "agent_loop._park_gate:4980",
    # ⑤ 交差：无事可做 + 无计时器 ⇒ `_hand_off`；父侧在消费唤醒时记静默。
    "_hand_off": "AgentLoop.run:6131（_park_gate 判成交差那一支）",
    "_note_child_handoff": "agent_loop._take_wakes:4328（每条唤醒都过一遍）",
    "record_handoff": "agent_loop._hand_off:5095",
    "mark_handoff_seen": "agent_loop._note_child_handoff:4360",
    "read_handoffs": "Conductor._handoffs_summary:2665（父侧读数）",
    # ⑥ 不变量：派活成功那一刻起表（写侧），读侧判据只被测试接线 ⇒ 见 KNOWN_ORPHANS。
    "arm_child_waiter": "Conductor._summon_preflight:5160（[5c]，_register_roster 之后）",
    "_summon_preflight": "Conductor.summon_begin:4824",
}

#: 模型按名字调的那一批：它们的接线面是 `tools._MODULES`（模块装配表），不是调用边。
#: 值是"这个函数所在的工具模块"，判据同时核两件事：函数真的有 tool 装饰器、模块在表里。
WIRED_BY_REGISTRY: dict[str, str] = {
    "clock_now": "clock_tools",
    "clock_timer_start": "clock_tools",
    "clock_alarm_start": "clock_tools",
    "clock_timer_list": "clock_tools",
    "clock_timer_cancel": "clock_tools",
    "clock_periodic_start": "clock_tools",
    "clock_periodic_stop": "clock_tools",
    "clock_timer_purpose": "clock_tools",
    "clock_wait_any": "clock_tools",
    "conductor_watch": "conductor_tools",
    "conductor_ledger": "conductor_tools",
    "conductor_guide": "conductor_tools",
    "trace_children": "trace_tools",
}

#: 今天实测没有真机调用点的那些。每一条都要写清"为什么它还在、以及差哪一根线"；
#: 这张表与实测集合必须相等（新增孤儿会红，接上之后不改表也会红）。
#:
#: 2026-10-27 晚清空：最后两条（`proof_route_of` / `proof_routes_of`）已经接上读侧
#: （`table_tools._with_proof_routes`），于是它们移进 `WIRED`。空表本身也是有内容的
#: 读数：它说"今天这一批没有孤儿"，而反真空那一条（实测集合必须等于台账）仍然在守。
#:
#: 2026-10-27 第二批填过七条（`programs` / `program_census` / `request_wait_any` /
#: `read_wait_any` / `cancel_wait_any` / `handoffs_reading` / `child_wait_invariant`），
#: 随后逐条补线清空：
#: - `request_wait_any` → `clock.wait_any`（工具面，`WIRED_BY_REGISTRY`）；
#: - `programs` → `clock.now` 的 `programs` 那一格；
#: - `program_census` → `clock.coverage()` 的 `programs_outside_clock`（`clock.now` 念它）；
#: - `read_wait_any` → `clock.wait_any` 的 `intents` 那一格；
#: - `cancel_wait_any` → `agent_loop._park_gate` 回模型那一拍（`run.park.wait_cancelled`）；
#: - `handoffs_reading` → `conductor.watch` / `conductor.ledger` 的 `silent_children`；
#: - `child_wait_invariant` → `conductor.watch` / `conductor.status_report` 的同一名格子。
#: 每一格的"读数里真有它 + 打桩成空就红"由 `tests/test_wiring_readouts.py` 钉住。
#:
#: 2026-10-26（F1a 第 ③ 条，补两条种子来源之后重跑）：台账仍然是空的。补的是入口那一侧
#: （模块级派发表）与字符串接缝（`getattr` 字面量 / `import ... as` 别名），它们只影响
#: "什么算活着的起点/边"，不影响"台账里这几个名字该不该在里面"—— 补完之后可达定义点
#: 从 3868 涨到 4123（全树 4859 个），`webui/readers.py` 从 7/103 涨到 101/103，
#: 而台账与实测两个方向仍然相等。误判的那些名字没有进这张表：它们本来就是活的，
#: 只是当时的图看不见那条线（清单在 `agentflow/temp/F1A-wiring-gained.md`）。
KNOWN_ORPHANS: dict[str, str] = {}

#: 这三个是"只作为读数被读、从不参与控制流"的属性。它们不算孤儿（属性读取算边），
#: 但它们是 `docs/WIRING-AUDIT-2026-10-27.md` 里 a/b 两条的判据本体 —— 单独点名，
#: 免得下一次有人把它们从读数面删掉却没有人发现。
READOUT_ONLY: tuple[str, ...] = ("park_state", "is_park")

#: 台账里同名多定义的那些：名字 -> 为什么仍按名字记账（今天为空）。
#:
#: 为什么需要这一栏：`WIRED` / `KNOWN_ORPHANS` 是按名字记账的，而名字级读数只能问
#: "这个名字有没有一份活定义"。一个名字一旦在树上有两份定义，死的那一份就会被活的那
#: 一份遮住（正是本文件 2026-10-27 晚第二处修的那个漏报方向）。今天 56 个台账名字
#: 每个都只有一处定义，于是名字级读数等于定义级读数；谁破了这条，就得在这里写清
#: 为什么，或者把台账改成按文件记账。
MULTI_DEF_LEDGER_NAMES: dict[str, str] = {}

#: 台账里"按文件解析不出唯一一份、只能退回按名字"的那些：名字 -> 为什么可以接受（今天为空）。
#:
#: 退回那一档会记一条 problem（`resolution_problems`）。台账名字出现这种 problem，
#: 说明这条判据对它又是名字级的了 —— 那等于把刚刚修掉的漏报方向又装回去。
NAME_FALLBACK_OK: dict[str, str] = {}


# ============================================================ 判据

def test_every_monitored_feature_has_a_live_edge() -> None:
    """① 表里每一项都必须有一个"本身可达"的调用点或引用点。"""
    g = graph()
    dead = []
    for name, why in WIRED.items():
        rows = g["defs"].get(name) or []
        assert rows, f"`WIRED` 里的 {name!r} 在 src 里找不到定义点 —— 表过期了"
        got = callers(g, name)
        if not got:
            dead.append(f"{name}（表里写的是：{why}）：0 个非测试调用点")
            continue
        if not is_live(g, name):
            where = "、".join(f"{rel}:{q}:{line}" for rel, q, line, _k in got[:4])
            dead.append(f"{name}（表里写的是：{why}）：有调用点但调用者不可达 {where}")
    assert not dead, (
        "这些功能没有活在真机调用图上（实现好了、没人调）：\n" + "\n".join(dead))


def test_every_ledger_name_is_resolved_by_file_not_by_name() -> None:
    """① 的另一半：台账里每个名字都必须是"按文件解析得出"的，不许靠同名借可达性。

    两个条件一起才够，两条都不许空转：

    - 名字在树上的定义点必须恰好一处：两份定义时名字级读数分不开死的那一份，
      死人会被活人遮住（`is_live` 按 `rel=` 能分开，但台账是按名字记账的）；
    - 这个名字在整张图里不许走到"退回按名字"那一档（`resolution_problems`）。

    两条都按台账两向相等：多一处就红，台账里留一条已经不需要的也红。
    """
    g = graph()
    ledger = list(WIRED) + list(KNOWN_ORPHANS)
    multi = {n: sorted(f"{d['rel']}:{d['qual']}" for d in g["defs"].get(n, ()))
             for n in ledger if len(g["defs"].get(n, ())) > 1}
    assert multi == MULTI_DEF_LEDGER_NAMES, (
        "台账里有名字在树上有不止一处定义 ⇒ 名字级读数会把可达性借给死的那一份。\n"
        f"  实测多定义、台账没写：{sorted(set(multi) - set(MULTI_DEF_LEDGER_NAMES))}\n"
        f"  台账写了、实测只有一处：{sorted(set(MULTI_DEF_LEDGER_NAMES) - set(multi))}\n"
        f"  多定义清单：{multi}")
    borrowed = {p[2]: p[3] for p in resolution_problems(g) if p[2] in set(ledger)}
    assert borrowed == NAME_FALLBACK_OK, (
        "台账里有名字是按名字借出来的（按文件指不到唯一一份）⇒ 漏报方向又回来了。\n"
        f"  实测退回按名字、台账没写：{sorted(set(borrowed) - set(NAME_FALLBACK_OK))}\n"
        f"  台账写了、实测已经按文件解析：{sorted(set(NAME_FALLBACK_OK) - set(borrowed))}\n"
        f"  逐条：{borrowed}")


def test_the_orphan_ledger_equals_what_the_graph_finds() -> None:
    """② 反向：实测孤儿集合必须等于台账（两向都红）。"""
    g = graph()
    found = {name for name in list(WIRED) + list(KNOWN_ORPHANS) if not is_live(g, name)}
    listed = set(KNOWN_ORPHANS)
    assert found == listed, (
        "孤儿台账与实测不符。\n"
        f"  实测是孤儿、台账里没写：{sorted(found - listed)}（有人在不知不觉中让它失去了调用点；"
        "要么接上，要么写进 `KNOWN_ORPHANS` 并说清差哪一根线）\n"
        f"  台账写了孤儿、实测已经有活调用点：{sorted(listed - found)}"
        "（这是接线事件，请把它从 `KNOWN_ORPHANS` 移到 `WIRED` 并写清谁调它）")


def _called_only_from_a_test() -> dict:
    """形态甲：唯一的调用点在一份测试文件里 ⇒ 没有真机入口 ⇒ 这个名字是死的。"""
    return _graph_of([
        ("probe_only_test_calls.py", ast.parse(
            "def orphan_fn():\n    return 1\n")),
        ("tests/test_probe.py", ast.parse(
            "def test_thing():\n    return orphan_fn()\n")),
    ])


def _called_from_a_real_entry() -> dict:
    """形态乙：调用点是 `cli.py` 的 `cmd_*`（真机入口集那一档）⇒ 这个名字是活的。"""
    return _graph_of([
        ("probe_real_entry_calls.py", ast.parse(
            "def real_fn():\n    return 1\n")),
        ("cli.py", ast.parse(
            "def cmd_probe(args):\n    return real_fn()\n")),
    ])


def _the_pair(predicate) -> tuple[bool, bool]:
    """判据本体：同一对语义相反的图、同一套谓词，必须读出"一死一活"。

    正控与反真空共用它：反真空把 `predicate` 换成恒 True（或恒 False），
    这一对读数就塌成一个值，"一死一活"当场不成立 —— 这正是"该判据必红"。
    """
    return (bool(predicate(_called_only_from_a_test(), "orphan_fn")),
            bool(predicate(_called_from_a_real_entry(), "real_fn")))


def test_the_liveness_predicate_is_not_vacuous() -> None:
    """③ 反真空：`is_live` / `reachable` 必须把两种语义相反的 AST 读成不同的结论。

    改前这一条是假反真空（审计 2026-10-27 第三处）：它断的是用例内嵌的 `callees()`
    对两棵合成树都给出 `{"call"}` —— 恒真，`is_live` / `reachable` 一次都没被调用。

    现在两棵树走完整条真判据：`_Collect` 收边、`entries()` 种真机入口、`reachable()`
    顺边闭包、`is_live()` 只看"调用者本身可不可达"：

    - 形态甲：`orphan_fn` 的唯一调用点在一份测试文件里 ⇒ `entries()` 不种它 ⇒ 不可达；
    - 形态乙：`real_fn` 的调用点是 `cli.py` 的 `cmd_probe`（真机入口集那一档）⇒ 可达。

    反真空（本条自己承重）：把谓词打桩成恒 True ⇒ 同一对读数塌成 `(True, True)`，
    第一条断言当场红；恒 False 同理。两条都断，所以"永远说活"和"永远说死"都逃不掉。
    """
    assert _the_pair(is_live) == (False, True), (
        "谓词读不出这两种形态的差别（都说活、或都说死）⇒ 它没在量接线",
        _the_pair(is_live))
    for stub_value in (True, False):
        stub = lambda _g, _name, _value=stub_value: _value   # noqa: E731 - 打桩谓词
        assert _the_pair(stub) != (False, True), (
            f"把谓词打桩成恒 {stub_value} 之后这一对读数仍然一死一活 ⇒ "
            "判据的牙不是从 is_live 那里来的")

    # 入口集与闭包各自也要承重（否则形态乙可能因为别的原因绿）：
    # `cmd_*` 在 `cli.py` 里才是入口，测试文件里的调用点一律不是。
    live_graph = _called_from_a_real_entry()
    assert ("cli.py", "cmd_probe") in entries(live_graph), entries(live_graph)
    assert ("cli.py", "cmd_probe") in reachable(live_graph), sorted(reachable(live_graph))
    assert ("probe_real_entry_calls.py", "real_fn") in reachable(live_graph), \
        sorted(reachable(live_graph))
    dead_graph = _called_only_from_a_test()
    assert ("tests/test_probe.py", "test_thing") not in entries(dead_graph), (
        "测试文件里的调用点被当成真机入口 ⇒ 形态甲那一半恒死不了")
    assert reachable(dead_graph) == set(), sorted(reachable(dead_graph))


def _twins_in_two_files() -> dict:
    """同名但不同文件的一对：`cli.py` 里那一份被入口调着，`probe_twin.py` 里那一份没人调。"""
    return _graph_of([
        ("probe_twin.py", ast.parse(
            "def twin_fn():\n    return 'dead'\n")),
        ("cli.py", ast.parse(
            "def twin_fn():\n    return 'live'\n\n"
            "def cmd_probe(args):\n    return twin_fn()\n")),
    ])


def test_a_same_named_function_in_another_file_cannot_borrow_liveness() -> None:
    """反真空（名字解析那一档）：同名不同文件的一对必须读出一死一活。

    改前 `is_live` 只按名字解析：`twin_fn` 这个名字有活调用点 ⇒ 两份定义一起被读成
    活的，于是"孤儿"与"活着的那条同名函数"在读数上一模一样（漏报方向）。
    改后边按 (文件, 限定名) 收，`is_live(g, name, rel=...)` 把两份定义分开量。

    为什么这是反真空：读者最容易的写法是"两条同名函数都算活"或者"都算死"，
    两种写法都会让下面这一对读成同一个值，第一条断言当场红。
    """
    g = _twins_in_two_files()
    assert {d["rel"] for d in g["defs"]["twin_fn"]} == {"probe_twin.py", "cli.py"}, (
        "夹具没造出「同名但不同文件」的一对")
    assert is_live(g, "twin_fn", rel="cli.py") is True, "活着的那一份被读成了死"
    assert is_live(g, "twin_fn", rel="probe_twin.py") is False, (
        "同名但不同文件的那一份死函数借到了可达性 —— is_live 又退回按名字解析了"
    )
    # 名字级读数（台账的记账单位）为真：活的那一份在。这一条与上面两条一起承重 ——
    # 只断"死的读成死"是不够的，一个恒假的谓词也满足它。
    assert is_live(g, "twin_fn") is True, "名字级读数把活的也读死了"


def test_a_name_that_resolves_to_two_files_is_recorded_as_a_problem() -> None:
    """退回按名字时必须留一条 problem：静默借可达性就是漏报的入口。

    这一条与上一条互为反面：上一条问"分开量得出来吗"，这一条问"分开量不出来的时候
    有没有留痕"。两种形态都不许悄悄过去。
    """
    ambiguous = _graph_of([
        ("probe_a.py", ast.parse("def shared_fn():\n    return 1\n")),
        ("probe_b.py", ast.parse("def shared_fn():\n    return 2\n")),
        ("cli.py", ast.parse("def cmd_probe(args):\n    return shared_fn()\n")),
    ])
    notes = resolution_problems(ambiguous)
    assert any("shared_fn" in note[3] for note in notes), (
        f"同名多定义、按文件指不到唯一一份，却没记 problem：{notes}")
    assert {note[2] for note in notes} == {"shared_fn"}, notes

    # 反真空的另一半：全树唯一的名字不许留 problem，否则台账迟早被噪音淹掉。
    unique = _graph_of([
        ("probe_unique.py", ast.parse("def solo_fn():\n    return 1\n")),
        ("cli.py", ast.parse("def cmd_probe(args):\n    return solo_fn()\n")),
    ])
    assert resolution_problems(unique) == [], resolution_problems(unique)
    assert is_live(unique, "solo_fn", rel="probe_unique.py") is True


def test_a_module_level_dispatch_table_seeds_the_functions_it_names() -> None:
    """反真空（入口集第 4 条，2026-10-26 F1a）：模块级派发表点名的函数必须被种成入口。

    这一段是"表的两种形状"的判据本体，两侧都断：

    - 路由表（`("GET", "/a", "handle_a")`）：字符串常量点到一个同文件定义 ⇒ 可达；
    - 处理器登记表（`{"handle_b": handle_b}`）：键是名字、值是函数对象 ⇒ 可达；
    - 动作表（`(Spec("G", "revise", ...),)`）：值是一个角色动作的实现方法名 ⇒ 同名定义
      都算入口（过近似那一侧，理由见 `_DISPATCH_KINDS`）。

    三条都要有一条反侧：把表里的那个名字改掉 / 把表去掉，同一份定义必须重新变成孤儿 ——
    否则这三条只是在核"有 def 就算活"。
    """
    named = _graph_of([
        ("probe_tables.py", ast.parse(
            "def handle_a():\n    return 1\n\n"
            "def handle_b():\n    return 2\n\n"
            "ROUTES = (('GET', '/a', 'handle_a'),)\n"
            "HANDLERS = {'handle_b': handle_b}\n")),
    ])
    assert is_live(named, "handle_a", rel="probe_tables.py") is True, (
        "路由表点了 handle_a 却没把它种成入口", sorted(entries(named)))
    assert is_live(named, "handle_b", rel="probe_tables.py") is True, (
        "登记表点了 handle_b 却没把它种成入口", sorted(entries(named)))

    # 反侧：表还在，但表里写的名字不在树上 ⇒ 两格都读成死（种子的牙在这一侧）。
    renamed = _graph_of([
        ("probe_tables.py", ast.parse(
            "def handle_a():\n    return 1\n\n"
            "def handle_b():\n    return 2\n\n"
            "ROUTES = (('GET', '/a', 'handle_nowhere'),)\n"
            "HANDLERS = {'handle_nobody': 'handle_elsewhere'}\n")),
    ])
    assert is_live(renamed, "handle_a", rel="probe_tables.py") is False
    assert is_live(renamed, "handle_b", rel="probe_tables.py") is False
    assert not entries(renamed), sorted(entries(renamed))

    # 声明面不许当派发表：`__all__` 那种"一串字符串"不是调用面。
    declared = _graph_of([
        ("probe_decl.py", ast.parse(
            "def exported():\n    return 1\n\n"
            "__all__ = ['exported']\n")),
    ])
    assert is_live(declared, "exported", rel="probe_decl.py") is False, (
        "`__all__` 被当成派发表了 —— 申明了就算活着，这一条判据从此不量接线")


def test_an_action_table_puts_every_same_named_implementation_on_the_graph() -> None:
    """反真空（动作表那一档）：`handler_name` 同名多份时按名字算入口，且这一档是宽的。

    为什么它必须是宽的：`host.build_role_registry` 按角色装配实现类，而
    `ActionSpec.handler_name` 只说"方法叫什么"，不说"在哪个文件" —— 静态指不到唯一一份。
    紧口径在这里会把真实现判成孤儿（实测：`agent_g/revise.py:_Revise.revise`、
    `agent_h/review.py:_Review.review` 这些动作实现在补种子之前都是孤儿）。

    反侧：把动作表去掉，同名两份必须都读成死 —— 否则这条判据是空的。
    """
    with_table = _graph_of([
        ("probe_specs.py", ast.parse(
            "class Spec:\n"
            "    def __init__(self, *args: object, **kw: object) -> None:\n"
            "        pass\n\n"
            "ACTIONS = (Spec('G', 'revise', '改一条', handler_name='revise'),)\n")),
        ("probe_impl_a.py", ast.parse("def revise():\n    return 'a'\n")),
        ("probe_impl_b.py", ast.parse("def revise():\n    return 'b'\n")),
    ])
    assert is_live(with_table, "revise", rel="probe_impl_a.py") is True, (
        "动作表点的名字没被种成入口", sorted(entries(with_table)))
    assert is_live(with_table, "revise", rel="probe_impl_b.py") is True

    without = _graph_of([
        ("probe_specs.py", ast.parse(
            "class Spec:\n"
            "    def __init__(self, *args: object, **kw: object) -> None:\n"
            "        pass\n")),
        ("probe_impl_a.py", ast.parse("def revise():\n    return 'a'\n")),
        ("probe_impl_b.py", ast.parse("def revise():\n    return 'b'\n")),
    ])
    assert is_live(without, "revise", rel="probe_impl_a.py") is False
    assert is_live(without, "revise", rel="probe_impl_b.py") is False


def test_a_getattr_string_literal_is_an_edge() -> None:
    """反真空（字符串接缝，2026-10-26 F1a）：`getattr(obj, "名字")` 里那个字面量要算边。

    `getattr(cond, "open_retire_question", None)` 这种写法在源码里没有调用边 ——
    不把第二实参当边，那一头就是孤儿（而它是真机上唯一会执行到的入口）。

    两条反侧，缺一条这一档就会骗人：
    - 名字是变量（`getattr(obj, name)`）时不算边（那种名字静态看不见，硬算就是编）；
    - 同名多定义时紧口径一个都不给、只留一条 problem（否则一条
      `getattr(args, "run")` 能替全树三十份 `run` 作证）。
    """
    literal = _graph_of([
        ("probe_seam.py", ast.parse("def target_fn():\n    return 1\n")),
        ("cli.py", ast.parse(
            "def cmd_probe(args):\n"
            "    return getattr(object(), 'target_fn', None)\n")),
    ])
    assert is_live(literal, "target_fn", rel="probe_seam.py") is True, (
        "`getattr(..., 'target_fn')` 的字符串没被当成边", resolution_problems(literal))

    variable = _graph_of([
        ("probe_seam.py", ast.parse("def target_fn():\n    return 1\n")),
        ("cli.py", ast.parse(
            "def cmd_probe(args):\n"
            "    name = 'target_fn'\n"
            "    return getattr(object(), name, None)\n")),
    ])
    assert is_live(variable, "target_fn", rel="probe_seam.py") is False, (
        "名字是变量时也算成了边 —— 这一档会替运行时才知道的调用作证")

    ambiguous = _graph_of([
        ("probe_a.py", ast.parse("def dup_fn():\n    return 1\n")),
        ("probe_b.py", ast.parse("def dup_fn():\n    return 2\n")),
        ("cli.py", ast.parse(
            "def cmd_probe(args):\n"
            "    return getattr(object(), 'dup_fn', None)\n")),
    ])
    assert is_live(ambiguous, "dup_fn", rel="probe_a.py") is False, (
        "字符串接缝在同名多定义时借了可达性 ⇒ 一条 getattr 替多份定义作证")
    assert is_live(ambiguous, "dup_fn", rel="probe_b.py") is False
    notes = [note for note in resolution_problems(ambiguous) if note[2] == "dup_fn"]
    assert notes and "按紧口径一个都不给" in notes[0][3], (
        f"紧口径没留 problem ⇒ 这种解析失败会静默过去：{resolution_problems(ambiguous)}")


def test_a_from_import_alias_points_at_the_submodule() -> None:
    """反真空（别名那一档，2026-10-26 F1a）：`from . import mod as M; M.f(...)` 要按文件解析。

    改前这一条两种写法都走不通：`from . import helper as H` 被记成"包里的一个名字"
    （候选是 `__init__.py`），而 `H.helper()` 这条边的名字是 `helper`、`import` 表的键
    是 `H` —— 两个名字对不上，于是永远退回按名字。退回按名字的后果不是"少一条边"，
    而是"同名的那份死函数也借到可达性"（漏报）。下面第四条断言钉的就是那一半。
    """
    g = _graph_of([
        ("mod.py", ast.parse(
            "from . import helper as H\n\n"
            "def run_it():\n"
            "    return H.helper()\n")),
        ("helper.py", ast.parse("def helper():\n    return 'real'\n")),
        ("decoy.py", ast.parse("def helper():\n    return 'decoy'\n")),
        ("cli.py", ast.parse(
            "from . import mod as M\n\n\n"
            "def cmd_probe(args):\n"
            "    return M.run_it()\n")),
    ])
    assert is_live(g, "helper", rel="helper.py") is True, (
        "`H.helper()` 没按别名指到 helper.py", sorted(reachable(g)))
    assert is_live(g, "helper", rel="decoy.py") is False, (
        "同名的那份（decoy.py）借到了可达性 —— 别名那条边又退回按名字了")


def test_every_route_table_handler_is_a_live_entry() -> None:
    """④ 的另一半（2026-10-26 F1a）：路由表 / 登记表点名的那批处理器必须全在图上。

    为什么要这一条：`readers.ROUTES` / `readers.HANDLERS` 是 HTTP 那一侧唯一的入口
    声明。补种子之前这张图只认得出 `webui/readers.py` 里 7 个 def（一份 103 个 def 的
    文件）、`webui/` 下 32 个 `handle_*` 一个都不可达，于是"这一片接上没有"这件事在这个
    判据上读不出来。补之后 101/103（剩下那两个是给契约判据用的类型表
    `ts_fields` / `type_decls`，它们不是 HTTP 入口）、`handle_*` 30/32 —— 差的那两个是
    `WebHandler.handle_one_request` / `handle_unknown`，它们是 `socketserver` 的基类回调
    （标准库按继承调，源码里没有调用点），也不在任何路由表里，所以不在这条判据的范围内。

    这条判据自己也要能被打破：任何一条路由表被改成"算出来的表达式"（不再有字面量
    可种），或某个处理器被从表里删掉，这里就会红 —— 三态写在断言里，不折成"没查成"。
    """
    g = graph()
    kinds = {"routes", "handlers"}
    named = [name for tables in g["dispatch"].values()
             for _line, kind, names in tables if kind in kinds for name in names]
    handlers = [name for name in named if name.startswith("handle_")]
    assert len(handlers) >= 20, (
        f"路由表 / 登记表里只认出 {len(handlers)} 个处理器 ⇒ 这两张表已经不按字面量写了，"
        f"这一条判据读不懂它们（认出的是：{sorted(set(handlers))}）")
    dead = sorted({name for name in handlers if not is_live(g, name)})
    assert not dead, (
        "这些处理器在路由表里点了名、却不在接线图上（表说它有入口，图说它是死的）："
        f"{dead}")


def test_the_clock_module_is_on_the_assembly_list() -> None:
    """④ 工具那一条面：`@tool` 函数必须挂着 tool 装饰器，且它所在模块在 `tools._MODULES` 里。

    为什么不把工具塞进 `WIRED` 那张表：工具在源码里没有调用点（模型按名字取），硬要求
    调用边会把十一件工具全判成孤儿 —— 那是判据错，不是代码错。它们的接线面是装配表。
    `_MODULES` 从源码里的那个元组字面量按 AST 现读（不 import）：它被改成算出来的表达式
    时这一条会以"读不懂装配表"红掉，而不是悄悄通过。
    """
    g = graph()
    modules = _assembly_modules()
    bad: list[str] = []
    for name, module in WIRED_BY_REGISTRY.items():
        rows = g["defs"].get(name) or []
        if not rows:
            bad.append(f"{name}：src 里找不到定义点（表过期了）")
            continue
        if not any("tool" in deco for d in rows for deco in d["decos"]):
            bad.append(f"{name}：不是 `@tool` 函数，注册表拿不到它")
        if module not in modules:
            bad.append(f"{name}：它所在的 {module} 不在 tools._MODULES 里 ⇒ 谁都拿不到")
    assert not bad, "这些工具不在真机工具面上：\n" + "\n".join(bad)


def _assembly_modules() -> set[str]:
    """`tools/__init__.py` 里 `_MODULES` 那个元组字面量（静态读，不 import）。"""
    tree = _parse(SRC / "tools" / "__init__.py")
    for node in tree.body:
        target = None
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            target = node.target.id
        elif isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], ast.Name):
            target = node.targets[0].id
        if target != "_MODULES":
            continue
        value = node.value
        if not isinstance(value, (ast.Tuple, ast.List)):
            raise AssertionError(
                "tools._MODULES 不是元组字面量，这一条判据读不懂它 —— "
                "装配表是接线判据的落点，改成算出来的表达式之前请先改这里")
        return {e.value for e in value.elts
                if isinstance(e, ast.Constant) and isinstance(e.value, str)}
    raise AssertionError("tools/__init__.py 里找不到 _MODULES")

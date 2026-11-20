# -*- coding: utf-8 -*-
"""按门面打桩的名字，其读点必须经门面（静态判据）。

## 为什么要有这一份（VERSPLIT2 留下的静默失效面）

2026-11-20 的 VERSPLIT2 把 `verifications.py` 拆成 18 个 `v_*.py`，门面只做再导出。
拆分时写进每个分文件 docstring 的承诺是：测试 `monkeypatch.setattr(verifications, "X", ...)`
打的只是门面那一格字典，而搬走的代码必须写成 `verifications.<名字>` —— 门面字典在调用那一刻
才查，所以单点打桩仍然到得了实现。`from .v_paths import X` 是快照，补丁到不了。

这条承诺当时只靠「反真空」一条行为判据自证（`test_k14` 的 a′：把锁打桩成
`nullcontext`，读数必须红）。行为反真空有一个空档：它证明的是"这一处打桩生效了"，
不是"每一处被打桩的名字都还查得到桩"。`v_pending_write.py` 里两处裸名读
（`with pending_write_lock(...)` / `_next_pending_verification_id(...)`）就是这么躲过
了 k14：桩打在门面上，实现读的是自己模块的全局，而 a′ 照样"红"（因为夹具把定义处
也打了）—— 但那是夹具在兜底，不是产品纪律。

## 这一份钉的三件事

| # | 判据 | 反真空 |
|---|---|---|
| a | 测试按门面打桩的名字集合（`setattr(VR, "X", ...)`、`monkeypatch.setattr(...)`、`VR.X = ...` 三种写法）里，凡定义在 `v_*.py` 的名字：`src/agentflow` 全树里裸名读点 0 处 | 把 `verifications.X(...)` 改回 `X(...)` ⇒ 必红（见 b 的合成负控；实跑复算见 `temp/vfacade/`） |
| b | 判据自身能咬：合成一个"有裸名读"的模块 ⇒ 检查器必须报出它；改成门面读 ⇒ 必须放行 | 不构造这一条，检查器写坏了也会全绿 |
| c | 每个被打桩、且定义在 `v_*.py` 的名字，至少有一个读点（门面读） | 桩打在一个没人读的名字上，反真空也是假的 |

## 判定口径（为什么不按"名字出现"扫）

`_now_iso` 在 `v_paths.py`、`vsigns.py`、`stopctl.py`、`exhaustionreport.py` 各有一份
同名实现 —— 它们不是同一枚符号。按名字扫会把二十多处无关的本地 helper 误报成
"读 v_paths._now_iso"。所以这里按符号来源判：先解出模块级绑定最终解析到哪个
`v_*.py` 定义，只有同源的裸名读才算。

扫描面是 `src/agentflow` 全树（含 `agent_v/` / `tools/` 等子包），不是只有 18 个分文件；
函数体内的惰性 `from . import verifications as _VR` 也认。
"""
from __future__ import annotations

import ast
import functools
import pathlib
from dataclasses import dataclass, field

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "agentflow"
TESTS = ROOT / "tests"

FACADE = "verifications"
FACADE_FULL = "agentflow." + FACADE


# ---------------------------------------------------------------- 打桩面（tests）


def _facade_aliases(tree: ast.AST) -> set[str]:
    """这份源码里绑到 verifications 模块的名字（含函数内惰性 import 与循环别名）。"""
    out: set[str] = set()
    loops: list[ast.For] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for a in node.names:
                if a.name == FACADE:
                    out.add(a.asname or a.name)
        elif isinstance(node, ast.Import):
            for a in node.names:
                if a.name in (FACADE, FACADE_FULL):
                    out.add(a.asname or FACADE)
        elif isinstance(node, ast.For):
            loops.append(node)
    # `for mod in (定义处, verifications): mod.X = 桩`：k14 的夹具就是这种写法，
    # 只认 `setattr` 会漏掉它（实测：FIXD 的静态普查因此少数了两个名字）。
    changed = bool(loops)
    while changed:
        changed = False
        for node in loops:
            leaves: set[str] = set()
            targets: set[str] = set()

            def walk(t: ast.AST, acc: set[str]) -> None:
                if isinstance(t, ast.Name):
                    acc.add(t.id)
                elif isinstance(t, (ast.Tuple, ast.List)):
                    for e in t.elts:
                        walk(e, acc)

            walk(node.iter, leaves)
            if not (leaves & out):
                continue
            walk(node.target, targets)
            if not targets <= out:
                out |= targets
                changed = True
    return out


def patched_names(tests_root: pathlib.Path) -> dict[str, list[str]]:
    """测试按门面打桩的名字 -> 打桩位置。

    认三种写法：
    - `setattr(VR, "X", ...)` / `monkeypatch.setattr(VR, "X", ...)`
    - `VR.X = ...`（直接赋值；k14 工作进程对 `pending_write_lock` 用的是这一种）
    多行写法（`setattr(` 与 `VR` 不在同一行）也认 —— 按 AST 不看行。
    """
    hits: dict[str, list[str]] = {}
    for path in sorted(tests_root.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        if FACADE not in text:
            # 绑到门面的别名必然在 import 行里写出 `verifications` 这个词；
            # 没有它就不可能按门面打桩。这是扫描面的预筛，不是判据的放宽。
            continue
        tree = ast.parse(text)
        aliases = _facade_aliases(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                if not (isinstance(func, ast.Attribute) and func.attr == "setattr"):
                    continue
                if len(node.args) < 2:
                    continue
                target, name = node.args[0], node.args[1]
                if not (isinstance(target, ast.Name) and target.id in aliases):
                    continue
                if isinstance(name, ast.Constant) and isinstance(name.value, str):
                    hits.setdefault(name.value, []).append(f"{path.name}:{node.lineno}")
            elif isinstance(node, ast.Assign):
                for t in node.targets:
                    if (isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name)
                            and t.value.id in aliases):
                        hits.setdefault(t.attr, []).append(f"{path.name}:{node.lineno}")
    return hits


# ---------------------------------------------------------------- 读点面（src）


def _target_names(node: ast.AST) -> set[str]:
    out: set[str] = set()

    def walk(t: ast.AST) -> None:
        if isinstance(t, ast.Name):
            out.add(t.id)
        elif isinstance(t, (ast.Tuple, ast.List)):
            for e in t.elts:
                walk(e)
        elif isinstance(t, ast.Starred):
            walk(t.value)

    walk(node)
    return out


class _LocalBinder(ast.NodeVisitor):
    """一个函数里所有本地绑定：这些名字的读不是"模块全局读"。"""

    def __init__(self, args: ast.arguments | None = None) -> None:
        self.bound: set[str] = set()
        if args is not None:
            for a in list(args.posonlyargs) + list(args.args) + list(args.kwonlyargs):
                self.bound.add(a.arg)
            if args.vararg:
                self.bound.add(args.vararg.arg)
            if args.kwarg:
                self.bound.add(args.kwarg.arg)

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, (ast.Store, ast.Del)):
            self.bound.add(node.id)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        self.bound |= _target_names(node.target)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if isinstance(node.target, ast.Name):
            self.bound.add(node.target.id)
        self.generic_visit(node)

    def visit_For(self, node: ast.For) -> None:
        self.bound |= _target_names(node.target)
        self.generic_visit(node)

    visit_AsyncFor = visit_For

    def visit_With(self, node: ast.With) -> None:
        for item in node.items:
            if item.optional_vars is not None:
                self.bound |= _target_names(item.optional_vars)
        self.generic_visit(node)

    visit_AsyncWith = visit_With

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        if node.name:
            self.bound.add(node.name)
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        for a in node.names:
            self.bound.add(a.asname or a.name.split(".")[0])

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        for a in node.names:
            if a.name != "*":
                self.bound.add(a.asname or a.name)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.bound.add(node.name)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.bound.add(node.name)

    def visit_Global(self, node: ast.Global) -> None:
        self.bound |= set(node.names)

    def visit_Nonlocal(self, node: ast.Nonlocal) -> None:
        self.bound |= set(node.names)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        return

    def visit_ListComp(self, node: ast.AST) -> None:
        return

    visit_SetComp = visit_ListComp
    visit_DictComp = visit_ListComp
    visit_GeneratorExp = visit_ListComp


class _ReadCollector(ast.NodeVisitor):
    """收集函数体里的模块全局裸名读、门面属性读、函数内 import。"""

    def __init__(self, facade_aliases: set[str]) -> None:
        self.facade_aliases = facade_aliases
        self.scopes: list[set[str]] = []
        self.stack: list[str] = []
        self.reads: list[tuple[str, int, str]] = []
        self.attr_reads: list[tuple[str, int, str, str]] = []
        self.local_imports: list[tuple[str, int, int, str, str]] = []

    def _is_local(self, name: str) -> bool:
        return any(name in scope for scope in self.scopes)

    def _enclosing(self) -> str:
        return self.stack[-1] if self.stack else "<module>"

    def _function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        for d in node.decorator_list:
            self.visit(d)
        # 默认值与注解在 def 那一刻求值（模块作用域）—— 打桩改不到它们，
        # 也不是本判据说的"函数体内的读"，这里不看。
        binder = _LocalBinder(node.args)
        for stmt in node.body:
            binder.visit(stmt)
        self.scopes.append(binder.bound)
        self.stack.append(node.name)
        for stmt in node.body:
            self.visit(stmt)
        self.stack.pop()
        self.scopes.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._function(node)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Lambda(self, node: ast.Lambda) -> None:
        binder = _LocalBinder(node.args)
        binder.visit(node.body)
        self.scopes.append(binder.bound)
        self.stack.append("<lambda>")
        self.visit(node.body)
        self.stack.pop()
        self.scopes.pop()

    def _comprehension(self, node: ast.AST, elts: list[ast.AST]) -> None:
        gens = node.generators  # type: ignore[attr-defined]
        binder = _LocalBinder()
        for gen in gens:
            binder.visit(gen.target)
        for gen in gens:
            self.visit(gen.iter)
            self.visit(gen.target)
            for cond in gen.ifs:
                self.visit(cond)
        self.scopes.append(binder.bound)
        self.stack.append("<comprehension>")
        for elt in elts:
            self.visit(elt)
        self.stack.pop()
        self.scopes.pop()

    def visit_ListComp(self, node: ast.ListComp) -> None:
        self._comprehension(node, [node.elt])

    visit_SetComp = visit_ListComp
    visit_GeneratorExp = visit_ListComp

    def visit_DictComp(self, node: ast.DictComp) -> None:
        self._comprehension(node, [node.key, node.value])

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if isinstance(node.value, ast.Name) and node.value.id in self.facade_aliases:
            self.attr_reads.append((node.attr, node.lineno, self._enclosing(), node.value.id))
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if not self.scopes:
            return  # 模块顶层 import 由 _bindings 负责
        for a in node.names:
            if a.name != "*":
                self.local_imports.append(
                    (a.asname or a.name, node.level, node.lineno, node.module or "", a.name))

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, ast.Load) and not self._is_local(node.id):
            self.reads.append((node.id, node.lineno, self._enclosing()))
        self.generic_visit(node)


def _package_of(mod: str) -> str:
    return ".".join(mod.split(".")[:-1])


def _resolve_relative(level: int, module: str | None, package: str) -> str:
    base = package
    for _ in range(level - 1):
        base = _package_of(base)
    if module:
        return f"{base}.{module}" if base else module
    return base


def _bindings(tree: ast.Module, mod: str) -> dict[str, tuple[str, str, str]]:
    """模块级绑定：本地名 -> (kind, 目标模块全名, 原名)。

    kind：`def` 本模块定义 / `mod` 绑到某个模块对象 / `import` 从别处取的名字。
    遇到 `from . import X` 时按模块处理；它也可能是包里的某个名字，但本判据只关心
    `verifications` 这一格，其余解析不到就返回 None，不猜。
    """
    out: dict[str, tuple[str, str, str]] = {}
    package = _package_of(mod)
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out[node.name] = ("def", mod, node.name)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for t in targets:
                for name in _target_names(t):
                    out[name] = ("def", mod, name)
        elif isinstance(node, ast.ImportFrom):
            base = _resolve_relative(node.level, node.module, package) if node.level \
                else (node.module or "")
            if not node.module:
                for a in node.names:
                    child = f"{base}.{a.name}" if base else a.name
                    out[a.asname or a.name] = ("mod", child, "")
            else:
                for a in node.names:
                    out[a.asname or a.name] = ("import", base, a.name)
        elif isinstance(node, ast.Import):
            for a in node.names:
                out[a.asname or a.name.split(".")[-1]] = ("mod", a.name, "")
    return out


@dataclass
class Audit:
    """一次静态普查的读数。空 `bare` 且每个名字都有门面读点 = 成立。"""

    names: dict[str, list[str]] = field(default_factory=dict)     # 打桩名 -> 打桩位置
    vdefs: dict[str, str] = field(default_factory=dict)           # 名字 -> 定义它的 v_* 模块
    bare: dict[str, list[str]] = field(default_factory=dict)      # 名字 -> 裸名读点
    facade: dict[str, list[str]] = field(default_factory=dict)    # 名字 -> 门面读点
    scanned_modules: int = 0


def _module_key(path: pathlib.Path, package_root: pathlib.Path) -> str:
    rel = path.relative_to(package_root).as_posix()
    return "agentflow." + rel[:-3].replace("/", ".")


def audit(package_root: pathlib.Path = SRC, tests_root: pathlib.Path = TESTS) -> Audit:
    """扫 `package_root`（agentflow 包目录）与 `tests_root`，给出逐名读数。"""
    return _audit(package_root, tests_root)


@functools.lru_cache(maxsize=None)
def _audit(package_root: pathlib.Path, tests_root: pathlib.Path) -> Audit:
    """`audit` 的实现（按路径缓存：四条判据共用一次全树 AST 解析）。"""
    result = Audit(names=patched_names(tests_root))
    paths = {_module_key(p, package_root): p for p in sorted(package_root.rglob("*.py"))
             if "__pycache__" not in p.parts}
    result.scanned_modules = len(paths)
    trees: dict[str, ast.Module] = {}
    binds: dict[str, dict[str, tuple[str, str, str]]] = {}
    tokens = tuple(result.names)
    for mod, path in paths.items():
        text = path.read_text(encoding="utf-8")
        if tokens and not any(name in text for name in tokens):
            # 一个被打桩名字的读点必然把那个名字写出来；名字都不出现的模块不可能读它。
            # 这是扫描面的预筛（省掉与判据无关的 300+ 份文件的 AST），不是判据的放宽。
            continue
        tree = ast.parse(text)
        trees[mod] = tree
        binds[mod] = _bindings(tree, mod)

    for mod, table in binds.items():
        if not mod.split(".")[-1].startswith("v_"):
            continue
        for name, (kind, _target, _orig) in table.items():
            if kind == "def":
                result.vdefs.setdefault(name, mod)

    def resolve(mod: str, name: str, seen: set[tuple[str, str]] | None = None
                ) -> tuple[str, str, str] | None:
        seen = seen if seen is not None else set()
        if (mod, name) in seen:
            return None
        seen.add((mod, name))
        binding = binds.get(mod, {}).get(name)
        if binding is None:
            return None
        kind, target, orig = binding
        if kind == "def":
            return ("def", mod, name)
        if kind == "mod":
            return ("mod", target, "")
        following = binds.get(target, {}).get(orig)
        if following is None:
            return ("import", target, orig)
        return resolve(target, orig, seen)

    for mod, tree in trees.items():
        collector = _ReadCollector(_facade_aliases(tree))
        for stmt in tree.body:
            collector.visit(stmt)
        for local, lineno, enclosing in collector.reads:
            origin = resolve(mod, local)
            if origin is None or origin[0] != "def":
                continue
            name = origin[2]
            if name not in result.names or origin[1] != result.vdefs.get(name):
                continue
            result.bare.setdefault(name, []).append(
                f"{mod}:{lineno}（{enclosing} 里读裸名 {local}）")
        for local, level, lineno, module_name, orig in collector.local_imports:
            base = _resolve_relative(level, module_name or None, _package_of(mod)) \
                if level else module_name
            origin = resolve(base, orig) if base else None
            if origin is None or origin[0] != "def" or origin[2] not in result.names:
                continue
            if origin[1] != result.vdefs.get(origin[2]):
                continue
            result.bare.setdefault(origin[2], []).append(
                f"{mod}:{lineno}（{local} 是函数内 import 的快照）")
        for attr, lineno, enclosing, alias in collector.attr_reads:
            if attr in result.names:
                result.facade.setdefault(attr, []).append(
                    f"{mod}:{lineno}（{enclosing} 里读 {alias}.{attr}）")
    return result


# ---------------------------------------------------------------- 判据


def test_no_read_of_a_facade_patched_name_goes_bare():
    """被打桩、且定义在 v_* 的名字：全树裸名读点 0 处。"""
    reading = audit()
    assert reading.vdefs, "v_* 里一个定义都没解析出来 ⇒ 判据失去对象（不是通过）"
    problems: list[str] = []
    for name, where in sorted(reading.bare.items()):
        problems.append(
            f"{name}（定义 {reading.vdefs.get(name)}）还有裸名读点 —— "
            f"打桩打在门面 `verifications.{name}` 上到不了这里：\n    "
            + "\n    ".join(where))
    assert problems == [], "\n\n".join(problems)


def test_every_patched_name_has_at_least_one_facade_read_point():
    """桩打的名字必须真的有人在门面上读它，否则这条反真空本身是空转。"""
    reading = audit()
    vacuous = sorted(name for name in reading.names
                     if name in reading.vdefs and not reading.facade.get(name))
    assert vacuous == [], (
        "这些名字被测试按门面打桩，但 src 里没有任何 `verifications.<名字>` 读点 ⇒ "
        f"打桩改了没人读的一格：{vacuous}")


def test_the_name_set_covers_the_three_stub_forms_and_the_whole_tree():
    """判据自己的扫描面不许塌：三种打桩写法都要抽得到，扫的模块数不许退回只扫分文件。"""
    reading = audit()
    assert "pending_write_lock" in reading.names, (
        "抽不到 `VR.X = ...` 直接赋值（k14 工作进程的写法）⇒ 静态判据会漏掉那两格")
    assert "_issued_verification_pointer" in reading.names, (
        "抽不到跨行写法的 `monkeypatch.setattr(` + 下一行的 `VR, \"X\"` ⇒ 集合少数一个")
    assert len(reading.names) >= 30, f"打桩名只抽到 {len(reading.names)} 个，抽取逻辑坏了"
    assert reading.scanned_modules >= 200, (
        f"只扫到 {reading.scanned_modules} 个模块 ⇒ 扫描面塌了（本判据要扫 src/agentflow 全树）")


# ---------------------------------------------------------------- 判据自己的反真空


_SYNTHETIC_STUBS = '''\
from agentflow import verifications as VR

def test_stub(monkeypatch):
    monkeypatch.setattr(VR, "lock", lambda root: None)
'''

_SYNTHETIC_BARE = '''\
# -*- coding: utf-8 -*-
def lock(root):
    return root

def use(root):
    with lock(root):
        return 1
'''

_SYNTHETIC_FACADE = '''\
# -*- coding: utf-8 -*-
from . import verifications

def lock(root):
    return root

def use(root):
    with verifications.lock(root):
        return 1
'''


_SYNTHETIC_SNAPSHOT = '''\
# -*- coding: utf-8 -*-
from .v_demo import lock

def use(root):
    with lock(root):
        return 1
'''

_SYNTHETIC_FUNC_IMPORT = '''\
# -*- coding: utf-8 -*-
def use(root):
    from .v_demo import lock as _lock
    with _lock(root):
        return 1
'''

_SYNTHETIC_NAMESAKE = '''\
# -*- coding: utf-8 -*-
def lock(root):
    return root

def use(root):
    with lock(root):
        return 1
'''


def _synthetic(tmp_path: pathlib.Path, module_text: str,
               extra: dict[str, str] | None = None) -> Audit:
    package = tmp_path / "agentflow"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "v_demo.py").write_text(module_text, encoding="utf-8")
    for name, text in (extra or {}).items():
        (package / f"{name}.py").write_text(text, encoding="utf-8")
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_stub.py").write_text(_SYNTHETIC_STUBS, encoding="utf-8")
    return audit(package, tests)


def test_the_checker_catches_a_bare_read_and_accepts_the_facade_read(tmp_path):
    """反真空（判据自证）：裸名读必须被咬住；改成 `verifications.lock` 必须放行。

    这一条不碰产品树：它在 tmp_path 里造一份"有裸名读"的分文件，证明检查器不是
    恒绿的空转。实跑复算（把产品里那两处改回裸名 ⇒ 本文件红）见 `temp/vfacade/`。
    """
    bare = _synthetic(tmp_path / "bare", _SYNTHETIC_BARE)
    assert bare.bare.get("lock"), (
        "合成的裸名读没被咬住 ⇒ 检查器坏了，上面那条全绿不算数")
    assert any("agentflow.v_demo:6" in where for where in bare.bare["lock"]), bare.bare["lock"]

    fixed = _synthetic(tmp_path / "fixed", _SYNTHETIC_FACADE)
    assert not fixed.bare, f"门面读被误判成裸名读：{fixed.bare}"
    assert fixed.facade.get("lock"), "门面读没被计数 ⇒ 上面那条'至少一个读点'会假红"

    # `from .v_demo import lock` 是快照：门面打桩同样到不了这一处，必须咬住。
    snapshot = _synthetic(tmp_path / "snapshot", _SYNTHETIC_FACADE,
                          extra={"consumer": _SYNTHETIC_SNAPSHOT})
    assert snapshot.bare.get("lock"), (
        "模块级 import 的快照没被咬住 ⇒ 只认函数体内的裸名读，漏一类")

    # 函数体内的惰性 import 也是快照（VERSPLIT2 之后 v_* 之间的常见写法）。
    local = _synthetic(tmp_path / "local", _SYNTHETIC_FACADE,
                       extra={"consumer": _SYNTHETIC_FUNC_IMPORT})
    assert local.bare.get("lock"), (
        "函数内 import 的快照没被咬住 ⇒ 惰性 import 那一支是空的")
    assert any("函数内 import" in where for where in local.bare["lock"]), local.bare["lock"]

    # 同名不同源不算：另一个模块自己定义的 `lock` 与 `v_demo.lock` 是两枚符号。
    namesake = _synthetic(tmp_path / "namesake", _SYNTHETIC_FACADE,
                          extra={"helper": _SYNTHETIC_NAMESAKE})
    flagged = [where for where in namesake.bare.get("lock", []) if "helper" in where]
    assert not flagged, (
        "把同名不同源的本地 helper 误报成读 v_demo.lock ⇒ 按名字扫的假阳性又回来了："
        f"{flagged}")


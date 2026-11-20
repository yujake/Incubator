# -*- coding: utf-8 -*-
"""② 裸构造点判据：能登记 / 改台账的路径上，秘书必须带缝。

## 这一条钉的是什么

命题同一性判定的整条链在 2026-10-26 的真机 sylow5 上是死的：`if self.seam is None`
那一道闸把每一次判定折成"没有判断面"，于是同一条定理被登记 2–3 次，而
`out/secretary/proposition_verdicts.jsonl` 一次都没被建出来（`secretary.seam_for_secretary`
的 docstring 逐字记着那五个构造点）。单测当时全绿 —— 因为每一处判据都自己塞了一条假缝。
断的不是判据，是"装配线"；所以这里按源码扫装配点。

## 判据（三层，缺一层都不成立）

1. 登记路径上的裸构造一律红：模块里只要能调到
   `record_statement` / `land_statement` / `amend_statement_meta` 这三件里的任何一件
   （`REGISTRATION_METHODS`），它里面就不许出现"没带缝"的 `Secretary(...)` /
   `for_role(...)`（`for_role` 不传 `seam=` 时与裸构造同义）。
2. 其余裸构造逐个登记理由：`_EXEMPT` 是"确实不需要缝"的白名单（只取 `child_counts`
   的 `statusreport.py` / `webui/readers.py`、工厂函数本体、模块自检探针、只读
   `surface_of` 的那一处、只转发交接的 `_peer_secretary`）。白名单与实际"逐条对表"
   （多一条、少一条都红）—— 一张永不生效的豁免表会腐烂成"看起来还在挡着什么"。
3. 反真空：把 `agent_b/core.py::_Core._statement_secretary` 的 `for_role_wired(...)`
   换成裸 `Secretary(...)`，本判据必须红（见 `test_anti_vacuum_...`）；同时正面钉住
   "它今天是带缝的"—— 否则"没有违规"可能只是"什么都没扫到"。

"带缝"的两种合法写法（与业主 2026-11-08 的措辞一致）：
`for_role_wired(...)`，或 `for_role(...)` / `Secretary(...)` 显式带 `seam=`（值可以是
`None`：`conceptrows._concept_secretary` 写明"这一名秘书从不对命题判词"，那是声明，
不是遗漏）。
"""
from __future__ import annotations

import ast
import pathlib
import warnings
from dataclasses import dataclass

ROOT = pathlib.Path(__file__).resolve().parents[1] / "src" / "agentflow"

#: "能登记 / 改台账"的三件秘书方法（判据只认这三件；`write_concept_row` 是概念那条路，
#: 它显式带 `seam=None` 并写明理由，走第 3 条白名单之外的合法写法）。
REGISTRATION_METHODS: tuple[str, ...] = (
    "record_statement", "land_statement", "amend_statement_meta")


@dataclass(frozen=True)
class Site:
    """一个装配点：`kind` = `wired` / `for_role` / `bare`；`seam=True` = 显式带 `seam=`。"""

    module: str
    line: int
    kind: str
    seam: bool
    qualname: str

    @property
    def wired(self) -> bool:
        """这一次构造有没有判断面（`for_role_wired`，或显式 `seam=`）。"""
        return self.kind == "wired" or self.seam

    @property
    def key(self) -> tuple[str, str]:
        return (self.module, self.qualname)


#: 白名单：逐条登记"确实不需要缝"的裸构造点，每一条都写清凭什么。
#: 键 = `(模块相对路径, 构造点所在函数/方法的 qualname)`；`selftest` 里有两个构造点，
#: 共用一个键（同一个理由）。
_EXEMPT: dict[tuple[str, str], str] = {
    ("secretary.py", "for_role"):
        "工厂本体：它把 `**kw` 原样交给 `Secretary(...)`，塞不塞缝由调用方决定"
        "（生产调用方 `agent_loop._secretary_for` 显式传 `seam=`；要判命题的调用方走"
        "`for_role_wired`）。",
    ("secretary.py", "Secretary._peer_secretary"):
        "只给转发链的下一跳造一名秘书，由 `relay_out` / `relay_in` 写一条 `relay_hop` "
        "记录；不碰 `statements`、不判命题（它只按 '代表别人' 那一档调 "
        "`bind_task(task_id, mark_alive=False)`：只分片、不写存活标记，见方法 docstring）。",
    ("secretary.py", "selftest"):
        "模块自检探针：只在 `python -m agentflow.secretary` 那一支里造两名临时秘书，"
        "验台账分片 / 存活读数，不判命题。",
    ("agent_loop.py", "LlmBackend.call"):
        "只调 `surface_of(...)` 读这一行的读写面（S1n-b/c），紧跟着就丢弃这名秘书；"
        "不判命题、不写 `statements`。",
    ("statusreport.py", "collect"):
        "只取 `child_counts()`（名册两个读数），口径只有 `Secretary.child_counts` 一处；"
        "从不调 `adjudicate_proposition`。",
    ("webui/readers.py", "_closing_runtime"):
        "只取 `child_counts()`（收工区块显示『名下还有几个未收尾的子项』），与 "
        "`statusreport.py` 同形。2026-11-20 对表（FN200 拆分）：`_closing_block` 已被拆成 "
        "`_closing_gates` / `_closing_machine` / `_closing_sessions` / `_closing_last_at` / "
        "`_closing_cost` / `_closing_runtime` / `_closing_content`（拆分后 `_closing_block` "
        "只剩装配，逐块调上面这几个），而那句裸构造跟着它唯一做的事（`child_counts()`）"
        "整体搬进了 `_closing_runtime` —— 豁免语义没有拆散（仍是一处只读名册的裸构造），"
        "所以仍是一条登记，只把键换到新单元名下；旧键 `_closing_block` 今天已不含任何"
        "构造点，继续挂着就是一条永不生效的豁免。",
}


def _secretary_names(tree: ast.AST) -> tuple[set[str], set[str], set[str], set[str]]:
    """这个文件里与"造秘书"有关的名字：类名 / `for_role` / `for_role_wired` / 模块别名。

    别名也要认（`from .secretary import Secretary as _Secretary`、
    `from . import secretary as SEC`、`import agentflow.secretary as S`）：
    改个名不该成为绕过护栏的路。
    """
    classes = {"Secretary"}          # 本模块定义 `class Secretary` 时也用它造实例
    for_role: set[str] = set()
    wired: set[str] = set()
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            mod = str(node.module or "")
            if mod.split(".")[-1] == "secretary":
                for one in node.names:
                    if one.name == "Secretary":
                        classes.add(one.asname or one.name)
                    elif one.name == "for_role":
                        for_role.add(one.asname or one.name)
                    elif one.name == "for_role_wired":
                        wired.add(one.asname or one.name)
            elif mod in ("", "agentflow"):
                for one in node.names:
                    if one.name == "secretary":
                        modules.add(one.asname or one.name)
        elif isinstance(node, ast.Import):
            for one in node.names:
                if one.name.split(".")[-1] == "secretary":
                    modules.add(one.asname or "secretary")
    return classes, for_role, wired, modules


def _qualnames(tree: ast.AST) -> dict[int, str]:
    """每个函数 / 类节点的 qualname（`_Core._statement_secretary` 这种）。"""
    out: dict[int, str] = {}

    def walk(node: ast.AST, stack: list[str]) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                out[id(child)] = ".".join(stack + [child.name])
                walk(child, stack + [child.name])
            else:
                walk(child, stack)

    walk(tree, [])
    return out


def _spans(tree: ast.AST) -> list[tuple[int, int, int, str]]:
    """所有函数 / 类的行区间 `(起点, 终点, 长度, qualname)`；`_enclosing` 只查这一张表。

    每个模块只建一次：按调用点逐次 `ast.walk` 整棵树在 `secretary.py` 这种一万三千行
    的文件上会把一条判据拖成几十秒，而"护栏跑得慢"的下一步就是"护栏被跳过"。
    """
    names = _qualnames(tree)
    out: list[tuple[int, int, int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        name = names.get(id(node), node.name)
        out.append((node.lineno, node.end_lineno or node.lineno, len(name), name))
    return out


def _enclosing(spans: list[tuple[int, int, int, str]], line: int) -> str:
    """`line` 落在哪个函数 / 类里（取最内层即 qualname 最长的那一层；模块级为空串）。"""
    best, best_len = "", 0
    for start, end, length, name in spans:
        if start <= line <= end and length > best_len:
            best, best_len = name, length
    return best


def _parse(text: str) -> ast.AST:
    """`ast.parse` 包一层：压掉历史源码里 `"\\d"` 一类转义带来的告警（不是本判据的读数）。"""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return ast.parse(text)


def _mentions_assembly(text: str) -> bool:
    """这份源码有没有可能"造秘书"（先做字面预筛，免得把一万行的文件全解析一遍）。"""
    return "Secretary" in text or "for_role" in text


def _sites(sources: dict[str, str]) -> list[Site]:
    """扫一遍给定的源码映射：`{相对路径: 源码}` ⇒ 全部装配点。"""
    found: list[Site] = []
    for module, text in sorted(sources.items()):
        if not _mentions_assembly(text):
            continue
        tree = _parse(text)
        classes, for_role, wired, modules = _secretary_names(tree)
        spans = _spans(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            kind = ""
            if isinstance(func, ast.Name) and func.id in classes:
                kind = "bare"
            elif isinstance(func, ast.Name) and func.id in wired:
                kind = "wired"
            elif isinstance(func, ast.Name) and func.id in for_role:
                kind = "for_role"
            elif isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
                base = func.value.id
                if base in modules and func.attr == "for_role_wired":
                    kind = "wired"
                elif base in modules and func.attr == "for_role":
                    kind = "for_role"
            if not kind:
                continue
            found.append(Site(
                module=module, line=node.lineno, kind=kind,
                seam=any(one.arg == "seam" for one in node.keywords),
                qualname=_enclosing(spans, node.lineno)))
    return found


def _registration_modules(sources: dict[str, str]) -> set[str]:
    """能调到 `record_statement` / `land_statement` / `amend_statement_meta` 的模块。"""
    out: set[str] = set()
    for module, text in sources.items():
        if not any(one in text for one in REGISTRATION_METHODS):
            continue
        tree = _parse(text)
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr in REGISTRATION_METHODS):
                out.add(module)
                break
    return out


def _load_sources() -> dict[str, str]:
    return {path.relative_to(ROOT).as_posix(): path.read_text(encoding="utf-8")
            for path in sorted(ROOT.rglob("*.py"))}


#: 整棵树的读数只算一次（两条判据读的是同一份扫描；各扫一遍是"同一读数两个主人"）。
_CACHE: dict[str, object] = {}


def _all_sites() -> list[Site]:
    if "sites" not in _CACHE:
        _CACHE["sites"] = _sites(_load_sources())
    return list(_CACHE["sites"])  # type: ignore[arg-type]


def _all_registration_modules() -> set[str]:
    if "registration" not in _CACHE:
        _CACHE["registration"] = _registration_modules(_load_sources())
    return set(_CACHE["registration"])  # type: ignore[arg-type]


def test_only_read_only_secretaries_may_be_bare():
    """全仓扫描：登记路径上的裸构造 0 处；其余裸构造逐条在白名单里（且白名单不多不少）。"""
    sites = _all_sites()
    assert len(sites) >= 20, f"只扫到 {len(sites)} 个装配点 ⇒ 护栏没生效"
    bare = [one for one in sites if not one.wired]
    got = {one.key for one in bare}
    assert got == set(_EXEMPT), (
        "裸构造点与白名单对不上（多出来的是新漏的线，少掉的是该撤的豁免）：\n"
        f"  实际 {sorted(got)}\n  登记 {sorted(_EXEMPT)}")
    # 白名单不许拿来放行"能登记 / 改台账"的模块：那条路只认 `for_role_wired` / 显式 seam=
    registration = _all_registration_modules()
    assert {"agent_b/register_statement.py", "tools/table_tools.py"} <= registration, (
        f"登记路径的模块集合变了（判据要跟着复核）：{sorted(registration)}")
    excused = sorted(module for module, _ in _EXEMPT)
    assert not (set(excused) & registration), (
        f"这些模块能登记 / 改台账，却被登记成『不需要缝』：{sorted(set(excused) & registration)}")
    # 逐条：裸构造点必须不在登记路径上（理由见 `_EXEMPT` 每一条）
    bad = [f"{one.module}:{one.line} {one.qualname}" for one in bare
           if one.module in registration]
    assert not bad, "登记路径上出现裸构造（真机 sylow5 的死链就是这么来的）：\n" + "\n".join(bad)


def test_positive_controls_are_still_wired():
    """正面钉住三处：B 的秘书、写侧的两条路、以及"确实扫到了"这个读数。"""
    sites = _all_sites()
    wired = {(one.module, one.qualname) for one in sites if one.wired}
    assert ("agent_b/core.py", "_Core._statement_secretary") in wired, (
        "B 的 `_statement_secretary` 不再是 `for_role_wired` ⇒ 命题同一性判定在这一支上"
        "永远没有判断面（真机 sylow5 的根因）")
    assert sum(1 for one in sites
               if one.module == "tools/table_tools.py" and one.wired) == 3, (
        "`tools/table_tools.py` 的写侧装配点少了（`_route_to_secretary` ×2 + `_selftest` ×1）")
    assert sum(1 for one in sites if one.module == "agent_b/core.py") == 1
    assert sum(1 for one in sites if one.wired) >= 15


def test_anti_vacuum_bare_statement_secretary_is_caught():
    """反真空：把 `agent_b/core.py:143` 的 `for_role_wired` 换成裸 `Secretary(...)` ⇒ 红。"""
    core = (ROOT / "agent_b" / "core.py").read_text(encoding="utf-8")
    neighbour = (ROOT / "agent_b" / "register_statement.py").read_text(encoding="utf-8")
    original = 'for_role_wired("B", root=self.store.root, store=self.store)'
    assert original in core, "反真空的前提变了：`agent_b/core.py` 里那一行不是预期写法"
    mutated = core.replace(original,
                           'Secretary("B", root=self.store.root, store=self.store)')
    assert mutated != core
    # 正控：原样 ⇒ 这一处不是裸构造、也不在白名单里
    assert not [one for one in _sites({"agent_b/core.py": core,
                                       "agent_b/register_statement.py": neighbour})
                if one.key == ("agent_b/core.py", "_Core._statement_secretary")
                and not one.wired]
    # 反真空：换成裸构造 ⇒ 被点到名（且它不在白名单里）
    caught = [one for one in _sites({"agent_b/core.py": mutated,
                                     "agent_b/register_statement.py": neighbour})
              if one.key == ("agent_b/core.py", "_Core._statement_secretary")
              and not one.wired]
    assert caught, "把 B 的 `for_role_wired` 换成裸 `Secretary(...)` 之后护栏没红 ⇒ 反真空失败"
    assert ("agent_b/core.py", "_Core._statement_secretary") not in _EXEMPT

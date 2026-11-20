# -*- coding: utf-8 -*-
"""按声明定位秘书的名字：打桩要打在那份模块的定义处，而不是再导出那一格。

## 为什么需要这一处（刀3 收口时露出来的）

`secretary.py` 对搬走的名字做再导出（`from .secretary_tier_ledger import nontriviality_of`）。
再导出之后，`SEC.nontriviality_of` 与 `agentflow.secretary_tier_ledger.nontriviality_of`
是同一个函数对象，但不是同一格名字绑定：`monkeypatch.setattr(SEC, "nontriviality_of", fake)`
只改 `secretary.py` 的全局，而真正调用它的那份模块里的全局仍是原函数。

不只再导出那一格：搬家之后模块之间也互相 import（`secretary_roster_write` 从
`secretary_ledger` import `roster_pending`），那一份也有自己的绑定。所以打桩要打在
家族里所有"当前绑着原对象"的模块全局上 —— 少打一处，反真空判据就会静默变成
"打桩没生效而判据仍绿"，那正是本仓反复踩的那个形态。

## 口径

`home(name)` 按 `__module__` 定位定义处（函数/类都有）；常量没有 `__module__`，那种情况
报错而不是猜 —— 猜错了就会静默打在再导出那一格上，正是本模块要防的事。
`rebind(name, value)` 换掉全部绑定并返回还原函数；`patch(monkeypatch, name, value)` 是它的
monkeypatch 版本（pytest 负责还原）。
"""
from __future__ import annotations

import importlib
import pathlib
import sys

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agentflow import secretary as SEC  # noqa: E402 — 先修 sys.path 才能 import

MISSING = object()


def family_modules():
    """秘书家族的全部已导入模块（`secretary.py` 在 import 时就 import 了它们全部）。"""
    pkg = importlib.import_module("agentflow")
    out = []
    for name in sorted(dir(pkg)):
        if not name.startswith("secretary"):
            continue
        mod = getattr(pkg, name)
        if getattr(mod, "__name__", "").startswith("agentflow.secretary"):
            out.append(mod)
    return out


def home(name: str):
    """这个秘书名字的定义模块（`agentflow.secretary_*`）。"""
    obj = getattr(SEC, name)
    mod = str(getattr(obj, "__module__", "") or "")
    if not mod.startswith("agentflow.secretary"):
        raise AssertionError(
            f"{name!r} 不在 secretary 家族里定义（__module__={mod!r}）⇒ 打桩位置无从定位")
    return importlib.import_module(mod)


def module_rel(qualname: str) -> str:
    """定义这个声明的那份源码的仓库相对路径（`src/agentflow/secretary_*.py`）。

    给"按 (模块, qualname) 对表"的静态判据用：它们原先写死 `src/agentflow/secretary.py`，
    搬家之后那一格对不上，红的是"文件名变了"，不是"多了一个写点"。
    """
    return f"src/agentflow/{source_of(qualname)[0]}"


def rebind(name: str, value):
    """把家族里所有绑着 `name` 原对象的模块全局换成 `value`；返回还原函数。"""
    orig = getattr(SEC, name)
    hit = []
    for mod in family_modules():
        if vars(mod).get(name, MISSING) is orig:
            hit.append(mod)
    if not hit:
        raise AssertionError(f"{name!r} 在家族里一格绑定都没有 ⇒ 打桩会打在空气上")
    for mod in hit:
        setattr(mod, name, value)

    def restore() -> None:
        for mod in hit:
            setattr(mod, name, orig)
    return restore


def patch(monkeypatch, name: str, value, *, raising: bool = True):
    """把桩打在这个名字的全部绑定上（每一格都登记给 monkeypatch，pytest 负责还原）。"""
    orig = getattr(SEC, name, MISSING)
    if orig is MISSING:
        if raising:
            raise AttributeError(f"{name!r} 不在 `agentflow.secretary` 上 ⇒ 打桩会打在空气上")
        return value
    hit = [mod for mod in family_modules() if vars(mod).get(name, MISSING) is orig]
    if not hit and raising:
        raise AssertionError(f"{name!r} 在家族里一格绑定都没有 ⇒ 打桩会打在空气上")
    for mod in hit:
        monkeypatch.setattr(mod, name, value, raising=raising)
    return value


def source_of(qualname: str) -> tuple[str, str]:
    """定义这个声明的那一份源码 `(文件名, 全文)`。

    给"按文件读源码"的判据用：它们原先写死 `secretary.py`，搬家之后红的是"这段文字不在
    这个文件名里"，不是行为变了。按声明定位之后，判据仍然只读那一份（不是放宽成整包扫描
    —— 提示词里重复的同一句会把判据喂饱）。
    """
    import ast

    want = qualname.split(".")[-1]
    pkg = _SRC / "agentflow"
    for path in sorted(pkg.glob("secretary*.py")):
        text = path.read_text(encoding="utf-8")
        for node in ast.walk(ast.parse(text)):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == want:
                return path.name, text
    raise AssertionError(f"秘书家族里找不到 {qualname} 的声明 ⇒ 判据失去对象")


def family_text() -> str:
    """秘书家族全部分文件的源码（拼接）。

    给"某段文字/某个字段在秘书源码里必须 0 处"那一类判据用：那几个字段若被重新写进来，
    写在哪一份分文件里都算数。
    """
    pkg = _SRC / "agentflow"
    parts = []
    for path in sorted(pkg.glob("secretary*.py")):
        parts.append(f"# ---- {path.name}\n" + path.read_text(encoding="utf-8"))
    return "\n".join(parts)

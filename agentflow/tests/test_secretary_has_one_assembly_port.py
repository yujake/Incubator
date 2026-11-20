# -*- coding: utf-8 -*-
"""判据：造一名 `Secretary` 只经装配口（业主批准 SECSPLIT2 的破环方式②）。

## 这一条钉的是什么

刀3–刀6 把 `class Secretary` 的 193 个方法搬进混入类，而混入类里仍有两处要造秘书：
`_peer_secretary`（转发链的下一跳）与 `concept_identity_gate`（概念闸的确定性判定）。
混入模块里写 `from .secretary import Secretary` 就是混入层反向 import 组装层；组装层为了
再导出又必须 import 混入模块 —— 两个方向同时成立，`import agentflow.secretary` 当场
ImportError。把 import 塞进函数体可以绕过环，但那会改 `ast_sha`（逐字等价当场红），
而且把依赖方向藏进运行时。

装配口把"造哪一门子"的答案挂在类上：`Secretary._new_secretary` 指向
`secretary_port.new_secretary`，真身只认 `secretary.py` 在模块级登记的那一个类。

## 五条（前四条结构、第五条反真空）

| 条 | 它要证明的事 |
|---|---|
| a | `class Secretary` 只在 `secretary.py` 里定义一次（类没有被拆成两个） |
| b | 除 `secretary.py` 外，任何 `secretary*.py` 都不出现 `Secretary(`（混入层不造类） |
| c | `_peer_secretary` 的方法体只经 `self._new_secretary(...)`，不出现 `Secretary(` |
| d | `concept_identity_gate` 的函数体只经 `new_secretary(...)`，不出现 `Secretary(` |
| e | 反真空：把 `secretary_port._FACTORY` 摘掉之后，`Secretary._new_secretary(...)` 必须抛错 |

e 是这一条的真空防线：如果谁把 `_new_secretary` 就地改写成 `return Secretary(...)`，
它照样能造出秘书，而装配口已经是死代码 —— 摘掉 `_FACTORY` 之后它不会抛，本判据红。
"""
from __future__ import annotations

import ast
import pathlib
import sys

import pytest

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agentflow import secretary as SEC
from agentflow import secretary_port as PORT

PKG = pathlib.Path(__file__).resolve().parents[1] / "src" / "agentflow"
FAMILY = sorted(PKG.glob("secretary*.py"))


def _sources() -> dict[str, str]:
    return {p.name: p.read_text(encoding="utf-8") for p in FAMILY}


def _method_segment(text: str, qualname: str) -> str:
    """按声明定位那个方法/函数，回它自己的源码段（不按整文件读）。"""
    tree = ast.parse(text)
    want = qualname.split(".")[-1]
    for cls in [n for n in tree.body if isinstance(n, ast.ClassDef)]:
        for node in cls.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == want:
                seg = ast.get_source_segment(text, node)
                assert seg is not None, f"{qualname} 的源码段读不出来"
                return seg
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == want:
            seg = ast.get_source_segment(text, node)
            assert seg is not None, f"{qualname} 的源码段读不出来"
            return seg
    raise AssertionError(f"这些 secretary 文件里找不到 {qualname}")


def _locate(qualname: str) -> tuple[str, str]:
    """`(文件名, 那个声明的源码段)` —— 搬了文件也不会让本判据失去对象。"""
    for name, text in _sources().items():
        try:
            return name, _method_segment(text, qualname)
        except AssertionError:
            continue
    raise AssertionError(f"全部分 secretary 文件里都没有 {qualname} ⇒ 判据失去对象")


def test_the_class_is_assembled_in_exactly_one_file():
    """a：`class Secretary` 只定义一次（类还是那一个类，118 个 import 一个字不改）。"""
    owners = [name for name, text in _sources().items() if "\nclass Secretary(" in text
              or text.startswith("class Secretary(") or "\nclass Secretary:" in text]
    assert owners == ["secretary.py"], f"`class Secretary` 出现在 {owners}"


def _construction_calls(text: str) -> int:
    """这份源码里"造一名 Secretary"的调用点个数（按调用点算，不按字面：docstring 里的
    举例是文档，不是装配点 —— 与 `test_bare_secretary_cannot_register` 的口径一致）。"""
    tree = ast.parse(text)
    n = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                and node.func.id == "Secretary":
            n += 1
    return n


def test_no_secretary_module_constructs_the_class():
    """b：混入层一个 `Secretary(...)` 调用点都没有 —— 造秘书只经装配口。"""
    offenders = {name: _construction_calls(text) for name, text in _sources().items()
                 if name != "secretary.py" and _construction_calls(text)}
    assert not offenders, f"这些混入模块在造秘书（应经 `_new_secretary`）：{offenders}"
    # 反真空：这一条只在真有文件可扫时才有意义
    assert len(_sources()) >= 2, "只扫到 1 个 secretary 文件 ⇒ 拆分没发生或扫错了目录"


def test_peer_secretary_goes_through_the_port():
    """c：转发链的下一跳只经 `self._new_secretary(...)`。"""
    name, seg = _locate("Secretary._peer_secretary")
    assert "self._new_secretary(" in seg, (
        f"`{name}::Secretary._peer_secretary` 没走装配口 ⇒ 它一定在直接造类或绕道 import")
    assert "Secretary(" not in seg, (
        f"`{name}::Secretary._peer_secretary` 里仍有 `Secretary(` ⇒ 混入层直接造类")


def test_concept_gate_goes_through_the_port():
    """d：概念闸的那一处构造也只经 `new_secretary(...)`。"""
    name, seg = _locate("concept_identity_gate")
    assert "new_secretary(" in seg, (
        f"`{name}::concept_identity_gate` 没走装配口 ⇒ 它一定在直接造类")
    assert "Secretary(" not in seg, (
        f"`{name}::concept_identity_gate` 里仍有 `Secretary(` ⇒ 混入层直接造类")


def test_the_port_is_the_class_attribute_and_fails_loud_when_unbound(monkeypatch, tmp_path):
    """e：`Secretary._new_secretary` 就是装配口本体；摘掉登记之后必须抛错而不是静默造一个。"""
    assert SEC.Secretary._new_secretary is PORT.new_secretary, (
        "`Secretary._new_secretary` 不是 `secretary_port.new_secretary` ⇒ 装配口被就地改写")
    # 接上时真的能造
    monkeypatch.setattr(PORT, "_FACTORY", SEC.Secretary)
    one = SEC.Secretary._new_secretary("M", root=tmp_path)
    assert isinstance(one, SEC.Secretary) and one.role == "M"
    # 摘掉登记 ⇒ 抛错（反真空：就地改写 `_new_secretary` 的实现会让这一条变绿）
    monkeypatch.setattr(PORT, "_FACTORY", None)
    with pytest.raises(RuntimeError, match="装配口还没接上"):
        SEC.Secretary._new_secretary("M", root=tmp_path)

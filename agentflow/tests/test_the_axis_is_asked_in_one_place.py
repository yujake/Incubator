# -*- coding: utf-8 -*-
"""判据：「这一行是代理还是板项」只有一个判据（2026-10-27，Q18 的下一批）。

## 背景

`secretary.row_axis`（2026-10-26 Q18）被宣布为"这一行落在哪根轴上"的唯一判据，五档：
`agent` / `item_open` / `item_closed` / `root` / `other`。秘书那一侧的注释写着
"conductor 那几处的内联判法留给下一批收"——本判据就是那一批的收口：

- `Conductor._is_board_item(row)` = `row_axis(row) in (item_open, item_closed)`
- `Conductor._is_instance_row(row)` = `not _is_board_item(row)`

两者都只取 `row_axis` 的结论，不再自己读 `kind`。conductor 里 20 来处
`str(r.get("kind") or "")` 因此收敛成两个具名谓词。

## 这条判据钉住什么

1. conductor 里再也没有内联的 `str(x.get("kind") or "")` 轴判法 ——
   除了三个"问的不是轴"的地方（见 `_ASKS_ANOTHER_KIND`，每处都带理由）；
2. 那三个例外仍然真的在问 kind（否则清单变成过期条目，等于把判据关掉）；
3. 反真空：轴谓词的调用点数量必须够多（收口之后应该随处可见，不是"一处都没有"）；
4. 两个谓词的实现必须真的走 `row_axis`（把实现改成读 `kind` ⇒ 红）。

为什么值得一条判据：轴判错一次的形态是"板项被数成在跑的子代理"（真机 `projects/mp3-r3`：
30 条板项被数成 `running 5 条`），而它不会让任何东西崩 —— 只会让两个读数各说一件事。
两处判据并存时，这种分叉迟早发生，且没有任何东西会报。
"""
from __future__ import annotations

import ast
import pathlib

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "agentflow"
CONDUCTOR = _SRC / "conductor.py"

#: "读了 `kind`、但问的不是任务台账那根轴"的地方：函数名 -> 它在问什么。
#:
#: 清单双向核（既不许漏，也不许多）：漏一条等于判据有洞，多一条过期条目等于把判据关掉一半。
_ASKS_ANOTHER_KIND: dict[str, str] = {
    "_roster_row_is_this_child":
        "问的是名册三份里哪一份的那一行（正文认 add / 对照表认 bind / 面池按名字槽位）",
    "_settle_if_informational":
        "问的是哪一类板项（信息型的那几类在渲染那一拍就收口），不是'是不是板项'",
    "keep_alive_of":
        "问的是'这一行是不是派活项'（待命声明只落在 kind=delegation 的行上，schema 受控）",
    "open_items_many":
        "写事件 note（`item:<kind>`）用的，与逐条 `open_item` 那一处逐字相同",
    "waiters_of":
        "读的是**时钟等待**记录的种类（timer / alarm / periodic），不是台账行",
    "retire_blocking":
        "同上：格式化的是时钟等待的种类",
    "retire_refusal":
        "同上：`retire_blocking` 交出来的那些等待记录",
    "_end_from_payload":
        "读的是**模型载荷**里的 `kind`（`handler_ok=False kind=…` 那一句），不是台账行；"
        "且它属 O1 那一批的改动面",
}

#: 读了轴、但本轮按纪律不许动的函数（O1 在改"事件消账"）：只登记，不判它违规。
_PROTECTED_FUNCTIONS: dict[str, str] = {
    "note_edge_release":
        "它自己那道 `kind` 过滤就是轴判法，但它属 O1 那一批（事件消账触发点），本轮不动",
}


def _walk_with_owner(tree: ast.AST):
    """(函数名, 节点) 逐个产出（类内方法用方法名，够用）。"""
    def visit(node: ast.AST, owner: str) -> None:
        for child in ast.iter_child_nodes(node):
            name = owner
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                name = child.name
            yield_ = visit(child, name)
            for item in yield_:
                _out.append(item)
    _out: list[tuple[str, ast.AST]] = []
    for item in visit(tree, ""):
        pass
    return _out


def _kind_reads(tree: ast.AST) -> list[tuple[str, int]]:
    """所有 `x.get("kind")` 的位置（函数名, 行号）。"""
    out: list[tuple[str, int]] = []

    def visit(node: ast.AST, owner: str) -> None:
        for child in ast.iter_child_nodes(node):
            name = owner
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                name = child.name
            if (isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute)
                    and child.func.attr == "get" and child.args
                    and isinstance(child.args[0], ast.Constant)
                    and child.args[0].value == "kind"):
                out.append((name, int(getattr(child, "lineno", 0) or 0)))
            visit(child, name)

    visit(tree, "")
    return out


def _source_of(name: str) -> str:
    """某个方法/函数的源码片段（用 AST 的区间取，够稳）。"""
    tree = ast.parse(CONDUCTOR.read_text(encoding="utf-8"))
    lines = CONDUCTOR.read_text(encoding="utf-8").splitlines()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return "\n".join(lines[node.lineno - 1:node.end_lineno or node.lineno])
    raise AssertionError(f"conductor 里找不到 {name}（判据清单过期了）")


def test_no_inline_axis_check_outside_the_three_documented_sites() -> None:
    tree = ast.parse(CONDUCTOR.read_text(encoding="utf-8"))
    offenders = [(fn, line) for fn, line in _kind_reads(tree) if fn not in _ASKS_ANOTHER_KIND and fn not in _PROTECTED_FUNCTIONS]
    assert not offenders, (
        "conductor 里又有内联的 `x.get(\"kind\")` 轴判法（应改调 "
        "`Conductor._is_board_item` / `_is_instance_row`）：\n"
        + "\n".join(f"  conductor.py:{line}  在 {fn}() 里" for fn, line in offenders))


def test_the_three_exceptions_really_ask_which_kind() -> None:
    """双向核：清单里的每一条今天仍然真的在读 `kind`（过期条目 = 判据被关掉一半）。"""
    tree = ast.parse(CONDUCTOR.read_text(encoding="utf-8"))
    present = {fn for fn, _line in _kind_reads(tree)}
    stale = [fn for fn in _ASKS_ANOTHER_KIND if fn not in present]
    assert not stale, (
        f"这几条已经不再读 `kind` 了 ⇒ 请从 `_ASKS_ANOTHER_KIND` 里删掉：{stale}")


def test_the_predicates_are_not_vacuous() -> None:
    """反真空：轴谓词必须真的被用起来（收口之后应该随处可见）。"""
    text = CONDUCTOR.read_text(encoding="utf-8")
    hits = text.count("_is_board_item(") + text.count("_is_instance_row(")
    assert hits >= 20, (
        f"只有 {hits} 处调用轴谓词 ⇒ 要么这批收口被回滚了，要么判据在扫一个空集")


def test_both_predicates_delegate_to_row_axis() -> None:
    """把实现改回读 `kind` ⇒ 红（这才是"唯一判据"的实质）。"""
    board = _source_of("_is_board_item")
    assert "row_axis(" in board, (
        "`_is_board_item` 不再走 `secretary.row_axis` ⇒ 轴又有了第二处判据")
    inst = _source_of("_is_instance_row")
    assert "_is_board_item" in inst, (
        "`_is_instance_row` 不再从 `_is_board_item` 派生 ⇒ 两处各判一次")

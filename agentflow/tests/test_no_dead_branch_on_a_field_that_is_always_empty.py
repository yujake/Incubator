# -*- coding: utf-8 -*-
"""判据：`next_name` 那两处"发号器可能拒"的死分支必须成对登记（2026-11-03，153-U-10）。

## 背景

`Secretary.next_name` 今天不能拒：它最后一句是
`return f"{role}{max(seen, default=0) + 1}", ""` —— 第二个分量恒为空串
（`secretary.py:4877`）。而两处调用点还留着 `if problem:` 的出口：

- `Secretary._roster_add`（`secretary.py:5095-5098`）
- `Secretary.roster_repair`（`secretary.py:7788-7790`）

151 判过："删掉会削掉'将来发号器可能拒'的显式出口，保留则要接受这两行永远不被执行"
—— 结论是保留。但 151 只记了一处，后一个人照着删就会只删一处，于是同一件事在
两个函数里各有一套处理（一个能拒、一个直接崩），而那不会让任何判据变红。

## 这条判据钉住什么

1. 前提今天成立：`next_name` 的返回确实恒空（AST 核那个 `return` 的第二个分量是
   `""` 字面量）。若哪天它真能拒了，下面两条的"死分支"说法就过期了 —— 那时应当删本文件，
   而不是给它放行；
2. 两处都在册：`next_name` 的调用点里，带 `if <问题变量>:` 的恰好是登记过的那两处
   （多一处 = 有新的死分支没登记；少一处 = 有人只删了一边）；
3. 两处带同一句登记注释：每个 `if` 的上一行必须是那句 `_MARKER` 开头的话，且全文件
   只出现两次 —— 删一边会红，写第三处而不登记也会红。

为什么值得一条判据：死代码不能靠行为红（它永远不执行），只能靠结构。而"两处各留一套"
正是这个仓库反复踩的形态。
"""
from __future__ import annotations

import ast
import pathlib

SECRETARY = pathlib.Path(__file__).resolve().parents[1] / "src" / "agentflow" / "secretary.py"

#: 登记过的两处死分支（所在函数名）。加/删一处必须同时改这里与文件里的注释 —— 这条判据
#: 就是"下一个人不许只删一处"的那道门。
_DEAD_BRANCH_SITES: tuple[str, ...] = ("_roster_add", "roster_repair")

#: 两处必须逐字相同的那句登记注释的开头（放在 `if problem:` 的上一行）。
_MARKER = "死分支·契约出口"


def _tree() -> ast.Module:
    return ast.parse(SECRETARY.read_text(encoding="utf-8"))


def _method(name: str) -> ast.FunctionDef:
    for node in ast.walk(_tree()):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"secretary.py 里找不到 {name}() ⇒ 判据的对象没了")


def test_next_name_cannot_refuse_today() -> None:
    """前提：`next_name` 的返回恒空（今天绿；它红了说明发号器真能拒了，本判据该退役）。"""
    fn = _method("next_name")
    returns = [n for n in ast.walk(fn) if isinstance(n, ast.Return)]
    assert returns, "`next_name` 里没有 return"
    problems = []
    for ret in returns:
        value = ret.value
        if not (isinstance(value, ast.Tuple) and len(value.elts) == 2):
            problems.append(f"第 {ret.lineno} 行的 return 不是二元组")
            continue
        second = value.elts[1]
        if not (isinstance(second, ast.Constant) and second.value == ""):
            problems.append(f"第 {ret.lineno} 行的第二个分量不是空串字面量")
    assert not problems, (
        "`next_name` 今天已经能返回非空的问题串了 —— 那两处 `if problem:` 不再是死分支，"
        "请删掉本判据文件并重新裁'发号器能不能拒'：\n  - " + "\n  - ".join(problems))


def _dead_branch_sites() -> list[tuple[str, int]]:
    """(所在函数名, `if` 那一行的行号) —— `next_name` 的返回值被拿去 `if` 的每一处。"""
    sites: list[tuple[str, int]] = []
    tree = _tree()
    for cls in ast.walk(tree):
        if not isinstance(cls, ast.ClassDef):
            continue
        for fn in cls.body:
            if not isinstance(fn, ast.FunctionDef):
                continue
            checked: set[str] = set()
            for node in ast.walk(fn):
                if (isinstance(node, ast.Assign)
                        and isinstance(node.value, ast.Call)
                        and isinstance(node.value.func, ast.Attribute)
                        and node.value.func.attr == "next_name"):
                    checked |= {t.id for t in node.targets if isinstance(t, ast.Name)}
                    if (isinstance(node.targets[0], ast.Tuple)
                            and all(isinstance(e, ast.Name) for e in node.targets[0].elts)):
                        checked |= {e.id for e in node.targets[0].elts}  # type: ignore[union-attr]
            for node in ast.walk(fn):
                if isinstance(node, ast.If) and isinstance(node.test, ast.Name) \
                        and node.test.id in checked:
                    sites.append((fn.name, node.lineno))
    return sorted(sites)


def test_the_two_dead_branches_are_the_registered_ones() -> None:
    """② 带 `if <问题变量>:` 的调用点恰好是登记的那两处（今天绿 —— 位置对，只是没登记注释）。"""
    got = sorted(name for name, _line in _dead_branch_sites())
    assert got == sorted(_DEAD_BRANCH_SITES), (
        f"`next_name` 那两处死分支的位置变了：实测 {got}，登记 {list(_DEAD_BRANCH_SITES)}。\n"
        "加了一处 ⇒ 请登记进 `_DEAD_BRANCH_SITES` 并在那里写同一句注释；\n"
        "少了一处 ⇒ 说明有人只删了一边（151 的结论是两处都保留，删要两处一起删并改这条判据）。")


def test_each_dead_branch_carries_the_same_note() -> None:
    """③ 每个 `if` 上面紧邻的那一段注释里有那句登记语，且全文件只出现两次（今天红）。

    为什么核"紧邻的整段注释"而不只核上一行：登记语写清楚要三行（为什么是死分支 / 与谁成对 /
    怎么改），把它压成一行只会写成一句看不懂的暗号。所以判据核"`if` 正上方那段连续注释"
    里有没有 `_MARKER` —— 中间隔了空行或代码就不算（那等于注释跟这一支没关系）。
    """
    lines = SECRETARY.read_text(encoding="utf-8").splitlines()
    hint = ("两处必须成对：`_roster_add` 与 `roster_repair`"
            "（见 tests/test_no_dead_branch_on_a_field_that_is_always_empty.py）")
    missing = []
    for name, lineno in _dead_branch_sites():
        #: 从 `if` 的上一行往上收集连续的 `#` 注释行。
        block: list[str] = []
        i = lineno - 2  #: 0 起的下标，指向 `if` 的上一行
        while i >= 0 and lines[i].strip().startswith("#"):
            block.append(lines[i])
            i -= 1
        if not any(_MARKER in line for line in block):
            missing.append(f"{name}（第 {lineno} 行）")
    total = "\n".join(lines).count(_MARKER)
    assert not missing, (
        f"这两处死分支上面那段注释里没有 `{_MARKER}`："
        + "、".join(missing) + f"\n登记语请写：{hint}")
    assert total == 2, (
        f"`{_MARKER}` 在源文件里出现 {total} 次，应当是 2 次（两处死分支各一次）—— "
        "多出来说明有新的一处没登记进 `_DEAD_BRANCH_SITES`")

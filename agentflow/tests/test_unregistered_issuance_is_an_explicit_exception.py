# -*- coding: utf-8 -*-
"""判据：未在册档不走秘书「发不发」判定，是业主裁的明文例外（乙-5）。

## 这一条守什么

业主 2026-10-29：「V 只产审稿意见；发不发签由 V 的秘书决定」。但未在册档
（`reports/{f,e,b}-proof-*.md` 那一支）常常没有「收方秘书在场」这个前提：F / E 的稿
在被收方接手之前就要签，强行要求秘书判定会把这一档变成死路。业主 2026-11-04 因此裁定：
2026-10-29 的发签权判定只约束在册档；未在册三转 clean 即颁发，落块仍由收方秘书做，
并且要求这条例外明文写在 `specs/v.py`、由判据钉住。

## 判据（每条都两向）

| # | 量什么 | 期望 |
|---|---|---|
| a | `specs/v.py` 的明文 | 读得到「只约束在册档」「落块仍由收方秘书做」两句 |
| b | `_review_pass`（在册档） | 调 `decide_sign_issuance`（正控：检测器不是瞎的） |
| c | `_review_unregistered_prose` / `_review_unregistered_exhaustion` | 不调 `decide_sign_issuance` / `judge_v_reply`（例外是真的） |
| d | 反真空（源码） | 往未在册函数里插一句 `self._decide_sign_issuance(...)` ⇒ 检测器报违规 |
| e | 反真空（明文） | 把 `specs/v.py` 那两句删掉 ⇒ 明文判据报缺 |

零模型调用、零盘上写；只读源码与声明文本。
"""
from __future__ import annotations

import ast
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
CORE = ROOT / "src" / "agentflow" / "agent_v" / "core.py"
SPEC_V = ROOT / "src" / "agentflow" / "specs" / "v.py"

#: `specs/v.py` 必须读到的两句（逐字）。
EXCEPTION_LINES: tuple[str, ...] = (
    "只约束在册档",
    "落块仍由收方秘书做",
)

#: 秘书「发不发」判定的调用名（未在册档里出现就是口径变了）。
DECISION_CALLS: frozenset[str] = frozenset({"decide_sign_issuance", "_decide_sign_issuance", "judge_v_reply", "_judge_v_reply"})

#: 在册档那一支（正控：它必须调得到判定）。
IN_REGISTER_FUNC = "_review_pass"
#: 未在册的两支（例外：不许插秘书判定）。
UNREGISTERED_FUNCS: tuple[str, ...] = (
    "_review_unregistered_prose", "_review_unregistered_exhaustion")


def _missing_exception(text: str) -> list[str]:
    """明文里缺哪几句（空表 = 两句都在）。"""
    return [needle for needle in EXCEPTION_LINES if needle not in str(text or "")]


def _func_node(source: str, name: str) -> ast.FunctionDef | None:
    """源码里名为 `name` 的函数节点（没有 ⇒ None，调用方按"没查成"报）。"""
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    return None


def _decision_calls(node: ast.AST) -> set[str]:
    """这一棵函数子树里对秘书判定入口的调用名（按属性末段认，别名也认不到就算了）。"""
    found: set[str] = set()
    for sub in ast.walk(node):
        if not isinstance(sub, ast.Call):
            continue
        func = sub.func
        name = (func.attr if isinstance(func, ast.Attribute)
                else func.id if isinstance(func, ast.Name) else "")
        if name in DECISION_CALLS:
            found.add(name)
    return found


# ====================================================================== a 明文
def test_a_the_exception_is_written_in_the_spec() -> None:
    """`specs/v.py` 明文写清「只约束在册档」与「落块仍由收方秘书做」。"""
    missing = _missing_exception(SPEC_V.read_text(encoding="utf-8"))
    assert missing == [], f"specs/v.py 缺这条明文例外：{missing}"


# ====================================================================== b 正控
def test_b_the_in_register_branch_really_asks_the_secretary() -> None:
    """正控：`_review_pass`（在册档）调得到 `decide_sign_issuance` —— 检测器不是瞎的。"""
    node = _func_node(CORE.read_text(encoding="utf-8"), IN_REGISTER_FUNC)
    assert node is not None, f"没找到函数 {IN_REGISTER_FUNC} ⇒ 这一格没查成"
    calls = _decision_calls(node)
    assert "_decide_sign_issuance" in calls, (
        f"{IN_REGISTER_FUNC} 里找不到 decide_sign_issuance ⇒ 要么口径变了，"
        f"要么检测器失效：{calls}")


# ====================================================================== c 例外是真的
def test_c_the_unregistered_branches_do_not_ask_the_secretary() -> None:
    """未在册两支不调秘书判定：三转 clean 即颁发（落块仍由收方秘书做）。"""
    source = CORE.read_text(encoding="utf-8")
    for name in UNREGISTERED_FUNCS:
        node = _func_node(source, name)
        assert node is not None, f"没找到函数 {name} ⇒ 这一格没查成"
        calls = _decision_calls(node)
        assert not calls, (
            f"{name} 里插进了秘书判定 {sorted(calls)} ⇒ 未在册档的明文例外被改了；"
            "要么把它撤掉，要么改业主裁定并同时改 specs/v.py")


# ====================================================================== d 反真空（源码）
def test_d_inserting_a_decision_into_the_unregistered_branch_is_caught() -> None:
    """反真空：往未在册函数里插一句 `self._decide_sign_issuance(...)` ⇒ 检测器报违规。"""
    source = CORE.read_text(encoding="utf-8")
    name = "_review_unregistered_prose"
    node = _func_node(source, name)
    assert node is not None, f"没找到函数 {name}"
    # 在函数体第一句之前插一句（保持缩进与语法）
    first = node.body[0]
    line = first.lineno - 1
    lines = source.splitlines()
    lines.insert(line, " " * first.col_offset + "self._decide_sign_issuance('x', '', 1, {})")
    mutated = "\n".join(lines)
    node2 = _func_node(mutated, name)
    assert node2 is not None
    assert "_decide_sign_issuance" in _decision_calls(node2), (
        "插了一句 decide_sign_issuance，检测器却没报 ⇒ 这一条量不到口径变化")


# ====================================================================== e 反真空（明文）
def test_e_removing_the_exception_text_is_caught() -> None:
    """反真空：把明文那两句删掉 ⇒ 明文判据报缺。"""
    text = SPEC_V.read_text(encoding="utf-8")
    for needle in EXCEPTION_LINES:
        text = text.replace(needle, "")
    assert _missing_exception(text) == list(EXCEPTION_LINES), (
        "删掉两句之后 `_missing_exception` 没报缺 ⇒ 这一条量不到明文")

# -*- coding: utf-8 -*-
"""审计：三处"默认值仍是写"的落点，生产路径必须显式关掉，不许靠默认值。

## 背景（2026-11-08 业主让核的三处）

V 已改成"只颁签 + 只落块"（`land_sign_without_ledger` / `record_verification(flip=False)`），
但三个签名默认值仍指向"会写"：

| 函数 | 默认值 | 改前的风险 |
|---|---|---|
| `verifications.record_verification(flip=True)` | 翻第 3 位 | 老调用给 `store` 而不传 `flip` ⇒ 顺手写命题位 |
| `vsigns.land(ledger_bit=True)` | 落台账位 | 老调用给 `store` 而不传 `ledger_bit` ⇒ 同一格两个写者 |
| `verifications._registration_after_sign(skip_gap=False)` | 读 `statements` 判"已收录" | V 的签后义务又去读命题台账 |

## 这一份的结论（审计口径，逐条可核）

- 生产路径全部显式关掉（本文件逐条 AST 核对）：`AgentV` 的两处
  `record_verification` 都带 `flip=False`；`verifications.py` 的两处 `vsigns.land` 都带
  `ledger_bit=False`（且 `store=None`）；`land_sign_without_ledger` 的
  `_registration_after_vsign` 带 `skip_gap=True`；
- 默认值保留（不改成 False）：它们只服务历史直调 / 夹具（`conftest.sign_for_the_gate`
  用 `record_verification(store=…, 不传 flip)` 一次签住第 3 位；
  `test_issue_and_land_are_two_steps` 走 `land(store=…, 不传 ledger_bit)` 测"落台账位"
  那条正路）。改成 False 会把这两条既有正路关掉 —— 按业主口径"说明并保留"。

所以判据不是"默认值改成 False"，而是"没有任何生产调用点靠默认值写"：上面三格由
AST 逐条核对；默认值本身由签名断言钉住（改它必须同时改这一份与报告）。
"""
from __future__ import annotations

import ast
import inspect
import pathlib
import sys

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agentflow import verifications as VR
from agentflow import vsigns as VS

SRC = _SRC / "agentflow"


def _enclosing(node: ast.AST, tree: ast.AST) -> str:
    """这个调用被哪个函数/方法包着（`Class.method` 形式；顶层 ⇒ 空串）。"""
    best = ""
    for parent in ast.walk(tree):
        if not isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for child in ast.walk(parent):
            if child is node:
                best = parent.name
                break
    for parent in ast.walk(tree):
        if isinstance(parent, ast.ClassDef):
            for child in parent.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and child.name == best:
                    return f"{parent.name}.{best}"
    return best


def _calls(path: pathlib.Path, *, name: str) -> list[dict]:
    """`path` 里所有末段名为 `name` 的调用 ⇒ `{kwargs, lineno, in_function, kw_false}`。"""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out: list[dict] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        callee = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
        if callee != name:
            continue
        kwargs = {kw.arg: kw.value for kw in node.keywords if kw.arg}
        out.append({
            "lineno": int(node.lineno), "kwargs": kwargs,
            "in_function": _enclosing(node, tree),
            "kw_false": {k: (isinstance(v, ast.Constant) and v.value is False)
                         for k, v in kwargs.items()},
            "kw_true": {k: (isinstance(v, ast.Constant) and v.value is True)
                        for k, v in kwargs.items()},
            "kw_none": {k: (isinstance(v, ast.Constant) and v.value is None)
                        for k, v in kwargs.items()},
        })
    return out


# ============================================================ 默认值本身（保留的读数）

def test_defaults_are_kept_on_purpose() -> None:
    """三个默认值仍是"会写"的那一档 —— 保留的理由在文件头，改它要一起改这一条。"""
    assert inspect.signature(VR.record_verification).parameters["flip"].default is True
    assert inspect.signature(VS.land).parameters["ledger_bit"].default is True
    assert inspect.signature(VR._registration_after_sign).parameters["skip_gap"].default is False


# ============================================================ 生产调用点逐条核对

def test_every_agent_v_record_verification_passes_flip_false() -> None:
    """V 的两条落台账路都显式 `flip=False`（翻位交给秘书）。"""
    calls = _calls(SRC / "agent_v" / "core.py", name="record_verification")
    assert calls, "agent_v/core.py 里一个 record_verification 调用都没扫到（判据真空）"
    for one in calls:
        assert "flip" in one["kwargs"], one
        assert one["kw_false"].get("flip") is True, one


def test_every_vsigns_land_call_passes_ledger_bit_false() -> None:
    """两处生产落签（`verifications.py` 的 V 侧 / `secretary.py` 的收方）都显式关位。"""
    calls = []
    for name in ("verifications.py", "secretary.py"):
        calls.extend({**c, "file": name}
                     for c in _calls(SRC / name, name="land"))
    assert len(calls) >= 2, calls
    for one in calls:
        assert one["kw_false"].get("ledger_bit") is True, one
        # 位由外层事务落 ⇒ 这里连 store 都不给（两个写者会重入同一把表锁）。
        assert one["kw_none"].get("store") is True, one

def test_the_secretary_landing_does_not_read_statements_for_the_obligation() -> None:
    """`land_sign_without_ledger` 开义务时显式 `skip_gap=True`（V 只对手稿负责）。

    剩下的那一处（`sign_statement` 的末尾）仍用默认 False —— 它是历史直调 / 夹具那条
    兼容门（docstring 写着"保留给历史直调 / 夹具"），不属生产签后义务。
    """
    calls = _calls(SRC / "verifications.py", name="_registration_after_vsign")
    assert calls, "一个 _registration_after_vsign 调用都没扫到（判据真空）"
    landing = [c for c in calls if c["in_function"].endswith("land_sign_without_ledger")]
    assert landing, calls
    for one in landing:
        assert one["kw_true"].get("skip_gap") is True, one
    legacy = [c for c in calls if c["in_function"].endswith("sign_statement")]
    assert legacy, calls
    for one in legacy:
        assert "skip_gap" not in one["kwargs"], one   # 默认 False = 兼容门的既有口径

# -*- coding: utf-8 -*-
"""`host` 是不是真的"读注册表"（`goal-7f5116c1` M4 的判据）。

M4 之前：`host._Builder` 里有 8 个各自带构造逻辑的方法（`agent_a` … `agent_h`），
每个都自己决定用哪个类、传哪些关键字、要谁的实例 —— 于是"新建一个 agent"必须改这个文件。
M4 之后：构造逻辑在 `specs/<角色>.py::build`，`_Builder` 里只留薄壳 + 一个通用 `_build`。

这条判据钉三件事（都有负控）：

1. 薄壳：`agent_x` 的方法体只有一个 `return self._build("<角色>", …)`，
   且 `_Builder` 的任何方法里都不再出现 `Agent[A-H](` / `Conductor(` 的直接构造；
2. 声明的字段对得上：每个角色 `spec.build` 可调用；`needs` 里的每个名字都是
   `BuilderDeps` 的字段（拼错会在这里红，而不是等到运行期某个角色拿到 `None`）；
   `peers` 里的每个角色都在注册表里；
3. 反真空：九个角色都要有 `build`（少一个说明这条判据的扫描面漏了）。

判据 1 用源码 + AST（不是"看名字像不像"）：`_Builder` 的类体里出现直接构造
就报错 —— 那是 M4 要消灭的形态。
"""
from __future__ import annotations

import ast
import pathlib

import pytest

from agentflow import host as H
from agentflow import leanscope
from agentflow.agentspec import BuilderDeps, AgentSpec, builtin_registry

HOST_SRC = pathlib.Path(H.__file__)
ROLES = tuple("ABCDEFGH")


def _builder_class(tree: ast.Module) -> ast.ClassDef:
    return next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "_Builder")


def direct_constructions(src: str) -> list[str]:
    """`_Builder` 里直接构造角色的地方（M4 之后必须为空）。

    认两种写法：`AgentX(...)` / `Conductor(...)` 的调用，以及 `from .agent_x import AgentX`
    这种"为了就地构造而 import"的写法 —— 后者是前者的前一步，一起挡掉。
    """
    tree = ast.parse(src)
    cls = _builder_class(tree)
    out: list[str] = []
    for node in ast.walk(cls):
        if isinstance(node, ast.Call):
            name = getattr(node.func, "id", None)
            if isinstance(name, str) and (name.startswith("Agent") or name == "Conductor"):
                out.append(f"{name}() 直接构造（第 {node.lineno} 行）")
        elif isinstance(node, ast.ImportFrom):
            for a in node.names:
                if a.name.startswith("Agent") or a.name == "Conductor":
                    out.append(f"import {a.name}（第 {node.lineno} 行，构造该搬进声明）")
    return out


def thin_shells(src: str) -> list[str]:
    """薄壳检查：每个 `agent_x` 的方法体只有一个 `return self._build("X", …)`。"""
    tree = ast.parse(src)
    cls = _builder_class(tree)
    problems: list[str] = []
    for node in cls.body:
        if not isinstance(node, ast.FunctionDef) or not node.name.startswith("agent_"):
            continue
        role = node.name.split("_", 1)[1].upper()
        body = [st for st in node.body if not (isinstance(st, ast.Expr)
                                                and isinstance(st.value, ast.Constant))]
        if len(body) != 1 or not isinstance(body[0], ast.Return):
            problems.append(f"{node.name}：方法体不是单个 return（{len(body)} 条语句）")
            continue
        call = body[0].value
        ok = (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
              and call.func.attr == "_build"
              and call.args and isinstance(call.args[0], ast.Constant)
              and call.args[0].value == role)
        if not ok:
            problems.append(f"{node.name}：return 的不是 self._build({role!r}, …)")
    return problems


def test_every_role_is_built_through_its_spec() -> None:
    """主判据：每个角色都有 `build`，`needs`/`peers` 都指向真实存在的东西。

    反真空那一条读的是"角色表读数"而不是一个写死的数字：业主 2026-10-22 起，L 的
    存在性由 Lean 开关决定（`leanscope.LEAN_ONLY_ROLES` + `AgentRegistry.roles()`
    的 docstring：「由开关决定存在性的角色在开关关着时不出现在这份读数里」），
    而本套件跑在 Lean 开着那一档（`conftest.py` 钉 `AGENTFLOW_LEAN_ENABLED=1`）
    ⇒ 读数是 11（A–H + V + M + L），钉死的 10 在这一档上必红。改成
    "等于这一档的可见面"比原来更严：少一个基础角色、或 L 的开关关系被改坏，
    两种都会红，而原来的写法只认一个数字。
    """
    reg = builtin_registry()
    fields = set(BuilderDeps.__dataclass_fields__)
    bad: list[str] = []
    for role in reg.roles():
        spec = reg.get(role)
        if spec.build is None or not callable(spec.build):
            bad.append(f"{role}：声明里没有可调用的 build")
        for need in spec.needs:
            if need not in fields:
                bad.append(f"{role}：needs 里的 {need!r} 不是 BuilderDeps 的字段")
        for peer in spec.peers:
            if peer not in reg.roles():
                bad.append(f"{role}：peers 里的 {peer!r} 不在注册表里")
    assert not bad, "角色声明与装配期契约对不上：\n  - " + "\n  - ".join(bad)
    expected = len(leanscope.visible_roles(reg._specs))
    assert len(reg.roles()) == expected, (
        f"角色表读数 {len(reg.roles())} ≠ 这一档的可见面 {expected}"
        f"（`leanscope.LEAN_ONLY_ROLES` 里的角色在开关关着时不算存在）")
    assert len(reg.roles()) >= 10, "反真空：A–H + V + M 十个基础角色一个都不许少"


def test_the_builder_only_delegates() -> None:
    """`_Builder` 里不再有构造逻辑：薄壳 + 没有直接构造。"""
    src = HOST_SRC.read_text(encoding="utf-8")
    problems = thin_shells(src) + direct_constructions(src)
    assert not problems, ("`host._Builder` 里还有构造逻辑（M4 之后应当只剩薄壳）：\n  - "
                          + "\n  - ".join(problems))


def test_the_registry_driven_criterion_catches_a_regression() -> None:
    """负控：把构造逻辑塞回 `agent_a`，两条判据都必须报出来。"""
    src = HOST_SRC.read_text(encoding="utf-8")
    doctored = src.replace(
        '        return self._build("A", store, instance)',
        "        from .agent_a import AgentA\n"
        "        return AgentA(store, providers=list(self.providers), llm=self._llm_for('A'))",
        1)
    assert doctored != src, "夹具前提：找得到 `agent_a` 的那一行"
    assert thin_shells(doctored), "薄壳判据没报出来"
    assert direct_constructions(doctored), "直接构造判据没报出来"

    # 另一个方向：`needs` 里写错一个名字，主判据必须报（不是等到运行期拿 None）
    reg = builtin_registry()
    import dataclasses

    broken = dataclasses.replace(reg.get("A"), needs=("provider",))
    fields = set(BuilderDeps.__dataclass_fields__)
    assert [n for n in broken.needs if n not in fields], "拼错的名字没被认出来"

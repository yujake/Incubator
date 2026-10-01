# -*- coding: utf-8 -*-
"""按动作拆包的判据（`goal-7f5116c1` M6）：一个动作一个文件。

M6 把 `agent_c.py`（3446 行）拆成包：9 个动作各占一个模块，其余成员在 `core.py`，
模块级 helper 与常量在 `_support.py`，入口 `__init__.py` 只做再导出。
这一条钉四件事（都有负控）：

1. **一个动作一个文件**：每个 `handler_name` 都有自己的 `<动作>.py`；
2. **方法真的住在那里**：`getattr(AgentC, action).__module__` 必须是 `...agent_c.<动作>`；
3. **core 里一个动作都没有**：`core.py` 的 AST 里不许出现动作方法名；
4. **入口保持 import 面**：`agentflow.agent_c` 下仍能取到 `AgentC` 与 `SPEC`（拆包不许改 import 面）。

搬移是否**逐字**由一次性证明给出（`temp/_m6_verify_verbatim.py`：9/9 个动作的源码非空行
与拆分前相同，相对 import 的层级归一化后逐行相等）；这条判据守的是"拆完之后还保持这个形状"。
"""
from __future__ import annotations

import ast
import importlib
import pathlib

import pytest

from agentflow.agentspec import builtin_registry

#: 拆成包的角色 ⇒ 包名（M6 先拆 `C`，`agent_d` 随后）。
SPLIT_PACKAGES: dict[str, str] = {"C": "agent_c"}

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "agentflow"


def split_problems(*, role: str, pkg: str, actions: list[str],
                   homes: dict[str, str], core_source: str,
                   package_dir: pathlib.Path) -> list[str]:
    """拆包形状的问题清单（空 = 成立）。把输入都作为参数，负控才跑得动同一段逻辑。"""
    out: list[str] = []
    for action in actions:
        if not (package_dir / f"{action}.py").is_file():
            out.append(f"{role}：动作 {action!r} 没有自己的 <动作>.py")
        home = homes.get(action, "")
        if home != f"agentflow.{pkg}.{action}":
            out.append(f"{role}：动作 {action!r} 的实现住在 {home!r}，"
                       f"应当是 'agentflow.{pkg}.{action}'")
    tree = ast.parse(core_source)
    defined = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    leaked = sorted(set(actions) & defined)
    if leaked:
        out.append(f"{role}：core.py 里还定义着动作方法 {leaked}（它们该各自一个文件）")
    return out


def _entry(role: str, pkg: str):
    mod = importlib.import_module(f"agentflow.{pkg}")
    return mod, getattr(mod, f"Agent{role}")


def test_split_packages_are_one_action_one_file() -> None:
    """主判据：每个拆了包的角色都要满足四条（见模块 docstring）。"""
    reg = builtin_registry()
    problems: list[str] = []
    for role, pkg in SPLIT_PACKAGES.items():
        mod, cls = _entry(role, pkg)
        actions = [a.handler_name for a in reg.get(role).actions]
        assert actions, f"{role} 的动作表是空的 ⇒ 这条判据没有输入"
        homes = {a: getattr(cls, a).__module__ for a in actions}
        problems += split_problems(role=role, pkg=pkg, actions=actions, homes=homes,
                                   core_source=(SRC / pkg / "core.py").read_text(encoding="utf-8"),
                                   package_dir=SRC / pkg)
        assert getattr(mod, f"Agent{role}") is cls
        assert mod.SPEC.role == role, f"{pkg}/__init__.py 没有把 SPEC 再导出"
    assert not problems, "拆包形状不对：\n  - " + "\n  - ".join(problems)


def test_the_split_shape_judge_catches_a_regression() -> None:
    """负控：把动作的落点改回 core、或删掉一个动作文件 ⇒ 同一个检查函数必须报出来。"""
    role, pkg = "C", "agent_c"
    reg = builtin_registry()
    actions = [a.handler_name for a in reg.get(role).actions]
    mod, cls = _entry(role, pkg)
    pkg_dir = SRC / pkg
    core_src = (pkg_dir / "core.py").read_text(encoding="utf-8")

    # ① 落点改回 core
    bad_homes = {a: f"agentflow.{pkg}.core" for a in actions}
    assert split_problems(role=role, pkg=pkg, actions=actions, homes=bad_homes,
                          core_source=core_src, package_dir=pkg_dir), "落点错没被抓住"
    # ② core 里塞一个动作方法
    doctored_core = core_src + f"\n\ndef {actions[0]}(self):\n    return None\n"
    assert split_problems(role=role, pkg=pkg, actions=actions,
                          homes={a: f"agentflow.{pkg}.{a}" for a in actions},
                          core_source=doctored_core, package_dir=pkg_dir), "core 泄漏没被抓住"
    # ③ 动作文件缺失
    assert split_problems(role=role, pkg=pkg, actions=["不存在的动作"],
                          homes={}, core_source=core_src,
                          package_dir=pkg_dir), "缺文件没被抓住"
    # 反真空：正控输入下必须干净
    assert split_problems(role=role, pkg=pkg, actions=actions,
                          homes={a: getattr(cls, a).__module__ for a in actions},
                          core_source=core_src, package_dir=pkg_dir) == []


def test_a_role_that_is_not_split_yet_is_still_a_module() -> None:
    """边界：还没拆的角色仍然是单个模块（这条判据不替它们背书，只是把事实写下来）。"""
    for role, pkg in SPLIT_PACKAGES.items():
        assert (SRC / pkg).is_dir(), f"{pkg} 应当是包"
        assert not (SRC / f"{pkg}.py").exists(), f"{pkg}.py 与包不能并存"
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("agentflow.agent_d.core")

# -*- coding: utf-8 -*-
"""按动作拆包的判据（`goal-7f5116c1` M6/M7）：一个动作一个文件。

M6 把 `agent_c.py`（3446 行）与 `agent_d.py`（4197 行）拆成包，M7 把余下六个角色
（A/B/E/F/G/H）也改成同样的形状：`<角色>/` 下 9–14 个动作各占一个模块，其余成员在
`core.py`，模块级 helper 与常量在 `_support.py`，入口 `__init__.py` 只做再导出，
`__main__.py` 是 `python -m agentflow.<角色>` 的自检入口。
这一条钉五件事（都有负控）：

1. 一个动作一个文件：每个 `handler_name` 都有自己的 `<动作>.py`；
2. 方法真的住在那里：`getattr(AgentC, action).__module__` 必须是 `...agent_c.<动作>`；
3. core 里一个动作都没有：`core.py` 的 AST 里不许出现动作方法名；
4. 入口保持 import 面：`agentflow.agent_c` 下仍能取到 `AgentC` 与 `SPEC`（拆包不许改 import 面）；
5. `python -m agentflow.<角色>` 还能跑（M6 漏了这一条：自检块被留在 `core.py` 里，
   于是块还在、却永远不会被执行 —— 见 `main_entry_problems` 的注释）。

搬移是否逐字由一次性证明给出（`temp/_m6_verify_verbatim.py`：C 9/9、D 14/14、
A 3/3、B 6/6、E 5/5、F 4/4、G 6/6、H 4/4 个动作的源码非空行与拆分前相同，
相对 import 的层级归一化后逐行相等）；这条判据守的是"拆完之后还保持这个形状"。
"""
from __future__ import annotations

import ast
import importlib
import os
import pathlib
import subprocess
import sys

import pytest

from agentflow.agentspec import builtin_registry

#: 拆成包的角色 ⇒ 包名（`M6` 先拆 `C`/`D`，`M7` 把余下六个一起拆）。
SPLIT_PACKAGES: dict[str, str] = {
    "A": "agent_a", "B": "agent_b", "C": "agent_c", "D": "agent_d",
    "E": "agent_e", "F": "agent_f", "G": "agent_g", "H": "agent_h",
}

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
    """边界：拆过的角色是包、没拆的仍是单模块（这条判据不替未拆的角色背书，只把事实写下来）。"""
    for role, pkg in SPLIT_PACKAGES.items():
        assert (SRC / pkg).is_dir(), f"{pkg} 应当是包"
        assert not (SRC / f"{pkg}.py").exists(), f"{pkg}.py 与包不能并存"
    assert SPLIT_PACKAGES == {
        "A": "agent_a", "B": "agent_b", "C": "agent_c", "D": "agent_d",
        "E": "agent_e", "F": "agent_f", "G": "agent_g", "H": "agent_h",
    }, "拆过的角色清单变了 ⇒ 这条判据的覆盖面跟着变，必须显式更新"
    # 八个角色（除主控）现在都是包；「还是单模块」的那一侧用非角色模块做边界。
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("agentflow.agent_prompts.core")   # 它不是角色包，没有 core 子模块


#: 拆包时最容易漏的一件事（实测：`M6` 漏了，`python -m agentflow.agent_c/d` 直接报
#: `No module named …__main__`，而"8 个 agent 自检退出码 0"写在 `docs/ROLE-SPECS.md`
#: 与 `scripts/release_check.py` 第 2 项里）。
def main_entry_problems(*, pkg: str, package_dir: pathlib.Path, source: str) -> list[str]:
    """`__main__.py` 的问题清单（空 = 成立）。负控跑的就是这一段。"""
    out: list[str] = []
    main_py = package_dir / "__main__.py"
    if not main_py.is_file():
        out.append(f"{pkg}：没有 __main__.py ⇒ `python -m agentflow.{pkg}` 跑不了")
        return out
    tree = ast.parse(source)
    guarded = [n for n in tree.body
               if isinstance(n, ast.If) and ast.unparse(n.test) == "__name__ == '__main__'"]
    if not guarded:
        out.append(f"{pkg}：__main__.py 里没有 `if __name__ == \"__main__\":` 自检块")
    return out


def test_every_split_package_has_a_runnable_main_entry() -> None:
    """每个拆了包的角色都要有 `__main__.py`（`python -m` 的契约不许被拆包悄悄破坏）。"""
    problems: list[str] = []
    for pkg in SPLIT_PACKAGES.values():
        src = (SRC / pkg / "__main__.py")
        problems += main_entry_problems(
            pkg=pkg, package_dir=SRC / pkg,
            source=src.read_text(encoding="utf-8") if src.is_file() else "")
    assert not problems, "拆包坏了 `python -m` 的契约：\n  - " + "\n  - ".join(problems)


def test_the_main_entry_judge_catches_a_regression(tmp_path: pathlib.Path) -> None:
    """负控：① 删掉 `__main__.py` ② 留下文件但没有那个守卫 ⇒ 同一个检查函数都要报出来。"""
    assert main_entry_problems(pkg="agent_x", package_dir=tmp_path, source=""), "缺文件没被抓住"
    empty = tmp_path / "__main__.py"
    empty.write_text("from .core import _selftest\n", encoding="utf-8")
    assert main_entry_problems(pkg="agent_x", package_dir=tmp_path,
                               source=empty.read_text(encoding="utf-8")), "缺守卫没被抓住"
    # 反真空：正控输入下必须干净
    empty.write_text('if __name__ == "__main__":\n    raise SystemExit(0)\n', encoding="utf-8")
    assert main_entry_problems(pkg="agent_x", package_dir=tmp_path,
                               source=empty.read_text(encoding="utf-8")) == []


@pytest.mark.parametrize("role,pkg", sorted(SPLIT_PACKAGES.items()))
def test_every_role_package_runs_as_a_module(role: str, pkg: str) -> None:
    """`python -m agentflow.<角色>` 的契约：退出码 0，且真的打印了自检结论。

    上一条判据只看文件形状（有没有那个守卫）；这一条真的把命令跑一遍 ——
    形状对而 import 错（例如 `__main__.py` 从 `_support` 里 import 一个住在 `core`
    的名字）只有跑起来才会露出来。A/B 另有 `tests/test_core_audit_abc_cli.py` 守着，
    这里对八个角色一视同仁。
    """
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1",
           "PYTHONPATH": str(SRC.parent)}
    r = subprocess.run([sys.executable, "-m", f"agentflow.{pkg}"], cwd=str(SRC.parent),
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       env=env, timeout=600)
    out = (r.stdout or "") + (r.stderr or "")
    assert r.returncode == 0, out[-800:]
    assert ("自检" in out) or ("SELF-CHECK" in out), (
        f"{role}：`python -m agentflow.{pkg}` 退出码 0 但没有任何自检结论 ⇒ "
        f"它可能什么都没检查。输出尾部：{out[-400:]!r}")

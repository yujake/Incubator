# -*- coding: utf-8 -*-
"""判据：四条"移植期工具"仍在 `tools/legacy_cli/` 里，CLI 那一层只剩一行转发。

## 这一份守什么

这一轮把 `repair` / `rebuild` / `demo` / `evidence migrate` 的实现搬到了
`tools/legacy_cli/<名字>.py`，CLI 里只留一行转发。搬东西最容易出的事是"顺手改好了"，
以及更常见的一种：搬家只搬了个空壳，实现还留在 CLI 里（两份真身，下一次只改一处）。

| 判据 | 它钉的是 | 改坏之后的样子 |
|---|---|---|
| ② | 转发只有一层（函数体里只有一处 `_legacy_module(...).main(args)`） | 转发层里长出第二份逻辑（两份实现又回来了） |
| ③ | 实现真的在 `tools/legacy_cli/<名字>.py` 里，且 `cli.py` 里不再有那份实现 | 搬家只搬了个空壳，实现还留在 CLI |
| ④ | 装好的包（没有 `tools/`）跑这四条 ⇒ ImportError 里那句人话 | 用户拿到一个 import 栈 |

## 2026-10-26：撤掉 ①「与搬走前逐字节相同」（G3 裁定）

① 拿的是搬走之前那一版输出的 sha256。G3 裁定撤掉它，理由只有一条：它已经没有
可比对象 —— 迁移在 2026-09 就完成了，之后工具面改了三轮（板项、`paper_package`
整条退场、`data/` 划成框架账本区），今天 `demo` 打出来的每一个字节都是迁移之后
那条路的产物。留着它只有两种结局：要么永远红着（读数与它声称守的东西已经无关），
要么每隔几天重算一次指纹 —— 那时它守的就不是"搬家没改行为"，而是"上一次重算
是什么样"，而那件事没有价值。

撤掉它不削弱②③④：② 守"转发只有一层"、③ 守"实现在 `tools/legacy_cli/` 里"、
④ 守"装好的包里那句人话"，三条都是结构判据，不依赖任何指纹。判据强度没变，
减少的只是一份过期的读数。
"""
from __future__ import annotations

import ast
import pathlib

import pytest

from agentflow import cli

#: 这条判据管的那四个"移植期工具"（名字 = `tools/legacy_cli/<名字>.py` 的文件名）。
LEGACY_TOOLS: tuple[str, ...] = ("rebuild", "repair", "demo", "evidence_migrate")


# ---------------------------------------------------------------- ② 转发只有一层


def _returns(func: ast.FunctionDef) -> list[ast.Return]:
    return [n for n in ast.walk(func) if isinstance(n, ast.Return)]


def test_each_forward_is_exactly_one_layer() -> None:
    """② 每个 `cmd_*` 的函数体只有一处 return，且那一处就是 `_legacy_module(..).main(args)`。

    "薄转发只有一层"的可执行形态：函数体里不许有第二份逻辑（if/for/try 一个都不许），
    返回值必须来自 `_legacy_module("<名字>").main(args)`。
    """
    tree = ast.parse((pathlib.Path(__file__).resolve().parents[1]
                      / "src" / "agentflow" / "cli.py").read_text(encoding="utf-8"))
    forwards = {"cmd_rebuild": "rebuild", "cmd_repair": "repair", "cmd_demo": "demo",
                "_evidence_migrate": "evidence_migrate"}
    found: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or node.name not in forwards:
            continue
        found.add(node.name)
        body = [n for n in node.body if not isinstance(n, ast.Expr)
                or not isinstance(getattr(n, "value", None), ast.Constant)]
        assert len(body) == 1, (node.name, [type(n).__name__ for n in node.body])
        returns = _returns(node)
        assert len(returns) == 1, (node.name, len(returns))
        text = ast.unparse(returns[0].value)
        assert text == f'_legacy_module({forwards[node.name]!r}).main(args)', (node.name, text)
        # 没有第二个语句、也没有别的地方偷偷干这件事
        assert not [n for n in ast.walk(node) if isinstance(n, (ast.If, ast.For, ast.While,
                                                                ast.Try, ast.With))], node.name
    assert found == set(forwards), sorted(found)


# ---------------------------------------------------------------- ③ 实现真的搬走了


def test_the_implementation_really_lives_in_tools_legacy_cli() -> None:
    """③ 实现真的在 `tools/legacy_cli/<名字>.py` 里，且 CLI 里不再有那份实现。"""
    root = pathlib.Path(__file__).resolve().parents[1]
    for name in LEGACY_TOOLS:
        path = root / "tools" / "legacy_cli" / f"{name}.py"
        assert path.is_file(), f"没有这个文件：{path}"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        funcs = [n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
        assert "main" in funcs, (name, funcs)
    cli_text = (root / "src" / "agentflow" / "cli.py").read_text(encoding="utf-8")
    for marker in ('st.rebuild(backup=', 'tty.bullet("没有需要迁移的产物',
                   'related_concepts 重算了', 'run_demo('):
        assert marker not in cli_text, f"实现还留在 cli.py 里：{marker!r}"


# ---------------------------------------------------------------- ④ 装好的包里那句人话


def test_a_missing_tools_directory_says_something_a_human_can_act_on(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """④ 没有 `tools/`（装好的包）⇒ ImportError 里那句人话，而不是一个 import 栈。"""
    monkeypatch.setattr(cli, "_LEGACY_TOOLS_DIR", "legacy_cli_not_here")
    with pytest.raises(ImportError) as exc:
        cli._legacy_module("rebuild")
    assert "移植期工具不在盘上" in str(exc.value), str(exc.value)
    assert "只能在源码仓库里跑" in str(exc.value), str(exc.value)


def test_the_loader_caches_the_module() -> None:
    """加载器把模块缓存进 `sys.modules`（连跑两次不重新执行模块体）。"""
    first = cli._legacy_module("rebuild")
    second = cli._legacy_module("rebuild")
    assert first is second
    assert first.__name__ == "_agentflow_legacy_cli_rebuild"

# -*- coding: utf-8 -*-
"""判据（施工单 a）：G 那一节技能正文里点名的东西，必须在源码里真的存在。

## 为什么这一条值得单独立案

技能正文是模型照着做事的东西，而它里面写的是 `模块.函数` 与 `工具名` 这样的符号。
名字写错一个字，模型拿到的是一个不存在的东西：它要么照着编一个参数表，要么干脆换一条路
—— 两种后果都不会让任何东西报错。改前的真身是一句

    exhaustionreport 的 write_report 写

而 `exhaustionreport` 里从来没有 `write_report`（真身是 `compose_report` 拼三段文本、
`land_report` 落盘）。这句话在提示词里躺了很久，因为没有任何判据读它。

## 判据

| # | 判据 | 改前为什么红 |
|---|---|---|
| ① | G 那一节里每个 `前缀.名字`：前缀是 agentflow 模块 ⇒ 名字必须是它的属性；前缀是工具组 ⇒ 名字必须是注册表里的一件工具 | `exhaustionreport.write_report` 不存在 |
| ② | 反真空：扫描面必须真的解析到若干个引用（不是"一个都没扫到 ⇒ 全绿"） | 扫描器解析出空集会无条件通过 |
| ③ | 负控：把改前那句话放回去 ⇒ ① 红；`D.write_report`（动作名，不是模块也不是工具组）不许被误报 | 判据不许对别的名字族叫狼 |

为什么"解析不到的前缀"要跳过而不是报错：技能正文里还有文件名（`main.tex` /
`MAPPING.json` / `code/r34_check.py`）与动作名（`G.build_document` / `D.write_report`）。
它们的前缀既不是模块也不是工具组 —— 判据把这种情况当"不是我们判的那一类名字"跳过。
误报一多，真违约就没人看了（本项目 R001 / R006 都栽在噪音上）。
"""
from __future__ import annotations

import importlib
import re

import pytest

from agentflow import agent_skills as SK
from agentflow.store import Store
from agentflow.tools import _TOOL_GROUP_PREFIXES, build_registry

#: `模块.名字` 的形态（前缀小写开头；函数名可以带下划线）。
_DOTTED = re.compile(r"([a-z][a-z0-9_]{2,})\.([A-Za-z_][A-Za-z0-9_]*)")

#: 中文所有格的另一种写法：`` `模块` 的 `函数` ``（改前那句话正是这一种）。
_POSSESSIVE = re.compile(r"`([a-z][a-z0-9_]{2,})`\s*的\s*`([A-Za-z_][A-Za-z0-9_]*)`")

#: 不做解析的前缀：`agentflow` 包本身（`agentflow.xxx` 这种写法要单独判）。
_SKIP_PREFIXES = frozenset({"agentflow"})

#: 文件名的那种"点"（`reports/q-research.md` / `main.tex` / `MAPPING.json`）。
#: 判据只判"我们自己产出的符号"，不比对一个不存在的文件类型 —— 这类尾巴一律跳过。
_FILE_EXTENSIONS = frozenset({
    "md", "tex", "pdf", "json", "jsonl", "py", "csv", "txt", "yaml", "yml", "toml", "sh",
})

#: 反真空下限：G 那一节里至少该解析到这么多个"我们自己产出的名字"。
#: 实测（2026-10-25）：`doc.*` 三处、`review.list_findings`、`fs.write`、
#: `papermapping.write_package`、`exhaustionreport.land_report` 共七处；下限取 6 是余量。
_MIN_RESOLVED = 6


def _g_text() -> str:
    """G 那一节的全文（title / summary / when / body 与它声明的工具面和动作面）。"""
    parts: list[str] = []
    for skill in SK._g_skills():  # noqa: SLF001 - 这一节就是被判的对象
        parts.extend([skill.title, skill.summary, skill.when, skill.body,
                      " ".join(skill.tools), " ".join(skill.actions)])
    return "\n".join(parts)


def _references(text: str) -> list[tuple[str, str]]:
    """文本里所有形如 `前缀.名字` 的引用（去重，保序；文件名那一种不算）。"""
    seen: list[tuple[str, str]] = []
    for prefix, name in _DOTTED.findall(str(text)) + _POSSESSIVE.findall(str(text)):
        if name.lower() in _FILE_EXTENSIONS:
            continue
        pair = (prefix, name)
        if pair not in seen:
            seen.append(pair)
    return seen


def _module(prefix: str) -> object | None:
    """把前缀解析成一个真的 import 得到的模块；解析不到返回 None（= 不是模块引用）。"""
    if prefix in _SKIP_PREFIXES:
        return None
    try:
        return importlib.import_module(f"agentflow.{prefix}")
    except Exception:  # noqa: BLE001 - 解析不到就是"这不是模块引用"，不是缺陷
        return None


def _problems(text: str, tool_names: set[str]) -> tuple[list[str], int]:
    """① 的正文：返回 `(问题清单, 解析到几个名字)`。"""
    bad: list[str] = []
    resolved = 0
    for prefix, name in _references(text):
        mod = _module(prefix)
        if mod is not None:
            resolved += 1
            if not hasattr(mod, name):
                bad.append(f"`{prefix}.{name}` 在源码里不存在（agentflow.{prefix} 没有属性 "
                           f"{name!r}）—— 技能正文点了一个不存在的符号，模型会照着它编")
            continue
        if prefix in _TOOL_GROUP_PREFIXES:
            resolved += 1
            if f"{prefix}.{name}" not in tool_names:
                bad.append(f"`{prefix}.{name}` 不是注册表里的任何一件工具（工具组 {prefix} "
                           "里没有这个名字）—— 技能正文点了一件不存在的工具")
    return bad, resolved


@pytest.fixture(scope="module")
def tool_names(tmp_path_factory: pytest.TempPathFactory) -> set[str]:
    """完整工具面的名字集合（带 store 与工作区根：`fs_tools` / `research_tools` 要它们）。"""
    root = tmp_path_factory.mktemp("g-skills-tools")
    st = Store(root / "ws")
    st.init()
    build = build_registry(store=st, workspace_root=root / "ws")
    names = set(build.registry.names())
    assert len(names) >= 90, (
        f"只装出 {len(names)} 件工具（skipped={build.skipped}）⇒ 下面那些工具名判据会"
        "把「装配没成功」读成「名字不存在」")
    return names


# ============================================================ ① 正文点名的东西都要在


def test_every_function_named_in_the_g_skills_really_exists(tool_names: set[str]) -> None:
    """① G 那一节点名的可解析名字都存在，且 ② 扫描面真的扫到了东西。"""
    bad, resolved = _problems(_g_text(), tool_names)
    assert bad == [], "\n".join(bad)
    assert resolved >= _MIN_RESOLVED, (
        f"只解析到 {resolved} 个名字（下限 {_MIN_RESOLVED}）⇒ 这条判据可能是真空的："
        "它要么没扫到正文，要么前缀全被跳过了")


def test_the_exhaustion_report_names_are_the_real_ones() -> None:
    """① 的另一半：那一句必须点名真身，而不是判据自己猜的写法。

    `compose_report`（拼三段文本）与 `land_report`（落盘）都在 `exhaustionreport` 里；
    `write_report` 不在。这一条把"该写哪两个名字"钉在源码上：以后谁给函数改名，
    技能正文会跟着红（而不是继续指着一个不存在的符号）。
    """
    from agentflow import exhaustionreport as ER

    assert hasattr(ER, "compose_report") and hasattr(ER, "land_report"), (
        "夹具前提：真身是 compose_report / land_report")
    text = _g_text()
    assert "compose_report" in text and "land_report" in text, (
        "G 那一节没有点名这两个真身 ⇒ 模型不知道那份 exhaustion.md 是谁写的")
    assert "exhaustionreport" in text
    assert "write_report" not in text.replace("D.write_report", ""), (
        "G 那一节还在点 exhaustionreport 的 write_report（那个函数不存在）")


# ============================================================ ③ 负控


def test_negative_control_a_missing_name_is_caught_and_an_action_name_is_not(
        tool_names: set[str]) -> None:
    """③ 负控：改前那句话放回去 ⇒ 红；动作名 `D.write_report` ⇒ 不误报。"""
    old = "（`exhaustionreport` 的 `write_report` 写；三块标题逐字、结尾署名 `作者：E`）"
    bad, _ = _problems(old, tool_names)
    assert bad and "write_report" in bad[0], bad

    # (a) 工具组里不存在的工具名也咬得住
    bad, _ = _problems("`review.list_findings_draft` 会列出待办", tool_names)
    assert bad and "review.list_findings_draft" in bad[0], bad

    # (b) 动作名（`D.write_report`）既不是模块也不是工具组 ⇒ 跳过，不误报
    bad, resolved = _problems("`D.write_report` 渲染的 `reports/q-research.md` 是工作稿",
                              tool_names)
    assert bad == [], f"动作名被当成模块/工具名了（这是假阳性）：{bad}"
    assert resolved == 0, resolved

    # 收尾：真的正文照旧全对
    assert _problems(_g_text(), tool_names)[0] == []


if __name__ == "__main__":  # pragma: no cover - 手动跑这一组时的入口
    raise SystemExit(pytest.main([__file__, "-q"]))

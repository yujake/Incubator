"""cache_tools 的两个工具：已知未接线，但必须被点名（施工单 150 的 e）。

业主 2026-10-23 裁定「本轮不挂」：`tools._MODULES` 里没有 `cache_tools`，所以
`cache.status` / `cache.warm` 现在没有任何角色拿得到。这不是「忘了接」，是「决定不接」 ——
两者在代码里长得一模一样，所以必须有一条判据把那个决定钉住：

  * 一旦有人把它们挂上去，第一条断言的期望要跟着改（那是接线事件，要人看见）；
  * 一旦文件被误删，第二条会红（「决定不接」不等于「允许它消失」）。
"""

from __future__ import annotations

import importlib
import pathlib

from agentflow import tools as T


def test_cache_tools_exist_but_are_not_in_the_module_list() -> None:
    """文件在、register 在，但 `_MODULES` 里没有它 —— 这就是「已知未接线」的定义。"""
    mod = importlib.import_module("agentflow.tools.cache_tools")
    assert callable(getattr(mod, "register", None)), "cache_tools.register 不见了"
    assert "cache_tools" not in T._MODULES, (
        "cache_tools 被挂进 _MODULES 了 —— 这是接线事件：请把本判据与工具面快照、"
        "工具总数一起改，并在 draft/150 的 e 那一节记一笔")
    names = {s.name for s in getattr(mod, "TOOLS", ())}
    if not names:
        # 这一族工具的声明不经过模块级 TOOLS：用真装配一次看它注册出什么名字
        # （register 需要一个真 registry —— 空表就够，它只往里注册声明）。
        from agentflow.tools.base import ToolRegistry
        reg = ToolRegistry(name="t-cache-unwired")
        mod.register(reg)
        names = {s.name for s in reg._specs.values()}
    assert names & {"cache.status", "cache.warm"}, (
        f"cache_tools 里找不到那两个声明：它可能在改名后失去了落点（读到 {sorted(names)}）")


def test_the_wiring_decision_is_written_down() -> None:
    """那个决定必须写在施工单里（没有这一句，就等于没人做过这个决定）。"""
    doc = pathlib.Path(__file__).resolve().parents[2] / "draft" / "150-缺陷修复施工单-20261024.md"
    assert doc.exists(), f"施工单不见了：{doc}"
    text = doc.read_text(encoding="utf-8")
    assert "cache_tools" in text and "未接线" in text, "施工单里没有记这条决定"

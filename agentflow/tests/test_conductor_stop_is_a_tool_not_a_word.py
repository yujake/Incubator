# -*- coding: utf-8 -*-
"""优雅停是主控的工具/动作，不靠单词匹配（业主 2026-10-17 口径）。

> *"优雅停是主控的工具或动作，用户只要表达出相关意思，主控就会启动该动作，不靠单词匹配。"*

这条口径在代码侧体现为三件事，本文件逐条钉住：

1. 工具在：`conductor.stop` 必须在主控的工具面上（它是"停"的正路）；
2. 旁路没了：`autonomy.STOP_TOKEN` 已删除，且源码里没有任何活引用
   （字面匹配必然漏：中文「停」「收工」一个都不认）；
3. 描述侧对齐：主控的声明文本里必须写着"用户表达出停意 ⇒ 调 `conductor.stop`"，
   并说明"不靠单词匹配"与"默认优雅、明确要立刻停才 force" —— 否则模型不知道该用这件工具。
"""

from __future__ import annotations

import pathlib

from agentflow.specs.m import SPEC

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "agentflow"


def test_conductor_stop_is_on_the_masters_surface() -> None:
    """工具在：主控看得到 `conductor.stop`（这是"停"的正路）。"""
    from agentflow.tools import build_registry
    from agentflow.store import Store
    import tempfile

    ws = pathlib.Path(tempfile.mkdtemp())
    st = Store(ws)
    st.init()
    reg = build_registry(store=st, workspace_root=ws).registry
    names = list(reg.names()) if hasattr(reg, "names") else []
    assert "conductor.stop" in names, "主控的工具面上没有 conductor.stop"


def test_the_stop_token_bypass_is_gone() -> None:
    """旁路没了：`STOP_TOKEN` 不再被定义，也没有活引用（注释里的说明不算）。"""
    import re

    autonomy = (SRC / "autonomy.py").read_text(encoding="utf-8")
    # 只看非注释的定义行（说明注释里会引用旧常量名，那是留档、不是旁路）。
    defines = [ln for ln in autonomy.splitlines()
               if re.match(r"^\s*STOP_TOKEN\s*=", ln) and not ln.lstrip().startswith("#")]
    assert defines == [], f"**字面匹配旁路还在**（业主口径已要求删除）：{defines}"
    live = []
    for path in SRC.rglob("*.py"):
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if "STOP_TOKEN" in line and not line.lstrip().startswith("#") \
                    and "已删除" not in line and "NameError" not in line:
                live.append(f"{path.name}:{n}")
    assert live == [], f"还有活引用：{live}"


def test_the_declaration_tells_the_master_to_use_the_tool() -> None:
    """描述侧对齐：声明里写着"用户表达停意 ⇒ 调 `conductor.stop`"，且不靠单词匹配。"""
    text = "\n".join(SPEC.brief.policy)
    assert "conductor.stop" in text, "主控的声明里没写该调哪个工具 ⇒ 它不知道'停'怎么执行"
    assert "不靠单词匹配" in text, "没写'不靠单词匹配' ⇒ 容易被读回字面匹配那一套"
    assert "force=true" in text, "没写 force 的边界 ⇒ 模型可能一上来就硬杀"

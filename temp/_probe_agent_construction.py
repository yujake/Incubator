# -*- coding: utf-8 -*-
"""探针：八个角色**只给 store**（A/B 另给必需依赖）时能不能建起来，以及它们的工具面。

这决定 host 的工厂要不要替它们装工具，还是像仓里其它调用点那样留 `tools=None`。
A 用 `FixtureProvider`（离线、确定性）—— 只为把构造跑通，不出网。

用法：`python -B temp/_probe_agent_construction.py`
退出码：0=全部建成 · 1=有建不成的（逐条打印）
"""

from __future__ import annotations

import pathlib
import shutil
import sys
import tempfile

sys.path.insert(0, r"D:\Incubator\agentflow\src")


def main() -> int:
    """逐个角色构造并打印工具面。"""
    from agentflow.agent_a import AgentA
    from agentflow.agent_b import AgentB
    from agentflow.agent_c import AgentC
    from agentflow.agent_d import AgentD
    from agentflow.agent_e import AgentE
    from agentflow.agent_f import AgentF
    from agentflow.agent_g import AgentG
    from agentflow.agent_h import AgentH
    from agentflow.extract import extract_text
    from agentflow.llm import RuleExtractor
    from agentflow.providers import FixtureProvider
    from agentflow.store import Store

    root = pathlib.Path(tempfile.mkdtemp(prefix="probe-ctor-"))
    st = Store(root)
    st.init()
    # A 需要一个 fixture 文件；给它一个最小的
    fx = root / "demo" / "fixtures"
    fx.mkdir(parents=True, exist_ok=True)
    (fx / "candidates.json").write_text("[]", encoding="utf-8")

    problems: list[str] = []
    made: dict[str, object] = {}
    plans = [
        ("A", lambda: AgentA(st, providers=[FixtureProvider(fx / "candidates.json")])),
        ("B", lambda: AgentB(st, extractor=RuleExtractor(), extract_text=extract_text)),
        ("C", lambda: AgentC(st)),
        ("D", lambda: AgentD(st)),
        ("E", lambda: AgentE(st, workspace_root=root)),
        ("F", lambda: AgentF(st)),
        ("G", lambda: AgentG(st, workspace_root=root)),
        ("H", lambda: AgentH(st)),
    ]
    for role, fn in plans:
        try:
            obj = fn()
        except Exception as exc:  # noqa: BLE001（探针要把异常原样打出来）
            print(f"{role}: 建不起来 -> {type(exc).__name__}: {exc}")
            problems.append(f"{role} 只给 store 建不起来：{type(exc).__name__}: {exc}")
            continue
        made[role] = obj
        tools = getattr(obj, "tools", None)
        n = len(tools.names()) if hasattr(tools, "names") else None
        print(f"{role}: ok  类={type(obj).__name__}  tools={type(tools).__name__ if tools else None}"
              f"（{n} 件）  actor={getattr(obj, 'actor', None)!r}")
    # D/F 的交叉链接：D 拿 C、F 拿 E（构造期定死"谁能叫谁"）
    if "C" in made and "E" in made:
        try:
            AgentD(st, c=made["C"])
            AgentF(st, e=made["E"])
            print("交叉链接：AgentD(c=C) / AgentF(e=E) 均可建")
        except Exception as exc:  # noqa: BLE001
            print(f"交叉链接建不起来 -> {type(exc).__name__}: {exc}")
            problems.append(f"交叉链接建不起来：{type(exc).__name__}: {exc}")
    shutil.rmtree(root, ignore_errors=True)

    print()
    if problems:
        for p in problems:
            print("[不符]", p)
        return 1
    print("[通过] 八个角色只给 store（A/B 另给必需依赖）都能建起来")
    return 0


if __name__ == "__main__":
    sys.exit(main())

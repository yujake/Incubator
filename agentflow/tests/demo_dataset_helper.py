"""测试用的演示数据集构造器（薄包装）。

为什么要单独一个模块：`tools/make_demo_dataset.py` 不是包的一部分，只能按路径
加载；`test_agent_c.py` / `test_pipeline.py` / `test_tools_graph_trace.py` 都要用它，
把加载逻辑抄三遍迟早会漂移。它只负责"构造到指定目录"，不碰任何演示目录。

数据集规模（见 `make_demo_dataset.py` 的 docstring）：10 概念 / 9 文献 / 15 关系，
含 2 跳与 3 跳路径、一条 `quote_verified=False`、一条 `status=suspect`、
一个 degree=0 的孤立概念、以及真实的文献文本文件。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

#: `test/test1/`（tests/ 的上一级）。
_TEST1 = Path(__file__).resolve().parents[1]

_mod: Any = None


def _load() -> Any:
    global _mod
    if _mod is None:
        path = _TEST1 / "tools" / "make_demo_dataset.py"
        spec = importlib.util.spec_from_file_location("agentflow_make_demo_dataset", path)
        assert spec is not None and spec.loader is not None, f"无法加载 {path}"
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _mod = mod
    return _mod


def build_demo(dest: str | Path) -> Path:
    """在 `dest` 重建一份演示数据集（已存在则整体删除重建），返回 dest。"""
    return Path(_load().build(Path(dest)))


#: 演示数据集里那条 3 跳链（群→环同态→素理想→域）的关系代号，供溯源用例直接引用。
DEMO_CHAIN_3HOPS = ["0009", "0010", "0005"]
#: 演示数据集里那条 2 跳链（阿贝尔群→群→子群方向的关系代号示例）。
DEMO_DIRECT = "0007"

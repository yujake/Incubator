"""abflow：A/B 双智能体的文献流水线原型。

本包遵循 ``DESIGN.md`` §4 的模块划分。``__init__`` **刻意不 import 任何子模块**：
子模块之间存在惰性互相引用（如 providers ↔ fetch 的自检块），在包初始化阶段
import 它们会形成循环依赖并让 `python -c "import abflow.providers"` 这类
单模块导入变慢变脆。使用方按需 ``from abflow.providers import OpenAlexProvider``。
"""

from __future__ import annotations

__version__ = "0.1.0"
__schema_version__ = 1  # 与 data/*.json 的 schema_version 对应（DESIGN.md §1）

__all__ = ["__version__", "__schema_version__"]

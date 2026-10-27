"""A 智能体：文献搜索。

职责（需求原文）：接收文献搜索请求清单 → 搜索 → 把文献下载到本地 → 维护文献表 → 把请求标记完成。

四个刻意的设计选择：

1. 锁只覆盖簿记，不覆盖网络：流程切成"短事务声明租约 → 无锁做 I/O → 短事务提交"，代价是提交时
   必须在锁内重做一次判重（另一个 A 实例可能已抢先登记同一篇），这一步不能省。
2. 先落文献行，再置请求完成（DESIGN.md §2.4）；崩溃后请求仍是未完成，重跑靠 `dedup_key` 幂等。
3. 下载失败不算请求失败：文献行照常登记（`path=null`），"我知道有这篇论文但拿不到全文"本身就是结果。
4. 取任务只排队、不抢占（I7）：排序键只有一份实现（`interactions.order_pending_requests`），本模块
   不另写一套 —— 两套判据并存会让"high 优先"静默失效，这正是 `RuleExtractor` docstring 警告过的
   "两个模块各持一套判据"；不抢占的代价论证见 `DESIGN-INTERACTIONS.md` §5 待决问题 3。

拆包（`goal-7f5116c1` M6/M7）不许改变 import 面：原来能在 `agentflow.agent_a` 下 import 到的名字
（含私有名，也包括 `_selftest`）逐个再导出；动作各自在 `agent_a/<动作>.py`，自检入口在同目录
`__main__.py`，自检本体在 `agent_a/selftest.py`（2026-10-26 从 `core.py` 搬出来：自检既不是
动作也不是装配，而 `core.py` 那一段把文件撑过了 `src_files_gt800_lines` 的基线）。
"""
from __future__ import annotations

from .core import AgentA
from .selftest import (_selftest,
)
from ._support import (ARunResult, AgentBrief, AgentSpec, Any, ClaimOutcome, D, Iterable, Path, 
    S, SPEC, Store, StoreError, T, X, annotations, dataclass, lease_expired, make_lease, 
    shutil, tempfile,
)
from ..specs.a import SPEC

__all__ = ["AgentA", "SPEC"]

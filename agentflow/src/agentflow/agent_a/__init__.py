"""A 智能体：文献搜索。

职责（需求原文）：接收文献搜索请求清单 → 搜索 → 把文献下载到本地 → 维护文献表 → 把请求标记完成。

四个刻意的设计选择：

1. 锁只覆盖簿记，不覆盖网络。搜索与下载可能耗时数十秒；若持锁做这些事，
   B 智能体会被整段时间阻塞。因此流程切成"短事务声明租约 → 无锁做 I/O → 短事务提交"。
   代价是提交时必须在锁内重做一次判重（另一个 A 实例可能已抢先登记同一篇），
   这一步不能省。
2. 先落文献行，再置请求完成（DESIGN.md §2.4）。崩溃时请求仍是未完成，
   重跑靠 `dedup_key` 幂等，不会重复登记。
3. 下载失败不算请求失败。文献行照常登记（`path=null`），
   因为"我知道有这篇论文但拿不到全文"本身就是有价值的结果；B 会跳过它并计数。
4. 取任务只做排队，不做抢占（I7）。A 按 `interactions.order_pending_requests`
   给出的顺序取任务，排序键是"优先级 → 租约是否过期 → 提交时间 → request_id"。
   这里有两条硬约束：

   - 排序键只有那一份实现，本模块不另写一套（哪怕只是 `sort(key=...)`）。
     一旦 A 的取任务顺序与提交方（C/D）的派发顺序各持一套判据，
     "high 优先"就会静默失效 —— 不报错，只是最关键的矛盾永远排在后面。
     这正是 `RuleExtractor` docstring 警告过的"两个模块各持一套判据"。
   - 不抢占：正在跑的 A 已经付掉了检索与下载的成本，被高优先级请求打断只会让
     两条请求都变慢，还在 staging 里留下一堆半成品；收益小于代价。
     高优先级请求在下一次 `_claim()` 时自然排到队首。
     见 `DESIGN-INTERACTIONS.md` §5 待决问题 3。

`goal-7f5116c1` M6/M7 把本模块拆成包：这里只做入口与命名空间的保持 ——
拆包不许改变 import 面，所以原来能在 `agentflow.agent_a` 下 import 到的名字（含私有名，也包括住在 `core.py` 的
`_selftest` / `selftest`）都逐个再导出；动作各自在 `agent_a/<动作>.py`，
`python -m agentflow.agent_a` 的自检入口在同目录 `__main__.py`。
"""
from __future__ import annotations

from .core import AgentA
from .core import (_selftest,
)
from ._support import (ARunResult, AgentBrief, AgentSpec, Any, ClaimOutcome, D, Iterable, Path, 
    S, SPEC, Store, StoreError, T, X, annotations, dataclass, lease_expired, make_lease, 
    shutil, tempfile,
)
from ..specs.a import SPEC

__all__ = ["AgentA", "SPEC"]

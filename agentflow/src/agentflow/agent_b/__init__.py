"""B 智能体：文献整理。

职责：处理 A 新搜到的文献 → 维护概念表与关系表 → 处理完一篇就把文献表的处理情况置 1；
每条关系录入前检查是否已有相同或几乎相同的表述。几个刻意的设计选择：

1. 概念名 → 概念代号 的解析在锁内做（否则两个 B 实例可能各自为"群"新建概念）。
   判重是业务规则，解析唯一性是数据结构约束，必须靠锁。
2. `related_concepts` 由关系表整体派生，不做增量 append：结果与"append+排序+去重"
   一致，但漏更新会自愈。
3. 引文校验失败的条目仍然落库、置 `status="suspect"`：丢掉它等于隐藏证据。
4. 抽取失败不置 `processed`：`processed` 的语义是"B 处理完了"；靠租约到期重试。
5. 写入期一致性闸门（I6）必须是纯函数（`interactions.check_conflict`，签名里没有
   store），否则同一进程内 `filelock` 重入。闸门三态：`True` 矛盾 / `False` 不矛盾 /
   `None`+`checked=False` 没检查；"没检查"绝不允许被压成"不冲突"。
6. 定向重抽取（I4）只动 `status="pending"` 的目标关系；事务里刻意不声明 `literature`
   表 —— 把 `processed` 置回 `False` 会触发全量重抽。
7. 结构重复的合并（I5）：C 只提候选，B 复核两路独立证据才合并，且必须留下可被反驳的
   理由。宁可漏合并，也不错误合并。

拆包只做入口与命名空间保持：import 面不许变，动作各自在 `agent_b/<动作>.py`。
"""
from __future__ import annotations

from .core import AgentB
from .core import (_selftest,
)
from ._support import (AgentBrief, AgentSpec, Any, BClaimOutcome, BRunResult, D, I, Iterable, 
    Mapping, NOTE_LIMIT, Path, QUOTE_OUT_OF_DECLARED_RANGE, REPROCESS_RESULTS, S, SPEC, 
    Sequence, Store, StoreError, T, _PASSAGE_RE, _passages, annotations, check_quote, 
    dataclass, field, lease_expired, make_lease, quoteverify, re,
)
from ..specs.b import SPEC

__all__ = ["AgentB", "SPEC"]

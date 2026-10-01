"""B 智能体：文献整理。

职责（需求原文）：处理 A 新搜到的文献 → 维护概念表与关系表 → 处理完一篇就把文献表的
处理情况置 1；每条关系录入前检查是否已有相同或几乎相同的表述。

四个刻意的设计选择：

1. 概念名 → 概念代号 的解析在锁内做。否则两个 B 实例可能各自为"群"新建一个概念，
   产生两个概念代号指向同一概念。这与"判重"是两回事：判重是业务规则，解析唯一性是
   数据结构约束，必须靠锁。
2. `related_concepts` 由关系表整体派生，不做增量 append（DESIGN.md §6.2）。
   需求说"每次 append 时保持升序"—— 整体重算的结果与"append+排序+去重"一致，
   但多了一个性质：漏更新会自愈，不需要靠人记得同步。
3. 引文校验失败的条目仍然落库，但置 `status="suspect"`。丢掉它等于隐藏证据；
   落库并标黄，才能让人看到"模型在哪些地方引不出原文"。
4. 抽取失败不置 `processed`。`processed` 的语义是"B 处理完了"，
   处理抛异常就不是处理完了；靠租约到期重试，超过次数才显式记错。

DESIGN-INTERACTIONS.md §1 新增的三件事（I6 / I4 / I5 的决定侧）：

5. 写入期一致性闸门（I6）：关系落库前问一句"这条与图里已有的矛盾吗"。
   这个闸门必须是纯函数（`interactions.check_conflict`，签名里没有 store）：
   B 在自己的事务内调用它，若它去查 store 就是同一进程内 `filelock` 重入
   （轻则抛错、重则死锁）。已有关系由 B 用 `tx.rows("relations")` 读好传进去，
   唯一入口是 :meth:`AgentB._conflict_scope`。
   闸门是三态的：`True` 矛盾 / `False` 不矛盾 / `None`+`checked=False` 没检查；
   "没检查"绝不允许被压成"不冲突"（见 `_conflict_check` 字段与两个计数器）。
6. 定向重抽取（I4）：处理 `reprocess_requests` 里 `status="pending"` 的行，
   只动目标关系。重抽取事务里刻意不声明 `literature` 表 ——
   把 `processed` 置回 `False` 会触发全量重抽，这是 I4 明写的幂等陷阱，
   不声明该表就是"结构上不可能犯这个错"。
7. 结构重复的合并决定权（I5）：C 只提候选，B 复核两路独立证据
   （结构等价 + 名字侧）才合并，且合并必须留下可被人反驳的理由。
   宁可漏合并（少省一点空间）也不错误合并（把两条知识并成一条，不可逆）。

`goal-7f5116c1` M6/M7 把本模块拆成包：这里只做入口与命名空间的保持 ——
拆包不许改变 import 面，所以原来能在 `agentflow.agent_b` 下 import 到的名字（含私有名，也包括住在 `core.py` 的
`_selftest` / `selftest`）都逐个再导出；动作各自在 `agent_b/<动作>.py`，
`python -m agentflow.agent_b` 的自检入口在同目录 `__main__.py`。
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

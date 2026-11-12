"""agentflow：面向数学研究的多智能体协同框架（一个主控 M + 若干角色）。

角色按 `specs/*.py` 注册，编排水位见 ``conductor.py``，规格见 ``docs/ROLE-SPECS.md``。
``__init__`` 刻意不 import 任何子模块（下面那个契约版本除外）：子模块之间存在惰性
互相引用，在包初始化阶段 import 它们会形成循环依赖。使用方按需
``from agentflow.providers import OpenAlexProvider``。
"""

from __future__ import annotations

__version__ = "1.0.0"
#: 与 `data/*.json` 的 `schema_version` 对应（权威定义在 `schema.SCHEMA_VERSION`）。
#: 两处必须同时升：`tests/test_fc05_contract.py` 判它们相等，发布门的 `item_contract`
#: 也判 `schema_version_pkg != schema_version_mod` ⇒ fail。
__schema_version__ = 2

#: 跨智能体契约版本。与 `__schema_version__` 是两件不同的事：前者管数据格式
#: （快照能不能被读进来），后者管函数契约（`interactions` 里跨智能体判据的语义与签名）。
#:
#: 只要另一个角色的行为会因为这次改动而不同，就必须 +1：
#:   1. 判据的取值集合或返回值形状变了（含词表改动 —— 调用方按词表分支）；
#:   2. 判据的语义变了而签名没变（最隐蔽：类型检查、单测、调用方全都不会红）；
#:   3. 新增一个跨角色判据（别的角色从此必须按它行事）。
#: 纯内部重构、注释、只影响单个角色且无跨角色消费者的实现细节，不必 +1。
#:
#: 权威定义在 `interactions.CONTRACT_VERSION`；这里引出来给 release check 与文档读。
from .interactions import CONTRACT_VERSION  # noqa: E402

__all__ = ["__version__", "__schema_version__", "CONTRACT_VERSION"]

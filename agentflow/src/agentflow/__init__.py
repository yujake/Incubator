"""agentflow：面向数学研究的多智能体协同框架（正式版，一个主控 + A–H 八个角色）。

角色与职责：M（主控，按需召唤 A–H，A–H 之间也可以互相唤起）/ A 文献检索 / B 文献整理 /
C 只读关系分析 / D 研究 / E 数值实验与形式化验证 / F 多轮难题攻坚 / G 撰写 / H 审校。
规格见 ``docs/ROLE-SPECS.md``，规范见 ``DEVELOPMENT.md``，主控的编排在 ``conductor.py``。

本包的原型在 ``D:\\Incubator\\test\\test1``（包名 ``abflow``，只有 A/B 两个角色），
两者刻意分开：原型是"跑通"的证据，正式版是"可发布"的形态。

``__init__`` 刻意不 import 任何子模块（除了下面那个版本号）：
子模块之间存在惰性互相引用（如 providers ↔ fetch 的自检块），在包初始化阶段
import 它们会形成循环依赖并让 `python -c "import agentflow.providers"` 这类
单模块导入变慢变脆。使用方按需 ``from agentflow.providers import OpenAlexProvider``。
"""

from __future__ import annotations

__version__ = "1.0.0"
__schema_version__ = 1  # 与 data/*.json 的 schema_version 对应（见 `schema.SCHEMA_VERSION`）

#: 跨智能体契约的版本。
#:
#: 与 `__schema_version__` 是两件不同的事，必须分开升：
#:   - `__schema_version__` 管数据格式（快照能不能被读进来）；
#:   - `CONTRACT_VERSION` 管函数契约（`interactions` 里那些跨智能体判据的
#:     语义与签名）。同一个 schema 版本下，`check_conflict` 的语义可能变
#:     （本项目真的发生过：矛盾判据从"否定词出现与否不一致"收紧成"明确对立主张"），
#:     而数据格式一个字都没变。
#:
#: ## 什么时候必须 +1（判据，不是感觉）
#:
#: 只要另一个角色的行为会因为这次改动而不同，就必须 +1。具体三类：
#:   1. `interactions` 里某个判据的取值集合或返回值形状变了
#:      （例如 `decide_relation` 多出一种 `kind`，或 `check_conflict` 的
#:      `reason` 换了词表）—— 改词表也算：调用方在按词表分支；
#:   2. 某个判据的语义变了而签名没变（最隐蔽的一类：类型检查、单测
#:      与调用方全都不会红）；
#:   3. 新增一个跨角色的判据（别的角色从此必须按它行事）。
#:
#: 不必 +1 的：纯内部重构、注释、只影响单个角色内部且没有任何跨角色消费者
#: 的实现细节。判据是"有没有第二个角色依赖它"，不是"改动大不大"。
#:
#: 为什么要版本号：`interactions` 是冻结契约，而"A 与 B 各自按不同版本的
#: 契约理解同一个字段"这种分裂没有任何报错。有了版本号，装配期就能断言
#: "调用方与契约的版本一致"，把它变成一声响（`scripts/release_check.py` 的第 7 项
#: 就是这条断言）。
#:
#: 权威定义在 `interactions.CONTRACT_VERSION`（契约模块自己持有自己的版本）；
#: 这里只是把它引出来给外部（release check / 文档）读。
from .interactions import CONTRACT_VERSION  # noqa: E402

__all__ = ["__version__", "__schema_version__", "CONTRACT_VERSION"]

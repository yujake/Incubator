# -*- coding: utf-8 -*-
"""智能体 L：Lean 形式化者（照 E 的 Lean 面复制出来的可运行角色）。

## 一句话

L 只做一件事：把 B 登记的那条命题与它的证明链路忠实搬进 Lean 源码、交给检查器
真跑，并如实报 `verified` / `failed` / `unknown`；跑完那一份可以登记成一行
`experiments`（`formal.record`，`method="formal"`）。协作面（业主 2026-10-22 晚的
最终裁定，逐字）：「只有 B 可以派 L，L 允许派 C 来梳理证明链，消费 B 的定理证明库，
可向 B 汇报形式化过程中遇到的困难、要求 B 完善证明并重新得到 V 签，若缺陷严重，
B 应通知 D 开展研究处理证明难点」—— 入边恰好 `B → L`（`formalize` / `check_formal` /
`record` 由 B 派）、出边恰好 `L → C`、可召唤；汇报与升级的落点在 `agent_l/report.py`
与 `agent_b/proof_research.py`（都是既有的 `agent_message` 收件箱）。声明在
`specs/l.py`（与 `specs/b.py`），读数由 `capabilities` 从声明派生 ——
本模块不写任何角色名单或计数。

## 与 E 的边界（业主 2026-10-22 的施工单）

- E 的代码一行没删、行为没改：L 复用 E 的 `_CheckFormal` 混入与
  `verify.check_formal` 桥接层，只在前者前面加了一道 Lean 自检闸；
- L 多出两格 E 没有的动作：`formalize`（写盘 + 检查 + 三态一次成型，
  理由是"写没写盘"必须是一条机器读数，而不是一句自述）与 `record`
  （把一次检查登记成 `experiments` 的一行，`method="formal"`）；
- 两个角色的理由词表是同一份（`agent_l._support` 从 `agent_e._support` import，
  只追加自检那三档与 `record` 那四档）。

## 落点

- `agent_l/core.py`：`AgentL` 的骨架、路径守卫、自检闸、结论三态形状；
- `agent_l/check_formal.py`：E 那条路的同一个实现 + 前置自检闸；
- `agent_l/formalize.py`：写 `.lean` 落盘 + 检查（`code/formal/<声明名>.lean`）；
- `agent_l/record.py`：把一次检查登记成 `experiments` 的一行（现跑一次对账，
  且不动 `statements`）；
- `tools/formal_tools.py`：L 的三件工具（`formal.formalize` / `formal.check_formal` /
  `formal.record`），工具 handler 惰性构造 AgentL（与 E 的 `verify_tools` 同一个形状）。

判据：`tests/test_l_formalizes_what_b_says.py`（零模型、tmp 工作区、真 lean 可选、
协作面与 experiments 行）与 `tests/test_l_collab_and_secretary.py`（F→L 边、
秘书台账 / 名册 / 读写面）。
"""
from __future__ import annotations

from ._support import (
    FAILED_REASONS,
    FORMAL_DIR,
    FORMAL_REASONS,
    FORMAL_REASONS_L,
    RECORD_REASONS,
    SELFCHECK_REASONS,
    STATEMENT_CLAIM_KEY_PREFIX,
    THREE_STATES,
    ExperimentError,
)
from .check_formal import _CheckFormalL
from .core import AgentL, install_l_tools
from .formalize import declaration_name_in
from .record import _Record

__all__ = [
    "AgentL",
    "ExperimentError",
    "FAILED_REASONS",
    "FORMAL_DIR",
    "FORMAL_REASONS",
    "FORMAL_REASONS_L",
    "RECORD_REASONS",
    "SELFCHECK_REASONS",
    "STATEMENT_CLAIM_KEY_PREFIX",
    "THREE_STATES",
    "_Record",
    "declaration_name_in",
    "install_l_tools",
]

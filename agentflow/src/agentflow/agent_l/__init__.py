# -*- coding: utf-8 -*-
"""智能体 L：Lean 形式化者（照 E 的 Lean 面复制出来的可运行角色）。

L 只做一件事：把 B 登记的那条命题与它的证明链路忠实搬进 Lean 源码、交给检查器
真跑，如实报 `verified` / `failed` / `unknown`；跑完那一份可登记成一行
`experiments`（`formal.record`，`method="formal"`）。协作面：只有 B 可以派 L，
L 允许派 C 梳理证明链，消费 B 的定理证明库，可向 B 汇报困难、要求 B 完善证明并
重新拿 V 签；缺陷严重时 B 通知 D 开研究 —— 入边恰好 `B → L`（`formalize` /
`check_formal` / `record` 由 B 派）、出边恰好 `L → C`、可召唤。汇报的落点在
`agent_l/report.py`（既有的 `agent_message` 收件箱，受控形态在 `proofreport`）；
"缺陷严重 ⇒ B 通知 D"那一跳不在这条消息链上：B 按 `specs/b.py` 的 `PROOF_CHANNEL`
第⑥步走 `summon` 形状派 D（改前 `agent_b/proof_research.py` 那个只活在测试里的程序入口
已退场，判据 `tests/test_proofchan_upgrade_is_the_summon_path.py`）。声明在 `specs/l.py`
（与 `specs/b.py`），读数由 `capabilities` 从声明
派生 —— 本模块不写任何角色名单或计数。

与 E 的边界：E 的动作面已经不再有形式化 —— `AgentE` 上没有 `check_formal`，
`run_experiment(method="formal")` 在第一句就以 `formal_not_in_e` 受控拒绝、一行都不落。
实现体 `agent_e/check_formal._CheckFormal` 仍留在原处、由 L 的 `_CheckFormalL` 继承
（桥接层与路径守卫只有一份）；L 只在它前面加一道 Lean 自检闸，不改 E 的其余动作与行为。
L 多出两格 E 没有的动作：`formalize`（写盘 + 检查 + 三态一次成型 —— "写没写盘"必须是机器读数，
不是一句自述）与 `record`（把一次检查登记成 `experiments` 的一行）。两个角色的
理由词表是同一份（`agent_l._support` 从 `agent_e._support` import，只追加自检那
三档与 `record` 那八档）。

落点：`agent_l/core.py`（`AgentL` 骨架、路径守卫、自检闸、三态形状）；
`agent_l/check_formal.py`（E 那条路 + 前置自检闸）；`agent_l/formalize.py`（写
`.lean` 落盘 + 检查，落 `code/formal/<声明名>.lean`）；`agent_l/record.py`（把一次
检查登记成 `experiments` 的一行，现跑一次对账，且不动 `statements`）；
`tools/formal_tools.py`（L 的三件工具，handler 惰性构造 AgentL，与 E 的
`verify_tools` 同形）。

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
    "_Record",
    "declaration_name_in",
    "install_l_tools",
]

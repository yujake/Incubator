# -*- coding: utf-8 -*-
"""产物畸形的统一判据（well-formedness）—— 一处判据，读写两侧共用。

## 这一层补的是什么

"这个工作区的产物有没有畸形"此前没有一个能回答它的地方。畸形分散在十几类产物里：
`data/*.json` 的行、`out/vsigns/<sha>.json` 的侧文件、`reports/*-proof-*.md` 的稿头、
`out/roster/*-retired.jsonl` 的销号行、`ARTIFACTS.jsonl` 的 sha 对拍……每一类要么有
自己的一处判据（`artifacts.verify_entries` 管 sha、`store.validate_table` 管列类型、
`closing` 的验收格管阈值），要么一处都没有（`relations` 里"说回验通过却给不出区间"
就属于后者：真机 `projects/lp-ball-10` 的 27 条关系行全是这个形态，没有任何一条判据
说得出来）。于是同一种畸形在两处被读到的时候，常常给出两个口径；而"没人管"的那几类
只会静默地留在盘上。

本模块把"形状 / 词表 / 内部一致性 / 跨表指向"这几根轴的规则收在一处。它不做两件事：
不改任何表、不做任何修补、不当任何门的输入。它只回答一个问题，答案分三态：

- `ok` —— 该类产物查过了，没有畸形；
- `malformed` —— 查过了，有 Finding（每条带文件、位置、逐字读数、怎么改）；
- `unchecked` —— 没查成（文件读不出来、交叉核对要用的另一张表读不出来、规则没实现）。

`unchecked` 绝不折成 `ok`。这条纪律与 `scripts/noai_gate.py` / `scripts/usage_ledger_audit.py`
的退出码同源：0 = 干净，1 = 有畸形，2 = 没查成。

## 为什么规则也集中在这里（而不是各产物模块各写一份）

同一条规则的第二个副本，早晚会与第一个对同一个输入给出两个答案，而那两个答案之间没有
任何东西会报错。所以：

- 词表从权威处 import，不在这里另抄一份：`schema.py`（状态 / 原因码 / 角色 / 用量档）、
  `evidencebits.py`（等级 / 位名）、`manuscriptkind.py`（命题类型）、
  `manuscriptfamily.py`（四族与名字解析）、`litread.py`（全文档）、`litavail.py`。
- 已经在别处有唯一实现的读取器，这里只转发：JSONL 的坏行口径走 `jsonlfile.read_jsonl_state`；
  手稿头走 `proofregistry.parse_entry`；签块走 `vsigns.manuscript_sign_reading`；
  验收行的形状走 `closing._acceptance_row_problem`。
- 这里只写"判什么"（`RULES`），不写"怎么修"。修法写在每条 Finding 的 `detail` 里，由人读。

## 规则怎么被测试打桩（反真空）

每条规则登记在 `RULES[kind][name]` 里，`check_kind` 调用时才取。判据可以把某一条规则
打桩成"永远返回空"，然后断言对应的夹具从 `malformed` 变回 `ok` —— 这证明那一条规则
就是抓住这类畸形的那一条，而不是别的规则顺手抓到的。没有这个动作，"规则存在"与"规则
接上了"在输出上完全一样。

## 它与收工门的关系

没有关系，而且这是刻意的。业主口径（2026-11-21）：「畸形要看得见，而不是再拦一道」。
所以本模块的结论只接进只读读数面（`statusreport.collect` 的 `wellformed` 一格），
不新增任何 blocker，也不改变任何门的格。畸形被看见之后改不改、什么时候改，由人定。
"""

from __future__ import annotations

# 13 个规则模块必须在包初始化时全部导入：`RULES[kind][name]` 由 `@_rule` 在导入那一刻登记 ——
# 少导入一个模块，那一类产物的规则就一条都没接上，而输出上"规则存在"与"规则接上了"完全一样
# （判据把某条规则打桩掉仍能翻绿，正是因为它真的被登记过）。
from . import acceptance, artifacts, candidates, ledger, literature  # noqa: F401
from . import manuscripts, proofs, relations, roster, sessions, signs  # noqa: F401
from . import statements, tasks  # noqa: F401
from .driver import WorkspaceReport, check_kind, check_workspace, workspace_reading
from .reader import _SPECS
from .registry import RULES
from .states import (EXIT_MALFORMED, EXIT_OK, EXIT_UNCHECKED, KINDS, MALFORMED, OK,
                     SEVERITIES, STATES, UNCHECKED, CheckResult, Finding,
                     Malformation)

__all__ = [
    "CheckResult",
    "EXIT_MALFORMED",
    "EXIT_OK",
    "EXIT_UNCHECKED",
    "Finding",
    "KINDS",
    "MALFORMED",
    "Malformation",
    "OK",
    "RULES",
    "SEVERITIES",
    "STATES",
    "UNCHECKED",
    "WorkspaceReport",
    "check_kind",
    "check_workspace",
    "workspace_reading",
]

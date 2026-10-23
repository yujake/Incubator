"""智能体 E：数值实验与形式化验证。

设计基线：``test/test1/DESIGN-ROLES.md`` §2.1 与 `schema.Experiment` 的硬约束。

## E 到底在做什么（一句话）

E 产出证据，不产出结论。

这个分工不是文字游戏，它是本模块每一行代码的由来。一个"能跑实验"的智能体
最自然也最危险的越界，就是把"我算了几千个点都对"写成"已证明" ——
数学里数值实验不构成证明（FC-22）。所以：

- `Experiment.evidence_kind` 是结构化字段，不是注释里的告诫；
- 计算类方法（numeric / symbolic / exhaustive_search）在 schema 层就拿不到
  `evidence_kind="proof"`，写入的那一刻就炸；
- 脚本自己声称 `proof` 会被降到 cross_check 并把这件事记进 `notes`
  （见 :meth:`AgentE.run_experiment` 的推导规则第 4 条）。

## 为什么"脚本自报 evidence_kind"必须被降级

这是本模块最反直觉的一条规矩，值得写清楚：

让被判定的对象自己当判官，等于没有判官。

`script_path` 指向的脚本是被检验的对象（它算出了结论）。如果它同时能决定
"这个结论算不算证明"，那么整条证据链的强度就由最不可信的一环决定 ——
而这一环恰恰是最容易"顺手写一句 `{"evidence_kind": "proof"}`"的地方。
更糟的是：这种越权不会报任何错，表里只会多一条看起来很漂亮的 proof。

所以 E 的态度是：脚本只能报告"我观察到了什么"（result / observations /
counterexample），证据等级由框架按 method 推导。脚本说自己是 proof，
E 记下"脚本声称过 proof，已被拒绝"这件事 —— 拒绝本身要留痕，
否则三个月后没人能解释这条记录的等级为什么比脚本里写的低。

## 推导规则（唯一权威表述，实现见 `_derive`）

输入是「退出码 + 脚本 stdout 里的一行结构化结论」：

1. `exit_code != 0`（崩溃 / 超时 / 启动失败）
   ⇒ `result="inconclusive"`, `negation_kind="no_local_evidence"`,
     `evidence_kind="heuristic"`。绝不允许把崩溃写成支持（FC-21/F C-25）。
   理由：崩溃只说明"这次没跑成"，它既不是对命题的支持也不是反驳。
2. 脚本在 stdout 打印了一行 `REPRO_RESULT: {json}`（约定格式见
   :data:`REPRO_RESULT_PREFIX`）：
   - `result` 必须 ∈ `EXPERIMENT_RESULTS`，否则整条结论视为格式非法，
     按第 3 条处理（宁可不认，也不要猜）；
   - `result="refutes"` ⇒ `negation_kind="disproved"` 且必须有 `counterexample`。
     缺反例时 `Experiment.validate()` 会抛 —— 让它抛：那说明脚本在声称
     一个它没给出依据的证否，这正是最该炸的地方；
   - `result="supports"` ⇒ `negation_kind="not_proved"`
     （数值支持只能是"未证明"，不是"已证明"）；
   - `result="inconclusive"` ⇒ `negation_kind="no_local_evidence"`；
   - `evidence_kind` 由 method 推导，脚本自报值只作为"它想声称什么"被记录：
     计算类方法一律 `cross_check`（自报 proof ⇒ 降级 + 记 notes）。
3. 脚本没有打印那行（或格式非法）
   ⇒ `result="inconclusive"`, `negation_kind="no_local_evidence"`,
     `evidence_kind="heuristic"`，`notes` 写明"脚本未给出结构化结论"。

## 形式化不在这一岗（业主 2026-10-23 晚：「E 侧与 Lean 相关的工具和动作都该清干净」）

本模块的动作表没有 `check_formal`，`AgentE` 上也没有这个方法；`run_experiment` 收到
`method="formal"` 时在第一句以受控理由码 `formal_not_in_e` 拒绝，一行都不落、也不起
检查器。形式化那一岗的实现体（`check_formal.py` 的 `_CheckFormal`）仍然留在本包里 ——
L 的 `_CheckFormalL` 继承它，桥接层（`verify_tools.check_formal` 那个纯函数）只有一份
实现。这条继承关系是"L 复用 E 的实现"，不是"E 还能形式化"。

`name` / `imports` 只服务形式化那一支：动作表与工具 schema 上都没有它们（工具面因此
传不进来）。方法层仍然收着这两个形参，只是为了把"传了也不做"变成一句受控拒绝 ——
F 的派活路径会按同一份子目标把它们传下来，而让它 TypeError 会把"调用方多给了一个
参数"读成"E 内部有 bug"。

## 三态纪律在模块里的落点

- `evidence_for(claim_key=None, for_question_id=None)` ⇒ `checked=False`（没查）；
  给了参数但库里没有 ⇒ `checked=True, experiments=[], proved=False`（查了、没有）。
- `check_formal` 的那套受控理由（`no_backend` / `timeout` / `tool_crashed` /
  `source_unreadable` / `lean_disabled` / `no_script`）随 `_CheckFormal` 一起服务 L；
  把"没查成"的判据写成 `checked is False` 会把几档全部折叠成第一档。
- `proved` 只有在存在 proof 级实验时才为 True（FC-22）。

## 已知边界（如实标注，不要读成缺陷）

- `params` / `artifact_paths` 是信息性字段：本模块不会把它们变成命令行参数，
  也不会去读那些产物文件。记录它们是为了"这条实验当时是怎么跑的"可被复核。
- 判读不走 LLM（`llm` 只用于 `author_script` 写脚本，S-10(a)）：数值实验的判读必须是
  确定性的（FC-16）—— `run_experiment` / `_derive` / `_parse_conclusion` 一条缝调用都没有，
  判据见 `tests/test_agent_e_author_script.py::test_the_reading_path_never_calls_the_seam`。

`goal-7f5116c1` M6/M7 把本模块拆成包：这里只做入口与命名空间的保持 ——
拆包不许改变 import 面，所以原来能在 `agentflow.agent_e` 下 import 到的名字（含私有名，也包括住在 `core.py` 的
`_selftest` / `selftest`）都逐个再导出；动作各自在 `agent_e/<动作>.py`，
`python -m agentflow.agent_e` 的自检入口在同目录 `__main__.py`。
"""
from __future__ import annotations

from .core import AgentE
from .core import (selftest,
)
from ._support import (AgentBrief, AgentSpec, Any, COMPUTATIONAL_METHODS, ExperimentError, 
    FORMAL_REASONS, Mapping, Path, REPRO_RESULT_PREFIX, S, SPEC, Sequence, Store, ToolError, 
    ToolRegistry, VT, _DECLARED_NAME_RX, _FORMALGW_STATUSES, _FORMAL_REASON_BY_TOOL_REASON, 
    _NOT_CHECKED_REASONS, _NO_EVIDENCE_KIND, _OUTPUT_DIGEST_WIDTH, _STDOUT_SCAN_LIMIT, 
    _as_dict, _declared_name_note, _decode, _derive, _digest, _docstring_not_checked_reasons, 
    _extract_stdout_lines, _formal_status_suffix, _normalize_evidence_kind, _parse_conclusion, 
    _relpath, _result_reason, _which, _write_run_log, annotations, build_experiment, 
    declared_name_of_notes, install_e_tools, json, os, re, subprocess, sys, time,
)
from ._support import E_NO_FORMAL_REASON
from ..specs.e import SPEC

__all__ = [
    "AgentE",
    "E_NO_FORMAL_REASON",
    "ExperimentError",
    "FORMAL_REASONS",
    "REPRO_RESULT_PREFIX",
    "build_experiment",
    "declared_name_of_notes",
    "install_e_tools",
    "selftest",
    "SPEC",
]

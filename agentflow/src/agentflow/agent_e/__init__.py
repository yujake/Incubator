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

## 形式化路径（`method="formal"`）与计算类路径的分工

`method="formal"` 不走上面那三条规则：它把工作区里的 `.lean` 文件交给
`verify.check_formal`（唯一实现）真跑一次，判据全部来自检查器，而不是来自脚本的
自我陈述。这是本模块唯一能产出 `evidence_kind="proof"` 的入口，收口规则是：

1. 检查器返回 `verified` ⇒ 登记 `evidence_kind="proof"`、`result="supports"`、
   `negation_kind="not_proved"`、`verifier_output` 是检查器自己的那句话、
   `verifier_subject_key` 逐字等于本行的 `claim_key`（schema 硬约束 2/2b 要求）；
2. 检查器跑了但没通过（`compile_error` / `uses_sorry` / `extra_axioms` /
   `decl_mismatch`）⇒ `inconclusive` + `heuristic`：它给不出任何正面证据，
   所以不许落 `cross_check`（那是"另一个方法旁证过"，见 `formalgw.evidence_of`）；
3. 没查成（`timeout` / `import_unavailable` / `no_backend` / `tool_crashed` /
   `source_unreadable` / `param_error`）⇒ 同上，且 `notes` 里写明是哪一种。
   其中"E 自己的受控'没查成'理由"只有一处定义：本模块的 `_NOT_CHECKED_REASONS`
   （`no_backend` / `timeout` / `tool_crashed` / `source_unreadable` / `param_error`）
   —— 上面这一行必须覆盖它，导入期断言与 `tests/test_agent_e.py` 各守一遍。
   为什么必须机器守：这里此前只有四项（少了 `source_unreadable` 与 `param_error`），
   而没有任何一条测试会因此变红（`R2-AN-3`），于是同一文件里
   docstring 与常量互相矛盾。`import_unavailable` 不在那张常量表里：
   它是 `formalgw` 的检查器状态（库不可得 ⇒ 那次检查没有发生），
   见 `FORMAL_REASONS` 与 `_FORMAL_REASON_BY_TOOL_REASON`。
   三态纪律：没查成绝不等于查了通过。
4. `method="formal"` 而产物不是 `.lean` 文件 ⇒ 当场拒绝（`ExperimentError`）：
   形式化路径的输入是一份检查器能读的形式化源码，"用 Python 脚本冒充形式化产物"
   正是 FC-22 要拦的那种越权。

`name` / `imports` 只对形式化路径有意义：给计算类方法传它们会被拒绝，而不是被
静默忽略 —— 静默忽略会让调用方以为自己指定了检查条件（"说明了 imports，
实际用的是默认 Mathlib"这种假话没有任何地方会报出来）。

## 三态纪律在本模块的三处落地

- `evidence_for(claim_key=None, for_question_id=None)` ⇒ `checked=False`（没查）；
  给了参数但库里没有 ⇒ `checked=True, experiments=[], proved=False`（查了、没有）。
- `check_formal` 无后端 ⇒ `checked=False, reason="no_backend"`，
  不是 `verified=False`（那是"验证没过"，与"没验证"完全不同）。
  受控理由至少要分清四种：`no_backend` / `timeout` / `tool_crashed` /
  `source_unreadable`（环境的锅，本次没查成 —— 最后那一档是"`script_path`
  给的源码文件读不到"，`E-3`）与 `no_script`（调用方没给源码 —— 有后端时
  也会走到这一态，它不是"本机没有检查器"）。把"没查成"的判据写成
  `checked is False` 就会把后两者折叠成前者。
  这五种理由都属于本模块的局部受控词表 :data:`FORMAL_REASONS`，
  而检查器原样报的那个状态另走 `verifier_status`（见 :meth:`AgentE.check_formal`
  的 docstring：收口与透传必须同时在，否则收口就是删信息）。
- `proved` 只有在存在 proof 级实验时才为 True（FC-22）。

## 已知边界（如实标注，不要读成缺陷）

- `params` / `artifact_paths` 是信息性字段：本模块不会把它们变成命令行参数，
  也不会去读那些产物文件。记录它们是为了"这条实验当时是怎么跑的"可被复核。
- 本模块不调用 LLM（`llm` 位置参数仅为与 A–D 的构造签名保持一致，当前未使用）：
  数值实验的判读必须是确定性的（FC-16）。

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
from ..specs.e import SPEC

__all__ = [
    "AgentE",
    "ExperimentError",
    "FORMAL_REASONS",
    "REPRO_RESULT_PREFIX",
    "build_experiment",
    "declared_name_of_notes",
    "install_e_tools",
    "selftest",
    "SPEC",
]

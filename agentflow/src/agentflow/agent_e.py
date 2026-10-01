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
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import schema as S
from .formalgw import STATUSES as _FORMALGW_STATUSES
from .store import Store
from .tools import verify_tools as VT
from .tools.base import ToolError, ToolRegistry
from .agentspec import AgentBrief, AgentSpec

__all__ = [
    "AgentE",
    "ExperimentError",
    "FORMAL_REASONS",
    "REPRO_RESULT_PREFIX",
    "build_experiment",
    "declared_name_of_notes",
    "install_e_tools",
    "selftest",
]

#: 实验脚本在 stdout 里给出结构化结论的唯一约定。
#:
#: 为什么用一行前缀而不是"让脚本写一个 json 文件"：单行前缀的好处是
#: 零额外 IO、零额外约定（不需要知道临时目录在哪、不需要清理），
#: 而且当脚本崩溃在打印之前时，"没有这一行"本身就是可判定的信号。
REPRO_RESULT_PREFIX = "REPRO_RESULT:"

#: 计算类方法（拿不到 proof 的那一类）。顺序与 `schema.EXPERIMENT_METHODS`
#: 的关系在导入期断言，理由同 `verify_tools._EVIDENCE_ORDER`：
#: "哪些方法算计算类"这个判断只能有一处定义，否则 schema 拒绝的组合
#: 与 E 推导的组合会静默不一致。
COMPUTATIONAL_METHODS = ("numeric", "symbolic", "exhaustive_search")
assert set(COMPUTATIONAL_METHODS) | {"formal"} == set(S.EXPERIMENT_METHODS), (
    f"COMPUTATIONAL_METHODS={COMPUTATIONAL_METHODS} 与 schema.EXPERIMENT_METHODS="
    f"{S.EXPERIMENT_METHODS} 不一致 —— '哪些方法拿不到 proof' 必须只有一处定义"
)

#: 崩溃 / 无结论时的证据等级。刻意不是 cross_check：
#: 什么都没观察到，连"交叉验证"都算不上（FC-25 的 `no_local_evidence` 同理）。
_NO_EVIDENCE_KIND = "heuristic"

#: 脚本 stdout 里抓取结论时最多看多少字符。防止一个把整个数据集 dump 到
#: stdout 的脚本把内存吃光（它不该这么做，但这是外部输入）。
_STDOUT_SCAN_LIMIT = 4 * 1024 * 1024

#: 写进 notes 的输出摘要长度上限。
_OUTPUT_DIGEST_WIDTH = 300

#: `check_formal` 的"没查成"理由（环境或工具侧的锅）。
#: 判据是具体理由而不是 `checked is False`：后者把"没查成"（这几个）
#: 与"调用方没给源码"（`no_script`）折叠成同一件事，于是有后端时的一次
#: 调用方失误会被读成"本机没有证明检查器" —— 三态纪律在这里同样是
#: "不许把没查成与别的处置折叠"。四个理由取自 `formalgw` 的受控状态
#: （`timeout` / `no_backend` / `tool_crashed` / `source_unreadable`），
#: 另加工具层的 `param_error`（参数不合法，同样是"没查"而不是"查了没过"）。
#: `source_unreadable`（`E-3`）必须在这里：源码文件读不到也是"没查成"，
#: 这一格是 E 自查"哪些理由表示本次没有结论"时读的那一份。
_NOT_CHECKED_REASONS = ("no_backend", "timeout", "tool_crashed", "source_unreadable",
                        "param_error")

#: `check_formal` 的 `reason` 局部受控词表（`G-24①`）。
#:
#: 它回答的是"这一行的 reason 允许出现哪些字面量"。在此之前的实现是
#: `status if status in formalgw.STATUSES else "tool_crashed"` —— 一条
#: 带兜底的透传：词表之外的新状态会被伪装成 `tool_crashed`（"桥接层自己出错"），
#: 那是一句具体的假话，而不是"我不认识它"。
#:
#: 前九个取值与 `formalgw.STATUSES` 的检查器状态逐字相同，这是刻意的：
#: 同一个事实只该有一个名字（再起一套同义的英文名只会让两层对账时多一层翻译）。
#: 这张表的作用不是改名，
#: 而是登记 + 失败收口：状态必须在这张表里被显式列出，没收口进来的落到
#: `status_unregistered`（本表里的一个值），而检查器原样报的那个状态照样由
#: `verifier_status` 逐字透传 —— 收口不等于删信息。
#:
#: 其余取值是本层（E）的受控状态，它们不是检查器状态：`no_script` /
#: `param_error`（调用方没给输入）、`path_outside_workspace`（路径守卫拒绝）、
#: `tool_failed`（工具层返回了失败，失败种类在 `detail` 里）、
#: `status_unregistered`（上面那条收口）。
FORMAL_REASONS: tuple[str, ...] = (
    "verified",
    "compile_error",
    "uses_sorry",
    "extra_axioms",
    "decl_mismatch",
    "timeout",
    "import_unavailable",
    "no_backend",
    "tool_crashed",
    "source_unreadable",
    "no_script",
    "param_error",
    "path_outside_workspace",
    "tool_failed",
    "status_unregistered",
)

#: 工具层 `reason` 到本层受控词表的显式映射（`G-24①`：不许直传）。
#:
#: 左边是 `verify_tools.check_formal` 可能给出的全部 `reason`：十个检查器状态，
#: 外加它自己那两条受控拒绝（`no_backend` 来自探测不到检查器、`no_script` 来自
#: 调用方没给源码）。`tests/test_agent_e_formal_reasons.py` 断言这张表与
#: `formalgw.STATUSES` 逐值对齐 —— 检查器那边新增一个状态而这里没跟上时，
#: 那条断言会红，而不是让新状态悄悄落进 `status_unregistered`。
_FORMAL_REASON_BY_TOOL_REASON: dict[str, str] = {
    "verified": "verified",
    "compile_error": "compile_error",
    "uses_sorry": "uses_sorry",
    "extra_axioms": "extra_axioms",
    "decl_mismatch": "decl_mismatch",
    "timeout": "timeout",
    "import_unavailable": "import_unavailable",
    "no_backend": "no_backend",
    "tool_crashed": "tool_crashed",
    "source_unreadable": "source_unreadable",
    "no_script": "no_script",
}

#: 上面那张映射表必须是 `formalgw.STATUSES` 的超集（导入期就核，不留到测试里）。
#: 为什么放在导入期：本模块与 `formalgw` 之间是"状态词表"这一条隐式契约，
#: 而它一旦漂移，症状不是崩溃，是某一种检查结论被写成 `status_unregistered`。
assert set(_FORMALGW_STATUSES) <= set(_FORMAL_REASON_BY_TOOL_REASON), (
    f"formalgw.STATUSES={_FORMALGW_STATUSES} 里有本模块没有收口的状态："
    f"{sorted(set(_FORMALGW_STATUSES) - set(_FORMAL_REASON_BY_TOOL_REASON))} —— "
    "请在 _FORMAL_REASON_BY_TOOL_REASON 里显式收口（不许靠透传兜底）"
)
assert set(_NOT_CHECKED_REASONS) <= set(FORMAL_REASONS), (
    f"_NOT_CHECKED_REASONS={_NOT_CHECKED_REASONS} 必须全部在 FORMAL_REASONS 里 —— "
    "两处各写一份'哪些算没查成'是 FC-03 的形态"
)


# ---------------------------------------------------------------- 两条跨模块契约
#
# 下面两件东西都不是运行时逻辑，而是"同一件事只许有一处定义"的落点：
# ① 模块 docstring 里那句"没查成"的清单，必须覆盖 `_NOT_CHECKED_REASONS`；
# ② `notes` 里"被检查的声明名"那一段的写法与读法（`verify` 的事后审计要读它）。


def _docstring_not_checked_reasons(doc: str) -> set[str]:
    """从模块 docstring 第 3 条（"没查成"）那一段里读出 `` `x` `` 标识符集合。

    为什么要有它：`R2-AN-3` 的形态是"docstring 写四项、`_NOT_CHECKED_REASONS`
    写五项"，而没有任何一条测试会因此变红 —— 于是同一份文件里两处说法不一致。
    所以把"读 docstring 里那一档"做成一个可判定的读法，让导入期断言与用例
    共用它（`FC-03`：判据本身也只许有一份）。

    两个锚点（`3. 没查成` 与 `4. \\`method``）是 docstring 的既有编号，
    改编号就要同时改这里与 `temp/_verify_r2.py` 的 `C1`（那是这批的验收判据）。
    读不到锚点时返回空集，而空集会让下面那条导入期断言炸，
    而不是静默地判"文档没问题"（"没查成"绝不等于"查过了没问题"）。
    """
    seg = str(doc or "")
    start = seg.find("3. 没查成")
    if start < 0:
        return set()
    end = seg.find("4. `method", start)
    if end < 0:
        return set()
    return set(re.findall(r"`([a-z_]+)`", seg[start:end]))


assert set(_NOT_CHECKED_REASONS) <= _docstring_not_checked_reasons(__doc__ or ""), (
    "模块 docstring 第 3 条（'没查成'）没有覆盖 _NOT_CHECKED_REASONS="
    f"{_NOT_CHECKED_REASONS}；缺 "
    f"{sorted(set(_NOT_CHECKED_REASONS) - _docstring_not_checked_reasons(__doc__ or ''))} "
    "—— docstring 与常量各说一套是 `R2-AN-3` 的形态，而没人会因此变红，"
    "所以在这里导入期就核（判据本体见 _docstring_not_checked_reasons）"
)

#: `notes` 里"被检查的声明名"那一段的唯一写法与读法（`R2-AN-2`）。
#:
#: 写入点是 :meth:`AgentE._record_formal` 里调 `_declared_name_note(...)` 的那一步；
#: 读的人是 `verify` 的事后审计（`selfreported_proof`）：它必须按"检查器实际
#: 检查的那个声明名"去认输出了哪条诊断。为什么不能拿 `claim_key` 代替：
#: 生产路径上两者可以合法地不同 —— `tests/test_agent_e_formal_path.py`
#: 的正控就是 `claim_key='probe-eq'` 而 Lean 声明是 `probe_eq`
#: （Lean 标识符不许带连字符）。绑 `claim_key` 会把每一条合规的 proof 行
#: 都判成"自报"（`draft/28` §41.1：判据过窄 ⇒ 红掉合规输入，第 12 次）。
#:
#: 写法与读法分处两个文件时，任何一处单独改动都会让审计静默退回
#: `verifier_subject_key`（那就回到了旧口径），所以两边合在这里一处。
#:
#: 这一段的证据上界（`R2b-AN-2-A`）：`notes` 是可写的自由文本，审计侧读到的
#: 名字不受任何约束，所以 `selfreported_proof` 能到的一层是"依据可以被读出来"，
#: 不是"依据就是本行命题的"。逐条论证与"为什么不补交叉判据"写在
#: `verify.verify_all` 里那条判据的注释段（`R2b-AN-2-A`），这里不复制第二份。
_DECLARED_NAME_RX = re.compile(r"声明名\s*(\S+?)\s*[；;]")


def _declared_name_note(declared_name: str) -> str:
    """`notes` 里"声明名 `<X>`；"那一段的唯一写法（读法：:func:`declared_name_of_notes`）。"""
    return f"声明名 {declared_name}；"


def declared_name_of_notes(notes: Any) -> str:
    """从一行实验的 `notes` 里读出被检查的声明名；读不到返回空串（不猜）。

    三态：读到名字 / 读不到（历史行、手工行、非形式化实验）。读不到时不在这里
    退回任何猜测：调用方（`verify`）按"退回 `verifier_subject_key`"处置，
    那一步的语义是"本行声称检查器管的就是它"，与本函数不同，不许在这里合并。

    `notes` 允许是 `str`，也容忍字符串序列：`build_experiment` 落库时已经拼成
    一个 `str`（`:480`），但历史行与外部工具改过的快照可能是序列 —— 形状不对时
    按"读不到"处置（返回空串），绝不 `str()` 一把梭出一个假的声明名。
    """
    if isinstance(notes, str):
        text = notes
    elif isinstance(notes, Sequence):
        text = "\n".join(str(x) for x in notes)
    else:
        return ""
    m = _DECLARED_NAME_RX.search(text)
    return m.group(1).strip() if m else ""


class ExperimentError(RuntimeError):
    """实验无法执行（脚本不存在 / 路径越界 / 方法不支持）。"""


def _digest(text: Any, width: int = _OUTPUT_DIGEST_WIDTH) -> str:
    """单行化 + 截断。写进 `notes` 的输出摘要用。"""
    s = " ".join(str(text or "").split())
    return s if len(s) <= width else s[: width - 1] + "…"


def _as_dict(value: Any) -> dict:
    """把"脚本给的 observations/counterexample"规整成 dict。

    非对象一律丢弃为 `{}` / `None`，不报错：这两个字段是脚本的自由输出，
    形状不对时最安全的处置是"当作没给"，而不是让整条实验记录失败。
    与 `result` / `evidence_kind`（受控词表，格式非法即不认）的处理不同 ——
    那两个字段决定记录的语义，形状不对就没有语义可谈。
    """
    return dict(value) if isinstance(value, Mapping) else {}


def _extract_stdout_lines(stdout: str) -> list[str]:
    """取出 stdout 里所有 `REPRO_RESULT:` 行。

    取全部而不是最后一行：最后一行会被脚本后续的无意输出悄悄覆盖，
    而"同一个脚本给了两个互相矛盾的结论"是需要被看见的事实，不是需要被平滑掉的东西。
    """
    out: list[str] = []
    for line in stdout[:_STDOUT_SCAN_LIMIT].splitlines():
        s = line.strip()
        if s.startswith(REPRO_RESULT_PREFIX):
            out.append(s[len(REPRO_RESULT_PREFIX) :].strip())
    return out


def _parse_conclusion(stdout: str) -> tuple[dict | None, list[str]]:
    """解析 stdout 里的结构化结论。

    返回 ``(payload, notes)``：payload 为 None 表示"没有可用的结构化结论"，
    notes 里写明是哪一种情况（没打印 / JSON 坏了 / 字段值非法）。
    三种情况必须分开记录 —— FC-15 的纪律：不可归因的失败计数会把
    "脚本没写"和"脚本写错了"混成一个数字。
    """
    raws = _extract_stdout_lines(stdout)
    if not raws:
        return None, ["脚本未给出结构化结论（stdout 里没有 REPRO_RESULT 行）"]

    notes: list[str] = []
    if len(raws) > 1:
        notes.append(
            f"脚本打印了 {len(raws)} 行 REPRO_RESULT（多于一行）⇒ 视为格式非法，"
            "拒绝在互相矛盾的结论里挑一个（挑一个就等于替脚本做决定）"
        )
        return None, notes

    try:
        payload = json.loads(raws[0])
    except (ValueError, TypeError) as e:
        notes.append(f"REPRO_RESULT 行不是合法 JSON（{type(e).__name__}: {e}）⇒ 视为未给出结论")
        return None, notes
    if not isinstance(payload, Mapping):
        notes.append(f"REPRO_RESULT 的内容是 {type(payload).__name__}，不是对象 ⇒ 视为未给出结论")
        return None, notes
    payload = dict(payload)

    res = payload.get("result")
    if res not in S.EXPERIMENT_RESULTS:
        notes.append(
            f"REPRO_RESULT.result={res!r} 不在受控词表 {S.EXPERIMENT_RESULTS} 里 ⇒ 视为格式非法，"
            "不认这条结论（不猜它想说什么）"
        )
        return None, notes
    return payload, notes


def _normalize_evidence_kind(raw: Any, *, method: str, notes: list[str]) -> str:
    """把脚本自报的证据等级规整成 schema 允许的值，并把越权记进 notes。

    这条函数是 FC-22 在运行期的那一半：schema 是写入期的那一半。
    两半都需要 —— schema 拦得住"存进去的谎话"，拦不住"脚本以为自己证明了"。
    """
    if raw is None:
        # 脚本没报证据等级：默认 cross_check（"这不是证明"本身就写在默认值里）。
        return "cross_check"
    kind = str(raw)
    if kind not in S.EVIDENCE_KINDS:
        notes.append(
            f"脚本自报 evidence_kind={kind!r} 不在受控词表 {S.EVIDENCE_KINDS} 里 ⇒ 降级为 heuristic"
        )
        return _NO_EVIDENCE_KIND
    if kind == "proof" and method != "formal":
        notes.append(
            f"脚本自报 evidence_kind='proof'，但 method={method!r} 是计算类方法 ⇒ 拒绝并降级为 cross_check。"
            "理由：让被判定的对象自己决定'算不算证明'，等于没有判官；"
            "数学里数值/符号/穷举实验都不构成证明（FC-22）"
        )
        return "cross_check"
    return kind


def _derive(
    exit_code: int | None,
    stdout: str,
    *,
    method: str,
) -> dict:
    """由「退出码 + 脚本输出」推导 `result` / `evidence_kind` / `negation_kind`。

    本函数的规则就是模块 docstring 里那份"推导规则"的实现，两边必须一致；
    任何改动都要同时改 docstring —— 一份与实现不符的推导说明比没有更糟，
    因为它会让人以为自己知道这条记录是怎么来的。
    """
    notes: list[str] = []

    # ---- 规则 1：没跑完 ⇒ 一律 inconclusive（崩溃绝不能被写成支持）
    if exit_code is None or exit_code != 0:
        return {
            "result": "inconclusive",
            "evidence_kind": _NO_EVIDENCE_KIND,
            "negation_kind": "no_local_evidence",
            "observations": {},
            "counterexample": None,
            "notes": [f"脚本以 exit_code={exit_code} 结束 ⇒ 没有正常跑完，不得记为任何正面结论"],
        }

    # ---- 规则 2/3：解析脚本给出的结构化结论
    payload, parse_notes = _parse_conclusion(stdout)
    notes.extend(parse_notes)
    if payload is None:
        return {
            "result": "inconclusive",
            "evidence_kind": _NO_EVIDENCE_KIND,
            "negation_kind": "no_local_evidence",
            "observations": {},
            "counterexample": None,
            "notes": notes,
        }

    result = str(payload["result"])
    evidence_kind = _normalize_evidence_kind(payload.get("evidence_kind"), method=method, notes=notes)
    observations = _as_dict(payload.get("observations"))

    if result == "refutes":
        counterexample = payload.get("counterexample")
        if not isinstance(counterexample, Mapping) or not counterexample:
            # 不在这里兜底。脚本声称"证否"却给不出反例，说明它的输出与
            # 框架的证否语义不一致 —— 让 Experiment.validate() 抛出来。
            # 若在这里悄悄改成 inconclusive，这条不一致就永远不会被发现。
            raise ExperimentError(
                "脚本给出 result='refutes' 却没有给出非空的 counterexample ⇒ "
                "证否必须可复核（本题的证否不可复核，拒绝登记）"
            )
        return {
            "result": "refutes",
            "evidence_kind": evidence_kind,
            "negation_kind": "disproved",
            "observations": observations,
            "counterexample": dict(counterexample),
            "notes": notes,
        }

    # supports / inconclusive：只能是"未证明"或"没有本地证据"，不许是 disproved
    negation = "not_proved" if result == "supports" else "no_local_evidence"
    return {
        "result": result,
        "evidence_kind": evidence_kind,
        "negation_kind": negation,
        "observations": observations,
        "counterexample": None,
        "notes": notes,
    }


def build_experiment(
    experiment_id: str,
    claim: str,
    claim_key: str,
    *,
    method: str,
    code_path: str,
    code_hash: str,
    derived: Mapping[str, Any],
    exit_code: int | None,
    runtime_sec: float | None,
    params: Mapping[str, Any] | None = None,
    artifact_paths: Sequence[str] = (),
    for_question_id: str | None = None,
    extra_notes: Sequence[str] = (),
    verifier_output: str = "",
    verifier_subject_key: str = "",
    certificate: Mapping[str, Any] | None = None,
    search_bound: Mapping[str, Any] | None = None,
    created_by: str = "agent-E",
) -> S.Experiment:
    """把"推导结果"装成一行 `Experiment`。纯函数（不碰 store），便于单测。

    它只做装配与校验，不做任何推导 —— 推导在 `_derive`（计算类方法）或
    :meth:`AgentE._record_formal`（形式化方法），写入在 `AgentE.run_experiment`。
    这样"为什么这条记录长这样"可以脱离子进程被单独复现。

    ## 四个"证据形状"字段为什么要在这里有位置（`P-8`）

    `schema.Experiment.validate` 有四条与证据形状绑定的硬约束：

    - `evidence_kind="proof"` ⇒ `verifier_output` 必须非空（硬约束 2）；
    - `evidence_kind="proof"` ⇒ `verifier_subject_key` 必须非空且等于 `claim_key`
      （硬约束 2b：检查器输出必须绑定到它管的那个命题）；
    - `method="exhaustive_search"` ⇒ 必须有 `certificate`（硬约束 2c）；
    - 给了 `certificate` ⇒ 必须有 `search_bound`（证书脱离边界没有意义）。

    本函数此前一个都不收 ⇒ 形式化路径上的 proof 记录在 `row.validate()` 必然抛，
    于是"E 登记不了一条 proof 级实验"（`P-8`）。这四个参数不是新判据：
    它们是让推导侧能把已有的硬约束所需的事实交下来的通道。
    默认值全为空，计算类调用点逐字节不变。
    """
    row = S.Experiment(
        experiment_id=experiment_id,
        claim=claim,
        claim_key=claim_key,
        method=method,
        evidence_kind=str(derived.get("evidence_kind") or "cross_check"),
        result=str(derived.get("result") or "inconclusive"),
        negation_kind=derived.get("negation_kind"),
        code_path=code_path,
        code_hash=code_hash,
        params=dict(params or {}),
        observations=_as_dict(derived.get("observations")),
        exit_code=exit_code,
        runtime_sec=runtime_sec,
        artifact_paths=list(artifact_paths),
        counterexample=derived.get("counterexample"),
        # 四个证据形状字段从调用方来，不从 `derived` 里猜：它们是"这次检查
        # 到底产出了什么"的事实，而事实只能来自真的跑过检查器的那一段。
        verifier_output=str(verifier_output or ""),
        verifier_subject_key=str(verifier_subject_key or ""),
        certificate=dict(certificate) if isinstance(certificate, Mapping) else None,
        search_bound=dict(search_bound) if isinstance(search_bound, Mapping) else {},
        for_question_id=for_question_id,
        notes="\n".join(
            [str(n) for n in list(derived.get("notes") or []) + list(extra_notes) if str(n).strip()]
        ),
        created_at=S.now_iso(),
        created_by=created_by,
    )
    # 这里故意让异常冒出来：如果推导出的组合违反 schema 硬约束，
    # 那是"推导规则与 schema 不一致"，是本项目最该炸的地方。
    # 用 try/except 吞掉它，就会得到一条表里没有、日志里没有、只有调用方以为成功的记录。
    row.validate()
    return row


class AgentE:
    """数值实验与形式化验证智能体。

    每个方法都可以被独立调用与单测：

    - :meth:`run_experiment` —— 执行脚本 + 登记一行 Experiment；
    - :meth:`check_formal` —— 转发到形式化检查器（无后端时如实返回"没做"）；
    - :meth:`evidence_for` —— 三态查询：没查 / 查了没有 / 查到了什么；
    - :meth:`list_experiments` —— 只读列表。

    LLM：没有。数值实验的判读必须是确定性的（FC-16）。构造签名保留 `llm`
    位置参数只是为了与 A–D 的构造习惯一致。
    """

    def __init__(
        self,
        store: Store,
        *,
        config: Mapping[str, Any] | None = None,
        workspace_root: str | Path | None = None,
        log: Any | None = None,
        llm: Any | None = None,
        tools: ToolRegistry | None = None,
        actor: str = "agent-E",
    ) -> None:
        self.store = store
        self.cfg: dict[str, Any] = dict(config or {})
        self.actor = actor
        #: 未使用（见类 docstring 末段）。保留它是为了显式说明 E 不用 LLM，
        #: 而不是让调用方以为"没传 llm 所以功能缺了一块"。
        self.llm = llm
        self.log = log

        # ---- 阈值全部来自 config，不写死在代码里（与 A–D 的既有做法一致）
        #: 默认超时（秒）。调用方可以在 `run_experiment(timeout=...)` 覆盖。
        self.default_timeout = int(self.cfg.get("timeout", 600))
        #: 脚本解释器。默认用当前解释器（`sys.executable`）：
        #: 用 `"python"` 会依赖 PATH，在 CI/虚拟环境里可能解析到另一个 Python
        #: —— 于是"脚本在 E 里跑得通"与"在命令行里跑得通"变成两件事。
        self.python = str(self.cfg.get("python") or sys.executable or "python")
        #: 允许的脚本后缀。不是白名单本身，而是给"我不知道怎么跑它"一个明确说法：
        #: 一个 .jl 文件被当成 Python 跑会得到一个看起来像脚本 bug 的报错。
        self.allowed_suffixes = tuple(self.cfg.get("allowed_suffixes") or (".py", ".ps1"))

        root = workspace_root if workspace_root is not None else self.cfg.get("workspace_root")
        if root is None:
            # 默认以 store.root 为工作区：实验脚本与数据在同一棵树里，
            # 这样"工作区"这个概念在整个框架里只有一个含义。
            root = Path(self.store.root)
        self.workspace_root = Path(root).resolve()

        self.last_run: dict[str, Any] = {}
        #: 工具调用失败记录（与 agent_d 的 `last_tool_errors` 同名同义）。
        self.last_tool_errors: list[dict] = []
        self.tools = tools if tools is not None else install_e_tools(self.store, workspace_root=self.workspace_root)
        # ---- 绑定角色（`P-14`）：注入的注册表同样要绑（`AgentD` 那条注释同族）。
        if self.tools.bound_role is None:
            self.tools.bound_role = "E"

    # ------------------------------------------------------------ 小工具

    def _log(self, message: str, **extra: Any) -> None:
        if self.log is not None:
            try:
                self.log(message, **extra)
            except Exception:  # noqa: BLE001 - 日志失败不该打断实验
                pass

    def _resolve(self, rel: str | Path) -> Path:
        """把脚本路径解析到工作区内，越界即拒绝。

        为什么这条闸必须在 `open()` 之前：`script_path` 是本模块唯一的
        "外部输入 → 执行"通道。允许 `../../` 就等于允许框架执行工作区外的
        任意代码，而这不会报任何错 —— 它只会"成功"。
        与 `tools/verify_tools.py::_resolve`、`Store.library_path` 同一判据。
        """
        p = Path(str(rel))
        cand = (p if p.is_absolute() else (self.workspace_root / p)).resolve()
        try:
            cand.relative_to(self.workspace_root)
        except ValueError:
            raise ExperimentError(
                f"script_path 越出工作区：{rel!r}（工作区={self.workspace_root}）。"
                "拒绝执行工作区外的代码"
            ) from None
        return cand

    def _call(self, name: str, **params: Any) -> Any:
        """调工具并解开 `ToolResult`；失败返回 None 并把原因记进 `last_tool_errors`。

        与 `AgentD._call` 同样的取舍：一次工具失败不该打断 E 的流程，
        但原因必须留痕（否则"没查到"与"工具坏了"在调用方眼里长得一样）。
        """
        res = self.tools.call(name, **params)
        if not res.ok:
            self.last_tool_errors.append({"tool": name, "error": res.error, "kind": res.meta.get("kind")})
            return None
        return res.data

    # ------------------------------------------------------------ 执行

    def _command_for(self, path: Path) -> list[str]:
        """按后缀给出命令行。未知后缀直接拒绝，不猜。"""
        suf = path.suffix.lower()
        if suf == ".py":
            return [self.python, str(path)]
        if suf == ".ps1":
            exe = "pwsh" if _which("pwsh") else "powershell"
            return [exe, "-NoProfile", "-NonInteractive", "-File", str(path)]
        raise ExperimentError(
            f"不知道怎么执行 {suf or '（无后缀）'} 文件（已知 {self.allowed_suffixes}）。"
            "拒绝猜：把 .jl 当 Python 跑会得到一个看起来像脚本 bug 的报错，"
            "而真正的错误是调用方给错了文件"
        )

    def _run_script(self, path: Path, *, timeout: int) -> dict:
        """在独立进程里跑脚本，捕获 stdout/stderr/exit_code。

        为什么必须是独立进程（而不是 `exec` 到本进程里）：实验脚本是我们
        不完全信任的代码 —— 它可能死循环、可能 `sys.exit`、可能改全局状态。
        放在子进程里，最坏情况是这一轮实验失败，而不是整个框架被带走。
        超时同理：`subprocess.run(timeout=...)` 之后进程会被杀掉，
        而进程内的 `signal.alarm` 在 Windows 上根本不存在。
        """
        cmd = self._command_for(path)
        env = dict(os.environ)
        env.setdefault("PYTHONIOENCODING", "utf-8")
        env.setdefault("PYTHONUTF8", "1")
        t0 = time.monotonic()
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(self.workspace_root),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=max(1, int(timeout)),
                env=env,
            )
        except subprocess.TimeoutExpired as e:
            return {
                "exit_code": None,
                "stdout": _decode(e.stdout),
                "stderr": _decode(e.stderr) + f"\n[超时] 超过 timeout={timeout}s，进程已被杀掉",
                "runtime_sec": round(time.monotonic() - t0, 4),
                "timed_out": True,
                "launch_error": None,
            }
        except OSError as e:
            # 解释器不存在 / 权限不足等：这是没跑起来，不是"跑失败"。
            return {
                "exit_code": None,
                "stdout": "",
                "stderr": f"[无法启动] {type(e).__name__}: {e}",
                "runtime_sec": round(time.monotonic() - t0, 4),
                "timed_out": False,
                "launch_error": f"{type(e).__name__}: {e}",
            }
        return {
            "exit_code": proc.returncode,
            "stdout": proc.stdout or "",
            "stderr": proc.stderr or "",
            "runtime_sec": round(time.monotonic() - t0, 4),
            "timed_out": False,
            "launch_error": None,
        }

    def run_experiment(
        self,
        claim: str,
        claim_key: str,
        script_path: str,
        *,
        params: Mapping[str, Any] | None = None,
        method: str = "numeric",
        for_question_id: str | None = None,
        timeout: int = 600,
        name: str | None = None,
        imports: Sequence[str] | None = None,
    ) -> dict:
        """跑一个实验脚本并登记一条 `Experiment` 行。

        推导规则见模块 docstring（唯一权威表述）：计算类方法在 :func:`_derive`，
        形式化方法在 :meth:`_record_formal`。

        返回 ``{"experiment_id", "recorded", "result", "evidence_kind",
        "negation_kind", "exit_code", "reason"}``。

        schema 校验失败必须让异常冒出来（本方法不做 try/except 兜底）：
        那说明上面的推导规则与 `Experiment.validate` 不一致，
        而"推导规则与 schema 打架"正是本项目最该炸的地方。

        ## 形式化路径（`P-8`）

        `method="formal"` 时登记的不是"这个脚本说了什么"，而是"检查器核了什么"：

        - 产物必须是工作区里的 `.lean` 文件（别的后缀当场拒绝，见模块 docstring）；
        - `name` / `imports` 只对这条路径有意义，它们是给检查器的参数
          （`name` 不给时由工具层按其声明取文件名词干，本方法不另猜一次）；
        - 只有检查器给出 `verified` 才登记 `evidence_kind="proof"`，
          `verifier_output` 与 `verifier_subject_key` 都来自那一次真实检查。

        计算类方法给了 `name` / `imports` 会被拒绝（不是静默忽略）：
        静默忽略会让调用方以为自己指定了检查条件，而实际用的是默认值 ——
        这种假话没有任何地方会报出来。

        ## 这里没有 `sleep` 形参，这是刻意的（`D-2`）

        `capabilities.CAPABILITIES["E"].run_experiment` 的 params 里声明了 `sleep`，
        而它不在本方法的形参表里，本方法也不收 `inspect.Parameter.VAR_KEYWORD`。
        这不是漏了一个参数，也不是"反正 kwargs 收得住"：`sleep` 只服务替身夹具
        （`tests/test_conductor.py` / `tests/test_scheduler.py` 的 `FakeE` 按同一份
        schema 传它来控制"这次实验跑多久"），已逐条登记在 `capabilities.PARAM_SEAMS`
        里（键含理由串），并由 `capabilities.assert_capabilities()` 第 [8] 条在
        `import agentflow.capabilities` 时核过：声明了而实现不收、又不登记 ⇒ 导入失败。

        两条不许做的改动：① 把 `sleep` 从能力表里删掉 —— 那会让替身无法按 schema
        传参，被测的就不再是那条真实链路；② 在这里补一个具名的 `sleep`，或让它收
        `inspect.Parameter.VAR_KEYWORD` —— 前者是没人读的假承诺，后者把
        "我传了但它没看"变成静默成功，而 `conductor.LocalBackend.call` 的 docstring
        逐字拒绝的正是这个形态。参数门的口径（声明 ∩ 实现签名）见
        `capabilities.gate_params` / `capabilities.check_params`。
        """
        if not str(claim).strip():
            raise ExperimentError("claim 不能为空（没有命题就没有实验）")
        if not str(claim_key).strip():
            raise ExperimentError("claim_key 不能为空（没有它就无法回答'这条实验检验的是哪个命题'）")
        if method not in S.EXPERIMENT_METHODS:
            raise ExperimentError(f"method 必须是 {S.EXPERIMENT_METHODS} 之一，收到 {method!r}")
        if method != "formal" and (name is not None or imports is not None):
            raise ExperimentError(
                f"name / imports 只对 method='formal' 有效（收到 method={method!r}）—— "
                "计算类方法的证据等级由 `_derive` 推导，没有任何检查器会读这两个参数。"
                "静默忽略会让调用方以为自己指定了检查条件（说明了 imports，实际用的是默认值）"
            )

        # ---- [1] 路径解析（越界即拒绝）
        path = self._resolve(script_path)
        if not path.is_file():
            raise ExperimentError(f"脚本不存在：{script_path!r}（解析为 {path}）")

        # ---- [2] 可复现性绑定：复用 verify_tools.code_hash，不另写一份
        try:
            chash = VT.code_hash(path)
        except ToolError as e:
            raise ExperimentError(f"计算 code_hash 失败：{e}") from e

        # ---- [2b] 形式化路径：判据来自检查器，而不是来自脚本的自我陈述
        if method == "formal":
            return self._record_formal(
                claim,
                claim_key,
                path,
                code_hash=chash,
                params=params,
                for_question_id=for_question_id,
                timeout=timeout if timeout is not None else self.default_timeout,
                name=name,
                imports=imports,
            )

        # ---- [3] 独立进程执行 + 超时
        run = self._run_script(path, timeout=timeout if timeout is not None else self.default_timeout)

        # ---- [4] 推导 result / evidence_kind / negation_kind（规则见模块 docstring）
        derived = _derive(run["exit_code"], run["stdout"] or "", method=method)

        notes = list(derived.pop("notes", []) or [])
        head = f"exit_code={run['exit_code']}"
        if run.get("timed_out"):
            head += f"，超时（timeout={timeout}s）"
        if run.get("launch_error"):
            head += f"，启动失败（{run['launch_error']}）"
        notes.insert(0, f"[run] {head}，runtime={run['runtime_sec']}s，脚本 {script_path}（sha256 前 16 位 {chash}）")
        if run.get("stderr"):
            notes.append(f"[stderr] {_digest(run['stderr'])}")
        if run.get("stdout") and derived["result"] != "supports":
            # 只有在"结论不是支持"时才附 stdout 摘要：支持类结论已经有
            # 结构化 observations 可读，再贴一段原始输出只是噪声。
            notes.append(f"[stdout] {_digest(run['stdout'])}")

        # ---- [4b]（在事务内写日志：文件名要用实验号，见 [5]）

        # ---- [5] 一个事务：alloc_id + 写 experiments
        #
        # `alloc_id` 必须在持锁事务内进行，否则两个 E 实例会拿到同一个
        # experiment_id，而按主键 upsert 会静默互相覆盖（ID 发号与建行必须同锁）。
        with self.store.tx("experiments", actor=self.actor, note="e.run_experiment") as tx:
            eid = tx.alloc_id("experiment")
            # 原始输出落成产物文件（`draft/30` §T0-12）：上面那条"支持类不贴
            # stdout 摘要"是刻意的（噪声），但 P4/P5 要求"每条带 code_hash + 退出码 +
            # 原始输出，且能重跑得到同一读数"。摘要不进 notes，原始输出落文件；
            # 文件名用实验号 —— 同一脚本跑两次（不同种子）输出不同，按脚本哈希命名会撞。
            log_rel = f"out/experiments/{eid}.log"
            log_error = _write_run_log(self.workspace_root / log_rel, claim=claim,
                                       claim_key=claim_key, script_path=script_path,
                                       chash=chash, run=run)
            if log_error:
                notes.append(f"[log] 原始输出未能落盘（{log_error}）—— 实验行本身照样写")
                log_rel = ""
            row = build_experiment(
                eid,
                claim,
                claim_key,
                method=method,
                code_path=_relpath(path, self.workspace_root),
                code_hash=chash,
                derived=derived,
                exit_code=run["exit_code"],
                runtime_sec=run["runtime_sec"],
                params=params,
                artifact_paths=([log_rel] if log_rel else []),
                for_question_id=for_question_id,
                extra_notes=notes,
                created_by=self.actor,
            )
            tx.upsert("experiments", row.to_dict(), note=f"experiment:{claim_key}")

        out = {
            "experiment_id": eid,
            "recorded": True,
            "result": row.result,
            "evidence_kind": row.evidence_kind,
            "negation_kind": row.negation_kind,
            "exit_code": row.exit_code,
            "runtime_sec": row.runtime_sec,
            "code_hash": row.code_hash,
            "notes": row.notes,
            "reason": _result_reason(row),
        }
        self.last_run = out
        self._log(f"experiment {eid} recorded", **{k: out[k] for k in ("result", "evidence_kind", "exit_code")})
        return out

    # ------------------------------------------------------------ 形式化路径

    def _record_formal(
        self,
        claim: str,
        claim_key: str,
        path: Path,
        *,
        code_hash: str,
        params: Mapping[str, Any] | None,
        for_question_id: str | None,
        timeout: int,
        name: str | None,
        imports: Sequence[str] | None,
    ) -> dict:
        """形式化路径：真跑一次检查器，按检查器给的结论登记一行 `Experiment`。

        这是 `P-8` 的接线：此前 `run_experiment` 只有"跑脚本 + 读脚本自报的结论"
        一条路径，而 `build_experiment` 一个证据形状字段都不传 ⇒ 走到
        `row.validate()` 必然抛（"evidence_kind='proof' 时必须给出 verifier_output"）
        ⇒ E 登记不了一条 proof 级实验。这里把"一次真实的形式化检查"与
        "一行 proof 级实验记录"接起来，判据一条都没有新发明：

        - "什么算证明"只有一处定义（`formalgw`），本方法只读它的结论；
        - 检查器说 `verified` ⇒ `evidence_kind="proof"`，`verifier_output` 是
          检查器自己的输出，`verifier_subject_key` 逐字等于 `claim_key`；
        - 其余一切状态（跑了没通过 / 没查成）⇒ `inconclusive` + `heuristic`，
          一行都不许标成 proof。为什么不是 `cross_check`：那是"另一个方法旁证过"，
          而"证明没过"给不出旁证（`formalgw.evidence_of` 的 docstring 逐字写了
          同一条理由：把它写成 cross_check 会让一次检查失败变成正面证据）。

        `imports` 直接转发：默认 `None` 表示"用工具层的默认值"，本方法不替调用方
        决定要加载哪个库 —— 这个决定会改变结论（库不可得时 status 是
        `import_unavailable`，而不是"证明没过"），所以它必须是调用方显式给的。
        """
        suffix = path.suffix.lower()
        if suffix != ".lean":
            raise ExperimentError(
                f"method='formal' 的产物必须是 .lean 源文件，收到 {suffix or '（无后缀）'} "
                f"（{path.name!r}）—— 形式化路径的输入是检查器能读的形式化源码，"
                "本方法不会把一段 Python/文本当成 Lean 去核。"
                "数值脚本请用 method='numeric' / 'symbolic' / 'exhaustive_search'；"
                "让脚本冒充形式化产物正是 FC-22 要拦的那种越权"
            )

        rel = _relpath(path, self.workspace_root)
        declared_name = str(name or path.stem)
        t0 = time.monotonic()
        data = self.check_formal(
            claim,
            script_path=rel,
            name=name,
            imports=imports,
            timeout_sec=float(timeout),
        )
        runtime_sec = round(time.monotonic() - t0, 4)

        status = str(data.get("verifier_status") or "")
        formal_reason = str(data.get("reason") or "")
        output = str(data.get("verifier_output") or "").strip()
        verified = data.get("verified") is True

        notes = [
            f"[formal] 检查器状态 {status!r}（本层受控理由 {formal_reason}）；"
            # "声明名 <X>；"这一段有唯一写法（`_declared_name_note`）与唯一读法
            # （`declared_name_of_notes`）：事后审计（`verify.selfreported_proof`）
            # 按它认"检查器实际检查的是哪条声明"。在这里手写这一段，
            # 改写法的改动就会让读法静默失配（审计悄悄退回 `verifier_subject_key`）。
            f"{_declared_name_note(declared_name)}"
            f"脚本 {rel}（sha256 前 16 位 {code_hash}）；"
            f"imports={list(imports) if imports is not None else '（工具层默认）'}"
        ]
        detail = _digest(data.get("detail") or "", 400)
        if detail:
            notes.append(f"[formal] 检查器/工具层的说明：{detail}")
        if verified:
            notes.append(f"[formal] 检查器原话：{_digest(output, 400)}")
            notes.append(
                "[formal] ⇒ 本次是 proof 级证据（唯一允许'已证明'的一档）："
                "结论来自检查器，不来自脚本或本模块的推断"
            )
        else:
            notes.append(
                f"[formal] ⇒ 本次不是 proof：status={status!r} ⇒ result=inconclusive、"
                f"evidence_kind={_NO_EVIDENCE_KIND}（没查成与查了没通过都不构成正面证据）"
            )
            if output:
                notes.append(f"[formal] 检查器原始输出：{_digest(output, 400)}")

        derived: dict[str, Any] = {
            "result": "supports" if verified else "inconclusive",
            "evidence_kind": "proof" if verified else _NO_EVIDENCE_KIND,
            "negation_kind": "not_proved" if verified else "no_local_evidence",
            "observations": {
                "verifier_status": status,
                "formal_reason": formal_reason,
                "checked": data.get("checked"),
                "missing_imports": [str(x) for x in (data.get("missing_imports") or [])],
            },
            "counterexample": None,
            "notes": notes,
        }
        # 检查器输出空着时不给 `verifier_subject_key`：绑定一个命题、却没有任何
        # 检查器的话可作为"它管的是这个命题"的依据，那是一条空绑定。
        # `verified=True` 而输出为空是不可能的（`verified` 的定义就包含"输出里
        # 看得到那条声明"）；真出现时让它按 schema 硬约束 2 抛出来，不许在这里兜。
        subject_key = claim_key if output else ""
        # `verified` 只可能在检查器退出码 0 时到达（`formalgw.check_lean` 的
        # 判据顺序：非零退出码全部在前面收口），所以这里记 0 不是编造。
        exit_code = 0 if verified else None

        with self.store.tx("experiments", actor=self.actor, note="e.run_experiment") as tx:
            eid = tx.alloc_id("experiment")
            row = build_experiment(
                eid,
                claim,
                claim_key,
                method="formal",
                code_path=rel,
                code_hash=code_hash,
                derived=derived,
                exit_code=exit_code,
                runtime_sec=runtime_sec,
                params=params,
                for_question_id=for_question_id,
                verifier_output=output,
                verifier_subject_key=subject_key,
                created_by=self.actor,
            )
            tx.upsert("experiments", row.to_dict(), note=f"experiment:{claim_key}")

        out = {
            "experiment_id": eid,
            "recorded": True,
            "result": row.result,
            "evidence_kind": row.evidence_kind,
            "negation_kind": row.negation_kind,
            "exit_code": row.exit_code,
            "runtime_sec": row.runtime_sec,
            "code_hash": row.code_hash,
            "notes": row.notes,
            "reason": _result_reason(row),
        }
        self.last_run = out
        self._log(
            f"formal experiment {eid} recorded",
            **{k: out[k] for k in ("result", "evidence_kind", "exit_code")},
        )
        return out

    # ------------------------------------------------------------ 转发 / 查询

    def check_formal(
        self,
        claim: str,
        *,
        script_path: str | None = None,
        source: str | None = None,
        name: str | None = None,
        imports: Sequence[str] | None = None,
        timeout_sec: float | None = None,
    ) -> dict:
        """转发到 `tools/verify_tools.check_formal`（唯一实现）。

        无后端时必须返回 ``checked=False, reason="no_backend"``。
        它与 ``verified=False`` 是两件事：后者是"验证没过"（命题可疑），
        前者是"我们没验证"（命题未被检验）。把两者折叠，下游就会把
        "本环境没有证明检查器"读成"这个命题被证伪了"。

        ## 参数透传（本方法此前只暴露 `claim` / `script_path`）

        工具层 `verify.check_formal` 早就收 `source` / `checker_name` / `imports` /
        `timeout_sec`（工具层的形参名是 `checker_name` 而非 `name`，理由见
        `verify_tools.check_formal` 的 docstring；本方法自己的形参仍叫 `name`：
        它不是经 `ToolRegistry.call` 调用的，不受那个撞名影响），
        而本方法只转发前两个 —— 于是"给一段内存里的 Lean 源码"、
        "指定要核对的声明名"、"换 imports"、"给这次检查一个更短的时限"这四件事
        到不了 E：调用方写得出参数，E 收不到，而且不会报错（多给的键被
        Python 静默吃掉或直接 TypeError）。这是一条"能力表声明了、实现没有"的
        接线缺口，不是在补新功能。

        向后兼容：旧调用方写的是 `check_formal(claim)` 或
        `check_formal(claim, script_path=...)`。两个参数的名字、位置、默认值
        与返回结构都未变；新增的四个一律是关键字参数且默认 None
        ⇒ 旧调用点逐字节不受影响（既有用例
        `test_check_formal_without_backend_is_not_checked_not_failed` 未改一字）。

        ## `reason` 的收口与透传（`G-24①`）

        `reason` 取本模块的局部受控词表 :data:`FORMAL_REASONS`，映射表是
        `_FORMAL_REASON_BY_TOOL_REASON`：工具层给的每一个 `reason` 都必须在那张表里
        被显式列出，表外的值落到 `status_unregistered`（而不是伪装成 `tool_crashed`
        —— 那是一句具体的假话："桥接层自己出错"与"我不认识这个状态"是两件事）。

        收口必须有配套的透传，否则收口就是删信息：工具层原样报的那个值逐字放进
        `verifier_status`，检查器自己的话在 `verifier_output` 与 `detail` 里。
        透传字段也是"多值不许压成一个模糊值"（`N-5`）在本层的落地形态。

        ## `script_path` 的路径守卫（本轮补上）

        工具层 `verify.check_formal` 把 `script_path` 原样交给
        `formalgw.check_lean` 的 `source_path` 入口（它刻意不自己读文件，
        理由是"读不到的收口方式必须与声明名核对同处"）。那个入口会
        `open()` 调用方给的路径 ⇒ 在本方法收口之前，工具的 `script_path`
        是一条能读工作区外任意文件的通道（`verify.run_experiment` 那条路径
        有 `AgentE._resolve`，这条没有）。

        所以这里用本模块既有的 `_resolve` 收口（与 `run_experiment`
        第一段同一份判据，不另写一份），并且不把越界变成异常 ——
        它返回与 `no_backend` / `no_script` 同形的受控三态 dict：
        `checked=False, verified=None, reason="path_outside_workspace"`。
        为什么不是抛异常：工具化调用（`registry.call`）会把异常兜成
        `kind="unexpected"`，于是"调用方指了一个越界路径"与"E 内部有 bug"
        在下游长得一模一样。为什么 `verified` 必须是 `None` 而不是 `False`：
        这次没有查，不是"查了没通过"。
        """
        # ---- 路径守卫：越界即拒绝，且失败形态与本方法的其它受控状态同形
        #
        # 判据只有一条、且永远执行（即使同时给了 source）：给了 source 时工具层
        # 以 source 为准、不会去读这个文件，但"调用方以为自己能读那儿"这件事仍然成立，
        # 而它正是要被拦下的那个想法。这里复用 `run_experiment` 用的同一份 `_resolve`，
        # 不另写一份路径判据。
        safe_script: str | None = None
        if script_path is not None:
            try:
                resolved = self._resolve(str(script_path))
                safe_script = _relpath(resolved, self.workspace_root)
            except ExperimentError as exc:
                return self._formal_refusal(claim, "path_outside_workspace", str(exc))

        res = VT.check_formal(
            claim,
            script_path=safe_script,
            source=source,
            # 本方法的形参叫 name，工具层的形参叫 checker_name（`C3`：工具层是经
            # `ToolRegistry.call` 调用的，而它的第一个形参就叫 `name`，工具再声明
            # 一个 `name` 会抛 `got multiple values for argument 'name'`）。
            # 这一格是两套名字之间的唯一映射点，改工具层形参名时必须同轮改这里。
            checker_name=name,
            imports=imports,
            timeout_sec=timeout_sec,
            # 工作区只有 E 知道：工具层拿到相对路径后要把它解析到「工作区」，
            # 而不是解析到进程的 CWD。不给这个参数时，"工作区 ≠ CWD"的环境里
            # 那个 .lean 文件会被报成"读不了 ⇒ decl_mismatch"（实测：
            # `FileNotFoundError: 'p8_probe.lean'`）—— 一次路径解析问题
            # 被说成"你证的东西不在文件里"。
            root=str(self.workspace_root),
        )
        if not res.ok:
            # 传递失败也带上三态位，避免调用方只看 ok 就当成"没验证过"。
            # 键集合与"路径越界"那一支共用 `_formal_refusal`（见它的理由）。
            #
            # `reason` 只写受控值 `tool_failed`：失败种类（`param_error` /
            # `check_failed` / …）拼进 reason 会造出一个词表外的复合值
            # （`tool_failed:xxx`），于是"有哪些可能的 reason"这个问题的答案
            # 就没有边界了。种类改放 `detail`，它照样可见。
            kind = str(res.meta.get("kind") or "error")
            return self._formal_refusal(claim, "tool_failed", f"[{kind}] {res.error or ''}")
        data = dict(res.data or {})
        raw_reason = str(data.get("reason") or "")
        data["reason"] = _FORMAL_REASON_BY_TOOL_REASON.get(raw_reason, "status_unregistered")
        #: 逐字透传：收口之后，调用方仍然拿得到工具层/检查器原样报的那个值。
        data["verifier_status"] = raw_reason
        return data

    def _formal_refusal(self, claim: str, reason: str, detail: str) -> dict:
        """`check_formal` 的受控拒绝形态（路径越界走这一支）。

        为什么单独一个方法而不是内联一个 dict：工具层
        `verify.check_formal` 的契约字符串是
        ``{'checked','verified','claim','reason','detail','verifier_output',
        'missing_imports','verifier_status'}``，
        而 `tests/test_tools_audit_fixes.py` 逐字核对每条分支的键集合。
        把"拒绝"的键集合收在一处，是为了让"多了/少了一个键"在结构上不可能
        只发生在某一条分支里 —— 顺便让下面 `tool_failed` 那一支也用它。

        `verified=None`（不是 `False`）：这次没有查。"查了、没过"是
        `checked=True, verified=False`；把两者折叠，下游会把"路径被拒"
        读成"这个命题被证伪了"。

        ## 为什么要带 `missing_imports`（`G-18` 之后的键集合一致性）

        工具层 `verify.check_formal` 的声明是一个键集合，它对每一条分支都成立
        （`tests/test_tools_audit_fixes.py` 逐字核对每条分支）。`G-18` 给成功分支加了
        `missing_imports`（"哪个包不可得"）之后，本方法这条拒绝分支如果还是 6 个键，
        就会出现"同一个工具的两条分支两个键集合" —— 这正是 `checks` 类契约最容易腐的地方。
        所以这里补一个空列表（拒绝路径上没有"缺哪个包"这回事，空列表是诚实的值：
        "我们没有因为缺包而拒绝"，而不是"我们不知道"）。

        ## 为什么 `verifier_status` 是空串（`G-24①` 的透传字段）

        这一支是"根本没起检查器"（路径被拒 / 工具层返回失败）⇒ 没有检查器的原话可透传，
        空串是诚实的值："这次没有检查器状态"，而不是"我不知道它是什么"。
        校验器原话在 `detail` 里，检查器输出在 `verifier_output` 里。
        """
        return {
            "checked": False,
            "verified": None,
            "claim": claim,
            "reason": reason,
            "detail": detail,
            "verifier_output": "",
            "missing_imports": [],
            "verifier_status": "",
        }

    def evidence_for(self, claim_key: str | None = None, *, for_question_id: str | None = None) -> dict:
        """三态查询某条命题 / 某个研究问题的实验证据。实现见 `verify_tools.evidence_for`。"""
        out = VT.evidence_for(self.store, claim_key, for_question_id=for_question_id)
        self.last_evidence_query = out
        return out

    def list_experiments(self, *, claim_key: str | None = None, limit: int | None = None) -> dict:
        """只读列出实验记录。"""
        return VT.list_experiments(self.store, claim_key=claim_key, limit=limit)

    # ------------------------------------------------------------ 便利构造

    def run_script_experiment(self, claim: str, claim_key: str, script_path: str, **kw: Any) -> dict:
        """`run_experiment` 的别名（保留给"读起来更顺"的调用点）。"""
        return self.run_experiment(claim, claim_key, script_path, **kw)


def _write_run_log(target: Path, *, claim: str, claim_key: str, script_path: str,
                   chash: str, run: Mapping[str, Any]) -> str | None:
    """把一次实验的原始输出写成产物文件；返回 `None` 表示写成了，否则返回失败原因。

    不许因为日志写不了就丢掉这条实验：调用方拿到原因后照样写实验行，
    并把这件事记进 `notes`（"有实验没日志"与"没这条实验"要分得开）。
    """
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            f"# {claim_key}\n"
            f"# 脚本 {script_path}  sha256={chash}\n"
            f"# exit_code={run['exit_code']}  runtime={run['runtime_sec']}s"
            + ("（超时）" if run.get("timed_out") else "")
            + "\n"
            f"# claim: {claim}\n"
            "----- stdout -----\n"
            f"{run.get('stdout') or ''}"
            "----- stderr -----\n"
            f"{run.get('stderr') or ''}",
            encoding="utf-8")
        return None
    except OSError as e:
        return f"{type(e).__name__}: {e}"


def _result_reason(row: S.Experiment) -> str:
    """给人看的一句话解释（不替代 notes，只是列表展示用）。"""
    if row.exit_code not in (0, None):
        return f"脚本 exit_code={row.exit_code} ⇒ 未正常跑完，记 inconclusive（崩溃不得当成支持）"
    if row.evidence_kind == "proof":
        return (
            f"{row.method} 实验支持该命题，证据等级 {row.evidence_kind}"
            "（有形式化检查器输出）"
            + _formal_status_suffix(row)
        )
    if row.result == "supports":
        return f"{row.method} 实验支持该命题，证据等级 {row.evidence_kind}（不构成证明）"
    if row.result == "refutes":
        return "实验给出反例 ⇒ disproved（已证否，且反例已登记）"
    return (
        f"未得到可判定的结论（negation_kind={row.negation_kind}）"
        + _formal_status_suffix(row)
    )


def _formal_status_suffix(row: S.Experiment) -> str:
    """形式化行的人话后缀：检查器原样报的状态 + 本层的受控理由。

    为什么它必须出现在这一句里（而不是只躺在 `observations` 里）：
    `P-8` 之后"形式化检查跑了但没过"与"数值实验没跑出结论"在列表里长得一样
    （都是 `inconclusive`），而两者的处置完全不同（一个去看检查器输出、
    一个去看脚本）。这一句是列表页唯一能区分它们的地方。
    """
    obs = row.observations if isinstance(row.observations, Mapping) else {}
    status = str(obs.get("verifier_status") or "")
    if not status:
        return ""
    return f"；检查器状态 {status!r}（本层受控理由 {obs.get('formal_reason') or '（未记）'}）"


def _relpath(path: Path, root: Path) -> str:
    """工作区内的相对路径（用 / 分隔，与 schema 的路径书写约定一致）。"""
    try:
        rel = path.resolve().relative_to(root)
    except ValueError:
        raise ExperimentError(f"路径 {path} 不在工作区 {root} 内") from None
    return rel.as_posix()


def _decode(value: Any) -> str:
    """`TimeoutExpired.stdout` 可能是 bytes（text= 参数在超时路径上不保证生效）。"""
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _which(name: str) -> str | None:
    import shutil

    return shutil.which(name)


def install_e_tools(
    store: Store,
    *,
    registry: ToolRegistry | None = None,
    workspace_root: str | Path | None = None,
) -> ToolRegistry:
    """装配 E 的工具栏（`verify.*`）。

    与其他角色同样的思路：E 只通过 registry 调用工具，于是"工具 handler 的实现"
    与"AgentE 的方法"必须共用同一份代码 —— 否则两个入口会写出字段口径不同的记录。
    本框架的做法是让工具 handler 惰性构造一个 AgentE（见 verify_tools 的 docstring）。
    """
    reg = registry if registry is not None else ToolRegistry(name="agent-E")
    root = Path(workspace_root) if workspace_root is not None else Path(store.root)
    VT.register(reg, store=store, root=root)
    # ---- 绑定角色（`P-14`）：这张注册表代表 E，`AgentE._call` 的每次调用都会被
    # 判一次"E 拿不拿得到这个工具"。不绑的话那些调用会全部以"调用方没有声明角色"失败。
    # 它不改 `E` 的工具面（`for_role` 在这张注册表上没剥掉任何东西）。
    if reg.bound_role is None:
        reg.bound_role = "E"
    return reg


# ---------------------------------------------------------------- 自检


def selftest() -> int:
    """离线自检：不联网、不依赖仓库里的任何外部文件，返回失败数。

    运行方式::

        cd D:\\Incubator\\test\\test1\\src
        $env:PYTHONIOENCODING='utf-8'; python -m agentflow.agent_e

    覆盖的核心性质（每一条都对应一个"如果错了会很安静"的失败模式）：

    1. 正常脚本 ⇒ 登记成功，exit_code=0，code_hash 非空；
    2. 脚本自报 proof ⇒ 被降级为 cross_check，且 notes 里记了这件事；
    3. 脚本崩溃 ⇒ inconclusive + no_local_evidence（崩溃不得写成支持）；
    4. 脚本不打印 REPRO_RESULT ⇒ inconclusive + no_local_evidence；
    5. 路径越界 ⇒ 拒绝；
    6. 超时 ⇒ inconclusive 且原因可见；
    7. evidence_for 三态：没查 / 查了没有 / 查到了什么；
    8. 只写一行 experiments（事务性）；
    9. `check_formal` 的受控理由：无后端 ⇒ `no_backend`；有后端但没给源码
       ⇒ `no_script`（两者都是"没查成"，但理由不同，不可折叠）；
    10. 形式化路径（`P-8`）：`.lean` 产物真的走检查器那一条 —— 检查器给
        `verified` 时登记的行必须是 `evidence_kind="proof"` 且
        `verifier_subject_key == claim_key`；否则一行都不许标成 proof。
        本机没有 Lean 时这一段的期望值自动降级成"不是 proof"，仍然核对
        "没查成不许登记成 proof"（三态纪律）。
    """
    import sys as _sys
    import tempfile

    try:
        _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # 有些 stdout 替身没有 reconfigure；切编码失败不该让自检本身挂掉
        pass

    failures = 0

    def check(label: str, cond: bool, extra: str = "") -> None:
        nonlocal failures
        okk = bool(cond)
        if not okk:
            failures += 1
        print(f"    [{'PASS' if okk else 'FAIL'}] {label}" + (f"  {extra}" if extra else ""))

    print("=" * 72)
    root = Path(tempfile.mkdtemp(prefix="agentflow-agente-"))
    st = Store(root)
    st.init()
    print(f"[0] 临时工作区：{root}")

    def put_script(name: str, body: str) -> str:
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
        return name

    e = AgentE(st, workspace_root=root)
    print(f"[1] 工具栏：{e.tools.names()}")

    # ---- 1. 正常脚本
    s1 = put_script(
        "ok_probe.py",
        "import json\n"
        "print('REPRO_RESULT: ' + json.dumps({'result':'supports','evidence_kind':'cross_check',\n"
        "  'observations':{'grid':64,'max_err':1e-9},'counterexample':None,'negation_kind':'not_proved'}))\n",
    )
    r1 = e.run_experiment("对 n<=64 的网格，Spec K(m)=[-m,m]", "SpecK(m)=[-m,m]", s1)
    print(f"[2] 正常脚本 ⇒ {r1['result']} / {r1['evidence_kind']} / exit={r1['exit_code']}")
    check("登记成功且 recorded=True", r1["recorded"] is True)
    check("exit_code==0", r1["exit_code"] == 0)
    check("code_hash 非空", bool(r1["code_hash"]))
    check("result=supports ⇒ negation_kind=not_proved", r1["negation_kind"] == "not_proved")

    # ---- 2. 脚本自报 proof（负控）
    s2 = put_script(
        "lying_probe.py",
        "import json\n"
        "print('REPRO_RESULT: ' + json.dumps({'result':'supports','evidence_kind':'proof',\n"
        "  'observations':{},'counterexample':None,'negation_kind':'not_proved'}))\n",
    )
    r2 = e.run_experiment("脚本自报 proof 的命题", "selfclaimed-proof", s2)
    print(f"[3] 脚本自报 proof ⇒ 实际 {r2['evidence_kind']}")
    check("脚本自报 proof 被降级为 cross_check", r2["evidence_kind"] == "cross_check")
    check("notes 里记下了这次越权", "proof" in r2["notes"] and "拒绝" in r2["notes"])

    # ---- 3. 崩溃（负控）
    s3 = put_script("crash_probe.py", "raise SystemExit(3)\n")
    r3 = e.run_experiment("崩溃脚本不得被写成支持", "crash", s3)
    print(f"[4] 崩溃 ⇒ {r3['result']} / {r3['negation_kind']} / exit={r3['exit_code']}")
    check("崩溃 ⇒ inconclusive", r3["result"] == "inconclusive")
    check("崩溃 ⇒ no_local_evidence", r3["negation_kind"] == "no_local_evidence")

    # ---- 4. 不打印 REPRO_RESULT
    s4 = put_script("silent_probe.py", "print('hello')\n")
    r4 = e.run_experiment("没有结构化结论", "silent", s4)
    print(f"[5] 无结论行 ⇒ {r4['result']} / notes={_digest(r4['notes'], 80)!r}")
    check("无结论行 ⇒ inconclusive + no_local_evidence",
          r4["result"] == "inconclusive" and r4["negation_kind"] == "no_local_evidence")
    check("notes 写明脚本未给出结构化结论", "未给出结构化结论" in r4["notes"])

    # ---- 5. 路径越界
    escaped = False
    try:
        e.run_experiment("越界脚本", "escape", "../outside.py")
    except Exception as ex:  # noqa: BLE001
        escaped = isinstance(ex, ExperimentError)
    check("路径越界被拒绝", escaped)

    # ---- 6. 超时
    s6 = put_script("slow_probe.py", "import time\ntime.sleep(30)\n")
    r6 = e.run_experiment("超时脚本", "slow", s6, timeout=1)
    print(f"[6] 超时 ⇒ {r6['result']} / exit={r6['exit_code']} / notes={_digest(r6['notes'], 70)!r}")
    check("超时 ⇒ inconclusive + no_local_evidence",
          r6["result"] == "inconclusive" and r6["negation_kind"] == "no_local_evidence")

    # ---- 7. evidence_for 三态
    q = e.evidence_for()
    hit = e.evidence_for("SpecK(m)=[-m,m]")
    miss = e.evidence_for("完全不存在的命题")
    print(f"[7] evidence_for：没查 checked={q['checked']}；命中 {len(hit['experiments'])} 条 "
          f"proved={hit['proved']}；未命中 checked={miss['checked']}")
    check("两个参数都不给 ⇒ checked=False（没查）", q["checked"] is False)
    check("给了参数且命中 ⇒ checked=True", hit["checked"] is True and len(hit["experiments"]) == 1)
    check("命中但没有 proof ⇒ proved=False", hit["proved"] is False)
    check("给了参数但没有 ⇒ checked=True 且 experiments=[]",
          miss["checked"] is True and miss["experiments"] == [] and miss["proved"] is False)
    check("'查了没有' 与 '没查' 的 reason 不同", "没有" in miss["reason"] and "没查" in q["reason"])

    # ---- 8. 事务性：一轮实验只写一行
    before = len(st.rows("experiments"))
    e.run_experiment("再来一条", "again", s1)
    after = len(st.rows("experiments"))
    print(f"[8] 事务性：experiments {before} -> {after}")
    check("一次 run_experiment 只多一行", after == before + 1)

    # ---- 9. check_formal 的三态（无后端时是'没做'，不是'没过'）
    #
    # 判据是具体理由，不是 `checked is False`：`checked=False` 有两种完全不同的来源
    # ——"没查成"（`no_backend` / `timeout` / `tool_crashed`，环境的锅）与
    # "调用方没给源码"（`no_script`，调用方的锅）。把它们折叠成一个判据之后，
    # 有后端时拿不到源码（`no_script`）会被读成"本机没有证明检查器"，
    # 于是这条断言在有后端的环境里必然失败（而且它失败得很安静）。
    # `no_script` 单独走下面第 10 段，形态与 `no_backend` 分别核对。
    cf = e.check_formal("1+1=2")
    print(f"[9] check_formal ⇒ checked={cf.get('checked')} reason={cf.get('reason')!r} "
          f"verified={cf.get('verified')!r}")
    if cf.get("reason") == "no_backend":
        check("无后端 ⇒ reason='no_backend' 且 verified 为 None（不是 False），"
              "且 checked=False",
              cf.get("checked") is False and cf.get("verified") is None)
    elif cf.get("reason") in _NOT_CHECKED_REASONS:
        # 环境侧"没查成"的另两种：`timeout` / `tool_crashed`。
        check(f"没查成（{cf.get('reason')}）⇒ checked=False 且 verified 为 None，"
              "且理由不是 no_script",
              cf.get("checked") is False and cf.get("verified") is None)
    else:
        # 有后端、没给源码 ⇒ 受控的 `no_script`（不是"没后端"）：
        # 这是本段收紧判据后新增的那一态，它必须在这里被单独核对。
        check("有后端但没给源码 ⇒ 受控的 no_script（不是 no_backend），"
              "且 verified 为 None",
              cf.get("reason") == "no_script" and cf.get("checked") is False
              and cf.get("verified") is None)
        # 同一环境里给一份源码：这次真的会去跑检查器，于是"有后端"这件事
        # 不只是从 reason 推出来的。`imports=()` 是为了不依赖 Mathlib 全库编完。
        src9 = "theorem selfcheck_one_plus_one : 1 + 1 = 2 := rfl\n"
        cf2 = e.check_formal("1+1=2", source=src9, name="selfcheck_one_plus_one",
                             imports=())
        print(f"[10] 有后端 + 给源码 ⇒ checked={cf2.get('checked')} "
              f"reason={cf2.get('reason')!r} verified={cf2.get('verified')!r}")
        check("有后端 + 给源码 ⇒ verified=True（检查器这一段真的接上了）",
              cf2.get("reason") == "verified" and cf2.get("verified") is True
              and cf2.get("checked") is True)
        check("`reason` 的收口与透传同时成立（G-24①）",
              cf2.get("reason") == "verified"
              and cf2.get("verifier_status") == cf2.get("reason"),
              f"verifier_status={cf2.get('verifier_status')!r}")

    # ---- 10. 形式化路径（P-8）：`.lean` 产物真的走检查器那一条
    #
    # 判据与"本机有没有 Lean"解耦：有检查器且命题为真 ⇒ 必须是 proof；
    # 否则必须是"不是 proof"（没查成不许登记成 proof）。
    # 两个方向都不许把 `heuristic` 写成 `proof`，所以这条检查在任何环境下都有信息量。
    lean_src = (
        "theorem selfcheck_formal_proof : 1 + 1 = 2 := rfl\n"
    )
    s10 = put_script("selfcheck_formal_proof.lean", lean_src)
    r10 = e.run_experiment(
        "内核级命题：1+1=2", "selfcheck-formal", s10,
        method="formal", imports=(),
    )
    print(f"[11] formal 路径 ⇒ evidence_kind={r10['evidence_kind']} "
          f"result={r10['result']} reason={_digest(r10['reason'], 90)!r}")
    if r10["evidence_kind"] == "proof":
        row10 = st.rows("experiments")[-1]
        check("proof 行必须由检查器背书：verifier_subject_key == claim_key",
              row10["verifier_subject_key"] == "selfcheck-formal")
        check("proof 行必须有检查器原话（verifier_output 非空）",
              bool(str(row10["verifier_output"]).strip()))
        check("proof 行不许出现在非 formal 方法上", row10["method"] == "formal")
    else:
        check("检查器没给出 verified 时，一行都不许标成 proof（三态纪律）",
              r10["evidence_kind"] != "proof" and r10["result"] == "inconclusive")
        check("没查成/没通过都必须写清检查器状态",
              "检查器状态" in r10["reason"] or "检查器状态" in r10["notes"])

    # ---- 11. 形式化路径的负控：非 .lean 产物当场拒绝（不留半条记录）
    before11 = len(st.rows("experiments"))
    refused = False
    try:
        e.run_experiment("用 Python 冒充形式化产物", "formal-python", s1, method="formal")
    except Exception as ex:  # noqa: BLE001
        refused = isinstance(ex, ExperimentError)
    check("method='formal' + 非 .lean 产物 ⇒ 当场拒绝", refused)
    check("被拒绝的形式化实验不得留下任何行", len(st.rows("experiments")) == before11)

    # ---- 12. 计算类方法不许收 name / imports（静默忽略是假话）
    ignored = False
    try:
        e.run_experiment("数值方法不许收 imports", "numeric-imports", s1, imports=())
    except Exception as ex:  # noqa: BLE001
        ignored = isinstance(ex, ExperimentError)
    check("计算类方法收到 imports ⇒ 拒绝而不是静默忽略", ignored)

    print("=" * 72)
    print(f"SELF-CHECK {'DONE' if failures == 0 else 'FAILED'}（agent_e）：失败 {failures} 项")
    return failures


#: 本角色的声明（`goal-7f5116c1` M3）。
#:
#: 真身在 `specs/e.py` —— 那里就是权限面的落点（`.noai-paths` 保护它）。
#: 这里只做再导出：`agentspec.builtin_registry()`、判据与调用方都按 `mod.SPEC` 取，
#: 于是"角色模块里能读到自己的声明"这件事仍然成立，而不会多出第二份拷贝。
from .specs.e import SPEC  # noqa: E402,F401


if __name__ == "__main__":  # pragma: no cover - 手工运行的自检块
    raise SystemExit(selftest())

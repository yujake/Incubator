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
from .. import schema as S
from ..formalgw import STATUSES as _FORMALGW_STATUSES
from ..formalgw import DeclarationNameError, sole_declaration_name
from ..store import Store
from ..tools import verify_tools as VT
from ..tools.base import ToolError, ToolRegistry
from ..agentspec import AgentBrief, AgentSpec
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
REPRO_RESULT_PREFIX = "REPRO_RESULT:"
COMPUTATIONAL_METHODS = ("numeric", "symbolic", "exhaustive_search")
assert set(COMPUTATIONAL_METHODS) | {"formal"} == set(S.EXPERIMENT_METHODS), (
    f"COMPUTATIONAL_METHODS={COMPUTATIONAL_METHODS} 与 schema.EXPERIMENT_METHODS="
    f"{S.EXPERIMENT_METHODS} 不一致 —— '哪些方法拿不到 proof' 必须只有一处定义"
)
_NO_EVIDENCE_KIND = "heuristic"
_STDOUT_SCAN_LIMIT = 4 * 1024 * 1024
_OUTPUT_DIGEST_WIDTH = 300
_NOT_CHECKED_REASONS = ("no_backend", "timeout", "tool_crashed", "source_unreadable",
                        "param_error")
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
assert set(_FORMALGW_STATUSES) <= set(_FORMAL_REASON_BY_TOOL_REASON), (
    f"formalgw.STATUSES={_FORMALGW_STATUSES} 里有本模块没有收口的状态："
    f"{sorted(set(_FORMALGW_STATUSES) - set(_FORMAL_REASON_BY_TOOL_REASON))} —— "
    "请在 _FORMAL_REASON_BY_TOOL_REASON 里显式收口（不许靠透传兜底）"
)
assert set(_NOT_CHECKED_REASONS) <= set(FORMAL_REASONS), (
    f"_NOT_CHECKED_REASONS={_NOT_CHECKED_REASONS} 必须全部在 FORMAL_REASONS 里 —— "
    "两处各写一份'哪些算没查成'是 FC-03 的形态"
)
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
from ..specs.e import SPEC  # noqa: E402,F401


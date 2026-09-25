"""智能体 E：**数值实验与形式化验证**。

设计基线：``test/test1/DESIGN-ROLES.md`` §2.1 与 `schema.Experiment` 的硬约束。

## E 到底在做什么（一句话）

**E 产出证据，不产出结论。**

这个分工不是文字游戏，它是本模块每一行代码的由来。一个"能跑实验"的智能体
最自然也最危险的越界，就是把"我算了几千个点都对"写成"已证明" ——
数学里数值实验**不构成证明**（FC-22）。所以：

- `Experiment.evidence_kind` 是**结构化字段**，不是注释里的告诫；
- 计算类方法（numeric / symbolic / exhaustive_search）**在 schema 层就拿不到
  `evidence_kind="proof"`**，写入的那一刻就炸；
- 脚本自己声称 `proof` 会被**降到 cross_check** 并把这件事记进 `notes`
  （见 :meth:`AgentE.run_experiment` 的推导规则第 4 条）。

## 为什么"脚本自报 evidence_kind"必须被降级

这是本模块最反直觉的一条规矩，值得写清楚：

**让被判定的对象自己当判官，等于没有判官。**

`script_path` 指向的脚本是**被检验的对象**（它算出了结论）。如果它同时能决定
"这个结论算不算证明"，那么整条证据链的强度就由最不可信的一环决定 ——
而这一环恰恰是最容易"顺手写一句 `{"evidence_kind": "proof"}`"的地方。
更糟的是：这种越权**不会报任何错**，表里只会多一条看起来很漂亮的 proof。

所以 E 的态度是：**脚本只能报告"我观察到了什么"（result / observations /
counterexample），证据等级由框架按 method 推导**。脚本说自己是 proof，
E 记下"脚本声称过 proof，已被拒绝"这件事 —— 拒绝本身要留痕，
否则三个月后没人能解释这条记录的等级为什么比脚本里写的低。

## 推导规则（**唯一权威表述**，实现见 `_derive`）

输入是「退出码 + 脚本 stdout 里的一行结构化结论」：

1. `exit_code != 0`（崩溃 / 超时 / 启动失败）
   ⇒ `result="inconclusive"`, `negation_kind="no_local_evidence"`,
     `evidence_kind="heuristic"`。**绝不允许把崩溃写成支持**（FC-21/F C-25）。
   理由：崩溃只说明"这次没跑成"，它既不是对命题的支持也不是反驳。
2. 脚本在 stdout 打印了一行 `REPRO_RESULT: {json}`（约定格式见
   :data:`REPRO_RESULT_PREFIX`）：
   - `result` 必须 ∈ `EXPERIMENT_RESULTS`，否则整条结论视为**格式非法**，
     按第 3 条处理（宁可不认，也不要猜）；
   - `result="refutes"` ⇒ `negation_kind="disproved"` 且**必须**有 `counterexample`。
     缺反例时 `Experiment.validate()` 会抛 —— **让它抛**：那说明脚本在声称
     一个它没给出依据的证否，这正是最该炸的地方；
   - `result="supports"` ⇒ `negation_kind="not_proved"`
     （数值支持只能是"未证明"，不是"已证明"）；
   - `result="inconclusive"` ⇒ `negation_kind="no_local_evidence"`；
   - `evidence_kind` **由 method 推导**，脚本自报值只作为"它想声称什么"被记录：
     计算类方法一律 `cross_check`（自报 proof ⇒ 降级 + 记 notes）。
3. 脚本没有打印那行（或格式非法）
   ⇒ `result="inconclusive"`, `negation_kind="no_local_evidence"`,
     `evidence_kind="heuristic"`，`notes` 写明"脚本未给出结构化结论"。

## 三态纪律在本模块的三处落地

- `evidence_for(claim_key=None, for_question_id=None)` ⇒ `checked=False`（**没查**）；
  给了参数但库里没有 ⇒ `checked=True, experiments=[], proved=False`（**查了、没有**）。
- `check_formal` 无后端 ⇒ `checked=False, reason="no_backend"`，
  **不是** `verified=False`（那是"验证没过"，与"没验证"完全不同）。
- `proved` 只有在存在 proof 级实验时才为 True（FC-22）。

## 已知边界（**如实标注，不要读成缺陷**）

- `params` / `artifact_paths` 是**信息性字段**：本模块不会把它们变成命令行参数，
  也不会去读那些产物文件。记录它们是为了"这条实验当时是怎么跑的"可被复核。
- 本模块**不调用 LLM**（`llm` 位置参数仅为与 A–D 的构造签名保持一致，当前未使用）：
  数值实验的判读必须是确定性的（FC-16）。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import schema as S
from .store import Store
from .tools import verify_tools as VT
from .tools.base import ToolError, ToolRegistry

__all__ = [
    "AgentE",
    "ExperimentError",
    "REPRO_RESULT_PREFIX",
    "build_experiment",
    "install_e_tools",
    "selftest",
]

#: 实验脚本在 stdout 里给出结构化结论的**唯一约定**。
#:
#: 为什么用一行前缀而不是"让脚本写一个 json 文件"：单行前缀的好处是
#: **零额外 IO、零额外约定**（不需要知道临时目录在哪、不需要清理），
#: 而且当脚本崩溃在打印之前时，"没有这一行"本身就是可判定的信号。
REPRO_RESULT_PREFIX = "REPRO_RESULT:"

#: 计算类方法（**拿不到 proof 的那一类**）。顺序与 `schema.EXPERIMENT_METHODS`
#: 的关系在导入期断言，理由同 `verify_tools._EVIDENCE_ORDER`：
#: "哪些方法算计算类"这个判断只能有一处定义，否则 schema 拒绝的组合
#: 与 E 推导的组合会静默不一致。
COMPUTATIONAL_METHODS = ("numeric", "symbolic", "exhaustive_search")
assert set(COMPUTATIONAL_METHODS) | {"formal"} == set(S.EXPERIMENT_METHODS), (
    f"COMPUTATIONAL_METHODS={COMPUTATIONAL_METHODS} 与 schema.EXPERIMENT_METHODS="
    f"{S.EXPERIMENT_METHODS} 不一致 —— '哪些方法拿不到 proof' 必须只有一处定义"
)

#: 崩溃 / 无结论时的证据等级。**刻意不是 cross_check**：
#: 什么都没观察到，连"交叉验证"都算不上（FC-25 的 `no_local_evidence` 同理）。
_NO_EVIDENCE_KIND = "heuristic"

#: 脚本 stdout 里抓取结论时最多看多少字符。防止一个把整个数据集 dump 到
#: stdout 的脚本把内存吃光（它不该这么做，但这是外部输入）。
_STDOUT_SCAN_LIMIT = 4 * 1024 * 1024

#: 写进 notes 的输出摘要长度上限。
_OUTPUT_DIGEST_WIDTH = 300


class ExperimentError(RuntimeError):
    """实验无法执行（脚本不存在 / 路径越界 / 方法不支持）。"""


def _digest(text: Any, width: int = _OUTPUT_DIGEST_WIDTH) -> str:
    """单行化 + 截断。写进 `notes` 的输出摘要用。"""
    s = " ".join(str(text or "").split())
    return s if len(s) <= width else s[: width - 1] + "…"


def _as_dict(value: Any) -> dict:
    """把"脚本给的 observations/counterexample"规整成 dict。

    ⚠️ 非对象一律丢弃为 `{}` / `None`，**不报错**：这两个字段是脚本的自由输出，
    形状不对时最安全的处置是"当作没给"，而不是让整条实验记录失败。
    与 `result` / `evidence_kind`（受控词表，格式非法即不认）的处理不同 ——
    那两个字段决定记录的语义，形状不对就没有语义可谈。
    """
    return dict(value) if isinstance(value, Mapping) else {}


def _extract_stdout_lines(stdout: str) -> list[str]:
    """取出 stdout 里所有 `REPRO_RESULT:` 行。

    取**全部**而不是最后一行：最后一行会被脚本后续的无意输出悄悄覆盖，
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
    notes 里写明是哪一种情况（**没打印** / JSON 坏了 / 字段值非法）。
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
            "不认这条结论（**不猜**它想说什么）"
        )
        return None, notes
    return payload, notes


def _normalize_evidence_kind(raw: Any, *, method: str, notes: list[str]) -> str:
    """把脚本自报的证据等级规整成 schema 允许的值，并把越权记进 notes。

    这条函数是 FC-22 在运行期的那一半：schema 是写入期的那一半。
    两半都需要 —— schema 拦得住"存进去的谎话"，拦不住"脚本以为自己证明了"。
    """
    if raw is None:
        # 脚本**没报**证据等级：默认 cross_check（"这不是证明"本身就写在默认值里）。
        return "cross_check"
    kind = str(raw)
    if kind not in S.EVIDENCE_KINDS:
        notes.append(
            f"脚本自报 evidence_kind={kind!r} 不在受控词表 {S.EVIDENCE_KINDS} 里 ⇒ 降级为 heuristic"
        )
        return _NO_EVIDENCE_KIND
    if kind == "proof" and method != "formal":
        notes.append(
            f"脚本自报 evidence_kind='proof'，但 method={method!r} 是计算类方法 ⇒ **拒绝并降级为 cross_check**。"
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

    **本函数的规则就是模块 docstring 里那份"推导规则"的实现**，两边必须一致；
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
            "notes": [f"脚本以 exit_code={exit_code} 结束 ⇒ **没有正常跑完**，不得记为任何正面结论"],
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
            # ⚠️ **不在这里兜底**。脚本声称"证否"却给不出反例，说明它的输出与
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

    # supports / inconclusive：**只能是"未证明"或"没有本地证据"**，不许是 disproved
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
    created_by: str = "agent-E",
) -> S.Experiment:
    """把"推导结果"装成一行 `Experiment`。**纯函数**（不碰 store），便于单测。

    它只做装配与校验，不做任何推导 —— 推导在 `_derive`，写入在 `AgentE.run_experiment`。
    这样"为什么这条记录长这样"可以脱离子进程被单独复现。
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
        for_question_id=for_question_id,
        notes="\n".join(
            [str(n) for n in list(derived.get("notes") or []) + list(extra_notes) if str(n).strip()]
        ),
        created_at=S.now_iso(),
        created_by=created_by,
    )
    # ⚠️ 这里**故意让异常冒出来**：如果推导出的组合违反 schema 硬约束，
    # 那是"推导规则与 schema 不一致"，是本项目最该炸的地方。
    # 用 try/except 吞掉它，就会得到一条表里没有、日志里没有、只有调用方以为成功的记录。
    row.validate()
    return row


class AgentE:
    """数值实验与形式化验证智能体。

    每个方法都可以被独立调用与单测：

    - :meth:`run_experiment` —— 执行脚本 + 登记一行 Experiment；
    - :meth:`check_formal` —— 转发到形式化检查器（无后端时**如实**返回"没做"）；
    - :meth:`evidence_for` —— 三态查询：没查 / 查了没有 / 查到了什么；
    - :meth:`list_experiments` —— 只读列表。

    LLM：**没有**。数值实验的判读必须是确定性的（FC-16）。构造签名保留 `llm`
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
        #: 未使用（见类 docstring 末段）。保留它是为了**显式说明 E 不用 LLM**，
        #: 而不是让调用方以为"没传 llm 所以功能缺了一块"。
        self.llm = llm
        self.log = log

        # ---- 阈值全部来自 config，不写死在代码里（与 A–D 的既有做法一致）
        #: 默认超时（秒）。调用方可以在 `run_experiment(timeout=...)` 覆盖。
        self.default_timeout = int(self.cfg.get("timeout", 600))
        #: 脚本解释器。默认用**当前解释器**（`sys.executable`）：
        #: 用 `"python"` 会依赖 PATH，在 CI/虚拟环境里可能解析到**另一个** Python
        #: —— 于是"脚本在 E 里跑得通"与"在命令行里跑得通"变成两件事。
        self.python = str(self.cfg.get("python") or sys.executable or "python")
        #: 允许的脚本后缀。不是白名单本身，而是**给"我不知道怎么跑它"一个明确说法**：
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

    # ------------------------------------------------------------ 小工具

    def _log(self, message: str, **extra: Any) -> None:
        if self.log is not None:
            try:
                self.log(message, **extra)
            except Exception:  # noqa: BLE001 - 日志失败不该打断实验
                pass

    def _resolve(self, rel: str | Path) -> Path:
        """把脚本路径解析到**工作区内**，越界即拒绝。

        为什么这条闸必须在 `open()` 之前：`script_path` 是本模块唯一的
        "外部输入 → 执行"通道。允许 `../../` 就等于允许框架执行工作区外的
        任意代码，而这**不会报任何错** —— 它只会"成功"。
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
        但**原因必须留痕**（否则"没查到"与"工具坏了"在调用方眼里长得一样）。
        """
        res = self.tools.call(name, **params)
        if not res.ok:
            self.last_tool_errors.append({"tool": name, "error": res.error, "kind": res.meta.get("kind")})
            return None
        return res.data

    # ------------------------------------------------------------ 执行

    def _command_for(self, path: Path) -> list[str]:
        """按后缀给出命令行。**未知后缀直接拒绝**，不猜。"""
        suf = path.suffix.lower()
        if suf == ".py":
            return [self.python, str(path)]
        if suf == ".ps1":
            exe = "pwsh" if _which("pwsh") else "powershell"
            return [exe, "-NoProfile", "-NonInteractive", "-File", str(path)]
        raise ExperimentError(
            f"不知道怎么执行 {suf or '（无后缀）'} 文件（已知 {self.allowed_suffixes}）。"
            "**拒绝猜**：把 .jl 当 Python 跑会得到一个看起来像脚本 bug 的报错，"
            "而真正的错误是调用方给错了文件"
        )

    def _run_script(self, path: Path, *, timeout: int) -> dict:
        """在**独立进程**里跑脚本，捕获 stdout/stderr/exit_code。

        为什么必须是独立进程（而不是 `exec` 到本进程里）：实验脚本是我们
        **不完全信任**的代码 —— 它可能死循环、可能 `sys.exit`、可能改全局状态。
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
            # 解释器不存在 / 权限不足等：这是**没跑起来**，不是"跑失败"。
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
    ) -> dict:
        """跑一个实验脚本并登记一条 `Experiment` 行。

        推导规则见模块 docstring（**唯一权威表述**，实现是 :func:`_derive`）。

        返回 ``{"experiment_id", "recorded", "result", "evidence_kind",
        "negation_kind", "exit_code", "reason"}``。

        ⚠️ **schema 校验失败必须让异常冒出来**（本方法不做 try/except 兜底）：
        那说明上面的推导规则与 `Experiment.validate` 不一致，
        而"推导规则与 schema 打架"正是本项目最该炸的地方。
        """
        if not str(claim).strip():
            raise ExperimentError("claim 不能为空（没有命题就没有实验）")
        if not str(claim_key).strip():
            raise ExperimentError("claim_key 不能为空（没有它就无法回答'这条实验检验的是哪个命题'）")
        if method not in S.EXPERIMENT_METHODS:
            raise ExperimentError(f"method 必须是 {S.EXPERIMENT_METHODS} 之一，收到 {method!r}")

        # ---- [1] 路径解析（越界即拒绝）
        path = self._resolve(script_path)
        if not path.is_file():
            raise ExperimentError(f"脚本不存在：{script_path!r}（解析为 {path}）")

        # ---- [2] 可复现性绑定：复用 verify_tools.code_hash，不另写一份
        try:
            chash = VT.code_hash(path)
        except ToolError as e:
            raise ExperimentError(f"计算 code_hash 失败：{e}") from e

        # ---- [3] 独立进程执行 + 超时
        run = self._run_script(path, timeout=timeout if timeout is not None else self.default_timeout)

        # ---- [4] 推导 result / evidence_kind / negation_kind（规则见模块 docstring）
        derived = _derive(run["exit_code"], run["stdout"] or "", method=method)

        notes = list(derived.pop("notes", []) or [])
        head = f"exit_code={run['exit_code']}"
        if run.get("timed_out"):
            head += f"，**超时**（timeout={timeout}s）"
        if run.get("launch_error"):
            head += f"，**启动失败**（{run['launch_error']}）"
        notes.insert(0, f"[run] {head}，runtime={run['runtime_sec']}s，脚本 {script_path}（sha256 前 16 位 {chash}）")
        if run.get("stderr"):
            notes.append(f"[stderr] {_digest(run['stderr'])}")
        if run.get("stdout") and derived["result"] != "supports":
            # 只有在"结论不是支持"时才附 stdout 摘要：支持类结论已经有
            # 结构化 observations 可读，再贴一段原始输出只是噪声。
            notes.append(f"[stdout] {_digest(run['stdout'])}")

        # ---- [5] 一个事务：alloc_id + 写 experiments
        #
        # `alloc_id` 必须在**持锁事务内**进行，否则两个 E 实例会拿到同一个
        # experiment_id，而按主键 upsert 会静默互相覆盖（ID 发号与建行必须同锁）。
        with self.store.tx("experiments", actor=self.actor, note="e.run_experiment") as tx:
            eid = tx.alloc_id("experiment")
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

    # ------------------------------------------------------------ 转发 / 查询

    def check_formal(self, claim: str, *, script_path: str | None = None) -> dict:
        """转发到 `tools/verify_tools.check_formal`（**唯一实现**）。

        无后端时**必须**返回 ``checked=False, reason="no_backend"``。
        它与 ``verified=False`` 是两件事：后者是"验证没过"（命题可疑），
        前者是"我们没验证"（命题未被检验）。把两者折叠，下游就会把
        "本环境没有证明检查器"读成"这个命题被证伪了"。
        """
        res = VT.check_formal(claim, script_path=script_path)
        if not res.ok:
            # 传递失败（如 not_implemented）也带上三态位，避免调用方只看 ok 就当成"没验证过"
            return {
                "checked": False,
                "verified": None,
                "claim": claim,
                "reason": f"tool_failed:{res.meta.get('kind') or 'error'}",
                "detail": res.error or "",
                "verifier_output": "",
            }
        return dict(res.data or {})

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


def _result_reason(row: S.Experiment) -> str:
    """给人看的一句话解释（**不替代 notes**，只是列表展示用）。"""
    if row.exit_code not in (0, None):
        return f"脚本 exit_code={row.exit_code} ⇒ 未正常跑完，记 inconclusive（崩溃不得当成支持）"
    if row.result == "supports":
        return (
            f"{row.method} 实验支持该命题，证据等级 {row.evidence_kind}"
            + ("（**有形式化检查器输出**）" if row.evidence_kind == "proof" else "（**不构成证明**）")
        )
    if row.result == "refutes":
        return "实验给出反例 ⇒ disproved（已证否，且反例已登记）"
    return f"未得到可判定的结论（negation_kind={row.negation_kind}）"


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

    与其他角色同样的思路：E **只通过 registry 调用工具**，于是"工具 handler 的实现"
    与"AgentE 的方法"必须共用同一份代码 —— 否则两个入口会写出字段口径不同的记录。
    本框架的做法是让工具 handler 惰性构造一个 AgentE（见 verify_tools 的 docstring）。
    """
    reg = registry if registry is not None else ToolRegistry(name="agent-E")
    root = Path(workspace_root) if workspace_root is not None else Path(store.root)
    VT.register(reg, store=store, root=root)
    return reg


# ---------------------------------------------------------------- 自检


def selftest() -> int:
    """离线自检：不联网、不依赖仓库里的任何外部文件，返回失败数。

    运行方式::

        cd D:\\Incubator\\test\\test1\\src
        $env:PYTHONIOENCODING='utf-8'; python -m abflow.agent_e

    覆盖的核心性质（每一条都对应一个"如果错了会很安静"的失败模式）：

    1. 正常脚本 ⇒ 登记成功，exit_code=0，code_hash 非空；
    2. 脚本自报 proof ⇒ **被降级为 cross_check**，且 notes 里记了这件事；
    3. 脚本崩溃 ⇒ inconclusive + no_local_evidence（崩溃不得写成支持）；
    4. 脚本不打印 REPRO_RESULT ⇒ inconclusive + no_local_evidence；
    5. 路径越界 ⇒ 拒绝；
    6. 超时 ⇒ inconclusive 且原因可见；
    7. evidence_for 三态：没查 / 查了没有 / 查到了什么；
    8. 只写一行 experiments（事务性）。
    """
    import sys as _sys
    import tempfile

    try:
        _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    failures = 0

    def check(label: str, cond: bool, extra: str = "") -> None:
        nonlocal failures
        okk = bool(cond)
        if not okk:
            failures += 1
        print(f"    [{'PASS' if okk else 'FAIL'}] {label}" + (f"  {extra}" if extra else ""))

    print("=" * 72)
    root = Path(tempfile.mkdtemp(prefix="abflow-agente-"))
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
    cf = e.check_formal("1+1=2")
    print(f"[9] check_formal ⇒ checked={cf.get('checked')} reason={cf.get('reason')!r} "
          f"verified={cf.get('verified')!r}")
    if cf.get("checked") is False:
        check("无后端 ⇒ reason='no_backend' 且 verified 为 None（不是 False）",
              cf.get("reason") == "no_backend" and cf.get("verified") is None)
    else:
        print("    [SKIP] 本机探测到证明检查器，跳过 no_backend 断言（如实标注）")

    print("=" * 72)
    print(f"SELF-CHECK {'DONE' if failures == 0 else 'FAILED'}（agent_e）：失败 {failures} 项")
    return failures


if __name__ == "__main__":  # pragma: no cover - 手工运行的自检块
    raise SystemExit(selftest())

"""Lean 形式化验证后端：把 `evidence_kind="proof"` 这句话变成一次真的检查。

## 为什么这一层必须单独存在

`tools/verify_tools.py`（禁改区）的 `check_formal` 曾经如实声明自己没有接线：
它只做探测与三态判定，从不真的跑检查器。那条路线上，"有后端"与"证完了"
之间没有任何东西 —— 于是 `proof` 级证据只能是一句人写的断言。

P1 已把两者接上：`check_formal` 现在转发到本模块的 :func:`check_lean`，
本模块因此成为"什么算证明"的唯一定义处（工具层只做参数归一与三态折算）。

本模块补的正是"真的跑一次、并逐条判它算不算证明"这一段：

1. 把 Lean 源码写成临时 `.lean` 文件，真起检查器（或注入的等价物）；
2. 解析它的输出，按受控词表给出结论；
3. 只有 :data:`PROOF_STATUS`（即 `verified`）才允许产出 `proof` 级证据。

它不修改禁改区：探测复用 `tools.verify_tools.detect_verifier`（只 import 调用）。

## 四条硬判据（本模块的全部价值所在）

| 判据 | 为什么它是必须的 |
|---|---|
| `sorry` 不算证明 | 含 `sorry` 的文件会正常编译通过（退出码 0）——"它编译过了"与"它被证明了"在退出码上完全一样 |
| 公理审计 | 一个用到 `MyAxiom` 的"证明"是"假设了结论再宣布结论"，退出码同样正常 |
| 声明名必须被检查到 | 声称证明了 `foo`、文件里却没有 `foo`：退出码可能仍是 0，而不检查名字就会放过它 |
| 超时是"没查成" | `timeout` 与 `compile_error` 折叠成一个之后，"没查完"会被读成"证伪了" |

外加一条贯穿全模块的三态纪律：`no_backend`（可判定地没有后端）
绝不等同于通过，也绝不等同于失败 —— 它是"本次没有结论"。

## 受控词表

:data:`STATUSES` 八值。除了 `verified`，任何一个都不得产出 `proof` 级证据。
默认状态刻意是 `tool_crashed`：任何没有走到结论的代码路径都不许看起来像通过。

## 为什么键的判定顺序是这样（改它之前请先读这一节）

1. `no_backend` / `tool_crashed` / `timeout` —— 三种"没查成"，最先判。
   后面所有判据都建立在"检查器真的回了话"之上。
2. `decl_mismatch`（静态）—— 待检查文件里根本没有这个名字。
   它在编译之前就能判，且比 `compile_error` 更有信息量：
   "文件里有语法错"与"文件里压根没有你要证的东西"是两件不同的事。
3. `uses_sorry`（静态）—— 源码里出现 `sorry`/`admit`。与编译是否通过无关。
4. `compile_error` —— 退出码非零。
5. `uses_sorry`（来自公理审计）—— 退出码 0 且公理表里出现 `sorryAx`
   （`sorry` 藏在被调用且真的已编好的引理里：那时文件真的精化通过了，
   `sorryAx` 是这次检查的证据而不是残渣）。
6. `extra_axioms` —— 公理超出允许集。
7. `decl_mismatch`（来自输出）—— 编译过了、但输出里没有被检查到的那个名字
   （例如 `#print axioms` 什么都没打出来）。这一条是 fail-closed 的：
   输出为空即判不匹配，而不是"没看见就当通过"。
8. 全过 ⇒ `verified`。
"""

from __future__ import annotations

import hashlib
import re
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

__all__ = [
    "BACKEND_NAME",
    "STATUSES",
    "PROOF_STATUS",
    "PROBE_STATUSES",
    "ALLOWED_AXIOMS",
    "FORBIDDEN_AXIOMS",
    "detect_backend",
    "declaration_name",
    "lean_snippets",
    "check_lean",
    "evidence_of",
    "selftest",
]

#: 本模块唯一实现的后端。Coq/Isabelle 的名字出现在探测层里，但本模块不解释它们的输出 ——
#: "看得见二进制"与"解释得了它的输出"是两件事，把后者当前者就是桥接层说谎。
BACKEND_NAME = "lean"

#: `check_lean` 的 `status` 受控词表。只有 `verified` 允许产出 `proof` 级证据。
STATUSES: tuple[str, ...] = (
    "verified",
    "compile_error",
    "uses_sorry",
    "extra_axioms",
    "decl_mismatch",
    "timeout",
    "no_backend",
    "tool_crashed",
)

#: 唯一允许的"证明通过"结论。
PROOF_STATUS = "verified"

#: `detect_backend` 的三态。注意它不是 `STATUSES` 的子集：
#: 探测回答的是"后端在不在"，检查回答的是"这次算不算证明"。
PROBE_STATUSES: tuple[str, ...] = ("available", "no_backend", "probe_failed")

#: 允许出现的公理（Lean 4 / Mathlib 的常规三条）。
ALLOWED_AXIOMS = frozenset({"propext", "Classical.choice", "Quot.sound"})

#: 明确禁止的公理。`sorryAx` 必须落在禁止侧：它等价于"这里我跳过了"。
FORBIDDEN_AXIOMS = frozenset({"sorryAx"})

#: 真的跑到了结论的那些状态（"查了"）。其余三态是"没查成"。
_CONCLUDED_STATUSES = ("verified", "compile_error", "uses_sorry", "extra_axioms",
                       "decl_mismatch")

#: 合法声明名的形状。挡住空名与带空白的名字 ——
#: 它们拼进 `#print axioms` 会让检查器报一个与"这个命题"无关的语法错，
#: 而那种错误会被读成"证明没过"。
_NAME_RE = re.compile(r"^[^\s:;()\[\]{},]+$")

#: 允许出现在声明前的修饰符与声明关键字。
_MODIFIERS = ("private", "protected", "noncomputable", "partial", "unsafe", "scoped", "local")
_DECL_KEYWORDS = ("theorem", "lemma", "def", "abbrev", "opaque", "axiom", "instance",
                  "structure", "class", "inductive", "example")
_NAMED_DECL_KEYWORDS = tuple(k for k in _DECL_KEYWORDS if k != "example")

#: Lean 注释与字符串（去噪用）。块注释不递归匹配：注释里出现 `sorry`
#: 与"真的用了 sorry"是两件事，非嵌套匹配足以区分它们。
_BLOCK_COMMENT = re.compile(r"/-.*?-/", re.S)
_STRING_LITERAL = re.compile(r'"(?:\\.|[^"\\\n])*"')
_LINE_COMMENT = re.compile(r"--[^\n]*")
_SORRY = re.compile(r"\b(?:sorry|admit)\b")

#: `#print axioms foo` 的输出形状：
#: `'foo' depends on axioms: [propext, Classical.choice, Quot.sound]`
#: 或 `'foo' does not depend on any axioms`。
_AXIOM_LIST = re.compile(r"depends on axioms:\s*\[([^\]]*)\]", re.S)
_NO_AXIOMS = re.compile(r"does not depend on any axioms")

#: 代码块（模型答复里的 Lean 片段）。`lean` / `lean4` 两种语言标注都收。
_FENCE = re.compile(r"```+[ \t]*(?:lean4?)[ \t]*\n(.*?)```+", re.S | re.I)

#: `check_lean` 的注入接缝签名说明（不参与运行，只给类型检查与读者）。
RunFn = Callable[..., Mapping[str, Any]]
ProbeFn = Callable[[], Mapping[str, Any]]


# ---------------------------------------------------------------- 探测后端


def _default_probe() -> Mapping[str, Any]:
    """生产路径的真探测：调用禁改区里既有的探测层（不重写一份）。

    为什么复用而不是自己 `shutil.which("lean")`：探测口径只能有一处。
    自己再写一份的话，"哪个名字算 Lean"这件事会有两个答案，
    而它们漂移的症状是"探测说有后端、检查时二进制却不在"这类难以定位的分歧。
    """
    from .tools.verify_tools import detect_verifier  # 惰性：避免 import 期拉起整个工具层

    return detect_verifier()


def _probe_result(status: str, *, reason: str, version: str = "", path: str = "",
                  checked: bool = False, probe_errors: Sequence[str] = ()) -> dict:
    """`detect_backend` 的返回构造（一处定义形状，免得三条分支给的键不一样）。"""
    return {
        "status": status,
        "backend": BACKEND_NAME,
        "checked": checked,
        "version": version,
        "path": path,
        "reason": reason,
        "probe_errors": [str(e) for e in probe_errors],
    }


def detect_backend(*, probe_fn: ProbeFn | None = None) -> dict:
    """探测 Lean 后端，三态：`available` / `no_backend` / `probe_failed`。

    ## 为什么必须是三态（本项目最贵的那个缺陷形态）

    "探测了，环境里没有 Lean"与"探测本身没做成"是两件完全不同的事：
    前者是一个有效结论（本次无法产出 proof 级证据），后者是"我们不知道"。
    把两者折叠成同一个 `False`，下游会把"没查成"读成"环境里确定没有 Lean" ——
    而"确定没有"会让一条本该走形式化核验的命题悄悄停在 cross_check 上，
    且没有任何地方报错。

    ## `probe_fn` 是唯一测试接缝

    生产为 `None`（调 `tools.verify_tools.detect_verifier`）。测试注入一个假探测函数，
    因此整套用例完全离线、不起任何外部进程。`probe_fn` 抛异常也算 `probe_failed` ——
    "探测函数炸了"与"没有后端"不能混。
    """
    probe = probe_fn if probe_fn is not None else _default_probe
    try:
        raw: Any = probe()
    # noqa: BLE001 - 探测层的任何异常都只能落"没查成"，不能变成"没有后端"
    except Exception as exc:
        return _probe_result(
            "probe_failed",
            reason=(f"探测没做成（{type(exc).__name__}: {exc}）⇒ 不是'环境里没有后端'，"
                    "而是'我们不知道'"),
            probe_errors=[f"{type(exc).__name__}: {exc}"],
        )
    if not isinstance(raw, Mapping):
        return _probe_result(
            "probe_failed",
            reason=(f"探测层返回了 {type(raw).__name__}，不是它声明的结构 ⇒ "
                    "没有可信的探测结论"),
        )
    errors = [str(e) for e in (raw.get("probe_errors") or [])]
    names = [str(n) for n in (raw.get("available_names") or [])]
    if not raw.get("checked"):
        return _probe_result(
            "probe_failed",
            reason=(f"探测层报告 checked=False ⇒ 本次探测没做成：{raw.get('reason')}"),
            probe_errors=errors or [str(raw.get("reason") or "探测没做成")],
        )
    if BACKEND_NAME not in names:
        return _probe_result(
            "no_backend",
            reason=(f"探测完成：环境里没有 {BACKEND_NAME} "
                    f"（探到的是 {names or '无'}）⇒ 本环境无法产出 proof 级证据"),
            checked=True,
            probe_errors=errors,
        )
    entry = next(
        (e for e in (raw.get("available") or []) if str(e.get("name")) == BACKEND_NAME),
        {},
    )
    return _probe_result(
        "available",
        reason=f"探测到 {BACKEND_NAME}：{entry.get('version') or '(版本未知)'}",
        version=str(entry.get("version") or ""),
        path=str(entry.get("path") or ""),
        checked=True,
        probe_errors=errors,
    )


# ---------------------------------------------------------------- 源码分析


def _strip_lean_noise(text: str) -> str:
    """去掉块注释、字符串字面量与行注释（注释里的 `sorry` 不算用了 `sorry`）。

    顺序是刻意的：块注释 → 字符串 → 行注释。反过来处理会让 `"--"` 这种
    出现在字符串里的内容被当成注释，从而删掉本不该删的代码。
    """
    out = _BLOCK_COMMENT.sub(lambda m: "\n" * m.group(0).count("\n"), text)
    out = _STRING_LITERAL.sub("", out)
    return _LINE_COMMENT.sub("", out)


def _sorry_count(source: str) -> int:
    """源码里真的用了几个 `sorry` / `admit`（注释与字符串里的不算）。"""
    return len(_SORRY.findall(_strip_lean_noise(source)))


def declaration_name(source: str) -> str:
    """取出源码里第一条具名声明（`theorem` / `lemma` / `def` ...）的名字。

    为什么需要它：模型给的 Lean 片段是自由文本，而"这条片段声称证了什么"
    必须有一个机器可读的答案 —— 公理审计（`#print axioms <name>`）与
    声明名核对都要求这个名字。`example` 没有名字，返回空串表示"取不到"，
    调用方不得把它当成"证了某个东西"。
    """
    body = _strip_lean_noise(str(source or ""))
    pat = re.compile(
        r"(?m)^[ \t]*(?:@\[[^\]]*\][ \t]*)*"
        r"(?:(?:" + "|".join(_MODIFIERS) + r")[ \t]+)*"
        r"(?:" + "|".join(_NAMED_DECL_KEYWORDS) + r")[ \t]+([^\s:{(]+)"
    )
    m = pat.search(body)
    return m.group(1).strip() if m else ""


def _declared_in_source(source: str, name: str) -> bool:
    """待检查的源码里真的声明了 `name` 吗？

    接受全名与最后一段（`Nat.foo` 与 `foo`）：Lean 里 `namespace` 之后写的短名
    在全名空间里是另一个名字，而"用户给了哪个"取决于调用方看的是文件还是命名空间。
    宁可两种情况都认，也不要因为这一处措辞差异把一次真的证明判成 `decl_mismatch`。
    """
    body = _strip_lean_noise(str(source or ""))
    short = name.rsplit(".", 1)[-1]
    for candidate in dict.fromkeys((name, short)):
        pat = re.compile(
            r"(?m)^[ \t]*(?:@\[[^\]]*\][ \t]*)*"
            r"(?:(?:" + "|".join(_MODIFIERS) + r")[ \t]+)*"
            r"(?:" + "|".join(_DECL_KEYWORDS) + r")[ \t]+"
            + re.escape(candidate) + r"(?![A-Za-z0-9_'.!?])"
        )
        if pat.search(body):
            return True
    return False


def lean_snippets(text: str) -> list[dict]:
    """从一段文本里取出 Lean 代码块 ⇒ `[{"source", "name"}]`（name 可为空串）。

    为什么按代码块取而不是猜：约定 `` ```lean `` 是模型侧唯一可机械识别的形态。
    从自然语言里猜"哪一段是形式化代码"，判的就变成解析器聪不聪明，
    而不是"证明成不成立" —— 那正是 `evidence.parse_claims` 反复强调的取舍。
    """
    out: list[dict] = []
    for m in _FENCE.finditer(str(text or "")):
        body = m.group(1).strip("\n")
        if not body.strip():
            continue
        out.append({"source": body, "name": declaration_name(body)})
    return out


# ---------------------------------------------------------------- 运行检查器


def _as_text(value: Any) -> str:
    """把超时异常里带的半截输出（可能是 bytes）变成文本。"""
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return str(value)


def _default_run(cmd: Sequence[str], *, cwd: str, timeout_sec: float) -> dict:
    """生产路径：真起检查器进程。

    超时不抛出去，而是返回 `timed_out=True`：调用方（`check_lean`）判的是
    "这次没查完"，而一个抛出去的 `TimeoutExpired` 在别处很容易被兜成"检查失败"——
    那就把"没查成"读成了"证伪了"。半截输出照样带回来（可能已经有编译错误）。
    """
    import subprocess

    try:
        proc = subprocess.run(list(cmd), cwd=cwd, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=timeout_sec)
    except subprocess.TimeoutExpired as exc:
        return {"exit_code": None, "stdout": _as_text(exc.stdout), "stderr": _as_text(exc.stderr),
                "timed_out": True}
    return {"exit_code": int(proc.returncode), "stdout": proc.stdout or "",
            "stderr": proc.stderr or "", "timed_out": False}


def _normalize_run(raw: Any) -> dict:
    """把运行函数的返回值归一。垃圾返回值是错误（`check_lean` 会兜成 `tool_crashed`），
    因为"看不懂运行结果"与"检查器说通过"之间隔着整个可信度问题。"""
    if not isinstance(raw, Mapping):
        raise TypeError(f"运行函数必须返回 dict，收到 {type(raw).__name__}")
    code = raw.get("exit_code")
    return {
        "exit_code": None if code is None else int(code),
        "stdout": str(raw.get("stdout") or ""),
        "stderr": str(raw.get("stderr") or ""),
        "timed_out": bool(raw.get("timed_out")),
        "backend_version": str(raw.get("backend_version") or ""),
    }


def _axioms_of(text: str) -> list[str]:
    """从检查器输出里解析公理表。`does not depend on any axioms` ⇒ 空列表。"""
    if _NO_AXIOMS.search(text):
        return []
    out: list[str] = []
    for m in _AXIOM_LIST.finditer(text):
        for piece in m.group(1).split(","):
            name = piece.strip()
            if name and name not in out:
                out.append(name)
    return out


def _file_text(source: str, imports: Sequence[str], audit_name: str) -> str:
    """待检查文件的全文：imports + 源码 +（可选）公理审计命令。

    `audit_name` 为空时不追加 `#print axioms`：对没有声明的名字追一条审计命令，
    检查器会报一个语法/未知标识符错误，而那个错误会被误读成"证明没过"。
    这里让"没有名字"在编译之前就被静态判据拦住（见 `check_lean` 的顺序）。
    """
    lines = [f"import {m}" for m in imports if str(m).strip()]
    if lines:
        lines.append("")
    lines.append(str(source).rstrip("\n"))
    if audit_name:
        lines += ["", f"#print axioms {audit_name}"]
    return "\n".join(lines) + "\n"


def _conclude(result: dict, status: str, reason: str) -> dict:
    """收口：写 status/reason，并把"实际到达的证据等级"一并算好（只此一处）。"""
    if status not in STATUSES:
        raise ValueError(f"status 必须是 {STATUSES} 之一，收到 {status!r}")
    result["status"] = status
    result["reason"] = reason
    result["evidence"] = evidence_of(result)
    return result


def evidence_of(result: Mapping[str, Any]) -> dict:
    """这次检查实际到达了什么证据等级 —— 三态，而不是一个布尔。

    - `verified` ⇒ `checked=True, proved=True, evidence_kind="proof"`；
    - 跑了但没通过（`compile_error` / `uses_sorry` / `extra_axioms` / `decl_mismatch`）
      ⇒ `checked=True, proved=False, evidence_kind=None`（这次没有拿到任何等级的证据）。
      为什么不是 `cross_check`：那是"另一个方法旁证过"，而这里"没通过"给不出旁证；
      把它写成 `cross_check` 会让"检查失败"变成一条正面证据。
    - `timeout` / `no_backend` / `tool_crashed` ⇒ `checked=False`（没查成）。
    """
    status = str(result.get("status") or "")
    concluded = status in _CONCLUDED_STATUSES
    proved = status == PROOF_STATUS
    return {
        "checked": concluded,
        "proved": proved,
        #: `proof` 与 `verified` 是同一件事的两种写法，因此这里只有一个来源。
        "evidence_kind": "proof" if proved else None,
        "status": status,
        "reason": (
            f"Lean 检查结论 {status}：{'可以产出 proof 级证据' if proved else '不构成证明'}"
            if concluded
            else f"Lean 检查没查成（{status}）⇒ 本次没有形式化验证结论，"
                 "既不是通过也不是证伪"
        ),
    }


def _safe_stem(name: str) -> str:
    """文件名用的安全词干（Lean 直接跑文件时不要求文件名与模块名一致）。"""
    return re.sub(r"[^A-Za-z0-9_]+", "_", name).strip("_") or "claim"


def check_lean(source: str, *, name: str, imports: Sequence[str] = ("Mathlib",),
               timeout_sec: float = 600, run_fn: RunFn | None = None,
               workdir: str | Path | None = None,
               source_path: str | Path | None = None) -> dict:
    """把一段 Lean 源码交给检查器真跑一次，并按受控词表给出结论。

    返回至少这些键：`status` / `exit_code` / `stdout` / `stderr` / `elapsed_sec` /
    `backend_version` / `source_sha256` / `axioms` / `sorry_count` / `decl_matches` /
    `reason`；另有 `name` / `checked_source` / `path` / `imports` / `ran` / `backend` /
    `evidence` 便于产物把"到底查了什么"写清楚（`checked_source` 是逐字交给检查器的那份
    文本，含追加的 `#print axioms`；`path` 在未给 `workdir` 时是临时路径，调用结束即清理；
    `ran` 表示检查器真的回了一个可用结论 —— 静态判据下结论、后端不在、超时三种都是 False）。

    判定顺序与理由写在模块 docstring 的这一节里；改动它之前请先读那一节。

    `run_fn` 是唯一的运行接缝：签名为 ``run_fn(cmd, *, cwd, timeout_sec) -> dict``，
    必须返回 ``{"exit_code", "stdout", "stderr", "timed_out"}``（可另带
    `backend_version`）。注入它时不作探测 —— 调用方等于声明"后端由我负责"，
    测试因此完全离线。它抛 `FileNotFoundError` 表示后端二进制不在
    （探测通过之后二进制消失就是这个形态）⇒ `no_backend`；抛别的异常、
    或返回看不懂的东西 ⇒ `tool_crashed`。

    `source_path` 是"源码来自哪个文件"的可选入口，与 `source` 二选一：
    给了它且 `source` 为空时，本函数自己按 UTF-8 读取该文件（读不到时
    `source` 留空，于是下面的静态判据照常给出 `decl_mismatch`，而不是让调用方
    各自实现一份读文件）。为什么要在这里收这一个入口：`tools/verify_tools.py`
    的 `check_formal` 是转发层，而转发层重复实现"怎么读文件、读不到算哪种失败"
    正是同一判据长出两份实现的典型形态。两个都为空时抛 `ValueError` ——
    "没有源码"与"源码里没有那个声明"是两件必须分开的事，前者是调用方写错了。

    `imports` 默认 `("Mathlib",)`。裸 `lean` 不会替你跑 `lake`：
    若这些模块在当前 `LEAN_PATH` 下不可用，结果是 `compile_error`（如实），
    而不是"没有后端" —— 后者会让一件纯环境配置问题看起来像"环境不支持形式化验证"。
    """
    src = str(source or "")
    read_failed = ""
    if not src and source_path is not None:
        # 读取失败不在这里抛：调用方（工具层）要的是"没查成"的结构化结论。
        # 但它也不许被折叠成"文件里没有那条声明"—— 那会把"路径写错了"
        # 说成"你证的东西不在文件里"，两者的处置完全不同。所以失败原因留在这里，
        # 由下面第一条判据如实报出。
        try:
            src = Path(source_path).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            read_failed = f"{type(exc).__name__}: {exc}"
            src = ""
    if not src.strip() and not read_failed and not (source or "").strip():
        # 这一支是"调用方什么都没给"：两条入口都空着，属于参数写错了，
        # 必须在起进程之前就抛出来（它与"文件读不到"是两件不同的事）。
        raise ValueError(
            "check_lean 需要 Lean 源码：`source` 与 `source_path` 至少给一个 —— "
            "'没有源码可查'与'源码里没有那条声明'是两件事，折叠成同一个结论"
            "会让前者看起来像一次失败的验证"
        )
    nm = str(name or "").strip()
    if not nm or not _NAME_RE.match(nm):
        raise ValueError(
            f"name 必须是非空的无空白标识符（收到 {name!r}）—— "
            "名字会被拼进 `#print axioms`，拼不对时检查器报的是语法错，"
            "而那个错误会被读成'证明没过'"
        )
    declared = _declared_in_source(src, nm)
    sry = _sorry_count(src)
    result: dict[str, Any] = {
        # 默认是最坏的那个状态：任何没走到结论的路径都不许看起来像通过。
        "status": "tool_crashed",
        "name": nm,
        "exit_code": None,
        "stdout": "",
        "stderr": "",
        "elapsed_sec": 0.0,
        "backend_version": "",
        # 给的是"声称要证的那段源码"的哈希（不是我们临时拼出来的包装文件）：
        # 复核的是"这份证明"，而包装文件由本模块确定地生成。
        "source_sha256": hashlib.sha256(src.encode("utf-8")).hexdigest(),
        "axioms": [],
        "sorry_count": sry,
        "decl_matches": False,
        "declared_in_source": declared,
        "reason": "",
        "imports": [str(m) for m in imports],
        "checked_source": "",
        "path": "",
        #: 源码来自哪个文件（没走 `source_path` 时为空串）。它不是 `path`：
        #: `path` 是临时物化出来的那份包装文件，而复核者要能回答的是
        #: "逐字查的是哪一份源码"，调用方给的那个路径才是答案。
        "source_path": "",
        #: 检查器真的回了一个可用结论吗？三种情况都是 False：
        #: 静态判据在起进程之前就下了结论（声明名不在文件里、源码里有 sorry）、
        #: 后端二进制不在、以及超时（那一刻它还没回话）。
        #: 调用方（`runflow` 的 Lean 段）用它决定"这一层算不算接上了"：
        #: 只有真跑出结论才允许把 lean 从未接线清单里摘掉。
        "ran": False,
        "backend": {},
        "evidence": {},
    }
    result["source_path"] = str(source_path) if source_path is not None and source == "" else ""

    version = ""
    exe = BACKEND_NAME
    if run_fn is None:
        probe = detect_backend()
        result["backend"] = probe
        version = probe["version"]
        result["backend_version"] = version
        exe = probe["path"] or BACKEND_NAME
        if probe["status"] == "no_backend":
            return _conclude(result, "no_backend", probe["reason"])
        if probe["status"] == "probe_failed":
            return _conclude(
                result, "tool_crashed",
                f"后端探测没做成 ⇒ 本次不是'环境里没有 Lean'，而是'没查成'：{probe['reason']}",
            )
    else:
        result["backend"] = {
            "status": "available", "backend": BACKEND_NAME, "checked": False,
            "version": "", "path": "", "probe_errors": [],
            "reason": "调用方注入了 run_fn ⇒ 后端由调用方负责，本次不做探测",
        }

    # ---- 静态判据（不必起进程就能判，因此排在编译错误之前）
    if read_failed:
        return _conclude(
            result, "decl_mismatch",
            f"读不了 source_path 给的源码文件（{read_failed}）⇒ 本次没有验证结论。"
            "刻意不把它说成'文件里没有那条声明'：路径写错了与命题不在文件里"
            "是两件事，而两者都不是通过。",
        )
    if not declared:
        return _conclude(
            result, "decl_mismatch",
            f"待检查的源码里没有声明 {nm!r} ⇒ 声称证明了的东西不在文件里"
            "（这一条不许因为'检查器退出码是 0'就放过）",
        )
    if sry:
        return _conclude(
            result, "uses_sorry",
            f"源码里有 {sry} 处 sorry/admit ⇒ 这不是证明。"
            "注意：含 sorry 的文件在 Lean 里会正常编译通过（退出码 0），"
            "所以退出码不能当证明的判据",
        )

    text = _file_text(src, imports, nm)
    result["checked_source"] = text
    path, tmp = _materialize(text, nm, workdir)
    result["path"] = str(path)
    t0 = time.monotonic()
    try:
        raw = (run_fn if run_fn is not None else _default_run)(
            [exe, str(path)], cwd=str(path.parent), timeout_sec=float(timeout_sec)
        )
        outcome = _normalize_run(raw)
        # 到这里才是"检查器回了一个可用的结果"。超时不算：那一刻它还没回话。
        result["ran"] = not outcome["timed_out"]
    except FileNotFoundError as exc:
        return _conclude(
            result, "no_backend",
            f"检查器二进制起不来（{type(exc).__name__}: {exc}）⇒ 本次没有后端，"
            "不是验证失败",
        )
    # noqa: BLE001 - 运行函数/返回值解析的任何异常都只能落"工具崩了"，
    # 绝不能兜成"验证通过"或"验证失败"。
    except Exception as exc:
        return _conclude(
            result, "tool_crashed",
            f"检查器没跑成（{type(exc).__name__}: {exc}）⇒ 没查成，"
            "既不是通过也不是证伪",
        )
    finally:
        result["elapsed_sec"] = round(time.monotonic() - t0, 6)
        if tmp is not None:
            # 临时文件不留在磁盘上：`checked_source` 已经逐字记下了查的是什么。
            tmp.cleanup()

    result["exit_code"] = outcome["exit_code"]
    result["stdout"] = outcome["stdout"]
    result["stderr"] = outcome["stderr"]
    result["backend_version"] = outcome["backend_version"] or version
    blob = outcome["stdout"] + "\n" + outcome["stderr"]
    axioms = _axioms_of(blob)
    result["axioms"] = axioms

    if outcome["timed_out"]:
        return _conclude(
            result, "timeout",
            f"超过 {timeout_sec} 秒还没查完 ⇒ 没查成（不是'证明不成立'，"
            "也不是'编译错误'：这两件事的处置完全不同）",
        )
    if "sorryAx" in axioms and outcome["exit_code"] == 0:
        return _conclude(
            result, "uses_sorry",
            "公理审计发现 sorryAx ⇒ 这段'证明'里有一处被跳过了"
            "（可能藏在它调用的引理里，所以静态扫描看不见）",
        )
    if outcome["exit_code"] != 0:
        # 退出码非零 ⇒ 这次没精化通过，因此它首先是编译失败，
        # 不是"用了 sorry"。判据顺序在这里是有意的：
        # Lean 的文件级 `#print axioms` 输出里会带出被 import 的 `sorryAx`
        # 之类的痕迹（实测：`theorem bad_one_eq_two : (1:Nat) = 2 := rfl`
        # 报 type mismatch，而 `#print axioms` 照样打出 `[sorryAx]`）。
        # 把那种残渣当成"这段证明里有一处被跳过了"，就把一次编译失败
        # 说成了另一件事。而"源码里真有 sorry"的情形在上面的静态判据
        # （第 3 条）就已经收口了，所以这里归 `compile_error` 不会漏掉真 sorry。
        tail = (outcome["stderr"] or outcome["stdout"]).strip().splitlines()
        hint = (
            "（另：公理审计里出现了 sorryAx，但本次没精化通过 ⇒ 它只是线索，"
            "不改变'这次是编译失败'这个结论）"
            if "sorryAx" in axioms
            else ""
        )
        return _conclude(
            result, "compile_error",
            f"检查器退出码 {outcome['exit_code']} ⇒ 编译/精化失败："
            f"{tail[0] if tail else '(没有输出)'}{hint}",
        )
    extra = [a for a in axioms if a not in ALLOWED_AXIOMS]
    if extra:
        return _conclude(
            result, "extra_axioms",
            f"用到了允许集之外的公理 {extra}（允许 {sorted(ALLOWED_AXIOMS)}，"
            f"禁止 {sorted(FORBIDDEN_AXIOMS)}）⇒ 这是在假设结论，不是证明结论",
        )
    seen = f"'{nm}'" in blob or nm in blob
    result["decl_matches"] = bool(seen)
    if not seen:
        return _conclude(
            result, "decl_mismatch",
            f"检查器退出码是 0，但输出里没有被检查到的 {nm!r} ⇒ 声明名对不上"
            "（判据 fail-closed：输出里没看见就当没检查到，不当通过）",
        )
    return _conclude(
        result, "verified",
        f"检查器退出码 0、无 sorry、公理 {axioms or '无'} 在允许集内、"
        f"且声明 {nm!r} 真的被检查到（用时 {result['elapsed_sec']} 秒）",
    )


def _materialize(text: str, name: str, workdir: str | Path | None) -> tuple[Path, Any]:
    """把待检查文本写成 `.lean` 文件。

    返回 `(路径, 临时目录对象或 None)`：给 `workdir` 时不建临时目录（也不清理），
    否则建一个由调用方负责清理的临时目录。"文件写在哪里"必须能被复核 ——
    命令行的 `lean <file>` 与 Lake 工程里的检查结果不会总是相同。
    """
    if workdir is None:
        tmp = tempfile.TemporaryDirectory(prefix="agentflow-lean-")
        base = Path(tmp.name)
    else:
        tmp = None
        base = Path(workdir)
        base.mkdir(parents=True, exist_ok=True)
    path = base / f"{_safe_stem(name)}.lean"
    path.write_text(text, encoding="utf-8")
    return path, tmp


# ---------------------------------------------------------------------- 自检


def selftest() -> int:
    """离线自检 + 真实后端探测（有 Lean 时真跑一次最小证明）。

    为什么要有它：本模块的价值全在"判据真的会红"。自检用注入的假运行函数
    把三条最贵的负控各跑一遍（含 sorry 且退出码 0 那种），并且如实报告
    本机有没有真的 Lean —— "没有真实输出"这件事必须写在输出里，而不是让
    读者把夹具当成真跑过。

    装了 Lean 的机器上（`lean` 在 PATH 里）它会多跑一条真实的
    `theorem one_plus_one : 1 + 1 = 2 := rfl`，并把检查器的原始 stdout 打出来；
    那条不通过就是问题 —— 桥接层的输出解析过时了，必须有人看。
    没装的机器上这条不执行，因此日常运行不依赖 Lean。
    """
    problems: list[str] = []
    fake_ok = {"exit_code": 0,
               "stdout": "'one_plus_one' depends on axioms: [propext, Classical.choice]\n",
               "stderr": "", "timed_out": False}
    good = "theorem one_plus_one : 1 + 1 = 2 := rfl\n"
    seen: dict[str, str] = {}

    r = check_lean(good, name="one_plus_one", imports=(), run_fn=lambda *a, **k: fake_ok)
    seen["clean"] = r["status"]
    if r["status"] != "verified" or r["evidence"]["evidence_kind"] != "proof":
        problems.append(f"正控：干净的证明应当 verified/proof：{r['status']}")

    sorry_src = "theorem one_plus_one : 1 + 1 = 2 := by sorry\n"
    r = check_lean(sorry_src, name="one_plus_one", imports=(), run_fn=lambda *a, **k: fake_ok)
    seen["sorry"] = r["status"]
    if r["status"] != "uses_sorry":
        problems.append(f"负控①：含 sorry 且退出码 0 不许判 verified：{r['status']}")
    if r["evidence"]["evidence_kind"] is not None:
        problems.append("负控①：没通过时不许产出 proof 级证据")

    extra = {"exit_code": 0, "stderr": "", "timed_out": False,
             "stdout": "'one_plus_one' depends on axioms: [MyAxiom]\n"}
    r = check_lean(good, name="one_plus_one", imports=(), run_fn=lambda *a, **k: extra)
    seen["extra_axioms"] = r["status"]
    if r["status"] != "extra_axioms":
        problems.append(f"负控②：额外公理不许判 verified：{r['status']}")

    blank = {"exit_code": 0, "stdout": "", "stderr": "", "timed_out": False}
    r = check_lean(good, name="one_plus_one", imports=(), run_fn=lambda *a, **k: blank)
    seen["decl_mismatch"] = r["status"]
    if r["status"] != "decl_mismatch":
        problems.append(f"负控③：退出码 0 但声明没被检查到不许判 verified：{r['status']}")

    probe = detect_backend()
    print(f"[formalgw] 假运行函数的结论：{seen}")
    print(f"[formalgw] 真实后端探测：{probe['status']} —— {probe['reason']}")
    if probe["status"] != "available":
        print("[formalgw] 注意：本次没有任何真实 Lean 输出，上面的结论全部来自注入的夹具")
    else:
        # 有后端就真跑一次最小证明：这一条是"桥接层有没有说谎"的直接证据。
        # 它只在装了 Lean 的机器上执行，所以日常（没装）不会拖慢任何东西。
        real = check_lean("theorem one_plus_one : 1 + 1 = 2 := rfl\n",
                          name="one_plus_one", imports=(), timeout_sec=120)
        print(f"[formalgw] 真实运行：status={real['status']} exit_code={real['exit_code']} "
              f"axioms={real['axioms']} stdout={real['stdout'].strip()!r}")
        if real["status"] != "verified":
            problems.append(
                f"有后端但最小证明没判 verified（{real['status']}：{real['reason']}）—— "
                "要么检查器输出形状变了，要么本模块的解析过时了，两种情况都必须有人看"
            )
    for p in problems:
        print(f"  [FAIL] {p}")
    if problems:
        return 1
    print("[formalgw] 四条硬判据的离线自检都对")
    return 0


def formal_main(argv: Any = None) -> int:
    """入口：目前只有自检。刻意不叫 `main`（`cli.main` 才是对外的唯一入口）。"""
    return selftest()


if __name__ == "__main__":
    raise SystemExit(formal_main())

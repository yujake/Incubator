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
| 库不可得是"没查成" | 包没装时检查器连编译都没开始（`error: unknown package 'Mathlib'`），把它说成 `compile_error`（查了没通过）是一句假话，而"这次没查成"与"这个命题不成立"的处置完全相反。判据只认检查器自己的诊断行：被检查源码自己打印的那一句话不算（`E-5`，见 `_MISSING_PACKAGE`） |

外加一条贯穿全模块的三态纪律：`no_backend`（可判定地没有后端）
绝不等同于通过，也绝不等同于失败 —— 它是"本次没有结论"。
同一条纪律适用于 `import_unavailable`：库不可得时这一次检查根本没发生。

## 受控词表

:data:`STATUSES` 十值。除了 `verified`，任何一个都不得产出 `proof` 级证据。
默认状态刻意是 `tool_crashed`：任何没有走到结论的代码路径都不许看起来像通过。

`source_unreadable` 是 `E-3` 补上的第五种"没查成"：`source_path` 给的源码文件
读不出来（文件不存在 / 权限拒绝 / 非 UTF-8）。它与 `decl_mismatch` 的处置相反 ——
`decl_mismatch` 说"我读了这份源码，里面没有你要证的东西"，`source_unreadable`
说"这份源码我根本没读到"。把后者折成前者，等于把"路径写错了"报成
"你证的东西不在文件里"，而后者在机器可读位上表现为 `checked=True`（"查了没通过"）。

## 为什么键的判定顺序是这样（改它之前请先读这一节）

1. `no_backend` / `tool_crashed` / `timeout` / `import_unavailable` /
   `source_unreadable` —— 五种"没查成"，最先判。
   后面所有判据都建立在"检查器真的回了话"之上。
   `import_unavailable` 排在 `compile_error` 之前：`error: unknown package 'X'`
   说明编译根本没开始，它不是"这份证明没通过"。这一档只认检查器自己的诊断行
   （`error:` 标记），源码自己打印的 `unknown package 'X'` 不构成这一档（`E-5`）。
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

from dataclasses import dataclass, field
import hashlib
import os
from functools import lru_cache
import re
import shutil
import sys
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
    "declaration_names",
    "sole_declaration_name",
    "DeclarationNameError",
    "lean_snippets",
    "check_lean",
    "evidence_of",
    "missing_imports_of",
    "concluded_names",
    "PINNED_LEAN_VERSION",
    "PINNED_LEAN_COMMIT",
    "PINNED_MATHLIB_COMMIT",
    "PINNED_MATHLIB_TAG",
    "MATHLIB_REV_STAMP",
    "ENV_MATHLIB_ROOT",
    "IMPORT_PROBE_SOURCE",
    "VERSION_STATUSES",
    "lean_commit_of",
    "find_lean",
    "find_mathlib_root",
    "mathlib_revision",
    "mathlib_imports",
    "ToolchainReport",
    "check_toolchain",
    "format_toolchain_report",
    "toolchain_main",
    "selftest",
]

#: 本模块唯一实现的后端。Coq/Isabelle 的名字出现在探测层里，但本模块不解释它们的输出 ——
#: "看得见二进制"与"解释得了它的输出"是两件事，把后者当前者就是桥接层说谎。
BACKEND_NAME = "lean"

#: `check_lean` 的 `status` 受控词表。只有 `verified` 允许产出 `proof` 级证据。
#: `source_unreadable`（`E-3`）是"没查成"里最容易被折错的那一档：
#: 它既不是"文件里没有那条声明"（`decl_mismatch`），也不是"工具崩了"
#: （`tool_crashed`）—— 它是"调用方给的那个文件我们没读到"。
STATUSES: tuple[str, ...] = (
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

# ------------------------------------------------------------ 版本要求（pin）

#: 钉住的 Lean 版本。这个字符串是要求，不是观测：观测值随机器变，
#: 而"我们按哪个版本判"必须是一个可核的常量。
PINNED_LEAN_VERSION = "4.7.0"
#: 钉住的 Lean 提交。为什么钉 commit 而不是只钉版本号：`4.7.0` 是标签，
#: 而 `lean --version` 里带的是 commit 短哈希 —— 只有它能逐位区分两次构建。
#: 与 `PINNED_LEAN_VERSION` 是两条判据：版本号对了、commit 不对，仍算版本不符。
PINNED_LEAN_COMMIT = "6fce8f7d5cd18a4419bca7fd51780c71c9b1cc5a"
#: 钉住的 Mathlib 提交（tag v4.7.0）。`import Mathlib` 的可用性由它决定。
PINNED_MATHLIB_COMMIT = "a45ae63747140c1b2cbad9d46f518015c047047a"
PINNED_MATHLIB_TAG = "v4.7.0"

#: Mathlib 工程里哪个文件记着"这棵树是哪个 commit"。
#:
#: 顺序即优先级，两条都是可核的机器事实，没有一条靠猜：
#: 1. `.lake/agentflow-mathlib-rev` —— 本仓库自定义的戳（一行 commit）。
#:    为什么需要它：`lake exe cache get` 那条路取回的树没有 `.git`，
#:    而"没有 git 元数据"不等于"不知道版本" —— 装的人应当在装完时写下这一行；
#: 2. `.git/HEAD` —— 正常 clone 的树（可能是 `ref: refs/heads/x`，那就要再读一层）。
MATHLIB_REV_STAMP = ".lake/agentflow-mathlib-rev"
#: Mathlib 工程根从哪读：环境变量第一档（没有它才看设置文件与候选目录，
#: 逐字口径见 `find_mathlib_root`）。
ENV_MATHLIB_ROOT = "AGENTFLOW_MATHLIB_ROOT"

#: 版本检查的受控词表。三态不许折叠成"能用/不能用"：
#: `installed_ok` 与 `version_mismatch` 的处置完全不同（一个继续，一个换版本），
#: 而两者与 `not_installed` 更不同（后者要装）。
VERSION_STATUSES: tuple[str, ...] = ("installed_ok", "version_mismatch", "not_installed")
#: 探测自己没做成（读不到 / 起不来 / 超时）。它不是上面三态里的任何一个。
VERSION_UNKNOWN = "check_failed"

#: `lean --version` 里的 commit 短哈希（12 位；`--githash` 给的是 40 位全长）。
_LEAN_COMMIT_IN_VERSION = re.compile(r"commit\s+([0-9a-fA-F]{7,40})")
_FULL_HASH = re.compile(r"^[0-9a-fA-F]{40}$")
_GIT_HEAD = re.compile(r"^ref:\s*(.+)$")


#: 真的下过结论的那些状态（"查了"）。其余各态都是"没查成"。
#: `import_unavailable` 刻意不在这一组里：库不可得时编译根本没开始，
#: 那次检查没有发生 —— 它不是"查了没通过"。
#: `source_unreadable`（`E-3`）同理、而且更靠前：源码文件根本没读到，
#: 连静态判据都没跑，说它"查了"是一句假话（`evidence_of` 的 `checked` 位
#: 会因此变成 `True`，工具层再折成 `verified=False`）。
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

#: 绑名的公理诊断（事后审计侧读"这条 proof 的依据"时用；`R2-AN-2`）。
#:
#: 与上面的 `_AXIOM_LIST` / `_NO_AXIOMS` 的区别只有一个，但它是全部意义所在：
#: 名字绑不绑得上。上面那两条不绑名，因为 `_axioms_of` 要回答的是
#: "这份输出里出现过哪些公理"（判据是公理列表优先、fail-closed，见它的 docstring），
#: 它刻意不问那句话说的是哪条声明。
#: 而事后审计（`verify` 的 `selfreported_proof`）要回答的是另一个问题：
#: 台账上这条 proof 的依据能不能被读出来 —— "名字被别处提了一句"
#: （例如一句 `warning: unused variable 'foo'`）不构成依据，所以只认
#: `#print axioms <name>` 自己打印的那种绑名形态。
#: 这也是"写入期比审计期宽"的刻意取舍（写入期要保的是真跑过检查器且退出码 0），
#: 详见 `draft/28` §41.2 的登记。
_NAMED_NO_AXIOMS = re.compile(r"'([^']+)'\s+does not depend on any axioms")
_NAMED_AXIOM_LIST = re.compile(r"'([^']+)'\s+depends on axioms:\s*\[[^\]]*\]", re.S)

#: "库不可得"的证据形态。裸 `lean` 解析不了 `import X` 时逐字回的是
#: `error: unknown package 'X'`（实测 Lean 4.7.0；`import Nonexistent.Pkg`
#: 报的是首段 `'Nonexistent'`，所以这里只许把它当线索）。
#:
#: 判据是「检查器自己的诊断行」：`error:` 标记与 `unknown package` 名同时出现。
#: 为什么必须带上 `error:`（`E-5`）：此前只认 `unknown package 'X'` 这半句，
#: 于是被检查的源码自己写一句 `#eval IO.println "unknown package 'Zzz'"`
#: 就能把一次真编译失败（输出里同时有 `error: type mismatch`）改判成
#: `import_unavailable` —— 而"这次没查成（装库）"与"查了没通过（改数学）"
#: 的处置完全相反（实测形态见 draft/28 的 `E-5` A10；本模块的自检里
#: 对应的负控是"源码打印的那句话不许改判"，夹具逐字用它）。
#:
#: 残留（如实登记）：源码若能逐字打印出 `error: unknown package 'X'` 这一整句，
#: 仍可骗过本判据。更强的口径是"输出里没有别的 error: 行"，但那会把
#: 检查器同时报出的两条真诊断（缺库 + 语法错）也折叠掉，而后者有回归用例守着
#: （tests/test_formalgw.py 的 test_a_real_compile_error_is_still_a_compile_error
#: 第 2 条）—— 那一处取舍属人的口径裁定，本函数只做不会误伤正控的收窄。
_MISSING_PACKAGE = re.compile(r"error:\s*unknown package\s+'([^']*)'")

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


# -------------------------------------------------- 版本要求：三态可核（G-13）


def lean_commit_of(version_text: str) -> str:
    """从 `lean --version` 的一行里取 commit 全长哈希；取不到返回空串。

    为什么取全长：实测 `lean --version` 给的是 12 位短哈希，而
    `lean --githash` 给 40 位全长；两者是同一个 commit 的两种写法。
    判据要在全长上做，短哈希只用于填回（见 `_short`），
    否则"12 位前缀相同"与"同一个 commit"会被混为一谈。
    """
    m = _LEAN_COMMIT_IN_VERSION.search(str(version_text or ""))
    return m.group(1).lower() if m else ""


def _same_commit(a: str, b: str) -> bool:
    """两个哈希文本是否指同一个 commit（一个可以是另一个的前缀，且都不为空）。

    为什么允许前缀：两个来源的写法不同（12 位 vs 40 位）。但必须都不为空 ——
    "都取不到哈希"绝不能被当成"一致"，那会把"我们不知道"折叠成"对上了"。
    """
    x, y = str(a or "").strip().lower(), str(b or "").strip().lower()
    if not x or not y:
        return False
    return x == y or x.startswith(y) or y.startswith(x)


def find_lean(*, which: Callable[[str], str | None] | None = None) -> str:
    """找 `lean` 可执行文件；找不到返回空串。

    「查找口径只有一处」（:mod:`agentflow.toolchain`）：显式配置
    （`AGENTFLOW_LEAN_BIN`，文件或目录）→ `AGENTFLOW_PROVER_PATH` → PATH。
    为什么不再自己 `shutil.which` 一次：探测（`tools/verify_tools.detect_verifier`）
    与调用（本函数）此前各看一遍 PATH，于是"探测说没有、调用却能跑"是可能的 ——
    2026-10-03 实测到的形态是：Lean 就装在机器上（仓库临时区里），探测报 `available=[]`，
    形式化那一条腿静默降级成 cross_check。

    `which` 注入那条路保留：离线判据靠它构造"装了但版本不符"这类本机拿不到的状态。
    """
    from . import toolchain as TC

    found = TC.resolve_checker("lean")
    if found["path"]:
        return str(found["path"])
    fn = which if which is not None else shutil.which
    return str(fn("lean") or "")


def _is_mathlib_root(path: Path) -> bool:
    """这个目录算不算"一个 Mathlib 工程根"。

    判据只有一条：同时有 `lakefile.lean` 与 `lean-toolchain`。两处判定
    （`find_mathlib_root` 与 `_check_mathlib_axis`）共用它 —— 各写一份的话，
    "哪个目录算工程"会有两个答案，而它们漂移的症状是"自动找不到、但显式给了又说没装"。
    """
    return (path / "lakefile.lean").is_file() and (path / "lean-toolchain").is_file()


def find_mathlib_root(env: Mapping[str, str] | None = None,
                      *, candidates: Sequence[str | Path] = ()) -> str:
    """找 Mathlib 工程根；找不到返回空串。

    判据见 `_is_mathlib_root`。为什么还要认 `lean-toolchain`：Mathlib 的可用性
    由它写的 Lean 版本决定，而只有 `lakefile.lean` 的目录可能是一个普通的 Lean 包
    —— 把一个不是 Mathlib 的工程报成"Mathlib 装了"，比报"没装"更坏。

    ## 四档（每一档都能被读出来；优先级口径见 `agentflow.settings`）

    优先级逐字：环境变量 > 设置文件 > 内置默认/自动探测。

    1. `AGENTFLOW_MATHLIB_ROOT`（环境变量，最高）；
    2. `LEAN_PATH` 里各段回推到工程根（也是环境变量：`…/mathlib4-<tag>/.lake/build/lib`
       ⇒ 往上四级；调用方自己配过的那一串同样是"显式给我的"）；
    3. 设置文件 `settings.json` 的 `toolchain.mathlib_root`（2026-10-07 起；
       相对路径相对工作区根解析，见 `settings.resolve_setting_path`）；
    4. `candidates`（调用方显式给的那一份）—— 最后那一档自动探测。

    本机路径写在设置文件里，代码与文档里不再写某台机器的绝对路径
    （见 `agentflow/settings.example.json`）。
    """
    src = dict(os.environ if env is None else env)
    roots: list[str | Path] = []
    explicit = str(src.get(ENV_MATHLIB_ROOT) or "").strip()
    if explicit:
        roots.append(explicit)
    # LEAN_PATH 里常出现 `…/mathlib4-<tag>/.lake/build/lib`：把它回推到工程根。
    for chunk in str(src.get("LEAN_PATH") or "").split(os.pathsep):
        p = Path(chunk.strip()) if chunk.strip() else None
        if p is None:
            continue
        for up in (p, p.parent, p.parent.parent, p.parent.parent.parent):
            roots.append(up)
    from . import settings as SET

    setting_root = SET.toolchain_settings(env=env).get("mathlib_root", "")
    if setting_root:
        roots.append(SET.resolve_setting_path(setting_root))
    roots.extend(candidates)
    for r in roots:
        if not str(r).strip():
            continue
        root = Path(str(r))
        if _is_mathlib_root(root):
            return str(root)
    return ""


def mathlib_revision(root: str | Path) -> dict:
    """Mathlib 工程是哪个 commit，以及这个答案是从哪读出来的。

    返回 `{"commit", "tag", "source", "reason"}`：三条来源判据按优先级试。

    为什么 `source` 必须回传：`commit` 为空时有三种完全不同的原因
    （戳文件没写 / 没有 git 元数据 / 读了但读不出哈希），
    把它们折叠成"没有 commit"会让"未核实"看起来像"不匹配"。
    """
    root = Path(str(root))
    tag_file = root / "lean-toolchain"
    tag = ""
    if tag_file.is_file():
        try:
            tag = tag_file.read_text(encoding="utf-8").strip()
        except OSError:
            tag = ""

    stamp = root / MATHLIB_REV_STAMP
    if stamp.is_file():
        try:
            text = stamp.read_text(encoding="utf-8").strip().splitlines()
        except OSError as exc:
            return {"commit": "", "tag": tag, "source": "stamp",
                    "reason": f"戳文件读不了（{type(exc).__name__}: {exc}）"}
        first = text[0].strip() if text else ""
        if _FULL_HASH.match(first):
            return {"commit": first.lower(), "tag": tag, "source": "stamp", "reason": ""}
        return {"commit": "", "tag": tag, "source": "stamp",
                "reason": f"戳文件 {stamp} 第一行不是 40 位 commit（收到 {first[:40]!r}）"}

    head = root / ".git" / "HEAD"
    if head.is_file():
        try:
            first = head.read_text(encoding="utf-8").strip()
        except OSError as exc:
            return {"commit": "", "tag": tag, "source": "git",
                    "reason": f".git/HEAD 读不了（{type(exc).__name__}: {exc}）"}
        if _FULL_HASH.match(first):
            return {"commit": first.lower(), "tag": tag, "source": "git", "reason": ""}
        m = _GIT_HEAD.match(first)
        if m:
            ref = root / ".git" / m.group(1).strip()
            if ref.is_file():
                try:
                    second = ref.read_text(encoding="utf-8").strip()
                except OSError as exc:
                    return {"commit": "", "tag": tag, "source": "git",
                            "reason": f"{ref} 读不了（{type(exc).__name__}: {exc}）"}
                if _FULL_HASH.match(second):
                    return {"commit": second.lower(), "tag": tag, "source": "git", "reason": ""}
            return {"commit": "", "tag": tag, "source": "git",
                    "reason": f".git/HEAD 指向 {m.group(1).strip()}，但读不到它的 40 位 commit"}
        return {"commit": "", "tag": tag, "source": "git",
                "reason": f".git/HEAD 既不是 40 位 commit、也不是 ref 行（收到 {first[:40]!r}）"}

    return {
        "commit": "", "tag": tag, "source": "none",
        "reason": (
            f"这棵树里既没有 {MATHLIB_REV_STAMP} 也没有 .git ⇒ 无法核实它是哪个 commit"
            "（缓存解包出来的树就是这种形态）。这不是'版本不符'，是'未核实'："
            f"请在装完时写一行 commit 到 {MATHLIB_REV_STAMP}"
        ),
    }


def mathlib_imports(root: str | Path, *, timeout_sec: float = 900,
                    lean: str = "") -> dict:
    """真的跑一次 `import Mathlib`，回答"这棵树现在能不能用"。

    为什么必须真跑而不能只看 `.olean` 在不在：oleans 在、但 Lean 版本变了，
    或少了某个包（实测：4100 个 olean 里缺 2 个 blob 时 `Mathlib.olean` 仍在），
    都会让 import 失败而文件树看起来完好。判据只能是"检查器回话"。

    为什么走 `lake env` 而不是自己拼 `LEAN_PATH`：路径拼法随 lake 版本变，
    而 `lake env` 是工程自己声明的那一份（本模块不猜）。返回的 `exit_code` 为
    None 表示没查成（lake 不在 / 超时），它与"import 失败"是两件事。
    """
    base = Path(str(root))
    if not base.is_dir():
        return {"checked": False, "imports": False, "exit_code": None, "command": "",
                "output": "", "reason": f"{base} 不是目录 ⇒ 没做 import 试跑"}
    lk = shutil.which("lake")
    if not lk:
        return {"checked": False, "imports": False, "exit_code": None, "command": "lake",
                "output": "",
                "reason": ("PATH 里没有 lake ⇒ 没查成（不是'Mathlib 不可用'："
                           "没有工具就没法问这个问题）")}
    checkdir = base / "checkdir"
    try:
        checkdir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return {"checked": False, "imports": False, "exit_code": None,
                "command": "lake env lean <tmp>.lean",
                "output": "", "reason": f"建不了 {checkdir}（{type(exc).__name__}: {exc}）"}
    # 探针文件写成临时文件、跑完即删：这次试跑不往工程里留下任何东西。
    # 为什么不用 `lean -`（从 stdin 读）：实测 Lean 4.7.0 把它当文件名，
    # 回的是 `file '-' not found` —— 那会把一次"没查成"伪装成"import 失败"。
    probe = checkdir / "_agentflow_import_probe.lean"
    try:
        with open(probe, "w", encoding="utf-8", newline="") as fh:
            fh.write(IMPORT_PROBE_SOURCE)
    except OSError as exc:
        return {"checked": False, "imports": False, "exit_code": None,
                "command": "lake env lean <checkdir>/_agentflow_import_probe.lean",
                "output": "", "reason": f"写不了探针文件（{type(exc).__name__}: {exc}）"}
    try:
        return _run_import_probe([lk, "env", "lean", str(probe)], cwd=str(base),
                                 timeout_sec=float(timeout_sec))
    finally:
        try:
            probe.unlink()
        except OSError:
            # 可以忽略：删不掉临时探针只影响"工程里多一个文件"，不影响本次结论
            # （结论已经算好了）；为它把一次成功的检查变成异常是更坏的选择。
            pass


#: import 试跑用的探针源码。判据读的是 `Nat.add_comm` 真的被打印出来
#: （不是"退出码 0"）：只 import 不 #check 时，一个空文件也会退出 0。
IMPORT_PROBE_SOURCE = "import Mathlib\n#check Nat.add_comm\n"


def _run_import_probe(cmd: Sequence[str], *, cwd: str, timeout_sec: float) -> dict:
    """起一次 `lake env lean <探针>` 并把它的输出归一。

    单独一个函数是为了让"起进程"这件事只有一处（`mathlib_imports` 只负责
    判据与返回形状）。
    """
    import subprocess

    shown = " ".join(cmd)
    try:
        proc = subprocess.run(list(cmd), cwd=cwd, stdin=subprocess.DEVNULL,
                              capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=timeout_sec)
    except subprocess.TimeoutExpired:
        return {"checked": False, "imports": False, "exit_code": None, "command": shown,
                "output": "", "reason": f"超过 {timeout_sec} 秒没查完 ⇒ 没查成"}
    except OSError as exc:
        return {"checked": False, "imports": False, "exit_code": None, "command": shown,
                "output": "", "reason": f"起不了进程（{type(exc).__name__}: {exc}）"}
    blob = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
    ok_import = proc.returncode == 0 and "Nat.add_comm" in blob
    return {
        "checked": True,
        "imports": bool(ok_import),
        "exit_code": int(proc.returncode),
        "command": shown,
        "output": blob[:800],
        "reason": (
            "`import Mathlib` 真跑通了（工程声明的 lake 环境）"
            if ok_import else
            f"`import Mathlib` 没跑通（退出码 {proc.returncode}）："
            f"{blob.splitlines()[0] if blob else '(没有输出)'}"
        ),
    }


@dataclass
class ToolchainReport:
    """一次版本检查的结论。三条轴各自三态，不折叠。"""

    lean_status: str
    lean_found: str
    lean_version: str
    lean_commit: str
    lean_reason: str
    #: 我们要求的 commit（pin）。判"不符"时，"不符"是与它比出来的。
    lean_expected: str
    mathlib_status: str
    mathlib_root: str
    mathlib_commit: str
    mathlib_source: str
    mathlib_reason: str
    mathlib_expected: str
    #: 只在调用方要求时才跑（默认 None = 本次没问这个问题）。
    import_check: dict | None = None
    #: 探测本身的失败（读不到 / 起不来）。非空时上面几个字段可能是空值。
    errors: list[str] = field(default_factory=list)

    @property
    def status(self) -> str:
        """合起来的一句话结论。只在"两边都 ok"时才说 ok。

        `check_failed` 优先于一切：没查成不许被读成"没装"或"不符"。
        """
        if self.lean_status == VERSION_UNKNOWN or self.mathlib_status == VERSION_UNKNOWN:
            return VERSION_UNKNOWN
        if "not_installed" in (self.lean_status, self.mathlib_status):
            return "not_installed"
        if "version_mismatch" in (self.lean_status, self.mathlib_status):
            return "version_mismatch"
        return "installed_ok"

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "lean": {"status": self.lean_status, "found": self.lean_found,
                     "version": self.lean_version, "commit": self.lean_commit,
                     "expected_commit": self.lean_expected, "reason": self.lean_reason},
            "mathlib": {"status": self.mathlib_status, "root": self.mathlib_root,
                        "commit": self.mathlib_commit, "source": self.mathlib_source,
                        "expected_commit": self.mathlib_expected,
                        "reason": self.mathlib_reason},
            "import_check": self.import_check,
            "errors": list(self.errors),
        }


def _check_lean_axis(which: Callable[[str], str | None] | None,
                     run_fn: RunFn | None) -> tuple[str, str, str, str, str]:
    """Lean 轴的三态 ⇒ `(status, found, version, commit, reason)`。"""
    exe = find_lean(which=which)
    if not exe:
        return ("not_installed", "", "", "",
                f"PATH 里没有 lean ⇒ 没装（要求的版本是 {PINNED_LEAN_VERSION}，"
                f"commit {PINNED_LEAN_COMMIT[:12]}）。装法与验证步骤见 "
                "docs/FORMAL-TOOLCHAIN.md")
    try:
        if run_fn is not None:
            raw = _normalize_run(run_fn([exe, "--version"], cwd=str(Path(exe).parent),
                                        timeout_sec=60))
            text = (raw["stdout"] + "\n" + raw["stderr"]).strip()
            code = raw["exit_code"]
        else:
            import subprocess

            proc = subprocess.run([exe, "--version"], capture_output=True, text=True,
                                  encoding="utf-8", errors="replace", timeout=60)
            text = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
            code = int(proc.returncode)
    except Exception as exc:  # noqa: BLE001 - 探测失败是"没查成"，不是任何三态
        return (VERSION_UNKNOWN, exe, "", "",
                f"`lean --version` 没跑成（{type(exc).__name__}: {exc}）⇒ 没查成，"
                "既不是'没装'也不是'版本不符'")
    first = text.splitlines()[0] if text else ""
    commit = lean_commit_of(text)
    if code != 0 or not first:
        return (VERSION_UNKNOWN, exe, "", commit,
                f"`lean --version` 退出码 {code} 且输出 {first[:80]!r} ⇒ 没查成")
    if PINNED_LEAN_VERSION not in first:
        return ("version_mismatch", exe, first, commit,
                f"装了 Lean，但版本不是 {PINNED_LEAN_VERSION}：{first}")
    if not _same_commit(commit, PINNED_LEAN_COMMIT):
        return ("version_mismatch", exe, first, commit,
                f"Lean 版本号对上了（{PINNED_LEAN_VERSION}），但 commit 不是 "
                f"{PINNED_LEAN_COMMIT[:12]}（读到 {commit[:12] or '取不到'}）⇒ 版本不符")
    return ("installed_ok", exe, first, commit,
            f"Lean {PINNED_LEAN_VERSION}，commit {PINNED_LEAN_COMMIT[:12]} 与要求逐位一致")


def _check_mathlib_axis(root: str | Path | None,
                        env: Mapping[str, str] | None) -> tuple[str, str, str, str, str]:
    """Mathlib 轴的三态 ⇒ `(status, root, commit, source, reason)`。"""
    resolved = str(root or "") or find_mathlib_root(env)
    if resolved and not _is_mathlib_root(Path(resolved)):
        # 显式给了一个不是 Mathlib 工程的目录：这是"没装"，不是"未核实"。
        # 把它当"未核实"会让"路径写错了"看起来像"版本查不出来"。
        return ("not_installed", "", "", "none",
                f"{resolved} 里没有同时出现 lakefile.lean 与 lean-toolchain ⇒ "
                "它不是一个 Mathlib 工程根，按没装处理")
    if not resolved:
        return ("not_installed", "", "", "none",
                f"没有 Mathlib 工程（找不到同时含 lakefile.lean 与 lean-toolchain 的目录，"
                f"也没设 {ENV_MATHLIB_ROOT}）⇒ 没装。装法与验证步骤见 "
                "docs/FORMAL-TOOLCHAIN.md")
    rev = mathlib_revision(resolved)
    commit = str(rev.get("commit") or "")
    if not commit:
        # 这一条是"未核实"，不是"版本不符"：没有 commit 可以比。
        return (VERSION_UNKNOWN, resolved, "", str(rev.get("source") or "none"),
                str(rev.get("reason") or "读不到 Mathlib 的 commit ⇒ 未核实"))
    if not _same_commit(commit, PINNED_MATHLIB_COMMIT):
        return ("version_mismatch", resolved, commit, str(rev.get("source") or ""),
                f"装了 Mathlib，但 commit 不是 {PINNED_MATHLIB_COMMIT[:12]}"
                f"（读到 {commit[:12]}，来源 {rev.get('source')}）⇒ 版本不符")
    return ("installed_ok", resolved, commit, str(rev.get("source") or ""),
            f"Mathlib commit {PINNED_MATHLIB_COMMIT[:12]} 与要求逐位一致"
            f"（来源 {rev.get('source')}；tag 文件写的是 {rev.get('tag') or '无'}）")


def check_toolchain(*, mathlib_root: str | Path | None = None,
                    env: Mapping[str, str] | None = None,
                    which: Callable[[str], str | None] | None = None,
                    run_fn: RunFn | None = None,
                    with_import_check: bool = False,
                    timeout_sec: float = 900) -> ToolchainReport:
    """回答"本机的 Lean/Mathlib 装没装、版本对不对"——三态，且永不折叠。

    ## 三态是什么，为什么不能少一个

    ===================  ==========================================================
    status               含义与处置
    ===================  ==========================================================
    `installed_ok`       装了且版本与 `PINNED_*` 逐位一致 ⇒ 可以用
    `version_mismatch`   装了但版本不符 ⇒ 换版本（不是重装，也不是继续用）
    `not_installed`      没装 ⇒ 装（见 docs/FORMAL-TOOLCHAIN.md）
    `check_failed`       探测自己没做成 ⇒ 我们不知道（不许读成上面任何一个）
    ===================  ==========================================================

    为什么"装了但版本不符"必须与"没装"分开：两者的处置相反 —— 一个是替换，
    一个是安装；折叠成"不能用"之后，读者会去装一个已经存在的工具，
    而版本漂移这个事实（它能解释"昨天还能证、今天证不了"）会永久丢失。

    `with_import_check=True` 时额外真跑一次 `import Mathlib`
    （约 1 分钟量级，且要求 `lake` 在 PATH）：那是"这棵树现在能不能用"。
    刻意默认关：版本判据是机器可读的文件事实，不需要一分钟的子进程；
    而一次默认就要起子进程的检查，会让人为了快而把它整个关掉。

    `which` / `run_fn` 是测试接缝：注入它们可以构造出"装了另一个版本"
    这种本机拿不到的状态（本机只有钉住的那一个版本）。
    """
    errors: list[str] = []
    l_status, l_found, l_ver, l_commit, l_reason = _check_lean_axis(which, run_fn)
    if l_status == VERSION_UNKNOWN:
        errors.append(l_reason)
    m_status, m_root, m_commit, m_source, m_reason = _check_mathlib_axis(mathlib_root, env)
    if m_status == VERSION_UNKNOWN:
        errors.append(m_reason)
    rep = ToolchainReport(
        lean_status=l_status, lean_found=l_found, lean_version=l_ver, lean_commit=l_commit,
        lean_reason=l_reason, lean_expected=PINNED_LEAN_COMMIT,
        mathlib_status=m_status, mathlib_root=m_root, mathlib_commit=m_commit,
        mathlib_source=m_source, mathlib_reason=m_reason,
        mathlib_expected=PINNED_MATHLIB_COMMIT, errors=errors,
    )
    if with_import_check and m_root:
        rep.import_check = mathlib_imports(m_root, timeout_sec=timeout_sec, lean=l_found)
        if not rep.import_check.get("checked"):
            errors.append(str(rep.import_check.get("reason") or "import 试跑没查成"))
    return rep


def format_toolchain_report(rep: ToolchainReport) -> str:
    """给人读的一页结论（脚本与文档引用同一段文本；行首缩进是给终端看的）。"""
    d = rep.to_dict()
    lines = [
        f"[toolchain] status={d['status']}",
        f"  lean     : {rep.lean_status}  {rep.lean_found or '(不在 PATH)'}",
        f"             version={rep.lean_version or '(未知)'}",
        f"             commit ={rep.lean_commit or '(取不到)'}  要求={rep.lean_expected[:12]}",
        f"             {rep.lean_reason}",
        f"  mathlib  : {rep.mathlib_status}  {rep.mathlib_root or '(没有工程)'}",
        f"             commit ={rep.mathlib_commit or '(未核实)'}  要求={rep.mathlib_expected[:12]}",
        f"             {rep.mathlib_reason}",
    ]
    if rep.import_check is not None:
        lines.append(f"  import   : checked={rep.import_check.get('checked')} "
                     f"imports={rep.import_check.get('imports')} "
                     f"exit={rep.import_check.get('exit_code')}")
        lines.append(f"             {rep.import_check.get('reason')}")
    for e in rep.errors:
        lines.append(f"  [没查成] {e}")
    return "\n".join(lines)



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


def declaration_names(source: str) -> list[str]:
    """源码里全部具名声明的名字（按出现顺序去重）。

    为什么要"全部"而不只是第一条（`goal-a5334ee8` 的 ④，真机实测 2026-10-01）：
    调用方只想给一份 `.lean` 文件、不想再报一遍声明名时，唯一的两种诚实做法是
    "文件里恰好只有一条声明 ⇒ 用它"或"不止一条 ⇒ 请调用方点名"。
    此前那两种都不是：工具层拿文件名词干当声明名（`agent_e` 的 `_record_formal`
    与 `verify_tools.check_formal` 各有一处），于是"源码里没有这个名字"被报成
    `decl_mismatch`（`checked=True`，读起来像"查了没通过"），而它其实是
    "调用方写错了参数" —— 两者的处置完全相反（见本模块 docstring 的判定顺序一节）。
    """
    body = _strip_lean_noise(str(source or ""))
    pat = re.compile(
        r"(?m)^[ \t]*(?:@\[[^\]]*\][ \t]*)*"
        r"(?:(?:" + "|".join(_MODIFIERS) + r")[ \t]+)*"
        r"(?:" + "|".join(_NAMED_DECL_KEYWORDS) + r")[ \t]+([^\s:{(]+)"
    )
    return list(dict.fromkeys(m.group(1).strip() for m in pat.finditer(body)))


class DeclarationNameError(ValueError):
    """取不到"唯一那条具名声明" —— 这是调用方参数问题，不是"验证没过"。

    继承 `ValueError`：`check_lean` 的既有契约里"参数不合法"就是 `ValueError`，
    工具层据此折成 `kind="param_error"`（`checked=False`）。刻意不复用
    `decl_mismatch`：那个状态的机器可读位是"查了、没通过"。
    """


def sole_declaration_name(source: str) -> str:
    """源码里恰好一条具名声明的名字；0 条或多条都抛 `DeclarationNameError`。

    多条时把候选名列进消息里（"请显式给名字，并告诉我是哪一个"），
    而不是替调用方挑第一条 —— 挑错了就等于把"声明名核对"这条判据悄悄关掉。
    """
    found = declaration_names(source)
    if len(found) == 1:
        return found[0]
    if not found:
        raise DeclarationNameError(
            "源码里没有具名声明（只有 example 或全被注释）⇒ 取不到声明名。"
            "公理审计（`#print axioms <name>`）与声明名核对都要求这个名字，"
            "猜一个等于把那条判据悄悄关掉。请显式给出声明名（`name` / `checker_name`），"
            "或把要核的命题写成具名声明（`theorem` / `lemma` / `def` …）。"
        )
    raise DeclarationNameError(
        f"源码里有 {len(found)} 条具名声明：{found[:8]}{'…' if len(found) > 8 else ''} —— "
        "取不到「唯一那条」。请显式给出声明名（`name` / `checker_name`）："
        "替调用方挑一条会把「核的是哪个命题」变成一次猜测。"
    )


def declaration_name(source: str) -> str:
    """取出源码里第一条具名声明（`theorem` / `lemma` / `def` ...）的名字。

    为什么需要它：模型给的 Lean 片段是自由文本，而"这条片段声称证了什么"
    必须有一个机器可读的答案 —— 公理审计（`#print axioms <name>`）与
    声明名核对都要求这个名字。`example` 没有名字，返回空串表示"取不到"，
    调用方不得把它当成"证了某个东西"。

    与 `sole_declaration_name` 的分工：这一条回答"第一条是谁"（给 `lean_snippets`
    这类"一段文本里可能有多个片段"的场景用），那一条回答"这一段只有一个候选吗"
    （给 `check_lean` / `_record_formal` 这类"必须点名核哪一条"的场景用）。
    """
    found = declaration_names(source)
    return found[0] if found else ""


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


@lru_cache(maxsize=1)
def _mathlib_lean_path() -> str:
    """解析一次 Mathlib 的 `LEAN_PATH` 段（`draft/37` §103）。

    为什么必须由框架做：`check_lean` 起检查器的命令是裸的 `[lean, <file>]` —— 它靠
    进程环境里的 `LEAN_PATH` 找包。框架已经知道 Mathlib 根在哪（`find_mathlib_root`），
    就不该要求调用方记得把那一串环境变量配好。真机读数（2026-10-04）：盘上有一份
    编译完整的 Mathlib（工程根由设置文件或 `AGENTFLOW_MATHLIB_ROOT` 给出来），
    而 E 的每一次形式化尝试都报 `unknown package 'Mathlib'` —— 直到跑之前
    手工把 `LEAN_PATH` 配上才通。按进程记忆一次（根不会在进程中途换）。
    """
    from . import toolchain as TC

    root = find_mathlib_root()
    return TC.lean_path_for(root) if root else ""


def ensure_lean_path() -> str:
    """把 Mathlib 的段并进进程的 `LEAN_PATH`（只加不改），返回最终那一串。

    只加不改：调用方自己配过的段一律保留（可能是另一份工程），我们只在缺的时候补上。
    没有 Mathlib 根时是空操作 —— 那时"没装 Mathlib"由 `check_formal` 的读数如实说出来。
    """
    segs = _mathlib_lean_path()
    have = [s for s in str(os.environ.get("LEAN_PATH") or "").split(os.pathsep) if s]
    if not segs:
        return os.pathsep.join(have)
    for seg in segs.split(os.pathsep):
        if seg and seg not in have:
            have.append(seg)
    os.environ["LEAN_PATH"] = os.pathsep.join(have)
    return os.environ["LEAN_PATH"]


def _default_run(cmd: Sequence[str], *, cwd: str, timeout_sec: float) -> dict:
    """生产路径：真起检查器进程。

    超时不抛出去，而是返回 `timed_out=True`：调用方（`check_lean`）判的是
    "这次没查完"，而一个抛出去的 `TimeoutExpired` 在别处很容易被兜成"检查失败"——
    那就把"没查成"读成了"证伪了"。半截输出照样带回来（可能已经有编译错误）。

    ## `G-1`：这个进程可被取消

    改前是 `subprocess.run(...)` —— 一个跑 600 秒的 Lean 检查会一直跑完，
    与"有人按了停止"这件事完全无关（取消只到任务入口，到不了正在跑的 handler）。
    现在走 `cancellation.run_cancellable(..., token=current_token())`：
    进程注册到当前 token 上，`CancelToken.cancel()` 会主动杀掉它
    （杀子进程不破坏"不在事务中间强杀"那条纪律 —— 子进程不写我们的表）。

    取消时返回 `cancelled=True`（与 `timed_out` 分开）：两者都落"没查成"，
    但处置不同 —— 超时是加时间，取消是有人喊停、不该重试。
    """
    from .cancellation import current_token, run_cancellable

    return run_cancellable(list(cmd), cwd=cwd, timeout_sec=float(timeout_sec),
                           token=current_token(), stdin_devnull=True)


def _normalize_run(raw: Any) -> dict:
    """把运行函数的返回值归一。垃圾返回值是错误（`check_lean` 会兜成 `tool_crashed`），
    因为"看不懂运行结果"与"检查器说通过"之间隔着整个可信度问题。

    `cancelled`（`G-1`）是新增的第五个键：既有 run_fn（含全部测试替身）
    不给它时默认 `False`，于是"没接取消"与"接了但没取消"在这条契约上分得开。
    """
    if not isinstance(raw, Mapping):
        raise TypeError(f"运行函数必须返回 dict，收到 {type(raw).__name__}")
    code = raw.get("exit_code")
    return {
        "exit_code": None if code is None else int(code),
        "stdout": str(raw.get("stdout") or ""),
        "stderr": str(raw.get("stderr") or ""),
        "timed_out": bool(raw.get("timed_out")),
        "cancelled": bool(raw.get("cancelled")),
        "backend_version": str(raw.get("backend_version") or ""),
    }


def _axioms_of(text: str, *, name: str = "") -> list[str]:
    """从检查器输出里解析公理表。

    ## `E-1`（2026-09-26 全面体检发现）：这里不许做全局短路

    旧实现的第一句是 `if _NO_AXIOMS.search(text): return []`，而 `text` 是检查器
    全部 stdout+stderr。后果（真 Lean 实测，`temp/auditE-lean-probe.json` A8）：
    被检查的源码里只要任何一处带出 `does not depend on any axioms`
    （一句 `#eval IO.println "..."` 就够），整份公理表就被丢弃 ——
    于是一个 `axiom e_ax : P` + `theorem bad : P := e_ax`（假设结论再宣布结论）
    被判成 `status=verified` + `proved=True` + `evidence_kind="proof"`。
    同一条短路也吃掉了 `"sorryAx" in axioms` 那道 sorry 判据（两者读同一个列表）。

    ## 现在的判据（按声明解析 + 公理列表优先，fail-closed）

    1. 先把输出里所有 `depends on axioms: [...]` 的条目收齐（`_AXIOM_LIST`）。
    2. 若给了 `name`，再看有没有指名它不依赖公理的那一行
       （`'<name>' does not depend on any axioms`）⇒ 只有这种情况下才是"显式清白"。
    3. 公理列表优先：只要列表非空就如实返回它（不问别处写没写"不依赖"）——
       因为公理依赖是会传递的，列表非空时我们无法证明被审的那条声明与它无关；
       把它读成"没有公理"是唯一会造成假 proof 的方向。
    4. 两者都没有 ⇒ 返回空列表（"输出里没有公理信息"，与"显式说了不依赖"仍然不同，
       但这一档由 `verified` 的其余前提——退出码 0、无 sorry、声明名真的被检查到——兜住）。

    已知代价（如实登记）：源码里另有一条无关声明带公理时（例如 `#print axioms helper`），
    本条会保守地报 `extra_axioms`。这是刻意的方向选择：宁可拒绝一次真证明，
    也不许把一条假证明读成已证明。
    """
    listed: list[str] = []
    for m in _AXIOM_LIST.finditer(text):
        for piece in m.group(1).split(","):
            piece = piece.strip()
            if piece and piece not in listed:
                listed.append(piece)
    if listed:
        return listed
    if name and re.search(rf"'{re.escape(name)}'\s+does not depend on any axioms", text):
        return []
    return []


def concluded_names(text: str) -> set[str]:
    """从检查器输出里取出被指名下过公理结论的声明名集合（保序无关，去重）。

    ## 为什么它是审计侧唯一的读法（`FC-03`）

    "这条 proof 有检查器依据"在事后只能从 `verifier_output` 里读。读法有两种：

    1. 名字出现在输出里 —— `check_lean` 的写入期判据就是这个
       （`seen = f"'{nm}'" in blob or nm in blob`）。它太宽：名字被一句与结论
       无关的告警提过（`warning: unused variable 'foo'`）也会被读成
       "检查器管过它"（`R2-AN-2` 的 A4 读数）。
    2. 输出里有一条绑了名字的公理诊断（`'<名>' does not depend on any axioms`
       / `'<名>' depends on axioms: [...]`）—— 本函数。

    事后审计用的是 ②：它要保的是"这条 proof 的依据能被读出来"。
    写入期与审计期不同严是刻意的，不是判据漂移（`draft/28` §41.2 有登记）——
    写入期要保的是"真跑过检查器且退出码 0"，那时诊断行必然存在。

    返回名字集合而不是布尔：调用方要做的是"我这条记录声称检查的声明名
    在不在这份输出下的结论里"这一条集合成员判断，而"一个名字都取不到"
    与"取到了别的名字"在处置上完全不同（前者是输出形态不对，后者是贴错了输出）。

    只认 `#print axioms <name>` 的两种输出格式（见 `_NAMED_NO_AXIOMS` /
    `_NAMED_AXIOM_LIST` 的注释），名字里的转义不做反转义：名字由检查器打印，
    我们只做逐字比对 —— 猜一个"还原后"的名字会引入第二种读法。
    """
    out: set[str] = set()
    for rx in (_NAMED_NO_AXIOMS, _NAMED_AXIOM_LIST):
        for m in rx.finditer(str(text or "")):
            nm = m.group(1).strip()
            if nm:
                out.add(nm)
    return out


def missing_imports_of(text: str) -> list[str]:
    """从检查器输出里取出"不可得的包名"（去重、保序）。

    为什么返回列表而不是布尔：`import_unavailable` 要能回答"哪个库不可得"
    —— 只说"库不可得"的返回值与"后端不在"在处置上无法区分，
    而它们的修法一个是装库、一个是装检查器。

    为什么这一条必须与 `compile_error` 分开（本函数的全部意义）：
    包没装时检查器连编译都没开始，它回的是 `unknown package 'X'`，
    而"这次没查成"与"这个命题不成立"是相反的结论。

    判据只认检查器自己的诊断行（`error: unknown package 'X'`，见
    `_MISSING_PACKAGE` 的注释）：被检查源码自己打印的一句话不算证据（`E-5`）。
    """
    out: list[str] = []
    for m in _MISSING_PACKAGE.finditer(str(text or "")):
        name = m.group(1).strip()
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
    - `timeout` / `import_unavailable` / `no_backend` / `tool_crashed` /
      `source_unreadable` ⇒ `checked=False`（没查成）。
      `import_unavailable` 在这里而不是在"跑了但没通过"那一组：
      库没装时编译根本没开始，那次检查没有发生 —— 把它读成"查了没通过"
      等于把一次环境配置问题说成一个数学结论。
      `source_unreadable`（`E-3`）同理：`source_path` 读不到时连"文件里有没有
      那条声明"都没判过，`checked=True` 会把一次路径写错说成"查了、命题不成立"。
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


def check_lean(source: str, *, name: str = "", imports: Sequence[str] = (),
               timeout_sec: float = 600, run_fn: RunFn | None = None,
               workdir: str | Path | None = None,
               source_path: str | Path | None = None) -> dict:
    """把一段 Lean 源码交给检查器真跑一次，并按受控词表给出结论。

    返回至少这些键：`status` / `exit_code` / `stdout` / `stderr` / `elapsed_sec` /
    `backend_version` / `source_sha256` / `axioms` / `sorry_count` / `decl_matches` /
    `missing_imports` / `reason`；另有 `name` / `checked_source` / `path` / `imports` /
    `ran` / `backend` / `evidence` 便于产物把"到底查了什么"写清楚（`checked_source`
    是逐字交给检查器的那份文本，含追加的 `#print axioms`；`path` 在未给 `workdir`
    时是临时路径，调用结束即清理；`ran` 表示检查器真的回了一个可用结论 ——
    静态判据下结论、后端不在、超时、库不可得、源码读不到五种都是 False）。

    判定顺序与理由写在模块 docstring 的这一节里；改动它之前请先读那一节。

    `run_fn` 是唯一的运行接缝：签名为 ``run_fn(cmd, *, cwd, timeout_sec) -> dict``，
    必须返回 ``{"exit_code", "stdout", "stderr", "timed_out"}``（可另带
    `backend_version`）。注入它时不作探测 —— 调用方等于声明"后端由我负责"，
    测试因此完全离线。它抛 `FileNotFoundError` 表示后端二进制不在
    （探测通过之后二进制消失就是这个形态）⇒ `no_backend`；抛别的异常、
    或返回看不懂的东西 ⇒ `tool_crashed`。

    `source_path` 是"源码来自哪个文件"的可选入口，与 `source` 二选一：
    给了它且 `source` 为空时，本函数自己按 UTF-8 读取该文件（读不到时
    `source` 留空，下面的静态判据之前先给出 `source_unreadable`，而不是让调用方
    各自实现一份读文件）。为什么要在这里收这一个入口：`tools/verify_tools.py`
    的 `check_formal` 是转发层，而转发层重复实现"怎么读文件、读不到算哪种失败"
    正是同一判据长出两份实现的典型形态。两个都为空时抛 `ValueError` ——
    "没有源码"与"源码里没有那个声明"是两件必须分开的事，前者是调用方写错了。

    `imports` 默认空（`goal-a5334ee8` 的 ④，真机实测 2026-10-01 改的口径）：
    源码自己写 `import Mathlib` 就加载 Mathlib，没写就什么都不注入 ——
    "源码说什么就是什么"。此前默认注入 `("Mathlib",)`，代价是桥接层替调用方
    改了被检查的那份源码：工作区里那三份纯核心 Lean 源码（`p2_L0_identity` /
    `p2_rho_sum_zero` / `p2_step_norm`）因为首行被塞进 `import Mathlib`，
    在没装 Mathlib 的本机上一律报 `import_unavailable`（= 没查成），
    而 E 把它读成了"这条路走不通"，于是"核验证明"这一整条主路径看起来不成立。
    实测探针（`temp/_m8_probe_lean.py`）：
    默认 ⇒ `missing_imports=['Mathlib']`；`imports=[]` ⇒ `verified=True`，
    检查器原话 `'rho_sum_zero' does not depend on any axioms`。
    要 Mathlib 就显式传 `imports=("Mathlib",)`（或在源码里 import 它）——
    库不可得时仍是 `import_unavailable`（不是 `compile_error`，也不是 `no_backend`），
    那两条区分的理由见下。

    `name` 为空时自动认名（同一次实测的另一半）：源码里恰好一条具名声明就用它；
    0 条或多条 ⇒ 抛 `DeclarationNameError`（`ValueError` 的子类 ⇒ 工具层折成
    `param_error`）。此前是"拿文件名词干当声明名"，于是 `decl_mismatch`
    （`checked=True`，读起来像"查了没通过"）掩盖了真正的问题：调用方没点名。
    """
    src = str(source or "")
    read_failed = ""
    if not src and source_path is not None:
        # 读取失败不在这里抛：调用方（工具层）要的是"没查成"的结构化结论。
        # 但它也不许被折叠成"文件里没有那条声明"—— 那会把"路径写错了"
        # 说成"你证的东西不在文件里"，两者的处置完全不同（前者 `checked=False`，
        # 后者 `checked=True`）。所以失败原因留在这里，由下面的 `source_unreadable`
        # 判据如实报出。
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
    # 只校验"给了名字时它的形状"，不在没给名字时抛错：没给名字是可以的
    # （下面自动认名），而"源码文件根本没读到"那个更准的状态排在自动认名之前
    # （`read_failed` 时自动认名只会说"源码里没有具名声明"，那是把
    # "路径写错了"说成"你要证的命题不在文件里"，两者处置相反 —— 见判定顺序那一节）。
    if nm and not _NAME_RE.match(nm):
        raise ValueError(
            f"name 必须是无空白标识符（收到 {name!r}）—— "
            "名字会被拼进 `#print axioms`，拼不对时检查器报的是语法错，"
            "而那个错误会被读成'证明没过'"
        )
    imports = tuple(imports or ())     # `None` 与 `()` 同义：不注入任何库
    declared = _declared_in_source(src, nm) if nm else False
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
        #: 检查器说"找不到这些包"（空列表 = 没有这种抱怨）。与 `imports` 是两个方向的事实：
        #: `imports` 是我们要它加载什么，这里是它说哪些加载不了。
        "missing_imports": [],
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
            result, "source_unreadable",
            f"读不了 source_path 给的源码文件（{read_failed}）⇒ 本次没有验证结论。"
            "刻意不把它说成'文件里没有那条声明'：路径写错了与命题不在文件里"
            "是两件事，而两者都不是通过。",
        )
    if not nm:
        # 自动认名：恰好一条具名声明 ⇒ 用它；0 条或多条 ⇒ 抛 `DeclarationNameError`
        # （`ValueError` 的子类 ⇒ 工具层折成 `param_error`）。放在 `source_unreadable`
        # 之后：文件没读到时"没有具名声明"那句话是假话，真原因是路径读不了。
        nm = sole_declaration_name(src)
        declared = _declared_in_source(src, nm)
        result["name"] = nm
        result["declared_in_source"] = declared
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
    # `draft/37` §103：起检查器之前把 Mathlib 的 `LEAN_PATH` 补上（只加不改）。
    # 这一步是"框架已经知道的事实不该让调用方记得"的同一条纪律 ——
    # 源码里 `import Mathlib` 能不能编过，取决于这一串在不在，而不是取决于谁记得配它。
    result["lean_path_segments"] = len(
        [s for s in ensure_lean_path().split(os.pathsep) if s])
    t0 = time.monotonic()
    try:
        raw = (run_fn if run_fn is not None else _default_run)(
            [exe, str(path)], cwd=str(path.parent), timeout_sec=float(timeout_sec)
        )
        outcome = _normalize_run(raw)
        # 到这里才是"检查器回了一个可用的结果"。超时与取消都不算：
        # 那两种情况下检查器还没对这份输入给出结论（`G-1` 把取消加了进来）。
        result["ran"] = not outcome["timed_out"] and not outcome["cancelled"]
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
    axioms = _axioms_of(blob, name=name)
    result["axioms"] = axioms

    if outcome["cancelled"]:
        # `G-1`：被取消 ≠ 超时。两者的处置完全相反（后者加时间，前者不该重试），
        # 而 `status` 的十值词表里没有 `cancelled` 这一档 —— 所以用 `tool_crashed`
        # （同样是"没查成"），但理由逐字写清是取消，并带上取消原因。
        from .cancellation import current_reason_text

        why = current_reason_text()
        return _conclude(
            result, "tool_crashed",
            f"检查器进程被**取消**了（{why or '未给出理由'}）⇒ 本次没有查成，"
            "既不是'证明不成立'也不是'超时'：取消是有人喊了停，不该重试；"
            "超时是没跑完，处置是加时间。",
        )
    if outcome["timed_out"]:
        return _conclude(
            result, "timeout",
            f"超过 {timeout_sec} 秒还没查完 ⇒ 没查成（不是'证明不成立'，"
            "也不是'编译错误'：这两件事的处置完全不同）",
        )
    missing_pkgs = missing_imports_of(blob)
    if outcome["exit_code"] != 0 and missing_pkgs:
        # 这一条必须排在 `compile_error` 之前，且必须带"退出码非零"这个前提。
        # 理由：包不可得时 Lean 报 `error: unknown package 'X'`，编译根本没开始。
        # 把它归到 `compile_error`（= "查了没通过"）是一句假话 ——
        # "这个命题不成立"与"这次没查成"的处置完全相反（前者改数学，后者装库）。
        # 要求退出码非零是 fail-closed 的一半：真编译错（少了 `:=` 之类）也非零退出，
        # 但它的输出里不会出现检查器的 `unknown package` 诊断，所以不会被这一条吞掉
        # （负控：`tests/test_formalgw.py` 里"注入语法错仍须 compile_error"那两条）。
        # 另一半是 `missing_imports_of` 只认带 `error:` 的诊断行（`E-5`）：
        # 被检查源码自己打印的同一句话不许把真编译失败改判成本档。
        result["missing_imports"] = missing_pkgs
        return _conclude(
            result, "import_unavailable",
            f"检查器说找不到这些包：{missing_pkgs} ⇒ 这次检查根本没发生"
            "（编译没开始），因此它既不是'证明通过'，也不是'证明没通过'。"
            "处置是装库或换 import 列表，不是改证明。"
            f"原始输出：{(outcome['stderr'] or outcome['stdout']).strip().splitlines()[:1]}",
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

    # 负控④（G-18）：库不可得不许被读成 compile_error，也不许被读成 verified。
    nolib = {"exit_code": 1, "stderr": "probe.lean:1:0: error: unknown package 'Mathlib'\n",
             "stdout": "", "timed_out": False}
    r = check_lean(good, name="one_plus_one", imports=("Mathlib",),
                   run_fn=lambda *a, **k: nolib)
    seen["import_unavailable"] = r["status"]
    if r["status"] != "import_unavailable":
        problems.append(f"负控④：库不可得必须归 import_unavailable：{r['status']}")
    if r.get("missing_imports") != ["Mathlib"]:
        problems.append(f"负控④：库不可得必须带上包名：{r.get('missing_imports')!r}")

    # 负控⑤（G-18 的核心）：真编译错不许被上一条吞成"库不可得"。
    syntax = {"exit_code": 1, "stderr": "probe.lean:1:9: error: unexpected token 'x'\n",
              "stdout": "", "timed_out": False}
    r = check_lean(good, name="one_plus_one", imports=(), run_fn=lambda *a, **k: syntax)
    seen["compile_error"] = r["status"]
    if r["status"] != "compile_error":
        problems.append(f"负控⑤：真编译错必须仍是 compile_error：{r['status']}")

    # 负控⑥（E-5）：被检查源码自己打印的那句话不许把一次真编译失败
    # 改判成"环境缺库"。夹具逐字重现 E-5 的 A10 形态：
    # 源码里 `#eval IO.println "unknown package 'Zzz'"`，而检查器真报的是
    # `error: type mismatch` —— 编译没过的证据在，源码打印的那一句不是证据。
    selfprinted = {
        "exit_code": 1, "stdout": "unknown package 'Zzz'\n",
        "stderr": "probe.lean:3:44: error: type mismatch\n", "timed_out": False,
    }
    r = check_lean(good, name="one_plus_one", imports=(),
                   run_fn=lambda *a, **k: selfprinted)
    seen["self_printed_unknown_package"] = r["status"]
    if r["status"] != "compile_error":
        problems.append(
            "负控⑥：源码自己打印的 unknown package 不许把编译失败改判成"
            f"库不可得：{r['status']}"
        )
    if r.get("missing_imports"):
        problems.append(
            f"负控⑥：这一档不许带上包名（那句话不是检查器的诊断）：{r.get('missing_imports')!r}"
        )

    # 负控⑦（E-3）：源码文件读不到 ⇒ `source_unreadable`（"没查成"），
    # 不许被折成 `decl_mismatch`（"查了、声明对不上"）。两者的机器可读位相反：
    # 前者 `checked=False`、工具层折成 `verified=None`；后者 `checked=True`、
    # 折成 `verified=False`。夹具用一个必然不存在的路径，不依赖任何后端 ——
    # 注入 `run_fn` 是为了跳过后端探测（探测不到后端时先报 `no_backend`，
    # 那一条本身是对的：没有检查器比"源码读不到"更靠前）。
    def _never(*_a: Any, **_k: Any) -> dict:
        raise AssertionError("源码都读不到，检查器一次都不该被起")

    r = check_lean(source="", source_path="definitely-not-here.lean",
                   name="one_plus_one", imports=(), run_fn=_never)
    seen["source_unreadable"] = r["status"]
    if r["status"] != "source_unreadable":
        problems.append(
            f"负控⑦：读不到源码文件必须归 source_unreadable，而不是 {r['status']!r}"
            "（那会把'路径写错了'说成'你证的东西不在文件里'）"
        )
    if r["evidence"].get("checked") is not False:
        problems.append(
            f"负控⑦：源码读不到时 `checked` 必须是 False（今天 {r['evidence'].get('checked')!r}）"
        )

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
    print("[formalgw] 正控与七条负控的离线自检都对")
    return 0


def formal_main(argv: Any = None) -> int:
    """入口：默认自检；`--toolchain` 做版本三态检查，`--import-check` 追加真跑一次 import。

    退出码（三条轴合起来的一句话结论，逐值可判）：

    ===================  ====  ================================================
    退出码                 结论   含义
    ===================  ====  ================================================
    0                     ok     装了且版本与 pin 逐位一致
    1                     自检失败  本模块的判据有一条没红（必须有人看）
    2                     not_installed
    3                     version_mismatch
    4                     check_failed（没查成 —— 不许读成上面任何一个）
    ===================  ====  ================================================

    刻意不叫 `main`（`cli.main` 才是对外的唯一入口）。
    """
    args = list(sys.argv[1:] if argv is None else argv)
    if "--toolchain" in args:
        return toolchain_main(args)
    return selftest()


#: 版本检查结论 ⇒ 退出码。`check_failed` 单独一个值：没查成不许借用别的码。
_TOOLCHAIN_EXIT = {"installed_ok": 0, "not_installed": 2, "version_mismatch": 3,
                   VERSION_UNKNOWN: 4}


def toolchain_main(argv: Sequence[str] | None = None) -> int:
    """`--toolchain [--mathlib-root R] [--import-check]`：跑版本检查并打印结论。"""
    args = list(sys.argv[1:] if argv is None else argv)
    root = None
    for i, a in enumerate(args):
        if a == "--mathlib-root" and i + 1 < len(args):
            root = args[i + 1]
        elif a.startswith("--mathlib-root="):
            root = a.split("=", 1)[1]
    rep = check_toolchain(mathlib_root=root, with_import_check="--import-check" in args)
    print(format_toolchain_report(rep))
    code = _TOOLCHAIN_EXIT.get(rep.status)
    if code is None:
        print(f"  [FAIL] 未登记的结论 {rep.status!r}（必须有人看）")
        return 1
    names = {0: "ok", 2: "没装", 3: "版本不符", 4: "没查成"}
    print(f"  ⇒ {names[code]}（退出码 {code}）")
    return code


if __name__ == "__main__":
    raise SystemExit(formal_main())

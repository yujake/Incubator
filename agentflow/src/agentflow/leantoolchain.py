# -*- coding: utf-8 -*-
"""Lean 工具链的"开机自检"：这台机器上的那个 lean 到底是不是一个真检查器。

## 为什么要有它（业主 2026-10-22 的原话）

「开机自检可以做，防止用户提供虚构的lean环境」。

这句话指的不是"lean 没装"，而是另一种更贵的形态：「环境看起来装好了，但它不说话」。
`toolchain.probe_checkers` 能回答"盘上有没有一个叫 lean 的可执行文件、它报什么版本"，
而这两件事都可以被一个只有五行代码的回显器满足（打印一行 `Lean (version 4.7.0, ...)`，
任何输入都以 0 退出）。于是一整套 `evidence_kind="proof"` 的证据链就建立在
"某个批处理文件说自己叫 Lean"之上，而报告照样打印、判据照样全绿。

自检要回答的是另一个问题：「这个解释器会不会拒绝一个假命题」。所以它不止
"能不能跑"，而是下面这五步：

1. 解析：`--lean` 显式 > 环境变量 > 设置文件 > 工作区 `config.yaml` > PATH 缺省探测，
   并把"是从哪一档找到的"记下来（`source`）。找不到解释器是 `unusable`，不是 `off`。
2. 版本：`lean --version` 要跑通、要能解析出版本号，主版本必须是 4，
   且要与本仓钉住的那一版一致（见 :data:`EXPECTED_LEAN_MAJOR` 与 :func:`expected_version`）。
3. 最小正样例：临时写一个 `theorem dsh_selfcheck : 1 = 1 := rfl`，用真的 lean 检查它，
   退出码 0 才算过。
4. 反控（关键）：同一个临时目录里写一个假命题
   `theorem dsh_selfcheck_bad : 1 = 2 := rfl`，它「必须非 0 退出」。
   若它也"通过"，说明那个 lean 是个回显器而不是检查器 —— 这正是"虚构环境"的
   唯一机械判据，也是本模块存在的全部理由。
5. 图论可用（第 ⑤ 步，2026-10-25 接入）：先按 :func:`mathlib_reading` 找那份
   Mathlib 工程（`lakefile.lean` + `lean-toolchain` + `.lake/build/lib[/lean]/Mathlib.olean`），
   找到了就用它编译一次 `import Mathlib.Combinatorics.SimpleGraph.Basic` 加
   `#check SimpleGraph`：退出码 0「且」输出里真的出现 `SimpleGraph` 才算 `usable`。
   找不到 Mathlib 是 `absent` —— 退回裸 lean（前四步照跑），读数里写明"无 Mathlib"，
   这一档不许把整次自检判成 `unusable`：缺库是"这一项不可用"，不是"检查器坏了"。
   反过来，检测到工程根而这一次编译没过，是 `unusable`，整次自检跟着不许是 `usable`。

## 第 ⑤ 步为什么要有一条自己的"怎么调用"（2026-10-25 的现场）

盘上那份 Mathlib 编译好了（`mathlib-pinned` 那份 `SimpleGraph` 的 38 个模块全有
`.olean`），而裸的 `lean.exe <file>` 不知道它在哪：实测原文是
`error: unknown package 'Mathlib'` 加 `unknown identifier 'SimpleGraph'`，退出码 1
（见 `tests/test_lean_mathlib_wiring.py` 里逐字引的那一段）。也就是说"装了等于没装"。
所以第 ⑤ 步不再用裸命令，而是 :func:`mathlib_command` 给出的那一条：

1. `lake env lean <file>`（cwd = Mathlib 工程根）—— 首选。`lake env` 是工程自己声明的
   那一条环境，路径拼法随 lake 版本变也不归我们猜；
2. 显式 `LEAN_PATH=<工程根>/.lake/build/lib;<各依赖包>` 加解析到的那份 `lean.exe` ——
   次选。只在 `lake.exe` 不在解析到的那个 `lean.exe` 旁边时才用：`lake env` 会把
   PATH 换成工具链里自己的 `lean`，那样自检的就不是同一个二进制了（这一条是本模块
   对"首选 lake"加的唯一限制，理由见 :func:`mathlib_command`）；
3. 检测不到 Mathlib 时退回裸命令（与前四步同一个调用方式），读数里写明"无 Mathlib"。

## 四档状态互不混（三态纪律在这里是四档）

| `state` | 意思 | `checked` |
|---|---|---|
| `off` | 开关关着（`toolchain.lean_enabled=false` 或 `AGENTFLOW_LEAN_ENABLED=0`） | `True` |
| `unknown` | 没查成（开关值读不懂、临时目录写不出、某一步超时、自检自己崩了） | `False` |
| `unusable` | 查了，不可用（找不到、版本不符、正样例不过、反控没失败、Mathlib 那一项没过） | `True` |
| `usable` | 前四步全过，且第 ⑤ 步不是 `unusable`（`absent` 也算过，见下） | `True` |

第 ⑤ 步的结论另有一格 `mathlib`（`state` 取值见 :data:`MATHLIB_STATES`），它「不」并进
上面这张表的措辞里：`mathlib.state == "unusable"` 会让整次自检不是 `usable`
（业主口径：那一项不可用时不许把整次自检判成 usable），而 `absent`（这台机器没有
Mathlib）只是"退回裸 lean"，整次自检照旧可以由前四步给出 `usable`。

两条硬纪律，代码里各有一处落点：

- `checked` 问的是"自检到底跑没跑成"，不是"通过了"；`ok` 只在 `checked` 为真时有意义。
  "没跑自检"永远不许被写成 `usable`（:func:`_empty_result` 的缺省值就是
  `state="unknown"` + `checked=False`）。
- "反控通过"不算自检通过：反控「必须失败」（非 0 退出）才知道对面是个检查器
  （:func:`_negative_control` 的 `failed` 与 `control_ok` 是两个字段，就是不让它被读成一个）。

## 为什么"关着时一次都不许碰 lean"

业主 2026-10-12 的开关口径：`lean_enabled=false` 时全流程涉及 Lean 的都跟着关，
连探测都不做（`formalgw.check_lean` 与 `toolchain._import_mathlib_probe` 已经各有一处
同形的落点）。自检更贵（三步子进程），所以关着时它在「解析之前」就返回：
不 spawn、不建临时目录、不算哈希。判据 `test_the_switch_off_means_off_and_no_process_is_started`
把这三件事逐条钉住（把 `_run` 换成"一被调用就炸"的桩）。

## 落点与读法（接线只有两处，别在本模块之外再造一份）

本模块是「纯函数」：:func:`selfcheck` 不读全局状态（除 `os.environ` 的缺省）、
不写盘（除 `tmp_root` 下那个临时目录，跑完删净）。给生产面的是一个只读读数：

    from . import leantoolchain as LT
    reading = LT.lean_selfcheck_reading(root=root)   # 模块级缓存，同一档只查一次
    state, why = LT.formal_evidence_state(reading)   # "verified" | "unknown"

`formal_evidence_state` 就是"防虚构环境"的落点：「只有 `usable` 才允许把形式化证据
记成 `verified`，其余三档一律 `unknown` 并把原因写在第二格里」。
调用方（`cli.cmd_doctor` 的那一档、`run-agent` / `project run` / `run` 的第一屏摘要、
`cmd_closing` 的那一格）只许从这两口取值。

## 与 `toolchain.py` 的关系（同一个答案，两个问题）

`toolchain.resolve_checker` 回答"盘上有没有它、从哪一档找到的"（探测），
本模块回答"找到的那个会不会拒绝假命题"（自检）。两者的查找梯子必须给出「同一个路径」：
只在 env / settings / PATH 三档上配置时，判据
`test_the_real_lean_on_this_machine_passes_all_four_steps` 会断言
`toolchain.resolve_checker("lean", env)["path"] == selfcheck(...)["lean_path"]`。
本模块多出的两档（`--lean` 与工作区 `config.yaml`）是自检自己的入口，`toolchain` 不认识它们。
"""
from __future__ import annotations

import random

import copy
import hashlib
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import settings as SET

__all__ = [
    "DEFAULT_TIMEOUT_SEC",
    "EXPECTED_LEAN_MAJOR",
    "GRAPH_NAME",
    "MATHLIB_GRAPH_MODULE",
    "MATHLIB_STATES",
    "NEGATIVE_NAME",
    "POSITIVE_NAME",
    "SOURCES",
    "STATES",
    "VERSION_TIMEOUT_SEC",
    "evidence_state_problem",
    "expected_version",
    "formal_evidence_state",
    "lean_selfcheck_reading",
    "mathlib_command",
    "mathlib_reading",
    "reset_reading_cache",
    "selfcheck",
]

#: 四档状态（词表只有这一处定义；`state` 的取值集合由它定）。
STATES: tuple[str, ...] = ("off", "usable", "unusable", "unknown")
#: 解释器是从哪一档解析到的（空串 = 五档都找过、都没找到）。
SOURCES: tuple[str, ...] = ("flag", "env", "settings", "config", "default")

#: 第 ⑤ 步（Mathlib 图论那一项）的四档状态。
#:
#: `usable` 「只能」由一次真编译给出（退出码 0 且输出里有 `SimpleGraph`）：
#: 盘上 `Mathlib/Combinatorics/SimpleGraph/Basic.olean` 在不在只是读数，不是通过
#: （`toolchain.mathlib_state` 的 docstring 记过这个差别：文件面说"可用"、
#: 真编译报 `unknown package 'Std'` 的那次事故）。`absent` 与 `unknown` 由检测给出：
#: 前者是"这台机器没有 Mathlib"（退回裸 lean，不是缺陷），后者是"检测没跑成"。
MATHLIB_STATES: tuple[str, ...] = ("usable", "unusable", "absent", "unknown")

#: 第 ⑤ 步用的那条 import：业主点名的那一个模块（图论入口）。
MATHLIB_GRAPH_MODULE = "Mathlib.Combinatorics.SimpleGraph.Basic"
#: 第 ⑤ 步的源码：一行 import 加一句 `#check`。`#check` 的输出是"这个检查器真的把
#: 这个名字当成了一个东西"的证据，而不只是"它没报错"（回显器给不出这一行）。
GRAPH_SOURCE = f"import {MATHLIB_GRAPH_MODULE}\n\n#check SimpleGraph\n"
#: 第 ⑤ 步那个临时文件的名字（与正/反样例同一族前缀：万一留在盘上一眼认得出）。
GRAPH_NAME = "dsh_mathlib_graph"
#: `#check SimpleGraph` 成功时输出里必然出现的那个标识符。退出码 0 但输出里没有它
#: （例如一个"任何输入都退 0"的东西）不算可用 —— 这一条与"反控必须失败"同向：
#: 通过必须能被看见，不能只靠"它没说话"。
GRAPH_MARKER = "SimpleGraph"

#: Mathlib 缺省候选目录名（在 `<工作区根>/_env/` 下面找；顺序即优先级）。
#:
#: 为什么有这一档：2026-10-25 的现场是"Mathlib 编译好了（`SimpleGraph` 的 38 个模块
#: 全有 `.olean`），而设置文件没写 `toolchain.mathlib_root`" —— 于是裸 lean 永远报
#: `unknown package 'Mathlib'`，盘上那份库等于没装。候选只探 `_env/` 这一层（外加每格
#: 的一层子目录，Mathlib 的发行目录形如 `mathlib4-<tag>`），不递归搜整盘：
#: "自动在别处找到了一个 Mathlib"比"没找到"更难排查。
MATHLIB_DEFAULT_DIRS: tuple[str, ...] = ("mathlib-pinned", "mathlib-pinned2", "mathlib4")
#: Mathlib 的 `.olean` 两种布局（4.7.0 是前者、4.9+ 是后者；口径与
#: `toolchain.lean_path_for` 逐字一致 —— 两处各写一份的话，"哪个目录算库"会有两个答案）。
_MATHLIB_LIB_SUBS: tuple[Path, ...] = (Path(".lake") / "build" / "lib",
                                       Path(".lake") / "build" / "lib" / "lean")


#: 期望的主版本号。本仓只认 Lean 4 家族：3.x 与 5.x 都意味着"另一个工具"，
#: 而 `evidence_kind="proof"` 这套口径是照着 Lean 4 的 `rfl`/`omega` 那些写法定的。
EXPECTED_LEAN_MAJOR = 4

#: 单步超时（秒）。三步子进程共用这一档：正样例与反控都在一个只有一行 `theorem`
#: 的文件上跑，本机实测 0.4–0.9 秒（2026-10-22，Lean 4.7.0）；给 60 秒是留给
#: 冷启动、杀毒扫描与慢盘的余量，而不是留给"它慢慢想"。
DEFAULT_TIMEOUT_SEC = 60.0
#: `--version` 单独一档（它比编译一个文件便宜得多，卡住就说明这个 exe 有问题）。
VERSION_TIMEOUT_SEC = 20.0

#: 正样例的声明名（进临时文件、也进读数的 `name` 字段；名字里带 dsh 前缀是为了
#: 万一有人把临时文件留在盘上时，一眼能看出它是本次自检造的）。
POSITIVE_NAME = "dsh_selfcheck"
#: 反控的声明名（与被检的那条真命题同一个文件族，只是命题是假的）。
NEGATIVE_NAME = "dsh_selfcheck_bad"
#: 正样例源码（「必须」是一个真命题：`1 = 1` 在 Lean 4 里 `rfl` 就能证）。
# 反控的命题每趟随机（业主 2026-10-22 口径：防虚构 lean 环境）：常量化的 `1 = 2` 会被
# 一个"源码里含 1=2 就 exit 1"的假 lean 认出来。这里随机两个不同的自然数 n != m，
# 正样例用 n = n，反控用 n = m ⇒ 假 lean 没法靠字面量或文件名蒙混。
_N = random.randint(2, 9999)
_M = _N + random.randint(1, 9999)
POSITIVE_SOURCE = f"theorem {POSITIVE_NAME} : {_N} = {_N} := rfl\n"
NEGATIVE_SOURCE = f"theorem {NEGATIVE_NAME} : {_N} = {_M} := rfl\n"
#: 反控源码（「必须」是假的：`1 = 2` 在 Lean 4 里 `rfl` 一定过不了；
#: 任何说它过了的东西都不是检查器）。


#: 版本行里那个版本号（`Lean (version 4.7.0, x86_64-w64-windows-gnu, commit ...)`）。
_VERSION_RE = re.compile(r"version\s+(\d+\.\d+\.\d+)", re.IGNORECASE)
#: 兜底：版本行里第一个像版本号的三段数字（有些发行版把 `version` 写成别的词）。
_VERSION_FALLBACK_RE = re.compile(r"\b(\d+\.\d+\.\d+)\b")
#: 输出里留多少字符进读数（够看出"它是报错了还是在回显"，又不至于把整份日志塞进摘要）。
_OUTPUT_HEAD_CHARS = 400

#: 卫生类问题的前缀：这类条目「不影响」 `state`（它说的是这次自检自己留下的垃圾，
#: 不是这个 lean 有毛病）。没有这一条区分，"临时目录没删净"会被读成"lean 不可用"。
HYGIENE_PREFIX = "[卫生]"


# ============================================================ 小工具


def _now() -> float:
    """单调时钟（只为算 `elapsed_ms`；不参与任何判据）。"""
    return time.monotonic()


def _head(text: str, limit: int = _OUTPUT_HEAD_CHARS) -> str:
    """输出开头那一段（换行压成单行：读数要能塞进一行摘要）。"""
    flat = " ".join(str(text or "").split())
    return flat[:limit]


def _ms(since: float) -> float:
    """从某个单调时钟读数到现在的毫秒数（保留 1 位小数）。"""
    return round((_now() - since) * 1000.0, 1)


def expected_version() -> str:
    """本仓钉住的那一版 Lean（唯一来源是 `formalgw.PINNED_LEAN_VERSION`）。

    刻意不在这里抄第二份常量：那个版本号已经是"钉住"这件事的唯一落点
    （`formalgw` 的模块 docstring 与 `docs/FORMAL-TOOLCHAIN.md` 都指着它）。
    读不到（`formalgw` 导不进来）⇒ 空串，此时 :func:`_version_verdict` 只判主版本，
    并在 `problems` 里说清"完整版本这一档没查"（三态：没查 != 通过）。
    """
    try:
        from . import formalgw as FG
    except Exception as exc:  # noqa: BLE001 - 读不到钉住的版本不该让自检崩掉
        return ""
    return str(getattr(FG, "PINNED_LEAN_VERSION", "") or "")


def _empty_mathlib() -> dict[str, Any]:
    """第 ⑤ 步那一格的缺省形状（`state="unknown"` + `checked=False`）。

    为什么连它也要有一份缺省：`lean_selfcheck_reading()` 的每一格都恒在
    （调用方按形状读，不做 `if "mathlib" in sc`），而"没查"与"查了没有"必须分得开 ——
    缺省的 `reason` 逐字写着"这一步没跑"，不留给读者去猜。
    """
    return {
        "checked": False,
        "detected": False,
        "state": "unknown",
        "root": "",
        "source": "",
        "version": "",
        "expected_version": "",
        "lakefile": "",
        "toolchain_file": "",
        "umbrella_olean": "",
        "graph_olean": "",
        "lake_exe": "",
        "lean_path": "",
        "lean_path_segments": 0,
        "runner": "",
        "argv": [],
        "cwd": "",
        "exit_code": None,
        "output_head": "",
        "evidence": "",
        "elapsed_ms": 0.0,
        "problems": [],
        "reason": "这一步没跑（自检没走到第 ⑤ 步）",
    }


def _empty_result() -> dict[str, Any]:
    """一份"什么都没查成"的读数（缺省值必须是 `unknown` + `checked=False`）。

    这是本模块最重要的一行纪律的落点：任何提前返回的路径都从这份形状出发，
    于是"没跑自检"在读数上「不可能」长得像 `usable`。
    """
    return {
        "checked": False,
        "ok": False,
        "state": "unknown",
        "source": "",
        "lean_path": "",
        "version": "",
        "version_ok": False,
        "sha256": "",
        "positive": {"name": POSITIVE_NAME, "exit_code": None, "output_head": "",
                     "elapsed_ms": 0.0, "passed": False, "problem": "",
                     "kind": "not_attempted"},
        "negative": {"name": NEGATIVE_NAME, "exit_code": None, "output_head": "",
                     "elapsed_ms": 0.0, "failed": False, "control_ok": False,
                     "problem": "", "kind": "not_attempted"},
        # 第 ⑤ 步那一格（Mathlib 图论）。它「不进」上面的 `problems`：缺库是这一项
        # 不可用，不是检查器坏了，把它混进 `problems` 会让 `formal_evidence_state`
        # 把一次"没装库"报成"检查器不可用"（两种处置相反：装库 vs 修工具链）。
        "mathlib": _empty_mathlib(),
        "problems": [],
        "note": "",
        "enabled": False,
        "enabled_source": "default",
        "expected_version": "",
        "elapsed_ms": 0.0,
    }


def _sha256_of(path: str) -> tuple[str, str]:
    """解释器文件的 sha256。返回 `(哈希, 问题)`；读不出来时哈希是空串。

    为什么连解释器都要哈希：读数里有了它，"这一次自检的是哪个二进制"才是可对账的
    （批准台账、事故复盘、以及"两次读数为什么不一样"都靠它）。算不出就是空串 + 一条问题，
    不伪造一个 64 个 0。
    """
    try:
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                h.update(chunk)
    except OSError as exc:
        return "", f"算不出解释器的 sha256（{type(exc).__name__}: {exc}）"
    return h.hexdigest(), ""


# ============================================================ ① 解析


def _locate(raw: str, name: str) -> tuple[str, str]:
    """一档"文件或目录"的取值 → `(绝对路径, 问题)`。

    - 指到文件：原样用（是不是真的能跑由第 ② 步判，不在这里猜）；
    - 指到目录：在里面找 `name`（与 `toolchain._probe_one_path` 同一口径 ——
      "指向安装目录"是人最自然的写法）；
    - 指到一个不存在的东西：空路径 + 一条点名这一档的问题（fail-closed：
      配了却找不到是配置问题，不许读成"这台机器没有"）。
    """
    p = SET.resolve_setting_path(raw)
    if p.is_file():
        return str(p.resolve()), ""
    if p.is_dir():
        found = shutil.which(name, path=str(p))
        if found:
            return str(Path(found).resolve()), ""
        return "", f"{raw} 是个目录，但里面没有 {name}（解析成 {p}）"
    return "", f"{raw} 不存在（解析成 {p}）"


def _config_lean_path(root: str | Path | None) -> tuple[str, str]:
    """工作区 `config.yaml` 的 `lean_path`（第 ④ 档）。返回 `(值, 问题)`。

    读法只走 `cli.load_config`（配置的唯一读入口），并且是惰性 import：本模块被
    `cli` 调用，模块级 `from . import cli` 会成环。没给 `root` ⇒ 这一档不适用
    （返回空串，不是"配了空值"）。
    """
    if root is None:
        return "", ""
    from . import cli as CLI

    try:
        cfg = CLI.load_config(Path(root))
    except SystemExit as exc:
        return "", f"工作区 config.yaml 读不出来（{exc}）"
    if not isinstance(cfg, Mapping):
        return "", f"工作区 config.yaml 不是一个映射（收到 {type(cfg).__name__}）"
    raw = cfg.get("lean_path")
    if raw is None:
        return "", ""
    if not isinstance(raw, str):
        return "", (f"config.yaml 的 lean_path 必须是字符串（收到 {type(raw).__name__}）"
                    "—— 非字符串一律当配置问题，不静默当没配")
    return raw.strip(), ""


def _resolve(src: Mapping[str, str], *, root: str | Path | None,
             lean: str | None,
             env: Mapping[str, str] | None = None) -> tuple[str, str, list[str]]:
    """解析解释器：返回 `(绝对路径, source, 逐档的问题)`。

    梯子（唯一口径，理由见模块 docstring）：`--lean` 显式 > 环境变量
    `AGENTFLOW_LEAN_BIN` > 设置文件 `toolchain.lean_bin` > 工作区 `config.yaml`
    的 `lean_path` > PATH 缺省探测。

    为什么 `config.yaml` 排在设置文件之后：设置文件是"这台机器上的显式配置"，
    而 `config.yaml` 随工作区走（为了"这条链在别的机器上也复现得出来"）。
    两者都是人写的显式档，冲突时让「机器级」那一档赢 —— 否则复制一份旧工作区
    就会静默盖掉这台机器上正确的落点。`--lean` 与 env 仍然压在所有文件档之上
    （CI 与既有脚本靠它们，见 `settings` 模块的优先级那一段）。

    `src` 与 `env` 是两个不同的东西（2026-10-25 修）：`src` 是"当成环境变量表用的
    那一份"（`selfcheck(env=None)` 时它就是 `os.environ` 的拷贝），而 `env` 是调用方
    「注入了没有」这件事本身。`settings.toolchain_settings` 判的是后者：`env is None`
    才落磁盘读 `settings.json`。此前这里把 `src` 传给了它，于是"注入了一份等于
    os.environ 的映射"被读成"调用方注入了环境"⇒ 设置文件那一档再也读不到 ——
    本机实测形态：`settings.json` 里明明写着 `toolchain.lean_bin`，自检却报
    "五档都找过、都没找到 lean"。口径与 `toolchain.resolve_checker` 逐字一致
    （它传的就是原始 `env`）。
    """
    problems: list[str] = []
    raw = str(lean or "").strip()
    if raw:
        found, why = _locate(raw, "lean")
        if found:
            return found, "flag", problems
        problems.append(f"--lean={why}")
    raw = str(src.get("AGENTFLOW_LEAN_BIN") or "").strip()
    if raw:
        found, why = _locate(raw, "lean")
        if found:
            return found, "env", problems
        problems.append(f"环境变量 AGENTFLOW_LEAN_BIN：{why}")
    setting_raw = str(SET.toolchain_settings(env=env).get("lean_bin") or "").strip()
    if setting_raw:
        found, why = _locate(setting_raw, "lean")
        if found:
            return found, "settings", problems
        problems.append(f"设置文件 {SET.DEFAULT_SETTINGS_REL} 的 toolchain.lean_bin：{why}")
    config_raw, config_why = _config_lean_path(root)
    if config_why:
        problems.append(f"config.yaml 的 lean_path：{config_why}")
    if config_raw:
        # 工作区配置里的相对路径相对「工作区根」解析（它的兄弟键都是这个口径），
        # 不相对本包所在的仓库根（`settings.resolve_setting_path` 的那一档是机器级配置的规则）。
        candidate = Path(config_raw)
        if not candidate.is_absolute():
            candidate = Path(str(root)) / config_raw
        found, why = _locate(str(candidate), "lean")
        if found:
            return found, "config", problems
        problems.append(f"config.yaml 的 lean_path：{why}")
    path_var = str(src.get("PATH") or "")
    found = shutil.which("lean", path=path_var) if path_var else None
    if found:
        return str(Path(found).resolve()), "default", problems
    problems.append(
        "五档都找过、都没找到 lean：--lean、环境变量 AGENTFLOW_LEAN_BIN、设置文件的 "
        f"toolchain.lean_bin、config.yaml 的 lean_path、PATH（PATH={'（空）' if not path_var else '已给'}）"
        "—— 处置：把 AGENTFLOW_LEAN_BIN 指向 lean.exe（或它所在的目录），"
        "或写进 settings.json 的 toolchain.lean_bin"
    )
    return "", "", problems


# ============================================================ 唯一 spawn 点


def _run(cmd: Sequence[str], *, cwd: str, timeout_sec: float,
         env_overlay: Mapping[str, str] | None = None) -> dict[str, Any]:
    """跑一次子进程。全模块「只有这一处」 spawn —— 判据因此只需要打一个桩。

    返回 `{started, exit_code, timed_out, output_head, elapsed_ms, error}`：

    - `started=False` ⇒ 进程都没起来（exe 不是合法的可执行文件、权限不足……）。
      这一档是"这个候选不是能用的 lean"，不是"我们没查成"；
    - `timed_out=True` ⇒ 到点还没回话，退出码是 `None`（那一刻它还没回话，
      记 0 或记 1 都是编的）。

    `env_overlay` 只给第 ⑤ 步用（次选那条路要显式给 `LEAN_PATH`）：它是「在进程环境
    之上加几格」，不是"把环境换成这几格" —— 只加不改，与
    `formalgw.ensure_lean_path` 同一条纪律（检查器还要找 `PATH` 上的别的工具）。
    缺省 `None` ⇒ 完全继承进程环境，前四步的行为一个字都不变。
    """
    started = _now()
    child_env: dict[str, str] | None = None
    if env_overlay:
        child_env = dict(os.environ)
        child_env.update({str(k): str(v) for k, v in env_overlay.items() if str(k)})
    try:
        proc = subprocess.run(
            [str(c) for c in cmd], cwd=cwd, capture_output=True, env=child_env,
            text=True, encoding="utf-8", errors="replace", timeout=timeout_sec,
        )
    except subprocess.TimeoutExpired:
        return {"started": True, "exit_code": None, "timed_out": True,
                "output_head": "", "elapsed_ms": _ms(started), "error": ""}
    except OSError as exc:
        return {"started": False, "exit_code": None, "timed_out": False,
                "output_head": "", "elapsed_ms": _ms(started),
                "error": f"{type(exc).__name__}: {exc}"}
    out = (proc.stdout or "")
    err = (proc.stderr or "")
    text = out if not err.strip() else (out + "\n" + err)
    return {"started": True, "exit_code": int(proc.returncode), "timed_out": False,
            "output_head": _head(text), "elapsed_ms": _ms(started), "error": ""}


# ============================================================ ② 版本


def _parse_version(text: str) -> tuple[str, str]:
    """从版本行里解析出 `x.y.z`。返回 `(版本, 问题)`；解析不出时版本是空串。"""
    body = str(text or "")
    for pat in (_VERSION_RE, _VERSION_FALLBACK_RE):
        m = pat.search(body)
        if m:
            return m.group(1), ""
    return "", (f"`--version` 的输出里解析不出版本号（开头：{_head(body) or '（什么都没有）'}）")


def _version_verdict(version: str, expected: str) -> tuple[bool, list[str]]:
    """版本是否满足期望。返回 `(是否满足, 逐条问题)`。

    两条判据都必须成立：主版本是 4；且（钉住的版本读得到时）完整版本与它一致。
    钉住的版本读不到时「不静默放过」：把"完整版本这一档没查"写进问题里，
    但此时 `version_ok` 仍可由主版本单独成立 —— 那一档是"没查"，不是"不符"。
    """
    problems: list[str] = []
    if not version:
        return False, ["版本号没解析出来 ⇒ 无法判断这是不是 Lean 4"]
    try:
        major = int(version.split(".")[0])
    except (ValueError, IndexError):
        return False, [f"版本号 {version!r} 读不出主版本 ⇒ 无法判断这是不是 Lean 4"]
    if major != EXPECTED_LEAN_MAJOR:
        problems.append(f"版本 {version} 的主版本是 {major}，本仓只认 {EXPECTED_LEAN_MAJOR}.x"
                        "（proof 级证据的口径是照着 Lean 4 定的）")
    if not expected:
        problems.append("本仓钉住的完整版本读不到（formalgw.PINNED_LEAN_VERSION 空）"
                        "⇒ 完整版本这一档没查，只判了主版本")
    elif version != expected:
        problems.append(f"版本 {version} 与本仓钉住的 {expected} 不一致"
                        "（换版本会让既有证明的编译结果漂移，所以这一档按不通过处理）")
    return (not problems), problems


# ============================================================ ③④ 正样例与反控


def _write_probe(workdir: Path, filename: str, source: str) -> tuple[str, str]:
    """把一段 `.lean` 源码写进临时目录。返回 `(路径, 问题)`。

    用 `write_bytes` 而不是 `write_text`：行尾必须逐字节是 `\\n`
    （Windows 上 `write_text` 会把 `\\n` 刷成 `\\r\\n`，那会让"这份源码的 sha256"
    变成一个与内容无关的数）。
    """
    path = workdir / filename
    try:
        path.write_bytes(source.encode("utf-8"))
    except OSError as exc:
        return "", f"写不出临时文件 {path}（{type(exc).__name__}: {exc}）"
    return str(path), ""


def _positive_control(exe: str, workdir: Path, *, timeout_sec: float) -> dict[str, Any]:
    """第 ③ 步：真命题必须通过（退出码 0）。

    它是"这个 lean 至少会工作"的下界 —— 只有正样例过了，反控的"没失败"
    才有意义（一个连 `1 = 1` 都编不过的东西，不拒绝假命题也不说明它是假货，
    只说明它坏了）。
    """
    row: dict[str, Any] = {"name": POSITIVE_NAME, "exit_code": None, "output_head": "",
                           "elapsed_ms": 0.0, "passed": False, "problem": "",
                           "kind": "not_attempted"}
    src_path, why = _write_probe(workdir, f"{POSITIVE_NAME}.lean", POSITIVE_SOURCE)
    if why:
        row["problem"] = why
        row["kind"] = "not_checked"
        return row
    got = _run([exe, src_path], cwd=str(workdir), timeout_sec=timeout_sec)
    row["exit_code"] = got["exit_code"]
    row["output_head"] = got["output_head"]
    row["elapsed_ms"] = got["elapsed_ms"]
    if got["timed_out"]:
        row["problem"] = (f"正样例在 {timeout_sec:g} 秒内没回话 ⇒ 没查成"
                          "（这不是『通过』，也不是『不可用』）")
        row["kind"] = "not_checked"
        return row
    if not got["started"]:
        row["problem"] = f"正样例起不了这个解释器：{got['error']}"
        row["kind"] = "unusable"
        return row
    if got["exit_code"] != 0:
        row["problem"] = (f"正样例 `{POSITIVE_NAME} : 1 = 1 := rfl` 没过"
                          f"（退出码 {got['exit_code']}；输出开头：{_head(got['output_head']) or '（空）'}）")
        row["kind"] = "unusable"
        return row
    row["passed"] = True
    row["kind"] = "passed"
    return row


def _negative_control(exe: str, workdir: Path, *, timeout_sec: float) -> dict[str, Any]:
    """第 ④ 步（关键）：假命题必须「失败」（非 0 退出）。

    `failed` 记的是"这一次真的失败了没有"，`control_ok` 记的是"这条反控成立没有"——
    它们在这里是同一个事实的两种说法，刻意保留两格：读的人一旦把"反控通过"（假命题
    被接受）读成"自检通过"，这一整套东西就白做了，所以宁可让字段名把话说死。
    """
    row: dict[str, Any] = {"name": NEGATIVE_NAME, "exit_code": None, "output_head": "",
                           "elapsed_ms": 0.0, "failed": False, "control_ok": False,
                           "problem": "", "kind": "not_attempted"}
    src_path, why = _write_probe(workdir, f"{NEGATIVE_NAME}.lean", NEGATIVE_SOURCE)
    if why:
        row["problem"] = why
        row["kind"] = "not_checked"
        return row
    got = _run([exe, src_path], cwd=str(workdir), timeout_sec=timeout_sec)
    row["exit_code"] = got["exit_code"]
    row["output_head"] = got["output_head"]
    row["elapsed_ms"] = got["elapsed_ms"]
    if got["timed_out"]:
        row["problem"] = (f"反控在 {timeout_sec:g} 秒内没回话 ⇒ 没查成"
                          "（『它没有拒绝』与『它拒绝了』必须分得开，所以这里不判不可用）")
        row["kind"] = "not_checked"
        return row
    if not got["started"]:
        row["problem"] = f"反控起不了这个解释器：{got['error']}"
        row["kind"] = "unusable"
        return row
    if got["exit_code"] == 0:
        row["problem"] = ("反控没失败：这个 lean 会接受假命题"
                          f"（`{NEGATIVE_NAME} : 1 = 2 := rfl` 以 0 退出）⇒ "
                          "它是个回显器/假货，不是检查器 —— 它产出的任何 proof 级证据都不算数")
        row["kind"] = "unusable"
        return row
    row["failed"] = True
    row["control_ok"] = True
    row["kind"] = "control_ok"
    return row


# ============================================================ ⑤ Mathlib（图论那一项）


def _mathlib_default_candidates(root: str | Path | None) -> list[str]:
    """缺省候选目录（`:data:`MATHLIB_DEFAULT_DIRS` 那一档）。返回去重后的绝对路径串。

    两个基点都试：`root` 本身与它上一级。理由是现场有两种叫法 —— `cmd_doctor` 传进来的
    `DEFAULT_ROOT` 是工程根（`.../agentflow`），而设置文件里那些相对路径是相对
    「工作区根」（工程根的上一级）解析的；`_env/` 落在后者的下面。不传 `root` 时用
    `settings.WORKSPACE_ROOT`（与 `resolve_setting_path` 同一个基点，不再造第二个）。

    每一格再往下探一层：Mathlib 的发行目录形如 `mathlib4-<tag>`，直接指到 `_env/`
    一个子目录是人不写全时的常态（与 `toolchain._probe_one_path` 认"安装目录"同一条口径）。
    """
    bases: list[Path] = []
    if root is not None and str(root).strip():
        base = Path(str(root))
        bases.extend([base, base.parent])
    else:
        bases.append(Path(str(SET.WORKSPACE_ROOT)))
    out: list[str] = []
    seen: set[str] = set()
    for base in bases:
        env_dir = base / "_env"
        for name in MATHLIB_DEFAULT_DIRS:
            cand = env_dir / name
            paths = [cand]
            try:
                if cand.is_dir():
                    paths.extend(sorted(p for p in cand.iterdir() if p.is_dir()))
            except OSError:
                # 列不出子目录就读不到"更深一层"的候选：这一档因此少一个候选而已，
                # 其余四档（env / LEAN_PATH / settings / 显式）照旧能给出工程根。
                # 读不了目录这件事在这里不是缺陷（候选表本来就是"有就多一条"）。
                pass
            for path in paths:
                key = os.path.normcase(str(path))
                if key in seen:
                    continue
                seen.add(key)
                out.append(str(path))
    return out


def _mathlib_source_label(found: str, *, explicit: str, default_candidates: Sequence[str],
                          env: Mapping[str, str] | None) -> str:
    """`found` 这个工程根是从哪一档读出来的（空串 = 没找到）。

    为什么不问 `formalgw.find_mathlib_root` 要这一格：它只回一个路径（那是刻意的 ——
    "哪个目录算工程"只许有一个判据）。"从哪一档来的"是读数，不是判据，所以在拿到
    权威答案之后按同一套优先级回头认一次即可；认不出来时如实写 `unknown`，
    不编一个"大概是这样"。

    `env` 的 `None` 与映射是两种口径（与 `settings.toolchain_settings` 逐字一致）：
    `None` 才落磁盘读 `settings.json`，注入映射时只认它里面给的 `AGENTFLOW_SETTINGS`。
    """
    if not found:
        return ""
    src = dict(os.environ if env is None else env)

    def _same(a: str, b: str) -> bool:
        return bool(a) and bool(b) and os.path.normcase(str(a)) == os.path.normcase(str(b))

    target = str(found)
    if explicit and _same(str(SET.resolve_setting_path(explicit)), target):
        return "flag"
    if _same(str(src.get("AGENTFLOW_MATHLIB_ROOT") or "").strip(), target):
        return "env"
    for chunk in str(src.get("LEAN_PATH") or "").split(os.pathsep):
        seg = chunk.strip()
        if not seg:
            continue
        p = Path(seg)
        for up in (p, p.parent, p.parent.parent, p.parent.parent.parent):
            if _same(str(up), target):
                return "lean_path"
    setting_raw = str(SET.toolchain_settings(env=env).get("mathlib_root") or "").strip()
    if setting_raw and _same(str(SET.resolve_setting_path(setting_raw)), target):
        return "settings"
    for cand in default_candidates:
        if _same(cand, target):
            return "default"
    return "unknown"


def _first_existing(root: Path, rel: str) -> str:
    """`root` 下两种 `.olean` 布局里先存在的那个（都不在 ⇒ 空串）。"""
    for sub in _MATHLIB_LIB_SUBS:
        path = root / sub / rel
        if path.is_file():
            return str(path)
    return ""


def _lake_beside(lean_exe: str) -> str:
    """与解析到的那个 `lean.exe` 同目录的 `lake.exe`（找不到 ⇒ 空串）。

    为什么只在同一目录里找：`lake env lean` 会把 `PATH` 换成工具链里自己的 `lean`。
    若那个 `lake` 不是这一个 `lean` 的同伴（例如 `--lean` 指着一个自造的假解释器，
    而 PATH 上另有一个 lake），第 ⑤ 步编译的就不是自检的那一个二进制 ——
    "自检的东西"与"自检用的东西"分家，是这类读数里最贵的一种错。
    """
    exe = str(lean_exe or "").strip()
    if not exe:
        return ""
    folder = Path(exe).parent
    names = ("lake.exe", "lake") if os.name == "nt" else ("lake", "lake.exe")
    for name in names:
        cand = folder / name
        if cand.is_file():
            return str(cand)
    return ""


def mathlib_reading(*, root: str | Path | None = None, env: Mapping[str, str] | None = None,
                    mathlib_root: str | None = None,
                    lean_exe: str = "") -> dict[str, Any]:
    """第 ⑤ 步的前半：这台机器上那份 Mathlib 在哪、它的库长什么样（纯盘面读，不起进程）。

    参数：

    - `root`：工作区根（用来找 `_env/` 下的缺省候选，见 :func:`_mathlib_default_candidates`）；
    - `env`：当成环境变量表用（`None` ⇒ `os.environ`）。给了它就只认它 ——
      与 :func:`selfcheck` 同一口径，判据因此不会读到开发机上的真配置；
    - `mathlib_root`：显式指定的工程根（`--mathlib-root` 那一档）。指到的目录不是
      Mathlib 工程时不静默往下掉（配置问题就是配置问题）；
    - `lean_exe`：解析到的解释器（用来找它旁边的 `lake.exe`）。

    返回 `_empty_mathlib()` 那个形状。三件事实分栏给：`detected`（找到了工程根）、
    `umbrella_olean` / `graph_olean`（盘上有没有那两个文件）、`lake_exe` / `lean_path`
    （第 ⑤ 步能用哪条命令）。

    这一格「不」下"可用"的结论：`state` 只可能是 `absent` / `unknown`（未检出 / 没查成）。
    `usable` 与 `unusable` 只能由真编译给出，见 :func:`_mathlib_control` ——
    盘面上 `Mathlib.olean` 在、而 `import Mathlib` 报 `unknown package 'Std'` 的那次
    真机事故（`toolchain._import_mathlib_probe` 的 docstring 逐字记着）就是这么来的。
    """
    out = _empty_mathlib()
    src = dict(os.environ if env is None else env)
    try:
        from . import formalgw as FG
    except Exception as exc:  # noqa: BLE001 - 读不到"什么算工程根"就只能如实报没查成
        out["problems"].append(f"读不出 Mathlib 工程根的判据（formalgw 导不进来："
                               f"{type(exc).__name__}: {exc}）⇒ 这一项没查成")
        out["reason"] = "没查成：Mathlib 的检测判据读不到"
        return out

    out["expected_version"] = expected_version()
    explicit = str(mathlib_root or "").strip()
    defaults = _mathlib_default_candidates(root)
    if explicit:
        explicit_path = str(SET.resolve_setting_path(explicit))
        if FG._is_mathlib_root(Path(explicit_path)):  # noqa: SLF001 - 判据只有那一份
            out.update({"checked": True, "detected": True, "root": explicit_path,
                        "source": "flag"})
        else:
            out["checked"] = True
            out["state"] = "unusable"
            out["problems"].append(
                f"显式给的 Mathlib 工程根不是 Mathlib 工程：{explicit}（解析成 "
                f"{explicit_path}；判据是同时含 `lakefile.lean` 与 `lean-toolchain`）"
                "—— 配了却找不到是配置问题，不静默退回裸 lean")
            out["reason"] = "不可用：显式指定的工程根不是 Mathlib 工程"
            return out
    else:
        found = FG.find_mathlib_root(env=env, candidates=tuple(defaults))
        out["checked"] = True
        out["source"] = _mathlib_source_label(found, explicit="", default_candidates=defaults,
                                              env=env)
        if not found:
            out["state"] = "absent"
            out["reason"] = ("无 Mathlib（五档都找过：AGENTFLOW_MATHLIB_ROOT、LEAN_PATH、"
                             "settings.json 的 toolchain.mathlib_root、"
                             + "/".join(MATHLIB_DEFAULT_DIRS)
                             + " 这几档缺省候选、调用方显式给的那一份）"
                             "⇒ 第 ⑤ 步退回裸 lean 跑，这一档不是「检查器不可用」")
            return out
        out.update({"detected": True, "root": str(found)})

    mroot = Path(str(out["root"]))
    out["lakefile"] = str(mroot / "lakefile.lean")
    out["toolchain_file"] = str(mroot / "lean-toolchain")
    out["version"] = _read_first_line(out["toolchain_file"])
    out["umbrella_olean"] = _first_existing(mroot, "Mathlib.olean")
    parts = MATHLIB_GRAPH_MODULE.split(".")
    out["graph_olean"] = _first_existing(
        mroot, str(Path(*parts[:-1]) / f"{parts[-1]}.olean"))
    out["lake_exe"] = _lake_beside(lean_exe)
    try:
        from . import toolchain as TC

        out["lean_path"] = TC.lean_path_for(mroot)
    except Exception as exc:  # noqa: BLE001 - 拼不出 LEAN_PATH 是"这一档没查成"，不是不可用
        out["problems"].append(f"拼不出 LEAN_PATH（{type(exc).__name__}: {exc}）")
        out["lean_path"] = ""
    out["lean_path_segments"] = len([s for s in out["lean_path"].split(os.pathsep) if s])
    out["checked"] = True
    out["state"] = "unknown"
    out["reason"] = (
        f"检测到工程根 {out['root']}（来源 {out['source']}；"
        f"{'umbrella 的 .olean 在' if out['umbrella_olean'] else 'umbrella 的 .olean 不在'}；"
        f"{'SimpleGraph 的 .olean 在' if out['graph_olean'] else 'SimpleGraph 的 .olean 不在'}）"
        "—— 可用与否由第 ⑤ 步的一次真编译决定，盘面这两格里没有「可用」这个结论")
    return out


def _read_first_line(path: str) -> str:
    """读一个文本文件的第一行（读不出来 ⇒ 空串；`lean-toolchain` 就是一行）。"""
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    lines = text.strip().splitlines()
    return lines[0].strip() if lines else ""


def mathlib_command(reading: Mapping[str, Any], lean_exe: str,
                    source_path: str, *, workdir: str) -> dict[str, Any]:
    """第 ⑤ 步用哪一条命令行去编译那份带 `import Mathlib...` 的源码。

    返回 `{runner, argv, cwd, env_overlay, why}`（`argv` 里的 `<file>` 已换成
    `source_path`）。三档，顺序即优先级：

    - `lake_env_lean`：`[<lake>, env, lean, <file>]`，cwd = Mathlib 工程根。首选 ——
      `lake env` 是工程自己声明的那一份环境，路径拼法随 lake 版本变也不归我们猜。
    - `lean_path`：`[<lean>, <file>]` 加 `LEAN_PATH`（只加不改，我们的段在前）。
      次选，只在 `lake.exe` 不在那个 `lean.exe` 旁边时才用（理由见 :func:`_lake_beside`）。
    - `bare`：`[<lean>, <file>]`，什么都没配。这一档有两来由：这台机器没有 Mathlib
      （`absent`，退回裸 lean 是本模块的约定动作），或者检测到了工程根却既没有 lake
      也拼不出 `LEAN_PATH`（那这一次编译预期会失败，第 ⑤ 步会如实报 `unusable` ——
      不在这里替它猜一个"大概能过"）。
    """
    exe = str(lean_exe or "")
    path = str(source_path or "")
    root = str(reading.get("root") or "")
    lake = str(reading.get("lake_exe") or "")
    segments = str(reading.get("lean_path") or "")
    if root and lake:
        return {"runner": "lake_env_lean", "argv": [lake, "env", "lean", path],
                "cwd": root, "env_overlay": {},
                "why": f"用 `lake env lean`（cwd = 工程根 {root}）"}
    if root and segments:
        have = [s for s in str(os.environ.get("LEAN_PATH") or "").split(os.pathsep) if s]
        merged: list[str] = []
        for seg in segments.split(os.pathsep) + have:
            if seg and seg not in merged:
                merged.append(seg)
        return {"runner": "lean_path", "argv": [exe, path], "cwd": str(workdir),
                "env_overlay": {"LEAN_PATH": os.pathsep.join(merged)},
                "why": (f"没有与 {exe} 同目录的 lake ⇒ 显式给 LEAN_PATH"
                        f"（{len([s for s in segments.split(os.pathsep) if s])} 段）")}
    if root:
        return {"runner": "bare", "argv": [exe, path], "cwd": str(workdir),
                "env_overlay": {},
                "why": (f"检测到工程根 {root}，但那里既没有 lake.exe 也拼不出 "
                        "LEAN_PATH ⇒ 这一次只能按裸命令试（预期会失败，读数会如实说）")}
    return {"runner": "bare", "argv": [exe, path], "cwd": str(workdir), "env_overlay": {},
            "why": "无 Mathlib ⇒ 退回裸 lean（与正/反样例同一个调用方式）"}


def _mathlib_control(out: dict[str, Any], exe: str, workdir: Path, *,
                     timeout_sec: float) -> tuple[str, str]:
    """第 ⑤ 步：把 `import Mathlib.Combinatorics.SimpleGraph.Basic` 加 `#check SimpleGraph`
    交给带 Mathlib 的那条命令真编译一次。返回 `(mathlib_state, 一行理由)`。

    读数全部写进 `out["mathlib"]`（形状是 `_empty_mathlib()` 加上这次运行的几格）。
    四档的落点：

    - 没有 Mathlib（`detected=False`）⇒ `absent`：这一次不给结论，也不把它说成
      "检查器不可用"（业主口径：缺库是这一项不可用，不是检查器坏了）；
    - 退出码 0 且输出里有 `SimpleGraph` ⇒ `usable`；
    - 退出码非 0 ⇒ `unusable`，理由里带上检查器的原文（例如 `unknown package 'Mathlib'`
      与 `unknown identifier 'SimpleGraph'` —— 那正是"裸 lean 不知道 Mathlib 在哪"的原文）；
    - 超时 / 进程起不来 ⇒ `unknown`（没查成），不折成不可用。
    """
    row = out["mathlib"]
    if str(row.get("state")) == "unusable":
        # 检测阶段就已经不可用（显式给的工程根不是 Mathlib 工程）：这一档不必再花
        # 一次编译，理由已经在 `reason` 里。它照样是 `unusable`，但不再起进程 ——
        # 配置问题与编译没过是两件事，处置也不同，所以理由里逐字写明是哪一种。
        return "unusable", str(row.get("reason") or "不可用")
    if not row.get("detected"):
        if str(row.get("state")) == "absent":
            row["state"] = "absent"
            return "absent", str(row.get("reason") or "无 Mathlib")
        row["state"] = "unknown"
        return "unknown", str(row.get("reason") or "没查成：Mathlib 的检测没跑成")
    src_path, why = _write_probe(workdir, f"{GRAPH_NAME}.lean", GRAPH_SOURCE)
    if why:
        row["state"] = "unknown"
        row["problems"].append(why)
        row["reason"] = f"没查成：{why}"
        return "unknown", row["reason"]
    cmd = mathlib_command(row, exe, src_path, workdir=str(workdir))
    row["runner"] = str(cmd["runner"])
    row["argv"] = [str(c) for c in cmd["argv"]]
    row["cwd"] = str(cmd["cwd"])
    got = _run(cmd["argv"], cwd=str(cmd["cwd"]), timeout_sec=timeout_sec,
               env_overlay=cmd["env_overlay"] or None)
    row["exit_code"] = got["exit_code"]
    row["output_head"] = got["output_head"]
    row["evidence"] = got["output_head"]
    row["elapsed_ms"] = got["elapsed_ms"]
    if got["timed_out"]:
        row["state"] = "unknown"
        row["reason"] = (f"第 ⑤ 步在 {timeout_sec:g} 秒内没回话 ⇒ 没查成"
                         "（这不是「图论不可用」：这一次没有结论）")
        return "unknown", row["reason"]
    if not got["started"]:
        row["state"] = "unknown"
        row["reason"] = f"第 ⑤ 步起不了这条命令：{got['error']} ⇒ 没查成"
        return "unknown", row["reason"]
    if got["exit_code"] != 0:
        row["state"] = "unusable"
        row["reason"] = (
            f"图论不可用：`{MATHLIB_GRAPH_MODULE}` + `#check SimpleGraph` 以退出码 "
            f"{got['exit_code']} 收场（工程根 {row.get('root')}；"
            f"跑的是 {row.get('runner')}）—— 检查器原文："
            f"{_head(got['output_head']) or '（空输出）'}")
        return "unusable", row["reason"]
    if GRAPH_MARKER not in str(got["output_head"]):
        row["state"] = "unusable"
        row["reason"] = (
            "图论不可用：退出码是 0，但输出里没有 `SimpleGraph` 那一行 —— "
            "通过必须能被看见（回显式的假解释器给不出 `#check` 的结果）："
            f"{_head(got['output_head']) or '（空输出）'}")
        return "unusable", row["reason"]
    row["state"] = "usable"
    row["reason"] = (f"图论可用：`{MATHLIB_GRAPH_MODULE}` + `#check SimpleGraph` 以 0 退出"
                     f"（{row.get('runner')}），输出开头 {_head(got['output_head'])}")
    return "usable", row["reason"]


# ============================================================ 临时目录


def _make_workdir(tmp_root: str | Path | None) -> tuple[str, str]:
    """在 `tmp_root`（缺省 `%TEMP%`）下开一个临时目录。返回 `(路径, 问题)`。"""
    base = None
    if tmp_root is not None:
        base = Path(tmp_root)
        try:
            base.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return "", (f"建不出 tmp_root={base}（{type(exc).__name__}: {exc}）"
                        "⇒ 这一步没查成")
    try:
        return tempfile.mkdtemp(prefix="agentflow-lean-selfcheck-",
                                dir=str(base) if base is not None else None), ""
    except OSError as exc:
        return "", (f"开不出临时目录（{type(exc).__name__}: {exc}）⇒ 这一步没查成")


def _drop_workdir(path: str) -> str:
    """删净临时目录。返回问题说明（空串 = 删干净了）。

    删不干净是「卫生问题」，不是"这个 lean 不可用"：它的后果是盘上多一个目录，
    而把它读成 `unusable` 会让下一次有人因为一条无关的清理失败去查 Lean。
    """
    try:
        shutil.rmtree(path, ignore_errors=False)
    except OSError as exc:
        return f"{HYGIENE_PREFIX} 临时目录没删净：{path}（{type(exc).__name__}: {exc}）"
    return "" if not Path(path).exists() else f"{HYGIENE_PREFIX} 临时目录删了还在：{path}"


# ============================================================ 本体


def selfcheck(*, root: str | Path | None = None, env: Mapping[str, str] | None = None,
              timeout_sec: float = DEFAULT_TIMEOUT_SEC,
              tmp_root: str | Path | None = None,
              lean: str | None = None,
              mathlib_root: str | None = None) -> dict[str, Any]:
    """跑一次 Lean 工具链开机自检。返回一份四档读数（形状见模块 docstring）。

    参数（全部显式，便于判据注入 —— 它不读任何本机隐藏状态）：

    - `root`：工作区根，用来读 `config.yaml` 的 `lean_path`（`None` ⇒ 这一档不适用），
      也当作 `_env/` 下那些 Mathlib 缺省候选的基点（见 `_mathlib_default_candidates`）；
    - `env`：当成环境变量表用（`None` ⇒ `os.environ`）。给了它就「只认它」：
      设置文件那一档也只在它里面给了 `AGENTFLOW_SETTINGS` 时才读（与
      `settings.load_settings` 同一口径），于是判据不会读到开发机上的真配置；
    - `timeout_sec`：单步超时（秒）；
    - `tmp_root`：临时 `.lean` 的落点（缺省 `%TEMP%`），跑完删净；
    - `lean`：`--lean` 那一档的显式路径（可执行文件或它所在的目录）；
    - `mathlib_root`：第 ⑤ 步那一档的显式 Mathlib 工程根（不给 ⇒ 按
      `formalgw.find_mathlib_root` 的四档加 `_env/` 缺省候选找）。指到的目录不是
      Mathlib 工程时按配置问题处理（`mathlib.state="unusable"`），不静默退回裸 lean。

    返回里 `checked` 问"自检跑成没有"，`ok` 只在 `checked` 为真时有意义；
    `problems` 逐条写"没通过"的原因（可操作：说清是哪一档、哪个值、该改哪儿），
    带 `[卫生]` 前缀的条目是这次自检自己留下的垃圾，不影响 `state`。
    `mathlib` 那一格（第 ⑤ 步）的细节「不进」`problems`：缺库与坏检查器的处置相反。
    两条例外是它自己的两种不可用（第 ⑤ 步 `unusable` 与显式工程根不是 Mathlib 工程）——
    那两种会被追加一条 `[Mathlib]` 开头的条目并让整次自检不是 `usable`。
    """
    started = _now()
    src = dict(os.environ if env is None else env)
    out = _empty_result()
    out["expected_version"] = expected_version()

    # ---- 开关：关着时「一次都不碰」 lean（不 spawn、不建临时目录、不算哈希）
    try:
        enabled, enabled_src = SET.lean_enabled(env=env)
    except ValueError as exc:
        out["problems"].append(f"开关值读不懂 ⇒ 没查成（不是『关着』也不是『不可用』）：{exc}")
        out["enabled_source"] = "unreadable"
        out["note"] = ("这次连开关都没读出来，所以一步都没跑；"
                       "把 settings.json 的 toolchain.lean_enabled 改成 true/false 之后重来")
        out["elapsed_ms"] = _ms(started)
        return out
    out["enabled"] = bool(enabled)
    out["enabled_source"] = str(enabled_src or "default")
    if not enabled:
        out["checked"] = True
        out["state"] = "off"
        out["note"] = ("本会话的 Lean 形式化已关闭（toolchain.lean_enabled=false 或 "
                       "AGENTFLOW_LEAN_ENABLED=0）⇒ 一次子进程都没起、一个临时文件都没写。"
                       "这一档是『关着』，既不是『不可用』，也不是『查过了没问题』")
        # 第 ⑤ 步那一格也要说清它为什么是空的：关着时连检测都没做（不是"没有 Mathlib"）。
        out["mathlib"]["reason"] = (
            "没查（Lean 形式化关着 ⇒ 在第 ⑤ 步之前就返回了：没检测工程根、没起子进程）"
            "—— 这一档既不是「不可用」，也不是「可用」")
        out["elapsed_ms"] = _ms(started)
        return out

    # ---- ① 解析
    path, source, resolve_problems = _resolve(src, root=root, lean=lean, env=env)
    out["problems"].extend(resolve_problems)
    if not path:
        out["checked"] = True
        out["state"] = "unusable"
        out["source"] = ""
        out["note"] = ("查过了：这台机器上（按五档找）没有可用的 lean 解释器 ⇒ "
                       "unusable。它不是 off（开关是开着的），也不是 unknown（查找做成了）")
        out["elapsed_ms"] = _ms(started)
        return out
    out["source"] = source
    out["lean_path"] = str(path)
    out["sha256"], sha_why = _sha256_of(path)
    if sha_why:
        out["problems"].append(sha_why)

    # ---- 第 ⑤ 步的前半：Mathlib 在哪（纯盘面读，不起进程；找不到也不算缺陷）
    # 放在这里而不是 `_four_steps` 里：`absent` 时前四步照跑（退回裸 lean），
    # 而"有没有库"这件事与"这个 lean 是不是检查器"是两根轴，读数上要分得开。
    out["mathlib"] = mathlib_reading(root=root, env=env, mathlib_root=mathlib_root,
                                     lean_exe=str(path))

    # ---- 临时目录（三步子进程共用同一个，跑完删净）
    workdir, workdir_why = _make_workdir(tmp_root)
    if workdir_why:
        out["problems"].append(workdir_why)
        out["state"] = "unknown"
        out["checked"] = False
        out["note"] = "临时目录都开不出来 ⇒ 自检没跑成；这是本机环境问题，不是这个 lean 的问题"
        out["elapsed_ms"] = _ms(started)
        return out
    try:
        verdict, detail = _four_steps(out, str(path), Path(workdir),
                                      timeout_sec=float(timeout_sec))
    except Exception as exc:  # noqa: BLE001 - 自检自己崩了是"没查成"，不是"不可用"
        out["problems"].append(f"自检自己崩了（{type(exc).__name__}: {exc}）⇒ 没查成")
        out["state"] = "unknown"
        out["checked"] = False
        out["note"] = ("自检的实现自己炸了 —— 这一档必须读成『没查成』："
                       "它没有给出关于这个 lean 的任何结论")
        out["elapsed_ms"] = _ms(started)
        return out
    finally:
        hygiene = _drop_workdir(workdir)
        if hygiene:
            out["problems"].append(hygiene)

    out["state"] = verdict
    out["checked"] = detail["checked"]
    out["ok"] = bool(out["checked"] and verdict == "usable")
    out["note"] = detail["note"]
    # 第 ⑤ 步没跑到时（前四步已经给了结论），把那一格的 reason 补一句：
    # 它的 `state` 仍然是 `unknown`（没有结论），既不写成"可用"也不写成"不可用"。
    _m = out.get("mathlib") or {}
    if _m.get("detected") and _m.get("state") == "unknown" and _m.get("exit_code") is None:
        _m["reason"] = (str(_m.get("reason") or "")
                        + "（前四步已经给了结论 ⇒ 这一次没有跑到第 ⑤ 步："
                          "它没查，不是不可用，也不是可用）")
    out["elapsed_ms"] = _ms(started)
    return out


def _four_steps(out: dict[str, Any], exe: str, workdir: Path, *,
                timeout_sec: float) -> tuple[str, dict[str, Any]]:
    """②③④ 三步加第 ⑤ 步：返回 `(state, {checked, note})`，并把读数写进 `out`。

    分成一个函数是为了让 `selfcheck` 的 `try/finally`（临时目录）与"自检自己崩了"
    那一档读起来是两条线：编排（解析/清理/结论）与判据（几步本身）各自只有一处。

    第 ⑤ 步排在最后、且只在前四步已经判成 `usable` 时才跑：一次 Mathlib 编译在本机
    实测约 7–11 秒（裸 lean 加 `LEAN_PATH` 约 7 秒、`lake env lean` 约 11 秒），
    而"这个解释器是不是检查器"这件事前四步已经答完了 —— 一个连反控都过不了的东西，
    再花十秒问它图论库通不通没有意义（它通不通都构不成证据）。
    """
    # ---- ② 版本
    ver = _run([exe, "--version"], cwd=str(workdir), timeout_sec=min(VERSION_TIMEOUT_SEC,
                                                                   timeout_sec))
    if ver["timed_out"]:
        out["problems"].append(f"`lean --version` 在 {VERSION_TIMEOUT_SEC:g} 秒内没回话 ⇒ 没查成")
        return "unknown", {"checked": False, "note": "版本这一档都没问出来 ⇒ 自检没跑成"}
    if not ver["started"]:
        out["problems"].append(f"这个解释器起不来（{ver['error']}）⇒ 查过了，不可用")
        return "unusable", {"checked": True,
                            "note": "解释器文件在，但它起不来（不是合法的可执行文件/权限不足）"}
    parsed, parse_why = _parse_version(ver["output_head"])
    out["version"] = parsed
    version_ok, version_problems = _version_verdict(parsed, out["expected_version"])
    out["version_ok"] = bool(version_ok)
    if ver["exit_code"] != 0:
        out["problems"].append(f"`lean --version` 退出码 {ver['exit_code']}"
                              f"（输出开头：{ver['output_head'] or '（空）'}）⇒ 不是能用的版本命令")
    out["problems"].extend(version_problems)
    if parse_why:
        out["problems"].append(parse_why)

    # ---- ③ 正样例
    pos = _positive_control(exe, workdir, timeout_sec=timeout_sec)
    out["positive"] = pos
    if pos["problem"]:
        out["problems"].append(pos["problem"])
    if pos["kind"] == "not_checked":
        # 超时/写不出文件：这一步没得出结论 ⇒ 整体是"没查成"（不是"不可用"）。
        return "unknown", {"checked": False,
                           "note": "正样例那一步没得出结论 ⇒ 自检没跑成"}
    if pos["kind"] == "unusable":
        # 起不来 / 连 1 = 1 都编不过：查过了，这个解释器不可用（不必再跑反控 ——
        # 一个连真命题都不接受的东西，"拒绝了假命题"也不构成任何证据）。
        return "unusable", {"checked": True,
                            "note": "查过了：正样例（1 = 1）都没过 ⇒ 这个解释器不可用"}

    # ---- ④ 反控（必须失败）
    neg = _negative_control(exe, workdir, timeout_sec=timeout_sec)
    out["negative"] = neg
    if neg["problem"]:
        out["problems"].append(neg["problem"])
    if neg["kind"] == "not_checked":
        return "unknown", {"checked": False,
                           "note": "反控那一步没得出结论 ⇒ 自检没跑成"}

    blocking = [p for p in out["problems"] if not str(p).startswith(HYGIENE_PREFIX)]
    if blocking:
        return "unusable", {"checked": True,
                            "note": "查过了：这个解释器不构成一条可用的 Lean 工具链（原因逐条见 problems）"}

    # ---- ⑤ Mathlib（图论那一项）
    # 它有三档要分开落：
    #   absent   ⇒ 退回裸 lean 本来的结论（这一趟没有库这一项，不是缺陷）；
    #   unusable ⇒ 整次自检不许是 usable，并追加一条 `[Mathlib]` 开头的 problem
    #              （业主口径：那一项不可用时不许把整次自检判成 usable）；
    #   unknown  ⇒ 这一步没查成 ⇒ 整次自检是"没查成"（与前四步超时同一档；
    #              这一步的结论没拿到，就不许把整次报成"查过了没问题"）。
    mstate, mwhy = _mathlib_control(out, exe, workdir, timeout_sec=timeout_sec)
    if mstate == "unknown":
        return "unknown", {"checked": False,
                           "note": f"第 ⑤ 步（Mathlib 图论）没得出结论 ⇒ 自检没跑成：{mwhy}"}
    if mstate == "unusable":
        out["problems"].append(f"[Mathlib] {mwhy}")
        return "unusable", {"checked": True,
                            "note": ("查过了：这个解释器本身是个检查器，但它接不上那一条"
                                     f"图论库（Mathlib 那一项 {mstate}）—— 原因与检查器原文见 problems")}
    mathlib_note = ("图论可用（Mathlib 工程根 "
                    f"{out['mathlib'].get('root') or '（无）'}；"
                    f"{out['mathlib'].get('runner') or '（没跑）'}）"
                    if mstate == "usable" else
                    "无 Mathlib ⇒ 第 ⑤ 步退回裸 lean 跑（前四步的结论不受影响）")
    return "usable", {"checked": True,
                      "note": (f"四步全过：版本 {out['version']}（期望 {EXPECTED_LEAN_MAJOR}.x"
                               + (f" / {out['expected_version']}" if out["expected_version"] else "")
                               + "）；正样例退出 0；反控（假命题 1 = 2）被拒绝"
                               f"（退出码 {out['negative']['exit_code']}）—— 这个 lean 会拒绝假命题；"
                               + mathlib_note)}


# ============================================================ 只读读数（模块级缓存）


#: 读数缓存：`(root, lean, 四档环境变量, mathlib_root)` → 上一份读数。
#:
#: 为什么必须缓存：一次自检要起三到四个子进程（本机真机实测 1.3 秒；接上 Mathlib 之后
#: 多一次约 7–11 秒的真编译），而"第一屏摘要"与"收工门那一格"问的是同一个问题、
#: 在同一趟里问两遍。缓存的是「读数」而不是"结论"：键里带着解析相关的四档环境变量，
#: 换一档就问一次，不会把上一次的答案张冠李戴。要强制重查用 `refresh=True`。
_READING_CACHE: dict[tuple[str, ...], dict[str, Any]] = {}


def _cache_key(root: str | Path | None, env: Mapping[str, str] | None,
               lean: str | None, mathlib_root: str | None = None) -> tuple[str, ...]:
    """读数的缓存键：解析这一趟答案所依赖的全部输入（含第 ⑤ 步那一档）。"""
    src = dict(os.environ if env is None else env)
    return (str(root or ""), str(lean or "").strip(),
            str(src.get("AGENTFLOW_LEAN_BIN") or "").strip(),
            str(src.get("AGENTFLOW_LEAN_ENABLED") or "").strip(),
            str(src.get("AGENTFLOW_SETTINGS") or "").strip(),
            str(mathlib_root or "").strip())


def lean_selfcheck_reading(*, root: str | Path | None = None,
                           env: Mapping[str, str] | None = None,
                           timeout_sec: float = DEFAULT_TIMEOUT_SEC,
                           tmp_root: str | Path | None = None,
                           lean: str | None = None,
                           mathlib_root: str | None = None,
                           refresh: bool = False) -> dict[str, Any]:
    """只读读数：这一趟的 Lean 工具链自检结论（同一档只查一次，返回深拷贝）。

    生产面（`cli` 的 doctor / 第一屏摘要 / 收工门那一格）只许从这一口取值：
    它是「读数」不是命令 —— 调用方拿到的是一份形状固定的字典，不许自己再 spawn 一次
    （两次 spawn 会给出"两个答案"，而这类漂移在本仓库已经栽过：见
    `toolchain.py` 模块 docstring 的开头那两条现场）。

    第 ⑤ 步那一格在 `reading["mathlib"]`（形状见 `_empty_mathlib`）：版本（`lean-toolchain`
    那一行）/ 工程根 / 图论可用与否 / 检查器原文，四件事分栏给。
    """
    key = _cache_key(root, env, lean, mathlib_root)
    if refresh or key not in _READING_CACHE:
        _READING_CACHE[key] = selfcheck(root=root, env=env, timeout_sec=timeout_sec,
                                        tmp_root=tmp_root, lean=lean,
                                        mathlib_root=mathlib_root)
    return copy.deepcopy(_READING_CACHE[key])


def reset_reading_cache() -> None:
    """清空读数缓存（判据换档时用；生产面不需要调它）。"""
    _READING_CACHE.clear()


def formal_evidence_state(reading: Mapping[str, Any] | None) -> tuple[str, str]:
    """形式化证据该记成哪一档：`("verified" | "unknown", 原因)`。

    这是"防虚构环境"在本模块这一侧的落点：「只有 `usable` 才给 `verified`」。
    其余三档（`off` / `unusable` / `unknown`）一律 `unknown` + 一句点名原因，
    因为它们的共同点是"我们没有拿到一个会拒绝假命题的检查器"—— 在这种情况下
    任何 `evidence_kind="proof"` 的东西都不许被记成 verified。

    `reading` 读不出来（`None` 或者形状不对）同样给 `unknown`：读数缺失不是通过。
    """
    state = ""
    if isinstance(reading, Mapping):
        state = str(reading.get("state") or "")
    if state == "usable":
        return "verified", ""
    problems = []
    if isinstance(reading, Mapping):
        problems = [str(p) for p in (reading.get("problems") or [])]
    blocking = [p for p in problems if not p.startswith(HYGIENE_PREFIX)]
    if blocking:
        why = blocking[0]
    elif state == "off":
        why = "Lean 形式化这一趟是关着的（自检没跑，也没起子进程）"
    elif state:
        why = f"自检结论 {state}"
    else:
        why = "没有自检读数（读不到它不等于通过）"
    return "unknown", why


def evidence_state_problem(reading: Mapping[str, Any] | None) -> str:
    """摘要里那一句话：自检不是 `usable` 时，"为什么形式化证据被记成 unknown"。"""
    state, why = formal_evidence_state(reading)
    if state == "verified":
        return ""
    return f"形式化证据记 unknown（不是 verified）：Lean 工具链自检没给出可用结论 —— {why}"


if __name__ == "__main__":  # pragma: no cover - 手动跑这一档时的入口
    import json
    import sys

    print(json.dumps(selfcheck(), ensure_ascii=False, indent=2, default=str))
    sys.exit(0)

# -*- coding: utf-8 -*-
"""这台机器上的证明工具链：在哪、哪一版、能不能用 —— 「一处定义」。

## 为什么要有这一层（2026-10-03 的现场）

`tools/verify_tools.py`（探测）与 `formalgw.py`（调用）此前「各自」 `shutil.which("lean")`
—— 两处独立地"看 PATH"。这带来两个后果，那天都实测到了：

1. 「同一台机器上"探测说没有、调用却真能跑"是可能的」（两处的口径各写一份，本可以漂）。
   实测：Lean 4.7.0 就装在这台机器的一个目录里（不在 PATH 上），
   而 `detect_verifier()` 报 `available=[]`。
2. 「能力静默降级」：探测说"没有检查器" ⇒ 形式化那一条腿改成 `cross_check`，
   报告里只剩一句"没核到"，而「没有任何地方会说"这台机器其实能做"」。
   用户的原话是"这是坏的" —— 坏的正是这种"看不出来"。

所以本层的职责只有一件事：把「这台机器能做形式化核验吗」变成一个「可读、可判据、三态」的读数，
并让「探测与调用共用同一个答案」（谁都不许再自己 `which` 一次）。

## 本机路径写在哪（代码与文档里都不再写某台机器的绝对路径）

这台机器的 Lean / Coq / Isabelle 装在哪，写在 `settings.json` 的
`toolchain.lean_bin` / `toolchain.coq_bin` / `toolchain.isabelle_bin`，
Mathlib 工程根写在 `toolchain.mathlib_root`（见 `agentflow/settings.example.json`
与 :mod:`agentflow.settings`；2026-10-07 起）。改前这里是逐字写着一台机器的
绝对路径的 —— 那是"机器相关的事实落在代码里"，换一台机器就变成一句假话。

## 查找顺序（每一档都留下"是从哪找到的"）

优先级（逐字，唯一口径）：环境变量 > 设置文件 > 内置默认/自动探测。
环境变量压在最上面，是为了 CI 与既有脚本不被这次改动弄坏（逐条理由见
:mod:`agentflow.settings` 的模块 docstring）。

1. 「显式配置（环境变量）」：`AGENTFLOW_LEAN_BIN` / `AGENTFLOW_COQ_BIN` /
   `AGENTFLOW_ISABELLE_BIN` —— 取值可以是「可执行文件」本身，也可以是
   「它所在的目录」（"指向安装目录"是人最自然的写法）；
2. 「`AGENTFLOW_PROVER_PATH`」（也是环境变量）：一个或多个目录
   （Windows 用 `;`、POSIX 用 `:` 分隔）；
3. 「设置文件」：`settings.json` 的 `toolchain.lean_bin` / `toolchain.coq_bin` /
   `toolchain.isabelle_bin`（同一套"文件或目录"的写法；相对路径相对工作区根解析，
   见 `settings.resolve_setting_path`）；
4. 「PATH」（`shutil.which`）—— 最后那一档自动探测。

「配了但找不到 ⇒ 记成配置问题（fail-closed）」，不当作"环境里没有"：把配置错读成
"没有检查器"，正是上面第 2 条那个静默降级。三态也照旧：探测本身没做成
（PATH 读不了、版本命令起不来）⇒ `checked=False`，绝不是"确定没有"。

## 谁在用这一层

- `tools/verify_tools.detect_verifier`（「禁改区」）只是「转发」到这里的 :func:`probe_checkers`
  —— 与它转发 `check_formal` 到 `formalgw.check_lean` 是同一条纪律（判据只有一处定义）；
- `formalgw.find_lean` 也走这里 —— 探测与调用从此不可能再各说各话；
- `agentflow doctor` 把 :func:`toolchain_report` 打给人看（跑之前先知道这台机器能不能做那件事）。
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import settings as SET

__all__ = [
    "CHECKERS", "ENV_LEAN_BIN", "ENV_COQ_BIN", "ENV_ISABELLE_BIN", "ENV_PROVER_PATH",
    "ENV_VERIFIER_BINS", "VERSION_COMMANDS", "resolve_checker", "probe_checkers",
    "mathlib_state", "toolchain_report",
]

#: 受支持的检查器，以及它们各自的"报版本"命令（探测时原样跑）。
VERSION_COMMANDS: Mapping[str, str] = {
    "lean": "lean --version",
    "coqc": "coqc --version",
    "isabelle": "isabelle version",
}
#: 顺序即展示顺序（Lean 是本项目形式化路径的唯一后端，排第一）。
CHECKERS: tuple[str, ...] = ("lean", "coqc", "isabelle")

#: 显式给出检查器的环境变量（可执行文件或它所在的目录）。
ENV_LEAN_BIN = "AGENTFLOW_LEAN_BIN"
ENV_COQ_BIN = "AGENTFLOW_COQ_BIN"
ENV_ISABELLE_BIN = "AGENTFLOW_ISABELLE_BIN"
#: 通用一档：一个或多个目录（`;` 在 Windows、`:` 在 POSIX 上分隔）。
ENV_PROVER_PATH = "AGENTFLOW_PROVER_PATH"
#: 检查器名 → 它自己的环境变量。
ENV_VERIFIER_BINS: Mapping[str, str] = {
    "lean": ENV_LEAN_BIN, "coqc": ENV_COQ_BIN, "isabelle": ENV_ISABELLE_BIN,
}
#: 检查器名 → `settings.json` 的 `toolchain` 段里那个键（第三档）。
#: 与 `ENV_VERIFIER_BINS` 逐名对齐：两张表的键集合由 `CHECKERS` 决定，漏一个
#: 会让"这个检查器永远读不到设置文件"，而症状只是"设置不生效"（静默）。
SETTING_KEYS: Mapping[str, str] = {
    "lean": "lean_bin", "coqc": "coq_bin", "isabelle": "isabelle_bin",
}


def _env(env: Mapping[str, str] | None) -> dict[str, str]:
    """读环境变量（给了 `env` 就用它，否则读 `os.environ`）—— 便于判据注入。"""
    return dict(os.environ if env is None else env)


def _probe_one_path(name: str, raw: str) -> tuple[str, str, str]:
    """一档"文件或目录"的取值 → `(路径, source, problem)`（三处共用，免得各写一份）。

    `raw` 是用户写的原样文本（可能是相对路径）：解析规则只有一处，
    见 `settings.resolve_setting_path`（相对工作区根，不相对进程 cwd）。
    """
    p = SET.resolve_setting_path(raw)
    if p.is_file():
        return str(p), "file", ""
    if p.is_dir():
        found = shutil.which(name, path=str(p))
        if found:
            return str(found), "dir", ""
        return "", "", f"{raw} 是目录，但里面没有 {name}（解析成 {p}）"
    return "", "", f"{raw} 不存在（解析成 {p}）"


def resolve_checker(name: str, env: Mapping[str, str] | None = None) -> dict[str, Any]:
    """一个检查器在哪、是从哪一档找到的、有没有配置问题。「不跑版本命令」。

    返回 `{"name", "path", "source", "problem", "looked"}`：

    - `path` 找到时的绝对路径，找不到是空串；
    - `source` 取值 `"explicit"`（环境变量指到文件）/ `"explicit_dir"`（指到目录）/
      `"settings"`（设置文件指到文件）/ `"settings_dir"`（设置文件指到目录）/
      `"prover_path"`（`AGENTFLOW_PROVER_PATH`）/ `"path"`（PATH）/ `""`（没找到）；
      "是从哪一档找到的"必须能被读出来 —— 只回一个路径的话，
      "机器上恰好装着"与"有人显式配过"在下游无法区分；
    - `problem` 非空表示「这一档配了却不能用」（例如路径不存在）—— 它与"没配"是两件事
      （fail-closed：配置错不许被读成"环境里没有检查器"）；
    - `looked` 是"找过哪些地方"的人话，给 `reason` 用（"环境没有 X"只在覆盖面内成立，
      所以必须写清楚覆盖面）。

    取值顺序 = 唯一口径（:mod:`agentflow.settings` 逐字写着）：
    环境变量 > 设置文件 > 内置默认/自动探测。
    """
    src = _env(env)
    var = ENV_VERIFIER_BINS.get(name, "")
    looked: list[str] = []
    problem = ""
    if var:
        looked.append(var)
        raw = (src.get(var) or "").strip()
        if raw:
            found, kind, why = _probe_one_path(name, raw)
            if found:
                return {"name": name, "path": found,
                        "source": "explicit" if kind == "file" else "explicit_dir",
                        "problem": "", "looked": "、".join(looked)}
            problem = f"{var}={why}"
    setting_key = SETTING_KEYS.get(name, "")
    if setting_key:
        setting_raw = SET.toolchain_settings(env=env).get(setting_key, "")
        looked.append(f"{SET.DEFAULT_SETTINGS_REL}:toolchain.{setting_key}")
        if setting_raw:
            found, kind, why = _probe_one_path(name, setting_raw)
            if found:
                return {"name": name, "path": found,
                        "source": "settings" if kind == "file" else "settings_dir",
                        "problem": "", "looked": "、".join(looked)}
            if not problem:
                problem = f"设置文件 {SET.DEFAULT_SETTINGS_REL} 的 toolchain.{setting_key}={why}"
    looked.append(ENV_PROVER_PATH)
    for one in (src.get(ENV_PROVER_PATH) or "").split(os.pathsep):
        one = one.strip()
        if not one:
            continue
        found = shutil.which(name, path=one)
        if found:
            return {"name": name, "path": str(found), "source": "prover_path",
                    "problem": "", "looked": "、".join(looked)}
    looked.append("PATH")
    try:
        found = shutil.which(name)
    except Exception as exc:  # noqa: BLE001 - PATH 不可读等
        return {"name": name, "path": "", "source": "", "looked": "、".join(looked),
                "problem": (problem + "；" if problem else "")
                           + f"which 失败（{type(exc).__name__}: {exc}）"}
    if found:
        return {"name": name, "path": str(found), "source": "path",
                "problem": "", "looked": "、".join(looked)}
    return {"name": name, "path": "", "source": "", "problem": problem,
            "looked": "、".join(looked)}


def _version_of(exe: str, name: str) -> tuple[str, str]:
    """跑那个检查器的报版本命令。返回 `(版本行, 问题)` —— 起不来就算问题（三态里的没查成）。

    业主 2026-10-27 第一条裁定：起程序就登记一条程序计时器，程序结束它返回。
    """
    cmd = VERSION_COMMANDS.get(name, f"{name} --version").split()
    argv = [exe, *cmd[1:]]
    try:
        from . import clock as _CLK

        with _CLK.program_span(program=exe, argv=argv,
                               workspace=(_CLK.current_workspace() or None),
                               where="toolchain._version_of",
                               purpose=f"问 {name} 的版本（等它回话）") as prog:
            r = subprocess.run(argv, capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=10)
            prog.finish(outcome="exited", exit_code=int(getattr(r, "returncode", 0) or 0))
    except Exception as exc:  # noqa: BLE001
        return "", f"{name}：版本探测失败（{type(exc).__name__}: {exc}）"
    text = (r.stdout or r.stderr or "").strip()
    return (text.splitlines()[0] if text else ""), ""


def probe_checkers(env: Mapping[str, str] | None = None) -> dict[str, Any]:
    """探测这台机器上有哪些检查器（三态：有没有 / 没查成 / 找过哪里）。

    返回的键与 `tools/verify_tools.detect_verifier` 逐字一致
    （`checked` / `available` / `available_names` / `reason` / `probe_errors`），
    另外多两把「给人读」的键：`looked_in`（找过哪些地方）与 `sources`（每个找到的是从哪一档来的）。
    多出来的键是纯增量的：转发方（`detect_verifier`）原样返回，旧调用方不受影响。
    """
    out: list[dict[str, Any]] = []
    probe_errors: list[str] = []
    looked_in: list[str] = []
    for name in CHECKERS:
        found = resolve_checker(name, env)
        looked_in.append(f"{name}: " + found["looked"])
        if found["problem"]:
            probe_errors.append(f"{name}：{found['problem']}")
        if not found["path"]:
            continue
        ver, problem = _version_of(found["path"], name)
        if problem:
            # 二进制在（这个事实仍记进 available），但"探测完成"不成立 ⇒ checked=False。
            probe_errors.append(problem)
        out.append({"name": name, "path": found["path"], "version": ver,
                    "source": found["source"]})
    checked = not probe_errors
    names = [row["name"] for row in out]
    if not checked:
        reason = "探测没做成（" + "；".join(probe_errors) + "）⇒ 不知道环境里有没有检查器"
    elif out:
        reason = f"探测到 {len(out)} 个证明检查器：" + "、".join(names)
    else:
        reason = ("探测完成：找过 " + "；".join(looked_in)
                  + " —— 环境里没有任何受支持的证明检查器 ⇒ 本环境无法产出 proof 级证据")
    return {"checked": checked, "available": out, "available_names": names,
            "probe_errors": probe_errors, "reason": reason,
            "looked_in": looked_in, "sources": {r["name"]: r["source"] for r in out}}


def lean_path_for(root: str | Path) -> str:
    """Mathlib 工程根 → 编译 `import Mathlib` 需要的 `LEAN_PATH`。

    ## 为什么要由框架来拼（`draft/37` §101 的真机读数）

    `formalgw.check_lean` 起检查器的命令是裸的 `[lean, <file>]` —— 它靠进程环境里的
    `LEAN_PATH` 找包。于是"Mathlib 装好了"与"`import Mathlib` 能不能编过"是两件事：
    2026-10-04 实测，盘上有一份编译完整的 Mathlib（工程根由设置文件或
    `AGENTFLOW_MATHLIB_ROOT` 给出来，umbrella `Mathlib.olean` 在、4095 个 olean 在），
    而 E 的每一次形式化尝试都报 `unknown package 'Mathlib'` —— 差的就是这一串
    `LEAN_PATH`。

    ## 布局只认两处（4.7.0 与 4.9+ 各一种）

    `<root>/.lake/build/lib`（Lean 4.7 时代）与 `<root>/.lake/build/lib/lean`（4.9+），
    外加每个依赖包（`<root>/.lake/packages/*`）的同样两种。只取存在的：
    拼进一个不存在的目录不会报错，只会让"路径拼错了"和"包没编"长得一样。
    """
    base = Path(str(root))
    parts: list[Path] = []
    for sub in (Path(".lake") / "build" / "lib", Path(".lake") / "build" / "lib" / "lean"):
        parts.append(base / sub)
    pkgs = base / ".lake" / "packages"
    if pkgs.is_dir():
        for pkg in sorted(pkgs.iterdir()):
            for sub in (Path(".lake") / "build" / "lib", Path(".lake") / "build" / "lib" / "lean"):
                parts.append(pkg / sub)
    return os.pathsep.join(str(p) for p in parts if p.is_dir())


#: 第 ⑤ 步的检查器原文里"缺哪个包"的那一句（`unknown package 'Std'`）。
_MISSING_PACKAGE = re.compile(r"unknown package '([^']+)'")


def _missing_imports_of(*texts: Any) -> list[str]:
    """从检查器原文里抠出"缺的包"（只认原文里真的出现过的那几个名字）。

    为什么从这里读、不另问一次：改前这条信息来自那次 umbrella 探针自己的返回值。
    现在只有第 ⑤ 步那一次编译（`leantoolchain.mathlib_reading` 的 `evidence`），
    所以"缺哪个包"也只能从那条原文里读 —— 两处各读一份，就又是两个答案。
    """
    out: list[str] = []
    for text in texts:
        for name in _MISSING_PACKAGE.findall(str(text or "")):
            if name and name not in out:
                out.append(name)
    return out


def _reading_problems(row: Mapping[str, Any]) -> list[str]:
    """一份第 ⑤ 步读数内部自相矛盾的地方（空清单 = 这份读数可以照用）。

    判两件事，它们是"两处各说各话"在合并成一处之后唯一还能出现的形态：

    - 结论有、而给出结论的那次编译没有：`usable` / `unusable` 只可能由一次真编译
      产生 —— `runner` 与 `exit_code` 都空，就说明这条结论没有落点；
    - `detected` 与 `root` 对不上（说检出了却没有工程根，或者反过来）。

    命中任何一条时 :func:`mathlib_state` 报"没查成"，不替这份读数挑一个说法。
    """
    state = str(row.get("state") or "")
    out: list[str] = []
    if state in ("usable", "unusable"):
        if row.get("exit_code") is None or not str(row.get("runner") or "").strip():
            out.append(f"读数自称 {state}，却没有那一次编译的读数"
                       "（runner 与 exit_code 都空）")
    detected = bool(row.get("detected"))
    root = str(row.get("root") or "")
    if detected and not root:
        out.append("读数自称 detected=True，工程根那一格却是空的")
    if root and not detected:
        out.append(f"读数给了工程根 {root}，detected 却是 False")
    return out


def _graph_import_verdict(row: Mapping[str, Any], *, enabled: bool,
                          problems: Sequence[str]) -> str:
    """第 ⑤ 步那一格的人话（三态：可用 / 不可用 / 没查成，外加两档"没查"）。"""
    from . import leantoolchain as LT

    module = str(getattr(LT, "MATHLIB_GRAPH_MODULE", "Mathlib"))
    if not enabled:
        # 开关关着时连探针都不跑：这一档必须与"探了、编译失败"分开说 —— 后者会让人去查
        # junction / 缺包（一条真实的排障路），而这一次该看的是设置文件里的开关。
        return ("没查（本会话的 Lean 形式化关着 ⇒ 第 ⑤ 步那条探针一次都没跑）—— "
                "这不是「Mathlib 坏了」，也不是「没装」")
    if problems:
        return ("没查成（第 ⑤ 步那条读数自相矛盾，不替它挑一个说法）："
                + "；".join(str(p) for p in problems))
    state = str(row.get("state") or "")
    if state == "usable":
        secs = row.get("elapsed_ms")
        secs_text = f"，{float(secs) / 1000.0:.1f}s" if isinstance(secs, (int, float)) and secs else ""
        return (f"可用（实测：`import {module}` + `#check SimpleGraph` 以 0 退出"
                f"{secs_text}；跑法 {row.get('runner') or '（空）'}）")
    if state == "unusable":
        missing = _missing_imports_of(row.get("evidence"), row.get("output_head"),
                                      row.get("reason"))
        return ("不可用（实测编译失败"
                + (f"，缺的包：{'、'.join(missing)}" if missing else "")
                + f"；检查器原文：{_head_text(row.get('evidence') or row.get('output_head'))}"
                  "）—— 这是环境问题，不是命题问题：先看 `toolchain.mathlib_root` 指的那份"
                  "工程里依赖包（`std` 等）的 `.lake/build/lib` 在不在"
                  "（搬过目录的 junction 会悬空）")
    if state == "absent":
        return (f"没查（这台机器上没有 Mathlib 工程根 {module} 无从谈起）⇒ 第 ⑤ 步退回"
                "裸 lean 跑；这是「没有库」，不是「检查器坏了」")
    return ("没查成（第 ⑤ 步没给结论："
            + str(row.get("reason") or "没给理由") + "）")


def _head_text(value: Any) -> str:
    """一格原文的头一段（空值也给一句可读的话，不留空白）。"""
    text = str(value or "").strip()
    if not text:
        return "（空输出）"
    first = text.splitlines()[0].strip()
    return first if len(first) <= 160 else first[:160] + "…"


def _probe_from_reading(row: Mapping[str, Any], *, enabled: bool,
                        problems: Sequence[str]) -> dict[str, Any]:
    """把第 ⑤ 步那条读数翻成既有那一格 `import_mathlib_probe` 的形状。

    形状逐字保留（`checked` / `verified` / `status` / `reason` / `missing_imports` /
    `elapsed_sec` / `exit_code`）：`agent_prompts.toolchain_formal_text` 按它分三档
    （可用 ⇒ 显式传 imports；不可用 ⇒ 自足文件；没查成 ⇒ 自足文件 + 写进 notes）。
    """
    if not enabled:
        return {"checked": True, "verified": False, "status": "lean_disabled",
                "reason": ("本会话的 Lean 形式化已关闭（toolchain.lean_enabled=false 或 "
                           "AGENTFLOW_LEAN_ENABLED=0）⇒ 不跑第 ⑤ 步那条探针："
                           "这是「没查」不是「不可用」"),
                "missing_imports": [], "elapsed_sec": None, "exit_code": None}
    if problems:
        return {"checked": False, "verified": None, "status": "reading_inconsistent",
                "reason": "读数自相矛盾 ⇒ 没查成：" + "；".join(str(p) for p in problems),
                "missing_imports": [], "elapsed_sec": None, "exit_code": None}
    state = str(row.get("state") or "")
    secs = row.get("elapsed_ms")
    return {
        "checked": state in ("usable", "unusable", "absent"),
        "verified": state == "usable",
        "status": state or "unknown",
        "reason": str(row.get("reason") or ""),
        "missing_imports": _missing_imports_of(row.get("evidence"), row.get("output_head"),
                                               row.get("reason")),
        "elapsed_sec": (float(secs) / 1000.0
                        if isinstance(secs, (int, float)) and secs else None),
        "exit_code": row.get("exit_code"),
    }


def mathlib_state(env: Mapping[str, str] | None = None, *,
                  reading: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Mathlib 那一轴的状态：第 ⑤ 步那条读数的一处投影。

    ## 为什么改前是两处探测，现在是这一处（2026-10-25 合并）

    改前这一格自己有一套探测：`formalgw.find_mathlib_root` 找工程根、自己认两种
    umbrella 布局、再真编译一次 `import Mathlib` + `norm_num`（`_import_mathlib_probe`，
    超时 180 秒）。而自检的第 ⑤ 步另有一套：`leantoolchain.mathlib_reading` 读盘面
    加一次 `import Mathlib.Combinatorics.SimpleGraph.Basic` + `#check SimpleGraph` 的真编译。
    两套探的是同一件事，却可以给出两个答案 —— 2026-10-08 的现场就是文件面说可用、
    真编译报 `unknown package 'Std'`；两处读数分家时，读的人分不清该信哪一个，
    而 `agentflow doctor` 为此要编译两次（本机实测：umbrella 那一次 18.9 秒、
    第 ⑤ 步那一次 12.4 秒）。

    所以本函数现在只做一件事：把第 ⑤ 步那条读数（`leantoolchain.mathlib_reading`，
    结论由 `leantoolchain._mathlib_control` 那一次真编译给出）投影成既有那几个键，
    一格都不自己量。`reading=` 让调用方把已经跑过的那一份传进来 —— doctor 把自检读数里
    的 `mathlib` 那一格直接给它，于是整趟只编译一次；不给就现读盘面（纯读，不起进程）。

    第 ⑤ 步读数内部自相矛盾时（结论有、而给出结论的那次编译没有），这一格报"没查成"，
    不替它挑一个说法 —— 那正是"两处各说各话"在合并之后唯一还能出现的形态。

    ## 键的口径

    - `import_mathlib`：文件面读数（umbrella 的 `.olean` 在不在）。历史口径，逐字保留：
      既有判据与文档都读它，但它不单独代表"可用"；
    - `import_mathlib_probe` / `import_mathlib_measured` / `graph_import_measured`：
      实测读数。三格同源 —— 本机只跑第 ⑤ 步那一次编译，所以"umbrella 实测"与
      "图论实测"是同一份读数（拆成两次编译就是改前那个毛病）。
    """
    from . import formalgw as FG
    from . import leantoolchain as LT

    row = dict(reading) if reading is not None else LT.mathlib_reading(env=env)
    problems = _reading_problems(row)
    enabled = bool(lean_enabled(env)[0])
    root = str(row.get("root") or "")
    umbrella = str(row.get("umbrella_olean") or "")
    rev: dict[str, Any] = FG.mathlib_revision(Path(root)) if root else {}
    pinned_commit = str(getattr(FG, "PINNED_MATHLIB_COMMIT", "") or "")
    pinned_tag = str(getattr(FG, "PINNED_MATHLIB_TAG", "") or "")
    got_commit = str(rev.get("commit") or "")
    same = bool(got_commit) and (got_commit == pinned_commit
                                 or got_commit.startswith(pinned_commit[:12]))
    measured = _graph_import_verdict(row, enabled=enabled, problems=problems)
    if not root:
        reason = str(row.get("reason") or "") or ("没找到 Mathlib 工程根"
                                                 "（看 AGENTFLOW_MATHLIB_ROOT 与常见位置）")
    elif problems:
        reason = "没查成（第 ⑤ 步那条读数自相矛盾）：" + "；".join(problems)
    else:
        reason = str(row.get("reason") or "")
    return {
        "checked": (not problems) and bool(row.get("checked")),
        "state": "unknown" if problems else (str(row.get("state") or "") or "unknown"),
        "detected": bool(row.get("detected")),
        "root": root,
        "source": str(rev.get("source") or ""),
        "reason": reason,
        #: 第 ⑤ 步那条读数是从哪一档找到工程根的（`flag` / `settings` / `env` / ...）。
        "reading_source": str(row.get("source") or ""),
        "version": str(row.get("version") or ""),
        "commit": got_commit, "tag": str(rev.get("tag") or ""),
        "pinned_commit": pinned_commit, "pinned_tag": pinned_tag, "pinned_match": same,
        "umbrella_olean": umbrella,
        "graph_olean": str(row.get("graph_olean") or ""),
        "lean_path": str(row.get("lean_path") or ""),
        "lean_path_segments": int(row.get("lean_path_segments") or 0),
        #: 文件面读数（历史口径，逐字保留：既有判据与文档都读它）。
        "import_mathlib": ("可用（umbrella 的 .olean 在；`LEAN_PATH` 用 lean_path 这一串，"
                           "检查器起子进程时要带上它）" if umbrella else
                           "不可用（两种布局都没找到 umbrella 的 .olean ⇒ import Mathlib 会报 "
                           "import_unavailable；处置是编全 Mathlib 或只 import 缓存里有的模块）"),
        #: 实测读数：第 ⑤ 步那一次真编译（同一份读数，不是第二次探测）。
        "import_mathlib_probe": _probe_from_reading(row, enabled=enabled, problems=problems),
        "import_mathlib_measured": measured,
        #: 图论那一格（`import Mathlib.Combinatorics.SimpleGraph.Basic`）的实测结论。
        "graph_import_measured": measured,
    }


def lean_enabled(env: Mapping[str, str] | None = None) -> tuple[bool, str]:
    """这一趟要不要走 Lean 形式化（业主 2026-10-12 的开关）。返回 `(值, 来源)`。

    实现在 `settings.lean_enabled`（取值梯子只有一处：环境变量
    `AGENTFLOW_LEAN_ENABLED` > 设置文件 `toolchain.lean_enabled` > 缺省 `True`）。
    本函数只是把它接到工具链这一层的读面上 —— 于是"模型看得见的 TOOLCHAIN_FACTS"、
    `agentflow doctor`、`formalgw.check_lean` 三处读的是同一个答案，
    不存在"一处说关着一处说开着"。
    """
    return SET.lean_enabled(env=env)


def formal_mode(env: Mapping[str, str] | None = None) -> str:
    """这一趟的证明路线：`"formal"`（默认）或 `"prose_review"`（开关关掉时）。"""
    enabled, _ = lean_enabled(env)
    return "formal" if enabled else "prose_review"


def _model_spec(env: Mapping[str, str] | None = None) -> Any:
    """模型那一格的读数（取值口仍是 `modelgw.spec_from_env`，口径只有一处）。

    为什么不在这里重写一遍那几个环境变量名：key 的取值口径只能有一处
    （`modelgw`），两处各写一份的话，"doctor 说有 key、网关说没有"是可能的，
    而那种漂移没有任何一条判据看得见。

    设置文件坏了不在这里吞掉：解析错就是解析错（`json.JSONDecodeError`
    带着文件路径与行列号抛出来）—— 把"文件坏了"折成"没配 key"，
    正是本项目最忌的那种静默折叠。
    """
    from . import modelgw as MG

    return MG.spec_from_env(env)


def toolchain_report(env: Mapping[str, str] | None = None, *,
                     mathlib_reading: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """跑一趟形式化核验之前该看的那几个事实（给 `agentflow doctor` 用）。

    只回答"这台机器能做什么"，「不发起任何模型调用」（它不花钱）。
    `model_key` 那一格只看「有没有配」，绝不打印值 —— 而且"配没配"要看
    环境变量与设置文件两档（2026-10-07 起 key 也可以落在 `settings.json` 里，
    那么这一格只读 key 的环境变量就会报"没配"，与真实情况相反）。

    `mathlib_reading` 是"已经跑过的那一份第 ⑤ 步读数"（doctor 把自检读数里的
    `mathlib` 那一格传进来）：给了它就一格都不再探，整趟只编译一次；不给则现读盘面。
    """
    spec = _model_spec(env)
    probe = probe_checkers(env)
    lean = next((r for r in probe["available"] if r["name"] == "lean"), None)
    enabled, enabled_src = lean_enabled(env)
    return {
        "model": {"key_present": bool(spec.api_key),
                  "base_url": spec.base_url,
                  "model": spec.model},
        "provers": probe,
        #: 用户设的那个开关（业主 2026-10-12）：`False` ⇒ 全流程不做 Lean 形式化。
        #: 它与下面 `lean_ready`（探测读数）是两条独立的事实：
        #: "机器上装了 Lean"不等于"这一趟允许用它"，反过来"关掉了"也不等于"没装"。
        #: 折叠这两件事的症状是：关掉开关的用户被报成"环境里没有检查器"，
        #: 于是他会去查环境，而真正该看的是设置文件。
        "lean_enabled": enabled,
        "lean_enabled_source": enabled_src,
        "formal_mode": formal_mode(env),
        "lean_ready": bool(lean),
        "can_do_formal": bool(lean) and enabled,
        "lean_path": (lean or {}).get("path", ""),
        "lean_version": (lean or {}).get("version", ""),
        "mathlib": mathlib_state(env, reading=mathlib_reading),
        # 2026-10-17（Lean 审计 #1）：原来这里还有一行 `"can_do_formal": bool(lean)`
        # 重复键覆盖了上面那行 —— 于是关掉 Lean 的机器上 `doctor` 仍说"能做形式化核验"。
        # 已删：能不能做 = 装了 且 开关开着（上面 456 行那一条是唯一口径）。
    }

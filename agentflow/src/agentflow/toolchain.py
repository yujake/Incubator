# -*- coding: utf-8 -*-
"""这台机器上的证明工具链：在哪、哪一版、能不能用 —— 「一处定义」。

## 为什么要有这一层（2026-10-03 的现场）

`tools/verify_tools.py`（探测）与 `formalgw.py`（调用）此前「各自」 `shutil.which("lean")`
—— 两处独立地"看 PATH"。这带来两个后果，那天都实测到了：

1. 「同一台机器上"探测说没有、调用却真能跑"是可能的」（两处的口径各写一份，本可以漂）。
   实测：Lean 4.7.0 就装在 `D:\\Incubator\\temp\\lean470\\lean-4.7.0-windows\\bin`，
   而 `detect_verifier()` 报 `available=[]`（PATH 上没有它）。
2. 「能力静默降级」：探测说"没有检查器" ⇒ 形式化那一条腿改成 `cross_check`，
   报告里只剩一句"没核到"，而「没有任何地方会说"这台机器其实能做"」。
   用户的原话是"这是坏的" —— 坏的正是这种"看不出来"。

所以本层的职责只有一件事：把「这台机器能做形式化核验吗」变成一个「可读、可判据、三态」的读数，
并让「探测与调用共用同一个答案」（谁都不许再自己 `which` 一次）。

## 查找顺序（每一档都留下"是从哪找到的"）

1. 「显式配置」：`AGENTFLOW_LEAN_BIN` / `AGENTFLOW_COQ_BIN` / `AGENTFLOW_ISABELLE_BIN`
   —— 取值可以是「可执行文件」本身，也可以是「它所在的目录」（"指向安装目录"是人最自然的写法）；
2. 「`AGENTFLOW_PROVER_PATH`」：一个或多个目录（Windows 用 `;`、POSIX 用 `:` 分隔）；
3. 「PATH」（`shutil.which`）。

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
import shutil
import subprocess
from pathlib import Path
from typing import Any, Mapping, Sequence

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


def _env(env: Mapping[str, str] | None) -> dict[str, str]:
    """读环境变量（给了 `env` 就用它，否则读 `os.environ`）—— 便于判据注入。"""
    return dict(os.environ if env is None else env)


def resolve_checker(name: str, env: Mapping[str, str] | None = None) -> dict[str, Any]:
    """一个检查器在哪、是从哪一档找到的、有没有配置问题。「不跑版本命令」。

    返回 `{"name", "path", "source", "problem", "looked"}`：

    - `path` 找到时的绝对路径，找不到是空串；
    - `source` 取值 `"explicit"`（显式变量指到文件）/ `"explicit_dir"`（指到目录）/
      `"prover_path"`（`AGENTFLOW_PROVER_PATH`）/ `"path"`（PATH）/ `""`（没找到）；
    - `problem` 非空表示「这一档配了却不能用」（例如路径不存在）—— 它与"没配"是两件事；
    - `looked` 是"找过哪些地方"的人话，给 `reason` 用（"环境没有 X"只在覆盖面内成立，
      所以必须写清楚覆盖面）。
    """
    src = _env(env)
    var = ENV_VERIFIER_BINS.get(name, "")
    looked: list[str] = []
    problem = ""
    if var:
        looked.append(var)
        raw = (src.get(var) or "").strip()
        if raw:
            p = Path(raw)
            if p.is_file():
                return {"name": name, "path": str(p), "source": "explicit",
                        "problem": "", "looked": "、".join(looked)}
            if p.is_dir():
                found = shutil.which(name, path=str(p))
                if found:
                    return {"name": name, "path": str(found), "source": "explicit_dir",
                            "problem": "", "looked": "、".join(looked)}
                problem = f"{var}={raw} 是目录，但里面没有 {name}"
            else:
                problem = f"{var}={raw} 不存在"
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
    """跑那个检查器的报版本命令。返回 `(版本行, 问题)` —— 起不来就算问题（三态里的没查成）。"""
    cmd = VERSION_COMMANDS.get(name, f"{name} --version").split()
    try:
        r = subprocess.run([exe, *cmd[1:]], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=10)
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


def mathlib_state(env: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Mathlib 那一轴的状态（三态）：工程根在不在、revision 与钉住的是否一致。

    为什么要单列：`import Mathlib` 能不能用，取决于「工程根 + 那一份编好的缓存」，
    与"有没有 lean 这个二进制"是两件事。实测 2026-10-03：根在、revision 与钉住的一致，
    但 umbrella 的 `.olean` 不在缓存里 ⇒ `import Mathlib` 报 `import_unavailable`。
    """
    from . import formalgw as FG

    root = FG.find_mathlib_root(env)
    if not root:
        return {"checked": True, "root": "", "reason": "没找到 Mathlib 工程根"
                                                      "（看 AGENTFLOW_MATHLIB_ROOT 与常见位置）"}
    rev = FG.mathlib_revision(Path(root))
    pinned_commit = str(getattr(FG, "PINNED_MATHLIB_COMMIT", "") or "")
    pinned_tag = str(getattr(FG, "PINNED_MATHLIB_TAG", "") or "")
    got_commit = str(rev.get("commit") or "")
    same = bool(got_commit) and (got_commit == pinned_commit
                                 or got_commit.startswith(pinned_commit[:12]))
    umbrella = Path(root) / ".lake" / "build" / "lib" / "lean" / "Mathlib.olean"
    return {"checked": True, "root": root, "commit": got_commit, "tag": str(rev.get("tag") or ""),
            "source": str(rev.get("source") or ""), "reason": str(rev.get("reason") or ""),
            "pinned_commit": pinned_commit, "pinned_tag": pinned_tag, "pinned_match": same,
            "umbrella_olean": str(umbrella) if umbrella.is_file() else "",
            "import_mathlib": ("可用" if umbrella.is_file() else
                               "不可用（umbrella 的 .olean 不在缓存里 ⇒ import Mathlib 会报 "
                               "import_unavailable；处置是编全 Mathlib 或只 import 缓存里有的模块）")}


def toolchain_report(env: Mapping[str, str] | None = None) -> dict[str, Any]:
    """跑一趟形式化核验之前该看的那几个事实（给 `agentflow doctor` 用）。

    只回答"这台机器能做什么"，「不发起任何模型调用」（它不花钱）。
    `model_key` 那一格只看「有没有配」，绝不打印值。
    """
    src = _env(env)
    key = (src.get("AGENTFLOW_MODEL_API_KEY") or "").strip()
    probe = probe_checkers(env)
    lean = next((r for r in probe["available"] if r["name"] == "lean"), None)
    return {
        "model": {"key_present": bool(key),
                  "base_url": src.get("AGENTFLOW_MODEL_BASE_URL") or "（缺省）",
                  "model": src.get("AGENTFLOW_MODEL_NAME") or "（缺省）"},
        "provers": probe,
        "lean_ready": bool(lean),
        "lean_path": (lean or {}).get("path", ""),
        "lean_version": (lean or {}).get("version", ""),
        "mathlib": mathlib_state(env),
        "can_do_formal": bool(lean),
    }

# -*- coding: utf-8 -*-
"""前端发布步：类型检查 + 构建 + 产物新鲜度（裁定 G2 / B1 的落点）。

## 三态（每条退出码都有出处，不是"非零就算红"）

```text 0 = pass       三件事都查过了：typecheck 过、构建过、构建结果与入库的 dist 逐字节相同1 = fail       查过了，有问题：类型检查报错 / 构建报错 / 构建结果与入库产物不一致2 = unknown    没查成：本机没有 node/pnpm，或构建环境起不来（例如沙箱不允许 Node用管道 stdio 起 esbuild ⇒ `spawn EPERM`）```

`unknown` 绝不是 `pass`：这是本项目反复踩的坑（`unknown` 被折成绿灯），所以"没装 node"这条路的退出码是 2，编排层（`tools/release_all.py`）会照实记 `unknown`。

## 为什么"新鲜度"要靠重新构建一次来判

`agentflow/src/agentflow/web/static/` 是入库的构建产物（裁定 B1：产物必须能被全新 clone 直接读到）。既然入库，它就会与源码脱节 —— 改了 `ui/src/` 而忘了重建，
判据必须能红。唯一可靠的判法就是"现在构建一次，与入库的那份比字节"：构建到临时目录（不改仓库状态），再与 `static/` 逐文件比（多一个/少一个/内容不同都算）；
- 相同 ⇒ pass；不同 ⇒ fail 并打印差异清单（谁多了、谁少了、谁内容不同）。

## 为什么 typecheck 与 build 都要跑

`tsc --noEmit` 抓的是类型层（组件 props 不匹配这类），`vite build` 抓的是打包层（入口引用不存在、资源缺失）—— 实测过：typecheck 过而 build 炸是可能的（反之亦然），
所以两步都要有，且两步都在同一条退出码语义下。
"""

from __future__ import annotations

import argparse
import hashlib
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
from typing import Sequence

#: 项目根（`tools/` 的上一级）。
ROOT = pathlib.Path(__file__).resolve().parents[1]
UI = ROOT / "ui"
#: 入库的产物落点（`ui/vite.config.ts` 的 `outDir`；裁定 B1）。
STATIC = ROOT / "src" / "agentflow" / "web" / "static"

#: 构建环境起不来时输出里会出现这些字样 ⇒ 记 `unknown` 而不是 `fail`。
#: `EPERM` 那条是本机实测的：本沙箱不允许 Node 用管道 stdio 起子进程，
#: esbuild 的服务协议走管道 ⇒ `spawn EPERM`（而 `esbuild.exe --version` 是好的）。
ENV_BROKEN_MARKERS = (
    "spawn EPERM",
    "EPERM",
    "ERR_PNPM_IGNORED_BUILDS",
    "EACCES",
    "command not found",
    "is not recognized as an internal or external command",
)


def _which_pnpm() -> str | None:
    """找 pnpm（Windows 上是 `pnpm.cmd`）。找不到返回 None ⇒ 本步 unknown。"""
    for name in ("pnpm", "pnpm.cmd", "pnpm.exe"):
        found = shutil.which(name)
        if found:
            return found
    return None


def _run(argv: Sequence[str], cwd: pathlib.Path,
         timeout: int) -> tuple[int, str]:
    """跑一条命令：返回 `(退出码, 合并输出)`；起不来返回 `(-1, 原因)`。"""
    env = dict(os.environ)
    env.setdefault("PYTHONIOENCODING", "utf-8")
    try:
        proc = subprocess.run(list(argv), cwd=str(cwd), env=env, timeout=timeout,
                              capture_output=True, text=True, encoding="utf-8",
                              errors="replace")
    except (OSError, subprocess.TimeoutExpired) as exc:
        return -1, f"{type(exc).__name__}: {exc}"
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def _tree(root: pathlib.Path) -> dict[str, str]:
    """一棵树的 `相对路径 -> sha256`（不存在 ⇒ 空表）。"""
    out: dict[str, str] = {}
    if not root.is_dir():
        return out
    for path in sorted(root.rglob("*")):
        if path.is_file():
            out[path.relative_to(root).as_posix()] = hashlib.sha256(
                path.read_bytes()).hexdigest()
    return out


def _tree_diff(committed: dict[str, str], built: dict[str, str]) -> list[str]:
    """入库产物 vs 刚构建出来的产物：逐条列出差异（人话）。"""
    rows: list[str] = []
    for rel in sorted(set(committed) - set(built)):
        rows.append(f"入库有、构建没有：{rel}（源码删了？）")
    for rel in sorted(set(built) - set(committed)):
        rows.append(f"构建有、入库没有：{rel}（改了前端没重建？）")
    for rel in sorted(set(committed) & set(built)):
        if committed[rel] != built[rel]:
            rows.append(f"内容不同：{rel}")
    return rows


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python tools/frontend_gate.py",
        description="前端发布步：typecheck + build + 产物新鲜度（0=pass / 1=fail / 2=unknown）")
    ap.add_argument("--timeout", type=int, default=600, help="每一步的超时秒数（默认 600）")
    ap.add_argument("--skip-typecheck", action="store_true",
                    help="只查构建与新鲜度（调试用；发布门不传它）")
    args = ap.parse_args(list(argv) if argv is not None else None)

    pnpm = _which_pnpm()
    if pnpm is None or not (UI / "package.json").is_file():
        print("[frontend_gate] unknown：本机没有 pnpm，或 ui/package.json 不在盘上 "
              f"（pnpm={pnpm!r}）—— 这一步记 unknown，不是 pass")
        return 2

    if not args.skip_typecheck:
        code, out = _run([pnpm, "-C", str(UI), "typecheck"], ROOT, args.timeout)
        if code == -1 or (code != 0 and any(m in out for m in ENV_BROKEN_MARKERS)):
            print(f"[frontend_gate] unknown：typecheck 没跑成（退出码 {code}）：\n{out[-2000:]}")
            return 2
        if code != 0:
            print(f"[frontend_gate] fail：typecheck 报了问题（退出码 {code}）：\n{out[-4000:]}")
            return 1
        print("[frontend_gate] typecheck：pass")

    tmp = pathlib.Path(tempfile.mkdtemp(prefix="frontend-gate-"))
    try:
        # 构建到临时目录：不改仓库状态（与 `X-1` 同一条口径）。
        code, out = _run([pnpm, "-C", str(UI), "exec", "vite", "build",
                          "--outDir", str(tmp), "--emptyOutDir"], ROOT, args.timeout)
        if code == -1 or (code != 0 and any(m in out for m in ENV_BROKEN_MARKERS)):
            print(f"[frontend_gate] unknown：构建没跑成（退出码 {code}）：\n{out[-2000:]}")
            return 2
        if code != 0:
            print(f"[frontend_gate] fail：构建失败（退出码 {code}）：\n{out[-4000:]}")
            return 1
        print("[frontend_gate] build：pass")
        rows = _tree_diff(_tree(STATIC), _tree(tmp))
        if not rows:
            print(f"[frontend_gate] 新鲜度：pass（入库产物 {len(_tree(STATIC))} 个文件与"
                  "刚构建的结果逐字节相同）")
            return 0
        print("[frontend_gate] fail：入库的前端产物与刚构建的结果不一致 —— "
              "改了前端就要重建并提交（裁定 B1）：")
        for row in rows:
            print("  " + row)
        return 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())

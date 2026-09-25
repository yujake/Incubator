#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""**一键发布检查** —— 把正式版要求的全部门串成一条命令，并做三态汇总。

## 为什么需要它（而不是"照文档手敲六条命令"）

用户对正式版的要求逐字是：

> **"建立一键发布检查（release check：全量测试 + 全部自检 + 验收测试 + verify + 工具普查 + linter）"**

`scripts/release_check.py` 覆盖了其中**五项**（全量测试 / 全部自检 / verify / 工具普查 / linter），
但**没有验收测试**这一项。两份东西合起来才等于用户点名的清单，而"照文档手敲六条命令"
是发布流程里最容易被跳过的一步 —— **手敲的清单没有退出码，于是"少跑了一条"与"跑了都过了"
在任何自动化里长得一模一样**（本项目 `draft/17` §6.3 的教训逐字：
*"多数脚本不设退出码，于是『未报错』被误读为『无问题』"*）。

## 三态汇总（**`unknown` 绝不是 `pass`**）

每一步都只有三种结论，与全项目的口径一致：

- ``pass``    —— 跑了，退出码 0；
- ``fail``    —— 跑了，退出码非 0（**并且**不是"没跑成"）；
- ``unknown`` —— **没跑成**：解释器都起不来、超时、取消、可执行文件不存在。

总判定：**任一 `fail` ⇒ `fail`；否则任一 `unknown` ⇒ `unknown`；全 `pass` ⇒ `pass`。**
退出码同样三档（0/1/2）。把 `unknown` 当 `pass` 是本项目反复踩过的坑，
所以它单独占一档 —— 哪怕这样让"发布门全绿"更难达到。

## 为什么它不在 `scripts/release_check.py` 里

`scripts/release_check.py` 命中 FC-27 禁 AI 区（`.noai-paths` 的 `release-deploy` 类），
**给它加一项要人审**（`docs/PROPOSALS.md` 的 **P-11**）。
所以本脚本是**并列的编排层**：它**调用**那个门，**不修改**它，也**不放松**它 ——
它只增加检查、不减少检查。本脚本自身也已登记进禁改区（发布门的一部分）。

## 用法

    python tools/release_all.py                 # 全跑（约 10~15 分钟）
    python tools/release_all.py --json r.json
    python tools/release_all.py --skip acceptance        # 只跑不用联网/不耗时的部分
    python tools/release_all.py --only lint,role-specs   # 只跑指定步骤（调试用）
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

# --------------------------------------------------------------------------- 三态

VERDICT_EXIT = {"pass": 0, "fail": 1, "unknown": 2}


@dataclass
class Step:
    """一个发布检查步骤。`argv` 是**完整命令**（含解释器），不经过 shell。"""

    key: str
    title: str
    argv: list[str]
    cwd: Path
    env: dict[str, str] = field(default_factory=dict)
    #: 该步骤**预期**耗时（秒），只用于打印，不参与判定 ——
    #: 用一个估算值去判超时会造出"机器慢就红"的假报警（`DEVELOPMENT.md` §5.5）。
    expect_seconds: int = 60
    #: **该步骤自己的退出码语义**：退出码 → 三态结论。
    #:
    #: ⚠️ **这是本编排层最容易写错的一处，而第一版就写错了**：
    #: 它当时把所有非零退出码一律判成 `fail`，于是 `scripts/release_check.py`
    #: 返回 **2**（它自己的"**没查成**"档）时，编排层报的是 `fail` ——
    #: **把"没查成"读成了"发现问题"**，正好是本项目三态纪律要挡的那件事，
    #: 而且发生在"用来挡住这类错误的那一层"里。
    #:
    #: 所以每一步都必须**显式声明**自己的码表。默认只认 `0 = pass`，
    #: 其余一律 `fail`（那是普通 pytest 风格脚本的语义）。
    exit_map: dict[int, str] = field(default_factory=lambda: {0: "pass"})

    def classify_code(self, code: int) -> str:
        return self.exit_map.get(code, "fail")


#: 本项目里**自带三态**的门：`0 = 通过 / 1 = 发现问题 / 2 = 没查成`。
#: 用同一份字面量给多个步骤，避免"每处各写一遍码表"（那种写法迟早会有一处漏掉 2）。
TRI_STATE_EXIT: dict[int, str] = {0: "pass", 1: "fail", 2: "unknown"}

#: 验收 / 论文复现用的普通脚本语义：`0 = 全过`，其余 `= 有问题`。
#: ⚠️ 它们**不**是三态 —— 但它们的 docstring 里必须写清"非零 = 跑过且发现问题"，
#: 否则"脚本崩了"与"检查不通过"仍然分不开（那是它们自己的事，见各自的 README）。
PLAIN_EXIT: dict[int, str] = {0: "pass"}


@dataclass
class Result:
    step: Step
    verdict: str
    exit_code: int | None
    seconds: float
    tail: list[str]

    def to_dict(self) -> dict:
        return {
            "key": self.step.key, "title": self.step.title, "verdict": self.verdict,
            "exit_code": self.exit_code, "seconds": round(self.seconds, 1),
            "tail": self.tail, "argv": self.step.argv,
        }


def classify(exit_code: int | None, started: bool, timed_out: bool, step: Step | None = None) -> str:
    """把"跑成什么样"映射到三态。

    ⚠️ **这个函数是本脚本的核心判据**，所以它的分支顺序本身就是设计：
    `timed_out` / `started=False` **必须先于** `exit_code == 0` 判断 ——
    否则"超时被杀"会走到某一侧去（Windows 上被强杀的进程退出码常是 1，
    与"检查发现问题"的 1 无法区分）。这正是三态纪律要挡的那种静默兜底。

    退出码的解释走 `step.exit_map`（**每一步显式声明自己的码表**）——
    把"2 = 没查成"这类项目内约定留给步骤自己说，而不是在这里猜。
    """
    if not started or timed_out:
        return "unknown"
    if exit_code is None:
        return "unknown"
    if step is not None:
        return step.classify_code(exit_code)
    return "pass" if exit_code == 0 else "fail"


# --------------------------------------------------------------------------- 步骤表

ROOT = Path(__file__).resolve().parents[1]


def _env(**extra: str) -> dict[str, str]:
    return {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1", **extra}


def build_steps(root: Path, acceptance_root: Path | None = None) -> list[Step]:
    """六项 = 用户点名的那六项，一项不多一项不少。

    `scripts/release_check.py` 一次覆盖前五项（全量测试 / 全部自检 / verify / 工具普查 / linter，
    外加禁 AI 区门 / 契约版本 / 源码树可导入三项），所以这里把它作为**一个**步骤，
    再把用户额外点名、而它没有的**验收测试**作为第二个步骤。
    另外并列两个本轮新增的**结构性门**（角色规格完整性、工具面 census 对账）。
    """
    acc = acceptance_root or (root.parent / "test" / "test2")
    return [
        Step(
            "release-check", "全量测试 + 全部自检 + verify + 工具普查 + linter + 禁 AI 区 + 契约 + 导入",
            [sys.executable, str(root / "scripts" / "release_check.py")],
            cwd=root, env=_env(), expect_seconds=300,
            # ⚠️ **`release_check.py` 自带三态**：`0=pass / 1=fail / 2=unknown`。
            # 第一版漏了这一行，于是它返回 2（本环境里第 6 项禁 AI 区门**必然**是
            # `unknown`，因为这不是 git 仓库）时，编排层报的是 `fail` ——
            # "没查成"被读成"发现问题"。**必须显式声明码表。**
            exit_map=TRI_STATE_EXIT,
        ),
        Step(
            "acceptance", "验收测试（P1–P9，正式版 target=formal）",
            [sys.executable, str(acc / "run_acceptance.py"), "--clean",
             "--json", str(acc / "acceptance-run" / "acceptance-release.json")],
            cwd=acc, env=_env(AGENTFLOW_TARGET="formal"), expect_seconds=420,
            exit_map=PLAIN_EXIT,
        ),
        Step(
            "repro", "论文独立复现（5 个实验 + 7 条负控）",
            [sys.executable, str(acc / "repro" / "run_all.py"),
             "--json", str(acc / "_probe" / "runall-release.json")],
            cwd=acc / "repro", env=_env(), expect_seconds=300,
            exit_map=PLAIN_EXIT,
        ),
        Step(
            "role-specs", "角色规格结构完整性（9 节 × 8 必备子节）",
            [sys.executable, str(root / "tools" / "verify_role_specs.py")],
            cwd=root, env=_env(), expect_seconds=30,
            exit_map=TRI_STATE_EXIT,
        ),
        Step(
            "coverage", "零测试公开函数的**风险分档**清单（等级 1/2 应为 0）",
            [sys.executable, str(root / "tools" / "coverage_zero_test.py")],
            cwd=root, env=_env(), expect_seconds=60,
            exit_map=TRI_STATE_EXIT,
        ),
    ]


# --------------------------------------------------------------------------- 跑一步


def run_step(step: Step, timeout: float) -> Result:
    t0 = time.monotonic()
    started = False
    timed_out = False
    code: int | None = None
    out = ""
    try:
        started = True
        p = subprocess.run(
            step.argv, cwd=str(step.cwd), env=step.env,
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout,
        )
        code = p.returncode
        out = (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        out = (exc.stdout or "") + (exc.stderr or "") if isinstance(exc.stdout, str) else ""
    except OSError as exc:
        # 解释器不在 / 路径不对 / 目录不存在 —— **没跑成**，不是失败。
        started = False
        out = f"{type(exc).__name__}: {exc}"
    except Exception as exc:  # noqa: BLE001 —— 理由：编排层不许让**任何**异常变成"看起来没跑过"。
        # 这里兜住的是"检查器自己炸了"，它必须落进 `unknown` 而不是把整个发布门带崩；
        # 消息里带上异常类型，于是"没跑成"仍可归因。
        out = f"编排层捕获到未预期异常：{type(exc).__name__}: {exc}"
    secs = time.monotonic() - t0
    tail = [ln for ln in out.strip().splitlines() if ln.strip()][-12:]
    return Result(step, classify(code, started, timed_out, step), code, secs, tail)


def overall(results: list[Result]) -> str:
    """总判定：任一 `fail` ⇒ `fail`；否则任一 `unknown` ⇒ `unknown`；全 `pass` ⇒ `pass`。"""
    if any(r.verdict == "fail" for r in results):
        return "fail"
    if any(r.verdict == "unknown" for r in results):
        return "unknown"
    return "pass"


# --------------------------------------------------------------------------- CLI


def main(argv: list[str] | None = None) -> int:
    # 输出编码不许依赖调用者的 locale：本脚本会打印中文与"⚠️"这类符号，
    # 在 cp936(GBK) 控制台上默认编码会直接抛 UnicodeEncodeError（退出码 1 之外的一类崩溃，
    # 发布门"没跑成"而不是"发现问题"）。显式指定 UTF-8 并用 replace 兜底，
    # 于是无论调用方是什么代码页，脚本都能把结论打印完。
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            # 被重定向或被替换过的流可能没有 reconfigure；此时不能因此崩掉发布门。
            pass
    ap = argparse.ArgumentParser(
        prog="release_all",
        description="一键发布检查：跑全部门并做三态汇总（退出码 0=pass / 1=fail / 2=unknown）",
    )
    ap.add_argument("--root", default=None, help="正式版仓库根（默认本文件的上两级）")
    ap.add_argument("--acceptance-root", default=None, help="验收程序所在目录（默认 <root>/../test/test2）")
    ap.add_argument("--json", default="", help="把结果写到该 JSON 路径")
    ap.add_argument("--skip", default="", help="跳过的步骤 key，逗号分隔（**跳过的会记成 unknown，不是 pass**）")
    ap.add_argument("--only", default="", help="只跑这些步骤 key，逗号分隔")
    ap.add_argument("--timeout", type=float, default=1800.0, help="单步超时（秒，默认 1800）")
    ap.add_argument("-q", "--quiet", action="store_true", help="只打印总判定")
    args = ap.parse_args(list(argv) if argv is not None else None)

    root = Path(args.root).resolve() if args.root else ROOT
    acc = Path(args.acceptance_root).resolve() if args.acceptance_root else None
    steps = build_steps(root, acc)
    keys = {s.key for s in steps}
    skip = {k.strip() for k in args.skip.split(",") if k.strip()}
    only = {k.strip() for k in args.only.split(",") if k.strip()}
    # ⚠️ **两个集合都要校验**，不能只校验"最终被跳过的那批"。
    # 第一版写成 `bad = (skip | (keys - only)) - keys`，于是 `--only lin`（打错一个字母）
    # 算出来的"跳过集"正好是整个 `keys`，`bad` 因此为空 ⇒ **静默地什么都没跑，然后退出码 2**。
    # 退出码凑巧是对的，理由却是错的 —— 而如果将来有人把跳过记成 `pass`，
    # 这个拼写错误就会变成一次"全绿的空跑"。**判据必须打在用户输入上，不是打在派生结果上。**
    bad = (skip | only) - keys
    if bad:
        print(f"[release_all] 未知的步骤 key：{sorted(bad)}（合法：{sorted(keys)}）", file=sys.stderr)
        return 2

    results: list[Result] = []
    for s in steps:
        if s.key in skip or (only and s.key not in only):
            # ⚠️ **跳过记成 `unknown`，不是 `pass`** —— 这是本脚本最重要的一条取舍。
            # 跳过 = 没查成；把它记成 pass 会让 `--skip acceptance` 变成
            # "发布门全绿"的捷径，而那正是"发布门可以被绕过"。
            results.append(Result(s, "unknown", None, 0.0, ["跳过（--skip / --only）⇒ 没查成，不是通过"]))
            if not args.quiet:
                print(f"[skip ] {s.key:14s} {s.title}")
            continue
        if not args.quiet:
            print(f"[run  ] {s.key:14s} {s.title}（预计 ~{s.expect_seconds}s）", flush=True)
        r = run_step(s, args.timeout)
        results.append(r)
        if not args.quiet:
            print(f"[{r.verdict:6s}] {s.key:14s} exit={r.exit_code} {r.seconds:.1f}s")
            for ln in r.tail[-4:]:
                print(f"         {ln[:150]}")

    verdict = overall(results)
    print("=" * 78)
    for r in results:
        print(f"  [{r.verdict:7s}] {r.step.key:14s} {r.step.title[:56]}")
    print(f"一键发布检查总判定：{verdict.upper()}    "
          f"pass={sum(1 for r in results if r.verdict == 'pass')} "
          f"fail={sum(1 for r in results if r.verdict == 'fail')} "
          f"unknown={sum(1 for r in results if r.verdict == 'unknown')}")
    print("⚠️ `unknown` 是**没查成**，绝不是通过。")
    print("⚠️ 本脚本与 scripts/release_check.py 自身都在 FC-27 禁改区，"
          "仍需人逐行走查 + 2 名 reviewer 批准 —— 它全绿**不构成发布许可**。")

    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(
            json.dumps({"verdict": verdict, "exit_code": VERDICT_EXIT[verdict],
                        "steps": [r.to_dict() for r in results]},
                       ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return VERDICT_EXIT[verdict]


if __name__ == "__main__":
    raise SystemExit(main())

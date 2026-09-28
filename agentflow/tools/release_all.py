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
- ``unknown`` —— **没跑成**：解释器都起不来、超时、被取消（`Ctrl-C`）、可执行文件不存在。

总判定：**任一 `fail` ⇒ `fail`；否则任一 `unknown` ⇒ `unknown`；空表 ⇒ `unknown`
（没有可判的项，不是"全过"）；全 `pass` ⇒ `pass`。**
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
    python tools/release_all.py --only role-specs,coverage   # 只跑指定步骤（调试用）

注意 `--only` 认的是**步骤 key**（`release-check` / `acceptance` / `repro` /
`role-specs` / `coverage` / `per-file`），不是发布门内部的子项名：
`lint` 是 `release-check` 这一步里的第 5 项，**不是**一个步骤 key
（`D3` 实测：旧版这里举的例子是 `--only lint,role-specs`，直接以退出码 2 失败，
而那是本 docstring 里唯一的一个 `--only` 例子）。
`tests/test_release_all.py` 会把本 docstring 里出现的每个 `--only` 示例真跑一遍，
判据是那两句话：stderr 不许出现「未知的步骤 key」，且被点名的每个 key 不许记成
`[unknown]`（**不许**拿退出码当判据：`--only` 是**子集**运行，未选中的步骤按 `H-5`
记 `unknown`，而 `unknown` 就是退出码 **2** —— 这一个数同时表示"用法错误"与"跑通了但有
步骤未知"两种事实，拿它判其中一种是**把两种含义折成一个读数**。`D-13` 记录了那次踩坑：
旧判据 `returncode != 2` 长期为真，只因为当时另一个门红着、整体退出码是 1）。
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

# --------------------------------------------------------------------------- 三态

VERDICT_EXIT = {"pass": 0, "fail": 1, "unknown": 2}

#: 三个合法结论，**从 `VERDICT_EXIT` 派生**（不另写一份枚举：两份枚举必然漂移，
#: 而漂移的表现是"某一步的 verdict 合法但退出码查不到"）。
VERDICTS: tuple[str, ...] = tuple(VERDICT_EXIT)


@dataclass
class Step:
    """一个发布检查步骤。`argv` 是**完整命令**（含解释器），不经过 shell。"""

    key: str
    title: str
    argv: list[str]
    cwd: Path
    #: 该步骤的环境变量。**空字典 = 继承当前环境**（传给 `subprocess.run` 时折叠成 `None`）。
    #:
    #: 为什么必须折叠：`subprocess.run(env={})` 在 Windows 上是**空环境块**，
    #: `CreateProcess` 直接以 `OSError: [WinError 87] 参数错误` 失败 —— 步骤于是被判成
    #: `unknown`（"没跑成"），而真因是编排层传了一个空环境。实测：`build_steps` 造的步骤
    #: 都带完整环境（`_env()`），所以这条只在"手写一个 Step 去跑"时才炸 ——
    #: 也就是只在测试里炸，正是最容易被忽略的形态。
    #: 空环境没有任何正当用途（连 `PATH` 都没有，解释器都起不来），所以"空 = 继承"。
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
    #: 该步骤若会把**自己的逐项结构**写成 JSON，这里给出那个路径（`D-2.3`）。
    #:
    #: 为什么编排层要读它：子进程（`scripts/release_check.py`）本来就把八项逐项
    #: 结果算好了（`items[]` + `counts{}` + `overall`）。编排层此前只留最后 12 行
    #: `tail`，把那份**已经算好的结构丢掉了** —— 于是"8 项各自 pass 还是 unknown"
    #: 在编排层的 JSON 里读不出来，只能靠翻文本。缺口在编排层，不在发布门。
    json_out: Path | None = None
    #: 这一步**已知的、会被绿的缺口**（`FINAL-R7-05`）：在报告里逐条打出来。
    #: 为什么要有这个字段而不是只写在标题里：标题会被 `[:56]` 截断（见汇总那一行），
    #: 而"这一步的绿不覆盖什么"恰恰是最容易被截掉的那半句。
    notes: tuple[str, ...] = ()

    def classify_code(self, code: int) -> str:
        return self.exit_map.get(code, "fail")


#: 本项目里**自带三态**的门：`0 = 通过 / 1 = 发现问题 / 2 = 没查成`。
#: 用同一份字面量给多个步骤，避免"每处各写一遍码表"（那种写法迟早会有一处漏掉 2）。
TRI_STATE_EXIT: dict[int, str] = {0: "pass", 1: "fail", 2: "unknown"}

#: 验收 / 论文复现用的普通脚本语义：`0 = 全过`，其余 `= 有问题`。
#: ⚠️ 它们**不**是三态 —— 但它们的 docstring 里必须写清"非零 = 跑过且发现问题"，
#: 否则"脚本崩了"与"检查不通过"仍然分不开（那是它们自己的事，见各自的 README）。
PLAIN_EXIT: dict[int, str] = {0: "pass"}

#: 崩溃指纹：脚本没跑起来，或跑起来后自己抛了异常。
#:
#: 为什么必须从**输出**认：`test/test2` 的验收与复现脚本只有 0/1 两个码，于是
#: "脚本崩了"与"检查不通过"在退出码上完全同形。两个方向的错法不对称：
#: 把崩溃读成"没查成"只会让人来查；把崩溃读成"发现问题"会让人去改一个没坏的东西。
#: 所以这里保守地降级（只会把 `fail` 降成 `unknown`，绝不会把 `pass` 抬上来）。
CRASH_MARKERS: tuple[str, ...] = (
    "Traceback (most recent call last)",
    "ModuleNotFoundError",
    "SyntaxError:",
    "can't open file",
)


def _looks_like_a_crash(output: str) -> bool:
    return any(marker in output for marker in CRASH_MARKERS)


def _read_step_json(path: Path | None) -> tuple[list[dict], dict, list[str]]:
    """读一个步骤写下的子 JSON（`D-2.3`）。返回 `(items, counts, notes)`。

    ⚠️ 三态纪律在这里同样适用：**读不到**与**读到了但是空的**不是一件事。
    读不到时返回空 `items` 并附一条 note（于是"这一项没有逐项结构"是可见的），
    绝不返回一个"看起来像全都通过"的空结构。

    结构不合规（`items` 不是对象数组 / 缺 `verdict`）时**不猜**：把异常如实记进
    note，让那一项的 `subitems` 保持为空 —— 猜出来的逐项明细比没有更危险。
    """
    if path is None:
        return [], {}, []
    if not path.is_file():
        return [], {}, [f"该步骤声明了逐项 JSON 但没找到文件：{path}"]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [], {}, [f"逐项 JSON 读不了（{type(exc).__name__}: {exc}）：{path}"]
    items = data.get("items")
    counts = data.get("counts")
    if not isinstance(items, list) or not all(isinstance(i, dict) for i in items):
        return [], {}, [f"逐项 JSON 的 `items` 不是对象数组（{path}）⇒ 不猜它的结构"]
    if any(i.get("verdict") not in VERDICTS for i in items):
        return [], {}, [f"逐项 JSON 有子项的 `verdict` 不在 {VERDICTS} 里（{path}）"]
    return list(items), (counts if isinstance(counts, dict) else {}), []


def verdict_from_subitems(items: list[dict]) -> str | None:
    """按子项汇总该步的结论（`D-2.3`）：任一 `fail` ⇒ `fail`；否则任一 `unknown` ⇒ `unknown`。

    这条口径与 `scripts/release_check.py::Report.overall` 「逐字相同」（刻意如此）：
    编排层要能「独立」从子项重算一遍，于是"子进程的总判定"与"逐项明细"之间
    一旦不一致就会被发现，而不是被信任。

    ⚠️ 空列表 ⇒ `None`，且这个 `None` 的含义是"「没有可汇总的东西」"，
    调用方应退回用退出码判定，「而不是」凭空得出 `pass`。

    `H-5` 之前的裂缝正是出在这一档：姊妹实现 `Report.overall()` 的空表分支返回
    `pass`（"三项计数都是 0 ⇒ 其余 ⇒ pass"），于是两处只在非空时相同 ——
    "独立重算一遍"这条防线在空集上整个失效，编排层看到 `subitems=[]` 时
    不会与发布门分家，两边都绿。现在 `Report.overall()` 的空表也返回 `unknown`
    （见 `tests/test_release_all.py` 的交叉断言：非空组合两处逐字一致，
    空表一律读成 `unknown`）。这里保留 `None` 而不是直接给 `"unknown"`：
    它的调用方（`run_step`）需要区分"没有逐项明细可汇总"（⇒ 没有别的证据，
    退回退出码）与"逐项明细说 unknown"，两者后续处理不同。
    """
    if not items:
        return None
    verdicts = [i.get("verdict") for i in items]
    if "fail" in verdicts:
        return "fail"
    if "unknown" in verdicts:
        return "unknown"
    return "pass"


@dataclass
class Result:
    step: Step
    verdict: str
    exit_code: int | None
    seconds: float
    tail: list[str]
    #: 该步骤**自己的逐项结构**（`D-2.3`）：原样嵌进来的子进程 JSON 的 `items[]`。
    #: 刻意"原样嵌"而不是"改写成一个我们自己的结构"：同一件事两个落点必然漂移，
    #: 而这里要的恰恰是"发布门逐项到底怎么判的"这件事只由发布门说了算。
    subitems: list[dict] = field(default_factory=list)
    subcounts: dict = field(default_factory=dict)
    #: 编排层自己观察到的话（子项汇总与退出码判定不一致、子 JSON 读不出来……）。
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "key": self.step.key, "title": self.step.title, "verdict": self.verdict,
            "exit_code": self.exit_code, "seconds": round(self.seconds, 1),
            "tail": self.tail, "argv": self.step.argv,
            "subitems": self.subitems, "subcounts": self.subcounts,
            "notes": self.notes,
        }


def classify(
    exit_code: int | None,
    started: bool,
    timed_out: bool,
    step: Step | None = None,
    output: str = "",
) -> str:
    """把"跑成什么样"映射到三态。

    ⚠️「这个函数是本脚本的核心判据」，所以它的分支顺序本身就是设计：
    `timed_out` / `started=False`「必须先于」`exit_code == 0` 判断 ——
    否则"超时被杀"会走到某一侧去（Windows 上被强杀的进程退出码常是 1，
    与"检查发现问题"的 1 无法区分）。这正是三态纪律要挡的那种静默兜底。

    退出码的解释走 `step.exit_map`（「每一步显式声明自己的码表」）——
    把"2 = 没查成"这类项目内约定留给步骤自己说，而不是在这里猜。

    另加一条「保守降级」：码表里没有 unknown 这一档的步骤（普通 0/1 脚本），
    若输出里带崩溃指纹，则判 `unknown` 而不是 `fail` —— 理由见 `CRASH_MARKERS`。
    """
    if not started or timed_out:
        return "unknown"
    if exit_code is None:
        return "unknown"
    if step is not None:
        verdict = step.classify_code(exit_code)
        if verdict == "fail" and 2 not in step.exit_map and _looks_like_a_crash(output):
            return "unknown"
        return verdict
    return "pass" if exit_code == 0 else "fail"


# --------------------------------------------------------------------------- 步骤表

ROOT = Path(__file__).resolve().parents[1]


def _env(**extra: str) -> dict[str, str]:
    return {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1", **extra}


def _resolve_changed(since: str | None, changed_file: str, root: Path) -> Path | None:
    """把禁 AI 区门的改动集变成一个文件路径；取不到 ⇒ None（那一项如实报 unknown）。

    改动集的唯一实现在 `scripts/noai_gate.py`：本脚本只做编排，不重写一遍 git 口径
    —— 两份实现必然漂移，那正是 P-5 那类缺陷的成因。所以这里调它的 `--print-changed`，
    把结果落成临时文件交给 `release_check.py --changed-file`。

    为什么用文件而不是命令行参数：空改动集必须能被表达（相对基线确实没有改动 ⇒ 那一项
    应当 pass），而 `--changed` 的空列表与"没给"在参数解析层面长得一样。
    """
    if changed_file:
        return Path(changed_file).resolve()
    if not since:
        return None
    gate = root / "scripts" / "noai_gate.py"
    if not gate.is_file():
        print("[release_all] 读不到 scripts/noai_gate.py ⇒ 禁 AI 区门这一项会如实报 unknown", file=sys.stderr)
        return None
    proc = subprocess.run(
        [sys.executable, str(gate), "--print-changed", "--since", since, "--root", str(root)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=_env(),
    )
    if proc.returncode != 0:
        print(
            f"[release_all] 取改动集失败（退出码 {proc.returncode}）⇒ 这一项会如实报 unknown："
            f"\n{(proc.stderr or '').strip()}",
            file=sys.stderr,
        )
        return None
    fd, tmp = tempfile.mkstemp(prefix="agentflow-changed-", suffix=".txt")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(proc.stdout)
    return Path(tmp)


def build_steps(root: Path, acceptance_root: Path | None = None, *, changed_file: Path | None = None,
                sub_json_dir: Path | None = None) -> list[Step]:
    """步骤表：2 个承接用户点名清单的步骤 + 1 个论文复现步骤 + 3 个结构性门 = 6。

    `D4` 的实测（改前）：这里原写"用户点名的六项 + 三个结构性门（角色规格、
    coverage 分档、逐文件单跑）"，按它自己的分解 —— 六项落在 2 个步骤里
    （`release-check` 覆盖 5 项 + `acceptance` 1 项），加 3 个结构性门 = **5**，
    而本函数实际返回 **6**。多出来的那个是 `repro`（论文独立复现），
    清单完全没有它：按 docstring 数步骤会漏掉一个门。
    `tests/test_release_all.py` 现在把这份清单与 `build_steps` 的实际条数铆在一起
    （往表里加一个步骤而不同步这段 ⇒ 测试必红）。

    `scripts/release_check.py` 一次覆盖用户点名的前五项（全量测试 / 全部自检 /
    verify / 工具普查 / linter，外加禁 AI 区门 / 契约版本 / 源码树可导入三项），
    所以这里把它作为一个步骤；用户额外点名、而它没有的验收测试是第二个步骤
    （`acceptance`）。论文独立复现是第三个：它不是用户在那一句里点名的项，
    但它守的是"论文里的实验能不能被独立重跑"，与本脚本存在的理由同源
    （"手敲的清单没有退出码"）。
    另外三个结构性门各自守一件"全量测试结构上守不住"的事：

    - `role-specs`：角色规格的节数与必备子节（缺一节不会让任何测试变红）；
    - `coverage`：零直接测试的公开函数分档（等级 1/2 必须为 0）；
    - `per-file`：逐文件单跑 —— 全量绿会掩盖单文件红（顺序依赖/跨文件状态泄漏），
      这一步正是把"排序给的那部分绿灯"收回去。它很慢，但 `--skip` 会记成 `unknown`。
    """
    acc = acceptance_root or (root.parent / "test" / "test2")
    # `D-2.3`：让 release-check 把它的逐项结构写成 JSON，编排层再读回来嵌进自己的 JSON。
    # 用临时目录而不是仓库里的固定路径：产物不该改仓库状态（与 `X-1` 同一条口径）。
    if sub_json_dir is None:
        sub_json_dir = Path(tempfile.mkdtemp(prefix="release-all-sub-"))
    release_check_json = sub_json_dir / "release-check.json"
    return [
        Step(
            "release-check", "全量测试 + 全部自检 + verify + 工具普查 + linter + 禁 AI 区 + 契约 + 导入",
            [sys.executable, str(root / "scripts" / "release_check.py")]
            + (["--changed-file", str(changed_file)] if changed_file is not None else [])
            + ["--json", str(release_check_json)],
            cwd=root, env=_env(), expect_seconds=300,
            # ⚠️ **`release_check.py` 自带三态**：`0=pass / 1=fail / 2=unknown`。
            # 第一版漏了这一行，于是它返回 2 时编排层报的是 `fail` ——
            # "没查成"被读成"发现问题"。**必须显式声明码表。**
            # 这里还曾把那一项 unknown 归因于"这不是 git 仓库"。真因是调用方不传改动集
            # （P-25）；本仓现在就是 git 仓库，而那一项照样 unknown。改动集由
            # `--since` / `--changed-file` 供上，取不到时仍如实报 unknown。
            exit_map=TRI_STATE_EXIT,
            json_out=release_check_json,
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
            "coverage", "零测试公开函数的风险分档清单（等级 1/2 应为 0；"
                        "注意：传递判据 `--propagate` 本步**不开**，见 `FINAL-R7-05`）",
            [sys.executable, str(root / "tools" / "coverage_zero_test.py")],
            cwd=root, env=_env(), expect_seconds=60,
            exit_map=TRI_STATE_EXIT,
            # `FINAL-R7-05`：`coverage_zero_test` 的传递判据（等级 1e/2c，"自身 AST 里
            # 没有写原语、只经由 callee 写盘"）默认关闭，而本步不传 `--propagate`
            # ⇒ 这类零测试编排函数落到等级 4，既不进 `gate`（阈值 2）也不进等级 1/2 清单。
            # 实测（R7）：真实树副本开 `--propagate` 后 gate=22（9+13）—— 也就是说
            # "开了就会红"。所以这里**不改判据强度**（那要先把那 22 个函数补上测试，
            # 属于另一件事），但把这句缺口写进步骤标题与 notes：读发布报告的人
            # 不会把这一步的绿读成"编排函数都被覆盖了"。
            notes=("传递判据（1e/2c）本次关闭 ⇒ 本步的『等级 1/2 = 0』不含"
                   "『只经由 callee 写盘』的编排函数（`FINAL-R7-05`）",),
        ),
        Step(
            "per-file", "逐文件单跑测试（把顺序依赖/跨文件状态泄漏变成可判定的门）",
            [sys.executable, str(root / "tools" / "run_each_test_file.py")],
            # 这一步很慢（每个 `tests/test_*.py` 各起一个 pytest 进程，量级与全量测试相同；
            # 文件数不写死（`G-32`）：由 `(Get-ChildItem tests -Filter 'test_*.py').Count`
            # 当次读 —— 观测 2026-09-27 14:56:26 ⇒ 118，多一个测试文件它就会过期）——
            # 但它守的是一件全量测试**结构上做不到**的事：全量绿掩盖单文件红。
            # 慢的门会被跳过，所以这里的对策不是"不做"，而是 `--skip per-file`
            # 会被记成 `unknown`（不是 pass），跳过了就得逐条解释。
            cwd=root, env=_env(), expect_seconds=420,
            exit_map=TRI_STATE_EXIT,
        ),
    ]


# --------------------------------------------------------------------------- 跑一步


class StepCancelled(BaseException):
    """这一步被中断（`Ctrl-C`）——「带着三态结论一起抛出」（`D5`）。

    为什么是 `BaseException` 而不是 `Exception`：它表示的是一次中断，
    任何 `except Exception` 都不该把它吞掉（吞掉就等于"用户按了 Ctrl-C，
    进程却继续把剩下的门跑完"）。为什么带一个 `result`：`D5` 的承诺是
    "取消落进 `unknown` 这一档"，而"抛出去"只证明了停下来了、证明不了记成了哪一档。
    带上 `Result` 之后，调用方既能如实记账（`unknown`），又能让中断继续向上传播。
    """

    def __init__(self, result: Result):
        super().__init__("step cancelled")
        self.result = result


def run_step(step: Step, timeout: float) -> Result:
    t0 = time.monotonic()
    started = False
    timed_out = False
    cancelled = False
    code: int | None = None
    out = ""
    try:
        started = True
        p = subprocess.run(
            step.argv, cwd=str(step.cwd), env=step.env or None,
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
    except KeyboardInterrupt:
        # `D5`：`KeyboardInterrupt` 是 BaseException，`except Exception` 兜不住它。
        # 旧实现只捕 `TimeoutExpired` / `OSError` / `Exception`，于是用户 Ctrl-C 时
        # 整段脚本带 traceback 结束 —— 拿到的是一个不属于三态的退出码，
        # 而模块 docstring 逐字承诺 `unknown` 覆盖"取消"。承诺在这里落地：
        # 这一步记 `unknown`（没跑成），并把中断继续抛给调用方。
        #
        # 为什么必须 `raise`（不能把它吞成"这一步 unknown，接着跑下一步"）：
        # 吞掉中断会让用户按了 Ctrl-C 之后进程还在后台把剩下的门跑完 ——
        # 那是"用沉默对抗操作者"。而"停下来"的代价只是这一次 run 的汇总不完整，
        # 那件事由 `main()` 的 `except KeyboardInterrupt` 如实报出来（退出码 130）。
        cancelled = True
        started = False
        out = "（被中断：KeyboardInterrupt）"
    except Exception as exc:  # noqa: BLE001 —— 理由：编排层不许让**任何**异常变成"看起来没跑过"。
        # 这里兜住的是"检查器自己炸了"，它必须落进 `unknown` 而不是把整个发布门带崩；
        # 消息里带上异常类型，于是"没跑成"仍可归因。
        out = f"编排层捕获到未预期异常：{type(exc).__name__}: {exc}"
    secs = time.monotonic() - t0
    tail = [ln for ln in out.strip().splitlines() if ln.strip()][-12:]
    subitems, subcounts, notes = _read_step_json(step.json_out)
    # `FINAL-R7-05`：步骤自己声明的"已知会被绿的缺口"要出现在 Result 的 notes 里
    # （打印与 JSON 都走这一处），否则它只活在标题那 56 个字符里。
    notes = [*(getattr(step, "notes", ()) or ()), *notes]
    if cancelled:
        # `D5`：先把这一步的结论算出来、再重新抛中断。
        #
        # `run_step` 的契约是"给一个 Step，回一个 `Result`"，所以它必须「返回」
        # 那个 `unknown`（于是调用方哪怕在 `finally` 里也能读到"这一步没跑成"），
        # 然后把 `KeyboardInterrupt` 继续抛出去让进程真的停下来。
        # 只 `raise` 不返回（第一版就是这样）会让"中断"这件事退化成一次普通异常
        # —— 那与 `D5` 的承诺（`unknown` 覆盖"取消"）不符，也让单元测试只能
        # 断言"抛了"，断言不了"记成了 unknown"。
        notes.append("这一步被中断（Ctrl-C）⇒ **没跑成**：不是 fail，更不是 pass")
        raise StepCancelled(Result(step, "unknown", code, secs, tail,
                                   subitems, subcounts, notes))
    verdict = classify(code, started, timed_out, step, out)
    if subitems:
            # `D-2.3`：该步的结论按**它自己的逐项明细**汇总，而不是只信一个整数退出码。
            derived = verdict_from_subitems(subitems)
            if derived is not None and derived != verdict:
                notes.append(
                    f"子项汇总给出 {derived}，退出码判定给出 {verdict} ⇒ 以逐项明细为准，"
                    "两者不一致本身是一个需要看的信号（子进程的总判定与逐项明细分家了）"
                )
                verdict = derived
    return Result(step, verdict, code, secs, tail, subitems, subcounts, notes)


def overall(results: list[Result]) -> str:
    """总判定：任一 `fail` ⇒ `fail`；否则任一 `unknown` ⇒ `unknown`；空表 ⇒ `unknown`。

    `H-5` / `T4` / `I-7`（本轮修）：空表**不再**返回 `pass`。
    旧口径是"三项计数都是 0 ⇒ 其余 ⇒ `pass`"，于是 `overall([]) == "pass"` ——
    一个"没有可判的项"的输入被读成"全过"，与姊妹函数
    `verdict_from_subitems([])`（返回 `None`，逐字写着"不许凭空得出 pass"）
    在同一仓库里给了两种口径。空集的含义是**没查成**，不是通过。

    真实路径上 `main()` 走不到这里：它对 `build_steps(...)` 的每一条都
    `results.append(...)`（跳过记 `unknown`、跑了记结果），而步骤表恒非空
    （`tests/test_release_all.py::test_main_records_one_result_per_step_so_the_empty_table_is_unreachable`
    把这件事从散文变成了可红的判据）。所以这一支今天只在被单测直接调用时可达 ——
    但"不可达"不是把语义写错的理由：口径一旦被别的调用方复用，
    写错的那一支就会成为下一个静默的"通过"。
    """
    if any(r.verdict == "fail" for r in results):
        return "fail"
    if any(r.verdict == "unknown" for r in results):
        return "unknown"
    if not results:
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
    ap.add_argument(
        "--since",
        default=None,
        help="禁 AI 区门的基线 ref（给了就自动算出改动集喂给它，CI 用这个；不给 ⇒ 那一项如实报 unknown）",
    )
    ap.add_argument("--changed-file", default="", help="显式给改动集文件（每行一条路径）；优先于 --since")
    args = ap.parse_args(list(argv) if argv is not None else None)

    root = Path(args.root).resolve() if args.root else ROOT
    acc = Path(args.acceptance_root).resolve() if args.acceptance_root else None
    _own_changed_file = ""
    changed_file = _resolve_changed(args.since, args.changed_file, root)
    # `FINAL-R7-09`：`_resolve_changed` 造的临时改动集文件只创建不删除 —— 跑一次门就在
    # 系统临时目录里留一份（实测 `--since HEAD~1` 后 `agentflow-changed-*.txt` 由 0 → 1）。
    # 记下"这一次自己造的那一份"，退出前删掉（用户显式给的 `--changed-file` 不在此列：
    # 那是他的文件，不许替他删）。
    if not args.changed_file and changed_file is not None and changed_file.is_file():
        _own_changed_file = str(changed_file)
    steps = build_steps(root, acc, changed_file=changed_file)
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
        _cleanup_own_changed_file(_own_changed_file)
        return 2

    results: list[Result] = []

    def _one(s: Step, results_list: list[Result]) -> None:
        """跑一步并记账（`D5`：Ctrl-C 不许让整段带 traceback 结束）。"""
        try:
            r = run_step(s, args.timeout)
        except StepCancelled as exc:
            # `D5`：这一步的结论是 `unknown`（`run_step` 已经算好并带出来了）。
            # 先如实记账，再把中断继续抛给外层 —— 于是"停下来"与"记成哪一档"
            # 这两件事都成立。吞掉它（不在外层接住）会让进程在用户按下 Ctrl-C
            # 之后继续在后台跑完剩下的门，那是"用沉默对抗操作者"。
            results_list.append(exc.result)
            if not args.quiet:
                print(f"[中断  ] {s.key:14s} 已被打断 ⇒ 这一步记 unknown（没跑成）")
            raise
        results_list.append(r)
        if not args.quiet:
            print(f"[{r.verdict:6s}] {s.key:14s} exit={r.exit_code} {r.seconds:.1f}s")
            for ln in r.tail[-4:]:
                print(f"         {ln[:150]}")

    try:
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
            _one(s, results)
    except (KeyboardInterrupt, StepCancelled):
        # 走到这里说明中断发生在还没轮到任何一步的那一刻（例如 `build_steps`
        # 还没返回、或正卡在打印上）。此时这一轮到此为止：把「没跑过的」步骤
        # 整批记 `unknown`，仍然把报告落盘并汇总 —— 绝不静默退出
        # （那正是 `D5` 说的"不属于三态的退出码"）。
        done = {r.step.key for r in results}
        remaining = [s for s in steps if s.key not in done]
        for s in remaining:
            results.append(Result(s, "unknown", None, 0.0,
                                  ["被打断（Ctrl-C）⇒ 没查成，不是通过"]))
        print("\n[release_all] 被中断（Ctrl-C）⇒ 未跑的步骤都记 `unknown`（没查成）。",
              file=sys.stderr)
        if not args.quiet:
            for s in remaining:
                print(f"[skip ] {s.key:14s} {s.title}")

    verdict = overall(results)
    # `D-2.5`：三个计数**只算一次**，stdout 的总判定行与 JSON 顶层用的是同一个 dict。
    # 各算一遍就会漂移，而漂移的表现是"打印说 pass=5、JSON 里说 pass=4" ——
    # 两个都对不上，读者不知道该信哪个。
    counts = {v: sum(1 for r in results if r.verdict == v) for v in ("pass", "fail", "unknown")}
    print("=" * 78)
    for r in results:
        print(f"  [{r.verdict:7s}] {r.step.key:14s} {r.step.title[:56]}")
        # `FINAL-R7-05`：把"这一步的绿不覆盖什么"逐条打出来（标题会被上面那行截断）。
        for note in getattr(r.step, "notes", ()) or ():
            print(f"           ! {note}")
    print(f"一键发布检查总判定：{verdict.upper()}    "
          f"pass={counts['pass']} fail={counts['fail']} unknown={counts['unknown']}")
    print("⚠️ `unknown` 是**没查成**，绝不是通过。")
    print("⚠️ 本脚本与 scripts/release_check.py 自身都在 FC-27 禁改区，"
          "仍需人逐行走查 + 2 名 reviewer 批准 —— 它全绿**不构成发布许可**。")

    if args.json:
        # 写文件用 `open(..., newline="")`：这是 G-42 的换行纪律（禁 `Path.write_text()`）
        # 在本文件里的落地形态 —— `write_text` 在 Windows 上会把 LF 刷成 CRLF，
        # 而产物的 sha256 与"盘上那一版"必须对得上（draft/22 §12.15.2 记过那次事故）。
        #
        # 这条纪律不再只是一段散文（`c-12`）：它现在是
        # `scripts/lint_rules.py` 的 `R012`（`rule_R012_write_text_newline`）——
        # 对 `scripts/` 与 `tools/` 下每个 `.py`，AST 里出现
        # `X.write_text(...)` 而没有 `newline=` ⇒ 一条 `warning`，并在
        # `python scripts/lint_rules.py --strict` 的报告里逐条点名。
        # 引用这条纪律时请引 `R012` 这个规则号，不要引 `G-42`：
        # `G-42` 只是 `docs/PROPOSALS.md` 里的一条教训，不是任何一条能跑的判据。
        #
        # 同族的另外两处本轮已按同一口径改掉（`c-12`）：
        # `scripts/release_check.py` 的 `--json` 出口与 `scripts/lint_rules.py` 的
        # `--json` 出口，两处都从 `Path.write_text` 改成 `open(..., newline="")`。
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        with open(args.json, "w", encoding="utf-8", newline="") as fh:
            fh.write(json.dumps(
                {"verdict": verdict, "exit_code": VERDICT_EXIT[verdict],
                 "counts": counts,
                 "steps": [r.to_dict() for r in results]},
                ensure_ascii=False, indent=2,
            ))
    cleanup_done = _cleanup_own_changed_file(_own_changed_file)
    return VERDICT_EXIT[verdict]


def _cleanup_own_changed_file(path_text: str) -> bool:
    """删掉"这一次自己造的"临时改动集文件（`FINAL-R7-09`）；返回是否删掉了。

    为什么单独一个函数：`main` 有两条出口（未知 key 的提前返回、正常收尾），
    两处都要清 —— 写成两段内联代码早晚会漏掉一处。用户显式给的
    `--changed-file` 从来不会传进来（那是他的文件）。
    """
    if not path_text:
        return False
    try:
        p = Path(path_text)
        if p.is_file():
            p.unlink()
            return True
    except OSError:
        # 删不掉不是运行失败：这一步只是卫生（temp 目录里的一个 16KB 文件）。
        # 但要说出来，免得"以为清了"变成又一个静默假设。
        print(f"[release_all] 临时改动集文件没删掉（不影响判定）：{path_text}", file=sys.stderr)
    return False


if __name__ == "__main__":
    raise SystemExit(main())

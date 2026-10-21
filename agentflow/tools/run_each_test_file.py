#!/usr/bin/env python
"""逐文件跑测试：把"顺序依赖 / 跨文件状态泄漏"变成一条可判定的门。
## 为什么要有这条门（G-27，实测）
审计期实测：`pytest tests/test_fc17_wiring.py -q` 单独跑是 6 failed / 4 passed，而在全量 `pytest -q` 里全过。也就是说那次的绿灯是排序给的，不是判据给的
——全量绿掩盖了单文件红，而"到底哪个文件坏了"必须可判定。
## 判据与退出码
判据：`tests/test_*.py` 里每个文件各起一个 pytest 进程；任一文件非 0 ⇒ 本门失败。
- `0` = 每个有可跑用例的文件单独跑都过（"全被配置筛掉"的文件逐条列出，不算过也不算失败）；
- `1` = 至少一个文件单独跑失败（逐文件列出，并给出该文件自己的汇总行）；
- `2` = 没查成（没有 tests 目录 / 空目录 / 超时 / 起不了进程 / 有文件一个用例都没有 /
有文件整份都是 xfail 或 xpass / 有文件整份被跳过而没豁免）。三态纪律：这些都不是"过"。
`exit=5`（pytest 的 `NO_TESTS_COLLECTED`）必须按输出拆成两种：汇总行里有 `deselected`⇒ "用例都被配置筛掉了"（如 `-m "not network"`），没有 ⇒
"这个文件空了"。第一版把两者都当失败，于是发布检查多了一条假红（实测见 `classify_pytest_result`）。
`exit=0` 也要按汇总行拆（`I-2` / `R6-7`）：只有 `skipped` ⇒ `all_skipped`；只有 `xfailed` / `xpassed` ⇒ `all_xfail`；
两者都不是"过"。`all_xfail` 单列一档（`R6-7`）的理由：旧版把它塞进 `no_tests`，而那一档的打印是"文件里一个用例都没有" —— 对一个整份都是 xfail 的文件，这句话是假的（用例在，
只是都被标成了预期失败）。桶名与措辞都必须说事实，否则读报告的人会去查一个不存在的问题（"文件是不是被改名了"）。
## 为什么必须逐文件起进程
同一个进程里连着跑多个文件，正是顺序依赖能藏身的地方。所以本脚本不许把文件合并成一次 pytest 调用 —— 那等于把这条门取消。`--list` 会把每条命令原样打出来，供人核对"确实是一个文件一条命令"。
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time
from pathlib import Path

#: 逐文件跑的额外 pytest 参数。`-p no:cacheprovider` 是刻意的：并发跑多个进程时
#: 共享 `.pytest_cache` 会产生互相干扰的写，而这条门本身不该引入新的不确定性。
PYTEST_ARGS: tuple[str, ...] = ("-q", "-p", "no:cacheprovider")

#: 允许整文件被跳过/筛掉的显式名单（`I-2` 的豁免面）。名单外的整文件跳过/筛掉一律按 `unknown` 处理并影响
#: 退出码 —— 否则"给一个文件所有用例加 `@pytest.mark.skip` 或 `network` 标记"就能把它整文件从门里摘掉而
#: 门报绿（`classify_pytest_result` 把"exit 0 且只有 skipped"判成 `all_skipped`，`deselected` 同样不进
#: 退出码）。与 `_KNOWN_UNMATCHED_ACTIONS` 同一条纪律：豁免要写下来，写不出理由的就该去修。本文件在
#: FC-27 清单里（`.noai-paths` 的 `[category: release-deploy]`）：改它要人逐行走查 + 2 名 reviewer 批准
#: （`FINAL-R7-04` 更正过此处"本文件不在清单里"的错说法）。`R6-1` 的绕过根因是"唯一的机器约束是理由长度
#: ≥ 20 字符"，所以 `audit_exemptions()`（`main()` 启动时先跑）加三道判据：① 条目数 ≤
#: `MAX_EXEMPT_ALL_SKIPPED`（默认 1，加第二条必须同时改上限）；② 文件必须真的存在；③ 理由 ≥ `MIN_EXEMPT_REASON_CHARS` 且提到 `network`/`skip`/`deselect` 之一。三条都不等于"这个豁免是对的"， 但"加一行就绿"必须经过一次可见的编辑。
EXEMPT_ALL_SKIPPED: dict[str, str] = {
    "tests/test_providers_online.py": (
        "整文件 `pytestmark = pytest.mark.network`，而 `pyproject.toml` 的 "
        "`addopts = -m \"not network\"` 默认排除它 —— 这是**设计**（联网回归测试"
        "不该在每一次本地/CI 跑里出网）。要跑它用 `pytest -m network`；"
        "它在 `-m network` 下实测 8 passed（见 `draft/28` §7）。"
    ),
    "tests/test_webui_browser.py": (
        "整文件 `pytestmark = pytest.mark.browser`，而 `pyproject.toml` 的 "
        "`addopts = -m \"not network and not browser\"` 默认筛掉它（裁定 F1：浏览器端到端"
        "**opt-in**）—— 与上一条同构。本机没装 playwright ⇒ 模块级 `importorskip` 再 skip 一次，"
        "于是逐文件单跑看到的汇总行是 `no tests ran`（`classify_pytest_result` 记 `no_tests`）。"
        "要跑它用 `pip install -e .[browser]` + `playwright install` + `pytest -m browser`；"
        "**没装就是 unknown，不是 pass**（这一点写在 marker 描述与文件 docstring 里）。"
    ),
}

#: 豁免名单的条数上限。见上面那段：它是"加一行就绿"的机器阻力。
#:
#: 2026-10-07 从 1 抬到 2：Web 端的浏览器判据（`tests/test_webui_browser.py`）与既有的
#: `test_providers_online.py` 完全同构 —— 都是"整文件被默认筛掉 + 未装依赖即 skip"，
#: 都不是缺陷。抬这个上限是一次需要解释的编辑（本条注释就是解释），并且：
#:   · 两条豁免各自的理由都过 `audit_exemptions()` 的三道机器判据（条数/存在/实质）；
#:   · 这条改动与 G2 那两处一样落在 FC-27 的 `[category: release-deploy]` 里
#:     ⇒ 需要人逐行走查 + 2 名 reviewer 批准，已登记在 `draft/67 §3b` 的第 3 条待签项；
#:   · 抬上限不放松判定语义：名单外的一律 `unknown`，而上限本身仍是硬约束（3 条就红）。
MAX_EXEMPT_ALL_SKIPPED: int = 2
#: 豁免理由的最短长度（字符）。
MIN_EXEMPT_REASON_CHARS: int = 20
#: 理由里必须出现的词之一（证明它说清了"为什么整文件会被筛掉"）。
EXEMPT_REASON_KEYWORDS: tuple[str, ...] = ("network", "skip", "deselect")


def audit_exemptions(
    exemptions: dict[str, str] | None = None,
    *,
    root: Path | None = None,
) -> tuple[list[str], list[str]]:
    """检查 `EXEMPT_ALL_SKIPPED` 自身的三条机器判据。

    返回 `(problems, notes)`：
    - `problems`：判据（空 = 通过）。任一条命中 ⇒ 调用方按"没查成"处理。
    - `notes`：环境性说明（例如"这个豁免的文件不在当前 `--root` 里"）——
      它不进退出码：`--root` 指向一棵没有那个文件的小树是合法用法，
      把"不在我这棵树里"当失败会造出一条假红（本项目记过这种形态）。

    `exemptions` 与 `root` 可注入，是为了让负控能在不改这张表的前提下
    证明这三条判据真的会响（见 `tests/test_run_each_test_file.py`）。
    """
    table = EXEMPT_ALL_SKIPPED if exemptions is None else exemptions
    base = Path(root) if root is not None else Path(__file__).resolve().parents[1]
    problems: list[str] = []
    notes: list[str] = []
    if len(table) > MAX_EXEMPT_ALL_SKIPPED:
        problems.append(
            f"豁免条目 {len(table)} 条 > 上限 {MAX_EXEMPT_ALL_SKIPPED}："
            "加豁免必须同时改 `MAX_EXEMPT_ALL_SKIPPED` 并在提交信息里说明理由"
            "（这张表曾经是'加一行就绿'的口子，见 `R6-1`）"
        )
    for rel, why in table.items():
        if not (base / rel).is_file():
            notes.append(f"豁免的 {rel} 不在当前 root（{base}）下 ⇒ 本次没有豁免对象")
        if len(why.strip()) < MIN_EXEMPT_REASON_CHARS:
            problems.append(
                f"豁免 {rel} 的理由只有 {len(why.strip())} 字符"
                f"（下限 {MIN_EXEMPT_REASON_CHARS}）"
            )
        elif not any(k in why for k in EXEMPT_REASON_KEYWORDS):
            problems.append(
                f"豁免 {rel} 的理由没有说明'为什么整文件会被筛掉'"
                f"（必须提到 {list(EXEMPT_REASON_KEYWORDS)} 之一）"
            )
    return problems, notes


def _pin_utf8() -> None:
    """钉住 stdout/stderr 的编码。

    内联的理由与 `scripts/lint_rules.py` 等门脚本同：门必须在本包 import 不了时也能跑。
    规范实现见 `src/agentflow/console.py::pin_utf8`。
    不钉的后果：GBK 控制台下打印含 `⇒` 的行会抛 UnicodeEncodeError，进程以 1 结束，
    而 1 是"发现问题"的码 —— 一次崩溃会被读成一次失败。
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            # 可以忽略：被重定向或被替换过的流可能没有 reconfigure，不该让门崩掉。
            pass


def discover(root: Path) -> list[Path]:
    """递归返回 `tests/` 下的 `test_*.py`（排序是为了输出可比对）。

    `R6-2`（第一次重审实测）：旧版是 `(root / "tests").glob("test_*.py")` ——
    只扫顶层，而 `pyproject.toml` 的 `testpaths = ["tests"]` 是递归的
    （pytest 会收 `tests/sub/` 里的用例）。实测：把一条会失败的用例放进
    `tests/sub/test_x.py`，逐文件门 exit 0（报绿），而同一个 root 的
    `pytest` 是 `1 failed` —— 门绿而仓库红，正是本门立项要抓的那类形态。
    现在用 `rglob`，与 pytest 的收集口径一致。
    """
    return sorted(p for p in (root / "tests").rglob("test_*.py") if p.is_file())


def pytest_argv(test_file: Path) -> list[str]:
    """一个文件一条命令 —— 这里是"逐文件"三个字的落点。"""
    return [sys.executable, "-m", "pytest", str(test_file), *PYTEST_ARGS]


def classify_pytest_result(returncode: int, output: str) -> tuple[str, str]:
    """    把一个 pytest 子进程的结果映射到本门的状态，返回 `(状态, 证据行)`。
    状态取值 `ok` / `fail` / `all_skipped` / `all_xfail` / `deselected` / `no_tests`；`unknown` 由调用方在超时/起不来时直接给，不经过这里。
    ## `I-2`：`exit 0` 不等于"有东西跑过且都过了"
    旧版第一句是 `if returncode == 0: return "ok", summary` —— 于是一个全部被 skip 的文件（汇总行是 `1 skipped in 0.01s`、一个 `passed` 都没有）被判成 `ok`。
    实测（`draft/28` 的 `I-2`）：文件内容`pytestmark = pytest.mark.skip(...)` + 一条 `assert False`，
    门报`[ok  ] tests/test_allskip.py  1 skipped in 0.01s` 且整体退出码 0。也就是说：给用例加一个 skip 就能整文件消音，而且报绿。
    真实实例：`tests/test_agent_e_formal_path.py` 默认 `14 passed, 1 skipped`，而被跳掉的那一条是全仓唯一真起 Lean 跑一遍的端到端判据 ——门只知道"过 1"，不知道那一条从没在门里跑过。
    所以 `exit 0` 要按汇总行再分两档：
    - 有 `passed` ⇒ `ok`（真的跑了，且都过了）；- 只有 `skipped`（一个 `passed` 都没有）⇒ `all_skipped`（没有对象可判）。
    `all_skipped` 在 `main()` 里按 `EXEMPT_ALL_SKIPPED` 处理：名单外的一律 `unknown`并影响退出码；名单内的照实打印豁免理由。
    ## 为什么必须把 `exit=5` 拆成两种（实测，本门接进 release_all 第一次就抓到）
    `tests/test_providers_online.py` 的用例全带 `network` 标记，而本仓库默认`-m "not network"` ⇒ pytest 以 5（`NO_TESTS_COLLECTED`）结束，
    汇总行是`8 deselected in 0.08s`。第一版把它判成"单独跑不过"，于是发布检查多了一条假红 ——拿"没有可判的对象"冒充"有问题"，正是本项目反复踩的那类错误。
    所以按输出区分两件不同的事：
    - `deselected`：文件里有用例，但都被配置筛掉了（汇总行里有 `deselected`）⇒ 没有对象可判；但同样必须显式豁免（否则"加一个标记"就是摘除文件的手段，而那正是 `I-2` 记的第二条旁路）。- `no_tests`：
    文件里一个用例都没有（既没 `deselected` 也没 `passed`）⇒ "这个文件空了"的信号，整体按没查成处理，绝不读成过。
    判"有 `passed`"用的是计数正则而不是 `"passed" in summary`：后者会被 `0 passed` 骗过去（pytest 在"全跳过"时会打 `1 skipped`，但在"空收集 + 有错误"时可能打 `0 passed`）。用
    `\\d+ passed` 且要求数字非 0。
    """
    lines = [ln for ln in (output or "").strip().splitlines() if ln.strip()]
    summary = lines[-1] if lines else "（没有输出）"
    if returncode == 0:
        m = re.search(r"(\d+)\s+passed", summary)
        if m and int(m.group(1)) > 0:
            return "ok", summary
        # `R6-7`：整文件 xfail / xpass —— 用例在，但没有一条在真的判。
        #
        # pytest 对"全被标成预期失败"的文件给 `exit=0` + `1 xfailed in …`。
        # 旧版把它归进 `no_tests`，而 `main()` 对那一档打印
        # "文件里一个用例都没有"、并把它算进"一个用例都没有"那一栏 ——
        # 对一个整文件 xfail 的文件，这两句话都是假的（用例在，只是都被标了）。
        # 判"有 xfailed"用的是计数正则，与上面判 passed 同一个道理：
        # `"xfailed" in summary` 会被 `0 xfailed` 骗过去，也可能出现在别的上下文里。
        if re.search(r"\d+\s+x(fail|pass)ed", summary):
            return "all_xfail", summary
        if "skipped" in summary:
            return "all_skipped", summary
        # exit 0 却既没 passed、也没 skipped、也没 xfail：收集到了 0 个用例
        # （或输出形状陌生）。这两种都不是"过" —— 归到"一个用例都没有"那一档。
        return "no_tests", summary
    if returncode == 5:
        if "deselected" in summary:
            return "deselected", summary
        return "no_tests", summary
    return "fail", f"exit={returncode}  {summary}"


def run_one(root: Path, test_file: Path, timeout: float) -> tuple[str, str]:
    """跑一个文件，返回 `(状态, 证据行)`。

    状态含义见 `classify_pytest_result`。`unknown` 只留给"这一条本身没跑成"
    （超时、解释器起不来）；崩溃与断言失败在抽查层面上都是"这个文件单独跑不过"。
    """
    env = {**os.environ, "PYTHONPATH": "src", "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    try:
        proc = subprocess.run(
            pytest_argv(test_file),
            cwd=str(root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return "unknown", f"超时（{timeout:.0f}s）"
    except OSError as exc:
        return "unknown", f"起不了进程：{type(exc).__name__}: {exc}"

    return classify_pytest_result(proc.returncode, (proc.stdout or "") + (proc.stderr or ""))


def main(argv: list[str] | None = None) -> int:
    _pin_utf8()
    ap = argparse.ArgumentParser(
        prog="run_each_test_file",
        description=(
            "逐文件跑 tests/test_*.py，把顺序依赖/跨文件状态泄漏变成可判定的门。"
            "退出码 0=全过 / 1=有文件单独跑不过 / 2=没查成。"
        ),
    )
    ap.add_argument("--root", default=None, help="仓库根（默认本文件的上两级）")
    ap.add_argument("--list", action="store_true", help="只打印每个文件要跑的命令，不执行")
    ap.add_argument("--timeout", type=float, default=600.0, help="单个文件的超时秒数（默认 600）")
    ap.add_argument("-q", "--quiet", action="store_true", help="只打印失败行与总判定")
    args = ap.parse_args(list(argv) if argv is not None else None)

    root = Path(args.root).resolve() if args.root else Path(__file__).resolve().parents[1]
    if not (root / "tests").is_dir():
        print(f"[per-file] 读不到测试目录 {root / 'tests'} —— 没查成（退出码 2）", file=sys.stderr)
        return 2
    # `R6-1`：先查豁免表自己。表本身不合规 ⇒ 没查成（退出码 2），
    # 不是"有过"也不是"有问题"：门还没开始判，先修表。
    exempt_problems, exempt_notes = audit_exemptions(root=root)
    for n in exempt_notes:
        print(f"[per-file] （说明）{n}", file=sys.stderr)
    if exempt_problems:
        print("[per-file] `EXEMPT_ALL_SKIPPED` 自身不合规 —— 没查成（退出码 2）：",
              file=sys.stderr)
        for p in exempt_problems:
            print(f"  - {p}", file=sys.stderr)
        return 2
    files = discover(root)
    if not files:
        print(f"[per-file] {root / 'tests'} 下没有 test_*.py —— 没查成（退出码 2）", file=sys.stderr)
        return 2

    if args.list:
        for f in files:
            print(" ".join(pytest_argv(f)))
        return 0

    ok = fail = unknown = deselected = no_tests = exempt = 0
    all_xfail = 0
    t0 = time.monotonic()
    failures: list[str] = []
    for f in files:
        status, detail = run_one(root, f, args.timeout)
        rel = f.relative_to(root).as_posix()
        if status in ("all_skipped", "deselected"):
            # `I-2`：整文件跳过/筛掉 ⇒ 必须显式豁免，否则按没查成处理。
            why = EXEMPT_ALL_SKIPPED.get(rel)
            if why:
                exempt += 1
                mark = "skip"
                detail = f"{detail}　[已豁免：{why}]"
            else:
                unknown += 1
                mark = "????"
                failures.append(
                    f"{rel}  整个文件被跳过/筛掉，而它**不在** `EXEMPT_ALL_SKIPPED` 里：{detail}"
                    "。这不是'过'，也不是'没问题' —— 它只是'这一次没有对象可判'。"
                    "要么把那个 skip/标记去掉，要么把它登记进 `EXEMPT_ALL_SKIPPED` 并写明理由。"
                )
            if status == "deselected":
                deselected += 1
        elif status == "all_xfail":
            # `R6-7`：整文件都是 xfail / xpass ⇒ 用例在，但没有一条在真的判。
            # 单列一档、单独计数、单独措辞：旧版把它塞进 `no_tests`，
            # 而那一档的打印是"文件里一个用例都没有"（对它是假话）。
            # 退出码按"没查成"（2）算：这不是失败（用例没崩），
            # 但也绝不是"过" —— 一个"给全文件加一行 xfail 标记"就能消音的文件
            # 不许让门变绿（与 `I-2` 的 skip 形态同一条纪律）。
            all_xfail += 1
            unknown += 1
            mark = "????"
            failures.append(
                f"{rel}  整文件 xfail/xpass（整个文件的用例都是预期失败或预期失败却通过，"
                f"没有一条在真的判）：{detail}"
                "。用例在，只是都被标成了预期失败 —— 这一档不该被读成'这个文件空了'。"
                "要么去掉那些标记让它真的判，要么删掉/改写这个文件；"
                "本门**不**为它提供豁免口（豁免口等于给'整文件消音'盖章）。"
            )
        elif status == "ok":
            ok += 1
            mark = "ok  "
        elif status == "fail":
            fail += 1
            mark = "FAIL"
            failures.append(f"{rel}  {detail}")
        elif status == "no_tests":
            no_tests += 1
            mark = "????"
            failures.append(f"{rel}  文件里一个用例都没有（不是过，也不许当没看见）：{detail}")
        else:
            unknown += 1
            mark = "????"
            failures.append(f"{rel}  没查成：{detail}")
        if not args.quiet or status != "ok":
            print(f"[{mark}] {rel}  {detail}")

    secs = time.monotonic() - t0
    print(
        f"[per-file] 共 {len(files)} 个文件：过 {ok} / 单独跑不过 {fail} / 全被配置筛掉 {deselected}"
        f" / 整文件 xfail 或 xpass {all_xfail} / 一个用例都没有 {no_tests}"
        f" / 没查成 {unknown} / 已豁免的整文件跳过 {exempt}"
        f"（{secs:.1f}s）"
    )
    if fail:
        print("以下文件在全量里可能是绿的，但单独跑不过 —— 那说明绿灯是排序给的：")
        for line in failures:
            print(f"  - {line}")
        return 1
    if no_tests or unknown:
        print("有文件没能查成（不是过）：")
        for line in failures:
            print(f"  - {line}")
        return 2
    return 0


if __name__ == "__main__":  # pragma: no cover - 由 tests 直接调 main()
    raise SystemExit(main())

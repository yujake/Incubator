#!/usr/bin/env python
"""把 `tests/` 按文件分成 N 路并行跑全量，并把「分块 / 命令 / 红」一起落盘。

为什么要有一个常设脚本（而不是继续在 `temp/` 里手搓）：一条全量要跑几十分钟，
手搓的每一趟分块都不一样，红的名字对不上是哪一路，日志还会互相覆盖。这个脚本
把三件事变成可复现的：

  · 分块：`manifest`（仓库相对路径 + 字节数）排序后按字节做 LPT 均衡，
    `plan_sha256` 把这一趟的分块钉住，结论里能带指纹；
  · 汇总：退出码只有三档（0 全绿 / 1 有红且都查得成 / 2 有任何一路没查成），
    红条目带 chunk 与那一路的完整 argv；
  · 证据：每路一个独立日志文件，直接重定向，不建管道；run 目录带 run-id，
    默认全部保留（`MAX_LOG_BYTES` 只负责在失控时停跑并提示，不删任何日志）。

退出码：0 全绿 / 1 有红且每一路都查得成 / 2 有任何一路没查成（unknown 不是 pass）。

`--jobs 1` 与直接 `python -m pytest` 的收集顺序等价（用于定位顺序依赖）：整棵树
不逐个列文件（路径字符数会撞 Windows 的 32767 上限），而是把 `tests` 交给 pytest
—— 与 `pyproject.toml` 的 `testpaths = ["tests"]` 是同一次收集。用法与全部开关见
`python -B scripts/pytest_all.py --help`。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

#: 默认并发数。4 是实测可用值：再高时磁盘与 CPU 抢占会把单路拖慢。
DEFAULT_JOBS = 4

#: 两种分块口径。默认 size-balance：按文件字节数做 LPT，避免一个大文件拖死一路。
CHUNK_BYS = ("size-balance", "round-robin")

#: 每路的 pytest 参数。`--tb=short` 而不是 `--tb=no`：后者连 Captured stdout 都不打，
#: 服务端日志会在日志文件里一行不落（实测）。`-p no:cacheprovider` 避开多进程写同一个
#: `.pytest_cache`；`tests/` 里没有用例用 `cache` fixture 或 `config.cache`（grep 0 处）。
#: 刻意不加 `-p no:randomly`：本机没装；装了之后它会改每路内部顺序，破坏 `--jobs 1` 等价。
PYTEST_FLAGS: tuple[str, ...] = ("-q", "--tb=short", "-p", "no:cacheprovider")

#: 过滤后的子集逐个列文件时的安全上限（字符）。Windows 的整条命令行上限是 32767，
#: 这里留出解释器路径、flags 与引号的余量。
MAX_ARGV_CHARS = 24_000
WINDOWS_CMDLINE_LIMIT = 32_767

#: 本次 run 目录里所有 chunk 日志的总字节上限。超了就停跑并提示，绝不默默删日志。
MAX_LOG_BYTES = 500 * 1024 * 1024

#: pytest 汇总行里的计数（`3 failed, 5 passed in 10.00s`）。
SUMMARY_COUNT_RE = re.compile(
    r"(\d+)\s+(passed|failed|errors?|skipped|xfailed|xpassed|deselected|warnings?)\b"
)
#: 只把「... in 12.34s」这种行当汇总行，避免把用例 stdout 里的「5 passed」当真。
SUMMARY_LINE_RE = re.compile(r"\bin \d+(?:\.\d+)?s\b")

#: short test summary info 里的失败/错误行。
FAIL_LINE_RE = re.compile(r"^(FAILED|ERROR) (.+)$")


class ArgvTooLong(RuntimeError):
    """一路的文件多到命令行超过安全阈值（只可能发生在过滤后的单路）。"""


def _pin_utf8() -> None:
    """把 stdout/stderr 钉成 utf-8。

    规范实现见 `src/agentflow/console.py::pin_utf8`；这里内联一份，理由与
    `scripts/lint_rules.py` / `scripts/noai_gate.py` 同：脚本必须在包 import 不了时也能跑。
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            # 被重定向或被替换过的流可能没有 reconfigure，不该让脚本崩掉。
            pass


@dataclass(frozen=True)
class FileEntry:
    """一个测试文件：仓库相对 posix 路径 + 字节数（size-balance 的输入）。"""

    rel: str
    size: int


@dataclass
class Manifest:
    """一次跑要覆盖的文件清单；顺序是「按仓库相对 posix 路径排序」。"""

    files: list[FileEntry]

    @property
    def total_bytes(self) -> int:
        """清单的总字节数。"""
        return sum(entry.size for entry in self.files)


@dataclass
class ChunkPlan:
    """一路的计划：有序的文件清单（manifest 顺序）与它的字节数。"""

    index: int
    files: list[str]
    bytes: int


@dataclass
class ChunkRead:
    """从一份 pytest 日志里读出来的东西。"""

    counts: dict[str, int]
    failures: list[tuple[str, str, str]]  # (kind, nodeid, raw)
    summary: str
    complete: bool


@dataclass
class Failure:
    """一条红：带 chunk 归属与原始行（参数化 id 含空格时以 raw 为准）。"""

    chunk: int
    nodeid: str
    kind: str
    raw: str


@dataclass
class ChunkResult:
    """一路的最终结果。"""

    index: int
    rc: int | None
    status: str
    seconds: float
    counts: dict[str, int]
    failures: list[Failure]
    log: str
    command: list[str]
    log_kept: bool = True
    note: str = ""


def build_manifest(root: Path) -> Manifest:
    """按 pytest 的默认收集口径（`test_*.py` 与 `*_test.py`，递归）列文件。

    为什么不用 `glob("test_*.py")`：`pyproject.toml` 的 `testpaths = ["tests"]` 是递归的，
    只扫顶层会在子目录里漏文件，于是 runner 绿而 `pytest` 红（`tools/run_each_test_file.py`
    记过同一个形态）。为什么排序用 posix 字符串：`WindowsPath` 比较是大小写折叠的，
    跨平台不可比；分块指纹必须只由「路径 + 字节数」决定。
    """
    base = root / "tests"
    found: dict[str, Path] = {}
    for pattern in ("test_*.py", "*_test.py"):
        for path in base.rglob(pattern):
            if path.is_file() and "__pycache__" not in path.parts:
                found[path.relative_to(root).as_posix()] = path
    entries = [FileEntry(rel, path.stat().st_size) for rel, path in sorted(found.items())]
    return Manifest(entries)


def build_plan(manifest: Manifest, jobs: int, chunk_by: str) -> list[ChunkPlan]:
    """按 `chunk_by` 把清单分给 `jobs` 路；每路内部一律按 manifest 顺序排。

    为什么不把 size-balance 的「大文件先放」顺序原样交给 pytest：那样一路内部的
    相对顺序会随分块变化，定位顺序依赖时多了一个变量。分配按字节、执行按清单顺序，
    于是「换 chunk 组成」是唯一变量。
    """
    entries = manifest.files
    if not entries:
        return []
    jobs = max(1, min(jobs, len(entries)))
    if jobs == 1:
        return [ChunkPlan(0, [entry.rel for entry in entries], manifest.total_bytes)]
    if chunk_by == "round-robin":
        buckets = [
            [entries[i] for i in range(len(entries)) if i % jobs == index]
            for index in range(jobs)
        ]
    elif chunk_by == "size-balance":
        buckets: list[list[FileEntry]] = [[] for _ in range(jobs)]
        sums = [0] * jobs
        for entry in sorted(entries, key=lambda item: (-item.size, item.rel)):
            target = min(range(jobs), key=lambda index: (sums[index], index))
            buckets[target].append(entry)
            sums[target] += entry.size
        order = {entry.rel: index for index, entry in enumerate(entries)}
        buckets = [sorted(bucket, key=lambda item: order[item.rel]) for bucket in buckets]
    else:  # pragma: no cover - argparse 的 choices 已经挡住；留着是为了 fail-closed
        raise ValueError(f"未知的分块口径：{chunk_by}")
    return [
        ChunkPlan(index, [entry.rel for entry in bucket], sum(entry.size for entry in bucket))
        for index, bucket in enumerate(buckets)
    ]


def manifest_fingerprint(manifest: Manifest) -> str:
    """清单指纹：只覆盖「路径 + 字节数」，与 jobs / 分块口径无关。"""
    digest = hashlib.sha256()
    for entry in manifest.files:
        digest.update(f"{entry.rel}\t{entry.size}\n".encode("utf-8"))
    return digest.hexdigest()


def plan_fingerprint(manifest: Manifest, jobs: int, chunk_by: str) -> str:
    """分块指纹：覆盖清单、jobs 与分块口径；两趟想比「是不是同一套分块」就看它。"""
    digest = hashlib.sha256()
    digest.update(f"jobs={jobs}\nchunk_by={chunk_by}\n".encode("utf-8"))
    for entry in manifest.files:
        digest.update(f"{entry.rel}\t{entry.size}\n".encode("utf-8"))
    return digest.hexdigest()


def pytest_argv(
    files: list[str], all_files: list[str], passthrough: bool
) -> list[str]:
    """拼一路的 pytest argv。

    整棵树（`files` 与 `all_files` 是同一个集合）走 `tests` 捷径：测试文件数已多到
    相对路径合计逼近 Windows 32767 的命令行上限。过滤后的子集才逐个列，超过
    `MAX_ARGV_CHARS` 就抛 `ArgvTooLong`（调用方按「没查成」处理，不静默截断）。
    """
    argv = [sys.executable, "-B", "-m", "pytest", *PYTEST_FLAGS]
    if passthrough:
        argv.append("-s")
    if set(files) == set(all_files):
        argv.append("tests")
        return argv
    if sum(len(item) + 1 for item in files) > MAX_ARGV_CHARS:
        raise ArgvTooLong(
            f"过滤后仍有 {len(files)} 个文件、命令行约 "
            f"{sum(len(item) + 1 for item in files)} 字符 > {MAX_ARGV_CHARS}；"
            "请收窄 --filter，或加 --jobs 把这一路拆开"
        )
    argv.extend(files)
    return argv


def _file_of(body: str, files: list[str]) -> str:
    """从 `FAILED/ERROR` 行剩余部分认出它属于清单里的哪个文件；认不出返回空串。

    pytest 在 Windows 上会把 short summary 里的路径写成反斜杠（即使参数里给的是
    `/`），所以两边都先归一成 posix 再比 —— 否则一条红都认领不到，rc=1 会被误判成
    `inconsistent`（实测踩过）。
    """
    normalized = body.replace("\\", "/")
    best = ""
    for rel in files:
        if (
            normalized == rel
            or normalized.startswith(rel + "::")
            or normalized.startswith(rel + " ")
        ):
            if len(rel) > len(best):
                best = rel
    return best


def parse_chunk_log(path: Path, files: list[str]) -> ChunkRead:
    """流式读一份 pytest 日志：汇总计数 + FAILED/ERROR 行，不把整份日志读进内存。"""
    counts: dict[str, int] = {}
    summary = ""
    failures: list[tuple[str, str, str]] = []
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for raw_line in handle:
                line = raw_line.rstrip("\r\n")
                if not line.strip():
                    continue
                matched = FAIL_LINE_RE.match(line)
                if matched:
                    kind = matched.group(1).lower()
                    body = matched.group(2)
                    if _file_of(body, files):
                        nodeid = body.split(" - ", 1)[0].replace("\\", "/")
                        failures.append((kind, nodeid, line))
                if SUMMARY_LINE_RE.search(line):
                    found = SUMMARY_COUNT_RE.findall(line)
                    if found:
                        summary = line
                        counts = {}
                        for number, word in found:
                            key = "error" if word.startswith("error") else word
                            if key.startswith("warning"):
                                continue
                            counts[key] = counts.get(key, 0) + int(number)
    except OSError:
        return ChunkRead({}, [], "", False)
    return ChunkRead(counts, failures, summary, bool(summary))


def classify_rc(rc: int, read: ChunkRead) -> str:
    """把 `(rc, 日志读数)` 映射成一路的状态；三态纪律：unknown 绝不折成 pass。

    关键的一格是 `rc=1` 且日志里只有 `ERROR`（collection error / setup error）：
    只匹配 `^FAILED` 会把它数成 `failed_count=0`。这里把 `error` 计入红，
    并且要求「汇总行的 failed/error 数」与「日志里认领到的行数」一致；不一致就判
    `inconsistent`（退出码 2），不拿一份读漏的日志冒充完整结论。
    """
    counts = read.counts
    failed_total = counts.get("failed", 0) + counts.get("error", 0)
    parsed_failed = sum(1 for kind, _, _ in read.failures if kind == "failed")
    parsed_error = sum(1 for kind, _, _ in read.failures if kind == "error")

    if rc == 0:
        if failed_total or parsed_failed or parsed_error:
            return "inconsistent"
        if counts.get("passed", 0) > 0:
            return "green"
        if counts.get("skipped", 0) > 0:
            return "all-skipped"
        if counts.get("xfailed", 0) or counts.get("xpassed", 0):
            return "all-xfail"
        return "no-tests" if read.complete else "inconsistent"

    if not read.complete:
        return {
            2: "interrupted",
            3: "internal-error",
            4: "usage-error",
            5: "no-tests",
        }.get(rc, "inconsistent")

    if rc == 1:
        if parsed_failed != counts.get("failed", 0) or parsed_error != counts.get("error", 0):
            return "inconsistent"
        return "red" if failed_total else "inconsistent"

    if rc == 5:
        return "deselected" if counts.get("deselected", 0) else "no-tests"
    if rc == 2:
        return "interrupted"
    if rc == 3:
        return "internal-error"
    if rc == 4:
        return "usage-error"
    return "inconsistent"


def read_chunk(
    index: int,
    rc: int | None,
    log_path: Path,
    files: list[str],
    command: list[str],
    seconds: float,
    *,
    status: str | None = None,
    note: str = "",
    log_label: str = "",
) -> ChunkResult:
    """读日志 + 定状态，装成一个 `ChunkResult`（`status` 用于超时/停跑等外部判定）。"""
    read = parse_chunk_log(log_path, files)
    final_status = status or classify_rc(int(rc or 0), read)
    failures = [
        Failure(chunk=index, nodeid=nodeid, kind=kind, raw=raw)
        for kind, nodeid, raw in read.failures
    ]
    return ChunkResult(
        index=index,
        rc=rc,
        status=final_status,
        seconds=seconds,
        counts=dict(read.counts),
        failures=failures,
        log=log_label or str(log_path),
        command=list(command),
        note=note,
    )


def exit_bucket(status: str) -> int:
    """状态 → 退出码档位：0 绿 / 1 红 / 2 没查成。"""
    if status == "green":
        return 0
    if status == "red":
        return 1
    return 2


def aggregate(results: list[ChunkResult]) -> int:
    """整趟退出码：全绿 0；有红且每路都查得成 1；有任何一路没查成 2。

    2 优先于 1：一路超时/中断意味着它的文件根本没跑完，此时「红的就是这些」
    这句话是假的。三态纪律比「先报红」重要。
    """
    buckets = [exit_bucket(result.status) for result in results]
    if not buckets:
        return 2
    if all(bucket == 0 for bucket in buckets):
        return 0
    if any(bucket == 2 for bucket in buckets):
        return 2
    return 1


def totals(results: list[ChunkResult]) -> dict[str, int]:
    """把各路的计数加起来（passed/failed/error/skipped/xfailed/xpassed/deselected）。"""
    keys = ("passed", "failed", "error", "skipped", "xfailed", "xpassed", "deselected")
    out = {key: 0 for key in keys}
    for result in results:
        for key in keys:
            out[key] += int(result.counts.get(key, 0))
    out["failures"] = sum(len(result.failures) for result in results)
    out["chunks"] = len(results)
    return out


def _write_text(path: Path, text: str) -> None:
    """写文本并显式钉住 `\\n`（R012：Windows 上默认会把 `\\n` 刷成 `\\r\\n`）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def _relative(root: Path, path: Path) -> str:
    """尽量给仓库相对路径；给不出就原样返回。"""
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def _plan_text(
    manifest: Manifest, plan: list[ChunkPlan], jobs: int, chunk_by: str, digest: str
) -> str:
    """`plan.txt` 的内容：指纹 + 每路的有序文件清单（结论里引用它）。"""
    lines = [
        f"# manifest_sha256 = {manifest_fingerprint(manifest)}",
        f"# plan_sha256 = {digest}",
        f"# jobs = {jobs}  chunk_by = {chunk_by}  files = {len(manifest.files)}"
        f"  bytes = {manifest.total_bytes}",
    ]
    for chunk in plan:
        lines.append(f"[chunk {chunk.index}] files={len(chunk.files)} bytes={chunk.bytes}")
        lines.extend(chunk.files)
    return "\n".join(lines) + "\n"


def _chunk_line(result: ChunkResult) -> str:
    """一路的进度行（打印到 stdout；失败详情在最后的失败清单里）。"""
    rc = "-" if result.rc is None else str(result.rc)
    counts = result.counts
    return (
        f"[pytest-all] chunk {result.index}  rc={rc}  {result.status}"
        f"  passed={counts.get('passed', 0)} failed={counts.get('failed', 0)}"
        f" error={counts.get('error', 0)} skipped={counts.get('skipped', 0)}"
        f"  {result.seconds}s  log={result.log}"
        + (f"  note={result.note}" if result.note else "")
    )


def _shell_join(argv: list[str]) -> str:
    """把 argv 拼成一行给人看（只用于 `.cmd.txt`；不经过 shell 执行）。"""
    return " ".join(argv)


def _build_parser() -> argparse.ArgumentParser:
    """CLI。与 `scripts/lint_rules.py` / `scripts/noai_gate.py` 同风格：argparse + 中文说明。"""
    parser = argparse.ArgumentParser(
        prog="pytest_all",
        allow_abbrev=False,
        description=(
            "把 tests/test_*.py 分成 N 路并行跑全量；退出码 0=全绿 / 1=有红且都查得成 /"
            " 2=有任何一路没查成。分块与每路命令都落盘，结论可复现。"
        ),
    )
    parser.add_argument("--jobs", type=int, default=DEFAULT_JOBS,
                        help=f"并发路数（默认 {DEFAULT_JOBS}；1 = 串行，与直接 pytest 同序）")
    parser.add_argument("--filter", default="", metavar="SUBSTR",
                        help="只跑仓库相对路径里含该子串的文件（只在命令行显式给；默认不筛）")
    parser.add_argument("--chunk-by", choices=CHUNK_BYS, default="size-balance",
                        help="分块口径：size-balance 按文件字节均衡（默认），round-robin 轮流发")
    parser.add_argument("--keep-logs", action="store_true",
                        help="显式声明保留全部日志；当前默认就是全留（本开关不改变行为）")
    parser.add_argument("--json", default="", metavar="PATH",
                        help="额外把同一份 summary 写到该路径（run 目录里永远有 summary.json）")
    parser.add_argument("--dry-run", action="store_true",
                        help="只打印分块与 pytest 参数，不建目录、不写日志、不起任何进程")
    parser.add_argument("--passthrough", action="store_true",
                        help="给每路加 -s：e2e 判据要它才看得到服务端日志（默认不加）")
    parser.add_argument("--timeout-sec", type=float, default=None, metavar="N",
                        help="单路超时兜底（秒）；默认不设。只用于某一路卡死，不用它掩盖慢")
    parser.add_argument("--root", default=None,
                        help="仓库根（默认本文件的上两级）；与 lint_rules / noai_gate 同构")
    return parser


def main(argv: list[str] | None = None) -> int:
    """入口：解析参数 → 分块 → 跑 → 汇总。返回三档退出码。"""
    _pin_utf8()
    parser = _build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.jobs < 1:
        parser.error("--jobs 必须 ≥ 1（1 = 串行）")
    if args.timeout_sec is not None and args.timeout_sec <= 0:
        parser.error("--timeout-sec 必须 > 0；默认不设超时")

    root = Path(args.root).resolve() if args.root else Path(__file__).resolve().parents[1]
    tests_dir = root / "tests"
    if not tests_dir.is_dir():
        print(f"[pytest-all] 读不到 {tests_dir} —— 没查成（退出码 2）", file=sys.stderr)
        return 2

    manifest = build_manifest(root)
    # 整棵树的路径清单必须在 --filter 之前取：`pytest_argv` 只在「这一路就是整棵树」时
    # 才走 `tests` 捷径。若拿过滤后的清单当 `all_files`，`--filter test_x.py --jobs 1`
    # 会被误判成整棵树，于是把全部用例都跑一遍（实测踩过）。
    all_files = [entry.rel for entry in manifest.files]
    if args.filter:
        kept = [entry for entry in manifest.files if args.filter in entry.rel]
        if not kept:
            print(
                f"[pytest-all] --filter {args.filter!r} 一个文件都没匹配到 —— 没查成（退出码 2）",
                file=sys.stderr,
            )
            return 2
        manifest = Manifest(kept)
    if not manifest.files:
        print(f"[pytest-all] {tests_dir} 下没有 test_*.py —— 没查成（退出码 2）", file=sys.stderr)
        return 2

    requested = args.jobs
    jobs = min(requested, len(manifest.files))
    if jobs != requested:
        print(f"[pytest-all] --jobs {requested} > 文件数 {len(manifest.files)} ⇒ 实跑 {jobs} 路")
    plan = build_plan(manifest, jobs, args.chunk_by)
    digest = plan_fingerprint(manifest, jobs, args.chunk_by)

    print(
        f"[pytest-all] 计划：jobs={jobs} chunk_by={args.chunk_by}"
        f" files={len(manifest.files)} bytes={manifest.total_bytes}"
        f" plan_sha256={digest}"
    )
    print(
        "[pytest-all] pytest 参数："
        + _shell_join(list(PYTEST_FLAGS) + (["-s"] if args.passthrough else []))
    )
    for chunk in plan:
        print(f"[chunk {chunk.index}] files={len(chunk.files)} bytes={chunk.bytes}")
        for rel in chunk.files:
            print(f"    {rel}")
    if args.dry_run:
        return 0

    run_id = time.strftime("%Y%m%d-%H%M%S")
    run_dir = root / "temp" / "pytest-all" / run_id
    suffix = 2
    while run_dir.exists():
        run_dir = root / "temp" / "pytest-all" / f"{run_id}-{suffix}"
        suffix += 1
    try:
        run_dir.mkdir(parents=True)
    except OSError as exc:
        print(f"[pytest-all] 建不了 run 目录 {run_dir}：{exc} —— 没查成（退出码 2）",
              file=sys.stderr)
        return 2
    _write_text(run_dir / "plan.txt", _plan_text(manifest, plan, jobs, args.chunk_by, digest))

    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"  # 只为日志解码；不覆盖 PYTHONPATH、不改 PYTHONUTF8
    started = time.monotonic()
    run_started_at = time.strftime("%Y-%m-%d %H:%M:%S")
    results: dict[int, ChunkResult] = {}
    pending: dict[int, tuple[subprocess.Popen[bytes], object, Path, list[str], float]] = {}

    for chunk in plan:
        log_path = run_dir / f"chunk-{chunk.index}.log"
        command_path = run_dir / f"chunk-{chunk.index}.cmd.txt"
        try:
            argv = pytest_argv(chunk.files, all_files, args.passthrough)
        except ArgvTooLong as exc:
            result = ChunkResult(chunk.index, None, "argv-too-long", 0.0, {}, [],
                                 _relative(root, log_path), [], True, str(exc))
            results[chunk.index] = result
            print(_chunk_line(result), flush=True)
            continue
        _write_text(command_path, _shell_join(argv) + "\n")
        try:
            handle = log_path.open("w", encoding="utf-8")
            process = subprocess.Popen(
                argv,
                cwd=str(root),
                stdout=handle,
                stderr=subprocess.STDOUT,
                env=env,
            )
        except OSError as exc:
            try:
                handle.close()  # type: ignore[possibly-undefined]
            except (NameError, OSError):
                pass
            result = ChunkResult(
                chunk.index, None, "spawn-error", 0.0, {}, [],
                _relative(root, log_path), argv, True,
                f"起不了进程：{type(exc).__name__}: {exc}",
            )
            results[chunk.index] = result
            print(_chunk_line(result), flush=True)
            continue
        pending[chunk.index] = (process, handle, log_path, argv, time.monotonic())

    log_cap_hit = False
    while pending:
        now = time.monotonic()
        for index in list(pending):
            process, handle, log_path, argv, chunk_started = pending[index]
            rc = process.poll()
            if rc is None:
                continue
            del pending[index]
            process.wait()
            handle.close()  # type: ignore[union-attr]
            seconds = round(time.monotonic() - chunk_started, 1)
            result = read_chunk(
                index, rc, log_path, plan[index].files, argv, seconds,
                log_label=_relative(root, log_path),
            )
            results[index] = result
            print(_chunk_line(result), flush=True)

        for index in list(pending):
            process, handle, log_path, argv, chunk_started = pending[index]
            if args.timeout_sec is not None and now - chunk_started > args.timeout_sec:
                del pending[index]
                process.kill()
                process.wait()
                handle.close()  # type: ignore[union-attr]
                seconds = round(time.monotonic() - chunk_started, 1)
                result = read_chunk(
                    index, None, log_path, plan[index].files, argv, seconds,
                    status="timeout",
                    note=f"超过 --timeout-sec {args.timeout_sec} 被终止；超时只用于兜底，不是节拍器",
                    log_label=_relative(root, log_path),
                )
                results[index] = result
                print(_chunk_line(result), flush=True)

        if pending and _log_bytes(run_dir) > MAX_LOG_BYTES:
            log_cap_hit = True
            for index in list(pending):
                process, handle, log_path, argv, chunk_started = pending.pop(index)
                process.kill()
                process.wait()
                handle.close()  # type: ignore[union-attr]
                seconds = round(time.monotonic() - chunk_started, 1)
                result = read_chunk(
                    index, None, log_path, plan[index].files, argv, seconds,
                    status="log-budget",
                    note="本次日志总量超过阈值，停跑（不删任何日志）",
                    log_label=_relative(root, log_path),
                )
                results[index] = result
                print(_chunk_line(result), flush=True)
            break
        if pending:
            time.sleep(0.5)

    wall = round(time.monotonic() - started, 1)
    ordered = [results[chunk.index] for chunk in plan]
    total = totals(ordered)
    code = aggregate(ordered)
    if log_cap_hit:
        print(
            f"[pytest-all] 日志已超过 {MAX_LOG_BYTES // (1024 * 1024)} MB 阈值 ⇒ 停跑（没有删任何日志）。\n"
            "[pytest-all] 请先清理 temp/pytest-all/ 的旧 run，或提高 --jobs 让单路更快结束，"
            "或缩小 --filter 后重跑。",
            flush=True,
        )

    failures = [failure for result in ordered for failure in result.failures]
    payload = {
        "schema_version": 1,
        "run_id": run_dir.name,
        "root": str(root),
        "started_at": run_started_at,
        "wall_seconds": wall,
        "jobs_requested": requested,
        "jobs": jobs,
        "chunk_by": args.chunk_by,
        "passthrough": bool(args.passthrough),
        "pytest_flags": list(PYTEST_FLAGS) + (["-s"] if args.passthrough else []),
        "manifest_sha256": manifest_fingerprint(manifest),
        "plan_sha256": digest,
        "files": len(manifest.files),
        "bytes": manifest.total_bytes,
        "chunks": [
            {
                "index": result.index,
                "rc": result.rc,
                "status": result.status,
                "seconds": result.seconds,
                "counts": result.counts,
                "files": plan[result.index].files,
                "bytes": plan[result.index].bytes,
                "failures": [failure.__dict__ for failure in result.failures],
                "log": result.log.replace("\\", "/"),
                "log_kept": True,
                "command": result.command,
                "note": result.note,
            }
            for result in ordered
        ],
        "failures": [
            {
                "chunk": failure.chunk,
                "nodeid": failure.nodeid,
                "kind": failure.kind,
                "raw": failure.raw,
            }
            for failure in failures
        ],
        "totals": total,
        "exit_code": code,
    }
    summary_text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    _write_text(run_dir / "summary.json", summary_text)
    _write_text(
        run_dir / "failures.txt",
        "".join(
            f"chunk {failure.chunk}\t{failure.kind}\t{failure.nodeid}\t{failure.raw}\n"
            for failure in failures
        ),
    )
    if args.json:
        try:
            _write_text(Path(args.json), summary_text)
        except OSError as exc:
            print(f"[pytest-all] 写不了 --json {args.json}：{exc} —— 没查成（退出码 2）",
                  file=sys.stderr)
            return 2

    print(
        f"[pytest-all] 汇总：files={len(manifest.files)} jobs={jobs}"
        f" passed={total['passed']} failed={total['failed']} error={total['error']}"
        f" skipped={total['skipped']}；红 {total['failures']} 条；墙钟 {wall}s",
        flush=True,
    )
    print(
        f"[pytest-all] 分块指纹 plan_sha256={digest}"
        f"（plan.txt：{_relative(root, run_dir / 'plan.txt')}）",
        flush=True,
    )
    if failures:
        print("[pytest-all] 失败清单：", flush=True)
        for failure in failures:
            print(
                f"  - chunk {failure.chunk}  {failure.nodeid}  [{failure.kind}]"
                f"  （日志 {results[failure.chunk].log}；"
                f"命令 {_relative(root, run_dir / f'chunk-{failure.chunk}.cmd.txt')}）",
                flush=True,
            )
    if code == 0:
        print("[pytest-all] 结论：全绿（退出码 0）", flush=True)
    elif code == 1:
        print("[pytest-all] 结论：有红（退出码 1）", flush=True)
    else:
        bad = [result for result in ordered if exit_bucket(result.status) == 2]
        print(
            f"[pytest-all] 结论：没查成（退出码 2）—— {len(bad)} 路没跑成/没读完："
            + "、".join(f"chunk {result.index}={result.status}" for result in bad),
            flush=True,
        )
    return code


def _log_bytes(run_dir: Path) -> int:
    """run 目录里所有 chunk 日志的当前总字节数（只用于日志总量兜底）。"""
    return sum(path.stat().st_size for path in run_dir.glob("chunk-*.log"))


if __name__ == "__main__":  # pragma: no cover - 由 tests 直接调 main()，这里只为手工运行
    raise SystemExit(main())

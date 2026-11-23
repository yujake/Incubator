# -*- coding: utf-8 -*-
"""check_all —— 一条命令跑完收口的所有门，末尾给一张总表与一句结论。

## 它解决什么

收口时要手工跑十来个命令再逐个读。本脚本按固定顺序把它们串起来，每项一行
`[ok|FAIL|SKIP] <项> <关键读数>`，最后一张总表与一句结论。它自己不写判据：
每一项都调用盘上那份权威工具（或它自己的判据文件），只负责编排与三态汇总。

## 项与顺序（固定；`--only` 只筛不改顺序）

| # | 项 | 判据（调谁） | 没查成（SKIP）的显式判据 |
|---|---|---|---|
| 1 | `three_cells` | `scripts/check_three_cells.py --json` | 脚本不在 / 产品根不在 / 读数 JSON 读不出 / 某格没值 |
| 2 | `lint` | `scripts/check_lint.py --json` | 脚本不在 / 读数 JSON 读不出 / 内层自相矛盾 |
| 3 | `prompt_digests` | `scripts/recompute_prompt_digests.py` | 脚本不在 / 输出里没有 11 格读数或版本行 |
| 4 | `eol` | `tools/eol_gate.py --json-out` | 脚本不在 / 读不出 JSON / 它自己报 unknown（缺 git） |
| 5 | `collect` | `pytest --collect-only` | 缺 `tests/` / 缺 pytest / 0 个用例被收集 / 自身失败 |
| 6 | `snapshot_agent` | `tests/test_agent_surface_snapshot.py::...` | 缺 `tests/` / 缺判据文件 / pytest 自己崩 |
| 7 | `snapshot_tool` | `tests/test_tool_surface_snapshot.py::...` | 同上 |
| 8 | `snapshot_verify` | `tests/test_verify_snapshot.py::...` | 同上 |
| 9 | `doc_numbers` | `scripts/check_doc_numbers.py --json` | 脚本不在 / 读数读不出 / 有没量到的键 |
| 10 | `gate_closing` | `scripts/check_closing_gate.py --workspace` | 没有工作区 / 工作区不在 / 报告形状没给 |
| 11 | `gate_landing` | `scripts/check_landing_gates.py --workspace` | 同上 |
| 12 | `gate_declaration` | `scripts/check_declaration.py --workspace` | 同上 |
| 13 | `wellformed` | `scripts/check_wellformed.py --root <ws>` | 同上 |
| 14 | `doc_refs` | `scripts/check_doc_refs.py --json <path>` | 脚本不在 / 它有没查成的引用 |
| 15 | `pytest_full` | `pytest -q`（只有 `--slow` 才有这一项） | 缺 `tests/` / 缺 pytest / 自身失败 |

## 三态（与仓库纪律同一条）

- `0` = 所有项都查了、都一致（没有任何 SKIP）；
- `1` = 至少一项查过且不一致（有 FAIL）；
- `2` = 没有 FAIL，但至少一项没查成（SKIP：缺工作区 / 缺 git / 缺依赖 / 缺 `tests/`）。

FAIL 优先于 SKIP：有失败时退出码是 1，而结论行会同时点名没查成的项 ——
不让一个 1 被读成"全都查过了、只是有几处红"。没查成不是通过。

## 用法（在 `agentflow/` 下）

    python scripts/check_all.py                     # 全部门，默认不含全量 pytest
    python scripts/check_all.py --json              # 机器读数
    python scripts/check_all.py --only lint         # 只跑一项（定位用；可逗号列多项）
    python scripts/check_all.py --slow              # 额外跑全量 pytest（很慢，默认不跑）
    python scripts/check_all.py --workspace projects/lp-ball-15
    python scripts/check_all.py --selftest          # a–d 四条判据的反真空自测

工作区缺省是自动挑：`<产品根>/projects/` 与 `<产品根>/../projects/` 下含 `data/`
或 `.agentflow-workspace` 的目录里最近动过的那个（目录 mtime 最新；本仓库的
`projects/` 在 git 根，即 `<产品根>/../projects/`）。挑不到 ⇒ 四条依赖工作区的项记 SKIP。

`tests/` 不随仓库交付（业主 2026-11-21 裁定）：干净 clone 里 `collect` 与三条快照判据
记 SKIP，不是 pass。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

PROG = "check_all"

EXIT_OK = 0
EXIT_BAD = 1
EXIT_UNKNOWN = 2

#: 单项的缺省超时（秒）。超时按"没查成"记 SKIP，绝不按"0 条问题"记通过。
DEFAULT_TIMEOUT = 1800

#: 三格的格名与顺序（与 `check_three_cells.BASELINE` 同一组键）。
_CELL_KEYS = ("gt800", "fn200", "dup")

#: 摘要工具的版本行：`版本：现算 p318 / 冻结 p318`。
_VERSION_RE = re.compile(r"现算\s+(\S+)\s*/\s*冻结\s+(\S+)")
#: 摘要工具逐格的行首：`  [DRIFT] A 现算 …`。
_ROLE_RE = re.compile(r"\]\s+([A-Za-z][A-Za-z0-9]*)\s+现算")

#: pytest 收集期的收尾行：`12916/12944 tests collected (28 deselected)`。
_COLLECT_RE = re.compile(r"(\d+)/(\d+) tests collected")
_COLLECT_ONE_RE = re.compile(r"(\d+) tests collected")

#: 全量 pytest 的收尾读数：`12 failed, 12890 passed, 28 deselected in 900.1s`。
_PYTEST_TAIL_RE = re.compile(r"(\d+ (?:passed|failed|error|errors)(?:, .*)?) in [\d.]+s")


@dataclass
class Result:
    """一项门的读数。`state` 只有三档：ok / fail / skip（skip 就是"没查成"）。"""

    state: str
    reading: str
    detail: str = ""
    exit_code: int | None = None
    key: str = ""
    title: str = ""
    elapsed_sec: float = 0.0
    evidence: dict = field(default_factory=dict)

    @property
    def mark(self) -> str:
        """人读的状态标记（与三态退出码一一对应）。"""
        return {"ok": "ok", "fail": "FAIL", "skip": "SKIP"}[self.state]


@dataclass(frozen=True)
class Ctx:
    """一趟检查的上下文：产品根、工作区、超时。"""

    root: Path
    workspace: Path | None
    workspace_note: str
    timeout: int = DEFAULT_TIMEOUT


# --------------------------------------------------------------------------- 基础件


def _pin_utf8() -> None:
    """钉住 stdout/stderr 的编码（GBK 重定向下打印 `⇒` 会抛，进程退 1 = 假红）。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def _clip(text: str, limit: int = 240) -> str:
    """把一段读数压成一行：去换行、掐长度。"""
    one = " ".join(str(text or "").split())
    return one if len(one) <= limit else one[: limit - 1] + "…"


def _tail(text: str, limit: int = 400) -> str:
    """取输出尾部（报错现场在最后几行，抬头那几行信息量最低）。"""
    clean = (text or "").strip()
    return clean if len(clean) <= limit else "…" + clean[-limit:]


def _load_json(text: str):
    """从一段文本里取出一个 JSON 对象；取不出就给 None（不抛）。"""
    raw = (text or "").strip()
    if not raw:
        return None
    try:
        doc = json.loads(raw)
        return doc if isinstance(doc, dict) else None
    except ValueError:
        pass
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        doc = json.loads(raw[start:end + 1])
    except ValueError:
        return None
    return doc if isinstance(doc, dict) else None


def _invoke(ctx: Ctx, argv: list[str], *, timeout: float | None = None,
            cwd: Path | None = None) -> tuple[int, str, str]:
    """跑一条子命令，返回 `(退出码, stdout, stderr)`；起不来时抛 OSError。"""
    env = dict(os.environ)
    # 子进程统一 UTF-8：本仓工具自己也会 _pin_utf8，但摘要工具不会，GBK 下 `⇒` 会抛。
    env["PYTHONUTF8"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    done = subprocess.run(
        argv,
        cwd=str(cwd or ctx.root),
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        timeout=timeout if timeout is not None else ctx.timeout,
    )
    return (done.returncode,
            done.stdout.decode("utf-8", "replace"),
            done.stderr.decode("utf-8", "replace"))


def _ok(reading: str, detail: str = "", evidence: dict | None = None) -> Result:
    """查过、一致。"""
    return Result(state="ok", reading=reading, detail=detail, exit_code=EXIT_OK,
                  evidence=dict(evidence or {}))


def _fail(reading: str, detail: str = "", exit_code: int = EXIT_BAD,
          evidence: dict | None = None) -> Result:
    """查过、不一致。"""
    return Result(state="fail", reading=reading, detail=detail, exit_code=exit_code,
                  evidence=dict(evidence or {}))


def _skip(reading: str, detail: str = "", exit_code: int = EXIT_UNKNOWN,
          evidence: dict | None = None) -> Result:
    """没查成 —— 缺对象 / 缺依赖 / 检查器自身失败。不是通过。"""
    return Result(state="skip", reading=reading, detail=detail, exit_code=exit_code,
                  evidence=dict(evidence or {}))


def _script(ctx: Ctx, rel: str) -> Path | None:
    """取产品根下的一只脚本；不在盘上就返回 None（调用方记 SKIP）。"""
    path = ctx.root / rel
    return path if path.is_file() else None


def _pytest_argv(ctx: Ctx, *extra: str) -> list[str]:
    """`python -B -m pytest` 的公共前缀（关缓存插件：不许往被查的树里写 `.pytest_cache`）。"""
    return [sys.executable, "-B", "-m", "pytest", "-p", "no:cacheprovider", *extra]


def _pytest_detail(text: str) -> str:
    """从 pytest 输出里取失败现场：优先 `FAILED` 摘要行，其次断言行与差异行。"""
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    picked = [line for line in lines if line.startswith("FAILED")]
    if not picked:
        picked = [line for line in lines if line.startswith("E ")]
    if not picked:
        picked = [line for line in lines if "≠" in line and not line.startswith(">")]
    if not picked:
        picked = lines[-4:]
    if len(picked) == 1 and " - " in picked[0]:
        picked = [picked[0].split(" - ", 1)[1]]
    return _clip(" | ".join(picked[:2]), 600)


def _collection_errors(text: str) -> str:
    """收集期错误的读数：`Interrupted: 14 errors during collection` 里的那个 14。"""
    match = re.search(r"(\d+) errors? during collection", text or "")
    return match.group(1) if match else ""


def _is_collection_error(text: str) -> bool:
    """pytest 的退出码 2 有两种含义：收集中断（这一条）与被 Ctrl-C 打断（不是这一条）。"""
    return bool(_collection_errors(text)) or "errors during collection" in (text or "") \
        or "error during collection" in (text or "")


def _workspace_missing(ctx: Ctx) -> Result | None:
    """依赖工作区的项共用的前置判据：没有工作区就 SKIP（不是通过）。"""
    if ctx.workspace is None:
        return _skip("没有工作区", ctx.workspace_note)
    return None


# --------------------------------------------------------------------------- 各门


def check_three_cells(ctx: Ctx) -> Result:
    """三格现算（>800 行文件 / >200 行函数 / 重复 docstring 段）与基线比。"""
    script = _script(ctx, "scripts/check_three_cells.py")
    if script is None:
        return _skip("缺 scripts/check_three_cells.py", "三格的计算入口不在盘上 ⇒ 没查成")
    code, out, err = _invoke(
        ctx, [sys.executable, "-B", str(script), "--root", str(ctx.root), "--json"])
    doc = _load_json(out)
    if doc is None:
        return _skip(f"exit {code}；读数 JSON 读不出", _tail(out or err))
    cells = doc.get("cells") or {}
    base = doc.get("baseline") or {}
    if code == EXIT_UNKNOWN or doc.get("state") == "unknown":
        return _skip("三格没算出来", str(doc.get("reason") or _tail(out or err)))
    values = "/".join(str((cells.get(name) or {}).get("value")) for name in _CELL_KEYS)
    bases = "/".join(str(base.get(name)) for name in _CELL_KEYS)
    scanned = (doc.get("survey") or {}).get("scanned") or {}
    reading = (f"{values}（基线 {bases}；src {scanned.get('src_files')} / "
               f"tests {scanned.get('tests_files')} .py）")
    over = [name for name, row in cells.items() if (row or {}).get("ok") is False]
    if code == EXIT_BAD or over:
        return _fail(reading, f"超线：{doc.get('reason') or '、'.join(over)}",
                     evidence={"cells": cells})
    if code != EXIT_OK:
        return _skip(f"退出码 {code}", _tail(out or err))
    missing = [name for name in _CELL_KEYS if (cells.get(name) or {}).get("value") is None]
    if missing:
        return _skip(reading, f"这些格没有读数：{missing} ⇒ 没查成")
    return _ok(reading, str(doc.get("reason") or ""), {"cells": cells})


def check_lint(ctx: Ctx) -> Result:
    """lint R001–R012：error 必须为 0（warning 不改退出码）。"""
    script = _script(ctx, "scripts/check_lint.py")
    if script is None:
        return _skip("缺 scripts/check_lint.py", "lint 的包装入口不在盘上 ⇒ 没查成")
    code, out, err = _invoke(
        ctx, [sys.executable, "-B", str(script), "--root", str(ctx.root), "--json"])
    doc = _load_json(out)
    if doc is None:
        return _skip(f"exit {code}；读数 JSON 读不出", _tail(out or err))
    counts = doc.get("counts") or {}
    scanned = doc.get("scanned") or {}
    reading = (f"error {counts.get('error')} / warning {counts.get('warning')} / "
               f"info {counts.get('info')}（规则 {len(doc.get('rules_run') or [])}；"
               f"src {scanned.get('src_py')} / tests {scanned.get('tests_py')} .py）")
    if code == EXIT_UNKNOWN or doc.get("state") == "unknown":
        return _skip("lint 没查成", str(doc.get("reason") or _tail(out or err)))
    errors = list(doc.get("errors") or [])
    if counts.get("error") and code == EXIT_OK:
        return _skip(reading, "内层说 0 条 error 却报了 error ⇒ 检查器自相矛盾，读数不可信")
    if code == EXIT_BAD or counts.get("error"):
        head = "；".join(f"{one.get('rule')} {one.get('path')}:{one.get('line')}"
                         for one in errors[:3] if isinstance(one, dict))
        return _fail(reading, head or str(doc.get("reason") or ""),
                     evidence={"errors": errors, "counts": counts})
    if code != EXIT_OK:
        return _skip(f"退出码 {code}", _tail(out or err))
    return _ok(reading, str(doc.get("reason") or ""), {"counts": counts})


def check_prompt_digests(ctx: Ctx) -> Result:
    """十一格提示词摘要与版本：现算 == 冻结表。"""
    script = _script(ctx, "scripts/recompute_prompt_digests.py")
    if script is None:
        return _skip("缺 scripts/recompute_prompt_digests.py",
                     "摘要的计算入口不在盘上 ⇒ 没查成")
    code, out, err = _invoke(ctx, [sys.executable, "-B", str(script)])
    text = out or err
    marks = [line for line in text.splitlines() if "[OK" in line or "[DRIFT" in line]
    drift = [line for line in marks if "[DRIFT" in line]
    version = _VERSION_RE.search(text)
    if not marks:
        return _skip(f"exit {code}；输出里没有逐格读数", _tail(text))
    if version is None:
        return _skip(f"exit {code}；输出里没有版本行", _tail(text))
    same_version = version.group(1) == version.group(2)
    reading = (f"格 {len(marks) - len(drift)}/{len(marks)} 一致；版本 "
               f"{version.group(1)}{'==' if same_version else '!='}{version.group(2)}")
    if code == EXIT_OK and drift:
        return _skip(reading, "工具以 0 结束却报了 DRIFT ⇒ 检查器自相矛盾，读数不可信")
    if code == EXIT_BAD or drift:
        roles = [m.group(1) for line in drift for m in [_ROLE_RE.search(line)] if m]
        return _fail(reading, f"漂了 {len(drift)} 格：{'、'.join(roles)}")
    if code != EXIT_OK:
        return _skip(f"退出码 {code}", _tail(text))
    if not same_version:
        return _fail(reading, "版本号现算与冻结不一致")
    return _ok(reading, "")


def check_eol(ctx: Ctx) -> Result:
    """行尾漂移：`git ls-files --eol` 里「入库 LF、工作区 CRLF」的已跟踪文件。"""
    script = _script(ctx, "tools/eol_gate.py")
    if script is None:
        return _skip("缺 tools/eol_gate.py", "行尾读数入口不在盘上 ⇒ 没查成")
    with tempfile.TemporaryDirectory(prefix="check-all-eol-") as tmp:
        out_json = Path(tmp) / "eol.json"
        code, out, err = _invoke(
            ctx, [sys.executable, "-B", str(script), "--root", str(ctx.root),
                  "--json-out", str(out_json), "--quiet"])
        try:
            doc = json.loads(out_json.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return _skip(f"exit {code}；读数文件读不出", _tail(out or err))
    if not isinstance(doc, dict):
        return _skip(f"exit {code}；读数不是一个对象", _tail(out or err))
    counts = doc.get("counts") or {}
    reading = f"漂移 {counts.get('drift')} / 已跟踪 {doc.get('tracked')}"
    if doc.get("status") != "ok":
        return _skip(reading, str(doc.get("why") or "它自己报 unknown ⇒ 没查成"))
    drift = list(doc.get("drift") or [])
    if code == EXIT_BAD or drift:
        head = "；".join(f"{one.get('path')} i/{one.get('index')} w/{one.get('worktree')}"
                         for one in drift[:3] if isinstance(one, dict))
        return _fail(reading, head or f"漂移 {len(drift)} 个")
    if code != EXIT_OK:
        return _skip(f"退出码 {code}", _tail(out or err))
    return _ok(reading, str(doc.get("why") or ""))


def check_collect(ctx: Ctx) -> Result:
    """收集期：`pytest --collect-only`（收集错误在这里红，而不是在某个用例里）。"""
    if not (ctx.root / "tests").is_dir():
        return _skip("缺 tests/", "tests 不随仓库交付（业主 2026-11-21 裁定）⇒ 收集期没查成")
    try:
        code, out, err = _invoke(ctx, _pytest_argv(ctx, "--collect-only", "-q"))
    except OSError as exc:
        return _skip("起不了 pytest", f"{type(exc).__name__}: {exc} ⇒ 没查成")
    text = out + "\n" + err
    two = _COLLECT_RE.search(text)
    one = _COLLECT_ONE_RE.search(text)
    if two:
        reading = f"{two.group(1)}/{two.group(2)} 个用例可收集"
    elif one:
        reading = f"{one.group(1)} 个用例可收集"
    else:
        reading = "收集期读数解析不了"
    if code == EXIT_OK:
        if two is None and one is None:
            return _skip(reading, _tail(text))
        return _ok(reading, "")
    if code == EXIT_BAD or _is_collection_error(text):
        counted = _collection_errors(text)
        if counted:
            reading = f"收集期有错：{counted} 个模块收不进来"
        elif code == EXIT_BAD:
            reading = "收集期有错"
        return _fail(reading, _tail(text))
    if code == 5:
        return _skip("0 个用例被收集（pytest 5）", "没收集到东西 ⇒ 没查成，不是没红")
    return _skip(f"pytest 自身以 {code} 结束", _tail(text))


#: 三条快照判据：判据文件、用例名、被对照的冻结件。
_SNAPSHOTS: dict[str, dict[str, str]] = {
    "snapshot_agent": {
        "file": "test_agent_surface_snapshot.py",
        "test": "test_the_agent_surface_matches_the_frozen_snapshot",
        "golden": "tests/golden/agent_surface_snapshot.json",
        "what": "agent 面",
    },
    "snapshot_tool": {
        "file": "test_tool_surface_snapshot.py",
        "test": "test_the_tool_surface_matches_the_frozen_snapshot",
        "golden": "tests/golden/tool_surface_snapshot.json",
        "what": "tool 面",
    },
    "snapshot_verify": {
        "file": "test_verify_snapshot.py",
        "test": "test_verify_output_matches_the_frozen_snapshot",
        "golden": "tests/golden/verify_all_snapshot.json",
        "what": "verify_all 面",
    },
}


def _check_snapshot(ctx: Ctx, key: str) -> Result:
    """跑一条冻结快照判据（只跑那一个用例，不改写判据本身）。"""
    spec = _SNAPSHOTS[key]
    if not (ctx.root / "tests").is_dir():
        return _skip("缺 tests/", "tests 不随仓库交付 ⇒ 这条快照判据没查成")
    test_file = ctx.root / "tests" / spec["file"]
    if not test_file.is_file():
        return _skip(f"缺 tests/{spec['file']}", "判据文件不在盘上 ⇒ 没查成")
    node = f"{test_file}::{spec['test']}"
    try:
        code, out, err = _invoke(
            ctx, _pytest_argv(ctx, "-q", "--no-header", node),
            timeout=min(ctx.timeout, 900))
    except OSError as exc:
        return _skip("起不了 pytest", f"{type(exc).__name__}: {exc} ⇒ 没查成")
    golden = spec["golden"]
    if code == EXIT_OK:
        return _ok(f"与 {golden} 一致", spec["what"])
    if code == EXIT_BAD:
        return _fail(f"与 {golden} 不一致", _pytest_detail(out + "\n" + err),
                     evidence={"golden": golden})
    if code == 5:
        return _skip("用例没被收集到（pytest 5）", _tail(out or err))
    return _skip(f"pytest 自身以 {code} 结束", _tail(out + "\n" + err))


def check_snapshot_agent(ctx: Ctx) -> Result:
    """快照判据之一：agent 面。"""
    return _check_snapshot(ctx, "snapshot_agent")


def check_snapshot_tool(ctx: Ctx) -> Result:
    """快照判据之二：tool 面。"""
    return _check_snapshot(ctx, "snapshot_tool")


def check_snapshot_verify(ctx: Ctx) -> Result:
    """快照判据之三：verify_all 面。"""
    return _check_snapshot(ctx, "snapshot_verify")


def check_doc_numbers(ctx: Ctx) -> Result:
    """文档数字 vs 现算：一处收口（过期数字逐条点名）。"""
    script = _script(ctx, "scripts/check_doc_numbers.py")
    if script is None:
        return _skip("缺 scripts/check_doc_numbers.py", "文档数字的入口不在盘上 ⇒ 没查成")
    code, out, err = _invoke(
        ctx, [sys.executable, "-B", str(script), "--root", str(ctx.root), "--json"])
    doc = _load_json(out)
    if doc is None:
        return _skip(f"exit {code}；读数 JSON 读不出", _tail(out or err))
    counts = doc.get("counts") or {}
    unmeasured = doc.get("unmeasured") or {}
    reading = (f"一致 {counts.get('ok')}/{counts.get('total')}；"
               f"过期 {counts.get('stale')}；缺项 {counts.get('missing')}；"
               f"没量 {len(unmeasured)}")
    if code == EXIT_UNKNOWN or doc.get("state") == "unknown":
        return _skip(reading, f"没查成：{sorted(unmeasured)[:6]}" if unmeasured
                     else str(doc.get("reason") or _tail(out or err)))
    stale = [item for item in (doc.get("items") or [])
             if isinstance(item, dict) and item.get("status") == "stale"]
    if code == EXIT_BAD or stale:
        head = "；".join(
            f"{item.get('doc')} {item.get('label')}：{item.get('doc_value')}→{item.get('now_value')}"
            for item in stale[:3])
        return _fail(reading, head or str(doc.get("reason") or ""),
                     evidence={"stale": [item.get("key") for item in stale]})
    if code != EXIT_OK:
        return _skip(f"退出码 {code}", _tail(out or err))
    return _ok(reading, "")


def check_closing(ctx: Ctx) -> Result:
    """收工门八格（`check_closing_gate.py`，复用 `agentflow.closing`）。"""
    missing = _workspace_missing(ctx)
    if missing is not None:
        return missing
    script = _script(ctx, "scripts/check_closing_gate.py")
    if script is None:
        return _skip("缺 scripts/check_closing_gate.py", "收工门的入口不在盘上 ⇒ 没查成")
    code, out, err = _invoke(
        ctx, [sys.executable, "-B", str(script), "--workspace", str(ctx.workspace),
              "--root", str(ctx.root), "--json"])
    doc = _load_json(out)
    if doc is None:
        return _skip(f"exit {code}；读数 JSON 读不出", _tail(out or err))
    counts = doc.get("counts") or {}
    reading = (f"八格 pass {counts.get('pass')} / fail {counts.get('fail')} / "
               f"unknown {counts.get('unknown')} / na {counts.get('na')}")
    if code == EXIT_BAD:
        blockers = doc.get("blockers") or []
        head = "；".join(_clip(str(one), 120) for one in blockers[:3])
        return _fail(reading, head or str(doc.get("reason") or ""))
    if code == EXIT_UNKNOWN:
        return _skip(reading, str(doc.get("reason") or _tail(out or err)))
    if code != EXIT_OK:
        return _skip(f"退出码 {code}", _tail(out or err))
    return _ok(reading, str(doc.get("reason") or ""))


def check_landing(ctx: Ctx) -> Result:
    """落点四道（`check_landing_gates.py`：非表文件 / 手稿正文 / reports 旧布局 / 书架登记）。"""
    missing = _workspace_missing(ctx)
    if missing is not None:
        return missing
    script = _script(ctx, "scripts/check_landing_gates.py")
    if script is None:
        return _skip("缺 scripts/check_landing_gates.py", "落点门的入口不在盘上 ⇒ 没查成")
    code, out, err = _invoke(
        ctx, [sys.executable, "-B", str(script), "--workspace", str(ctx.workspace),
              "--root", str(ctx.root), "--json"])
    doc = _load_json(out)
    if doc is None:
        return _skip(f"exit {code}；读数 JSON 读不出", _tail(out or err))
    problems = list(doc.get("problem_items") or [])
    unknown = list(doc.get("unknown_checks") or [])
    unsupported = list(doc.get("unsupported_items") or [])
    state = doc.get("state")
    reading = (f"{state}：命中 {len(problems)} / 不支持 {len(unsupported)} / "
               f"没查成 {len(unknown)}")
    if code == EXIT_BAD or state in ("hit", "unsupported"):
        head = "；".join([_clip(str(one), 110) for one in problems[:3]]
                         + [_clip(str(one), 110) for one in unsupported[:1]])
        return _fail(reading, head or str(doc.get("reason") or ""))
    if code == EXIT_UNKNOWN:
        return _skip(reading, str(doc.get("reason") or _tail(out or err)))
    if code != EXIT_OK:
        return _skip(f"退出码 {code}", _tail(out or err))
    return _ok(reading, str(doc.get("reason") or ""))


def check_declaration(ctx: Ctx) -> Result:
    """声明面（`check_declaration.py`：声明识读 / 空目录 / reference 份数 / 游离文件）。"""
    missing = _workspace_missing(ctx)
    if missing is not None:
        return missing
    script = _script(ctx, "scripts/check_declaration.py")
    if script is None:
        return _skip("缺 scripts/check_declaration.py", "声明门的入口不在盘上 ⇒ 没查成")
    code, out, err = _invoke(
        ctx, [sys.executable, "-B", str(script), "--workspace", str(ctx.workspace),
              "--root", str(ctx.root), "--json"])
    doc = _load_json(out)
    if doc is None:
        return _skip(f"exit {code}；读数 JSON 读不出", _tail(out or err))
    problems = list(doc.get("problem_items") or [])
    unknown = list(doc.get("unknown_checks") or [])
    na = list(doc.get("na_checks") or [])
    checks = list(doc.get("checks") or [])
    state = doc.get("state")
    reading = (f"{state}：{len(checks)} 项；命中 {len(problems)} / "
               f"没查成 {len(unknown)} / 不适用 {len(na)}")
    if code == EXIT_BAD:
        head = "；".join(_clip(str(one), 110) for one in problems[:3])
        return _fail(reading, head or str(doc.get("reason") or ""))
    if code == EXIT_UNKNOWN:
        return _skip(reading, str(doc.get("reason") or _tail(out or err)))
    if code != EXIT_OK:
        return _skip(f"退出码 {code}", _tail(out or err))
    return _ok(reading, str(doc.get("reason") or ""))


def check_wellformed(ctx: Ctx) -> Result:
    """产物畸形（`check_wellformed.py`，注意它的 `--root` 是工作区）。"""
    missing = _workspace_missing(ctx)
    if missing is not None:
        return missing
    script = _script(ctx, "scripts/check_wellformed.py")
    if script is None:
        return _skip("缺 scripts/check_wellformed.py", "畸形判据的入口不在盘上 ⇒ 没查成")
    code, out, err = _invoke(
        ctx, [sys.executable, "-B", str(script), "--root", str(ctx.workspace), "--json"])
    doc = _load_json(out)
    if doc is None:
        return _skip(f"exit {code}；读数 JSON 读不出", _tail(out or err))
    counts = doc.get("counts") or {}
    nonzero = [f"{name} {value}" for name, value in counts.items() if value]
    state = doc.get("state")
    reading = f"{state}：{'，'.join(nonzero) if nonzero else '0 条'}"
    if code == EXIT_BAD or state == "malformed":
        findings = []
        for row in doc.get("results") or []:
            for one in (row.get("findings") or [])[:2]:
                findings.append(f"{one.get('where')}：{_clip(str(one.get('detail')), 90)}")
        return _fail(reading, "；".join(findings[:3]) or str(doc.get("reason") or ""))
    if code == EXIT_UNKNOWN:
        return _skip(reading, str(doc.get("reason") or _tail(out or err)))
    if code != EXIT_OK:
        return _skip(f"退出码 {code}", _tail(out or err))
    return _ok(reading, "")


def check_doc_refs(ctx: Ctx) -> Result:
    """文档与注释里的指路（行号 / `文件::符号`）：死引用逐条点名。"""
    script = _script(ctx, "scripts/check_doc_refs.py")
    if script is None:
        return _skip("缺 scripts/check_doc_refs.py", "指路判据的入口不在盘上 ⇒ 没查成")
    with tempfile.TemporaryDirectory(prefix="check-all-refs-") as tmp:
        out_json = Path(tmp) / "docrefs.json"
        code, out, err = _invoke(
            ctx, [sys.executable, "-B", str(script), "--root", str(ctx.root),
                  "--json", str(out_json)])
        try:
            doc = json.loads(out_json.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return _skip(f"exit {code}；读数文件读不出", _tail(out or err))
    if not isinstance(doc, dict):
        return _skip(f"exit {code}；读数不是一个对象", _tail(out or err))
    summary = doc.get("summary") or {}
    unchecked = list(doc.get("unchecked") or [])
    reading = (f"死引用 {summary.get('dead')} / 活引用 {summary.get('line_refs_live')}；"
               f"没查成 {len(unchecked)}")
    if code == EXIT_UNKNOWN or unchecked:
        return _skip(reading, f"这些引用没查成：{_clip(str(unchecked[:3]), 200)}"
                     if unchecked else _tail(out or err))
    if code == EXIT_OK and summary.get("dead"):
        return _skip(reading, "工具以 0 结束却报了死引用 ⇒ 检查器自相矛盾，读数不可信")
    if code == EXIT_BAD:
        by_kind = summary.get("dead_by_kind") or {}
        head = "；".join(f"{name} {value}" for name, value in by_kind.items())
        return _fail(reading, head or str(summary.get("dead")))
    if code != EXIT_OK:
        return _skip(f"退出码 {code}", _tail(out or err))
    return _ok(reading, "")


def check_pytest_full(ctx: Ctx) -> Result:
    """全量 pytest（只有 `--slow` 才有这一项；收口时通常另跑）。"""
    if not (ctx.root / "tests").is_dir():
        return _skip("缺 tests/", "tests 不随仓库交付 ⇒ 全量没查成")
    try:
        code, out, err = _invoke(ctx, _pytest_argv(ctx, "-q"))
    except OSError as exc:
        return _skip("起不了 pytest", f"{type(exc).__name__}: {exc} ⇒ 没查成")
    text = out + "\n" + err
    tail = _PYTEST_TAIL_RE.search(text)
    reading = f"pytest：{tail.group(1)}" if tail else "全量读数解析不了"
    if code == EXIT_OK:
        return _ok(reading, "")
    if code == EXIT_BAD or _is_collection_error(text):
        return _fail(reading, _pytest_detail(text))
    if code == 5:
        return _skip("0 个用例被收集（pytest 5）", "没收集到东西 ⇒ 没查成")
    return _skip(f"pytest 自身以 {code} 结束", _tail(text))


# --------------------------------------------------------------------------- 编排

#: 固定顺序（与模块 docstring 的表一一对应）。`--only` 只筛不改顺序。
ITEMS: tuple[tuple[str, str, object], ...] = (
    ("three_cells", "三格现算（体量软基线）", check_three_cells),
    ("lint", "lint R001–R012（error 必须为 0）", check_lint),
    ("prompt_digests", "十一格提示词摘要与版本", check_prompt_digests),
    ("eol", "行尾漂移（git ls-files --eol）", check_eol),
    ("collect", "pytest 收集期（--collect-only）", check_collect),
    ("snapshot_agent", "快照：agent 面", check_snapshot_agent),
    ("snapshot_tool", "快照：tool 面", check_snapshot_tool),
    ("snapshot_verify", "快照：verify_all 面", check_snapshot_verify),
    ("doc_numbers", "文档数字 vs 现算", check_doc_numbers),
    ("gate_closing", "收工门八格（check_closing_gate）", check_closing),
    ("gate_landing", "落点四道（check_landing_gates）", check_landing),
    ("gate_declaration", "声明面（check_declaration）", check_declaration),
    ("wellformed", "产物畸形（check_wellformed）", check_wellformed),
    ("doc_refs", "文档指路死引用（check_doc_refs）", check_doc_refs),
)

#: 只有 `--slow` 才追加的项。
SLOW_ITEM = ("pytest_full", "全量 pytest", check_pytest_full)


def item_keys(*, slow: bool = False) -> list[str]:
    """这一趟认的项名（`--only` 的合法值）。"""
    keys = [key for key, _, _ in ITEMS]
    if slow:
        keys.append(SLOW_ITEM[0])
    return keys


def _find_workspace(root: Path) -> tuple[Path | None, str]:
    """挑一个工作区：含 `data/` 或 `.agentflow-workspace` 的目录里最近动过的那个。

    本仓库的 `projects/` 在 git 根（产品的上一级），交付形态里也可能在产品根下；
    两处都找。挑不到就给 None（依赖工作区的项记 SKIP，不是 pass）。
    """
    bases = [root / "projects", root.parent / "projects"]
    for base in bases:
        try:
            is_dir = base.is_dir()
        except OSError:
            is_dir = False
        if not is_dir:
            continue
        try:
            found = [path for path in base.iterdir()
                     if path.is_dir()
                     and ((path / "data").is_dir()
                          or (path / ".agentflow-workspace").is_file())]
        except OSError:
            continue
        if not found:
            continue
        found.sort(key=_workspace_rank, reverse=True)
        return found[0], f"自动选取（{base} 下最近动过的工作区）"
    return None, ("没给 --workspace，也没在 projects/ 下找到含 data/ 或 "
                  ".agentflow-workspace 的目录")


def _workspace_rank(path: Path) -> tuple[float, str]:
    """按目录 mtime 排（最近动过的优先）；读不出 mtime 按 0，并列按名字。"""
    try:
        mtime = path.stat().st_mtime
    except OSError:
        mtime = 0.0
    return (mtime, path.name)


def _timed(key: str, title: str, fn, ctx: Ctx) -> Result:
    """跑一项并计时；检查器自己抛了 / 超时都算没查成（不许当成通过）。"""
    started = time.monotonic()
    try:
        result = fn(ctx)
    except subprocess.TimeoutExpired as exc:
        result = _skip("超时", f"超过 {exc.timeout} 秒没结束 ⇒ 没查成（超时不是通过）")
    except Exception as exc:  # noqa: BLE001 - 编排层的任何意外都是"没查成"
        result = _skip("检查器自己抛了", f"{type(exc).__name__}: {exc} ⇒ 没查成")
    result.key, result.title = key, title
    result.elapsed_sec = time.monotonic() - started
    return result


def run_checks(ctx: Ctx, *, only: list[str] | None = None,
               slow: bool = False) -> list[Result]:
    """按固定顺序跑选中的项，返回逐项读数。"""
    wanted = list(only) if only else item_keys(slow=slow)
    order = list(ITEMS) + ([SLOW_ITEM] if slow else [])
    return [_timed(key, title, fn, ctx) for key, title, fn in order if key in wanted]


def overall(results: list[Result]) -> int:
    """三态汇总：有 FAIL 记 1；否则有 SKIP 记 2；全 ok 记 0。"""
    if any(result.state == "fail" for result in results):
        return EXIT_BAD
    if any(result.state == "skip" for result in results):
        return EXIT_UNKNOWN
    return EXIT_OK


def _conclusion(results: list[Result]) -> str:
    """一句结论：把三档计数与点名都写在同一行。"""
    ok = [result.key for result in results if result.state == "ok"]
    bad = [result.key for result in results if result.state == "fail"]
    skip = [result.key for result in results if result.state == "skip"]
    if bad:
        extra = f"另有 {len(skip)} 项没查成" if skip else "没有没查成的项"
        return (f"结论：{len(ok)} 项过 / {len(bad)} 项失败 / {len(skip)} 项没查成 ⇒ exit 1"
                f"（有失败：{'、'.join(bad)}；{extra}）")
    if skip:
        return (f"结论：{len(ok)} 项过 / 0 项失败 / {len(skip)} 项没查成 ⇒ exit 2"
                f"（没查成：{'、'.join(skip)}）")
    return f"结论：{len(ok)} 项全过 / 0 项失败 / 0 项没查成 ⇒ exit 0（所有门都查了、都一致）"


def render_text(ctx: Ctx, results: list[Result], *, slow: bool,
                only: list[str] | None, elapsed_sec: float) -> str:
    """人读版：抬头、逐项一行、总表、结论行。"""
    lines = [f"{PROG} —— 一条命令跑完收口门",
             f"产品根  {ctx.root}",
             f"工作区  {ctx.workspace if ctx.workspace else '（无）'}"
             f"（{ctx.workspace_note}）"]
    if only:
        lines.append(f"范围    --only {','.join(only)}")
    lines.append(f"耗时    {elapsed_sec:.1f} 秒")
    lines.append("")
    for result in results:
        lines.append(f"[{result.mark:<4}] {result.key:<17} {result.reading}")
        if result.state != "ok" and result.detail:
            for part in result.detail.splitlines()[:3]:
                lines.append(f"         {part}")
    lines.append("")
    lines.append("总表（项 / 状态 / 秒 / 关键读数）")
    for result in results:
        lines.append(f"  {result.key:<17} {result.mark:<5} {result.elapsed_sec:7.1f}  "
                     f"{_clip(result.reading, 72)}")
    lines.append("")
    bad = [result.key for result in results if result.state == "fail"]
    skip = [result.key for result in results if result.state == "skip"]
    lines.append(f"计：ok {len(results) - len(bad) - len(skip)} / FAIL {len(bad)} / "
                 f"SKIP {len(skip)}")
    lines.append(f"失败项：{'、'.join(bad) if bad else '（无）'}")
    lines.append(f"没查成：{'、'.join(skip) if skip else '（无）'}")
    if not slow:
        lines.append("未纳入：pytest 全量（--slow 才跑；收口时可另跑全量）")
    lines.append(_conclusion(results))
    return "\n".join(lines)


def render_json(ctx: Ctx, results: list[Result], *, slow: bool,
                only: list[str] | None, elapsed_sec: float) -> str:
    """机器读数：逐项三态 + 汇总 + 失败/没查成的点名单。"""
    payload = {
        "script": PROG,
        "root": str(ctx.root),
        "workspace": str(ctx.workspace) if ctx.workspace else "",
        "workspace_note": ctx.workspace_note,
        "slow_included": bool(slow),
        "only": list(only or []),
        "elapsed_sec": round(elapsed_sec, 2),
        "exit_code": overall(results),
        "counts": {
            "ok": sum(1 for result in results if result.state == "ok"),
            "fail": sum(1 for result in results if result.state == "fail"),
            "skip": sum(1 for result in results if result.state == "skip"),
        },
        "failures": [result.key for result in results if result.state == "fail"],
        "skips": [result.key for result in results if result.state == "skip"],
        "conclusion": _conclusion(results),
        "items": [
            {"key": result.key, "title": result.title, "state": result.state,
             "mark": result.mark, "reading": result.reading, "detail": result.detail,
             "exit_code": result.exit_code, "elapsed_sec": round(result.elapsed_sec, 2)}
            for result in results
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


# --------------------------------------------------------------------------- 自测夹具
# 夹具是一棵最小产品树：门全是替身（只按固定 JSON 作答），用来验本脚本的三态映射。
# 它测的是编排契约，不是任何一条判据本身 —— 判据的测试在各自的判据文件里。

_STUB_JSON = '''"""夹具替身：按固定读数作答（check_all --selftest 生成，不在交付面里）。"""
import json
import sys

PAYLOAD = %(payload)s

print(json.dumps(PAYLOAD, ensure_ascii=False))
raise SystemExit(%(code)d)
'''

_STUB_LINT = '''"""夹具替身：lint 的两种读数（环境变量 CHECKALL_STUB_LINT=ok 时恒 ok）。"""
import json
import os
import sys

BAD = %(bad)r
if os.environ.get("CHECKALL_STUB_LINT") == "ok":
    BAD = False
payload = {
    "script": "check_lint",
    "state": "bad" if BAD else "ok",
    "exit_code": 1 if BAD else 0,
    "counts": {"error": 1 if BAD else 0, "warning": 0, "info": 0},
    "rules_run": ["R001"],
    "scanned": {"src_py": 1, "tests_py": 12},
    "errors": ([{"rule": "R001", "path": "src/agentflow/fixture.py", "line": 7,
                 "message": "夹具：一处 bare except pass"}] if BAD else []),
    "reason": "error 1 条（夹具）" if BAD else "0 条 error（夹具）",
}
print(json.dumps(payload, ensure_ascii=False))
raise SystemExit(1 if BAD else 0)
'''

_STUB_EOL = '''"""夹具替身：行尾读数写进 --json-out。"""
import json
import sys

args = sys.argv[1:]
path = args[args.index("--json-out") + 1] if "--json-out" in args else ""
payload = {"status": "ok", "why": "", "tracked": 7, "drift": [],
           "committed_crlf": [], "counts": {"drift": 0, "committed_crlf": 0}}
if path:
    with open(path, "w", encoding="utf-8", newline="\\n") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False))
raise SystemExit(0)
'''

_STUB_DOCREFS = '''"""夹具替身：指路读数写进 --json 路径。"""
import json
import sys

args = sys.argv[1:]
path = args[args.index("--json") + 1] if "--json" in args else ""
payload = {
    "root": ".",
    "summary": {"scanned_files": 3, "dead": 0, "info": 0, "line_refs_live": 3,
                "line_refs_with_symbol": 0, "dead_by_kind": {}, "unchecked": 0},
    "findings": [],
    "unchecked": [],
}
if path:
    with open(path, "w", encoding="utf-8", newline="\\n") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, indent=1))
raise SystemExit(0)
'''

_STUB_DIGESTS = '''"""夹具替身：十一格摘要与版本行（夹具永远一致）。"""
for role in ("A", "B", "C", "D", "E", "F", "G", "H", "L", "M", "V"):
    print(f"  [OK ] {role} 现算 {'a' * 16}…  冻结 {'a' * 16}…")
print("  版本：现算 p1 / 冻结 p1")
print("[ok] 冻结表与现算一致")
raise SystemExit(0)
'''

_STUB_TEST = '''"""夹具替身：快照判据恒过（check_all --selftest 生成）。"""


def %s():
    assert True
'''


def _write_lf(path: Path, text: str) -> None:
    """写一份 LF 文本（行尾纪律：绝不依赖平台缺省）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def build_fixture(base: Path, *, lint_bad: bool = False,
                  workspace: bool = True) -> Path:
    """造一棵全绿（或指定一处 lint error / 无工作区）的最小产品树，返回它的根。

    参数两个：`lint_bad` 把 lint 的读数打成 1 条 error；`workspace` 决定要不要
    `projects/fixture-ws/`。`--selftest` 与 `tests/test_check_all.py` 共用它。
    """
    root = Path(base)
    root.mkdir(parents=True, exist_ok=True)
    (root / "scripts").mkdir(exist_ok=True)
    (root / "tools").mkdir(exist_ok=True)
    (root / "tests" / "golden").mkdir(parents=True, exist_ok=True)
    if workspace:
        (root / "projects" / "fixture-ws" / "data").mkdir(parents=True, exist_ok=True)

    three = {
        "script": "check_three_cells", "root": str(root), "state": "ok", "exit_code": 0,
        "baseline": {"gt800": 72, "fn200": 95, "dup": 2},
        "cells": {
            "gt800": {"value": 1, "baseline": 72, "ok": True},
            "fn200": {"value": 2, "baseline": 95, "ok": True},
            "dup": {"value": 0, "baseline": 2, "ok": True},
        },
        "survey": {"scanned": {"src_files": 1, "tests_files": 12}},
        "reason": "三格现算都不超过基线",
    }
    docnum = {
        "script": "check_doc_numbers", "root": str(root), "state": "ok", "exit_code": 0,
        "counts": {"total": 3, "ok": 3, "stale": 0, "missing": 0},
        "unmeasured": {}, "items": [], "reason": "",
    }
    closing = {
        "script": "check_closing_gate", "workspace": str(root), "state": "pass",
        "exit_code": 0, "counts": {"pass": 8, "fail": 0, "unknown": 0, "na": 0},
        "blockers": [], "status": {"contradictions": "pass"}, "reason": "八格都过",
    }
    landing = {
        "script": "check_landing_gates", "workspace": str(root), "state": "clear",
        "exit_code": 0, "problem_items": [], "unknown_checks": [], "na_checks": [],
        "unsupported_items": [], "checks": [{"check": "fixture", "state": "clear"}],
        "reason": "四项都查了、都没有命中",
    }
    declaration = {
        "script": "check_declaration", "workspace": str(root), "state": "clear",
        "exit_code": 0, "problem_items": [], "unknown_checks": [], "na_checks": [],
        "checks": [{"check": "fixture", "state": "clear"}],
        "reason": "四项都查了、都没有命中",
    }
    wellformed = {
        "root": str(root), "state": "ok", "exit_code": 0,
        "counts": {"tasks": 0, "sessions": 0, "layout": 0},
        "by_kind": {}, "results": [],
    }
    stubs = {
        "scripts/check_three_cells.py": _STUB_JSON % {"payload": repr(three), "code": 0},
        "scripts/check_doc_numbers.py": _STUB_JSON % {"payload": repr(docnum), "code": 0},
        "scripts/check_closing_gate.py": _STUB_JSON % {"payload": repr(closing), "code": 0},
        "scripts/check_landing_gates.py": _STUB_JSON % {"payload": repr(landing), "code": 0},
        "scripts/check_declaration.py": _STUB_JSON % {"payload": repr(declaration), "code": 0},
        "scripts/check_wellformed.py": _STUB_JSON % {"payload": repr(wellformed), "code": 0},
        "scripts/recompute_prompt_digests.py": _STUB_DIGESTS,
        "tools/eol_gate.py": _STUB_EOL,
        "scripts/check_doc_refs.py": _STUB_DOCREFS,
        "scripts/check_lint.py": _STUB_LINT % {"bad": bool(lint_bad)},
    }
    for rel, source in stubs.items():
        _write_lf(root / rel, source)
    for key, spec in _SNAPSHOTS.items():
        _write_lf(root / "tests" / spec["file"], _STUB_TEST % spec["test"])
        _write_lf(root / "tests" / "golden" / Path(spec["golden"]).name, "{}\n")
    return root


def _run_child(tree: Path, env_extra: dict[str, str] | None = None) -> tuple[int, dict]:
    """起一个子进程跑本脚本 `--root <tree> --json`，返回 `(退出码, 读数)`。"""
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env.update(env_extra or {})
    done = subprocess.run(
        [sys.executable, "-B", str(Path(__file__).resolve()), "--root", str(tree), "--json"],
        env=env, stdin=subprocess.DEVNULL, capture_output=True, timeout=600)
    text = done.stdout.decode("utf-8", "replace")
    doc = _load_json(text)
    return done.returncode, doc or {"raw": _tail(text)}


def selftest() -> int:
    """a–d 四条判据：全绿 ⇒ 0、一处 lint error ⇒ 1 且点名、缺工作区 ⇒ 2、反真空。"""
    rows: list[tuple[str, str, int, int, bool]] = []
    with tempfile.TemporaryDirectory(prefix="check-all-selftest-") as tmp:
        base = Path(tmp)
        green = build_fixture(base / "a", lint_bad=False, workspace=True)
        code, doc = _run_child(green)
        rows.append(("a 全绿夹具", "exit 0", EXIT_OK, code,
                     code == EXIT_OK and doc.get("counts", {}).get("skip") == 0))

        bad = build_fixture(base / "b", lint_bad=True, workspace=True)
        code, doc = _run_child(bad)
        rows.append(("b 一处 lint error", "exit 1 且点名 lint", EXIT_BAD, code,
                     code == EXIT_BAD and doc.get("failures") == ["lint"]))

        nows = build_fixture(base / "c", lint_bad=False, workspace=False)
        code, doc = _run_child(nows)
        skipped = doc.get("skips") or []
        rows.append(("c 缺工作区", "exit 2 且四条工作区项 SKIP", EXIT_UNKNOWN, code,
                     code == EXIT_UNKNOWN
                     and doc.get("counts", {}).get("fail") == 0
                     and {"gate_closing", "gate_landing", "gate_declaration",
                          "wellformed"}.issubset(set(skipped))))

        code_d, doc_d = _run_child(bad, {"CHECKALL_STUB_LINT": "ok"})
        rows.append(("d 反真空（把 lint 判定打桩成恒 ok）", "b 的红消失 ⇒ b 会红",
                     EXIT_OK, code_d,
                     code_d == EXIT_OK and not doc_d.get("failures")))

    print("自测（夹具是 tempfile 里的最小产品树；门全是替身，测的是三态映射契约）")
    bad_rows = 0
    for name, want_text, want, got, passed in rows:
        flag = "OK  " if passed else "BAD "
        if not passed:
            bad_rows += 1
        print(f"  [{flag}] {name:32s} 期望 {want_text}  实际 exit={got}")
    print(f"自测结论：{len(rows) - bad_rows}/{len(rows)} 条符合期望")
    return EXIT_OK if not bad_rows else EXIT_UNKNOWN


# --------------------------------------------------------------------------- 入口


def main(argv: list[str] | None = None) -> int:
    """解析参数、按固定顺序跑门、按三态返回退出码。"""
    _pin_utf8()
    parser = argparse.ArgumentParser(
        prog=PROG,
        description=("一条命令跑完收口门（固定顺序；0 全过 / 1 有失败 / 2 没查成）"),
        allow_abbrev=False,
    )
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[1]),
                        help="产品根（缺省 = 本脚本的上一级，即 agentflow/）")
    parser.add_argument("--workspace", default="",
                        help="工作区根（缺省自动挑 projects/ 下最近动过的一个）")
    parser.add_argument("--only", default="",
                        help="只跑这些项（逗号分隔；便于定位，不改顺序）")
    parser.add_argument("--json", action="store_true", help="输出机器读数")
    parser.add_argument("--slow", action="store_true",
                        help="额外跑全量 pytest（默认不跑；收口时通常另跑）")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT,
                        help=f"单项超时秒数（缺省 {DEFAULT_TIMEOUT}；超时记没查成）")
    parser.add_argument("--selftest", action="store_true",
                        help="用 tempfile 造夹具验 a–d 四条（含反真空）")
    args = parser.parse_args(argv)

    if args.selftest:
        return selftest()

    root = Path(args.root).expanduser().resolve()
    if not root.is_dir():
        print(f"[unknown] 产品根不存在：{root} ⇒ 没查成", file=sys.stderr)
        return EXIT_UNKNOWN

    if args.workspace:
        workspace = Path(args.workspace).expanduser()
        if not workspace.is_absolute():
            workspace = Path.cwd() / workspace
        workspace, note = workspace.resolve(), "命令行 --workspace"
    else:
        workspace, note = _find_workspace(root)
    ctx = Ctx(root=root, workspace=workspace, workspace_note=note,
              timeout=max(int(args.timeout), 1))

    wanted = [part.strip() for part in args.only.split(",") if part.strip()]
    if "pytest_full" in wanted:
        args.slow = True
    known = item_keys(slow=args.slow)
    unknown = [name for name in wanted if name not in known]
    if unknown:
        print(f"[unknown] --only 不认这些项：{unknown}；认：{known}", file=sys.stderr)
        return EXIT_UNKNOWN
    only = wanted or None

    started = time.monotonic()
    results = run_checks(ctx, only=only, slow=args.slow)
    elapsed = time.monotonic() - started
    if not results:
        print("[unknown] 一项都没跑 ⇒ 没查成", file=sys.stderr)
        return EXIT_UNKNOWN
    if args.json:
        print(render_json(ctx, results, slow=args.slow, only=only, elapsed_sec=elapsed))
    else:
        print(render_text(ctx, results, slow=args.slow, only=only, elapsed_sec=elapsed))
    return overall(results)


if __name__ == "__main__":
    raise SystemExit(main())

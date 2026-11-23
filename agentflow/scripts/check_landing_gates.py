"""`check_landing_gates` —— 框架自保的只读体检：这个工作区的落点还是不是那套布局。

用法：

```
python scripts/check_landing_gates.py --workspace projects/lp-ball-15
python scripts/check_landing_gates.py --workspace projects/lp-ball-15 --json
python scripts/check_landing_gates.py --selftest
```

四项读数（每项是 `clear` / `hit` / `unsupported` / `unknown` / `na` 之一；
`unsupported` = 旧布局（不再支持），只用于第 2 项的旧账本）：

| # | 项 | 判什么 |
|---|---|---|
| 1 | `data_non_table` | `data/` 里有没有不是表、也不是已登记旁路的文件或目录 |
| 2 | `manuscripts_body` | `manuscripts/` 里有没有正文（canonical 交接账本在 `work/handoffs.jsonl`；`manuscripts/handoffs.jsonl` 是旧布局、不再支持） |
| 3 | `reports_legacy` | `reports/` 还留着文件吗（旧布局的残留） |
| 4 | `library_registered` | `library/` 里有没有未被 `literature` 行引用的文件（复核 `seedinject` 的判据） |

退出码（三态）：

- `0` = 四项都查了、都没有命中；
- `1` = 查过了、至少一项命中（含「旧布局（不再支持）」；逐项逐条在输出里）；
- `2` = 没查成（工作区不在、import 不到 `agentflow`、或命中之外还有项读不出来）——
  "没查成"与"干净"是两件事，同时"命中"优先于"没查成"（已知的坏不许被旁边一项的
  读不到盖住）。

## 第 2 项的 `unsupported` 是什么

`manuscripts/handoffs.jsonl` 是旧布局：账本的新家是 `work/handoffs.jsonl`，`manuscripts/`
只放正文（`manuscripts/<角色>/`）。它一出现，第 2 项报 `unsupported`，整份读数退出码 1 ——
既不是 `hit`（"新布局下缺正文"），也不是 `unknown`（"没查成"）。这与
`wellformed.layout` 的 `UNSUPPORTED` 是同一档严重度（旧布局不是 ok）。
读数里 canonical 与 unsupported 逐字分开：canonical = `work/handoffs.jsonl`，
unsupported = `manuscripts/handoffs.jsonl` —— 旧账本不再被数成"交接记录"。

## 第 1 项的判据是怎么来的（为什么不是"凡不在 TABLES 里就红"）

`data/` 里天然会有不是表的东西，它们各有各的出处：

- `counters.json`（编号空间计数器）、`events.jsonl`（事件流）、`.locks`（表锁目录）
  是 `store` 自己写的；
- `lit_reads.jsonl` / `lit_readbacks.jsonl` / `lit_availability.jsonl` / `lit_candidates/`
  是抽读与可得性那一路的台账（`litavail.py` / `litstage.py` 写）；
- `research_request_ledger.json` 是 `research_tools.py` 的去重台账，它刻意不是 schema 表
  （`LEDGER_FILE`，`verify.py` 也按这个名字核）。

所以判据分三档：表文件（`schema.TABLES`）认；退役表文件（`schema.RETIRED_TABLES`）
认，但报一句"退役的表文件还在盘上"（读侧认它，`init` 不再生成）；登记过的旁路认。
剩下的一律报出来 —— 2026-11-22 那台真机 `data/lp_ball_3d_final.json` 这种一次性模型
产物就是这样留在台账目录里的，它既不是表也不是任何模块的旁路。

`*.jsonl` 一律按"日志旁路"认（表一律是 `.json` 文档 + `rows`；`.jsonl` 是追加日志），
这条规则不靠一张越写越长的白名单。真出现一个"应该建表却写成了 jsonl"的东西，
它的症状是表里没有行，那是 `verify` / 收工门的活，不是这一项能判的。

## 为什么不重写判据

第 4 项直接调 `seedinject.unregistered_library_files` —— 它是"书架只放已登记的"
这条不变量的唯一实现（2026-11-22 业主指出的事故就是它要拦的形态）。本脚本只负责
组织这四项、给三态、把读数排成人能读的样子。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROG = "check_landing_gates"

EXIT_OK = 0
EXIT_BAD = 1
EXIT_UNKNOWN = 2

#: 四态的四个取值（一处词表；JSON 与文本共用）。
CLEAR = "clear"
HIT = "hit"
UNKNOWN = "unknown"
NA = "na"
#: 第 5 档：旧布局（不再支持）。只在第 2 项用：`manuscripts/handoffs.jsonl` 还占着
#: 手稿目录的根 —— 它不是 `hit`（"新布局下缺正文"），也不是 `unknown`（"没查成"）。
UNSUPPORTED = "unsupported"

#: 交接账本的名字与两个落点。它们与 `agentflow.manuscripts` 的
#: `HANDOFFS_NAME` / `HANDOFFS_DIR` / `MANUSCRIPTS_DIR` 是同一处口径
#: （`tests/test_old_md_and_old_ledger_are_not_supported.py` 把两者钉在一起）。
LEDGER_NAME = "handoffs.jsonl"
CANONICAL_LEDGER_DIR = "work"
LEGACY_LEDGER_DIR = "manuscripts"

#: `data/` 里不是表、但不是残留的旁路（每一项都要能在源码里指到写点）。
#: 键是 `data/` 下的一级名字（文件或目录），值是一句"它是谁写的"。
KNOWN_DATA_SIDECARS: dict[str, str] = {
    "counters.json": "编号空间计数器（`store` 的 `ID_COUNTERS` 落盘处）",
    ".locks": "表锁目录（`store.locks`）",
    "lit_candidates": "候选分目录（`litstage` 落，按候选号分文件）",
    "research_request_ledger.json": ("研究请求去重台账（`research_tools.LEDGER_FILE`；"
                                     "刻意不是 schema 表）"),
    "lit_reads.jsonl": "抽读台账（`litavail` 落）",
    "lit_readbacks.jsonl": "抽读回执（`litstage` 落）",
    "lit_availability.jsonl": "可得性判读（`litavail.LEDGER_NAME`）",
}

#: 追加日志的后缀：按"日志旁路"认（表一律是 `.json` 文档）。
LOG_SUFFIX = ".jsonl"

#: `data/` 顶层的散文文件：说明书不是台账（仓库自带 `data/README.md`，真机工作区里也可能有
#: 人写的说明）。它们没有行、不进重建、不参与任何判据，所以按"文档"数，不算非表残留。
DOC_SUFFIXES: tuple[str, ...] = (".md", ".txt")

#: `library/` 那一项最多点名几份未登记文件（计数仍是全量）。
DEFAULT_MAX_ITEMS = 12


def _pin_utf8() -> None:
    """钉住 stdout/stderr 的编码（GBK 重定向会把"发现问题"打印成进程失败）。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def _product_root() -> Path:
    """本脚本所属的产品根（`scripts/` 的上一级）。"""
    return Path(__file__).resolve().parents[1]


def load_modules(root: Path):
    """从目标根的 `src/` 导入 `schema` 与 `seedinject`；返回 `(schema, seedinject, 理由)`。"""
    src = Path(root) / "src"
    if not (src / "agentflow" / "seedinject.py").is_file():
        return None, None, (f"读不到 {src / 'agentflow' / 'seedinject.py'}"
                            "（第 4 项的判据本体）⇒ 没查成")
    sys.path.insert(0, str(src))
    try:
        from agentflow import schema as S  # noqa: PLC0415 - 必须在改过 sys.path 之后
        from agentflow import seedinject as SI  # noqa: PLC0415
    except Exception as exc:  # noqa: BLE001 - 导入失败就是"没查成"
        return None, None, f"导入 agentflow 失败：{type(exc).__name__}: {exc} ⇒ 没查成"
    where = Path(getattr(SI, "__file__", "") or "").resolve()
    try:
        where.relative_to(Path(root).resolve())
    except ValueError:
        return None, None, (f"import 到的 agentflow 是 {where}，不在 {Path(root).resolve()} 下"
                            " ⇒ 判据不是这一棵树的，没查成")
    return S, SI, ""


def _state_row(name: str, state: str, detail: str, items: list[str] | None = None) -> dict:
    """一项读数的统一形状（`state` 只有一个词表，文本与 JSON 都用它）。"""
    return {"check": name, "state": state, "detail": detail, "items": list(items or ())}


def _looks_like_workspace(workspace: Path, schema) -> tuple[bool, str]:
    """这个目录看起来是一个工作区吗；返回 `(像不像, 理由)`。

    为什么要先问这一句：`--workspace` 指错（指到产品树、指到一个空目录）时，
    后面四项会照样给出读数 —— 产品树的 `data/` 里有仓库自带的 `README.md`，
    于是"非表文件 1 份"看起来像一条真缺陷。那不是这个工具的判据问题，是喂错了对象；
    三态纪律要求这种情况落"没查成"并说清原因，而不是落一条像样的红。

    判据只有两条（不猜）：工作区标记 `.agentflow-workspace` 在盘上；或 `data/` 里
    至少有表文件中的一份（`schema.TABLES` 的 `file` 名字）。
    """
    if (workspace / ".agentflow-workspace").is_file():
        return True, "有 .agentflow-workspace 标记"
    data = workspace / "data"
    if not data.is_dir():
        return False, f"没有 {data}"
    names = {str((spec or {}).get("file") or "") for spec in (getattr(schema, "TABLES", {}) or {}).values()}
    names.discard("")
    try:
        present = [p.name for p in data.iterdir() if p.is_file() and p.name in names]
    except OSError as exc:
        return False, f"列不了 {data}：{type(exc).__name__}: {exc}"
    if present:
        return True, f"data/ 里有表文件 {len(present)} 份"
    return False, (f"data/ 里一张表都没有（也没有 .agentflow-workspace 标记）"
                   " —— 这不是一个已初始化的工作区")


def _check_data(schema, workspace: Path, max_items: int) -> dict:
    """第 1 项：`data/` 里有没有非表、非登记旁路的文件或目录。"""
    data = workspace / "data"
    if not data.is_dir():
        return _state_row("data_non_table", UNKNOWN,
                          f"读不到 {data} ⇒ 这一项没查成（不是「没有非表文件」）")
    table_files = {str((spec or {}).get("file") or "") for spec in (schema.TABLES or {}).values()}
    # `RETIRED_TABLES` 是 2026-11-22 才有的那一档。干净 clone 上是 HEAD 那一版 schema，
    # 可能还没有它 —— 用 getattr 兜住，并把"这一档没有"写在读数里（不是崩，也不是假装有）。
    retired_tables = getattr(schema, "RETIRED_TABLES", None)
    retired_files = ({str((spec or {}).get("file") or "")
                      for spec in (retired_tables or {}).values()}
                     if isinstance(retired_tables, dict) else set())
    table_files.discard("")
    retired_files.discard("")
    notes: list[str] = []
    if not isinstance(retired_tables, dict):
        notes.append("这一版 schema 没有 `RETIRED_TABLES`（退役表那一档是 2026-11-22 之后才有的）")

    unknown: list[str] = []
    retired: list[str] = []
    sidecars: list[str] = []
    logs: list[str] = []
    docs: list[str] = []
    tables = 0
    try:
        entries = sorted(data.iterdir(), key=lambda p: p.name)
    except OSError as exc:
        return _state_row("data_non_table", UNKNOWN,
                          f"列不了 {data}：{type(exc).__name__}: {exc} ⇒ 这一项没查成")
    for path in entries:
        name = path.name
        if path.is_dir():
            if name in KNOWN_DATA_SIDECARS:
                sidecars.append(f"{name}/")
                continue
            unknown.append(f"{name}/")
            continue
        if name in table_files:
            tables += 1
        elif name in retired_files:
            retired.append(name)
        elif name in KNOWN_DATA_SIDECARS:
            sidecars.append(name)
        elif name.lower().endswith(LOG_SUFFIX):
            logs.append(name)
        elif name.lower().endswith(DOC_SUFFIXES):
            docs.append(name)
        else:
            unknown.append(name)
    detail = (f"表文件 {tables} 份、登记旁路 {len(sidecars)} 份、日志 {len(logs)} 份"
              f"、文档 {len(docs)} 份、退役表文件 {len(retired)} 份、非表 {len(unknown)} 份")
    if notes:
        detail += "（" + "；".join(notes) + "）"
    if retired:
        detail += f"（退役表仍在盘上：{retired} —— 读侧认它，`init` 不再生成）"
    if unknown:
        return _state_row("data_non_table", HIT,
                          detail + "；这些不在任何台账里：" + "；".join(unknown[:max_items]),
                          unknown)
    return _state_row("data_non_table", CLEAR, detail)


def _ledger_verdict(base: Path, canonical: Path) -> tuple[str, str, list[str]] | None:
    """旧账本（`manuscripts/handoffs.jsonl`）的判词；不在盘上 ⇒ `None`。

    "旧布局（不再支持）"与"没有正文"必须分开说：前者是"账本还在旧地方"（整项
    `unsupported`），后者是新目录下一份稿子都没落进来（`hit`）。折成同一档，
    体检读数就会把旧账本读成"交接记录" —— 改前实测：`manuscripts/handoffs.jsonl`
    加一份正文 ⇒ 读数"正文 1 份、交接记录 1 份"、退出码 0。
    """
    old = base / LEDGER_NAME
    if not old.is_file():
        return None
    try:
        size = old.stat().st_size
    except OSError:
        size = -1
    canon = (f"；canonical 落点 `{CANONICAL_LEDGER_DIR}/{LEDGER_NAME}` 也在盘上（新家）"
             if canonical.is_file() else
             f"；canonical 落点是 `{CANONICAL_LEDGER_DIR}/{LEDGER_NAME}`（新家）")
    detail = (f"旧布局（不再支持）：`{LEGACY_LEDGER_DIR}/{LEDGER_NAME}` 在盘上（{size} 字节）"
              f"—— 交接账本不是手稿，已从 `{LEGACY_LEDGER_DIR}/` 挪到 "
              f"`{CANONICAL_LEDGER_DIR}/{LEDGER_NAME}`；本项不把它数成交接记录，"
              f"也不折成「没有旧账本」{canon}")
    return UNSUPPORTED, detail, [f"{LEGACY_LEDGER_DIR}/{LEDGER_NAME}"]


def _check_manuscripts(workspace: Path, max_items: int) -> dict:
    """第 2 项：`manuscripts/` 里有没有正文（交接账本不是正文）。

    读数分三档：canonical 交接账本在 `work/handoffs.jsonl`（不在 `manuscripts/` 里）；
    `manuscripts/handoffs.jsonl` 是旧布局 ⇒ `unsupported`（不再支持，不是"交接记录"）；
    其余文件按正文数。旧账本出现时不先判它、把它从"正文"里剔掉就报 clear —— 那正是
    改前的错觉（旧账本 + 一份正文 ⇒ "交接记录 1 份"、退出码 0）。
    """
    base = workspace / LEGACY_LEDGER_DIR
    canonical = workspace / CANONICAL_LEDGER_DIR / LEDGER_NAME
    if not base.is_dir():
        return _state_row("manuscripts_body", NA,
                          f"没有 {base} ⇒ 这一项没有可判对象"
                          f"（交接账本是 `{CANONICAL_LEDGER_DIR}/{LEDGER_NAME}`，不在这里）")
    try:
        files = [p for p in sorted(base.rglob("*")) if p.is_file()]
    except OSError as exc:
        return _state_row("manuscripts_body", UNKNOWN,
                          f"列不了 {base}：{type(exc).__name__}: {exc} ⇒ 这一项没查成")
    verdict = _ledger_verdict(base, canonical)
    if verdict is not None:
        return _state_row("manuscripts_body", verdict[0], verdict[1], verdict[2])
    bodies = [p for p in files if p.name != LEDGER_NAME]
    if not files:
        return _state_row("manuscripts_body", HIT, f"{base} 是空的（一份文件都没有）")
    if not bodies:
        names = [p.relative_to(base).as_posix() for p in files]
        return _state_row("manuscripts_body", HIT,
                          f"{base} 里没有任何正文（只有 {', '.join(names[:max_items])}）",
                          names[:max_items])
    names = [p.relative_to(base).as_posix() for p in bodies]
    ledger_note = (f"；交接账本 `{CANONICAL_LEDGER_DIR}/{LEDGER_NAME}`（canonical）"
                   if canonical.is_file() else
                   f"；交接账本 canonical 落点是 `{CANONICAL_LEDGER_DIR}/{LEDGER_NAME}`")
    return _state_row("manuscripts_body", CLEAR,
                      f"正文 {len(bodies)} 份{ledger_note}", names[:max_items])


def _check_reports(workspace: Path, max_items: int) -> dict:
    """第 3 项：`reports/` 还留着文件吗（旧布局的残留）。"""
    base = workspace / "reports"
    if not base.is_dir():
        return _state_row("reports_legacy", NA,
                          f"没有 {base} ⇒ 没有旧布局残留可判（新布局的手稿在 `manuscripts/`）")
    try:
        files = [p for p in sorted(base.rglob("*")) if p.is_file()]
    except OSError as exc:
        return _state_row("reports_legacy", UNKNOWN,
                          f"列不了 {base}：{type(exc).__name__}: {exc} ⇒ 这一项没查成")
    if not files:
        return _state_row("reports_legacy", CLEAR, f"{base} 在盘上但是空的")
    names = [p.relative_to(base).as_posix() for p in files]
    return _state_row("reports_legacy", HIT,
                      (f"{base} 里还有 {len(files)} 个文件（旧布局；"
                       "新布局是 `manuscripts/` + `data/`）"), names[:max_items])


def _check_library(seedinject, workspace: Path, max_items: int) -> dict:
    """第 4 项：`library/` 里有没有未被 `literature` 行引用的文件。"""
    judge = getattr(seedinject, "unregistered_library_files", None)
    if not callable(judge):
        return _state_row("library_registered", UNKNOWN,
                          ("这一版 `seedinject` 没有 `unregistered_library_files`（2026-11-22 "
                           "之后才有的判据）⇒ 这一项没查成。本脚本刻意不在这里补一份判据："
                           "补出来的就是第二个口径"))
    try:
        got = judge(workspace)
    except Exception as exc:  # noqa: BLE001 - 判据自己抛了 = 没查成
        return _state_row("library_registered", UNKNOWN,
                          f"判据自己抛了：{type(exc).__name__}: {exc} ⇒ 这一项没查成")
    if got is None:
        return _state_row("library_registered", UNKNOWN,
                          ("`data/literature.json` 读不出来或形状不对"
                           " ⇒ 这一项没查成（不是「书架干净」）"))
    if not got:
        return _state_row("library_registered", CLEAR, "`library/` 里每个文件都有 `literature` 行引用")
    return _state_row("library_registered", HIT,
                      (f"`library/` 里有 {len(got)} 个文件没有 `literature` 行引用"
                       "（书架只该放已登记的）"), list(got)[:max_items])


def run(workspace: Path | str, *, root: Path | str | None = None,
        max_items: int = DEFAULT_MAX_ITEMS) -> tuple[int, dict]:
    """跑四项并给出 `(退出码, 读数)`。"""
    ws = Path(workspace).expanduser().resolve()
    product = Path(root).expanduser().resolve() if root else _product_root()
    payload: dict = {
        "script": PROG,
        "workspace": str(ws),
        "product_root": str(product),
        "workspace_marker": {},
        "checks": [],
        "problem_items": [],
        "unsupported_items": [],
        "unknown_checks": [],
        "na_checks": [],
        "state": UNKNOWN,
        "exit_code": EXIT_UNKNOWN,
        "reason": "",
    }
    if not ws.is_dir():
        payload["reason"] = f"工作区不在：{ws} ⇒ 没查成（不是「落点都干净」）"
        return EXIT_UNKNOWN, payload
    schema, seedinject, why = load_modules(product)
    if schema is None:
        payload["reason"] = why
        return EXIT_UNKNOWN, payload

    looks, why_not = _looks_like_workspace(ws, schema)
    payload["workspace_marker"] = {"looks_like_workspace": looks, "detail": why_not}
    if not looks:
        payload["reason"] = (f"{ws} 不像一个工作区：{why_not}"
                             " ⇒ 没查成（四项链的是工作区的盘面，不是随便一棵树）")
        return EXIT_UNKNOWN, payload

    checks = [
        _check_data(schema, ws, max_items),
        _check_manuscripts(ws, max_items),
        _check_reports(ws, max_items),
        _check_library(seedinject, ws, max_items),
    ]
    payload["checks"] = checks
    payload["problem_items"] = [f"{c['check']}：{c['detail']}" for c in checks if c["state"] == HIT]
    payload["unsupported_items"] = [f"{c['check']}：{c['detail']}"
                                    for c in checks if c["state"] == UNSUPPORTED]
    payload["unknown_checks"] = [c["check"] for c in checks if c["state"] == UNKNOWN]
    payload["na_checks"] = [c["check"] for c in checks if c["state"] == NA]

    unsupported_names = [c["check"] for c in checks if c["state"] == UNSUPPORTED]
    if payload["problem_items"]:
        payload["state"], code = HIT, EXIT_BAD
        payload["reason"] = ("命中了 " + "、".join(c["check"] for c in checks if c["state"] == HIT)
                             + "（已知的坏优先于旁边没查成的那一项）")
        if unsupported_names:
            payload["reason"] += "；另有旧布局（不再支持）：" + "、".join(unsupported_names)
        if payload["unknown_checks"]:
            payload["reason"] += "；另有没查成的项：" + "、".join(payload["unknown_checks"])
    elif unsupported_names:
        # 旧布局是"查过了、结论是旧的"：不是 hit（新布局下的缺陷），也不是 unknown（没查成）。
        payload["state"], code = UNSUPPORTED, EXIT_BAD
        payload["reason"] = ("命中了旧布局（不再支持）：" + "、".join(unsupported_names)
                             + "（旧布局不是「干净」，也不是「没查成」）")
        if payload["unknown_checks"]:
            payload["reason"] += "；另有没查成的项：" + "、".join(payload["unknown_checks"])
    elif payload["unknown_checks"]:
        payload["state"], code = UNKNOWN, EXIT_UNKNOWN
        payload["reason"] = ("这些项没查成：" + "、".join(payload["unknown_checks"])
                             + " ⇒ 没查成（不是「落点都干净」）")
    elif not [c for c in checks if c["state"] == CLEAR]:
        # 四项全是 na：一项都没判过。照 closing 的同一条规矩（八格全 na 不落 pass），
        # 这里也不落 0 —— 没有可判对象不等于落点都干净。
        payload["state"], code = UNKNOWN, EXIT_UNKNOWN
        payload["reason"] = ("四项都没有可判对象（不适用：" + "、".join(payload["na_checks"])
                             + "）⇒ 没查成（不是「落点都干净」）")
    else:
        payload["state"], code = CLEAR, EXIT_OK
        payload["reason"] = "四项都查了、都没有命中"
        if payload["na_checks"]:
            payload["reason"] += "（不适用：" + "、".join(payload["na_checks"]) + "）"
    payload["exit_code"] = code
    return code, payload


def render_text(payload: dict) -> str:
    """人读版：一行一项，命中的逐条列出来。"""
    lines = [f"工作区 {payload['workspace']}",
             f"读数   state={payload['state']}  exit={payload['exit_code']}"]
    marker = payload.get("workspace_marker") or {}
    if marker.get("detail"):
        lines.append(f"工作区 {'是' if marker.get('looks_like_workspace') else '否'}：{marker['detail']}")
    lines.append("")
    for cell in payload["checks"]:
        lines.append(f"  [{cell['state']}] {cell['check']}")
        lines.append(f"          {cell['detail']}")
        for item in cell["items"]:
            lines.append(f"            - {item}")
    lines.append("")
    if payload["exit_code"] == EXIT_BAD:
        lines.append("结论：有旧布局（不再支持）（1）—— 逐项见上"
                     if payload.get("state") == UNSUPPORTED else
                     "结论：有命中（1）—— 逐项见上")
    else:
        lines.append({0: "结论：四项都没有命中（0）",
                      2: "结论：没查成（2）—— 0 不是「落点都干净」"}[payload["exit_code"]])
    lines.append(f"理由：{payload['reason']}")
    return "\n".join(lines)


# --------------------------------------------------------------------------- 自测
def _write_lf(path: Path, text: str) -> None:
    """按 UTF-8 + LF 写文本（新文件带 CRLF 会被 lint 的 R012 记成 error）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)


def _write_json(path: Path, doc: dict) -> None:
    """按 UTF-8 + LF 写一份 JSON 文档（表的形状：`{"rows": [...]}`）。"""
    _write_lf(path, json.dumps(doc, ensure_ascii=False, indent=2) + "\n")


def _fixture_clean(ws: Path) -> Path:
    """干净夹具：表 + 登记旁路 + 已登记的书 + 正文，没有 reports/；账本在 canonical 位。"""
    _write_json(ws / "data" / "literature.json",
                {"rows": [{"lit_id": "lit:000001", "path": "library/book.pdf"}]})
    _write_lf(ws / "data" / "counters.json", "{}\n")
    _write_lf(ws / "data" / "events.jsonl", "")
    _write_lf(ws / "library" / "book.pdf", "%PDF-1.4 夹具\n")
    _write_lf(ws / "work" / "handoffs.jsonl", "")
    _write_lf(ws / "manuscripts" / "F" / "m-000001.md", "# 夹具正文\n")
    return ws


def _fixture_dirty(ws: Path) -> Path:
    """脏夹具：非表文件 + 旧布局 reports/ + 没有正文 + 未登记的书。"""
    _write_json(ws / "data" / "literature.json", {"rows": []})
    _write_lf(ws / "data" / "lp_ball_final.json", "{}\n")
    _write_lf(ws / "data" / "stray-dir" / "x.txt", "x\n")
    _write_lf(ws / "library" / "unregistered.pdf", "%PDF-1.4 夹具\n")
    _write_lf(ws / "work" / "handoffs.jsonl", "")
    _write_lf(ws / "reports" / "000000-research.md", "# 旧布局\n")
    return ws


def _fixture_old_ledger(ws: Path) -> Path:
    """旧账本夹具：像工作区（`data/` 有表），但交接账本还在 `manuscripts/`（旧布局）。"""
    _write_json(ws / "data" / "literature.json", {"rows": []})
    _write_lf(ws / "manuscripts" / "handoffs.jsonl", "")
    return ws


def selftest() -> int:
    """四条自测：通过（干净夹具）/ 失败（脏夹具）/ 旧布局（旧账本夹具）/ 没查成（没有 data/）。

    期望值是"这一棵树的判据面"的函数，不是写死的 0：第 4 项依赖
    `seedinject.unregistered_library_files`，而干净 clone 上的 HEAD 可能还没有这个函数
    （它是 2026-11-22 之后才落盘的）。那时干净夹具的正确答案是 2（没查成），不是 0 ——
    自测把这个差别算进期望里，并把它打在读数后面。
    """
    rows: list[tuple[str, str, int, int]] = []
    schema, seedinject, why = load_modules(_product_root())
    if schema is None:
        print(f"自测没跑成：{why}")
        return EXIT_UNKNOWN
    judge = callable(getattr(seedinject, "unregistered_library_files", None))
    clean_want = EXIT_OK if judge else EXIT_UNKNOWN
    clean_detail = ("干净夹具（表 + 旁路 + 已登记书 + 正文）" if judge else
                    "干净夹具；但这一版没有 unregistered_library_files ⇒ 第 4 项没查成，期望 2")
    import tempfile  # noqa: PLC0415 - 只在自测里用，不占生产路径的 import 表

    with tempfile.TemporaryDirectory(prefix="b7-landing-") as tmp:
        base = Path(tmp)
        cases = (
            ("通过", clean_detail, _fixture_clean, clean_want),
            ("失败", "脏夹具（非表文件 + reports/ + 无正文 + 未登记书）", _fixture_dirty, EXIT_BAD),
            ("旧布局", "旧账本夹具（只有 manuscripts/handoffs.jsonl）", _fixture_old_ledger, EXIT_BAD),
        )
        for kind, detail, build, want in cases:
            code, _payload = run(build(base / kind))
            rows.append((kind, detail, want, code))
        empty = base / "no-data"
        empty.mkdir(parents=True, exist_ok=True)
        code, _payload = run(empty)
        rows.append(("没查成", "空目录（没有 data/ ⇒ 不像工作区）", EXIT_UNKNOWN, code))

    print("自测（夹具是 tempfile 里的最小工作区；判据是 schema / seedinject 的原函数）")
    bad = 0
    for kind, detail, want, got in rows:
        flag = "OK  " if want == got else "BAD "
        if want != got:
            bad += 1
        print(f"  [{flag}] {kind:4s} 期望 exit={want} 实际 exit={got}  （{detail}）")
    print(f"自测结论：{len(rows) - bad}/{len(rows)} 条符合期望")
    return EXIT_OK if not bad else EXIT_UNKNOWN


def main(argv: list[str] | None = None) -> int:
    """入口：解析参数、跑四项、按三态返回退出码。"""
    _pin_utf8()
    parser = argparse.ArgumentParser(
        prog=PROG,
        description=("工作区落点体检（只读）：data/ 非表文件、manuscripts/ 无正文"
                     "（manuscripts/handoffs.jsonl 报旧布局不再支持）、reports/ 旧布局、"
                     "library/ 未登记文件；0 干净 / 1 命中或旧布局 / 2 没查成"),
        allow_abbrev=False,
    )
    parser.add_argument("--workspace", default="", help="工作区根（必填，例如 projects/lp-ball-15）")
    parser.add_argument("--root", default=str(_product_root()),
                        help="产品根（缺省 = 本脚本的上一级；判据从它的 src/ 里导入）")
    parser.add_argument("--max-items", type=int, default=DEFAULT_MAX_ITEMS,
                        help=f"每项最多点名几条（缺省 {DEFAULT_MAX_ITEMS}；计数仍是全量）")
    parser.add_argument("--json", action="store_true", help="输出机器读数")
    parser.add_argument("--selftest", action="store_true",
                        help="用 tempfile 造最小工作区自测（通过 / 失败 / 没查成）")
    args = parser.parse_args(argv)

    if args.selftest:
        return selftest()

    if not str(args.workspace or "").strip():
        print("必须给 --workspace <工作区根>（这四项查的都是一个工作区的盘面）", file=sys.stderr)
        return EXIT_UNKNOWN

    code, payload = run(args.workspace, root=args.root, max_items=args.max_items)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(render_text(payload))
    return code


if __name__ == "__main__":
    raise SystemExit(main())

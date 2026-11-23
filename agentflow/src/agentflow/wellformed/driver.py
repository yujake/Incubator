# -*- coding: utf-8 -*-
"""
驱动：摊开文件清单、跑一类规则、三态合成，与两个对外入口。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .. import jsonlfile as JL
from .manuscripts import _manuscript_name, _proof_name
from .predicates import _Unchecked, _is_int, _rel, _shown
from .reader import _SPECS, _Spec, _read_json, _spec_path
from .registry import RULES, _Ctx
from .states import (EXIT_MALFORMED, EXIT_OK, EXIT_UNCHECKED, KINDS, MALFORMED, OK,
                     SEVERITIES, UNCHECKED, CheckResult, Finding)


# ---------------------------------------------------------------- 驱动


def _rows_of(doc: Any, key: str = "rows") -> list[tuple[int, Mapping[str, Any]]]:
    """JSON 表对象 ⇒ `(1 起条号, 行)`；非对象行不出现在这里（由上层的形状规则报）。"""
    if not isinstance(doc, Mapping):
        return []
    rows = doc.get(key)
    if not isinstance(rows, list):
        return []
    return [(i + 1, r) for i, r in enumerate(rows) if isinstance(r, Mapping)]


def _run_rules(ctx: _Ctx) -> tuple[list[Finding], list[str], list[str]]:
    """跑完该类产物的全部规则，返回 `(findings, 没查成的理由, 顺带的读数)`。"""
    findings: list[Finding] = []
    reasons: list[str] = []
    for name, fn in RULES.get(ctx.kind, {}).items():
        try:
            got = fn(ctx)
        except _Unchecked as exc:
            reasons.append(f"{name}：{exc}")
            continue
        findings.extend(got)
    return findings, reasons, list(ctx.notes)


def _state_of(findings: Sequence[Finding], reasons: Sequence[str]) -> str:
    """三态合成：有 error/warning 就是 malformed，否则看有没有没查成。

    `info` 的 Finding 不把整类翻成 malformed：它是"有读数、且已有解释"的那一档
    （例如手稿登记之后才落的签块让 ARTIFACTS 的 sha 落后一格）。把它算畸形，会让
    "签块落盘"这条正常路径把每一份签过的稿都读成畸形。`info` 仍逐条列出，看得见。

    2026-11-22：这里曾有一段"`legacy` 同理（旧形态、读得通、不是畸形）"的说明。
    业主裁定「旧工作区不必兼容」之后 `legacy` 那一档删掉了：旧布局现在报 `error`、
    照常翻 `malformed`（那个决定只剩 `layout.UNSUPPORTED_SEVERITY` 一格）。
    """
    if any(f.severity in ("error", "warning") for f in findings):
        return MALFORMED
    if reasons:
        return UNCHECKED
    return OK


def _check_json_rows(kind: str, root: Path, path: Path, *, spec: _Spec) -> CheckResult:
    """一个 `{"<rows_key>": [...]}` 表文件的检查。"""
    rel = _rel(root, path)
    key = spec.rows_key
    try:
        doc = _read_json(path)
    except (OSError, UnicodeDecodeError) as exc:
        return CheckResult(kind, UNCHECKED, rel,
                           reasons=[f"读不出来（{type(exc).__name__}: {exc}）"])
    except json.JSONDecodeError as exc:
        return CheckResult(kind, UNCHECKED, rel,
                           reasons=[f"不是合法 JSON（{exc}）⇒ 这一张表读不懂"])
    if not isinstance(doc, Mapping):
        want = f"带 schema_version 与 {key} 的对象" if spec.version else f"带 {key} 的对象"
        return CheckResult(kind, MALFORMED, rel, findings=[Finding(
            kind, rel, f"顶层读到 {_shown(doc)}，应为{want}",
            "error", "table_top")])
    ctx = _Ctx(kind, root, path, rel, doc, _rows_of(doc, key))
    findings, reasons, notes = _run_rules(ctx)
    if not isinstance(doc.get(key), list):
        findings.insert(0, Finding(
            kind, f"{rel}#{key}", f"`{key}` 读到 {_shown(doc.get(key))}，应为数组",
            "error", "table_rows"))
    if spec.version and not _is_int(doc.get("schema_version")):
        findings.insert(0, Finding(
            kind, f"{rel}#schema_version",
            f"`schema_version` 读到 {_shown(doc.get('schema_version'))}，应为整数",
            "warning", "table_version"))
    return CheckResult(kind, _state_of(findings, reasons), rel, findings,
                       notes=notes, reasons=reasons)


def _check_jsonl(kind: str, root: Path, path: Path) -> CheckResult:
    """一个 JSONL 文件的检查（坏行口径走 `jsonlfile`）。"""
    rel = _rel(root, path)
    records, problems, state = JL.read_jsonl_state(path)
    if state == "unreadable":
        return CheckResult(kind, UNCHECKED, rel,
                           reasons=[s for s in problems] or ["读不出来"])
    ctx = _Ctx(kind, root, path, rel, records,
               [(i + 1, r) for i, r in enumerate(records)], line_problems=problems)
    findings, reasons, notes = _run_rules(ctx)
    if kind == "sessions" and records and not any("seq" in r for r in records):
        notes.append("这一份事件流没有 `seq` 字段（顺序按文件行序；单调判据不适用）")
    return CheckResult(kind, _state_of(findings, reasons), rel, findings,
                       notes=notes, reasons=reasons)


def _check_json_file(kind: str, root: Path, path: Path) -> CheckResult:
    """一个 JSON 文件的检查（vsigns 那一类，没有 `rows` 包装）。"""
    rel = _rel(root, path)
    try:
        obj = _read_json(path)
    except (OSError, UnicodeDecodeError) as exc:
        return CheckResult(kind, UNCHECKED, rel,
                           reasons=[f"读不出来（{type(exc).__name__}: {exc}）"])
    except json.JSONDecodeError as exc:
        return CheckResult(kind, MALFORMED, rel, findings=[Finding(
            kind, rel, f"不是合法 JSON（{exc}）", "error", "json_parse")])
    if not isinstance(obj, Mapping):
        return CheckResult(kind, MALFORMED, rel, findings=[Finding(
            kind, rel, f"顶层读到 {_shown(obj)}，应为对象", "error", "json_top")])
    ctx = _Ctx(kind, root, path, rel, obj)
    findings, reasons, notes = _run_rules(ctx)
    return CheckResult(kind, _state_of(findings, reasons), rel, findings,
                       notes=notes, reasons=reasons)


def _check_text_file(kind: str, root: Path, path: Path) -> CheckResult:
    """一个 Markdown 文件的检查（手稿头 / 证明稿）。"""
    rel = _rel(root, path)
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return CheckResult(kind, UNCHECKED, rel,
                           reasons=[f"读不出来（{type(exc).__name__}: {exc}）"])
    ctx = _Ctx(kind, root, path, rel, text)
    findings, reasons, notes = _run_rules(ctx)
    return CheckResult(kind, _state_of(findings, reasons), rel, findings,
                       notes=notes, reasons=reasons)


def _check_tree(kind: str, root: Path) -> CheckResult:
    """整棵树一类的检查（`path-tree`：规则自己摊开文件清单）。

    为什么另立一个形态而不是塞进 `md-dir`：布局是整棵树的属性 —— `reports/x.md` 与
    `manuscripts/A/x.md` 是两份同名字节，判词却相反，而"它旁边的目录叫什么"不是单份文件
    能回答的。所以这一类只建一个 `_Ctx`（`path=None`、`rel=""`），把清单交给规则，
    findings 的 `where` 由规则逐份填（见 `layout._rule_layout`）。
    """
    ctx = _Ctx(kind, root, None, "", None)
    findings, reasons, notes = _run_rules(ctx)
    return CheckResult(kind, _state_of(findings, reasons), ".", findings,
                       notes=notes, reasons=reasons)


def _merge(kind: str, results: Sequence[CheckResult]) -> CheckResult:
    """把一批同类的单文件结果并成一条（三态取"最坏"：malformed > unchecked > ok）。"""
    findings = [f for r in results for f in r.findings]
    reasons = [f"{r.where}：{why}" for r in results for why in r.reasons]
    notes = [f"{r.where}：{one}" for r in results for one in r.notes]
    return CheckResult(kind, _state_of(findings, reasons),
                       results[0].where if len(results) == 1 else f"{len(results)} 份",
                       findings, notes=notes, reasons=reasons)


def _files_for(spec: _Spec, root: Path) -> list[Path]:
    """按 `_Spec` 摊开要检查的文件清单。"""
    target = _spec_path(root, spec.rel)
    if spec.mode.endswith("-dir"):
        if not target.is_dir():
            return []
        pattern = spec.pattern or "*"
        if spec.mode == "json-dir" or spec.mode == "jsonl-dir":
            names = sorted(p for p in target.glob(pattern)
                           if p.is_file() and p.name not in spec.skip)
            return names
        return sorted(p for p in target.glob(spec.pattern or "*.md") if p.is_file())
    return [target] if target.is_file() else []


def check_kind(kind: str, root: str | Path) -> CheckResult:
    """查一类产物（CLI 与读数面共用的入口）。

    落点按 :data:`_SPECS`；文件不存在时：必修表判 `unchecked`，可选产物判 `ok`
    （"没有这类产物"不是没查成）。这一条分界是刻意的：一个 init 过的工作区每张表都有
    空文件，缺表说明这个目录不是工作区或没 init 过；而 `out/vsigns/` / `sessions/`
    在没有产物时本来就不存在。
    """
    root_p = Path(root)
    if kind not in _SPECS:
        return CheckResult(kind, UNCHECKED, "",
                           reasons=[f"没实现这一类：{kind}（可选：{list(KINDS)}）"])
    if not root_p.is_dir():
        return CheckResult(kind, UNCHECKED, str(root_p),
                           reasons=[f"工作区不存在：{root_p}"])
    spec = _SPECS[kind]
    target = _spec_path(root_p, spec.rel)
    if not target.exists():
        if spec.required:
            return CheckResult(kind, UNCHECKED, spec.rel,
                               reasons=[f"缺 {spec.rel}（工作区没 init 过？）⇒ 没查成"])
        return CheckResult(kind, OK, spec.rel,
                           notes=[f"没有 {spec.rel}（这一类产物不存在，不是没查成）"])
    if spec.mode == "path-tree":
        return _check_tree(kind, root_p)
    if spec.mode == "json-rows":
        return _check_json_rows(kind, root_p, target, spec=spec)
    if spec.mode == "jsonl":
        return _check_jsonl(kind, root_p, target)
    if spec.mode == "json-dir":
        results = [_check_json_file(kind, root_p, p) for p in _files_for(spec, root_p)]
        return _merge(kind, results) if results else CheckResult(
            kind, OK, spec.rel, notes=[f"{spec.rel} 里没有 {kind} 文件"])
    if spec.mode == "jsonl-dir":
        results = [_check_jsonl(kind, root_p, p) for p in _files_for(spec, root_p)]
        return _merge(kind, results) if results else CheckResult(
            kind, OK, spec.rel, notes=[f"{spec.rel} 里没有 {kind} 文件"])
    # md-dir
    matcher = _proof_name if kind == "proof_reports" else _manuscript_name
    picked = [p for p in _files_for(spec, root_p) if matcher(_rel(root_p, p))]
    results = [_check_text_file(kind, root_p, p) for p in picked]
    return _merge(kind, results) if results else CheckResult(
        kind, OK, spec.rel, notes=[f"{spec.rel} 里没有这一类手稿"])


@dataclass
class WorkspaceReport:
    """一个工作区的全量检查结果。"""

    root: str
    results: list[CheckResult]

    @property
    def state(self) -> str:
        """整份读数：有畸形 ⇒ malformed；否则有没查成 ⇒ unchecked；否则 ok。"""
        if any(r.state == MALFORMED for r in self.results):
            return MALFORMED
        if any(r.state == UNCHECKED for r in self.results):
            return UNCHECKED
        return OK

    @property
    def findings(self) -> list[Finding]:
        """按严重度排序后的全部 Finding（error 在前）。"""
        order = {s: i for i, s in enumerate(SEVERITIES)}
        return sorted((f for r in self.results for f in r.findings),
                      key=lambda f: (order.get(f.severity, 9), f.kind, f.where))

    @property
    def exit_code(self) -> int:
        """三态 ⇒ 退出码（0 / 1 / 2）。"""
        return {OK: EXIT_OK, MALFORMED: EXIT_MALFORMED,
                UNCHECKED: EXIT_UNCHECKED}[self.state]

    def counts_by_kind(self) -> dict[str, dict[str, int]]:
        """每一类产物的三态与条数（普查表用它）。"""
        return {r.kind: {"state": r.state, "findings": len(r.findings),
                         **r.counts()}
                for r in self.results}

    def as_dict(self) -> dict[str, Any]:
        """给 `--json` 用的纯数据形态。"""
        return {"root": self.root, "state": self.state, "exit_code": self.exit_code,
                "counts": {r.kind: len(r.findings) for r in self.results},
                "by_kind": self.counts_by_kind(),
                "results": [r.as_dict() for r in self.results]}


def check_workspace(root: str | Path, kinds: Iterable[str] | None = None) -> WorkspaceReport:
    """查一个工作区的全部（或点名的几类）产物。

    `kinds` 里出现未知名字 ⇒ 那一条以 `unchecked` 落进结果（"没实现"不是"干净"）。
    """
    picked = list(kinds) if kinds else list(KINDS)
    root_p = Path(root)
    return WorkspaceReport(str(root_p), [check_kind(k, root_p) for k in picked])


def workspace_reading(root: str | Path) -> dict[str, Any]:
    """读数面（`statusreport.collect`）用的那一格：三态 + 条数 + 前几条原文。

    只读、零模型调用、不改盘。它不返回 blocker 语义的东西：这一格被看见，不被用来拦。
    """
    report = check_workspace(root)
    findings = report.findings
    by_sev = {s: 0 for s in SEVERITIES}
    for f in findings:
        by_sev[f.severity] = by_sev.get(f.severity, 0) + 1
    unchecked = [r.kind for r in report.results if r.state == UNCHECKED]
    return {
        "checked": report.state != UNCHECKED,
        "state": report.state,
        "exit_code": report.exit_code,
        "kinds": {r.kind: r.state for r in report.results},
        "findings": len(findings),
        "by_severity": by_sev,
        "by_kind": {r.kind: len(r.findings) for r in report.results},
        "unchecked": unchecked,
        "examples": [f.as_dict() for f in findings[:5]],
        "reason": ("" if report.state != UNCHECKED else
                   "没查成：" + "；".join(f"{r.kind}（{'；'.join(r.reasons)}）"
                                          for r in report.results
                                          if r.state == UNCHECKED)),
    }

# -*- coding: utf-8 -*-
"""
三态、退出码与三张读数类型（`Malformation` / `Finding` / `CheckResult`）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------- 三态与退出码

#: 一份（或一类）产物的三态。`unchecked` 是"没查成"，不许折成 `ok`。
OK = "ok"
MALFORMED = "malformed"
UNCHECKED = "unchecked"
STATES: tuple[str, ...] = (OK, MALFORMED, UNCHECKED)

#: CLI 退出码：0 = 全 ok / 1 = 有畸形 / 2 = 没查成。
EXIT_OK = 0
EXIT_MALFORMED = 1
EXIT_UNCHECKED = 2

#: Finding 的严重度。`error` 是形状/词表/指向的硬伤；`warning` 是应当看得见但可能
#: 有正当来由的读数（例如旧工作区把 `path` 存成工作区相对路径）；`info` 是"有读数、
#: 但已有解释"（例如手稿登记之后才落的签块让 ARTIFACTS 的 sha 落后一格）。
#:
#: 2026-11-22：这里曾有一档 `LEGACY = "legacy"`（B2a 给"旧布局读得通、不判畸形"立的
#: 严重度名：进读数、不改三态）。业主 2026-11-22 裁定「旧工作区不必兼容」之后那一档
#: 连同常量一起删了 —— 旧布局（`reports/` / `documents/` / `manuscripts/handoffs.jsonl`
#: 与 `library/<lit_id>/` 两种旧落点）现在报 `error`、翻 `malformed`、退出码 1
#: （严重度只有一个决定点：`layout.UNSUPPORTED_SEVERITY`）。不许把 `legacy` 加回来：
#: 加回来等于把"旧工作区还能用"这条已撤销的裁定悄悄恢复成默认值。
SEVERITIES: tuple[str, ...] = ("error", "warning", "info")

#: 本工具覆盖的产物类别。名字就是 CLI 的 `--kind` 取值。
KINDS: tuple[str, ...] = (
    "vsigns",
    "literature",
    "relations",
    "statements",
    "lit_candidates",
    "tasks",
    "usage_ledger",
    "sessions",
    "manuscripts",
    "proof_reports",
    "acceptance",
    "artifacts",
    "roster_retired",
    # 2026-11-22（B2b-1）：落点布局。它不是"一份产物"而是一棵树 —— 落点是整棵树的属性
    # （同一份 `x.md` 在 `reports/` 下是旧落点、在 `work/A/` 下是草稿），所以它有自己的一档
    # 类别与自己的读法（`reader._SPECS["layout"]` 的 `path-tree`，规则见 `layout.py`）。
    "layout",
    # 2026-11-22（PAPER-PKG-FIX）：论文包。同一条 `path-tree` 读法，两条规则：
    # `appendix.tex` 必须是片段且被 `main.tex` `\input`；有台账渲染物而研究台账全空
    # ⇒ 点名（`paperpackage.py`）。这一档只报，不进收工门。
    "paper_package",
)

#: 工作区里"必须有"的表由 `reader.py` 的 `_Spec(required=True)` 逐条声明。
#: （2026-11-22：这里曾有一份 `REQUIRED_KINDS` 副本，零读者且与那份声明重复，已删 ——
#: "必须有"只能有一个真身。）


@dataclass(frozen=True)
class Malformation:
    """一条畸形读数。

    `where` 说"在哪一份文件的哪一个位置"，`detail` 说"读到的是什么、该改成什么"。
    `detail` 里必须带逐字读数：只说"这里不对"的 Finding 没法复核，等于没有。

    真身叫 `Malformation` 而不是 `Finding`：`closing.py` 已有一个公开的 `Finding`，
    同名两份实现会被 lint 的 R003 记成"同一判据两个落位"（那正是它要防的漂移），而
    两者并不是同一个东西（`closing.Finding` 属于收工门的格子，这一份属于产物畸形）。
    下面的 `Finding` 只是本模块内部的短别名。
    """

    kind: str
    where: str
    detail: str
    severity: str = "error"
    code: str = ""

    def as_dict(self) -> dict[str, str]:
        """给 `--json` 与读数面用的纯数据形态。"""
        return {"kind": self.kind, "where": self.where, "detail": self.detail,
                "severity": self.severity, "code": self.code}


#: 本模块内部的短名（对外仍可写 `wellformed.Finding`）。
Finding = Malformation


@dataclass
class CheckResult:
    """一类（或一份）产物的检查结果：三态 + 逐条 Finding + 没查成的理由。"""

    kind: str
    state: str
    where: str = ""
    findings: list[Finding] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """这一份查过了且没有畸形（`unchecked` 不是 ok）。"""
        return self.state == OK

    def counts(self) -> dict[str, int]:
        """按严重度与按 finding code 的条数（普查表用它统计）。"""
        by_sev = {s: 0 for s in SEVERITIES}
        by_code: dict[str, int] = {}
        for f in self.findings:
            by_sev[f.severity] = by_sev.get(f.severity, 0) + 1
            by_code[f.code] = by_code.get(f.code, 0) + 1
        return {**{f"severity.{k}": v for k, v in by_sev.items()},
                **{f"code.{k}": v for k, v in by_code.items()}}

    def as_dict(self) -> dict[str, Any]:
        """给 `--json` 用的纯数据形态。"""
        return {"kind": self.kind, "state": self.state, "where": self.where,
                "findings": [f.as_dict() for f in self.findings],
                "notes": list(self.notes), "reasons": list(self.reasons)}

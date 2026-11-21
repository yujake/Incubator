# -*- coding: utf-8 -*-
"""
每一类产物的落点声明（`_Spec` / `_SPECS`）与读一个 JSON 的唯一入口。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


# ---------------------------------------------------------------- 读盘（唯一入口）


def _read_json(path: Path) -> Any:
    """读一个 JSON 文件（调用方负责把失败翻成 unchecked 或 Finding）。"""
    return json.loads(path.read_text(encoding="utf-8"))


def _spec_path(root: Path, rel: str) -> Path:
    """工作区相对路径 ⇒ 绝对路径。"""
    return root / rel


#: 每一类产物的落点与读法。`mode` 决定 `check_kind` 怎么把它摊开：
#: - `json-rows`：一个 JSON 文件，`rows` 是数组；
#: - `jsonl`：一个 JSONL 文件；
#: - `json-dir`：目录下一批 JSON 文件（一份文件一条读数）；
#: - `jsonl-dir`：目录下一批 JSONL 文件；
#: - `md-dir`：目录下一批 Markdown 文件（按名字筛）。
@dataclass(frozen=True)
class _Spec:
    """一类产物的落点声明。

    `rows_key` 是顶层装行数组的键：普通表是 `rows`，验收表是 `checks`。
    `version` 说这一份有没有 `schema_version`（验收表没有）。
    """

    rel: str
    mode: str
    required: bool = False
    pattern: str = ""
    skip: tuple[str, ...] = ()
    label: str = ""
    rows_key: str = "rows"
    version: bool = True


_SPECS: Mapping[str, _Spec] = {
    "literature": _Spec("data/literature.json", "json-rows", required=True, label="文献库"),
    "relations": _Spec("data/relations.json", "json-rows", required=True, label="关系"),
    "statements": _Spec("data/statements.json", "json-rows", required=True, label="命题台账"),
    "lit_candidates": _Spec("data/lit_candidates.json", "json-rows", required=True,
                            label="候选文献"),
    "tasks": _Spec("data/tasks.json", "json-rows", required=True, label="任务台账"),
    "usage_ledger": _Spec("data/usage_ledger.json", "json-rows", required=True,
                          label="用量账"),
    "vsigns": _Spec("out/vsigns", "json-dir", pattern="*.json", skip=("issued.json",),
                    label="V 签侧文件"),
    "sessions": _Spec("sessions", "jsonl-dir", pattern="*.jsonl", label="会话记录"),
    "manuscripts": _Spec("reports", "md-dir", label="手稿头"),
    "proof_reports": _Spec("reports", "md-dir", label="证明稿"),
    "acceptance": _Spec("out/paper/ACCEPTANCE-CHECKS.json", "json-rows",
                        label="验收表", rows_key="checks", version=False),
    "artifacts": _Spec("ARTIFACTS.jsonl", "jsonl", label="产物登记台账"),
    "roster_retired": _Spec("out/roster", "jsonl-dir", pattern="*-retired.jsonl",
                            label="销号名单"),
}

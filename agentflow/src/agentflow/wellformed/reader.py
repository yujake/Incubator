# -*- coding: utf-8 -*-
"""
每一类产物的落点声明（`_Spec` / `_SPECS`）与读一个 JSON 的唯一入口。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

#: 验收表的落点只认一处真身（`closing.ACCEPTANCE_TARGETS_NAME` = `out/package/...`）。
#: 2026-11-22（PAPER-PKG-FIX）：文件名从 `ACCEPTANCE-CHECKS.json` 改为
#: `ACCEPTANCE-TARGETS.json` —— 它装的是目标/阈值，不是检查结论。不读旧名：
#: 旧文件在盘上就是"没写过"。
from .. import manuscripts as MS
from ..closing import ACCEPTANCE_TARGETS_NAME


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
#: - `md-dir`：目录下一批 Markdown 文件（按 `pattern` 摊开、再按名字筛）；
#: - `path-tree`：整棵树的布局（规则自己摊开清单，见 `driver._check_tree`）。
@dataclass(frozen=True)
class _Spec:
    """一类产物的落点声明。

    `rows_key` 是顶层装行数组的键：普通表是 `rows`，验收表是 `checks`。
    `version` 说这一份有没有 `schema_version`（验收表没有）。
    `pattern` 是摊开文件用的 glob（相对 `rel`）；空串时 `-dir` 各有缺省
    （`md-dir` 是 `*.md`）。正文手稿按角色分目录 ⇒ `manuscripts/*/*.md`。
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
    "manuscripts": _Spec(MS.MANUSCRIPTS_DIR, "md-dir", pattern="*/*.md", label="手稿头"),
    "proof_reports": _Spec(MS.MANUSCRIPTS_DIR, "md-dir", pattern="*/*.md", label="证明稿"),
    "acceptance": _Spec(ACCEPTANCE_TARGETS_NAME, "json-rows",
                        label="验收目标表", rows_key="checks", version=False),
    "artifacts": _Spec("ARTIFACTS.jsonl", "jsonl", label="产物登记台账"),
    "roster_retired": _Spec("out/roster", "jsonl-dir", pattern="*-retired.jsonl",
                            label="销号名单"),
    # 落点布局（2026-11-22 B2b-1）：`manuscripts/<角色>/` · `work/<角色>/` · `work/handoffs.jsonl`
    # 是新的合法落点，`reports/**` / `documents/**` / `manuscripts/handoffs.jsonl` 是旧布局
    # （按 `unsupported` 判 error；`legacy` 一档已按业主裁定删除）。
    # `rel="."` + `mode="path-tree"`：这一类不按一份文件判，规则自己摊开受管的那几个目录
    # （布局是整棵树的属性 —— 一份文件单独看判不出它旁边的目录叫什么）。
    "layout": _Spec(".", "path-tree", label="落点布局"),
    # 论文包（2026-11-22，PAPER-PKG-FIX）：`appendix.tex` 必须是片段且被 `main.tex`
    # `\input`；有台账渲染物而研究台账全空 ⇒ 点名。规则见 `paperpackage.py`。
    "paper_package": _Spec(".", "path-tree", label="论文包"),
}

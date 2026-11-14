# -*- coding: utf-8 -*-
"""命题类型那一轴：稿头标签 / 台账交叉核对 / 收录计划（2026-11-14 解耦）。

## 两根轴，各有自己的名字

业主 2026-11-14：「将命题类型和等级两组词进行解耦」。

- 命题类型（`statements.kind`：theorem / lemma / proposition / corollary /
  conjecture / example / concept / definition）—— 作者对「这是哪一种命题」的声明；
- 证据档位（`schema.EVIDENCE_KINDS`：proof / proof_review / cross_check /
  heuristic）—— `evidencebits.derive_grade` 从五元位算出来的那根轴。

改前手稿头那一行叫 `- 证据种类：`，装的确是命题类型 —— 名字借了另一根轴的词。
两处读者（`proofregistry.parse_entry` 与 `manuscriptintake.extract_cells`）各自
手写了一遍这个中文标签；改一处漏一处的形态是：写出来的稿读不回来，而没有任何
判据会红。所以本模块是那一轴标签的唯一权威来源：写侧与两个读侧都从这里取。

## 老盘旧名的读能力不删

`- 证据种类：` 是历史字节（`reports/` 下的老稿、`tests/fixtures/` 里的回放稿），
仓的纪律是「读能力不删」：读侧认旧名（`LEGACY_PROPOSITION_KIND_MARK`），写侧只
产生新名。旧稿被重写时那一行换成新名（同一格，不新增第二行）。

## 为什么 `extract_kind` / `plan_kind` 住在这里

它们是「命题类型」这一格的两个纯函数：从稿头取，与台账对。原先住在
`manuscriptintake`（那份文件正好压在 800 行软基线上）；2026-11-14 解耦要在那一格
里加交叉核对，而业主口径是「体量软基线不许抬」⇒ 把这一格整块搬出来，`manuscriptintake`
只保留一张转发表。搬的是同一份实现（`plan_cells` 仍调同一个函数）—— 不是第二套。
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

#: 手稿头那一行的新名（写侧只写这一个）。
PROPOSITION_KIND_MARK = "- 命题类型："

#: 老盘上的旧名（只读兼容；写侧不再产生，重写时换成新名）。
LEGACY_PROPOSITION_KIND_MARK = "- 证据种类："

#: 命题类型那根轴的交叉核对读数（2026-11-14 解耦）：台账 `statements.kind` 是权威，
#: 手稿头的 `- 命题类型：` 是交叉核对。不一致时给专用读数、不静默取其一。
#: 四个码只在 `kind_crosscheck` 一处产生（消费侧只读 `outcome` / `code`）。
KIND_CROSSCHECK_AGREE = "kind_crosscheck_agree"
KIND_CROSSCHECK_MISMATCH = "kind_crosscheck_mismatch"
KIND_CROSSCHECK_ABSENT = "kind_crosscheck_manuscript_absent"
KIND_CROSSCHECK_NO_LEDGER = "kind_crosscheck_ledger_absent"

#: `kind` 的受控词表（`secretary.PROPOSITION_KINDS` 的镜像）。
#: 顺序按档位从弱到强：`kind` 只升不降，升要签。
KIND_RANK: Mapping[str, int] = {
    "conjecture": 0, "example": 1, "proposition": 2,
    "lemma": 3, "corollary": 4, "theorem": 5,
}


def mark_key(mark: str) -> str:
    """`- 命题类型：` ⇒ `命题类型`（两个读侧解析稿头 `- 键：值` 用同一个口径）。"""
    return str(mark or "").strip().lstrip("-").strip().rstrip("：:").strip()


def kind_crosscheck(ledger_kind: Any, declared_kind: Any) -> dict[str, Any]:
    """台账 `statements.kind` 与稿头「命题类型」的交叉核对（台账为准，逐次留读数）。

    ## 单一权威来源（业主 2026-11-14）

    「命题类型以台账 `statements.kind` 为准；手稿上那一行是交叉核对，不一致时要有
    读数（不许静默取其一）」。所以这个函数只回答三件事：两侧各是什么、一致不一致、
    不一致时按谁算。它不改任何一侧 —— 要改类型是已签的升档那一格
    （`_apply_declared_manuscript_kind`）或台账写入路径的事。

    ## 三态，不是布尔

    - `agree`：两侧都非空且相等；
    - `mismatch`：两侧都非空而不同（`code=kind_crosscheck_mismatch`）—— 这是本函数
      存在的理由，调用方必须把它带进读数；
    - `manuscript_absent` / `ledger_absent`：有一侧本来就没有（新登记那一档还没有
      台账 kind，稿头也可以不声明）—— `agree=None`，不是"一致"，也不是"不一致"。

    四档的码只在上面 :data:`KIND_CROSSCHECK_*` 一处定义。
    """
    ledger = str(ledger_kind or "").strip().lower()
    declared = str(declared_kind or "").strip().lower()
    out: dict[str, Any] = {
        "checked": True, "agree": None, "ledger": ledger, "declared": declared,
        "outcome": "", "code": "", "why": "",
    }
    if not ledger:
        out.update(outcome="ledger_absent", code=KIND_CROSSCHECK_NO_LEDGER,
                   why=f"台账这一行还没有 kind ⇒ 没有可对的一侧（稿头声明 {declared!r}）")
        return out
    if not declared:
        out.update(outcome="manuscript_absent", code=KIND_CROSSCHECK_ABSENT,
                   why="稿头没有声明命题类型 ⇒ 这一格不核对（不拿台账现值冒充稿头）")
        return out
    if ledger == declared:
        out.update(agree=True, outcome="agree", code=KIND_CROSSCHECK_AGREE,
                   why=f"台账 kind={ledger!r} 与稿头「命题类型」一致")
        return out
    out.update(agree=False, outcome="mismatch", code=KIND_CROSSCHECK_MISMATCH,
               why=(f"台账 kind={ledger!r} 与稿头「命题类型」{declared!r} 不一致 ⇒ "
                    "以台账为准；要改类型走已签的升档那一格，不拿稿头静默改写"))
    return out


def extract_kind(text: str) -> dict[str, Any]:
    """稿头 `- 命题类型：<kind>` ⇒ 命题类型（小写；不在稿头里猜，也不从正文里猜）。

    老盘旧名 `- 证据种类：` 照读（仓的纪律「读能力不删」；2026-11-14 解耦前的字节）。
    两个名字同时出现时以新名为准；只认稿头（第一个 `##` 之前），不认正文里的同名行。
    """
    from . import manuscriptintake as _MI

    legacy: tuple[int, str] | None = None
    for line_no, raw in _MI._head_lines(text):
        matched = _MI._HEAD_FIELD_RE.match(raw)
        if not matched:
            continue
        key = matched.group("key").strip()
        if key not in (mark_key(PROPOSITION_KIND_MARK),
                       mark_key(LEGACY_PROPOSITION_KIND_MARK)):
            continue
        value = matched.group("value").strip().strip("`").strip().lower()
        if key == mark_key(LEGACY_PROPOSITION_KIND_MARK):
            if legacy is None:
                legacy = (line_no, value)
            continue
        if not value:
            return _MI._absent("kind", f"稿头第 {line_no} 行声明了命题类型但是空的")
        return _MI._reading("kind", _MI.EXTRACT_PRESENT, lines=[line_no, line_no],
                            sha=_MI._sha(value), value=value, label="命题类型",
                            why=f"稿头第 {line_no} 行声明的命题类型")
    if legacy is not None:
        line_no, value = legacy
        if not value:
            return _MI._absent(
                "kind", f"稿头第 {line_no} 行声明了命题类型但是空的（旧名 `证据种类`）")
        return _MI._reading("kind", _MI.EXTRACT_PRESENT, lines=[line_no, line_no],
                            sha=_MI._sha(value), value=value, label="证据种类（老盘旧名）",
                            why=f"稿头第 {line_no} 行声明的命题类型（老盘旧名 `证据种类`，照读）")
    return _MI._absent("kind", f"稿头没有 `{PROPOSITION_KIND_MARK}` 那一行 ⇒ 没有可填的类型")


def plan_kind(reading: Mapping[str, Any], row: Mapping[str, Any],
              conflict: str) -> dict[str, Any]:
    """`kind`（命题类型）：台账为准、稿头是交叉核对；只升不降，升档要签。

    两侧不一致时这一格必须带 `crosscheck` 读数（`outcome="mismatch"`）：升级 ⇒
    `kind_not_upgraded_without_sign`（先 kept，等签），降级 ⇒ `kind_downgrade`（整笔拒）。
    """
    from . import manuscriptintake as _MI

    def _cross(declared: str) -> dict[str, Any]:
        return kind_crosscheck(str(row.get("kind") or ""), declared)

    if reading.get("outcome") == _MI.EXTRACT_UNREADABLE:
        return _MI._refused(reading, True, _MI.CODE_UNREADABLE,
                            str(reading.get("why") or "稿头没读到"),
                            crosscheck=_cross(""))
    if reading.get("outcome") == _MI.EXTRACT_ABSENT:
        return _MI._planned(reading, _MI.PLAN_NOT_APPLICABLE, writable=True,
                            reason="稿头没有声明命题类型 ⇒ 这一格不适用（不拿台账现值冒充稿头）",
                            crosscheck=_cross(""))
    value = str(reading.get("value") or "")
    cross = _cross(value)
    if value not in KIND_RANK:
        return _MI._refused(reading, True, _MI.CODE_KIND_BAD,
                            f"稿头声明的命题类型 {value!r} 不在受控词表 {tuple(KIND_RANK)} 里",
                            crosscheck=cross)
    if str(row.get("kind") or "") in ("concept", "definition"):
        return _MI._refused(reading, True, _MI.CODE_CELL_NOT_APPLICABLE,
                            "概念 / 定义行没有证明档 ⇒ 不收 kind", crosscheck=cross)
    current = str(row.get("kind") or "")
    if _MI._is_register(row) or not current:
        return _MI._planned(reading, _MI.PLAN_FILLED, writable=True,
                            reason="新行：按稿头声明落 kind", crosscheck=cross)
    if value == current:
        return _MI._planned(reading, _MI.PLAN_UNCHANGED, writable=True, reason="与台账相同",
                            crosscheck=cross)
    if current not in KIND_RANK:
        return _MI._refused(reading, True, _MI.CODE_KIND_ROW_UNREADABLE,
                            f"台账上的 kind {current!r} 不在受控词表里 ⇒ 不比较强弱",
                            crosscheck=cross)
    if KIND_RANK[value] > KIND_RANK[current]:
        return _MI._planned(reading, _MI.PLAN_KEPT, writable=True,
                            reason=(f"台账更弱（{current}）、稿头更强（{value}）⇒ 签后才升；"
                                    "这一格先 kept"),
                            code=_MI.CODE_KIND_UPGRADE_UNSIGNED, crosscheck=cross)
    if conflict == "keep":
        return _MI._planned(reading, _MI.PLAN_KEPT, writable=True,
                            reason=f"conflict=keep：保留台账的 {current}（稿头 {value} 更弱）",
                            crosscheck=cross)
    return _MI._refused(reading, True, _MI.CODE_KIND_DOWNGRADE,
                        f"只升不降：台账 {current} 强于稿头 {value} ⇒ 拒", crosscheck=cross)

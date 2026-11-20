# -*- coding: utf-8 -*-
"""秘书的四本判定旁支台账：append / rows / of / path（从 secretary.py 的 U30 逐字搬出）。

我保证哪条不变式：每一次判定都落一行（包括"没查成"那一档），读侧只回三态 ——
`checked` 跟着 `rows` 走，读不出来时不许折成"没有这一行"。四本台账同形：派活适配、
命题形态、命题判词、同命题判定。

## 依赖方向

本模块只依赖 `secretary_ledger`（路径）与 `secretary_time`（时间戳），不依赖业务判据。
它是"判定面"与"台账面"之间那一层，所以必须在刀1 先落地：后面每一刀的判据模块都往里
写，但谁也不需要从 secretary.py 反向 import。

对外名字：`append_dispatch_fit` / `dispatch_fit_rows` / `append_proposition_form` /
`proposition_form_rows` / `proposition_form_of` / `append_statement_same` /
`statement_same_rows` / `append_proposition_verdict` / `proposition_verdict_of` /
`proposition_verdict_rows`。再导出仍在 secretary.py 里。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence
import hashlib
import json
from .secretary_ledger import (  # noqa: F401 — 这些名字由 secretary_ledger 定义
    dispatch_fit_path,
    proposition_form_path,
    proposition_verdicts_path,
    statement_same_path,
)
from .secretary_time import (  # noqa: F401 — 这些名字由 secretary_time 定义
    _now_iso,
)

def append_dispatch_fit(root: str | Path, *, to: str, task: str, checked: bool,
                        verdict: str = "", why: str = "", basis: Sequence[str] = (),
                        decision: str = "", cost_ledger: str = "", role: str = "",
                        task_id: str = "") -> dict[str, Any]:
    """追加一行派活审阅读数（append-only；显式 LF，与 `append_proposition_form` 同一口径）。

    每一次判定都记（含 `checked=False` 的"没查成"）：只记"不合适"的那几行，会让
    "秘书这一趟到底审过没有"在盘上消失 —— 那正是这条提醒要防的"静默放行"。
    `verdict` 只在 `checked=True` 时有值（`是一个方向` / `不是一个方向`）；
    `decision` 是台账那一栏
    的结论词（没查成时是 `没查成`，不是"合适"）。
    """
    path = dispatch_fit_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {"at": _now_iso(),
           "to": str(to or ""), "task": str(task or ""),
           "task_chars": len(str(task or "")),
           "checked": bool(checked), "verdict": str(verdict or ""),
           "why": str(why or ""), "basis": [str(x) for x in (basis or ())],
           "decision": str(decision or ""), "cost_ledger": str(cost_ledger or ""),
           "role": str(role or ""), "task_id": str(task_id or "")}
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        # `default=str` 与全仓同一口径（`tests/test_json_dumps_has_a_default.py`）。
        handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True, default=str) + "\n")
    return row


def dispatch_fit_rows(root: str | Path) -> list[dict[str, Any]]:
    """这本台账的全部行（读不出来 ⇒ 空列表，并把原因留给调用方那条三态读数去报）。"""
    path = dispatch_fit_path(root)
    if not path.is_file():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text:
            continue
        try:
            row = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(row, Mapping):
            out.append(dict(row))
    return out


def append_proposition_form(root: str | Path, *, statement_full: str, checked: bool,
                            well_formed: bool, conditions: str = "", conclusion: str = "",
                            problems: Sequence[str] = (), decision: str = "",
                            refused: str = "", reason: str = "", label: str = "",
                            kind: str = "", stmt_id: str = "", role: str = "",
                            task_id: str = "") -> dict[str, Any]:
    """追加一行形态判定读数（append-only；显式 LF，与 `append_proposition_verdict` 同一口径）。

    每一次判定都记（含"没查成"那一档）：读数要把"被拒了几条 / 每条是什么码"数得出来，
    而只记放行的那几条会让拒收在盘上消失 —— 那正是这道闸要防的"静默放行"。
    """
    path = proposition_form_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {"at": _now_iso(),
           "statement_sha256": _proposition_verdict_key(statement_full),
           "statement_chars": len(str(statement_full or "")),
           "checked": bool(checked), "well_formed": bool(well_formed),
           "conditions": str(conditions or ""), "conclusion": str(conclusion or ""),
           "problems": [str(x) for x in (problems or ())],
           "decision": str(decision or ""), "refused": str(refused or ""),
           "reason": str(reason or ""), "label": str(label or ""),
           "kind": str(kind or ""), "stmt_id": str(stmt_id or ""),
           "role": str(role or ""), "task_id": str(task_id or "")}
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        # `default=str` 与全仓同一口径（`tests/test_json_dumps_has_a_default.py`）。
        handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True, default=str) + "\n")
    return row


def proposition_form_rows(root: str | Path) -> list[dict[str, Any]]:
    """这本台账的全部行（读不出来 ⇒ 空列表，并把原因留给调用方那条三态读数去报）。"""
    path = proposition_form_path(root)
    if not path.is_file():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text:
            continue
        try:
            row = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(row, Mapping):
            out.append(dict(row))
    return out


def proposition_form_of(root: str | Path, *, statement_full: str = "",
                        stmt_id: str = "") -> dict[str, Any]:
    """这条命题的形态判定（读侧唯一口）。

    三态：空字典 = 没有判定过（不是"判过、合格"）；非空 = 有判定行，`well_formed`
    与 `checked` 两格说清结论。能不能缓存由调用方按 `checked` 决定 —— "没查成"的行
    不许挡住下一次调用（缝是可能好起来的，与 `proposition_verdict_of` 同一条纪律）。
    """
    key = _proposition_verdict_key(statement_full) if statement_full else ""
    last: dict[str, Any] = {}
    for row in proposition_form_rows(root):
        if stmt_id and str(row.get("stmt_id") or "") == str(stmt_id):
            last = row
            continue
        if key and str(row.get("statement_sha256") or "") == key:
            last = row
    return last


def append_statement_same(root: str | Path, *, stage: str, statement_full: str,
                          checked: bool, keywords: Sequence[str] = (),
                          hits_total: int = 0, candidates: Sequence[str] = (),
                          found: str = "", why: str = "", label: str = "",
                          kind: str = "", seam_source: str = "", role: str = "",
                          task_id: str = "") -> dict[str, Any]:
    """追加一行检索 / 判定读数（append-only；显式 LF，与形态台账同一口径）。

    每一次都记（含"没查成"那一档）：把"没查成"也留在盘上，读的人才分得清
    "查过、没查到"与"根本没查"。只记查到的那几笔会让 fail-closed 在盘上消失。
    """
    path = statement_same_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {"at": _now_iso(), "stage": str(stage or ""),
           "statement_sha256": _proposition_verdict_key(statement_full),
           "statement_chars": len(str(statement_full or "")),
           "checked": bool(checked),
           "keywords": [str(x) for x in (keywords or ())],
           "hits_total": int(hits_total or 0),
           "candidates": [str(x) for x in (candidates or ())][:50],
           "found": str(found or ""), "why": str(why or ""),
           "seam_source": str(seam_source or ""),
           "label": str(label or ""), "kind": str(kind or ""),
           "role": str(role or ""), "task_id": str(task_id or "")}
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True, default=str) + "\n")
    return row


def statement_same_rows(root: str | Path) -> list[dict[str, Any]]:
    """这本台账的全部行（读不出来 ⇒ 空列表，与形态台账同一条读法）。"""
    path = statement_same_path(root)
    if not path.is_file():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text:
            continue
        try:
            row = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(row, Mapping):
            out.append(dict(row))
    return out


def _proposition_verdict_key(statement_full: str) -> str:
    """缓存键：命题正文的 sha256（去首尾空白之后）。

    为什么键是正文而不是（正文 + 标签）：业主口径是"定理描述一致（什么条件推出什么结论），
    就是一个定理" —— 判定的对象是那一段描述，标签只是它的名字。同一条正文换个标签再交
    一次，判定结论不会有别的答案；按（正文 + 标签）做键就会为"改了个名字"再花一次钱。
    标签带来的那点差异由命中缓存之后的重放处理：结论与洗过的定理名一起沿用，读的人从
    `cached` 与 `label` 两格看得见这一次交上来的标签是什么。
    """
    return hashlib.sha256(str(statement_full or "").strip().encode("utf-8")).hexdigest()


def append_proposition_verdict(root: str | Path, *, statement_full: str,
                               verdict: str, canonical_name: str = "",
                               same_as: str = "", route: str = "",
                               label: str = "", condition: str = "",
                               conclusion: str = "", basis: str = "",
                               keywords: Sequence[str] = (), hits_total: int = 0,
                               hits_named: Sequence[Mapping[str, Any]] = (),
                               judged: bool = False, why: str = "",
                               keyword_checked: bool = False,
                               candidates_total: int = 0, pages_total: int = 0,
                               pages_judged: int = 0, candidates_seen: int = 0,
                               page_exhausted: bool = False,
                               seam_source: str = "",
                               role: str = "", task_id: str = "") -> dict[str, Any]:
    """追加一行判定读数（append-only；显式 LF，Windows 上不留 CRLF）。

    只记判成了的两档结论（same / different）：没判成（没缝 / 开关关着 / 超时 / 坏 JSON /
    词表外结论 / same 点不出号 / 关键词没提取成）不许缓存 —— 那会把"这一次没判成"变成
    "以后都别查了"，而缝是可能好起来的（与 `_statement_verdicts` 同一条纪律）。

    每行带 `statement_sha256`：读侧按它折叠出"这条正文最后一次判定是什么"，不必去猜行序。
    检索读数（`keywords` / `hits_total` / `hits_named` / `judged` / `why`）也落这一行：
    "沿用那一次判定"时，读的人同样看得到它当年查过什么（业主 2026-11-08：主动查询）。
    返回写下去的那一行（调用方拿它进返回值，不另拼一份）。
    """
    path = proposition_verdicts_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {"at": _now_iso(),
           "statement_sha256": _proposition_verdict_key(statement_full),
           "statement_chars": len(str(statement_full or "")),
           "verdict": str(verdict or ""),
           "canonical_name": str(canonical_name or ""),
           "same_as": str(same_as or ""),
           "route": str(route or ""),
           "label": str(label or ""),
           "condition": str(condition or ""),
           "conclusion": str(conclusion or ""),
           "basis": str(basis or ""),
           "keywords": [str(x) for x in (keywords or ())],
           "hits_total": int(hits_total or 0),
           "hits_named": [dict(x) if isinstance(x, Mapping) else {"stmt_id": str(x)}
                          for x in (hits_named or ())],
           "judged": bool(judged), "why": str(why or ""),
           #: 分页读数（2026-11-08 缺陷 ②）：看了几页 / 几个候选 / 是否页尽。
           "keyword_checked": bool(keyword_checked),
           "candidates_total": int(candidates_total or 0),
           "pages_total": int(pages_total or 0),
           "pages_judged": int(pages_judged or 0),
           "candidates_seen": int(candidates_seen or 0),
           "page_exhausted": bool(page_exhausted),
           "seam_source": str(seam_source or ""),
           "role": str(role or ""), "task_id": str(task_id or "")}
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        # `default=str` 与全仓同一口径（`tests/test_json_dumps_has_a_default.py`）。
        handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True, default=str) + "\n")
    return row


def proposition_verdict_of(root: str | Path, statement_full: str) -> dict[str, Any]:
    """这条正文在台账里最后一次判定的结论（没有 ⇒ 空字典）。

    三态：返回空字典 = "没有判定过"（不是"判过不同"）；返回带 `verdict` 的行 = 判过。
    两者在调用方那里处置完全不同（前者要发一次调用，后者不许再花钱），所以这里不折成
    一个默认值。
    """
    path = proposition_verdicts_path(root)
    key = _proposition_verdict_key(statement_full)
    if not path.is_file():
        return {}
    last: dict[str, Any] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, Mapping):
            continue
        if str(row.get("statement_sha256") or "") == key and str(row.get("verdict") or ""):
            last = dict(row)
    return last


def proposition_verdict_rows(root: str | Path) -> list[dict[str, Any]]:
    """命题同一性判定台账的全部行（读侧唯一口；没有文件 ⇒ 空列表）。

    为什么要有这一格（2026-11-08，①）：收工读数要数"这一趟判定到底发生过几次"，
    而"判定台账有几行"是唯一可靠的落盘读数。读法与 `proposition_form_rows` /
    `statement_same_rows` 逐字同形：空行跳过、坏 JSON 跳过（读不出来由调用方的三态
    读数报"没查成"，不许折成"0 次判定"）。
    """
    path = proposition_verdicts_path(root)
    if not path.is_file():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text:
            continue
        try:
            row = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(row, Mapping):
            out.append(dict(row))
    return out

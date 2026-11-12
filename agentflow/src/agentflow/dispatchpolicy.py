# -*- coding: utf-8 -*-
"""D 的派活文本里有没有点名它自己登记的猜想号 —— 机械判据。

## 业主口径

那条猜想只是参考意见：D 不能直接把自己的猜想登记到命题台账，也不能命令 E 或 F 必须
把它做出来，这只是研究方向参考。

⇒ 落地成一条可机械核的判据（不是词表判断、也不看语气）：

- 从 D 的派活记录里取文本（`sessions/*.jsonl` 的 `agent_step` 事件：`role="D"`、
  `shape="summon"` 的 `payload` —— 那是 D 真的交给 E/F 的那一段）；
- 若那段文本里出现 D 自己登记的某条 `conjecture_id`（`conj:NNNNNN` 或裸 6 位号，
  且那个号真的在 `conjectures` 台账里）⇒ 红，逐条点名「哪一次派活、点了哪条猜想」；
- 只写研究方向（不提号）⇒ 绿。

## 为什么不判 F 的 `attack_plans.problem`

F 可能自己想证 D 登记的某条猜想（那是 F 的自主选择，不是 D 的命令）。判 F 的计划文本
会把这种合法情形误伤成违规 —— 所以判据的输入是 D 派活的记录。`attack_plans` 只在
"它的问题文本能在某一段 D 派活文本里找到"（`normalize(plan.problem)` 是派活文本的子串，
或 `problem_key` 就是那一段的 `params` 里给的值）时才算"这一条计划是那句派活落成的"，
并在读数里同时点名计划号 —— 认不出归属的计划一律记进 `self_authored_plans`，不算违规。

## 三态

`checked=False` + `reason` = 会话记录读不出来（没查成 ≠ 没有违规）。读得到但没有
`summon` 派活 ⇒ `checked=True` 且 `dispatches=[]`（那是"这一趟没有 D 派活"，不是"绿"；
调用方要看 `dispatches` 才分得开）。
"""
from __future__ import annotations

import re
from typing import Any, Callable, Iterable, Mapping, Sequence

__all__ = [
    "CONJECTURE_PREFIX_RE",
    "conjecture_ids_of",
    "d_dispatch_records",
    "dispatch_text_problems",
]

#: `conj:` / `conj：` 前缀（模型在派活文本里常这么写；台账里的号本身是裸 6 位）。
CONJECTURE_PREFIX_RE = re.compile(r"conj\s*[:：]\s*(\d{6})", re.IGNORECASE)
#: 裸 6 位号（前后不能再是数字 —— 长串里的 6 位不算一个号）。
BARE_ID_RE = re.compile(r"(?<![\d])(\d{6})(?![\d])")

#: 判据射程：D 的研究侧直属只有 E / F（C 是结构读数面，不在这一条上）。
_RESEARCH_TARGETS: tuple[str, ...] = ("E", "F")


def conjecture_ids_of(rows: Iterable[Mapping[str, Any]]) -> set[str]:
    """`conjectures` 台账里的号集合（只认 6 位；形状不对的不进判据）。"""
    out: set[str] = set()
    for row in rows or ():
        if not isinstance(row, Mapping):
            continue
        cid = str(row.get("conjecture_id") or "").strip()
        if re.fullmatch(r"\d{6}", cid):
            out.add(cid)
    return out


def _strings_of(value: Any) -> list[str]:
    """把一段 payload 里的所有字符串摊平（判据只看"文本里有没有那个号"）。"""
    out: list[str] = []
    if isinstance(value, str):
        out.append(value)
    elif isinstance(value, Mapping):
        for key, item in value.items():
            out.extend(_strings_of(item))
    elif isinstance(value, (list, tuple)):
        for item in value:
            out.extend(_strings_of(item))
    return out


def d_dispatch_records(root: Any) -> dict:
    """D 的派活记录（唯一读口）⇒ `{checked, sessions, dispatches, reason}`。

    每一条 `dispatches` 是 `{sid, index, role, action, task, why, text, payload}`：
    `text` 是那一次 `summon` 载荷里全部字符串的拼接（判据的输入），`role` 是收件角色。
    """
    from . import sessions as _SS

    out: dict[str, Any] = {"checked": False, "sessions": 0, "dispatches": [],
                           "reason": "", "problems": []}
    try:
        events, problems = _SS.read_all_sessions(root)
    except Exception as exc:  # noqa: BLE001 —— 读不到要说出来，不许当成"没有派活"
        out["reason"] = f"会话记录读不出来（{type(exc).__name__}: {exc}）⇒ 这一格没查成"
        return out
    out["problems"] = [str(x) for x in ((problems or {}).get("unreadable_files") or [])]
    out["sessions"] = int((problems or {}).get("files") or 0)
    if isinstance(problems, Mapping) and not problems.get("checked", True):
        out["reason"] = (f"会话记录只读了一部分（{problems.get('reason') or '没有理由'}）"
                         "⇒ 这一格没查成")
        return out
    out["checked"] = True
    rows: list[dict[str, Any]] = []
    for event in events or ():
        if not isinstance(event, Mapping):
            continue
        if str(event.get("kind") or "") != "agent_step":
            continue
        if str(event.get("role") or "") != "D":
            continue
        shape = str(event.get("shape") or "")
        payload = event.get("payload") if isinstance(event.get("payload"), Mapping) else {}
        if shape != "summon" and not (
                isinstance(payload, Mapping) and "role" in payload and "task" in payload):
            continue
        target = str(payload.get("role") or "")
        texts = _strings_of(payload)
        rows.append({
            "sid": str(event.get("sid") or ""),
            "index": int(event.get("index") or 0),
            "role": target,
            "action": str(payload.get("action") or ""),
            "task": str(payload.get("task") or ""),
            "why": str(payload.get("why") or ""),
            "text": "\n".join(texts),
            "payload": dict(payload),
        })
    out["dispatches"] = rows
    if not rows:
        out["reason"] = ("会话记录里没有 D 的 `summon` 事件 ⇒ 这一趟没有可判的派活文本"
                         "（不是「绿」：绿要有一段真的派活、且其中没有猜想号）")
    return out


def _normalize(text: Any) -> str:
    return " ".join(str(text or "").split())


def _id_hits(text: str, ids: set[str]) -> list[dict[str, str]]:
    """这段文本点名了哪几个猜想号（只认台账里真有的号）⇒ `[{conjecture_id, token}]`。"""
    hits: dict[str, str] = {}
    if not ids:
        return []
    for match in CONJECTURE_PREFIX_RE.finditer(str(text or "")):
        cid = match.group(1)
        if cid in ids:
            hits.setdefault(cid, match.group(0))
    for match in BARE_ID_RE.finditer(str(text or "")):
        cid = match.group(1)
        if cid in ids:
            hits.setdefault(cid, cid)
    return [{"conjecture_id": cid, "token": hits[cid]} for cid in sorted(hits)]


def dispatch_text_problems(root: Any, *, conjectures: Sequence[Mapping[str, Any]] | None = None,
                           events: Sequence[Mapping[str, Any]] | None = None,
                           token_match: Callable[[str, set[str]], list[dict[str, str]]] | None = None
                           ) -> dict:
    """D 的派活文本点名了它自己的猜想号没有 ⇒ 判据读数（红 = `violations` 非空）。

    参数
    ----
    conjectures : `conjectures` 台账行（不给 ⇒ 从 `store.rows("conjectures")` 现读）。
    events : 已经读出来的会话事件（不给 ⇒ 走 `sessions.read_all_sessions`）。
    token_match : 判子（反真空用：把它换成恒返回 `[]` 的那一个 ⇒ 红必须变绿）。

    返回 `{checked, dispatches, violations, self_authored_plans, named_plans, conjectures,
    reason}`。`violations` 每条是
    `{kind: "dispatch"|"plan", conjecture_id, token, sid, index, role, task, plan_id, problem}`。
    """
    from .store import Store

    match = token_match or _id_hits
    out: dict[str, Any] = {"checked": False, "dispatches": 0, "violations": [],
                           "self_authored_plans": 0, "named_plans": [],
                           "conjectures": [], "reason": "", "events_error": ""}
    if conjectures is None:
        try:
            conjectures = [dict(r) for r in Store(str(root)).rows("conjectures")]
        except Exception as exc:  # noqa: BLE001 —— 读不到台账 ⇒ 没查成
            out["reason"] = (f"`conjectures` 台账读不出来（{type(exc).__name__}: {exc}）"
                             "⇒ 这一格没查成（不是「没有违规」）")
            return out
    ids = conjecture_ids_of(conjectures or ())
    out["conjectures"] = sorted(ids)
    if events is not None:
        try:
            from . import sessions as _SS

            reading = {"checked": True, "dispatches": []}
            for event in events:
                if not isinstance(event, Mapping):
                    continue
                if str(event.get("kind") or "") != "agent_step":
                    continue
                if str(event.get("role") or "") != "D":
                    continue
                payload = event.get("payload") if isinstance(event.get("payload"), Mapping) else {}
                if str(event.get("shape") or "") != "summon" and not (
                        "role" in payload and "task" in payload):
                    continue
                reading["dispatches"].append({
                    "sid": str(event.get("sid") or ""),
                    "index": int(event.get("index") or 0),
                    "role": str(payload.get("role") or ""),
                    "action": str(payload.get("action") or ""),
                    "task": str(payload.get("task") or ""),
                    "why": str(payload.get("why") or ""),
                    "text": "\n".join(_strings_of(payload)),
                    "payload": dict(payload),
                })
        except Exception as exc:  # noqa: BLE001
            out["reason"] = f"会话事件读不出来（{type(exc).__name__}: {exc}）⇒ 没查成"
            return out
    else:
        reading = d_dispatch_records(root)
        if not reading.get("checked"):
            out["reason"] = str(reading.get("reason") or "会话记录没查成")
            return out
    out["checked"] = True
    dispatches = [dict(x) for x in (reading.get("dispatches") or [])]
    out["dispatches"] = len(dispatches)
    # ---- ① D 的派活文本本身点名了猜想号 ----------------------------------------
    for one in dispatches:
        if str(one.get("role") or "") not in _RESEARCH_TARGETS:
            continue
        for hit in match(str(one.get("text") or ""), ids):
            out["violations"].append({
                "kind": "dispatch",
                "conjecture_id": str(hit.get("conjecture_id") or ""),
                "token": str(hit.get("token") or ""),
                "sid": str(one.get("sid") or ""),
                "index": int(one.get("index") or 0),
                "role": str(one.get("role") or ""),
                "task": str(one.get("task") or ""),
                "plan_id": "",
                "problem": "",
            })
    # ---- ② 归属到某一段 D 派活文本的 attack_plans（F 自主写的不算） -------------
    try:
        plans = [dict(r) for r in Store(str(root)).rows("attack_plans")]
    except Exception as exc:  # noqa: BLE001 —— 计划表读不到 ⇒ 这一半没查成
        out["reason"] = (f"`attack_plans` 读不出来（{type(exc).__name__}: {exc}）"
                         "⇒ 计划归属这一半没查成")
        plans = []
    for plan in plans:
        problem = _normalize(plan.get("problem"))
        key = _normalize(plan.get("problem_key"))
        attributed = None
        if problem:
            for one in dispatches:
                if str(one.get("role") or "") not in _RESEARCH_TARGETS:
                    continue
                text = _normalize(one.get("text"))
                if problem and problem in text:
                    attributed = one
                    break
        if attributed is None and key:
            for one in dispatches:
                if str(one.get("role") or "") not in _RESEARCH_TARGETS:
                    continue
                if key in {_normalize(v) for v in _strings_of(one.get("payload"))}:
                    attributed = one
                    break
        if attributed is None:
            out["self_authored_plans"] = int(out["self_authored_plans"]) + 1
            continue
        hits = match(problem, ids)
        if not hits:
            continue
        entry = {"plan_id": str(plan.get("plan_id") or ""), "problem": problem,
                 "problem_key": str(plan.get("problem_key") or ""),
                 "sid": str(attributed.get("sid") or ""),
                 "index": int(attributed.get("index") or 0),
                 "role": str(attributed.get("role") or "")}
        out["named_plans"].append(entry)
        for hit in hits:
            out["violations"].append({
                "kind": "plan",
                "conjecture_id": str(hit.get("conjecture_id") or ""),
                "token": str(hit.get("token") or ""),
                "sid": entry["sid"], "index": entry["index"], "role": entry["role"],
                "task": str(attributed.get("task") or ""),
                "plan_id": entry["plan_id"], "problem": problem,
            })
    if not out["violations"]:
        out["reason"] = ("D 的派活文本里没有点名任何一条它自己登记的猜想号"
                         "（方向由文本给，号不作为命令）")
    return out

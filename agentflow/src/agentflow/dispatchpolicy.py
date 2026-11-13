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
    "dispatch_directions",
    "dispatch_text_problems",
]

#: `conj:` / `conj：` 前缀（模型在派活文本里常这么写；台账里的号本身是裸 6 位）。
CONJECTURE_PREFIX_RE = re.compile(r"conj\s*[:：]\s*(\d{6})", re.IGNORECASE)
#: 裸 6 位号（前后不能再是数字 —— 长串里的 6 位不算一个号）。
BARE_ID_RE = re.compile(r"(?<![\d])(\d{6})(?![\d])")
#: 台账里的号就长得这样（`conjecture_ids_of` 用；与上面两条同一种号形）。
_SIX_DIGIT_RE = re.compile(r"\d{6}")

#: 判据射程：D 的研究侧直属只有 E / F（C 是结构读数面，不在这一条上）。
_RESEARCH_TARGETS: tuple[str, ...] = ("E", "F")


def conjecture_ids_of(rows: Iterable[Mapping[str, Any]]) -> set[str]:
    """`conjectures` 台账里的号集合（只认 6 位；形状不对的不进判据）。"""
    out: set[str] = set()
    for row in rows or ():
        if not isinstance(row, Mapping):
            continue
        cid = str(row.get("conjecture_id") or "").strip()
        if _SIX_DIGIT_RE.fullmatch(cid):
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


def _dispatch_rows(events: Iterable[Any]) -> list[dict[str, Any]]:
    """会话事件里 D 的派活事件 ⇒ 读数行（唯一一份形状）。

    `d_dispatch_records` 与 `dispatch_text_problems(events=…)` 两支读的是同一批事件、
    同一组过滤条件 ⇒ 行怎么长只能有一处说；各写一遍就是"同一件事两个实现"。
    """
    rows: list[dict[str, Any]] = []
    for event in events or ():
        if not isinstance(event, Mapping):
            continue
        if str(event.get("kind") or "") != "agent_step":
            continue
        if str(event.get("role") or "") != "D":
            continue
        payload = event.get("payload") if isinstance(event.get("payload"), Mapping) else {}
        if str(event.get("shape") or "") != "summon" and not (
                isinstance(payload, Mapping) and "role" in payload and "task" in payload):
            continue
        rows.append({
            "sid": str(event.get("sid") or ""),
            "index": int(event.get("index") or 0),
            "role": str(payload.get("role") or ""),
            "action": str(payload.get("action") or ""),
            "task": str(payload.get("task") or ""),
            "why": str(payload.get("why") or ""),
            "text": "\n".join(_strings_of(payload)),
            "payload": dict(payload),
        })
    return rows


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
    rows = _dispatch_rows(events or ())
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
    text = str(text or "")
    for match in CONJECTURE_PREFIX_RE.finditer(text):
        cid = match.group(1)
        if cid in ids:
            hits.setdefault(cid, match.group(0))
    for match in BARE_ID_RE.finditer(text):
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
            reading = {"checked": True, "dispatches": _dispatch_rows(events)}
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
    # 判据只射向 E / F：先筛一次、文本先归一一次 —— 下面两段都要按同一顺序看同一批行，
    # 每段各筛一遍、每计划每行各 `_normalize` 一遍只是白算（首次命中相同）。
    research = [one for one in dispatches
                if str(one.get("role") or "") in _RESEARCH_TARGETS]
    dispatch_texts = [(one, _normalize(one.get("text"))) for one in research]
    # ---- ① D 的派活文本本身点名了猜想号 ----------------------------------------
    for one in research:
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
            for one, text in dispatch_texts:
                if problem in text:
                    attributed = one
                    break
        if attributed is None and key:
            for one in research:
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


# ---------------------------------------------------------------- 派了几个 F、各自方向
#
# 业主 2026-11-13（R1）：「plan由F自己决定，所以D不可能做出按plan个数派F，于是D只能按
# 研究方向开多个F而非把一堆方向委托给一个F」。这一条只要读数：这一趟 D 派了几个 F、
# 各自的方向是什么 —— 一个字段都不新造，全从既有数据现算：
#
#   ① 名册（`out/roster/D.jsonl` 折叠后）：有几个 F、各自的 `brief` 与 `task_text`；
#   ② `tasks` 行（`role=F`、`called_by=D`）：派过几趟（对拍用）；
#   ③ D 派活原文（:func:`d_dispatch_records` 的 `agent_step` payload）：方向的正本。
#
# 为什么不从 `attack_plans.problem_key` 读方向：派了方向但还没立计划的 F 会漏掉
# （R1 的口径：D 按方向开 F，F 自己决定 plan）—— 那一格是 F 落成计划之后的产物，
# 不是派活的读数。


def _bigrams(text: Any) -> set[str]:
    """连续两字（去空白后）。只用来给"brief 与该方向是不是同一件事"一个机械读数。"""
    s = "".join(str(text or "").split())
    return {s[i:i + 2] for i in range(len(s) - 1)}


def _flat(text: Any) -> str:
    return " ".join(str(text or "").split())


def _d_roster(root: Any, owners: Sequence[str]) -> tuple[list[dict[str, Any]], list[str]]:
    """D 各趟的名册折叠后状态（读口；只读 root）。

    `owners` 是 D 自己的台账号（`tasks` 里 `role="D"` 的行）：名册按父分片
    （`out/roster/<父>.jsonl`），所以"D 派了几个 F"要把 D 每一趟的名册并起来。
    重复的名字不算两个 F（同一个名字 = 同一个实例）；不同父名册里的同名项是不同实例。
    判据要能打桩这一处（反真空：打桩成空 ⇒ 调用方必须报"没读成"）。
    """
    from . import secretary as SEC

    sec = SEC.Secretary("D", root=str(root))
    items: list[dict[str, Any]] = []
    bad: list[str] = []
    for owner in owners:
        got, bad_rows = sec.roster_rows(str(owner))
        for row in got:
            one = dict(row)
            one["owner"] = str(owner)
            items.append(one)
        bad += [str(x) for x in bad_rows]
    return items, bad


def dispatch_directions(root: Any, *, roster: Sequence[Mapping[str, Any]] | None = None,
                        tasks: Sequence[Mapping[str, Any]] | None = None,
                        dispatches: Sequence[Mapping[str, Any]] | None = None) -> dict:
    """D 派了几个 F、各自方向（唯一读数口；只从既有数据现算，不新造字段）。

    返回 `{checked, reason, count, fs, directions, unmatched, roster_f, tasks_f, problems}`：

    - `count`：名册上（未退役的）F 的个数 —— "派了几个 F"；
    - `fs`：每个 F 一项 `{name, owner, task_id, brief, brief_source, direction,
      direction_source, roster_task_text, dispatch_task, direction_agrees, brief_overlap}`；
      `direction` 的正本是D 派活那一刻写下的原文（③）；名册的 `task_text` 只是同一段
      原文的副本（它按 `TASK_TEXT_MAX` 截断），两处都有时 `direction_agrees` 给一个读数；
    - `directions`：非空的那些方向（逐条原文）；
    - `unmatched`：有派活原文、但对不上任何在册 F 的条数（不许静默丢）；
    - `checked`：这一格读成了没有。三态：名册有坏行 / `tasks` 里有 F 的派活行而名册里
      一个 F 都没有（两处对不上）/ 派活记录读不出来 ⇒ `False` + `reason` ——
      "没读成"绝不许读成"0 个 F"。

    `roster` / `tasks` / `dispatches` 三个形参是给判据打桩用的（反真空）；生产调用不给。
    """
    out: dict[str, Any] = {"checked": False, "reason": "", "count": 0, "fs": [],
                           "directions": [], "unmatched": 0, "roster_f": 0,
                           "tasks_f": 0, "problems": []}
    if tasks is None:
        try:
            from .store import Store

            task_rows = [dict(r) for r in Store(str(root)).rows("tasks")]
        except Exception as exc:  # noqa: BLE001
            out["reason"] = f"`tasks` 读不出来（{type(exc).__name__}: {exc}）⇒ 这一格没查成"
            return out
    else:
        task_rows = [dict(r) for r in tasks]
    owners = sorted({str(r.get("task_id") or "") for r in task_rows
                     if str(r.get("role") or "") == "D"
                     and str(r.get("task_id") or "")})
    if roster is None:
        try:
            items, bad = _d_roster(root, owners)
        except Exception as exc:  # noqa: BLE001 —— 读不成如实报（不是"0 个 F"）
            out["reason"] = (f"名册读不出来（{type(exc).__name__}: {exc}）"
                             "⇒ 这一格没查成（不是「0 个 F」）")
            return out
    else:
        items, bad = [dict(r) for r in roster], []
    if dispatches is None:
        reading = d_dispatch_records(root)
        if not reading.get("checked"):
            out["reason"] = str(reading.get("reason") or "D 的派活记录没查成")
            return out
        recs = [dict(x) for x in (reading.get("dispatches") or [])]
    else:
        recs = [dict(x) for x in dispatches]
    out["problems"] = [str(x) for x in bad]

    f_items = [r for r in items
               if str(r.get("role") or "") == "F" and not bool(r.get("retired"))]
    out["roster_f"] = len(f_items)
    f_tasks = [r for r in task_rows
               if str(r.get("role") or "") == "F"
               and str(r.get("called_by") or "") == "D"]
    out["tasks_f"] = len({str(r.get("task_id") or "") for r in f_tasks})
    # ---- 派活原文按 F 归位：先按点名（name / reuse），再按原文对得上 ----
    unmatched: list[str] = []
    for rec in recs:
        if str(rec.get("role") or "") != "F":
            continue
        text = _flat(rec.get("task"))
        if not text:
            continue
        payload = dict(rec.get("payload") or {}) if isinstance(rec.get("payload"), Mapping) else {}
        want = {str(payload.get("name") or ""), str(payload.get("reuse") or "")} - {""}
        hit = next((it for it in f_items
                    if want and str(it.get("name") or "") in want), None)
        if hit is None:
            hit = next((it for it in f_items
                        if _flat(it.get("task_text")) and
                        (text in _flat(it.get("task_text"))
                         or _flat(it.get("task_text")) in text)), None)
        if hit is None:
            unmatched.append(text)
            continue
        if not str(hit.get("dispatch_task") or ""):
            hit["dispatch_task"] = str(rec.get("task") or "")
            hit["dispatch_sid"] = str(rec.get("sid") or "")
    out["unmatched"] = len(unmatched)
    # ---- 每个 F 的方向与两处读数 ----
    for it in f_items:
        name = str(it.get("name") or "")
        roster_text = str(it.get("task_text") or "")
        dispatch_text = str(it.get("dispatch_task") or "")
        direction = dispatch_text or roster_text
        source = "dispatch" if dispatch_text else ("roster_task_text" if roster_text else "")
        both = bool(dispatch_text and roster_text)
        agrees: bool | None
        if both:
            a, b = _flat(dispatch_text), _flat(roster_text)
            # 名册那一段会被 `TASK_TEXT_MAX` 截断 ⇒ 只问"是不是同一段原文的开头"
            agrees = bool(a == b or b in a or a in b)
        else:
            agrees = None
        brief = str(it.get("brief") or "")
        g1, g2 = _bigrams(brief), _bigrams(direction)
        overlap = (round(len(g1 & g2) / len(g1), 3) if g1 and g2 else None)
        entry = {"name": name, "owner": str(it.get("owner") or ""),
                 "task_id": str(it.get("task_id") or ""),
                 "brief": brief, "brief_source": str(it.get("brief_source") or ""),
                 "direction": direction, "direction_source": source,
                 "roster_task_text": roster_text, "dispatch_task": dispatch_text,
                 "direction_agrees": agrees, "brief_overlap": overlap}
        out["fs"].append(entry)
        if direction:
            out["directions"].append(direction)
    out["count"] = len(f_items)
    # ---- 三态：两处对不上 / 名册有坏行 ⇒ 没读成 ----
    if bad:
        out["reason"] = (f"名册有 {len(bad)} 行读不出来 ⇒ 这一格没查成"
                         "（不是「0 个 F」）")
        return out
    if out["roster_f"] == 0 and out["tasks_f"] > 0:
        out["reason"] = ("`tasks` 里有 F 的派活行，而名册里一个（未退役的）F 都没有 "
                         f"（{out['tasks_f']} 趟）⇒ 两处对不上：这一格没查成，"
                         "不是「0 个 F」")
        return out
    out["checked"] = True
    if not f_items:
        out["reason"] = "这一趟 D 没派过 F（名册上一个 F 都没有，`tasks` 也没有 F 的行）"
    elif out["unmatched"]:
        out["reason"] = (f"派了 {out['count']} 个 F；另有 {out['unmatched']} 条派活原文"
                         "对不上任何在册 F（没丢，见 problems / 调用方读数）")
    else:
        out["reason"] = f"派了 {out['count']} 个 F，各自方向都读得到"
    return out


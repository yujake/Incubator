# -*- coding: utf-8 -*-
"""父子链的只读追踪：一层工具与全树工具共用的读侧（业主 2026-10-24 裁定）。

## 业主原话（唯一权威）

「普通代理能追一层，M能想追几层追几层。下层父代理若想监控地下最末端分支行为时可向M请求
 （一般提出的都是d2想看到d4甚至d5，毕竟再往下的层级派不了太深（深度锁：5级））」

## 三件事的落点（本模块只做读，不注册工具、不写盘）

1. 一层：`children_with_facts(...)` 给"我直接下级"的行为读数。非 M 角色的深度由
   `clamp_depth` 钉成 1（就算调用方传了 depth=3 也只给一层），并在返回值里带
   `deeper` 那一格，逐字写清"更深要看请向 M 请求"。
2. 全树：`watch_rows(...)` 沿 `parent_task_id` 向下走，给 M 想追几层追几层。
   它与 `Conductor.tree` 的父子谓词逐条一致（只数实例行 `kind == ""`，板项行
   `parent_task_id` 的口径是"收件人"，不是父代理）。测试会断言两份读数同集。
3. 请求路径：非 M 角色看更深的地方，用已有的上行工具 `conductor.escalate`
   （本模块只给那句可复制的调用文本，不新造一条边）。M 看完之后的指导由
   `conductor.guide` 沿树下发，那件工具在 `tools/conductor_tools.py` 里。

## 每个节点给什么（业主四格）

- 状态：`tasks` 行上的 status / outcome / refusal_reason / detail / tokens / usd；
- 最近 N 步在做什么：会话记录里的 `agent_step`（窗口口径见 `_steps_for_task`）；
- 被拒次数与类目：复用 `errorstats` 的主码规则与类目表（`primary_code` /
  `CODE_TO_CATEGORY`），不另写一份码表；
- 产出是否真落盘：`experiments` / `statements` / `documents` 里署名是本实例的
  行，以及任务行 `artifacts` 里那些引用在盘上/表里是否真的存在；
- 最近一次 handoff 摘要：`manuscripts/handoffs.jsonl` 里 `task_id` 对得上的最后一行。

## 三态（与全仓同一纪律）

读不到会话记录 / 读不到某张表 一律 `checked=False` 加原因，不折成"0 条"。
"这个节点没有子代理"是 `checked=True` + 空列表，与"没读成"分得开。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from . import errorstats as ES
from . import manuscripts as MAN
from . import schema as S

__all__ = [
    "DESCEND_LIMIT_FOR_NON_M",
    "clamp_depth",
    "children_of",
    "subtree_rows",
    "children_with_facts",
    "watch_rows",
    "node_facts",
    "artifact_readings",
]

#: 非 M 角色一次能看下去的层数。业主口径：「普通代理能追一层，M能想追几层追几层」。
#: 这个数字只在这里定义一次：`trace.children` 与 `conductor.watch` 都从
#: `clamp_depth` / `subtree_rows` 取，不在两处各写一个字面量。
DESCEND_LIMIT_FOR_NON_M = 1

#: 产出落表的三张表（`表名 -> 主键字段`）。业主点名的是这三张。
PRODUCT_TABLES: tuple[tuple[str, str], ...] = (
    ("experiments", "experiment_id"),
    ("statements", "stmt_id"),
    ("documents", "doc_id"),
)

#: 最近 N 步的默认窗口。与 `conductor.watch` 的 `window` 缺省值同源。
DEFAULT_WINDOW = 5


def _role_of(row: Mapping[str, Any]) -> str:
    return str(row.get("role") or "")


def _task_id_of(row: Mapping[str, Any]) -> str:
    return str(row.get("task_id") or "")


def clamp_depth(role: str, depth: Any = None) -> int:
    """这一趟实际能看到几层。

    非 M 角色一律 `DESCEND_LIMIT_FOR_NON_M`；M 按调用方给的层数，不给（None）
    表示"不限"（`subtree_rows` 用一个大数接住）。为什么把 M 的"不限"集中在这里：
    业主的要求是"M能想追几层追几层"，而"几层"不写死，等于把上界交给台账的
    实际深度（不额外造一个会过期的数字）。

    为什么单独成一个函数（而不是在工具里写 `min(depth, 1)`）：反真空判据
    `test_05_disabling_the_clamp_makes_the_one_layer_rule_fail` 把本函数打桩成
    "不限"，于是"只给一层"这条判据必然变红。受限逻辑若散在 handler 里，那条
    判据就只能去改 handler 的源码，测的就不是这条规则本身了。
    """
    requested = 1 if depth is None else max(1, int(depth))
    if str(role or "") == S.CONDUCTOR_ROLE:
        return requested
    return min(requested, DESCEND_LIMIT_FOR_NON_M)


def children_of(rows: Iterable[Mapping[str, Any]], parent_task_id: str) -> list[dict[str, Any]]:
    """`parent_task_id` 名下直接子代理的行（只数实例行）。

    与 `Conductor._children_of` 同一条谓词（`kind == ""` 才算代理；板项行的
    `parent_task_id` 口径是"收件人的编号"）。本模块不持有 `Conductor`，而工具层
    在测试与脚本里会拿到"只有 store"的装配，所以这一条谓词必须在这里有一份可用的
    实现；两份是否一致由判据钉住（`test_12_the_two_child_predicates_agree`），
    而不是靠人记得两边一起改。
    """
    want = str(parent_task_id or "")
    out = [
        dict(r) for r in rows
        if str(r.get("parent_task_id") or "") == want and not str(r.get("kind") or "")
    ]
    return sorted(out, key=lambda r: str(r.get("task_id") or ""))


def subtree_rows(
    rows: Iterable[Mapping[str, Any]], root_task_id: str, *, depth: Any = None
) -> list[dict[str, Any]]:
    """从 `root_task_id` 自己开始向下走，返回带 `level` 的扁平行。

    `depth` 的口径是"含根的那几层"：`depth=1` 只有根，`depth=2` 是根加直接下级。
    `depth=None` 表示不额外截断（走到台账里没有下一行为止）。返回顺序是
    先根、再逐层按 task_id 升序，于是两个独立调用在同一份台账上给出同一份顺序。

    这里刻意不复用 `Conductor.tree` 的返回值：那一份的 `level` 从根算 0，但它的
    `children` 只给编号、不给行，且它一次把整棵树都吐出来，没法在这里按调用方
    要的层数截断。父子谓词仍与它逐条一致（见 `children_of` 的注释）。
    """
    everything = [dict(r) for r in rows]
    by_id = {_task_id_of(r): r for r in everything}
    root = by_id.get(str(root_task_id or ""))
    if root is None:
        # 台账里没有这个号 ⇒ 这棵树本来就不存在（不是"台账读不出来"，那一档在别处报）。
        # 空列表是准数，不是把"没查成"折叠成"没有结果"。
        return []
    limit = None if depth is None else max(1, int(depth))
    out: list[dict[str, Any]] = []

    def walk(row: dict[str, Any], level: int) -> None:
        if limit is not None and level >= limit:
            return
        out.append({**row, "level": level})
        for kid in children_of(everything, _task_id_of(row)):
            walk(kid, level + 1)

    walk(root, 0)
    return out


# ---------------------------------------------------------------- 会话记录（最近 N 步）


def _session_records(root: str | Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """读会话记录。直接复用 `errorstats` 的读盘器：被拒读数的三态口径在那里。

    为什么调私有的 `_read_sessions`：它是"读不到"与"这个工作区没有 sessions
    目录"这两种情况的唯一判法（前者 checked=False，后者 checked=True + 0 条）。
    在本模块再写一份，两份对"空目录算不算读成"迟早会分叉，而被拒分节的读数
    正是靠这一格决定要不要显示。
    """
    return ES._read_sessions(Path(str(root or ".")))


def _steps_for_task(
    records: Sequence[Mapping[str, Any]], task_id: str, role: str
) -> dict[str, Any]:
    """某个台账号那一趟的 `agent_step` 序列。

    窗口口径与 `agent_loop.resume_messages` 同一条：起点是最后一条
    `agent_run_start`（`task_id` 对得上、`role` 也对得上），终点是同角色的
    下一条 `agent_run_start`（任何任务）。`agent_step` 记录里没有任务号，
    窗口是唯一能把两趟分开的东西（本文件不发明第二种归属方式）。

    找不到起点不是错误：老工作区 / 这一趟还没跑过，如实返回 `found=False`。
    """
    wanted = str(task_id or "")
    role_name = str(role or "")
    starts = [
        i for i, e in enumerate(records)
        if str(e.get("kind") or "") == "agent_run_start"
        and str(e.get("task_id") or "") == wanted
        and (not role_name or str(e.get("role") or "") == role_name)
    ]
    if not starts:
        return {"checked": True, "found": False, "count": 0, "steps": [],
                "reason": f"会话记录里没有台账号 {wanted} 的起趟事件（不是『它一步都没做』）"}
    begin = starts[-1]
    end = next(
        (i for i in range(begin + 1, len(records))
         if str(records[i].get("kind") or "") == "agent_run_start"
         and (not role_name or str(records[i].get("role") or "") == role_name)),
        len(records),
    )
    steps = [e for e in records[begin + 1: end] if str(e.get("kind") or "") == "agent_step"]
    return {"checked": True, "found": True, "count": len(steps),
            "steps": [_step_line(e) for e in steps], "reason": ""}


def _step_line(event: Mapping[str, Any]) -> dict[str, Any]:
    """一步的读数（给人/模型看的一句话 + 结构化的 ok/被拒原话）。"""
    payload = event.get("payload")
    payload = dict(payload) if isinstance(payload, Mapping) else {}
    result = event.get("result")
    result = dict(result) if isinstance(result, Mapping) else {}
    shape = str(event.get("shape") or "")
    did = (
        payload.get("tool") or payload.get("target_role") or payload.get("to")
        or payload.get("subject") or payload.get("final") or payload.get("text") or ""
    )
    if isinstance(did, Mapping):
        did = did.get("summary") or ""
    line = f"第 {event.get('index')} 步（{shape}）：{str(did)[:160]}" if shape else \
        f"第 {event.get('index')} 步：{str(did)[:160]}"
    ok = result.get("ok")
    error = str(result.get("error") or result.get("problem") or "")
    if ok is False or error:
        line += f" ⇒ 被拒/失败：{error or '（没有原话）'}"[:220]
    return {
        "step": event.get("index"),
        "shape": shape,
        "what": str(did)[:200],
        "ok": ok if isinstance(ok, bool) else None,
        "error": error[:200],
        "line": line[:400],
    }


# ---------------------------------------------------------------- 被拒次数与类目


def _refusals(records: Sequence[Mapping[str, Any]], steps: Mapping[str, Any],
              row: Mapping[str, Any]) -> dict[str, Any]:
    """被拒次数与类目：复用 `errorstats` 的主码规则（一条记录只算一次）。

    两个来源都算（业主说的是"被拒次数"这件事，不是一个文件里的次数）：
    - 这一趟的 `agent_step` 里的拒信原话（工具层 / 收工门 / 判据层）；
    - 台账里这个台账号自己那一行 `outcome="refused"`（召唤期就拒了的那些）。

    类目只在码表里取（`CODE_TO_CATEGORY`）；码读不出来时记进 `unclassified`，
    不猜一个类目出来（与 `errorstats` 模块 docstring 第 2 条同一口径）。
    """
    by_category: dict[str, int] = {}
    samples: list[dict[str, str]] = []
    unclassified = 0

    def _bump(found: tuple[str, str] | None, text: str) -> None:
        nonlocal unclassified
        if found is None:
            unclassified += 1
            return
        code, cat = found
        by_category[cat] = by_category.get(cat, 0) + 1
        category = ES.CODE_TO_CATEGORY.get(code, cat)
        samples.append({"code": code, "category": category, "text": str(text)[:200]})

    for item in steps.get("steps") or []:
        text = f"{item.get('error') or ''} {item.get('line') or ''}"
        found = ES.primary_code(text)
        if found is not None:
            _bump(found, item.get("error") or item.get("line") or "")
    if str(row.get("outcome") or "") == "refused":
        _bump(ES.primary_code(row.get("refusal_reason"), row.get("error"), row.get("detail")),
              row.get("refusal_reason") or row.get("detail") or "")
    total = sum(by_category.values()) + unclassified
    return {"count": total, "by_category": by_category, "samples": samples,
            "unclassified": unclassified,
            "checked": bool(steps.get("checked", True))}


# ---------------------------------------------------------------- 产出是否真落盘


def _signs_row(row: Mapping[str, Any], *, task_id: str, role: str,
               started_at: str, ended_at: str) -> bool:
    """这一行算不算本实例署名的产出。

    三种署名形态（都要求"对得上"，不做模糊匹配）：
    - `created_by` 就是台账号（最强的一种，写者明确署了实例号）；
    - `created_by` 是 `role` 或 `agent-<role>` / `secretary-<role>` 这种带角色后缀
      的名字，且 `created_at` 落在这一趟的时间窗里（老写者只署角色）；
    - 时间窗读不出来时不看时间（只认角色署名）—— 这是"看不准"的那一档，
      由 `time_window_checked` 在返回值里如实标出，不冒充精确。
    """
    who = str(row.get("created_by") or "")
    if not who:
        return False
    if task_id and who == task_id:
        return True
    if not role:
        return False
    tagged = who == role or who.endswith(f"-{role}") or who.endswith(f":{role}")
    if not tagged:
        return False
    created = str(row.get("created_at") or "")
    if not created or not started_at:
        return True
    upper = ended_at or "9999"
    return started_at <= created <= upper


def _products(store: Any, row: Mapping[str, Any]) -> dict[str, Any]:
    """三张表里本实例署名的行 + 任务行 `artifacts` 的落地核验。"""
    task_id = _task_id_of(row)
    role = _role_of(row)
    started_at = str(row.get("started_at") or "")
    ended_at = str(row.get("ended_at") or "")
    tables: dict[str, Any] = {}
    total = 0
    checked_all = True
    for table, id_field in PRODUCT_TABLES:
        reading: dict[str, Any] = {"checked": False, "count": 0, "ids": [],
                                   "reason": ""}
        try:
            rows = store.rows(table) if store is not None else []
        except Exception as exc:  # noqa: BLE001 - 读不到是 unknown，不是 0 行
            reading["reason"] = f"读不出来（{type(exc).__name__}: {exc}）"
            checked_all = False
            tables[table] = reading
            continue
        hits = [
            str(r.get(id_field) or "") for r in rows
            if _signs_row(r, task_id=task_id, role=role, started_at=started_at,
                          ended_at=ended_at)
        ]
        reading.update(checked=True, count=len(hits), ids=sorted(h for h in hits if h))
        total += len(hits)
        tables[table] = reading
    return {
        "checked": checked_all,
        "count": total,
        "tables": tables,
        "artifacts": artifact_readings(store, row),
        "time_window_checked": bool(started_at),
    }


def artifact_readings(store: Any, row: Mapping[str, Any]) -> dict[str, Any]:
    """任务行 `artifacts` 里那些引用在盘上/表里是否真的存在（"真落盘"那一半）。

    两种引用形态都认：台账主键（如 `stmt:` 前缀或纯编号）与工作区相对路径。
    读不成与不存在分开：`checked=False` 是"没查成"，`exists=False` 是"查过了没有"。
    """
    refs = [str(a) for a in (row.get("artifacts") or []) if str(a)]
    readings: list[dict[str, Any]] = []
    root = Path(str(getattr(store, "root", "") or "")) if store is not None else None
    ids: dict[str, set[str]] = {}
    if store is not None:
        for table, id_field in PRODUCT_TABLES:
            try:
                ids[table] = {str(r.get(id_field) or "") for r in store.rows(table)}
            except Exception:  # noqa: BLE001 - 读不成的那张表不参与主键核验
                ids[table] = set()
    for ref in refs:
        reading: dict[str, Any] = {"ref": ref, "kind": "", "exists": False,
                                   "checked": True}
        bare = ref.split(":", 1)[-1]
        hit = next((t for t, members in ids.items() if ref in members or bare in members), "")
        if hit:
            reading.update(kind=f"row:{hit}", exists=True)
        elif root is not None:
            path = Path(ref)
            reading.update(kind="file", exists=(root / path).exists())
        else:
            reading.update(kind="reference", checked=False)
        readings.append(reading)
    return {"refs": readings,
            "exists": sum(1 for r in readings if r.get("exists")),
            "missing": [r["ref"] for r in readings if r.get("checked") and not r.get("exists")],
            "unchecked": [r["ref"] for r in readings if not r.get("checked")]}


# ---------------------------------------------------------------- 最近一次 handoff


def _last_handoff(handoffs: Sequence[Mapping[str, Any]], row: Mapping[str, Any]) -> dict[str, Any]:
    """`manuscripts/handoffs.jsonl` 里 `task_id` 对得上的最后一行（摘要）。

    没有手稿是 `checked=True` + `found=False`（"它没交过手稿"）；目录/文件读不成
    由调用方给 `checked=False`（`handoffs=None`），这里不猜。
    """
    task_id = _task_id_of(row)
    mine = [dict(h) for h in handoffs if str(h.get("task_id") or "") == task_id]
    if not mine:
        return {"checked": True, "found": False, "summary": "", "to": "", "id": "",
                "created_at": "", "reason": "台账里没有这一趟署名的交接手稿"}
    mine.sort(key=lambda h: str(h.get("created_at") or ""))
    last = mine[-1]
    return {
        "checked": True, "found": True,
        "id": str(last.get("id") or ""),
        "summary": str(last.get("summary") or "")[:400],
        "to": str(last.get("to") or ""),
        "sender": str(last.get("sender") or ""),
        "created_at": str(last.get("created_at") or ""),
        "body_head": str(last.get("body") or "")[:400],
    }


# ---------------------------------------------------------------- 拼一个节点的全部读数


def node_facts(
    store: Any,
    root: str | Path,
    row: Mapping[str, Any],
    *,
    window: int = DEFAULT_WINDOW,
    records: Sequence[Mapping[str, Any]] | None = None,
    session_reading: Mapping[str, Any] | None = None,
    handoffs: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """一个任务的完整读数（状态 / 最近 N 步 / 被拒 / 产出 / 上一次 handoff）。

    `records` / `handoffs` 可以由调用方预先读一次传进来：一次 `trace.children`
    要对多个子任务算同一批读数，逐个重读会话文件是 O(n^2) 的无谓开销。
    """
    if records is None:
        records, session_reading = _session_records(root)
    session_reading = dict(session_reading or {})
    steps_all = _steps_for_task(records, _task_id_of(row), _role_of(row))
    all_steps = list(steps_all.get("steps") or [])
    window_n = max(1, int(window or DEFAULT_WINDOW))
    recent = all_steps[-window_n:]
    steps_view = {**steps_all, "window": window_n, "shown": recent}
    steps_view.pop("steps", None)
    if not session_reading:
        session_reading = {"checked": bool(steps_all.get("checked")), "reason": ""}
    steps_view["session"] = session_reading
    if handoffs is None:
        try:
            handoffs = MAN.rows(root)
        except Exception as exc:  # noqa: BLE001 - 读不成手稿不是"没交过"
            handoffs = []
            handoff_broken = f"交接手稿读不成（{type(exc).__name__}: {exc}）"
        else:
            handoff_broken = ""
    else:
        handoff_broken = ""
    handoff = _last_handoff(handoffs, row)
    if handoff_broken:
        handoff = {"checked": False, "found": False, "reason": handoff_broken}
    return {
        "task_id": _task_id_of(row),
        "role": _role_of(row),
        "action": str(row.get("action") or ""),
        "kind": str(row.get("kind") or ""),
        "status": str(row.get("status") or ""),
        "outcome": row.get("outcome"),
        "refusal_reason": row.get("refusal_reason"),
        "depth": row.get("depth"),
        "instance": str(row.get("instance") or ""),
        "called_by": str(row.get("called_by") or ""),
        "parent_task_id": row.get("parent_task_id"),
        "detail": str(row.get("detail") or "")[:400],
        "tokens": row.get("tokens"),
        "usd": row.get("usd"),
        "started_at": str(row.get("started_at") or ""),
        "ended_at": row.get("ended_at"),
        "recent_steps": steps_view,
        "refusals": _refusals(records, {"steps": all_steps,
                                        "checked": steps_all.get("checked", True)}, row),
        "products": _products(store, row),
        "last_handoff": handoff,
    }


# ---------------------------------------------------------------- 两个工具入口


def _request_text(task_id: str, depth: Any) -> dict[str, str]:
    """非 M 角色要更深时的那段"怎么请求"（逐字可复制，不新造一条边）。

    只给文本、不替调用方发请求：上行是一件"这一趟要收工"的动作
    （`conductor.escalate` 成功即 `stop_reason=escalated`），替它发等于替它做决定。
    """
    requested = 1 if depth is None else max(1, int(depth))
    return {
        "tool": "conductor.escalate",
        "call": ('conductor.escalate(need="深看请求：请 M 用 conductor.watch '
                 f'看 {task_id or "我这一支"} 的第 2 层以下分支", kind="other")'),
        "who": "M",
        "note": (
            f"你只能向下看 {DESCEND_LIMIT_FOR_NON_M} 层（追子代理的层数，"
            f"与召唤链的深度锁不是同一个数）；"
            f"你传的 depth={requested} 已被按 {DESCEND_LIMIT_FOR_NON_M} 处理。"
            "要看更深的分支请向 M 请求：用已有的上行工具 conductor.escalate"
            "（它把请求写进召唤者的收件箱并沿链上行到 M，不新造一条边）；"
            "M 用 conductor.watch 看全树（每行都带 chain / chain_text：从顶趟到这个节点的"
            "绝对编号链），再用 conductor.guide 把指导意见沿秘书链逐级传到那一个代理手上"
            "（`to` 直接贴那一行的 chain 即可；中间各级代理本人看不到内容）。"
        ),
    }


def _chain_cells(rows: Sequence[Mapping[str, Any]], task_id: str) -> dict[str, Any]:
    """这个节点的绝对编号链两格（业主 2026-10-26：轮查读数必须反馈绝对编码链）。

    口径在 `conductor.absolute_chain` 一处（从顶趟那一行沿 `parent_task_id` 追到
    这个节点）。为什么每一行都要给：只给"父是谁"的话，调用方还得自己一层层拼 ——
    拼错一个号，消息就发到另一支去了；而链是拿去做链式寻址的（`conductor.guide`
    的 `to` 原样能贴）。
    """
    from .conductor import CHAIN_SEPARATOR, absolute_chain

    got = absolute_chain(rows, task_id)
    return {"chain": got, "chain_text": CHAIN_SEPARATOR.join(got)}


def children_with_facts(
    store: Any,
    root: str | Path,
    task_row: Mapping[str, Any],
    *,
    depth: Any = None,
    window: int = DEFAULT_WINDOW,
) -> dict[str, Any]:
    """`trace.children` 的读侧：我的直接下级（非 M 角色永远只有一层）。"""
    rows = store.rows("tasks") if store is not None else []
    me = _task_id_of(task_row)
    role = _role_of(task_row)
    granted = clamp_depth(role, depth)
    records, session_reading = _session_records(root)
    try:
        handoffs = MAN.rows(root)
    except Exception:  # noqa: BLE001 - 读不成时每个节点各自如实标 unknown
        handoffs = []
    nodes = subtree_rows(rows, me, depth=granted + 1) if me else []
    children = [r for r in nodes if int(r.get("level") or 0) > 0]
    facts = [
        {**node_facts(store, root, r, window=window, records=records,
                      session_reading=session_reading, handoffs=handoffs),
         "level": int(r.get("level") or 0),
         **_chain_cells(rows, _task_id_of(r))}
        for r in children
    ]
    return {
        "checked": True,
        "me": {"task_id": me, "role": role,
               "parent_task_id": task_row.get("parent_task_id")},
        "depth_requested": 1 if depth is None else max(1, int(depth)),
        "depth_granted": granted,
        "one_layer_only": granted == DESCEND_LIMIT_FOR_NON_M,
        "children": facts,
        "count": len(facts),
        "deeper": _request_text(me, depth),
        "session": session_reading,
    }


def watch_rows(
    store: Any,
    root: str | Path,
    *,
    task_row: Mapping[str, Any],
    depth: Any = None,
    window: int = DEFAULT_WINDOW,
) -> dict[str, Any]:
    """`conductor.watch` 的读侧：从这一行向下整棵子树（M 专用，层数不限）。"""
    rows = store.rows("tasks") if store is not None else []
    root_id = _task_id_of(task_row)
    nodes = subtree_rows(rows, root_id, depth=depth)
    records, session_reading = _session_records(root)
    try:
        handoffs = MAN.rows(root)
    except Exception:  # noqa: BLE001 - 读不成时每个节点各自如实标 unknown
        handoffs = []
    facts = [
        {**node_facts(store, root, r, window=window, records=records,
                      session_reading=session_reading, handoffs=handoffs),
         "level": int(r.get("level") or 0),
         **_chain_cells(rows, _task_id_of(r))}
        for r in nodes
    ]
    max_level = max((f["level"] for f in facts), default=0)
    return {
        "checked": True,
        "root_task_id": root_id,
        "depth_requested": None if depth is None else max(1, int(depth)),
        "depth_reached": (max_level + 1) if facts else 0,
        "window": max(1, int(window or DEFAULT_WINDOW)),
        "rows": facts,
        "count": len(facts),
        "truncated": (depth is not None and any(
            children_of(rows, f["task_id"]) for f in facts
            if f["level"] == max(0, int(depth) - 1))),
        "session": session_reading,
    }

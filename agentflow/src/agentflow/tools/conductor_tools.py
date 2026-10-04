"""主控工具：给主控 M 配手与眼。

## 为什么需要这个模块（实测的洞）

`registry.for_role("M") == []` —— 主控此前一件工具都没有：
它作为确定性执行者能被 `Conductor` 调用，却没有"派活"这个动作可用。
于是一句"评审这篇论文并给我更好的论文包"要落地，只能靠调用方在代码里替它把
`plan` 拼出来 —— 那不是主 Agent，那是"人在派活"。

## 这里刻意不做什么（所有者两次点名要防的形态）

不写计划 JSON schema、不写 prompt 模板库、不写 plan 解析器、不写重计划状态机。
判断在 M（主 Agent）那里；本模块只提供两件事：
能不能做（闸门在 `Conductor` 内部：`ALLOWED_EDGES` / `CAPABILITIES` /
参数接缝 / `policy` 四上限 / 预算）与做了什么（`tasks` 台账）。

## 工具面（一个模块一个组前缀：`conductor.`）

| 工具 | 侧效 | 作用 |
|---|---|---|
| `conductor.summon` | write_local | 唯一的派活动作（过全部闸门） |
| `conductor.ledger` | read | 看台账：派了什么、被拒什么、剩多少 |
| `conductor.stop` | write_local | 优雅停止：不再新开任务 → 等在飞收尾 → 合成终态（无僵尸）→ 落续跑简报 |
| `conductor.resume_brief` | read | 读续跑简报（做了什么 / 剩什么 / 从哪继续） |
| `conductor.cancel` | write_local | 硬取消（不等收尾，协作式） |
| `conductor.ensure_project` | write_local | 冷启动 / 热启动由 M 决定（四态如实给） |
| `conductor.state` | read | 只读状态视图（给 M 判断用） |
| `conductor.role_spec` | read | 某角色的动作与工具面（派给谁、怎么写 brief） |
| `conductor.summon_many` | write_local | 批量派活（分波与峰值在返回里；同角色多实例） |
| `conductor.acceptance` | read | 读项目的验收表（哪几行成立、读数原文可引用） |
| `conductor.closing` | read | 跑收工门五条（三态读数；`can_close` 只在五条全过时为真） |

## 为什么 M 的写面变了不等于"主控开始产出知识"

写侧工具改的是编排状态（台账行、取消信号、工作区目录、停止回执），
`CAPABILITIES["M"] = ()`（零动作）与 `WRITE_SETS["M"] = {}`（不写领域表）
一个字都没动 —— 领域表仍然只有 A–H 能写。
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import replace
from functools import partial
from pathlib import Path
from typing import Any, Callable, Mapping

from .. import policy as P
from .. import schema as S
from ..cancellation import CANCEL_CODES
from ..conductor import Conductor, NotWiredError, SummonResult
from . import ToolError, ToolRegistry, ToolResult, fail, ok, tool

#: 一个工作区一个主控（键 = store 根路径）。主控是会话状态：
#: 预算、台账、取消信号必须跨多次工具调用连续，否则每次派活都是一个新主控。
_CONDUCTORS: dict[str, Conductor] = {}


def conductor_for(store: Any, *, policy: Any = None,
                  role_registry: Any = None, backend: Any = "local") -> Conductor:
    """取（或建）这个工作区的主控实例。同一个 `store.root` 永远拿到同一个实例。"""
    root = str(Path(getattr(store, "root", ".")).resolve())
    if root not in _CONDUCTORS:
        _CONDUCTORS[root] = Conductor(store, policy=policy, registry=role_registry,
                                      backend=backend)
    return _CONDUCTORS[root]


def reset_cache() -> None:
    """清掉主控缓存（只给测试用：换一个工作区就换一个主控）。"""
    _CONDUCTORS.clear()


def _summon_dict(res: SummonResult) -> dict:
    """把一次召唤的结果收成工具返回值（键与 `returns=` 声明逐字对应）。"""
    return {"task_id": res.task_id, "role": res.role, "action": res.action,
            "status": res.status, "outcome": res.outcome,
            "refusal_reason": res.refusal_reason, "detail": res.detail,
            "error": res.error, "tokens": res.tokens, "usd": res.usd,
            "depth": res.depth, "elapsed_sec": res.elapsed_sec,
            "children": list(res.children or ()), "checked": res.checked}


def _write_resume_brief(conductor: Conductor) -> dict:
    """落一份续跑简报，并返回它。

    这叫"续跑简报"而不是"计划"：它只记已经发生的事实（做到哪、剩什么、
    下一步从哪接），不替 M 决定下一步做什么。
    它是"优雅停止"与 kill 的唯一区别 —— 没有它，下一次热启动只能靠猜。

    落点是工作区根下的文件（与产物同族），不是领域表：
    `WRITE_SETS["M"] = {}` 管的是 store 的表，这条约束没有被动过。
    """
    rows = conductor.tree()
    counts: dict[str, int] = {}
    for r in rows:
        key = str(r.get("outcome") or r.get("status") or "?")
        counts[key] = counts.get(key, 0) + 1
    pending = [r.get("task_id") for r in rows
               if str(r.get("status")) in ("pending", "running")]
    brief = {
        "written_at": S.now_iso(),
        "tasks_total": len(rows),
        "outcome_counts": counts,
        "not_finished": pending,
        "verify_issues": conductor.verify_tasks(),
        "last_tasks": [{"task_id": r.get("task_id"), "role": r.get("role"),
                        "action": r.get("action"), "status": r.get("status"),
                        "outcome": r.get("outcome"),
                        "refusal_reason": r.get("refusal_reason")} for r in rows[-8:]],
        "how_to_continue": ("工作区已在手边时，直接 conductor.resume_brief / conductor.ledger"
                            "（view=\"stats\"）接着做，不要另建项目；要从默认 projects 目录进，"
                            "才用 conductor.ensure_project(start=\"auto\") 热启动。"
                            "本简报是事实记录，不代替判断。"),
    }
    try:
        root = Path(getattr(conductor.store, "root", "."))
        (root / "resume-brief.json").write_text(
            json.dumps(brief, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
        brief["path"] = str(root / "resume-brief.json")
    except OSError as exc:  # 简报写不进去必须如实说，不许当"停好了"
        brief["path"] = ""
        brief["write_error"] = f"{type(exc).__name__}: {exc}"
    return brief


def _relay_requests(conductor: Conductor) -> tuple[list[dict[str, Any]], str]:
    """把会话记录里的 `agent_summon_request` 整理成"受理了没有"的表。

    判据（刻意保守、可复算）：一条申请算已受理，当且仅当台账里存在一条
    `role == wants_role` 且 `action == wants_action` 的任务行，其 `started_at`
    不早于该申请的时刻。为什么用"之后有没有出现这个动作"而不是"M 明确说受理了"：
    后者是一个自然语言承诺，而前者是台账上的事实；两者不一致时该相信台账。

    返回 `(行, 没查成的原因)`：读不到 sessions 目录时返回空表 + 原因，
    调用方据此报 `relay_pending=None`（没查成 ≠ 没有申请）。
    """
    from .. import sessions as SS

    root = Path(getattr(getattr(conductor, "store", None), "root", "."))
    sess_dir = root / "sessions"
    if not sess_dir.is_dir():
        return [], f"没有会话目录 {sess_dir} ⇒ 读不到代唤申请（没查成，不是没有申请）"
    rows = [dict(r) for r in conductor.store.rows("tasks")]
    out: list[dict[str, Any]] = []
    try:
        files = sorted(sess_dir.glob("*.jsonl"))
    except OSError as exc:
        return [], f"列会话文件失败：{type(exc).__name__}: {exc}"
    for path in files:
        events, problems = SS.read_session(root, sid=path.stem)
        if problems:
            return [], f"读会话 {path.name} 失败：{problems[:1]}"
        for e in events:
            if e.get("kind") != "agent_summon_request":
                continue
            at = str(e.get("ts") or "")
            want_role = str(e.get("wants_role") or "")
            want_action = str(e.get("wants_action") or "")
            hit = next((r for r in rows
                        if str(r.get("role")) == want_role
                        and str(r.get("action")) == want_action
                        and str(r.get("started_at") or "") >= at), None) if at else None
            out.append({
                "role": str(e.get("role") or ""),
                "wants_role": want_role,
                "wants_action": want_action,
                "refusal_reason": str(e.get("refusal_reason") or ""),
                "at": at,
                "fulfilled": hit is not None,
                "fulfilled_by_task": str(hit.get("task_id") or "") if hit else "",
            })
    return out, ""


@tool(
    "conductor.summon",
    "派活：召唤某个角色做某个动作。闸门在主控内部（允许的边 / 动作表 / 参数接缝 /"
    "四类上限 / 预算），被拒也落台账并返回 refusal_reason。",
    {
        "type": "object",
        "properties": {
            "target_role": {"type": "string", "description": "被召唤的角色（A–H）"},
            "action": {"type": "string", "description": "该角色登记过的动作名"},
            "params": {"type": "object", "description": "动作参数（按参数的 schema 校验）"},
            "input_key": {"type": "string", "description": "同一祖先链上去重用的键（防活锁）"},
        },
        "required": ["target_role", "action"],
        "additionalProperties": False,
    },
    side_effect="write_local",
    roles=("M",),
    returns=("{'task_id','role','action','status','outcome','refusal_reason','detail',"
             "'error','tokens','usd','depth','elapsed_sec','children','checked'}"),
)
def conductor_summon(_conductor, target_role: str, action: str, params: dict | None = None,
                     input_key: str = "") -> ToolResult:
    """工具体：一次派活。闸门全在 `Conductor.summon` 内部；被拒也落台账。"""
    # 形参刻意不叫 `role`：`ToolRegistry.call(..., role=...)` 的 `role` 是
    # 调用方角色（`P-14` 的调用期权限判据，`None` 一律拒）。撞名会让模型传的
    # `role` 被读成"调用者是谁" —— 既拿不到目标角色，又会改变权限判据的输入。
    # 同理不许叫 `name` / `args` / `budget` / `spill_root`（都是 `call` 自己的形参）。
    #
    # 召唤方身份用 `S.CONDUCTOR_ROLE`（"M"）而不是自造的 "agent-M"：
    # 它是一个受控词表（`schema.ROLES` ∪ {M}），自造值会被 `Conductor` 拒为
    # `unknown_role` —— 实测撞过（fail-closed 生效，没有静默放行）。
    #
    # `input_key` 是循环检测的键（同一 `(role, action, input_key)` 出现在祖先链上
    # 才算循环）：不给会被 `verify_tasks` 报 `task_without_input_key`。
    res = _conductor().summon(target_role, action, params or {}, by=S.CONDUCTOR_ROLE,
                              input_key=input_key)
    data = _summon_dict(res)
    return ok(data, **data)

@tool(
    "conductor.summon_many",
    "一次派**一批**活，真的并发：按写集分波（`policy.waves_of`），同波用线程池跑"
    "（上限 `max_concurrency`）。"
    "同一角色要开多个实例时，给每个 target 一个不同的 `instance` 标签 —— "
    "**同角色不同实例允许同波并发**（例：一批文献分给 3 个 B 同时读）；"
    "没给标签时：同一角色在一批里出现多次会自动补 `<角色>#N`（返回里标 "
    "`auto_instance=true`），只出现一次则与从前一样串行。"
    "返回里带 `waves` 与 `concurrent_peak`："
    "'到底并发了没有'看这两个数，不要看墙钟。",
    {
        "type": "object",
        "properties": {
            "targets": {
                "type": "array",
                "minItems": 1,
                "maxItems": 8,
                "description": "一批派活（每项一条）",
                "items": {
                    "type": "object",
                    "properties": {
                        "target_role": {"type": "string", "description": "被召唤的角色（A–H）"},
                        "action": {"type": "string", "description": "该角色登记过的动作名"},
                        "params": {"type": "object", "description": "动作参数"},
                        "instance": {"type": "string",
                                     "description": "实例标签；同角色不同标签 ⇒ 允许同波并发"},
                        "input_key": {"type": "string", "description": "去重/防活锁的键"},
                    },
                    "required": ["target_role", "action"],
                    "additionalProperties": False,
                },
            },
            "why": {"type": "string", "description": "这批活是为什么派的（写进日志，便于复盘）"},
        },
        "required": ["targets"],
        "additionalProperties": False,
    },
    side_effect="write_local",
    roles=("M",),
    returns=("{'count','ok_count','refused_count','failed_count','waves','max_wave',"
             "'concurrent_peak','elapsed_sec','why','results'}；results[] 每项是 "
             "{'role','action','instance','auto_instance','task_id','status','outcome',"
             "'refusal_reason','detail','error','tokens','usd','elapsed_sec','checked',"
             "'children'}"),
)
def conductor_summon_many(_conductor, targets: list, why: str = "") -> ToolResult:
    """工具体：一次派一批活，走 `Conductor.run_plan`（分波 + 线程池 + 探针）。

    为什么要有它（2026-09-30）：`run_plan` / `run_waves` 这套并发引擎早就存在
    （分波按写集、同波线程池、`ConcurrencyProbe` 能证明区间重叠），但生产路径
    上零调用 —— 主控只能一次派一个，于是"并发开 3 个 B 读一批文献"在工具面上
    根本表达不出来。这个工具就是那条路。

    三态纪律：每一项都必须有自己的结局（`status`/`outcome`/`refusal_reason`），
    列表长度恒等于输入长度 —— "第 3 个被拒了"不许表达成"只有 2 个任务"。
    """
    from .. import scheduler as SC

    c = _conductor()
    # ---- 实例标签的自动补齐（2026-09-30，加在"用户要一批 B 同时干活"这条路上）
    #
    # 为什么要有它：并发多实例要求"同一角色的每个 target 给不同 `instance`"
    # （`policy._same_role_other_instance`），而模型在写一批 target 时经常不写
    # 那个标签 —— 于是三个 B 会被排成三波串行，而它看起来"派了三份活、都成功了"。
    # 那种失败不会报错，只是慢，正是最容易被读成"没问题"的形态。
    # 所以这里做一件确定性的事：同一个角色在一次批量里出现多次、且没给标签时，
    # 自动补上序号（`<role>#1`…），并在返回里逐项标 `auto_instance=True`。
    # 给了标签的一律尊重（那是调用方在明确指定"谁干哪一份"）。
    seen: dict[str, int] = {}
    for item in (targets or []):
        if isinstance(item, Mapping) and not str(item.get("instance") or ""):
            seen[str(item.get("target_role") or "")] = seen.get(
                str(item.get("target_role") or ""), 0) + 1
    auto: dict[str, list[str]] = {
        role: [f"{role}#{k}" for k in range(1, n + 1)] for role, n in seen.items() if n > 1
    }
    used: dict[str, int] = {}
    calls = []
    for i, item in enumerate(targets or []):
        if not isinstance(item, Mapping):
            raise ToolError(f"targets[{i}] 必须是对象（收到 {type(item).__name__}）")
        target_role = str(item.get("target_role") or "")
        action = str(item.get("action") or "")
        if not target_role or not action:
            raise ToolError(f"targets[{i}] 缺 target_role 或 action")
        instance = str(item.get("instance") or "")
        if not instance and target_role in auto:
            used[target_role] = used.get(target_role, 0) + 1
            instance = auto[target_role][used[target_role] - 1]
        calls.append(SC.TaskCall(
            role=target_role, action=action,
            params=dict(item.get("params") or {}),
            by=S.CONDUCTOR_ROLE,
            input_key=str(item.get("input_key") or ""),
            instance=instance,
        ))
    t0 = time.monotonic()
    results = c.run_plan(calls)
    elapsed = time.monotonic() - t0
    probe = getattr(c, "_last_probe", None)
    waves = [len(w) for w in P.waves_of(calls, limit=c.policy.max_concurrency)]
    items = [{**_summon_dict(r), "instance": str(getattr(call, "instance", "") or ""),
              "auto_instance": bool(
                  str(getattr(call, "instance", "") or "").startswith(
                      f"{call.role}#") and not str(
                          (targets[i] or {}).get("instance") or ""))}
             for i, (r, call) in enumerate(zip(results, calls))]
    payload = {
        "count": len(items),
        "ok_count": sum(1 for r in results if getattr(r, "ok", False)),
        "refused_count": sum(1 for r in results
                             if str(getattr(r, "outcome", "")) == "refused"),
        "failed_count": sum(1 for r in results
                            if str(getattr(r, "status", "")) == "failed"),
        "waves": waves,
        "max_wave": max(waves) if waves else 0,
        "concurrent_peak": int(getattr(probe, "peak", 0) or 0),
        "elapsed_sec": round(elapsed, 3),
        # `why` 恒在（没给就是空串）：声明了却"有时不给"会让读它的人
        # 把"这一次没给"读成"这个键不存在"（`returns=` 是契约，不是提示）。
        "why": str(why or ""),
        "results": items,
    }
    # 键表写在这里（字面量）而不是 `ok(payload, **payload)`：本模块的工具体
    # 历史上都是"看不清的调用点"那一档，静态扫描读不出键；这一件刻意写成
    # 看得见的形态，于是"声明了哪些键"可以直接对着这段代码核。
    # （`test_tools_branch_key_sets` 的 `INVISIBLE_OK_SITES` 里
    # `conductor_tools.py` 的处数因此 +1，已同步改表。）
    return ok(payload, **payload)

@tool(
    "conductor.ledger",
    "看台账：tree（每行的层级与结局）/ stats（总数与分类计数）/ issues（结构问题）/ "
    "verify（不变式检查）/ relays（同伴发来的「请代唤」申请：哪些还没受理）。"
    "给主控判断'下一步'用的事实，不含任何建议。",
    {
        "type": "object",
        "properties": {
            "view": {"type": "string",
                     "enum": ["tree", "stats", "issues", "verify", "relays"]},
            "root_task_id": {"type": "string", "description": "只看这一棵子树（可空）"},
        },
        "required": [],
        "additionalProperties": False,
    },
    side_effect="read",
    roles=("M",),
    returns=("{'view','rows','stats','issues','verify','relays','relay_pending','relay_note',"
             "'task_count'}；relays[] 每项含 role / wants_role / wants_action / "
             "refusal_reason / at / fulfilled / fulfilled_by_task（逐项键名见 "
             "`_relay_requests` 的字面量）"),
)
def conductor_ledger(_conductor, view: str = "tree", root_task_id: str = "") -> ToolResult:
    """工具体：把台账的视图读出来（只读，不写任何字节）。

    `view="relays"` 是 2026-09-30 加的（`draft/28` §199）：同伴够不到某个边时，
    框架会自动给主控发一条 `subject=请代唤` 的留言并落一条 `agent_summon_request`
    事件（`agent_loop._request_relay`）。留言是给人看的，这个视图是给主控看的 ——
    它把那些申请整理成一张可判定的表：每条申请后面有没有出现"要的那个
    (角色, 动作)"的任务行 ⇒ `fulfilled` / 待受理。三态纪律：查不到会话记录时
    `relay_pending` 报 `None`（没查成），不报 0（"没有申请"）。
    """
    c = _conductor()
    payload: dict[str, Any] = {"view": view, "rows": [], "stats": {}, "issues": [],
                               "verify": [], "relays": [], "relay_pending": None,
                               "relay_note": "", "task_count": 0}
    if view == "tree":
        payload["rows"] = c.tree(root_task_id or None)
    elif view == "stats":
        payload["stats"] = c.stats()
    elif view == "issues":
        payload["issues"] = [i.to_dict() if hasattr(i, "to_dict") else dict(i)
                             for i in c.task_issues()]
    elif view == "verify":
        payload["verify"] = c.verify_tasks()
    else:
        relays, why = _relay_requests(c)
        payload["relays"] = relays
        payload["relay_pending"] = (None if why else
                                    sum(1 for r in relays if not r["fulfilled"]))
        if why:
            payload["relay_note"] = why
    payload["task_count"] = len(c.tree())
    return ok(payload, **payload)

@tool(
    "conductor.stop",
    "优雅停止：不再接受新召唤 → 等在飞任务收尾（有界）→ 给剩下的合成终态"
    "（不留僵尸、结果记未知、不自动重试）→ 落一份续跑简报。幂等：第二次不改第一次的理由。",
    {
        "type": "object",
        "properties": {
            "reason": {"type": "string", "enum": list(CANCEL_CODES)},
            "drain_sec": {"type": "number", "description": "等收尾的上限秒数"},
        },
        "required": [],
        "additionalProperties": False,
    },
    side_effect="write_local",
    roles=("M",),
    returns=("{'reason','reason_mapped_from','detail','inflight_at_stop','drained_sec',"
             "'disposed','resume_brief','verify'}"),
)
def conductor_stop(_conductor, reason: str = "user", drain_sec: float = 30.0) -> ToolResult:
    """工具体：优雅停止（喊停 → 有界收尾 → 合成终态 → 落续跑简报）。"""
    c = _conductor()
    mapped_from = ""
    code = reason if reason in CANCEL_CODES else "user"
    if code != reason:
        mapped_from = reason
    receipt = c.cancel(code, detail="优雅停止（主控 M）", by=S.CONDUCTOR_ROLE)
    # 回报首次生效的那个原因（FC-20 第 2 条：终态先到先得、reason 只许一个答案）。
    # 本次请求的 code 可能不是它 —— 那就把两个都写出来，别让"我请求了 budget"
    # 被读成"停止原因是 budget"。
    effective = str(getattr(c.token.reason, "code", "") or code)
    if effective != code and not mapped_from:
        mapped_from = code
    code = effective
    t0 = time.monotonic()
    while c.cancel_inflight() and (time.monotonic() - t0) < float(drain_sec):
        time.sleep(0.05)
    waited = round(time.monotonic() - t0, 3)
    disposed = c.dispose()
    brief = _write_resume_brief(c)
    data = {"reason": code, "reason_mapped_from": mapped_from,
            "detail": receipt.get("detail", ""),
            "inflight_at_stop": list(receipt.get("inflight") or ()),
            "drained_sec": waited, "disposed": disposed,
            "resume_brief": brief, "verify": c.verify_tasks()}
    return ok(data, **data)

@tool(
    "conductor.resume_brief",
    "读上一次优雅停止留下的续跑简报（做了什么 / 剩什么 / 从哪继续）。"
    "没有简报时如实说'还没有停止过'；未终态行会逐条报出（不隐藏、不自动续跑）。",
    {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
    side_effect="read",
    roles=("M",),
    returns="{'present','brief','unfinished_now','path'}",
)
def conductor_resume_brief(_conductor, ) -> ToolResult:
    """工具体：读续跑简报；没有就如实说没有（不编一份空的）。"""
    c = _conductor()
    root = Path(getattr(c.store, "root", "."))
    path = root / "resume-brief.json"
    brief = None
    if path.is_file():
        try:
            brief = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            brief = {"unreadable": f"{type(exc).__name__}: {exc}"}
    data = {"present": brief is not None, "brief": brief or {},
            "unfinished_now": c.cancel_inflight(), "path": str(path)}
    return ok(data, **data)

@tool(
    "conductor.cancel",
    "硬取消（协作式）：立刻置共享停止信号，不等在飞收尾；在飞任务自己收终态。"
    "与 conductor.stop 的区别是 stop 先尝试收尾。",
    {
        "type": "object",
        "properties": {"reason": {"type": "string", "enum": list(CANCEL_CODES)},
                       "detail": {"type": "string"}},
        "required": [],
        "additionalProperties": False,
    },
    side_effect="write_local",
    roles=("M",),
    returns="{'reason','reason_mapped_from','detail','inflight'}",
)
def conductor_cancel(_conductor, reason: str = "user", detail: str = "") -> ToolResult:
    """工具体：硬取消（不等收尾；与 `conductor.stop` 的区别写在那里）。"""
    c = _conductor()
    mapped_from = ""
    code = reason if reason in CANCEL_CODES else "user"
    if code != reason:
        mapped_from = reason
    out = c.cancel(code, detail=detail or "取消（主控 M）", by=S.CONDUCTOR_ROLE)
    data = {"reason": out.get("reason", code), "reason_mapped_from": mapped_from,
            "detail": out.get("detail", ""), "inflight": list(out.get("inflight") or ())}
    return ok(data, **data)

@tool(
    "conductor.ensure_project",
    "冷启动 / 热启动由你决定：给 start=auto|cold|warm，返回四态"
    "（absent/empty/workspace/not_a_project）与最终 mode。cold 才建目录，"
    "warm 必须已存在且是工作区 —— 绝不替你删、也绝不替你把别人的目录当工作区。"
    "⚠️ 你已经在某个工作区里、又没有显式给 projects_dir 时，这一件会被拒"
    "（kind=already_a_project）：待在项目里不要另建项目。",
    {
        "type": "object",
        "properties": {
            "project_name": {"type": "string", "description": "项目名（缺省取下一个 projectN）"},
            "start": {"type": "string", "enum": ["auto", "cold", "warm"]},
            "books_dir": {"type": "string", "description": "本地书架目录（登记进项目库）"},
            "books_limit": {"type": "integer", "minimum": 0},
            "projects_dir": {"type": "string",
                             "description": "projects 落点（缺省取 AGENTFLOW_PROJECTS_DIR 或默认值）"},
        },
        "required": [],
        "additionalProperties": False,
    },
    side_effect="write_local",
    roles=("M",),
    returns="{'name','path','mode','requested','state','why','created','ingested'}",
)
def conductor_ensure_project(store, project_name: str = "", start: str = "auto",
                             books_dir: str = "", books_limit: int | None = None,
                             projects_dir: str = "") -> ToolResult:
    """工具体：冷/热启动由主控决定，四态如实返回（不替它猜）。

    ## 为什么"已经在项目里"要直接拒（2026-10-02 真机读数逼出来的守卫）

    `projects_dir` 的缺省不是当前工作区，而是 `projects.projects_dir(None)`
    —— 一个与工作区无关的默认落点（本机实测 `D:\\Incubator\\projects`）。
    于是"在一个已存在的工作区里调它"会得到一个在别处新建的空项目，
    而不是"热启动当前项目"：

    - 真机实测（`draft/37` §37）：那一趟 23 步里有 4 步在 `ensure_project`，
      其中一次真的建出了 `D:\\Incubator\\projects\\project11`
      （`project.json` 的 `created_at` = 2026-10-02T20:39:47+08:00，
      与那次运行同秒级）—— 而当时的账本上没有任何一步显示"我建了个项目"。
    - 同一天，本仓库自己的普查探针（`temp/_p40_m_tool_smoke.py`）在没给
      `projects_dir` 时也建了 `project12` / `project13` 两个空项目 ——
      写探针的人也会踩，说明这不是"M 的纪律问题"，是缺省值的问题。

    守卫的边界刻意很窄：只拒"当前工作区自己就是一个初始化过的项目、
    而调用方又没显式说项目落在哪"。显式给 `projects_dir`（或设
    `AGENTFLOW_PROJECTS_DIR`）时照旧工作 —— 那是操作者在说"我知道落在哪"。
    不这么定就会误伤既有判据：`tests/test_conductor_tools.py` 里那两条
    冷/热启动用例正是"在一个工作区里、把项目建到另一个显式指定的目录"。
    """
    from .. import projects as P

    explicit = bool(projects_dir.strip()) or bool(os.environ.get(P.ENV_PROJECTS_DIR, "").strip())
    inside = store is not None and P.classify(Path(store.root))[0] == "workspace"
    if inside and not explicit:
        default_root = P.projects_dir(None)
        return fail(
            "你已经在项目" + f" {Path(store.root).name} 里（{store.root}）⇒ 不要另建项目。"
            "接着做下去用 conductor.resume_brief / conductor.state / conductor.ledger，"
            "要派活就用 conductor.summon。真要另建一个项目，请显式给 projects_dir"
            f"（缺省落点是 {default_root}，不是你当前的工作区）；"
            "这一件拒绝时没有建任何目录。",
            kind="already_a_project", root=str(store.root), default_projects_dir=str(default_root),
        )

    root = Path(projects_dir) if projects_dir else P.projects_dir(None)
    ref = P.resolve(root, project_name or None, start=start)
    state, why = P.classify(ref.path)
    created = False
    ingested: dict[str, Any] = {}
    if ref.mode == "cold":
        P.create_project(ref, now=None)
        created = True
        state, why = P.classify(ref.path)
    if books_dir:
        from ..locallib import ingest_directory
        from ..store import Store

        store_ = Store(ref.path)
        store_.init()
        rep = ingest_directory(store_, books_dir, limit=books_limit,
                               note=f"{ref.name} 登记本地藏书（主控 M）")
        ingested = rep.to_dict()
    data = {"name": ref.name, "path": str(ref.path), "mode": ref.mode,
            "requested": ref.requested, "state": state, "why": why,
            "created": created, "ingested": ingested}
    return ok(data, **data)

@tool(
    "conductor.state",
    "只读状态视图：各表计数 + 猜想按状态计数（有这张表时）+ 台账规模。"
    "给主控判断用的眼睛，不带任何建议。",
    {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
    side_effect="read",
    roles=("M",),
    returns="{'root','tables','conjectures','tasks'}",
)
def conductor_state(_conductor, ) -> ToolResult:
    """工具体：只读状态视图（给主控判断用，不含建议）。"""
    c = _conductor()
    store_ = c.store
    tables: dict[str, int] = {}
    for name in S.TABLES:
        try:
            tables[name] = len(store_.rows(name))
        except Exception:  # 表读不了就如实缺一格，不编 0
            tables[name] = -1
    conjectures: dict[str, int] = {}
    if "conjectures" in S.TABLES:
        for row in store_.rows("conjectures"):
            key = str(row.get("status") or "?")
            conjectures[key] = conjectures.get(key, 0) + 1
    data = {"root": str(getattr(store_, "root", "")), "tables": tables,
            "conjectures": conjectures, "tasks": len(c.tree())}
    return ok(data, **data)

@tool(
    "conductor.role_spec",
    "某角色的规格：允许的动作与各自的参数名、以及它今天有哪些工具。"
    "派活前用它确认'这个角色能不能做这件事'；与 capabilities 同源，不另写一份。",
    {
        "type": "object",
        "properties": {"role_name": {"type": "string", "description": "角色名（A–H）"}},
        "required": ["role_name"],
        "additionalProperties": False,
    },
    side_effect="read",
    roles=("M",),
    returns="{'role','actions','tools','summonable'}",
)
def conductor_role_spec(store, role_name: str) -> ToolResult:
    """工具体：某角色的动作与工具面（与 `capabilities` 同源）。"""
    from .. import capabilities as C

    actions = [{"action": s.action, "params": list(getattr(s, "params", ()) or ()),
                "why": getattr(s, "why", "")} for s in C.actions_for(role_name)]
    tools_now: list[str] = []
    try:
        from . import build_registry

        tools_now = sorted(s.name for s in build_registry(store=store).registry.for_role(role_name))
    except Exception:  # 工具面读不到就说读不到，不编空表
        tools_now = []
    data = {"role": role_name, "actions": actions, "tools": tools_now,
            "summonable": role_name in C.ALLOWED_EDGES.get(S.CONDUCTOR_ROLE, frozenset()),
            # `draft/37` §108（用户口径"先加强描述"）：这一格此前只给"它有哪些动作"，
            # 而派活错的形态恰恰是"不知道它交付什么、不许做什么"。声明层
            # （`agentspec.AgentBrief`）里现成，现算给出去 —— 一份来源，不另抄。
            **{k: v for k, v in (_brief_of(role_name) or {}).items()
                if k in _ROLE_SPEC_BRIEF_KEYS}}
    return ok(data, **data)


#: `conductor.role_spec` 里转述声明层的那几格（`duty`/`deliverable` 是字符串，
#: `boundary`/`policy`/`stance` 是字符串列表，`signature_error` 一句话）。
_ROLE_SPEC_BRIEF_KEYS: tuple[str, ...] = ("duty", "deliverable", "boundary", "policy",
                                          "stance", "signature_error")


def _brief_of(role: str) -> dict[str, Any] | None:
    """从声明层读一个角色的 brief；读不到返回 `None`（不是空 dict）。

    为什么返回 `None` 而不是 `{}`：这几格是附加读数，读不到时调用方一格都不并——
    空 dict 会把"我们没记录"说成"它没有边界"（三态纪律：没查 ≠ 没有）；
    `None` 语义上没有冒充任何值，调用方也必须显式处理（`or {}`）。
    """
    try:
        from .. import agentspec as AS

        spec = AS.builtin_registry().get(role)
        brief = getattr(spec, "brief", None)
    except Exception:  # noqa: BLE001
        # 声明层读不到 ⇒ 这几个键是附加读数（有就多给几格），缺席不等于"这个角色没有边界"：
        # `role_spec` 的主读数（actions / tools / summonable）照旧由另一条路给出，
        # 而"这个角色存不存在"由那条路承担（不在就 actions 空、summonable=False）。
        return {}
    if brief is None:
        # 理由（R002）：声明层里没有这个角色的 brief ⇒ 附加读数缺席，返回 None；
        # 缺的是「我们没记录」，不是「它没有」（三态纪律：没查 ≠ 没有）。
        return None
    return {"duty": str(brief.duty), "deliverable": str(brief.deliverable),
            "boundary": [str(x) for x in brief.boundary],
            "policy": [str(x) for x in brief.policy],
            "stance": [str(x) for x in brief.stance],
            "signature_error": str(brief.signature_error)}

@tool(
    "conductor.acceptance",
    "只读：读某个项目的验收表（默认 out/paper/ACCEPTANCE.md），逐行解析出 P1–P11 的"
    "判据名 / 结论 / 读数。交付说明必须逐条与它对齐 —— 没有这张表就只能靠猜。",
    {
        "type": "object",
        "properties": {
            "project_dir": {"type": "string",
                            "description": "项目根（相对工作区；`.` 或空 = 工作区自己就是项目根）"},
            "rel_path": {"type": "string",
                         "description": "验收表相对项目根的路径（缺省 out/paper/ACCEPTANCE.md）"},
            "max_chars": {"type": "integer", "minimum": 0, "maximum": 4000,
                          "description": "每行读数最多留多少字（缺省 60；0 = 不截断）"},
            "ids": {"type": "array", "items": {"type": "string"},
                    "description": "只要这几行（如 ['P5','P6']）；一次读不完时按批读"},
        },
        "required": [],
        "additionalProperties": False,
    },
    side_effect="read",
    roles=("M",),
    returns=("{'found','path','title','conclusion','rows','row_count','ok_count','not_ok_count',"
             "'readings_truncated','row_ids','problems'}；"
             "rows[] 每项是 {'id','name','ok','reading','reading_chars'}；"
             "给了 ids 时多 {'requested','unknown_ids'}"),
)
def conductor_acceptance(store, project_dir: str = "", rel_path: str = "",
                         max_chars: int = 60, ids: list | None = None) -> ToolResult:
    """工具体：把验收表读成结构化的十行（读不到就如实说读不到，不给空表）。

    `ids` 是给"一次读不完"准备的：真机实测（2026-09-29）十行的完整读数会被
    上下文预算剪枝，而主控手里没有读文件工具（它的面只有 `conductor.*`）⇒
    被剪掉的部分读不回来。按批读是"不靠猜"的做法（而不是让 M 猜 P5–P11 写了什么）。

    ## 路径解析（`draft/37` §88：这一处是三个落点里被漏掉的那一个）

    `conductor.acceptance(project_dir=".")` 原先按进程 cwd 解析 ——
    而工具描述逐字写的是"相对工作区"。T1 第 2 趟真机（2026-10-04）：主控传
    `{"project_dir": "."}`，工具去读 `D:\\Incubator\\agentflow\\out\\paper\\ACCEPTANCE.md`
    （进程 cwd 所在的仓库目录），连报两次"验收表不在盘上"，而那张表就在工作区里
    —— 主控因此始终没看到 P1–P11 判据，后面每一跳都靠猜。

    同一件事 `closing.resolve_under_workspace` 的 docstring 里已经记过一次
    （`draft/37` §60：`closing` 与 `reviewaccept` 都改成了那一个解析口），
    本工具是那批里的第三个落点却漏改了 ⇒ 现在共用同一个解析口，不另写一份。
    """
    raw_project = str(project_dir or "").strip()
    if store is not None:
        # 局部 import：与 `conductor_closing` 同一写法（`closing` 这一支只在真调用时才需要）
        from .. import closing as CL

        base = Path(CL.resolve_under_workspace(store, raw_project or "."))
    else:
        base = Path(raw_project or ".")
    rel = rel_path or "out/paper/ACCEPTANCE.md"
    path = (base / rel).resolve()
    if not path.is_file():
        return fail(
            f"验收表不在盘上：{path} ⇒ 没查成（不是「没有判据」）。"
            f"基准＝{base}（相对工作区的路径按工作区根解析）；"
            "先让项目跑一次验收脚本，或把 rel_path 指对。",
            kind="no_acceptance_table", path=str(path), base=str(base), found=False,
        )
    got = _parse_acceptance(path, max_chars=max_chars)
    # 验收表背后的 documents 行（`draft/28` §196 第 2 条）：真机实测 —— M 拿验收表标题里的
    # `draft/31` 当 doc_id 去派 H 审校，H 回"draft/31 不在 documents 表"，于是
    # "核验证明"这条链在第一跳就断了。表和行都在库里，工具就该一起给出来，
    # 而不是让主控从一个标题里猜一个号。
    if store is not None:
        try:
            rows = store.rows("documents")
        except Exception as exc:  # noqa: BLE001 —— 读不到就如实说，不编一个空清单
            got["documents"] = []
            got["problems"] = list(got["problems"]) + [
                f"读不到 documents 表：{type(exc).__name__}: {exc} ⇒ 猜不出该审哪一行"]
        else:
            got["documents"] = [{"doc_id": str(r.get("doc_id") or ""),
                                 "kind": str(r.get("kind") or ""),
                                 "title": str(r.get("title") or ""),
                                 "status": str(r.get("status") or ""),
                                 "claims": len(r.get("claims") or [])} for r in rows]
    else:
        got["documents"] = []
        got["problems"] = list(got["problems"]) + [
            "没有 store ⇒ 说不出验收表背后的 documents 行是哪一条（没查成，不是「没有」）"]
    if ids:
        want = [str(x) for x in ids]
        keep = [r for r in got["rows"] if r["id"] in want]
        missing = [x for x in want if x not in {r["id"] for r in got["rows"]}]
        got["rows"] = keep
        got["row_count"] = len(keep)
        got["ok_count"] = sum(1 for r in keep if r["ok"])
        got["not_ok_count"] = len(keep) - got["ok_count"]
        got["requested"] = want
        got["unknown_ids"] = missing
        if missing:
            got["problems"] = list(got["problems"]) + [f"这些行不在验收表里：{missing}"]
    else:
        # 没给 `ids` 时这两栏也必须在：`returns=` 声明了它们，而"声明了却没给"
        # 是一条会被机械核的判据（实测撞过）。空列表的语义是"没有指定 / 没有未知"，
        # 与"没有这一栏"是两件事。
        got["requested"] = []
        got["unknown_ids"] = []
    # 成功支写成字面量键表：让"返回了哪些键"静态可见（与论文包四件同一条纪律）。
    return ok({
        "found": got["found"], "path": got["path"], "title": got["title"],
        "conclusion": got["conclusion"], "rows": got["rows"],
        "row_count": got["row_count"], "ok_count": got["ok_count"],
        "not_ok_count": got["not_ok_count"],
        "readings_truncated": got["readings_truncated"], "row_ids": got["row_ids"],
        "problems": got["problems"], "requested": got["requested"],
        "unknown_ids": got["unknown_ids"],
        # 验收表背后的 documents 行（§196 第 2 条）：主控据此派审校，不必从标题猜号。
        "documents": got.get("documents") or [],
    })


@tool(
    "conductor.closing",
    "只读：跑收工门（`draft/37` §16 P3 的七格）—— 锚 consistent / 无未裁决矛盾 / "
    "承重结论有 T3 或已降档 / 报告九节齐全 / 没有还在等用户回答的问题 / "
    "**实质产出**（`documents`/`relations`/`experiments`/`review_findings`/`statements` "
    "至少一张非空）/ **验收表的机器可判行**（项目里若有一份 `out/paper/ACCEPTANCE-CHECKS.json`，"
    "逐行从台账现算：任务点名的每一条腿都要有落台账的凭据）。"
    "每条各自一个三态读数，unknown 不是通过；`can_close` 只在七格全过时为真。",
    {
        "type": "object",
        "properties": {
            "project_dir": {"type": "string",
                            "description": "项目根（相对工作区；渲染锚在 <它>/out/paper/"
                                           "RENDER-ANCHOR.json —— 传论文包目录会把 out/paper "
                                           "拼两次；不给 ⇒ 锚那一格是 unknown）"},
            "report_path": {"type": "string",
                            "description": "报告路径（不给 ⇒ 报告形状那一格是 unknown）"},
        },
        "required": [],
        "additionalProperties": False,
    },
    side_effect="read",
    roles=("M",),
    returns=("{'can_close','status','failed','unknowns','findings','readings','summary'}；"
             "status 的键是七格检查（anchor/contradictions/load_bearing/report_shape/"
             "user_pending/substance/acceptance），值是三态之一（通过 / 拦住 / 没查成）；"
             "acceptance 那一格的 readings 里逐行给出：判据号、名称、受控档位、阈值、"
             "台账现算值、是否满足（不满足的那几行同时进 findings）；"
             "findings[] 每项是 {'check','code','level','detail'}"),
)
def conductor_closing(store, session=None, project_dir: str = "", report_path: str = "") -> ToolResult:
    """工具体：把收工门包成一次只读调用（判据在 `agentflow.closing`，这里不另写一份）。

    为什么主控需要它：交付说明里"能不能交"这句话必须有可查的读数撑腰。
    真机读数里最贵的一类失败不是"做错了"，而是"做完了"与"能交"被当成同一件事 ——
    包是旧的、依赖还挂着争议、承重结论只有数值支持。这些每一条都能被机器判，
    混在一段总结里就只剩一句"基本完成"。

    ## `session` 是装配期注入的「会话身份」（`draft/37` §63，修法 B）

    `session` = `{"root": <会话记录根>, "sid": <这一趟的会话号>}`，由
    `tools.build_registry(session_root=..., sid=...)` 放进装配依赖里。
    为什么不让工具体自己"猜"一个 sid：真机实测（第 11 趟 `real11`）主控在
    第 28 步调 `conductor.closing` 拿到 `can_close: true, failed: []`，
    而同一次运行外部带 `sid=real11` 的读数报 `failed: ['user_pending']` ——
    工具体此前按 `sid=None` 走到了缺省会话文件 `sessions/<今天>.jsonl`，
    而那一趟的提问落在 `sessions/real11.jsonl`。「假绿」。
    修法不是"让工具按调用时的日期猜得准一点"，而是把身份做成装配期的显式输入：
    装配时知道这一趟是谁，就一路带到判据里。
    没注入时按 `closing.NO_SESSION` 传下去 ⇒ 那一格记 `unknown`（不是 pass，
    也不是"读今天那份"——三态纪律）。
    """
    if store is None:
        return fail("没有工作区 ⇒ 收工门没查成（不是「可以交」）", kind="no_store", can_close=False)
    from .. import closing as CL

    sess = session if isinstance(session, Mapping) else {}
    rep = CL.check_closing(store, project_dir=project_dir, report_path=report_path,
                           session_root=(str(sess.get("root") or "") or None),
                           sid=str(sess.get("sid") or CL.NO_SESSION))
    data = rep.to_dict()
    kind = "" if rep.can_close else ("closing_unknown" if CL.tri_state_exit_code(rep) == 2
                                     else "closing_blocked")
    return ok({
        "can_close": data["can_close"], "status": data["status"],
        "failed": data["failed"], "unknowns": data["unknowns"],
        "findings": data["findings"], "readings": data["readings"],
        "summary": rep.summary(),
    }, kind=kind, blocked=not rep.can_close,
        blocker_count=len(rep.blockers), unknown_count=len(rep.unknowns))

#: 装配清单（`T-8`）：`(工具体函数, 需要从装配期注入的名字)`。
_TOOL_FUNCTIONS: tuple[tuple[Callable[..., Any], tuple[str, ...]], ...] = (
    (conductor_summon, ('_conductor',)),
    (conductor_summon_many, ('_conductor',)),
    (conductor_ledger, ('_conductor',)),
    (conductor_stop, ('_conductor',)),
    (conductor_resume_brief, ('_conductor',)),
    (conductor_cancel, ('_conductor',)),
    (conductor_ensure_project, ('store',)),
    (conductor_state, ('_conductor',)),
    (conductor_role_spec, ('store',)),
    (conductor_acceptance, ('store',)),
    # `session` 是装配期注入的会话身份（§63 修法 B）：`conductor.closing` 靠它
    # 读这一趟自己的会话文件，而不是回落到"今天那个文件"（那是一次实测假绿）。
    (conductor_closing, ('store', 'session')),
)


def register(registry: ToolRegistry, *, store: Any = None, conductor: Any = None,
             role_registry: Any = None, policy: Any = None,
             session: Any = None,
             backend: Any = "local") -> list[str]:
    """把主控工具注册进 `registry`，返回注册的工具名列表。

    参数
    ----
    store : Store | None
        台账与状态视图的来源；不给时工具仍会注册，但一被调用就明确报
        "没有工作区"（没查成 ≠ 没有问题）。
    conductor : Conductor | None
        现成的主控（不给就用 `conductor_for(store)` 按工作区取/建一个）。
    role_registry : Mapping | None
        `LocalBackend` 的角色接线（role -> 实例/工厂）；不给我方仍可派活，
        但被派的角色会以 `refused/not_wired` 如实落台账。
    session : Mapping | None
        这一趟的会话身份 `{"root": ..., "sid": ...}`，由
        `tools.build_registry(session_root=, sid=)` 注入；不给 ⇒
        `conductor.closing` 的 `user_pending` 那一格记 `unknown`（§63 修法 B）。
    """
    def _conductor() -> Conductor:
        if conductor is not None:
            return conductor  # type: ignore[return-value]
        if store is None:
            raise ToolError(
                "没有工作区（register 时既没给 conductor 也没给 store）⇒ 主控无法派活。"
                "这不是'没有任务'，是'没有台账可记'。"
            )
        return conductor_for(store, policy=policy, role_registry=role_registry, backend=backend)

    # \T-8\：声明与工具体都在模块级（\@tool\ 写进 \n.__tool_spec__\），
    # 这里只把装配期算出来的值按位置绑上去（\partial\）。
    _bound: dict[str, Any] = {}
    _bound['_conductor'] = _conductor
    _bound['store'] = store
    _bound['session'] = session
    names: list[str] = []
    for _fn, _deps in _TOOL_FUNCTIONS:
        names.append(registry.register(replace(
            _fn.__tool_spec__, handler=partial(_fn, *[_bound[k] for k in _deps]))).name)
    return names


def _parse_acceptance(path: Path, *, max_chars: int = 60) -> dict[str, Any]:
    """把验收表（markdown）解析成结构化的行。

    认的是项目脚本自己的写法：一行标题（含「P1–P11」之类）、一行结论
    （`结论：**全部成立**（10/10）`）、一张 `| 判据 | 名称 | 结论 | 读数 |` 表。

    `max_chars` 是交付说明能不能逐条对齐的关键：真机实测（2026-09-29，只读重放）
    十行的完整读数合起来 >1400 字，工具结果被上下文预算截断，M 只看到 P1–P4，
    于是它如实写"P5–P11 未核到"。默认截到 120 字/行 ⇒ 十行约 1.2k 字，
    够 M 逐条引用；需要全量时把 `max_chars` 调大（读数原文仍在盘上，随时可读）。

    解析不出来时 `rows` 为空而 `problems` 非空 —— 空表与"解析失败"必须分得开。
    """
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    title = next((ln.lstrip("# ").strip() for ln in lines if ln.startswith("#")), "")
    conclusion = next((ln.strip() for ln in lines if ln.startswith("结论")), "")
    rows: list[dict[str, Any]] = []
    problems: list[str] = []
    truncated = 0
    in_table = False
    for ln in lines:
        if not ln.startswith("|"):
            in_table = False
            continue
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        if len(cells) < 4 or set(ln.strip()) <= set("|-: "):
            continue
        if cells[0] == "判据":
            in_table = True
            continue
        if not in_table:
            continue
        reading = cells[3]
        if max_chars > 0 and len(reading) > max_chars:
            reading = reading[:max_chars] + "…"
            truncated += 1
        name = cells[1] if len(cells[1]) <= 30 else cells[1][:30] + "…"
        # 「成立」与「不成立」必须分得开：`"成立" in cells[2]` 会把不成立读成成立
        # （实测 2026-09-29：验收表里 P10/P11 写着「不成立」，解析出来却是 10/10 成立）。
        verdict = cells[2]
        rows.append({"id": cells[0], "name": name, "ok": verdict.strip() == "成立",
                     "reading": reading, "reading_chars": len(cells[3])})
    if not rows:
        problems.append("验收表里一行判据都没解析出来（表头是 `| 判据 | 名称 | 结论 | 读数 |` 吗？）")
    ok_count = sum(1 for r in rows if r["ok"])
    return {"found": True, "path": str(path), "title": title, "conclusion": conclusion,
            "rows": rows, "row_count": len(rows), "ok_count": ok_count,
            "not_ok_count": len(rows) - ok_count, "readings_truncated": truncated,
            "row_ids": [r["id"] for r in rows], "problems": problems}


def selftest() -> int:
    """自检：注册面与声明面逐名相同、且每个工具的 roles 里都有主控；不需要真工作区。

    ## 为什么条数不再写死（2026-10-02 实测的一处烂账）

    这里原先写的是 `if len(names) != 9` 与"应有 9 个"、外加一句"自检通过：9 件编排面工具"。
    工具面在 `acceptance` / `closing` / `summon_many` 落地之后就是 11 件了，
    于是这条自检恒返回 1（实测：`[conductor_tools] 注册了 11 个工具（应有 9 个）`）——
    而没有任何判据跑 `tools/*_tools.py` 的 `selftest()`（普查 13 个工具模块，
    只有这一个有 selftest），所以它烂在那里没人看见：一条恒红的自检与一条恒绿的自检
    一样没有信息量。修法不是把 9 改成 11（下次加工具会再烂一次），
    而是让"应有几个"由 `_TOOL_FUNCTIONS` 现算 —— 那个元组才是这份声明的唯一来源。
    """
    problems: list[str] = []
    reg = ToolRegistry(name="conductor-selftest")
    try:
        names = register(reg)
    except Exception as exc:  # 注册期就炸说明接线本身坏了
        print(f"[conductor_tools] 注册失败：{type(exc).__name__}: {exc}")
        return 1
    declared = [fn.__tool_spec__.name for fn, _deps in _TOOL_FUNCTIONS]
    if sorted(names) != sorted(declared):
        problems.append(
            f"注册面与声明面不一致：注册 {sorted(names)}，`_TOOL_FUNCTIONS` 声明 {sorted(declared)}")
    # 反向真空：声明了几件就真注册几件（`register` 少绑一件也要看得出来）。
    if len(names) != len(_TOOL_FUNCTIONS):
        problems.append(f"注册了 {len(names)} 个工具（`_TOOL_FUNCTIONS` 有 {len(_TOOL_FUNCTIONS)} 件）")
    for spec in reg.for_role(S.CONDUCTOR_ROLE):
        if S.CONDUCTOR_ROLE not in tuple(getattr(spec, "roles", ())):
            problems.append(f"{spec.name} 的 roles 里没有主控")
    for spec in reg.for_role("C"):
        problems.append(f"只读角色 C 拿到了主控工具 {spec.name}")
    if problems:
        for p in problems:
            print(f"[conductor_tools] {p}")
        return 1
    print(f"[conductor_tools] 自检通过：{len(names)} 件编排面工具，只有主控拿得到")
    return 0


__all__ = ["conductor_for", "reset_cache", "register", "selftest", "NotWiredError"]

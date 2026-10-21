"""主控工具：给主控 M 配手与眼。
`registry.for_role("M") == []` —— 主控此前一件工具都没有：它作为确定性执行者能被 `Conductor` 调用，却没有"派活"这个动作可用。
于是一句"评审这篇论文并给我更好的论文包"要落地，只能靠调用方在代码里替它把`plan` 拼出来 —— 那不是主 Agent，那是"人在派活"。
本模块只提供两件事：能不能做（闸门在 `Conductor` 内部：`ALLOWED_EDGES` / `CAPABILITIES` /参数接缝 / `policy` 四上
限 / 预算）与做了什么（`tasks` 台账）。
工具面（一个模块一个组前缀：`conductor.`）| 工具 | 侧效 | 作用 ||---|---|---|| `conductor.summon`
| write_local | 唯一的派活动作（过全部闸门） || `conductor.ledger` | read | 看台账：派了什么、被拒什么、剩多少 || 
`conductor.stop` | write_local | 优雅停止：不再新开任务 → 等在飞收尾 → 合成终态（无僵尸）→ 落续跑简报 || 
`conductor.resume_brief` | read | 读续跑简报（做了什么 / 剩什么 / 从哪继续） || `conductor.cancel`
| write_local | 硬取消（不等收尾，协作式） || `conductor.ensure_project` | write_local | 冷启动 / 热启动由
M 决定（四态如实给） || `conductor.state` | read | 只读状态视图（给 M 判断用） || `conductor.role_spec`
| read | 某角色的动作与工具面（派给谁、怎么写 brief） || `conductor.summon_many` | write_local | 批量派活（分波与
峰值在返回里；同角色多实例） || `conductor.acceptance` | read | 读项目的验收表（哪几行成立、读数原文可引用） || 
`conductor.closing` | read | 跑收工门八格 + 同一次调用里的内容级验收读数（两层各自三态；`can_close` = M 自己交的判据 
`goal_met`，八格退成读数 `status`/`machine_pass`） || `conductor.board` | read | 板上还挂着什么（工作项
+ 走到哪一档 + 谁读的） || `conductor.broadcast` | write_local | 给我名下的直接子代理广播一条通告（每人一条 ack 板项；
写侧工具改的是编排状态（台账行、取消信号、工作区目录、停止回执），`CAPABILITIES["M"] = ()`（零动作）与 `WRITE_SETS["M"] = {}`
（不写领域表）一个字都没动 —— 领域表仍然只有 A–H 能写。
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
from ..conductor import (DEFAULT_FANOUT_WAIT_SEC, ESCALATE_KINDS, Conductor, NotWiredError,
                         SummonResult, current_caller_role, current_task_id)
from . import READ_ONLY_ROLES, ToolError, ToolRegistry, ToolResult, fail, ok, tool

#: 一个工作区一个主控（键 = store 根路径）。主控是会话状态：
#: 预算、台账、取消信号必须跨多次工具调用连续，否则每次派活都是一个新主控。
_CONDUCTORS: dict[str, Conductor] = {}


def conductor_for(store: Any, *, policy: Any = None,
                  role_registry: Any = None, backend: Any = "local") -> Conductor:
    """取（或建）这个工作区的主控实例。同一个 `store.root` 永远拿到同一个实例。

    这里显式给 `fanout_wait_sec=DEFAULT_FANOUT_WAIT_SEC`（所有者 2026-10-08：
    「当达到派活上限后，父智能体或主控只可等待子智能体返回结果」）——
    真跑批的那一处由这里决定；`Conductor` 自己的默认值是 0（不阻塞库的其它调用方）。
    """
    root = str(Path(getattr(store, "root", ".")).resolve())
    if root not in _CONDUCTORS:
        _CONDUCTORS[root] = Conductor(store, policy=policy, registry=role_registry,
                                      backend=backend,
                                      fanout_wait_sec=DEFAULT_FANOUT_WAIT_SEC)
    return _CONDUCTORS[root]


def reset_cache() -> None:
    """清掉主控缓存（只给测试用：换一个工作区就换一个主控）。"""
    _CONDUCTORS.clear()


def cached_conductor(store: Any) -> Conductor | None:
    """这个工作区「已经存在」的主控实例；没有就返回 `None`（「绝不顺手建一个」）。
    
    ## 为什么要与 `conductor_for` 分开
    
    `conductor_for` 是"取（或建）"，它建出来的那个主控没有角色登记表、没有 policy （`registry=None`）。谁先在装配之前叫它一次，后来的 
    `wired_llm_conductor` 就会按缓存静默复用到那个空壳 —— 于是"我要的是接了线的主控"与"实际跑的是空壳"在读数上长得一模一样（这条缓存纪律写在 
    `host.wired_llm_conductor` 的 docstring 里，`conductor_for` 自己也写着）。
    
    所以"只想借用一下这一趟的主控身份说句话"的调用方（今天只有一个：F 上报缺缝，见 `agent_f/core.py::_escalate_missing_seam`）只能
    借用「已经存在」的那一个；不存在时它必须如实说"这一层没接到主控"，而不是为了发一条消息把会话的主控建歪。
    """
    return _CONDUCTORS.get(str(Path(getattr(store, "root", ".")).resolve()))


#: `payload_preview` 的字数上限（`draft/37` §130）。
#:
#: 为什么要把它给主控：`SummonResult.payload` 是「动作的返回值」 —— 而此前
#: `_summon_dict` 只回任务元数据（status/outcome/detail），返回值的「一个字都不给」。
#: 真机后果（T2 第 4 趟，95 个任务）：主控只能靠反复 `fs.read data/*.json` 反推
#: 每个动作到底产出了什么；而 C 的八个动作「产物就是返回值本身」（只读分析）⇒
#: 召 C 等于什么都没拿到 ⇒ 那一趟 `role=C` 的任务是 「0 条」（不是 C 坏了，是它不可见）。
#: 2000 字沿用 `_write_task_digest` 的 `payload_preview` 口径（同一处量法，不另立一份）；
#: 要完整的那份就 `fs.read` `artifacts[0]`（`out/tasks/<task_id>.json`）。
PAYLOAD_PREVIEW_CHARS = 2000


def _summon_dict(res: SummonResult) -> dict:
    """把一次召唤的结果收成工具返回值（键与 `returns=` 声明逐字对应）。

    `draft/37` §130：除了任务元数据，还要带上「动作返回值的预览」与「完整那份的落点」
    —— 这是"主控能不能看见同伴产出了什么"的那条线。预览有上限（`PAYLOAD_PREVIEW_CHARS`），
    截断与否如实写在 `payload_truncated` 里（不许静默截断）。
    """
    payload = getattr(res, "payload", None)
    preview = ""
    size = 0
    keys: list[str] = []
    if payload is not None:
        try:
            blob = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
        except Exception:  # noqa: BLE001 —— 编不出来就退回 `repr`（照样给出去，不吞）
            blob = repr(payload)
        size = len(blob.encode("utf-8"))
        preview = blob[:PAYLOAD_PREVIEW_CHARS]
        if isinstance(payload, Mapping):
            keys = sorted(str(k) for k in payload)
    return {"task_id": res.task_id, "role": res.role, "action": res.action,
            "status": res.status, "outcome": res.outcome,
            "refusal_reason": res.refusal_reason, "detail": res.detail,
            "error": res.error, "tokens": res.tokens, "usd": res.usd,
            "depth": res.depth, "elapsed_sec": res.elapsed_sec,
            "children": list(res.children or ()), "checked": res.checked,
            "payload_preview": preview, "payload_bytes": size,
            "payload_keys": keys,
            "payload_truncated": size > PAYLOAD_PREVIEW_CHARS,
            "artifacts": list(getattr(res, "artifacts", None) or ())}


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
            json.dumps(brief, ensure_ascii=False, indent=1, default=str) + "\n", encoding="utf-8", newline="\n")
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
    "派活：把活交给某个角色（只写**是什么活**，怎么做由它定）。闸门在主控内部（边 / 动作表 / 参数接缝 / 上限 / 预算）；被拒也落台账并回 `"
    "refusal_reason`。",
    {
        "type": "object",
        "properties": {
            "target_role": {"type": "string", "description": "被召唤的角色（A–H）"},
            # 「2026-10-16（业主口径 S2 最终形态）」：`action` 「整个摘掉」 ——
            # 「一致改成 task 必填，action 不填」「action 完全不用父代理填」。
            # 派活只有 `target_role` + `task`；点哪个动作是被派者自己的事。
            "task": {"type": "string", "description":
                     "**必填**：这一趟派给它的是什么活（写清做什么；可带起手建议，怎么做由它定）"},
            "params": {"type": "object", "description": "动作参数（按参数的 schema 校验）"},
            "input_key": {"type": "string", "description": "同一祖先链上去重用的键（防活锁）"},
        },
        # 2026-10-16（口径 S2）：「`task` 进必填、`action` 可选」（与形状面／广告面一致）。
        "required": ["target_role", "task"],
        "additionalProperties": False,
    },
    side_effect="write_local",
    roles=("M",),
    returns=("{'task_id','role','action','status','outcome','refusal_reason','detail',"
             "'error','tokens','usd','depth','elapsed_sec','children','checked',"
             "'payload_preview','payload_bytes','payload_keys','payload_truncated','artifacts'}"),
)
def conductor_summon(_conductor, target_role: str, task: str, params: dict | None = None,
                     input_key: str = "") -> ToolResult:
    """工具体：一次派活。闸门全在 `Conductor.summon` 内部；被拒也落台账。

    2026-10-16（口径 S2「M 只派活」）：`action` 可以为空 —— 那就是「只派活」，
    由被召唤的角色跑自己的循环、按自己的能力范围选动作；此时 `task` 必填
    （"接活的人得知道自己该干什么"）。与 `_do_summon` 同一套，不另立规矩。
    """
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
    if not str(task or "").strip():
        raise ToolError("派活必须写清是什么活：`task` 必填"
                        "（否则接活的人不知道自己该干什么）")
    # 2026-10-16（口径 S2 最终形态）：「「不是忽略 action，是完全不要有填 action 的位置」」
    # ⇒ 形参里没有 `action`、条目里不读它；这一行那个 `""` 是「内部 API 的实参」
    # （`Conductor.summon(role, action, params)` 是 `pipeline`/`scheduler`/`deliver`
    # 也在用的内部接口，它保留动作那一格），「不是留给模型填的位置」。
    params = {**dict(params or {}), "task": str(task)}
    res = _conductor().summon(target_role, "", params or {}, by=S.CONDUCTOR_ROLE,
                              input_key=input_key)
    data = _summon_dict(res)
    return ok(data, **data)

@tool(
    "conductor.summon_many",
    "一次派**一批**活，真并发：按写集分波（`policy.waves_of`），同波用线程池跑（上限 `max_concurrency`）。同角色多实例给每个 target "
    "不同 `instance` 标签 ⇒ 允许同波并发；没标签时出现多次自动补 `<角色>#N`（`auto_instance=true`）。并发看 `waves` 与 `"
    "concurrent_peak`。",
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
                        # 2026-10-16（口径 S2 最终形态）：`action` 同样摘掉（与 `summon` 一致）。
                        "task": {"type": "string", "description":
                                 "**必填**：这件活是什么（可带起手建议）"},
                        "params": {"type": "object", "description": "动作参数"},
                        "instance": {"type": "string",
                                     "description": "实例标签；同角色不同标签 ⇒ 允许同波并发"},
                        "input_key": {"type": "string", "description": "去重/防活锁的键"},
                    },
                    "required": ["target_role", "task"],
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
        # 2026-10-16（口径 S2 最终形态）：条目里「不读 `action`」（模型没有那个位置可填）。
        if not target_role:
            raise ToolError(f"targets[{i}] 缺 target_role")
        work = str(item.get("task") or "").strip()
        if not work:
            raise ToolError(f"targets[{i}] 的 `task` 必填（这一件活是什么）")
        item = {**dict(item), "params": {**dict(item.get("params") or {}), "task": work}}
        instance = str(item.get("instance") or "")
        if not instance and target_role in auto:
            used[target_role] = used.get(target_role, 0) + 1
            instance = auto[target_role][used[target_role] - 1]
        calls.append(SC.TaskCall(
            # 2026-10-16（口径 S2 最终形态）：这里那个 `""` 是「内部 API 的实参」，
            # 不是留给模型填的位置（条目里没有 `action` 可读）。
            role=target_role, action="",
            params=dict(item.get("params") or {}),
            by=S.CONDUCTOR_ROLE,
            # 2026-10-20：父必须是「发起这一批的那一趟的绝对编号」（改前这一格缺 ⇒
            # `TaskCall.parent_task_id` 走默认 `None` ⇒ 批量派出去的子代理在台账上
            # 全是孤儿，名册 owner 也落成空串/隐藏文件）。号从调用上下文读，
            # 不在这里拼（`calling_as` 挂上的就是这一趟的 `task_id`）。
            parent_task_id=current_task_id() or None,
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
    # 键表写在这里（字面量）而不是 `ok(payload, payload)`：本模块的工具体
    # 历史上都是"看不清的调用点"那一档，静态扫描读不出键；这一件刻意写成
    # 看得见的形态，于是"声明了哪些键"可以直接对着这段代码核。
    # （`test_tools_branch_key_sets` 的 `INVISIBLE_OK_SITES` 里
    # `conductor_tools.py` 的处数因此 +1，已同步改表。）
    return ok(payload, **payload)

@tool(
    "conductor.ledger",
    "看台账：tree（层级与结局）/ stats（计数）/ issues（结构问题）/ verify（不变式）/ relays（同伴的『请代唤』申请）。`task_count` "
    "与 tree 行数数 `tasks` 全量（含顶趟行）；召唤数看 `started_total`。不含建议。",
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
    `view="relays"` 是 2026-09-30 加的（`draft/28` §199）：同伴够不到某个边时，框架会自动给主控发一条 `subject=请代唤` 的
    留言并落一条 `agent_summon_request`事件（`agent_loop._request_relay`）。留言是给人看的，这个视图是给主控看的 ——它把那些
    申请整理成一张可判定的表：每条申请后面有没有出现"要的那个(角色, 动作)"的任务行 ⇒ `fulfilled` / 待受理。三态纪律：查不到会话记录时
    `relay_pending` 报 `None`（没查成），不报 0（"没有申请"）。
    ## 口径（F1 之后 `tasks` 里多了顶趟行，这一屏必须说清它数的是什么）
    `task_count = len(c.tree())` 数的是 `tasks` 台账全量 —— 里面包含顶趟行（`role=M` / `action="run"` / 
    `called_by="user"`，由 `conductor.open_top_level_run`开、`finish_top_level_run` 收）：那是用户发起的
    那一趟，不是一次召唤。它留在读数里是刻意的（它同时是"谁在派活"的身份行），但下游不许把 `M.run`当成"第 N 次召唤"；要召唤数就看 `view="stats"` 
    的 `started_total`（那一格的口径连同 `calibers` 一起写在 `conductor.stats()` 里）。
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
    "停止：默认**优雅** —— 落停机开关 → 广播叫停（同伴收工并停掉自己起的子进程）→ 拒新召唤 → 在飞任务有界收尾 → 剩下的合成终态（记未知、不重试）→ 落续跑简报。`"
    "force=true` 直接停：立刻按进程登记连子孙一起杀。给 `root_task_id` 只停那一支，不给是全工作区。幂等。",
    {
        "type": "object",
        "properties": {
            "reason": {"type": "string", "enum": list(CANCEL_CODES)},
            "drain_sec": {"type": "number", "description": "等收尾的上限秒数（force=true 时不等待）"},
            "force": {"type": "boolean",
                      "description": "直接停：不等待收尾，并杀掉登记在盘的子进程（连子孙）"},
            "notify": {"type": "boolean",
                       "description": "是否在公共频道广播叫停（默认 true）"},
            "root_task_id": {"type": "string",
                             "description": "只停这一支（S4）：给一个实例号 ⇒ 开关只对"
                                            "它和它的子孙生效；不给 = 全工作区（老行为）"},
        },
        "required": [],
        "additionalProperties": False,
    },
    side_effect="write_local",
    roles=("M",),
    returns=("{'reason','reason_mapped_from','detail','inflight_at_stop','drained_sec',"
             "'disposed','resume_brief','verify','stop_switch','notified','killed_children',"
             "'blocked_remaining'}"),
)
def conductor_stop(_conductor, reason: str = "user", drain_sec: float = 30.0,
                   force: bool = False, notify: bool = True,
                   root_task_id: str = "") -> ToolResult:
    """工具体：停止（优雅 = 喊停 → 有界收尾 → 合成终态 → 续跑简报；强制 = 直接停）。
    
    `draft/37` §128 加的两件（用户口径："优雅停止还要提醒那些 Agent 把发起的进程一起停掉，还要写个强制停止是直接杀掉"）：
    
    1. 「先落停机开关」（`stopctl`）—— 它是唯一能打断"在飞工作"的通道：卡在等待循环里的子进程（E 的实验脚本）每 0.2 s 看一次它，于是会被立刻终止（实测
    30 s → 0.36 s）； 2. `notify=True` 时在「公共频道广播」一条叫停（`#public`）：A–H 每个角色都收得到。 2026-10-08 晚改
    回留言（所有者 T18：「插话只有 M 可能受到用户的插话」）： D07 当年把它改成集体插话的理由是"留言躺在收件箱里等下一次听、打断不了在跑的同伴"，而那句话今天已经不
    成立 —— 步边界的 `_hear()` 会把新留言并进这一步的结果（`agent_loop._hear`，判据见 `draft/85` §5 的表），所以留言同样"下一步
    就看到"，而且它在盘上有收件人、可 ack（`draft/85` §2.1）。body 里仍然点明"收到广播不等于被叫停，开关才算"，免得同伴误判。
    
    `force=True` 是"直接杀掉"：不等待收尾，并按进程登记把子进程连子孙一起杀（「排除自己」：杀掉自己的进程树会让这次调用永远回不去；M 随后由步循环的停机判据收工）。
    """
    from .. import stopctl
    from ..agent_loop import PUBLIC, send_message

    c = _conductor()
    root = Path(str(getattr(getattr(c, "store", None), "root", "") or "."))
    sid = str(getattr(getattr(c, "backend", None), "sid", "") or "")
    mapped_from = ""
    code = reason if reason in CANCEL_CODES else "user"
    if code != reason:
        mapped_from = reason
    # S4（`draft/90` E7）：给了 `root_task_id` ⇒ 这把开关只对那一支生效
    # （`stop_scope` = `"subtree"`）；不给 = 全工作区（老行为逐字不变）。
    # 撤开关的责任：那一支的根自己撤（`AgentLoop._stop_applies` 里那一格），
    # 别的成员只记一笔 —— 谁先读到谁撤会让同支后面的人静默不停（§140 的反向形态）。
    switch = stopctl.request_stop(root, reason=code, by=S.CONDUCTOR_ROLE, force=force, sid=sid,
                                  root_task_id=root_task_id)
    notified = ""
    if notify:
        # 2026-10-08 晚（所有者 T18）：叫停广播改回留言。D07（用户 2026-10-05）当年
        # 把它改成集体插话，理由是"留言躺在收件箱里等下一次听、打断不了在跑的同伴"——
        # 那句在今天是过期的事实（步边界的 `_hear()` 会把新留言并进这一步的结果）。
        # 而插话收窄成"只有用户 → M"之后，M 发的叫停不能再走插话：那是另一条通道。
        # 留言还有两个插话给不了的东西：它落在公共频道（盘上可读）、且可 ack。
        #
        # S6-a：公聊的可见面收窄成"发信人的直接子代理"（业主 T21）之后，叫停这一条
        # 走框架档（`by_framework=True` ⇒ 所有角色可见）—— 工具层手上没有实例号，
        # 而"听不到叫停的子孙会继续烧钱跑实验"是安全件。S4 的"沿边逐层下发"落地后
        # 这一档退休（`draft/86` §14.6 写明了这处冲突与处置）。
        ij_id, problem = send_message(
            root, sender=S.CONDUCTOR_ROLE, to=PUBLIC, subject="叫停",
            body=("用户/主控叫停（" + code + ("，强制" if force else "") + "）：请各自收工，"
                  "并把你已经起的子进程停掉（实验脚本、检查器进程等）。"
                  "停机开关已落在 " + str(stopctl.stop_path(root)) + "；"
                  "你会在**下一步开头**读到这条留言（它不打断当前步）——"
                  "真正让在飞工作停下的是那个开关。"),
            sid=sid or None, by_framework=True)
        notified = ij_id if not problem else f"未发出：{problem}"
    receipt = c.cancel(code, detail=("强制停止（主控 M）" if force else "优雅停止（主控 M）"),
                       by=S.CONDUCTOR_ROLE)
    # 回报首次生效的那个原因（FC-20 第 2 条：终态先到先得、reason 只许一个答案）。
    # 本次请求的 code 可能不是它 —— 那就把两个都写出来，别让"我请求了 budget"
    # 被读成"停止原因是 budget"。
    effective = str(getattr(c.token.reason, "code", "") or code)
    if effective != code and not mapped_from:
        mapped_from = code
    code = effective
    waited = 0.0
    if not force:
        t0 = time.monotonic()
        while c.cancel_inflight() and (time.monotonic() - t0) < float(drain_sec):
            time.sleep(0.05)
        waited = round(time.monotonic() - t0, 3)
    disposed = c.dispose()
    killed = {}
    if force:
        # 「直接杀掉」那一半：按登记把子进程连子孙一起杀，「排除自己」
        # （杀掉自己的进程树会让这次工具调用永远回不去）。
        killed = stopctl.kill_registered(root, exclude_pid=os.getpid())
    brief = _write_resume_brief(c)
    # 业主 2026-10-13：「优雅停止就是主控用这个操作…」+「接收到停的时候，剩余任务委托状态
    # 自动变成 block」—— 这一条是 M 的优雅停止操作，所以「整趟」还没终态的任务与委托
    # 在这里由框架翻成 `block`（不留"谁该收尾"的模糊），读数随结果回去，M 汇总进交付说明。
    try:
        blocked_remaining = stopctl.block_remaining_tasks(
            c.store, why=code, all_runs=True)
    except Exception as exc:  # noqa: BLE001 —— 翻不动是"没查成"，如实报，不吞
        blocked_remaining = {"checked": False, "blocked": [], "blocked_items": [],
                             "why": code,
                             "reason": f"剩余任务翻 block 没走成：{type(exc).__name__}: {exc}"}
    data = {"reason": code, "reason_mapped_from": mapped_from,
            "blocked_remaining": blocked_remaining,
            "detail": receipt.get("detail", ""),
            "inflight_at_stop": list(receipt.get("inflight") or ()),
            "drained_sec": waited, "disposed": disposed,
            "resume_brief": brief, "verify": c.verify_tasks(),
            "stop_switch": switch, "notified": notified, "killed_children": killed}
    return ok(data, **data)

@tool(
    "conductor.resume_brief",
    "读上一次优雅停止留下的续跑简报（做了什么 / 剩什么 / 从哪继续）。没有简报时如实说『还没有停止过』；未终态行逐条报出。",
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
    "硬取消（协作式）：立刻置共享停止信号，不等在飞收尾；在飞任务自己收终态。与 conductor.stop 的区别是 stop 先尝试收尾。",
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
    "冷启动 / 热启动：`start=auto|cold|warm`，返回四态（absent/empty/workspace/not_a_project）与 mode。`cold`"
    " 才建目录；`warm` 必须已存在且是工作区。已在工作区里又没给 `projects_dir` ⇒ 被拒（`already_a_project`）：**不要另建项目**。",
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
    `projects_dir` 的缺省不是当前工作区，而是 `projects.projects_dir(None)`—— 一个与工作区无关的默认落点（本机读数 `projects/`，工作区根相对；
    `projects.DEFAULT_PROJECTS_DIR` 是"由本包位置推出的工作区根 + `projects/`"，也可用设置文件的 `workspace.projects_dir` 覆盖）。
    于是"在一个已存在的工作区里调它"会得到一个在别处新建的空项目，而不是"热启动当前项目"：
    - 真机实测（`draft/37` §37）：那一趟 23 步里有 4 步在 `ensure_project`，其中一次真的建出了 `projects/project11`（`project.json`
    的 `created_at` = 2026-10-02T20:39:47+08:00，与那次运行同秒级）—— 而当时的账本上没有任何一步显示"我建了个项目"。- 同一天，本仓库自己的普查探针（`temp/_p40_m_tool_smoke.py`）
    在没给`projects_dir` 时也建了 `project12` / `project13` 两个空项目 ——写探针的人也会踩，说明这不是"M 的纪律问题"，是缺省值的问题。
    守卫的边界刻意很窄：只拒"当前工作区自己就是一个初始化过的项目、而调用方又没显式说项目落在哪"。显式给 `projects_dir`（或设`AGENTFLOW_PROJECTS_DIR`）时照旧工
    作 —— 那是操作者在说"我知道落在哪"。不这么定就会误伤既有判据：`tests/test_conductor_tools.py` 里那两条冷/热启动用例正是"在一个工作区里、把项目建到另一个显式
    指定的目录"。
    """
    from .. import projects as P
    from .. import settings as SET

    explicit = (bool(projects_dir.strip())
                or bool(os.environ.get(P.ENV_PROJECTS_DIR, "").strip())
                # 设置文件里写了落点也算"操作者说了落在哪"（与上面那两档同义）：
                # 漏掉这一档会让"配了 settings.json 的人"收到一句"缺省落点是…"的
                # 误导拒绝 —— 那句话在读数上就是假的。
                or bool(SET.workspace_settings().get("projects_dir", "")))
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

def _queue_backlog(store_: Any) -> dict[str, Any]:
    """两条请求队列里「还没人做」的读数（`draft/39` §6.45 的 D56）。

    为什么需要这一格：`tables` 只给行数 —— `search_requests: 4` 这一行读不出
    「其中 1 条 `done=false`、没人认领」。真机读数（T5 第 5 趟 `p8e`）：F 的攻坚子目标
    用 `submit_search_request` 提了一条请求，整趟没人做，计划停在「等 A 完成检索请求」，
    而 `conductor.state` 与收工门都看不出这件事。

    读不出来的表记 `rows=-1` / `unfinished=-1`（与 `tables` 里 -1 的约定同一条：
    -1 是「没查成」，不是 0）。
    """
    def _is_open_search(r: Mapping[str, Any]) -> bool:
        return r.get("done") is not True

    def _is_open_reprocess(r: Mapping[str, Any]) -> bool:
        return str(r.get("status") or "pending") == "pending"

    out: dict[str, Any] = {
        "note": ("`unfinished` 是**提交了、还没人做**的条数：消费这两条队列的动作是 "
                 "A 的 `run_once` / `run`（检索）与 B 的 `reprocess_once` / `run_reprocess`"
                 "（重抽取）。收工前它应当是 0 —— 有的话要么派活做完，要么在交付说明里"
                 "逐条写清为什么留着。`literature.unprocessed` 是**第三条队列**："
                 "注册了、还没被消化的文献条数；消费它的动作是 B 的 `run_once` / `run`，"
                 "而**一次调用只消化一篇**。"),
    }
    for table, key, is_open in (("search_requests", "request_id", _is_open_search),
                                ("reprocess_requests", "reprocess_id", _is_open_reprocess)):
        try:
            rows = [dict(r) for r in store_.rows(table)]
        except Exception:  # noqa: BLE001 —— 读不到就说读不到（不编 0）
            out[table] = {"rows": -1, "unfinished": -1, "unfinished_ids": [], "unreadable": True}
            continue
        open_rows = [r for r in rows if is_open(r)]
        out[table] = {
            "rows": len(rows),
            "unfinished": len(open_rows),
            "unfinished_ids": [str(r.get(key) or "") for r in open_rows[:12]],
            "submitted_by": sorted({str(r.get("submitted_by") or "")
                                    for r in open_rows if r.get("submitted_by")}),
        }
    # 第三条队列（T2 第 23 趟 `t2r` 的整改）：注册了、还没消化的文献。
    #
    # 为什么要有这一格：`tables["literature"] = 8` 读不出"其中 7 篇 `processed` 不是 True"。
    # 真机读数（`projects/p6t-research-from-zero`）：M 只派了 1 次 `B.run_once`
    # （而 `run_once` 的语义是 `claim()` 领一行、处理完返回 ⇒ 一次一篇），
    # 命中的恰好是不对口的那一篇（签名/增益图书目）——12 条 `statements` 全是它来的概念，
    # 而对口的 `lit:0003`《Edge-girth-regular graphs》留在 `processed=False`，
    # 于是"文献进稿"那一格（`document_literature_citations`）读成 0。
    # 这件事当时的 `conductor.state` 与收工门都看不出来，与 `D56`（请求队列）
    # 同一个形态：只有行数、没有"还有几条没人做"。
    try:
        lit_rows = [dict(r) for r in store_.rows("literature")]
    except Exception:  # noqa: BLE001 —— 与上面两条同一条约定：-1 是"没查成"，不是 0
        out["literature"] = {"rows": -1, "unprocessed": -1, "unprocessed_ids": [],
                             "unreadable": True}
    else:
        pending = [r for r in lit_rows if r.get("processed") is not True]
        out["literature"] = {
            "rows": len(lit_rows),
            "unprocessed": len(pending),
            "unprocessed_ids": [str(r.get("lit_id") or "") for r in pending[:12]],
        }
    # 第四条："你立了几条研究问题"与"那两档的隐式门槛"（T4 第 10 趟 `t4j` 的整改）。
    #
    # 为什么要有这一格：`closing` 的 `retrieval_ok_rows` 与 `document_claim_rows` 两档，
    # 缺省门槛（`kind_min`）就是研究问题条数，而 `min_overridden` 的规则是
    # `max(declared, kind_min)` ⇒ 验收表里写什么都不能把它压低。真机读数（`t4j`）：
    # M 立了 12 条研究问题、只跑了 4 次检索、只写了 5 条断言
    # ⇒ 收工门报两条 blocker（4<12、5<12），而这两句话在提示词里已经写着
    # （`specs/m.py` 那两个"缺省阈值 = 你立起来的研究问题条数"）—— 散文改不了行为，
    # 所以这一格把它放到 M 每次看状态时都看得到的地方：三个数并排摆着。
    try:
        n_qs = len(list(store_.rows("research_questions")))
        n_ok = len([r for r in store_.rows("search_requests") if str(r.get("outcome") or "") == "ok"])
        n_claims = sum(len([c for c in (dict(d).get("claims") or [])
                            if isinstance(c, dict) and (c.get("citations") or [])])
                       for d in store_.rows("documents"))
    except Exception:  # noqa: BLE001 —— 读不到就整格记 -1（不编 0）
        out["thresholds"] = {"research_questions": -1, "retrieval_ok": -1,
                             "document_claims": -1, "unreadable": True}
    else:
        out["thresholds"] = {
            "research_questions": n_qs,          # 这两档缺省门槛的来源
            "retrieval_ok": n_ok,                # `retrieval_ok_rows` 的当前读数
            "document_claims": n_claims,         # `document_claim_rows` 的当前读数
            "short_retrieval": max(0, n_qs - n_ok),
            "short_claims": max(0, n_qs - n_claims),
            "note": ("`retrieval_ok_rows` 与 `document_claim_rows` 两档的**缺省门槛就是"
                     "研究问题条数**（`closing` 的 `kind_min`；而生效值是 "
                     "`max(你在验收表里写的 min, kind_min)` ⇒ 写小了压不下去）。"
                     "`short_*` 是还差几条：要收工时它们应当是 0 —— 要么把检索与断言做够，"
                     "要么立题时克制一点。"),
        }
    return out


@tool(
    "conductor.state",
    "只读状态视图：各表计数 + 猜想按状态 + 台账规模，不带建议。`tasks` 是全量（含顶趟行 `called_by=user`）；召唤数看 `"
    "conductor.ledger(view=\"stats\")` 的 `started_total`；`queues.literature.unprocessed` = "
    "已注册未消化的篇数（`run_once` 一篇一次）。",
    {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
    side_effect="read",
    roles=("M",),
    returns="{'root','tables','conjectures','tasks','queues'}",
)
def conductor_state(_conductor, ) -> ToolResult:
    """工具体：只读状态视图（给主控判断用，不含建议）。

    口径（F1）：`tasks` 这一格是 `len(c.tree())`，即 `tasks` 台账全量 ——
    含顶趟行（`role=M` / `action="run"` / `called_by="user"`，用户发起的那一趟，
    不是召唤）。它与同一屏里 `tables["tasks"]`（`store.rows("tasks")` 的行数）是
    同一个量；要"我派了几次活"就看 `conductor.ledger(view="stats")` 的
    `started_total`（那一格不计顶趟）。
    """
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
            "conjectures": conjectures, "tasks": len(c.tree()),
            "queues": _queue_backlog(store_)}
    return ok(data, **data)

@tool(
    "conductor.role_spec",
    "某角色的规格：允许的动作与各自的参数名、以及它今天有哪些工具。派活前用它确认『这个角色能不能做这件事』；与 capabilities 同源。",
    {
        "type": "object",
        "properties": {"role_name": {"type": "string", "description": "角色名（A–H）"}},
        "required": ["role_name"],
        "additionalProperties": False,
    },
    side_effect="read",
    roles=("M",),
    # 2026-10-15 补齐：这把工具体返回的是那个角色的整份 brief（六个字段），
    # 而声明里只列了 `{role, actions, tools, summonable}` ⇒ 模型看不到
    # `duty` / `boundary` / `policy` / `stance` / `signature_error` / `deliverable` ——
    # 而这件的用途「恰恰是」"让一个角色读到另一个角色的口径"。
    # `returns` 会拼进 function-calling 的 `description`（模型看得到）。
    # 「2026-10-16（业主口径）」：这里「不再返回 `actions` / `tools`」。
    # 原话逐字：「M 只是个派活的……「不指定能力」。M 能看到的只是各角色描述，
    # 「看不到具体的工具箱与动作」，但可在角色描述中暗示它各角色能干什么。」
    # 所以这一格从"查它的动作面与工具面"改成"读它的描述"（`role` + `summonable`
    # + brief 六格）。留着 `actions`/`tools` 等于把刚在伙伴表上关掉的门又开半扇 ——
    # M 只要逐个角色查一遍，就能重新拿到每个角色的动作与必填参数。
    returns="{'role','summonable',"
            "'duty','boundary','policy','signature_error','deliverable','stance'}",
)
def conductor_role_spec(store, role_name: str) -> ToolResult:
    """工具体：某角色的「描述」（职责/交付物/边界/立场；不再给动作面与工具面）。"""
    from .. import capabilities as C

    data = {"role": role_name,
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
    "只读：读某项目的验收表（默认 out/paper/ACCEPTANCE.md），逐行解析出 P1–P11 的判据名 / 结论 / 读数。交付说明要逐条对齐。",
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
             "'readings_truncated','row_ids','problems','documents'}；"
             "rows[] 每项是 {'id','name','ok','reading','reading_chars'}；"
             "给了 ids 时多 {'requested','unknown_ids'}"),
)
def conductor_acceptance(store, project_dir: str = "", rel_path: str = "",
                         max_chars: int = 60, ids: list | None = None) -> ToolResult:
    """工具体：把验收表读成结构化的十行（读不到就如实说读不到，不给空表）。
    `ids` 是给"一次读不完"准备的：真机实测（2026-09-29）十行的完整读数会被上下文预算剪枝，而主控手里没有读文件工具（它的面只有 `conductor.*`）⇒
    被剪掉的部分读不回来。按批读是"不靠猜"的做法（而不是让 M 猜 P5–P11 写了什么）。
    ## 路径解析（`draft/37` §88：这一处是三个落点里被漏掉的那一个）
    `conductor.acceptance(project_dir=".")` 原先按进程 cwd 解析 ——而工具描述逐字写的是"相对工作区"。T1 第 2 趟真机（2026-10-04）：
    主控传`{"project_dir": "."}`，工具去读 `agentflow/out/paper/ACCEPTANCE.md`（工作区根相对）（进程 cwd 所在的仓
    库目录），连报两次"验收表不在盘上"，而那张表就在工作区里—— 主控因此始终没看到 P1–P11 判据，后面每一跳都靠猜。
    同一件事 `closing.resolve_under_workspace` 的 docstring 里已经记过一次（`draft/37` §60：`closing` 与 
    `reviewaccept` 都改成了那一个解析口），本工具是那批里的第三个落点却漏改了 ⇒ 现在共用同一个解析口，不另写一份。
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
    "只读：跑收工门（八格）—— 正文与 PDF 对得上（`out/paper/main.tex`）/ 无未裁决矛盾 / 承重结论有 T3 / 报告体例 / 无待答问题 / "
    "**实质产出**（`statements` 等表至少一张非空）/ 验收表机器可判行（`out/paper/ACCEPTANCE-CHECKS.json`）/ "
    "产物台账与盘上一致（`ARTIFACTS.jsonl`）。每格三态，unknown 不是通过。`can_close` 由你交的判据（`goal`/`goal_met`/`"
    "task_list`）决定，不交 ⇒ `false` + 『没人判过』。还回 `review_acceptance`：内容级验收五条判据 + 五种辅助读数；给 `"
    "cap_usd` 才判成本上限。",
    {
        "type": "object",
        "properties": {
            "project_dir": {"type": "string",
                            "description": "项目根（相对工作区；正文与编译回执在 <它>/out/paper/ "
                                           "—— 传 out/paper 目录会把 out/paper 拼两次；不给 ⇒ "
                                           "论文那一格是 unknown）"},
            "report_path": {"type": "string",
                            "description": "报告路径（不给 ⇒ 报告形状那一格是 unknown）"},
            "cap_usd": {"type": "number", "minimum": 0,
                        "description": "这一趟的成本上限（美元）—— 内容级验收的"
                                       "「在成本上限内」那一格用它判；不给 ⇒ 那一格是"
                                       "「没查成」而不是通过（负数会被参数校验拒成 param_error）"},
            "goal": {"type": "string",
                     "description": "你这一趟的目标（一句话）。收工由你判 ⇒ 先说清目标是什么"},
            "goal_met": {"type": "boolean",
                         "description": "**你的判断**：目标达成了没有（业主 2026-10-09："
                                        "「是否收工不要用机械判据，由 M 制定的目标是否达成为准」）。"
                                        "不给 ⇒ 这一趟没有收工判据（`can_close=false`）"},
            "basis": {"type": "string",
                      "description": "你凭哪几条读数这么判（可写台账计数 / 交付物路径 / "
                                     "与机器八格不一致时你为什么不认它）"},
            "task_list": {
                "type": "array",
                "description": "**你自己列的任务列表**（业主 2026-10-09：「所有智能体是否能停"
                               "都是看自己被派的活有没有做完，M 也不例外，只是 M 需要根据用户"
                               "指令给自己设计任务列表」）—— 每一项写清做什么、做完了没有",
                "items": {
                    "type": "object",
                    "properties": {
                        "what": {"type": "string", "description": "这一项是什么活"},
                        "state": {"type": "string",
                                  "enum": ["done", "not_done", "cannot"],
                                  "description": "done=做完了；not_done=还没做；"
                                                 "cannot=做不了（must 写 why）"},
                        "why": {"type": "string",
                                "description": "not_done / cannot 的理由（做不了时必填）"},
                    },
                    "required": ["what", "state"],
                    "additionalProperties": False,
                },
            },
        },
        "required": [],
        "additionalProperties": False,
    },
    side_effect="read",
    roles=("M",),
    returns=("{'can_close','machine_pass','m_verdict','overrode','verdict_conflicts',"
             "'verdict_note','verdict_written',"
             "'status','failed','unknowns','findings','readings','summary','review_acceptance'}；"
             "**can_close 是 M 的判据**（它按自己列的 `task_list` 判『活做完了没有』，"
             "结论写在 `goal_met`），机器八格退成读数（`status`/`machine_pass`），"
             "两者不一致时 `overrode` 逐格点名、自述与自己的列表对不上时 `verdict_conflicts` "
             "逐项点名；M 没给判据 ⇒ `can_close=false` + 读数说明『没人判过』；"
             "M 给了判据 ⇒ 那一次调用把它落到 `out/review/m-verdicts.jsonl`"
             "（运行外那一趟/发布门读同一份），落盘结果在 `verdict_written` 里；"
             "status 的键是八格检查（paper/contradictions/load_bearing/report_shape/"
             "user_pending/substance/acceptance/artifact_ledger），值是三态之一（通过 / 拦住 / 没查成）；"
             "acceptance 那一格的 readings 里逐行给出：判据号、名称、受控档位、阈值、"
             "台账现算值、是否满足（不满足的那几行同时进 findings）；"
             "**读不懂的行**各自带 `state=\"unreadable\"` + `reason`（空 id / id 重复 / 词表外的 kind / "
             "`na` 无理由 / 阈值不是整数 / 台账读不到），读数里另有 `rows_unreadable`（条数）与 "
             "`unreadable_rows`（逐条 id/kind/code/reason）—— `unreadable` 既不是通过、也不进未满足，"
             "它让**整格落 `unknown`**（绝不 `pass`）；读表那一层（`conductor.acceptance`）同样把这类行"
             "标 `unreadable` 并在 `problems` 里点名（两边同一处口径：`closing.acceptance_row_state`）；"
             "artifact_ledger 那一格的 readings 里给出对不上的行数与逐条说明；"
             "findings[] 每项是 {'check','code','level','detail'}；"
             "review_acceptance 是那一栏内容级验收读数："
             "{'passed','criteria','failed','auxiliary','auxiliary_note','readings','summary'}，"
             "criteria[] 每项是 {'key','name','state','detail'}（`key`/`name` 与顺序现取自 "
             "`reviewaccept.CRITERIA`，`state` 是三态之一），"
             "auxiliary[] 每项是 {'key','label','value'}（标签现取自 `reviewaccept.AUXILIARY_SIGNALS`，"
             "值只作辅助、一个都不参与 `passed`），"
             "auxiliary_note 就是那一句『辅助读数逐字禁止拿来当通过』的来源"
             "（`reviewaccept.ReviewAcceptance.to_dict` 的原话）"),
)
def conductor_closing(store, session=None, project_dir: str = "", report_path: str = "",
                      cap_usd: float | None = None, goal: str = "",
                      goal_met: bool | None = None, basis: str = "",
                      task_list: Any = None) -> ToolResult:
    """工具体：把收工门包成一次只读调用（判据在 `agentflow.closing`，这里不另写一份）。
    `session` 是装配期注入的「会话身份」（`draft/37` §63，修法 B）`session` = `{"root": <会话记录根>, "sid": <这一趟的会话号>}`，由
    `tools.build_registry(session_root=..., sid=...)` 放进装配依赖里。为什么不让工具体自己"猜"一个 sid：真机实测（第 11 趟 `real11`）主控在第 28 步调 
    `conductor.closing` 拿到 `can_close: true, failed: []`，而同一次运行外部带 `sid=real11` 的读数报 `failed: ['user_pending']` ——工具体此前按 
    `sid=None` 走到了缺省会话文件 `sessions/<今天>.jsonl`，而那一趟的提问落在 `sessions/real11.jsonl`。没注入时按 `closing.NO_SESSION` 传下去 ⇒ 那一格记 
    `unknown`（不是 pass，也不是"读今天那份"——三态纪律）。
    收工那一步也要看得见内容级验收（所有者 2026-10-07 裁定「题 13 选 B」）决定收工的人是主控，而"能不能交"有两层问法：收工门的八格问结构与凭据，`reviewaccept` 问同一份交付的内容层（定理台账有没有假设与出处、三态分
    支、成本上限、每跳的输入可读、附件诚实）。第二层此前只有 CLI 出口（`agentflow closing`）能看见，运行内的主控看不见 —— 于是它做收工决定时手里只有八格。
    为什么与 CLI 出口同形：两个入口读的是同一批入参（`project_dir` /`report_path` / `session_root` / `sid` / 成本上限），就该给出同一栏读数 ——判据名、判据顺序、辅助读数的标签与那句禁令
    全部现取自 `reviewaccept`（`CRITERIA` / `AUXILIARY_SIGNALS` / `to_dict`），本文件不抄第二份。
    `cap_usd` 不给时成本那一格是「没查成」而不是「通过」（与 CLI 那边的缺省一致）。
    收工由 M 判（业主 2026-10-09）「是否收工不要用机械判据，由 M 制定的目标是否达成为准」⇒ 本工具新增`goal` / `goal_met` / `basis` 三个入参：`can_close` 是 M 的判据，机器那八格退成读数
    （`status` / `machine_pass`），两者不一致时 `overrode` 逐格点名。 M 不给 `goal_met` ⇒ `can_close=false` + 「没人判过」的读数（不是「可以交」）。内容级验收（`review_acceptance`）
    照旧只是读数 —— 它从不参与 `can_close`，这一条从裁定题 13 起就没变过。
    判据由 M 在运行内给，而门还有运行外的出口（`agentflow closing` / 发布门）：两处必须得出同一个结论（`draft/37` §63 记过一次"运行内 `can_close=true`、外部 `failed=[...]`"的
    假绿）。所以 M 给判据的那一次调用把它落到`out/review/m-verdicts.jsonl`（append-only，取最后一行）—— 运行外那一趟没有显式入参时读它。门本身仍然只读：`check_closing` 不写任何东西，写这
    一笔的是本工具（M 的动作），落盘失败如实进 `verdict_written`。
    """
    if store is None:
        return fail("没有工作区 ⇒ 收工门没查成（不是「可以交」）", kind="no_store", can_close=False)
    from .. import closing as CL
    from .. import reviewaccept as RX

    sess = session if isinstance(session, Mapping) else {}
    session_root = str(sess.get("root") or "") or None
    sid = str(sess.get("sid") or CL.NO_SESSION)
    # 落盘先于读数：这一次调用给出的判据要能立刻被"运行外那一趟"读到。
    written: dict[str, Any] = {"tried": False, "ok": False, "why": "", "path": ""}
    if goal_met is not None or (task_list if isinstance(task_list, (list, tuple)) else None):
        # 落点的解析必须与门读侧同一条口径（`resolve_under_workspace`）：工具契约写的
        # 是"相对工作区"，而 `Path(".")` 是按进程当前目录解析的 —— 真机 t1v 就是
        # 这么把判据写到跑批的工作目录里去的（M 判了达成，而外部门说"没人判过"）。
        vroot = CL.resolve_under_workspace(store, str(project_dir or "")) or str(
            session_root or getattr(store, "root", "") or "")
        if vroot:
            written["tried"] = True
            written["path"] = str(CL.m_verdicts_path(vroot))
            okw, whyw = CL.write_m_verdict(vroot, goal=goal, met=goal_met, basis=basis,
                                           tasks=task_list or (), sid=str(sid or ""))
            written["ok"], written["why"] = bool(okw), str(whyw)
        else:
            written = {"tried": False, "ok": False, "path": "",
                       "why": "没有项目根/会话根 ⇒ 判据没落盘（运行外那一趟会读不到）"}
    rep = CL.check_closing(store, project_dir=project_dir, report_path=report_path,
                           session_root=session_root, sid=sid,
                           goal=goal, goal_met=goal_met, basis=basis,
                           task_list=task_list or ())
    data = rep.to_dict()
    # 内容级验收（§17.3）：同一批入参走只读入口 `reviewaccept.check_review`。
    # 它与收工门是同一份交付的同一个问题的两层，所以并排给出、各自三态。
    acc = RX.check_review(store, project_dir=project_dir, report_path=report_path,
                          session_root=session_root, cost_cap_usd=cap_usd, sid=sid)
    ra = acc.to_dict()
    kind = "" if rep.can_close else ("closing_unknown" if CL.tri_state_exit_code(rep) == 2
                                     else "closing_blocked")
    return ok({
        "can_close": data["can_close"], "machine_pass": data["machine_pass"],
        "m_verdict": data["m_verdict"], "overrode": data["overrode"],
        "verdict_conflicts": data["verdict_conflicts"],
        "verdict_note": data["verdict_note"],
        "verdict_written": written,
        "status": data["status"],
        "failed": data["failed"], "unknowns": data["unknowns"],
        "findings": data["findings"], "readings": data["readings"],
        "summary": rep.summary(),
        # 判据名与顺序现取自 `RX.CRITERIA`、辅助读数的标签现取自
        # `RX.AUXILIARY_SIGNALS`：与 CLI 出口同一处口径，本文件不写死任何一个名字。
        "review_acceptance": {
            "passed": ra["passed"],
            "criteria": [{"key": key, "name": name,
                          "state": ra["criteria"].get(key, "?"),
                          "detail": ra["details"].get(key) or ""}
                         for key, name in RX.CRITERIA],
            "failed": ra["failed"],
            "auxiliary": [{"key": key, "label": label,
                           "value": ra["auxiliary"].get(key)}
                          for key, label in RX.AUXILIARY_SIGNALS],
            "auxiliary_note": ra["auxiliary_note"],
            "readings": ra["readings"],
            "summary": acc.summary(),
        },
    }, kind=kind, blocked=not rep.can_close,
        blocker_count=len(rep.blockers), unknown_count=len(rep.unknowns))

#: 装配清单（`T-8`）：`(工具体函数, 需要从装配期注入的名字)`。
@tool(
    "conductor.status_report",
    "项目**状态报告**：只读收集当前情况（产出/交接/在飞卡点/被拒与插话）→ 落 `out/review/STATUS-<ts>.{md,json}`。"
    "用户问「现在什么情况」走它：不发 ask_user、不停别人的循环（**旁路观测**）。",
    {"type": "object",
     "properties": {"since": {"type": "string",
                              "description": "只统计这个 ISO 时间前缀之后的读数（如 2026-10-05）"},
                    "out_dir": {"type": "string", "description": "报告落哪个目录（缺省 out/review）"}},
     "required": [], "additionalProperties": False},
    side_effect="read",
    roles=("M",),
    returns=("{'ok','md','json','tables','manuscripts','in_flight','attack_rounds',"
             "'interjections','next_steps','note'}"),
)
def conductor_status_report(_conductor, since: str = "", out_dir: str = "") -> ToolResult:
    """工具体：只读收集 + 落盘，并把四类读数回给主控（实现只有一份：`statusreport`）。"""
    from .. import statusreport as SR

    c = _conductor()
    root = Path(str(getattr(getattr(c, "store", None), "root", "") or "."))
    report, md, js = SR.write_status_report(
        getattr(c, "store", None), root, out_dir=(out_dir or None), since=since)
    data = {
        "ok": True, "md": str(md), "json": str(js),
        "tables": report["tables"], "manuscripts": report["manuscripts"],
        "in_flight": report["in_flight"], "attack_rounds": report["attack_rounds"],
        "interjections": report["interjections"], "next_steps": report["next_steps"],
        "note": ("这份报告是旁路观测：只读台账与手稿、零模型调用；"
                 "报告本身落在 out/review/ 下（那是产物，不是台账）"),
    }
    return ok(data, **data)


@tool(
    "conductor.board",
    "只读：板上还挂着什么。一行 = 一个工作项（`tasks` 里 `kind` 非空）；`expects=ack` 确认读过算完，`expects=work` 要交付算完。",
    {"type": "object",
     "properties": {"limit": {"type": "number", "description": "最多列几项（默认 20）"}},
     "required": [], "additionalProperties": False},
    side_effect="read",
    roles=("M",),
    returns="{'checked','open_items','open_count','readings'}",
)
def conductor_board(_conductor, limit: int = 20) -> ToolResult:
    """工具体：转发 `Conductor.board_view`（工具只做适配层，权限判定不在这一层）。

    "读不成"必须显式报错而不是回一个空板：`checked=False` 说明没查成，
    而"板上没事"是 `checked=True` 且 `open_count==0` —— 这两件事折平就是本仓最忌的形态。
    """
    view = _conductor().board_view(limit=int(limit))
    if not view.get("checked", False):
        raise ToolError(f"板读不成：{view.get('reason') or '未知原因'} ⇒ 这是『没查成』，"
                        "不是『板上没事』")
    return ok(view, **view)


@tool(
    "conductor.broadcast",
    "给我名下**直接子代理**广播一条通告（每个收件人一条 ack 板项）。级联由收件人做、框架不代转；没有子代理时如实报『**没有收件人**』。",
    {"type": "object",
     "properties": {"subject": {"type": "string", "description": "一句话标题"},
                    "body": {"type": "string", "description": "正文（进板项的 detail）"}},
     "required": ["subject"], "additionalProperties": False},
    side_effect="write_local",
    # 所有角色 + 主控：T21 逐字「这个子代理广播对 M 也是完全一样的做法」
    # （`S.ROLES` 不含主控 ⇒ 单独并上它）。
    # 只读角色（C/H/V）不声明 —— 比"声明了再让 `for_role` 剥掉"更干净：
    # 后者会被 `cli tools` 报成"声明错误"（`role_filter_notes` 非空），
    # 而那份说明里逐字写着"行为上已被拦下，但声明本身应改"。
    roles=tuple(r for r in S.ROLES if r not in READ_ONLY_ROLES) + (S.CONDUCTOR_ROLE,),
    returns="{'checked','ok','broadcast','recipients','items','cascade','readings','note'}",
)
def conductor_broadcast(_conductor: Any, subject: str, body: str = "") -> ToolResult:
    """工具体：转发 `Conductor.broadcast`。

    "我是谁"从调用上下文里读（`current_task_id()` / `current_caller_role()`）——
    工具的形状里没有这一格，而只有循环知道它（`AgentLoop._do_tool` 用 `calling_as` 挂上）。
    挂不上 ⇒ `broadcast` 自己会受控拒绝（三态：不许猜一个父号），这里不替它猜。
    """
    got = _conductor().broadcast(subject=subject, body=body,
                                 by=current_caller_role() or S.CONDUCTOR_ROLE,
                                 parent_task_id=current_task_id())
    if got.get("ok") is False:
        raise ToolError(str(got.get("error") or "广播没成"))
    return ok(got, **got)


#: 上行成功那一支里不属于载荷的两格（`data` 里不给，`meta` 里照旧给全）：
#:
#: - `addressing`：`_escalation_roster_check` 的原样读数（`checked` / `how` / `kind` /
#:   `error` / `candidates` …）—— 它回答的是「这个编号是怎么被认成父的」；
#: - `roster_unavailable`：上一条派生出来的三态位（名册没读成 ⇒ 按运行期解析的父投递）。
#:
#: 为什么要分出来（2026-10-21，判据 `test_no_tool_returns_a_top_level_key_it_does_not_declare`）：
#: 这两格是框架读数，不是这次上行的载荷；`returns=` 声明的就是 `data` 的键集合
#: （同一张面的先例：`conductor.broadcast` 的 `returns` 与它的 `data` 逐键相同）。
#: 读数一个字都没少：`ok(payload, **got)` 的 `**got` 把它们留在 `meta` 里，而 `meta`
#: 整格都渲染进模型看到的那条工具结果（`agent_loop._flatten_one_level` 只摊平 `data`，
#: `meta` 原样保留）⇒ 「模型不知道这两格存在」这个后果不会发生。
#: 为什么不反向补进 `returns=`：那会让工具面与冻结快照
#: （`tests/golden/tool_surface_snapshot.json`，FC-27 禁改区）不一致，重冻必须由人逐格看过。
_ESCALATE_READING_KEYS: tuple[str, ...] = ("addressing", "roster_unavailable")


@tool(
    "conductor.escalate",
    "把「我需要召唤者做什么」写进**父代理的收件箱**并让本趟以 stop_reason=escalated 收工"
    "（子代理跑到一半卡住时用它，别靠返回值等下一轮、也别借别人的边绕）。"
    "收件人=运行期解析出的召唤者，**不要求**在 `edges` 里登记。"
    "顶层（没有召唤者）会被受控拒绝 `not_caller`，一行都不写。",
    {"type": "object",
     "properties": {
         "need": {"type": "string", "minLength": 1, "maxLength": 300,
                  "description": "一句话说清要父代理做什么（≤300 字）"},
         "kind": {"type": "string", "enum": list(ESCALATE_KINDS),
                  "description": ("哪一类：" + " / ".join(ESCALATE_KINDS))},
         "evidence": {"type": "array", "items": {"type": "string"}, "maxItems": 20,
                      "description": "哪些台账 id 需要它（`lit:` / `stmt:` / `exp:` 等，可空）"},
     },
     "required": ["need", "kind"], "additionalProperties": False},
    side_effect="read",
    # 所有角色 + 主控（业主 2026-10-19：亲子天然双向，上行不是权限面的一条边）。
    # 只读角色（C/H/V）「也」要拿到它 —— 这一点由 `side_effect="read"` 保证：
    # `write_local` 会在 `for_role` 里被结构性剥掉。为什么"声明 read"是如实的而不是取巧：
    # 它不写任何数据表、也不改工作区里任何产物，只把一条「通信记录」追加进会话
    # （与 `message` / `note` / `ask_user` 三个循环形态同一个平面 —— 那三个 C/H/V 本来就有）。
    # 同一口径的既有先例：`verify.verify_proof` 也写 `verifications/<命题号>.jsonl`
    # 却声明 `read`，理由逐字是"V 不写表"。
    roles=tuple(S.ROLES) + (S.CONDUCTOR_ROLE,),
    returns=("{'checked','ok','state','to','to_task_id','need','kind','evidence',"
             "'msg_id','reason','error','note'}"),
)
def conductor_escalate(_conductor: Any, need: str, kind: str,
                       evidence: list | None = None) -> ToolResult:
    """工具体：转发 `Conductor.escalate`（判据在 `conductor.py`，这里不另写一份）。

    "我的召唤者是谁"与"这条留言该落进哪个会话"从调用上下文里读
    （`current_parent()` / `current_session()`）—— 工具的形状里没有这两格，
    而它们只有循环知道（`AgentLoop._do_tool` 用 `calling_as(...)` 挂上）。

    成功 ⇒ `ok(state="escalated")`：循环见到 `data.state` 就把这一趟收成
    `stop_reason="escalated"`（退出码 5）。受控拒绝 ⇒ `fail(kind=<理由码>)`：
    `not_caller`（没有父）「不会」停掉这一趟 —— 顶层 M 调错一次不该把自己停掉。
    """
    got = _conductor().escalate(
        need=need, kind=kind, evidence=list(evidence or ()),
        my_task_id=current_task_id(), by=current_caller_role())
    if not got.get("ok"):
        # 受控拒绝这一档的「理由码」放在 `meta.kind`（工具层统一的读法），
        # 而"哪一类需求"那一格改名成 `escalate_kind` 一并带回去。
        # 为什么不直接把 `got` 整个塞进 `fail(**got)`：`got` 里已经有 `error` 这个键，
        # `fail(error, **meta)` 会当场 TypeError（"got multiple values for argument"），
        # 于是拒绝变成 `kind="unexpected"` 的框架级失败 —— 理由码就此消失。
        meta = {k: v for k, v in got.items() if k not in ("error", "kind")}
        meta["kind"] = str(got.get("reason") or "escalate_refused")
        meta["escalate_kind"] = str(got.get("kind") or "")
        return fail(str(got.get("error") or "上行没成"), **meta)
    # 成功那一支：`data` 只给 `returns=` 声明过的那几格，名册寻址那两格留在 `meta`
    # （理由见 `_ESCALATE_READING_KEYS` 的注释）。
    payload = {k: v for k, v in got.items() if k not in _ESCALATE_READING_KEYS}
    return ok(payload, **got)


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
    # `draft/39` §4 的入口②：M 用 `conductor.status_report` 回答"现在什么情况"
    # （只读、零模型调用、不停任何循环）；用户侧入口①是 `agentflow status-report`。
    (conductor_status_report, ('_conductor',)),
    # 工作项板（业主 2026-10-08 裁 A1=甲、T16）：M 的编排面看"还挂着什么"。
    # A–H 的那一半在 `manuscript_tools`（`manuscripts.items` / `manuscripts.ack`）——
    # M 不进 `manuscripts.*` 的面是既有判据钉着的（`test_m_tool_surface_is_orchestration_only`）。
    (conductor_board, ('_conductor',)),
    # 广播（S6-b，业主 T20/T21）：一件能力、所有角色同一个做法（没有 tree 特权档）。
    # 收件人是"我名下的直接子代理"，而"我是谁"从调用上下文读（`AgentLoop._do_tool`
    # 用 `calling_as` 挂上）—— 拿不到就不广播（受控拒绝，不猜父号）。
    # 只读角色（C/H/V）由 `write_local` 在 `for_role` 里结构性剥离。
    (conductor_broadcast, ('_conductor',)),
    # 上行（业主 2026-10-19「父子天然双向」）：孩子的需求写进父的收件箱，本趟以
    # `stop_reason="escalated"` 收工。收件人是运行期解析出的召唤者，「不」在 `edges` 里登记。
    (conductor_escalate, ('_conductor',)),
)


def register(registry: ToolRegistry, *, store: Any = None, conductor: Any = None,
             role_registry: Any = None, policy: Any = None,
             session: Any = None,
             backend: Any = "local") -> list[str]:
    """把主控工具注册进 `registry`，返回注册的工具名列表。
    
    参数----store : Store | None 台账与状态视图的来源；不给时工具仍会注册，但一被调用就明确报"没有工作区"（没查成 ≠ 没有问题）。
    conductor : Conductor | None 现成的主控（不给就用 `conductor_for(store)` 按工作区取/建一个）。
    role_registry : Mapping | None`LocalBackend` 的角色接线（role -> 实例/工厂）；不给我方仍可派活，但被派的角色会以 
    `refused/not_wired` 如实落台账。 session : Mapping | None 这一趟的会话身份 
    `{"root": ..., "sid": ...}`，由`tools.build_registry(session_root=, sid=)` 注入；不给 ⇒
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

    # \T-8\：声明与工具体都在模块级（\@tool\ 写进 \fn.__tool_spec__\），
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


#: 验收表表头第一格认得的写法 —— 这是输入归一化的匹配表，不是受控词表
#: （别把它塞进 `tools/vocab_census` 的 reason/vocab 面：那是另一类东西；
#:  反过来，改这张表也不等于改判据 —— 判据是"这一行读得懂读不懂"这件事本身）。
_ACCEPTANCE_HEADER_ALIASES: tuple[str, ...] = ("判据", "编号", "id", "序号", "检查", "项")
#: 结论格认得的写法（同上：匹配表，不是词表）。
#:
#: 顺序是判据的一部分："不成立"必须先于"成立"判 —— `"成立" in "不成立"` 会把
#: 不成立读成成立（2026-09-29 实测：验收表里 P10/P11 写着「不成立」，解析出来却是 10/10 成立）。
_ACCEPTANCE_NOT_OK_ALIASES: tuple[str, ...] = ("不成立", "未通过", "不通过", "失败",
                                               "fail", "no", "false", "✗", "×", "否")
_ACCEPTANCE_OK_ALIASES: tuple[str, ...] = ("成立", "通过", "pass", "ok", "yes", "true",
                                           "✓", "√", "是")


def _acceptance_verdict(cell: str) -> tuple[bool | None, str]:
    """结论格 → `(ok, reason)`：读得懂时 `reason` 空；读不懂时 `ok is None`。

    默认方向写死：认不出来一律当"读不懂"，永不猜成"成立" ——
    下游拿这个结论去算"这一格算不算通过"，而猜错的方向只有一个（假绿）。
    """
    text = str(cell or "").strip()
    if not text:
        return None, "结论格是空的"
    lowered = text.lower()
    if any(a in text for a in _ACCEPTANCE_NOT_OK_ALIASES) or lowered in ("fail", "failed", "no",
                                                                        "false"):
        return False, ""
    if any(a in text for a in _ACCEPTANCE_OK_ALIASES) or lowered in ("pass", "passed", "ok",
                                                                    "yes", "true"):
        return True, ""
    return None, (f"结论格 {text!r} 认不出来"
                  "（认得的写法写在 `_ACCEPTANCE_OK_ALIASES` / `_ACCEPTANCE_NOT_OK_ALIASES` 两处）")


def _acceptance_header_cells(cells: list[str]) -> bool:
    """这一行是不是验收表的表头（第一格认得出来，且至少有四栏）。"""
    if len(cells) < 4:
        return False
    first = cells[0].strip().lstrip("#").strip()
    return first in _ACCEPTANCE_HEADER_ALIASES or first.lower() in _ACCEPTANCE_HEADER_ALIASES


def _parse_acceptance(path: Path, *, max_chars: int = 60) -> dict[str, Any]:
    """把验收表（markdown）解析成结构化的行。
    认的是项目脚本自己的写法：一行标题（含「P1–P11」之类）、一行结论（`结论：「全部成立」（10/10）`）、一张四栏表（默认表头 `| 判据 | 名称 | 结论 | 读数 |`）。
    ## 表头与结论都归一化后再判（`draft/52` CC-02）
    真机里 8/54 行被读成 0 行的原因就是两张逐字判据：表头只认 `cells[0] == "判据"`、结论只认 `cells[2].strip() == "成立"` —— 表是人手写的，写法一换就整张表读不出来。现在：表头认 
    `_ACCEPTANCE_HEADER_ALIASES`、结论认两张别名表（不成立先于成立判）。
    ## 行状态的口径只有一处（`closing`）
    每一行的 `state` 由 `closing.acceptance_row_state` 给（词表是 `closing.ROW_STATES`）：本模块只做"这一行读不懂"这一个判断（空编号 / 编号重复 / 结论格认不出来），不
    抄第二份口径 —— 同一张表两种读法正是 CC-02 要治的形态。读不懂的行仍然出现在 `rows` 里（带 `state` 与 `reason`）并在 `problems` 里点名："读不出来"既不是 `0 行`、也不是 
    `不通过`（三态）。
    `max_chars` 是交付说明能不能逐条对齐的关键：真机实测（2026-09-29，只读重放）十行的完整读数合起来 >1400 字，工具结果被上下文预算截断，M 只看到 P1–P4，于是它如实写"P5–P11 未核到"。
    解析不出来时 `rows` 为空而 `problems` 非空 —— 空表与"解析失败"必须分得开。
    """
    # 行状态口径的唯一来源在 `closing`（`acceptance_row_state` / `ROW_STATES` /
    # `acceptance_kinds_with_state`）：此处只做"这一行读不懂"的判定、不抄第二份。
    # 惰性 import：只在真解析时付这个 import 的代价（与 `_agent_for` 同一风格），
    # 且 `closing` 不 import `tools/*` ⇒ 这条边不成环。
    from .. import closing as CL

    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    title = next((ln.lstrip("# ").strip() for ln in lines if ln.startswith("#")), "")
    conclusion = next((ln.strip() for ln in lines if ln.startswith("结论")), "")
    rows: list[dict[str, Any]] = []
    problems: list[str] = []
    truncated = 0
    in_table = False
    seen_ids: set[str] = set()
    for ln in lines:
        if not ln.startswith("|"):
            in_table = False
            continue
        if set(ln.strip()) <= set("|-: "):
            continue
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        if not in_table:
            if _acceptance_header_cells(cells):
                in_table = True
            continue
        if len(cells) < 3:
            cells = cells + [""] * (3 - len(cells))
        rid = cells[0].strip()
        name = cells[1] if len(cells[1]) <= 30 else cells[1][:30] + "…"
        ok, reason = _acceptance_verdict(cells[2])
        if not rid:
            reason = "这一行没有编号（读数没法与表上那一行对上）"
        elif rid in seen_ids:
            reason = f"编号 {rid!r} 在同一张表里重复（读数无法归属）"
        seen_ids.add(rid)
        raw_reading = cells[3] if len(cells) > 3 else ""
        reading = raw_reading
        if max_chars > 0 and len(raw_reading) > max_chars:
            reading = raw_reading[:max_chars] + "…"
            truncated += 1
        row: dict[str, Any] = {"id": rid, "name": name,
                               "ok": (None if reason else ok),
                               "reading": reading, "reading_chars": len(raw_reading)}
        if reason:
            row["state"] = "unreadable"     # 这一档的判定在本模块；词表在 `closing`
            row["reason"] = reason
        row["state"] = CL.acceptance_row_state(row)
        rows.append(row)
    if not rows:
        problems.append("验收表里一行判据都没解析出来（表头认得「判据 / 编号 / id / 序号」吗？）"
                        "—— 0 行**不等于**里面的判据都通过")
    unreadable = [r for r in rows if r["state"] == "unreadable"]
    if unreadable:
        listed = "；".join(f"{r['id'] or '（无编号）'}：{r['reason']}" for r in unreadable[:4])
        problems.append(f"有 {len(unreadable)} 行**读不懂**（既不是「0 行」，也不是「不通过」）：{listed}")
        kinds = sorted(k for k in CL.acceptance_kinds_with_state(rows, "unreadable") if k)
        if kinds:
            problems.append(f"读不懂的行涉及的 kind：{kinds}")
    ok_count = sum(1 for r in rows if r["ok"] is True)
    not_ok_count = sum(1 for r in rows if r["ok"] is False)
    return {"found": True, "path": str(path), "title": title, "conclusion": conclusion,
            "rows": rows, "row_count": len(rows), "ok_count": ok_count,
            "not_ok_count": not_ok_count, "readings_truncated": truncated,
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
        # 2026-10-19（业主裁定「父子天然双向」）：`conductor.escalate` 不是主控工具，
        # 它是「上行通道」（孩子跟召唤它的人说话），只读角色必须有 —— 见 `register`
        # 那一行的 `roles=` 与 `side_effect="read"` 的理由。除了它，一件都不许漏过去。
        if spec.name == "conductor.escalate":
            continue
        problems.append(f"只读角色 C 拿到了主控工具 {spec.name}")
    if "conductor.escalate" not in {s.name for s in reg.for_role("C")}:
        problems.append("只读角色 C 没拿到 conductor.escalate（上行通道对所有角色都要开）")
    if problems:
        for p in problems:
            print(f"[conductor_tools] {p}")
        return 1
    print(f"[conductor_tools] 自检通过：{len(names)} 件编排面工具，只有主控拿得到")
    return 0


__all__ = ["conductor_for", "reset_cache", "register", "selftest", "NotWiredError"]

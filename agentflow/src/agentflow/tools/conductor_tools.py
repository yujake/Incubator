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
from ..conductor import (AGENT_STATE_SILENT, AGENT_STATE_UNKNOWN,
                         DEFAULT_FANOUT_WAIT_SEC, ESCALATE_KINDS,
                         RETIRE_REFUSAL_TARGET_NOT_SILENT, Conductor, NotWiredError,
                         SummonResult, current_caller_role, current_session,
                         current_task_id, retire_refusal)
from . import (READ_ONLY_ROLES, UNIVERSAL_TOOLS, ToolError, ToolRegistry, ToolResult, fail,
               is_universal_tool, ok, tool)

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
            # ---- 名册那三格（2026-10-21 真机缺陷的读数面）：主控自己就是"派活的人"，
            # 它要能读回"这一条进名册没有、叫什么、没进的理由是什么"。改前这里一个字都
            # 没有，而真机 `projects/p3-verify` 恰恰就是主控用这个工具派的活 ⇒ 名册空了
            # 也没人读得出来（`roster_considered` 回答"走没走过漏斗"，是第三态）。
            "roster_name": str(getattr(res, "roster_name", "") or ""),
            "roster_problem": str(getattr(res, "roster_problem", "") or ""),
            "roster_considered": bool(getattr(res, "roster_considered", False)),
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
            "target_role": {"type": "string", "description":
                            "被召唤的角色代号（能不能派它、你有哪些出边，见伙伴表）"},
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
             "'roster_name','roster_problem','roster_considered',"
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
                              input_key=input_key,
                              # 父必须是"发起这一趟的绝对编号"（与 `conductor.summon_many`
                              # 那一处同一条口径，2026-10-20 修孤儿行时补的）：改前这一格
                              # 缺 ⇒ 每条工具派出去的子行 `parent_task_id=None`，于是它既
                              # 不在任何人的名册上、也不占任何父的扇出。号从调用上下文
                              # 读（`calling_as` 挂上的就是这一趟的 `task_id`），不在这里拼。
                              parent_task_id=current_task_id() or None,
                              # 名册登记要用的任务原文：登记发生在 `summon` 的 [5b]，
                              # 简介没写时由秘书据它代写并留痕（2026-10-20 裁定）。
                              roster={"task": str(task)})
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
                        "target_role": {"type": "string", "description":
                            "被召唤的角色代号（能不能派它、你有哪些出边，见伙伴表）"},
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
             "'children','roster_name','roster_problem','roster_considered'}"),
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
            # 名册登记要用的那两格（2026-10-21）：`task` 是这一项自己的那句活，
            # `brief` 如果模型给了就原样带（工具的 schema 里没有 `brief` 这一格 ——
            # 那是形状面 `summon_many` 的；这里容忍它存在，给了就用，没给由秘书代写）。
            roster={"task": work, "brief": str(item.get("brief") or "")},
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
             "'task_count','silent_children','silent_children_checked',"
             "'silent_children_reason'}；relays[] 每项含 role / wants_role / wants_action / "
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
    # 交过差的那一批（父据此把它们记为静默）：`Conductor.handoffs_reading` 的唯一读侧入口。
    # 不给 parent ⇒ 读整本交差账（谁向谁交的都算），因为台账视图回答的是"这一趟共几个人
    # 安静了"，不是"我名下几个安静了"（后者用 `conductor.watch` 的同一格，那一个是逐支的）。
    try:
        hand = c.handoffs_reading("")
        payload["silent_children"] = [str(x) for x in (hand.get("silent") or ())]
        payload["silent_children_checked"] = bool(hand.get("checked"))
    except Exception as exc:  # noqa: BLE001 - 读不成是"没查成"，不是"没人交差"
        payload["silent_children"] = []
        payload["silent_children_checked"] = False
        payload["silent_children_reason"] = f"{type(exc).__name__}: {exc}"
    payload.setdefault("silent_children_reason", "")
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
        from .. import clock as CLK

        t0 = time.monotonic()
        while c.cancel_inflight() and (time.monotonic() - t0) < float(drain_sec):
            # 2026-10-25 业主裁定「主时钟要控制所有计时类工作」：优雅停止的排水轮询
            # 原来是就地 `time.sleep(0.05)`（不在任何账上）。它现在走 `await_io`：
            # 仍然真睡 0.05 秒、仍然每拍看一次"还有没有在飞的"，只是这一次等待记进
            # `out/clock/waits.json`（`kind="drain"`）。这也是代理可见面上最后
            # 一个"自己计时"的入口 —— 它进账之后，计时只剩主时钟这一处。
            CLK.await_io(0.05, "等正在跑的活收工（优雅停止）",
                         kind="drain", where="conductor.stop")
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
    "某角色的描述（不是它的工具面）：role、summonable（你能不能直接派它），外加职责 / 交付物 / 边界 / "
    "政策 / 立场 / 签名错六格；不给它的动作表，也不给它今天的工具名。派活前用它确认『这个角色是干什么的』；"
    "与声明层同源。",
    {
        "type": "object",
        "properties": {"role_name": {"type": "string", "description": "角色名（A–H / V / L）"}},
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
    from .. import leanscope as _LEANSCOPE

    # 业主 2026-10-22（「在Lean开关没开时隔绝L」）：按名取一个"这一档下不存在"的角色
    # 不给描述，也不给空壳（给空壳等于告诉模型"这个人存在、只是没内容"）。拒绝形状是
    # 受控的：`ok=False` + 理由码（`lean_off` / `lean_unreadable`）+ 开关读数六格。
    if _LEANSCOPE.is_hidden(role_name):
        payload = _LEANSCOPE.hidden_refusal(role_name, surface="conductor.role_spec")
        return ToolResult(False, payload, str(payload["error"]), payload)

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
    # ---- D-38 C（2026-10-24）：论文包缺对应表时，M 手里的验收表要能读到这件事。
    #
    # 为什么要接到这里：D-38 两趟真机的 out/paper 里只有两份验收表，M 读验收表时
    # 看不到"论文欠一张对应表"这一项 —— 于是它在验收表里连那一行都不会写。判据与
    # 收工门那一格共用同一处实现（`closing.mapping_absence_reading`），这里只把
    # 结论翻成一句 M 能照写的话；表在盘上时这句话不出现（不是一句恒真的提示）。
    if store is not None:
        try:
            written = CL.mapping_absence_reading(store, base)
        except Exception as exc:  # noqa: BLE001 - 没查成也要说出来，不许静默当成"表在"
            got["problems"] = list(got["problems"]) + [
                f"论文对应表这一项没查成：{type(exc).__name__}: {exc} ⇒ 验收表里那一项记"
                "「未核到」，不许记「成立」"]
        else:
            if written.get("missing"):
                got["problems"] = list(got["problems"]) + [
                    f"论文包里没有 {written['mapping_json']}（有 "
                    f"{written['statements']} 条命题、{written['documents']} 份稿件）⇒ "
                    "验收表里「论文对应表」那一项记「未完成」；缺对应表 ⇒ 论文无法从稿件"
                    "追溯到台账（不许记 `na`、也不许把那一行省掉）"]
    # ---- D-38 第二步（2026-10-24）：机器可判那一份里「论文对应表」这一档的三种形态。
    #
    # 为什么接在这里：M 写两张表（人读的 ACCEPTANCE.md 与机器可判的
    # ACCEPTANCE-CHECKS.json），而这一档此前只有人读那张能表达「未完成」。
    # 三种形态都要读得出来，且老工作区不因为门加了一档而变红：
    #   - 机器表里那一行缺失（老工作区）⇒ 读成「没查成」（unknown），不判红，点名请 M 补；
    #   - 机器表里记了 na + 理由 ⇒ 不适用（na 不是通过，也不是失败）；
    #   - 人读表里那一行记「未完成」⇒ 它没过（解析器已读成 ok=False）。
    # 判据本体在 `closing`（`paper_mapping_cell_reading` / `acceptance_absent_kind_state`）；
    # 这里只读表、只把结论翻成一句 M 能照写的话。没有那份机器可判文件时一言不发
    # （那一趟没走机器可判那一档，由收工门自己判，不在这里补噪音）。
    got["problems"] = list(got["problems"]) + _paper_mapping_leg_problems(
        base, [r for r in got["rows"] if isinstance(r, Mapping)])
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
             "'interjections','next_steps','child_wait_invariant','note'}；"
             "child_wait_invariant 是不变量『活跃子代理 ⇒ 必有一条等它的计时器』的读侧判据"
             "（逐趟给 by_parent / unwaited / problems）"),
)
def conductor_status_report(_conductor, since: str = "", out_dir: str = "") -> ToolResult:
    """工具体：只读收集 + 落盘，并把四类读数回给主控（实现只有一份：`statusreport`）。"""
    from .. import statusreport as SR

    c = _conductor()
    root = Path(str(getattr(getattr(c, "store", None), "root", "") or "."))
    report, md, js = SR.write_status_report(
        getattr(c, "store", None), root, out_dir=(out_dir or None), since=since)
    # 不变量（活跃子代理 ⇒ 必有一条等它的计时器）的读侧判据：逐趟给。
    # 这一格是"这条不变量今天成不成立"唯一会被真机念出来的地方 —— 缺了它，
    # `child_wait_invariant` 就只在测试里活（2026-10-27 补线）。
    try:
        top = [r for r in c.tree() if not str(r.get("parent_task_id") or "")]
        invs = [c.child_wait_invariant(str(r.get("task_id") or "")) for r in top]
    except Exception as exc:  # noqa: BLE001 - 读不成是"没查成"，不是"不变量成立"
        invs = [{"checked": False, "parent": "", "active_children": [], "waited": {},
                 "unwaited": [], "problems": [], "reason": f"{type(exc).__name__}: {exc}"}]
    data = {
        "ok": True, "md": str(md), "json": str(js),
        "tables": report["tables"], "manuscripts": report["manuscripts"],
        "in_flight": report["in_flight"], "attack_rounds": report["attack_rounds"],
        "interjections": report["interjections"], "next_steps": report["next_steps"],
        "child_wait_invariant": {
            "checked": all(i.get("checked") for i in invs) if invs else False,
            "by_parent": {str(i.get("parent") or ""): {
                "checked": bool(i.get("checked")),
                "active_children": list(i.get("active_children") or ()),
                "unwaited": list(i.get("unwaited") or ()),
                "problems": list(i.get("problems") or ()),
                "reason": str(i.get("reason") or ""),
            } for i in invs},
            "unwaited": sorted({t for i in invs for t in (i.get("unwaited") or ())}),
            "problems": [p for i in invs for p in (i.get("problems") or ())],
        },
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


# ---------------------------------------------------------------- 销号（父发起，秘书落实）

#: `conductor.retire_child` 的三态（`state` 那一格）：可销 / 不可销 / 读不到。
#:
#: 为什么是三档而不是一个布尔：`Conductor.retire_ready` 与 `Secretary.retire` 各自都已经是
#: 三态的（`checked` 位），折成一个 `retired: bool` 会让「台账 / 名册读不出来」与「它还在飞」
#: 在读数上长得一模一样 —— 而父下一步该做的事正好相反（前者要重读一次，后者要等）。
RETIRE_CHILD_STATES: tuple[str, ...] = ("retired", "refused", "unknown")


def _parent_roles() -> tuple[str, ...]:
    """谁拿得到 `conductor.retire_child`：能当父的那些角色（边表里有出边）。

    ## 为什么从边表派生，而不是手写一份清单
    「谁能当父」的权威定义只有一处（`specs/<角色>.py` 的 `edges`，
    `capabilities.ALLOWED_EDGES` 是它的派生）。手写一份名单会在有人加边时静默漏掉那个角色，
    而漏掉的表现是"这个角色看不到销号工具" —— 它不报错，只会让那一支的名册越来越长
    （D-59 的原始症状：父从不给交完差的子销号）。

    ## 两处排除，都是结构性的、都登记在这里（不是遗漏）
    - `C` 没有出边（它不召唤任何人）⇒ 它当不了父，销号工具对它没有对象；
    - 只读角色（`C` / `H` / `V`）拿不到写工具 —— `ToolRegistry.for_role` 按
      `SIDE_EFFECTS_WRITE` 结构性剥离。本件落 `out/roster/*.jsonl`、并在台账里记一笔消边，
      是真写，所以它不能挂在只读角色面上（`AGENTS.md` 第七类：权限面被悄悄放宽 ⇒
      测试全绿、上线即越权）。「登记下来的缺口」：`H` / `V` 边表里有出边（`H→A/E/G`、
      `V→F`），它们名下若有子代理，本工具不是它们的销号入口 —— 那件事要由人（或一次
      明确放宽只读角色写面的裁定）来处理，而不是在这里静默抹掉。
    """
    from .. import specs as _specs

    return tuple(sorted(r for r, out in _specs.edges().items()
                        if out and r not in READ_ONLY_ROLES))


#: 拿得到销号工具的角色（`_parent_roles()` 的读数，声明期算一次）。
_PARENT_ROLES: tuple[str, ...] = _parent_roles()


def _roster_secretary(conductor: Any, store: Any) -> Any:
    """这一趟「写名册的那个秘书」（与 `Conductor._register_roster` 同一条取法）。

    取法三档，与名册登记那一处逐字对齐（`roster_sink` 优先，其次 `secretary`）：
    销号必须落在「同一份名册文件」上，否则 `retire_ready` 说"可销"、名册里却找不到那个名字
    （两处各读一份名册的形态）。两档都空 ⇒ 现造一个：`Secretary` 的构造零模型调用，
    只读 root 与 store（`Secretary._conductor` 会用它读台账）。

    现造那一条走 `secretary.for_role_wired` 而不是裸的 `Secretary(...)`
    （2026-10-26 真机 sylow5）：后者不传 `seam=` ⇒ 这一名秘书没有判断面，任何经它
    落下去的判词（今天还没有，命题同一性那条判定就在同一个构造点上）
    都会静默折成 `checked=False`。缝从哪来写进 `Secretary.model_source`
    （秘书档没配 key 时它连着"为什么没缝"）。
    """
    for attr in ("roster_sink", "secretary"):
        got = getattr(conductor, attr, None)
        if got is not None:
            return got
    from ..secretary import for_role_wired as _secretary_wired

    root = getattr(store, "root", None) or getattr(conductor, "root", None) or "."
    # `for_role` / `for_role_wired` 都是模块级函数（`secretary.*`），不是 `Secretary` 的
    # 方法。写成 `Secretary.for_role(...)` 会在"两档都没接"这条回退路上抛
    # AttributeError，而那条路只有装配没接 `roster_sink` / `secretary` 时才走到 ——
    # 于是它一直没人发现，直到 `tests/test_tools_returns_declaration.py` 用一个裸
    # `Conductor` 探针调到这里。
    return _secretary_wired(str(current_caller_role() or S.CONDUCTOR_ROLE),
                            root=root, store=store)


@tool(
    "conductor.retire_child",
    "给一个已经交差、你不会再用到的子代理销号（退役）：判定与落盘都在秘书那一侧"
    "（`Secretary.retire` 那一步，不是工具名），本工具只做「父发起 → 秘书落实」这条链。"
    "child_name 给它的名册名（如 D1 —— 名册名才是父子之间的指称）；reason 写为什么销它，"
    "原样落进名册/销号名单。task_id 是旧的兼容写法（只收绝对编号，读数里标 task_id_compat）"
    "⇒ 新写的一律用 child_name。级联：它名下那一支会从最深的开始一起销号（先叶子后父），"
    "而子树里有任何一个节点还在活跃（自己在跑，或它的下级在跑）⇒ 整笔受控拒绝、"
    "一处都不销，并在 active_nodes / busy_task_ids 里点名是谁卡在哪件任务上。"
    "销号前置：它名下的板项必须已经清干净（queued / seen 都算没清）—— 不清就受控拒绝，"
    "先把那些项逐条处置掉再来销（没读的东西不许跟着名字一起销掉）。"
    "第二道前置（业主 2026-10-26：「销号可以也只可针对静默子代理」）：目标此刻必须是静默的"
    "（无工作、无任何计时器、无活跃子代理）—— 在飞 ⇒ 拒（销号等于把它手上的活扔掉）、"
    "待机 ⇒ 拒并逐条列出它挂的计时器（它还会醒过来）、读不到时钟/名册 ⇒ 一律拒"
    "（fail-closed）；这三种都带 refusal_code=target_not_silent 与 blocking。"
    "三态：可销 ⇒ state=retired；不可销（还在飞 / 待机 / 名下还有未消的板项 / "
    "不在你的名册里）⇒ state=refused 并在 missing 里点名缺什么；台账或名册读不出来 ⇒ "
    "state=unknown（不猜）。销号 ≠ 停止：要它立刻停下来用叫停/停止，销号说的是"
    "「它交完了、名字永久不复用」。",
    {"type": "object",
     "properties": {
         # 为什么这一格叫 `child_name` 而不是 `name`：`ToolRegistry.call(name, ...)` 的首个形参
         # 就叫 `name`，而 `agent_loop._do_tool` 把模型给的 args 摊成关键字传进去
         # ⇒ 形参叫 `name` 会撞成 `TypeError: call() got multiple values for argument 'name'`。
         # 那正是"模型写的名字对、工具本身没问题、却拿到工具层抛错"的形态（2026-10-26 实测）。
         # 所以正路是 `child_name`；`name` 只作为兼容别名收（按映射整体传入时才走得到），
         # 读数里用 `addressed_by` 记这一次是按哪一格指称的。
         "child_name": {"type": "string", "minLength": 1, "maxLength": 32,
                        "description": "子代理的名册名（如 `D1`；来自 {\"roster\": {\"of\": \"self\"}}）"},
         "reason": {"type": "string", "maxLength": 300,
                    "description": "为什么销它（一句话，逐字落进名册与销号名单）"},
         "task_id": {"type": "string", "minLength": 6, "maxLength": 8,
                     "description": "旧的兼容写法：子代理的绝对编号（新写的一律用 child_name）"},
     },
     "required": [],
     "additionalProperties": False},
    side_effect="write_local",
    roles=_PARENT_ROLES,
    returns=("{'checked','state','retired','task_id','name','parent_task_id','branch',"
             "'task_id_compat','addressed_by',"
             "'open_items','missing','reason','note','retired_path','roster_retired',"
             "'subtree','subtree_size','order','cascade','retired_count','unrostered',"
             "'active_nodes','busy_task_ids','readings','child_count',"
             "'active_child_count','target_state','target_state_label','blocking',"
             "'refusal_code'}；"
             "open_items 是列表（没销成时才非空），每项给 task_id / kind / item_state / "
             "summary 四格 —— 那四条键名刻意不写进键集合：空列表时一个都观测不到，"
             "写进去会让『声明 ⊆ 实跑』在受控拒绝那一支假红；"
             "target_state 是目标此刻的三态（flying / standby / silent / unknown）—— "
             "空串只有一个意思：三态还没读到（早拒支：没有台账号 / 没给 store / 台账或名册对照表"
             "读不成 / 名册里没这个名字 / 不是你的子代理 / 没点名 / 子树或活跃读数没读成），"
             "**不是**「它是静默的」；target_state_label 是它的中文标签（空串同此一条），"
             "blocking 是逐条『为什么还不能销』（kind=working / waiting / unknown；"
             "target_state 是空串时它也是空表）；"
             "refusal_code 的充要条件：静默闸（三态读数）说话的每一档必带 target_not_silent —— "
             "在飞 / 待机 / 三态读不到 / 名下还有活跃子代理 / 子树里还有活跃节点（含写盘前逐节点复核）；"
             "其余每一档都不带、是空串：早拒支（三态还没读）与板项没清那一档（读到了三态，"
             "但拦它的是板项，不是「不静默」）；"
             "cascade 是按销号次序排的逐项读数（task_id / name / role / depth / state），"
             "order 是本次的销号次序（最深的在前），active_nodes 是拒绝时点名的活跃节点"),
)
def conductor_retire_child(_conductor: Any, store: Any, child_name: str = "",
                           task_id: str = "", reason: str = "",
                           name: str = "") -> ToolResult:
    """工具体：父发起、秘书落实（三分支的判定在 `Secretary.retire`，本层不另写一份）。

    ## 三态为什么都在 `ok(...)` 里（不是 `fail`）
    `state` 就是这次销号的结论，而三档都要「带同一套键」回去（`returns=` 声明的是 `data` 的键
    集合，同一张面的先例：`formal.record` 把受控拒绝放在 `refused` 格子里而不是 `data=None`）。
    `state=refused` / `unknown` 不是工具故障：模型下一步该做的是"等它跑完/别销它"或"重读一次"，
    那些判断需要 `missing` / `branch` 这几格，`fail` 会把它们全吞掉。

    ## 判定次序（先读得到，再判得了，最后才是"能不能销"）
    1. 我是谁（`current_task_id()`：父的台账号 = 名册的 owner）；
    2. 台账读得出来吗 ⇒ 读不出来一律 `unknown`（不许折成"它不在飞"）；
    3. 这一行是不是我的子代理（`parent_task_id` 必须是我；板项行不是代理）；
    4. 子树与销号次序（`Conductor.subtree_postorder`：从最深到最浅，先叶子后父）；
    5. 子树里有没有还在活跃的节点（`Conductor.active_in_subtree`，含"在等"的向上继承）
       —— 有就整笔拒绝并点名"谁卡在哪件任务上"；
    6. 三态读数（`Conductor.retire_state_of`）：板项闸先说话（最具体的那一条），
       然后才是静默闸 —— 在飞 / 待机 / 读不到三档各自拒绝；
    7. 逐项核：未消的板项（每一项都要核）、`retire_ready` 的三分支、名册名、
       整支每个节点的三态（写盘之前，一次快照）；
    8. 全过 ⇒ 按第 4 步的次序从最深的开始逐项交给秘书（一次也不许反序）。

    ## 级联（业主 2026-10-26）
    「销号时需保证被销号子代理无活跃子代理，且自动帮它的子代理销号（从最深的开始销号）」。
    所以销的不是一个名字，是它名下那一支：叶子先退场、父后走，次序落进 `order` 与 `cascade`
    两格（`cascade` 逐项带 `task_id` / `name` / `role` / `depth` / `state` / `why`）。
    「不许销一半」是这一条的另一半：第 5、6、7 步任何一项不过 ⇒ 整笔不动、一个字节都不落盘。
    销一半的形态很具体：叶子销了、中间那一层因为还有别的活跃孙代被拒 ⇒ 名册上剩下一个
    名字，而它名下的孩子已经不能寻址（父再也叫不醒它们）。写那一步自己炸了（磁盘坏了）时
    已经没有"不动"这条路可走，那时只能如实报 `unknown` 并把"已经销掉的是哪几个"端出来 ——
    那不是半笔销号，那是一笔事故。

    ## 两个读数（子代理数 / 活跃子代理数）
    报告里贴 `child_count`（名册里未销号的名册项数）与 `active_child_count`（其中工作没做完
    还在做的，含靠等下级才活跃的），口径只有 `Secretary.child_counts` 一处；外加 `readings`
    那一格（判据读数：`subtree_size` / `active_count` / `busy_task_ids` / 销号前后的两份名册
    读数）。拒绝时那两个数是"为什么这一笔不许销"的证据；成功时它们是销完之后的名册读数。

    ## 销号 ≠ 停止
    `conductor.stop` / 叫停是"让它此刻停下来"，销号是"它交完了、名字永久不复用"。
    两件事混起来的代价：把还在飞的子代理当成"已经结束"（活干到一半、名字已被销掉）。
    所以子树里只要还有活跃节点这一档就拒绝，并把它的状态与最近报告端回去。

    ## 只有静默可销（业主 2026-10-26：「销号可以也只可针对静默子代理」）
    静默 = 无工作 ∧ 无任何计时器 ∧ 无活跃子代理。三档拒信各自点名它现在在哪一档、
    为什么不能销：在飞 ⇒ 它还在干活（销号等于把它手上的活扔掉）；待机 ⇒ 它挂着 N 条
    计时器（逐条给目的与到点时刻），它还会醒过来；未读到 ⇒ 读不到它是不是静默，
    一律不许销（fail-closed）。拒信用 `refusal_code=target_not_silent` 与
    `blocking`（kind = working / waiting / unknown）把这件事给机器读。

    ## 早拒支那两格怎么读（`target_state` 空串 / `refusal_code` 何时带）

    三态读数（判定次序第 6 步）之前的所有拒绝与「没查成」都还没读到 `target_state`
    ⇒ 它是空串、`target_state_label` 与 `blocking` 同为空表。空串只有一个意思：
    还没读 —— 它不是「它是静默的」，也不是「读不到」（读不到是 `state=unknown`
    且 `target_state=unknown`，那是读过了、读出了「不知道」）。

    `refusal_code` 的充要条件是「静默闸说话了」：目标不是静默的每一档（在飞 / 待机 /
    三态读不到 / 名下还有活跃子代理 / 子树里还有活跃节点，含写盘前逐节点复核）必带
    `target_not_silent`；其余每一档都是空串 —— 早拒支（三态还没读）与板项没清那一档
    （读到了三态，但拦它的是板项，不是「不静默」）都不带。

    ## 级联与静默的关系（业主同一批裁定的不变量）
    父代理还有活跃子 ⇒ 父非静默（有"等它的计时器"那条不变量）⇒ 父不许销 ⇒ 级联永远
    是"先子后父"，与既有的深→浅一致。这条不靠"遍历时对父特殊放行"实现：根那一项
    单独判静默，其余节点在写盘前用同一份三态读数逐项复核 —— 任何一个不静默的节点
    都让整笔一处不动。
    """
    c = _conductor()
    data: dict[str, Any] = {
        "checked": False, "state": "unknown", "retired": False,
        "task_id": str(task_id or ""), "name": str(name or child_name or ""),
        "parent_task_id": "",
        "branch": "", "open_items": [], "missing": [], "reason": "",
        "note": str(reason or ""), "retired_path": "", "roster_retired": False,
        "task_id_compat": False, "addressed_by": "",
        # 级联销号与两个读数的落点（业主 2026-10-26）。这些键在 `returns=` 里都声明了，
        # 所以每一条返回路径上都必须真的有它们 —— 声明 ⊆ 实跑是 `test_tools_returns_declaration`
        # 钉着的门（"声明了却没给"在本仓是红）。
        "subtree": [], "subtree_size": 0, "order": [], "cascade": [],
        "retired_count": 0, "unrostered": [], "active_nodes": [],
        "busy_task_ids": [], "readings": {},
        "child_count": None, "active_child_count": None,
        # 销号前置的读数（业主 2026-10-26：「销号可以也只可针对静默子代理」）：
        # 目标此刻的三态、逐条 blocking、以及受控拒绝的机器码。这三格在 `returns=`
        # 里都声明了，所以每一条返回路径上都必须真的有它们。
        "target_state": "", "target_state_label": "", "blocking": [],
        "refusal_code": "",
    }

    def _out(state: str, why: str, *, checked: bool = True,
             missing: list[str] | None = None, **extra: Any) -> ToolResult:
        """盖章并返回（`state` 只许 `RETIRE_CHILD_STATES` 里的取值）。"""
        assert state in RETIRE_CHILD_STATES, state
        data["state"] = state
        data["checked"] = bool(checked)
        data["reason"] = str(why or "")
        if missing:
            data["missing"] = list(missing) + list(data["missing"])
        data.update(extra)
        return ok(data, **data)

    def _counts(sec: Any) -> dict[str, Any]:
        """父这一份名册的两个读数（子代理数 / 活跃子代理数）。

        读不成 ⇒ `checked=False` 且两个数都是 `None`（不折成 0：0 是"名册空了"这个
        很强的结论）。口径只有 `Secretary.child_counts` 一处 —— 这里再算一遍就是
        "同一读数两个主人"。
        """
        try:
            got = sec.child_counts(owner=mine)
        except Exception as exc:  # noqa: BLE001 —— 读侧自己炸了也是"没读成"
            return {"checked": False, "child_count": None, "active_child_count": None,
                    "reason": f"{type(exc).__name__}: {exc}"}
        if not isinstance(got, Mapping):
            return {"checked": False, "child_count": None, "active_child_count": None,
                    "reason": "名册读数不是对象"}
        return got

    mine = str(current_task_id() or "")
    if not mine:
        return _out("unknown", "这一趟没有台账号 ⇒ 不知道这份名册属于谁（不猜一个父号）",
                    checked=False, missing=["没有台账号"])
    data["parent_task_id"] = mine
    if store is None:
        return _out("unknown", "装配时没给 store ⇒ 读不到台账（没查成，不是'它不在飞'）",
                    checked=False, missing=["store"])
    try:
        rows = list(store.rows("tasks"))
    except Exception as exc:  # noqa: BLE001 —— 读不成不许折成"没有这一行"
        return _out("unknown", f"tasks 台账读不成（{type(exc).__name__}: {exc}）⇒ 本次没查成",
                    checked=False, missing=["tasks 台账"])
    # 指称只有一条正路：名册名（`child_name`）。`task_id` 是旧的兼容写法 —— 它只收绝对编号，
    # 按对照表换算成名册名，并在读数里标 `task_id_compat=true`（谁还在用旧写法，读得出）。
    # `name` 是兼容别名：只在"按映射整体传入"的调用里走得到（模型的 JSON args 会被
    # `agent_loop._do_tool` 摊成关键字 ⇒ 与 `ToolRegistry.call` 的首个形参撞名），
    # 所以它不进 schema，只在读数 `addressed_by` 里留痕。
    sec = _roster_secretary(c, store)
    want = str(child_name or name or "").strip()
    tid = str(task_id or "").strip()
    data["addressed_by"] = ("child_name" if str(child_name or "").strip()
                            else "name" if str(name or "").strip()
                            else "task_id" if tid else "")
    if want:
        try:
            index, bad = sec.roster_index(mine)
        except Exception as exc:  # noqa: BLE001
            return _out("unknown",
                        f"名册对照表读不成（{type(exc).__name__}: {exc}）⇒ 名字换不成编号",
                        checked=False, missing=["名册对照表"])
        if bad:
            return _out("unknown",
                        (f"名册对照表有 {len(bad)} 行读不出来 ⇒ 名字换不成编号"
                         "（没查成，不是『名册里没有它』）"),
                        checked=False, missing=["名册对照表"])
        hit_name = next((r for r in index if str(r.get("name") or "") == want), None)
        if hit_name is None:
            return _out("refused", f"名册里没有 {want} 这个名字（查过了、确实没有）",
                        missing=[f"{want} 不在名册里"])
        tid = str(hit_name.get("task_id") or "")
        if not tid:
            return _out("unknown",
                        f"{want} 在名册上、但对照表里没有它的绝对编号（没查成）",
                        checked=False, missing=["名册名对应的编号"])
        data["task_id"] = tid
    elif tid:
        data["task_id_compat"] = True
    else:
        return _out("refused",
                    "销号要点名：给 child_name（名册名，如 D1）；task_id 只是旧的兼容写法",
                    missing=["没有给 child_name"])
    row = next((r for r in rows if str(r.get("task_id") or "") == tid), None)
    if row is None:
        return _out("refused", f"台账里没有 {tid} 这一行（这是查过了、确实没有）",
                    missing=[f"{tid} 不在 tasks 里"])
    if str(row.get("kind") or ""):
        return _out("refused", f"{tid} 是一条板项（kind={row.get('kind')}），不是代理 ⇒ 销号没有对象",
                    missing=[f"{tid} 是板项不是代理"])
    if str(row.get("parent_task_id") or "") != mine:
        return _out("refused",
                    (f"{tid} 不是你的子代理（它的父是 {row.get('parent_task_id') or '（顶层）'}）"
                     "⇒ 只有它的父能发起销号"),
                    missing=[f"{tid} 的父不是你"])
    data["branch"] = ""
    before = _counts(sec)
    data["readings"] = {"child_counts_before": before}
    data["child_count"] = before.get("child_count")
    data["active_child_count"] = before.get("active_child_count")
    # ---- 子树与次序（从最深到最浅 = 先叶子后父）。级联销号按这个次序落盘。
    try:
        sub = c.subtree_postorder(tid)
    except Exception as exc:  # noqa: BLE001
        return _out("unknown", f"子树读不成（{type(exc).__name__}: {exc}）⇒ 销号次序判不了",
                    checked=False, missing=["subtree"])
    if not sub.get("checked"):
        return _out("unknown", f"子树读不成（{sub.get('reason')}）⇒ 销号次序判不了",
                    checked=False, missing=["subtree"])
    order = [str(x) for x in (sub.get("order") or [])]
    parent_of = dict(sub.get("parent_of") or {})
    depth_of = dict(sub.get("depth_of") or {})
    data["order"] = order
    data["subtree"] = order
    data["subtree_size"] = len(order)
    # ---- 活跃读数（含"在等"的向上继承）：子树里只要还有一个活跃节点就整笔拒绝
    try:
        act = c.active_in_subtree(tid)
    except Exception as exc:  # noqa: BLE001
        return _out("unknown", f"活跃读数没读成（{type(exc).__name__}: {exc}）⇒ 不敢销",
                    checked=False, missing=["活跃读数"])
    if not act.get("checked"):
        return _out("unknown", f"活跃读数没读成（{act.get('reason')}）⇒ 不敢销",
                    checked=False, missing=["活跃读数"])
    active_count = int(act.get("active_count") or 0)
    data["active_nodes"] = list(act.get("rows") or [])
    data["busy_task_ids"] = list(act.get("busy_root_ids") or [])
    data["readings"].update({"subtree_size": len(order), "active_count": active_count,
                             "busy_task_ids": list(act.get("busy_root_ids") or []),
                             "labels": dict(before.get("labels") or {})})
    try:
        ready = c.retire_ready(mine)
    except Exception as exc:  # noqa: BLE001
        return _out("unknown", f"就绪读数没读成（{type(exc).__name__}: {exc}）",
                    checked=False, missing=["retire_ready"])
    if not ready.get("checked"):
        return _out("unknown", f"就绪读数没读成（{ready.get('reason')}）",
                    checked=False, missing=["retire_ready"])
    hit = next((r for r in ready.get("ready") or [] if str(r.get("task_id") or "") == tid), None)
    if hit is None:
        return _out("refused",
                    (f"{tid} 不在可销清单里（已经销过号，或它不在你名下）⇒ 不重复销"),
                    missing=[f"{tid} 不在可销清单里"])
    branch = str(hit.get("branch") or "")
    if active_count > 0 and branch != "active":
        # 继承口径的补丁：`retire_ready` 只看直接子，看不见孙代 —— 一个自己已经收口、
        # 但孙辈还在跑的节点，在它眼里是"可以销"的。业主的规则是"不得有活跃的下级"，
        # 所以这一档按"名下还有活跃子代理"报，不按"可以销"报。
        branch = "waiting_with_children"
    data["branch"] = branch
    # ---- 三态读数（销号前置的唯一读数）：业主 2026-10-26「销号可以也只可针对静默子代理」。
    # 先读它，理由是板项闸与静默闸都要带同一份读数回去（读数在拒信里），而板项闸排在
    # 前面说话 —— 板项清单是父下一步真正要处置的那件事，缺了它这条拒信只是"不许"。
    kid_names: dict[str, str] = {}
    for r in rows:
        if str(r.get("parent_task_id") or "") != tid or str(r.get("kind") or ""):
            continue
        kid = str(r.get("task_id") or "")
        try:
            kid_name, _why_kid = sec.name_of(owner=tid, task_id=kid)
        except Exception:  # noqa: BLE001 —— 名字读不到只影响措辞，不影响这一格的三态
            kid_name = ""
        if kid_name:
            kid_names[kid] = kid_name
    try:
        probe = c.retire_state_of(tid, names=kid_names)
    except Exception as exc:  # noqa: BLE001 —— 读侧自己炸了也是"没读成"
        return _out("unknown",
                    f"三态读数没读成（{type(exc).__name__}: {exc}）⇒ "
                    "读不到它是不是静默，不许销（fail-closed）",
                    checked=False, missing=["三态读数"])
    data["target_state"] = str(probe.get("state") or "")
    data["target_state_label"] = str(probe.get("state_label") or "")
    data["blocking"] = list(probe.get("blocking") or [])
    data["readings"]["target_state"] = data["target_state"]
    # ---- 板项闸（既有闸，排在最具体的那一档）：queued / seen 都算没清
    open_rows = [r for r in rows
                 if str(r.get("parent_task_id") or "") == tid
                 and str(r.get("kind") or "")
                 and str(r.get("item_state") or "") != "done"]
    items_open = int(((hit.get("reading") or {}).get("items_open")) or 0)
    if items_open > 0 or open_rows:
        listed = [{"task_id": str(r.get("task_id") or ""), "kind": str(r.get("kind") or ""),
                   "item_state": str(r.get("item_state") or ""),
                   "summary": str(r.get("detail") or "")[:80]} for r in open_rows[:8]]
        return _out("refused",
                    (f"{tid} 名下还有 {max(items_open, len(open_rows))} 条未消的板项 ⇒ "
                     "task_board 没清，不许直接销号：先用 `conductor.ack` 把已办的那些确认掉、"
                     "没办的先办，等它名下一条未消的项都不剩再来销 —— 否则不许销号"
                     "（没读的东西不许跟着名字一起销掉）"),
                    missing=[f"{r['task_id']}（{r['kind']}/{r['item_state']}）" for r in listed],
                    open_items=listed)
    # ---- 静默闸（本批新增）：只有静默可销。三档各有各的下一步，所以拒信必须分开说。
    if not probe.get("silent"):
        # "真正在跑的在下级的下级"那一小档交给子树活跃闸去说：那份拒信逐个点名整支的
        # 活跃节点，比这里只说"它在待机"更有用。放行到那里不等于允许销号 —— 它照样拒。
        deferred = bool(probe.get("deferred")) and active_count > 0
        if not deferred:
            ref = retire_refusal(probe, tid=tid, name=data["name"], names=kid_names)
            unreadable = (str(probe.get("state") or "") == AGENT_STATE_UNKNOWN
                          or not probe.get("checked"))
            return _out("unknown" if unreadable else "refused",
                        ref["why"], checked=not unreadable,
                        missing=list(ref["missing"]),
                        refusal_code=ref["code"], target_state=ref["state"],
                        target_state_label=ref["state_label"],
                        blocking=list(ref["blocking"]))
    if active_count > 0:
        # 点名：谁还活跃、把它撑成活跃的那些"真在跑"的任务是哪几件。
        named: list[str] = []
        for a in data["active_nodes"]:
            detail = []
            for b in a.get("busy") or []:
                tail = f"/{b['action']}" if str(b.get("action") or "") else ""
                detail.append(f"{b.get('task_id')}（{b.get('role') or '?'}/"
                              f"{b.get('status') or '?'}{tail}）")
            one = (f"{a.get('role') or '?'}（{a.get('task_id')}）还在活跃：卡在 "
                   + ("、".join(detail) or "（读不到它在跑哪一件）"))
            if a.get("note"):
                one += f"；{a['note']}"
            named.append(one)
        if branch == "active":
            return _out("refused",
                        (f"{tid} 还在飞（status={row.get('status') or 'unknown'}）⇒ 等它交差再销；"
                         "销号 ≠ 停止：要它此刻停下来用停止/叫停，不是销号"),
                        missing=[f"{tid} 还在跑"],
                        refusal_code=RETIRE_REFUSAL_TARGET_NOT_SILENT,
                        target_state=str(probe.get("state") or ""),
                        target_state_label=str(probe.get("state_label") or ""),
                        blocking=list(probe.get("blocking") or []))
        return _out("refused",
                    (f"{tid} 这一支里还有 {active_count} 个节点在活跃"
                     f"（子代理数={data['child_count']}，"
                     f"活跃子代理数={data['active_child_count']}）⇒ 整笔不销、一处都不动："
                     "先等那些节点交差再销。点名：" + "；".join(named)),
                    missing=named,
                    refusal_code=RETIRE_REFUSAL_TARGET_NOT_SILENT,
                    target_state=str(probe.get("state") or ""),
                    target_state_label=str(probe.get("state_label") or ""),
                    blocking=list(probe.get("blocking") or []))
    if branch == "waiting_with_children":
        # 读到这一步说明 `retire_ready` 与活跃读数不一致（前者说名下还有活跃子代理、
        # 后者说一个都读不到活跃）。两边都是"查过了"的结论 ⇒ 按保守的那一侧拒绝。
        return _out("refused",
                    (f"{tid} 名下还有活跃子代理 ⇒ 它还在干活；先处置那些子代理再销它"),
                    missing=[f"{tid} 名下还有活跃子代理"],
                    refusal_code=RETIRE_REFUSAL_TARGET_NOT_SILENT,
                    target_state=str(probe.get("state") or ""),
                    target_state_label=str(probe.get("state_label") or ""),
                    blocking=list(probe.get("blocking") or []))
    try:
        name, why = sec.name_of(owner=mine, task_id=tid)
    except Exception as exc:  # noqa: BLE001
        return _out("unknown", f"名册对照表读不成（{type(exc).__name__}: {exc}）",
                    checked=False, missing=["名册对照表"])
    if not name:
        state = "unknown" if ("读不出" in str(why) or "读不成" in str(why)) else "refused"
        return _out(state, f"{tid} 的名册名没读到（{why}）⇒ 不猜一个名字去销",
                    checked=state == "refused", missing=["名册名"])
    data["name"] = name
    # ---- 子树逐项核（先读后写）：任何一项不过 ⇒ 整笔不动，一个字节都不落盘
    ready_by_parent: dict[str, dict[str, Any]] = {}

    def _ready_of(pid: str) -> dict[str, Any]:
        """某父那一层的可销清单：`{"checked", "branch_of", "reason"}`（每个父只问一次）。"""
        if pid in ready_by_parent:
            return ready_by_parent[pid]
        got_ready: dict[str, Any]
        try:
            got_ready = c.retire_ready(pid)
        except Exception as exc:  # noqa: BLE001
            got_ready = {"checked": False, "reason": f"{type(exc).__name__}: {exc}"}
        found = ({str(r.get("task_id") or ""): str(r.get("branch") or "")
                  for r in (got_ready.get("ready") or [])}
                 if got_ready.get("checked") else {})
        ready_by_parent[pid] = {"checked": bool(got_ready.get("checked")),
                                "branch_of": found,
                                "reason": str(got_ready.get("reason") or "")}
        return ready_by_parent[pid]

    plans: list[dict[str, Any]] = []
    blocked: list[str] = []
    for node in order:
        pid = str(parent_of.get(node) or "")
        plan: dict[str, Any] = {
            "task_id": node, "parent": pid, "depth": int(depth_of.get(node) or 0),
            "role": str(next((r.get("role") for r in rows
                              if str(r.get("task_id") or "") == node), "") or ""),
            "name": "", "branch": "", "state": "ready", "why": "",
        }
        plans.append(plan)
        layer = _ready_of(pid)
        if not layer["checked"]:
            return _out("unknown",
                        (f"{pid or '（顶层）'} 那一层的就绪读数没读成"
                         f"（{layer['reason']}）⇒ 级联销号判不了"),
                        checked=False, missing=[f"{pid} 的 retire_ready"])
        if node == tid:
            plan["branch"] = branch
            plan["name"] = name
            continue
        if node not in layer["branch_of"]:
            # 已经销过号的（或不在这个父名下）不在可销清单里 ⇒ 跳过，不算失败。
            plan["state"] = "already"
            plan["why"] = "不在它父那一层的可销清单里（已经销过号）"
            continue
        plan["branch"] = str(layer["branch_of"].get(node) or "")
        kid_open = [r for r in rows
                    if str(r.get("parent_task_id") or "") == node
                    and str(r.get("kind") or "")
                    and str(r.get("item_state") or "") != "done"]
        if kid_open:
            blocked.append(f"{node} 名下还有 {len(kid_open)} 条未消的板项"
                           f"（{[str(r.get('task_id') or '') for r in kid_open[:8]]}）"
                           "—— 先用 `conductor.ack` 把它们收口")
            plan["state"] = "blocked"
            plan["why"] = blocked[-1]
            continue
        try:
            kid_name, why_kid = sec.name_of(owner=pid, task_id=node)
        except Exception as exc:  # noqa: BLE001
            return _out("unknown", f"名册对照表读不成（{type(exc).__name__}: {exc}）",
                        checked=False, missing=["名册对照表"])
        if not kid_name:
            plan["state"] = "unrostered"
            plan["why"] = f"名册里没有它（{why_kid}）⇒ 它不是名册项，没有名字可销"
            data["unrostered"].append({"task_id": node, "parent": pid,
                                       "why": plan["why"]})
            continue
        plan["name"] = kid_name
    if blocked:
        return _out("refused",
                    (f"{tid} 这一支里还有 {len(blocked)} 项不让销 ⇒ 整笔不销、一处都不动："
                     + "；".join(blocked)),
                    missing=blocked)
    # ---- 静默闸（整支逐项，写盘之前）：级联里每一个会被销的节点都必须是静默的。
    #
    # 根那一项已经在上面判过；这里复核其余"这一笔真的会写下去"的节点（`state == ready`
    # 的那些），理由是"级联不许用遍历时特殊放行绕过一个不静默的节点"（业主：
    # 「销号可以也只可针对静默子代理」，这一句对叶子同样成立）。已经销过号的节点
    # （`already`）不在这里判：它们不在这一笔的写入面里，而"已销号"在三态里是另一档
    # （`agent_states` 这里不传 retired 对照，读成待机也只会让一笔本来就不写它的
    # 级联被误拒）。
    # 计时器的"待机"会沿"在等"向上继承，所以根静默通常已经蕴含全支静默 —— 这一趟是
    # 保险，代价是一次 `activity_snapshot`（整支只读一次，不逐节点重读）。
    ready_kids = [p for p in plans
                  if str(p.get("task_id") or "") != tid and p.get("state") == "ready"]
    if ready_kids:
        try:
            snap = c.activity_snapshot()
        except Exception as exc:  # noqa: BLE001 —— 读侧自己炸了也是"没读成"
            return _out("unknown",
                        f"整支的三态读数没读成（{type(exc).__name__}: {exc}）⇒ 不敢销",
                        checked=False, missing=["三态读数"])
        if not snap.get("checked"):
            return _out("unknown", f"整支的三态读数没读成（{snap.get('reason')}）⇒ 不敢销",
                        checked=False, missing=["三态读数"])
        cells = dict(snap.get("by_task") or {})
        for plan in ready_kids:
            node = str(plan.get("task_id") or "")
            cell = cells.get(node)
            if cell is None:
                return _out("unknown",
                            f"三态读数里没有 {node} 这一行 ⇒ 不敢销（读不到它是不是静默）",
                            checked=False, missing=[f"{node} 的三态"])
            if str(cell.get("state") or "") == AGENT_STATE_SILENT:
                continue
            ref = retire_refusal(cell, tid=node, name=str(plan.get("name") or ""))
            return _out("refused",
                        (f"级联里 {ref['why']} ⇒ 整笔不销、一处都不动"
                         "（级联永远是先子后父，且每个节点都必须是静默的）"),
                        missing=list(ref["missing"]), refusal_code=ref["code"],
                        target_state=ref["state"],
                        target_state_label=ref["state_label"],
                        blocking=list(ref["blocking"]))
    # ---- 从最深的开始逐项交给秘书（次序 = `order`，一次也不许反序）
    written: list[dict[str, Any]] = []
    for plan in plans:
        if plan["state"] != "ready":
            data["cascade"].append(dict(plan))
            continue
        sub_reason = str(reason or "")
        if plan["task_id"] != tid:
            lead = f"{data['name'] or tid}（{tid}）"
            sub_reason = ((sub_reason + "；") if sub_reason else "") + \
                f"级联销号：随 {lead} 一起退场"
        sub_reason = sub_reason[:300]
        try:
            got = sec.retire(owner=plan["parent"], name=plan["name"],
                             by_task_id=plan["task_id"], reason=sub_reason)
        except Exception as exc:  # noqa: BLE001 —— 抛了不代表没写：这一档只能记 unknown
            data["cascade"].append(dict(plan, state="unknown",
                                        why=f"秘书销号时抛了（{type(exc).__name__}: {exc}）"))
            data["retired_count"] = len(written)
            data["readings"]["written"] = [w["task_id"] for w in written]
            return _out("unknown",
                        (f"级联销号在第 {len(written) + 1} 项（{plan['name']}）上抛了 ⇒ "
                         f"已经销掉的是 {[w['name'] for w in written]}，剩下没动；"
                         "这不是'全销'也不是'没动'，重读一次再决定"),
                        checked=False, missing=[f"{plan['name']} 落没落盘不知道"])
        if not isinstance(got, Mapping):
            data["cascade"].append(dict(plan, state="unknown", why="秘书的销号读数不是对象"))
            data["retired_count"] = len(written)
            data["readings"]["written"] = [w["task_id"] for w in written]
            return _out("unknown",
                        (f"级联销号在第 {len(written) + 1} 项（{plan['name']}）上没拿到可判读数 ⇒ "
                         f"已经销掉的是 {[w['name'] for w in written]}，剩下没动"),
                        checked=False, missing=["secretary.retire 读数"])
        action = str(got.get("action") or "")
        why_list = [str(x) for x in (got.get("why") or [])]
        why = "；".join(why_list)
        if action != "retired":
            data["cascade"].append(dict(plan, state="refused", why=why))
            data["retired_count"] = len(written)
            data["readings"]["written"] = [w["task_id"] for w in written]
            # 三态在这里再分一次：秘书给出 `reported` / `refused` 是"查过了、现在不许销"
            # （它是确定结论 ⇒ `refused`）；其余（空 action / 没给可判读数）才是"落没落盘不知道"
            # ⇒ `unknown`。把这两档折成一个会让父把"它还在跑、等它"读成"重读一次"。
            if action in ("reported", "refused"):
                return _out("refused",
                            (f"级联销号在第 {len(written) + 1} 项（{plan['name']}）上被秘书拒了"
                             f"（action={action}：{why}）⇒ 已经销掉的是 "
                             f"{[w['name'] for w in written]}，剩下没动；"
                             "先处置那一项再来销"),
                            missing=[f"{plan['name']} action={action}"])
            return _out("unknown",
                        (f"级联销号在第 {len(written) + 1} 项（{plan['name']}）上没落成"
                         f"（action={action or '（空）'}：{why}）⇒ 已经销掉的是 "
                         f"{[w['name'] for w in written]}，剩下没动 —— 这不是'全销'，"
                         "重读一次再决定"),
                        checked=False,
                        missing=[f"{plan['name']} action={action or '（空）'}"])
        written.append(dict(plan))
        data["cascade"].append(dict(plan, state="retired", why=why))
        data["retired_count"] = len(written)
    after = _counts(sec)
    data["readings"]["child_counts_after"] = after
    data["readings"]["written"] = [w["task_id"] for w in written]
    data["child_count"] = after.get("child_count")
    data["active_child_count"] = after.get("active_child_count")
    from ..secretary import retired_path

    roster_retired = False
    try:
        folded, _bad = sec.roster_rows(mine)
        roster_retired = any(str(r.get("name") or "") == name and bool(r.get("retired"))
                             for r in folded)
    except Exception:  # noqa: BLE001 —— 复核读不成不改结论（落盘已经成功）
        roster_retired = False
    msg = why or f"{name}（{tid}）已销号"
    if len(written) > 1:
        msg += (f"；级联销号 {len(written)} 项（从最深到最浅）："
                + "、".join(f"{w['name']}（{w['task_id']}）" for w in written))
    if data["unrostered"]:
        msg += (f"；另有 {len(data['unrostered'])} 行不是名册项"
                "（它们没有名字可销，已在 unrostered 里点名）")
    return _out("retired", msg, retired=True, roster_retired=roster_retired,
                retired_path=str(retired_path(Path(str(sec.root)), mine)))


# ---------------------------------------------------------------- 消项（收件人自己确认）

#: `conductor.ack` 的几档结论（`state` 那一格），与 `Conductor.ack_items` 同一套取值。
#:
#: 为什么不是"成功/失败"两档：`partial`（一条成、一条不是你的）与 `refused`（一条都没成）
#: 在下一步该做的事上完全不同 —— 前者要继续处理剩下的，后者要先弄清为什么一条都不成。
ACK_STATES: tuple[str, ...] = ("acked", "partial", "refused", "nothing", "unknown")


@tool(
    "conductor.ack",
    "把自己名下已经读过、已经办完的板项确认掉（消项）：逐条从 seen 或 queued 推到 done，"
    "落 by_task_id 与步号，并 append-only 记一条事件。只许 ack 收件人是自己的项"
    "（别人的项 ⇒ 受控拒绝 not_yours，一条都不写）。"
    "这是销号之前必须先走的那一步：板没清干净时 `conductor.retire_child` 会拒，"
    "而 M 收工时整棵树都要销号 —— 所以这是那条链上唯一的「确认」动作。",
    {"type": "object",
     "properties": {
         "item_ids": {"type": "array",
                      "items": {"type": "string", "minLength": 4, "maxLength": 12},
                      "minItems": 1, "maxItems": 50,
                      "description": "要确认的板项编号（`tasks` 里的 task_id，可一次给多条）"},
         "note": {"type": "string", "maxLength": 300,
                  "description": "一句为什么（逐字落进那一条事件，可空）"},
     },
     "required": ["item_ids"],
     "additionalProperties": False},
    side_effect="write_local",
    # 所有角色 + 主控：板项按 `parent_task_id` 投给任何一行，所以「会收到板项的」是全部角色
    # （含只读角色 C/H/V —— 它们同样收交接通报、指导与停止通知）。它写的只有
    # `tasks` 的 `item_state`/`item_close` 与一条事件，属簿记 ⇒ 登记在 `UNIVERSAL_TOOLS`
    # 里由那条判据放行，而不是走只读例外表（那是"谁能用"的另一种说法）。
    roles=tuple(S.ROLES) + (S.CONDUCTOR_ROLE,),
    returns=("{'checked','ok','state','acked','already_done','refused','unknown',"
             "'missing','not_yours','refusal_codes','results','count','requested',"
             "'by_task_id','note','reason'}；state 是 acked / partial / refused / "
             "nothing / unknown 之一；acked 是落成的编号，refused 每项给 "
             "item_id / code / reason（code 是 not_yours / no_such_item / "
             "not_board_item / ack_unbacked / state_error 之一），results 逐条给 "
             "item_id / ok / code / state_before / state_after / step / seen_backfilled"),
)
def conductor_ack(_conductor: Any, item_ids: list, note: str = "") -> ToolResult:
    """工具体：收件人自己把名下板项推到 done（判定与写盘都在 `Conductor.ack_items`）。

    ## 为什么"我是谁"不在工具形状里
    收件人 = 这一趟的台账号（`current_task_id()`，生产里由 `AgentLoop._do_tool` 用
    `calling_as` 挂上）。把它做成一个参数等于让模型自己声明"这些项归我"——
    那正是本工具唯一要挡住的那件事（替别人 ack）。

    ## 三态都在 `ok(...)` 里（与同族的 `conductor.retire_child` 同一形状）
    `state` 就是这次消项的结论，而 `acked` / `refused` / `results` 是模型下一步要看的东西；
    `fail` 会把 `data` 整个丢掉（`ToolResult` 的错误那一档 `data=None`），
    于是"哪一条没成、为什么"就没了 —— 而它正是受控拒绝里唯一有用的那一格。
    """
    ids = [str(x) for x in (item_ids or ())]
    data: dict[str, Any] = {
        "checked": False, "ok": False, "state": "unknown",
        "acked": [], "already_done": [], "refused": [], "unknown": [],
        "missing": [], "not_yours": [], "refusal_codes": [], "results": [],
        "count": 0, "requested": len(ids), "by_task_id": "", "note": str(note or ""),
        "reason": "",
    }
    mine = str(current_task_id() or "")
    data["by_task_id"] = mine
    if not mine:
        data["reason"] = ("这一趟没有台账号 ⇒ 不知道这些项归谁（不猜一个收件人）；"
                          "ack 只认收件人是自己的项，所以一行都不写")
        return ok(data, **data)
    if not ids:
        data.update(checked=True, state="nothing", ok=True,
                    reason="没给任何项 ⇒ 一个字节都不写（空调用不是一次消项）")
        return ok(data, **data)
    cond = _conductor()
    try:
        got = cond.ack_items(ids, by_task_id=mine, note=note)
    except Exception as exc:  # noqa: BLE001 —— 抛了不代表没写：这一档只能如实说不知道
        data["reason"] = f"ack 时抛了（{type(exc).__name__}: {exc}）⇒ 落没落盘不知道"
        return ok(data, **data)
    if not isinstance(got, Mapping):
        data["reason"] = "ack 的读数不是对象 ⇒ 没查成"
        return ok(data, **data)
    for key in data:
        if key in got:
            data[key] = got[key]
    state = str(data.get("state") or "unknown")
    data["state"] = state if state in ACK_STATES else "unknown"
    if not str(data.get("reason") or ""):
        n = int(data.get("count") or 0)
        data["reason"] = (f"确认了 {n} 条" if data["state"] == "acked"
                          else f"{n} 条成、{len(data.get('refused') or [])} 条没成"
                          if data["state"] == "partial"
                          else "一条都没确认（逐条理由见 refused）")
    return ok(data, **data)


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
    # 销号（D-59，业主 2026-10-26）：「销号的发起在父代理，销号的实际动作在秘书侧」。
    # 改前这一条链只断在"发起"这一端：`Secretary.retire` 早就写好了，而父代理没有任何动作
    # 去叫它（工具面上一个字都没有）⇒ 名册只增不减。本件是那一端的唯一入口。
    (conductor_retire_child, ('_conductor', 'store')),
    # 消项（D-68，业主 2026-10-26）：「就做手，不兜底。在销号时，如果 task_board 没清，
    # 发提醒，不准直接销号」。改前模型只能在回复里说"已处理"，而盘上那条项永远停在
    # `seen`（真机 sylow3：45 条 seen + 3 条 queued）—— 本件是那一端的唯一动作。
    (conductor_ack, ('_conductor',)),
)


# ---------------------------------------------------------------- 全树追踪（只有 M）

@tool(
    "conductor.watch",
    "看任意一支任务树的行为：从 task_id（或某个角色在台账里的实例行）向下走，"
    "每个节点给状态、最近 N 步（agent_step）、被拒次数与类目、产出是否真落盘、"
    "最近一次交接手稿摘要。depth 缺省（或 0）= 整棵树；主控能想追几层追几层。",
    {"type": "object",
     "properties": {
         "task_id": {"type": "string", "minLength": 4, "maxLength": 8,
                     "description": "从哪一行开始向下看（缺省=我这一趟）"},
         "role_name": {"type": "string",
                       "description": "看某个角色在台账里的每一行（task_id 优先；不给 task_id 时才用它）"},
         "depth": {"type": "integer", "minimum": 0, "maximum": 64,
                   "description": "含根向下看几层；0 或缺省 = 全树"},
         "window": {"type": "integer", "minimum": 1, "maximum": 50,
                    "description": "每个节点给最近几步（缺省 5）"},
     },
     "required": [], "additionalProperties": False},
    side_effect="read",
    roles=("M",),
    returns=("{'checked','roots','depth_requested','depth_reached','window','rows',"
             "'count','truncated','session','silent_children','child_wait_invariant'}；"
             "每个节点里有 {'task_id','role','level',"
             "'status','outcome','recent_steps','refusals','products','last_handoff'}；"
             "silent_children 是这一支里交过差的子代理编号（父据此把它们记为静默），"
             "child_wait_invariant 是不变量『活跃子代理 ⇒ 必有一条等它的计时器』的读侧判据"
             "（by_parent 逐父给 active_children / waited / unwaited / problems）"),
)
def conductor_watch(_conductor: Any, store: Any, *, task_id: str = "",
                    role_name: str = "", depth: int = 0,
                    window: int = 5) -> ToolResult:
    """全树读数（判据在 `agenttrace.watch_rows`）。

    为什么是主控专属：业主原话「普通代理能追一层，M能想追几层追几层」。一层那一半
    在 `trace.children`（所有可被召唤的角色都有），本件只声明 `roles=("M",)`。
    `depth=0` 表示不额外截断：上界交给台账的真实深度，不写死一个会过期的数字。
    """
    from .. import agenttrace as AT
    from .. import conductor as COND

    if store is None:
        return fail("没有工作区（装配时没给 store）⇒ 读不到台账，本次没查成",
                    kind="no_store", checked=False)
    try:
        rows = store.rows("tasks")
    except Exception as exc:  # noqa: BLE001 - 读不成不等于没有任务
        return fail(f"tasks 台账读不成（{type(exc).__name__}: {exc}）⇒ 本次没查成",
                    kind="store_error", checked=False)
    roots: list[dict[str, Any]] = []
    wanted_task = str(task_id or "")
    wanted_role = str(role_name or "")
    if wanted_task:
        hit = next((r for r in rows if str(r.get("task_id") or "") == wanted_task), None)
        if hit is None:
            return fail(f"台账里没有 {wanted_task} 这一行", kind="not_found",
                        checked=True, task_id=wanted_task)
        roots = [hit]
    elif wanted_role:
        roots = [r for r in rows
                 if str(r.get("role") or "") == wanted_role and not str(r.get("kind") or "")]
        if not roots:
            return fail(f"台账里没有角色 {wanted_role} 的实例行（这是查过了、确实没有；"
                        "不是'没读成'）", kind="not_found", checked=True,
                        role_name=wanted_role)
    else:
        mine = str(COND.current_task_id() or "")
        hit = next((r for r in rows if str(r.get("task_id") or "") == mine), None)
        if hit is None:
            return fail("既没给 task_id 也没给 role_name，而这一趟没有台账号 ⇒ 不猜一棵树",
                        kind="no_identity", checked=False)
        roots = [hit]
    roots.sort(key=lambda r: str(r.get("task_id") or ""))
    parts = [
        AT.watch_rows(store, getattr(store, "root", None) or ".", task_row=r,
                      depth=(int(depth) or None), window=window)
        for r in roots
    ]
    merged: list[dict[str, Any]] = []
    for part in parts:
        merged.extend(part.get("rows") or [])
    # ---- 两个"这一支现在安静不安静"的读数（2026-10-27 补线：两条读侧判据原先只有测试调）
    #
    # `silent_children`：这一支名下「交过差」的那些子代理编号（`Conductor.handoffs_reading`
    # 折出来的 `silent` 那一格）。业主 2026-10-27：「父代理把它记为静默子代理」——
    # 缺这一格，"谁安静了"就只有交差账那个文件知道，看树的人看不见。
    # `child_wait_invariant`：不变量（活跃子代理 ⇒ 必有一条等它的计时器）的读侧判据。
    # 缺这一格，不变量破了一天也不会有人报。
    silent: list[str] = []
    invariants: list[dict[str, Any]] = []
    # 这两格要 conductor 本体（`handoffs_reading` / `child_wait_invariant` 都在它上面）：
    # 本件别的部分只用 `store`，所以 `c` 在这里现取一次。取不到 ⇒ 两格报"没查成"，
    # 不许报成"没有子代理交差"（三态纪律）。
    try:
        c = _conductor()
    except Exception as exc:  # noqa: BLE001
        c = None
        no_c = f"拿不到 conductor（{type(exc).__name__}: {exc}）"
    else:
        no_c = ""
    for r in roots:
        rid = str(r.get("task_id") or "")
        if c is None:
            hand = {"checked": False, "silent": [], "reason": no_c}
            inv = {"checked": False, "parent": rid, "active_children": [], "waited": {},
                   "unwaited": [], "problems": [], "reason": no_c}
        else:
            try:
                hand = c.handoffs_reading(rid)
            except Exception as exc:  # noqa: BLE001 - 读不成是"没查成"
                hand = {"checked": False, "silent": [],
                        "reason": f"{type(exc).__name__}: {exc}"}
            try:
                inv = c.child_wait_invariant(rid)
            except Exception as exc:  # noqa: BLE001
                inv = {"checked": False, "parent": rid, "active_children": [], "waited": {},
                       "unwaited": [], "problems": [],
                       "reason": f"{type(exc).__name__}: {exc}"}
        silent.extend(str(x) for x in (hand.get("silent") or ()))
        invariants.append(inv)
    return ok({
        "checked": all(p.get("checked") for p in parts),
        "roots": [str(r.get("task_id") or "") for r in roots],
        "depth_requested": int(depth) or None,
        "depth_reached": max((p.get("depth_reached") or 0) for p in parts) if parts else 0,
        "window": int(window),
        "rows": merged,
        "count": len(merged),
        "truncated": any(p.get("truncated") for p in parts),
        "session": (parts[0].get("session") if parts else {}),
        "silent_children": sorted(set(silent)),
        "child_wait_invariant": {
            "checked": all(i.get("checked") for i in invariants) if invariants else False,
            "by_parent": {str(i.get("parent") or ""): {
                "checked": bool(i.get("checked")),
                "active_children": list(i.get("active_children") or ()),
                "waited": dict(i.get("waited") or {}),
                "unwaited": list(i.get("unwaited") or ()),
                "problems": list(i.get("problems") or ()),
                "reason": str(i.get("reason") or ""),
            } for i in invariants},
            "unwaited": sorted({t for i in invariants for t in (i.get("unwaited") or ())}),
            "problems": [p for i in invariants for p in (i.get("problems") or ())],
            "reason": "；".join(str(i.get("reason") or "") for i in invariants
                               if str(i.get("reason") or "")),
        },
    })


@tool(
    "conductor.guide",
    "把 M 的一句话沿秘书链逐级转发到链上最后那一个代理：只写链尾也认（链由台账的"
    "父子关系现算）；写整条链（绝对编号 `t-000001->t-000005->t-000012`，或名册名"
    "混写 `M->D1->F2`）也认，内部一律先解析成绝对编号链。每一跳的秘书只看链头往下"
    "转，正文只到链尾：只有链尾那一跳的秘书开一条板项、把正文交给它服务的那个代理；"
    "中间的秘书只转发、不读内容。"
    "返回里的 hops 逐项给 hop / of / at / elapsed_us / delta_us / secretary_role / "
    "secretary_task_id / mode（forward 或 deliver）/ from / to / remaining_chain / "
    "content_read / item_id / relay_id；delivered_to 是列表，只有一个元素 = 链尾那一个的"
    "绝对编号（不是标量；读它要先取 [0]）。",
    {"type": "object",
     "properties": {
         "to": {"type": "string", "minLength": 1, "maxLength": 512,
                "description": ("收件人：绝对编号链（`t-000001->t-000005->t-000012`，"
                                "也可写裸六位数 `000001->000005`）、名册名混写（`M->D1->F2`），"
                                "或只写链尾（`t-000012` / `D1`，链由台账现算）")},
         "text": {"type": "string", "minLength": 1, "maxLength": 800,
                  "description": "指导正文（800 字以内；只有链尾那一个代理读得到）"},
     },
     "required": ["to", "text"], "additionalProperties": False},
    side_effect="write_local",
    roles=("M",),
    # 这里只声明顶层键（逐跳那几格写在上面的摘要里）：本仓的声明判据把 `returns=`
    # 里出现的每个引号键都算成"声明的键"，而探针落在受控拒绝那一支时 `hops` 是空
    # 数组 ⇒ 逐跳键观察不到（那会让 `declared ⊆ actual` 假红）。逐跳的形状仍然对
    # 模型可见：`tools/base.py` 把摘要与 returns 一起拼进 description。
    returns=("{'checked','ok','status','to','chain','chain_text','names','roles','to_role',"
             "'delivered_to','hops','item_id','relay_id','refused','error','skipped',"
             "'text','note'}"),
)
def conductor_guide(_conductor: Any, store: Any, *, to: str, text: str) -> ToolResult:
    """M 的指导沿秘书链逐级下发（业主 2026-10-26 裁定：只走秘书链，逐级转发）。

    ## 链路（每一跳都记在 `out/secretary/relay.jsonl`，一笔转发编号贯穿全链）

    1. 收件人写法先由 `Conductor.resolve_chain` 解析成绝对编号链并逐跳校验
       （某跳不是上一跳的直接下级 ⇒ `broken_chain`；销号 ⇒ `retired_target`；
       不在册 ⇒ `not_in_roster`；名册读不成 ⇒ `unknown`）；
    2. 发送方（M）的秘书把正文交给链上第一跳的秘书，载荷里带剩余链；
    3. 每一跳的秘书只看剩余链的头、继续交给下一跳的秘书 —— 正文不落到任何一位
       被转发的代理的板项上；
    4. 链尾那一跳的秘书才开一条 `notice`/`ack` 板项，把正文交给它服务的那一个代理；
    5. 回执沿链回传：发送方拿到 `delivered_to`（链尾的绝对编号）、每一跳的时间与
       `relay_id`。

    ## 改掉的是什么（业主取消的那一条）

    改前这件工具走的是"目标一条板项 + 它的每一级父代理各一条板项"（参数
    `notify_parents`，返回里的 `ancestors`）。业主 2026-10-26 明确取消：
    「我取消我之前说的要让各级父代理知道该消息的说法」⇒ 那一支整条删除，
    `notify_parents` 参数与 `ancestors` 读数一并消失。为什么连参数都不留：
    留着它就是一个"仍会通知各级父"的开关，而这条路径的语义是"消息沿秘书往下走、
    中间不看内容"；留一个能把它改回旧行为的开关，等于让这条裁定只在新调用的
    默认值上成立。
    """
    c = None
    try:
        c = _conductor()
    except Exception as exc:  # noqa: BLE001 - 没有主控句柄时如实报，不假装发出去了
        return fail(f"没有主控句柄（{type(exc).__name__}: {exc}）⇒ 指导没有下发",
                    kind="no_conductor", checked=False)
    body = str(text or "").strip()
    if not body:
        return fail("text 不能为空：指导要是一句能执行的话", kind="param_error")
    store_now = c.store if store is None else store
    root = str(getattr(store_now, "root", "") or "")
    sender = str(current_task_id() or "")
    sender_role = str(current_caller_role() or "") or S.CONDUCTOR_ROLE
    resolved = c.resolve_chain(to, sender_task_id=sender, sender_role=sender_role)
    data: dict[str, Any] = {
        "checked": bool(resolved.get("checked")), "ok": True,
        "status": "refused", "to": str(to or ""),
        "chain": list(resolved.get("chain") or ()),
        "chain_text": str(resolved.get("chain_text") or ""),
        "names": list(resolved.get("names") or ()),
        "roles": list(resolved.get("roles") or ()),
        "to_role": (list(resolved.get("roles") or ()) or [""])[-1],
        "delivered_to": [], "hops": [], "item_id": "", "relay_id": "",
        "refused": "", "error": "", "skipped": list(resolved.get("skipped") or ()),
        "text": body, "note": str(resolved.get("note") or ""),
    }

    def _fill(reading: Mapping[str, Any]) -> dict[str, Any]:
        """把解析/转发读数并进同一张 payload（三档共用一套键，声明才对得上）。"""
        status = str(reading.get("status") or "unknown")
        data["status"] = status if status in ("delivered", "refused", "unknown") else "unknown"
        data["refused"] = str(reading.get("refused") or "")
        data["error"] = str(reading.get("error") or "")
        data["relay_id"] = str(reading.get("relay_id") or data.get("relay_id") or "")
        data["delivered_to"] = list(reading.get("delivered_to") or ())
        data["hops"] = [dict(h) for h in (reading.get("hops") or ())]
        data["item_id"] = str(reading.get("item_id") or "")
        data["checked"] = bool(reading.get("checked", data["checked"]))
        problems = [str(p) for p in (reading.get("problems") or ())]
        if problems:
            data["error"] = (data["error"] + "；" if data["error"] else "") + "；".join(problems)
        return data

    if str(resolved.get("status") or "") != "resolved":
        payload = _fill(resolved)
        return ok(payload, **payload)
    if not root:
        payload = _fill({"status": "unknown", "checked": False,
                         "refused": "store_unreadable",
                         "error": "工作区根读不出来 ⇒ 造不出转发链上的秘书（没查成）"})
        return ok(payload, **payload)
    from .. import secretary as SEC

    _sid = current_session()[1]
    # 带缝的那一支（`for_role_wired`）：转发本身不需要模型，但"这一位秘书将来要判东西"
    # 时，裸 `for_role(...)` 结构上判不了 —— 与 `agent_b` / `table_tools` 同一条口径。
    sender_secretary = SEC.for_role_wired(sender_role, root=root, store=store_now, sid=_sid)
    sender_secretary.task_id = sender
    receipt = sender_secretary.relay_out(
        chain=list(resolved.get("chain") or ()), body=body,
        subject="", sender_role=sender_role)
    payload = _fill(receipt)
    if payload["status"] == "delivered":
        payload["note"] = (f"链 {payload['chain_text']} 已逐级转发完："
                           f"{len(payload['hops'])} 位秘书各经手一次，"
                           f"只有链尾 {payload['delivered_to'][-1]} 读到了正文")
    elif payload["status"] == "refused":
        payload["note"] = "受控拒绝：正文一步都没动"
    else:
        payload["note"] = payload["note"] or "没查成：正文没有交给任何人（不是「送到了」）"
    return ok(payload, **payload)


#: 全树那一档的两件（2026-10-24 业主裁定）。为什么在下面补进 `_TOOL_FUNCTIONS`、
#: 而不是直接写进上面那个元组：那两件声明放在这里是为了与其它 `conductor.*` 的
#: 声明挨在一起（读的人按顺序就能看到"M 的面上有哪些件"），而 `register` 与
#: `selftest` 读的是模块级的 `_TOOL_FUNCTIONS` —— 追加发生在同一个模块的导入期，
#: 两条读路径都看得到同一份清单（不另开第二张表）。
_TOOL_FUNCTIONS = _TOOL_FUNCTIONS + (
    (conductor_watch, ('_conductor', 'store')),
    (conductor_guide, ('_conductor', 'store')),
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
#: 2026-10-24（D-38 C）：加「未完成」—— 那一档说的是"这一项还没做完"，与「不成立」
#:（做完了、结论是坏的）不是同一件事，但两者都算这一行没过；不加它的话 M 按新口径写
#: 下的「未完成」会落成"结论格读不懂"（那一行既不算通过也不算不成立，等于没记）。
_ACCEPTANCE_NOT_OK_ALIASES: tuple[str, ...] = ("不成立", "未通过", "不通过", "失败", "未完成",
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


def _paper_mapping_human_row(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    """人读验收表里「论文对应表」那一行（按名称 / 编号里的词认，取第一行）。

    认法刻意不按固定编号：P12 是 D-38 那两趟真机里 M 自己写的号，换一份表就变。
    名称里带「对应表」或 MAPPING 的那一行就是它；认不出来返回 None（不是"没有这一行"
    的结论，只是这一层没有可读的行 —— 调用方还有机器可判那张表那一层）。
    """
    for row in rows:
        text = f"{row.get('name') or ''}{row.get('id') or ''}".lower()
        if "对应表" in text or "mapping" in text:
            return row
    return None


def _paper_mapping_leg_problems(base: Path, rows: list[dict[str, Any]]) -> list[str]:
    """「论文对应表」这一档在两张验收表里的三种形态（D-38 第二步，2026-10-24）。

    M 手上有两张表：人读的 `out/paper/ACCEPTANCE.md`（`rows` 是解析出来的行）与机器可判的
    `out/paper/ACCEPTANCE-CHECKS.json`。这一步让这一档在两张表上都读得出来：

    - 机器表里那一行缺失（老工作区）⇒ 读成「没查成」（unknown），不判红，点名叫 M 补一行；
    - 机器表里那一行标了 `na` + 理由 ⇒ 不适用（`na` 不是通过，也不是失败）；
    - 人读表里那一行记的是「未完成」一类结论（解析器已读成 `ok=False`）⇒ 它没过；
      机器表里同时有一行时，两张表的结论不一致这件事要点出来（收工门只读机器那张）。

    只在机器表真的在盘上时才说话：没有那份文件是「这一趟没走机器可判那一档」，
    由收工门自己判（研究型项目缺表有它自己的红），这里再补一句只会变成噪音。
    返回空列表 = 这一档在两张表里都没有要报的形态。
    """
    from .. import closing as CL

    path = Path(base) / CL.ACCEPTANCE_CHECKS_NAME
    want = CL.PAPER_MAPPING_LEG_KIND
    if not path.is_file():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        checks = raw["checks"] if isinstance(raw, dict) else raw
        if not isinstance(checks, list):
            raise ValueError("顶层必须是数组，或 {'checks': [...]}")
    except Exception as exc:  # noqa: BLE001 - 读不懂要说出来，不许静默当成"没有这一档"
        return [f"机器可判的验收表读不出来（{path}：{type(exc).__name__}: {exc}）⇒ "
                f"`{want}` 这一档没查成（不是「没有这一行」）；收工门那一侧同样记 unknown"]
    mine = [r for r in checks if isinstance(r, Mapping) and str(r.get("kind") or "") == want]
    problems: list[str] = []
    if not mine:
        problems.append(
            f"验收表缺 `{want}` 这一档（老工作区里的 {CL.ACCEPTANCE_CHECKS_NAME} 没有这一行）"
            "⇒ 读成「没查成」（unknown），不判红；下一趟补一行："
            "{\"id\": \"P12\", \"kind\": \"paper_mapping_rows\", \"min\": 1}"
            "（读数 = out/paper/MAPPING.json 里三格齐的行数，分母是表里的行数）")
    else:
        for row in mine:
            rid = str(row.get("id") or "")
            if row.get("na") is True:
                note = str(row.get("note") or "").strip()
                problems.append(
                    f"验收表行 {rid} 把 `{want}` 标了 na"
                    + (f"（理由：{note}）" if note else "（没写理由 ⇒ 那一行读不懂）")
                    + " ⇒ 这一档不适用（na 不是通过，也不是失败）")
    human = _paper_mapping_human_row(rows)
    if human is not None and human.get("ok") is False and mine:
        problems.append(
            f"验收表行 {human.get('id') or '（无编号）'}"
            f"（{human.get('name') or '论文对应表'}）记的是「未完成」一类结论"
            f"（读数：{human.get('reading') or '（空）'}），而机器可判那张表里有一行 "
            f"`{want}` ⇒ 两张表对同一件事的结论不一致：收工门只读机器那张，"
            "人读那张请改到与它一致（补完对应表再一起翻）")
    return problems


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
        # 它是「上行通道」（孩子跟召唤它的人说话），只读角色必须有。
        #
        # 2026-10-26（D-68 同一族，业主裁定「通用能力根本不该出现谁能用这个说法」）：
        # 这一格的判据不许再是"除了点名的那一件，其余一律是主控工具"—— 那会把
        # 通用能力一律判红，而 C/H/V 同样会收到板项（`conductor.ack` 是收件人的手）。
        # 判据改成读那一张受控集合（`for_role` 用的同一张，不另写一份名单）。
        if is_universal_tool(spec.name):
            continue
        problems.append(f"只读角色 C 拿到了非通用的主控工具 {spec.name}")
    face_c = {s.name for s in reg.for_role("C")}
    if "conductor.escalate" not in face_c:
        problems.append("只读角色 C 没拿到 conductor.escalate（上行通道对所有角色都要开）")
    # 反真空：登记成通用能力的那几件（本模块产出的）必须真的发到 C 的面上 ——
    # 否则"通用能力对所有角色开放"这句话只是登记表上的一句话。
    lacking = sorted(n for n in UNIVERSAL_TOOLS
                     if n.startswith("conductor.") and n not in face_c)
    if lacking:
        problems.append(f"这些通用能力没发给只读角色 C：{lacking}")
    if problems:
        for p in problems:
            print(f"[conductor_tools] {p}")
        return 1
    print(f"[conductor_tools] 自检通过：{len(names)} 件编排面工具；"
          "只读角色的面上只有登记在案的通用能力")
    return 0


__all__ = ["conductor_for", "reset_cache", "register", "selftest", "NotWiredError"]

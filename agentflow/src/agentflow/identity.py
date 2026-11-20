# -*- coding: utf-8 -*-
"""实例身份的单一来源：一个角色的一趟活到底是「谁」。

## 为什么需要这个模块（K1 / K2 的根因）

装配期拿得到 `instance`（`host._actor_for(role, instance)` 的第二个形参），但落盘的
`actor` / `created_by` / `owner` / `producer` / 事件 `actor` / 会话 `instance` 各自
只写角色字面量，或者由某个默认参数把它写死。最硬的一条证据是工具路径：

    `tools/attack_tools._agent_for(store)` 只拿 `store`，不传 `actor`
    ⇒ `AgentF.actor` 恒为 `"agent-F"`（`agent_f/core.py` 的默认值）
    ⇒ claims.owner / events.actor / created_by / ARTIFACTS.producer 全塌成角色级。

于是「两个 F 一起干活」在盘上分不开，而 `_plan_owner` 只能靠名册名补全一格
（`created_by`）—— 那是全仓唯一活下来的实例身份，也是「四套键各写各的」的来源：
tasks.instance、名册名、actor、owner 各说各的（t-000030：tasks.instance=`proof`、
名册=`F1`、actor=`agent-F`）。

## 一套键怎么对（本模块的裁定）

- 规范实例标签（canonical instance）：按下面次序取第一个读得到的：
  1. 名册名（`Secretary.name_of`：名册是「这个实例是谁」的唯一权威读法，它拒重名、
     跨 task 复用同名，`_plan_owner` 的 docstring 已经这样写了）；
  2. 召唤标签（`conductor.current_instance()` / 调用方显式给的 `instance`）；
  3. `tasks.instance`（这一趟台账行上的实例列）；
  4. 台账号 `task_id`（最后的稳定键：一趟活一定有一个台账号；用它当标签既不是
     角色桶，也不会把两个并发实例混在一起）。
- actor = `agent-<角色>-<规范实例标签>`（与 `host._actor_for` 同一个格式，
  `host._actor_for` 现在反过来调 :func:`actor_for`，格式只有一处）。
- owner / created_by / producer 都等于这个 actor（谁写的就是谁）。
- 四套键不一致时不许静默挑一个：`conflict` 写清哪两套不一致、以哪一套为准
  （名册名优先）。读的人据此知道「这一格有争议、争议怎么裁的」。

## 读不到实例时（三态纪律，不许折平）

`attributed=False` + `conflict` 非空。两种处置都合规（业主口径：「要么受控拒、
要么记 conflict」）：

- 有台账号时不塌成角色桶：规范标签退到 `task_id`，actor 是 `agent-F-t-000030`
  这样的实例级键；
- 连台账号都没有（直调 / 单测 / 脚本）时保留 `agent-F` 这个兼容值（否则单实例的
  直调全被挡死），但 `conflict` 逐字说明「这一笔没有实例身份，落的是角色桶」——
  写盘面（claims / ARTIFACTS / 计划行）把这份读数一并带上，不是静默。

## 这个模块不做什么

- 不查名册以外的语义（谁是父、这一趟做什么）—— 那些各有各的单一来源；
- 不写盘：只给读数，写由调用方做（`.identity` 这份读数随写口一起落）。
"""
from __future__ import annotations

import contextvars
from typing import Any, Mapping

#: actor 的格式前缀（`agent-<role>` / `agent-<role>-<instance>`）。
ACTOR_PREFIX = "agent-"

#: 「这一笔的实例标签」的挂点。与 `conductor.calling_as` 同一个临界区：
#: 工具调用与循环体都把这一格挂上，退出时复位。空串 = 这一层没拿到。
_CURRENT_INSTANCE: contextvars.ContextVar[str] = contextvars.ContextVar(
    "agentflow_instance_label", default="")


def current_instance() -> str:
    """这一笔调用挂着的实例标签（没挂点 ⇒ 空串 = 「这一层不知道」，不是「没有实例」）。"""
    return _CURRENT_INSTANCE.get()


def set_current_instance(value: Any) -> contextvars.Token:
    """挂上实例标签，返回复位令牌（由 `conductor.calling_as` 的 `finally` 复位）。"""
    return _CURRENT_INSTANCE.set(str(value or ""))


def reset_current_instance(token: contextvars.Token) -> None:
    """把实例标签复位到 `set_current_instance` 之前的那一格。"""
    _CURRENT_INSTANCE.reset(token)


def actor_for(role: Any, instance: Any = "") -> str:
    """角色 + 实例标签 ⇒ actor 名（格式只有这一处）。

    空标签 ⇒ 角色级名（`agent-F`）。这个兼容值刻意保留：`host.get` 的「空串 = 那个
    单例」是既有契约（`tests/test_host_wiring.py`），改它会把单实例装配整个换掉。
    实例身份是否真的读到了，由 :func:`resolve_identity` 的 `attributed` / `conflict` 回答，
    不由这个字符串单独回答。
    """
    role_text = str(role or "").strip()
    inst = str(instance or "").strip()
    return f"{ACTOR_PREFIX}{role_text}-{inst}" if inst else f"{ACTOR_PREFIX}{role_text}"


def split_actor(role: Any, actor: Any) -> dict[str, Any]:
    """actor 名 ⇒ 它的实例标签（`agent-F-F1` ⇒ `F1`）。

    返回 `{matched, role_level, instance}`：
    - `matched=False`：这个 actor 不是这个角色的形态（别的角色 / 自由文本）；
    - `role_level=True`：正好是角色级名（`agent-F`），没有实例标签；
    - 其余：`instance` 是标签（可能为空串只当前缀恰好相等时，见上一条）。
    """
    role_text = str(role or "").strip()
    text = str(actor or "").strip()
    out = {"matched": False, "role_level": False, "instance": ""}
    if not role_text or not text.startswith(f"{ACTOR_PREFIX}{role_text}"):
        return out
    if text == f"{ACTOR_PREFIX}{role_text}":
        out.update(matched=True, role_level=True)
        return out
    prefix = f"{ACTOR_PREFIX}{role_text}-"
    if text.startswith(prefix):
        out.update(matched=True, instance=text[len(prefix):])
    return out


def _now_task_id(explicit: Any) -> str:
    """台账号：显式给的最优先；否则读 `conductor.current_task_id()`（读不到 ⇒ 空串）。"""
    text = str(explicit or "").strip()
    if text:
        return text
    try:
        from . import conductor as _C

        return str(_C.current_task_id() or "") .strip()
    except Exception:  # noqa: BLE001 —— 读不到上下文 ⇒ 这一格没有（不编一个号）
        return ""


def _tasks_row(store: Any, task_id: str) -> tuple[dict[str, Any], bool, str]:
    """读这一趟的 `tasks` 行：`(行, 查成了没有, 为什么没查成)`。

    行不存在 = 查成了、没有这一行（`checked=True`）；台账读不出来才是 `checked=False`
    ——「没查成」不许折成「没有这一行」（三态纪律）。
    """
    if store is None or not task_id:
        return {}, True, ""
    try:
        rows = store.rows("tasks")
    except Exception as exc:  # noqa: BLE001 —— 台账读不出来是「没查成」
        return {}, False, f"`tasks` 读不出来（{type(exc).__name__}: {exc}）"
    for row in rows:
        got = dict(row)
        if str(got.get("task_id") or "") == task_id:
            return got, True, ""
    return {}, True, ""


def roster_name(store: Any, role: str, task_id: str, *, checked: bool = True) -> dict[str, Any]:
    """用台账号向名册问「这个实例叫什么」：`{checked, name, why}`。

    名册的读法只有一处（`Secretary.name_of`）：它拒「一个号两个名字」的歧义、
    读全历史而不是折叠视图。这里只做「有父行才问」这一步，不另写一份解析。
    """
    out = {"checked": False, "name": "", "why": ""}
    if store is None or not str(task_id or "").strip():
        out.update(checked=True, why="没有台账号 ⇒ 问不到名册名")
        return out
    if not checked:
        out["why"] = "`tasks` 行没查成 ⇒ 不知道这一趟挂在哪个父的名册下"
        return out
    row, rows_ok, why = _tasks_row(store, str(task_id))
    if not rows_ok:
        out["why"] = why
        return out
    parent = str(row.get("parent_task_id") or "").strip()
    if not parent:
        out.update(checked=True,
                   why="这一行没有父台账号 ⇒ 它不在别人的名册里（顶层发起）")
        return out
    try:
        from . import secretary as _SEC

        name, problem = _SEC.Secretary(role, root=getattr(store, "root", "")).name_of(
            owner=parent, task_id=str(task_id))
    except Exception as exc:  # noqa: BLE001 —— 名册读不成是「没查成」
        out["why"] = f"名册读不成（{type(exc).__name__}: {exc}）"
        return out
    out.update(checked=True, name=str(name or "").strip(), why=str(problem or ""))
    return out


def _reading(role: str, *, task_id: str = "", instance: str = "", actor: str = "",
             source: str = "", attributed: bool = False, conflict: str = "",
             tasks_instance: str = "", roster: Mapping[str, Any] | None = None,
             checked: bool = True) -> dict[str, Any]:
    """把各格收成统一形状（键集合固定；本模块内部只走这一个出口）。"""
    return {
        "checked": bool(checked),
        "role": str(role or ""),
        "task_id": str(task_id or ""),
        "instance": str(instance or ""),
        "actor": str(actor or ""),
        "source": str(source or ""),
        "attributed": bool(attributed),
        "conflict": str(conflict or ""),
        "tasks_instance": str(tasks_instance or ""),
        "roster_name": str((roster or {}).get("name") or ""),
        "roster_checked": bool((roster or {}).get("checked")),
        "roster_why": str((roster or {}).get("why") or ""),
    }


def resolve_identity(store: Any = None, role: Any = "", *, task_id: Any = None,
                     instance: Any = None, actor: Any = "", read_roster: bool = True) -> dict[str, Any]:
    """一趟活的实例身份：返回 `{checked, role, task_id, instance, actor, source,
    attributed, conflict, tasks_instance, roster_name, roster_checked, roster_why}`。

    - `task_id` / `instance` 不给（`None`）⇒ 读 `conductor` 的挂点；显式给空串 =
      「这一层明确没有」；
    - `actor` 给了就也当成一个候选来源（`:func:`split_actor``），用于「构造期
      已经把实例折进 actor」的那条路（host 装配 / 直调 `AgentF(actor=…)`）；
    - 规范标签的优先次序见模块 docstring；两套来源不一致 ⇒ `conflict` 非空并说明
      以哪一套为准（名册名 > 召唤标签 > `tasks.instance` > `task_id`）。

    这个函数不抛异常：名册 / 台账读不出来只让 `checked=False`，并留 `conflict`
    说明读不成哪一格 —— 身份格坏了不许把整趟活带走。
    """
    role_text = str(role or "").strip()
    tid = _now_task_id(task_id)
    explicit = str(instance if instance is not None else current_instance() or "").strip()
    from_actor = split_actor(role_text, actor)
    if not explicit and from_actor.get("instance"):
        explicit = str(from_actor["instance"])
    row, tasks_ok, tasks_why = _tasks_row(store, tid)
    tasks_instance = str(row.get("instance") or "").strip()
    roster = {"checked": False, "name": "", "why": ""}
    if read_roster and tasks_ok:
        roster = roster_name(store, role_text, tid)
    elif not tasks_ok:
        roster["why"] = tasks_why

    chosen = ""
    source = ""
    for value, label in ((str(roster.get("name") or "").strip(), "roster"),
                         (explicit, "instance"),
                         (tasks_instance, "tasks.instance"),
                         (tid, "task_id")):
        if value:
            chosen, source = value, label
            break

    conflicts: list[str] = []
    if explicit and roster.get("name") and explicit != roster["name"]:
        conflicts.append(
            f"召唤标签={explicit!r} 与名册名={roster['name']!r} 不一致（以名册名为准）")
    if tasks_instance and chosen and tasks_instance != chosen:
        conflicts.append(
            f"tasks.instance={tasks_instance!r} 与规范标签={chosen!r} 不一致（以{source}为准）")
    if not tasks_ok:
        conflicts.append(f"{tasks_why} ⇒ tasks.instance 这一格没查成")
    if not roster.get("checked") and tid:
        conflicts.append(f"{str(roster.get('why') or '名册没查成')} ⇒ 名册名这一格没查成")
    checked = bool(tasks_ok and roster.get("checked", True))
    if not chosen:
        conflicts.append(
            "实例读不到：名册名 / 召唤标签 / tasks.instance / 台账号四个来源都空 ⇒ "
            "这一笔只能落角色桶（不是「这一笔没有实例问题」）")

    actor_text = actor_for(role_text, chosen) if chosen else (
        str(actor or "").strip() if from_actor.get("matched") else actor_for(role_text, ""))
    return _reading(
        role_text, task_id=tid, instance=chosen, actor=actor_text, source=source,
        attributed=bool(chosen), conflict="；".join(conflicts),
        tasks_instance=tasks_instance, roster=roster, checked=checked)


def from_actor(role: Any, actor: Any, *, task_id: Any = None) -> dict[str, Any]:
    """构造期只拿得到 actor 时的廉价身份读数（不读台账、不读名册）。

    用途：`AgentF.__init__` / `AgentE.__init__` 这类装配期对象留一份可从返回值读到的
    身份。`actor=agent-F-F1` ⇒ `attributed=True`；`actor=agent-F` ⇒ 未归因 + 一句
    `conflict`（真值由调用方在需要时再走 :func:`resolve_identity` 补全）。
    """
    role_text = str(role or "").strip()
    got = split_actor(role_text, actor)
    tid = _now_task_id(task_id)
    if got.get("instance"):
        return _reading(role_text, task_id=tid, instance=got["instance"],
                        actor=str(actor or ""), source="actor", attributed=True)
    return _reading(
        role_text, task_id=tid, actor=actor_for(role_text, ""), source="actor",
        attributed=False,
        conflict=("装配期只拿到角色级 actor（"
                  f"{str(actor or '') or '空'}）⇒ 实例身份未折进来；写盘面会把它当"
                  "未归因读数带上，不静默"))


def owner_for(store: Any, role: Any, *, actor: Any = "", task_id: Any = None,
              instance: Any = None) -> dict[str, Any]:
    """归属键（`created_by` / claims.owner / ARTIFACTS.producer）该写谁。

    与 `AgentF._plan_owner` 的既有口径逐条同一：actor 已经带实例标签 ⇒ 原样用它
    （装配期折进来的身份优先）；只有角色级 actor ⇒ 再向名册/台账要一次（读不到就
    保留角色桶，并把 `attributed=False` 与 `conflict` 带回去）。返回形状与
    :func:`resolve_identity` 相同，调用方只需读 `actor` / `attributed` / `conflict`。
    """
    got = split_actor(role, actor)
    if got.get("instance"):
        base = resolve_identity(store, role, task_id=task_id, instance=got["instance"], actor=actor)
        base["actor"] = str(actor or "").strip()
        base["source"] = "actor"
        return base
    return resolve_identity(store, role, task_id=task_id, instance=instance, actor=actor)


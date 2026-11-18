# -*- coding: utf-8 -*-
"""行级归属（K11）：一张表的每一行归谁，读 / 造 / 改 / 删都问同一处。

## 为什么需要这个模块

改前「行级归属」只有一张表有：`tasks`（`tools/table_tools.py` 的 `_visible_tasks` 与
`_tasks_write_refusal`）。其余表走的是表级判据：要么整张表谁都能读、能改、能删、能造
（`experiments` —— `direct_write_refusal("experiments")` 返回空串，实测评测里 E-2 用
`table.update("experiments", id="000000", patch={"result": …})` 当场改掉了 E-1 那一行），
要么整张表一律不许通用写口碰（`documents` —— DOCGATE2 的成文门），而删除又整张放开。

两件事都不对：

- 表级「一律拒」把「正路」和「别人那一行」混成一件事：`documents` 上我自己的稿也删不掉；
- 表级「一律放行」把「我的行」和「别人的行」混成一件事：任何角色都能改别人的实验证据。

所以这一层的判据是行级的：同一张表里，我那一行（以及我这一趟的产物）归我，
别人的行归别人。表级那道「这张表要不要走正路」的判据（`store.direct_write_refusal`）
原样保留、且先于本模块生效 —— 它不是「归属」问题，是「这张表有没有单点写口」。

## 判据（唯一一处）

- 归属两格：`owner_task`（写这一行那一趟的台账号）+ `owner_instance`（那一趟的实例
  标签）。两格都空 = 加这两列之前的老行。
- 写（改 / 删）：行的归属必须与调用者同一支笔 —— 实例相同，或台账号相同；
  老行按 `created_by` 的角色级归属判（`agent-E` ⇒ 任何 E 实例都不算它的主人，
  但 E 这个角色能处置它；带实例后缀的 `agent-E-E1` ⇒ 只认 E1）。
  归属读不出来（两格空、`created_by` 也读不出）⇒ 受控拒（fail-closed）：
  「不知道是谁的」不许读成「谁都能改」。
- 造行：调用者必须是这张表的产出角色之一，且带得出身份（台账号或实例标签）；
  两格由调用者身份现盖，载荷里自带的两格若与调用者不一致 ⇒ 受控拒（伪造）。
- 读：同一角色的另一个实例看不到这一行（「我做过哪些实验」按实例回答）；
  别的角色照旧整表读得到 —— 证据要能从 E 流到 V / B / G，这不是「泄露」，
  是这条流水线的设计；而这些角色对这张表没有写权（上面那条判据挡着）。
- 老行（两格空）在读侧：`created_by` 是角色级 ⇒ 该角色的任何实例都读得到
  （历史数据不能因为加列而消失）；带实例后缀 ⇒ 只认那个实例。

## 这个模块不做什么

- 不管「这张表的正路是哪一条」（`store.direct_write_refusal` / `_direct_write_disposal`）；
- 不管主题语义（谁能造一条实验行、稿过不过成文门）—— 那些各有各的判据；
- 不写盘：只给读数与拒信，写由调用方做。
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping

from . import identity as _IDENT
from . import schema as _S

#: 两张归属两格的字段名（唯一定义处）。
OWNER_TASK = "owner_task"
OWNER_INSTANCE = "owner_instance"
OWNER_FIELDS: tuple[str, str] = (OWNER_TASK, OWNER_INSTANCE)

#: 有行级归属的表 → 「哪几个角色会产出这张表的行」。
#:
#: 为什么只登记这两张（而不是全表）：这两张表改前各有一次实测越界
#: （`experiments` 被另一实例改行、`documents` 的删除整张放开），而且它们的行
#: 本来就是「某一支笔的产物」。其余表要么是公共知识台账（`statements` /
#: `literature` / `relations`，归属由各自的登记正路负责），要么是过程记录
#: （`tasks` 已有自己的一套可见面），不在这一层重复判。
OWNED_TABLES: dict[str, frozenset[str]] = {
    "experiments": frozenset({"E", "L"}),
    "documents": frozenset({"G"}),
}

#: 写侧受控理由码（进 `ToolResult.meta.kind`）。
ROW_NOT_YOURS = "row_not_yours"
ROW_OWNER_UNKNOWN = "row_owner_unknown"
ROW_OWNER_FORGED = "row_owner_forged"
ROW_OWNER_NOT_PRODUCER = "row_owner_not_producer"

#: 读侧受控理由码（按主键点名取一行、而那一行不是我的时候）。
ROW_NOT_VISIBLE = "row_not_visible"


# ---------------------------------------------------------------- 调用者身份


def caller() -> dict[str, str]:
    """这一次工具调用是「谁」：`{role, task_id, instance}`（读不到就是空串，不编）。

    三个来源与真机装配是同一处（`conductor.calling_as` 五格里的三格）：
    `current_caller_role()` / `current_task_id()` / `identity.current_instance()`。
    没有挂点（脚本 / 单测直调）⇒ 三格全空；判据据此 fail-closed。
    """
    role = task = ""
    try:
        from . import conductor as _C

        role = str(_C.current_caller_role() or "")
        task = str(_C.current_task_id() or "")
    except Exception:  # noqa: BLE001 —— 读不到就是读不到（空串），不编一个身份出来
        role, task = "", ""
    return {"role": role, "task_id": task, "instance": str(_IDENT.current_instance() or "")}


def owned(table: str) -> bool:
    """这张表有没有行级归属（没有 ⇒ 本模块全部放行、一个字节都不动）。"""
    return str(table or "") in OWNED_TABLES


def producers(table: str) -> frozenset[str]:
    return OWNED_TABLES.get(str(table or ""), frozenset())


# ---------------------------------------------------------------- 一行归谁


def owner_of(row: Mapping[str, Any] | None) -> dict[str, str]:
    """这一行的归属读数：`{task, instance, legacy_role, legacy_instance, attributed}`。

    - `task` / `instance`：行上两格；两格都空 ⇒ 老行，转而读 `created_by`；
    - `legacy_role` / `legacy_instance`：`created_by` 拆出来的角色级 / 实例级标签
      （`identity.split_actor` 是这层拆法的唯一来源）；
    - `attributed`：这一行指名到了某个实例（新行的 `owner_instance`，或老行
      `created_by` 里的实例后缀）。`False` 且两格空 = 角色级老行；两者都不是
      「没有归属」——「归属只到角色」与「归属到实例」是两档，判据分开用。
    """
    got = dict(row or {})
    task = str(got.get(OWNER_TASK) or "").strip()
    instance = str(got.get(OWNER_INSTANCE) or "").strip()
    created_by = str(got.get("created_by") or "").strip()
    legacy = {"role": "", "instance": ""}
    for role in sorted(producers_of_row(got)):
        part = _IDENT.split_actor(role, created_by)
        if part.get("matched"):
            legacy = {"role": role, "instance": str(part.get("instance") or "")}
            break
    attributed = bool(instance or legacy["instance"])
    return {
        "task": task,
        "instance": instance,
        "legacy_role": legacy["role"],
        "legacy_instance": legacy["instance"],
        "attributed": attributed,
    }


def producers_of_row(row: Mapping[str, Any]) -> set[str]:
    """这一行可能属于哪几个角色（从 `created_by` 的 actor 前缀反推）。

    为什么不问表名：同一张表可能被多个角色写（`experiments` 的 E / L），
    而「这一行的 `created_by` 是哪个角色的 actor」只有那一格说得清。
    """
    text = str((row or {}).get("created_by") or "").strip()
    if not text:
        return set()
    return {role for role in _all_producer_roles()
            if _IDENT.split_actor(role, text).get("matched")}


def _all_producer_roles() -> set[str]:
    out: set[str] = set()
    for roles in OWNED_TABLES.values():
        out.update(roles)
    return out


# ---------------------------------------------------------------- 读侧


def visible(table: str, row: Mapping[str, Any], *, role: str = "",
            task_id: str = "", instance: str = "") -> bool:
    """这一行该不该给这个调用者看（判据见模块 docstring 的「读」那一条）。"""
    if not owned(table):
        return True
    mine = str(role or "")
    if mine not in producers(table):
        # 别的角色：这张表对它们是「证据来源」，整表可读（写权由写侧判据挡着）。
        return True
    got = owner_of(row)
    if got["legacy_role"] and got["legacy_role"] != mine:
        # 同一张表、另一个产出角色（`experiments` 的 E 与 L）：那是它自己的账，
        # 读得到（证据是公共的），但写侧不认（归属判据在 `write_refusal`）。
        return True
    my_task = str(task_id or "")
    my_instance = str(instance or "")
    if got["instance"] or got["task"]:
        if my_instance and got["instance"] == my_instance:
            return True
        if my_task and got["task"] == my_task:
            return True
        return False
    # ---- 老行：没有归属两格 ⇒ 按 `created_by` 判角色 / 实例
    if got["legacy_instance"]:
        return bool(my_instance) and got["legacy_instance"] == my_instance
    if got["legacy_role"]:
        return got["legacy_role"] == mine
    # 归属完全读不出来（`created_by` 空 / 认不出角色）⇒ 不给同角色实例看：
    # 「判不了」不是「可以看」；别的角色那一支上面已经放行（它们读的是公共证据）。
    return False


def scope_rows(table: str, rows: Iterable[Mapping[str, Any]], *, role: str = "",
               task_id: str = "", instance: str = "") -> list[dict]:
    """按可见面收窄一批行（读侧唯一实现：`table.*` 与 E 的台账读口都走它）。"""
    if not owned(table):
        return [dict(r) for r in rows]
    return [dict(r) for r in rows
            if visible(table, r, role=role, task_id=task_id, instance=instance)]


# ---------------------------------------------------------------- 写侧


def create_refusal(table: str, payload: Mapping[str, Any], *, role: str = "",
                   task_id: str = "", instance: str = "") -> tuple[str, str] | None:
    """造行前的判据：`(理由码, 人话)` 或 `None`（放行）。"""
    if not owned(table):
        return None
    mine = str(role or "")
    if not mine:
        # 没有调用上下文（脚本 / 单测直调）⇒ 连「你是哪个角色」都不知道：这是身份缺，
        # 不是「角色不对」。两档必须分开说，否则读的人会去改角色而不是补身份。
        return (ROW_OWNER_UNKNOWN,
                f"{ROW_OWNER_UNKNOWN}：`{table}` 的行要写清「哪一趟、哪个实例」写下的，"
                "而这一次调用没有身份（没有角色，也没有台账号 / 实例标签）⇒ 拒。"
                "「不知道是谁」不许写成「谁都可以」—— 请在有身份的循环里调用。")
    if mine not in producers(table):
        return (ROW_OWNER_NOT_PRODUCER,
                f"{ROW_OWNER_NOT_PRODUCER}：`{table}` 的行是 "
                f"{' / '.join(sorted(producers(table)))} 的产出 —— 你这一趟是 "
                f"{mine or '（没有角色）'} ⇒ 通用写口不许替它们造行。"
                "要造这类行请走那个角色的正路动作（实验走 `run_experiment`，"
                "稿件走 `doc.build_document`）。")
    if not str(task_id or "") and not str(instance or ""):
        return (ROW_OWNER_UNKNOWN,
                f"{ROW_OWNER_UNKNOWN}：`{table}` 的行要写清「哪一趟、哪个实例」写下的，"
                "而这一次调用没有身份（没有台账号，也没有实例标签）⇒ 拒。"
                "「不知道是谁」不许写成「谁都可以」—— 请在有身份的循环里调用。")
    forged = forged_owner_fields(payload, role=mine, task_id=task_id, instance=instance)
    if forged is not None:
        return forged
    return None


def forged_owner_fields(payload: Mapping[str, Any], *, role: str = "", task_id: str = "",
                        instance: str = "") -> tuple[str, str] | None:
    """载荷里自带归属两格、且与调用者不一致 ⇒ 受控拒（伪造他人的归属）。"""
    got = dict(payload or {})
    task = str(got.get(OWNER_TASK) or "").strip()
    instance_value = str(got.get(OWNER_INSTANCE) or "").strip()
    if task and task != str(task_id or ""):
        return (ROW_OWNER_FORGED,
                f"{ROW_OWNER_FORGED}：载荷里的 `{OWNER_TASK}` 是 {task!r}，而你这一趟是 "
                f"{str(task_id or '') or '（没有台账号）'!r} ⇒ 归属两格由调用者身份现盖，"
                "不许写成别人那一趟。")
    if instance_value and instance_value != str(instance or ""):
        return (ROW_OWNER_FORGED,
                f"{ROW_OWNER_FORGED}：载荷里的 `{OWNER_INSTANCE}` 是 {instance_value!r}，"
                f"而你这一趟的实例标签是 {str(instance or '') or '（空）'!r} ⇒ 归属两格由"
                "调用者身份现盖，不许写成别人的实例。")
    return None


def write_refusal(table: str, row: Mapping[str, Any] | None, *, op: str = "update",
                  role: str = "", task_id: str = "", instance: str = "") -> tuple[str, str] | None:
    """改 / 删一行的判据：`(理由码, 人话)` 或 `None`（放行）。

    `op` 只用于措辞（`update` / `delete`）：两条路判的是同一件事 ——
    「这一笔改动替你改的是谁那一行」。
    """
    if not owned(table):
        return None
    where = f"table.{str(op or 'update')}"
    got = owner_of(row)
    mine = str(role or "")
    my_task = str(task_id or "")
    my_instance = str(instance or "")
    if got["instance"] or got["task"]:
        if my_instance and got["instance"] == my_instance:
            return None
        if my_task and got["task"] == my_task:
            return None
        who = got["instance"] or got["task"]
        return (ROW_NOT_YOURS,
                f"{ROW_NOT_YOURS}：`{where}(table=\"{table}\")` 的这一行归 "
                f"{who!r}（`{OWNER_INSTANCE}` / `{OWNER_TASK}`），你这一趟是 "
                f"{my_instance or my_task or '（没有身份）'!r} ⇒ 拒。"
                "改 / 删别人的行等于替别人收工：实验证据与稿件的归属只有它那一支笔能处置。")
    if got["legacy_instance"]:
        if my_instance and got["legacy_instance"] == my_instance:
            return None
        return (ROW_NOT_YOURS,
                f"{ROW_NOT_YOURS}：这一行的 `created_by` 指名到实例 "
                f"{got['legacy_instance']!r}，你这一趟是 {my_instance or '（没有实例标签）'!r} ⇒ 拒。")
    if got["legacy_role"]:
        if got["legacy_role"] == mine:
            return None
        return (ROW_NOT_YOURS,
                f"{ROW_NOT_YOURS}：这一行的 `created_by` 是 {got['legacy_role']} 那一族"
                f"（老行没带实例两格），你这一趟是 {mine or '（没有角色）'!r} ⇒ 拒。")
    return (ROW_OWNER_UNKNOWN,
            f"{ROW_OWNER_UNKNOWN}：这一行没有归属（`{OWNER_TASK}` / `{OWNER_INSTANCE}` 与 "
            "`created_by` 都读不出主人）⇒ 受控拒。「判不了是谁的」不是「谁都能改」。"
            "处置：由这一行的产出角色按正路重建，或先补齐归属（人裁）。")


def same_writer(row: Mapping[str, Any], *, role: str = "", task_id: str = "",
                instance: str = "", actor: str = "") -> bool:
    """这一行是不是「我这一支笔」写下的（撤销 / 比对这类会改动别人证据的动作只认它）。

    与 `visible` 的区别不是松紧，而是问的问题不同：`visible` 回答「我读不读得到」
    （角色级老行对同角色每个实例都可读）；本函数回答「我能不能替它作决定」。
    所以老行只在一种情况下算我的：`created_by` 逐字等于我这一趟的 actor
    （同一个 actor 就是同一支笔 —— 直调 / 单测那一档没有实例标签，这是唯一可判的键）。
    老行 `created_by` 是角色级而我是实例级（`agent-E` vs `agent-E-E1`）⇒ 判不了 ⇒ False：
    「判不了是不是你的」不许读成「可以撤」。
    """
    got = owner_of(row)
    my_task = str(task_id or "")
    my_instance = str(instance or "")
    if got["instance"] or got["task"]:
        if my_instance and got["instance"] == my_instance:
            return True
        return bool(my_task) and got["task"] == my_task
    if got["legacy_instance"]:
        return bool(my_instance) and got["legacy_instance"] == my_instance
    if got["legacy_role"]:
        return bool(actor) and str(row.get("created_by") or "").strip() == str(actor).strip()
    return False


def stamp(table: str, payload: dict, *, role: str = "", task_id: str = "",
          instance: str = "") -> dict:
    """给要落盘的行现盖归属两格（非归属表原样返回）。只盖，不校验 —— 校验在上面。"""
    if owned(table):
        payload[OWNER_TASK] = str(task_id or "")
        payload[OWNER_INSTANCE] = str(instance or "")
    return payload

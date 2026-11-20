# -*- coding: utf-8 -*-
"""稿、计划与命题的三态生命周期：活跃 / 完工 / 放弃 —— 以及「活跃集」的唯一读数。

## 业主口径（2026-11-18，逐字）

```text
稿与计划的生命周期：显式三态 = 活跃 / 完工 / 放弃
 · 完工 = 拿到 V 签 ⇒ 冻结只读
 · 放弃 = 该稿号或计划号已放弃 ⇒ 从活跃集踢出（可物理踢出）
 · 唯一判据入口：只看活跃集；其他判据不得各自写 `if abandoned: continue`
```

「唯一判据入口」是这一条的分量所在：改前同一个「这条计划还算不算在推」在四处各写
一份 —— 判重（`create_plan` 的 `status not in TERMINAL_STATUSES`）、并发上限（同一个
名单的第二份副本 `PLAN_CAP_TERMINAL_STATUSES`）、`list_plans(include_terminal=False)`、
`step` 的「终态先到先得」外加一句 `if status != "abandoned"`。四份名单今天恰好
相等，所以没有判据会红 —— 这正是本仓反复记过的形态：两份逐字相同的判据，改一处
不会有任何东西变红。K3 / K4 / K8 / K9 / K10 / K11 都会问「它还活着吗」，所以本模块
是它们共用的那一个入口：后续批次只许调 :func:`state_of_plan` /
:func:`active_plans` / :func:`state_of_manuscript`，不许再各写一份名单。

## 六个原始状态怎么折成三档（计划的 `ATTACK_STATUSES`）

| 原始 `status` | 三态 | 为什么 |
|---|---|---|
| `open` / `attacking` | `active` | 还在推 |
| `resolved` | `completed` | 子目标都有依据、稿已拿签（2026-11-18 的关计划闸） |
| `stalled` / `supported_not_proved` | `completed` | 同一道闸：改后它们只在稿已拿到 V 签（或这条计划没有要签的稿）时才可能出现（`agent_f/step.py` 的 `_finish_gate`），所以它们也是「完工」而不是「还在推」；与 2026-11-18 的并发上限口径同一份名单 |
| `abandoned` | `abandoned` | F 主动放弃（`attack.abandon_plan`）；不是「完工」 |

`TERMINAL_STATUSES`（`schema.ATTACK_TERMINAL_STATUSES`）仍然是「不再推进」的那一列，
本模块不另立词表：完工那一档就是 `TERMINAL_STATUSES` 去掉 `abandoned`。

## 稿的三态

| 读数 | 三态 | 依据 |
|---|---|---|
| `manuscriptfreeze.freeze_reading` 的 `signed` / `edited_after_sign` | `completed` | 拿到 V 签 ⇒ 冻结只读（`edited_after_sign` 是违规态，但它确实签过，仍是「完工 + 只读」） |
| `manuscriptretire.retire_reading` 的 `retired=True` | `abandoned` | 该稿所属命题已放弃/判错 ⇒ 稿一并作废（业主 2026-11-13 裁定） |
| 其余（`unsigned` / 查成了但没有签、没有退休） | `active` | 还能写 |

优先级：放弃压过完工（一条已签的稿后来所属命题被放弃 ⇒ 它是「放弃」；两档都不在
活跃集，但放弃是更具体的那个事实）。`unchecked`（颁发表读不出来 / 命题台账读不出来）
⇒ `checked=False` + 空 `state`：不折成活跃（三态纪律：没查成不等于还活着）。

## 命题的三态（2026-11-19，FIX186-A）

命题面（`statements.status`）也必须走同一入口：:func:`state_of_statement`。
三档按「它还占不占活跃集」划，词表仍以 `schema.STATEMENT_STATUSES` 为唯一真身，
本模块只写「哪一档落哪一类」这张映射：

| 原始 `status` | 三态 | 为什么 |
|---|---|---|
| `active` / `disputed` / `pending_definition` | `active` | 还在推（争议未裁、定义待补都不是「结束」） |
| `superseded` | `completed` | 被后来的一条取代：走到了头（取代者还在） |
| `abandoned` / 错误那一档 | `abandoned` | 放弃与「标记为错误」都是退休态，从活跃集踢出 |

错误那一档不从本模块另抄一份词：映射按补集从 `STATEMENT_STATUSES` 派生
（未落在活跃 / 完工两档的全部归「放弃」），于是 `refuted` 与将来的 `error`
自动同档，而新增一个状态词时导入期的分区断言会先炸。

## 读不到 / 未知状态

计划行上出现不在 `ATTACK_STATUSES` 里的状态 ⇒ `checked=False` + 空 `state`，并在
:func:`active_plans` 的 `unjudged` 里逐条列出 —— 不许把它读成活跃（也没资格读成完工）。
命题行同理（不在 `STATEMENT_STATUSES` 里 ⇒ `checked=False`）。
"""
from __future__ import annotations

from typing import Any, Mapping

from . import errorstate as _ES
from . import schema as _S

#: 三态（闭集）。
ACTIVE = "active"
COMPLETED = "completed"
ABANDONED = "abandoned"
STATES: tuple[str, ...] = (ACTIVE, COMPLETED, ABANDONED)

#: 计划的两档「不活跃」：完工 = 终态里除 `abandoned` 以外的三档（全部过稿已拿签的闸）。
PLAN_COMPLETED_STATUSES: tuple[str, ...] = tuple(
    s for s in _S.ATTACK_TERMINAL_STATUSES if s != ABANDONED)

#: 计划的三态映射（原始状态 ⇒ 三态；闭集，键都在 `ATTACK_STATUSES` 里）。
PLAN_STATE_OF: dict[str, str] = {
    **{s: ACTIVE for s in _S.ATTACK_STATUSES
       if s not in _S.ATTACK_TERMINAL_STATUSES},
    **{s: COMPLETED for s in PLAN_COMPLETED_STATUSES},
    ABANDONED: ABANDONED,
}

#: 命题的三档原始状态（不写词表里的具体词，只写「哪几档是活跃 / 完工」）。
#:
#: 「放弃」那一档不列：它是 `STATEMENT_STATUSES` 的补集 —— 错误那一档的词
#: （今天 `refuted`，词表补丁落地后 `error`）由 `errorstate.ERROR_WORDS` 定义，
#: 本模块抄一份就会在补丁落地那天分家。补集写法的负控见
#: `tests/test_lifecycle_three_states_single_source.py` 的 f 条（打桩成全是活跃 ⇒ 红）。
STATEMENT_ACTIVE_STATUSES: tuple[str, ...] = ("active", "disputed", "pending_definition")
STATEMENT_COMPLETED_STATUSES: tuple[str, ...] = ("superseded",)

#: 命题的三态映射（`status` ⇒ 三态；闭集，键都在 `STATEMENT_STATUSES` 里）。
STATEMENT_STATE_OF: dict[str, str] = {
    **{s: ACTIVE for s in STATEMENT_ACTIVE_STATUSES},
    **{s: COMPLETED for s in STATEMENT_COMPLETED_STATUSES},
    **{s: ABANDONED for s in _S.STATEMENT_STATUSES
       if s not in STATEMENT_ACTIVE_STATUSES
       and s not in STATEMENT_COMPLETED_STATUSES},
}

#: 导入期分区断言：活跃 / 完工两档都在词表里，且「放弃」恰是退休那一列
#: （`abandoned` + `errorstate.ERROR_WORDS`，与 `manuscriptretire.RETIRED_STATUSES`
#: 同一个派生）。新增一个状态词而没在活跃 / 完工两档里点名 ⇒ 它会被静默算成「放弃」；
#: 这里先炸（三态是闭集，不许靠补集悄悄收编新词）。
_NAMED_STATEMENT_STATES: set[str] = (
    set(STATEMENT_ACTIVE_STATUSES) | set(STATEMENT_COMPLETED_STATUSES)
)
_STATEMENT_RETIRED_STATUSES: set[str] = {ABANDONED, *_ES.ERROR_WORDS}
assert _NAMED_STATEMENT_STATES <= set(_S.STATEMENT_STATUSES), (
    "lifecycle 的命题三档点名了词表里没有的状态："
    f"{sorted(_NAMED_STATEMENT_STATES - set(_S.STATEMENT_STATUSES))}"
)
assert set(STATEMENT_STATE_OF) == set(_S.STATEMENT_STATUSES), (
    "命题三态映射没有覆盖 STATEMENT_STATUSES："
    f"缺 {sorted(set(_S.STATEMENT_STATUSES) - set(STATEMENT_STATE_OF))}"
)
assert set(STATEMENT_STATE_OF) - _NAMED_STATEMENT_STATES == _STATEMENT_RETIRED_STATUSES, (
    "命题三态映射的「放弃」那一档与 errorstate 的退休词表分家了："
    f"映射多出 {sorted(set(STATEMENT_STATE_OF) - _NAMED_STATEMENT_STATES - _STATEMENT_RETIRED_STATUSES)}、"
    f"少了 {sorted(_STATEMENT_RETIRED_STATUSES - set(STATEMENT_STATE_OF))}"
    " ⇒ 新增状态词要先在这里点名（活跃 / 完工），或先认它是不是退休"
)


def _reading(kind: str, ref: Any, *, state: str = "", raw: str = "",
             checked: bool = True, why: str = "", **extra: Any) -> dict[str, Any]:
    """三态读数的统一形状（键集合固定；本模块只从这里出读数）。"""
    out = {"checked": bool(checked), "kind": str(kind), "ref": str(ref or ""),
           "state": str(state or ""), "raw": str(raw or ""), "why": str(why or "")}
    out.update(extra)
    return out


def is_active(reading: Mapping[str, Any] | None) -> bool:
    """这份读数是不是「活跃」（`checked=True` 且 `state=active`）。"""
    got = dict(reading or {})
    return bool(got.get("checked")) and str(got.get("state") or "") == ACTIVE


def state_of_plan(row: Any) -> dict[str, Any]:
    """计划行（或裸 `status` 字符串）⇒ 三态读数。

    返回 `{checked, kind="plan", ref, state, raw, why}`：
    - 行上没有 `status` ⇒ 按 `open`（`AttackPlan` 的默认值；老行可能缺这一格）；
    - 状态不在 `ATTACK_STATUSES` ⇒ `checked=False` + `state=""`（不折成活跃）；
    - `kind="plan"` 是给调用方分派用的（K3/K4 与稿共用同一个读数形状）。
    """
    if isinstance(row, Mapping):
        status = str(dict(row).get("status") or "open")
        ref = str(dict(row).get("plan_id") or "")
    else:
        status = str(row or "open")
        ref = ""
    if status not in PLAN_STATE_OF:
        return _reading("plan", ref, raw=status, checked=False,
                        why=(f"计划状态 {status!r} 不在 ATTACK_STATUSES "
                             f"{list(_S.ATTACK_STATUSES)} 里 ⇒ 这一格判不了"
                             "（不折成活跃，也不折成完工）"))
    state = PLAN_STATE_OF[status]
    return _reading("plan", ref, state=state, raw=status,
                    why=(f"status={status!r} ⇒ {state}"))


def state_of_statement(row: Any) -> dict[str, Any]:
    """命题行（或裸 `status` 字符串）⇒ 三态读数（`kind="statement"`）。

    这是命题面唯一的「它还占不占活跃集」入口：`closing` / `agent_loop` 那几处
    原先各自写 `if status == "abandoned": continue`，改后一律调本函数
    （静态判据 `tests/test_lifecycle_three_states_single_source.py` 的 g 条守着）。

    - 行上没有 `status` ⇒ 按 `active`（`Statement` 的默认值；老行可能缺这一格）；
    - 状态不在 `STATEMENT_STATUSES` 里 ⇒ `checked=False` + `state=""`（不折成活跃，
      也不折成放弃）；
    - `raw` 原样保留：调用方要写"凭什么退休"（放弃标记 / 错误凭据）时读它，
      但"还在不在活跃集"只读 `state`。
    """
    if isinstance(row, Mapping):
        got = dict(row)
        status = str(got.get("status") or ACTIVE)
        ref = str(got.get("stmt_id") or got.get("statement_id") or "")
    else:
        status = str(row or ACTIVE)
        ref = ""
    if status not in STATEMENT_STATE_OF:
        return _reading("statement", ref, raw=status, checked=False,
                        why=(f"命题状态 {status!r} 不在 STATEMENT_STATUSES "
                             f"{list(_S.STATEMENT_STATUSES)} 里 ⇒ 这一格判不了"
                             "（不折成活跃，也不折成放弃）"))
    state = STATEMENT_STATE_OF[status]
    return _reading("statement", ref, state=state, raw=status,
                    why=f"status={status!r} ⇒ {state}")


def statement_is_active(row: Any) -> bool:
    """这一行命题现在还在活跃集里吗（`state_of_statement` 的薄包装，供判据读）。"""
    return is_active(state_of_statement(row))


def state_of_manuscript(store: Any, rel: Any) -> dict[str, Any]:
    """一份稿 ⇒ 三态读数（`{checked, kind="manuscript", ref, state, raw, why, ...}`）。

    只读盘上两份既有读数：`manuscriptfreeze.freeze_reading`（拿签 ⇒ 冻结）与
    `manuscriptretire.retire_reading`（命题退休 ⇒ 稿作废）。本函数不写盘、
    不新增台账、不改任何写口。`root` 从 `store.root` 取（稿路径是工作区相对）。
    """
    rel_text = str(rel or "").strip().replace("\\", "/")
    root = str(getattr(store, "root", "") or "")
    base = {"sign_state": "", "retired": False, "stmt_id": ""}
    if not rel_text:
        return _reading("manuscript", "", checked=True,
                        why="没给稿路径 ⇒ 这一份不存在（不是「它还活着」）", **base)
    if not root:
        return _reading("manuscript", rel_text, checked=False,
                        why="没有工作区根 ⇒ 拿不到签台账与命题台账（没查成）", **base)
    from . import manuscriptfreeze as _FZ

    try:
        frozen = _FZ.freeze_reading(root, rel_text)
    except Exception as exc:  # noqa: BLE001 —— 判据自己炸了 = 没查成
        return _reading("manuscript", rel_text, checked=False,
                        why=f"签台账判据没跑成（{type(exc).__name__}: {exc}）", **base)
    base["sign_state"] = str(frozen.get("state") or "")
    if not frozen.get("checked", True):
        return _reading("manuscript", rel_text, checked=False, raw=base["sign_state"],
                        why=f"拿签台账读不出来 ⇒ 没查成：{frozen.get('why') or ''}",
                        **base)
    from . import manuscriptretire as _MR

    try:
        retire = _MR.retire_reading(store, rel_text)
    except Exception as exc:  # noqa: BLE001 —— 同上
        return _reading("manuscript", rel_text, checked=False,
                        why=f"命题退休判据没跑成（{type(exc).__name__}: {exc}）", **base)
    base["stmt_id"] = str(retire.get("stmt_id") or "")
    base["retired"] = bool(retire.get("retired"))
    if not retire.get("checked", False):
        return _reading("manuscript", rel_text, checked=False,
                        why=f"命题台账读不出来 ⇒ 没查成：{retire.get('why') or ''}",
                        **base)
    if base["retired"]:
        return _reading("manuscript", rel_text, state=ABANDONED,
                        raw=f"statement={base['stmt_id']}",
                        why="所属命题已退休（放弃/判错）⇒ 这一份稿一并作废", **base)
    if base["sign_state"] in ("signed", "edited_after_sign"):
        return _reading("manuscript", rel_text, state=COMPLETED,
                        raw=base["sign_state"],
                        why="已拿到 V 签 ⇒ 完工、只读（`manuscriptfreeze`）", **base)
    return _reading("manuscript", rel_text, state=ACTIVE, raw=base["sign_state"],
                    why="没签、所属命题没退休 ⇒ 还能写", **base)


def active_plans(store: Any, *, owner: Any = None, problem_key: Any = None
                 ) -> dict[str, Any]:
    """活跃计划集（K3/K4 的计数入口）：返回 `{checked, kind, total, active,
    ids, rows, unjudged, checked_plans, why}`。

    - `owner` 给了就只算 `created_by == owner` 的那些（并发上限的分桶口径）；
    - `problem_key` 给了就只看同一难题键；
    - `active` 是活跃条的读数（`ids` 与 `rows` 只含活跃行，顺序按 `plan_id`）；
    - `unjudged` 是「状态判不了」的那些行（`checked=False`），不进活跃集；
    - 台账读不出来 ⇒ `checked=False` + 空集（不是「一条活跃的都没有」）。
    """
    out: dict[str, Any] = {"checked": False, "kind": "plan", "total": 0, "active": 0,
                           "ids": [], "rows": [], "unjudged": [], "checked_plans": 0,
                           "why": ""}
    try:
        rows = [dict(r) for r in store.rows("attack_plans")]
    except Exception as exc:  # noqa: BLE001 —— 台账读不出来是「没查成」
        out["why"] = f"`attack_plans` 读不出来（{type(exc).__name__}: {exc}）⇒ 活跃集没查成"
        return out
    owner_text = "" if owner is None else str(owner)
    key_text = "" if problem_key is None else str(problem_key)
    kept, unjudged = [], []
    considered = 0
    for row in rows:
        if owner_text and str(row.get("created_by") or "") != owner_text:
            continue
        if key_text and str(row.get("problem_key") or "") != key_text:
            continue
        considered += 1
        reading = state_of_plan(row)
        if not reading.get("checked"):
            unjudged.append({"plan_id": str(row.get("plan_id") or ""),
                             "status": str(row.get("status") or ""),
                             "why": str(reading.get("why") or "")})
            continue
        out["checked_plans"] += 1
        if reading.get("state") == ACTIVE:
            kept.append(row)
    kept.sort(key=lambda r: str(r.get("plan_id") or ""))
    out.update(checked=True, total=considered, active=len(kept),
               ids=[str(r.get("plan_id") or "") for r in kept], rows=kept,
               unjudged=unjudged,
               why=(f"活跃计划 {len(kept)} 条（候选 {considered} 条）"
                    + (f"；状态判不了 {len(unjudged)} 条（未计入活跃集）"
                       if unjudged else "")))
    return out


def plan_is_active(row: Any) -> bool:
    """这一行计划现在还在活跃集里吗（`state_of_plan` 的薄包装，供判据读）。"""
    return is_active(state_of_plan(row))


__all__ = [
    "ACTIVE", "COMPLETED", "ABANDONED",
    "PLAN_COMPLETED_STATUSES", "PLAN_STATE_OF",
    "STATEMENT_ACTIVE_STATUSES", "STATEMENT_COMPLETED_STATUSES", "STATEMENT_STATE_OF",
    "is_active", "plan_is_active",
    "state_of_plan", "state_of_statement", "state_of_manuscript",
    "active_plans",
]

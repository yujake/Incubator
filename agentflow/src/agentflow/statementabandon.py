# -*- coding: utf-8 -*-
"""「放弃原命题」的标记与写入口：`abandoned@<ISO8601>@<理由>`。

业主 2026-11-01 逐字裁定：

> 「每个命题和证明的产出最终必须以V签收尾，拿不到V签就得一直改，或者放弃原命题」

于是"已登记的命题"只许落在两处：有 V 签，或明确放弃（带理由与时间）。
"明确"这个词在盘上要有载体，否则 `status="abandoned"` 只是换了一个字面量：
一条被标成放弃、却读不出为什么、也不知道什么时候放弃的命题，与"悬着"没有区别
（读的人既没法复核，也没法回答"这件事是几时被放下的"）。

本模块是这件事的唯一实现：`abandon_marker`（拼装）、`parse_abandon`（解析）、
`apply_abandonment`（写：改状态 + 落理由与时间 + 作废重送义务）。`schema` 的
数据面校验与 `closing` 的两格读数都从这里取，不各写一份。

## 为什么标记住在 `quote_reason`，而不是新加两列

同一张表的 `pending_definition`（`draft/93·续` D12 甲）已经用同一套手法把
"为什么空着、谁来补"写进 `quote_reason` 的受控标记（`concept:pending_search` /
`concept:self_authored`，唯一出处是 `migrate_concepts`），由 `schema.Statement.validate`
逐条核。这里照抄那一条纪律：不新增列（新增列就是改磁盘契约，属 FC-27 的
schema 迁移，能不做就不做），标记的写侧（`abandon_marker`）与读侧
（`parse_abandon`）只此一份实现，`schema` 与 `closing` 都从这里取 ——
两处各写一份正则，"什么算明确放弃"就会在两个出口长出两种答案。

## 形状与三态

`abandoned@2026-11-01T21:10:00+08:00@证明第 5 步补不出来，改不动了`

- 时间必须是 `datetime.fromisoformat` 认得的 ISO8601（带不带时区都行，带更好）；
- 理由非空；理由里允许再出现 `@`（只切前两刀），也允许中文与换行；
- `parse_abandon` 的三态：`checked=True` = 是一条可解析的放弃标记；
  `checked=False` + `why` = 不是（空、前缀不对、时间坏了、理由空）。
  `checked=False` 绝不是"没有放弃"——它说的是"这一行自称放弃，而拿不出理由与时间"，
  那种行在收工读数里按未签计（`statements_unsigned` 的
  `abandoned_without_reason` 那一类），而不是按"已放弃"放行。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping

#: 标记前缀。它与 `schema.STATEMENT_STATUSES` 里的 `abandoned` 同源命名：
#: 状态那一格说"这一行放弃了"，这一格说"为什么、什么时候"。
ABANDON_MARKER = "abandoned@"

#: 字段分隔符：`<前缀><ISO8601><分隔符><理由>`。
ABANDON_SEP = "@"


def abandon_marker(*, at: str, reason: str) -> str:
    """拼一条放弃标记（写侧唯一实现）。理由为空 ⇒ `ValueError`（不许静默丢理由）。

    为什么时间由调用方给而不是在这里取 `now()`：这一格要能被判据钉死
    （测试里两条一模一样的输入必须给出同一个字符串），"现在几点"的来源留在调用点。
    """
    got = str(reason or "").strip()
    if not got:
        raise ValueError(
            "放弃必须给理由：只写一个 status='abandoned' 等于把'为什么放下'记成一笔"
            "没人能接手的账（与 `quote_verified` 的三态纪律同一条）")
    stamp = str(at or "").strip()
    try:
        datetime.fromisoformat(stamp)
    except ValueError as exc:
        raise ValueError(
            f"放弃标记的时间必须是 ISO8601（收到 {stamp!r}）：{exc}") from exc
    return f"{ABANDON_MARKER}{stamp}{ABANDON_SEP}{got}"


def parse_abandon(text: Any) -> dict[str, Any]:
    """读一条放弃标记（读侧唯一实现）：`{"checked","at","reason","why"}`。

    三态见模块 docstring：`checked=False` 说的是"这不是一条可解析的放弃标记"，
    不是"没有放弃"。
    """
    out: dict[str, Any] = {"checked": False, "at": "", "reason": "", "why": ""}
    raw = str(text or "").strip()
    if not raw:
        out["why"] = "`quote_reason` 是空的 ⇒ 拿不出理由与时间"
        return out
    if not raw.startswith(ABANDON_MARKER):
        out["why"] = (f"`quote_reason` 不以 {ABANDON_MARKER!r} 开头"
                      f"（收到 {raw[:40]!r}）⇒ 这不是一条放弃标记")
        return out
    rest = raw[len(ABANDON_MARKER):]
    stamp, sep, reason = rest.partition(ABANDON_SEP)
    stamp, reason = stamp.strip(), reason.strip()
    if not sep:
        out["why"] = (f"标记缺第二刀：要 `{ABANDON_MARKER}<ISO8601>{ABANDON_SEP}<理由>`，"
                      f"收到 {raw[:60]!r}")
        return out
    out["at"] = stamp
    try:
        datetime.fromisoformat(stamp)
    except ValueError:
        out["why"] = (f"标记里的时间不是 ISO8601（{stamp!r}）⇒ 读不出「什么时候放弃的」")
        return out
    if not reason:
        out["why"] = "标记里有时间没有理由 ⇒ 读不出「为什么放弃」"
        return out
    out.update(checked=True, reason=reason)
    return out


def _statement_of(row: Mapping[str, Any]) -> Any:
    """盘上那一行 ⇒ `schema.Statement`（`page_range` 是唯一需要还原的对象字段）。"""
    from . import schema as _S

    body = dict(row)
    pr = body.get("page_range")
    body["page_range"] = (_S.PageRange.from_dict(pr) if isinstance(pr, Mapping)
                          else _S.PageRange())
    return _S.Statement(**{k: v for k, v in body.items()
                           if k in _S.Statement.__dataclass_fields__})


def apply_abandonment(store: Any, *, statement_id: str, reason: str, at: str = "",
                      actor: str = "secretary-B") -> dict[str, Any]:
    """把一条已登记命题标成 `abandoned`（写侧唯一实现：理由与时间一起落盘）。

    这是业主 2026-11-01 那句「拿不到V签就得一直改，或者放弃原命题」里
    "放弃"那一条的落地：它把命题从"还欠一个签"的集合里挪走，同时也把名下开着的
    重送义务作废（`vreceipts.close_resubmits_for`，`close="expired"`）—— 不一起办，
    "放弃"会被"名下还有未消的板项"反锁死（`retire_integrity`）。

    返回 `{"checked","abandoned","already","stmt_id","at","reason","marker",
    "changes","refused","why","resubmits","row"}`。三态：

    - `checked=True`：写成了（`abandoned=True`），或本来就是这一档（`already=True`，幂等）；
    - `checked=False` + `refused`：不在册 / 没有 store / 理由空 / 标记拼不出来 ⇒ 一个字节
      都没写（受控拒绝，不是异常）；
    - 校验一律过 `schema.Statement.validate`（数据面唯一判据），这里不另立一份。
    """
    out: dict[str, Any] = {"checked": False, "abandoned": False, "already": False,
                           "stmt_id": str(statement_id or ""), "at": "", "reason": "",
                           "marker": "", "changes": [], "refused": "", "why": "",
                           "resubmits": {}, "row": {}}
    sid = str(statement_id or "").strip()
    if not sid:
        out.update(refused="abandon_missing_id",
                   why="没给命题号 ⇒ 不知道放弃哪一条（不猜）")
        return out
    if store is None:
        out.update(refused="store_unavailable",
                   why="这一层没有 store ⇒ 写不了（不是「已经放弃」）")
        return out
    # 时间由写侧盖：（缺省）取盘上的 now，不接受"没有时间"的放弃 ——
    # 业主这一条要求"带理由与时间"，把时间交给调用方去填是把它变成可选项。
    stamp = str(at or "").strip()
    if not stamp:
        from . import schema as _S

        stamp = _S.now_iso()
    try:
        marker = abandon_marker(at=stamp, reason=str(reason or ""))
    except ValueError as exc:
        out.update(refused="abandon_marker_invalid", why=str(exc))
        return out
    got = parse_abandon(marker)
    out.update(at=str(got.get("at") or ""), reason=str(got.get("reason") or ""),
               marker=marker)
    try:
        current = next((dict(r) for r in store.rows("statements")
                        if str(r.get("stmt_id") or "") == sid), None)
    except Exception as exc:  # noqa: BLE001
        out.update(refused="statements_unreadable",
                   why=f"`statements` 读不出来（{type(exc).__name__}: {exc}）⇒ 没查成")
        return out
    if current is None:
        out.update(refused="abandon_unknown_statement",
                   why=f"命题 {sid} 不在册 ⇒ 放弃一条不存在的命题（不新建行）")
        return out
    if str(current.get("status") or "") == "abandoned":
        was = parse_abandon(current.get("quote_reason"))
        if was.get("checked"):
            out.update(checked=True, abandoned=True, already=True,
                       at=str(was.get("at") or ""), reason=str(was.get("reason") or ""),
                       marker=str(current.get("quote_reason") or ""),
                       row=current, why="这一条早就是 abandoned（幂等：不改任何格）")
            out["resubmits"] = close_resubmits(store, statement_id=sid,
                                               why="命题被明确放弃（幂等重放）")
            return out
    row = dict(current)
    row["status"] = "abandoned"
    row["quote_reason"] = marker
    try:
        stmt = _statement_of(row)
        stmt.validate()
    except ValueError as exc:
        out.update(refused="abandon_invalid_row", why=f"这一行过不了数据面校验：{exc}")
        return out
    from . import schema as _S

    data = stmt.to_dict()
    if str(current.get("status") or "") != "abandoned":
        out["changes"] = [f"status: {current.get('status')} → abandoned",
                          f"quote_reason: {str(current.get('quote_reason') or '')[:40]!r} "
                          f"→ {marker[:60]!r}"]
    try:
        with store.tx("statements", actor=str(actor or "secretary-B"),
                      note=f"statement:abandoned:{got.get('at')}") as tx:
            live = next((r for r in tx.rows("statements")
                         if str(r.get("stmt_id") or "") == sid), None)
            if live is None:
                out.update(refused="abandon_unknown_statement",
                           why=f"命题 {sid} 在写事务里不见了 ⇒ 整笔不写")
                return out
            tx.upsert("statements", data, note="statement:abandoned")
    except ValueError as exc:
        out.update(refused="abandon_write_refused", why=str(exc))
        return out
    except Exception as exc:  # noqa: BLE001
        out.update(refused="abandon_write_failed",
                   why=f"写不进去（{type(exc).__name__}: {exc}）⇒ 一行都没改")
        return out
    out.update(checked=True, abandoned=True, row=data,
               why=(f"命题 {sid} 已明确放弃（{got.get('at')}）：理由已随标记落盘，"
                    "名下开着的重送义务一并作废"))
    out["resubmits"] = close_resubmits(store, statement_id=sid,
                                       why=f"命题 {sid} 被明确放弃：{got.get('reason')}")
    return out


def close_resubmits(store: Any, *, statement_id: str, why: str) -> dict[str, Any]:
    """把一条命题名下的重送义务作废（`vreceipts` 的同一份实现，惰性引用避开环）。"""
    try:
        from . import vreceipts as _VRC

        return _VRC.close_resubmits_for(store, statement_id=str(statement_id), why=str(why))
    except Exception as exc:  # noqa: BLE001 —— 作废失败不许带走"放弃"这件事本身
        return {"checked": False, "closed": [], "problems": [f"{type(exc).__name__}: {exc}"],
                "reason": "重送项作废没跑成（放弃这一笔已经落盘）"}


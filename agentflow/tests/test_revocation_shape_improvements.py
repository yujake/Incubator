# -*- coding: utf-8 -*-
"""撤销的三处形态改进（业主 2026-11-06：「均按建议」，甲 / 乙 / 丙）。

## 三件（业主逐字）

```
甲 查看与修改不该是"两步"：conductor.board / conductor.patrol 的每一项要能直接看出
   这一条能不能被撤（并给出"撤它该用哪个动作"的提示），让模型不必自己把
   items[].id 搬到 void_items 那一步去猜
乙 撤销时自动投一条通知给收件人（系统发出、不要 ack）：
   「你名下 t-xxxxx（<summary>）已被 <by> 撤销（理由：…），你不需要再处理它」
丙 撤销后那一行不该再看着像欠一个 ack：
   把 expects 处理掉（能置空就置空；schema 不允许就加一格 expects_was 留史）
   并在 docstring 写清
```

## 这一份钉住什么

| 格 | 用例 |
|---|---|
| 甲 | `test_a_board_and_patrol_items_carry_the_revocability_reading` |
| 甲 · 反真空 | `test_a2_stubbing_the_authority_check_to_always_allow_turns_the_denied_cases_red` |
| 乙 | `test_b_revocation_reaches_the_recipient_without_posting_a_row` |
| 乙 · 反真空 | `test_b2_opening_the_old_notice_row_turns_the_new_criterion_red` |
| 丙 | `test_c_the_revoked_row_no_longer_owes_an_ack` |
| 丙 · schema | `test_c2_expects_was_is_the_only_door_to_an_empty_expects` |

## 乙在 2026-11-09（D13）之后换了落法（这一节改过，理由逐字留在这里）

改前：撤销成功 ⇒ 另落一条 `kind="notice"` 的新行（`done` + `expired`、`expects=""`、
`called_by="system"`、`input_key="revoke-notice@<被撤项>"`）。当时的论证是
「通知不能是一条开着的待办（`ITEM_EXPECTS` 只有 ack/work 两档），所以落成已收口的一行」。

那一条把「不欠 ack」办对了，但留下另一个病灶：撤 N 条就多 N 行 —— 真机 11:09:10
M 撤 12 条，`tasks` 里就多出 t-000095..t-000106 十二行。而板项行的 `status` 恒为
`pending`（`conductor._item_row` 写死），叠上 D12 的投影，那十二行在页面上就是
「十二个新待办」⇒ 业主的观感是「越清越多」。

业主 2026-11-09 的口径：撤销动作不再自己生成待 ack 通知，判据是
**撤销 N 条之后新增 notice 行 = 0**。所以现在：

- 提醒的载体是**被撤那一行自己的** `inputs`（`revoke:expired:by=…:owner=…:from=…:
  to=done:at=…:reason=…`，append-only 六格）；
- 收件人那一侧的读口是 `Conductor.revoked_recent_of`（`agent_loop.mailbox_digest`
  每一拍渲染成【最近被撤销的项】），`void_items` 返回的 `notified` 逐条写明
  `carrier="revoked_recent@<收件人>"`；
- 旧行为留在 `Conductor.REVOKE_POSTS_NOTICE_ROW`（默认 `False`），只给 b2 的反真空用。
  详细判据在新文件 `tests/test_revocation_posts_no_new_notice_rows.py`。

下面这段是改前那套论证，逐字保留（读的人要知道「为什么曾经那样做」）：

## 为什么改前那条通知是"已收口"的一行（不是一条开着的新待办）

通知的语义是「你不需要再处理它」：它不能产生任何一种动作义务。
本仓 `ITEM_EXPECTS` 只有 `ack` / `work` 两档（冻结面，`agent_loop.deliver_v_verdicts`
的 docstring 逐字写着"不许新增档"），所以一条开着的通知只能是：
① `expects=ack` ⇒ 收件人欠一个回执（与「不需要 ack」正相反），而且它会在销号闸里
   冒充"名下还有未消的板项"（`conductor.retire_child` 读的就是"kind 非空且 done 之前"）；
② 造一个新的 `expects` 取值 ⇒ 冻结面被新增一档。
两条都不是这份裁定要的。所以改前那条通知以「已收口（`expired`）」落行：它是一份记录，
不是一条待办 —— `open_items_of` 看不见它，`ack_items` 收不掉它（也不是它该收的），
板的两个计数一个都不动（既有判据 `test_the_board_readings_drop_the_revoked_item_at_once`
要求撤销后计数恰好少 1，这一条同时守着通知不许冒充待办）。

## 丙的 schema 依据（判"能不能置空"，不是猜）

`schema.Task.validate`（改前）：`kind` 非空 ⇒ `expects` 必须 ∈ `ITEM_EXPECTS`，
没有空串这一档。所以撤销后"把 expects 置空"必须先给 schema 一条窄门。本笔的窄门
只开在 `item_state="done"` 且 `item_close="expired"` 的行上（那一档本来就回答
"这条永远不会再被处理"，`expects` 在那一行上不再承担任何义务），并新增
`expects_was` 记原值；其余任何行（`queued` / `seen` / `block`）的 `expects` 
仍然只许 `ack` / `work`。判据见 `test_c2_...` 的正负控。
"""
from __future__ import annotations

import pathlib
from typing import Any, Mapping

from agentflow import agent_loop as AL
from agentflow import schema as S
from agentflow.conductor import Conductor, LocalBackend, calling_as
from agentflow.store import Store
from agentflow.tools import build_registry
from agentflow.tools import conductor_tools as CT


# ---------------------------------------------------------------- 夹具


def _workspace(tmp_path: pathlib.Path) -> tuple[pathlib.Path, Conductor]:
    """M（根）→ D1（父）→ F1 / F2（兄弟）；F1 → G1（孙代）。"""
    ws = tmp_path / "ws"
    ws.mkdir(parents=True, exist_ok=True)
    st = Store(ws)
    st.init()
    return ws, Conductor(st, policy=None, backend=LocalBackend({}))


def _agent(box: Conductor, *, role: str, parent: str | None, detail: str,
           status: str = "running") -> str:
    ended = None if status in ("pending", "running") else "2026-11-06T08:00:00+08:00"
    return box._write_new_row({
        "role": role, "action": "run", "called_by": (parent and "M") or "user",
        "parent_task_id": parent, "depth": (1 if parent is None else 2),
        "input_key": f"test:{role}:{detail}", "status": status,
        "outcome": ("ok" if status == "done" else None),
        "refusal_reason": None, "instance": "", "detail": detail, "error": None,
        "started_at": "2026-11-06T08:00:00+08:00", "ended_at": ended,
        "tokens": 0, "usd": 0.0, "artifacts": [], "inputs": [],
        "kind": "", "expects": "", "item_state": "", "item_close": "",
        "seen_by": "", "seen_step": None, "keep_alive": False,
    }, note=f"test:agent:{role}")


def _item(box: Conductor, *, owner: str, role: str, expects: str,
          kind: str, summary: str) -> str:
    return box.open_item(kind=kind, role=role, expects=expects, action=kind,
                         summary=summary, called_by="test", parent_task_id=owner,
                         depth=2, input_key=f"test:{kind}:{owner}")


def _hierarchy(tmp_path: pathlib.Path) -> tuple[pathlib.Path, Conductor,
                                                dict[str, str]]:
    ws, box = _workspace(tmp_path)
    ids = {"M": _agent(box, role="M", parent=None, detail="顶趟"),
           "D1": "", "F1": "", "F2": "", "G1": ""}
    ids["D1"] = _agent(box, role="D", parent=ids["M"], detail="D1")
    ids["F1"] = _agent(box, role="F", parent=ids["D1"], detail="F1")
    ids["F2"] = _agent(box, role="F", parent=ids["D1"], detail="F2")
    ids["G1"] = _agent(box, role="G", parent=ids["F1"], detail="G1")
    return ws, box, ids


def _row(box: Conductor, item_id: str) -> dict[str, Any]:
    return next(dict(r) for r in box._tasks()
                if str(r.get("task_id") or "") == str(item_id))


def _board_item(box: Conductor, item_id: str, *, viewer: str) -> dict[str, Any]:
    """`conductor.board` 那一条的读数（按某个看的人算）。"""
    view = box.board_view(limit=100, by_task_id=viewer)
    return next(dict(r) for r in (view.get("board_open_items") or ())
                if str(r.get("task_id") or "") == str(item_id))


def _notices_of(box: Conductor, owner: str) -> list[dict[str, Any]]:
    return [dict(r) for r in box._tasks()
            if str(r.get("parent_task_id") or "") == str(owner)
            and str(r.get("input_key") or "").startswith("revoke-notice@")]


# ---------------------------------------------------------------- 甲 —— 能否撤销


def _a_problems(tmp_path: pathlib.Path) -> list[str]:
    """(甲) 的判据本体：一条项的 revoke 格按看的人给出可否与动作。"""
    problems: list[str] = []
    ws, box, ids = _hierarchy(tmp_path)
    # 与 F1 那一条完全无关的另一支（M 的另一个直接子）：它既不是父、也不是兄弟，
    # 更不是 F1 名下的人 —— "无关者"这一例必须真是无关的，不许拿 F1 的子（G1）顶替。
    unrelated_id = _agent(box, role="D", parent=ids["M"], detail="另一支（无关）")
    item = _item(box, owner=ids["F1"], role="F", expects="work",
                 kind="delegation", summary="一条待撤的活")

    m = _board_item(box, item, viewer=ids["M"]).get("revoke") or {}
    parent = _board_item(box, item, viewer=ids["D1"]).get("revoke") or {}
    sibling = _board_item(box, item, viewer=ids["F2"]).get("revoke") or {}
    child = _board_item(box, item, viewer=ids["G1"]).get("revoke") or {}
    unrelated = _board_item(box, item, viewer=unrelated_id).get("revoke") or {}

    if m.get("revocable") is not True or parent.get("revocable") is not True:
        problems.append(f"M / 直接父应当看得到可撤：M={m!r} 父={parent!r}")
    if sibling.get("revocable") is not False:
        problems.append(f"兄弟（F2）不该看得到可撤：{sibling!r}")
    if child.get("revocable") is not False:
        problems.append(f"名下的子（G1）不该看得到可撤父母那一层的项：{child!r}")
    if unrelated.get("revocable") is not False:
        problems.append(f"无关者（另一支）不该看得到可撤：{unrelated!r}")
    # "撤它该用哪个动作"：动作名 + 可照抄的 args（不让模型自己搬 id）
    if m.get("action") != "conductor.void_items":
        problems.append(f"可撤那一档没有给出动作名：{m!r}")
    call = dict(m.get("call") or {})
    if call.get("item_ids") != [item]:
        problems.append(f"可撤那一档没有把 item_ids 填好（模型还得自己搬 id）：{m!r}")
    if "why" not in call:
        problems.append(f"可撤那一档没有给 why 的占位（留痕必填）：{m!r}")
    if m.get("mode") != Conductor.ITEM_AUTHORITY_CONDUCTOR:
        problems.append(f"M 那一档的 mode 不对：{m!r}")
    if parent.get("mode") != Conductor.ITEM_AUTHORITY_PARENT:
        problems.append(f"父那一档的 mode 不对：{parent!r}")
    if "直接父代理" not in str(sibling.get("why") or ""):
        problems.append(f"拒绝那一档没有说清凭什么拒：{sibling!r}")

    # patrol 的那个子格（`_board_cell`）必须带同一格（board / patrol 是两个面）
    cell = CT._board_cell(box, ids["F1"], by_task_id=ids["D1"])
    row = next((dict(r) for r in (cell.get("items") or ())
                if str(r.get("id") or "") == str(item)), {})
    if (row.get("revoke") or {}).get("revocable") is not True:
        problems.append(f"patrol 的 board.items 没有带可撤读数：{row!r}")
    return problems


def test_a_board_and_patrol_items_carry_the_revocability_reading(
        tmp_path: pathlib.Path) -> None:
    """甲：board / patrol 的每一项都带 revoke 格；M / 直接父看得到，兄弟 / 子 / 无关者看不到。"""
    assert _a_problems(tmp_path) == [], _a_problems(tmp_path)


def test_a2_stubbing_the_authority_check_to_always_allow_turns_the_denied_cases_red(
        tmp_path: pathlib.Path, monkeypatch: Any) -> None:
    """甲 · 反真空：把权限判据打桩成恒真 ⇒ 兄弟 / 无关者那两例当场红。"""
    assert _a_problems(tmp_path / "a0") == []

    def _allow(self: Conductor, rows: Mapping[str, Mapping[str, Any]], *,
               by_task_id: str, row: Mapping[str, Any]) -> dict[str, Any]:
        return {"checked": True, "allowed": True, "mode": "stub",
                "by": str(by_task_id), "owner": str(row.get("parent_task_id") or ""),
                "code": "", "why": "打桩：恒有权限"}

    monkeypatch.setattr(Conductor, "_item_authority", _allow)
    problems = _a_problems(tmp_path / "a1")
    assert problems, "权限判据被打桩成恒真，兄弟 / 无关者那两例却仍然绿 ⇒ 判据没在看权限"
    assert any("兄弟" in p or "无关者" in p for p in problems), problems


# ---------------------------------------------------------------- 乙 —— 自动提醒


def _b_problems(tmp_path: pathlib.Path) -> list[str]:
    """(乙) 的判据本体：撤销之后收件人**不**多一行，而提醒仍然读得到。"""
    problems: list[str] = []
    ws, box, ids = _hierarchy(tmp_path)
    item = _item(box, owner=ids["F1"], role="F", expects="ack",
                 kind="notice", summary="到点通知：不再需要做")
    before = len(box._tasks())
    got = box.void_items([item], by_task_id=ids["D1"],
                         why="方向已砍", revoke=True)
    if got.get("voided") != [item]:
        problems.append(f"撤销本身没成：{got!r}")
        return problems
    after = len(box._tasks())
    if after != before:
        problems.append(
            f"撤销多落了 {after - before} 行 tasks（2026-11-09 D13：清理不该让台账变长）")
    if _notices_of(box, ids["F1"]):
        problems.append(f"收件人名下多出了撤销通知行：{_notices_of(box, ids['F1'])!r}")
    # 提醒没丢：收件人那一侧的读口读得到那一条（编号 / 谁撤的 / 理由 / 摘要）
    cell = list(box.revoked_recent_of(ids["F1"], limit=5))
    if len(cell) != 1:
        problems.append(f"收件人那一侧的「最近被撤销」应当恰好多一条，实测 {cell!r}")
        return problems
    entry = dict(cell[0])
    if (entry.get("item_id"), entry.get("by"), entry.get("reason"), entry.get("summary")) != (
            item, ids["D1"], "方向已砍", "到点通知：不再需要做"):
        problems.append(f"提醒的五格不对：{entry!r}")
    # 返回读数逐条写明载体：不是一行新台账
    notified = list(got.get("notified") or ())
    if len(notified) != 1 or str(notified[0].get("item_id")) != str(item):
        problems.append(f"`notified` 没有把这一条算进去：{notified!r}")
    elif str(notified[0].get("carrier")) != f"revoked_recent@{ids['F1']}":
        problems.append(f"`notified` 没有写明提醒的载体：{notified[0]!r}")
    if notified and "你不需要再处理它" not in str(notified[0].get("text") or ""):
        problems.append(f"提醒正文不是那一句：{notified[0]!r}")
    # 它不产生 ack 义务：既不在未消项里，也没留下一条可 ack 的项
    if str(item) in {str(r.get("task_id")) for r in box.open_items_of(ids["F1"])}:
        problems.append("被撤项还挂在收件人的未消项里 ⇒ 它会冒充欠一个 ack")
    return problems


def test_b_revocation_reaches_the_recipient_without_posting_a_row(
        tmp_path: pathlib.Path) -> None:
    """乙（改后）：撤销 ⇒ 收件人名下不多一行，提醒仍读得到（载体是被撤行自己的留痕）。"""
    assert _b_problems(tmp_path) == [], _b_problems(tmp_path)


def test_b2_opening_the_old_notice_row_turns_the_new_criterion_red(
        tmp_path: pathlib.Path, monkeypatch: Any) -> None:
    """乙 · 反真空：把旧行为（另落一条通知行）打开 ⇒ (乙) 那条判据当场红。"""
    assert _b_problems(tmp_path / "b0") == []
    monkeypatch.setattr(Conductor, "REVOKE_POSTS_NOTICE_ROW", True)
    problems = _b_problems(tmp_path / "b1")
    assert problems, "旧行为打开了，(乙) 却仍然绿 ⇒ 那条判据没在数行"
    assert any("多落了" in p or "通知行" in p for p in problems), problems


# ---------------------------------------------------------------- 丙 —— expects 处理


def _c_problems(tmp_path: pathlib.Path) -> list[str]:
    """(丙) 的判据本体：撤销后那一行不再有任何读侧把它当 ack 项。"""
    problems: list[str] = []
    ws, box, ids = _hierarchy(tmp_path)
    item = _item(box, owner=ids["F1"], role="F", expects="ack",
                 kind="notice", summary="一条通知")
    before_board = int(box.board_view(limit=100, by_task_id=ids["M"])["board_open_count"])
    before_cell = int(CT._board_cell(box, ids["F1"], by_task_id=ids["M"])["child_open_count"])

    got = box.void_items([item], by_task_id=ids["D1"], why="撤销", revoke=True)
    if got.get("voided") != [item]:
        problems.append(f"撤销本身没成：{got!r}")
        return problems
    row = _row(box, item)
    if str(row.get("expects") or "") != "":
        problems.append(f"撤销后那一行的 expects 仍然非空：{row.get('expects')!r}")
    if str(row.get("expects_was") or "") != "ack":
        problems.append(f"expects 的原值没有留在 expects_was：{row.get('expects_was')!r}")
    if (str(row.get("item_state") or ""), str(row.get("item_close") or "")) != ("done", "expired"):
        problems.append(f"撤销的收口不是 done/expired：{row.get('item_state')!r}/"
                        f"{row.get('item_close')!r}")
    # 读侧：未消项、板面、patrol 都不再数它
    if str(item) in {str(r.get("task_id")) for r in box.open_items_of(ids["F1"])}:
        problems.append("撤销后它仍然挂在 open_items_of 里（仍像一条待办）")
    if int(box.board_view(limit=100, by_task_id=ids["M"])["board_open_count"]) != before_board - 1:
        problems.append("撤销后 board_open_count 没有恰好少 1")
    if int(CT._board_cell(box, ids["F1"], by_task_id=ids["M"])["child_open_count"]) != before_cell - 1:
        problems.append("撤销后 patrol 的 child_open_count 没有恰好少 1")
    # `ack_items` 不把空 expects 的行当 ack 项：它必须拒（而不是收掉）
    acked = box.ack_items([item], by_task_id=ids["F1"], close="acked")
    if acked.get("ok") or str(acked.get("state")) == "acked":
        problems.append(f"`ack_items` 仍然把撤销后的行当 ack 项收掉了：{acked!r}")
    if [str(x.get("code") or "") for x in (acked.get("refused") or ())] != ["bad_close"]:
        problems.append(f"`ack_items` 的拒信不是 bad_close（expects 空与 acked 不配对）：{acked!r}")
    # 渲染侧：撤销后的行不在这一拍的板摘要里（done 的行不进 `board_digest`）
    _text, ids_shown, _probs = AL.board_digest(box, my_task_id=ids["F1"])
    if str(item) in [str(x) for x in ids_shown]:
        problems.append("撤销后的行仍然被渲染进提示词（会被读成待办）")
    return problems


def test_c_the_revoked_row_no_longer_owes_an_ack(tmp_path: pathlib.Path) -> None:
    """丙：撤销 ⇒ expects 清空、expects_was 留原值；没有任何读侧再把它当 ack 项。"""
    assert _c_problems(tmp_path) == [], _c_problems(tmp_path)


def test_c2_expects_was_is_the_only_door_to_an_empty_expects() -> None:
    """丙的 schema 依据：空 expects 只开在 done/expired 上；expects_was 不许伪造／并存。"""
    base = dict(task_id="t-900001", role="F", action="notice", called_by="system",
                status="pending", detail="x", depth=2,
                kind="notice", expects_was="ack", expects="",
                item_state="done", item_close="expired")
    S.Task(**base).validate()          # 正控：撤销后的那一行

    bad_open = dict(base, item_state="queued", item_close="")
    try:
        S.Task(**bad_open).validate()
    except ValueError:
        pass
    else:
        raise AssertionError("expects 为空却不在 done/expired 上，schema 居然放过了")

    both = dict(base, expects="ack")
    try:
        S.Task(**both).validate()
    except ValueError:
        pass
    else:
        raise AssertionError("expects 与 expects_was 同时非空，schema 居然放过了")

    bogus = dict(base, expects_was="whatever")
    try:
        S.Task(**bogus).validate()
    except ValueError:
        pass
    else:
        raise AssertionError("expects_was 不在 ITEM_EXPECTS 里，schema 居然放过了")


# ---------------------------------------------------------------- 接线 —— 工具路


def test_d_the_tool_route_carries_the_same_three_shapes(tmp_path: pathlib.Path) -> None:
    """接线：`conductor.board` 走调用身份算出 revoke 格；撤销工具把通知读数带回 meta。"""
    ws, box, ids = _hierarchy(tmp_path)
    item = _item(box, owner=ids["F1"], role="F", expects="ack",
                 kind="notice", summary="一条通知")
    reg = build_registry(store=box.store, conductor=box, workspace_root=ws).registry
    reg.bound_role = "M"
    with calling_as(ids["M"]):
        board = dict(reg.call("conductor.board", {"limit": 100}).data or {})
        mine = next((dict(r) for r in (board.get("board_open_items") or ())
                     if str(r.get("task_id") or "") == str(item)), {})
        assert (mine.get("revoke") or {}).get("revocable") is True, mine
        res = reg.call("conductor.void_items", {"item_ids": [item],
                                                 "why": "撤掉这一条"})
    data = dict(res.data or {})
    assert data.get("voided") == [item], data
    notified = list((res.meta or {}).get("notified") or ())
    assert len(notified) == 1 and str(notified[0].get("item_id")) == str(item), (
        "撤销工具的 meta 里没有把『通知已投』这件事带回来", res.meta)
    assert _row(box, item).get("expects") == ""

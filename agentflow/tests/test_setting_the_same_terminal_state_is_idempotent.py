# -*- coding: utf-8 -*-
"""Q24：同一终态重复设置是幂等命中（不是错误）；倒退照旧拒。

## 这一件修的是什么

`Conductor._set_item` 原判据只有一句 `if want <= have: return "", "…已经到过…"` ——
它把"倒退"与"同一格重复设置"折成同一句话。D12 之后信息型板项在渲染那一拍就由
`_settle_if_informational` 收口成 `done`，随后 `close_item` / `conductor.ack` 再推一次
`state="done"` ⇒ 撞上那句拒信。红的就是它（改造前实测）：

```
tests/test_a_parent_retires_its_finished_child.py::test_a_child_with_unread_board_items_is_refused
AssertionError: ('', "t-000003 已经到过 'done'（不许倒退或重复迁移）")
判据期望：("done", "")
```

根除落在迁移图（`Conductor.ITEM_MOVES` + `Conductor.item_move`）：逐对给判词，
三列 forward / same / back。幂等与倒退由同一张图判出来，不是另加一句
`want == have: return ok` —— 因为 `seen → seen` 必须照旧被拒（每一步的 `seen_by` /
`seen_step` 都不一样，静默接受就是丢读数）。

## 这一份钉住的判据

| 判据 | 守的是 | 改前红在哪 |
|---|---|---|
| a) `test_a_the_same_terminal_state_is_an_idempotent_hit` | `done` 的项再 `_set_item(done)` ⇒ 成功、`item_state` 不变、`changed=False` | 改前返回 `("", "…已经到过 'done'…")` |
| b) `test_b_seen_to_done_still_moves` | `seen → done` 照旧真迁移（正控：图没把前进也吞掉） | 不适用（改前就绿） |
| c) `test_c_done_to_seen_is_still_refused` | `done → seen` 仍被拒（反真空：倒退不许被幂等吞掉） | 不适用（改前也拒，改后必须继续拒） |
| d) `test_d_stubbing_the_idempotent_hit_makes_a_red` | 反真空：把幂等命中打桩回"照旧报错" ⇒ a 必红 | 不适用 |
| e) `test_e_repeating_seen_is_still_refused` | `seen → seen` 仍拒（既有口径，与 `test_board_items.py:86-88` 同一条） | 不适用 |
| f) `test_f_the_idempotent_hit_writes_nothing` | 命中时 `tasks` 行的字节、盘上表文件的字节、`events` 的事件数都不变 | a 的加强：不许"成功但偷偷又写一次" |
| g) `test_g_the_graph_is_total_and_three_col_valued` | 迁移图穷举 `ITEM_STATES × ITEM_STATES`，且三列都非空 | 不适用（改前没有图） |
| h) `test_h_ack_on_an_already_done_item_reports_already_done_and_writes_nothing` | `ack_items` 的 `already_done` 改由状态机的 `changed=False` 产生，且不追加事件（删掉的那份实现的接续判据） | 不适用（改前靠入口自己判一次） |

三档口径（与既有一致）：`("done","")`＝真迁移/命中都算成；`("", 那一句)`＝拒；
`"ack_unbacked"`＝空口 ack 的读数（状态不动）。
"""
from __future__ import annotations

import json
import pathlib

import pytest

from agentflow import schema as S
from agentflow.conductor import Conductor, LocalBackend
from agentflow.store import Store

#: 一条要模型自己 ack 的项（`v-verdict@` 那一档不在 `INFORMATIONAL_ITEM_KINDS` 的
#: 自动收口里）⇒ `mark_item_seen` 停在 `seen`，`done` 必须由我们显式推一次。
KEY_NEEDS_HAND = "v-verdict@判据@v1"
OWNER = "t-0100"


# ====================================================================== 夹具
def _ws(tmp_path: pathlib.Path) -> tuple[Store, Conductor]:
    st = Store(tmp_path / "ws")
    st.init()
    return st, Conductor(st, policy=None, backend=LocalBackend({}))


def _row(st: Store, task_id: str) -> dict:
    return next(r for r in st.rows("tasks") if str(r.get("task_id")) == str(task_id))


def _row_bytes(row: dict) -> str:
    """一行的字节（键序归一）：比"改了没有"比比字段逐个比更严。"""
    return json.dumps(row, ensure_ascii=False, sort_keys=True, default=str)


def _events(st: Store) -> list[dict]:
    return list(st.read_events())


def _table_bytes(st: Store) -> bytes:
    return (st.data / str(S.TABLES["tasks"]["file"])).read_bytes()


def _hand_item(cond: Conductor, *, summary: str = "一条要先读、再收口的项") -> str:
    """一条 `expects="ack"` 的项：读进来停在 `seen`（不会被同拍收口）。"""
    return cond.open_item(kind="notice", role="M", expects="ack", action="notice",
                          summary=summary, called_by="V",
                          parent_task_id=OWNER, depth=2, input_key=KEY_NEEDS_HAND)


def _done_item(cond: Conductor, st: Store) -> str:
    """一条已经在 `done` 的板项：按生产的次序真迁移一次（`seen → done`）。"""
    item = _hand_item(cond)
    state, why = cond.mark_item_seen(item, by_task_id=OWNER, step=1)
    assert (state, why) == ("seen", ""), (state, why)
    state, why = cond.close_item(item, close="acked", by_task_id=OWNER)
    assert (state, why) == ("done", ""), (state, why)
    assert _row(st, item)["item_state"] == "done"
    return item


# ====================================================================== a) 幂等命中
def _a_problems(st: Store, cond: Conductor, item: str) -> list[str]:
    """(a) 的判据本体：`done` 的项再设一次 `done` ⇒ 成功、状态不变、`changed=False`。

    `item` 由调用方给（不在这里建）：(d) 的反真空要先把夹具建好、再打桩，否则打桩会
    连"把项推到 done"那一步一起打掉 —— 那时测到的就不是幂等那一列了。
    """
    problems: list[str] = []
    state, why, changed = cond._set_item(item, state="done", close="acked", by_task_id=OWNER)
    if (state, why) != ("done", ""):
        problems.append(f"同一终态重复设置被判成错误：state={state!r}、why={why!r}"
                        "（改前形态：`want <= have` 那一支把幂等折成倒退）")
    if changed:
        problems.append("幂等命中却报 changed=True（那一格是'真写了行'的读数）")
    if str(_row(st, item).get("item_state") or "") != "done":
        problems.append(f"命中之后状态变了：{_row(st, item).get('item_state')!r}")
    return problems


def test_a_the_same_terminal_state_is_an_idempotent_hit(tmp_path: pathlib.Path) -> None:
    """a) 正控：`done → done` 成功且状态不动（改前红：返回空状态 + 已经到过）。"""
    st, cond = _ws(tmp_path)
    item = _done_item(cond, st)
    assert _a_problems(st, cond, item) == [], _a_problems(st, cond, item)


# ====================================================================== b) 前进
def test_b_seen_to_done_still_moves(tmp_path: pathlib.Path) -> None:
    """b) 正控：`seen → done` 照旧真迁移（`changed=True`）。"""
    st, cond = _ws(tmp_path)
    item = _hand_item(cond)
    assert cond.mark_item_seen(item, by_task_id=OWNER, step=1) == ("seen", "")
    state, why, changed = cond._set_item(item, state="done", close="acked",
                                         by_task_id=OWNER)
    assert (state, why, changed) == ("done", "", True), (state, why, changed)
    row = _row(st, item)
    assert (row["item_state"], row["item_close"]) == ("done", "acked"), row


# ====================================================================== c) 倒退
def test_c_done_to_seen_is_still_refused(tmp_path: pathlib.Path) -> None:
    """c) 反真空：`done → seen` 仍拒、零写入 —— 倒退不许被"幂等"那一列吞掉。"""
    st, cond = _ws(tmp_path)
    item = _done_item(cond, st)
    before = _row_bytes(_row(st, item))
    state, why, changed = cond._set_item(item, state="seen", by_task_id=OWNER, step=2)
    assert state == "" and "已经到过" in why, (state, why)
    assert changed is False
    assert _row_bytes(_row(st, item)) == before, "被拒的那一笔改写了行"
    assert str(_row(st, item)["item_state"]) == "done"


# ====================================================================== d) 反真空
def test_d_stubbing_the_idempotent_hit_makes_a_red(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """d) 反真空：把"幂等命中"打桩成照旧报错 ⇒ (a) 必红。

    打桩的口子就是迁移图的读数（`Conductor.item_move` 恒回 `back`）—— 这也顺带证明
    (a) 判的红绿确实由那张图决定，而不是由别处某一句 `if` 决定的。
    """
    st, cond = _ws(tmp_path)
    item = _done_item(cond, st)
    assert _a_problems(st, cond, item) == [], "基线必须绿，否则下面的红证明不了任何事"

    def _always_back(cur: str, state: str) -> str:
        return Conductor.ITEM_MOVE_BACK

    monkeypatch.setattr(Conductor, "item_move", staticmethod(_always_back))
    problems = _a_problems(st, cond, item)
    assert problems, "把迁移图打桩成恒拒，(a) 却仍然绿 ⇒ 这条判据没在看迁移图"
    assert any("同一终态重复设置被判成错误" in p for p in problems), problems


# ====================================================================== e) 既有口径
def test_e_repeating_seen_is_still_refused(tmp_path: pathlib.Path) -> None:
    """e) 正控（既有行为的守卫）：`seen → seen` 仍拒 —— 它不是终态，重复读会丢读数。

    同一条口径在 `test_board_items.py::test_skipping_a_state_is_refused_and_writes_nothing`
    里已经钉过一次；这一份把它写进三列的判据里，免得"幂等"被顺手放宽成"同一格都算成功"。
    """
    st, cond = _ws(tmp_path)
    item = _hand_item(cond)
    assert cond.mark_item_seen(item, by_task_id=OWNER, step=1) == ("seen", "")
    state, why = cond.mark_item_seen(item, by_task_id=OWNER, step=2)
    assert state == "" and "已经到过" in why, (state, why)
    row = _row(st, item)
    assert (row["item_state"], row["seen_step"]) == ("seen", 1), row


# ====================================================================== f) 零写入
def test_f_the_idempotent_hit_writes_nothing(tmp_path: pathlib.Path) -> None:
    """f) 反真空（a 的加强）：命中时行、盘上表文件、事件数三者都不许变。

    "成功但偷偷又写了一次"是这一族缺陷的通用形态：状态读数照样对，盘上却多了一笔
    "已收口"事件与一个计数 —— 事后按事件数对账的人会看到两条收口记录。
    """
    st, cond = _ws(tmp_path)
    item = _done_item(cond, st)
    row_before = _row_bytes(_row(st, item))
    table_before = _table_bytes(st)
    events_before = len(_events(st))
    readings_before = dict(cond.board_readings().get("by_state") or {})

    state, why, changed = cond._set_item(item, state="done", close="acked",
                                         by_task_id=OWNER)

    assert (state, why, changed) == ("done", "", False), (state, why, changed)
    assert _row_bytes(_row(st, item)) == row_before, "命中之后行变了（应逐字不变）"
    assert _table_bytes(st) == table_before, "命中之后表文件变了（应一个字节都不写）"
    assert len(_events(st)) == events_before, (
        f"命中之后多了 {len(_events(st)) - events_before} 条事件（应零记账）")
    assert dict(cond.board_readings().get("by_state") or {}) == readings_before, (
        "命中之后板上计数变了（应零记账）")


# ====================================================================== g) 图的形态
def test_g_the_graph_is_total_and_three_col_valued() -> None:
    """g) 迁移图是穷举的、三列都非空、且"同一格"只在终态上算幂等。

    反真空：表一旦退化成"比序数"或补一句 `want == have ⇒ ok`，下面几条里必有一条红。
    """
    pairs = {(a, b) for a in S.ITEM_STATES for b in S.ITEM_STATES}
    assert set(Conductor.ITEM_MOVES) == pairs, (
        "迁移图没有穷举 ITEM_STATES × ITEM_STATES："
        f"缺 {sorted(pairs - set(Conductor.ITEM_MOVES))}、"
        f"多 {sorted(set(Conductor.ITEM_MOVES) - pairs)}")
    cols = {Conductor.ITEM_MOVE_FORWARD, Conductor.ITEM_MOVE_SAME, Conductor.ITEM_MOVE_BACK}
    assert set(Conductor.ITEM_MOVES.values()) == cols, (
        f"判词不只三列：{sorted(set(Conductor.ITEM_MOVES.values()))}")
    for col in sorted(cols):
        assert any(v == col for v in Conductor.ITEM_MOVES.values()), (
            f"{col} 这一列一个格子都没有 ⇒ 那三列是假的")
    # "同一格"的判词只由终态决定：终态是幂等，其余一律拒（不许 `want == have ⇒ ok`）
    assert Conductor.ITEM_MOVES[("done", "done")] == Conductor.ITEM_MOVE_SAME
    assert Conductor.ITEM_MOVES[("block", "block")] == Conductor.ITEM_MOVE_SAME
    for state in S.ITEM_STATES:
        if state in ("done", "block"):
            continue
        assert Conductor.ITEM_MOVES[(state, state)] == Conductor.ITEM_MOVE_BACK, (
            f"{state} 的同一格被放宽成幂等（它会静默吞掉这一步的读数）")
    # block 是只进不出的终态：它的四条出边一律拒（今天没有写入者，只靠这张表守着）
    for state in S.ITEM_STATES:
        if state == "block":
            continue
        assert Conductor.ITEM_MOVES[("block", state)] == Conductor.ITEM_MOVE_BACK, (
            f"从 block 出去的边被放行了：block → {state}")
    # 读数的两条口径：认不出的现态按 queued；目标态认不出 ⇒ ValueError（不是一句假话）
    assert Conductor.item_move("", "claimed") == Conductor.ITEM_MOVE_FORWARD
    assert Conductor.item_move("没有这一档", "claimed") == Conductor.ITEM_MOVE_FORWARD
    with pytest.raises(ValueError):
        Conductor.item_move("queued", "没有这一档")


# ====================================================================== h) ack 那一支
def test_h_ack_on_an_already_done_item_reports_already_done_and_writes_nothing(
        tmp_path: pathlib.Path) -> None:
    """h) `ack_items` 的 `already_done` 现在从状态机的 `changed=False` 来（不再入口自判）。

    D12 的形态：信息型项渲染那一拍就收口成 `done`；模型随后再 `conductor.ack` 一次是
    正常次序。读数要照旧报"已经收口"，而事件与计数一个都不许多。
    """
    st, cond = _ws(tmp_path)
    item = cond.open_item(kind="notice", role="M", expects="ack", action="notice",
                          summary="一条渲染即收口的报醒", called_by="clock",
                          parent_task_id=OWNER, depth=2, input_key="clock:t-000001")
    state, why = cond.mark_item_seen(item, by_task_id=OWNER, step=1)
    assert (state, why) == ("done", ""), (state, why)
    assert _row(st, item)["item_state"] == "done"

    events_before = len(_events(st))
    got = cond.ack_items([item], by_task_id=OWNER, note="我再确认一次")
    assert got["state"] == "acked", got
    assert got["acked"] == [item] and got["already_done"] == [item], got
    assert got["refused"] == [], got
    assert got["results"][0]["code"] == "already_done", got["results"]
    assert len(_events(st)) == events_before, (
        f"幂等命中之后多了 {len(_events(st)) - events_before} 条事件")
    assert _row(st, item)["item_state"] == "done"

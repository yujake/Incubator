# -*- coding: utf-8 -*-
"""工作项板：状态机与其判据（业主 2026-10-08 裁 A1=甲、A3=甲+seen、A6=丙）。

板的落点：`tasks` 表（七格见 `schema.Task` 末尾）。这份文件钉四件事：

1. 状态机只能往后走：`queued → claimed → seen → done`，不许跳、不许倒退；
2. `done` 之前必须 `seen`：否则返回 `ack_unbacked`（空口 ack），且状态不动、零写入
   —— 业主 A5 的口径是"只记读数、不拒写"；
3. 板只认 `kind` 非空的行：真机上 `projects.py` / `runflow.py` 也直接写本表
   （实测 `draft/89` §5.4），它们的行 `kind` 为空 ⇒ 不许混进板；
4. 三态：读不成是"没查成"，不是"板上没事"（`board_view()["checked"] is False`）。

读数的来源口径：状态是列（`item_state`），"谁在第几步改的"在事件流里
（每次 `tx.upsert` 落一条事件）—— 所以第 5 条判据顺带把 `rebuild()` 之后状态不变也钉住。
"""
from __future__ import annotations

import pathlib

from conftest import add_request  # noqa: F401  （与其它 conductor 判据同一套夹具口径）

from agentflow import schema as S
from agentflow.conductor import Conductor, LocalBackend
from agentflow.store import Store


def _cond(tmp_path: pathlib.Path) -> tuple[Store, Conductor]:
    st = Store(tmp_path / "ws")
    st.init()
    return st, Conductor(st, backend=LocalBackend({}))


def _item(st: Store, task_id: str) -> dict:
    return next(r for r in st.rows("tasks") if str(r.get("task_id")) == task_id)


def test_a_new_item_starts_queued_and_is_not_an_instance_row(tmp_path: pathlib.Path):
    """正控：开一项 ⇒ `queued`；它不算"老实例行"（两类行在读数里分开数）。"""
    st, c = _cond(tmp_path)
    tid = c.open_item(kind=S.ITEM_KINDS[0], role="G", action="build_document",
                      expects="work", summary="给 G 一件活", parent_task_id="t-0100")
    row = _item(st, tid)
    assert row["kind"] == "delegation" and row["item_state"] == "queued", row
    assert row["expects"] == "work" and row["item_close"] == "", row
    rd = c.board_readings()
    assert rd["checked"] is True and rd["board_rows"] == 1, rd
    assert rd["by_state"]["queued"] == 1, rd
    # 非派活项的 action 用 kind 当哨兵值（见 `open_item` 的 docstring）
    mid = c.open_item(kind="message", role="M", expects="ack", summary="通知一声")
    assert _item(st, mid)["action"] == "message", _item(st, mid)


def test_the_state_machine_only_moves_forward(tmp_path: pathlib.Path):
    """正控：`queued → claimed → seen → done/acked` 四步各自都能落盘。

    这一项刻意用「要你办事」那一档的 `input_key`（`v-verdict@…`）：信息型
    （`notice` / `message` 的普通项）自 D12 起渲染即收口，`mark_item_seen`
    那一拍就写 `done`+`acked`（见 `Conductor._settle_if_informational`），
    于是"四步各自落盘"这件事在它身上观测不到。
    """
    st, c = _cond(tmp_path)
    tid = c.open_item(kind="message", role="M", expects="ack", summary="只是让你知道",
                      input_key="v-verdict@判据@v1")
    assert c.claim_item(tid, by_task_id="t-0002")[0] == "claimed"
    assert c.mark_item_seen(tid, by_task_id="t-0002", step=3)[0] == "seen"
    row = _item(st, tid)
    assert (row["seen_by"], row["seen_step"]) == ("t-0002", 3), row
    assert c.close_item(tid, close="acked")[0] == "done"
    row = _item(st, tid)
    assert (row["item_state"], row["item_close"]) == ("done", "acked"), row
    assert c.board_readings()["by_close"]["acked"] == 1


def test_skipping_a_state_is_refused_and_writes_nothing(tmp_path: pathlib.Path):
    """负控：`queued → done`（跳过 claimed/seen）⇒ 拒绝，且状态不变、零写入。"""
    st, c = _cond(tmp_path)
    tid = c.open_item(kind="message", role="M", expects="ack", summary="x",
                      input_key="v-verdict@判据@v1")
    got, problem = c.close_item(tid, close="acked")
    assert got == "ack_unbacked" and "空口 ack" in problem, (got, problem)
    assert _item(st, tid)["item_state"] == "queued", _item(st, tid)
    # `claimed` 这一档允许被跳过（消息/通报类项没有 `running` 行，`claimed` 对它们没有意义）
    got2, problem2 = c.mark_item_seen(tid, by_task_id="t-9", step=1)
    assert got2 == "seen" and not problem2, (got2, problem2)
    assert _item(st, tid)["item_state"] == "seen", _item(st, tid)
    # 而倒退与重复迁移一律拒绝
    got3, problem3 = c.mark_item_seen(tid, by_task_id="t-9", step=2)
    assert got3 == "" and "已经到过" in problem3, (got3, problem3)


def test_an_ack_without_seen_is_only_a_reading_not_a_write(tmp_path: pathlib.Path):
    """负控（业主 A5 的核心）：没 `seen` 就 ack ⇒ `ack_unbacked`，状态一动不动。"""
    st, c = _cond(tmp_path)
    tid = c.open_item(kind="message", role="M", expects="ack", summary="x")
    c.claim_item(tid, by_task_id="t-1")
    got, problem = c.close_item(tid, close="acked")
    assert got == "ack_unbacked", (got, problem)
    row = _item(st, tid)
    assert (row["item_state"], row["item_close"]) == ("claimed", ""), row
    assert row["outcome"] is None and row["status"] == "pending", row


def test_only_board_rows_are_visible_on_the_board(tmp_path: pathlib.Path):
    """负控（实测形态）：老管线的行（`kind` 为空）不许混进板。

    真机上 `projects.py` / `runflow.py` 也直接写 `tasks`（`draft/89` §5.4）——
    它们不设 `kind`，所以"板上还挂着什么"读的是板的行，不是全部 `tasks` 行。
    """
    st, c = _cond(tmp_path)
    c.open_item(kind="message", role="M", expects="ack", summary="板项")
    with st.tx("tasks", actor="test") as tx:      # 手工塞一行"老管线"形态
        tx.upsert("tasks", {
            "task_id": "t-9001", "role": "A", "action": "run_once", "called_by": "M",
            "parent_task_id": None, "depth": 1, "input_key": "run_once@deadbeef",
            "status": "done", "outcome": "ok", "refusal_reason": None, "instance": "",
            "detail": "老行", "error": None, "started_at": S.now_iso(),
            "ended_at": S.now_iso(), "tokens": 0, "usd": 0.0, "artifacts": [], "inputs": [],
        }, note="fixture:legacy")
    view = c.board_view()
    assert view["open_count"] == 1, view
    assert [r["kind"] for r in view["open_items"]] == ["message"], view["open_items"]
    rd = c.board_readings()
    assert rd["board_rows"] == 1 and rd["old_instance_rows"] == 1, rd


def test_the_state_survives_a_rebuild(tmp_path: pathlib.Path):
    """I-9 的板版本：状态迁移之后 `rebuild()` 必须把它重建回来（列 + 事件两处一致）。"""
    st, c = _cond(tmp_path)
    tid = c.open_item(kind="message", role="M", expects="ack", summary="x")
    c.mark_item_seen(tid, by_task_id="t-2", step=5)
    before = _item(st, tid)
    st.rebuild(backup=False)
    after = _item(st, tid)
    assert before == after, (before, after)
    assert after["seen_by"] == "t-2" and after["seen_step"] == 5, after


def test_readings_are_three_state_when_the_table_cannot_be_read(tmp_path: pathlib.Path):
    """反真空：读不成 ⇒ `checked is False`（不是一串 0）。"""
    st, c = _cond(tmp_path)

    def boom():
        raise RuntimeError("注入的读失败")

    c._tasks = boom          # type: ignore[method-assign]
    rd = c.board_readings()
    assert rd["checked"] is False and "RuntimeError" in rd["reason"], rd
    view = c.board_view()
    assert view["checked"] is False and view["open_count"] == 0, view

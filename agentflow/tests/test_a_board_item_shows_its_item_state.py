# -*- coding: utf-8 -*-
"""D12：板项行的「状态」按 `item_state`/`item_close` 投影（读侧，不改 schema）。

## 补的是哪个缺口（真机读数）

`tasks` 表里板项行（`kind` 非空）的 `status` **设计上永远是 `pending`**：
`conductor._item_row` 建行写死（`conductor.py:4568-4577`），收口只动
`item_state`/`item_close`（`_set_item`，`:5348-5360`），源码自己那句逐字写着
「板项行 `status` 永远是 `pending`」（`:5663`）。于是按 `status` 打印的读口会被读成
"还没收口"：

    out/review/STATUS-20261109-1110.md： t-000104 B.notice pending/None
    data/tasks.json：71 条 notice 的 (status, item_state) 全是 ("pending", "done")

改前实测（本仓夹具，两条板项一条已 ack、一条还开着）：

    statusreport hint  done 项 → 'F.notice pending/None'
    statusreport hint  open 项 → 'F.notice pending/None'      ← 两者逐字相同
    /api/artifacts 的 tasks 行 → status='pending'（两条都是）

## 两处读口，一个函数

| 读口 | 落点 | 判据 |
|---|---|---|
| 状态报告（`.md` / `.json`） | `statusreport._hint_of` → `tasks_row_reading` | a / b |
| 网页 `GET /api/artifacts` | `webui.readers.artifacts_face` 的 `TaskRow.status_reading` | c |

`ui/src/pages/Artifacts.tsx` 的「任务产物」那一栏读的就是 `status_reading`（改前读
`status`）—— c 条同时钉"页面真读这一格"。

## 硬边界（业主明令）

**不许改 `schema` 的 `status` 语义**：`schema.Task.validate` 要求 `done` 必须有
`outcome`，而板项行的 `outcome` 恒为 `None` ⇒ 把盘上那格改成 `done` 会当场不合法。
d 条把这条边界的机器读数钉住：盘上那一行一个字都不变，`status` 仍是 `pending`。

| 格 | 用例 |
|---|---|
| a | `test_a_a_closed_board_item_no_longer_reads_as_pending` |
| b | `test_b_an_open_board_item_still_reads_as_not_closed` |
| c | `test_c_the_page_and_the_report_read_the_same_reading` |
| d | `test_d_removing_the_projection_turns_it_back_into_pending`（反真空） |
| e | `test_e_the_disk_status_cannot_be_changed_without_breaking_the_schema` |
"""
from __future__ import annotations

import pathlib
from typing import Any, Mapping

from agentflow import schema as S
from agentflow import statusreport as SR
from agentflow.conductor import Conductor, LocalBackend
from agentflow.store import Store
from agentflow.webui import readers as RD

REPO = pathlib.Path(__file__).resolve().parents[1]
ARTIFACTS_TSX = REPO / "ui" / "src" / "pages" / "Artifacts.tsx"


# ---------------------------------------------------------------- 夹具


def _ws(tmp_path: pathlib.Path) -> tuple[pathlib.Path, Conductor, dict[str, str]]:
    """M（根）→ D1（父）→ F1：F1 名下两条 notice（一条收口、一条还开着）。"""
    ws = tmp_path / "ws"
    ws.mkdir(parents=True, exist_ok=True)
    st = Store(ws)
    st.init()
    box = Conductor(st, policy=None, backend=LocalBackend({}))
    ids = {"M": _agent(box, role="M", parent=None, detail="顶趟")}
    ids["D1"] = _agent(box, role="D", parent=ids["M"], detail="D1")
    ids["F1"] = _agent(box, role="F", parent=ids["D1"], detail="F1")
    return ws, box, ids


def _agent(box: Conductor, *, role: str, parent: str | None, detail: str) -> str:
    return box._write_new_row({
        "role": role, "action": "run", "called_by": (parent and "M") or "user",
        "parent_task_id": parent, "depth": (1 if parent is None else 2),
        "input_key": f"d12:{role}:{detail}", "status": "running", "outcome": None,
        "refusal_reason": None, "instance": "", "detail": detail, "error": None,
        "started_at": "2026-11-09T08:00:00+08:00", "ended_at": None,
        "tokens": 0, "usd": 0.0, "artifacts": [], "inputs": [],
        "kind": "", "expects": "", "item_state": "", "item_close": "",
        "seen_by": "", "seen_step": None, "keep_alive": False,
    }, note=f"d12:agent:{role}")


def _items(box: Conductor, ids: Mapping[str, str]) -> tuple[str, str]:
    """`(已收口的那一条, 还开着的那一条)`。"""
    closed = box.open_item(kind="notice", role="F", expects="ack", action="notice",
                           summary="到点通知：已经收口的那一条",
                           called_by="clock", parent_task_id=ids["F1"], depth=2,
                           input_key="d12:notice:closed")
    still_open = box.open_item(kind="notice", role="F", expects="ack", action="notice",
                               summary="还没消的那一条", called_by="clock",
                               parent_task_id=ids["F1"], depth=2,
                               input_key="d12:notice:open")
    # 走真正的收口入口：`notice` 是信息型，渲染（`mark_item_seen`）就在同一拍收口
    # （`conductor._settle_if_informational`，业主 2026-10-27 的口径）——
    # 所以这里不手改盘上的行，也不假装它是 ack 出来的。
    state, _note = box.mark_item_seen(closed, by_task_id=ids["F1"], step=1)
    assert state == "done", state
    row = _disk_row(box, closed)
    assert (row["item_state"], row["item_close"]) == ("done", "acked"), row
    return closed, still_open


def _hints(box: Conductor, ws: pathlib.Path) -> dict[str, str]:
    report = SR.collect(box.store, ws)
    return {str(r.get("id")): str(r.get("hint") or "")
            for r in (report["tables"]["tasks"]["recent"] or [])}


def _md_tasks_line(box: Conductor, ws: pathlib.Path) -> str:
    md = SR.render_status_markdown(SR.collect(box.store, ws))
    return next((line for line in md.splitlines() if line.startswith("| `tasks` |")), "")


def _face_rows(box: Conductor, ws: pathlib.Path) -> dict[str, dict[str, Any]]:
    face = RD.artifacts_face(ws, box.store)
    return {str(r.get("task_id")): dict(r) for r in (face.get("tasks") or [])
            if isinstance(r, dict)}


def _disk_row(box: Conductor, item_id: str) -> dict[str, Any]:
    return next(dict(r) for r in box._tasks()
                if str(r.get("task_id") or "") == str(item_id))


# ---------------------------------------------------------------- a —— 已收口的板项


def test_a_a_closed_board_item_no_longer_reads_as_pending(tmp_path: pathlib.Path) -> None:
    """a：`item_state=done` 的 notice 在状态报告里不再显示 pending（逐字给读数）。"""
    ws, box, ids = _ws(tmp_path)
    closed, _open_item = _items(box, ids)
    hint = _hints(box, ws)[closed]
    assert hint == "F.notice 板项 done/acked", hint
    assert "pending" not in hint, f"已收口的板项仍然印出 pending：{hint!r}"
    line = _md_tasks_line(box, ws)
    assert f"{closed} F.notice 板项 done/acked" in line, line
    assert f"{closed} F.notice pending/None" not in line, line


# ---------------------------------------------------------------- b —— 还开着的板项


def test_b_an_open_board_item_still_reads_as_not_closed(tmp_path: pathlib.Path) -> None:
    """b：`item_state` 还开着的板项仍读成"未消" —— 不许把所有板项都说成 done。"""
    ws, box, ids = _ws(tmp_path)
    _closed, still_open = _items(box, ids)
    hint = _hints(box, ws)[still_open]
    assert hint == "F.notice 板项 queued/未收口", hint
    assert "未收口" in hint, hint
    assert "done" not in hint, f"还没消的板项被读成了已收口：{hint!r}"
    assert f"{still_open} F.notice 板项 queued/未收口" in _md_tasks_line(box, ws)


# ---------------------------------------------------------------- c —— 两处读口同源


def test_c_the_page_and_the_report_read_the_same_reading(tmp_path: pathlib.Path) -> None:
    """c：网页 `/api/artifacts` 与状态报告读的是同一个函数的同一份读数。"""
    ws, box, ids = _ws(tmp_path)
    closed, still_open = _items(box, ids)
    hints = _hints(box, ws)
    rows = _face_rows(box, ws)
    for item_id, want in ((closed, "板项 done/acked"), (still_open, "板项 queued/未收口")):
        assert rows[item_id]["status_reading"] == want, rows[item_id]
        # 报告那一格是 `role.action + 投影`：把前缀去掉必须逐字相等
        assert hints[item_id].endswith(rows[item_id]["status_reading"]), (
            hints[item_id], rows[item_id]["status_reading"])
        # 盘上那一格仍然是 pending（投影不是改写）
        assert rows[item_id]["status"] == "pending", rows[item_id]
    # 页面真读这一格（改前读的是 `status`）
    tsx = ARTIFACTS_TSX.read_text(encoding="utf-8")
    assert "status_reading" in tsx, (
        "Artifacts.tsx 的「任务产物」那一栏没读 status_reading ⇒ 页面仍然印 pending")


# ---------------------------------------------------------------- d —— 反真空


def test_d_removing_the_projection_turns_it_back_into_pending(
        tmp_path: pathlib.Path, monkeypatch: Any) -> None:
    """d：把投影摘掉（退回"直接打 status/outcome"）⇒ 那一又显示 pending，两处一起变。

    这条同时钉"同一处口径"：替换的是 `statusreport.tasks_row_reading` 这一个函数，
    报告与网页必须**同时**回到改前的读数 —— 若网页自己另写了一份投影，它不会跟着变。
    """
    ws, box, ids = _ws(tmp_path)
    closed, _open_item = _items(box, ids)
    assert _hints(box, ws)[closed] == "F.notice 板项 done/acked"
    assert _face_rows(box, ws)[closed]["status_reading"] == "板项 done/acked"

    def _raw(row: Mapping[str, Any]) -> str:
        return f"{row.get('status')}/{row.get('outcome')}"

    monkeypatch.setattr(SR, "tasks_row_reading", _raw)
    back = _hints(box, ws)[closed]
    assert back == "F.notice pending/None", f"投影摘掉后没有回到改前的读数：{back!r}"
    assert _face_rows(box, ws)[closed]["status_reading"] == "pending/None", (
        "网页那一侧没跟着同一个函数变 ⇒ 它自己另写了一份投影")


# ---------------------------------------------------------------- e —— status 语义没动


def test_e_the_disk_status_cannot_be_changed_without_breaking_the_schema(
        tmp_path: pathlib.Path) -> None:
    """e：边界读数的机器证据 —— 盘上那格仍是 pending，改成 done 会被 schema 拒。

    业主明令不许改 `schema` 的 `status` 语义。这条把"为什么不能改"钉成可执行读数：
    `schema.Task.validate` 要求 `status == "done"` 的行必须有 `outcome`，而板项行的
    `outcome` 恒为 `None`（板项不是一次调用，没有结局这一说）。
    """
    ws, box, ids = _ws(tmp_path)
    closed, _open_item = _items(box, ids)
    # 两处读口都读过之后，盘上那一行一个字都没变
    SR.collect(box.store, ws)
    RD.artifacts_face(ws, box.store)
    row = _disk_row(box, closed)
    assert (row["status"], row["outcome"]) == ("pending", None), row
    assert (row["item_state"], row["item_close"]) == ("done", "acked"), row

    S.Task(**{k: v for k, v in row.items()
              if k in S.Task.__dataclass_fields__}).validate()      # 正控：现状合法

    def _why(**patch: Any) -> str:
        """把某一格改成"看起来像收口"的样子 ⇒ 拿 schema 的拒信原话。"""
        base = {k: v for k, v in row.items() if k in S.Task.__dataclass_fields__}
        try:
            S.Task(**{**base, **patch}).validate()
        except ValueError as exc:
            return str(exc)
        raise AssertionError(
            f"把板项行改成 {patch!r}，schema 居然放过了 ⇒ e 条的机器证据失效了")

    # ① 光把 status 改成 done 就不合法：板项行没有 ended_at（它不是一次调用）
    assert "ended_at" in _why(status="done")
    # ② 连 ended_at 都补上，`outcome` 仍然把它挡在门外 —— 板项的 outcome 恒为 None
    #    （`schema.py:2982`）。这就是「不许改 status 语义」那条边界的技术内容：
    #    要让板项行真的 `done`，得先给它编一个 outcome，而那是另一件事（改 schema）。
    assert "outcome" in _why(status="done", ended_at="2026-11-09T08:00:01+08:00")

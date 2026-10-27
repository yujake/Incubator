# -*- coding: utf-8 -*-
"""判据：一拍一份台账快照（只读作用域）—— `Conductor.reading_snapshot`（2026-10-27）。

## 为什么要这条判据

`Secretary.roster_view` 一拍要把同一张 `tasks` 表读十几遍：逐名册项问一次"它名下最新的
派活项声明过待命吗"（`keep_alive_of`）、逐层问一次"这一层哪几项可退役"（`retire_ready`）、
外加三态快照与 `children_facts`。它们读的是同一份台账的同一个时刻，而每一读都是一次
`store.rows()`（逐行新建副本）。实测（`temp/r_be2_reads_per_beat2.py`，12 项名册）：

- 改前：一拍 31 次（= 2N+7）；
- 把 `keep_alive_of` 与 `retire_ready` 的内部重复读收掉之后：17 次（= N+7）；
- 包进 `reading_snapshot()` 之后：1 次。

## 这份判据钉住的四件事

1. 一拍只读一次：`roster_view` 期间 `store.rows("tasks")` 恰好 1 次（反真空：名册里
   必须既有"在飞"又有"已收工"的项，否则 `keep_alive_of` 那一路根本不会被走到）；
2. 可重入：嵌套进入不换快照（外层那一份一直用到最外层退出）；
3. 作用域内只读：写入口在作用域里调用当场抛（`RuntimeError`），负控证明同一个写入口
   在作用域外是成功的；
4. 出了作用域立刻回到现读现算：作用域外写一行，紧接着读必须看得到它
   （这一条防的正是"缓存把一拍延长成了永久"）。

已知未覆盖：`note_edge_release`（属 O1 那一批"事件消账"的改动面，本轮按纪律不动）
没有被守卫覆盖 —— 第 5 条判据把这件事钉在 docstring 里，免得它静默。
"""
from __future__ import annotations

import inspect
import pathlib

import pytest

from agentflow import schema as S
from agentflow.conductor import Conductor
from agentflow.secretary import Secretary
from agentflow.store import Store

TS = "2026-01-01T00:00:00+00:00"
N_KIDS = 4


def _ws(tmp_path: pathlib.Path) -> tuple[Store, Conductor, Secretary]:
    """一个最小工作区：1 个顶趟 + N 个子代理（一半在飞、一半已收工）+ N 项名册。"""
    st = Store(tmp_path / "ws")
    st.init()
    rows = [S.Task(task_id="t-0001", role="M", action="run", called_by="user",
                   status="running", outcome=None, input_key="M.run",
                   detail="顶趟", started_at=TS, ended_at=None).to_dict()]
    for i in range(N_KIDS):
        done = i % 2 == 1
        rows.append(S.Task(task_id=f"t-{i + 2:04d}", role="D", action="run",
                           called_by="M", status="done" if done else "running",
                           outcome="ok" if done else None,
                           input_key=f"D.run#{i}", detail="子代理",
                           parent_task_id="t-0001", started_at=TS,
                           ended_at=TS if done else None).to_dict())
    with st.tx("tasks", actor="fixture") as tx:
        for r in rows:
            tx.upsert("tasks", r)
    sec = Secretary("M", root=st.root, store=st)
    for i in range(N_KIDS):
        sec.roster_add(owner="t-0001", role="D", task_id=f"t-{i + 2:04d}",
                       brief=f"第{i}项", new="D")
    return st, Conductor(st), sec


def _count_rows(st: Store, monkeypatch) -> dict[str, int]:
    """把 `Store.rows` 包成计数器（只数 `tasks`，其余原样）。"""
    hits = {"tasks": 0}
    real = Store.rows

    def wrapped(self, table):
        if table == "tasks":
            hits["tasks"] += 1
        return real(self, table)

    monkeypatch.setattr(Store, "rows", wrapped)
    return hits


# ---------------------------------------------------------------- 1. 一拍只读一次
def test_roster_view_reads_the_ledger_once(tmp_path, monkeypatch) -> None:
    st, cond, sec = _ws(tmp_path)
    sec._cond_cache = cond          # 让秘书的读句柄就是这一个（与生产同一形态）
    hits = _count_rows(st, monkeypatch)
    view = sec.roster_view(owner="t-0001", scope="descendants")
    assert view.get("checked"), view
    assert len(view.get("rows") or []) == N_KIDS
    # 反真空：这一份名册里必须既有"在飞"又有"已收工"的项 —— 否则 `keep_alive_of`
    # 那一支根本不会被走到，"只读一次"就变成了"只读一次特别好读的那一路"。
    states = {str(r.get("state") or "") for r in view["rows"]}
    assert "活跃" in states and "已停" in states, states
    assert hits["tasks"] == 1, (
        f"一拍读了 {hits['tasks']} 次 `tasks`（应为 1）⇒ `reading_snapshot` 没罩住"
        " 这次调用，或者某处读侧绕开了 `Conductor._tasks()`")


def test_child_counts_also_rides_the_beat(tmp_path, monkeypatch) -> None:
    """同一拍里 `child_counts` 与逐行渲染共用一份快照（不是各自再读一遍）。"""
    st, cond, sec = _ws(tmp_path)
    sec._cond_cache = cond
    hits = _count_rows(st, monkeypatch)
    with cond.reading_snapshot():
        got = sec.child_counts(owner="t-0001")
    assert got.get("checked"), got
    assert hits["tasks"] == 1, hits


# ---------------------------------------------------------------- 2. 可重入
def test_nested_scopes_keep_the_outer_snapshot(tmp_path) -> None:
    _st, cond, _sec = _ws(tmp_path)
    with cond.reading_snapshot():
        outer = cond._snapshot_rows()
        assert outer is not None
        with cond.reading_snapshot():
            inner = cond._snapshot_rows()
            assert inner is outer, "嵌套进入换掉了外层快照 ⇒ 外层那一拍会看到两个时刻的盘"
        assert cond._snapshot_rows() is outer
    assert cond._snapshot_rows() is None, "退出作用域之后快照还在 ⇒ 读侧会一直读旧值"


# ---------------------------------------------------------------- 3. 作用域内只读
@pytest.mark.parametrize("call", [
    ("open_item", dict(kind="notice", role="D", expects="ack", summary="x", called_by="M")),
    ("set_item_detail", dict()),
])
def test_writes_are_refused_inside_the_scope(tmp_path, call) -> None:
    _st, cond, _sec = _ws(tmp_path)
    name, kw = call
    if name == "set_item_detail":
        args = ("t-0002", "说明")
    else:
        args = ()
    with cond.reading_snapshot():
        with pytest.raises(RuntimeError) as exc:
            getattr(cond, name)(*args, **kw)
    assert "只读快照作用域" in str(exc.value)
    assert name in str(exc.value) or "板项" in str(exc.value) or "建行" in str(exc.value)


def test_negative_control_the_same_write_succeeds_outside(tmp_path) -> None:
    """负控：同一个写入口在作用域外必须成功（否则上一条只是"这个方法坏了"）。"""
    _st, cond, _sec = _ws(tmp_path)
    item = cond.open_item(kind="notice", role="D", expects="ack", summary="x",
                          called_by="M")
    assert item, "作用域外 open_item 也失败了 ⇒ 上一条的正控不成立"
    got, why = cond.set_item_detail(item, "说明")
    assert got == "说明" and not why, (got, why)


# ---------------------------------------------------------------- 4. 出处即现读
def test_reads_are_live_again_after_the_scope(tmp_path, monkeypatch) -> None:
    _st, cond, _sec = _ws(tmp_path)
    with cond.reading_snapshot():
        before = len(cond._tasks())
    new_id = cond.open_item(kind="notice", role="D", expects="ack", summary="作用域外写的",
                            called_by="M")
    assert new_id
    hits = _count_rows(_st, monkeypatch)
    after = len(cond._tasks())
    assert hits["tasks"] == 1, "作用域外的读没有真的去读台账（走的是缓存）"
    assert after == before + 1, (
        f"作用域外写一行之后读到 {after} 行（应为 {before + 1}）⇒ 快照活过了作用域")


# ---------------------------------------------------------------- 5. 已知未覆盖
def test_the_known_uncovered_writer_is_named_in_the_docstring() -> None:
    """`note_edge_release` 没有被守卫覆盖（O1 在改它）—— 这件事必须写在 docstring 里。"""
    text = inspect.getsource(Conductor.reading_snapshot)
    assert "note_edge_release" in text, (
        "`reading_snapshot` 的 docstring 没有再点名那一处未覆盖的写入口 ⇒ "
        "下一个人会以为整个作用域都守着只读")

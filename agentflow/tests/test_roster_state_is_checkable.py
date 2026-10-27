# -*- coding: utf-8 -*-
"""判据：名册那一行的"它停了"与"它判不了"必须分得开（2026-10-27）。

## 背景

`roster_view` 的每一行有一个 `state`（五档中文：活跃 / 待命 / 已停 / 已退役 / 未登记）。
「已停 / 待命」这两档要看"它名下最新的那条派活项声明过待命没有"（`conductor.keep_alive_of`），
而那一读可能读不成（台账读失败、那一行在两次读之间没了）。改前它被折成 `state="已停"` ——
把"没查成"写成一条结论，而这一格会被父代理读成"它停了、可以销号"。销号是不可逆的那一类。

## 判据的形状（五档不动，另给一格说明可不可信）

`state` 的五档取值域一个字符都不改（前端与读侧都按它显示），另加两格：

- `state_checked: bool` —— 这一格查过没有；
- `state_reason: str` —— 没查成时的理由（查成了就是空串）。

读侧在 `state_checked=False` 时不许把 `state` 当结论用（前端按这一格决定怎么显示）。

## 本判据钉住四件事

1. 正常路径：每一行都带 `state_checked=True` 与 `state ∈ 五档`；
2. 待命声明读不成 ⇒ `state_checked=False`、`state` 不是"已停"、`state_reason` 非空；
3. 那一层就绪读数（`retire_ready`）读不成 ⇒ 同样 `state_checked=False`（"未登记"也不许
   被当成"读过了、确实没有这一项"）；
4. 反真空：同一份名册里必须有"已停"那一档的行，否则第 2 条守的是一个走不到的分支。
"""
from __future__ import annotations

import pathlib

from agentflow import schema as S
from agentflow.conductor import Conductor
from agentflow.secretary import STATE_LABELS, Secretary
from agentflow.store import Store

TS = "2026-01-01T00:00:00+00:00"
N_KIDS = 4


def _ws(tmp_path: pathlib.Path) -> tuple[Store, Conductor, Secretary]:
    """两层：`t-0001`（M）→ 4 个 D（`t-0002`…）+ 其中一个 D 自己还有一个 E。

    为什么要两层：`roster_view(scope="descendants")` 会逐层问 `retire_ready`，
    而"某一层的读数没读成"只在第二层起才可能发生（第一层读不成 ⇒ 整份视图 fail-closed）。
    """
    st = Store(tmp_path / "ws")
    st.init()
    rows = [S.Task(task_id="t-0001", role="M", action="run", called_by="user",
                   status="running", outcome=None, input_key="M.run",
                   detail="顶趟", started_at=TS, ended_at=None).to_dict()]
    for i in range(N_KIDS):
        rows.append(S.Task(task_id=f"t-{i + 2:04d}", role="D", action="run",
                           called_by="M", status="done", outcome="ok",
                           input_key=f"D.run#{i}", detail="子代理收工",
                           parent_task_id="t-0001", started_at=TS,
                           ended_at=TS).to_dict())
    rows.append(S.Task(task_id="t-0009", role="E", action="run", called_by="D",
                       status="done", outcome="ok", input_key="E.run#0",
                       detail="孙代理收工", parent_task_id="t-0002",
                       started_at=TS, ended_at=TS).to_dict())
    with st.tx("tasks", actor="fixture") as tx:
        for r in rows:
            tx.upsert("tasks", r)
    sec = Secretary("M", root=st.root, store=st)
    for i in range(N_KIDS):
        sec.roster_add(owner="t-0001", role="D", task_id=f"t-{i + 2:04d}",
                       brief=f"第{i}项", new="D")
    sec.roster_add(owner="t-0002", role="E", task_id="t-0009",
                   brief="孙代理的活", new="E")
    cond = Conductor(st)
    sec._cond_cache = cond
    return st, cond, sec


def test_rows_carry_state_checked_and_keep_the_five_labels(tmp_path) -> None:
    _st, _cond, sec = _ws(tmp_path)
    view = sec.roster_view(owner="t-0001", scope="descendants")
    assert view.get("checked"), view
    rows = view["rows"]
    assert rows
    for r in rows:
        assert "state_checked" in r and "state_reason" in r, r.keys()
        assert r["state"] in STATE_LABELS, (r["state"], STATE_LABELS)
        assert r["state_checked"] is True, (
            f"正常路径下 {r['task_id']} 的 `state_checked` 是 {r['state_checked']}：{r}")
    # 反真空：这一份名册里必须真有"已停"那一档（否则下面的判据守的是空分支）。
    assert any(r["state"] == "已停" for r in rows), [r["state"] for r in rows]


def test_unreadable_keep_alive_never_reads_as_stopped(tmp_path, monkeypatch) -> None:
    _st, cond, sec = _ws(tmp_path)
    real = cond.keep_alive_of

    def broken(task_id):
        return {"checked": False, "keep_alive": False, "reason": "台账读不成（判据打桩）"}

    monkeypatch.setattr(cond, "keep_alive_of", broken)
    view = sec.roster_view(owner="t-0001", scope="descendants")
    assert view.get("checked"), view
    rows = [r for r in view["rows"] if r["name"]]
    assert rows
    for r in rows:
        assert r["state"] in STATE_LABELS, r["state"]
        assert r["state_checked"] is False, (
            f"待命声明读不成，`state_checked` 却是 {r['state_checked']}：{r}")
        assert r["state"] != "已停", (
            f"'没查成'被写成了'它停了'：{r}")
        assert r["state_reason"], f"`state_checked=False` 却没有理由：{r}"
    # 负控：把读口修好，同一份名册必须回到"查过了"那一档（否则上面只是"它总是 false"）。
    monkeypatch.setattr(cond, "keep_alive_of", real)
    again = sec.roster_view(owner="t-0001", scope="descendants")
    assert any(r["state_checked"] is True for r in again["rows"]), again["rows"]


def test_unreadable_retire_ready_never_reads_as_registered(tmp_path, monkeypatch) -> None:
    """某一层的就绪读数读不成 ⇒ 那一层的"未登记"也不许冒充"读过了、确实没有这一项"。"""
    _st, cond, sec = _ws(tmp_path)
    real = cond.retire_ready

    def flaky(parent_task_id):
        # 第一层（owner）照常读成 —— 第一层读不成时 `roster_view` 是 fail-closed 整份拒，
        # 那是更早的一道闸；这里要测的是"第二层及以下读不成"。
        if str(parent_task_id) == "t-0001":
            return real(parent_task_id)
        return {"checked": False, "ready": [], "reason": "就绪读数没读成（判据打桩）"}

    monkeypatch.setattr(cond, "retire_ready", flaky)
    view = sec.roster_view(owner="t-0001", scope="descendants")
    assert view.get("checked"), view
    grand = [r for r in view["rows"] if r["task_id"] == "t-0009"]
    assert grand, [r["task_id"] for r in view["rows"]]
    row = grand[0]
    assert row["state"] in STATE_LABELS, row["state"]
    assert row["state_checked"] is False, (
        f"那一层的就绪读数没读成，`state_checked` 却是 {row['state_checked']}：{row}")
    assert row["state_reason"], row
    # 负控：第一层读得成的那几行仍然是"查过了"。
    first = [r for r in view["rows"] if r["task_id"] == "t-0002"]
    assert first and first[0]["state_checked"] is True, first

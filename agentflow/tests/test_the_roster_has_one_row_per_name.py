# -*- coding: utf-8 -*-
"""名册的不变量：一个名字一行（`draft/149` §1.4 / `draft/150` §5.2 的七条口径）。

## 这一组守什么（r1–r7，逐条对应业主 2026-11-02 的定稿口径）

| 编号 | 口径 | 改前读数 |
|---|---|---|
| r1 | 身份 = `(owner, name)`：名册项 = `add` 行（一名一行）；`bind` 行 = 这个名字接过的活（一名可多号，复用合法） | 绿（合法的复用形态，钉住它别被"去重"改坏） |
| r2 | `roster_add` 的「名字分配 + 槽位分配 + 去重」在同一个 per-owner 临界区 | 红：3 线程同时 add ⇒ 三个都拿到 `E1` / `S01`（`temp/probe_roster_one_row.py` A） |
| r2b | 槽位不许重叠：3 线程同时 add 不许都拿到 `S01` | 红（同上） |
| r3 | `roster_repair` 的已知集 = 全部 `add` 行 ∪ 全部 `bind` 行的 `task_id` 并集（不是 `_fold_index` 的"只留最新 bind"） | 红：零并发 `add(new) → add(reuse) → repair` ⇒ 多一行 `D2/t-000002`（机制 B） |
| r4 | 同一个 `task_id` 不许出现在两条 `add` 行（`task_id_reused`）；同一个 `(owner,name)` 不许 `add` 两次（`name_taken`） | 红：同一个号拿到第二个名字 `E2`；`name_taken` 只在人话里、没有判据可认 |
| r5 | 销号要标死该名字绑过的全部号（不只当前号） | 红：`D1/t-000002` 复用出 `t-000003`，销号后 `retired_reading_of(t-000002).retired=False`（旧号永久可唤醒） |
| r6 | `add` / `bind` 到已销号的号必须拒绝 | 红：已销号的 `t-000002` 换个名字 `D2` 再 `add` 成功；再 `bind` 给 `D2` 也成功 |
| r7 | 按号寻址多成员要拒歧义（`agent_loop.py:3655` 现静默取 `hit[0]`） | 红：两个名字共用一个号时 `roster_addresses(to=号)` 静默返回 `D1` |

外加一条（同一笔口径的另一半）：`Conductor._register_roster` 的"撞名 ⇒ 静默换名"
（`conductor.py:3061-3110`）去掉，改成 `name_taken` 拒绝。

## 夹具的纪律

- 真工作区（`Store.init` + 真 `Conductor` + 真 `Secretary(enable_model=False)`），零模型调用；
- 台账子行用 `_write_new_row` 建（`status=done`、`ended_at` 非空 ⇒ 静默，销号闸/三态都能过）；
- 机制 A 用真线程 + 真 `roster_add` / `roster_repair`，只用 `next_name` 的 sleep 把窗口拉宽
  （不改进代码判据，也不加锁替身）；
- 机制 B 是零并发串行夹具：`add(new) → add(reuse) → repair`。
"""
from __future__ import annotations

import json
import pathlib
import sys
import threading
import time

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agentflow import secretary as SEC  # noqa: E402
from agentflow.agent_loop import roster_addresses  # noqa: E402
from agentflow.conductor import Conductor, LocalBackend  # noqa: E402
from agentflow.secretary import Secretary  # noqa: E402
from agentflow.store import Store  # noqa: E402

TS = "2026-01-01T00:00:00+00:00"


# ---------------------------------------------------------------- 夹具


def _env(tmp_path: pathlib.Path) -> dict:
    """一个工作区 + 一趟顶趟（父）+ 真秘书。"""
    ws = tmp_path / "ws"
    st = Store(ws)
    st.init()
    cond = Conductor(st, policy=None, backend=LocalBackend({}))
    sec = Secretary("M", root=ws, store=st, enable_model=False)
    cond.secretary = sec
    cond.roster_sink = sec
    parent = str(cond.open_top_level_run("M", "顶趟这一趟"))
    return {"ws": ws, "st": st, "cond": cond, "sec": sec, "owner": parent}


def _child(cond: Conductor, parent: str, *, role: str = "D", tag: str = "") -> str:
    """在台账里造一条"有父、静默"的代理行（名册写口之外的唯一来源）。"""
    return str(cond._write_new_row({
        "role": role, "action": "run", "called_by": "M",
        "parent_task_id": parent, "depth": 2, "input_key": f"fixture:{tag}",
        "status": "done", "outcome": "ok", "refusal_reason": None, "instance": "",
        "detail": "夹具子代理", "error": None, "started_at": TS, "ended_at": TS,
        "tokens": 0, "usd": 0.0, "artifacts": [], "inputs": [],
    }, note="fixture:child"))


def _lines(path: pathlib.Path) -> list[dict]:
    p = pathlib.Path(path)
    if not p.is_file():
        return []
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]


def _adds(env: dict, owner: str = "") -> list[dict]:
    return [r for r in _lines(SEC.roster_path(env["ws"], owner or env["owner"]))
            if str(r.get("kind")) == "add"]


def _binds(env: dict, owner: str = "") -> list[dict]:
    return [r for r in _lines(SEC.roster_index_path(env["ws"], owner or env["owner"]))
            if str(r.get("kind")) == "bind"]


def _add_rows_for(env: dict, task_id: str) -> list[dict]:
    return [r for r in _adds(env) if str(r.get("task_id")) == str(task_id)]


def _slow_next_name(delay: float = 0.05) -> object:
    """把 `next_name` 卡慢一点：只加 sleep，不改判据（改前并发窗口因此可复现）。"""
    orig = Secretary.next_name

    def patched(self: Secretary, owner: str, role: str) -> tuple[str, str]:
        got = orig(self, owner, role)
        time.sleep(delay)
        return got

    Secretary.next_name = patched  # type: ignore[method-assign]
    return orig


def _restore_next_name(orig: object) -> None:
    Secretary.next_name = orig  # type: ignore[method-assign]


# ---------------------------------------------------------------- r1（身份：一名一行，bind 是复用）


def test_r1_one_name_is_one_add_row_and_binds_are_the_reuse_path(tmp_path: pathlib.Path) -> None:
    """r1：`reuse` 是合法的一等功能 —— 只追加 `bind`，名册正文一个字节都不动。"""
    env = _env(tmp_path)
    sec, cond, owner = env["sec"], env["cond"], env["owner"]
    t1 = _child(cond, owner, tag="r1-a")
    t2 = _child(cond, owner, tag="r1-b")
    first = sec.roster_add(owner=owner, role="D", task_id=t1, brief="第一件活")
    assert first.get("problem") == "", first
    name = str(first.get("name") or "")
    second = sec.roster_add(owner=owner, role="D", task_id=t2, brief="第二件活", reuse=name)
    assert second.get("problem") == "", second
    assert str(second.get("name")) == name, second
    rows = _adds(env)
    assert [str(r.get("name")) for r in rows] == [name], rows
    assert [str(r.get("task_id")) for r in rows] == [t1], rows
    assert sorted(str(r.get("task_id")) for r in _binds(env)) == sorted([t1, t2])
    folded = sec.roster_rows(owner)[0]
    assert len(folded) == 1 and str(folded[0].get("name")) == name, folded


# ---------------------------------------------------------------- r2 + r2b（per-owner 临界区）


def test_r2_concurrent_adds_allocate_distinct_names_and_surfaces(
        tmp_path: pathlib.Path) -> None:
    """r2 / r2b：同一个父名下 3 个线程同时 `roster_add` ⇒ 名字与槽位都不许撞。

    改前读数（`temp/probe_roster_one_row.py` A）：三次调用都返回 `E1` / `S01`，
    名册里三行同名、三个面池 `alloc` 指向同一个槽位。
    """
    env = _env(tmp_path)
    sec, owner = env["sec"], env["owner"]
    orig = _slow_next_name()
    out: list[dict] = []
    lock = threading.Lock()
    start = threading.Barrier(3, timeout=10)

    def work(k: int) -> None:
        start.wait()
        got = sec.roster_add(owner=owner, role="E", task_id=f"t-00000{k}", brief=f"第 {k} 件活")
        with lock:
            out.append({"name": got.get("name"), "surface": got.get("surface"),
                        "problem": got.get("problem")})

    try:
        threads = [threading.Thread(target=work, args=(k,)) for k in (1, 2, 3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    finally:
        _restore_next_name(orig)

    assert all(str(o.get("problem") or "") == "" for o in out), out
    names = [str(o.get("name") or "") for o in out]
    slots = [str(o.get("surface") or "") for o in out]
    assert sorted(names) == ["E1", "E2", "E3"], names
    assert sorted(slots) == ["S01", "S02", "S03"], slots
    rows = _adds(env)
    assert len(rows) == 3, rows
    assert sorted(str(r.get("name")) for r in rows) == ["E1", "E2", "E3"], rows
    assert sorted(str(r.get("surface")) for r in rows) == ["S01", "S02", "S03"], rows
    pool = [r for r in _lines(SEC.surfaces_path(env["ws"], owner))
            if str(r.get("kind")) == "alloc"]
    assert sorted(str(r.get("slot")) for r in pool) == ["S01", "S02", "S03"], pool


def test_r2b_mechanism_a_three_threads_add_then_repair_leave_one_row_per_task(
        tmp_path: pathlib.Path) -> None:
    """r2 的机制 A：3 线程「先落台账、再 add、再 repair」⇒ 每个号只许一行 `add`。

    改前读数（`temp/probe_roster_one_row.py` A2）：三个线程的 `roster_repair` 都在
    "别人的台账行已落、index 行还没落"的窗口里补了一条 `repaired:true` 的行，
    于是 3 个号长出 9 条 `add` 行（每个号 2–4 条）。

    修后不保证"每个线程都抢到自己的名字"（自愈可能先替它补上，随后那次 add 会
    以 `task_id_reused` 被拒）—— 这一条钉的是「每个号恰好一行、名字不重复」，
    以及"被拒不是静默的"。
    """
    env = _env(tmp_path)
    sec, cond, owner = env["sec"], env["cond"], env["owner"]
    tasks = [_child(cond, owner, tag=f"r2b-{i}") for i in (1, 2, 3)]
    orig = _slow_next_name()
    out: list[dict] = []
    lock = threading.Lock()
    start = threading.Barrier(3, timeout=10)

    def work(k: int, tid: str) -> None:
        start.wait()
        got = sec.roster_add(owner=owner, role="D", task_id=tid, brief=f"第 {k} 件活")
        fixed, why, _skipped = sec.roster_repair(owner=owner)
        with lock:
            out.append({"k": k, "task_id": tid, "name": got.get("name"),
                        "problem": got.get("problem"),
                        "refusal_code": got.get("refusal_code", ""),
                        "repaired": fixed, "why": why})

    try:
        threads = [threading.Thread(target=work, args=(k, tid))
                   for k, tid in enumerate(tasks)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    finally:
        _restore_next_name(orig)

    rows = _adds(env)
    per_task: dict[str, list[dict]] = {}
    for r in rows:
        per_task.setdefault(str(r.get("task_id")), []).append(r)
    assert sorted(per_task) == sorted(tasks), (per_task, tasks)
    for tid in tasks:
        assert len(per_task[tid]) == 1, (tid, per_task[tid])
    assert len({str(r.get("name")) for r in rows}) == len(rows), rows
    for got in out:
        problem = str(got.get("problem") or "")
        if problem:
            # 被拒的那几次必须点名原因（不许"没写成"却当成写成了）。
            assert str(got.get("refusal_code") or "") in {"task_id_reused", "task_id_retired",
                                                          "name_taken"}, got


# ---------------------------------------------------------------- r3（已知集 = add ∪ bind）


def test_r3_repair_does_not_forget_a_task_the_name_already_bound(
        tmp_path: pathlib.Path) -> None:
    """r3（机制 B，零并发）：一个名字接过第二件活之后，自愈不得再补第一件活。

    改前读数（`temp/probe_roster_one_row.py` B）：`_fold_index` 只留最新那条 `bind`
    ⇒ `t-000002` 从 `known` 里消失 ⇒ `repair fixed=1`，名册里长出 `D2/t-000002`
    （`repaired:true`、无 surface）。这一步与并发无关。
    """
    env = _env(tmp_path)
    sec, cond, owner = env["sec"], env["cond"], env["owner"]
    t1 = _child(cond, owner, tag="r3-a")
    t2 = _child(cond, owner, tag="r3-b")
    first = sec.roster_add(owner=owner, role="D", task_id=t1, brief="第一件活")
    assert first.get("problem") == "", first
    name = str(first.get("name") or "")
    second = sec.roster_add(owner=owner, role="D", task_id=t2, brief="第二件活", reuse=name)
    assert second.get("problem") == "", second

    fixed, why, _skipped = sec.roster_repair(owner=owner)
    assert (fixed, why) == (0, ""), (fixed, why)
    rows = _adds(env)
    assert len(rows) == 1, rows
    assert str(rows[0].get("name")) == name and str(rows[0].get("task_id")) == t1, rows
    assert [r for r in rows if r.get("repaired")] == [], rows
    # 反真空：台账里真缺一行时，自愈还是要补（不许把"不补"写成"永远不补"）。
    orphan = _child(cond, owner, tag="r3-orphan")
    fixed2, why2, _skipped2 = sec.roster_repair(owner=owner)
    assert (fixed2, why2) == (1, ""), (fixed2, why2)
    assert [str(r.get("task_id")) for r in _add_rows_for(env, orphan)], [orphan]


# ---------------------------------------------------------------- r4（同号 / 同名去重）


def test_r4_a_task_id_and_a_name_are_both_used_at_most_once(tmp_path: pathlib.Path) -> None:
    """r4：同一个号不许两条 `add`（`task_id_reused`）；同一个名字不许 `add` 两次（`name_taken`）。"""
    env = _env(tmp_path)
    sec, owner = env["sec"], env["owner"]
    first = sec.roster_add(owner=owner, role="E", task_id="t-000001", brief="甲这件活")
    assert first.get("problem") == "", first
    name = str(first.get("name") or "")

    same_id = sec.roster_add(owner=owner, role="E", task_id="t-000001", brief="乙这件活")
    assert same_id.get("problem"), same_id
    assert str(same_id.get("refusal_code") or "") == "task_id_reused", same_id
    assert "task_id_reused" in str(same_id.get("problem")), same_id
    assert len(_add_rows_for(env, "t-000001")) == 1, _adds(env)

    same_name = sec.roster_add(owner=owner, role="E", task_id="t-000002", brief="丙这件活",
                               want_name=name)
    assert same_name.get("problem"), same_name
    assert str(same_name.get("refusal_code") or "") == "name_taken", same_name
    assert "name_taken" in str(same_name.get("problem")), same_name
    assert len(_adds(env)) == 1, _adds(env)


# ---------------------------------------------------------------- r5（销号标死全部号）


def test_r5_retire_marks_every_task_id_the_name_ever_bound(tmp_path: pathlib.Path) -> None:
    """r5：销号写全这个名字绑过的所有号 —— 旧号也要读成"已销号"（否则永久可唤醒）。

    改前读数（`temp/probe_roster_one_row.py` E）：`retired_names` 只有
    `D1/t-000003`；`retired_reading_of(t-000002).retired=False`。
    """
    env = _env(tmp_path)
    sec, cond, owner = env["sec"], env["cond"], env["owner"]
    t1 = _child(cond, owner, tag="r5-a")
    t2 = _child(cond, owner, tag="r5-b")
    first = sec.roster_add(owner=owner, role="D", task_id=t1, brief="第一件活")
    assert first.get("problem") == "", first
    name = str(first.get("name") or "")
    second = sec.roster_add(owner=owner, role="D", task_id=t2, brief="第二件活", reuse=name)
    assert second.get("problem") == "", second

    got = sec.retire(owner=owner, name=name, by_task_id=owner, reason="夹具：复用后销号")
    assert got.get("ok") is True, got
    retired_ids = sorted(str(r.get("task_id")) for r in sec.retired_names(owner)[0])
    assert retired_ids == sorted([t1, t2]), retired_ids
    for tid in (t1, t2):
        reading = cond.retired_reading_of(tid, parent=owner)
        assert reading.get("checked") is True, (tid, reading)
        assert reading.get("retired") is True, (tid, reading)
    again = sec.retire(owner=owner, name=name, by_task_id=owner)
    assert again.get("ok") is False, again


# ---------------------------------------------------------------- r6（已销号的号不许再登记 / 再绑）


def test_r6_a_retired_task_id_cannot_be_added_or_bound_again(tmp_path: pathlib.Path) -> None:
    """r6：已销号的号换个新名字 `add` 必须拒；以 `reuse` 绑给别的名字也必须拒。

    改前读数（`temp/probe_roster_one_row.py` D）：`add` 回 `D2/t-000002`（problem 空），
    随后 `reuse=D2` 再绑同一个号也成功 ⇒ 已销号的号永远销不掉，成为永久孤儿。
    """
    env = _env(tmp_path)
    sec, cond, owner = env["sec"], env["cond"], env["owner"]
    t1 = _child(cond, owner, tag="r6-dead")
    first = sec.roster_add(owner=owner, role="D", task_id=t1, brief="会销号的那件")
    assert first.get("problem") == "", first
    dead_name = str(first.get("name") or "")
    got = sec.retire(owner=owner, name=dead_name, by_task_id=owner, reason="夹具：先销号")
    assert got.get("ok") is True, got

    again = sec.roster_add(owner=owner, role="D", task_id=t1, brief="同一个号再登一次")
    assert again.get("problem"), again
    assert str(again.get("refusal_code") or "") == "task_id_retired", again
    assert "task_id_retired" in str(again.get("problem")), again
    assert len(_adds(env)) == 1, _adds(env)

    live_tid = _child(cond, owner, tag="r6-live")
    live = sec.roster_add(owner=owner, role="D", task_id=live_tid, brief="另一个名字的活")
    assert live.get("problem") == "", live
    live_name = str(live.get("name") or "")
    bind = sec.roster_add(owner=owner, role="D", task_id=t1, brief="想把旧号绑给它",
                          reuse=live_name)
    assert bind.get("problem"), bind
    assert str(bind.get("refusal_code") or "") == "task_id_retired", bind
    assert [str(r.get("task_id")) for r in _binds(env) if str(r.get("name")) == live_name] \
        == [live_tid], _binds(env)


# ---------------------------------------------------------------- r7（按号寻址拒歧义）


def test_r7_addressing_by_a_shared_task_id_refuses_ambiguity(tmp_path: pathlib.Path) -> None:
    """r7：两个名册项共用一个号时，按号寻址必须拒歧义，不许静默取排序第一个。

    改前读数（`temp/probe_roster_one_row.py` F）：`roster_addresses(to=t-000002)`
    回 `how=child / name=D1 / refused=""` —— 第二个名字被静默丢掉。
    """
    env = _env(tmp_path)
    sec, cond, owner = env["sec"], env["cond"], env["owner"]
    shared = _child(cond, owner, tag="r7-shared")
    # 产品写口今天会拒这种形态（r4），夹具只能直接落盘：它模拟的是历史/异常名册。
    for name in ("D1", "D2"):
        SEC.append_jsonl(SEC.roster_path(env["ws"], owner),
                         {"kind": "add", "owner": owner, "name": name, "role": "D",
                          "task_id": shared, "first_task_id": shared,
                          "brief": f"夹具：{name} 与别人共号", "brief_source": "parent",
                          "surface": "", "at": TS})
        SEC.append_jsonl(SEC.roster_index_path(env["ws"], owner),
                         {"kind": "bind", "owner": owner, "name": name, "role": "D",
                          "task_id": shared, "at": TS, "first": True})
    got = roster_addresses(sec, to=shared, owner=owner, my_task_id="t-999999")
    assert got.get("checked") is True, got
    assert str(got.get("refused") or "") == "ambiguous_in_roster", got
    assert sorted(got.get("candidates") or []) == ["D1", "D2"], got
    assert str(got.get("task_id") or "") == shared, got
    assert str(got.get("kind") or "") == "", got
    assert "不替你挑一个" in str(got.get("error") or ""), got
    # 反真空：按名字仍能各自寻址（拒的是"按号多匹配"，不是把这两个名字一起废掉）。
    one = roster_addresses(sec, to="D1", owner=owner, my_task_id="t-999999")
    assert str(one.get("name") or "") == "D1" and not one.get("refused"), one


# ---------------------------------------------------------------- 外加（撞名 ⇒ name_taken，不静默改名）


def test_the_conductor_refuses_a_taken_name_instead_of_renaming(
        tmp_path: pathlib.Path) -> None:
    """`_register_roster`：父给的名字撞车 ⇒ `name_taken` 拒绝，不许静默顺延换名。

    改前读数（`temp/probe_roster_one_row.py` G）：第二次登记回 `name=D2`、`problem=""`，
    note 里写"改用框架顺延发的 D2"；名册里两条行是 `D1/t-000009` 与 `D2/t-000012`。
    """
    env = _env(tmp_path)
    cond, owner = env["cond"], env["owner"]
    first = cond._register_roster(task_id="t-000009", role="D", owner=owner,
                                  meta={"name": "D1", "brief": "研究包A", "task": "做研究"})
    assert first.get("problem") == "", first
    second = cond._register_roster(task_id="t-000012", role="D", owner=owner,
                                   meta={"name": "D1", "brief": "研究包B", "task": "做研究"})
    assert second.get("problem"), second
    assert "name_taken" in str(second.get("problem")), second
    assert str(second.get("state") or "") == "missing", second
    assert "顺延发" not in str(second.get("note") or ""), second
    rows = _adds(env)
    assert [(str(r.get("name")), str(r.get("task_id"))) for r in rows] == [("D1", "t-000009")], rows
    # 反真空：被拒的那一条也没有被兜底自愈偷偷补上（"拒绝交父决定"不是"换个名字继续"）。
    assert _add_rows_for(env, "t-000012") == [], _adds(env)

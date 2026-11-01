# -*- coding: utf-8 -*-
"""判据：兄弟行在「台账行已落、名册行未落」的窗口里，不许被兜底自愈抢名。

## 真机（`draft/158` §二-2 / `draft/159` §一）

81 趟 13 条 `repaired=true` 里 6 条是这一档（t-000011/D3、t-000012/D4、t-000022/F3、
t-000023/F4、t-000065/F3、t-000072/F1）：A 线程已经 `_write_new_row` 落了台账行、
还没走到自己的 `roster_add`；B 线程在 `roster_add` 之后跑 `roster_repair`，读到 A 的行
"台账有、名册没有" ⇒ 按 `next_name` 给 A 发了一个名字补上。A 随后自己的登记撞
`task_id_reused`（点名那一支撞 `name_taken`）—— 拒绝是果，补登记是先发生的那一半。
盘上读数：那 6 个号各自只有一条 `repaired=true` 的 add 行、没有自己的 add 行；拒绝
流水里正好是这 6 个号；补登记行的 `at` 与台账 `started_at` 同秒、`ended_at` 在之后
（当事行当时 `running/outcome=None/ended_at=None`）。

## 这一组守什么（业主 2026-11-02 三条硬要求 + 八条判据）

1. 两条兄弟各自的登记必须写成（`problem==""`、`state=="written"`）；
2. 名册里 `repaired=true` 的 add 行 0 条；
3. 拒绝流水里没有这两个号；
4. 名字按登记顺序连续发（`[D1, D2, D3, D4]`，补登记不再吃掉序号）；
5. 在飞集合在登记之后必须清空（清不掉 = 该号被 repair 永久跳过，静默欠补）；
6. 反真空：没被标在飞的真孤儿仍然要补（在飞集合不是"不补"的开关；79 那趟
   "11 个节点卡住"就是靠这一档解开的）；
7. `roster_repair` 的第三个返回值要能读出哪几个号被跳过（不是只回条数）；
8. 读序负控：`roster_repair` 必须先读 `_tasks()`、后读在飞集合。这条顺序是
   "见行必见标记"的地基 —— 标记在行提交之前落进集合，GIL 保证"看得见行"的读者
   之后一定看得见标记；两处读一对调，地基就没了，而所有正题仍会是绿的。

## 夹具怎么造出那个窗口

不改源文件：把 `Conductor._register_roster` 在实例上包一层，进入时先发信号、
等放行，再调原方法。它只延迟线程，不读写任何被测状态，停在门口时一手锁都没拿
（不在 `_id_lock` / `store.tx` / per-owner 名册锁里）。

T2 先写行、停在门口；A、B 各写行、停在门口（窗口两端都在盘上）；放行 T2 ⇒ 它
`roster_add` 成功并立刻跑 repair；再放行 A、B ⇒ 它们的登记撞什么就是什么。

## 改前读数（HEAD `51326111`）

`5 failed / 1 passed`：两条兄弟被拒（①②③④ 红）、在飞集合不存在（⑤⑦ 红）、
读序判据找不到 `roster_pending`（⑧ 红）；反真空那条（⑥）本来就是绿的。
"""
from __future__ import annotations

import ast
import inspect
import json
import pathlib
import textwrap
import threading

import pytest

from agentflow import secretary as SEC
from agentflow.conductor import Conductor, LocalBackend
from agentflow.secretary import Secretary
from agentflow.store import Store

BR = "2026-10-29T17:00:00+08:00"


class _Handler:
    """最小角色对象：`backend.call` 按 `ActionSpec.handler_name` 找方法。"""

    def __init__(self, tag: str) -> None:
        self.tag = tag

    def __getattr__(self, name: str):
        def _fn(**kw):
            return {"status": "done", "tag": self.tag, "handler": name}
        return _fn


def _env(tmp_path: pathlib.Path) -> tuple[Conductor, Secretary, pathlib.Path, str]:
    ws = tmp_path / "ws"
    st = Store(ws)
    st.init()
    reg = {"D": ("object", _Handler("D")), "F": ("object", _Handler("F"))}
    cond = Conductor(st, policy=None, backend=LocalBackend(reg))
    sec = Secretary("M", root=ws, store=st, enable_model=False)
    cond.secretary = sec
    cond.roster_sink = sec
    top = cond.open_top_level_run("M", "顶趟：兄弟行竞态判据")
    return cond, sec, ws, str(top)


def _adds(ws: pathlib.Path, owner: str) -> list[dict]:
    p = SEC.roster_path(ws, owner)
    if not p.is_file():
        return []
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines()
            if x.strip() and json.loads(x).get("kind") == "add"]


def _refusals(ws: pathlib.Path, owner: str) -> list[dict]:
    p = SEC.refusals_path(ws, owner)
    if not p.is_file():
        return []
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]


class _Parked:
    """把 `_register_roster` 变成「到门口先停一下」的钩子（实例级，不改源文件）。"""

    def __init__(self, cond: Conductor) -> None:
        self.arrived: dict[str, threading.Event] = {}
        self.release: dict[str, threading.Event] = {}
        self.tids: dict[str, str] = {}
        self._orig = cond._register_roster

        def hooked(*, task_id: str, role: str, owner: str, meta=None):
            tag = str((meta or {}).get("park") or "")
            if tag:
                self.tids[tag] = str(task_id)
                self.arrived[tag].set()
                if not self.release[tag].wait(30.0):
                    raise RuntimeError(f"判据超时：{tag} 没被放行")
            return self._orig(task_id=task_id, role=role, owner=owner, meta=meta)

        cond._register_roster = hooked  # type: ignore[method-assign]


def _start(tag: str, cond: Conductor, parent: str, *, role: str, action: str,
           params: dict, by: str, want_name: str = "") -> tuple[dict, threading.Thread]:
    box: dict = {}

    def run() -> None:
        try:
            box["start"] = cond.summon_begin(
                role, action, dict(params), by=by, parent_task_id=parent,
                roster={"brief": f"判据派活 {tag}", "task": f"做 {tag} 这件事",
                        "name": want_name, "park": tag})
        except BaseException as exc:  # noqa: BLE001 - 线程里的异常带回主线程判
            box["err"] = exc

    th = threading.Thread(target=run, name=f"criterion-{tag}", daemon=True)
    th.start()
    return box, th


def _in_window(tmp_path: pathlib.Path, *, role: str, action: str, param: str,
               by: str, want: tuple[str, str] | None) -> dict:
    """跑一遍「两条兄弟停在窗口里、第三条的登记触发自愈」的交错。"""
    cond, sec, ws, parent = _env(tmp_path)
    if by != "M":
        # M 不能派 F（`ALLOWED_EDGES` 里没有 M→F）⇒ F 家族必须由 D 子行当父，
        # 与 81 的树（M→D→F）同形。
        mid = cond.summon("D", "research", {"qid": "fparent"}, parent_task_id=parent,
                          roster={"brief": "F 家族的父亲", "task": "带一批 F"})
        assert str(mid.task_id), mid
        parent = str(mid.task_id)
    park = _Parked(cond)
    first = cond.summon(role, action, {param: f"{role}1"}, by=by, parent_task_id=parent,
                        roster={"brief": "第一件", "task": "做第一件"})
    assert str(first.roster_name) == f"{role}1", first.roster_rec

    for tag in ("T2", "A", "B"):
        park.arrived[tag] = threading.Event()
        park.release[tag] = threading.Event()
    box_t2, th_t2 = _start("T2", cond, parent, role=role, action=action,
                           params={param: f"{role}T2"}, by=by)
    assert park.arrived["T2"].wait(30.0), "T2 没走到 _register_roster 门口"
    box_a, th_a = _start("A", cond, parent, role=role, action=action,
                         params={param: f"{role}A"}, by=by,
                         want_name=(want[0] if want else ""))
    assert park.arrived["A"].wait(30.0), "A 没走到 _register_roster 门口"
    box_b, th_b = _start("B", cond, parent, role=role, action=action,
                         params={param: f"{role}B"}, by=by,
                         want_name=(want[1] if want else ""))
    assert park.arrived["B"].wait(30.0), "B 没走到 _register_roster 门口"
    tids = (park.tids["A"], park.tids["B"])

    # 窗口的机器读数：三行都在台账上、都还没进名册
    before = {str(r.get("task_id")): r for r in cond._tasks()}
    for tid in (park.tids["T2"], *tids):
        assert str(before[tid].get("status")) == "running", before[tid]
        assert before[tid].get("outcome") is None, before[tid]
        assert before[tid].get("ended_at") is None, before[tid]

    park.release["T2"].set()
    th_t2.join(30)
    assert not th_t2.is_alive(), "T2 没回来"
    park.release["A"].set()
    park.release["B"].set()
    th_a.join(30)
    th_b.join(30)
    assert not th_a.is_alive() and not th_b.is_alive(), "A/B 没回来"
    for box in (box_t2, box_a, box_b):
        assert "err" not in box, box.get("err")
        cond.summon_run(box["start"])
    return {
        "ws": ws, "parent": parent, "tids": tids,
        "recs": {t: box["start"].roster_rec for t, box in zip(tids, (box_a, box_b))},
        "adds": _adds(ws, parent), "refs": _refusals(ws, parent),
        "role": role,
    }


@pytest.mark.parametrize("role,action,param,by,want,names", [
    ("D", "research", "qid", "M", None, ("D3", "D4")),
    ("F", "status", "plan_id", "D", ("F3", "F4"), ("F3", "F4")),
])
def test_sibling_in_the_window_is_not_backfilled(tmp_path, role, action, param,
                                                 by, want, names) -> None:
    """① 登记写成 ② 没有 repaired 行 ③ 没有拒绝流水 ④ 名字连续。"""
    got = _in_window(tmp_path, role=role, action=action, param=param, by=by, want=want)
    tid_a, tid_b = got["tids"]
    for tid in (tid_a, tid_b):
        rec = got["recs"][tid]
        assert rec.get("problem") == "", (tid, rec)
        assert rec.get("state") == "written", (tid, rec)
    assert [r for r in got["adds"] if r.get("repaired")] == [], got["adds"]
    assert [r for r in got["refs"] if str(r.get("task_id")) in (tid_a, tid_b)] == [], got["refs"]
    assert [str(r.get("name")) for r in got["adds"]] == [f"{role}1", f"{role}2", *names], \
        [(r.get("name"), r.get("task_id")) for r in got["adds"]]


def test_pending_is_empty_after_a_summon(tmp_path) -> None:
    """⑤ 在飞集合登记完必须清空（清不掉 = 该号被 repair 永久跳过）。"""
    cond, sec, ws, parent = _env(tmp_path)
    first = cond.summon("D", "research", {"qid": "d1"}, parent_task_id=parent,
                        roster={"brief": "第一件", "task": "做第一件"})
    assert str(first.roster_name) == "D1"
    assert SEC.roster_pending(ws, parent) == frozenset(), SEC.roster_pending(ws, parent)


def test_a_real_orphan_is_still_repaired(tmp_path) -> None:
    """⑥ 反真空：没被标在飞的真孤儿仍然要补。"""
    cond, sec, ws, parent = _env(tmp_path)
    orphan = cond._write_new_row({
        "task_id": "", "role": "D", "action": "research", "called_by": "M",
        "parent_task_id": parent, "depth": 2, "input_key": "", "status": "running",
        "outcome": None, "refusal_reason": None, "instance": "", "detail": "",
        "error": None, "started_at": BR, "ended_at": None,
        "tokens": 0, "usd": 0.0, "artifacts": [], "inputs": [],
    }, note="criterion:orphan")
    fixed, why, skipped = _repair3(sec, parent)
    assert (fixed, why, skipped) == (1, "", []), (fixed, why, skipped)
    assert orphan in [str(r.get("task_id")) for r in _adds(ws, parent)]


def _repair3(sec: Secretary, owner: str) -> tuple[int, str, list[str]]:
    """读 `roster_repair` 的三格；旧树只有两格时第三格按空（⑦ 另行咬死三格）。"""
    got = sec.roster_repair(owner=owner)
    fixed, why = got[0], got[1]
    skipped = list(got[2]) if len(got) > 2 else []
    return int(fixed), str(why), skipped


def test_repair_reports_the_ids_it_skipped(tmp_path) -> None:
    """⑦ `skipped` 要列出哪几个号，不是只回条数。"""
    cond, sec, ws, parent = _env(tmp_path)
    orphan = cond._write_new_row({
        "task_id": "", "role": "D", "action": "research", "called_by": "M",
        "parent_task_id": parent, "depth": 2, "input_key": "", "status": "running",
        "outcome": None, "refusal_reason": None, "instance": "", "detail": "",
        "error": None, "started_at": BR, "ended_at": None,
        "tokens": 0, "usd": 0.0, "artifacts": [], "inputs": [],
    }, note="criterion:pending")
    SEC.note_roster_pending(ws, parent, orphan)
    try:
        fixed, why, skipped = sec.roster_repair(owner=parent)
        assert (fixed, why) == (0, ""), (fixed, why)
        assert skipped == [orphan], skipped
        assert [r for r in _adds(ws, parent) if r.get("repaired")] == []
    finally:
        SEC.forget_roster_pending(ws, parent, orphan)
    fixed2, why2, skipped2 = sec.roster_repair(owner=parent)
    assert (fixed2, skipped2) == (1, []), (fixed2, why2, skipped2)


def test_repair_reads_tasks_before_the_in_flight_set(tmp_path) -> None:
    """⑧ 读序负控：先 `_tasks()`、后 `roster_pending`。

    静态一半：AST 比对两个调用的行号（源码顺序）；
    动态一半：给两处读套上记录器，断言运行期顺序。两者任一被对调 ⇒ 本判据红。
    """
    src = textwrap.dedent(inspect.getsource(Secretary.roster_repair))
    tree = ast.parse(src)
    pos: dict[str, int] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if isinstance(fn, ast.Attribute) and fn.attr == "_tasks":
            pos.setdefault("tasks", node.lineno)
        if isinstance(fn, ast.Name) and fn.id == "roster_pending":
            pos.setdefault("pending", node.lineno)
    assert "tasks" in pos and "pending" in pos, pos
    assert pos["tasks"] < pos["pending"], (
        f"`roster_repair` 必须先读 _tasks()（行号 {pos.get('tasks')}）、"
        f"后读 roster_pending（行号 {pos.get('pending')}）：标记在行提交之前落进集合，"
        "反过来读就丢了「见行必见标记」这条保证")

    cond, sec, ws, parent = _env(tmp_path)
    order: list[str] = []
    orig_tasks = cond._tasks
    orig_pending = SEC.roster_pending

    def tasks() -> list[dict]:
        order.append("tasks")
        return orig_tasks()

    def pending(root, owner):
        order.append("pending")
        return orig_pending(root, owner)

    cond._tasks = tasks  # type: ignore[method-assign]
    SEC.roster_pending = pending  # type: ignore[assignment]
    try:
        sec.roster_repair(owner=parent)
    finally:
        cond._tasks = orig_tasks  # type: ignore[method-assign]
        SEC.roster_pending = orig_pending  # type: ignore[assignment]
    assert order[:2] == ["tasks", "pending"], order

# -*- coding: utf-8 -*-
"""Q27：这一行是什么（轴）与它还活不活（活档）是两问，各自只有一处判据。

## 为什么要拆（业主 2026-10-26）

`secretary.task_row_axis` 一次返回五档，但它是两件事挤在一个返回值里：轴（板项 / 顶趟 /
代理 / 别的）与活档（`status` 在 `pending` / `running`）。要"所有代理行（含终态）"的读点
拿不到它（终态代理行被折进 `other`）；要"活着的代理"的读点只能自己再写一遍
`kind == "" and status in {pending, running}` —— 而自己写的那几份正是 Q18 之前板项被数成
"在跑的子代理"的来源。拆开之后：

- `secretary.row_axis(row)`：只回答轴，五档与 Q18 的 `task_row_axis` 逐字同形；
- `secretary.is_live_agent(row)`：只回答"是不是一个活着的代理"（= 轴是 `agent`）。

## 五条判据与各自的改前红

| 判据 | 守的是 | 改前红在哪 |
|---|---|---|
| a | 五档同形 + `is_live_agent == (旧 task_row_axis == agent)`（穷举交叉表） | 改前没有 `row_axis` / `is_live_agent` 这两个名字（本文件第一条测试逐名断言，报"改前红"） |
| b | 48 行真机形状夹具上 `inbox_todos` 两栏逐字不变（`running=0` / `items=30` / 截断读数不变） | 不适用：拆分本身不许动读数（它守的是"拆得干净"） |
| c | P0 两处（`conductor._in_flight_children_of` / `statusreport.collect`）与旧判据同夹具逐条相同，且函数体里不再出现 `get("kind")` | 不适用：迁移必须保读数（改的是判据的出处，不是口径） |
| d | 反真空：把 `is_live_agent` 打桩成恒 True ⇒ b 的两栏判据必红 | 不适用（它守的是"b 真的在读 is_live_agent"，不是真空形态） |
| e | 反真空：把 `row_axis` 打桩成"五档形状不变、status 恒活" ⇒ c 的对拍必红 | 不适用（它守的是"c 真的在看活档"） |

判据写成 `_x_problems()` 返回问题清单（同 `test_information_items_are_acked_when_read.py`
的形态）：红的时候读到的是那份清单的逐字内容，而不是一个断言下标。
"""
from __future__ import annotations

import ast
import inspect
import pathlib
import textwrap
from typing import Any, Callable, Iterable, Mapping

import pytest

import agentflow.secretary as SEC
from agentflow import statusreport as SR
from agentflow.conductor import Conductor, LocalBackend
from agentflow.store import Store

TS = "2026-10-26T00:00:00+08:00"


# ============================================================ 改前的两份判据（oracle，逐字）
def _old_task_row_axis(row: Mapping[str, Any]) -> str:
    """改前 `secretary.task_row_axis` 的逐字实现（2026-10-26 Q18 的树）。

    取值写字面量而不读模块常量：这一份要能独立于被测代码存在，否则"同形"会被
    "两边同时改了一处"骗过去。
    """
    if str(row.get("kind") or ""):
        return "item_closed" if str(row.get("item_state") or "") == "done" else "item_open"
    if (str(row.get("action") or "") == "run"
            and not str(row.get("parent_task_id") or "")):
        return "root"
    if str(row.get("status") or "") in ("pending", "running"):
        return "agent"
    return "other"


def _old_live_rows(rows: Iterable[Mapping[str, Any]]) -> list[str]:
    """改前 P0 两处各自写的那一句判据（逐字）：`kind` 为空 + `status` 在活档。"""
    return [str(r.get("task_id") or "") for r in rows
            if not str(r.get("kind") or "")
            and str(r.get("status") or "") in ("pending", "running")]


# ============================================================ 夹具（真 Store + 真 Conductor）
def _env(root: pathlib.Path) -> dict[str, Any]:
    st = Store(root)
    st.init()
    cond = Conductor(st, policy=None, backend=LocalBackend({}))
    sec = SEC.Secretary("M", root=root, store=st)
    cond.secretary = sec
    owner = str(cond.open_top_level_run("M", "Q27 的夹具"))
    return {"store": st, "cond": cond, "sec": sec, "owner": owner}


def _agent(env: dict[str, Any], *, role: str = "A", action: str = "run_once",
           status: str = "running", outcome: str | None = None,
           ended_at: str | None = None, key: str = "k") -> str:
    """一条代理行（`kind` 为空、有父）。终态行也走这里 —— 拆分要覆盖"含终态的代理行"。"""
    return str(env["cond"]._write_new_row({
        "task_id": "", "role": role, "action": action, "called_by": "M",
        "parent_task_id": env["owner"], "depth": 2, "input_key": f"q27:{key}",
        "status": status, "outcome": outcome, "refusal_reason": None,
        "instance": "", "detail": ("跑完了" if status == "done" else ""), "error": None,
        "started_at": TS, "ended_at": ended_at, "tokens": 0, "usd": 0.0,
        "artifacts": [], "inputs": [],
    }, note="q27:agent"))


def _board(env: dict[str, Any], n: int, *, start: int = 0) -> list[str]:
    """`n` 条板项行（`notice` / `message` 交替）。"""
    out: list[str] = []
    for i in range(start, start + n):
        kind = ("notice", "message")[i % 2]
        out.append(str(env["cond"].open_item(
            kind=kind, role="M", expects="ack", action=kind, summary=f"{i} 号板项",
            called_by="M", parent_task_id=env["owner"], depth=2,
            input_key=f"q27:item{i}")))
    return out


def _rows(env: dict[str, Any]) -> list[dict[str, Any]]:
    return [dict(r) for r in env["store"].rows("tasks")]


def _columns(got: Mapping[str, Any]) -> tuple[dict, dict]:
    return (dict(got.get("running_agents") or {}),
            dict(got.get("pending_items") or {}))


def _fixture_48(env: dict[str, Any]) -> tuple[list[str], list[str]]:
    """真机 48 行的形状：18 条终态代理行（17 ok + 1 no_result）+ 30 条板项行。"""
    agents = [_agent(env, role=("A", "B", "C")[i % 3], status="done",
                     outcome=("ok" if i < 17 else "no_result"), ended_at=TS,
                     key=f"a{i}") for i in range(18)]
    items = _board(env, 30)
    env["cond"].finish_top_level_run(env["owner"], stop_reason="final")
    return agents, items


# ============================================================ a) 五档同形 + 活档判据
#: 五类行各一条（穷举之外的那一眼）：`axis` 是期望的档，`live` 是期望的活档结论。
_FIVE: tuple[tuple[str, dict[str, Any], str, bool], ...] = (
    ("代理行（活档）", {"kind": "", "action": "run_once", "parent_task_id": "t-1",
                        "status": "running"}, "agent", True),
    ("板项行（没收口）", {"kind": "notice", "item_state": "queued", "action": "notice",
                          "parent_task_id": "t-1", "status": "pending"}, "item_open", False),
    ("板项行（已收口）", {"kind": "report", "item_state": "done", "action": "report",
                          "parent_task_id": "t-1", "status": "pending"}, "item_closed", False),
    ("顶趟行", {"kind": "", "action": "run", "parent_task_id": None,
                "status": "running"}, "root", False),
    ("代理行（终态）", {"kind": "", "action": "run_once", "parent_task_id": "t-1",
                        "status": "done", "outcome": "ok"}, "other", False),
)


def test_a_the_axis_and_the_liveness_are_two_names_over_the_same_boxes() -> None:
    """a) `row_axis` 五档与旧 `task_row_axis` 同形；`is_live_agent` 只认代理轴。

    改前红：这两个名字都不存在（下面两行逐名断言会以"改前红"的措辞失败）。
    """
    for name in ("row_axis", "is_live_agent"):
        assert hasattr(SEC, name), (
            f"改前红（2026-10-26 Q27 之前）：secretary 没有 {name} 这个名字 —— "
            "轴与活档还挤在 task_row_axis 一个返回值里")
    assert not hasattr(SEC, "task_row_axis"), (
        "旧名 `task_row_axis` 应当退场：轴与活档拆开之后它指向哪一个说法都会误导读者")

    problems: list[str] = []
    for where, row, want_axis, want_live in _FIVE:
        axis = str(SEC.row_axis(row))
        live = bool(SEC.is_live_agent(row))
        if axis != want_axis:
            problems.append(f"{where}：轴应为 {want_axis!r}，收到 {axis!r}（行 {row}）")
        if live is not want_live:
            problems.append(f"{where}：活档应为 {want_live!r}，收到 {live!r}（行 {row}）")
    assert problems == [], problems


def test_a_the_two_names_agree_with_the_old_axis_over_the_cross_product() -> None:
    """a) 穷举交叉表：同一批行喂给旧判据与两个新名字，逐行相等。

    为什么穷举而不是五条：五类行只证明"五种形状"，而这一次拆分的风险恰恰在
    "某种组合下两处判得不一样"（`kind` × `item_state` × `action` × 父 × `status`）。
    """
    kinds = ("", "notice", "message", "report", "delegation")
    item_states = ("", "queued", "seen", "done")
    actions = ("", "run", "run_once", "formalize")
    parents: tuple[Any, ...] = (None, "", "t-000001")
    statuses = ("", "pending", "running", "done", "failed", "cancelled", "blocked")
    problems: list[str] = []
    n = 0
    for kind in kinds:
        for item_state in item_states:
            for action in actions:
                for parent in parents:
                    for status in statuses:
                        row = {"kind": kind, "item_state": item_state, "action": action,
                               "parent_task_id": parent, "status": status}
                        old = _old_task_row_axis(row)
                        n += 1
                        if str(SEC.row_axis(row)) != old:
                            problems.append(f"轴不同形：旧 {old!r} / 新 "
                                            f"{SEC.row_axis(row)!r}（行 {row}）")
                        if bool(SEC.is_live_agent(row)) is not (old == "agent"):
                            problems.append(f"活档判据与旧轴不等价：旧轴 {old!r} / 新 "
                                            f"{SEC.is_live_agent(row)!r}（行 {row}）")
    assert n >= 1000, f"交叉表没铺开（只有 {n} 行）—— 那样'逐行相等'证明不了什么"
    assert problems == [], problems[:5]


# ============================================================ b) 两栏读数不变
#: 拆分之前（Q18 的树）在同一份 48 行夹具上的逐字读数。
#: 采集方式：真 Store + 真 Conductor + 真 Secretary，`inbox_todos()` 原样打印。
#: 采集日期 2026-10-26，拆分前后各跑一次，逐行相同（探针输出 122 行完全一致）。
_BEFORE_48 = {
    "running_count": 0,
    "running_ids": [],
    "item_count": 30,
    "item_by_kind": {"task": 30},
    "excluded_top_level": 1,
    "excluded_item_closed": 0,
    "truncated": {"shown": 20, "total": 30, "more": 10},
}


def _b_problems(env: dict[str, Any], agents: list[str], items: list[str]) -> list[str]:
    problems: list[str] = []
    got = env["sec"].inbox_todos()
    run_col, item_col = _columns(got)
    if int(run_col.get("count") or 0) != _BEFORE_48["running_count"]:
        problems.append(f"在跑栏读数变了：拆分前 {_BEFORE_48['running_count']}，"
                        f"现在 {run_col.get('count')!r}（18 条代理行全是终态）")
    if [str(x) for x in (run_col.get("ids") or ())] != _BEFORE_48["running_ids"]:
        problems.append(f"在跑栏编号变了：{run_col.get('ids')}")
    if int(item_col.get("count") or 0) != _BEFORE_48["item_count"]:
        problems.append(f"待办栏读数变了：拆分前 {_BEFORE_48['item_count']}，"
                        f"现在 {item_col.get('count')!r}")
    if [str(x) for x in (item_col.get("ids") or ())] != items:
        problems.append(f"待办栏编号变了：期望 30 条板项的编号 {items}，"
                        f"收到 {item_col.get('ids')}")
    if dict(item_col.get("by_kind") or {}) != _BEFORE_48["item_by_kind"]:
        problems.append(f"待办栏分组变了：{item_col.get('by_kind')}")
    for key in ("excluded_top_level", "excluded_item_closed"):
        if int(got.get(key) or 0) != _BEFORE_48[key]:
            problems.append(f"{key} 变了：拆分前 {_BEFORE_48[key]}，现在 {got.get(key)!r}")
    if dict(got.get("truncated") or {}) != _BEFORE_48["truncated"]:
        problems.append(f"截断读数变了：拆分前 {_BEFORE_48['truncated']}，"
                        f"现在 {got.get('truncated')}")
    # 逐行对拍：两栏的成员必须与旧判据逐条相同（这是"逐字相同"的行级证据）
    rows = _rows(env)
    old_agents = _old_live_rows(rows)
    old_items = [str(r.get("task_id") or "") for r in rows
                 if _old_task_row_axis(r) == "item_open"]
    if [str(x) for x in (run_col.get("ids") or ())] != old_agents:
        problems.append(f"在跑栏与旧判据不逐条相同：旧 {old_agents} / "
                        f"新 {run_col.get('ids')}")
    if [str(x) for x in (item_col.get("ids") or ())] != old_items:
        problems.append(f"待办栏与旧判据不逐条相同：旧 {old_items} / 新 {item_col.get('ids')}")
    return problems


def test_b_the_two_columns_do_not_move_when_the_axis_is_split(
        tmp_path: pathlib.Path) -> None:
    """b) 同一份 48 行夹具：拆分前后 `running_agents` / `pending_items` 逐字相同。"""
    env = _env(tmp_path / "ws")
    agents, items = _fixture_48(env)
    assert len(agents) + len(items) + 1 == 49, (len(agents), len(items))
    problems = _b_problems(env, agents, items)
    assert problems == [], problems


# ============================================================ c) P0 两处与旧判据对拍
def _p0_env(tmp_path: pathlib.Path) -> dict[str, Any]:
    """P0 的对拍夹具：活代理 / 活 `action=run` 子 / 终态子 / 板项 / 派活项 / 活顶趟行。

    `action="run"` 那一条是真子代理（父派给它一次 `A.run`，它带着 `parent_task_id`）
    —— 它同时是两根轴的分界样本：`row_axis` 认 `agent`、而 `statusreport.top_runs`
    （本批不动，见交付说明的 P1 清单）会把它数成"顶趟行"。
    """
    env = _env(tmp_path / "ws_p0")
    env["live"] = _agent(env, role="A", key="live")
    env["live_run"] = _agent(env, role="B", action="run", key="liverun")
    env["done"] = _agent(env, role="C", status="done", outcome="ok",
                        ended_at=TS, key="done")
    env["notice"] = str(env["cond"].open_item(
        kind="notice", role="A", expects="ack", summary="收工了", called_by="A",
        parent_task_id=env["owner"], depth=2, input_key="q27:notice"))
    env["work"] = str(env["cond"].open_item(
        kind="delegation", role="A", expects="work", action="run_once",
        summary="派给 A 的活", called_by="M", parent_task_id=env["owner"],
        depth=2, input_key="q27:work"))
    return env


def _c_problems(env: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    rows = _rows(env)
    kids = [str(r.get("task_id") or "") for r in rows
            if str(r.get("parent_task_id") or "") == env["owner"]]
    old_kids = [x for x in _old_live_rows(rows) if x in set(kids)]
    got_kids = [str(x) for x in env["cond"]._in_flight_children_of(env["owner"])]
    if got_kids != old_kids:
        problems.append(f"_in_flight_children_of 与旧判据不逐条相同：旧 {old_kids} / "
                        f"新 {got_kids}")
    for want in (env["live"], env["live_run"]):
        if want not in got_kids:
            problems.append(f"活着的代理 {want} 必须占名额（否则扇出上限形同虚设）："
                            f"{got_kids}")
    for unwanted in (env["done"], env["notice"], env["work"]):
        if unwanted in got_kids:
            problems.append(f"{unwanted} 不是活着的代理，不许进扇出分子：{got_kids}")

    infl = dict(SR.collect(env["store"], env["store"].root).get("in_flight") or {})
    old_all = _old_live_rows(rows)
    got_all = [str(x) for x in (infl.get("running_task_ids") or ())]
    if int(infl.get("running_tasks") or 0) != len(old_all):
        problems.append(f"statusreport 的在飞任务数变了：旧 {len(old_all)} / "
                        f"新 {infl.get('running_tasks')!r}")
    if got_all != old_all:
        problems.append(f"statusreport 的在飞编号与旧判据不逐条相同：旧 {old_all} / 新 {got_all}")
    # 顶趟行必须留在这一格里（F1 的裁定）：它是"谁在派活"的身份行，而 is_live_agent
    # 结构上排掉它 —— 所以 statusreport 那一处必须"代理轴 + 顶趟轴"两根都读。
    if env["owner"] not in got_all:
        problems.append(f"顶趟行 {env['owner']} 被从在飞读数里丢了（它是在飞的那一趟本身）")
    for unwanted in (env["notice"], env["work"], env["done"]):
        if unwanted in got_all:
            problems.append(f"{unwanted} 不是一次还在飞的调用，不许进 running_tasks：{got_all}")
    return problems


def _body_code(fn: Callable[..., Any]) -> str:
    """一个函数的可执行体（去掉 docstring），用于源码级判据。"""
    src = textwrap.dedent(inspect.getsource(fn))
    tree = ast.parse(src)
    node = tree.body[0]
    body = list(getattr(node, "body", []))
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
            and isinstance(body[0].value.value, str):
        body = body[1:]
    return "\n".join((ast.get_source_segment(src, stmt) or "") for stmt in body)


def test_c_the_two_p0_sites_agree_with_the_old_judgement(tmp_path: pathlib.Path) -> None:
    """c) P0 两处与旧判据同夹具逐条相同，且两处函数体里不再自己写 `kind` 判据。"""
    env = _p0_env(tmp_path)
    problems = _c_problems(env)
    # 源码级：`get("kind")` 是改前那两份判据的指纹；迁移之后它不许再出现在这两个函数体里。
    for where, fn in (("conductor._in_flight_children_of",
                       Conductor._in_flight_children_of),
                      ("statusreport.collect", SR.collect)):
        body = _body_code(fn)
        for needle in ('get("kind")', "get('kind')"):
            if needle in body:
                problems.append(f"{where} 的函数体里还有自己的 kind 判据（{needle}）："
                                "迁移要删掉那份判断，不是转发一份")
    assert problems == [], problems


# ============================================================ d) 反真空（收件箱）
def test_d_stubbing_the_liveness_makes_the_two_columns_red(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """d) 反真空：`is_live_agent` 打桩成恒 True ⇒ b 的两栏判据必红。"""
    baseline = _env(tmp_path / "b0")
    agents, items = _fixture_48(baseline)
    base = _b_problems(baseline, agents, items)
    assert base == [], base

    monkeypatch.setattr(SEC, "is_live_agent", lambda row: True)
    stub = _env(tmp_path / "b1")
    stub_agents, stub_items = _fixture_48(stub)
    got = stub["sec"].inbox_todos()
    run_col, item_col = _columns(got)
    assert int(run_col.get("count") or 0) == 48 + 1, (
        "把活档判据打桩成恒 True 之后，在跑栏应当把每一行都数进去（48 行 + 顶趟行）："
        f"{run_col}")
    assert [str(x) for x in (item_col.get("ids") or ())] == [], item_col
    red = _b_problems(stub, stub_agents, stub_items)
    assert red, "把 is_live_agent 打桩成恒 True，两栏判据却仍然绿 ⇒ 它没在读这个判据"
    assert any("在跑栏读数变了" in x or "待办栏读数变了" in x for x in red), red


# ============================================================ e) 反真空（P0 两处）
def _axis_status_always_live(row: Mapping[str, Any]) -> str:
    """五档形状不变，只把"活不活"那一格恒判活（Q27 的反真空桩）。

    形状与 `row_axis` 逐档对齐，唯一的差别是第 3 档不再看 `status` —— 也就是改前
    "status 恒活"那种形态。它必须能把 P0 两处的对拍判据弄红，否则那两处并没有在读
    活档，只是把轴读了一遍。
    """
    if str(row.get("kind") or ""):
        return (SEC.ROW_AXIS_ITEM_CLOSED if str(row.get("item_state") or "") == "done"
                else SEC.ROW_AXIS_ITEM_OPEN)
    if (str(row.get("action") or "") == SEC.TOP_LEVEL_ACTION
            and not str(row.get("parent_task_id") or "")):
        return SEC.ROW_AXIS_ROOT
    return SEC.ROW_AXIS_AGENT


def test_e_stubbing_the_status_makes_the_p0_comparison_red(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """e) 反真空：`row_axis` 五档形状不变、status 恒活 ⇒ c 的对拍必红。"""
    baseline = _p0_env(tmp_path / "c0")
    base = _c_problems(baseline)
    assert base == [], base

    monkeypatch.setattr(SEC, "row_axis", _axis_status_always_live)
    stub = _p0_env(tmp_path / "c1")
    red = _c_problems(stub)
    assert red, ("把 row_axis 打桩成'status 恒活'，P0 两处的对拍却仍然绿 ⇒ "
                 "它们没在看活档")
    assert any("_in_flight_children_of 与旧判据不逐条相同" in x for x in red), red
    assert any("statusreport 的在飞编号与旧判据不逐条相同" in x for x in red), red

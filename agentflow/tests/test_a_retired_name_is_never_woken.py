# -*- coding: utf-8 -*-
"""判据：销了号的名字永远不许被叫醒 —— 闸门必须读真秘书的销号名单。

## 为什么要新起一份（来由是实测，不是设想）

`draft/143` §七 在真 Secretary 上量到一条「不可逆方向」的缺陷：

```text
conductor.py:3459   got = holder() if callable(holder) else holder
真身是 secretary.py:4505  def retired_names(self, owner: str) -> tuple[list[dict], list[str]]
⇒ 无参调 ⇒ TypeError ⇒ 被 3464 的 except 吞掉 ⇒ _is_retired_task 在真秘书下永远是 False
⇒ 已销号的 t-000002 被判 resume、落 wake: 痕、被叫醒两次（§7.3 逐字读数）
```

四个调用点因此全失效（`wake_blocked` 的 retired 档 / `wake_on_lifeline` /
`_ensure_consumer` 的双保险 / `void_items` 的 deaf 证明只剩 `lifeline_suppressed` 一半）。

而既有的 17 条判据全绿，因为它们的"已销号"是形状不同的 dict 替身
（`test_the_block_table_wakes_one_by_one.py:148` 与
`test_the_wake_does_not_resume_a_running_agent.py:70`）：

```python
cond.secretary = type("S", (), {"retired_names": {str(task_id): "夹具：已销号"}})()
```

真身是方法、要 `owner`、返回 `(rows, bad)`；替身与真身分家 ⇒ 那些判据测的是
"`_is_retired_task` 会读 `retired_names` 这个名字"，不是"它读得对"。这正是 `w8`
（读侧与真实生产者不许分家）自己的判据学，只是那一趟只守住了 `block` 的生产者。

## 这一份钉住的四件事（每一条都自带反真空）

| 判据 | 守的是 | 改前红在哪 |
|---|---|---|
| w9 `test_w9_a_real_retirement_is_read_by_the_wake_gate` | 真 `Secretary` ＋ 真销号路径（`conductor.retire_child` → `Secretary.retire` → `out/roster/<父>-retired.jsonl`）造出的已销号名字：`_is_retired_task` 为真、`wake_on_lifeline` 不起、`wake_blocked` 判 skip/retired 且零字节零次叫醒 | 改前 `_is_retired_task=False`、`wake_on_lifeline` 起了、`wake_blocked` 判 resume、`count=1`、叫了两次、`tasks.json` 被写 |
| w10 `test_w10_a_live_name_is_still_woken` | 负控：同一套夹具里不销号 ⇒ 同一条路会叫醒（证明 w9 量的是"销号"这件事，不是"这条路永远不叫"） | 不适用（它是 w9 的反真空，改前改后都必须绿） |
| w11 `test_w11_both_roster_shapes_are_read` | 形状回归：`retired_names` 给 `(rows, bad)` 二元组、给 `list`、给无参可调、给老的 `{号: 理由}` dict —— 四种形状都要被认出 | 改前二元组与 list 都读不出（`{str(x) for x in got}` 得到的是 `"[{...}]"` / `"[]"` 这种字符串），只有 dict 那一种活 |
| w12 `test_w12_an_unreadable_roster_is_not_folded_into_not_retired` | 坏行如实记进读数：销号名单里有一行读不出来 ⇒ 读数说"读不全"（`checked=False`），不许说"没销号" | 改前那一格连"读不全"这个概念都没有（异常被吞成 `False`），改后没接住的话它就退化成 `checked=True, retired=False` |

## 为什么 w9 的板项是手搓的两根轴

两个真实生产者对同一个 owner 是互斥的：`stopctl.block_remaining_tasks` 只翻
`pending`/`running` 的行（要停的是"还没做完的活"），而 `Secretary.retire` 只放行
静默的目标（板项没清 ⇒ 板项闸先拒）。所以"已销号 ＋ 名下还挂着 block 项"这个组合
在同一次真实流程里造不出来，它是 `draft/143` §8.4 记的那个组合：
优雅停止（`block`）之后销号，`settle_retired_row` 不动 `block` 行 ⇒ `status` 仍是 `block`，
而"在飞"闸只认 `pending`/`running`，于是已销号这道闸是唯一还站着的。

因此本夹具分两步，每一步都走真身：① 销号走真 `Secretary.retire`（真名册、真台账、
真销号名单）；② block 板项用 `_blocked_item` 的两根轴形状（与
`test_the_block_table_wakes_one_by_one.py` 同一份夹具，`w8` 已经把"真实生产者造的
block 行"单独钉住了）。`_w9_problems` 里对这两步各有"夹具自己成立"的断言 ——
夹具坏了要说"夹具坏了"，不许算成闸门坏了。

## 零模型

`Secretary(..., enable_model=False)`；`resume_runner` 是记账替身（生产里由
`host.wired_conductor` 接上）。没有角色循环、没有模型调用。
"""

from __future__ import annotations

import json
import pathlib
from typing import Any

from agentflow import secretary as SEC
from agentflow.conductor import Conductor, LocalBackend, calling_as
from agentflow.secretary import Secretary
from agentflow.store import Store
from agentflow.tools import ToolRegistry
from agentflow.tools import conductor_tools as CT

TS = "2026-01-01T00:00:00+00:00"

#: 回执顶层键集（与 `Conductor.wake_blocked` 的 docstring 同形同集）。
RECEIPT_KEYS = {"checked", "state", "items", "count", "requested", "reason"}

#: 一条回执项的键集（逐项同形同集）。
ITEM_KEYS = {"item_id", "task_id", "owner", "verdict", "started",
             "refusal_code", "why", "mark"}


# ====================================================================== 夹具
def _workspace(tmp_path: pathlib.Path, name: str) -> dict[str, Any]:
    """一个工作区 ＋ 一个主控 ＋ 真秘书 ＋ 一个记着"谁被叫过"的执行侧。"""
    root = tmp_path / name
    store = Store(root)
    store.init()
    cond = Conductor(store, registry={}, backend=LocalBackend({}))
    sec = Secretary("M", root=root, store=store, enable_model=False)
    # 生产里由 `AgentLoop._bind_roster_sink` 接上（与 `test_retire_only_for_the_silent.py` 同一条取法）：
    # 销号与登记名册必须落同一份名册，否则判据测的不是生产形态。
    cond.roster_sink = sec
    # 生产里 `agent_loop.py` 还有这一句（`cond.secretary = sec`）：它是 `_is_retired_task`
    # 读销号名单那一格的来路。不接它，这一份判据量的就只是"没有秘书"那一档。
    cond.secretary = sec
    calls: list[str] = []

    def _runner(tid: str, **_kw: Any) -> dict[str, Any]:
        calls.append(str(tid))
        return {"started": True, "task_id": str(tid), "reason": "夹具：叫起来了"}

    cond.resume_runner = _runner
    boss = str(cond.open_top_level_run("M", "夹具：销了号的名字不许被叫醒"))
    return {"root": root, "store": store, "cond": cond, "sec": sec,
            "boss": boss, "calls": calls}


def _agent(cond: Conductor, parent: str, *, status: str = "done", role: str = "D") -> str:
    """一个代理行（`kind` 空 = 实例行）；`done` 带 `ended_at`，好让它是静默的。"""
    row = {"role": role, "action": "write_report", "called_by": "M",
           "parent_task_id": parent, "depth": 2,
           "input_key": f"retired-gate:{role}:{status}", "status": status,
           "outcome": ("ok" if status == "done" else None), "refusal_reason": None,
           "instance": "", "detail": "夹具代理",
           "error": None, "started_at": TS,
           "ended_at": (TS if status in ("done", "cancelled", "failed", "block") else None),
           "tokens": 0, "usd": 0.0, "artifacts": [], "inputs": []}
    return str(cond._write_new_row(row, note="fixture:retired_gate"))


def _blocked_item(cond: Conductor, owner: str, *, tag: str = "w9") -> str:
    """一条 block 板项（`status` 与 `item_state` 两根轴同时停）。

    形状与 `test_the_block_table_wakes_one_by_one.py::_blocked_item` 逐字同源：
    `seen_by`/`seen_step` 都填上（直写必须清掉它们），`inputs` 带一条旧落痕
    （直写只许追加）。
    """
    row = {"role": "D", "action": "write_report", "called_by": owner,
           "parent_task_id": owner, "depth": 3,
           "input_key": f"item:{owner}:{tag}",
           "status": "block", "outcome": None, "refusal_reason": None, "instance": "",
           "detail": "优雅停止（budget）：这活停在这里、没做完",
           "error": None, "started_at": TS, "ended_at": TS,
           "tokens": 0, "usd": 0.0, "artifacts": [],
           "inputs": ["blocked:fixture@x|夹具"],
           "kind": "delegation", "expects": "work", "item_state": "block",
           "item_close": "", "seen_by": owner, "seen_step": 3, "keep_alive": False}
    return str(cond._write_new_row(row, note="fixture:retired_gate"))


def _retire_for_real(env: dict[str, Any]) -> dict[str, Any]:
    """走真销号路径：名册登记 → 工具 `conductor.retire_child` → `Secretary.retire`。

    刻意不 `append_jsonl` 手造那一行：销号名单的行形状（`owner`/`name`/`task_id`/
    `role`/`at`/`reason`/`branch`）是生产者的事实，判据要读的是生产者写出来的东西。
    手造行只能证明"我会读我自己想出来的形状"—— 那正是 `draft/143` §7.4 记的那条教训。
    """
    boss = str(env["boss"])
    child = _agent(env["cond"], boss, status="done")
    added = env["sec"].roster_add(owner=boss, role="D", task_id=child, brief="写研究报告")
    name = str(added.get("name") or "")
    reg = ToolRegistry(name="retired-gate")
    CT.register(reg, store=env["store"], conductor=env["cond"])
    with calling_as(boss, "M"):
        res = reg.call("conductor.retire_child", {"child_name": name}, role="M")
    return {"child": child, "name": name, "ok": bool(getattr(res, "ok", False)),
            "data": dict(getattr(res, "data", None) or {})}


def _retired_rows(env: dict[str, Any], owner: str) -> tuple[list[dict], list[str]]:
    """父名下那份销号名单（真读口：`Secretary.retired_names`）。"""
    return env["sec"].retired_names(str(owner))


def _tasks_bytes(env: dict[str, Any]) -> bytes:
    """`tasks.json` 的字节（"零字节"的唯一硬判据：逐字节比）。"""
    return (pathlib.Path(str(env["root"])) / "data" / "tasks.json").read_bytes()


def _rows(env: dict[str, Any]) -> dict[str, dict]:
    return {str(r.get("task_id")): r for r in env["store"].rows("tasks")}


def _verdicts(got: Any) -> dict[str, dict]:
    return {str(c.get("item_id")): dict(c) for c in ((got or {}).get("items") or ())}


def _shapes(got: Any) -> list[str]:
    """回执形状问题（顶层键集 ＋ 逐项键集）：空表 = 形状对。"""
    problems: list[str] = []
    if set(got or {}) != RECEIPT_KEYS:
        problems.append(f"回执顶层键集不对：{sorted(got or {})}")
    for i, cell in enumerate((got or {}).get("items") or ()):
        if set(cell) != ITEM_KEYS:
            problems.append(f"第 {i} 项键集不对：多 {sorted(set(cell) - ITEM_KEYS)}、"
                            f"少 {sorted(ITEM_KEYS - set(cell))}")
    return problems


# ====================================================================== w9 真销号
def _w9_problems(env: dict[str, Any]) -> list[str]:
    """(w9) 的判据本体：真销号之后，四条路一条都不许把它叫醒。"""
    problems: list[str] = []
    retired = _retire_for_real(env)
    owner = str(retired["child"])
    if not retired["ok"] or retired["data"].get("state") != "retired":
        return [f"夹具自己没成立：真销号没成（{retired['data'].get('state')!r} / "
                f"{retired['data'].get('refusal_code')!r} / {retired['data'].get('why')!r}）"]

    # ① 反真空：夹具里接的必须是真身，dict 替身不许混进来
    if not isinstance(env["cond"].secretary, Secretary):
        problems.append(f"夹具退化成替身了：{type(env['cond'].secretary).__name__}")

    # ② 名册侧读得出这一行（正控：销号真的落盘了，且行形状是生产者写的）
    rows, bad = _retired_rows(env, str(env["boss"]))
    if bad:
        problems.append(f"夹具自己没成立：销号名单有坏行 {bad!r}")
    if [str(r.get("task_id") or "") for r in rows] != [owner]:
        problems.append(f"夹具自己没成立：销号名单里该恰好是 {owner}，实际 {rows!r}")
    elif str(rows[0].get("name") or "") != str(retired["name"]):
        problems.append(f"夹具自己没成立：销号名单那一行的名字该是 {retired['name']!r}，"
                        f"实际 {rows[0].get('name')!r}")

    # ③ 闸门自己（改前：永远 False）
    if env["cond"]._is_retired_task(owner) is not True:
        problems.append(f"{owner} 已销号 ⇒ `_is_retired_task` 必须是 True，"
                        f"实际 {env['cond']._is_retired_task(owner)!r}")

    # ④ 叫不醒（改前：started=True）
    woke = env["cond"].wake_on_lifeline(owner)
    if woke.get("started") is not False:
        problems.append(f"已销号 ⇒ `wake_on_lifeline` 不许叫起来，实际 {woke!r}")
    if "销号" not in str(woke.get("reason") or ""):
        problems.append(f"叫不醒的理由要点名「销号」：{woke.get('reason')!r}")
    if env["calls"]:
        problems.append(f"`wake_on_lifeline` 已经叫了人：calls={env['calls']}")

    # ⑤ 经真工具入口：verdict 必须 skip / retired，且零字节、零次叫醒
    item = _blocked_item(env["cond"], owner)
    before = _tasks_bytes(env)
    res = env["cond"].wake_blocked([item], approve="yes", dry_run=False)
    problems += _shapes(res)
    cell = _verdicts(res).get(item) or {}
    if cell.get("verdict") != "skip":
        problems.append(f"已销号的 owner ⇒ 逐条该判 skip，实际 {cell.get('verdict')!r}"
                        f"（why={cell.get('why')!r}）")
    if cell.get("refusal_code") != "retired":
        problems.append(f"理由码该是 retired，实际 {cell.get('refusal_code')!r}")
    if cell.get("started") is not False:
        problems.append(f"已销号那一档不许 started=True：{cell.get('started')!r}")
    if cell.get("mark"):
        problems.append(f"已销号那一档不许落 wake: 痕：{cell.get('mark')!r}")
    if int(res.get("count") or 0) != 0:
        problems.append(f"一条都不许叫起来，count 该是 0，实际 {res.get('count')!r}")
    if env["calls"]:
        problems.append(f"已销号 ⇒ 一次都不许叫，calls={env['calls']}")
    if before != _tasks_bytes(env):
        problems.append("已销号那一档一个字节都不许写：`tasks.json` 前后不是逐字节一致")
    row = _rows(env).get(item) or {}
    if str(row.get("item_state")) != "block" or str(row.get("status")) != "block":
        problems.append("已销号那一档不许动板项："
                        f"status={row.get('status')!r}、item_state={row.get('item_state')!r}")
    return problems


def test_w9_a_real_retirement_is_read_by_the_wake_gate(tmp_path: pathlib.Path) -> None:
    """w9) 真 Secretary ＋ 真销号路径 ⇒ 闸门读得到、叫不醒、零字节。

    这一条是 §7.1 那两处独立错（签名要 `owner`、返回 `(rows, bad)` 且键是 `name`/`task_id`）
    的机器读数：三处一起红，且红在真身而不是替身上。
    """
    problems = _w9_problems(_workspace(tmp_path, "w9"))
    assert problems == [], problems


# ====================================================================== w10 负控
def test_w10_a_live_name_is_still_woken(tmp_path: pathlib.Path) -> None:
    """w10) 负控：没销号 ⇒ 同一套调用会叫醒（证明 w9 量的是"销号"这件事）。

    没有这一条，w9 在一个"`_is_retired_task` 恒 True"的实现下也是绿的 —— 那会让
    每一个静默的代理从此再也收不到信（另一种不可逆）。
    """
    env = _workspace(tmp_path, "w10")
    owner = _agent(env["cond"], str(env["boss"]), status="done")
    item = _blocked_item(env["cond"], owner)
    problems: list[str] = []

    rows, bad = _retired_rows(env, str(env["boss"]))
    if rows or bad:
        problems.append(f"夹具自己没成立：这一份不该有销号名单，实际 rows={rows!r} bad={bad!r}")

    if env["cond"]._is_retired_task(owner) is not False:
        problems.append(f"{owner} 没销号 ⇒ `_is_retired_task` 必须是 False，"
                        f"实际 {env['cond']._is_retired_task(owner)!r}")

    woke = env["cond"].wake_on_lifeline(owner)
    if woke.get("started") is not True:
        problems.append(f"没销号 ⇒ `wake_on_lifeline` 该叫得起来，实际 {woke!r}")
    if env["calls"] != [owner]:
        problems.append(f"该叫的号是 {owner}，实际 calls={env['calls']}")

    env["calls"].clear()
    before = _tasks_bytes(env)
    res = env["cond"].wake_blocked([item], approve="yes", dry_run=False)
    problems += _shapes(res)
    cell = _verdicts(res).get(item) or {}
    if cell.get("verdict") != "resume":
        problems.append(f"没销号、静默、板项未终态 ⇒ 该判 resume，实际 {cell.get('verdict')!r}"
                        f"（why={cell.get('why')!r}）")
    if res.get("state") != "woken" or int(res.get("count") or 0) != 1:
        problems.append(f"负控要真的叫起来：state={res.get('state')!r} "
                        f"count={res.get('count')!r}")
    if env["calls"] != [owner]:
        problems.append(f"负控里执行侧该被叫一次：calls={env['calls']}")
    if before == _tasks_bytes(env):
        problems.append("负控里 `tasks.json` 该被写（板项由 block 翻成 queued），实际逐字节没变")
    assert problems == [], problems


# ====================================================================== w11 形状回归
#: `retired_names` 的真实行形状（生产者写的七个键）。
_ROW = {"owner": "t-000001", "name": "D1", "task_id": "t-000002", "role": "D",
        "at": TS, "reason": "夹具：已销号", "branch": "waiting_no_children"}


def _stub(shape: str, task_id: str) -> Any:
    """四种读口形状各造一份替身（刻意不用 dict 当"唯一正确形状"）。

    - `"tuple"`：真身的形状（要 `owner`，返回 `(rows, bad)`）；
    - `"list"`：返回行列表；
    - `"list_no_arg"`：无参可调、返回行列表（改前那句 `holder()` 假定的形状）；
    - `"mapping"`：老的 dict 替身（现役判据用的那一种，不许被新实现弄死）。
    """
    row = dict(_ROW, task_id=task_id)

    if shape == "tuple":
        class _Tuple:
            def retired_names(self, owner: str) -> tuple[list[dict], list[str]]:
                return [row], []
        return _Tuple()

    if shape == "list":
        class _List:
            def retired_names(self, owner: str) -> list[dict]:
                return [row]
        return _List()

    if shape == "list_no_arg":
        class _NoArg:
            def retired_names(self) -> list[dict]:
                return [row]
        return _NoArg()

    if shape == "mapping":
        class _Mapping:
            retired_names = {task_id: "夹具：已销号"}
        return _Mapping()

    raise AssertionError(f"没有这种形状：{shape!r}")


def _w11_problems(tmp_path: pathlib.Path) -> list[str]:
    """(w11) 的判据本体：四种读口形状都要被认出（同一条闸门，四种壳）。"""
    problems: list[str] = []
    for shape in ("tuple", "list", "list_no_arg", "mapping"):
        env = _workspace(tmp_path, f"w11-{shape}")
        owner = _agent(env["cond"], str(env["boss"]), status="done")
        item = _blocked_item(env["cond"], owner)
        env["cond"].secretary = _stub(shape, owner)
        if env["cond"]._is_retired_task(owner) is not True:
            problems.append(f"[{shape}] 销号名单里明明有 {owner}，"
                            f"`_is_retired_task` 却是 {env['cond']._is_retired_task(owner)!r}")
        before = _tasks_bytes(env)
        res = env["cond"].wake_blocked([item], approve="yes", dry_run=False)
        problems += [f"[{shape}] {p}" for p in _shapes(res)]
        cell = _verdicts(res).get(item) or {}
        if cell.get("refusal_code") != "retired" or cell.get("verdict") != "skip":
            problems.append(f"[{shape}] 该判 skip/retired，实际 "
                            f"{cell.get('verdict')!r}/{cell.get('refusal_code')!r}"
                            f"（why={cell.get('why')!r}）")
        if env["calls"]:
            problems.append(f"[{shape}] 已销号却叫了人：calls={env['calls']}")
        if before != _tasks_bytes(env):
            problems.append(f"[{shape}] 已销号却写了盘（`tasks.json` 不是逐字节一致）")
    return problems


def test_w11_both_roster_shapes_are_read(tmp_path: pathlib.Path) -> None:
    """w11) 防形状回归：`(rows, bad)` 与 `list` 两种返回都要活（外加无参可调与老 dict）。"""
    problems = _w11_problems(tmp_path)
    assert problems == [], problems


# ====================================================================== w12 坏行
def test_w12_an_unreadable_roster_is_not_folded_into_not_retired(
        tmp_path: pathlib.Path) -> None:
    """w12) 坏行如实记：销号名单读不全 ⇒ 读数说"读不全"，不许说"没销号"。

    三态纪律在这一格上的落点。方向仍是 `_is_retired_task` docstring 那一句
    （读不到 ⇒ 宁可叫它：叫醒一个还在的代理只花一次循环，而把一个还在的代理当成
    已销号会让它永远收不到信）—— 但"叫了"与"没销号"是两件事：读数必须分得开，
    否则下一次读的人只会看到一句"它没销号"，而盘上其实有一行读不出来。

    夹具走真读口：真 `Secretary` ＋ 盘上一份混着坏行的销号名单（不是打桩）。
    """
    env = _workspace(tmp_path, "w12")
    owner = _agent(env["cond"], str(env["boss"]), status="done")
    path = SEC.retired_path(str(env["root"]), str(env["boss"]))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "{ 这一行不是 JSON —— 销号名单读不全\n"
        + json.dumps(dict(_ROW, task_id="t-999999"), ensure_ascii=False) + "\n",
        encoding="utf-8")
    problems: list[str] = []

    rows, bad = _retired_rows(env, str(env["boss"]))
    if not bad:
        problems.append(f"夹具自己没成立：这一份销号名单该读出坏行，实际 rows={rows!r} bad={bad!r}")

    got = env["cond"]._is_retired_task(owner)
    if got is not False:
        problems.append(f"坏行那一档没有把握 ⇒ `_is_retired_task` 该取保守侧 False，实际 {got!r}")
    reading = dict(getattr(env["cond"], "last_retired_reading", {}) or {})
    if not reading:
        problems.append("`_is_retired_task` 没有留下读数（这一格判据读不到任何东西）")
    else:
        if reading.get("checked") is not False:
            problems.append(f"读不全 ⇒ 读数里 checked 该是 False，实际 {reading.get('checked')!r}"
                            f"（{reading!r}）")
        if not reading.get("bad"):
            problems.append(f"读不全 ⇒ 读数里要原样带着坏行，实际 bad={reading.get('bad')!r}")
        if reading.get("retired") is not False:
            problems.append(f"这一档没读到它已销号 ⇒ retired 该是 False，实际 "
                            f"{reading.get('retired')!r}")
    why = str(reading.get("reason") or "")
    if "读不全" not in why and "读不出" not in why:
        problems.append(f"读数的 reason 要说明是「读不全」，不许折成「没销号」：{why!r}")

    # 动作侧仍走 fail-open（方向见 `_is_retired_task` 的 docstring），但回执要如实带上那一句。
    item = _blocked_item(env["cond"], owner)
    res = env["cond"].wake_blocked([item], approve="yes", dry_run=True)
    cell = _verdicts(res).get(item) or {}
    if cell.get("verdict") != "resume":
        problems.append(f"方向取「宁可叫它」⇒ 该判 resume，实际 {cell.get('verdict')!r}"
                        f"（why={cell.get('why')!r}）")
    if "读不全" not in str(cell.get("why") or ""):
        problems.append(f"回执的 why 要写明销号名单读不全（否则读的人以为「它没销号」）："
                        f"{cell.get('why')!r}")
    assert problems == [], problems

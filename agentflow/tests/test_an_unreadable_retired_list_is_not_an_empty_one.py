# -*- coding: utf-8 -*-
"""判据（先红）：销号名单「读不全」不许与「名单为空」同形 —— w13 / w13b / w14。

## 来由（`draft/145` §一，全部是盘上读数，不是设想）

`Secretary.retired_names(owner)` 就是 `jsonlfile.read_jsonl(<父>-retired.jsonl)`，它的
`bad` 只认两件事：某行不是合法 JSON、或合法 JSON 但不是对象（`jsonlfile.py:87-98`）。
其余每一种「读不全」都不出现在 `bad` 里，于是 `Conductor.retired_reading_of` 的
`checked = not bad`（`conductor.py:3640`）读成 True，回执就写出一句没有根据的「未销号」：

```text
盘上形态                                  bad   checked  _is_retired_task  wake_blocked
行还在、只是少了 task_id 这一格            []    True     False             resume（叫了）
task_id 被写成 int                         []    True     False             resume（叫了）
整份名单落在另一个父的分片里（文件缺失）    []    True     False             resume（叫了）
```

前两种最要命：名字那一格明明写着「这个号销过」，而闸门手里只有号，于是它读成
「没销号」并把代理叫起来 —— 与 `draft/143` §7.3 那一类同向（已销号却仍会被叫醒），
只是这一次坏的不是签名，是行本身。

## 这一份钉住的三件事（顺序就是落地的顺序）

| 判据 | 守的是 | 今天红在哪 |
|---|---|---|
| w13 | 读数：读不全必须自报（`checked=False` ＋ `bad`/`reason`），回执里要有一处能读出「读不全」；而那一行认不出来时 `_is_retired_task` 仍取 False（不知道不许说成已销号） | 少了 `task_id` 那一档：`checked=True`、`reason=''`、回执 `refusal_code=''` 且 `why` 里一个字都没有。同一文件里的 `bad_line` 那一档今天是正控（坏行被记进 `bad`，读数自报） |
| w13b | 负控：名单为空（文件不存在 / 空文件）不是读不全 —— 它必须是 `checked=True`，而且照样叫得起来 | 不适用（它是 w13/w14 的反真空，今天必须绿） |
| w14 | 动作：读不全 ⇒ 不叫醒（`wake_on_lifeline` 不起、`wake_blocked` 判 `review` ＋ `unknown_retired`、零字节零次叫醒），且同一条判据里自带反真空（同一份夹具里另一个没销号的号照样叫得起来） | `missing_task_id` 那一档：判 `resume`、`count=1`、叫了人、`tasks.json` 被写。`bad_line` 那一档今天是回归半边（结论仍是 `skip`/`retired`，必须保持） |

## 「读不全 ⇒ 不叫醒」这一条与业主裁定的关系（写清楚，免得下一读的人以为它已是定论）

w13 只钉「读数必须分得开」，它今天红、改完读数就绿，与 fail-closed 那个方向无关。
w14 钉的是 `draft/145` §三 建议的方向（读不全 ⇒ 不叫醒）。这一条的方向是对是错由业主裁定：
若裁定取反（仍旧宁可叫它），要改的是 w14 而不是实现 —— 那时它从「先红」变成一条
「钉住 fail-open 方向」的判据，同样有用。

## 为什么 `_is_retired_task` 在 w13/w14 里都必须是 False

两种折叠都不许：

- 折成 True ⇒ 一个「读不出」的号从此再也收不到任何信（不可逆的另一种）；
- 折成 False 并且不说 ⇒ 今天这个洞（已销号却仍被叫醒）。

所以布尔只回「读到了匹配行没有」，而「读不全」由 `last_retired_reading` 与回执承担；
动作侧要看的是那份读数，不是这个布尔。

## 零模型

`Secretary(..., enable_model=False)`；`resume_runner` 是记账替身。没有角色循环、没有模型调用。
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

#: 「读不全」这一档的建议档名（`draft/145` §三）：与既有的 `unknown_reading` 同族，
#: 但单独一格 —— 两者要同时出现时（子树读数也坏）还能分得清是哪一格坏。
UNKNOWN_RETIRED = "unknown_retired"

#: 读数 `reason` 里必须出现的那几个词之一（三档措辞都算自报）。
SAYS_INCOMPLETE = ("读不全", "读不出", "没查成")


# ====================================================================== 夹具
def _workspace(tmp_path: pathlib.Path, name: str) -> dict[str, Any]:
    """一个工作区 ＋ 一个主控 ＋ 真秘书 ＋ 一个记着「谁被叫过」的执行侧。"""
    root = tmp_path / name
    store = Store(root)
    store.init()
    cond = Conductor(store, registry={}, backend=LocalBackend({}))
    sec = Secretary("M", root=root, store=store, enable_model=False)
    # 生产装配的两句（`agent_loop.py` / `test_retire_only_for_the_silent.py` 同一取法）：
    # 登记与销号必须落同一份名册，销号名单那一格才读得到。
    cond.roster_sink = sec
    cond.secretary = sec
    calls: list[str] = []

    def _runner(tid: str, **_kw: Any) -> dict[str, Any]:
        calls.append(str(tid))
        return {"started": True, "task_id": str(tid), "reason": "夹具：叫起来了"}

    cond.resume_runner = _runner
    boss = str(cond.open_top_level_run("M", "夹具：销号名单读不全"))
    return {"root": root, "store": store, "cond": cond, "sec": sec,
            "boss": boss, "calls": calls}


def _agent(cond: Conductor, parent: str, *, role: str = "D", tag: str = "") -> str:
    """一个代理行（`kind` 空 = 实例行）；`done` 带 `ended_at`，好让它是静默的。"""
    return str(cond._write_new_row({
        "role": role, "action": "write_report", "called_by": "M",
        "parent_task_id": parent, "depth": 2,
        "input_key": f"retired-unreadable:{role}:{tag}", "status": "done",
        "outcome": "ok", "refusal_reason": None, "instance": "",
        "detail": "夹具代理", "error": None, "started_at": TS, "ended_at": TS,
        "tokens": 0, "usd": 0.0, "artifacts": [], "inputs": [],
    }, note="fixture:retired_unreadable"))


def _blocked_item(cond: Conductor, owner: str, *, tag: str) -> str:
    """一条 block 板项（`status` 与 `item_state` 两根轴同时停）。

    形状与 `test_the_block_table_wakes_one_by_one.py::_blocked_item` 同源（`w12` 已经
    用过同一份形状）。为什么手搓：两个真实生产者对同一个 owner 互斥（见 w12 的 docstring）。
    """
    return str(cond._write_new_row({
        "role": "D", "action": "write_report", "called_by": owner,
        "parent_task_id": owner, "depth": 3,
        "input_key": f"item:{owner}:{tag}",
        "status": "block", "outcome": None, "refusal_reason": None, "instance": "",
        "detail": "优雅停止（budget）：这活停在这里、没做完",
        "error": None, "started_at": TS, "ended_at": TS,
        "tokens": 0, "usd": 0.0, "artifacts": [],
        "inputs": ["blocked:fixture@x|夹具"],
        "kind": "delegation", "expects": "work", "item_state": "block",
        "item_close": "", "seen_by": owner, "seen_step": 3, "keep_alive": False,
    }, note="fixture:retired_unreadable"))


def _retire_for_real(env: dict[str, Any]) -> dict[str, Any]:
    """走真销号路径：名册登记 → 工具 `conductor.retire_child` → `Secretary.retire`。

    刻意不手造销号名单那一行：行形状是生产者的事实（`owner`/`name`/`task_id`/`role`/
    `at`/`reason`/`branch`），本文件只在这份真行上做「少一格」「追加一行坏 JSON」这种
    盘上改动，不许自己编一个形状。
    """
    boss = str(env["boss"])
    child = _agent(env["cond"], boss, tag="retired")
    added = env["sec"].roster_add(owner=boss, role="D", task_id=child, brief="写研究报告")
    name = str(added.get("name") or "")
    reg = ToolRegistry(name="retired-unreadable")
    CT.register(reg, store=env["store"], conductor=env["cond"])
    with calling_as(boss, "M"):
        res = reg.call("conductor.retire_child", {"child_name": name}, role="M")
    return {"child": child, "name": name, "ok": bool(getattr(res, "ok", False)),
            "data": dict(getattr(res, "data", None) or {})}


def _retired_file(env: dict[str, Any]) -> pathlib.Path:
    return SEC.retired_path(str(env["root"]), str(env["boss"]))


def _real_row(env: dict[str, Any]) -> dict[str, Any]:
    """销号名单里那一行（真生产者写的）。"""
    rows, bad = env["sec"].retired_names(str(env["boss"]))
    assert not bad, bad
    assert len(rows) == 1, rows
    return dict(rows[0])


def _drop_key_rewrite(env: dict[str, Any], key: str) -> None:
    """把那一行里某一格删掉再写回（行的其余键逐字不动）。"""
    row = _real_row(env)
    row.pop(key, None)
    path = _retired_file(env)
    path.write_text(json.dumps(row, ensure_ascii=False) + "\n",
                    encoding="utf-8", newline="")


def _append_broken_line(env: dict[str, Any]) -> None:
    """在真行之后追加一行读不出来的（进程被杀 / 追加写交错的那一档）。"""
    path = _retired_file(env)
    before = path.read_text(encoding="utf-8")
    path.write_text(before + "{ 这一行不是 JSON\n", encoding="utf-8", newline="")


def _tasks_bytes(env: dict[str, Any]) -> bytes:
    """`tasks.json` 的字节（「零字节」的唯一硬判据：逐字节比）。"""
    return (pathlib.Path(str(env["root"])) / "data" / "tasks.json").read_bytes()


def _cell(res: Any, item: str) -> dict[str, Any]:
    for c in ((res or {}).get("items") or ()):
        if str(c.get("item_id")) == str(item):
            return dict(c)
    return {}


def _shape_problems(res: Any) -> list[str]:
    """回执形状问题（顶层键集 ＋ 逐项键集）：空表 = 形状对。"""
    problems: list[str] = []
    if set(res or {}) != RECEIPT_KEYS:
        problems.append(f"回执顶层键集不对：{sorted(res or {})}")
    for i, cell in enumerate((res or {}).get("items") or ()):
        if set(cell) != ITEM_KEYS:
            problems.append(f"第 {i} 项键集不对：多 {sorted(set(cell) - ITEM_KEYS)}、"
                            f"少 {sorted(ITEM_KEYS - set(cell))}")
    return problems


def _says_incomplete(text: Any) -> bool:
    got = str(text or "")
    return any(word in got for word in SAYS_INCOMPLETE)


# ====================================================================== w13 读数
def _w13_problems(tmp_path: pathlib.Path, case: str) -> list[str]:
    """(w13) 的判据本体：一行「读不全」的销号名单必须自报，不许读成「名单为空」。

    `case` 是盘上那一种形态：
    - `"missing_task_id"`：这一行写着「D 这个名字销号了」，只是没有号那一格；
    - `"bad_line"`：真行后面追加一行读不出来的 JSON。
    """
    env = _workspace(tmp_path, f"w13-{case}")
    retired = _retire_for_real(env)
    owner = str(retired["child"])
    problems: list[str] = []
    if not retired["ok"] or retired["data"].get("state") != "retired":
        return [f"夹具自己没成立：真销号没成（{retired['data'].get('state')!r} / "
                f"{retired['data'].get('why')!r}）"]
    if case == "missing_task_id":
        _drop_key_rewrite(env, "task_id")
    elif case == "bad_line":
        _append_broken_line(env)
    else:
        raise AssertionError(f"没有这种形态：{case!r}")

    rows, bad = env["sec"].retired_names(str(env["boss"]))
    if case == "bad_line" and not bad:
        return [f"夹具自己没成立：这一份该读出坏行，实际 rows={rows!r} bad={bad!r}"]

    # ① 布尔只回「读到了匹配行没有」，两种折叠都不许：
    #    · 那一行认不出来（少了 task_id）⇒ 不许说成「已销号」（那是另一种不可逆）；
    #    · 那一行本身读得出来（`bad_line`：坏的是别的行）⇒ 「读到就是读到」，仍是 True。
    want_retired = case == "bad_line"
    got_retired = env["cond"]._is_retired_task(owner)
    if got_retired is not want_retired:
        problems.append(f"[{case}] `_is_retired_task` 该是 {want_retired!r}，"
                        f"实际 {got_retired!r}（那一行认不出来 ⇒ 不许说成已销号；"
                        "那一行读得出来 ⇒ 读到就是读到）")

    # ② 读数必须自报「读不全」
    reading = dict(getattr(env["cond"], "last_retired_reading", {}) or {})
    if not reading:
        problems.append("这一格没有留下读数（判据读不到任何东西）")
    else:
        if reading.get("checked") is not False:
            problems.append(f"[{case}] 读不全 ⇒ 读数 checked 该是 False，实际 "
                            f"{reading.get('checked')!r}（{reading!r}）")
        if not (reading.get("bad") or _says_incomplete(reading.get("reason"))):
            problems.append(f"[{case}] 读不全 ⇒ 读数里要带着坏行或那一句理由，"
                            f"实际 bad={reading.get('bad')!r} reason={reading.get('reason')!r}")
        if not _says_incomplete(reading.get("reason")):
            problems.append(f"[{case}] 读数的 reason 要说明是「读不全」，不许空串："
                            f"{reading.get('reason')!r}")

    # ③ 回执里也要有一处读得出来（`why` 带那一句，或另立一个理由码）
    item = _blocked_item(env["cond"], owner, tag=f"w13-{case}")
    res = env["cond"].wake_blocked([item], approve="yes", dry_run=True)
    problems += [f"[{case}] {p}" for p in _shape_problems(res)]
    cell = _cell(res, item)
    if not (str(cell.get("refusal_code") or "") or _says_incomplete(cell.get("why"))):
        problems.append(f"[{case}] 回执要能读出「销号名单读不全」（否则读的人以为"
                        f"「它没销号」）：refusal_code={cell.get('refusal_code')!r} "
                        f"why={cell.get('why')!r}")
    return problems


def test_w13_an_unreadable_retired_list_says_so(tmp_path: pathlib.Path) -> None:
    """w13) 读不全必须自报：`checked=False` ＋ 理由，回执里也要有一处。

    两档盘上形态：销号行少了 `task_id` 那一格（今天 `bad=[]`、`checked=True`）、
    真行后面追加一行坏 JSON（这一档今天 `checked=False`，是 w13 的正控半边）。
    """
    problems = (_w13_problems(tmp_path, "missing_task_id")
                + _w13_problems(tmp_path, "bad_line"))
    assert problems == [], problems


# ====================================================================== w13b 负控
def test_w13b_an_empty_list_is_not_an_unreadable_one(tmp_path: pathlib.Path) -> None:
    """w13b) 负控：名单为空 ⇒ `checked=True`，而且照样叫得起来。

    没有这一条，「一律判读不全」也能让 w13 绿 —— 那会让每一条派活都叫不醒任何人。
    两档「为空」都要绿：文件不存在（还没人销过号）、文件在但零字节。
    """
    env = _workspace(tmp_path, "w13b")
    owner = _agent(env["cond"], str(env["boss"]), tag="live")
    item = _blocked_item(env["cond"], owner, tag="w13b")
    problems: list[str] = []

    path = _retired_file(env)
    if path.exists():
        problems.append(f"夹具自己没成立：这一档该是「文件不存在」，实际 {path} 在盘上")
    reading = env["cond"].retired_reading_of(owner)
    if reading.get("checked") is not True:
        problems.append(f"文件不存在 ⇒ checked 该是 True（查过了、没有），"
                        f"实际 {reading.get('checked')!r}（{reading.get('reason')!r}）")
    if reading.get("retired") is not False:
        problems.append(f"文件不存在 ⇒ retired 该是 False，实际 {reading.get('retired')!r}")

    # 空文件那一档：文件在、零字节
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")
    reading = env["cond"].retired_reading_of(owner)
    if reading.get("checked") is not True or reading.get("retired") is not False:
        problems.append(f"空文件 ⇒ checked/retired 该是 True/False，实际 "
                        f"{reading.get('checked')!r}/{reading.get('retired')!r}"
                        f"（{reading.get('reason')!r}）")
    path.unlink()

    # 动作侧：它必须真的叫得起来（这是 w13 / w14 的反真空）
    if env["cond"]._is_retired_task(owner) is not False:
        problems.append(f"没销号 ⇒ `_is_retired_task` 必须是 False，"
                        f"实际 {env['cond']._is_retired_task(owner)!r}")
    before = _tasks_bytes(env)
    res = env["cond"].wake_blocked([item], approve="yes", dry_run=False)
    problems += _shape_problems(res)
    cell = _cell(res, item)
    if cell.get("verdict") != "resume":
        problems.append(f"没销号、静默、板项未终态 ⇒ 该判 resume，实际 "
                        f"{cell.get('verdict')!r}（why={cell.get('why')!r}）")
    if res.get("state") != "woken" or int(res.get("count") or 0) != 1:
        problems.append(f"负控要真的叫起来：state={res.get('state')!r} "
                        f"count={res.get('count')!r}")
    if env["calls"] != [owner]:
        problems.append(f"负控里执行侧该被叫一次：calls={env['calls']}")
    if before == _tasks_bytes(env):
        problems.append("负控里 `tasks.json` 该被写（板项由 block 翻成 queued），实际逐字节没变")
    assert problems == [], problems


# ====================================================================== w14 动作
def _w14_problems(tmp_path: pathlib.Path, case: str) -> list[str]:
    """(w14) 的判据本体：读不全 ⇒ 不叫醒，且同一份夹具里没销号的号照样叫得起来。

    两档盘上形态的期望不同（差别正是这一条要守的那条线）：

    - `missing_task_id`：那一行认不出来 ⇒ 不知道它销过没有 ⇒ 不许叫（`review` /
      `unknown_retired`）。改前判 `resume` 并真的叫了人 —— 这就是先红的红点；
    - `bad_line`：坏的是别的行，这一行读得出来 ⇒ 结论仍是「已销号」（`skip` /
      `retired`，零字节零次叫醒）。它是回归半边：读不全不许把读得出来的那一行也作废。
    """
    env = _workspace(tmp_path, f"w14-{case}")
    retired = _retire_for_real(env)
    broken = str(retired["child"])
    problems: list[str] = []
    if not retired["ok"] or retired["data"].get("state") != "retired":
        return [f"夹具自己没成立：真销号没成（{retired['data'].get('state')!r}）"]
    if case == "missing_task_id":
        _drop_key_rewrite(env, "task_id")
    elif case == "bad_line":
        _append_broken_line(env)
    else:
        raise AssertionError(f"没有这种形态：{case!r}")
    want_verdict = "skip" if case == "bad_line" else "review"
    want_code = "retired" if case == "bad_line" else UNKNOWN_RETIRED

    # ① 叫不醒
    woke = env["cond"].wake_on_lifeline(broken)
    if woke.get("started") is not False:
        problems.append(f"[{case}] 销号名单读不全 ⇒ `wake_on_lifeline` 不许叫起来，"
                        f"实际 {woke!r}")
    if want_verdict == "review" and not _says_incomplete(woke.get("reason")):
        problems.append(f"[{case}] 叫不醒的理由要点名「读不全」：{woke.get('reason')!r}")
    if env["calls"]:
        problems.append(f"[{case}] `wake_on_lifeline` 已经叫了人：calls={env['calls']}")

    # ② 逐条审批：verdict 与理由码按上面那条线，零字节、零次叫醒
    item = _blocked_item(env["cond"], broken, tag=f"w14-{case}")
    before = _tasks_bytes(env)
    res = env["cond"].wake_blocked([item], approve="yes", dry_run=False)
    problems += [f"[{case}] {p}" for p in _shape_problems(res)]
    cell = _cell(res, item)
    if cell.get("verdict") != want_verdict:
        problems.append(f"[{case}] 该判 {want_verdict}，实际 "
                        f"{cell.get('verdict')!r}（why={cell.get('why')!r}）")
    if cell.get("refusal_code") != want_code:
        problems.append(f"[{case}] 理由码该是 {want_code}，实际 "
                        f"{cell.get('refusal_code')!r}")
    if cell.get("started") is not False:
        problems.append(f"[{case}] 这一档不许 started=True：{cell.get('started')!r}")
    if cell.get("mark"):
        problems.append(f"[{case}] 这一档不许落 wake: 痕：{cell.get('mark')!r}")
    if int(res.get("count") or 0) != 0:
        problems.append(f"[{case}] 一条都不许叫起来，count 该是 0，实际 {res.get('count')!r}")
    if env["calls"]:
        problems.append(f"[{case}] 一次都不许叫，calls={env['calls']}")
    if before != _tasks_bytes(env):
        problems.append(f"[{case}] 一个字节都不许写：`tasks.json` 前后不是逐字节一致")
    row = {str(r.get("task_id")): r for r in env["store"].rows("tasks")}.get(item) or {}
    if str(row.get("item_state")) != "block" or str(row.get("status")) != "block":
        problems.append(f"[{case}] 不许动板项：status={row.get('status')!r}、"
                        f"item_state={row.get('item_state')!r}")

    # ③ 反真空（同一份夹具）：另一条没销号的号走同一条路必须叫得起来
    live = _agent(env["cond"], str(env["boss"]), tag=f"live-{case}")
    live_item = _blocked_item(env["cond"], live, tag=f"w14-live-{case}")
    env["calls"].clear()
    live_res = env["cond"].wake_blocked([live_item], approve="yes", dry_run=False)
    live_cell = _cell(live_res, live_item)
    if live_cell.get("verdict") != "resume" or live_res.get("count") != 1:
        problems.append(f"[{case}] 反真空：没销号的号该判 resume 并真的叫起来，实际 "
                        f"{live_cell.get('verdict')!r}/count={live_res.get('count')!r}"
                        f"（why={live_cell.get('why')!r}）")
    if env["calls"] != [live]:
        problems.append(f"[{case}] 反真空：该叫的只有 {live}，实际 calls={env['calls']}")
    return problems


def test_w14_an_unreadable_retired_list_never_wakes(tmp_path: pathlib.Path) -> None:
    """w14) 读不全 ⇒ 不叫醒（方向：`draft/145` §三；业主裁定若取反，改的是这一条）。

    两档盘上形态各跑一遍，每一档都自带反真空：同一份夹具里另一个没销号的号必须
    照样叫得起来 —— 否则一个「一律不叫」的实现也能让这一条绿。两档的期望不同：
    那一行认不出来 ⇒ `review`／`unknown_retired`（今天红）；坏的是别的行 ⇒ 仍是
    `skip`／`retired`（今天绿，是回归半边：读不全不许把读得出来的那一行也作废）。
    """
    problems = (_w14_problems(tmp_path, "missing_task_id")
                + _w14_problems(tmp_path, "bad_line"))
    assert problems == [], problems

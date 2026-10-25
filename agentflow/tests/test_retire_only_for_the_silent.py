# -*- coding: utf-8 -*-
"""销号只给静默子代理（业主 2026-10-26 裁定）。

## 业主原话（唯一权威，逐字）

```
「销号可以也只可针对静默子代理」
```

静默的定义见同批裁定的上一句（`tests/test_three_states_flying_standby_silent.py` 的
模块头逐字抄着它）：无工作 ∧ 无任何计时器 ∧ 无活跃子代理；活跃 = 非静默；
不变量：有活跃子代理 ⇒ 必存在一条等待该子代理的计时器。

## 这一份钉住的七件事

| 判据 | 守的是 | 改前红在哪 |
|---|---|---|
| a) `test_a_a_silent_child_can_be_retired` | 静默子（无工作、无计时器、无活跃子）⇒ 可销（正控） | 改前读数里没有 `target_state` / `blocking` 这两格（`data` 里读到的是 KeyError），而"静默可销"这句话也没有任何机器读数守着 |
| b) `test_b_a_flying_child_is_refused_by_the_silent_gate` | 在飞的子 ⇒ 拒 `target_not_silent` ＋ 拒信说"它还在干活" | 改前只要能清板就销：活跃那一档是另一道闸说的话（`还在飞（status=running）⇒ 等它交差再销`），没有 `target_not_silent` 这个码，也不说"它还在干活（销号等于把它手上的活扔掉）" |
| c) `test_c_a_standby_child_is_refused_and_its_timers_are_listed` | 待机的子（done 但挂着 timer）⇒ 拒 ＋ 拒信逐条列出它挂的计时器（目的 ＋ 到点时刻） | 改前它会真的被销：活跃口径只看"自己在跑 / 下级在跑"，一条挂着的计时器在那条口径里一个字都没有（真机上的形态：交完差、钟还挂着，名字被销掉） |
| d) `test_d_an_unreadable_clock_is_refused_fail_closed` | 读不到时钟 ⇒ 拒（fail-closed），拒信写"读不到它是不是静默"（负控） | 改前时钟簿记根本不进销号门：坏掉的 `out/clock/state.json` 与"没有任何计时器"是同一件事 ⇒ 照销 |
| e) `test_e_a_parent_with_a_flying_child_is_refused_and_the_child_is_named` | 父有 1 个在飞的子 ⇒ 销父被拒，且点名是哪个子让它非静默（与级联深→浅一致，不许特批） | 改前拒信只报"这一支里还有 1 个节点在活跃"（子树活跃闸），没有 `target_not_silent`、也不说"它在等哪个子"；而"父因为等子才非静默"这条不变量没有任何判据钉着 |
| f) `test_f_stubbing_the_state_judgement_makes_b_c_d_red` | 反真空：把 `state` 判据打桩成恒 `silent` ⇒ b / c / d 必红 | 不适用（它守的是 b/c/d 不是真空的那几条） |
| g) `test_g_the_board_gate_still_speaks_first` | 既有闸不退化：板项未清 ⇒ 仍先报"板项没清"（两条闸都在，报最具体的那条） | 改前同一份夹具报的是"还在飞"（活跃闸先说话）—— 板项清单是父下一步真正要做的那件事，它被另一条闸挡在后面就等于没提醒 |

b / c / d 的判据本体各自只写一份（`_b_problems` / `_c_problems` / `_d_problems`），
反真空那一条调同一份判据：打桩之后它必须报出问题 —— 否则"打桩 ⇒ 必红"证明的是
打桩坏了，而不是判据真的在看那件事。

## 三态纪律在这一份里的落点

`unknown` 是第四档，不是静默的别名：销号门上它一律 fail-closed（读不到就不销）。
把"没查成"折成"静默"的代价在这里最具体 —— 销号是不可逆的，名字永久不复用（业主 B1）。

## 销号不等于停止

`conductor.stop` / 叫停是"让它此刻停下来"，销号是"它交完了、名字永久不复用"。
待机那一档的拒信必须写清"要么让那些计时器等的事先发生，要么显式让它停（停止≠销号）"：
父读到拒信后该做的是这两件事之一，而不是反复调销号。
"""

from __future__ import annotations

import json
import pathlib
from typing import Any

import pytest

from agentflow import clock as CLK
from agentflow.conductor import Conductor, LocalBackend, calling_as
from agentflow.secretary import Secretary, retired_path
from agentflow.store import Store
from agentflow.tools import conductor_tools as CT
from agentflow.tools.base import ToolRegistry

#: 父代理唯一的销号入口（`Secretary.retire` 是它下游的落实那一步）。
TOOL = "conductor.retire_child"

TS = "2026-01-01T00:00:00+00:00"


# ====================================================================== 夹具
def _workspace(tmp_path: pathlib.Path) -> dict[str, Any]:
    """一个工作区 ＋ 一个主控 ＋ 父那一趟的秘书（`roster_sink` 接上，与生产同一条取法）。"""
    root = tmp_path / "ws"
    store = Store(root)
    store.init()
    cond = Conductor(store, registry={}, backend=LocalBackend({}))
    sec = Secretary("M", root=root, store=store)
    # 生产里由 `AgentLoop._bind_roster_sink` 接上；这里显式接，是为了让"销号"与
    # "登记名册"落同一份名册文件（否则两条链各读一份名册，判据测的就不是生产形态）。
    cond.roster_sink = sec
    owner = str(cond.open_top_level_run("M", "夹具：销号只给静默"))
    return {"root": root, "store": store, "cond": cond, "sec": sec, "owner": owner}


def _child(cond: Conductor, parent: str, *, role: str = "D",
           status: str = "done") -> str:
    """造一个子代理的台账行（`kind` 空 = 代理行；`done` 带 outcome 与 ended_at）。"""
    row = {
        "role": role, "action": "write_report", "called_by": "M",
        "parent_task_id": parent, "depth": 2, "input_key": f"silent:{role}:{status}",
        "status": status,
        "outcome": ("ok" if status == "done" else None),
        "refusal_reason": None, "instance": "", "detail": "夹具子代理",
        "error": None, "started_at": TS,
        "ended_at": (TS if status in ("done", "cancelled") else None),
        "tokens": 0, "usd": 0.0, "artifacts": [], "inputs": [],
    }
    return cond._write_new_row(row, note="fixture:child")


def _register(env: dict[str, Any], owner: str, task_id: str, *,
              role: str = "D", brief: str = "写研究报告") -> str:
    """把它登记进 `owner` 那份名册（销号的正路指称是名册名，所以这一步是前提）。"""
    got = env["sec"].roster_add(owner=str(owner), role=role, task_id=task_id, brief=brief)
    assert got.get("problem") == "", got
    return str(got["name"])


def _timer(env: dict[str, Any], task_id: str, *, reason: str = "等实验结果",
           after_sec: float = 600.0, role: str = "D") -> Any:
    """给它起一条一次性计时器（"还会醒过来"的最直接证据）。"""
    return CLK.start_timer(str(env["root"]), reason=reason, after_sec=after_sec,
                           task_id=str(task_id), role=role)


def _call(env: dict[str, Any], **kwargs: Any) -> Any:
    """以"父这一趟"的身份调一次销号（`calling_as` 挂上台账号，生产里由 `_do_tool` 挂）。"""
    reg = ToolRegistry(name="retire-silent")
    CT.register(reg, store=env["store"], conductor=env["cond"])
    with calling_as(str(env["owner"]), "M"):
        return reg.call(TOOL, dict(kwargs), role="M")


def _retired_rows(root: Any, owner: str) -> list[dict]:
    """某个父的销号名单（一行 = 一次销号）。"""
    path = retired_path(str(root), str(owner))
    if not path.is_file():
        return []
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def _data_of(res: Any) -> dict[str, Any]:
    """工具回执的 `data`（工具自己失败时把错误写进 problems，不吞掉）。"""
    assert getattr(res, "ok", False), getattr(res, "error", res)
    return dict(res.data or {})


def _blocking_kinds(data: dict[str, Any]) -> list[str]:
    return [str(b.get("kind") or "") for b in (data.get("blocking") or [])]


def _blocking_text(data: dict[str, Any]) -> str:
    return "；".join(str(b.get("detail") or "") for b in (data.get("blocking") or []))


# ====================================================================== a) 静默可销
def _a_env(tmp_path: pathlib.Path) -> dict[str, Any]:
    env = _workspace(tmp_path)
    owner = str(env["owner"])
    silent = _child(env["cond"], owner, role="D", status="done")
    env["silent"] = {"task_id": silent, "name": _register(env, owner, silent)}
    return env


def _a_problems(env: dict[str, Any]) -> list[str]:
    """(a) 的判据本体：静默子 ⇒ 销得掉，且读数里写明它是静默、没有任何 blocking。"""
    ctx = dict(env["silent"])
    problems: list[str] = []
    res = _call(env, child_name=str(ctx["name"]))
    if not getattr(res, "ok", False):
        return [f"销号工具自己失败了：{getattr(res, 'error', res)}"]
    data = dict(res.data or {})
    if data.get("state") != "retired":
        problems.append(f"静默子该能销，实际 state={data.get('state')!r}：{data.get('reason')!r}")
    if data.get("retired") is not True:
        problems.append(f"销成了 retired 该是 True，实际 {data.get('retired')!r}")
    if data.get("target_state") != "silent":
        problems.append(f"读数里该写 target_state=silent，实际 {data.get('target_state')!r}")
    if data.get("blocking"):
        problems.append(f"静默子不该有任何 blocking，实际 {data.get('blocking')!r}")
    if data.get("refusal_code"):
        problems.append(f"销成了不该带拒信码，实际 {data.get('refusal_code')!r}")
    rows = _retired_rows(env["root"], str(env["owner"]))
    if [str(r.get("name") or "") for r in rows] != [str(ctx["name"])]:
        problems.append(f"销号名单该只有 {ctx['name']} 一行，实际 {rows}")
    if int(data.get("active_child_count") or 0) != 0:
        problems.append(f"静默子不是活跃子代理，销完之后 active_child_count "
                        f"该是 0，实际 {data.get('active_child_count')!r}")
    return problems


def test_a_a_silent_child_can_be_retired(tmp_path: pathlib.Path) -> None:
    """a) 静默子（无工作、无计时器、无活跃子）⇒ 可销（正控）。

    正控也要有改前红：它断言的 `target_state` / `blocking` / `refusal_code` 三格
    在改前的回执里根本不存在（读到的是 KeyError）—— 而"静默可销"这句话如果连
    读数都不给，父就没有任何办法把"可以销了"与"再等等"分开。
    """
    env = _a_env(tmp_path)
    problems = _a_problems(env)
    assert problems == [], problems


# ====================================================================== b) 在飞
def _b_env(tmp_path: pathlib.Path) -> dict[str, Any]:
    env = _workspace(tmp_path)
    owner = str(env["owner"])
    flying = _child(env["cond"], owner, role="E", status="running")
    env["flying"] = {"task_id": flying, "name": _register(env, owner, flying, role="E")}
    return env


def _b_problems(env: dict[str, Any]) -> list[str]:
    """(b) 的判据本体：在飞的子 ⇒ 拒 `target_not_silent` ＋ 拒信说"它还在干活"。"""
    ctx = dict(env["flying"])
    tid = str(ctx["task_id"])
    problems: list[str] = []
    res = _call(env, child_name=str(ctx["name"]))
    if not getattr(res, "ok", False):
        return [f"销号工具自己失败了：{getattr(res, 'error', res)}"]
    data = dict(res.data or {})
    if data.get("state") != "refused":
        problems.append(f"在飞的子 ⇒ 该受控拒绝，实际 state={data.get('state')!r}")
    if data.get("refusal_code") != "target_not_silent":
        problems.append(f"拒信码该是 target_not_silent，实际 {data.get('refusal_code')!r}")
    if data.get("target_state") != "flying":
        problems.append(f"目标该读成在飞（flying），实际 {data.get('target_state')!r}")
    if not (data.get("blocking") or []):
        problems.append("在飞这一档的 blocking 是空的（没说它卡在哪）")
    elif "working" not in _blocking_kinds(data):
        problems.append(f"在飞这一档的 blocking 该是 working，实际 {_blocking_kinds(data)}")
    reason = str(data.get("reason") or "")
    if "它还在干活" not in reason:
        problems.append(f"拒信没写「它还在干活」：{reason}")
    if "销号等于把它手上的活扔掉" not in reason:
        problems.append(f"拒信没说清销号会扔掉它手上的活：{reason}")
    if "先让它收工" not in reason:
        problems.append(f"拒信没给出下一步（先让它收工）：{reason}")
    if "销号 ≠ 停止" not in reason:
        problems.append(f"拒信没写清「销号 ≠ 停止」：{reason}")
    if data.get("retired") is not False or int(data.get("retired_count") or 0) != 0:
        problems.append(f"被拒绝时一项都不许销：retired={data.get('retired')!r} "
                        f"retired_count={data.get('retired_count')!r}")
    if _retired_rows(env["root"], str(env["owner"])):
        problems.append(f"被拒绝时销号名单里不许有行：{_retired_rows(env['root'], str(env['owner']))}")
    return problems


def test_b_a_flying_child_is_refused_by_the_silent_gate(tmp_path: pathlib.Path) -> None:
    """b) 在飞的子 ⇒ 拒 `target_not_silent` ＋ 拒信说"它还在干活"。

    改前红：改前的在飞那一档由子树活跃闸说话（`还在飞（status=running）⇒ 等它交差再销`），
    没有 `target_not_silent` 这个码，也不说"它还在干活（销号等于把它手上的活扔掉）"。
    只要能清板，改前这条判据仍然拿到一个 refused —— 但它拿不到"为什么不能销"的那句话。
    """
    env = _b_env(tmp_path)
    problems = _b_problems(env)
    assert problems == [], problems


# ====================================================================== c) 待机
def _c_env(tmp_path: pathlib.Path) -> dict[str, Any]:
    env = _workspace(tmp_path)
    owner = str(env["owner"])
    standby = _child(env["cond"], owner, role="F", status="done")
    name = _register(env, owner, standby, role="F")
    first = _timer(env, standby, reason="等 B 把稿子交上来", after_sec=3600.0, role="F")
    second = _timer(env, standby, reason="等外部检索回执", after_sec=7200.0, role="F")
    env["standby"] = {"task_id": standby, "name": name,
                      "timers": [str(first.timer_id), str(second.timer_id)],
                      "purposes": [str(first.purpose), str(second.purpose)],
                      "due": [str(first.due_at), str(second.due_at)]}
    return env


def _c_problems(env: dict[str, Any]) -> list[str]:
    """(c) 的判据本体：待机的子 ⇒ 拒，且拒信逐条列出它挂的计时器（目的 ＋ 到点时刻）。"""
    ctx = dict(env["standby"])
    tid = str(ctx["task_id"])
    problems: list[str] = []
    res = _call(env, child_name=str(ctx["name"]))
    if not getattr(res, "ok", False):
        return [f"销号工具自己失败了：{getattr(res, 'error', res)}"]
    data = dict(res.data or {})
    if data.get("state") != "refused":
        problems.append(f"待机的子 ⇒ 该受控拒绝，实际 state={data.get('state')!r}"
                        f"（销号名单：{_retired_rows(env['root'], str(env['owner']))}）")
    if data.get("refusal_code") != "target_not_silent":
        problems.append(f"拒信码该是 target_not_silent，实际 {data.get('refusal_code')!r}")
    if data.get("target_state") != "standby":
        problems.append(f"目标该读成待机（standby），实际 {data.get('target_state')!r}")
    kinds = _blocking_kinds(data)
    if kinds.count("waiting") != len(ctx["timers"]):
        problems.append(f"blocking 该逐条列出 {len(ctx['timers'])} 条计时器，实际 {kinds}")
    reason = str(data.get("reason") or "")
    for one in list(ctx["timers"]) + list(ctx["purposes"]) + list(ctx["due"]):
        if str(one) and str(one) not in reason:
            problems.append(f"拒信里没有逐条点名 {one!r}：{reason}")
    combined = reason + "；" + _blocking_text(data)
    for one in list(ctx["purposes"]) + list(ctx["due"]):
        if str(one) and str(one) not in combined:
            problems.append(f"拒信与 blocking 里都没有 {one!r}：{combined}")
    if "它还会醒过来" not in reason:
        problems.append(f"拒信没说清它还会醒过来：{reason}")
    if "停止≠销号" not in reason:
        problems.append(f"拒信没写清「停止≠销号」：{reason}")
    if data.get("retired") is not False or int(data.get("retired_count") or 0) != 0:
        problems.append(f"被拒绝时一项都不许销，实际 retired={data.get('retired')!r} "
                        f"retired_count={data.get('retired_count')!r}")
    if _retired_rows(env["root"], str(env["owner"])):
        problems.append("被拒绝时销号名单里不许有行")
    # 读数面：待机也算活跃（活跃 = 非静默），两个数与三态读数同源。
    before = dict((data.get("readings") or {}).get("child_counts_before") or {})
    states = dict(before.get("states") or {})
    if before.get("child_count") != 1:
        problems.append(f"子代理数该是 1，实际 {before.get('child_count')!r}")
    if before.get("active_child_count") != 1:
        problems.append(f"待机也算活跃 ⇒ 活跃子代理数该是 1，实际 "
                        f"{before.get('active_child_count')!r}")
    if int(states.get("standby") or 0) != 1:
        problems.append(f"三态读数里待机该是 1，实际 {states}")
    if int(states.get("flying") or 0) + int(states.get("standby") or 0) != \
            int(before.get("active_child_count") or 0):
        problems.append(f"active_child_count 与「在飞 ＋ 待机」对不上：{before}")
    return problems


def test_c_a_standby_child_is_refused_and_its_timers_are_listed(
        tmp_path: pathlib.Path) -> None:
    """c) 待机的子（done 但挂着 timer）⇒ 拒 ＋ 拒信逐条列出它挂的计时器。

    改前红：改前它会真的被销掉 —— 活跃口径只有"自己在跑 / 下级在跑"，时钟上挂着的
    计时器在那条口径里一个字都没有，于是"交完差、钟还挂着"与"静默"长得一模一样。
    """
    env = _c_env(tmp_path)
    problems = _c_problems(env)
    assert problems == [], problems


# ====================================================================== d) 读不到
def _d_env(tmp_path: pathlib.Path) -> dict[str, Any]:
    env = _workspace(tmp_path)
    owner = str(env["owner"])
    child = _child(env["cond"], owner, role="G", status="done")
    name = _register(env, owner, child, role="G")
    clock_dir = pathlib.Path(str(env["root"])) / "out" / "clock"
    clock_dir.mkdir(parents=True, exist_ok=True)
    (clock_dir / "state.json").write_text("{ 这不是 JSON", encoding="utf-8")
    CLK.reset_books()               # 让下一次读盘真的去读那份坏文件
    env["broken"] = {"task_id": child, "name": name}
    return env


def _d_problems(env: dict[str, Any]) -> list[str]:
    """(d) 的判据本体：读不到时钟 ⇒ 拒（fail-closed），拒信写"读不到它是不是静默"。"""
    ctx = dict(env["broken"])
    problems: list[str] = []
    res = _call(env, child_name=str(ctx["name"]))
    if not getattr(res, "ok", False):
        return [f"销号工具自己失败了：{getattr(res, 'error', res)}"]
    data = dict(res.data or {})
    if data.get("state") not in ("unknown", "refused"):
        problems.append(f"读不到时钟 ⇒ 该拒（unknown / refused），实际 {data.get('state')!r}"
                        f"（销号名单：{_retired_rows(env['root'], str(env['owner']))}）")
    if data.get("refusal_code") != "target_not_silent":
        problems.append(f"拒信码该是 target_not_silent，实际 {data.get('refusal_code')!r}")
    if data.get("target_state") != "unknown":
        problems.append(f"目标该读成未读到（unknown），实际 {data.get('target_state')!r}")
    if "unknown" not in _blocking_kinds(data):
        problems.append(f"blocking 该有一条 unknown，实际 {_blocking_kinds(data)}")
    reason = str(data.get("reason") or "")
    if "读不到它是不是静默" not in reason:
        problems.append(f"拒信没写「读不到它是不是静默」：{reason}")
    if "fail-closed" not in reason:
        problems.append(f"拒信没写明这一档是 fail-closed：{reason}")
    if data.get("retired") is not False or int(data.get("retired_count") or 0) != 0:
        problems.append("读不到时一项都不许销")
    if _retired_rows(env["root"], str(env["owner"])):
        problems.append(f"读不到时销号名单里不许有行：{_retired_rows(env['root'], str(env['owner']))}")
    return problems


def test_d_an_unreadable_clock_is_refused_fail_closed(tmp_path: pathlib.Path) -> None:
    """d) 读不到时钟 ⇒ 拒（fail-closed），拒信写"读不到它是不是静默"（负控）。

    改前红：时钟簿记根本不进销号门 —— 坏掉的 `out/clock/state.json` 与"没有任何计时器"
    是同一件事，于是这一笔在改前会照销。三态纪律：`unknown` 不是静默的别名。
    """
    env = _d_env(tmp_path)
    problems = _d_problems(env)
    assert problems == [], problems


# ====================================================================== e) 父有在飞子
def _e_env(tmp_path: pathlib.Path) -> dict[str, Any]:
    env = _workspace(tmp_path)
    owner = str(env["owner"])
    parent = _child(env["cond"], owner, role="D", status="done")
    child = _child(env["cond"], parent, role="F", status="running")
    parent_name = _register(env, owner, parent)
    child_name = _register(env, parent, child, role="F")
    env["pair"] = {"parent": parent, "parent_name": parent_name,
                   "child": child, "child_name": child_name}
    return env


def _e_problems(env: dict[str, Any]) -> list[str]:
    """(e) 的判据本体：父有 1 个在飞的子 ⇒ 销父被拒，且点名是哪个子让它非静默。"""
    ctx = dict(env["pair"])
    parent, child = str(ctx["parent"]), str(ctx["child"])
    problems: list[str] = []
    res = _call(env, child_name=str(ctx["parent_name"]))
    if not getattr(res, "ok", False):
        return [f"销号工具自己失败了：{getattr(res, 'error', res)}"]
    data = dict(res.data or {})
    if data.get("state") != "refused":
        problems.append(f"父有在飞的子 ⇒ 该受控拒绝，实际 {data.get('state')!r}")
    if data.get("refusal_code") != "target_not_silent":
        problems.append(f"拒信码该是 target_not_silent，实际 {data.get('refusal_code')!r}")
    if data.get("target_state") != "standby":
        problems.append(f"父在等子 ⇒ 它该读成待机（standby），实际 {data.get('target_state')!r}")
    blob = "；".join([str(data.get("reason") or ""), _blocking_text(data),
                      "；".join(str(x) for x in (data.get("missing") or []))])
    if child not in blob:
        problems.append(f"拒信没有点名那个让它非静默的子（{child}）：{blob}")
    if str(ctx["child_name"]) not in blob:
        problems.append(f"拒信没有点名那个子的名册名（{ctx['child_name']}）：{blob}")
    if "它在等子代理" not in blob and "它名下有" not in blob:
        problems.append(f"拒信没说清「它在等那个子」这件事：{blob}")
    if int(data.get("retired_count") or 0) != 0:
        problems.append(f"被拒绝时一项都不许销，实际 retired_count={data.get('retired_count')!r}")
    for who in (str(env["owner"]), parent):
        rows = _retired_rows(env["root"], who)
        if rows:
            problems.append(f"{who} 的销号名单不该有行：{rows}")
    return problems


def test_e_a_parent_with_a_flying_child_is_refused_and_the_child_is_named(
        tmp_path: pathlib.Path) -> None:
    """e) 父有 1 个在飞的子 ⇒ 销父被拒，且点名是哪个子让它非静默。

    业主同一批裁定给的那条不变量：有活跃子代理 ⇒ 必存在一条等待该子代理的计时器
    ⇒ 父非静默 ⇒ 父不许销 ⇒ 级联永远是"先子后父"（与既有深→浅一致，不许特批）。

    改前红：改前的拒信只报"这一支里还有 1 个节点在活跃"（子树活跃闸），没有
    `target_not_silent`，也不说"它在等哪个子"。
    """
    env = _e_env(tmp_path)
    problems = _e_problems(env)
    assert problems == [], problems


# ====================================================================== f) 反真空
def test_f_stubbing_the_state_judgement_makes_b_c_d_red(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """f) 反真空：把 `state` 判据打桩成恒 `silent` ⇒ b / c / d 必红。

    打桩点是 `Conductor.retire_state_of`（销号前置那一格的唯一读数）—— 让它永远回
    "静默、没有 blocking"。这不是"读不成"（那一档会得 unknown，见 d），而是
    "查过了、它是静默的"：于是 b/c/d 三条判据必须当场报出问题，否则它们证明的不是
    "这道闸在看三态"。
    """
    # 打桩点必须存在（打不到的话，下面那句"必红"就是在同义反复里自证）
    assert callable(Conductor.retire_state_of)
    real = Conductor.retire_state_of

    def always_silent(self, task_id, **kw):  # noqa: ANN001, ANN202 - 打桩
        return {"checked": True, "task_id": str(task_id), "state": "silent",
                "state_label": "静默", "status": "done", "role": "D", "silent": True,
                "blocking": [], "waiters": [], "waiting_for": [], "busy_roots": [],
                "deferred": False, "reason": ""}

    # 先证明三条判据在真读数上是安静的（否则下面的"必红"可能只是夹具坏了）
    b_env, c_env, d_env = (_b_env(tmp_path / "b"), _c_env(tmp_path / "c"),
                           _d_env(tmp_path / "d"))
    assert _b_problems(b_env) == [], _b_problems(b_env)
    assert _c_problems(c_env) == [], _c_problems(c_env)
    assert _d_problems(d_env) == [], _d_problems(d_env)

    monkeypatch.setattr(Conductor, "retire_state_of", always_silent)
    assert _b_problems(b_env), "把三态判据打桩成恒静默，b 却一声不吭（说明它没在看 state）"
    assert _c_problems(c_env), "把三态判据打桩成恒静默，c 却一声不吭"
    assert _d_problems(d_env), "把三态判据打桩成恒静默，d 却一声不吭"
    # 反真空的另一半：打桩之后 c 必须真的被销掉（那才是这道闸原本挡住的那一笔）
    assert _retired_rows(c_env["root"], str(c_env["owner"])), (
        "把三态判据打桩成恒静默，待机的子却没有被销 ⇒ 这条反真空证明不了 c 依赖 state")
    assert real is not None


# ====================================================================== g) 板项闸先说话
def test_g_the_board_gate_still_speaks_first(tmp_path: pathlib.Path) -> None:
    """g) 既有闸不退化：板项未清 ⇒ 仍先报"板项没清"（两条闸都在，报最具体的那条）。

    两半，缺一条都不算：
    1. 在飞的子 ＋ 一条没消的板项 ⇒ 拒信报的是板项（那份清单是父下一步真正要做的事），
       不是"还在飞" —— 改前红：改前活跃闸排在板项闸前面，报的是"还在飞"；
    2. 静默的子 ＋ 一条没消的板项 ⇒ 同一句"板项没清"（这一半改前就是绿的，它是
       "新闸没有把旧闸挤掉"的负控）。
    """
    env = _workspace(tmp_path)
    owner = str(env["owner"])
    flying = _child(env["cond"], owner, role="E", status="running")
    flying_name = _register(env, owner, flying, role="E")
    item = env["cond"].open_item(kind="notice", role="E", expects="ack", action="notice",
                                 summary="一条没消的通知", called_by="M",
                                 parent_task_id=flying, depth=3)
    res = _call(env, child_name=flying_name)
    assert getattr(res, "ok", False), getattr(res, "error", res)
    data = dict(res.data or {})
    assert data["state"] == "refused", data
    assert "未消的板项" in str(data.get("reason") or ""), data
    assert "task_board 没清" in str(data.get("reason") or ""), data
    assert [str(x.get("task_id") or "") for x in (data.get("open_items") or [])] == [item], data
    assert any(item in str(m) for m in (data.get("missing") or [])), data
    assert data.get("refusal_code") != "target_not_silent", (
        "板项闸先说话时不该报成 target_not_silent（两条闸都在，报最具体的那条）", data)
    assert _retired_rows(env["root"], owner) == [], "被拒绝时一行都不许写"

    # ---- 第二半：静默的子 ＋ 没消的板项 ⇒ 仍是板项那一句（旧闸没有被新闸挤掉）
    env2 = _workspace(tmp_path / "silent")
    owner2 = str(env2["owner"])
    quiet = _child(env2["cond"], owner2, role="D", status="done")
    quiet_name = _register(env2, owner2, quiet)
    item2 = env2["cond"].open_item(kind="notice", role="D", expects="ack", action="notice",
                                   summary="另一条没消的通知", called_by="M",
                                   parent_task_id=quiet, depth=3)
    again = _call(env2, child_name=quiet_name)
    assert getattr(again, "ok", False), getattr(again, "error", again)
    data2 = dict(again.data or {})
    assert data2["state"] == "refused", data2
    assert "未消的板项" in str(data2.get("reason") or ""), data2
    assert [str(x.get("task_id") or "") for x in (data2.get("open_items") or [])] == [item2], data2
    assert _retired_rows(env2["root"], owner2) == [], "被拒绝时一行都不许写"

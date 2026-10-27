# -*- coding: utf-8 -*-
"""销号与收工之前先查"这一支还有没有程序在跑"（G2；零模型钱）。

## 业主原话（唯一权威，逐字）

```
「重点完善子代理杀自己发出去的程序进程的工具（由于计时器监控着那些程序，我
  想实现起来不会太难），以及注销前检测的能力」
```

另一条背景（同一晚的真机读数）：机器上跑出十五个野 python 进程，CPU 快炸了；
那些是智能体起的"研究程序"，没人能停、也没人在销号前查过。

## 这一份钉住的八条

| 判据 | 守的是 | 改前红在哪（本机实测，见下节） |
|---|---|---|
| a) `test_a_a_running_program_stops_the_retire` | 子代理名下有一个在跑的程序 ⇒ `conductor.retire_child` 受控拒绝、拒信点名 program / pid / 已跑秒数、子树一个字节没落盘 | 归属清楚且计时器还 pending 的那一档：改前被静默闸拒，但拒信把程序读成"一条挂着到点时刻的计时器"（到点时刻读不到），没有 pid、没有秒数、不指路；归属清楚而计时器已收口、进程还在的那一档：改前它真的被销掉（state=retired） |
| b) `test_b_after_the_program_ends_the_retire_goes_through` | 程序退出之后再销 ⇒ 成功（正控：闸不误伤） | 不适用（正控） |
| c) `test_c_an_unreadable_program_reading_is_refused_fail_closed` | 读数读不成（`clock.programs` 抛）⇒ 拒（fail-closed），拒信写"没查成"、不许说"没有在跑的程序" | 改前没有任何一格读程序，于是"没查成"与"没有在跑的程序"是同一件事 |
| d) `test_d_the_final_gate_names_the_programs_still_running` | 收工（`final`）收口时名下（含子树）还有在跑的程序 ⇒ `_final_gate_reading` 的读数点名、`run.notes` 点名、不记 final | 改前 `retire_integrity` / `_final_gate_reading` 的键集合里根本没有 `programs`（实测），程序还在跑照样 complete=True |
| e) `test_e_the_ownerless_reading_names_the_two_anomalies` | 无主进程读数（M 的巡查用）："起了却没有计时器"与"计时器收口了但进程还在"两类 ⇒ `conductor.state` 的 `programs` 格点名；正常结束 ⇒ 不点名（正控） | 改前 `conductor.state` 没有 `programs` 这一格（读数无从读起） |
| f) `test_f_stubbing_the_program_reading_makes_a_and_d_red` | 反真空：把"查程序"那一步打桩成恒空 ⇒ a 与 d 必红 | 不适用（它守的是 a/d 不是真空的那几条） |
| g) `test_g_the_two_running_tiers_are_not_folded_together` | 两档都在跑而处置不同：有主的（`running`，叫它的父先停）与无主的（`unowned`，旧账没记归属、只能 M 处理）分开给；销号只被有主的那一台拦、拒信不许把无主的那一台算到目标头上 | 改前 `programs()` 只给一串计时器流水，没有任何一格按归属分开（探针读数：两种都只看到 `count=1 running=1`） |
| h) `test_h_an_attributed_program_makes_the_gate_bite` | 归属被填上之后这道闸必须真的咬住（造"带 task_id 的程序 + 尝试销号" ⇒ 拒 + 点名 pid / 秒数 + 指路一条）。归属还没填上（旧账）时同一台必须落在 `unowned` 那一档、不许被算成有主 | 改前没有任何闸读程序，两种归属形态都照销（探针第 2、3 条） |

## 改前的实测读数（探针 `agentflow/temp/probe_g2_before.py`，本次取证）

```
1) 程序计时器 pending、task_id=子   ⇒ state=refused（静默闸：待机）
   拒信原文（节选）：D1（t-000002）现在是待机：它挂着 1 条计时器
   （tm-000001（program）：等程序跑完：python（python -c print(1)），到点
   （没读到到点时刻）），它还会醒过来 —— … 销号只针对静默子代理
2) 程序计时器 pending、task_id 空   ⇒ state=retired（真的销掉了）
3) 计时器已收口（fired）、pid 还活着、task_id=子 ⇒ state=retired（真的销掉了）
4) 工作区里有一条无主程序在跑，销静默叶子 ⇒ state=retired
5) retire_integrity 的键集合里没有 programs（final 闸读不到程序）
```

第 2、3、4 条就是"名字销了、程序还在跑"的真身；第 1 条说明既有的那道闸看得见
计时器、看不见程序（它连"到点时刻"都读不到，因为程序计时器没有到点这一刻）。

## 为什么要起真进程，以及它们怎么收场

"pid 还活着"这件事只有真进程能证明，所以本文件的夹具会起 `python -c "time.sleep(N)"`。
纪律（业主同一晚的教训：十五个野进程）：每一个真进程都由 `_sleeper` 这个上下文管理器
持有，`finally` 里 `kill()` + `wait()`；任何一个用例抛异常也一样被杀。
`test_b` 是唯一一条会"让程序自己结束"的路：它显式收口计时器，不靠等。

## 三态纪律在这一份里的落点

`programs` 那一格有三档：读到（有主的 / 无主的 / 账与进程对不上的）、读到但一个
在跑的程序都没有、没读到。第三档不等于第二档：`checked=False` 时销号一律不许
（fail-closed，判据 c），而收工那一档只留痕不拦（程序那一格没有"一定在跑"的证据，
拦下去会让一台坏掉的时钟把整棵树永远关在收工门外 —— 但"没查成"必须写出来，判据 d
的另一半守着这句话）。
"""

from __future__ import annotations

import contextlib
import json
import pathlib
import re
import subprocess
import sys
import time
import types
from datetime import datetime, timedelta, timezone
from typing import Any, Iterator

import pytest

from agentflow import clock as CLK
from agentflow.agent_loop import AgentLoop
from agentflow.conductor import Conductor, LocalBackend, calling_as
from agentflow.conductor import programs_reading
from agentflow.secretary import Secretary, retired_path
from agentflow.store import Store
from agentflow.tools import conductor_tools as CT
from agentflow.tools.base import ToolRegistry

#: 父代理唯一的销号入口。
TOOL = "conductor.retire_child"

TS = "2026-01-01T00:00:00+00:00"


# ====================================================================== 夹具
@contextlib.contextmanager
def _sleeper(seconds: float = 30.0) -> Iterator[subprocess.Popen]:
    """一个真进程（只在用例执行期间活着；`finally` 里杀掉，绝不留到用例之外）。

    为什么不用 `time.sleep` 的进程池 / 后台线程：判据要的是"pid 还活着"这个
    盘外事实（`stopctl.alive` 读的就是它），替身给不出这个事实。
    """
    proc = subprocess.Popen([sys.executable, "-c",
                             f"import time; time.sleep({float(seconds)})"])
    try:
        yield proc
    finally:
        with contextlib.suppress(Exception):
            proc.kill()
        with contextlib.suppress(Exception):
            proc.wait(timeout=10)


def _workspace(tmp_path: pathlib.Path) -> dict[str, Any]:
    """一个工作区 ＋ 一个主控 ＋ 父那一趟的秘书（`roster_sink` 接上，与生产同一条取法）。"""
    root = tmp_path / "ws"
    store = Store(root)
    store.init()
    cond = Conductor(store, registry={}, backend=LocalBackend({}))
    sec = Secretary("M", root=root, store=store)
    cond.roster_sink = sec
    owner = str(cond.open_top_level_run("M", "夹具：销号前查程序"))
    return {"root": root, "store": store, "cond": cond, "sec": sec, "owner": owner}


def _child(cond: Conductor, parent: str, *, role: str = "D",
           status: str = "done") -> str:
    """造一个子代理的台账行（`kind` 空 = 代理行；`done` 带 outcome 与 ended_at）。"""
    return cond._write_new_row({
        "role": role, "action": "write_report", "called_by": "M",
        "parent_task_id": parent, "depth": 2,
        "input_key": f"g2:{role}:{status}:{parent}", "status": status,
        "outcome": ("ok" if status == "done" else None), "refusal_reason": None,
        "instance": "", "detail": "夹具子代理", "error": None, "started_at": TS,
        "ended_at": (TS if status == "done" else None),
        "tokens": 0, "usd": 0.0, "artifacts": [], "inputs": [],
    }, note="fixture:g2")


def _register(env: dict[str, Any], owner: str, task_id: str, *,
              role: str = "D", brief: str = "写研究报告") -> str:
    """把它登记进 `owner` 那份名册（销号的正路指称是名册名，所以这一步是前提）。"""
    got = env["sec"].roster_add(owner=str(owner), role=role, task_id=task_id, brief=brief)
    assert got.get("problem") == "", got
    return str(got["name"])


def _call(env: dict[str, Any], **kwargs: Any) -> Any:
    """以"父这一趟"的身份调一次销号（`calling_as` 挂上台账号，生产里由 `_do_tool` 挂）。"""
    reg = ToolRegistry(name="g2")
    CT.register(reg, store=env["store"], conductor=env["cond"])
    with calling_as(str(env["owner"]), "M"):
        return reg.call(TOOL, dict(kwargs), role="M")


def _data_of(res: Any) -> dict[str, Any]:
    assert getattr(res, "ok", False), getattr(res, "error", res)
    return dict(res.data or {})


def _retired_rows(root: Any, owner: str) -> list[dict]:
    """某个父的销号名单（一行 = 一次销号）。"""
    path = retired_path(str(root), str(owner))
    if not path.is_file():
        return []
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def _backdate(env: dict[str, Any], timer_id: str, seconds: float) -> None:
    """把这条程序计时器的登记时刻往前挪 —— 让"已跑 N 秒"是确定的读数，不靠等。"""
    bucket = CLK.book(str(env["root"]))
    timer = bucket.get(str(timer_id))
    assert timer is not None, timer_id
    past = datetime.now(timezone.utc) - timedelta(seconds=float(seconds))
    timer.created_at = past.isoformat()
    bucket.save()


def _running_program(env: dict[str, Any], *, task_id: str = "", pid: int | None = None,
                     age_sec: float = 0.0, program: str = "python") -> Any:
    """登记一条"还在跑"的程序计时器（`state=pending`，与 `start_program` 同一形状）。"""
    timer = CLK.start_program(str(env["root"]), program=program,
                              argv=[program, "-c", "print(1)"],
                              task_id=str(task_id or ""), role="D",
                              where="fixture:g2")
    if pid is not None:
        CLK.attach_program_pid(str(env["root"]), timer.timer_id, int(pid))
    if age_sec:
        _backdate(env, timer.timer_id, age_sec)
    return timer


def _closed_program(env: dict[str, Any], *, task_id: str, pid: int | None,
                    outcome: str = "timed_out", elapsed_sec: float = 1.5) -> Any:
    """登记并立刻收口一条程序计时器（账说它完了；进程活不活着是盘外事实）。"""
    timer = CLK.start_program(str(env["root"]), program="python",
                              argv=["python", "-c", "print(1)"],
                              task_id=str(task_id or ""), role="D",
                              where="fixture:g2-closed")
    if pid is not None:
        CLK.attach_program_pid(str(env["root"]), timer.timer_id, int(pid))
    CLK.finish_program(str(env["root"]), timer.timer_id, outcome=outcome,
                       elapsed_sec=elapsed_sec)
    return timer


def _gate(env: dict[str, Any]) -> AgentLoop:
    """一趟主控的循环对象：`_final_gate_reading` 是纯读，不需要真模型。"""
    loop = AgentLoop(role="M", session_root=env["root"], registry=None, seam=None,
                     conductor=env["cond"], store=env["store"], sid="g2",
                     auto_secretary=False)
    loop.my_task_id = str(env["owner"])
    loop.secretary = env["sec"]
    return loop


def _run_notes() -> Any:
    """`_final_gate_reading` 只往 `run.notes` 上写（其余格子它不读）。"""
    return types.SimpleNamespace(notes=[])


def _child_retired(env: dict[str, Any], owner: str) -> bool:
    rows, _bad = env["sec"].roster_rows(str(owner))
    return any(bool(r.get("retired")) for r in rows)


# ====================================================================== a) 受控拒绝
def _a_env(tmp_path: pathlib.Path, proc: subprocess.Popen) -> dict[str, Any]:
    """子代理静默，但名下有一条还在跑的程序（归属清楚：`task_id` 就是它）。"""
    env = _workspace(tmp_path)
    owner = str(env["owner"])
    kid = _child(env["cond"], owner)
    env["kid"] = kid
    env["kid_name"] = _register(env, owner, kid)
    env["timer"] = _running_program(env, task_id=kid, pid=proc.pid, age_sec=42.0)
    env["pid"] = int(proc.pid)
    return env


def _a_problems(env: dict[str, Any]) -> list[str]:
    """(a) 判据本体：拒 + 点名 program/pid/秒数 + 只指一条正路 + 一个字节没落盘。"""
    problems: list[str] = []
    data = _data_of(_call(env, child_name=str(env["kid_name"])))
    if data.get("state") != "refused":
        return [f"子代理名下还有程序在跑 ⇒ 该受控拒绝，实际 state={data.get('state')!r}："
                f"{str(data.get('reason') or '')[:300]}"]
    if data.get("retired") is not False or int(data.get("retired_count") or 0) != 0:
        problems.append(f"被拒绝时一项都不许销：retired={data.get('retired')!r} "
                        f"retired_count={data.get('retired_count')!r}")
    reason = str(data.get("reason") or "")
    if "个程序在跑" not in reason:
        problems.append(f"拒信没点名「还有几个程序在跑」：{reason}")
    if "python" not in reason:
        problems.append(f"拒信没点名是哪台程序：{reason}")
    if f"pid {env['pid']}" not in reason:
        problems.append(f"拒信没点名 pid（{env['pid']}）：{reason}")
    if not re.search(r"已跑 (4[0-9]|5[0-9]) 秒", reason):
        problems.append(f"拒信没给「已跑 N 秒」这个读数：{reason}")
    if "program.stop" not in reason:
        problems.append(f"拒信没指路到 program.stop：{reason}")
    if reason.count("program.stop") != 1:
        problems.append(f"拒信把同一条正路指了 {reason.count('program.stop')} 遍"
                        "（只许一次）：" + reason)
    if "等它们自己结束" not in reason:
        problems.append(f"拒信没给另一条也会发生的路（等它自己结束）：{reason}")
    if "没有在跑的程序" in reason:
        problems.append(f"拒信说成了「没有在跑的程序」：{reason}")
    if data.get("refusal_code"):
        problems.append(f"程序闸那一档不该带 refusal_code（拦它的不是静默闸）："
                        f"{data.get('refusal_code')!r}")
    kinds = [str(b.get("kind") or "") for b in (data.get("blocking") or [])]
    if "working" not in kinds:
        problems.append(f"blocking 里该有一条 working（程序还在跑），实际 {kinds}")
    blob = "；".join([reason] + [str(b.get("detail") or "")
                                for b in (data.get("blocking") or [])]
                    + [str(x) for x in (data.get("missing") or [])])
    if str(env["timer"].timer_id) not in blob and "python" not in blob:
        problems.append(f"拒信与 blocking / missing 里都没有那台程序：{blob}")
    # 一个字节都不许落盘：销号名单、名册的 retired 位、台账那一行都没动
    rows = _retired_rows(env["root"], str(env["owner"]))
    if rows:
        problems.append(f"被拒绝时销号名单里不许有行：{[r.get('name') for r in rows]}")
    if _child_retired(env, str(env["owner"])):
        problems.append("被拒绝时名册里那一项的 retired 位不许变真")
    row = next(r for r in env["store"].rows("tasks")
               if str(r.get("task_id") or "") == str(env["kid"]))
    if str(row.get("status") or "") != "done":
        problems.append(f"被拒绝时台账那一行不许被改写：status={row.get('status')!r}")
    return problems


def test_a_a_running_program_stops_the_retire(tmp_path: pathlib.Path) -> None:
    """a) 子代理名下有一个在跑的程序 ⇒ 受控拒绝，拒信点名 program+pid+已跑秒数。

    两半，都是"归属清楚"的那一档（`task_id` 就是那个子代理）：

    1. 计时器还 `pending`（账上说在跑）：改前被静默闸拒，但拒信写的是
       "它挂着 1 条计时器（…（program）…到点（没读到到点时刻））" —— 没有 pid、
       没有秒数、不指路，父照着那句话处置不了一台程序；
    2. 计时器已收口、pid 还活着：改前它真的被销掉（state=retired），
       名字永久不复用，而进程还在跑。
    """
    with _sleeper() as proc:
        env = _a_env(tmp_path / "pending", proc)
        problems = _a_problems(env)

    with _sleeper() as proc:
        env2 = _workspace(tmp_path / "closed")
        owner2 = str(env2["owner"])
        kid2 = _child(env2["cond"], owner2)
        env2["kid"] = kid2
        env2["kid_name"] = _register(env2, owner2, kid2)
        env2["timer"] = _closed_program(env2, task_id=kid2, pid=proc.pid)
        env2["pid"] = int(proc.pid)
        data2 = _data_of(_call(env2, child_name=str(env2["kid_name"])))
        if data2.get("state") != "refused":
            problems.append(
                "账上说收口了而进程还在 ⇒ 该受控拒绝，实际 "
                f"state={data2.get('state')!r}（销号名单："
                f"{[r.get('name') for r in _retired_rows(env2['root'], owner2)]}）")
        reason2 = str(data2.get("reason") or "")
        if f"pid {env2['pid']}" not in reason2:
            problems.append(f"第二半的拒信没点名 pid：{reason2}")
        if "账上说它已经收口了" not in reason2:
            problems.append(f"第二半的拒信没写「账说收口了、进程还在」这句实话：{reason2}")
        if _retired_rows(env2["root"], owner2):
            problems.append("第二半被拒时销号名单里不许有行")
    assert problems == [], problems


# ====================================================================== b) 正控
def test_b_after_the_program_ends_the_retire_goes_through(
        tmp_path: pathlib.Path) -> None:
    """b) 把那台程序停掉（进程退出 ＋ 计时器收口）之后再销 ⇒ 成功。

    这一条守的是"闸不许误伤"：同一条夹具、同一台程序，只把"它还在跑"这一个事实
    变掉，销号就必须放行。程序怎么结束的并不重要（`outcome=killed` 是父杀掉它、
    `exited` 是它自己跑完），重要的是账上收口了、而且进程真的没了。
    """
    with _sleeper() as proc:
        env = _a_env(tmp_path, proc)
        # 先证一遍闸真的在响（否则下面"放行"证明不了任何事）
        assert _a_problems(env) == [], _a_problems(env)
        pid = int(proc.pid)
        proc.kill()
        proc.wait(timeout=10)
        time.sleep(0.2)                       # 让 OS 真的回收那个 pid
        timer = env["timer"]
        got, res = CLK.finish_program(str(env["root"]), timer.timer_id,
                                      outcome="killed", exit_code=None,
                                      elapsed_sec=42.0)
        assert res == "fired", res
        reading = programs_reading(str(env["root"]))
        assert reading.get("checked") is True, reading
        assert [r for r in reading["running"]] == [], reading["running"]
        alive = [r for r in reading["rows"]
                 if str(r.get("timer_id") or "") == str(timer.timer_id)]
        assert alive and alive[0].get("live") is False, alive
        data = _data_of(_call(env, child_name=str(env["kid_name"])))
        assert data.get("state") == "retired", data
        assert int(data.get("retired_count") or 0) == 1, data
        assert [r.get("name") for r in _retired_rows(env["root"], str(env["owner"]))] == \
            [str(env["kid_name"])], data
        assert pid > 0


# ====================================================================== c) 读不成
def test_c_an_unreadable_program_reading_is_refused_fail_closed(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """c) 读数读不成（`clock.programs` 抛）⇒ 拒（fail-closed），拒信说"没查成"。

    三态纪律：把"没查成"折成"没有在跑的程序"是这一闸最贵的一次折叠 —— 销号不可逆
    （名字永久不复用，业主 B1），而"我不知道"与"我查过、没有"在处置上正好相反。
    """
    env = _workspace(tmp_path)
    owner = str(env["owner"])
    kid = _child(env["cond"], owner)
    name = _register(env, owner, kid)

    def boom(workspace: Any) -> dict[str, Any]:
        raise RuntimeError("时钟簿记坏了（打桩）")

    monkeypatch.setattr(CLK, "programs", boom)
    res = _call(env, child_name=name)
    data = _data_of(res)
    problems: list[str] = []
    if data.get("state") not in ("unknown", "refused"):
        problems.append(f"读不成 ⇒ 该拒，实际 state={data.get('state')!r}")
    if data.get("checked") is not False:
        problems.append(f"读不成时 checked 该是 False，实际 {data.get('checked')!r}")
    reason = str(data.get("reason") or "")
    if "没查成" not in reason and "没读成" not in reason:
        problems.append(f"拒信没写「没查成」：{reason}")
    if "没有在跑的程序" in reason:
        problems.append(f"拒信把「没查成」折成了「没有在跑的程序」：{reason}")
    if data.get("retired") is not False or int(data.get("retired_count") or 0) != 0:
        problems.append("读不成时一项都不许销")
    if _retired_rows(env["root"], owner):
        problems.append("读不成时销号名单里不许有行")
    assert problems == [], problems


# ====================================================================== d) 收工门
def _d_env(tmp_path: pathlib.Path, proc: subprocess.Popen) -> dict[str, Any]:
    """名册已清干净（子代理已经销号），而它名下还有一台程序在跑。

    为什么这么造：这是"名字销了、程序还在"的真身（也是 `final` 唯一挡不住的那一档
    —— 名册项已经 retired，`complete` 为真）。它以"改前的世界"起手：先销号、再起程序。
    """
    env = _workspace(tmp_path)
    owner = str(env["owner"])
    kid = _child(env["cond"], owner)
    kid_name = _register(env, owner, kid)
    data = _data_of(_call(env, child_name=kid_name))
    assert data.get("state") == "retired", data
    env["kid"] = kid
    env["timer"] = _running_program(env, task_id=kid, pid=proc.pid, age_sec=7.0)
    env["pid"] = int(proc.pid)
    return env


def _d_problems(env: dict[str, Any]) -> list[str]:
    """(d) 判据本体：收工读数点名、run.notes 点名、这一趟不记 final。"""
    problems: list[str] = []
    loop = _gate(env)
    run = _run_notes()
    reading = dict(loop._final_gate_reading(run))
    if reading.get("applicable") is not True:
        problems.append(f"主控 M 名下这一道闸该 applicable，实际 {reading.get('applicable')!r}")
    progs = dict(reading.get("programs") or {})
    if not progs:
        return ["收工读数里没有 programs 这一格（程序还在跑，读数却读不到它）"]
    if progs.get("checked") is not True:
        problems.append(f"程序读数该读成，实际 checked={progs.get('checked')!r}："
                        f"{progs.get('reason')!r}")
    running = [dict(r) for r in (progs.get("running") or ())]
    if len(running) != 1:
        problems.append(f"这一支该点名 1 个在跑的程序，实际 {[r.get('program') for r in running]}")
    elif int(running[0].get("pid") or 0) != env["pid"]:
        problems.append(f"点名的那一台程序 pid 不对：{running[0].get('pid')!r} != {env['pid']}")
    if reading.get("programs_ok") is not False:
        problems.append(f"还有程序在跑 ⇒ programs_ok 该是 False，实际 "
                        f"{reading.get('programs_ok')!r}")
    if reading.get("complete") is not False:
        problems.append(f"还有程序在跑 ⇒ 这一趟不该记 final（complete 该是 False），实际 "
                        f"{reading.get('complete')!r}")
    why = str(reading.get("why") or "")
    if "program.stop" not in why:
        problems.append(f"收工拒信没指路到 program.stop：{why}")
    if f"pid {env['pid']}" not in why:
        problems.append(f"收工拒信没点名 pid：{why}")
    notes = " ".join(str(n) for n in run.notes)
    if "个程序在跑" not in notes:
        problems.append(f"run.notes 没点名「还有几个程序在跑」：{list(run.notes)}")
    if f"pid {env['pid']}" not in notes:
        problems.append(f"run.notes 没点名 pid：{list(run.notes)}")
    return problems


def test_d_the_final_gate_names_the_programs_still_running(
        tmp_path: pathlib.Path) -> None:
    """d) 收工收口时有在跑的程序 ⇒ 读数点名 + run.notes 点名 + 不记 final。

    改前红（实测）：`retire_integrity` 与 `_final_gate_reading` 的键集合里都没有
    `programs`（`['checked','clock','complete','count','dirty','nodes','reason',
    'root','root_open_items','stalled','stalled_count','states','total']`），而
    `complete` 是 True —— 名册清干净了，程序还在跑，这一趟照样记 final。
    """
    with _sleeper() as proc:
        env = _d_env(tmp_path, proc)
        problems = _d_problems(env)
    # 正控：同一条夹具、不跑到程序那一步 ⇒ 放行，且 why 是空串
    clean = _workspace(tmp_path / "clean")
    owner = str(clean["owner"])
    leaf = _child(clean["cond"], owner)
    leaf_name = _register(clean, owner, leaf)
    assert _data_of(_call(clean, child_name=leaf_name)).get("state") == "retired"
    loop = _gate(clean)
    run_clean = _run_notes()
    ok_reading = dict(loop._final_gate_reading(run_clean))
    if ok_reading.get("complete") is not True:
        problems.append(f"没有程序在跑时收工该放行，实际 {ok_reading.get('complete')!r}："
                        f"{str(ok_reading.get('why') or '')[:200]}")
    if ok_reading.get("programs_ok") is not True:
        problems.append(f"没有程序在跑时 programs_ok 该是 True，实际 "
                        f"{ok_reading.get('programs_ok')!r}")
    if str(ok_reading.get("why") or ""):
        problems.append(f"放行时 why 该是空串，实际 {ok_reading.get('why')!r}")
    if any("程序" in str(n) for n in run_clean.notes):
        problems.append(f"没有程序在跑时不许往 run.notes 里写程序读数：{list(run_clean.notes)}")
    assert problems == [], problems


# ====================================================================== e) 无主进程读数
def test_e_the_ownerless_reading_names_the_two_anomalies(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """e) 无主进程读数：两类异常点名、正常结束不点名（正控）。

    业主第 ③ 条点名的两类：
    - "起了却没有对应计时器"（`orphans.no_timer`：`program_span` 登记失败时留下的读数）；
    - "计时器已收口但进程还在"（`orphans.finished_but_alive`）。

    正控那一半同样重要：正常结束（进程真的退了、账也收口了）不许被点名 ——
    否则这张异常清单会天天响，M 的巡查就再也不看它了。
    """
    problems: list[str] = []
    env = _workspace(tmp_path / "closed-alive")
    owner = str(env["owner"])
    kid = _child(env["cond"], owner)
    _register(env, owner, kid)
    with _sleeper() as proc:
        timer = _closed_program(env, task_id=kid, pid=proc.pid)
        got = programs_reading(str(env["root"]))
        if got.get("checked") is not True:
            problems.append(f"读数该读成：{got.get('reason')!r}")
        listed = [dict(r) for r in ((got.get("orphans") or {}).get("finished_but_alive")
                                   or ())]
        if not any(str(r.get("timer_id") or "") == str(timer.timer_id) for r in listed):
            problems.append(f"账说收口了而进程还在 ⇒ 该在 finished_but_alive 里点名，"
                            f"实际 {[r.get('timer_id') for r in listed]}")
        if int(got.get("orphan_count") or 0) < 1:
            problems.append(f"orphan_count 该 >= 1，实际 {got.get('orphan_count')!r}")
        named = [str(r.get("pid")) for r in listed]
        if str(proc.pid) not in named:
            problems.append(f"点名里没有那个 pid（{proc.pid}）：{named}")
        # 三类归属：有主的进 running（不在 unowned 里）
        if any(str(r.get("timer_id") or "") == str(timer.timer_id)
               for r in (got.get("unowned") or ())):
            problems.append("有主的程序不该出现在 unowned 里")

    # ---- 正控：正常结束（进程已退、账已收口）⇒ 两类异常都不点名
    env2 = _workspace(tmp_path / "normal-exit")
    owner2 = str(env2["owner"])
    kid2 = _child(env2["cond"], owner2)
    _register(env2, owner2, kid2)
    with _sleeper() as proc2:
        pid2 = int(proc2.pid)
        timer2 = _closed_program(env2, task_id=kid2, pid=pid2, outcome="exited",
                                 elapsed_sec=0.3)
        proc2.kill()
        proc2.wait(timeout=10)
        time.sleep(0.2)
        clean = programs_reading(str(env2["root"]))
        alive = [r for r in (clean.get("orphans") or {}).get("finished_but_alive") or ()
                 if str(r.get("timer_id") or "") == str(timer2.timer_id)]
        if alive:
            problems.append(f"正常结束的程序不许进 finished_but_alive：{alive}")
        if int(clean.get("orphan_count") or 0) != 0:
            problems.append(f"正常结束时 orphan_count 该是 0，实际 {clean.get('orphan_count')!r}")
        if int(clean.get("running_count") or 0) != 0:
            problems.append(f"正常结束时 running_count 该是 0，实际 "
                            f"{clean.get('running_count')!r}")
        if pid2 <= 0:
            problems.append("夹具的 pid 没读到")

    # ---- "起了却没有计时器"：登记那一步失败 ⇒ 留一条 unbooked 读数（进程照跑，账上没有）
    #
    # 打桩点是 `clock.start_program`（`ProgramSpan.open` 唯一调的那一处）：它一抛，
    # `program_span` 就按既有口径走 `_note_unbooked` 那条路 —— 这正是真机上
    # "起了进程却没进账"的形态（`ProgramSpan` 的 docstring 写着"登记失败不拦程序运行，
    # 但必须留下 problem 与一条读数"）。
    def boom(**kwargs: Any) -> Any:
        raise RuntimeError("登记那一步坏了（打桩）")

    CLK.reset_programs()
    real_start = CLK.start_program
    monkeypatch.setattr(CLK, "start_program", boom)
    try:
        with CLK.program_span(program="python", argv=["python", "-c", "print(1)"],
                              workspace=str(env["root"])) as span:
            if not str(span.problem or ""):
                problems.append("登记失败时 program_span 该留下 problem（读数是没登记）")
        unbooked = programs_reading(str(env["root"]))
        listed = [dict(r) for r in ((unbooked.get("orphans") or {}).get("no_timer") or ())]
        if not any(str(r.get("program") or "") == "python" for r in listed):
            problems.append(f"起了却没有计时器 ⇒ 该在 no_timer 里点名，实际 {listed}")
        if int(unbooked.get("orphan_count") or 0) < 1:
            problems.append(f"no_timer 那一档 orphan_count 该 >= 1，实际 "
                            f"{unbooked.get('orphan_count')!r}")
        # M 的巡查面：`conductor.state` 的 programs 格读得到同一份读数
        reg = ToolRegistry(name="g2-state")
        CT.register(reg, store=env["store"], conductor=env["cond"])
        with calling_as(str(env["owner"]), "M"):
            state = _data_of(reg.call("conductor.state", {}, role="M"))
        grid = dict(state.get("programs") or {})
        if not grid:
            problems.append("conductor.state 里没有 programs 这一格（M 的巡查读不到）")
        else:
            for key in ("checked", "running", "unowned", "orphans", "no_timer",
                        "finished_but_alive", "named"):
                if key not in grid:
                    problems.append(f"conductor.state.programs 缺 {key!r}：{sorted(grid)}")
            if int(grid.get("orphans") or 0) < 1:
                problems.append(f"conductor.state 的 programs.orphans 该 >= 1，实际 "
                                f"{grid.get('orphans')!r}")
            if not any("python" in str(x) for x in (grid.get("named") or ())):
                problems.append(f"conductor.state 的 programs.named 没点名那台程序："
                                f"{grid.get('named')!r}")
    finally:
        monkeypatch.setattr(CLK, "start_program", real_start)
        CLK.reset_programs()
    assert problems == [], problems


# ====================================================================== f) 反真空
def _stub_programs_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    """把"查程序那一步"打桩成"查过了、一个都没有"。

    打桩点必须存在（打不到的话，下面那句"必红"就是在同义反复里自证）。
    """
    assert callable(Conductor.programs_in_subtree)
    real = Conductor.programs_in_subtree

    def empty(self, root_task_id: str, **kw: Any) -> dict[str, Any]:
        got = real(self, root_task_id, **kw)
        return dict(got, checked=True, running=[], running_count=0,
                    unowned=[], unowned_count=0, orphan_count=0,
                    orphans={"no_timer": [], "finished_but_alive": []}, reason="")

    monkeypatch.setattr(Conductor, "programs_in_subtree", empty)


def test_f_stubbing_the_program_reading_makes_a_and_d_red(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """f) 反真空：把"查程序"打桩成恒空 ⇒ (a) 与 (d) 必红。

    没有这一条，(a) 只能证明"现在会拒"，证明不了"这一拒就是那道程序读数在起作用"；
    (d) 同理只能证明"现在拦"，证明不了拦它的是程序那一格。
    """
    # 先证明两条判据在真读数上是安静的（否则下面的"必红"可能只是夹具坏了）
    with _sleeper() as proc:
        assert _a_problems(_a_env(tmp_path / "a0", proc)) == []
    with _sleeper() as proc0:
        assert _d_problems(_d_env(tmp_path / "d0", proc0)) == []

    _stub_programs_empty(monkeypatch)
    with _sleeper() as proc:
        red_a = _a_problems(_a_env(tmp_path / "a1", proc))
    assert red_a, "把程序读数打桩成恒空，(a) 却一声不吭（说明它没在读程序）"
    assert any("refused" in p or "销" in p or "程序在跑" in p for p in red_a), red_a
    with _sleeper() as proc2:
        red_d = _d_problems(_d_env(tmp_path / "d1", proc2))
    assert red_d, "把程序读数打桩成恒空，(d) 却一声不吭"
    assert any("programs" in p or "complete" in p for p in red_d), red_d


# ====================================================================== g) 两档不许折
def test_g_the_two_running_tiers_are_not_folded_together(
        tmp_path: pathlib.Path) -> None:
    """g) 有主的在跑 与 无主的在跑 是两档：读数分开、处置分开、拒信不冤枉。

    两档都在跑，但处置不同（业主 2026-10-27 追裁：别把两档折成一档）：
    - 有主的（`task_id` 落在这一支里）⇒ 它的父能叫住它（先停、或等它退出），
      所以它是销号门上该拦的那一台；
    - 无主的（旧账没记归属）⇒ 没有任何一支认领它，只有 M 能处置 —— 它是读数。
    折成一档的后果很具体：父读到"还有 1 个程序在跑"，照着"先停它"去操作，而那一台
    根本不在它名下（停不了），真正该停的那一台反而没被点名。
    """
    problems: list[str] = []
    with _sleeper() as owned_proc, _sleeper() as loose_proc:
        env = _workspace(tmp_path)
        owner = str(env["owner"])
        kid = _child(env["cond"], owner)
        kid_name = _register(env, owner, kid)
        owned = _running_program(env, task_id=kid, pid=owned_proc.pid, age_sec=12.0)
        loose = _running_program(env, task_id="", pid=loose_proc.pid, age_sec=99.0)
        reading = programs_reading(str(env["root"]))
        if reading.get("checked") is not True:
            return [f"读数没读成：{reading.get('reason')!r}"]
        if int(reading.get("running_count") or 0) != 1:
            problems.append(f"有主的在跑该是 1 台，实际 {reading.get('running_count')!r}"
                            f"（{[(r.get('timer_id'), r.get('owner')) for r in reading['running']]}）")
        if int(reading.get("unowned_count") or 0) != 1:
            problems.append(f"无主的在跑该是 1 台，实际 {reading.get('unowned_count')!r}")
        owned_ids = [str(r.get("timer_id") or "") for r in (reading.get("running") or ())]
        loose_ids = [str(r.get("timer_id") or "") for r in (reading.get("unowned") or ())]
        if owned_ids != [str(owned.timer_id)]:
            problems.append(f"running 该只有有主的那一台（{owned.timer_id}），实际 {owned_ids}")
        if loose_ids != [str(loose.timer_id)]:
            problems.append(f"unowned 该只有无主的那一台（{loose.timer_id}），实际 {loose_ids}")
        if any(str(r.get("owner") or "") for r in (reading.get("unowned") or ())):
            problems.append("unowned 里的行不该带台账号（带了就说明它不是无主的）")

        # 销号：只被有主的那一台拦，拒信不许把无主的那一台算到目标头上
        data = _data_of(_call(env, child_name=kid_name))
        if data.get("state") != "refused":
            problems.append(f"有主的程序还在跑 ⇒ 该拒，实际 {data.get('state')!r}")
        reason = str(data.get("reason") or "")
        if f"pid {int(owned_proc.pid)}" not in reason:
            problems.append(f"拒信没点名有主的那一台（pid {owned_proc.pid}）：{reason}")
        if f"pid {int(loose_proc.pid)}" in reason:
            problems.append(f"拒信把无主的那一台算到了目标头上（pid {loose_proc.pid}）：{reason}")
        if "还有 1 个程序在跑" not in reason:
            problems.append(f"拒信该只数有主的那 1 台：{reason}")

        # M 的巡查面：两档各自点名，处置路径也各写一句
        reg = ToolRegistry(name="g2-tiers")
        CT.register(reg, store=env["store"], conductor=env["cond"])
        with calling_as(str(env["owner"]), "M"):
            grid = dict((_data_of(reg.call("conductor.state", {}, role="M"))
                         .get("programs") or {}))
        if int(grid.get("running") or 0) != 1 or int(grid.get("unowned") or 0) != 1:
            problems.append(f"conductor.state 的两档计数该是 1 / 1，实际 "
                            f"running={grid.get('running')!r} unowned={grid.get('unowned')!r}")
        if not any(f"pid {int(owned_proc.pid)}" in str(x)
                   for x in (grid.get("owned_named") or ())):
            problems.append(f"owned_named 没点名有主的那一台：{grid.get('owned_named')!r}")
        if not any(f"pid {int(loose_proc.pid)}" in str(x)
                   for x in (grid.get("unowned_named") or ())):
            problems.append(f"unowned_named 没点名无主的那一台：{grid.get('unowned_named')!r}")
        handling = dict(grid.get("handling") or {})
        for key in ("running", "unowned", "orphans"):
            if key not in handling:
                problems.append(f"handling 缺 {key!r} 这一档的处置路径：{sorted(handling)}")
    assert problems == [], problems


# ====================================================================== h) 归属填上之后
def test_h_an_attributed_program_makes_the_gate_bite(
        tmp_path: pathlib.Path) -> None:
    """h) 归属被填上之后这道闸必须真的咬住；还没填上时它是无主那一档、不许算成有主。

    归属的写口归 G1（`clock.start_program` 在调用方不给 `task_id` 时从台账号现取）。
    本判据对两种仓库状态都给出真断言，所以哪一天落地都不真空：

    - 已经填上（`start_program` 把 `calling_as(子)` 的编号写进了那一条计时器）⇒
      销号必须拒，且点名 pid / 已跑秒数 / 一条正路（这就是"闸真的咬住"的机器形态）；
    - 还没填上（今天的形态）⇒ 同一台程序必须落在 `unowned` 那一档（旧账没记归属），
      并且不许出现在 `running` 里 —— 有主/无主两档都不许折。
    """
    problems: list[str] = []
    with _sleeper() as proc:
        env = _workspace(tmp_path)
        owner = str(env["owner"])
        kid = _child(env["cond"], owner)
        kid_name = _register(env, owner, kid)
        # 起程序的那一刻，这一趟的台账号就是那个子代理（G1 的兜底要读的就是它）
        with calling_as(kid, "D"):
            timer = _running_program(env, task_id="", pid=proc.pid, age_sec=42.0)
        attributed = str(timer.task_id or "")
        reading = programs_reading(str(env["root"]))
        if not reading.get("checked"):
            return [f"读数没读成：{reading.get('reason')!r}"]
        if attributed:
            if attributed != kid:
                problems.append(f"归属填错了：该是 {kid}，实际 {attributed!r}")
            running = [str(r.get("timer_id") or "") for r in (reading.get("running") or ())]
            if running != [str(timer.timer_id)]:
                problems.append(f"归属填上之后该进 running 那一档，实际 {running}")
            if any(str(r.get("timer_id") or "") == str(timer.timer_id)
                   for r in (reading.get("unowned") or ())):
                problems.append("归属填上了，同一台却还在 unowned 里（两档折了）")
            data = _data_of(_call(env, child_name=kid_name))
            if data.get("state") != "refused":
                problems.append(f"归属填上之后销号必须拒，实际 {data.get('state')!r}")
            reason = str(data.get("reason") or "")
            if f"pid {int(proc.pid)}" not in reason:
                problems.append(f"拒信没点名 pid：{reason}")
            if not re.search(r"已跑 4[0-9] 秒", reason):
                problems.append(f"拒信没给已跑秒数：{reason}")
            if reason.count("program.stop") != 1:
                problems.append(f"拒信只许指一条正路一次：{reason}")
        else:
            # 今天这一档（G1 还没落地）：它必须是无主的，且不许被算成有主
            unowned = [str(r.get("timer_id") or "") for r in (reading.get("unowned") or ())]
            running = [str(r.get("timer_id") or "") for r in (reading.get("running") or ())]
            if str(timer.timer_id) not in unowned:
                problems.append(f"没有归属的程序该进 unowned 那一档，实际 unowned={unowned}"
                                f" running={running}")
            if str(timer.timer_id) in running:
                problems.append("没有归属的程序被算成了有主（两档折了）")
    assert problems == [], problems

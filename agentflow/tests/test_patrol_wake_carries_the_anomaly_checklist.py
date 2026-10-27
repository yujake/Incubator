# -*- coding: utf-8 -*-
"""判据：M 的周期性巡查报醒必须带「异常清单 + 干预指引」（业主 2026-10-26）。

## 业主原话（唯一权威）

```
「这个是M定期巡查需要特别注意的异常行为，M可通过发送指导意见干预」
```

## 这个文件修的是什么

改前「巡查时间到」那句话只有三样：目的 / 间隔 / 第几次：

    巡查时间到：周期性巡查｜每 20 分钟一次（第 1 次）

于是 M 被叫醒了，却没人告诉它"这一拍要看什么"。真机 `projects/mp3-r3` 的读数把代价写得很直白：
B1（`t-000006`）81 分钟只走了 4 步、`status` 一直是 running，而 M 的报醒里一个字都没提到它。

现在同一条报醒后面另起一句，带当拍现算的四类异常（每类给条数 + 点名绝对编号）：

    ① 停滞子：`status=running` 而超过 N 分钟没有新步（点名 + `stalled_sec`）
    ② 静默未销号的子：无工作、无计时器、无活跃子，却还留在册上（给销号指路）
    ③ 未消板项：`item_state != done` 的条数，按 expect 分 ack / work
    ④ 被拦的结项原因：最近一次 `final_refused` / 板项闸的拒信首句

四类都空 => 逐字写「本轮无异常」（不许不写：不写就分不清"没有"与"没查"）。
有异常子 => 末尾给一句可执行的干预指引，点名那个子的绝对编号。

## 五条判据与改前红在哪

| 判据 | 守的是 | 改前红在哪 |
|---|---|---|
| a) `test_a_the_wake_carries_all_four_categories` | 四类各一句、每句有"条数"；四类都空时逐字"本轮无异常" | 改前 `patrol_anomalies` / `patrol_text` 都不存在（AttributeError），报醒只有三样 |
| b) `test_b_a_stalled_child_is_named_with_stalled_sec` | 停滞子点名绝对编号 + `stalled_sec` | 同上：没有任何一类，更谈不上点名 |
| c) `test_c_a_silent_child_is_named_with_a_retire_pointer` | 静默未销号的子点名 + "要销号它吗" / `retire_child` | 同上 |
| d) `test_d_the_guidance_names_the_child_and_never_appears_when_clean` | 有异常子 => "可发指导意见" + 绝对编号；无异常 => 不许出现这句 | 同上（正控与负控都读不到那一句） |
| e) `test_e_stubbing_the_checklist_turns_a_and_b_red` | 反真空：把"异常清单"那一步打桩成返回空 => a 与 b 必红 | 不适用（它守的是 a / b 不是真空的那几条） |

e 调的是 a / b 各自的判据函数（`_a_problems` / `_b_problems`）：打桩之后它们必须报出问题，
否则"打桩 => 必红"证明的是打桩坏了，而不是判据真的在看那件事。

## 三条纪律在本文件里的落点

- 停滞那一格：本文件的夹具给的是"最近一步在 30 分钟前 + `status=running`"（业主在施工单里
  点名的那一形）。判据本体归另一条 lane 的 `stalled` / `stalled_sec`；它落地后由
  `clock_tools.set_stalled_probe` 在装配期接进来，本文件不用改（报醒文本一个字都不变）。
- 静默那一格：取 `Conductor.retire_integrity` 的 `nodes` 里 `state == "silent"` 的那些 ——
  三态判定仍然只由 `conductor.agent_state` 一处算，本文件不写第二份。
- 未消板项：取 `Conductor.open_items_by_parent`（`open_items_of(tid)` 就是它按父取的那一格）。

## 反真空（另两条）

- 夹具里真的有一条停滞子、一条静默子、两条未消板项、一条 `final_refused`：否则 a / b / c
  是在空集上成立；
- 干净那一档真的没有任何异常（只有 M 自己、没有子、没有板项、没有会话）：否则 d 的负控
  会因为它什么时候都不出现而"通过"。
"""

from __future__ import annotations

import pathlib

import pytest

from agentflow import clock as C
from agentflow import schema as S
from agentflow import sessions as SS
from agentflow.conductor import Conductor, LocalBackend, calling_as, stamp_step
from agentflow.secretary import Secretary
from agentflow.store import Store
from agentflow.tools import ToolRegistry
from agentflow.tools import clock_tools as CT

TS = "2026-01-01T00:00:00+00:00"

#: 停滞那一格的当前时刻（钉死它，`stalled_sec` 才是确定的 1800）。
#: 判据本体在 `conductor.agent_state`：它按 `out/steps/<台账号>.json` 的 `at` 与
#: `STALLED_AFTER_SEC` 算，而"现在"取的是 `schema.now_iso()` —— 钉住这一个就钉住了那一格。
STALL_NOW = "2026-01-01T00:20:00+00:00"
#: 停滞子的最近一步（比 `STALL_NOW` 早 30 分钟 => `stalled_sec=1800`）。
STALL_STEP_AT = "2025-12-31T23:50:00+00:00"

#: 四类在报醒里的逐字开头（判据按它认出"这一类查过了"）。
CATEGORY_HEADS: tuple[str, ...] = ("① 停滞子 条数", "② 静默未销号的子 条数",
                                   "③ 未消板项 条数", "④ 被拦的结项原因 条数")


# ====================================================================== 夹具


def _env(tmp_path: pathlib.Path) -> dict[str, object]:
    """一个工作区 + M 那一趟 + 装配好的 `clock.*` 工具面（假时钟从 `TS` 起步）。"""
    root = tmp_path / "ws"
    root.mkdir(parents=True, exist_ok=True)
    store = Store(root)
    store.init()
    cond = Conductor(store, registry={}, backend=LocalBackend({}))
    sec = Secretary("M", root=root, store=store)
    cond.roster_sink = sec
    owner = str(cond.open_top_level_run("M", "夹具：周期性巡查的异常清单"))
    C.reset()
    fake = C.FakeClock(wall=TS, monotonic=1000.0)
    C.use(fake)
    reg = ToolRegistry(name="patrol-checklist")
    reg.bound_role = S.CONDUCTOR_ROLE
    CT.register(reg, store=store, root=root, conductor=cond)
    return {"root": root, "store": store, "cond": cond, "sec": sec,
            "owner": owner, "reg": reg, "fake": fake}


def _child(env: dict[str, object], *, role: str = "D", status: str = "running",
           started_at: str = TS, detail: str = "夹具子代理") -> str:
    """造一个子代理的台账行（`running` 不带 `ended_at`，终态必须带）。"""
    row = {
        "role": role, "action": "write_report", "called_by": "M",
        "parent_task_id": str(env["owner"]), "depth": 2,
        "input_key": f"巡查夹具:{role}:{status}:{started_at}",
        "status": status,
        "outcome": ("ok" if status == "done" else None),
        "refusal_reason": None, "instance": "",
        "detail": detail, "error": None, "started_at": started_at,
        "ended_at": (started_at if status in ("done", "cancelled") else None),
        "tokens": 0, "usd": 0.0, "artifacts": [], "inputs": [],
    }
    return str(env["cond"]._write_new_row(row, note="fixture:child"))


def _item(env: dict[str, object], *, expects: str, kind: str = "notice") -> str:
    """在 M 名下开一条未消的板项（`expects` 两档各一条时 ③ 才能读出 ack / work）。"""
    return str(env["cond"].open_item(
        kind=kind, role=S.CONDUCTOR_ROLE, expects=expects, parent_task_id=str(env["owner"]),
        depth=1, summary=f"巡查夹具：{kind}/{expects}", input_key=f"巡查:{kind}:{expects}"))


def _stall(env: dict[str, object], child_id: str, *, step: int = 4) -> str:
    """把这个子代理的"最近一步"落在 30 分钟前（停滞判据从那里读，本文件不自己判）。

    判据与它的输入都在别处：`conductor.stamp_step` 写 `out/steps/<台账号>.json`，
    `conductor.step_beats` 按 `STALLED_AFTER_SEC` 判"这一步是不是已经太久"。
    本文件只负责造出那一格的事实。
    """
    _path, problem = stamp_step(str(env["root"]), task_id=child_id, role="B",
                                step=step, at=STALL_STEP_AT)
    assert problem == "", problem
    return child_id


def _record_refusal(env: dict[str, object], why: str) -> None:
    """落一条 `final_refused` 的会话事件（④ 读的就是它）。"""
    _path, problem = SS.append(pathlib.Path(str(env["root"])), {
        "kind": "agent_step", "role": S.CONDUCTOR_ROLE, "index": 1, "shape": "final",
        "payload": {"final": "我做完了"},
        "result": {"final_refused": {"root": str(env["owner"]), "why": why}},
    }, sid="patrol-fixture")
    assert problem == "", problem


def _fire(env: dict[str, object], *, every_sec: float = 1200.0) -> str:
    """起一条 `periodic_start(purpose="周期性巡查")` 并让它到点，返回那条报醒的原文。"""
    reg = env["reg"]
    with calling_as(str(env["owner"]), S.CONDUCTOR_ROLE):
        started = reg.call("clock.periodic_start", every_sec=every_sec,
                           purpose="周期性巡查")
    assert started.ok is True, started.error
    with calling_as(str(env["owner"]), S.CONDUCTOR_ROLE):
        env["fake"].advance(every_sec)
    details = [str(r.get("detail") or "") for r in env["store"].rows("tasks")
               if str(r.get("kind") or "") == "notice"
               and str(r.get("detail") or "").startswith("巡查时间到：")]
    assert details, "巡查到点没有落任何 notice 项（到点动作没跑）"
    return details[-1]


def _segment(text: str, index: int) -> str:
    """报醒文本里第 `index` 类那一段（① 是 0）：判据要按类断言，不许在全文里撞运气。"""
    heads = ["①", "②", "③", "④", "。干预指引", "。处置指路"]
    start = text.find(heads[index])
    if start < 0:
        return ""
    ends = [text.find(h, start + 1) for h in heads[index + 1:]]
    ends = [e for e in ends if e > 0]
    return text[start:min(ends)] if ends else text[start:]


# ====================================================================== 判据本体


def _a_problems(text: str) -> list[str]:
    """a：四类各一句、每句有"条数"；四类都空时逐字"本轮无异常"。"""
    problems = [f"报醒里没有这一类：{head}" for head in CATEGORY_HEADS if head not in text]
    if "本轮无异常" in text:
        body = text.split("本轮无异常")[0]
        for head in CATEGORY_HEADS:
            if head not in body:
                problems.append(f"写了「本轮无异常」却缺这一类：{head}")
    return problems


def _b_problems(text: str, child_id: str, stalled_sec: int) -> list[str]:
    """b：停滞子点名绝对编号 + `stalled_sec`。"""
    segment = _segment(text, 0)
    problems: list[str] = []
    if child_id not in segment:
        problems.append(f"① 停滞子那一段没点名 {child_id}：{segment!r}")
    if f"stalled_sec={stalled_sec}" not in segment:
        problems.append(f"① 停滞子那一段没有 stalled_sec={stalled_sec}：{segment!r}")
    return problems


def _c_problems(text: str, child_id: str) -> list[str]:
    """c：静默未销号的子点名 + "要销号它吗" / `retire_child` 指路。"""
    segment = _segment(text, 1)
    problems: list[str] = []
    if child_id not in segment:
        problems.append(f"② 静默未销号的子那一段没点名 {child_id}：{segment!r}")
    if "要销号它吗" not in segment and "retire_child" not in segment:
        problems.append(f"② 那一段没有销号指路（要销号它吗 / retire_child）：{segment!r}")
    return problems


def _d_problems(text: str, child_id: str, *, expect_guidance: bool) -> list[str]:
    """d：有异常子 => "可发指导意见" + 那个子的绝对编号；无异常 => 不许出现这句。"""
    has = "可发指导意见" in text
    if not expect_guidance:
        return ["无异常的那一拍竟然带了「可发指导意见」"] if has else []
    problems: list[str] = []
    if not has:
        problems.append("有异常子却没有「可发指导意见」那一句")
    tail = text.split("可发指导意见", 1)[1] if has else ""
    if child_id not in tail:
        problems.append(f"干预指引里没点名 {child_id}")
    return problems


# ====================================================================== a


def test_a_the_wake_carries_all_four_categories(tmp_path) -> None:
    """a：到点那条报醒含四类清单；四类都空时逐字"本轮无异常"。"""
    env = _env(tmp_path)
    text = _fire(env)
    assert not _a_problems(text), text
    # 这一档是真的干净：没有子、没有板项、没有会话记录 => 逐字写"本轮无异常"。
    assert "本轮无异常" in text, text
    # 正控：三样（目的 / 间隔 / 第几次）一个字都没丢。
    assert text.startswith("巡查时间到：周期性巡查｜每 20 分钟一次（第 1 次）"), text


def test_a2_the_four_categories_are_all_reported_when_dirty(tmp_path, monkeypatch) -> None:
    """a 的另一半：有异常时四类仍各一句（不是只报查到的那几类）。"""
    monkeypatch.setattr(S, "now_iso", lambda: STALL_NOW)
    env = _env(tmp_path)
    _stall(env, _child(env, role="D", status="running"))
    _child(env, role="E", status="done")
    _item(env, expects="ack")
    _item(env, expects="work", kind="report")
    _record_refusal(env, "还没销号：t-000001 名下整棵树还有 2/2 个代理在册")
    text = _fire(env)
    assert not _a_problems(text), text
    assert "本轮无异常" not in text, text


# ====================================================================== b


def test_b_a_stalled_child_is_named_with_stalled_sec(tmp_path, monkeypatch) -> None:
    """b：停滞子（最近一步在 30 分钟前 + status=running）点名绝对编号 + `stalled_sec`。"""
    monkeypatch.setattr(S, "now_iso", lambda: STALL_NOW)
    env = _env(tmp_path)
    child_id = _stall(env, _child(env, role="B", status="running",
                                  detail="八十多分钟只走四步"))
    text = _fire(env)
    assert not _b_problems(text, child_id, 1800), text
    # 负控：同一个子若是 `done`，① 里不许出现它（停滞是"还在跑而没动"，不是"跑完了"）。
    env2 = _env(tmp_path / "done")
    quiet_id = _stall(env2, _child(env2, role="B", status="done"))
    text2 = _fire(env2)
    assert quiet_id not in _segment(text2, 0), text2


def test_b2_a_child_with_recent_steps_is_not_stalled(tmp_path, monkeypatch) -> None:
    """b 的负控：`status=running` 但最近一步就在刚刚 => 不许算成停滞。"""
    monkeypatch.setattr(S, "now_iso", lambda: STALL_NOW)
    env = _env(tmp_path)
    child_id = _child(env, role="D", status="running")
    _path, problem = stamp_step(str(env["root"]), task_id=child_id, role="D", step=9,
                                at=STALL_NOW)
    assert problem == "", problem
    text = _fire(env)
    assert child_id not in _segment(text, 0), text
    assert "① 停滞子 条数 0" in text, text


# ====================================================================== c


def test_c_a_silent_child_is_named_with_a_retire_pointer(tmp_path) -> None:
    """c：静默未销号的子点名 + "要销号它吗" / `retire_child` 指路。"""
    env = _env(tmp_path)
    child_id = _child(env, role="E", status="done", detail="收工了但还在册")
    text = _fire(env)
    assert not _c_problems(text, child_id), text


# ====================================================================== d


def test_d_the_guidance_names_the_child_and_never_appears_when_clean(tmp_path) -> None:
    """d：有异常子 => "可发指导意见" + 绝对编号；无异常 => 不许出现这句（正控）。"""
    dirty = _env(tmp_path / "dirty")
    child_id = _child(dirty, role="D", status="done")
    text = _fire(dirty)
    assert not _d_problems(text, child_id, expect_guidance=True), text

    clean = _env(tmp_path / "clean")
    clean_text = _fire(clean)
    assert not _d_problems(clean_text, child_id, expect_guidance=False), clean_text


def test_d2_the_guidance_is_a_reading_requirement(tmp_path) -> None:
    """d 的后半句：把"发过之后它的下一步应该变"写成读数要求（不是一句空话）。"""
    env = _env(tmp_path)
    _child(env, role="D", status="done")
    text = _fire(env)
    guide = text.split("可发指导意见", 1)[1]
    for must in ("发过之后", "下一步", "步号", "status"):
        assert must in guide, f"干预指引里缺 {must} 这一处读数要求：{guide!r}"


# ====================================================================== e（反真空）


def test_e_stubbing_the_checklist_turns_a_and_b_red(tmp_path, monkeypatch) -> None:
    """e：把"异常清单"那一步打桩成返回空 => a 与 b 必红（且不许写"本轮无异常"）。"""
    monkeypatch.setattr(S, "now_iso", lambda: STALL_NOW)
    normal = _env(tmp_path / "normal")
    child_id = _stall(normal, _child(normal, role="B", status="running"))
    good = _fire(normal)
    assert not _a_problems(good) and not _b_problems(good, child_id, 1800), good

    stubbed = _env(tmp_path / "stubbed")
    stub_child = _stall(stubbed, _child(stubbed, role="B", status="running"))
    monkeypatch.setattr(C, "patrol_anomalies", lambda *a, **k: {})
    red = _fire(stubbed)
    assert _a_problems(red), f"打桩成空之后 a 仍然通过：{red!r}"
    assert _b_problems(red, stub_child, 1800), f"打桩成空之后 b 仍然通过：{red!r}"
    assert "本轮无异常" not in red, f"打桩成空之后不许报「本轮无异常」：{red!r}"
    assert "异常清单没查成" in red, red


# ====================================================================== 起表读数


def test_f_periodic_start_shows_what_the_wake_will_carry(tmp_path) -> None:
    """起表那一刻就让 M 看见"到点会收到什么"（`patrol_checklist` 读数）。"""
    env = _env(tmp_path)
    child_id = _child(env, role="D", status="done")
    with calling_as(str(env["owner"]), S.CONDUCTOR_ROLE):
        started = env["reg"].call("clock.periodic_start", every_sec=1200,
                                  purpose="周期性巡查")
    assert started.ok is True, started.error
    got = started.data["patrol_checklist"]
    assert got["checked"] is True, got
    assert got["counts"]["silent"]["count"] == 1, got
    assert f"{child_id}（D，无工作、无计时器、无活跃子，却还留在册上" in got["wake_sample"], got
    # 三态：读口没接上时这一格必须如实说没查成（不许折成"四类都是 0"）。
    C.set_patrol_probe(None)
    try:
        bare = C.patrol_anomalies(env["root"], task_id=str(env["owner"]))
        bare_text = C.patrol_section(env["root"], task_id=str(env["owner"]))
    finally:
        C.set_patrol_probe(CT._patrol_probe)
    assert bare["checked"] is False and bare["reason"], bare
    assert bare_text.startswith("异常清单没查成"), bare_text
    assert "本轮无异常" not in bare_text, bare_text

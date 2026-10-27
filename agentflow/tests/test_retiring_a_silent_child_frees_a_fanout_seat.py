# -*- coding: utf-8 -*-
"""触顶的拒信要能照着做：销号静默子代理 ⇒ 名额立刻回来（业主 2026-10-26）。

## 业主原话（唯一权威，逐字）

```
「如果一个父代理想派子代理触发到扇出上限12，则报错信息要提醒它可通过销号
  静默子代理腾出名额（你也要确实保证这个机制跑得通）」
```

## 这一份钉住的五件事

| 判据 | 守的是 | 改前红在哪 |
|---|---|---|
| a) `test_a_the_refusal_names_the_tool_the_precondition_and_the_seats` | 触顶拒信里四样齐全：上限现算（测试档 3，不是 12）、`conductor.retire_child` 与它的参数、静默前提（在飞/待机/读不到 ⇒ `target_not_silent`）、当前占位读数（几格 + 谁已静默可销） | 改前的报文只说"先等已派出去的那些回来"，一个字的销号都没有；测试档 cap=3 时它也没有"现算"的痕迹 |
| b) `test_b_retiring_a_silent_child_frees_the_seat_at_once` | 端到端：挂满 ⇒ 拒；销号一个静默子 ⇒ 同一父的下一次 `summon` 当场成功 | 改前销号只写名册三份 jsonl、台账那一行动都不动 ⇒ 占位数不变 ⇒ 下一次仍然 `fanout_exceeded`（这一条在改前是红的，见 e 的反真空） |
| c) `test_c_retiring_a_flying_child_refuses_and_keeps_the_seat` | 反向：销号在飞的子 ⇒ 拒 `target_not_silent`，名额不变（不许"拒了但名额少了"） | 改前销号门没有静默闸（2026-10-26 才加）；而"拒了之后名额有没有变"这一条改前没有判据 |
| d) `test_d_the_seat_count_and_the_ledgers_do_not_drift` | 占位数与台账、名册两处口径不分家；"静默"在第一处读数（`fanout_seats_of`）与第二处读数（`handoffs_reading` 的 `silent`）是同一个答案 | 改前"父已记为静默"（交差账）与销号门读的三态各说各的：一份交过差的子代理在销号门上是"在飞"，而去销又会被拒 |
| e) `test_e_stubbing_the_settle_makes_b_red` | 反真空：把"销号后落定台账 / 重算占位"打桩成不落定 ⇒ b 必红 | 不适用（它守的是 b 不是真空的那一条） |

## 为什么"销号腾名额"必须靠一笔台账写

扇出名额的分子是"父名下 `status ∈ {pending, running}` 的直接子"
（`Conductor._in_flight_children_of`，业主 2026-10-08 的单时刻口径：子代理一返回就腾位）。
销号改前落在名册 / 对照表 / 销号名单三份 jsonl 上，台账那一行一个字节都不动 ——
于是"销号一个静默子代理腾出名额"这句话在盘上是空话：占位数不变，下一次 `summon`
照旧 `fanout_exceeded`。b 之所以在改前是红的，根子就在这条缝上：两个口径（名额看台账、
销号写名册）根本没有接上。修法见 `Secretary.settle_retired_row`（销号先落台账终态，
再写名册；先台账后名册的顺序是判据本身）。

## "静默子代理占着名额"这一档是真实存在的

一个子代理交差（`clock.record_handoff`，业主 2026-10-27 第四条：「父代理把它记为
静默子代理」）之后，那一趟循环就收工了；而它的台账行由派活的父那一侧落终态。
异步 / 可抢占派活、或上一次收尾没走完时，中间会留下"已交差、行还是 `running`"的那一格。
它正是本功能的唯一对象：已经静默、却还占着一格。夹具用生产里同一个写盘口
（`CLK.record_handoff`）造这一格，不手写"看起来像交差"的假字段。

口径因此只有一处：`handoff_index`（交差账的唯一读口）⇒ `agent_state` 第 ⑥ 步
（交差 ⇒ 不再算"自己在跑"）⇒ `activity_snapshot` 的 `active` ⇒ 销号门的静默闸 ⇒
`fanout_seats_of` 的 `retirable`。五处读的是同一份事实。
"""

from __future__ import annotations

import pathlib
from typing import Any

from agentflow import clock as CLK
from agentflow import policy as P
from agentflow.agent_d import AgentD
from agentflow.agent_e import AgentE
from agentflow.conductor import Conductor, calling_as
from agentflow.secretary import Secretary
from agentflow.store import Store
from agentflow.tools import conductor_tools as CT
from agentflow.tools.base import ToolRegistry

#: 父代理唯一的销号入口（工具名 = 拒信里点名的那一个）。
TOOL = "conductor.retire_child"

#: 扇出上限的测试档：刻意不是 12 / 25 / 100 —— 报文里的上限必须是现算出来的那个数。
CAP = 3

TS = "2026-01-01T00:00:00+00:00"


# ====================================================================== 测试替身
class FakeD(AgentD):
    """D 的替身：`write_report` 永远受理成功（只用来造一个"父那一行"）。"""

    def __init__(self) -> None:  # noqa: D107
        pass

    def write_report(self, **_kw: Any) -> dict[str, Any]:  # noqa: D102
        return {"outcome": "ok", "detail": "夹具：写了报告"}


class FakeE(AgentE):
    """E 的替身：`list_experiments` 永远受理成功（触顶之后那一件必须派得进去）。"""

    def __init__(self) -> None:  # noqa: D107
        pass

    def list_experiments(self, **_kw: Any) -> dict[str, Any]:  # noqa: D102
        return {"outcome": "ok", "detail": "夹具：列了实验"}


# ====================================================================== 夹具
def _workspace(tmp_path: pathlib.Path, *, cap: int = CAP) -> dict[str, Any]:
    """一个工作区：D 的父行 + 名册（`roster_sink` 接上，与生产同一条取法）。"""
    root = tmp_path / "ws"
    store = Store(root)
    store.init()
    cond = Conductor(
        store,
        policy=P.Policy(max_concurrency=8, max_direct_children=cap,
                        max_tasks_per_run=500, wall_clock_sec=600),
        registry={"D": ("object", FakeD()), "E": ("object", FakeE())},
        # 触顶时不等：这一份判的是"拒信说的那条路走不走得通"，不是"只可等待"。
        fanout_wait_sec=0.0,
    )
    sec = Secretary("D", root=root, store=store)
    # 生产里由 `AgentLoop._bind_roster_sink` 接上；这里显式接，是为了让"销号"与
    # "登记名册"落同一份名册文件（否则两条链各读一份名册，判据测的就不是生产形态）。
    cond.roster_sink = sec
    cond.secretary = sec
    res = cond.summon("D", "write_report", {}, by="M", input_key="父那一件活")
    assert res.outcome == "ok", f"造父任务失败：{res.outcome}/{res.refusal_reason}"
    return {"root": root, "store": store, "cond": cond, "sec": sec,
            "parent": str(res.task_id)}


def _seed_in_flight(env: dict[str, Any], n: int, *, base: int = 0) -> list[str]:
    """往台账写 n 行"此刻在飞"的子行（父 = 父任务），并把它们登记进名册。

    口径 = `Conductor._in_flight_children_of` 认的那一档，逐字对齐 `schema.Task.validate`：
    `status="running"` ⇒ `started_at` 必须非空；未完成 ⇒ `ended_at=None`、`outcome=None`。
    号段用 `t-9NNN`（字面号，远离自动发放的号）。
    """
    ids = [f"t-9{base + i:03d}" for i in range(n)]
    parent = str(env["parent"])
    with env["store"].tx("tasks", actor="test") as tx:
        for tid in ids:
            row = {
                "task_id": tid, "role": "E", "action": "list_experiments",
                "called_by": "D", "parent_task_id": parent, "depth": 2,
                "input_key": tid, "status": "running", "outcome": None,
                "refusal_reason": None, "instance": "",
                "detail": "夹具：此刻在飞", "error": None,
                "started_at": TS, "ended_at": None,
                "tokens": 0, "usd": 0.0, "artifacts": [], "inputs": [],
            }
            tx.upsert("tasks", row, note="fixture:in_flight")
    for tid in ids:
        got = env["sec"].roster_add(owner=parent, role="E", task_id=tid,
                                    brief="夹具：此刻在飞")
        assert got.get("problem") == "", got
    return ids


def _hand_off(env: dict[str, Any], task_id: str) -> None:
    """记一条交差（生产里由子代理自己的 `agent_loop._hand_off` 写这一笔）。

    这是"父已把它记为静默"的盘上证据（业主 2026-10-27 第四条），也是本功能唯一对象的
    来源：它交完差就收工了，而它那一行此刻还在飞（异步派活 / 收尾没走完）⇒ 占着一格。
    """
    CLK.record_handoff(str(env["root"]), task_id=str(task_id),
                       parent_task_id=str(env["parent"]), role="E",
                       reason="无事可做且没有任何计时器 ⇒ 交差")


def _name_of(env: dict[str, Any], task_id: str) -> str:
    got, _why = env["sec"].name_of(owner=str(env["parent"]), task_id=str(task_id))
    assert got, f"{task_id} 在名册里没有名字"
    return str(got)


def _summon_one(env: dict[str, Any], key: str) -> Any:
    """以父（D）的身份派一件给 E —— 触顶的那一次、以及腾位之后的那一次都走这一格。"""
    return env["cond"].summon("E", "list_experiments", {}, by="D",
                              parent_task_id=str(env["parent"]), input_key=key)


def _retire(env: dict[str, Any], *, child_name: str, reason: str = "") -> Any:
    """以父这一趟的身份调一次销号工具（`calling_as` 挂台账号，生产里由 `_do_tool` 挂）。"""
    reg = ToolRegistry(name="fanout-seat")
    CT.register(reg, store=env["store"], conductor=env["cond"])
    with calling_as(str(env["parent"]), "D"):
        return reg.call(TOOL, {"child_name": str(child_name), "reason": str(reason)},
                        role="D")


def _data_of(res: Any) -> dict[str, Any]:
    assert getattr(res, "ok", False), getattr(res, "error", res)
    return dict(res.data or {})


def _handoff_env(tmp_path: pathlib.Path, *, cap: int = CAP) -> dict[str, Any]:
    """挂满 + 其中一格"已交差、行还在飞"（= 唯一能销号腾出来的那一格）。"""
    env = _workspace(tmp_path, cap=cap)
    ids = _seed_in_flight(env, cap)
    env["seeds"] = ids
    env["silent_id"] = ids[0]
    env["silent_name"] = _name_of(env, ids[0])
    _hand_off(env, ids[0])
    return env


# ====================================================================== a) 拒信四样
def test_a_the_refusal_names_the_tool_the_precondition_and_the_seats(
        tmp_path: pathlib.Path) -> None:
    """a) 触顶拒信：上限现算 + 工具与参数 + 静默前提 + 占位读数（谁已静默、谁还在飞）。

    "现算"必须能分辨：测试档的上限是 3，报文里就不许出现 12 / 25 / 100 当作本次上限。
    """
    env = _handoff_env(tmp_path)
    refused = _summon_one(env, "a0")
    assert refused.outcome == "refused", refused
    assert refused.refusal_reason == "fanout_exceeded", refused
    detail = str(refused.detail or "")
    problems: list[str] = []
    for want in ("上限 3",                      # ① 上限现算（测试档就是 3）
                 "`conductor.retire_child`",    # ② 点名工具
                 "child_name=",                 # ② 点名参数
                 "销号静默子代理",                # 业主那句原话
                 "target_not_silent",           # ③ 点名前提的拒信码
                 "无工作 ∧ 无计时器 ∧ 无活跃子代理",  # ③ 静默的定义
                 "此刻占住这 3 格",              # ④ 占位读数（数量）
                 "已静默、销号即腾位的有 1 个"):    # ④ 谁已静默可销
        if want not in detail:
            problems.append(f"拒信里缺 {want!r}")
    silent_seat = f"{env['silent_name']}（{env['silent_id']}）=静默"
    if silent_seat not in detail:
        problems.append(f"拒信没把那一格点名成『已静默』（找不到 {silent_seat!r}）")
    if "静默" not in detail:
        problems.append("拒信没有『静默』这个词")
    for wrong in ("上限 12", "上限 25", "上限 100"):
        if wrong in detail:
            problems.append(f"上限写死了：拒信里出现了 {wrong!r}（本次上限是 3）")
    assert not problems, "；".join(problems) + f"\n拒信原文：{detail}"


# ====================================================================== b) 端到端
def _b_problems(env: dict[str, Any]) -> list[str]:
    """b) 的判据本体：满 ⇒ 拒；销号一个静默子 ⇒ 下一次 summon 当场成功；占位少一格。

    反真空（e）复用这一份：打桩之后它必须报出问题，否则"打桩 ⇒ 必红"证明的是打桩坏了。
    """
    problems: list[str] = []
    parent = str(env["parent"])
    before = env["cond"].fanout_seats_of(parent)
    if int(before.get("count") or 0) != CAP:
        problems.append(f"夹具没挂满：占位该是 {CAP}，实际 {before.get('count')}")
    refused = _summon_one(env, "b0")
    if refused.refusal_reason != "fanout_exceeded":
        problems.append(f"挂满时该拒 fanout_exceeded，拿到 {refused.outcome}/"
                        f"{refused.refusal_reason}")
    if refused.outcome != "refused":
        problems.append(f"挂满时该是 refused，拿到 {refused.outcome}")

    data = _data_of(_retire(env, child_name=str(env["silent_name"]),
                            reason="已经交差、我不会再用到它"))
    if data.get("state") != "retired":
        problems.append(f"静默子该销得掉，实际 state={data.get('state')!r}："
                        f"{data.get('reason')!r}")
    if data.get("target_state") != "silent":
        problems.append(f"销号读数里该写 target_state=silent，实际 {data.get('target_state')!r}")

    after = env["cond"].fanout_seats_of(parent)
    if int(after.get("count") or 0) != int(before.get("count") or 0) - 1:
        problems.append(f"销号之后占位数该少一格（{before.get('count')} ⇒ "
                        f"{after.get('count')}）")
    nxt = _summon_one(env, "b1")
    if nxt.outcome != "ok":
        problems.append("销号一个静默子之后，同一父的下一次 summon 该当场成功，"
                        f"拿到 {nxt.outcome}/{nxt.refusal_reason}：{nxt.detail}")
    return problems


def test_b_retiring_a_silent_child_frees_the_seat_at_once(tmp_path: pathlib.Path) -> None:
    """b) 端到端：挂满 ⇒ 拒；销号一个静默子 ⇒ 再 summon 成功（改前红：机制不通就红）。"""
    env = _handoff_env(tmp_path)
    problems = _b_problems(env)
    assert not problems, "；".join(problems)
    # 腾出来的那一格被新的那件活用了：它返回之后名额回到 2（不是 3，也不是 1）。
    assert int(env["cond"].fanout_seats_of(str(env["parent"]))["count"] or 0) == CAP - 1


# ====================================================================== c) 反向
def test_c_retiring_a_flying_child_refuses_and_keeps_the_seat(
        tmp_path: pathlib.Path) -> None:
    """c) 反向：销号在飞的子 ⇒ 拒 `target_not_silent`，随后 summon 仍被拒（名额没变）。

    "拒了但名额少了"是最坏的一种：父以为没销成，其实那一格被吃掉了 —— 所以这里同时钉
    三件事：拒信码、拒信给的下一步、以及占位数与台账一个都没动。
    """
    env = _workspace(tmp_path)
    ids = _seed_in_flight(env, CAP)
    env["seeds"] = ids
    flying_name = _name_of(env, ids[0])
    parent = str(env["parent"])

    before = env["cond"].fanout_seats_of(parent)
    assert int(before.get("count") or 0) == CAP
    data = _data_of(_retire(env, child_name=flying_name, reason="想腾个名额"))
    problems: list[str] = []
    if data.get("state") != "refused":
        problems.append(f"在飞的子不该销得掉，实际 state={data.get('state')!r}")
    if data.get("refusal_code") != "target_not_silent":
        problems.append(f"拒信码该是 target_not_silent，实际 {data.get('refusal_code')!r}")
    if data.get("target_state") != "flying":
        problems.append(f"target_state 该是 flying，实际 {data.get('target_state')!r}")
    kinds = [str(b.get("kind") or "") for b in (data.get("blocking") or [])]
    if "working" not in kinds:
        problems.append(f"blocking 该点名『它还在干活』（kind=working），实际 {kinds}")
    if data.get("retired") is True:
        problems.append("在飞的子被销成功了（retired=True）")
    after = env["cond"].fanout_seats_of(parent)
    if int(after.get("count") or 0) != CAP:
        problems.append(f"拒了之后名额不许变：{before.get('count')} ⇒ {after.get('count')}")
    ledger = [r for r in env["store"].rows("tasks")
              if str(r.get("parent_task_id") or "") == parent
              and not str(r.get("kind") or "")
              and str(r.get("status") or "") in ("pending", "running")]
    if len(ledger) != CAP:
        problems.append(f"台账里还在飞的子代理数不许变：该是 {CAP}，实际 {len(ledger)}")
    still = _summon_one(env, "c1")
    if still.refusal_reason != "fanout_exceeded":
        problems.append(f"名额没变 ⇒ 下一次 summon 仍该拒 fanout_exceeded，拿到 "
                        f"{still.outcome}/{still.refusal_reason}")
    assert not problems, "；".join(problems)


# ====================================================================== d) 两处口径
def test_d_the_seat_count_and_the_ledgers_do_not_drift(tmp_path: pathlib.Path) -> None:
    """d) 占位数与台账 / 名册两处口径一致；"静默"在两条读数上是同一个答案。

    三份读数各自独立地数一次"此刻占着几格"：判据的分子（`_in_flight_children_of`）、
    席位读数（`fanout_seats_of`）、名册的未销号项数（`child_counts` 的 `child_count`），
    外加一次直写台账的独立复核。四个数必须相等 —— 销号前后都要相等。
    """
    env = _handoff_env(tmp_path)
    parent = str(env["parent"])
    cond = env["cond"]
    problems: list[str] = []

    def _check(tag: str) -> None:
        seats = cond.fanout_seats_of(parent)
        ledger = [r for r in env["store"].rows("tasks")
                  if str(r.get("parent_task_id") or "") == parent
                  and not str(r.get("kind") or "")
                  and str(r.get("status") or "") in ("pending", "running")]
        counts = env["sec"].child_counts(owner=parent)
        if int(seats.get("count") or 0) != len(cond._in_flight_children_of(parent)):
            problems.append(f"{tag}：席位读数与判据的分子分家了")
        if int(seats.get("count") or 0) != len(ledger):
            problems.append(f"{tag}：席位读数={seats.get('count')} 与台账在飞数={len(ledger)} 分家")
        if counts.get("checked") is not True:
            problems.append(f"{tag}：名册读数没读成（{counts.get('reason')}）")
        elif int(counts.get("child_count") or 0) != len(ledger):
            problems.append(f"{tag}：名册未销号项={counts.get('child_count')} 与台账在飞数"
                            f"={len(ledger)} 分家")
        # "活跃子代理数"（= 非静默）比占位数少的那些，必须正好是"已静默、还能销"的那几格。
        silent_seats = [s for s in (seats.get("seats") or []) if s.get("retirable")]
        active = int(counts.get("active_child_count") or 0)
        if active != int(seats.get("count") or 0) - len(silent_seats):
            problems.append(f"{tag}：活跃子代理数={active} 该等于占位 {seats.get('count')} "
                            f"减去已静默的 {len(silent_seats)} 格")
        # 静默的口径只有一处：席位读数里的 retirable == 交差账里那些"此刻还占着位"的。
        # （交差账是历史账：已销号的那些仍留在账上，但它们已经不在占位名单里 —— 所以
        # 这里比的是"交差账 ∩ 此刻在飞"，不是"交差账全表"。）
        seats_silent = {str(s.get("task_id") or "") for s in silent_seats}
        hand_silent = {str(x) for x in (cond.handoffs_reading(parent).get("silent") or [])}
        in_flight = set(cond._in_flight_children_of(parent))
        if seats_silent != (hand_silent & in_flight):
            problems.append(f"{tag}：席位说静默的 {sorted(seats_silent)} 与交差账里还在飞的 "
                            f"{sorted(hand_silent & in_flight)} 分家（两处口径不许分家）")

    _check("销号前")
    _retire(env, child_name=str(env["silent_name"]), reason="腾一格")
    _check("销号后")
    assert not problems, "；".join(problems)


# ====================================================================== e) 反真空
def test_e_stubbing_the_settle_makes_b_red(tmp_path: pathlib.Path,
                                          monkeypatch: Any) -> None:
    """e) 反真空：把"销号后落定台账 / 重算占位"打桩成不落定 ⇒ b 必红。

    这一档就是改前的形态：销号只写名册三份 jsonl，台账那一行动都不动。打桩只挡住
    落定这一笔，其余全走真实现 —— 于是"销号成功、占位数没变、下一次仍被拒"必须当场
    可见。它同时是 b 的改前红证据：b 在改前红的根子就是这一笔不存在。
    """
    def no_settle(self_: Secretary, task_id: str, *, name: str = "",
                  reason: str = "") -> dict[str, Any]:
        """打桩：返回"查过了、它不占名额"，实际一个字节都不写（= 改前的行为）。"""
        return {"checked": True, "was_occupying": False, "status_before": "",
                "status_after": "", "task_id": str(task_id),
                "reason": "打桩：台账那一行不落定（改前的形态）"}

    monkeypatch.setattr(Secretary, "settle_retired_row", no_settle)
    env = _handoff_env(tmp_path)
    parent = str(env["parent"])
    problems = _b_problems(env)
    assert problems, ("打桩之后 b 仍然全绿 ⇒ b 没有在测『销号真的腾出了名额』，"
                      "它测的只是别的东西")
    joined = "；".join(problems)
    assert "占位数该少一格" in joined or "该当场成功" in joined, (
        f"打桩之后 b 该红在『占位没减 / 下一次仍被拒』这两处，实际红在：{joined}")
    # 再钉一次"打桩没把别的东西打坏"：销号本身仍然是成功的（它只是没腾出名额）。
    assert int(env["cond"].fanout_seats_of(parent)["count"] or 0) == CAP, \
        "打桩下占位数不该自己变（变了说明红的原因不是它）"


def test_f_without_the_handoff_fact_the_retire_is_refused_and_b_is_red(
        tmp_path: pathlib.Path, monkeypatch: Any) -> None:
    """b 的改前红（另一半）：把"交差 ⇒ 静默"这条事实拿掉，销号门当场回到改前。

    改前那扇门只看 `status`：一份已经交差的子代理在它眼里是"在飞"，于是父手上有
    静默子却销不掉 —— b 的第一步（销号）就红。这一条与 e 合起来说明 b 的两半缺一不可：
    没有"交差 ⇒ 静默"，静默子销不掉；没有"销号落定台账"，销掉了名额也不回来。
    """
    from agentflow import conductor as CO

    monkeypatch.setattr(CO, "handoff_index",
                        lambda _ws: {"checked": True, "by_task": {}, "rows": [],
                                     "count": 0, "reason": "打桩：交差账当作没有"})
    env = _handoff_env(tmp_path)
    problems = _b_problems(env)
    assert problems, "拿掉交差那条事实之后 b 仍然全绿 ⇒ b 没有在测『静默子可销』"
    joined = "；".join(problems)
    assert "静默子该销得掉" in joined or "target_state" in joined, (
        f"改前红该红在『销号被拒 / 它没被判成静默』，实际红在：{joined}")
    # 名额当然也没动：拒了就是拒了（不许"拒了但名额少了"）。
    assert int(env["cond"].fanout_seats_of(str(env["parent"]))["count"] or 0) == CAP

# -*- coding: utf-8 -*-
"""级联销号把整棵树清得完（Q13；业主 2026-10-26 两条原话）。

## 业主原话（唯一权威，逐字）

```
「销号和连锁销号这些父代理统一拥有的工具都没被使用（极度怀疑未实现或接线）」
「最终 final 时应该是 M 下整棵树都已销号，否则不记 final」（D-68）
```

## 这一份钉住的到底是什么（先看结论，再看判据）

级联本身在 `b83362c`（2026-10-24 23:05）就落了，落在
`tools/conductor_tools.py::conductor_retire_child`（深→浅、整笔不销或整支销完），
不是本批新写的。本批补的是另一件事：第二个销号入口
`{"retire": {"name": "A1"}}`（`agent_loop._do_retire`，协议骨架里逐步都发给模型的那一形）
直接调 `Secretary.retire`，不走级联，于是

```
M 销 A1  ⇒ A1 退场、B1 留在册上
         ⇒ B1 的父已经销号（名字永久不复用、不会再有下一轮）
         ⇒ 只有它的父能销它 ⇒ 没有任何代理有权限销 B1
         ⇒ Conductor.retire_integrity 永不 complete ⇒ final 被结构完整性闸永久拒
```

这就是"深树永远清不完"的真身。补法是在 `Secretary.retire` 加一条孤儿闸：
销父之前，它名册里不许留下没销号的子。于是"父先走、子成孤儿"在结构上不可能发生，
正路只剩 `conductor.retire_child` 那一件（它先深后浅、一次把整支带走）。

## 六条判据

| 判据 | 守的是 | 改前红在哪 |
|---|---|---|
| a) `test_a_one_cascade_call_retires_the_whole_branch` | 三层树全静默，M 销 A1 ⇒ 整支销号，返回逐条点名编号与层深 | 形那一入口只销 A1 一行，B1 仍占着名册（判据 (g) 直接钉住它） |
| b) `test_b_a_flying_grandchild_is_not_swept_and_is_named` | A1 名下有一个在飞的 B2 ⇒ 整笔不销、B2 原状、逐条点名"它还在跑" | 形那一入口会在 B2 还在跑的时候把 A1 销掉 |
| c) `test_c_a_standby_grandchild_is_not_swept_and_is_named` | A1 名下有一个待机的 B3 ⇒ 同样不连带、点名"它还在等" | 同上（挂钟的那一档更隐蔽：B3 自己 done，只是钟还挂着） |
| d) `test_d_the_readings_carry_count_ids_levels_and_kept` | 返回带 `cascade_reading={count,ids,levels,kept}` 与逐条 `kept[{id,why}]` | 改前没有 `kept` 这一格：拒信只在 `reason` 那句人话里，机器读不出"谁没销" |
| e) `test_e_after_one_cascade_the_final_gate_completes` | 一轮级联之后 `_final_gate_reading().complete == True`（D-68 的闸有可达的完成路径） | 本批之前这条路径在形那一入口上是闭死的（(g) 的读数：complete=False） |
| f) 反真空：`test_f_stubbing_the_cascade_to_one_layer_makes_a_and_e_red` | 把"级联那一层循环"打桩成只销一层 ⇒ a 与 e 必红 | 不适用（它守的是 a/e 不是真空的那几条） |
| g) `test_g_the_second_entry_point_can_no_longer_orphan_a_child` | 形那一入口销父而子未销 ⇒ 受控拒绝，且点名唯一正路 | 改前它返回 `action=retired`，把 B1 永久孤儿化 |
| h) `test_h_the_cascade_path_does_not_trip_the_orphan_gate` | 级联那条路不误伤（先深后浅 ⇒ 轮到父时子已 retired ⇒ 闸放行） | 不适用（正控：它守的正是"加了闸之后级联没被打死"） |
| i) `test_i_retiring_a_leaf_still_works` | 叶子（没有子）照旧销得掉 —— 闸不许误伤绝大多数销号 | 不适用（正控） |

## 关于业主那句"三行都变 retired"

三层树 `M -> A1 -> B1` 里只有两行能变 retired：`M` 是根，没有父，"父给它销号"
对它没有对象（`Conductor.retire_integrity` 的 `root_open_items` 那句注释说的就是这件事）。
所以 (a) 断的是：`A1` 与 `B1` 两行都 retired、整支 `total=2 / count=0`、M 那一行不参与。
把"根也要 retired"写进判据会让这条闸永远绿不了 —— 那正好是 D-68 要防的形态。

## 三态纪律在这一份里的落点

"读不到它名下还有没有子"⇒ 一律不销（fail-closed）。把"没查成"折成"没有子"的代价
在这里最具体：销号不可逆，一次误销就是永久孤儿。
"""

from __future__ import annotations

import json
import pathlib
from typing import Any

import pytest

from agentflow import clock as CLK
from agentflow.agent_loop import AgentLoop
from agentflow.conductor import Conductor, LocalBackend, calling_as
from agentflow.secretary import Secretary, retired_path
from agentflow.store import Store
from agentflow.tools import conductor_tools as CT
from agentflow.tools.base import ToolRegistry

#: 父代理唯一的级联销号入口。
TOOL = "conductor.retire_child"

TS = "2026-01-01T00:00:00+00:00"


# ====================================================================== 夹具
def _workspace(tmp_path: pathlib.Path) -> dict[str, Any]:
    """一个工作区 ＋ 一个主控（`roster_sink` 接上，与生产同一条取法）。"""
    root = tmp_path / "ws"
    store = Store(root)
    store.init()
    cond = Conductor(store, registry={}, backend=LocalBackend({}))
    sec = Secretary("M", root=root, store=store)
    cond.roster_sink = sec
    owner = str(cond.open_top_level_run("M", "夹具：级联销号把树清得完"))
    return {"root": root, "store": store, "cond": cond, "sec": sec, "owner": owner}


def _child(cond: Conductor, parent: str, *, role: str = "D",
           status: str = "done") -> str:
    """造一个子代理的台账行（`kind` 空 = 代理行；`done` 带 outcome 与 ended_at）。"""
    return cond._write_new_row({
        "role": role, "action": "write_report", "called_by": "M",
        "parent_task_id": parent, "depth": 2,
        "input_key": f"q13:{role}:{status}:{parent}",
        "status": status,
        "outcome": ("ok" if status == "done" else None),
        "refusal_reason": None, "instance": "", "detail": "夹具子代理", "error": None,
        "started_at": TS, "ended_at": (TS if status == "done" else None),
        "tokens": 0, "usd": 0.0, "artifacts": [], "inputs": [],
    }, note="fixture:q13")


def _register(env: dict[str, Any], owner: str, task_id: str, *,
              role: str = "D", brief: str = "写研究报告") -> str:
    """把它登记进 `owner` 那份名册（销号的正路指称是名册名，所以这一步是前提）。"""
    got = env["sec"].roster_add(owner=str(owner), role=role, task_id=task_id, brief=brief)
    assert got.get("problem") == "", got
    return str(got["name"])


def _call(env: dict[str, Any], **kwargs: Any) -> Any:
    """以"父这一趟"的身份调一次销号（`calling_as` 挂上台账号，生产里由 `_do_tool` 挂）。"""
    reg = ToolRegistry(name="q13")
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


def _names(rows: list[dict]) -> list[str]:
    return [str(r.get("name") or "") for r in rows]


def _gate(env: dict[str, Any]) -> AgentLoop:
    """一趟主控的循环对象：`_final_gate_reading` 是纯读，不需要真模型。"""
    loop = AgentLoop(role="M", session_root=env["root"], registry=None, seam=None,
                     conductor=env["cond"], store=env["store"], sid="q13",
                     auto_secretary=False)
    loop.my_task_id = str(env["owner"])
    loop.secretary = env["sec"]
    return loop


def _chain(tmp_path: pathlib.Path, *, b_status: str = "done",
           b_timer: bool = False) -> dict[str, Any]:
    """三层树 `M -> A1 -> B1`，M 与 A1 都静默；B1 的样子由参数定。

    `depth` 由 `subtree_postorder` 现算（目标自己是 0），夹具不手写。
    """
    env = _workspace(tmp_path)
    owner = str(env["owner"])
    a1 = _child(env["cond"], owner, role="A")
    b1 = _child(env["cond"], a1, role="D", status=b_status)
    env["a1"] = a1
    env["b1"] = b1
    env["nm_a1"] = _register(env, owner, a1, role="A", brief="夹具 A1")
    env["nm_b1"] = _register(env, a1, b1, role="D", brief="夹具 B1")
    if b_timer:
        CLK.start_timer(str(env["root"]), reason="等实验结果", after_sec=600.0,
                        task_id=b1, role="D")
    return env


# ====================================================================== a) 整支销号
def _a_problems(env: dict[str, Any]) -> list[str]:
    """(a) 的判据本体：三层树全静默 ⇒ M 销 A1 一次把整支销完，逐条点名编号与层深。"""
    a1, b1 = str(env["a1"]), str(env["b1"])
    problems: list[str] = []
    data = _data_of(_call(env, child_name=str(env["nm_a1"])))
    if data.get("state") != "retired" or data.get("retired") is not True:
        return [f"三层树全静默 ⇒ 该销成，实际 state={data.get('state')!r}："
                f"{str(data.get('reason') or '')[:200]}"]
    if list(data.get("order") or []) != [b1, a1]:
        problems.append(f"级联次序该从最深到最浅 [B1, A1]，实际 {data.get('order')!r}")
    if int(data.get("subtree_size") or 0) != 2:
        problems.append(f"subtree_size 该是 2（不含根 M），实际 {data.get('subtree_size')!r}")
    if int(data.get("retired_count") or 0) != 2:
        problems.append(f"该销掉 2 项，实际 retired_count={data.get('retired_count')!r}")
    reading = dict(data.get("cascade_reading") or {})
    if reading.get("ids") != [b1, a1]:
        problems.append(f"cascade_reading.ids 该逐条点名 [B1, A1]，实际 {reading.get('ids')!r}")
    if reading.get("levels") != [1, 0]:
        problems.append(f"cascade_reading.levels 该逐层给 [1, 0]（目标自己为 0），"
                        f"实际 {reading.get('levels')!r}")
    if int(reading.get("count") or 0) != 2:
        problems.append(f"cascade_reading.count 该是 2，实际 {reading.get('count')!r}")
    if reading.get("kept") != []:
        problems.append(f"整支销完 ⇒ kept 该是空表，实际 {reading.get('kept')!r}")
    # 三份销号名单：级联是"各自的父给自己的直接子销号"，不是全塞进 M 那一份。
    if _names(_retired_rows(env["root"], str(env["owner"]))) != [str(env["nm_a1"])]:
        problems.append(f"M 的销号名单该只有 A1，"
                        f"实际 {_names(_retired_rows(env['root'], str(env['owner'])))}")
    if _names(_retired_rows(env["root"], a1)) != [str(env["nm_b1"])]:
        problems.append(f"A1 的销号名单该只有 B1，"
                        f"实际 {_names(_retired_rows(env['root'], a1))}")
    # 整棵树清得完：根自己不在"要销号"的对象里（它没有父），所以 total=2 / count=0。
    integ = env["cond"].retire_integrity(str(env["owner"]))
    if not integ.get("checked"):
        problems.append(f"retire_integrity 没读成：{integ.get('reason')}")
    elif integ.get("complete") is not True:
        problems.append(f"一轮级联之后整棵树该是 complete，实际 {integ.get('complete')!r}"
                        f"（还在册 {integ.get('count')}/{integ.get('total')}："
                        f"{[n.get('task_id') for n in (integ.get('nodes') or [])]}）")
    return problems


def test_a_one_cascade_call_retires_the_whole_branch(tmp_path: pathlib.Path) -> None:
    """a) 三层树全静默，M 销 A1 ⇒ 整支变 retired，返回点名 2 个编号与层深。

    改前红：形那一入口（见 (g)）只销 A1 一行 —— 同一份夹具、同一次"父说销 A1"，
    在那一入口上 B1 留在名册里，而它的父已经退场。
    """
    env = _chain(tmp_path)
    problems = _a_problems(env)
    assert problems == [], problems


# ====================================================================== b) 在飞的孙代
def test_b_a_flying_grandchild_is_not_swept_and_is_named(
        tmp_path: pathlib.Path) -> None:
    """b) A1 名下有一个在飞的 B2 ⇒ 整笔不销、B2 原状、逐条点名"它还在跑"。

    业主口径下的答案（也是"不许扩权"的形态）：A1 自己也不销，因为
    "有活跃子 ⇒ 非静默"是本仓的不变量（`Conductor.agent_state`），A1 此刻被读成
    待机而不是静默。父此刻的可行动作只有一个：先处置 B2（等在飞的交差，
    或用叫停让它停），再来一次级联把整支带走。
    """
    env = _chain(tmp_path, b_status="running")
    b1, a1 = str(env["b1"]), str(env["a1"])
    data = _data_of(_call(env, child_name=str(env["nm_a1"])))
    problems: list[str] = []
    if data.get("state") != "refused":
        problems.append(f"孙代还在飞 ⇒ 该受控拒绝，实际 state={data.get('state')!r}")
    if data.get("retired") is not False or int(data.get("retired_count") or 0) != 0:
        problems.append(f"被拒绝时一项都不许销：retired={data.get('retired')!r} "
                        f"retired_count={data.get('retired_count')!r}")
    if data.get("refusal_code") != "target_not_silent":
        problems.append(f"拒信码该是 target_not_silent，实际 {data.get('refusal_code')!r}")
    if _retired_rows(env["root"], str(env["owner"])):
        problems.append("被拒绝时 M 的销号名单里不许有行")
    if _retired_rows(env["root"], a1):
        problems.append("被拒绝时 A1 的销号名单里不许有行（B1 更不许被连带）")
    # 逐条点名：B1 与 A1 都在 kept 里，且各有一句"为什么没销"
    kept = {str(x.get("id") or ""): x for x in (data.get("kept") or [])}
    if set(kept) != {b1, a1}:
        problems.append(f"kept 该逐条点名 [B1, A1]，实际 {sorted(kept)}")
    if b1 in kept and not str(kept[b1].get("why") or ""):
        problems.append(f"kept 里 B1 那一行没有 why：{kept[b1]!r}")
    if a1 in kept and "活跃" not in str(kept[a1].get("why") or ""):
        problems.append(f"kept 里 A1 那一行该说清它缠在哪个活跃子上：{kept[a1]!r}")
    # 下一步：拒信要把人引到"先处置它、再来销"
    reason = str(data.get("reason") or "")
    if "先让那些子代理收工" not in reason:
        problems.append(f"拒信没给出下一步（先让子代理收工）：{reason}")
    # B2 原状：状态逐字没动、也没有销号落痕
    row = next(r for r in env["store"].rows("tasks") if str(r.get("task_id")) == b1)
    if str(row.get("status") or "") != "running":
        problems.append(f"B2 的状态被动了：{row.get('status')!r}")
    assert problems == [], problems


# ====================================================================== c) 待机的孙代
def test_c_a_standby_grandchild_is_not_swept_and_is_named(
        tmp_path: pathlib.Path) -> None:
    """c) A1 名下有一个待机的 B3（done 但挂着钟）⇒ 同样不连带、点名"它还在等"。

    这一档比 (b) 更隐蔽：B3 自己不忙（status=done），只有一条挂着的计时器说明
    "它还会醒过来"。销号是不可逆的，所以这一档必须与在飞那一档一样拒。
    """
    env = _chain(tmp_path, b_status="done", b_timer=True)
    b1, a1 = str(env["b1"]), str(env["a1"])
    data = _data_of(_call(env, child_name=str(env["nm_a1"])))
    problems: list[str] = []
    if data.get("state") != "refused":
        problems.append(f"孙代挂着钟 ⇒ 该受控拒绝，实际 state={data.get('state')!r}")
    if int(data.get("retired_count") or 0) != 0:
        problems.append(f"被拒绝时一项都不许销，实际 {data.get('retired_count')!r}")
    if data.get("refusal_code") != "target_not_silent":
        problems.append(f"拒信码该是 target_not_silent，实际 {data.get('refusal_code')!r}")
    if data.get("target_state") != "standby":
        problems.append(f"目标该读成待机（它挂着钟），实际 {data.get('target_state')!r}")
    if _retired_rows(env["root"], a1):
        problems.append("被拒绝时 A1 的销号名单里不许有行（B1 更不许被连带）")
    kept = {str(x.get("id") or ""): x for x in (data.get("kept") or [])}
    if set(kept) != {b1, a1}:
        problems.append(f"kept 该逐条点名 [B1, A1]，实际 {sorted(kept)}")
    if b1 in kept and not str(kept[b1].get("why") or ""):
        problems.append(f"kept 里 B1 那一行没有 why：{kept[b1]!r}")
    reason = str(data.get("reason") or "")
    if "待机" not in reason:
        problems.append(f"拒信没说清它是待机（还在等）：{reason}")
    assert problems == [], problems


# ====================================================================== d) 读数
def test_d_the_readings_carry_count_ids_levels_and_kept(
        tmp_path: pathlib.Path) -> None:
    """d) 返回带 `cascade_reading={count,ids,levels,kept}` 与逐条 `kept[{id,why}]`。

    这一格是给机器读的：父下一步要处置的正是"没销的那几个与为什么"，
    而改前它只活在 `reason` 那句人话里（`missing` 是给 `conductor.ack` 用的字符串表，
    口径不同）。两档都要有它：销成时 `kept` 是空表，拒绝时 `kept` 逐条点名。
    """
    # 销成那一档
    env = _chain(tmp_path / "ok")
    data = _data_of(_call(env, child_name=str(env["nm_a1"])))
    reading = data.get("cascade_reading")
    assert isinstance(reading, dict), f"cascade_reading 该是对象，实际 {reading!r}"
    assert set(reading) == {"count", "ids", "levels", "kept"}, sorted(reading)
    assert reading["count"] == 2, reading
    assert reading["ids"] == [str(env["b1"]), str(env["a1"])], reading
    assert reading["levels"] == [1, 0], reading
    assert reading["kept"] == [], reading
    assert data.get("kept") == [], data.get("kept")

    # 拒绝那一档（孙代在飞）
    env2 = _chain(tmp_path / "refused", b_status="running")
    data2 = _data_of(_call(env2, child_name=str(env2["nm_a1"])))
    reading2 = data2.get("cascade_reading")
    assert isinstance(reading2, dict), f"拒绝档也要有 cascade_reading：{reading2!r}"
    assert reading2["count"] == 0 and reading2["ids"] == [] and reading2["levels"] == [], reading2
    assert {str(x["id"]) for x in reading2["kept"]} == {str(env2["b1"]), str(env2["a1"])}, reading2
    for row in reading2["kept"]:
        assert set(row) >= {"id", "why"}, row
        assert str(row["why"]), f"kept 里每一行都要有 why：{row!r}"


# ====================================================================== e) 闸有可达的完成路径
def _e_problems(env: dict[str, Any]) -> list[str]:
    """(e) 的判据本体：一轮级联之后 `_final_gate_reading().complete` 必须是 True。"""
    problems: list[str] = []
    loop = _gate(env)
    before = dict(loop._final_gate_reading())
    if before.get("applicable") is not True:
        problems.append(f"主控 M 名下这一道闸该 applicable，实际 {before.get('applicable')!r}")
    if before.get("checked") is not True:
        problems.append(f"闸该读得成，实际 checked={before.get('checked')!r}："
                        f"{before.get('reason')!r}")
    if before.get("complete") is not False:
        problems.append(f"还没销号时闸该是 complete=False，实际 {before.get('complete')!r}")
    data = _data_of(_call(env, child_name=str(env["nm_a1"])))
    if data.get("state") != "retired":
        return problems + [f"级联没销成，闸当然过不去：{str(data.get('reason') or '')[:200]}"]
    after = dict(loop._final_gate_reading())
    if after.get("complete") is not True:
        problems.append(f"一轮级联之后闸该放行（complete=True），实际 "
                        f"{after.get('complete')!r}；why={str(after.get('why') or '')[:300]!r}")
    if after.get("why"):
        problems.append(f"complete=True 的那一档 why 该是空串，实际 {after.get('why')!r}")
    return problems


def test_e_after_one_cascade_the_final_gate_completes(tmp_path: pathlib.Path) -> None:
    """e) 一轮级联之后 `_final_gate_reading().complete == True`。

    这是 Q13 的真正目的：让 D-68 那道闸有一条可达的完成路径。判据分两步：
    销之前必须是 False（否则这道闸是摆设），销之后必须是 True（否则 M 永远交不了工）。
    """
    env = _chain(tmp_path)
    problems = _e_problems(env)
    assert problems == [], problems


# ====================================================================== f) 反真空
def _stub_cascade_to_one_layer(monkeypatch: pytest.MonkeyPatch) -> None:
    """把"级联那一层循环"打桩成只销自己（`subtree_postorder` 只返回目标那一项）。"""
    real = Conductor.subtree_postorder

    def stub(self, root_task_id: str) -> dict:
        got = real(self, root_task_id)
        if not got.get("checked"):
            return got
        order = list(got.get("order") or [])
        order = order[-1:]           # 只留最浅那一项 = 目标自己
        inside = set(order)
        return dict(got, order=order,
                    depth_of={k: v for k, v in (got.get("depth_of") or {}).items()
                              if k in inside},
                    parent_of={k: v for k, v in (got.get("parent_of") or {}).items()
                               if k in inside},
                    rows=[r for r in (got.get("rows") or [])
                          if str(r.get("task_id") or "") in inside])

    monkeypatch.setattr(Conductor, "subtree_postorder", stub)


def _stub_orphan_gate_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """把孤儿闸打桩成"永远看不到没销的子"。

    反真空要测的是级联那一层，所以另一道防线（孤儿闸）必须关掉 —— 否则
    只销一层的打桩会先被那道闸拒掉，红的原因就换成了"被拒"而不是"树没清完"。
    """
    monkeypatch.setattr(Secretary, "_children_left_behind",
                        lambda self, tid: {"checked": True, "rows": [], "reason": ""})


def test_f_stubbing_the_cascade_to_one_layer_makes_a_and_e_red(
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch) -> None:
    """f) 反真空：把级联打桩成只销一层 ⇒ a 与 e 必红。

    只销一层的话：B1 留在名册上（a 的 kept / count / 销号名单都对不上），
    而整棵树永远不 complete（e 必红）。两条都必须报出问题 —— 否则它们证明不了
    "整棵树清得完"这件事。
    """
    _stub_cascade_to_one_layer(monkeypatch)
    _stub_orphan_gate_off(monkeypatch)
    env_a = _chain(tmp_path / "a")
    problems_a = _a_problems(env_a)
    assert problems_a, "只销一层之后 (a) 仍然绿 ⇒ 它证明不了级联把整支都销了"
    assert any("B1" in p or "kept" in p or "retired_count" in p for p in problems_a), problems_a

    env_e = _chain(tmp_path / "e")
    problems_e = _e_problems(env_e)
    assert problems_e, "只销一层之后 (e) 仍然绿 ⇒ 它证明不了闸有可达的完成路径"
    assert any("complete" in p for p in problems_e), problems_e


# ====================================================================== g) 形那一入口的孤儿洞
def test_g_the_second_entry_point_can_no_longer_orphan_a_child(
        tmp_path: pathlib.Path) -> None:
    """g) 形那一入口销父而子未销 ⇒ 受控拒绝，并点名唯一正路。

    改前红（本判据的取证读数，改前实测）：
    `Secretary.retire(owner=M, name=A1)` 返回 `action="retired"`，A1 的销号名单落了一行，
    A1 名下没有任何销号名单文件（B1 没被带走）；之后
    `retire_integrity: complete=False count=1/2`，而 M 想直接销 B1 拿到的是
    "名册里没有 D1 这个名字"（B1 不在 M 的名册里）⇒ B1 永久在册、final 永久被拒。
    """
    env = _chain(tmp_path)
    a1, b1 = str(env["a1"]), str(env["b1"])
    problems: list[str] = []

    got = env["sec"].retire(owner=str(env["owner"]), name=str(env["nm_a1"]),
                            by_task_id=str(env["owner"]))
    if got.get("action") != "refused":
        problems.append(f"形那一入口销父而子未销 ⇒ 该受控拒绝，实际 action={got.get('action')!r}")
    if got.get("ok") is not False:
        problems.append(f"被拒时 ok 该是 False，实际 {got.get('ok')!r}")
    why = "；".join(str(x) for x in (got.get("why") or []))
    for want in ("只有它这一个父能销", "`conductor.retire_child",
                 "没有任何代理有权限销它们"):
        if want not in why:
            problems.append(f"拒信里该有「{want}」这一句：{why}")
    cascade = dict(got.get("cascade") or {})
    kept = {str(x.get("id") or ""): x for x in (cascade.get("kept") or [])}
    if b1 not in kept:
        problems.append(f"cascade.kept 该点名 B1，实际 {sorted(kept)}")
    # 一个字节都不许落盘：A1 还在册、B1 也没有被连带
    if _retired_rows(env["root"], str(env["owner"])):
        problems.append("被拒时 M 的销号名单里不许有行")
    if _retired_rows(env["root"], a1):
        problems.append("被拒时 A1 的销号名单里不许有行")

    # 正路仍然可达：同一条树用级联工具一次销完，闸放行。
    data = _data_of(_call(env, child_name=str(env["nm_a1"])))
    if data.get("state") != "retired":
        problems.append(f"被拒之后正路该仍然走得通，实际 {data.get('state')!r}："
                        f"{str(data.get('reason') or '')[:200]}")
    if env["cond"].retire_integrity(str(env["owner"])).get("complete") is not True:
        problems.append("拒了形那一入口之后，级联那一件该能把整棵树清完（complete=True）")
    assert problems == [], problems


def test_g_anti_vacuum_without_the_gate_the_orphan_hole_reappears(
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch) -> None:
    """g 的反真空：把孤儿闸关掉 ⇒ 改前那个孤儿洞原样复现。

    这一条就是本判据的"改前红"，而且是永久可复现的那一版：它逐条断言
    "闸不在时会怎样"——A1 被销、B1 留下、整棵树 1/2、而 M 想直接销 B1 拿到的
    是"它不是你的子代理"。没有这一条，(g) 只能证明"现在会拒"，
    证明不了"这一拒就是那道闸在起作用"。
    """
    monkeypatch.setattr(Secretary, "_children_left_behind",
                        lambda self, tid: {"checked": True, "rows": [], "reason": ""})
    env = _chain(tmp_path)
    a1, b1 = str(env["a1"]), str(env["b1"])
    got = env["sec"].retire(owner=str(env["owner"]), name=str(env["nm_a1"]),
                            by_task_id=str(env["owner"]))
    # 改前：销父成功，子没被带走
    assert got.get("action") == "retired", got
    assert _names(_retired_rows(env["root"], str(env["owner"]))) == [str(env["nm_a1"])]
    assert _retired_rows(env["root"], a1) == [], "改前的形态：A1 名下没有销号名单文件"
    # 改前：整棵树清不完（B1 永久在册）
    integ = env["cond"].retire_integrity(str(env["owner"]))
    assert integ["complete"] is False and integ["count"] == 1 and integ["total"] == 2, integ
    # 改前：M 想直接销 B1 —— 销不动（B1 不在 M 的名册里；工具先按 M 的名册译名）
    refused = _data_of(_call(env, child_name=str(env["nm_b1"])))
    assert refused.get("state") == "refused", refused
    reason = str(refused.get("reason") or "")
    assert ("名册里没有" in reason or "不是你的子代理" in reason), reason


# ====================================================================== h) 级联不误伤
def test_h_the_cascade_path_does_not_trip_the_orphan_gate(
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch) -> None:
    """h) 正控：级联那条路不触发孤儿闸（先深后浅 ⇒ 轮到父时子已经 retired）。

    这条是为"修好孤儿洞的同时别把级联打死"立的：`Secretary.retire` 每一次都必须是
    `action="retired"`，一次也不许出现"父名下还有没销的子"那种拒绝；
    而且轮到 A1 的那一刻，B1 的名册项已经标了 retired（闸能放行的真实原因）。
    """
    env = _chain(tmp_path)
    a1 = str(env["a1"])
    seen: list[tuple[str, str, str, bool]] = []
    real = Secretary.retire

    def spy(self, *, owner: str, name: str, by_task_id: str = "", reason: str = ""):
        got = real(self, owner=owner, name=name, by_task_id=by_task_id, reason=reason)
        # 这一笔跑完之后，A1 名册上 B1 的 retired 读数（闸下次能不能放行就看它）
        folded, _bad = self.roster_rows(a1)
        kids_retired = all(bool(k.get("retired")) for k in folded)
        seen.append((str(owner), str(name), str(got.get("action") or ""), kids_retired))
        return got

    monkeypatch.setattr(Secretary, "retire", spy)
    data = _data_of(_call(env, child_name=str(env["nm_a1"])))

    problems: list[str] = []
    if data.get("state") != "retired":
        problems.append(f"级联被孤儿闸误伤了：state={data.get('state')!r}："
                        f"{str(data.get('reason') or '')[:300]}")
    actions = [a for _o, _n, a, _k in seen]
    if actions and any(a != "retired" for a in actions):
        problems.append(f"级联里每一次秘书销号都该是 retired，实际 {actions}")
    if len(seen) != 2:
        problems.append(f"三层树该调两次秘书，实际 {len(seen)} 次：{seen}")
    # 轮到 A1 那一笔时，B1 已经 retired（这才是闸放行的真实原因，不是特批）
    if len(seen) == 2 and not seen[0][3]:
        problems.append(f"销 B1 那一笔之后 A1 名下该全都是 retired：{seen}")
    assert problems == [], problems


# ====================================================================== i) 叶子照旧
def test_i_retiring_a_leaf_still_works(tmp_path: pathlib.Path) -> None:
    """i) 正控：叶子（名下没有子代理）照旧销得掉 —— 闸不许误伤绝大多数销号。

    这一条守的是"闸不能宽到把正常销号也拦掉"：孤儿闸只在"父名下还有没销的子"
    这一个形状上说话，叶子那一路它连一行都不该拦。
    """
    env = _workspace(tmp_path)
    owner = str(env["owner"])
    leaf = _child(env["cond"], owner, role="D")
    name = _register(env, owner, leaf)
    data = _data_of(_call(env, child_name=name))
    assert data.get("state") == "retired", data
    assert int(data.get("retired_count") or 0) == 1, data
    assert _names(_retired_rows(env["root"], owner)) == [name], data
    assert dict(data.get("cascade_reading") or {}).get("levels") == [0], data

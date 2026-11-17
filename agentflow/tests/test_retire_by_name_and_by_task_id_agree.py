# -*- coding: utf-8 -*-
"""销号的两个入口（名册名 / 台账号）必须指向同一个节点（业主 2026-11-17 真机缺陷 ③）。

## 现场（`projects/lp-ball-3`，2026-11-17，`final` 被结构完整性闸拒三次）

M 试了三条路都清不掉 `D1` 这一支：

| 入口 | 真机读数（原样） |
|---|---|
| `retire_child(child_name="D1")` | 「还没销 F1：它名下还有 1 个名册项没有销号（V2（t-000019））」；而同一次级联读数里 `t-000019` 又标「已经销过号」 |
| `retire_child(task_id="t-000010")` | 「t-000010 不是你的子代理」 |
| `{"retire": {"name": "D1"}}` | 「D1 已经销号过（业主 B1）」 |

最后 `retire_integrity` 仍报 3/24 在册（`t-000008` / `t-000010` / `t-000072`），
而 `t-000008` 就是 `D1` 那一项自己的号 —— 名册与台账对不上。

## 根因（两处，同一条"名字 ↔ 号"的解析）

1. `Secretary._resolve`（按名找号）读 `_fold_index` 的折叠结果 = 每个名字最新那条
   `bind` 的号；而 `name_of`（按号找名）也读同一份折叠 ⇒ 名字被复用（同一个子代理
   再接一件活）之后，早先那个号在折叠视图里"不存在"。真机 `D1` 绑过 `t-000008`
   与 `t-000110`：按名销的是 `t-000110`，按号查 `t-000008` 回「未登记」——
   两个入口给出两种答案。
2. 销号只落定"最新那个号"：`Secretary.retire` 的 `settle_retired_row` /
   `note_edge_release` 都只拿解析出来的一个号，而 `Conductor.retire_integrity`
   按父行 `inputs` 里的 `edge-released:` 落痕数每一个代理行 ⇒ 早先那个号永远"还在册"。

## 这一份钉住的四条

| 判据 | 守的是 | 改前红在哪 |
|---|---|---|
| a) `test_a_both_entrances_retire_the_same_item_and_it_is_the_last_free_of_them` | 同一项用 `child_name` 销一次、再用 `task_id` 销一次：第一次真的把这一项绑过的所有号都落定（`task_ids` 点名、`retire_integrity` 不再把它算在册）；第二次报「已销」而不是「对不上」 | 改前按名只销最新那个号；按号则可能读成"名册里没有它"（被当成 unrostered 只认边、回执还说 retired） |
| b) `test_b_retiring_one_name_never_sweeps_another_item` | 名册名被复用时，按 name 销只带走这一项绑过的号；别的名册项一个字都不动 | 不适用（正控：口径不许从"销一个"放宽成"销一片"） |
| c) `test_c_resolving_by_the_item_id_is_the_same_answer_as_by_name` | 两个入口解析出同一个号（`resolve_roster_item(name)` 与 `name_of(该号)` 互为逆） | 改前一个给最新 bind、另一个对早先的号回空 |
| d) `test_d_stubbing_the_roster_resolution_makes_a_red` | 反真空：把"按父名册解析"打回折叠口径 ⇒ a 必红（早先那个号留在册） | 不适用（它守的是 a 不是真空） |

## 为什么钉的是"项"而不是"号"

一个子代理可以接 N 件活（`_roster_add` 的 `reuse` 支，业主 2026-10-24 的口径）——
所以一个名字绑 N 个号是合法的一等功能。销号销的是"这一项"（身份），
而 `retire_integrity` 数的是台账行 ⇒ 销一项 = 把它绑过的每一行都落定终态 + 认边。
把这两个量折成一个（只销一个号）就是 `lp-ball-3` 那 3/24 的真身。
"""
from __future__ import annotations

import pathlib
from typing import Any

import pytest

from agentflow.conductor import Conductor, LocalBackend, calling_as
from agentflow.secretary import Secretary
from agentflow.store import Store
from agentflow.tools import conductor_tools as CT
from agentflow.tools.base import ToolRegistry

#: 父代理唯一的级联销号入口（与 `test_cascade_retire_closes_the_tree` 同一个）。
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
    owner = str(cond.open_top_level_run("M", "夹具：销号两个入口指向同一个节点"))
    return {"root": root, "store": store, "cond": cond, "sec": sec, "owner": owner}


def _child(cond: Conductor, parent: str, *, role: str = "D",
           status: str = "done") -> str:
    """造一个子代理的台账行（`kind` 空 = 代理行；`done` 带 outcome 与 ended_at）。"""
    return cond._write_new_row({
        "role": role, "action": "write_report", "called_by": "M",
        "parent_task_id": parent, "depth": 2,
        "input_key": f"fx2:{role}:{status}:{parent}",
        "status": status,
        "outcome": ("ok" if status == "done" else None),
        "refusal_reason": None, "instance": "", "detail": "夹具子代理", "error": None,
        "started_at": TS, "ended_at": (TS if status == "done" else None),
        "tokens": 0, "usd": 0.0, "artifacts": [], "inputs": [],
    }, note="fixture:fx2")


def _register(env: dict[str, Any], owner: str, task_id: str, *,
              role: str = "D", brief: str = "写研究报告", reuse: str = "") -> str:
    """把它登记进 `owner` 那份名册；`reuse=<名>` = 同一个子代理再接一件活（新号、旧名）。"""
    got = env["sec"].roster_add(owner=str(owner), role=role, task_id=task_id,
                                brief=brief, reuse=reuse)
    assert got.get("problem") == "", got
    return str(got["name"])


def _call(env: dict[str, Any], **kwargs: Any) -> Any:
    """以"父这一趟"的身份调一次销号（`calling_as` 挂上台账号，生产里由 `_do_tool` 挂）。"""
    reg = ToolRegistry(name="fx2")
    CT.register(reg, store=env["store"], conductor=env["cond"])
    with calling_as(str(env["owner"]), "M"):
        return reg.call(TOOL, dict(kwargs), role="M")


def _node_ids(env: dict[str, Any]) -> set[str]:
    """`retire_integrity` 眼里"还在册"的那些号（结构完整性闸数的那一份）。"""
    got = env["cond"].retire_integrity(str(env["owner"]))
    assert got.get("checked"), got
    return {str(n.get("task_id") or "") for n in (got.get("nodes") or [])}


# ====================================================================== a) 两个入口
def test_a_both_entrances_retire_the_same_item_and_it_is_the_last_free_of_them(
        tmp_path: pathlib.Path) -> None:
    """a：`child_name` 销一次（把这一项绑过的号都带走），再用 `task_id` 销一次 ⇒「已销」。

    改名册名被复用（同一个 `D1` 接过两件活：`t-000002` 建项、`t-000003` 复用）。
    """
    env = _workspace(tmp_path)
    owner = str(env["owner"])
    first = _child(env["cond"], owner)
    reused = _child(env["cond"], owner)
    name = _register(env, owner, first)
    reused_name = _register(env, owner, reused, reuse=name)
    assert reused_name == name, (name, reused_name)
    assert _node_ids(env) == {first, reused}, _node_ids(env)

    got = _call(env, child_name=name)
    data = dict(got.data or {})
    assert data.get("state") == "retired", data
    # ① 两个入口指向同一个节点：按名解析到的是名册项自己的号，不是复用那一趟
    assert data.get("task_id") == first, data
    # ② 结构完整性闸数的那一份：这一项绑过的号都不在册了
    assert _node_ids(env) == set(), _node_ids(env)
    # ③ 名册项本身也标了 retired（两个入口读的是同一件事）
    retired = [r for r in env["sec"].roster_rows(owner)[0] if r.get("name") == name]
    assert retired and retired[0].get("retired") is True, retired

    # ④ 第二次：换 `task_id` 入口、指向同一个节点 ⇒ 必须是「已销」，不是「对不上」
    again = _call(env, task_id=reused)
    again_data = dict(again.data or {})
    assert again_data.get("state") == "refused", again_data
    why = str(again_data.get("reason") or "")
    assert "已经销过号" in why or "不重复销" in why, why
    assert "名册里没有" not in why and "不是你的子代理" not in why, why
    # 两个入口都没把台账弄脏：一份销号名单、两个号各一行
    from agentflow.secretary import retired_path

    rows = [r for r in _jsonl(retired_path(env["root"], owner))]
    assert sorted({str(r.get("task_id") or "") for r in rows}) == sorted([first, reused]), rows
    assert _node_ids(env) == set(), _node_ids(env)


def _jsonl(path: Any) -> list[dict[str, Any]]:
    import json

    out: list[dict[str, Any]] = []
    for line in pathlib.Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            out.append(json.loads(line))
    return out


# ====================================================================== b) 不误销他人
def test_b_retiring_one_name_never_sweeps_another_item(tmp_path: pathlib.Path) -> None:
    """b：按 name 销只带走这一项绑过的号；另一个名册项（同一个父）一个字都不动。"""
    env = _workspace(tmp_path)
    owner = str(env["owner"])
    left_a = _child(env["cond"], owner)
    left_b = _child(env["cond"], owner)
    other = _child(env["cond"], owner, role="E")
    name_a = _register(env, owner, left_a, role="D")
    _register(env, owner, left_b, role="D", reuse=name_a)
    name_b = _register(env, owner, other, role="E")

    got = _call(env, child_name=name_a)
    data = dict(got.data or {})
    assert data.get("state") == "retired", data
    # 别人的号还在册、也还在名册上没销号
    assert _node_ids(env) == {other}, _node_ids(env)
    kept = [r for r in env["sec"].roster_rows(owner)[0] if r.get("name") == name_b]
    assert kept and kept[0].get("retired") is False, kept
    # 它名下没有落任何销号行
    from agentflow.secretary import retired_path

    rows = _jsonl(retired_path(env["root"], owner))
    assert {str(r.get("name") or "") for r in rows} == {name_a}, rows


# ====================================================================== c) 同一答案
def test_c_resolving_by_the_item_id_is_the_same_answer_as_by_name(
        tmp_path: pathlib.Path) -> None:
    """c：两个解析互为逆：`resolve_roster_item(name)` 的号 ⇄ `name_of(号)` 的名字。

    改前 `name_of` 读折叠视图 ⇒ 复用场景下对早先那个号回空；`resolve_roster_item`
    读名册项自己的号（`first_task_id`）。两条路现在必须说同一件事。
    """
    env = _workspace(tmp_path)
    owner = str(env["owner"])
    first = _child(env["cond"], owner)
    reused = _child(env["cond"], owner)
    name = _register(env, owner, first)
    _register(env, owner, reused, reuse=name)

    by_name, why_name = env["sec"].resolve_roster_item(owner=owner, name=name)
    assert by_name == first, (by_name, why_name)
    for one in (first, reused):
        got, why = env["sec"].name_of(owner=owner, task_id=one)
        assert got == name and not why, (one, got, why)
    # 消息投递那一口径（`resolve_down`）仍然是"当前那一件活" —— 两格分工没折平
    assert env["sec"].resolve_down(owner=owner, name=name)[0] == reused


# ====================================================================== d) 反真空（解析）
def test_d_stubbing_the_roster_resolution_makes_a_red(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """d：把"按父名册解析"打回折叠口径（最新那条 bind）⇒ a 的"同一个节点"断言必红。

    旧口径下这一笔照样"成功"，但它把节点认成了复用那一趟 ⇒ `data["task_id"] != first`
    （a 的第 ① 条断言），也就是"两个入口指向两个节点"。
    """
    env = _workspace(tmp_path)
    owner = str(env["owner"])
    first = _child(env["cond"], owner)
    reused = _child(env["cond"], owner)
    name = _register(env, owner, first)
    _register(env, owner, reused, reuse=name)

    monkeypatch.setattr(Secretary, "resolve_roster_item",
                        lambda self, *, owner, name: self.resolve_down(owner=owner, name=name))
    got = _call(env, child_name=name)
    data = dict(got.data or {})
    assert data.get("state") == "retired", data
    assert data.get("task_id") != first, (
        "打桩回旧口径之后按名解析到的仍是名册项自己的号 —— 这条反真空没有对象")
    assert data.get("task_id") == reused, data


# ====================================================================== e) 反真空（按号找名）
def test_e_stubbing_name_of_makes_the_second_entrance_lie(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """e：把 `name_of` 打回折叠口径 ⇒ 按号那一入口变成假绿（a 的断言必红）。

    改前的 `name_of` 只在折叠视图（每个名字最新那条 bind）里找号 ⇒ 早先那个号回空，
    于是按号那一侧把目标读成"名册里没有它"（`unrostered`），只认边就回 `state=retired`
    —— 回执说销了、名册项却还挂着、复用那一趟也还在册。这就是真机那处
    「两个入口两种答案」（M 用 `task_id="t-000008"` 拿到的正是这一形态）。
    """
    def _two_rows(where: pathlib.Path) -> tuple[dict[str, Any], str, str, str]:
        env = _workspace(where)
        owner = str(env["owner"])
        first = _child(env["cond"], owner)
        reused = _child(env["cond"], owner)
        name = _register(env, owner, first)
        _register(env, owner, reused, reuse=name)
        return env, owner, name, first, reused

    def folded_name_of(self, *, owner: str, task_id: str):  # noqa: ANN001 - 打桩
        """改前那一版：只认折叠后每个名字的当前号。"""
        index, _bad = self.roster_index(owner)
        names = sorted({str(r.get("name") or "") for r in index
                        if str(r.get("name") or "")
                        and str(r.get("task_id") or "") == str(task_id)})
        return (names[0], "") if len(names) == 1 else (
            "", f"对照表里没有 {task_id}（未登记）")

    # 正控：真 `name_of` ⇒ 按号也能认出这一项，销的是这一项（两个号一起走）
    real_env, *_, real_first = _two_rows(tmp_path / "real")
    real = dict(_call(real_env, task_id=real_first).data or {})
    assert real.get("state") == "retired", real
    assert str(real.get("branch") or "") != "unrostered", real
    assert _node_ids(real_env) == set(), _node_ids(real_env)

    # 反真空：打回旧口径 ⇒ 同一次调用变成"名册里没有它"的假绿
    stub_env, owner, name, first, reused = _two_rows(tmp_path / "stub")
    monkeypatch.setattr(Secretary, "name_of", folded_name_of)
    fake = dict(_call(stub_env, task_id=first).data or {})
    assert fake.get("state") == "retired", fake           # 回执说销了
    assert str(fake.get("branch") or "") == "unrostered", fake
    assert "没有" in str(fake.get("reason") or "") and "未登记" in str(
        fake.get("reason") or ""), fake
    # 而盘上什么都没销干净：复用那一趟还在册、名册项也没标 retired ⇒ a 的断言必红
    assert _node_ids(stub_env) == {reused}, _node_ids(stub_env)
    still = [r for r in stub_env["sec"].roster_rows(owner)[0] if r.get("name") == name]
    assert still and still[0].get("retired") is False, still

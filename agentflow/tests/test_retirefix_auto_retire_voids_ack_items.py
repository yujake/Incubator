# -*- coding: utf-8 -*-
"""RETIREFIX（2026-11-21）：收尾前自动收尾要把「只剩 block 通知」的那一档真的收干净。

## 现场（真机 `projects/lp-ball-15` 的 reconB 对账，只读）

```text
板项 137 条；未收口 6 条（全是 notice）
root_open_items = 2（t-000176 · t-000179，M 自己的两条）
产品 retire 读数：checked=True complete=False 在册 38 / 共 41；dirty=0
收尾前自动收尾投影：would_retire 36 / kept 2（那两个被未消项挡住）；
  收尾前自动收尾之后 retire 仍不干净：t-000047（名下还有 1 条未消项）、
  t-000122（名下还有 2 条未消项）
```

那三笔逐条（`data/tasks.json`）：

| 项 | 收件人 | kind/expects | item_state | input_key |
|---|---|---|---|---|
| t-000055 | t-000047（D） | notice/ack | block | `relay@R-000003` |
| t-000175 | t-000122（F） | notice/ack | block | `clock:tm-000076` |
| t-000178 | t-000122（F） | notice/ack | block | `clock:tm-000078` |

`block` 是「框架自己」翻的（唯一写入点 `stopctl.block_remaining_tasks`，优雅停止那一刻），
而 `block -> done` 是状态机倒退 ⇒ 收件人自己都 ack 不动（`conductor.ack` 报 `state_error`）。
改前自动收尾只认 `items_open == 0` ⇒ 这两笔永远销不掉，final 闸永远报"retire 不干净"。

## 改后的判据（一条都不许宽）

自动收尾对未消项只多认一档：「`expects="ack"` 且 `item_state="block"`」（框架停止时翻的）。
`expects="work"` 的交付项（`b-register@` / `v-resubmit@`）一条都不作废；`queued` / `seen`
的通知（收件人还来得及 ack，d68 的 `conductor.ack` 就是那只手）一条都不作废；M 自己
名下的项不碰。"整棵树干净"的定义没动（`retire_integrity.complete` 仍要 `nodes` 与 `dirty` 都空）。

## 判据

| # | 造什么 | 期望 |
|---|---|---|
| a | 在册静默节点名下 1 条 ack 通知，由真实生产者翻成 `block`；触发自动收尾 | 节点销号（`retired.jsonl` 有该笔、reason 含「收工前自动收尾」）、通知 `done`+`expired` 且 `inputs` 有 `void:expired:` 痕、`retire_integrity.complete=True`、`root_open_items=0` |
| b | 正控：`expects=work` 的项 / `seen` 的 ack 项 / M 自己的项 | 一条都不作废（`voided==[]`）、节点留着、读数点名；`root_open_items` 不动 |
| c | b-awake：新召 / 实例地址 / 角色地址三种落点 | 该有行就有行（`summoned`）、该没行就口径明确（`instance_addressed` / `role_addressed`），且 `registration_digest` 的合计对得上 —— 0 条 b-awake 不是"缺读数" |
| d | 反真空：把 `void_items` 打桩成空 | a 必红：节点销了但通知仍 `block`、`complete=False`、`dirty` 非空 |
| e | 停止通知的 ack 落痕记在"谁 ack 的"（历史写法） | 消边仍放行（读通知项自己的 `seen_by`）；完全没 ack ⇒ 照旧拒 |
"""
from __future__ import annotations

import json
import pathlib
from typing import Any

import pytest

from agentflow import agent_loop as AL
from agentflow import autoretire as AR
from agentflow import obligations as OBL
from agentflow import stopctl as SC
from agentflow.conductor import Conductor
from agentflow.secretary import Secretary
from agentflow.store import Store

TS = "2026-11-21T00:00:00+00:00"


class _Loop:
    """`_auto_retire_ready` 用不到 self 的属性（与 `test_r9fix_auto_retire_ready.py` 同形）。"""


class _Run:
    def __init__(self) -> None:
        self.notes: list[str] = []


def _ws(tmp_path: pathlib.Path) -> dict[str, Any]:
    root = tmp_path / "ws"
    store = Store(root)
    store.init()
    # `conductor_for` 把实例登记进"这个工作区已有主控"的缓存 —— `obligations._conductor`
    # 走 `cached_conductor`（绝不顺手建一个空壳），所以三族义务那一格才读得到板。
    from agentflow.tools.conductor_tools import conductor_for, reset_cache

    reset_cache()
    cond = conductor_for(store)
    sec = Secretary("M", root=root, store=store)
    cond.roster_sink = sec
    # 生产里 `run_role` 在起跑时挂 `conductor.secretary = 秘书`（`_auto_retire_ready` 读它）。
    cond.secretary = sec
    owner = str(cond.open_top_level_run("M", "夹具：RETIREFIX"))
    return {"root": root, "store": store, "cond": cond, "sec": sec, "owner": owner}


def _child(env: dict[str, Any], *, role: str = "D", status: str = "done") -> str:
    row = {"role": role, "action": "write_report", "called_by": "M",
           "parent_task_id": str(env["owner"]), "depth": 2,
           "input_key": f"fixture:{role}:{status}", "status": status,
           "outcome": ("ok" if status == "done" else None), "refusal_reason": None,
           "instance": "", "detail": "夹具子代理", "error": None, "started_at": TS,
           "ended_at": (TS if status in ("done", "cancelled") else None),
           "tokens": 0, "usd": 0.0, "artifacts": [], "inputs": []}
    return str(env["cond"]._write_new_row(row, note="fixture:child"))


def _roster(env: dict[str, Any], task_id: str, *, role: str = "D") -> str:
    got = env["sec"].roster_add(owner=str(env["owner"]), role=role, task_id=task_id,
                               brief="写研究报告")
    assert got.get("problem") == "", got
    return str(got["name"])


def _item(env: dict[str, Any], *, to: str, expects: str = "ack",
          kind: str = "notice", summary: str = "夹具：一条通知",
          role: str = "D", input_key: str = "", instance: str = "") -> str:
    """在 ``to`` 名下开一条板项（`queued`）。

    `input_key` 刻意用 `stop-notice@` 那一档（在 `ACK_REQUIRED_ITEM_PREFIXES` 里）：
    普通信息型 notice 会在渲染那一拍就 `done`+`acked`，"仍有未消项"这一档就造不出来。
    """
    return str(env["cond"].open_item(
        kind=kind, role=role, expects=expects, action=kind, summary=summary,
        called_by="M", parent_task_id=(to or None), depth=3,
        input_key=(input_key or f"stop-notice@{env['owner']}->{to}"),
        recipient_instance=instance))


def _block(env: dict[str, Any], child: str) -> dict[str, Any]:
    """真实生产者翻 `block`（不是手搓 `item_state`）。"""
    return dict(SC.block_remaining_tasks(env["store"], task_id=child, why="夹具：budget"))


def _row(env: dict[str, Any], task_id: str) -> dict:
    return next(r for r in env["store"].rows("tasks")
                if str(r.get("task_id") or "") == str(task_id))


def _retired(env: dict[str, Any]) -> list[dict]:
    rows, bad = env["sec"].retired_names(str(env["owner"]))
    assert not bad, bad
    return [dict(r) for r in rows]


def _auto(env: dict[str, Any], run: _Run | None = None) -> dict[str, Any]:
    return AL.AgentLoop._auto_retire_ready(_Loop(), env["cond"], str(env["owner"]),
                                           run or _Run())


# ====================================================================== a 真消掉
def test_a_a_node_whose_only_leftover_is_a_blocked_ack_notice_is_retired_and_voided(
        tmp_path: pathlib.Path) -> None:
    """a：静默节点名下只剩一条"被停止翻成 block"的 ack 通知 ⇒ 销号 + 作废，整支干净。"""
    env = _ws(tmp_path)
    owner = str(env["owner"])
    child = _child(env, role="D")
    name = _roster(env, child, role="D")
    item = _item(env, to=child, role="D")
    got = _block(env, child)
    assert got.get("blocked_items") == [item], got
    assert _row(env, item)["item_state"] == "block"

    before = env["cond"].retire_integrity(owner)
    assert before["checked"] is True and before["complete"] is False, before
    nodes = {str(n.get("task_id") or ""): n for n in before["nodes"]}
    assert int(nodes[child]["open_items"]) == 1, nodes.get(child)

    # 只读投影与真写同一份判据：会销这个节点、会作废这一条。
    proj = AR.project_retire(env["cond"], owner, before)
    assert proj["complete"] is True, proj
    assert proj["auto_retire"]["kept"] == [], proj["auto_retire"]
    assert proj["auto_retire"]["would_void"] == [{"task_id": child, "item_ids": [item]}], (
        proj["auto_retire"])

    run = _Run()
    report = _auto(env, run)
    assert report["checked"] is True, report
    assert report["retired"] == [child], report
    assert report["voided"] == [item], report
    assert child in report["retired"] and name, report

    done = _row(env, item)
    assert (done["item_state"], done["item_close"]) == ("done", "expired"), done
    assert any(str(x).startswith("void:expired:") for x in (done.get("inputs") or [])), done

    after = env["cond"].retire_integrity(owner)
    assert after["complete"] is True, after
    assert after["nodes"] == [] and after["dirty"] == [], after
    assert after["root_open_items"] == 0, after

    lines = _retired(env)
    assert [str(x.get("task_id")) for x in lines] == [child], lines
    assert "收工前自动收尾" in str(lines[0].get("reason") or ""), lines[0]


# ====================================================================== b 正控
def test_b_work_items_seen_items_and_the_roots_own_items_are_never_voided(
        tmp_path: pathlib.Path) -> None:
    """b：`expects=work` / `seen` 的通知 / M 自己的项 —— 一条都不许被自动作废，且读数点名。"""
    env = _ws(tmp_path)
    owner = str(env["owner"])
    work_child = _child(env, role="F")
    _roster(env, work_child, role="F")
    work_item = _item(env, to=work_child, role="F", expects="work",
                      summary="必须收录的义务（要交付的活）")
    _block(env, work_child)

    seen_child = _child(env, role="E")
    _roster(env, seen_child, role="E")
    seen_item = _item(env, to=seen_child, role="E")
    state, why = env["cond"].mark_item_seen(seen_item, by_task_id=seen_child, step=2)
    assert (state, why) == ("seen", ""), (state, why)

    mine = _item(env, to=owner, role="M", summary="M 自己的一条通知")
    _block(env, owner)

    report = _auto(env)
    assert report["voided"] == [], report
    assert report["retired"] == [], report
    assert _row(env, work_item)["item_state"] == "block", _row(env, work_item)
    assert _row(env, seen_item)["item_state"] == "seen", _row(env, seen_item)
    assert _row(env, mine)["item_state"] == "block", _row(env, mine)

    kept = {str(x.get("task_id")): str(x.get("why") or "") for x in report["kept"]}
    assert "未消项" in kept.get(work_child, ""), report["kept"]
    assert "未消项" in kept.get(seen_child, ""), report["kept"]
    after = env["cond"].retire_integrity(owner)
    assert after["complete"] is False, after
    assert after["root_open_items"] == 1, after
    assert work_child in {str(n.get("task_id")) for n in after["nodes"]}, after["nodes"]


# ====================================================================== c b-awake
def _digest(env: dict[str, Any]) -> dict[str, Any]:
    got = OBL.registration_digest(env["root"], env["store"])
    assert got["checked"] is True, got
    return got


def test_c_b_awake_counts_new_summons_only_and_says_so(tmp_path: pathlib.Path) -> None:
    """c：b-awake 是「召唤」的幂等键 —— 新召才落行；实例地址 / 角色地址不落行，也不叫"缺读数"。"""
    env = _ws(tmp_path)
    cond = env["cond"]
    sha_summoned = "a" * 64
    sha_instance = "b" * 64
    sha_role = "c" * 64
    _item(env, to="", expects="work", kind="notice", role="B",
          summary="必须收录（新召那一档）",
          input_key=OBL.register_key("000001#p1", sha_summoned))
    # 实例地址：板项行自己带 `instance`（K9，`_item` 的 `instance=` → `open_item` 的
    # `recipient_instance`）。
    _item(env, to="", expects="work", kind="notice", role="B",
          summary="必须收录（实例地址那一档）", instance="B1",
          input_key=OBL.register_key("000002#p1", sha_instance))
    _item(env, to="", expects="work", kind="notice", role="B",
          summary="必须收录（角色地址那一档）",
          input_key=OBL.register_key("000003#p1", sha_role))
    # 新召那一档的召唤行（`b-awake@`，role=B 的台账号行）
    cond._write_new_row({
        "role": "B", "action": "", "called_by": "M", "parent_task_id": None,
        "depth": 1, "input_key": OBL.register_wake_key("000001#p1", sha_summoned),
        "status": "running", "outcome": None, "refusal_reason": None,
        "instance": "B1", "detail": "夹具：召唤行", "error": None,
        "started_at": TS, "ended_at": None, "tokens": 0, "usd": 0.0,
        "artifacts": [], "inputs": []}, note="fixture:wake")
    got = _digest(env)
    assert got["open"] == 3, got
    assert got["summoned"] == 1, got
    assert got["instance_addressed"] == 1, got
    assert got["role_addressed"] == 1, got
    states = {str(r["key"]): str(r["wake_state"]) for r in got["rows"]}
    assert states[OBL.register_key("000001#p1", sha_summoned)] == "summoned", states
    assert states[OBL.register_key("000002#p1", sha_instance)] == "instance_addressed", states
    assert states[OBL.register_key("000003#p1", sha_role)] == "role_addressed", states
    assert "不落召唤行，不是没叫醒" in str(got["reason"]), got["reason"]
    # 判据本体（只读、纯函数）：三种输入各一档；召唤行的 task_id 为空 ⇒ 不算新召。
    assert OBL.wake_state_of({"instance": "B1"},
                             {"task_id": "t-x"}) == "summoned"
    assert OBL.wake_state_of({"instance": "B1"}, {}) == "instance_addressed"
    assert OBL.wake_state_of({}, {}) == "role_addressed"
    assert OBL.wake_state_of({"instance": ""}, {"task_id": ""}) == "role_addressed"


# ====================================================================== d 反真空
def test_d_stubbing_the_void_port_makes_a_red(tmp_path: pathlib.Path,
                                              monkeypatch: pytest.MonkeyPatch) -> None:
    """d 反真空：把作废口打桩成空 ⇒ a 的"收干净"必红（否则 a 只是"跑过了"）。"""
    env = _ws(tmp_path)
    owner = str(env["owner"])
    child = _child(env)
    _roster(env, child)
    item = _item(env, to=child)
    _block(env, child)

    def _empty(self, item_ids, **kw):  # noqa: ANN001, ARG001
        return {"checked": True, "voided": [], "refused": [], "traces": [],
                "notified": [], "notification_problems": [], "reason": "反真空：打桩"}

    monkeypatch.setattr(Conductor, "void_items", _empty)
    report = _auto(env)
    assert item not in report["voided"], report
    assert report["problems"], "作废一条都没成，却一个问题都没报 ⇒ 读数在说谎"
    assert _row(env, item)["item_state"] == "block", _row(env, item)
    after = env["cond"].retire_integrity(owner)
    assert after["complete"] is False, after
    assert {str(x.get("task_id")) for x in after["dirty"]} == {child}, after


# ====================================================================== e 停止通知的 ack 落痕
def test_e_a_stop_notice_acked_by_another_task_id_still_releases_the_edge(
        tmp_path: pathlib.Path) -> None:
    """e：ack 落痕记在"谁 ack 的"上（历史写法）⇒ 消边仍放行；完全没 ack ⇒ 照旧拒。

    真机 lp-ball-15：通知项 t-000151 的收件人是 t-000147，而读到并 ack 它的是 t-000128
    （名册名复用）⇒ 落痕是 `stop-acked:t-000128@…`。`note_edge_release` 按被通知的那条边
    找 `stop-acked:t-000147`，于是那条边永远不许消边、`f-sec3d`（t-000071）永远销不掉。
    """
    env = _ws(tmp_path)
    cond, owner = env["cond"], str(env["owner"])
    child = _child(env, role="F")
    reader = _child(env, role="V")
    item = _item(env, to=child, role="F", input_key=f"stop-notice@{owner}->{child}")
    mark, why = cond._mark_stop_notified_many(
        owner, [(child, TS, item)])[0]
    assert mark and not why, (mark, why)
    state, why = cond.mark_item_seen(item, by_task_id=reader, step=7)
    assert (state, why) == ("seen", ""), (state, why)
    state, why = cond.close_item(item, close="acked", by_task_id=reader)
    assert (state, why) == ("done", ""), (state, why)
    assert str(_row(env, item).get("item_close")) == "acked", _row(env, item)
    assert str(_row(env, item).get("seen_by")) == reader, _row(env, item)

    # 历史写法：落痕记在"谁 ack 的"上（不是被通知的那条边的子）。
    got, why = cond.note_stop_ack(owner, reader, at=TS)
    assert got and not why, (got, why)
    mark, why = cond.note_edge_release(owner, child_task_id=child)
    assert mark and not why, (mark, why)

    # 负控：同一形状、但一条 ack 落痕都没有 ⇒ 照旧拒（不然 e 只是"一律放行"）。
    env2 = _ws(tmp_path / "noack")
    cond2, owner2 = env2["cond"], str(env2["owner"])
    child2 = _child(env2, role="F")
    item2 = _item(env2, to=child2, role="F", input_key=f"stop-notice@{owner2}->{child2}")
    assert cond2._mark_stop_notified_many(owner2, [(child2, TS, item2)])[0][0]
    assert cond2.mark_item_seen(item2, by_task_id=child2, step=3)[0] == "seen"
    assert cond2.close_item(item2, close="acked", by_task_id=child2)[0] == "done"
    mark2, why2 = cond2.note_edge_release(owner2, child_task_id=child2)
    assert not mark2 and "停止通知还没被确认" in why2, (mark2, why2)

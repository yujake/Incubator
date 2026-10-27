# -*- coding: utf-8 -*-
"""父代理追子代理行为（业主 2026-10-24 裁定，唯一权威）：

「普通代理能追一层，M能想追几层追几层。下层父代理若想监控地下最末端分支行为时可向M请求
 （一般提出的都是d2想看到d4甚至d5，毕竟再往下的层级派不了太深（深度锁：5级））」

## 这一份守的是什么

| 判据 | 守的那件事 | 改前形态（每条都实测红过） |
|---|---|---|
| 01 | 非 M 角色只拿得到一层 | `trace.children` 不存在（`unknown_tool`） |
| 02 | M 沿 parent_task_id 追到第 3、4 层 | `conductor.watch` 不存在（`unknown_tool`） |
| 03 | 非 M 角色拿不到别人的子树 | `table.list("tasks")` 返回全表（绕过路径） |
| 04 | 深看请求走已有上行通道并可逐字查到 | 没有那段"向 M 请求"的指路文本 |
| 05 | 把限深打桩成不限 ⇒ 01 必红（反真空） | 同 01 |
| 06 | 一层视图里点得出被拒次数/类目与真产出 | 同 01 |

## 夹具（一条 5 层链）

`M(top) -> D(d1) -> D(d2) -> B(b3) -> E(e4)`，其中 b3 那一趟有 3 条 `agent_step`
（前两条是被拒：`forbidden_edge` / `depth_exceeded`）、1 条真落到 `experiments` 的行
（`created_by` 就是 b3 的台账号）、1 份交接手稿。所有替身都不联网、零模型调用
（`Conductor(st, policy=None, backend=LocalBackend({}))`）。
"""

from __future__ import annotations

import pathlib
from typing import Any

import pytest

from agentflow import agenttrace as AT
from agentflow import manuscripts as MAN
from agentflow import schema as S
from agentflow import sessions as SS
from agentflow.conductor import Conductor, LocalBackend, calling_as
from agentflow.store import Store
from agentflow.tools import build_registry

SID = "trace-children"


def _child(cond: Conductor, *, role: str, parent: str, depth: int, key: str) -> str:
    """建一条子代理实例行（`kind == ""`）—— 与 `summon` 建的那种行同形。

    为什么不用 `open_item`：它建的是工作项行（`kind` 非空），而业主问的
    "子代理行为"问的是代理这一轴（`tasks` 里两类行，见 `Conductor.tree` 的
    两轴分家）。实例行的建行点是 `_write_new_row`（全仓唯一的新行临界区），
    这里调它而不是自己拼一个 dict 落盘，是为了让键集只有一处口径。
    """
    row = {"role": role, "action": "write_report", "called_by": "M",
           "parent_task_id": parent, "depth": depth, "input_key": key,
           "status": "running", "outcome": None, "refusal_reason": None,
           "instance": "", "detail": f"派给 {role} 的活（{key}）", "error": None,
           "started_at": "2026-10-24T09:00:00+08:00", "ended_at": None,
           "tokens": 0, "usd": 0.0, "artifacts": [], "inputs": []}
    return cond._write_new_row(row, note="start:test")


def _fixture(tmp_path: pathlib.Path) -> dict[str, Any]:
    """造 5 层链 + b3 的步/产出/手稿。返回全部素材（编号都在里面）。"""
    ws = tmp_path / "ws"
    st = Store(ws)
    st.init()
    cond = Conductor(st, policy=None, backend=LocalBackend({}))
    reg = build_registry(store=st, workspace_root=ws, conductor=cond).registry

    top = cond.open_top_level_run("M", "顶层那一趟的活")
    d1 = _child(cond, role="D", parent=top, depth=2, key="d1@1")
    d2 = _child(cond, role="D", parent=d1, depth=3, key="d2@1")
    b3 = _child(cond, role="B", parent=d2, depth=4, key="b3@1")
    e4 = _child(cond, role="E", parent=b3, depth=5, key="e4@1")

    # b3 那一趟的会话记录：一条起趟 + 三条步（两条被拒、一条正常）。
    SS.append(ws, {"kind": "agent_run_start", "role": "B", "task": "b3 那一趟",
                   "task_id": b3, "depth": 4, "summoned_by": "D"}, sid=SID)
    SS.append(ws, {"kind": "agent_step", "role": "B", "index": 0, "shape": "tool",
                   "payload": {"tool": "fs.read"},
                   "result": {"ok": False, "error": "forbidden_edge：D → B 不在策略允许的边里"}},
              sid=SID)
    SS.append(ws, {"kind": "agent_step", "role": "B", "index": 1, "shape": "tool",
                   "payload": {"tool": "table.create"},
                   "result": {"ok": False, "error": "depth_exceeded：链深超过上限"}}, sid=SID)
    SS.append(ws, {"kind": "agent_step", "role": "B", "index": 2, "shape": "tool",
                   "payload": {"tool": "fs.stat"}, "result": {"ok": True}}, sid=SID)

    # 一条真的落到 experiments 的行：`created_by` 就是 b3 的台账号（最强的那种署名）。
    with st.tx("experiments", actor="B", note="fixture:b3-product") as tx:
        tx.upsert("experiments", {
            "experiment_id": S.format_id(1),
            "claim": "b3 真跑过一次",
            "claim_key": "b3-fixture",
            "method": "numeric",
            "result": "supports",
            "negation_kind": "not_proved",
            "created_by": b3,
            "created_at": "2026-10-24T10:00:00+08:00",
        })

    MAN.write(ws, sender="B", recipient="M", summary="b3 收工：链路读数已交",
              body="正文（夹具用）", task_id=b3, sid=SID)

    return {"ws": ws, "st": st, "cond": cond, "reg": reg, "top": top,
            "d1": d1, "d2": d2, "b3": b3, "e4": e4}


def _as(ws: pathlib.Path, task_id: str, role: str, parent_task_id: str = "",
        parent_role: str = ""):
    """以某个实例的身份跑一段（生产路径上由 `AgentLoop._do_tool` 挂，判据里显式挂）。"""
    return calling_as(str(task_id), role, parent_task_id=str(parent_task_id),
                      parent_role=parent_role, session_root=str(ws), sid=SID)


def _children(res: Any) -> dict[str, Any]:
    assert res.ok, res.to_dict()
    return res.data


def _assert_one_layer(res: Any, *, only_child: str, must_not: str) -> None:
    """01 与 05 共用的断言（05 打桩之后同一段断言必须变红）。"""
    data = _children(res)
    ids = {c["task_id"] for c in data["children"]}
    assert ids == {only_child}, ("非 M 角色只许看直接下级：", ids, res.to_dict())
    assert must_not not in ids, ("更深那一层不许出现：", ids)
    assert data["depth_granted"] == 1, data["depth_granted"]
    assert data["one_layer_only"] is True, data
    note = data["deeper"]["note"]
    assert "向 M 请求" in note, ("只给一层时必须说明更深怎么请求：", note)
    assert data["deeper"]["tool"] == "conductor.escalate", data["deeper"]
    assert "conductor.escalate(" in data["deeper"]["call"], data["deeper"]


# ============================================================ 01 一层

def test_01_a_non_conductor_only_traces_one_layer(tmp_path: pathlib.Path):
    """非 M 角色：`trace.children` 只返回直接下级（传 depth=3 仍只有一层）。

    改前红：`trace.children` 不在任何角色的工具面上（`reg.call` 返回
    `kind="unknown_tool"`），01 的第一句断言就炸。
    """
    fx = _fixture(tmp_path)
    with _as(fx["ws"], fx["d2"], "D", fx["d1"], "D"):
        res = fx["reg"].call("trace.children", role="D", depth=3, window=5)
    _assert_one_layer(res, only_child=fx["b3"], must_not=fx["e4"])
    data = _children(res)
    assert data["depth_requested"] == 3, data["depth_requested"]
    assert data["me"]["task_id"] == fx["d2"], data["me"]
    # 四格读数都在（状态 / 最近 N 步 / 被拒 / 产出 / 上一次交接）。
    child = data["children"][0]
    for key in ("status", "outcome", "recent_steps", "refusals", "products",
                "last_handoff"):
        assert key in child, (key, child)
    assert child["recent_steps"]["shown"], child["recent_steps"]
    assert child["last_handoff"]["found"] is True, child["last_handoff"]


# ============================================================ 02 全树

def test_02_the_conductor_watch_reaches_levels_three_and_four(tmp_path: pathlib.Path):
    """M：`conductor.watch` 沿 parent_task_id 追到第 3、第 4 层（5 层链一次看全）。

    改前红：`conductor.watch` 不存在（M 只有 15 件 conductor.*）。
    """
    fx = _fixture(tmp_path)
    res = fx["reg"].call("conductor.watch", role="M", task_id=fx["top"], window=5)
    assert res.ok, res.to_dict()
    rows = res.data["rows"]
    by_id = {r["task_id"]: r for r in rows}
    assert set(by_id) == {fx["top"], fx["d1"], fx["d2"], fx["b3"], fx["e4"]}, by_id
    assert by_id[fx["d2"]]["level"] == 2, by_id[fx["d2"]]
    assert by_id[fx["b3"]]["level"] == 3, by_id[fx["b3"]]
    assert by_id[fx["e4"]]["level"] == 4, by_id[fx["e4"]]
    assert res.data["depth_reached"] == 5, res.data["depth_reached"]
    # 截断那一档也是活的：depth=3 只到第 3 层（d2），b3/e4 不在里面。
    cut = fx["reg"].call("conductor.watch", role="M", task_id=fx["top"], depth=3)
    assert cut.ok, cut.to_dict()
    cut_ids = {r["task_id"] for r in cut.data["rows"]}
    assert fx["d2"] in cut_ids and fx["b3"] not in cut_ids, cut_ids
    assert cut.data["truncated"] is True, cut.data
    # 与台账那一份父子链同集（两份读数不许分家）。
    assert set(by_id) == {str(r.get("task_id")) for r in fx["cond"].tree(fx["top"])}


# ============================================================ 03 全表读不到

def test_03_a_non_conductor_cannot_read_the_whole_tasks_table(tmp_path: pathlib.Path):
    """非 M 角色拿不到全树：`table.list("tasks")` 只给自己的子树那一层。

    改前红：`table.list("tasks")` 返回全表（d2 能看到 top 与 e4），这条断言必红。
    """
    fx = _fixture(tmp_path)
    with _as(fx["ws"], fx["d2"], "D", fx["d1"], "D"):
        listed = fx["reg"].call("table.list", role="D", table="tasks")
        got = fx["reg"].call("table.get", role="D", table="tasks", id=fx["e4"])
    assert listed.ok, listed.to_dict()
    ids = {str(r["task_id"]) for r in listed.data["rows"]}
    assert ids == {fx["d2"], fx["b3"], fx["d1"]}, (
        "非 M 的可见面 = 自己 + 直接下级 + 自己的父：", ids)
    assert fx["e4"] not in ids and fx["top"] not in ids, ("别人的子树/树顶不许出现：", ids)
    assert got.ok and got.data is None and got.meta.get("found") is False, got.to_dict()
    # 没有身份时 fail-closed（不是"按全表兜底"）。
    anon = fx["reg"].call("table.list", role="D", table="tasks")
    assert not anon.ok and "台账号" in str(anon.error), anon.to_dict()


# ============================================================ 04 上行请求

def test_04_the_deep_watch_request_goes_up_the_existing_channel(tmp_path: pathlib.Path):
    """非 M 角色发起深看请求 ⇒ 到 M 的那条上行通道上逐字查得到。

    通道是已有的 `conductor.escalate`（不新造一条边）：d1 的召唤者是 M，于是请求
    直接落进 M 的收件箱；`agent_escalation` 那一行留了 from/to 与 need 原文。
    改前红：`trace.children` 的 `deeper` 指路文本不存在（第一段断言就炸）。
    """
    fx = _fixture(tmp_path)
    with _as(fx["ws"], fx["d2"], "D", fx["d1"], "D"):
        hint = _children(fx["reg"].call("trace.children", role="D", depth=9))
    assert "conductor.escalate" in hint["deeper"]["call"], hint["deeper"]

    need = "深看请求：请 M 用 conductor.watch 看 d2 下面第 4、5 层在做什么"
    with _as(fx["ws"], fx["d1"], "D", fx["top"], "M"):
        sent = fx["reg"].call("conductor.escalate", role="D", need=need, kind="other")
    assert sent.ok and sent.data.get("state") == "escalated", sent.to_dict()
    events, problems = SS.read_session(fx["ws"], sid=SID)
    assert not problems, problems
    msgs = [e for e in events
            if e.get("kind") == "agent_message" and str(e.get("to") or "") == "M"]
    assert msgs, "M 的收件箱里没有这一条（上行通道没接上）"
    assert any(need in f"{m.get('subject') or ''}{m.get('body') or ''}" for m in msgs), (
        "请求必须逐字到 M 那条上行通道上：", msgs[-1])
    esc = [e for e in events if e.get("kind") == "agent_escalation"]
    assert esc and esc[-1].get("need") == need, esc
    assert esc[-1].get("from_task_id") == fx["d1"], esc[-1]
    assert esc[-1].get("to_task_id") == fx["top"], esc[-1]

    # M 看完之后的指导沿秘书链逐级下来（业主 2026-10-26：只走秘书链、逐级转发）：
    # 正文只交给链尾那一跳的代理；链上其余各跳（M 自己与 d1）一条板项都不该多出来。
    # 发送方身份必须挂上（生产路径由 `AgentLoop._do_tool` 的 `calling_as` 挂）：
    # 没有身份就拼不出"从谁到 d2"那条链，工具会如实报 `no_identity`（没查成）。
    with _as(fx["ws"], fx["top"], "M"):
        guided = fx["reg"].call("conductor.guide", role="M", to=fx["d2"],
                                text="先停掉 E 那一支，把 D 的口径补上再往下派")
    assert guided.ok, guided.to_dict()
    data = guided.data
    assert data["status"] == "delivered", data
    assert data["chain"] == [fx["top"], fx["d1"], fx["d2"]], data["chain"]
    assert data["chain_text"] == f"{fx['top']}->{fx['d1']}->{fx['d2']}", data["chain_text"]
    assert data["delivered_to"] == [fx["d2"]], data["delivered_to"]
    assert [h["content_read"] for h in data["hops"]] == [False, False, True], data["hops"]
    target_items = {str(i.get("task_id"))
                    for i in fx["cond"].open_items_of(fx["d2"])}
    assert data["item_id"] in target_items, (data, target_items)
    assert any("先停掉 E 那一支" in str(i.get("detail") or "")
               for i in fx["cond"].open_items_of(fx["d2"])), data["item_id"]
    for other in (fx["d1"], fx["top"]):
        assert fx["cond"].open_items_of(other) == [], (
            "中间各跳的代理本人不许拿到内容", other,
            fx["cond"].open_items_of(other))


# ============================================================ 05 反真空

def test_05_disabling_the_clamp_makes_the_one_layer_rule_fail(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    """反真空：把 depth 限制打桩成"不限" ⇒ 01 的那段断言必红。

    没有这一条时，01 可能靠"夹具里恰好没有更深的层"变绿 —— 那测的就不是
    "限深"这条规则。这里把 `agenttrace.clamp_depth` 换成"按传入值走"，于是同一个
    调用会返回 b3 与 e4（2 层），01 的断言当场红。
    """
    fx = _fixture(tmp_path)
    monkeypatch.setattr(AT, "clamp_depth", lambda role, depth=None: max(1, int(depth or 1)))
    with _as(fx["ws"], fx["d2"], "D", fx["d1"], "D"):
        res = fx["reg"].call("trace.children", role="D", depth=3)
    data = _children(res)
    ids = {c["task_id"] for c in data["children"]}
    assert fx["e4"] in ids, ("打桩之后必须真的看到更深那一层，否则这条反真空是假的：", ids)
    with pytest.raises(AssertionError):
        _assert_one_layer(res, only_child=fx["b3"], must_not=fx["e4"])


# ============================================================ 06 被拒与真产出

def test_06_refusals_and_products_are_readable_in_the_one_layer_view(
        tmp_path: pathlib.Path):
    """一层视图里点得出被拒次数/类目与真落盘的产出（改前红：工具不存在）。"""
    fx = _fixture(tmp_path)
    with _as(fx["ws"], fx["d2"], "D", fx["d1"], "D"):
        res = fx["reg"].call("trace.children", role="D", window=5)
    child = _children(res)["children"][0]
    ref = child["refusals"]
    assert ref["count"] == 2, ref
    assert ref["by_category"].get("forbidden_edge") == 1, ref
    assert ref["by_category"].get("capacity_refused") == 1, ref
    assert {s["code"] for s in ref["samples"]} == {"forbidden_edge", "depth_exceeded"}, ref
    prod = child["products"]
    assert prod["checked"] is True, prod
    assert prod["tables"]["experiments"]["count"] == 1, prod
    assert prod["tables"]["experiments"]["ids"] == [S.format_id(1)], prod
    assert prod["count"] == 1, prod
    steps = child["recent_steps"]
    assert steps["shown"] and len(steps["shown"]) == 3, steps
    assert steps["shown"][-1]["ok"] is True, steps


# ============================================================ 两份父子谓词必须同集

def test_12_the_two_child_predicates_agree(tmp_path: pathlib.Path):
    """`agenttrace.children_of` 与 `Conductor._children_of` 在同一份台账上同集。

    两份实现的存在理由见 `agenttrace.children_of` 的注释；这条判据让"两边一起改"
    从人的记性变成机器可查的事实。
    """
    fx = _fixture(tmp_path)
    rows = fx["st"].rows("tasks")
    for tid in (fx["top"], fx["d1"], fx["d2"], fx["b3"]):
        mine = {str(r.get("task_id")) for r in AT.children_of(rows, tid)}
        theirs = set(fx["cond"]._children_of(tid))
        assert mine == theirs, (tid, mine, theirs)

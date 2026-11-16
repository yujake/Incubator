# -*- coding: utf-8 -*-
"""S6-b：一件广播能力 —— 广播 = 发给我名下的直接子代理（业主 T20/T21）。

业主逐字（T21）：「现在有没有做每个代理记录名下子代理编号的机制？把 public 约束到这些就对了。这个子代理广播对 M 也是完全一样的做法。M 要广播全树就逐层向下调用即可。」⇒
只有一件能力（`Conductor.broadcast`），所有角色同一个做法；没有 `scope="tree"` 特权档；全树 = 逐层向下（级联是收件人的动作，框架不代它级联）。

2026-11-16 退场（业主逐字「广播工具现在已经被精细的父对子监控替代，目前几乎已无用，全面退场」）：
`conductor.broadcast` 这件工具已从注册表移除、不再进任何角色面；`Conductor.broadcast`
这个方法保留为它下面的管道（退场的是工具面，不是这套语义的实现）。所以下面仍对方法
逐条测（正控 ①② 与三条负控），另加一条面级判据钉住「工具确实不在任何角色面上」。

收件人枚举用 `_children_of`（实例轴，`kind == ""`）—— 板项行的 `parent_task_id` 是"收件人的编号"，把它算成子代理就是两轴混算（S1e 的教训）。

判据（正控 2 / 负控 3 / 面级 1 / 反真空 1）：正控 ① 两个子代理 ⇒ 每人一条 `kind="message"`、`expects="ack"` 的板项，且板项的 `parent_task_id`
是收件人的编号、`role` 是收件人的角色；② 开了几条 / seen 几条 / acked 几条三个读数都在（"展开了"≠"都读到了"）。

负控：① 我名下没有子代理 ⇒ `recipients=[]` + 说清"没有收件人"（不许假装发了）；② 不知道我是谁（没有编号、也没有调用上下文）⇒ 受控拒绝、零写入；
③ 工具面：注册表里没有 `conductor.broadcast`，十一个角色面上也都没有它。

反真空：级联是收件人的动作 —— `cascade` 恒为 `"children_decide"`，框架不许代它转发。"""
from __future__ import annotations

import pathlib
from typing import Any

from agentflow import schema as S
from agentflow.conductor import Conductor, LocalBackend
from agentflow.store import Store
from agentflow.tools import build_registry

SID = "s6b"


def _env(tmp_path: pathlib.Path):
    ws = tmp_path / "ws"
    st = Store(ws)
    st.init()
    cond = Conductor(st, policy=None, backend=LocalBackend({}))
    reg = build_registry(store=st, conductor=cond).registry
    me = cond.open_top_level_run("M", "我这一趟")
    return st, cond, reg, ws, me


def _child(cond: Conductor, parent: str, *, role: str, key: str) -> str:
    return cond._write_new_row({
        "task_id": "", "role": role, "action": "run_once", "called_by": "M",
        "parent_task_id": parent, "depth": 2, "input_key": key, "status": "running",
        "outcome": None, "refusal_reason": None, "instance": "", "detail": "一个子代理",
        "error": None, "started_at": "2026-10-09T00:00:00+08:00", "ended_at": None,
        "tokens": 0, "usd": 0.0, "artifacts": [], "inputs": [],
    }, note="start:%s.run_once" % role)


def _rows(st: Store, ids: list[str]) -> list[dict]:
    want = {str(x) for x in ids}
    return [r for r in st.rows("tasks") if str(r.get("task_id")) in want]


# ------------------------------------------------------------------ 正控

def test_broadcast_opens_one_ack_item_per_child(tmp_path: pathlib.Path):
    """正控①：每个直接子代理一条 `message`/`ack` 板项（挂在收件人自己名下）。"""
    st, cond, _reg, _ws, me = _env(tmp_path)
    kid_d = _child(cond, me, role="D", key="s6b@d")
    kid_e = _child(cond, me, role="E", key="s6b@e")
    # 孙级：不该收到（要它自己的父去转）
    _child(cond, kid_d, role="F", key="s6b@grand")

    got = cond.broadcast(subject="口径更新", body="n<=5 才成立", parent_task_id=me, by="M")
    assert got["checked"] is True and got["ok"] is True, got
    assert sorted(got["recipients"]) == sorted([kid_d, kid_e]), got
    assert len(got["items"]) == 2, got
    assert got["cascade"] == "children_decide", got
    rows = _rows(st, got["items"])
    assert len(rows) == 2, rows
    for row in rows:
        assert str(row.get("kind")) == "message", row
        assert str(row.get("expects")) == "ack", row
        holder = str(row.get("parent_task_id"))
        assert holder in (kid_d, kid_e), row          # 挂在收件人名下
        want_role = "D" if holder == kid_d else "E"
        assert str(row.get("role")) == want_role, row
        assert "n<=5 才成立" in str(row.get("detail")), row
        assert str(row.get("item_state")) == "queued", row
    assert str(_rows(st, [kid_d])[0].get("kind") or "") == "", "子代理那一行不许被写成板项"


def test_the_readings_say_opened_but_not_read(tmp_path: pathlib.Path):
    """正控③ + 反真空：三个读数都在 —— "开了 N 条"不等于"都读到了"。"""
    st, cond, _reg, _ws, me = _env(tmp_path)
    kid_a = _child(cond, me, role="A", key="s6b@a")
    kid_b = _child(cond, me, role="B", key="s6b@b")
    got = cond.broadcast(subject="开工", body="各自收工前写手稿", parent_task_id=me, by="M")
    readings = dict(got.get("readings") or {})
    assert readings.get("opened") == 2, got
    assert readings.get("seen") == 0 and readings.get("acked") == 0, got
    assert readings.get("checked") is True, got

    # 其中一个真的被读进过某一步 ⇒ 再读一次板，读数要跟着变（判据不是"当时打了 0"）。
    # D12（业主 2026-10-27）：广播落在 `kind="message"` 上 ⇒ 信息型，被渲染那一拍
    # 就收口（"seen 就是 ack"，`Conductor._settle_if_informational`）。于是它有两条
    # 可观测的后果：行上是 `done`+`acked`，而板上"未消的项"里不再有它。
    item = str(got["items"][0])
    _state, why = cond.mark_item_seen(item, by_task_id=kid_a, step=1)
    assert not why, why
    rows = {str(r["task_id"]): r for r in st.rows("tasks")}
    assert str(rows[item].get("item_state")) == "done", rows[item]
    assert str(rows[item].get("item_close")) == "acked", rows[item]
    assert str(rows[item].get("seen_by")) == kid_a, rows[item]
    after = cond.board_readings()
    assert after["by_state"]["done"] == 1, after
    assert after["by_close"]["acked"] == 1, after
    left = {str(x["task_id"]) for x in cond.board_view(limit=50)["board_open_items"]}
    assert item not in left, ("已经收口的信息型项还挂在板上（会永久积压并卡销号门）", left)
    assert kid_b and st is not None


def test_the_tool_face_no_longer_has_broadcast(tmp_path: pathlib.Path):
    """负控③之一（面级）：`conductor.broadcast` 已整件退场 —— 注册表里没有它。

    2026-11-16 业主逐字「广播工具…全面退场」⇒ 这一条从「只读角色拿不到」翻成
    「注册表里根本没有」。判据强度没有变松：它仍然是真的读取装配结果。
    """
    _st, _cond, reg, _ws, _me = _env(tmp_path)
    assert "conductor.broadcast" not in {str(n) for n in reg.names()}


def test_the_internal_method_is_kept_as_the_pipe(tmp_path: pathlib.Path):
    """反真空：退场的是工具面，不是方法 —— `Conductor.broadcast` 仍可被内部调用。

    上面三条正控 / 负控就是它的读数；这里只钉住"方法还在"，免得下一轮把它
    连同工具一起删掉时，这套语义的单一实现也跟着消失而没人知道。
    """
    _st, cond, _reg, _ws, _me = _env(tmp_path)
    assert callable(cond.broadcast)


# ------------------------------------------------------------------ 负控

def test_no_children_is_a_readable_zero_not_a_fake_send(tmp_path: pathlib.Path):
    """负控①：我名下没有子代理 ⇒ 如实报 0 + 说清（三态：不是"发出去了"）。"""
    st, cond, _reg, _ws, me = _env(tmp_path)
    got = cond.broadcast(subject="通告", body="正文", parent_task_id=me, by="M")
    assert got.get("recipients") == [] and got.get("items") == [], got
    assert "没有收件人" in str(got.get("note") or ""), got
    assert [r for r in st.rows("tasks") if str(r.get("kind") or "")] == [], "零写入"


def test_without_knowing_who_i_am_it_refuses(tmp_path: pathlib.Path):
    """负控②：不知道我是谁 ⇒ 受控拒绝、零写入（不许猜一个父号）。"""
    st, cond, _reg, _ws, me = _env(tmp_path)
    _child(cond, me, role="D", key="s6b@blind")
    before = len(st.rows("tasks"))
    got = cond.broadcast(subject="通告", body="正文")     # 没有编号、也没有调用上下文
    assert got.get("ok") is False, got
    assert "不知道我是谁" in str(got.get("error") or ""), got
    assert len(st.rows("tasks")) == before, "受控拒绝不许留下半条板项"


def test_every_role_lost_the_broadcast_tool(tmp_path: pathlib.Path):
    """负控③（面级·全角色）：十一个角色面上都没有已退场的 `conductor.broadcast`。

    与上面那条同族、分开写是刻意的：那条守"注册表里没有这件工具"，这条守
    "就算有人把它重新登记，也不会漏给任何一个角色面"。
    """
    _st, _cond, reg, _ws, _me = _env(tmp_path)
    for role in tuple(S.ROLES) + (S.CONDUCTOR_ROLE,):
        names = {str(spec.name) for spec in reg.for_role(role)}
        assert "conductor.broadcast" not in names, (role, sorted(names))

# -*- coding: utf-8 -*-
"""S6-a：公共频道的可见面 = 发信人的直接子代理（业主 T20/T21 附二 乙）。

`draft/86` §14.6 乙：`agent_message` 加一格 `from_task_id`（发信人的实例编号），`read_messages` 按"这一条的 `from_task_id` 是不是我的父"判可见。
于是"任何角色随手`to=#public` 就等于全树广播"这个形态消失（T20 要治的正是它），而"要全树就逐层向下"（T21）由可见面本身保证。

## 判据（正控 3 / 负控 3 / 反真空 2）

正控：① 实例级：父发的公聊，直接子级收得到（`visibility="instance"`）；② 逐层向下：子自己再发公聊 ⇒ 只有它的子级收得到（父反过来收不到）；③ 回执三态：有子代理 ⇒ `queued` 且说明里写清"N
个直接子代理"。

负控：① 发公聊不带台账号 ⇒ 受控拒绝（`no_task_id`）且零写入；② 老消息（没有 `from_task_id`）⇒ 按角色级回退，不许当成全角色可见；③ 不是它子级的读者（孙级 / 不知道自己父是谁的）收不到。

反真空：① 框架档（`by_framework=True`）仍全角色可见 —— 叫停那一份是安全件（工具层手上没有实例号，而听不到叫停的子孙会继续烧钱跑实验），走 `conductor.stop`真跑一次核；② 看不见我名下的子代理
⇒ 回执是 `unknown`，不许猜成 `queued`。
"""
from __future__ import annotations

import pathlib
from typing import Any

from agentflow.agent_loop import (ALL, AgentLoop, public_visibility, read_messages,
                                  send_message)
from agentflow.conductor import Conductor, LocalBackend
from agentflow.store import Store
from agentflow.tools import build_registry

SID = "s6a"


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


def _loop(ws: pathlib.Path, st: Store, cond: Conductor, reg: Any, *, task_id: str = ""):
    loop = AgentLoop(role="M", session_root=ws, registry=reg, seam=None, conductor=cond,
                     store=st, sid=SID, max_steps=1, auto_secretary=False)
    loop.my_task_id = task_id
    return loop


# ------------------------------------------------------------------ 可见面本体

def test_public_visibility_reads_the_sender_instance():
    """正控①（纯函数）：带编号 ⇒ 只有它的直接子级可见；别人一概不可见。"""
    msg = {"from": "M", "from_task_id": "t-0001", "to": ALL}
    assert public_visibility(msg, parent_task_id="t-0001") == (True, "instance")
    assert public_visibility(msg, parent_task_id="t-0002") == (False, "not_my_parent")
    assert public_visibility(msg, parent_task_id="") == (False, "not_my_parent")


def test_an_old_message_falls_back_to_the_role_level_with_a_reading():
    """负控②：老消息（没有 `from_task_id`）按角色级回退，且留读数。

    三态（`draft/86` §14.6 丁）：不许把老消息当成"全角色可见"（那会让老会话继续漏），
    也不许一律不可见（丢历史）—— 回退到"父的角色 == 发信人"，并把 `role_fallback`
    这个读数写在行上。连父角色都不知道 ⇒ 不可见（读数 `unknown_parent`）。
    """
    old = {"from": "M", "to": ALL}
    assert public_visibility(old, parent_role="M") == (True, "role_fallback")
    assert public_visibility(old, parent_role="D") == (False, "unknown_parent")
    assert public_visibility(old, parent_task_id="t-0001") == (False, "unknown_parent")


def test_the_framework_notice_stays_visible_to_everyone(tmp_path: pathlib.Path):
    """反真空①：框架档（叫停那一份）仍然全角色可见 —— 它是安全件。

    真跑一次 `conductor.stop(notify=True)`（工具面那条路）：叫停留言落在公共频道，
    带着 `by_framework=True`，于是任何角色（哪怕不是 M 的子代理）都读得到。
    """
    st, cond, reg, ws, me = _env(tmp_path)
    out = reg.call("conductor.stop", role="M", reason="user", notify=True)
    assert out.ok is True, out
    # 叫停那条留言落在工具那侧看到的会话里（`conductor.stop` 从 backend 的 sid 取，
    # 这个夹具的 backend 没有 sid ⇒ 缺省会话），所以这里按缺省会话读。
    someone, _ = read_messages(ws, "A", sid=None, parent_task_id="t-9999")
    notices = [m for m in someone if str(m.get("subject")) == "叫停"]
    assert notices, ("叫停必须每个角色都收得到（框架档）", someone)
    assert notices[0].get("visibility") == "framework", notices[0]
    assert notices[0].get("by_framework") is True, notices[0]
    assert me and st and cond  # 夹具引用


# ------------------------------------------------------------------ 循环那一层

def test_a_public_message_without_a_task_id_is_refused_with_nothing_written(
        tmp_path: pathlib.Path):
    """负控①：这一趟没有台账号 ⇒ 受控拒绝，且一行都不落。"""
    st, cond, reg, ws, me = _env(tmp_path)
    loop = _loop(ws, st, cond, reg, task_id="")      # 没有台账号
    got = loop._do_message({"to": ALL, "subject": "广播", "body": "随便说点什么"})
    assert got.get("ok") is False and got.get("refused") == "no_task_id", got
    assert "可见面" in str(got.get("error") or ""), got
    events, _ = __import__("agentflow.sessions", fromlist=["x"]).read_session(ws, sid=SID)
    assert not [e for e in events if e.get("kind") == "agent_message"], events
    assert me and cond


def test_the_receipt_says_who_will_read_it(tmp_path: pathlib.Path):
    """正控③ + 反真空②：公聊的回执按"我名下有几个直接子代理"给三态。"""
    st, cond, reg, ws, me = _env(tmp_path)
    loop = _loop(ws, st, cond, reg, task_id=me)
    none_yet = loop._do_message({"to": ALL, "subject": "广播", "body": "没人听"})
    assert none_yet["receipt"] == "no_reader", none_yet
    assert "没有直接子代理" in none_yet["note"], none_yet

    _child(cond, me, role="D", key="s6a@a")
    _child(cond, me, role="E", key="s6a@b")
    some = loop._do_message({"to": ALL, "subject": "广播", "body": "有人听"})
    assert some["receipt"] == "queued", some
    assert "2 个直接子代理" in some["note"], some

    # 看不见子代理（没有 conductor 句柄）⇒ `unknown`，不许猜成 `queued`
    blind = _loop(ws, st, cond, reg, task_id=me)
    blind.conductor = None
    unknown = blind._do_message({"to": ALL, "subject": "广播", "body": "判不了"})
    assert unknown["receipt"] == "unknown", unknown
    assert "不许折成" in unknown["note"], unknown
    assert st is not None


def test_a_private_message_is_unaffected(tmp_path: pathlib.Path):
    """边界（同一处不许改坏）：私聊逐字按老口径，不吃"父是谁"那两格。"""
    st, cond, reg, ws, me = _env(tmp_path)
    _mid, problem = send_message(ws, sender="M", to="D", subject="私聊", body="只给你",
                                sid=SID, from_task_id=me)
    assert not problem, problem
    got, _ = read_messages(ws, "D", sid=SID, parent_task_id="t-不存在")
    assert [m for m in got if str(m.get("subject")) == "私聊"], got
    assert got[0].get("visibility") == "private", got[0]
    other, _ = read_messages(ws, "E", sid=SID, parent_task_id=me)
    assert not [m for m in other if str(m.get("subject")) == "私聊"], other
    assert cond is not None

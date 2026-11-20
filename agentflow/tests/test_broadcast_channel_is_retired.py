# -*- coding: utf-8 -*-
"""BCRETIRE：广播通道（`to=ALL`）退场 —— 只退通道面，读侧兼容一字节不动。

## 业主口径（逐字）

「确认没用的东西就删，不要保留」+「收件人必须是实例（按角色桶归属已废）」。

## 现场（改前取证）

工具面 `conductor.broadcast` 2026-11-16 已退场；通道面还活着：提示词教 `to=ALL`、
`message` / `handoff` 两个写入口都收、落盘 `channel="public"`、读侧据此标
`kind="broadcast"`。这一组把通道面也退了。

## 判据（四格，对应施工单 ④）

- a 写 `to=ALL` ⇒ 受控拒 `broadcast_retired`（`message` 与 `handoff` 两个写入口各一条），
  零写入，拒信带 `how_to_fix`（改前：被接受 —— 落一条 `channel="public"` 的消息）；
- b 写具体实例 ⇒ 照常成功（正控：退的是广播，不是整条留言 / 手稿通道）；
- c 旧数据（带 `to=ALL` / legacy `#public` 的行）仍读得出来，读数标 `broadcast`
  —— 兼容不许破（`_legacy_all` 的读侧折算保留）；
- d 反真空：把 a 的拒打桩掉（`_broadcast_retired_refusal` 恒返回 `{}`）⇒ a 必红。

## 这一组不测什么（如实写清边界）

- 不测 `send_message` 的框架直路（`by_framework=True` 的叫停通报）：它不是代理的收件人面，
  这一批不动它；它的读侧在 c 里以"旧行"形态出现。
- 不测工具面：`conductor.broadcast` 的退场由 `test_broadcast_reaches_my_children.py` 守着。

零模型钱：网关是桩，`Store` / 名册全在 `tmp_path` 里；夹具引
`test_the_handoff_shows_the_absolute_code` 的四层台账 + 名册（不另造一套父子夹具）。
"""
from __future__ import annotations

import pathlib
from typing import Any

import pytest

import test_the_handoff_shows_the_absolute_code as Q2

from agentflow import agent_loop as AL
from agentflow import schema as S
from agentflow import sessions as SS

SID = Q2.SID


def _env(tmp_path: pathlib.Path) -> dict[str, Any]:
    """B（我）+ 父 D + 两个直接子代理 F / A 的台账与名册。"""
    return Q2._env(tmp_path)


# ====================================================================== a 受控拒

def test_a_a_message_to_all_is_refused_as_broadcast_retired(tmp_path: pathlib.Path):
    """判据 a（message 写入口）：`to=ALL` ⇒ `broadcast_retired`，零写入。

    改前红：改前这一条 `ok=True`、落一条 `channel="public"` 的 `agent_message`。
    拒信必须给出路（`how_to_fix`）：点具体实例，或对 M 发。
    """
    env = _env(tmp_path)
    got = env["loop"]._do_message({"to": AL.ALL, "subject": "公告", "body": "全树一句话"})
    assert got.get("ok") is False, got
    assert got.get("refused") == AL.BROADCAST_RETIRED, got
    assert got.get("receipt") == "unknown", got
    fix = str(got.get("how_to_fix") or "")
    assert "实例" in fix and "M" in fix, ("拒信必须给出路（点具体实例 / 对 M 发）：", fix)
    # 零写入：一条 agent_message 都不许落盘
    events, problems = SS.read_session(env["ws"], sid=SID)
    assert not problems, problems
    assert [e for e in events if e.get("kind") == "agent_message"] == [], (
        "受控拒绝不许落半条消息：", events)
    # 小写 / 旧写法同样拒：判据只有一处（`_is_all_recipient`），不是字面量比对
    for spelled in ("all", "#public"):
        again = env["loop"]._do_message({"to": spelled, "subject": "s", "body": "b"})
        assert again.get("refused") == AL.BROADCAST_RETIRED, (spelled, again)


def test_a2_a_handoff_to_all_is_refused_as_broadcast_retired(tmp_path: pathlib.Path):
    """判据 a（handoff 写入口）：`to=ALL` ⇒ `broadcast_retired`，手稿一行不写、留言一条不发。"""
    env = _env(tmp_path)
    got = env["loop"]._do_handoff({"to": AL.ALL, "summary": "广播一份",
                                   "body": "## 正文\n一行。"})
    assert got.get("ok") is False, got
    assert got.get("refused") == AL.BROADCAST_RETIRED, got
    fix = str(got.get("how_to_fix") or "")
    assert "实例" in fix and "M" in fix, ("拒信必须给出路：", fix)
    from agentflow import manuscripts as MS

    assert MS.rows(env["ws"]) == [], "受控拒绝不许写手稿行：%r" % (MS.rows(env["ws"]),)
    events, problems = SS.read_session(env["ws"], sid=SID)
    assert not problems, problems
    assert [e for e in events if e.get("kind") == "agent_message"] == [], (
        "受控拒绝不许发通知留言：", events)


# ====================================================================== b 正控

def test_b_a_concrete_instance_still_works(tmp_path: pathlib.Path):
    """判据 b（正控）：写具体实例 ⇒ 两条通道照常成功（退的是广播，不是通道本身）。"""
    env = _env(tmp_path)
    msg = env["loop"]._do_message({"to": env["f1"], "subject": "一件私事", "body": "正文"})
    assert msg.get("ok") is True, msg
    assert msg.get("refused", "") == "", msg
    hand = env["loop"]._do_handoff({"to": env["f1"], "summary": "一份手稿",
                                    "body": "## 正文\n一行。"})
    assert hand.get("ok") is True, hand
    assert hand.get("refused", "") == "", hand


# ====================================================================== c 旧数据兼容

def test_c_old_rows_with_all_still_read_as_broadcast(tmp_path: pathlib.Path):
    """判据 c（兼容不许破）：旧行（`to=ALL` / legacy `#public`）仍读得出来，读数标 `broadcast`。

    旧行按旧实现落库的形态造（`channel="public"` + `to=ALL`，没有 `by_framework`）——
    这一格量的是"读侧"：`read_messages` 的可见面判据、`_legacy_all` 的折算、
    `message_source` 的类别读数。新写入已不产生这种行（a 守着）。
    """
    env = _env(tmp_path)
    old_rows = [
        {"kind": "agent_message", "msg_id": "m000001", "from": "M", "to": AL.ALL,
         "subject": "旧广播", "body": "旧正文一", "channel": "public",
         "from_task_id": env["me"]},
        {"kind": "agent_message", "msg_id": "m000002", "from": "M", "to": "#public",
         "subject": "更旧的广播", "body": "旧正文二", "channel": "public"},
    ]
    for row in old_rows:
        _path, problem = SS.append(env["ws"], row, sid=SID)
        assert not problem, problem

    # ① 读得出来（子代理按「我父是谁」读得到父发的旧广播）
    mine, problems = AL.read_messages(env["ws"], "F", sid=SID,
                                      parent_task_id=env["me"], parent_role="M")
    assert not problems, problems
    got = {str(m.get("msg_id")): m for m in mine}
    assert set(got) == {"m000001", "m000002"}, sorted(got)
    # ② 旧写法在行上折成规范值（`_legacy_all` 的读侧折算还在）
    assert all(m.get("to") == AL.ALL for m in got.values()), got
    assert got["m000002"].get("visibility") == "role_fallback", got["m000002"]
    # ③ 类别读数照旧：`channel == "public"` ⇒ `broadcast`（这条只由读侧产生）
    assert AL.message_source(got["m000001"])["kind"] == "broadcast", got["m000001"]
    # ④ 读侧判据本身没改：纯函数正控
    assert AL._legacy_all("#public") == AL.ALL
    assert AL._is_all_recipient("#public") is True


# ====================================================================== d 反真空

def test_d_stubbing_the_refusal_makes_a_red(tmp_path: pathlib.Path,
                                           monkeypatch: pytest.MonkeyPatch):
    """判据 d（反真空）：把 a 的拒打桩成"永远不拒" ⇒ a 那一条当场红。

    不复制一份旧实现：把 `_broadcast_retired_refusal` 换成恒返回 `{}`，于是写入口照旧往下走
    （= 改前的行为）⇒ `to=ALL` 又被接受。若 a 仍然绿，说明 a 量的不是这道闸。
    """
    env = _env(tmp_path)
    monkeypatch.setattr(AL, "_broadcast_retired_refusal", lambda **_kw: {})
    again = env["loop"]._do_message({"to": AL.ALL, "subject": "公告", "body": "全树一句话"})
    assert again.get("refused") != AL.BROADCAST_RETIRED, (
        "打桩之后仍然拿到 broadcast_retired ⇒ 这道拒不是那个谓词产生的：", again)
    assert again.get("ok") is True, ("打桩之后应当回到改前的行为（接受）：", again)
    hand = env["loop"]._do_handoff({"to": AL.ALL, "summary": "广播一份", "body": "正文"})
    assert hand.get("refused") != AL.BROADCAST_RETIRED, hand
    assert hand.get("ok") is True, ("打桩之后应当回到改前的行为（接受）：", hand)
    assert S.ROLES, "反真空夹具前提：角色表读得到"

# -*- coding: utf-8 -*-
"""寻址面的读数不许自相矛盾：成功的一步里不许写着「被拒」，名册不可用不许当成不校验。

## 缺陷 1（读数说谎，2026-10-22 查实）

A 把一份手稿交给 B（角色名写法）：B 不在 A 的名册上，而 A 与 B 之间有协作边 ——
手稿写成了、编号有、B 的收件箱真的收到，那一步 `ok is True`；可同一个
`addressing` 里却留着名册探针的结论：

    addressing.refused = "not_in_roster"
    addressing.error   = "B 不在你的名册里（只有父与子能通话）⇒ 受控拒绝…"

走 `ok` 的判据不会因此误判，但事后按 `addressing.refused` 统计「被拒几条」的人会
把成功的一步算进被拒。修法选的是「另起一格」：`addressing` 只讲这一条实际怎么投的，
探针读数原样挪进 `addressing.roster_probe`（`checked` / `how` / `refused` / `error` / `why`）
—— 「为什么这次能发给非名册收件人」这句话不许删掉，它是这一档的正当性理由。

## 缺陷 2（fail-open，2026-10-22 查实）

裸构造的循环（没有台账号，`my_task_id=""`）发一条私聊：名册读不出来 ⇒ 老路照发
（`ok: True`、`receipt: "unknown"`、结果带 `roster_unavailable: True`），`messages_sent`
也把它算成发出去了。生产路径 `run_role` 一定给台账号 ⇒ 这一档只在单测里可达，但
「没有台账号就等于不校验名册」在安全上是 fail-open：业主口径是名册规则只会收紧
（「我们已经双边通话畅通了，就没什么特别的必要要有私聊了」）。

修法：fail-closed —— 台账号读不出 / 名册读不出 ⇒ 私聊一律受控拒绝（理由码沿用
`roster_unavailable`），拒信说清「名册不可用 ⇒ 不投递」；上行（`escalate` 给父）与
手稿的角色级通道不受影响（它们不靠名册，收件人是运行期解析出来的那一个）。

## 这一份守什么（每条改前都红）

1. A 到 B（角色名）的手稿成功 ⇒ `ok is True`、手稿编号有、B 收件箱真的收到，
   而 `addressing` 里没有 `refused` / `error`（探针读数在 `roster_probe` 里）；
2. 真被拒的手稿（名册上没有的名字 / 没有协作边的角色）⇒ `refused` 仍在、且必须读得到
   （修法不许把「失败也不说」一起带进来）；
3. 同一条（3）里 `my_task_id=""` 且名册不可用 ⇒ 私聊被拒 `roster_unavailable`、
   收件箱为空、`messages_sent == []`、`messages_refused` 点名；
4. 同一条（3）里给父的上行（`escalate`）与手稿的角色级通道仍然可用
   （正控：收紧不许把整条通信掐死）；
5. 反真空：把缺陷 1 的修法 monkeypatch 回「不清空」⇒ 判据 1 必红；把缺陷 2 的
   fail-open monkeypatch 回去 ⇒ 判据 3 必红。

零模型：替身网关照剧本回答，价格 0；父子那一套装配直接引用
`tests/test_children_and_parent_are_visible.py`（`_tree` / `_loop` / `_Gate`），
不另造一对父子夹具、不新造通道。
"""
from __future__ import annotations

import json
import pathlib
from typing import Any

import pytest

import test_children_and_parent_are_visible as TCP

from agentflow import agent_loop as AL
from agentflow import manuscripts as MS
from agentflow.agent_loop import read_messages

#: 与夹具同一个会话号（收件箱/手稿都按它归口）。
SID = TCP.SID


def _say(obj: dict[str, Any]) -> str:
    return json.dumps(obj, ensure_ascii=False)


def _env(tmp_path: pathlib.Path) -> dict[str, Any]:
    """A 那一趟 + 一个空名册：B 是我叫得应的角色，却不在我的名册上（缺陷 1 的现场）。

    名册只登记了「父」（由台账换算出来，M 那一行），子代理一个都没登记 ——
    所以按角色名 `B` 问名册得到的是探针的 `not_in_roster`，而协作边（A 能叫 B）
    仍然成立：这一档本来就是「角色级投递」的正当形态。
    """
    st, cond, reg, ws, me, kids, other = TCP._tree(tmp_path, role="A")
    loop = TCP._loop(cond, reg, ws, st, TCP._Gate([_say({"final": "收工", "evidence": []})]),
                     role="A")
    loop.my_task_id = me
    view = loop.secretary.roster_view(owner=me)
    assert view["checked"] is True and view["rows"] == [], view
    return {"st": st, "cond": cond, "reg": reg, "ws": ws, "me": me, "kids": kids,
            "other": other, "loop": loop}


# ============================================================ 判据 1：成功的一步里没有「被拒」

def _a_handoff_to_a_role_outside_the_roster_is_clean(env: dict[str, Any]) -> None:
    """判据 1：A 到 B（角色名）的手稿成功 ⇒ 读数里不许有 `refused` / `error`。

    改前必红：`ok is True`、手稿编号有、B 收件箱真的收到，而 `addressing.refused`
    是探针的 `not_in_roster`、`addressing.error` 是一句「受控拒绝」。
    """
    loop, ws = env["loop"], env["ws"]
    got = loop._do_handoff({"to": "B", "summary": "把手稿交给 B", "body": "正文甲"})
    assert got.get("ok") is True, got
    assert str(got.get("handoff") or ""), ("手稿编号得有", got)

    addr = got.get("addressing") or {}
    assert "refused" not in addr, ("成功的一步里不许留着 refused", addr)
    assert "error" not in addr, ("成功的一步里不许留着 error", addr)
    assert str(addr.get("how") or "") == "outside_roster", addr
    assert str(addr.get("delivery") or "") == "role", addr

    # 探针读数一条都不许丢：为什么这次能发给非名册收件人，必须还读得到。
    probe = addr.get("roster_probe") or {}
    assert str(probe.get("refused") or "") == "not_in_roster", ("探针读数丢了", addr)
    assert "B" in str(probe.get("error") or ""), addr
    assert "名册" in str(addr.get("why") or ""), ("成功那一句要讲清这一档不靠名册", addr)

    # 落点：手稿写的是角色 B，通知真的进了 B 的收件箱（读数与行为一起看）。
    rows = [r for r in MS.rows(ws) if str(r.get("to") or "") == "B"]
    assert len(rows) == 1, rows
    assert str(got.get("to") or "") == "B", got
    msgs, problems = read_messages(ws, "B", sid=SID)
    assert problems == [], problems
    assert len(msgs) == 1, ("B 的收件箱必须真的收到那条通知", msgs)
    assert str(got.get("handoff") or "") in str(msgs[0].get("subject") or ""), msgs[0]


def test_a_successful_handoff_never_carries_a_refusal(tmp_path: pathlib.Path):
    """判据 1（正控）：成功的一步与「被拒」不许并存。"""
    _a_handoff_to_a_role_outside_the_roster_is_clean(_env(tmp_path))


# ============================================================ 判据 2：真被拒的仍然说得出拒绝

def _a_refused_handoff_still_says_why(env: dict[str, Any]) -> None:
    """判据 2：真被拒的手稿 ⇒ `refused` 仍在、且必须读得到（两种真拒绝各一条）。

    (a) 名册上没有这个名字（`Z9`）⇒ `handoff_is_role_addressed`；
    (b) 角色级那一支的真拒绝（没有协作边，`V`）⇒ `not_an_edge`。
    两条的 `addressing` 里都必须还留着探针的 `refused` / `error`：修法只清「成功」
    那一档，不许把失败也一起抹平（否则「被拒几条」会从多算变成查不到）。
    """
    loop, ws = env["loop"], env["ws"]
    before = len(MS.rows(ws))

    got = loop._do_handoff({"to": "Z9", "summary": "给谁", "body": "正文甲"})
    assert got.get("ok") is False, got
    assert str(got.get("refused") or "") == "handoff_is_role_addressed", got
    addr = got.get("addressing") or {}
    assert str(addr.get("refused") or "") == "not_in_roster", ("失败那一档的探针读数", addr)
    assert "名册" in str(addr.get("error") or ""), addr
    assert "受控拒绝" in str(got.get("error") or ""), got

    bad = loop._do_handoff({"to": "V", "summary": "给 V", "body": "正文乙"})
    assert bad.get("ok") is False, bad
    assert str(bad.get("refused") or "") == "not_an_edge", bad
    assert str((bad.get("addressing") or {}).get("refused") or ""), (
        "失败那一档不许被「清空」的修法顺手抹掉", bad)

    assert len(MS.rows(ws)) == before, ("受控拒绝不许写手稿", MS.rows(ws))
    assert read_messages(ws, "V", sid=SID)[0] == [], "被拒的手稿不许发出通知"


def test_a_refused_handoff_still_carries_its_reason(tmp_path: pathlib.Path):
    """判据 2（负控的另一半）：真被拒的两档都还读得到理由码。"""
    _a_refused_handoff_still_says_why(_env(tmp_path))


# ============================================================ 判据 3：没有台账号就不许开私聊

def _private_chat_is_refused_without_a_task_id(env: dict[str, Any]) -> None:
    """判据 3：`my_task_id=""` + 名册不可用 ⇒ 私聊受控拒绝，一条都不许落。

    改前必红：那一档退回老路照发（`ok: True`、`receipt: "unknown"`、
    `roster_unavailable: True`），`messages_sent == ["B"]` 而 B 的收件箱里真的有它。
    """
    cond, ws, kids = env["cond"], env["ws"], env["kids"]
    gate = TCP._Gate([_say({"message": {"to": "B", "subject": "私聊", "body": "正文丙"}}),
                      _say({"final": "收工", "evidence": []})])
    loop = TCP._loop(cond, env["reg"], ws, env["st"], gate, role="A")
    run = loop.run("没有台账号的一趟", summoned_by="M", my_task_id="", depth=1)

    step = run.steps[0]
    assert step.shape == "message", step.to_dict()
    res = step.result
    assert res.get("ok") is False, ("名册不可用 ⇒ 私聊不许落成", res)
    assert str(res.get("refused") or "") == "roster_unavailable", res
    assert "名册" in str(res.get("error") or ""), ("拒信要说清名册不可用 ⇒ 不投递", res)
    assert not res.get("message_sent"), res

    assert run.messages_sent == [], run.to_dict()
    refused = run.messages_refused
    assert [(r["to"], r["refused"]) for r in refused] == [("B", "roster_unavailable")], refused

    inbox, problems = read_messages(ws, "B", sid=SID)
    assert problems == [], problems
    assert inbox == [], ("收件箱必须是空的", inbox)
    board = [r for r in cond.open_items_of(kids[0]) if str(r.get("kind")) == "message"]
    assert board == [], ("板项也不许开", board)


def test_without_a_task_id_no_private_chat_is_delivered(tmp_path: pathlib.Path):
    """判据 3（fail-closed）：没有台账号 ⇒ 私聊受控拒绝，收件箱空、回执里点名。"""
    _private_chat_is_refused_without_a_task_id(_env(tmp_path))


# ============================================================ 判据 4：上行与手稿通道不受影响

def _upward_and_handoff_still_work(env: dict[str, Any]) -> None:
    """判据 4：同一个「名册不可用」状态里，上行给父与手稿的角色级通道仍然可用。

    名册规则收紧不许把整条通信掐死：`escalate` 的收件人是运行期解析出来的父
    （结构上就只有一个），手稿的角色级通道靠协作边 —— 它们都不靠名册。
    但读数必须如实：`roster_unavailable` 那一格还在，且成功的一步里同样不许有 `refused`。
    """
    cond, ws, me = env["cond"], env["ws"], env["me"]
    top = str((cond._task(me) or {}).get("parent_task_id") or "")
    assert top, "夹具：我那一行有父（M 那一趟）"
    parent = TCP._item(cond, role="D", parent=top, depth=2, key="addr-reading@parent")

    got = cond.escalate(need="要 lit:0007 的全文", kind="fetch_fulltext", by="A",
                        my_task_id="", parent_task_id=parent, parent_role="D",
                        session_root=str(ws), sid=SID)
    assert got.get("ok") is True and got.get("state") == "escalated", got
    assert got.get("roster_unavailable") is True, ("名册没读成这件事必须还在读数里", got)
    addr = got.get("addressing") or {}
    assert (addr.get("checked"), str(addr.get("how") or "")) == (False, "roster_unavailable"), addr
    assert "refused" not in addr and "error" not in addr, ("成功的一步不许留着「被拒」", addr)
    assert str((addr.get("roster_probe") or {}).get("refused") or "") == "roster_unavailable", addr
    inbox, problems = read_messages(ws, "D", sid=SID)
    assert problems == [], problems
    assert [e for e in inbox if e.get("escalation")], ("父的收件箱里要读得到这条上行", inbox)

    # 手稿的角色级通道：同一档（没有台账号）也写得成、发得出，读数同样不许带 refused。
    bare = TCP._loop(cond, env["reg"], ws, env["st"],
                     TCP._Gate([_say({"final": "收工", "evidence": []})]), role="A")
    bare.my_task_id = ""
    hand = bare._do_handoff({"to": "B", "summary": "交给 B", "body": "正文丁"})
    assert hand.get("ok") is True, hand
    assert str(hand.get("handoff") or ""), hand
    addr2 = hand.get("addressing") or {}
    assert "refused" not in addr2, addr2
    assert str(addr2.get("how") or "") == "outside_roster", addr2
    assert addr2.get("checked") is False, ("名册没读成这件事必须还在读数里", addr2)
    assert str((addr2.get("roster_probe") or {}).get("refused") or "") == "roster_unavailable", addr2
    msgs, problems = read_messages(ws, "B", sid=SID)
    assert problems == [], problems
    assert [m for m in msgs if str(m.get("subject") or "").startswith("手稿")], msgs


def test_the_upward_paths_survive_a_missing_task_id(tmp_path: pathlib.Path):
    """判据 4（正控）：fail-closed 只掐私聊 —— 上行与手稿的角色级通道照旧。"""
    env = _env(tmp_path)
    _private_chat_is_refused_without_a_task_id(env)   # 先钉「私聊确实被拒」
    _upward_and_handoff_still_work(env)               # 再钉「别的通道还通」


# ============================================================ 判据 5：反真空

def test_negctl_the_old_merge_makes_criterion_1_red(tmp_path: pathlib.Path,
                                                    monkeypatch: pytest.MonkeyPatch):
    """反真空（缺陷 1）：把「清空/另起一格」改回「原样合并」⇒ 判据 1 当场红。

    这里的坏实现就是改前那一行：`{**base, **addr}` —— 探针的 `refused` / `error`
    与本次投递的读数混在同一个字典里。
    """
    env = _env(tmp_path)
    monkeypatch.setattr(AL, "delivery_addressing", lambda base, addr: {**base, **addr})
    with pytest.raises(AssertionError):
        _a_handoff_to_a_role_outside_the_roster_is_clean(env)


def test_negctl_the_old_fail_open_makes_criterion_3_red(tmp_path: pathlib.Path,
                                                        monkeypatch: pytest.MonkeyPatch):
    """反真空（缺陷 2）：把 fail-open patch 回去（名册不可用不清 `refused`）⇒ 判据 3 当场红。

    坏实现只做一件事：`how == "roster_unavailable"` 时把 `refused` / `error` 清掉 ——
    这正是改前那一档的形态（读数标着「名册不可用」，而投递照旧）。
    """
    real = AL.roster_addresses

    def fail_open(secretary: Any, *, to: str, owner: str = "",
                  my_task_id: str = "", sender: str = "") -> dict[str, Any]:
        got = real(secretary, to=to, owner=owner, my_task_id=my_task_id, sender=sender)
        if str(got.get("how") or "") == "roster_unavailable":
            got = {**got, "refused": "", "error": ""}
        return got

    monkeypatch.setattr(AL, "roster_addresses", fail_open)
    env = _env(tmp_path)
    with pytest.raises(AssertionError):
        _private_chat_is_refused_without_a_task_id(env)

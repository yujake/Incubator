# -*- coding: utf-8 -*-
"""回执不许说谎：`messages_sent` 只记真的落成的留言，没落成的逐条进 `messages_refused`。

## 这条缺陷的现场（2026-10-22 查实）

`tests/test_agent_faculties.py` 里那条"伙伴之间可以私聊"的判据红了，红的位置不是
"D 与 E 没有协作边"，而是 E 的收件箱是空的。逐步实测那一步：

    step shape=message  payload {"to": "E", ...}
    result = {"message": "未发出", "to": "E", "ok": False, "receipt": "unknown",
              "refused": "not_in_roster", ...}

而 `run.messages_sent == ["E"]`。根因是它只数 `shape == "message"` 的步，不看那一步的
结果 ⇒ 受控拒绝被读成"发成了"。回执是这一趟留给父代理、人和 Web UI 的唯一读数，
它说谎的代价是上游以为"话已经带到了"，于是不再重发、也不再换一条路。

## 这一组守什么

1. 被受控拒（`not_in_roster`）⇒ `messages_sent` 为空，`messages_refused` 点名收件人与理由码；
2. 真发出（父 → 名册上的子）⇒ `messages_sent` 有它、`messages_refused` 为空，
   且收件人那一侧读得到、body 逐字；
3. 公共频道不是特例：同一判据（落成的不进/被拒的不进，方向都按同一个谓词判）；
4. 反真空：把"看结果"的判据换回"只看形状"，第 1 条必须红。

零模型：替身网关照剧本回答，价格 0；父子那一套装配直接引用
`tests/test_children_and_parent_are_visible.py`（不另造一对父子夹具、不新造通道）。
"双边通话真的通"那条正控也在那个文件里（父↔子的可见面逐格有判据）。
"""
from __future__ import annotations

import json
import pathlib
from typing import Any

import test_agent_faculties as TAF
import test_children_and_parent_are_visible as TCP

from agentflow import agent_loop as AL
from agentflow.agent_loop import ALL, board_digest, read_messages, run_role
from agentflow.llmseam import LlmSeam

#: 收工那一格（D 不是主控 ⇒ 每个终态都要给 notify，否则 run.notes 里挂一条 `notify_problem`）。
NOTIFY = {"to": "M", "summary": "收工：见 final",
          "body": "## 结论\n见 final。\n## 依据\n（见这一趟的步骤）\n"}


def _say(obj: dict[str, Any]) -> str:
    return json.dumps(obj, ensure_ascii=False)


def _final() -> str:
    return _say({"final": "收工", "evidence": [], "notify": NOTIFY})


def _run_d_to_e(tmp_path: pathlib.Path) -> tuple[Any, pathlib.Path]:
    """跑一趟 D 想让 E 收到一条私聊（D 的名册上没有 E ⇒ 受控拒绝那一档）。

    装配用的是 `test_agent_faculties.py` 的 `_ws`（同一个工作区 + 主控 + 工具层，
    替身网关，价格 0）—— 不在这里另写一套。
    """
    st, registry, cond, root = TAF._ws(tmp_path)
    gw = TAF.ScriptedGateway([_say({"message": {"to": "E", "subject": "约束",
                                                "body": "只在 n<=5 时成立"}}),
                              _final()])
    run = run_role("D", "把约束告诉 E", store=st, registry=registry, conductor=cond,
                   seam=LlmSeam(role="D", session_root=root, gateway=gw, price=(0.0, 0.0),
                                sid="t"), workspace_root=str(root), sid="t", from_env=False)
    return run, root


# ============================================================ 判据 1：被拒不进 messages_sent

def test_a_controlled_refusal_is_not_counted_as_sent(tmp_path: pathlib.Path):
    """负控（回执不许把"尝试过"读成"发成了"）：`not_in_roster` 那一条一个字都不许进 `messages_sent`。

    改前必红：旧实现只看 `shape == "message"`，于是 `messages_sent == ["E"]`，
    而 E 的收件箱是空的（`read_messages` 返回 `[]`）。
    """
    run, root = _run_d_to_e(tmp_path)
    step = run.steps[0]
    assert step.shape == "message", step.to_dict()
    assert step.result.get("refused") == "not_in_roster", step.result

    assert run.messages_sent == [], run.to_dict()
    refused = run.messages_refused
    assert len(refused) == 1, refused
    assert refused[0]["to"] == "E", refused
    assert refused[0]["refused"] == "not_in_roster", refused
    # 回执态如实：没落盘就是 unknown（不许写成 queued 那种"送到了"的话）
    assert refused[0]["receipt"] == "unknown", refused

    msgs, problems = read_messages(root, "E", sid="t")
    assert msgs == [] and not problems, ("被拒的那一条从来不该出现在 E 的收件箱里：", msgs, problems)


# ============================================================ 判据 2：真发出（父 → 子）

def test_a_message_to_a_roster_child_is_counted_and_readable(tmp_path: pathlib.Path):
    """正控（真落成的那一档）：父发给名册上的子 ⇒ 计数、`messages_refused` 为空、子读得到且 body 逐字。

    装配引用 `test_children_and_parent_are_visible.py` 的 `_tree` + `_loop`（父/子实例行
    与提示词渲染用的是同一套夹具），子先按 `roster_add` 登记进名册 —— 那一格正是名册口径
    要求的那一步，测试里也不许绕开它自己拼一条行。父这一趟取角色 `A`（它的协作边里有 `B`），
    子是 `_tree` 建的那个 `B` 实例：于是 `to="B"` 是一条模型写得出来、也真的投得出去的名字。

    收件人"读得到"的落点：名册私聊投的是收件人名下的板项（`open_item(kind="message")`），
    而收件人读板项的那条路是 `board_digest`（也进它的提示词）。会话级 `read_messages`
    只认 `agent_message` 那一种事件，按名册投的私聊不写那一格 —— 所以这里按真实落点验。
    """
    st, cond, reg, ws, me, kids, _other = TCP._tree(tmp_path, role="A")
    kid = kids[0]
    body = "只在 n<=5 时成立（这一句要逐字回读）"
    gate = TCP._Gate([_say({"message": {"to": "B", "subject": "约束", "body": body}}),
                      _say({"final": "发好了", "evidence": []})])
    loop = TCP._loop(cond, reg, ws, st, gate, role="A")
    got = loop.secretary.roster_add(owner=me, role="B", task_id=kid, brief="第 1 件活")
    assert got["problem"] == "", got

    run = loop.run("把约束告诉子代理", summoned_by="M", my_task_id=me, depth=2)
    assert run.messages_sent == ["B"], run.to_dict()
    assert run.messages_refused == [], run.to_dict()

    items = [r for r in cond.open_items_of(kid) if str(r.get("kind") or "") == "message"]
    assert len(items) == 1, ("收件人名下应当正好一条 message 板项：", items)
    assert body in str(items[0].get("detail") or ""), ("body 要逐字落进收件人的板项：", items[0])
    board, fresh, problems = board_digest(cond, my_task_id=kid)
    assert not problems, problems
    assert body in board, ("收件人读板那条路上要读得到这一句：", board)
    assert str(items[0]["task_id"]) in fresh, (
        "对收件人来说它是一条还没读过的新项（`queued`）—— 不跑子循环，所以它停在这一档：",
        fresh)


# ============================================================ 判据 3：公共频道同一判据

def test_the_public_channel_uses_the_same_receipt_rule(tmp_path: pathlib.Path):
    """正控 + 负控（同一判据，不特判频道）：公聊被拒的不进 `messages_sent`，落成的进。

    ① 公告栏里点名某个名册成员并下指令 ⇒ 受控拒绝 `public_is_not_a_conversation`
       ⇒ 一字不进 `messages_sent`，`messages_refused` 点名这条理由码；
    ② 我名下有两个直接子代理 ⇒ 公聊有读者（`receipt="queued"`、`ok` 真）⇒ 进 `messages_sent`。

    改前必红：①的第一条断言（`messages_sent == []`）在旧实现下是 `["#public"]`。
    """
    # ---- ① 被拒那一档
    st2, cond2, reg2, ws2, me2, kids2, _o2 = TCP._tree(tmp_path / "public_refused")
    gate2 = TCP._Gate([_say({"message": {"to": "#public", "subject": "B1：把这件活做完",
                                        "body": "先跑表"}}),
                       _say({"final": "收工", "evidence": []})])
    loop2 = TCP._loop(cond2, reg2, ws2, st2, gate2)
    got = loop2.secretary.roster_add(owner=me2, role="B", task_id=kids2[0], brief="第 1 件活")
    assert got["problem"] == "", got
    run2 = loop2.run("在公告栏里点名", summoned_by="M", my_task_id=me2, depth=2)
    step2 = run2.steps[0]
    assert step2.result.get("refused") == "public_is_not_a_conversation", step2.result
    assert run2.messages_sent == [], run2.to_dict()
    assert [r["refused"] for r in run2.messages_refused] == \
        ["public_is_not_a_conversation"], run2.messages_refused

    # ---- ② 落成那一档
    st, cond, reg, ws, me, _kids, _other = TCP._tree(tmp_path / "public_ok")
    gate = TCP._Gate([_say({"message": {"to": "#public", "subject": "口径",
                                        "body": "度数 = 去重后的邻居数"}}),
                      _say({"final": "说完了", "evidence": []})])
    run = TCP._loop(cond, reg, ws, st, gate).run("把口径说给名下的人", summoned_by="M",
                                                 my_task_id=me, depth=2)
    first = run.steps[0].result
    assert first.get("receipt") == "queued" and first.get("ok") is True, first
    assert run.messages_sent == [ALL], run.to_dict()
    assert run.messages_refused == [], run.to_dict()


# ============================================================ 判据 4：反真空

def test_the_receipt_rule_is_not_vacuous(tmp_path: pathlib.Path, monkeypatch: Any):
    """反真空：把"看结果"的判据换回"只看形状"，判据 1 当场红。

    不复制一份旧实现，而是把 `_message_landed` 换成恒真（= 旧实现的 `shape == "message"`）：
    于是"被拒的那一条也算发出去了"原样回来 —— `messages_sent == ["E"]`，而 E 的收件箱
    仍是空的。判据 1 的第一条断言与"点名理由码"那两条都会在这里红，所以判据 1 量的
    确实是"那一步的结果"，不是"那一步的形状"。
    """
    monkeypatch.setattr(AL, "_message_landed", lambda result: True)
    run, root = _run_d_to_e(tmp_path)
    assert run.messages_sent == ["E"], ("只按形状数时这里必须是 ['E'] —— 否则判据 1 "
                                        "不是在测'看结果'：", run.to_dict())
    assert run.messages_refused == [], ("恒真谓词下没有一条会被算成'被拒'：",
                                        run.messages_refused)
    msgs, _problems = read_messages(root, "E", sid="t")
    assert msgs == [], ("这一条从来没落过盘：回执照报它发出去，正是那条缺陷：", msgs)

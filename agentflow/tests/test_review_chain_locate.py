# -*- coding: utf-8 -*-
"""R13 的 A 侧两跳（离线）：A 的定位确认（写 `matched`）与它交出去的那一包（结论 + 页码）。

`draft/37` §5.2 把这两跳点成"用户这一条流程的核心"：A 抽文本 → 定位 →
确认这条定理在不在（`matched` 三态 + 页码 + 片段），`none` 不许交给 B；
确认之后要把结论、出处与页码交给下游，下游才知道去查哪一行。

## 2026-10-22 起这条通道换了（名册规则：只有父与子能通话）

改前这四条写的是"伙伴之间可以私聊"那个口径：A 直接
`{"message": {"to": "D"}}` / `{"message": {"to": "B"}}`。名册规则落地后这两条都不成立
（实测：两条都被 `not_in_roster` 拒，`messages_sent` 为空、收件箱一条也没有），
所以这一组按合法通道重写，守的东西不变：

- 回报父（D）：把 D 真的装配成 A 的父（D 召唤 A）。名册通道的落点是收件人名下的
  板项（`channel="roster"`，投递读数里 `item_id` 非空、"已投递到收件人的板"），
  不是角色收件箱；判据因此读 `open_items_of(D)` 与 `board_digest(D)` ——
  这正是 D 那一侧读得到它的形态。
- 交给下游 B：走 `handoff`（手稿通道）。它是角色级投递、由协作边准入
  （`ALLOWED_EDGES["A"] == {"B"}`），`_handoff_address` 的 docstring 逐字写着
  "按名册拒掉会把整条交付链掐死"；私聊 `message` 那一份判据仍只认父与子。
- A→D 的非父子私聊本身留了一条负控（`test_a_non_parent_private_message_...`），
  把"原来那条路走不通"钉住，防止日后有人又把它改回"伙伴私聊"。

守三件事（与改前同）：

1. 写得进去：`literature.matched` 是 A 能在自己面上改的（`table.update`）；
2. 交得出去且带号：交出去的那一包里必须有 `matched` 的结论与页码；
3. 反真空：`matched="mismatch"`（下错了论文）时，A 不许说"定理已确认"，
   也不许把那篇交给 B —— 这一条把 P2 的提示词口径与 P3 的门接起来
   （门的 `contradiction_wrong_paper` 读的就是这一栏，见 `closing._check_contradictions`）。
"""
from __future__ import annotations

import json
import pathlib
from typing import Any

from conftest import TS, sync_counters
from agentflow import agent_loop as AL
from agentflow import manuscripts as MS
from agentflow import schema as S
from agentflow.agent_loop import AgentLoop, LlmBackend, run_role
from agentflow.conductor import Conductor, LocalBackend
from agentflow.llmseam import LlmSeam
from agentflow.store import Store
from agentflow.tools import build_registry

LOOPS: dict[tuple[str, str], dict] = {("A", "run_once"): {}}


class _Scripted:
    """照剧本回答的替身模型（每次取一条，取完重复最后一条）。"""

    spec = type("Spec", (), {"model": "scripted", "api_key": "fake"})()

    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)
        self.prompts: list[str] = []

    def complete(self, prompt: str, *, scope: str = "", system: str | None = None, **kw):
        """记下这一问，回剧本里的下一条。"""
        self.prompts.append(prompt)
        text = self.replies[min(len(self.prompts) - 1, len(self.replies) - 1)]
        return type("Reply", (), {"ok": True, "text": text, "tokens_in": 10, "tokens_out": 10,
                                  "error_detail": "", "error_kind": ""})()


def _store(tmp_path: pathlib.Path):
    """一个已经有文献行的工作区（A 检索完的形态）：台账 + 主控 + 工具面。"""
    st = Store(tmp_path / "ws")
    st.init()
    with st.tx("literature", actor="test") as tx:
        tx.upsert("literature", S.Literature(lit_id="0000", title="Brown 1971", type="J",
                                             summary="室图随机游走", path="0000.pdf",
                                             added_at=TS).to_dict())
    sync_counters(st)
    cond = Conductor(st, policy=None, backend=LocalBackend({}))
    built = build_registry(store=st, conductor=cond, workspace_root=str(st.root))
    return st, cond, built.registry


def _world(tmp_path: pathlib.Path, replies: list[str]):
    """顶趟形态（A 由 M 直接跑，台账里没有父）：工作区 + A 的循环 + 替身模型。"""
    st, cond, reg = _store(tmp_path)
    gw = _Scripted(replies)
    inner = LocalBackend({})
    backend = LlmBackend(inner=inner, loops=LOOPS, session_root=st.root,
                         seam_factory=lambda role: LlmSeam(role=role, session_root=st.root,
                                                           gateway=gw, price=(0.0, 0.0), sid="t"),
                         max_steps=4, store=st, sid="t")
    cond.backend = backend
    backend.conductor = cond
    backend.registry = reg
    return st, cond, reg, gw


def _instance(cond: Conductor, *, role: str, parent: str, depth: int, key: str,
              called_by: str) -> str:
    """建一条"已接手"的代理实例行（`kind == ""`），返回它的绝对编号。

    与 `tests/test_children_and_parent_are_visible.py::_child` 同形，只多一处 `called_by`：
    这一组里 A 是 D 召唤的，而那个夹具写死 `"M"` —— 台账里"谁叫的"与这一趟的提示词
    （`summoned_by="D"`）自相矛盾会误导后来读台账的人。建行仍走同一个临界区
    （`Conductor._write_new_row`：取号与建行在同一把锁里），不自己拼 dict 落盘。
    """
    row = {"task_id": "", "role": role, "action": "write_report", "called_by": called_by,
           "parent_task_id": parent, "depth": depth, "input_key": key,
           "status": "running", "outcome": None, "refusal_reason": None, "instance": "",
           "detail": f"派给 {role} 的活（{key}）", "error": None,
           "started_at": "2026-10-08T22:00:00+08:00", "ended_at": None,
           "tokens": 0, "usd": 0.0, "artifacts": [], "inputs": []}
    return cond._write_new_row(row, note="start:test")


def _tree_world(tmp_path: pathlib.Path, replies: list[str]):
    """父子形态：D 是顶趟，A 是 D 名下的子代理（名册上只有这一对父与子）。

    为什么不用 `run_role("A", ...)`：那条路会自己给 A 开一条顶趟行，台账里 A 就没有父，
    而这一组要测的正是"父与子"这条合法通道。`open_top_level_run("D", ...)` 与
    `_instance(...)` 就是 `run_role("D", ...)` / `summon` 在台账上留下的那两行，
    这里只造行、不替 D 也跑一趟循环。
    """
    st, cond, reg = _store(tmp_path)
    d = cond.open_top_level_run("D", "派 A 去确认这条定理在不在")
    a = _instance(cond, role="A", parent=d, depth=2, key="a@1", called_by="D")
    gw = _Scripted(replies)
    return st, cond, reg, gw, d, a


def _run_a(st, cond, reg, gw):
    """顶趟 A（`run_role`）：A 由 M 直接跑，台账里没有父。"""
    return run_role("A", "确认这条定理在不在，并通知 D", store=st, registry=reg, conductor=cond,
                    seam=LlmSeam(role="A", session_root=st.root, gateway=gw, price=(0.0, 0.0),
                                 sid="t"),
                    workspace_root=str(st.root), sid="t", from_env=False, max_steps=4)


def _run_a_under_d(st, cond, reg, gw, *, a: str, d: str):
    """跑 A 这一趟（父是 D）：直接驱动 A 的循环，不替 D 也跑一趟。"""
    loop = AgentLoop(role="A", session_root=st.root, registry=reg, conductor=cond,
                     seam=LlmSeam(role="A", session_root=st.root, gateway=gw,
                                  price=(0.0, 0.0), sid="t"),
                     store=st, sid="t", max_steps=4)
    return loop.run("确认这条定理在不在，并回报 D", summoned_by="D", my_task_id=a,
                    parent_task_id=d, depth=2)


def _d_board(cond: Conductor, d: str) -> list[dict[str, Any]]:
    """D 名下由 A 发来的那几条 `message` 板项（名册通道的落点就是板项）。"""
    return [it for it in cond.open_items_of(d)
            if str(it.get("kind") or "") == "message"
            and str(it.get("called_by") or "") == "A"]


def test_a_writes_the_match_verdict_through_its_own_tool_face(tmp_path):
    """第 1 跳：A 把定位结论写进文献行（`table.update` 在 A 的面上，写的是受控词表里的值）。"""
    replies = [
        json.dumps({"tool": "table.update",
                    "args": {"table": "literature", "id": "0000", "patch": {"matched": "exact"}},
                    "why": "定位到 Theorem 1.5：题名/年份对得上，正文第 7 页有它"},
                   ensure_ascii=False),
        json.dumps({"final": "已确认：exact（pp. 7-8）", "evidence": ["lit:0000"], "notify": {"to": "M", "summary": "收工：见 final", "body": "## 结论\n见 final。\n## 依据\n（见这一趟的步骤）\n"}},
                   ensure_ascii=False),
    ]
    st, cond, reg, gw = _world(tmp_path, replies)
    run = _run_a(st, cond, reg, gw)
    assert run.stop_reason == "final", run.to_dict()
    assert st.rows("literature")[0]["matched"] == "exact", st.rows("literature")[0]


def test_a_bogus_verdict_cannot_be_written(tmp_path):
    """负控：拼错的结论写不进去（词表在参数期拦，与 `download.status` 同一族）。"""
    replies = [
        json.dumps({"tool": "table.update",
                    "args": {"table": "literature", "id": "0000",
                             "patch": {"matched": "missing"}},
                    "why": "（故意拼一个词表里没有的值）"}, ensure_ascii=False),
        json.dumps({"final": "写不进去就如实说", "evidence": [], "notify": {"to": "M", "summary": "收工：见 final", "body": "## 结论\n见 final。\n## 依据\n（见这一趟的步骤）\n"}}, ensure_ascii=False),
    ]
    st, cond, reg, gw = _world(tmp_path, replies)
    _run_a(st, cond, reg, gw)
    assert st.rows("literature")[0]["matched"] == "", st.rows("literature")[0]


def test_the_handoff_message_carries_the_verdict_and_the_page(tmp_path):
    """第 2 跳：交给 D 的那一包里有结论与页码（R13 判据③的 A 侧）。

    为什么改成这条通道（2026-10-22 名册规则：只有父与子能通话）：改前这里写的是
    A 直接私聊 D —— 那是"伙伴之间可以私聊"那个口径；名册规则落地后 A→D 被
    `not_in_roster` 拒、D 一条也收不到。所以这一条把 D 真的装配成 A 的父（D 召唤 A），
    并读名册通道的落点：父那一侧收到的是挂在自己名下的板项（`channel="roster"`，
    投递读数里 `item_id` 非空、"已投递到收件人的板"），不是角色收件箱 ——
    所以判据从 `inbox_digest` 换成 `open_items_of` / `board_digest`，要守的内容一字不改。
    """
    replies = [
        json.dumps({"tool": "table.update",
                    "args": {"table": "literature", "id": "0000", "patch": {"matched": "exact"}},
                    "why": "确认到了"}, ensure_ascii=False),
        json.dumps({"message": {"to": "D", "subject": "定理已确认",
                                "body": "matched=exact；出处 lit:0000，页码 pp. 7-8；"
                                        "Theorem 1.5 的原文与证明已可交给 B 消化。"}},
                   ensure_ascii=False),
        json.dumps({"final": "已通知 D", "evidence": [], "notify": {"to": "M", "summary": "收工：见 final", "body": "## 结论\n见 final。\n## 依据\n（见这一趟的步骤）\n"}}, ensure_ascii=False),
    ]
    st, cond, reg, gw, d, a = _tree_world(tmp_path, replies)
    run = _run_a_under_d(st, cond, reg, gw, a=a, d=d)
    assert run.stop_reason == "final", run.to_dict()
    # 回执按新口径（2026-10-22：真落成才算发出）：这一条落在 D 的板项上，所以它记 D；
    # 改前这四条一条都没断言过 `messages_sent`，而"被拒也记成发出"正是那条缺陷。
    assert run.messages_sent == ["D"], run.to_dict()
    assert run.messages_refused == [], run.to_dict()
    items = _d_board(cond, d)
    assert len(items) == 1, items
    assert str(items[0].get("expects") or "") == "ack", items[0]
    detail = str(items[0].get("detail") or "")
    assert "matched=exact" in detail and "pp. 7-8" in detail and "lit:0000" in detail, detail
    heard, ids, problems = AL.board_digest(cond, my_task_id=d, window=None)
    assert problems == [], problems
    assert ids, heard
    assert "matched=exact" in heard and "pp. 7-8" in heard and "lit:0000" in heard, heard


def test_a_mismatch_is_not_reported_as_a_confirmed_theorem(tmp_path):
    """反真空：下错了论文时，通知不许说"定理已确认"。

    为什么改成这条通道（2026-10-22 名册规则：只有父与子能通话）：与上一条同因 ——
    A→D 的私聊被 `not_in_roster` 拒，所以把 D 装配成 A 的父、读 D 名下的板项。
    这一条把 P2 的口径与 P3 的门接起来：门的 `contradiction_wrong_paper` 读的就是这一栏。
    判据不判"措辞好不好"（那是语义判断），只判结论栏与消息是否自相矛盾：
    写了 `mismatch` 却在消息里说"已确认" ⇒ A 的话与它自己刚落的那一栏打架。
    """
    replies = [
        json.dumps({"tool": "table.update",
                    "args": {"table": "literature", "id": "0000",
                             "patch": {"matched": "mismatch"}},
                    "why": "下回来的是 2022 年另一篇 CLT 论文，不是 Brown 1971"},
                   ensure_ascii=False),
        json.dumps({"message": {"to": "D", "subject": "命中校验失败",
                                "body": "matched=mismatch：检索回来的不是派活点名的那一篇；"
                                        "不许交给 B，先重取。"}},
                   ensure_ascii=False),
        json.dumps({"final": "已如实通知 D", "evidence": [], "notify": {"to": "M", "summary": "收工：见 final", "body": "## 结论\n见 final。\n## 依据\n（见这一趟的步骤）\n"}}, ensure_ascii=False),
    ]
    st, cond, reg, gw, d, a = _tree_world(tmp_path, replies)
    run = _run_a_under_d(st, cond, reg, gw, a=a, d=d)
    assert st.rows("literature")[0]["matched"] == "mismatch", st.rows("literature")[0]
    assert run.messages_sent == ["D"], run.to_dict()
    assert run.messages_refused == [], run.to_dict()
    items = _d_board(cond, d)
    assert len(items) == 1, items
    assert "mismatch" in str(items[0].get("detail") or ""), items[0]
    heard, ids, problems = AL.board_digest(cond, my_task_id=d, window=None)
    assert problems == [], problems
    assert ids, heard
    assert "mismatch" in heard, heard
    # 措辞上不许出现"已确认"这种把 mismatch 说成找到的说法
    assert "已确认" not in heard, heard


def test_a_hands_the_confirmed_text_to_b(tmp_path):
    """第 3 跳（R13 的最后一跳）：确认之后把原文与页码交给 B 消化。

    为什么改成这条通道（2026-10-22 名册规则：只有父与子能通话）：A→B 不是父子，
    私聊 `message` 会被 `not_in_roster` 拒（B 不在 A 的名册上）；而 A→B 这条协作边
    是有的（`ALLOWED_EDGES["A"] == {"B"}`），框架给角色级投递留的合法通道是
    `handoff`：写一份交接手稿，再给 B 发一条带编号与一句话的留言
    （`_handoff_address` 的 docstring 逐字写着"按名册拒掉会把整条交付链掐死"）。
    所以这一条改走手稿通道、判据改成"B 读得到手稿正文"；要守的东西没变：
    那一份里缺 `lit_id` 或页码，B 就只能去猜该抽哪一篇的哪几页。
    """
    replies = [
        json.dumps({"tool": "table.update",
                    "args": {"table": "literature", "id": "0000", "patch": {"matched": "exact"}},
                    "why": "确认到了"}, ensure_ascii=False),
        json.dumps({"handoff": {"to": "B", "summary": "定理 1.5 已确认，正文交给你",
                                "body": "matched=exact；出处 lit:0000，页码 pp. 7-8；"
                                        "请把 Theorem 1.5 的完整假设与证明逐字摘进 statements，"
                                        "quote_verified 三态要写清。",
                                "refs": ["lit:0000"], "why": "B 要的是能逐字摘录的正文"}},
                   ensure_ascii=False),
        json.dumps({"final": "已交给 B", "evidence": ["lit:0000"], "notify": {"to": "M", "summary": "收工：见 final", "body": "## 结论\n见 final。\n## 依据\n（见这一趟的步骤）\n"}}, ensure_ascii=False),
    ]
    st, cond, reg, gw = _world(tmp_path, replies)
    run = _run_a(st, cond, reg, gw)
    assert run.stop_reason == "final", run.to_dict()
    step = next(s for s in run.steps if s.shape == "handoff")
    assert step.result.get("ok") is True, step.result
    ms_id = str(step.result.get("id") or "")
    assert ms_id, step.result
    # B 的收件箱里是那条通知（编号 + 一句话）；正文在 handoffs 台账里。
    heard, ids, _sent = AL.inbox_digest(st.root, "B", sid="t")
    assert ids, heard
    assert f"手稿 {ms_id}" in heard, heard
    assert "定理 1.5" in heard, heard
    handed = [r for r in MS.rows(st.root) if str(r.get("to") or "") == "B"]
    assert len(handed) == 1, handed
    assert str(handed[0].get("sender") or "") == "A", handed[0]
    body = str(handed[0].get("body") or "")
    for want in ("matched=exact", "lit:0000", "pp. 7-8", "逐字"):
        assert want in body, (want, body)


def test_a_mismatch_is_not_handed_to_b(tmp_path):
    """反真空（P2 口径逐字要求的那一条）：`none`/`mismatch` 时不许交给 B。

    为什么改成这条通道（2026-10-22 名册规则：只有父与子能通话）：改前这里写的是
    A 私聊 D 报 mismatch，而 D 不是 A 的父 —— 那条会被 `not_in_roster` 拒
    （同文件的负控钉着它）。所以这一条也把 D 装配成 A 的父：A 把 mismatch 如实回报给父，
    而"没交给 B"判两条 —— B 的收件箱空，且盘上没有一份发给 B 的手稿。
    这两半必须一起断言：只看"B 的收件箱空"无法区分"没交"与"什么都没做"；
    上一条（`test_a_hands_the_confirmed_text_to_b`）证明同一趟在 exact 时真的交得出去。
    """
    replies = [
        json.dumps({"tool": "table.update",
                    "args": {"table": "literature", "id": "0000",
                             "patch": {"matched": "mismatch"}},
                    "why": "下回来的是另一篇"}, ensure_ascii=False),
        json.dumps({"message": {"to": "D", "subject": "命中校验失败",
                                "body": "matched=mismatch：不许交给 B，先重取。"}},
                   ensure_ascii=False),
        json.dumps({"final": "未交给 B", "evidence": [], "notify": {"to": "M", "summary": "收工：见 final", "body": "## 结论\n见 final。\n## 依据\n（见这一趟的步骤）\n"}}, ensure_ascii=False),
    ]
    st, cond, reg, gw, d, a = _tree_world(tmp_path, replies)
    run = _run_a_under_d(st, cond, reg, gw, a=a, d=d)
    assert run.messages_sent == ["D"], run.to_dict()
    assert run.messages_refused == [], run.to_dict()
    items = _d_board(cond, d)
    assert len(items) == 1, items
    assert "mismatch" in str(items[0].get("detail") or ""), items[0]
    b_heard, b_ids, b_problems = AL.inbox_digest(st.root, "B", sid="t")
    assert b_problems == [], b_problems
    assert b_ids == [], f"mismatch 不许交给 B：{b_heard}"
    assert [r for r in MS.rows(st.root) if str(r.get("to") or "") == "B"] == [], (
        "mismatch 时不许写一份交给 B 的手稿")


def test_a_non_parent_private_message_is_refused_and_never_lands(tmp_path):
    """负控：A→D 这种非父子私聊被 `not_in_roster` 拒，D 一条也收不到。

    为什么需要这一条（2026-10-22 名册规则：只有父与子能通话）：上面几条把"A 回报父 D"
    改成了合法通道；这一条钉住"原来那条路走不通"，防止有人日后又把它改回"伙伴私聊"。
    三件事一起断言，缺一条就只剩一半：

    1. 这一步的读数：`refused="not_in_roster"`、`addressing.how="not_in_roster"`，
       拒信点名 D 并写出"只有父与子能通话"；
    2. 后果：`messages_sent == []` —— 旧期望把尝试当成功（2026-10-22 查实：只看
       `shape == "message"` 会把它数成发出去了），`messages_refused` 逐项点名
       `{to: "D", refused: "not_in_roster", how: "not_in_roster"}`，D 的收件箱一条也没有；
    3. 反真空：同一趟里发给 M 的收工手稿留言读得到 —— "D 收不到"不是"谁都收不到"
       （存储与收件箱读取本身是好的）。
    """
    replies = [
        json.dumps({"tool": "table.update",
                    "args": {"table": "literature", "id": "0000", "patch": {"matched": "exact"}},
                    "why": "确认到了"}, ensure_ascii=False),
        json.dumps({"message": {"to": "D", "subject": "定理已确认",
                                "body": "matched=exact；出处 lit:0000。"}},
                   ensure_ascii=False),
        json.dumps({"final": "已通知 D", "evidence": [], "notify": {"to": "M", "summary": "收工：见 final", "body": "## 结论\n见 final。\n## 依据\n（见这一趟的步骤）\n"}}, ensure_ascii=False),
    ]
    st, cond, reg, gw = _world(tmp_path, replies)
    run = _run_a(st, cond, reg, gw)
    assert run.stop_reason == "final", run.to_dict()
    step = next(s for s in run.steps if s.shape == "message")
    res = step.result
    assert str(res.get("refused") or "") == "not_in_roster", res
    assert str((res.get("addressing") or {}).get("how") or "") == "not_in_roster", res
    error = str(res.get("error") or "")
    assert "D" in error and "只有父与子能通话" in error, error
    assert run.messages_sent == [], run.to_dict()
    refused = run.messages_refused
    assert len(refused) == 1, refused
    assert (refused[0]["to"], refused[0]["refused"], refused[0]["how"]) == \
        ("D", "not_in_roster", "not_in_roster"), refused
    d_heard, d_ids, d_problems = AL.inbox_digest(st.root, "D", sid="t")
    assert d_problems == [], d_problems
    assert d_ids == [], f"受控拒绝不许落进收件箱：{d_heard}"
    m_heard, m_ids, m_problems = AL.inbox_digest(st.root, "M", sid="t")
    assert m_problems == [], m_problems
    assert m_ids, f"同一趟里合法的那一条（给 M 的收工手稿留言）必须读得到：{m_heard}"

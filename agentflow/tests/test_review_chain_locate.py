# -*- coding: utf-8 -*-
"""R13 的 A 侧两跳（离线）：A 的定位确认（写 `matched`）与 A→D 的交接消息。

`draft/37` §5.2 把这两跳点成"用户这一条流程的核心"：A 抽文本 → 定位 →
确认这条定理在不在（`matched` 三态 + 页码 + 片段），`none` 不许交给 B；
确认之后要通知 D（带号与页码），下游才知道去查哪一行。

这一组不接真模型：用一个照剧本回答的替身模型驱动 A 的循环，让它
①通过自己的工具面把 `matched` 写进文献行、②给 D 发一条带号与页码的消息。
守三件事：

1. 写得进去：`literature.matched` 是 A 能在自己面上改的（`table.update`）；
2. 通知带号：交给 D 的消息里必须有 `matched` 的结论与页码；
3. 反真空：`matched="mismatch"`（下错了论文）时，A 的通知不许说"定理已确认"
   —— 这一条把 P2 的提示词口径与 P3 的门接起来（门的 `contradiction_wrong_paper`
   读的就是这一栏，见 `closing._check_contradictions`）。
"""
from __future__ import annotations

import json
import pathlib

from conftest import TS, sync_counters
from agentflow import agent_loop as AL
from agentflow import schema as S
from agentflow.agent_loop import LlmBackend, run_role
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


def _world(tmp_path: pathlib.Path, replies: list[str]):
    """一个已经有文献行的工作区（A 检索完的形态）+ A 的循环。"""
    st = Store(tmp_path / "ws")
    st.init()
    with st.tx("literature", actor="test") as tx:
        tx.upsert("literature", S.Literature(lit_id="0000", title="Brown 1971", type="J",
                                             summary="室图随机游走", path="0000.pdf",
                                             added_at=TS).to_dict())
    sync_counters(st)
    gw = _Scripted(replies)
    inner = LocalBackend({})
    backend = LlmBackend(inner=inner, loops=LOOPS, session_root=st.root,
                         seam_factory=lambda role: LlmSeam(role=role, session_root=st.root,
                                                           gateway=gw, price=(0.0, 0.0), sid="t"),
                         max_steps=4, store=st, sid="t")
    cond = Conductor(st, policy=None, backend=backend)
    backend.conductor = cond
    built = build_registry(store=st, conductor=cond, workspace_root=str(st.root))
    backend.registry = built.registry
    return st, cond, built.registry, gw


def _run_a(st, cond, reg, gw):
    return run_role("A", "确认这条定理在不在，并通知 D", store=st, registry=reg, conductor=cond,
                    seam=LlmSeam(role="A", session_root=st.root, gateway=gw, price=(0.0, 0.0),
                                 sid="t"),
                    workspace_root=str(st.root), sid="t", from_env=False, max_steps=4)


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
    """第 2 跳：交给 D 的消息里带结论与页码（R13 判据③的 A 侧）。"""
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
    st, cond, reg, gw = _world(tmp_path, replies)
    run = _run_a(st, cond, reg, gw)
    assert run.stop_reason == "final", run.to_dict()
    heard, ids, _sent = AL.inbox_digest(st.root, "D", sid="t")
    assert ids, heard
    assert "matched=exact" in heard and "pp. 7-8" in heard and "lit:0000" in heard, heard


def test_a_mismatch_is_not_reported_as_a_confirmed_theorem(tmp_path):
    """反真空：下错了论文时，通知不许说"定理已确认"。

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
                                        "**不许**交给 B，先重取。"}},
                   ensure_ascii=False),
        json.dumps({"final": "已如实通知 D", "evidence": [], "notify": {"to": "M", "summary": "收工：见 final", "body": "## 结论\n见 final。\n## 依据\n（见这一趟的步骤）\n"}}, ensure_ascii=False),
    ]
    st, cond, reg, gw = _world(tmp_path, replies)
    _run_a(st, cond, reg, gw)
    assert st.rows("literature")[0]["matched"] == "mismatch", st.rows("literature")[0]
    heard, ids, _sent = AL.inbox_digest(st.root, "D", sid="t")
    assert ids, heard
    assert "mismatch" in heard, heard
    # 措辞上不许出现"已确认"这种把 mismatch 说成找到的说法
    assert "已确认" not in heard, heard


def test_a_hands_the_confirmed_text_to_b(tmp_path):
    """第 3 跳（R13 的最后一跳）：确认之后把原文与页码交给 B 消化。

    这一跳是整链的接缝：A 那边只认"文献与页码"，B 那边要的是"能逐字摘录的正文"。
    消息里缺 `lit_id` 或页码，B 就只能去猜该抽哪一篇的哪几页 ——
    而 §3 说得很清楚：B 的消化必须交出可回验的文本。
    """
    replies = [
        json.dumps({"tool": "table.update",
                    "args": {"table": "literature", "id": "0000", "patch": {"matched": "exact"}},
                    "why": "确认到了"}, ensure_ascii=False),
        json.dumps({"message": {"to": "B", "subject": "请消化这条定理",
                                "body": "matched=exact；出处 lit:0000，页码 pp. 7-8；"
                                        "请把 Theorem 1.5 的完整假设与证明逐字摘进 statements，"
                                        "quote_verified 三态要写清。"}},
                   ensure_ascii=False),
        json.dumps({"final": "已交给 B", "evidence": ["lit:0000"], "notify": {"to": "M", "summary": "收工：见 final", "body": "## 结论\n见 final。\n## 依据\n（见这一趟的步骤）\n"}}, ensure_ascii=False),
    ]
    st, cond, reg, gw = _world(tmp_path, replies)
    run = _run_a(st, cond, reg, gw)
    assert run.stop_reason == "final", run.to_dict()
    heard, ids, _sent = AL.inbox_digest(st.root, "B", sid="t")
    assert ids, heard
    assert "lit:0000" in heard and "pp. 7-8" in heard, heard
    assert "statement_full" in heard or "逐字" in heard, heard


def test_a_mismatch_is_not_handed_to_b(tmp_path):
    """反真空（P2 口径逐字要求的那一条）：`none`/`mismatch` 时不许交给 B。

    做法与上一条配对：同一个剧本骨架，只把结论换成 `mismatch` 且不发给 B 的消息。
    判据：B 的收件箱空，而 D 的收件箱里有那条如实回报。
    这两半必须一起断言 —— 只看"B 的收件箱空"无法区分"没交"与"什么都没做"。
    """
    replies = [
        json.dumps({"tool": "table.update",
                    "args": {"table": "literature", "id": "0000",
                             "patch": {"matched": "mismatch"}},
                    "why": "下回来的是另一篇"}, ensure_ascii=False),
        json.dumps({"message": {"to": "D", "subject": "命中校验失败",
                                "body": "matched=mismatch：**不许交给 B**，先重取。"}},
                   ensure_ascii=False),
        json.dumps({"final": "未交给 B", "evidence": [], "notify": {"to": "M", "summary": "收工：见 final", "body": "## 结论\n见 final。\n## 依据\n（见这一趟的步骤）\n"}}, ensure_ascii=False),
    ]
    st, cond, reg, gw = _world(tmp_path, replies)
    _run_a(st, cond, reg, gw)
    b_heard, b_ids, _bsent = AL.inbox_digest(st.root, "B", sid="t")
    d_heard, d_ids, _dsent = AL.inbox_digest(st.root, "D", sid="t")
    assert b_ids == [], f"mismatch 不许交给 B：{b_heard}"
    assert d_ids, "但必须如实回报给 D —— 否则'没交'与'什么都没做'分不开"
    assert "mismatch" in d_heard, d_heard

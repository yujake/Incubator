# -*- coding: utf-8 -*-
"""R13 的第 5–6 跳（离线）：B 请不动 E，框架把它转成"请代唤"给 M，M 再派 E。

`draft/37` §5.2 第 3 条把这一格点名为"用户流程里最容易漏的一格"：
`message` 只把话放进对方的收件箱，不会启动对方的循环；而 B 的可召唤边只有
`B → C` ⇒ B 想让 E 做背书，只能走"请代唤"这条路。

这一组守三件事：
1. 转得成：B 的循环里出现一次 `summon E` ⇒ 被边表拒（`forbidden_edge`），
   而框架自动把它转成给 M 的"请代唤"留言（不是静默丢掉）；
2. M 接得住：拿到那条留言之后，M 真的派得动 E（边 `M → E` 在表里）；
3. 反真空：一个本来就允许的召唤（`B → C`）不许产生"请代唤"
   —— 否则"代唤"会变成噪音，而真需要它的时候没人看。
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

LOOPS: dict[tuple[str, str], dict] = {("B", "run_once"): {}}


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


class _StubE:
    """E 的最小替身：让"主控派得动 E"这件事在内层确定性后端上真的有落点。

    （只放一个只读动作：这一组判的是"边通不通、代唤转不转得成"，不是 E 会不会做实验。）
    """

    def list_experiments(self, **kw) -> dict:
        """替身的 handler：回一个最小合法载荷。"""
        return {"outcome": "ok", "detail": "替身 E：读了实验台账", "checked": True,
                "payload": {"experiments": [], "count": 0}}


def _world(tmp_path: pathlib.Path, replies: list[str]):
    st = Store(tmp_path / "ws")
    st.init()
    with st.tx("literature", actor="test") as tx:
        tx.upsert("literature", S.Literature(lit_id="0000", title="Brown 1971", type="J",
                                             summary="室图", path=None, added_at=TS).to_dict())
    sync_counters(st)
    gw = _Scripted(replies)
    inner = LocalBackend({"E": ("object", _StubE())})
    backend = LlmBackend(inner=inner, loops=LOOPS, session_root=st.root,
                         seam_factory=lambda role: LlmSeam(role=role, session_root=st.root,
                                                           gateway=gw, price=(0.0, 0.0), sid="t"),
                         max_steps=4, store=st, sid="t")
    cond = Conductor(st, policy=None, backend=backend)
    backend.conductor = cond
    built = build_registry(store=st, conductor=cond, workspace_root=str(st.root))
    backend.registry = built.registry
    return st, cond, built.registry, gw


def _run_b(st, cond, reg, gw, *, task: str = "请 E 给这条证明做背书"):
    return run_role("B", task, store=st, registry=reg, conductor=cond,
                    seam=LlmSeam(role="B", session_root=st.root, gateway=gw, price=(0.0, 0.0),
                                 sid="t"),
                    workspace_root=str(st.root), sid="t", from_env=False, max_steps=4)


def test_a_forbidden_summon_becomes_a_relay_request_to_the_conductor(tmp_path):
    """第 5 跳：B 够不着 E ⇒ 框架自动转成给 M 的"请代唤"（不是静默丢掉）。"""
    gw_replies = [
        json.dumps({"summon": {"role": "E", "task": "派活：跑一次实验",
                               "params": {"claim": "定理 1.5 的形式化", "claim_key": "thm:1.5",
                                          "script_path": "code/lean/thm.lean"},
                               "why": "要一条 proof 级背书"}}, ensure_ascii=False),
        json.dumps({"final": "已请主控代为召唤 E", "evidence": [], "notify": {"to": "M", "summary": "收工：见 final", "body": "## 结论\n见 final。\n## 依据\n（见这一趟的步骤）\n"}}, ensure_ascii=False),
    ]
    st, cond, reg, gw = _world(tmp_path, gw_replies)
    run = _run_b(st, cond, reg, gw)
    assert run.stop_reason == "final", run.to_dict()
    # `run.summons` 记的是尝试，不是成功 —— 被边表拒的那一次也在里面
    # （这一条是本判据第一次跑时咬出来的：它记 attempts，refused 也有台账行）。
    assert run.summons == ["E"], run.summons
    e_rows = [r for r in st.rows("tasks") if str(r.get("role")) == "E"]
    assert len(e_rows) == 1 and str(e_rows[0]["outcome"]) == "refused", e_rows
    assert str(e_rows[0]["refusal_reason"]) == "forbidden_edge", e_rows[0]
    assert str(e_rows[0]["called_by"]) == "B", e_rows[0]
    relayed = [s for s in run.steps if "代唤" in json.dumps(s.to_dict(), ensure_ascii=False)]
    assert relayed, [s.to_dict() for s in run.steps]
    # M 的收件箱里必须有那条申请，而且它点名了要谁
    heard, ids, _sent = AL.inbox_digest(st.root, "M", sid="t")
    assert ids, heard
    # 2026-10-16（口径 S2 最终形态）：代唤申请现在只点名角色、不点名动作 ——
    # 「action 完全不用父代理填」⇒ 申请里那一格恒为空（`wants_action == ""`）。
    # 原来还断 `"run_experiment" in heard`，那一档已不存在。
    assert "E" in heard, heard
    assert "代唤" in heard, heard


def test_the_conductor_can_then_actually_send_e(tmp_path):
    """第 6 跳：拿到那条留言之后，M 真的派得动 E（`M → E` 在边表里）。"""
    gw_replies = [
        json.dumps({"summon": {"role": "E", "task": "派活：列一遍实验", "params": {},
                               "why": "先看一眼实验台账"}}, ensure_ascii=False),
        json.dumps({"final": "已请主控代唤", "evidence": [], "notify": {"to": "M", "summary": "收工：见 final", "body": "## 结论\n见 final。\n## 依据\n（见这一趟的步骤）\n"}}, ensure_ascii=False),
    ]
    st, cond, reg, gw = _world(tmp_path, gw_replies)
    _run_b(st, cond, reg, gw)
    # B → E 是不是真的没有边（这是"为什么需要代唤"的理由本身）
    from agentflow import capabilities as C

    assert "E" not in C.ALLOWED_EDGES.get("B", ()), C.ALLOWED_EDGES.get("B")
    res = cond.summon("E", "list_experiments", {}, by="M")
    assert res.outcome == "ok", (res.status, res.outcome, res.refusal_reason, res.error)
    # 只数主控派的那一行：B 那次尝试也留了一行（refused），两件事必须分得开
    rows = [r for r in st.rows("tasks")
            if str(r.get("role")) == "E" and str(r.get("called_by")) == "M"]
    assert len(rows) == 1 and str(rows[0]["outcome"]) == "ok", rows
    refused = [r for r in st.rows("tasks") if str(r.get("outcome")) == "refused"]
    assert len(refused) == 1 and str(refused[0]["called_by"]) == "B", refused


def test_an_allowed_summon_does_not_create_a_relay_request(tmp_path):
    """反真空：允许的召唤（`B → C`）不许产生"请代唤" —— 否则代唤会变成噪音。"""
    gw_replies = [
        json.dumps({"summon": {"role": "C", "task": "派活：报最热的几条",
                               "params": {"top_n": 1}, "why": "问一下图里的枢纽"}},
                   ensure_ascii=False),
        json.dumps({"final": "问过 C 了", "evidence": [], "notify": {"to": "M", "summary": "收工：见 final", "body": "## 结论\n见 final。\n## 依据\n（见这一趟的步骤）\n"}}, ensure_ascii=False),
    ]
    st, cond, reg, gw = _world(tmp_path, gw_replies)
    run = _run_b(st, cond, reg, gw)
    assert run.stop_reason == "final", run.to_dict()
    # 判据是"没有代唤申请"（不是"主控收件箱里一条留言都没有"）：收工时的强制 `notify`
    # 本来就会给 M 发一条 `[手稿 NNNN]` 的交接留言 —— 那是应该有的那条。
    messages, problems = AL.read_messages(st.root, "M", sid="t")
    assert not problems, problems
    relays = [m for m in messages if "请代唤" in str(m.get("subject") or "")]
    assert relays == [], f"允许的召唤不该产生代唤申请：{relays}"

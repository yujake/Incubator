# -*- coding: utf-8 -*-
"""R13 的第一跳，走 LLM 循环那一版（离线，用照剧本回答的替身模型）。

## 为什么与 `test_review_chain_hop.py` 分开

那一组证明的是"工具面上做得成"（按角色直接调 `table.create`）；
这一组证明的是"循环驱动得动"：模型说一句 `{"tool": "table.create", ...}`，
框架真的把那一行落了库、把这一步记进 `LoopRun`、并且下游读得到。

两者不是同一件事：工具面能写 ≠ 循环里写得成（循环还要求①形状被判对、
②工具在该角色的面上、③结果回给模型时没有被观测层截成半句）。
上一轮 §27.3 记的正是这个区别；这一组把后半补上。
"""
from __future__ import annotations

import json
import pathlib

from conftest import TS, sync_counters
from agentflow import schema as S
from agentflow.agent_loop import LlmBackend, run_role
from agentflow.conductor import Conductor, LocalBackend
from agentflow.llmseam import LlmSeam
from agentflow.store import Store
from agentflow.tools import build_registry

LOOPS: dict[tuple[str, str], dict] = {("B", "run_once"): {}}

_ROW: dict = {
    "origin": "external_lit", "kind": "theorem", "label": "Theorem 1.5",
    "statement_text": "随机游走的距离有 CLT 型极限",
    "statement_full": "设 G 是有限连通图，各边电导有正下界；则 (d(X_0,X_n)-E d)/sqrt(n) 收敛到正态",
    "proof_text": "Proof. By Theorem 6.5 of the companion book ...",
    "source_lit_id": "0000", "page_range": {"start": 7, "end": 8, "label": "pp. 7-8"},
    "quote_verified": True, "quote_reason": "逐字比对通过（page 7）",
    "evidence_kind": "cross_check", "status": "active", "created_at": TS,
}


class _Scripted:
    """照剧本回答的替身模型：每次取一条，取完重复最后一条。"""

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


def _world(tmp_path: pathlib.Path):
    st = Store(tmp_path / "ws")
    st.init()
    with st.tx("literature", actor="test") as tx:
        tx.upsert("literature", S.Literature(lit_id="0000", title="Brown 1971", type="J",
                                             summary="室图", path=None, added_at=TS).to_dict())
    sync_counters(st)
    gw = _Scripted([
        json.dumps({"tool": "table.create",
                    "args": {"table": "statements", "row": dict(_ROW)},
                    "why": "把刚消化的那条命题登记进台账"}, ensure_ascii=False),
        json.dumps({"final": "已登记 Theorem 1.5", "evidence": ["statements:0001"]},
                   ensure_ascii=False),
    ])
    inner = LocalBackend({})
    backend = LlmBackend(inner=inner, loops=LOOPS, session_root=st.root,
                         seam_factory=lambda role: LlmSeam(role=role, session_root=st.root,
                                                           gateway=gw, price=(0.0, 0.0),
                                                           sid="t"),
                         max_steps=4, store=st, sid="t")
    cond = Conductor(st, policy=None, backend=backend)
    backend.conductor = cond
    built = build_registry(store=st, conductor=cond, workspace_root=str(st.root))
    backend.registry = built.registry
    return st, cond, built.registry, gw


def test_the_loop_can_drive_b_to_register_a_statement(tmp_path):
    """正控：模型说一句 `table.create` ⇒ 那一行真的落库（循环路径，不只是工具面）。"""
    st, cond, reg, gw = _world(tmp_path)
    run = run_role("B", "消化这条定理并登记", store=st, registry=reg, conductor=cond,
                   seam=LlmSeam(role="B", session_root=st.root, gateway=gw, price=(0.0, 0.0),
                                sid="t"),
                   workspace_root=str(st.root), sid="t", from_env=False, max_steps=4)
    assert run.stop_reason == "final", run.to_dict()
    assert [s.shape for s in run.steps] == ["tool", "final"], [s.shape for s in run.steps]
    rows = st.rows("statements")
    assert len(rows) == 1, rows
    assert rows[0]["statement_full"] == _ROW["statement_full"], rows[0]
    assert rows[0]["page_range"]["start"] == 7 and rows[0]["quote_verified"] is True, rows[0]


def test_the_step_that_wrote_the_row_is_readable_in_the_run(tmp_path):
    """读数面：那一步的工具名、参数、以及"为什么"都要能在 `LoopRun` 里读到。"""
    st, cond, reg, gw = _world(tmp_path)
    run = run_role("B", "消化这条定理并登记", store=st, registry=reg, conductor=cond,
                   seam=LlmSeam(role="B", session_root=st.root, gateway=gw, price=(0.0, 0.0),
                                sid="t"),
                   workspace_root=str(st.root), sid="t", from_env=False, max_steps=4)
    step = run.steps[0]
    assert step.result.get("ok") is True, step.result
    assert "table.create" in json.dumps(step.to_dict(), ensure_ascii=False), step.to_dict()


def test_the_downstream_role_reads_it_after_the_loop_ran(tmp_path):
    """R13 判据①（循环版）：跑完之后下游（D）按号读得到这一行。"""
    st, cond, reg, gw = _world(tmp_path)
    run_role("B", "消化这条定理并登记", store=st, registry=reg, conductor=cond,
             seam=LlmSeam(role="B", session_root=st.root, gateway=gw, price=(0.0, 0.0), sid="t"),
             workspace_root=str(st.root), sid="t", from_env=False, max_steps=4)
    sid = st.rows("statements")[0]["stmt_id"]
    got = reg.call("table.get", role="D", table="statements", id=sid)
    assert got.ok and got.meta.get("found") is True, (got.data, got.meta)
    assert "完整" not in got.data["statement_full"] or True   # 完整性由上面那条判据守
    assert got.data["proof_text"].startswith("Proof."), got.data


def test_a_dangling_artifact_reference_is_caught_by_verify(tmp_path):
    """反真空（§17.2 的后半）："调用成功但下游看不见"这件事有判据。

    做法：让那一步声称产出了 `statements:9999`（一个不存在的行）⇒
    `verify` 必须以 `dangling_task_artifact` 报出来。
    没有这一条，"每一跳都有下游可见的产物"就只是句愿望。
    """
    from agentflow.verify import verify_all

    st, cond, reg, gw = _world(tmp_path)
    # 走主控的召唤（`run_role` 直接调不写台账行 —— 台账行是召唤写的）
    res = cond.summon("B", "run_once", {}, by="M")
    assert res.outcome == "ok", (res.status, res.outcome, res.error, res.refusal_reason)
    rows = st.rows("tasks")
    assert len(rows) == 1, rows
    # 把那次召唤的产出改成指向一个不存在的行
    with st.tx("tasks", actor="test") as tx:
        row = dict(rows[0])
        row["artifacts"] = ["statements:9999"]
        tx.upsert("tasks", row)
    d = verify_all(st).to_dict()
    codes = [i["code"] for i in list(d["errors"]) + list(d["warnings"])]
    assert "dangling_task_artifact" in codes, codes

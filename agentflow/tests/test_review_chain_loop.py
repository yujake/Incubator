# -*- coding: utf-8 -*-
"""R13 的第一跳，走 LLM 循环那一版（离线，用照剧本回答的替身模型）。

## 为什么与 `test_review_chain_hop.py` 分开

那一组证明的是"正路在**工具面**上做得成"（B 交内容、秘书落盘，按角色直接调）；
这一组证明的是"**循环驱动得动**"：模型说一句 `{"tool": "own.register_statement", …}`，
框架真的把那一行落了库、把这一步记进 `LoopRun`、并且下游读得到。

两者不是同一件事：工具面能写 ≠ 循环里写得成（循环还要求①形状被判对、
②工具在该角色的面上、③结果回给模型时没有被观测层截成半句）。

## 2026-10-19 晚：这一组换成真机那条派活路径（`projects/mp2` 的读数）

改前这里剧本写的是 `table.create(table="statements")`，而且用 `run_role` 直接起循环 ——
两处都绕开了真机：真机的派活是 **S2 口径的「只派活、不点动作」**（`tasks.action=""`），
走 `LlmBackend.call` 的那条路；而 `table.create` 那条路现在被
`store.direct_write_refusal` 受控拒绝（`mp2-7.jsonl` 第 97 行就是它）。

所以现在：

- 派活走 `backend.call("B", "", {"task": …})`（空动作 = 真机那条路）；
- 剧本喊 `own.register_statement`（这一趟循环里由 `_registry_with_own_action` 注入，
  见 `agent_loop` 那段注释），handler 走 `AgentB.register_statement` 的**真实现**；
- 落盘由秘书完成（`created_by="secretary-B"`），`bits` 由动作现算。

判据本身没有放宽：仍然判"循环里那一行真的落库了、下游按号读得到、
这一步在 `LoopRun` 里读得出来"。
"""
from __future__ import annotations

import json
import pathlib

from conftest import TS, sync_counters
from agentflow import schema as S
from agentflow.agent_b import AgentB
from agentflow.agent_loop import LlmBackend
from agentflow.conductor import Conductor, LocalBackend
from agentflow.llmseam import LlmSeam
from agentflow.store import Store
from agentflow.tools import build_registry

#: `("B", "")` 是真机的形状（只派活、不点动作）；`("B", "run_once")` 给下面那条
#: 「dangling artifact」的判据用（它要走一次**点名动作**的召唤）。
LOOPS: dict[tuple[str, str], dict] = {("B", ""): {"max_steps": 4},
                                     ("B", "run_once"): {"max_steps": 4}}

_ROW: dict = {
    "origin": "external_lit", "kind": "theorem", "label": "Theorem 1.5",
    "statement_text": "随机游走的距离有 CLT 型极限",
    "statement_full": "设 G 是有限连通图，各边电导有正下界；则 (d(X_0,X_n)-E d)/sqrt(n) 收敛到正态",
    "proof_text": "Proof. By Theorem 6.5 of the companion book ...",
    "source_lit_id": "0000", "page_range": {"start": 7, "end": 8, "label": "pp. 7-8"},
    "quote_verified": True, "quote_reason": "逐字比对通过（page 7）",
    "evidence_kind": "cross_check",
}


class _StubA:
    """A 的替身（只为了给 B 一个能转达的父代理）。

    为什么这一组需要它（2026-10-10 裁定第 4 条：主控不许直接控制 B / F / V）：
    改前这里直接 `summon("B", ..., by="M")`；裁定之后 B 必须由 A/D/E/F 转达，
    而本组的 registry 里只登记了循环角色（`LOOPS` 只有 B）⇒ 不补一个 A，
    "B 被召唤"这件事在这张工作区里根本发生不了。
    """

    def __init__(self) -> None:
        pass

    def run_once(self):
        return {"outcome": "ok", "detail": "stub-A"}


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
        json.dumps({"tool": "own.register_statement", "args": dict(_ROW),
                    "why": "把刚消化的那条命题登记进台账（正路：交给秘书落盘）"},
                   ensure_ascii=False),
        json.dumps({"final": "已登记 Theorem 1.5", "evidence": ["statements:0001"],
                    "notify": {"to": "D", "summary": "已登记 Theorem 1.5",
                               "body": "## 我做了什么\n把 Theorem 1.5 登记进 statements。\n"
                                       "## 依据\nlit:0000（逐字核过）\n## 要你做什么\n审它。\n"
                                       "## 我卡在哪\n不卡。\n", "refs": []}},
                   ensure_ascii=False),
    ])
    # 内层后端里放**真实现**：`own.register_statement` 的 handler 走 `self.inner.call`，
    # 于是闸门一个不少（出处核对 / 页码形状 / 五元位 / 秘书落盘）。
    inner = LocalBackend({"A": ("object", _StubA()),
                          "B": ("object", AgentB(st, extractor=None, extract_text=None))})
    backend = LlmBackend(inner=inner, loops=LOOPS, session_root=st.root,
                         seam_factory=lambda role: LlmSeam(role=role, session_root=st.root,
                                                           gateway=gw, price=(0.0, 0.0),
                                                           sid="t"),
                         max_steps=4, store=st, sid="t")
    cond = Conductor(st, policy=None, backend=backend)
    backend.conductor = cond
    built = build_registry(store=st, conductor=cond, workspace_root=str(st.root))
    backend.registry = built.registry
    return st, cond, built.registry, gw, backend


def _drive(tmp_path):
    """跑一趟「只派活、不点动作」的 B 循环（真机那条路）。"""
    st, cond, reg, gw, backend = _world(tmp_path)
    out = backend.call("B", "", {"task": "消化这条定理并登记"}, token=None, task_id="")
    return st, cond, reg, gw, out


def _steps(res: dict) -> list[dict]:
    """这一趟的每一步（`LlmBackend` 把完整记录写盘，结果里只给路径）。"""
    path = str(res.get("llm_run_path") or "")
    if path and pathlib.Path(path).is_file():
        return list(json.loads(pathlib.Path(path).read_text(encoding="utf-8")).get("steps") or [])
    return list((res.get("llm_run") or {}).get("steps") or [])


def test_the_loop_can_drive_b_to_register_a_statement(tmp_path):
    """正控：模型说一句 `own.register_statement` ⇒ 那一行真的落库（循环路径，不只是工具面）。"""
    st, cond, reg, gw, out = _drive(tmp_path)
    assert out["stop_reason"] == "final", out
    steps = _steps(out)
    assert [s.get("shape") for s in steps] == ["tool", "final"], steps
    rows = st.rows("statements")
    assert len(rows) == 1, rows
    assert rows[0]["statement_full"] == _ROW["statement_full"], rows[0]
    assert rows[0]["page_range"]["start"] == 7 and rows[0]["quote_verified"] is True, rows[0]
    # 落盘那一笔的留痕是**秘书**，不是模型自己写表
    assert rows[0]["created_by"] == "secretary-B", rows[0]["created_by"]
    # 而五元位是动作现算的那一份（手写表那条路给的是 `{}`，见 mp2 的读数）
    assert rows[0]["bits"], rows[0]["bits"]


def test_the_step_that_wrote_the_row_is_readable_in_the_run(tmp_path):
    """读数面：那一步的工具名、参数、以及"为什么"都要能在循环记录里读到。"""
    st, cond, reg, gw, out = _drive(tmp_path)
    steps = _steps(out)
    step = steps[0]
    assert (step.get("result") or {}).get("ok") is True, step.get("result")
    assert "own.register_statement" in json.dumps(step, ensure_ascii=False), step


def test_the_downstream_role_reads_it_after_the_loop_ran(tmp_path):
    """R13 判据①（循环版）：跑完之后下游（D）按号读得到这一行。"""
    st, cond, reg, gw, out = _drive(tmp_path)
    sid = st.rows("statements")[0]["stmt_id"]
    got = reg.call("table.get", role="D", table="statements", id=sid)
    assert got.ok and got.meta.get("found") is True, (got.data, got.meta)
    assert got.data["proof_text"].startswith("Proof."), got.data


def test_the_loop_cannot_reach_the_generic_table_writer(tmp_path):
    """负控（真机 `mp2-7.jsonl` 第 97 行）：循环里喊 `table.create("statements")` ⇒ 被拒。

    它与上面那条正控成对：**同一条循环**、同一个模型、只是这一句喊的是野路
    ⇒ 一行都不许落，而拒信要能把模型指回正路。没有这一条，正控的绿说明不了
    "野路被封了"。
    """
    st, cond, reg, gw, backend = _world(tmp_path)
    # 换一份剧本：第一句走野路
    backend.seam_factory = lambda role: LlmSeam(
        role=role, session_root=st.root, price=(0.0, 0.0), sid="t",
        gateway=_Scripted([
            json.dumps({"tool": "table.create",
                        "args": {"table": "statements", "row": dict(_ROW)},
                        "why": "我手上的动作调不通，改手写表"}, ensure_ascii=False),
            json.dumps({"final": "放弃了", "evidence": []}, ensure_ascii=False),
        ]))
    out = backend.call("B", "", {"task": "消化这条定理并登记"}, token=None, task_id="")
    assert out["stop_reason"] == "final", out
    step = _steps(out)[0]
    got = step.get("result") or {}
    assert got.get("ok") is False, got
    assert "direct_write_refused" in json.dumps(got, ensure_ascii=False), got
    assert st.rows("statements") == [], st.rows("statements")


def test_a_dangling_artifact_reference_is_caught_by_verify(tmp_path):
    """反真空（§17.2 的后半）："调用成功但下游看不见"这件事有判据。

    做法：让那一步声称产出了 `statements:9999`（一个不存在的行）⇒
    `verify` 必须以 `dangling_task_artifact` 报出来。
    没有这一条，"每一跳都有下游可见的产物"就只是句愿望。
    """
    from agentflow.verify import verify_all

    st, cond, reg, gw, backend = _world(tmp_path)
    # 走主控的召唤（直接 `backend.call` 不写台账行 —— 台账行是召唤写的）
    # B 只能由 A 转达（2026-10-10 裁定第 4 条：主控不许直接控制 B / F / V）⇒ 走 M→A→B。
    a1 = cond.summon("A", "run_once", {}, by="M")
    assert a1.outcome == "ok", (a1.status, a1.outcome, a1.refusal_reason, a1.detail)
    res = cond.summon("B", "run_once", {}, by="A", parent_task_id=a1.task_id)
    assert res.outcome == "ok", (res.status, res.outcome, res.refusal_reason, res.detail)
    rows = [r for r in st.rows("tasks") if r.get("role") == "B"]
    assert len(rows) == 1, rows
    # 把那次召唤的产出改成指向一个不存在的行
    with st.tx("tasks", actor="test") as tx:
        row = dict(rows[0])
        row["artifacts"] = ["statements:9999"]
        tx.upsert("tasks", row)
    d = verify_all(st).to_dict()
    codes = [i["code"] for i in list(d["errors"]) + list(d["warnings"])]
    assert "dangling_task_artifact" in codes, codes

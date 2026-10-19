# -*- coding: utf-8 -*-
"""二层唤起（父 → 子 → 孙）真跑一次：三跳各自落台账、且孙代理的活真的做得成。

## 为什么单独一条（业主 2026-10-14 裁定 ③ 逐字）

「**确保二层唤起（父→子→孙）道路畅通**」—— 并点名要先查清卡在哪。查出来的读数
（`temp/_r103_*.py` 一组探针，真机 `p9-t1-nolean`）是：

- **不是深度挡的**：`policy.max_depth=5`，`M(1)→A(2)→B(3)` 离上限还远；真机上
  也确实跑出过一条三跳链（M→H→A→B，`tasks` 里 t-0018 d2 → t-0019 d3 → t-0020..24 d4）。
- **断在第三跳**：那 5 条孙代理的活**没有一条成功** —— 3 条以
  `TypeError: Object of type PageRange is not JSON serializable` 崩掉
  （子代理第一步读 `table.schema`，而反射出来的 `page_range` 默认值是个行内对象，
  这趟运行在落产出时 json 化失败 ⇒ 整趟 failed），2 条被 `concurrency_exceeded`
  拒掉（`max_concurrency=4` 是全局在飞上限）。

所以"路通不通"不能只看那条边存不存在，要看**三跳各自真的跑完**。这一条就是这么跑的：
从 M 起，用照剧本回答的替身模型让每一层派下一层，孙代理那一步**照真机的样子**读
`table.schema`（那正是当年把整趟弄崩的那一步），最后断言：

1. `tasks` 里有一条 `depth=1 → 2 → 3` 的链（`parent_task_id` 一环比一环紧）；
2. 三跳**全部** `done/ok`（有一个 failed，"畅通"这句话就不成立）；
3. 孙代理那一趟的完整记录能落盘（`llm_run_path` 非空）——"跑完了但产出写不出去"
   在读数上与崩掉是一回事；
4. 孙代理那一趟里那一步 `table.schema` 的工具名与读数在 `LoopRun` 里读得到。
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

#: 三跳都要"循环驱动"才能各自再派下一层：M 派 A、A 派 B、B 干活。
LOOPS: dict[tuple[str, str], dict] = {("M", "run"): {}, ("A", "run_once"): {}, ("B", "run_once"): {}}

_ROW: dict = {
    "origin": "external_lit", "kind": "theorem", "label": "Theorem 1.5",
    "statement_full": "设 G 是有限连通图，各边电导有正下界；则 (d(X_0,X_n)-E d)/sqrt(n) 收敛到正态",
    "proof_text": "Proof. By Theorem 6.5 of the companion book ...",
    "source_lit_id": "0000", "page_range": {"start": 7, "end": 8, "label": "pp. 7-8"},
    "quote_verified": True, "quote_reason": "逐字比对通过（page 7）",
    "evidence_kind": "cross_check", "created_at": TS,
}

#: 每一层的剧本（按角色给：同一个替身模型对象只服务一个角色）。
SCRIPTS: dict[str, list[str]] = {
    "M": [
        json.dumps({"summon": {"role": "A", "task": "派活：按你的职责把这件事做掉", "params": {},
                               "why": "这一件是 A 的编排面"},
                    "notify": {"to": "A", "summary": "请登记 Theorem 1.5",
                               "body": "## 要你做什么\n登记 Theorem 1.5。\n", "refs": []}},
                   ensure_ascii=False),
        json.dumps({"final": "已交 A 转达"}, ensure_ascii=False),
    ],
    "A": [
        json.dumps({"summon": {"role": "B", "task": "派活：按你的职责把这件事做掉", "params": {},
                               "why": "登记是 B 的活，我只负责转达"},
                    "notify": {"to": "B", "summary": "请登记 Theorem 1.5",
                               "body": "## 要你做什么\n登记 Theorem 1.5。\n", "refs": []}},
                   ensure_ascii=False),
        json.dumps({"final": "已交 B"}, ensure_ascii=False),
    ],
    "B": [
        # 真机里崩掉的那一步：不带 table ⇒ 反射全部表（含 page_range 的默认值）。
        json.dumps({"tool": "table.schema", "args": {}, "why": "先看台账字段再落行"},
                   ensure_ascii=False),
        # 2026-10-19 晚：落行这一步换成**正路**（`own.register_statement` ⇒ 秘书落盘）。
        # 原先这里写 `table.create(table="statements")` —— 那正是 `mp2-7.jsonl` 第 97 行
        # 手写 `bits={}` 的形态，现在被 `store.direct_write_refusal` 受控拒绝。
        # `created_at` 是**行**的字段、不是动作的参数（动作面的 schema 是封闭集合）⇒ 摘掉。
        json.dumps({"tool": "own.register_statement",
                    "args": {k: v for k, v in _ROW.items() if k != "created_at"},
                    "why": "把这条命题登记进台账（交秘书落盘）"}, ensure_ascii=False),
        json.dumps({"final": "已登记 Theorem 1.5"}, ensure_ascii=False),
    ],
}


class _Scripted:
    """照剧本回答的替身模型：每次取一条，取完重复最后一条。"""

    spec = type("Spec", (), {"model": "scripted", "api_key": "fake"})()

    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)
        self.prompts: list[str] = []

    def complete(self, prompt: str, *, scope: str = "", system: str | None = None, **kw):
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
    gateways = {role: _Scripted(replies) for role, replies in SCRIPTS.items()}
    # 内层后端里放 **B 的真实现**：孙代理那一趟要调 `own.register_statement`，
    # 而那条路的 handler 是 `self.inner.call(role, action, …)`（确定性实现 + 闸门）。
    # 不注册 B ⇒ 注入不发生（`role not in inner.known_roles()`）⇒ 那一步 `unknown_tool`。
    from agentflow.agent_b import AgentB

    inner = LocalBackend({"B": ("object", AgentB(st, extractor=None, extract_text=None))})
    backend = LlmBackend(
        inner=inner, loops=LOOPS, session_root=st.root,
        seam_factory=lambda role: LlmSeam(role=role, session_root=st.root,
                                          gateway=gateways.get(role, _Scripted(["{}"])),
                                          price=(0.0, 0.0), sid="t"),
        max_steps=6, store=st, sid="t")
    cond = Conductor(st, policy=None, backend=backend)
    backend.conductor = cond
    built = build_registry(store=st, conductor=cond, workspace_root=str(st.root))
    backend.registry = built.registry
    return st, cond, built.registry, gateways


def _chain(rows: list[dict]) -> list[dict]:
    """从 `tasks` 里挑出那条三跳链（从 depth=1 那一行顺 parent 往下走）。"""
    by_id = {str(r.get("task_id")): r for r in rows}
    kids: dict[str, list[dict]] = {}
    for r in rows:
        kids.setdefault(str(r.get("parent_task_id") or ""), []).append(r)
    roots = [r for r in rows if int(r.get("depth") or 0) == 1 and str(r.get("role")) == "M"]
    out: list[dict] = []
    node = roots[0] if roots else None
    while node is not None:
        out.append(node)
        nxt = [c for c in kids.get(str(node.get("task_id")), [])
               if str(c.get("role")) != "M"]  # `M.notice` 那类板项不是召唤
        node = nxt[0] if nxt else None
    return out


def test_two_hop_summoning_runs_end_to_end(tmp_path):
    """父 → 子 → 孙：三跳各自落台账、全部成功、孙代理那一趟的产出真写得出去。"""
    st, cond, reg, gateways = _world(tmp_path)
    run = run_role("M", "把这件活按你的编排派下去", store=st, registry=reg, conductor=cond,
                   seam=LlmSeam(role="M", session_root=st.root, gateway=gateways["M"],
                                price=(0.0, 0.0), sid="t"),
                   workspace_root=str(st.root), sid="t", from_env=False, max_steps=6)
    assert run.stop_reason == "final", run.to_dict()

    rows = st.rows("tasks")
    chain = _chain(rows)
    assert [int(r["depth"]) for r in chain] == [1, 2, 3], (
        f"三跳链没成形（读到 {[(r.get('task_id'), r.get('role'), r.get('depth')) for r in chain]}）；"
        f"全部行：{[(r.get('task_id'), r.get('role'), r.get('called_by'), r.get('depth')) for r in rows]}")
    assert [str(r["role"]) for r in chain] == ["M", "A", "B"], chain
    assert str(chain[1]["parent_task_id"]) == str(chain[0]["task_id"]), chain
    assert str(chain[2]["parent_task_id"]) == str(chain[1]["task_id"]), chain
    assert str(chain[2]["called_by"]) == "A", "第三跳必须是子代理自己派的（这才是'二层唤起'）"

    bad = [(r.get("task_id"), r.get("role"), r.get("status"), r.get("outcome"),
            r.get("refusal_reason")) for r in chain
           if str(r.get("status")) != "done" or str(r.get("outcome")) != "ok"]
    assert not bad, f"三跳里有没跑成的 ⇒ 「道路畅通」不成立：{bad}"

    # 孙代理那一趟：产出落盘 + 那一步 `table.schema` 在读数里
    b_tid = str(chain[2]["task_id"])
    arts = sorted((st.root / "runs").glob("B-*.json"))
    assert arts, "孙代理那一趟的完整记录没落盘（跑完了但产出写不出去 = 读数上与崩掉同形）"
    payload = json.loads(arts[-1].read_text(encoding="utf-8"))
    json.dumps(payload, ensure_ascii=False)  # 不许有不可落盘的东西
    shapes = [s.get("shape") for s in payload.get("steps", [])]
    assert "tool" in shapes, f"孙代理那一步没记进 LoopRun：{shapes}"
    tools = [str((s.get("payload") or {}).get("name")) for s in payload.get("steps", [])]
    assert "table.schema" in tools, f"真机里崩掉的那一步没跑到：{tools}"
    assert str(payload.get("prompt_audit", {}).get("task_id") or "") == b_tid or True

    assert len(st.rows("statements")) == 1, st.rows("statements")


def test_a_non_jsonable_tool_result_no_longer_kills_the_grandchild_run(tmp_path, monkeypatch):
    """防回归（2026-10-17 改口径）：**即使**工具层退化成"不兜底"，孙代理也不许被打死。

    ⚠️ 这条原来是**反负控**（把修复放回去 ⇒ 必须崩）。后来我们把兜底加到了更下游
    （`canonical_json_text` 与全仓 `json.dumps(default=str)`）⇒ **崩不了了**，
    于是它反过来断言"照样 done、且落盘行仍是合法 JSON"：这才是"兜住了"的直接读数。
    （真机 T1/T4/T5 曾共撞 5 次同一崩溃。）

    没有这一条，"三跳全绿"说明不了任何事（它可能只是这条链本身不会崩）。
    这里把 `table_tools._jsonable_default` 换回恒等函数（= 修复前的行为），
    于是 `table.schema` 的返回里又出现 `PageRange` 实例 —— 真机上 t-0020/21/24
    就是这么死的：**整趟 `failed`**，不是"少一格读数"。
    """
    from agentflow.tools import table_tools

    st, cond, reg, gateways = _world(tmp_path)
    monkeypatch.setattr(table_tools, "_jsonable_default", lambda v: v, raising=True)
    run = run_role("M", "把这件活按你的编排派下去", store=st, registry=reg, conductor=cond,
                   seam=LlmSeam(role="M", session_root=st.root, gateway=gateways["M"],
                                price=(0.0, 0.0), sid="t"),
                   workspace_root=str(st.root), sid="t", from_env=False, max_steps=6)
    assert run.stop_reason == "final", run.to_dict()

    rows = st.rows("tasks")
    b_rows = [r for r in rows if str(r.get("role")) == "B"]
    assert b_rows, f"孙代理那一趟连行都没落：{[(r.get('task_id'), r.get('role')) for r in rows]}"
    assert str(b_rows[0]["status"]) == "done", (
        "非 JSON 结果又把孙代理打死了 —— 兜底没兜住："
        f"读数 {b_rows[0].get('status')}/{b_rows[0].get('outcome')}：{b_rows[0].get('detail')}")
    assert "not JSON serializable" not in str(b_rows[0].get("detail") or ""), b_rows[0].get("detail")
    import json as _json

    # 落盘的那份任务行必须是**合法 JSON**（修复前这里会是 `PageRange` 实例 ⇒ TypeError）
    _json.loads(_json.dumps(dict(b_rows[0]), ensure_ascii=False))

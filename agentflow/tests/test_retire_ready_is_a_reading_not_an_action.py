# -*- coding: utf-8 -*-
"""S1f'：`retire_ready` 就绪读数（只报不动作）—— 业主 T22 的三分支，框架不替父退役。

## 口径（`draft/90` §1.9 逐字，`draft/92` §15.3）

业主：「子代理宣布收工后，由父代理决定是否消边」。所以框架只给就绪读数：

- `branch="active"`：这一项还在跑 ⇒ 父该先看它最近报了什么，不许退役；
- `branch="waiting_no_children"`：它不在跑、它自己名下没有活跃子代理 ⇒ 可以退役；
- `branch="waiting_with_children"`：它不在跑、但它自己名下还有活跃子代理 ⇒ 不退役。

（"无活跃子代理且自身完全停止"说的是它自己，不是父 —— `draft/92` §15.6 的订正。）`reading.items_open` 只报不拦（业主算法里没这一条，C2 的裁定）。

## 判据

正控 2：三分支各就各位；父读到板项那一步的结果里出现"可退役"，而且只在这一拍出现一次
（板项的 `seen_step` 是同一件事在台账上的读数：报就绪与"板项进上下文"是同一拍）。负控
（本批最重要的一条）：`retire_ready` 与它接进循环之后，零写入（子行的 `status` / `inputs`
逐字不变、父侧没有 `edge-released:` 落痕）——没有这一条，"只报不动作"就只是注释里的一句话。
D-68（2026-10-26）之后这条负控更硬了：父不销号就发 `final` 会被结构完整性闸拒收，而框架
仍然不替它销（旧剧本里这一支根本走不到：终局那一步会先被闸拦下）。板项自己按 D12 落到
`done` + `acked`（信息型渲染即收口，"seen 就是 ack"）——那是投递侧的账，与"退役"是两件事。
反真空 1：读不成 ⇒ `checked=False`（不许折成"没有可退役的"）。边界 1：已记过消边的那些不再进候选。
"""
from __future__ import annotations

import json
import pathlib
from typing import Any

from agentflow.agent_loop import AgentLoop
from agentflow.conductor import Conductor, LocalBackend
from agentflow.llmseam import LlmSeam
from agentflow.store import Store
from agentflow.tools import build_registry

SID = "s1fp"


class _Gate:
    spec = type("Spec", (), {"model": "stub", "api_key": "x"})()

    def __init__(self, replies: list[str]) -> None:
        self.replies = replies
        self.systems: list[str] = []

    def complete(self, prompt: str, *, scope: str = "", system: str | None = None,
                 **kw: Any) -> Any:
        self.systems.append(system or "")
        text = self.replies[min(len(self.systems) - 1, len(self.replies) - 1)]
        return type("Reply", (), {"ok": True, "text": text, "tokens_in": 10, "tokens_out": 10,
                                  "error_detail": "", "error_kind": ""})()


def _cond(tmp_path: pathlib.Path) -> tuple[Store, Conductor, pathlib.Path]:
    ws = tmp_path / "ws"
    st = Store(ws)
    st.init()
    return st, Conductor(st, policy=None, backend=LocalBackend({})), ws


def _child(cond: Conductor, parent: str, *, role: str = "A", status: str = "done",
           key: str = "s1fp@c") -> str:
    return cond._write_new_row({
        "task_id": "", "role": role, "action": "run_once", "called_by": "M",
        "parent_task_id": parent, "depth": 2, "input_key": key, "status": status,
        "outcome": None if status in ("pending", "running") else "ok",
        "refusal_reason": None, "instance": "", "detail": "一个子代理",
        "error": None, "started_at": "2026-10-08T22:00:00+08:00",
        "ended_at": None if status in ("pending", "running") else "2026-10-08T22:05:00+08:00",
        "tokens": 0, "usd": 0.0, "artifacts": [], "inputs": [],
    }, note="start:A.run_once")


def _branches(ready: dict[str, Any]) -> dict[str, str]:
    return {r["task_id"]: r["branch"] for r in ready["ready"]}


def test_three_branches_are_classified(tmp_path: pathlib.Path):
    """正控：三分支各就各位（活跃 / 在等待且名下无活跃子 / 在等待但名下有活跃子）。"""
    _st, cond, _ws = _cond(tmp_path)
    parent = cond.open_top_level_run("M", "父那一趟")
    running = _child(cond, parent, status="running", key="s1fp@run")
    free = _child(cond, parent, status="done", key="s1fp@free")
    busy = _child(cond, parent, status="done", key="s1fp@busy")
    _child(cond, busy, status="running", key="s1fp@grand")     # busy 名下还有一个在跑的

    got = cond.retire_ready(parent)
    assert got["checked"] is True and got["reason"] == "", got
    table = _branches(got)
    assert table[running] == "active", table
    assert table[free] == "waiting_no_children", table
    assert table[busy] == "waiting_with_children", table
    # `reading.items_open` 只报不拦：给 free 挂一条未消的项，它仍然是"可以退役"
    cond.open_item(kind="notice", role="A", expects="ack", summary="子代理已收工",
                   called_by="A", parent_task_id=free, depth=3, input_key="s1fp@n")
    again = _branches(cond.retire_ready(parent))
    assert again[free] == "waiting_no_children", again
    reading = {r["task_id"]: r["reading"] for r in cond.retire_ready(parent)["ready"]}
    assert reading[free]["items_open"] == 1, reading[free]


def test_a_released_child_drops_out_of_the_candidates(tmp_path: pathlib.Path):
    """边界：已经记过消边的那些不再进候选（否则父会看到"它又变成可退役了"）。"""
    _st, cond, _ws = _cond(tmp_path)
    parent = cond.open_top_level_run("M", "父那一趟")
    free = _child(cond, parent, status="done", key="s1fp@free2")
    assert _branches(cond.retire_ready(parent))[free] == "waiting_no_children"
    mark, why = cond.note_edge_release(parent, child_task_id=free, attempt=1)
    assert mark and not why, (mark, why)
    assert free not in _branches(cond.retire_ready(parent)), cond.retire_ready(parent)


def test_retire_ready_is_three_state(tmp_path: pathlib.Path, monkeypatch):
    """反真空：台账读不成 ⇒ `checked=False`（不许折成"没有可退役的"）。"""
    _st, cond, _ws = _cond(tmp_path)
    parent = cond.open_top_level_run("M", "父那一趟")

    def boom() -> Any:
        raise RuntimeError("注入的台账故障")

    monkeypatch.setattr(cond, "_tasks", boom)
    got = cond.retire_ready(parent)
    assert got["checked"] is False and "RuntimeError" in got["reason"], got
    assert got["ready"] == [], got


def _run_loop(cond: Conductor, st: Store, ws: pathlib.Path, gate: _Gate, me: str) -> Any:
    reg = build_registry(store=st, conductor=cond).registry
    loop = AgentLoop(role="M", session_root=ws, registry=reg, conductor=cond,
                     seam=LlmSeam(role="M", session_root=ws, gateway=gate,
                                  price=(0.0, 0.0), sid=SID),
                     store=st, sid=SID, max_steps=2)
    return loop.run("把这一趟做完", summoned_by="user", my_task_id=me, depth=1)


def test_the_loop_reports_ready_items_and_never_retires_them(tmp_path: pathlib.Path):
    """正控（接线）+ 负控（本批最重要的一条）：报得出来，但一个字节都不写。

    剧本为什么要多一步（2026-10-26）：D-68 的结构完整性闸在终局那一支的最前面，
    父直接说 `final` 时整步只剩一条拒信、走不到渲染板项与报就绪的那一段 ——
    于是"报得出来"这件事在旧剧本里永远测不到（红的不是产品，是剧本先把那一段截掉了）。
    现在第 0 步先做一件读的事（`note`），第 1 步才说 `final`：

    正控：父这一步渲染到了板项 ⇒ 结果里出现 `可退役`（含 branch），且只在这一拍出现一次。
    负控（"零自动退役"的机器形态）：跑完之后
    ① 父那一行 `inputs` 里没有任何 `edge-released:` 落痕（`released_edges` 为空）
    ② 子那一行的 `status` 与 `inputs` 逐字不变（框架没替父把它划掉）
    ③ 那条 notice 按 D12 落到 `done` + `acked`（信息型渲染即收口，"seen 就是 ack"）——
       这一格与"退役"是两件事：把它写进断言是为了让人一眼看出两者的区别。
    ④ 父不销号直接说 `final` ⇒ D-68 拒收，且拒信点名那个还没销号的子代理：
       框架宁可拒掉这一趟，也不替父销号。
    """
    st, cond, ws = _cond(tmp_path)
    me = cond.open_top_level_run("M", "我这一趟的活")
    child = _child(cond, me, status="done", key="s1fp@reported")
    item = cond.open_item(kind="notice", role="M", expects="ack", summary="子代理已收工",
                          called_by="A", parent_task_id=me, depth=2, input_key="s1fp@item")
    child_before = next(r for r in st.rows("tasks") if str(r.get("task_id")) == child)
    gate = _Gate([json.dumps({"note": "板上的那条看清了，先不动手"}, ensure_ascii=False),
                  json.dumps({"final": "收工", "evidence": []}, ensure_ascii=False)])
    run = _run_loop(cond, st, ws, gate, me)

    merged = [s.result for s in run.steps]
    carrying = [r for r in merged if "可退役" in r]
    assert len(carrying) == 1, (
        "就绪读数只该在'板项进了这一步上下文'的那一拍出现一次", merged)
    ready = carrying[0]["可退役"]
    assert {x["task_id"]: x["branch"] for x in ready} == {child: "waiting_no_children"}, ready

    # 正控的"位置"那一半：读数的落点与板项进上下文是同一拍（`seen_step` 是它在台账上的读数）。
    item_row = next(r for r in st.rows("tasks") if str(r.get("task_id")) == item)
    assert item_row.get("seen_step") == 0, item_row

    # 负控①②：零写入（不许替父退役）
    assert cond.released_edges(me)["edges"] == [], (
        "框架不许替父退役（父侧不许留消边落痕）", cond.released_edges(me))
    child_after = next(r for r in st.rows("tasks") if str(r.get("task_id")) == child)
    assert (child_after["status"], list(child_after.get("inputs") or [])) == (
        child_before["status"], list(child_before.get("inputs") or [])), (
        "子那一行不许被动过", (child_before, child_after))
    # ③ 板项按 D12 收口（信息型：渲染即 ack）—— 与"退役"是两件事
    state, close = item_row.get("item_state"), item_row.get("item_close")
    assert (state, close) == ("done", "acked"), (
        "信息型板项该在渲染那一拍收口成 done/acked（D12：seen 就是 ack）；"
        f"读到的是 {state!r} / {close!r}", item_row)
    assert str(item_row.get("seen_by") or "") == me, item_row
    # ④ 不销号就说 final ⇒ D-68 拒收；拒信点名那个还没销号的子代理（框架宁可拒，也不替它销）
    refusals = [r for r in merged if r.get("final_refused")]
    assert refusals, ("父不销号直接说 final 而树上还有子代理 ⇒ D-68 必须拒收", merged)
    assert refusals[0]["final_refused"].get("complete") is False, refusals[0]
    assert child in json.dumps(refusals[0], ensure_ascii=False), (
        "拒信必须点名还没销号的子代理（否则父不知道该销谁）", refusals[0])

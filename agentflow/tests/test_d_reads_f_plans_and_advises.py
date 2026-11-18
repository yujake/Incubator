# -*- coding: utf-8 -*-
"""R4：D 查得到 F 的 plan，也能把「这条不再需要」的建议送到 F，F 照做（业主 2026-11-13）。

## 业主原话（逐字）

> 「我们依旧要说D可以查F的plan且发信息给F说关于plan的建议，如哪些不再需要了或哪些需要
>   调整（需要调整=不再需要原来的并新设新plan）。」

## 落点（都是既有面，不另开旁路）

- 读口：`attack.status` / `attack.list_plans` 的 `roles` 里本来就有 D
  （`agent_f/tools/attack_tools._READ_ROLES = ("F", "D", "G", "H")`）—— 这一条是回归，
  不是判据（改前也绿）。
- 发建议：走既有的跨角色消息面（`handoff` → `manuscripts/handoffs.jsonl`；或 `message`
  形状 → 名册成员的收件板项）。这里用 `Secretary.handoff_add` —— 它正是循环里
  `_do_handoff` 调的那一个写口（`sender` 仍是 D），不新造通道。
- F 照做：`attack.abandon_plan`（R3 的写入口）⇒ `status=abandoned` + `history` 含
  「不再需要」。这是本文件真正的判据：建议链路的终点是 F 的台账真的变了。

## 判据

| 判据 | 它要证明的事 | 改前红在哪 |
|---|---|---|
| a | D 的动作面里有读口，且 `attack.status` 真能读出 plan 的方向/状态 | 回归（改前也绿），不作判据 |
| b | D 的建议落进 `handoffs.jsonl`（既有消息面，无旁路），正文点名 plan 与「不再需要」 | 改前没有 `attack.abandon_plan`，这条链路走不到底（F 收得到、做不了） |
| c | F 用 `attack.abandon_plan` 放弃那条 plan ⇒ `status=abandoned` + `history` 含「不再需要」 | 改前 F 没有这个动作（`abandon_plan` 不存在） |
"""
from __future__ import annotations

import pathlib
import sys

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agentflow import agent_f as AF
from agentflow import manuscripts as MAN
from agentflow import secretary as SEC
from agentflow.store import Store
from agentflow.tools import build_registry

BUDGET = {"max_rounds": 3, "max_parallel_subgoals": 2,
          "max_persist_attempts": 2, "max_depth": 2}
REASON = "不再需要"


def _ws(path: pathlib.Path) -> Store:
    st = Store(path / "ws")
    st.init()
    return st


def _f(store: Store) -> AF.AgentF:
    return AF.AgentF(store, config={"workspace_root": store.root}, actor="agent-F-F1")


def test_d_reads_fs_plans_advises_and_f_abandons(tmp_path: pathlib.Path) -> None:
    """a（回归）＋ b ＋ c：读得到 → 发得出 → F 真的把那条 plan 放弃成「不再需要」。"""
    store = _ws(tmp_path)
    f = _f(store)
    keep = f.create_plan("方向一：把界算出来", "PK-KEEP", budget=dict(BUDGET))["plan_id"]
    drop = f.create_plan("方向二：把同构类数出来", "PK-DROP", budget=dict(BUDGET))["plan_id"]
    assert keep and drop, (keep, drop)

    # ---- a（回归，不作判据）：D 的读口本来就在，且真读得出方向/状态 ----
    reg = build_registry(store=store).registry
    d_specs = {s.name: s for s in reg.for_role("D")}
    assert {"attack.status", "attack.list_plans"} <= set(d_specs), sorted(d_specs)
    got = reg.call("attack.status", role="D", plan_id=drop)
    assert got.ok, got
    view = dict(got.data or {})
    assert view.get("status") == "open", view
    assert "方向二" in str(view.get("problem") or ""), view

    # ---- b：D 的建议落进既有消息面（handoffs.jsonl；无旁路） ----
    sec = SEC.Secretary("D", root=store.root, store=store)
    rec = sec.handoff_add(
        to="F", summary=f"计划 {drop} 不再需要",
        body=(f"计划 {drop}（方向二）不再需要了：方向已改，请把它放弃成「不再需要」；"
              f"计划 {keep} 继续推进。"),
        refs=[f"plan:{drop}"])
    assert rec.get("id") or rec.get("mid"), rec
    rows = [dict(r) for r in MAN.rows(store.root)]
    mine = [r for r in rows if drop in str(r.get("body") or "")]
    assert mine, rows
    assert str(mine[-1].get("sender") or "") == "D", mine[-1]
    assert str(mine[-1].get("to") or "") in ("F", "ALL") or "F" in str(mine[-1].get("to")), mine[-1]

    # ---- c：F 照建议放弃（写入口是 R3 的 `attack.abandon_plan`） ----
    out = f.abandon_plan(drop, reason=REASON)
    assert out.get("ok") is True and out.get("status") == "abandoned", out
    row = next(dict(r) for r in store.rows("attack_plans")
               if str(r.get("plan_id")) == str(drop))
    assert row["status"] == "abandoned", row
    hist = list(row.get("history") or [])
    assert hist and REASON in str(hist[-1].get("detail") or ""), hist
    # 另一条不受影响（建议点名的是 drop，不是"全放弃"）
    keep_row = next(dict(r) for r in store.rows("attack_plans")
                    if str(r.get("plan_id")) == str(keep))
    assert keep_row["status"] == "open", keep_row


def test_e_anti_vacuum_without_the_real_writer_the_plan_stays_open(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """e 判据（反真空）：把写盘那一格打桩成"什么都不写" ⇒ 同一笔调用后计划仍是 open。

    证明 c 的绿来自 `attack.abandon_plan` 真的写了库，而不是来自
    "调用返回 ok 就算过了"（返回 ok 但没落盘的那种实现在这条下必红）。
    """
    store = _ws(tmp_path)
    f = _f(store)
    pid = f.create_plan("方向三", "PK-STUB", budget=dict(BUDGET))["plan_id"]
    monkeypatch.setattr(AF.AgentF, "_write_plan",
                        lambda self, row, *, note, base=None: None)   # 夹具：写盘整格打桩
    out = f.abandon_plan(pid, reason=REASON)
    assert out.get("ok") is True, out
    row = next(dict(r) for r in store.rows("attack_plans")
               if str(r.get("plan_id")) == str(pid))
    assert row["status"] == "open", (
        "写盘被打桩成空之后计划竟然变成 abandoned ⇒ c 的绿不是来自真的落盘", row)
    assert [h for h in (row.get("history") or []) if h.get("action") == "abandon"] == [], row

# -*- coding: utf-8 -*-
"""判据：实例身份一路带到写盘面（K1 / K2 的 a / b / d / e 四条）。

## 现场（AUDIT-F，逐字）

```text
`tools/attack_tools.py:271-290` 的 `_agent_for(store)` 不传 actor
⇒ `self.actor` 恒 "agent-F"（core.py:631）
⇒ claims.owner / events.actor / submitter / ARTIFACTS.producer 全塌成角色级
```

真机读数：`projects/lp-ball-8`（本仓只读副本 `temp/planlife/lp-ball-8-copy`）的
`runs/manuscript-claims.json` 两份稿 owner 都是 `agent-F`；`ARTIFACTS.jsonl` 10 条
f-proof 行 `producer=F`、`task_id=""`；`data/events.jsonl` 20 条 `attack_plans`
upsert 全 `actor=agent-F` —— 而写它们的是 t-000015（名册 F-proof1）与
t-000026（名册 f-dual-proof-1）两个不同实例。

## 判据

| # | 判据 | 改前红在哪 |
|---|---|---|
| a | 两个同角色实例各写一笔 ⇒ claims.owner / ARTIFACTS.producer / 事件 actor 可区分，且等于各自的实例键 | 两边都 `agent-F` / `F`（改前红） |
| b1 | 空标签（tasks.instance 空、名册无名、有台账号）⇒ 退到 `agent-F-<task_id>`，不塌成 `agent-F` | 改前一律 `agent-F` |
| b2 | 连台账号都没有 ⇒ `attributed=False` + `conflict` 非空，且 claims 行把这两格落盘（显式 conflict，不是静默） | 改前没有「归因成了没有」这个读数 |
| d | 单实例回归：一个有名册名的 F 写一笔，下游（claims 复核 / `artifacts.owners_of`）读到的仍是这个实例 | —— |
| e | 反真空：把 ① 的 actor 传递打桩成「只给角色名」⇒ a 必须塌回同一个值（证明 a 的绿来自身份传递） | —— |

## 边界

全部 `tmp_path` 工作区；不读写 `projects/`（真机工作区只读，复算在 ③ 的探针里
只读取数）；不跑全量。
"""
from __future__ import annotations

import json
import pathlib
import sys

import pytest

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agentflow import artifacts as A
from agentflow import conductor as CON
from agentflow import identity as ID
from agentflow import schema as S
from agentflow import secretary as SEC
from agentflow.store import Store
from agentflow.tools import attack_tools as AT

BUDGET = {"max_rounds": 3, "max_parallel_subgoals": 2,
          "max_persist_attempts": 2, "max_depth": 2}

#: 一页够用的证明产物（`proof_manuscript` 要的最小形状：kind / proposition / steps）。
PRODUCT = {
    "kind": "proof",
    "proposition": "设 n≥3，则 c(G) ≤ 1。",
    "steps": [{"text": "由定义直接得到。", "assumption": True}],
}

PARENT = "t-000001"


def _ws(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _task(st: Store, *, task_id: str, parent: str = PARENT, role: str = "F",
          instance: str = "") -> None:
    """铺一条 tasks 行（`instance` 是这一趟的实例列 —— K2 的四套键之一）。"""
    with st.tx("tasks", actor="test") as tx:
        tx.upsert("tasks", {
            "task_id": task_id, "role": role, "action": "",
            "called_by": "D" if parent else "M", "parent_task_id": (parent or None),
            "depth": 2, "input_key": f"k-{task_id}", "status": "running",
            "outcome": None, "started_at": S.now_iso(), "ended_at": None,
            "detail": "跑着", "instance": instance,
        })


def _rename(st: Store, *, task_id: str, name: str = "") -> str:
    """在父的名册里登记这个 F，返回名册实际发出的名字（不给名字时由秘书发号）。"""
    sec = SEC.Secretary("D", root=st.root, store=st)
    got = sec.roster_add(owner=PARENT, role="F", task_id=task_id, brief="攻一个方向",
                         want_name=name)
    assert got.get("problem") == "", got
    return str(got.get("name") or "")


def _write_one(st: Store, *, task_id: str, instance: str, key: str) -> dict:
    """在 `calling_as(task_id, instance=…)` 里走生产工具路径写一笔。

    返回这一笔在三个写盘面上的读数：claims / ARTIFACTS / 事件 actor。
    """
    with CON.calling_as(task_id, "F", instance=instance):
        agent = AT._agent_for(st)
        made = agent.create_plan(f"难题 {key}", key,
                                 subgoals=[{"sid": "S1", "text": "子目标一",
                                            "owner": "F", "testable": "能判"}],
                                 budget=dict(BUDGET))
        assert made.get("ok") is True, made
        pid = str(made.get("plan_id") or "")
        plan = next(dict(r) for r in st.rows("attack_plans")
                    if str(r.get("plan_id")) == pid)
        got = agent.proof_manuscript(PRODUCT, sg=plan["subgoals"][0], plan=plan)
        assert got.get("ok") is True, got
        row = next(dict(r) for r in st.rows("attack_plans")
                   if str(r.get("plan_id")) == pid)
        return {"actor": agent.actor, "identity": dict(agent.identity),
                "plan_id": pid, "created_by": str(row.get("created_by") or ""),
                "path": str(got.get("path") or "")}


def _claims(st: Store) -> dict:
    raw = json.loads((pathlib.Path(st.root) / "runs/manuscript-claims.json")
                     .read_text(encoding="utf-8"))
    return dict(raw.get("claims") or {})


def _artifacts(st: Store) -> list[dict]:
    return [dict(r) for r in A.read_ledger(st.root)[0]]


def _plan_event_actors(st: Store) -> list[str]:
    return [str(e.get("actor") or "") for e in st.read_events()
            if str(e.get("op") or "") == "upsert"
            and str(e.get("table") or "") == "attack_plans"]


# ============================================================ a：两个实例可区分
def test_a_two_instances_of_one_role_are_distinguishable_on_every_write_surface(
        tmp_path: pathlib.Path) -> None:
    """a 判据：两个同角色实例各写一笔 ⇒ claims / ARTIFACTS / 事件 的 actor 可区分。

    改前红（逐字）：`_agent_for(store)` 不传 actor ⇒ 两边 `claims.owner` 都是
    `"agent-F"`、`ARTIFACTS.producer` 都是 `"F"`、事件 actor 都是 `"agent-F"`。
    """
    st = _ws(tmp_path)
    _task(st, task_id=PARENT, parent="", role="D")
    first, second = "t-000010", "t-000011"
    _task(st, task_id=first, instance="")
    _task(st, task_id=second, instance="")
    name1 = _rename(st, task_id=first)
    name2 = _rename(st, task_id=second)
    assert name1 and name2 and name1 != name2, (name1, name2)

    one = _write_one(st, task_id=first, instance=name1, key="PK-A1")
    two = _write_one(st, task_id=second, instance=name2, key="PK-A2")

    # ① 归因键（created_by）与 ② 事件 actor：两个实例各是自己的那一个。
    assert one["created_by"] == f"agent-F-{name1}", one
    assert two["created_by"] == f"agent-F-{name2}", two
    assert _plan_event_actors(st) == [f"agent-F-{name1}", f"agent-F-{name2}"], (
        _plan_event_actors(st))

    # ③ claims.owner：同一角色两个实例各写一份稿，盘上分得开。
    claims = _claims(st)
    assert claims[one["path"]]["owner"] == f"agent-F-{name1}", claims
    assert claims[two["path"]]["owner"] == f"agent-F-{name2}", claims
    assert claims[one["path"]]["owner"] != claims[two["path"]]["owner"]

    # ④ ARTIFACTS.producer（以及新加的 instance / task_id 两格）。
    rows = {r["path"]: r for r in _artifacts(st) if r.get("path") in
            (one["path"], two["path"])}
    assert rows[one["path"]]["producer"] == f"agent-F-{name1}", rows
    assert rows[two["path"]]["producer"] == f"agent-F-{name2}", rows
    assert rows[one["path"]]["instance"] == name1, rows
    assert rows[two["path"]]["instance"] == name2, rows
    assert rows[one["path"]]["task_id"] == first, rows
    assert rows[two["path"]]["task_id"] == second, rows


# ============================================================ b1：空标签不退角色桶
def test_b1_an_empty_label_falls_back_to_the_task_id_not_the_role_bucket(
        tmp_path: pathlib.Path) -> None:
    """b1 判据：`tasks.instance` 空、名册没有名字、但有台账号 ⇒ 实例键是台账号。

    改前红：这一档 actor 一律 `agent-F`（角色桶），与「另一个同样没名字的 F」
    在盘上完全重合。
    """
    st = _ws(tmp_path)
    _task(st, task_id=PARENT, parent="", role="D")
    tid = "t-000020"
    _task(st, task_id=tid, instance="")        # 空标签，且不登记名册

    with CON.calling_as(tid, "F"):
        agent = AT._agent_for(st)
        ident = dict(agent.identity)
        assert agent.actor == f"agent-F-{tid}", (agent.actor, ident)
        assert ident["attributed"] is True, ident
        assert ident["source"] == "task_id", ident
        made = agent.create_plan("无名字的一趟", "PK-B1",
                                 subgoals=[{"sid": "S1", "text": "子目标",
                                            "owner": "F", "testable": "能判"}],
                                 budget=dict(BUDGET))
        assert made.get("ok") is True, made
        plan = next(dict(r) for r in st.rows("attack_plans")
                    if str(r.get("plan_id")) == str(made.get("plan_id")))
        got = agent.proof_manuscript(PRODUCT, sg=plan["subgoals"][0], plan=plan)
        assert got.get("ok") is True, got
        assert str(plan.get("created_by")) == f"agent-F-{tid}", plan
        claims = _claims(st)
        assert claims[str(got.get("path"))]["owner"] == f"agent-F-{tid}", claims
        assert claims[str(got.get("path"))]["instance"] == tid, claims
        assert claims[str(got.get("path"))]["owner"] != "agent-F"


# ============================================================ b2：读不到就记 conflict
def test_b2_no_task_at_all_is_an_explicit_conflict_not_a_silent_role_bucket(
        tmp_path: pathlib.Path) -> None:
    """b2 判据：连台账号都没有 ⇒ `attributed=False` + `conflict` 非空，并随 claims 落盘。

    改前红：没有任何一格说得出「这一笔没归因」—— 盘上只有 `agent-F`，与「真的叫
    agent-F 的那个单例」长得一模一样。
    """
    st = _ws(tmp_path)
    agent = AT._agent_for(st)                  # 不在任何 calling_as 里（直调现场）
    ident = dict(agent.identity)
    assert ident["attributed"] is False, ident
    assert ident["conflict"], "未归因必须有一句为什么（不许静默）"
    assert "实例读不到" in ident["conflict"], ident
    # 兼容值仍是角色级 actor（单实例直调不许被挡死），但读数把冲突带出来。
    assert agent.actor == "agent-F", ident

    made = agent.create_plan("直调的一笔", "PK-B2",
                             subgoals=[{"sid": "S1", "text": "子目标",
                                        "owner": "F", "testable": "能判"}],
                             budget=dict(BUDGET))
    assert made.get("ok") is True, made
    plan = next(dict(r) for r in st.rows("attack_plans")
                if str(r.get("plan_id")) == str(made.get("plan_id")))
    got = agent.proof_manuscript(PRODUCT, sg=plan["subgoals"][0], plan=plan)
    assert got.get("ok") is True, got
    holder = _claims(st)[str(got.get("path"))]
    assert holder["attributed"] is False, holder
    assert holder["identity_conflict"], holder
    assert "实例读不到" in holder["identity_conflict"], holder


# ============================================================ d：单实例回归
def test_d_a_single_instance_is_still_readable_downstream(
        tmp_path: pathlib.Path) -> None:
    """d 判据：单实例场景下 actor 仍能被下游读到（不许把单实例搞坏）。

    下游读两处既有入口：`manuscriptids.claim_for_write`（同一个人续写自己的稿
    ⇒ `mine`）与 `artifacts.owners_of`（按路径查生产者）。
    """
    st = _ws(tmp_path)
    _task(st, task_id=PARENT, parent="", role="D")
    tid = "t-000030"
    _task(st, task_id=tid, instance="")
    name = _rename(st, task_id=tid)
    one = _write_one(st, task_id=tid, instance=name, key="PK-D")

    from agentflow import manuscriptids as MID

    held = MID.claim_for_write(st.root, one["path"], owner=one["actor"], role="F")
    assert held.get("state") == "mine", held
    assert held["holder"]["owner"] == one["actor"], held
    owners = A.owners_of(st.root, one["path"])
    assert [o["producer"] for o in owners] == [one["actor"]], owners


# ============================================================ e：反真空
def test_e_stubbing_the_actor_transfer_back_to_the_role_makes_a_red(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """e 判据（反真空）：把 ① 的 actor 传递打桩成角色字面量 ⇒ a 必须红。

    打桩点就是 `identity.resolve_identity`（`attack_tools._agent_for` 取身份的唯一入口）：
    它退回改前的形态（`actor="agent-F"`、`attributed=False`）。此时两个实例的
    claims / ARTIFACTS / 事件必须重新塌成同一个值 —— 证明 a 的绿来自身份传递，
    而不是来自别的什么。
    """
    def fake_resolve(store=None, role="", **_kw):  # noqa: ANN001, ARG001
        return {"checked": True, "role": str(role), "task_id": "", "instance": "",
                "actor": f"agent-{role}", "source": "stub", "attributed": False,
                "conflict": "反真空：身份传递被打桩成角色字面量", "tasks_instance": "",
                "roster_name": "", "roster_checked": True, "roster_why": ""}

    monkeypatch.setattr(ID, "resolve_identity", fake_resolve)
    st = _ws(tmp_path)
    _task(st, task_id=PARENT, parent="", role="D")
    first, second = "t-000040", "t-000041"
    _task(st, task_id=first, instance="")
    _task(st, task_id=second, instance="")
    name1 = _rename(st, task_id=first)
    name2 = _rename(st, task_id=second)
    one = _write_one(st, task_id=first, instance=name1, key="PK-E1")
    two = _write_one(st, task_id=second, instance=name2, key="PK-E2")

    assert one["actor"] == two["actor"] == "agent-F", (one, two)
    assert one["created_by"] == two["created_by"] == "agent-F", (one, two)
    claims = _claims(st)
    assert {claims[one["path"]]["owner"], claims[two["path"]]["owner"]} == {"agent-F"}
    rows = {r["path"]: r for r in _artifacts(st) if r.get("path") in
            (one["path"], two["path"])}
    assert {rows[one["path"]]["producer"], rows[two["path"]]["producer"]} == {"agent-F"}
    assert set(_plan_event_actors(st)) == {"agent-F"}


if __name__ == "__main__":          # pragma: no cover - 手工跑这一份时用
    raise SystemExit(pytest.main([__file__, "-q"]))





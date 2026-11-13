# -*- coding: utf-8 -*-
"""并发计划上限：一个 F「未 finish 且未放弃」的计划不许超过 2 条（业主 2026-11-13）。

业主原话（逐字，末句按业主补完）：

> 「若一个F开了多plan且未finish的同时推进的大于2个（已finish或放弃的不计入该数），
>   系统需拦截并给出提醒，内容类似"同时推进的plan个数已达上限2，请先推进已有plan，
>   或将新plan的计划汇报父D，让父派其它F攻坚"。」

## 判据

| 判据 | 它要证明的事 | 改前红在哪 |
|---|---|---|
| a | 已有 2 条在推 ⇒ 第 3 条受控拒（`parallel_plans_limit`）＋提醒逐字＋台账零写入 | 改前 `create_plan` 没有上限，照建不误 |
| b | `resolved` / `abandoned` 不计入；`stalled` 计入（Q4 按业主字面） | 改前没有"计不计入"这件事 |
| c | 反真空：把"不计入"的名单打桩成空 ⇒ b 必红（证明 b 的绿来自那两档真的被排除） | —— |
| d | 分桶按 `created_by`：另一个 F 的计划不占这个 F 的名额（否则会与"按研究方向开多个 F"打架） | 改前没有桶，只有全体 |
| e | 归因：默认 actor 时用台账号现查名册名 ⇒ `created_by=agent-F-<名>`（上限才可能按"一个 F"算） | 改前恒 `agent-F`（所有 F 挤一个桶） |

不改 schema、不改 `tools/base.py`：归因只用 `host._actor_for` 已有的格式
（`agent-<role>-<instance>`）＋ conductor 已经挂在 ContextVar 上的台账号。
"""
from __future__ import annotations

import pathlib
import sys

import pytest

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agentflow import agent_f as AF
from agentflow import conductor as CON
from agentflow import schema as S
from agentflow import secretary as SEC
from agentflow.agent_f import create_plan as CP
from agentflow.store import Store

BUDGET = {"max_rounds": 3, "max_parallel_subgoals": 2,
          "max_persist_attempts": 2, "max_depth": 2}
OWNER_TEXT = ("同时推进的plan个数已达上限2，请先推进已有plan，"
              "或将新plan的计划汇报父D，让父派其它F攻坚。")


def _ws(path: pathlib.Path) -> Store:
    st = Store(path / "ws")
    st.init()
    return st


def _f(store: Store, actor: str = "agent-F-F1") -> AF.AgentF:
    return AF.AgentF(store, config={"workspace_root": store.root}, actor=actor)


def _seed_plan(store: Store, *, key: str, status: str, owner: str = "agent-F-F1") -> str:
    """直接落一条计划行（造"已有 N 条"的现场；不经过 `create_plan` 的上限）。"""
    with store.tx("attack_plans", actor="test") as tx:
        pid = tx.alloc_id("plan")
        tx.upsert("attack_plans", {
            "plan_id": pid, "problem": f"难题 {key}", "problem_key": key,
            "status": status, "rounds": 0, "budget": dict(BUDGET),
            "subgoals": [], "history": [], "depth": 0,
            "best_partial": ("停下来时的最好部分结果" if status == "stalled" else ""),
            "created_by": owner,
        })
    return pid


def _seed_task(store: Store, *, task_id: str, parent: str, role: str = "F") -> None:
    with store.tx("tasks", actor="test") as tx:
        tx.upsert("tasks", {
            "task_id": task_id, "role": role, "action": "",
            "called_by": "D", "parent_task_id": (parent or None), "depth": 2,
            "input_key": f"k-{task_id}", "status": "running", "outcome": None,
            "started_at": S.now_iso(), "ended_at": None, "detail": "跑着",
        })


# ============================================================ a：第 3 条受控拒
def test_a_the_third_concurrent_plan_is_refused_with_the_owner_wording(
        tmp_path: pathlib.Path) -> None:
    """a 判据：已有 2 条在推 ⇒ 第 3 条整笔拒，提醒逐字，台账不多一行。

    改前红：改前这里会返回 `ok=True, created=True`（`create_plan` 没有上限），
    于是"一个 F 同时推 3 条"在盘上成立而没有任何提醒。
    """
    store = _ws(tmp_path)
    f = _f(store)
    first = f.create_plan("难题甲", "PK-A", budget=dict(BUDGET))
    second = f.create_plan("难题乙", "PK-B", budget=dict(BUDGET))
    assert first.get("ok") is True and second.get("ok") is True, (first, second)
    before = len(store.rows("attack_plans"))

    out = f.create_plan("难题丙", "PK-C", budget=dict(BUDGET))

    assert out.get("ok") is False, out
    assert out.get("kind") == "parallel_plans_limit", out
    assert out.get("created") is False and out.get("plan_id") is None, out
    # 提醒逐字（业主原话）＋ 点名挡路的那两条
    err = str(out.get("error") or "")
    assert OWNER_TEXT in err, err
    assert str(first.get("plan_id")) in err and str(second.get("plan_id")) in err, err
    # 受控码落在既有那一档（终态 refused / invalid_params），不是"执行完成"
    assert out.get("refusal_reason") == "invalid_params", out
    # 零写入
    assert len(store.rows("attack_plans")) == before, store.rows("attack_plans")


# ============================================================ b：计不计入
def test_b_finished_and_abandoned_do_not_count_but_stalled_does(
        tmp_path: pathlib.Path) -> None:
    """b 判据：`resolved` / `abandoned` 不占名额；`stalled` 占（Q4 的业主字面口径）。

    改前红：改前没有"占不占名额"这件事（第三条照样建得出来，或根本没有上限）。
    """
    store = _ws(tmp_path)
    f = _f(store)
    _seed_plan(store, key="PK-R1", status="resolved")
    _seed_plan(store, key="PK-R2", status="resolved")
    _seed_plan(store, key="PK-AB", status="abandoned")
    ok = f.create_plan("新方向一", "PK-N1", budget=dict(BUDGET))
    assert ok.get("ok") is True and ok.get("created") is True, ok

    # 现在在推的 = 1 条（刚建的那条）；再建一条仍在 2 以内
    ok2 = f.create_plan("新方向二", "PK-N2", budget=dict(BUDGET))
    assert ok2.get("ok") is True, ok2
    # 第 3 条（2 条在推）⇒ 拒
    blocked = f.create_plan("新方向三", "PK-N3", budget=dict(BUDGET))
    assert blocked.get("kind") == "parallel_plans_limit", blocked

    # `stalled` 计入：另一个桶里放两条 stalled ⇒ 它也满员
    store2 = _ws(tmp_path / "stalled")
    f2 = _f(store2)
    _seed_plan(store2, key="PK-S1", status="stalled")
    _seed_plan(store2, key="PK-S2", status="stalled")
    blocked2 = f2.create_plan("再一条", "PK-S3", budget=dict(BUDGET))
    assert blocked2.get("kind") == "parallel_plans_limit", blocked2


def test_c_stubbing_the_exclusions_out_turns_b_red(tmp_path: pathlib.Path,
                                                   monkeypatch: pytest.MonkeyPatch) -> None:
    """c 判据（反真空）：把"不计入"的名单打桩成空 ⇒ 同一笔调用必须被拒。

    证明 b 的绿来自"`resolved` / `abandoned` 真的被排除"，而不是来自"上限没生效"。
    """
    store = _ws(tmp_path)
    f = _f(store)
    _seed_plan(store, key="PK-R1", status="resolved")
    _seed_plan(store, key="PK-R2", status="resolved")
    monkeypatch.setattr(CP, "PLAN_CAP_TERMINAL_STATUSES", (), raising=False)
    out = f.create_plan("新方向一", "PK-N1", budget=dict(BUDGET))
    assert out.get("kind") == "parallel_plans_limit", (
        "把「不计入」打桩成空之后仍然建成了 ⇒ b 那条判据是真空的", out)


# ============================================================ d：分桶
def test_d_another_f_does_not_consume_this_fs_quota(tmp_path: pathlib.Path) -> None:
    """d 判据：上限按 `created_by` 分桶 —— 另一个 F 满员不挡这个 F（R1 的兼容面）。

    改前红：改前没有桶（也没有上限）；若按全体计数，这条会失败 —— 而"按研究方向开
    多个 F"正是同一批裁定的另一半，两条不能互相打架。
    """
    store = _ws(tmp_path)
    f1 = _f(store, actor="agent-F-F1")
    f2 = _f(store, actor="agent-F-F2")
    f1.create_plan("F1 的方向甲", "PK-F1A", budget=dict(BUDGET))
    f1.create_plan("F1 的方向乙", "PK-F1B", budget=dict(BUDGET))
    assert f1.create_plan("F1 的方向丙", "PK-F1C",
                          budget=dict(BUDGET)).get("kind") == "parallel_plans_limit"

    out = f2.create_plan("F2 的方向丁", "PK-F2A", budget=dict(BUDGET))
    assert out.get("ok") is True and out.get("created") is True, out
    row = next(r for r in store.rows("attack_plans")
               if str(r.get("plan_id")) == str(out.get("plan_id")))
    assert row["created_by"] == "agent-F-F2", row


# ============================================================ e：归因
def test_e_the_default_actor_is_named_from_the_roster(tmp_path: pathlib.Path) -> None:
    """e 判据：默认 actor（`agent-F`）时，用当前台账号现查名册名补全 `created_by`。

    改前红：改前 `created_by` 恒为 `agent-F` —— 所有 F 实例挤一个桶，"一个 F"无从统计。
    """
    store = _ws(tmp_path)
    parent, child = "t-000001", "t-000002"
    _seed_task(store, task_id=parent, parent="", role="D")
    _seed_task(store, task_id=child, parent=parent, role="F")
    sec = SEC.Secretary("D", root=store.root, store=store)
    got = sec.roster_add(owner=parent, role="F", task_id=child, brief="攻方向：界")
    assert got.get("name"), got
    name = str(got["name"])

    f = AF.AgentF(store, config={"workspace_root": store.root})   # 默认 actor = agent-F
    with CON.calling_as(child, "F"):
        out = f.create_plan("方向", "PK-DEFAULT", budget=dict(BUDGET))
    assert out.get("ok") is True, out
    row = next(r for r in store.rows("attack_plans")
               if str(r.get("plan_id")) == str(out.get("plan_id")))
    assert row["created_by"] == f"agent-F-{name}", (row, name)


if __name__ == "__main__":          # pragma: no cover - 手工跑这一份时用
    raise SystemExit(pytest.main([__file__, "-q"]))

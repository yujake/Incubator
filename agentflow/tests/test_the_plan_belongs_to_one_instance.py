# -*- coding: utf-8 -*-
"""K3 + K4：计划归属按实例、活跃上限按「我在推的」、轮次写回在锁内合并且不丢行。

## 业主口径 / 清单（`temp/master/MASTER-INVENTORY.csv` 的 K3 / K4）

K3 的根因一句：`created_by` 只被「同时最多 2 条计划」的分桶读；list / status / step /
abandon / 判重全不看归属；推进一轮计划的预算读数也从不注入（每轮 unknown）。

K4 的根因一句：rounds / history / 子目标状态 / best_partial 都是计划级单格，写回是
「事务外读到的整行 upsert」—— 两个实例并发各推一轮，后提交的那一笔把前一笔的
history 行整段覆盖掉。

## 判据（每条都先看过红；红的样子写在各自的 docstring 里）

| # | 判据 | 改前红在哪 |
|---|---|---|
| a | 非属主 `step` 别人的计划 ⇒ 受控拒 `plan_not_yours`，台账一个字节不动 | 改前照推，且能把属主的计划推到 `stalled`（AUDIT-F：plan 000001 的 r3 由 t-000015 推、r5/r6 由 t-000049 推，20:19:22 由 t-000049 推到 stalled，seq 4150） |
| b | 非属主 `abandon_plan` 别人的计划 ⇒ 受控拒，`status` / `history` 不动 | 改前照放弃（plan 000000 的 stalled 由非属主 t-000030 在 19:44:39 触发，seq 2600 的同族） |
| c | `list_plans` 只列自己名下，每条显式带 `created_by` | 改前列全表 |
| d | 「活跃≤2」按每个实例自己在推的活跃计划计数：A 已推 2 条 ⇒ A 被拒；B 名下 0 条 ⇒ B 建成；A 推不动 B 的那条（所以「A 在推 3 条」在盘上不成立） | 改前按「注册的」算而 step 不看归属 ⇒ 出现「拒 A 时 A 实际在推 3 条 / B 桶内 0 条却放错桶」 |
| e | 两个进程并发各推一轮同一计划 ⇒ history 两轮都在（不丢行），`rounds` 加了两轮 | 改前事务外整行 upsert：后提交的那笔把先提交的 history 行覆盖掉 |
| f | `step` 返回 `budget_known=True` 且带读数（账本 + 预算寄存器现读） | 改前恒 `unknown`（工具路径没有任何注入点：22/22 趟 `budget_known=False`） |
| g | 负控：属主推进/放弃自己的计划照常；单实例建第 3 条活跃计划该拒 | —— |
| h | 反真空：把归属判定打桩成恒真 ⇒ a / b 必红；把 `lifecycle.active_plans` 打桩成空 ⇒ d 必红 | —— |
| i | 不占轮次的那两行（超预算修补轮 / 放弃行）的 `round` 不比已落的最大 `round` 小 ⇒ 属主推得动、也放弃得了（真机 lp-ball-8 的 plan 000001 现场：rounds=6 而 history 已到 round 7） | 改前写 `rounds` ⇒ schema 单调不减把整笔写回拒掉（`history[7].round=6 小于前一轮 7`） |

## 边界

全部 `tmp_path` 工作区；不读写 `projects/`；不起真机（`step` 不接线模型缝，走
`_seam_missing_round` 那一档）；e 用 `multiprocessing`（spawn，真进程 —— 本沙箱禁止
命名管道，所以子进程用文件回报，与 `test_store_concurrency.py` 同一套写法）。
"""
from __future__ import annotations

import json
import multiprocessing as mp
import pathlib
import sys
import time
from typing import Any

import pytest

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agentflow import agent_f as AF
from agentflow import budget as BUDGET_REG
from agentflow import lifecycle as L
from agentflow.store import Store

BUDGET = {"max_rounds": 3, "max_parallel_subgoals": 2,
          "max_persist_attempts": 2, "max_depth": 2}
#: 两个实例的归属键（`agent-<role>-<规范实例标签>`，与 `identity.actor_for` 同格式）。
A = "agent-F-F1"
B = "agent-F-F2"


def _ws(path: pathlib.Path) -> Store:
    st = Store(path / "ws")
    st.init()
    return st


def _f(store: Store, actor: str) -> AF.AgentF:
    return AF.AgentF(store, config={"workspace_root": store.root}, actor=actor)


def _sg(sid: str = "s1", **over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "sid": sid, "text": "子目标一：把界算出来", "owner": "F", "status": "todo",
        "evidence_ids": [], "experiment_ids": [], "proof_experiment_ids": [],
        "blocked_reason": "", "attempts": 0, "negation_kind": None,
        "testable": "能判：算出常数",
    }
    row.update(over)
    return row


def _seed_plan(store: Store, *, owner: str, key: str = "PK-SEED", status: str = "open",
               rounds: int = 0, budget: dict[str, int] | None = None,
               subgoals: list[dict[str, Any]] | None = None,
               history: list[dict[str, Any]] | None = None) -> str:
    """直接落一条计划行（造「别人的计划已经在盘上」的现场；不经过 `create_plan`）。"""
    with store.tx("attack_plans", actor="test") as tx:
        pid = tx.alloc_id("plan")
        tx.upsert("attack_plans", {
            "plan_id": pid, "problem": f"难题 {key}", "problem_key": key,
            "status": status, "rounds": int(rounds), "budget": dict(budget or BUDGET),
            "subgoals": [dict(s) for s in (subgoals if subgoals is not None else [_sg()])],
            "history": [dict(h) for h in (history or [])], "depth": 0,
            "best_partial": ("停下来时的最好部分结果" if status == "stalled" else ""),
            "created_by": owner,
        })
    return pid


def _row(store: Store, pid: str) -> dict[str, Any]:
    return next(dict(r) for r in store.rows("attack_plans")
                if str(r.get("plan_id")) == str(pid))


def _create(f: AF.AgentF, key: str, *, budget: dict[str, int] | None = None) -> dict:
    return f.create_plan(f"难题 {key}", key, budget=dict(budget or BUDGET),
                         subgoals=[_sg()])


# ============================================================ a：非属主 step
def test_a_a_foreign_instance_cannot_push_a_round_into_someone_elses_plan(
        tmp_path: pathlib.Path) -> None:
    """a 判据：`step` 读归属；不是自己的计划 ⇒ 受控拒，行一个字节不动。

    改前红（逐字）：`f2.step(pid)` 返回 `ok=True` 的那一份读数、`rounds` 变 2，
    而且因为 `max_rounds=1/rounds=1`，这一推直接把属主的计划写成 `status="stalled"`
    —— 真机读数就是这条：`plan 000001` 六轮里属主只拿 3 轮，r5/r6 由 t-000049 推，
    `20:19:22` 由 t-000049 推到 stalled（seq 4150）。
    """
    store = _ws(tmp_path)
    pid = _seed_plan(store, owner=A, budget={**BUDGET, "max_rounds": 1}, rounds=1)

    f2 = _f(store, B)
    with pytest.raises(AF.PlanError) as ei:
        f2.step(pid)
    assert "plan_not_yours" in str(ei.value), str(ei.value)

    row = _row(store, pid)
    assert row["status"] == "open", row
    assert int(row["rounds"]) == 1, row
    assert list(row["history"]) == [], row


# ============================================================ b：非属主 abandon
def test_b_a_foreign_instance_cannot_abandon_someone_elses_plan(
        tmp_path: pathlib.Path) -> None:
    """b 判据：`abandon_plan` 读归属；不是自己的计划 ⇒ 受控拒，`status`/`history` 不动。

    改前红（逐字）：`f2.abandon_plan(pid, reason="不再需要")` 返回
    `{"ok": True, "status": "abandoned", ...}` —— 非属主把属主的计划关掉了
    （AUDIT-F：plan 000000 的 stalled 由非属主 t-000030 在 19:44:39 触发，seq 2600）。
    """
    store = _ws(tmp_path)
    pid = _seed_plan(store, owner=A)

    f2 = _f(store, B)
    with pytest.raises(AF.PlanError) as ei:
        f2.abandon_plan(pid, reason="不再需要", basis="夹具：不是我的计划")
    assert "plan_not_yours" in str(ei.value), str(ei.value)

    row = _row(store, pid)
    assert row["status"] == "open", row
    assert list(row["history"]) == [], row


# ============================================================ c：list_plans 只看自己
def test_c_list_plans_only_lists_your_own_and_names_the_owner(
        tmp_path: pathlib.Path) -> None:
    """c 判据：`list_plans` 只列自己名下，且每条显式带 `created_by`。

    改前红（逐字）：`f2.list_plans()["total"] == 2`（列全表，包含 F1 的那条）。
    """
    store = _ws(tmp_path)
    f1, f2 = _f(store, A), _f(store, B)
    mine = str(_create(f1, "PK-C1")["plan_id"])
    theirs = str(_create(f2, "PK-C2")["plan_id"])

    view2 = f2.list_plans()
    assert view2["checked"] is True, view2
    ids2 = [str(x.get("plan_id")) for x in view2["plans"]]
    assert ids2 == [theirs], (ids2, theirs, mine)
    assert [str(x.get("created_by")) for x in view2["plans"]] == [B], view2["plans"]
    assert view2["total"] == 1, view2

    view1 = f1.list_plans()
    assert [str(x.get("plan_id")) for x in view1["plans"]] == [mine], view1
    assert [str(x.get("created_by")) for x in view1["plans"]] == [A], view1["plans"]

    # `include_terminal=False` 仍只在自己名下（过滤与归属是两条判据，不能互相顶掉）。
    f1.abandon_plan(mine, reason="不再需要", basis="夹具")
    assert f1.list_plans(include_terminal=False)["total"] == 0, f1.list_plans()
    assert f2.list_plans(include_terminal=False)["total"] == 1, f2.list_plans()


# ============================================================ d：上限按「我在推的」
def test_d_the_cap_counts_what_this_instance_is_pushing(
        tmp_path: pathlib.Path) -> None:
    """d 判据：上限按每个实例「自己在推的」活跃计划计数（不是「我注册的」）。

    - A 已推 2 条活跃 ⇒ A 建第 3 条被拒（`parallel_plans_limit`），拒信点名那两条；
    - B 名下 0 条 ⇒ B 建得成，`created_by` 是 B；
    - A 推不动 B 的那条（归属判据）⇒「A 实际在推 3 条」这种形态不再成立。

    改前红（逐字）：A 那句 `create_plan` 确实会被拒（按 `created_by` 分桶已经对），
    但同一时刻 `f1.step(B 的计划)` 返回 `ok=True` ⇒ A 桶里 2 条、实际在推 3 条 ——
    这正是清单点名的「拒 A 时实际在推 3 条」。
    """
    store = _ws(tmp_path)
    f1, f2 = _f(store, A), _f(store, B)
    a1 = str(_create(f1, "PK-D1")["plan_id"])
    a2 = str(_create(f1, "PK-D2")["plan_id"])

    # B 名下 0 条 ⇒ 建得成（放错桶的话这里会跟着 A 一起被拒）。
    made_b = _create(f2, "PK-D3")
    assert made_b.get("ok") is True and made_b.get("created") is True, made_b
    b1 = str(made_b["plan_id"])
    assert _row(store, b1)["created_by"] == B, _row(store, b1)

    # A 的第 3 条：被拒，且拒信点名 A 自己那两条。
    blocked = _create(f1, "PK-D4")
    assert blocked.get("kind") == "parallel_plans_limit", blocked
    err = str(blocked.get("error") or "")
    assert a1 in err and a2 in err, err

    # A 推不动 B 的那条 ⇒「A 在推 3 条」不成立。
    with pytest.raises(AF.PlanError) as ei:
        f1.step(b1)
    assert "plan_not_yours" in str(ei.value), str(ei.value)
    # 而 B 自己推得动（同一个上限、同一条路径：拒的是归属，不是"所有推进"）。
    assert f2.step(b1)["plan_id"] == b1


# ============================================================ e：并发写回不丢行
def _step_worker(root: str, plan_id: str, tag: str) -> None:
    """子进程 worker：等一个起跑线，然后推一轮同一计划（回报写文件，不走管道）。"""
    import traceback

    out_dir = pathlib.Path(root) / "out" / "_k4_workers"
    out_dir.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {"tag": tag, "ok": False, "error": None,
                              "round": None, "status": None}
    try:
        from agentflow import agent_f as _AF
        from agentflow.store import Store as _Store

        st = _Store(root)
        agent = _AF.AgentF(st, config={"workspace_root": st.root}, actor="agent-F-F1")
        (out_dir / f"{tag}.started").write_text("1", encoding="utf-8")
        got = agent.step(plan_id)
        report.update(ok=True, round=got.get("round"), status=got.get("status"))
    except BaseException:  # noqa: BLE001 —— 子进程里的失败要带回去，不许静默
        report["error"] = traceback.format_exc()
    (out_dir / f"{tag}.json").write_text(json.dumps(report, ensure_ascii=False),
                                         encoding="utf-8")


def _wait_for(paths: list[pathlib.Path], timeout: float = 30.0) -> list[bool]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if all(p.is_file() for p in paths):
            return [True] * len(paths)
        time.sleep(0.02)
    return [p.is_file() for p in paths]


def test_e_two_instances_pushing_one_round_each_keep_both_history_rows(
        tmp_path: pathlib.Path) -> None:
    """e 判据：两个进程并发各推一轮 ⇒ history 两轮都在，`rounds` 是 2。

    为什么这样造红：父进程先持住 `attack_plans` 的跨进程锁，再放两个子进程进去。
    两边都会先读到同一份 `rounds=0` 的快照、然后卡在写回那把锁上。改前那一笔写回
    是「事务外读到的整行 upsert」⇒ 后提交的把先提交的 history 整段覆盖掉
    （实测：`len(history)==1`、`rounds==1`）。改后写回在事务内重读 + 按增量合并 ⇒
    两行都在、`rounds==2`。
    """
    store = _ws(tmp_path)
    pid = _seed_plan(store, owner=A, key="PK-E", subgoals=[_sg()])

    from filelock import FileLock

    lock_path = pathlib.Path(store.root) / "data" / ".locks" / "attack_plans.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    holder = FileLock(str(lock_path))
    holder.acquire(timeout=10)
    ctx = mp.get_context("spawn")
    procs = [ctx.Process(target=_step_worker, args=(str(store.root), pid, tag))
             for tag in ("a", "b")]
    try:
        for p in procs:
            p.start()
        started = [pathlib.Path(store.root) / "out" / "_k4_workers" / f"{t}.started"
                   for t in ("a", "b")]
        assert all(_wait_for(started)), "子进程没跑到起跑线（夹具坏了，不是判据的结论）"
        time.sleep(0.4)          # 让两边都读过计划、卡在写回那把锁上
    finally:
        holder.release()
    for p in procs:
        p.join(timeout=60)
    assert all(p.exitcode == 0 for p in procs), [p.exitcode for p in procs]
    reports = [json.loads((pathlib.Path(store.root) / "out" / "_k4_workers" / f"{t}.json")
                          .read_text(encoding="utf-8")) for t in ("a", "b")]
    assert all(r.get("ok") for r in reports), reports

    row = _row(store, pid)
    history = list(row.get("history") or [])
    assert len(history) == 2, (
        "两轮里有一轮被覆盖掉了（写回还是事务外的整行 upsert？）", history)
    assert int(row["rounds"]) == 2, row
    assert {str(h.get("sid")) for h in history} == {"s1"}, history


# ============================================================ f：预算读数
def test_f_a_pushed_round_carries_a_real_budget_reading(tmp_path: pathlib.Path) -> None:
    """f 判据：`step` 的返回里 `budget_known=True` 且带读数（不是恒 `unknown`）。

    改前红（逐字）：工具路径上没有任何地方注入 `budget_reading` ⇒
    `budget_reading={"status": "unknown", ..., "why": "调用方没有注入预算读数…"}`、
    `budget_known=False`（清单：22/22 趟 step 都是这一档）。
    """
    store = _ws(tmp_path)
    BUDGET_REG.write_initial(store.root, 5.0, by="test", note="K3 判据夹具")
    f1 = _f(store, A)
    pid = str(_create(f1, "PK-F")["plan_id"])

    out = f1.step(pid)
    reading = dict(out.get("budget_reading") or {})
    assert out.get("budget_known") is True, out
    assert reading.get("status") == "known", reading
    assert float(reading.get("left_usd")) == pytest.approx(5.0), reading
    assert float(reading.get("spent_usd")) == pytest.approx(0.0), reading
    assert reading.get("why") == "", reading
    # 预算读数不是"只有返回值里才有"：`budget_left` 那一格照旧在（轮数轴）。
    assert out.get("budget_left"), out


# ============================================================ g：负控
def test_g_the_owner_can_still_push_and_abandon_its_own_plan(
        tmp_path: pathlib.Path) -> None:
    """g 判据（负控）：属主推进自己的计划、放弃自己的计划都照常；第 3 条照旧被拒。

    这一条防的是「把归属判据写成谁都推不动」：它必须与 a/b 同时成立。
    """
    store = _ws(tmp_path)
    f1 = _f(store, A)
    p1 = str(_create(f1, "PK-G1")["plan_id"])
    p2 = str(_create(f1, "PK-G2")["plan_id"])

    got = f1.step(p1)
    assert got.get("plan_id") == p1 and got.get("status"), got
    assert int(_row(store, p1)["rounds"]) == 1, _row(store, p1)

    out = f1.abandon_plan(p2, reason="不再需要", basis="夹具：属主自己放弃")
    assert out.get("ok") is True and out.get("status") == "abandoned", out
    assert _row(store, p2)["status"] == "abandoned", _row(store, p2)

    # 属主的第 3 条（p1 还活着 + 一条新的活着）⇒ 该拒。
    p3 = _create(f1, "PK-G3")
    assert p3.get("created") is True, p3
    assert _create(f1, "PK-G4").get("kind") == "parallel_plans_limit", _create(f1, "PK-G4")


# ============================================================ h：反真空
def test_h_stubbing_the_owner_check_or_the_active_set_turns_a_b_d_red(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """h 判据（反真空）：两处打桩各造一次红，证明 a/b/d 的绿来自那两条判据本身。

    ① 把归属判定打桩成"恒真"（谁看都是自己的）⇒ a 不拒了、b 放弃成功了
       （a/b 的绿只能来自 `_plan_owner_of`）；
    ② 把 `lifecycle.active_plans` 打桩成空 ⇒ A 的第 3 条建成了
       （d 的绿只能来自那个活跃集读数）。
    """
    store = _ws(tmp_path)
    pid = _seed_plan(store, owner=A)
    f2 = _f(store, B)

    def _always_mine(self: AF.AgentF, row: Any) -> dict:  # noqa: ANN001, ARG001
        return {"checked": True, "mine": str(self.actor or ""),
                "owner": str((row or {}).get("created_by") or ""),
                "owned": True, "foreign": False, "unowned": False,
                "why": "反真空：归属判定被打桩成恒真"}

    monkeypatch.setattr(AF.AgentF, "_plan_owner_of", _always_mine)
    assert f2.step(pid).get("plan_id") == pid, "打桩成恒真之后仍然推不动 ⇒ a 的绿不是来自归属判定"
    out = f2.abandon_plan(pid, reason="不再需要", basis="反真空")
    assert out.get("status") == "abandoned", out

    # ② 活跃集打桩成空 ⇒ 第 3 条建得出来（d 的绿来自 `lifecycle.active_plans`）。
    store2 = _ws(tmp_path / "cap")
    f1 = _f(store2, A)
    _create(f1, "PK-H1")
    _create(f1, "PK-H2")
    monkeypatch.setattr(
        L, "active_plans",
        lambda *a, **kw: {"checked": True, "kind": "plan", "total": 0, "active": 0,
                          "ids": [], "rows": [], "unjudged": [], "checked_plans": 0,
                          "why": "反真空：活跃集被打桩成空"})
    made = _create(f1, "PK-H3")
    assert made.get("created") is True, (
        "活跃集打桩成空之后第 3 条仍被拒 ⇒ d 的绿不是来自 `lifecycle.active_plans`", made)


# ============================================================ i：不占轮次的行也单调
def test_i_rows_that_do_not_take_a_round_still_advance_the_round_counter(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """i 判据：修补轮与放弃行的 `round` 不比已落的最大 `round` 小。

    真机现场（只读复算）：`projects/lp-ball-8` 的 plan 000001 是 rounds=6、history 已到
    round 7（停止那一行写的是 `rounds + 1`）。属主再推一轮是「超预算修补轮」（`rounds`
    不涨）、放弃也不涨轮次 —— 那两行若仍写 `round=rounds`（6），就落在 7 前面，
    `AttackPlan.validate` 的单调不减当场拒掉整笔写回：属主既推不动也放弃不了。
    改前红（逐字）：`PlanError: 计划 '000001' 的写回内容不合 schema 硬约束 ⇒ 未写回：
    history[7].round=6 小于前一轮 7：轮次必须单调不减`。
    """
    store = _ws(tmp_path)
    hist = [
        {"round": 1, "sid": "s1", "action": "no_change", "outcome": "no_change",
         "detail": "夹具：第 1 轮", "evidence": [], "at": "2026-11-18T19:47:30+08:00"},
        {"round": 2, "sid": "s1", "action": "proof", "outcome": "progress",
         "detail": "夹具：第 2 轮", "evidence": [], "at": "2026-11-18T19:52:19+08:00"},
        {"round": 3, "sid": "s1", "action": "proof", "outcome": "progress",
         "detail": "夹具：第 3 轮", "evidence": [], "at": "2026-11-18T20:07:51+08:00"},
        {"round": 4, "sid": None, "action": "stop", "outcome": "no_change",
         "detail": "夹具：停止行（round = rounds + 1）", "evidence": [],
         "at": "2026-11-18T20:08:02+08:00"},
    ]
    pid = _seed_plan(store, owner=A, key="PK-I", status="attacking", rounds=3,
                     budget={**BUDGET, "max_rounds": 3},
                     subgoals=[_sg("s1"), _sg("s2")], history=hist)
    # 稿没签 ⇒ 不许判 stalled：这一轮才落成「超预算修补轮」（`_finish_gate` 不是本条的判据）。
    monkeypatch.setattr(AF.AgentF, "_finish_gate",
                        lambda self, row: {"finished": False, "why": "夹具：稿没签"})
    f1 = _f(store, A)

    out = f1.step(pid)
    assert out.get("plan_id") == pid, out
    row = _row(store, pid)
    rounds_now = [int(h.get("round") or 0) for h in (row.get("history") or [])]
    assert rounds_now == sorted(rounds_now), ("history 的 round 不是单调不减的", rounds_now)
    assert rounds_now[-1] >= 4, (rounds_now, row)
    assert int(row.get("rounds") or 0) == 3, ("修补轮不许把 rounds 推过 max_rounds", row)

    got = f1.abandon_plan(pid, reason="不再需要", basis="夹具：属主自己放弃")
    assert got.get("ok") is True and got.get("status") == "abandoned", got
    row = _row(store, pid)
    rounds_now = [int(h.get("round") or 0) for h in (row.get("history") or [])]
    assert rounds_now == sorted(rounds_now), ("放弃行的 round 落在了前面", rounds_now)
    assert str((row.get("history") or [])[-1].get("action")) == "abandon", row


if __name__ == "__main__":          # pragma: no cover - 手工跑这一份时用
    raise SystemExit(pytest.main([__file__, "-q"]))
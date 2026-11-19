# -*- coding: utf-8 -*-
"""判据：猜想台账是一份台账，不是「最后一次写的人说了算」的日志（FIX186-E/F/G）。

## 现场（`temp/r11c/REPORT.md`）

```text
E 的每一笔都落同一行：run_experiment.py:771 的 counterexample_experiment_id=(eid if refutes else "")
                     + conjectureledger.py:243-246 的 experiment_ids 是替换不是并集
⇒ lp-ball-11 的 c000002 共 11 次写（seq=1036…1541）：
  最后一次（17:26:32 supported_not_proved）把「refuted / 反例 exp:000002」静默抹掉，
  最终 status=有支持、counterexample_experiment_id 为空，而 notes 里还写着 exp:000002 refutes。
```

## 判据

| # | 判据 | 改前红在哪 |
|---|---|---|
| e | 登记成功即写 `registered_stmt_id`（落盘）⇒「待登记」视图与 `conjecture_rows` 都不再数它；反真空：未登记的仍出现 | 改前只往 `notes` 塞 `[landed]`（全仓 0 个消费者） |
| f | c000002 的 11 次写重放 ⇒ 最终 `status=refuted`、反例号非空、`experiment_ids` 是 11 条的并集 | 改前最终 `supported_not_proved` + 反例号空 + 只剩 exp:000017 |
| f-反真空 | 按改前的替换语义重放同一批写 ⇒ 红（supported / 空反例号） | 证明 f 的绿由并集与两条守卫给出 |
| g | `conjectures` 进 `_BLOCKING_TARGETS`：被一条计划的 `problem_key` 引用 ⇒ 删除受控拒；反真空：没被引用 ⇒ 删得掉 | 改前 `table.delete` 放行，留下悬空引用 |
| g2 | `agent_skills` 的 D 那一跳与「三件活」不再教「D 立猜想」（与 `specs/a.py` 一致） | 改前 D 的产物写「待登记命题（`conjectures`）一条」 |

## 边界

`tmp_path` 工作区；不读写 `projects/`。真实副本上的复算见 `temp/fix186/judge_e_lp11.py`。
"""
from __future__ import annotations

import pathlib
import sys
from typing import Any

import pytest

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agentflow import agent_skills as AS        # noqa: E402
from agentflow import closing as CL             # noqa: E402
from agentflow import conjectureledger as CLed  # noqa: E402
from agentflow import schema as S               # noqa: E402
from agentflow.conductor import Conductor       # noqa: E402
from agentflow.store import Store               # noqa: E402
from agentflow.tools import table_tools         # noqa: E402
from agentflow.tools.base import ToolRegistry   # noqa: E402

CONJECTURE = "夹具猜想：对一切整数 n≥1，n^2+n 恒为偶数。"
STMT_ID = "000007"


def _store(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _add_conjecture(st: Store, *, testable: dict | None = None) -> str:
    got = CLed.register(
        store=st, statement=CONJECTURE, origin="experiment:000001",
        status="proposed", testable=dict(testable or {"params": {"n": "≥1"}}),
        form="universal", actor="agent-E-F1")
    return str(got.get("conjecture_id") or "")


def _row(st: Store, cid: str) -> dict:
    return next(dict(r) for r in st.rows("conjectures")
                if str(r.get("conjecture_id") or "") == cid)


# ============================================================ e：登记即毕业
def test_e_a_landed_conjecture_leaves_the_pending_views(tmp_path: pathlib.Path) -> None:
    """e：写 `registered_stmt_id` 之后，「待登记」视图与 `conjecture_rows` 都不再数它。"""
    st = _store(tmp_path)
    cid = _add_conjecture(st)
    board = Conductor(st)
    assert [x["conjecture_id"] for x in board._pending_attack_items()] == [cid]
    count, detail = CL._leg_reading(st, "conjecture_rows", pathlib.Path(st.root))
    assert count == 1 and detail["total_conjectures"] == 1, (count, detail)

    CLed.register(store=st, statement=CONJECTURE, origin="experiment:000001",
                  registered_stmt_id=STMT_ID, actor="agent-B")
    # 落盘事实：换一个 Store 重新读盘也读得到（不是进程内缓存）。
    fresh = _row(Store(st.root), cid)
    assert fresh["registered_stmt_id"] == STMT_ID, fresh
    assert board._pending_attack_items() == [], board._pending_attack_items()
    count, detail = CL._leg_reading(Store(st.root), "conjecture_rows",
                                    pathlib.Path(st.root))
    assert count == 0, (count, detail)
    assert detail["registered_conjectures"] == 1, detail
    assert detail["total_conjectures"] == 1, detail


def test_e2_an_unregistered_conjecture_still_shows_up(tmp_path: pathlib.Path) -> None:
    """e-反真空：没登记的猜想仍在「待登记」视图与计数里。"""
    st = _store(tmp_path)
    cid = _add_conjecture(st)
    assert _row(st, cid).get("registered_stmt_id") == "", _row(st, cid)
    assert [x["conjecture_id"] for x in Conductor(st)._pending_attack_items()] == [cid]
    count, _detail = CL._leg_reading(st, "conjecture_rows", pathlib.Path(st.root))
    assert count == 1


# ============================================================ f：并集 + 两条守卫
#: lp-ball-11 的 c000002 那 11 次写（`data/events.jsonl` seq / status /
#: experiment_ids 当场那一格 / counterexample_experiment_id 当场那一格）。
C000002_WRITES: tuple[tuple[int, str, str, str], ...] = (
    (1036, "refuted", "000002", "000002"),
    (1057, "testing", "000003", ""),
    (1220, "testing", "000007", ""),
    (1255, "refuted", "000009", "000009"),
    (1312, "testing", "000011", ""),
    (1389, "refuted", "000012", "000012"),
    (1445, "testing", "000013", ""),
    (1498, "testing", "000014", ""),
    (1511, "testing", "000015", ""),
    (1528, "testing", "000016", ""),
    (1541, "supported_not_proved", "000017", ""),
)


def _seed_experiments(st: Store, ids: set[str]) -> None:
    with st.tx("experiments", actor="test") as tx:
        for eid in sorted(ids):
            tx.upsert("experiments", {
                "experiment_id": eid, "claim": CONJECTURE, "claim_key": "fixture:even",
                "method": "numeric",
                "code_path": f"code/fixture-{eid}.py", "code_hash": "0" * 16,
                "exit_code": 0, "result": "inconclusive",
                "negation_kind": "not_proved", "metrics": {},
                "created_at": S.now_iso(), "created_by": "agent-E"})


def _replay(st: Store, writes: tuple[tuple[int, str, str, str], ...]) -> dict:
    """按 E 的写口重放（与 `run_experiment.py` 那一笔逐参同形）。"""
    out: dict[str, Any] = {}
    for _seq, status, eid, cex in writes:
        out = CLed.register(
            store=st, statement=CONJECTURE, origin="experiment:000002",
            status=status, experiment_ids=[eid],
            counterexample_experiment_id=cex, actor="agent-E-num-corro-1")
    return out


def test_f_the_eleven_writes_do_not_erase_the_counterexample(tmp_path: pathlib.Path) -> None:
    """f：重放 11 次写 ⇒ 仍是 refuted、反例号非空、11 条实验都在。"""
    st = _store(tmp_path)
    _seed_experiments(st, {w[2] for w in C000002_WRITES})
    out = _replay(st, C000002_WRITES)
    row = _row(st, str(out["conjecture_id"]))
    assert row["status"] == "refuted", row
    assert row["counterexample_experiment_id"] == "000012", row
    assert row["experiment_ids"] == sorted({w[2] for w in C000002_WRITES}), row


def test_f2_the_old_replace_semantics_would_have_ended_supported_and_empty(
        tmp_path: pathlib.Path) -> None:
    """f-反真空：按改前的「整格替换」重放同一批写 ⇒ supported + 反例号空。

    这一条不碰产品代码：它用 `schema.Conjecture` + `tx.upsert` 复算改前那一份语义，
    证明 f 的绿确实来自"并集 + 两条守卫"，而不是因为那批写恰好以 refuted 收尾。
    """
    st = _store(tmp_path)
    _seed_experiments(st, {w[2] for w in C000002_WRITES})
    with st.tx("conjectures", actor="test") as tx:
        legacy = S.Conjecture(conjecture_id="000000", statement=CONJECTURE,
                              origin="experiment:000002", status="testing")
        for _seq, status, eid, cex in C000002_WRITES:
            legacy.status = status
            legacy.experiment_ids = [eid]                 # 替换，不是并集
            legacy.counterexample_experiment_id = cex     # 非反例那一笔显式传空
            legacy.validate()
            tx.upsert("conjectures", legacy.to_dict())
    row = _row(st, "000000")
    assert row["status"] == "supported_not_proved", row
    assert row["counterexample_experiment_id"] == "", row
    assert row["experiment_ids"] == ["000017"], row


# ============================================================ g：删除保护 + 教法对齐
@pytest.fixture
def tables(store):
    reg = ToolRegistry(name="fix186-tables")
    reg.bound_role = "A"
    table_tools.register(reg, store=store)
    return reg


def test_g_a_referenced_conjecture_cannot_be_deleted(tables, store: Store) -> None:
    """g：被一条计划的 `problem_key` 引用 ⇒ 删除受控拒（`kind=referenced`）。"""
    cid = _add_conjecture(store)
    with store.tx("attack_plans", actor="test") as tx:
        tx.upsert("attack_plans", {
            "plan_id": "000001", "problem": "夹具攻坚", "problem_key": cid,
            "status": "open", "rounds": 0,
            "budget": {"max_rounds": 3, "max_parallel_subgoals": 2,
                       "max_persist_attempts": 2, "max_depth": 2},
            "subgoals": [], "history": [], "depth": 0, "created_by": "agent-F-F1"})
    res = tables.call("table.delete", table="conjectures", id=cid)
    assert res.ok is False, res
    assert res.meta["kind"] == "referenced", res.meta
    assert "attack_plans" in str(res.error), res.error
    assert _row(store, cid)["conjecture_id"] == cid      # 被拒之后行还在


def test_g2_an_unreferenced_conjecture_is_still_deletable(tables, store: Store) -> None:
    """g-反真空：没被引用的猜想照常删得掉（保护只加在"有引用"那一档）。"""
    cid = _add_conjecture(store)
    res = tables.call("table.delete", table="conjectures", id=cid)
    assert res.ok is True, res
    assert all(str(r.get("conjecture_id")) != cid for r in store.rows("conjectures"))


def test_g3_the_manual_does_not_teach_d_to_register_conjectures() -> None:
    """g2：`agent_skills` 的 D 那一跳与「三件活」与 `specs/a.py` 一致（D 不立猜想）。"""
    chain = next(s for s in AS.CATALOG["M"] if s.slug == "研究攻坚链-文献到收录证明").body
    three = next(s for s in AS.CATALOG["M"] if s.slug == "立项-从一句话到可派的三件").body
    for body, where in ((chain, "研究攻坚链"), (three, "三件活")):
        assert "立可判猜想" not in body, f"{where} 还在教 D 立猜想"
        assert "待登记命题（表 `conjectures`）" not in body, f"{where} 还说 D 落 conjectures"
    assert "不写 `conjectures`" in chain, chain
    assert "不写 `conjectures`" in three, three
    # 反真空：把旧字面量塞回去 ⇒ 断言必须报出来（判据不是空转）。
    bad = chain.replace("不写 `conjectures`", "立可判猜想")
    assert "立可判猜想" in bad and bad != chain


if __name__ == "__main__":          # pragma: no cover - 手工跑这一份时用
    raise SystemExit(pytest.main([__file__, "-q"]))

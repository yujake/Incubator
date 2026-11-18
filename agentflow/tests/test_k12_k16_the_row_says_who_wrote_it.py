# -*- coding: utf-8 -*-
"""K12 / K16 收尾：台账行自己说得出「这一笔是谁的」。

| # | 判据 | 条目 |
|---|---|---|
| a | 猜想台账按规范化正文归并（一条命题一行），但行上记「最后一个写它的人」；`created_by` 不被并进来的第二笔改掉 | SH-10 |
| b | 委托认领落在候选行上（`claimed_by` / `lease_until` / `claimed_at`），租约还在别人手上时第二个 A 一个字节都不写 | AL-11 |

反真空：`updated_by` 只在写入期产生（直接构造的行是空串 = 「没记」）；认领的互斥
只在行上有活租约时生效（租约过期 ⇒ 另一个实例可以接手，与 `search_requests` 同一套语义）。
"""
from __future__ import annotations

import pathlib
import sys

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agentflow import conjectureledger as CL  # noqa: E402
from agentflow import litstage as L  # noqa: E402
from agentflow import store as ST  # noqa: E402
from agentflow.store import Store  # noqa: E402

TEXT = "设 n 为偶数，则 n^2 是 4 的倍数。"
TESTABLE = {"form": "computational", "detail": "枚举偶数 n <= 200，逐条核 n^2 是否能被 4 整除"}


def _store(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


# ------------------------------------------------------------------ a SH-10
def test_a_the_conjecture_row_says_who_moved_it(tmp_path: pathlib.Path) -> None:
    """a：同一条正文两次落账 ⇒ 一行；创建者不动，`updated_by` 是最后那一笔。"""
    st = _store(tmp_path)
    first = CL.register(store=st, statement=TEXT, origin="refusal",
                        testable=dict(TESTABLE), notes="第一笔（D）", actor="agent-D-d1")
    assert first["updated_by"] == "agent-D-d1", first
    second = CL.register(store=st, statement="  " + TEXT + "  ", origin="refusal",
                         status="refuted", refusal_ref="v-000001",
                         notes="第二笔（E 的实验把它否掉了）", actor="agent-E-e1")
    assert second["conjecture_id"] == first["conjecture_id"], second
    assert second.get("duplicate") is True, second
    rows = [dict(r) for r in st.rows("conjectures")]
    assert len(rows) == 1, rows
    assert rows[0]["created_by"] == "agent-D-d1", rows[0]
    assert rows[0]["updated_by"] == "agent-E-e1", rows[0]
    assert rows[0]["status"] == "refuted", rows[0]
    # 反真空：这一格是写入期产生的 —— 老行（没有这个键）读进来是空串「没记」，
    # 不是被悄悄折成创建者，也不是被折成某个默认角色。
    from agentflow import schema as S

    old = S.Conjecture(conjecture_id="000000", statement=TEXT, origin="refusal",
                       status="needs_evidence", notes="老行", created_by="agent-D")
    assert old.to_dict().get("updated_by") == "", old.to_dict()


# ------------------------------------------------------------------ b AL-11
def _stage(st: Store, rid: str) -> None:
    L.stage_entries(st, [{"title": "候选一", "doi": "10.1/a", "relevance": "与本次检索相关"},
                         {"title": "候选二", "doi": "10.1/b", "relevance": "与本次检索相关"}],
                    request_id=rid)


def test_b_a_delegation_claim_is_a_row_and_it_excludes(tmp_path: pathlib.Path) -> None:
    """b：认领落在行上；另一个实例的租约没到期 ⇒ 不写。"""
    st = _store(tmp_path)
    _stage(st, "r-000001")
    mine = L.claim_delegation(st, "r-000001", actor="agent-A-lit")
    assert mine["claimed"] is True and mine["state"] == "mine", mine
    rows = [dict(r) for r in st.rows("lit_candidates") if r.get("request_id") == "r-000001"]
    assert rows and all(r["claimed_by"] == "agent-A-lit" for r in rows), rows
    assert all(str(r["claimed_at"] or "") for r in rows), rows
    # 第二个实例：租约还在 ⇒ 一个字节都不写。
    other = L.claim_delegation(st, "r-000001", actor="agent-A-other")
    assert other["claimed"] is False and other["state"] == "other", other
    assert other["holder"] == "agent-A-lit", other
    rows2 = [dict(r) for r in st.rows("lit_candidates") if r.get("request_id") == "r-000001"]
    assert {r["claimed_by"] for r in rows2} == {"agent-A-lit"}, rows2
    # 反真空：把租约推到过去（模拟"上一支笔挂了"）⇒ 另一个实例可以接手，
    # 与 `search_requests` 的领取同一条三态语义（过期 ≠ 一直归谁）。
    with st.tx("lit_candidates", actor="agent-M", note="判据：把租约推到过去") as tx:
        for r in [dict(x) for x in tx.rows("lit_candidates")]:
            if r.get("request_id") != "r-000001":
                continue
            r["lease_until"] = "2020-01-01T00:00:00+00:00"
            tx.upsert("lit_candidates", r)
    assert ST.lease_expired("2020-01-01T00:00:00+00:00") is True
    taken = L.claim_delegation(st, "r-000001", actor="agent-A-other")
    assert taken["claimed"] is True and taken["state"] == "mine", taken
    rows3 = [dict(r) for r in st.rows("lit_candidates") if r.get("request_id") == "r-000001"]
    assert {r["claimed_by"] for r in rows3} == {"agent-A-other"}, rows3

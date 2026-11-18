# -*- coding: utf-8 -*-
"""K13 判据：实验号按角色分号段 —— E 与 L 各自一格（业主 2026-11-19 口径）。

## 缺口（AUDIT-BA ④-6 / NS-12 已钉）

业主口径「计划号和稿号在拿号时一种角色一套号」。发号器（store.alloc_id）是
「一类实体一格」；今天绝大多数实体类恰好只服务一个角色，唯一不合口径的是
experiment 由 E 与 L 共发：E 写 numeric / symbolic / exhaustive、L 写 formal，
改前共用 counters.experiment 一格（E 发 000000，L 接着发 000001）。

## 这一组守什么

| # | 造什么 | 期望 | 改前读数 |
|---|---|---|---|
| f | E 跑两条实验、L 记一条形式化行 | E 拿 000000 / 000001；L 拿 500000（各自那半段的起点）；counters 里两格分开 | 一条号段：E 占 0/1、L 接着发 2 |
| f′ | 号段本身 | 两段不重叠、合起来是整段编号空间；谁的计数器动不影响另一格 | —— |
| f″ | 审计 | verify_all 不报 counter_behind / id_gap（分号段之后这两条判据各查各段） | —— |

边界：全部 tmp_path 工作区；E 那一支跑真脚本、L 那一支走 record（本机没有真 Lean
时它落 heuristic，号段照样发）；一个模型调用都不发，不碰 projects/。
"""
from __future__ import annotations

import json
import pathlib
import sys

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from conftest import e_form_gate_ok  # noqa: E402
from agentflow import schema as S  # noqa: E402
from agentflow import verify as V  # noqa: E402
from agentflow.agent_e import AgentE  # noqa: E402
from agentflow.agent_l import AgentL  # noqa: E402
from agentflow.store import Store  # noqa: E402

SCRIPT_REL = "code/probe.py"
CLAIM = "网格 n<=3 上 Spec K(m)=[-m,m]"
CLAIM_KEY = "SpecK(m)=[-m,m]"
PROBE = """
import json
print("REPRO_RESULT: " + json.dumps({
    "result": "supports",
    "evidence_kind": "cross_check",
    "observations": {"points": 3},
    "counterexample": None,
    "negation_kind": "not_proved",
    "bound": {"n": 3},
}))
"""
LEAN_REL = "code/formal/add_zero_probe.lean"
LEAN_SOURCE = """import Init.Data.Nat.Basic

namespace LProbe
/-- 一条具体命题：对所有自然数 n，n + 0 = n。 -/
theorem add_zero_probe (n : Nat) : n + 0 = n := rfl
-- step 1
end LProbe
"""


def _ws(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _write(root: pathlib.Path, rel: str, body: str) -> None:
    path = pathlib.Path(root) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body.encode("utf-8"))


def _e(store: Store, instance: str = "E1") -> AgentE:
    return e_form_gate_ok(AgentE(store, config={}, workspace_root=store.root,
                                 actor=f"agent-E-{instance}"))


def _statement(st: Store) -> str:
    sid = S.format_id(1)
    stmt = S.Statement(
        stmt_id=sid, origin="own_result", kind="theorem", label="Theorem 1",
        statement_text="短版", statement_full="forall n : Nat, n + 0 = n",
        proof_text="对任意自然数 n，n + 0 与 n 是同一个项，故由 rfl 即得。",
        quote_verified=None, quote_reason="还没校验：没有可比的全文",
        evidence_kind="heuristic", status="active", created_at=S.now_iso())
    stmt.validate()
    with st.tx("statements", actor="fixture", note="k13 stmt") as tx:
        tx.upsert("statements", stmt.to_dict(), note="k13 stmt")
    return sid


def _l_row(st: Store) -> dict:
    sid = _statement(st)
    _write(st.root, LEAN_REL, LEAN_SOURCE)
    agent = AgentL(st, workspace_root=st.root, actor="agent-L-L1")
    got = agent.record(sid, LEAN_REL, declaration_name="add_zero_probe")
    assert got.get("recorded") is True, got
    row = next(r for r in st.rows("experiments")
               if str(r.get("experiment_id")) == str(got.get("experiment_id")))
    return {"id": str(got["experiment_id"]), "row": dict(row)}


# ============================================================ f：E 与 L 各拿自己的号


def test_f_e_and_l_allocate_from_their_own_segments(tmp_path):
    """f：E 拿 000000 / 000001，L 拿 500000（改前 red：L 从 E 那条号段接着发）。"""
    st = _ws(tmp_path)
    _write(st.root, SCRIPT_REL, PROBE)
    first = _e(st).run_experiment(CLAIM, CLAIM_KEY, SCRIPT_REL, method="numeric")
    second = _e(st).run_experiment(CLAIM, CLAIM_KEY, SCRIPT_REL, method="numeric")
    assert first["experiment_id"] == S.format_id(0), first["experiment_id"]
    assert second["experiment_id"] == S.format_id(1), second["experiment_id"]

    l_row = _l_row(st)
    assert l_row["id"] == S.format_id(500_000), (
        "L 的实验号没有落在它自己那一段（改前的形态：接着 E 的号段发）", l_row["id"])
    assert l_row["row"]["method"] == "formal", l_row["row"]

    counters = json.loads((pathlib.Path(st.root) / "data" / "counters.json")
                          .read_text(encoding="utf-8"))["counters"]
    assert counters.get("experiment") == 2, counters          # E 那一格：000000/000001 之后是 2
    assert counters.get("experiment:L") == 500_001, counters   # L 那一格：500000 之后是 500001

    # E 再发一个号：仍是自己那一段，绝不跨进 L 那半段。
    third = _e(st).run_experiment(CLAIM, CLAIM_KEY, SCRIPT_REL, method="numeric")
    assert third["experiment_id"] == S.format_id(2), third["experiment_id"]


def test_f2_the_two_segments_are_disjoint_and_cover_the_space():
    """f′：两段不重叠、合起来是整段编号空间（号段表的机械读数）。"""
    bands = S.counter_bands("experiment")
    e_lo, e_hi = bands[S.segment_for_role("experiment", "E")]
    l_lo, l_hi = bands[S.segment_for_role("experiment", "L")]
    assert e_lo == 0 and e_hi < l_lo, bands
    assert l_hi == 10 ** S.ID_DIGITS - 1, bands
    assert e_hi + 1 == l_lo, ("两段之间有空隙 ⇒ 有号发不出来", bands)
    assert S.id_counter_key("experiment", "") == "experiment", ("E 那一格必须与改前同键",)
    assert S.id_counter_key("experiment", "L") == "experiment:L"
    # 别的类别没有登记号段 ⇒ 一格、从 0 起（本批只改 experiment 一处）。
    assert S.counter_bands("plan") == {"": (0, 10 ** S.ID_DIGITS - 1)}


def test_f3_verify_does_not_call_the_segments_a_gap(tmp_path):
    """f″：审计不把「L 那半段从 500000 起」读成 id_gap / counter_behind。"""
    st = _ws(tmp_path)
    _write(st.root, SCRIPT_REL, PROBE)
    _e(st).run_experiment(CLAIM, CLAIM_KEY, SCRIPT_REL, method="numeric")
    _l_row(st)
    report = V.verify_all(st)
    issues = [i.to_dict() for i in report.issues]
    # 只判实验号那两条：夹具直接铺的命题行会有它自己的 id_gap / counter_behind，
    # 那是夹具的形态，不是号段的读数。
    assert not [i for i in issues
                if i["code"] == "id_gap" and i["table"] == "experiments"], issues
    assert not [i for i in issues
                if i["code"] == "counter_behind"
                and str(i.get("row_id") or "") in ("experiment", "experiment:L")], issues

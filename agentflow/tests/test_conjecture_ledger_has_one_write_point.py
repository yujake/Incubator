# -*- coding: utf-8 -*-
"""判据 ③(c)(d)：临时命题由产出侧落账，且只有这一个写点。

## 业主 2026-11-13 裁定甲（逐字）

> 「D 不该立项临时命题，D 只给研究方向让下面的人去研究，请确认 D 自己这没有自己的一套命题。」

改前的真机读数（`projects/*/data/conjectures.json`，42 个工作区 111 行）：`created_by`
全部是 `agent-D`，而且 D 会把 E 的实验号、F 的稿 + V 的签、B 的拒收读进来自己改
`status` 与 `notes`（证据：`projects/octahedron-20261113/sessions/20261113.jsonl:1550`）。

## 这一份钉的四条

| # | 判据 |
|---|---|
| a | E 起手：跑一次真实验（`AgentE.run_experiment`，`result=supports`）⇒ `conjectures` 有一行，状态 `supported_not_proved`、`experiment_ids` 就是那一条、`created_by` 是 E |
| b | 被拒那一档：`result=refutes` ⇒ 同一行落 `refuted` + `counterexample_experiment_id`（裁定 ② 的第一条来路） |
| c | 反真空：把 `conjectureledger.register` 打桩成"不写" ⇒ a 必红（证明那行真的来自产出侧这一笔，而不是别处顺手写的） |
| d | 同一个写点：`conjecture.register_conjecture` 不在工具面上，通用写口也拒 `conjectures`（后门堵上） |

零真实模型：形态闸读预置缓存（`conftest.e_form_gate_ok`）。
"""

from __future__ import annotations

import json
import pathlib
import sys

import pytest

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from conftest import e_form_gate_ok  # noqa: E402
from agentflow import conjectureledger as CL  # noqa: E402
from agentflow.agent_e import AgentE  # noqa: E402
from agentflow.store import Store  # noqa: E402
from agentflow.tools import build_registry  # noqa: E402

CLAIM = "设 n<=10，则扫描全部 100 个点都满足 P(n)。"
SCRIPT_REL = "code/scan.py"

SUPPORTS_PROBE = """
import json
print("REPRO_RESULT: " + json.dumps({
    "result": "supports", "evidence_kind": "cross_check",
    "observations": {"points": 100, "grid": 10},
    "counterexample": None, "negation_kind": "not_proved",
}))
"""

REFUTES_PROBE = """
import json
print("REPRO_RESULT: " + json.dumps({
    "result": "refutes", "evidence_kind": "cross_check",
    "observations": {"points": 100, "n": 3},
    "counterexample": {"n": 3, "value": 0},
    "negation_kind": "counterexample",
}))
"""


def _store(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _run(st: Store, body: str) -> dict:
    path = pathlib.Path(st.root) / SCRIPT_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    e = e_form_gate_ok(AgentE(st, config={}, workspace_root=st.root))
    return e.run_experiment(CLAIM, "scan=100", SCRIPT_REL, method="numeric")


# ============================================================ a E 起手

def test_a_e_runs_one_experiment_and_the_ledger_gets_one_row(tmp_path):
    """a：一次真实验 ⇒ `conjectures` 一行，状态由 `result` 现算，`created_by` 是 E。"""
    st = _store(tmp_path)
    out = _run(st, SUPPORTS_PROBE)
    rows = [dict(r) for r in st.rows("conjectures")]
    assert len(rows) == 1, rows
    row = rows[0]
    eid = str(out.get("experiment_id") or "")
    assert row["statement"] == CLAIM, row
    assert row["status"] == "supported_not_proved", row
    assert row["experiment_ids"] == [eid], row
    assert row["origin"] == f"experiment:{eid}", row
    assert "E" in str(row["created_by"]), row
    # 回执里也要能看见（E 那一趟的读数）
    ledger = dict(out.get("conjecture_ledger") or {})
    assert ledger.get("ok") is True and ledger.get("conjecture_id") == row["conjecture_id"], ledger


# ============================================================ b 被拒那一档

def test_b_a_refuting_experiment_lands_refuted_with_the_counterexample(tmp_path):
    """b：`result=refutes` ⇒ `refuted` + `counterexample_experiment_id`（裁定 ② 第一条来路）。"""
    st = _store(tmp_path)
    out = _run(st, REFUTES_PROBE)
    rows = [dict(r) for r in st.rows("conjectures")]
    assert len(rows) == 1, rows
    row = rows[0]
    eid = str(out.get("experiment_id") or "")
    assert row["status"] == "refuted", row
    assert row["counterexample_experiment_id"] == eid, row
    assert row["experiment_ids"] == [eid], row


# ============================================================ c 反真空

def test_c_stub_out_the_ledger_write_and_the_row_disappears(tmp_path, monkeypatch):
    """c（反真空）：把 `conjectureledger.register` 打桩成"不写" ⇒ a 必红。

    打桩的是写点（不是实验）：实验照跑照落行 —— 于是这一条证明"那一行猜想真的来自
    `conjectureledger.register` 这一笔"，而不是别处顺手写的（例如某个 tx 里手写 upsert）。
    """
    st = _store(tmp_path)

    def _no_write(**_kw):
        return {}

    monkeypatch.setattr(CL, "register", _no_write)
    out = _run(st, SUPPORTS_PROBE)
    assert str(out.get("experiment_id") or ""), "打桩把实验也弄没了 ⇒ 这条反真空没有对象"
    assert [dict(r) for r in st.rows("experiments")], "实验行该照常落"
    assert st.rows("conjectures") == [], f"写点被打桩成不写，却仍有一行：{st.rows('conjectures')}"


# ============================================================ d 只有一个写点

def test_d_there_is_no_second_write_point(tmp_path):
    """d：工具面上没有那件工具；通用写口拒 `conjectures`（后门堵上）。"""
    st = _store(tmp_path)
    reg = build_registry(store=st, workspace_root=str(st.root)).registry
    assert "conjecture.register_conjecture" not in set(reg.names()), sorted(reg.names())
    from agentflow.store import DIRECT_WRITE_REFUSED, direct_write_refusal

    why = direct_write_refusal("conjectures")
    assert why.startswith(DIRECT_WRITE_REFUSED), why
    assert "conjectureledger" in why, why


# ============================================================ 同一句话只有一个号

def test_e_the_same_proposition_from_two_producers_is_still_one_row(tmp_path):
    """跨族去重：E 落的行，B 收录同一条时只补读数，不落第二行（也不会退回 needs_evidence）。"""
    st = _store(tmp_path)
    out = _run(st, SUPPORTS_PROBE)
    before = dict(st.rows("conjectures")[0])
    got = CL.register(store=st, statement=CLAIM, origin="statements:000001",
                      notes="B 收录之后补一行备注", actor="agent-B")
    rows = [dict(r) for r in st.rows("conjectures")]
    assert len(rows) == 1, rows
    assert rows[0]["conjecture_id"] == before["conjecture_id"]
    assert rows[0]["status"] == before["status"], "没提状态 ⇒ 不许退回别的档"
    assert rows[0]["experiment_ids"] == before["experiment_ids"]
    # `origin` 是"调用方对来路的声明"，给了就会改（必填参）：B 那一侧自己传的是「既有那一行
    # 的 origin」（`agent_b/register_statement.py::_ledger_origin`）⇒ 生产路径上来路不会被改；
    # 这里给的是另一段 origin，所以它如实变了 —— 这一格是"调用方说了算"，不是"静默保留"。
    assert rows[0]["notes"] == "B 收录之后补一行备注"
    assert got["duplicate"] is True and got["duplicate_of"] == before["conjecture_id"], got
    assert str(out.get("experiment_id") or "")


# ============================================================ e 历史行读数（裁定 甲 的同日处置）

def _authors_reading(st):
    """收工读数里那一格（`closing._leg_reading` 的 `conjecture_rows`）。"""
    from agentflow import closing as C

    _n, detail = C._leg_reading(st, "conjecture_rows", pathlib.Path(st.root))
    return dict(detail["conjecture_authors"])


def test_f_the_closing_reading_marks_legacy_authors(tmp_path):
    """f：历史行（`created_by=agent-D`）由收工读数标出来，且新写的行不被误标。

    业主 2026-11-13 同一天的处置：老盘上的猜想行按历史行冻结，只加一条读数把
    `legacy_author` 标出来。这一格钉的就是那条读数（加键不改形）。
    """
    st = _store(tmp_path)
    empty = _authors_reading(st)
    assert empty["checked"] is True and empty["authors"] == [] and empty["legacy_rows"] == 0, empty

    # 一行历史行（直接写盘：那一档之后没有任何角色的动作能产生它）
    with st.tx("conjectures", actor="legacy") as tx:
        tx.upsert("conjectures", {"conjecture_id": "000000", "statement": "历史行。",
                                 "form": "universal", "testable": {"why": "夹具"},
                                 "origin": "gap", "status": "proposed",
                                 "created_by": "agent-D"})
    _run(st, SUPPORTS_PROBE)
    got = _authors_reading(st)
    assert got["checked"] is True, got
    by = {one["author"]: one for one in got["authors"]}
    assert by["agent-D"]["rows"] == 1 and by["agent-D"]["legacy"] is True, by
    assert got["legacy_rows"] == 1, got
    assert [one for one in got["authors"] if one["author"] != "agent-D"][0]["legacy"] is False, by

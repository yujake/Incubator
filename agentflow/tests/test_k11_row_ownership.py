# -*- coding: utf-8 -*-
"""K11 判据：experiments / documents 的行级归属（业主 2026-11-19 批次）。

## 缺口（`AUDIT-E` 已钉，双实例实测）

`table.*` 只对 `tasks` 有行级可见面 / 写闸；`experiments` 与 `documents` 走的是表级判据：
实验行谁都能读、能改、能删、能造（`direct_write_refusal("experiments")` 返回空串 ⇒ 放行），
稿件表的删除整张放开。实测（探针 p8 ④）：E-2 以 `TableContext(actor='agent-E-2')` 调
`table.update(table="experiments", id="000000", patch={"result": …})` ⇒ `ok=True`，
E-1 那一行当场被改。

## 这一组守什么

| # | 造什么 | 期望 | 改前读数 |
|---|---|---|---|
| a | E-1 落一行实验，E-2 改它 | 受控拒 `row_not_yours`；那一行一个字节不动 | `ok=True`、行被改（探针 p8 ④） |
| b | E-2 读 E-1 那一行（list / get） | list 里 0 条；get 受控拒 `row_not_visible`（不是 `found=False`） | list `total=2` 且含 E-1 那条（探针 p8 ③） |
| e | G-1 建一份稿，G-2 删它 / G-1 删它 | G-2 受控拒 `row_not_yours`；G-1 删除成立（正控）；G-2 的 list 看不见、G-1 看得见 | 删除整张放开、读面不区分调用者 |
| e′ | 造行时的归属 | `table.create` 把 `owner_task` / `owner_instance` 现盖成调用者；载荷里伪造这两格 ⇒ 拒 | 两格不存在（`Experiment` 没有这两列） |
| h | 反真空：把行级归属打桩掉（`write_refusal` 恒放行 / `visible` 恒真） | a 与 e 必须红 | —— |

边界：全部 `tmp_path` 工作区、假时钟、零真实模型调用、不碰 `projects/`。
"""
from __future__ import annotations

import pathlib
import sys

import pytest

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agentflow import rowscope as RS  # noqa: E402
from agentflow import schema as S  # noqa: E402
from agentflow.conductor import calling_as  # noqa: E402
from agentflow.store import Store  # noqa: E402
from agentflow.tools import build_registry  # noqa: E402

TS = "2026-11-19T00:20:00+08:00"
EXP_ROW = {
    "claim": "对 n<=40 的偶数 n，n^2+2 不是 3 的倍数",
    "claim_key": "K11-exp",
    "method": "numeric",
    "result": "inconclusive",
    "negation_kind": "not_proved",
}
CLAIMS = [{
    "claim_id": "claim-1", "text": "两族闭式的坐标型推导在交叉验证下成立",
    "citations": ["stmt:000000"], "evidence_kind": "cross_check",
    "disclaimer": "数值交叉验证，不构成证明", "section": "1",
}]


def _ws(tmp_path: pathlib.Path):
    root = tmp_path / "ws"
    st = Store(root)
    st.init()
    (root / "reports").mkdir(parents=True, exist_ok=True)
    reg = build_registry(store=st, workspace_root=root).registry
    return st, reg


def _call(reg, role: str, tool: str, *, task: str, instance: str = "", **params):
    """按某个实例的身份调一次（与真机同一条挂点：`calling_as` 的三个格子）。"""
    with calling_as(task, role, instance=instance):
        return reg.call(tool, role=role, **params)


def _statement(st: Store) -> None:
    """一行可被引用的命题（`doc.build_document` 的引用存在性要它）。"""
    stmt = S.Statement(
        stmt_id=S.format_id(0), origin="own_result", kind="theorem",
        label="Theorem 0.1", statement_text="命题短版",
        statement_full="若假设 A 成立，则结论 B 成立", proof_text="Proof. 由定义直接得到。",
        quote_verified=None, quote_reason="还没校验：这一条没有可比的全文",
        evidence_kind="cross_check", status="active", created_at=TS)
    stmt.validate()
    with st.tx("statements", actor="fixture", note="k11 stmt") as tx:
        tx.upsert("statements", stmt.to_dict(), note="k11 stmt")


# ============================================================ e′：造行时盖归属


def test_e2_create_stamps_the_caller_and_refuses_forged_owner_fields(tmp_path):
    """e′：`table.create` 现盖归属两格；载荷里自带别人那一趟 / 别人那一支笔 ⇒ 拒。"""
    st, reg = _ws(tmp_path)
    got = _call(reg, "E", "table.create", task="t-k11-1", instance="E1",
                table="experiments", row=dict(EXP_ROW))
    assert got.ok is True, (got.error, got.meta)
    row = st.rows("experiments")[0]
    assert row["owner_task"] == "t-k11-1", row
    assert row["owner_instance"] == "E1", row

    forged_task = _call(reg, "E", "table.create", task="t-k11-2", instance="E2",
                        table="experiments",
                        row={**EXP_ROW, "owner_task": "t-k11-1"})
    assert forged_task.ok is False, forged_task.data
    assert forged_task.meta.get("kind") == RS.ROW_OWNER_FORGED, forged_task.meta

    forged_inst = _call(reg, "E", "table.create", task="t-k11-2", instance="E2",
                        table="experiments",
                        row={**EXP_ROW, "owner_instance": "E1"})
    assert forged_inst.ok is False, forged_inst.data
    assert forged_inst.meta.get("kind") == RS.ROW_OWNER_FORGED, forged_inst.meta

    # 没有身份（脚本 / 单测直调）⇒ fail-closed：不是「谁都可以」，是「不知道是谁就拒」。
    anonymous = reg.call("table.create", role="E", table="experiments", row=dict(EXP_ROW))
    assert anonymous.ok is False, anonymous.data
    assert anonymous.meta.get("kind") == RS.ROW_OWNER_UNKNOWN, anonymous.meta


# ============================================================ a / b：实验行


def test_a_e2_cannot_update_e1_experiment_row(tmp_path):
    """a：E-2 改 E-1 那一行 ⇒ `row_not_yours`，且那一行一个字节不动（改前 red：ok=True）。"""
    st, reg = _ws(tmp_path)
    first = _call(reg, "E", "table.create", task="t-k11-e1", instance="E1",
                  table="experiments", row=dict(EXP_ROW))
    assert first.ok is True, (first.error, first.meta)
    eid = str(first.data)
    before = dict(st.rows("experiments")[0])

    res = _call(reg, "E", "table.update", task="t-k11-e2", instance="E2",
                table="experiments", id=eid,
                patch={"result": "inconclusive", "evidence_kind": "heuristic"})
    assert res.ok is False, ("E-2 改掉了 E-1 那一行（改前的形态）", res.data)
    assert res.meta.get("kind") == RS.ROW_NOT_YOURS, res.meta
    assert "归" in str(res.error), res.error
    after = dict(st.rows("experiments")[0])
    assert after == before, ("被拒了却还是改了盘", after, before)

    # 正控：E-1 自己改自己的行照旧成立（不是「一律拒」）。
    own = _call(reg, "E", "table.update", task="t-k11-e1", instance="E1",
                table="experiments", id=eid, patch={"evidence_kind": "heuristic"})
    assert own.ok is True, (own.error, own.meta)
    assert st.rows("experiments")[0]["evidence_kind"] == "heuristic"


def test_b_e2_cannot_see_e1_experiment_row(tmp_path):
    """b：E-2 读不到 E-1 那一行；E-1 读得到（改前 red：两趟都读到同一份）。"""
    st, reg = _ws(tmp_path)
    first = _call(reg, "E", "table.create", task="t-k11-e1", instance="E1",
                  table="experiments", row=dict(EXP_ROW))
    assert first.ok is True, (first.error, first.meta)
    eid = str(first.data)

    mine = _call(reg, "E", "table.list", task="t-k11-e1", instance="E1",
                 table="experiments")
    assert mine.data["total"] == 1, mine.data
    assert "own-instance" in str(mine.meta.get("row_scope") or ""), mine.meta

    other = _call(reg, "E", "table.list", task="t-k11-e2", instance="E2",
                  table="experiments")
    assert other.data["total"] == 0, ("E-2 读到了 E-1 的实验行（改前的形态）", other.data)

    got = _call(reg, "E", "table.get", task="t-k11-e2", instance="E2",
                table="experiments", id=eid)
    assert got.ok is False, got.data
    assert got.meta.get("kind") == RS.ROW_NOT_VISIBLE, got.meta
    assert got.meta.get("found") is True, ("「不是你的行」不许折成「没有这一行」", got.meta)

    # 别的角色照旧读得到（证据要能从 E 流到 V / B / G）：这是设计，不是泄露。
    from agentflow.tools import build_registry as _build

    vreg = _build(store=st, workspace_root=tmp_path / "ws").registry
    with calling_as("t-k11-v", "V", instance="V1"):
        seen = vreg.call("table.list", role="V", table="experiments")
    assert seen.data["total"] == 1, ("V 读不到 E 的实验行 ⇒ 证据链断了", seen.data)


# ============================================================ e：稿件行


def _build_doc(reg, *, task: str, instance: str):
    return _call(reg, "G", "doc.build_document", task=task, instance=instance,
                 kind="note", title="K11 稿件", claims=[dict(c) for c in CLAIMS])


def test_e_document_rows_belong_to_the_g_instance_that_wrote_them(tmp_path):
    """e：别人的稿不能删、也不能读到；自己的稿照旧可删（改前：删除整张放开）。"""
    st, reg = _ws(tmp_path)
    _statement(st)
    built = _build_doc(reg, task="t-k11-g1", instance="G1")
    assert built.ok is True, (built.error, built.meta)
    doc_id = str(built.data["doc_id"])
    row = st.rows("documents")[0]
    assert row["owner_task"] == "t-k11-g1", row
    assert row["owner_instance"] == "G1", row

    other = _call(reg, "G", "table.list", task="t-k11-g2", instance="G2",
                  table="documents")
    assert other.data["total"] == 0, ("G-2 看见了 G-1 的稿", other.data)
    mine = _call(reg, "G", "table.list", task="t-k11-g1", instance="G1",
                 table="documents")
    assert mine.data["total"] == 1, mine.data

    denied = _call(reg, "G", "table.delete", task="t-k11-g2", instance="G2",
                   table="documents", id=doc_id)
    assert denied.ok is False, ("G-2 删掉了 G-1 的稿（改前的形态）", denied.data)
    assert denied.meta.get("kind") == RS.ROW_NOT_YOURS, denied.meta
    assert len(st.rows("documents")) == 1, st.rows("documents")

    # 正控：同一支笔删得掉自己的稿（不是「一律拒」）。
    ok_delete = _call(reg, "G", "table.delete", task="t-k11-g1", instance="G1",
                      table="documents", id=doc_id)
    assert ok_delete.ok is True, (ok_delete.error, ok_delete.meta)
    assert st.rows("documents") == []


def test_e2_a_document_cannot_be_created_through_the_generic_port(tmp_path):
    """e′：通用写口造 `documents` 仍然受控拒（DOCGATE2 的单点写口没被本批放宽）。"""
    st, reg = _ws(tmp_path)
    res = _call(reg, "G", "table.create", task="t-k11-g1", instance="G1",
                table="documents",
                row={"doc_id": "000099", "kind": "note", "title": "手写一行",
                     "markdown_path": "documents/000099.md", "sections": [],
                     "open_problems": [], "status": "draft", "review_rounds": 0,
                     "revision": 1, "created_at": TS, "updated_at": TS,
                     "created_by": "agent-G", "claims": [dict(c) for c in CLAIMS]})
    assert res.ok is False, res.data
    assert st.rows("documents") == []


# ============================================================ h：反真空


def test_h_stubbing_the_ownership_judgement_turns_a_and_e_red(
        tmp_path, monkeypatch: pytest.MonkeyPatch):
    """h：把行级归属打桩掉（写闸恒放行 / 读面恒可见）⇒ a 与 e 必红。"""
    monkeypatch.setattr(RS, "write_refusal", lambda *a, **k: None)
    monkeypatch.setattr(RS, "visible", lambda *a, **k: True)

    st, reg = _ws(tmp_path)
    first = _call(reg, "E", "table.create", task="t-k11-e1", instance="E1",
                  table="experiments", row=dict(EXP_ROW))
    assert first.ok is True, (first.error, first.meta)
    eid = str(first.data)
    # a 的那一笔现在真的落盘了 ⇒ a 的绿是这道判据给的，不是别的格子碰巧。
    res = _call(reg, "E", "table.update", task="t-k11-e2", instance="E2",
                table="experiments", id=eid, patch={"evidence_kind": "heuristic"})
    assert res.ok is True, ("闸关掉了却仍写不进去 ⇒ a 的拒不是它给的", res.error, res.meta)
    assert st.rows("experiments")[0]["evidence_kind"] == "heuristic"

    _statement(st)
    built = _build_doc(reg, task="t-k11-g1", instance="G1")
    assert built.ok is True, (built.error, built.meta)
    doc_id = str(built.data["doc_id"])
    denied = _call(reg, "G", "table.delete", task="t-k11-g2", instance="G2",
                   table="documents", id=doc_id)
    assert denied.ok is True, ("闸关掉了却仍删不掉 ⇒ e 的拒不是它给的", denied.error, denied.meta)
    assert st.rows("documents") == []

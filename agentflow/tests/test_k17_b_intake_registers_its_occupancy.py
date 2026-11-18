# -*- coding: utf-8 -*-
"""K17 判据：B 收编一份稿要登记占用 —— 回执与落点要能回答「这一笔是谁的稿」。

## 读数（`MASTER-INVENTORY` K17：BR-06，以及 BR-01 / BR-04 的"谁"那一半）

改前 B 收编（`own.ingest_manuscript` 的 apply / register）只往 `statements` 行里写
`manuscripts`（`{path_group: rel}`）与 `verifications` 行上的路径号 —— 盘上没有任何
一格记着"这一份稿是谁收的、收的是哪一版"。于是回执与落点只剩一个路径字符串：
两个 B 实例各收一份稿时，"这一笔是谁的稿"没有答案（BR-06 的缺口）。

现在每写库一笔就落一条收编占用（`manuscriptids.claim_intake`，判据本体仍是
`claim_for_write` 一处）：键 = `intake:<rel>`（与 F/E 的写者登记分命名空间）、
holder 带 `owner` / `instance` / `sha256` / `family` / `target`，回执原样带回
`out["intake_claim"]`，另行登记在 `runs/manuscript-claims.json`。

| # | 判据 |
|---|---|
| e | 收编回执带 `intake_claim`，holder 的 owner / instance / sha256 / family / 路径逐格对得上 |
| e′ | 换一个 B 实例再收同一份稿 ⇒ 回执写的是新实例，`previous` 带回上一笔（收编是事件，不是永久所有权） |
| e″ | 反真空：把 `claim_intake` 打桩成空 ⇒ 这一笔不写库、受控拒 `intake_claim_unchecked`（登记不是装饰） |
"""
from __future__ import annotations

import pathlib
import sys

from agentflow import identity as IDENT
from agentflow import manuscriptids as MID
from agentflow.agent_b import AgentB
from agentflow.conductor import calling_as
from agentflow.store import Store

import conftest

PROPOSITION = "对任意有限群 G，若 p 整除 |G|，则 G 有 p 阶元。"
PROOF = ("1. 取 G 的一个 Sylow p-子群 P（二阶 Sylow 定理）。\n"
         "2. |P| = p^a > 1 ⇒ 取 1 ≠ x ∈ P，由拉格朗日定理 ord(x) 是 p 的幂。\n"
         "3. 结论：x 的某个幂就是 p 阶元。")
REL = "reports/f-proof-000001.md"


def _ws(tmp_path: pathlib.Path) -> tuple[Store, AgentB]:
    st = Store(tmp_path / "ws")
    st.init()
    return st, conftest.b_form_gate_ok(
        AgentB(st, extractor=None, extract_text=None, config={}))


def _manuscript() -> str:
    deps = ("| 引用（F 的原话） | 命题号（stmt:NNNNNN） | 用在哪一步 | 路径号（第几条证明） |\n"
            "|---|---|---|---|\n")
    return ("- 命题类型：conjecture\n\n## 命题\n\n" + PROPOSITION + "\n\n"
            "## 证明\n\n" + PROOF + "\n\n## 依赖\n\n" + deps)


def _signed_row(st: Store) -> dict:
    row = conftest.seed_statement_row(
        st, stmt_id="000001", statement_full=PROPOSITION, kind="conjecture",
        proof_text="")
    conftest.sign_for_the_gate(
        st.root, statement_id="000001", proof_text=PROOF, proof_no=1,
        store=st, manuscript=REL)
    return row


def _write_manuscript(st: Store) -> pathlib.Path:
    path = pathlib.Path(st.root) / REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_manuscript(), encoding="utf-8")
    return path


def _ingest(b: AgentB, *, instance: str = "") -> dict:
    """按实例身份调一次收编（与真机同一条挂点：`calling_as` 的 instance 格）。"""
    with calling_as("t-b-1", "B", instance=instance):
        return b.ingest_manuscript(
            manuscript=REL, target_stmt_id="000001",
            cells=["proof_text"], mode="apply")


# --------------------------------------------------------------------- e


def test_e_intake_receipt_names_the_instance_and_the_manuscript(tmp_path: pathlib.Path):
    """收编回执的 holder 逐格对得上：owner / instance / sha256 / family / 路径。"""
    st, b = _ws(tmp_path)
    _signed_row(st)
    _write_manuscript(st)

    got = _ingest(b, instance="B1")
    assert got["ok"] is True, got
    claim = got.get("intake_claim") or {}
    assert claim.get("checked") is True, claim
    holder = dict(claim.get("holder") or {})
    assert holder.get("owner") == "agent-B-B1", holder
    assert holder.get("instance") == "B1", holder
    # 稿身份用的是收编读数里那一把尺（`out["manuscript"]["sha256"]`，整份稿的正文
    # 归一化 sha）—— 两处必须同值，否则"收的是哪一版"有两个答案。
    assert holder.get("sha256") == got["manuscript"]["sha256"], holder
    assert len(str(holder.get("sha256") or "")) == 64, holder
    assert holder.get("family") == "f-proof", holder
    assert holder.get("target") == "000001", holder
    assert holder.get("purpose") == MID.INTAKE_PURPOSE, holder
    # 落点（盘上的登记）与回执是同一份：读回来逐格相同。
    on_disk = MID.intake_claim(st.root, REL)
    assert on_disk.get("owner") == "agent-B-B1", on_disk
    assert on_disk.get("sha256") == holder["sha256"], on_disk
    # 它盖在既有的写者登记之外（同一份稿的"谁写"仍然读得到）。
    assert claim.get("rel") == REL, claim


# --------------------------------------------------------------------- e′


def test_e_prime_another_instance_records_itself_and_keeps_the_previous(
        tmp_path: pathlib.Path):
    """换一个 B 实例再收同一份稿 ⇒ 回执写新实例，previous 带回上一笔。"""
    st, b = _ws(tmp_path)
    _signed_row(st)
    _write_manuscript(st)
    first = _ingest(b, instance="B1")
    assert first["ok"] is True, first
    assert (first["intake_claim"]["holder"] or {}).get("owner") == "agent-B-B1"

    again = _ingest(b, instance="B2")
    assert again["ok"] is True, again
    holder = dict(again["intake_claim"]["holder"] or {})
    assert holder.get("owner") == "agent-B-B2", holder
    previous = dict(holder.get("previous") or {})
    assert previous.get("owner") == "agent-B-B1", (
        f"第二笔收编没把上一笔的 holder 带回来：{holder}")
    assert again["intake_claim"]["state"] == "replaced", again["intake_claim"]["state"]


# --------------------------------------------------------------------- e″


def test_e_prime_prime_anti_vacuum_the_intake_claim_is_load_bearing(
        tmp_path: pathlib.Path, monkeypatch):
    """反真空：把 `claim_intake` 打桩成空 ⇒ 这一笔不写库（登记不是装饰）。"""
    st, b = _ws(tmp_path)
    _signed_row(st)
    _write_manuscript(st)
    before = [dict(r) for r in st.rows("statements")]
    monkeypatch.setattr(MID, "claim_intake", lambda *a, **kw: {})
    got = _ingest(b, instance="B1")
    assert got["ok"] is False, got
    assert got["refused"] == "intake_claim_unchecked", got
    assert [dict(r) for r in st.rows("statements")] == before, "登记没成却写了库"
    assert IDENT.current_instance() == ""  # 夹具复位（不把实例漏到下一个用例）

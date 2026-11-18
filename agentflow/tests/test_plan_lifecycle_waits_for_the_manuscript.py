# -*- coding: utf-8 -*-
"""判据：稿没完工，计划就关不掉（业主 2026-11-18 逐字裁定）。

> 「逻辑反了。稿没完工，计划本身就关不掉」

## 现场（`temp/qa3/REPORT.md` §2.2、`temp/inv8/REPORT.md` §3.7）

`projects/lp-ball-8`：`reports/f-proof-000000.md` 一次签都没发（`out/vsigns/` count=0）。
19:23:15 / 19:27:51 / 19:37:12 三轮 `outcome=no_change` ⇒ 19:44:39 非属主 t-000030
把 plan 000000 判 `stalled`（seq 2600）⇒ 19:47:39 t-000015 交 v3 时，`step` 在读产物之前
就按 `status in TERMINAL_STATUSES` 返回 `action=stop`（`agent_f/step.py` 的终态早退）——
而同一份 stop 返回里已经写着 `delivery.state=outputs_unsigned`、
`still_unsubmitted[0].signed=false`。F 没有 `fs.write` 自己那份稿的权限
（`fs_tools.RESERVED_ARTIFACT_TABLE`），唯一写口就是 `attack.step(product=…)` ⇒ 实质锁死未签稿。

## 这一份钉什么

| # | 造什么 | 期望 | 改前红在哪 |
|---|---|---|---|
| a | 计划有未签稿 ＋ 连续 3 轮 `no_change` | 不 `stalled`、`action=proof`、正文 sha 变 | 停滞检测只看 `history[-3:]`，直接 `stalled` |
| b | 同场景、轮数也用尽 | 同上；计划不因轮数关 | 轮数用尽那一支直接 `stalled` |
| c | 子目标全 `closed` / `supported_not_proved` 但稿未签 | `status` 不进 `resolved` / `supported_not_proved` | `_derive_status` 只看子目标状态 |
| d | 稿已签 | 该计划可以进终态；重写同一份稿受控拒 `manuscript_frozen`（按稿级冻结，不是按计划状态） | （负控；当前应绿，钉住"别把 gate 做成按计划状态拦写"） |
| e | `abandoned`（F 主动放弃） | 行为不变：`step` 仍 `stop`，不许被"稿未签"重新拾起 | （负控） |
| f | 反真空：把「完工才可关」打桩成"永远完工" | a / b / c 三条断言必红 | —— |

零模型调用：稿走真的 `attack.step(product=…)` 落盘；签走生产的写口
（`_credential_fixture.issue_credential` + `vsigns.write_manuscript_sign`）。
"""

from __future__ import annotations

import pathlib

import pytest
from conftest import seed_statement_row
from agentflow import depsection as _DS
from agentflow import proofregistry as _PR
from agentflow import vsigns as VS
from agentflow.agent_f import AgentF
from agentflow.store import Store

from _credential_fixture import issue_credential

PROPOSITION = "设 g ≥ 0 可积、|f_n| ≤ g；则 ∫|f_n − f| → 0。"
SUBGOAL = "控制项 2g 可积，且 |f_n-f| ≤ 2g 在 X 上处处成立。"
TESTABLE = "手稿的 `## 证明` 里逐步给出依据（`cites` 或 `assumption: true`）。"
BUDGET = {"max_rounds": 6, "max_parallel_subgoals": 2,
          "max_persist_attempts": 2, "max_depth": 2}
AT = "2026-11-18T19:47:39+08:00"


# --------------------------------------------------------------------- 夹具

def _ws(base: pathlib.Path) -> Store:
    st = Store(base / "ws")
    st.init()
    return st


def _f(st: Store) -> AgentF:
    return AgentF(st, config={"workspace_root": str(st.root)})


def _gate_ok(monkeypatch) -> None:
    """命题形态闸打桩成"判过、合格"（它不是这一份要测的那道闸）。"""
    def fake_gate(self, *, full, kind, body, label, task_id=""):  # noqa: ANN001, ARG001
        return {"checked": True, "well_formed": True, "submittable": True,
                "conditions": "夹具：设…", "conclusion": "夹具：则…",
                "problems": [], "decision": "夹具：形态合规",
                "refused": "", "reason": "夹具：形态合规"}

    monkeypatch.setattr(AgentF, "_proposition_form_gate", fake_gate)


def _citable_statement(st: Store) -> str:
    """一条够格（`pre_theorem`）的在册命题，给证明的某一串当依据。"""
    row = seed_statement_row(
        st, statement_full="引理：被可积函数 g 控制的可测函数列，控制项 2g 可积。",
        statement_text="2g 可积", kind="lemma", label="前提A",
        bits={"proof": True, "reviewed": True,
              "evidence": {"proof_process": "夹具：第 1 步设 g 可积。",
                           "reviewed_by": {"verdict": "成立", "verification_id": "v-000001"}}})
    return str(row["stmt_id"])


def _plan(f: AgentF, *, key: str, max_rounds: int = 6) -> str:
    budget = dict(BUDGET, max_rounds=max_rounds)
    made = f.create_plan(PROPOSITION, key,
                         subgoals=[{"sid": "S1", "text": SUBGOAL, "owner": "F",
                                    "testable": TESTABLE}],
                         budget=budget)
    assert made.get("created") is True, made
    return str(made["plan_id"])


def _product(stmt_id: str, *, manuscript_id: str = "", tail: str = "") -> dict:
    return {
        "kind": "proof",
        "proposition": PROPOSITION,
        "label": "控制收敛的一段",
        "manuscript_id": manuscript_id,
        "steps": [
            {"text": "设 g ≥ 0 可积、|f_n| ≤ g（本步是前提）", "assumption": True},
            {"text": f"由控制函数得 |f_n-f| ≤ 2g，且 2g 可积{tail}",
             "cites": [f"stmt:{stmt_id}"]},
            {"text": f"对 2g-|f_n-f| 用 Fatou 引理得 limsup ∫|f_n-f| ≤ 0{tail}",
             "cites": [f"stmt:{stmt_id}"]},
        ],
    }


def _land_unsigned(f: AgentF, plan_id: str, stmt_id: str) -> dict:
    """走真路径落一份未签手稿（第一轮）。"""
    out = dict(f.step(plan_id, product=_product(stmt_id)) or {})
    assert out.get("action") == "proof", out
    assert out.get("manuscript_path"), out
    assert out.get("manuscript_id"), out
    return out


def _row(st: Store, plan_id: str) -> dict:
    return next(dict(r) for r in st.rows("attack_plans")
                if str(r.get("plan_id")) == plan_id)


def _body_sha(st: Store, rel: str) -> str:
    """这一份稿的「正文 sha」——与签/登记同一把尺（`vsigns.manuscript_proof_body`）。"""
    text = (pathlib.Path(st.root) / rel).read_text(encoding="utf-8")
    return _PR.proof_sha(VS.manuscript_proof_body(text))


def _no_change(round_no: int) -> dict:
    return {"round": round_no, "sid": "S1", "action": "no_change",
            "outcome": "no_change", "detail": "夹具：这一轮没有进展",
            "evidence": [], "at": AT}


def _progress(round_no: int) -> dict:
    return {"round": round_no, "sid": "S1", "action": "proof",
            "outcome": "progress", "detail": "夹具：这一轮有进展",
            "evidence": [], "at": AT}


def _seed_history(st: Store, plan_id: str, rows: list[dict], *, rounds: int) -> None:
    """把"连续 N 轮 no_change"的现场铺进台账（真机同形态；不经过模型缝）。"""
    row = _row(st, plan_id)
    row["history"] = list(row.get("history") or []) + list(rows)
    row["rounds"] = int(rounds)
    row["updated_at"] = AT
    with st.tx("attack_plans", actor="test") as tx:
        tx.upsert("attack_plans", row, note="fixture:seed_no_change")


def _set_subgoals(st: Store, plan_id: str, subgoals: list[dict]) -> None:
    row = _row(st, plan_id)
    row["subgoals"] = [dict(s) for s in subgoals]
    row["updated_at"] = AT
    with st.tx("attack_plans", actor="test") as tx:
        tx.upsert("attack_plans", row, note="fixture:set_subgoals")


def _sign(st: Store, rel: str) -> None:
    """用生产的写口把一份签盖到这一份稿现行的正文上。"""
    text = (pathlib.Path(st.root) / rel).read_text(encoding="utf-8")
    body = _DS.proof_body(text).strip("\n")
    issue_credential(st.root, proof_text=body, manuscript=rel, artifact_path=rel)
    got = VS.write_manuscript_sign(
        st.root, rel, proof_sha=VS._sign_sha(body), streak=3, need=3,
        verdict="成立", signer="V", at=AT,
        ledger="verifications/000000.jsonl#v-000003", statement_id="", signed=True)
    assert got.get("written") is True, got


# ------------------------------------------------------- a：不因无进展关计划

def _scenario_no_progress(base: pathlib.Path, monkeypatch) -> dict:
    """稿未签 ＋ 连续 3 轮 no_change ⇒ 再交一轮应当落稿（不是 stall_detected）。"""
    _gate_ok(monkeypatch)
    st = _ws(base)
    f = _f(st)
    stmt = _citable_statement(st)
    plan_id = _plan(f, key="PK-STALL", max_rounds=6)
    first = _land_unsigned(f, plan_id, stmt)
    rel, mid = str(first["manuscript_path"]), str(first["manuscript_id"])
    before = _body_sha(st, rel)
    # 第 1 轮是 progress；再把 2/3/4 轮铺成 no_change（真机 19:23/19:27/19:37 的形态）。
    _seed_history(st, plan_id, [_no_change(2), _no_change(3), _no_change(4)], rounds=4)

    out = dict(f.step(plan_id, product=_product(
        stmt, manuscript_id=mid, tail="（v2：同一份稿，改了第 2、3 步）")) or {})
    return {"out": out, "row": _row(st, plan_id), "rel": rel,
            "before": before, "after": _body_sha(st, rel)}


def test_a_three_no_progress_rounds_do_not_close_a_plan_with_an_unsigned_manuscript(
        tmp_path: pathlib.Path, monkeypatch) -> None:
    """a：改前红——停滞检测只看 `history[-3:]`，这里会返回 `action=stall_detected`。

    改后：稿没拿到 V 签 ⇒ 计划不许进 `stalled`；这一轮照常推进并把正文写进盘。
    """
    got = _scenario_no_progress(tmp_path / "a", monkeypatch)
    out, row = got["out"], got["row"]

    assert out.get("action") == "proof", out
    assert out.get("outcome") == "progress", out
    assert out.get("status") == "attacking", out
    assert row.get("status") == "attacking", row
    # 真写盘：正文 sha 变了
    assert got["after"] != got["before"], (got["before"], got["after"])
    # 读数里带「稿还没完工」这一格（不是只写在散文里）
    gate = dict(out.get("finish_gate") or {})
    assert gate.get("finished") is False, gate
    assert int(gate.get("unfinished_count") or 0) >= 1, gate
    assert any(str(x.get("manuscript") or "") == got["rel"]
               for x in (gate.get("items") or [])), gate


# ------------------------------------------------------- b：不因轮数用尽关计划

def _scenario_rounds_exhausted(base: pathlib.Path, monkeypatch) -> dict:
    """稿未签 ＋ 轮数用尽 ⇒ 再交一轮应当落稿（不是 stalled）。

    刻意让最后三轮不是"全 no_change"（第 4 轮记 progress）——这样命中的是「轮数」
    那一支（a 命中的是连续无进展那一支），两条停止判据各有一条判据。
    """
    _gate_ok(monkeypatch)
    st = _ws(base)
    f = _f(st)
    stmt = _citable_statement(st)
    plan_id = _plan(f, key="PK-ROUNDS", max_rounds=4)
    first = _land_unsigned(f, plan_id, stmt)
    rel, mid = str(first["manuscript_path"]), str(first["manuscript_id"])
    before = _body_sha(st, rel)
    # rounds=4 == max_rounds（4）；历史 1+3 条，schema 上限 4×1+1=5 ⇒ 还留得下这一轮。
    _seed_history(st, plan_id,
                  [_no_change(2), _no_change(3), _progress(4)], rounds=4)

    out = dict(f.step(plan_id, product=_product(
        stmt, manuscript_id=mid, tail="（v2：轮数用尽也要把稿写进去）")) or {})
    return {"out": out, "row": _row(st, plan_id), "rel": rel,
            "before": before, "after": _body_sha(st, rel)}


def test_b_exhausted_rounds_do_not_close_a_plan_with_an_unsigned_manuscript(
        tmp_path: pathlib.Path, monkeypatch) -> None:
    """b：改前红——轮数用尽那一支直接 `stalled`；稿未签时不许这样关。

    这一轮是"超预算修补轮"：`rounds` 不涨（schema 的硬上限不许越），但稿照样写进去。
    """
    got = _scenario_rounds_exhausted(tmp_path / "b", monkeypatch)
    out, row = got["out"], got["row"]

    assert out.get("action") == "proof", out
    assert out.get("status") == "attacking", out
    assert row.get("status") == "attacking", row
    assert got["after"] != got["before"], (got["before"], got["after"])
    # 轮数不越过 `max_rounds`（schema 硬约束），但这一轮如实进 history。
    assert int(row.get("rounds") or 0) == int(row["budget"]["max_rounds"]), row
    assert int(out.get("round") or 0) == int(row["budget"]["max_rounds"]), out
    gate = dict(out.get("finish_gate") or {})
    assert gate.get("finished") is False, gate


# ------------------------------------------- c：子目标全关也不许关计划

def _scenario_all_closed(base: pathlib.Path, monkeypatch, *,
                         status: str = "closed") -> dict:
    _gate_ok(monkeypatch)
    st = _ws(base)
    f = _f(st)
    stmt = _citable_statement(st)
    plan_id = _plan(f, key=f"PK-{status}")
    first = _land_unsigned(f, plan_id, stmt)
    rel = str(first["manuscript_path"])
    sg = dict(_row(st, plan_id)["subgoals"][0])
    sg["status"] = status
    if status == "closed":
        # schema：closed 必须有 proof 级证据（FC-22）。
        sg["proof_experiment_ids"] = ["exp:000001"]
    _set_subgoals(st, plan_id, [sg])

    out = dict(f.step(plan_id) or {})
    return {"out": out, "row": _row(st, plan_id), "rel": rel}


def test_c_all_closed_subgoals_do_not_resolve_a_plan_with_an_unsigned_manuscript(
        tmp_path: pathlib.Path, monkeypatch) -> None:
    """c：改前红——`_derive_status` 只看子目标全 `closed` ⇒ 直接 `resolved`。"""
    got = _scenario_all_closed(tmp_path / "c", monkeypatch)
    out, row = got["out"], got["row"]

    assert out.get("status") != "resolved", out
    assert row.get("status") == "attacking", row
    gate = dict(out.get("finish_gate") or {})
    assert gate.get("finished") is False, gate
    assert "稿" in str(out.get("reason") or ""), out


def test_c2_supported_not_proved_is_gated_the_same_way(
        tmp_path: pathlib.Path, monkeypatch) -> None:
    """c2：`supported_not_proved` 与 `resolved` 同一道闸（① 逐字点名了它）。"""
    got = _scenario_all_closed(tmp_path / "c2", monkeypatch,
                               status="supported_not_proved")
    out, row = got["out"], got["row"]
    assert out.get("status") != "supported_not_proved", out
    assert row.get("status") == "attacking", row


# ------------------------------------------------- d：稿已签 ⇒ 可以关；写口按稿拦

def test_d_a_signed_manuscript_lets_the_plan_close(tmp_path: pathlib.Path,
                                                   monkeypatch) -> None:
    """d①：稿拿到 V 签 ⇒ 同一场景可以进终态（负控：gate 不许把已完工也挡掉）。"""
    _gate_ok(monkeypatch)
    st = _ws(tmp_path / "d1")
    f = _f(st)
    stmt = _citable_statement(st)
    plan_id = _plan(f, key="PK-SIGNED")
    first = _land_unsigned(f, plan_id, stmt)
    _sign(st, str(first["manuscript_path"]))
    sg = dict(_row(st, plan_id)["subgoals"][0])
    sg.update(status="closed", proof_experiment_ids=["exp:000001"])
    _set_subgoals(st, plan_id, [sg])

    out = dict(f.step(plan_id) or {})
    assert out.get("status") == "resolved", out
    assert _row(st, plan_id).get("status") == "resolved"
    assert dict(out.get("finish_gate") or {}).get("finished") is True, out


def test_d2_a_signed_manuscript_is_refused_by_the_freeze_not_by_the_plan_status(
        tmp_path: pathlib.Path, monkeypatch) -> None:
    """d②：计划仍在推进（不是终态）时重写已签稿 ⇒ `manuscript_frozen`（按稿级冻结）。

    这是"写口不因计划状态被关"的反向负控：关写口的只能是「稿级」冻结，
    不能是 gate 顺手把计划判成终态。
    """
    _gate_ok(monkeypatch)
    st = _ws(tmp_path / "d2")
    f = _f(st)
    stmt = _citable_statement(st)
    plan_id = _plan(f, key="PK-FROZEN")
    first = _land_unsigned(f, plan_id, stmt)
    rel, mid = str(first["manuscript_path"]), str(first["manuscript_id"])
    _sign(st, rel)
    before = (pathlib.Path(st.root) / rel).read_bytes()

    out = dict(f.step(plan_id, product=_product(stmt, manuscript_id=mid)) or {})
    assert out.get("action") == "no_change", out
    assert "已经拿签" in str(out.get("reason") or ""), out
    assert (pathlib.Path(st.root) / rel).read_bytes() == before, "被拒的那一笔动了稿"
    hist = list(_row(st, plan_id).get("history") or [])
    refusal = dict((hist[-1] or {}).get("refusal") or {})
    assert refusal.get("kind") == "manuscript_frozen", refusal
    # 计划没有被这道拒信顺手关掉（它仍是一条在推的计划）。
    assert _row(st, plan_id).get("status") == "attacking", _row(st, plan_id)


# ------------------------------------------------------- e：abandoned 行为不变

def test_e_f_abandoned_plans_stay_closed_even_with_an_unsigned_manuscript(
        tmp_path: pathlib.Path, monkeypatch) -> None:
    """e（负控）：`abandoned` 是 F 的决定，不是程序关计划 ⇒ 不许被 gate 重新拾起。"""
    _gate_ok(monkeypatch)
    st = _ws(tmp_path / "e")
    f = _f(st)
    stmt = _citable_statement(st)
    plan_id = _plan(f, key="PK-ABANDON")
    _land_unsigned(f, plan_id, stmt)     # 稿未签
    got = f.abandon_plan(plan_id, reason="不再需要", basis="夹具：这条方向不再需要")
    assert got.get("abandoned") is True, got

    out = dict(f.step(plan_id) or {})
    assert out.get("action") == "stop", out
    assert out.get("status") == "abandoned", out
    assert out.get("reason") and "终结状态" in str(out.get("reason")), out
    assert _row(st, plan_id).get("status") == "abandoned"


# --------------------------------------------------- f：反真空（打桩掉 ① 必红）

def test_f_stubbing_the_finish_gate_out_turns_a_b_c_red(
        tmp_path: pathlib.Path, monkeypatch) -> None:
    """f 反真空：把「完工才可关」打桩成"永远完工"⇒ a / b / c 的读数必须翻回旧的错形态。

    若这三条打桩后仍然绿，那 a/b/c 的绿就与这道闸无关（判据是真空的）。
    """
    def always_finished(self, plan):  # noqa: ANN001, ARG001
        return {"checked": True, "finished": True, "unfinished_count": 0,
                "items": [], "why": "夹具：打桩成「永远完工」", "state": "signed_all"}

    monkeypatch.setattr(AgentF, "_finish_gate", always_finished)

    a = _scenario_no_progress(tmp_path / "fa", monkeypatch)
    assert a["out"].get("action") == "stall_detected", a["out"]
    assert a["out"].get("status") == "stalled", a["out"]
    assert a["after"] == a["before"], "打桩后仍然写了盘 ⇒ a 测的不是这道闸"

    b = _scenario_rounds_exhausted(tmp_path / "fb", monkeypatch)
    assert b["out"].get("status") == "stalled", b["out"]
    assert b["out"].get("action") == "stop", b["out"]
    assert b["after"] == b["before"], "打桩后仍然写了盘 ⇒ b 测的不是这道闸"

    c = _scenario_all_closed(tmp_path / "fc", monkeypatch)
    assert c["out"].get("status") == "resolved", c["out"]
    assert c["row"].get("status") == "resolved", c["row"]


if __name__ == "__main__":          # pragma: no cover - 手工跑这一份时用
    raise SystemExit(pytest.main([__file__, "-q"]))

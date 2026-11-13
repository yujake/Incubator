# -*- coding: utf-8 -*-
"""彩排 C12：收工链 —— 三个产出方各自按签拦收工、收工自动提交、钱对账。

## 这一条链的业主口径

「如果产出方是 E 和 F，都应该在收工时自动提交名下所有未提交稿并将状态更新」
（2026-11-11，逐字）；以及 `agent_loop._v_wait_gate_reading` 的「收工门按签拦收工，
不按计时器拦：F 计划号 / E `e-proof` / B `b-proof` 各自」。

## 这一条链怎么真跑

```text
未签（或签被打桩成没签）
  ⇒ AgentLoop._v_wait_gate_reading 受控拒：complete=False、逐条点名缺什么
  ⇒ 一个计划号 / 一份稿都不许被读成「可 finish」

已签
  ⇒ agent_f.autosubmit.auto_submit_signed（F）
  ⇒ agent_e.autosubmit.auto_submit_at_close（E）
  ⇒ 两枚 mss: 记号落进各自 tasks.artifacts
  ⇒ 统一读口 manuscriptsubmission.submission_reading（工具面
     `manuscripts.submission_reading`）把它读成 submitted / via=closing_auto_submit
  ⇒ B 收录成功时那一枚 mss:（via=ingested_to_ledger）落进 B 那一行
  ⇒ tokenmeter.TokenMeter.charge 真记两笔账 ⇒ reconcile_usage 逐分相等
```

## 终态断言（盘上/台账上可查）

| 判据 | 终态 |
|---|---|
| `test_c12_a_unsigned_work_is_refused_with_names` | 三个角色的 `_v_wait_gate_reading`：`complete=False`，F 点名「计划 0001」、E/B 点名各自的稿；`problems` 非空 |
| `test_c12_b_signed_work_passes_and_is_auto_submitted` | 三道门 `complete=True`；`tasks.artifacts` 里真的有 `mss:` 记号（F/E）；`via=closing_auto_submit` |
| `test_c12_c_b_ingest_writes_the_b_side_marker` | B 收录成功的 `out` 经 `agent_b.autosubmit.mark_b_ingested` ⇒ B 那一行 `artifacts` 里 `mss:<稿号>`、`via=ingested_to_ledger` |
| `test_c12_d_money_reconciles` | 真 `TokenMeter.charge` 两笔 ⇒ `reconcile_usage()["equal"] is True`、`diff_usd == 0`、逐行残差空 |

## 反真空（缺一不算走通）

1. 签打桩成"没签"：把 `manuscriptclosing.signed_candidates` 打成恒
   `signed=False/state=unsigned` ⇒ 已签那一趟必须被拦（`test_..._e`）；
2. artifacts 写口打桩成失败：`store.tx("tasks")` 在自动提交那一刻抛 ⇒ 读数必须说
   "没写成 / 没交成"（`checked=False` + `why` 含"没写成"），不许说"没有要交的"
   （`test_..._f`）。这一格钉的是"没交成"与"没有要交的"是两件事。

## 零模型

全部 tmp 工作区；签用 `verifications.record_pending_sign` + `vsigns.issue` 直接造
（与 `test_e_auto_submits_signed_manuscripts.py` 同一套夹具形状）；不读写 `projects/`。
"""
from __future__ import annotations

import pathlib
from typing import Any, Mapping

import pytest

from agentflow import conductor as CND
from agentflow import depsection as DS
from agentflow import manuscriptclosing as MC
from agentflow import manuscriptsubmission as MS
from agentflow import modelcost as MCost
from agentflow import proofregistry as PR
from agentflow import schema as S
from agentflow import tokenmeter as TM
from agentflow import verifications as VR
from agentflow import vsigns as VS
from agentflow.agent_loop import AgentLoop
from agentflow.agent_b import autosubmit as BAS
from agentflow.agent_e import autosubmit as EAS
from agentflow.agent_f import autosubmit as FAS
from agentflow.store import Store
from agentflow.tools import manuscript_tools as MT

TS = "2026-01-01T00:00:00+00:00"
PLAN = "0001"
F_MID = "000101"
E_MID = "000201"
B_MID = "000301"
F_CLAIM = "设 G 是有限群；则 G 的阶与它的子群阶之间存在拉格朗日关系。"
F_BODY = ("1. 取任意子群 H；H 的元素两两落在 G 的同一个左陪集里。\n"
          "2. 左陪集构成 G 的一个划分，每一块的基数都是 |H| ⇒ |H| 整除 |G|。")
E_CLAIM = "R(3,4)=9（K_9 的二染色穷举）。"
E_BODY = ("1. 枚举 K_9 的全部二染色；每一种都命中单色 K_3 或 K_4。\n"
          "2. K_8 存在反例 ⇒ 界是 9。")
B_CLAIM = "设 H 是 G 的子群；则 H 的左陪集两两不交且覆盖 G。"
B_BODY = ("1. 若 xH 与 yH 相交，则 x^{-1}y ∈ H ⇒ 两个左陪集相同。\n"
          "2. 每个 g 都在 gH 里 ⇒ 全体左陪集覆盖 G。")


# ====================================================================== 夹具
def _ws(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _text(*, head: str, claim: str, body: str) -> str:
    return (f"# 证明手稿\n\n{head}\n\n## 命题\n\n{claim}\n\n## 证明\n\n{body}\n\n"
            + DS.render_dependency_section([]))


def _f_text() -> str:
    return _text(head=f"- 命题号：stmt:（还没落号）\n- 计划：{PLAN}",
                 claim=F_CLAIM, body=F_BODY)


def _e_text() -> str:
    return _text(head=f"- 命题号：stmt:（还没落号）\n- 实验号：exp:{E_MID}",
                 claim=E_CLAIM, body=E_BODY)


def _b_text() -> str:
    return _text(head=f"- 命题号：stmt:{B_MID}", claim=B_CLAIM, body=B_BODY)


def _write(st: Store, rel: str, text: str) -> str:
    path = pathlib.Path(st.root) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return rel


def _sign(st: Store, rel: str, text: str, *, by: str, statement_id: str = "") -> str:
    """把一份稿签成「成立」：三票台账 ＋ `vsigns.issue` 的真凭据（同 E 那份夹具）。"""
    body = DS.proof_body(text).strip("\n")
    rows = [VR.record_pending_sign(
        st.root, proof_text=body, verdict={"verdict": "成立", "findings": []},
        verifier="agent-V", object_path=rel,
        secretary_judge={"checked": True, "axis": "clean", "decision": "没问题",
                         "reason": "夹具：clean"}) for _i in range(3)]
    key = str(rows[0].get("object_sha256") or rows[0].get("proof_sha256") or "")
    passes = [{"verification_id": r["verification_id"], "at": r["at"],
               "proof_sha256": r["proof_sha256"]} for r in rows]
    wrote = VS.issue(st.root, artifact_sha=PR.proof_sha(text), streak=3, need=3,
                     artifact_path=rel, statement_id=statement_id,
                     ledger=f"verifications/pending/{key}.jsonl"
                            f"#{rows[-1]['verification_id']}",
                     passes=passes, by=by)
    assert wrote.get("written") is True, wrote
    return str(wrote.get("sign", {}).get("artifact_sha") or PR.proof_sha(text))


def _task(st: Store, role: str, *, task_id: str, status: str = "running") -> dict:
    row = S.Task(task_id=task_id, role=role, action="run", called_by="M", depth=1,
                 status=status, started_at=TS, input_key=f"c12:{role}")
    row.validate()
    with st.tx("tasks", actor="fixture") as tx:
        tx.upsert("tasks", row.to_dict())
    return row.to_dict()


def _plan(st: Store) -> None:
    row = S.AttackPlan(
        plan_id=PLAN, problem="拉格朗日定理", problem_key="lagrange",
        status="open", rounds=1,
        budget={"max_rounds": 4, "max_parallel_subgoals": 2,
                "max_persist_attempts": 2, "max_depth": 2},
        history=[{"round": 1, "sid": "S1", "action": "proof",
                  "outcome": "ok", "detail": "夹具", "evidence": [],
                  "at": TS, "manuscript_id": F_MID}],
        created_at=TS, updated_at=TS)
    row.validate()
    with st.tx("attack_plans", actor="fixture") as tx:
        tx.upsert("attack_plans", row.to_dict())


def _experiment(st: Store) -> None:
    row = S.Experiment(
        experiment_id=E_MID, claim=E_CLAIM, claim_key="ramsey34",
        method="symbolic", evidence_kind="cross_check",
        result="inconclusive", negation_kind="not_proved", created_at=TS)
    row.validate()
    with st.tx("experiments", actor="fixture") as tx:
        tx.upsert("experiments", row.to_dict())


def _env(tmp_path: pathlib.Path, *, signed: bool = True) -> dict[str, Any]:
    """一个带三族稿的工作区：F 计划／E 穷举证明／B 改写稿。"""
    st = _ws(tmp_path)
    _plan(st)
    _experiment(st)
    f_rel = _write(st, f"reports/f-proof-{F_MID}.md", _f_text())
    e_rel = _write(st, f"reports/e-proof-{E_MID}.md", _e_text())
    b_rel = _write(st, f"reports/b-proof-{B_MID}.md", _b_text())
    _task(st, "F", task_id="t-000001")
    _task(st, "E", task_id="t-000002")
    _task(st, "B", task_id="t-000003")
    if signed:
        _sign(st, f_rel, _f_text(), by="secretary:F", statement_id="")
        _sign(st, e_rel, _e_text(), by="secretary:E", statement_id="")
        _sign(st, b_rel, _b_text(), by="secretary:B", statement_id="")
    return {"store": st, "root": st.root, "f": f_rel, "e": e_rel, "b": b_rel}


def _gate(env: Mapping[str, Any], role: str) -> dict:
    """真入口：`AgentLoop._v_wait_gate_reading`（`final` 那条路读的就是它）。"""
    loop = AgentLoop(role=role, session_root=pathlib.Path(str(env["root"])),
                     registry=None, seam=None, store=env["store"],
                     workspace_root=str(env["root"]))
    return loop._v_wait_gate_reading()


def _artifacts(st: Store, task_id: str) -> list[str]:
    row = next(dict(r) for r in st.rows("tasks")
               if str(r.get("task_id")) == task_id)
    return [str(x) for x in (row.get("artifacts") or [])]


# ====================================================================== a：未签
def test_c12_a_unsigned_work_is_refused_with_names(tmp_path: pathlib.Path) -> None:
    """未签时三个产出方各自被收工门受控拒，且逐条点名缺什么。"""
    env = _env(tmp_path, signed=False)
    problems: list[str] = []
    for role in ("F", "E", "B"):
        gate = _gate(env, role)
        if gate.get("checked") is not True:
            problems.append(f"{role}：读数该是 checked=True（台账读得成），实际 "
                            f"{gate.get('checked')!r} / {gate.get('reason')!r}")
        if gate.get("applicable") is not True:
            problems.append(f"{role}：这道门对这一角色该有对象")
        if gate.get("complete") is not False:
            problems.append(f"{role}：未签时该判 complete=False，实际 {gate.get('complete')!r}")
        if not gate.get("problems"):
            problems.append(f"{role}：未签时 problems 为空 —— 受控拒没点名缺什么")
        why = str(gate.get("why") or "")
        if "还没收工" not in why:
            problems.append(f"{role}：拒信没有『还没收工』：{why!r}")
    f_gate = _gate(env, "F")
    if not any("计划 " + PLAN in str(p.get("where") or "")
               for p in (f_gate.get("problems") or ())):
        problems.append(f"F：拒信没点名计划 {PLAN}：{f_gate.get('problems')!r}")
    e_gate = _gate(env, "E")
    if not any("e-proof" in str(p.get("where") or "")
               for p in (e_gate.get("problems") or ())):
        problems.append(f"E：拒信没点名 e-proof 稿：{e_gate.get('problems')!r}")
    b_gate = _gate(env, "B")
    if not any("b-proof" in str(p.get("where") or "")
               for p in (b_gate.get("problems") or ())):
        problems.append(f"B：拒信没点名 b-proof 稿：{b_gate.get('problems')!r}")
    assert problems == [], problems


# ====================================================================== b：已签
def test_c12_b_signed_work_passes_and_is_auto_submitted(tmp_path: pathlib.Path) -> None:
    """已签 ⇒ 三道门放行；收工自动提交把 `mss:` 记号写进 F/E 各自的 artifacts。"""
    env = _env(tmp_path, signed=True)
    st = env["store"]
    problems: list[str] = []
    for role in ("F", "E", "B"):
        gate = _gate(env, role)
        if gate.get("complete") is not True or gate.get("problems"):
            problems.append(f"{role}：已签却没过门：complete={gate.get('complete')!r}，"
                            f"problems={gate.get('problems')!r}，why={gate.get('why')!r}")

    with CND.calling_as("t-000001", "F"):
        f_out = FAS.auto_submit_signed(store=st, root=st.root, plan_id=PLAN, stamp=TS)
    if f_out.get("auto_submitted_count") != 1:
        problems.append(f"F 收工自动提交该 1 份，实际 {f_out.get('auto_submitted_count')!r}"
                        f"（why={f_out.get('why')!r}，still={f_out.get('still_unsubmitted')!r}）")
    f_tokens = [x for x in _artifacts(st, "t-000001") if x.startswith("mss:")]
    if not any(x.startswith(f"mss:{F_MID}") for x in f_tokens):
        problems.append(f"F 那一行 artifacts 里没有 mss:{F_MID}：{_artifacts(st, 't-000001')}")

    e_out = EAS.auto_submit_at_close(store=st, root=st.root, task_id="t-000002", stamp=TS)
    if e_out.get("auto_submitted_count") != 1:
        problems.append(f"E 收工自动提交该 1 份，实际 {e_out.get('auto_submitted_count')!r}"
                        f"（why={e_out.get('why')!r}，still={e_out.get('still_unsubmitted')!r}）")
    e_tokens = [x for x in _artifacts(st, "t-000002") if x.startswith("mss:")]
    if not any(x.startswith(f"mss:{E_MID}") for x in e_tokens):
        problems.append(f"E 那一行 artifacts 里没有 mss:{E_MID}：{_artifacts(st, 't-000002')}")

    # 统一读口（工具面 `manuscripts.submission_reading`）真的读得出「已提交」。
    for rel, mid, producer in ((env["f"], F_MID, "F"), (env["e"], E_MID, "E")):
        got = MS.submission_reading(st, st.root, manuscript=rel)
        if got.get("state") != "submitted":
            problems.append(f"{rel}：统一读口该是 submitted，实际 {got.get('state')!r}"
                            f"（{got.get('why')!r}）")
        if got.get("producer_role") != producer:
            problems.append(f"{rel}：产出方该是 {producer}，实际 {got.get('producer_role')!r}")
        if got.get("via") != MS.VIA_CLOSING:
            problems.append(f"{rel}：via 该是 {MS.VIA_CLOSING}，实际 {got.get('via')!r}")
    tool_reg = None
    with CND.calling_as("t-000003", "B"):
        res = _call_submission_reading_tool(st, env["f"])
    if res.get("state") != "submitted":
        problems.append(f"工具 manuscripts.submission_reading 没读出 submitted：{res!r}")
    assert problems == [], problems


def _call_submission_reading_tool(st: Store, rel: str) -> dict:
    """真工具面：`manuscripts.submission_reading`（只读，全部可召唤角色）。"""
    from agentflow.tools import manuscript_tools as MT_
    from agentflow.tools.base import ToolRegistry

    reg = ToolRegistry(name="c12")
    reg.bound_role = "B"
    MT_.register(reg, store=st, actor="agent-B")
    got = reg.call("manuscripts.submission_reading", manuscript=rel, role="B")
    assert got.ok, (got.error, got.meta)
    return dict(got.data or {})


# ====================================================================== c：B 收编
def test_c12_c_b_ingest_writes_the_b_side_marker(tmp_path: pathlib.Path) -> None:
    """B 收录成功那一刻：`mss:` 记号落进 B 自己那一行（`via=ingested_to_ledger`）。"""
    env = _env(tmp_path, signed=True)
    st = env["store"]
    out: dict[str, Any] = {"ok": True,
                           "manuscript": {"proof_sha256": PR.proof_sha(_b_text())},
                           "target": {"stmt_id": B_MID},
                           "path_group": {"path_group": 1}}
    with CND.calling_as("t-000003", "B"):
        got = BAS.mark_b_ingested(st, st.root, manuscript=env["b"], out=out)
    problems: list[str] = []
    if got.get("b_submission", {}).get("written") is not True:
        problems.append(f"B 收录成功却没有写提交记号：{got.get('b_submission')!r}")
    tokens = [x for x in _artifacts(st, "t-000003") if x.startswith("mss:")]
    if not any(x.startswith(f"mss:{B_MID}") for x in tokens):
        problems.append(f"B 那一行 artifacts 里没有 mss:{B_MID}：{_artifacts(st, 't-000003')}")
    reading = MS.submission_reading(st, st.root, manuscript=env["b"])
    if reading.get("via") != MS.VIA_INGEST:
        problems.append(f"B 的 via 该是 {MS.VIA_INGEST}，实际 {reading.get('via')!r}")
    if reading.get("state") != "submitted":
        problems.append(f"B 的稿该读成 submitted，实际 {reading.get('state')!r}")
    # 受控拒：`out["ok"] is False` ⇒ 一个字节都不写。
    refused_out: dict[str, Any] = {"ok": False, "manuscript": {}, "target": {}}
    before = list(_artifacts(st, "t-000003"))
    with CND.calling_as("t-000003", "B"):
        BAS.mark_b_ingested(st, st.root, manuscript=env["b"], out=refused_out)
    if list(_artifacts(st, "t-000003")) != before:
        problems.append("受控拒那一档动了 B 的 artifacts（不该写）")
    assert problems == [], problems


# ====================================================================== d：钱
def test_c12_d_money_reconciles(tmp_path: pathlib.Path) -> None:
    """真记账两笔 ⇒ `usage_ledger` 与 `tasks.usd` 逐分相等；再打坏一笔必须点名。"""
    env = _env(tmp_path, signed=True)
    st = env["store"]
    meter = TM.TokenMeter(st)
    meter.charge(TM.Charge(role="F", scope="reason", tokens_in=1000, tokens_out=200,
                           usd=0.0015, task_id="t-000001", note="C12 F 一轮"), now=TS)
    meter.charge(TM.Charge(role="E", scope="experiment", tokens_in=2000, tokens_out=400,
                           usd=0.0030, task_id="t-000002", note="C12 E 一轮"), now=TS)
    reading = MCost.reconcile_usage(st)
    problems: list[str] = []
    if reading.get("equal") is not True:
        problems.append(f"两本账该逐分相等，实际 {reading!r}")
    if reading.get("diff_usd") != 0.0:
        problems.append(f"diff_usd 该是 0，实际 {reading.get('diff_usd')!r}")
    if reading.get("named_residual") or reading.get("unattributed", {}).get("count"):
        problems.append(f"逐行残差与无主账都该为空：{reading!r}")
    if not reading.get("tasks_usd"):
        problems.append(f"tasks.usd 合计该非零：{reading!r}")

    # 反真空：把 E 那一行的账改小（只改账本、不改 tasks）⇒ 对账必须红并点名。
    rows = [dict(r) for r in st.rows("usage_ledger")]
    target = next(r for r in rows if str(r.get("task_id")) == "t-000002")
    target["usd"] = 0.0
    target["note"] = "C12 打坏的那一笔"
    with st.tx("usage_ledger", actor="fixture") as tx:
        tx.upsert("usage_ledger", target)
    bad = MCost.reconcile_usage(st)
    if bad.get("equal") is not False:
        problems.append(f"打坏一笔之后对账仍 equal：{bad!r}")
    if not any(str(r.get("task_id")) == "t-000002" for r in (bad.get("named_residual") or ())):
        problems.append(f"差额没有逐行点名 t-000002：{bad.get('named_residual')!r}")
    assert problems == [], problems


# ====================================================================== e：反真空签
def test_c12_e_stubbing_the_sign_to_unsigned_blocks_the_close(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """反真空①：把签打桩成"全都没签" ⇒ 已签那一趟必须被收工门拦住。

    打桩点选 `manuscriptclosing.signed_candidates`（"签算不算签"的唯一口径）：
    盘上真签不动，只让门读到 unsigned。若门不读它、或"没签"被折成"可以收工"，
    这一条当场红。
    """
    env = _env(tmp_path, signed=True)
    real = MC.signed_candidates

    def _unsigned(root: Any, *, families: Any, role: str = "") -> dict:
        got = dict(real(root, families=families, role=role))
        got["candidates"] = [{**dict(c), "signed": False, "state": "unsigned",
                              "why": "打桩：没签"} for c in (got.get("candidates") or ())]
        return got

    monkeypatch.setattr(MC, "signed_candidates", _unsigned)
    problems: list[str] = []
    for role in ("F", "E", "B"):
        gate = _gate(env, role)
        if gate.get("complete") is not False:
            problems.append(f"{role}：签被打桩成没签之后仍然放行 ⇒ 「按签拦」不来自签")
        if not gate.get("problems"):
            problems.append(f"{role}：签被打桩成没签之后没有点名缺什么")
    assert problems == [], problems


# ====================================================================== f：反真空写口
def test_c12_f_a_failed_artifacts_write_says_it_was_not_submitted(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """反真空②：artifacts 写口打桩成失败 ⇒ 读数说"没交成"，不许说"没有要交的"。"""
    env = _env(tmp_path, signed=True)
    st = env["store"]
    real_tx = Store.tx

    def _tx(self: Store, *tables: str, **kw: Any):
        note = str(kw.get("note") or "")
        if "auto_submit" in note:
            raise OSError("打桩：artifacts 写口坏了")
        return real_tx(self, *tables, **kw)

    monkeypatch.setattr(Store, "tx", _tx)
    e_out = EAS.auto_submit_at_close(store=st, root=st.root, task_id="t-000002",
                                     stamp=TS)
    problems: list[str] = []
    if e_out.get("checked") is not False:
        problems.append(f"写不进去时 checked 该是 False，实际 {e_out.get('checked')!r}")
    why = str(e_out.get("why") or "")
    if "没写成" not in why and "没交成" not in why:
        problems.append(f"读数没说是『没写成/没交成』：{why!r}")
    if "没有「已拿签、尚未提交」的稿" in why:
        problems.append(f"写失败被读成了『没有要交的』：{why!r}")
    states = {str(x.get("state")) for x in (e_out.get("still_unsubmitted") or ())}
    if "write_failed" not in states:
        problems.append(f"逐条理由里没有 write_failed：{e_out.get('still_unsubmitted')!r}")
    if any(x.startswith(f"mss:{E_MID}") for x in _artifacts(st, "t-000002")):
        problems.append("写口坏了却仍然写进了 artifacts")
    assert problems == [], problems

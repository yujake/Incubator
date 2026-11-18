# -*- coding: utf-8 -*-
"""BATCH3 · K5 / K6 / K7 的判据（2026-11-18）。

这一份钉三组根因，每条都带「改前会红」的读法：

| # | 造什么 | 期望 |
|---|---|---|
| a | F#1 先登记 `f-proof-000001`，F#2 重写同一份稿 | 受控拒 `claim_not_yours`；盘上那份稿一个字节不动；属主重写仍可写、claim 的 `at` 更新 |
| b | E 走 `land_manuscript` 落 `e-proof` | `runs/manuscript-claims.json` 里有这一份、owner 是 E 的实例 |
| c | V 读到 v1（sha c023），签发前盘上已是 v2 | 受控拒 `proof_changed_since_dispatch`；v1 的判词仍是台账行 / V 稿那一版，v2 不被签 |
| d | 同一号跨族 / 同族同号 | `(族, 号)` 可区分；同族同号幂等（键相等） |
| e | pending 计票：同一 `review_call` 三轮 vs 跨 `review_call` 的旧行 | 前者 3 票、后者只数最后一趟（旧行不计） |
| f | `attack.step` 的 returns / `create_plan` 两处回执 | 声明里有 `plan_state`；两处回执都有 `created_by` |
| g | 收工门 `_sign_gate_f` 遇到别人的计划 | 只遍历本实例的计划（别人的不判欠签） |
| h | 反真空：打桩掉 claim / 版本绑定 | a / c 必须红 |

纪律：不 skip / xfail；夹具只造盘上真文件（不写假签块）。
"""
from __future__ import annotations

import json
import pathlib
import types

from agentflow import agent_loop as AL
from agentflow import depsection as DS
from agentflow import exhaustionreport as ER
from agentflow import manuscriptids as MID
from agentflow import proofregistry as PR
from agentflow import statementledger as SL
from agentflow import verifications as VR
from agentflow.agent_v.core import AgentV
from agentflow.store import Store
from agentflow.tools import build_registry

BUDGET = {"max_rounds": 3, "max_parallel_subgoals": 2,
          "max_persist_attempts": 2, "max_depth": 2}
FULL = "对 n <= 40 的偶数 n，n^2 + 2 都不是 3 的倍数。"
BODY = "1. 逐个枚举 n<=40 的偶数，命中全部。\n2. 枚举覆盖区间两端，没有遗漏。"
FULL2 = "对 n <= 41 的偶数 n，n^2 + 2 都不是 3 的倍数。"
BODY2 = "1. 逐个枚举 n<=41 的偶数，命中全部。\n2. 枚举覆盖区间两端，没有遗漏。"


def _ws(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


# ============================================================ a：非属主重写
def test_a_a_non_owner_cannot_rewrite_someone_elses_manuscript(tmp_path):
    """a：F#2 重写 F#1 的稿 ⇒ `claim_not_yours`；属主续写仍可写且 claim 更新。"""
    st = _ws(tmp_path)
    root = str(st.root)
    first = PR.register_or_rewrite(
        root, family="F", label="夹具", proposition=FULL, proof_text=BODY,
        manuscript_id="000001", author="agent-F-F1", task_id="t-000001",
        instance="F1")
    assert first.get("ok") is True, first
    rel = str(first.get("manuscript_path") or "")
    assert rel == "reports/f-proof-000001.md", rel
    disk_v1 = (pathlib.Path(root) / rel).read_text(encoding="utf-8")

    intruder = PR.register_or_rewrite(
        root, family="F", label="夹具", proposition=FULL, proof_text=BODY2,
        manuscript_id="000001", author="agent-F-F2", task_id="t-000002",
        instance="F2")
    assert intruder.get("ok") is False, intruder
    assert intruder.get("refused") == PR.REFUSED_CLAIM_NOT_YOURS, intruder
    # 盘上一个字节不动（不是「拒了但还是写了」）。
    assert (pathlib.Path(root) / rel).read_text(encoding="utf-8") == disk_v1

    claims = json.loads((pathlib.Path(root) / MID.CLAIMS_REL).read_text(encoding="utf-8"))
    holder = dict(claims["claims"][rel])
    assert holder.get("owner") == "agent-F-F1", holder

    owner_again = PR.register_or_rewrite(
        root, family="F", label="夹具", proposition=FULL, proof_text=BODY2,
        manuscript_id="000001", author="agent-F-F1", task_id="t-000003",
        instance="F1")
    assert owner_again.get("ok") is True, owner_again
    holder2 = dict(json.loads(
        (pathlib.Path(root) / MID.CLAIMS_REL).read_text(encoding="utf-8"))["claims"][rel])
    assert holder2.get("owner") == "agent-F-F1", holder2
    assert holder2.get("task_id") == "t-000003", holder2


# ============================================================ b：E 侧 claim
def test_b_e_landing_registers_a_claim(tmp_path):
    """b：E 落 `e-proof` ⇒ claims 里有这一行（改前 claims_E=0）。"""
    st = _ws(tmp_path)
    root = str(st.root)
    got = ER.land_manuscript(
        root, experiment_id="000000", claim=FULL, claim_key="K-1",
        script_path="code/e1.py", script_sha256="0" * 64,
        design="d", enumeration="e", search_space="s", result="supports",
        evidence_kind="proof", kind="theorem",
        owner="agent-E-E1", task_id="t-000010", instance="E1")
    assert got.get("ok") is True, got
    rel = str(got.get("path") or "")
    assert rel == "reports/e-proof-000000.md", rel
    claims_path = pathlib.Path(root) / MID.CLAIMS_REL
    assert claims_path.is_file(), "E 落稿后 claims 文件不存在（改前 claims_E=0）"
    holder = dict(json.loads(claims_path.read_text(encoding="utf-8"))["claims"][rel])
    assert holder.get("owner") == "agent-E-E1", holder
    assert holder.get("task_id") == "t-000010", holder
    assert holder.get("role") == "E", holder


# ============================================================ c：版本绑定
def _pending_trip(root: str, body: str, call: str) -> tuple[list[dict], str]:
    rows = [VR.record_pending_sign(
        root, proof_text=body, verdict={"verdict": "成立", "findings": []},
        verifier="agent-V", object_path="reports/f-proof-000001.md",
        secretary_judge={"checked": True, "axis": "clean", "decision": "没问题",
                         "reason": "夹具：clean"},
        review_call=call, review_pass=n) for n in (1, 2, 3)]
    key = str(rows[0].get("object_sha256") or rows[0].get("proof_sha256") or "")
    ledger = f"verifications/pending/{key}.jsonl#{rows[-1]['verification_id']}"
    return rows, ledger


def test_c_signing_refuses_when_the_manuscript_changed_after_read(tmp_path):
    """c：V 读 v1、签发前盘上 v2 ⇒ `proof_changed_since_dispatch`，不签 v2。"""
    st = _ws(tmp_path)
    root = str(st.root)
    rel = "reports/f-proof-000001.md"
    (pathlib.Path(root) / "reports").mkdir(parents=True, exist_ok=True)
    (pathlib.Path(root) / rel).write_text(
        "# F 的证明手稿：夹具\n\n- 计划：000001\n\n## 命题\n\n" + FULL +
        "\n\n## 证明\n\n" + BODY + "\n\n" + DS.render_dependency_section([]) + "\n",
        encoding="utf-8")
    read_sha = VR.text_sha(BODY)
    rows, ledger = _pending_trip(root, BODY, "call-c")
    passes = [{"verification_id": r["verification_id"], "at": r["at"],
               "proof_sha256": r["proof_sha256"]} for r in rows]

    # V 读完之后、签发之前：盘上改成 v2。
    (pathlib.Path(root) / rel).write_text(
        "# F 的证明手稿：夹具\n\n- 计划：000001\n\n## 命题\n\n" + FULL +
        "\n\n## 证明\n\n" + BODY2 + "\n\n" + DS.render_dependency_section([]) + "\n",
        encoding="utf-8")

    agent = AgentV(st, secretary=types.SimpleNamespace(actor_label=""))
    block: dict = {}
    got_block, issued, landed = agent._issue_and_land_unregistered(
        rel=rel, sha=read_sha, streak=3, need=3, passes=passes,
        at=str(rows[-1].get("at") or ""), block_write=block, ledger=ledger)
    assert got_block.get("code") == VR.PROOF_CHANGED_SINCE_DISPATCH, got_block
    assert issued == {} and landed == {}, (issued, landed)
    # v2 的正文 sha 没有被签成文件。
    v2_sha = VR.text_sha(BODY2)
    assert not (pathlib.Path(root) / "out" / "vsigns" / f"{v2_sha}.json").is_file()
    assert not (pathlib.Path(root) / "out" / "vsigns" / f"{read_sha}.json").is_file()
    # 判词仍挂读到的那一版（v1）。
    assert rows[0].get("proof_sha256") == read_sha


# ============================================================ d：稿身份 (族, 号)
def test_d_manuscript_identity_is_family_and_id_across_the_statement_ledger():
    """d：同号不同族可区分；同族同号仍幂等。"""
    assert MID.identity_key("f-proof", "000040") != MID.identity_key("b-proof", "000040")
    assert MID.identity_key("f-proof", "000040") == MID.identity_key("f-proof", "000040")
    assert MID.identity_key("f-proof", "not-a-id") == ""

    f_row = {"manuscript_id": "000040", "manuscript_family": "f-proof"}
    b_row = {"manuscript_id": "000040", "manuscript_family": "b-proof"}
    assert SL.statement_manuscript_identity(f_row)["key"] != \
        SL.statement_manuscript_identity(b_row)["key"]
    assert SL.statement_manuscript_identity(f_row)["key"] == \
        SL.statement_manuscript_identity(dict(f_row))["key"]

    # 老行没有 family ⇒ 从逐路径稿现认（不猜）；认不出 ⇒ 空串。
    old = {"manuscript_id": "000040", "manuscripts": {"1": "reports/b-proof-000040.md"}}
    assert SL.statement_manuscript_identity(old)["family"] == "b-proof"


def test_d2_pending_ids_are_unique_across_files(tmp_path):
    """d2（K6③）：两份 pending 台账的第一行不再都叫 `u-000001`。"""
    st = _ws(tmp_path)
    root = str(st.root)
    one = VR.record_pending_sign(
        root, proof_text=BODY, verdict={"verdict": "成立", "findings": []},
        secretary_judge={"checked": True, "axis": "clean", "decision": "没问题",
                         "reason": "夹具"})
    two = VR.record_pending_sign(
        root, proof_text=BODY2, verdict={"verdict": "成立", "findings": []},
        secretary_judge={"checked": True, "axis": "clean", "decision": "没问题",
                         "reason": "夹具"})
    assert one["verification_id"] != two["verification_id"], (one, two)
    passes, _ = VR.pending_rows(root)
    ids = [str(r.get("verification_id") or "") for r in passes]
    assert len(ids) == len(set(ids)), ids


def test_d3_the_manuscript_head_and_artifacts_carry_family_and_instance(tmp_path):
    """d3（K6④）：稿头带 `- 稿族：` / `- 产出者：`；ARTIFACTS 带族与实例。"""
    st = _ws(tmp_path)
    root = str(st.root)
    got = PR.register_or_rewrite(
        root, family="F", label="夹具", proposition=FULL, proof_text=BODY,
        manuscript_id="000001", author="agent-F-F1", task_id="t-000001", instance="F1")
    assert got.get("ok") is True, got
    text = (pathlib.Path(root) / str(got["manuscript_path"])).read_text(encoding="utf-8")
    assert "- 稿族：f-proof" in text, text[:500]
    assert "- 产出者：agent-F-F1" in text, text[:500]
    entry = json.loads(
        (pathlib.Path(root) / "ARTIFACTS.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert entry.get("family") == "f-proof", entry
    assert entry.get("instance") == "F1", entry
    assert entry.get("producer") == "agent-F-F1", entry


# ============================================================ e：计票一把尺
def _clean_rows(root: str, *, call: str, n: int) -> list[dict]:
    out = []
    for p in range(1, n + 1):
        out.append(VR.record_pending_sign(
            root, proof_text=BODY, verdict={"verdict": "成立", "findings": []},
            verifier="agent-V", object_path="reports/f-proof-000001.md",
            secretary_judge={"checked": True, "axis": "clean", "decision": "没问题",
                             "reason": "夹具：clean"},
            review_call=call, review_pass=p))
    return out


def test_e_pending_streak_counts_only_the_tail_review_call(tmp_path):
    """e：同一 `review_call` 三轮 ⇒ 3；跨 `review_call` 的旧行 ⇒ 不计。"""
    import agentflow.verifications as V

    st = _ws(tmp_path)
    root = str(st.root)
    sha = VR.text_sha(BODY)
    _clean_rows(root, call="call-old", n=2)
    _clean_rows(root, call="call-new", n=1)
    passes, _problems = V.pending_rows(root)
    got = V._pending_claim_streak(passes, sha)
    assert got["votes"] == 1, got           # 改前：3（全部历史行）
    assert got["ok"] is False, got

    # 正控：同一趟三轮 ⇒ 3 票、ok。
    st2 = _ws(tmp_path / "two")
    _clean_rows(str(st2.root), call="call-one", n=3)
    passes2, _ = V.pending_rows(str(st2.root))
    got2 = V._pending_claim_streak(passes2, sha)
    assert got2["votes"] == 3, got2
    assert got2["ok"] is True, got2


# ============================================================ f：声明与回执
def test_f_returns_declarations_and_create_plan_created_by(tmp_path):
    """f：`attack.step` returns 含 plan_state；create_plan 两处回执含 created_by。"""
    st = _ws(tmp_path)
    reg = build_registry(store=st, workspace_root=st.root).registry
    assert "plan_state" in str(reg._specs["attack.step"].returns)
    assert "created_by" in str(reg._specs["attack.create_plan"].returns)
    sub = [{"sid": "s1", "text": "把命题约化到局部情形", "owner": "E",
            "testable": "枚举小情形后能一句话判它成立或不成立"}]
    first = reg.call("attack.create_plan", role="F", problem="夹具难题",
                     problem_key="probe:created-by", budget=BUDGET,
                     subgoals=sub).unwrap()
    assert first.get("created_by"), first
    second = reg.call("attack.create_plan", role="F", problem="夹具难题",
                      problem_key="probe:created-by", budget=BUDGET,
                      subgoals=sub).unwrap()
    assert second.get("duplicate") is True, second
    assert second.get("created_by") == first.get("created_by"), (first, second)


# ============================================================ g：收工门按实例
def test_g_the_f_closing_gate_only_walks_this_instances_plans(tmp_path):
    """g：`_sign_gate_f` 只遍历本实例的计划（别人的计划不判欠签）。"""
    st = _ws(tmp_path)
    with st.tx("attack_plans", actor="fixture") as tx:
        for pid, owner in (("000001", "agent-F-F1"), ("000002", "agent-F-F2")):
            tx.upsert("attack_plans", {
                "plan_id": pid, "problem": "夹具", "problem_key": f"k-{pid}",
                "status": "open", "rounds": 0, "subgoals": [], "history": [],
                "created_by": owner, "depth": 0, "parent_plan_id": None,
                "budget": dict(BUDGET), "created_at": "2026-11-18T10:00:00+08:00",
                "updated_at": "2026-11-18T10:00:00+08:00",
            })
    out = {"plans": [], "problems": []}
    AL._sign_gate_f(st, str(st.root), {}, out, owner="agent-F-F1")
    assert [p["plan_id"] for p in out["plans"]] == ["000001"], out
    assert len(out["problems"]) == 1, out

    # 没有实例身份 ⇒ 退回全表（三态：不假装自己是某一个）。
    legacy = {"plans": [], "problems": []}
    AL._sign_gate_f(st, str(st.root), {}, legacy, owner="")
    assert {p["plan_id"] for p in legacy["plans"]} == {"000001", "000002"}, legacy


# ============================================================ h：反真空
def test_h_anti_vacuum_claim_and_version_checks_are_load_bearing(tmp_path, monkeypatch):
    """h：把 K5 的 claim 判定 / K6 的版本绑定打桩掉 ⇒ a / c 必红。"""
    # K5：claim_for_write 恒 free ⇒ 非属主重写照写。
    st = _ws(tmp_path / "k5")
    root = str(st.root)
    first = PR.register_or_rewrite(
        root, family="F", label="夹具", proposition=FULL, proof_text=BODY,
        manuscript_id="000001", author="agent-F-F1", instance="F1")
    assert first.get("ok") is True, first
    monkeypatch.setattr(
        MID, "claim_for_write",
        lambda *a, **k: {"checked": True, "state": "free", "holder": {}, "why": ""})
    intruder = PR.register_or_rewrite(
        root, family="F", label="夹具", proposition=FULL, proof_text=BODY2,
        manuscript_id="000001", author="agent-F-F2", instance="F2")
    assert intruder.get("ok") is True, "打桩之后非属主重写居然被拒了（判据不承重）"

    # K6：版本绑定打桩成恒「没变」⇒ c 的签发不再拒。
    monkeypatch.setattr(VR, "PROOF_CHANGED_SINCE_DISPATCH", "still_refused")
    # 直接把 c 的 helper 结果钉成"同版"（判据本体被摘掉）。
    monkeypatch.setattr(VR, "text_sha", lambda text: "same")
    st2 = _ws(tmp_path / "k6")
    root2 = str(st2.root)
    rel = "reports/f-proof-000001.md"
    (pathlib.Path(root2) / "reports").mkdir(parents=True, exist_ok=True)
    (pathlib.Path(root2) / rel).write_text(
        "# F 的证明手稿：夹具\n\n## 命题\n\n" + FULL +
        "\n\n## 证明\n\n" + BODY + "\n\n" + DS.render_dependency_section([]) + "\n",
        encoding="utf-8")
    rows, ledger = _pending_trip(root2, BODY, "call-h")
    passes = [{"verification_id": r["verification_id"], "at": r["at"],
               "proof_sha256": r["proof_sha256"]} for r in rows]
    agent = AgentV(st2, secretary=types.SimpleNamespace(actor_label=""))
    block: dict = {}
    got_block, _issued, _landed = agent._issue_and_land_unregistered(
        rel=rel, sha="same", streak=3, need=3, passes=passes,
        at=str(rows[-1].get("at") or ""), block_write=block, ledger=ledger)
    assert got_block.get("code") != "still_refused", (
        "把版本判据摘掉之后签发仍然被拒 —— 说明 c 的绿不是这条判据给的")

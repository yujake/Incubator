# -*- coding: utf-8 -*-
"""乙：E 收工自动提交（业主 2026-11-11 裁定 ②）。

业主逐字：
    「如果产出方是 E 和 F，都应该在收工时自动提交名下所有未提交稿并将状态更新。」

## 这一份钉什么

| # | 造什么 | 期望 |
|---|---|---|
| a | E 名下 2 份已签、artifacts 里都没有 | 收工后两份的 `mss:<稿号>` 记号都进 E 那一行；`auto_submitted` 逐份点名 |
| b | 同一趟再收工 | 幂等：一个字节都不重复写；`already_submitted` 说清 |
| c | 盘上一份没签的 E 稿 | 不提交；`still_unsubmitted` 说「未签」 |
| d | 反真空：把自动提交摘掉 | a 那组断言必须红 |

零模型调用：签用 `verifications.record_pending_sign` + `vsigns.issue` 直接造
（与 F 那份判据同一套夹具形状）。
"""
from __future__ import annotations

import pathlib

import pytest
from agentflow import conductor as CND
from agentflow import depsection as DS
from agentflow import proofregistry as PR
from agentflow import schema as S
from agentflow import verifications as VR
from agentflow import vsigns as VS
from agentflow.agent_e import AgentE
from agentflow.agent_e import autosubmit as EAS
from agentflow import manuscriptsubmission as MS
from agentflow import manuscriptclosing as MC
from agentflow.store import Store

FULL = "设 f 在 [0,1] 上连续；则 f 在该区间上一致连续。"
BODY = ("1. 取 δ=ε：对任意 x,y∈[0,1]，|x-y|<δ ⇒ |f(x)-f(y)|<ε。\n"
        "2. 第 1 步的 δ 只依赖 ε、不依赖点 ⇒ 按定义即一致连续。")


def _ws(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _task(st: Store, *, task_id: str = "t-000001", role: str = "E") -> dict:
    row = S.Task(task_id=task_id, role=role, action="run_experiment",
                 called_by="D", depth=1, status="running", started_at=S.now_iso(),
                 input_key="e-auto-submit-fixture")
    row.validate()
    with st.tx("tasks", actor="fixture") as tx:
        tx.upsert("tasks", row.to_dict())
    return row.to_dict()


def _e_text(body: str) -> str:
    return ("# E 的证明手稿：一致连续\n\n"
            "- 命题号：stmt:（还没落号）\n"
            "- 实验号：exp:000001\n\n"
            f"## 命题\n\n{FULL}\n\n## 证明\n\n{body}\n\n"
            + DS.render_dependency_section([]))


def _signed(st: Store, mid: str, *, body: str | None = None) -> str:
    body = (BODY + f"\n3. 稿 {mid} 的收尾标记。") if body is None else body
    rel = f"reports/e-proof-{mid}.md"
    path = pathlib.Path(st.root) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    text = _e_text(body)
    path.write_text(text, encoding="utf-8")
    rows = [VR.record_pending_sign(
        st.root, proof_text=body, verdict={"verdict": "成立", "findings": []},
        verifier="agent-V", object_path=rel,
        secretary_judge={"checked": True, "axis": "clean", "decision": "没问题",
                         "reason": "夹具：clean"}) for _ in range(3)]
    key = str(rows[0].get("object_sha256") or rows[0].get("proof_sha256") or "")
    passes = [{"verification_id": r["verification_id"], "at": r["at"],
               "proof_sha256": r["proof_sha256"]} for r in rows]
    wrote = VS.issue(st.root, artifact_sha=PR.proof_sha(text), streak=3, need=3,
                     artifact_path=rel,
                     ledger=f"verifications/pending/{key}.jsonl"
                            f"#{rows[-1]['verification_id']}",
                     statement_id="", passes=passes, by="secretary:E")
    assert wrote.get("written") is True, wrote
    return rel


def _unsigned(st: Store, mid: str) -> str:
    rel = f"reports/e-proof-{mid}.md"
    path = pathlib.Path(st.root) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_e_text(BODY), encoding="utf-8")
    return rel


def _artifacts(st: Store, task_id: str = "t-000001") -> list[str]:
    row = next(dict(r) for r in st.rows("tasks")
               if str(r.get("task_id")) == task_id)
    return [str(x) for x in (row.get("artifacts") or [])]


def _submitted(out: dict) -> dict[str, dict]:
    return {str(x.get("manuscript_id")): dict(x)
            for x in (out.get("auto_submitted") or [])}


def _assert_a(st: Store, out: dict, mids: list[str]) -> None:
    got = _submitted(out)
    assert set(got) == set(mids), (sorted(got), mids)
    assert out.get("auto_submitted_count") == len(mids), out
    for mid in mids:
        one = got[mid]
        for key in ("body_sha", "sign_sha", "file_sha", "at", "manuscript"):
            assert str(one.get(key) or "").strip(), (mid, key, one)
        assert one["manuscript"] == f"reports/e-proof-{mid}.md", one
        assert len(str(one["body_sha"])) == 64, one
        assert len(str(one["sign_sha"])) == 64, one
        assert str(one.get("token") or "").startswith(f"mss:{mid}"), one
        assert str(one.get("via") or "") == MS.VIA_CLOSING, one
    assert set(MS.submissions_of(_artifacts(st))[0]) == set(mids)


# ============================================================ a：2 份已签 ⇒ 都提交
def test_a_two_signed_unsubmitted_are_auto_submitted(tmp_path):
    st = _ws(tmp_path)
    _task(st)
    mids = ["000000", "000001"]
    for mid in mids:
        _signed(st, mid)
    out = EAS.auto_submit_at_close(store=st, root=st.root, task_id="t-000001",
                                 stamp=S.now_iso())
    _assert_a(st, out, mids)


# ============================================================ b：幂等
def test_b_a_second_close_does_not_write_again(tmp_path):
    st = _ws(tmp_path)
    _task(st)
    mid = "000000"
    _signed(st, mid)
    first = EAS.auto_submit_at_close(store=st, root=st.root, task_id="t-000001",
                                   stamp=S.now_iso())
    _assert_a(st, first, [mid])
    before = list(_artifacts(st))
    second = EAS.auto_submit_at_close(store=st, root=st.root, task_id="t-000001",
                                    stamp=S.now_iso())
    assert second.get("auto_submitted") == [], second
    assert second.get("auto_submitted_count") == 0, second
    assert list(_artifacts(st)) == before, "第二次收工又写了一遍 artifacts"
    still = {str(x.get("manuscript_id")): dict(x)
             for x in (second.get("still_unsubmitted") or [])}
    assert str(still[mid].get("state")) == "already_submitted", still


# ============================================================ c：未签不提交
def test_c_an_unsigned_manuscript_is_not_submitted(tmp_path):
    st = _ws(tmp_path)
    _task(st)
    mid = "000002"
    _unsigned(st, mid)
    out = EAS.auto_submit_at_close(store=st, root=st.root, task_id="t-000001",
                                 stamp=S.now_iso())
    assert out.get("auto_submitted") == [], out
    still = {str(x.get("manuscript_id")): dict(x)
             for x in (out.get("still_unsubmitted") or [])}
    assert mid in still, still
    assert str(still[mid].get("state")) == "unsigned", still[mid]
    assert "未签" in str(still[mid].get("why") or ""), still[mid]
    assert _artifacts(st) == [], "未签的稿被写进了提交单"


# ============================================================ d：反真空
def test_d_stubbing_the_auto_submit_turns_a_red(tmp_path, monkeypatch):
    st = _ws(tmp_path)
    _task(st)
    mids = ["000000", "000001"]
    for mid in mids:
        _signed(st, mid)

    def _silent(*_a, **_kw):
        return {"checked": True, "auto_submitted": [], "auto_submitted_count": 0,
                "still_unsubmitted": [], "problems": [], "why": "打桩：不提交"}

    monkeypatch.setattr(MC, "auto_submit_for", _silent)
    out = EAS.auto_submit_at_close(store=st, root=st.root, task_id="t-000001",
                                 stamp=S.now_iso())
    assert out.get("auto_submitted") == [], out
    with pytest.raises(AssertionError):
        _assert_a(st, out, mids)


# ============================================================ e：E 的收工读数三格
def test_e_close_reading_carries_the_three_cells(tmp_path):
    st = _ws(tmp_path)
    _task(st)
    mid = "000003"
    _signed(st, mid)
    e = AgentE(st, config={"workspace_root": str(st.root)})
    with CND.calling_as("t-000001", "E", parent_task_id="t-000002", parent_role="D"):
        got = e.close_reading(stamp=S.now_iso())
    assert got.get("auto_submitted_count") == 1, got
    assert [str(x.get("manuscript_id")) for x in (got.get("auto_submitted") or [])] == [mid], got
    assert got.get("still_unsubmitted") == [], got
    assert set(MS.submissions_of(_artifacts(st))[0]) == {mid}

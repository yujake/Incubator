# -*- coding: utf-8 -*-
"""F 收工时自动提交其名下未提交的 V 签稿（业主 2026-11-11 裁定 ①，逐字）：

    「F侧报告收工时自动提交其名下未提交的V签稿」

## 这一份判据钉什么

| # | 造什么 | 期望 |
|---|---|---|
| a | F 名下 2 份已签、artifacts 里都没有 ⇒ 走到收工出口 | 两份的 `mss:<稿号>` 记号都在 F 那一行的 `artifacts` 里；`auto_submitted` 逐份点名（稿号 + 正文 sha + 签 sha + 时刻） |
| b | 同一趟再收工一次 | 一个字节都不重复写（幂等）；`auto_submitted` 空、`still_unsubmitted` 说「already_submitted」 |
| c | 盘上有一份没签的 F 稿 | 不提交；`still_unsubmitted` 逐条说「未签 ⇒ 不入提交单」 |
| d | 反真空：把自动提交摘掉 | a 那组断言必须红（静默不提交不许通过） |
| e | 签过之后正文又被改（签 sha ≠ 当前 sha） | 不提交；读数点名两个 sha 并说明「签后改正文违背只读纪律」 |

## 事实来源（业主同日裁定 ②）

签的那一侧只读 V 的颁发表（`out/vsigns/<正文sha>.json`），不新建表 —— 判据里
`FD.submission_candidates` 的 `sign_sha` 就是签文件的字节 sha256。

零模型调用：签用 `verifications.record_pending_sign` + `vsigns.issue` 直接造，
收工走 F 的 `step`（轮数用尽那条出口）。
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
from agentflow.agent_f import AgentF
from agentflow.agent_f import delivery as FD
from agentflow.store import Store

FULL = "设 f 在 [0,1] 上连续；则 f 在该区间上一致连续。"
BODY = ("1. 取 δ=ε：对任意 x,y∈[0,1]，|x-y|<δ ⇒ |f(x)-f(y)|<ε。\n"
        "2. 第 1 步的 δ 只依赖 ε、不依赖点 ⇒ 按定义即一致连续。")


# ---------------------------------------------------------------- 夹具
def _ws(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _f(st: Store) -> AgentF:
    return AgentF(st, config={"workspace_root": str(st.root), "plan_id": "0000"})


def _task(st: Store, *, task_id: str = "t-000001") -> dict:
    row = S.Task(task_id=task_id, role="F", action="step", called_by="M",
                 depth=1, status="running", started_at=S.now_iso(),
                 input_key="auto-submit-fixture")
    row.validate()
    with st.tx("tasks", actor="fixture") as tx:
        tx.upsert("tasks", row.to_dict())
    return row.to_dict()


def _manuscript_text(body: str = BODY) -> str:
    return ("# F 的证明手稿：一致连续\n\n"
            "- 依赖面洗稿：已洗=true；执行者=secretary:F\n\n"
            f"## 命题\n\n{FULL}\n\n## 证明\n\n{body}\n\n"
            + DS.render_dependency_section([]))


def _signed_manuscript(st: Store, mid: str, *, body: str | None = None) -> str:
    """落一份 `reports/f-proof-<mid>.md` 并拿到真签（三行 pending 台账 + 一份签文件）。

    正文里带一句稿号专属的收尾：两份不同的稿若正文逐字相同，正文 sha 也相同，
    签文件就只会有一份（一稿一签）—— 那是签的口径，不是这一份判据要造的现场。
    """
    body = BODY if body is None else body
    if body is BODY:
        body = BODY + f"\n3. 稿 {mid} 的收尾标记。"
    rel = f"reports/f-proof-{mid}.md"
    path = pathlib.Path(st.root) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    text = _manuscript_text(body)
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
                     ledger=(f"verifications/pending/{key}.jsonl"
                             f"#{rows[-1]['verification_id']}"),
                     statement_id="", passes=passes, by="secretary:F")
    assert wrote.get("written") is True, wrote
    return rel


def _unsigned_manuscript(st: Store, mid: str) -> str:
    rel = f"reports/f-proof-{mid}.md"
    path = pathlib.Path(st.root) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_manuscript_text(), encoding="utf-8")
    return rel


def _plan_used_up(f: AgentF) -> str:
    """一个预算已用尽的计划：`step` 必走 `_close_reading`（stalled 那条收工出口）。"""
    pid = str(f.create_plan("难题：判定这个族", "PK-179-AUTOSUBMIT", subgoals=[
        {"sid": "s1", "text": "证明：紧集上的连续函数一致连续", "owner": "F",
         "testable": "存在反例或有限界"}],
        budget={"max_rounds": 1, "max_parallel_subgoals": 1,
                "max_persist_attempts": 1, "max_depth": 1})["plan_id"])
    row = next(dict(r) for r in f.store.rows("attack_plans")
               if str(r.get("plan_id")) == pid)
    row["rounds"] = 1
    f._write_plan(row, note="test:used_up")
    return pid


def _close(f: AgentF, pid: str, *, task_id: str = "t-000001") -> dict:
    with CND.calling_as(task_id, "F", parent_task_id="t-000002",
                        parent_role="M"):
        out = f.step(pid)
    assert out.get("action") in ("stop", "stall_detected"), out
    return out


def _artifacts(st: Store, task_id: str = "t-000001") -> list[str]:
    row = next(dict(r) for r in st.rows("tasks")
               if str(r.get("task_id")) == task_id)
    return [str(x) for x in (row.get("artifacts") or [])]


def _submitted(out: dict) -> dict[str, dict]:
    return {str(x.get("manuscript_id")): dict(x)
            for x in (out.get("auto_submitted") or [])}


def _assert_a(st: Store, out: dict, mids: list[str]) -> None:
    """a 的断言（d 的反真空也走它）。"""
    got = _submitted(out)
    assert set(got) == set(mids), (sorted(got), mids)
    assert out.get("auto_submitted_count") == len(mids), out
    for mid in mids:
        one = got[mid]
        for key in ("body_sha", "sign_sha", "file_sha", "at", "manuscript"):
            assert str(one.get(key) or "").strip(), (mid, key, one)
        assert one["manuscript"] == f"reports/f-proof-{mid}.md", one
        assert len(str(one["body_sha"])) == 64, one
        assert len(str(one["sign_sha"])) == 64, one
        assert str(one.get("token") or "").startswith(f"mss:{mid}"), one
    # 记号也真进了那一行 artifacts（不只是返回值里的读数）
    assert set(FD.submissions_of(_artifacts(st))[0]) == set(mids)
    # 收工说明里也点得到（不只在结构化读数里）
    reason = str(out.get("reason") or "")
    for mid in mids:
        assert f"mss:{mid}" in reason, reason


# ============================================================ a：2 份已签 ⇒ 都提交
def test_a_two_signed_unsubmitted_are_auto_submitted(tmp_path):
    st = _ws(tmp_path)
    f = _f(st)
    _task(st)
    mids = ["000000", "000001"]
    for mid in mids:
        _signed_manuscript(st, mid)
    out = _close(f, _plan_used_up(f))
    _assert_a(st, out, mids)


# ============================================================ b：幂等
def test_b_a_second_close_does_not_write_again(tmp_path):
    st = _ws(tmp_path)
    f = _f(st)
    _task(st)
    mid = "000000"
    _signed_manuscript(st, mid)
    pid = _plan_used_up(f)
    first = _close(f, pid)
    _assert_a(st, first, [mid])
    before = list(_artifacts(st))
    second = _close(f, pid)
    assert second.get("auto_submitted") == [], second
    assert second.get("auto_submitted_count") == 0, second
    assert list(_artifacts(st)) == before, "第二次收工又写了一遍 artifacts"
    still = {str(x.get("manuscript_id")): dict(x)
             for x in (second.get("still_unsubmitted") or [])}
    assert str(still[mid].get("state")) == "already_submitted", still
    # 换一个 task 再收工也不重复写：「已提交」是稿号上的事实，不是某一趟的。
    _task(st, task_id="t-000002")
    third = _close(f, _plan_used_up(f), task_id="t-000002")
    assert third.get("auto_submitted") == [], third
    assert _artifacts(st, "t-000002") == [], "换一个 task 把同一份稿又提交了一遍"


# ============================================================ c：未签不提交
def test_c_an_unsigned_manuscript_is_not_submitted(tmp_path):
    st = _ws(tmp_path)
    f = _f(st)
    _task(st)
    mid = "000002"
    _unsigned_manuscript(st, mid)
    out = _close(f, _plan_used_up(f))
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
    f = _f(st)
    _task(st)
    mids = ["000000", "000001"]
    for mid in mids:
        _signed_manuscript(st, mid)

    def _silent(self, plan):
        return {"checked": True, "auto_submitted": [], "auto_submitted_count": 0,
                "still_unsubmitted": [], "problems": [], "why": "打桩：不提交"}

    monkeypatch.setattr(AgentF, "_auto_submit_signed", _silent)
    out = _close(f, _plan_used_up(f))
    assert out.get("auto_submitted") == [], out      # 打桩之后它确实没提交
    with pytest.raises(AssertionError):
        _assert_a(st, out, mids)


# ============================================================ e：签后改正文
def test_e_a_changed_body_after_signing_is_not_submitted(tmp_path):
    st = _ws(tmp_path)
    f = _f(st)
    _task(st)
    mid = "000003"
    rel = _signed_manuscript(st, mid)
    path = pathlib.Path(st.root) / rel
    signed_text = path.read_text(encoding="utf-8")
    signed_sha = PR.proof_sha(signed_text)
    # 签完再改正文（违背只读/冻结纪律的那一形态）
    path.write_text(signed_text.replace("2. 第 1 步", "2. 第 1 步（改过）"),
                    encoding="utf-8")
    current_sha = PR.proof_sha(path.read_text(encoding="utf-8"))
    assert signed_sha != current_sha

    out = _close(f, _plan_used_up(f))
    assert out.get("auto_submitted") == [], out
    assert _artifacts(st) == [], "签后被改过的正文被提交了"
    still = {str(x.get("manuscript_id")): dict(x)
             for x in (out.get("still_unsubmitted") or [])}
    one = still[mid]
    assert str(one.get("state")) == "body_changed_after_sign", one
    assert str(one.get("signed_sha")) == signed_sha, one
    assert str(one.get("current_sha")) == current_sha, one
    assert one.get("sha_matches") is False, one
    why = str(one.get("why") or "")
    assert signed_sha in why and current_sha in why, why
    assert "只读" in why and "不提交" in why, why


def test_e2_removing_the_sha_pairing_turns_e_red(tmp_path, monkeypatch):
    """e 的反真空：把「签 sha 与当前 sha 不一致 ⇒ 不提交」那条检查摘掉 ⇒ e 必须红。"""
    st = _ws(tmp_path)
    f = _f(st)
    _task(st)
    mid = "000003"
    rel = _signed_manuscript(st, mid)
    path = pathlib.Path(st.root) / rel
    text = path.read_text(encoding="utf-8")
    path.write_text(text.replace("2. 第 1 步", "2. 第 1 步（改过）"),
                    encoding="utf-8")

    real = FD.submission_candidates

    def _no_sha_pairing(root):
        got = real(root)
        for cand in got.get("candidates") or []:
            if not cand.get("signed"):
                cand.update(signed=True, state="signed",
                            signed_sha=cand.get("current_sha") or "",
                            why="打桩：不看签 sha 与当前 sha 配不配")
        return got

    monkeypatch.setattr(FD, "submission_candidates", _no_sha_pairing)
    out = _close(f, _plan_used_up(f))
    assert out.get("auto_submitted"), (
        "摘掉 sha 配对检查之后仍然没提交 —— 这条反真空不成立", out)
    assert _artifacts(st), "摘掉 sha 配对检查之后 artifacts 仍为空"


if __name__ == "__main__":          # pragma: no cover - 手工跑这一份时用
    raise SystemExit(pytest.main([__file__, "-q"]))

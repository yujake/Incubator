# -*- coding: utf-8 -*-
"""甲（2026-11-11，业主裁定）：「签是事件，收工是轮询」—— 签那一刻就提交。

## 真机现场（`projects/dct-min5r-20261111`）

```
F 21:21 收工（收工自动提交扫的时候还没签）⇒ auto_submitted=[]、auto_submitted_count=null
V 21:37 才签                                   ⇒ 稿至今「已签、未提交」、0 个 mss: 记号
```

两条路里选了「签触发」那一条：在 `vsigns.issue` 成功（签文件已在盘上）之后，由框架
调 `manuscriptsubmission.mark_sign_submitted`，复用 `agent_f/submission.py` 的 `mss:`
记号写进产出方那一行 `tasks.artifacts`（幂等：该稿号已有记号就不重复写）。
另一条路（产出方收工前必须等到签）作为题面义务写进 F/E/B 三份 specs，并由收工门
`_v_wait_gate_reading` 挡住「送审后没起 wait_for=V 的计时器就收工」。

## 这一组守什么

| # | 造什么 | 期望 |
|---|---|---|
| a | F 派过 V、没起计时器 ⇒ final | 收工被拒（`complete=False`，拒信点名 V 的编号与 `clock.timer_start`） |
| a2 | 同一次派 V，起了 `wait_for=task:<V>` 的计时器 | 放行；指着更早那一次 V 的计时器不算 |
| b | 先收工（无签）→ 之后 V 才签 | 稿最终有 `mss:` 记号，`via=sign_issued` |
| c | 签触发 + 收工各一次 | 只有一条记号（幂等） |
| d | 反真空：把签触发摘掉 | b 的断言红 |

零模型调用：签用 `verifications.record_pending_sign` + `vsigns.issue` 直接造。
"""
from __future__ import annotations

import pathlib

import pytest
from agentflow import agent_loop as AL
from agentflow import clock as CLK
from agentflow import conductor as CND
from agentflow import depsection as DS
from agentflow import manuscriptsubmission as MS
from agentflow import proofregistry as PR
from agentflow import schema as S
from agentflow import verifications as VR
from agentflow import vsigns as VS
from agentflow.agent_f import autosubmit as AS
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


def _task(st: Store, *, task_id: str = "t-000001", role: str = "F",
          status: str = "running") -> dict:
    row = S.Task(task_id=task_id, role=role, action="step", called_by="M",
                 depth=1, status=status, started_at=S.now_iso(),
                 ended_at=(S.now_iso() if status == "done" else None),
                 input_key="jia-sign-fixture")
    row.validate()
    with st.tx("tasks", actor="fixture") as tx:
        tx.upsert("tasks", row.to_dict())
    return row.to_dict()


def _manuscript(st: Store, mid: str) -> str:
    rel = f"reports/f-proof-{mid}.md"
    path = pathlib.Path(st.root) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "# F 的证明手稿：一致连续\n\n"
        "- 命题号：stmt:（还没落号）\n"
        "- 依赖面洗稿：已洗=true；执行者=secretary:F\n\n"
        f"## 命题\n\n{FULL}\n\n## 证明\n\n{BODY}\n\n"
        + DS.render_dependency_section([]), encoding="utf-8")
    return rel


def _close(st: Store, *, task_id: str = "t-000001") -> dict:
    with CND.calling_as(task_id, "F", parent_task_id="t-000000", parent_role="M"):
        return AS.auto_submit_signed(store=st, root=st.root, plan_id="0000",
                                     stamp=S.now_iso())


def _sign(st: Store, rel: str) -> dict:
    """走 V 那条真路（三行 pending 台账 + `vsigns.issue(store=...)`）。"""
    text = (pathlib.Path(st.root) / rel).read_text(encoding="utf-8")
    body = BODY
    rows = [VR.record_pending_sign(
        st.root, proof_text=body, verdict={"verdict": "成立", "findings": []},
        verifier="agent-V", object_path=rel,
        secretary_judge={"checked": True, "axis": "clean", "decision": "没问题",
                         "reason": "夹具：clean"}) for _ in range(3)]
    key = str(rows[0].get("object_sha256") or rows[0].get("proof_sha256") or "")
    passes = [{"verification_id": r["verification_id"], "at": r["at"],
               "proof_sha256": r["proof_sha256"]} for r in rows]
    return VS.issue(st.root, artifact_sha=PR.proof_sha(text), streak=3, need=3,
                    artifact_path=rel,
                    ledger=f"verifications/pending/{key}.jsonl"
                           f"#{rows[-1]['verification_id']}",
                    statement_id="", passes=passes, by="secretary:F", store=st)


def _tokens(st: Store, *, task_id: str = "t-000001") -> list[str]:
    row = next(dict(r) for r in st.rows("tasks")
               if str(r.get("task_id")) == task_id)
    return [str(x) for x in (row.get("artifacts") or ())]


class _Run:
    def __init__(self) -> None:
        self.notes: list[str] = []


class _Shell:
    """把 `AgentLoop._final_gate_reading` 挂到一个只有四格属性的壳上。"""

    role = "F"
    my_task_id = "t-000001"
    max_final_refused = 3
    conductor = None

    def __init__(self, st: Store) -> None:
        self.store = st
        self.workspace_root = str(st.root)

    def reading(self, run: _Run | None = None) -> dict:
        return AL.AgentLoop._final_gate_reading(self, run)

    def _v_wait_gate_reading(self) -> dict:
        return AL.AgentLoop._v_wait_gate_reading(self)


def _refused(reading: dict) -> bool:
    return bool(reading.get("applicable")) and not bool(reading.get("complete"))


# ============================================================ a：送审后没等 ⇒ 不许收工
def test_a_closing_without_a_wait_for_v_timer_is_refused(tmp_path):
    st = _ws(tmp_path)
    _task(st)
    _task(st, task_id="t-000002", role="V")
    with st.tx("tasks", actor="fixture") as tx:
        v = dict(tx.find("tasks", task_id="t-000002"))
        v["parent_task_id"] = "t-000001"
        v["called_by"] = "F"
        tx.upsert("tasks", v)
    reading = _Shell(st).reading(_Run())
    assert _refused(reading), reading
    why = str(reading.get("why") or "")
    assert "t-000002" in why, why
    assert "clock.timer_start" in why and "wait_for" in why, why
    # 计时器那两格是读数：没起过 ⇒ 空表；等的是哪一条 ⇒ 点名最近那个 V
    assert reading.get("v_wait_timers") == [], reading
    assert reading.get("v_wait_for") == "task:t-000002", reading


# ============================================================ a2：等对了就放行
def test_a2_a_timer_waiting_for_that_v_lets_the_close_through(tmp_path):
    st = _ws(tmp_path)
    _task(st)
    _task(st, task_id="t-000002", role="V")
    _task(st, task_id="t-000003", role="V")
    with st.tx("tasks", actor="fixture") as tx:
        for tid in ("t-000002", "t-000003"):
            v = dict(tx.find("tasks", task_id=tid))
            v["parent_task_id"] = "t-000001"
            v["called_by"] = "F"
            v["started_at"] = ("2026-11-11T21:00:0" + tid[-1] + "+08:00")
            tx.upsert("tasks", v)
    # 只等了更早那一次 V ⇒ 不算（最近那一次没等）
    CLK.start_timer(st.root, wait_for="task:t-000002", reason="等 V 的结论",
                    task_id="t-000001", role="F")
    refused = _Shell(st).reading(_Run())
    assert _refused(refused), refused
    assert refused.get("v_wait_for") == "task:t-000003", refused
    # 等最近那一次 ⇒ 放行
    CLK.start_timer(st.root, wait_for="task:t-000003", reason="等 V 的结论",
                    task_id="t-000001", role="F")
    ok = _Shell(st).reading(_Run())
    assert not _refused(ok), ok
    assert ok.get("v_wait_timers"), ok


# ============================================================ b/c：签晚于收工
def test_b_sign_after_close_still_lands_a_token(tmp_path):
    st = _ws(tmp_path)
    _task(st)
    rel = _manuscript(st, "000000")
    # ① 收工那一刻还没签：扫盘读成「未签 ⇒ 不入提交单」，一个字节都不写
    first = _close(st)
    assert first.get("auto_submitted") == [], first
    assert _tokens(st) == [], _tokens(st)
    # ② 收工那一行已经是终态（真机次序：F 21:21 收工）
    with st.tx("tasks", actor="fixture") as tx:
        row = dict(tx.find("tasks", task_id="t-000001"))
        row["status"] = "done"
        row["outcome"] = "ok"
        row["detail"] = "收工（夹具：真机 21:21 收工那一刻）"
        row["ended_at"] = S.now_iso()
        tx.upsert("tasks", row)
    # ③ V 现在才签（21:37）⇒ 签触发提交
    got = _sign(st, rel)
    assert got.get("written") is True, got
    sub = dict(got.get("submission") or {})
    assert sub.get("written") is True, sub
    tokens, _bad = FD.submissions_of(_tokens(st))
    assert "000000" in tokens, _tokens(st)
    rec = dict(tokens["000000"])
    assert rec.get("via") == MS.VIA_SIGN, rec
    assert str(rec.get("token") or "").startswith("mss:000000"), rec
    assert len(str(rec.get("body_sha") or "")) == 64, rec
    assert len(str(rec.get("sign_sha") or "")) == 64, rec
    # 统一读口也读得出来（不只是记号本身）
    read = MS.submission_reading(st, st.root, manuscript_id="000000")
    assert read.get("state") == "submitted", read
    assert read.get("via") == MS.VIA_SIGN, read


def test_c_sign_then_close_write_only_one_token(tmp_path):
    st = _ws(tmp_path)
    _task(st)
    rel = _manuscript(st, "000000")
    got = _sign(st, rel)
    assert got.get("written") is True, got
    before = list(_tokens(st))
    # ① 同一份签再颁一次（idempotent）⇒ 签触发那一笔读成 already，不重复写
    again = _sign(st, rel)
    assert again.get("idempotent") is True, again
    assert (again.get("submission") or {}).get("already") is True, again
    # ② 收工那一趟再扫一次 ⇒ already_submitted，不重复写
    closed = _close(st)
    assert closed.get("auto_submitted") == [], closed
    still = {str(x.get("manuscript_id")): dict(x)
             for x in (closed.get("still_unsubmitted") or [])}
    assert str(still["000000"].get("state")) == "already_submitted", still
    after = list(_tokens(st))
    assert after == before, (after, before)
    tokens, _bad = FD.submissions_of(after)
    assert list(tokens) == ["000000"], tokens


def test_d_without_the_sign_trigger_b_goes_red(tmp_path, monkeypatch):
    """反真空：把签触发摘掉 ⇒ 真机那个次序之后稿永远没有记号（b 的断言必须红）。"""
    st = _ws(tmp_path)
    _task(st)
    rel = _manuscript(st, "000000")
    _close(st)

    def _silent(**__):
        return {"checked": True, "written": False, "already": False,
                "manuscript_id": "000000", "producer_role": "F", "task_id": "",
                "token": "", "via": "", "why": "打桩：签不触发提交"}

    monkeypatch.setattr(MS, "mark_sign_submitted", _silent)
    got = _sign(st, rel)
    assert got.get("written") is True, got
    assert got.get("submission", {}).get("written") is False, got
    tokens, _bad = FD.submissions_of(_tokens(st))
    with pytest.raises(AssertionError):
        assert "000000" in tokens

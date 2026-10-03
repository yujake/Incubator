"""§58 的判据：带 sid 的运行里问过的问题，判据必须看得见（`reviewaccept` / `closing`）。

第九趟真机（`draft/37` §58）撞出来的：那一趟问了（`q0001`，落在
`sessions/real9.jsonl`），而 `check_review` / `check_closing` 都不带 `sid`
⇒ 按默认会话读 ⇒ `triage_branch_recorded` 报"一次都没问过用户"、
`user_pending` 报 pass —— 两处都读错了，而病因在调用姿势上。
"""
from __future__ import annotations

import json
from pathlib import Path

from agentflow import closing as CL
from agentflow import reviewaccept as RA
from agentflow import sessions as SS
from agentflow import store as S

WS_QUESTION = {
    "kind": "user_question", "role": "M", "qid": "q0001",
    "text": "这四处改动要不要保留？", "options": ["保留", "回退"], "timeout_sec": 60.0,
}
WS_ANSWER = {"kind": "user_answer", "qid": "q0001", "answer": "保留",
             "by": "user", "role": "M"}


def _ws(tmp_path: Path, *, sid: str, answered: bool) -> Path:
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    st = S.Store(tmp_path)
    st.init()
    SS.append(tmp_path, WS_QUESTION, sid=sid)
    if answered:
        SS.append(tmp_path, WS_ANSWER, sid=sid)
    return tmp_path


def test_a_question_in_a_sid_scoped_run_is_visible_to_the_judges(tmp_path: Path):
    """正控：带 sid 的提问被判据读到 —— 没答 ⇒ `fail`（应停在等待用户），答了 ⇒ `pass`。"""
    ws = _ws(tmp_path / "answered", sid="real9", answered=True)
    st = S.Store(ws)
    st.init()
    acc = RA.check_review(st, project_dir=str(ws), report_path="", cost_cap_usd=1.0, sid="real9")
    assert acc.criteria["triage_branch_recorded"] == "pass", acc.details
    rep = CL.check_closing(st, project_dir="", report_path="", sid="real9")
    assert rep.status["user_pending"] == "pass", rep.to_dict()

    ws2 = _ws(tmp_path / "pending", sid="real9", answered=False)
    st2 = S.Store(ws2)
    st2.init()
    acc2 = RA.check_review(st2, project_dir=str(ws2), report_path="", cost_cap_usd=1.0, sid="real9")
    assert acc2.criteria["triage_branch_recorded"] == "fail", acc2.details
    assert "没被回答" in acc2.details["triage_branch_recorded"], acc2.details
    rep2 = CL.check_closing(st2, project_dir="", report_path="", sid="real9")
    assert rep2.status["user_pending"] == "fail", rep2.to_dict()


def test_a_question_from_another_run_is_not_counted(tmp_path: Path):
    """负控：别的 sid 的提问不算这一趟的 —— 不带 sid（或带错 sid）时看不见它。"""
    ws = _ws(tmp_path / "other", sid="real-other", answered=True)
    st = S.Store(ws)
    st.init()
    acc = RA.check_review(st, project_dir=str(ws), report_path="", cost_cap_usd=1.0, sid="real9")
    assert acc.criteria["triage_branch_recorded"] == "unknown", acc.details
    rep = CL.check_closing(st, project_dir="", report_path="", sid="real9")
    assert rep.status["user_pending"] == "pass", rep.to_dict()   # 没有待答问题 ⇒ pass 是对的
    # 不带 sid 时同样看不见（这是老行为，保持住：默认会话里没有它）
    acc2 = RA.check_review(st, project_dir=str(ws), report_path="", cost_cap_usd=1.0)
    assert acc2.criteria["triage_branch_recorded"] == "unknown", acc2.details


def test_the_answer_event_shape_is_what_the_reader_expects(tmp_path: Path):
    """反真空：上面的夹具真的能被 `userio` 读出来（否则那两条判据测的是空集）。"""
    from agentflow import userio as U

    ws = _ws(tmp_path / "reader", sid="real9", answered=True)
    pending = U.pending_questions(ws, sid="real9")
    replies = U.read_replies(ws, sid="real9")
    assert [q.qid for q in pending] == [], "夹具前提：那个问题已经被回答 ⇒ 不该还在待答里"
    qids = [getattr(r, "qid", "") or (r.get("qid") if isinstance(r, dict) else "")
            for r in replies]
    assert "q0001" in qids, (qids, replies)

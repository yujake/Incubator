# -*- coding: utf-8 -*-
"""167 判据：V 回执的投递不依赖收件人醒来（业主 2026-11-01 裁定的丙案）。

## 为什么需要这一组（81 的真机读数）

改前 `deliver_v_verdicts` 的唯一调用点是 `AgentLoop.run` 的 F 分支 ⇒ 送达是"收件人
下一次起跑"的副作用。81 的 8 条「有毛病」里，后 4 条（04:05–04:14）全在 F 最后一次
起跑（03:54:03）之后 ⇒ 连板项都没开。

## 这组判据守的四件事（逐条都能红）

| # | 它要证明的事 | 它能怎么红 |
|---|---|---|
| 1 | 8 条判定 + F 一次不跑 ⇒ 8 条都有板项，`not_dispatched == 0` | 把投递挂回收件人起跑 ⇒ 一条都没有 |
| 2 | 反真空：把 `_publish_receipt` 摘掉 ⇒ 1 变红 | 摘掉之后还有项 ⇒ 判据 1 量的是"盘上本来就有" |
| 3 | 同一 label 不同 vid 是两条独立项（不按 label 合并） | 键里少了 vid ⇒ 只剩一条 |
| 4 | 同一条判定投两次 / 两个线程同时投 ⇒ 板项只 1 行 | 去掉 outbox 锁或键里少了收件人 ⇒ 2 行 |
| 5 | 补投源是 `receipt_digest` 全集：同一份证明判两次 ⇒ 补投 2 条 | 换成 `v_rejections_digest` ⇒ 只有 1 条（它只给最近那一签） |
| 6 | 收件人读不到 ⇒ 记 `undelivered`，不猜（不开项） | 拿"谁醒着"兜底 ⇒ 会开出一项 |
| 7 | `conductor.closing` 的调用链里带着补投读数（不新增顶层键） | 不接 ⇒ 读数里没有 `v_receipts` |
| 8 | 替人送审（F 写、B 送）⇒ `submitter_is_not_author` 出现，且回执仍投送审者 B | 按作者改投 ⇒ 项会落在 F 的板上 |
| 9 | 作者未记录 ⇒ 记 `author_not_recorded`（不是"没问题"），也不改投 | 默认"作者=送审者" ⇒ 这一格消失 |
| 10 | B 的收录路径不发起送审（`register_statement` 里没有 `verify_proof`） | 顺手加一次送审 ⇒ 判据红 |

## 三个数分开报（不许折平）

`dispatched`（有板项）/ `delivered`（收件人读过并 ack）/ `not_dispatched`（连板项都
没有）。判据 1 断言的只是"8 条都有板项"，不是"8 条都送达"——按现读，投出去之后
`delivered` 仍然是 0，那是对的（没人读）。
"""
from __future__ import annotations

import json
import threading
import time

import pytest

from _proof_manuscript_fixture import write_proof_manuscript

from agentflow import closing as CL
from agentflow import conductor as CND
from agentflow import reviewaccept as RX
from agentflow import schema as S
from agentflow import verifications as VR
from agentflow import vreceipts as VRC
from agentflow import vsigns as VSP
from agentflow.agent_v import AgentV
from agentflow.conductor import Conductor
from agentflow.store import Store
from agentflow.tools import conductor_tools as CT
from agentflow.tools.conductor_tools import conductor_for, reset_cache

TS = S.now_iso()
SID = "000019"
PROOF = "1. 取 G = C_n（n ≥ 3）：它是 2-正则、围长为 n。\n2. 由第 1 步直接得到结论。"
FULL = "设 G 是 3-正则群；则弦长函数不是常值。"
REPLY_DEFECT = json.dumps({
    "verdict": "有毛病", "defect_step": 2, "why": "第 2 步没有依据",
    "findings": [{"level": "error", "step": 2, "kind": "无依据的步骤",
                  "detail": "第 2 步直接用了结论"}],
}, ensure_ascii=False)


# ------------------------------------------------------------------ 夹具

class _Call:
    ok = True
    problem = ""
    detail = ""
    text = ""
    model = "fake"
    prompt_version = "t"
    prompt_sha256 = "0" * 64


class _Seam:
    """V 自己的那条缝：只喂 `verify_proof` 的审阅结论（不联网、不碰秘书）。"""

    wired = True

    def __init__(self, *replies: str) -> None:
        self.replies = list(replies)

    def ask(self, prompt: str = "", **_kw) -> _Call:
        call = _Call()
        call.text = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        return call


def _ws(tmp_path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _put(st: Store, sid: str = SID, *, proof: str = PROOF) -> dict:
    row = {
        "stmt_id": sid, "origin": "own_result", "kind": "theorem",
        "label": f"探针命题 {sid}", "statement_full": FULL,
        "statement_text": FULL, "proof_text": proof,
        "evidence_kind": "heuristic", "status": "active",
        "quote_verified": None, "quote_reason": "夹具：自产命题",
        "created_at": TS, "created_by": "test", "bits": {},
    }
    with st.tx("statements", actor="test") as tx:
        tx.upsert("statements", row)
    return row


def _agent_row(st: Store, *, role: str = "B", parent: str = "t-root",
               depth: int = 2, status: str = "done",
               started: str = "", ended: str = "") -> str:
    """落一条代理行（`kind` 空）：收件人 / V 的时间窗都用它。"""
    started = started or TS
    return Conductor._write_new_row(
        conductor_for(st), {
            "task_id": "", "role": role, "action": "", "called_by": "M",
            "parent_task_id": parent, "depth": depth, "input_key": f"@t:{role}:{time.time()}",
            "status": status, "outcome": "ok" if status == "done" else None,
            "refusal_reason": None, "instance": f"{role}#1", "detail": "夹具",
            "error": None, "started_at": started,
            "ended_at": (ended or (TS if status == "done" else None)),
            "tokens": 0, "usd": 0.0, "artifacts": [], "inputs": [],
        }, note="probe:agent")


def _conductor(st: Store):
    reset_cache()
    return conductor_for(st)


def _verify(st: Store, sid: str, *, v_task: str, parent: str,
            role: str = "B", reply: str = REPLY_DEFECT) -> dict:
    """走 V 的真入口：`AgentV.verify_proof`（投递钩子在它里面）。

    2026-11-04（业主裁定 甲）：在册命题送审必须带手稿 ⇒ 夹具给被审的那一份正文落一份
    按号命名的稿（`## 证明` 与 `proof_text` 逐字一致、`## 依赖` 空表），再带
    `proof_manuscript` 送审。投递判据一个字没改：量的是同一份判定照旧投出去。
    """
    row = next((dict(r) for r in st.rows("statements")
                if str(r.get("stmt_id") or "") == str(sid)), {})
    text = str(row.get("proof_text") or PROOF)
    rel = write_proof_manuscript(st.root, str(sid), text,
                                 statement_full=str(row.get("statement_full") or ""))
    agent = AgentV(st, workspace_root=st.root, llm=_Seam(reply))
    with CND.calling_as(v_task, "V", parent_task_id=parent, parent_role=role):
        return agent.verify_proof(sid, proof_text=text, proof_manuscript=rel)


def _items(st: Store) -> list[dict]:
    return [dict(r) for r in st.rows("tasks")
            if str(r.get("input_key") or "").startswith("v-verdict@")]


def _ledger_row(st: Store, sid: str, vid: str) -> dict:
    rows, _ = VR.list_verifications(st.root, statement_id=sid, limit=None)
    return next(dict(r) for r in rows if str(r.get("verification_id")) == vid)


# ------------------------------------------------------------------ 1 正控

def test_eight_verdicts_all_dispatched_with_f_never_running(tmp_path):
    """8 条判定 + F 一次都不跑 ⇒ 8 条都有板项，`not_dispatched == 0`。

    改前红：投递挂在 F 的 `run()` 起跑处 ⇒ 这个现场一条板项都不会有。
    """
    st = _ws(tmp_path)
    _conductor(st)
    recipient = _agent_row(st, role="B")          # 送审者：B
    for i in range(8):
        sid = S.format_id(i + 1)
        _put(st, sid)
        got = _verify(st, sid, v_task="t-v1", parent=recipient)
        assert got.get("checked") is True and got.get("verdict") == "有毛病", got

    # 现场里没有任何 F 的台账号 —— "收件人不醒"这件事是结构性的，不是时序凑巧。
    assert not [r for r in st.rows("tasks") if str(r.get("role")) == "F"], \
        "这个现场不该有 F 的台账号（判据要的是「F 一次都不跑」）"

    items = _items(st)
    assert len(items) == 8, [(r.get("task_id"), r.get("input_key")) for r in items]
    for i in range(8):
        sid = S.format_id(i + 1)
        want = f"v-verdict@{sid}#p1@v-000001@{recipient}"
        hit = [r for r in items if str(r.get("input_key")) == want]
        assert len(hit) == 1, (want, [r.get("input_key") for r in items])
        assert str(hit[0].get("parent_task_id")) == recipient, hit[0]
        assert str(hit[0].get("kind")) == "notice" and str(hit[0].get("expects")) == "ack"

    got = VSP.receipt_digest(st.root, st, limit=100)
    assert got["receipts"] == 8, got["reason"]
    assert got["dispatched"] == 8 and got["not_dispatched"] == 0, got["reason"]
    # 投出去 ≠ 送到：一条都没人读。
    assert got["delivered"] == 0, got["reason"]


# ------------------------------------------------------------------ 2 反真空

def test_taking_the_hook_out_leaves_zero_items(tmp_path, monkeypatch):
    """反真空：把 `AgentV._publish_receipt` 摘成空转 ⇒ 判据 1 必须变红。"""
    st = _ws(tmp_path)
    _conductor(st)
    recipient = _agent_row(st, role="B")
    monkeypatch.setattr(AgentV, "_publish_receipt", lambda self, row: {})
    for i in range(8):
        sid = S.format_id(i + 1)
        _put(st, sid)
        assert _verify(st, sid, v_task="t-v1", parent=recipient).get("checked") is True
    assert _items(st) == [], "钩子被摘掉了，板上却仍然冒出判决项 ⇒ 这条反真空没打中"
    assert VSP.receipt_digest(st.root, st)["not_dispatched"] == 8


# ------------------------------------------------------------------ 3 label 相同、vid 不同

def test_same_label_different_vid_are_two_items(tmp_path):
    """同一份证明判两次（两个 vid）⇒ 两条独立项（键里少了 vid 就会并成一条）。"""
    st = _ws(tmp_path)
    _conductor(st)
    recipient = _agent_row(st, role="B")
    _put(st, SID)
    _verify(st, SID, v_task="t-v1", parent=recipient)
    _verify(st, SID, v_task="t-v1", parent=recipient)
    keys = sorted(str(r.get("input_key")) for r in _items(st))
    assert keys == [f"v-verdict@{SID}#p1@v-000001@{recipient}",
                    f"v-verdict@{SID}#p1@v-000002@{recipient}"], keys


# ------------------------------------------------------------------ 4 幂等 / 并发

def test_publishing_the_same_row_twice_adds_nothing(tmp_path):
    st = _ws(tmp_path)
    _conductor(st)
    recipient = _agent_row(st, role="B")
    _put(st, SID)
    _verify(st, SID, v_task="t-v1", parent=recipient)
    assert len(_items(st)) == 1
    row = _ledger_row(st, SID, "v-000001")
    with CND.calling_as("t-v1", "V", parent_task_id=recipient, parent_role="B"):
        again = VRC.publish_row(st, row)
    assert again["state"] == VRC.DISPATCHED and again["opened"] is False, again
    assert len(_items(st)) == 1, [r.get("input_key") for r in _items(st)]
    box = VRC.outbox_digest(st.root)
    assert (box["keys"], box["dispatched"]) == (1, 1), box


def test_two_threads_publishing_the_same_row_open_one_item(tmp_path):
    """并发负控：两个线程同时投同一条 ⇒ 板项只 1 行（outbox 锁 + 先写后查）。

    改前红：幂等靠"先读板、再开项"，两个投递者同时拿到"还没有这一条"的板快照
    就会各开一项（2026-11-01 探针实测过同键 2 行）。
    """
    st = _ws(tmp_path)
    _conductor(st)
    recipient = _agent_row(st, role="B")
    _put(st, SID)
    _verify(st, SID, v_task="t-v1", parent=recipient)
    assert len(_items(st)) == 1
    row = _ledger_row(st, SID, "v-000001")

    # 先把这一条从板上与 outbox 里"取消"，让两个线程都从零开始（同一条判定）。
    key = VRC.key_of(f"{SID}#p1", "v-000001", recipient)
    outbox = VRC.outbox_path(st.root)
    outbox.write_text("", encoding="utf-8")
    with st.tx("tasks", actor="test") as tx:
        for r in _items(st):
            tx.delete("tasks", r["task_id"])

    barrier = threading.Barrier(2)
    errors: list[BaseException] = []
    seen: list[dict] = []

    def _work() -> None:
        try:
            with CND.calling_as("t-v1", "V", parent_task_id=recipient, parent_role="B"):
                barrier.wait(timeout=10)
                seen.append(VRC.publish_row(st, row))
        except BaseException as exc:  # noqa: BLE001 —— 线程里的异常要带回主线程
            errors.append(exc)

    threads = [threading.Thread(target=_work) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert not errors, errors
    # 板上原来那 1 行 + 这一次只许再开 0 行（两个线程抢同一把锁，第二个看到 dispatched）。
    after = [r for r in _items(st) if str(r.get("input_key")) == key]
    assert len(after) == 1, [(r.get("task_id"), r.get("input_key")) for r in after]
    assert sum(1 for r in seen if r.get("state") == VRC.DISPATCHED) == 2, seen
    assert sum(1 for r in seen if r.get("opened")) == 1, seen


# ------------------------------------------------------------------ 5 乙 的补投源

def test_backfill_uses_every_fault_row_not_only_the_latest_sign(tmp_path):
    """同一份证明判两次 ⇒ 乙 补投 2 条；`v_rejections_digest` 只给 1 条。

    这一条就是 81 的"8 条 vs 7 条"：补投源必须是 `receipt_digest` / `_fault_rows`
    的全集，不是"每份证明最近那一签"。
    """
    st = _ws(tmp_path)
    _conductor(st)
    recipient = _agent_row(st, role="B")
    # 一条 V 的时间窗：补投解析"送审者"要靠它（唯一才认，见 `resolve_recipient`）。
    _agent_row(st, role="V", parent=recipient, depth=3,
               started="2026-11-01T00:00:00+08:00", ended="2099-01-01T00:00:00+08:00")
    _put(st, SID)
    _verify(st, SID, v_task="t-v1", parent=recipient)
    _verify(st, SID, v_task="t-v1", parent=recipient)
    # 把甲 开的两项撤掉（模拟"改前判的、当时没人投"）：板项清零，只留台账。
    with st.tx("tasks", actor="test") as tx:
        for r in _items(st):
            tx.delete("tasks", r["task_id"])

    # 两个读数在同一个现场给出两个数：这是补投源选择的唯一依据。
    digest = VSP.receipt_digest(st.root, st, limit=100)
    _text, details, _p = AL_digest(st)
    assert digest["receipts"] == 2, digest["reason"]
    assert digest["not_dispatched"] == 2, digest["reason"]
    assert len(details) == 1, details          # v_rejections_digest：只有最近那一签

    got = VRC.backfill(store=st, caller="test")
    assert len(got["opened"]) == 2, got
    assert got["dispatched"] == 2 and got["not_dispatched"] == 0, got["reason"]
    assert sorted(str(r.get("input_key")) for r in _items(st)) == [
        f"v-verdict@{SID}#p1@v-000001@{recipient}",
        f"v-verdict@{SID}#p1@v-000002@{recipient}",
    ]
    # 再扫一次：不新开（认领已有的两条）。
    again = VRC.backfill(store=st, caller="test")
    assert again["opened"] == [] and len(again["adopted"]) == 2, again


def AL_digest(st: Store):
    """`v_rejections_digest` 的现读（与 `receipt_digest` 对照用）。"""
    from agentflow import agent_loop as AL

    return AL.v_rejections_digest(st.root, [dict(r) for r in st.rows("statements")],
                                  store=st)


# ------------------------------------------------------------------ 6 收件人不可判

def test_an_unresolvable_recipient_is_recorded_not_guessed(tmp_path):
    """那一拍有 2 趟 V 在跑 ⇒ 送审者不可判 ⇒ `undelivered`，一条项都不开。"""
    st = _ws(tmp_path)
    _conductor(st)
    _put(st, SID)
    # 两趟 V 的时间窗都盖住这条判定 ⇒ 不可判（81 的 03:35 那一拍就是这个形状）。
    now = S.now_iso()
    _agent_row(st, role="V", parent="t-b1", depth=3, started="2026-11-01T00:00:00+08:00",
               ended="2099-01-01T00:00:00+08:00")
    _agent_row(st, role="V", parent="t-b2", depth=3, started="2026-11-01T00:00:00+08:00",
               ended="2099-01-01T00:00:00+08:00")
    VR.record_verification(st.root, statement_id=SID, proof_text=PROOF,
                           verdict={"verdict": "有毛病", "defect_step": 2,
                                    "findings": []},
                           verifier="agent-V", store=st, proof_no=1)
    got = VRC.backfill(store=st, caller="test")
    assert got["opened"] == [], got
    assert got["undelivered"] and "不可判" in got["undelivered"][0], got
    assert _items(st) == [], "收件人不可判却开出了项 ⇒ 这一条是猜的"
    box = VRC.outbox_digest(st.root)
    assert box["undelivered"] == 1 and box["dispatched"] == 0, box
    assert now  # 时间戳只是夹具的锚，不参与断言


# ------------------------------------------------------------------ 7 乙 挂在收工链上

class _Rep:
    closable = True
    blockers: list = []
    unknowns: list = []

    def to_dict(self) -> dict:
        return {"m_says_done": True, "can_close": True, "can_close_reason": "",
                "closable": True, "machine_pass": True, "m_verdict": None,
                "overrode": [], "verdict_conflicts": [], "verdict_note": "",
                "status": "pass", "failed": [], "unknowns": [], "findings": [],
                "readings": {}, "summary": "stub"}

    def summary(self) -> str:
        return "stub"


class _Acc:
    def to_dict(self) -> dict:
        return {"passed": True, "criteria": {}, "details": {}, "failed": [],
                "auxiliary": {}, "auxiliary_note": "", "readings": {}}

    def summary(self) -> str:
        return "stub"


class _Ident:
    problem = ""
    code = ""
    sid = "probe"


def test_closing_carries_the_backfill_reading(tmp_path, monkeypatch):
    """`conductor.closing` 的调用链里带着补投读数（新增的只是 `readings` 的一格）。

    为什么要这一条：乙 不许动 `conductor.closing` 的 `side_effect`、也不许新增顶层键
    （两者都会改工具面 golden）。把读数放进 `readings` 是"不动声明"的那条路。
    """
    st = _ws(tmp_path)
    _conductor(st)
    recipient = _agent_row(st, role="B")
    # 一条 V 的时间窗（补投解析历史判定要用它；唯一才认）。
    _agent_row(st, role="V", parent=recipient, depth=3,
               started="2026-11-01T00:00:00+08:00", ended="2099-01-01T00:00:00+08:00")
    _put(st, SID)
    _verify(st, SID, v_task="t-v1", parent=recipient)     # 甲 已经投过 1 条
    _put(st, S.format_id(2))
    # 第二条只落台账、不投（模拟"改前判的"）。
    VR.record_verification(st.root, statement_id=S.format_id(2), proof_text=PROOF,
                           verdict={"verdict": "有毛病", "defect_step": 2,
                                    "findings": []},
                           verifier="agent-V", store=st, proof_no=1)

    monkeypatch.setattr(CL, "closing_session_identity", lambda root, sid: _Ident())
    monkeypatch.setattr(CL, "machine_feeders", lambda store, **kw: {})
    monkeypatch.setattr(CL, "check_closing", lambda *a, **k: _Rep())
    monkeypatch.setattr(CL, "tri_state_exit_code", lambda rep: 0)
    monkeypatch.setattr(RX, "check_review", lambda *a, **k: _Acc())

    got = CT.conductor_closing(st, session={"root": str(st.root), "sid": "probe"})
    assert got.ok, got.error
    readings = got.data["readings"]["v_receipts"]
    assert readings["checked"] is True, readings
    assert readings["receipts"] == 2, readings
    assert readings["dispatched"] == 2 and readings["not_dispatched"] == 0, readings
    # 新增的只有 `readings` 这一格：顶层键集合与改前一致（`returns=` 一个字没动）。
    new_top = [k for k in got.data
               if k not in ("m_says_done", "can_close", "can_close_reason", "closable",
                            "machine_pass", "m_verdict", "overrode", "verdict_conflicts",
                            "verdict_note", "verdict_written", "status", "failed",
                            "unknowns", "findings", "readings", "summary",
                            "review_acceptance")]
    assert new_top == [], new_top


# ------------------------------------------------------------------ 8/9 替人送审

def _put_authored(st: Store, sid: str, *, authors=None, created_by: str = "secretary-B"):
    """落一条带作者来源的命题（`proof_authors` 能落在行上，不需要动 schema）。"""
    row = {
        "stmt_id": sid, "origin": "own_result", "kind": "theorem",
        "label": f"探针命题 {sid}", "statement_full": FULL,
        "statement_text": FULL, "proof_text": PROOF,
        "evidence_kind": "heuristic", "status": "active",
        "quote_verified": None, "quote_reason": "夹具：自产命题",
        "created_at": TS, "created_by": created_by, "bits": {},
    }
    if authors is not None:
        row["proof_authors"] = list(authors)
    with st.tx("statements", actor="test") as tx:
        tx.upsert("statements", row)
    return row


def test_a_submitter_who_is_not_the_author_is_flagged_but_not_rerouted(tmp_path):
    """F 写、B 送 ⇒ 记 `submitter_is_not_author`（error），回执仍投送审者 B。

    业主 2026-11-01 定稿：「不存在 F 写证明 B 送审」⇒ 替人送审是缺陷，不是分流；
    回执的收件人仍是送审者（把回执改投作者就是把定义读成路由）。
    """
    st = _ws(tmp_path)
    _conductor(st)
    b_task = _agent_row(st, role="B")
    f_task = _agent_row(st, role="F")
    _put_authored(st, SID, authors=["F"], created_by="agent-F")
    _verify(st, SID, v_task="t-v1", parent=b_task, role="B")

    items = _items(st)
    assert len(items) == 1, [r.get("input_key") for r in items]
    assert str(items[0].get("parent_task_id")) == b_task, "回执被改投给了作者（F）"
    assert str(items[0].get("role")) == "B"
    assert "替人送审" in str(items[0].get("detail") or ""), items[0].get("detail")
    assert not [r for r in items if str(r.get("parent_task_id")) == f_task], (
        "F 的板上多了一条 ⇒ 这一条在按作者路由")

    got = VSP.receipt_digest(st.root, st, limit=100)
    assert got["submitter_is_not_author"] == 1, got["reason"]
    assert got["dispatched"] == 1 and got["not_dispatched"] == 0
    row = got["rows"][0]
    assert (row["submitter_role"], row["author"]) == ("B", "F"), row
    box = VRC.outbox_index(st.root)
    rec = next(iter(box.values()))
    assert rec["severity"] == "error" and rec["submitter_is_not_author"] is True, rec


def test_the_same_person_submitting_is_not_flagged(tmp_path):
    """F 写、F 送 ⇒ 那一条读数必须不出现（同一份判定，只换送审者）。"""
    st = _ws(tmp_path)
    _conductor(st)
    f_task = _agent_row(st, role="F")
    _put_authored(st, SID, authors=["F"], created_by="agent-F")
    _verify(st, SID, v_task="t-v1", parent=f_task, role="F")
    got = VSP.receipt_digest(st.root, st, limit=100)
    assert got["submitter_is_not_author"] == 0, got["reason"]
    assert got["rows"][0]["submitter_is_not_author"] is False
    assert str(_items(st)[0].get("parent_task_id")) == f_task
    assert "替人送审" not in str(_items(st)[0].get("detail") or "")


def test_an_unrecorded_author_is_visible_and_not_guessed(tmp_path):
    """作者没登记（`created_by` 是登记口）⇒ `author_not_recorded`，既不判违规也不改投。"""
    st = _ws(tmp_path)
    _conductor(st)
    b_task = _agent_row(st, role="B")
    _put_authored(st, SID, authors=None, created_by="secretary-B")
    _verify(st, SID, v_task="t-v1", parent=b_task, role="B")
    got = VSP.receipt_digest(st.root, st, limit=100)
    assert got["author_not_recorded"] == 1, got["reason"]
    assert got["submitter_is_not_author"] == 0, got["reason"]
    assert got["rows"][0]["submitter_is_not_author"] is None, got["rows"][0]
    assert str(_items(st)[0].get("parent_task_id")) == b_task


# ------------------------------------------------------------------ 10 B 收录不送审

def test_the_registration_path_never_calls_verify_proof():
    """B 的收录路径不许发起送审（业主 2026-11-01：B 只读签、不送审）。

    用 AST 判据：`secretary.record_statement` 与 `agent_b/register_statement.py` 里
    不许出现任何对 `verify_proof` 的调用（属性调用或裸名都算）。
    """
    import ast
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[1] / "src" / "agentflow"
    targets = [root / "secretary.py", root / "agent_b" / "register_statement.py"]
    hits: list[str] = []
    for path in targets:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                fn = node.func
                name = (fn.attr if isinstance(fn, ast.Attribute) else
                        fn.id if isinstance(fn, ast.Name) else "")
                if name == "verify_proof":
                    hits.append(f"{path.name}:{getattr(node, 'lineno', '?')}")
    assert hits == [], f"B 的收录路径在发起送审：{hits}"


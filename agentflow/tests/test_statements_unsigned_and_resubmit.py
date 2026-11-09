# -*- coding: utf-8 -*-
"""命题的「签收尾」：未签读数、放弃读数、重送义务（业主 2026-11-01 裁定）。

## 这一组守什么

业主逐字：

> 「每个命题和证明的产出最终必须以V签收尾，拿不到V签就得一直改，或者放弃原命题」

四条判据（本文件按块分节；每一节自己造现场、不依赖别的节）：

| # | 造什么 | 期望 |
|---|---|---|
| ① | 打回之后不重送 | `statements_unsigned` 非 0、逐条点名、门红（`machine_pass=false`、退出码 1） |
| ② | 重送并拿到干净「成立」 | 归 0（连续次数未满 3 也算"有签"：发签门槛不是"没签过"） |
| ③ | 明确放弃 | 进 `statements_abandoned`、不出现在 `statements_unsigned` |
| ④ | 同一份证明打回两次 | 板项只 1 条（幂等键 `v-resubmit@<命题>@<proof_sha>`，不带收件人后缀） |
| ⑤ | 收工时还悬着 | `machine_pass=false`、退出码 1（这是门的强度变更，不是读数变化） |

## 为什么夹具都走真写口

台账用 `verifications.record_verification`（唯一写口）、命题行用 `store.tx` 的
`tx.upsert`（与 `tests/test_v_receipt_delivery_does_not_wait_for_the_recipient.py` 同一
套夹具形状），板项由 `vreceipts.publish_row` 自己开 —— 手写台账 JSONL 会让判据
测到"我抄的那份形状"而不是"生产写出来的那份"。
"""
from __future__ import annotations

import json
import pathlib

import pytest
from agentflow import closing as CL
from agentflow import conductor as CND
from agentflow import secretary as SEC
from agentflow import statementabandon as SA
from agentflow import verifications as VR
from agentflow import vreceipts as VRC
from agentflow.agent_v import AgentV
from agentflow.store import Store
from agentflow.tools.conductor_tools import conductor_for, reset_cache

TS = "2026-11-01T20:00:00+08:00"
SID = "000001"
FULL = "设 f 在 [0,1] 上连续，则 f 一致连续。"
PROOF = "取 δ=ε，逐点验证：|x-y|<δ ⇒ |f(x)-f(y)|<ε。"
PROOF2 = "取 δ=ε/2，用紧性把逐点控制换成一致控制，再验证 |x-y|<δ ⇒ |f(x)-f(y)|<ε。"
REPLY_DEFECT = json.dumps({
    "verdict": "有毛病", "defect_step": 5, "why": "第 5 步没有依据",
    "findings": [{"level": "error", "step": 5, "kind": "无依据的步骤",
                  "detail": "第 5 步直接用了结论"}],
}, ensure_ascii=False)
REPLY_CLEAN = json.dumps({"verdict": "成立", "why": "逐步核过，没有缺陷"},
                         ensure_ascii=False)


class _Call:
    ok = True
    problem = ""
    detail = ""
    text = ""
    model = "fake"
    prompt_version = "t"
    prompt_sha256 = "0" * 64


class _Seam:
    """V 的那条缝：只喂审阅结论（不联网）。"""

    wired = True

    def __init__(self, *replies: str) -> None:
        self.replies = list(replies)

    def ask(self, prompt: str = "", **_kw) -> _Call:
        call = _Call()
        call.text = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        return call


# ------------------------------------------------------------------ 夹具

def _ws(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _put(st: Store, sid: str = SID, *, proof: str = PROOF, kind: str = "theorem",
         status: str = "active", quote_reason: str = "夹具：自产命题") -> dict:
    row = {
        "stmt_id": sid, "origin": "own_result", "kind": kind,
        "label": f"探针命题 {sid}", "statement_full": FULL,
        "statement_text": FULL, "proof_text": proof,
        "evidence_kind": "heuristic", "status": status,
        "quote_verified": None, "quote_reason": quote_reason,
        "created_at": TS, "created_by": "test", "bits": {},
    }
    with st.tx("statements", actor="test") as tx:
        tx.upsert("statements", row)
    return row


def _reproof(st: Store, sid: str = SID, *, proof: str = PROOF2) -> None:
    """把在册那一行的证明正文换成新的一版（F 改稿那条路的最小形态）。"""
    with st.tx("statements", actor="test") as tx:
        row = next(r for r in tx.rows("statements") if str(r.get("stmt_id")) == sid)
        row["proof_text"] = proof
        tx.upsert("statements", row)


def _verify(st: Store, sid: str = SID, *, proof: str = PROOF,
            verdict: str = "有毛病", fault: bool = True, step: int | None = 5) -> dict:
    """落一签（走真写口）：默认"有毛病 + 秘书判 fault"。"""
    findings = ([{"detail": "夹具：第 5 步的断言不成立", "level": "error", "step": step}]
                if verdict == "有毛病" else [])
    return VR.record_verification(
        st.root, statement_id=sid, proof_text=proof,
        verdict={"verdict": verdict, "defect_step": step, "findings": findings},
        secretary_judge={"axis": "fault" if fault else "clean", "checked": True,
                         "reason": "夹具：秘书的语义判定"},
        flip=False)


class _Rows:
    """只读台账的替身：只实现 `rows("statements")` 与 `root`。

    为什么需要它：`status="abandoned"` 的写入侧是块 4 那一笔（`Statement.validate`
    认这一档之后 `store.tx` 才写得进去）；而读侧今天就要能读盘上已经有的那一行
    （手改的行、schema 认这一档之前写下的行、以及将来别的写入路径）。所以这两个用例
    把行直接喂给读数，端到端的写路径由块 4 的用例守（同一份读数函数，两处都测）。
    """

    def __init__(self, root: pathlib.Path, rows: list[dict]) -> None:
        self.root = str(root)
        self._rows = rows

    def rows(self, table: str) -> list[dict]:
        if table != "statements":
            raise KeyError(table)
        return list(self._rows)


def _abandoned_row(*, status: str, quote_reason: str) -> dict:
    return {"stmt_id": SID, "origin": "own_result", "kind": "theorem",
            "label": f"探针命题 {SID}", "statement_full": FULL, "statement_text": FULL,
            "proof_text": PROOF, "evidence_kind": "heuristic", "status": status,
            "quote_verified": None, "quote_reason": quote_reason,
            "created_at": TS, "created_by": "test", "bits": {}}


def _unsigned(st: Store, *, now: str = "2026-11-01T21:00:00+08:00") -> dict:
    return CL.statements_unsigned_reading(st, now=now)


def _abandoned(st: Store) -> dict:
    return CL.statements_abandoned_reading(st)


# ------------------------------------------------------------------ ① 打回之后不重送

def test_a_fault_without_resubmission_is_unsigned_and_named(tmp_path):
    """① 打回之后不重送 ⇒ 读数非 0，逐条给 stmt_id / class / 最后 verdict / 悬了多久。"""
    st = _ws(tmp_path)
    _put(st)
    _verify(st)
    got = _unsigned(st)
    assert got["checked"] is True, got
    assert got["count"] == 1, got
    one = got["rows"][0]
    assert one["stmt_id"] == SID
    assert one["class"] == "fault_unrepaired", one
    assert one["last_verdict"] == "有毛病", one
    assert one["fault_at"], "打回时刻必须读得出来（'已悬多久'的锚点）"
    assert one["hung_seconds"] is not None and one["hung"], one
    assert one["proofs"][0]["class"] == "fault_unrepaired", one["proofs"]


def test_a_statement_never_sent_to_v_is_unsigned_not_hidden(tmp_path):
    """① 的另一半：一次都没送过 V 也算未签（"没送过的也算没签"，业主口径）。"""
    st = _ws(tmp_path)
    _put(st)
    got = _unsigned(st)
    assert got["count"] == 1, got
    assert got["rows"][0]["class"] == "never_submitted", got["rows"][0]


def test_the_count_is_red_before_any_sign_exists(tmp_path):
    """① 的反真空：三条都没签 ⇒ 3；不是"读不到"也不是 0。"""
    st = _ws(tmp_path)
    for i in range(3):
        _put(st, f"{i + 1:06d}")
    got = _unsigned(st)
    assert got["count"] == 3 and got["scanned"] == 3, got
    assert got["by_class"] == {"never_submitted": 3}, got["by_class"]


# ------------------------------------------------------------------ ② 重送并成立 ⇒ 归 0

def test_resubmitted_and_held_returns_to_zero(tmp_path):
    """② 打回 → 改稿 → 重送拿到干净「成立」⇒ 归 0（连续 3 次是发签门槛，不是"没签过"）。"""
    st = _ws(tmp_path)
    _put(st)
    _verify(st)
    assert _unsigned(st)["count"] == 1

    _reproof(st)
    row = _verify(st, proof=PROOF2, verdict="成立", fault=False, step=None)
    assert row.get("verification_id") == "v-000002", row
    got = _unsigned(st)
    assert got["count"] == 0, got
    assert got["rows"] == [], got["rows"]


def test_a_clean_sign_on_one_proof_does_not_cover_another(tmp_path):
    """② 的反向：干净「成立」只盖住它自己那一份证明，不借光。"""
    st = _ws(tmp_path)
    _put(st)
    row = {"stmt_id": SID, "origin": "own_result", "kind": "theorem",
           "label": "探针命题", "statement_full": FULL, "statement_text": FULL,
           "proof_text": PROOF, "evidence_kind": "heuristic", "status": "active",
           "quote_verified": None, "quote_reason": "夹具：自产命题",
           "created_at": TS, "created_by": "test", "bits": {},
           "proofs": [{"proof_no": 2, "proof_text": PROOF2}]}
    with st.tx("statements", actor="test") as tx:
        tx.upsert("statements", row)
    _verify(st, proof=PROOF, verdict="成立", fault=False, step=None)
    got = _unsigned(st)
    assert got["count"] == 1, got
    assert got["rows"][0]["proofs"][0]["proof_no"] == 2, got["rows"][0]["proofs"]


# ------------------------------------------------------------------ ③ 明确放弃

def test_an_explicit_abandonment_leaves_unsigned_and_enters_abandoned(tmp_path):
    """③ 明确放弃（带理由与时间）⇒ 进 abandoned、不出现在 unsigned。"""
    st = _ws(tmp_path)
    shim = _Rows(st.root, [_abandoned_row(
        status="abandoned",
        quote_reason=SA.abandon_marker(at="2026-11-01T20:30:00+08:00",
                                       reason="第 5 步补不出来，改不动了"))])
    assert _unsigned(shim)["count"] == 0, _unsigned(shim)
    got = _abandoned(shim)
    assert got["checked"] is True and got["count"] == 1, got
    assert got["rows"][0]["stmt_id"] == SID
    assert got["rows"][0]["at"] == "2026-11-01T20:30:00+08:00", got["rows"][0]
    assert "补不出来" in got["rows"][0]["reason"], got["rows"][0]


def test_abandoned_without_a_reason_is_still_unsigned(tmp_path):
    """③ 的反向：只写 status='abandoned' 而没有理由/时间 ⇒ 不算明确放弃，仍算未签。"""
    st = _ws(tmp_path)
    shim = _Rows(st.root, [_abandoned_row(status="abandoned", quote_reason="算了不做了")])
    got = _unsigned(shim)
    assert got["count"] == 1, got
    assert got["rows"][0]["class"] == "abandoned_without_reason", got["rows"][0]
    assert got["problems"], "读不出理由的那一行必须在 problems 里说一句"
    assert _abandoned(shim)["count"] == 0, _abandoned(shim)


# ------------------------------------------------------------------ 概念行与三态

def test_concept_rows_are_not_counted(tmp_path):
    """概念行不参与等级链（与既有读数同口径）：没有可签的证明。"""
    st = _ws(tmp_path)
    _put(st, "000009", kind="concept", proof="")
    _put(st, "000010")
    got = _unsigned(st)
    assert got["scanned"] == 1 and got["count"] == 1, got
    assert [r["stmt_id"] for r in got["rows"]] == ["000010"], got["rows"]


def test_unreadable_statements_are_not_zero(tmp_path):
    """三态：`statements` 读不出来 ⇒ `checked=False`（不是"一条都不欠签"）。"""
    got = CL.statements_unsigned_reading(None)
    assert got["checked"] is False and got["count"] == 0, got
    assert got["reason"], got
    assert CL.statements_abandoned_reading(None)["checked"] is False


# ------------------------------------------------------------------ 放弃标记的唯一实现

def test_the_abandon_marker_roundtrips_and_rejects_half_forms():
    """标记的写侧/读侧是同一份实现：理由与时间缺一即拒。"""
    text = SA.abandon_marker(at=TS, reason="改不动了")
    assert text.startswith(SA.ABANDON_MARKER), text
    got = SA.parse_abandon(text)
    assert got["checked"] is True and got["at"] == TS and got["reason"] == "改不动了", got
    # 理由里允许再出现 @（只切前两刀）
    assert SA.parse_abandon(SA.abandon_marker(at=TS, reason="a@b"))["reason"] == "a@b"
    for bad, why in (
        ("", "空"),
        ("abandoned", "没有第二刀"),
        (SA.ABANDON_MARKER + "昨天" + SA.ABANDON_SEP + "理由", "时间不是 ISO8601"),
        (SA.ABANDON_MARKER + TS + SA.ABANDON_SEP, "没有理由"),
    ):
        assert SA.parse_abandon(bad)["checked"] is False, (bad, why)
    with pytest.raises(ValueError):
        SA.abandon_marker(at=TS, reason="   ")
    with pytest.raises(ValueError):
        SA.abandon_marker(at="昨天", reason="有理由")


# ------------------------------------------------------------------ ②/④ 重送义务（板项层）
#
# 这一节走 V 的真入口（`AgentV.verify_proof`）：回执与义务都由 `vreceipts.publish_row`
# 在判定那一笔里开，判据测的是"生产写出来的那份"，不是手写行。

_SEQ = {"n": 0}


def _agent_row(st: Store, *, role: str = "F", parent: str = "t-root",
               depth: int = 2) -> str:
    """落一条代理行（`kind` 空）：收件人 / 送审者都用它。"""
    from agentflow.conductor import Conductor

    _SEQ["n"] += 1
    return Conductor._write_new_row(
        conductor_for(st), {
            "task_id": "", "role": role, "action": "", "called_by": "M",
            "parent_task_id": parent, "depth": depth,
            "input_key": f"@t:{role}:{_SEQ['n']}",
            "status": "done", "outcome": "ok", "refusal_reason": None,
            "instance": f"{role}#1", "detail": "夹具", "error": None,
            "started_at": TS, "ended_at": TS, "tokens": 0, "usd": 0.0,
            "artifacts": [], "inputs": [],
        }, note="probe:agent")


def _manuscript(st: Store, sid: str, proof: str) -> str:
    """把这一份证明栏写成 `reports/f-proof-<号>.md`（在册 V 审的载体）。"""
    rel = f"reports/f-proof-{sid}.md"
    target = pathlib.Path(str(st.root)) / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        f"# F 的证明手稿\n\n- 命题号：stmt:{sid}\n\n## 命题\n\n{FULL}\n\n"
        f"## 证明\n\n{proof}\n\n"
        "## 依赖\n\n| 引用（F 的原话） | 命题号（stmt:NNNNNN） | 用在哪一步 | 路径号（第几条证明） |\n"
        "|---|---|---|---|\n\n（这一份证明没有引用任何在册命题 —— 空表就是声明。）\n",
        encoding="utf-8")
    return rel


class _JudgeStub:
    """V 的秘书替身（p247：轴与洗稿都由秘书给；这一支量的是「待重送」板项）。

    夹具按 V 的判词给轴（有毛病 ⇒ fault）—— 这是替身自己的判定，不是生产代码按字面定轴。
    """

    def judge_v_reply(self, *, reply="", verdict="", defect_step=None, **_kw):
        bad = "有毛病" in str(verdict) or "有毛病" in str(reply)
        return {"checked": True, "axis": "fault" if bad else "clean",
                "decision": "有缺陷要指出" if bad else "没问题",
                "reason": "夹具：秘书语义判定", "basis": ["夹具"],
                "defect_step": (defect_step if isinstance(defect_step, int) else 5)
                if bad else None}

    def wash_v_reply(self, **_kw):
        return {"checked": True, "washed": True, "text": "第 5 步没有依据：补齐后重送 V。",
                "findings": [], "dropped": [], "refused": ""}

    def decide_sign_issuance(self, *, within_call=None, **_kw):
        ok = within_call is not None and int(within_call) >= int(VR.SIGN_STREAK_NEED)
        return {"checked": True, "issue": ok, "issued": False,
                "decision": SEC.SIGN_ISSUE if ok else SEC.SIGN_WITHHOLD,
                "streak": int(within_call or 0), "projected": int(within_call or 0),
                "need": int(VR.SIGN_STREAK_NEED), "streak_ok": ok,
                "reason": "夹具：够就签发", "basis": ["夹具"]}


def _verify_v(st: Store, sid: str, *, parent: str, proof: str = PROOF,
              reply: str = REPLY_DEFECT) -> dict:
    """走 V 的真入口（投递钩子在它里面）。

    2026-11-04（甲）：在册命题的 V 审也要手稿 —— 夹具把这一份证明栏写成一份
    `reports/f-proof-<号>.md` 的「## 证明」，V 从稿里取正文、签块也落回稿。
    """
    agent = AgentV(st, workspace_root=st.root, llm=_Seam(reply),
                   secretary=_JudgeStub())
    rel = _manuscript(st, sid, proof)
    with CND.calling_as("t-v1", "V", parent_task_id=parent, parent_role="F"):
        return agent.verify_proof(sid, proof_text=proof, proof_manuscript=rel)


def _resubmit_items(st: Store) -> list[dict]:
    return [dict(r) for r in st.rows("tasks")
            if str(r.get("input_key") or "").startswith(VRC.RESUBMIT_PREFIX)]


def test_a_fault_opens_one_resubmit_item_keyed_without_recipient(tmp_path):
    """④ 打回 ⇒ 开一条「待重送」板项；键是 `v-resubmit@<命题>@<sha>`，没有收件人后缀。"""
    st = _ws(tmp_path)
    conductor_for(st)
    parent = _agent_row(st)
    _put(st)
    got = _verify_v(st, SID, parent=parent)
    assert got.get("checked") is True, got
    items = _resubmit_items(st)
    assert len(items) == 1, [(r.get("input_key"), r.get("item_state")) for r in items]
    one = items[0]
    assert one["input_key"] == VRC.resubmit_key(f"{SID}#p1", VR.text_sha(PROOF)), one
    assert one["input_key"].endswith(VR.text_sha(PROOF)), "键尾必须是 sha，不是收件人"
    assert str(one.get("parent_task_id")) == parent, "负责人 = 那一次送审的送审者"
    assert str(one.get("expects")) == "work", "重送是要交付的活，不是'知道了'"
    assert str(one.get("kind")) == "notice"
    assert str(one.get("item_state")) == "queued", one
    assert "重送" in str(one.get("detail") or ""), one.get("detail")


def test_two_different_bodies_faulted_open_two_items_keyed_by_sha(tmp_path):
    """④ 两次打回、两份不同正文 ⇒ 各开一条（键 `v-resubmit@<命题>@<sha>` 里含 sha）。

    2026-11-06 裁定 3（打回即站住）之后，「同一份正文被打回两次」在入口上已不可能 ——
    同一 sha 的第二趟会被短接。所以这一条改成量键的语义：正文变了就是另一条义务。
    """
    st = _ws(tmp_path)
    conductor_for(st)
    parent = _agent_row(st)
    _put(st)
    _verify_v(st, SID, parent=parent)
    _reproof(st)   # 打回站住之后要再判必须改稿（同 sha 重掷不再重判）
    _verify_v(st, SID, parent=parent, proof=PROOF2)
    assert len(_resubmit_items(st)) == 2, [r.get("input_key") for r in _resubmit_items(st)]
    VRC.backfill(store=st)
    assert len(_resubmit_items(st)) == 2, [r.get("input_key") for r in _resubmit_items(st)]
    # 而回执那一侧是两条（两签两个 vid）—— 义务与回执不是同一条
    receipts = [r for r in st.rows("tasks")
                if str(r.get("input_key") or "").startswith("v-verdict@")]
    assert len(receipts) == 2, [r.get("input_key") for r in receipts]


def test_a_clean_hold_closes_the_resubmit_item_but_an_ack_does_not(tmp_path):
    """②/④ 关闭条件 = 更新的干净「成立」行；ack 关不掉它（这是业主裁定的关闭条件）。"""
    st = _ws(tmp_path)
    conductor_for(st)
    parent = _agent_row(st)
    _put(st)
    _verify_v(st, SID, parent=parent)
    item = _resubmit_items(st)[0]
    item_id = str(item["task_id"])

    cond = conductor_for(st)
    acked = cond.ack_items([item_id], by_task_id=parent)
    assert not acked.get("acked"), acked
    assert str(_resubmit_items(st)[0]["item_state"]) != "done", "ack 不许关掉重送义务"

    _reproof(st)
    got = _verify_v(st, SID, parent=parent, proof=PROOF2, reply=REPLY_CLEAN)
    assert got.get("checked") is True, got
    closed = [r for r in st.rows("tasks") if str(r.get("task_id")) == item_id][0]
    assert str(closed.get("item_state")) == "done", closed
    assert str(closed.get("item_close")) == "completed", closed


def test_an_unowned_fault_opens_nothing_and_reads_as_owner_unknown(tmp_path):
    """I2 的第二半：读不到送审者 ⇒ 记 unknown、不开项（不拿"谁醒着"当负责人）。"""
    st = _ws(tmp_path)
    conductor_for(st)
    _put(st)
    # 不在任何召唤里 ⇒ current_parent 为空 ⇒ undelivered
    agent = AgentV(st, workspace_root=st.root, llm=_Seam(REPLY_DEFECT),
                   secretary=_JudgeStub())
    got = agent.verify_proof(SID, proof_text=PROOF,
                             proof_manuscript=_manuscript(st, SID, PROOF))
    assert got.get("checked") is True, got
    assert _resubmit_items(st) == [], [r.get("input_key") for r in _resubmit_items(st)]
    one = _unsigned(st)["rows"][0]
    assert one["owner_known"] is False and one["owner"] == "", one


def test_abandonment_expires_the_open_resubmit_item(tmp_path):
    """③/④ 放弃原命题 ⇒ 那条义务同时作废（否则销号闸会被它反锁住）。"""
    st = _ws(tmp_path)
    conductor_for(st)
    parent = _agent_row(st)
    _put(st)
    _verify_v(st, SID, parent=parent)
    item = _resubmit_items(st)[0]
    got = VRC.close_resubmits_for(st, statement_id=SID, why="命题被明确放弃")
    assert got["checked"] is True and got["closed"], got
    closed = [r for r in st.rows("tasks") if str(r.get("task_id")) == item["task_id"]][0]
    assert str(closed.get("item_state")) == "done", closed
    assert str(closed.get("item_close")) == "expired", closed
    assert _resubmit_items(st) == [] or all(
        str(r.get("item_state")) == "done" for r in _resubmit_items(st)), _resubmit_items(st)


# ------------------------------------------------------------------ ⑤ 收工门（强度变更）

def _closing(st: Store):
    """只跑读数那一层（`checks=()`）：这一笔要测的是门对"悬着"的反应。"""
    return CL.check_closing(st, checks=(), goal="测门", goal_met=True, basis="夹具")


def test_the_gate_blocks_while_a_statement_is_unsigned(tmp_path):
    """⑤ 收工时还悬着 ⇒ blocker + machine_pass=false + 退出码 1（门强度变更）。"""
    st = _ws(tmp_path)
    _put(st)
    _verify(st)
    rep = _closing(st)
    assert rep.machine_pass is False, rep.to_dict()
    assert CL.tri_state_exit_code(rep) == 1, rep.to_dict()
    blockers = [f for f in rep.blockers if f.check == "statements_unsigned"]
    assert len(blockers) == 1, [f.to_dict() for f in rep.findings]
    assert blockers[0].code == "statements_unsigned_without_v_or_abandon"
    assert SID in blockers[0].detail, blockers[0].detail
    assert "已悬" in blockers[0].detail and "负责人" in blockers[0].detail, blockers[0].detail
    assert "业主 2026-11-01" in blockers[0].detail, "拦门读数要点名裁定"


def test_the_gate_names_at_most_six_and_counts_the_rest(tmp_path):
    """⑤ 逐条点名只到前 6 条，其余折成「共 N 条」（不许把 detail 塞爆）。"""
    st = _ws(tmp_path)
    for i in range(8):
        _put(st, f"{i + 1:06d}")
    rep = _closing(st)
    detail = [f.detail for f in rep.blockers if f.check == "statements_unsigned"][0]
    assert "8 条命题" in detail, detail
    assert detail.count("，已悬") == 6, detail
    assert "…" in detail, detail


def test_the_gate_is_green_when_every_statement_is_signed_or_abandoned(tmp_path):
    """⑤ 的正控：重送并成立 ⇒ 门绿（0 条未签）；没有 statements ⇒ 也绿。"""
    st = _ws(tmp_path)
    empty = _closing(st)
    assert empty.blockers == [] and empty.machine_pass is True, empty.to_dict()
    _put(st)
    _verify(st)
    _reproof(st)
    _verify(st, proof=PROOF2, verdict="成立", fault=False, step=None)
    rep = _closing(st)
    assert rep.blockers == [], [f.to_dict() for f in rep.findings]
    assert rep.machine_pass is True, rep.to_dict()
    assert CL.tri_state_exit_code(rep) == 0, rep.to_dict()


# ------------------------------------------------------------------ ③ 放弃出口（写侧）
#
# 这一节测的是 `statementabandon.apply_abandonment`（写侧唯一实现）：状态 + 理由 + 时间
# 一起落盘，名下开着的重送义务一并作废。第二半是"经 `table.update` 走到这里"
# （`Secretary.record_statement` 的 abandoned 分支），端到端那一条在下面。

def test_apply_abandonment_writes_status_and_marker(tmp_path):
    """③ 写侧：一条在册命题 ⇒ status=abandoned + 可解析标记；读数从 unsigned 挪到 abandoned。"""
    st = _ws(tmp_path)
    _put(st)
    _verify(st)
    assert _unsigned(st)["count"] == 1
    got = SA.apply_abandonment(st, statement_id=SID, reason="第 5 步补不出来",
                               at="2026-11-01T21:10:00+08:00",
                               abandon_kind="math_error",
                               abandon_basis="第 5 步直接用了结论：那一步没有依据",
                               defect_ref=f"verifications/{SID}.jsonl#v-000001")
    assert got["checked"] is True and got["abandoned"] is True, got
    row = next(dict(r) for r in st.rows("statements") if r["stmt_id"] == SID)
    assert row["status"] == "abandoned", row
    parsed = SA.parse_abandon(row["quote_reason"])
    assert parsed["checked"] and parsed["at"] == "2026-11-01T21:10:00+08:00", parsed
    # 2026-11-07：`@` 之后是结构化理由（两档形状），理由正文在 `abandon_basis` 里
    assert "补不出来" in parsed["reason"] or "第 5 步直接用了结论" in parsed["reason"], parsed
    structured = SA.parse_abandon_reason(row["quote_reason"])
    assert structured["complete"] is True and structured["abandon_kind"] == "math_error", \
        structured
    assert _unsigned(st)["count"] == 0, _unsigned(st)
    abandoned = _abandoned(st)
    assert abandoned["count"] == 1 and abandoned["rows"][0]["stmt_id"] == SID, abandoned
    rep = _closing(st)
    assert [f for f in rep.blockers if f.check == "statements_unsigned"] == [], rep.to_dict()


def test_apply_abandonment_is_idempotent(tmp_path):
    """③ 同一份放弃重放 ⇒ 幂等（不改任何格、不报错）。"""
    st = _ws(tmp_path)
    _put(st)
    _verify(st)
    args = dict(abandon_kind="math_error",
                abandon_basis="第 5 步直接用了结论",
                defect_ref=f"verifications/{SID}.jsonl#v-000001")
    first = SA.apply_abandonment(st, statement_id=SID, reason="改不动", at=TS, **args)
    second = SA.apply_abandonment(st, statement_id=SID, reason="改不动", at=TS, **args)
    assert first["checked"] and second["checked"], (first, second)
    assert second["already"] is True and second["changes"] == [], second


def test_apply_abandonment_refuses_without_a_reason_or_an_id(tmp_path):
    """③ 没有理由 / 没有命题号 / 不在册 ⇒ 受控拒绝，盘上一个字节都不改。

    2026-11-07 改：命题行"只给一段散文"这一档现在受控拒在换号理由那一关
    （`abandon_reason_missing`，业主裁定要 `abandon_kind` + `abandon_basis`）；
    `abandon_marker_invalid` 这一档仍然对不是命题的行（概念行不过那道闸）生效。
    """
    st = _ws(tmp_path)
    _put(st)
    _verify(st)
    blank = SA.apply_abandonment(st, statement_id=SID, reason="   ")
    assert blank["checked"] is False and blank["refused"] == "abandon_reason_missing", blank
    _put(st, "000002", kind="concept")
    concept_blank = SA.apply_abandonment(st, statement_id="000002", reason="   ")
    assert concept_blank["checked"] is False, concept_blank
    assert concept_blank["refused"] == "abandon_marker_invalid", concept_blank
    no_id = SA.apply_abandonment(st, statement_id="", reason="有理由")
    assert no_id["checked"] is False and no_id["refused"] == "abandon_missing_id", no_id
    unknown = SA.apply_abandonment(st, statement_id="999999", reason="有理由")
    assert unknown["checked"] is False, unknown
    assert unknown["refused"] == "abandon_unknown_statement", unknown
    assert next(dict(r) for r in st.rows("statements"))["status"] == "active"


def test_apply_abandonment_expires_the_open_resubmit_item(tmp_path):
    """③ 放弃 ⇒ 名下开着的重送义务同时作废（否则销号闸被反锁）。"""
    st = _ws(tmp_path)
    conductor_for(st)
    parent = _agent_row(st)
    _put(st)
    _verify_v(st, SID, parent=parent)
    item = _resubmit_items(st)[0]
    got = SA.apply_abandonment(st, statement_id=SID, reason="改不动了", at=TS,
                               abandon_kind="math_error",
                               abandon_basis="第 5 步直接用了结论：那一步没有依据",
                               defect_ref=f"verifications/{SID}.jsonl#v-000001")
    assert got["checked"] is True, got
    assert got["resubmits"]["checked"] is True and got["resubmits"]["closed"], got["resubmits"]
    closed = [r for r in st.rows("tasks") if str(r.get("task_id")) == item["task_id"]][0]
    assert str(closed.get("item_state")) == "done", closed
    assert str(closed.get("item_close")) == "expired", closed


def test_schema_requires_a_parseable_marker_for_abandoned():
    """③ 数据面：status=abandoned 而标记不可解析 ⇒ `Statement.validate` 当场拒。"""
    from agentflow import schema as S

    base = dict(stmt_id="0009", origin="own_result", kind="theorem",
                statement_full="若 A 则 B", proof_text="证明：略。",
                status="abandoned")
    with pytest.raises(ValueError):
        S.Statement(**{**base, "quote_reason": "算了不做了"}).validate()
    ok = S.Statement(**{**base, "quote_reason": SA.abandon_marker(at=TS, reason="改不动了")})
    ok.validate()
    assert ok.status == "abandoned"


# ------------------------------------------------------------------ ③ 端到端：table.update

def _table_registry(st: Store):
    from agentflow.tools import table_tools
    from agentflow.tools.base import ToolRegistry

    reg = ToolRegistry(name="tables")
    reg.bound_role = "B"
    table_tools.register(reg, store=st)
    return reg


def test_the_table_update_route_abandons_a_statement_and_the_closing_reconciles_it(tmp_path):
    """③ 端到端（业主验收口径）：`table.update(status=abandoned, quote_reason=标记)`。

    走的是生产的通用写口（`table.update` → `Secretary.amend_statement_meta`，业主
    2026-11-01 加的非正文三格就地写口），不是直接调内部函数。

    ## 2026-11-02 改（①：`apply_abandonment` 没有生产调用点）

    改前这一条把"重送义务什么时候作废"押在收工前那一趟对账上（`vreceipts.
    reconcile_resubmits`，backfill 里调）—— 也就是说真机上"放弃命题"那一笔写完之后，
    板上那条 `v-resubmit@` 还开着，直到有人跑收工对账才关得掉（83 的真实读数：4 条
    abandoned 全走 `table.update`，而那一趟不认识板项）。现在作废就发生在那一笔写口里
    （`table_tools._route_to_secretary` 在就地写成功之后调 `apply_abandonment`），
    所以下面断言的是"写完就 done/expired"，而对账那一趟此时是「幂等重放」（零写入）：
    改前它非空（`expired` 里有这一条），改后它必须空 —— 这不是放宽，是同一件事挪到了
    写口上（判据见 `test_table_update_closes_the_open_resubmit_item_and_leaves_no_open_work`）。
    """
    st = _ws(tmp_path)
    conductor_for(st)
    parent = _agent_row(st)
    _put(st)
    _verify_v(st, SID, parent=parent)
    item = _resubmit_items(st)[0]
    reg = _table_registry(st)
    with CND.calling_as("t-b1", "B"):
        res = reg.call("table.update", table="statements", id=SID,
                       patch={"status": "abandoned"},
                       abandon_kind="math_error",
                       abandon_basis="第 5 步直接用了结论：那一步没有依据",
                       defect_ref=f"verifications/{SID}.jsonl#v-000001")
    assert res.ok, (res.error, getattr(res, "data", None) or getattr(res, "meta", None))
    row = next(dict(r) for r in st.rows("statements") if r["stmt_id"] == SID)
    assert row["status"] == "abandoned", row
    parsed = SA.parse_abandon(row["quote_reason"])
    assert parsed["checked"], parsed
    assert SA.parse_abandon_reason(row["quote_reason"])["abandon_kind"] == "math_error", row
    assert _unsigned(st)["count"] == 0, _unsigned(st)
    assert _abandoned(st)["count"] == 1, _abandoned(st)

    # 写口自己关：不等 backfill。
    closed = [r for r in st.rows("tasks") if str(r.get("task_id")) == item["task_id"]][0]
    assert str(closed.get("item_state")) == "done", closed
    assert str(closed.get("item_close")) == "expired", closed

    got = VRC.backfill(store=st)
    rec = got["resubmit_reconcile"]
    assert rec["checked"] is True, rec
    assert item["task_id"] not in rec["expired"], rec
    assert item["task_id"] not in rec["closed"], rec
    closed = [r for r in st.rows("tasks") if str(r.get("task_id")) == item["task_id"]][0]
    assert str(closed.get("item_state")) == "done", closed
    assert str(closed.get("item_close")) == "expired", closed


# ------------------------------------------------------------------ ① 放弃 ⇒ 板项当场作废
#
# 真机代价（83 的读数）：`statementabandon.apply_abandonment` 只有测试在调，走
# `table.update(status=abandoned)` 那条正路不会 close 该命题名下的 `v-resubmit@` 项 ⇒
# 板上留下一条永远关不掉的 work 项（`retire_integrity` 把"名下还有未消的板项"算成
# 不干净，于是"放弃"这条出口被反锁死）。这一节把"谁在什么时候关"钉在写口上。

def _open_work_for(st: Store, sid: str) -> list[dict]:
    """该命题名下还开着的重送 work 项（`expects=work` 且 `item_state != done`）。"""
    want = f"{VRC.RESUBMIT_PREFIX}{sid}@"
    return [dict(r) for r in st.rows("tasks")
            if str(r.get("input_key") or "").startswith(want)
            and str(r.get("expects") or "") == "work"
            and str(r.get("item_state") or "") != "done"]


def test_table_update_closes_the_open_resubmit_item_and_leaves_no_open_work(tmp_path):
    """① 打回 → 开 v-resubmit 项 → 放弃命题 ⇒ 该项 done/expired，板上没有它的 open work。"""
    st = _ws(tmp_path)
    conductor_for(st)
    parent = _agent_row(st)
    _put(st)
    _verify_v(st, SID, parent=parent)
    item = _resubmit_items(st)[0]
    assert _open_work_for(st, SID), "夹具没造出重送项 —— 判据会变成恒绿"

    reg = _table_registry(st)
    with CND.calling_as("t-b1", "B"):
        res = reg.call("table.update", table="statements", id=SID,
                       patch={"status": "abandoned"},
                       abandon_kind="math_error",
                       abandon_basis="第 5 步直接用了结论：那一步没有依据",
                       defect_ref=f"verifications/{SID}.jsonl#v-000001")
    assert res.ok, (res.error, getattr(res, "data", None) or getattr(res, "meta", None))

    closed = next(dict(r) for r in st.rows("tasks")
                  if str(r.get("task_id")) == item["task_id"])
    assert str(closed.get("item_state")) == "done", closed
    assert str(closed.get("item_close")) == "expired", closed
    assert _open_work_for(st, SID) == [], _open_work_for(st, SID)
    # 读数透出来（模型 / 审计看得到"放弃把哪条义务作废了"）
    payload = getattr(res, "data", None) or {}
    got = payload.get("abandon") or {}
    assert got.get("checked") is True, payload
    assert item["task_id"] in list((got.get("resubmits") or {}).get("closed") or []), got


def test_a_fault_that_is_not_abandoned_keeps_the_resubmit_item_open(tmp_path):
    """① 反真空：只打回、不放弃 ⇒ 该项仍 open（不能被无条件关掉）。"""
    st = _ws(tmp_path)
    conductor_for(st)
    parent = _agent_row(st)
    _put(st)
    _verify_v(st, SID, parent=parent)
    item = _resubmit_items(st)[0]
    # 只改一句无害的非正文格（不碰 status / quote_reason）⇒ 义务一个字都不该动。
    reg = _table_registry(st)
    with CND.calling_as("t-b1", "B"):
        res = reg.call("table.update", table="statements", id=SID,
                       patch={"kind": "lemma"})
    assert res.ok, (res.error, getattr(res, "data", None) or getattr(res, "meta", None))
    still = next(dict(r) for r in st.rows("tasks")
                 if str(r.get("task_id")) == item["task_id"])
    assert str(still.get("item_state")) != "done", still
    assert [r["task_id"] for r in _open_work_for(st, SID)] == [item["task_id"]], \
        _open_work_for(st, SID)


def test_the_table_update_route_refuses_an_abandonment_without_a_marker(tmp_path):
    """③ 反向：只写 status='abandoned' 而不带可解析标记 ⇒ 通用写口当场拒，一个字节不改。"""
    st = _ws(tmp_path)
    conductor_for(st)
    parent = _agent_row(st)
    _put(st)
    _verify_v(st, SID, parent=parent)
    item = _resubmit_items(st)[0]
    reg = _table_registry(st)
    with CND.calling_as("t-b1", "B"):
        res = reg.call("table.update", table="statements", id=SID,
                       patch={"status": "abandoned", "quote_reason": "算了不做了"})
    assert res.ok is False, res
    row = next(dict(r) for r in st.rows("statements") if r["stmt_id"] == SID)
    assert row["status"] == "active", row
    assert _unsigned(st)["count"] == 1, _unsigned(st)
    still_open = [r for r in st.rows("tasks") if str(r.get("task_id")) == item["task_id"]][0]
    assert str(still_open.get("item_state")) != "done", still_open

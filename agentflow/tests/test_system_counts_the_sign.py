# -*- coding: utf-8 -*-
"""判据：系统计数落签（业主 2026-11-17 裁定）。

## 业主逐字

    「三次连续过审才能签…不存在 V 秘书判一次审过后直接落签，不存在 V 秘书
      自己拿着工具落签（是系统计数落签）」

## 这一份量什么

"数"这件事不再由 V 那一趟的循环变量（`pass_no` / `len(judged)`）或台账尾数决定，
而是由框架的一层（`agentflow.sign_counting`）从盘上那本台账现数：同一份正文、
同一个 `review_call`（一次送审）内 `review_pass=1..need` 连续 clean 的轮数。

| 编号 | 判据 | 本文件的测试 |
|---|---|---|
| a | 同一趟三轮 clean（`review_pass=1,2,3`）⇒ 计数 3 ⇒ 发签；签文件三票各带 `review_call` / `review_pass` / `object_sha256` | `test_a_*` / `test_a2_*` |
| b | 旧组两轮 clean + 新 `review_call` 一轮 clean ⇒ 不累计（只算最新那一组 = 1）⇒ 不发签 | `test_b_*` |
| c | 同一 `review_call` 内同号重放 clean ⇒ 计数不增加 | `test_c_*` |
| d | fault 出现 ⇒ 该组终止；下一组从 1 重新数 | `test_d_*` |
| e | 反真空：把"系统计数"打桩成恒 `>= need` ⇒ b / c 必须变红（发签了） | `test_e_*` |
| f | 老行（无 `review_call`）⇒ 读数里标 legacy（签文件写 `legacy=true`），且不进新组计数 | `test_f_*` |
| ④ | "V 少回一轮 / 多回一轮都不改变发签与否" | `test_rounds_*` |
| ① | 每行 `at` 是那一轮判词的时刻（不是三行一起写下的那一刻） | `test_at_*` |

判据 a 的口径说明（口径冲突的处置）：任务书 a 那一行写的是"三轮 clean（三个不同
`review_call`）"，而 b 写的是"只算最新那一组、不许跨 `review_call` 累计" —— 两者
字面上不能同时成立。产品既有定稿（2026-11-02 业主：「一次送审 = 同一次调用内连判
三轮」「不允许跨两次送审累计成功数」）与 VSEM1 §2.4 的还原都是"同一 `review_call`
内 `review_pass=1..3`"。所以 a 按"同一趟三轮"钉；"三个不同 `review_call` 各一轮
clean"按 b 钉（不累计、不发签）。
"""
from __future__ import annotations

import json
import pathlib

import pytest

from agentflow import sign_counting as SC
from agentflow import verifications as VR
from agentflow import vsigns as VS
from agentflow import secretary as SEC
from agentflow.agent_v import core as V_CORE

from test_sign_reading import CALL, PROOF, TS, _manuscript, _row, _write_ledger, _write_ws
from test_v_reviews_three_times_before_signing import CLEAN_REPLY
from test_v_unregistered_manuscript_review import (
    REL,
    _pending_rows,
    _sign_files,
    _submitted_by_f,
    _v,
    _ws as _vws,
)

SID = "000007"


# ---------------------------------------------------------------- 夹具

def _rows(sid: str, sha: str, spec: list[tuple[str, int, str]]) -> list[dict]:
    """按 `(review_call, review_pass, axis)` 造台账行（`axis=""` = 没查成）。"""
    out: list[dict] = []
    for i, (call, pass_no, axis) in enumerate(spec, 1):
        row = _row(sid, sha, pass_no=pass_no, axis=axis or "clean", call=call,
                   vid=f"v-{i:06d}")
        if not axis:
            row["secretary_judge"] = {"checked": False, "axis": ""}
        out.append(row)
    return out


def _work(root: pathlib.Path, sids: list[str] = (SID,)) -> tuple[str, str]:
    """一个带命题行 + 手稿的工作区 ⇒ `(rel, sha)`。"""
    _write_ws(root, list(sids))
    rel, _text, sha = _manuscript(root, sids[0])
    return rel, sha


def _issue(root: pathlib.Path, rel: str, sha: str, rows: list[dict], *,
           sid: str = SID) -> dict:
    need = int(VR.SIGN_STREAK_NEED)
    passes = []
    for r in rows[-need:]:
        one = {"verification_id": str(r["verification_id"]), "at": str(r["at"]),
               "proof_sha256": sha}
        if r.get("review_call"):
            one["review_call"] = str(r["review_call"])
        if isinstance(r.get("review_pass"), int):
            one["review_pass"] = int(r["review_pass"])
        passes.append(one)
    return VS.issue(root, artifact_sha=sha, streak=need, need=need,
                    artifact_path=rel,
                    ledger=f"verifications/{sid}.jsonl#{rows[-1]['verification_id']}",
                    statement_id=sid, proof_no=1, passes=passes, at=TS,
                    by="secretary:B")


def _sign_doc(root: pathlib.Path, sha: str) -> dict:
    return json.loads(VS.sign_path(root, sha).read_text(encoding="utf-8"))


# ============================================================ a：同一趟三轮 ⇒ 发签

def test_a_three_clean_rounds_in_one_call_count_to_three_and_sign(tmp_path):
    """a（计数层）：同一 `review_call` 内 `review_pass=1,2,3` 都 clean ⇒ 3/3。"""
    sha = "a" * 64
    rows = _rows(SID, sha, [(CALL, 1, "clean"), (CALL, 2, "clean"), (CALL, 3, "clean")])
    got = SC.count_rows(rows, review_call=CALL, proof_sha256=sha, need=3)
    assert got["checked"] is True, got
    assert (got["count"], got["ok"], got["counted_by"]) == (3, True, SC.COUNTED_BY), got
    assert [p["review_pass"] for p in got["passes"]] == [1, 2, 3], got["passes"]
    assert "系统计数" in got["why"], got["why"]


def test_a2_the_sign_file_carries_the_three_identities(tmp_path):
    """a（写签）：发出来的签，三票各带 `review_call` / `review_pass` / `object_sha256`。"""
    root = tmp_path / "ws"
    rel, sha = _work(root)
    rows = _rows(SID, sha, [(CALL, 1, "clean"), (CALL, 2, "clean"), (CALL, 3, "clean")])
    for i, row in enumerate(rows, 1):
        row["object_sha256"] = "b" * 64
        row["at"] = f"{TS[:-6]}{i}+08:00"
    _write_ledger(root, SID, rows)
    wrote = _issue(root, rel, sha, rows)
    assert wrote["written"] is True, wrote
    assert (wrote["counted_by"], wrote["count"], wrote["legacy"]) == (
        SC.COUNTED_BY, 3, False), wrote
    doc = _sign_doc(root, sha)
    assert (doc["counted_by"], doc["count"], doc["legacy"]) == (SC.COUNTED_BY, 3, False), doc
    passes = doc["passes"]
    assert [p["review_pass"] for p in passes] == [1, 2, 3], passes
    assert {p["review_call"] for p in passes} == {CALL}, passes
    assert [p["object_sha256"] for p in passes] == ["b" * 64] * 3, passes
    assert [p["at"] for p in passes] == [r["at"] for r in rows], passes


def test_a3_the_unregistered_main_path_puts_the_three_identities_in_the_sign(tmp_path):
    """a（真路）：未在册三转 clean ⇒ 签文件三票带身份，pending 三行各带自己的身份。"""
    st = _vws(tmp_path)
    v, seam = _v(st, [CLEAN_REPLY])
    with _submitted_by_f():
        got = v.verify_proof(proof_manuscript=REL)
    assert got.get("kind") == "proof_unregistered_signed", got
    assert seam.asked() == 3, seam.asked()

    files = _sign_files(st)
    assert len(files) == 1, files
    doc = json.loads(files[0].read_text(encoding="utf-8"))
    passes = doc["passes"]
    assert len(passes) == 3, passes
    calls = {str(p.get("review_call") or "") for p in passes}
    assert len(calls) == 1 and "" not in calls, passes
    assert [int(p.get("review_pass") or 0) for p in passes] == [1, 2, 3], passes
    assert all(len(str(p.get("object_sha256") or "")) == 64 for p in passes), passes
    assert len({str(p.get("object_sha256")) for p in passes}) == 1, passes
    assert (doc["counted_by"], doc["count"]) == (SC.COUNTED_BY, 3), doc

    # 盘上那三行与签里的三票同源（同一个 review_call / 同一个对象 sha）。
    rows = _pending_rows(st)
    assert {str(r.get("review_call") or "") for r in rows} == calls, rows
    assert {str(r.get("object_sha256") or "") for r in rows} == {
        str(p.get("object_sha256") or "") for p in passes}, rows


# ============================================================ b：跨组不累计

def test_b_two_old_rounds_plus_one_new_call_is_not_three(tmp_path):
    """b：旧组 2 轮 clean + 新 `review_call` 1 轮 clean ⇒ 只算最新那一组 = 1 ⇒ 不发签。"""
    sha = "c" * 64
    old = "call-old"
    new = "call-new"
    rows = _rows(SID, sha, [(old, 1, "clean"), (old, 2, "clean"), (new, 1, "clean")])
    counted = SC.count_rows(rows, review_call=new, proof_sha256=sha, need=3)
    assert (counted["count"], counted["ok"]) == (1, False), counted
    assert counted["legacy_rows"] == 0, counted

    root = tmp_path / "ws"
    rel, sha_real = _work(root)
    rows = _rows(SID, sha_real, [(old, 1, "clean"), (old, 2, "clean"), (new, 1, "clean")])
    _write_ledger(root, SID, rows)
    wrote = _issue(root, rel, sha_real, rows)
    assert wrote["written"] is False, wrote
    assert wrote["code"] == VS.SIGN_COUNT_SHORT, wrote
    assert not VS.sign_path(root, sha_real).exists(), "跨组凑数却写出了签文件"
    # 反向（反真空的一半）：同一批行里新组自己攒满 3 轮 ⇒ 才发签。
    three = _rows(SID, sha_real, [(new, 1, "clean"), (new, 2, "clean"), (new, 3, "clean")])
    _write_ledger(root, SID, three)
    assert _issue(root, rel, sha_real, three)["written"] is True


# ============================================================ c：同号重放不增加

def test_c_replaying_the_same_pass_does_not_add_a_vote(tmp_path):
    """c：同一 `review_call` 内同号重放 clean ⇒ 计数不增加（重放不是新的一轮）。"""
    sha = "d" * 64
    rows = _rows(SID, sha, [(CALL, 1, "clean"), (CALL, 2, "clean"),
                            (CALL, 3, "clean"), (CALL, 3, "clean")])
    got = SC.count_rows(rows, review_call=CALL, proof_sha256=sha, need=3)
    assert (got["count"], got["ok"], got["replayed"]) == (3, True, 1), got
    # 只重放到第 2 轮 ⇒ 不是三轮（计数不因"多回一次"而够）。
    short = _rows(SID, sha, [(CALL, 1, "clean"), (CALL, 2, "clean"), (CALL, 2, "clean")])
    counted = SC.count_rows(short, review_call=CALL, proof_sha256=sha, need=3)
    assert (counted["count"], counted["ok"], counted["replayed"]) == (2, False, 1), counted

    root = tmp_path / "ws"
    rel, sha_real = _work(root)
    three = _rows(SID, sha_real, [(CALL, 1, "clean"), (CALL, 2, "clean"),
                                  (CALL, 3, "clean"), (CALL, 3, "clean")])
    _write_ledger(root, SID, three)
    wrote = _issue(root, rel, sha_real, three)
    assert wrote["written"] is True, wrote
    # 签里只写三轮（重放那一行不构成第四票，也不占掉第 3 轮）。
    assert [int(p["review_pass"]) for p in _sign_doc(root, sha_real)["passes"]] == [1, 2, 3]


# ============================================================ d：fault 终止这一组

def test_d_fault_ends_the_group_and_the_next_group_starts_at_one(tmp_path):
    """d：fault ⇒ 这一组终止；下一组从 1 重新数（不借上一组的 clean）。"""
    sha = "e" * 64
    a, b = "call-a", "call-b"
    rows = _rows(SID, sha, [(a, 1, "clean"), (a, 2, "fault"), (b, 1, "clean")])
    first = SC.count_rows(rows, review_call=a, proof_sha256=sha, need=3)
    assert (first["count"], first["ok"], first["terminated"]) == (1, False, "fault"), first
    second = SC.count_rows(rows, review_call=b, proof_sha256=sha, need=3)
    assert (second["count"], second["ok"], second["terminated"]) == (
        1, False, "missing_pass"), second

    root = tmp_path / "ws"
    rel, sha_real = _work(root)
    real = _rows(SID, sha_real, [(a, 1, "clean"), (a, 2, "fault"), (b, 1, "clean")])
    _write_ledger(root, SID, real)
    wrote = _issue(root, rel, sha_real, real)
    assert wrote["written"] is False and wrote["code"] == VS.SIGN_COUNT_SHORT, wrote


# ============================================================ e：反真空（闸有牙）

def test_e_stubbing_the_count_to_always_ok_opens_b_and_c(tmp_path, monkeypatch):
    """e：把系统计数打桩成恒 `>= need` ⇒ b / c 的"不发签"当场变红（签被写出来）。

    这一条证明 b / c 的绿是这道闸给的，不是别的什么顺手挡住了。
    """
    monkeypatch.setattr(SC, "count_ledger_file",
                        lambda path, *, anchor_vid, proof_sha256, need: {
                            "checked": True, "ok": True, "count": int(need),
                            "need": int(need), "passes": [], "legacy": True,
                            "counted_by": "fixture:stub", "review_call": "",
                            "legacy_rows": 0, "replayed": 0, "terminated": "",
                            "why": "夹具：系统计数恒过"})
    root = tmp_path / "ws"
    rel, sha = _work(root)
    # b 的形状：旧组 2 轮 + 新组 1 轮。
    rows = _rows(SID, sha, [("call-old", 1, "clean"), ("call-old", 2, "clean"),
                            ("call-new", 1, "clean")])
    _write_ledger(root, SID, rows)
    wrote = _issue(root, rel, sha, rows)
    assert wrote["written"] is True, (
        "把系统计数打桩成恒过之后，b 那一份仍然没发出签 ⇒ b 的绿不是这道闸给的")
    # c 的形状：同号重放只到第 2 轮。
    root2 = tmp_path / "ws2"
    rel2, sha2 = _work(root2)
    _write_ledger(root2, SID, _rows(SID, sha2, [
        (CALL, 1, "clean"), (CALL, 2, "clean"), (CALL, 2, "clean")]))
    wrote2 = _issue(root2, rel2, sha2, _rows(SID, sha2, [
        (CALL, 1, "clean"), (CALL, 2, "clean"), (CALL, 2, "clean")]))
    assert wrote2["written"] is True, (
        "把系统计数打桩成恒过之后，c 那一份仍然没发出签 ⇒ c 的绿不是这道闸给的")


# ============================================================ f：老行标 legacy

def test_f_legacy_rows_are_labelled_and_do_not_count_into_the_new_group(tmp_path):
    """f：无 `review_call` 的老行 ⇒ 读数标 legacy；且不进新组计数、不改变它的数。"""
    sha = "f" * 64
    rows = _rows(SID, sha, [(CALL, 1, "clean")])
    for i in (1, 2):
        legacy = _row(SID, sha, pass_no=i, vid=f"v-legacy-{i}")
        legacy["review_call"] = ""
        legacy["review_pass"] = None
        rows.insert(0, legacy)
    counted = SC.count_rows(rows, review_call=CALL, proof_sha256=sha, need=3)
    assert (counted["count"], counted["ok"], counted["legacy_rows"]) == (1, False, 2), counted

    # 老形态发签：三行都没有 review_call ⇒ 按台账尾部复算，签文件显式标 legacy。
    root = tmp_path / "ws"
    rel, sha_real = _work(root)
    legacy_rows = [_row(SID, sha_real, pass_no=n, vid=f"v-{n:06d}") for n in (1, 2, 3)]
    for row in legacy_rows:
        row["review_call"] = ""
        row["review_pass"] = None
    _write_ledger(root, SID, legacy_rows)
    wrote = _issue(root, rel, sha_real, legacy_rows)
    assert wrote["written"] is True, wrote
    assert (wrote["legacy"], wrote["counted_by"]) == (True, SC.LEGACY_TAIL), wrote
    doc = _sign_doc(root, sha_real)
    assert doc["legacy"] is True and doc["counted_by"] == SC.LEGACY_TAIL, doc
    # 读侧同样显式：`consecutive_holds` / `review_standing` 都写 legacy 来源。
    assert VR.consecutive_holds(root, SID)["counted_by"] == SC.LEGACY_TAIL
    reading = VR.review_standing(root, statement_id=SID, proof_text=PROOF)
    assert reading["counted_by"] == SC.LEGACY_TAIL, reading


# ============================================================ ④：少一轮 / 多一轮

def test_rounds_one_less_or_one_more_does_not_change_the_decision(tmp_path):
    """④：`1..need` 齐 ⇒ 发；少一轮 ⇒ 不发；多一轮（第 4 轮 / 同号重放）⇒ 结论不变。"""
    sha = "1" * 64
    two = _rows(SID, sha, [(CALL, 1, "clean"), (CALL, 2, "clean")])
    three = _rows(SID, sha, [(CALL, 1, "clean"), (CALL, 2, "clean"), (CALL, 3, "clean")])
    four = _rows(SID, sha, [(CALL, 1, "clean"), (CALL, 2, "clean"),
                            (CALL, 3, "clean"), (CALL, 4, "clean")])
    replay = _rows(SID, sha, [(CALL, 1, "clean"), (CALL, 2, "clean"),
                              (CALL, 3, "clean"), (CALL, 3, "clean")])
    assert SC.count_rows(two, review_call=CALL, proof_sha256=sha, need=3)["ok"] is False
    base = SC.count_rows(three, review_call=CALL, proof_sha256=sha, need=3)
    for extra in (four, replay):
        got = SC.count_rows(extra, review_call=CALL, proof_sha256=sha, need=3)
        assert (got["count"], got["ok"]) == (base["count"], base["ok"]), got


def test_rounds_the_decision_does_not_read_the_callers_round_number(tmp_path):
    """④/③：把调用方递进来的轮数改成 1 或 999，秘书的发签结论不变（它只作读数）。"""
    root = tmp_path / "ws"
    rel, sha = _work(root)
    rows = _rows(SID, sha, [(CALL, 1, "clean"), (CALL, 2, "clean"), (CALL, 3, "clean")])
    _write_ledger(root, SID, rows)
    sec = SEC.Secretary("V", root=root)          # 没有 store：只判"发不发"，不落签
    for claim in (1, 3, 999):
        got = sec.decide_sign_issuance(
            statement_id=SID, proof_text=PROOF, proof_no=1, row=rows[-1],
            within_call=claim)
        assert got["checked"] is True, got
        assert got["issue"] is True, (claim, got["reason"])
        assert got["projected"] == 3, (claim, got["projected"])
        assert got["counted_by"] == SC.COUNTED_BY, got
    # 少一轮：只有 2 行 ⇒ 不论调用方说几轮，都不发。
    _write_ledger(root, SID, rows[:2])
    for claim in (3, 999):
        got = sec.decide_sign_issuance(
            statement_id=SID, proof_text=PROOF, proof_no=1, row=rows[1],
            within_call=claim)
        assert got["issue"] is False, (claim, got["reason"])
        assert got["projected"] == 2, (claim, got["projected"])


# ============================================================ ①：逐轮时刻

def test_at_is_the_round_time_not_the_batch_write_time(tmp_path, monkeypatch):
    """①：三行 `at` 是各自那一轮判词的时刻，不是三行一起写下那一刻。

    做法：把 `agent_v.core._now_iso` 打成一个递增的计数器（三个判词时刻各不相同），
    把 `verifications._now_iso`（写行时刻的来路）打成一个 2099 的哨兵。若写口退回
    "批量写行时刻"，三行 `at` 会全部等于哨兵 —— 那就当场红。
    """
    sentinel = "2099-01-01T00:00:00+08:00"
    ticks = iter([f"2026-11-17T10:00:0{i}+08:00" for i in (1, 2, 3, 4, 5)])

    def fake_core_now() -> str:
        return next(ticks)

    monkeypatch.setattr(V_CORE, "_now_iso", fake_core_now)
    monkeypatch.setattr(VR, "_now_iso", lambda: sentinel)
    st = _vws(tmp_path)
    v, _seam = _v(st, [CLEAN_REPLY])
    with _submitted_by_f():
        v.verify_proof(proof_manuscript=REL)
    rows = _pending_rows(st)
    assert len(rows) == 3, rows
    ats = [str(r.get("at") or "") for r in rows]
    assert ats == ["2026-11-17T10:00:01+08:00",
                   "2026-11-17T10:00:02+08:00",
                   "2026-11-17T10:00:03+08:00"], ats
    assert sentinel not in ats, "三行 `at` 是写行时刻（批量写下的那一刻）"

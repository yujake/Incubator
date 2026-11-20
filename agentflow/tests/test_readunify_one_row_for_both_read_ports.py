# -*- coding: utf-8 -*-
"""READUNIFY：两个读口对「哪一行算那一签」只有一个答案（锚行 / 否决 / 尾行）。

## 分歧现场（`temp/readunify/REPORT.md` §①）

`projects/lp-ball-10` 的 `stmt:000015`：pending 4 行 u-000022..025 全是「成立」、没有
未解决 error，前 3 行计 3/3，签文件 `out/vsigns/4e418348….json` 锚在 u-000024；尾行
u-000025 的秘书轴为空（`row_signable=False`）。同一份盘：

- 读口① `verifications.pending_sign`（R10FIX-D2）认「已发签锚在的那一行」⇒ u-000024、有签；
- 读口② `unverified_statement_refs` 的第二路（V2FIX）取 `claimed_rows[-1]` ⇒ u-000025、missing。

## 统一方向（三档，不折平）

以签文件的 ledger 锚行为准：

- 锚行成立、其后没有 fault ⇒ 有签（认锚行）；
- 锚点之后那一行判 `fault` ⇒ 否决（后来的否决盖过更早的成立，RETIRE-E3 同一条纪律）；
- 没有签文件 / 锚点不在盘上 / 锚行签不住 ⇒ 按尾行判（尾行没判成 ⇒ 无签）。

取行只有一处：`verifications._pending_sign_row`（判据本体是 `_issued_anchor_of_pending`）。
两读口都调它；V2FIX 的「在册台账 或 已认领的 pending」两路并读结构一个字没动。

## 判据

| # | 判据 | 造的是什么现场 |
|---|---|---|
| a | 3/3 签 + 之后一笔没判成的行（都认领）⇒ 两读口都认 u-000003、`missing=[]` | lp-ball-10 的 stmt:000015（BWRITE 回填后的形态） |
| b | 3/3 签之后又来一笔 `fault`（那一笔没认领）⇒ 两读口都「否决」 | lp-ball-12 的 000071（u-000045 判 fault、000042..44 已认领） |
| c | 没有签文件（只是 pending 行、尾行没判成）⇒ 两读口都「无签」 | 未发签的三转 |
| d | 反真空：把统一实现打桩回旧行为（只取尾行）⇒ a 当场红 | 证明 a 的绿灯压在这一处 |
"""
from __future__ import annotations

import json
import pathlib

import pytest

from agentflow import verifications as VR
from agentflow import vsigns as VS

from conftest import seed_statement_row
from test_the_issued_sign_is_what_gets_claimed import (
    CARRIER, CLEAN_JUDGE, REL_TAIL, UNJUDGED, _issue, _manuscript, _pending, _put,
    _store,
)
from test_the_first_sign_before_registration_still_lifts_the_kind import (
    FULL, LABEL, PROOF,
)

SID = "000000"


# ---------------------------------------------------------------- 夹具


def _seed_statement(st: object) -> str:
    """在册一行（没有 `verifications/<号>.jsonl`：答案只能由第二路给）。"""
    row = seed_statement_row(
        st, statement_full=FULL, statement_text=LABEL, kind="conjecture",
        proof_text=PROOF, label=LABEL, stmt_id=SID)
    return str(row["stmt_id"])


def _claim(st: object, vids: list[str], sid: str) -> None:
    """把选定的那几行认领给 `sid`（只改 tmp 工作区：真机形态是 `bind_pending_claim`）。"""
    path = VR.pending_ledger_path(getattr(st, "root"), CARRIER)
    lines = []
    for line in path.read_text(encoding="utf-8").splitlines(keepends=True):
        row = json.loads(line)
        if str(row.get("verification_id") or "") in vids:
            row["statement_id"] = sid
            row["stmt_id"] = sid
            row["claimed_at"] = "2026-11-19T13:47:02+08:00"
        lines.append(json.dumps(row, ensure_ascii=False) + "\n")
    path.write_text("".join(lines), encoding="utf-8")


def _plain_rows(st: object) -> list[dict]:
    """前 3 行：同一趟送审的 3/3「成立 + 秘书判 clean」。"""
    return [_pending(st, i=i, call="c1", judge=CLEAN_JUDGE,
                     at=f"2026-11-19T13:42:1{i}+08:00") for i in (1, 2, 3)]


def _port1(root: object, sha: str, sid: str) -> dict:
    """读口①：这一份正文有没有签，取到的那一行签不签得住。"""
    got = VR.pending_sign(root, proof_shas=(sha,))
    row = dict(got.get("row") or {})
    claimed = str(row.get("stmt_id") or row.get("statement_id") or "")
    return {"found": bool(got.get("found")), "row": row,
            "row_id": str(row.get("verification_id") or ""),
            "signable": bool(row) and VR.row_signable(row),
            "claimed_to": claimed,
            "anchored": bool(got.get("anchored_at_issued_sign")),
            "has_sign": bool(got.get("found")) and VR.row_signable(row)
            and claimed in ("", sid)}


def _port2(root: object, sid: str) -> tuple[dict, bool]:
    """读口②：V2FIX 第二路（一份 plan 的 history 点名这一条命题）。"""
    refs = VR.unverified_statement_refs(
        root, [{"plan_id": "readunify",
                "history": [{"round": 1, "statement_id": sid}]}])
    assert refs.get("checked") is True, refs
    (ref,) = refs["refs"]
    has_sign = (not refs["missing"]) and bool(ref.get("pending_signable"))
    return {"refs": refs, "ref": ref, "has_sign": has_sign,
            "missing_ids": [str(m.get("statement_id") or "")
                            for m in (refs.get("missing") or [])]}


# ============================================================ a 有签（锚行）


def test_a_the_issued_sign_anchors_both_read_ports(tmp_path: pathlib.Path) -> None:
    """a：签锚在 u-000003、尾行 u-000004 没判成 ⇒ 两读口都认 u-000003（有签）。"""
    st = _store(tmp_path)
    rel, text = _manuscript()
    _put(st, rel, text)
    rows = _plain_rows(st)
    issued = _issue(st, rows)
    assert issued.get("written") is True or issued.get("idempotent") is True, issued
    # 签发出之后 V 又跑了一趟：第 2 轮、秘书没判成（尾行无轴）
    tail = _pending(st, i=2, call="c2", judge=UNJUDGED,
                    at="2026-11-19T13:42:52+08:00")
    sid = _seed_statement(st)
    _claim(st, [r["verification_id"] for r in rows] + [tail["verification_id"]], sid)

    sha = str(rows[0]["proof_sha256"])
    p1 = _port1(st.root, sha, sid)
    p2 = _port2(st.root, sid)
    # 读口①：认签文件锚在的那一行（不是尾行）
    assert p1["found"] is True, p1
    assert p1["row_id"] == "u-000003", p1
    assert p1["signable"] is True, p1
    assert p1["anchored"] is True, p1
    # 读口②：同一个答案（改前它取 u-000004 ⇒ missing）
    assert p2["ref"]["pending_rows"] == 4, p2["ref"]
    assert p2["ref"]["pending_row"] == "u-000003", p2["ref"]
    assert p2["ref"]["pending_state"] == "anchor", p2["ref"]
    assert p2["ref"]["pending_signable"] is True, p2["ref"]
    assert p2["refs"]["missing"] == [], p2["refs"]
    assert p2["ref"]["rows"] == 4, p2["ref"]
    # 两读口一致「有签」
    assert p1["has_sign"] is True and p2["has_sign"] is True, (p1, p2)


# ============================================================ b 否决（锚点后的 fault）


def test_b_a_later_fault_vetoes_even_when_that_row_is_unclaimed(
        tmp_path: pathlib.Path) -> None:
    """b：3/3 签之后又来一笔 fault、那一笔没认领 ⇒ 两读口都「否决」。

    现场是 `lp-ball-12` 的 000071：u-000042..44（已认领）+ u-000045（`fault`、未认领）
    住在同一份 pending 台账里。只读已认领的行 ⇒ 尾行是 u-000044（成立）⇒ 会漏掉
    后来的否决；整叠读才看得见 u-000045。
    """
    st = _store(tmp_path)
    rows = _plain_rows(st)
    _issue(st, rows)
    fault = _pending(st, i=1, call="c3",
                     judge={"checked": True, "axis": "fault",
                            "decision": "有毛病", "reason": "夹具：秘书判 fault"},
                     at="2026-11-19T13:50:00+08:00")
    sid = _seed_statement(st)
    _claim(st, [r["verification_id"] for r in rows], sid)   # 只认前 3 行

    sha = str(rows[0]["proof_sha256"])
    p1 = _port1(st.root, sha, sid)
    p2 = _port2(st.root, sid)
    # 读口①：尾行 fault ⇒ 不翻旧账（锚点不复活）
    assert p1["row_id"] == fault["verification_id"], p1
    assert p1["signable"] is False, p1
    assert p1["has_sign"] is False, p1
    # 读口②：同一个答案 —— 尾行那一转即使没认领，也仍是这一签之后的那一转
    assert p2["ref"]["pending_row"] == fault["verification_id"], p2["ref"]
    assert p2["ref"]["pending_state"] == "vetoed", p2["ref"]
    assert p2["ref"]["pending_signable"] is False, p2["ref"]
    assert p2["missing_ids"] == [sid], p2["refs"]
    assert p2["has_sign"] is False, p2
    # 两读口一致「否决」
    assert p1["has_sign"] is False and p2["has_sign"] is False, (p1, p2)


# ============================================================ c 无签（没有签文件）


def test_c_without_a_sign_file_both_read_ports_say_no_sign(
        tmp_path: pathlib.Path) -> None:
    """c：没有签文件、尾行没判成 ⇒ 两读口都「无签」（不许拿一叠没判完的行当签）。"""
    st = _store(tmp_path)
    rows = _plain_rows(st)                       # 没有 `_issue`：这一份正文没有签文件
    tail = _pending(st, i=2, call="c2", judge=UNJUDGED,
                    at="2026-11-19T13:42:52+08:00")
    sid = _seed_statement(st)
    _claim(st, [r["verification_id"] for r in rows] + [tail["verification_id"]], sid)

    sha = str(rows[0]["proof_sha256"])
    assert not VS.sign_of(str(st.root), sha).get("found"), "夹具：这一份正文不该有签文件"
    p1 = _port1(st.root, sha, sid)
    p2 = _port2(st.root, sid)
    # 读口①：读得到行（found），但那一行签不住；没有锚点可认
    assert p1["found"] is True, p1
    assert p1["row_id"] == tail["verification_id"], p1
    assert p1["signable"] is False, p1
    assert p1["anchored"] is False, p1
    assert p1["has_sign"] is False, p1
    # 读口②：同一个答案
    assert p2["ref"]["pending_row"] == tail["verification_id"], p2["ref"]
    assert p2["ref"]["pending_state"] == "tail", p2["ref"]
    assert p2["ref"]["pending_signable"] is False, p2["ref"]
    assert p2["missing_ids"] == [sid], p2["refs"]
    assert p2["has_sign"] is False, p2
    # 两读口一致「无签」
    assert p1["has_sign"] is False and p2["has_sign"] is False, (p1, p2)


# ============================================================ d 反真空


def test_d_stubbing_the_unified_reader_back_to_the_tail_turns_a_red(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """d：把统一取行打桩回旧行为（只取尾行）⇒ a 的断言当场红。"""
    def _tail_only(root, *, rows, tail=None, sha=""):  # noqa: ARG001 —— 只模拟旧射程
        pile = [dict(r) for r in (rows or ())]
        last = dict(tail) if isinstance(tail, dict) else (pile[-1] if pile else {})
        return {"row": last, "anchored": False, "path": "",
                "signable": bool(last) and VR.row_signable(last),
                "state": "tail", "sha": sha, "why": "夹具：打桩回旧行为（只取尾行）"}

    monkeypatch.setattr(VR, "_pending_sign_row", _tail_only)
    st = _store(tmp_path)
    rel, text = _manuscript()
    _put(st, rel, text)
    rows = _plain_rows(st)
    _issue(st, rows)
    tail = _pending(st, i=2, call="c2", judge=UNJUDGED,
                    at="2026-11-19T13:42:52+08:00")
    sid = _seed_statement(st)
    _claim(st, [r["verification_id"] for r in rows] + [tail["verification_id"]], sid)

    p1 = _port1(st.root, str(rows[0]["proof_sha256"]), sid)
    p2 = _port2(st.root, sid)
    # a 的三条断言逐条回红（这一格不是恒真）：
    assert p1["anchored"] is False, p1                    # a: anchored is True
    assert p1["has_sign"] is False, p1                    # a: has_sign is True
    assert p2["missing_ids"] == [sid], p2["refs"]     # a: missing == []
    assert p2["ref"]["pending_signable"] is False, p2["ref"]

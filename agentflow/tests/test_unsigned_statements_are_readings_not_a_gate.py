# -*- coding: utf-8 -*-
"""收工门不再读签拦收工：只列「有稿无签」读数清单（业主裁定 3 + 追加裁定 B）。

裁定原文（逐字）：

> 「取消（但要保证没签的都是放弃的）」＋ 追加裁定「B」：
> 收工门不再读签拦收工，只列"无签"读数清单，不拦。

## 改前是什么形态（缺陷本体）

`closing.py` 的 `statements_unsigned` 那一格读签，读到"既无 V 签也未放弃"就发一条
blocker（`statements_unsigned_without_v_or_abandon`）：`machine_pass=false`、退出码 1。
业主 2026-11-01 的旧裁定（「每个命题和证明的产出最终必须以V签收尾」）在 2026-11-16
被裁定 3 + B 取代：门不再因为"还没签"而拦住收工，只把"有稿无签"逐份列成读数。

## 判据一览

| # | 造什么 | 期望 |
|---|---|---|
| f | 一条命题有稿、没有签（V 判过「有毛病」之后没重送） | 收工门不 fail（`machine_pass=true`、退出码 0、没有 blocker）；读数里逐份列出族 / 号 / sha / 为什么没签；门上那条是 warning（不是 blocker） |
| g | 反真空：把读数删掉（打桩成空清单） | f 的清单为空 ⇒ f 的逐份断言当场红（那条读数在承重） |

## 为什么不是"静默丢掉"

裁定要的是"不拦"，不是"看不见"：清单里逐份给族 + 号 + sha + 为什么没签
（`class` 与一句话），于是"哪几份稿还没签、欠的是哪一种"仍然读得出来，只是不再
把整趟收工判死。三态纪律照旧：台账读不出来 ⇒ `checked=False` + warning（不是 0 条）。
"""
from __future__ import annotations

import pathlib

import pytest
from agentflow import closing as CL
from agentflow import proofregistry as R
from agentflow import verifications as VR
from agentflow.store import Store

TS = "2026-11-16T19:00:00+08:00"
SID = "000001"
SID2 = "000002"
FULL = "设 f 在 [0,1] 上连续，则 f 一致连续。"
PROOF = "取 δ=ε，逐点验证：|x-y|<δ ⇒ |f(x)-f(y)|<ε。"
PROOF2 = "取 δ=ε/2，用紧性把逐点控制换成一致控制。"
MID = "000777"
MID2 = "000778"
REL_F = f"reports/f-proof-{MID}.md"
REL_F2 = f"reports/f-proof-{MID2}.md"


def _ws(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _put(st: Store, *, sid: str = SID, proof: str = PROOF, mid: str = MID) -> dict:
    """铺一行在册命题（与 `test_statements_unsigned_and_resubmit.py` 同一套夹具形状）。"""
    row = {
        "stmt_id": sid, "origin": "own_result", "kind": "theorem",
        "label": f"探针命题 {sid}", "statement_full": FULL, "statement_text": FULL,
        "proof_text": proof, "evidence_kind": "heuristic", "status": "active",
        "quote_verified": None, "quote_reason": "夹具：自产命题",
        "created_at": TS, "created_by": "test", "bits": {},
        "manuscript_id": mid,
    }
    with st.tx("statements", actor="test") as tx:
        tx.upsert("statements", row)
    return row


def _manuscript_file(st: Store, rel: str) -> None:
    """盘上真的有一份稿（"有稿无签"里的"有稿"必须是真的有）。"""
    path = pathlib.Path(st.root) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "# F 的证明手稿（夹具）\n\n- 正文sha：" + "0" * 64 + "\n\n"
        "## 命题\n\n" + FULL + "\n\n## 证明\n\n" + PROOF + "\n\n"
        "## 依赖\n\n（这一份证明没有引用任何在册命题 —— 空表就是声明。）\n",
        encoding="utf-8")


def _fault(st: Store, *, sid: str = SID, proof: str = PROOF, rel: str = REL_F) -> dict:
    """V 判过「有毛病」、之后没有重送 ⇒ 这一份稿"没有签"。"""
    return VR.record_verification(
        st.root, statement_id=sid, proof_text=proof,
        verdict={"verdict": "有毛病", "defect_step": 5,
                 "findings": [{"level": "error", "step": 5, "kind": "无依据的步骤",
                               "detail": "第 5 步直接用了结论"}]},
        secretary_judge={"axis": "fault", "checked": True, "reason": "夹具：秘书的语义判定"},
        manuscript=rel, flip=False)


def _closing(st: Store):
    """只跑读数那一层（`checks=()`）：这一笔要测的是门对"还没签"的反应。"""
    return CL.check_closing(st, checks=(), goal="测门", goal_met=True, basis="夹具")


def _unsigned(st: Store) -> dict:
    return CL.statements_unsigned_reading(st, now="2026-11-16T20:00:00+08:00")


# ------------------------------------------------------------------ f：不拦 + 逐份列出

def test_f_a_manuscript_without_a_sign_does_not_fail_the_closing_gate(tmp_path):
    """f：有稿无签 ⇒ 收工门不 fail，读数里逐份给族 / 号 / sha / 为什么没签。"""
    st = _ws(tmp_path)
    _put(st)
    _manuscript_file(st, REL_F)
    _fault(st)

    rep = _closing(st)
    # ① 不拦：没有 blocker、machine_pass 仍为真、退出码 0
    assert rep.machine_pass is True, [f.to_dict() for f in rep.blockers]
    assert CL.tri_state_exit_code(rep) == 0, rep.to_dict()
    assert [f for f in rep.blockers if f.check == "statements_unsigned"] == []
    # ② 读数里逐份列出（族 / 号 / sha / 为什么没签）
    reading = rep.readings["statements_unsigned"]
    assert reading["checked"] is True, reading
    assert reading["count"] == 1, reading
    items = list(reading.get("unsigned_manuscripts") or [])
    assert len(items) == 1, items
    one = dict(items[0])
    assert one["stmt_id"] == SID, one
    assert one["family"] == "f-proof", one
    assert one["manuscript_id"] == MID, one
    assert one["manuscript"] == REL_F, one
    assert one["sha256"] == R.proof_sha(PROOF), one
    assert len(one["sha256"]) == 64, one
    assert one["class"] == "fault_unrepaired", one
    assert one["why"], one
    # ③ 门上那条读数还在（warning，不判 fail），且 detail 里带族 + 号 + sha 的前缀
    warned = [f for f in rep.findings
              if f.check == "statements_unsigned" and f.level == "warning"]
    named = [f for f in warned
             if f.code == "statements_unsigned_without_v_or_abandon"]
    assert len(named) == 1, [f.to_dict() for f in warned]
    detail = named[0].detail
    assert "f-proof" in detail and MID in detail, detail
    assert R.proof_sha(PROOF)[:12] in detail, detail
    assert "还没签" in detail or "没有 V 签" in detail, detail


def test_f_two_manuscripts_without_signs_are_both_listed_in_statement_order(tmp_path):
    """f（两条）：清单逐份、按命题号稳定排序；两条都进读数（不折叠成一句"共 N 条"）。"""
    st = _ws(tmp_path)
    _put(st)
    _put(st, sid=SID2, proof=PROOF2, mid=MID2)
    _manuscript_file(st, REL_F)
    _manuscript_file(st, REL_F2)
    _fault(st)
    _fault(st, sid=SID2, proof=PROOF2, rel=REL_F2)

    reading = _unsigned(st)
    assert reading["count"] == 2, reading
    items = list(reading.get("unsigned_manuscripts") or [])
    assert [x["stmt_id"] for x in items] == [SID, SID2], items
    assert [x["manuscript_id"] for x in items] == [MID, MID2], items
    assert [x["sha256"] for x in items] == [R.proof_sha(PROOF), R.proof_sha(PROOF2)], items
    assert reading["unsigned_manuscripts_count"] == 2, reading


def test_f_the_reading_still_works_when_the_gate_is_green(tmp_path):
    """f（正控）：没有"有稿无签"的命题 ⇒ 清单为空、门绿（不冤枉干净的工作区）。"""
    st = _ws(tmp_path)
    rep = _closing(st)
    assert rep.machine_pass is True, rep.to_dict()
    assert list(rep.readings["statements_unsigned"].get("unsigned_manuscripts") or []) == []


# ------------------------------------------------------------------ g：反真空

def test_g_removing_the_reading_empties_the_list_and_makes_f_red(tmp_path, monkeypatch):
    """g：把清单那一格打桩成空 ⇒ f 的"逐份列出"当场红（那条读数在承重）。"""
    monkeypatch.setattr(CL, "unsigned_manuscripts_from",
                        lambda *_a, **_kw: [])
    st = _ws(tmp_path)
    _put(st)
    _manuscript_file(st, REL_F)
    _fault(st)
    rep = _closing(st)
    reading = rep.readings["statements_unsigned"]
    items = list(reading.get("unsigned_manuscripts") or [])
    assert items == [], "打桩之后清单必须真的空了（否则这一条证明不了什么）"
    with pytest.raises(AssertionError):
        assert len(items) == 1, "清单被删掉 ⇒ f 的逐份断言不成立"
    # 门仍然绿（这一格本来就不再拦），所以红只能来自读数 —— 这正是要钉的那一格
    assert rep.machine_pass is True, [f.to_dict() for f in rep.blockers]

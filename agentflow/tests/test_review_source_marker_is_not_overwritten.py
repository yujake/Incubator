# -*- coding: utf-8 -*-
"""RE ①：finding 的来源标识属于身份，不许被状态写口吃掉。

## 现场（projects/lp-ball，2026-11-14；分析与原始读数见 temp/analysis/12-review-exit.md）

H 用 `record_finding` 落手工判词时，`resolution_note` 以 `[manual] ` 开头；G 的
`own.revise` 把它标成 fixed（追加理由，不动前缀）；H 的 `verify_fixes` 重开它时
把 `resolution_note` 整格替换成 `[round 2] ...` ⇒ 前缀消失 ⇒ `_is_manual_finding`
变 False ⇒ H 再复核被自己的闸拒（"显式复核只对手工判词开放"），而下一轮又会
把它当机械发现"没复现 ⇒ fixed"（不查就关）。两个方向都错，唯一的开关是这一格原文。

## 四条判据

- a 正控：手工判词被 G 标 fixed、再被 `verify_fixes` 重开 ⇒ 它仍是手工判词，
  显式复核被接受并能关掉（真机上对应 000000 / 000002 那两条）；
- b 负控：机械发现全程保持机械（不许被误抬成手工，显式复核仍被拒）；
- c 反真空：把"认来源标识"那处打桩回旧行为（恒返回空串）⇒ a 必红；
- d 反向风险：前缀（或它在盘上的历史残迹）在的行不许走"没复现 ⇒ fixed"那条。

## 为什么选"保前缀 + 认曾经出现过"，而不是新加一列

来源标识属于 finding 的身份，不属于状态：它必须活在一个不会被状态写口覆写的落点。
`schema.ReviewFinding` 在 FC-27 禁改区（本批不许加列），而 `resolution_note` 是既有
自由文本字段、不进去重键、不是审校内容 ⇒ 只有它能承载这个身份。于是：

- 写侧：状态写口对手工判词只追加（`_note_after_status_update`），前缀永不被吃掉；
- 读侧：判定是"这句话出现过没有"（`_manual_origin_mark`），不是"它还在不在开头"
  —— 这样修复之前已经落盘的损伤（真机那两条只剩 `MANUAL_NOT_RECHECKED_NOTE`）
  也能被认出来，不会在下一轮被静默关掉。

两种形态都读同一格自由文本、都是本模块的受控常量，机械那一支一个字都不写它们
⇒ 不产生第二套事实源。
"""

from __future__ import annotations

import pytest

from agentflow import schema as S
from agentflow.agent_g import AgentG
from agentflow.agent_h import AgentH
from agentflow.store import Store
from agentflow.tools import review_tools as RV

from conftest import add_literature, write_paper

TS = "2026-01-01T00:00:00+00:00"

MANUAL_MESSAGE = "手工判词：这句把交叉验证说成了证明"
MANUAL_EVIDENCE = "正文第 10 行逐字：'we have proved it'"


def _claim(citations: list[str] | None = None) -> dict:
    return {
        "claim_id": "claim-1",
        "section": "主要结果",
        "text": "谱落在区间内。",
        "evidence_kind": "heuristic",
        "citations": ["lit:0000"] if citations is None else list(citations),
        "is_negative": False,
        "negation_kind": None,
    }


def _workspace(store: Store) -> Store:
    write_paper(store, "\\documentclass{article}\n\\begin{document}\n谱落在区间内。\n\\end{document}\n")
    add_literature(store, "0000", title="探针文献", processed=True)
    row = S.Document(
        doc_id="0000", kind="paper", title="RE ① 探针稿", markdown_path=None,
        claims=[_claim()], status="draft", review_rounds=0,
        created_at=TS, updated_at=TS,
    ).to_dict()
    with store.tx("documents", actor="test", note="fixture") as tx:
        tx.upsert("documents", row)
    return store


def _row(store: Store, finding_id: str) -> dict:
    return next(dict(r) for r in store.rows("review_findings")
                if str(r["finding_id"]) == str(finding_id))


def _record(agent: AgentH, *, round_no: int, **overrides):
    kw = {
        "kind": "overclaim",
        "target": "claim-1",
        "message": MANUAL_MESSAGE,
        "evidence": MANUAL_EVIDENCE,
        "level": "error",
        "round_no": round_no,
    }
    kw.update(overrides)
    return agent.writers.call("review.record_finding", role="H", doc_id="0000", **kw)


def _record_ok(agent: AgentH, *, round_no: int, **overrides) -> str:
    got = _record(agent, round_no=round_no, **overrides)
    assert got.ok is True, got.error
    return str(got.data["finding_id"])


def _recheck(agent: AgentH, *, evidence: str, message: str = MANUAL_MESSAGE):
    return _record(agent, round_no=2, evidence=evidence, message=message)


# ============================================================ a 正控


def test_a_a_manual_finding_reopened_by_verify_fixes_is_still_manual(store: Store):
    """手工判词被 G 标 fixed、再被 H 重开 ⇒ 仍是手工判词，显式复核被接受并能关掉。"""
    _workspace(store)
    agent = AgentH(store, config={"max_review_rounds": 5})
    fid = _record_ok(agent, round_no=1)
    assert _row(store, fid)["resolution_note"].startswith(RV.MANUAL_FINDING_NOTE_PREFIX)

    # G 修得越对，越会走到这条路上：revise 先把它标成 fixed。
    AgentG(store).revise("0000", fixed_findings=[fid], note="按 H 的发现改了正文")
    assert _row(store, fid)["status"] == "fixed"

    res = agent.verify_fixes("0000", round_no=2)
    row = _row(store, fid)
    assert row["status"] == "open", row
    assert row["resolution_note"].startswith(RV.MANUAL_FINDING_NOTE_PREFIX), row["resolution_note"]
    # 重开理由必须真的写进去（不是靠不写来"保住前缀"）：
    assert "不能被自动复跑判掉" in row["resolution_note"], row["resolution_note"]
    assert RV._is_manual_finding(row) is True
    assert [f for f in res["still_open"] if f["finding_id"] == fid][0]["source"] == "manual_not_rechecked"

    fixed = _recheck(agent, evidence=f"{RV.RECHECK_FIXED_PREFIX}第 10 行已改成 numerically supported")
    assert fixed.ok is True, fixed.error
    assert fixed.data["status"] == "fixed", fixed.data
    row = _row(store, fid)
    assert row["status"] == "fixed", row
    assert RV.MANUAL_RECHECK_MARK in row["resolution_note"], row["resolution_note"]


# ============================================================ b 负控（方向相反）


def test_b_a_mechanical_finding_stays_mechanical(store: Store):
    """机械发现全程保持机械：显式复核仍被拒，状态写口也不会把它抬成手工。"""
    _workspace(store)
    # 一条悬空依赖 ⇒ 机械扫描必产 dangling_dep（稿件行本身仍然合法）。
    dep = S.Dependency(
        dep_id="0000", used_by="doc:0000#claim-1", kind="theorem",
        label="悬空依赖", status="dangling", status_reason="引了但还没找到来源",
        created_at=TS,
    )
    dep.validate()
    with store.tx("dependencies", actor="test", note="fixture") as tx:
        tx.upsert("dependencies", dep.to_dict())
    agent = AgentH(store, config={"max_review_rounds": 5})
    reviewed = agent.review("0000")
    mech = [f for f in reviewed["new_findings"] if str(f.get("kind")) == "dangling_dep"]
    assert mech, reviewed["new_findings"]
    fid = str(mech[0]["finding_id"])
    row = _row(store, fid)
    assert row["resolution_note"] == "", row["resolution_note"]
    assert RV._is_manual_finding(row) is False

    # 显式复核不许替机械发现盖章（与 a 的方向相反）。
    refused = _record(agent, round_no=2, kind=str(row["kind"]), target=str(row["target"]),
                      message=str(row["message"]),
                      evidence=f"{RV.RECHECK_FIXED_PREFIX}我说它好了")
    assert refused.ok is False and "机械扫描" in str(refused.error), refused

    # G 谎报 fixed、扫描仍复现 ⇒ 重开；重开写口只写理由，不写来源标识。
    AgentG(store).revise("0000", fixed_findings=[fid], note="我说改好了")
    agent.verify_fixes("0000", round_no=2)
    row = _row(store, fid)
    assert row["status"] == "open", row
    # 状态写口写进去的是理由，不是来源标识（两种形态都不许出现）。
    assert RV.MANUAL_FINDING_NOTE_PREFIX not in str(row["resolution_note"])
    assert RV.MANUAL_NOT_RECHECKED_NOTE not in str(row["resolution_note"])
    assert RV._is_manual_finding(row) is False
    refused2 = _record(agent, round_no=2, kind=str(row["kind"]), target=str(row["target"]),
                       message=str(row["message"]),
                       evidence=f"{RV.RECHECK_WONTFIX_PREFIX}不修")
    assert refused2.ok is False, refused2


# ============================================================ c 反真空


def test_c_stubbing_the_origin_reader_back_to_old_behaviour_makes_a_red(store: Store, monkeypatch):
    """反真空：把"认来源标识"那处打桩回旧行为 ⇒ a 的三条主张全不成立。"""
    _workspace(store)
    agent = AgentH(store, config={"max_review_rounds": 5})
    fid = _record_ok(agent, round_no=1)
    AgentG(store).revise("0000", fixed_findings=[fid], note="按 H 的发现改了正文")
    assert _row(store, fid)["status"] == "fixed"

    # 旧行为 = 前缀只在开头才算数，且状态写口整格覆写（两者都由这一个读口驱动）。
    monkeypatch.setattr(RV, "_manual_origin_mark", lambda row: "")
    agent.verify_fixes("0000", round_no=2)

    row = _row(store, fid)
    # a 说"重开之后仍是 open 且仍是手工判词"—— 在这一桩下两条都不成立，a 必红。
    assert row["status"] == "fixed", row
    assert RV._is_manual_finding(row) is False
    refused = _recheck(agent, evidence=f"{RV.RECHECK_FIXED_PREFIX}第 10 行已改")
    assert refused.ok is False, refused
    assert "显式复核只对" in str(refused.error), refused


# ============================================================ d 反向风险


def test_d1_a_prefix_surviving_manual_finding_is_not_closed_by_the_mechanical_criterion(store: Store):
    """前缀在的手工判词：下一轮复审不许拿"没复现"把它关掉（不查就关）。"""
    _workspace(store)
    agent = AgentH(store, config={"max_review_rounds": 5})
    fid = _record_ok(agent, round_no=1)
    AgentG(store).revise("0000", fixed_findings=[fid], note="按 H 的发现改了正文")
    agent.verify_fixes("0000", round_no=2)          # 重开，前缀保住
    assert RV._is_manual_finding(_row(store, fid)) is True

    # 第二轮复审：这一条的去重键永远不在 scan 产出里 —— 机械判据会判"没复现 ⇒ fixed"。
    res = agent.verify_fixes("0000", round_no=3)
    row = _row(store, fid)
    assert row["status"] == "open", row
    assert res["resolved"] == [], res["resolved"]
    assert [f for f in res["still_open"] if f["finding_id"] == fid][0]["source"] == "manual_not_rechecked"
    assert "不再复现" not in row["resolution_note"], row["resolution_note"]


def test_d2_a_prefix_already_destroyed_on_disk_is_not_read_as_mechanical(store: Store):
    """盘上前缀已被旧写口吃掉的行（真机 000000 / 000002 的形态）也不许被静默关掉。"""
    _workspace(store)
    agent = AgentH(store, config={"max_review_rounds": 5})
    fid = _record_ok(agent, round_no=1)

    # 复刻旧写口留下的盘上形态：整格覆写之后只剩那句"手工判词不能被自动复跑判掉"，
    # 状态还是 open（真机那两条被 verify_fixes 重开之后就是这个形状）。
    with store.tx("review_findings", actor="test", note="fixture: 旧写口的损伤") as tx:
        row = dict(tx.find("review_findings", finding_id=fid))
        row["status"] = "open"
        row["resolution_note"] = f"[round 2] {RV.MANUAL_NOT_RECHECKED_NOTE}"
        tx.upsert("review_findings", row)
    assert RV._is_manual_finding(_row(store, fid)) is True

    res = agent.verify_fixes("0000", round_no=3)
    row = _row(store, fid)
    assert row["status"] == "open", row
    assert res["resolved"] == [], res["resolved"]
    assert [f for f in res["still_open"] if f["finding_id"] == fid][0]["source"] == "manual_not_rechecked"

    # 真机上 H 已经判过 fixed 的那条现在能被接受（这正是被关死的唯一离场通道）。
    got = _recheck(agent, evidence=f"{RV.RECHECK_FIXED_PREFIX}第 8/9 节标题已上盘")
    assert got.ok is True, got.error
    assert got.data["status"] == "fixed", got.data

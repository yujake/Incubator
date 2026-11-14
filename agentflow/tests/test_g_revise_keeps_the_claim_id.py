# -*- coding: utf-8 -*-
"""G 的 `revise`：只认本稿现行号；标 fixed 必须真改到那条断言。

## 现场（`projects/lp-ball`，2026-11-14；读数见 `temp/_g3/p12_revise_probe.txt`）

- G 三次 `revise` 一次都没传过已存在的 claim 号 —— 而"号没地方查"不成立：号就在它
  三次 `fs.read` 过的 `documents/000000.md` 正文里（`**claim-N**`）。
- 传 `claim_id="claim-99"` ⇒ `replaced=[]`、`appended=["claim-99"]`，盘上那条被
  `normalize_claims` 按位置编成 claim-26 ⇒ 三态折成一态，且回执报的是请求号。
- `fixed_findings` 里 `target=claim-11` 的发现标 fixed 三次，claim-11 一个字没改，
  写口照收。

## 判据

- a 正控：`claim-7` 同号交回 ⇒ `replaced=["claim-7"]`、`appended=[]`、条数不变、正文真改；
- b 未知号 `claim-99` ⇒ 受控拒 `unknown_claim_id`，拒信列出本稿现行号；盘上一行不动；
- c `target=claim-11` 的发现，而这一笔没改 claim-11 ⇒ 拒 `finding_target_not_revised`；
  c2 同号交回但内容逐字相同 ⇒ 同样拒（"交回了"不等于"改了"）；
- d 反真空：把 ① 打桩回旧行为 ⇒ b 的场景被静默追加；把 ② 打桩成恒通过 ⇒ c 照收；
- e 回执报归一化号：新增一条（不给号）⇒ `appended=["claim-12"]`，不是请求号/占位句。
"""

from __future__ import annotations

import pytest

from agentflow.agent_g import AgentG
from agentflow.agent_g import revise_gates as RG
from agentflow.agent_g._support import DocumentError
from agentflow.store import Store
from agentflow.tools import review_tools as RV

from conftest import add_literature, write_paper


def _claim(text: str, claim_id: str | None = None) -> dict:
    out = {
        "section": "主要结果",
        "text": text,
        "evidence_kind": "heuristic",
        "citations": ["lit:0000"],
        "is_negative": False,
        "negation_kind": None,
    }
    if claim_id is not None:
        out["claim_id"] = claim_id
    return out


def _workspace(store: Store, *, n: int = 11) -> tuple[AgentG, str, dict]:
    """建一份 n 条断言的稿件（claim-1..claim-n），返回 `(G, doc_id, build 回执)`。"""
    write_paper(store, "\\documentclass{article}\n\\begin{document}\n探针正文。\n\\end{document}\n")
    add_literature(store, "0000", title="探针文献", processed=True)
    g = AgentG(store, config={"docs_subdir": "documents"})
    doc = g.build_document(
        "note", "G 的 revise 探针稿",
        claims=[_claim(f"断言 {i}。") for i in range(1, n + 1)],
    )
    return g, str(doc["doc_id"]), doc


def _row(store: Store, doc_id: str) -> dict:
    return next(dict(r) for r in store.rows("documents")
                if str(r.get("doc_id")) == str(doc_id))


def _documents_bytes(store: Store) -> bytes:
    return (store.data / "documents.json").read_bytes()


# ============================================================ a 正控


def test_a_a_same_id_replacement_changes_that_claim_in_place(store: Store):
    """claim-7 同号交回 ⇒ 原位替换、条数不变、正文真改。"""
    g, doc_id, doc = _workspace(store)
    before = [dict(c) for c in doc["claims"]]

    out = g.revise(doc_id, new_claims=[_claim("断言 7（改后）。", "claim-7")],
                   note="同号替换 claim-7")

    assert out["replaced_claim_ids"] == ["claim-7"], out
    assert out["appended_claim_ids"] == [], out
    assert out["claim_count"] == len(before), out
    row = _row(store, doc_id)
    assert len(row["claims"]) == len(before), "同号替换不许加条数"
    assert row["claims"][6]["claim_id"] == "claim-7"
    assert row["claims"][6]["text"] == "断言 7（改后）。"


# ============================================================ b 未知号


def test_b_an_invented_claim_id_is_refused_and_lists_the_current_ids(store: Store):
    """claim-99 不在本稿 ⇒ 受控拒，拒信列出本稿现行号，盘上一行不动。"""
    g, doc_id, _ = _workspace(store)
    before = _documents_bytes(store)

    with pytest.raises(DocumentError) as ei:
        g.revise(doc_id, new_claims=[_claim("凭空一条。", "claim-99")],
                 note="未知号")

    message = str(ei.value)
    assert "unknown_claim_id" in message, message
    assert "claim-99" in message, message
    for i in range(1, 12):
        assert f"claim-{i}" in message, f"拒信没列出现行号 claim-{i}：{message}"
    # 拒信可以解释"新增不给号时 appended_claim_ids 报归一化号"，但不许报"已 append 99"。
    assert "appended=['claim-99']" not in message, message
    assert "已 append 99" not in message, message
    assert _documents_bytes(store) == before, "被拒的修订不许留下半条断言"
    row = _row(store, doc_id)
    assert len(row["claims"]) == 11, row
    assert all(str(c.get("claim_id")) != "claim-99" for c in row["claims"])
    # 也不许出现"被归一化成第 12 条"的静默追加
    assert all(str(c.get("claim_id")) != "claim-12" for c in row["claims"])


# ============================================================ c fixed 必须真改


def test_c_a_finding_targeting_an_unrevised_claim_cannot_be_marked_fixed(store: Store):
    """target=claim-11 的发现，而这一笔只改了 claim-2 ⇒ 拒，发现仍 open。"""
    g, doc_id, _ = _workspace(store)
    finding = RV.record_finding(
        store, doc_id=doc_id, kind="overclaim", target="claim-11",
        message="claim-11 这里说得太满",
        evidence="正文逐字：'这已被证明'", level="error", round_no=1,
    )
    before = _documents_bytes(store)

    with pytest.raises(DocumentError) as ei:
        g.revise(doc_id, fixed_findings=[finding["finding_id"]],
                 new_claims=[_claim("断言 2（改后）。", "claim-2")],
                 note="只改了 claim-2")

    assert "finding_target_not_revised" in str(ei.value), str(ei.value)
    assert _documents_bytes(store) == before, "整笔回滚：claim-2 也不许被改"
    row = next(dict(r) for r in store.rows("review_findings")
               if str(r["finding_id"]) == str(finding["finding_id"]))
    assert row["status"] == "open", row


def test_c2_a_same_id_but_unchanged_claim_is_not_a_revision(store: Store):
    """同号交回一份逐字相同的断言 ⇒ 仍不算"改了那条"，拒。"""
    g, doc_id, doc = _workspace(store)
    finding = RV.record_finding(
        store, doc_id=doc_id, kind="overclaim", target="claim-11",
        message="claim-11 这里说得太满",
        evidence="正文逐字：'这已被证明'", level="error", round_no=1,
    )
    unchanged = dict(doc["claims"][10])

    with pytest.raises(DocumentError) as ei:
        g.revise(doc_id, fixed_findings=[finding["finding_id"]],
                 new_claims=[unchanged], note="只把状态标成 fixed")

    assert "finding_target_not_revised" in str(ei.value), str(ei.value)
    assert "一个字没改" in str(ei.value), str(ei.value)


# ============================================================ d1 反真空（①）


def test_d1_stubbing_the_unknown_id_gate_back_to_old_behaviour_appends(store: Store, monkeypatch):
    """把"未知号"打桩回旧行为 ⇒ b 的场景变成静默追加（b 因此必红）。"""
    g, doc_id, _ = _workspace(store)
    monkeypatch.setattr(RG, "ensure_known_claim_id", lambda **kwargs: None)

    out = g.revise(doc_id, new_claims=[_claim("凭空一条。", "claim-99")],
                   note="反真空：未知号打桩")

    # 旧行为：不拒，按位置归一化成第 12 条（请求号 claim-99 不进盘）
    assert out["replaced_claim_ids"] == [], out
    assert out["appended_claim_ids"] == ["claim-12"], out
    row = _row(store, doc_id)
    assert len(row["claims"]) == 12, row
    assert str(row["claims"][-1]["claim_id"]) == "claim-12"
    assert str(row["claims"][-1]["text"]) == "凭空一条。"


# ============================================================ d2 反真空（②）


def test_d2_stubbing_the_real_change_check_to_pass_lets_c_through(store: Store, monkeypatch):
    """把"必须真改"打桩成恒通过 ⇒ c 的场景被照收（c 因此必红）。"""
    g, doc_id, _ = _workspace(store)
    finding = RV.record_finding(
        store, doc_id=doc_id, kind="overclaim", target="claim-11",
        message="claim-11 这里说得太满",
        evidence="正文逐字：'这已被证明'", level="error", round_no=1,
    )
    monkeypatch.setattr(RG, "ensure_finding_target_revised", lambda **kwargs: None)

    out = g.revise(doc_id, fixed_findings=[finding["finding_id"]],
                   new_claims=[_claim("断言 2（改后）。", "claim-2")],
                   note="反真空：不真改也放行")

    assert out["fixed_findings"] == [finding["finding_id"]], out
    row = next(dict(r) for r in store.rows("review_findings")
               if str(r["finding_id"]) == str(finding["finding_id"]))
    assert row["status"] == "fixed", row
    assert _row(store, doc_id)["claims"][10]["text"] == "断言 11。", "claim-11 确实没改"


# ============================================================ e 归一化号


def test_e_appended_claim_ids_are_the_normalized_ones(store: Store):
    """不给号的新增 ⇒ 回执报归一化后的号（不是请求号，也不是占位句）。"""
    g, doc_id, _ = _workspace(store)

    out = g.revise(doc_id, new_claims=[_claim("新增的一条。")], note="新增")

    assert out["appended_claim_ids"] == ["claim-12"], out
    assert out["replaced_claim_ids"] == [], out
    assert all("自动编号" not in cid for cid in out["appended_claim_ids"]), out
    row = _row(store, doc_id)
    assert str(row["claims"][-1]["claim_id"]) == "claim-12"

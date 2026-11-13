# -*- coding: utf-8 -*-
"""V 的 `verify_proof`：载体是手稿，不是"命题在不在册"（2026-11-08 新契约）。

## 旧契约与被替换的那一条

改前这一组钉的是「命题不在册 ⇒ `checked=False` + `kind='statement_missing'`」。那是
「V 读 `statements` 才知道审谁」时代的判据。业主 2026-11-08 的口径是：

    「V现在只对手稿负责，不该看台账了」

⇒ V 不再知道、也不该声称"这条命题在不在册"。它要知道的是"有没有一份可审的手稿"：
- 没有稿（只给内联正文 / 什么都没给）⇒ 受控拒 `proof_kind=proof_manuscript_required`，
  没审、不落台账行；
- 有稿 ⇒ 照常审（命题有没有被 B 收录是另一件事，由 B 收录时按正文 sha 认领）。

## 这一组钉三件事

1. `999999` + 只给内联正文 ⇒ `checked=False`、`kind='proof_manuscript_required'`、
   没有 verdict、台账文件不存在（这是"没查成"，不是"审过了"）；
2. 负控：`999999`（不在册）+ 一份按号手稿 ⇒ 不走"不在册"那条路，而是进正常审校
   （裸装配下如实回 `judge_not_wired`）—— V 不再因为"没登记"拒审一份稿；
3. 在册命题 + 按号手稿 ⇒ 同样进正常审校（两条路径在"有没有稿"这一格上一致）。
"""
from __future__ import annotations

import pathlib

from agentflow.agent_b import AgentB
from agentflow.agent_v import AgentV
from agentflow.store import Store

from _proof_manuscript_fixture import write_proof_manuscript
from conftest import b_form_gate_ok  # noqa: E402


def _ws(tmp_path: pathlib.Path) -> Store:
    store = Store(tmp_path / "ws")
    store.init()
    return store


def _register_a_statement(store: Store) -> str:
    """登记一条在册的命题（走 B 的动作，出处齐、可追溯）。"""
    with store.tx("literature", actor="test") as tx:
        tx.upsert("literature", {
            "lit_id": "000000", "title": "探针文献", "summary": "s", "year": "2022",
            "doi": "", "type": "J", "path": "", "processed": True, "source_request_ids": [],
            "download": {"status": "ok"},
        })
    b = b_form_gate_ok(AgentB(store, extractor=None, extract_text=None))
    got = b.register_statement(
        origin="external_lit", statement_full="探针命题：若 n≥3 则无解（V 判据用）",
        kind="theorem", source_lit_id="000000", page_range={"start": 1},
        # 2026-11-13（甲）：引文侧登记要落一份 b-稿，而那份稿的 `## 证明` 就是逐字引文
        # ⇒ 这一笔必须带 `proof_text`。
        proof_text="Theorem. For n >= 3 there is no solution (probe).",
        quote_verified=False, quote_reason="探针：引文还没查",
    )
    row = got if isinstance(got, dict) else got.to_dict()
    assert row.get("ok"), row
    return str(row.get("stmt_id") or "")


def _ledger_files(store: Store) -> list[str]:
    root = getattr(store, "root", None)
    d = pathlib.Path(root) / "verifications"
    return sorted(p.name for p in d.glob("*")) if d.is_dir() else []


def test_without_a_manuscript_there_is_no_review_even_for_an_unknown_id(
        tmp_path: pathlib.Path) -> None:
    """载体闸：`999999` + 只给内联正文 ⇒ 没审、无 verdict、台账不留行。

    它不是"这条命题不在册"，而是"这一趟没有可审 / 可签的载体"。
    """
    store = _ws(tmp_path)
    v = AgentV(store)
    out = v.verify_proof("999999", "Proof. 一步。")
    got = out if isinstance(out, dict) else out.to_dict()
    assert got.get("checked") is False, got
    assert got.get("kind") == "proof_manuscript_required", got
    assert not str(got.get("verdict") or "").strip(), f"不该给 verdict：{got}"
    assert _ledger_files(store) == [], "没审却落了台账行"


def test_an_unregistered_manuscript_is_reviewed_like_any_other(
        tmp_path: pathlib.Path) -> None:
    """负控：`999999` 不在册，但给了一份按号手稿 ⇒ 正常审校路径，不是"不在册"。

    V 不再读册 ⇒ "没登记"不是拒信。裸装配（没有判定模型）下如实回 `judge_not_wired`
    —— 那是"没判成"，不是"不在册"，也不是"审过了"。
    """
    store = _ws(tmp_path)
    v = AgentV(store)
    rel = write_proof_manuscript(store.root, "999999", "Proof. 一步。",
                                 statement_full="探针命题（不在册）")
    out = v.verify_proof("999999", "Proof. 一步。", proof_manuscript=rel)
    got = out if isinstance(out, dict) else out.to_dict()
    assert got.get("kind") != "statement_missing", f"不在册又成了一封拒信：{got}"
    assert str(got.get("reason") or "") != "statement_missing", got
    assert got.get("reason") == "judge_not_wired", got
    assert got.get("checked") is False, got
    assert _ledger_files(store) == [], "没判成却落了台账行"


def test_a_registered_statement_takes_the_same_review_path(tmp_path: pathlib.Path) -> None:
    """在册 + 手稿 ⇒ 与上面那条同一条审校路径（"在不在册"不再分叉）。"""
    store = _ws(tmp_path)
    sid = _register_a_statement(store)
    assert sid, "没种出命题"
    v = AgentV(store)
    rel = write_proof_manuscript(store.root, sid, "Proof. 一步。",
                                 statement_full="探针命题：若 n≥3 则无解（V 判据用）")
    out = v.verify_proof(sid, "Proof. 一步。", proof_manuscript=rel)
    got = out if isinstance(out, dict) else out.to_dict()
    assert got.get("kind") != "statement_missing", f"在册命题被误报成不在册：{got}"
    assert got.get("reason") == "judge_not_wired", got
    assert got.get("checked") is False, got
    assert _ledger_files(store) == [], "没判成却落了台账行"

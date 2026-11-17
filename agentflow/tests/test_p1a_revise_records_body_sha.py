# -*- coding: utf-8 -*-
"""甲（2026-11-11）：G 的「改」必须记进台账 —— 轮次 + 正文 sha（a / b / c）。

## 现场

真机（`projects/dct-min4-20261111`）里 G 用 `fs.edit` 改 `out/paper/main.tex`，
而 `documents.review_rounds` 只有 `G.revise` 会 +1 ⇒ 台账上永远是 0 轮、0 条记录；
`content_sha256` 又是"这一版内容（claims）"的规范哈希，不是盘上正文的 sha。

## 落点（为什么不是 documents 加一列）

`schema.Document` 在 FC-27 禁改区（本批不许加列）；`content_sha256` 被签名链与
`doc:@hash` 内部引用钉着（D-44 的现场），把文件 sha 塞进那一格会让
`verify.content_hash_mismatch` 与整条签名链同时失效。所以正文 sha 记在同一条
既有读数上：`documents` 行写盘时 `doc_tools.ARTIFACT_EVENT` 那条 info 事件
（D-44 引入的"中间产物自己的 sha"），由 `doc_tools.body_artifact_of` 定"以哪份文件为准"：

- `kind="paper"` ⇒ `out/paper/main.tex`（H 审的就是它；还没落盘时记一条"不在盘上"）；
- 其它 kind ⇒ 它自己的 `markdown_path`。

`document_artifact_readings` 逐行给出 `body_path` / `body_sha256_recorded` /
`body_sha256_now` / `body_status`（四态 + `unrecorded`）。

## 判据

- a 走 `revise` 改一次 ⇒ `review_rounds=1`、`status=revised`、记下的正文 sha == 盘上 tex 的 sha；
- b 走 `fs.edit` 直接改 tex 一次 ⇒ 行上能看出「sha 变了」（`body_status="changed"`，
  记录值与现值不等；不是 0 轮 0 记录）；
- c 反真空：把记下的值换成 claims hash（`content_sha256`）⇒ a 的等式当场红。
"""

from __future__ import annotations

import hashlib

import pytest

from agentflow import schema as S
from agentflow import signatures as SIG
from agentflow.agent_g import AgentG
from agentflow.store import Store
from agentflow.tools import doc_tools as DT
from agentflow.tools import build_registry as build_tools

from conftest import add_literature, seed_writing_material


def _claim() -> dict:
    return {
        "claim_id": "claim-1",
        "section": "主要结果",
        "text": "谱落在区间内。",
        "evidence_kind": "heuristic",
        "citations": ["lit:0000"],
        "is_negative": False,
        "negation_kind": None,
    }


def _workspace(store: Store) -> tuple[AgentG, str, str]:
    """建一份 paper 稿件 + 盘上的 `out/paper/main.tex`（正文），返回 `(G, doc_id, tex 相对路径)`。"""
    add_literature(store, "0000", title="探针文献", processed=True)
    seed_writing_material(store)
    tex_rel = DT.BODY_TEX_REL
    tex = store.root / tex_rel
    tex.parent.mkdir(parents=True, exist_ok=True)
    tex.write_text("\\documentclass{article}\n\\begin{document}\n谱落在区间内。\n\\end{document}\n",
                   encoding="utf-8")
    g = AgentG(store, workspace_root=store.root)
    built = g.build_document("paper", "甲 探针稿", claims=[_claim()],
                             sections=[{"heading": "主要结果", "body": "谱落在区间内。"}])
    return g, str(built["doc_id"]), tex_rel


def _body_row(store: Store, doc_id: str) -> dict:
    got = DT.document_artifact_readings(store, [doc_id])
    rows = [r for r in got["rows"] if r["doc_id"] == doc_id]
    assert len(rows) == 1, got
    return rows[0]


# ============================================================ a


def test_a_revise_records_rounds_status_and_the_tex_sha(store: Store):
    """走 `revise` 改一次 ⇒ rounds=1、status=revised、记下的正文 sha == 盘上 tex 的 sha。"""
    g, doc_id, tex_rel = _workspace(store)
    rv = g.revise(doc_id, new_claims=[], note="甲：改一版正文")

    assert rv["review_rounds"] == 1, rv
    assert rv["status"] == "revised", rv
    row = next(dict(r) for r in store.rows("documents") if str(r["doc_id"]) == doc_id)
    assert row["review_rounds"] == 1 and row["status"] == "revised", row

    on_disk = hashlib.sha256((store.root / tex_rel).read_bytes()).hexdigest()
    reading = _body_row(store, doc_id)
    assert reading["body_path"] == tex_rel, reading
    # a 的核心等式：记下的值 == 盘上 tex 的字节 sha256
    assert reading["body_sha256_recorded"] == on_disk, reading
    assert reading["body_sha256_now"] == on_disk, reading
    assert reading["body_status"] == "ok", reading
    # 返回值里也带同一份读数（G 自己读得到）
    assert rv["body_path"] == tex_rel and rv["body_sha256"] == on_disk, rv
    # 说明格：`content_sha256` 仍是内容哈希，两个 sha 不是一回事（不是把 claims hash 冒充正文）
    assert rv["content_sha256"] == SIG.content_sha256_of(row) != on_disk


# ============================================================ b


def test_b_a_direct_fs_edit_shows_the_body_sha_changed(store: Store):
    """走 `fs.edit` 直接改 tex ⇒ 行上能看出「正文 sha 变了」（不是 0 轮 0 记录）。"""
    g, doc_id, tex_rel = _workspace(store)
    g.revise(doc_id, note="甲：先把正文登记到台账")
    before = _body_row(store, doc_id)
    assert before["body_status"] == "ok" and before["body_sha256_recorded"], before

    reg = build_tools(store=store, workspace_root=store.root).registry
    # 读后写闸：`fs.edit` 要求这一趟先读过目标（防"静默覆盖一个没看过的文件"）。
    assert reg.call("fs.read", role="G", path=tex_rel).ok
    res = reg.call("fs.edit", role="G", path=tex_rel,
                   old_string="谱落在区间内。", new_string="谱落在闭区间内。",
                   note="甲：G 直接改正文（不走 revise）")
    assert res.ok, res.error

    after = _body_row(store, doc_id)
    on_disk = hashlib.sha256((store.root / tex_rel).read_bytes()).hexdigest()
    assert after["body_sha256_now"] == on_disk, after
    assert after["body_sha256_recorded"] != after["body_sha256_now"], after
    assert after["body_status"] == "changed", after
    assert "内容已变" in after["body_reason"] or "被写过" in after["body_reason"], after
    # 记录本身在（不是 0 轮 0 记录）
    assert after["body_sha256_recorded"], after
    # 轮次不会被 fs.edit 假装 +1（它只留读数，不冒充一次 revise）——
    # 但状态/轮次仍带上一笔 revise 的读数，不是 0/0。
    row = next(dict(r) for r in store.rows("documents") if str(r["doc_id"]) == doc_id)
    assert (row["review_rounds"], row["status"]) == (1, "revised"), row


# ============================================================ c


def test_c_recording_the_claims_hash_instead_turns_a_red(store: Store, monkeypatch):
    """反真空：把记下的正文 sha 写死成 claims hash ⇒ a 的等式当场红。"""
    g, doc_id, tex_rel = _workspace(store)
    real = DT.record_markdown_artifact

    def _claims_hash_instead(tx, doc_id_, rel, absolute, *, body_rel=None, body_absolute=None):
        reading = real(tx, doc_id_, rel, absolute,
                       body_rel=body_rel, body_absolute=body_absolute)
        doc = dict(next(r for r in tx.rows("documents") if str(r.get("doc_id")) == str(doc_id_)))
        # 模拟"把 sha 写死成 claims hash"：同一条事件、正文那一格换成内容哈希
        tx.info(DT.ARTIFACT_EVENT, doc_id=str(doc_id_), path=reading["path"],
                sha256=reading["sha256"], bytes=reading["bytes"], problem="",
                body_path=reading["body_path"],
                body_sha256=SIG.content_sha256_of(doc),
                body_bytes=0, body_problem="反真空夹具：写死成 claims hash")
        return reading

    monkeypatch.setattr(DT, "record_markdown_artifact", _claims_hash_instead)
    assert g.revise(doc_id, note="反真空")["review_rounds"] == 1

    reading = _body_row(store, doc_id)
    on_disk = hashlib.sha256((store.root / tex_rel).read_bytes()).hexdigest()
    assert reading["body_sha256_recorded"] != on_disk, reading
    assert reading["body_sha256_recorded"] == SIG.content_sha256_of(
        next(dict(r) for r in store.rows("documents") if str(r["doc_id"]) == doc_id))

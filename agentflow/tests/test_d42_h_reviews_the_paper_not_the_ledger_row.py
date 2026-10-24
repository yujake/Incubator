# -*- coding: utf-8 -*-
"""D-42：H 的审校对象是论文正文，不是 `documents` 那一行（四条判据）。

业主裁定（唯一权威，逐字）：

    只对论文负责是正确的，documents等都是中间产物

并已确认：

    H 审论文（out/paper/main.tex / pdf），documents 只是它的登记行

改前现场（`src/agentflow/tools/review_tools.py`）：`scan_document` 是纯函数、
`review_document` 只拿到 `documents` 那一行，行号那一格的理由串逐字写着
"审校是纯函数、只读 `documents` 那一行，没有行号来源" —— 于是 H 审的是中间产物，
`review_findings.line` 结构上恒为 `None`。

本文件钉四件事，每条都在改前红（各自的 docstring 里写了"改前为什么红"）：

1. 有 `main.tex` ⇒ 审校输入里有正文且带行号，发现能指到正文的某一行；
   读数里记着"本次审的那一份正文"的 sha256（可追溯）；
2. 没有 `main.tex` 也没有 `main.pdf` ⇒ 报"没有可审的论文"，不 pass；
3. `documents` 行缺失但论文在 ⇒ 仍可审（论文是真身；台账行缺了只记读数）；
4. 反真空：把"读论文"打桩成返回空串 ⇒ 第 2 条必须照样红。

第 2 条的"红"不是"报错"，而是"不许把它读成 accepted"：`checked is False` +
`verdict="unreviewable"` + 一条发现都不落 + `documents` 状态一个字都不动。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from agentflow import papercompile as PC
from agentflow import schema as S
from agentflow.store import Store
from agentflow.tools import review_tools as RV

from conftest import sync_counters, write_paper

TS = "2026-01-01T00:00:00+00:00"

#: 被审正文里那句话（逐字进正文，行号就是按它定位的）。
CLAIM_TEXT = "谱落在区间内。"


def clean_claim(text: str = CLAIM_TEXT) -> dict:
    """一条 schema 合法的断言（引用齐全，所以它本身不产生任何发现）。"""
    return {
        "claim_id": "claim-1",
        "section": "主要结果",
        "text": text,
        "evidence_kind": "cross_check",
        "citations": ["lit:0000"],
        "is_negative": False,
        "negation_kind": None,
        "disclaimer": "数值交叉验证，不构成证明",
    }


def document_row(doc_id: str, claims: list[dict], *, markdown_path: str | None = None) -> dict:
    """构造一行 documents（`content_sha256` 按写侧口径补齐，与 G 写出来的行同形）。"""
    from agentflow import signatures as SIG

    row = S.Document(
        doc_id=doc_id,
        kind="paper",
        title=f"稿件 {doc_id}",
        markdown_path=markdown_path,
        claims=[dict(c) for c in claims],
        status="draft",
        review_rounds=0,
        created_at=TS,
        updated_at=TS,
    ).to_dict()
    row["content_sha256"] = SIG.content_sha256_of(row)
    return row


def inject_raw_document(st: Store, row: dict) -> None:
    """绕过 store 校验直接改盘（"无引用断言"这种坏行只能这样造）。"""
    p = st.data / "documents.json"
    doc = json.loads(p.read_text(encoding="utf-8"))
    doc["rows"] = [r for r in doc["rows"] if r.get("doc_id") != row["doc_id"]] + [row]
    p.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    sync_counters(st)


def no_citation_claim() -> dict:
    """一条审校会抓的断言：引用为空（schema 会拒，所以只能直接改盘造）。"""
    bad = clean_claim()
    bad["citations"] = []
    return bad


def paper_with_the_claim(*, claim_line: int) -> str:
    """造一份正文：`CLAIM_TEXT` 恰好落在第 `claim_line` 行（1 起）。"""
    head = [r"\documentclass{article}", r"\begin{document}"]
    assert claim_line > len(head), "夹具前提：那句话不能落在导言区里"
    body = [""] * (claim_line - len(head) - 1) + [CLAIM_TEXT]
    tail = [r"\end{document}"]
    return "\n".join(head + body + tail) + "\n"


# ============================================================ ① 有正文 ⇒ 带行号


def test_the_review_input_is_the_paper_body_and_findings_point_at_its_lines(store: Store):
    """① 有 `main.tex` ⇒ 审校输入里有正文（带行号），findings 能指到行。

    改前为什么红：`review_document` 只把 `documents` 那一行交给 `scan_document`，
    而那一行里没有正文（`text`/`body`/`markdown` 三个键它都没有）⇒ `_line_of` 拿不到
    正文 ⇒ 每条发现的 `line` 恒为 `None` + 那句"没有行号来源"的理由。本用例断言
    `line == 该句正文在 main.tex 里的行号`、且 `line_unavailable_reason == ""`。

    为什么"指到行"这件事足以证明"审的是论文"：同一句正文我也写进了中间产物
    （`documents/0000.md`，行号刻意不同）。若审校输入仍是中间产物或台账行，
    行号要么是那个不同的号、要么是 `None` —— 只有真的读了 `main.tex` 才可能等于
    这里的 tex 行号。
    """
    claim_line = 7
    tex = paper_with_the_claim(claim_line=claim_line)
    write_paper(store, tex)

    # 中间产物：同一句话在第 3 行（与正文的行号不同）——它是"另一份东西"的证据
    note = store.root / "documents" / "0000.md"
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text("\n".join(["# 中间笔记", "", CLAIM_TEXT, ""]) + "\n", encoding="utf-8")
    inject_raw_document(
        store,
        document_row("0000", [no_citation_claim()], markdown_path="documents/0000.md"),
    )

    res = RV.review_document(store, "0000", dependencies=[])

    # ---- 正文这一路输入真的进来了
    assert res["checked"] is True
    body = res["paper_body"]
    assert body["checked"] is True and body["source"] == "tex"
    assert body["path"] == "out/paper/main.tex"
    assert body["lines"] == tex.count("\n") + 1
    assert body["bytes"] == len(tex.encode("utf-8"))
    assert body["documents_row"] == "present"
    # ---- 本次审的是哪一份正文：sha256 可追溯（盘上那份文件的字节摘要）
    assert body["sha256"] == hashlib.sha256(tex.encode("utf-8")).hexdigest()
    assert body["sha256"] == PC.file_digest(store.root / "out" / "paper" / "main.tex")
    # 读数里不许把正文本身带出来（25 KB 会烧掉上下文），只给读数
    assert "text" not in body

    # ---- findings 能指到正文的某一行（且不是中间产物那一行）
    finding = next(f for f in res["new_findings"] if f["kind"] == "unsupported_claim")
    assert finding["line"] == claim_line, (
        f"发现没有指到正文第 {claim_line} 行（line={finding['line']!r}）——"
        "审校输入里没有那份带行号的正文"
    )
    assert finding["line_unavailable_reason"] == ""
    # 落库的那一行也是同一份读数（不是只在返回值里好看）
    stored = store.rows("review_findings")
    assert [r["line"] for r in stored] == [claim_line], stored
    # 那一句"没有行号来源"必须已经不在理由串里了
    for r in stored:
        assert "没有行号来源" not in str(r.get("line_unavailable_reason") or "")


# ============================================================ ② 没有正文 ⇒ 不 pass


def test_without_a_paper_there_is_nothing_to_review_and_it_does_not_pass(store: Store):
    """② 没有 `main.tex` 也没有 `main.pdf` ⇒ 报"没有可审的论文"，不 pass。

    改前为什么红：改前 `review_document` 根本不知道"正文"这回事，于是一份零发现
    的台账行会被判 `accepted`、`documents.status` 被推成 accepted ——"我们没审到
    任何正文"被写成了"审过、没问题"。

    本用例的台账行是干净的（引用齐全、零发现）：这正是最危险的那种输入 ——
    机器检查全绿，而被审的对象压根不在盘上。
    """
    inject_raw_document(store, document_row("0000", [clean_claim()]))
    assert not (store.root / "out" / "paper").exists(), "夹具前提：论文包里什么都没有"

    res = RV.review_document(store, "0000", dependencies=[])

    assert res["checked"] is False, "没读到正文却报 checked=True —— 那是静默 pass"
    assert res["verdict"] == "unreviewable"
    assert "没有可审的论文" in res["reason"]
    assert res["verdict"] != "accepted" and res["status"] != "accepted"
    assert res["paper_body"]["checked"] is False
    assert res["paper_body"]["path"] == "out/paper/main.tex"
    # 一个字都不写盘：不落发现、状态不动、不签
    assert store.rows("review_findings") == []
    assert store.rows("documents")[0]["status"] == "draft"
    assert res["status_updated"] is False
    assert res["signature"] is None and res["signature_error"] is None
    # 三态：依赖闭合/语义两层都如实报"没查"，不是"查过没问题"
    assert res["dep_check"]["checked"] is False
    assert res["semantic_check"]["checked"] is False
    assert res["coverage"]["claims_reviewed"] == 0


# ============================================================ ③ 台账行缺 ⇒ 照审


def test_a_missing_ledger_row_still_lets_h_review_the_paper(store: Store):
    """③ `documents` 行缺失但有论文 ⇒ 仍可审（论文是真身；台账行缺了只记读数）。

    改前为什么红：`_doc_of` 在行缺失时直接 `ValueError("稿件 … 不存在")`，
    于是"论文在盘上"这件事完全不被看见 —— 审校被一份缺失的登记行挡住了。

    本条不断言"审出了什么发现"（台账行缺了，就没有断言可查 —— 那是事实），
    只断言三件事：① 它真的去审了（`checked is True` 且正文读数在）；
    ② 台账行缺失这件事被记成读数，而不是被吞掉；③ 状态写不成时如实报失败。
    """
    tex = paper_with_the_claim(claim_line=5)
    write_paper(store, tex)

    res = RV.review_document(store, "0007", dependencies=[])

    assert res["checked"] is True
    assert res["paper_body"]["checked"] is True
    assert res["paper_body"]["documents_row"] == "missing"
    assert res["paper_body"]["sha256"] == hashlib.sha256(tex.encode("utf-8")).hexdigest()
    assert "台账行缺失" in res["reason"] and "论文是真身" in res["reason"]
    # 台账行缺了 ⇒ 状态写不成：这一步必须如实报失败，而不是假装成功
    assert res["status_updated"] is False
    assert res["status_error"] and "不存在" in res["status_error"]
    # 也不许因为"没有断言可查"就判 accepted
    assert res["verdict"] != "accepted"


# ============================================================ ④ 反真空


def test_stubbing_the_paper_reader_to_an_empty_body_keeps_the_no_paper_case_red(
    store: Store, monkeypatch: pytest.MonkeyPatch
):
    """④ 反真空：把"读论文"打桩成返回空串 ⇒ 第 ② 条必须照样红。

    为什么需要它：② 的判据是"读不到正文就不许 pass"。若实现按 `checked` 这个布尔
    分支（而 `checked=True` 却给了空正文），② 会在"看起来查成了"的桩下静默变绿 ⇒
    那条判据是真空的。本用例造一个真的有 main.tex 的工作区，再把读取器打桩成
    "查成了、但正文是空串"：实现必须仍然判"没有可审的论文"。
    """
    write_paper(store, paper_with_the_claim(claim_line=5))
    inject_raw_document(store, document_row("0000", [clean_claim()]))
    real = RV.read_paper_body

    def empty_reader(project_root):  # noqa: ARG001 - 打桩：故意不读盘
        return {
            "checked": True,          # 桩说"查成了"
            "source": "tex",
            "path": "out/paper/main.tex",
            "sha256": "",
            "bytes": 0,
            "lines": 0,
            "chars": 0,
            "text": "",               # 但正文是空的
            "reason": "",
        }

    monkeypatch.setattr(RV, "read_paper_body", empty_reader)
    assert RV.read_paper_body is empty_reader, "打桩没生效 ⇒ 本用例会真空通过"
    try:
        res = RV.review_document(store, "0000", dependencies=[])
    finally:
        monkeypatch.setattr(RV, "read_paper_body", real)

    assert res["verdict"] == "unreviewable", (
        "读取器答'查成了但正文是空的'时仍被判成 pass ⇒ ② 的判据是真空的"
    )
    assert res["checked"] is False
    assert store.rows("review_findings") == []
    assert store.rows("documents")[0]["status"] == "draft"

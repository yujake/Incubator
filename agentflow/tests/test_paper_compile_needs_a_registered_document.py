# -*- coding: utf-8 -*-
"""判据：论文包必须先有 `documents` 行，H 才有一行可审；没有行 ⇒ 不编译。

## 业主裁定（2026-11-04，逐字）

> 收工门的 `paper` 那一格判的是"论文正文与回执一致"，而 H 的审校对象是
> `documents` 行；没有行 ⇒ H 永远不审 ⇒ 论文包这一环没有第三方。

真机读数（`projects/paper-rewrite-big`，只读）：`out/paper/main.pdf` 396,066 B /
17 页、`COMPILE-RECEIPT.json` 在，而 `data/documents.json` 0 行、H 从未出场。
改前 `doc.paper_compile` 只要求 `main.tex` + 引擎，从不看 `documents` ⇒ 这条
「有 PDF、没论文行、没第三方」的形态在工具层是合法的。

## 这一份钉的四条

| 判据 | 造什么 | 期望 |
|---|---|---|
| a | 有 `main.tex`、`documents` 0 行 | 受控拒绝 `paper_not_registered`、不落 PDF；拒信点名 `doc.build_document` |
| b | 有 `main.tex`、有一行 `documents`、假引擎 | `ok=True` / `tri=computed`（正控：不许把正常论文路径堵死） |
| c | H 读那一行 | `doc.list_documents` 在 H 的工具面上能看到这个 `doc_id`（端到端：论文行真的进了审校面） |
| d | 反真空：把 `_paper_documents_count` 打桩成 `(1, "")`（无行）/ `(0, "")`（有行） | 同一现场的红绿必须跟着这一处判据翻转，而不是靠"没有行"这个事实本身 |

`papercompile.compile_paper` 是纯编译器（判据夹具直调它，不建表）—— 门在工具层
`doc.paper_compile`（`tools/doc_tools.py::_paper_compile`），与 `doc.write_mapping`
的成文门同一条纪律。
"""
from __future__ import annotations

import json
import pathlib
import sys

import pytest
import paperfixture as FX

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agentflow import schema as S
from agentflow.store import Store
from agentflow.tools import build_registry
from agentflow.tools import doc_tools as DT

TS = "2026-11-04T15:00:00+08:00"
KIND = "paper_not_registered"


def _document_row(doc_id: str = "000000") -> dict:
    """一份最小但读得动的 `documents` 行（H 的审校对象）。"""
    return {
        "doc_id": doc_id, "kind": "note", "title": "论文正文的稿件行",
        "markdown_path": f"documents/{doc_id}.md",
        "sections": [{"heading": "结论", "body": "正文结论。"}],
        "claims": [{"claim_id": "claim-1", "text": "正文结论。",
                    "citations": ["stmt:000000"], "evidence_kind": "heuristic",
                    "section": "结论"}],
        "open_problems": [], "status": "accepted", "review_rounds": 0,
        "review_verdict": "成立", "created_at": TS, "created_by": "agent-G",
    }


def _dump(path: pathlib.Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def _ws(tmp_path: pathlib.Path, *, documents: int = 0) -> tuple[pathlib.Path, object]:
    """工作区 + 真注册表；`documents` 行数由这一格决定。"""
    root = tmp_path / "ws"
    _dump(root / "data" / str(S.TABLES["documents"]["file"]),
          {"schema_version": 2,
           "rows": [_document_row(S.format_id(i)) for i in range(documents)]})
    store = Store(root)
    store.init()
    reg = build_registry(store=store, workspace_root=root).registry
    return root, reg


@pytest.fixture()
def engine(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    """假 LaTeX 引擎（不依赖本机装没装）。"""
    got = FX.fake_engine(tmp_path / "_engine")
    monkeypatch.setenv("AGENTFLOW_LATEX_ENGINE", str(got))
    return got


def _call(reg, tool: str, **params):
    return reg.call(tool, role="G", **params)


# ============================================================ a 没有行 ⇒ 不编译
def test_a_a_paper_without_a_documents_row_is_not_compiled(tmp_path, engine):
    """a：有正文、`documents` 0 行 ⇒ 受控拒绝 `paper_not_registered`、不落 PDF。"""
    root, reg = _ws(tmp_path, documents=0)
    FX.write_paper(root)

    res = _call(reg, "doc.paper_compile", project=".")
    assert res.ok is False, (res.error, res.meta)
    assert res.meta.get("kind") == KIND, (res.error, res.meta)
    assert "doc.build_document" in str(res.error), res.error
    assert not (root / "out" / "paper" / "main.pdf").exists(), "被拒了却仍写出 PDF"


# ============================================================ b 有行 ⇒ 正常编
def test_b_a_registered_paper_still_compiles(tmp_path, engine):
    """b（正控）：有一行 `documents`、正文在、假引擎在 ⇒ `computed`。"""
    root, reg = _ws(tmp_path, documents=1)
    FX.write_paper(root)

    res = _call(reg, "doc.paper_compile", project=".")
    assert res.ok is True, (res.error, res.meta)
    assert res.data.get("tri") == "computed", res.data
    assert (root / "out" / "paper" / "main.pdf").is_file()


# ============================================================ c H 读得到那一行
def test_c_h_can_read_the_documents_row(tmp_path):
    """c（端到端）：H 的工具面上 `doc.list_documents` 能看到这个 `doc_id`。"""
    _root, reg = _ws(tmp_path, documents=1)
    res = reg.call("doc.list_documents", role="H")
    assert res.ok is True, (res.error, res.meta)
    got = res.data if isinstance(res.data, dict) else {"rows": res.data}
    rows = got.get("rows") or got.get("documents") or []
    ids = {str(r.get("doc_id") or "") for r in rows if isinstance(r, dict)}
    assert "000000" in ids, ("H 的只读列举里没有那一行 ⇒ 论文行没有进审校面", got)


# ============================================================ d 反真空
def test_d_the_gate_flips_with_its_one_judgement(monkeypatch, tmp_path, engine):
    """d（反真空）：这一格的红绿必须由 `_paper_documents_count` 一处判据决定。"""
    # 无行，但把判据打桩成 1 行 ⇒ 编译放行（证明 a 的红来自这一处）。
    root, reg = _ws(tmp_path / "one", documents=0)
    FX.write_paper(root)
    monkeypatch.setattr(DT, "_paper_documents_count", lambda workspace, store: (1, ""))
    passed = _call(reg, "doc.paper_compile", project=".")
    assert passed.ok is True, (passed.error, passed.meta)

    # 有行，但把判据打桩成 0 行 ⇒ 拒绝（同一处判据翻转，红绿跟着翻）。
    root2, reg2 = _ws(tmp_path / "two", documents=1)
    FX.write_paper(root2)
    monkeypatch.setattr(DT, "_paper_documents_count", lambda workspace, store: (0, ""))
    refused = _call(reg2, "doc.paper_compile", project=".")
    assert refused.ok is False and refused.meta.get("kind") == KIND, (refused.error, refused.meta)

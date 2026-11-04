# -*- coding: utf-8 -*-
"""判据：盘上有 PDF / 正文、台账里一行 `documents` 都没有 ⇒ 不许当成"论文已入库"。

## 真机读数（2026-11-04 `projects/paper-rewrite-big`）

- `out/paper/main.pdf` 17 页 / 396,066 B / 14:33:29（`COMPILE-RECEIPT.json` 也在）；
- `data/documents.json` 0 行；H 从未出场；收工门没跑。

追下去是一处读数轴接错了：`closing.mapping_absence_reading` 判"已成稿"用的是
`documents` 有没有行（`doc.build_document` 是那一张表唯一的建行入口）。于是
"论文包真的在盘上、而 `documents` 0 行"这一形态落进"还没有成稿 ⇒ 不适用"，
D-38 的 `mapping_not_written` 那条 blocker 永远不会触发 —— 盘上有论文、
门说"不适用"。

## 这一份钉的三条

| 判据 | 造什么 | 期望 |
|---|---|---|
| a | statements>=1、documents 0 行、`out/paper/main.tex` 与 `main.pdf` 在盘上、没有 `MAPPING.json` | `mapping_absence_reading.missing=True`（论文包在盘上就是"已成稿"） |
| b | 同上，但 `MAPPING.json` 在盘上 | `missing=False`（有表就不报缺） |
| c | statements>=1、documents 0 行、没有论文包 | `missing=False` 且 `paper_package=False`（不适用）—— 负控，不许把早期阶段全判红 |

`doc.paper_compile` 本身不拦"没有 documents 行"：论文的交付面是
`main.tex` + PDF + `MAPPING.json` + 验收表（`documents` 是研究手稿那一档，
ROLE-GUIDE 的交付物第 ①/② 两类），编译不需要先建 `documents` 行。这一份只钉
"收工门不许把那份 PDF 读成论文已入库"。
"""
from __future__ import annotations

import json
import pathlib
import sys

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agentflow import closing as CL
from agentflow import schema as S
from agentflow.store import Store

TS = "2026-11-04T15:00:00+08:00"
CODE = "mapping_not_written"


def _dump(path: pathlib.Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def _statement_row(stmt_id: str = "000000") -> dict:
    return {
        "stmt_id": stmt_id, "origin": "own_result", "kind": "conjecture",
        "statement_full": "对任意 n >= 0：1^3 + ... + n^3 = (n(n+1)/2)^2。",
        "statement_text": "sum-of-cubes", "proof_text": "归纳：基例 0，归纳步提公因式。",
        "quote_reason": "我方自产命题", "evidence_kind": "heuristic",
        "status": "active", "bits": {}, "created_at": TS, "created_by": "test",
    }


def _ws(root: pathlib.Path) -> pathlib.Path:
    """statements 1 行、documents 0 行 的工作区。"""
    root = pathlib.Path(root)
    Store(root).init(force=True)
    _dump(root / "data" / str(S.TABLES["statements"]["file"]),
          {"schema_version": 2, "rows": [_statement_row()]})
    _dump(root / "data" / str(S.TABLES["documents"]["file"]),
          {"schema_version": 2, "rows": []})
    return root


def _paper_package(root: pathlib.Path, *, mapping: bool = False,
                   tex: bool = True) -> None:
    """论文包：main.tex + main.pdf（+ 可选 MAPPING.json）。"""
    pkg = root / "out" / "paper"
    pkg.mkdir(parents=True, exist_ok=True)
    if tex:
        (pkg / "main.tex").write_text(
            "\\documentclass{article}\\begin{document}x\\end{document}\n", encoding="utf-8")
    (pkg / "main.pdf").write_bytes(b"%PDF-1.4 probe\n")
    if mapping:
        (pkg / "MAPPING.json").write_text(json.dumps({"rows": []}), encoding="utf-8")


# ============================================================ a 有论文包、没表
def test_a_a_pdf_without_documents_rows_still_needs_a_mapping(tmp_path):
    """a：论文包在盘上（PDF 已编出）、documents 0 行、没有 MAPPING ⇒ 缺表。"""
    root = _ws(tmp_path / "ws")
    _paper_package(root)

    got = CL.mapping_absence_reading(Store(root), root)
    assert got["checked"] is True, got
    assert got["paper_package"] is True, got
    assert got["documents"] == 0, got
    assert got["missing"] is True, (
        "盘上有论文包（main.pdf）、没有 MAPPING.json，而这一档说「不适用」"
        f"⇒ '有 PDF 但论文没入库'在收工门上没有读数：{got}")
    assert "论文包" in str(got["reason"]), got["reason"]


def test_a2_the_gate_raises_the_mapping_blocker_for_a_pdf_only_paper(tmp_path):
    """a2：只剩 `main.pdf`（正文都被人删了）、documents 0 行、没有 MAPPING ⇒ 仍拦门。

    这一档是 `mapping_package_missing` 的盲区：那一条以"正文在不在"为轴，
    `main.tex` 不在时它判 unknown（不适用），而盘上明明有一份编出来的 PDF。
    改前 `mapping_absence_reading` 又因为 documents 0 行判"不适用"⇒ 两条都沉默。
    现在理由码是 D-38 的 `mapping_not_written`（它补的就是那个盲区）。
    """
    root = _ws(tmp_path / "ws")
    _paper_package(root, tex=False)

    rep = CL.check_closing(Store(root), project_dir=str(root), checks=("paper",))
    codes = [str(f.code) for f in rep.findings if f.check == "mapping"]
    assert CODE in codes, (codes, rep.to_dict())
    assert rep.machine_pass is False, rep.to_dict()


# ============================================================ b 有表就不报缺
def test_b_a_mapping_on_disk_is_not_reported_missing(tmp_path):
    """b（正控）：论文包在盘上、MAPPING.json 也在 ⇒ 不报缺。"""
    root = _ws(tmp_path / "ws")
    _paper_package(root, mapping=True)
    got = CL.mapping_absence_reading(Store(root), root)
    assert got["checked"] is True, got
    assert got["paper_package"] is True, got
    assert got["missing"] is False, got


# ============================================================ c 没有论文包仍不适用
def test_c_without_a_paper_package_the_cell_is_not_applicable(tmp_path):
    """c（负控）：documents 0 行、也没有论文包 ⇒ 不适用（不许把早期阶段全判红）。"""
    root = _ws(tmp_path / "ws")
    got = CL.mapping_absence_reading(Store(root), root)
    assert got["checked"] is True, got
    assert got["paper_package"] is False, got
    assert got["missing"] is False, got
    assert "不适用" in str(got["reason"]), got["reason"]

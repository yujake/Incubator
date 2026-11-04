# -*- coding: utf-8 -*-
"""H 的审核轴：只有「成立 / 有毛病」；没查成不是一条裁决（业主 2026-10-30 裁定）。

```text
「不应该有『看不出来』，『看不出错』就是没毛病」
```

正确三分：成立 / 有毛病 / 没查成（`checked=False` + 理由，台账不留行）。
⇒ 「看不出来」不是第三个结论。政策（`specs/h.py:133`）与数据层此前把它当成一个
可写可存的裁决，于是「没查成」被记成了一条裁决 —— 这是最贵的一种折平。

## 这一份守什么（a–e）

| # | 它守什么 | 改前为什么红 |
|---|---|---|
| a | 没查成（依赖闭合没查）⇒ `documents.review_verdict` 是空串，读侧 `checked=False`，盘上没有新裁决 | `_set_doc_status` 从 status 推裁决：`in_review` ⇒ 「有毛病」—— 没查被写成了一条裁决 |
| b | `schema.REVIEW_VERDICTS` 里没有「看不出来」；把旧值塞进新行 ⇒ 受控拒 | 旧值在词表里 ⇒ 新行照收 |
| c | 带 `review_verdict="看不出来"` 的旧行读成「没查成」（带 legacy 读数），不是「成立」也不是「有毛病」；不计入 `reviewed_documents` | 旧值被读成一条真裁决（`reviewed_documents` 还数它） |
| d | 反真空：把 c 的兼容映射摘掉 ⇒ c 必须红（旧行读成空裁决而不带任何「没查成」读数） | 兼容映射不存在 |
| e | `reviewed_documents` 认两态裁决；`accepted_documents` 只认「成立」 | 旧值混进 `reviewed_documents` |

反真空：a 的模型面走真的 `review_document`（不是拼一个 dict）；b 同时核词表与
`Document.validate` / store 提交两处受控拒；c 的旧行是绕过 store 校验直接写盘的
（写侧已经收不了那一格）；d 用 monkeypatch 摘掉映射本体。

零真模型调用，零网络。
"""
from __future__ import annotations

import json
import pathlib
import sys

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import pytest  # noqa: E402

from agentflow import closing as CL  # noqa: E402
from agentflow import schema as S  # noqa: E402
from agentflow import signatures as SIG  # noqa: E402
from agentflow.store import Store  # noqa: E402
from agentflow.tools import review_tools as RV  # noqa: E402

TS = "2026-11-04T00:00:00+08:00"
CLAIM_TEXT = "谱落在区间内。"
DISCLAIMER = "数值交叉验证，不构成证明"


# ------------------------------------------------------------------ 夹具


def _claim() -> dict:
    """一条机械审校判不出 error / warning 的断言（与 `test_agent_h.clean_claim` 同形）。"""
    return {
        "claim_id": "claim-1",
        "section": "主要结果",
        "text": CLAIM_TEXT,
        "evidence_kind": "cross_check",
        "citations": ["lit:0000"],
        "is_negative": False,
        "negation_kind": None,
        "disclaimer": DISCLAIMER,
    }


def _paper() -> str:
    return "\n".join(
        [
            r"\documentclass{article}",
            r"\begin{document}",
            r"\section{主要结果}",
            CLAIM_TEXT,
            r"\end{document}",
            "",
        ]
    )


def _doc_row(doc_id: str, *, status: str = "draft") -> dict:
    row = S.Document(
        doc_id=doc_id,
        kind="paper",
        title=f"稿件 {doc_id}",
        markdown_path=None,
        claims=[_claim()],
        status=status,
        review_rounds=0,
        created_at=TS,
        updated_at=TS,
    ).to_dict()
    if not row.get("content_sha256"):
        row["content_sha256"] = SIG.content_sha256_of(row)
    return row


def _project(root: pathlib.Path) -> Store:
    """造一个最小工作区：有一份可审的论文正文 + 空台账。"""
    out = root / "out" / "paper"
    out.mkdir(parents=True, exist_ok=True)
    (out / "main.tex").write_text(_paper(), encoding="utf-8")
    st = Store(root)
    st.init(force=True)
    return st


def _seed_document(st: Store, doc_id: str = "0000") -> dict:
    row = _doc_row(doc_id)
    S.row_from_dict("documents", row).validate()
    with st.tx("documents", actor="test", note="fixture") as tx:
        tx.upsert("documents", row)
    return row


def _inject_raw(st: Store, row: dict) -> None:
    """绕过 store 校验直接改盘：旧行（写侧已经收不了那一格）只能这样造。"""
    p = st.data / "documents.json"
    doc = json.loads(p.read_text(encoding="utf-8"))
    doc["rows"] = [r for r in doc["rows"] if r.get("doc_id") != row["doc_id"]] + [row]
    p.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_rows(st: Store, rows: list[dict]) -> None:
    p = st.data / "documents.json"
    doc = json.loads(p.read_text(encoding="utf-8"))
    doc["rows"] = list(rows)
    p.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _count(st: Store, kind: str) -> tuple[int, dict]:
    return CL._leg_reading(st, kind, st.root)


# ------------------------------------------------------------------ a


def test_a_a_review_that_could_not_check_writes_no_verdict(tmp_path: pathlib.Path) -> None:
    """a：没查成（依赖闭合没查）⇒ 裁决空串 + 读侧 checked=False，盘上不留裁决。

    改前：`_set_doc_status` 按 status 推裁决（`in_review` ⇒ 「有毛病」），
    把「这一维没查」折成了一条真裁决。
    """
    st = _project(tmp_path)
    _seed_document(st)

    res = RV.review_document(st, "0000", dependencies=None)
    assert res["verdict"] == "unverified", res["verdict"]
    assert "没查" in res["reason"], res["reason"]

    row = st.rows("documents")[0]
    assert row.get("review_verdict") == "", (
        f"没查成却落了裁决：review_verdict={row.get('review_verdict')!r}"
    )
    reading = S.read_review_verdict(row)
    assert reading["checked"] is False, reading
    assert reading["verdict"] == "", reading
    assert reading["legacy"] is False, reading


# ------------------------------------------------------------------ b


def test_b_the_legacy_word_is_out_of_the_vocabulary_and_rejected_on_write(
    tmp_path: pathlib.Path,
) -> None:
    """b：词表里没有「看不出来」；把旧值硬塞进新行 ⇒ 受控拒（字段层 + 提交层）。"""
    assert "看不出来" not in S.REVIEW_VERDICTS, S.REVIEW_VERDICTS
    assert S.REVIEW_VERDICTS == ("", "成立", "有毛病"), S.REVIEW_VERDICTS

    st = _project(tmp_path)
    row = _doc_row("0000")
    row["review_verdict"] = "看不出来"

    with pytest.raises(ValueError) as caught:
        S.row_from_dict("documents", row).validate()
    assert "review_verdict" in str(caught.value), caught.value

    before = (st.data / "documents.json").read_text(encoding="utf-8")
    with pytest.raises(ValueError):
        with st.tx("documents", actor="test", note="legacy write") as tx:
            tx.upsert("documents", row)
    assert (st.data / "documents.json").read_text(encoding="utf-8") == before, (
        "受控拒之后盘上必须一个字都没变"
    )


# ------------------------------------------------------------------ c


def test_c_a_legacy_row_reads_as_unchecked_not_as_hold(tmp_path: pathlib.Path) -> None:
    """c（要害）：旧行 `review_verdict="看不出来"` 读成「没查成」，不是「成立」/「有毛病」。

    旧行只能绕过 store 校验直接写盘（写侧已经收不了那一格）。
    """
    st = _project(tmp_path)
    _seed_document(st)
    legacy = dict(st.rows("documents")[0])
    legacy["review_verdict"] = "看不出来"
    legacy["reviewed_at"] = TS
    legacy["reviewed_by"] = "agent-H"
    legacy["status"] = "in_review"
    _inject_raw(st, legacy)

    st2 = Store(st.root)
    row = st2.rows("documents")[0]
    reading = S.read_review_verdict(row)
    assert reading["raw"] == "看不出来", reading
    assert reading["legacy"] is True, reading
    assert reading["checked"] is False, reading
    assert reading["verdict"] == "", reading
    assert reading["verdict"] not in ("成立", "有毛病"), reading
    assert "旧数据" in reading["reason"] and "没查成" in reading["reason"], reading

    reviewed, detail = _count(st2, "reviewed_documents")
    assert reviewed == 0, f"旧值被算成「审过」了：{reviewed}；detail={detail}"
    assert [r["doc_id"] for r in detail.get("legacy_unchecked") or []] == ["0000"], detail

    accepted, _ = _count(st2, "accepted_documents")
    assert accepted == 0, "旧值绝不许折成「成立」"


# ------------------------------------------------------------------ d


def test_d_the_legacy_mapping_is_load_bearing(monkeypatch: pytest.MonkeyPatch) -> None:
    """d（反真空）：摘掉 c 的兼容映射 ⇒ 旧行读成空裁决且不带任何「没查成」读数。

    这条钉的是「兼容映射不是装饰」：删了它，c 的 `legacy is True` / 「旧数据」断言必红。
    """
    row = {"review_verdict": "看不出来"}
    monkeypatch.setattr(S, "REVIEW_LEGACY_VERDICTS", ())
    reading = S.read_review_verdict(row)
    assert reading["verdict"] == "", reading
    assert reading["legacy"] is False, reading
    assert "旧数据" not in reading["reason"], reading
    assert reading["checked"] is False, reading


# ------------------------------------------------------------------ e


def test_e_reviewed_counts_both_states_and_accepted_counts_only_hold(
    tmp_path: pathlib.Path,
) -> None:
    """e：`reviewed_documents` 认两态裁决；`accepted_documents` 只认「成立」。"""
    st = _project(tmp_path)
    rows: list[dict] = []
    for doc_id, verdict in (("0000", "成立"), ("0001", "有毛病"),
                            ("0002", ""), ("0003", "看不出来")):
        row = _doc_row(doc_id)
        row["review_verdict"] = verdict
        if verdict:
            row["reviewed_at"] = TS
            row["reviewed_by"] = "agent-H"
        rows.append(row)
    _write_rows(st, rows)
    st2 = Store(st.root)

    reviewed, detail = _count(st2, "reviewed_documents")
    assert reviewed == 2, f"审过 = 成立 + 有毛病；detail={detail}"
    assert {r["doc_id"] for r in detail["documents"]} == {"0000", "0001"}, detail

    accepted, _ = _count(st2, "accepted_documents")
    assert accepted == 1, "通过只认「成立」"

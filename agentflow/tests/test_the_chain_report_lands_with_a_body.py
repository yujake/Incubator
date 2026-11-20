# -*- coding: utf-8 -*-
"""`proof_chain` 的报告要落得进 `analysis_reports`，而「没有正文的报告」仍然不许登记。

## 现场（改前）

`agent_c/core.py::_report` 在 `ok=True` 时「产出即登记」，`proof_chain` 的成功分支却从不
传 `markdown=`；`AnalysisReport.persist` 在 `agent_c/_support.py:218` 拒收空正文 ⇒
同一族五档报告里只有这一档「产出即失败」：

```
ValueError: markdown 为空，拒绝登记一个没有内容的报告。
tests/test_each_role_queries_the_statement_ledger.py::test_c_takes_the_chain_target_by_number…
tests/test_the_three_half_breaks_are_fixed.py ① 的正控与负控（两条）
```

## 判据（a 改前红 / b 正控 / c 反真空）

- a：`proof_chain` 的成功报告带着正文落库，且能从盘上读回（登记行 + `reports/<id>-proof_chain.md`
  的字节与返回对象逐字节一致）；两条成功分支各一条用例（已经是根 / 走到根）。
- b：正控，闸没被关掉 —— 五档 `REPORT_KINDS` 逐档拿空正文去登记都必须抛 `markdown 为空`，
  且一行都不许落；`proof_chain` 也在这一档里（它并不是「可以只带结构」的例外）。
- c：反真空 —— 把 a 依赖的那处正文渲染打桩成空串，a 的形态必须当场变红（`persist` 拒登记、
  台账 0 行）。否则 a 量的就不是「正文渲染接上了」。

闸为什么不能被关掉：登记行是 D 的第一入口，`markdown_path` 是它照着打开的那一份正文；
一份 0 字节的正文会让「这份报告存在」变成一句查不出来的假话（`verify.py` 只核文件在不在）。
"""
from __future__ import annotations

import pathlib
import sys

import pytest

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from conftest import seed_statement_row  # noqa: E402
from agentflow import schema as S  # noqa: E402
from agentflow.agent_c import AgentC, AnalysisReport  # noqa: E402
from agentflow.agent_c import proof_chain as PC  # noqa: E402
from agentflow.store import Store  # noqa: E402


def _store(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _root(st: Store, sid: str = "0001") -> None:
    """一条无依赖、有 proof 证据的命题 ⇒ 链的「已经是根」那一支。"""
    seed_statement_row(
        st, stmt_id=sid, label="A⇒B", statement_full="若 A 成立，则 B 成立。",
        kind="theorem", evidence_kind="proof", proof_text="Proof. 检查器核过。")


def _dep(st: Store, did: str, used_by: str, *, stmt: str = "",
         group: int = 1) -> None:
    row = S.Dependency(dep_id=did, used_by=used_by, kind="theorem", label="前提",
                       status="closed", status_reason="", source_stmt_id=stmt or None,
                       source_experiment_id=None, source_lit_id=None,
                       path_group=group, created_at="2026-11-20T00:00:00+08:00")
    row.validate()
    with st.tx("dependencies", actor="test") as tx:
        tx.upsert("dependencies", row.to_dict(), note="dep")


def _the_chain_world(st: Store) -> None:
    """0001（要证）依赖 0002（无前提自证）⇒ 链走到根那一支（带候选路径表）。"""
    seed_statement_row(
        st, stmt_id="0001", label="A⇒B", statement_full="若 A 成立，则 B 成立。",
        kind="theorem", proof_text="Proof. 由命题 0002 推出。")
    seed_statement_row(
        st, stmt_id="0002", label="C⇒D", statement_full="若 C 成立，则 D 成立。",
        kind="theorem", evidence_kind="proof", proof_text="Proof. 检查器核过。")
    _dep(st, "0001", "stmt:0001", stmt="0002")


def _landed_rows(st: Store, report_id: str) -> list[dict]:
    return [dict(r) for r in st.rows("analysis_reports")
            if str(r.get("report_id") or "") == report_id]


def _assert_landed_and_readable(st: Store, rep) -> str:
    """a 的断言本体（两条成功分支共用）：登记行在、正文在盘上、两者与返回对象一致。"""
    assert rep.ok is True, (rep.error, rep.summary)
    assert rep.report_id, "成功报告没有 report_id（产出没有登记）"
    rows = _landed_rows(st, rep.report_id)
    assert len(rows) == 1, f"登记行数不对：{rows}"
    row = rows[0]
    assert row["kind"] == "proof_chain", row
    assert row["markdown_path"] == rep.markdown_path, (row, rep.markdown_path)
    assert row["markdown_path"] == f"reports/{rep.report_id}-proof_chain.md", row
    md_file = pathlib.Path(st.root) / str(row["markdown_path"])
    assert md_file.is_file(), f"登记行指向的正文文件不在盘上：{md_file}"
    text = md_file.read_text(encoding="utf-8")
    assert text == rep.markdown, "盘上的正文与返回对象不是同一份"
    assert text.strip(), "正文是空的 —— 这正是 persist() 要拒的那一种"
    assert "## 目标" in text and "## 结论" in text, text[:400]
    assert row["payload"]["target"] == rep.payload["target"], row["payload"]
    return text


# ===================================================== a：成功报告落库且读得回


def test_a_the_root_chain_report_lands_with_a_readable_body(tmp_path: pathlib.Path) -> None:
    """已经发成的根（没有依赖边）也必须有正文：这是改前被拒的那两支之一。"""
    st = _store(tmp_path)
    _root(st)
    rep = AgentC(st).proof_chain("stmt:0001")
    text = _assert_landed_and_readable(st, rep)
    # 正文确实写的是这一趟的读数（不是一句通用的占位）：
    assert "已经是根" in text or "闭合" in text, text[:400]
    assert "`0001`" in text, text[:400]


def test_a_the_reached_chain_report_lands_with_its_paths(tmp_path: pathlib.Path) -> None:
    """走到根那一支：正文里要有候选路径表与逐组明细，行的 payload 带同一份读数。"""
    st = _store(tmp_path)
    _the_chain_world(st)
    rep = AgentC(st).proof_chain("0001")
    text = _assert_landed_and_readable(st, rep)
    assert "候选路径（每条一行" in text, text[:600]
    assert "逐组明细" in text, text[:600]
    assert "走到根（closed）：是" in text, text[:600]
    rows = _landed_rows(st, rep.report_id)
    assert rows[0]["payload"]["closed"] is True, rows[0]["payload"]
    assert rows[0]["payload"]["groups_total"] == 1, rows[0]["payload"]
    # 正文是读数现算的：同一份数据连跑两次必须逐字节一致（不许带时间戳或随机序）。
    again = AgentC(st).proof_chain("0001")
    assert again.markdown == rep.markdown, "两次运行的正文不一致"


# ===================================================== b：正控 —— 闸没被关掉


@pytest.mark.parametrize("kind", S.REPORT_KINDS)
def test_b_a_report_without_a_body_is_still_refused(
        tmp_path: pathlib.Path, kind: str) -> None:
    """五档报告（含 proof_chain）拿空正文去登记：逐档都必须被拒，且一行都不落。"""
    st = _store(tmp_path)
    empty = AnalysisReport(kind=kind, summary="有摘要", payload={"k": 1},
                           markdown="   \n\t")
    empty._store = st  # type: ignore[attr-defined]
    with pytest.raises(ValueError, match="markdown 为空"):
        empty.persist()
    assert st.rows("analysis_reports") == [], "空正文的报告被登记了 ⇒ 闸被关掉了"


# ===================================================== c：反真空


def test_c_stubbing_the_body_renderer_makes_a_red(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """把正文渲染打桩成空串 ⇒ a 的形态当场变红（拒登记 + 台账 0 行）。"""
    st = _store(tmp_path)
    _root(st)
    monkeypatch.setattr(PC._ProofChain, "_md_chain", lambda *_a, **_k: "")
    with pytest.raises(ValueError, match="markdown 为空"):
        AgentC(st).proof_chain("0001")
    assert st.rows("analysis_reports") == [], "正文渲染被打了桩，报告却还是落了库"

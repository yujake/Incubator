# -*- coding: utf-8 -*-
"""块丙：D 的写集按实际写过的表列全（业主 2026-11-08）。

业主原话（逐字）：

> 「D对命题台账只有只读权限，D向B提交要登记的命题时都是有证明或数值实验的
>   （即E和F的成果）…B侧做好适配」

## 判据

| # | 判据 |
|---|---|
| a | 跑一趟 D 的两个写动作（`propose_question` / `submit_gaps`），拿 `events.jsonl` 里 `(op="upsert"/"delete", table)` 现算"真的写过的表"，与 `WRITE_SETS["D"]` 逐表相等 |
| b | policy 里逐字有「命题台账由 B 写、D 只读」 |
| c | `statements` / `dependencies` 不在 D 的写集里（哪怕这一趟经由 B 写了 statements —— 那是 B 写的，不是 D） |
| d | 报告落点是文件：`write_report` 之后 `analysis_reports` 一行都不多（它是 C 的表） |
| e | `conjectures` 也不在 D 的写集里（业主 2026-11-13 裁定甲：D 不该立项临时命题；台账的唯一写点在产出侧 —— 它在 E / F / B 的写集里） |

反真空读数在 a 的内部：`actual` 是从事件流现算的，不是照抄声明；少一张表会让 a 当场红。
"""

from __future__ import annotations

import pathlib
import sys

import pytest

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agentflow import capabilities as CAP  # noqa: E402
from agentflow import schema as S  # noqa: E402
from agentflow import specs  # noqa: E402
from agentflow.agent_d import AgentD  # noqa: E402
from agentflow.store import Store  # noqa: E402


def _run_d(tmp_path: pathlib.Path) -> tuple[Store, AgentD]:
    st = Store(tmp_path / "ws")
    st.init()
    d = AgentD(st)
    q = d.propose_question(question="当 n 增大时，计数 A(n) 是否单调？", kind="gap")
    assert q.get("ok") is True, q
    qid = str(q.get("question_id") or "")
    gaps = d.submit_gaps(qid)
    assert gaps, f"这一趟没有提交检索请求 ⇒ 写集少一张表就量不到：{gaps}"
    return st, d


def _tables_written(store: Store) -> set[str]:
    out: set[str] = set()
    for event in store.read_events():
        if not isinstance(event, dict):
            continue
        if str(event.get("op") or "") not in ("upsert", "delete"):
            continue
        table = str(event.get("table") or "")
        if table in S.TABLES:
            out.add(table)
    return out


# ============================================================ a 声明 = 实际
def test_a_the_declared_write_set_equals_the_tables_d_actually_writes(
        tmp_path: pathlib.Path) -> None:
    """a：跑一趟 ⇒ 事件流里真的写过的表集合 == `WRITE_SETS["D"]`（逐表相等）。"""
    st, _d = _run_d(tmp_path)
    actual = _tables_written(st)
    declared = {str(t) for t in (CAP.WRITE_SETS.get("D") or ())}
    assert actual == declared, (
        "写集声明与实际写过的表对不上：\n"
        f"  实际（events.jsonl）：{sorted(actual)}\n"
        f"  声明（WRITE_SETS['D']）：{sorted(declared)}\n"
        f"  差：实际多 {sorted(actual - declared)} / 声明多 {sorted(declared - actual)}")
    assert actual == {"research_questions", "search_requests"}, actual


# ============================================================ b policy 逐字
def test_b_the_policy_says_the_ledger_is_written_by_b_and_read_only_for_d() -> None:
    """b：policy 里逐字有「命题台账由 B 写、D 只读」。"""
    policy = "\n".join(specs.builtin_specs()["D"].brief.policy)
    assert "命题台账由 B 写、D 只读" in policy, policy[-3000:]


# ============================================================ c statements 不在写集
def test_c_statements_and_dependencies_are_not_in_d_write_set() -> None:
    """c：D 对命题台账 / 依赖面只读 —— 写集里不许有那两张表。"""
    ws = {str(t) for t in (CAP.WRITE_SETS.get("D") or ())}
    for table in ("statements", "dependencies"):
        assert table not in ws, (table, sorted(ws))


# ============================================================ e conjectures 不在写集
def test_e_conjectures_is_written_by_the_producers_not_by_d() -> None:
    """e：`conjectures` 撤出 D 的写集，落进三个产出侧（业主 2026-11-13 裁定甲）。"""
    ws = {str(t) for t in (CAP.WRITE_SETS.get("D") or ())}
    assert "conjectures" not in ws, (
        "D 的写集里又有 `conjectures` 了 —— 临时命题由产出侧（E 的实验 / F 的稿命题 / "
        f"B 的收录）登记，D 只给研究方向：{sorted(ws)}")
    for role in ("E", "F", "B"):
        assert "conjectures" in {str(t) for t in (CAP.WRITE_SETS.get(role) or ())}, role


# ============================================================ d 报告落点是文件
def test_d_the_report_lands_as_a_file_not_in_a_report_table(tmp_path: pathlib.Path) -> None:
    """d：`write_report` 只写文件；`analysis_reports`（C 的表）一行都不多。"""
    st, d = _run_d(tmp_path)
    before = len([r for r in st.rows("analysis_reports")])
    path = pathlib.Path(str(d.write_report()))
    assert path.is_file(), path
    assert len([r for r in st.rows("analysis_reports")]) == before, (
        "D 的报告落进了 `analysis_reports` —— 那是 C 的表，D 的报告落点是文件")


if __name__ == "__main__":          # pragma: no cover - 手工跑这一份时用
    raise SystemExit(pytest.main([__file__, "-q"]))

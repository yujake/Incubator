"""编排（`pipeline.py`）的性质测试。

只跑离线静态分析模式（`agent_a=None` / `agent_b=None`）：整条流水线不碰网络、
不依赖 API key，因此可重复。两件事必须成立：

1. 用真实演示数据集跑一遍，要产出 C 报告（文件 + 登记行）、D 报告、非空问题表，且不崩；
2. 同一份 C 报告 ingest 两次不得产生重复问题（去重口径是
   `(kind, 排序后的关系代号)`，即"同一条关系链"）。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agentflow.agent_c import AgentC
from agentflow.pipeline import PipelineError, run_pipeline
from agentflow.store import Store

from demo_dataset_helper import build_demo

REQUEST = "查询 群 与 域 之间的关系"


@pytest.fixture
def demo(tmp_path) -> Store:
    return Store(build_demo(tmp_path / "demo"))


def test_run_pipeline_on_demo_dataset_produces_reports_and_questions(demo, tmp_path):
    """离线跑通 C→D：产生 C 报告、D 报告、非空问题表，且全程不抛异常。"""
    out = run_pipeline(
        demo,
        request=REQUEST,
        gap_rounds=2,
        agent_c=AgentC(demo),
        agent_a=None,
        agent_b=None,
        d_report_path=tmp_path / "demo" / "reports" / "pipeline-research.md",
    )

    assert out["mode"] == "analyze"
    assert out["report_ids"], "没有产生 C 报告"
    rid = out["report_ids"][0]

    # C 的报告必须双份落盘：文件 + 登记行
    reports = demo.rows("analysis_reports")
    assert len(reports) == 1 and reports[0]["report_id"] == rid
    assert reports[0]["kind"] == "paths"
    md_path = demo.root / str(reports[0]["markdown_path"])
    assert md_path.exists() and md_path.stat().st_size > 0
    assert out["c_analysis"]["kind"] == "paths"

    # 问题表非空，且状态都在受控词表内
    assert out["questions_total"] > 0, "D 没有从 C 的报告里提取出任何研究问题"
    assert out["questions"], out["questions"]
    for row in demo.rows("research_questions"):
        assert row["status"] in ("open", "needs_evidence", "researching", "answered", "dropped")
        assert row["related_relation_ids"] and row["related_concept_ids"]
        assert row["origin"].startswith(f"C:paths:{rid}:")

    # D 的研究报告必须写出来
    d_path = Path(out["d_report_path"])
    assert d_path.exists() and d_path.stat().st_size > 0
    text = d_path.read_text(encoding="utf-8")
    assert "# D 初步研究报告" in text
    assert "代号溯源" in text
    assert "置信度" in text

    # 每轮摘要必须可审计
    assert out["rounds"] and out["rounds"][0]["round"] == 1
    assert "d" in out["rounds"][0] and "d_poll" in out["rounds"][0]
    # 不跑检索时不得凭空提交查询请求（那会让问题永远停在 needs_evidence）
    assert out["requests_total"] == 0


def test_run_pipeline_reingest_does_not_duplicate_questions(demo, tmp_path):
    """同一份 C 报告（同一条关系链）ingest 两次不得产生重复问题，问题表大小不变。"""
    first = run_pipeline(
        demo, request=REQUEST, gap_rounds=1, agent_c=AgentC(demo), agent_a=None, agent_b=None,
        d_report_path=tmp_path / "demo" / "reports" / "r1.md",
    )
    assert first["questions_total"] > 0
    before = first["questions_total"]

    second = run_pipeline(
        demo, request=REQUEST, gap_rounds=1, agent_c=AgentC(demo), agent_a=None, agent_b=None,
        d_report_path=tmp_path / "demo" / "reports" / "r2.md",
    )
    assert len(demo.rows("analysis_reports")) == 2, "第二次运行应当另发一个报告号"
    assert second["report_ids"] != first["report_ids"]
    assert second["questions_total"] == before, "同一条关系链被重复提成了新问题"
    assert len(demo.rows("research_questions")) == before
    assert all(r["origin"].startswith("C:paths:") for r in demo.rows("research_questions"))


def test_run_pipeline_resume_mode_replays_registered_reports(demo, tmp_path):
    """续跑模式（agent_c=None + 关掉自动装配）只读已登记的报告，不重复建问题。"""
    first = run_pipeline(
        demo, request=REQUEST, gap_rounds=1, agent_c=AgentC(demo), agent_a=None, agent_b=None,
        d_report_path=tmp_path / "demo" / "reports" / "r1.md",
    )
    before = first["questions_total"]
    replay = run_pipeline(
        demo,
        request=REQUEST,
        gap_rounds=1,
        config={"auto_build_c": False},
        agent_c=None,
        agent_a=None,
        agent_b=None,
        d_report_path=tmp_path / "demo" / "reports" / "replay.md",
    )
    assert replay["mode"] == "replay"
    assert replay["questions_total"] == before
    assert len(demo.rows("analysis_reports")) == 1, "replay 不该再产生新的 C 报告"
    assert Path(replay["d_report_path"]).exists()


def test_run_pipeline_fails_loudly_when_there_is_nothing_to_analyze(tmp_path):
    """既没有 C 报告、又拿不到 C 分析器时，必须显式失败而不是"假装跑通"。"""
    st = Store(tmp_path / "empty")
    st.init()
    with pytest.raises(PipelineError) as exc:
        run_pipeline(
            st,
            request="查询 群 与 域 之间的关系",
            gap_rounds=1,
            config={"auto_build_c": False},
            agent_c=None,
            agent_a=None,
            agent_b=None,
        )
    assert "analysis_reports" in str(exc.value)
    assert not st.rows("research_questions")

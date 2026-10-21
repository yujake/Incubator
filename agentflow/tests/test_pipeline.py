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


# ============================================================ L-03：报告只由 C 的动作产出


def test_l03_the_direct_write_path_is_gone(demo, tmp_path):
    """L-03 的负控：`pipeline` 里"自己把报告写进 `analysis_reports`"那条路不存在。

    改前必红：`pipeline.py` 里有 `def _persist_report(...)` 且 `run_pipeline` 调它
    （`report = _make_request_fn(agent_c)(request)` → `row = _persist_report(...)`），
    那次分析不写 `role=C` 的 `tasks` 行、也不过策略/预算闸门 ⇒
    `c_analysis_runs` 读 0（台账上像"C 一次都没跑过"）。

    判据形态：源码里不许再有那个直写函数、也不许在 `run_pipeline` 里调它 ——
    这是"退场"这件事本身的判据（行为判据在下面两条）。
    """
    import inspect

    from agentflow import pipeline as PL

    assert not hasattr(PL, "_persist_report"), "直写报告表那条路还在（L-03 没落）"
    # 只看代码行（注释里说明"旧形态叫什么"是应该的，判据判的是行为）。
    src = "\n".join(ln for ln in inspect.getsource(PL.run_pipeline).splitlines()
                    if not ln.lstrip().startswith("#"))
    assert "_persist_report(" not in src, "run_pipeline 里还在调直写"
    assert "summon(" in src, "新路径（经 conductor.summon）不见了"
    # 报告只由 C 的动作产出 ⇒ 写集声明与落点必须对得上（不动权限面）
    from agentflow import capabilities as C

    assert "analysis_reports" in C.WRITE_SETS["C"], "C 的写集里没有 analysis_reports"
    assert C.find_action("C", "handle").handler_name == "handle"


def test_l03_the_analysis_leaves_a_role_c_task_row(demo, tmp_path):
    """L-03 的正控：这一次分析在 `tasks` 里留下 `role="C"` 的行（治 `c_analysis_runs` 读 0）。"""
    out = run_pipeline(
        demo, request=REQUEST, gap_rounds=1, agent_c=AgentC(demo),
        agent_a=None, agent_b=None,
        d_report_path=tmp_path / "demo" / "reports" / "pipeline-research.md",
    )
    rows = [r for r in demo.rows("tasks") if str(r.get("role")) == "C"]
    assert rows, f"没有 role=C 的任务行：{[r.get('role') for r in demo.rows('tasks')]}"
    assert rows[0]["action"] == "handle", rows[0]
    assert rows[0]["called_by"] == "M", rows[0]
    assert rows[0]["outcome"] == "ok" and rows[0]["status"] == "done", rows[0]
    assert out["c_analysis"]["task_id"] == rows[0]["task_id"], out["c_analysis"]
    # 报告仍是双份落盘（文件 + 登记行）——退场的是"pipeline 自己写"，不是"报告不落盘"
    reports = demo.rows("analysis_reports")
    assert len(reports) == 1 and reports[0]["report_id"] == out["report_ids"][0], reports
    assert (demo.root / str(reports[0]["markdown_path"])).is_file(), reports[0]


def test_l03_the_role_c_surface_is_still_read_only():
    """L-03 的第 4 条负控：不许为了让 `handle` 能落盘而放宽 C 的只读工具面。

    `analysis_reports` 的写权来自 `capabilities.WRITE_SETS["C"]`（声明面），
    而 C 的工具面是另一回事：它一律拿不到写工具（`for_role` 的结构性剥离），
    只读角色仍可调的落库代理只由 `READONLY_CALL_EXCEPTIONS` 一张表说了算。
    """
    from agentflow import capabilities as C
    from agentflow.tools import READONLY_CALL_EXCEPTIONS, READ_ONLY_ROLES
    from agentflow.tools import build_registry

    assert "C" in READ_ONLY_ROLES, "C 掉出只读角色名单了"
    allowed = {name for name, _why in READONLY_CALL_EXCEPTIONS.get("C", ())}
    reg = build_registry().registry
    for spec in reg.for_role("C"):
        if spec.name in allowed:
            # 2026-10-18（业主裁定）：C 拿到**一件**登记工具，用来把分析结果写进
            # `analysis_reports`（此前它"面外操作"，报告进不了台账）。判据没有放宽：
            # 例外只能来自 `READONLY_CALL_EXCEPTIONS["C"]` 这张逐条登记的表，
            # 且登记的那件必须真是写工具（否则等于登记了一件没用的事）。
            assert spec.side_effect != "read", f"登记为例外的工具应当是写工具：{spec.name}"
            continue
        assert spec.side_effect == "read", f"C 的工具面上出现了写工具：{spec.name}"
    for spec in reg.call_surface("C"):
        if spec in allowed:
            continue
        assert reg.get(spec).side_effect == "read", f"C 多拿到了写工具：{spec}"
    assert "analysis_reports" in C.WRITE_SETS["C"]   # 落盘权来自声明面，不是工具面


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

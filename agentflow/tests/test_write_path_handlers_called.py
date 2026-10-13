# -*- coding: utf-8 -*-
"""裁决 8 = A（`draft/52` §裁决 8 / F7）：7 个写路径 handler 要有真的调用它们的测试。

## 为什么单开一个文件

发布门 `coverage` 今天 `gate=0`，靠的是在测试里写一次工具名串（`conductor.stop`
这种点号名）—— 等级 1（写路径，最高风险档）的零测试数是 7（忽略工具名串时），
而门看到的读数是 0。裁决 8 选的处置是 A：给这 7 个补"真的构造 store/上下文
并调用它"的测试 —— 不是把名字写进 `tests/`（那样一个字符串就又把门满足掉了）。

7 个（`draft/52` §裁决 8 逐字）：`conductor_summon_many` / `conductor_stop` /
`conductor_cancel` / `conductor_ensure_project` / `fs_move` /
`research_write_note` / `research_set_status`。

本文件都用直接导入并调用 handler 函数的方式（不是 `reg.call("…")`）：
`reg.call` 只会让"工具名串"出现在测试里 —— 那正是这一条要治的形态。
"""
from __future__ import annotations

import json

import pytest

from agentflow import schema as S
from agentflow.conductor import Conductor
from agentflow.store import Store
from agentflow.tools import conductor_tools as CT
from agentflow.tools import fs_tools as FT
from agentflow.tools import research_tools as RT

TS = "2026-01-01T00:00:00+00:00"

#: 裁决 8 点名的 7 个写路径 handler（本文件必须逐个真的调用）。
WRITE_PATH_HANDLERS: tuple[str, ...] = (
    "conductor_summon_many", "conductor_stop", "conductor_cancel",
    "conductor_ensure_project", "fs_move", "research_write_note", "research_set_status",
)


def _store(tmp_path) -> Store:
    st = Store(tmp_path)
    st.init()
    return st


def _conductor(st: Store) -> Conductor:
    """真主控：注册表给空表（这一档测的是 handler 自己的行为，不是派活是否成功）。"""
    return Conductor(st, registry={})


def _question(st: Store, qid: str = "0000", **patch) -> dict:
    row = {"question_id": qid, "question": "问题", "status": "open",
           "created_at": TS, "created_by": "test", **patch}
    with st.tx("research_questions", actor="test") as tx:
        tx.upsert("research_questions", row)
    return row


def test_conductor_summon_many_reports_one_outcome_per_target(tmp_path):
    """`conductor_summon_many`：真的建主控、真的派一批，每一项都有自己的结局。

    三态纪律（handler 的 docstring 逐字）：返回列表长度恒等于输入长度 ——
    "第 3 个被拒了"不许表达成"只有 2 个任务"。注册表是空的 ⇒ 每一项都该被拒，
    而被拒也要有一行（这正是"没查成"与"没做"要分得开的那条纪律）。
    """
    st = _store(tmp_path)
    c = _conductor(st)
    res = CT.conductor_summon_many(lambda: c, targets=[
        {"target_role": "B", "action": "run_once"},
        {"target_role": "B", "action": "run_once"},
    ], why="裁决 8 的调用面测试")
    assert res.ok is True, res
    assert len(res.data["results"]) == 2, res.data
    # 同一角色两个 target 且没给 instance ⇒ handler 自动补序号（并发才排得开）
    assert res.data["results"][0].get("auto_instance") is True, res.data["results"]


def test_conductor_stop_writes_the_stop_switch(tmp_path):
    """`conductor_stop`：优雅停止必须先落停机开关（那是唯一能打断在飞工作的通道）。

    `notify=False` 只是跳过"公共频道广播/插话"那一段（与本判据无关），
    开关与终态收尾照走。
    """
    from agentflow import stopctl

    st = _store(tmp_path)
    c = _conductor(st)
    res = CT.conductor_stop(lambda: c, reason="user", drain_sec=0.0, notify=False)
    assert res.ok is True, res
    assert stopctl.stop_path(tmp_path).exists(), "停机开关没有落盘 —— 在飞工作打断不了"
    assert res.data["reason"] == "user", res.data


def test_conductor_cancel_records_a_terminal_state(tmp_path):
    """`conductor_cancel`：硬取消也要落一条有理由的终态（不许静默）。"""
    st = _store(tmp_path)
    c = _conductor(st)
    res = CT.conductor_cancel(lambda: c, reason="user", detail="裁决 8 的调用面测试")
    assert res.ok is True, res
    assert res.data["reason"] == "user", res.data
    assert res.data["detail"], res.data


def test_conductor_ensure_project_cold_start_creates_the_project(tmp_path):
    """`conductor_ensure_project`：显式给 `projects_dir` 时 cold 启动真的建目录。

    显式给落点是这个 handler 的允许路径（不给时在已初始化的工作区里会被拒）。
    """
    st = _store(tmp_path)
    target = tmp_path / "projects-root"
    res = CT.conductor_ensure_project(st, project_name="probe8", start="cold",
                                      projects_dir=str(target))
    assert res.ok is True, res
    assert (target / "probe8").is_dir(), res.data
    assert res.data["mode"] == "cold", res.data


def test_fs_move_really_moves_inside_the_sandbox(tmp_path):
    """`fs_move`：真的建 `FsContext`、真的搬一个文件（写路径必须被直接跑到）。"""
    st = _store(tmp_path)
    ctx = FT.FsContext(root=tmp_path, actor="test")
    (tmp_path / "a.txt").write_text("内容\n", encoding="utf-8")
    res = FT.fs_move(ctx, src="a.txt", dst="sub/b.txt")
    assert res.ok is True, res
    assert (tmp_path / "sub" / "b.txt").read_text(encoding="utf-8") == "内容\n"
    assert not (tmp_path / "a.txt").exists()
    # 负控（沙箱边界不许被这次测试放宽）：越界目标照旧被拒
    bad = FT.fs_move(ctx, src="sub/b.txt", dst="../outside.txt")
    assert bad.ok is False, bad


def test_research_write_note_appends_instead_of_overwriting(tmp_path):
    """`research_write_note`：笔记是追加的（覆盖会毁掉"第几轮说了什么"的时间序列）。"""
    st = _store(tmp_path)
    _question(st)
    res = RT.research_write_note(st, "0000", "第一轮：证据不足")
    assert res.ok is True, res
    res2 = RT.research_write_note(st, "0000", "第二轮：够了")
    assert res2.ok is True, res2
    row = [dict(r) for r in st.rows("research_questions")][0]
    assert "第一轮" in row["notes"] and "第二轮" in row["notes"], row["notes"]
    # 负控：问题不存在时如实 fail（不是静默成功）
    missing = RT.research_write_note(st, "9999", "x")
    assert missing.ok is False and missing.meta.get("kind") == "not_found", missing


def test_research_set_status_goes_through_the_state_machine(tmp_path):
    """`research_set_status`：合法迁移走通、非法迁移被拒（状态机是 D 的循环骨架）。"""
    st = _store(tmp_path)
    _question(st)
    assert RT.research_set_status(st, "0000", "researching").ok is True
    row = [dict(r) for r in st.rows("research_questions")][0]
    assert row["status"] == "researching", row
    bad = RT.research_set_status(st, "0000", "open")
    assert bad.ok is False and bad.meta.get("kind") == "illegal_transition", bad


def test_the_seven_handlers_are_exercised_by_their_own_names() -> None:
    """元判据（裁决 8 的判据本身）：本文件必须逐个直接调用那 7 个 handler。

    为什么这条判据必要：发布门"零测试"的口径是"名字有没有出现在 tests/ 里"。
    如果本文件只写 `reg.call("conductor.stop")`，那么被判据承认的仍然只是
    一个字符串 —— 而裁决 8 要的恰恰是"真的构造上下文并调用它"。
    所以这里扫本文件的源码：7 个 `def <handler>(` 名字都要作为被调用的标识符
    （`CT.<name>(` / `FT.<name>(` / `RT.<name>(`）出现。
    """
    import pathlib
    import re

    src = pathlib.Path(__file__).read_text(encoding="utf-8")
    called = set(re.findall(r"\b(?:CT|FT|RT)\.([a-z_]+)\(", src))
    missing = [name for name in WRITE_PATH_HANDLERS if name not in called]
    assert not missing, (
        f"这 7 个写路径 handler 里有 {len(missing)} 个没有被直接调用：{missing} —— "
        "把名字写进 tests/ 不等于有测试（裁决 8 = A 逐字）"
    )


def test_the_production_caller_gauge_is_stated_in_the_output() -> None:
    """F7/裁决 2（主控 2026-10-06）：读数必须口径自明 —— 两档分开、各说各数什么。

    为什么单列：生产路径常直调工具体（`agent_a/shelf_search.py` 调 `_h_shelf`/
    `_h_local`、`agent_g/_support.py` 同族）而不写工具名串
    （`registry.call("search.shelf")`）⇒ 同一句话会被两种读法读成两个结论。
    读数自己不说口径，就是本项目最忌的形态（"没查成"与"查过了"读起来一样）。
    """
    import importlib.util
    import sys
    from pathlib import Path

    repo = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("_coverage_under_test_gauge",
                                                  repo / "tools" / "coverage_zero_test.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)

    gauge = mod.production_caller_reading([], [], 2)["gauge"]
    assert set(gauge) == {"function_level", "string_level", "production_caller", "gate_basis"}, \
        sorted(gauge)
    assert "函数" in gauge["production_caller"] and "handler" in gauge["production_caller"], gauge
    assert "字符串" in gauge["string_level"], gauge
    assert "不是一次调用" in gauge["string_level"], gauge
    assert gauge["gate_basis"].startswith("function_level"), gauge
    # 打印面也要有这句（人读的是 stdout，不只是 --json）
    import inspect

    src = inspect.getsource(mod.main)
    assert "口径（两档分开，别混读）" in src, "stdout 里没有口径说明"
    assert "字符串级" in src and "函数级" in src, src[:200]


def test_a_registered_zero_caller_module_is_named_not_silently_exempt() -> None:
    """F7 读数必须点名 `deliver.py` 这个"零生产调用者但不许删"的登记项。

    为什么单列（主控 2026-10-06 裁定）：`cli` 的 `gate` 子命令退场之后 `deliver.py`
    会零生产调用者，而 `draft/48-09 §4.10` 逐字要求不许删（它是第二套交付闸门，
    与收工门同族重叠）。静默豁免是本项目最忌的形态 ⇒ 它必须出现在读数里、
    带署名与依据。这一条同时是收紧的负控素材：如果读数对它一声不响，
    说明收紧只数了一半。
    """
    import importlib.util
    import sys
    from pathlib import Path

    repo = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("_coverage_under_test_reg",
                                                  repo / "tools" / "coverage_zero_test.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)

    entries = mod.registered_no_production_caller_reading([])
    targets = [e["target"] for e in entries]
    assert "src/agentflow/deliver.py" in targets, targets
    entry = [e for e in entries if e["target"].endswith("deliver.py")][0]
    for key in ("why", "status", "guarded_by", "decision", "source"):
        assert entry.get(key), (key, entry)
    assert "保留" in entry["decision"] and "48-09" in entry["source"], entry
    # 读数里带着实测数（不是一句声明）：模块公开函数数与零测试数
    assert "module_public_functions" in entry and "module_zero_test" in entry, entry
    # 它出现在 production_callers 读数里（不是躲在某个豁免表里）
    reading = mod.production_caller_reading([], [], 2)
    assert reading["registered_no_production_caller"], reading


def test_a_tool_name_string_alone_is_not_a_test(tmp_path) -> None:
    """J-45 硬边界②（F7 收紧的负控）：新造一个真无测试的写路径 handler 仍会被判。

    为什么必须单独钉这一条：收紧（把 `via:tool_name` 排除在"有测试"之外）最容易
    退化成一句口号 —— 如果负控只证明"旧的那 7 个不再红"，那么下一个只被
    工具名串满足的写路径 handler 会照样绿。这里造一个全新的小世界：

    - `submit_thing` 是等级 1（写路径：`store.tx`）且带工具名（`x.submit_thing`）；
    - 测试里只写一次那个工具名串 ⇒ 收紧后必须算零测试 ⇒ `gate >= 1`（红）；
    - 补上真调用（`m.submit_thing(...)`）⇒ 才转绿。

    改前红：`info.tested` 只看 `bool(hits)`，工具名串那一档也算 ⇒ 这一档恒绿。
    """
    import importlib.util
    import sys
    from pathlib import Path

    repo = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("_coverage_under_test_j45",
                                                  repo / "tools" / "coverage_zero_test.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)

    (tmp_path / "src" / "agentflow").mkdir(parents=True)
    (tmp_path / "tests").mkdir()
    # 形状照真机：函数名与工具名不同名（`conductor_stop` vs `"conductor.stop"`）——
    # 所以"在测试里写一次工具名串"不会让裸名/限定名命中。
    (tmp_path / "src" / "agentflow" / "m.py").write_text(
        'def tool(name, *a, **kw):\n'
        '    """测试替身：`collect_src` 只读 `@tool(\"…\")` 的第一个参数。"""\n'
        '    def deco(fn):\n'
        '        return fn\n'
        '    return deco\n'
        '\n'
        '@tool("svc.write_thing")\n'
        'def my_writer(store):\n'
        '    """写路径：直接落库。"""\n'
        '    with store.tx("t", actor="x") as tx:\n'
        '        tx.upsert("t", {})\n', encoding="utf-8")
    # 只写工具名串（`svc.write_thing`）：这个函数在测试里没有任何真调用
    (tmp_path / "tests" / "test_nominal.py").write_text(
        'def test_x():\n    assert "svc.write_thing" in "svc.write_thing"\n', encoding="utf-8")
    funcs, _ex = mod.collect_src(tmp_path, frozenset())
    info = [f for f in funcs if f.bare == "my_writer"][0]
    assert info.level == 1, (info.level, info.level_why)
    # 夹具自证：这一档必须靠 `via:tool_name` 才可能"看起来有测试"
    mod.mark_tested(funcs, tmp_path)
    assert any(h.startswith("via:tool_name") for h in info.tested_by), \
        (info.tested_by, "夹具没造出'只靠工具名串'的形态 —— 这条负控就没有判别力")
    assert info.tested is False, info.tested_by
    assert [f for f in funcs if not f.tested and f.level <= 2], \
        "只被工具名串满足的写路径 handler 必须仍然算零测试（收紧不许退化）"

    # 补上真调用 ⇒ 这一档才消失
    (tmp_path / "tests" / "test_real.py").write_text(
        "import m\n\n\ndef test_y():\n    m.my_writer(store=None)\n", encoding="utf-8")
    funcs2, _ex2 = mod.collect_src(tmp_path, frozenset())
    mod.mark_tested(funcs2, tmp_path)
    info2 = [f for f in funcs2 if f.bare == "my_writer"][0]
    assert info2.tested is True, info2.tested_by
    assert not [f for f in funcs2 if not f.tested and f.level <= 2], \
        [f.bare for f in funcs2 if not f.tested and f.level <= 2]


def test_the_coverage_tool_reads_alias_direct_calls(tmp_path) -> None:
    """F7 的收紧读数（小世界、不在真树上跑发布门）：限定名调用算"真的调用过"。

    为什么不在真树上跑：`collect_src` + `_test_text` 在真树上要分钟级
    （整条 `coverage` 步实测 928.6 s，`draft/43-D` §0.3）—— 单元测试不许背这个成本。
    所以这里用一个小世界证明判据的分量（`via:alias_direct` 与 `via:tool_name` 可分辨），
    "7 个 handler 不再只靠工具名串"的全量读数由发布门自己出
    （`python -B tools/coverage_zero_test.py --json` 的 `totals.production_callers`）。
    """
    import importlib.util
    import sys
    from pathlib import Path

    repo = Path(__file__).resolve().parents[1]
    script = repo / "tools" / "coverage_zero_test.py"
    spec = importlib.util.spec_from_file_location("_coverage_under_test_handlers", script)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)

    (tmp_path / "src" / "agentflow").mkdir(parents=True)
    (tmp_path / "tests").mkdir()
    (tmp_path / "src" / "agentflow" / "m.py").write_text(
        "def conductor_stop():\n    return 1\n", encoding="utf-8")
    # 只写工具名串 ⇒ 只该拿到 `via:tool_name`（名义覆盖，不算真的调用过）
    (tmp_path / "tests" / "test_nominal.py").write_text(
        'def test_x():\n    assert "conductor.stop" == "conductor.stop"\n', encoding="utf-8")
    funcs, _excluded = mod.collect_src(tmp_path, frozenset())
    mod.mark_tested(funcs, tmp_path)
    info = [f for f in funcs if f.bare == "conductor_stop"][0]
    assert info.tested is False, info.tested_by  # 工具名不匹配裸名 ⇒ 这一档不成立
    # 真的调用（限定名）⇒ `via:alias_direct`（裁决 8 要的那一档）
    (tmp_path / "tests" / "test_real.py").write_text(
        "import m\n\n\ndef test_y():\n    assert m.conductor_stop() == 1\n", encoding="utf-8")
    funcs2, _excluded2 = mod.collect_src(tmp_path, frozenset())
    mod.mark_tested(funcs2, tmp_path)
    info2 = [f for f in funcs2 if f.bare == "conductor_stop"][0]
    assert info2.tested is True, info2.tested_by
    assert any(h.startswith("via:alias_direct") for h in info2.tested_by), info2.tested_by

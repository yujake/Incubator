"""T0-12 的判据：实验的原始输出落成产物文件（依据 `draft/30` §T0-12）。

背景（验收 P4 实测）：E 只在解析不出结论时才把 stdout 摘要放进 `notes`
（`agent_e.py` 里那条"支持类不贴摘要"的取舍是刻意的），于是结论解析成功的实验
原始输出根本没落盘 —— 而 P4/P5 要求"每条带 code_hash + 退出码 + 原始输出"。

处置：原始输出写成 `out/experiments/<实验号>.log` 并进 `artifact_paths`；
摘要仍不进 `notes`。三条判据：正控（产物在且逐字含原始 stdout）、
防误伤（notes 里没有 `[stdout]` 摘要）、负控（日志写不出来时实验行照样写）。
"""

from __future__ import annotations

from pathlib import Path

from agentflow.agent_e import AgentE
from agentflow.store import Store

SCRIPT_GOOD = """\
import json
print("hello from the certificate")
print("a second line of raw output")
print("REPRO_RESULT: " + json.dumps({"result": "supports", "evidence_kind": "cross_check",
                                     "observations": {"checked": 3}}))
"""


def _workspace(tmp_path: Path, *, block_log_dir: bool = False) -> tuple[Store, Path]:
    """造一个工作区 + 一个会打印结论的脚本。"""
    st = Store(tmp_path)
    st.init()
    (tmp_path / "code").mkdir(parents=True, exist_ok=True)
    (tmp_path / "code" / "probe.py").write_text(SCRIPT_GOOD, encoding="utf-8")
    if block_log_dir:
        # 把 `out/experiments` 造成文件：`mkdir` 必定失败
        (tmp_path / "out").mkdir(parents=True, exist_ok=True)
        (tmp_path / "out" / "experiments").write_text("not a directory", encoding="utf-8")
    return st, tmp_path


def test_raw_output_becomes_an_artifact(tmp_path: Path):
    """正控：原始输出落成产物文件，且逐字含脚本的 stdout。"""
    st, root = _workspace(tmp_path)
    e = AgentE(st, workspace_root=root, config={"max_downloads_per_request": 1})
    out = e.run_experiment("原始输出必须落盘", "T0-12-raw-output", "code/probe.py")
    rows = st.rows("experiments")
    assert len(rows) == 1, rows
    row = rows[0]
    arts = list(row.get("artifact_paths") or [])
    assert arts == [f"out/experiments/{row['experiment_id']}.log"], arts
    text = (root / arts[0]).read_text(encoding="utf-8")
    assert "hello from the certificate" in text, text
    assert "a second line of raw output" in text, text
    assert "REPRO_RESULT:" in text, text
    assert "----- stdout -----" in text and "----- stderr -----" in text, text
    assert f"sha256={row['code_hash']}" in text, text
    assert f"exit_code={row['exit_code']}" in text, text
    assert out["result"] == "supports"


def test_notes_do_not_carry_the_stdout_digest_for_a_supported_result(tmp_path: Path):
    """防误伤：那条"支持类不贴 stdout 摘要"的取舍仍在（摘要不进 notes，原始输出进文件）。"""
    st, root = _workspace(tmp_path)
    e = AgentE(st, workspace_root=root)
    e.run_experiment("摘要不进 notes", "T0-12-summary-stays-out", "code/probe.py")
    notes = str(st.rows("experiments")[0].get("notes") or "")
    assert "[stdout]" not in notes, notes
    assert "[run]" in notes, notes


def test_a_failed_log_write_does_not_lose_the_experiment(tmp_path: Path):
    """负控（注入）：日志写不出来 ⇒ 实验行照样写、`artifact_paths` 为空、notes 写明原因。"""
    st, root = _workspace(tmp_path, block_log_dir=True)
    e = AgentE(st, workspace_root=root)
    e.run_experiment("日志写不出来也要记实验", "T0-12-log-failure", "code/probe.py")
    rows = st.rows("experiments")
    assert len(rows) == 1, rows
    row = rows[0]
    assert list(row.get("artifact_paths") or []) == [], row.get("artifact_paths")
    notes = str(row.get("notes") or "")
    assert "[log]" in notes and "未能落盘" in notes, notes
    assert row.get("result") == "supports", row
    assert not (root / "out" / "experiments").is_dir(), "夹具前提：那个位置是文件而不是目录"

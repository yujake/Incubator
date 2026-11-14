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



# ============================================================ 产物归属（ARTIFACTS.jsonl）

def test_the_run_log_is_registered_as_an_owned_artifact(tmp_path: Path):
    """原始输出那份 `.log` 是内容产物 ⇒ 台账里有一行、sha 与盘上一致。"""
    from agentflow import artifacts as A

    st, root = _workspace(tmp_path)
    e = AgentE(st, workspace_root=root, config={"max_downloads_per_request": 1})
    e.run_experiment("原始输出要有归属", "T0-12-owned", "code/probe.py")
    row = st.rows("experiments")[0]
    rel = f"out/experiments/{row['experiment_id']}.log"
    rows = [r for r in A.read_ledger(root)[0] if r.get("path") == rel]
    assert rows, f"{rel} 没有进产物台账（unowned）"
    assert rows[-1]["sha256"] == A.sha256_of(root / rel)
    assert rows[-1]["kind"] == "experiment-log"
    assert rows[-1]["producer"] == "E"


def test_stubbing_the_recorder_makes_the_log_registration_red(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """反真空：`artifacts.record` 不写 ⇒ 同一条读不到归属（红压在这一步）。

    "打桩成不写"改的是登记行为本身；实验行、日志文件、`artifact_paths` 一个都不动
    —— 判据变红只能是因为那一行归属没了。
    """
    from agentflow import artifacts as A

    st, root = _workspace(tmp_path)
    e = AgentE(st, workspace_root=root, config={"max_downloads_per_request": 1})
    monkeypatch.setattr(A, "record", lambda *a, **k: {})
    e.run_experiment("归属失败要说出来", "T0-12-unowned", "code/probe.py")
    row = st.rows("experiments")[0]
    rel = f"out/experiments/{row['experiment_id']}.log"
    assert (root / rel).is_file(), "打桩只该改登记行为，日志照样要落盘"
    assert [r for r in A.read_ledger(root)[0] if r.get("path") == rel] == []


def test_a_registration_failure_is_named_in_the_experiment_row(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """登记失败（台账写不进去）⇒ 那一行的 `notes` 里点名，实验行照样建。"""
    from agentflow import artifacts as A

    def _boom(*a, **k):
        raise A.ArtifactError("注入：台账写不进去")

    st, root = _workspace(tmp_path)
    e = AgentE(st, workspace_root=root, config={"max_downloads_per_request": 1})
    monkeypatch.setattr(A, "record", _boom)
    e.run_experiment("归属失败要说出来", "T0-12-named", "code/probe.py")
    row = st.rows("experiments")[0]
    rel = f"out/experiments/{row['experiment_id']}.log"
    assert (root / rel).is_file()
    notes = str(row.get("notes") or "")
    assert "[artifact]" in notes and "没登记成" in notes, notes
    # 日志仍然被这一行引用（文件真的在盘上，缺的只是归属）。
    assert list(row.get("artifact_paths") or []) == [rel]

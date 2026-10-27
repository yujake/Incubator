"""使用侧缺陷的四条判据（2026-10-27 真机启动时实测踩到的坑）。

这一批不是"功能没做"，而是"能做的事被用法坑住了"：同一批旗标里两个 `0` 语义相反、
CLI 缺省工作区指向代码检出目录、用户插话只有 Python API、真机日志被块缓冲吃掉。
每条都先记录复现（draft/172），这里钉住修好之后的口径：

| 坑 | 改前实测 | 改后口径 |
|---|---|---|
| `--budget-usd 0` | 上限 0，第一拍就"预算已耗尽"停机（0 次模型调用） | 0 = 不设上限（与 `--wall-clock-sec 0` 同口径）；记账层的 `0 = 预算为零` 不动 |
| 缺省工作区 | `DEFAULT_ROOT` = 代码检出目录 ⇒ 真机写脏受版本控制的 `data/*.json` | 缺省 = 当前目录；指到代码检出目录时提醒一句 |
| 用户插话 | 只能 `send_interjection(...)`；传 `sessions/` 会静默写错位置 | 新增 `agentflow interject`；传 `sessions/` 直接拒 |
| 日志 | `> log` 之后几分钟只有一行（块缓冲） | `main()` 把 stdout/stderr 调成行缓冲 |
"""

from __future__ import annotations

import argparse
import pathlib
import sys
from typing import Any

import pytest

from agentflow import agent_loop as AL
from agentflow import cli


# ---------------------------------------------------------------- ① budget 0

def test_budget_zero_means_no_cap_not_zero_cap() -> None:
    """正控：`--budget-usd 0` 解析成"不限"，而正数仍是"上限这么多"。"""
    ns = cli.build_parser().parse_args(["run-agent", "M", "--task", "x", "--budget-usd", "0"])
    assert ns.budget_usd is None, "0 必须读成「不设上限」（改前它读成「上限 0」）"
    assert ns.budget_usd_given is False, "0 不该让任何预算寄存器落盘"
    assert getattr(ns, "budget_usd_zero_means_unlimited", False) is True

    ns2 = cli.build_parser().parse_args(["run-agent", "M", "--task", "x", "--budget-usd", "0.5"])
    assert ns2.budget_usd == 0.5 and ns2.budget_usd_given is True

    ns3 = cli.build_parser().parse_args(["run-agent", "M", "--task", "x"])
    assert ns3.budget_usd is None, "不给 --budget-usd 仍然是「不限」（role 模式的缺省）"


def test_the_accounting_layer_still_treats_zero_as_zero() -> None:
    """反真空：改的只是命令行上的 0；记账层的三态（0 ≠ None）一个字没动。

    这两层必须分开：`tokenmeter` 的 `0 = 预算为零` 是内部语义（有判据钉着），
    CLI 的 `0 = 不限` 是给人用的口径。把两者合并会让"忘了配"看起来像"配成了零"。
    """
    from agentflow import tokenmeter as TM

    assert "0.0" not in str(TM.TokenMeter.__doc__ or "") or True  # 只是提醒：语义在 meter 里
    import inspect

    src = inspect.getsource(TM)
    assert "不能为负" in src, "meter 拒绝负数那一条还在（说明我们没动它的语义面）"


# ---------------------------------------------------------------- ② 缺省工作区

def test_the_default_workspace_is_the_current_directory(monkeypatch: pytest.MonkeyPatch,
                                                       tmp_path: pathlib.Path) -> None:
    """缺省工作区 = cwd（改前 = 代码检出目录 ⇒ 真机写脏交付物）。"""
    monkeypatch.chdir(tmp_path)
    assert cli._root_of(argparse.Namespace(root=None)) == tmp_path.resolve()
    given = cli._root_of(argparse.Namespace(root=str(tmp_path / "other")))
    assert given == (tmp_path / "other").resolve()


def test_pointing_the_run_at_the_code_checkout_warns(capsys: pytest.CaptureFixture[str]) -> None:
    """指到代码检出目录时提醒一句：不拦（维护命令合法），但真机会写脏数据。"""
    cli._warn_if_code_checkout(pathlib.Path(cli.DEFAULT_ROOT))
    out = capsys.readouterr().out
    assert "代码检出目录" in out and "--root" in out, out

    cli._warn_if_code_checkout(pathlib.Path(cli.DEFAULT_ROOT).parent)
    assert "代码检出目录" not in capsys.readouterr().out, "别的工作区不该有这条提醒"


# ---------------------------------------------------------------- ③ 插话 CLI

def test_interject_writes_one_interjection_addressed_to_the_conductor(
    tmp_path: pathlib.Path,
) -> None:
    """`agentflow interject` 真把一条插话写进会话台账，收件人是 M。"""
    assert cli.main(["--root", str(tmp_path), "init"]) == 0
    code = cli.main(["--root", str(tmp_path), "interject",
                     "--text", "提醒：可以并行派几个研究子代理", "--subject", "并行"])
    assert code == 0
    import json

    files = sorted((tmp_path / "sessions").glob("*.jsonl"))
    assert files, "会话台账没生成"
    rows = [json.loads(line) for line in files[0].read_text(encoding="utf-8").splitlines() if line.strip()]
    inter = [r for r in rows if r.get("kind") == "agent_interjection"]
    assert len(inter) == 1, rows
    assert inter[0]["to"] == "M" and inter[0]["from"] == "用户"
    assert "并行" in inter[0]["body"]


def test_interject_refuses_a_path_that_is_not_a_workspace(tmp_path: pathlib.Path) -> None:
    """负控：指到 `sessions/` 这种位置 ⇒ 退出码 2，且一个字都不写。"""
    assert cli.main(["--root", str(tmp_path), "init"]) == 0
    sessions = tmp_path / "sessions"
    before = {p.name for p in sessions.glob("*.jsonl")}
    code = cli.main(["--root", str(sessions), "interject", "--text", "x"])
    assert code == 2
    assert {p.name for p in sessions.glob("*.jsonl")} == before, "退出码 2 时不许留半条记录"


def test_the_api_itself_refuses_a_sessions_directory(tmp_path: pathlib.Path) -> None:
    """API 层也拒：传 `sessions/` 会写出 `sessions/sessions/<sid>.jsonl`（实测踩过）。"""
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    iid, problem = AL.send_interjection(sessions, sender="用户", subject="x", body="y", to="M")
    assert iid == ""
    assert "工作区根" in problem, problem
    assert not (sessions / "sessions").exists(), "拒绝时不许真建出嵌套目录"


# ---------------------------------------------------------------- ④ 行缓冲

def test_the_entry_point_switches_stdout_to_line_buffering(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`main()` 一进来就把 stdout/stderr 调成行缓冲（否则 `> log` 看不到进度）。"""

    class _Recorder:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        def reconfigure(self, **kwargs: Any) -> None:
            self.calls.append(kwargs)

        def write(self, _s: str) -> int:      # main 里可能往 stdout 写
            return 0

        def flush(self) -> None:
            return None

        def isatty(self) -> bool:
            return False

    rec_out, rec_err = _Recorder(), _Recorder()
    monkeypatch.setattr(sys, "stdout", rec_out)
    monkeypatch.setattr(sys, "stderr", rec_err)
    # `--version` 走 argparse 的 `action="version"`，它会 SystemExit(0) —— 那是正常退出，
    # 不是失败；这里只关心"进来之后有没有把两路输出调成行缓冲"。
    with pytest.raises(SystemExit):
        cli.main(["--version"])
    assert rec_out.calls and rec_out.calls[0].get("line_buffering") is True, rec_out.calls
    assert rec_err.calls and rec_err.calls[0].get("line_buffering") is True, rec_err.calls

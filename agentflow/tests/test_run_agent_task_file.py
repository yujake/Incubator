# -*- coding: utf-8 -*-
"""B/C：`run-agent --task-file` —— 多行中文提示词不再经过 PowerShell 的 argv。

## 业主的原话（2026-11-01）

「开真机跑必须写一个临时启动器脚本（`temp/_launch_cold_v2*.py`），因为它要 `--task`
传一段多行提示词，而 `--task` 在 PowerShell 里传多行中文会碎 ⇒ 我每次都得现写一个 py 文件。」

那一份临时启动器的日志口径逐字是：

    [launch] task 字符数=1219 sha256=11c9964a30c89f10b16d0e03e53b762f

（`_launch_cold_v2_uap.py`：`raw = TASK_FILE.read_text('utf-8')`、`TASK = raw[:-1] if
raw.endswith('\\n') else raw`，再打 `len(TASK)` 与 `sha256(TASK.encode())[:32]`。）

## 这一组守什么

1. `--task-file` 逐字读文件，只去掉末尾一个换行；打印的 `字符数=` 与 `sha256=` 前 32 位
   与启动器同口径、同数值；
2. 同一个文件跑两次 ⇒ 两次读数逐字相同；与 `--task` 直接给同一段文本 ⇒ 传给运行层的那一段
   （`spec.task` / `args.task`）逐字相同（于是 sha 也相同）；
3. 文件末尾没有换行 ⇒ 一个字符都不多去；
4. 文件不存在 ⇒ 受控报错（非 0、有中文提示、不进入运行）；
5. `--task` 与 `--task-file` 同时给 ⇒ 受控拒绝（不许谁覆盖谁）；
6. `--json` 档下那行读数走 stderr（stdout 必须是可解析的 JSON）。

## 为什么可以不起真跑

这一组只查"命令把哪一段文本交给运行层"，不查角色循环。把 `_run_spec`（五条入口唯一的
执行体）换成假的，就能在不调模型、不花钱的前提下读到 `spec.task` —— 而真跑起来之后
读的就是同一个 `spec.task`（`_exec_role` 的入口参数）。判据不碰网络、也不碰真工作区。
"""
from __future__ import annotations

import hashlib
import pathlib
import re
from typing import Any

import pytest

from agentflow import cli

#: 启动器那一行读数的形状（`[launch] task 字符数=… sha256=…` 的 CLI 版）。
_READING = re.compile(r"字符数=(\d+) sha256=([0-9a-f]{32})")

#: 判据里反复用的多行中文：带引号、`$`、`%`、反引号 —— PowerShell 传 argv 最容易吃掉的字符。
MULTILINE = ("第一段：把这篇论文重新研究后重写。\n"
             "第二段：里面有 \"引号\"、$变量、%百分号% 与 `反引号`。\n"
             "第三段末尾没有句号")


def _readings(text: str) -> list[tuple[int, str]]:
    return [(int(n), sha) for n, sha in _READING.findall(text)]


def _fake_run_spec(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """把执行体换成"只记下这一段任务"的假的（不跑角色、不调模型、不写盘）。"""
    seen: dict[str, Any] = {}

    def fake(spec: Any, args: Any) -> int:
        seen["spec_task"] = spec.task
        seen["args_task"] = args.task
        return 0

    monkeypatch.setattr(cli, "_run_spec", fake)
    return seen


def _run(argv: list[str]) -> int:
    """进程内跑一次 `cli.main`；argparse 的用法错（SystemExit）原样抛给用例。"""
    return int(cli.main(argv))


# ====================================================================== 1) 逐字 + 只去一个换行
def test_the_task_file_is_verbatim_and_drops_exactly_one_trailing_newline(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """文件末尾一个 `\\n` ⇒ 去掉它；正文一个字不改，读数与启动器同口径。"""
    task_file = tmp_path / "task.txt"
    task_file.write_text(MULTILINE + "\n", encoding="utf-8")
    seen = _fake_run_spec(monkeypatch)

    assert _run(["--root", str(tmp_path / "ws"), "run-agent", "M",
                 "--task-file", str(task_file)]) == 0
    (count, sha), = _readings(capsys.readouterr().out)
    assert count == len(MULTILINE), count
    assert sha == hashlib.sha256(MULTILINE.encode("utf-8")).hexdigest()[:32], sha
    assert seen["spec_task"] == MULTILINE
    assert seen["args_task"] == MULTILINE


def test_a_file_without_a_trailing_newline_loses_no_character(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """文件末尾没有换行 ⇒ 一个字符都不许多去（判据 ③）。"""
    body = "只剩这一行，末尾确实没有换行"
    task_file = tmp_path / "task.txt"
    task_file.write_text(body, encoding="utf-8")     # 故意不补 "\n"
    seen = _fake_run_spec(monkeypatch)

    assert _run(["--root", str(tmp_path / "ws"), "run-agent", "M",
                 "--task-file", str(task_file)]) == 0
    (count, _sha), = _readings(capsys.readouterr().out)
    assert count == len(body), count
    assert seen["spec_task"] == body


def test_two_trailing_newlines_lose_only_one(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """末尾两个换行 ⇒ 只去掉一个（"只去一个"不许被实现成 `rstrip`）。"""
    task_file = tmp_path / "task.txt"
    task_file.write_text("abc\n\n", encoding="utf-8")
    seen = _fake_run_spec(monkeypatch)

    assert _run(["--root", str(tmp_path / "ws"), "run-agent", "M",
                 "--task-file", str(task_file)]) == 0
    assert seen["spec_task"] == "abc\n", repr(seen["spec_task"])


# ====================================================================== 2) 两次 / 与 --task 同值
def test_the_same_file_reports_the_same_sha_twice(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """判据 ①：同一个文件两次跑，打印的读数逐字相同。"""
    task_file = tmp_path / "task.txt"
    task_file.write_text(MULTILINE + "\n", encoding="utf-8")
    _fake_run_spec(monkeypatch)

    assert _run(["--root", str(tmp_path / "ws"), "run-agent", "M",
                 "--task-file", str(task_file)]) == 0
    first = capsys.readouterr().out
    assert _run(["--root", str(tmp_path / "ws"), "run-agent", "M",
                 "--task-file", str(task_file)]) == 0
    second = capsys.readouterr().out
    assert _readings(first) == _readings(second), (first, second)
    assert _readings(first) and _readings(first) == _readings(second)


def test_the_file_and_a_direct_task_hand_the_same_text_to_the_run(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """判据 ②：`--task-file` 与 `--task` 给同一段文本 ⇒ 交给运行层的那一段逐字相同。"""
    task_file = tmp_path / "task.txt"
    task_file.write_text(MULTILINE + "\n", encoding="utf-8")
    seen = _fake_run_spec(monkeypatch)

    assert _run(["--root", str(tmp_path / "ws"), "run-agent", "M",
                 "--task-file", str(task_file)]) == 0
    from_file = (seen["spec_task"], seen["args_task"])
    assert _run(["--root", str(tmp_path / "ws"), "run-agent", "M",
                 "--task", MULTILINE]) == 0
    from_task = (seen["spec_task"], seen["args_task"])
    assert from_file == from_task == (MULTILINE, MULTILINE)


# ====================================================================== 3) 缺文件
def test_a_missing_task_file_is_a_controlled_refusal(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """判据 ④：文件不存在 ⇒ 非 0、有中文提示、不进运行。"""
    seen = _fake_run_spec(monkeypatch)
    missing = tmp_path / "根本没有这个文件.txt"

    code = _run(["--root", str(tmp_path / "ws"), "run-agent", "M",
                 "--task-file", str(missing)])
    captured = capsys.readouterr()
    assert code == 2, (code, captured.out, captured.err)
    assert "读不出" in captured.err or "读不到" in captured.err, captured.err
    assert missing.name in captured.err, captured.err
    assert seen == {}, "读文件失败了却仍旧进了运行层"


# ====================================================================== 4) 两个都给
def test_task_and_task_file_together_are_refused(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """C：两个都给 ⇒ 受控拒绝（不许谁静默覆盖谁）。"""
    task_file = tmp_path / "task.txt"
    task_file.write_text("文件里的任务\n", encoding="utf-8")
    seen = _fake_run_spec(monkeypatch)

    code = _run(["--root", str(tmp_path / "ws"), "run-agent", "M",
                 "--task", "命令行里的任务", "--task-file", str(task_file)])
    captured = capsys.readouterr()
    assert code == 2, (code, captured.out, captured.err)
    assert "--task" in captured.err and "--task-file" in captured.err, captured.err
    assert seen == {}, "两个都给时不许「随便挑一个」继续跑"


def test_neither_task_nor_task_file_is_refused(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """反真空：两个都不给也不能悄悄跑一个空任务（而且提示要把两条路都说出来）。"""
    seen = _fake_run_spec(monkeypatch)

    code = _run(["--root", str(tmp_path / "ws"), "run-agent", "M"])
    captured = capsys.readouterr()
    assert code == 2, (code, captured.out, captured.err)
    assert "--task-file" in captured.err, captured.err
    assert seen == {}, "没给任务却进了运行层"


# ====================================================================== 5) --json 不脏 stdout
def test_under_json_the_reading_goes_to_stderr(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`--json` 的 stdout 必须可解析：读数走 stderr（与 `--budget-usd` 那一档同一条纪律）。"""
    task_file = tmp_path / "task.txt"
    task_file.write_text(MULTILINE + "\n", encoding="utf-8")
    _fake_run_spec(monkeypatch)

    assert _run(["--root", str(tmp_path / "ws"), "run-agent", "M",
                 "--task-file", str(task_file), "--json"]) == 0
    captured = capsys.readouterr()
    assert not _readings(captured.out), captured.out
    assert _readings(captured.err), captured.err

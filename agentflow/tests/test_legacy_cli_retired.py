# -*- coding: utf-8 -*-
"""判据（A4）：四条移植期工具已受控退场 —— 明确错误 + 替代指引 + 退出码 2。

## 这一版删了什么、没删什么

2026-11-20 业主批准 A4：`tools/legacy_cli/`（`demo` / `rebuild` / `repair` /
`evidence_migrate` 四个模块）与 CLI 里那层 `_legacy_module(...)` 转发一起删。
**删的是命令行这一层**；库里真正干活的实现（`demo.run_demo` / `Store.rebuild` /
`fulltextstore` 那一套）一件都没删。

## 为什么命令名还留着

"删干净"不等于"让命令从 `--help` 里消失"：删掉 argparse 挂点之后，调用方拿到的是
`invalid choice: 'rebuild'` —— 那句话只说"不认识"，不说"它去哪了、现在该用什么"，
而且它和"打错字"长得一模一样。所以四条命令仍能解析，函数体只做一件事：
把退场原因、替代路径、退出码说清楚。

## 三态口径

退出码必须是 `2`（没查成）：**这条路已经不存在了**。不许是 `0`（那会把"没有这条路"
读成"跑过了没问题"），也不许是 `1`（那是"查过了、发现问题"，会把一次退场读成缺陷）。

## 反真空

判据本体是 `_problems`：它逐条核退出码 / stdout 空 / 标签 / "已退场" / 替代指引。
`test_anti_vacuum_...` 把退场层打桩成 `return 0`、再把指引换成空串 —— 同一个
`_problems` 必须当场报出问题。没有这一条，上面的绿只证明"命令返回了一个数"。
"""
from __future__ import annotations

import inspect
import pathlib

import pytest

from agentflow import cli

REPO = pathlib.Path(__file__).resolve().parents[1]

#: 每一条：命令行、退场标签、替代指引里必须出现的那几段。
#:
#: 期望值是**独立抄写**的（不从 `cli.RETIRED_COMMANDS` 现读）：读被测表来给自己判卷
#: 会让"指引被改空"与"判据没查"变成同一件事。四个标签各至少一条；`repair` 那一半
#: 还在的 `--backfill-grades` 也要被点到（退场不等于整条命令消失）。
CASES: tuple[tuple[tuple[str, ...], str, tuple[str, ...]], ...] = (
    (("rebuild",), "rebuild", ("agentflow verify", "make_store", "events.jsonl")),
    (("repair",), "repair", ("--backfill-grades", "related_drift", "agentflow verify")),
    (("repair", "--related"), "repair", ("relations", "--backfill-grades")),
    (("run", "repair"), "repair", ("related_drift",)),
    (("demo",), "demo", ("agentflow.demo", "run_demo", "agentflow doctor")),
    (("evidence", "migrate", "<root>"), "evidence migrate",
     ("evidence verify", "evidence store")),
)


def _argv(template: tuple[str, ...], root: pathlib.Path) -> list[str]:
    """把 `--root <工作区>` 放在子命令之前（全局开关的位置），并填掉 `<root>` 占位符。"""
    body = [str(root) if part == "<root>" else part for part in template]
    return ["--root", str(root), *body]


def _problems(argv: list[str], label: str, needles: tuple[str, ...], capsys) -> list[str]:
    """一次受控退场该满足的全部读数；返回问题清单（空 = 全对）。"""
    capsys.readouterr()
    code = cli.main(argv)
    out, err = capsys.readouterr()
    problems: list[str] = []
    if code != 2:
        problems.append(f"退出码是 {code}，必须是 2（没查成；0 会把退场读成跑过了）")
    if out.strip():
        problems.append(f"stdout 不为空（退场层不许冒充一次成功的输出）：{out!r}")
    if f"[{label}]" not in err:
        problems.append(f"stderr 里没有命令标签 [{label}]：{err!r}")
    if "已退场" not in err:
        problems.append(f"stderr 没说清「已退场」：{err!r}")
    if "退出码 2" not in err:
        problems.append(f"stderr 没把退出码 2 的含义写出来：{err!r}")
    for needle in needles:
        if needle not in err:
            problems.append(f"替代指引里缺 {needle!r}：{err!r}")
    return problems


def _all_cases(root: pathlib.Path):
    for template, label, needles in CASES:
        yield _argv(template, root), label, needles


def test_the_four_legacy_commands_are_controlled_retirements(tmp_path, capsys) -> None:
    """四条（含分组路径 `run repair`）都：退出码 2、stdout 空、明确退场 + 替代指引。"""
    root = tmp_path / "ws"
    root.mkdir()
    before = sorted(p.relative_to(root).as_posix() for p in root.rglob("*"))
    problems: list[str] = []
    for argv, label, needles in _all_cases(root):
        problems.extend(_problems(argv, label, needles, capsys))
    assert not problems, "\n".join(problems)
    # 退场层一行都不许碰盘：四条命令跑完，工作区与跑之前逐项相同（今天都是空）。
    after = sorted(p.relative_to(root).as_posix() for p in root.rglob("*"))
    assert after == before, f"退场层动了盘：{before} -> {after}"


def test_the_retired_verbs_still_parse_so_the_error_is_ours_not_argparses(tmp_path) -> None:
    """命令名与旧旗标仍能解析：用户拿到的是我们的退场说明，不是 `invalid choice`。"""
    parser = cli.build_parser()
    for argv in (
        ["--root", "WS", "rebuild", "--no-backup"],
        ["--root", "WS", "repair"],
        ["--root", "WS", "repair", "--related"],
        ["--root", "WS", "demo", "--keep"],
        ["--root", "WS", "evidence", "migrate", "WS", "--apply"],
    ):
        parser.parse_args(argv)  # 不抛 SystemExit 就是通过


def test_the_legacy_modules_and_the_forwarder_are_really_gone() -> None:
    """A4 的删除面：目录不在了，转发器不在了，四个命令体里也没有转发调用。"""
    assert not (REPO / "tools" / "legacy_cli").exists(), (
        "`tools/legacy_cli/` 还在盘上 —— A4 删的是它，不是只把命令改成 2")
    for attr in ("_legacy_module", "_LEGACY_TOOLS_DIR"):
        assert not hasattr(cli, attr), f"`cli.{attr}` 还在 ⇒ 转发层没删干净"
    for name in ("cmd_rebuild", "cmd_repair", "cmd_demo"):
        body = inspect.getsource(getattr(cli, name))
        assert "_legacy_module" not in body, f"`{name}` 里还在调转发器：{body}"
        assert "_retired(" in body, f"`{name}` 没有走受控退场：{body}"


def test_the_library_implementations_were_not_deleted_with_the_cli_layer() -> None:
    """反方向：退场的是 CLI 那一层，库里真正干活的实现必须还在（否则删过头了）。"""
    from agentflow import demo
    from agentflow.store import Store

    assert callable(demo.run_demo), "`demo.run_demo` 不见了 —— 删的是命令行，不是演示本身"
    assert callable(Store.rebuild), "`Store.rebuild` 不见了 —— 重放能力必须留在库里"
    assert callable(cli.make_store)


def test_anti_vacuum_stubbing_the_retirement_off_turns_the_criterion_red(
        tmp_path, capsys, monkeypatch: pytest.MonkeyPatch) -> None:
    """反真空：把退场打桩成 `return 0`、把指引换成空串 ⇒ 同一个 `_problems` 必报。

    两面都验：
    - 退出码 2 那一半来自 `_retired` 的返回值（打桩成 0 后必报）；
    - 替代指引那一半来自 `RETIRED_COMMANDS`（换成空串后必报）。
    两半同时打桩 ⇒ 问题清单非空；只打一半 ⇒ 另一半仍然拦得住。
    """
    root = tmp_path / "ws"
    root.mkdir()
    argv = ["--root", str(root), "rebuild"]

    monkeypatch.setattr(cli, "_retired", lambda command: 0)
    problems = _problems(argv, "rebuild", ("agentflow verify",), capsys)
    assert any("退出码" in p for p in problems), (
        f"把退场打桩成 return 0 之后判据仍然绿 ⇒ 退出码那一半没有牙：{problems}")

    monkeypatch.undo()
    monkeypatch.setitem(cli.RETIRED_COMMANDS, "rebuild", "")
    problems = _problems(argv, "rebuild", ("agentflow verify",), capsys)
    assert any("替代指引" in p for p in problems), (
        f"把替代指引打桩成空串之后判据仍然绿 ⇒ 指引那一半没有牙：{problems}")

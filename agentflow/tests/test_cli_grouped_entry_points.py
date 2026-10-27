# -*- coding: utf-8 -*-
"""判据：四个入口组把 29 个旧名收进分层，而旧名一个都没坏（业主批的 CLI 更新方案 A）。

## 形状

```text
incubate {init start stop status answer inbox submit}
inspect  {status-report stats evidence artifacts analyze tools cache budget doctor verify}
run      {topic(=run) pipeline run-a run-b run-agent repair rebuild project closing}
serve    {web demo}
```

## 这一份守什么

| 判据 | 它钉的是 | 改坏之后的样子 |
|---|---|---|
| ① | 29 个旧名逐个 `--help` 都退出 0 | 有人为了让新路径好看，动了某条老命令的 parser |
| ② | 新路径与旧名落到同一个函数对象（同一个 `func`） | 新路径自带一份实现，两份漂了没人看得见 |
| ③ | 首屏只露四个组名 + 一段"旧名仍可用"的说明，且旧名逐个都在那一屏上 | 首屏退回 28 行（分组白做），或者有名字静默消失 |
| ④ | 组名不在 `choices` 里（`canonical_argv` 在解析之前折回旧名） | 28 变 32，`README`/`DEVELOPMENT-SPEC` 的子命令数当场漂掉 |
| ⑤ | 组页（`agentflow inspect`）打得出成员表；不认识的成员是人话 + 退出码 2 | 用户拿到 `invalid choice: 'inspect'` |
| ⑥ | `--help-legacy` 的对照表逐行可执行（每行的新路径都能 `--help` 通过） | 文档里写着一条敲不通的路径 |

## 为什么 ② 要用"同一个函数对象"

"新路径是别名"这句话最容易退化成"新路径调了一个同名包装函数"。包装函数本身也能跑，
所以只能钉对象身份：`build_parser()` 把 `cmd_x` 这个函数对象塞进 `set_defaults`，
两条路取出来的 `func` 必须是同一个对象 —— 差一个对象就是差一份实现。

## 负控

③ 的"旧名逐个都在那一屏上"是被 `LEGACY_COMMANDS` 驱动的：删一条登记，那一句就红。
④ 的"28"是 `build_parser()` 的 choices 现数出来的，不是抄来的常量。
"""
from __future__ import annotations

import io
from contextlib import redirect_stderr, redirect_stdout

import pytest

from agentflow import cli

#: 四个组名（顺序即首屏顺序）。
GROUPS: tuple[str, ...] = ("incubate", "inspect", "run", "serve")


def _run(argv: list[str]) -> tuple[int, str, str]:
    """进程内跑一次 CLI，返回 `(退出码, stdout, stderr)`（`--help` 会抛 SystemExit）。"""
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        try:
            code = cli.main(argv)
        except SystemExit as exc:  # argparse: --help(0) / 用法错(2)
            code = int(exc.code or 0)
    return int(code or 0), out.getvalue(), err.getvalue()


# ---------------------------------------------------------------- ① 旧名逐个 --help


@pytest.mark.parametrize("name", cli.LEGACY_COMMANDS)
def test_every_legacy_command_still_answers_help(name: str) -> None:
    """① 29 个旧名逐个 `--help`：退出码 0，且它自己的 usage 行里有自己。"""
    code, out, err = _run([name, "--help"])
    assert code == 0, (name, code, err)
    assert f"agentflow {name}" in out, (name, out[:200])


# ---------------------------------------------------------------- ② 同一个 handler


def test_the_group_path_and_the_legacy_name_share_one_function_object(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """② 每个旧名与它的新路径都落到同一个 `func` 对象上（不是同名包装函数）。

    用桩函数替换那几个 handler 之后重新建 parser：`set_defaults(func=...)` 读的是
    建 parser 那一刻的模块属性，所以桩会被装进 choices —— 于是"两条路是同一个对象"
    这件事可以对着一个能记账的桩断言，而不是对着 `cmd_tools.__name__`。

    选的这八条覆盖四个组、并且都没有必填的位置参数（有必填位置参数的那几条 ——
    `answer <qid>` / `run-agent <role>` 之类 —— 由下一条普查按"折回旧名"钉住，
    它们的 `func` 身份与这里同源）。
    """
    table: tuple[tuple[str, str, str], ...] = (
        ("cmd_tools", "tools", "inspect tools"),
        ("cmd_doctor", "doctor", "inspect doctor"),
        ("cmd_stats", "stats", "inspect stats"),
        ("cmd_analyze", "analyze", "inspect analyze"),
        ("cmd_status", "status", "incubate status"),
        ("cmd_budget", "budget", "inspect budget"),
        ("cmd_closing", "closing", "run closing"),
        ("cmd_demo", "demo", "serve demo"),
    )
    for attr, old_name, path in table:
        seen: list[str] = []

        def _stub(args, _seen=seen):
            _seen.append(str(getattr(args, "cmd", "")))
            return 0

        monkeypatch.setattr(cli, attr, _stub)
        parser = cli.build_parser()
        new = parser.parse_args(cli.canonical_argv(path.split()))
        old = parser.parse_args([old_name])
        assert old.func is new.func is _stub, (path, old.func, new.func)
        assert cli.main([old_name]) == 0, old_name
        assert cli.main(path.split()) == 0, path
        assert seen == [old_name, old_name], (path, seen)


def test_every_new_path_folds_back_to_its_legacy_command() -> None:
    """② 的普查版：对照表里每一行都折回它的旧名，且 handler 是同一个默认值对象。

    为什么允许"靠折回旧名"来证明：新路径没有自己的 parser（组名不在 choices 里）。
    所以"同一份实现"的唯一形态就是"折回同一个 argv"，而 argv 一样 ⇒ 同一个 parser ⇒
    同一个 `func`。这里把后半句也真的比一遍（`get_default("func")`），免得将来有人给
    新路径另开一个 parser 而这条判据还绿。
    """
    parser = cli.build_parser()
    action = next(a for a in parser._actions if getattr(a, "choices", None))
    for old_name, path in cli.command_paths():
        folded = cli.canonical_argv(path.split())
        assert folded[0] == old_name, (path, folded)
        child = action.choices[old_name]
        func = child.get_default("func")
        assert callable(func), (old_name, func)
        # handler 要么在 cli 里，要么在它明确授权的模块里（`cache` 那一组的实现真身在
        # `cachectl`：命令行的按钮与网页的按钮读同一份实现，这是刻意的那一种"不在 cli"）。
        assert getattr(func, "__module__", "") in {"agentflow.cli", "agentflow.cachectl"}, (
            old_name, func)
        # 新路径的成员名不在 choices 里（它只存在于 `GROUP_MEMBERS`）；
        # 唯一的例外是 `run`：那个词同时是旧命令名，它必须在 choices 里。
        member = path.split()[1]
        assert member not in action.choices or member == old_name, (path, member)


# ---------------------------------------------------------------- ③ 首屏


def test_the_first_screen_shows_only_the_groups_and_a_legacy_note() -> None:
    """③ 首屏只露四个组名 + 一段说明；29 个旧名逐个都在那一屏上。"""
    code, out, err = _run(["--help"])
    assert code == 0, (code, err)
    for group in GROUPS:
        assert group in out, group
    assert "旧名仍可用" in out, out
    for name in cli.LEGACY_COMMANDS:
        assert name in out, f"首屏上没有 {name}（它只能出现在『旧名仍可用』那一段里）"
    # 反真空：29 个旧名不是一个空表（否则上面那个循环恒绿）
    assert len(cli.LEGACY_COMMANDS) == 29, sorted(cli.LEGACY_COMMANDS)


# ---------------------------------------------------------------- ④ 组名不进 choices


def test_the_group_names_are_not_subcommands() -> None:
    """④ 四个组名不在 `choices` 里：它们由 `canonical_argv` 在解析之前折回旧名。

    这一条为什么重要：组名一旦进 `choices`，子命令数就从 28 变成 32，而
    `README.md` 与 `docs/DEVELOPMENT-SPEC.md` 两处读数会当场漂掉（各有判据钉着）。
    """
    parser = cli.build_parser()
    subs = [a for a in parser._actions if getattr(a, "choices", None)]
    assert len(subs) == 1
    names = set(subs[0].choices)
    assert names == set(cli.LEGACY_COMMANDS), names ^ set(cli.LEGACY_COMMANDS)
    for group in GROUPS:
        if group in cli.LEGACY_COMMANDS:
            # `run` 是唯一一个"组名同时是旧命令名"的：它必须在 choices 里（那条旧命令
            # 一个字都不许动），而这也正是它的组页走 `--help`、裸命令照旧的原因。
            assert group in names, group
            assert group == "run", group
            continue
        assert group not in names, f"{group} 进了 choices（28 会变成 32）"


# ---------------------------------------------------------------- ⑤ 组页与人话


def test_each_group_page_lists_its_members() -> None:
    """⑤ 组页打得出成员表，且每个成员都在那一页上。"""
    for group in GROUPS:
        code, out, err = _run([group, "--help"])
        assert code == 0, (group, code, err)
        assert f"agentflow {group}" in out, (group, out[:200])
        for member in cli.GROUP_MEMBERS[group]:
            assert member in out, (group, member)


def test_an_unknown_member_is_human_words_and_exit_two() -> None:
    """⑤ 组里没有这个成员 ⇒ 人话 + 退出码 2（不是 `invalid choice` 的堆栈）。"""
    code, out, err = _run(["inspect", "nope"])
    assert code == 2, (code, out, err)
    assert "没有" in err and "nope" in err, err
    assert "组内成员" in err, err
    assert "invalid choice" not in err, err


def test_the_run_group_keeps_its_legacy_bare_form() -> None:
    """⑤ `agentflow run` 裸着敲仍是那条旧命令（缺 --topic ⇒ 2），组页走 `--help`。

    这一条是"同名"那个坑的钉子：组名与旧命令同名时，裸命令必须原样交给 argparse ——
    把裸 `run` 改成打组页就等于改了那条命令的行为。
    """
    code, out, err = _run(["run"])
    assert code == 2, (code, out, err)
    assert "--topic" in err, err
    code, out, err = _run(["run", "--help"])
    assert code == 0, (code, out, err)
    assert "跑：流水线与角色循环" in out, out[:200]
    assert "--topic" in out, "组页后面必须接上旧命令自己的 help（旗标一个都不能丢）"


# ---------------------------------------------------------------- ⑥ 对照表逐行可执行


def test_every_row_of_the_legacy_table_is_executable() -> None:
    """⑥ `--help-legacy` 的每一行（旧名与它的新路径）都能 `--help` 通过。"""
    code, out, err = _run(["--help-legacy"])
    assert code == 0, (code, err)
    assert "旧名 → 新路径" in out, out[:200]
    for old_name, path in cli.command_paths():
        assert f"agentflow {path}" in out, (old_name, path)
        code, sub_out, sub_err = _run([*path.split(), "--help"])
        assert code == 0, (path, code, sub_err)
        assert old_name in sub_out or path.split()[-1] in sub_out, (path, sub_out[:200])
    # 与首屏那句说明同源：两处点名的是同一批旧名
    assert len(cli.command_paths()) == len(cli.LEGACY_COMMANDS) == 29

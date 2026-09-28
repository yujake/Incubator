"""交互台的判据：菜单可以在没有终端的情况下被脚本驱动，且退出语义是"不继续"。

为什么要测这个：交互界面最容易变成"只有手敲才能跑"的东西 —— 那它就无法进 CI，
于是它坏了也没人知道。这里用两个口子（`ask` / `out`）把整台菜单变成可测函数：
输入是脚本化的字符串序列，输出被收进一个列表。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agentflow import cli  # noqa: E402
from agentflow import tty  # noqa: E402


class Scripted:
    """脚本化的输入：预先给一串回答，问完了还问就抛 EOF（模拟管道结束）。"""

    def __init__(self, answers: list[str]) -> None:
        self.answers = list(answers)
        self.prompts: list[str] = []

    def __call__(self, prompt: str = "") -> str:
        self.prompts.append(prompt)
        if not self.answers:
            raise EOFError
        return self.answers.pop(0)


class Sink:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def __call__(self, text: str = "") -> None:
        self.lines.append(str(text))

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


@pytest.fixture(autouse=True)
def _no_color():
    tty.set_style(color=False, charset="ascii", width_px=76)
    yield
    tty.set_style(color=False, charset="ascii", width_px=76)


def test_menu_lists_every_action() -> None:
    sink = Sink()
    rc = cli.shell(ask=Scripted(["q"]), out=sink)
    assert rc == 0
    for key, text, _fn in cli.MENU:
        assert key in sink.text
        assert text.split("（")[0][:6] in sink.text
    assert "退出" in sink.text


def test_empty_input_quits_cleanly() -> None:
    """回车（空输入）算"不想继续"，不是错误 —— 退出码必须是 0。"""
    assert cli.shell(ask=Scripted([""]), out=Sink()) == 0


def test_eof_quits_cleanly() -> None:
    assert cli.shell(ask=Scripted([]), out=Sink()) == 0


def test_unknown_choice_hints_and_keeps_going() -> None:
    sink = Sink()
    rc = cli.shell(ask=Scripted(["7", "q"]), out=sink)
    assert rc == 0
    assert "没有这一项" in sink.text


def test_menu_dispatches_and_reports_the_exit_code(monkeypatch) -> None:
    called: list[str] = []

    def _stub(ask, out) -> int:
        called.append("hit")
        return 7

    monkeypatch.setitem(cli.SHELL_ACTIONS, "1", _stub)
    sink = Sink()
    rc = cli.shell(ask=Scripted(["1", "q"]), out=sink)
    assert called == ["hit"]
    assert rc == 0, "菜单本身正常退出；上一步的退出码只如实打出来，不冒充菜单的退出码"
    assert "上一步退出码 7" in sink.text


def test_ask_text_uses_default_on_empty() -> None:
    assert cli._ask_text(Scripted([""]), "书", "D:\\books") == "D:\\books"
    assert cli._ask_text(Scripted(["x"]), "书", "D:\\books") == "x"


def test_ask_yes_defaults_and_parses() -> None:
    assert cli._ask_yes(Scripted([""]), "继续", default=True) is True
    assert cli._ask_yes(Scripted([""]), "继续", default=False) is False
    assert cli._ask_yes(Scripted(["y"]), "继续") is True
    assert cli._ask_yes(Scripted(["是"]), "继续") is True
    assert cli._ask_yes(Scripted(["nope"]), "继续") is False


def test_main_without_arguments_enters_the_shell(monkeypatch) -> None:
    seen: list[int] = []

    def _fake_shell(*_a, **_k) -> int:
        seen.append(1)
        return 0

    monkeypatch.setattr(cli, "shell", _fake_shell)
    assert cli.main([]) == 0
    assert seen == [1], "不带任何参数时必须进交互台，而不是打一串用法错误"


def test_project_menu_builds_the_run_argv(monkeypatch) -> None:
    """菜单第 1 项要能把"用户答的几件事"翻成 `project run` 的 argv（且不真跑）。"""
    captured: list[list[str]] = []

    def _fake_main(argv) -> int:
        captured.append(list(argv))
        return 0

    monkeypatch.setattr(cli, "main", _fake_main)
    monkeypatch.setattr(cli, "_project_rows", lambda: [])
    answers = Scripted(["project9", "D:\\books", "主题一", "y", "3"])
    rc = cli._shell_project(answers, Sink())
    assert rc == 0
    assert captured == [["project", "run", "--name", "project9", "--books", "D:\\books",
                         "--topic", "主题一", "--extract", "--extract-rounds", "3"]]


def test_project_menu_without_books_skips_extraction(monkeypatch) -> None:
    captured: list[list[str]] = []
    monkeypatch.setattr(cli, "main", lambda argv: captured.append(list(argv)) or 0)
    monkeypatch.setattr(cli, "_project_rows", lambda: [])
    # 全回车之后要显式确认一次（见下面那条负控），所以这里给第 4 个回答 y。
    cli._shell_project(Scripted(["", "", "", "y"]), Sink())
    assert captured == [["project", "run"]], "确认后也只带一个动词，不带任何开关"


def test_run_menu_refuses_an_empty_topic(monkeypatch) -> None:
    """负控：主题为空时必须不调模型并以退出码 2 结束，而不是编一个主题跑起来。"""
    called: list[list[str]] = []
    monkeypatch.setattr(cli, "main", lambda argv: called.append(list(argv)) or 0)
    sink = Sink()
    rc = cli._shell_run(Scripted([""]), sink)
    assert rc == 2 and called == []
    assert "没给主题" in sink.text


def test_status_menu_can_ask_for_verify(monkeypatch) -> None:
    called: list[list[str]] = []
    monkeypatch.setattr(cli, "main", lambda argv: called.append(list(argv)) or 0)
    cli._shell_status(Scripted(["y"]), Sink())
    assert called[0] == ["status"] and called[1] == ["verify"]


def test_project_menu_does_not_create_a_folder_on_three_empty_answers(monkeypatch) -> None:
    """负控：三个问题全按回车时必须不建项目文件夹。

    2026-09-28 实测踩到：一次菜单冒烟测试（全回车）静默建出了 `project2`，
    项目卡里 run-1 的 result 是 None。新建目录是不可逆的动作，
    不该由三次回车触发 —— 所以缺省答案必须是"不建"。
    """
    called: list[list[str]] = []
    monkeypatch.setattr(cli, "main", lambda argv: called.append(list(argv)) or 0)
    monkeypatch.setattr(cli, "_project_rows", lambda: [])
    sink = Sink()
    rc = cli._shell_project(Scripted(["", "", "", ""]), sink)
    assert rc == 0 and called == [], f"全回车竟然去跑了：{called}"
    assert "没有建任何东西" in sink.text


def test_project_menu_creates_when_the_user_confirms(monkeypatch) -> None:
    """正控：全回车之后明确答 y ⇒ 才允许去建（否则上面那条只是"永远不建"）。"""
    called: list[list[str]] = []
    monkeypatch.setattr(cli, "main", lambda argv: called.append(list(argv)) or 0)
    monkeypatch.setattr(cli, "_project_rows", lambda: [])
    cli._shell_project(Scripted(["", "", "", "y"]), Sink())
    assert called == [["project", "run"]]


def test_project_menu_echoes_what_it_will_run(monkeypatch) -> None:
    """跑之前必须把"即将执行什么"打出来 —— 菜单不该让人猜它调了什么。"""
    monkeypatch.setattr(cli, "main", lambda argv: 0)
    monkeypatch.setattr(cli, "_project_rows", lambda: [])
    sink = Sink()
    cli._shell_project(Scripted(["", "D:\\books", "群论", "n"]), sink)
    assert "即将执行：agentflow project run --books D:\\books --topic 群论" in sink.text


def test_exit_badge_keeps_the_three_states_apart() -> None:
    """退出码徽标：0/1/2 是三态，不许把 2（没查成）画成 1（查过了、失败）。

    第一版写成 `success if code == 0 else failed`，于是"没 key ⇒ 退出码 2"被画成
    红色 failed —— 读的人会去查结论，而该做的动作是去配 key 或重试。
    """
    assert "success" in cli._exit_badge(0)
    assert "failed" in cli._exit_badge(1)
    assert "没查成" in cli._exit_badge(2), "退出码 2 必须落『没查成』那一档"
    assert "failed" not in cli._exit_badge(2)
    # 没见过的退出码必须原样打出来，不编一个档
    assert "9" in cli._exit_badge(9)


def test_state_badge_maps_all_four_folder_states() -> None:
    assert "ok" in cli._state_badge("workspace")
    assert "cold" in cli._state_badge("absent")
    assert "cold" in cli._state_badge("empty")
    assert "unknown" in cli._state_badge("not_a_project")

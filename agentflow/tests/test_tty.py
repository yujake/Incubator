"""`tty` 的判据：好看这件事也要可判定 —— 框必须真对齐、颜色必须真能关掉。

这一组里最重要的两条不是"看起来对不对"，而是结构性的：

* `test_panel_lines_all_have_the_same_display_width`：一个框里每一行的显示列数
  必须相等。CJK 在等宽终端里占两列，用 `len()` 补空格就会差一截 —— 而"框对不齐"
  正是那种"看上去没做完"的细节，且没有任何别的判据会红。
* `test_no_ansi_when_not_a_tty`：管道/重定向/CI 捕获时不许出现转义序列，
  否则日志里混进 `\x1b[36m`，人读的时候只会觉得这工具脏。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agentflow import tty  # noqa: E402


def _plain(fn, *args, **kwargs):
    """在"无颜色 + 指定字符集 + 指定宽度"下渲染，返回行列表。"""
    tty.set_style(color=False, charset="unicode", width_px=80)
    out = fn(*args, **kwargs)
    return out if isinstance(out, list) else [out]


def test_width_is_clamped() -> None:
    assert 56 <= tty.default_width(minimum=56, maximum=100) <= 100
    tty.set_style(color=False, charset="ascii", width_px=40)
    assert tty.width() == 40


def test_display_width_counts_cjk_as_two() -> None:
    assert tty.display_width("ab") == 2
    assert tty.display_width("中文") == 4
    assert tty.display_width("a中") == 3


def test_truncate_respects_display_width() -> None:
    assert tty.display_width(tty.truncate("中" * 10, 7)) <= 7
    assert tty.truncate("hello world", 5).endswith("…")
    assert tty.truncate("hi", 5) == "hi"


def test_panel_lines_all_have_the_same_display_width() -> None:
    lines = _plain(tty.panel, "标题 title", [("键", "值"), ("很长的键名", "很长的值" * 20)],
                   body=["正文一行", "另一行 " * 40])
    widths = {tty.display_width(line) for line in lines}
    assert len(widths) == 1, f"框里每行的显示宽度必须相同，实测 {sorted(widths)}"


def test_panel_ascii_fallback_has_no_box_chars() -> None:
    tty.set_style(color=False, charset="ascii", width_px=70)
    joined = "\n".join(tty.panel("t", [("k", "v")]))
    assert all(ch not in joined for ch in "─│┌┐└┘├┤┬┴┼")
    assert "+" in joined


def test_table_lines_all_have_the_same_display_width() -> None:
    lines = _plain(tty.table, ("项目", "状态", "说明"),
                   [("project1", "ok", "文件夹存在且是一个初始化过的工作区"),
                    ("project2", "unknown", "短")],
                   aligns=("left", "left", "left"))
    widths = {tty.display_width(line) for line in lines}
    assert len(widths) == 1, f"表里每行的显示宽度必须相同，实测 {sorted(widths)}"


def test_table_narrows_itself_to_the_terminal() -> None:
    tty.set_style(color=False, charset="ascii", width_px=60)
    lines = tty.table(("a", "b", "c", "d"),
                      [("x" * 40, "y" * 40, "z" * 40, "w" * 40)])
    assert all(tty.display_width(line) <= 60 for line in lines), \
        "表宽超过屏宽时应当按比例收窄，而不是把终端撑破"


def test_no_ansi_when_style_disabled() -> None:
    tty.set_style(color=False, charset="unicode", width_px=80)
    joined = "\n".join(tty.panel("t", [("k", "v")]) + tty.table(("h",), [("v",)]))
    assert "\x1b[" not in joined, "没开颜色时不许出现转义序列"


def test_ansi_only_when_style_enabled() -> None:
    tty.set_style(color=True, charset="unicode", width_px=80)
    try:
        assert "\x1b[" in tty.paint("x", "red")
        assert "\x1b[" in tty.badge("ok")
    finally:
        tty.set_style(color=False, charset="unicode", width_px=80)


def test_style_enabled_respects_no_color(monkeypatch) -> None:
    monkeypatch.setenv("NO_COLOR", "1")
    assert tty.style_enabled() is False
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("TERM", "dumb")
    assert tty.style_enabled() is False


def test_badge_covers_the_three_states_and_does_not_invent_colors() -> None:
    tty.set_style(color=False, charset="unicode", width_px=80)
    assert "ok" in tty.badge("ok")
    assert "unknown" in tty.badge("unknown")
    # 没登记过的状态名必须原样打出来（宁可露出一个陌生词，也不编一个颜色）
    assert "没登记过的状态" in tty.badge("没登记过的状态")


def test_bad_charset_is_rejected() -> None:
    try:
        tty.set_style(color=False, charset="emoji", width_px=80)
    except ValueError as exc:
        assert "charset" in str(exc)
    else:  # pragma: no cover - 走到这里说明校验没生效
        raise AssertionError("非法的 charset 必须当场抛，不许静默退回默认值")
    tty.set_style(color=False, charset="unicode", width_px=80)


def test_progress_line_is_bounded() -> None:
    tty.set_style(color=False, charset="ascii", width_px=80)
    line = tty.progress_line(3, 10, "读书")
    assert tty.display_width(line) <= 80
    assert "30.0%" in line


def test_rule_fills_exactly_one_screen_width() -> None:
    tty.set_style(color=False, charset="unicode", width_px=80)
    assert tty.display_width(tty.rule("标题")) == 80
    assert tty.display_width(tty.rule()) == 80

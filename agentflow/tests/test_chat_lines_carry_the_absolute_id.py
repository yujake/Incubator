"""判据：对话线必须能回答"是哪个绝对编号的哪个角色"（业主 2026-10-21「全面接入」）。

## 钉三件事

1. **每一行都有 `task_id` 与 `task_id_source` 两个键**（缺键 = 页面无法显示"谁在说话"）；
2. `task_id_source` 只许是 `event` / `missing` 两值（**三态**：编号要么来自事件，
   要么显式标"这条事件没记" —— 不许空着不标，那会让读的人以为"这个代理没有编号"）；
3. 事件里**有** `task_id` 的那一行，`task_id_source` 必须是 `event`（负控：
   把有编号的行标成 missing 要红）。
"""

from __future__ import annotations

import pathlib
import sys

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agentflow.webui import readers  # noqa: E402


def _lines(events: list[dict]) -> list[dict]:
    out = []
    for i, ev in enumerate(events):
        line = readers._chat_line(i, ev)
        if line is not None:
            out.append(line)
    return out


def test_every_line_carries_the_absolute_id_keys() -> None:
    lines = _lines([
        {"kind": "agent_run_start", "role": "M", "task": "干活", "task_id": "t-000001"},
        {"kind": "agent_message", "from": "M", "to": "D", "channel": "private",
         "body": "派给你", "task_id": "t-000001"},
        {"kind": "agent_run_end", "role": "A", "final": "做完了"},
    ])
    assert lines, "这三条事件应该都进对话"
    for line in lines:
        assert "task_id" in line, line
        assert "task_id_source" in line, line
        assert line["task_id_source"] in ("event", "missing"), line


def test_an_id_from_the_event_is_marked_as_such() -> None:
    """负控：事件里真有编号，却标成 missing（或把编号丢了）⇒ 红。"""
    lines = _lines([{"kind": "agent_run_start", "role": "M", "task": "干活", "task_id": "t-000001"}])
    assert lines[0]["task_id"] == "t-000001"
    assert lines[0]["task_id_source"] == "event"


def test_a_line_without_an_id_says_so_instead_of_pretending() -> None:
    lines = _lines([{"kind": "agent_run_end", "role": "A", "final": "做完了"}])
    assert lines[0]["task_id"] == ""
    assert lines[0]["task_id_source"] == "missing"

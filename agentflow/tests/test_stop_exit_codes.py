# -*- coding: utf-8 -*-
"""停机开关的三个退出码（`draft/39` §3.11 D25，用户 2026-10-05 裁定）—— 也是 E6 的离线演练。

用户口径（逐字）：

> D25 搞退出码来分

裁定（`draft/39` §3.11 三）：`0` = 这次调用新写了开关（调用方可以清）；
`3` = 盘上已有一把别人写的开关（不许清，只能追加升级）；`4` = 没有开关（无需清）。

为什么它值得一条判据：驱动器此前只看"命令成没成功"，于是会把用户刚落的开关顺手撤掉
（"停完就清"）—— 那正是"用户叫停"这件事在系统里消失的形态。这条判据钉的就是
"别人的开关一律不许清"，并且要在真命令行上读退出码（不是只读内部函数的返回值）。
"""
from __future__ import annotations

import json
import pathlib

from agentflow import cli, stopctl


def _run(argv: list[str]) -> int:
    return int(cli.main(argv))


def test_e6_a_new_switch_is_zero_and_is_mine(tmp_path: pathlib.Path):
    """① 新写 ⇒ `0`，盘上真的有一把，且内容记着"是谁在什么时候为什么落的"。"""
    root = tmp_path / "ws"
    root.mkdir()
    code = _run(["--root", str(root), "stop", "--reason", "用户叫停"])
    assert code == 0, code
    state = stopctl.read_stop(root)
    assert state and state["reason"] == "用户叫停" and state["by"] == "user", state
    assert state["at"], state


def test_e6_a_second_caller_gets_three_and_the_first_reason_is_kept(tmp_path: pathlib.Path):
    """② 已有一把（别人写的）⇒ `3`，理由不许被覆盖（先到先得）。"""
    root = tmp_path / "ws"
    root.mkdir()
    assert _run(["--root", str(root), "stop", "--reason", "第一次"]) == 0
    # 第二个调用方（模拟驱动器/另一个进程）：不带 --clear，看它怎么回答
    second = _run(["--root", str(root), "stop", "--reason", "第二次"])
    assert second == 3, second
    state = stopctl.read_stop(root)
    assert state and state["reason"] == "第一次", state


def test_e6_force_on_someone_elses_switch_upgrades_but_still_says_three(tmp_path: pathlib.Path):
    """③ 在别人的开关上追加 `force` 升级是允许的，但它仍然是"别人的" ⇒ 仍是 `3`。"""
    root = tmp_path / "ws"
    root.mkdir()
    assert _run(["--root", str(root), "stop", "--reason", "优雅停"]) == 0
    code = _run(["--root", str(root), "stop", "--reason", "强杀", "--force"])
    state = stopctl.read_stop(root)
    assert state and state["force"] is True, state
    assert state["reason"] == "优雅停", "理由仍是第一次那份"
    assert state.get("escalated_at") and state.get("escalated_by"), state
    assert code in (2, 3), code      # 2 = 一个进程都没杀掉（本机登记为空时不会走到）⇒ 3


def test_e6_clear_says_zero_when_it_removed_something_and_four_when_empty(tmp_path: pathlib.Path):
    """④ `--clear`：撤掉了 ⇒ `0`；本来就空 ⇒ `4`（"没有开关"是与"撤掉了"不同的结局）。"""
    root = tmp_path / "ws"
    root.mkdir()
    assert _run(["--root", str(root), "stop", "--clear"]) == 4
    assert _run(["--root", str(root), "stop", "--reason", "落一把"]) == 0
    assert _run(["--root", str(root), "stop", "--clear"]) == 0
    assert stopctl.read_stop(root) is None
    assert _run(["--root", str(root), "stop", "--clear"]) == 4


def test_e6_the_detail_helper_reports_the_three_outcomes(tmp_path: pathlib.Path):
    """判据本体（纯函数那一层）：`created` / `existing` / `upgraded` 三态各自可判。"""
    root = tmp_path / "ws"
    root.mkdir()
    _payload, first = stopctl.request_stop_detail(root, reason="a", by="user")
    assert first == "created", first
    _payload, again = stopctl.request_stop_detail(root, reason="b", by="driver")
    assert again == "existing", again
    got, upgraded = stopctl.request_stop_detail(root, reason="c", by="user", force=True)
    assert upgraded == "upgraded" and got["force"] is True, (upgraded, got)


def test_e6_the_consumed_switch_does_not_come_back(tmp_path: pathlib.Path):
    """与"一次性开关"（`draft/37` §140）连起来：消费掉之后 `--clear` 回答 `4`。

    这两条是同一件事的两半：开关被消费 ⇒ 盘上没有了 ⇒ 驱动器下次来清时得到 `4`
    （"无需清"），而不是一把被重新写出来的开关。
    """
    root = tmp_path / "ws"
    root.mkdir()
    assert _run(["--root", str(root), "stop", "--reason", "停一趟"]) == 0
    record = stopctl.consume_stop(root, sid="s1")
    assert record and record.get("consumed_by_sid") == "s1", record
    assert stopctl.read_stop(root) is None
    assert _run(["--root", str(root), "stop", "--clear"]) == 4
    history = stopctl.stop_history(root)
    assert len(history) == 1 and history[0]["consumed_by_sid"] == "s1", history


def test_e6_status_answers_whether_a_loop_is_running(tmp_path: pathlib.Path, capsys):
    """D07 的读数（`draft/39` §2 那一行）：`--status` 要显式回答"在跑的循环：有/无"。

    为什么单列：旧形态只报 pid 登记，登记为空时读者会把"没人消费的开关"读成"没事"。
    这一条钉的是输出里有一行回答这件事（按 `agent_run_start` vs `agent_run_end` 判）。
    """
    from agentflow import sessions as SS

    root = tmp_path / "ws"
    root.mkdir()
    assert _run(["--root", str(root), "stop", "--status"]) == 0
    out = capsys.readouterr().out
    assert "在跑的循环" in out and "没有" in out, out

    path, problem = SS.append(root, {"kind": "agent_run_start", "role": "M", "task": "x"}, sid="t")
    assert not problem, problem
    assert _run(["--root", str(root), "stop", "--status"]) == 0
    out = capsys.readouterr().out
    assert "在跑的循环" in out and "有" in out and "M" in out, out
    SS.append(root, {"kind": "agent_run_end", "role": "M", "stop_reason": "final"}, sid="t")
    assert _run(["--root", str(root), "stop", "--status"]) == 0
    out = capsys.readouterr().out
    assert "没有" in out, out


def test_the_switch_file_payload_has_no_caller_outcome_in_it(tmp_path: pathlib.Path):
    """反真空：结局（created/existing/upgraded）不许写进开关文件。

    写进去会让下一次读它的人把"上一次是谁写的"与"这一次是谁在问"混起来
    （而那正是这个码要分清的东西）。
    """
    root = tmp_path / "ws"
    root.mkdir()
    stopctl.request_stop_detail(root, reason="a", by="user")
    raw = stopctl.stop_path(root).read_text(encoding="utf-8")
    assert "created" not in raw and "existing" not in raw, raw
    assert set(json.loads(raw)) >= {"reason", "by", "force", "at"}, json.loads(raw)

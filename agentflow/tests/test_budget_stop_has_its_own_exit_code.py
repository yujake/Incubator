"""给「预算耗尽」这一档定退出码 4（业主 2026-10-19 重排：它不再是"独立插一条"）。

为什么（来由没变，变的是 4 这个码的口径）：`_run_agent_exit_code` 原先只是一个 `if` 阶梯
（0 final / 3 waiting_for_user / 2 没查成 / 1 其余）。于是真机 `projects/mp4` 的 `mp4-7` 那趟
（`stop_reason="budget"`、已写出完整收尾说明、`--resume` 可续）返回了 1，而 1 的语义是"跑过了但没
给出 final" —— 把"钱花完的优雅停"读成了"这趟坏了"，与业主定的"停是否成功由 M 决定"直接冲突。

2026-10-19 业主重排之后（本条口径跟着改）：业主把这套码重排成六档，并把 4 的含义定成「系统行为
正常且中途停止：用户叫停（强停与优雅停同档）＋ 预算耗尽」—— 也就是说 `budget` 不再是一个为它单独
插进去的码，而是与 `stop_file` / `force_stop` 同一族（有人把它叫停，只是叫停的是钱）。所以：
`budget ⇒ 4` 不变（真机 `mp4-7` 那格读数一个字没变）；理由文案从"预算耗尽要独立一档"改成"预算是
'中途停止'那一族的一员"；判据从"表里有没有那条 if"改成"表里那一格 `"budget": 4` 在不在"（表在
`cli.EXIT_CODE_BY_STOP`，分类表本身由 `tests/test_run_agent_exit_code_table.py` 守）。

判据三条（断言一条都没删，只按新口径改期望值与负控的落点）：① `stop_reason="budget"` ⇒ 4（不是 1）；
② 同族对照：4 与 3（等人）仍是两件事，且 `stop_file` / `force_stop` 与它同为 4；③ 负控：把表里
那一格拿掉 ⇒ 同一 fixture 返回 1（证明这条判据真的在守它）。"""
from __future__ import annotations

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from agentflow import cli as CLI  # noqa: E402


class _Run:
    """最小替身：`_run_agent_exit_code` 只读 `stop_reason`。"""

    def __init__(self, stop_reason: str) -> None:
        self.stop_reason = stop_reason


def _code(stop_reason: str) -> int:
    return CLI._run_agent_exit_code(_Run(stop_reason))


def test_budget_exhaustion_is_its_own_code_not_a_failure() -> None:
    """正控：预算耗尽是中途停止（已写 final、可 --resume）⇒ 4，不许是 1。

    2026-10-19 业主重排：4 的含义是「系统行为正常且中途停止」—— 预算耗尽属于
    这一族（与用户叫停同档）。这张断言钉的仍是「不许读成 1（异常）」。
    """
    assert _code("budget") == 4, (
        "预算耗尽返回的不是 4：「钱花完了」被读成「这趟坏了」，"
        "与业主「停是否成功由 M 决定」冲突；重排后它属于"
        "「系统行为正常且中途停止」那一档")


def test_the_other_codes_are_untouched() -> None:
    """反真空：0/2/3 与异常档一个字没动（避免把 0/1/2/3 顺手改了）。

    2026-10-19 业主重排改掉了一处期望值（口径变更，不是削弱）：
    `no_progress_limit` 从 `1` 挪到 `5` —— 它原来是"跑过了但没给出 final（异常）"，
    现在被定成「系统行为正常且自行停止，但没有 final」。原断言留在原地，只是期望值
    随裁定走；谁把它改回 1，这一行就红。
    """
    assert _code("final") == 0
    assert _code("waiting_for_user") == 3
    assert _code("no_checkpoint") == 2
    assert _code("checkpoint_mismatch") == 2
    assert _code("bad_json_limit") == 1
    assert _code("model_timeout") == 1
    # 2026-10-19 业主重排：原句 `assert _code("no_progress_limit") == 1`
    # ⇒ 新句 `== 5`（"正常且自行停止、没有 final"那一档）。
    assert _code("no_progress_limit") == 5


def test_budget_is_not_folded_into_the_waiting_code() -> None:
    """反负控：4 与 3 是两件事（等人 vs 等钱/被叫停），不许合并。"""
    assert _code("budget") != _code("waiting_for_user")


def test_budget_sits_with_the_other_mid_way_stops() -> None:
    """同族正控（2026-10-19 重排新增的读数）：预算耗尽与用户叫停同为 4。

    为什么这条不许退化成"只测 budget"：重排把 4 定成"中途停止"这一族，
    只钉 budget 一格的话，把 `stop_file` 挪回 1（用户叫停被读成异常）也不会红。
    """
    assert _code("stop_file") == 4
    assert _code("force_stop") == 4
    assert _code("ask_cancelled") == 4
    assert _code("budget") == _code("stop_file") == _code("force_stop")


def test_negative_control_removing_the_branch_makes_it_one_again(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """负控：把「budget ⇒ 4」那一格从表里拿掉（= 没登记的样子）⇒ 同一输入返回 1。

    2026-10-19 重排之后，那条 if 变成了表里的一行（`"budget": 4,`），所以负控
    也跟着换成"从表里删掉这一格"—— 它证明的仍是同一句话：
    `test_budget_exhaustion_is_its_own_code_not_a_failure` 真的在守这一格，
    而不是"恰好通过"。
    """
    monkeypatch.delitem(CLI.EXIT_CODE_BY_STOP, "budget")

    class _R:
        def __init__(self) -> None:
            self.stop_reason = "budget"

    assert CLI._run_agent_exit_code(_R()) == 1, (
        "拿掉那一格之后应当回落到 1（行为异常）—— 这就是「漏登记」的形态")
    # 装回去，并确认这一格必须仍是 4（负控不许把现场留在坏状态上）。
    monkeypatch.setitem(CLI.EXIT_CODE_BY_STOP, "budget", 4)
    assert CLI._run_agent_exit_code(_R()) == 4, "现在这条必须仍是 4"

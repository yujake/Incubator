"""给「预算耗尽 = 优雅停、可续」一个独立退出码 4（业主 2026-10-19 裁定：做 1 不做 2）。

## 为什么

`_run_agent_exit_code` 原来的阶梯只区分四档（0 final / 3 waiting_for_user / 2 没查成 / 1 其余）。
于是真机 `projects/mp4` 的 `mp4-7` 那趟（`stop_reason="budget"`、**已写出完整收尾说明**、
`--resume` 可续）返回了 **1**，而 1 的语义是"跑过了但没给出 final"——把"钱花完的优雅停"
读成了"这趟坏了"。这与业主定的"**停是否成功由 M 决定**"直接冲突。

## 改法

`budget` 独立成 **4**：0/1/2/3 一档不动，只在阶梯里插一条。判据两条：
① `stop_reason="budget"` ⇒ 4（不是 1）；
② 负控：把那条分支拿掉 ⇒ 同一 fixture 返回 1（证明这条判据真的在守它）。
"""
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
    """正控：预算耗尽是**优雅停**（已写 final、可 --resume）⇒ 4，不许是 1。"""
    assert _code("budget") == 4, (
        "预算耗尽返回的不是 4：「钱花完了」被读成「这趟坏了」，"
        "与业主「停是否成功由 M 决定」冲突")


def test_the_other_codes_are_untouched() -> None:
    """反真空：另外四档一个字没动（避免把 0/1/2/3 顺手改了）。"""
    assert _code("final") == 0
    assert _code("waiting_for_user") == 3
    assert _code("no_checkpoint") == 2
    assert _code("checkpoint_mismatch") == 2
    assert _code("bad_json_limit") == 1
    assert _code("model_timeout") == 1
    assert _code("no_progress_limit") == 1


def test_budget_is_not_folded_into_the_waiting_code() -> None:
    """反负控：4 与 3 是**两件事**（等人 vs 等钱），不许合并。"""
    assert _code("budget") != _code("waiting_for_user")


def test_negative_control_removing_the_branch_makes_it_one_again(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """负控：把「budget ⇒ 4」那条拿掉（= 改前的行为）⇒ 同一输入返回 1，判据当场红。

    这条证明 `test_budget_exhaustion_is_its_own_code_not_a_failure` 真的在守这一格，
    而不是"恰好通过"。
    """
    import inspect

    src = inspect.getsource(CLI._run_agent_exit_code)
    old = src.replace('    if run.stop_reason == "budget":\n        return 4\n', "")
    assert old != src, "负控夹具前提：源码里应当有「budget ⇒ 4」那两行"
    ns: dict[str, object] = {}
    exec(compile(old, "<neg-control>", "exec"), dict(CLI.__dict__), ns)  # noqa: S102
    old_fn = ns["_run_agent_exit_code"]  # type: ignore[index]

    class _R:
        def __init__(self) -> None:
            self.stop_reason = "budget"

    assert old_fn(_R()) == 1, "去掉分支后应当回落到 1（这就是改前的错误行为）"
    assert CLI._run_agent_exit_code(_R()) == 4, "现在这条必须仍是 4"

# -*- coding: utf-8 -*-
"""自检入口的退出码契约（`SELF-CHECK-FINDINGS.md` 的 F-7 / F-4）。
## 这条判据守的是什么
"失败没有退出码"比失败本身更贵：任何基于退出码的门（CI / 发布检查 /`release_all` / `python -m agentflow.agent_c` 的手工复跑）都会把一次真实的失败读成"通过"，
而折平成通过的那一档不会有人再来修。所以这里只钉一件事：
- 输出里有 `SELF-CHECK FAILED` / `FAILED:` / `[FAIL]` ⇒ 退出码 必须非零；- 输出里有 `SELF-CHECK DONE`（或整段全 `[PASS]`）⇒ 退出码 必须为零；-
两样都没有 ⇒ 这条判据没量成（判红，不当作通过 —— 三态纪律："没量到"既不是"通过"也不是"失败"）。
## 为什么必须起子进程
退出码是进程级读数，而这三个自检都住在 `if __name__ == "__main__":` 里（`agent_c/__main__.py`、`agent_e/__main__.py`、`agent_v/__main__.py`）
：import 期它们根本不存在。进程内 `runpy` 也不行 —— `SystemExit` 会被 pytest当成"测试自己退出了"，量到的不是被测代码的退出码。
## 负控：为什么每条契约都配一次"注入失败"
真自检今天是绿的，于是"`DONE` ⇒ 0"在绿的那一侧永远成立 —— 它证明不了"红了会怎样"（F-7 的现场正是"红着、退出码却是 0"）。所以每条契约都另起一次子进程，先把自检读到的一个方法换成恒错的替身，再
`runpy.run_module(..., run_name="__main__")`：
| 角色 | 注入点 | 注入后必然失败的检查 |
|---|---|---|
| C | `AgentC.neighbors` 恒返回空邻居 | `[15]` 的 4 条邻居判据 |
| E | `AgentE.evidence_for` 恒说"查过了、没有" | `[7]` 的三态判据 |
| V | `AgentV.list_verifications` 恒返回 0 行 | 追加式编号 / 全量两条判据 |
没有一行生产代码为测试让路：注入点是子进程内的模块全局，产品路径不知道它存在，也不接受任何"测试模式"开关。修好前这条判据红（`FAILED` + 退出码 0），修好后绿 —— 同一个断言在两个方向上都被量过。
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

#: 子进程的 stdio 编码钉死（`X-91.5-2`：本机 `chcp` = 936，不钉就会在断言里
#: 读到自己造出来的乱码）。
_ENV = {
    **os.environ,
    "PYTHONIOENCODING": "utf-8",
    "PYTHONUTF8": "1",
    "PYTHONPATH": str(REPO / "src"),
    # `settings.py` 的出厂默认是 `lean_enabled=false`（业主 2026-10-12 的
    # "默认关闭省下形式化那笔钱"），而 `tests/conftest.py` 为了让形式化那一段
    # 能跑，把环境变量钉成了 `1`。这里量的是出厂默认那条路（F-4 的现场
    # 就是它），所以显式写回 `0`，不吃 pytest 会话的那一份。
    "AGENTFLOW_LEAN_ENABLED": "0",
}

#: 负控注入（各自只换一个方法，返回值都"形状合法、结论错"）。
_INJECT = {
    "agent_c": """
from agentflow.agent_c.core import AgentC

def _fake_neighbors(self, *a, **k):
    return {"nodes": [], "truncated": False, "reason": "负控注入：邻居恒空",
            "checked": True, "empty": True}

AgentC.neighbors = _fake_neighbors
""",
    "agent_e": """
from agentflow.agent_e.core import AgentE

def _fake_evidence_for(self, *a, **k):
    return {"checked": True, "experiments": [], "proved": False, "reason": "负控注入"}

AgentE.evidence_for = _fake_evidence_for
""",
    "agent_v": """
from agentflow.agent_v.core import AgentV

def _fake_list_verifications(self, *a, **k):
    return {"checked": True, "total": 0, "items": [], "problems": [],
            "truncated": False, "reason": "负控注入"}

AgentV.list_verifications = _fake_list_verifications
""",
}

#: 负控里"必然红"的最少 FAIL 条数（只用来防"注入没生效"造成的假绿）。
_MIN_FAILS = {"agent_c": 1, "agent_e": 1, "agent_v": 1}


def _run(module: str, *, inject: bool = False) -> subprocess.CompletedProcess:
    if inject:
        code = _INJECT[module] + (
            f"\nimport runpy\nrunpy.run_module({'agentflow.' + module!r}, run_name='__main__')\n"
        )
        argv = [sys.executable, "-c", code]
    else:
        argv = [sys.executable, "-m", f"agentflow.{module}"]
    return subprocess.run(
        argv, cwd=str(REPO), capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=900, env=_ENV,
    )


def _tail(proc: subprocess.CompletedProcess, n: int = 1600) -> str:
    out = (proc.stdout or "") + (proc.stderr or "")
    return out[-n:]


def _assert_exit_code_agrees(proc: subprocess.CompletedProcess, module: str) -> str:
    """三态判据：`FAILED` ⇒ 非零；`DONE` ⇒ 零；都没有 ⇒ 判"没量成"。"""
    out = _tail(proc, 6000)
    failed = ("SELF-CHECK FAILED" in out) or ("FAILED:" in out) or ("[FAIL]" in out)
    done = "SELF-CHECK DONE" in out
    if failed and done:
        pytest.fail(
            f"{module}：同一次输出里既有 `FAILED` 又有 `SELF-CHECK DONE` —— "
            f"汇总行与检查结论自相矛盾（读者无从判断该信哪一半）。尾部：\n{out}"
        )
    if not failed and not done:
        pytest.fail(
            f"{module}：既没有 `FAILED` 也没有 `SELF-CHECK DONE` ⇒ 这条判据**没量成**"
            f"（三态纪律：没量到不许当通过）。退出码={proc.returncode}，尾部：\n{out}"
        )
    # 汇总行必须说清"几项通过 / 几项失败"——只打一个词不算可机械读出的汇总。
    assert "项通过" in out and "项失败" in out, (
        f"{module}：有结论词但没有可机械读出的汇总行（`N 项通过 / M 项失败`）。"
        f"尾部：\n{out}"
    )
    if failed:
        assert proc.returncode != 0, (
            f"{module}：自检输出 `FAILED` 而退出码是 0 —— F-7 的原形态。尾部：\n{out}"
        )
        return "failed"
    assert proc.returncode == 0, (
        f"{module}：自检输出 `SELF-CHECK DONE`（全过）而退出码是 {proc.returncode} "
        f"—— F-4 的反向形态。尾部：\n{out}"
    )
    return "done"


@pytest.mark.parametrize("module", ["agent_c", "agent_e", "agent_v"])
def test_selfcheck_exit_code_agrees_with_the_printed_summary(module: str) -> None:
    """正控：真实自检必须打印汇总行，且退出码与它一致。

    修好前这条对 `agent_c` 红（`FAILED` + 退出码 0）、对 `agent_e` 红
    （`0 项失败`/无汇总行 + 退出码 1）、对 `agent_v` 红（`[FAIL]` 无汇总行）。
    """
    proc = _run(module)
    verdict = _assert_exit_code_agrees(proc, module)
    assert verdict == "done", (
        f"{module}：真实自检仍然是红的 —— 修代码或如实登记，**不要**把汇总行删掉。"
        f"尾部：\n{_tail(proc)}"
    )


@pytest.mark.parametrize("module", ["agent_c", "agent_e", "agent_v"])
def test_selfcheck_negative_control_an_injected_failure_must_go_red(module: str) -> None:
    """负控：注入一个"形状合法、结论错"的替身 ⇒ `FAILED` + 非零退出码。

    这一条证明上面那条判据真的会红：它不是"读一遍代码觉得对"，
    而是把失败造出来、看退出码是不是跟着变。
    """
    proc = _run(module, inject=True)
    verdict = _assert_exit_code_agrees(proc, module)
    assert verdict == "failed", (
        f"{module}：注入了必然失败的替身，自检却仍然报 `DONE` ⇒ 判据没有牙。"
        f"尾部：\n{_tail(proc)}"
    )
    out = _tail(proc, 6000)
    fails = out.count("[FAIL]") + out.count("FAILED:")
    assert fails >= _MIN_FAILS[module], (
        f"{module}：注入了失败却几乎没看到 `[FAIL]`（{fails} 条）⇒ 注入点可能没生效，"
        f"这条负控会以'未命中'的形态假绿。尾部：\n{out}"
    )

# -*- coding: utf-8 -*-
"""判据：能力表审计是显式的（2026-10-27 业主批）。

## 为什么要这条判据（它守的是一次刚发生过的耦合）

`capabilities.assert_capabilities()` 原先挂在导入期。两条实测代价：① 每一次 CLI 启动
多付 1.2 秒（`python -m agentflow --help` 2036ms 里 1.2 秒在它身上）；② 任何一格的
登记过期都会让所有命令 exit 1 —— 2026-10-27 真实发生过：一条并行 lane 把
`D.register_conjecture` 的工具匹配跑通了却没把它从 `_KNOWN_UNMATCHED_ACTIONS` 里删掉，
于是 `agentflow --help` 也炸。审计失败应该让发布门与判据红，不该让"看一眼帮助"红。

## 三条判据（缺一条，"搬走"就会变成"不跑了"）

1. 导入期不许跑：`import agentflow.capabilities` 之后 `AUDIT_RUNS == 0`，
   且 `PARAM_ASSERT_COVERAGE` 仍是空的（空是"还没跑"的可见形态，不许被"跑过一次"掩盖）；
2. 显式调必须真跑：`run_capability_audit()` 之后 `AUDIT_RUNS == 1`、
   `PARAM_ASSERT_COVERAGE["checked"] == ["declared"]`（反真空：跑了个空转不算跑）；
3. 开关必须真的能恢复旧行为：`AGENTFLOW_CAPABILITY_AUDIT=1` 时导入期那趟照跑
   （用一个子进程量，因为本进程早就 import 过它了）。
"""

from __future__ import annotations

import os
import subprocess
import sys

from agentflow import capabilities as C

SRC = os.path.dirname(os.path.dirname(os.path.abspath(C.__file__)))


def _run(code: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PYTHONPATH"] = SRC
    env.pop(C.CAPABILITY_AUDIT_ENV, None)
    return subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", env=env, timeout=300)


def test_importing_capabilities_does_not_run_the_audit() -> None:
    """① 导入期不跑：`AUDIT_RUNS == 0` 且覆盖读数仍是空的（"没跑"必须看得见）。"""
    p = _run(
        "import agentflow.capabilities as C\n"
        "print(C.AUDIT_RUNS, len(C.PARAM_ASSERT_COVERAGE))\n"
    )
    assert p.returncode == 0, (p.returncode, p.stdout, p.stderr)
    runs, covered = p.stdout.split()
    assert runs == "0", f"导入期跑了 {runs} 次审计 ⇒ item 1 的收益（1.2 秒/次）又回来了"
    assert covered == "0", (
        f"导入之后 PARAM_ASSERT_COVERAGE 已经有 {covered} 个键 ⇒ 审计在别处被触发了，"
        "这条判据的前提不成立")


def test_explicit_run_does_audit_and_fills_the_readings() -> None:
    """② 显式调必须真跑（反真空：跑了个空转不算跑）。"""
    p = _run(
        "import agentflow.capabilities as C\n"
        "C.run_capability_audit(print_readings=False)\n"
        "print(C.AUDIT_RUNS, C.PARAM_ASSERT_COVERAGE.get('checked'), "
        "C.PARAM_ASSERT_COVERAGE.get('declared'))\n"
    )
    assert p.returncode == 0, (p.returncode, p.stdout, p.stderr)
    runs, checked, declared = (int(x) for x in p.stdout.split())
    assert runs == 1, runs
    assert checked == declared and checked >= 100, (checked, declared)


def test_the_env_switch_restores_the_import_time_audit() -> None:
    """③ 开关能恢复旧行为：`AGENTFLOW_CAPABILITY_AUDIT=1` ⇒ 导入期就跑一趟。"""
    env = dict(os.environ)
    env["PYTHONPATH"] = SRC
    env[C.CAPABILITY_AUDIT_ENV] = "1"
    p = subprocess.run(
        [sys.executable, "-c", "import agentflow.capabilities as C; print(C.AUDIT_RUNS)"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, timeout=300)
    assert p.returncode == 0, (p.returncode, p.stderr)
    assert p.stdout.strip() == "1", (
        f"开关打开时导入期没有跑审计（AUDIT_RUNS={p.stdout.strip()!r}）⇒ "
        "'想恢复旧行为'那句话是空的")
    assert "覆盖" in p.stderr and "两层参数对账" in p.stderr, (
        f"开关打开时那两行读数没有打出来：{p.stderr[:200]!r}")

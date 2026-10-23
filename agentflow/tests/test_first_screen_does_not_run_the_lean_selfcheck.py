# -*- coding: utf-8 -*-
"""判据（施工单 d）：首屏不跑 Lean 自检（只写"未查"），doctor 与收工门照旧给完整读数。

## 首屏为什么要让路

自检的第 ⑤ 步（Mathlib 图论）要真编译一次 `import Mathlib.Combinatorics.SimpleGraph.Basic`
加 `#check SimpleGraph`：本机实测 11.3 秒（整次自检 13.3 秒）。而首屏的用途只是
"开跑之前让人看一眼开关与解释器"——把十几秒压在开工前那一下，读数是"这工具启动很慢"，
它想回答的那个问题（这台机器的图论库可用吗）却是 `agentflow doctor` 与收工门的活。

## 判据

| # | 判据 | 改前为什么红 |
|---|---|---|
| ① | `cli._lean_first_screen()` 调用一次小于 2 秒、文本含"未查"、且它一次都不调 `lean_selfcheck_reading` / `selfcheck` / `_run` | 改前它第一件事就是 `lean_selfcheck_reading`（本机 13.3 秒） |
| ② | 返回的读数把"未查"写在格子里：`checked=False`、`state=unknown`、`first_screen=True` | 改前这里是 `usable` |
| ③ | `doctor` 仍然给完整的 Mathlib 读数，而且它把自检那一格交给 `toolchain_report`（不另起一次探测） | 改前 doctor 这一轴编译两次（18.9 秒 + 12.4 秒） |

① 的做法是把三个入口都换成"一被调用就炸"的桩：于是"它没跑"是结构性的
（任何一次调用都会让本用例以 AssertionError 收场），而不是"看起来没输出"。
② 是同一件事的读数面：没查不许长得像查过了。
"""
from __future__ import annotations

import argparse
import pathlib
import time
from typing import Any

import pytest

from agentflow import cli
from agentflow import leantoolchain as LT
from agentflow import settings as SET
from agentflow import toolchain as TC

#: 首屏的耗时上限（秒）。实测（2026-10-25）：改前 13.3 秒、改后 0.01 秒；
#: 2 秒是"任何一次子进程都不许发生"的余量，不是性能指标。
_MAX_SEC = 2.0

#: 一份"第 ⑤ 步真跑过"的读数（doctor 那一档要吃它）。
_MATHLIB_CELL: dict[str, Any] = {
    "checked": True, "detected": True, "state": "usable",
    "root": "Z:/stub-mathlib4", "source": "settings",
    "version": "leanprover/lean4:v4.7.0",
    "umbrella_olean": "Z:/stub-mathlib4/.lake/build/lib/Mathlib.olean",
    "graph_olean": "Z:/stub-mathlib4/.lake/build/lib/Mathlib/Combinatorics/SimpleGraph/Basic.olean",
    "lean_path": "Z:/stub-mathlib4/.lake/build/lib", "lean_path_segments": 1,
    "runner": "lake_env_lean", "argv": ["lake", "env", "lean", "probe.lean"],
    "cwd": "Z:/stub-mathlib4", "exit_code": 0,
    "output_head": "SimpleGraph.{u} (V : Type u) : Type u",
    "evidence": "SimpleGraph.{u} (V : Type u) : Type u",
    "elapsed_ms": 12390.0, "problems": [], "reason": "图论可用（stub）",
}


def _first_screen_problems(text: str, elapsed: float, reading: Any) -> list[str]:
    """① 与 ② 的正文（空清单 = 两条都成立）。"""
    bad: list[str] = []
    if elapsed >= _MAX_SEC:
        bad.append(f"首屏花了 {elapsed:.2f} 秒（上限 {_MAX_SEC:.1f}）—— "
                   "它又把 Lean 自检跑了一遍（第 ⑤ 步那一次编译实测 11.3 秒）")
    if "未查" not in str(text):
        bad.append("首屏没有写「未查」⇒ 读的人无法把它与「查过了、没问题」分开")
    if "doctor" not in str(text):
        bad.append("首屏没有指路（要读数请跑 `agentflow doctor`）")
    state = dict(reading or {})
    if state.get("checked") is not False:
        bad.append(f"首屏交出去的读数里 checked={state.get('checked')!r} ⇒ 它自称查过了")
    if str(state.get("state")) != "unknown":
        bad.append(f"首屏交出去的读数里 state={state.get('state')!r}（应为 unknown）")
    if state.get("first_screen") is not True:
        bad.append("首屏交出去的读数没有标 first_screen=True ⇒ 下游分不清这份读数的来源")
    return bad


@pytest.fixture()
def lean_on(monkeypatch: pytest.MonkeyPatch) -> None:
    """产品缺省是关的，而这批判的是"开着的时候首屏也不许跑自检"。"""
    monkeypatch.setenv(SET.ENV_LEAN_ENABLED, "1")


# ============================================================ ①② 首屏


def test_the_first_screen_does_not_run_the_lean_selfcheck(
        monkeypatch: pytest.MonkeyPatch, lean_on: None, capsys: pytest.CaptureFixture[str],
) -> None:
    """①② 首屏 < 2 秒、含「未查」、且一次都不调自检那三个入口。"""

    def _explode(*a: Any, **kw: Any) -> Any:
        raise AssertionError("首屏不许跑 Lean 自检（第 ⑤ 步那一次编译实测 11.3 秒）")

    monkeypatch.setattr(LT, "lean_selfcheck_reading", _explode)
    monkeypatch.setattr(LT, "selfcheck", _explode)
    monkeypatch.setattr(LT, "_run", _explode)

    started = time.perf_counter()
    reading = cli._lean_first_screen(pathlib.Path("."))
    elapsed = time.perf_counter() - started
    printed = capsys.readouterr().out

    bad = _first_screen_problems(printed, elapsed, reading)
    assert bad == [], "\n".join(bad) + f"\n首屏原文：\n{printed}"


def test_the_first_screen_still_names_the_switch_and_the_interpreter(
        monkeypatch: pytest.MonkeyPatch, lean_on: None, capsys: pytest.CaptureFixture[str],
) -> None:
    """反真空的另一半：首屏省掉的是自检，不是那三行读数。

    业主点名要露出来的三件事（开关值 / 来源 / 解释器路径）读的是配置与文件面，
    不跑自检也能给；把这三行一起省掉就成了"省得太多"。
    """
    monkeypatch.setattr(LT, "lean_selfcheck_reading",
                        lambda *a, **kw: (_ for _ in ()).throw(AssertionError("不许跑")))
    cli._lean_first_screen(pathlib.Path("."))
    printed = capsys.readouterr().out
    for needle in ("开关：", "来源：", "解释器：", "[开机自检]"):
        assert needle in printed, f"首屏少了「{needle}」那一行：\n{printed}"


# ============================================================ ③ doctor


def _doctor_args() -> argparse.Namespace:
    return argparse.Namespace(selfcheck=False, json=False, root=None)


def test_doctor_still_gives_the_full_mathlib_reading_from_one_probe(
        monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    """③ doctor 打完整 Mathlib 读数，且把自检那一格交给 `toolchain_report`（只探一次）。"""
    seen: dict[str, Any] = {}
    calls: list[int] = []

    def _reading(*a: Any, **kw: Any) -> dict[str, Any]:
        calls.append(1)
        return {"checked": True, "ok": True, "state": "usable", "enabled": True,
                "enabled_source": "env", "source": "settings", "lean_path": "lean.exe",
                "version": "4.7.0", "version_ok": True, "sha256": "0" * 64,
                "positive": {"exit_code": 0, "output_head": "", "name": "dsh_selfcheck"},
                "negative": {"exit_code": 1, "output_head": "", "name": "dsh_selfcheck_bad"},
                "mathlib": dict(_MATHLIB_CELL), "problems": [], "note": "四步全过（stub）",
                "expected_version": "leanprover/lean4:v4.7.0", "elapsed_ms": 1.0}

    def _report(env: Any = None, *, mathlib_reading: Any = None) -> dict[str, Any]:
        seen["mathlib_reading"] = mathlib_reading
        return {"model": {"key_present": True, "base_url": "b", "model": "m"},
                "provers": {"checked": True, "available": [], "looked_in": [],
                            "probe_errors": [], "reason": "stub"},
                "lean_enabled": True, "lean_enabled_source": "env",
                "formal_mode": "formal", "lean_ready": True, "can_do_formal": True,
                "lean_path": "", "lean_version": "",
                "mathlib": TC.mathlib_state(reading=mathlib_reading)}

    monkeypatch.setattr(LT, "lean_selfcheck_reading", _reading)
    monkeypatch.setattr(TC, "toolchain_report", _report)
    cli.cmd_doctor(_doctor_args())
    printed = capsys.readouterr().out

    assert calls == [1], f"doctor 跑了 {len(calls)} 次自检（应为 1 次）：它又各探各的了"
    assert seen.get("mathlib_reading") == _MATHLIB_CELL, (
        "doctor 没有把自检那一格交给 `toolchain_report` ⇒ 这一轴又变成两处探测")
    # 完整读数：工程根 / 版本 / 跑法 / 退出码 / 检查器原文都要出现在台面上
    for needle in ("Z:/stub-mathlib4", "leanprover/lean4:v4.7.0", "lake_env_lean",
                   "SimpleGraph", "mathlib：usable"):
        assert needle in printed, f"doctor 的 Mathlib 读数里丢了「{needle}」：\n{printed}"
    # 那一格不是"另探一次"得来的：它写的是第 ⑤ 步的结论
    assert "可用" in printed


if __name__ == "__main__":  # pragma: no cover - 手动跑这一组时的入口
    raise SystemExit(pytest.main([__file__, "-q"]))

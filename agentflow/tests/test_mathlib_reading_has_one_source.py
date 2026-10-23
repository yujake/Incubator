# -*- coding: utf-8 -*-
"""判据（施工单 c）：Mathlib 那一轴只有一处读数 —— 打桩一处，另一处跟着变。

## 改前的两处探测（这就是"两个答案"的形态）

| 地址 | 探什么 | 本机实测 |
|---|---|---|
| `toolchain.mathlib_state()` | 自己找根、自己认两种 umbrella 布局、再真编译一次 `import Mathlib` 加 `norm_num` | 18.9 秒 |
| `leantoolchain.mathlib_reading()` | 第 ⑤ 步：读盘面，再由 `_mathlib_control` 真编译一次 `import Mathlib.Combinatorics.SimpleGraph.Basic` 加 `#check SimpleGraph` | 12.4 秒 |

两处探的是同一件事，却可以给出两个答案（2026-10-08 的现场：文件面说"可用"、真编译报
`unknown package 'Std'`）。而且 `agentflow doctor` 会为这两处各编译一次。

现在 `mathlib_state()` 只做一件事：把第 ⑤ 步那条读数投影成既有那几个键。判据因此有三条：

| # | 判据 | 改前为什么红 |
|---|---|---|
| ① | 打桩 `leantoolchain.mathlib_reading` ⇒ `toolchain.mathlib_state()` 的每一格跟着变（root / state / 实测那两格） | 改前它自己找根，打桩一点都不动 |
| ② | 那一处 umbrella 探针不存在了（`toolchain` 里没有 `_import_mathlib_probe`），且 `mathlib_state()` 不 spawn | 改前它是这个模块里的一件常设探针 |
| ③ | 负控：读数自相矛盾（自称 usable 却没有那次编译的读数 / detected 与 root 对不上）⇒ 报"没查成"，不许各说各话 | 改前没有"只能有一处"这件事，也就没有这个需要 |

零模型调用；打桩那一档不碰盘、不起子进程。
"""
from __future__ import annotations

from typing import Any, Mapping

import pytest

from agentflow import leantoolchain as LT
from agentflow import toolchain as TC

#: 一份"看起来可用"的第 ⑤ 步读数：每一格都齐（结论、跑法、退出码、检查器原文）。
_USABLE_READING: dict[str, Any] = {
    "checked": True, "detected": True, "state": "usable",
    "root": "Z:/stub-mathlib4", "source": "flag",
    "version": "leanprover/lean4:v4.7.0", "expected_version": "leanprover/lean4:v4.7.0",
    "lakefile": "Z:/stub-mathlib4/lakefile.lean",
    "toolchain_file": "Z:/stub-mathlib4/lean-toolchain",
    "umbrella_olean": "Z:/stub-mathlib4/.lake/build/lib/Mathlib.olean",
    "graph_olean": "Z:/stub-mathlib4/.lake/build/lib/Mathlib/Combinatorics/SimpleGraph/Basic.olean",
    "lake_exe": "Z:/stub-mathlib4/lake.exe",
    "lean_path": "Z:/stub-mathlib4/.lake/build/lib", "lean_path_segments": 1,
    "runner": "lake_env_lean", "argv": ["lake", "env", "lean", "probe.lean"],
    "cwd": "Z:/stub-mathlib4", "exit_code": 0,
    "output_head": "SimpleGraph.{u} (V : Type u) : Type u", "evidence": "SimpleGraph.{u} (V : Type u) : Type u",
    "elapsed_ms": 12390.0, "problems": [], "reason": "图论可用（stub）",
}


def _problems(state: Mapping[str, Any], reading: Mapping[str, Any]) -> list[str]:
    """① 的正文：`mathlib_state()` 与它声称读的那一份读数对不对得上。"""
    bad: list[str] = []
    for key in ("root", "state", "detected", "version", "umbrella_olean", "graph_olean",
                "lean_path", "lean_path_segments"):
        want = reading.get(key)
        if want is None:
            continue
        if state.get(key) != want:
            bad.append(f"`mathlib_state()[{key!r}]` 是 {state.get(key)!r}，而读数里是 "
                       f"{want!r} ⇒ 两处没有同源")
    if state.get("graph_import_measured") != state.get("import_mathlib_measured"):
        bad.append("实测那两格（`import_mathlib_measured` 与 `graph_import_measured`）"
                   "不是同一句话 ⇒ 这一轴又分成了两处读数")
    probe = state.get("import_mathlib_probe") or {}
    if probe.get("verified") is not (reading.get("state") == "usable"):
        bad.append(f"`import_mathlib_probe.verified` 是 {probe.get('verified')!r}，"
                   f"而第 ⑤ 步读数是 {reading.get('state')!r}")
    return bad


@pytest.fixture()
def lean_on(monkeypatch: pytest.MonkeyPatch) -> None:
    """这一批判的是合并之后的读数，不判开关 —— 把开关钉在"开"上。"""
    from agentflow import settings as SET

    monkeypatch.setenv(SET.ENV_LEAN_ENABLED, "1")


# ============================================================ ① 一处读数


def test_stubbing_the_reading_moves_mathlib_state(monkeypatch: pytest.MonkeyPatch,
                                                  lean_on: None) -> None:
    """① 打桩 `LT.mathlib_reading` ⇒ `TC.mathlib_state()` 每一格跟着变。"""
    calls: list[dict[str, Any]] = []

    def _stub(**kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        return dict(_USABLE_READING)

    monkeypatch.setattr(LT, "mathlib_reading", _stub)
    state = TC.mathlib_state(env={"AGENTFLOW_LEAN_ENABLED": "1"})
    assert calls, "打桩没被调用 ⇒ `mathlib_state()` 走的是自己那条探测（两处仍然分家）"
    bad = _problems(state, _USABLE_READING)
    assert bad == [], "\n".join(bad)
    # 那份工程根在盘上根本不存在：于是"读到了 Z:/stub-mathlib4"只可能来自那处打桩
    assert state["root"] == "Z:/stub-mathlib4"
    assert "可用" in str(state["graph_import_measured"])
    assert state["checked"] is True


def test_the_second_probe_address_is_gone(monkeypatch: pytest.MonkeyPatch,
                                          lean_on: None) -> None:
    """② 那一处 umbrella 探针不存在了，而 `mathlib_state()` 一个子进程都不起。"""
    assert not hasattr(TC, "_import_mathlib_probe"), (
        "`toolchain._import_mathlib_probe` 又回来了 ⇒ 这一轴重新变成两处探测"
        "（doctor 会为此编译两次，而两处可以各说各话）")
    assert not hasattr(TC, "_IMPORT_MATHLIB_PROBE_SRC")

    def _explode(*a: Any, **kw: Any) -> Any:
        raise AssertionError("`mathlib_state()` 不许起子进程（它只读第 ⑤ 步那条读数）")

    monkeypatch.setattr(LT, "_run", _explode)
    monkeypatch.setattr(LT, "selfcheck", _explode)
    state = TC.mathlib_state(env={"AGENTFLOW_LEAN_ENABLED": "1"})
    # 读盘面那一档给不出"可用"：`usable` 只能由一次真编译产生，而这一趟一个子进程都没起。
    assert state["state"] != "usable", state
    assert (state["import_mathlib_probe"] or {}).get("exit_code") is None, state
    assert state["checked"] is True, state


# ============================================================ ③ 负控：不一致要明说


def test_negative_control_a_self_contradicting_reading_is_reported_as_unchecked(
        monkeypatch: pytest.MonkeyPatch, lean_on: None) -> None:
    """③ 负控：读数自相矛盾 ⇒ 报"没查成"，不许各说各话地报一个"可用"。"""
    # (a) 自称 usable，却没有那次编译的读数（runner / exit_code 都空）
    hollow = {k: v for k, v in _USABLE_READING.items()}
    hollow.update({"runner": "", "exit_code": None})
    monkeypatch.setattr(LT, "mathlib_reading", lambda **kw: dict(hollow))
    state = TC.mathlib_state(env={"AGENTFLOW_LEAN_ENABLED": "1"})
    assert state["state"] == "unknown", state
    assert state["checked"] is False, state
    assert str(state["graph_import_measured"]).startswith("没查成"), state["graph_import_measured"]
    assert "可用" not in str(state["graph_import_measured"]), (
        "读数自相矛盾却报了一个「可用」—— 两处各说各话重新出现了")
    assert (state["import_mathlib_probe"] or {}).get("verified") is None, state
    assert "自相矛盾" in str(state["reason"]), state["reason"]

    # (b) detected 与 root 对不上（说检出了，却没有工程根）
    blind = {k: v for k, v in _USABLE_READING.items()}
    blind.update({"root": "", "state": "unknown", "runner": "", "exit_code": None})
    monkeypatch.setattr(LT, "mathlib_reading", lambda **kw: dict(blind))
    state = TC.mathlib_state(env={"AGENTFLOW_LEAN_ENABLED": "1"})
    assert state["state"] == "unknown", state
    assert str(state["graph_import_measured"]).startswith("没查成"), state["graph_import_measured"]

    # 收尾：一份自洽的读数照旧判"可用"（上面那两条红不是"恒红"）
    monkeypatch.setattr(LT, "mathlib_reading", lambda **kw: dict(_USABLE_READING))
    state = TC.mathlib_state(env={"AGENTFLOW_LEAN_ENABLED": "1"})
    assert state["state"] == "usable" and "可用" in str(state["graph_import_measured"])


if __name__ == "__main__":  # pragma: no cover - 手动跑这一组时的入口
    raise SystemExit(pytest.main([__file__, "-q"]))

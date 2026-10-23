# -*- coding: utf-8 -*-
"""无 Lean 时绝不允许出现 `proof` 级证据（T2 场景的硬约束）。

## 为什么这条必须是判据而不是"每次我看一眼"

T2 是"无 Lean"路线。真机上我确实没看到 `proof`，但那是这一次的读数；
它背后的机制有三层（`settings.lean_enabled` 先判 → `formalgw.check_lean` ② 不编译 →
`run_experiment` 把非 `verified` 一律落 `inconclusive`+`heuristic`），任何一层被改宽，
`proof` 就会在没有检查器的机器上出现 —— 而报告照样打印，那正是 FC-27 里
「桥接层说谎 ⇒ proof 级证据是假的」那条最怕的形态。

这条判据把三层一起钉住（全部在 Lean 关的模式下跑）：

1. `settings.lean_enabled()` 为 False（本判据自己设的环境：清掉变量 ＋ 空设置文件）；
2. `check_formal` 受控拒绝：`ok=True`、`reason="lean_disabled"`、`verified=None`
   （是"用户关掉了"，不是"机器上没有"，也不是"证明没过"）；
3. `run_experiment(method="formal")` 的结论只能是 `inconclusive` ＋ `heuristic`，
   `evidence_kind != "proof"`、`result != "supports"`。
"""
from __future__ import annotations

import importlib

import pytest

from agentflow.store import Store


@pytest.fixture()
def lean_off(tmp_path, monkeypatch):
    empty = tmp_path / "settings.json"
    empty.write_text('{"toolchain": {"lean_enabled": false, "lean_bin": ""}}', encoding="utf-8")
    monkeypatch.setenv("AGENTFLOW_SETTINGS", str(empty))
    monkeypatch.delenv("AGENTFLOW_LEAN_ENABLED", raising=False)
    monkeypatch.delenv("AGENTFLOW_LEAN_BIN", raising=False)
    from agentflow import settings as S

    importlib.reload(S)
    yield S
    importlib.reload(S)


def test_the_switch_really_reads_off(lean_off):
    """前置：这一组用例确实跑在"Lean 关"的模式下（否则下面的断言会假绿）。"""
    assert bool(lean_off.lean_enabled()[0]) is False


def test_check_formal_is_a_controlled_refusal(lean_off):
    """`check_formal` 必须受控拒绝：`lean_disabled`、`verified=None`、不抛异常。"""
    from agentflow.tools import verify_tools as V

    r = V.check_formal("1+1=2", source="theorem t_v : (1:Nat)+1=2 := rfl",
                       checker_name="t_v")
    assert r.ok is True, "关掉开关不等于出错 —— 拒信要能被正常读到"
    data = r.data or {}
    assert data.get("verified") is None
    assert str(data.get("reason")) == "lean_disabled"
    assert data.get("checked") is False


def test_a_formal_experiment_is_refused_outright(lean_off, tmp_path):
    """核心：无 Lean 时 `method="formal"` 直接拒绝，且一行都不落。

    我原来以为它会落一行 `inconclusive`+`heuristic`；实测比那更硬 ——
    `agent_e/run_experiment.py` 抛 `ExperimentError`（「E 不做形式化」）。这更好：
    根本没有机会产出一行带 `proof` 的记录。2026-10-23 晚裁定之后这一档不再看开关
    （E 的动作面没有 `method='formal'` 了，理由码 `formal_not_in_e`）⇒ 本用例钉的
    "拒绝 + 一行都不落"在无 Lean 这一档更成立，而且是最强的那一形态。
    判据钉住这个更强的口径，并额外断言"台账里没多出实验行"。
    """
    from agentflow.agent_e._support import ExperimentError
    from agentflow.agent_e import AgentE

    ws = tmp_path / "ws"
    st = Store(ws)
    st.init()
    lean_dir = ws / "code" / "formal"
    lean_dir.mkdir(parents=True, exist_ok=True)
    src = lean_dir / "t_np.lean"
    src.write_text("theorem t_np : (1:Nat) + 1 = 2 := rfl\n", encoding="utf-8")
    before = len(st.rows("experiments"))

    e = AgentE(st, workspace_root=ws)
    with pytest.raises(ExperimentError) as ei:
        e.run_experiment("1+1=2", "t_np", str(src), method="formal")
    assert "formal_not_in_e" in str(ei.value), ei.value
    assert "不做形式化" in str(ei.value), ei.value
    after = st.rows("experiments")
    assert len(after) == before, f"拒绝了却还是落了行：{after}"
    assert not any(str(r.get("evidence_kind")) == "proof" for r in after)

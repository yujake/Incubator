# -*- coding: utf-8 -*-
"""18A + 22B：M 拿得到收工门，而且"没跑门就 final"会被受控拒。

## 现场（AH2b，`projects/lp-ball-2`）

- 18A：M 在 final 里把"收工前跑 `conductor.closing` 并逐条对 P1–P11"列成待办，
  然后交了 final —— 全表 `conductor.closing` 0 次调用。工具在声明里（`roles=("M",)`），
  但本审计阶段的工具面读数把它数丢了；这一组先把"它在 M 的面上、也在 M 的提示词里"
  钉成判据（回归），再补"不跑就会被拦"的那道闸。
- 22B：研究型 / 有门的项目在 final 之前若从未成功调用过 `conductor.closing`
  ⇒ 受控拒（`closing_not_run_before_final`），并把处置与豁免路径写在拒信里。

## 判据

| # | 判据 |
|---|---|
| a | `conductor.closing` 在 M 的工具面上，也在 M 的渲染提示词里 |
| b | 研究型 / 有门的项目、从未跑过门 ⇒ `_final_gate_reading` 挡住并点名理由码 |
| c | 真的跑过一次（经 `_do_tool` 的成功调用记录）⇒ 同一道闸放行 |
| d | 非研究型（无研究问题 / 验收表 / 论文包）⇒ 不拦 |
| e | 反真空：把"跑过没有"的判据打桩成恒真 ⇒ b 的受控拒必须消失 |
| f | 显式声明 `no_gate` + 理由 ⇒ 放行；只写 `no_gate` 不写理由 ⇒ 不豁免 |
"""
from __future__ import annotations

import json
import pathlib
from types import SimpleNamespace

from agentflow import agent_prompts as AP
from agentflow import agent_loop as AL
from agentflow.store import Store
from agentflow.tools import build_registry


class _Conductor:
    """只提供收工闸要读的那一格（销号完整性）：树已清空。"""

    def retire_integrity(self, mine: str) -> dict:  # noqa: ARG002 —— 夹具
        return {"checked": True, "complete": True, "nodes": [], "dirty": [],
                "count": 0, "total": 0, "root_open_items": 0,
                "stalled": [], "stalled_count": 0, "states": None, "reason": ""}


class _ClosingRegistry:
    """一个只认 `conductor.closing` 的注册表：让 `_do_tool` 走真实记录那一支。"""

    def names(self) -> list[str]:
        return ["conductor.closing"]

    def call(self, name: str, role: str | None = None, **args: object) -> SimpleNamespace:
        assert name == "conductor.closing" and role == "M", (name, role)
        return SimpleNamespace(ok=True, data={"can_close": True, "machine_pass": True,
                                              "closable": True},
                               error="", meta={})


def _ws(tmp_path: pathlib.Path, *, gated: bool = True) -> tuple[Store, pathlib.Path]:
    root = tmp_path / "ws"
    st = Store(root)
    st.init(force=True)
    if gated:
        # 验收表 = "有门的项目"（研究问题表可以为空，这一格不依赖 schema 行）
        p = root / "out" / "paper" / "ACCEPTANCE-CHECKS.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"checks": []}), encoding="utf-8", newline="\n")
    return st, root


def _loop(st: Store, root: pathlib.Path, *, registry: object = None) -> AL.AgentLoop:
    return AL.AgentLoop(role="M", session_root=root,
                        registry=registry if registry is not None else object(),
                        seam=None, conductor=_Conductor(), store=st,
                        workspace_root=str(root), my_task_id="t-000001",
                        auto_secretary=False)


# ============================================================ a 工具面 + 提示词
def test_a_the_closing_gate_is_on_ms_tool_surface_and_in_the_prompt(
        tmp_path: pathlib.Path) -> None:
    """a：`conductor.closing` 在 M 的工具面上，也在 M 的渲染提示词里（18A 回归）。"""
    st, root = _ws(tmp_path)
    built = build_registry(store=st, workspace_root=root)
    names = {spec.name for spec in built.registry.for_role("M")}
    assert "conductor.closing" in names, sorted(names)
    text = AP.system_prompt("M", registry=built.registry)
    assert "conductor.closing" in text, "M 的提示词里没有收工门这一件工具"


# ============================================================ b 未跑门 ⇒ 受控拒
def test_b_a_gated_project_that_never_ran_the_gate_is_refused(tmp_path: pathlib.Path):
    """b：有门、从未跑过 `conductor.closing` ⇒ final 被受控拒并点名理由码。"""
    st, root = _ws(tmp_path)
    reading = _loop(st, root)._final_gate_reading()
    assert reading["applicable"] is True, reading
    assert reading["complete"] is False, reading
    assert reading.get("code") == AL.CLOSING_NOT_RUN_CODE, reading
    assert "conductor.closing" in str(reading.get("why")), reading
    gate = reading["closing_gate"]
    assert gate["required"] is True and gate["consulted"] is False, gate


# ============================================================ c 跑过门 ⇒ 放行
def test_c_running_the_gate_once_lets_the_final_through(tmp_path: pathlib.Path):
    """c：真的经 `_do_tool` 成功跑过一次 ⇒ 收工闸放行（销号那一格由夹具保证干净）。"""
    st, root = _ws(tmp_path)
    loop = _loop(st, root, registry=_ClosingRegistry())
    result = loop._do_tool({"name": "conductor.closing", "args": {"project_dir": "."}})
    assert result["ok"] is True, result
    assert loop._closing_gate_readings, loop._closing_gate_readings
    reading = loop._final_gate_reading()
    assert reading["complete"] is True, reading
    assert reading.get("code") != AL.CLOSING_NOT_RUN_CODE, reading
    assert reading["closing_gate"]["consulted"] is True, reading["closing_gate"]


# ============================================================ d 非研究型 ⇒ 不拦
def test_d_a_non_research_project_without_gates_is_not_blocked(tmp_path: pathlib.Path):
    """d：没有研究问题、没有验收表、没有论文包 ⇒ 这道闸没有对象，不拦。"""
    st, root = _ws(tmp_path, gated=False)
    reading = _loop(st, root)._final_gate_reading()
    gate = reading["closing_gate"]
    assert gate["required"] is False, gate
    assert reading.get("code") != AL.CLOSING_NOT_RUN_CODE, reading
    assert reading["complete"] is True, reading


# ============================================================ e 反真空
def test_e_stubbing_the_consulted_check_makes_the_refusal_disappear(tmp_path: pathlib.Path,
                                                                   monkeypatch):
    """e：反真空 —— 把"跑过没有"打桩成恒真 ⇒ b 的受控拒必须消失；放回去 ⇒ 重新出现。"""
    st, root = _ws(tmp_path)
    loop = _loop(st, root)
    assert loop._final_gate_reading().get("code") == AL.CLOSING_NOT_RUN_CODE

    real = AL.closing_gate_consulted
    monkeypatch.setattr(AL, "closing_gate_consulted",
                        lambda _loop: {"consulted": True, "calls": 1, "last": {}})
    stubbed = loop._final_gate_reading()
    assert stubbed.get("code") != AL.CLOSING_NOT_RUN_CODE, stubbed

    monkeypatch.setattr(AL, "closing_gate_consulted", real)
    restored = loop._final_gate_reading()
    assert restored.get("code") == AL.CLOSING_NOT_RUN_CODE, restored


# ============================================================ f 豁免
def _no_gate(root: pathlib.Path, payload: dict) -> None:
    p = root / "out" / "review" / "NO-GATE.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8", newline="\n")


def test_f_an_explicit_no_gate_declaration_with_a_reason_is_honoured(
        tmp_path: pathlib.Path) -> None:
    """f：`no_gate: true` + 非空理由 ⇒ 放行并留痕。"""
    st, root = _ws(tmp_path)
    _no_gate(root, {"no_gate": True, "reason": "这一趟只交一份书目清单，没有可复算的交付"})
    reading = _loop(st, root)._final_gate_reading()
    assert reading.get("code") != AL.CLOSING_NOT_RUN_CODE, reading
    assert reading["closing_gate"]["exempt"]["declared"] is True, reading["closing_gate"]
    assert reading["complete"] is True, reading


def test_f_a_no_gate_declaration_without_a_reason_is_not_an_exemption(
        tmp_path: pathlib.Path) -> None:
    """f 的负控：光写 `no_gate: true` 不写理由 ⇒ 不算豁免（否则豁免就是随手可写）。"""
    st, root = _ws(tmp_path)
    _no_gate(root, {"no_gate": True})
    reading = _loop(st, root)._final_gate_reading()
    assert reading.get("code") == AL.CLOSING_NOT_RUN_CODE, reading
    assert reading["closing_gate"]["exempt"]["declared"] is False, reading["closing_gate"]

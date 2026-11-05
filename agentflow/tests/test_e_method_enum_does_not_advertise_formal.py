# -*- coding: utf-8 -*-
"""E 的两面都不广告 `formal`：模型看得见的 `method.enum` 只许是它真收得下的三种。

## 这一组守什么（D15，2026-11-05 走查）

工具面（`verify_tools.py` 的 `verify.run_experiment`）先改成了 `COMPUTATIONAL_METHODS`
（三种），而动作面（`specs/e.py` 的 `run_experiment`）仍是 `schema.EXPERIMENT_METHODS`
全表（四种，含 `formal`）⇒ `capabilities` 里那份 `params` 仍广告 `formal`，模型按它传参，
再拿回一次 `AgentE.run_experiment` 第一句的必然拒绝（理由码 `formal_not_in_e`）。
广告一个必然被拒的值与"广告面 = 接受面"（`tests/test_action_surface_matches_acceptance.py`）
是同一条纪律的反面。

`formal` 本身不能从 `schema.EXPERIMENT_METHODS` 删：L 的 `formal.record` 要写
`method="formal"` 的 `experiments` 行。所以两个面读的是中立模块
`agentflow.experiment_methods` 的 `COMPUTATIONAL_METHODS`，而不是 schema 全表。

## 判据（a–e）

| # | 判据 | 反真空 / 负控 |
|---|---|---|
| a | 动作面与工具面的 `method.enum` 都恰好是三种，且都不含 `formal` | 把 `formal` 加回任一面 ⇒ 判据函数当场报（`test_the_criterion_catches_formal_added_back`） |
| b | `AgentE.run_experiment(method="formal")` 仍 `ExperimentError` + `formal_not_in_e` + 0 行 | 改前红：动作面广告它的时候这一条本来就是绿的（方法层后盾没动） |
| c | `schema.Experiment(method="formal")` 仍通过校验（L 那一侧不受影响） | 同上：这里是正控，摘掉 schema 的 `formal` ⇒ 红 |
| d | 反真空（见 a 的右列） | —— |
| e | 两个导入方向各自先导入都不炸（常量下沉就是为了这个） | 从 `agent_e._support` import 会成环 ⇒ 那一版在这里红 |

`specs/e.py` 在 FC-27 禁改区（auth-audit）：本文件守的是它的广告面，不是权限面。
"""
from __future__ import annotations

import os
import pathlib
import subprocess
import sys
import tempfile

import pytest

from agentflow import capabilities as CAP
from agentflow import schema as S
from agentflow.agent_e import AgentE
from agentflow.agent_e._support import (
    COMPUTATIONAL_METHODS,
    E_NO_FORMAL_REASON,
    ExperimentError,
)
from agentflow.experiment_methods import COMPUTATIONAL_METHODS as NEUTRAL
from agentflow.specs import e as E_SPEC
from agentflow.store import Store
from agentflow.tools import build_registry

#: E 收得下的三种计算法（顺序也钉住：模型读的就是这个数组）。
WANT = ("numeric", "symbolic", "exhaustive_search")

_PROJ = pathlib.Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------- 读数

def _spec_enum() -> list[str]:
    """动作面：`specs/e.py::ACTIONS` 里 `run_experiment` 的 `method.enum`。"""
    for spec in E_SPEC.ACTIONS:
        if spec.action == "run_experiment":
            return list(spec.params["properties"]["method"]["enum"])
    raise AssertionError("specs/e.py 的动作表里没有 run_experiment")


def _tool_enum() -> list[str]:
    """工具面：装配出来的 `verify.run_experiment`（模型看到的工具 schema）。"""
    with tempfile.TemporaryDirectory(prefix="e-enum-tool-") as td:
        ws = pathlib.Path(td) / "ws"
        ws.mkdir(parents=True, exist_ok=True)
        st = Store(ws)
        st.init()
        reg = build_registry(store=st, workspace_root=ws, roles=("E",),
                             strict=True).registry
        return list(reg.get("verify.run_experiment").params["properties"]["method"]["enum"])


def _capabilities_enum() -> list[str]:
    """运行时真正的面：`capabilities.CAPABILITIES` 里 E 那一格的 `method.enum`。"""
    spec = next(s for s in CAP.CAPABILITIES["E"] if s.action == "run_experiment")
    return list(spec.params["properties"]["method"]["enum"])


def _advertised_problems(spec: list[str], tool: list[str],
                         want: tuple[str, ...] = WANT) -> list[str]:
    """a 的判据本体（单独抽出来，反真空的同一条判据才能对"被篡改的那一版"再判一次）。"""
    problems: list[str] = []
    for label, got in (("动作面 specs/e.py", spec), ("工具面 verify.run_experiment", tool)):
        if tuple(got) != tuple(want):
            problems.append(f"{label} 的 method.enum = {got!r}，应为 {list(want)!r}")
        if "formal" in got:
            problems.append(f"{label} 仍广告 formal（它必然被 formal_not_in_e 拒）")
    return problems


# ---------------------------------------------------------------- a / d

def test_both_surfaces_advertise_only_the_three_computational_methods() -> None:
    """a：两面都恰好三种，且都不含 `formal`。"""
    spec, tool = _spec_enum(), _tool_enum()
    assert not _advertised_problems(spec, tool), "；".join(_advertised_problems(spec, tool))
    assert "formal" not in spec and "formal" not in tool
    # 派生表（`capabilities.CAPABILITIES`）—— 改前那一版在运行时仍是四值。
    assert _capabilities_enum() == list(WANT), _capabilities_enum()
    # 两面读的必须是同一个常量（值相等只是必要条件；来源见 docstring）。
    assert tuple(COMPUTATIONAL_METHODS) == WANT, COMPUTATIONAL_METHODS
    assert tuple(NEUTRAL) == WANT, NEUTRAL
    assert COMPUTATIONAL_METHODS is NEUTRAL, "两份常量（`_support` 只许 re-export）"


def test_the_criterion_catches_formal_added_back() -> None:
    """d 反真空：`formal` 加回任一面 ⇒ a 的判据当场报，不许"两面都没扫到也算绿"。

    直接对"被篡改的那一版"调用同一个判据函数 —— 不是另写一份检查器（两份判据
    会漂，漂的那一份不会红）。
    """
    spec, tool = _spec_enum(), _tool_enum()
    assert _advertised_problems(spec, tool) == []

    in_spec = _advertised_problems(spec + ["formal"], tool)
    assert in_spec, "把 formal 加回动作面 enum，判据没红（真空）"
    assert "formal" in in_spec[0]

    in_tool = _advertised_problems(spec, tool + ["formal"])
    assert in_tool, "把 formal 加回工具面 enum，判据没红（真空）"
    assert "formal" in in_tool[0]


# ---------------------------------------------------------------- b

def test_agent_e_still_refuses_formal_with_a_controlled_reason(store: Store) -> None:
    """b：方法层后盾没动 —— 受控拒绝、理由码不变、一行都不写。

    这一条在改前就是绿的（动作面广告 `formal` 的时候它也是绿的）：它证明的是
    "把 `formal` 从广告面拿掉"没有顺手动到拒绝路径，不是"这一改把它变绿了"。
    """
    e = AgentE(store, config={}, workspace_root=store.root)
    with pytest.raises(ExperimentError) as ei:
        e.run_experiment("形式化方法", "formal-claim", "probes/x.py", method="formal")
    assert E_NO_FORMAL_REASON in str(ei.value), str(ei.value)
    assert store.rows("experiments") == [], "被拒绝的形式化实验不得留下任何行"


# ---------------------------------------------------------------- c

def test_schema_still_accepts_a_formal_row_for_l() -> None:
    """c：`schema.EXPERIMENT_METHODS` 一字未动 —— L 的 `formal.record` 那条落点还在。

    同时钉住 L 那侧的调用点：`agent_l/record.py` 仍以 `method="formal"` 调
    `build_experiment`（没有 Lean 的机器上，"现跑对账"那一段跑不了，所以这里
    核的是调用点，不是端到端；端到端由 `tests/test_l_action_dispatch.py` 在
    Lean 可用时覆盖）。
    """
    row = S.Experiment(
        experiment_id="0000", claim="形式化命题", claim_key="formal:test",
        method="formal", evidence_kind="proof", result="supports",
        negation_kind="not_proved", code_path="code/formal/Probe.lean",
        code_hash="a" * 64, verifier_output="Probe: no goals",
        verifier_subject_key="formal:test",
    )
    row.validate()
    assert "formal" in S.EXPERIMENT_METHODS, S.EXPERIMENT_METHODS
    record_src = (_PROJ / "src" / "agentflow" / "agent_l" / "record.py").read_text(encoding="utf-8")
    assert 'method="formal"' in record_src, (
        "agent_l/record.py 不再以 method='formal' 调 build_experiment —— "
        "L 那一侧的形式化行没落点了")


# ---------------------------------------------------------------- e

def _import_once(module: str) -> str:
    env = {**os.environ, "PYTHONUTF8": "1",
           "PYTHONPATH": str(_PROJ / "src") + os.pathsep + os.environ.get("PYTHONPATH", "")}
    proc = subprocess.run(
        [sys.executable, "-c", f"import {module}; print('ok {module}')"],
        cwd=str(_PROJ), env=env, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=180)
    assert proc.returncode == 0, (
        f"`python -c \"import {module}\"` 先导入失败（returncode={proc.returncode}）\n"
        f"stdout={proc.stdout}\nstderr={proc.stderr}")
    return proc.stdout.strip()


def test_either_import_order_works() -> None:
    """e：常量下沉之后，两个方向各自先导入都不成环。

    负控：`specs/e.py` 若改成从 `agent_e._support` 取常量，第一个方向会红
    （`_support` 末尾反向 `from ..specs.e import SPEC`，此时 `SPEC` 还没定义）。
    """
    assert _import_once("agentflow.specs.e") == "ok agentflow.specs.e"
    assert _import_once("agentflow.agent_e._support") == "ok agentflow.agent_e._support"
    # 权限面整装配也要能过（`capabilities` 导入期有交叉断言）。
    assert _import_once("agentflow.capabilities") == "ok agentflow.capabilities"


def test_both_surfaces_read_the_same_constant_not_two_copies() -> None:
    """常量只有一处定义：`_support` 的 re-export 与中立模块是同一个对象。"""
    from agentflow.agent_e import _support

    assert _support.COMPUTATIONAL_METHODS is NEUTRAL

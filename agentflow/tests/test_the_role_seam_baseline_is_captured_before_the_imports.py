# -*- coding: utf-8 -*-
"""判据：逐角色注册表的会话基线必须拍在测试模块导入之前，且模块级夹具的装配副作用在判据开始前被装回。

## 真因（2026-11-09 逐条可核；两条污染路径）

`tests/conftest.py::_restore_role_seams` 改前在 setup 里 `saved = dict(_LS._ROLE_SEAMS)`
只挡得住"同一条判据里写的缝"。挡不住的那一条是 `scope="module"` 的夹具：

- 它们比任何函数级夹具都先装配 ⇒ setup 里拍到的"起点"已经带着别人装出来的缝；
- 收尾又忠实地把它还原回去 ⇒ 污染变成基线，整趟会话里再也抹不掉。

真实出处（本仓既有代码，不是这一份判据造出来的）：
`tests/test_l_formalizes_what_b_says.py:156` 的 `good_run` 在夹具体里跑一趟进程内
`run-agent L`，而装配层 `host.wired_llm_conductor` 会无条件
`_AF.set_default_llm(f_llm)`（`src/agentflow/host.py:553`）。

现场读数（最小复现：`test_l_exists_as_a_role_and_runs_a_scripted_round` 在前、
`tests/test_agent_f_inference.py::test_the_tool_layer_path_gets_the_registered_seam` 在后）：
目标判据 setup 时 `_ROLE_SEAMS={'F': LlmSeam@…, 'E': None}`（基线应为 `{}`），
于是那条判据的负控前提被换掉，`history` 上没有 `product` 键 ⇒
`KeyError: 'product'`（`tests/test_agent_f_inference.py:461`）。

## 这一份守什么

本文件在两个层次上复现同一件事（都只用公开的登记口，不碰产品私有状态），
两张逐角色注册表都覆盖（`_ROLE_SEAMS` 与 `_ROLE_CONFIGS`；业主 2026-11-09 裁定
"同一类进程级注册表一并进基线"）：

1. 导入期：模块级 `AF.set_default_llm(POLLUTER)` 与 `LS.set_role_config(...)` ——
   与 `host.py:553` 同一机制。基线若晚于测试模块导入才拍（改前的 setup 快照就是
   "晚于"，而且会被模块夹具再污染），它们就会被吃进基线 ⇒ 判据①红。
2. 模块级夹具：`a_module_fixture_that_registers_a_seam`（`scope="module"`）同时登记
   一条缝与一份配置。夹具 setup 早于本条判据的函数级夹具 ⇒ 判据体里必须已经看不到
   它们（`_restore_role_seams` 的 setup 装回基线）。

反真空：两个层次的污染动作都必须真的发生过，否则"看不见"可能只是"没人登记过"。
"""
from __future__ import annotations

import pytest

from agentflow import agent_f as AF
from agentflow import llmseam as LS

#: 导入期那条配置的落点（一个不会与任何用例工作区重合的假根）。
POLLUTER_ROOT = "/agentflow-temp/import-time-polluter-ws"

#: 导入期副作用（与 `host.wired_llm_conductor` 里那一行无条件装配同一机制）：
#: pytest 在收集阶段导入本模块，所以它们一定发生在"第一条判据 setup"之前。
POLLUTER = object()
AF.set_default_llm(POLLUTER)
LS.set_role_config("F", POLLUTER_ROOT, {"round_cost_usd": 1.0})

#: 导入期那一刻的读数（反真空用：判据 setup 会把两张表装回基线，届时就看不到它们了 ——
#: 但"它们确实被登记过"必须有一条机械证据，否则"基线里没有"可能只是"没人登记过"）。
IMPORT_TIME_SEAM = LS.role_seam("F")
IMPORT_TIME_CONFIG = LS.role_config("F", POLLUTER_ROOT)


@pytest.fixture(scope="module")
def a_module_fixture_that_registers_a_seam() -> dict:
    """模块级夹具里登记一条缝与一份配置（真实形态：`tests/test_l_formalizes_what_b_says.py:156`）。"""
    seam = object()
    root = "/agentflow-temp/module-fixture-ws"
    LS.set_role_seam("F", seam)
    LS.set_role_config("F", root, {"round_cost_usd": 9.9})
    return {"seam": seam, "root": root}


def test_the_baseline_has_no_seam_from_the_import_time_polluter(
        role_registry_baseline: dict) -> None:
    """基线里不许有 `F`（有 = 基线拍在测试模块导入之后）；两张表都要干净。"""
    assert "F" not in role_registry_baseline["seams"], (
        "会话基线里出现了 `F` 的缝 ⇒ 基线是在测试模块导入之后拍的"
        "（别的模块的导入期副作用被当成了会话起点）。拍点必须留在 "
        "`tests/conftest.py` 的导入期（见 `_ROLE_REGISTRY_BASELINE` 上方那段），"
        "否则工具路径会把'没登记缝'读成'登记了别人的缝'。")
    assert ("F", POLLUTER_ROOT) not in role_registry_baseline["configs"], (
        "会话基线里出现了导入期登记的 `(角色, 根)` 配置 ⇒ 基线拍晚了。"
        "`_ROLE_CONFIGS` 与 `_ROLE_SEAMS` 是同一类进程级注册表，必须进同一份基线。")
    # 反真空：本文件导入期那两手真的执行过（否则上面两句可能只是"没人登记过"）。
    assert IMPORT_TIME_SEAM is POLLUTER, (
        "导入期的 `AF.set_default_llm(POLLUTER)` 没生效 ⇒ 这条判据的前提不成立")
    assert IMPORT_TIME_CONFIG == {"round_cost_usd": 1.0}, (
        "导入期的 `LS.set_role_config(...)` 没生效 ⇒ 这条判据的前提不成立")


def test_a_module_fixture_seam_is_gone_before_the_test_body_runs(
        a_module_fixture_that_registers_a_seam: dict) -> None:
    """模块级夹具登记的缝与配置，在判据体里必须已经被装回基线（否则就是"污染成了基线"）。"""
    assert a_module_fixture_that_registers_a_seam, "模块级夹具没跑 ⇒ 这条判据的前提不成立"
    assert "F" not in LS._ROLE_SEAMS, (
        "模块级夹具登记的缝活到了判据体里：`_restore_role_seams` 只在收尾还原、"
        "setup 没有装回基线 ⇒ 模块夹具的副作用被当成了这条判据的起点"
        "（最小复现与现场读数见模块 docstring）。")
    assert LS.role_config("F", a_module_fixture_that_registers_a_seam["root"]) is None, (
        "模块级夹具登记的配置活到了判据体里：`_ROLE_CONFIGS` 不在还原面上"
        "（或 setup 没有装回基线）⇒ 下一条判据会读到别人的装配期配置。")

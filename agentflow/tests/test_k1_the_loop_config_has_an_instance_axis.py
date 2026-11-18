# -*- coding: utf-8 -*-
"""SH-02：循环配置表有实例轴（同一动作、两个实例各一组步数/预算）。

判据只钉一处：`LlmBackend._loop_cfg`（`call` 取配置的唯一入口）。
改前这张表只按 `(role, action)` 建键，实例轴在这一层被丢掉；现在每一格可以带
`by_instance: {<实例标签>: {...}}`，按这一趟的 `instance` 叠上去。键不改型
（`loops=` 是构造入参，CLI `--drive` 也照它写）。
"""
from __future__ import annotations

import pathlib
import sys

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agentflow.agent_loop import LlmBackend  # noqa: E402


class _Inner:
    """内层后端的替身：本文件不走到它（只量配置读数）。"""

    def known_roles(self):
        return ()

    def resolve(self, role):
        return None

    def call(self, role, action, params, *, token, instance="", task_id=""):
        return {"inner": True}


def _backend() -> LlmBackend:
    loops = {
        ("E", "run"): {"max_steps": 5, "by_instance": {"e1": {"max_steps": 9}}},
        ("E", ""): {"max_steps": 9, "by_instance": {"e1": {"max_steps": 12}}},
    }
    return LlmBackend(loops=loops, inner=_Inner(), session_root=pathlib.Path("."),
                      max_steps=30)


def test_the_loop_config_has_an_instance_axis() -> None:
    b = _backend()
    # 同一动作：实例 e1 有自己那一组，别的实例仍用角色/动作那一格。
    assert b._loop_cfg("E", "run", "e1") == {"max_steps": 9}
    assert b._loop_cfg("E", "run", "e2") == {"max_steps": 5}
    # 反真空：不给实例 ⇒ 与改前逐字相同（读不到实例这一轴时老表的行为不变）。
    assert b._loop_cfg("E", "run", "") == {"max_steps": 5}
    # 空动作那一档（"只派活"）：默认档仍是 self.max_steps，实例覆盖同样生效。
    assert b._loop_cfg("E", "", "") == {"max_steps": 9}
    assert b._loop_cfg("E", "", "e1") == {"max_steps": 12}
    # 没登记的动作 ⇒ None（调用方据此交给内层后端，逐字不变）。
    assert b._loop_cfg("E", "not_registered", "e1") is None
    assert b._loop_cfg("C", "run", "") is None

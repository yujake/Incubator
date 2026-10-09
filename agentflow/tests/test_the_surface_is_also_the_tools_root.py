# -*- coding: utf-8 -*-
"""D8 / E23：把"每实例一个注册表"的装配点接上 —— 检查的基准 == 执行的基准。

业主 2026-10-09 裁定 D8 = 修。现场（`draft/90` §2 的 E23，实现行号在那里）：

- `_surface_refusal`（`agent_loop.py`）判"这条路径在不在你的面里"，基准是这一趟的
  `workspace_root`（跟着面走）；
- 而 `fs.*` 真正落盘的根是注册表的根 —— 装配点（`LlmBackend.registry_factory`）
  此前在 `cli.py` / `webui` 里从来没接 ⇒ 子代理用的是共用注册表（根 = 父的工作区）。
- 后果：一条相对路径的检查结论是"在面内"，真写下去却落在面外；而测试全绿。

判据（正控 2 / 负控 1 / 反真空 1）：

- 正控①：`wired_llm_conductor` 回来的 `backend.registry_factory` 可调用
  （这就是"装配点接上了"的读数 —— 它此前是 `None`）；
- 正控②：工厂按面造出来的注册表，`fs.*` 的根就是那个面（写一条相对路径 ⇒ 落在面里）；
- 负控：没有面时走共用注册表（老行为不变：`backend.registry` 还是那一份）；
- 反真空：面目录不存在时fs 工具自己的沙箱仍拒（面这一层不是唯一的防线）。
"""
from __future__ import annotations

import pathlib

from agentflow import host as H
from agentflow.store import Store


def _wiring(tmp_path: pathlib.Path):
    ws = tmp_path / "ws"
    ws.mkdir(parents=True, exist_ok=True)
    st = Store(ws)
    st.init()
    return ws, H.wired_llm_conductor(st, loops={}, session_root=ws, sid="d8", max_steps=2)


def test_the_assembly_point_is_wired(tmp_path: pathlib.Path):
    """正控①：装配点接上了 —— `registry_factory` 可调用（改前是 `None`，E23 的根因）。"""
    _ws, wiring = _wiring(tmp_path)
    assert callable(wiring["backend"].registry_factory), (
        "`LlmBackend.registry_factory` 还是 None ⇒ 子代理会用共用注册表"
        "（根 = 父的工作区）而检查按面走 —— 那正是 E23"
    )


def test_the_registry_for_a_face_uses_that_face_as_the_fs_root(tmp_path: pathlib.Path):
    """正控②：按面造出来的注册表，`fs.*` 的根就是那个面（检查基准 == 执行基准）。"""
    ws, wiring = _wiring(tmp_path)
    face = ws / "out" / "surfaces" / "t-parent" / "S01"
    face.mkdir(parents=True, exist_ok=True)
    reg = wiring["backend"].registry_factory(str(face))
    res = reg.call("fs.write", role="D", path="笔记.md", content="落在面里")
    assert res.ok, (res.error, res.meta)
    assert (face / "笔记.md").is_file(), list(face.iterdir())
    assert not (ws / "笔记.md").exists(), "相对路径落到了工作区根 ⇒ 执行基准与检查基准分家了"


def test_without_a_face_the_shared_registry_is_unchanged(tmp_path: pathlib.Path):
    """负控：没有面时仍是共用注册表（老行为逐字不变）。"""
    ws, wiring = _wiring(tmp_path)
    shared = wiring["registry"]
    assert shared is wiring["backend"].registry
    res = shared.call("fs.write", role="D", path="工作区根下的文件.md", content="x")
    assert res.ok, (res.error, res.meta)
    assert (ws / "工作区根下的文件.md").is_file()


def test_the_face_registry_still_has_the_tool_sandbox(tmp_path: pathlib.Path):
    """反真空：面这一层不是唯一防线 —— 出了工作区，`fs` 工具自己的沙箱照旧拒。"""
    ws, wiring = _wiring(tmp_path)
    face = ws / "out" / "surfaces" / "t-parent" / "S01"
    face.mkdir(parents=True, exist_ok=True)
    reg = wiring["backend"].registry_factory(str(face))
    res = reg.call("fs.write", role="D", path="../../../../外面.md", content="x")
    assert res.ok is False, res

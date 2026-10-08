# -*- coding: utf-8 -*-
"""S1n-b：读写面的强制 —— 子代理只能读写父切割给它的面（业主 T23）。

`draft/92` §3.6：面是每实例的；强制点有两处：
① 这一步的工具调用越没越面（`agent_loop._surface_refusal`，本文件判）；
② 面从哪儿来（`LlmBackend.call` 从父的名册里读 `surface` 那一格，传进 `run(surface=…)`）。

## 判据（正控 2 / 负控 3 / 反真空 2）

正控：① 面内写新文件成功（"若子代理想新写文件，这个是允许的"）；
② 面内的子目录也放行（判的是落在哪儿，不是"存在不存在"）。
负控：① `../` 越出 ⇒ 拒 ② 绝对路径在面外 ⇒ 拒 ③ 别人的面 ⇒ 拒；
反真空：① 没设面 ⇒ 老行为逐字不变（`fs.*` 照旧走工作区沙箱）；
② 面路径读不成/不是目录 ⇒ 拒（不许当"整工作区可写"）。
"""
from __future__ import annotations

import json
import pathlib
from pathlib import Path
from typing import Any

from agentflow.agent_loop import AgentLoop
from agentflow.conductor import Conductor, LocalBackend
from agentflow.llmseam import LlmSeam
from agentflow.store import Store
from agentflow.tools import build_registry


class _Gate:
    spec = type("Spec", (), {"model": "stub", "api_key": "x"})()

    def __init__(self, replies: list[dict]) -> None:
        self.replies = replies
        self.systems: list[str] = []

    def complete(self, prompt: str, *, scope: str = "", system: str | None = None,
                 **kw: Any) -> Any:
        self.systems.append(system or "")
        item = self.replies[min(len(self.systems) - 1, len(self.replies) - 1)]
        return type("Reply", (), {"ok": True, "text": item.get("text", ""),
                                  "tool_calls": tuple(item.get("tool_calls", ())),
                                  "tokens_in": 10, "tokens_out": 10,
                                  "error_detail": "", "error_kind": ""})()


RELPATH = "out/surfaces/t-0001/S01"


def _loop(tmp_path: pathlib.Path, *, surface: str = "") -> tuple[AgentLoop, pathlib.Path]:
    ws = tmp_path / "ws"
    st = Store(ws)
    st.init()
    cond = Conductor(st, policy=None, backend=LocalBackend({}))
    reg = build_registry(store=st, conductor=cond, workspace_root=ws).registry
    loop = AgentLoop(role="D", session_root=ws, registry=reg, conductor=cond,
                     seam=LlmSeam(role="D", session_root=ws,
                                  gateway=_Gate([{"text": json.dumps({"final": "x"})}]),
                                  price=(0.0, 0.0), sid="s1nb"),
                     store=st, sid="s1nb", workspace_root=str(ws))
    loop.surface = surface
    if surface:
        # 面要在 `Store.init()` 之后建：init 拒绝往非空目录里建工作区（store.py 的守卫）
        Path(surface).mkdir(parents=True, exist_ok=True)
    return loop, ws


def _write(loop: AgentLoop, path: str) -> dict[str, Any]:
    return loop._do_tool({"name": "fs.write", "args": {"path": path, "content": "x"}})  # noqa: SLF001


def test_inside_the_surface_a_new_file_is_allowed(tmp_path: pathlib.Path):
    """正控：面内写新文件成功（业主："若子代理想新写文件，这个是允许的"）。

    口径（过渡语义，见 `_surface_refusal` 的 docstring）：面是工作区里的一个子目录，
    所以路径按工作区相对写全（`out/surfaces/<owner>/<slot>/…`）；面外一律拒。
    """
    surface = tmp_path / "ws" / "out" / "surfaces" / "t-0001" / "S01"
    loop, _ws = _loop(tmp_path, surface=str(surface))
    got = _write(loop, f"{RELPATH}/新建的.md")
    assert got.get("ok") is True, got
    assert (surface / "新建的.md").is_file(), list(surface.iterdir())
    # 面内的子目录也放行（判的是落在哪儿）
    sub = surface / "子目录"
    sub.mkdir()
    assert _write(loop, f"{RELPATH}/子目录/再一层.md").get("ok") is True


def test_outside_the_surface_is_refused(tmp_path: pathlib.Path):
    """负控：`../` 与绝对路径在面外 ⇒ 拒（且拒信里点名面在哪里）。"""
    surface = tmp_path / "ws" / "out" / "surfaces" / "t-0001" / "S01"
    loop, ws = _loop(tmp_path, surface=str(surface))
    up = _write(loop, f"{RELPATH}/../越界.md")
    assert up.get("ok") is False and "越出了你这趟的读写面" in str(up.get("error")), up
    assert not (surface.parent / "越界.md").exists(), "越界的那一份不许落盘"
    outside = tmp_path / "别处.txt"
    abs_try = _write(loop, str(outside))
    assert abs_try.get("ok") is False, abs_try
    assert not outside.exists()
    assert ws  # 工作区本身也在面外（这一条正是"面 ≠ 工作区"）


def test_another_instances_surface_is_refused(tmp_path: pathlib.Path):
    """负控（业主："父原则上必须把各子代理的面拆开"）：别人的面 ⇒ 拒。"""
    mine = tmp_path / "ws" / "out" / "surfaces" / "t-0001" / "S01"
    theirs = tmp_path / "ws" / "out" / "surfaces" / "t-0001" / "S02"
    loop, _ws = _loop(tmp_path, surface=str(mine))
    theirs.mkdir(parents=True, exist_ok=True)
    got = _write(loop, str(theirs / "别人的.md"))
    assert got.get("ok") is False and "面外" in str(got.get("error")), got
    assert not (theirs / "别人的.md").exists()


def test_without_a_surface_nothing_changes(tmp_path: pathlib.Path):
    """反真空：没设面 ⇒ 老行为逐字不变（`fs.*` 照旧走工作区沙箱）。"""
    loop, ws = _loop(tmp_path)
    assert loop.surface == ""
    got = _write(loop, "工作区根下的文件.md")
    assert got.get("ok") is True, got
    assert (ws / "工作区根下的文件.md").is_file(), list(ws.iterdir())
    # 出了工作区仍然被 `fs_tools` 自己的沙箱挡住（那一层判据没动）
    out = _write(loop, "../外面.md")
    assert out.get("ok") is False, out


def test_a_missing_surface_directory_is_a_refusal(tmp_path: pathlib.Path):
    """反真空（第二处）：面根本不在盘上 ⇒ 拒（不许当"整工作区可写"）。"""
    loop, _ws = _loop(tmp_path, surface=str(tmp_path / "ws" / "out" / "surfaces" / "无此面"))
    got = _write(loop, "x.md")
    assert got.get("ok") is False and "面" in str(got.get("error")), got


def test_the_surface_comes_from_the_parents_roster(tmp_path: pathlib.Path):
    """正控（接线那一半）：父名册里那一格 `surface` 能被读出来，指向面目录。

    这一条只钉"读得出来且算得出路径"（`LlmBackend.call` 用的就是同一对 API）——
    真正传进子循环那一趟在 `draft/95` 的 M2 探针跑里验（真跑一次 M→A）。
    """
    from agentflow.conductor import Conductor as C
    from agentflow.secretary import Secretary, surface_dir

    ws = tmp_path / "ws"
    st = Store(ws)
    st.init()
    cond = C(st, policy=None, backend=LocalBackend({}))
    owner = cond.open_top_level_run("M", "父那一趟")
    child = cond._write_new_row({
        "task_id": "", "role": "D", "action": "run_once", "called_by": "M",
        "parent_task_id": owner, "depth": 2, "input_key": "s1nb@child",
        "status": "done", "outcome": "ok", "refusal_reason": None, "instance": "",
        "detail": "一个子代理", "error": None, "started_at": "2026-10-08T22:00:00+08:00",
        "ended_at": "2026-10-08T22:05:00+08:00", "tokens": 0, "usd": 0.0,
        "artifacts": [], "inputs": [],
    }, note="start:D.run_once")
    sec = Secretary("M", root=ws, store=st)
    reg = sec.roster_add(owner=owner, role="D", task_id=child, brief="一件活")
    assert reg["surface"] == "S01", reg
    roster = sec.roster_rows(owner)[0]
    slot = next(str(r["surface"]) for r in roster if str(r["task_id"]) == child)
    got = surface_dir(ws, owner, slot)
    assert got.is_dir() and got.name == "S01", got

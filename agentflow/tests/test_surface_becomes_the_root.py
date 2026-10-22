# -*- coding: utf-8 -*-
"""S1n-c：面就是这一趟的 `fs.*` 根 —— 每实例一个注册表（业主 T23 的原始写法）。

`draft/92` §3.6：装配点给一个 `surface -> registry` 的工厂（`LlmBackend.registry_factory`），
`LlmBackend.call` 按这一趟的面选注册表 —— 于是子代理写裸相对路径 `x.md` 就落在
它自己的面里，而 `..` 越界由 `fs_tools` 自己的沙箱判据（`resolve() + relative_to(root)`）挡住。

## 判据（正控 3 / 负控 2 / 反真空 1）

正控：① 带面的子循环：写 `笔记.md`（裸相对路径）落在面里（不是工作区根）；
② 同一个工作区里两个面各写各的，互不串（面 = 各自的根）；
③ 名字第二次派活（I-12 复用）仍然找得到自己的面（`task_id → 名字` 在对照表里）。
负控：① `../越界.md` ⇒ 被 `fs_tools` 的沙箱拒（面就是根，越界在工具层就被挡）；
② 退役的名字不再读出原槽位（槽位已归别人 ⇒ 照旧读就是跨代理重叠）。
反真空：工厂抛异常 ⇒ 退回共用注册表（老行为），不静默当"切过面"。
"""
from __future__ import annotations

import json
import pathlib
from typing import Any

from agentflow.agent_loop import AgentLoop, LlmBackend
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


def _step(tool: str, args: dict) -> dict:
    # 规范形态是扁平的：`{"tool": "<工具名>", "args": {…}}`
    # （嵌套的 `{"tool": {"name":…}}` 会被判"tool 必须是一个工具名字符串"）。
    return {"text": json.dumps({"tool": tool, "args": args}, ensure_ascii=False)}


def _setup(tmp_path: pathlib.Path, *, with_factory: bool = True):
    ws = tmp_path / "ws"
    st = Store(ws)
    st.init()
    cond = Conductor(st, policy=None, backend=LocalBackend({}))
    owner = cond.open_top_level_run("M", "父那一趟")
    from agentflow.secretary import surface_dir

    sec = __import__("agentflow.secretary", fromlist=["Secretary"]).Secretary(
        "M", root=ws, store=st)
    reg = sec.roster_add(owner=owner, role="D", task_id="pending", brief="占位（稍后换真行）")
    # 真代理行（名字/面都挂在它上面）
    child = cond._write_new_row({
        "task_id": "", "role": "D", "action": "write_report", "called_by": "M",
        "parent_task_id": owner, "depth": 2, "input_key": "s1nc@child", "status": "running",
        "outcome": None, "refusal_reason": None, "instance": "", "detail": "一个子代理",
        "error": None, "started_at": "2026-10-08T22:00:00+08:00", "ended_at": None,
        "tokens": 0, "usd": 0.0, "artifacts": [], "inputs": [],
    }, note="start:D.write_report")
    # 把那个名册项的 task_id 改指到真行上（测试夹具：名册要的是"这一行属于谁"）
    from agentflow.secretary import append_jsonl, roster_index_path

    append_jsonl(roster_index_path(ws, owner),
                 {"kind": "bind", "owner": owner, "name": reg["name"], "role": "D",
                  "task_id": child, "at": "2026-10-08T22:00:01+08:00"})
    surface = surface_dir(ws, owner, reg["surface"])
    surface.mkdir(parents=True, exist_ok=True)
    # 面里先放一样东西：2026-10-22 的真机口径是「空面不算切面」
    # （`agent_loop._surface_root_decision`，判据 `tests/test_an_empty_surface_is_not_a_cut.py`）——
    # 切一个空目录进去等于把这一趟的手脚绑住（真机上 G 因此读不到 `out/paper/main.tex`），
    # 于是 `LlmBackend.call` 会如实退回共用注册表。本文件要判的是"面内的裸相对路径落在哪"，
    # 所以夹具必须交出一个真的被切了的面（非空）；空面那一档由上面那条判据单独守。
    (surface / "面内已有.md").write_text("这一趟要用的那一块\n", encoding="utf-8", newline="\n")

    def factory(path: str) -> Any:
        return build_registry(store=st, conductor=cond, workspace_root=path).registry

    backend = LlmBackend(inner=LocalBackend({}), loops={("D", "write_report"): {}},
                         session_root=ws, conductor=cond, store=st, sid="s1nc",
                         workspace_root=str(ws), registry=build_registry(
                             store=st, conductor=cond, workspace_root=ws).registry,
                         registry_factory=factory if with_factory else None)
    return st, cond, backend, ws, owner, child, surface


def test_a_children_bare_relative_write_lands_in_its_own_surface(tmp_path: pathlib.Path):
    """正控：写裸相对路径 ⇒ 落在面里（面就是这一趟的 `fs.*` 根）。"""
    st, cond, backend, ws, owner, child, surface = _setup(tmp_path)
    # 替身模型：先写一个裸相对路径的文件，再收工
    gate = _Gate([_step("fs.write", {"path": "笔记.md", "content": "我自己的面"}),
                  {"text": json.dumps({"final": "写完收工", "evidence": []}, ensure_ascii=False)}])
    backend.seam_factory = lambda role: LlmSeam(role=role, session_root=ws, gateway=gate,
                                               price=(0.0, 0.0), sid="s1nc")
    res = backend.call("D", "write_report", {}, token=None, instance="", task_id=child)
    assert res["stop_reason"] == "final", res
    assert (surface / "笔记.md").is_file(), (
        "裸相对路径必须落在面里（面 = 这一趟的 fs.* 根）", list(surface.iterdir()))
    assert not (ws / "笔记.md").exists(), ("不许落在工作区根上", list(ws.iterdir()))
    assert owner and cond and st  # 夹具引用（免得 lint 说没用）


def test_two_surfaces_do_not_see_each_other(tmp_path: pathlib.Path):
    """正控（两轴互不串）：同一个工作区里两个面各写各的 —— 各自是各自的根。"""
    st, cond, backend, ws, owner, child, surface = _setup(tmp_path)
    from agentflow.secretary import surface_dir

    other = surface_dir(ws, owner, "S02")
    other.mkdir(parents=True, exist_ok=True)
    reg_a = build_registry(store=st, conductor=cond, workspace_root=str(surface)).registry
    reg_b = build_registry(store=st, conductor=cond, workspace_root=str(other)).registry
    reg_a.call("fs.write", role="D", path="a.md", content="A")
    reg_b.call("fs.write", role="D", path="b.md", content="B")
    assert (surface / "a.md").is_file() and not (surface / "b.md").exists(), list(surface.iterdir())
    assert (other / "b.md").is_file() and not (other / "a.md").exists(), list(other.iterdir())
    assert child and backend


def test_escaping_the_surface_is_refused_by_the_tool_layer(tmp_path: pathlib.Path):
    """负控：面是根 ⇒ `../` 越界在 `fs_tools` 那一层就被挡（不需要上层再拦）。"""
    st, cond, backend, ws, owner, child, surface = _setup(tmp_path)
    reg = build_registry(store=st, conductor=cond, workspace_root=str(surface)).registry
    out = reg.call("fs.write", role="D", path="../越界.md", content="x")
    assert out.ok is False, out
    assert not (surface.parent / "越界.md").exists(), "越界的那一份不许落盘"
    assert backend and owner and child


def test_a_broken_factory_falls_back_to_the_shared_registry(tmp_path: pathlib.Path):
    """反真空：工厂抛异常 ⇒ 退回共用注册表（老行为），不静默当"切过面"。"""
    st, cond, backend, ws, owner, child, surface = _setup(tmp_path)

    def boom(_path: str) -> Any:
        raise RuntimeError("注入的工厂故障")

    backend.registry_factory = boom
    gate = _Gate([_step("fs.write", {"path": "退回.md", "content": "x"}),
                  {"text": json.dumps({"final": "收工", "evidence": []}, ensure_ascii=False)}])
    backend.seam_factory = lambda role: LlmSeam(role=role, session_root=ws, gateway=gate,
                                               price=(0.0, 0.0), sid="s1nc")
    res = backend.call("D", "write_report", {}, token=None, instance="", task_id=child)
    assert res["stop_reason"] == "final", res
    # 工厂坏了 ⇒ 用共用注册表（根 = 工作区）⇒ 文件落在工作区根，不在面里
    assert (ws / "退回.md").is_file(), list(ws.iterdir())
    assert not (surface / "退回.md").exists(), list(surface.iterdir())
    assert owner and cond and st


def _second_invocation(cond, owner: str) -> str:
    """再派一趟给同一个名字（I-12 复用：名册项不动，只加一个调用行）。"""
    return cond._write_new_row({
        "task_id": "", "role": "D", "action": "write_report", "called_by": "M",
        "parent_task_id": owner, "depth": 2, "input_key": "s1nc@again", "status": "running",
        "outcome": None, "refusal_reason": None, "instance": "", "detail": "同一个名字第二趟",
        "error": None, "started_at": "2026-10-08T23:00:00+08:00", "ended_at": None,
        "tokens": 0, "usd": 0.0, "artifacts": [], "inputs": [],
    }, note="start:D.write_report")


def test_a_reused_name_still_finds_its_surface(tmp_path: pathlib.Path):
    """正控（I-12 复用）：名字第二次派活，那一行仍然找得到自己的面。

    这条判据专门盯"只读名册那一份"的实现（红/绿）：名册的 `add` 行记的是第一次
    的 `task_id`，第二次调用只在对照表里（`bind`）⇒ 只读名册就会判"这一行没有面"，
    于是那一趟静默落回共用注册表（写进工作区根 —— 与别人抢同一份文件）。
    """
    st, cond, backend, ws, owner, child, surface = _setup(tmp_path)
    from agentflow.secretary import Secretary, append_jsonl, roster_index_path

    sec = Secretary("M", root=ws, store=st)
    name = str(sec.roster_rows(owner)[0][0]["name"])
    second = _second_invocation(cond, owner)
    append_jsonl(roster_index_path(ws, owner),
                 {"kind": "bind", "owner": owner, "name": name, "role": "D",
                  "task_id": second, "at": "2026-10-08T23:00:01+08:00"})
    gate = _Gate([_step("fs.write", {"path": "复用.md", "content": "第二趟"}),
                  {"text": json.dumps({"final": "收工", "evidence": []}, ensure_ascii=False)}])
    backend.seam_factory = lambda role: LlmSeam(role=role, session_root=ws, gateway=gate,
                                               price=(0.0, 0.0), sid="s1nc")
    res = backend.call("D", "write_report", {}, token=None, instance="", task_id=second)
    assert res["stop_reason"] == "final", res
    assert (surface / "复用.md").is_file(), list(surface.iterdir())
    assert not (ws / "复用.md").exists(), ("复用的那一趟也不许落回工作区根", list(ws.iterdir()))
    assert child


def test_a_retired_name_does_not_lend_its_surface_to_the_next_owner(tmp_path: pathlib.Path):
    """负控（不许串面）：退役的名字不再读出它原来那个槽位 —— 那时槽位已经归别人了。

    「名字不回收、面回收」的落点：若退役后照旧按名册那一格读面，新主人写的东西
    会与旧主人写的东西落在同一个目录里，而没有任何一层会报错（跨代理静默重叠）。
    """
    st, cond, backend, ws, owner, child, surface = _setup(tmp_path)
    from agentflow.secretary import Secretary, append_jsonl, roster_path

    sec = Secretary("M", root=ws, store=st)
    name = str(sec.roster_rows(owner)[0][0]["name"])
    # 只写"退役"那一格状态位：退役整机（三分支 + 销号名单）在
    # `test_roster_and_retire_are_the_secretarys_job.py` 里跑，这里只钉读侧的防串面。
    append_jsonl(roster_path(ws, owner),
                 {"kind": "retire", "owner": owner, "name": name, "task_id": child,
                  "branch": "waiting_no_children", "at": "2026-10-08T23:10:00+08:00"})
    state, why = sec.surface_release(owner=owner, name=name, slot="S01")
    assert state == "空闲" and not why, (state, why)
    other = sec.roster_add(owner=owner, role="E", task_id="t-0009", brief="接手那个面的人",
                           surface="S01")
    assert not other["problem"], other
    assert other["surface"] == "S01", other
    got = sec.surface_of(owner=owner, task_id=child)
    assert got["checked"] is False, ("退役的名字不许照旧读出槽位", got)
    assert got["path"] == "", got
    got2 = sec.surface_of(owner=owner, task_id="t-0009")
    assert got2["checked"] is True and got2["path"] == str(surface), got2
    assert backend and cond

# -*- coding: utf-8 -*-
"""S1g-2：面适配 —— 秘书要看"这件活在被派人的读写面里做不做得成"。

业主 2026-10-09 逐字（`draft/90` §0 第 6 条）：

> 「"超越职责"的一个主要可能是无法在被分配的读写面内完成任务，这个秘书也要帮忙看，
> 不只是看任务是否符合角色设计」

口径与机器形态写在 `draft/90` §1.11，符号级规格在 `draft/92` §3.3 的 S1g-2 块。
这一条读数回答的是一句话的所指是不是同一个文件，四档：

| `verdict` | 判据 | 意思 |
|---|---|---|
| `escapes` | 解析结果落在面外 | 越界 ⇒ 面内做不成 |
| `in_face` | 解析结果在面里（面已知时才给这一档） | 做得到 |
| `not_in_face` | 父视角那一份盘上有、面内那一份盘上没有 | 错位 ⇒ 面内做不成 |
| `unknown` | 面未定 / 两边都没有 / 解析不了 | 判不了（不许折成 in_face） |

## 判据（正控 2 / 负控 2 / 反真空 2 + 收口 1）

- 正控①：`fs.write` 点的路径在工作区里有、面里没有 ⇒ `fits=False` / `not_in_face`，
  且读数里两份落点都在（父视角那条、面内那条）；
- 正控②：面已知且落点在面内 ⇒ `fits=True` / `in_face`（面内的新文件也算做得到）；
- 负控①：绝对路径（在面外）/ `..` 逃出 ⇒ `escapes`，不读成 `in_face`；
- 负控②：只报不改 —— 判完这条读数，`params` 里的路径值逐字不变；
- 反真空①：非 `fs.` 动作 ⇒ `checked=False` / `fits=None`；`fs.` 但没给路径 ⇒
  `checked=True` / `fits=None` 且理由说"判不了（不是通过）"；
- 反真空②：面/名册读不成 ⇒ `fits=None`（不是 `True`）；
- 收口（E22）：`fs.move` 的 `src` 在面外 ⇒ 执行期被 `_surface_refusal` 拒
  （先前只看 `path` ⇒ 这一步是放行的）。
"""
from __future__ import annotations

import json
import pathlib
from pathlib import Path
from typing import Any

from agentflow.agent_loop import AgentLoop
from agentflow.conductor import Conductor, LocalBackend
from agentflow.llmseam import LlmSeam
from agentflow.secretary import Secretary, surface_dir
from agentflow.store import Store
from agentflow.tools import build_registry


def _ws(tmp_path: pathlib.Path) -> tuple[pathlib.Path, Store, Conductor]:
    ws = tmp_path / "ws"
    st = Store(ws)
    st.init()
    cond = Conductor(st, policy=None, backend=LocalBackend({}))
    return ws, st, cond


def _sec(ws: pathlib.Path, st: Store, *, task_id: str = "t-0001") -> Secretary:
    s = Secretary("M", root=ws, store=st)
    s.bind_task(task_id)
    return s


# --------------------------------------------------------------- 正控 / 负控


def test_the_parents_view_differs_from_the_childs_face(tmp_path: pathlib.Path):
    """正控①：这一份在工作区里（父的视角指得到它），而子那趟的根是它的面 ⇒ 面内做不成。

    这正是业主说的那一档：活符合角色设计、参数也齐全，而盘不在收件方手里。
    """
    ws, st, _cond = _ws(tmp_path)
    (ws / "out" / "paper").mkdir(parents=True)
    (ws / "out" / "paper" / "main.tex").write_text("\\documentclass{article}", encoding="utf-8")
    s = _sec(ws, st)
    got = s.surface_fit(action="fs.read", params={"path": "out/paper/main.tex"},
                        face=str(surface_dir(ws, "t-0001", "S01")))
    assert got["checked"] is True, got
    assert got["fits"] is False, got
    row = got["paths"][0]
    assert row["verdict"] == "not_in_face", row
    # 两份落点都要在纸上（否则"错位"这句话没法核对）
    assert row["ws"].endswith(str(Path("out") / "paper" / "main.tex")), row
    assert row["face"].endswith(str(Path("out") / "paper" / "main.tex")), row
    assert row["ws"] != row["face"], row
    assert row["ws_exists"] is True and row["face_exists"] is False, row
    assert "面内做不成" in got["reason"], got


def test_a_path_inside_a_known_face_fits(tmp_path: pathlib.Path):
    """正控②：面已知、落点在面内 ⇒ `in_face`（面内的新文件也算做得到）。"""
    ws, st, _cond = _ws(tmp_path)
    face = surface_dir(ws, "t-0001", "S01")
    face.mkdir(parents=True)
    s = _sec(ws, st)
    got = s.surface_fit(action="fs.write",
                        params={"path": str(face / "笔记.md")}, face=str(face))
    assert got["checked"] is True and got["fits"] is True, got
    assert got["paths"][0]["verdict"] == "in_face", got
    # 面内还没建的子目录同样是 in_face（判的是落在哪儿，不是存在不存在）
    got2 = s.surface_fit(action="fs.write",
                         params={"path": str(face / "子目录" / "再一层.md")}, face=str(face))
    assert got2["fits"] is True, got2


def test_an_escape_is_never_read_as_inside(tmp_path: pathlib.Path):
    """负控①：绝对路径在面外 / `..` 逃出 ⇒ `escapes`（不许读成 in_face）。"""
    ws, st, _cond = _ws(tmp_path)
    face = surface_dir(ws, "t-0001", "S01")
    face.mkdir(parents=True)
    outside = tmp_path / "别处.txt"
    outside.write_text("x", encoding="utf-8")
    s = _sec(ws, st)
    for raw in (str(outside), str(face / ".." / "越界.md")):
        got = s.surface_fit(action="fs.write", params={"path": raw}, face=str(face))
        assert got["fits"] is False, (raw, got)
        assert got["paths"][0]["verdict"] == "escapes", (raw, got)


def test_the_reading_does_not_touch_the_content(tmp_path: pathlib.Path):
    """负控②：只报不改 —— 判完这条读数，`params` 里的路径值逐字不变。"""
    ws, st, _cond = _ws(tmp_path)
    (ws / "out" / "paper").mkdir(parents=True)
    (ws / "out" / "paper" / "main.tex").write_text("x", encoding="utf-8")
    s = _sec(ws, st)
    params = {"path": "out/paper/main.tex", "content": "值一个字不许动"}
    before = json.dumps(params, ensure_ascii=False, sort_keys=True)
    got = s.surface_fit(action="fs.write", params=params,
                        face=str(surface_dir(ws, "t-0001", "S01")))
    assert got["fits"] is False, got
    assert json.dumps(params, ensure_ascii=False, sort_keys=True) == before, params


# --------------------------------------------------------------- 反真空


def test_other_actions_are_not_applicable(tmp_path: pathlib.Path):
    """反真空①：非 `fs.` 动作 ⇒ 不适用；`fs.` 但没给路径 ⇒ 判不了。都不是通过。"""
    ws, st, _cond = _ws(tmp_path)
    s = _sec(ws, st)
    other = s.surface_fit(action="manuscripts.write", params={"path": "x.md"})
    assert other["checked"] is False and other["fits"] is None, other
    assert "不适用" in other["reason"], other
    nopath = s.surface_fit(action="fs.list", params={})
    assert nopath["checked"] is True and nopath["fits"] is None, nopath
    assert "判不了" in nopath["reason"], nopath


def test_an_unknown_face_is_not_a_pass(tmp_path: pathlib.Path):
    """反真空②：面没定 ⇒ `fits=None`（`True` 只在面已知且落点在面里时给）。

    新起一个子代理时槽位要到派活那一刻才分（`surface_alloc` 与 `roster_add` 同一趟）——
    这一档判不了就是判不了，不许折成"没问题"。
    """
    ws, st, _cond = _ws(tmp_path)
    face = surface_dir(ws, "t-0001", "S01")
    face.mkdir(parents=True)
    s = _sec(ws, st)
    got = s.surface_fit(action="fs.write", params={"path": str(face / "笔记.md")})
    assert got["checked"] is True and got["fits"] is None, got
    assert got["paths"][0]["verdict"] == "unknown", got
    assert "判不了" in got["reason"], got
    # 名册读不成（没有 store）⇒ 名字到不了面 ⇒ 空串，不许假装知道
    assert s._face_of_name(owner="t-0001", name="D1") == ""  # noqa: SLF001


# --------------------------------------------------------------- 收口（E22）


class _Gate:
    spec = type("Spec", (), {"model": "stub", "api_key": "x"})()

    def complete(self, prompt: str, *, scope: str = "", system: str | None = None,
                 **kw: Any) -> Any:
        return type("Reply", (), {"ok": True, "text": json.dumps({"final": "x"}),
                                  "tool_calls": (), "tokens_in": 10, "tokens_out": 10,
                                  "error_detail": "", "error_kind": ""})()


def test_a_move_out_of_the_face_is_refused(tmp_path: pathlib.Path):
    """收口（`draft/90` E22）：`fs.move` 的 `src`/`dst` 与 `path` 走同一张表。

    先把"今天放行"这件事写成红的（`src` 在面外 ⇒ 先前只看 `args["path"]`，
    `fs.move` 没有 `path` ⇒ 一个字都不拦）。
    """
    ws = tmp_path / "ws"
    st = Store(ws)
    st.init()
    cond = Conductor(st, policy=None, backend=LocalBackend({}))
    reg = build_registry(store=st, conductor=cond, workspace_root=ws).registry
    face = ws / "out" / "surfaces" / "t-0001" / "S01"
    face.mkdir(parents=True)
    victim = ws / "别处的.md"
    victim.write_text("x", encoding="utf-8")
    loop = AgentLoop(role="D", session_root=ws, registry=reg, conductor=cond,
                     seam=LlmSeam(role="D", session_root=ws, gateway=_Gate(),
                                  price=(0.0, 0.0), sid="s1g2"),
                     store=st, sid="s1g2", workspace_root=str(ws))
    loop.surface = str(face)
    got = loop._do_tool({"name": "fs.move",  # noqa: SLF001
                         "args": {"src": "别处的.md",
                                  "dst": "out/surfaces/t-0001/S01/搬进来.md"}})
    assert got.get("ok") is False, got
    assert "越出了你这趟的读写面" in str(got.get("error")), got
    assert victim.is_file() and not (face / "搬进来.md").exists(), "面外那一份不许被搬动"
    # 负控：两边都在面内 ⇒ 放行（口径没被改宽成"一律拒"）
    src = face / "a.md"
    src.write_text("x", encoding="utf-8")
    ok = loop._do_tool({"name": "fs.move",  # noqa: SLF001
                        "args": {"src": "out/surfaces/t-0001/S01/a.md",
                                 "dst": "out/surfaces/t-0001/S01/b.md"}})
    assert ok.get("ok") is True, ok
    assert (face / "b.md").is_file(), list(face.iterdir())

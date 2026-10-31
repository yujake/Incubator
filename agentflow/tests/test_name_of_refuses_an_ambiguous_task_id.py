# -*- coding: utf-8 -*-
"""判据：按号反查名字（`name_of`）遇到"一个号两个名字"必须拒，不许静默取第一个。

## 为什么（`draft/151` 三-4）

写口从 2026-11-02 起拒"同一个号出现在两条 add"（`task_id_reused`），所以新数据不会有
这一形态。但 `projects/**` 里的历史名册有（`draft/150` §5.1 的数：116/881 个名册项
在正文的号与对照表的当前号之间分叉）；按号寻址那一侧已经因此改成拒歧义
（`agent_loop.roster_addresses` 的 `ambiguous_in_roster`），而 `name_of` 仍
`return` 第一个命中。后果不是读数难看，是 `surface_of` 会按第一个名字的槽位去切
读写面 —— 两个人的面重叠等于跨代理写同一份文件。

## 改前读数（`temp/probe_h11_leftovers.py` 的 K，2026-11-02 实测）

同一份名册（`t-000004` 同时挂在 D1 与 D2 名下）：

    roster_addresses(to=号) ⇒ {"how": "ambiguous_in_roster", "refused":
                                "ambiguous_in_roster", "candidates": ["D1", "D2"]}
    name_of(owner=父, task_id=号) ⇒ ("D1", "")        ← 静默取第一个

## 这一组守什么

1. 正题：一个号两个名字 ⇒ `name_of` 回空名 + 一句点名"几个名字"的理由；
   `surface_of` 因此 `checked=False`（不许假装切过面）；
2. 反真空：唯一命中的号照旧译得出来（收紧不许把正常那一档一起废掉）；
3. 反真空：真的没登记过的号照旧回"未登记"（不是把"歧义"与"没有"折成同一句话）。
"""
from __future__ import annotations

import pathlib

from agentflow import secretary as SEC
from agentflow.conductor import Conductor, LocalBackend
from agentflow.secretary import Secretary
from agentflow.store import Store

TS = "2026-10-24T19:40:00+08:00"


def _env(tmp_path: pathlib.Path) -> tuple[Secretary, str, pathlib.Path]:
    ws = tmp_path / "ws"
    st = Store(ws)
    st.init()
    cond = Conductor(st, policy=None, backend=LocalBackend({}))
    sec = Secretary("M", root=ws, store=st, enable_model=False)
    cond.secretary = sec
    cond.roster_sink = sec
    owner = str(cond.open_top_level_run("M", "顶趟这一趟"))
    return sec, owner, ws


def _two_names_one_id(sec: Secretary, owner: str, ws: pathlib.Path, task_id: str) -> None:
    """历史形态（写口今天拒）：同一个号挂在 D1 与 D2 名下。"""
    for name in ("D1", "D2"):
        SEC.append_jsonl(SEC.roster_path(ws, owner),
                         {"kind": "add", "owner": owner, "name": name, "role": "D",
                          "task_id": task_id, "first_task_id": task_id,
                          "brief": f"判据：{name}", "brief_source": "parent",
                          "surface": "S01" if name == "D1" else "S02", "at": TS})
        SEC.append_jsonl(SEC.roster_index_path(ws, owner),
                         {"kind": "bind", "owner": owner, "name": name, "role": "D",
                          "task_id": task_id, "at": TS, "first": True})


def test_an_ambiguous_task_id_is_not_resolved_to_the_first_name(
        tmp_path: pathlib.Path) -> None:
    """正题：一个号两个名字 ⇒ 不猜；`surface_of` 不许按第一个名字切面。"""
    sec, owner, ws = _env(tmp_path)
    _two_names_one_id(sec, owner, ws, "t-000004")
    name, why = sec.name_of(owner=owner, task_id="t-000004")
    assert name == "", ("按号反查静默取了一个名字", name, why)
    assert "2" in why and ("不猜" in why or "ambiguous" in why), why
    assert "D1" in why and "D2" in why, why
    face = sec.surface_of(owner=owner, task_id="t-000004")
    assert face.get("checked") is False, face
    assert str(face.get("slot") or "") == "", face


def test_a_unique_task_id_still_resolves(tmp_path: pathlib.Path) -> None:
    """反真空：唯一命中的号照旧译得出来（并且面照旧读得到）。"""
    sec, owner, _ws = _env(tmp_path)
    made = sec.roster_add(owner=owner, role="D", task_id="t-000009",
                          brief="判据夹具", task="做研究", want_name="D1")
    assert made.get("problem") == "", made
    name, why = sec.name_of(owner=owner, task_id="t-000009")
    assert (name, why) == ("D1", ""), (name, why)
    face = sec.surface_of(owner=owner, task_id="t-000009")
    assert face.get("checked") is True, face
    assert face.get("name") == "D1", face


def test_an_unregistered_task_id_still_says_it_is_unregistered(
        tmp_path: pathlib.Path) -> None:
    """反真空：没登记过的号仍回"未登记"（不许把"歧义"与"没有"折成同一句话）。"""
    sec, owner, _ws = _env(tmp_path)
    name, why = sec.name_of(owner=owner, task_id="t-999999")
    assert name == "", (name, why)
    assert "未登记" in why, why

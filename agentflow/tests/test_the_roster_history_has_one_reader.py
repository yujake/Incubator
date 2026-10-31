# -*- coding: utf-8 -*-
"""判据："谁绑过哪个号"只能有一处解析器。

## 为什么单为这件事立一条判据（`draft/151` 三-5）

名册正文 `<父>.jsonl` 的 `add` 行与对照表 `<父>-index.jsonl` 的 `bind` 行，是同一份
"哪个号绑给了谁"的历史。改前有两处各解析一遍、过滤条件逐字相同：

- `_roster_history`（号 → 名字：自愈的已知集、写口的"同号"拒绝都用它）；
- `_bound_task_ids`（名字 → 它的全部号：销号要标死的集合用它）。

两处今天给出相同答案，所以没有任何判据会红；但将来只改一处（例如 `add` 行也开始
带 `task_ids` 留痕），另一处就静默给出另一个答案 —— 而这一份历史的两个读法分别
决定"自愈会不会补重复行"与"销号漏不漏号"，两个后果都不可逆。

## 这一组守什么

1. 正题：解析器只有一处（`_roster_bindings`），两个读法都从它派生 ——
   打桩那一处，两个读法必须一起跟着变（改前：压根没有 `_roster_bindings`，红）；
2. 语义钉死（合并前后逐字不变）：同一个号在历史里出现两次（先 add 给 A、后 bind 给 B）
   ⇒ 已知集记 A（首个名字胜），而销号时 A 与 B 都拿得到这个号（两行都算它绑过）；
3. 反真空：真盘上写过一次的名字，两个读法都读得到它。
"""
from __future__ import annotations

import pathlib

import pytest

from agentflow import secretary as SEC
from agentflow.conductor import Conductor, LocalBackend
from agentflow.secretary import Secretary
from agentflow.store import Store

TS = "2026-10-24T19:40:00+08:00"


def _env(tmp_path: pathlib.Path) -> tuple[Secretary, str]:
    ws = tmp_path / "ws"
    st = Store(ws)
    st.init()
    cond = Conductor(st, policy=None, backend=LocalBackend({}))
    sec = Secretary("M", root=ws, store=st, enable_model=False)
    cond.secretary = sec
    cond.roster_sink = sec
    owner = str(cond.open_top_level_run("M", "顶趟这一趟"))
    return sec, owner


def test_both_readers_come_from_one_parser(tmp_path: pathlib.Path,
                                           monkeypatch: pytest.MonkeyPatch) -> None:
    """正题：`_roster_history` 与 `_bound_task_ids` 共用 `_roster_bindings` 这一处解析。"""
    sec, owner = _env(tmp_path)
    assert hasattr(Secretary, "_roster_bindings"), (
        "没有 `_roster_bindings`：'谁绑过哪个号'还是两处各解析一遍"
        "（`_roster_history` 与 `_bound_task_ids`）—— 见 `draft/151` 三-5")
    fake = [("t-000001", "A"), ("t-000002", "A"), ("t-000001", "B")]
    monkeypatch.setattr(Secretary, "_roster_bindings",
                        lambda self, owner: (list(fake), []))
    history, bad = sec._roster_history(owner)
    assert bad == [], bad
    assert history == {"t-000001": "A", "t-000002": "A"}, history
    assert sec._bound_task_ids(owner, "A") == ["t-000001", "t-000002"]
    assert sec._bound_task_ids(owner, "B") == ["t-000001"], (
        "第二个名字绑过的号丢了：销号会漏标（`draft/150` §5.1-③ 的读数 H）")


def test_the_merged_parser_keeps_the_semantics_of_both(tmp_path: pathlib.Path) -> None:
    """语义：同一个号先 add 给 A、后 bind 给 B ⇒ 已知集记 A，销号时 A 与 B 都算绑过。"""
    sec, owner = _env(tmp_path)
    ws = tmp_path / "ws"
    for name in ("A1", "B1"):
        SEC.append_jsonl(SEC.roster_path(ws, owner),
                         {"kind": "add", "owner": owner, "name": name, "role": "D",
                          "task_id": "t-000001" if name == "A1" else "t-000002",
                          "first_task_id": "t-000001", "brief": f"判据：{name}",
                          "brief_source": "parent", "surface": "", "at": TS})
        SEC.append_jsonl(SEC.roster_index_path(ws, owner),
                         {"kind": "bind", "owner": owner, "name": name, "role": "D",
                          "task_id": "t-000001" if name == "A1" else "t-000002",
                          "at": TS, "first": True})
    # B1 后来又接了 A1 那个号（历史异常形态：写口今天拒，盘上可能有）
    SEC.append_jsonl(SEC.roster_index_path(ws, owner),
                     {"kind": "bind", "owner": owner, "name": "B1", "role": "D",
                      "task_id": "t-000001", "at": TS})
    history, _bad = sec._roster_history(owner)
    assert history["t-000001"] == "A1", history          # 首个名字胜
    assert sec._bound_task_ids(owner, "A1") == ["t-000001"], sec._bound_task_ids(owner, "A1")
    assert sec._bound_task_ids(owner, "B1") == ["t-000002", "t-000001"], (
        "B1 绑过的两个号必须都在（销号要标死全部）", sec._bound_task_ids(owner, "B1"))


def test_a_really_written_name_is_read_by_both(tmp_path: pathlib.Path) -> None:
    """反真空：真盘上写过一次的名字，两个读法都读得到（判据的扫描面没跑偏）。"""
    sec, owner = _env(tmp_path)
    made = sec.roster_add(owner=owner, role="D", task_id="t-000009",
                          brief="判据夹具", task="做研究", want_name="D1")
    assert made.get("problem") == "", made
    history, _bad = sec._roster_history(owner)
    assert history.get("t-000009") == "D1", history
    assert sec._bound_task_ids(owner, "D1") == ["t-000009"]

# -*- coding: utf-8 -*-
"""判据：工具层的**受控拒绝**必须在 `errorstats` 上看得见（一条都不许消失）。

## 改前实测的形态（根因）

`conductor_tools.py::_out` 最后一句是 `return ok(data, **data)`：一条"拒绝"在工具层
是 `ok=True`，拒因写在 `data.state == "refused"` / `data.refusal_code` 里。
而 `errorstats` 的 `agent_step` 分支只认 `result.ok is False`（`_tool_refusal_family`
也只读 `result.error` / `result.detail`）⇒ 真形受控拒绝 **total 0、连 unclassified
都没有**。用真工具 `conductor.ack(close="nope")` 的返回当夹具，改前计数是 0。

## 四条

a. 真形受控拒绝 ⇒ `by_role` 里能数到（改前红：total 0）；
b. `ok=False` 的老形态仍按原样计（回归，不许被新判据抢走）；
c. 反真空：把结构判据摘掉 ⇒ a 回到 0（数出来的确实是这一条判据，不是别的）；
d. 同一次拒绝不重复计两次：`data.reason` 里已经有一个可扫的码时，只记一次。

码与类目的口径：受控拒绝记进 `tool_refused_controlled`（与既有 `tool_refused_*` 并列），
**不硬塞进参数错误那一族** —— "你的参数形状不合法"与"框架按受控码拒了这次操作"不是
同一件事，混在一起会让参数错误那一族的读数说谎。
"""
from __future__ import annotations

import json
import pathlib

import pytest

from agentflow import errorstats as ES
from agentflow.tools.conductor_tools import conductor_ack

#: 真工具产出的受控拒绝：`close` 不在 `ITEM_CLOSES` 里 ⇒ `data.state="refused"`
#: （`conductor_tools.py:2712-2716`），而 `ToolResult.ok` 仍是 True。
_ACK_REFUSAL = conductor_ack(None, ["t-000123"], close="nope")


def _workspace(root: pathlib.Path, records: list[dict]) -> pathlib.Path:
    """最小工作区：一份空的 `events.jsonl` + 一份会话记录（与真盘同形）。"""
    (root / "data").mkdir(parents=True, exist_ok=True)
    (root / "data" / "events.jsonl").write_text("", encoding="utf-8")
    sessions = root / "sessions"
    sessions.mkdir(parents=True, exist_ok=True)
    (sessions / "s1.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n",
        encoding="utf-8")
    return root


def _step(role: str, result: dict, *, index: int = 1) -> dict:
    return {"kind": "agent_step", "role": role, "index": index, "shape": "tool",
            "payload": {"name": "conductor.ack"}, "result": result}


def _real_refusal_record(role: str = "H") -> dict:
    """一条真形受控拒绝的会话记录（`result` 就是真工具的 `to_dict()`）。"""
    result = _ACK_REFUSAL.to_dict()
    assert result["ok"] is True, "夹具前提：受控拒绝在工具层是 ok=True"
    assert result["data"]["state"] == "refused", "夹具前提：受控拒绝的 state"
    return _step(role, result)


# ---------------------------------------------------------------- a 真形计数


def test_a_controlled_refusal_is_counted_in_by_role(tmp_path: pathlib.Path) -> None:
    """a：真形受控拒绝 ⇒ `by_role` 里数得到；改前这条是 0（本文件第一段）。"""
    assert _real_refusal_record()["result"]["ok"] is True
    stats = ES.error_action_stats(_workspace(tmp_path / "ws", [_real_refusal_record()]))

    assert stats.checked is True
    assert stats.total == 1, "改前（没有结构判据时）这里是 0 —— 受控拒绝在统计上不存在"
    assert stats.by_role["H"] == {"tool_refused_controlled": 1}, stats.by_role
    assert stats.count("H", "tool_refused_controlled") == 1


# ---------------------------------------------------------------- b 老形态回归


def test_an_ok_false_tool_refusal_still_counts_by_its_old_rule(
        tmp_path: pathlib.Path) -> None:
    """b：`ok=False` 的老形态照旧按原来的族表计（新判据只补 ok=True 那一半）。"""
    record = _step("C", {"ok": False, "data": None, "meta": {},
                         "error": "文件不存在：out/none.md"})
    stats = ES.error_action_stats(_workspace(tmp_path / "ws", [record]))

    assert stats.total == 1
    assert stats.by_role["C"] == {"tool_refused_path": 1}, stats.by_role


# ---------------------------------------------------------------- c 反真空


def test_the_structural_predicate_is_load_bearing(
        monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path) -> None:
    """c：把结构判据摘掉 ⇒ a 回到 0（且拒绝仍然"看得见"：进 unclassified）。"""
    assert ES._controlled_refusal_family(_ACK_REFUSAL.to_dict()) == (
        "", "tool_refused_controlled")

    monkeypatch.setattr(ES, "_controlled_refusal_family", lambda result: None)
    stats = ES.error_action_stats(_workspace(tmp_path / "ws", [_real_refusal_record()]))

    assert stats.total == 0, "摘掉结构判据后还能数到 ⇒ 数的不是这一条判据"
    assert stats.sources["unclassified"]["tool"] == 1, (
        "不许静默丢掉：认不出的受控拒绝至少要进兜底那一格")


# ---------------------------------------------------------------- d 不重复计


def test_one_refusal_is_not_counted_twice(tmp_path: pathlib.Path) -> None:
    """d：`data.reason` 里已经带一个可扫的受控码时，这次拒绝只记一次（不是两笔）。

    用 `invalid_params`（码表里可扫的那一类）当"抢码"的证据：主码规则先认它，
    结构判据就不再叠一笔 —— 同一次拒绝在 `by_role` 里只 +1。
    """
    result = _real_refusal_record()["result"]
    result["data"] = dict(result["data"])
    result["data"]["reason"] = "invalid_params：这次调用不成立（这一条只想被数一次）"
    stats = ES.error_action_stats(_workspace(tmp_path / "ws", [_step("H", result)]))

    assert stats.total == 1, stats.by_role
    assert sum(stats.by_role["H"].values()) == 1, stats.by_role
    assert stats.count("H", "controlled_refusal") == 1
    assert stats.count("H", "tool_refused_controlled") == 0

# -*- coding: utf-8 -*-
"""状态报告强制：M 收工前盘上必须有一份 `out/review/STATUS-*`（`draft/38` §7 第三组判据）。

T1 第 18 趟（并表之后重跑）实测的失败形态：M 派了活、也收了工，却一次都没调
`conductor.status_report` —— 工具在它的面上（注册表 83 件含它）、提示词里也写着，
只是那句原先只说"用户问『现在什么情况』时用"；补一句"收工前也落一份"之后仍然没调
（收尾序列被 `conductor.closing` 占满，一句散文不足以让它多走一步）。

⇒ 与 `_emit_settlement`（"通报由框架保证、内容由模型给"）同族：框架保证"有"。
判据四半（正控 / 负控 / 三态 / 反真空），照 `tests/test_report_is_mandatory.py` 的同一套写法。
"""

from __future__ import annotations

import json
import pathlib
from typing import Any

from test_llm_work_reaches_the_ledger import _run

from agentflow import statusreport as SR
from agentflow.agent_loop import AgentLoop
from agentflow.store import Store


class _StubLoop:
    """借用 `_ensure_status_report` 需要的三个字段（同 `test_report_is_mandatory` 的写法）。"""

    def __init__(self, root: pathlib.Path, *, role: str, store: Any) -> None:
        self.role = role
        self.session_root = root
        self.store = store


class _Run:
    """只提供 `elapsed_sec` 的替身（`_ensure_status_report` 用它算这一趟的起点）。"""

    elapsed_sec = 0.0
    notes: list[str] = []


def _status_files(ws: pathlib.Path) -> list[pathlib.Path]:
    d = ws / "out" / "review"
    return sorted(p for p in d.glob("STATUS-*")) if d.is_dir() else []


def _empty_ws(tmp_path: pathlib.Path) -> pathlib.Path:
    ws = tmp_path / "empty-ws"
    (ws / "data").mkdir(parents=True, exist_ok=True)
    Store(ws).init()
    return ws


def test_a_run_without_the_tool_still_leaves_a_status_report(tmp_path: pathlib.Path):
    """正控：M 那一趟没调 `conductor.status_report` ⇒ 框架补落一份，读数点名是谁落的。"""
    ws, run = _run(tmp_path, [{"text": json.dumps(
        {"final": "这一趟做完了（我没调状态报告）", "evidence": []}, ensure_ascii=False)}],
        role="M")
    assert run.stop_reason == "final", run.to_dict()
    files = _status_files(ws)
    assert {p.suffix for p in files} == {".md", ".json"}, files
    md = next(p for p in files if p.suffix == ".md")
    assert md.read_text(encoding="utf-8").strip(), "补落的报告不许是空文件"
    notes = " ".join(run.notes)
    assert "状态报告" in notes and "framework" in notes, run.notes


def test_a_report_that_is_already_there_is_not_touched(tmp_path: pathlib.Path):
    """负控：盘上已经有本趟产生的报告（模型自己调的）⇒ 一个字都不动。"""
    ws = _empty_ws(tmp_path)
    _, md, js = SR.write_status_report(Store(ws), ws)          # 模拟"模型刚落的那一份"
    before = {p: p.read_bytes() for p in (md, js)}
    note = AgentLoop._ensure_status_report(_StubLoop(ws, role="M", store=Store(ws)), _Run())
    assert note == "", ("模型已经落过 ⇒ 框架不许再落一份", note)
    assert {p: p.read_bytes() for p in (md, js)} == before, "负控失败：框架改了模型那一份"
    assert len(_status_files(ws)) == 2, _status_files(ws)


def test_only_m_with_a_store_is_guarded(tmp_path: pathlib.Path):
    """三态：不是 M / 没有 store ⇒ 返回空串且不写任何东西（'不该我管'不是'补过了'）。"""
    ws = _empty_ws(tmp_path)
    assert AgentLoop._ensure_status_report(
        _StubLoop(ws, role="D", store=Store(ws)), _Run()) == ""
    assert AgentLoop._ensure_status_report(
        _StubLoop(ws, role="M", store=None), _Run()) == ""
    assert _status_files(ws) == [], "这两档都不该落盘"


def test_a_d_run_is_never_guarded(tmp_path: pathlib.Path):
    """反真空（整趟）：D 跑完一趟 ⇒ 盘上没有 `STATUS-*`（那是 M 的活，不该被顺带补）。"""
    ws, run = _run(tmp_path, [{"text": json.dumps(
        {"final": "D 这一趟做完了", "evidence": []}, ensure_ascii=False)}], role="D")
    assert run.stop_reason == "final", run.to_dict()
    assert _status_files(ws) == [], _status_files(ws)


def test_the_failure_to_write_is_reported_not_swallowed(tmp_path: pathlib.Path):
    """反真空：补落失败 ⇒ 返回一句失败读数（不许把'没写成'读成'报告已落盘'）。

    造法：把 `out` 做成一个文件（不是目录）⇒ `out/review/` 建不出来，
    `write_status_report` 当场 OSError。为什么不用"盘坏了"的 store：
    `statusreport._rows` 对读不成的表是吞掉给空的（它的口径就是那样），
    所以读那一侧炸不掉它 —— 要测失败路径就得让写失败。
    """
    ws = _empty_ws(tmp_path)
    (ws / "out").write_text("我是一个文件，不是目录", encoding="utf-8")
    note = AgentLoop._ensure_status_report(_StubLoop(ws, role="M", store=Store(ws)), _Run())
    assert "补落失败" in note, note
    assert _status_files(ws) == [], "失败之后不该留下半份报告"

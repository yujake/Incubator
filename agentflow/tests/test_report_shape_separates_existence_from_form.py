# -*- coding: utf-8 -*-
"""收工门 `report_shape`：存在性 = fail、形状 = 读数（业主 2026-11-14 拍板）。

## 改前是什么（这一份要钉住的那个缺陷）

这一格改前只有两种结局：`unknown`（没给路径 / 报告不在盘上 / 体例读不成）与 `pass`
（报告在、读得成）—— 没有 fail 分支。于是"调用方给了报告路径、盘上没有这份报告"
与"调用方没给路径"在读数上同形（真机 47 个不通过全是 `report_not_written` 这一档），
而 60 个 pass 里 30 个缺附件三件套却照样绿。

## 改后

| 现场 | 状态 |
|---|---|
| 给了 `report_path`，文件不在盘上 | `fail` + blocker `report_not_written`（交付物缺失） |
| 没给 `report_path` | `unknown` + warning（调用方没给，不是没交） |
| 文件在、缺附件三件套 / 体例没兑现 | `pass` + warning + 读数（业主 2026-10-09：「交付形式归 M」） |

## 判据（每条都能造红，也有反真空）

| # | 判据 | 造的是什么现场 |
|---|---|---|
| f | 给了路径而文件不在 ⇒ `fail` + blocker | 报告落点写错 / 忘了写 |
| g | 没给路径 ⇒ `unknown`（负控：不许变成 fail） | 调用方没给 |
| h | 缺附件三件套 ⇒ 仍 `pass` + warning（负控：不许变 fail） | 报告在、抽掉附件那一段 |
| i | 反真空：把 `_report_file_exists` 打桩成恒真 ⇒ f 必红 | 同 f，`monkeypatch.setattr` |

夹具与 `tests/test_closing_gate.py` 同一份（`_good` / `_write_report`）；所有工作区都在
`tmp_path` 下，不碰 `projects/`。
"""
from __future__ import annotations

import pathlib

import pytest

from agentflow import closing as CL

from test_closing_gate import _good, _write_report


def _gate(store, report: pathlib.Path | None, *, project_dir: pathlib.Path | None = None):
    return CL.check_closing(
        store,
        project_dir=str(project_dir if project_dir is not None else store.root),
        report_path=str(report) if report is not None else "")


def _cell(rep, name: str) -> dict:
    return {
        "status": rep.status.get(name),
        "blockers": [f.code for f in rep.blockers if f.check == name],
        "levels": {f.code: f.level for f in rep.findings if f.check == name},
    }


# ============================================================ f) 存在性 = fail

def test_a_given_report_path_without_a_file_is_a_failure_not_unknown(
        tmp_path: pathlib.Path) -> None:
    """f) 给了 `report_path` 而文件不在盘上 ⇒ `fail` + blocker（不是 `unknown`）。

    改前的读数是 `unknown` + warning `report_not_written`：那是一句"没查成"，
    而现场其实是"交付物没交"。
    """
    st, _report = _good(tmp_path)
    gone = tmp_path / "out" / "review" / "NOPE.md"
    assert not gone.exists()
    rep = _gate(st, gone)

    cell = _cell(rep, "report_shape")
    assert cell["status"] == "fail", rep.to_dict()
    assert cell["blockers"] == ["report_not_written"], cell
    assert cell["levels"]["report_not_written"] == "blocker", cell
    readings = rep.readings["report_shape"]
    assert readings["exists"] is False, readings
    assert readings["verdict"] == "missing", readings
    assert readings["path"].endswith("NOPE.md"), readings
    # 其余各格不被这一条带红（这一格只说自己那一件事）
    others = {k: v for k, v in rep.status.items() if k != "report_shape"}
    assert others == {name: "pass" for name in CL.DEFAULT_CHECKS if name != "report_shape"}, \
        others
    assert rep.machine_pass is False, "fail + blocker 不许被读成可以交"


# ============================================================ g) 没给路径 = unknown

def test_no_report_path_stays_unknown(tmp_path: pathlib.Path) -> None:
    """g) 负控：没给 `report_path` ⇒ 仍 `unknown`（那不是"没交"，是调用方没给）。"""
    st, _report = _good(tmp_path)
    rep = _gate(st, None)

    cell = _cell(rep, "report_shape")
    assert cell["status"] == "unknown", rep.to_dict()
    assert cell["status"] != "fail", "没给路径不是「没交」——不许把这一档读成 fail"
    assert cell["blockers"] == [], cell
    assert cell["levels"] == {"report_path_missing": "warning"}, cell
    assert "report_shape" not in (rep.readings or {}), rep.readings.get("report_shape")


# ============================================================ h) 缺附件 = pass

def test_missing_attachments_stay_a_reading_not_a_failure(tmp_path: pathlib.Path) -> None:
    """h) 负控：缺附件三件套 ⇒ 仍 `pass` + warning（守 2026-10-09「形式归 M」的裁定）."""
    st, _report = _good(tmp_path)
    bad = _write_report(tmp_path, drop_attachment=True)
    rep = _gate(st, bad)

    cell = _cell(rep, "report_shape")
    assert cell["status"] == "pass", rep.to_dict()
    assert cell["blockers"] == [], cell
    assert cell["levels"].get("attachment_fields_missing") == "warning", cell
    readings = rep.readings["report_shape"]
    assert readings["missing_attachment_fields"] == ["origin=own_result", "依据", "sha"], readings
    assert readings.get("verdict") != "missing", readings
    # 缺附件不许把 machine_pass 弄假（那是 2026-10-09 裁定要防的"形式变成门"）
    assert rep.machine_pass is True, rep.to_dict()


# ============================================================ i) 反真空

def test_stubbing_the_existence_criterion_turns_the_red_off(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """i) 反真空：把「报告文件在不在盘上」打桩成恒真 ⇒ f 那一条必红。

    两半一起读：不打桩 ⇒ `fail`；打桩成恒真之后同一份现场不再 fail（它落进
    `_run_check` 的兜底 `unknown`）。有人把 `_report_file_exists` 换成恒真，
    f 会当场变绿 —— 那正是这一条要报的"判据没有接线"。
    """
    st, _report = _good(tmp_path)
    gone = tmp_path / "out" / "review" / "NOPE.md"
    plain = _cell(_gate(st, gone), "report_shape")
    assert plain["status"] == "fail", plain

    monkeypatch.setattr(CL, "_report_file_exists", lambda _path: True)
    stubbed = _gate(st, gone)
    cell = _cell(stubbed, "report_shape")
    assert cell["status"] != "fail", (
        "把「文件在不在」打桩成恒真之后仍然 fail ⇒ f 红的不是这条判据", stubbed.to_dict())
    assert "check_crashed" in cell["levels"], cell

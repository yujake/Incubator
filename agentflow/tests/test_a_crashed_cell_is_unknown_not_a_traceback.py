# -*- coding: utf-8 -*-
"""判据：某一格自己炸掉 ⇒ 只有那一格 `unknown`，整份门不塌、也不把真 bug 藏起来。

## 这一份守什么（R-BE1 的 ⑥-1，2026-10-27）

`check_closing` 的 docstring 写着"不抛业务异常 —— 没查成落成 `unknown`"。改前那句是假的：
`store.rows` 抛的 StoreError（半截表 / 非 UTF-8 / schema 版本不符）从某一格里冒出来，
`agentflow closing` 打一份 Python traceback。现在每一格经 `closing._run_check`、
每一格读数经 `closing._run_reading`。

| 判据 | 它钉的是 | 改坏之后的样子 |
|---|---|---|
| ① 坏一张表 | 只有 `contradictions` 变 `unknown`，原因里逐字带 `StoreError`，其余格与好工作区逐格相同 | 整份门塌成 traceback（改前）或整屏 unknown（改坏的新形态） |
| ② 反真空 | 把一格打桩成"抛异常"⇒ 只有那一格 unknown；其余格必须仍是它们各自的好值 | 有人把 `_run_check` 改成"一格抛了就全格 unknown"⇒ 这条红 |
| ③ 读数炸掉 | 读数自己抛了 ⇒ `readings[key]` 是 `checked=False` + 原因，门照常出结论 | 读数一炸整份门又塌回去 |
| ④ CLI 退出码 | `agentflow closing` 在坏表上不再 traceback，退出码 2（= 没查成） | 退出码是 1 / 抛异常退出 |

② 的反真空是这一条最要紧的：`unknown` 既不是 `pass` 也不是 `fail`，所以"把一切收成 unknown"
会让门永远收不了工而任何一条既有判据都不一定红（它们多半断言 `fail` 或 `pass`）。
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys

import pytest

from agentflow import closing as CL
from agentflow.store import Store

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"


def _ws(tmp_path: pathlib.Path) -> pathlib.Path:
    """一个门跑得动的最小工作区（每张表都初始化过、都是 0 行）。"""
    ws = tmp_path / "ws"
    ws.mkdir(parents=True, exist_ok=True)
    Store(ws).init()
    return ws


def _status(ws: pathlib.Path) -> dict[str, str]:
    return dict(CL.check_closing(Store(ws), project_dir="", report_path="").status)


def _crash_detail(rep: CL.ClosingReport, check: str) -> str:
    return "；".join(f.detail for f in rep.findings if f.check == check)


# ---------------------------------------------------------------- ① 坏一张表


def test_a_broken_table_makes_exactly_one_cell_unknown(tmp_path: pathlib.Path):
    """坏掉 `statements` 表 ⇒ 读它的那三格 unknown（原因逐字带 StoreError），其余格照常。

    为什么"其余格照常"要断言：整份塌与"几格 unknown"在 CLI 上都只是一行字，
    只有逐格比较才区分得开 —— 而"整份塌"是这一条要修的那个形态。
    变的那三格正是读 `statements` 的那三格（`contradictions` / `load_bearing` /
    `substance`）；`user_pending` 这种与那张表无关的格必须逐字不变、且仍是 `pass`
    （不是"一片 unknown"）。
    """
    ws = _ws(tmp_path)
    before = _status(ws)
    path = ws / "data" / "statements.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["rows"] = "这不是数组"          # store.rows 会抛受控 StoreError（不是崩溃）
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")

    rep = CL.check_closing(Store(ws), project_dir="", report_path="")
    assert rep.status["contradictions"] == "unknown", rep.status
    assert "StoreError" in _crash_detail(rep, "contradictions"), rep.findings
    changed = {k for k in rep.status if rep.status[k] != before.get(k)}
    assert changed == {"contradictions", "load_bearing", "substance"}, (
        "只有读 statements 的那三格该变；其余格逐格相同", changed, rep.status, before)
    assert rep.status["user_pending"] == before["user_pending"] == "pass", rep.status
    # 那几格不许同时留下 blocker：unknown 不折成"被拦住"
    assert not [f for f in rep.blockers if f.check in changed], rep.blockers


# ---------------------------------------------------------------- ② 反真空


def test_a_cell_that_raises_does_not_turn_the_other_cells_unknown(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    """一格被打桩成抛异常 ⇒ 只有它 unknown；其余格仍是它们各自的好值（不是一片 unknown）。"""
    ws = _ws(tmp_path)
    before = _status(ws)

    def _boom(rep, store):  # noqa: ANN001 - 与 `_check_substance` 同形
        raise RuntimeError("这一格故意炸掉")

    monkeypatch.setattr(CL, "_check_substance", _boom)
    rep = CL.check_closing(Store(ws), project_dir="", report_path="")

    assert rep.status["substance"] == "unknown", rep.status
    assert "这一格故意炸掉" in _crash_detail(rep, "substance"), rep.findings
    others = {k: v for k, v in rep.status.items() if k != "substance"}
    assert others == {k: v for k, v in before.items() if k != "substance"}, (
        "一格炸掉只塌那一格；把一切收成 unknown 的实现在这里红", others, before)
    assert rep.machine_pass is False       # unknown 不是 pass


# ---------------------------------------------------------------- ③ 读数炸掉


def test_a_reading_that_raises_is_checked_false_with_a_reason(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    """读数自己抛了 ⇒ `readings[key].checked is False` + 原因；门照常出结论。"""
    ws = _ws(tmp_path)

    def _boom(root, *, sid=""):  # noqa: ANN001 - 与 `nontriviality_reading` 同形
        raise ValueError("非平凡性那一格故意炸掉")

    monkeypatch.setattr(CL, "nontriviality_reading", _boom)
    rep = CL.check_closing(Store(ws), project_dir="", report_path="")

    got = rep.readings["nontriviality"]
    assert got["checked"] is False, got
    assert "非平凡性那一格故意炸掉" in str(got.get("reason")), got
    assert "nontriviality" in {f.check for f in rep.findings}, rep.findings
    # 读数塌掉不许改门的形状：status 的键集与好工作区一样
    assert set(rep.status) == set(CL.DEFAULT_CHECKS), rep.status


# ---------------------------------------------------------------- ④ CLI 退出码


def test_the_cli_exits_two_instead_of_a_traceback(tmp_path: pathlib.Path):
    """`agentflow closing` 在坏表上打"没查成"并退 2（不是 traceback、不是 1）。"""
    ws = _ws(tmp_path)
    path = ws / "data" / "statements.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["rows"] = "这不是数组"
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")

    env = {"PYTHONPATH": str(SRC), "PYTHONIOENCODING": "utf-8",
           "SYSTEMROOT": str(pathlib.Path("C:/Windows")), "PATH": ""}
    proc = subprocess.run(
        # `--root` 是顶层参数，必须写在动词之前（argparse 的口径，CLI 自己的注释也这么写）。
        [sys.executable, "-m", "agentflow", "--root", str(ws), "closing"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=str(SRC.parent), env=env, timeout=180)
    out = (proc.stdout or "") + (proc.stderr or "")
    assert "Traceback" not in out, out[-2000:]
    assert proc.returncode == 2, (proc.returncode, out[-2000:])
    assert "contradictions" in out and "没查成" in out, out[-2000:]
    # 改前这里是"一行 `[store 错误] …`、一格读数都没有"：机器八格的那句汇总必须出现，
    # 说明门自己跑完了（`_print_review_acceptance` 之后仍可能落到 CLI 兜底，那不是门）。
    assert "机器八格" in out, out[-2000:]

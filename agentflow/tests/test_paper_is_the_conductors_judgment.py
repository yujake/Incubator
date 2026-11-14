# -*- coding: utf-8 -*-
"""判据：出不出 paper 由 M 判断，不是门（业主 2026-11-14）。

## 业主裁定（逐字）

> 「是否出 paper 退出收工判定，由 M 自行判断是否到这个时机。」

## 三条判据

| # | 查什么 | 期望 |
|---|---|---|
| a | 门的格表 | `"paper" not in closing.DEFAULT_CHECKS`，格数 7，模块 docstring 那张表与它逐条同序 |
| b | 读数还在、内容不变 | `readings["paper"]` 四档照旧（`consistent` / `drifted` / `unknown` / `not_applicable`）+ 一句 `gate` 说明；`status` 里没有它；PDF 过期只留 warning、不产生 blocker |
| c | 反真空 | 把 `paper` 塞回 `DEFAULT_CHECKS`（并显式传进 `checks=`）⇒ `status` 多出那一格、`paper_pdf_is_stale` 重新成为 blocker —— 证明 a/b 不是恒绿 |

`_check_paper` 本体保留并且不变：显式 `checks=("paper",)` 的调用方（论文那一路的
负控、D-38 的夹具）仍然得到那一格、判据强度一个字没软。判据 d 在
`tests/test_closing_gate.py::test_the_paper_reading_goes_red_alone_but_does_not_gate`。
"""
from __future__ import annotations

import pathlib
import re

import paperfixture as FX
from agentflow import closing as CL
from agentflow import papercompile as PC
from agentflow.store import Store

#: 模块 docstring 那张表的行形（第一列是反引号包住的格名）。
_ROW = re.compile(r"^\|\s*`([a-z_]+)`\s*\|", re.M)


def _ws(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _paper_ws(tmp_path: pathlib.Path, *, drift: bool = False) -> tuple[Store, pathlib.Path]:
    """一个有正文、且（未）过期论文包的现场：`drift=True` 时改正文不重编。"""
    st = _ws(tmp_path)
    root = pathlib.Path(st.root)
    pkg = root / "out" / "paper"
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "main.tex").write_text("\\documentclass{article}\nbody\n", encoding="utf-8")
    with FX.use_engine(FX.fake_engine(root / "_engine")):
        PC.compile_paper(root)
    if drift:
        (pkg / "main.tex").write_text(
            "\\documentclass{article}\nbody（改过）\n", encoding="utf-8")
    return st, root


def _gate(st: Store, root: pathlib.Path, *, checks=None):
    kw = {"checks": checks} if checks is not None else {}
    return CL.check_closing(st, project_dir=str(root), report_path="", **kw)


# ------------------------------------------------------------------ a 格表
def test_a_paper_is_not_one_of_the_gate_cells() -> None:
    """a：`paper` 不在 `DEFAULT_CHECKS` 里；docstring 那张表与它逐条同序（七格）。"""
    documented = _ROW.findall(CL.__doc__ or "")
    assert documented == list(CL.DEFAULT_CHECKS), (
        f"说明书与实现分家了：docstring 表里是 {documented}，"
        f"`DEFAULT_CHECKS` 是 {list(CL.DEFAULT_CHECKS)}")
    assert "paper" not in CL.DEFAULT_CHECKS, CL.DEFAULT_CHECKS
    assert len(CL.DEFAULT_CHECKS) == 7, CL.DEFAULT_CHECKS


# ------------------------------------------------------------------ b 读数照旧
def test_b_the_paper_reading_is_still_computed_and_is_not_a_gate(
        tmp_path: pathlib.Path) -> None:
    """b：读数四档照旧 + 一句 `gate`；不进 `status`、不产生 blocker。"""
    st, root = _paper_ws(tmp_path)
    rep = _gate(st, root)
    assert "paper" not in rep.status, rep.to_dict()
    reading = rep.readings["paper"]
    assert reading["verdict"] == "consistent", reading
    assert pathlib.Path(str(reading["root"])) == root, reading
    assert pathlib.Path(str(reading["tex"])) == root / "out" / "paper" / "main.tex", reading
    assert pathlib.Path(str(reading["pdf"])) == root / "out" / "paper" / "main.pdf", reading
    assert reading["gate"] == CL.PAPER_READING_NOTE, reading
    assert [f for f in rep.findings if f.check == "paper"] == [], rep.to_dict()

    # 改正文不重编 ⇒ 读数转 `drifted`，但也只是一条 warning：不许再拦门。
    (root / "out" / "paper" / "main.tex").write_text(
        "\\documentclass{article}\nbody（再改一次）\n", encoding="utf-8")
    rep2 = _gate(st, root)
    assert "paper" not in rep2.status, rep2.to_dict()
    assert rep2.readings["paper"]["verdict"] == "drifted", rep2.readings["paper"]
    paper_findings = [f for f in rep2.findings if f.check == "paper"]
    assert [f.code for f in paper_findings] == ["paper_pdf_is_stale"], paper_findings
    assert paper_findings[0].level == "warning", paper_findings[0]
    assert [f for f in rep2.blockers if f.check == "paper"] == [], rep2.to_dict()

    # 没有正文 ⇒ `not_applicable`（不是"没查成"）
    (root / "out" / "paper" / "main.tex").unlink()
    rep3 = _gate(st, root)
    assert rep3.readings["paper"]["verdict"] == "not_applicable", rep3.readings["paper"]


# ------------------------------------------------------------------ c 反真空
def test_c_putting_paper_back_into_the_table_turns_the_gate_red(
        tmp_path: pathlib.Path, monkeypatch) -> None:
    """c：把 `paper` 塞回 `DEFAULT_CHECKS` ⇒ 那一格重新进 `status` 并拦门。"""
    st, root = _paper_ws(tmp_path, drift=True)
    monkeypatch.setattr(CL, "DEFAULT_CHECKS", CL.DEFAULT_CHECKS + ("paper",))
    assert "paper" in CL.DEFAULT_CHECKS, "反真空夹具没真的塞回去"
    rep = CL.check_closing(st, project_dir=str(root), report_path="",
                           checks=CL.DEFAULT_CHECKS)
    assert rep.status.get("paper") == "fail", rep.to_dict()
    codes = [f.code for f in rep.blockers]
    assert "paper_pdf_is_stale" in codes, codes

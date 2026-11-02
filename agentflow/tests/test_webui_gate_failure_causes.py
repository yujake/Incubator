# -*- coding: utf-8 -*-
"""`machine_pass=false` 的两条来源：格失败 vs blocker（84 ④，2026-11-02）。

## 84 的现场

`/api/package` 的 `closing.gates`：`counts = {pass:6, fail:1, na:1, unknown:0}`、
`machine_pass=false`、**`blockers` 一格没有**（读出来是 `null` / 不存在）。
读的人只看到"门没过"，看不出是"有一格 fail"还是"本该有 blocker 却没产出"。

`closing.ClosingReport.machine_pass` 的定义是"八格全 pass **且** 没有 blocker"：
`na`（不适用）也不等于 pass，所以 84 的 `machine_pass=false` 里同时有 `acceptance=fail`
与 `load_bearing=na` 两份格读数；blocker 那一半是空的。两者都能让 machine_pass 变假，
所以页面必须分开点名，不许只给一个 false。

## 这一份钉什么

| 判据 | 造什么 | 要看到什么 |
|---|---|---|
| a | 只有一格 `fail` | `machine_pass_cause="cells"`、`blocking_cells` 点名那一格、`blockers=[]` |
| b | 八格全 pass + 一条 blocker | `machine_pass_cause="blockers"`、`blockers` 带清单、`blocking_cells=[]` |
| c | 一格 fail + 一条 blocker | `machine_pass_cause="blockers+cells"`、两栏都非空 |
| d | 八格全 pass、无 blocker | `machine_pass_cause="pass"`、两栏都空 |
| e | 只有一格 `na` | 也算"格没全 pass"（`machine_pass` 的定义就是全 pass） |
| f | machine_pass=false 的每一档 | **两栏不许同时空着**（空着就是缺陷读数） |
| g | 页面源码 | 读 `gates.blocking_cells` / `gates.blockers` / `gates.machine_pass_cause`，并且有「因格失败」与 blocker 清单 |

`machine_pass_cause` 是受控词：`pass` / `cells` / `blockers` / `blockers+cells` /
`unknown`（最后一档只在"两条都空而 machine_pass 假"这种逻辑上到不了的形态出现，
页面把它显成缺陷读数而不是空白）。
"""
from __future__ import annotations

import pathlib
import re

from agentflow import closing as CL
from agentflow.store import Store
from agentflow.webui import readers as RD

REPO = pathlib.Path(__file__).resolve().parents[1]
ACCEPTANCE_TSX = REPO / "ui" / "src" / "pages" / "Acceptance.tsx"


# ====================================================================== 夹具
def _gates(tmp_path: pathlib.Path, *, status: dict[str, str] | None = None,
           findings: list[CL.Finding] | None = None) -> dict:
    """跑 `_closing_block`，只取 `gates` 那一块（其余几块与本判据无关）。"""
    root = tmp_path / "ws"
    root.mkdir(parents=True)
    store = Store(root)
    store.init()
    rep = CL.ClosingReport(
        status={name: "pass" for name in CL.DEFAULT_CHECKS},
        findings=list(findings or []),
        readings={}, m_verdict=None)
    rep.status.update(status or {})
    out = RD._closing_block(rep, {}, {"tri": "computed", "criteria": {}, "details": {}},
                            {}, {"receipt": {}}, root, store)
    return out["gates"]


def _blocker(check: str = "statements_unsigned") -> CL.Finding:
    return CL.Finding(check, "statements_unsigned_without_v_or_abandon", "blocker",
                      "夹具：一条命题既没有 V 签、也没有被明确放弃")


# ====================================================================== a 只有格
def test_a_only_a_failed_cell_says_cells(tmp_path: pathlib.Path) -> None:
    """只有一格 fail、没有任何 blocker ⇒ 页面要说「因格失败」，并点名那一格。"""
    gates = _gates(tmp_path, status={"acceptance": "fail"})
    assert gates["machine_pass"] is False, gates
    assert gates["machine_pass_cause"] == "cells", gates
    assert [c["name"] for c in gates["blocking_cells"]] == ["acceptance"], gates
    assert gates["blocking_cells"][0]["status"] == "fail", gates
    assert gates["blockers"] == [], gates


# ====================================================================== b 只有 blocker
def test_b_only_a_blocker_says_blockers_and_lists_it(tmp_path: pathlib.Path) -> None:
    """八格全 pass、只有一条 blocker ⇒ 必须给出 blocker 清单（不是一句空 false）。"""
    gates = _gates(tmp_path, findings=[_blocker()])
    assert gates["machine_pass"] is False, gates
    assert gates["machine_pass_cause"] == "blockers", gates
    assert gates["blocking_cells"] == [], gates
    assert len(gates["blockers"]) == 1, gates
    one = gates["blockers"][0]
    assert one["check"] == "statements_unsigned", one
    assert one["code"] == "statements_unsigned_without_v_or_abandon", one
    assert one["level"] == "blocker" and one["detail"], one


# ====================================================================== c 两半都有
def test_c_both_halves_are_named(tmp_path: pathlib.Path) -> None:
    """一格 fail + 一条 blocker ⇒ 两半都要出现（不许只报一半）。"""
    gates = _gates(tmp_path, status={"acceptance": "fail"}, findings=[_blocker()])
    assert gates["machine_pass_cause"] == "blockers+cells", gates
    assert [c["name"] for c in gates["blocking_cells"]] == ["acceptance"], gates
    assert len(gates["blockers"]) == 1, gates


# ====================================================================== d 通过
def test_d_a_passing_gate_says_pass(tmp_path: pathlib.Path) -> None:
    """八格全 pass 且没有 blocker ⇒ `pass`，两栏都空（空是"没有"，不是"没记录"）。"""
    gates = _gates(tmp_path)
    assert gates["machine_pass"] is True, gates
    assert gates["machine_pass_cause"] == "pass", gates
    assert gates["blockers"] == [] and gates["blocking_cells"] == [], gates


# ====================================================================== e na
def test_e_na_is_not_pass_either(tmp_path: pathlib.Path) -> None:
    """84 的 `load_bearing=na`：`na` 也不等于 pass，所以它同样让 machine_pass 变假。"""
    gates = _gates(tmp_path, status={"load_bearing": "na"})
    assert gates["machine_pass"] is False, gates
    assert gates["machine_pass_cause"] == "cells", gates
    assert [(c["name"], c["status"]) for c in gates["blocking_cells"]] == [
        ("load_bearing", "na")], gates


# ====================================================================== f 反真空
def test_f_a_false_machine_pass_never_has_two_empty_columns(tmp_path: pathlib.Path) -> None:
    """反真空：machine_pass=false 的每一档，两栏至少一栏非空（否则就是缺陷读数）。"""
    for i, (status, findings) in enumerate((
            ({"acceptance": "fail"}, []),
            ({}, [_blocker()]),
            ({"acceptance": "fail"}, [_blocker()]),
            ({"load_bearing": "na"}, []),
            ({"report_shape": "unknown"}, []))):
        gates = _gates(tmp_path / f"case-{i}", status=status, findings=findings)
        assert gates["machine_pass"] is False, gates
        assert gates["machine_pass_cause"] != "pass", gates
        assert gates["blockers"] or gates["blocking_cells"], (
            "machine_pass=false 而 blocker 与格两栏都空着 ⇒ 页面会显示一个空原因", gates)


# ====================================================================== g 页面
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_LINE_COMMENT = re.compile(r"^[ \t]*//.*$", re.M)


def _code_only(text: str) -> str:
    return _LINE_COMMENT.sub("", _BLOCK_COMMENT.sub("", text))


def _page_problems(source: str) -> list[str]:
    """页面必须把两条来源都读出来、都画出来（纯函数，可负控）。"""
    code = _code_only(source)
    problems: list[str] = []
    for token in ("gates.blocking_cells", "gates.blockers", "gates.machine_pass_cause"):
        if token not in code:
            problems.append(f"页面没有读 {token}")
    for word in ("因格失败", "blocker"):
        if word not in code:
            problems.append(f"页面没有把「{word}」说给读的人")
    return problems


def test_g_the_page_shows_which_half_turned_machine_pass_false() -> None:
    """页面那一半：格失败与 blocker 清单都在，负控能抓住"只剩一个 false"。"""
    source = ACCEPTANCE_TSX.read_text(encoding="utf-8")
    assert _page_problems(source) == [], _page_problems(source)

    # 负控：不读 blocker 清单 ⇒ 必须报（"有 blocker"那一档就退回一个空的 false）。
    doctored = source.replace("gates.blockers", "gates.not_a_field")
    assert doctored != source, "负控没改到源码"
    assert any("gates.blockers" in p for p in _page_problems(doctored)), _page_problems(doctored)
    # 负控：把「因格失败」这句删掉 ⇒ 必须报（页面又只剩一个 false）。
    dropped = source.replace("因格失败", "没过", 1)
    assert any("因格失败" in p for p in _page_problems(dropped)), _page_problems(dropped)


def test_h_the_type_declaration_carries_the_two_columns() -> None:
    """类型来源（`_TS_TYPES` → types.ts）必须带上两栏与原因词，否则页面读不到。"""
    decl = RD.type_decls()
    assert "export interface GateBlocker {" in decl, decl
    for field in ("blockers: GateBlocker[]", "blocking_cells: GateCell[]",
                  "machine_pass_cause: string"):
        assert field in decl, f"`types.ts` 的 GateTable 里没有 {field}"


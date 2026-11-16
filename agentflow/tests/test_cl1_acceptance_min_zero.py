# -*- coding: utf-8 -*-
"""验收表的 `min: 0` 是合法阈值，"未声明"只由缺键或 `null` 表达。

## 现场（AH2b，`projects/lp-ball-2`）

M 在 `ACCEPTANCE-CHECKS.json` 里给两行写了 `"min": 0`，意思是"这一档不要求条数"。
旧读法 `declared_min = int(row.get("min") or 0)` 把 0 折成"没声明"，再落回缺省阈值 1
（`closing.py:3170` 改前那句 `declared_min or (0 if implicit_max else 1)`）⇒ A11 / A14
两条明明写着 0 的行被判成 `0 < 1`。把"0 是合法阈值"和"没声明"折成同一个值，是这一档
唯一的缺陷。

## 这一组钉什么

| # | 判据 |
|---|---|
| a | `min: 0` 且实测 0 ⇒ 这一行达标（`want_min == 0`） |
| b | 缺 `min` 键 ⇒ 未声明（沿用原行为：缺省 1） |
| c | `min: null` ⇒ 未声明（同上） |
| d | 反真空：把 `_declared_min` 打桩成"0 也算未声明" ⇒ a 必红 |

`_declared_min(row)` 是唯一的分水岭（返回 `None` = 未声明、整数 = 声明值）；
反真空只打这一处桩。
"""
from __future__ import annotations

import json
import pathlib

from agentflow import closing as CL
from agentflow.store import Store


def _ws(tmp_path: pathlib.Path) -> tuple[Store, pathlib.Path]:
    root = tmp_path / "ws"
    st = Store(root)
    st.init(force=True)
    return st, root


def _table(root: pathlib.Path, row: dict) -> pathlib.Path:
    p = root / "out" / "paper" / "ACCEPTANCE-CHECKS.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"checks": [row]}, ensure_ascii=False),
                 encoding="utf-8", newline="\n")
    return p


def _report(st: Store, root: pathlib.Path) -> CL.ClosingReport:
    return CL.check_closing(st, project_dir=str(root), checks=("acceptance",))


def _only_row(rep: CL.ClosingReport) -> dict:
    rows = rep.readings["acceptance"]["rows"]
    assert len(rows) == 1, rows
    return rows[0]


def test_a_min_zero_is_a_real_threshold_and_zero_meets_it(tmp_path: pathlib.Path):
    """a：`min: 0` + 实测 0 ⇒ `want_min=0`、这一行达标、整格 pass。

    改前为什么红：0 被读成"未声明" ⇒ `want_min=1` ⇒ `0 < 1` ⇒ fail。
    """
    st, root = _ws(tmp_path)
    _table(root, {"id": "P1", "name": "稿件", "kind": "document_rows", "min": 0})
    rep = _report(st, root)
    row = _only_row(rep)
    assert row["got"] == 0, row
    assert row["min"] == 0, row
    assert row["ok"] is True, row
    assert row["detail"]["min_overridden"] == {"declared": 0, "kind_min": None,
                                               "effective": 0}, row["detail"]
    assert rep.status["acceptance"] == "pass", rep.to_dict()


def test_b_a_missing_min_key_is_undeclared_and_still_defaults_to_one(
        tmp_path: pathlib.Path):
    """b：缺 `min` 键 ⇒ 未声明（沿用原行为：缺省 1）⇒ 0 条不达标。"""
    st, root = _ws(tmp_path)
    _table(root, {"id": "P2", "name": "稿件", "kind": "document_rows"})
    row = _only_row(_report(st, root))
    assert row["got"] == 0, row
    assert row["min"] == 1, row
    assert row["ok"] is False, row
    assert row["detail"]["min_overridden"] == {"declared": None, "kind_min": None,
                                               "effective": 1}, row["detail"]


def test_c_a_null_min_is_undeclared_and_still_defaults_to_one(tmp_path: pathlib.Path):
    """c：`min: null` ⇒ 未声明（与缺键同一条路）。"""
    st, root = _ws(tmp_path)
    _table(root, {"id": "P3", "name": "稿件", "kind": "document_rows", "min": None})
    row = _only_row(_report(st, root))
    assert row["min"] == 1, row
    assert row["ok"] is False, row
    assert row["detail"]["min_overridden"]["declared"] is None, row["detail"]


def test_d_stubbing_zero_back_to_undeclared_turns_a_red(tmp_path: pathlib.Path,
                                                        monkeypatch):
    """d：反真空 —— 把 0 读回"未声明" ⇒ a 那一条必须重新变红。

    两段：先证真读数是达标（`min=0`），再打桩 `_declared_min`（只把 0 折回 `None`）、
    证同一条表重新变红。没有第二段，"a 恒绿"这一种坏法测不出来。
    """
    st, root = _ws(tmp_path)
    _table(root, {"id": "P1", "name": "稿件", "kind": "document_rows", "min": 0})
    assert _only_row(_report(st, root))["ok"] is True

    real = CL._declared_min

    def _zero_is_undeclared(row):  # noqa: ANN001 —— 打桩：把改前那句语义放回来
        value = real(row)
        return None if value == 0 else value

    monkeypatch.setattr(CL, "_declared_min", _zero_is_undeclared)
    row = _only_row(_report(st, root))
    assert row["min"] == 1, row
    assert row["ok"] is False, row
    assert row["detail"]["min_overridden"]["declared"] is None, row["detail"]

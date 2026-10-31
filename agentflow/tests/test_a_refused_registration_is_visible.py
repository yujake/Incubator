# -*- coding: utf-8 -*-
"""判据（先红 · 未修）：名册写口拒过的号必须有一个读数面（2026-11-03，153-U-09 的 registration 半）。

## 背景

业主 2026-11-02 的裁定让"被拒"落成一条盘上流水（`out/roster/refusals/<父>.jsonl`），
但那个流水只有一个读者：`Secretary.roster_repair`（收口兜底读它，免得把被拒的号
补成新名字）。全仓 `refusals_path` / `roster_refusal_note` / `_refused_task_ids` 的命中
只有 `secretary.py` 自己；`webui/*.py` 与 `ui/src/` 对 `refus` 的命中全是别的意思
（"被拒的续跑" / "写设置的 refused"）⇒ "这一号曾被拒过"在读数面上不可见。

## 这一笔做什么（2026-11-03 的裁决 5 的 `registration_refusals` 那一半）

给一个只读读数：`secretary.registration_refusals(root, owner=...)`，
并在两处读数面上透出来 —— `conductor.state`（主控的判断面）与项目状态报告
（`statusreport`）。名字用 `registration_refusals`（与 `action_refusals` /
`final_refusals` 那两义分开；词面拆分见 153-U-09）。

## 这条判据钉住什么

1. 拒一次 ⇒ `registration_refusals` 的 `count == 1`，`items` 里点得到那个号，
   且带 `refusal_code` / `requested_name` / `at`；
2. 三态：流水读不出来（坏行）⇒ `checked is False` 且 `bad` 非空 —— 不许折成"没人被拒"；
3. 没拒过 ⇒ `checked is True`、`count == 0`（反真空：不许把"没查成"与"没人被拒"折平）；
4. `conductor.state` 的返回里有这一格（主控判断面看得到）。
"""
from __future__ import annotations

import pathlib

from agentflow import secretary as SEC
from agentflow.store import Store


def _ws(tmp_path: pathlib.Path):
    root = tmp_path / "ws"
    root.mkdir()
    st = Store(root)
    st.init()
    return root, SEC.Secretary("M", root=root, store=st)


def test_a_refused_registration_leaves_a_readable_reading(tmp_path: pathlib.Path) -> None:
    """① 拒一次 ⇒ 读数里点得到那个号（今天红：`registration_refusals` 还不存在）。"""
    root, sec = _ws(tmp_path)
    ok, why = sec.roster_refusal_note(owner="t-000001", task_id="t-000009",
                                      name="D1", refusal_code="name_taken",
                                      problem="这个名字已经被占了")
    assert ok, why
    got = SEC.registration_refusals(root, owner="t-000001")
    assert got.get("checked") is True, got
    assert got.get("count") == 1, got
    items = got.get("items") or []
    assert [str(x.get("task_id") or "") for x in items] == ["t-000009"], items
    assert str(items[0].get("refusal_code") or "") == "name_taken", items[0]
    assert str(items[0].get("requested_name") or "") == "D1", items[0]
    assert str(items[0].get("at") or ""), items[0]


def test_no_refusal_is_a_checked_zero(tmp_path: pathlib.Path) -> None:
    """② 反真空：没拒过 ⇒ `checked=True` 且 `count == 0`（不是"没查成"）。"""
    root, _sec = _ws(tmp_path)
    got = SEC.registration_refusals(root, owner="t-000001")
    assert got.get("checked") is True, got
    assert got.get("count") == 0, got


def test_a_broken_log_is_unchecked_not_empty(tmp_path: pathlib.Path) -> None:
    """③ 三态：流水里有一行读不出来 ⇒ `checked is False`，不许折成"没人被拒"。"""
    root, sec = _ws(tmp_path)
    sec.roster_refusal_note(owner="t-000001", task_id="t-000010",
                            refusal_code="not_in_roster", problem="不在名册里")
    path = SEC.refusals_path(root, "t-000001")
    with path.open("a", encoding="utf-8") as fh:
        fh.write("{这一行不是 JSON\n")
    got = SEC.registration_refusals(root, owner="t-000001")
    assert got.get("checked") is False, got
    assert got.get("bad"), got


def test_the_state_view_carries_it(tmp_path: pathlib.Path) -> None:
    """④ `conductor.state` 的返回里有这一格（主控判断面看得到）。"""
    import ast

    src = (pathlib.Path(__file__).resolve().parents[1]
           / "src" / "agentflow" / "tools" / "conductor_tools.py").read_text(encoding="utf-8")
    assert "registration_refusals" in src, (
        "`conductor.state` 没有把 `registration_refusals` 摆到主控的判断面上")
    # 反真空：它必须真的在 `conductor_state` 的返回字典里（不是只出现在别的函数/注释里）
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "conductor_state":
            keys = {k.value for sub in ast.walk(node) if isinstance(sub, ast.Dict)
                    for k in sub.keys
                    if isinstance(k, ast.Constant) and isinstance(k.value, str)}
            assert "registration_refusals" in keys, sorted(keys)
            return
    raise AssertionError("找不到 `conductor_state`（判据对象没了）")

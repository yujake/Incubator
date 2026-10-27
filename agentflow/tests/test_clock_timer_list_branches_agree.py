# -*- coding: utf-8 -*-
"""判据：`clock.timer_list` 的四条返回分支共用同一套顶层键。

## 它修的是什么

`tools/clock_tools.py::clock_timer_list` 里曾有三处 `ok({...})`，键集合各不相同：正常那一支
18 个；`C.timers` 读不出那一支 13 个（少 `periodics` / `periodic_count` / `waiters` /
`waiters_parked` / `observed_events`）；`C.waiters` 或 `C.periodics` 读不出那一支 12 个
（再少 `pending_count` / `fired_count` / `cancelled_count`）。而 `returns=` 逐字写的是正常
那 18 个。后果不是"读数难看"，是调用方读 `data["periodics"]` 时，只要这一趟恰好读不出
计时器，拿到的就是 KeyError，而不是"这一格读不出来"。

修法与 `attack.create_plan`（2026-10-27 统一四条分支）同一条：四支统一键集合，
缺数据的那几格给空值，不删声明。

## 判据分两半，缺一半都不算数

1. 四条分支（正常 / 读不出 timers / 读不出 waiters / 读不出 periodics）的顶层键集合逐字
   相等，且等于 `returns=` 声明的那一套 —— 四支互相相等只是必要条件：四支都少同一格时
   它们依然相等，所以还要与声明对上（负控里第三条专门打这一档）；
2. 缺数据的那几格给的是空值（`[]` / `0` / `None`）而不是缺键，并由 `checked` 说清
   "这一趟没读成"。空值不等于"查过了、什么都没有"：那个结论归 `checked`。

四条分支的夹具各打坏一格：把 `C.timers` / `C.waiters` / `C.periodics` 换成判据侧的
`_unreadable`（抛的是真身那个 `ClockStateError`，不是随便一个异常）。工作区里先起一条
计时器与一条巡查 —— 否则"读不出一格"与"本来就没有"在读数是同一个形状，判据会退化成
自证。

## 反真空

正控断言"正常那一支真的读成了、而且读到了那两条"；两条负控分别往判据的输入里注入
"三支各删一个键"与"四支都删同一个键"，同一个 `_problems` 必须报出来。两条都打在
`_problems` 的输入上（与 `tests/test_reading_map.py` 的行数负控同形），所以不需要写盘。
"""

from __future__ import annotations

import pathlib

import pytest

from agentflow import clock as C
from agentflow.tools import clock_tools as CT
from test_tools_audit_fixes import parse_declared_keys

#: 四条分支的名字与它们各自打坏的那一格（空串 = 什么都不打坏）。
BRANCHES: tuple[tuple[str, str], ...] = (
    ("正常", ""),
    ("读不出 timers", "timers"),
    ("读不出 waiters", "waiters"),
    ("读不出 periodics", "periodics"),
)

#: 每一支读不出之后必须是空值的那几格（空值是 `[]` / `0` / `None`，不是缺键）。
EMPTY_ON_UNREAD: dict[str, dict[str, object]] = {
    "读不出 timers": {"timers": [], "count": 0, "pending_count": 0,
                      "fired_count": 0, "cancelled_count": 0},
    "读不出 waiters": {"waiters": [], "waiters_parked": None},
    "读不出 periodics": {"periodics": [], "periodic_count": 0},
}


def _unreadable(_workspace: object) -> object:
    """夹具：把某一格读成"读不出来"（抛的是真身那个 `ClockStateError`）。"""
    raise C.ClockStateError("夹具造的：这一格读不出来")


def _seed(workspace: pathlib.Path) -> None:
    """工作区里真起一条计时器 + 一条巡查（否则"读不出"与"没有"读数同形）。"""
    C.start_timer(workspace, after_sec=3600.0, reason="判据：一条待发的计时器")
    C.start_periodic(workspace, every_sec=3600.0, purpose="判据：一条周期性巡查")


def _data(workspace: pathlib.Path, monkeypatch: pytest.MonkeyPatch, broken: str = "") -> dict:
    """按某一条分支读一次 `clock.timer_list`，返回它的顶层数据。"""
    with monkeypatch.context() as m:
        if broken:
            m.setattr(C, broken, _unreadable)
        got = CT.clock_timer_list(None, workspace)
    assert got.ok is True, got.error
    assert isinstance(got.data, dict), got.data
    return got.data


def _branch_data(workspace: pathlib.Path,
                 monkeypatch: pytest.MonkeyPatch) -> dict[str, dict]:
    """四条分支各读一次（顺序就是 `BRANCHES` 的顺序，第一项是正常那一支）。"""
    return {name: _data(workspace, monkeypatch, broken) for name, broken in BRANCHES}


def _declared_keys() -> set[str]:
    """`clock.timer_list` 的 `returns=` 那一套键（三态入口，不接受"抽不到"）。"""
    spec = getattr(CT.clock_timer_list, "__tool_spec__", None)
    assert spec is not None, "`clock.timer_list` 上没有 `__tool_spec__`（装饰器的形态变了）"
    keys, state = parse_declared_keys(spec.returns)
    assert state == "parsed", f"`clock.timer_list` 的 `returns=` 不是键列表写法：{state}"
    return keys


def _problems(branches: dict[str, dict]) -> list[str]:
    """四条分支对不齐的地方（正控与两条负控走同一个函数）。"""
    bad: list[str] = []
    names = list(branches)
    canonical = frozenset(branches[names[0]])
    for name in names[1:]:
        keys = frozenset(branches[name])
        missing = sorted(canonical - keys)
        extra = sorted(keys - canonical)
        if missing or extra:
            bad.append(f"{name} 与「{names[0]}」不一致：缺 {missing}，多 {extra}")
    declared = _declared_keys()
    if canonical != declared:
        bad.append(
            "四支共有的那一套与 `returns=` 不一致："
            f"声明里有而实跑没有 {sorted(declared - canonical)}，"
            f"实跑有而声明没有 {sorted(canonical - declared)}")
    return bad


# ------------------------------------------------------------------ 判据本体


def test_the_four_branches_share_one_key_set(tmp_path: pathlib.Path,
                                             monkeypatch: pytest.MonkeyPatch) -> None:
    """正控：四条分支的顶层键集合逐字相等，且等于 `returns=` 声明的那一套。"""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    _seed(workspace)
    branches = _branch_data(workspace, monkeypatch)
    assert set(branches) == {name for name, _ in BRANCHES}, sorted(branches)

    bad = _problems(branches)
    assert not bad, (
        "同一个 handler 的四条分支给了不同的键集合（调用方读某几个键时会 KeyError）：\n"
        + "\n".join(bad))

    # 反真空：正常那一支必须真的读成了，而且读到了刚才起的那两条 ——
    # 四支"都一样"也可能只是"四支都空"，那与本判据要问的不是一回事。
    normal = branches["正常"]
    assert normal["checked"] is True, normal
    assert normal["count"] == 1 and normal["periodic_count"] == 1, {
        k: normal[k] for k in ("count", "periodic_count")}


def test_the_unreadable_branches_give_empty_values_not_missing_keys(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """缺数据的那几格是空值（不是缺键），并由 `checked` 说清这一趟没读成。"""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    _seed(workspace)
    branches = _branch_data(workspace, monkeypatch)

    for name, expected in EMPTY_ON_UNREAD.items():
        data = branches[name]
        for key, want in expected.items():
            assert key in data, f"{name} 缺键 `{key}` —— 缺键会让调用方 KeyError"
            assert data[key] == want, (
                f"{name} 的 `{key}` 是 {data[key]!r}，这里要的是空值 {want!r}"
                "（0 或空清单是'查过了、什么都没有'的读数，不能拿来顶替'没读成'）")
        assert data["checked"] is False, (
            f"{name} 的 `checked` 是 {data['checked']!r} —— 没读成必须说成没读成")

    # 一格读不出不等于全丢：其余几格照常给真读数（这正是把三次读各自关起来的意义）。
    # 比的是编号而不是整行：每行带 `remaining_sec` / `waited_sec` 这种现算读数，
    # 两次读之间墙钟在走，整行逐字相同是做不到的（那也不是本判据要问的东西）。
    def ids(data: dict, key: str) -> list[str]:
        rows = data[key]
        field = "periodic_id" if key == "periodics" else "timer_id"
        return [str(row.get(field) or "") for row in rows]

    assert ids(branches["读不出 periodics"], "timers") == ids(branches["正常"], "timers"), \
        "读不出巡查的时候，计时器那一格也跟着空了 —— 三处读没有各自关起来"
    assert ids(branches["读不出 waiters"], "timers") == ids(branches["正常"], "timers"), \
        "读不出挂机等待者的时候，计时器那一格也跟着空了"
    assert ids(branches["读不出 timers"], "periodics") == ids(branches["正常"], "periodics"), \
        "读不出计时器的时候，巡查那一格也跟着空了"


# ------------------------------------------------------------------ 反真空


def test_deleting_a_key_from_three_branches_turns_the_criterion_red(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """负控 1：从三条"读不出"的分支里各删一个键 ⇒ 同一个 `_problems` 必须报出来。"""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    _seed(workspace)
    branches = _branch_data(workspace, monkeypatch)
    assert not _problems(branches), "负控没落脚点：四支本来就对不齐"

    victim = "periodics"
    assert all(victim in data for data in branches.values()), \
        f"`{victim}` 不是四支共有的键 —— 负控打不进去"
    doctored = {
        name: ({k: v for k, v in data.items() if k != victim} if name != "正常" else dict(data))
        for name, data in branches.items()
    }
    bad = _problems(doctored)
    assert bad, "从三支里各删掉一个键之后判据仍然全绿 —— 这条判据是橡皮图章"
    assert len(bad) >= 3, f"三条被删的分支应各报一处，实际只报了：{bad}"


def test_deleting_a_key_from_all_four_branches_is_caught_by_the_declaration(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """负控 2：四支都删同一个键 ⇒ 四支仍然互相相等，只有与 `returns=` 对账才咬得住。"""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    _seed(workspace)
    branches = _branch_data(workspace, monkeypatch)
    assert not _problems(branches), "负控没落脚点：四支本来就对不齐"

    victim = "periodics"
    doctored = {name: {k: v for k, v in data.items() if k != victim}
                for name, data in branches.items()}
    sets = {frozenset(data) for data in doctored.values()}
    assert len(sets) == 1, "负控造错了：四支并没有被删成同一套键"
    assert _problems(doctored), (
        "四支都删掉同一格之后判据仍然全绿 —— 只比四支互相相等的判据看不见这一档，"
        "与 `returns=` 对账那一半必须咬住")


if __name__ == "__main__":  # pragma: no cover - 手工复跑用
    raise SystemExit(pytest.main([__file__]))

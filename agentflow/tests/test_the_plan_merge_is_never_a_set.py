# -*- coding: utf-8 -*-
"""`agent_f.core._merged_plan_round` 的直接判据（K4 的唯一合并点）。

## 为什么补这个文件

2026-11-20 11:10 的提交 `2ab3bbdb`（"lint 清零"）用当天那个一次性的 `_fixdup.py` 的
regex 逐行替换清 R009 的强调标记：只要一行里有成对星号、且不含
`**kwargs` / `**opts` 一类白名单词，就把中间那段当强调抹掉。它抹中的不是注释，
而是代码表达式 —— `agent_f/core.py` 里那条
`merged: dict[str, Any] = {**dict(fresh), **dict(mine)}` 被抹成集合字面量
`{dict(fresh), dict(mine)}`：两个 dict 不可哈希 ⇒ 每次写回都
`TypeError: unhashable type: 'dict'` ⇒ 真机 `lp-ball-13` 的 F 侧 15/15 次
`attack.step` 被拒、0.18 美元零可签产出。而 `_merged_plan_round` 当时在 `tests/`
里 0 命中，所以 22 条计划判据全绿也没碰到它。

## 这个文件钉什么

a. 三份 dict 合并后键齐全、`rounds = fresh.rounds + max(0, mine - base)`；
b. `history` 的两条分支（在 `base` 上追加 / 整行重写）；
c. 反真空：把真实源码里那一行用事故当天的同一个正则重放成集合字面量，
   同一套入参喂过去必须抛 `TypeError` —— 证明上面几条判据真的能打死事故版本；
d. 空输入 / 缺省值不抛，非 Mapping 顶层入参当场报错（行为明说，不静默）。

## 一条纪律

本文件的判据一律经 `FC._merged_plan_round` 取函数（不是 `from ... import`），
这样取证目录里的打桩插件把事故版本打桩进模块属性后，
同一个文件能跑出红 —— 判据的"牙"要能被当场量到，而不是只写在报告里。
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from types import MappingProxyType
from typing import Any

import pytest

from agentflow.agent_f import core as FC

#: 被钉的那份源码。反真空判据要读它，而不是抄一份"事故版本"的副本。
CORE_PY = Path(__file__).resolve().parents[1] / "src" / "agentflow" / "agent_f" / "core.py"

#: 事故当天那个一次性脚本用的正则（逐字）。
INCIDENT_REGEX = r"\*\*([^*\n]+?)\*\*"


# ============================================================ 造行


def _row(*, rounds: int, history: list[dict], subgoals: list[dict],
         status: str = "active", best_partial: str = "partial",
         updated_at: str = "2026-01-01T00:00:00+00:00") -> dict[str, Any]:
    """一份最小可合并的计划行（字段名与 `attack_plans` 的行一致）。"""
    return {
        "plan_id": "000001",
        "rounds": rounds,
        "history": history,
        "subgoals": subgoals,
        "status": status,
        "best_partial": best_partial,
        "updated_at": updated_at,
    }


def _source_function() -> ast.FunctionDef:
    """从真实源码里取出 `_merged_plan_round` 的函数节点。

    取不到就当场失败：那说明被钉的那个函数换了名字或搬了位置，
    这条反真空判据需要人来复核，而不是继续对着一个抄本判绿。
    """
    tree = ast.parse(CORE_PY.read_text(encoding="utf-8"))
    fn = next((n for n in tree.body
               if isinstance(n, ast.FunctionDef) and n.name == "_merged_plan_round"), None)
    assert fn is not None, f"{CORE_PY} 里找不到 `_merged_plan_round`"
    return fn


def _merge_stmt(fn: ast.FunctionDef) -> ast.AnnAssign:
    """取那行合并语句（`merged: dict[...] = {...}`）。"""
    for stmt in fn.body:
        if (isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name)
                and stmt.target.id == "merged" and isinstance(stmt.value, ast.Dict)):
            return stmt
    raise AssertionError("`_merged_plan_round` 里找不到 `merged: dict[...] = {...}` 那一行")


def _the_set_literal_version() -> Any:
    """把事故当天的正则重放到真实源码那一行上，编译成"事故版本"的函数。

    为什么从源码重放而不是手抄 `{dict(fresh), dict(mine)}`：手抄的副本会漂移 ——
    源码改了，判据还对着旧副本绿。重放跟着真实那一行走；它若不再是展开的形态，
    下面的 ast 比对会当场红，提示同步更新判据。
    """
    fn = _source_function()
    stmt = _merge_stmt(fn)
    original = ast.unparse(stmt.value)
    broken_src = re.sub(INCIDENT_REGEX, r"\1", original)
    broken = ast.parse(broken_src, mode="eval").body
    assert ast.dump(broken) != ast.dump(stmt.value), (
        "把那行用事故当天的正则重放之后结构没有变化：它现在不是 "
        "`{**dict(fresh), **dict(mine)}` 这种展开了 —— "
        "若是有意改写法，请同步更新这条反真空判据"
    )
    stmt.value = broken
    # 函数的注解是 `Mapping[str, Any]`：带上 future import，免得注解在 def 期被求值
    # （那会先抛 NameError/TypeError，盖住真正要看的 `unhashable type: 'dict'`）。
    module = ast.parse("from __future__ import annotations\n")
    module.body.append(fn)
    ast.fix_missing_locations(module)
    ns: dict[str, Any] = {}
    exec(compile(module, "<the-broken-merge>", "exec"), ns)  # noqa: S102
    return ns["_merged_plan_round"]


# ============================================================ a) rounds 与键


def test_rounds_adds_only_my_delta_to_the_fresh_row() -> None:
    """`rounds` 是「事务里重读到的计数 + 我这一轮的增量」，不是我这一轮的绝对值。

    现场形状：我开工时 `base` 是 3 轮，我推完 `mine` 是 4 轮（我加了 1 轮）；
    事务里重读到 `fresh` 是 5 轮（这期间别的实例又推了 2 轮）。
    正确写回是 6 轮 —— 写 4 是「把我的绝对值盖上去」（丢别人两轮），
    写 5 是「丢掉我这一轮」。
    """
    fresh = _row(rounds=5, history=[{"round": 3}, {"round": 4}],
                 subgoals=[{"sid": "a", "status": "closed"}])
    base = _row(rounds=3, history=[{"round": 3}],
                subgoals=[{"sid": "a", "status": "todo"}])
    mine = _row(rounds=4, history=[{"round": 3}, {"round": 4}],
                subgoals=[{"sid": "a", "status": "closed"}])

    got = FC._merged_plan_round(fresh, base, mine)

    assert got["rounds"] == 6, f"期望 fresh(5) + delta(1) = 6，实得 {got['rounds']}"


def test_rounds_never_goes_backwards_when_i_add_no_round() -> None:
    """我没有推进轮数（delta 为 0 甚至为负）⇒ 只保留 fresh 的计数，不许倒扣。

    整行重写的老调用点可能把 `mine` 写成比 `base` 还小的轮数；`max(0, delta)`
    这一格保证「别人的轮数」不会被一次重写抹掉。
    """
    fresh = _row(rounds=7, history=[], subgoals=[{"sid": "a", "status": "todo"}])
    base = _row(rounds=4, history=[], subgoals=[{"sid": "a", "status": "todo"}])
    same = _row(rounds=4, history=[], subgoals=[{"sid": "a", "status": "todo"}])
    less = _row(rounds=2, history=[], subgoals=[{"sid": "a", "status": "todo"}])

    assert FC._merged_plan_round(fresh, base, same)["rounds"] == 7
    assert FC._merged_plan_round(fresh, base, less)["rounds"] == 7


def test_merged_keys_are_the_union_of_fresh_and_mine() -> None:
    """合并后键齐全：`fresh` 有而 `mine` 没有的键留着，`mine` 有而 `fresh` 没有的键也进来。

    计划级单格（`status` / `best_partial` / `updated_at`）取我这一轮算出来的值：
    它们回答「这条计划现在怎么样」，不是「哪一轮发生了什么」。
    """
    fresh = _row(rounds=2, history=[], subgoals=[], status="active",
                 best_partial="old", updated_at="T-old")
    fresh["owner"] = "F"  # 只在 fresh 里的键
    base = _row(rounds=1, history=[], subgoals=[])
    mine = _row(rounds=2, history=[], subgoals=[], status="stalled",
                best_partial="mine", updated_at="T-mine")
    mine["budget"] = {"max_rounds": 6}  # 只在 mine 里的键

    got = FC._merged_plan_round(fresh, base, mine)

    assert set(got) == set(fresh) | set(mine)
    assert got["owner"] == "F"
    assert got["budget"] == {"max_rounds": 6}
    assert got["status"] == "stalled"
    assert got["best_partial"] == "mine"
    assert got["updated_at"] == "T-mine"


# ============================================================ b) history 两条分支


def test_history_appends_only_my_new_tail() -> None:
    """「在 `base` 上追加」的形态：只追加我新落的那几行，重读那一行已有的行一行不动。

    整行 upsert 丢的正是别人这一截。这里让 `fresh` 里先有别人的第 4 轮，
    我的尾巴是第 3 轮 —— 正确结果是「别人的 4 + 我的 3」都在，且顺序是
    「fresh 原有在前、我的尾巴在后」。
    """
    base_h = [{"round": 1}, {"round": 2}]
    mine_h = base_h + [{"round": 3, "note": "mine"}]
    fresh_h = base_h + [{"round": 4, "note": "other"}]
    fresh = _row(rounds=4, history=list(fresh_h), subgoals=[])
    base = _row(rounds=2, history=list(base_h), subgoals=[])
    mine = _row(rounds=3, history=list(mine_h), subgoals=[])

    got = FC._merged_plan_round(fresh, base, mine)

    assert got["history"] == fresh_h + [{"round": 3, "note": "mine"}], got["history"]
    assert got["history"][:2] == base_h
    assert got["history"][2] == {"round": 4, "note": "other"}


def test_a_whole_row_rewrite_keeps_my_history() -> None:
    """不是「在 `base` 上追加」的形态（老调用点整行重写）⇒ 按我这份写，不并 fresh。

    判据是 `mine` 的 history 前缀是否等于 `base`：对不上就说明我这份是重写的，
    此时把 fresh 的行并进来会让同一轮出现两行、且用户看到的次序是错的。
    """
    base_h = [{"round": 1}]
    mine_h = [{"round": 9, "note": "rewrite"}]
    fresh_h = [{"round": 1}, {"round": 2}]
    fresh = _row(rounds=2, history=list(fresh_h), subgoals=[])
    base = _row(rounds=1, history=list(base_h), subgoals=[])
    mine = _row(rounds=9, history=list(mine_h), subgoals=[])

    got = FC._merged_plan_round(fresh, base, mine)

    assert got["history"] == mine_h, got["history"]


def test_a_missing_history_reads_as_an_empty_list() -> None:
    """`history` 缺失（或 None）时两条分支都要能走：不许把 None 迭代成异常。"""
    fresh = _row(rounds=1, history=[], subgoals=[])
    base = _row(rounds=1, history=[], subgoals=[])
    mine = _row(rounds=1, history=[], subgoals=[])
    fresh.pop("history")
    base.pop("history")
    mine.pop("history")
    got = FC._merged_plan_round(fresh, base, mine)
    assert got["history"] == []


# ============================================================ b') subgoals 按 sid 合并


def test_subgoals_merge_by_sid() -> None:
    """我没动过的子目标用重读到的（别人推进的那一版），我改过的用我的，我新增的追加。

    这条与 (a)(b) 是同一件事的另外两格：K4 合并点只有这一个函数，
    它错则 `rounds` / `history` / `subgoals` 三格一起错。
    """
    fresh = _row(rounds=3, history=[], subgoals=[
        {"sid": "a", "status": "in_progress"},
        {"sid": "b", "status": "closed"},
        {"sid": "z", "status": "todo"},
    ])
    base = _row(rounds=2, history=[], subgoals=[
        {"sid": "a", "status": "todo"},
        {"sid": "b", "status": "todo"},
        {"sid": "z", "status": "todo"},
    ])
    mine = _row(rounds=3, history=[], subgoals=[
        {"sid": "a", "status": "closed"},
        {"sid": "b", "status": "todo"},
        {"sid": "c", "status": "todo"},
    ])

    got = FC._merged_plan_round(fresh, base, mine)

    by_sid = {str(s["sid"]): s for s in got["subgoals"]}
    assert by_sid["a"]["status"] == "closed", "我改过的那条要用我的"
    assert by_sid["b"]["status"] == "closed", "我没动过的那条要用重读到的"
    assert by_sid["z"]["status"] == "todo", "我没动过、fresh 里有的那条要留着"
    assert by_sid["c"]["status"] == "todo", "我新增的要追加进来"
    assert [s["sid"] for s in got["subgoals"]] == ["a", "b", "z", "c"], "次序：fresh 在前，新增在后"


# ============================================================ c) 反真空


def test_the_criteria_would_kill_the_set_literal_version() -> None:
    """反真空：同一套入参喂给事故版本必须抛 `TypeError`，喂给真身必须不抛。

    这一条是上面那些判据的"牙"：如果哪天有人把它们改成只传空 dict / 只断言不抛，
    这一条仍然证明事故版本会被同一套入参打死。它读的是真实源码那一行，
    所以"源码又被抹成集合字面量"时，这条（连同上头全部）一起红。
    """
    fresh = _row(rounds=5, history=[{"round": 3}], subgoals=[])
    base = _row(rounds=3, history=[{"round": 3}], subgoals=[])
    mine = _row(rounds=4, history=[{"round": 3}, {"round": 4}], subgoals=[])

    broken = _the_set_literal_version()
    with pytest.raises(TypeError, match="unhashable"):
        broken(fresh, base, mine)

    # 同一套入参，真身必须不抛并给出正确读数 —— 两侧不能都是抛。
    assert FC._merged_plan_round(fresh, base, mine)["rounds"] == 6


# ============================================================ d) 空输入与非 Mapping


def test_empty_inputs_are_an_empty_round_not_a_crash() -> None:
    """三份空 dict ⇒ 一份空合并结果（0 轮 / 空 history / 空 subgoals），不抛。"""
    got = FC._merged_plan_round({}, {}, {})
    assert got == {"history": [], "rounds": 0, "subgoals": []}


def test_missing_values_read_as_zero_and_empty_lists() -> None:
    """三格给 None（而不是缺键）时按空值读，不抛；`rounds` 是数字字符串时能转。"""
    got = FC._merged_plan_round(
        {"history": None, "rounds": None, "subgoals": None}, {}, {"rounds": "2"})
    assert got["rounds"] == 2
    assert got["history"] == []
    assert got["subgoals"] == []


def test_a_mapping_proxy_is_accepted_as_declared() -> None:
    """注解声明的是 `Mapping`，不是 `dict`：只读映射也要能用（不许偷偷要求可变 dict）。"""
    fresh = MappingProxyType(_row(rounds=1, history=[], subgoals=[]))
    got = FC._merged_plan_round(fresh, {}, MappingProxyType({"rounds": 1}))
    # fresh 1 轮 + 我的增量 1 轮（base 是空的 ⇒ delta = 1 - 0）
    assert got["rounds"] == 2
    assert got["history"] == [] and got["subgoals"] == []


def test_a_non_mapping_row_is_refused_loudly() -> None:
    """非 Mapping 顶层入参不是静默当空表：当场报错，且错误类型明确。

    钉的是「调用点写错了要被看见」：`None` 走 `dict(None)` 的 TypeError，
    `list` 走 `.get` 的 AttributeError。将来若加了统一的 TypeError 前置闸，
    这一条会红 —— 那是提示来更新判据（把两条并成一条），不是放宽。
    """
    with pytest.raises(TypeError):
        FC._merged_plan_round(None, {}, {})  # type: ignore[arg-type]
    with pytest.raises(AttributeError):
        FC._merged_plan_round([("rounds", 1)], {}, {})  # type: ignore[arg-type]

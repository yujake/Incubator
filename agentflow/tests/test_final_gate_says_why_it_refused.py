# -*- coding: utf-8 -*-
"""判据：final 闸读不成时必须挡住，而且拒信要说出真原因（2026-11-03，153-U-04）。

## 背景

`_final_gate_reading` 里同一颗 `checked=False` 分成两支：

| 支 | 来源 | 改前结论 | 改前 `why` |
|---|---|---|---|
| A | 没有 conductor / 台账号（`agent_loop.py:6817-6823`） | 放行（`complete` 保持 True） | `""` |
| C | `retire_integrity` 抛异常（`:6833-6838`） | 放行 | `""` |
| B | `retire_integrity` 自己报 `checked=False`（`:6849-6852`） | 挡 | `""` |

`why` 是空串 ⇒ 调用方（`:7787`）的兜底串顶上：`"还有节点没销号 ⇒ 不记 final"` ——
台账读不成的那一刻，拒信写的是假原因。补救窗口用尽时（`:7820-7827`）还会再判一次
"在册从 N 减到 M"（这一档 `count` 恒 0）⇒ 落到第二句假原因
"在册节点已清空，卡在已销号节点名下的未消项"。

## 业主的裁定（2026-11-03 第 ③ 条）

- `checked=False` **一律挡**（fail-closed），与"A 的读不全 ⇒ 不叫醒"同一口径；
- `why` 必须写**真原因**，不许再出现"还有节点没销号"这种假原因；
- 并给一句"这种情形下怎么继续"的指路。

## 这条判据钉住什么

1. 四条读不成的路径（没 conductor / 没 `retire_integrity` / 它抛异常 / 它自己报
   `checked=False`）**一律** `applicable=True` 且 `complete=False`；
2. 四句 `why` 各不相同、都非空、都说出真原因（点名哪一格没查成；抛异常那一条带异常名），
   且都不含"还有节点没销号"；
3. 四句 `why` 都带指路（`conductor.state`）；
4. 反真空：干净的那一档照旧放行且 `why` 为空 —— 否则"一律挡"会退化成"永远挡"；
5. 兜底串在源码里消失，补救用尽那句在"没查成"时不许说"已清空"。
"""
from __future__ import annotations

import pathlib
from typing import Any

from agentflow import agent_loop as AL
from agentflow import schema as S

AGENT_LOOP = pathlib.Path(AL.__file__)


class _Run:
    def __init__(self) -> None:
        self.notes: list[str] = []


class _Cond:
    """只实现 `retire_integrity` 的假 conductor（与本仓探针同一套做法）。"""

    def __init__(self, result: Any = None, *, raises: str = "") -> None:
        self._result = result
        self._raises = raises

    def retire_integrity(self, root: str) -> dict[str, Any]:
        if self._raises:
            raise RuntimeError(self._raises)
        return dict(self._result or {})


class _NoIntegrity:
    """连 `retire_integrity` 都没有的 conductor（`getattr` 那一支）。"""


class _Shell:
    """把 `AgentLoop._final_gate_reading` 挂到一个只有三格属性的壳上。"""

    role = S.CONDUCTOR_ROLE
    my_task_id = "t-000001"
    max_final_refused = 3

    def __init__(self, cond: Any) -> None:
        self.conductor = cond

    def reading(self, run: _Run | None = None) -> dict[str, Any]:
        return AL.AgentLoop._final_gate_reading(self, run)


def _refused(reading: dict[str, Any]) -> bool:
    """抄调用方 `agent_loop.py:7786` 那一个判据。"""
    return bool(reading.get("applicable")) and not bool(reading.get("complete"))


#: (名字, conductor, 拒信里必须出现的真原因片段)
_BROKEN: tuple[tuple[str, Any, str], ...] = (
    ("no_conductor", None, "没有台账"),
    ("no_retire_integrity", _NoIntegrity(), "没有 retire_integrity"),
    ("raises", _Cond(raises="台账文件读不成（判据构造）"), "RuntimeError"),
    ("retire_says_unchecked", _Cond({"checked": False, "complete": False,
                                     "root": "t-000001", "count": 0, "total": 0,
                                     "nodes": [], "dirty": [],
                                     "reason": "tasks 台账读不成（判据构造）⇒ 本次没查成"}),
     "tasks 台账读不成"),
)


def _broken_readings() -> list[tuple[str, dict[str, Any], str]]:
    out: list[tuple[str, dict[str, Any], str]] = []
    for name, cond, token in _BROKEN:
        out.append((name, _Shell(cond).reading(_Run()), token))
    return out


def test_every_unreadable_path_blocks_the_final() -> None:
    """① 四条读不成的路径一律挡（改前：没 conductor 与抛异常那两支放行）。"""
    opened = []
    for name, reading, _token in _broken_readings():
        if not _refused(reading):
            opened.append(f"{name}: checked={reading.get('checked')!r} "
                          f"complete={reading.get('complete')!r}")
    assert not opened, (
        "这几条读不成的路径在改前会放行（`complete` 保持 True）—— 业主 2026-11-03 的裁定是"
        "一律挡（fail-closed）：\n  - " + "\n  - ".join(opened))


def test_each_refusal_says_the_real_reason() -> None:
    """② 四句 `why` 各不相同、都非空、都点名真原因、都不含假原因。"""
    whys: dict[str, str] = {}
    problems: list[str] = []
    for name, reading, token in _broken_readings():
        why = str(reading.get("why") or "")
        whys[name] = why
        if not why.strip():
            problems.append(f"{name}: why 是空的（调用方会拿兜底串顶上）")
            continue
        if "还有节点没销号" in why:
            problems.append(f"{name}: why 说的是假原因（还有节点没销号）：{why[:80]}")
            continue
        if token not in why:
            problems.append(f"{name}: why 没有点名真原因（缺 {token!r}）：{why[:120]}")
    assert not problems, "\n  - ".join(["拒信没说真话："] + problems)
    dup = [(a, b) for a in whys for b in whys if a < b and whys[a] == whys[b]]
    assert not dup, f"这几条路径的 why 一模一样（读者分不出是哪一格没查成）：{dup}"


def test_each_refusal_says_how_to_continue() -> None:
    """③ 四句 `why` 都带指路（业主："给一句这种情形下怎么继续"）。"""
    missing = [name for name, reading, _token in _broken_readings()
               if "conductor.state" not in str(reading.get("why") or "")]
    assert not missing, (
        f"这几条拒信没有指路（`conductor.state` 一句都没有）：{missing}")


def test_the_clean_case_still_passes() -> None:
    """④ 反真空：干净的那一档照旧放行，且不落噪声（`why` 为空）。"""
    run = _Run()
    reading = _Shell(_Cond({"checked": True, "complete": True, "count": 0, "total": 0,
                            "nodes": [], "dirty": [], "root": "t-000001",
                            "reason": ""})).reading(run)
    assert not _refused(reading), reading
    assert str(reading.get("why") or "") == "", reading.get("why")


def test_the_fallback_string_that_lied_is_gone() -> None:
    """⑤ 调用方那句兜底串必须消失（它是假原因的唯一来源）。"""
    text = AGENT_LOOP.read_text(encoding="utf-8")
    assert "还有节点没销号 ⇒ 不记 final" not in text, (
        "`agent_loop.py` 里还留着那句兜底串：`why` 一旦为空，它就会把"
        "'台账读不成'说成'还有节点没销号'")


def test_the_exhausted_note_does_not_claim_a_clean_ledger_when_it_never_read() -> None:
    """⑥ 补救用尽那句：`checked=False` 时不许说"在册节点已清空"。"""
    first = {"checked": False, "count": 0, "total": 0}
    last = {"checked": False, "count": 0, "total": 0, "reason": "台账读不成"}
    seen = AL.final_refusal_beats_text(first, last)
    assert "已清空" not in seen, f"没查成的那一档说成了'已清空'：{seen}"
    assert "没查成" in seen or "读不成" in seen, f"这一档没有说'没查成'：{seen}"

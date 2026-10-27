# -*- coding: utf-8 -*-
"""判据：`stats all` 四条读数共用一次扫描，而读数一个字节都不许变（R-BE1 的 ⑥-5）。

## 这一份守什么

`agentflow stats all` 把 errors / flow / cost / gates 四条读数依次跑一遍。改前每条各读一遍盘
（实测 `events.jsonl` 读 4 次、`sessions/*.jsonl` 读 4 次；同一份 2.9 MB 的会话被解析四遍，
约 2.5 s 里一大半是重复读）。现在 `cmd_stats` 先 `readouts.scan()` 一次，再把那份扫描
交给四条。

| 判据 | 它钉的是 | 改坏之后的样子 |
|---|---|---|
| ① 读数不变 | 共用扫描的四份输出 + `merge_readouts` 与"各自单跑"逐字节相同（sha256 相等） | 共享扫描顺手改了某条读数的输入（例如把 `sources` 复制丢了）⇒ 数字悄悄变了 |
| ② 只读一遍 | 共用那一轮里 `_read_events` / `_read_sessions` 各只被调 1 次 | 谁又在自己那里读了一遍（省了但没全省），或 `scan` 被调了两次 |
| ③ errors 也走这份扫描 | `errorstats.error_action_stats_from` 在（不在时下面那条会说怎么补） | 那一支被删/被覆盖 ⇒ `errors` 又自己读一遍 |

② 为什么要数到函数级：`scan()` 自己只调那两个读口一次，如果 `errors` 那一支退回"自己读"，
计数就变成 2 —— 而输出仍然完全相同，靠对拍是抓不到的。
"""
from __future__ import annotations

import hashlib
import json

import pytest

from agentflow import cli as CLI
from agentflow import errorstats as ES
from agentflow import readouts as R
from test_readouts_are_the_single_shape import _fixture_workspace

KINDS: tuple[str, ...] = ("errors", "flow", "cost", "gates")


class _Args:
    project_dir = ""
    report = ""


def _sha(obj) -> str:
    return hashlib.sha256(json.dumps(obj, ensure_ascii=False, sort_keys=True,
                                     default=str).encode()).hexdigest()


def _count_reads(monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
    calls = {"events": 0, "sessions": 0}
    real = {"events": ES._read_events, "sessions": ES._read_sessions}

    def events(*a, **k):
        calls["events"] += 1
        return real["events"](*a, **k)

    def sessions(*a, **k):
        calls["sessions"] += 1
        return real["sessions"](*a, **k)

    monkeypatch.setattr(ES, "_read_events", events)
    monkeypatch.setattr(ES, "_read_sessions", sessions)
    return calls


# ---------------------------------------------------------------- ① 读数不变


def test_the_four_readouts_are_byte_identical_with_a_shared_scan(
        tmp_path) -> None:
    """共用一份扫描 / 各自单跑，四条读数与合计逐字节相同。"""
    ws = _fixture_workspace(tmp_path / "ws")
    solo = {kind: R.READOUTS[kind](ws) for kind in KINDS}

    scanned = R.scan(ws, tables=("usage_ledger",))
    shared = {kind: CLI._stats_readout(kind, ws, _Args(), scanned=scanned)
              for kind in KINDS}

    for kind in KINDS:
        assert _sha(solo[kind]) == _sha(shared[kind]), (
            f"{kind} 的读数在共用扫描之后变了（只许少读盘，不许改读数）",
            solo[kind], shared[kind])
    assert _sha(R.merge_readouts(solo)) == _sha(R.merge_readouts(shared)), (
        "合计三态/原因变了")
    # 反真空：四条都得真有读数，否则上面的相等是空转
    assert all(shared[kind]["checked"] for kind in KINDS), shared


# ---------------------------------------------------------------- ② 只读一遍


def test_the_shared_round_reads_each_source_once(
        tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """共用那一轮：事件流与会话记录各只读 1 次（改前 4 次）。"""
    ws = _fixture_workspace(tmp_path / "ws")
    calls = _count_reads(monkeypatch)
    scanned = R.scan(ws, tables=("usage_ledger",))
    for kind in KINDS:
        CLI._stats_readout(kind, ws, _Args(), scanned=scanned)
    assert calls == {"events": 1, "sessions": 1}, (
        "共用扫描之后仍有读数自己读盘 ⇒ 检查 readouts.errors_readout 的 "
        "`errorstats.error_action_stats_from` 那一支还在不在（见 ③）", calls)


# ---------------------------------------------------------------- ③ errors 那一支


def test_errors_can_count_from_already_read_records(
        tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`errorstats.error_action_stats_from` 与 `error_action_stats` 给同一份计数。

    这一条同时是"那一支还在不在"的判据：它被删掉时（例如别的 lane 大改 `errorstats.py`
    时覆盖掉）这里会以 AttributeError 红，提示把"读盘"与"从已读记录算"分开的那三行补回来。
    """
    assert hasattr(ES, "error_action_stats_from"), (
        "`errorstats.error_action_stats_from` 不见了：`readouts` 的共用扫描靠它才不用再读一遍盘。"
        "补法：把 `error_action_stats` 里 `_read_events`/`_read_sessions` 之后的那段搬进 "
        "`error_action_stats_from(events, ev_reading, records, ss_reading)`，原函数改成"
        "读盘 + 转发（R-BE1 的 ⑥-5）")
    ws = _fixture_workspace(tmp_path / "ws")
    # 读盘那一遍
    read_stats = ES.error_action_stats(ws)
    # 从已读记录算的那一遍（用 errorstats 自己的读口把记录读出来，只读一次）
    root, store = ES._resolve_target(ws)
    events, ev = ES._read_events(root, store)
    records, ss = ES._read_sessions(root)
    from_records = ES.error_action_stats_from(events, ev, records, ss)
    assert read_stats.as_dict() == from_records.as_dict(), (
        "两条路给出的计数不同 ⇒ 口径分家了", read_stats.as_dict(), from_records.as_dict())
    # 调用方传进来的扫描读数不许被写坏（`unclassified` 那一格是唯一会被累加的地方）
    assert "unclassified" not in ev or int(ev.get("unclassified") or 0) == int(
        from_records.sources["events"].get("unclassified") or 0)

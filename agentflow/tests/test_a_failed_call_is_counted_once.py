# -*- coding: utf-8 -*-
"""判据：同一次失败只许数一次（`llm_call` 与它的 `agent_step` 是同一件事）。

## 真机（2026-10-28 17:15，`projects/paper-rewrite-78c`）

B 那两秒里网关断了两下（`IncompleteRead(0 bytes read)`）。每次失败落两条记录：

```
17:15:08  llm_call   problem="judge_no_reply:unknown"   detail="…IncompleteRead(0 bytes read)…"
17:15:08  agent_step shape="invalid"  result.problem="judge_no_reply:unknown"
17:15:09  llm_call   …
17:15:09  agent_step …
```

`error_action_stats_from` 两处都数 ⇒ 页面上 `judge_no_reply = 4`，而真实失败是 2 次。
"错误动作"那张表是拿来判"哪一类毛病在涨"的，×2 的读数会让它失真（B 看起来比实际坏一倍）。

## 这一组守什么

1. 一次失败（`llm_call` + 同 ts 同角色的 `agent_step`，同一个类目）⇒ 只记 1；
2. 反真空：两次失败（不同的 ts）⇒ 记 2（别把不同的失败也合并）；
3. 只有 `agent_step`、没有 `llm_call`（`judge_bad_json` 就是这一形）⇒ 照旧记 1；
4. 去重只走"同 ts + 同角色 + 同类目"这一格；行读数（`by_role`）与总计一起对上。
"""
from __future__ import annotations

import json
import pathlib

from agentflow import errorstats as ES


def _ws(tmp_path: pathlib.Path) -> pathlib.Path:
    ws = tmp_path / "ws"
    (ws / "data").mkdir(parents=True)
    (ws / "sessions").mkdir(parents=True)
    (ws / "data" / "events.jsonl").write_text("", encoding="utf-8")
    return ws


def _sessions(ws: pathlib.Path, records: list[dict]) -> None:
    path = ws / "sessions" / "s1.jsonl"
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n",
                    encoding="utf-8")


def _pair(ts: str, role: str = "B", index: int = 13) -> list[dict]:
    """一次失败的两条记录（真机形态：先 llm_call、再 agent_step）。"""
    return [
        {"kind": "llm_call", "role": role, "ts": ts, "task_id": "t-000001",
         "problem": "judge_no_reply:unknown",
         "detail": "网关内部抛出了 IncompleteRead：IncompleteRead(0 bytes read)"},
        {"kind": "agent_step", "role": role, "ts": ts, "index": index, "shape": "invalid",
         "payload": {}, "result": {"problem": "judge_no_reply:unknown", "detail": ""}},
    ]


def test_one_failure_is_counted_once_not_twice(tmp_path: pathlib.Path):
    """正题：一次网关中断 ⇒ `judge_no_reply` 计 1（改前计 2）。"""
    ws = _ws(tmp_path)
    _sessions(ws, _pair("2026-10-28T17:15:08+08:00"))
    got = ES.error_action_stats(ws)
    assert got.by_role.get("B", {}).get("judge_no_reply") == 1, got.by_role
    assert got.total == 1, got.as_dict()


def test_two_failures_are_still_two(tmp_path: pathlib.Path):
    """反真空：不同 ts 的两次失败 ⇒ 计 2（别把不同的失败也合并掉）。"""
    ws = _ws(tmp_path)
    _sessions(ws, _pair("2026-10-28T17:15:08+08:00", index=13)
              + _pair("2026-10-28T17:15:09+08:00", index=20))
    got = ES.error_action_stats(ws)
    assert got.by_role.get("B", {}).get("judge_no_reply") == 2, got.by_role
    assert got.total == 2, got.as_dict()


def test_an_invalid_step_without_an_llm_call_still_counts(tmp_path: pathlib.Path):
    """只有 `agent_step`（`judge_bad_json` 就是这一形）⇒ 照旧计 1，别被去重吞掉。"""
    ws = _ws(tmp_path)
    _sessions(ws, [
        {"kind": "agent_step", "role": "F", "ts": "2026-10-28T17:26:57+08:00", "index": 41,
         "shape": "invalid", "payload": {},
         "result": {"problem": "judge_bad_json",
                    "detail": "模型返回的不是一个 JSON 对象（解析报错：末尾少了一个 }）"}},
    ])
    got = ES.error_action_stats(ws)
    assert got.by_role.get("F", {}).get("judge_bad_json") == 1, got.by_role
    assert got.total == 1, got.as_dict()


def test_the_dedupe_is_per_ts_and_role(tmp_path: pathlib.Path):
    """去重只在"同 ts + 同角色 + 同类目"那一格生效：不同角色的同秒失败各算各的。"""
    ws = _ws(tmp_path)
    _sessions(ws, _pair("2026-10-28T17:15:08+08:00", role="B", index=13)
              + _pair("2026-10-28T17:15:08+08:00", role="E", index=16))
    got = ES.error_action_stats(ws)
    assert got.by_role.get("B", {}).get("judge_no_reply") == 1, got.by_role
    assert got.by_role.get("E", {}).get("judge_no_reply") == 1, got.by_role
    assert got.total == 2, got.as_dict()

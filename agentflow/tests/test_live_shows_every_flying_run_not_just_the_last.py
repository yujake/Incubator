# -*- coding: utf-8 -*-
"""判据：同一角色并发跑过几趟时，"还在跑的是哪一趟"必须按台账号配对，不许按角色。

## 真机（2026-10-28 17:44，`projects/paper-rewrite-78c`）

会话里 V 的事件逐条是：

```
17:33:16 start t-000079
17:33:16 start t-000080
17:34:53 start t-000082      ← 这一趟一直在跑（页面名册里标"在飞"）
17:36:41 end   t-000080
17:40:30 end   t-000079
17:40:38 start t-000092
17:44:08 end   t-000092
```

旧口径是按角色配平（"该角色最后一条 start 之后有没有该角色的 end"）⇒ 最后一条 start
是 t-000092、它自己已经 end ⇒ 判定"V 没有在跑"。可 t-000082 一行 end 都没有，它确实还在飞。

于是同一个页面上两处读数打架：上面「在飞」只列 M/D/F（漏了 V），下面名册树里
V 的 t-000082 标着"在飞"。这正是 E-13 想治的那一类（"按角色而不是按整段会话"），
只是当年只往前推了一层：真正能配平这两条事件的键是 `task_id`。

## 这一组守什么

1. 同角色并发、后起的那趟先结束 ⇒ 先起那趟仍要报出来（真机那一格）；
2. 全结完 ⇒ `running` 空、`answer="没有"`（反真空：不许永远说"有"）；
3. 老会话的事件没有 `task_id` ⇒ 退回按角色配平（不许把老读数全丢）；
4. `resume_refused` 的 start 仍然不算在跑（E-13 那条不许被这次改回去）；
5. 行里带 `task_id`（新键）：页面/`--status` 才能说清"在飞的是哪一趟"；
6. 负控：把口径退回"按角色取最后一条 start"，同一批事件必须漏掉 t-000082（证明这条判据有对手方）。
"""
from __future__ import annotations

import json
import pathlib

from agentflow import sessions as SS
from agentflow import stopctl as SC
from agentflow.store import Store


def _ws(tmp_path: pathlib.Path) -> pathlib.Path:
    ws = tmp_path / "ws"
    (ws / "data").mkdir(parents=True)
    Store(ws).init()
    return ws


def _seq(root: pathlib.Path, rows: list[tuple[str, str, str]]) -> None:
    """把 `(kind, role, task_id)` 逐条写进会话（ts 按写入顺序自动生成）。"""
    for kind, role, tid in rows:
        event = {"kind": kind, "role": role}
        if tid:
            event["task_id"] = tid
        SS.append(root, event, sid="probe")


#: 真机那一格的最小复刻：V 的 t-3 一直没 end，而比它晚起的 t-4 已经结完。
REAL = [
    ("agent_run_start", "V", "t-000079"),
    ("agent_run_start", "V", "t-000080"),
    ("agent_run_start", "V", "t-000082"),
    ("agent_run_end", "V", "t-000080"),
    ("agent_run_end", "V", "t-000079"),
    ("agent_run_start", "V", "t-000092"),
    ("agent_run_end", "V", "t-000092"),
]


def _old_rule(root: pathlib.Path) -> list[str]:
    """改前的口径（按角色取最后一条 start）；这里留一份作对手方，判据才有得比。"""
    out: list[str] = []
    for info in SS.list_sessions(root):
        sid = str(info.get("sid") or "")
        events, _bad = SS.read_session(root, sid)
        last: dict[str, str] = {}
        closed: set[str] = set()
        for e in events:
            role = str(e.get("role") or "")
            if e.get("kind") == "agent_run_start":
                if e.get("resume_refused"):
                    continue
                last[role] = str(e.get("task_id") or "")
                closed.discard(role)
            elif e.get("kind") == "agent_run_end":
                closed.add(role)
        for role, tid in last.items():
            if role not in closed:
                out.append(f"{role}:{tid}")
    return sorted(out)


def test_a_run_that_is_still_flying_is_not_masked_by_a_later_sibling(tmp_path: pathlib.Path):
    """正题：同角色并发，后起的那趟先结完，先起那趟仍必须在 `running` 里。"""
    ws = _ws(tmp_path)
    _seq(ws, REAL)
    got = SC.running_loops(ws)
    tids = {str(r.get("task_id") or "") for r in got["running"]}
    assert "t-000082" in tids, got
    assert got["answer"] == "有", got


def test_the_negative_control_shows_the_old_rule_misses_it(tmp_path: pathlib.Path):
    """负控：退回"按角色取最后一条 start"，同一批事件就漏掉 t-000082 —— 判据有对手方。"""
    ws = _ws(tmp_path)
    _seq(ws, REAL)
    assert _old_rule(ws) == [], "旧口径居然也看见了它 ⇒ 这条负控没有对手方，判据证明不了什么"
    assert "t-000082" in {str(r.get("task_id") or "") for r in SC.running_loops(ws)["running"]}


def test_everything_finished_means_nothing_is_running(tmp_path: pathlib.Path):
    """反真空：全结完 ⇒ 空列表 + `answer="没有"`（不许永远说"有"）。"""
    ws = _ws(tmp_path)
    _seq(ws, [("agent_run_start", "V", "t-1"), ("agent_run_end", "V", "t-1"),
              ("agent_run_start", "D", "t-2"), ("agent_run_end", "D", "t-2")])
    got = SC.running_loops(ws)
    assert got["running"] == [] and got["answer"] == "没有", got


def test_old_sessions_without_a_task_id_fall_back_to_the_role_rule(tmp_path: pathlib.Path):
    """老会话的事件没有 `task_id` ⇒ 退回按角色配平，不许把老读数全丢。"""
    ws = _ws(tmp_path)
    _seq(ws, [("agent_run_start", "V", ""), ("agent_run_start", "D", ""),
              ("agent_run_end", "D", "")])
    got = SC.running_loops(ws)
    assert [str(r.get("role")) for r in got["running"]] == ["V"], got
    assert got["answer"] == "有", got


def test_a_refused_resume_is_still_not_a_running_loop(tmp_path: pathlib.Path):
    """E-13 那条不许被这次改回去：`resume_refused` 的 start 不算在跑。"""
    ws = _ws(tmp_path)
    SS.append(ws, {"kind": "agent_run_start", "role": "M", "task_id": "t-9",
                   "resume_refused": "checkpoint_mismatch"}, sid="probe")
    got = SC.running_loops(ws)
    assert got["running"] == [] and got["answer"] == "没有", got


def test_the_row_says_which_task_and_which_session(tmp_path: pathlib.Path):
    """行里带 `task_id`：页面与 `--status` 才能说清"在飞的是哪一趟"。"""
    ws = _ws(tmp_path)
    _seq(ws, REAL)
    rows = [r for r in SC.running_loops(ws)["running"] if r.get("task_id") == "t-000082"]
    assert rows, "t-000082 没被报出来"
    row = rows[0]
    assert set(row) >= {"role", "sid", "since", "task_id"}, row
    assert row["role"] == "V" and row["sid"] == "probe", row
    json.dumps(row, ensure_ascii=False)          # 可 JSON 化（要进 /api/live 与页面）

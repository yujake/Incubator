# -*- coding: utf-8 -*-
"""判据：有坏行时，已经算出来的读数不许丢（`tri=unreadable` ≠ 一无所有）。

## 改前是什么样（`draft/187` P3-1 / B7 的现场读数）

`badlines` 副本实测：`/api/run-digest` 回 `tri=unreadable`，但同时给了
`runs=22 / steps=475 / usd=2.42272 / dispatched=11 / verified=12`，`reason` 里带
「第 11 行读不出来…；第 22–23 行读不出来（2 行）」。`/api/run/{sid}/events` 同理：
`tri=unreadable` 但 `total=1916`、`events` 里有 5 条。

页面改前走 `digest.data.tri !== "computed"` 分支只印一句「这一格没查成（不是一份 0 档案）」
+「趟数 / 步数 / 花销 / 派活 / 验签那几格因此是 unknown，不是 0」—— 把有的数说成
unknown；事件那一栏干脆直接 return 一句「这一栏没查成」，5 条与 1916 都不上屏。

## 三条

1. 后端读数：坏行 ⇒ `tri=unreadable`，而 `runs` / `steps` / `usd` / `total` /
   `events` 照常给（`readers.run_digest` / `run_events` 的 docstring 逐字如此）；
2. 页面：这一档不再整块换成一句话 —— 理由单独一条，下面每一格照印自己的值；
3. 反真空：把改前那一句「因此是 unknown」塞回页面源码 ⇒ 检查函数必须报红。
"""
from __future__ import annotations

import json
import pathlib
import re
from typing import Any

from agentflow.webui import readers as R

REPO = pathlib.Path(__file__).resolve().parents[1]
RUN_TSX = REPO / "ui" / "src" / "pages" / "Run.tsx"

_TS = "2026-11-19T10:00:00+08:00"
_SID = "2026-11-19"
_TASK = "t-000001"


def _workspace(tmp_path: pathlib.Path) -> pathlib.Path:
    """一段会话：起、一步、收工，外加一条坏行（坏行不在合法行之间当数据用）。"""
    root = tmp_path / "ws"
    (root / "sessions").mkdir(parents=True)
    lines = [
        {"kind": "agent_run_start", "ts": _TS, "role": "F", "task_id": _TASK,
         "task": "夹具", "sid": _SID},
        {"kind": "agent_step", "ts": _TS, "role": "F", "task_id": _TASK, "shape": "tool"},
        {"kind": "llm_call", "ts": _TS, "role": "F", "task_id": _TASK, "usd": 1.5,
         "tokens_in": 10, "tokens_out": 5},
        {"kind": "agent_run_end", "ts": _TS, "role": "F", "task_id": _TASK,
         "stop_reason": "final", "steps": 1},
    ]
    body = "".join(json.dumps(one, ensure_ascii=False) + "\n" for one in lines)
    body += "{这一行不是 JSON\n"
    (root / "sessions" / f"{_SID}.jsonl").write_text(body, encoding="utf-8")
    return root


# ====================================================================== 1 后端读数
def test_a_bad_line_keeps_the_numbers_the_verdict_only_says_unreadable(
        tmp_path: pathlib.Path) -> None:
    """坏行 ⇒ `tri=unreadable`，而趟数 / 步数 / 花销 / 事件条数照给。"""
    root = _workspace(tmp_path)
    digest = R.run_digest(root, _SID)
    assert digest["tri"] == "unreadable", digest
    assert "坏行" in digest["reason"], digest["reason"]
    # 反真空：这几个数不是 0 —— 有真的一趟、一步、一笔钱。
    assert digest["runs"] == 1, digest
    assert digest["steps"] == 1, digest
    assert digest["usd"] == 1.5, digest
    # 「派活」是另一档三态：这一趟的收工行没报 `summons` ⇒ `None`（不知道该派了没有），
    # 不是 0。它与上面那几个「已经算出来的数」不是一回事，这里分开钉。
    assert digest["dispatched"] is None, digest

    events = R.run_events(root, _SID)
    assert events["tri"] == "unreadable", events
    assert events["total"] == 4, events
    assert len(events["events"]) == 4, events
    assert "坏行" in events["reason"], events["reason"]


# ====================================================================== 2 页面
def _strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"(?m)^\s*//.*$", "", text)


def _run_page_problems(source: str) -> list[str]:
    """纯函数（可负控）：坏行那一档是不是仍然把读数印出来。"""
    code = _strip_comments(source)
    problems: list[str] = []
    if "因此是 unknown" in code:
        problems.append("页面还在说「因此是 unknown」—— 把已经算出来的数说成没查到")
    if "有坏行：读得出来的照常算" not in code:
        problems.append("页面没有「有坏行：读得出来的照常算」这一档（坏行被读成「一无所有」）")
    if "const partial = data.tri !== \"computed\"" not in code:
        problems.append("事件那一栏没有 partial 档（改前是直接 return 一句「没查成」）")
    for token in ("formatCount(digest.data.runs)", "formatCount(digest.data.steps)",
                  "formatCount(data.total)"):
        if token not in code:
            problems.append(f"页面没有印 `{token}`")
    return problems


def test_the_page_keeps_the_readings_when_a_row_is_broken() -> None:
    """页面那一半：坏行只加一条理由，不换掉整块读数；负控能抓住旧写法。"""
    source = RUN_TSX.read_text(encoding="utf-8")
    assert _run_page_problems(source) == [], _run_page_problems(source)
    # 反真空：把改前那一句塞回去 ⇒ 必须报红。
    planted = source.replace("有坏行：读得出来的照常算", "因此是 unknown，不是 0", 1)
    assert planted != source, "负控没改到源码"
    assert _run_page_problems(planted), "检查函数对旧写法没报红"

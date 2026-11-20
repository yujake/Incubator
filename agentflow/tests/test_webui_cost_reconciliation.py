# -*- coding: utf-8 -*-
"""判据：四个成本数并排时，差额要有一句对账（账本 − 事件 = extract 那几笔）。

## 改前是什么样（`draft/187` P4-1 / B10 的现场读数）

收工页一行内并排印着四个数：

```
事件求和 2.422720 · 收工行自报 2.271637 · 无人认领 0.151083 · usage_ledger 2.543759（522 行）
2.422720 − 2.271637 = 0.151083 ✓（自洽）
2.422720 + 0.151083 = 2.573803 ≠ 2.543759，差 0.121039
```

这 0.121039 正好等于 `/api/budget.by_scope.extract.usd`（14 行）—— 事件流里没有这 14 笔
调用。页面上没有这句话，读者只能说「四个数里三个对不上」。

## 三条

1. 后端：`closing.cost.reconciliation` 给 `by_scope` / `extract_usd` / 差额 /
   `explained_by_extract` / `event_llm_calls`，归口来自 `tokenmeter.TokenMeter.by_scope()`
   （唯一出处，不在这一层另算一遍分组）；
2. 页面：收工页印那一句（差额 = extract 那几笔 / ≠ 时说清"还有别的来源"）；
3. 反真空：把 extract 打桩成 0（差额不再能解释）⇒ `explained_by_extract` 必须是
   `False` 而不是"照样说等于"；页面源码退回旧读法 ⇒ 检查函数报红。
"""
from __future__ import annotations

import json
import pathlib
import re
from typing import Any

from agentflow.webui import readers as R

REPO = pathlib.Path(__file__).resolve().parents[1]
ACCEPTANCE_TSX = REPO / "ui" / "src" / "pages" / "Acceptance.tsx"
_TS = "2026-11-19T10:00:00+08:00"
_SID = "2026-11-19"
_TASK = "t-000001"


def _workspace(tmp_path: pathlib.Path) -> pathlib.Path:
    """会话（事件求和 1.5）+ 账本（1.0 reason + 0.5 summon + 0.25 extract = 1.75）。

    差额 0.25 恰好等于 extract 那几笔 —— 这就是真机上那句"账本 − 事件 = extract"。
    """
    root = tmp_path / "ws"
    (root / "sessions").mkdir(parents=True)
    (root / "data").mkdir(parents=True)
    events = [
        {"kind": "agent_run_start", "ts": _TS, "role": "F", "task_id": _TASK,
         "task": "夹具", "sid": _SID},
        {"kind": "llm_call", "ts": _TS, "role": "F", "task_id": _TASK, "usd": 0.75,
         "tokens_in": 10, "tokens_out": 5},
        {"kind": "llm_call", "ts": _TS, "role": "F", "task_id": _TASK, "usd": 0.75,
         "tokens_in": 10, "tokens_out": 5},
        {"kind": "agent_run_end", "ts": _TS, "role": "F", "task_id": _TASK,
         "stop_reason": "final", "steps": 0},
    ]
    (root / "sessions" / f"{_SID}.jsonl").write_text(
        "".join(json.dumps(one, ensure_ascii=False) + "\n" for one in events),
        encoding="utf-8")
    ledger = [
        {"usage_id": "000000", "scope": "reason", "role": "F", "task_id": _TASK,
         "tokens_in": 1, "tokens_out": 1, "tokens_total": 2, "usd": 1.0,
         "attempts": 1, "at": _TS, "note": "", "idem_key": "idem-a"},
        {"usage_id": "000001", "scope": "summon", "role": "M", "task_id": _TASK,
         "tokens_in": 0, "tokens_out": 0, "tokens_total": 0, "usd": 0.5,
         "attempts": 1, "at": _TS, "note": "", "idem_key": "idem-b"},
        {"usage_id": "000002", "scope": "extract", "role": "B", "task_id": _TASK,
         "tokens_in": 0, "tokens_out": 0, "tokens_total": 0, "usd": 0.25,
         "attempts": 1, "at": _TS, "note": "", "idem_key": "idem-c"},
    ]
    (root / "data" / "usage_ledger.json").write_text(
        json.dumps({"schema_version": 2, "rows": ledger}, ensure_ascii=False),
        encoding="utf-8")
    return root


def _cost(root: pathlib.Path) -> dict[str, Any]:
    pkg = R.package_face(root, project_dir=".")
    return pkg["closing"]["cost"]


# ====================================================================== 1 后端
def test_the_cost_difference_is_explained_by_the_extract_scope(
        tmp_path: pathlib.Path) -> None:
    """账本 − 事件 = extract 那几笔；账本行数另不等于事件里的调用数。"""
    cost = _cost(_workspace(tmp_path))
    recon = cost["reconciliation"]
    assert cost["event_usd"] == 1.5, cost
    assert cost["ledger_usd"] == 1.75, cost
    assert recon["extract_usd"] == 0.25, recon
    assert recon["ledger_minus_event_usd"] == 0.25, recon
    assert recon["explained_by_extract"] is True, recon
    assert recon["extract_entries"] == 1, recon
    assert recon["event_llm_calls"] == 2, recon
    assert cost["ledger_rows"] == 3, cost
    # 「账本行」与「调用数」是两个数（一次调用可记 0..n 行）——这一句也要在。
    assert "不许互相顶替" in recon["note"], recon["note"]


# ====================================================================== 2 反真空
def test_a_difference_the_extract_scope_does_not_explain_is_not_said_to_be_equal(
        monkeypatch: Any, tmp_path: pathlib.Path) -> None:
    """把归口打桩成「没有 extract」⇒ 差额解释不了，`explained_by_extract` 必须是 False。"""
    from agentflow import tokenmeter as TM

    class _NoExtract:
        def __init__(self, *a: Any, **k: Any) -> None:
            pass

        def by_scope(self) -> dict[str, Any]:
            return {"reason": {"usd": 1.0, "entries": 1}, "summon": {"usd": 0.5, "entries": 1}}

    monkeypatch.setattr(TM, "TokenMeter", _NoExtract, raising=True)
    recon = _cost(_workspace(tmp_path))["reconciliation"]
    assert recon["extract_usd"] == 0, recon
    assert recon["ledger_minus_event_usd"] == 0.25, recon
    assert recon["explained_by_extract"] is False, recon


# ====================================================================== 3 页面
def _strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"(?m)^\s*//.*$", "", text)


def _page_problems(source: str) -> list[str]:
    """纯函数（可负控）：页面有没有把差额那句印出来。"""
    code = _strip_comments(source)
    problems: list[str] = []
    for token in ("closing.cost.reconciliation.ledger_minus_event_usd",
                  "closing.cost.reconciliation.extract_usd",
                  "closing.cost.reconciliation.explained_by_extract",
                  "closing.cost.reconciliation.event_llm_calls"):
        if token not in code:
            problems.append(f"收工页没有读 `{token}`")
    if "成本对账" not in code:
        problems.append("收工页没有「成本对账」那一行")
    return problems


def test_the_acceptance_page_reconciles_the_four_amounts() -> None:
    """页面那一半：四个数并排之后有一句对账；负控能抓住退回旧读法。"""
    source = ACCEPTANCE_TSX.read_text(encoding="utf-8")
    assert _page_problems(source) == [], _page_problems(source)
    doctored = source.replace("closing.cost.reconciliation.extract_usd", "closing.cost.ledger_usd")
    assert doctored != source, "负控没改到源码"
    assert _page_problems(doctored), "检查函数对旧读法没报红"

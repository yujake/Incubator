# -*- coding: utf-8 -*-
"""带 `why` 的调用在 `log_calls=False` 时**不许炸**（缺陷 ⑬，2026-10-18 根因）。

## 这个缺陷有多贵

`tools/base.py` 的调用日志段原来是：

```python
if self.log_calls:
    entry = {"tool": …, "ok": res.ok, …}      # ← entry 只在这里赋值
if _why:                                       # ← 没有 log_calls 判断
    entry["why"] = str(_why)[:400]             # ← 生产默认 log_calls=False ⇒ UnboundLocalError
    self._call_log.append(entry)
```

于是**生产里任何带 `why` 的工具调用都会抛** `UnboundLocalError: cannot access local variable 'entry'`。
真机三处报错全是它：

* `table.create`（T2 的 D 写 `research_questions`，idx 5/6/8 三次失败、idx 9 换别名成功）；
* `review.verify_fixes`（T1 的 H 复审那一趟）；
* M 在验收表里把它误记成「`search.download` 对内联 URL 一律 `UnboundLocalError`」。

它**间歇**是因为只有"调用方传了 `why`"才触发 —— 所以探针不传 `why` 时全绿，
真机一传就炸。这条判据同时钉住两个方向：`log_calls` 开/关 × 传/不传 `why`。
"""
from __future__ import annotations

import pathlib
import tempfile

import pytest

from agentflow.store import Store
from agentflow.tools import build_registry
from agentflow.tools.base import ToolRegistry, ToolSpec


def _registry(*, log_calls: bool) -> ToolRegistry:
    ws = pathlib.Path(tempfile.mkdtemp())
    reg = build_registry(store=Store(ws), workspace_root=ws).registry
    reg.log_calls = log_calls
    return reg


def _row(q: str) -> dict:
    return {"question": q, "origin": "gap", "kind": "gap", "priority": "high",
            "status": "researching", "gap_reason": "判据用的最小行"}


@pytest.mark.parametrize("log_calls", [False, True])
def test_a_call_with_why_never_raises(log_calls):
    """**正控**：`log_calls` 两种取值下，带 `why` 的 `table.create` 都必须正常返回。"""
    reg = _registry(log_calls=log_calls)
    r = reg.call("table.create", role="D", table="research_questions", row=_row("q1"),
                 why="这条为什么值得登记")
    assert r.ok, f"带 why 的调用炸了（log_calls={log_calls}）：{r.error}"


@pytest.mark.parametrize("log_calls", [False, True])
def test_why_lands_in_the_call_log_when_logging_is_on(log_calls):
    """**留痕**：`log_calls=True` 时 `why` 必须真的进了调用日志（不是被静默丢掉）。"""
    reg = _registry(log_calls=log_calls)
    before = len(reg.call_log())
    reg.call("table.create", role="D", table="research_questions", row=_row("q2"),
             why="留痕测试")
    log = reg.call_log()
    if not log_calls:
        assert len(log) == before, "log_calls=False 却往日志里写了东西"
        return
    assert len(log) == before + 1
    assert str(log[-1].get("why")) == "留痕测试"


def test_a_call_without_why_is_unaffected():
    """**负控**：不带 `why` 的调用行为不变（两种模式都能过）。"""
    for flag in (False, True):
        reg = _registry(log_calls=flag)
        r = reg.call("table.create", role="D", table="research_questions", row=_row(f"q-{flag}"))
        assert r.ok, r.error

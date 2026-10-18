# -*- coding: utf-8 -*-
"""长 `Retry-After` 不许**原地睡**（缺陷 ⑭，真机 T2 抓到）。

## 现场

`providers.http_get_json` 收到 HTTP 429 时，会按服务端给的 `Retry-After` 睡过去再试。
OpenAlex 回的是 **`Retry-After: 60`** ⇒ 每一次限流都睡 60 秒。
真机读数（`projects/t2t`）：**20 分钟只烧掉 $0.09** —— 时间全花在等，不在做研究。

这与 `_h_download` 里那条既有原则是同一句话：**限流要换源，不在原地耗时间**。

## 现在的口径

`delay > RATE_LIMIT_MAX_WAIT_SEC`（10 秒）⇒ **不睡**，立刻抛 `rate_limited`，
让检索层去换 provider。短的 `Retry-After`（≤10s）仍照常等待重试。
"""
from __future__ import annotations

import urllib.error

import pytest

from agentflow import providers as P


class _Logger:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def warning(self, msg: str, *args, **kwargs) -> None:
        self.lines.append(msg % args if args else msg)


def _patch(monkeypatch, *, retry_after: str | None):
    calls = {"n": 0}

    def boom(request, timeout=None):  # noqa: ARG001 - 签名对齐 urlopen
        calls["n"] += 1
        headers = {} if retry_after is None else {"Retry-After": retry_after}
        raise urllib.error.HTTPError(request.full_url, 429, "rate limited",
                                     headers, None)

    monkeypatch.setattr(P.urllib.request, "urlopen", boom)
    slept: list[float] = []
    monkeypatch.setattr(P.time, "sleep", lambda s: slept.append(float(s)))
    logger = _Logger()
    monkeypatch.setattr(P, "logger", logger)
    return calls, slept, logger


def test_a_long_retry_after_does_not_block(monkeypatch):
    """**正控**：`Retry-After: 60` ⇒ 一次都不睡，立刻抛（检索层才能换源）。"""
    calls, slept, logger = _patch(monkeypatch, retry_after="60")
    with pytest.raises(Exception) as ei:
        P.http_get_json("https://api.openalex.org/works", retries=3)
    assert "429" in str(ei.value) or "HTTP" in str(ei.value), ei.value
    assert slept == [], f"它睡了 {slept} 秒 —— 长限流不该原地等"
    assert calls["n"] == 1, f"它重试了 {calls['n']} 次"
    assert any("rate_limited" in m or "不在原地等" in m for m in logger.lines), logger.lines


def test_a_short_retry_after_still_retries(monkeypatch):
    """**负控**：`Retry-After: 2` 是短等待 ⇒ 仍按原策略重试（不许把好的一起砍掉）。"""
    calls, slept, _ = _patch(monkeypatch, retry_after="2")
    with pytest.raises(Exception):
        P.http_get_json("https://api.openalex.org/works", retries=2)
    assert calls["n"] >= 2, f"短限流应该重试，实际只试了 {calls['n']} 次"
    assert slept, "短限流应当有等待"


def test_the_cap_is_ten_seconds():
    """把上限本身钉住（改它等于改"愿意等多久"这件事）。"""
    assert P.RATE_LIMIT_MAX_WAIT_SEC == 10.0

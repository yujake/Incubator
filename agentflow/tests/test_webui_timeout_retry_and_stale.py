"""判据（鲁棒 c）：请求会超时、会重试；SSE 断了会重连、过期会说「数据可能过期」。

## 三件事，三个真行为（都在前端源码里可读）

1. 读请求有超时：`getJSON` 走 `fetchOnce`，它用 `AbortController` 在
   `REQUEST_TIMEOUT_MS`（15 秒）后真把请求掐掉 —— 不是"等它自己回来"。
   没有这一条，`/api/state` 慢或后端卡住时页面就是无限转圈。
2. 读请求有有界重试：网络 / 超时 / 5xx 最多再试 `RETRY_LIMIT`（2）次，退避
   `RETRY_BASE_MS * 2^n`；写请求不自动重试（同一次写重放 = 两次副作用：
   回答两次、追加两次预算）。
3. SSE 降级之后不是终点：轮询期间每隔 `STREAM_REOPEN_MS` 再试着把 SSE 接回来；
   轮询连续失败到 `STALE_AFTER_POLL_FAILS` 就把连接态报成 `stale`，顶部横幅
   逐字写「数据可能过期」。

## 反真空（三条负控）

- 把 `getJSON` 的重试循环退回"只发一次" ⇒ 判据必须报；
- 把 `sse.ts` 的复连定时器删掉 ⇒ 判据必须报（"轮询了就不再试 SSE"是旧形态）；
- 把横幅里的「数据可能过期」删掉 ⇒ 判据必须报（否则 stale 与 degraded 长得一样）。
"""
from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[1]
API_TS = REPO / "ui" / "src" / "api.ts"
SSE_TS = REPO / "ui" / "src" / "sse.ts"
LIVE_TSX = REPO / "ui" / "src" / "live.tsx"


def _strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"//[^\n]*", "", text)


def _api_problems(text: str) -> list[str]:
    code = _strip_comments(text)
    problems: list[str] = []
    for name in ("AbortController", "REQUEST_TIMEOUT_MS", "RETRY_LIMIT", "RETRY_BASE_MS"):
        if name not in code:
            problems.append(f"api.ts 没有 `{name}`（请求不会超时 / 不会重试）")
    if "fetchOnce" not in code:
        problems.append("api.ts 没有 fetchOnce（超时与重试没有共同落点）")
    if not re.search(r"for \([^)]*attempt[^)]*RETRY_LIMIT", code):
        problems.append("getJSON 没有按 RETRY_LIMIT 的重试循环（只发一次）")
    # 写路径不许重试：postForm 里出现 RETRY / fetchOnce 之外的循环都算红。
    at = code.find("async function postForm")
    if at < 0:
        problems.append("api.ts 没有 postForm")
    else:
        body = code[at:]
        if "RETRY_LIMIT" in body or "retryable" in body:
            problems.append("postForm 里出现重试 —— 写请求不许自动重放（两次副作用）")
    return problems


def _sse_problems(text: str) -> list[str]:
    code = _strip_comments(text)
    problems: list[str] = []
    if '"stale"' not in code:
        problems.append("sse.ts 的连接态没有 stale（轮询也失败时无法说「可能过期」）")
    for name in ("STREAM_REOPEN_MS", "STALE_AFTER_POLL_FAILS", "POLL_INTERVAL_MS"):
        if name not in code:
            problems.append(f"sse.ts 没有 `{name}`")
    # 复连：降级之后的某处定时器里必须再调 open()（轮询不是终点），
    # 而且那个定时器的间隔就是 STREAM_REOPEN_MS（不是随手写一个数）。
    if not re.search(
        r"setInterval\(\(\) => \{[\s\S]{0,400}?open\(\);[\s\S]{0,120}?\}, STREAM_REOPEN_MS\);",
        code,
    ):
        problems.append("sse.ts 降级之后没有再试 SSE 的定时器（轮询成了终点）")
    return problems


def _banner_problems(text: str) -> list[str]:
    code = _strip_comments(text)
    problems: list[str] = []
    if "数据可能过期" not in code:
        problems.append("live.tsx 的横幅没有写「数据可能过期」（stale 与 degraded 长得一样）")
    if 'live.connection === "stale"' not in code:
        problems.append("live.tsx 的横幅没有 stale 这一支")
    return problems


def test_the_read_path_has_a_timeout_and_bounded_retries() -> None:
    """正控：超时 + 有界重试 + 写路径不重试。"""
    source = API_TS.read_text(encoding="utf-8")
    assert _api_problems(source) == [], _api_problems(source)
    # 负控一：把重试循环退回"只发一次"。
    doctored = source.replace("for (let attempt = 0; attempt <= RETRY_LIMIT; attempt += 1)",
                              "for (let attempt = 0; attempt <= 0; attempt += 1)")
    assert doctored != source, "负控没改到源码"
    assert any("RETRY_LIMIT" in p for p in _api_problems(doctored)), _api_problems(doctored)


def test_the_stream_reopens_after_degrading_and_says_stale() -> None:
    """正控：降级后可复连；轮询连续失败报 stale。"""
    sse = SSE_TS.read_text(encoding="utf-8")
    assert _sse_problems(sse) == [], _sse_problems(sse)
    live = LIVE_TSX.read_text(encoding="utf-8")
    assert _banner_problems(live) == [], _banner_problems(live)
    # 负控二：整段删掉复连定时器（不是只改赋值方式 —— 那还留着 setInterval 的字面）。
    start = sse.find("reopen = window.setInterval(")
    stop = sse.find("}, STREAM_REOPEN_MS);", start)
    assert start >= 0 and stop > start, "负控没找到复连那一段"
    doctored = sse[:start] + sse[stop + len("}, STREAM_REOPEN_MS);"):]
    assert _sse_problems(doctored), "删掉复连之后判据仍然绿 ⇒ 这一条没有牙"
    # 负控三：横幅不再说「数据可能过期」。
    assert _banner_problems(live.replace("数据可能过期", "降级")), "横幅负控没红"

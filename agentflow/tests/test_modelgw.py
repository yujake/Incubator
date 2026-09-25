"""`modelgw`（模型网关）的测试：三态纪律 + 重试 + 脱敏，全部离线可跑。

## 为什么这些用例一条都不联网

网关是"能不能挂上 key 跑通"的唯一入口，它的失败路径比成功路径重要得多
（key 没配、401、429、超时、上游返回非 JSON、上游返回空内容）。
真实网络无法稳定复现这些情形，所以传输层由 `transport=` 注入 ——
每条失败路径都能配一条确定性的负控，而套件保持离线、秒级、可重复。

## 每个用例都在钉一条正在被违反就会出事的规则

- `test_no_key_is_not_checked_not_failure`：没配 key 是"没查成"，不是"模型答错了"；
- `test_empty_content_is_never_success`：空内容绝不能当成功（那会把"没答"读成"答了"）；
- `test_retry_on_rate_limit_then_success`：429 要重试，且 `attempts` 要如实记；
- `test_auth_failure_is_not_retried`：401 重试不会变好，只会烧钱；
- `test_reply_dict_never_leaks_key`：`to_dict()` 与 `redacted()` 永不含 key 本体。
"""

from __future__ import annotations

import json

import pytest

from agentflow import modelgw as G


def _transport(status: int, body: str, *, calls: list[int] | None = None):
    """造一个固定应答的传输层；`calls` 非空时记录调用次数，用来验重试。"""

    def _t(url: str, headers, data: bytes, timeout_sec: float):
        if calls is not None:
            calls.append(1)
        return status, body

    return _t


def _ok_body(text: str = "4", tokens_in: int = 11, tokens_out: int = 3) -> str:
    return json.dumps({
        "choices": [{"message": {"role": "assistant", "content": text}}],
        "usage": {"prompt_tokens": tokens_in, "completion_tokens": tokens_out},
    }, ensure_ascii=False)


def _gw(status: int, body: str, *, key: str = "test-key", retries: int = 0,
        calls: list[int] | None = None) -> G.ModelGateway:
    return G.ModelGateway(
        G.ModelSpec(api_key=key, max_retries=retries),
        transport=_transport(status, body, calls=calls),
        sleep=lambda _s: None,          # 注入 sleep：退避不许让测试真的等
        clock=lambda: 0.0,
    )


# --------------------------------------------------------------- 三态：没查成

def test_no_key_is_not_checked_not_failure():
    """负控：没配 key ⇒ `no_key` + `not_checked=True`，且不发请求。"""
    calls: list[int] = []
    gw = G.ModelGateway(G.ModelSpec(api_key=""), transport=_transport(200, _ok_body(), calls=calls))
    r = gw.complete("1+1=?")
    assert r.ok is False and r.error_kind == "no_key"
    assert r.not_checked is True
    assert calls == [], "没配 key 时不许发起网络请求"


def test_empty_prompt_is_refused_without_spending_money():
    """负控：空 prompt 直接拒，不烧一次必然失败的调用。"""
    calls: list[int] = []
    gw = _gw(200, _ok_body(), calls=calls)
    r = gw.complete("   ")
    assert r.ok is False and r.error_kind == "bad_response"
    assert calls == []


@pytest.mark.parametrize("kind,status", [("timeout", 0), ("network", 0), ("server_error", 500)])
def test_transport_errors_are_not_checked(kind, status):
    """三态：超时/网络/5xx 都属"没查成"，`not_checked` 必须为真。"""
    def _boom(url, headers, data, timeout_sec):
        if kind == "timeout":
            raise TimeoutError("read timed out")
        if kind == "network":
            raise ConnectionError("URLError: [Errno 11001] getaddrinfo failed")
        return status, "upstream exploded"

    gw = G.ModelGateway(G.ModelSpec(api_key="k", max_retries=0), transport=_boom,
                        sleep=lambda _s: None, clock=lambda: 0.0)
    r = gw.complete("hi")
    assert r.ok is False and r.error_kind == kind and r.not_checked is True


# --------------------------------------------------------------- 三态：查了失败

def test_auth_failure_is_failure_and_not_retried():
    """正向 + 负控：401 ⇒ `auth_failed`（不是"没查成"），且不重试。"""
    calls: list[int] = []
    gw = _gw(401, '{"error":"invalid api key"}', retries=3, calls=calls)
    r = gw.complete("hi")
    assert r.error_kind == "auth_failed" and r.not_checked is False
    assert len(calls) == 1, "401 重试不会变好，只会烧钱"
    assert r.http_status == 401


@pytest.mark.parametrize("body", ["<html>proxy error</html>", "{}", '{"choices":[]}',
                                  '{"choices":[{"message":{"content":"   "}}]}'])
def test_bad_response_is_never_success(body):
    """负控（四条）：非 JSON / 缺 choices / 空 choices / 空白内容 —— 一律不许当成功。"""
    r = _gw(200, body).complete("hi")
    assert r.ok is False and r.error_kind == "bad_response"
    assert r.not_checked is False, "上游答了但答坏了，属于失败，不属于没查成"


# --------------------------------------------------------------- 成功与重试

def test_success_carries_usage_and_attempts():
    """正向：成功时 text/usage/attempts/model 都要有值。"""
    r = _gw(200, _ok_body("42", tokens_in=7, tokens_out=5)).complete("1+1=?")
    assert r.ok is True and r.text == "42"
    assert (r.tokens_in, r.tokens_out) == (7, 5)
    assert r.attempts == 1 and r.model and r.not_checked is False


def test_retry_on_rate_limit_then_success():
    """正向：429 重试一次后成功，`attempts` 必须如实记 2。"""
    calls: list[int] = []
    seq = [429, 200]

    def _t(url, headers, data, timeout_sec):
        calls.append(1)
        code = seq[min(len(calls), len(seq)) - 1]
        return code, (_ok_body() if code == 200 else '{"error":"rate limit"}')

    gw = G.ModelGateway(G.ModelSpec(api_key="k", max_retries=2), transport=_t,
                        sleep=lambda _s: None, clock=lambda: 0.0)
    r = gw.complete("hi")
    assert r.ok is True and r.attempts == 2 and len(calls) == 2


def test_retry_exhausted_reports_last_kind():
    """负控：一直 429 ⇒ 最终结局是 `rate_limited`，且 `attempts` = 重试上限 + 1。"""
    calls: list[int] = []
    gw = _gw(429, '{"error":"rate limit"}', retries=2, calls=calls)
    r = gw.complete("hi")
    assert r.error_kind == "rate_limited" and r.attempts == 3 and len(calls) == 3


# --------------------------------------------------------------- 脱敏与配置

def test_reply_dict_and_redacted_never_leak_key():
    """安全负控：`to_dict()` 与 `redacted()` 永不含 key 本体。"""
    secret = "sk-super-secret-value"
    spec = G.ModelSpec(api_key=secret)
    r = _gw(200, _ok_body()).complete("hi")
    blob = json.dumps({"reply": r.to_dict(), "spec": spec.redacted()}, ensure_ascii=False)
    assert secret not in blob
    assert spec.redacted()["api_key"] == "***"


def test_spec_from_env_reads_only_environment():
    """配置只来自环境变量（密钥不落盘），缺省值要能读出。"""
    spec = G.spec_from_env({G.ENV_KEY: " k ", G.ENV_NAME: "m", G.ENV_BASE: "http://x/v1/"})
    assert spec.api_key == "k" and spec.model == "m"
    assert spec.base_url == "http://x/v1", "base_url 末尾斜杠必须归一，否则会拼出双斜杠"
    empty = G.spec_from_env({})
    assert empty.api_key == "" and empty.configured is False


def test_module_selftest_passes_offline():
    """自检本身要能在没有 key、没有网络的环境里通过（退出码 0）。"""
    assert G.gateway_main([]) == 0

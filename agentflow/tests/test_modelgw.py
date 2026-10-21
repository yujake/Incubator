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
    r = gw.complete("1+1=?", scope="reason")
    assert r.ok is False and r.error_kind == "no_key"
    assert r.not_checked is True
    assert calls == [], "没配 key 时不许发起网络请求"


def test_empty_prompt_is_refused_without_spending_money():
    """负控：空 prompt 直接拒，不烧一次必然失败的调用。"""
    calls: list[int] = []
    gw = _gw(200, _ok_body(), calls=calls)
    r = gw.complete("   ", scope="reason")
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
    r = gw.complete("hi", scope="reason")
    assert r.ok is False and r.error_kind == kind and r.not_checked is True


# --------------------------------------------------------------- 三态：查了失败

def test_auth_failure_is_failure_and_not_retried():
    """正向 + 负控：401 ⇒ `auth_failed`（不是"没查成"），且不重试。"""
    calls: list[int] = []
    gw = _gw(401, '{"error":"invalid api key"}', retries=3, calls=calls)
    r = gw.complete("hi", scope="reason")
    assert r.error_kind == "auth_failed" and r.not_checked is False
    assert len(calls) == 1, "401 重试不会变好，只会烧钱"
    assert r.http_status == 401


@pytest.mark.parametrize("body", ["<html>proxy error</html>", "{}", '{"choices":[]}',
                                  '{"choices":[{"message":{"content":"   "}}]}'])
def test_bad_response_is_never_success(body):
    """负控（四条）：非 JSON / 缺 choices / 空 choices / 空白内容 —— 一律不许当成功。"""
    r = _gw(200, body).complete("hi", scope="reason")
    assert r.ok is False and r.error_kind == "bad_response"
    assert r.not_checked is False, "上游答了但答坏了，属于失败，不属于没查成"


def test_thinking_that_eats_the_budget_is_its_own_kind():
    """判据（2026-10-12 T2 真机）：`finish_reason=length` + 正文空 + 思维链非空 ⇒ 单独一档。

    真机那两条：思维链 109,397 / 96,969 字、正文 ""、`max_tokens=32768`
    （109397 ÷ 32768 ≈ 3.3 字/token，与中文推理的字-token 比一致）——
    推理 token 与正文共用同一份完成预算，于是这一步一个字都没留下。
    四件事一起钉：

    1. 不许当成功；
    2. 不许折成 `bad_response`（"协议漂移"与"想太久把预算吃光"处置方向相反）；
    3. 属于"没查成"（我们没拿到可用的回复）；
    4. 不重试 —— 同一个请求必然同一个结局，而每次重试都要再付一整份输出预算。
    """
    body = json.dumps({"choices": [{"finish_reason": "length",
                                    "message": {"role": "assistant", "content": "",
                                                "reasoning_content": "想" * 800}}],
                       "usage": {"prompt_tokens": 10, "completion_tokens": 32768}},
                      ensure_ascii=False)
    calls: list[int] = []
    r = _gw(200, body, retries=2, calls=calls).complete("hi", scope="reason")
    assert r.ok is False and r.error_kind == "output_exhausted", r.to_dict()
    assert r.not_checked is True, "没拿到可用的回复属于没查成，不是'查了没通过'"
    assert len(calls) == 1, "同一个请求重试必然同一个结局，只会再烧一份输出预算"
    assert "思维链 800 字" in r.error_detail, r.error_detail
    # 负控一：同样空正文、但没被截断（`stop`）⇒ 仍是 `bad_response`
    plain = _gw(200, '{"choices":[{"finish_reason":"stop","message":{"content":""}}]}')
    assert plain.complete("hi", scope="reason").error_kind == "bad_response"
    # 负控二：被截断但一个字都没想 ⇒ 也仍是 `bad_response`（那一档是"它没想"，不是"想太多"）
    quiet = _gw(200, '{"choices":[{"finish_reason":"length","message":{"content":""}}]}')
    assert quiet.complete("hi", scope="reason").error_kind == "bad_response"


# --------------------------------------------------------------- 成功与重试

def test_success_carries_usage_and_attempts():
    """正向：成功时 text/usage/attempts/model 都要有值。"""
    r = _gw(200, _ok_body("42", tokens_in=7, tokens_out=5)).complete("1+1=?", scope="reason")
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
    r = gw.complete("hi", scope="reason")
    assert r.ok is True and r.attempts == 2 and len(calls) == 2


def test_retry_exhausted_reports_last_kind():
    """负控：一直 429 ⇒ 最终结局是 `rate_limited`，且 `attempts` = 重试上限 + 1。"""
    calls: list[int] = []
    gw = _gw(429, '{"error":"rate limit"}', retries=2, calls=calls)
    r = gw.complete("hi", scope="reason")
    assert r.error_kind == "rate_limited" and r.attempts == 3 and len(calls) == 3


# --------------------------------------------------------------- 脱敏与配置

def test_reply_dict_and_redacted_never_leak_key():
    """安全负控：`to_dict()` 与 `redacted()` 永不含 key 本体。"""
    secret = "sk-super-secret-value"
    spec = G.ModelSpec(api_key=secret)
    r = _gw(200, _ok_body()).complete("hi", scope="reason")
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


# --------------------------------------------------------------- 用途归口（G-20）

def test_scope_is_required_and_has_no_default():
    """负控：不传 `scope` ⇒ 当场 `TypeError`。

    为什么这必须是硬约束：有缺省值（曾经是 `charge_reply(scope="reason")`）时，
    忘记传的调用点会静默落进那一档 —— 账本总额与条目数全对，
    而"搜索/抽取/审校各花了多少"永远答不出来。缺省值是这条缺陷的成因本身。
    """
    gw = _gw(200, _ok_body())
    with pytest.raises(TypeError):
        gw.complete("hi")  # type: ignore[call-arg]


def test_scope_must_be_in_the_controlled_vocabulary():
    """负控：词表外的 `scope` ⇒ `ValueError`（不静默落档）。"""
    gw = _gw(200, _ok_body())
    with pytest.raises(ValueError, match="scope"):
        gw.complete("hi", scope="不是范围")
    with pytest.raises(ValueError):
        gw.complete("hi", scope="")


def test_scope_travels_with_the_reply_and_into_to_dict():
    """`scope` 随结局回传：记账时不必再回忆一遍（回忆就会写错，而写错是静默的）。"""
    for scope in G.USAGE_SCOPES:
        r = _gw(200, _ok_body()).complete("hi", scope=scope)
        assert r.scope == scope
        assert r.to_dict()["scope"] == scope, "落台账那一层必须看得见它"


def test_every_vocabulary_scope_is_accepted_but_other_is_not():
    """    词表里的每一档都被接受；`other` 不是词表里的一档，所以必须被拒（`G-6`）。

    ## 为什么这条要单独写（改前的形态是错的）

    改前这里是 `for scope in G.USAGE_SCOPES: ... complete("hi", scope=scope)`，而当时 `"other"` 在词表里 —— 于是这条用例逐字要求
    `complete(scope="other")`被接受。它断的是一个真实存在的旧形态（"什么都不是"的档在词表里），而不是一条应当成立的契约：`modelgw.complete` 的 docstring
    自己写着"缺省也不许是「其它」：一个「其他」档会把「有人忘了写」伪装成一个正常的分类"。数据侧（`modelcost.charge_reply` / `tokenmeter.Charge`）也共用这张词表。

    所以改的是断言：断言"词表里每一档都被接受"这件事仍然成立，但不许再把 `other` 算进词表；`other` 改为显式断言被拒。这样"词表 ⊆ 被接受"与"词表外 ⊄ 被接受"两侧都有判据。
    """
    for scope in G.USAGE_SCOPES:
        r = _gw(200, _ok_body()).complete("hi", scope=scope)
        assert r.scope == scope
    assert "other" not in G.USAGE_SCOPES
    with pytest.raises(ValueError, match="scope"):
        _gw(200, _ok_body()).complete("hi", scope="other")


def test_scope_is_kept_even_on_the_failure_paths():
    """负控：失败/没查成也要带 `scope` —— 否则失败的那一档花销归不了口。"""
    no_key = G.ModelGateway(G.ModelSpec(api_key=""), transport=_transport(200, _ok_body()))
    assert no_key.complete("hi", scope="extract").scope == "extract"
    assert _gw(401, '{"error":"x"}').complete("hi", scope="review").scope == "review"
    assert _gw(200, "<html>").complete("hi", scope="search").scope == "search"

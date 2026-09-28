"""`modelclient` 的判据：三态翻译（成功 / 没查成 / 查了失败）与记账只走一条路。

为什么这三态必须分开：`LLMExtractor` 只认"字符串或抛异常"，把所有失败折成一个
`RuntimeError` 会让"没 key"与"模型返回了坏 JSON"在下游长得一模一样 ——
而这两件事该做的动作完全不同（去配 key vs 去查 prompt/模型）。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agentflow.modelclient import (  # noqa: E402
    ModelClient,
    ModelFailed,
    ModelUnavailable,
    client_from_env,
)
from agentflow.modelgw import ModelGateway, ModelSpec  # noqa: E402
from agentflow.store import Store  # noqa: E402
from agentflow.tokenmeter import TokenMeter  # noqa: E402


def _transport(status: int, body: str):
    calls: list[dict] = []

    def _t(url: str, headers, data: bytes, timeout_sec: float):
        calls.append({"url": url, "headers": dict(headers), "data": data})
        return status, body

    _t.calls = calls  # type: ignore[attr-defined]
    return _t


def _body(text: str, tin: int = 11, tout: int = 3) -> str:
    return json.dumps({
        "choices": [{"message": {"role": "assistant", "content": text}}],
        "usage": {"prompt_tokens": tin, "completion_tokens": tout},
    }, ensure_ascii=False)


def _client(transport, *, api_key: str = "selftest-key", meter=None) -> ModelClient:
    spec = ModelSpec(api_key=api_key)
    return ModelClient(gateway=ModelGateway(spec, transport=transport), meter=meter,
                       task_id="t-0001", role="B")


def test_complete_returns_text_and_charges_once() -> None:
    t = _transport(200, _body("甲"))
    c = _client(t)
    assert c.complete("你好") == "甲"
    assert c.calls == 1 and len(c.charges) == 1
    assert c.uncharged() == 1, "meter=None 的记账结局是『未接线』，不许折进 0 里"

    store = Store(Path(__file__).resolve().parent / "_mc_ws")
    try:
        store.init()
        meter = TokenMeter(store)
        c2 = _client(_transport(200, _body("乙")), meter=meter)
        assert c2.complete("你好") == "乙"
        assert c2.uncharged() == 0 and c2.charged_usd() > 0
        assert c2.tokens() == (11, 3)
        rows = store.rows("usage_ledger")
        assert len(rows) == 1 and rows[0]["scope"] == "extract"
    finally:
        import shutil
        shutil.rmtree(store.root, ignore_errors=True)


def test_missing_key_is_not_a_failure() -> None:
    """负控：没 key 必须抛 `ModelUnavailable`（没查成），不许抛 `ModelFailed`。"""
    t = _transport(200, _body("不该被调用"))
    c = _client(t, api_key="")
    with pytest.raises(ModelUnavailable) as exc:
        c.complete("你好")
    assert exc.value.reply is not None and exc.value.reply.not_checked is True
    assert t.calls == [], "没 key 时一次网络请求都不许发"


def test_bad_response_is_a_failure_not_a_not_checked() -> None:
    c = _client(_transport(200, "这不是 JSON"))
    with pytest.raises(ModelFailed) as exc:
        c.complete("你好")
    assert exc.value.reply is not None and exc.value.reply.not_checked is False


def test_http_error_is_translated_by_the_gateway_kind() -> None:
    c = _client(_transport(429, "{}"))
    with pytest.raises((ModelUnavailable, ModelFailed)) as exc:
        c.complete("你好")
    reply = exc.value.reply
    assert reply is not None and reply.error_kind, "失败必须带受控的 error_kind"


def test_call_never_raises_and_exposes_the_tristate() -> None:
    c = _client(_transport(200, "{}"))
    r = c.call("x")
    assert r.ok is False and r.error_kind and r.not_checked is False


def test_client_from_env_reads_the_documented_env_names() -> None:
    c = client_from_env(env={"AGENTFLOW_MODEL_API_KEY": "k", "AGENTFLOW_MODEL_NAME": "m"})
    assert c.gateway.spec.api_key == "k" and c.gateway.spec.model == "m"
    assert c.scope == "extract"
    assert "api_key" not in json.dumps(c.to_dict()), "读数里不许出现 key"

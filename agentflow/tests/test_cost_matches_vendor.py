# -*- coding: utf-8 -*-
"""花销口径与供应商定价对齐：**三档 token**（命中 / 未命中 / 输出）各有其价。

业主 2026-10-14：「将花销计算标准调整到与模型供应商定价吻合」。

## 这一组治的是哪一个口径缺口

改前我们只记两个 token 数（`tokens_in` / `tokens_out`）与两格价，而供应商的账单价目表
按**三种 token** 分开登：命中缓存的输入、未命中缓存的输入、输出。于是：

- 上游回的 `prompt_cache_hit_tokens` / `prompt_cache_miss_tokens` 被**整格丢掉**
  （`modelgw` 只读 `prompt_tokens` / `completion_tokens`）；
- 记账把所有输入都按"未命中价"算 ⇒ **系统性偏高**，而且偏高得没法核对；
- "为什么和供应商账单对不上"这件事在读数上无法定位（账上只有一个 `usd`）。

修法：`ModelReply` / `SeamCall` 各加两格（三态：`None` = 上游没报，0 = 明说零命中）、
`Price` 加一档 `usd_per_m_in_hit`、`usd_for` 按三档分别乘，
`modelcost.billing_reading()` 把"按哪几档算的"留成读数。

## 三态纪律在这一组的位置

"命中价没登记"与"上游没报命中数"都会让 `usd` 偏高 —— 二者都**不许静默**：
`billing_reading()['cache_tri']` 分别报 `price_unknown` / `not_reported`，
而只有两样都在位时才报 `billed`。
"""

from __future__ import annotations

import json

from agentflow import modelcost as MC
from agentflow import modelgw as G

#: 一份**示例**价（不是任何厂商的登记值）—— 判据只关心算术，不关心具体数字。
EXAMPLE = MC.Price(usd_per_m_in=1.0, usd_per_m_out=2.0, usd_per_m_in_hit=0.25)


def _reply(tokens_in: int = 1000, tokens_out: int = 100,
           hit: int | None = 800, miss: int | None = 200, attempts: int = 1):
    return G.ModelReply(ok=True, text="x", tokens_in=tokens_in, tokens_out=tokens_out,
                        cache_hit_tokens=hit, cache_miss_tokens=miss, attempts=attempts)


def test_the_three_tiers_are_billed_at_their_own_prices():
    """正控：命中那部分按命中价、未命中按未命中价、输出按输出价 —— 逐档可复算。

    手算（每百万 token 的价）：`800×0.25 + 200×1.0 + 100×2.0 = 200 + 200 + 200 = 600`
    ⇒ 600 / 1e6 = 0.0006。改前会算成 `1000×1.0 + 100×2.0 = 1200` / 1e6 = 0.0012（贵一倍）。
    """
    got = MC.usd_for(_reply(), EXAMPLE)
    assert got == 0.0006, got
    reading = MC.billing_reading(_reply(), EXAMPLE)
    assert reading["cache_tri"] == "billed", reading
    assert reading["cache_hit_tokens"] == 800 and reading["usd_per_m_in_hit"] == 0.25, reading


def test_retries_multiply_the_three_tier_total():
    """口径不变：`attempts` 乘在总额上（每次重试都是另一次计费请求）。"""
    assert MC.usd_for(_reply(attempts=3), EXAMPLE) == 0.0018


def test_a_missing_hit_price_is_conservative_and_says_so():
    """三态之一：命中价**没登记** ⇒ 全部按未命中价算（偏保守）+ 一条 `price_unknown`。

    这条负控钉的是"不许把不知道写成一个更便宜的数字"：若实现把未登记的命中价
    当成 0，这条断言会当场红（`usd` 会掉到 0.0004）。
    """
    p = MC.Price(usd_per_m_in=1.0, usd_per_m_out=2.0)   # 没有 hit 档
    assert MC.usd_for(_reply(), p) == 0.0012, "未登记命中价时必须按未命中价算（保守）"
    reading = MC.billing_reading(_reply(), p)
    assert reading["cache_tri"] == "price_unknown", reading
    assert reading["usd_per_m_in_hit"] is None, reading


def test_upstream_silence_is_a_third_state_not_a_zero():
    """三态之二：上游**没回**命中数（`None`）⇒ `not_reported`，且与"明说零命中"分得开。

    注意"零命中"与"上游没报"在**金额**上可以相等（两种都按未命中价算）——
    这条判据断言的是**读数**分得开（`cache_tri` 两档 + 命中数那一格 `0` vs `None`），
    以及在真的命中时金额**不同**（`800×0.25` 而不是 `800×1.0`）。
    """
    silent = MC.billing_reading(_reply(hit=None, miss=None), EXAMPLE)
    assert silent["cache_tri"] == "not_reported", silent
    assert silent["cache_hit_tokens"] is None, silent
    zero_hit = MC.billing_reading(_reply(hit=0, miss=1000), EXAMPLE)
    assert zero_hit["cache_tri"] == "billed", zero_hit
    assert zero_hit["cache_hit_tokens"] == 0 and zero_hit["usd"] == 0.0012, zero_hit
    hit = MC.billing_reading(_reply(), EXAMPLE)
    assert hit["usd"] < silent["usd"], (hit, silent)


def test_the_gateway_reads_the_vendors_cache_columns(monkeypatch):
    """网关那一层：上游回的 `prompt_cache_*` 必须被读进来（否则上面全是对着空气算）。"""
    body = {
        "choices": [{"message": {"content": "4"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 1000, "completion_tokens": 100,
                  "prompt_cache_hit_tokens": 800, "prompt_cache_miss_tokens": 200},
    }

    def _transport(url, headers, payload, timeout):
        return 200, json.dumps(body, ensure_ascii=False)

    gw = G.ModelGateway(G.ModelSpec(api_key="k", max_retries=0), transport=_transport)
    reply = gw.complete("1+1=?", scope="reason")
    assert reply.ok, reply.error_detail
    assert reply.cache_hit_tokens == 800 and reply.cache_miss_tokens == 200, reply.to_dict()
    # 上游不回那两格时是 `None`（不是 0）—— 三态在网关上就成立
    body["usage"] = {"prompt_tokens": 1000, "completion_tokens": 100}
    reply2 = gw.complete("1+1=?", scope="reason")
    assert reply2.cache_hit_tokens is None and reply2.cache_miss_tokens is None, reply2.to_dict()
    assert reply2.to_dict()["cache_hit_tokens"] is None, reply2.to_dict()


def test_the_price_env_override_covers_all_three_tiers():
    """配置面：三档价都能被环境变量覆盖；命中那一档**没有默认值**（未登记就是未登记）。"""
    env = {"AGENTFLOW_MODEL_PRICE_IN_USD_PER_M": "3.0",
           "AGENTFLOW_MODEL_PRICE_OUT_USD_PER_M": "6.0",
           "AGENTFLOW_MODEL_PRICE_IN_HIT_USD_PER_M": "0.5"}
    p = MC.price_from_env(env)
    assert (p.usd_per_m_in, p.usd_per_m_out, p.usd_per_m_in_hit) == (3.0, 6.0, 0.5), p
    assert p.source.startswith("env:"), p.source
    bare = MC.price_from_env({})
    assert bare.usd_per_m_in_hit is None, bare
    assert not bare.hit_price_known and bare.source.startswith("default:"), bare
    # 老调用方（两格口径）不受影响：`price_of` 仍是那两个数
    assert MC.price_of(env={}) == (MC.DEFAULT_PRICE_IN_USD_PER_M, MC.DEFAULT_PRICE_OUT_USD_PER_M)
    assert set(MC.price_of_full().to_dict()) == {"usd_per_m_in", "usd_per_m_out",
                                                 "usd_per_m_in_hit"}

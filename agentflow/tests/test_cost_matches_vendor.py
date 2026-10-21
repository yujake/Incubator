# -*- coding: utf-8 -*-
"""花销口径与供应商定价对齐：三档 token（命中 / 未命中 / 输出）各有其价。

业主 2026-10-14：「将花销计算标准调整到与模型供应商定价吻合」。治的口径缺口：改前我们只记两个
token 数（`tokens_in` / `tokens_out`）与两格价，而供应商的账单价目表按三种 token 分开登：命中缓存的
输入、未命中缓存的输入、输出。于是：上游回的 `prompt_cache_hit_tokens` / `prompt_cache_miss_tokens`
被整格丢掉（`modelgw` 只读 `prompt_tokens` / `completion_tokens`）；记账把所有输入都按"未命中价"算
⇒ 系统性偏高、且偏高得没法核对；"为什么和供应商账单对不上"在读数上无法定位（账上只有一个 `usd`）。

修法：`ModelReply` / `SeamCall` 各加两格（三态：`None` = 上游没报，0 = 明说零命中）、`Price` 加一档
`usd_per_m_in_hit`、`usd_for` 按三档分别乘，`modelcost.billing_reading()` 把"按哪几档算的"留成读数。

三态纪律在这一组的位置："命中价没登记"与"上游没报命中数"都会让 `usd` 偏高 —— 二者都不许静默：
`billing_reading()['cache_tri']` 分别报 `price_unknown` / `not_reported`，而只有两样都在位时才报
`billed`。"""

from __future__ import annotations

import json

from agentflow import modelcost as MC
from agentflow import modelgw as G

#: 一份示例价（不是任何厂商的登记值）—— 判据只关心算术，不关心具体数字。
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
    """三态之一：命中价没登记 ⇒ 全部按未命中价算（偏保守）+ 一条 `price_unknown`。

    这条负控钉的是"不许把不知道写成一个更便宜的数字"：若实现把未登记的命中价
    当成 0，这条断言会当场红（`usd` 会掉到 0.0004）。
    """
    p = MC.Price(usd_per_m_in=1.0, usd_per_m_out=2.0)   # 没有 hit 档
    assert MC.usd_for(_reply(), p) == 0.0012, "未登记命中价时必须按未命中价算（保守）"
    reading = MC.billing_reading(_reply(), p)
    assert reading["cache_tri"] == "price_unknown", reading
    assert reading["usd_per_m_in_hit"] is None, reading


def test_upstream_silence_is_a_third_state_not_a_zero():
    """三态之二：上游没回命中数（`None`）⇒ `not_reported`，且与"明说零命中"分得开。

    注意"零命中"与"上游没报"在金额上可以相等（两种都按未命中价算）——
    这条判据断言的是读数分得开（`cache_tri` 两档 + 命中数那一格 `0` vs `None`），
    以及在真的命中时金额不同（`800×0.25` 而不是 `800×1.0`）。
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
    """配置面：三档价都能被环境变量覆盖；命中那一档没有默认值（未登记就是未登记）。"""
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


# ---------------------------------------------------------------- 厂商价目表（官方定价页）

def _at(hour: int, *, weekday: int = 0) -> "object":
    """造一个 UTC 时刻：`weekday=0` 是周一（2026-10-12 是周一）。"""
    from datetime import datetime, timedelta, timezone

    return datetime(2026, 10, 12, hour, 0, tzinfo=timezone.utc) + timedelta(days=weekday)


def test_the_table_matches_the_vendors_published_numbers():
    """价目表就是官方定价页那六个数（两个模型 × 三档 × 峰谷）。

    口径来源：`https://api-docs.deepseek.com/quick_start/pricing`，抓取于 2026-10-14。
    官方把低谷价定义成峰值价的一半，所以这六个数互相校验：`peak == 2 × off_peak`。
    """
    flash = MC.VENDOR_PRICES["deepseek"]["deepseek-flash"]
    assert flash["hit"] == (0.006, 0.003), flash
    assert flash["in"] == (0.3, 0.15), flash
    assert flash["out"] == (1.2, 0.6), flash
    pro = MC.VENDOR_PRICES["deepseek"]["deepseek-v4-pro"]
    assert pro["hit"] == (0.044, 0.022), pro
    assert pro["in"] == (1.32, 0.66), pro
    assert pro["out"] == (3.96, 1.98), pro
    for row in (flash, pro):
        for tier, (peak, off) in row.items():
            assert abs(peak - 2 * off) < 1e-9, (tier, peak, off)


def test_peak_and_off_peak_are_chosen_by_the_clock():
    """峰谷按官方口径现算：UTC 周一至周五的 01–04 与 06–10 点是峰值，其余（含周末）低谷。

    这一条逐句传 `env={}`：钟是这一格唯一被测的输入。不传就会读到进程环境里
    别人钉的 `AGENTFLOW_MODEL_PEAK` —— 而"别人"可以是另一个测试文件的导入期语句
    （实测 2026-10-14：`test_r5_orchestration_cost` 曾在导入期 setdefault 它，
    于是这条判据在全量跑里红、单跑绿）。判据自己把输入钉死，才谈得上可复现。
    """
    off_clock = {}
    peak = MC.price_for("deepseek", "deepseek-flash", at=_at(2), env=off_clock)
    off = MC.price_for("deepseek", "deepseek-flash", at=_at(12), env=off_clock)
    assert peak[0].usd_per_m_in == 0.3 and peak[1]["peak"] is True, peak
    assert off[0].usd_per_m_in == 0.15 and off[1]["peak"] is False, off
    # 边界：左闭右开 —— 04:00 已出峰值窗，06:00 进第二个窗
    assert MC.is_peak(_at(1)) is True and MC.is_peak(_at(4)) is False, "01–04 是左闭右开"
    assert MC.is_peak(_at(6)) is True and MC.is_peak(_at(10)) is False, "06–10 是左闭右开"
    # 周末整日低谷（官方原文：all other hours are off-peak, including weekends）
    assert MC.is_peak(_at(2, weekday=5)) is False
    assert MC.is_peak(_at(2, weekday=6)) is False


def test_the_two_number_price_also_knows_the_vendor_and_the_clock():
    """`price_of`（两格那个旧口径）也看厂商与峰谷 —— 认得出就按表算。

    为什么这条要单独判（2026-10-14）：`price_of` 此前只读环境变量与缺省价，
    而 `runflow`（`agentflow run` 那条路）用它取价 ⇒ 同一个工作区里，
    多智能体那条按厂商价目表算、单跑那条按缺省价算，两个数字都自洽
    且没有任何地方会报错。业主 ① 要的正是把这一格收成一处。
    """
    from agentflow.modelgw import ModelSpec

    spec = ModelSpec()          # 缺省：vendor 空、端点 api.deepseek.com、模型 deepseek-flash
    at_peak = "2026-01-01T02:00:00+00:00"
    at_off = "2026-01-01T00:00:00+00:00"
    assert MC.price_of(spec, at=at_peak, env={}) == (0.3, 1.2)
    assert MC.price_of(spec, at=at_off, env={}) == (0.15, 0.6)
    # 显式写了厂商就用它（模型名查不到 ⇒ 回落成缺省价，读数里看得出来）
    assert MC.price_of(ModelSpec(vendor="acme", model="x"), at=at_off, env={}) == \
        (MC.DEFAULT_PRICE_IN_USD_PER_M, MC.DEFAULT_PRICE_OUT_USD_PER_M)
    # 认不出厂商 / 不给 spec ⇒ 行为逐字不变（既有调用点不受影响）
    assert MC.price_of(None, env={}) == (MC.DEFAULT_PRICE_IN_USD_PER_M,
                                         MC.DEFAULT_PRICE_OUT_USD_PER_M)
    assert MC.price_of_full(ModelSpec(), at=at_off, env={}).usd_per_m_in_hit == 0.003


def test_the_peak_clock_accepts_an_iso_string():
    """`is_peak` 也收 ISO 串：调用方手上常常只有 `S.now_iso()` 那个串。

    为什么值得有（2026-10-14）：`runflow` 就是拿自己那个时间戳去取价的
    （"这一笔按它发生的那一刻计价"），而它手上那个 `stamp` 是字符串。
    裸 `datetime` 按 UTC 解释 —— 按本机时区解释等于让"这台机器在哪"
    悄悄改变一笔账的价格。
    """
    from datetime import datetime, timezone

    assert MC.is_peak("2026-01-01T02:00:00+00:00") is True        # 周四 02:00 UTC
    assert MC.is_peak("2026-01-01T04:00:00+00:00") is False       # 左闭右开
    assert MC.is_peak("2026-01-01T02:00:00Z") is True              # 尾 Z 也认
    assert MC.is_peak(datetime(2026, 1, 1, 2)) is True             # 裸时间按 UTC
    assert MC.is_peak(datetime(2026, 1, 1, 2, tzinfo=timezone.utc)) is True


def test_an_unregistered_vendor_or_model_falls_back_and_says_so():
    """负控：没登记的组合不猜 —— 回落到缺省价，并把 `price_source=fallback` 记下来。"""
    p, reading = MC.price_for("acme", "whatever", at=_at(12))
    assert reading["price_source"] == "fallback", reading
    assert p.usd_per_m_in == MC.DEFAULT_PRICE_IN_USD_PER_M, p
    assert p.usd_per_m_in_hit is None, p
    # 登记了的组合走表，读数里带厂商与模型（账要对得上供应商的账单）
    p2, r2 = MC.price_for("deepseek", "deepseek-v4-pro", at=_at(12))
    assert r2["price_source"] == "table" and r2["vendor"] == "deepseek", r2
    assert (p2.usd_per_m_in, p2.usd_per_m_out) == (0.66, 1.98), p2


def test_the_env_override_still_beats_the_table():
    """环境变量压在最上面：CI 与既有脚本不许被价目表弄坏。"""
    env = {"AGENTFLOW_MODEL_PRICE_IN_USD_PER_M": "9.0"}
    p, reading = MC.price_for("deepseek", "deepseek-flash", at=_at(12), env=env)
    assert p.usd_per_m_in == 9.0, p
    assert reading["price_source"] == "env", reading


def test_the_ledger_row_note_carries_which_price_tier_was_used():
    """账本那一行自己说得清"这笔钱按哪一档价算的"（不必去翻会话事件）。

    判据打在唯一那处入账口（`LlmSeam._charge_ledger` → `note`）：它抄的是
    `SeamCall.billing` 的四格，所以这条断言同时钉住"billing 真的被算过"。
    """
    from agentflow import llmseam as LS
    from agentflow.modelgw import ModelSpec as _Spec
    from agentflow.tokenmeter import TokenMeter
    from agentflow.store import Store
    import pathlib
    import tempfile

    st = Store(pathlib.Path(tempfile.mkdtemp(prefix="seam-note-")))
    st.init()
    seam = LS.LlmSeam(role="A", session_root=st.root, sid="t",
                      meter=TokenMeter(st, budget_usd=1.0))
    seam.gateway = type("G", (), {"spec": _Spec(api_key="k", model="deepseek-flash",
                                               vendor="deepseek")})()
    reply = _reply(hit=0, miss=1000)
    seam._land(LS.SeamCall(ok=True, text="x", tokens_in=1000, tokens_out=100,
                           usd=seam._usd_of(reply)[0],
                           billing=seam._billing_of(reply)),
               prompt="p", system="", task_id="", note="unit")
    rows = st.rows("usage_ledger")
    assert rows, "这一笔没有入账"
    note = str(rows[0].get("note") or "")
    for needle in ("price=table", "vendor=deepseek", "model=deepseek-flash",
                   "peak=", "cache=billed", "in_hit=", "in=", "out="):
        assert needle in note, (needle, note)


def test_the_seam_bills_the_configured_vendor_model():
    """缝那一层：按这次用的那个模型取价（厂商 + 模型 + 峰谷），并留读数。"""
    from agentflow import llmseam as LS

    seam = LS.LlmSeam(role="A", session_root=".", gateway=None, sid="t")
    seam.gateway = type("G", (), {"spec": G_SPEC})()
    reading = seam._billing_of(_reply(hit=0, miss=1000))
    assert reading["price_source"] == "table", reading
    assert reading["vendor"] == "deepseek" and reading["model"] == "deepseek-flash", reading
    assert reading["peak"] in (True, False), reading
    assert reading["usd_per_m_in"] in (0.15, 0.3), reading


G_SPEC = G.ModelSpec(api_key="k", model="deepseek-flash", vendor="deepseek")

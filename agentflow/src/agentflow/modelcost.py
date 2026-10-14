"""模型花销入账适配器：把 `modelgw.ModelReply` 变成 `usage_ledger` 里的一笔账。

## 为什么需要这一层

`modelgw` 刻意不碰台账（它的 docstring 写明"记账由调用方用既有 `tokenmeter` 做"），
`tokenmeter` 只认 `Charge` 这个记账口径。于是"调了模型"与"花了钱"之间缺一个
把 `ModelReply.tokens_in/tokens_out` 翻译成 `Charge` 的东西 —— 没有它，
每一次真实调用在账面上都不存在，`budget_usd` 也就永远拦不住任何东西。

本模块只做这一件翻译，且只做一次：单价的唯一来源是环境变量，
记账的唯一出口是 `TokenMeter.charge`（不另开一条写 `usage_ledger` 的路，
否则"账本有几份口径"这个问题会立刻回来）。

## 单价从哪来

`AGENTFLOW_MODEL_PRICE_IN_USD_PER_M` / `AGENTFLOW_MODEL_PRICE_OUT_USD_PER_M`
是每百万 token 的美元价。默认值（输入 0.27 / 输出 1.10）是按 DeepSeek 公开价
登记的观测值，会随官方调价而过时 —— 因此它必须能被环境变量覆盖，
而不是被当成事实写死在代码里。价格不是从模型问来的：让模型回答"这次花了多少钱"
就是把可复核的算术换成一次无法复核的生成（`usd_for` 的全部意义是确定性算术）。

## 三态与幂等（本模块的两条纪律）

- `meter=None` ⇒ 明确返回 `charged=False, reason="not_wired"`。绝不假装入账：
  一个"看起来记了账、其实没记"的返回值会让预算熔断永远不触发，
  而账面上一分钱都没有 —— 那是最贵的一种静默失败。
- 同一 `(task_id, call_index)` 重复入账只写一次。入账走
  `TokenMeter.charge_once`，判重与写入在同一次加锁内完成 ——
  键既写在那一行的 `note` 里（跨版本可用的那一层），也写进 `UsageEntry.idem_key`
  字段（表级唯一性断言与 `verify.duplicate_idem_key` 读的那一层）。

## 失败的调用记不记账

记。上游只要真的计了费，账就必须留下。取舍是：

- `reply.not_checked` 为真（`no_key` / `timeout` / `network` / `server_error`）
  ⇒ 这笔调用很可能没花到钱，按上游回的 usage 记（通常就是零值行），
  并带 note（"零值也要记"：否则"没记账"与"花了零"分不开）；
- `auth_failed` / `bad_response` 这类"查过了确实失败" ⇒ 同样按上游回的 usage 记：
  上游确实计了费就记实账，因为那正是"一直重试一直在烧钱"的形态，
  只记一次会让它看起来便宜；
- 上游没回 usage（`tokens_in == tokens_out == 0`）而调用又成功了 ⇒ 记零值行且
  `reason="tokens_missing"`，把这个缺口显式暴露出来，宁可少算也不静默按 0 计价。

## 已知边界（不假装解决）

跨进程的重复扣费已在本层关闭：判重与写入都在 `TokenMeter.charge_once`
的同一次加锁内完成，所以两个进程用同一组 `(task_id, call_index)` 同时入账时，
后到的那个会在锁内看见前一个刚提交的行，返回 `duplicate` 而不是再写一行。

仍然存在的边界（性质与上面那条不同，是表达力而不是竞态）：

- 幂等键是两层同时承载的：`note` 里一个文本 token（跨版本可用，但判重是
  "扫全表 + 拆 token"，且别的写入方理论上能写出同形 token），以及
  `UsageEntry.idem_key` 字段（`schema.validate_table` 对非空该字段断言整表唯一，
  `verify` 的 `duplicate_idem_key` 复查）。字段层的洞是混合版本窗口：
  未升级进程写下的行不带这个键，在滚动升级期间它逃过字段级唯一性
  （`docs/SCHEMA-MIGRATION-PROPOSAL-usage-ledger-idem-key.md` §3.3）。
  另外字段会被回滚后的 `rebuild` 静默丢掉，`note` 标记不会 —— 这正是两层都要留的理由。
- `charge_reply` 里的快速通道（`_find_by_marker`，无锁）只用于省一次抢锁，
  不承担正确性责任；把它当成判据就会把这个窗口重新引回来。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Mapping

from .schema import USAGE_SCOPES
from .tokenmeter import Charge, TokenMeter, marker_of, row_with_idem_key

__all__ = [
    "DEFAULT_PRICE_IN_USD_PER_M",
    "DEFAULT_PRICE_OUT_USD_PER_M",
    "ENV_PRICE_IN",
    "ENV_PRICE_OUT",
    "ENV_PRICE_IN_HIT",
    "PEAK_HOURS_UTC",
    "VENDOR_PRICES",
    "ENV_PEAK",
    "peak_override",
    "DEFAULT_ROLE",
    "Price",
    "is_peak",
    "price_for",
    "price_of",
    "price_of_full",
    "price_from_env",
    "usd_for",
    "billing_reading",
    "idempotency_key",
    "settle_key",
    "charge_reply",
]

#: 每百万输入 token 的美元价。**DeepSeek 官方定价页的观测值**（抓取时刻见下），
#: 调价后请用环境变量覆盖，或把新数补进 :data:`VENDOR_PRICES`。
#:
#: 2026-10-14 抓 `https://api-docs.deepseek.com/quick_start/pricing`（英文页）：
#: 官方把输入拆成 **cache hit / cache miss** 两档，且**峰谷两价**（低谷 = 峰值的一半），
#: 所以"一个数"只能是最保守的那一档。这里的缺省取 `deepseek-flash` 的**低谷**价
#: （$0.15 / $0.6）—— 真正该走的是 :func:`price_for`（按厂商 × 模型 × 峰谷取）。
DEFAULT_PRICE_IN_USD_PER_M = 0.15
#: 每百万输出 token 的美元价。同上（`deepseek-flash` 低谷）。
DEFAULT_PRICE_OUT_USD_PER_M = 0.6

#: **厂商 × 模型 × 峰谷**的价目表（业主 2026-10-14：「花销计算标准与供应商定价吻合」）。
#:
#: 口径来源逐字：`https://api-docs.deepseek.com/quick_start/pricing`，抓取于 2026-10-14。
#: 单位是**每百万 token 的美元**，形状 `{键: {"hit"/"in"/"out": (peak, off_peak)}}`：
#:
#: | 模型 | 输入(命中) | 输入(未命中) | 输出 |
#: |---|---|---|---|
#: | `deepseek-flash` | 0.006 / 0.003 | 0.3 / 0.15 | 1.2 / 0.6 |
#: | `deepseek-v4-pro` | 0.044 / 0.022 | 1.32 / 0.66 | 3.96 / 1.98 |
#:
#: 峰谷按官方页面的原文判定：**峰值时段 = UTC 周一至周五的 01:00–04:00 与 06:00–10:00**
#: （不含中国法定节假日），其余时段（含周末与节假日整日）都是低谷；低谷价 = 峰值价的一半。
#: 我们按调用发生的时刻现算（见 :func:`is_peak`），并把用了哪一档写进计价读数 ——
#: 否则"账单对不上"这件事又变成没法定位的。
#:
#: 没登记的组合**不猜**：回落到 `DEFAULT_PRICE_*` 并在读数里标 `price_fallback`。
VENDOR_PRICES: dict[str, dict[str, dict[str, tuple[float, float]]]] = {
    "deepseek": {
        "deepseek-flash": {"hit": (0.006, 0.003), "in": (0.3, 0.15), "out": (1.2, 0.6)},
        "deepseek-v4-pro": {"hit": (0.044, 0.022), "in": (1.32, 0.66), "out": (3.96, 1.98)},
    },
}

#: 峰值时段的 UTC 小时区间（左闭右开），官方原文：`01:00 - 04:00 and 06:00 - 10:00 UTC,
#: Monday through Friday, excluding Chinese public holidays`。
PEAK_HOURS_UTC: tuple[tuple[int, int], ...] = ((1, 4), (6, 10))
#: 峰谷判定的显式覆盖：`1`/`0`（认得的真假写法同 `settings`）。
#:
#: 为什么要有它：峰谷判据读的是**墙钟**，于是同一份判据在不同时刻会算出两个不同的
#: 数（差一倍）—— 那让"花销"这件事在判据里不可复现。真机当然按钟走；判据与
#: 离线复算用这一格把它钉住（也顺手给运维一个"按谷价批账"的显式开关）。
ENV_PEAK = "AGENTFLOW_MODEL_PEAK"
_TRUE_WORDS: tuple[str, ...] = ("1", "true", "yes", "on")
_FALSE_WORDS: tuple[str, ...] = ("0", "false", "no", "off")


def peak_override(env: Mapping[str, str] | None = None) -> bool | None:
    """`AGENTFLOW_MODEL_PEAK` 给的显式峰谷判定；没给/读不懂 ⇒ `None`（按钟现算）。"""
    src = dict(os.environ if env is None else env)
    raw = str(src.get(ENV_PEAK) or "").strip().lower()
    if raw in _TRUE_WORDS:
        return True
    if raw in _FALSE_WORDS:
        return False
    return None

ENV_PRICE_IN = "AGENTFLOW_MODEL_PRICE_IN_USD_PER_M"
ENV_PRICE_OUT = "AGENTFLOW_MODEL_PRICE_OUT_USD_PER_M"
#: 命中缓存那一档的输入价（每百万 token 美元）。**故意没有默认值**：
#: 这一档的价是供应商价目表上的一个具体数字，没登记就按未命中价算并留痕，
#: 不许由一个"看起来差不多"的数字顶上（业主 2026-10-14：口径要与供应商定价吻合）。
ENV_PRICE_IN_HIT = "AGENTFLOW_MODEL_PRICE_IN_HIT_USD_PER_M"

#: 记账时的角色名。这一层只调模型、不扮演编排角色，所以默认登记为 modelgw
#: 而不是硬塞一个 A–H 里的字母：冒名会让 `by_role()` 的归口统计说谎。
DEFAULT_ROLE = "modelgw"

_PER_M = 1_000_000.0


@dataclass(frozen=True)
class Price:
    """一档单价（每百万 token 的美元价）。负价直接拒绝。

    ## 为什么是三格而不是两格（业主 2026-10-14：「花销计算标准与供应商定价吻合」）

    供应商的价目表按**三种 token** 分开登：命中缓存的输入、未命中缓存的输入、输出。
    我们此前只记两格（`in` / `out`），于是"命中缓存的那部分按未命中价算"——
    系统性偏高，而且偏得没法核对（供应商账单上那三档是分开列的）。

    `usd_per_m_in_hit` 的三态：`None` = **我们不知道这一档的价**（不是 0）。
    未知时按未命中价计（偏保守），并在 `source` 里如实标出来 —— 宁可算贵，
    也不许把"我不知道"写成一个更便宜的数字。
    """

    usd_per_m_in: float
    usd_per_m_out: float
    #: 命中缓存的输入价（每百万 token 美元）；`None` = 未登记（按未命中价算并留痕）。
    usd_per_m_in_hit: float | None = None
    #: 这份价是从哪来的（`env:…` / `default:…`）。由 `price_from_env` 在构造时写死 ——
    #: 不能在属性里现读 `os.environ`：那样"用哪份 env 算的价"与"报出来的来源"
    #: 会是两个东西（判据 `test_cost_matches_vendor` 当场抓到过这一格）。
    source_note: str = ""

    def __post_init__(self) -> None:
        for name, value in (("usd_per_m_in", self.usd_per_m_in),
                            ("usd_per_m_out", self.usd_per_m_out),
                            ("usd_per_m_in_hit", self.usd_per_m_in_hit)):
            if value is not None and value < 0:
                raise ValueError(
                    f"单价不能为负（{name}={value}）—— 负价会让'花了多少'这个数字失去意义"
                )

    def to_dict(self) -> dict[str, float | None]:
        """落盘用的扁平结构（`cost.json` 与清单都引用它）。"""
        return {
            "usd_per_m_in": self.usd_per_m_in,
            "usd_per_m_out": self.usd_per_m_out,
            "usd_per_m_in_hit": self.usd_per_m_in_hit,
        }

    @property
    def hit_price_known(self) -> bool:
        """命中缓存那一档的价**知不知道**（三态的那一格）。"""
        return self.usd_per_m_in_hit is not None

    @property
    def source(self) -> str:
        """这份价是环境变量给的还是默认观测值？写进产物里，便于日后复核。"""
        return self.source_note or "default:deepseek-public-observed"


def _float_env(env: Mapping[str, str], name: str, default: float) -> float:
    """读一个浮点环境变量；读不出来就用默认值（不静默改成 0，那会变成免费）。"""
    raw = str(env.get(name) or "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _float_env_opt(env: Mapping[str, str], name: str) -> float | None:
    """读一个**可缺**的浮点环境变量：没给就是 `None`（"未登记"，不是 0）。"""
    raw = str(env.get(name) or "").strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def price_from_env(env: Mapping[str, str] | None = None) -> Price:
    """从环境变量读单价；三个变量都可单独缺省。"""
    src = dict(os.environ if env is None else env)
    named = [k for k in (ENV_PRICE_IN, ENV_PRICE_OUT, ENV_PRICE_IN_HIT)
             if str(src.get(k) or "").strip()]
    return Price(
        usd_per_m_in=_float_env(src, ENV_PRICE_IN, DEFAULT_PRICE_IN_USD_PER_M),
        usd_per_m_out=_float_env(src, ENV_PRICE_OUT, DEFAULT_PRICE_OUT_USD_PER_M),
        usd_per_m_in_hit=_float_env_opt(src, ENV_PRICE_IN_HIT),
        # 来源按**这一份 env** 记（不是按进程环境现读）—— 见 `Price.source_note`。
        source_note=(f"env:{'/'.join(named)}" if named else ""),
    )


def price_of(spec: Any = None, *, env: Mapping[str, str] | None = None) -> tuple[float, float]:
    """一次调用该按什么价算 ⇒ `(输入价, 输出价)`，单位是美元每百万 token。

    ⚠️ 这是**两格**的那个旧口径（未命中输入 / 输出），保留给"只想要两个数"的调用方
    （`runflow` 的清单、`cost.json`）。要用上缓存命中那一档，请用
    :func:`price_of_full` —— 它返回完整的 :class:`Price`（三格 + `source`）。

    真正的按厂商/模型分档表需要一个数据源，而"从模型问价"是错的方向（见模块 docstring）：
    今天的价目表就是"默认观测值 + 环境变量覆盖"，`spec` 参数留着是因为调用方手上总有它，
    而"价格与配置同源"这件事在接口上应当看得见。
    """
    p = price_from_env(env)
    return (p.usd_per_m_in, p.usd_per_m_out)


def price_of_full(spec: Any = None, *, env: Mapping[str, str] | None = None) -> Price:
    """完整的那一档价（三格 + 来源）—— 记账时用这个，不要用 `price_of` 的两格。"""
    return price_from_env(env)


def is_peak(at: Any = None) -> bool:
    """这次调用落在**峰值时段**吗（官方口径：UTC 周一至周五的 01–04 与 06–10 点）。

    `at` 收一个带时区的 `datetime`；不给就用"现在"（UTC）。周末整日低谷；
    中国法定节假日官方页面说"整日低谷"，我们**没有节假日表**，所以那一档如实不判
    （见 :func:`price_for` 的读数：`holiday_table=False`）——不假装知道。
    """
    from datetime import datetime, timezone

    now = at if at is not None else datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    now = now.astimezone(timezone.utc)
    if now.weekday() >= 5:      # 5/6 = 周六/周日
        return False
    return any(start <= now.hour < end for start, end in PEAK_HOURS_UTC)


def price_for(vendor: str = "", model: str = "", *, at: Any = None,
              env: Mapping[str, str] | None = None) -> tuple[Price, dict[str, Any]]:
    """按**厂商 × 模型 × 峰谷**取价；返回 `(Price, 读数)`。

    读数（进 `billing_reading` 与账本 note）回答四件事：用了哪一档（`peak`）、
    价格是从价目表还是回落来的（`price_source`）、有没有命中价（`hit_price_known`）、
    以及我们**没有**节假日表这一条（`holiday_table=False`）——
    最后一条是"低谷判定可能偏严（把节假日算成峰值）"的如实交代，不是缺陷掩盖。

    环境变量仍然压在最上面（`price_from_env`）：CI 与既有脚本不许被这次改动弄坏。
    """
    src = dict(os.environ if env is None else env)
    overridden = any(str(src.get(k) or "").strip()
                     for k in (ENV_PRICE_IN, ENV_PRICE_OUT, ENV_PRICE_IN_HIT))
    pinned = peak_override(env)
    peak = is_peak(at) if pinned is None else pinned
    table = VENDOR_PRICES.get(str(vendor or "").strip().lower(), {})
    row = table.get(str(model or "").strip())
    if overridden or row is None:
        p = price_from_env(env)
        return p, {
            "peak": peak,
            "peak_source": ("env" if pinned is not None else "clock"),
            "price_source": ("env" if overridden else "fallback"),
            "vendor": str(vendor or ""),
            "model": str(model or ""),
            "hit_price_known": p.hit_price_known,
            "holiday_table": False,
        }
    idx = 0 if peak else 1
    p = Price(usd_per_m_in=row["in"][idx], usd_per_m_out=row["out"][idx],
              usd_per_m_in_hit=row["hit"][idx],
              source_note=f"table:deepseek-public-2026-10-14/{'peak' if peak else 'off_peak'}")
    return p, {
        "peak": peak,
        "peak_source": ("env" if pinned is not None else "clock"),
        "price_source": "table",
        "vendor": str(vendor or ""),
        "model": str(model or ""),
        "hit_price_known": True,
        "holiday_table": False,
    }


def usd_for(reply: Any, price: tuple[float, float] | Price) -> float:
    """这一笔调用花了多少美元（含重试的总额）—— 确定性算术。

    ## 口径：这是总额，不是单次价

    `attempts` 在这里就乘进去了（`04-…md` §B6：每次重试都是另一次计费请求）。
    只按最后一次的 usage 算钱，会把"重试三次才成功"记成与"一次就成功"同价 ——
    而那正是最该被看见的浪费。

    注意它与 `tokenmeter.Charge.usd` 同名不同口径：`Charge.usd` 是单次价
    （`Charge.usd_total = usd × attempts`）。`charge_reply` 负责这个换算，
    别把本函数的返回值直接塞进 `Charge.usd` —— 那会让重试被乘两遍。

    ## 为什么不是精确的

    上游只给 token 数，单价是每百万的近似值，所以结果按 6 位小数收口
    （与 UsageEntry.usd 的存储精度一致，避免"账上一个数、汇总里另一个数"
    这种对不上的假不一致）。

    ## 三档 token（业主 2026-10-14：「花销计算标准与供应商定价吻合」）

    上游回 `prompt_cache_hit_tokens` / `prompt_cache_miss_tokens` 时，输入那一块按
    **两档价**分别算：命中部分用 `usd_per_m_in_hit`，未命中部分用 `usd_per_m_in`。
    上游没回这两格（`None`）⇒ 全部按未命中价算（保守），并在
    :func:`billing_reading` 里留一条读数，免得"我们不知道"被读成"没有这回事"。
    """
    p = price if isinstance(price, Price) else Price(price[0], price[1])
    tokens_in = int(getattr(reply, "tokens_in", 0) or 0)
    tokens_out = int(getattr(reply, "tokens_out", 0) or 0)
    hit = getattr(reply, "cache_hit_tokens", None)
    miss = getattr(reply, "cache_miss_tokens", None)
    if p.hit_price_known and hit is not None:
        hit_tokens = max(0, min(int(hit), tokens_in))
        miss_tokens = tokens_in - hit_tokens
    else:
        # 要么这一档价没登记，要么上游没报命中数 —— 两种都按未命中价算（偏保守）。
        hit_tokens, miss_tokens = 0, tokens_in
    per_call = (
        hit_tokens * float(p.usd_per_m_in_hit or 0.0)
        + miss_tokens * p.usd_per_m_in
        + tokens_out * p.usd_per_m_out
    ) / _PER_M
    attempts = max(1, int(getattr(reply, "attempts", 1) or 1))
    return round(per_call * attempts, 6)


def billing_reading(reply: Any, price: tuple[float, float] | Price) -> dict[str, Any]:
    """这一笔的**计价读数**：用了哪几档价、命中多少、有没有"我们不知道"的格子。

    它存在的理由（三态纪律）：`usd` 只是一个数，而"这个数是怎么来的"必须能复核 ——
    尤其是"命中缓存的价没登记"与"上游没回命中数"这两种情形，它们都会让
    `usd` 偏高，而偏高如果不留痕，读账的人只会以为供应商算错了。
    """
    p = price if isinstance(price, Price) else Price(price[0], price[1])
    tokens_in = int(getattr(reply, "tokens_in", 0) or 0)
    hit = getattr(reply, "cache_hit_tokens", None)
    miss = getattr(reply, "cache_miss_tokens", None)
    if hit is None and miss is None:
        cache_tri = "not_reported"
    elif not p.hit_price_known:
        cache_tri = "price_unknown"
    else:
        cache_tri = "billed"
    return {
        "tokens_in": tokens_in,
        "tokens_out": int(getattr(reply, "tokens_out", 0) or 0),
        "cache_hit_tokens": hit,
        "cache_miss_tokens": miss,
        "usd_per_m_in": p.usd_per_m_in,
        "usd_per_m_in_hit": p.usd_per_m_in_hit,
        "usd_per_m_out": p.usd_per_m_out,
        "cache_tri": cache_tri,
        "price_source": p.source,
        "usd": usd_for(reply, p),
    }


def idempotency_key(task_id: str, call_index: int) -> str:
    """`(task_id, call_index)` 的稳定压缩键（写进那一行的 `note`，重放时查它）。

    为什么压缩而不是原样拼接：`task_id` 里可能带 `#`、空格与冒号，
    原样拼出来的标记会与 note 里别的内容互相干扰；摘要串只有十六进制字符，
    既能当标记用，又不会把 note 变成不可读的机器串。

    实现在 `tokenmeter.marker_of`（一处定义）：两处各写一份的话，
    同一个 `(task_id, call_index)` 会在两个地方算出不同的键 ——
    而那正是"同一判据两处实现"的老毛病。

    本模块是所有幂等键的唯一生成处：另一条写入方（`conductor` 的召唤级结算）
    用的 :func:`settle_key` 也在这里。这样"键长什么样"只有一份定义。
    """
    return marker_of("idem", task_id, int(call_index))


def settle_key(task_id: str) -> str:
    """召唤级结算（`conductor._charge_and_settle`）的幂等键。

    ## 为什么它不叫 `idempotency_key(task_id, 0)`

    那样算出来的键会与 `charge_reply(..., call_index=0)` 在同一个 `task_id`
    上逐位相同。两条写入方撞键的后果不是报错，而是后到的那一笔被静默判成
    `duplicate` —— 一笔真实花销凭空消失，而账面上一切都自洽。
    召唤级结算是"整条任务的汇总"，模型调用级是"第 i 次调用"，它们是两件事，
    所以键的命名空间也不同（`settle-` / `idem-`）。
    这个区分不是风格：`scripts/usage_ledger_audit.py` 的 `MARKER_RE`
    与 `tests/test_usage_ledger_idempotency_mp.py` 都按前缀区分它们。
    """
    return marker_of("settle", task_id)


def _ledger_rows(meter: Any) -> list[dict]:
    """读账本行。读不出来时返回空列表是错误的（那会把"没查成"折叠成"没这笔账"），
    所以这里不吞异常：`meter.store` 坏了就必须往上抛，让调用方看见。"""
    store = getattr(meter, "store", None)
    if store is None:
        raise AttributeError("meter 没有 store ⇒ 无法读账本，本次不能判定幂等（不许猜）")
    return list(store.rows("usage_ledger"))


def _find_by_marker(meter: Any, key: str) -> dict | None:
    """按幂等标记找那笔已入账的行；找不到返回 None（"没有"与"读不到"不同，
    读不到会抛异常，见 `_ledger_rows`）。

    这是一次无锁快照读，它只用来走一条便宜的快速通道（"明显是重放"时
    不必去抢锁）。它不是幂等的权威判据 —— 权威判据在
    `TokenMeter.charge_once` 的锁内比对。把这里当成权威，
    就等于把"先读账再写账"那个窗口重新引回来。
    """
    return row_with_idem_key(_ledger_rows(meter), key)


def _tokens_missing(reply: Any) -> bool:
    """上游回了个成功但不带 usage —— 那笔账只能记零，且必须显式说出来。"""
    return (
        bool(getattr(reply, "ok", False))
        and int(getattr(reply, "tokens_in", 0) or 0) == 0
        and int(getattr(reply, "tokens_out", 0) or 0) == 0
    )


def _charge_note(reply: Any, *, call_index: int, extra_note: str) -> str:
    """那一行的 `note`：给人读的业务说明。

    幂等键不在这里拼（曾经在这里，用 `；` 接在末尾）：键由
    `TokenMeter.charge_once` 统一追加。理由是键必须与"判重"在同一处构造 ——
    两处各拼一次的话，将来只改一处就会写出"判重按 A、落盘按 B"的行，
    而那会让同一笔账被记两次且没有任何检查会响。
    """
    kind = "ok" if bool(getattr(reply, "ok", False)) else str(getattr(reply, "error_kind", "") or "unknown")
    bits = [f"modelgw;call_index={int(call_index)};outcome={kind}"]
    if not bool(getattr(reply, "ok", False)):
        bits.append("not_checked=1" if bool(getattr(reply, "not_checked", False)) else "not_checked=0")
    if _tokens_missing(reply):
        bits.append("上游未回 usage ⇒ 本次只能按零记（不是真花了零）")
    if extra_note.strip():
        bits.append(extra_note.strip())
    return "；".join(bits)


def charge_reply(meter: TokenMeter | None, reply: Any, *, role: str = DEFAULT_ROLE,
                 task_id: str, scope: str, extra_note: str = "",
                 call_index: int = 0, price: tuple[float, float] | None = None,
                 now: str | None = None, idem_scope: str | None = None) -> dict:
    """把一次模型调用的花销经 `TokenMeter` 写进 `usage_ledger`，并如实报告结局。

    返回 `{"charged", "usage_id", "tokens_in", "tokens_out", "usd", "reason", "scope"}`。

    ## 七个键在四条分支上恒在场（`R5-AN-2`）

    这个返回值有四个出口（`meter=None` 的未接线、无锁快速通道判重放、写入竞态
    判重放、真的入账），它们必须给出同形的 dict：调用方按 `d["scope"]` 取值
    时，四种结局不该有两种行为。此前那个无锁快速通道的 duplicate 分支漏了
    `scope`（另外三支都有），于是重放路径上 `cost.json` 的 `per_call[].scope`
    静默变成空串 —— 而 G-20 的承诺是"逐笔看得见归口，汇总才对得上账"。
    `runflow` 自己用 `.get(...) or ""` 兜住了，别的调用方不一定。
    重放那一笔的 `scope` 就是账本里 `prior` 行的那一列：判重放的是账本，
    归口也该从账本读，不能拿本次调用点的实参去覆盖历史事实。

    ## `scope` 是必填的（G-20）

    它回答"这笔钱是为了什么"，取值只能在 `schema.USAGE_SCOPES` 里。没有缺省值：
    缺省值曾是 `"reason"`，于是每一个忘记传 scope 的调用点都静默落进"推理"档 ——
    账本的总额与条目数完全自洽，而"搜索/抽取/审校各花了多少"这个问题永远答不出来
    （这就是 G-20 登记的形态：`USAGE_SCOPES` 五档全无产出）。
    缺省也不许是 `"other"`：那会把"有人忘了写"伪装成一个正常的分类。

    如果 `reply` 自己带着 `scope`（`modelgw.ModelReply` 是），两者必须一致 ——
    不一致时抛 `ValueError`。为什么要在意：网关声明了"这次是 extract"、
    账本记成"review"，两个数字都自洽而互相矛盾，且没有任何地方会报错；
    把它变成当场报错，是唯一能保住"台账那一列可信"的做法。

    三种结局各有各的 `reason`，绝不折叠：

    - `not_wired`：没给 `meter` ⇒ 没有入账（不是"记了一笔零"，更不是"免费"）；
    - `reply.error_kind`（如 `no_key` / `auth_failed`）：调用本身没成，
      按上游回的 usage 记（失败不等于免费），`reason` 说的仍是调用为什么没成；
    - `charged` / `duplicate` / `tokens_missing`：入了账，以及它是怎么入的。

    ## 返回的 `usd` 与账本上的 `usd` 是同一口径（总额，含重试）

    `usd_for` 给的是这一笔账的总额（已含重试），`Charge.usd` 要的是单次价
    （`Charge.usd_total` 会自己乘 `attempts` —— 这是 `tokenmeter` 已经定下的口径，
    这里不去造第二份）。两者同名不同口径，是本项目实测踩过的坑，所以这里：
    把 `usd_for(...) / attempts` 交给 `Charge`，把 `usd_for(...)` 返回给调用方。
    把一个总额当成单次价传进去，会让重试被乘两遍，账面静默翻倍。

    `price` 缺省时读环境变量；`now` 只为测试注入固定时间戳（不注入就是当前时间）。

    ## `idem_scope`：幂等键的命名空间可以与 `task_id` 不同（`P-17` × `G-2`）

    `task_id` 是审计挂点（`usage_ledger.task_id` 要指得到 `tasks` 表的实体行，
    `verify` 有 `dangling_usage_task` 检查），所以它必须服从 `schema` 的 `t-NNNN`
    契约、每一跑都是新号。而"是不是同一笔账"要按运行标识判：同一秒同一主题的
    第二跑必须算出同一个键才判得成 `duplicate`（`test_cli_run.py:437`）。

    把两件事挤进同一个字符串，结果只有两种：要么 task_id 违反契约（写入被拒、
    静默不落库），要么第二跑换了 task_id 而重复扣费。所以这里多一个可选参数：
    给了 `idem_scope` 就只用它算键，`task_id` 照旧写进行里；不给就退回旧口径
    （键按 `task_id` 算），既有调用点行为不变。
    """
    if scope not in USAGE_SCOPES:
        raise ValueError(
            f"scope 必须是 {USAGE_SCOPES} 之一，收到 {scope!r} —— "
            "它是这笔花销的用途归口；缺省值/兜底值会让忘记传的调用点静默落档，"
            "而账本仍然完全自洽"
        )
    reply_scope = str(getattr(reply, "scope", "") or "").strip()
    if reply_scope and reply_scope != scope:
        raise ValueError(
            f"reply 声明的 scope 是 {reply_scope!r}，入账时给的是 {scope!r} ⇒ "
            "同一次调用在两处有两个归口，两个数字都会自洽而互相矛盾。"
            "请让调用点只声明一次（`modelgw.complete(..., scope=...)`），"
            "入账处用同一个值"
        )
    if meter is None:
        return {
            "charged": False,
            "usage_id": "",
            "tokens_in": 0,
            "tokens_out": 0,
            "usd": 0.0,
            "reason": "not_wired",
            "scope": scope,
        }

    key = idempotency_key(idem_scope or task_id, call_index)
    prior = _find_by_marker(meter, key)
    if prior is not None:
        return {
            "charged": False,
            "usage_id": str(prior.get("usage_id") or ""),
            "tokens_in": int(prior.get("tokens_in") or 0),
            "tokens_out": int(prior.get("tokens_out") or 0),
            "usd": float(prior.get("usd") or 0.0),
            "reason": "duplicate",
            # `R5-AN-2`：这一支此前没有 `scope`，于是重放路径上逐笔的归口是空串。
            # 取 `prior` 行的值（判重放的是账本，归口也以账本为准）；
            # `prior` 行理论上可能没有这一列（手工写的行），那时退回本次实参
            # —— 实参已经过 `USAGE_SCOPES` 校验，不会是空串。
            "scope": str(prior.get("scope") or scope),
        }

    ok = bool(getattr(reply, "ok", False))
    attempts = max(1, int(getattr(reply, "attempts", 1) or 1))
    missing = _tokens_missing(reply)
    # 按上游回的 usage 记钱 —— 成功与失败是同一个口径：上游回了 usage 就说明
    # 这次请求在它那边是计费的（失败不等于免费）。真正的零值只有一种来源：
    # 上游一个 token 都没回。
    #
    # 口径陷阱（实测踩过一次，记在这里）：`Charge.usd` 要的是单次尝试的价，
    # 因为 `Charge.usd_total` 会自己乘 `attempts`；而 `usd_for` 返回的是含重试的
    # 总额。把 `usd_for` 的结果直接当 `Charge.usd` 传进去，会让重试被乘两遍：
    # 实测 1000+1000 token、attempts=2 时账上写成 0.00548（应为 0.00274），
    # 同时 `tasks.tokens` 那类派生值也跟着虚高。所以这里显式除回去。
    usd_total = 0.0 if missing else usd_for(reply, price if price is not None else price_of())
    usd_per_attempt = round(usd_total / attempts, 9)
    usd = usd_total
    note = _charge_note(reply, call_index=call_index, extra_note=extra_note)

    # 零值也要记：账上"没有这一行"与"这一行是零"是两件不同的事，
    # 而 `Charge` 只在"零值且无 note"时才拒绝 —— 这里永远给了 note。
    tokens_in = int(getattr(reply, "tokens_in", 0) or 0)
    tokens_out = int(getattr(reply, "tokens_out", 0) or 0)

    once = getattr(meter, "charge_once", None)
    if once is None:
        # fail-closed：只实现 `charge` 的 meter 无法保证跨进程幂等。
        # 静默退化成 `charge` 会把"并发重复扣费"重新引回来，而账面上一切自洽。
        raise TypeError(
            f"{type(meter).__name__} 没有实现 `charge_once`（账本层幂等入账）—— "
            "只实现 `charge` 的 meter 无法保证同一幂等键只落一条账"
        )
    outcome = once(
        Charge(
            role=role,
            scope=scope,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            usd=usd_per_attempt,
            attempts=attempts,
            task_id=task_id,
            note=note,
        ),
        idem_key=key,
        now=now,
    )
    if not outcome["recorded"]:
        # 竞态的另一半：快速通道漏掉了（另一个进程是在本次无锁读之后才提交的），
        # 而锁内的权威判据抓到了它。这是正常结局，返回幂等结果而不是错误。
        prior = outcome["row"]
        return {
            "charged": False,
            "usage_id": str(prior.get("usage_id") or ""),
            "tokens_in": int(prior.get("tokens_in") or 0),
            "tokens_out": int(prior.get("tokens_out") or 0),
            "usd": float(prior.get("usd") or 0.0),
            "reason": "duplicate",
            # 与上面那条无锁快速通道同一口径（`R5-AN-2`）：归口以账本那一行为准，
            # 那一行缺列时才退回本次实参。
            "scope": str(prior.get("scope") or scope),
        }
    if not ok:
        reason = str(getattr(reply, "error_kind", "") or "unknown")
    elif missing:
        reason = "tokens_missing"
    else:
        reason = "charged"

    return {
        "charged": True,
        "usage_id": outcome["usage_id"],
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "usd": usd,
        "reason": reason,
        "scope": scope,
    }


# ---------------------------------------------------------------------- 自检


def _fake_reply(**kw: Any) -> Any:
    """造一个和 `modelgw.ModelReply` 同形的对象（自检与测试共用，避免真连网）。"""
    from .modelgw import ModelReply

    return ModelReply(**kw)


def selftest() -> int:
    """离线自检：`meter=None` 的三态、一次成功入账、以及幂等。

    为什么要有它：这一层"看起来记了账"与"真的记了账"在返回值上只差一个布尔，
    而那正是最容易被读错的地方 —— 用一条独立的自检把它钉住。
    """
    import tempfile
    from pathlib import Path

    from .store import Store

    problems: list[str] = []

    stuck = charge_reply(None, _fake_reply(ok=True, tokens_in=10, tokens_out=5), task_id="t0",
                         scope="reason")
    if stuck["charged"] or stuck["reason"] != "not_wired":
        problems.append(f"meter=None 时必须 not_wired 且不入账：{stuck}")

    with tempfile.TemporaryDirectory() as td:
        st = Store(Path(td) / "ws")
        st.init()
        meter = TokenMeter(st, budget_usd=1.0)
        r = _fake_reply(ok=True, tokens_in=1_000_000, tokens_out=1_000_000, attempts=1)
        first = charge_reply(meter, r, task_id="t1", call_index=0, scope="reason")
        again = charge_reply(meter, r, task_id="t1", call_index=0, scope="reason")
        rows = st.rows("usage_ledger")
        if len(rows) != 1:
            problems.append(f"重复入账必须只写一行，实际 {len(rows)} 行")
        if rows and str(rows[0].get("scope")) != "reason":
            problems.append(f"scope 必须如实落账：{rows[0].get('scope')!r}")
        by_scope = meter.by_scope()
        if by_scope["reason"]["entries"] != 1:
            problems.append(f"by_scope 必须看得见这一档：{by_scope['reason']}")
        if by_scope["search"]["entries"] != 0:
            problems.append("没花过钱的档必须以零值出现，而不是缺席")
        if again["reason"] != "duplicate":
            problems.append(f"第二次入账应当是 duplicate：{again}")
        want = DEFAULT_PRICE_IN_USD_PER_M + DEFAULT_PRICE_OUT_USD_PER_M
        if abs(first["usd"] - want) > 1e-9:
            problems.append(f"一百万一进一百万出的价应当是 {want}：{first}")
        third = charge_reply(meter, r, task_id="t1", call_index=1, scope="search")
        if third["reason"] != "charged":
            problems.append(f"换了 call_index 就是另一笔：{third}")
        if meter.by_scope()["search"]["entries"] != 1:
            problems.append("第二笔落在 search 档 ⇒ 那一档必须非零")
        if meter.spent()["tokens"] != 2 * 2_000_000:
            problems.append(
                f"总额不许因为换档而变化（重放那一笔不入账）：{meter.spent()}"
            )

    for p in problems:
        print(f"  [FAIL] {p}")
    print(f"[modelcost] 自检：未接线={stuck['reason']} / 首次={first['reason']} "
          f"/ 重放={again['reason']} / 新序号={third['reason']}")
    if problems:
        return 1
    print("[modelcost] 三态与幂等都对")
    return 0


def cost_main(argv: Any = None) -> int:
    """入口：目前只有自检。刻意不叫 `main`（`cli.main` 才是对外的唯一命令入口）。"""
    return selftest()


if __name__ == "__main__":
    raise SystemExit(cost_main())

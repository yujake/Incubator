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

from .tokenmeter import Charge, TokenMeter, marker_of, row_with_idem_key

__all__ = [
    "DEFAULT_PRICE_IN_USD_PER_M",
    "DEFAULT_PRICE_OUT_USD_PER_M",
    "ENV_PRICE_IN",
    "ENV_PRICE_OUT",
    "DEFAULT_ROLE",
    "Price",
    "price_of",
    "usd_for",
    "idempotency_key",
    "settle_key",
    "price_from_env",
    "charge_reply",
]

#: 每百万输入 token 的美元价。DeepSeek 公开价的观测值；调价后请用环境变量覆盖。
DEFAULT_PRICE_IN_USD_PER_M = 0.27
#: 每百万输出 token 的美元价。同上。
DEFAULT_PRICE_OUT_USD_PER_M = 1.10

ENV_PRICE_IN = "AGENTFLOW_MODEL_PRICE_IN_USD_PER_M"
ENV_PRICE_OUT = "AGENTFLOW_MODEL_PRICE_OUT_USD_PER_M"

#: 记账时的角色名。这一层只调模型、不扮演编排角色，所以默认登记为 modelgw
#: 而不是硬塞一个 A–H 里的字母：冒名会让 `by_role()` 的归口统计说谎。
DEFAULT_ROLE = "modelgw"

_PER_M = 1_000_000.0


@dataclass(frozen=True)
class Price:
    """一个单价对（每百万 token 的美元价）。负价直接拒绝。"""

    usd_per_m_in: float
    usd_per_m_out: float

    def __post_init__(self) -> None:
        if self.usd_per_m_in < 0 or self.usd_per_m_out < 0:
            raise ValueError(
                f"单价不能为负（收到 in={self.usd_per_m_in} out={self.usd_per_m_out}）"
                "—— 负价会让'花了多少'这个数字失去意义"
            )

    def to_dict(self) -> dict[str, float]:
        """落盘用的扁平结构（`cost.json` 与清单都引用它）。"""
        return {
            "usd_per_m_in": self.usd_per_m_in,
            "usd_per_m_out": self.usd_per_m_out,
        }

    @property
    def source(self) -> str:
        """这份价是环境变量给的还是默认观测值？写进产物里，便于日后复核。"""
        env = os.environ
        if str(env.get(ENV_PRICE_IN) or "").strip() or str(env.get(ENV_PRICE_OUT) or "").strip():
            return f"env:{ENV_PRICE_IN}/{ENV_PRICE_OUT}"
        return "default:deepseek-public-observed"


def _float_env(env: Mapping[str, str], name: str, default: float) -> float:
    """读一个浮点环境变量；读不出来就用默认值（不静默改成 0，那会变成免费）。"""
    raw = str(env.get(name) or "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def price_from_env(env: Mapping[str, str] | None = None) -> Price:
    """从环境变量读单价；两个变量都可单独缺省。"""
    src = dict(os.environ if env is None else env)
    return Price(
        usd_per_m_in=_float_env(src, ENV_PRICE_IN, DEFAULT_PRICE_IN_USD_PER_M),
        usd_per_m_out=_float_env(src, ENV_PRICE_OUT, DEFAULT_PRICE_OUT_USD_PER_M),
    )


def price_of(spec: Any = None, *, env: Mapping[str, str] | None = None) -> tuple[float, float]:
    """一次调用该按什么价算 ⇒ `(输入价, 输出价)`，单位是美元每百万 token。

    为什么收 `spec` 却不用它：本轮的单价表就是一个全局对（DeepSeek 一家）。
    真正的按模型分档表需要一个数据源，而"从模型问价"是错的方向（见模块 docstring）。
    参数留着是因为调用方手上总有 `spec`，而"价格与配置同源"这件事在接口上
    应当看得见；等有了多档价目表，扩展点就在这里，不必改调用方。
    """
    p = price_from_env(env)
    return (p.usd_per_m_in, p.usd_per_m_out)


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
    """
    p = price if isinstance(price, Price) else Price(price[0], price[1])
    per_call = (
        int(getattr(reply, "tokens_in", 0) or 0) * p.usd_per_m_in
        + int(getattr(reply, "tokens_out", 0) or 0) * p.usd_per_m_out
    ) / _PER_M
    attempts = max(1, int(getattr(reply, "attempts", 1) or 1))
    return round(per_call * attempts, 6)


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
                 task_id: str, scope: str = "reason", extra_note: str = "",
                 call_index: int = 0, price: tuple[float, float] | None = None,
                 now: str | None = None) -> dict:
    """把一次模型调用的花销经 `TokenMeter` 写进 `usage_ledger`，并如实报告结局。

    返回 ``{"charged", "usage_id", "tokens_in", "tokens_out", "usd", "reason"}``。

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
    """
    if meter is None:
        return {
            "charged": False,
            "usage_id": "",
            "tokens_in": 0,
            "tokens_out": 0,
            "usd": 0.0,
            "reason": "not_wired",
        }

    key = idempotency_key(task_id, call_index)
    prior = _find_by_marker(meter, key)
    if prior is not None:
        return {
            "charged": False,
            "usage_id": str(prior.get("usage_id") or ""),
            "tokens_in": int(prior.get("tokens_in") or 0),
            "tokens_out": int(prior.get("tokens_out") or 0),
            "usd": float(prior.get("usd") or 0.0),
            "reason": "duplicate",
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

    stuck = charge_reply(None, _fake_reply(ok=True, tokens_in=10, tokens_out=5), task_id="t0")
    if stuck["charged"] or stuck["reason"] != "not_wired":
        problems.append(f"meter=None 时必须 not_wired 且不入账：{stuck}")

    with tempfile.TemporaryDirectory() as td:
        st = Store(Path(td) / "ws")
        st.init()
        meter = TokenMeter(st, budget_usd=1.0)
        r = _fake_reply(ok=True, tokens_in=1_000_000, tokens_out=1_000_000, attempts=1)
        first = charge_reply(meter, r, task_id="t1", call_index=0)
        again = charge_reply(meter, r, task_id="t1", call_index=0)
        rows = st.rows("usage_ledger")
        if len(rows) != 1:
            problems.append(f"重复入账必须只写一行，实际 {len(rows)} 行")
        if again["reason"] != "duplicate":
            problems.append(f"第二次入账应当是 duplicate：{again}")
        want = DEFAULT_PRICE_IN_USD_PER_M + DEFAULT_PRICE_OUT_USD_PER_M
        if abs(first["usd"] - want) > 1e-9:
            problems.append(f"一百万一进一百万出的价应当是 {want}：{first}")
        third = charge_reply(meter, r, task_id="t1", call_index=1)
        if third["reason"] != "charged":
            problems.append(f"换了 call_index 就是另一笔：{third}")

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

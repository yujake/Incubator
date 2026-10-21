"""`modelcost`（模型花销入账适配器）的测试：单价、算术、三态、幂等。

## 为什么单价与算术要单独测

"这次花了多少钱"是一个会被印进成本报告、并被用来决定"还能不能继续跑"的数字。
它必须是确定性算术（`usd_for`），而不是任何一次模型生成的结果。
本文件把三个环节各自钉住：单价从哪来、token 怎么换成美元、以及
"没记账"与"记了一笔零"必须能分辨。

## 幂等为什么要有负控

重复入账是"预算看起来还剩很多、实际已经花了两倍"的典型成因，
而它在账面上表现为一条完全合理的行 —— 没有一条断言去数行数就发现不了。
`test_second_charge_same_key_writes_nothing` 与 `test_different_call_index_is_a_new_charge`
是一对：前者钉住"不许重复写"，后者钉住"别把合法的第二笔也当成重复"。
"""

from __future__ import annotations

import pytest

from agentflow import modelcost as MC
from agentflow.modelgw import ModelReply
from agentflow.store import Store
from agentflow.tokenmeter import TokenMeter

#: 固定时间戳：`usage_ledger` 的行要求 `at` 非空，而测试不许依赖当前时间。
TS = "2026-01-01T00:00:00+00:00"


@pytest.fixture
def meter(store: Store) -> TokenMeter:
    """挂在临时工作区上的记账器（预算不设上限，除非用例自己造一个）。"""
    return TokenMeter(store)


def _ok(tokens_in: int = 1_000_000, tokens_out: int = 0, attempts: int = 1) -> ModelReply:
    """一个成功的结局，token 数按用例给。"""
    return ModelReply(ok=True, text="4", tokens_in=tokens_in, tokens_out=tokens_out,
                      attempts=attempts, model="deepseek-chat")


def _rows(store: Store) -> list[dict]:
    return store.rows("usage_ledger")


# --------------------------------------------------------------- 单价解析


def test_price_of_defaults_are_documented_observations():
    """缺省价必须等于登记的那两个常量（否则文档里的数字与代码里的数字会漂移）。

    2026-10-14（业主「花销标准与供应商定价吻合」）之后 `Price` 多了一档命中缓存价：
    它故意没有缺省值（未登记就是 `None`，按未命中价算并留痕），
    所以这里断言的是"两格照旧 + 第三格是 None"。
    """
    assert MC.price_of() == (MC.DEFAULT_PRICE_IN_USD_PER_M, MC.DEFAULT_PRICE_OUT_USD_PER_M)
    assert MC.price_from_env({}).to_dict() == {
        "usd_per_m_in": MC.DEFAULT_PRICE_IN_USD_PER_M,
        "usd_per_m_out": MC.DEFAULT_PRICE_OUT_USD_PER_M,
        "usd_per_m_in_hit": None,
    }


def test_env_overrides_each_price_independently():
    """单价可由环境变量覆盖，且两个变量可单独覆盖（只改输出价不该动输入价）。"""
    only_out = MC.price_from_env({MC.ENV_PRICE_OUT: "9.5"})
    assert only_out.usd_per_m_in == MC.DEFAULT_PRICE_IN_USD_PER_M
    assert only_out.usd_per_m_out == 9.5
    both = MC.price_from_env({MC.ENV_PRICE_IN: "1.5", MC.ENV_PRICE_OUT: "3"})
    assert (both.usd_per_m_in, both.usd_per_m_out) == (1.5, 3.0)


def test_price_of_reads_the_injected_env():
    """`price_of(env=...)` 走同一份解析（不另开一条读环境变量的路）。"""
    assert MC.price_of(env={MC.ENV_PRICE_IN: "2"}) == (2.0, MC.DEFAULT_PRICE_OUT_USD_PER_M)


def test_unparseable_price_falls_back_to_default_not_to_zero():
    """负控：单价读不出来时用缺省值，不许静默变成 0（那等于宣布模型免费）。"""
    got = MC.price_of(env={MC.ENV_PRICE_IN: "不是数字", MC.ENV_PRICE_OUT: ""})
    assert got == (MC.DEFAULT_PRICE_IN_USD_PER_M, MC.DEFAULT_PRICE_OUT_USD_PER_M)


def test_negative_price_is_refused():
    """负控：负价会让"花了多少"这个数字失去意义，构造时就拒绝。"""
    with pytest.raises(ValueError, match="单价不能为负"):
        MC.Price(-1.0, 1.0)


# --------------------------------------------------------------- 美元算术


def test_usd_for_is_exact_arithmetic():
    """一百万一进、一百万出 ⇒ 恰好是两条单价之和；半量 ⇒ 恰好是一半。"""
    assert MC.usd_for(_ok(1_000_000, 1_000_000), (1.0, 2.0)) == 3.0
    assert MC.usd_for(_ok(500_000, 0), (1.0, 2.0)) == 0.5


def test_usd_for_multiplies_by_attempts():
    """与 `tokenmeter.Charge` 同一口径：重试的每一次都是另一次计费请求。"""
    one = MC.usd_for(_ok(1_000_000, 0, attempts=1), (1.0, 0.0))
    three = MC.usd_for(_ok(1_000_000, 0, attempts=3), (1.0, 0.0))
    assert (one, three) == (1.0, 3.0)


def test_usd_for_zero_tokens_is_zero():
    """没有 token 就是 0 美元（不是 None、不是缺省价）。"""
    assert MC.usd_for(_ok(0, 0), (1.0, 2.0)) == 0.0


# --------------------------------------------------------------- 三态：未接线


def test_no_meter_is_not_wired_and_writes_nothing(store: Store):
    """三态①：没接线 ⇒ `charged=False` 且 `reason=not_wired`，一行都不许写。

    这是本模块最贵的一条：一个"看起来记了账"的返回值会让预算熔断永远不触发。
    """
    before = len(_rows(store))
    got = MC.charge_reply(None, _ok(), task_id="t", call_index=0, scope="reason")
    assert got == {"charged": False, "usage_id": "", "tokens_in": 0, "tokens_out": 0,
                   "usd": 0.0, "reason": "not_wired", "scope": "reason"}
    assert len(_rows(store)) == before, "没接线时不许假装入账"


# --------------------------------------------------------------- 三态：失败


def test_failed_reply_records_zero_value_row_not_a_silent_skip(store: Store, meter: TokenMeter):
    """三态②：失败的调用仍然留一行（零值 + note），`reason` 是失败原因。

    零值也要记：否则"没记账"与"这一笔是零"在账面上分不开，
    而"预算还剩多少"就永远答不准。
    """
    reply = ModelReply(ok=False, error_kind="timeout", error_detail="x", attempts=1)
    got = MC.charge_reply(meter, reply, task_id="t", call_index=0, now=TS, scope="reason")
    assert got["charged"] is True and got["reason"] == "timeout" and got["usd"] == 0.0
    rows = _rows(store)
    assert len(rows) == 1
    assert rows[0]["tokens_total"] == 0 and rows[0]["usd"] == 0.0
    assert "timeout" in rows[0]["note"] and "not_checked=1" in rows[0]["note"]


def test_auth_failure_with_usage_is_billed_at_real_cost(store: Store, meter: TokenMeter):
    """三态②的另一半：上游确实计了费就不许记成零（只记一次会让"一直重试"看起来便宜）。"""
    reply = ModelReply(ok=False, error_kind="auth_failed", http_status=401,
                       tokens_in=1_000_000, tokens_out=0, attempts=1)
    got = MC.charge_reply(meter, reply, task_id="t", call_index=0, scope="reason",
                          price=(1.0, 0.0), now=TS)
    assert got["reason"] == "auth_failed" and got["usd"] == 1.0
    assert _rows(store)[0]["usd"] == 1.0


def test_success_without_usage_is_reported_as_tokens_missing(store: Store, meter: TokenMeter):
    """负控：成功但上游没回 usage ⇒ 记零并显式报 `tokens_missing`，不静默按 0 计价。"""
    got = MC.charge_reply(meter, ModelReply(ok=True, text="ok"), task_id="t",
                          call_index=0, scope="reason", now=TS)
    assert got["reason"] == "tokens_missing" and got["usd"] == 0.0
    assert _rows(store), "成功但没 usage 的调用也要留一行"


# --------------------------------------------------------------- 三态：成功


def test_successful_reply_is_charged_with_scope_role_and_attempts(store: Store, meter: TokenMeter):
    """正向：一次成功调用写进账本，scope/role/attempts 都要如实登记。"""
    got = MC.charge_reply(meter, _ok(1_000_000, 1_000_000), task_id="t1", call_index=0,
                          role="C", scope="reason", extra_note="端到端", now=TS)
    assert got["charged"] is True and got["reason"] == "charged"
    row = _rows(store)[0]
    assert row["usage_id"] == got["usage_id"] and row["scope"] == "reason"
    assert row["role"] == "C" and row["task_id"] == "t1"
    assert row["tokens_total"] == 2_000_000
    assert row["usd"] == round(MC.DEFAULT_PRICE_IN_USD_PER_M + MC.DEFAULT_PRICE_OUT_USD_PER_M, 6)
    assert "端到端" in row["note"]


def test_attempts_are_charged_and_recorded(store: Store, meter: TokenMeter):
    """重试按次计费：`attempts=3` 的钱与行上的 `attempts` 都必须是 3。"""
    got = MC.charge_reply(meter, _ok(1_000_000, 0, attempts=3), task_id="t", call_index=0,
                          scope="reason", price=(1.0, 0.0), now=TS)
    assert got["usd"] == 3.0
    assert _rows(store)[0]["attempts"] == 3
    assert _rows(store)[0]["tokens_total"] == 3_000_000


# --------------------------------------------------------------- 幂等


def test_second_charge_same_key_writes_nothing(store: Store, meter: TokenMeter):
    """负控（会红的那个）：同一个 `(task_id, call_index)` 记两次，账上只能有一行。"""
    first = MC.charge_reply(meter, _ok(1_000_000, 0), task_id="t", call_index=0,
                            scope="reason", price=(1.0, 0.0), now=TS)
    again = MC.charge_reply(meter, _ok(1_000_000, 0), task_id="t", call_index=0,
                            scope="reason", price=(1.0, 0.0), now=TS)
    assert first["charged"] is True and first["reason"] == "charged"
    assert again["charged"] is False and again["reason"] == "duplicate"
    assert again["usage_id"] == first["usage_id"], "重放要指回那一行，而不是发一个新号"
    assert len(_rows(store)) == 1, "重复入账必须只写一次"
    assert meter.spent()["usd"] == 1.0


def test_different_call_index_is_a_new_charge(store: Store, meter: TokenMeter):
    """反向负控：序号不同就是另一笔账（别把合法的第二笔也当成重复）。"""
    MC.charge_reply(meter, _ok(1_000_000, 0), task_id="t", call_index=0,
                    scope="reason", price=(1.0, 0.0), now=TS)
    second = MC.charge_reply(meter, _ok(1_000_000, 0), task_id="t", call_index=1,
                             scope="reason", price=(1.0, 0.0), now=TS)
    assert second["reason"] == "charged" and len(_rows(store)) == 2


def test_different_task_id_is_a_new_charge(store: Store, meter: TokenMeter):
    """反向负控：序号相同但 task 不同也是另一笔账。"""
    MC.charge_reply(meter, _ok(1_000_000, 0), task_id="a", call_index=0,
                    scope="reason", price=(1.0, 0.0), now=TS)
    other = MC.charge_reply(meter, _ok(1_000_000, 0), task_id="b", call_index=0,
                            scope="reason", price=(1.0, 0.0), now=TS)
    assert other["reason"] == "charged" and len(_rows(store)) == 2


def test_idempotency_key_is_stable_and_index_sensitive():
    """幂等键确定性：同输入同输出（跨进程重放才认得出），序号变则键变。"""
    assert MC.idempotency_key("任务 1", 0) == MC.idempotency_key("任务 1", 0)
    assert MC.idempotency_key("任务 1", 0) != MC.idempotency_key("任务 1", 1)
    assert MC.idempotency_key("a", 0).startswith("idem-")


def test_scope_must_be_in_the_controlled_vocabulary(meter: TokenMeter):
    """负控：`scope` 不是 `USAGE_SCOPES` 里的值 ⇒ `Charge` 直接拒绝。"""
    with pytest.raises(ValueError, match="scope"):
        MC.charge_reply(meter, _ok(1, 0), task_id="t", call_index=0, scope="不是范围")


# --------------------------------------------------------------- 自检


def test_module_selftest_passes_offline():
    """自检本身要能在没有 key、没有网络的环境里通过（退出码 0）。"""
    assert MC.cost_main([]) == 0

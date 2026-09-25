"""FC-19（token 预算是硬约束、重试也计入）的测试。

## 判据逐条对应

FC-19 的三条判据（`test/test2/LESSONS.md` §6.5）：

1. 每个子任务有 token 上限与最长轮次，超额即降级或返回当前最好答案
   → `TokenMeter.guard()`：`allowed=False` 时在开工前拒绝；
   调用方（F 的攻坚 / 编排层）据此降级并交出 `best_partial`。
2. 重试计入预算（可判定：注入 N 次失败重试后，消耗 ≥ N × 单次成本）
   → `Charge.attempts` 参与 `tokens`；`test_retries_are_charged_individually` 就是那条判据。
3. D 向 A 提问的预算必须已定值并写进配置
   → 这一条落在"预算从配置来"，本文件由 `TokenMeter(budget_tokens=...)` 的形状体现；
   实际的配置接线在 `Policy.token_budget` 与 `run_*` 的装配处（尚未接线，见文末注释）。

## 为什么这一条最后才做

数据结构（`UsageEntry` / `usage_ledger` / `Policy.token_budget` / `CancelToken.token_budget`）
早就备好了，但没有任何东西把花销记进去、也没有任何东西据此说"不"。
"有表、有字段、有测试"与"真的会拦"是两件事 —— 本文件测的是后者。
"""

from __future__ import annotations

import pytest
from agentflow import schema as S
from agentflow.tokenmeter import Charge, TokenMeter


def _meter(store, **kw):
    store.init()
    return TokenMeter(store, **kw)


# ============================================================ Charge 的计费口径


def test_charge_multiplies_by_attempts():
    """判据②的核心：`attempts` 参与计费。

    只记一次的后果是"一直在重试的路径在账面上与一次就成功的路径一样贵" ——
    而那正是最该被看见的浪费。
    """
    one = Charge(role="A", scope="search", tokens_in=1000, tokens_out=500, attempts=1)
    three = Charge(role="A", scope="search", tokens_in=1000, tokens_out=500, attempts=3)
    assert one.tokens == 1500
    assert three.tokens == 4500, "重试按次计费"


def test_charge_rejects_a_bad_scope():
    """负控：`scope` 必须在受控词表里（`schema.USAGE_SCOPES`）。"""
    with pytest.raises(ValueError, match="scope"):
        Charge(role="A", scope="不是范围")


def test_charge_rejects_zero_attempts():
    """负控：0 次尝试却记一笔花销是不自洽的。"""
    with pytest.raises(ValueError, match="attempts"):
        Charge(role="A", scope="search", tokens_in=1, attempts=0)


# ============================================================ 记账


def test_zero_value_charge_is_recorded_with_a_note(store):
    """零值也要记 —— 否则"没记账"与"花了零"无法区分。

    而一条不带任何信息的零值行只会污染台账 ⇒ 必须写 `note`。
    """
    m = _meter(store)
    with pytest.raises(ValueError, match="note"):
        m.charge(Charge(role="E", scope="experiment"))
    got = m.charge(Charge(role="E", scope="experiment", note="纯本地数值计算，未调 LLM"))
    assert got["recorded"] is True and got["tokens"] == 0
    assert len(store.rows("usage_ledger")) == 1, "零值也要落一行"


def test_charge_writes_a_valid_ledger_row(store):
    """记账写出的行必须能通过 schema 校验（含 `tokens_total >= in + out`）。"""
    m = _meter(store)
    m.charge(Charge(role="A", scope="search", tokens_in=100, tokens_out=50, usd=0.002, attempts=2))
    row = store.rows("usage_ledger")[0]
    S.UsageEntry(**{k: v for k, v in row.items() if k in S.UsageEntry.__dataclass_fields__}).validate()
    assert row["tokens_total"] == 300, "(100+50) × 2 次"
    assert row["attempts"] == 2 and "重试" in row["note"]


def test_retries_are_charged_individually(store):
    """判据②的可判定形式：注入 N 次失败重试后，消耗 ≥ N × 单次成本。

    模拟"一次检索失败了 3 次才成功"：4 次尝试 = 4 次计费。
    """
    m = _meter(store)
    per_attempt = 800
    attempts = 4  # 3 次失败 + 1 次成功
    m.charge(Charge(role="A", scope="search", tokens_in=per_attempt, attempts=attempts,
                    note="前 3 次 provider 超时后成功"))
    spent = m.spent()
    assert spent["tokens"] >= attempts * per_attempt, (
        f"重试必须计入：期望 >= {attempts * per_attempt}，实际 {spent['tokens']}"
    )
    over = m.retry_overhead()
    assert over["extra_tokens"] == per_attempt * (attempts - 1), "重试的**额外**开销可单独看出"
    assert over["entries_with_retry"] == 1


def test_spent_reads_from_the_ledger_not_from_memory(store):
    """账本是唯一权威：每次都从表里读，不在内存里缓存。

    缓存会让"另一个进程刚记了一笔"在这边看不见 —— 那正是
    "预算判断按哪一份"这类问题的来源。
    """
    m = _meter(store)
    m.charge(Charge(role="A", scope="search", tokens_in=100, note="第一笔"))
    before = m.spent()["tokens"]
    # 另一个"进程"（直接写表）记了一笔 —— 本实例必须看得见
    with store.tx("usage_ledger", "counters", actor="other") as tx:
        tx.upsert("usage_ledger", S.UsageEntry(
            usage_id=tx.alloc_id("usage"), scope="summon", role="B",
            tokens_in=70, tokens_total=70, at=S.now_iso(), note="外来一笔",
        ).to_dict())
    assert m.spent()["tokens"] == before + 70, "内存缓存会让这一笔丢失"


# ============================================================ 守卫（三态）


def test_guard_is_not_limited_when_no_budget_is_configured(store):
    """三态：没设预算 ⇒ `limited=False` 且 reason 说"不限制"，不是"够用"。

    把两者折叠成一个 `allowed=True`，就无法回答"预算守卫生效了没有"。
    """
    m = _meter(store)
    r = m.guard(estimate_tokens=10_000)
    assert r.limited is False and r.allowed is True
    assert "未设预算" in r.reason and "没有生效" in r.reason


def test_guard_refuses_before_work_when_the_estimate_would_overshoot(store):
    """判据①：超额要在开工前拒绝，而不是做到一半再停。"""
    m = _meter(store, budget_tokens=1000)
    m.charge(Charge(role="A", scope="search", tokens_in=900, note="先花掉 900"))
    r = m.guard(estimate_tokens=200)
    assert r.limited is True and r.allowed is False
    assert "在开工前拒绝" in r.reason and r.remaining_tokens == 100

    ok = m.guard(estimate_tokens=50)
    assert ok.allowed is True and ok.remaining_tokens == 100


def test_guard_refuses_when_already_over_budget(store):
    """已经超了 ⇒ 拒绝（且 reason 给出实际数字，可复核）。"""
    m = _meter(store, budget_tokens=100)
    m.charge(Charge(role="A", scope="search", tokens_in=150, note="超了"))
    r = m.guard()
    assert r.allowed is False and "已经超出预算" in r.reason
    assert r.spent_tokens == 150 and r.budget_tokens == 100


def test_charge_still_records_when_over_budget(store):
    """关键区分：`charge()` 在超预算时照样写 —— 钱已经花了，账必须记。

    拦住新工作的权力在 `guard()`（开工之前），不在 `charge()`（做完之后）。
    把两者混起来会得到一个既不准又拦不住的账本。
    """
    m = _meter(store, budget_tokens=100)
    got = m.charge(Charge(role="A", scope="search", tokens_in=500, note="已经花了"))
    assert got["recorded"] is True and got["over_budget"] is True
    assert len(store.rows("usage_ledger")) == 1
    assert "账照样记" in got["reason"]


def test_zero_budget_is_not_the_same_as_no_budget(store):
    """负控（三态）：`budget_tokens=0` 与 `None` 语义不同。

    `None` = 没设预算（不限制）；`0` = 预算为零（什么都不准做）。
    合并这两者会让"忘了配"看起来像"配成了零"。
    """
    with pytest.raises(ValueError, match="必须为正"):
        _meter(store, budget_tokens=0)


def test_by_role_attributes_the_spend(store):
    """花销必须能归口：总量只说明"花了多少"，"是谁花的"才决定下一步压谁。"""
    m = _meter(store)
    m.charge(Charge(role="A", scope="search", tokens_in=100, note="A"))
    m.charge(Charge(role="E", scope="experiment", tokens_in=30, attempts=2, note="E，重试过一次"))
    got = m.by_role()
    assert got["A"]["tokens"] == 100
    assert got["E"]["tokens"] == 60 and got["E"]["attempts"] == 2


# ============================================================ 与预算守卫的接缝
#
# 接线状态（如实登记）：`TokenMeter` 现在是一个可用的记账+守卫，
# 但 `src/agentflow/` 里还没有调用方（`Policy.token_budget` 与
# `CancelToken.token_budget` 是配置位，`conductor` 尚未调 `guard`）。
# 这条与 FC-17 当时的情形一样（"有骨架、没接线"）——
# 接线点已定位：`conductor.summon()` 在过策略时调 `guard(estimate)`，
# 各 agent 的 `_call` 在调用后 `charge(...)`。
# 在那之前，本文件测的是机制，不是"框架已经在限流"。


def test_meter_does_not_touch_other_tables(store):
    """并发安全性：记账只动 `usage_ledger` + `counters`。

    若非如此，每次调用都要去抢一张可能被别处长期持有的表，整个编队会排队 ——
    而记账是每次调用都要做的事。
    """
    m = _meter(store)
    before = {t: len(store.rows(t)) for t in S.TABLES if t not in ("usage_ledger",)}
    m.charge(Charge(role="A", scope="search", tokens_in=10, note="x"))
    after = {t: len(store.rows(t)) for t in S.TABLES if t not in ("usage_ledger",)}
    assert before == after, "记账不该写别的表"

"""退避租约被读（而不只是被写）：`AgentA._claim` 必须遵守 `lease_until`。

## 本文件修的是什么

搜索失败时 `run_once` 会写下一条"退避租约"：

    fresh["claimed_by"] = None
    fresh["lease_until"] = make_lease(self.retry_backoff_seconds)

而 `_claim` 的跳过判据曾经是::

    if r.get("claimed_by") and not lease_expired(r.get("lease_until")):
        skipped_lease_active += 1
        continue

它同时要求 `claimed_by` 非空 —— 而失败分支恰好把它置成了 `None`
⇒ 这条租约永远不会被读到 ⇒ 同一个 A 实例下一轮立刻再领同一条，
连打同一个 API（最多到 `max_attempts` 才 `gave_up`）。
"写进存储的约束"与"被执行的约束"是两件事，而当时的自检只断言了写
（`bool(r3["lease_until"]) and r3["claimed_by"] is None`）——
一个断言"写入了"的测试，无法发现"没有任何地方读它"。

所以本文件的每一条都是"读了没有"的断言，而不是"写了没有"。

## 判定矩阵（四种情形，缺一不可）

===============================  ==================  ==========  ==========================
`claimed_by`                     `lease_until`       可领?       计数落在哪
===============================  ==================  ==========  ==========================
非空                              在未来              不可     ``skipped_lease_active``（他人持有）
空                            在未来          不可     ``skipped_lease_backoff``（本文件的存在理由）
任意（含非空）                     已过期/为空         可           领走并接管（原有语义，必须保留）
空                                为空                可           ——
===============================  ==================  ==========  ==========================

## 判据来源（不许另写一份）

"租约是否仍在有效期内"只有 `agentflow.store.lease_expired` 一份实现
（`interactions.order_pending_requests` 内部用的也是它）。本文件的测试调用它来
造场景（例如断言 `FUTURE_LEASE` 真的没过期，避免测试空洞），不在测试里另写比较。

## 本文件只调用、不改动

`order_pending_requests` / `lease_expired` / `admit_search_request` 都在
`src/agentflow/interactions.py`（FC-27 禁 AI 区）与 `store.py`。本文件只调用它们。
"""

from __future__ import annotations

from agentflow import schema as S
from agentflow.agent_a import AgentA
from agentflow.store import lease_expired

from conftest import TS, add_request

# ---------------------------------------------------------------- 常量 / 替身

#: 未过期的租约（"租约仍在走"）：用于构造"别人正在做"与"我们自己正在退避"两种行。
FUTURE_LEASE = "2099-01-01T00:00:00+00:00"
#: 已过期的租约（"有人拿到却没做完"）：可以抢，也可以重试。
PAST_LEASE = "2020-01-01T00:00:00+00:00"

REASON_EMPTY = "no_pending_request"
REASON_ALL_LEASED = "pending_requests_all_leased"
REASON_ALL_IN_BACKOFF = "pending_requests_all_in_backoff"
REASON_NOTHING_CLAIMABLE = "no_claimable_request"


class CountingProvider:
    """记录"被问了什么"的 provider 替身；`error` 非空时模拟上游故障（离线、确定性）。

    用它而不是 Mock：`provider.calls` 的长度就是上游 API 被打了几次。
    退避租约的全部意义就是"别在同一个进程里立刻再打一次"，所以这个计数
    是本文件最直接的证据 —— 它让"租约被读了"成为一个可观察的事实。
    """

    name = "counting"

    def __init__(self, candidates=(), error: Exception | None = None):
        self.candidates = list(candidates)
        self.error = error
        self.calls: list[str] = []

    def search(self, topic, mode, description, limit):
        self.calls.append(topic)
        if self.error is not None:
            raise self.error
        return list(self.candidates)


def _agent(store, provider, **cfg) -> AgentA:
    """A 实例：不下载（本文件只关心"取不取得到"）。`retry_backoff_seconds` 默认 60。"""
    config = {"download": False, "lease_seconds": 900, "max_attempts": 3}
    config.update(cfg)
    return AgentA(store, providers=[provider], downloader=None, config=config)


def _add_req(
    store,
    request_id: str,
    *,
    priority: str = "medium",
    topic: str | None = None,
    attempts: int = 0,
    claimed_by: str | None = None,
    lease_until: str | None = None,
) -> dict:
    """插入一条合法的 search_requests 行（带 `priority`，含校验）。

    为什么不用 conftest 的 `add_request`：那个夹具没有 `priority` 参数，而
    "被跳过的那条排在被取走的那条之前"在本文件里是必需的 ——
    `_claim` 只统计在被取走那条之前扫过的行（领到就 return），
    而排序键的第一档是优先级。所以要构造"高优先级的退避行先被扫到、随后
    低优先级的全新行被领走"这种顺序，就必须能显式写优先级。
    （`tests/test_agent_a_priority.py` 出于同样的理由也自建了一份带校验的版本。）

    不合法就当场炸（`row.validate()`），而不是让测试数据悄悄退化。
    """
    row = S.SearchRequest(
        request_id=request_id,
        timestamp=TS,
        topic=topic or f"主题-{request_id}",
        mode="broad",
        content_description="",
        done=False,
        submitted_by="agent-D",
        claimed_by=claimed_by,
        lease_until=lease_until,
        attempts=attempts,
        priority=priority,
    )
    row.validate()
    with store.tx("search_requests", actor="test") as tx:
        tx.upsert("search_requests", row.to_dict())
    return row.to_dict()


def _row(store, request_id: str) -> dict:
    return next(r for r in store.rows("search_requests") if r["request_id"] == request_id)


def _expire_lease(store, request_id: str) -> None:
    """把某行的租约改成已过期（模拟"退避到点了"），`claimed_by` 一律不动。

    为什么直接改 `lease_until` 而不 sleep：测试不许依赖真实时间；而"租约过期"这个
    事实本身由 `store.lease_expired` 判定 —— 我们只是把那个输入换成过去时刻。
    """
    with store.tx("search_requests", actor="test") as tx:
        row = tx.find("search_requests", request_id=request_id)
        assert row is not None, f"请求 {request_id} 不存在"
        row["lease_until"] = PAST_LEASE
        tx.upsert("search_requests", row, note="test_expire_lease")


# ================================================================ 0. 夹具自检


def test_fixture_leases_are_really_live_and_really_expired():
    """负控（防空洞测试）：两个常量必须真的"未过期"/"已过期"。

    若哪天有人把 `FUTURE_LEASE` 写成过去的时刻，下面所有"应当被跳过"的用例都会
    因为租约过期而通过（而不是因为判据正确）—— 那种"绿"毫无意义。
    这里先把夹具本身钉住。
    """
    assert not lease_expired(FUTURE_LEASE), "FUTURE_LEASE 必须真的未过期，否则用例空洞"
    assert lease_expired(PAST_LEASE), "PAST_LEASE 必须真的已过期"
    assert lease_expired(None), "空租约 = 无人持有 = 已过期（store.lease_expired 的口径）"


# ================================================================ 1. 判定矩阵四种情形


def test_case_a_other_holder_with_live_lease_is_skipped(store):
    """(a) 别人持有（`claimed_by` 非空）+ 租约未过期 ⇒ 跳过，计 `skipped_lease_active`。

    这是"只排队、不抢占"的原有语义，修复不得改动它。
    """
    provider = CountingProvider()
    add_request(store, "r-0001", topic="别人的活", claimed_by="agent-A-other", lease_until=FUTURE_LEASE)
    a = _agent(store, provider)

    out = a._claim()

    assert out.request is None, "别人持着有效租约的活不得被抢"
    assert out.skipped_lease_active == 1 and out.skipped_lease_backoff == 0, "记进'他人持有'那一类"
    assert out.skipped_reason == REASON_ALL_LEASED
    assert provider.calls == [], "没领到就不该去检索"
    assert _row(store, "r-0001")["attempts"] == 0, "被跳过的那条一行都没被改过"


def test_case_b_backoff_lease_without_holder_is_skipped(store):
    """(b) 退避中（`claimed_by is None` + `lease_until` 在未来）⇒ 跳过。本次修复。

    这条在修复之前是红的：旧判据要求 `claimed_by` 非空，于是这种行被判成"可以领"，
    A 立刻重领同一条 —— 退避租约写了等于没写。
    """
    provider = CountingProvider()
    add_request(store, "r-0001", topic="退避中", attempts=1, claimed_by=None, lease_until=FUTURE_LEASE)
    a = _agent(store, provider)

    out = a._claim()

    assert out.request is None, "退避租约必须拦住重领 —— 它是我们自己上次失败留下的，不是'没人要'"
    assert out.skipped_lease_backoff == 1, "退避中的条数必须被数出来"
    assert out.skipped_lease_active == 0, "claimed_by 为空 ⇒ 不许记进'别人持着'（诊断文字不能撒谎）"
    assert out.skipped_reason == REASON_ALL_IN_BACKOFF, "整队都在退避 ⇒ 必须是第四态那个 reason"
    assert out.skipped_reason != REASON_ALL_LEASED, "不许把它压进'全被别人持着'"
    assert _row(store, "r-0001")["attempts"] == 1, "attempts 只在 _claim 里 +1：没增 = 真的没被领走"
    assert provider.calls == [], "退避期间不得打上游"


def test_case_c_expired_lease_is_claimable_regardless_of_holder(store):
    """(c) 租约已过期 ⇒ 可以抢，不管 `claimed_by` 是谁（原有且必须保留的语义）。

    两种 `claimed_by` 都测：非空 = "之前有人拿到却没做完"（收回沉没成本），
    空 = "我们自己的退避到点了，允许重试"。这两条正是租约存在的另一半理由。
    """
    for rid, claimed_by in (("r-0001", "agent-A-dead"), ("r-0002", None)):
        add_request(store, rid, topic=f"过期-{rid}", attempts=1, claimed_by=claimed_by, lease_until=PAST_LEASE)
    a = _agent(store, CountingProvider())

    first = a._claim()
    assert first.request is not None, "过期租约必须可领（否则死掉的活永远烂在队里）"
    assert first.request["request_id"] == "r-0001" and first.request["claimed_by"] == a.actor
    assert first.request["attempts"] == 2, "attempts 继续累加（不是重新开始）"
    assert first.gave_up == 0 and first.skipped_lease_active == 0

    # 第二条（claimed_by 为空 + 过期租约）同样可领 —— 这是"退避到期可重试"的落点
    second = a._claim()
    assert second.request is not None and second.request["request_id"] == "r-0002"
    assert second.request["attempts"] == 2


def test_case_d_no_lease_and_no_holder_is_claimable(store):
    """(d) `claimed_by is None` 且 `lease_until is None` ⇒ 可领（全新请求）。"""
    provider = CountingProvider()
    add_request(store, "r-0001", topic="全新")
    a = _agent(store, provider)

    out = a._claim()

    assert out.request is not None and out.request["request_id"] == "r-0001"
    assert out.request["claimed_by"] == a.actor and out.request["attempts"] == 1
    assert out.skipped_reason is None, "取到了就不该有 skipped_reason"
    assert provider.calls == [], "取任务不检索（检索在 run_once 阶段）"


# ================================================================ 2. 三态优先级：混合情形


def test_mixed_held_and_backoff_reports_no_claimable_request(store):
    """混合：一部分被别人持着、一部分在退避 ⇒ `no_claimable_request`（优先级判据）。

    为什么不用 `pending_requests_all_leased` 或 `..._all_in_backoff`：那两句诊断各自
    说着一个具体的原因（"别人在跑" / "我们自己退避"），而混合情形下一个都不成立。
    诚实的说法是"有活，但都领不到"，把"该等谁"的判断交回调用方。
    """
    add_request(store, "r-0001", topic="别人的活", claimed_by="agent-A-other", lease_until=FUTURE_LEASE)
    add_request(store, "r-0002", topic="退避中", attempts=1, claimed_by=None, lease_until=FUTURE_LEASE)
    a = _agent(store, CountingProvider())

    out = a._claim()

    assert out.request is None
    assert out.pending == 2
    assert out.skipped_lease_active == 1, "两个计数**分开**数：一个是别人，一个是我们自己"
    assert out.skipped_lease_backoff == 1
    assert out.skipped_reason == REASON_NOTHING_CLAIMABLE
    assert out.skipped_reason not in (REASON_ALL_LEASED, REASON_ALL_IN_BACKOFF), "混合不许谎报成单一原因"


def test_backoff_row_does_not_block_later_fresh_work(store):
    """高优先级的退避行不得阻塞后面的全新请求（也不得被抢跑）。

    这条同时钉住两件事，也是"排序 vs 跳过"分工的落点：

    1. 不抢占：退避行虽然优先级更高、排在最前，但它是跳过的（不是领走的），
       于是排在它后面的全新请求照样被取走 —— 队列不会被一条正在退避的活堵死；
    2. 不撒谎：被跳过的那条要按"退避"计数（`skipped_lease_backoff`），
       不是按"别人持着"计数。

    为什么把退避行设成 `high`：`_claim` 只统计在被取走的那条之前扫过的行
    （领到就 `return`），而排序键的第一档是优先级。若退避行是 low、全新行是 medium，
    全新行会先被扫到并直接领走，退避行根本不会被扫到 —— 那样断言
    `skipped_lease_backoff == 1` 就成了一个永远不成立的空洞期望。
    """
    provider = CountingProvider()
    _add_req(store, "r-0001", priority="high", topic="退避中", attempts=1, claimed_by=None, lease_until=FUTURE_LEASE)
    _add_req(store, "r-0002", priority="low", topic="全新的")
    a = _agent(store, provider)

    out = a.run_once()

    assert out.request_id == "r-0002", "退避中的活不抢占队列：低优先级的全新请求照样被取走"
    assert provider.calls == ["全新的"], "只检索了被取走的那条"
    assert out.skipped_lease_backoff == 1, "被跳过的那条要被计入退避（扫过它才算数）"
    assert out.skipped_lease_active == 0, "它不是'别人持着'"
    assert _row(store, "r-0001")["attempts"] == 1, "退避中的那条一行都没被改过"


# ================================================================ 3. 端到端：缺陷的真实症状


def test_same_instance_does_not_immediately_rehit_the_api_after_search_failure(store):
    """本次修复的验收判据：搜索失败后的下一轮，同一个 A 实例不得立刻重打同一个 API。

    缺陷形态（修复前）：第一次 `run_once` 写下的退避租约没有任何地方读它，
    于是第二次 `run_once` 立刻再领同一条、再打一次上游，直到 `max_attempts` 才 `gave_up`
    —— 退避写成了一句空话，而上游看到的是同一个 A 在连打。
    """
    provider = CountingProvider(error=RuntimeError("transient 503"))
    a = _agent(store, provider, retry_backoff_seconds=60)
    add_request(store, "r-0001", topic="退避主题")

    first = a.run_once()
    assert first.processed == 1 and first.outcome is None, "第一次失败：请求保持未完成（§5.3）"
    assert provider.calls == ["退避主题"], "第一次确实打了一次上游"
    assert _row(store, "r-0001")["attempts"] == 1

    second = a.run_once()

    assert provider.calls == ["退避主题"], "退避租约必须拦住第二次调用 —— 这正是本次修复"
    assert second.processed == 0 and second.request_id is None
    assert second.skipped_reason == REASON_ALL_IN_BACKOFF
    assert second.skipped_lease_backoff == 1 and second.skipped_lease_active == 0
    row = _row(store, "r-0001")
    assert row["attempts"] == 1, "attempts 只在 _claim 里 +1 ⇒ 没被领走的最硬证据"
    assert row["done"] is False, "退避不是终局（§5.3：一次网络抖动不该判死请求）"


def test_retry_is_allowed_again_once_the_backoff_lease_expires(store):
    """退避租约的另一半语义：到期后重试必须可行（否则它就从"退避"变成了"判死"）。

    做法：把租约改成过去的时刻（等价于"时间走到了退避到期"），仍然 `claimed_by=None`。
    此时 `_claim` 必须把它领回来并重新检索 —— 证明这条租约只延后重试，不取消重试。
    """
    provider = CountingProvider(error=RuntimeError("transient 503"))
    a = _agent(store, provider, retry_backoff_seconds=60)
    add_request(store, "r-0001", topic="退避主题")

    a.run_once()
    assert provider.calls == ["退避主题"]
    assert a.run_once().request_id is None, "租约生效中：这一轮不动它"

    _expire_lease(store, "r-0001")
    third = a.run_once()

    assert third.request_id == "r-0001", "退避到期 ⇒ 重试可行（租约只延后，不取消）"
    assert provider.calls == ["退避主题", "退避主题"], "到期后确实重打了上游"
    assert _row(store, "r-0001")["attempts"] == 2, "attempts 继续累加"
    assert _row(store, "r-0001")["done"] is False, "第二次仍失败：还是未完成，留待下一轮"


# ================================================================ 4. retry_backoff_seconds = 0


def test_retry_backoff_seconds_zero_means_backoff_off_not_unset(store):
    """`retry_backoff_seconds=0` 是合法配置（= 关闭退避），不是"没配"。

    三态纪律：0（配置成"关闭"）与"键缺失"（用默认值）必须给出不同行为，否则将来有人
    把 `get(..., 60)` 写成 `get(...) or 60`，用户显式配的 0 会被静默换成一个默认值
    —— "我明明关了退避，为什么还在等" 就变成一个查不出来的问题。
    """
    provider = CountingProvider(error=RuntimeError("transient 503"))
    a = _agent(store, provider, retry_backoff_seconds=0)
    add_request(store, "r-0001", topic="关掉退避")

    a.run_once()
    row = _row(store, "r-0001")
    assert row["lease_until"] is not None, "租约仍然被**写下**（不是'没写'：字段有值、来源可查）"
    assert lease_expired(row["lease_until"]) is True, "0 秒 ⇒ 租约当场过期（判据仍走 store.lease_expired）"
    assert row["claimed_by"] is None

    second = a.run_once()

    assert second.request_id == "r-0001", "退避关闭 ⇒ 立刻可以重领"
    assert provider.calls == ["关掉退避", "关掉退避"], "确实又打了一次上游（这才叫'关掉了退避'）"
    assert _row(store, "r-0001")["attempts"] == 2

    # 负控：默认值（键缺失）不是 0 ⇒ "没配" 与 "配成 0" 是两件事
    assert _agent(store, provider).retry_backoff_seconds == 60, "键缺失时必须落到默认 60"
    assert _agent(store, provider, retry_backoff_seconds=0).retry_backoff_seconds == 0, "显式的 0 必须原样保留"
    assert _agent(store, provider).retry_backoff_seconds != _agent(store, provider, retry_backoff_seconds=0).retry_backoff_seconds


# ================================================================ 5. 审计：事件日志里也要能分辨


def test_claim_order_event_records_which_kind_of_lease_was_skipped(store):
    """`claim_order` 事件必须带上 `skipped_lease_backoff` —— 否则事后复盘分不清是哪种跳过。

    外部能看到"高优先级没被取走"，但如果事件里只有一个 `skipped_lease_active`，
    就无从判断该去叫另一个 A 实例（别人持有），还是什么都不用做（我们自己退避）。

    退避行故意设成 `high`：事件里的 `skipped_lease_backoff` 只统计在领到那条之前
    扫过的行（见 `test_backoff_row_does_not_block_later_fresh_work` 的说明）。
    """
    provider = CountingProvider()
    _add_req(store, "r-0001", priority="high", topic="退避中", attempts=1, claimed_by=None, lease_until=FUTURE_LEASE)
    _add_req(store, "r-0002", priority="low", topic="全新的")
    a = _agent(store, provider)

    assert a.run_once().request_id == "r-0002"

    events = [e for e in store.read_events() if e.get("message") == "claim_order"]
    assert len(events) == 1, f"应当恰好有一条 claim_order 事件，实际 {len(events)}"
    ev = events[0]
    assert ev["request_id"] == "r-0002"
    assert ev["skipped_lease_backoff"] == 1, "事件里必须能看见'退避被跳过'这一类"
    assert ev["skipped_lease_active"] == 0, "不得把它记成'他人持有'"
    assert ev["order"] == ["r-0001", "r-0002"], "排序：high 的退避行在前（分桶只影响排序，不决定取哪条）"


def test_skip_reasons_stay_distinct_and_old_values_are_untouched(store):
    """负控：新增第四态不得改动原有三个值的字面量（别的代码/测试可能在用）。

    这里逐个走一遍并断言字面量 —— 值一旦被改名，外部（CLI、报告、运维脚本）会
    静默地读不到自己认识的那个字符串。
    """
    assert (REASON_EMPTY, REASON_ALL_LEASED, REASON_ALL_IN_BACKOFF, REASON_NOTHING_CLAIMABLE) == (
        "no_pending_request",
        "pending_requests_all_leased",
        "pending_requests_all_in_backoff",
        "no_claimable_request",
    )

    a = _agent(store, CountingProvider())

    # 空
    empty = a._claim()
    assert empty.skipped_reason == "no_pending_request"

    # 全被放弃（attempts 用尽）⇒ 原有语义不许变
    add_request(store, "r-0001", attempts=3)
    gave = a._claim()
    assert gave.skipped_reason == "no_claimable_request" and gave.gave_up == 1

    # 全被别人持着 ⇒ 原有语义不许变
    add_request(store, "r-0001", claimed_by="agent-A-other", lease_until=FUTURE_LEASE)
    leased = a._claim()
    assert leased.skipped_reason == "pending_requests_all_leased"

    # 全在退避中 ⇒ 第四态
    add_request(store, "r-0001", claimed_by=None, lease_until=FUTURE_LEASE)
    backoff = a._claim()
    assert backoff.skipped_reason == "pending_requests_all_in_backoff"

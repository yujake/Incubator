"""I7 检索预算与优先级（DESIGN-INTERACTIONS.md §1 I7 / §4 验收）。

本文件只测两件事：A 按优先级取任务（`AgentA._claim` → `interactions.order_pending_requests`）；
准入闸门（`interactions.admit_search_request`：定优先级 + 超限拒绝）。时间戳一律写死常量
（不依赖"当前时间"），租约用固定的过去/未来时刻表示"已过期/有效"。

验收口径与每条负控（"构造它不该触发的场景，断言它确实没触发"）：
- 混合队列 → 先 high 后 low：``test_high_priority_is_claimed_before_low...``
- 同级 FIFO（timestamp），同 timestamp 按 request_id：``test_same_priority_is_fifo...total_order``
- 同级下：租约已过期 排在 租约仍在走 之前：``test_expired_lease_is_claimed_before_a_still_running_lease``
- 同级下：全新请求与过期租约平手（契约实测）：``test_fresh_request_and_expired_lease_tie_on_fifo...``
- 顺序只能来自 `interactions`（不许第二套判据）：``test_claim_order_comes_from_interactions_only``
- 顺序与优先级可从结果外部观察：``test_run_result_exposes_priority...``
- 负控 1：`done=True` 的（哪怕 high）永不被取：``test_done_request_is_never_claimed_even_if_high``
- 负控 2：租约未过期的（哪怕 high）永不被取：``test_active_lease_blocks_claim_even_if_high``
- 负控 3：超限时逐字节确认没有写入：``test_over_limit_is_rejected_and_writes_nothing``
- 四态：队列空 / 全被别人持着 / 全在退避中 / 全被放弃 必须可区分：``test_claim_skip_reasons_are_four_distinct_states``
- 退避租约（`claimed_by` 空 + 未来的 `lease_until`）不得被压进"全被别人持着"，被遵守：``tests/test_agent_a_backoff.py`` 整个文件
- 准入闸门：默认优先级表、非法值回退、陌生来源落 low：``test_admit_*``"""

from __future__ import annotations

import pytest

from agentflow import interactions as X
from agentflow import schema as S
from agentflow.agent_a import AgentA

from conftest import TS, read_data_bytes

# ---------------------------------------------------------------- 常量 / 替身

#: 固定时间戳（升序用）：一律写死，绝不取"当前时间"，保证可复现。
T1 = "2026-01-01T00:00:00+00:00"
T2 = "2026-01-02T00:00:00+00:00"
T3 = "2026-01-03T00:00:00+00:00"

#: 已过期的租约：表示"之前有 A 拿到却没做完"（应当被抢回来重试）。
PAST_LEASE = "2020-01-01T00:00:00+00:00"
#: 未过期的租约：表示"现在有 A 正在做"（不得被抢）。
FUTURE_LEASE = "2099-01-01T00:00:00+00:00"

#: `_claim()` 没取到请求时的四个原因。测试里写成常量，避免手抄字符串拼错
#: （拼错会让断言永远为真，这正是"看起来在测、实际没测"）。
REASON_EMPTY = "no_pending_request"
REASON_ALL_LEASED = "pending_requests_all_leased"
REASON_ALL_IN_BACKOFF = "pending_requests_all_in_backoff"
REASON_NOTHING_CLAIMABLE = "no_claimable_request"


class RecordingProvider:
    """永不返回候选、只记录"被问了什么"的 provider 替身（离线、确定性）。

    用它而不是 Mock：断言 `provider.calls` 就能证明取到的那条请求真的驱动了检索，
    而负控里则能证明"没取走的那条从未被检索过"。
    """

    name = "recording"

    def __init__(self):
        self.calls: list[str] = []

    def search(self, topic, mode, description, limit):
        self.calls.append(topic)
        return []


# ---------------------------------------------------------------- 工具


def _add_req(
    store,
    request_id: str,
    *,
    priority: str = "medium",
    timestamp: str = T1,
    done: bool = False,
    outcome: str | None = None,
    claimed_by: str | None = None,
    lease_until: str | None = None,
    attempts: int = 0,
    submitted_by: str = "agent-D",
    topic: str | None = None,
    mode: str = "broad",
    content_description: str = "",
) -> dict:
    """插入一条合法的 search_requests 行（含 I7 的 priority / submitted_by）。

    为什么不用 conftest 的 `add_request`：那个夹具没有 priority 参数，而
    "优先级被正确写进行"恰好是 I7 的前提。这里自建一个带校验的版本，
    不合法就当场炸（`row.validate()`），而不是让测试数据悄悄退化。
    """
    row = S.SearchRequest(
        request_id=request_id,
        timestamp=timestamp,
        topic=topic or f"主题-{request_id}",
        mode=mode,  # type: ignore[arg-type]
        content_description=content_description,
        done=done,
        submitted_by=submitted_by,
        claimed_by=claimed_by,
        lease_until=lease_until,
        attempts=attempts,
        outcome=outcome,
        priority=priority,
    )
    row.validate()
    with store.tx("search_requests", actor="test") as tx:
        tx.upsert("search_requests", row.to_dict())
    return row.to_dict()


def _agent(store, provider=None) -> AgentA:
    """A 实例：不下载、串行 provider（本文件只关心"取哪条"，不关心下载）。"""
    return AgentA(
        store,
        providers=[provider or RecordingProvider()],
        downloader=None,
        config={"download": False, "lease_seconds": 900, "max_attempts": 3},
    )


def _row(store, request_id: str) -> dict:
    return next(r for r in store.rows("search_requests") if r["request_id"] == request_id)


def _claim_ids(store, n: int, provider=None) -> list[str | None]:
    """连续跑 n 轮，返回每轮取到的 request_id（没取到是 None）。"""
    a = _agent(store, provider)
    return [a.run_once().request_id for _ in range(n)]


# ================================================================ 1. 按优先级取任务


def test_high_priority_is_claimed_before_low_even_if_submitted_later(store):
    """混合队列：low 先提交、high 后提交 ⇒ A 必须先取 high。

    这是 I7 的全部意义所在：需求里"知识不足就提问"会在 D 的循环里反复触发，
    低价值请求如果靠"谁先提谁先查"占住队首，关键矛盾就永远排在后面。
    """
    provider = RecordingProvider()
    _add_req(store, "r-0001", priority="low", timestamp=T1, submitted_by="agent-B")
    _add_req(store, "r-0002", priority="high", timestamp=T2, submitted_by="agent-D:contradiction")
    a = _agent(store, provider)

    first = a.run_once()
    assert first.request_id == "r-0002", "high 必须排在 low 之前（与提交先后无关）"
    assert first.priority == "high"
    assert first.priority_rank == S.PRIORITY_RANK["high"]
    assert first.submitted_by == "agent-D:contradiction"
    assert first.queue_pending == 2, "定序时队列里应当有 2 条待办"
    # 负控：这一轮没有动过那条 low（取走它才是错的）
    low = _row(store, "r-0001")
    assert low["attempts"] == 0 and low["claimed_by"] is None and low["done"] is False

    second = a.run_once()
    assert second.request_id == "r-0001"
    assert second.priority == "low"
    assert second.priority_rank == S.PRIORITY_RANK["low"]
    assert provider.calls == ["主题-r-0002", "主题-r-0001"], "检索顺序必须与取任务顺序一致"


def test_same_priority_is_fifo_by_timestamp_then_request_id_total_order(store):
    """同优先级 ⇒ 按 timestamp FIFO；timestamp 相同时 ⇒ 按 request_id 兜底（全序）。

    为什么必须断言完整序列而不是"第一条是谁"：若排序键里少了 request_id 兜底，
    Python 的 sorted 是稳定的，同 timestamp 的那些行会按文件里的存放顺序出队 ——
    于是"哪条先被取"取决于插入顺序，断言会随机失败（或随机通过）。
    """
    # 故意乱序插入：r-0003 最先写、r-0002 最后写
    _add_req(store, "r-0003", priority="medium", timestamp=T3)
    _add_req(store, "r-0001", priority="medium", timestamp=T1)
    _add_req(store, "r-0002", priority="medium", timestamp=T1)

    assert _claim_ids(store, 3) == ["r-0001", "r-0002", "r-0003"]


def test_expired_lease_is_claimed_before_a_still_running_lease(store):
    """同优先级下，租约已过期的请求排在"租约仍在走"的请求之前（收回沉没成本）。

    一条"有人拿到却没做完、租约已经烂掉"的请求，重试它比从零开始更接近完成；而租约仍在走的
    请求（上一轮搜索失败后 A 自己设的退避租约）应当往后排，免得反复重打同一个上游 API。

    措辞照着 `interactions.order_pending_requests` 的真实判据写，不是照抄设计文档：契约把
    "租约为空（无人持有）"与"租约已过期"放进同一个桶，两者都排在"租约仍在走"之前（实测证据与
    后果见 ``test_fresh_request_and_expired_lease_tie_on_fifo_instead_of_jumping_queue``）。

    旧断言 `second.request["request_id"] == "r-0001"` 编码的是一个缺陷行为（"退避租约
    （`claimed_by` 为空 + 未来的 `lease_until`）可以在同一进程里立刻被重领"），已按"租约仍在
    有效期内就得跳过，不管 `claimed_by` 是谁"改正 —— 详见下面那段负控与 `tests/test_agent_a_backoff.py`。"""
    _add_req(store, "r-0001", priority="medium", timestamp=T1, lease_until=FUTURE_LEASE)  # 退避中（租约仍在走）
    _add_req(
        store,
        "r-0002",
        priority="medium",
        timestamp=T2,  # 提交更晚
        attempts=1,
        claimed_by="agent-A-dead",
        lease_until=PAST_LEASE,
    )

    # 直接看 `_claim()`（而不是 `run_once()`）：跑完一轮之后 claimed_by 会被清空，
    # 而"这条过期租约是不是被抢回来了"恰恰只有在领取那一刻才看得见。
    a = _agent(store)
    first = a._claim()
    assert first.request is not None and first.request["request_id"] == "r-0002"
    assert first.request["claimed_by"] == a.actor, "过期租约必须被本轮 A 接管"
    assert first.request["attempts"] == 2, "attempts 必须继续累加（不是重新开始）"

    # 负控（修复后新增，替换掉旧断言 `second.request["request_id"] == "r-0001"`）：
    # 那条"退避中"的 r-0001 不得被领走。旧断言的错误在于：它把"退避租约"
    # 当成了"现在可以领"，于是"写了退避租约"这件事从来没有被任何测试读过一次 ——
    # 一个只断言"写入了"的测试，无法发现"没有任何地方读它"。
    second = a._claim()
    assert second.request is None, "退避租约必须被遵守：claimed_by 为空 ≠ 现在可以领"
    assert second.skipped_lease_backoff == 1, "退避中的那条要单独计数（不是'被别人持着'）"
    assert second.skipped_lease_active == 1, "r-0002 是本轮刚领下的有效租约 ⇒ 算'活跃'那一类"
    # 混合情形（一条被别人/自己持着 + 一条在退避）⇒ 诚实的 `no_claimable_request`：
    # 前两类 reason 都要求整队都是那一种情形，所以这里不许谎报成其中任何一类。
    assert second.skipped_reason == REASON_NOTHING_CLAIMABLE
    assert _row(store, "r-0001")["attempts"] == 0, "退避中的那条不得被尝试"


def test_fresh_request_and_expired_lease_tie_on_fifo_instead_of_jumping_queue(store):
    """契约实测：全新请求与"租约已过期"的请求在排序上平手，由 FIFO 决定先后。

    这条是被实测逼出来的，不是想当然：`order_pending_requests` 里
    ``exp = True if not lease_until else lease_expired(lease_until)``
    —— 空租约被视为"可立刻取走"，于是它和"已过期的租约"落进同一个桶
    （bucket 0），"仍在走的租约"才是 bucket 1。

    后果（也正是这样才安全）：死掉的租约既不会插队、也不会被饿死，
    它按提交时间正常轮到 —— 设计担心的"死掉的租约永远烂在队里"不会发生，
    但它也不是靠"排在全新请求前面"来实现的。这一点必须写明，
    否则将来有人照着"过期优先"的措辞去改判据，会把退避租约一起改坏。
    """
    provider = RecordingProvider()
    _add_req(store, "r-0001", priority="medium", timestamp=T1)  # 全新
    _add_req(
        store,
        "r-0002",
        priority="medium",
        timestamp=T2,
        attempts=1,
        claimed_by="agent-A-dead",
        lease_until=PAST_LEASE,
    )

    a = _agent(store, provider)
    assert [a.run_once().request_id for _ in range(2)] == ["r-0001", "r-0002"], "同桶 ⇒ 按 timestamp FIFO"
    assert provider.calls == ["主题-r-0001", "主题-r-0002"], "过期租约那一轮**确实**被检索了（没被饿死）"
    stale = _row(store, "r-0002")
    assert stale["attempts"] == 2 and stale["done"] is True and stale["claimed_by"] is None


def test_claim_order_comes_from_interactions_only(store, monkeypatch):
    """A 的取任务顺序必须完全来自 `interactions.order_pending_requests`。

    做法：把契约函数换成"故意给错顺序"的替身（按 request_id 升序，即让 low 先出队），
    断言 A 真的照着它取。若 agent_a 里又长出一套自己的排序，行为测试仍可能碰巧
    通过（同级 FIFO 两种实现结果一样），但这一条会立刻失败 —— 这正是
    "两个模块各持一套判据 ⇒ 静默漂移"的守卫。
    """
    _add_req(store, "r-0001", priority="low", timestamp=T1)
    _add_req(store, "r-0002", priority="high", timestamp=T2)

    def wrong_order(rows, **kwargs):  # noqa: ARG001 - 替身只需签名兼容
        return sorted((dict(r) for r in rows if not r.get("done")), key=lambda r: r["request_id"])

    monkeypatch.setattr(X, "order_pending_requests", wrong_order)
    res = _agent(store).run_once()
    assert res.request_id == "r-0001", "A 必须服从 interactions 给的顺序（哪怕是错的），不许自己排序"


def test_run_result_exposes_priority_and_skipped_lease_count(store):
    """`run()` 的返回里必须能看出优先级与"被有效租约挡住"的条数 —— 否则 I7 不可观察。

    队列：r-0001 low / r-0002 high（被别人的有效租约占着）/ r-0003 medium。
    正确行为：high 那条虽然排在最前，但不能被抢 ⇒ 依次做掉 medium、low，
    最后停在"全被租约挡住"。
    """
    _add_req(store, "r-0001", priority="low", timestamp=T1)
    _add_req(store, "r-0002", priority="high", timestamp=T2, claimed_by="agent-A-other", lease_until=FUTURE_LEASE)
    _add_req(store, "r-0003", priority="medium", timestamp=T3)

    out = _agent(store).run()

    assert out["processed"] == 2, "被有效租约占着的 high 不该被处理"
    assert out["request_id"] == "r-0001" and out["priority"] == "low", "最后处理的是 low 那条"
    assert out["skipped_lease_active"] >= 1, "必须报出'因租约未过期而跳过'的条数"
    assert out["skipped_reason"] == REASON_ALL_LEASED
    assert _row(store, "r-0002")["attempts"] == 0, "被租约挡住的那条不得被尝试"


def test_missing_priority_is_treated_as_low_not_medium(store):
    """缺 `priority` 键的历史行按 low 排序（fail-safe），而不是按 schema 默认的 medium。

    这是一个已记录的口径分歧（见最终报告），不是"修好了"：
    - `schema.SearchRequest.priority` 的默认值是 `"medium"`（新写入的行都会带上它）；
    - 而 `interactions.priority_rank(None)` ⇒ `low`（契约的显式选择：来源不明的行不许插队）。

    对"历史快照里没有这个键的行"，两条口径给出不同答案（校验说 medium、排序说 low）。
    今天没有实际影响（能走到 A 的 pending 行都由带 priority 的代码写入），
    但它是"同一个字段两处口径"的形态，所以在这里把行为钉住：
    排序口径以 `interactions` 为准，A 不擅自替历史行补一个优先级。
    """
    with store.tx("search_requests", actor="test") as tx:
        tx.upsert(
            "search_requests",
            {
                "request_id": "r-0001",
                "timestamp": T1,
                "topic": "历史行（无 priority 键）",
                "mode": "broad",
                "content_description": "",
                "done": False,
                "submitted_by": "unknown",
                "claimed_by": None,
                "lease_until": None,
                "attempts": 0,
                "result_lit_ids": [],
                "last_error": None,
                "outcome": None,
            },
        )
    _add_req(store, "r-0002", priority="medium", timestamp=T2)

    assert _row(store, "r-0001").get("priority") is None, "夹具本身要真的缺这个键"
    assert _claim_ids(store, 2) == ["r-0002", "r-0001"], "缺优先级的行不得插到显式 medium 前面"
    assert X.priority_rank(None) == S.PRIORITY_RANK["low"]
    # 记录分歧本身：schema 的默认值是 medium（新行），排序对"缺键"给 low
    assert S.SearchRequest(request_id="r-0009", timestamp=T1, topic="t", mode="broad").priority == "medium"


# ================================================================ 2. 负控：不该被取的


def test_done_request_is_never_claimed_even_if_high(store):
    """负控 1：`done=True` 的请求永远不被取 —— 哪怕它是 high 且时间戳最早。

    这条防的是"按优先级排序时把 done 忘掉"：排序函数很好写对，过滤条件却容易漏，
    而漏掉的后果是已完成的请求被反复重跑（重复登记文献/重复烧检索配额）。
    """
    provider = RecordingProvider()
    _add_req(store, "r-0001", priority="high", timestamp=T1, done=True, outcome="no_results")
    _add_req(store, "r-0002", priority="low", timestamp=T2)
    a = _agent(store, provider)
    done_before = dict(_row(store, "r-0001"))

    res = a.run_once()

    assert res.request_id == "r-0002", "high 但已完成 ⇒ 必须让位给待办的 low"
    assert res.queue_pending == 1, "已完成的请求不计入待办队列"
    assert provider.calls == ["主题-r-0002"], "已完成的那条不得被检索"
    assert _row(store, "r-0001") == done_before, "已完成的行必须逐字段原样保留"
    assert _row(store, "r-0001")["attempts"] == 0 and _row(store, "r-0001")["claimed_by"] is None

    # 再跑一轮：队列里已经没有待办（那条 done 的仍然不算）
    empty = a.run_once()
    assert empty.request_id is None and empty.skipped_reason == REASON_EMPTY
    assert provider.calls == ["主题-r-0002"], "两轮下来 provider 只该被调用一次"


def test_active_lease_blocks_claim_even_if_high(store):
    """负控 2：`claimed_by` 非空且租约未过期的请求不被取 —— 哪怕它是 high。

    这是"只排队、不抢占"的硬边界：抢一条别人正在跑的活，会让两条请求都变慢，
    还会留下半成品。这里既断言"A 去做了别的"，也断言"那条 high 一行都没被改动"。
    """
    provider = RecordingProvider()
    _add_req(
        store,
        "r-0001",
        priority="high",
        timestamp=T1,
        attempts=1,
        claimed_by="agent-A-other",
        lease_until=FUTURE_LEASE,
    )
    _add_req(store, "r-0002", priority="low", timestamp=T2)
    a = _agent(store, provider)
    leased_before = dict(_row(store, "r-0001"))

    first = a.run_once()
    assert first.request_id == "r-0002"
    assert first.queue_pending == 2, "被租约挡住的请求**仍算在待办队列里**（它并没有完成）"
    assert first.skipped_lease_active == 1
    assert provider.calls == ["主题-r-0002"], "别人的活不得被检索"
    assert _row(store, "r-0001") == leased_before, "不得改动别人持租约的那一行"

    # 队列里只剩那条被租约挡住的：A 必须停下并说清原因，而不是把它抢来做
    second = a.run_once()
    assert second.request_id is None
    assert second.skipped_reason == REASON_ALL_LEASED
    assert second.skipped_lease_active == 1
    assert _row(store, "r-0001") == leased_before
    assert provider.calls == ["主题-r-0002"]


def test_claim_skip_reasons_are_four_distinct_states(store):
    """四态：队列空 / 全被别人持租约 / 全在退避中 / 全被当场放弃 ⇒ 四个不同的原因。

    把四者压成同一个 `None`（或同一个 "no_pending_request"）会让运维误判：
    看到"没有待办"就不会去查那条躺着等租约的 high 请求。这里对四种状态分别构造，
    并断言原因两两不同、且都显式带上了"没取到"的语义。

    第四态（全在退避中）是修复后新增的：它的行形状是 ``claimed_by=None`` +
    未来的 `lease_until`（`run_once` 在搜索失败时写下的退避租约）。修复之前这种行
    会被压进 `pending_requests_all_leased`，而那句诊断说的是"别人持着" ——
    与事实不符（那是我们自己上次失败留下的），会把运维引去找一个不存在的
    另一个 A 实例。所以它必须单独命名、单独计数。
    """
    a = _agent(store)
    empty = a._claim()
    assert empty.request is None and empty.pending == 0 and empty.skipped_reason == REASON_EMPTY

    _add_req(store, "r-0001", priority="high", claimed_by="agent-A-other", lease_until=FUTURE_LEASE)
    leased = a._claim()
    assert leased.request is None and leased.pending == 1
    assert leased.skipped_reason == REASON_ALL_LEASED
    assert leased.skipped_lease_active == 1 and leased.gave_up == 0
    assert leased.skipped_lease_backoff == 0, "别人持着的不得被算进'退避'"

    # 再插一条已经用尽尝试次数的请求：它会被当场放弃（done=true + outcome=gave_up）
    _add_req(store, "r-0002", priority="low", attempts=3)
    claim = a._claim()
    assert claim.request is None and claim.pending == 2
    assert claim.skipped_reason == REASON_NOTHING_CLAIMABLE
    assert claim.gave_up == 1, "放弃条数必须被数出来（它曾经恒为 0，见 agent_a 的注释）"
    gave_up_row = _row(store, "r-0002")
    assert gave_up_row["done"] is True and gave_up_row["outcome"] == "gave_up"
    assert "超过最大尝试次数" in (gave_up_row["last_error"] or "")

    # 第四态：整队都躺在我们自己的退避租约里（claimed_by 为空 + 租约未过期）。
    # 覆盖写 r-0001 成退避形状（`_add_req` 默认 claimed_by=None）；r-0002 已 done ⇒ 不计入待办。
    _add_req(store, "r-0001", priority="high", lease_until=FUTURE_LEASE)
    backoff = a._claim()
    assert backoff.request is None and backoff.pending == 1
    assert backoff.skipped_reason == REASON_ALL_IN_BACKOFF
    assert backoff.skipped_lease_backoff == 1 and backoff.skipped_lease_active == 0
    assert backoff.gave_up == 0
    assert _row(store, "r-0001")["attempts"] == 0, "退避中的那条不得被尝试"
    assert REASON_ALL_IN_BACKOFF != REASON_ALL_LEASED, "退避 ≠ 被别人持着（诊断文字不能撒谎）"

    reasons = {empty.skipped_reason, leased.skipped_reason, claim.skipped_reason, backoff.skipped_reason}
    assert len(reasons) == 4, f"四种状态不许混淆：{sorted(reasons)}"


# ================================================================ 3. 准入闸门（提交侧）


def test_over_limit_is_rejected_and_writes_nothing(store):
    """负控 3：在途数 = 上限 ⇒ `admitted=False`，且逐字节确认没有写入。

    "拒绝而不是无限排队"的意义：队列无上限时，循环里的提交方永远感觉不到压力，
    于是"知识不足就提问"退化成"每轮都问"，A 的固定产能被摊薄，
    连最关键的那条矛盾也一起变慢。拒绝会把压力传导回提交方（让它自己决定值不值得问）。
    """
    _add_req(store, "r-0001", priority="medium")
    _add_req(store, "r-0002", priority="medium")
    before = read_data_bytes(store)
    before_ids = [r["request_id"] for r in store.rows("search_requests")]

    adm = X.admit_search_request(store.rows("search_requests"), submitted_by="agent-C", max_inflight=2)

    assert adm["admitted"] is False
    assert adm["inflight"] == 2 and adm["limit"] == 2
    assert adm["reason"], "拒绝必须带 reason —— 三态纪律：False 不许是'没检查'的替身"
    assert "拒绝" in adm["reason"]
    assert adm["priority"] == S.SUBMITTER_DEFAULT_PRIORITY["agent-C"]
    # 重复断言一次 `admitted` 的取值类型：`0`/`""` 这类"假值"不算 False
    assert adm["admitted"] is not True

    after = read_data_bytes(store)
    assert after == before, "被拒的提交不得产生任何写入（含 events.jsonl）"
    assert (store.data / "search_requests.json").read_bytes() == before["search_requests.json"]
    assert [r["request_id"] for r in store.rows("search_requests")] == before_ids

    # 让这条负控非空洞：同样的调用把上限放宽一条就必须放行，
    # 否则"被拒"可能只是因为别的原因（提交方没登记、参数写错……）。
    relaxed = X.admit_search_request(store.rows("search_requests"), submitted_by="agent-C", max_inflight=3)
    assert relaxed["admitted"] is True and relaxed["inflight"] == 2 and relaxed["limit"] == 3


def test_caller_pattern_writes_nothing_when_rejected(store):
    """按 I7 的调用方契约走一遍：`admitted=False` 时调用方跳过写入。

    这是 D 的 `submit_gap` / C 的 I3 应当照抄的形态（本任务不实现它们，只把契约测透）。
    断言的是"闸门 + 调用方"这一对：闸门自己是无锁纯函数（`interactions` 导入期已自检
    签名里没有 store/tx），所以"有没有写"取决于调用方是否照契约办事。
    """

    def submit(store, request_id: str, *, max_inflight: int):
        with store.tx("search_requests", actor="agent-C", note="test.submit") as tx:
            adm = X.admit_search_request(tx.rows("search_requests"), submitted_by="agent-C", max_inflight=max_inflight)
            if not adm["admitted"]:
                return adm  # 不写任何东西；把决定权交回提交方
            row = S.SearchRequest(
                request_id=request_id, timestamp=TS, topic=f"主题-{request_id}", mode="broad", priority=adm["priority"]
            )
            row.validate()
            tx.upsert("search_requests", row.to_dict(), note="submitted")
            return adm

    _add_req(store, "r-0001")
    before = read_data_bytes(store)
    rejected = submit(store, "r-9001", max_inflight=1)
    assert rejected["admitted"] is False
    assert read_data_bytes(store) == before, "拒绝路径不得留下任何字节变化"

    admitted = submit(store, "r-9001", max_inflight=2)
    assert admitted["admitted"] is True
    assert _row(store, "r-9001")["priority"] == S.SUBMITTER_DEFAULT_PRIORITY["agent-C"]


@pytest.mark.parametrize("submitter,expected", sorted(S.SUBMITTER_DEFAULT_PRIORITY.items()))
def test_admit_resolves_default_priority_from_submitter(store, submitter, expected):
    """在途 < 上限 ⇒ 放行，且 `priority` 必须按 `SUBMITTER_DEFAULT_PRIORITY` 解析。

    直接对着那张受控表参数化：表改了而闸门没跟上（或反过来）会立刻炸，
    而不是变成"某天 high 悄悄变成了 medium"。
    """
    adm = X.admit_search_request(store.rows("search_requests"), submitted_by=submitter, max_inflight=1)
    assert adm["admitted"] is True
    assert adm["priority"] == expected
    assert adm["inflight"] == 0 and adm["limit"] == 1
    assert submitter in adm["priority_why"] or expected in adm["priority_why"]


def test_admit_explicit_priority_wins_and_illegal_falls_back(store):
    """显式优先级合法则直接用；非法则回退到默认，且 `priority_why` 要说清是回退。

    为什么非法值不能"静默当成 low"：回退与"提交方本来就想要 low"是两回事，
    混在一起之后没人能查出"我明明写了 urgent，为什么排在后面"。
    """
    ok = X.admit_search_request(store.rows("search_requests"), submitted_by="agent-B", explicit_priority="high")
    assert ok["admitted"] is True and ok["priority"] == "high"
    assert "显式" in ok["priority_why"]

    bad = X.admit_search_request(store.rows("search_requests"), submitted_by="agent-B", explicit_priority="urgent")
    assert bad["priority"] == S.SUBMITTER_DEFAULT_PRIORITY["agent-B"] == "low"
    assert "非法" in bad["priority_why"] and "回退" in bad["priority_why"], bad["priority_why"]
    # 回退但仍然放行：非法优先级是"排队位置错了"，不是"这条请求不该进队"
    assert bad["admitted"] is True

    bad_d = X.admit_search_request(store.rows("search_requests"), submitted_by="agent-D", explicit_priority=123)
    assert bad_d["priority"] == "medium", "非法值必须回退到**该提交方**的默认，而不是一律 low"
    assert "回退" in bad_d["priority_why"]


def test_admit_unregistered_submitter_falls_to_low(store):
    """未登记的提交方（如 `agent-X`）⇒ 落到 `low`：宁可不给它插队，也不要让它插队。"""
    adm = X.admit_search_request(store.rows("search_requests"), submitted_by="agent-X", max_inflight=5)
    assert adm["admitted"] is True
    assert adm["priority"] == "low"
    assert "未登记" in adm["priority_why"], adm["priority_why"]


def test_admit_limit_default_is_high_and_is_overridable(store):
    """`DEFAULTS["max_inflight_requests"]` 现在是 200（业主 2026-10-15 裁定 C9：
    20 → 200，「凡是可能阻止智能体完成大项目的……抬到几乎不可能触发」），
    但 `max_inflight` 仍可覆盖（含 0）。"""
    assert X.DEFAULTS["max_inflight_requests"] == 200

    # 空队列 + 上限 0 ⇒ 仍然拒绝：上限是"允许在途多少条"，0 就是一条都不许
    zero = X.admit_search_request(store.rows("search_requests"), submitted_by="human", max_inflight=0)
    assert zero["admitted"] is False and zero["inflight"] == 0 and zero["limit"] == 0
    assert zero["reason"], "拒绝了就必须说清为什么"

    for i in range(199):
        _add_req(store, f"r-{i + 1:04d}")
    rows = store.rows("search_requests")
    under = X.admit_search_request(rows, submitted_by="human")
    assert under["admitted"] is True and under["inflight"] == 199 and under["limit"] == 200

    _add_req(store, "r-0200")
    rows = store.rows("search_requests")
    at = X.admit_search_request(rows, submitted_by="human")
    assert at["admitted"] is False and at["inflight"] == 200 and at["limit"] == 200

    # 覆盖成小值同样生效
    _add_req(store, "r-0201")
    rows = store.rows("search_requests")
    assert X.admit_search_request(rows, submitted_by="human", max_inflight=1)["admitted"] is False


def test_admit_counts_only_unfinished_requests_as_inflight(store):
    """在途的口径只有一条：`done` 为假。已完成的请求不占配额。"""
    _add_req(store, "r-0001", done=True, outcome="no_results")
    _add_req(store, "r-0002")
    rows = store.rows("search_requests")

    adm = X.admit_search_request(rows, submitted_by="agent-D", max_inflight=2)
    assert adm["admitted"] is True and adm["inflight"] == 1, "done 的那条不该占在途额度"

    full = X.admit_search_request(rows, submitted_by="agent-D", max_inflight=1)
    assert full["admitted"] is False and full["inflight"] == 1 and full["limit"] == 1

"""取消语义测试（FC-20 的四条纪律）。

`CancelToken` 是跨层的东西（主控按停止、调度器传进每个在飞任务、
handler 在关键点检查）。它出错的方式全部是"静默的"：取消只对某一层生效——
点了停止之后还有三个任务在跑，而不会报任何错。
所以这里的每一条纪律都有一条正向断言 + 一条负控。
"""

from __future__ import annotations

import threading
import time

import pytest

from agentflow.cancellation import (
    CANCEL_CODES,
    CancelReason,
    CancelRequested,
    CancelToken,
    detail_of,
)


# ---------------------------------------------------------------- 基本语义


def test_token_starts_uncancelled_with_no_reason():
    """三态：`cancelled` 永远是 bool（有答案），`reason` 在没取消时是 None。

    "没有理由"与"理由是空字符串"必须能区分 —— 后者会被台账读成
    "取消了一次，但说不出为什么"，而前者是"根本没取消"。
    """
    t = CancelToken()
    assert t.cancelled is False
    assert t.reason is None


def test_cancel_sets_flag_and_reason():
    t = CancelToken()
    r = t.cancel("user", detail="人按了停止", by="user")
    assert t.cancelled is True
    assert t.reason is not None and t.reason.code == "user"
    assert r.detail == "人按了停止"
    assert t.to_dict()["reason"]["code"] == "user"


def test_cancel_is_idempotent_first_wins():
    """纪律 2 的对应物：第二次取消不改变第一次的理由。

    为什么连 reason 都不能改：它会被写进台账的 `detail`，
    而"为什么停的"必须只有一个答案 —— 两个答案等于没有答案。
    """
    t = CancelToken()
    first = t.cancel("user", detail="第一次", by="user")
    second = t.cancel("dispose", detail="第二次", by="conductor.dispose")
    third = t.cancel("deadline", detail="第三次", by="deadline")
    assert second == first and third == first
    assert t.reason is not None and t.reason.code == "user"
    assert t.reason.detail == "第一次"


def test_cancel_negative_control_reason_is_not_overwritten():
    """负控：如果实现是"后写覆盖"，上面那条测试会过；这条专门钉住"不许覆盖"。

    它检查的是中间态不存在：一个已取消的 token 上再取消，
    无论调多少次、从哪个线程调，`reason` 都必须逐字段等于第一次。
    """
    t = CancelToken()
    t.cancel("budget", detail="预算耗尽", by="conductor")
    snapshot = (t.reason.code, t.reason.detail, t.reason.by, t.reason.outcome_known)  # type: ignore[union-attr]
    for i in range(50):
        t.cancel(f"reason-{i}", detail=f"第 {i} 次", by=f"caller-{i}")
    assert (t.reason.code, t.reason.detail, t.reason.by, t.reason.outcome_known) == snapshot  # type: ignore[union-attr]


def test_raise_if_cancelled_raises_only_when_cancelled():
    """协作式取消的全部实现：取消是请求，不是强杀。"""
    t = CancelToken()
    t.raise_if_cancelled()  # 没取消 ⇒ 什么都不做（不抛）
    t.cancel("user", detail="停")
    with pytest.raises(CancelRequested):
        t.raise_if_cancelled()


def test_cancel_requested_is_not_an_error():
    """`CancelRequested` 必须能被普通 `except Exception` 捕获。

    否则它会穿过 `Conductor.finish()` 的兜底逻辑，让任务永远停在 running
    —— 一个僵尸。这是"继承 Exception 而不是 BaseException"的真实理由。
    """
    t = CancelToken()
    t.cancel("user")
    caught = False
    try:
        t.raise_if_cancelled()
    except Exception as e:  # noqa: BLE001 - 这里正是要证明它能被 Exception 捕获
        caught = isinstance(e, CancelRequested)
    assert caught


def test_reason_code_is_controlled_vocabulary():
    """受控词表：自由文本的取消原因无法统计，也无法被 verify 检查。"""
    assert "user" in CANCEL_CODES and "deadline" in CANCEL_CODES
    assert "dispose" in CANCEL_CODES and "budget" in CANCEL_CODES


def test_detail_of_never_returns_empty_string():
    """负控：`None` 理由必须渲染成"未给出理由"，不是空串。

    空串在台账里与"这一列没填"长得一样，而"取消了但说不出为什么"
    是一件需要被看见的事。
    """
    assert detail_of(None) == "取消（未给出理由）"
    assert detail_of(None) != ""
    assert "预算" in detail_of(CancelReason("budget", "预算耗尽"))


# ---------------------------------------------------------------- 三态与结果未知


def test_outcome_known_is_false_on_cancel():
    """纪律 4：被取消的任务结果是 unknown，不是"失败"。

    一个被中途砍掉的实验可能已经写了半张表，声称它"失败"是过度声称。
    """
    t = CancelToken()
    r = t.cancel("dispose", detail="进程要走了")
    assert r.outcome_known is False


def test_with_deadline_creates_self_cancelling_token():
    """`deadline` 的性质是"没人按按钮它也会到" —— 不需要任何线程去通知它。"""
    t = CancelToken.with_deadline(0.05)
    assert t.cancelled is False
    time.sleep(0.08)
    assert t.cancelled is True
    assert t.reason is not None and t.reason.code == "deadline"
    assert t.reason.outcome_known is False


def test_with_deadline_rejects_non_positive():
    """负控：0 或负数的 deadline 必须被拒。

    否则 `with_deadline(0)` 会造出一个"出生就已取消"的 token，
    而调用方以为自己设了一个（很小的）期限。
    """
    with pytest.raises(ValueError):
        CancelToken.with_deadline(0)
    with pytest.raises(ValueError):
        CancelToken.with_deadline(-1)


def test_deadline_reason_is_lazy_but_repeatable():
    """到点后的理由要稳定：反复读 `reason` 必须得到同一个 code。"""
    t = CancelToken.with_deadline(0.02)
    time.sleep(0.05)
    codes = {t.reason.code for _ in range(20)}  # type: ignore[union-attr]
    assert codes == {"deadline"}


def test_manual_cancel_beats_deadline():
    """first-wins 也覆盖"人先按的"与"到点"的竞争：先发生的赢。"""
    t = CancelToken.with_deadline(5.0)
    t.cancel("user", detail="人先按的")
    assert t.reason is not None and t.reason.code == "user"


# ---------------------------------------------------------------- token 预算


def test_token_budget_exhaustion_turns_into_cancellation():
    """预算耗尽与取消走同一个信号：处置完全一样（停止派新 + 取消在跑）。

    分成两套信号会让"停止"出现两条路径，而其中一条一定会被漏掉。
    """
    t = CancelToken(token_budget=10)
    assert t.consume_tokens(4) is True
    assert t.consume_tokens(4) is True
    assert t.cancelled is False
    assert t.consume_tokens(4) is False, "花到 12 >= 10 ⇒ 返回 False（还没超时返回 True）"
    assert t.cancelled is True
    assert t.reason is not None and t.reason.code == "budget"


def test_token_budget_none_means_unlimited():
    """负控：`None`（不限）不许被当成 0（已耗尽）。"""
    t = CancelToken(token_budget=None)
    for _ in range(100):
        assert t.consume_tokens(10**6) is True
    assert t.cancelled is False
    assert t.reason is None


def test_consume_tokens_ignores_negative():
    """负数消耗不许把预算"充回来" —— 那会让超支被静默抹平。"""
    t = CancelToken(token_budget=10)
    t.consume_tokens(10)
    assert t.cancelled is True
    t.consume_tokens(-100)
    assert t.tokens_used == 10


# ---------------------------------------------------------------- 线程安全


def test_cancel_is_thread_safe_first_wins():
    """一个共享 signal 会被多个线程同时读到（主线程取消、worker 检查）。

    这条测试不是"跑一遍看看有没有崩"，而是断言一个不变量：
    50 个线程同时取消，最终 state 必须恰好是其中一个（不许出现混合态）。
    """
    t = CancelToken()
    barrier = threading.Barrier(50)

    def worker(i: int) -> None:
        barrier.wait()
        t.cancel(f"reason-{i}", detail=f"d{i}", by=f"t{i}")
        # 每个线程还要读一次：读到的必须是完整的 (code, detail, by) 三元组
        r = t.reason
        assert r is not None
        assert r.detail == f"d{r.code.split('-')[1]}" and r.by == f"t{r.code.split('-')[1]}"

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(50)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    assert t.cancelled is True
    code = t.reason.code  # type: ignore[union-attr]
    i = code.split("-")[1]
    assert (t.reason.detail, t.reason.by) == (f"d{i}", f"t{i}")  # type: ignore[union-attr]


def test_cancel_while_readers_spin():
    """负控：读线程在取消的同时不停读，不许读到"已取消但没有理由"。

    这正是 `cancel()` 里"先写 reason 再置 flag"的顺序所保护的东西：
    顺序反过来时，读线程会看到一个 `cancelled=True, reason=None` 的中间态，
    而 `detail_of(None)` 会把"预算耗尽"写成"未给出理由" ——
    一条内容错误但看起来正常的台账。
    """
    t = CancelToken()
    bad: list[str] = []
    stop = threading.Event()

    def reader() -> None:
        while not stop.is_set():
            if t.cancelled:
                if t.reason is None:
                    bad.append("cancelled 但 reason is None（中间态泄漏）")
                return

    readers = [threading.Thread(target=reader) for _ in range(8)]
    for th in readers:
        th.start()
    time.sleep(0.01)
    t.cancel("budget", detail="预算耗尽", by="conductor")
    stop.set()
    for th in readers:
        th.join(timeout=2.0)
    assert bad == []

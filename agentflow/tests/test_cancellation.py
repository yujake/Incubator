"""取消语义测试（FC-20 的四条纪律）。

`CancelToken` 是跨层的东西（主控按停止、调度器传进每个在飞任务、
handler 在关键点检查）。它出错的方式全部是"静默的"：取消只对某一层生效——
点了停止之后还有三个任务在跑，而不会报任何错。
所以这里的每一条纪律都有一条正向断言 + 一条负控。
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from agentflow.cancellation import (
    CANCEL_BY_VALUES,
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


# ---------------------------------------------------------------- G-24 ③：`by` 的受控词表


def test_cancel_by_values_are_all_really_produced_in_src() -> None:
    """正控（`G-24` ③）：`CANCEL_BY_VALUES` 里每一条都必须真的能在 `src/` 里找到产出点。

    这条防的是"编造一个取值"：G-25 的 ② 就是同一个病的另一面
    （文档声称了一个代码里没有的行为）。一个只在词表里存在的 `by` 值，
    会让读词表的人以为"系统会在这种情况下报它"，从而不再自己核对。
    """
    src = Path(__file__).resolve().parents[1] / "src" / "agentflow"
    blob = "\n".join(
        p.read_text(encoding="utf-8")
        for p in sorted(src.rglob("*.py"))
    )
    for v in CANCEL_BY_VALUES:
        # 两种产出形态：显式传参 `by="x"`，或参数默认值 `by: str = "x"`。
        assert f'by="{v}"' in blob or f'by: str = "{v}"' in blob, (
            f"CANCEL_BY_VALUES 里的 {v!r} 在 src/ 里找不到产出点 ⇒ 这是一个编造的值"
        )


def test_cancel_by_vocab_negative_control_an_invented_value_is_detected() -> None:
    """负控：往词表里塞一个不存在的取值 ⇒ 上面那条判据必须变红。

    没有这条，正控在"词表是空元组"时也会绿（循环一次都不跑）。
    """
    src = Path(__file__).resolve().parents[1] / "src" / "agentflow"
    blob = "\n".join(p.read_text(encoding="utf-8") for p in sorted(src.rglob("*.py")))
    invented = "definitely_not_a_real_cancel_source"
    assert invented not in CANCEL_BY_VALUES, "前提：它本来不在词表里"
    found = f'by="{invented}"' in blob or f'by: str = "{invented}"' in blob
    assert found is False, "编造的取值不该在 src/ 里找得到 —— 否则这条负控失去意义"


def test_cancel_by_is_not_a_hard_enum_so_callers_keep_their_own_label() -> None:
    """`by` 刻意不是硬枚举：调用方自定义标签必须仍然被接受（审计信息只许变多）。

    与 `code` 对比：`code` 是封闭词表（`CANCEL_CODES`），`by` 不是。
    两者都不许互换 —— 把 `by` 锁成枚举会拒掉合法调用方，并让
    "谁喊的停"这条信息变少。
    """
    t = CancelToken()
    r = t.cancel("user", detail="调用方自定义标签", by="caller-with-my-own-name")
    assert r.by == "caller-with-my-own-name"
    assert "caller-with-my-own-name" not in CANCEL_BY_VALUES
    # `code` 那一侧仍然是封闭的：词表外的 code 由 `Conductor._signal_stop` 拒绝
    # （这里只断言词表本身没被放宽成"什么都收"）。
    assert isinstance(CANCEL_CODES, tuple) and "user" in CANCEL_CODES


def test_cancel_reason_default_by_is_registered() -> None:
    """`CancelReason` 的默认 `by` 必须在词表里 —— 否则"没记谁喊的"这一档无处可查。"""
    assert CancelReason("user").by in CANCEL_BY_VALUES
    assert "unknown" in CANCEL_BY_VALUES
    # `Conductor.cancel` 的默认 `by="user"`：这是一个会被真的用到的取值，
    # 不许因为"文档读起来像是没用到"就把它从词表里删掉。
    assert "user" in CANCEL_BY_VALUES


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


# ---------------------------------------------------------------- token 读数（不再是预算）


def test_token_spend_is_only_a_reading_and_never_cancels():
    """2026-10-15 业主裁定 A1/A2/A3：**「我们不卡 token，只卡总花销的钱」**。

    这一条是那一轮裁定的钉子：`CancelToken` 上必须**没有**任何按 token 停的路径。
    它此前有一条（`token_budget=10` ⇒ 花到 12 ⇒ `cancelled` 变 True ⇒
    在跑的 handler 在下一个 `raise_if_cancelled` 点被掀掉），
    那是一条**强杀**——正是裁定要删的东西。
    """
    t = CancelToken()          # ⚠️ 连这个参数都不该再存在
    assert "token_budget" not in CancelToken.__init__.__code__.co_varnames
    for _ in range(1000):
        assert t.consume_tokens(10 ** 6) == t.tokens_used
    assert t.cancelled is False, "花多少 token 都不许把这一趟停掉"
    assert t.reason is None
    assert t.tokens_used == 10 ** 9, "但花销必须记得住（读数）"
    assert "token_budget" not in t.to_dict(), "读数里也不许再出现预算这一格"


def test_consume_tokens_ignores_negative():
    """负数消耗不许把读数抹掉 —— 那会让超支被静默抹平。"""
    t = CancelToken()
    assert t.consume_tokens(10) == 10
    assert t.consume_tokens(-100) == 10
    assert t.cancelled is False


# ---------------------------------------------------------------- 线程安全


def test_cancel_is_thread_safe_first_wins():
    """一个共享 signal 会被多个线程同时读到（主线程取消、worker 检查）。

    这条测试不是"跑一遍看看有没有崩"，而是断言一个不变量：
    50 个线程同时取消，最终 state 必须恰好是其中一个（不许出现混合态）。

    `code` 必须取词表内（`CANCEL_CODES`）的值：`G-10` 之后 `CancelReason.__post_init__`
    会校 `code ∈ CANCEL_CODES`，而"哪个线程赢了"这件事由 `detail` / `by` 承载
    （它们刻意保持开放，见 `test_cancel_by_is_not_a_hard_enum_so_callers_keep_their_own_label`）。
    早期这版用 `f"reason-{i}"` 造编外 code，靠的正是"code 没人校验"—— 那不是本用例要证的东西。
    """
    codes = ("user", "deadline")  # schema.CANCEL_CODES 的成员
    t = CancelToken()
    barrier = threading.Barrier(50)

    def worker(i: int) -> None:
        barrier.wait()
        t.cancel(codes[i % len(codes)], detail=f"d{i}", by=f"t{i}")
        # 每个线程还要读一次：读到的必须是完整的 (code, detail, by) 三元组
        r = t.reason
        assert r is not None
        assert r.detail in (f"d{j}" for j in range(50))
        assert r.by == "t" + r.detail[1:], "detail 与 by 必须来自同一个线程"

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(50)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    assert t.cancelled is True
    code = t.reason.code  # type: ignore[union-attr]
    assert code in codes, f"赢的那一次必须用词表内的 code，实得 {code!r}"
    i = t.reason.detail[1:]  # type: ignore[union-attr]
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

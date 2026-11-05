"""全局并发闸「不设限」（业主 2026-11-05 裁定，逐字：「丙：全局不设限」）。

## 这道闸为什么被拿掉

真机 `1703d44f` 的读数：16 格里 8 格被 1–2 小时不终态的任务占着；65 次
`concurrency_exceeded` 里 42 次目标是 V（审稿人）。也就是说这道闸挡住的不是花钱，
而是"本来就该等"的那一类派活 —— 它把一个结构性上限用在了资源轴该管的地方，
而真正的资源闸（钱 / 墙钟）一格没动。

## 判据（先红后绿 + 反真空）

- a：缺省 `Policy().max_concurrency is None`，且 `check` 在 `running=100/1000` 时
  不返回 `concurrency_exceeded`；
- c（反真空）：显式给一个数时照旧拒（`16` 拒 `running=100`，10 的 9 次方拒
  同量级的 `running`）⇒ 证的是"缺省这一档不走比较"，不是"把闸换成永远放行"，
  也不是"换成一个够大的数"；把跳过改回 `d.running >= policy.max_concurrency`
  （此时右端是 None）会当场抛 `TypeError` ⇒ a 红，而不是静默放行；
- b：其余闸照旧 —— 扇出（25 / 主控 100）、召唤总数（5000）、深度（6）、墙钟；
- d：三处读数同一口径 —— `Policy` 那一格的注释 / 模块 docstring / 开场那段
  `agent_prompts.parent_limits_text`（提示词里那句）。

## 为什么不跟着抬 `PROMPT_VERSION`（2026-11-05 实测，免得下次又有人抬）

可核的一句话：这次改的是开场那条 user 消息里 `parent_limits` 一格的值
（从「16 个」变成「不设限」），而那一格被 `promptstability.split_facts` 归进
`STEP_VOLATILE_FACTS`（system 里只留静态指路语）、又被
`tests/test_agent_prompts.py::_surface_digest` 显式替换成夹具串
`_SURFACE_FIXTURE_LIMITS` 之后才算摘要 ⇒ 值怎么变，`_FROZEN_PROMPT_DIGESTS`
的十一格都一格不动。实测把 `PROMPT_VERSION` 抬到 p243 会让
`test_the_prompt_version_moves_with_the_sections` 报「PROMPT_VERSION 动了而
十格摘要一格没变」⇒ 那一版号是假账。同一原因，两份 golden（agent_surface /
tool_surface）里根本没有这一串，重冻格数 = 0；warm 的前缀也不含它
（`scripts/warm_prompt_cache.py` 发的是 system + 固定那句 user）⇒ 这次改动
不重冻、不抬版本、不需要重跑 warm。

## 为什么是 `None` 而不是 0

`0` 在这份 `Policy` 里的自然读法是"0 个名额"（真闸门：谁都派不动），
`d.running >= 0` 的极性正好相反；而 `wall_clock_sec` / `usd_budget` 早就是
`None` = 不限、`to_dict()` 原样保留 None ⇒ 台账上"不设限"与"限 0"分得开。
（裁定原文与取舍见 `policy.Policy.max_concurrency` 的注释。）
"""

from __future__ import annotations

import pytest

from agentflow import agent_prompts as AP
from agentflow import policy as P
from agentflow import schema as S
from agentflow import scheduler as SCH


def _d(**kw) -> P.Decision:
    """一条合法的召唤（M→C），只把这一条判据关心的那几格换掉。"""
    base = dict(frm="M", to="C", action="hottest")
    base.update(kw)
    return P.Decision(**base)


# ---------------------------------------------------------------- a：缺省 = 不设限


def test_default_policy_represents_unlimited_as_none() -> None:
    """缺省值是 `None`（不限），不是 0、也不是一个很大的数。"""
    p = P.Policy()
    assert p.max_concurrency is None, (
        f"缺省并发上限应当是 None（不设限），实际 {p.max_concurrency!r} —— "
        "0 会被读成「0 个名额」、大数只是把同一个比较换了个常数")
    # 台账形态必须原样保留 None（"不限"与"限 0"是两件事，不许折叠）
    assert p.to_dict()["max_concurrency"] is None
    # 构造即校验：None 是合法值（不是"忘了设"，是裁定后的"不设"）
    assert p.validate() is None


def test_check_skips_the_gate_at_one_hundred_and_one_thousand() -> None:
    """a：`running=100/1000` 时不再返回 `concurrency_exceeded`。

    先红后绿：改前 `Policy()` 的默认值是 16 ⇒ `running=100` 必拒；改后这两个
    读数都必须放行。若有人把"跳过"改回"比较一个数"，右端是 None ⇒ 这里会抛
    `TypeError`（红），而不是静默放行。
    """
    p = P.Policy()
    for running in (100, 1000):
        r = P.check(p, _d(running=running))
        assert r is None, (
            f"不设限时 running={running} 仍被拒：{r.reason if r else None} "
            f"{r.detail if r else ''}")


# ---------------------------------------------------------------- c：反真空


def test_an_explicit_number_still_refuses_and_a_huge_number_is_not_unlimited() -> None:
    """c：显式给数 ⇒ 照旧比大小；大数只是大数，不是"不设限"。

    这一条钉住两件事：① 闸门代码还在（缺省不装闸 ≠ 把闸拆了），显式设数的调用方
    （库的用法 / 判据）仍拿得到 `concurrency_exceeded`；② "不设限"不是"换一个
    永远不会触顶的数" —— `10**9` 在 `running=10**9` 时照样拒。
    """
    r = P.check(P.Policy(max_concurrency=16), _d(running=16))
    assert r is not None and r.reason == "concurrency_exceeded", r
    assert P.check(P.Policy(max_concurrency=16), _d(running=15)) is None

    # 受控词表那格不许变死值：历史 `projects/**/tasks.json` 里有 162 处带着
    # `concurrency_exceeded`（`capabilities.audit_task_ledger` 按 `rr not in
    # S.REFUSAL_REASONS` 判非法）⇒ 词表里留着它，而且它今天仍有活的产出点
    # （上一行就是：显式设数的 policy 仍然产出它）。
    assert "concurrency_exceeded" in S.REFUSAL_REASONS
    assert r.reason in S.REFUSAL_REASONS

    big = 10 ** 9
    r = P.check(P.Policy(max_concurrency=big), _d(running=big))
    assert r is not None and r.reason == "concurrency_exceeded", (
        "把上限换成一个很大的数仍然是一道闸（只是难以触顶）—— "
        "裁定要的是「不装闸」，所以缺省必须是 None")


def test_validate_rejects_zero_and_non_int_but_accepts_none() -> None:
    """取舍的另一半：只有 `None` 表示不限；0 / 负数 / 非整数仍然非法。"""
    for bad in (0, -1):
        with pytest.raises(ValueError, match="max_concurrency"):
            P.Policy(max_concurrency=bad)
    for bad in ("16", 16.0, True):
        with pytest.raises(ValueError, match="max_concurrency"):
            P.Policy(max_concurrency=bad)  # type: ignore[arg-type]
    assert P.Policy(max_concurrency=None).max_concurrency is None
    assert P.Policy(max_concurrency=1).max_concurrency == 1


# ---------------------------------------------------------------- b：其余闸照旧


def test_the_other_gates_still_fire_under_an_unlimited_policy() -> None:
    """b：拿掉并发闸之后，其余五道闸一格没松。

    用缺省 `Policy()`（并发不设限）逐条打：扇出（工人 25 / 主控 100）、召唤总数
    5000、深度 6、墙钟。任何一条不拒 ⇒ 这一批"顺手放宽了别的闸"。
    """
    p = P.Policy()

    worker = P.check(p, _d(frm="A", to="B", action="run_once", direct_children=25))
    assert worker is not None and worker.reason == "fanout_exceeded", worker
    assert P.check(p, _d(frm="A", to="B", action="run_once",
                         direct_children=24)) is None

    boss = P.check(p, _d(frm="M", to="C", action="hottest", direct_children=100))
    assert boss is not None and boss.reason == "fanout_exceeded", boss
    assert P.check(p, _d(direct_children=99)) is None

    total = P.check(p, _d(total=5_000))
    assert total is not None and total.reason == "budget_exceeded", total
    assert total.limit == "max_tasks_per_run"
    assert P.check(p, _d(total=4_999)) is None

    depth = P.check(p, _d(depth=7))
    assert depth is not None and depth.reason == "depth_exceeded", depth
    assert P.check(p, _d(depth=6)) is None

    wall = P.check(P.Policy(wall_clock_sec=60), _d(deadline_hit=True))
    assert wall is not None and wall.reason == "deadline_exceeded", wall
    assert wall.limit == "wall_clock"


# ---------------------------------------------------------------- d：三处读数一致


def test_the_three_readings_agree() -> None:
    """d：`Policy` 注释 / 模块 docstring / 开场读数（提示词里那句）同一口径。"""
    p = P.Policy()
    reading = P.concurrency_reading(p)
    assert "不设限" in reading and "丙：全局不设限" in reading, reading

    # 提示词里那句（开场那条 user 消息的一栏）读的是同一个函数
    text = AP.parent_limits_text(p, "E")
    assert "全局同时运行" in text and "不设限" in text, text
    # 不设限时不许再出现"16 个"这种旧缺省（那会是一句谎话）
    assert "全局同时运行 16 个" not in text, text

    # 模块 docstring：裁定原文与取舍都写在里面（改回"四个都是正数"就红）
    assert "丙：全局不设限" in P.__doc__, "policy 模块 docstring 没留下裁定的口径"
    assert "不设限" in P.__doc__

    # 反真空：显式设数时提示词逐字回到旧口径（可复现性：p242 的渲染字节不变）
    capped = P.Policy(max_concurrency=16)
    assert P.concurrency_reading(capped) == "16 个（超了落 `concurrency_exceeded`）"
    assert ("- 全局同时运行 16 个（超了落 `concurrency_exceeded`）；"
            in AP.parent_limits_text(capped, "E"))


# ---------------------------------------------------------------- 运行期：不许炸


def test_wave_handle_constructs_without_a_cap() -> None:
    """不设限时调度器构造不许炸（改前 `Semaphore(int(None))` 会 TypeError）。

    只测构造/空批这一条最短路径：满批的并发行为由 `tests/test_scheduler.py` 与
    `tests/test_e13_concurrency.py` 用显式上限守着（那道代码没动）。
    """
    handle = SCH.WaveHandle([], conductor=object(), policy=P.Policy(),
                            token=object(), probe=object())
    assert handle.start() is handle
    assert handle.waves == []

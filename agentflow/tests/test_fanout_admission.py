"""扇出口径判据：扇出 = 此刻在飞的子代理数，不是累计受理数（所有者 2026-10-08 裁定）。

## 这一条判的是什么

所有者逐字（2026-10-08）：

    「我认为的"派活上限"不是累计的，是单时刻的，即 M 同时派出在后台运行的子代理数
    不超过 20，各角色智能体允许同时向其它智能体派活数不超过 5，智能体返回后腾出空间。」

机器化的三件事：

1. 分子说的是"此刻在飞"，台账上的形态是子行里 `status ∈ {"pending", "running"}`
   的那些（`Conductor._in_flight_children_of`；`schema.TASK_STATUSES` 是状态词表的
   唯一来源）。`Conductor.summon` 第 [4] 步给 `Decision.fanout` 喂的就是这个数
   （`conductor.py:1413`），判定在 `policy.check` 的第 [5] 步（`policy.py:352-375`）。
2. 返回即腾位：子代理一返回（`done` / `failed` / `cancelled`，三者都带
   `ended_at`）就从分子里消失 —— 与它返回得好不好无关。这是所有者那句话里
   "智能体返回后腾出空间"的直译，也是本文件与改前口径差别最大的地方：
   改前那一版按"受理数"算名额（题15 选B，2026-10-07），跑完的行永远占着格子。
   触顶时的动作也是所有者规定的（2026-10-08 追加）：「当达到派活上限后，父智能体
   或主控只可等待子智能体返回结果」⇒ `summon` 先等（`Conductor._await_fanout_slot`，
   默认 `DEFAULT_FANOUT_WAIT_SEC`；`fanout_wait_sec=0` = 不等、立即拒），等到了就
   照常派，等到窗口用完仍满才拒（报文尾部带上等的那一段读数）。这一条在本文件里
   有正控、负控与单元级三层断言（`test_..._returns_in_time` / `..._times_out` /
   `test_await_fanout_slot_...`）。
3. 累计读数退到审计面：`Conductor._admitted_children_of`（配合
   `_occupies_fanout_slot`）仍然回答"这一趟累计真的派出去过几件"，状态报告与审计
   要用它；但它不再参与策略判定 —— 本文件里凡涉及它的断言都只证明
   "累计读数不许被记账炸掉而少算"，不再证明"它影响上限"。

## 改前口径的代价（累计口径的真机读数）

累计口径与"受理数"口径合起来有一个不可恢复的形态：闸门拒掉的召唤也落一行台账
（`Conductor._refuse` 的 `note="refused:<reason>"`），而旧实现的扇出读数是
`len(self._children_of(parent))` —— 数的是全部子行，于是"被拒的那一次"自己也占一个
名额：父任务触顶 → 之后每一次召唤都被 `fanout_exceeded` 拒掉 → 每一次拒绝又落一行、
又占一格 → 名额只增不减 → 父任务再也派不出活。

真机读数（工作区 `agentflow/projects/p9-post-merge-probe`，2026-10-07 台账）：
顶趟行 `t-0001` 名下 10 个子行，末 5 条（`t-0007`…`t-0011`）全是
`refused/fanout_exceeded`，detail 里的读数从"已派生 5 个"一路涨到"已派生 9 个"
（那就是自我毒化的机器形态）；本趟主控只成功派了 3 件活（A 检索 / D 立题 /
D 登记猜想），E 的实验永远进不去 ⇒ `experiments=0`、收工门两格红。

而累计口径另有它自己的代价（这一版改口径的直接动因）：T1 第 18/19 趟
（工作区 `p5-review-t18`，sid `t1r` / `t1s`）在第 51–88 步就用完了 20 个累计
名额，此后 `G.build_document` 与修好的 Lean 重派全部进不去 ⇒ `documents` 0 行、
P8/P9 两行红。一趟 78–138 步的研究型跑批只许派 20 次活，是结构性不够；
"同时在飞 20 个"在同一份 `Policy` 里另有 `max_concurrency` 约束着，所以这一格
不需要再当作总量额度来花。

## 三份读数在这里怎么落地

1. 单时刻口径的正面：`test_gate_refusal_does_not_consume_a_fanout_slot`
   （闸门拒掉的根本不在飞 ⇒ 满格前的那一次拒绝不占位）与
   `test_refused_attempts_at_the_cap_never_deepen_the_poison`（在飞数不随拒绝上涨）。
2. 返回即腾位：`test_a_failed_child_frees_the_slot_on_return` 与
   `test_a_role_refused_child_frees_the_slot_on_return`（语义反转：改前它们是
   "跑完也占名额"，现在是"跑完就腾位"）；两条档位判据
   （`test_conductor_tier...` / `test_conductor_tier_is_exactly_twenty`）里也各有一段
   "把一行标成返回 ⇒ 名额立刻还回来"的显式断言。
3. 反真空：上面每一条里"闸门仍然会拒、报文里带着在飞几与上限几"的那几段断言 ——
   它们防止有人用"把闸门拆掉"的方式让前两组变绿。

## 受理标记为什么必须与 running 行同事务（题 21 选 B，2026-10-07 所有者裁定）

这一族函数行为没变：它们测的是受理标记与累计审计读数（`_occupies_fanout_slot` /
`_admitted_children_of`），而口径改成"在飞"之后累计读数今天只服务审计面。
上一轮的最小修法把"占不占名额"挂在 `tokenmeter:settled` 上，而那是收尾的记账写回
（`_set_usage`）打的标记 —— 它能炸：`_charge_and_settle` 刻意兜住记账异常，兜住之后
这一行就缺标记 ⇒ 被当成"没跑" ⇒ 累计读数少算 1。本轮的判据换成"受理那一刻就落盘的
标记"（`_ADMITTED_MARK`，与 `status="running"` 同一笔事务写下），于是它与后续任何一步
的成败解耦。四条读数：

- `test_the_admission_mark_is_on_disk_while_the_handler_runs`：跑到一半看盘，标记已在
  （而结算标记还不在）—— 这是"在受理那一刻打的"的结构性证据；
- `test_a_contained_charge_failure_still_occupies_the_slot`：记账抛异常被兜住 ⇒ 累计读数仍算它；
- `test_a_failed_charge_writeback_still_occupies_the_slot`：记账写回炸掉（异常逸出
  `summon`）⇒ 累计读数仍算它；
- `test_the_previous_minimal_fix_would_miss_this_row`：负控 —— 同一个行喂给旧判据
  （只看结算标记）给 False、喂给新判据给 True，这就是本轮与上一轮的差别。

老行（本题之前落盘的、没有受理标记的行）退回读结算标记：历史台账的累计判法与改前一致
（`test_a_legacy_refused_row_keeps_the_old_verdict`）。

## 展示面为什么单独有一条

`_children_of` 还服务 `SummonResult.children`（谁试过什么必须看得见）。本次修法
不就地改它，而是另加 `_admitted_children_of`；`test_display_face_still_lists_attempts`
就是"没有顺手把展示面改坏"的机器证据。

## 夹具怎么造出"此刻在飞 k 个"

真派活是同步的：`summon` 返回时那件活在台账上已经是终态，所以"派一件、它还在飞"
在单进程测试里造不出来。要判"在飞数"，就必须直接往台账写"在飞"的子行 ——
`_seed_in_flight` / `_mark_returned` 就是那两个夹具（口径：`status="running"` 且
`started_at` 非空、`ended_at=None`，逐字对齐 `schema.Task.validate`
的 `schema.py:2131-2139`）。

## "只可等待"那两组怎么判才不赌时序

等待窗与"谁把行标成返回"是两件事：测试用一个很短的窗（5s）加一个后台线程
（0.4s 后 `_mark_returned`），所以整份文件仍然是秒级。同步点选"台账里出现等待读数"
而不是固定 `sleep`：线程等 `readings` 非空（= 主线程已经进了等待循环）才动手，
之后再给足余量。读数从 `_await_fanout_slot` 的返回值取 —— 与其解析日志文本，
不如把那个返回值截下来直接断言（日志那一层另有 `_log` 钩子，本文件不依赖它）。
"""

from __future__ import annotations

import threading
import time

import pytest

from agentflow import conductor as CO
from agentflow import policy as P
from agentflow import schema as S
from agentflow.agent_e import AgentE
from agentflow.agent_h import AgentH
from agentflow.store import Store


# ---------------------------------------------------------------- 测试替身
#
# 与 `test_scheduler.py` 同约定：替身继承真实类，保证"替身必须提供真实方法名"，
# 只覆写要用的那一个方法（真类的方法签名由 Python 自己核）。


class _GStub(AgentE):
    """G 替身的共同基类：不建工具面（真类构造要 store/tools）。"""

    def __init__(self) -> None:  # noqa: D107
        pass


class FakeG(_GStub):
    """G 的替身：`revise` 永远受理成功（父任务 = 谁召唤它）。"""

    def revise(self, doc_id, **kw):  # noqa: D102
        return {"outcome": "ok", "detail": f"revised {doc_id}"}


class BoomG(_GStub):
    """G 的替身：`bad_doc_id` 那一次跑了、炸了（`outcome=failed`），其余照常。"""

    def __init__(self, bad_doc_id: str = "k0") -> None:  # noqa: D107
        self.bad = bad_doc_id

    def revise(self, doc_id, **kw):  # noqa: D102
        if doc_id == self.bad:
            raise RuntimeError("替身故意炸")
        return {"outcome": "ok", "detail": f"revised {doc_id}"}


class RefusingG(_GStub):
    """G 的替身：`bad_doc_id` 那一次跑了、角色自己拒了（领域错误 ⇒ `refused/invalid_params`）。

    这不是闸门拒绝：`_business_refusal_code` 按类名认领域错误（`agent_g` 的
    `DocumentError`），与"闸门拒掉、根本没跑"是两件事（真机 `t-0006` 就是这一档）。
    """

    def __init__(self, bad_doc_id: str = "k0") -> None:  # noqa: D107
        self.bad = bad_doc_id

    def revise(self, doc_id, **kw):  # noqa: D102
        if doc_id == self.bad:
            raise DocumentError("替身按领域规则拒绝")
        return {"outcome": "ok", "detail": f"revised {doc_id}"}


class DocumentError(ValueError):
    """与 `agent_g._support.DocumentError` 同名：判据按类名认它。"""


class ProbeG(_GStub):
    """G 的替身：在跑的当口回头读自己那一行（受理标记在不在盘上）。

    为什么必须"在跑的当口"读：只断言收尾之后行上有标记，区分不了"受理时写的"
    与"收尾时补的"—— 而上一轮的最小修法恰恰是后者（收尾一炸标记就没了）。
    这里是本题 ④ 的结构性证据：跑到一半标记就必须已经在盘上，而结算标记不该在。
    """

    def __init__(self, store: Store, *, refuse: bool = True) -> None:  # noqa: D107
        self.store = store
        self.refuse = refuse
        self.seen_inputs: list[str] | None = None

    def revise(self, doc_id, **kw):  # noqa: D102
        running = [r for r in self.store.rows("tasks")
                   if r.get("role") == "G" and r.get("status") == "running"]
        assert running, "跑到这里时自己的 running 行必须已经在盘上"
        self.seen_inputs = [str(x) for x in (running[-1].get("inputs") or [])]
        if self.refuse:
            raise DocumentError("替身按领域规则拒绝")
        return {"outcome": "ok", "detail": f"revised {doc_id}"}


class FakeH(AgentH):
    """H 的替身：`review` 只用来造一个"父任务行"。"""

    def __init__(self) -> None:  # noqa: D107
        pass

    def review(self, doc_id, *, round_no=None, dependencies=None):  # noqa: D102
        return {"outcome": "ok", "detail": f"review {doc_id}", "checked": True}


# ---------------------------------------------------------------- fixtures


def _mk_store(tmp_path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _mk_conductor(store, *, max_fanout: int, g=None, fanout_wait_sec: float = 0.0,
                  log=None) -> CO.Conductor:
    """夹具一律传 `fanout_wait_sec=0`（= 不等，立即拒）。

    实现在触顶时的默认行为是等（`DEFAULT_FANOUT_WAIT_SEC = 900.0`，所有者
    2026-10-08：「当达到派活上限后，父智能体或主控只可等待子智能体返回结果」）。
    那些"触顶 ⇒ 被拒"的用例要的是即时拒绝，用默认值会让它们真的挂 900 秒
    —— 所以默认在这里关掉等待；"只可等待"自己那两条用例显式把窗口打开。
    """
    return CO.Conductor(
        store,
        policy=P.Policy(max_concurrency=8, max_fanout=max_fanout,
                        max_tasks_per_run=500, wall_clock_sec=600),
        registry={"H": ("object", FakeH()), "G": ("object", g or FakeG())},
        fanout_wait_sec=fanout_wait_sec,
        log=log,
    )


def _parent(c: CO.Conductor, doc_id: str = "0001") -> str:
    """造一个父任务行（主控发起，depth=1），返回它的 `task_id`。"""
    res = c.summon("H", "review", {"doc_id": doc_id})
    assert res.outcome == "ok", f"造父任务失败：{res.outcome}/{res.refusal_reason}"
    return str(res.task_id)


def _revise(c: CO.Conductor, parent: str, key: str, *, by: str = "H", doc_id: str | None = None):
    return c.summon("G", "revise", {"doc_id": doc_id or key}, by=by,
                    parent_task_id=parent, input_key=key)


def _bad_revise(c: CO.Conductor, parent: str, key: str, *, by: str = "H"):
    """一次必然被闸门拒掉、根本没跑的召唤（多传一个未声明的参数）。"""
    return c.summon("G", "revise", {"doc_id": key, "no_such_param": 1}, by=by,
                    parent_task_id=parent, input_key=key)


# ---- 在飞夹具
#
# 号段用 `t-9NNN`（字面号，不用 `alloc_id` —— `tasks` 是过程记录，号由
# `interactions.next_prefixed_id` 按"表里最大号 +1"发，`tx.alloc_id("task")`
# 会抛 `StoreError: 未知 ID 类别`）。`t-9NNN` 远高于每个用例里真派活发到的号段，
# 所以字面号与自动号不会撞。
#
# 为什么必须直接写台账、而不是"派一件然后在它跑的时候插进去"：`summon` 是同步的，
# 返回时那件活已经是终态 ⇒ 单进程测试里造不出"派完还在飞"（见模块 docstring 末节）。


def _seed_in_flight(store: Store, parent: str, n: int, *, base: int = 0,
                    role: str = "G", action: str = "revise", called_by: str = "H") -> list[str]:
    """往台账写 n 行"此刻在飞"的子行（父 = `parent`），返回它们的 `task_id`。

    口径 = `Conductor._in_flight_children_of` 认的那一档，逐字对齐
    `schema.Task.validate`（`schema.py:2131-2139`）：`status="running"` ⇒
    `started_at` 必须非空；`status ∈ {"pending","running"}` ⇒ `ended_at` 必须为 None；
    `outcome` 必须是 None（不能是空串 —— `TASK_OUTCOMES` 里没有 `""`）。

    号段是 `t-9{base+i:03d}`：`base` 让同一个父任务可以分两批加在飞行
    （例如先 19 行判"第 20 件受理"，再加 1 行判"触顶被拒"）而不撞号。

    读累计读数时要注意：在飞的行在 `_occupies_fanout_slot` 眼里也算"曾经受理过的
    派活"（`outcome is None` ⇒ 非 refused ⇒ True）。这是对的 —— 一件正在飞的活确实
    已经被受理了 —— 所以断言累计值时要把 seed 的行算进去。
    """
    ids = [f"t-9{base + i:03d}" for i in range(n)]
    with store.tx("tasks", actor="test") as tx:
        for tid in ids:
            row = {
                "task_id": tid, "role": role, "action": action, "called_by": called_by,
                "parent_task_id": parent, "depth": 2, "input_key": tid,
                "status": "running", "outcome": None, "refusal_reason": None,
                "instance": "", "detail": "夹具：此刻在飞", "error": None,
                "started_at": S.now_iso(), "ended_at": None,
                "tokens": 0, "usd": 0.0, "artifacts": [], "inputs": [],
            }
            S.Task(**{k: v for k, v in row.items() if k in S.Task.__dataclass_fields__}).validate()
            tx.upsert("tasks", row, note="fixture:in_flight")
    return ids


def _mark_returned(store: Store, task_id: str) -> None:
    """把某一行标成"已经返回"：`status="done"` + 非空 `ended_at`（口径见 `_seed_in_flight`）。

    刻意用 `done`（而不是写成"删掉这一行"）：所有者那句话说的是"返回后腾出空间"，
    腾位的机制是终态，不是行消失 —— 行必须留着（谁派过什么不许丢）。
    """
    with store.tx("tasks", actor="test") as tx:
        row = next(r for r in tx.rows("tasks") if r.get("task_id") == task_id)
        row["status"] = "done"
        row["outcome"] = "ok"
        row["detail"] = "夹具：已返回"
        row["ended_at"] = S.now_iso()
        S.Task(**{k: v for k, v in row.items() if k in S.Task.__dataclass_fields__}).validate()
        tx.upsert("tasks", row, note="fixture:returned")


# ---------------------------------------------------------------- 读数一：单时刻口径


def test_gate_refusal_does_not_consume_a_fanout_slot(tmp_path):
    """闸门拒掉的召唤不占在飞名额：满格前一格时，下一次合法派活必须受理。

    两件事：①在飞分子只数 `status ∈ {pending,running}` 的子行 ⇒ 闸门拒掉的
    那一行（终态 `refused`、根本没跑）不进分子；②受理成功后累计读数
    `_admitted_children_of` 才 +1，而在飞读数在同步派活返回后回到 seed 的数。

    改前（受理数口径）：被拒的那一行也算进 `fanout` ⇒ 这一件合法派活看到
    `fanout=cap` ⇒ 报 `fanout_exceeded`，父任务从此再也派不出活。
    """
    store = _mk_store(tmp_path)
    c = _mk_conductor(store, max_fanout=3)
    parent = _parent(c)

    _seed_in_flight(store, parent, 2)          # 此刻在飞 2（cap=3，还剩 1 格）

    seed = _bad_revise(c, parent, "seed")
    assert seed.refusal_reason == "invalid_params", (
        f"这一条要的是闸门拒绝（根本没跑），拿到 {seed.outcome}/{seed.refusal_reason}")
    assert seed.task_id, "被拒的召唤必须落行（谁试过什么不许丢）"

    # 合法派活：改前这里被 fanout_exceeded 拒掉（那一行占了名额），改后必须受理。
    assert len(c._in_flight_children_of(parent)) == 2, "被拒的那一行不许进在飞分子"
    ok = _revise(c, parent, "k5")
    assert ok.outcome == "ok", (
        "在飞口径下这一件本该受理（在飞 2 < 上限 3）"
        f"（{ok.outcome}/{ok.refusal_reason}：{ok.detail}）")
    assert len(c._in_flight_children_of(parent)) == 2, "它已经返回 ⇒ 名额还回去了"
    # 累计读数：seed 的两行在飞 + 这一件 = 3（在飞的行也算"曾经受理过" —— 它确实被受理了）。
    assert len(c._admitted_children_of(parent)) == 2 + 1, (
        "累计读数只算真的受理过的（seed 的两行在飞 + 这一件），闸门拒掉的那一行不算")


def test_refused_attempts_at_the_cap_never_deepen_the_poison(tmp_path):
    """触顶之后每次尝试照旧落行，但在飞读数不许再涨（真机 detail 里那个 5→9）。"""
    store = _mk_store(tmp_path)
    c = _mk_conductor(store, max_fanout=3)
    parent = _parent(c)
    _seed_in_flight(store, parent, 3)

    refused = [_revise(c, parent, f"over{i}") for i in range(3)]
    assert [r.refusal_reason for r in refused] == ["fanout_exceeded"] * 3
    for r in refused:
        assert "在飞 3" in r.detail and "上限 3" in r.detail, (
            f"报文要能看出此刻在飞几与上限是多少，拿到：{r.detail}")

    assert len(c._children_of(parent)) == 3 + 3, "被拒的尝试照旧要落行"
    assert len(c._in_flight_children_of(parent)) == 3, "在飞读数不许随拒绝上涨"
    # 累计读数 = seed 的 3 行（在飞的活已经被受理过），被闸门拒的那 3 行一格不进。
    assert len(c._admitted_children_of(parent)) == 3, (
        "累计读数不许随拒绝上涨（那三行是闸门拒的）")


def test_display_face_still_lists_attempts(tmp_path):
    """展示面没被改坏：`_children_of` 仍然列出全部尝试（含被拒的）。"""
    c = _mk_conductor(_mk_store(tmp_path), max_fanout=3)
    parent = _parent(c)
    assert _revise(c, parent, "k0").outcome == "ok"
    assert _bad_revise(c, parent, "seed").refusal_reason == "invalid_params"

    all_kids = c._children_of(parent)
    admitted = c._admitted_children_of(parent)
    assert len(all_kids) == 2, f"展示面要看到两次尝试，拿到 {all_kids}"
    assert len(admitted) == 1, f"审计面只数真的受理过的那一次，拿到 {admitted}"
    assert set(admitted) <= set(all_kids)


# ---------------------------------------------------------------- 口径的另一半：返回即腾位
#
# 这两条是语义反转：所有者 2026-10-08 的裁定推翻了题15 选B 的那一半 ——
# 改前它们是"跑完也占名额"，现在是"跑完（无论失败还是角色自己拒）就腾出名额"。
# 改前的写法在这一条上会拒：`max_fanout=1` 时第 1 件跑完就把唯一的格占死。


def test_a_failed_child_frees_the_slot_on_return(tmp_path):
    """跑了但失败的子行返回后不占名额（与它返回得好不好无关）。

    这是所有者 2026-10-08 裁定推翻题15 选B 的那一半：改前的口径下，这一件
    `failed` 也占着唯一那一格 ⇒ 下一件当场被 `fanout_exceeded` 拒。

    两件事：①返回后 `_in_flight_children_of(parent) == []`；②下一件立刻受理。
    """
    store = _mk_store(tmp_path)
    c = _mk_conductor(store, max_fanout=1, g=BoomG())
    parent = _parent(c)

    boom = _revise(c, parent, "k0")
    assert boom.outcome == "failed" and boom.error

    assert c._in_flight_children_of(parent) == [], (
        "跑完（失败也算返回）就该腾出名额；拿到 "
        f"{c._in_flight_children_of(parent)}")
    nxt = _revise(c, parent, "k1")
    assert nxt.outcome == "ok", (
        "前一格已被腾出 ⇒ 这一件必须受理"
        f"（{nxt.outcome}/{nxt.refusal_reason}：{nxt.detail}）")
    # 累计读数不受影响：它仍然记得"这一趟派出去过两件"（审计面）。
    assert len(c._admitted_children_of(parent)) == 2


def test_a_role_refused_child_frees_the_slot_on_return(tmp_path):
    """跑了、角色自己拒了的子行（真机 `t-0006` 那一档）返回后同样腾位。

    闸门拒绝与角色拒绝的差别只在"跑没跑"上（累计读数要分得开），
    在"腾不腾位"上没有差别 —— 两者都已经是终态行。
    """
    store = _mk_store(tmp_path)
    c = _mk_conductor(store, max_fanout=1, g=RefusingG())
    parent = _parent(c)

    role_refusal = _revise(c, parent, "k0")
    assert role_refusal.outcome == "refused" and role_refusal.refusal_reason == "invalid_params"
    assert c._in_flight_children_of(parent) == [], "角色拒绝也是返回 ⇒ 也要腾位"
    nxt = _revise(c, parent, "k1")
    assert nxt.outcome == "ok", (
        f"腾位之后这一件必须受理（{nxt.outcome}/{nxt.refusal_reason}：{nxt.detail}）")
    assert len(c._admitted_children_of(parent)) == 2, "累计读数仍然分得开这一档"


# ---------------------------------------------------------------- 受理标记（题 21 选 B）
#
# 这一族接下来六条测的是受理标记与累计审计读数（`_occupies_fanout_slot` /
# `_admitted_children_of`），函数行为在本次口径改动里没变：它们今天证明的是
# "累计读数不许被记账炸掉而少算"，而不再证明"占名额 ⇒ 影响上限"（上限看的是在飞数）。


def test_the_admission_mark_is_on_disk_while_the_handler_runs(tmp_path):
    """受理标记与 `running` 行同一笔事务：跑到一半看盘，它已经在（结算标记还不在）。"""
    store = _mk_store(tmp_path)
    probe = ProbeG(store)
    c = _mk_conductor(store, max_fanout=2, g=probe)
    parent = _parent(c)

    r = _revise(c, parent, "k0")
    assert r.outcome == "refused" and r.refusal_reason == "invalid_params", r
    assert probe.seen_inputs is not None, "替身没被跑到 ⇒ 这条判据在这一形态上没有牙"
    assert CO._ADMITTED_MARK in probe.seen_inputs, (
        f"跑到一半还看不到受理标记 ⇒ 它不是与 running 行同一笔事务写的：{probe.seen_inputs}")
    assert CO._SETTLED_MARK not in probe.seen_inputs, (
        f"跑到一半就看见了结算标记 ⇒ 那个标记不是收尾的记账写回打的：{probe.seen_inputs}")
    row = next(x for x in store.rows("tasks") if x["task_id"] == r.task_id)
    assert CO._ADMITTED_MARK in [str(x) for x in row["inputs"]], row["inputs"]


def test_the_gate_refusal_row_carries_no_admission_mark(tmp_path):
    """闸门拒掉的那一行没有受理标记；它在在飞与累计两份读数里都不占位。

    这里不再用"下一件被拒"来证明占位（上限看的是在飞数，不看累计值）——
    改前的口径下这条断言咬的是"累计那一格被占住"，现在它咬的是三件事：
    ①行上没有标记；②在飞分子不含它；③累计分子也不含它。
    """
    store = _mk_store(tmp_path)
    c = _mk_conductor(store, max_fanout=3)
    parent = _parent(c)
    seed = _bad_revise(c, parent, "seed")
    assert seed.refusal_reason == "invalid_params"
    row = next(x for x in c.store.rows("tasks") if x["task_id"] == seed.task_id)
    marks = [str(x) for x in row["inputs"]]
    assert CO._ADMITTED_MARK not in marks, row["inputs"]
    assert CO._SETTLED_MARK not in marks, row["inputs"]
    assert row["inputs"] == [], "闸门拒绝的行连调用方给的 inputs 都不带（_refuse 的写法）"
    assert CO._occupies_fanout_slot(row) is False
    assert len(c._admitted_children_of(parent)) == 0
    assert len(c._in_flight_children_of(parent)) == 0


def test_a_legacy_refused_row_keeps_the_old_verdict(tmp_path):
    """向后兼容：本题之前落盘的行没有受理标记，退回读结算标记 ⇒ 累计判法与改前一致。

    为什么必须有：累计读数是审计面，它读的是历史台账（真机 `p9-post-merge-probe`
    的 10 个子行就是老行）。若新判据只认 `conductor:admitted`，那些"跑过又拒"的老行
    会被重新读成"没跑"—— 历史读数当场分家，而且分家方向是累计值被少算。这一版没有动
    `schema.Task`，所以老行连字段都不用补。
    """
    base = {"role": "G", "action": "revise", "called_by": "H", "status": "done",
            "outcome": "refused", "refusal_reason": "invalid_params"}
    assert CO._occupies_fanout_slot({**base, "inputs": [CO._SETTLED_MARK]}) is True, \
        "老行（跑过又拒、只有结算标记）应当仍然算进累计读数"
    assert CO._occupies_fanout_slot({**base, "inputs": [CO._ADMITTED_MARK]}) is True, \
        "新行（有受理标记）算进累计读数"
    assert CO._occupies_fanout_slot({**base, "inputs": []}) is False, \
        "老行（闸门拒、inputs 为空）不算进累计读数"
    assert CO._occupies_fanout_slot({**base, "outcome": "ok", "inputs": []}) is True, \
        "反真空：非 refused 的行照旧一律算进累计读数"


def test_a_contained_charge_failure_still_occupies_the_slot(tmp_path, monkeypatch):
    """④（被兜住的那一半）：记账抛异常被 `_charge_and_settle` 兜住 ⇒ 累计读数仍算它。

    `_charge_and_settle` 刻意兜住记账异常（钱已经花了、活已经干完了，不许让它翻转
    一次已完成的召唤）。兜住之后这一行就没有结算标记 —— 上一轮的最小修法据此
    把它读成"没跑"，累计读数少算 1。

    这里删掉了旧的"第 3 件被 fanout_exceeded 拒"那段：上限今天看的是在飞数
    （同步派活返回后那一行已经不在飞），它证明不了累计占位。
    """
    store = _mk_store(tmp_path)
    c = _mk_conductor(store, max_fanout=2, g=RefusingG())

    def boom(*_a, **_kw):
        raise RuntimeError("替身：记账炸了")
    monkeypatch.setattr(c.meter, "charge_once", boom)

    parent = _parent(c)
    r = _revise(c, parent, "k0")
    assert r.outcome == "refused" and r.refusal_reason == "invalid_params", (
        f"这一条要的是「跑了、角色自己拒」，拿到 {r.outcome}/{r.refusal_reason}")
    row = next(x for x in store.rows("tasks") if x["task_id"] == r.task_id)
    marks = [str(x) for x in row["inputs"]]
    assert CO._SETTLED_MARK not in marks, f"注入没生效（结算标记还是写上了）：{marks}"
    assert CO._ADMITTED_MARK in marks, f"受理标记不在盘上：{marks}"
    assert len(c._admitted_children_of(parent)) == 1, (
        "记账失败让这条「跑了又拒」的行从累计读数里消失了（少算 1）")
    assert _revise(c, parent, "k1").outcome == "ok"      # 下一件照常派得出去
    assert len(c._admitted_children_of(parent)) == 2


def test_a_failed_charge_writeback_still_occupies_the_slot(tmp_path, monkeypatch):
    """④（写回那一半）：`_set_usage` 炸掉 ⇒ 累计读数仍然算它。

    这是所有者点名的那个形态（"把记账写回弄炸"）。如实记一条观察：`_set_usage`
    的调用点在 `_charge_and_settle` 的 try 之外，所以它的异常会逸出 `summon`
    ——本判据把这一点也断言出来，免得把"被兜住"与"逸出"混成一句话。
    无论哪种，行的终态与受理标记都已经在盘上（写 running 行时就写了）。

    这里删掉了旧的"闸门仍按那一行占住的格子拒第 3 件"那段：上限看的是在飞数。
    """
    store = _mk_store(tmp_path)
    c = _mk_conductor(store, max_fanout=2, g=RefusingG())
    # 父任务要在注入之前造好：`_set_usage` 是每一次召唤收尾都走的，
    # 注入之后再造父任务会让它自己也炸（那是另一个形态，不是这一条要判的）。
    parent = _parent(c)

    def boom(*_a, **_kw):
        raise RuntimeError("替身：记账写回炸了")
    monkeypatch.setattr(c, "_set_usage", boom)

    with pytest.raises(RuntimeError, match="记账写回炸了"):
        _revise(c, parent, "k0")
    assert c._set_usage is boom, "注入没生效"

    kids = [x for x in store.rows("tasks") if x.get("parent_task_id") == parent]
    assert len(kids) == 1, kids
    row = kids[0]
    assert row["outcome"] == "refused" and row["refusal_reason"] == "invalid_params", row
    marks = [str(x) for x in row["inputs"]]
    assert CO._SETTLED_MARK not in marks, f"注入没生效（结算标记还是写上了）：{marks}"
    assert CO._ADMITTED_MARK in marks, f"受理标记不在盘上：{marks}"
    assert len(c._admitted_children_of(parent)) == 1, (
        "记账写回失败让这条「跑了又拒」的行从累计读数里消失了（少算 1）")
    assert len(c._in_flight_children_of(parent)) == 0, (
        "它已经返回（终态在盘上）⇒ 在飞分子里没有它")


def test_the_previous_minimal_fix_would_miss_this_row(tmp_path, monkeypatch):
    """负控：同一行喂给上一轮那个判据（只看结算标记）⇒ 它漏算；新判据算上。

    这一条是本题与上一轮最小修法的差别所在。没有它，"解耦"就只是我的断言：
    旧判据给 False（不计入累计读数）、新判据给 True，差别在同一个机器读数上可见。
    旧判据在下面按它改前的写法复现（那个函数体逐字来自 `_occupies_fanout_slot`
    的上一版）。
    """
    def _settled_only(row) -> bool:
        """`_occupies_fanout_slot` 的上一版（逐字复现，只用于这条负控）。"""
        if row.get("outcome") != "refused":
            return True
        return any(str(x) == CO._SETTLED_MARK for x in (row.get("inputs") or []))

    store = _mk_store(tmp_path)
    c = _mk_conductor(store, max_fanout=2, g=RefusingG())

    def boom(*_a, **_kw):
        raise RuntimeError("替身：记账炸了")
    monkeypatch.setattr(c.meter, "charge_once", boom)

    parent = _parent(c)
    _revise(c, parent, "k0")
    row = next(x for x in store.rows("tasks")
               if x.get("parent_task_id") == parent and x.get("outcome") == "refused")
    assert _settled_only(row) is False, (
        f"旧判据居然算上了 ⇒ 这个负控没造出差异（inputs={row['inputs']}）")
    assert CO._occupies_fanout_slot(row) is True, "新判据必须算上这一行"
    assert len(c._admitted_children_of(parent)) == 1


# ---------------------------------------------------------------- 读数二：主控那一档（在飞口径）


def test_conductor_tier_dispatches_more_than_five_while_worker_refuses_at_five(tmp_path):
    """同一棵树：主控档同时在飞 20，工人档同时在飞 5；各自到点被拒、返回即腾位。

    两件事：①主控档的上限是 20（`FANOUT_LIMIT_BY_ROLE`），在飞 19 时第 20 件受理、
    在飞 20 时下一件被拒且报文里两个数都读得出来；②工人档在 5 处被拒（反真空），
    并把一行标成返回之后名额立刻还回来（所有者那句话的机器化）。
    """
    store = _mk_store(tmp_path)
    c = _mk_conductor(store, max_fanout=5)

    m_parent = _parent(c)
    _seed_in_flight(store, m_parent, 19, called_by="M")
    last = _revise(c, m_parent, "m19", by="M")
    assert last.outcome == "ok", (
        "主控那一档的同时在飞上限是 20，在飞 19 时这件必须派得进去；"
        f"拿到 {last.outcome}/{last.refusal_reason}")
    # `m19` 是同步返回的 ⇒ 它不留在在飞里；补一行 seed 把主控档填到恰好 20。
    _seed_in_flight(store, m_parent, 1, base=19, called_by="M")
    assert len(c._in_flight_children_of(m_parent)) == 20, "此刻在飞恰好 20"
    over = _revise(c, m_parent, "m20", by="M")
    assert over.refusal_reason == "fanout_exceeded", "工人档之外也要有反真空（主控也会触顶）"
    assert "在飞 20" in over.detail and "上限 20" in over.detail, over.detail

    worker_parent = _parent(c, doc_id="0002")
    _seed_in_flight(store, worker_parent, 5, called_by="H")
    refused = _revise(c, worker_parent, "w5", by="H")
    assert refused.refusal_reason == "fanout_exceeded", "工人档仍然在 5 处被拒（反真空）"
    assert "在飞 5" in refused.detail and "上限 5" in refused.detail, refused.detail

    # ---- 返回即腾位（所有者 2026-10-08 那句话的机器化）
    _mark_returned(store, c._in_flight_children_of(worker_parent)[0])
    freed = _revise(c, worker_parent, "w6", by="H")
    assert freed.outcome == "ok", (
        "有一行返回了 ⇒ 名额必须立刻还回来；"
        f"拿到 {freed.outcome}/{freed.refusal_reason}：{freed.detail}")


def test_conductor_tier_is_exactly_twenty(tmp_path):
    """主控那一档恰好是 20（同时在飞）：在飞 20 被拒、有一行返回后立刻受理。"""
    store = _mk_store(tmp_path)
    c = _mk_conductor(store, max_fanout=5)

    full = _parent(c)
    _seed_in_flight(store, full, 20, called_by="M")
    over = _revise(c, full, "m20", by="M")
    assert over.refusal_reason == "fanout_exceeded"
    assert "在飞 20" in over.detail and "上限 20" in over.detail, over.detail

    _mark_returned(store, c._in_flight_children_of(full)[0])
    assert len(c._in_flight_children_of(full)) == 20 - 1
    freed = _revise(c, full, "m20b", by="M")
    assert freed.outcome == "ok", (
        f"返回一行就该腾出一格（{freed.outcome}/{freed.refusal_reason}：{freed.detail}）")

    # 另一棵树：在飞 19 时第 20 件受理（边界另一侧）
    edge = _parent(c, doc_id="0002")
    _seed_in_flight(store, edge, 19, called_by="M")
    twentieth = _revise(c, edge, "e19", by="M")
    assert twentieth.outcome == "ok", (
        f"第 20 件必须受理，拿到 {twentieth.outcome}/{twentieth.refusal_reason}")


# ------------------------------------------- 读数三：触顶之后"只可等待"（所有者 2026-10-08 追加）
#
# 所有者逐字：「当达到派活上限后，父智能体或主控只可等待子智能体返回结果」。
# `summon` 的实现：算完在飞数、拿并发占位令牌之前先等（等的时候不占全局并发名额），
# 等完重算，仍然满才拒（报文尾部带上等的那一段读数）。


def _capture_await(c: CO.Conductor) -> list[dict]:
    """把 `summon` 内部那次 `_await_fanout_slot` 的返回值截下来：返回一个读数列表。

    为什么截返回值而不是解析日志文本：日志是给人看的，读数才是判据
    （`_log` 钩子坏了按纪律不该打断编排 —— 拿它当判据会把判据挂在一条
    "坏了也不该报错"的路径上）。
    """
    readings: list[dict] = []
    inner = c._await_fanout_slot

    def wrapper(parent_task_id, limit, *, token):
        out = inner(parent_task_id, limit, token=token)
        readings.append(out)
        return out

    c._await_fanout_slot = wrapper  # type: ignore[method-assign]
    return readings


def test_a_capped_summon_waits_and_dispatches_when_a_slot_frees_in_time(tmp_path):
    """正控：触顶之后等着，子代理在窗口内返回 ⇒ 这一件受理（不是被拒）。

    两件事：①`summon` 真的走了等待路径（截下来的读数 `waited is True`），
    ②等到之后按"返回即腾位"照常派出去（`outcome == "ok"`），且读数里
    `reason == "slot_freed"`、`in_flight_after < in_flight_before`。

    同步点不赌时序：后台线程等"读数出现"（= 主线程已经进了等待循环）再动手，
    然后只睡 0.4s，窗口给 5s。
    """
    store = _mk_store(tmp_path)
    c = _mk_conductor(store, max_fanout=3, fanout_wait_sec=5.0)
    parent = _parent(c)
    in_flight = _seed_in_flight(store, parent, 3)

    readings = _capture_await(c)

    def _return_one() -> None:
        deadline = time.monotonic() + 3.0
        while not readings and time.monotonic() < deadline:
            time.sleep(0.02)
        time.sleep(0.4)                  # 让它先在"在飞 3"上等一会儿
        _mark_returned(store, in_flight[0])

    t = threading.Thread(target=_return_one, daemon=True)
    t.start()
    try:
        ok = _revise(c, parent, "w3")
    finally:
        t.join(timeout=5.0)

    assert not t.is_alive(), "后台线程没在窗口内收工 ⇒ 这条判据的同步点失效了"
    assert readings, "没有等到等待路径的读数 ⇒ 这条正控在这一形态上没有牙"
    assert readings[-1]["waited"] is True, readings[-1]
    assert readings[-1]["reason"] == "slot_freed", readings[-1]
    assert readings[-1]["in_flight_before"] == 3 and readings[-1]["in_flight_after"] == 2, \
        readings[-1]
    assert readings[-1]["waited_sec"] > 0, "等过就应当有非零时长"
    assert ok.outcome == "ok", (
        "窗口内有人返回 ⇒ 这一件必须受理（不是被拒）；"
        f"拿到 {ok.outcome}/{ok.refusal_reason}：{ok.detail}")


def test_a_capped_summon_times_out_and_refuses_with_the_wait_reading(tmp_path):
    """负控：触顶之后等着，窗口内没人返回 ⇒ 仍拒，报文带上等的那一段读数。

    三态纪律：`wait_timeout` 不许冒充"腾出了名额"—— 台账上"等到了"与"没等到"
    必须分得开（前者继续派、后者拒并带上读数）。
    """
    store = _mk_store(tmp_path)
    c = _mk_conductor(store, max_fanout=3, fanout_wait_sec=0.3)
    parent = _parent(c)
    _seed_in_flight(store, parent, 3)

    readings = _capture_await(c)
    refused = _revise(c, parent, "over")
    assert readings and readings[-1]["reason"] == "wait_timeout", readings
    assert readings[-1]["waited"] is True and readings[-1]["in_flight_after"] == 3, readings[-1]

    assert refused.refusal_reason == "fanout_exceeded", (
        f"没人返回 ⇒ 仍然拒；拿到 {refused.outcome}/{refused.refusal_reason}")
    assert "在飞 3" in refused.detail and "上限 3" in refused.detail, refused.detail
    assert "触顶后等了" in refused.detail and "wait_timeout" in refused.detail, refused.detail
    assert len(c._in_flight_children_of(parent)) == 3, "等不出来不许把在飞读数改小"


def test_await_fanout_slot_is_disabled_by_a_zero_window(tmp_path):
    """单元级：窗口为 0 ⇒ `wait_disabled`、`waited=False`、读数原样不退（不冒充腾位）。"""
    store = _mk_store(tmp_path)
    c = _mk_conductor(store, max_fanout=3, fanout_wait_sec=0.0)
    parent = _parent(c)
    _seed_in_flight(store, parent, 3)

    off = c._await_fanout_slot(parent, 3, token=None)
    assert off["waited"] is False and off["waited_sec"] == 0.0, off
    assert off["reason"] == "wait_disabled", off
    assert off["in_flight_before"] == off["in_flight_after"] == 3, off
    assert off["limit"] == 3, off


def test_await_fanout_slot_honours_an_already_cancelled_token(tmp_path):
    """单元级：取消信号已置位 ⇒ `cancel_requested`，且不冒充腾出了名额。

    窗口必须开（`fanout_wait_sec>0`）：`budget <= 0` 那条早退排在取消检查之前，
    窗口为 0 时拿到的是 `wait_disabled` —— 这是实现里"不等"的优先级，不是缺陷。
    """
    store = _mk_store(tmp_path)
    c = _mk_conductor(store, max_fanout=3, fanout_wait_sec=5.0)
    parent = _parent(c)
    _seed_in_flight(store, parent, 3)

    token = CO.CancelToken()
    # 理由码必须是 `CANCEL_CODES` 里的值（`G-10`：自由文本不许绕过词表）。
    token.cancel("user")
    killed = c._await_fanout_slot(parent, 3, token=token)
    assert killed["waited"] is True and killed["reason"] == "cancel_requested", killed
    assert killed["in_flight_after"] == 3, "取消不冒充腾出了名额"


def test_await_fanout_slot_reports_slot_freed_when_a_child_returns(tmp_path):
    """单元级正控：等待期间有一行返回 ⇒ `slot_freed`，读数里两个数都对得上。"""
    store = _mk_store(tmp_path)
    c = _mk_conductor(store, max_fanout=3, fanout_wait_sec=5.0)
    parent = _parent(c)
    in_flight = _seed_in_flight(store, parent, 3)

    def _return_one() -> None:
        time.sleep(0.4)
        _mark_returned(store, in_flight[0])

    t = threading.Thread(target=_return_one, daemon=True)
    t.start()
    try:
        out = c._await_fanout_slot(parent, 3, token=None)
    finally:
        t.join(timeout=5.0)

    assert not t.is_alive(), "后台线程没在窗口内收工"
    assert out["reason"] == "slot_freed", out
    assert out["in_flight_before"] == 3 and out["in_flight_after"] == 2, out
    assert out["waited_sec"] > 0, out
    assert out["limit"] == 3, out


# ---------------------------------------------------------------- 判据口径本身


def test_policy_default_tier_is_policy_max_fanout():
    """工人档的上限只有一处来源：`Policy.max_fanout`（不许在别处再写一个 5）。"""
    for cap in (2, 3, 7):
        p = P.Policy(max_fanout=cap)
        assert P.fanout_limit_for(p, "H") == cap
        assert P.fanout_limit_for(p, "A") == cap


def test_unknown_initiator_falls_back_to_policy_default():
    """不在覆盖表里的发起方一律退回 `Policy.max_fanout`（保守方向，不fail-open）。"""
    p = P.Policy(max_fanout=4)
    assert P.fanout_limit_for(p, "Z") == 4
    # 闸门那一层的负控用真角色（H→G 是允许的边）：在飞 4 处仍拒，报文带在飞几与上限。
    r = P.check(p, P.Decision(frm="H", to="G", action="revise", fanout=4))
    assert r is not None and r.reason == "fanout_exceeded"
    assert "在飞 4" in r.detail and "上限 4" in r.detail, r.detail


# ---------------------------------------------------------------- 名额是逐实例的（所有者 2026-10-08）


def test_a_saturated_instance_does_not_block_another_parents_dispatch(tmp_path):
    """名额挂在实例（任务行）上，不挂在角色上：忙的那个满了，别人另起一个。

    所有者逐字：「如果 D 外派了 5 个智能体，又有其它人向 D 派活且不是之前唤起 D 的那个人，
    这时应该是唤起另一个 D2 而非让这个 D 去接手。」

    本仓库里"实例"的落点就是任务行：`Decision.fanout` 数的是"这一个父任务此刻在飞的
    子代理"，不是"这个角色一共有几个子在飞"。所以这条判据的两件事是：

    ① 父任务 P1 自己在飞 5 个（上限 5）⇒ 它自己再派一件被拒（它的位满了，这没错）；
    ② 另一个父任务 P2 派同一角色的活 ⇒ 立刻受理（它是另一个实例，自己的在飞数是 0）
       —— 这正是"唤起另一个 D2 而不是让 P1 里那个 D 去接手"在台账上的形态。

    为什么必须单列这一条：把名额挂到角色上（"这个角色一共有几个子在飞"）会把并行度
    压成"每个角色 5 个"，而那与所有者说的 20*(5*5*5*5) 是两回事 —— 后者要求名额沿链相乘。
    """
    store = _mk_store(tmp_path)
    c = _mk_conductor(store, max_fanout=5)
    p1 = _parent(c, doc_id="0001")
    p2 = _parent(c, doc_id="0002")
    assert p1 != p2

    _seed_in_flight(store, p1, 5, role="G", called_by="H")
    assert len(c._in_flight_children_of(p1)) == 5
    assert len(c._in_flight_children_of(p2)) == 0

    # ① 饱和的那个实例自己再派 ⇒ 拒（它的 5 个位满了）
    blocked = _revise(c, p1, "k-blocked", by="H")
    assert blocked.outcome == "refused" and blocked.refusal_reason == "fanout_exceeded", blocked

    # ② 另一个实例（P2）派同一角色的活 ⇒ 立刻受理（名额是逐实例的，不是逐角色的）
    other = _revise(c, p2, "k-other", by="H")
    assert other.outcome == "ok", (
        "名额被挂到角色上了：另一个父任务派同一角色也被拒 —— "
        f"拿到 {other.outcome}/{other.refusal_reason}：{other.detail}")

    # ③ 反真空：P2 那件跑完之后，P2 的在飞数回到 0（同步派活），累计读数两边各算各的
    assert len(c._in_flight_children_of(p2)) == 0
    assert len(c._in_flight_children_of(p1)) == 5, "P1 的 5 个还在飞，别被 P2 的派活动了"


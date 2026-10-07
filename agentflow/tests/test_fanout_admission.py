"""扇出口径判据：扇出 = 受理数，不是尝试数；上限按发起方角色取（题15 选B，2026-10-07）。

## 这一条判的是什么

闸门拒掉的召唤也落一行台账（`Conductor._refuse` 的 `note="refused:<reason>"`），
而旧实现的扇出读数是 `len(self._children_of(parent))` —— 数的是全部子行，
于是"被拒的那一次"自己也占一个名额。后果不是少派一件活，而是不可恢复：

    父任务触顶（受理 5 个）→ 之后每一次召唤都被 fanout_exceeded 拒掉
    → 每一次拒绝又落一行、又占一格 → 名额只增不减 → 父任务再也派不出活。

## 真机读数（工作区 `agentflow/projects/p9-post-merge-probe`，2026-10-07 台账）

顶趟行 `t-0001` 名下 10 个子行：

    t-0002 A search_literature   ok        （受理）
    t-0003 D propose_question    ok        （受理）
    t-0004 D register_conjecture refused invalid_params（闸门拒，没跑）
    t-0005 D register_conjecture ok        （受理）
    t-0006 E run_experiment      refused invalid_params（跑了、角色拒）
    t-0007 E run_experiment      refused fanout_exceeded  detail：已派生 5 个
    t-0008 E run_experiment      refused fanout_exceeded  detail：已派生 6 个
    t-0009 E run_experiment      refused fanout_exceeded  detail：已派生 7 个
    t-0010 E run_experiment      refused fanout_exceeded  detail：已派生 8 个
    t-0011 E run_script_experiment refused fanout_exceeded detail：已派生 9 个

detail 里那个 5→6→7→8→9 就是自我毒化的机器形态（每拒一次，读数涨一格）。
本趟主控只成功派了 3 件活（A 检索 / D 立题 / D 登记猜想），E 的实验永远进不去
⇒ `experiments=0`、收工门两格红。按新口径，`t-0001` 的受理数 = 4（t-0002/3/5 加
t-0006 这条跑过又拒的），4 < 5 ⇒ E 的实验本来派得进去。

## 三份读数在这里怎么落地

1. 自我毒化：`test_gate_refusal_does_not_consume_a_fanout_slot`（拒掉的尝试不让名额变少）
   与 `test_refused_attempts_at_the_cap_never_deepen_the_poison`（读数不随拒绝上涨）。
2. 主控那一档：`test_conductor_tier_dispatches_more_than_five_while_worker_refuses_at_five`
   与 `test_conductor_tier_is_exactly_twenty`。
3. 反真空：上面两条里"闸门仍然会拒、报文里带着上限与当前几"的那几段断言 ——
   它们防止有人用"把闸门拆掉"的方式让前两组变绿。
4. 口径的另一半：`test_ran_and_failed_child_still_counts` 与
   `test_ran_and_refused_child_still_counts` 咬住"运行过但失败/角色拒绝的仍占名额"，
   否则修法会滑成"凡 refused 都不算"。

## 受理标记为什么必须与 running 行同事务（题 21 选 B，2026-10-07 所有者裁定）

上一轮的最小修法把"占不占名额"挂在 `tokenmeter:settled` 上，而那是收尾的记账写回
（`_set_usage`）打的标记 —— 它能炸：`_charge_and_settle` 刻意兜住记账异常，兜住之后
这一行就缺标记 ⇒ 被当成"没跑" ⇒ 扇出少算 1（名额被少占，上限被悄悄放宽）。
本轮的判据换成"受理那一刻就落盘的标记"（`_ADMITTED_MARK`，与 `status="running"`
同一笔事务写下），于是它与后续任何一步的成败解耦。这一族新增四条读数：

- `test_the_admission_mark_is_on_disk_while_the_handler_runs`：跑到一半看盘，标记已在
  （而结算标记还不在）—— 这是"在受理那一刻打的"的结构性证据；
- `test_a_contained_charge_failure_still_occupies_the_slot`：记账抛异常被兜住 ⇒ 仍占名额；
- `test_a_failed_charge_writeback_still_occupies_the_slot`：记账写回炸掉（异常逸出
  `summon`）⇒ 仍然占名额，且闸门照旧按它占的那一格拒下一件；
- `test_the_previous_minimal_fix_would_miss_this_row`：负控 —— 同一个行喂给旧判据
  （只看结算标记）给 False、喂给新判据给 True，这就是本轮与上一轮的差别。

老行（本题之前落盘的、没有受理标记的行）退回读结算标记：历史台账的判法与改前一致
（`test_a_legacy_refused_row_keeps_the_old_verdict`）。

## 展示面为什么单独有一条

`_children_of` 还服务 `SummonResult.children`（谁试过什么必须看得见）。本次修法
不就地改它，而是另加 `_admitted_children_of`；`test_display_face_still_lists_attempts`
就是"没有顺手把展示面改坏"的机器证据。
"""

from __future__ import annotations

import pytest

from agentflow import conductor as CO
from agentflow import policy as P
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
    """G 的替身：`bad_doc_id` 那一次跑了、炸了（`outcome=failed`），其余照常。

    "炸一次"而不是"永远炸"：这两条判据要的是"失败的那一行也占名额"，
    所以后面还得有一次正常的派活来把上限用满。
    """

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


def _mk_conductor(store, *, max_fanout: int, g=None) -> CO.Conductor:
    return CO.Conductor(
        store,
        policy=P.Policy(max_concurrency=8, max_fanout=max_fanout,
                        max_tasks_per_run=500, wall_clock_sec=600),
        registry={"H": ("object", FakeH()), "G": ("object", g or FakeG())},
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


# ---------------------------------------------------------------- 读数一：自我毒化


def test_gate_refusal_does_not_consume_a_fanout_slot(tmp_path):
    """闸门拒掉的召唤不占名额：受理数到 cap-1 时，下一次合法派活必须成功。

    改前（同一条探针）：被拒的那一行也算进 `fanout` ⇒ 第 3 件合法派活
    看到 `fanout=cap` ⇒ 报 `fanout_exceeded`，父任务从此再也派不出活。
    """
    c = _mk_conductor(_mk_store(tmp_path), max_fanout=3)
    parent = _parent(c)

    for i in range(2):                      # 受理 2 件（cap=3，还剩 1 格）
        assert _revise(c, parent, f"k{i}").outcome == "ok"

    seed = _bad_revise(c, parent, "seed")
    assert seed.refusal_reason == "invalid_params", (
        f"这一条要的是闸门拒绝（根本没跑），拿到 {seed.outcome}/{seed.refusal_reason}")
    assert seed.task_id, "被拒的召唤必须落行（谁试过什么不许丢）"

    # 合法派活：改前这里被 fanout_exceeded 拒掉（自我毒化），改后必须受理。
    ok = _revise(c, parent, "k5")
    assert ok.outcome == "ok", (
        "扇出被自我毒化：闸门拒掉的尝试占了名额"
        f"（{ok.outcome}/{ok.refusal_reason}：{ok.detail}）")
    assert len(c._admitted_children_of(parent)) == 3


def test_refused_attempts_at_the_cap_never_deepen_the_poison(tmp_path):
    """触顶之后每次尝试照旧落行，但扇出读数不许再涨（真机 detail 里那个 5→9）。"""
    c = _mk_conductor(_mk_store(tmp_path), max_fanout=3)
    parent = _parent(c)
    for i in range(3):
        assert _revise(c, parent, f"k{i}").outcome == "ok"

    refused = [_revise(c, parent, f"over{i}") for i in range(3)]
    assert [r.refusal_reason for r in refused] == ["fanout_exceeded"] * 3
    for r in refused:
        assert "已受理 3" in r.detail and "上限 3" in r.detail, (
            f"报文要能看出当前几与上限是多少，拿到：{r.detail}")

    assert len(c._children_of(parent)) == 3 + 3, "被拒的尝试照旧要落行"
    assert len(c._admitted_children_of(parent)) == 3, "扇出读数不许随拒绝上涨"


def test_display_face_still_lists_attempts(tmp_path):
    """展示面没被改坏：`_children_of` 仍然列出全部尝试（含被拒的）。"""
    c = _mk_conductor(_mk_store(tmp_path), max_fanout=3)
    parent = _parent(c)
    assert _revise(c, parent, "k0").outcome == "ok"
    assert _bad_revise(c, parent, "seed").refusal_reason == "invalid_params"

    all_kids = c._children_of(parent)
    admitted = c._admitted_children_of(parent)
    assert len(all_kids) == 2, f"展示面要看到两次尝试，拿到 {all_kids}"
    assert len(admitted) == 1, f"扇出面只数受理过的那一次，拿到 {admitted}"
    assert set(admitted) <= set(all_kids)


# ---------------------------------------------------------------- 口径的另一半


def test_ran_and_failed_child_still_counts(tmp_path):
    """跑了但失败的子行仍然占名额（它确实消耗了一次派活）。"""
    c = _mk_conductor(_mk_store(tmp_path), max_fanout=2, g=BoomG())
    parent = _parent(c)
    boom = _revise(c, parent, "k0")
    assert boom.outcome == "failed" and boom.error
    assert len(c._admitted_children_of(parent)) == 1
    assert _revise(c, parent, "k1").outcome == "ok"      # 第 2 格用完
    over = _revise(c, parent, "k2")
    assert over.refusal_reason == "fanout_exceeded", (
        f"失败的那一行必须占名额，拿到 {over.outcome}/{over.refusal_reason}")


def test_ran_and_refused_child_still_counts(tmp_path):
    """跑了、角色自己拒了的子行也算受理（`t-0006` 那一档，不是闸门拒绝）。"""
    c = _mk_conductor(_mk_store(tmp_path), max_fanout=2, g=RefusingG())
    parent = _parent(c)
    role_refusal = _revise(c, parent, "k0")
    assert role_refusal.outcome == "refused" and role_refusal.refusal_reason == "invalid_params"
    assert len(c._admitted_children_of(parent)) == 1, (
        "角色拒绝发生在跑过之后 ⇒ 它占名额（与闸门拒绝分档）")
    assert _revise(c, parent, "k1").outcome == "ok"
    over = _revise(c, parent, "k2")
    assert over.refusal_reason == "fanout_exceeded"


# ---------------------------------------------------------------- 受理标记（题 21 选 B）


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
    """闸门拒掉的那一行没有受理标记（这就是它不占名额的机械理由）。"""
    c = _mk_conductor(_mk_store(tmp_path), max_fanout=3)
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


def test_a_legacy_refused_row_keeps_the_old_verdict(tmp_path):
    """向后兼容：本题之前落盘的行没有受理标记，退回读结算标记 ⇒ 判法与改前一致。

    为什么必须有：扇出判据读的是历史台账（真机 `p9-post-merge-probe` 的 10 个子行
    就是老行）。若新判据只认 `conductor:admitted`，那些"跑过又拒"的老行会被重新
    读成"没跑"—— 历史读数当场分家，而且分家方向是名额被少占。这一版没有动
    `schema.Task`，所以老行连字段都不用补。
    """
    base = {"role": "G", "action": "revise", "called_by": "H", "status": "done",
            "outcome": "refused", "refusal_reason": "invalid_params"}
    assert CO._occupies_fanout_slot({**base, "inputs": [CO._SETTLED_MARK]}) is True, \
        "老行（跑过又拒、只有结算标记）应当仍然占名额"
    assert CO._occupies_fanout_slot({**base, "inputs": [CO._ADMITTED_MARK]}) is True, \
        "新行（有受理标记）占名额"
    assert CO._occupies_fanout_slot({**base, "inputs": []}) is False, \
        "老行（闸门拒、inputs 为空）不占名额"
    assert CO._occupies_fanout_slot({**base, "outcome": "ok", "inputs": []}) is True, \
        "反真空：非 refused 的行照旧一律占名额"


def test_a_contained_charge_failure_still_occupies_the_slot(tmp_path, monkeypatch):
    """④（被兜住的那一半）：记账抛异常被 `_charge_and_settle` 兜住 ⇒ 该行仍占名额。

    `_charge_and_settle` 刻意兜住记账异常（钱已经花了、活已经干完了，不许让它翻转
    一次已完成的召唤）。兜住之后这一行就没有结算标记 —— 上一轮的最小修法据此
    把它读成"没跑"，扇出少算 1。
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
        "记账失败让这条「跑了又拒」的行从扇出里消失了（少算 1 ⇒ 名额被少占）")
    assert _revise(c, parent, "k1").outcome == "ok"      # 第二个名额被正常用掉
    over = _revise(c, parent, "k2")
    assert over.refusal_reason == "fanout_exceeded", (
        f"那一行没占住名额 ⇒ 第 3 件本该被拒却{over.outcome}")


def test_a_failed_charge_writeback_still_occupies_the_slot(tmp_path, monkeypatch):
    """④（写回那一半）：`_set_usage` 炸掉 ⇒ 该行仍然算占名额。

    这是所有者点名的那个形态（"把记账写回弄炸"）。如实记一条观察：`_set_usage`
    的调用点在 `_charge_and_settle` 的 try 之外，所以它的异常会逸出 `summon`
    ——本判据把这一点也断言出来，免得把"被兜住"与"逸出"混成一句话。
    无论哪种，行的终态与受理标记都已经在盘上（写 running 行时就写了）。
    """
    store = _mk_store(tmp_path)
    c = _mk_conductor(store, max_fanout=2, g=RefusingG())
    # 父任务要在注入之前造好：`_set_usage` 是每一次召唤收尾都走的，
    # 注入之后再造父任务会让它自己也炸（那是另一个形态，不是这一条要判的）。
    parent = _parent(c)
    real_set_usage = c._set_usage

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
        "记账写回失败让这条「跑了又拒」的行从扇出里消失了（少算 1）")

    # 反真空：把注入撤掉，后两件照常跑 —— 闸门必须仍然按那一行占住的格子拒第 3 件。
    monkeypatch.setattr(c, "_set_usage", real_set_usage)
    assert _revise(c, parent, "k1").outcome == "ok"
    over = _revise(c, parent, "k2")
    assert over.refusal_reason == "fanout_exceeded", (
        f"那一行没占住名额 ⇒ 第 3 件本该被拒却{over.outcome}")


def test_the_previous_minimal_fix_would_miss_this_row(tmp_path, monkeypatch):
    """负控：同一行喂给上一轮那个判据（只看结算标记）⇒ 它漏算；新判据算上。

    这一条是本题与上一轮最小修法的差别所在。没有它，"解耦"就只是我的断言：
    旧判据给 False（不占名额）、新判据给 True，差别在同一个机器读数上可见。
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


# ---------------------------------------------------------------- 读数二：主控那一档


def test_conductor_tier_dispatches_more_than_five_while_worker_refuses_at_five(tmp_path):
    """同一棵树：主控派得进第 6 件，工人档仍在 5 处被拒。"""
    c = _mk_conductor(_mk_store(tmp_path), max_fanout=5)
    parent = _parent(c)

    m_kids = [_revise(c, parent, f"m{i}", by="M") for i in range(6)]
    assert [k.outcome for k in m_kids] == ["ok"] * 6, (
        "主控那一档的扇出上限是 20（题15 选B），第 6 件必须派得进去；"
        f"拿到 {[(k.outcome, k.refusal_reason) for k in m_kids]}")

    worker_parent = _parent(c, doc_id="0002")
    for i in range(5):
        assert _revise(c, worker_parent, f"w{i}", by="H").outcome == "ok"
    over = _revise(c, worker_parent, "w5", by="H")
    assert over.refusal_reason == "fanout_exceeded", "工人档仍然在 5 处被拒（反真空）"
    assert "已受理 5" in over.detail and "上限 5" in over.detail, over.detail


def test_conductor_tier_is_exactly_twenty(tmp_path):
    """主控那一档恰好是 20：第 20 件受理，第 21 件被拒且报文写着上限 20。"""
    c = _mk_conductor(_mk_store(tmp_path), max_fanout=5)
    parent = _parent(c)
    kids = [_revise(c, parent, f"m{i:02d}", by="M") for i in range(20)]
    assert [k.outcome for k in kids] == ["ok"] * 20, (
        f"第 20 件必须受理，拿到 {[(k.outcome, k.refusal_reason) for k in kids][-3:]}")
    over = _revise(c, parent, "m20", by="M")
    assert over.refusal_reason == "fanout_exceeded"
    assert "已受理 20" in over.detail and "上限 20" in over.detail, over.detail


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
    # 闸门那一层的负控用真角色（H→G 是允许的边）：4 处仍拒，报文带着上限与当前几。
    r = P.check(p, P.Decision(frm="H", to="G", action="revise", fanout=4))
    assert r is not None and r.reason == "fanout_exceeded"
    assert "已受理 4" in r.detail and "上限 4" in r.detail, r.detail

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

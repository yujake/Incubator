# -*- coding: utf-8 -*-
"""判据乙：D 走过不去的那条 proof 路 —— 拒绝报文必须点名下一步，且同形重试不许无声。

## 现场（2026-11-05 真机 `projects/R-mk-infinite-90`，只读）

`data/attack_plans.json` 的 history 里，同一个难题从 `attack-000013` 一路重交到
`attack-000016`（15 轮），每一轮的判词逐字都是：

    论证没能落进 statements（这份手稿不是框架渲染的（缺洗稿元信息），请让 F 用
    proof 动作重写）—— 那是没做成，不是做过了；没有命题号 ⇒ 手稿保持计划名（不凭空造号）；
    V 签：待签（还没有命题号（B 的登记没成）⇒ 在册台账查不到…）

## 断在哪一跳

1. 判"缺洗稿元信息"的是收方 B，不是 F 的 proof 动作：`agent_b/register_statement.py`
   的那道兜底审计读手稿里的 `- 依赖面洗稿：`（`depsection.WASH_MARK`），并且只在稿
   来自 `carried_by_D` / `disk` 时才判（`param` 直递不判 —— B 拿不到它的落点）。
2. 那句话点的下一步是「让 F 用 proof 动作重写」—— 而 F 的动作表里没有 `proof`
   （`specs/f.py`：`create_plan` / `step` / `status` / `list_plans`；`proof` 只是
   `step` 的一种产物）⇒ 收到拒信的人没有任何可执行的动作。
3. 于是它只能原样再交一次同一条路径 —— 而洗稿元信息那一行只有 F 的秘书在一轮 proof
   里才盖得上（`agent_f.core._wash_manuscript` → `mark_washed`）。同一条路径重交
   永远不会长出那一行：结构上走不出去，报文里又没说该换哪条路。

## 判据

| 判据 | 它要证明的事 | 改前红在哪 |
|---|---|---|
| a 报文点名下一步 | 逐字给出动作 + 参数形状（`framework_summon(role="F", action="step", params={"plan_id": …})`） | 改前只有"请让 F 用 proof 动作重写"，没有任何参数 |
| b 第二轮同形重试被计数 | `streak` 进 history（`attack.status` 的 `history_tail` 看得见） | 改前每次都从头数，重试是静默的 |
| c 反真空 | 把报文里那两句摘掉 ⇒ a 必红 | —— |

不扩大：`param` 直递那一档仍不判洗稿（与既有判据同一条边界）。
"""
from __future__ import annotations

import pathlib
import sys

_TESTS = pathlib.Path(__file__).resolve().parent
_SRC = _TESTS.parents[0] / "src"
for _p in (str(_SRC), str(_TESTS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from agentflow import depsection as DS  # noqa: E402
from agentflow.agent_f import core as FC  # noqa: E402
from agentflow.agent_f.core import AgentF  # noqa: E402

import test_b_manuscript_must_be_framework_rendered as T  # noqa: E402

SHAPE = 'framework_summon(role="F", action="step", params={"plan_id":'


def _refusing_register(tmp_path: pathlib.Path):
    """走 D 那条路：把盘上那份手写的按号稿交给 B（`proof_manuscript=""` ⇒ 兜底读盘）。"""
    store = T._ws(tmp_path)
    T._add_statement(store, T.THEOREM_A)
    sid = T._seed_target(store)
    rel = DS.manuscript_relpath(statement_id=sid)
    path = pathlib.Path(store.root) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(T._handwritten(sid), encoding="utf-8")
    return T._register(store)


# ============================================================ a 报文点名下一步
def test_a_the_refusal_names_the_exact_next_action_and_its_params(
        tmp_path: pathlib.Path) -> None:
    """a：`manuscript_not_washed` 的报文里逐字给出下一步动作 + 参数形状。

    改前红：`next_step` 这一格不存在，`error` 只有"请让 F 用 proof 动作重写"。
    """
    got = _refusing_register(tmp_path)
    assert got.get("kind") == T.KIND, got
    assert str(got.get("error") or "").strip() == T.MESSAGE, got
    next_step = str(got.get("next_step") or "")
    assert SHAPE in next_step, next_step
    # 参数形状要能照着粘：参数名与占位符都在。
    assert '"<这一轮的计划号>"' in next_step, next_step
    # 还要说清"只给路径不行"—— 那是空转的根。
    assert "proof_manuscript=<正文>" in next_step, next_step
    # 机器可读的那一格（不想让人从散文里解析）。
    action = dict(got.get("next_action") or {})
    assert action.get("role") == "F" and action.get("action") == "step", action
    assert "plan_id" in dict(action.get("params") or {}), action


def test_b_f_side_fills_in_the_real_plan_id() -> None:
    """b（正控）：F 那一侧拿得到计划号，所以它拼出来的形状可以直接粘。"""
    text = FC.not_washed_next_step("000016")
    assert 'params={"plan_id": "000016"}' in text, text
    assert SHAPE in text, text


# ============================================================ c 反真空
def test_c_without_the_sentences_the_refusal_goes_back_to_nothing(
        tmp_path: pathlib.Path, monkeypatch) -> None:
    """c：把报文里那两句摘掉 ⇒ a 必须红（退回改前那句只有"重写"的拒信）。"""
    monkeypatch.setattr(DS, "NOT_WASHED_NEXT_STEP", "")
    got = _refusing_register(tmp_path)
    assert got.get("kind") == T.KIND, got
    assert str(got.get("next_step") or "") == "", (
        f"摘掉那两句之后报文里仍然有下一步 ⇒ a 的绿不是那两句话给的：{got}")


# ============================================================ d 同形重试被计数
def test_d_same_shape_retries_are_counted_across_plans_of_one_problem() -> None:
    """d：同一个 `problem_key` 下、同一种拒绝跨计划累计（真机是一次重试一份新计划）。"""
    plans = [
        {"plan_id": "000013", "problem_key": "p3",
         "history": [{"round": 1, "refusal": {"kind": T.KIND}}]},
        {"plan_id": "000014", "problem_key": "p3",
         "history": [{"round": 1, "refusal": {"kind": T.KIND}}]},
        {"plan_id": "000015", "problem_key": "another",
         "history": [{"round": 1, "refusal": {"kind": T.KIND}}]},
        {"plan_id": "000016", "problem_key": "p3",
         "history": [{"round": 1, "refusal": {"kind": "something_else"}}]},
    ]
    assert FC.proof_refusal_streak(
        plans, problem_key="p3", kind=T.KIND) == 2
    assert FC.proof_refusal_streak(
        plans, problem_key="", kind=T.KIND) == 0


def _plan(agent: AgentF) -> dict:
    got = agent.create_plan(
        problem="P3（判据乙夹具）", problem_key="probe-p3",
        subgoals=[{"sid": "P3", "text": "证明 P3", "owner": "F", "status": "todo",
                   "testable": "判据夹具"}])
    assert got.get("created") is True, got
    return next(dict(r) for r in agent.store.rows("attack_plans")
                if str(r.get("plan_id")) == str(got["plan_id"]))


#: 这一轮 F 的 proof 产物（一步，引一条在册号）。
PRODUCT = {"product": "proof", "strategy": "局部—整体", "why_strategy": "判据夹具",
           "steps": [{"n": 1, "text": "由在册定理得结论", "cites": ["stmt:000013"],
                      "assumption": False, "role": "推导步", "problem": ""}]}


def test_e_the_streak_lands_in_the_round_detail_and_in_history(
        tmp_path: pathlib.Path, monkeypatch) -> None:
    """e：D 那条路上一轮 proof 被这条拒 ⇒ `refusal` 有 `streak`，detail 点名下一步。

    这里把"同 problem_key 下已经拒过一次"打桩进计数函数 —— 判的是 F 这一侧有没有
    消费那个计数、有没有把可粘贴的下一步写进 detail。
    """
    store = T._ws(tmp_path)
    agent = AgentF(store)
    plan = _plan(agent)
    plan_id = str(plan["plan_id"])
    monkeypatch.setattr(FC, "proof_refusal_streak", lambda plans, *, problem_key, kind: 1)
    monkeypatch.setattr(
        AgentF, "_wash_manuscript",
        lambda self, m: {"submittable": True, "checked": True, "washed": True,
                         "actor": "secretary-F", "text": str(m.get("text") or "")})
    monkeypatch.setattr(
        AgentF, "_proof_outlet",
        lambda self, product, sg, *, plan, proof_manuscript="": {
            "ok": False, "why": "这份手稿不是框架渲染的（缺洗稿元信息），请让 F 用 proof 动作重写",
            "refused_kind": DS.REFUSED_NOT_WASHED, "manuscript_received": {}})

    out = agent._apply_round(PRODUCT, plan["subgoals"][0], plan=plan, owner="F")
    refusal = dict(out.get("refusal") or {})
    assert refusal.get("kind") == DS.REFUSED_NOT_WASHED, out
    assert int(refusal.get("streak") or 0) == 2, out
    detail = str(out.get("detail") or "")
    assert f'"plan_id": "{plan_id}"' in detail, detail
    assert "同形拒绝第 2 次" in detail, detail
    assert "别再重交同一份稿或同一条路径" in detail, detail
    # F 说"洗过了"而 B 说"缺元信息"⇒ 这一条必须被当成要上报的缺陷，而不是原地重试。
    assert "读数打架" in detail, detail

    # 落盘可见：同一段读数进 history（`attack.status` 的 `history_tail` 读的就是它）。
    monkeypatch.setattr(
        AgentF, "_deploy",
        lambda self, sg, *, plan: {
            "action": "proof", "outcome": "progress", "detail": detail,
            "evidence": [], "product": {"product": "proof", "strategy": "局部—整体"},
            "count_attempt": True, "refusal": refusal})
    agent.step(plan_id)
    saved = next(dict(r) for r in store.rows("attack_plans")
                 if str(r.get("plan_id")) == plan_id)
    landed = dict((saved.get("history") or [])[-1].get("refusal") or {})
    assert landed.get("kind") == DS.REFUSED_NOT_WASHED, saved.get("history")
    assert int(landed.get("streak") or 0) == 2, saved.get("history")

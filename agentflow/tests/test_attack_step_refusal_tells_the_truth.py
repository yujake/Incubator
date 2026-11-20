"""判据：`attack.step` 被拒时，回执与台账必须说真话（真机 lp-ball-13 的 P0-2 / P0-3 / 审计痕迹）。

## 现场（`temp/mineloop/MINE-LOOP-lp-ball-13.md` §P0-1/P0-2/P0-3）

`agent_f/core.py` 的 `_merged_plan_round` 的 dict 解包被一次 lint 抹成 set 字面量 ⇒ 每次
`attack.step` 的写回都抛 `TypeError: unhashable type: 'dict'` ⇒ `tools/attack_tools.py`
的 `_guard` 把它折成「校验失败：unhashable type: 'dict'（这一笔没有落库）」。三个后果：

1. 框架 bug 伪装成"你交的东西不合格"（F 15 次调用 15 次同一个拒信，只会换措辞重试）；
2. 拒信谎报落库（稿同一秒真的落了盘：行 722 / 814 / 895）；
3. 校验器算出的逐条问题被吞（行 501/560/789 各 8 条「steps[k] 既没有 cites 也没有声明成
   前提」；行 895 是 0 条 —— 那一份其实合格）。

## 这份文件钉五件事

a 分档：框架级 TypeError ⇒ 受控码 `framework_error`（不是 `validation_error`），且 errorstats
  数得到这一条（类目 `tool_refused_controlled`、码位就是 `framework_error`）；
b 诊断：校验器的逐条问题（8 条）在异常路径上也要带出去；
c 落库：拒信里"有没有落库"以盘上事实为准（写成功但后续异常 ⇒ 必须说已落库，并点名那份稿）；
d 审计：被拒那一轮的 `history[*].refusal` 写得进去（两条拒绝路径各一条）；
e 反真空：a / b / c 各自的判据被打桩掉之后必须红。

## 为什么这份用例不调模型

`_apply_round` 的命题形态闸（`Secretary.judge_proposition_form`）是真模型。要它"此前已判过、
合格"，用 `conftest.seed_proposition_form_ok` 预置一条缓存读数（生产里命中的正是这条缓存）
—— 于是整份用例跑完 `usage_ledger` 必须是 0 行（最后一条用例钉住这一点）。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentflow import attackround as AR
from agentflow import errorstats as ES
from agentflow import refusalfault as RF
from agentflow.agent_f import core as CD
from agentflow.store import Store
from agentflow.tools import attack_tools as AT
from agentflow.tools.base import ToolRegistry
from conftest import seed_proposition_form_ok

#: 一条"设…则…"形状的命题（形态闸的缓存按正文 sha 命中，与 kind 无关）。
PROPOSITION = "设 K 是中心对称紧凸集，则对一切 t∈R 有 A_K(t) ≤ A_K(0)。"


# ------------------------------------------------------------------ 夹具


def _steps_without_cites(n: int = 9) -> list[dict]:
    """会话行 501 的形状：首步声明成前提，其余步既没给 `cites` 也没写 `assumption`。"""
    return ([{"assumption": True, "text": "Brunn-Minkowski 定理（前提）。"}]
            + [{"text": f"第 {i} 步的推导正文。"} for i in range(2, n + 1)])


def _steps_all_assumptions() -> list[dict]:
    """一份过得了逐条校验的稿（会话行 895 那一份的形状：0 条问题）。"""
    return [{"assumption": True, "text": "Brunn-Minkowski 定理（前提）。"},
            {"assumption": True, "text": "凹性与偶性（前提）。"}]


def _product(steps: list[dict] | None = None, *,
             proposition: str = PROPOSITION) -> dict:
    return {"kind": "proof", "proposition": proposition,
            "strategy": AR.STRATEGIES[0],
            "steps": list(_steps_without_cites() if steps is None else steps)}


def _reg(store: Store) -> ToolRegistry:
    reg = ToolRegistry(name="guardfix")
    AT.register(reg, store=store)
    reg.bound_role = "F"  # `P-14`：`attack.*` 的写侧唯一主人是 F
    return reg


def _plan(store: Store) -> tuple[ToolRegistry, str]:
    """经工具层立一条带 F 子目标的计划（不绕过被测的那一层）。"""
    reg = _reg(store)
    res = reg.call("attack.create_plan", problem="难题", problem_key="k-a",
                   subgoals=[{"sid": "s1", "text": "推进 A", "testable": "x",
                              "owner": "F"}])
    assert res.ok, res.error
    return reg, str(res.data["plan_id"])


def _form_gate_passed(store: Store) -> None:
    """预置"命题形态闸此前判过、合格"的缓存读数 ⇒ 这一关不再问模型。"""
    seed_proposition_form_ok(store.root, PROPOSITION, kind="theorem", role="F")


def _break_the_plan_write(monkeypatch: pytest.MonkeyPatch) -> None:
    """把真机那一行原样打回去：写回合并点抛那个 TypeError。

    打桩点是根因所在的那一个函数（`_merged_plan_round`），不是 `_guard` —— 这样被测的
    仍是真路径：`_apply_round` 照样跑（稿照样落盘），只有写回那一笔炸。
    """

    def boom(*_a: object, **_k: object) -> dict:
        raise TypeError("unhashable type: 'dict'")

    monkeypatch.setattr(CD, "_merged_plan_round", boom)


def _history(store: Store, plan_id: str) -> list[dict]:
    row = next(r for r in store.rows("attack_plans")
               if str(r.get("plan_id")) == plan_id)
    return [dict(h) for h in (row.get("history") or [])]


def _bullets(text: str) -> list[str]:
    """回执里逐条问题那几行（`- steps[k] …` 的机器可读形态）。"""
    return [ln for ln in str(text or "").splitlines() if ln.startswith("- steps[")]


def _a_holds(res: object) -> bool:
    """判据 a：框架级异常被报成 `framework_error`，且明说不是模型的输入不合格。"""
    text = str(getattr(res, "error", "") or "")
    meta = dict(getattr(res, "meta", {}) or {})
    return (getattr(res, "ok", None) is False
            and meta.get("kind") == AT.FRAMEWORK_ERROR_KIND
            and meta.get("refusal_code") == AT.FRAMEWORK_ERROR_KIND
            and "校验失败" not in text
            and "框架侧的问题" in text
            and "换措辞重试没有用" in text)


# ------------------------------------------------------------------ a 分档


def test_a_a_framework_type_error_is_not_your_validation_failure(
    store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """a：同一支 TypeError ⇒ `framework_error`，而不是"校验失败"。"""
    reg, pid = _plan(store)
    _form_gate_passed(store)
    _break_the_plan_write(monkeypatch)
    res = reg.call("attack.step", plan_id=pid, product=_product(_steps_all_assumptions()))

    assert _a_holds(res), res.error
    assert "不是你交的东西不合格" in res.error
    assert res.meta.get("kind") != "validation_error"
    # 那一份其实是合格的（会话行 895 的形状）：回执必须这么说，而不是留白
    assert "0 条" in res.error


def test_a_the_framework_bug_is_countable_in_errorstats(
    store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """a 的读数那一半：这一条在 errorstats 里数得到，码位就是 `framework_error`。"""
    reg, pid = _plan(store)
    _form_gate_passed(store)
    _break_the_plan_write(monkeypatch)
    res = reg.call("attack.step", plan_id=pid, product=_product(_steps_all_assumptions()))

    (store.root / "sessions").mkdir(exist_ok=True)
    record = {"kind": "agent_step", "role": "F", "index": 3, "shape": "tool",
              "ts": "2026-11-20T13:16:36+08:00",
              "payload": {"name": "attack.step"},
              "result": {"ok": res.ok, "error": res.error, "data": res.data,
                         "meta": res.meta}}
    (store.root / "sessions" / "2026-11-20.jsonl").write_text(
        json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")

    stats = ES.error_action_stats(store.root)
    assert stats.checked, stats.reason
    assert stats.count("F", "framework_error") == 1, stats.by_role
    assert stats.samples["framework_error"][0]["code"] == AT.FRAMEWORK_ERROR_KIND
    # 改前它落在兜底那一档（"哪一族都不认"）：读数里看不见"框架 bug"这件事
    assert stats.sources["unclassified"]["tool"] == 0
    assert stats.sources["hits"]["codes"]["F"] == {AT.FRAMEWORK_ERROR_KIND: 1}


# ------------------------------------------------------------------ b 诊断


def test_b_a_validation_refusal_carries_every_problem_the_validator_computed(
    store: Store,
) -> None:
    """b（写回正常那一档）：8 条问题逐条到模型手里（会话行 501/560/789 各 8 条）。"""
    reg, pid = _plan(store)
    res = reg.call("attack.step", plan_id=pid, product=_product())

    assert res.ok is True, res.error
    reason = str(res.data.get("reason") or "")
    lines = _bullets(reason)
    assert len(lines) == 8, reason
    assert "steps[2]" in reason and "steps[9]" in reason
    assert "cites" in reason and "assumption" in reason
    # 可执行的下一步也要在（只说"校验失败"没有可操作性）
    assert "再把同一份交一次" in reason
    # 这一条拒收没有落任何稿：拒信不许含糊（P0-2 的反面也要求说清）
    assert "这一轮没有落稿" in reason


def test_b_the_exception_path_does_not_swallow_the_verdict(
    store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """b（异常路径）：写回炸了，校验器那 8 条也要带出去（P0-3 的信息毁灭）。"""
    reg, pid = _plan(store)
    _break_the_plan_write(monkeypatch)
    res = reg.call("attack.step", plan_id=pid, product=_product())

    assert res.meta.get("kind") == AT.FRAMEWORK_ERROR_KIND, res.error
    lines = _bullets(res.error)
    assert len(lines) == 8, res.error
    assert "steps[2]" in res.error and "steps[9]" in res.error
    assert "一条没丢" in res.error


# ------------------------------------------------------------------ c 落库


def test_c_the_refusal_says_what_really_landed_on_disk(
    store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """c：稿真的落了盘而写回炸了 ⇒ 拒信必须说已落库，并点名那份稿。

    这正是 lp-ball-13 的行 722 / 814 / 895：稿与推进台账同一秒落盘，拒信却说"没有落库"。
    """
    reg, pid = _plan(store)
    _form_gate_passed(store)
    _break_the_plan_write(monkeypatch)
    res = reg.call("attack.step", plan_id=pid, product=_product(_steps_all_assumptions()))

    assert res.meta.get("kind") == AT.FRAMEWORK_ERROR_KIND, res.error
    landing = dict(res.meta.get("landing") or {})
    assert landing.get("checked") is True, landing
    assert landing.get("landed") is True, landing
    manuscript = store.root / "reports" / "f-proof-000000.md"
    assert manuscript.is_file(), "夹具没造出'写成功'：稿必须真的在盘上"
    assert "已落库" in res.error
    assert f"reports/{manuscript.name}" in res.error


def test_c_the_other_way_round_says_nothing_landed(
    store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """c 的反向那一半：什么都没落盘时也必须如实说"没有落库"（不是恒说已落库）。"""
    reg, pid = _plan(store)
    _break_the_plan_write(monkeypatch)
    # 不给形态闸缓存 ⇒ 这一轮在形态闸就被受控拒，`_apply_round` 不落任何稿
    res = reg.call("attack.step", plan_id=pid, product=_product(_steps_all_assumptions()))

    assert res.meta.get("kind") == AT.FRAMEWORK_ERROR_KIND, res.error
    landing = dict(res.meta.get("landing") or {})
    assert landing.get("checked") is True, landing
    assert landing.get("landed") is False, landing
    assert "这一笔没有落库" in res.error


# ------------------------------------------------------------------ d 审计痕迹


def test_d_a_validation_refusal_leaves_a_refusal_row(store: Store) -> None:
    """d（写回正常那一档）：被拒那一轮的 `refusal` 在盘上，逐条 8 条也在。"""
    reg, pid = _plan(store)
    reg.call("attack.step", plan_id=pid, product=_product())

    refusal = dict((_history(store, pid)[-1] or {}).get("refusal") or {})
    assert refusal.get("kind") == "handed_product_refused", refusal
    assert len(refusal.get("problems") or []) == 8, refusal
    assert refusal.get("next_step"), refusal


def test_d_a_framework_rejection_leaves_a_refusal_row_even_if_the_write_blew(
    store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """d（写回炸了那一档）：拒因仍然写进 history —— 改前它跟着那一笔写回一起丢了。"""
    reg, pid = _plan(store)
    _form_gate_passed(store)
    _break_the_plan_write(monkeypatch)
    res = reg.call("attack.step", plan_id=pid, product=_product(_steps_all_assumptions()))

    rows = [h for h in _history(store, pid)
            if h.get("audit") == AT.REFUSAL_AUDIT_MARKER]
    assert len(rows) == 1, _history(store, pid)
    refusal = dict(rows[0].get("refusal") or {})
    assert refusal.get("kind") == AT.FRAMEWORK_ERROR_KIND, refusal
    assert "unhashable type" in str(refusal.get("framework_error") or "")
    assert refusal.get("manuscript_path") or refusal.get("report_path"), refusal
    # 回执也要说"留痕写进去了"（写不进去时它会说没写进去，不静默）
    assert res.meta["refusal_record"]["recorded"] is True
    assert "审计痕迹：这一轮的拒因已经写进" in res.error


def test_the_whole_file_never_calls_a_model(store: Store,
                                            monkeypatch: pytest.MonkeyPatch) -> None:
    """夹具纪律：上面这些场景一个模型调用都不许发生（否则真机跑一次要花钱）。"""
    for product in (_product(), _product(_steps_all_assumptions())):
        reg, pid = _plan(store)
        _form_gate_passed(store)
        _break_the_plan_write(monkeypatch)
        reg.call("attack.step", plan_id=pid, product=product)
        monkeypatch.undo()
    assert store.rows("usage_ledger") == [], store.rows("usage_ledger")


# ------------------------------------------------------------------ e 反真空


def test_e1_stub_the_split_back_to_one_bucket_and_a_turns_red(
    store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """e（对 a）：把分档打桩回"一律当校验失败" ⇒ 同一支 TypeError 又变回 `validation_error`。"""
    reg, pid = _plan(store)
    _form_gate_passed(store)
    _break_the_plan_write(monkeypatch)
    product = _product(_steps_all_assumptions())
    good = reg.call("attack.step", plan_id=pid, product=product)
    assert _a_holds(good), good.error  # 先绿

    monkeypatch.setattr(AT, "FRAMEWORK_FAULTS", ())
    bad = reg.call("attack.step", plan_id=pid, product=product)
    assert not _a_holds(bad)
    assert bad.meta.get("kind") == "validation_error", bad.error
    assert "校验失败" in bad.error


def test_e2_stub_the_disk_probe_out_and_c_turns_red(
    store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """e（对 c）：把查盘打桩掉 ⇒ 回执不许再说"已落库"，只能说"没查成"。"""
    reg, pid = _plan(store)
    _form_gate_passed(store)
    _break_the_plan_write(monkeypatch)
    product = _product(_steps_all_assumptions())
    good = reg.call("attack.step", plan_id=pid, product=product)
    assert "已落库" in good.error  # 先绿

    monkeypatch.setattr(RF, "disk_state",
                        lambda *_a, **_k: {"checked": False, "why": "夹具：不查盘",
                                           "plans": None, "rounds": None,
                                           "history": None, "reports": {}})
    bad = reg.call("attack.step", plan_id=pid, product=product)
    landing = dict(bad.meta.get("landing") or {})
    assert landing.get("checked") is False, landing
    assert landing.get("landed") is None, landing
    assert "已落库" not in bad.error
    assert "没查成" in bad.error


def test_e3_stub_the_validator_reading_out_and_b_turns_red(
    store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """e（对 b）：把校验器的逐条读数打桩掉 ⇒ 异常路径上一句具体问题都不剩。"""
    reg, pid = _plan(store)
    _break_the_plan_write(monkeypatch)
    good = reg.call("attack.step", plan_id=pid, product=_product())
    assert len(_bullets(good.error)) == 8  # 先绿

    monkeypatch.setattr(AT, "product_problems", lambda _p: [])
    bad = reg.call("attack.step", plan_id=pid, product=_product())
    assert _bullets(bad.error) == []
    assert "校验器对你这一份的逐条读数" in bad.error

# -*- coding: utf-8 -*-
"""F 的闭环四跳（`draft/44` 的 P2-3 / P2-4 / P3-5 / P3-6 / P4-7 / P4-8）—— 一处一组判据。

## 每一组治的都是"看起来在工作、其实原地打转"

| 组 | 改前的真机形态 |
|---|---|
| P2-3 证据正文 | 提示词里只有 `已跑实验：['000001']` ⇒ 模型拿不到"那条证据说了什么" |
| P2-4 history 回灌 | 提示词里一个字都没有"上一轮" ⇒ mp3 `000001` 的 r1/r3/r4 **逐字重复** |
| P3-5 带原因重问 | 一次不成形 = 永久封存（`RoundError` ⇒ `blocked` + `in_flight=True`） |
| P3-6 产物出口 | `product_detail` 只写不读；`proof` 不进 `statements`、盘上无 `reports/attack-*.md` |
| P4-7 子目标优先 | `counterexample_request` 之后父目标仍 `in_progress` ⇒ 子目标永远 `todo` |
| P4-8 换招与判据 | `tried_strategies` 只读不写；手写 E 子目标必然"缺 `script_path`" |

判据一律离线（假模型返回写死的 JSON），每条都配一条负控：把修好的那一处按改前的
形态注回去 ⇒ 同一组断言必须红。负控用的是 `monkeypatch`，不动生产代码。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentflow import attackround as AR
from agentflow import llmseam
from agentflow.agent_f import AgentF
from agentflow.store import Store
from agentflow.tools import attack_tools as AT

TS = "2026-10-19T00:00:00+08:00"

#: E 写脚本那一跳要的合格脚本（`author_script` 的判据：必须打印 `REPRO_RESULT`）。
SCRIPT = (
    "import json\n"
    "print('REPRO_RESULT: ' + json.dumps({\n"
    "    'result': 'supports',\n"
    "    'observations': {'n': 18},\n"
    "    'counterexample': None,\n"
    "    'negation_kind': 'not_proved',\n"
    "    'bound': {'n': 18}}))\n"
)


class FakeLLM:
    """最小模型缝（`judge.judge_json` 的调用约定）。每次调用都记下提示词。"""

    def __init__(self, *replies: str) -> None:
        self.replies = list(replies)
        self.prompts: list[str] = []
        self.calls = 0

    def complete(self, prompt: str) -> str:
        self.calls += 1
        self.prompts.append(prompt)
        if not self.replies:
            raise AssertionError("模型被调用的次数比剧本多")
        return self.replies.pop(0)


def _f(store: Store, llm=None, **cfg) -> AgentF:
    return AgentF(store, config={"workspace_root": store.root, **cfg}, llm=llm)


def _round(**fields) -> str:
    base = {"strategy": "反证", "why_strategy": "反设存在反例"}
    base.update(fields)
    return json.dumps(base, ensure_ascii=False)


def _proof_round(text: str = "反设存在反例，取最小者", strategy: str = "反证") -> str:
    """一份成形的 `proof`：只有显式前提（不引 id ⇒ 不会被 R-03 拒收）。"""
    return _round(product="proof", strategy=strategy,
                  steps=[{"text": text, "assumption": True}])


def _new_plan(f: AgentF, *, owner: str = "F", testable: str = "存在反例或有限界",
              evidence_ids=(), key: str = "PK-LOOP") -> str:
    return f.create_plan("难题：判定这个族的存在性", key, subgoals=[
        {"sid": "s1", "text": "判定这条难题", "owner": owner, "testable": testable,
         "evidence_ids": list(evidence_ids)},
    ])["plan_id"]


def _experiment(store: Store, *, eid: str = "000001", claim: str, result: str = "supports") -> None:
    """写一行形状合法的实验（证据正文那一组要一条真的台账行）。"""
    with store.tx("experiments", actor="test", note="loop probe") as tx:
        tx.upsert("experiments", {
            "experiment_id": eid, "claim": claim, "claim_key": "K#s1",
            "script_path": "code/x.py", "method": "numeric", "params": {}, "timeout": 60,
            "exit_code": 0, "result": result, "evidence_kind": "cross_check",
            "negation_kind": "not_proved", "observations": {"n": 18},
            "created_at": TS, "created_by": "test"})


# ============================================================ P2-3：证据正文进提示词

def test_the_evidence_body_is_in_the_prompt_not_just_the_id(store: Store):
    """判据：提示词里要出现那条证据的**正文**（`claim` / `result`），不只是 id。"""
    _experiment(store, claim="n<=18 的穷举没有反例", result="supports")
    llm = FakeLLM(_proof_round())
    f = _f(store, llm=llm)
    f.step(_new_plan(f, evidence_ids=["exp:000001"]))

    prompt = llm.prompts[0]
    assert "000001" in prompt, prompt
    assert "n<=18 的穷举没有反例" in prompt, "提示词里只有 id，没有证据正文"
    assert "result=supports" in prompt, prompt
    # 上限写在提示词里（"超出即截断"必须是模型读得到的一句话，不是内部约定）
    assert "字，超出即截断" in prompt, prompt


def test_a_long_evidence_body_is_truncated_and_says_so(store: Store):
    """判据（截断纪律）：正文超上限时截断，并在提示词里写明原长 —— 不许静默截断。"""
    long_claim = "很长的结论" * 60
    _experiment(store, claim=long_claim)
    llm = FakeLLM(_proof_round())
    f = _f(store, llm=llm)
    f.step(_new_plan(f, evidence_ids=["exp:000001"]))
    prompt = llm.prompts[0]
    assert "已截断，原长" in prompt, prompt
    assert long_claim not in prompt, "整段正文都进了提示词 ⇒ 那条上限没生效"


def test_an_evidence_id_that_is_not_in_the_ledger_is_said_out_loud(store: Store):
    """负控（三态）：证据 id 不在册 ⇒ 提示词里必须说"不在册"，不是静默丢掉这条。"""
    llm = FakeLLM(_proof_round())
    f = _f(store, llm=llm)
    f.step(_new_plan(f, evidence_ids=["exp:999999"]))
    assert "不在册" in llm.prompts[0], llm.prompts[0]


def test_without_evidence_the_prompt_says_there_is_none(store: Store):
    """反真空：一条证据都没有时，提示词要**明说**没有（而不是留一块空白）。"""
    llm = FakeLLM(_proof_round())
    f = _f(store, llm=llm)
    f.step(_new_plan(f))
    assert "还没有任何证据正文可读" in llm.prompts[0], llm.prompts[0]


# ============================================================ P2-4：history 回灌 + 换招

def _two_same_strategy_rounds(store: Store) -> FakeLLM:
    llm = FakeLLM(_proof_round("第一轮：反设存在反例"),
                  _proof_round("第二轮：再反设一次"))
    f = _f(store, llm=llm)
    pid = _new_plan(f)
    f.step(pid)
    f.step(pid)
    return llm


def test_the_previous_round_is_replayed_into_the_next_prompt(store: Store):
    """判据：第 2 轮的提示词里要看得到第 1 轮发生了什么（outcome / 产物 / 结论摘要）。"""
    llm = _two_same_strategy_rounds(store)
    second = llm.prompts[1]
    assert "此前几轮**已经发生过**的事" in second, second
    assert "第 1 轮" in second and "outcome=progress" in second, second
    assert "第一轮：反设存在反例" in second, "上一轮的结论摘要没进提示词"


def test_the_same_strategy_twice_asks_for_a_different_one(store: Store):
    """判据：同一招连续出现 ⇒ 显式要求换一招（并且把还没试过的招列出来）。"""
    llm = FakeLLM(_proof_round("r1", strategy="反证"),
                  _proof_round("r2", strategy="反证"),
                  _proof_round("r3", strategy="归约"))
    f = _f(store, llm=llm)
    pid = _new_plan(f)
    f.step(pid)
    f.step(pid)
    f.step(pid)

    # 负控（反真空）：第 2 轮的提示词里还不该有这句 —— 否则它是写死的话术
    assert "连续" not in llm.prompts[1] or "换一招" not in llm.prompts[1], llm.prompts[1]
    third = llm.prompts[2]
    assert "连续 2 轮" in third and "换一招" in third, third
    assert "归约" in third.split("换一招")[1][:200], third


# ============================================================ P3-5：带原因重问

def test_a_malformed_round_is_asked_again_with_its_own_reason(store: Store):
    """判据：第一次不成形 ⇒ 带着它自己的原因重问；第二次成形 ⇒ 这一轮**真推进**。"""
    bad = _round(product="reduction", new_subgoals=[])          # 归约必须给 1–3 条
    good = _round(product="proof", steps=[{"text": "这才是论证", "assumption": True}])
    llm = FakeLLM(bad, good)
    f = _f(store, llm=llm)
    pid = _new_plan(f)
    out = f.step(pid)

    assert out["outcome"] == "progress", out
    assert len(llm.prompts) == 2, llm.prompts
    assert "不成形" in llm.prompts[1] and "1–3" in llm.prompts[1], llm.prompts[1]
    assert "为了不要重复劳动" not in llm.prompts[0], llm.prompts[0]
    assert store.rows("attack_plans")[0]["history"][-1]["product"] == "proof"


def test_the_retry_budget_is_read_from_the_plan_not_hardcoded(store: Store):
    """判据（口径）：重问几次由计划预算里的 `max_persist_attempts` 决定，不是写死的。"""
    bad = _round(product="reduction", new_subgoals=[])
    llm = FakeLLM(bad, bad, bad)
    f = _f(store, llm=llm)
    pid = f.create_plan("难题", "PK-RETRY", subgoals=[
        {"sid": "s1", "text": "判定", "owner": "F", "testable": "有限界"}],
        budget={"max_rounds": 6, "max_parallel_subgoals": 2,
                "max_persist_attempts": 3, "max_depth": 1})["plan_id"]
    out = f.step(pid)
    assert out["outcome"] == "no_change", out
    assert len(llm.prompts) == 3, llm.prompts           # 三次 = 预算里的 3
    assert "3 次" in out["reason"], out["reason"]
    # 负控：默认预算（2）下就不会有第三次 —— 这个数真的来自计划
    llm2 = FakeLLM(bad, bad)
    f2 = _f(store, llm=llm2)
    f2.step(_new_plan(f2, key="PK-RETRY-2"))
    assert len(llm2.prompts) == 2, llm2.prompts


# ============================================================ P3-6：proof 的出口

def test_a_proof_round_lands_a_statement_and_a_report_line(store: Store):
    """判据：`proof` 之后，`statements` 有一行、`reports/attack-<plan_id>.md` 有一行。"""
    llm = FakeLLM(_proof_round("这是第一步"))
    f = _f(store, llm=llm)
    pid = _new_plan(f)
    out = f.step(pid)

    stmts = store.rows("statements")
    assert len(stmts) == 1, stmts
    row = stmts[0]
    assert row["origin"] == "own_result" and row["kind"] == "lemma", row
    assert "这是第一步" in row["proof_text"], row
    # 等级**不许**自报更高：V 没签过 ⇒ 只能 heuristic，而且五元位是空的
    assert row["evidence_kind"] == "heuristic", row
    assert not dict(row.get("bits") or {}), row
    assert row["quote_reason"], row

    report = Path(store.root) / "reports" / f"attack-{pid}.md"
    assert report.is_file(), f"盘上没有 {report}"
    text = report.read_text(encoding="utf-8")
    assert "第 1 轮" in text and "`proof`" in text and "依据" in text and "下一步" in text, text
    assert str(row["stmt_id"]) in text, text

    # 产物落点进 `detail`（M 读 `attack.status` 就看得见）与返回值
    rec = store.rows("attack_plans")[0]["history"][-1]
    assert rec["statement_id"] == row["stmt_id"] and rec["report_path"] == f"reports/attack-{pid}.md", rec
    assert out["statement_id"] == row["stmt_id"] and out["report_path"] in out["reason"], out


def test_the_proof_outlet_is_what_writes_the_statement(store: Store, monkeypatch):
    """负控：把出口按改前的形态注回去（不写 statements）⇒ 同一组断言必须红。"""
    def gone(self, product, sg, *, plan):
        return {"ok": False, "statement_id": "", "reused": False,
                "why": "（负控：出口被摘掉）", "cites": []}

    monkeypatch.setattr(AgentF, "_proof_outlet", gone)
    llm = FakeLLM(_proof_round())
    f = _f(store, llm=llm)
    f.step(_new_plan(f))
    assert store.rows("statements") == [], "出口摘掉之后仍然写进了 statements ⇒ 这条负控是空转"
    rec = store.rows("attack_plans")[0]["history"][-1]
    assert "没能**落进 statements" in rec["detail"] or "没能" in rec["detail"], rec["detail"]


def test_the_same_proof_twice_is_not_registered_twice(store: Store):
    """反真空（幂等）：逐字相同的论证不许登记第二行（否则 `statement_rows` 虚高）。"""
    llm = FakeLLM(_proof_round("同一步"), _proof_round("同一步"))
    f = _f(store, llm=llm)
    pid = _new_plan(f)
    f.step(pid)
    f.step(pid)
    assert len(store.rows("statements")) == 1, store.rows("statements")


# ============================================================ P4-7：子目标优先

def test_a_dispatched_subgoal_is_picked_before_its_parent(store: Store):
    """判据：`counterexample_request` 造出 E 子目标之后，下一轮选的是**子目标**。"""
    llm = FakeLLM(_round(product="counterexample_request",
                         script_spec={"criterion": "k-圈数 >= 2", "params": "m=3, k=6",
                                      "expected_bound": "n_max=18"},
                         why_it_decides="这条判据直接把命题判死或判活"))
    f = _f(store, llm=llm)
    pid = _new_plan(f)
    assert f.step(pid)["sid"] == "s1"
    row = store.rows("attack_plans")[0]
    parent = next(s for s in row["subgoals"] if s["sid"] == "s1")
    assert parent["waiting_on"] == ["s2"], parent          # 显式读数，不是靠状态暗示
    # 下一轮：选的是刚派出去的那条（E 那边缺缝，所以它会 no_change —— 但选中的是 s2）
    assert f.step(pid)["sid"] == "s2"


def test_without_waiting_on_the_parent_would_win_again(store: Store):
    """负控：把 `waiting_on` 摘掉 ⇒ 排序回到改前的形态（父目标仍压住子目标）。"""
    subs = [
        {"sid": "s1", "text": "父", "owner": "F", "status": "in_progress",
         "waiting_on": ["s2"]},
        {"sid": "s2", "text": "子", "owner": "E", "status": "todo"},
    ]
    assert AT.pick_next_subgoal(subs)["subgoal"]["sid"] == "s2"
    assert AT.pick_next_subgoal([{k: v for k, v in s.items() if k != "waiting_on"}
                                 for s in subs])["subgoal"]["sid"] == "s1"


def test_a_parent_waiting_on_finished_children_comes_back(store: Store):
    """反负控（不许死锁）：等的那条做完了 ⇒ 父目标恢复次序首位。"""
    subs = [
        {"sid": "s1", "text": "父", "owner": "F", "status": "in_progress",
         "waiting_on": ["s2"]},
        {"sid": "s2", "text": "子", "owner": "E", "status": "supported_not_proved"},
    ]
    assert AT.pick_next_subgoal(subs)["subgoal"]["sid"] == "s1"


def test_everyone_waiting_is_not_read_as_nothing_to_do(store: Store):
    """反负控：全部都在等 ⇒ 仍然选一个（不许返回"没有可推进的子目标"）。"""
    subs = [
        {"sid": "s1", "text": "甲", "owner": "F", "status": "in_progress", "waiting_on": ["s2"]},
        {"sid": "s2", "text": "乙", "owner": "F", "status": "in_progress", "waiting_on": ["s1"]},
    ]
    got = AT.pick_next_subgoal(subs)
    assert got["picked"] is True and got["subgoal"]["sid"] in {"s1", "s2"}, got


# ============================================================ P4-8：换招记录与判据推演

def test_the_strategy_that_was_used_is_written_back(store: Store):
    """判据：这一轮用了哪一招要写回子目标（`tried_strategies` 不再只读不写）。"""
    llm = FakeLLM(_proof_round("r1", strategy="反证"))
    f = _f(store, llm=llm)
    pid = _new_plan(f)
    f.step(pid)
    sg = store.rows("attack_plans")[0]["subgoals"][0]
    assert sg["tried_strategies"] == ["反证"], sg
    # 负控（反真空）：第一轮的提示词里它还是"（无）" —— 说明这是写回，不是常量
    assert "已试过的招：（无）" in llm.prompts[0], llm.prompts[0]
    # 下一轮读得到（`pre_spend_gate` 的 `strategies_tried` 就是读它的）
    gate = AR.pre_spend_gate(goal="g", testable="t", tried_strategies=sg["tried_strategies"])
    assert gate["checks"]["strategies_tried"]["tried"] == ["反证"], gate["checks"]


def test_testable_is_turned_into_a_script_spec_by_f_then_e_runs_it(store: Store):
    """判据（P4-8 的第二半）：手写 E 子目标只带 `testable` ⇒ F 推判据、E 写脚本、跑出实验。"""
    spec_reply = _round(product="counterexample_request",
                        script_spec={"criterion": "k-圈数 >= 2", "params": "m=3, k=6, n<=18",
                                     "expected_bound": "n_max=18"},
                        why_it_decides="枚举小情形就能判定")
    llmseam.set_role_seam("E", FakeLLM(json.dumps({"source": SCRIPT, "why": "枚举"})))
    try:
        llm = FakeLLM(spec_reply)          # F 只该被问一次（把 testable 变成判据）
        f = _f(store, llm=llm)
        pid = f.create_plan("难题", "PK-SPEC", subgoals=[
            {"sid": "s1", "text": "按可检验形式跑实验", "owner": "E",
             "testable": "n<=18 时 k-圈数 >= 2"}])["plan_id"]
        out = f.step(pid)
    finally:
        llmseam.set_role_seam("E", None)

    assert out["outcome"] == "progress", out
    sg = store.rows("attack_plans")[0]["subgoals"][0]
    assert sg["script_spec"]["criterion"] == "k-圈数 >= 2", sg
    assert sg["script_path"] == "code/attack_s1.py", sg
    assert store.rows("experiments"), "判据有了、脚本有了，却没跑出实验行"


def test_without_a_seam_a_testable_only_subgoal_still_says_what_is_missing(store: Store):
    """负控（不许凭空造判据）：F 没有缝 ⇒ 仍然"缺 script_path"，并说清缺的是哪三件。"""
    f = _f(store)                          # llm=None
    pid = f.create_plan("难题", "PK-SPEC2", subgoals=[
        {"sid": "s1", "text": "按可检验形式跑实验", "owner": "E",
         "testable": "n<=18 时 k-圈数 >= 2"}])["plan_id"]
    out = f.step(pid)
    assert out["outcome"] == "no_change", out
    assert "script_path" in out["reason"], out
    assert "推理缝" in out["reason"], out["reason"]
    sg = store.rows("attack_plans")[0]["subgoals"][0]
    assert not sg.get("script_spec"), sg
    assert store.rows("experiments") == [] and list((Path(store.root) / "code").glob("*.py")) == []

# -*- coding: utf-8 -*-
"""F 自己推理那一支（`draft/39` §6.31 的 D42）：插座接上之后，`step` 真的推一轮。

## 背景（真机读数）

`agent_f/core.py` 的 `llm` 形参从 `draft/30` §T0-8 起就在，注释逐字写着
"默认 None = 不接线 ⇒ 本角色一个 LLM 调用都不发"，但 `_deploy` 里那一条
`owner in UNWIRED_OWNERS`（C/D/F）无论有没有缝都落 `dead_end(缺工具)` ——
于是 T2 第 11 趟（`projects/p6m-research-from-zero`）`F.step` 回的是
`no_change`，M 据此写下"F 的自动推理未接线，攻坚这条路走不通"。
这一组钉的就是"接上缝之后它真的推一轮"，以及四种受控产物各自的落法。

## 判据的形状

离线（假模型返回写死的 JSON）——不由真模型决定判据；
每一档都有一条正控（接线的 F 交得出那一档产物）与一条负控
（没接线时仍是 `dead_end`；闸门说不许花钱时一次模型调用都不发）。
"""
from __future__ import annotations

import json

from agentflow import attackround as AR
from agentflow.agent_f import AgentF
from agentflow.store import Store


class FakeLLM:
    """最小模型缝：`complete(prompt) -> str`（`judge.judge_json` 的调用约定）。"""

    def __init__(self, *replies: str) -> None:
        self.replies = list(replies)
        self.prompts: list[str] = []

    def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if not self.replies:
            raise AssertionError("模型被调用的次数比剧本多")
        return self.replies.pop(0)


class BrokenLLM:
    """每次调用都炸（走 `judge_failed:<类名>` 那一档）。"""

    def __init__(self) -> None:
        self.calls = 0

    def complete(self, prompt: str) -> str:
        self.calls += 1
        raise RuntimeError("网关炸了")


def _f(store: Store, llm=None, *, budget_reading=None, **cfg) -> AgentF:
    return AgentF(store, config={"workspace_root": store.root, **cfg}, llm=llm,
                  budget_reading=budget_reading)


def _new_plan(f: AgentF, *, owner: str = "F", testable: str = "存在反例或有限界",
              key: str = "PK-INF") -> str:
    return f.create_plan("难题：证明或否证某个族的存在性", key, subgoals=[
        {"sid": "s1", "text": "判定这条难题", "owner": owner, "testable": testable},
    ])["plan_id"]


def _round(**fields) -> str:
    """造一份成形产物的 JSON 文本（缺省补上公共字段）。"""
    base = {"strategy": "小情形搜索找模式", "why_strategy": "先看小情形有没有模式"}
    base.update(fields)
    return json.dumps(base, ensure_ascii=False)


# ============================================================ 正控：四档产物都能交出来


def test_a_wired_f_really_advances_one_round(store: Store):
    """正控（D42 的核心）：接上缝的 F 交 `reduction` ⇒ 子目标真被归约、history 长一条。"""
    llm = FakeLLM(_round(product="reduction", reason="把存在性归约成两个更小的判定",
                         new_subgoals=[{"goal": "判定小情形 n<=12",
                                        "testable": "枚举 n<=12 全部候选"},
                                       {"goal": "判定构造族是否无限",
                                        "testable": "给出参数族与它的 girth 公式"}]))
    f = _f(store, llm=llm)
    pid = _new_plan(f)
    out = f.step(pid)

    assert out["action"] == "reduction", out
    assert out["outcome"] == "progress", out
    row = store.rows("attack_plans")[0]
    sids = [s["sid"] for s in row["subgoals"]]
    assert sids == ["s1", "s2", "s3"], sids
    assert row["subgoals"][1]["owner"] == "F" and row["subgoals"][1]["status"] == "todo"
    rec = row["history"][-1]
    assert rec["product"] == "reduction" and rec["strategy"] in AR.STRATEGIES, rec
    # 整份产物进 history（D42）：归约出来的子目标不许只活在模型那一句回复里
    assert [g["goal"] for g in rec["product_detail"]["new_subgoals"]], rec
    # 提示词里必须带着受控值（四档 + 九招 + #5 的禁用词 + 这一条子目标的可检验形式）
    assert llm.prompts and "reduction" in llm.prompts[0] and "dead_end" in llm.prompts[0]
    for word in AR.F_BANNED_MARKERS:
        assert word in llm.prompts[0], f"提示词没把禁用词 {word} 告诉模型"


# ============================================================ CS-6：`dead_end_reason` 只属于 dead_end


def test_a_reduction_round_does_not_write_a_dead_end_reason(store: Store):
    """`dead_end_reason` 只属于 `dead_end` 那一档（CS-6，2026-10-11 修）。

    病因（`draft/108` §四 CS-6）：`attackround.parse_round` 给 `reduction` 与 `dead_end`
    两档都写了 `product["reason"]`（`:112` 与 `:149`），而 `step` 从前是
    "见 reason 就写 `dead_end_reason`" —— 于是归约轮的"为什么这样归约"落进了一个名叫
    "死路理由"的字段。现算读数（两个根、100 个工作区）：22 条 reduction 行全部带
    `dead_end_reason`，且那 22 条全部落在受控 7 值之外。

    归约的理由一个字都没丢：整份产物照旧进 `product_detail`（这一条同时钉这件事）。
    """
    llm = FakeLLM(_round(product="reduction", reason="把存在性归约成两个更小的判定",
                         new_subgoals=[{"goal": "判定小情形 n<=12",
                                        "testable": "枚举 n<=12 全部候选"},
                                       {"goal": "判定构造族是否无限",
                                        "testable": "给出参数族与它的 girth 公式"}]))
    f = _f(store, llm=llm)
    pid = _new_plan(f)
    f.step(pid)

    rec = store.rows("attack_plans")[0]["history"][-1]
    assert rec["product"] == "reduction", rec
    assert "dead_end_reason" not in rec, (
        "归约轮写了一个名叫 `dead_end_reason` 的字段 ⇒ 读的人会把归约当成死路（CS-6）"
        f"：{rec.get('dead_end_reason')!r}")
    assert rec["product_detail"].get("reason") == "把存在性归约成两个更小的判定", rec["product_detail"]


def test_a_dead_end_round_still_writes_the_controlled_reason(store: Store):
    """另一半（防止把上面那条修成"谁都不写"）：`dead_end` 照旧写，且在受控词表里。"""
    llm = FakeLLM(_round(product="dead_end", reason="缺工具",
                         evidence="这一轮要走的那条路没有可用的检查器",
                         best_partial=[{"what": "已把命题改小到有限枚举", "ids": [],
                                        "why_partial": "缺工具"}]))
    f = _f(store, llm=llm)
    pid = _new_plan(f)
    f.step(pid)

    rec = store.rows("attack_plans")[0]["history"][-1]
    assert rec["product"] == "dead_end", rec
    assert rec.get("dead_end_reason") in AR.DEAD_END_REASONS, rec
    assert rec["product_detail"].get("reason") == "缺工具", rec["product_detail"]


def test_a_proof_round_is_progress_but_never_closes_the_subgoal(store: Store):
    """`proof`：论证进 history 的 `product_detail`；子目标不因此关闭（FC-22）。

    步的形状是 `attackround._clean_step` 定的 `{text, cites, assumption}` ——
    提示词里也必须逐字给这三个键（写错键名 ⇒ 模型照提示词写、判据照样拒，
    那正是"提示词与判据分家"）。

    R-03 之后这一条要先真的有一条文献可引：引用先过存在性判据（伪造引用当场拒收），
    所以夹具里那条 `lit:` 必须落进 `literature` 表 —— 这一条因此同时钉住
    "引了在册的 id ⇒ 照常进 progress"。
    """
    from conftest import add_literature

    add_literature(store, "0004", title="边-围长正则图的下界")
    llm = FakeLLM(_round(product="proof", steps=[
        {"text": "对于 n=14 的具名图，每条边落在 4 个 k-圈里", "cites": ["lit:0004"]},
    ]))
    f = _f(store, llm=llm)
    pid = _new_plan(f)
    out = f.step(pid)

    row = store.rows("attack_plans")[0]
    assert out["outcome"] == "progress", out
    assert row["subgoals"][0]["status"] != "closed", "FC-22：没有 proof 级实验就不许关闭"
    rec = row["history"][-1]
    assert rec["product"] == "proof"
    assert len(rec["product_detail"]["steps"]) == 1, rec
    assert "assumption" in llm.prompts[0], "提示词没给步的真实形状（text/cites/assumption）"


def test_r03_a_proof_citing_a_nonexistent_id_is_refused_not_counted_as_progress(store: Store):
    """R-03：引了台账里不存在的 id ⇒ 这一轮拒收（既不是进展，也不是"做了但没结果"）。

    真机读数（`p8f` 计划 0002）：`proof` 的一步 `cites` 写着 `lit:Frey1986/…`，
    而那个工作区的 literature id 是 `0000-0007` —— 一个不存在的 id，那一轮照样记 `progress`。
    """
    llm = FakeLLM(_round(product="proof", steps=[
        {"text": "由 lit:Frey1986/annals-1986 得到结论",
         "cites": ["lit:Frey1986/annals-1986"]},
    ]))
    f = _f(store, llm=llm)
    out = f.step(_new_plan(f))

    assert out["outcome"] == "no_change" and out["action"] == "no_change", out
    assert "不存在的 id" in out["reason"], out
    row = store.rows("attack_plans")[0]
    rec = row["history"][-1]
    assert rec.get("product_detail") is None, "拒收的一轮不许落产物（落了就等于认了它的引文）"
    assert row["subgoals"][0]["attempts"] == 0, "拒收与「不成形」同一档：不记成一次尝试"


def test_r03_the_verifications_prefix_is_not_judged_here_and_not_refused(store: Store):
    """三态：`v:` 的账本不在 `schema.TABLES` 里（V 的是文件账本 `verifications/*.jsonl`）
    ⇒ 本层不判它，也不因此拒收 —— "这一层查不了"与"这个 id 是假的"是两件事。"""
    llm = FakeLLM(_round(product="proof", steps=[
        {"text": "这一步已经过 V 核验", "cites": ["v:v-0001"]},
    ]))
    f = _f(store, llm=llm)
    out = f.step(_new_plan(f))
    assert out["outcome"] == "progress", out


def test_a_counterexample_request_becomes_an_e_owned_subgoal(store: Store):
    """`counterexample_request`：判据变成一条 owner=E 的新子目标（下一轮派给它跑）。"""
    llm = FakeLLM(_round(product="counterexample_request",
                         script_spec={"criterion": "每条边的 k-圈数 >= 2",
                                      "params": "m=3, k=6, n<=18",
                                      "expected_bound": "n_max=18"},
                         why_it_decides="这条判据直接把 R(3,6) 判死或判活"))
    f = _f(store, llm=llm)
    pid = _new_plan(f)
    out = f.step(pid)

    row = store.rows("attack_plans")[0]
    assert out["action"] == "counterexample_request", out
    owners = {s["sid"]: s["owner"] for s in row["subgoals"]}
    assert owners == {"s1": "F", "s2": "E"}, owners
    assert "每条边的 k-圈数 >= 2" in row["subgoals"][1]["text"], row["subgoals"][1]


def test_s10_the_counterexample_request_carries_its_spec_into_the_e_subgoal(store: Store):
    """S-10：F 造的 E 子目标必须带着判据，缺脚本时把判据念出来。

    旧形态：`counterexample_request` 造出的 E 子目标只有 `text`/`testable`，没有 `script_path`
    ⇒ 下一轮 `_deploy_e` 只回一句"没有给 script_path ⇒ 未推进"，而判据（criterion/params/
    expected_bound）留在上一轮的 `product_detail` 里没人念 ⇒ 这条子目标原地打转直到计划
    `stalled`（"造出的子目标必然停住"）。
    现在：判据随子目标走（`script_spec`），缺脚本时那句拒绝逐字带上判据，谁都能照着写脚本。
    """
    llm = FakeLLM(_round(product="counterexample_request",
                         script_spec={"criterion": "每条边的 k-圈数 >= 2",
                                      "params": "m=3, k=6, n<=18",
                                      "expected_bound": "n_max=18"},
                         why_it_decides="这条判据直接把 R(3,6) 判死或判活"))
    f = _f(store, llm=llm)
    f.step(_new_plan(f))

    plan = store.rows("attack_plans")[0]
    sg = next(s for s in plan["subgoals"] if s["sid"] == "s2")
    assert sg["script_spec"]["criterion"] == "每条边的 k-圈数 >= 2", sg
    assert sg["script_spec"]["expected_bound"] == "n_max=18", sg

    # 派给 E 那一条（另起一张计划：`pick_next_subgoal` 会把 `in_progress` 的 s1 排在前面，
    # 这里要单独测 `_deploy_e` 的拒绝文案）⇒ 拒绝里必须逐字念出判据
    pid2 = f.create_plan("难题二", "PK-S10", subgoals=[
        {"sid": "s1", "text": "按判据跑实验", "owner": "E", "testable": "n<=18",
         "script_spec": {"criterion": "每条边的 k-圈数 >= 2", "params": "m=3, k=6, n<=18",
                         "expected_bound": "n_max=18"}},
    ])["plan_id"]
    out = f.step(pid2)
    assert out["outcome"] == "no_change", out
    assert "script_path" in out["reason"], out
    assert "每条边的 k-圈数 >= 2" in out["reason"], out
    assert "n_max=18" in out["reason"], out
    # 反负控：没有判据的那种 E 子目标 ⇒ 文案里不该多出判据那半句（判据是读数，不是模板）
    pid3 = f.create_plan("难题三", "PK-S10B", subgoals=[
        {"sid": "s1", "text": "做个实验", "owner": "E"}])["plan_id"]
    plain = f.step(pid3)
    assert "script_path" in plain["reason"] and "criterion=" not in plain["reason"], plain


def test_a_dead_end_round_is_blocked_with_a_controlled_reason(store: Store):
    """`dead_end`：如实 `blocked`（受控理由 + `in_flight`），不许自动重试同一条。"""
    llm = FakeLLM(_round(product="dead_end", reason="方法不适用",
                         evidence="这条子目标里没有可判定的有限形式",
                         best_partial=[{"what": "已把难题缩到 k=6 这一支", "ids": [],
                                        "why_partial": "不是进展，是范围"}],
                         why_strategy="九招里没有一招能落在没有有限形式的命题上"))
    f = _f(store, llm=llm)
    pid = _new_plan(f)
    out = f.step(pid)

    row = store.rows("attack_plans")[0]
    assert out["outcome"] == "no_change", out
    assert row["subgoals"][0]["status"] == "blocked"
    assert row["subgoals"][0]["blocked_reason"], "blocked 必须说清被什么卡住"
    assert row["subgoals"][0].get("in_flight") is True
    rec = row["history"][-1]
    assert rec["product"] == "dead_end" and rec["dead_end_reason"] == "方法不适用", rec
    assert rec["best_partial"], rec


# ============================================================ 负控：三种"没推成"分得开


def test_an_unwired_f_still_says_it_is_not_wired(store: Store):
    """负控（D42 的反面）：没接缝时仍是 `dead_end(缺工具)`，不许假装推了一轮。"""
    f = _f(store)                      # llm=None
    pid = _new_plan(f)
    f.step(pid)

    rec = store.rows("attack_plans")[0]["history"][-1]
    assert rec["product"] == "dead_end", rec
    assert rec["dead_end_reason"] == "缺工具", rec
    assert "尚未接线自动推理" in rec["detail"], rec["detail"]


def test_a_broken_seam_is_recorded_as_not_checked_not_as_a_dead_end(store: Store):
    """三态：缝炸了 ⇒ `no_change` + `judge_failed:…`，不落产物（不是"这条路死了"）。"""
    llm = BrokenLLM()
    f = _f(store, llm=llm)
    pid = _new_plan(f)
    out = f.step(pid)

    rec = store.rows("attack_plans")[0]["history"][-1]
    assert llm.calls == 1, "炸了的那一次该只调一次"
    assert out["outcome"] == "no_change", out
    assert rec.get("product_detail") is None, "没查成不许落产物（那会把'没查'写成'查了'）"
    assert "judge_failed:RuntimeError" in rec["detail"], rec["detail"]
    assert store.rows("attack_plans")[0]["subgoals"][0]["blocked_reason"].startswith("LLM 判定没查成")


def test_a_malformed_round_comes_back_with_the_original_reason(store: Store):
    """不成形 ⇒ 原话带回去（而不是只说"没进展"）：调用方要能据它改提示词。

    2026-10-19（`draft/44` P3-5）：原话要带进下一次提问，不是只写进 history。
    改前 `RoundError` 一次就把子目标标成 `blocked` + `in_flight=True`，而 `step` 的
    选目标过滤会摘掉 `in_flight` 的子目标 ⇒ 一次不成形的回答 = 这条路永久封存
    （预算里的 `max_persist_attempts` 在 F 侧零消费者）。现在重问到上限才 blocked，
    且重试用尽的 blocked 不带 `in_flight`（下轮仍会重试它）。"""
    bad = _round(product="reduction", new_subgoals=[])            # reduction 必须给 1–3 条
    llm = FakeLLM(bad, bad)                                       # 预算里 max_persist_attempts=2
    f = _f(store, llm=llm)
    pid = _new_plan(f)
    out = f.step(pid)

    rec = store.rows("attack_plans")[0]["history"][-1]
    assert out["outcome"] == "no_change", out
    assert rec.get("product_detail") is None, rec
    assert "不成形" in rec["detail"] and "1–3" in rec["detail"], rec["detail"]
    # 判据①：真的重问了（不是同一个问题原样再发一遍）—— 原因必须进第二次的提示词
    assert len(llm.prompts) == 2, llm.prompts
    assert "不成形" in llm.prompts[1] and "1–3" in llm.prompts[1], llm.prompts[1]
    # 判据②：重试用尽 ≠ 永久封存 —— blocked 与 in_flight 是两件事
    sg = store.rows("attack_plans")[0]["subgoals"][0]
    assert sg["status"] == "blocked" and sg.get("in_flight") is not True, sg


def test_the_pre_spend_gate_stops_the_call_before_any_money_is_spent(store: Store):
    """I9：子目标没有可检验形式 ⇒ 一轮的钱都不花（模型一次都没被调用）。"""
    llm = FakeLLM()                    # 一次都不该被调用（调了就 AssertionError）
    f = _f(store, llm=llm)
    pid = _new_plan(f, testable="")
    out = f.step(pid)

    rec = store.rows("attack_plans")[0]["history"][-1]
    assert llm.prompts == [], "闸门没过却发了模型调用"
    assert rec["product"] == "dead_end" and rec["dead_end_reason"] == "缺定义", rec
    assert "可检验形式" in rec["detail"], rec["detail"]
    assert out["outcome"] == "no_change", out


def test_a_step_on_a_missing_plan_lists_the_plans_in_the_ledger(store: Store):
    """判据（`draft/39` §6.41 的 D51）：拒信要可行动 —— 说清在册的 `plan_id` 与 `problem_key`。

    真机读数（T5 第 1 趟 `p8-fermat-shorter-proof`）：主控把 `problem_key`
    （`flt-conj-1`）当 `plan_id` 传了三次，每次都只收到一句"攻坚计划 flt-conj-1 不存在"
    —— 而台账里明明有一行（`plan_id=0000`）。只说"没有"、不说"有哪些"，调用方只能硬猜
    （与 §6.21 修的 D 侧 qid 那条同一族）。
    """
    from agentflow.agent_f import AgentF, PlanError

    pid = AgentF(store).create_plan("难题", "flt-conj-1", subgoals=[
        {"sid": "s1", "text": "判定这条难题", "owner": "F", "testable": "有限界"}])["plan_id"]
    try:
        _f(store).step("flt-conj-1")
    except PlanError as exc:
        text = str(exc)
    else:  # pragma: no cover —— 走不到这里
        raise AssertionError("不存在的 plan_id 竟然推了一轮")

    assert pid in text, text
    assert "problem_key=flt-conj-1" in text, text
    assert "step 要的是 plan_id" in text, text


def test_a_step_on_an_empty_ledger_says_to_create_a_plan_first(store: Store):
    """负控：台账里一条计划都没有时，拒信要指向"先立项"，而不是给一张空清单。"""
    from agentflow.agent_f import AgentF, PlanError

    try:
        AgentF(store).step("0000")
    except PlanError as exc:
        text = str(exc)
    else:  # pragma: no cover
        raise AssertionError("空台账竟然推了一轮")

    assert "一条攻坚计划都没有" in text, text
    assert "F.create_plan" in text, text


def test_the_tool_layer_path_gets_the_registered_seam(store: Store):
    """判据（`draft/39` §6.33 的 D42c）：工具层那条路也要拿得到缝。

    真机读数（T2 第 14 趟 `projects/p6p-research-from-zero`，`--attack-reasoning` 开着）：
    `F.step` 连续 5 次 `no_change` —— 因为 M 派 `F.step` 走的是 `attack.step`
    这条工具路径（`attack_tools._agent_for` → `AgentF(store)`），而顺手接好的那条
    角色工厂路它不走。判据钉两半：登记了缝 ⇒ 工具层的 `attack.step` 真推一轮；
    没登记 ⇒ 照旧 `dead_end(缺工具)`（默认确定性不许被这处改动破坏）。
    """
    from agentflow import agent_f as AF

    llm = FakeLLM(_round(product="reduction", reason="拆成两条更小的判定",
                         new_subgoals=[{"goal": "判定 n<=12 的小情形",
                                        "testable": "枚举 n<=12 全部候选"}]))
    reg = AF.install_f_tools(store)

    def _plan_for(key: str) -> str:
        return AF.AgentF(store).create_plan("难题", key, subgoals=[
            {"sid": "s1", "text": "判定这条难题", "owner": "F",
             "testable": "存在反例或有限界"}])["plan_id"]

    build = AF.AgentF(store)

    def _last_product(plan_id: str) -> dict:
        row = build._plan_row(plan_id) or {}
        hist = list(row.get("history") or [])
        return dict(hist[-1]) if hist else {}

    # ① 没登记 ⇒ 工具层那条路仍是"未接线"（负控）
    pid_off = _plan_for("PK-TOOL-LAYER-OFF")
    off = reg.call("attack.step", plan_id=pid_off)
    assert off.ok, off
    rec_off = _last_product(pid_off)
    assert rec_off["product"] == "dead_end" and rec_off["dead_end_reason"] == "缺工具", rec_off

    # ② 登记之后 ⇒ 同一条工具路径真的推了一轮（正控；换一条计划 —— 上一条的子目标
    #    已经被 dead_end 标了 `in_flight`，下一轮按设计不会再选它）
    pid_on = _plan_for("PK-TOOL-LAYER-ON")
    AF.set_default_llm(llm)
    try:
        on = reg.call("attack.step", plan_id=pid_on)
    finally:
        AF.set_default_llm(None)
    assert on.ok, on
    rec_on = _last_product(pid_on)
    assert rec_on["product"] == "reduction", rec_on
    assert rec_on["product_detail"]["new_subgoals"], rec_on


def test_j07_the_tool_path_receives_the_config_of_its_own_root(tmp_path):
    """J-07：工具路径的 F 必须拿到它那个工作区登记的那份配置（按 root 键，防 B8 复发）。

    `tools/attack_tools._agent_for` 此前是 `AgentF(store, llm=…)` —— 不传 `config=` ⇒ F 的预算四键在工具路径上永远是空
    dict（`draft/44` J-07 实测：那四个键全仓无赋值点）。这里给配置补一条工具路径的登记口：`llmseam.set_role_config(role, root, cfg)`，
    按 `(角色, root)` 键，不是全局单值 —— `draft/41` 的 B8 逐字记着 `conductor_for` 按 root 缓存、同进程第二次装配会沿用第一次的设定；全局单值会把 B8
    换个地方重演：
    A 工作区的配置发给 B 工作区的 F，而读数上两边都"看起来正常"。

    判据三条 + 一条反负控：① 不登记 ⇒ `cfg == {}`（与不传 config 逐字同形）；② 在 root A 登记 ⇒ A 的 F 拿到它；③ 反负控：两个 root 各登记一份 ⇒ 互不影响；④
    登记 `None` ⇒ 回到不登记的行为。"""
    from agentflow import llmseam as LS
    from agentflow.tools import attack_tools as AT

    a, b = tmp_path / "a", tmp_path / "b"
    sa, sb = Store(a), Store(b)
    sa.init()
    sb.init()
    try:
        assert AT._agent_for(sa).cfg == {}, "不登记时必须与不传 config 逐字同形"
        LS.set_role_config("F", a, {"round_budget_usd": 1.5})
        assert AT._agent_for(sa).cfg == {"round_budget_usd": 1.5}
        assert AT._agent_for(sb).cfg == {}, "另一个工作区不许串台（B8 的形态）"
        LS.set_role_config("F", b, {"round_budget_usd": 9.9})
        assert AT._agent_for(sa).cfg["round_budget_usd"] == 1.5
        assert AT._agent_for(sb).cfg["round_budget_usd"] == 9.9
        LS.set_role_config("F", a, None)
        assert AT._agent_for(sa).cfg == {}, "登记 None ⇒ 回到不登记的行为"
    finally:
        LS.set_role_config("F", a, None)
        LS.set_role_config("F", b, None)


# ============================================================ P-09：预算读数（注入点 + 三态）


def _reading(**over) -> dict:
    """注入读数的形状（判据与实现共用同一份口径，不各写一套）。"""
    base = {"status": "known", "left_usd": 2.5, "spent_usd": 0.4,
            "source": "测试注入（P-09 的注入点）"}
    base.update(over)
    return base


def _reduction_reply() -> str:
    return _round(product="reduction", reason="拆成一条更小的判定",
                  new_subgoals=[{"goal": "判定 n<=12 的小情形",
                                 "testable": "枚举 n<=12 全部候选"}])


def test_p09_a_zero_left_reading_stops_the_round_before_it_spends(store: Store):
    """判据①（`draft/44:60`）：注入的读数说"还剩 0" ⇒ 这一轮一次模型调用都不发。

    "还剩 0"是事实，所以它仍然是否决面里的一条（`pre_spend_gate` 的第三条）。
    这一条与下面判据③是同一次裁定的两面：读数读得到且是 0 ⇒ 否决；
    读数读不到 ⇒ 不否决（不许把"没读数"折成"零"）。
    """
    llm = FakeLLM()                       # 调了就 AssertionError
    f = _f(store, llm=llm, budget_reading=_reading(left_usd=0.0))
    out = f.step(_new_plan(f))

    assert llm.prompts == [], "读数说还剩 0，这一轮却发了模型调用"
    assert out["action"] == "dead_end", out
    assert out["budget_known"] is True, out
    assert out["budget_reading"]["left_usd"] == 0.0, out
    rec = store.rows("attack_plans")[0]["history"][-1]
    assert rec["dead_end_reason"] in AR.DEAD_END_REASONS, rec
    assert "预算" in rec["detail"], rec["detail"]


def test_p09_a_sufficient_reading_lets_the_round_spend(store: Store):
    """判据②：读数够（`left_usd > 0`）⇒ 闸门放行，这一轮正常花一次模型调用。"""
    llm = FakeLLM(_reduction_reply())
    f = _f(store, llm=llm, budget_reading=_reading(left_usd=2.5))
    out = f.step(_new_plan(f))

    assert len(llm.prompts) == 1, llm.prompts
    assert out["action"] == "reduction", out
    assert out["budget_known"] is True, out
    assert out["budget_reading"]["status"] == "known", out
    assert out["budget_reading"]["source"].startswith("测试注入"), out


def test_p09_a_missing_reading_does_not_stop_the_round_and_says_so(store: Store):
    """判据③：不注入 ⇒ `spend` 不为假，且"读不到"如实进返回值（不是静默洞）。

    这里刻意不叫"最保守的做法"：那个方向是反的。读不到 ≠ 不许花 ——
    不把"读数缺失"变成全局停摆；钱仍由全局预算守卫管
    （`conductor` 的 `[4a]` 开工前守卫 + `policy.usd_budget`）。
    """
    llm = FakeLLM(_reduction_reply())
    f = _f(store, llm=llm)                # 不注入读数
    out = f.step(_new_plan(f))

    assert len(llm.prompts) == 1, "读数缺失不该让这一轮停摆（方向与'最保守'相反）"
    assert out["budget_known"] is False, out
    assert out["budget_reading"]["status"] == "unknown", out
    assert AR.BUDGET_UNREADABLE_NOTE in out["budget_reading"]["why"], out
    # 反负控：闸门那一层"没有读数"同样不否决（不是 F 这一层特判出来的）
    assert AR.pre_spend_gate(goal="证 n=3", testable="枚举")["spend"] is True
    assert AR.pre_spend_gate(goal="证 n=3", testable="枚举")["checks"]["budget_known"] is False


def test_p09_the_missing_reading_names_the_gap_and_who_still_guards_the_money(store: Store):
    """缺口登记（不许"永远 unknown 但没人说"）：`why` 要点名缺什么、谁还在管钱。

    工具路径拿不到当前这一次召唤的 `task_id`（`tools/base.py:1304` 的
    `ToolRegistry.call` 没有任务上下文的形参，`tools/attack_tools.py:281-300`
    的 `_agent_for(store)` 只能拿到 `store`）⇒ 注入点暂时没有真源。
    它是残余集 R1 的「P-09 粒度口径」的前置（记账粒度是召唤级：
    `tokenmeter.py:250-286` 的 `usd_for` / `usd_reading` 都以 `task_id` 为键）——
    所以这条读数必须把缺口写在明面上，而不是永远 `unknown` 而无人知晓。
    """
    reading = _f(store).budget_of_round()

    assert reading["status"] == "unknown", reading
    for needle in ("task_id", "ToolRegistry.call", "attack_tools.py", "R1", "召唤级"):
        assert needle in reading["why"], (needle, reading["why"])
    # 谁还在管钱：必须给出代码行的证据，不许只写一句"有人管"
    for needle in ("conductor.py", "[4a]", "policy.py", "usd_budget"):
        assert needle in reading["why"], (needle, reading["why"])
    # 反负控：读得到的时候不许还挂着"读不到"的说法
    ok = _f(store, budget_reading=_reading()).budget_of_round()
    assert ok["status"] == "known" and not ok["why"], ok


def test_p09_the_framework_written_why_strategy_carries_the_same_sentence(store: Store):
    """口径逐字对齐：框架自己写 `why_strategy` 的那几条路，也要写同一句（且方向不许反）。

    "读数缺失 ⇒ 不据此否决"这句话在代码里只有一份
    （`attackround.BUDGET_UNREADABLE_NOTE`），提示词侧（E 的 policy）逐字引用它 ——
    同一句在下面第三条断言里被同时钉住，两处漂了就红。
    """
    from agentflow import agent_prompts as AP

    llm = FakeLLM()                       # 缺定义 ⇒ 闸门先挡住，模型一次都不发
    f = _f(store, llm=llm)                # 不注入 ⇒ 读不到
    out = f.step(_new_plan(f, testable=""))

    rec = store.rows("attack_plans")[0]["history"][-1]
    assert rec["dead_end_reason"] == "缺定义", rec
    why = rec["product_detail"]["why_strategy"]
    assert AR.BUDGET_UNREADABLE_NOTE in why, why
    assert "最保守" not in why, "读数缺失不许写成'最保守的做法'（方向相反）"
    assert out["budget_known"] is False, out
    # 提示词侧：同一句逐字在 E 的 policy 里（两处口径不许漂）
    prompt_side = "\n".join(AP.ROLE_BRIEFS["E"].policy)
    assert AR.BUDGET_UNREADABLE_NOTE in prompt_side, "提示词侧那一句与代码侧不同源"
    assert "读不到时如实说读不到（那时按最保守的做法办）" not in prompt_side, prompt_side


def test_p09_the_reading_keys_are_on_every_return_path(store: Store):
    """键名稳定：不管这一轮从哪条路收尾，返回值里都有 `budget_known` / `budget_reading`。

    为什么这一条要单列：只在"顺利推进"那条路上给读数，会让"这一轮有没有预算读数"
    取决于它走了哪条分支 —— 那正是"读数存在与否本身成了隐变量"的形态。
    六条收尾路径逐条走一遍（每条一个独立计划：`dead_end` 会把子目标标 `in_flight`）。
    """
    from agentflow.agent_f import AgentF

    keys = {"budget_known", "budget_reading"}
    seen: list[str] = []

    def _one(tag: str, reply, **kw) -> dict:
        llm = None if reply == "unwired" else (BrokenLLM() if reply == "broken"
                                               else FakeLLM(*reply))
        f = AgentF(store, config={"workspace_root": store.root, **kw.pop("cfg", {})},
                   llm=llm, budget_reading=kw.pop("reading", None))
        out = f.step(_new_plan(f, key=f"PK-KEYS-{tag}", **kw))
        assert keys <= set(out), (tag, sorted(set(out)))
        seen.append(tag)
        return out

    _one("OK", [_reduction_reply()], reading=_reading())                       # 正常推进
    _one("GATE", [], testable="")                                             # I9 闸门否决
    _one("BIG", [], cfg={"round_cost_usd": 3.5, "round_cost_cap_usd": 3.0})   # I16 超上限
    _one("SHAPE", [_round(product="reduction", new_subgoals=[])])             # 不成形
    _one("BROKEN", "broken", reading=_reading())                              # 缝炸了
    _one("UNWIRED", "unwired")                                                # 没接推理缝
    assert len(seen) == 6, seen
    # 反负控：那条"没接缝"的路走的是 `_deploy` 的另一支（不在 `_reason_self` 里），
    # 它的返回值同样带读数 —— 否则"有没有读数"会取决于 role 分派到哪一支。
    assert store.rows("attack_plans")[-1]["history"][-1]["dead_end_reason"] == "缺工具"


def test_p09_the_over_budget_block_is_verbatim_and_the_injected_spent_is_used(store: Store):
    """判据④：I16 的 `too_large` 逐字不变；注入的读数参与它，但不许把它抹过去。

    两半：① 配置里那一组数（`round_cost_usd` / `round_cost_cap_usd` / `spent_usd`）
    算出来超上限 ⇒ 照旧 `dead_end(超出本轮预算)` 且理由逐字带"不截断"；
    ② 注入了 `spent_usd` 时，I16 用的是注入的那一份（不算出第二个真相）。
    """
    llm = FakeLLM()
    f = _f(store, llm=llm, round_cost_usd=3.5, round_cost_cap_usd=3.0, spent_usd=0.4,
           budget_reading=_reading(left_usd=2.5))
    f.step(_new_plan(f, key="PK-P09-OVER"))
    rec = store.rows("attack_plans")[0]["history"][-1]
    assert llm.prompts == [], "超上限的一轮必须显式阻塞（不许静默截断）"
    assert rec["dead_end_reason"] == "超出本轮预算", rec
    assert "不截断" in rec["detail"] and "拆子目标" in rec["detail"], rec["detail"]

    # ② 同一组 cfg，但注入的 spent_usd 说"已经花了 2.0" ⇒ 超上限的是注入的那一份
    f2 = _f(store, llm=FakeLLM(), round_cost_usd=0.1, round_cost_cap_usd=1.5, spent_usd=0.0,
            budget_reading=_reading(left_usd=2.5, spent_usd=2.0))
    f2.step(_new_plan(f2, key="PK-P09-OVER-2"))
    rec2 = [r for r in store.rows("attack_plans") if r["problem_key"] == "PK-P09-OVER-2"][0]
    assert rec2["history"][-1]["dead_end_reason"] == "超出本轮预算", rec2["history"][-1]

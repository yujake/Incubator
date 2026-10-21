# -*- coding: utf-8 -*-
"""F 一轮提示词的两条契约（2026-10-19，`projects/mp4` 的 `mp4-6` 真机暴露的两个缺陷）。

缺陷 1：模型把 `outcome` 写成 `no_change`，不在受控产物里。真机原文（`projects/mp4/data/attack_plans.json`，计划 `000002` 第 1
轮 `detail`）：子目标 `sg-r5` 的这一轮不成形（`no_change` 不是四种产物之一（它正是 D15 要根除的形态）；什么都做不了时也要落成 `dead_end`（受控理由 + 证据 +
best_partial））⇒ 未推进；已按预算里的 `max_persist_attempts=3` 带着原因重问了 3 次。计划 `000001` 第 1 轮同形 ⇒ 重问 3 次仍然给 `no_change`，
说明"光在提示词里写一句不够"。

三处根因（缺一处都修不好）：① `agent_f/core.py` 的 `_attack_prompt`：受控四档是提示词的最后一块（上下文 → 证据正文 → history → 重问原因 → 才轮到"四档之一"）；②
同文件的 `_reason_self`：`retry_note = str(exc)` —— 只有一句判据原话，既不复述四档，也不给模型看它自己写了什么；③ `attackround.parse_round`：
非法 `product` 只说"必须是 (...) 之一，收到 'x'"，`no_change` 那支另有一句"它正是 D15 要根除的形态" —— 两处都不给"你给的是 X"。

缺陷 2：模型编造引用 id。真机原文（计划 `000001` 第 1 轮）：引了 `reports/attack-000000.md §A5` —— 台账里不存在，判据当场拒收并报"伪造引用是不可逆损失（R-03）"；
拒收拦得住，但它为什么编没治：`_evidence_digest` 里那句"不在册"是一条旁注，提示词从没把"能引的 id 就这些"摆出来。

判据一律离线（假模型返回写死的 JSON），每一组都带负控（把修好的那一处按改前的形态注回去 ⇒ 删掉纪律那一段 / 把词表挪回末尾 / 用改前的 `retry_note` 与旧旁注），同一组断言必须红 ——
否则那组断言分不清"修好了"与"永远是绿的"。"""
from __future__ import annotations

import json

import pytest

from agentflow import attackround as AR
from agentflow.agent_f import AgentF
from agentflow.agent_f.core import _attack_prompt
from agentflow.store import Store

#: 受控词表必须落在提示词的前多少行（"挪到最前面"的可判形式）。
PROMPT_HEAD_LINES = 40

#: 引用纪律那一句（字面断言：它就是提示词里给模型读的那句话）。
DISCIPLINE_NEEDLE = "只许引用下面列出的 id"


class FakeLLM:
    """最小模型缝（`judge.judge_json` 的调用约定）：每次调用都记下提示词。"""

    def __init__(self, *replies: str) -> None:
        self.replies = list(replies)
        self.prompts: list[str] = []

    def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if not self.replies:
            raise AssertionError("模型被调用的次数比剧本多")
        return self.replies.pop(0)


def _f(store: Store, llm=None, **cfg) -> AgentF:
    return AgentF(store, config={"workspace_root": store.root, **cfg}, llm=llm)


def _round(**fields) -> str:
    """造一份成形产物的 JSON 文本（缺省补上公共字段）。"""
    base = {"strategy": "小情形搜索找模式", "why_strategy": "先看小情形有没有模式"}
    base.update(fields)
    return json.dumps(base, ensure_ascii=False)


def _proof_premise() -> str:
    """一份只有显式前提的 `proof`（不引 id ⇒ 不会被 R-03 拒收，用来单独判提示词）。"""
    return _round(product="proof", steps=[{"text": "设命题成立（本轮前提）", "assumption": True}])


def _new_plan(f: AgentF, *, evidence_ids=(), key: str = "PK-CONTRACT") -> str:
    return f.create_plan("难题：判定这个族的存在性", key, subgoals=[
        {"sid": "s1", "text": "判定这条难题", "owner": "F",
         "testable": "存在反例或有限界", "evidence_ids": list(evidence_ids)},
    ])["plan_id"]


def _first_prompt(store: Store, *, evidence_ids=(), reply: str | None = None) -> str:
    """走一次真的 `step`，把模型收到的第一条提示词拿回来。"""
    llm = FakeLLM(reply if reply is not None else _proof_premise())
    f = _f(store, llm=llm)
    f.step(_new_plan(f, evidence_ids=evidence_ids))
    assert llm.prompts, "模型一次都没被调用 ⇒ 这条判据没有输入"
    return llm.prompts[0]


# ============================================================ 判据函数（负控也走它们）


def vocab_in_head(prompt: str, *, within: int = PROMPT_HEAD_LINES) -> bool:
    """受控四档 + "`no_change` 不是产物"是否在提示词的前 `within` 行、且在上下文之前。

    两个条件都要：只判行数的话，一份短提示词把词表挪到末尾也仍然"在前 40 行内"
    （实测：最小提示词 41 行）—— 那样这条判据分不出"在最前面"与"在最后面"。
    所以再加一条序关系：四个取值必须出现在「难题键」那一行（上下文那一段）之前。
    """
    head = "\n".join(prompt.splitlines()[:within])
    if not (all(f"`{v}`" in head for v in AR.PRODUCTS)
            and "`no_change` 不是产物" in head):
        return False
    anchor = prompt.find("难题键：")
    if anchor < 0:                      # 没有上下文那一段（纯提示词夹具）⇒ 行数那一条已经够了
        return True
    return all(prompt.index(f"`{v}`") < anchor for v in AR.PRODUCTS)


def retry_names_vocabulary_and_quotes(note: str, raw: str) -> bool:
    """重问那一段三件事齐不齐：四档 + 上一次原文 + "换成上述四个之一"。

    只在重问那一段里判（`_retry_section`），不在整份提示词里判 —— 否则提示词头部
    本来就印着四档，"重问复述四档"这一条会永远为真（那是判据自己的假绿）。
    """
    return (all(f"`{v}`" in note for v in AR.PRODUCTS)
            and raw in note
            and "换成上述四个之一" in note)


def _retry_section(prompt: str) -> str:
    """提示词里"重问"那一段（从"上一次的产物"那行到末尾）。"""
    marker = "上一次的产物"
    return prompt[prompt.index(marker):] if marker in prompt else ""


def discipline_with_ids(prompt: str, *ids: str, window: int = 400) -> bool:
    """引用纪律那句在不在，且当轮 id 列表紧邻它（纪律那句之后 `window` 字内）。"""
    if DISCIPLINE_NEEDLE not in prompt:
        return False
    tail = prompt[prompt.index(DISCIPLINE_NEEDLE):]
    return all(f"`{i}`" in tail[:window] for i in ids)


def not_on_ledger_is_a_ban(line: str) -> bool:
    """"不在册"那一行是不是一条禁令 + 正确做法（而不只是一句旁注）。"""
    return "不在册" in line and "禁止" in line and "assumption" in line


def _move_vocab_to_tail(prompt: str) -> str:
    """负控夹具（改前的形态）：把带受控取值的那些行挪回提示词末尾。"""

    def names_a_product(line: str) -> bool:
        return (any(f"`{v}`" in line for v in AR.PRODUCTS)
                or "`no_change` 不是产物" in line)

    lines = prompt.splitlines()
    moved = [ln for ln in lines if names_a_product(ln)]
    rest = [ln for ln in lines if not names_a_product(ln)]
    return "\n".join(rest + [""] + moved)


# ============================================================ 缺陷 1：受控词表在最前面


def test_the_controlled_products_are_at_the_head_of_the_prompt(store: Store):
    """判据：四个受控取值在提示词前 40 行内，且"`no_change` 不是产物"逐字在。

    真机依据：词表写在末尾时，重问 3 次模型仍然交 `{"outcome": "no_change"}`
    （`attack_plans` 计划 `000002` / `000001` 第 1 轮）。
    """
    prompt = _first_prompt(store)
    head = "\n".join(prompt.splitlines()[:PROMPT_HEAD_LINES])

    assert vocab_in_head(prompt), (
        "受控四档没有落在提示词头部（前 "
        f"{PROMPT_HEAD_LINES} 行）—— 模型读到的顺序仍是「先看事实、最后才知道只能交四档」；"
        f"头部实际是：\n{head}")
    for value in AR.PRODUCTS:
        assert f"`{value}`" in head, f"前 {PROMPT_HEAD_LINES} 行里没有受控取值 `{value}`"
    assert "`no_change` 不是产物" in head, head
    # 反例要逐个点名（同一族的别名也不许凭空出现）
    for alias in ("`ok`", "`success`", "`done`"):
        assert alias in head, f"头部没有点名反例 {alias}"
    # 四档的必填字段也在这同一个头部里（"先给词表、再给每种的必填字段"）
    for field in ("`new_subgoals`", "`script_spec`", "`steps`", "`best_partial`"):
        assert field in head, f"头部没有 {field} 那一档的必填字段"


def test_the_vocabulary_moved_back_to_the_tail_turns_the_control_red(store: Store):
    """负控：把受控词表挪回提示词末尾（改前的形态）⇒ 上面那条判据必须红。"""
    prompt = _first_prompt(store)
    doctored = _move_vocab_to_tail(prompt)
    assert not vocab_in_head(doctored), (
        "把词表挪到末尾之后判据仍然是绿的 ⇒ 这条判据测的不是「词表在最前面」"
        f"；挪过之后的前 40 行：\n" + "\n".join(doctored.splitlines()[:PROMPT_HEAD_LINES]))


# ============================================================ 缺陷 1：重问复述 + 引用原文


def test_a_no_change_round_is_asked_again_and_the_second_try_lands(store: Store):
    """行为：第一次 `{"outcome": "no_change"}`、第二次合法 `dead_end` ⇒ 第二次成功。

    同时钉住"第二次的提示词里出现了四个合法值 + 上一次的原文"—— 真机上重问 3 次
    都失败，正是因为那两样都不在重问提示词里。
    """
    bad = json.dumps({"outcome": "no_change"}, ensure_ascii=False)
    good = _round(product="dead_end", reason="缺工具",
                  evidence="这一轮要走的那条路没有可用的检查器",
                  best_partial=[{"what": "已把命题缩到有限枚举", "ids": [],
                                 "why_partial": "缺工具"}])
    llm = FakeLLM(bad, good)
    f = _f(store, llm=llm)
    out = f.step(_new_plan(f))

    assert len(llm.prompts) == 2, [p[-300:] for p in llm.prompts]
    # 第一次问的时候还没有"上一次"；第二次有 —— 这就是重问，不是同一句话原样再发
    assert '{"outcome": "no_change"}' not in llm.prompts[0]
    second = llm.prompts[1]
    section = _retry_section(second)
    assert section, ("第二次提问里没有「上一次的产物」那一段 ⇒ 那不叫重问\n"
                     + second[-900:])
    assert retry_names_vocabulary_and_quotes(section, '{"outcome": "no_change"}'), (
        "重问那一段里没有同时出现「四个合法值 + 上一次的原文 + 把 X 换成上述四个之一」：\n"
        + section[-900:])
    # 逐字引用（让模型看见自己写了什么）：非法取值被点名
    assert "no_change" in section, section[-600:]
    # 第二次成形 ⇒ 这一轮真的交了产物（而不是"重试用尽"）
    rec = store.rows("attack_plans")[0]["history"][-1]
    assert out["action"] == "dead_end", out
    assert rec["product"] == "dead_end" and rec["dead_end_reason"] == "缺工具", rec
    assert "不成形" not in rec["detail"], rec["detail"]


def test_the_old_retry_note_would_not_satisfy_the_same_criterion():
    """负控：改前的 `retry_note = str(exc)`（只有一句判据原话）⇒ 同一判据必须红。"""
    with pytest.raises(AR.RoundError) as ei:
        AR.parse_round('{"outcome": "no_change"}')
    legacy = str(ei.value)                      # 逐字就是改前那一行的值
    assert not retry_names_vocabulary_and_quotes(legacy, '{"outcome": "no_change"}'), (
        "改前的重问文本竟然满足新判据 ⇒ 这条判据测不出「复述 + 引用原文」这一改")


def test_the_parser_lists_the_four_values_and_what_it_got():
    """判据（解析层）：非法取值时错误消息里列着四个合法值与"你给的是 X"。"""
    with pytest.raises(AR.RoundError) as ei:
        AR.parse_round('{"outcome": "no_change"}')
    msg = str(ei.value)
    for value in AR.PRODUCTS:
        assert f"`{value}`" in msg, msg
    assert "你给的是" in msg and "`no_change`" in msg, msg
    assert ei.value.illegal == "no_change", ei.value.illegal

    # 另一档：`product` 写了一个不在四档里的词 ⇒ 同样点名"你给的是"
    with pytest.raises(AR.RoundError) as ei2:
        AR.parse_round(_round(product="ok"))
    msg2 = str(ei2.value)
    assert "你给的是 `ok`" in msg2, msg2
    for value in AR.PRODUCTS:
        assert f"`{value}`" in msg2, msg2
    # 反负控：合法的四档不许被这套纠正指引误伤
    ok = AR.parse_round(_round(product="dead_end", reason="缺工具", evidence="没有检查器",
                               best_partial=[{"what": "w", "ids": [], "why_partial": "p"}]))
    assert ok["product"] == "dead_end", ok


# ============================================================ 缺陷 2：引用纪律 + 合法 id


def test_the_citation_discipline_is_next_to_the_rounds_id_list(store: Store):
    """判据：提示词里含引用纪律那句（字面），且当轮 id 列表紧挨着它。"""
    from conftest import add_literature

    add_literature(store, "0004", title="边-围长正则图的下界")
    prompt = _first_prompt(store, evidence_ids=["lit:0004"])

    assert DISCIPLINE_NEEDLE in prompt, prompt
    # 三条纪律逐条在：只许引列出的 id / 没有可引的就不要引 / 要声明前提就 assumption
    assert "没有可引的就不要引" in prompt, prompt
    assert "`assumption: true`" in prompt, prompt
    # `reports/…md` 是产物文件、不是台账 id（真机编的正是这一种定位）
    assert "`reports/…md` 是产物文件，不是台账 id" in prompt, prompt
    assert "§A5" in prompt, "提示词没有点名它编过的那一类定位（§A5）"
    # 当轮 id 列表紧邻纪律那句（不是散在提示词别处）
    assert discipline_with_ids(prompt, "lit:0004"), prompt[:2000]


def test_dropping_the_discipline_section_turns_the_control_red(store: Store, monkeypatch):
    """负控：把"引用纪律"那一段删掉（改前的形态：根本没有这一段）⇒ 同一判据必须红。"""
    from conftest import add_literature

    add_literature(store, "0004", title="边-围长正则图的下界")
    _first_prompt(store, evidence_ids=["lit:0004"])      # 先确认正控是绿的
    row = store.rows("attack_plans")[0]
    plan, sg = dict(row), dict(row["subgoals"][0])

    monkeypatch.setattr(AR, "CITE_DISCIPLINE", "")
    legacy = _attack_prompt(plan=plan, sg=sg, owner="F", tried=[],
                            evidence=[], citable_ids=["lit:0004"])
    assert not discipline_with_ids(legacy, "lit:0004"), (
        "纪律那一段删掉之后判据仍然是绿的 ⇒ 它测的不是这一段")
    assert "`lit:0004`" in legacy, "负控前提不成立：id 列表本该还在（被删的只是纪律那句）"


def test_a_fabricated_citation_is_refused_with_the_legal_ids_of_this_round(store: Store):
    """行为：引一个不在册的定位 ⇒ 拒收，且消息里含"合法 id 有："与当轮的 id 列表。

    真机那一份逐字：`reports/attack-000000.md §A5`（计划 `000001` 第 1 轮）。
    """
    from conftest import add_literature

    add_literature(store, "0004", title="边-围长正则图的下界")
    fake = "reports/attack-000000.md §A5"
    llm = FakeLLM(_round(product="proof", steps=[
        {"text": "由 reports/attack-000000.md §A5 直接得到结论", "cites": [fake]}]))
    f = _f(store, llm=llm)
    out = f.step(_new_plan(f, evidence_ids=["lit:0004"]))

    assert out["outcome"] == "no_change" and out["action"] == "no_change", out
    reason = out["reason"]
    assert "不存在的 id" in reason, reason
    assert "合法 id 有：" in reason, reason
    # 列表来自当轮 digest（不是现编的）：这一轮唯一那条在册 id 必须在里面
    assert "`lit:0004`" in reason, reason
    # "拒收的是引用，不是产物形态" ⇒ 四档一起念
    for value in AR.PRODUCTS:
        assert f"`{value}`" in reason, reason
    # 拒收的一轮不落产物（落了就等于认了它的引文），也不记成一次尝试
    rec = store.rows("attack_plans")[0]["history"][-1]
    assert rec.get("product_detail") is None, rec
    assert store.rows("attack_plans")[0]["subgoals"][0]["attempts"] == 0, rec
    assert "合法 id 有：" in rec["detail"], rec["detail"]


def test_an_id_that_is_not_on_the_ledger_is_a_ban_not_a_side_note(store: Store):
    """判据：`_evidence_digest` 的"不在册"是禁令 + 正确做法，不是一句旁注。"""
    prompt = _first_prompt(store, evidence_ids=["exp:999999"])
    line = next((ln for ln in prompt.splitlines() if "不在册" in ln), "")
    assert line, "提示词里没有点名那条不在册的证据（三态：它不该被静默丢掉）"
    assert not_on_ledger_is_a_ban(line), line
    # 负控（改前那句旁注）⇒ 同一判据必须红
    legacy = ("exp:999999（experiments）：**这一条不在册**"
              "（台账里没有这个 id ⇒ 引它算伪造引用，会被拒收）")
    assert not not_on_ledger_is_a_ban(legacy), legacy

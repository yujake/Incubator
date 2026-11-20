# -*- coding: utf-8 -*-
"""ROLECLEAN-1（角色 A / B / D）的残留判据：声明正文 vs 实现、死入口不许长回来。

## 这一组守什么（每条都对应一张取证表里的"改前红"）

| # | 判据 | 改前为什么红 |
|---|---|---|
| 1 | D 的「猜想九状态」硬条件清单与 `schema.Conjecture.validate` 逐条一致 | 清单停在 2026-11-13 裁定 ② 之前：`refuted` 漏了第二条来路 `refusal_ref`、`promoted` 漏了 `proof_experiment_id`、九状态里漏了 `needs_evidence` 的 `notes` ⇒ 照文案做的模型会在"V 判有毛病"时去造一个反例实验 |
| 2 | B 的 boundary 不再说「三件套缺一不可」，并写明「缺证明不拒收」 | 实现（P-06）缺证明照常登记、落最低等级；文案与它同文件的动作摘要「没有稿不拒收」互相矛盾 |
| 3 | `B.ingest_manuscript(reason=…)` 的 `reason` 真的落进返回值 | 改前形参在函数体里一次都没被读（传了等于没传），而文案说它进读数 |
| 4 | 两个零调用方的死入口不许长回来（`_source_matches_row` / `_parse_json_block`） | 改前它们是零引用的包装壳：定义还在，全仓无人调 |
| 5 | S-09 的判据收 D 真正产出的置信度档名（high / medium / low），且 `research` 真的算它 | 改前只 `float(confidence)`，收到档名永远 `checked=False` —— 判据只有测试直接喂浮点数时才绿 |

## 反真空

第 1 / 2 条各带一个负控：把旧文案塞回去 / 把新句抠掉，同一个检查函数必须报红。
只断言"今天的文本里没有某句话"无法区分"改好了"与"这句话本来就不在"。
第 3 / 5 条是行为判据，负控是把判据该看的那一格拿掉就变红。
"""
from __future__ import annotations

import pathlib

from agentflow import agent_prompts as AP
from agentflow import schema as S


def _flat(text: str) -> str:
    """去掉空白 —— 判「读到的意思」，不判排版换行。"""
    return "".join(str(text).split())


def _has(text: str, needle: str) -> bool:
    return _flat(needle) in _flat(text)


def _d_boundary() -> str:
    return "\n".join(AP.ROLE_BRIEFS["D"].boundary)


def _b_boundary() -> str:
    return "\n".join(AP.ROLE_BRIEFS["B"].boundary)


# ============================================================ 判据 1（D 的猜想九状态）
def conjecture_status_problems(text: str) -> list[str]:
    """D 的「九状态硬条件」清单 vs `schema.Conjecture.validate` 的三处硬条件。

    返回问题清单（空 = 文案与实现一致）。正控与负控共用同一把尺子。
    """
    flat = _flat(text)
    problems: list[str] = []
    if "refusal_ref" not in flat:
        problems.append(
            "`refuted` 的文案没写第二条来路 `refusal_ref`（V 判「有毛病」/ B 拒收那一档；"
            "`schema.Conjecture.validate` 认它）")
    if "promoted_to" in flat:
        seg = flat.split("promoted", 1)[-1].split("known_in_literature", 1)[0]
        if "proof_experiment_id" not in seg:
            problems.append(
                "`promoted` 的文案只写 `promoted_to`，而 validate 要 "
                "`proof_experiment_id` ＋ `promoted_to.id`")
    if "needs_evidence" not in flat or "notes" not in flat:
        problems.append(
            "九状态清单漏了 `needs_evidence`：validate 要 `notes` 或 `withdraw_reason`")
    return problems


def test_d_the_conjecture_status_text_matches_the_schema() -> None:
    """正控：D 的 boundary 逐条对上 `Conjecture.validate` 的硬条件。"""
    problems = conjecture_status_problems(_d_boundary())
    assert not problems, "\n".join(problems)


def test_d_the_conjecture_text_checker_is_not_vacuous() -> None:
    """反真空：旧文案（改前那一版逐字）塞回去 ⇒ 三处必须逐条点红；新文案 ⇒ 绿。

    旧文案从改前那一版逐字抄来，不从当前文本拼 —— 拼出来的"旧版"会随修好一起变好。
    """
    stale = (
        "猜想的九个状态各自必须带什么：`proposed` 要给非空 `testable`；"
        "`supported_not_proved` 要至少一条 `experiment_ids`；"
        "`refuted` 要 `counterexample_experiment_id`；`proved` 要 `proof_experiment_id`；"
        "`promoted` 要 `promoted_to`；`known_in_literature` 要 `known_lit_id`；"
        "`withdrawn` 要 `withdraw_reason`。")
    problems = conjecture_status_problems(stale)
    assert len(problems) == 3, problems
    assert any("refusal_ref" in p for p in problems), problems
    assert any("promoted" in p for p in problems), problems
    assert any("needs_evidence" in p for p in problems), problems

    # 三处硬条件各自在真实 schema 上真的成立（文案不是照着一句空话写的）。
    S.Conjecture(conjecture_id="000000", statement="p", origin="gap", status="refuted",
                 refusal_ref="verifications/000000.jsonl#v-000001").validate()
    try:
        S.Conjecture(conjecture_id="000000", statement="p", origin="gap",
                     status="needs_evidence").validate()
    except ValueError as exc:
        assert "notes" in str(exc), exc
    else:  # pragma: no cover - 负控前提坏了才到这里
        raise AssertionError("needs_evidence 不写 notes 竟然通过了 validate ⇒ 文案判据失去对象")
    try:
        S.Conjecture(conjecture_id="000000", statement="p", origin="gap",
                     status="promoted",
                     promoted_to={"kind": "document_claim", "id": "0000#C1"}).validate()
    except ValueError as exc:
        assert "proof_experiment_id" in str(exc), exc
    else:  # pragma: no cover
        raise AssertionError("promoted 不带 proof_experiment_id 竟然通过了 validate")


# ============================================================ 判据 2（B 的三件套）
def three_pieces_problems(text: str) -> list[str]:
    """B 的 boundary：不许再说「三件套缺一不可」，并必须写明「缺证明不拒收」。"""
    flat = _flat(text)
    problems: list[str] = []
    if "三件套缺一不可" in flat:
        problems.append(
            "B 的 boundary 又说「命题台账三件套缺一不可」了 —— 实现缺证明不拒收"
            "（P-06；同一份 spec 的动作摘要写着「没有稿不拒收」）")
    if "缺证明不拒收" not in flat:
        problems.append("B 的 boundary 没有写清「缺证明不拒收」这条现行口径")
    return problems


def test_b_the_boundary_teaches_the_current_intake_rule() -> None:
    """正控：B 的 boundary 与 P-06 一致（不再要求三件套齐全才收）。"""
    problems = three_pieces_problems(_b_boundary())
    assert not problems, "\n".join(problems)


def test_b_the_boundary_checker_is_not_vacuous() -> None:
    """反真空：改前那一句塞回去 ⇒ 必红；新句抠掉 ⇒ 也红（两个方向都有牙）。"""
    stale = ("命题台账（statements）三件套缺一不可：含完整假设的命题正文（statement_full）、"
             "证明正文、出处（source_lit_id + page_range）。")
    problems = three_pieces_problems(stale)
    assert any("三件套缺一不可" in p for p in problems), problems
    assert any("缺证明不拒收" in p for p in problems), problems

    cut = _b_boundary().replace("缺证明不拒收", "（已删）")
    assert three_pieces_problems(cut), "把「缺证明不拒收」抠掉之后检查器没报红"


# ============================================================ 判据 3（B 的 reason 读数）
def test_b_ingest_manuscript_carries_the_caller_reason() -> None:
    """`reason` 是读数不是判据：传了要在返回值里看得见，没传是空串（不是缺键）。

    用一条必然在参数面被拒的调用（`mode` 不认识）走早期出口：受控拒的信封里
    同样要带这一格 —— 读数不因为这一笔没做成而丢。
    """
    from agentflow.agent_b.register_statement import _RegisterStatement

    _B = _RegisterStatement

    got = _B().ingest_manuscript(manuscript="reports/f-proof-000000.md",
                                 mode="not_a_mode", reason="给问题 3 补一份可签的稿")
    assert got.get("ok") is False and got.get("refused") == "bad_ingest_mode", got
    assert got.get("caller_reason") == "给问题 3 补一份可签的稿", got

    empty = _B().ingest_manuscript(manuscript="reports/f-proof-000000.md",
                                   mode="not_a_mode")
    assert empty.get("caller_reason") == "", empty
    assert "caller_reason" in empty, "没传 reason 时这一格也必须存在（空串 ≠ 缺键）"


# ============================================================ 判据 4（死入口不许长回来）
def test_the_dead_wrappers_are_gone_and_stay_gone() -> None:
    """零调用方的两个包装壳已删；它们不许以同名长回来（那会让"删了"没有读数）。"""
    from agentflow.agent_b import AgentB
    from agentflow.agent_d import AgentD

    assert not hasattr(AgentB, "_source_matches_row"), (
        "`_source_matches_row` 长回来了：它只是 `manuscriptpaths.manuscript_matches_row` "
        "的包装壳，全仓零调用（ROLECLEAN-1 取证时 src/refs=0、tests/refs=0）")
    assert not hasattr(AgentD, "_parse_json_block"), (
        "`_parse_json_block` 长回来了：它只是 `_support._json_object` 的包装壳，"
        "全仓零调用；解析实现只有 `_support._json_object` 一处")
    # 反真空：被包装的那两份实现仍然在（删的是壳，不是真身）。
    from agentflow import manuscriptpaths
    from agentflow.agent_d import _support as support

    assert callable(manuscriptpaths.manuscript_matches_row)
    assert callable(support._json_object)


# ============================================================ 判据 5（S-09 真的在跑）
def test_s09_accepts_the_confidence_vocabulary_d_research_actually_produces() -> None:
    """S-09 的判据收档名：low 说满了 ⇒ overstated；high 留余地 ⇒ understated。

    改前它只做 `float(confidence)` ⇒ 收到 `high` / `medium` / `low` 一律
    `checked=False`（"不是数字"），而 D 的 `research` 产出的正是这三个档名。
    """
    from agentflow.agent_d._support import conclusion_consistency_reading

    low = conclusion_consistency_reading(conclusion="我们证明了这条命题。", confidence="low")
    assert low["checked"] is True and low["verdict"] == "overstated", low
    high = conclusion_consistency_reading(conclusion="这也许成立，有待确认。", confidence="high")
    assert high["checked"] is True and high["verdict"] == "understated", high
    medium = conclusion_consistency_reading(conclusion="我们证明了这条命题。", confidence="medium")
    assert medium["checked"] is True and medium["verdict"] == "consistent", medium
    # 浮点那一档照旧收（原判据的调用面不许被收窄）。
    assert conclusion_consistency_reading(conclusion="我们证明了它。",
                                         confidence=0.3)["verdict"] == "overstated"
    # 认不出的字符串仍然是"没查成"，不许折成"一致"。
    bad = conclusion_consistency_reading(conclusion="x", confidence="很高")
    assert bad["checked"] is False and "没查成" in bad["reason"], bad


def test_research_carries_the_s09_reading(tmp_path: pathlib.Path) -> None:
    """`research` 的返回值里真的有 S-09 那一格（不是只活在测试里的判据）。

    反真空：这一格必须是 `research` 现算的 —— 把 `_support` 的判据打桩成恒
    `checked=False`，返回值也得跟着变（证明它读的是那一处，不是抄了一份常量）。
    """
    from agentflow.agent_d import _support as support
    from agentflow.agent_d import AgentD
    from agentflow.store import Store

    st = Store(tmp_path / "ws")
    st.init()
    d = AgentD(st)
    qid = str(d.propose_question(question="探针：这条问题有没有证据支撑？",
                                 kind="gap", priority="medium").get("question_id") or "")
    assert qid, "propose_question 没给出 qid"
    got = d.research(qid)
    reading = dict(got.get("conclusion_consistency") or {})
    assert reading.get("checked") is True, (
        f"S-09 的读数没有真的算出来（D 的 confidence 是档名）：{reading}")
    assert reading.get("verdict") in ("consistent", "overstated", "understated"), reading

    real = support.conclusion_consistency_reading

    def _stub(**_kw):
        return {"checked": False, "verdict": "", "reason": "打桩"}

    try:
        support.conclusion_consistency_reading = _stub
        # `research` 在导入期 from-import 了这个名字 ⇒ 直接换模块属性不会影响它；
        # 这一条因此钉 `research` 模块自己的绑定，证明它读的就是那一处。
        from agentflow.agent_d import research as _research_mod

        _research_mod.conclusion_consistency_reading = _stub
        d2 = AgentD(st)
        got2 = d2.research(qid)
        assert dict(got2.get("conclusion_consistency") or {}).get("reason") == "打桩", (
            "把 S-09 的判据打桩之后 `research` 的读数没变 ⇒ 那一格不是现算的")
    finally:
        support.conclusion_consistency_reading = real
        from agentflow.agent_d import research as _research_mod

        _research_mod.conclusion_consistency_reading = real

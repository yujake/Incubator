# -*- coding: utf-8 -*-
"""F 的交差读数按条读（业主 2026-11-02 原话，`draft/179` §二之三）。

| # | 造什么 | 期望 |
|---|---|---|
| a | F 产出 「3 条成果、其中 1 条有签」 | `signed_count=1` / `coverage=1/3`；`delivered` 假 —— 不许判成交差完成 |
| b | 3 条全签 | `coverage=1/1`（`coverage_reading=3/3`）；判「全签交差」 |
| d | 反真空：把「逐条」打桩回单一的 `delivered` | a 的那组断言必须红 |

改前红：`AgentF.delivery_reading` 不存在；`F.step` 的交差读数只有
`delivered` + `delivery_state` 两格，且读的是「这一轮那一份」（三条只签一条也读成
`delivered=True`）。

零模型调用：三条成果走真的 `_apply_round`（proof 档）落进 `statements`，
签由生产的写口 `vsigns.write_manuscript_sign` 盖在「已发布的那份手稿」上。

## 2026-11-10：夹具跟上「F 只认稿号」

业主裁定之后稿名只按 F 自己的稿号（`reports/f-proof-<稿号>.md`），与命题号不再绑定；
B 收录时把稿号记在 statements 行的 `manuscript_id` 格上（
`secretary.STATEMENT_LAND_OPS["attach_proofs"]`），而读侧（`AgentF._output_body`）
只按这一格回找那份稿。本文件的夹具是直接铺行的（绕开 B 的收录），所以这两件
"收录回执"要自己补上：`_record_manuscript` 记稿号、`_sign` 按稿号取那份稿再签。

改的是夹具，不是断言：期望值（1/3、3/3、逐条点名）一个字没动。改前那版夹具把签盖在
`reports/f-proof-<命题号>.md` 上 —— 那个名字现在是上一轮发的那份稿（第 1 条成果
的发布稿是 `f-proof-000001.md`、第 2 条是 `f-proof-000003.md`），于是第 2、3 条读到
的是别人的正文：签读到 0/少一不是读签漏签，是夹具盖错了稿。
"""
from __future__ import annotations

import json
import pathlib

import pytest
from conftest import seed_statement_row
from agentflow import depsection as _DS
from agentflow import manuscriptids as _MID
from agentflow import verifications as VR
from agentflow import vsigns as VS
from agentflow.agent_f import AgentF
from agentflow.store import Store

from _credential_fixture import issue_credential

AT = "2026-11-02T10:00:00+08:00"


class _FSecretary:
    """F 的秘书替身：洗稿照过（`_apply_round` 的 proof 分支要求它这一遍核得过）。"""

    actor = "fake-F-secretary"
    seam = object()

    def wash_dependency_face(self, text: str, **_kw) -> dict:
        return {"checked": True, "text": str(text), "actor": self.actor,
                "washed": False, "deps_refused": "", "deps_refused_findings": [],
                "deps_section_filled": "", "deps_washing": [],
                "reason": "夹具：依赖面本来就合规"}

    def judge_proposition_form(self, **_kw) -> dict:
        """2026-11-07（业主裁定）：交稿之前那道命题形态闸。夹具的命题是规范的。"""
        return {"checked": True, "well_formed": True,
                "conditions": "夹具：前提", "conclusion": "夹具：结论",
                "problems": [], "decision": "夹具：形态合规",
                "refused": "", "reason": "夹具：形态合规"}


def _ws(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _f(st: Store) -> AgentF:
    f = AgentF(st, config={"workspace_root": str(st.root), "plan_id": "0000"})
    f.f_secretary = _FSecretary()
    return f


def _plan() -> dict:
    return {"plan_id": "0000", "problem": "判定一个族的存在性", "problem_key": "PK-179",
            "rounds": 0, "history": [], "status": "open", "depth": 0,
            "best_partial": "", "created_at": AT, "updated_at": AT,
            "budget": {"max_rounds": 12, "max_parallel_subgoals": 3,
                       "max_persist_attempts": 1, "max_depth": 1},
            "subgoals": [
                {"sid": "s1", "text": "证明引理 A", "owner": "F", "status": "in_progress",
                 "evidence_ids": [], "experiment_ids": [], "blocked_reason": "",
                 "attempts": 1, "negation_kind": None},
                {"sid": "s2", "text": "证明引理 B", "owner": "F", "status": "in_progress",
                 "evidence_ids": [], "experiment_ids": [], "blocked_reason": "",
                 "attempts": 1, "negation_kind": None},
                {"sid": "s3", "text": "证明引理 C", "owner": "F", "status": "in_progress",
                 "evidence_ids": [], "experiment_ids": [], "blocked_reason": "",
                 "attempts": 1, "negation_kind": None},
            ]}


def _proof_round(f: AgentF, plan: dict, *, sid: str, text: str) -> dict:
    """走一次 `_apply_round` 的 proof 档，并把这一轮的 history 行补进计划（同 `step.py`）。

    准入闸 strict 之后，一条"还没签的成果"不能再由这一次登记「造出来」（无签正文
    整笔拒）。所以夹具先把这一份稿渲染出来（`proof_manuscript`，交给 B 的就是它），
    再直接铺一行 statements（真机 3134 行 own_result 的历史形态）—— 行上的 canonical
    与这一笔逐字相同 ⇒ 闸不适用（没有要写的新正文），`_apply_round` 照旧把稿发布。
    期望值一个字没改。
    """
    sg = next(dict(s) for s in plan["subgoals"] if s["sid"] == sid)
    product = {"product": "proof", "strategy": "direct", "why_strategy": "直接按定义",
               "steps": [{"n": 1, "text": f"{text}：取 ε>0，按定义逐点验证。", "cites": [],
                          "assumption": False},
                         {"n": 2, "text": "ε 任意 ⇒ 结论成立。", "cites": []}]}
    manuscript = f.proof_manuscript(product, sg=sg, plan=plan)
    body = _DS.proof_body(str(manuscript.get("text") or "")).strip("\n")
    full = str(sg.get("text") or "")
    if str(sg.get("testable") or ""):
        full += f"；这一条的可检验形式：{sg.get('testable')}"
    existing = next((dict(r) for r in f.store.rows("statements")
                     if str(r.get("statement_full") or "").strip() == full.strip()), None)
    if existing is not None:
        seeded = existing
    else:
        seeded = seed_statement_row(
            f.store, proof_text=body, statement_full=full,
            statement_text=str(sg.get("text") or ""), kind="conjecture",
            label=f"F 攻坚 {plan.get('plan_id') or ''} 子目标 {sid}",
            quote_reason="F 交来的论证，V 还没签（历史形态：直接铺行）")
    deploy = f._apply_round(product, sg, plan=plan, owner="F")
    assert str(deploy.get("statement_id") or "") == str(seeded["stmt_id"]), deploy
    _record_manuscript(f.store, str(seeded["stmt_id"]), deploy)
    plan["history"].append({"round": len(plan["history"]) + 1, "sid": sid,
                            "action": deploy.get("action"),
                            "outcome": deploy.get("outcome"),
                            "detail": deploy.get("detail"),
                            "evidence": list(deploy.get("evidence") or []),
                            "statement_id": str(deploy.get("statement_id") or ""),
                            # 2026-11-10：稿号与落点要进 history（同 `step.py`）——
                            # 改同一份稿沿用同一个稿号，靠的就是这两格。
                            "manuscript_id": str(deploy.get("manuscript_id") or ""),
                            "manuscript_path": str(deploy.get("manuscript_path") or ""),
                            "at": AT})
    plan["rounds"] = len(plan["history"])
    return deploy


def _record_manuscript(store: Store, sid: str, deploy: dict) -> None:
    """把「这一条成果落在哪一份稿上」记进 statements 行 —— B 收录回执的同形那两格。

    `manuscript_id` 是读侧的唯一回找口（`AgentF._output_body`）：没有它就只能退到旧
    约定名 `reports/f-proof-<命题号>.md`，而 2026-11-10 之后那个名字指不到这一条成果
    的稿。夹具直接铺行（绕开 B 的收录）⇒ 这两格要自己补，与 `attach_proofs` 同形。
    """
    mid = str(deploy.get("manuscript_id") or "")
    rel = str(deploy.get("manuscript_path") or "")
    assert mid and rel, deploy
    row = next(dict(r) for r in store.rows("statements")
               if str(r.get("stmt_id")) == str(sid))
    row.update(manuscript_id=mid, manuscript_path=rel)
    with store.tx("statements", actor="secretary-B") as tx:
        tx.upsert("statements", row)


def _manuscript_rel(st: Store, sid: str) -> str:
    """这一条成果的那份稿（行上 `manuscript_id` → 落点）—— 读侧同一个回找口。"""
    row = next((dict(r) for r in st.rows("statements")
                if str(r.get("stmt_id")) == str(sid)), {})
    mid = str(row.get("manuscript_id") or "")
    assert mid, f"夹具：stmt:{sid} 行上没有 manuscript_id（B 收录回执那一格）"
    rel = str(_MID.canonical_rel(mid))
    assert rel, mid
    return rel


def _sign(st: Store, sid: str) -> None:
    """V 在「这一条成果的那份已发布手稿」上签（D268 批 2：三票同源 + 发签，块当视图）。

    2026-11-10：稿名只按 F 自己的稿号，所以签的落点从 statements 行的 `manuscript_id`
    取（与读侧的 `_output_body` 同一个回找口），不再按命题号拼一个名字。
    """
    rel = _manuscript_rel(st, sid)
    path = pathlib.Path(st.root) / rel
    assert path.is_file(), f"手稿没发布：{rel}"
    body = _DS.proof_body(path.read_text(encoding="utf-8")).strip("\n")
    issue_credential(st.root, proof_text=body, statement_id=sid, manuscript=rel)
    wrote = VS.write_manuscript_sign(
        st.root, rel, proof_sha=VS._sign_sha(body), streak=3, need=3,
        verdict="成立", signer="V", at=AT,
        ledger=f"verifications/{sid}.jsonl#v-000003",
        statement_id=sid, signed=True)
    assert wrote.get("written") is True, wrote


def _three_outputs(st: Store, tmp_path: pathlib.Path) -> tuple[AgentF, dict, list[str]]:
    """F 交三条成果（三个在册命题、三份发布的手稿），一条都不签。"""
    f = _f(st)
    plan = _plan()
    sids: list[str] = []
    for sid, text in (("s1", "引理 A"), ("s2", "引理 B"), ("s3", "引理 C")):
        deploy = _proof_round(f, plan, sid=sid, text=text)
        got = str(deploy.get("statement_id") or "")
        assert got, deploy
        sids.append(got)
    # 三条必须是三个不同的命题号（否则下面数的就不是「三条成果」）
    assert len(set(sids)) == 3, sids
    return f, plan, sids


# ============================================================ a：3 条成果、1 条有签
def _assert_a(reading: dict) -> None:
    """a 的断言（d 的反真空也走它 —— 换一条读数进来，它必须咬得住）。"""
    assert reading.get("total") == 3, reading
    assert reading.get("signed_count") == 1, reading
    assert reading.get("pending_count") == 2, reading
    assert reading.get("unsigned_count") == 0, reading
    assert reading.get("coverage") == "1/3", reading
    assert reading.get("coverage_reading") == "1/3", reading
    assert reading.get("coverage_ratio") == pytest.approx(1 / 3, abs=1e-3), reading
    assert reading.get("state") == "outputs_unsigned", reading
    # 关键：1/3 不许读成「交差完成」
    assert reading.get("delivered") is False, reading


def test_a_one_of_three_signed_is_not_a_delivery(tmp_path):
    """a 造「3 条成果、其中 1 条有签」⇒ 1/3，且不许判成交差完成。

    改前红：`AgentF.delivery_reading` 不存在；旧的单一 `delivered` 会在那一条签上时
    读成 `True` —— 那个读数把「有一条签了」当成了「交差完成」。
    """
    st = _ws(tmp_path)
    f, plan, sids = _three_outputs(st, tmp_path)
    _sign(st, sids[0])

    reading = f.delivery_reading(plan)
    _assert_a(reading)
    # 逐条：一条已签、两条待签，各自点名（读数不是只有一个汇总数）
    by_sid = {str(o.get("statement_id")): o for o in reading["outputs"]}
    assert by_sid[sids[0]]["signed"] is True, by_sid[sids[0]]
    for sid in sids[1:]:
        assert by_sid[sid]["signed"] is False, by_sid[sid]
        assert by_sid[sid]["state"] == "waiting", by_sid[sid]
        # 2026-11-10：稿名只按 F 的稿号（`f-proof-<稿号>.md`），不再与命题号绑定 ——
        # 逐条点名的仍是「这一条自己的那份稿」，名字由行上的 `manuscript_id` 决定。
        want = _manuscript_rel(st, sid)
        assert by_sid[sid]["manuscript"] == want, by_sid[sid]
        assert (pathlib.Path(st.root) / want).is_file(), want
    # 三条成果各自落在各自的那份稿上（不是同一个名字被读三遍）。
    assert len({str(by_sid[sid]["manuscript"]) for sid in sids}) == 3, by_sid


# ============================================================ b：3 条全签
def test_b_three_of_three_signed_reads_as_full_coverage(tmp_path):
    """b 造「3 条全签」⇒ `coverage=1/1`，判「全签交差」。

    改前红：`coverage` 这一格不存在（改前的读数只有 `delivered`）。
    """
    st = _ws(tmp_path)
    f, plan, sids = _three_outputs(st, tmp_path)
    for sid in sids:
        _sign(st, sid)

    reading = f.delivery_reading(plan)
    assert reading.get("total") == 3, reading
    assert reading.get("signed_count") == 3, reading
    assert reading.get("pending_count") == 0, reading
    assert reading.get("unsigned_count") == 0, reading
    # 3/3 的最简分数是 1/1（覆盖率 = 1），原样读数在 coverage_reading 里
    assert reading.get("coverage") == "1/1", reading
    assert reading.get("coverage_reading") == "3/3", reading
    assert reading.get("coverage_ratio") == 1.0, reading
    assert reading.get("state") == "signed_all", reading
    assert reading.get("delivered") is True, reading


def test_b2_zero_signed_is_not_read_as_one_output():
    """0 条已签照实写 `0/N`（0 没有可约的东西）：`0/2` 不许读成「只有 1 条」。"""
    from agentflow.agent_f import delivery as FD

    assert FD.coverage_of(0, 2)["coverage"] == "0/2", FD.coverage_of(0, 2)
    assert FD.coverage_of(0, 5)["coverage"] == "0/5", FD.coverage_of(0, 5)
    assert FD.coverage_of(1, 3)["coverage"] == "1/3"
    assert FD.coverage_of(3, 3)["coverage"] == "1/1"
    assert FD.coverage_of(2, 4)["coverage"] == "1/2"


# ============================================================ d：反真空
def test_d_stubbing_back_to_a_single_delivered_turns_a_red(tmp_path, monkeypatch):
    """d 反真空：把「逐条」打桩回改前的单一 `delivered` ⇒ a 那组断言必须红。

    打桩的是读数本体（`AgentF._delivery_reading`），不是断言：若 `_assert_a`
    对这种"只有一个 delivered 布尔"的读数仍然通过，那它测的就不是「逐条」。
    """
    st = _ws(tmp_path)
    f, plan, sids = _three_outputs(st, tmp_path)
    _sign(st, sids[0])

    def _legacy(_self, plan_row, **_kw):        # 改前：这一轮那一份签了 = delivered
        return {"checked": True, "delivered": True, "delivery_state": "signed",
                "delivery_label": "已签", "outputs": [],
                "why": "改前口径：这一轮那一份有签 ⇒ delivered=True（没有逐条这一格）"}

    monkeypatch.setattr(AgentF, "_delivery_reading", _legacy)
    legacy = f.delivery_reading(plan)
    assert legacy.get("delivered") is True, legacy          # 改前确实会读成交差完成
    with pytest.raises(AssertionError):
        _assert_a(legacy)


# ============================================================ ② 那一趟的读数也是逐条的
def test_e_the_step_cell_is_the_plan_level_reading_not_this_rounds(tmp_path):
    """② `F.step` 交回来的 `delivered` 必须是「整个任务」的读数，不是这一轮那一份。

    造法：三条成果、只签了第三条；再交一轮「就是那一条」（改稿重交同一份）⇒
    这一轮那一份有签，但整个任务只有 1/3 —— 读数不许读成交差完成。

    改前红：`_apply_round` 的 `delivered` 只看这一轮的 `v_sign` ⇒ 这里会读成 True。

    2026-11-11（业主裁定 ②，本条的第二个判据）：那一轮重交的是已拿签的那一份 ⇒
    它现在受控拒（`manuscript_frozen`，改法指向 `B.open_polish_copy`），盘上那一份
    一个字节都不动；但交差读数照给 —— 所以下面那几格 plan 级读数一个字都不用改。
    """
    st = _ws(tmp_path)
    f, plan, sids = _three_outputs(st, tmp_path)
    _sign(st, sids[2])
    frozen_rel = _manuscript_rel(st, sids[2])
    frozen_before = (pathlib.Path(st.root) / frozen_rel).read_text(encoding="utf-8")
    deploy = _proof_round(f, plan, sid="s3", text="引理 C")

    assert deploy.get("delivered") is False, deploy
    agg = dict(deploy.get("delivery") or {})
    assert agg.get("checked") is True, agg
    assert agg.get("total") == 3, agg
    assert agg.get("signed_count") == 1, agg
    assert agg.get("pending_count") == 2, agg
    assert agg.get("coverage") == "1/3", agg
    # 这一轮那一份确实是已签的（逐条读数不是把签读丢了）
    assert bool((deploy.get("v_sign") or {}).get("reading", {}).get("delivered")) is True, deploy
    # 交差说明里逐条点名了「1/3」与未签的条数
    detail = str(deploy.get("detail") or "")
    assert "1/3" in detail and "待签 2" in detail, detail
    # ---- 2026-11-11（业主裁定 ②）：重交同一份「已拿签」的稿现在受控拒 ------------
    #
    # 业主逐字：「稿通过后相当于这个命题证完了，后续只对稿允许有只读权」；改法只有一条
    # ——「要改就开 B 的优化副本」。所以这一轮不再是"又一次落稿"，而是一次受控拒。
    assert deploy.get("action") == "no_change", deploy
    refusal = dict(deploy.get("refusal") or {})
    assert refusal.get("kind") == "manuscript_frozen", deploy
    assert "open_polish_copy" in str(refusal.get("next_step") or ""), refusal
    assert "拿签" in detail, detail
    # 盘上那一份一个字节都没动（冻结是"只读"，不是"改一半"）
    assert (pathlib.Path(st.root) / frozen_rel).read_text(
        encoding="utf-8") == frozen_before


class _FakeLLM:
    """最小模型缝（`judge.judge_json` 的调用约定）：每次调用都记下提示词。"""

    def __init__(self, *replies: str) -> None:
        self.replies = list(replies)
        self.prompts: list[str] = []

    def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if not self.replies:
            raise AssertionError("模型被调用的次数比剧本多")
        return self.replies.pop(0)


def _proof_reply() -> str:
    """一份不引 id 的 proof 产物（显式前提 ⇒ 不会被 R-03 拒收）。"""
    return json.dumps({"product": "proof", "strategy": "套用已知定理",
                       "why_strategy": "直接按定义",
                       "steps": [{"text": "设命题成立（本轮前提）", "assumption": True}]},
                      ensure_ascii=False)


def test_f_a_signed_output_does_not_end_the_plan(tmp_path):
    """② 一条成果拿到签之后，计划不许因此收工（没有「签到手就结束」这条路）。

    判据走真的 `step`：一个两条子目标的计划先交两条成果、只签了第一条；
    再 `step` 一次必须仍能推进（`action` 不是 `stop`、计划不在终态），
    而且读数仍是 1/2 —— 一条签到手不等于交差。
    """
    st = _ws(tmp_path)
    f = _f(st)
    # 2026-11-07（业主裁定：登记与写证明解耦）：`step` 再跑一轮会重写 s1 的手稿，
    # 而重写会换掉正文 sha ⇒ 盖在旧正文上的那一签按设计作废（V 台账按新 sha 另落一行）。
    # 所以这一条要验的"签到手不等于交差"必须让这一轮的正文与已签的那一份逐字相同
    # （同一份正文 ⇒ 同一个 sha ⇒ 签仍然成立），其余读数一个字不改。
    f.llm = _FakeLLM(json.dumps({
        "product": "proof", "strategy": "套用已知定理", "why_strategy": "直接按定义",
        "steps": [{"n": 1, "text": "引理 A：取 ε>0，按定义逐点验证。", "cites": [],
                   "assumption": False},
                  {"n": 2, "text": "ε 任意 ⇒ 结论成立。", "cites": []}]},
        ensure_ascii=False))
    pid = f.create_plan("难题：判定这个族", "PK-179-NOSTOP", subgoals=[
        {"sid": "s1", "text": "证明引理 A", "owner": "F", "testable": "存在反例或有限界"},
        {"sid": "s2", "text": "证明引理 B", "owner": "F", "testable": "存在反例或有限界"},
    ])["plan_id"]
    row = next(dict(r) for r in st.rows("attack_plans")
               if str(r.get("plan_id")) == str(pid))
    sids: list[str] = []
    for sg, text in (("s1", "引理 A"), ("s2", "引理 B")):
        deploy = _proof_round(f, row, sid=sg, text=text)
        got = str(deploy.get("statement_id") or "")
        assert got, deploy
        sids.append(got)
    f._write_plan(row, note="test:two_outputs")
    _sign(st, sids[0])

    after = f.step(pid)
    assert after.get("action") != "stop", after
    assert str(after.get("status")) not in ("resolved", "stalled",
                                            "supported_not_proved"), after
    agg = dict(after.get("delivery") or {})
    assert agg.get("total") == 2, agg
    assert agg.get("signed_count") == 1, agg
    assert agg.get("delivered") is False, agg
    assert agg.get("state") == "outputs_unsigned", agg


def test_g_the_round_prompt_asks_for_the_three_self_assessment_tiers(tmp_path):
    """② 三条自评判据进提示词（F 自己判，框架不替它判）。"""
    st = _ws(tmp_path)
    llm = _FakeLLM(_proof_reply())
    f = _f(st)
    f.llm = llm
    pid = f.create_plan("难题：判定这个族", "PK-179-SELF", subgoals=[
        {"sid": "s1", "text": "证明引理 A", "owner": "F", "testable": "存在反例或有限界"},
    ])["plan_id"]
    f.step(pid)
    prompt = llm.prompts[0]
    assert "self_assessment" in prompt, prompt[-1200:]
    for criterion in ("comprehensive", "enough_output", "partial_output"):
        assert criterion in prompt, (criterion, prompt[-1200:])
    assert "不要因为一条拿到签就收工" in prompt, prompt[-1200:]
    assert "合法的收工理由" in prompt, prompt[-1200:]


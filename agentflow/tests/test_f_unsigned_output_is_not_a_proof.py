# -*- coding: utf-8 -*-
"""① 无签不许叫「证明」（业主 2026-11-02 原话）。

    如果某命题无V签，F侧就不能声称自己产出了"证明"

所以 F 的产出统计里，一条成果只有在「拿到 V 签」之后才算 `proof`；没签的只能读成
受控词 `proof_unsigned`（待签）或 `draft`（V 判过没过 / 没查成），「不计入产出的证明数」。

| # | 造什么 | 期望 |
|---|---|---|
| a | 有正文、无签 | `claim=proof_unsigned` / `proof_count=0`（不算证明） |
| b | 有正文、有签 | `claim=proof` / `proof_count=1`（算证明） |
| c | 反真空：把这条判据摘掉（打桩成恒 `proof`） | a 必须红 |

零模型调用：三条成果走真的 `_apply_round`（proof 档）落进 `statements`；
签由生产的写口 `vsigns.write_manuscript_sign` 盖在已发布的那份手稿上。
"""
from __future__ import annotations

import pathlib

import pytest
from conftest import seed_statement_row
from agentflow import depsection as _DS
from agentflow import verifications as VR
from agentflow import vsigns as VS
from agentflow.agent_f import AgentF
from agentflow.agent_f import delivery as FD
from agentflow.store import Store

AT = "2026-11-02T10:00:00+08:00"


class _FSecretary:
    actor = "fake-F-secretary"
    seam = object()

    def wash_dependency_face(self, text: str, **_kw) -> dict:
        return {"checked": True, "text": str(text), "actor": self.actor,
                "washed": False, "deps_refused": "", "deps_refused_findings": [],
                "deps_section_filled": "", "deps_washing": [],
                "reason": "夹具：依赖面本来就合规"}


def _ws(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _f(st: Store) -> AgentF:
    f = AgentF(st, config={"workspace_root": str(st.root), "plan_id": "0000"})
    f.f_secretary = _FSecretary()
    return f


def _plan() -> dict:
    return {"plan_id": "0000", "problem": "判定一个族的存在性", "problem_key": "PK-179-P",
            "rounds": 0, "history": [], "status": "open", "depth": 0,
            "best_partial": "", "created_at": AT, "updated_at": AT,
            "budget": {"max_rounds": 12, "max_parallel_subgoals": 3,
                       "max_persist_attempts": 1, "max_depth": 1},
            "subgoals": [{"sid": "s1", "text": "证明引理 A", "owner": "F",
                          "status": "in_progress", "evidence_ids": [],
                          "experiment_ids": [], "blocked_reason": "",
                          "attempts": 1, "negation_kind": None}]}


def _one_output(st: Store) -> tuple[AgentF, dict, str]:
    """一条"有正文、还没签"的成果（直接铺行造历史形态）。

    准入闸 strict 之后 `_apply_round` 写不进无签的证明正文（整笔拒
    `proof_without_v_sign`）—— 这一组测的是"无签成果被读成什么"，现场因此改成
    直接铺一行 statements（真机 3134 行 own_result 的历史形态）＋按约定路径落一份
    手稿（`_sign` 要在它上面盖签块，所以正文必须与行上的 proof_text 逐字相同）。
    改的是"怎么造现场"，不是期望值。
    """
    f = _f(st)
    plan = _plan()
    body = _proof_body()
    # `_plan()` 的子目标没有 `testable` ⇒ F 的 full 就是子目标原文（与 `_proof_outlet`
    # 的拼法一致；full 对不上会让 B 以为这是一条新命题、从而撞上准入闸）。
    full = "证明引理 A"
    seeded = seed_statement_row(
        st, proof_text=body, statement_full=full, statement_text="证明引理 A",
        kind="conjecture", label="F 攻坚 0000 子目标 s1",
        quote_reason="F 交来的论证，V 还没签（历史形态：直接铺行）")
    sid = str(seeded["stmt_id"])
    # 手稿由 F 自己的渲染写（签块的落点与真机同形）；这一笔登记与在册正文逐字相同
    # ⇒ 准入闸不适用（没有要写的新正文），照旧把稿按命号发布。
    sg = dict(plan["subgoals"][0])
    deploy = f._apply_round(_proof_product(), sg, plan=plan, owner="F")
    assert str(deploy.get("statement_id") or "") == sid, deploy
    plan["history"].append({"round": 1, "sid": "s1", "action": "proof",
                            "outcome": "progress", "detail": "", "evidence": [],
                            "statement_id": sid, "at": AT})
    plan["rounds"] = 1
    return f, plan, sid


def _proof_body() -> str:
    """`_proof_product` 交给 B 的那一份正文（`agent_f._proof_outlet` 的拼法）。"""
    return "1. 取 δ=ε，按定义逐点验证。（前提）"


def _proof_product() -> dict:
    return {"product": "proof", "strategy": "套用已知定理",
            "why_strategy": "直接按定义",
            "steps": [{"n": 1, "text": "取 δ=ε，按定义逐点验证。", "cites": [],
                       "assumption": False}]}


def _sign(st: Store, sid: str) -> None:
    rel = f"reports/f-proof-{sid}.md"
    path = pathlib.Path(st.root) / rel
    body = _DS.proof_body(path.read_text(encoding="utf-8")).strip("\n")
    wrote = VS.write_manuscript_sign(
        st.root, rel, proof_sha=VR.proof_sha(body), streak=3, need=3,
        verdict="成立", signer="V", at=AT, ledger=f"{rel}#V签",
        statement_id=sid, signed=True)
    assert wrote.get("written") is True, wrote


# ============================================================ a：有正文、无签
def _assert_unsigned_is_not_a_proof(reading: dict) -> None:
    assert reading.get("total") == 1, reading
    assert reading.get("signed_count") == 0, reading
    item = dict((reading.get("outputs") or [{}])[0])
    assert item.get("claim") == "proof_unsigned", item
    assert item.get("claim_label") == "待签（还没 V 签，不算证明）", item
    # 关键：不签就不许计入「产出的证明数」
    assert reading.get("proof_count") == 0, reading
    assert reading.get("proof_statements") == [], reading
    assert reading.get("draft_count") == 1, reading


def test_a_an_output_without_a_sign_is_not_a_proof(tmp_path):
    """a 造「有正文、无签」⇒ 读数里它是 `proof_unsigned`，证明数为 0。

    改前红：`claim` / `proof_count` 不存在；无签的正文在读数上与证明没有区别。
    """
    st = _ws(tmp_path)
    f, plan, sid = _one_output(st)
    reading = f.delivery_reading(plan)
    _assert_unsigned_is_not_a_proof(reading)


# ============================================================ b：有正文、有签
def test_b_a_signed_output_is_the_only_thing_counted_as_proof(tmp_path):
    """b 造「有正文、有签」⇒ `claim=proof`，证明数 = 1。"""
    st = _ws(tmp_path)
    f, plan, sid = _one_output(st)
    _sign(st, sid)
    reading = f.delivery_reading(plan)
    assert reading.get("total") == 1, reading
    assert reading.get("signed_count") == 1, reading
    item = dict((reading.get("outputs") or [{}])[0])
    assert item.get("claim") == "proof", item
    assert item.get("claim_label") == "证明（有 V 签）", item
    assert reading.get("proof_count") == 1, reading
    assert reading.get("proof_statements") == [sid], reading
    assert reading.get("draft_count") == 0, reading


# ============================================================ c：反真空
def test_c_stubbing_the_claim_back_to_always_proof_turns_a_red(tmp_path, monkeypatch):
    """c 反真空：把「无签不叫证明」这条判据摘掉（`claim_of` 恒返回 `proof`）⇒ a 必须红。

    摘的是判据本体，不是断言：若打桩之后 a 那组断言仍然通过，它测的就不是这一条。
    """
    st = _ws(tmp_path)
    f, plan, sid = _one_output(st)
    monkeypatch.setattr(FD, "claim_of", lambda *_a, **_k: "proof")
    reading = f.delivery_reading(plan)
    assert reading.get("proof_count") == 1, reading       # 摘掉判据后真的数成 1 条证明
    with pytest.raises(AssertionError):
        _assert_unsigned_is_not_a_proof(reading)


def test_d_the_controlled_vocabulary_is_three_values():
    """受控词表：`proof` / `proof_unsigned` / `draft` 三档，标签与档位一一对上。"""
    assert FD.OUTPUT_CLAIMS == ("proof", "proof_unsigned", "draft")
    for claim in FD.OUTPUT_CLAIMS:
        assert FD.CLAIM_LABELS.get(claim), claim
    # 反真空：受控词表不是空的、也不是单值
    assert len(set(FD.OUTPUT_CLAIMS)) == 3


def test_e_the_step_cell_carries_the_same_proof_count(tmp_path):
    """`F.step` 的返回值里也有 `proof_count`（产出统计只在读数一处定义）。"""
    st = _ws(tmp_path)
    f, plan, sid = _one_output(st)
    sg = dict(plan["subgoals"][0])
    first = f._apply_round(_proof_product(), sg, plan=plan, owner="F")
    assert str(first.get("statement_id") or "") == sid, first
    assert first.get("proof_count") == 0, first
    assert first.get("draft_count") == 1, first
    _sign(st, sid)
    second = f._apply_round(_proof_product(), sg, plan=plan, owner="F")
    assert str(second.get("statement_id") or "") == sid, second
    assert second.get("proof_count") == 1, second
    assert second.get("proof_statements") == [sid], second

# -*- coding: utf-8 -*-
"""F 的交差要有 V 签（业主 2026-11-02 逐字：「重点是要F侧拿V签，拿到V签F才能交差」）。

## 这一组守什么

改前：`F -> V` 那条边一直在（`capabilities.ALLOWED_EDGES["F"]` 含 `"V"`），
`agent_skills` 也一直教 F「你产出的证明由你派 V 签」，而 `agent_f` 的实现交完
B 的登记就结束了 —— 没有一处回读签。于是 F 的 `step` 无论签没签都回
`outcome=progress`，读数里根本没有「签」这一格。83 的定格现场就是它：
F 写的五份证明一份都没签（`out/vsigns/` 只有 000005 一份）。

改后：`agent_f/vsign.py` 只做一件事 —— 回读签（四档）；`F.step` 的返回值与
history 里带这一格，`delivered` 只在「已签」时为真。送审不在这里做：
业主 2026-11-02 的第二句是「F 不是直接能派 V 吗」，所以派活是 F 自己的动作
（`framework_summon`），这一层只回答"现在有没有签"。

## 四条判据（先红后绿；红的样子写在每一条的 docstring 里）

| # | 造什么 | 期望 |
|---|---|---|
| a | 手稿上有一份盖住现行正文的签块 | 读数 = 已签；`delivered` 为真 |
| b | 有正文、没签（没送审） | 读数 = 待签；`delivered` 为假 |
| c | 手稿上的签块是 `已签=false；判词=有毛病` | 读数 = 未通过 |
| d | 反真空：删掉签块 / 签块盖的是另一版 | 读数必须回落 |

零模型调用：签块由 `vsigns.write_manuscript_sign`（生产的写口）造，不手写盘。
"""
from __future__ import annotations

import pathlib

import pytest
from conftest import seed_statement_row
from agentflow import depsection as _DS
from agentflow import verifications as VR
from agentflow import vsigns as VS
from agentflow.agent_f import AgentF
from agentflow.agent_f import vsign as FVS
from agentflow.store import Store

FULL = "设 f 在 [0,1] 上连续；则 f 在该区间上一致连续。"
MANUSCRIPT = ("# F 的证明手稿：一致连续\n\n"
              "- 命题号：stmt:（还没落号）\n"
              "- 计划：0000 · 子目标：s1\n\n"
              "## 命题\n\n"
              f"{FULL}\n\n"
              "## 证明\n\n"
              "1. 取 δ=ε：对任意 x,y∈[0,1]，|x-y|<δ ⇒ |f(x)-f(y)|<ε。\n"
              "2. 第 1 步的 δ 只依赖 ε、不依赖点 ⇒ 按定义即一致连续。\n\n"
              "## 依赖\n\n"
              "（这一份证明没有引用任何在册命题 —— 空表就是声明。）\n")
#: 被签正文 = 手稿里「## 证明」那一节（`vsigns.ARTIFACT_SHA_RULE` 的那把 sha）。
PROOF = _DS.proof_body(MANUSCRIPT).strip("\n")
REL = "reports/f-proof-plan-0000.md"


def _ws(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    path = pathlib.Path(st.root) / REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(MANUSCRIPT, encoding="utf-8")
    return st


def _stamp(st: Store, *, signed: bool = True, verdict: str = "成立",
           sha: str = "", rel: str = REL) -> dict:
    return VS.write_manuscript_sign(
        st.root, rel, proof_sha=sha or VR.text_sha(PROOF),
        streak=3 if signed else 0, need=3, verdict=verdict, signer="V",
        at="2026-11-02T10:00:00+08:00", ledger=f"{rel}#V签", statement_id="",
        signed=signed)


# ============================================================ a：已签
def test_a_a_sign_block_in_the_manuscript_reads_as_signed(tmp_path):
    """a 造「手稿上有签块」⇒ 读数 = 已签、`delivered` 为真。

    改前红：`agent_f.vsign` 不存在（`ImportError`），`F.step` 的返回值里也没有
    `v_sign` / `delivered` 这两格。
    """
    st = _ws(tmp_path)
    wrote = _stamp(st)
    assert wrote["written"] is True, wrote

    reading = FVS.delivery_reading(st.root, proof_text=PROOF, manuscript_paths=(REL,))
    assert reading["state"] == FVS.STATE_SIGNED, reading
    assert reading["label"] == "已签", reading
    assert reading["delivered"] is True, reading
    assert reading["channel"] == FVS.CHANNEL_MANUSCRIPT, reading


# ============================================================ b：待签
def test_b_a_proof_without_a_sign_reads_as_waiting(tmp_path):
    """b 造「有正文、没签」⇒ 待签，不许算交差；下一步明写"派 V"。"""
    st = _ws(tmp_path)
    reading = FVS.delivery_reading(st.root, proof_text=PROOF, manuscript_paths=(REL,))
    assert reading["state"] == FVS.STATE_WAITING, reading
    assert reading["label"] == "待签", reading
    assert reading["delivered"] is False, reading
    hint = FVS.next_step_hint(reading, manuscript_paths=(REL,))
    assert "派 V" in hint and "framework_summon" in hint, hint


# ============================================================ c：未通过
def test_c_a_rejected_block_reads_as_not_passed(tmp_path):
    """c 造「V 判过、没过」⇒ 未通过（不是待签、不是已签）。"""
    st = _ws(tmp_path)
    _stamp(st, signed=False, verdict="有毛病")
    reading = FVS.delivery_reading(st.root, proof_text=PROOF, manuscript_paths=(REL,))
    assert reading["state"] == FVS.STATE_REJECTED, reading
    assert reading["label"] == "未通过", reading
    assert reading["delivered"] is False, reading
    hint = FVS.next_step_hint(reading, manuscript_paths=(REL,))
    assert "改稿" in hint, hint


# ============================================================ d：反真空
def test_d1_deleting_the_block_falls_back_to_waiting(tmp_path):
    """d1 反真空：删掉手稿签块 ⇒ 回落成待签（读数真的在读盘，不是恒绿）。"""
    st = _ws(tmp_path)
    _stamp(st)
    assert FVS.delivery_reading(st.root, proof_text=PROOF,
                                manuscript_paths=(REL,))["state"] == FVS.STATE_SIGNED
    path = pathlib.Path(st.root) / REL
    text = path.read_text(encoding="utf-8")
    path.write_text("\n".join(ln for ln in text.split("\n")
                              if not ln.strip().startswith(VS.SIGN_MARK)),
                    encoding="utf-8")
    after = FVS.delivery_reading(st.root, proof_text=PROOF, manuscript_paths=(REL,))
    assert after["state"] == FVS.STATE_WAITING, after
    assert after["delivered"] is False, after


def test_d2_a_block_for_another_body_does_not_count(tmp_path):
    """d2 反真空：签块盖的是另一版正文 ⇒ 不算签（改过稿就要重签）。"""
    st = _ws(tmp_path)
    _stamp(st, sha=VR.text_sha(PROOF + "改一个字"))
    reading = FVS.delivery_reading(st.root, proof_text=PROOF, manuscript_paths=(REL,))
    assert reading["state"] != FVS.STATE_SIGNED, reading
    assert reading["delivered"] is False, reading


# ============================================================ F.step 的那一格

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


def _apply_one_proof_round(st: Store) -> dict:
    """走 `_apply_round` 的 proof 分支（不调模型：产物是直接给的）。

    准入闸 strict 之后，"这一份还没签"的现场不能再由这一次登记造出来（无签正文
    整笔拒）。夹具因此先把稿渲染出来（交给 B 的就是它），直接铺一行 statements
    （真机历史形态），再走 `_apply_round` 发布 —— 行上的 canonical 与这一笔逐字
    相同，闸不适用（没有要写的新正文）。期望值一个字没改。
    """
    f = AgentF(st, config={"workspace_root": str(st.root)})
    f.f_secretary = _FSecretary()
    plan = {"plan_id": "0000", "rounds": 0, "history": [], "subgoals": [],
            "budget": {"max_rounds": 9}, "status": "open"}
    sg = {"sid": "s1", "text": FULL, "owner": "F", "status": "in_progress"}
    product = {"product": "proof", "strategy": "direct",
               "steps": [{"n": 1, "text": "取 δ=ε，逐点验证。", "cites": [],
                          "assumption": False},
                         {"n": 2, "text": "δ 只依赖 ε ⇒ 一致连续。", "cites": []}],
               "best_partial": [], "why_strategy": "直接按定义"}
    manuscript = f.proof_manuscript(product, sg=sg, plan=plan)
    body = _DS.proof_body(str(manuscript.get("text") or "")).strip("\n")
    if not any(str(r.get("statement_full") or "").strip() == FULL.strip()
               for r in st.rows("statements")):
        seed_statement_row(
            st, proof_text=body, statement_full=FULL, statement_text=FULL,
            kind="conjecture", label=f"F 攻坚 0000 子目标 s1",
            quote_reason="F 交来的论证，V 还没签（历史形态：直接铺行）")
    return f._apply_round(product, sg, plan=plan, owner="F")


def test_the_step_cell_says_not_delivered_until_the_sign_is_on_disk(tmp_path):
    """F 的这一趟带「签」这一格：没签 ⇒ 没交差；签上 ⇒ 已签。

    改前红：`_apply_round` 的返回值里没有 `v_sign` / `delivered` 这两格
    （KeyError）—— 「这一趟交没交差」在读数上根本不存在。
    """
    st = _ws(tmp_path)
    first = _apply_one_proof_round(st)
    assert first.get("delivered") is False, first
    assert first.get("delivery_state") != FVS.STATE_SIGNED, first
    detail = str(first.get("detail") or "")
    assert "没签 ⇒ 这一趟不算交差" in detail, detail
    assert "派 V" in detail, detail
    sid = str(first.get("statement_id") or "")
    assert sid, first

    # V 落了签（生产的写口）⇒ 下一轮 step 读成已签（签块跟着稿走：publish 会搬它）。
    published = pathlib.Path(st.root) / f"reports/f-proof-{sid}.md"
    assert published.is_file(), published
    body_sha = VR.text_sha(_DS.proof_body(published.read_text(encoding="utf-8")).strip("\n"))
    VS.write_manuscript_sign(
        st.root, f"reports/f-proof-{sid}.md", proof_sha=body_sha,
        streak=3, need=3, verdict="成立", signer="V",
        at="2026-11-02T10:00:00+08:00",
        ledger=f"reports/f-proof-{sid}.md#V签", statement_id=sid, signed=True)
    second = _apply_one_proof_round(st)
    assert second.get("delivered") is True, second
    assert second.get("delivery_state") == FVS.STATE_SIGNED, second
    assert second.get("delivery_label") == "已签", second


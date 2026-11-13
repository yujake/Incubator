# -*- coding: utf-8 -*-
"""业主裁定 B：proof 档必须给 `product.proposition`，`## 命题` 只从它渲染。

## 为什么（真机 `projects/octahedron-20261113`，2026-11-13）

`reports/f-proof-000002.md` 的 `## 命题` 是一段修订说明（「按 V u-000005 的唯一缺陷
修订第 7 步…其余八步一字不动；同一份稿就地重写后重送 V」）—— 因为改前 `## 命题` 渲染的
是子目标正文（派给 F 的活）＋可检验形式。那段作业话被 V 签了、被 B 拒了（B 按
`## 命题` 取 `statement_full`）。

治位置（闸挪到写盘之前）是上一笔（`test_f_form_gate_precedes_the_write.py`）；
这一笔治来源：子目标正文不再有机会变成命题。业主的判据：

> 子目标写作业话时 `## 命题` 仍是定理陈述（或直接受控拒），且真机 f-proof-000002
> 那段的形态再也落不了盘。

## 判据

| 编号 | 判据 | 改前红在哪 |
|---|---|---|
| a | 作业话子目标 + `proposition`=定理陈述 ⇒ 稿上 `## 命题` 逐字 == 它、登记成功、闸判的就是它 | 改前 `## 命题` = 作业话 ⇒ 形态闸拒（真机形态） |
| b | 作业话子目标 + 缺 `proposition` ⇒ 受控拒 `proposition_missing`、0 字节、不发模型调用 | 改前会先问一次形态闸（拒的是 `proposition_form_refused`，且白花一次） |
| c | 反真空：把 `proposition_text` 换回"从子目标正文拼" ⇒ a 必红 | —— |
| d | `label` 不是命题；`testable` 不再进 `## 命题`（它是计划/子目标的验收口径） | 改前 `## 命题` 带着「；这一条的可检验形式：…」 |
| e | 真机 f-proof-000002 的作业话原文 ⇒ `proposition_missing`、盘上一个字节都没写 | 改前稿会落盘 |
| f | schema 一落地，代码层那张"暂认键"表就该空（p281 之后摘掉） | —— |
| g | 框架自己那一轮（`parse_round`）同样必填 `proposition`，缺 ⇒ `RoundError` 带 fix 文案 | 改前只认 `steps` |
"""
from __future__ import annotations

import json
import pathlib

from agentflow import attackround as AR
from agentflow import secretary as SEC
from agentflow.agent_f import core as FC
from agentflow.agent_f import manuscript as M
from agentflow.agent_f.core import AgentF
from agentflow.store import Store

TS = "2026-11-13T14:30:00+08:00"

#: 真机 `reports/f-proof-000002.md` 的 `## 命题` 那一节（逐字，311 字）—— 它是
#: 子目标正文（作业话）拼出来的，不是定理陈述。B 之后它只能作为 `proposition`
#: 被闸拒，永远不能作为 `## 命题` 落盘。
REVISION_NOTE = (
    "按 V u-000005 的唯一缺陷修订第 7 步：把「2|P_1| = 2/√(u²+v²)」改为"
    "「2|P_1| = 2√(u²+v²)/(u+v) = 2/(u+v)（用 u²+v² = 1）」，其余八步一字不动；"
    "同一份稿 reports/f-proof-000002.md 就地重写后重送 V。"
    "；这一条的可检验形式：V 对这一版正文（新 sha，与 b944298d… 不同）给出两态结论"
    "「成立」（零 finding），且稿上签块的正文 sha 与现行正文一致（v_sign 读数 = 已签）。"
    "判据：F.step 返回的 v_sign.label == '已签' 即为成立；"
    "若 V 仍判「有毛病」则本轮记为缺陷步号。"
)
#: 子目标正文那一半（作业话）。
TASK_TEXT = REVISION_NOTE.split("；这一条的可检验形式：", 1)[0]

#: 一条规范的定理陈述（业主给的那一条）。
POSITIVE = (
    "设 a = 1/√2，O = {(x,y,z) ∈ R³ : |x|+|y|+|z| ≤ a}；"
    "则任意平面与 O 的截面面积 ≤ 2a² = 1，"
    "等号当且仅当该平面垂直于某个坐标轴且过原点（此时截面是边长 1 的正方形）。"
)

#: 形态闸的模型答案（真机回放；见 `temp/w1_answers.json` 的两次真调用）。
ANSWER_NEGATIVE = {
    "checked": True, "well_formed": False,
    "conditions": "文本没有给出数学前提；它要求按 V u-000005 的唯一缺陷修订第 7 步。",
    "conclusion": "V 对本版新 sha 正文给出两态结论「成立」；按判据 v_sign.label == '已签' 记为成立。",
    "problems": ["没有写清数学前提与假设",
                 "结论不是可判真假的数学断言，而是验收/流程状态判定",
                 "整体是修订、重送和验收规格，不是「若…则…」式的数学命题结构",
                 "混入了作业/验收判据，如 v_sign.label == '已签'、重送 V、签块 sha 一致性"],
    "decision": "不合格：这是修订与验收流程要求，不是从条件导出数学结论的命题。",
    "refused": "proposition_form_refused",
    "reason": "形态不合规：4 条",
}
ANSWER_POSITIVE = {
    "checked": True, "well_formed": True,
    "conditions": "设 a = 1/√2，O = {(x,y,z) ∈ R³ : |x|+|y|+|z| ≤ a}。",
    "conclusion": "任意平面与 O 的截面面积 ≤ 2a² = 1，等号当且仅当…",
    "problems": [], "decision": "合格：前提与结论都写得出来。",
    "refused": "", "reason": "形态合规：前提与结论都读得出来",
}


class _ReplaySeam:
    """真机回放：材料里带 `statement_full`，按它选那一次真模型的答案。"""

    class _Call:
        ok = True
        problem = ""
        detail = ""
        text = ""
        model = "replay"
        prompt_version = "t"
        prompt_sha256 = "0" * 64

    def __init__(self, answers: dict[str, dict]) -> None:
        self.answers = dict(answers)
        self.calls: list[str] = []

    def ask_json(self, prompt: str, *, system: str = "", task_id: str = "",
                 note: str = ""):
        for key, answer in self.answers.items():
            if key in prompt:
                self.calls.append(key)
                return dict(answer), self._Call()
        raise AssertionError("回放表里没有这一段正文：\n" + str(prompt)[:600])


class _WashOnly:
    """秘书替身：只做依赖面那一遍（其余一概不碰）。"""

    role = "F"

    def wash_dependency_face(self, text: str, **_kw) -> dict:
        return {"checked": True, "text": str(text), "actor": self.role,
                "washed": False, "deps_refused": "", "deps_refused_findings": [],
                "deps_section_filled": "", "deps_washing": [],
                "reason": "夹具：依赖面本来就合规"}

    def judge_proposition_form(self, **_kw):
        raise AssertionError("这一条不该问形态闸（缺命题那一档在写盘之前就拒）")


def _ws(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _agent(st: Store, answers: dict[str, dict], *, secretary: object | None = None) -> AgentF:
    f = AgentF(st, config={"workspace_root": str(st.root), "plan_id": "0001"})
    if secretary is not None:
        f.f_secretary = secretary
    else:
        f.f_secretary = SEC.Secretary(
            "F", root=st.root, store=st, seam=_ReplaySeam(answers), enable_model=True)
    return f


def _plan(text: str = TASK_TEXT, *, testable: str = "") -> dict:
    sg = {"sid": "S4", "text": text, "owner": "F", "status": "in_progress",
          "evidence_ids": [], "experiment_ids": [], "blocked_reason": "",
          "attempts": 0, "negation_kind": None}
    if testable:
        sg["testable"] = testable
    return {"plan_id": "0001", "problem": "单位正八面体的最大截面", "problem_key": "PK-W1B",
            "rounds": 0, "history": [], "status": "open", "depth": 0,
            "best_partial": "", "created_at": TS, "updated_at": TS,
            "budget": {"max_rounds": 4, "max_parallel_subgoals": 2,
                       "max_persist_attempts": 2, "max_depth": 1},
            "subgoals": [sg]}


def _product(proposition: str | None = None, *, label: str = "") -> dict:
    product: dict = {
        "product": "proof", "strategy": "按定义", "why_strategy": "直接算截面",
        "steps": [{"n": 1, "text": "取 a=1 的八面体 O_1，按 n 的三个分量分两支。",
                   "cites": [], "assumption": True},
                  {"n": 2, "text": "由 Brunn 凹性，最大截面必过原点。",
                   "cites": [], "assumption": False}]}
    if proposition is not None:
        product["proposition"] = proposition
    if label:
        product["label"] = label
    return product


def _round(f: AgentF, *, plan: dict, product: dict) -> dict:
    return f._apply_round(product, plan["subgoals"][0], plan=plan, owner="F")


def _manuscripts(st: Store) -> list[pathlib.Path]:
    base = pathlib.Path(st.root) / "reports"
    return sorted(base.glob("f-proof-*.md")) if base.is_dir() else []


def _section(text: str, name: str) -> str:
    lines = str(text).splitlines()
    for i, line in enumerate(lines):
        if line.strip() == f"## {name}":
            out: list[str] = []
            for nxt in lines[i + 1:]:
                if nxt.startswith("## "):
                    break
                out.append(nxt)
            return "\n".join(out).strip()
    return ""


def _header_line(text: str, mark: str) -> str:
    for line in str(text).splitlines():
        if line.startswith(mark):
            return line
    return ""


# ---------------------------------------------------------------- a 作业话子目标 + proposition

def test_a_the_manuscript_statement_comes_from_the_product(tmp_path):
    """a：子目标正文是作业话，`proposition` 是定理陈述 ⇒ 稿上 `## 命题` 逐字 == 它。

    改前红：`## 命题` 从子目标正文渲染 ⇒ 写进盘的是那段修订说明，形态闸当场拒。
    """
    st = _ws(tmp_path)
    f = _agent(st, {POSITIVE: ANSWER_POSITIVE})
    plan = _plan()
    out = _round(f, plan=plan, product=_product(POSITIVE))

    assert out.get("proof_registered") is True, out
    files = _manuscripts(st)
    assert [p.name for p in files] == ["f-proof-000000.md"], files
    text = files[0].read_text(encoding="utf-8")
    # 这一条就是真机那一段作业话所属的子目标；稿上 `## 命题` 却是定理陈述。
    assert _section(text, "命题") == POSITIVE, _section(text, "命题")
    assert REVISION_NOTE.split("；", 1)[0] not in _section(text, "命题"), _section(text, "命题")
    # 闸判的就是这一段（台账里那一行的字数 == 定理陈述的字数）。
    rows = SEC.proposition_form_rows(st.root)
    assert len(rows) == 1 and rows[0]["statement_chars"] == len(POSITIVE), rows
    assert rows[0]["well_formed"] is True, rows


# ---------------------------------------------------------------- b 缺 proposition ⇒ 受控拒

def test_b_without_a_proposition_the_round_is_refused_before_any_model_call(tmp_path):
    """b：缺 `proposition` ⇒ `proposition_missing`、0 字节、一次模型都不问。

    改前红：改前会先花一次形态闸（拒的是 `proposition_form_refused`）—— 判据的码与
    "有没有白花那一次"两处都不同。
    """
    st = _ws(tmp_path)
    f = _agent(st, {})          # 回放表是空的：真的问闸就会炸
    plan = _plan()
    out = _round(f, plan=plan, product=_product(None))

    refusal = dict(out.get("refusal") or {})
    assert refusal.get("kind") == M.PROPOSITION_MISSING, out
    assert out.get("outcome") == "no_change" and out.get("status") != "progress", out
    assert out.get("manuscript_path") == "" and out.get("manuscript") == "", out
    assert _manuscripts(st) == [], [p.name for p in _manuscripts(st)]
    # 一个字节都没写 ⇒ 没有台账行（闸没跑）；回放表是空的也没炸 ⇒ 没问模型。
    assert SEC.proposition_form_rows(st.root) == [], SEC.proposition_form_rows(st.root)
    assert len(f.f_secretary.seam.calls) == 0, f.f_secretary.seam.calls
    detail = str(out.get("detail") or "")
    assert "product.proposition" in detail and "子目标正文不是命题" in detail, detail
    assert out.get("proof_registered") is False, out
    assert out.get("statement_id") == "", out


# ---------------------------------------------------------------- c 反真空

def test_c_forcing_the_subgoal_back_into_the_statement_turns_a_red(tmp_path, monkeypatch):
    """c：把 `proposition_text` 换回"从子目标正文拼" ⇒ a 的断言必红。

    这一条钉的是"a 的绿是这一格给的"：摘掉它，稿上 `## 命题` 就不再是定理陈述。
    """
    forced = "（探针：从子目标正文拼出来的那段话）"
    monkeypatch.setattr(FC, "proposition_text", lambda _p: forced)
    monkeypatch.setattr(M, "proposition_text", lambda _p: forced)
    st = _ws(tmp_path)
    f = _agent(st, {forced: ANSWER_NEGATIVE})
    plan = _plan()
    out = _round(f, plan=plan, product=_product(POSITIVE))

    files = _manuscripts(st)
    if files:
        landed = _section(files[0].read_text(encoding="utf-8"), "命题")
        assert landed != POSITIVE, (
            "反真空失效：`proposition_text` 被换掉之后 `## 命题` 仍然是定理陈述")
        assert landed == forced, landed
    else:
        assert dict(out.get("refusal") or {}).get("kind") == "proposition_form_refused", out
    assert out.get("proof_registered") is not True or not files, out


# ---------------------------------------------------------------- d label / testable

def test_d_label_is_not_the_proposition_and_testable_stays_out(tmp_path):
    """d：`label` 只是标签；`testable` 不再进 `## 命题`（业主裁定 B 的连带）。"""
    st = _ws(tmp_path)
    f = _agent(st, {POSITIVE: ANSWER_POSITIVE})
    plan = _plan(testable="V 给出两态结论「成立」即为成立")
    product = _product(POSITIVE, label="按 V 的缺陷修订第 7 步")
    out = _round(f, plan=plan, product=product)

    # 代码层：`label` 与 `proposition` 两格各归各的（label 不是命题）。
    parsed = FC.parse_handed_product({"kind": "proof", "proposition": POSITIVE,
                                      "label": "按 V 的缺陷修订第 7 步",
                                      "steps": [{"text": "取 a=1。", "assumption": True}]})
    assert parsed.get("ok") is True, parsed
    assert parsed["product"]["label"] == "按 V 的缺陷修订第 7 步", parsed
    assert parsed["product"]["proposition"] == POSITIVE, parsed

    assert out.get("proof_registered") is True, out
    text = _manuscripts(st)[0].read_text(encoding="utf-8")
    assert _section(text, "命题") == POSITIVE, _section(text, "命题")
    # 可检验形式（验收口径）不在命题里 —— 它属于计划 / 子目标。
    assert "这一条的可检验形式" not in _section(text, "命题"), _section(text, "命题")


# ---------------------------------------------------------------- e 真机形态

def test_e_the_real_revision_note_shape_can_never_land(tmp_path):
    """e：真机 f-proof-000002 的作业话原文 ⇒ `proposition_missing`、盘上 0 字节。

    这一条就是业主那句「真机 f-proof-000002 那段的形态再也落不了盘」。
    """
    st = _ws(tmp_path)
    f = _agent(st, {}, secretary=_WashOnly())
    plan = _plan(TASK_TEXT, testable=REVISION_NOTE.split("；这一条的可检验形式：", 1)[1])
    out = _round(f, plan=plan, product=_product(None))

    assert dict(out.get("refusal") or {}).get("kind") == M.PROPOSITION_MISSING, out
    assert _manuscripts(st) == [], [p.name for p in _manuscripts(st)]
    assert REVISION_NOTE[:20] not in str(out.get("manuscript") or ""), out


# ---------------------------------------------------------------- f schema 声明

def test_f_the_tool_schema_declares_the_proposition_so_the_tool_path_can_carry_it():
    """f：`attack.step` 的工具 schema 声明了 `proposition`（否则工具参数门先拒）。

    2026-11-13（p281，业主批准合批）：这一格在 3b7501ea 先只声明类型（让工具参数门认它），
    p281 把 description 写全 —— 判据跟着改成「类型是 string、且说明里点明是那条定理的完整
    陈述（前提 → 结论）」。这一条钉的是"工具入口真的收得下它"，以及
    `parse_handed_product` 的"未声明的键"闸与 schema 同源。
    """
    props = dict(AR.HANDED_PRODUCT_SCHEMA.get("properties") or {})
    assert "proposition" in props, sorted(props)
    assert props["proposition"]["type"] == "string", props["proposition"]
    assert "完整陈述（前提 → 结论）" in str(props["proposition"].get("description") or ""), \
        props["proposition"]
    parsed = FC.parse_handed_product({
        "kind": "proof", "proposition": POSITIVE,
        "steps": [{"text": "取 a=1 的八面体。", "assumption": True}]})
    assert parsed.get("ok") is True, parsed
    assert parsed["product"]["proposition"] == POSITIVE, parsed


# ---------------------------------------------------------------- g 框架自己那一轮

def test_g_parse_round_requires_the_proposition_too():
    """g：框架自己那一轮（`parse_round`）同样必填 `proposition`（缺 ⇒ RoundError + fix 文案）。"""
    base = {"product": "proof", "strategy": "反证", "why_strategy": "反设存在反例",
            "steps": [{"text": "取 a=1 的八面体。", "assumption": True}]}
    try:
        AR.parse_round(json.dumps(base, ensure_ascii=False))
    except AR.RoundError as exc:
        msg = str(exc)
        assert "proposition" in msg and "子目标正文不是命题" in msg, msg
    else:
        raise AssertionError("没有 proposition 的 proof 被 parse_round 收下了")

    ok = dict(base, proposition=POSITIVE)
    got = AR.parse_round(json.dumps(ok, ensure_ascii=False))
    assert got["proposition"] == POSITIVE, got

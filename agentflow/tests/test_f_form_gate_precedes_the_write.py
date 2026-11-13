# -*- coding: utf-8 -*-
"""W1：F 的命题形态闸必须在写盘之前，而且判的就是稿上 `## 命题` 那一节的字节。

## 现场（真机 `projects/octahedron-20261113`，2026-11-13）

`reports/f-proof-000002.md` 的 `## 命题` 是一段修订说明（「按 V u-000005 的唯一缺陷
修订第 7 步…其余八步一字不动…同一份稿就地重写后重送 V」＋可检验形式）。它

- 判据当场就说"不是命题"：`out/secretary/proposition_form.jsonl` 12:28:39 那一行
  `checked=True / well_formed=False`，逐条四条问题（"结论不是可判真假的数学断言，
  而是验收/流程状态判定"…）；
- 却还是落了盘、被送 V、拿到了「成立」的签（12:36:17）——B 收录时按 `## 命题`
  取 `statement_full`，于是拒收「`## 命题` 节是修订说明不是定理陈述 ⇒ 未登记」。
  签了却永远入不了台账，F 再落一版、白花钱。

根因两处，都在"闸的位置与字节"上（判据本身没有问题）：

1. 位置：闸只在 `proofregistry.register_or_rewrite`（登记那一步）跑，而手稿在那一步
   之前已经由 `AgentF.proof_manuscript` 写进盘（先写稿、后登记的既有次序）⇒
   闸拦得住登记，拦不住稿；稿在盘上，F 下一步就是把它送 V。
2. 字节：闸判的是 `_proof_outlet` 拼的 `full`（`## 命题` ＋「显式声明的前提：…」），
   写进盘的是 `## 命题` 本身（真机：判 977 字、写 311 字）⇒"判过了"证明不了
   "写下去的那一节合格"。

## 这个文件钉什么

| 编号 | 判据 | 用例 |
|---|---|---|
| a | f-proof-000002 的 `## 命题` 原文 ⇒ 受控拒 `proposition_form_refused`，盘上一个字节都没写 | `test_a_*` |
| b | 正控：一条规范定理陈述 ⇒ 过闸、落稿、登记；且只问一次模型（登记那一步命中台账缓存） | `test_b_*` |
| c | 反真空：把判据打桩成恒 well_formed ⇒ a 必红（那段修订说明照旧落成手稿） | `test_c_*` |
| d | 端到端：走 `_proposition_form_gate` 那条真路 ⇒ 它在写盘之前拒，且判的字节 == 稿上 `## 命题` | `test_d_*` |

## 判据一侧的读数用真机回放（不是本文件的发明）

`_ReplaySeam` 按"要判的那段正文"回放真模型那一次的答案：反例与正控的原文、以及
模型逐字的 conditions / conclusion / problems / decision，都取自
`temp/w1_answers.json`（2026-11-13 用真的 `Secretary.judge_proposition_form` 跑出来的
两次调用；反例那一问命中台账里 13:28:29 那一次的缓存）。于是这里的"拒 / 放"
不是本文件自己编的判据 —— 它是真机上那一问当时的读数。
"""
from __future__ import annotations

import pathlib

from agentflow import secretary as SEC
from agentflow.agent_f.core import AgentF
from agentflow.store import Store

TS = "2026-11-13T13:00:00+08:00"

#: 真机 `reports/f-proof-000002.md` 的 `## 命题` 那一节（逐字，311 字）。
#: 台账 12:28:39 那一行判的就是它：`checked=True / well_formed=False`。
NEGATIVE = (
    "按 V u-000005 的唯一缺陷修订第 7 步：把「2|P_1| = 2/√(u²+v²)」改为"
    "「2|P_1| = 2√(u²+v²)/(u+v) = 2/(u+v)（用 u²+v² = 1）」，其余八步一字不动；"
    "同一份稿 reports/f-proof-000002.md 就地重写后重送 V。"
    "；这一条的可检验形式：V 对这一版正文（新 sha，与 b944298d… 不同）给出两态结论"
    "「成立」（零 finding），且稿上签块的正文 sha 与现行正文一致（v_sign 读数 = 已签）。"
    "判据：F.step 返回的 v_sign.label == '已签' 即为成立；"
    "若 V 仍判「有毛病」则本轮记为缺陷步号。"
)
#: 子目标正文里属于"作业要求"的那一半（`## 命题` = 它 ＋ 可检验形式）。
NEG_TEXT, NEG_TESTABLE = NEGATIVE.split("；这一条的可检验形式：", 1)

#: 正控：一条规范的「设…则…，等号当且仅当…」（业主给的那一条）。
POSITIVE = (
    "设 a = 1/√2，O = {(x,y,z) ∈ R³ : |x|+|y|+|z| ≤ a}；"
    "则任意平面与 O 的截面面积 ≤ 2a² = 1，"
    "等号当且仅当该平面垂直于某个坐标轴且过原点（此时截面是边长 1 的正方形）。"
)

#: 真模型对上面两段的答案（逐字回放；见 `temp/w1_answers.json`）。
ANSWER_NEGATIVE = {
    "checked": True, "well_formed": False,
    "conditions": ("文本没有给出数学前提；它要求按 V u-000005 的唯一缺陷修订第 7 步，"
                   "把「2|P_1| = 2/√(u²+v²)」改为「2|P_1| = 2√(u²+v²)/(u+v) = 2/(u+v)"
                   "（用 u²+v² = 1）」，其余八步不动，并就地重写同一份稿 "
                   "reports/f-proof-000002.md 后重送 V。"),
    "conclusion": ("V 对本版新 sha 正文给出两态结论「成立」（零 finding），且稿上签块正文 "
                   "sha 与现行正文一致；按判据 F.step 返回的 v_sign.label == '已签' 即记为成立。"),
    "problems": ["没有写清数学前提与假设",
                 "结论不是可判真假的数学断言，而是验收/流程状态判定",
                 "整体是修订、重送和验收规格，不是「若…则…」式的数学命题结构",
                 "混入了作业/验收判据，如 v_sign.label == '已签'、重送 V、签块 sha 一致性"],
    "decision": "不合格：这是修订与验收流程要求，不是从条件导出数学结论的命题。",
    "refused": "proposition_form_refused",
    "reason": "形态不合规：4 条 —— 没有写清数学前提与假设；结论不是可判真假的数学断言",
}
ANSWER_POSITIVE = {
    "checked": True, "well_formed": True,
    "conditions": ("设 a = 1/√2，O = {(x,y,z) ∈ R³ : |x|+|y|+|z| ≤ a}，"
                   "并考虑任意平面与 O 的截面。"),
    "conclusion": ("任意平面与 O 的截面面积 ≤ 2a² = 1；且等号成立当且仅当该平面垂直于"
                   "某个坐标轴且过原点（此时截面是边长 1 的正方形）。"),
    "problems": [],
    "decision": "该描述以“设…则…”结构给出了明确前提和可判真假的结论，属于合格命题形态。",
    "refused": "", "reason": "形态合规：前提与结论都读得出来",
}


class _ReplaySeam:
    """真机读数回放：材料里带 `statement_full`，按它选那一次真模型的答案。

    `before` 是"闸判的那一刻"的回调（判据 d 用它看盘上有没有稿）。
    """

    class _Call:
        ok = True
        problem = ""
        detail = ""
        text = ""
        model = "replay"
        prompt_version = "t"
        prompt_sha256 = "0" * 64

    def __init__(self, answers: dict[str, dict], *, before=None) -> None:
        self.answers = dict(answers)
        self.before = before
        self.calls: list[str] = []
        self.prompts: list[str] = []

    def ask_json(self, prompt: str, *, system: str = "", task_id: str = "",
                 note: str = ""):
        self.prompts.append(prompt)
        if self.before is not None:
            self.before(prompt)
        for key, answer in self.answers.items():
            if key in prompt:
                self.calls.append(key)
                return dict(answer), self._Call()
        raise AssertionError(
            "回放表里没有这一段正文（真机上这一问没有答案 ⇒ 不许在这里凭空造一个）：\n"
            + str(prompt)[:600])


class _WashOnly:
    """秘书替身：只做依赖面那一遍（反真空 d 用它证明"没直接调 judge"）。"""

    role = "F"

    def wash_dependency_face(self, text: str, **_kw) -> dict:
        return {"checked": True, "text": str(text), "actor": self.role,
                "washed": False, "deps_refused": "", "deps_refused_findings": [],
                "deps_section_filled": "", "deps_washing": [],
                "reason": "夹具：依赖面本来就合规"}

    def judge_proposition_form(self, **_kw):
        raise AssertionError("这一条走的是 `_proposition_form_gate`，不该直接问 judge")


def _ws(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _agent(st: Store, answers: dict[str, dict], *, before=None,
           secretary: object | None = None) -> AgentF:
    f = AgentF(st, config={"workspace_root": str(st.root), "plan_id": "0001"})
    if secretary is not None:
        f.f_secretary = secretary
    else:
        f.f_secretary = SEC.Secretary(
            "F", root=st.root, store=st, seam=_ReplaySeam(answers, before=before),
            enable_model=True)
    return f


def _plan(text: str, testable: str = "") -> dict:
    subgoal = {"sid": "S4", "text": text, "owner": "F", "status": "in_progress",
               "testable": testable, "evidence_ids": [], "experiment_ids": [],
               "blocked_reason": "", "attempts": 0, "negation_kind": None}
    sg = {k: v for k, v in subgoal.items() if v != ""}
    return {"plan_id": "0001", "problem": "单位正八面体的最大截面", "problem_key": "PK-W1",
            "rounds": 0, "history": [], "status": "open", "depth": 0,
            "best_partial": "", "created_at": TS, "updated_at": TS,
            "budget": {"max_rounds": 4, "max_parallel_subgoals": 2,
                       "max_persist_attempts": 2, "max_depth": 1},
            "subgoals": [sg]}


def _product(proposition: str) -> dict:
    """这一轮的 proof 产物（2026-11-13 业主裁定 B：`proposition` 必填）。

    这一份文件判的是**形态闸**那一轴：`proposition` 就是这一轮声明的命题正文
    （可以是那段作业话 —— 那时闸的任务就是把它判成"不是命题"）。
    """
    return {"product": "proof", "proposition": proposition,
            "strategy": "按定义", "why_strategy": "直接算截面",
            "steps": [{"n": 1, "text": "取 a=1 的八面体 O_1，按 n 的三个分量分两支。",
                       "cites": [], "assumption": True},
                      {"n": 2, "text": "由 Brunn 凹性，最大截面必过原点。",
                       "cites": [], "assumption": False}]}


def _round(f: AgentF, *, text: str, testable: str = "",
           proposition: str = NEGATIVE) -> tuple[dict, dict]:
    plan = _plan(text, testable)
    sg = plan["subgoals"][0]
    out = f._apply_round(_product(proposition), sg, plan=plan, owner="F")
    return out, plan


def _manuscripts(st: Store) -> list[pathlib.Path]:
    base = pathlib.Path(st.root) / "reports"
    return sorted(base.glob("f-proof-*.md")) if base.is_dir() else []


def _proposition_section(text: str) -> str:
    """稿上 `## 命题` 那一节的正文（与 B 收录时读的是同一节）。"""
    return _section(text, "命题")


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


# ---------------------------------------------------------------- a 真机那段修订说明 ⇒ 拒且不落盘

def test_a_the_revision_note_never_reaches_the_disk(tmp_path):
    """a：f-proof-000002 的 `## 命题` 原文 ⇒ 受控拒，盘上一个字节都没写。

    改前红：改前这道闸在登记那一步才跑，而稿在那之前已经由 `proof_manuscript`
    写进盘 ⇒ `_manuscripts(st)` 非空、`manuscript_path` 非空（本用例断言它们为空）。
    """
    st = _ws(tmp_path)
    f = _agent(st, {NEGATIVE: ANSWER_NEGATIVE})
    assert (NEG_TEXT + "；这一条的可检验形式：" + NEG_TESTABLE) == NEGATIVE, (
        "夹具错：拆回的两段拼起来必须逐字等于真机 `## 命题` 那一节")
    out, _plan_now = _round(f, text=NEG_TEXT, testable=NEG_TESTABLE)

    # 这一轮是受控拒，不是推进，也不是交差。
    assert out.get("outcome") == "no_change", out
    assert out.get("status") != "progress", out
    assert out.get("delivered") is False, out
    refusal = dict(out.get("refusal") or {})
    assert refusal.get("kind") == "proposition_form_refused", out
    assert refusal.get("manuscript_path") == "reports/f-proof-000000.md", out
    assert "一个字节都没写" in str(out.get("detail") or ""), out.get("detail")
    assert "## 命题" in str(out.get("detail") or ""), out.get("detail")

    # 盘上没有任何稿：闸拒在写盘之前（改前这里会有一份 f-proof-000000.md）。
    assert _manuscripts(st) == [], [p.name for p in _manuscripts(st)]
    assert out.get("manuscript_path") == "", out
    assert out.get("manuscript") == "", out

    # 判据真的判过一次，且判的就是 `## 命题` 那一节的字节（311 字，不是 977 字）。
    rows = SEC.proposition_form_rows(st.root)
    assert len(rows) == 1, rows
    row = dict(rows[0])
    assert row["checked"] is True and row["well_formed"] is False, row
    assert row["statement_chars"] == len(NEGATIVE), row
    assert row["role"] == "F" and row["label"] == "F 攻坚 0001 子目标 S4", row
    assert len(row["problems"]) == 4, row


# ---------------------------------------------------------------- b 正控 ⇒ 落稿 + 登记

def test_b_a_normal_theorem_statement_lands_and_registers(tmp_path):
    """b：规范的「设…则…，等号当且仅当…」⇒ 过闸、落成手稿、登记；只问一次模型。"""
    st = _ws(tmp_path)
    f = _agent(st, {POSITIVE: ANSWER_POSITIVE})
    out, _plan_now = _round(f, text=POSITIVE, proposition=POSITIVE)

    assert out.get("proof_registered") is True, out
    assert out.get("proof_mode") == "registered", out
    assert out.get("status") == "in_progress", out
    files = _manuscripts(st)
    assert [p.name for p in files] == ["f-proof-000000.md"], files

    text = files[0].read_text(encoding="utf-8")
    # 稿上 `## 命题` 就是要判、要登记的那一段字节（一字不多、一字不少）。
    assert _section(text, "命题") == POSITIVE, _section(text, "命题")
    assert "## 证明" in text and "## 依赖" in text, text

    rows = SEC.proposition_form_rows(st.root)
    assert len(rows) == 1, rows
    assert rows[0]["checked"] is True and rows[0]["well_formed"] is True, rows
    assert rows[0]["statement_chars"] == len(POSITIVE), rows
    # 成本不变量：写前闸问过一次，登记那一步判同一段字节 ⇒ 命中台账缓存，不再问模型。
    assert len(f.f_secretary.seam.calls) == 1, f.f_secretary.seam.calls


# ---------------------------------------------------------------- c 反真空

def test_c_stubbing_always_well_formed_lets_the_revision_note_land(tmp_path, monkeypatch):
    """c：反真空 —— 把判据打桩成恒 well_formed ⇒ a 必红（修订说明照旧落成手稿）。

    这一条钉的是"a 的绿是闸给的"：摘掉判据（恒放行）之后，同一段修订说明会被写成
    `reports/f-proof-000000.md` 的 `## 命题` —— 那正是真机上发生的事。
    """
    st = _ws(tmp_path)
    f = _agent(st, {}, secretary=_WashOnly())
    monkeypatch.setattr(
        AgentF, "_proposition_form_gate",
        lambda self, **kw: {"checked": True, "well_formed": True, "submittable": True,
                            "conditions": "（探针：恒放行）", "conclusion": "（探针）",
                            "problems": [], "decision": "（探针：摘掉判据）",
                            "refused": "", "reason": "（探针）", "actor": ""})
    out, _plan_now = _round(f, text=NEG_TEXT, testable=NEG_TESTABLE)
    assert out.get("proof_registered") is True, out
    files = _manuscripts(st)
    assert [p.name for p in files] == ["f-proof-000000.md"], files
    text = files[0].read_text(encoding="utf-8")
    assert _section(text, "命题") == NEGATIVE, _section(text, "命题")
    # 于是 a 的三条断言（无稿 / manuscript_path 空 / 台账一行 wf=False）在这一档全部为假。
    assert _manuscripts(st) != []


# ---------------------------------------------------------------- d 端到端：写盘之前拒

def test_d_the_gate_runs_before_any_byte_is_written(tmp_path):
    """d：走 `_proposition_form_gate` 那条真路 ⇒ 它在写盘之前拒，判的是 `## 命题` 的字节。

    改前红：改前闸在登记那一步才跑，跑的时候 `reports/f-proof-000000.md` 已经躺在盘上
    （`at_gate != []`）⇒ "闸在写盘之前拒"这句话是假的。
    """
    st = _ws(tmp_path)
    at_gate: dict = {}

    def _before(prompt: str) -> None:
        at_gate["reports"] = sorted(p.name for p in
                                    (pathlib.Path(st.root) / "reports").glob("*.md"))
        at_gate["prompt"] = prompt

    f = _agent(st, {NEGATIVE: ANSWER_NEGATIVE}, before=_before)
    out, _plan_now = _round(f, text=NEG_TEXT, testable=NEG_TESTABLE)

    # ① 闸判的那一刻，盘上还没有这一份稿 —— 拒绝发生在写盘之前。
    assert at_gate.get("reports") == [], at_gate
    assert not _manuscripts(st), [p.name for p in _manuscripts(st)]
    # ② 判的就是要写进 `## 命题` 的那一段字节（不是拼上"显式声明的前提"的另一段）。
    assert NEGATIVE in str(at_gate.get("prompt") or ""), at_gate.get("prompt")
    assert "显式声明的前提" not in str(at_gate.get("prompt") or ""), at_gate.get("prompt")
    # ③ 走的是 `_proposition_form_gate` 那条真路：读数带它的 actor 与那一行台账。
    refusal = dict(out.get("refusal") or {})
    form = dict(refusal.get("proposition_form") or {})
    assert form.get("checked") is True and form.get("well_formed") is False, form
    assert form.get("actor") == "secretary-F", form
    assert form.get("refused") == "proposition_form_refused", form
    assert len(SEC.proposition_form_rows(st.root)) == 1
    # ④ 没有登记、没有送审的读数（这一轮没有可送的对象）。
    assert out.get("proof_registered") is False and out.get("proof_rewritten") is False, out
    assert out.get("statement_id") == "", out

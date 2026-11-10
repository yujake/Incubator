# -*- coding: utf-8 -*-
"""命题形态闸（业主 2026-11-07 裁定）：F 登记新命题时，命题描述必须明确「条件 → 结论」。

业主原话（逐字，这就是本文件的验收标准）：

> 「命题登记时需过 F 秘书闸，审查命题描述是否规范，是否明确了从什么条件导出什么结论」
> 「就是F侧登记新命题F秘书闸拦的那块」

## 现场（98 的三条反例，逐字，见 `projects/paper-rewrite-98/data/statements.json`）

| 号 | 正文开头（逐字节选） | 它其实是什么 |
|---|---|---|
| 000036 | 「本轮产物必须是 proof（禁止 reduction、禁止 dead_end、禁止拆出新子目标）：把 reports/f-0002-carrier-v3.md 的既有正文原样作为这一轮的证明正文提交…」 | F 的作业规格 |
| 000037 | 「本轮产物必须是 proof，且证明正文原样取自盘上文件 reports/f-0002-carrier-v3.md…」 | F 的作业规格 |
| 000039 | 同 000037 + 「…并逐字给出 fs.stat 的 size 与 sha256」 | 验收读数清单 |

这三条被登记成 `kind=conjecture`，然后以「本行不是数学命题，而是 F 一方的作业/验收规格」
为由放弃 —— 那是事后才发现的。这一闸把它挪到手稿登记之前。

## 闸装在哪（2026-11-07 业主第二次裁定把它挪到了手稿登记那一步）

| 位置 | 装不装 | 理由（业主逐字） |
|---|---|---|
| F 登记新命题（手稿登记：`proofregistry.register_or_rewrite` 的 `registered` 那一档） | 装 | 「就是F侧登记新命题F秘书闸拦的那块」 |
| 已有命题的证明重写 | 不装 | 「已经在登记里的命题重写证明时不再过这一步 —— 改证明不需要重新登记」 |
| `D.register_conjecture` | 不装 | 「D侧给的猜想只是参考」 |
| `B.register_statement` | 不装 | 「B侧收录不拦」（那条路还承载文献侧定理的收录） |

## 两根轴必须分开（这是最容易做错的一格）

这一闸只判形状（有没有写出「条件 → 结论」）。它不判对不对（V 的轴）、
不判是否平凡/是否已知（`judge_statement` 的非平凡性轴）。也不拿字数/关键词表
代替判断（业主明确不要机械判据）。

## 用例与判据

| 编号 | 判据 | 用例 |
|---|---|---|
| a | 98 那三条文本 ⇒ 受控拒，手稿不落盘、`statements` 一行都不多 | `test_a_*` |
| b | 一条规范的「设…则…」⇒ 过闸、落成手稿登记条目，且判定结果读得回来 | `test_b_*` |
| c | B 自己收录文献侧定理（不经 F）⇒ 不受影响 | `test_c_*` |
| d | `D.register_conjecture` ⇒ 不受影响 | `test_d_*` |
| e | 判定没查成（打桩抛 / 没有秘书）⇒ 受控拒 + `checked=False`（fail-closed） | `test_e_*` |
| f | 反真空：摘掉这道闸 ⇒ a 红 | `test_f_*` |
| g | 收工读数 `proposition_form`：被拒条数 + 逐条码 + 一条合法样本 | `test_g_*` |
"""
from __future__ import annotations

import pathlib

import pytest
from agentflow import closing as CL
from agentflow import secretary as SEC
from agentflow import statementabandon as SA
from agentflow import verifications as VR
from agentflow.agent_f.core import AgentF
from agentflow.store import Store
from agentflow.tools import conjecture_tools

TS = "2026-11-07T10:00:00+08:00"
SID = "000001"
FULL = "设 f 在 [0,1] 上连续，则 f 一致连续。"
PROOF = "取 δ=ε，逐点验证：|x-y|<δ ⇒ |f(x)-f(y)|<ε。"

#: 98 的三条反例（逐字，取自 `data/statements.json` 的 `statement_full` 开头）。
SPEC_036 = (
    "本轮产物必须是 proof（禁止 reduction、禁止 dead_end、禁止拆出新子目标）：把 "
    "reports/f-0002-carrier-v3.md 的既有正文原样作为这一轮的证明正文提交，命题号 0002、"
    "证明号 1，不重写任何数学内容、不回退 V 手稿 000024 的六条修法；正文来源格 "
    "proof_manuscript=reports/f-0002-carrier-v3.md，carrier_path 同值。；这一条的可检验形式："
    "'判据：attack.step 的返回里 manuscript_published=true 且 "
    "manuscript_path='reports/f-proof-0002.md'，并且 fs.stat('reports/f-proof-0002.md') "
    "给出 exists=true 与非空 sha256")
SPEC_037 = (
    "本轮产物必须是 proof，且证明正文**原样取自盘上文件 reports/f-0002-carrier-v3.md**："
    "该文件的全文就是本次要发布的证明正文，一字不改（不改写、不摘要、不重写数学、不新增论证、"
    "不改标题）。禁止 reduction、禁止 dead_end、禁止生成任何新论证。发布落点尽量指向 "
    "reports/f-proof-0002.md（命题号 0002、证明号 1）。；这一条的可检验形式：attack.step "
    "返回里 manuscript_published=true，且返回自报的稿正文长度与载体同量级（>8000 字符，"
    "而非千余字）；随后 fs.stat 该 manuscript_path 给出的 size 与载体 22114 B 同量级")
SPEC_039 = SPEC_037   # 000039 与 000037 的正文同源（只差尾部那几格读数）

#: 一条写得规范的命题（「设…，若…则…」）。
WELL_FORMED = ("设 K=Q(√−3)，O_K 为其整数环；若 𝔭 是 O_K 中范数 ≤ X 的素理想，"
               "则 ∑_{N𝔭≤X} log N𝔭 = X + O(√X)。")


class _FormStub:
    """F 的秘书替身：只实现形态判定这一问（其余一概不碰）。"""

    role = "F"

    def __init__(self, *, checked: bool = True, well_formed: bool = True,
                 problems: list[str] | None = None,
                 conditions: str = "设 K=Q(√−3)", conclusion: str = "则 …",
                 raises: BaseException | None = None) -> None:
        self.checked = checked
        self.well_formed = well_formed
        self.problems = list(problems if problems is not None else [])
        self.conditions = conditions
        self.conclusion = conclusion
        self.raises = raises
        self.calls: list[dict] = []

    def judge_proposition_form(self, **kw):
        self.calls.append(dict(kw))
        if self.raises is not None:
            raise self.raises
        return {"checked": self.checked, "well_formed": self.well_formed,
                "conditions": self.conditions if self.well_formed else "",
                "conclusion": self.conclusion if self.well_formed else "",
                "problems": self.problems, "decision": "夹具：形态判定",
                "refused": "" if (self.checked and self.well_formed)
                else SEC.PROPOSITION_FORM_REFUSED,
                "reason": "夹具：形态判定", "cached": False}


class _Seam:
    """模型缝的替身：`ask_json` 回一段写死的 JSON（含 `SeamCall` 的最小形状）。"""

    class _Call:
        ok = True
        problem = ""
        detail = ""
        text = ""
        model = "fake"
        prompt_version = "t"
        prompt_sha256 = "0" * 64

    def __init__(self, data: dict) -> None:
        self.data = dict(data)
        self.prompts: list[str] = []
        self.systems: list[str] = []

    def ask_json(self, prompt: str, *, system: str = "", task_id: str = "",
                 note: str = ""):
        self.prompts.append(prompt)
        self.systems.append(system)
        return dict(self.data), self._Call()


def _ws(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _agent(st: Store, secretary: object | None) -> AgentF:
    agent = AgentF(st, config={"workspace_root": str(st.root), "plan_id": "0001"})
    if secretary is not None:
        agent.f_secretary = secretary
    return agent


def _hand(agent: AgentF, full: str, *, kind: str = "conjecture", sid: str = "S1",
          body: str = PROOF):
    return agent._hand_proof(
        full=full, text=full, body=body, sid=sid,
        plan={"plan_id": "0001", "problem_key": "k1"},
        sg={"sid": sid, "text": full, "kind": kind},
        manuscript_text="",
        manuscript_received={"source": "param", "chars": 0,
                             "section_rows": 0, "refs_in_proof": 0},
        cites=[], tier={"kind": "heuristic", "why": "夹具"},
        dependency_rows=[], existing_row={"kind": kind})


def _count(st: Store) -> int:
    return len(list(st.rows("statements")))


def _manuscripts(st: Store) -> list[str]:
    base = pathlib.Path(st.root) / "reports"
    return sorted(p.name for p in base.glob("*.md")) if base.is_dir() else []


# ---------------------------------------------------------------- a 98 的三条 ⇒ 受控拒

@pytest.mark.parametrize("text", [SPEC_036, SPEC_037, SPEC_039],
                         ids=["000036", "000037", "000039"])
def test_a_a_spec_registered_as_a_conjecture_is_refused(tmp_path, text):
    """a：98 那种「作业/验收规格」当新命题登记 ⇒ 受控拒，手稿不落盘、行数不变。"""
    st = _ws(tmp_path)
    before = _count(st)
    stub = _FormStub(
        well_formed=False,
        problems=["这是流程要求（本轮产物必须是 proof），不是数学命题",
                  "没有写清前提：给出的是判据与验收读数（manuscript_published / fs.stat）",
                  "结论不是可判真假的断言：它要求交付一份稿，而不是断言某条件推出某结论"])
    agent = _agent(st, stub)
    got = _hand(agent, text)
    assert got["ok"] is False, got
    assert got["kind"] == "proposition_form_refused", got
    assert got["refused_kind"] == "proposition_form_refused", got
    assert got["statement_id"] == "", got
    assert _count(st) == before, "闸判不过时 statements 不许出现新行"
    assert _manuscripts(st) == [], "闸判不过时手稿不许落盘"
    form = dict(got.get("proposition_form") or {})
    assert form.get("checked") is True and form.get("well_formed") is False, form
    assert len(form.get("problems") or []) == 3, form
    assert "流程要求" in got["error"], got["error"]
    # 闸真的看到了那段正文（不是拿空串判的）
    assert stub.calls and stub.calls[0]["statement_full"] == text, stub.calls


# ---------------------------------------------------------------- b 合格 ⇒ 落手稿登记

def test_b_a_well_formed_proposition_is_registered_as_a_manuscript(tmp_path):
    """b：规范的「设…若…则…」⇒ 过闸、落成手稿登记条目（登记一次）。"""
    st = _ws(tmp_path)
    stub = _FormStub(well_formed=True, conditions="设 K=Q(√−3)，O_K 为其整数环",
                     conclusion="∑_{N𝔭≤X} log N𝔭 = X + O(√X)")
    agent = _agent(st, stub)
    got = _hand(agent, WELL_FORMED)
    assert got["ok"] is True, got
    assert got["proof_mode"] == "registered", got
    assert got["proof_no"] == 1, got
    assert len(stub.calls) == 1, stub.calls
    form = dict(got.get("proposition_form") or {})
    assert form.get("submittable") is True, form
    assert stub.calls[0]["label"], "闸要拿到这一条的 label 才能判"
    # 登记条目真的落盘了（规范路径 + 头部元信息）
    path = pathlib.Path(st.root) / str(got["manuscript_path"])
    assert path.is_file(), got["manuscript_path"]
    text = path.read_text(encoding="utf-8")
    assert "## 命题" in text and "## 证明" in text and "## 依赖" in text, text
    assert "- 命题指纹：" in text and "- 正文sha：" in text, text


def test_b_the_verdict_lands_in_the_ledger_and_is_readable(tmp_path):
    """b 的第二半：判定结果落在秘书台账上，读侧一个口读得回来（含条件与结论）。"""
    st = _ws(tmp_path)
    seam = _Seam({"well_formed": True, "conditions": "设 K=Q(√−3)，O_K 为其整数环",
                  "conclusion": "∑_{N𝔭≤X} log N𝔭 = X + O(√X)",
                  "problems": [], "decision": "前提与结论都写清了"})
    sec = SEC.Secretary("F", root=st.root, store=st, seam=seam, enable_model=True)
    got = sec.judge_proposition_form(statement_full=WELL_FORMED, label="lem:sum",
                                     kind="lemma", stmt_id=SID)
    assert got["checked"] is True and got["well_formed"] is True, got
    assert got["conditions"] and got["conclusion"], got
    read = SEC.proposition_form_of(st.root, statement_full=WELL_FORMED)
    assert read.get("well_formed") is True and read.get("checked") is True, read
    assert read.get("conditions"), read
    assert read.get("stmt_id") == SID, read
    # 缓存：同一段正文再问一次 ⇒ 不再花钱（同一份台账、`cached=True`）
    calls_before = len(seam.prompts)
    again = sec.judge_proposition_form(statement_full=WELL_FORMED, label="lem:sum",
                                       kind="lemma", stmt_id=SID)
    assert again["cached"] is True and len(seam.prompts) == calls_before, again


# ---------------------------------------------------------------- e 没判成 ⇒ fail-closed

def test_e_a_failed_judgement_refuses_and_says_not_checked(tmp_path):
    """e：模型那一侧炸了 ⇒ F 受控拒 + `checked=False`（不许静默放行，也不许穿透）。"""
    st = _ws(tmp_path)
    before = _count(st)
    agent = _agent(st, _FormStub(raises=TimeoutError("模型超时")))
    got = _hand(agent, WELL_FORMED)
    assert got["ok"] is False and got["kind"] == "proposition_form_refused", got
    assert _count(st) == before
    assert _manuscripts(st) == [], "没判成时手稿不许落盘"
    rows = SEC.proposition_form_rows(st.root)
    assert len(rows) == 1 and rows[0]["checked"] is False, rows

    # 秘书那一层自己把异常折成"没判成"（fail-closed 的那一半）
    sec = SEC.Secretary("F", root=st.root, store=st, seam=_RaisingSeam(),
                        enable_model=True)
    got = sec.judge_proposition_form(statement_full=WELL_FORMED, kind="lemma")
    assert got["checked"] is False, got
    assert got["well_formed"] is False, got
    assert got["refused"] == SEC.PROPOSITION_FORM_REFUSED, got
    assert "没判成" in got["reason"], got


def test_e_no_secretary_means_refused(tmp_path):
    """e 的第二档：F 派生不出秘书（没有判断面）⇒ 受控拒，不是放行。"""
    st = _ws(tmp_path)
    before = _count(st)
    agent = AgentF(st)
    agent.f_secretary = None
    agent.f_secretary_problem = "夹具：没有配模型 key"
    # `_secretary()` 会重新派生 —— 这里把它钉死成 None
    agent._secretary = lambda: None          # type: ignore[method-assign]
    got = _hand(agent, WELL_FORMED)
    assert got["ok"] is False and got["kind"] == "proposition_form_refused", got
    form = dict(got.get("proposition_form") or {})
    assert form.get("checked") is False, form
    assert _count(st) == before
    assert _manuscripts(st) == []
    # "没有秘书"也进形态台账（否则 judged=0 与"没跑过闸"不可分）
    rows = SEC.proposition_form_rows(st.root)
    assert len(rows) == 1 and rows[0]["checked"] is False, rows


class _RaisingSeam:
    class _Call:
        ok = False
        problem = "网络超时"
        detail = "timeout"
        text = ""

    def ask_json(self, prompt: str, *, system: str = "", task_id: str = "",
                 note: str = ""):
        raise TimeoutError("模型超时")


# ---------------------------------------------------------------- f 反真空

def test_f_removing_the_gate_makes_a_red(tmp_path, monkeypatch):
    """f：把这道闸摘掉 ⇒ a 立刻变红（同一段作业规格、只是不再判形态）。"""
    st = _ws(tmp_path)
    before = _count(st)
    agent = _agent(st, _FormStub(
        well_formed=False, problems=["这是流程要求，不是命题"]))
    monkeypatch.setattr(
        AgentF, "_proposition_form_gate",
        lambda self, **kw: {"checked": True, "well_formed": True, "submittable": True,
                            "conditions": "x", "conclusion": "y", "problems": [],
                            "decision": "（探针：摘掉闸）", "refused": "", "reason": "",
                            "actor": ""})

    got = _hand(agent, SPEC_036)
    assert got["ok"] is True, (
        "反真空失效：摘掉形态闸之后仍然被拒 ⇒ 这条用例证明不了闸在起作用")
    # 摘掉闸之后那段作业规格会被登记成手稿 —— 这正是 a 要拦住的那件事。
    #
    # 2026-11-10（F 稿自建号源，88074416）：稿名只由 F 自己的稿号决定
    # （`reports/f-proof-<稿号>.md`）；改前那条"还没有命题号时按计划名拼
    # `f-proof-plan-<计划号>.md`"的兜底已经停用（只保留给老盘读兼容）。
    # 空号在 `_hand_proof` 里补：这个工作区是新的 ⇒ 取到 `000000`。
    # 判的仍是"摘掉闸 ⇒ 这段作业规格落成了一份手稿"，只是落点换成了稿号口径；
    # 反向断言（稿名里不含计划名 / 不含命题号）钉的是新口径本身 —— 谁把兜底改回来，
    # 这两行立刻红。
    assert _manuscripts(st) == ["f-proof-000000.md"], (
        "摘掉闸之后那段作业规格会被登记成手稿 —— 这正是 a 要拦住的那件事")
    assert got.get("manuscript_id") == "000000" and \
        got.get("manuscript_id_source") == "allocated", got
    manuscript_name = pathlib.Path(str(got.get("manuscript_path") or "")).name
    assert manuscript_name == "f-proof-000000.md", got
    assert "plan" not in manuscript_name and "0001" not in manuscript_name, manuscript_name
    assert _count(st) == before, "F 仍然不写 statements（登记那一步不在这一侧）"


# ---------------------------------------------------------------- c/d 两处不受影响

def test_c_b_collects_a_literature_theorem_without_this_gate(tmp_path):
    """c：B 自己收录文献侧定理（不经 F）⇒ 这条路一个字节都没被动。"""
    st = _ws(tmp_path)
    sec = SEC.Secretary("B", root=st.root, store=st)
    got = sec.record_statement({
        "origin": "own_result", "kind": "theorem", "label": "定理 A",
        "statement_full": "设 G 是有限群，若 |G|=p^2，则 G 交换。",
        "statement_text": "若 |G|=p^2，则 G 交换。",
        "evidence_kind": "heuristic", "quote_verified": None,
        "quote_reason": "夹具：自产命题",
    }, role="B")
    assert got.get("created") is True, got
    row = next(dict(r) for r in st.rows("statements"))
    assert row["kind"] == "theorem" and row["status"] == "active", row
    # 形态闸那本台账一次都没被写（B 这条路不经过它）
    assert SEC.proposition_form_rows(st.root) == []


def test_d_register_conjecture_does_not_go_through_this_gate(tmp_path):
    """d：D 的 `register_conjecture` 只是参考 ⇒ 不受这道闸影响。"""
    st = _ws(tmp_path)
    got = conjecture_tools.register_conjecture(
        st, statement=SPEC_036, origin="doc:0000#thm", actor="agent-D",
        testable={"criterion": "夹具：这条是参考用的猜想，不受形态闸管"})
    assert got.get("conjecture_id"), got
    assert len(list(st.rows("conjectures"))) == 1
    assert SEC.proposition_form_rows(st.root) == []


# ---------------------------------------------------------------- g 收工读数

def test_g_the_closing_reading_counts_refusals_codes_and_one_sample(tmp_path):
    """g：`proposition_form` 一格数得出"被拒几条 / 每条什么码 / 一条合法样本"。"""
    st = _ws(tmp_path)
    sec = SEC.Secretary("F", root=st.root, store=st, enable_model=True,
                        seam=_Seam({"well_formed": False,
                                    "problems": ["这是流程要求，不是命题"],
                                    "conditions": "", "conclusion": "",
                                    "decision": "不是命题"}))
    bad = sec.judge_proposition_form(statement_full=SPEC_036, kind="conjecture")
    assert bad["checked"] is True and bad["well_formed"] is False, bad
    sec2 = SEC.Secretary("F", root=st.root, store=st, enable_model=True,
                         seam=_Seam({"well_formed": True,
                                     "conditions": "设 K=Q(√−3)",
                                     "conclusion": "∑ log N𝔭 = X + O(√X)",
                                     "problems": [], "decision": "写清了"}))
    ok = sec2.judge_proposition_form(statement_full=WELL_FORMED, kind="lemma",
                                     stmt_id=SID)
    assert ok["well_formed"] is True, ok
    read = CL.proposition_form_reading(st)
    assert read["checked"] is True, read
    assert read["judged"] == 2 and read["well_formed"] == 1 and read["refused"] == 1, read
    assert read["codes"] == [{"code": "proposition_form_refused", "count": 1}], read
    assert read["sample"].get("conditions") == "设 K=Q(√−3)", read["sample"]
    assert "受控拒 1" in read["reason"], read["reason"]


def test_g_an_empty_ledger_is_not_all_clean(tmp_path):
    """g 的三态：台账 0 行 ⇒ `judged=0` 且 reason 说清"这一趟没跑过闸"。"""
    st = _ws(tmp_path)
    read = CL.proposition_form_reading(st)
    assert read["checked"] is True and read["judged"] == 0, read
    assert "一次都没跑过" in read["reason"], read["reason"]
    assert CL.proposition_form_reading(None)["checked"] is False

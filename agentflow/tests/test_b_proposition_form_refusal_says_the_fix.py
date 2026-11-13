# -*- coding: utf-8 -*-
"""W2 / 甲 判据：引文侧登记的命题形态闸拒收，必须自己给出可执行改法。

## 语义变更（2026-11-13 晚，业主改裁「甲」）

改前（W2，2026-11-13 早些时候）本文件判的是"按稿收录（F 的 `f-proof-*`）时
`## 命题` 是修订说明 ⇒ 受控拒 + `fix`"。

业主同日晚改裁（甲）：「B 侧只对 B 自己登记的命题审注册名（如来自引文的内容），
E 和 F 手稿侧录入放行」＋「应该设在 B 侧写手稿侧（形状同 F 和 E）…从引文侧录入命题
每个命题落手稿」。于是：

- F / E 的手稿现在放行（上游的 `_proposition_form_precheck` /
  `agent_e/proposition_form.py` 已经判过）；`f-proof-000002` 那一份不再归 B 判；
- 拒收 + `fix` / `next_step` 这一组断言整体挪到引文侧登记：从引文抽出来的一条
  命题，形状不合格 ⇒ 受控拒，连那份 b-稿都不落（`reports/` 零字节）。
  判据强度一字没降：仍是"受控码 + 可执行改法 + 零写入"三件，只是对象从"稿"换成
  "这条命题"。

正控 b 也换成引文侧：形状合规 ⇒ 登记成功且落一份 `b-proof-<稿号>.md`。

## 判据

| # | 判据 | 改前为什么红 |
|---|---|---|
| a | 引文侧命题（形状是修订说明）⇒ 受控拒 `proposition_form_refused`，`fix` 明写「重写成完整陈述（条件 → 结论）」「不要为了过闸去改引文」；`next_step` 明写不用 D 裁；`statements` 零行、`reports/` 零字节、稿号未发、形态台账留一行 `role=B` | 改前 `ok=true`（探针 `temp/z1_fact_probe/probe.py`）：修订说明成了 `statement_full` |
| b | 正控：同一段引文、命题是正常定理陈述 ⇒ 登记成功 + b-稿落盘 + 行指向它 | 闸若把正常命题也拒了，a 就是"什么都拒"的假绿 |
| c | 反真空：把 `AgentB.PROPOSITION_FORM_REGISTER_FIX` 打桩成空串 ⇒ a 的改法断言必红 | 证明 a 读的确实是代码里那一格 |
| d | 反真空：把这道闸摘掉 ⇒ 那段修订说明真的被收成一条命题（且落一份稿） | 证明"拒收"来自这道闸 |
| e | 语义变更的正面：F 的 `f-proof-*`（同一段修订说明）不再被 B 拒 | 改前它在这里被拒（W2 的原判据）；现在放行由 `test_b_citation_registration_lands_a_manuscript.py::c` 钉住 |

## 不判什么

- 不判"命题对不对"（那是 V 的轴）；也不许用关键词/字数阈值代替判断 —— 判据本体只有
  `Secretary.judge_proposition_form` 那一次模型调用，本文件的替身只换"模型缝"。
"""
from __future__ import annotations

import pathlib
import sys

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import conftest  # noqa: E402
from agentflow import depsection as DS  # noqa: E402
from agentflow import manuscriptids as MP  # noqa: E402
from agentflow import secretary as SEC  # noqa: E402
from agentflow.agent_b import AgentB  # noqa: E402
from agentflow.store import Store  # noqa: E402

TS = "2026-11-13T10:00:00+08:00"
LIT = "000000"

#: 真机 `reports/f-proof-000002.md` 的 `## 命题` 节（逐字；它就是"修订说明"）。
NOTE = ("按 V u-000005 的唯一缺陷修订第 7 步：把「2|P_1| = 2/√(u²+v²)」改为"
        "「2|P_1| = 2√(u²+v²)/(u+v) = 2/(u+v)（用 u²+v² = 1）」，其余八步一字不动；"
        "同一份稿 reports/f-proof-000002.md 就地重写后重送 V。"
        "；这一条的可检验形式：V 对这一版正文（新 sha）给出两态结论「成立」（零 finding），"
        "且稿上签块的正文 sha 与现行正文一致；判据：F.step 返回的 v_sign.label == '已签'。")

#: 正控用的正常定理陈述（同一段引文正文；`## 命题` 这一节才是变量）。
PROPOSITION = ("设 a = 1/√2、O_a = {(x,y,z) : |x|+|y|+|z| ≤ a}；则对任意单位向量 n 与"
               "任意实数 t，截面面积 A_n(t) ≤ 2a²，且等号成立当且仅当 n 平行于某坐标轴"
               "且 t = 0。")

#: 引文侧登记的 `proof_text`：回验要比对的那一段逐字引文（甲：它进 b-稿的 `## 证明`）。
QUOTE = ("Theorem 1.2. Let a = 1/sqrt(2). For every unit vector n and every real t, "
         "the central section area A_n(t) is at most 2a^2, with equality iff n is "
         "parallel to a coordinate axis and t = 0.")

PROOF = ("1. 口径与齐次缩放：O_a = a·O_1，area(a·K) = a²·area(K)，故只需证 a=1 时 ≤ 2。\n"
         "2. 由 Brunn 凹性与 O_1 的中心对称得 A_n(t) ≤ A_n(0)：最大值在中心截面。\n"
         "3. 中心截面为六边形，面积闭式 2s/D ≤ 2（对称函数估计），等号当且仅当 n=±e_i。")

F_REL = "reports/f-proof-000002.md"


class _Seam:
    """秘书模型缝的替身：`ask_json` 回一段写死的 JSON（`SeamCall` 的最小形状）。

    为什么只换缝、不换秘书：形态台账（`out/secretary/proposition_form.jsonl`）那一行是
    `Secretary.judge_proposition_form` 自己写的 —— 换掉秘书就把"拒收读数进台账"这件事
    一起换掉了，那条判据就成了夹具的自说自话。
    """

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

    def ask_json(self, prompt: str, *, system: str = "", task_id: str = "",
                 note: str = ""):
        # 这一名秘书在这种登记里还会被问"是不是在册的同一条"（`secretary:*` 里的
        # 身份那一问）。替身只该替换形态那一问；身份那一回答"不同"（本文件的
        # 工作区里没有在册命题，那一问本来也会判不同）。
        if not str(note or "").endswith("secretary:proposition_form"):
            return ({"decision": "different", "canonical_name": "夹具",
                     "same_as": "", "route": "", "condition": "夹具",
                     "conclusion": "夹具", "reason": "夹具：在册没有同一条",
                     "basis": ["夹具"]}, self._Call())
        self.prompts.append(prompt)
        return dict(self.data), self._Call()


def _ill_formed_seam() -> _Seam:
    """真机那一次判定的形状：不是「条件 → 结论」，是流程要求 / 验收规格。"""
    return _Seam({"well_formed": False, "conditions": "", "conclusion": "",
                  "problems": ["这是修订与送审的流程要求，不是「从什么条件导出什么结论」"
                               "的数学命题",
                               "结论部分是操作指令与验收规格，不是可判真假的断言"],
                  "decision": "不是命题"})


def _well_formed_seam() -> _Seam:
    return _Seam({"well_formed": True, "conditions": "设 a = 1/√2、n 为单位向量",
                  "conclusion": "则 A_n(t) ≤ 2a²，等号当且仅当 n ∥ 坐标轴且 t = 0",
                  "problems": [], "decision": "前提与结论都写清了"})


def _store(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    with st.tx("literature", actor="w2") as tx:
        tx.upsert("literature", {
            "lit_id": LIT, "title": "夹具文献", "type": "J", "summary": "夹具",
            "path": f"{LIT}/source.txt", "processed": True,
            "created_at": TS, "created_by": "w2"})
    return st


def _manuscript(proposition: str) -> str:
    """F 稿的骨架（稿头 / 三节 / 空依赖表），只换 `## 命题` 那一节。"""
    return ("# F 的证明手稿：按 V u-000005 的唯一缺陷修订第 7 步\n\n"
            "- 命题号：stmt:（还没落号）\n"
            "- 计划：000002 · 子目标：S4\n"
            "- 依赖面洗稿：已洗=true；执行者=secretary:F\n\n"
            "## 命题\n\n" + proposition + "\n\n"
            "## 证明\n\n" + PROOF + "\n\n"
            + DS.render_dependency_section([]) + "\n")


def _b(store: Store, seam: _Seam) -> AgentB:
    """B + 真的 `Secretary`（`judge_proposition_form` 本体），只换模型缝。"""
    sec = SEC.Secretary("B", root=store.root, store=store, seam=seam,
                        enable_model=True)
    return AgentB(store, extractor=None, extract_text=None, config={}, secretary=sec)


def _register(st: Store, seam: _Seam, *, text: str = NOTE) -> dict:
    """现场：引文侧登记一条命题（出处三件齐全；形状由 `text` 决定）。"""
    return _b(st, seam).register_statement(
        statement_full=text, statement_text="", kind="theorem", label="主定理",
        origin="external_lit", source_lit_id=LIT, page_range={"start": 1, "end": 2},
        evidence_kind="cross_check", quote_verified=False,
        quote_reason="夹具：还没有逐字比对", proof_text=QUOTE)


def _statements(store: Store) -> list[dict]:
    return [dict(r) for r in store.rows("statements")]


def _reports(store: Store) -> list[str]:
    base = pathlib.Path(store.root) / "reports"
    return sorted(p.name for p in base.glob("*.md")) if base.is_dir() else []


# ------------------------------------------------------------------ a 受控拒 + 改法

def test_a_a_citation_proposition_with_a_revision_note_is_refused_with_a_fix(
        tmp_path):
    """a：引文侧命题形状不合格 ⇒ 受控码 + 可执行改法 + 零写入（稿都不落）。"""
    st = _store(tmp_path)
    seam = _ill_formed_seam()
    got = _register(st, seam)

    assert got.get("ok") is False, got
    assert str(got.get("refused") or got.get("kind") or "") == "proposition_form_refused", got

    fix = str(got.get("fix") or "")
    assert "statement_full" in fix, fix
    assert "条件" in fix and "结论" in fix, fix
    assert "引文" in fix, fix

    nxt = str(got.get("next_step") or "")
    assert "不用 D 裁" in nxt, nxt
    assert "D 对命题台账只有只读权限" in nxt, nxt
    assert "own.register_statement" in nxt, nxt

    # 拒收回执本身把改法也带在 reason 里（模型只读 reason 也拿得到）
    assert "改法：" in str(got.get("error") or ""), got.get("error")

    # 零写入：statements 一行都没有、稿一份都没有、稿号一个没发
    assert _statements(st) == [], _statements(st)
    assert _reports(st) == [], _reports(st)
    assert MP.peek_manuscript_counter(st.root, family="b-proof") == 0

    # 拒收读数进台账（收工门那一格 `readings.proposition_form` 按 role 读得到）
    rows = SEC.proposition_form_rows(st.root)
    assert len(rows) == 1, rows
    assert rows[0]["role"] == "B", rows
    assert rows[0]["checked"] is True and rows[0]["well_formed"] is False, rows
    assert rows[0]["refused"] == "proposition_form_refused", rows
    from agentflow import closing as CL

    read = CL.proposition_form_reading(st)
    assert read["checked"] is True, read
    assert read["by_role"]["B"]["refused"] == 1, read["by_role"]
    assert read["by_role"]["B"]["codes"] == [
        {"code": "proposition_form_refused", "count": 1}], read["by_role"]

    # 闸真的看到了这条命题（不是拿空串判的）
    assert seam.prompts and NOTE[:24] in seam.prompts[0], seam.prompts


# ------------------------------------------------------------------ b 正控

def test_b_a_well_formed_citation_proposition_lands_a_manuscript(tmp_path):
    """b：正控 —— 形状合规的引文命题 ⇒ 登记成功、落 b-稿（稿号 != 命题号）。"""
    st = _store(tmp_path)
    seam = _well_formed_seam()
    got = _register(st, seam, text=PROPOSITION)

    assert got.get("ok") is True, got
    sid = str(got.get("stmt_id") or "")
    assert sid, got
    ms = dict(got.get("citation_manuscript") or {})
    mid = str(ms.get("manuscript_id") or "")
    assert mid and str(ms.get("path") or "") == MP.canonical_rel(
        mid, family="b-proof"), ms
    assert (pathlib.Path(st.root) / str(ms["path"])).is_file(), ms

    rows = _statements(st)
    assert len(rows) == 1, rows
    assert str(rows[0].get("statement_full") or "") == PROPOSITION, rows[0]
    assert str(rows[0].get("manuscript_id") or "") == mid, rows[0]

    assert seam.prompts and PROPOSITION[:16] in seam.prompts[0], seam.prompts


# ------------------------------------------------------------------ c 反真空（fix 文案）

def test_c_an_empty_fix_text_makes_a_red(tmp_path, monkeypatch):
    """c：把 `fix` 文案打桩成空串 ⇒ a 的改法断言必红（判据读的是代码里那一格）。"""
    monkeypatch.setattr(AgentB, "PROPOSITION_FORM_REGISTER_FIX", "")
    st = _store(tmp_path)
    got = _register(st, _ill_formed_seam())

    assert got.get("ok") is False, got
    assert got.get("refused") == "proposition_form_refused", got
    fix = str(got.get("fix") or "")
    assert fix == "", fix
    assert not ("条件" in fix and "结论" in fix and "引文" in fix), (
        "反真空失效：fix 被打桩成空串之后 a 的断言仍然成立 ⇒ a 证明不了文案来自这一格")


# ------------------------------------------------------------------ d 反真空（摘掉闸）

def test_d_removing_the_gate_lands_the_revision_note_as_a_proposition(
        tmp_path, monkeypatch):
    """d：把这道闸摘掉 ⇒ 那段修订说明被收成一条命题（并且落了一份稿）。"""
    monkeypatch.setattr(
        AgentB, "_proposition_form_gate",
        lambda self, **_kw: {"checked": True, "well_formed": True, "submittable": True,
                             "conditions": "夹具", "conclusion": "夹具", "problems": [],
                             "decision": "（探针：摘掉闸）", "refused": "", "reason": "",
                             "actor": ""})
    st = _store(tmp_path)
    got = _register(st, _ill_formed_seam())

    assert got.get("ok") is True, (
        "反真空失效：摘掉命题形态闸之后仍然被拒 ⇒ 这条用例证明不了闸在起作用", got)
    rows = _statements(st)
    assert len(rows) == 1, rows
    landed = str(rows[0].get("statement_full") or "")
    assert landed.startswith("按 V u-000005"), landed
    assert "不要重落新稿号" not in landed, landed
    assert _reports(st), "摘掉闸之后没有落 b-稿 ⇒ d 证明不了落稿这一步在承重"


# ------------------------------------------------------------------ e 语义变更的正面

def test_e_the_same_note_on_an_f_manuscript_is_now_released(tmp_path):
    """e：同一段修订说明在 F 稿上 ⇒ 现在放行（上游已判过；W2 原先判的是它）。"""
    st = _store(tmp_path)
    path = pathlib.Path(st.root) / F_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_manuscript(NOTE), encoding="utf-8")
    conftest.sign_before_registration(st.root, proof_text=PROOF)
    seam = _ill_formed_seam()   # 若 B 真问了，它会判"不是命题"
    got = _b(st, seam).ingest_manuscript(manuscript=F_REL, mode="register")

    assert got.get("ok") is True, (
        "F 手稿仍被 B 侧的形态闸拦（甲：E/F 手稿放行、闸在 B 自己登记那一格）", got)
    assert seam.prompts == [], seam.prompts
    assert SEC.proposition_form_rows(st.root) == [], SEC.proposition_form_rows(st.root)
    rows = _statements(st)
    assert len(rows) == 1, rows
    assert str(rows[0].get("statement_full") or "") == NOTE, rows[0]
    assert "f-proof-000002.md" in _reports(st), _reports(st)

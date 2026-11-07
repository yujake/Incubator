# -*- coding: utf-8 -*-
"""登记命题与写/改证明解耦（业主 2026-11-07 裁定）。

业主原话（逐字，这就是本文件的验收标准）：

    「要让注册命题和写证明两件事解耦，不然无法做到只一遍又一遍修改证明」
    「我只是说F侧落手稿，B的重写一样（只是B不用再注册命题，命题拿已经登记的待优化的）」
    「F侧反复修改一个命题的证明时要直接动那个命题所指手稿的 proof 板块」
    「就是F侧登记新命题F秘书闸拦的那块」

## 判据一览

| # | 造什么 | 期望 |
|---|---|---|
| a | 手稿登记 1 次 + 连续重写 3 次（正文各不同） | 版本历史 4 条、sha 全不同、`proof_no` 1→4；形态闸只调用 1 次；`statements` 行数不变 |
| b | 重写时改命题正文 | 受控拒 `proposition_text_changed`；盘上 `## 命题` 一个字没动 |
| c | 98 那三条「作业规格」 | 登记那一刻被形态闸拒；手稿不落盘、版本历史不追加 |
| d | 反真空：摘掉「已登记 ⇒ 只重写」 | a 那一组断言变红（闸调用次数从 1 变 4） |
| i | 同一命题重写 3 次 | 盘上始终只有 1 份稿；`## 命题` / `## 依赖` 分节哈希逐次相同，`## 证明` 逐次不同；头部 `proof_no` 1→4 |
| g | F→B 绕行 | 调用方是 F ⇒ 受控拒 `f_proposition_must_be_a_manuscript` |
| h | lemma 死锁 | F 登记一条引理 ⇒ 手稿头 `- 证据种类：lemma`；B 的收录读得到它 |
| — | 登记期的异常 | 形态闸抛异常 ⇒ 受控拒 + 形态台账有一行「没判成」 |

零模型调用：形态闸用替身（只记调用次数），落稿与重写走真的 `proofregistry`。
"""
from __future__ import annotations

import pathlib

import pytest
from conftest import seed_statement_row
from agentflow import proofregistry as R
from agentflow import vsigns as VS
from agentflow.agent_f import AgentF
from agentflow.store import Store

PLAN = "0000"
SID = "s1"
LABEL = f"F 攻坚 {PLAN} 子目标 {SID}"
TEXT = "设 f 在 [0,1] 上连续，则 f 一致连续。"
OTHER = "设 g 在 [0,1] 上可导，则 g 一致连续。"
FULL = TEXT
PROOFS = ["第一版：取 δ=ε，逐点验证。",
          "第二版：换用反证法，先假定存在 ε₀。",
          "第三版：用有限覆盖，把区间分成有限段。",
          "第四版：整理成一行：由 Heine–Cantor 定理即得。"]
CITES = [{"stmt_id": "000001", "quote": "由引理甲", "step": "第 1 步", "path_group": 1}]
AT = "2026-11-07T10:00:00+08:00"

SPEC_036 = (
    "本轮产物必须是 proof（禁止 reduction、禁止 dead_end、禁止拆出新子目标）：把 "
    "reports/f-0002-carrier-v3.md 的既有正文原样作为这一轮的证明正文提交，命题号 0002、"
    "证明号 1，不重写任何数学内容。；这一条的可检验形式：'判据：attack.step 的返回里 "
    "manuscript_published=true 且 manuscript_path='reports/f-proof-0002.md'")
SPEC_037 = (
    "本轮产物必须是 proof，且证明正文原样取自盘上文件 reports/f-0002-carrier-v3.md："
    "该文件的全文就是本次要发布的证明正文，一字不改。禁止 reduction、禁止 dead_end、"
    "禁止生成任何新论证。发布落点尽量指向 reports/f-proof-0002.md")
SPEC_039 = SPEC_037 + "并逐字给出 fs.stat 的 size 与 sha256"


class _FormStub:
    """F 的秘书替身：只实现形态判定这一问（记下每一次调用）。"""

    role = "F"
    seam = object()

    def __init__(self, *, well_formed: bool = True, raises: BaseException | None = None):
        self.well_formed = bool(well_formed)
        self.raises = raises
        self.calls: list[dict] = []

    def judge_proposition_form(self, **kw):
        self.calls.append(dict(kw))
        if self.raises is not None:
            raise self.raises
        return {"checked": True, "well_formed": self.well_formed,
                "conditions": "设 f 在 [0,1] 上连续" if self.well_formed else "",
                "conclusion": "则 f 一致连续" if self.well_formed else "",
                "problems": [] if self.well_formed else ["这是流程要求，不是数学命题"],
                "decision": "夹具：形态判定",
                "refused": "" if self.well_formed else "proposition_form_refused",
                "reason": "夹具：形态判定", "cached": False}

    def wash_dependency_face(self, text: str, **_kw) -> dict:
        return {"checked": True, "text": str(text), "actor": "fake-F-secretary",
                "washed": False, "deps_refused": "", "deps_refused_findings": [],
                "deps_section_filled": "", "deps_washing": [],
                "reason": "夹具：依赖面本来就合规"}


def _ws(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _f(st: Store, stub: _FormStub | None = None) -> AgentF:
    f = AgentF(st, config={"workspace_root": str(st.root), "plan_id": PLAN})
    f.f_secretary = stub or _FormStub()
    return f


def _hand(f: AgentF, body: str, *, text: str = TEXT, sid: str = SID,
          stable_row: dict | None = None, at: str = AT):
    return f._hand_proof(
        full=text, text=text, body=body, sid=sid,
        plan={"plan_id": PLAN, "problem_key": "PK"},
        sg={"sid": sid, "text": text},
        manuscript_text="",
        manuscript_received={"source": "param", "chars": len(body),
                             "section_rows": len(CITES), "refs_in_proof": 0,
                             "preview_ok": True, "refused": "", "why": ""},
        cites=["stmt:000001"], tier={"kind": "heuristic", "why": "夹具"},
        dependency_rows=[dict(x) for x in CITES], existing_row=stable_row,
        )


def _seeded(st: Store) -> dict:
    return seed_statement_row(
        st, proof_text=PROOFS[0], statement_full=FULL, statement_text=TEXT,
        kind="conjecture", label=LABEL, stmt_id="000041")


def _manuscript_text(st: Store) -> str:
    return (pathlib.Path(st.root) / f"reports/f-proof-000041.md").read_text(encoding="utf-8")


# ---------------------------------------------------------------- a：登记一次 + 重写 3 次

def test_a_one_registration_and_three_rewrites(tmp_path):
    """a：登记 1 次 + 重写 3 次 ⇒ 闸只跑 1 次、版本 4 条、statements 行数不变。"""
    st = _ws(tmp_path)
    row = _seeded(st)
    stub = _FormStub()
    f = _f(st, stub)
    before_rows = len(list(st.rows("statements")))

    rounds = [_hand(f, PROOFS[0], stable_row=row)]
    for body in PROOFS[1:]:
        rounds.append(_hand(f, body, stable_row=row))

    assert [r["proof_mode"] for r in rounds] == [
        "registered", "rewritten", "rewritten", "rewritten"], rounds
    assert [r["proof_no"] for r in rounds] == [1, 2, 3, 4], rounds
    shas = [str(r["proof_sha256"]) for r in rounds]
    assert len(set(shas)) == 4 and all(len(s) == 64 for s in shas), shas
    # 形态闸只在"登记新命题"那一次跑
    assert len(stub.calls) == 1, stub.calls
    # statements 行数全程不变
    assert len(list(st.rows("statements"))) == before_rows == 1
    # 版本历史 4 条（手稿头的 append-only 那一行）
    entries = R.entries_on_disk(st.root)
    assert len(entries) == 1, entries
    versions = entries[0]["versions"]
    assert [v["proof_no"] for v in versions] == [1, 2, 3, 4], versions
    assert len({v["sha256"] for v in versions}) == 4, versions


# ---------------------------------------------------------------- b：改命题正文 ⇒ 受控拒

def test_b_changing_the_proposition_on_rewrite_is_refused(tmp_path):
    """b：重写时把命题正文换了 ⇒ 受控拒，盘上 `## 命题` 一个字没动。"""
    st = _ws(tmp_path)
    row = _seeded(st)
    stub = _FormStub()
    f = _f(st, stub)
    first = _hand(f, PROOFS[0], stable_row=row)
    assert first["ok"] is True, first
    prop_before = R.section_hashes(_manuscript_text(st))["## 命题"]

    bad = _hand(f, PROOFS[1], text=OTHER, stable_row=row)
    assert bad["ok"] is False, bad
    assert bad["kind"] == "proposition_text_changed", bad
    assert bad["refused_kind"] == "proposition_text_changed", bad
    assert "放弃" in bad["error"] and "换号" in bad["error"], bad["error"]
    # 一个字节都没动：命题那一节的分节哈希与登记那一刻相同
    assert R.section_hashes(_manuscript_text(st))["## 命题"] == prop_before
    assert len(stub.calls) == 1, "改命题正文不该再跑一次形态闸（它不是重写）"


# ---------------------------------------------------------------- c：98 的三条作业规格

@pytest.mark.parametrize("text", [SPEC_036, SPEC_037, SPEC_039],
                         ids=["000036", "000037", "000039"])
def test_c_a_work_spec_is_refused_at_registration_and_writes_nothing(tmp_path, text):
    """c：作业规格在手稿登记那一刻被形态闸拒 ⇒ 手稿不落盘、版本历史不追加。"""
    st = _ws(tmp_path)
    stub = _FormStub(well_formed=False)
    f = _f(st, stub)
    got = _hand(f, "证明正文", text=text, sid="S9")
    assert got["ok"] is False, got
    assert got["kind"] == "proposition_form_refused", got
    assert got["refused_kind"] == "proposition_form_refused", got
    assert got["proposition_form"]["checked"] is True
    assert got["proposition_form"]["well_formed"] is False
    assert len(got["proposition_form"]["problems"]) == 1, got["proposition_form"]
    reports = list((pathlib.Path(st.root) / "reports").glob("*.md")) \
        if (pathlib.Path(st.root) / "reports").is_dir() else []
    assert reports == [], f"闸判不过时手稿不许落盘：{reports}"
    assert R.entries_on_disk(st.root) == []
    assert len(list(st.rows("statements"))) == 0


# ---------------------------------------------------------------- d：反真空

def test_d_removing_the_rewrite_branch_makes_a_red(tmp_path, monkeypatch):
    """d：把「已登记 ⇒ 只重写」摘掉（每次都当新登记）⇒ a 的闸计数断言必红。"""
    st = _ws(tmp_path)
    row = _seeded(st)
    stub = _FormStub()
    f = _f(st, stub)

    def _always_new(root, **kw):   # 模拟"登记分支永远成立"：看不到盘上已有登记条目
        return {"checked": True, "exists": False, "path": "", "text": "",
                "entry": {"label": "", "versions": [], "proof_no": 0, "sha256": "",
                          "fingerprint": ""},
                "why": ""}

    monkeypatch.setattr(R, "read_entry", _always_new)
    for body in PROOFS:
        _hand(f, body, stable_row=row)
    assert len(stub.calls) == 4, (
        "反真空失效：摘掉「已登记 ⇒ 只重写」之后闸仍然只跑一次 ⇒ a 证明不了那条分支在承重")


# ---------------------------------------------------------------- i：只动 `## 证明` 那一块

def test_i_rewrite_touches_only_the_proof_section(tmp_path):
    """i：同一命题重写 3 次 ⇒ 盘上 1 份稿、分节哈希只变 `## 证明`、proof_no 递增。"""
    st = _ws(tmp_path)
    row = _seeded(st)
    f = _f(st)
    first = _hand(f, PROOFS[0], stable_row=row)
    base = dict(first["section_hashes"])
    assert set(base) == {"## 命题", "## 证明", "## 依赖"}, base
    seen = [dict(first["section_hashes"])]
    nos = [first["proof_no"]]
    for body in PROOFS[1:]:
        got = _hand(f, body, stable_row=row)
        seen.append(dict(got["section_hashes"]))
        nos.append(got["proof_no"])
    assert nos == [1, 2, 3, 4], nos
    # 盘上始终只有 1 份该命题的手稿（不许出现 -v2 / -p2 这一族新名）
    files = sorted(p.name for p in (pathlib.Path(st.root) / "reports").glob("*.md"))
    assert files == ["f-proof-000041.md"], files
    for hashes in seen[1:]:
        assert hashes["## 命题"] == base["## 命题"], "命题那一节一个字都不许动"
        assert hashes["## 依赖"] == base["## 依赖"], "依赖那一节没有新引用 ⇒ 逐字节相同"
        assert hashes["## 证明"] != base["## 证明"], "证明那一节必须变"
    assert len({h["## 证明"] for h in seen}) == 4, seen
    # 头部：proof_no 1→4、正文 sha 与版本记录一致
    entry = R.parse_entry(_manuscript_text(st))
    assert entry["proof_no"] == 4, entry
    assert [v["proof_no"] for v in entry["versions"]] == [1, 2, 3, 4], entry["versions"]


# ---------------------------------------------------------------- g：F→B 那条绕行

def test_g_an_f_caller_cannot_register_through_b(tmp_path, monkeypatch):
    """g：调用方是 F ⇒ B 的登记入口受控拒，并点名"走手稿登记"。"""
    from agentflow.agent_b import AgentB
    from agentflow.agent_b import register_statement as RS

    st = _ws(tmp_path)
    b = AgentB(st, extractor=None, extract_text=None)
    monkeypatch.setattr(RS, "_caller_role", lambda: "F")
    got = b.register_statement(
        statement_full=FULL, statement_text=TEXT, kind="conjecture",
        origin="own_result", evidence_kind="heuristic",
        quote_reason="夹具：F 直接派 B 登记")
    assert got.get("ok") is False, got
    assert got.get("kind") == RS._RegisterStatement.F_CALLER_REFUSED, got
    assert "手稿" in str(got.get("error") or ""), got
    assert len(list(st.rows("statements"))) == 0


# ---------------------------------------------------------------- h：lemma 打通

def test_h_a_lemma_lands_as_lemma_in_the_manuscript_and_b_can_read_it(tmp_path):
    """h：F 登记一条引理 ⇒ 手稿头 `- 证据种类：lemma` ⇒ B 的收录读得到。"""
    from agentflow.agent_b import register_statement as RS

    st = _ws(tmp_path)
    stub = _FormStub()
    f = _f(st, stub)
    got = f._hand_proof(
        full=TEXT, text=TEXT, body=PROOFS[0], sid=SID,
        plan={"plan_id": PLAN, "problem_key": "PK"},
        sg={"sid": SID, "text": TEXT, "kind": "lemma"},
        manuscript_text="", manuscript_received={"source": "param", "chars": 1,
                                                 "section_rows": 0, "refs_in_proof": 0},
        cites=[], tier={"kind": "heuristic", "why": "夹具"},
        dependency_rows=[], existing_row={})
    assert got["ok"] is True, got
    text = (pathlib.Path(st.root) / str(got["manuscript_path"])).read_text(encoding="utf-8")
    assert "- 证据种类：lemma" in text, text
    assert RS._declared_manuscript_kind(text=text) == "lemma"
    # 词表外的手稿头不许落成 kind（作者写的字节不能绕开 kind 的语义）
    assert RS._declared_manuscript_kind(
        text=text.replace("- 证据种类：lemma", "- 证据种类：whatever")) == ""
    # 端到端：B 收录同一条命题（V 的 pending 签按正文 sha 认领）⇒ statements 那一行
    # kind=lemma（手稿头的 `- 证据种类：lemma` 被如实采纳）⇒ 它可以被
    # `statementabandon` 的 `salvaged` 引用（`SALVAGED_KINDS=("lemma",)`）。
    from agentflow import depsection as DS
    from agentflow import secretary as SEC
    from agentflow.agent_b import AgentB
    from conftest import sign_before_registration

    body = DS.proof_body(text).strip("\n")
    sign_before_registration(st.root, proof_text=body)
    b = AgentB(st, extractor=None, extract_text=None)
    first = b.register_statement(
        statement_full=TEXT, statement_text=TEXT, origin="own_result",
        kind="conjecture", label=f"F 攻坚 {PLAN} 子目标 {SID}",
        proof_text=body, proof_manuscript=text,
        line_range={"label": str(got["manuscript_path"])},
        quote_reason="夹具：V 的 pending 签在盘上，B 按 sha 认领")
    assert first.get("ok") is True, first
    row = next(r for r in st.rows("statements")
               if str(r["stmt_id"]) == str(first["stmt_id"]))
    assert row["kind"] == "lemma", row
    assert row["kind"] in SEC.PROPOSITION_KINDS, row
    assert (first.get("kind_upgraded_from_manuscript") or {}).get("to") == "lemma", first


# ---------------------------------------------------------------- 异常 ⇒ 受控拒 + 台账

def test_a_gate_that_raises_is_a_controlled_refusal_and_is_recorded(tmp_path):
    """形态判定那一问抛异常 ⇒ 受控拒（不穿透），且形态台账有一行「没判成」。"""
    from agentflow import secretary as SEC

    st = _ws(tmp_path)
    stub = _FormStub(raises=TimeoutError("模型超时"))
    f = _f(st, stub)
    got = _hand(f, "证明正文", sid="S8")
    assert got["ok"] is False, got
    assert got["kind"] == "proposition_form_refused", got
    assert got["proposition_form"]["checked"] is False, got["proposition_form"]
    assert "没判成" in str(got.get("error") or ""), got
    # 台账里必须有一行（否则 judged=0 与"没跑过闸"不可分）
    rows = SEC.proposition_form_rows(st.root)
    assert len(rows) == 1, rows
    assert rows[0]["checked"] is False and "TimeoutError" in str(rows[0]["reason"]), rows


# ---------------------------------------------------------------- B 的重写

def test_b_rewrite_lands_the_same_manuscript_and_never_adds_a_row(tmp_path):
    """c：B 重写同一命题 ⇒ 重写 `b-proof-<号>.md`，`statements` 行数不变。"""
    from agentflow import depsection as DS
    from agentflow.agent_b import AgentB
    from conftest import sign_before_registration

    st = _ws(tmp_path)
    row = seed_statement_row(
        st, proof_text="B 收录时的第一版证明。", statement_full=FULL,
        statement_text=TEXT, kind="conjecture", label="B 优化 000041",
        evidence_kind="heuristic", line_range={"label": "reports/attack-0000.md"},
        stmt_id="000041")
    before = len(list(st.rows("statements")))
    b = AgentB(st, extractor=None, extract_text=None, config={})
    bodies = ["B 重写后的第二版：先取 ε>0。", "B 重写后的第三版：改用有限覆盖。"]
    seen: list[dict] = []
    for i, body in enumerate(bodies, start=2):
        sign_before_registration(st.root, proof_text=body)
        got = b.register_statement(
            statement_full=FULL, statement_text=TEXT, origin="own_result",
            kind="conjecture", label="B 优化 000041", proof_text=body,
            evidence_kind="heuristic", line_range={"label": "reports/attack-0000.md"},
            quote_reason="夹具：B 在 V 签之后重写证明")
        seen.append(dict(got))
        assert len(list(st.rows("statements"))) == before == 1, (
            f"第 {i} 版证明让 statements 多出了行：{list(st.rows('statements'))}")
    # 盘上仍然只有一份 B 的手稿（同一个路径、就地改）
    files = sorted(p.name for p in (pathlib.Path(st.root) / "reports").glob("b-proof-*.md"))
    assert files == ["b-proof-000041.md"], files
    text = (pathlib.Path(st.root) / "reports/b-proof-000041.md").read_text(encoding="utf-8")
    assert DS.SECTION_HEADING in text, text
    assert VS.manuscript_proof_body(text).strip("\n") == bodies[-1], text
    # 第二版开始走的是 `proofregistry`：头部有版本记录
    entry = R.parse_entry(text)
    assert entry["proof_no"] >= 2, entry
    assert entry["versions"], entry


# ---------------------------------------------------------------- 收工读数

def test_the_closing_reading_shows_registration_once_and_n_versions(tmp_path):
    """收工读数 `proof_revisions`：登记 1 次 / 证明 N 版 / 逐版 sha 与 proof_no。"""
    from agentflow import closing as CL

    st = _ws(tmp_path)
    row = _seeded(st)
    f = _f(st)
    for body in PROOFS:
        _hand(f, body, stable_row=row)
    read = CL.proof_revisions_reading(st) if hasattr(CL, "proof_revisions_reading") \
        else CL._proof_revisions_reading(st)
    assert read["checked"] is True, read
    assert read["registrations"] == 1, read
    assert read["proof_versions"] == 4, read
    one = read["propositions"][0]
    assert one["registrations"] == 1 and one["proof_count"] == 4, one
    assert [v["proof_no"] for v in one["versions"]] == [1, 2, 3, 4], one
    assert "登记 1 次" in read["reason"] and "4 版" in read["reason"], read["reason"]

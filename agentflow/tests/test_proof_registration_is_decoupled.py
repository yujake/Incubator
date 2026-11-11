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
| a | 手稿登记 1 次 + 连续重写 3 次（正文各不同） | 版本历史恰好 1 条（当前那一版，sha 对盘上 `## 证明`）、sha 全不同、`proof_no` 恒 1；形态闸只调用 1 次；`statements` 行数不变 |
| b | 重写时改命题正文 | 受控拒 `proposition_text_changed`；盘上 `## 命题` 一个字没动 |
| c | 98 那三条「作业规格」 | 登记那一刻被形态闸拒；手稿不落盘、版本历史不追加 |
| d | 反真空：摘掉「已登记 ⇒ 只重写」 | a 那一组断言变红（闸调用次数从 1 变 4） |
| i | 同一命题重写 3 次 | 盘上始终只有 1 份稿；`## 命题` / `## 依赖` 分节哈希逐次相同，`## 证明` 逐次不同；头部 `proof_no` 恒 1、版本历史恰好 1 条 |
| g | F→B 绕行 | 调用方是 F ⇒ 受控拒 `f_proposition_must_be_a_manuscript` |
| h | lemma 死锁 | F 登记一条引理 ⇒ 手稿头 `- 证据种类：lemma`；B 的收录读得到它 |
| — | 登记期的异常 | 形态闸抛异常 ⇒ 受控拒 + 形态台账有一行「没判成」 |

零模型调用：形态闸用替身（只记调用次数），落稿与重写走真的 `proofregistry`。
"""
from __future__ import annotations

import json
import pathlib
import re

import pytest
from conftest import seed_statement_row
from _credential_fixture import issue_credential
from agentflow import proofregistry as R
from agentflow import vsigns as VS
from agentflow.agent_f import AgentF
from agentflow.store import Store

PLAN = "0000"
SID = "s1"
#: 这一组夹具的固定稿号（新口径：稿名只由 F 自己的稿号决定；刻意取得与命题号 000041
#: 不同 —— 于是"稿名带的是稿号而不是命题号"是量得出来的）。
MID = "000777"
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
        manuscript_id=MID,
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
    return (pathlib.Path(st.root) / f"reports/f-proof-{MID}.md").read_text(encoding="utf-8")


# ---------------------------------------------------------------- a：登记一次 + 重写 3 次

def test_a_one_registration_and_three_rewrites(tmp_path):
    """a：登记 1 次 + 重写 3 次 ⇒ 闸只跑 1 次、一份稿一份证明、statements 行数不变。"""
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
    # 业主 2026-11-11：「同稿号多个版本是错误的，一个稿号就相当于是该稿的文件名，
    # 不再细分 version 几，应该在改正文时 edit 它」＋「proof_no 确实该退役……
    # 手稿产出侧和 V 签侧甚至呈递侧可退役」⇒ 读数里不再有这一格，盘上的稿头也没有
    # `- 证明号：` 那一行。反面：谁把它加回来（读数或渲染），这两条立刻红。
    assert all("proof_no" not in r for r in rounds), rounds
    text_now = _manuscript_text(st)
    assert "- 证明号：" not in text_now, text_now[:600]
    assert re.search(r"(?m)^- 版本：p\d+@", text_now) is None, text_now[:600]
    shas = [str(r["proof_sha256"]) for r in rounds]
    assert len(set(shas)) == 4 and all(len(s) == 64 for s in shas), shas
    # 形态闸只在"登记新命题"那一次跑
    assert len(stub.calls) == 1, stub.calls
    # statements 行数全程不变
    assert len(list(st.rows("statements"))) == before_rows == 1
    # 一个稿号 = 一份文件 = 一份证明 ⇒ 版本历史恰好 1 条（当前那一版），
    # 且它的 sha 就是盘上 `## 证明` 那一节的 sha（同一把尺：`proof_sha`）。
    entries = R.entries_on_disk(st.root)
    assert len(entries) == 1, entries
    versions = entries[0]["versions"]
    assert len(versions) == 1, versions
    # 新写的版本段没有 `pN@` ⇒ 读回来的号是"没写"（0），不是恒真的 1。
    assert versions[0]["proof_no"] == 0, versions
    body_now = VS.manuscript_proof_body(text_now).strip("\n")
    assert versions[0]["sha256"] == R.proof_sha(body_now), versions
    assert versions[0]["sha256"] == str(rounds[-1]["proof_sha256"]), versions
    # 反面：把 `- 证明号：` 加回渲染 ⇒ `test_a2_*` 那一条红；把 bump 加回来 ⇒
    # `test_a_negative_control_restoring_the_bump_makes_the_history_red` 红。


def test_a_negative_control_restoring_the_bump_makes_the_history_red(
        tmp_path, monkeypatch):
    """反真空①：把 `proof_no` 的 bump 加回去（旧版本模型）⇒ a 的版本历史那条红。

    判据 a 现在是两个合取：`len(versions) == 1` 且那一条的 sha == 盘上 `## 证明`
    的 sha。这里把那一步换回旧口径（每次都 `+1`），然后照 a 的算法重算一遍：
    它必须不成立 —— 否则 a 那条「恰好 1 条」证明不了"重写不涨号"在承重。
    """
    st = _ws(tmp_path)
    row = _seeded(st)
    f = _f(st)

    state = {"n": 1}

    def _bump(_rel, _entry):   # 旧口径：重写就 +1（业主 2026-11-11 已作废）
        state["n"] += 1
        return int(state["n"])

    monkeypatch.setattr(R, "_legacy_proof_no_of", _bump)
    for body in PROOFS:
        _hand(f, body, stable_row=row)

    versions = R.entries_on_disk(st.root)[0]["versions"]
    body_now = VS.manuscript_proof_body(_manuscript_text(st)).strip("\n")
    # 先量"模拟真的生效"：旧口径下重写各记一个新号 2/3/4（第一版 canonical 不写号，
    # 读回来是 0）。否则下面那个 False 是假的。
    assert [v["proof_no"] for v in versions] == [0, 2, 3, 4], versions
    held = (len(versions) == 1
            and str(versions[0].get("sha256") or "") == R.proof_sha(body_now))
    assert held is False, (
        "把 bump 加回去之后版本历史仍然是「恰好 1 条且 sha 对得上」⇒ "
        "a 的版本历史判据是恒真的", versions)


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
    """i：同一命题重写 3 次 ⇒ 盘上 1 份稿、分节哈希只变 `## 证明`、不再写 `proof_no`。"""
    st = _ws(tmp_path)
    row = _seeded(st)
    f = _f(st)
    first = _hand(f, PROOFS[0], stable_row=row)
    base = dict(first["section_hashes"])
    assert set(base) == {"## 命题", "## 证明", "## 依赖"}, base
    seen = [dict(first["section_hashes"])]
    readers = [first]
    for body in PROOFS[1:]:
        got = _hand(f, body, stable_row=row)
        seen.append(dict(got["section_hashes"]))
        readers.append(got)
    # 业主 2026-11-11：`proof_no` 在手稿产出侧退役 ⇒ 四笔读数里都没有这一格。
    assert all("proof_no" not in r for r in readers), readers
    # 盘上始终只有 1 份该命题的手稿（不许出现 -v2 / -p2 这一族新名），
    # 而且它按 F 自己的稿号命名、不按命题号（2026-11-10 口径）。
    files = sorted(p.name for p in (pathlib.Path(st.root) / "reports").glob("*.md"))
    assert files == [f"f-proof-{MID}.md"], files
    assert not any(name == f"f-proof-{row['stmt_id']}.md" for name in files), (
        "稿名里带上了命题号（旧口径的回潮）", files, row["stmt_id"])
    for hashes in seen[1:]:
        assert hashes["## 命题"] == base["## 命题"], "命题那一节一个字都不许动"
        assert hashes["## 依赖"] == base["## 依赖"], "依赖那一节没有新引用 ⇒ 逐字节相同"
        assert hashes["## 证明"] != base["## 证明"], "证明那一节必须变"
    assert len({h["## 证明"] for h in seen}) == 4, seen
    # 头部：一个稿号一份文件一份证明 ⇒ 稿头没有 `- 证明号：`、版本历史恰好 1 条
    # （当前那一版），且这一条的 sha 就是盘上 `## 证明` 的 sha。
    entry = R.parse_entry(_manuscript_text(st))
    assert "- 证明号：" not in _manuscript_text(st), _manuscript_text(st)[:600]
    assert entry["proof_no"] == 0, entry
    assert len(entry["versions"]) == 1, entry["versions"]
    assert entry["versions"][0]["proof_no"] == 0, entry["versions"]
    body_now = VS.manuscript_proof_body(_manuscript_text(st)).strip("\n")
    assert entry["versions"][0]["sha256"] == R.proof_sha(body_now), entry["versions"]
    assert entry["sha256"] == R.proof_sha(body_now), entry
    # 反面：谁让重写落成 `-p2` / `-p3` 这一族新名 ⇒ 上面"盘上只有一份"必红。
    # 反真空在 `test_i_negative_control_a_new_name_per_rewrite_makes_it_red`。


def test_i_negative_control_a_new_name_per_rewrite_makes_it_red(tmp_path, monkeypatch):
    """反真空②：让重写每轮落成新名（`-p2` / `-p3` 那一族）⇒ i 的「盘上只有一份」红。

    i 的算法是 `files == [f"f-proof-{MID}.md"]`。这里把落点换成旧的"一版一文件"
    形状（同一个稿号，第 N 轮拼上 `-pN`）—— 这正是"一个稿号多个版本"的物理形态。
    若盘上仍然只有一份，i 那条判据就是恒真的。
    """
    st = _ws(tmp_path)
    row = _seeded(st)
    f = _f(st)
    state = {"round": 1}

    def _numbered(*, family, statement_id="", plan_id="", manuscript_id=""):
        return f"reports/f-proof-{manuscript_id}-p{state['round']}.md"

    monkeypatch.setattr(R, "entry_relpath", _numbered)
    for i, body in enumerate(PROOFS, start=1):
        state["round"] = i
        _hand(f, body, stable_row=row)

    files = sorted(p.name for p in (pathlib.Path(st.root) / "reports").glob("*.md"))
    # 先量"模拟真的生效"：旧形状下每轮一个新名（否则下面那个不等是假的）。
    assert files == [f"f-proof-{MID}-p{n}.md" for n in (1, 2, 3, 4)], files
    assert files != [f"f-proof-{MID}.md"], (
        "让重写每轮落成新名之后盘上仍然只有一份 ⇒ i 的「盘上只有一份」是恒真的", files)


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
        manuscript_id=MID,
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
    """c：B 显式落稿重写同一命题 ⇒ 同一份 b-proof 就地改，statements 行数不变。

    2026-11-10（D1）：登记不再顺手落稿；旧断言（"两次提交后盘上有 b-proof"）钉的是
    被拒登记的副作用 —— 实测旧实现上两笔登记其实都被 `proof_without_v_sign` 拒，
    文件只是 D1 留下的。现在改成显式 `land_manuscript` + 覆盖正文的台账签，登记
    真的成功；断言强度没降：仍然量"一份稿 / 同一路径 / 正文是最后一版 / 版本记录"。

    2026-11-10（T1 收口）：D268 批 2 之后签只认 `vsigns.sign_reading` 的可复算凭据；
    原来那几行 `sign_for_the_gate` 只够 #p1 那一档，而这一笔的稿头是 #p2 / #p3 ⇒ 必须
    把对应证明号的三票真发成 `out/vsigns/<sha>.json`。这里改用批 2 自己那份夹具
    （`_credential_fixture.issue_credential`：三票同源 `review_call` + `vsigns.issue`）。
    改的是夹具，不是断言：这一格原本就是"V 签过这一版"的替身；现在它签的是同一份
    正文的一份可复算签，而"#p2 不借 #p1 的光"这条口径也因此被真正量到。
    """
    from agentflow import depsection as DS
    from agentflow.agent_b import AgentB

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
    rel = ""
    for i, body in enumerate(bodies, start=2):
        landed = b.land_manuscript(
            statement_id="000041", statement_full=FULL, proof_text=body,
            label="B 优化 000041", proof_no=1)
        assert landed.get("ok") is True, landed
        rel = str(landed.get("path") or "")
        # 2026-11-11（业主裁定 ①「B侧稿号和命题号耦合是错的」）：B 的稿号由 B 自己的
        # 号段发 ⇒ 签的载体是这一笔落成的那个路径，不再写死 `b-proof-<命题号>`。
        # 断言强度不降：仍然量"一份稿 / 同一路径 / 正文是最后一版 / 版本记录"。
        from agentflow import manuscriptids as _MIDS

        _mid = str(landed.get("manuscript_id") or "")
        assert _mid, landed
        assert rel == _MIDS.canonical_rel(_mid, family="b-proof"), landed
        # 这一笔的稿头证明号：一个稿号一份文件一份证明（业主 2026-11-11）⇒
        # 两次就地改都还是 #p1，签也按 #1 认领（旧口径的 #p1→#p2 已作废）。
        issue_credential(st.root, proof_text=body, statement_id="000041",
                         manuscript=rel, proof_no=1)
        manuscript = (pathlib.Path(st.root) / rel).read_text(encoding="utf-8")
        got = b.register_statement(
            statement_full=FULL, statement_text=TEXT, origin="own_result",
            kind="conjecture", label="B 优化 000041", proof_text=body,
            proof_manuscript=manuscript,
            evidence_kind="heuristic", line_range={"label": "reports/attack-0000.md"},
            quote_reason="夹具：B 在 V 签之后重写证明")
        assert got.get("ok") is True, got
        seen.append(dict(got))
        assert len(list(st.rows("statements"))) == before == 1, (
            f"第 {i} 版证明让 statements 多出了行：{list(st.rows('statements'))}")
    # 盘上仍然只有一份 B 的手稿（同一个路径、就地改）
    files = sorted(p.name for p in (pathlib.Path(st.root) / "reports").glob("b-proof-*.md"))
    assert files == [rel.rsplit("/", 1)[-1]], files
    text = (pathlib.Path(st.root) / rel).read_text(encoding="utf-8")
    assert DS.SECTION_HEADING in text, text
    assert VS.manuscript_proof_body(text).strip("\n") == bodies[-1], text
    # 第二版开始走的是 `proofregistry`：头部有版本记录 —— 一个稿号一份证明 ⇒
    # 恰好 1 条（当前那一版），不再写 `proof_no`，sha 就是盘上 `## 证明` 的 sha。
    entry = R.parse_entry(text)
    assert "- 证明号：" not in text, text[:600]
    assert entry["proof_no"] == 0, entry
    assert len(entry["versions"]) == 1, entry["versions"]
    assert entry["versions"][0]["proof_no"] == 0, entry["versions"]
    assert entry["versions"][0]["sha256"] == R.proof_sha(
        VS.manuscript_proof_body(text).strip("\n")), entry["versions"]


# ---------------------------------------------------------------- 收工读数

def test_the_closing_reading_shows_registration_once_and_n_versions(tmp_path):
    """收工读数 `proof_revisions`：登记 1 次 / 一份稿一份证明（版本恰好 1 条）。"""
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
    # 一个稿号 = 一份文件 = 一份证明（业主 2026-11-11）⇒ 重写不涨"版本"。
    assert read["proof_versions"] == 1, read
    one = read["propositions"][0]
    assert one["registrations"] == 1 and one["proof_count"] == 1, one
    assert [v["proof_no"] for v in one["versions"]] == [0], one
    body_now = VS.manuscript_proof_body(_manuscript_text(st)).strip("\n")
    assert one["versions"][0]["sha256"] == R.proof_sha(body_now), one
    assert "登记 1 次" in read["reason"] and "1 版" in read["reason"], read["reason"]


# ================================================================ A1 / A2 / A3
#
# 2026-11-07 业主审计（a02d4682）：上面 a/d 那两条走的是 `_hand_proof(manuscript_text="")`，
# 而生产路径是 `_apply_round` → `proof_manuscript` 先写一份计划稿 → 洗稿写回盘
# → 才登记。那两笔写盘都把登记条目的头部（`- 标签：` / 正文 sha / 版本）覆盖成普通稿，
# 于是每一轮都读成"新命题"：实测 3 轮 `modes=[registered×3]`、形态闸 3 次、
# `proof_no=[1,1,1]`、版本历史只有 1 条 —— 解耦在默认路径上没有生效。
#
# 下面三条钉的就是"生产路径"本身（不带 `manuscript_text=""` 这种夹具形状）。

class _ProofSeam:
    """一次性推理缝：每轮回一份 proof 产物（`complete(prompt) -> str`）。"""

    def __init__(self, body: str) -> None:
        self.body = str(body)

    def complete(self, prompt: str) -> str:
        return json.dumps({"product": "proof", "strategy": "套用已知定理",
                           "why_strategy": "夹具：由在册定理逐条读出",
                           "steps": [{"n": 1, "text": self.body,
                                      "cites": [], "assumption": True}]},
                          ensure_ascii=False)


def _production_rounds(st: Store, bodies, monkeypatch=None):
    """生产路径跑 N 轮 F 的 proof 档（`AgentF.step`，与真机同一入口）。

    返回 `(plan_id, rounds, stub)`；`rounds` 是每一轮 `step` 的返回值。
    """
    stub = _FormStub()
    f = AgentF(st, config={"workspace_root": str(st.root)},
               llm=_ProofSeam(bodies[0] if bodies else ""))
    f.f_secretary = stub
    plan = f.create_plan("引理：由定义推出目标结论", "PK-A1-PRODUCTION", subgoals=[
        {"sid": "s1", "text": "由定义推出目标结论", "owner": "F",
         "testable": "同一命题的证明每轮重写"}])
    pid = str(plan["plan_id"])
    rounds = []
    for body in bodies:
        f.llm = _ProofSeam(body)
        rounds.append(dict(f.step(pid)))
    return pid, rounds, stub


def test_a1_the_production_path_registers_once_and_rewrites_after(tmp_path):
    """A1：生产路径 3 轮 ⇒ `[registered, rewritten, rewritten]`、闸 1 次、一份稿一份证明。

    改前（a02d4682）读数：`[registered, registered, registered]`、闸 3 次、
    `proof_no=[1,1,1]`、版本历史 `[1]` —— 因为 `proof_manuscript` 与洗稿写回盘
    都把登记条目头部的元信息覆盖掉了。
    """
    st = _ws(tmp_path)
    pid, rounds, stub = _production_rounds(st, PROOFS[:3])

    assert [r.get("proof_mode") for r in rounds] == [
        "registered", "rewritten", "rewritten"], rounds
    # 一个稿号一份文件一份证明（业主 2026-11-11）⇒ 读数里不再有 `proof_no`。
    assert all("proof_no" not in r for r in rounds), rounds
    # 形态闸只在"登记新命题"那一次跑（改前是 3 次）
    assert len(stub.calls) == 1, stub.calls
    entries = R.entries_on_disk(st.root)
    assert len(entries) == 1, entries
    versions = entries[0]["versions"]
    assert len(versions) == 1, versions
    assert versions[0]["proof_no"] == 0, versions
    # 一份命题只住一份稿（F 自己的稿号那一份；还没有命题号）
    files = sorted(p.name for p in (pathlib.Path(st.root) / "reports").glob("f-proof*.md"))
    mids = {str(r.get("manuscript_id") or "") for r in rounds}
    assert len(mids) == 1 and "" not in mids, rounds
    assert files == [f"f-proof-{next(iter(mids))}.md"], files
    body_now = VS.manuscript_proof_body(
        (pathlib.Path(st.root) / "reports" / files[0]).read_text(
            encoding="utf-8")).strip("\n")
    assert versions[0]["sha256"] == R.proof_sha(body_now), versions
    # F 不再直写 statements（解耦之后那一行由 B 在 V 签之后认领）
    assert len(list(st.rows("statements"))) == 0


def test_a1_negative_control_no_manuscript_reuse_makes_it_red(tmp_path, monkeypatch):
    """A1 反真空：不沿用稿号（每轮向号源要一个新号）⇒ 上面那条红。

    2026-11-10：槽位身份从"计划 + 子目标 + label"换成了 F 自己的稿号 ——
    `register_or_rewrite` 看到同一个 `manuscript_id` 就是同一份稿（改证明），看到新号
    就是新稿（过闸登记）。把"沿用稿号"摘掉（`_resolve_manuscript_id → ""` 让
    `proof_manuscript` 每轮发一个新号）⇒ 3 轮变成 3 次登记、闸 3 次、盘上 3 份稿。
    """
    from agentflow.agent_f import AgentF

    monkeypatch.setattr(AgentF, "_resolve_manuscript_id",
                        lambda self, *, plan, sid, product: "")
    st = _ws(tmp_path)
    _pid, rounds, stub = _production_rounds(st, PROOFS[:3])
    assert len(stub.calls) == 3, (
        "不沿用稿号之后闸仍然只跑一次 ⇒ A1 那条判据证明不了「稿号的沿用」在承重", stub.calls)
    assert [r.get("proof_mode") for r in rounds] == ["registered"] * 3, rounds
    assert len(R.entries_on_disk(st.root)) == 3, R.entries_on_disk(st.root)


def test_a2_changing_the_proposition_in_the_same_window_is_refused(tmp_path):
    """A2：同一槽位（计划 + 子目标）改命题正文 ⇒ 受控拒 `proposition_text_changed`。

    改前：`proposition_text_changed` 只在 `same_slot` 生效，而生产路径上 `same_slot`
    永远是 False ⇒ 改命题正文被当成"新命题"静默登记（盘上 `## 命题` 被换掉）。
    现在：槽位从稿头元信息认出来，改命题正文走受控拒，盘上一个字节都不动。
    """
    st = _ws(tmp_path)
    pid, rounds, stub = _production_rounds(st, PROOFS[:1])
    assert rounds[0].get("proof_mode") == "registered", rounds
    sheet = pathlib.Path(st.root) / (
        f"reports/f-proof-{rounds[0]['manuscript_id']}.md")
    before = R.section_hashes(sheet.read_text(encoding="utf-8"))
    # 同一个子目标换命题正文（同窗口）：只改 plan 台账上的 subgoal.text
    row = dict(st.rows("attack_plans")[0])
    subs = [dict(s) for s in (row.get("subgoals") or [])]
    subs[0]["text"] = OTHER
    row["subgoals"] = subs
    with st.tx("attack_plans", actor="test", note="fixture:a2") as tx:
        tx.upsert("attack_plans", row)
    _pid, second, _stub = _production_rounds(st, [PROOFS[1]])
    out = second[0]
    assert "命题正文与登记条目里那一条不一致" in str(out.get("reason") or ""), out
    after = R.section_hashes(sheet.read_text(encoding="utf-8"))
    assert after == before, "受控拒却动了盘上的稿（命题 / 证明 / 依赖任何一节都不许变）"
    assert len(stub.calls) == 1, "改命题正文不该再跑一次形态闸（它不是重写）"


def test_a3_a_handwritten_labelled_head_is_not_a_registration_entry(tmp_path):
    """A3：手写一份带 `- 标签：` 的头，不许被认成登记条目。

    判据：`- 标签：` 只是作者给的一个粗键；"是不是登记条目"看的是登记元信息
    （正文 sha / 命题指纹 / 版本记录）。改前 `same_slot` 只比 label ⇒ 手写稿被当成
    已登记，于是 `mode=rewritten`、形态闸一次都不跑 —— 一份手写稿就能冒充登记条目。
    """
    st = _ws(tmp_path)
    rel = "reports/f-proof-plan-0000.md"
    path = pathlib.Path(st.root) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "# F 的证明手稿：手写的\n\n"
        "- 命题号：stmt:（还没落号）\n"
        "- 计划：0000 · 子目标：s1\n"
        "- 标签：F 攻坚 0000 子目标 s1\n\n"
        "## 命题\n\n" + TEXT + "\n\n"
        "## 证明\n\n手写的证明正文。\n\n"
        "## 依赖\n\n（这一份证明没有引用任何在册命题 —— 空表就是声明。）\n",
        encoding="utf-8")
    assert R.parse_entry(path.read_text(encoding="utf-8"))["checked"] is False
    gates: list[str] = []

    def _gate(**kw):
        gates.append("called")
        return {"checked": True, "well_formed": True, "submittable": True,
                "problems": [], "refused": "", "reason": "夹具：形态合规"}

    got = R.register_or_rewrite(
        st.root, family="F", label="F 攻坚 0000 子目标 s1", proposition=TEXT,
        proof_text=PROOFS[0], plan_id="0000", sid="s1", gate=_gate)
    assert got.get("mode") == "registered", got
    assert len(gates) == 1, "手写稿被当成登记条目 ⇒ 形态闸一次都没跑"
    entry = R.parse_entry(path.read_text(encoding="utf-8"))
    assert entry["checked"] is True, entry
    assert [v["proof_no"] for v in entry["versions"]] == [0], entry


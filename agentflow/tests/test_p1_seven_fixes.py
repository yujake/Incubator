# -*- coding: utf-8 -*-
"""P1 七件的一致化（业主 2026-11-11 批）：判据 a–g + 反真空。

## 这一份钉什么

| # | 判据 | 钉住的东西 |
|---|---|---|
| a | `capabilities.find_action("B","open_polish_copy")` 不再是 None，`conductor` 的派活口能真调到它 | 冻结后的补救路径可达 |
| b | F 改已签稿 ⇒ `manuscript_frozen` 拒、读数指到 `open_polish_copy` ⇒ B 通过 conductor 真调到它 ⇒ 拿到副本 | 端到端可达（真跑，不只看声明） |
| c | B 的新写路径不再产 `-pN`：两份不同证明 ⇒ 两个不同 B 稿号、名字都不含 `-pN` | 一个稿号 = 一份文件 |
| e | V 的题面没有「第几条证明」；签文件仍无 `proof_no`；认签仍成立 | 签的身份 = 正文 sha + 稿路径 |
| f | F 的题面与手册都有「已拿签的稿不许就地改」，且与 `manuscript_frozen` 拒信同一口径 | 题面与实现同一句话 |
| g | `submission_reading` 被暴露成工具后可读（贴 E 与 B 两条读数） | E/F/B 读得到自己的提交状态 |
| h | 反真空四支：摘动作 ⇒ a 红；写回 `-pN` ⇒ c 红；藏读口 ⇒ g 红（d 那一支在 ⑥ 的判据文件里） | 每条绿都来自它声称的那一步 |

全部 tmp 工作区，不读写 `projects/`（真机工作区只读），不跑全量。
"""
from __future__ import annotations

import json
import pathlib
import re

import pytest

from agentflow import agent_prompts as AP
from agentflow import agent_skills as AS
from agentflow import capabilities as C
from agentflow import manuscriptfreeze as FZ
from agentflow import manuscriptids as MID
from agentflow import proofregistry as PR
from agentflow import verifications as VR
from agentflow import vsigns as VS
from agentflow.agent_b import AgentB
from agentflow.agent_f import AgentF
from agentflow.cancellation import CancelToken
from agentflow.conductor import LocalBackend, NotWiredError
from agentflow.store import Store
from agentflow.tools import build_registry

import _credential_fixture as CF
import conftest

SID = "000005"
BODY_1 = "由定义直接得到：任取 x ∈ X，按定义展开即得。"
BODY_2 = "改用有限覆盖：取一族开覆盖，再用紧性抽出有限子覆盖。"
ACTION = "open_polish_copy"

#: B 的新写路径产出的名字里不许有 `-p<N>` 后缀。
_PN = re.compile(r"-p\d+\.md$")


# ------------------------------------------------------------------ 夹具

def _ws(tmp_path: pathlib.Path, *, seed: bool = True) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    (pathlib.Path(st.root) / "reports").mkdir(parents=True, exist_ok=True)
    if seed:
        conftest.seed_statement_row(st, stmt_id=SID, statement_full="夹具命题。",
                                    kind="conjecture")
    return st


def _b(st: Store) -> AgentB:
    return AgentB(st, extractor=None, extract_text=None)


def _f_manuscript(*, statement_id: str, body: str) -> str:
    """F 的一族规范名正文（稿头一行命题号；签块由调用方决定加不加）。"""
    return (f"# F 的证明手稿：夹具命题\n\n- 命题号：stmt:{statement_id}\n"
            "- 依赖面洗稿：已洗=true；洗的人=secretary:F；补写=无\n"
            f"\n## 命题\n\n夹具命题。\n\n## 证明\n\n{body}\n\n"
            "## 依赖\n\n| 引用（F 的原话） | 命题号（stmt:NNNNNN） | 用在哪一步 | 路径号（第几条证明） |\n"
            "|---|---|---|---|\n（这一份证明没有引用任何在册命题 —— 空表就是声明。）\n")


def _signed_source(st: Store, *, sid: str = SID, body: str = BODY_1) -> str:
    """一份已拿签的 F 稿（签块在稿上、颁发表里也有一份）—— 返回路径。"""
    mid = MID.next_manuscript_id(st.root)
    rel = MID.canonical_rel(mid)
    text = _f_manuscript(statement_id=sid, body=body)
    sha = PR.proof_sha(body)
    block = (f"- V 签：已签=true；判词=成立；连续=3/3；正文sha={sha}；"
             "时间=2026-11-02T10:00:00+08:00；签名者=V；"
             f"台账=verifications/{sid}.jsonl#v-000003；命题号=stmt:{sid}；手稿号={mid}")
    text = text.replace("- 依赖面洗稿：", block + "\n- 依赖面洗稿：", 1)
    (pathlib.Path(st.root) / rel).write_text(text, encoding="utf-8")
    CF.issue_credential(st.root, proof_text=body, statement_id=sid,
                        manuscript=rel, artifact_path=rel)
    return rel


def _no_pn(rels: list[str]) -> bool:
    """c 的判据：这些落点里没有一条带 `-p<N>` 后缀。"""
    return all(_PN.search(str(r)) is None for r in rels)


# ============================================================ a：动作入表 + 可派

def test_a_open_polish_copy_is_declared_and_dispatchable(tmp_path) -> None:
    """a：`find_action` 不再是 None，且 conductor 的派活口能真调到它（不是 NotWiredError）。"""
    spec = C.find_action("B", ACTION)
    assert spec is not None, (
        "B 的动作表里没有 open_polish_copy —— 冻结拒信与 `manuscript_frozen` 的 "
        "next_step 都指着它，而 conductor 会对未声明动作直接 NotWiredError")
    assert str(spec.handler_name) == ACTION, spec
    assert callable(getattr(AgentB, spec.handler_name, None)), (
        "动作声明了，却没有实现方法（声明面与实现面分家）")

    st = _ws(tmp_path)
    backend = LocalBackend({"B": ("object", _b(st))})
    got = backend.call("B", ACTION, {"statement_id": SID}, token=CancelToken())
    assert isinstance(got, dict) and got.get("checked") is True, got
    # 这一条命题没有已签的稿 ⇒ 受控拒「无可优化」（不是 NotWiredError、也不是成功）
    assert got.get("ok") is False and got.get("refused") == "no_signed_manuscript", got


def test_h_removing_the_action_turns_a_red(tmp_path,
                                           monkeypatch: pytest.MonkeyPatch) -> None:
    """h-a 反真空：把动作从能力表里摘掉 ⇒ a 那条判据当场红。"""
    kept = tuple(s for s in C.CAPABILITIES["B"] if s.action != ACTION)
    assert len(kept) == len(C.CAPABILITIES["B"]) - 1
    monkeypatch.setitem(C.CAPABILITIES, "B", kept)
    assert C.find_action("B", ACTION) is None, (
        "摘掉之后 find_action 仍找得到 ⇒ a 的绿不是来自动作表")
    backend = LocalBackend({"B": ("object", _b(_ws(tmp_path)))})
    with pytest.raises(NotWiredError):
        backend.call("B", ACTION, {"statement_id": SID}, token=CancelToken())


def test_a2_the_action_is_exposed_as_own_tool_to_the_b_loop() -> None:
    """a2（工具面形状）：只派活、不点动作时，`own.open_polish_copy` 会被注入 B 的工具面。

    判据读的是同一张表（`capabilities._KNOWN_UNMATCHED_ACTIONS`）—— 它由导入期
    `assert_capabilities()` 第 [7] 条与现算的 `unmapped_actions()` 逐条对过。
    """
    from agentflow.agent_loop import LlmBackend

    loop = object.__new__(LlmBackend)          # 只调那一格纯读方法，不建模型缝
    names = LlmBackend._own_actions_to_expose(loop, "B", action="")
    assert ACTION in names, (
        f"B 的工具面里没有 own.{ACTION}（只派活那一档注入的动作 = {sorted(names)}）")
    assert "ingest_manuscript" in names and "land_manuscript" in names, names


# ============================================================ b：冻结 → 副本 端到端

def _gate_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    """命题形态闸打桩成"判过、合格"（那不是这一份要测的闸）。"""

    def fake_gate(self, *, full, kind, body, label, task_id=""):  # noqa: ANN001, ARG001
        return {"checked": True, "well_formed": True, "submittable": True,
                "conditions": "夹具：设…", "conclusion": "夹具：则…",
                "problems": [], "decision": "夹具：形态合规",
                "refused": "", "reason": "夹具：形态合规"}

    monkeypatch.setattr(AgentF, "_proposition_form_gate", fake_gate)


_STEPS = [
    {"text": "设 (X,d) 为度量空间（本步是前提）", "assumption": True},
    {"text": "取 δ=ε 逐点验证，按定义即得结论", "assumption": True},
    {"text": "凑齐定义的三项，结论成立", "assumption": True},
]
_PROBLEM = "证明：度量空间里紧性蕴含序列紧性。"
_SUBGOAL = "任一序列有收敛子列。"
_TESTABLE = "手稿的 `## 证明` 里逐步给出依据。"


def test_b_frozen_refusal_points_to_the_copy_and_b_gets_one(
        tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """b：F 改已签稿被拒（读数指路）⇒ B 通过 conductor 调到 open_polish_copy ⇒ 拿到副本。"""
    _gate_ok(monkeypatch)
    st = _ws(tmp_path, seed=False)
    f = AgentF(st, config={"workspace_root": str(st.root)})
    made = f.create_plan(_PROBLEM, "pk-p1-b",
                         subgoals=[{"sid": "S1", "text": _SUBGOAL, "owner": "F",
                                    "testable": _TESTABLE}])
    assert made.get("created") is True, made
    plan_id = str(made["plan_id"])
    product = {"kind": "proof", "label": "紧性一段", "steps": list(_STEPS)}

    first = dict(f.tools.call("attack.step", plan_id=plan_id, product=product).data or {})
    assert first.get("action") == "proof", first
    rel = str(first.get("manuscript_path") or "")
    assert rel.startswith("reports/f-proof-"), first
    body = VS.manuscript_proof_body(
        (pathlib.Path(st.root) / rel).read_text(encoding="utf-8")).strip("\n")
    CF.issue_credential(st.root, proof_text=body, statement_id="",
                        manuscript=rel, artifact_path=rel)
    conftest.sign_before_registration(st.root, proof_text=body)

    # D→B 的收录（这一批 ⑥ 之外的那条路）：B 真收进来，行上才记得住「这一条的稿是哪一份」
    b = _b(st)
    ing = b.ingest_manuscript(manuscript=rel, mode="register",
                              cells=("statement_full", "proof_text", "dependencies"))
    assert ing.get("ok") is True, ing
    sid = str((ing.get("register") or {}).get("stmt_id") or "")
    assert sid, ing
    from agentflow import manuscriptfamily as MFAM

    row = next(dict(r) for r in st.rows("statements") if str(r.get("stmt_id")) == sid)
    assert str(row.get("manuscript_id") or "") == str(
        MFAM.classify_manuscript(rel).get("manuscript_id") or ""), row

    # ① F 再改这一份已签的稿 ⇒ 受控拒，读数指到 open_polish_copy
    before = (pathlib.Path(st.root) / rel).read_bytes()
    again = dict(f.tools.call("attack.step", plan_id=plan_id, product=product).data or {})
    assert again.get("action") == "no_change", again
    why = str(again.get("reason") or "")
    assert "已经拿签" in why and ACTION in why, why
    assert (pathlib.Path(st.root) / rel).read_bytes() == before, "被拒的那一笔动了稿"

    # ② B 通过 conductor 的派活口调到它 ⇒ 拿到一份 B 号副本（清签、源稿不动）
    backend = LocalBackend({"B": ("object", b)})
    got = backend.call("B", ACTION, {"statement_id": sid}, token=CancelToken())
    assert got.get("ok") is True, got
    cp = str(got.get("path") or "")
    assert cp == MID.canonical_rel(str(got.get("manuscript_id") or ""), family="b-proof"), got
    assert _no_pn([cp]), cp
    copy_text = (pathlib.Path(st.root) / cp).read_text(encoding="utf-8")
    assert VS.SIGN_MARK not in copy_text, copy_text.split("\n")[:8]
    # 源稿上有没有签块取决于它是怎么签的：颁发表那一份签才是判据；副本必须读成未签。
    assert got.get("cleared") in (0, 1), got
    assert got.get("signed_before") is True and got.get("signed_after") is False, got
    assert (pathlib.Path(st.root) / rel).read_bytes() == before, "开副本动了源稿"


# ============================================================ c：新写路径不再产 -pN

def test_c_two_proofs_get_two_b_numbers_without_pn(tmp_path) -> None:
    """c：两份不同证明 ⇒ 两个不同 B 稿号；两条落点都不含 `-pN`。"""
    st = _ws(tmp_path)
    src1 = _signed_source(st, body=BODY_1)
    src2 = _signed_source(st, body=BODY_2)
    b = _b(st)
    one = b.open_polish_copy(statement_id=SID, source_manuscript=src1)
    two = b.open_polish_copy(statement_id=SID, source_manuscript=src2)
    assert one.get("ok") is True and two.get("ok") is True, (one, two)
    mid1, mid2 = str(one["manuscript_id"]), str(two["manuscript_id"])
    assert mid1 != mid2, (mid1, mid2)
    assert _no_pn([str(one["path"]), str(two["path"])]), (one["path"], two["path"])
    # 实现面同一条纪律：`land_rewrite` 带 `proof_no=2` 也不再拼 `-p2`
    landed = b.land_manuscript(statement_id=SID, proof_text=BODY_1, proof_no=2)
    assert landed.get("ok") is True, landed
    assert _no_pn([str(landed.get("path") or "")]), landed


def test_h_writing_pn_back_turns_c_red(
        tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """h-c 反真空：让写路径真的产出一条 `-pN` ⇒ c 的判据必须红。"""
    st = _ws(tmp_path)
    src = _signed_source(st)
    real = MID.canonical_rel

    def _pn(mid, proof_no=1, *, family=MID.FAMILY_F, legacy=False):
        return real(mid, family=family).replace(".md", "-p2.md")

    monkeypatch.setattr(MID, "canonical_rel", _pn)
    got = _b(st).open_polish_copy(statement_id=SID, source_manuscript=src)
    assert got.get("ok") is True, got
    assert _PN.search(str(got.get("path") or "")) is not None, (
        "写路径被改回 `-pN` 之后 c 的判据仍说「没有」⇒ c 是恒真")


# ============================================================ d：D→B 生产路的路径号

_DEP = "000002"


def _d_path_fixture(tmp_path):
    """一条在册命题 + 一条可引命题 + 两份不同正文的 F 手稿（D 只递指针）。"""
    from agentflow import evidencebits as EB

    st = _ws(tmp_path)
    conftest.seed_statement_row(st, stmt_id=SID, statement_full="夹具命题。",
                                kind="theorem")
    conftest.seed_statement_row(st, stmt_id=_DEP, statement_full="引理：夹具。",
                                kind="lemma", proof_text="引理：夹具。")
    conftest.sign_for_the_gate(st.root, statement_id=_DEP, proof_text="引理：夹具。",
                               store=st)
    row = next(dict(r) for r in st.rows("statements")
               if str(r.get("stmt_id")) == _DEP)
    bits = dict(row.get("bits") or {})
    bits["proof"] = True
    ev = dict(bits.get("evidence") or {})
    ev.setdefault("proof_process", str(row.get("proof_text") or "（夹具）"))
    bits["evidence"] = ev
    bits["grade"] = EB.derive_grade(bits, kind="lemma")
    with st.tx("statements", actor="夹具") as tx:
        tx.upsert("statements", dict(row, bits=bits))

    def _ms(body: str, mid: str) -> str:
        rel = f"reports/f-proof-{mid}.md"
        sha = PR.proof_sha(body)
        block = (f"- V 签：已签=true；判词=成立；连续=3/3；正文sha={sha}；"
                 "时间=2026-11-02T10:00:00+08:00；签名者=V；"
                 f"台账=verifications/{SID}.jsonl#v-000003；命题号=stmt:{SID}；手稿号={mid}")
        deps = ("| 引用（F 的原话） | 命题号（stmt:NNNNNN） | 用在哪一步 | 路径号（第几条证明） |\n"
                "|---|---|---|---|\n"
                f"| 由引理，得所需 | stmt:{_DEP} | 1 | 1 |\n")
        text = (f"# F 的证明手稿：夹具命题\n\n- 命题号：stmt:{SID}\n{block}\n"
                "- 依赖面洗稿：已洗=true；洗的人=secretary:F；补写=无\n"
                f"\n## 命题\n\n夹具命题。\n\n## 证明\n\n{body}\n\n## 依赖\n\n{deps}")
        (pathlib.Path(st.root) / rel).write_text(text, encoding="utf-8")
        conftest.sign_for_the_gate(st.root, statement_id=SID, proof_text=body,
                                   store=st, manuscript=rel)
        return rel

    return st, _b(st), _ms(BODY_1, "000010"), _ms(BODY_2, "000011")


def _dep_rows(st: Store) -> list[dict]:
    return [dict(r) for r in st.rows("dependencies")
            if str(r.get("used_by") or "").split("#", 1)[0] == f"stmt:{SID}"]


def test_d_second_proof_gets_path_two_not_a_rewrite(tmp_path) -> None:
    """d：同一命题第二份证明 ⇒ `path_group=2`（不是把 #1 改写）。"""
    st, b, rel1, rel2 = _d_path_fixture(tmp_path)
    first = b.register_statement(proof_manuscript=rel1)
    assert first.get("ok") is True, first
    second = b.register_statement(proof_manuscript=rel2)
    assert second.get("ok") is True, second
    assert int((second.get("path_group") or {}).get("path_group") or 0) == 2, second

    rows = _dep_rows(st)
    groups = sorted(int(r.get("path_group") or 1) for r in rows)
    assert groups == [1, 2], rows
    used = sorted(str(r.get("used_by") or "") for r in rows)
    assert used == [f"stmt:{SID}", f"stmt:{SID}#p2"] or used == [
        f"stmt:{SID}#p1", f"stmt:{SID}#p2"], used
    # 路径数两处同号：dependencies 与 verifications
    from agentflow import manuscriptpaths as MP

    reading = MP.path_reading(st, st.root, statement_id=SID)
    assert reading.get("checked") is True and int(reading.get("count") or 0) == 2, reading
    vgroups = sorted(int(p.get("path_group") or 0) for p in (reading.get("paths") or []))
    assert vgroups == [1, 2], reading
    # 第 2 份没有把 #1 的正文改写掉（canonical 仍是第一份）
    row = next(dict(r) for r in st.rows("statements") if str(r.get("stmt_id")) == SID)
    assert str(row.get("proof_text") or "") == BODY_1, row.get("proof_text")
    proofs = [dict(x) for x in (row.get("proofs") or [])]
    assert [int(p.get("proof_no") or 0) for p in proofs] == [2], proofs


def test_h_not_assigning_a_path_turns_d_red(
        tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """h-d 反真空：把「分配新路径」改成「永远第 1 条」⇒ d 必须红。"""
    from agentflow import manuscriptsubmission as MS

    st, b, rel1, rel2 = _d_path_fixture(tmp_path)
    assert b.register_statement(proof_manuscript=rel1).get("ok") is True
    monkeypatch.setattr(
        MS, "assign_path_group",
        lambda **kw: {"checked": True, "path_group": 1, "existing": False,
                      "count": 1, "why": "打桩：永远第 1 条"})
    second = b.register_statement(proof_manuscript=rel2)
    assert second.get("ok") is True, second
    reading = __import__("agentflow.manuscriptpaths", fromlist=["x"]).path_reading(
        st, st.root, statement_id=SID)
    assert int(reading.get("count") or 0) != 2, (
        "把分配改成永远 1 之后 d 仍读出两条路径 ⇒ d 的绿不是来自分配那一步", reading)


# ============================================================ e：V 题面 / 签 / 认签

def _prompt(role: str, registry) -> str:
    return AP.system_prompt(role, registry=registry, task="把这条链路走一遍",
                            workspace_root="D:/x")


def test_e_v_prompt_has_no_proof_index_and_sign_still_has_no_proof_no(tmp_path) -> None:
    """e：V 题面不再有「第几条证明」；签文件仍无 `proof_no`；认签仍成立。"""
    registry = build_registry().registry
    for text in (_prompt("V", registry),
                 VR.cold_start_prompt("夹具命题。", BODY_1, readonly_facts="- 手稿：夹具")):
        for stale in ("第几条证明", "第几份证明"):
            assert stale not in text, f"V 的题面仍写着 {stale!r}"
        assert "正文 sha + 稿路径" in text, "V 的题面没有说清签的身份"

    st = _ws(tmp_path)
    rel = _signed_source(st, body=BODY_1)
    sign_files = sorted((pathlib.Path(st.root) / "out" / "vsigns").glob("*.json"))
    assert sign_files, "颁发表里一份签都没有 ⇒ 这一条没查成"
    for path in sign_files:
        doc = json.loads(path.read_text(encoding="utf-8"))
        if path.name == "issued.json":
            for entry in (doc.get("entries") or doc.get("issued") or []):
                assert "proof_no" not in dict(entry or {}), (path.name, entry)
            continue
        assert "proof_no" not in doc, (path.name, doc)
    reading = VS.sign_reading(st.root, statement_id=SID, proof_text=BODY_1)
    assert reading.get("state") == "signed", reading
    signed_docs = []
    for path in sign_files:
        doc = json.loads(path.read_text(encoding="utf-8"))
        if path.name != "issued.json":
            signed_docs.append(doc)
    assert any(str(d.get("artifact_path") or "") == rel for d in signed_docs), (
        "签文件里没有一份记着它盖在哪份稿上 ⇒ 认签的载体不见了", [d.get("artifact_path") for d in signed_docs])


# ============================================================ f：题面与拒信同一口径

def test_f_the_frozen_sentence_is_in_the_prompt_and_matches_the_refusal() -> None:
    """f：F 的题面与手册都有「已拿签的稿不许就地改」，与 `manuscript_frozen` 拒信同一口径。"""
    registry = build_registry().registry
    text = _prompt("F", registry)
    assert "已拿签的稿不许就地改" in text, "F 的题面没有那句禁令"
    assert "manuscript_frozen" in text, "F 的题面没有点名受控码"
    assert "B.open_polish_copy" in text, "F 的题面没有指到唯一正路（开副本）"
    # 同一口径：拒信也说「只读 / 开 B 的优化副本（B.open_polish_copy）」。
    assert "只读" in FZ.FREEZE_MESSAGE and "B.open_polish_copy" in FZ.FREEZE_MESSAGE, (
        FZ.FREEZE_MESSAGE)
    assert "只读" in text, "题面没有说清「已签 = 只读」"
    # 手册（按需读的那一份）同口径
    bodies = "\n".join(str(s.body) for s in AS.skills_for("F"))
    assert "已拿签的稿不许就地改" in bodies, "F 的手册里没有那条禁令"
    assert "B.open_polish_copy" in bodies, "F 的手册没有指到开副本那条路"
    # 「就地重写」只属于未签那一档：F 的题面必须带这个限定
    assert "未签时" in text, "「就地重写」那一句没有限定成未签时"


# ============================================================ g：提交状态读口

def _submitted_reading(reg, **params):
    got = reg.call("manuscripts.submission_reading", params, role="E")
    return got


def test_g_the_reading_is_exposed_and_reads_e_and_b(tmp_path) -> None:
    """g：工具暴露之后，E 与 B 各读到自己的提交状态（两条读数都贴在这里）。"""
    import test_b_ingest_marks_submitted as TB
    import test_e_auto_submits_signed_manuscripts as TE
    from agentflow import manuscriptsubmission as MS

    # ---- E：收工自动提交 ⇒ via=closing_auto_submit
    st_e = TE._ws(tmp_path / "e")
    TE._task(st_e)
    e_mid = "000000"
    TE._signed(st_e, e_mid)
    from agentflow import schema as S

    closed = TE.EAS.auto_submit_at_close(store=st_e, root=st_e.root,
                                         task_id="t-000001", stamp=S.now_iso())
    assert int(closed.get("auto_submitted_count") or 0) >= 1, closed

    reg_e = build_registry(store=st_e).registry
    got_e = _submitted_reading(reg_e, manuscript_id=e_mid)
    assert got_e.ok is True, (got_e.error, got_e.meta)
    read_e = dict(got_e.data or {})
    assert read_e.get("state") == "submitted", read_e
    assert read_e.get("via") == MS.VIA_CLOSING, read_e
    assert read_e.get("producer_role") == "E", read_e
    assert read_e.get("signed") is True, read_e
    assert read_e.get("submitted_at"), read_e

    # ---- B：收录即提交 ⇒ via=ingested_to_ledger
    st_b, b = TB._ws(tmp_path / "b")
    TB._task(st_b)
    conftest.seed_statement_row(st_b, stmt_id=TB.SID,
                                statement_full=TB.PROPOSITION, kind="theorem")
    rel = "reports/b-proof-000001.md"
    TB._write(st_b, rel, TB._manuscript())
    TB._signed_proof(st_b, rel, TB.PROOF1)
    ing = TB._ingest(b, rel, cells=["proof_text"])
    assert ing.get("b_submission", {}).get("written") is True, ing
    reg_b = build_registry(store=st_b).registry
    got_b = reg_b.call("manuscripts.submission_reading", {"manuscript": rel}, role="B")
    assert got_b.ok is True, (got_b.error, got_b.meta)
    read_b = dict(got_b.data or {})
    assert read_b.get("state") == "submitted", read_b
    assert read_b.get("via") == MS.VIA_INGEST, read_b
    assert read_b.get("producer_role") == "B", read_b
    assert read_b.get("signed") is True, read_b
    # 两条读数的形状一致（同一个读口，不是两套）
    assert set(read_e) == set(read_b), (sorted(read_e), sorted(read_b))
    # 「没查成」与「未提交」分得开：不给稿号/路径 ⇒ checked=False（不是 unsubmitted）
    empty = reg_e.call("manuscripts.submission_reading", {}, role="E").data or {}
    assert empty.get("checked") is False and empty.get("state") == "unsubmitted", empty


def test_h_hiding_the_reading_turns_g_red(
        tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """h-g 反真空：把读口从工具面藏回去 ⇒ g 那条判据当场红。"""
    from agentflow.tools import manuscript_tools as MT

    kept = tuple(x for x in MT._TOOL_FUNCTIONS
                 if x[0] is not MT.manuscripts_submission_reading)
    assert len(kept) == len(MT._TOOL_FUNCTIONS) - 1
    monkeypatch.setattr(MT, "_TOOL_FUNCTIONS", kept)
    st = _ws(tmp_path)
    reg = build_registry(store=st).registry
    assert "manuscripts.submission_reading" not in reg.names(), (
        "读口被藏回去之后仍然在名册里 ⇒ g 的绿不是来自暴露面")
    hidden = reg.call("manuscripts.submission_reading", {}, role="E")
    assert hidden.ok is False, ("藏回去的工具仍能调到 ⇒ g 的绿不是来自暴露面", hidden.data)

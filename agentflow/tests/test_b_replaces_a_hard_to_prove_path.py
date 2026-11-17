# -*- coding: utf-8 -*-
"""GB-B 路：路径 1 是「难以自证」时，一份带真 V 签的正式稿整条替换它。

## 业主口径（逐字，2026-11-13）

> 「极有可能后续正式 V 签稿被 B 秘书侧以已有证明拒，我们需保证这种异常情况允许替换，
>   且 B 秘书应该认为难以自证状态的证明路径号是空号，即如果路径 1 是难以自证状态，
>   后续提交 V 签稿时应替换该路径的证明稿、依赖面、V 签、引文状态等等，且将优化栏更新
>   为新稿提交一致的未优化。」

## 改前的机制（为什么会被「以已有证明拒」）

`ingest_manuscript(mode="apply")` 的依赖那一格 → `Secretary.record_manuscript_dependency_face`
→ `_manuscript_dependency_refusal` → `_same_kind_hits`：它拿在册全部证明正文（含引文
占位那一份）去问秘书"这一份与它们是不是同种"。引文占位与形式证明讲的是同一条定理、
语义判定很容易给 `same` ⇒ 整份正式稿被 `proof_same_kind` 拒（探针实测，见下）。即使
侥幸收下（走 `register_statement` 的升档支），优化栏也会被打成 `optimized=true`、
`hard_to_prove_by_proof[1]` 留着，读侧 `optimized_state` 仍是第四档 `hard_to_prove`。

## 判据

| # | 造什么 | 期望 |
|---|---|---|
| a | 路径 1 = 难以自证（引文占位），交一份真 V 签的形式稿（`mode=apply`） | 不被 `proof_same_kind` 拒；`path_group=1`；四样全换（证明稿 / 依赖面 / V 签 / 引文状态）；优化栏 `optimized_state=1` 读成 `"false"`（未优化） |
| a2 | 同一件事走逐份登记（`register_statement`，inline 那一条入口） | 同 a：同一个号、同样四样换、同样未优化（两条入口一个口径） |
| b | 正控：同一条「难以自证」的命题仍可被放弃 | `amend_statement_meta(status="abandoned")` 走既有 counterexample 档 ⇒ `checked/amended`，`status=abandoned` |
| c | 反真空①：把"空号读法"打桩成"没有空号" | a 必须红 —— 正式稿被 `proof_same_kind` 拒，盘上一个字节没动（证明这条读法承重） |
| d | 反真空②：替换只做一半（只换稿不换签） | a 的判据必须红（V 签 / 引文状态那一条）—— 原子性 |
| e | 三态：「难以自证」那一格读不出来 | 不许当空号：按普通「已有证明」处置 ⇒ `proof_same_kind` 拒，且拒信带读数 |

探针（temp/，不入库）实测改前读数：a 在改前是 `refused="proof_same_kind"`（apply 路）；
a2 在改前 `ok=true` 而 `optimized_state(1)=="hard_to_prove"`、`hard_to_prove_by_proof` 还在。
"""
from __future__ import annotations

import json
import pathlib
import sys

import pytest

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
_TESTS = pathlib.Path(__file__).resolve().parent
for _path in (_SRC, _TESTS):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import conftest  # noqa: E402

from agentflow import evidencebits as EB  # noqa: E402
from agentflow import manuscriptpaths as MP  # noqa: E402
from agentflow import schema as S  # noqa: E402
from agentflow import verifications as VR  # noqa: E402
from agentflow import vsigns as VS  # noqa: E402
from agentflow.agent_b import AgentB  # noqa: E402
from agentflow.secretary import Secretary  # noqa: E402
from agentflow.store import Store  # noqa: E402

#: 被引的那条在册命题（手稿依赖段的引用门槛：`pre_theorem` 及以上）。
DEP_SID = "000000"
PROP = "对任意有限群 G，若 p 整除 |G|，则 G 有 p 阶元。"
#: 路径 1：引文侧录入的占位证明（引文只给了结论 ⇒ 优化栏记「难以自证」）。
P_CITE = "由文献 [12] 的定理 3.2 直接得到。"
#: 新稿：真 V 签的形式证明（与占位那一份"同一路"—— 语义判定会判 same）。
P_FORMAL = ("取 G 在自身上的共轭作用，用轨道-稳定化子计数。\n\n"
            "〔证法编号：A1〕\n引 stmt:000000。")
REL_NEW = "reports/f-proof-000201.md"
#: 新稿的稿号（`_VS.manuscript_id_of(REL_NEW)`；逐路径记录与 `manuscript_id` 都读它）。
MID_NEW = "000201"

OWN = {"statement_full": PROP, "statement_text": "p 阶元",
# 2026-11-17（语义纠正）：`derived_from` / `source_lit_id` 是可选信息（`origin` 只是状态：自产/引用）；这一份夹具不测来路。
       "origin": "own_result", "derived_from": ["999999"], "kind": "conjecture",
       "doc_id": S.format_id(0),
       "quote_reason": "我方自产命题，没有外部引文要比对"}


# ============================================================ 假缝（只答三问）
class _Seam:
    """秘书判定面的替身：命题同一性回 same、同种证明按 `kind` 回（缺省 same）。"""

    class _Call:
        ok = True
        problem = ""
        detail = ""
        text = ""
        model = "fake"
        prompt_version = "t"
        prompt_sha256 = "0" * 64

    def __init__(self, *, kind: str = "same") -> None:
        self.kind = str(kind)
        self.notes: list[str] = []

    def ask_json(self, prompt, **kw):
        note = str(kw.get("note") or "")
        self.notes.append(note)
        data: dict = {}
        start, end = str(prompt).find("{"), str(prompt).rfind("}")
        if 0 <= start < end:
            try:
                data = json.loads(str(prompt)[start:end + 1])
            except json.JSONDecodeError:
                data = {}
        if note.endswith("statement_keywords"):
            return {"keywords": ["子群", "p 阶元"], "why": "打桩：两个数学词"}, self._Call()
        if note.endswith("proof_kind"):
            return ({"decision": self.kind,
                     "same_path": 1 if self.kind == "same" else 0,
                     "reason": f"打桩：恒判 {self.kind}"}, self._Call())
        full = str(data.get("statement_full") or "")
        cands = [c for c in (data.get("candidates") or []) if isinstance(c, dict)]
        hit = next((c for c in cands
                    if str(c.get("statement_full") or "") == full), None)
        if hit is None:
            return ({"decision": "different", "canonical_name": "p 阶元", "same_as": "",
                     "route": "", "reason": "打桩：没有逐字同一条", "basis": ["打桩"]},
                    self._Call())
        return ({"decision": "same", "same_as": str(hit.get("stmt_id") or ""),
                 "canonical_name": "p 阶元", "route": "",
                 "reason": "打桩：逐字同一条", "basis": ["打桩"]}, self._Call())


# ============================================================ 工作区
def _ws(base: pathlib.Path, name: str = "ws") -> tuple[Store, AgentB]:
    st = Store(base / name)
    st.init()
    sec = Secretary("B", root=st.root, store=st, seam=_Seam(), enable_model=True)
    return st, conftest.b_form_gate_ok(
        AgentB(st, extractor=None, extract_text=None, config={}, secretary=sec))


def _citable(st: Store) -> None:
    conftest.seed_statement_row(st, stmt_id=DEP_SID, statement_full="引理：p 阶元",
                                kind="lemma", proof_text="引理：p 阶元")
    conftest.sign_for_the_gate(st.root, statement_id=DEP_SID,
                               proof_text="引理：p 阶元", store=st)
    row = next(dict(r) for r in st.rows("statements")
               if str(r.get("stmt_id")) == DEP_SID)
    bits = dict(row.get("bits") or {})
    bits["proof"] = True
    ev = dict(bits.get("evidence") or {})
    ev.setdefault("proof_process", str(row.get("proof_text") or ""))
    bits["evidence"] = ev
    bits["grade"] = EB.derive_grade(bits, kind="lemma")
    with st.tx("statements", actor="夹具") as tx:
        tx.upsert("statements", dict(row, bits=bits))


def _cite_row(st: Store, *, hard: object | None = None) -> str:
    """铺一条「路径 1 = 引文占位、优化栏记难以自证」的命题行。

    `hard` 是 `bits.evidence.hard_to_prove_by_proof` 那一格的形状（判据 e 用它造
    "读不出来"）；缺省是合法的一条（第 1 条路径）。
    """
    pocket = ({"1": {"basis": "引文只给了结论，没给可复算的完整严密证明",
                     "at": "2026-11-13T10:00:00+08:00"}}
              if hard is None else hard)
    bits = {
        "proof": True, "reviewed": False, "grade": "conjecture",
        "origin": "own_result",
        "evidence": {"proof_process": P_CITE,
                     "reviewed_source": EB.REVIEWED_SOURCE_CITATION,
                     "reviewed_by": {"verifier": "citation", "verification_id": "",
                                     "round": None, "verdict": "占位",
                                     "evidence": "lit:000012", "findings": [],
                                     "proof_no": 1, "proof_sha256": ""},
                     EB.HARD_TO_PROVE_KEY: pocket,
                     EB.OPTIMIZED_BY_PROOF_KEY: {"1": False}},
    }
    row = conftest.seed_statement_row(st, proof_text=P_CITE, statement_full=PROP,
                                      statement_text="p 阶元", kind="conjecture",
                                      label="p 阶元", origin="own_result", bits=bits)
    sid = str(row["stmt_id"])
    rel = f"reports/f-proof-{sid}.md"
    path = pathlib.Path(st.root) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"# 引文侧的稿\n\n## 命题\n\n{PROP}\n\n## 证明\n\n{P_CITE}\n",
                    encoding="utf-8")
    with st.tx("statements", "dependencies", actor="夹具") as tx:
        tx.upsert("statements", dict(row, manuscripts={"1": rel}))
        #: 路径 1 的旧依赖面（引文那一份的边）。替换之后这一行必须消失。
        tx.upsert("dependencies", S.Dependency(
            dep_id=tx.alloc_id(S.TABLES["dependencies"]["id_kind"]),
            used_by=f"stmt:{sid}", kind="theorem", label="文献 12 定理 3.2",
            source_lit_id=None, source_experiment_id=None,
            source_stmt_id=DEP_SID, source_doc_id=None, quote="文献 12",
            status="closed", status_reason="", page_range=S.PageRange(),
            path_group=1, created_at=S.now_iso(), created_by="夹具").to_dict())
    return sid


def _manuscript(proof: str) -> str:
    deps = ("| 引用 | 命题号 | 步 |\n|---|---|---|\n"
            f"| 引理：p 阶元 | stmt:{DEP_SID} | 1 |\n")
    return ("# 形式证明稿\n\n## 命题\n\n" + PROP + "\n\n## 证明\n\n" + proof
            + "\n\n## 依赖\n\n" + deps)


def _write(st: Store, rel: str, text: str) -> None:
    path = pathlib.Path(st.root) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _signed_manuscript(st: Store, sid: str) -> str:
    """写一份新稿并用真写口签住它（签文件 / 台账票数都是真的）。"""
    _write(st, REL_NEW, _manuscript(P_FORMAL))
    conftest.sign_for_the_gate(st.root, statement_id=sid, proof_text=P_FORMAL,
                               store=st, manuscript=REL_NEW)
    return REL_NEW


# ============================================================ 读数
def _row(st: Store, sid: str) -> dict:
    return next(dict(r) for r in st.rows("statements")
                if str(r.get("stmt_id")) == sid)


def _deps(st: Store, sid: str) -> list[dict]:
    return [dict(r) for r in st.rows("dependencies")
            if str(r.get("used_by") or "").split("#", 1)[0] == f"stmt:{sid}"]


def _verification_groups(st: Store, sid: str, text: str) -> list[int]:
    rows, bad = VR.list_verifications(st.root, statement_id=sid, limit=None)
    assert bad == [], bad
    sha = VR.text_sha(text)
    return [int(r.get("path_group") or 0) for r in rows
            if str(r.get("proof_sha256") or "") == sha]


def _fill_problems(st: Store, sid: str, got: dict) -> list[str]:
    """判据 a 的本体：五件事（四样替换 + 优化栏复位）逐条读，缺一条都不算。"""
    problems: list[str] = []
    if got.get("ok") is not True:
        return [f"正式稿没被收下：ok={got.get('ok')!r} refused={got.get('refused')!r} "
                f"{str(got.get('reason') or '')[:160]}"]
    row = _row(st, sid)
    # ① 路径号：空号被填上（不是新开一条）。
    if MP.path_reading(st, st.root, statement_id=sid).get("count") != 1:
        problems.append(f"路径数不是 1：{MP.path_reading(st, st.root, statement_id=sid)}")
    # ② 证明稿：正文 + 逐路径记录 + 稿号。
    if str(row.get("proof_text") or "").strip() != P_FORMAL.strip():
        problems.append(f"`proof_text` 还是旧的：{str(row.get('proof_text') or '')[:60]!r}")
    per = dict(row.get("manuscripts") or {})
    if str(per.get("1") or "") != REL_NEW:
        problems.append(f"`manuscripts['1']` 没有换成新稿：{per!r}")
    if str(row.get("manuscript_id") or "") != MID_NEW:
        problems.append(f"`manuscript_id` 没有换成新稿号：{row.get('manuscript_id')!r}")
    history = [dict(h) for h in (row.get("proof_history") or [])
               if isinstance(h, dict)]
    if not any(str(h.get("text") or "").startswith("由文献 [12]")
               for h in history):
        problems.append(f"旧的引文占位正文没有进 `proof_history`：{history!r}")
    # ③ 依赖面：这一条路径的旧行必须换掉（同一路径号上只该剩新稿的边）。
    deps = [d for d in _deps(st, sid) if int(d.get("path_group") or 1) == 1]
    if not deps:
        problems.append("第 1 条路径的依赖面空了（新稿的边没落）")
    old = [d for d in deps if str(d.get("label") or "") == "文献 12 定理 3.2"]
    if old:
        problems.append(f"第 1 条路径的旧依赖行还在：{old!r}")
    if not any(str(d.get("source_stmt_id") or "") == DEP_SID for d in deps):
        problems.append(f"新稿的依赖边没落：{[d.get('source_stmt_id') for d in deps]!r}")
    # ④ V 签：新正文的签行带第 1 号，且签是真的。
    if not _verification_groups(st, sid, P_FORMAL):
        problems.append("`verifications` 里没有覆盖新正文的行")
    elif any(g != 1 for g in _verification_groups(st, sid, P_FORMAL)):
        problems.append(f"覆盖新正文的签行路径号不是 1："
                        f"{_verification_groups(st, sid, P_FORMAL)!r}")
    if str(VS.sign_reading(st.root, statement_id=sid, proof_text=P_FORMAL,
                           proof_no=1).get("state") or "") != "signed":
        problems.append("新正文的签不是真签（`sign_reading` 不是 signed）")
    # ⑤ 引文状态：占位签 ⇒ 真签。
    bits = dict(row.get("bits") or {})
    ev = dict(bits.get("evidence") or {})
    if bool(bits.get("reviewed")) is not True:
        problems.append(f"`bits.reviewed` 仍是假：{bits.get('reviewed')!r}")
    if str(ev.get("reviewed_source") or "") != EB.REVIEWED_SOURCE_V:
        problems.append(f"`reviewed_source` 不是真签：{ev.get('reviewed_source')!r}")
    # ⑥ 优化栏复位：新稿 = 未优化，旧的难以自证不许留。
    if EB.hard_to_prove_by_proof(row):
        problems.append(f"旧的「难以自证」记录还在：{EB.hard_to_prove_by_proof(row)!r}")
    if EB.optimized_by_proof(row).get(1) is not False:
        problems.append(f"`optimized_by_proof[1]` 不是 false："
                        f"{EB.optimized_by_proof(row)!r}")
    state = EB.optimized_state(row, 1)
    if state != "false":
        problems.append(f"优化栏读数是 {state!r}（应是未优化 \"false\"）")
    return problems


def _apply(st: Store, b: AgentB, sid: str) -> dict:
    return b.ingest_manuscript(manuscript=REL_NEW, target_stmt_id=sid,
                               cells=["proof_text", "dependencies"], mode="apply")


def _fixture(base: pathlib.Path, name: str = "ws",
             *, hard: object | None = None) -> tuple[Store, AgentB, str]:
    st, b = _ws(base, name)
    _citable(st)
    return st, b, _cite_row(st, hard=hard)


# ============================================================ a：整条替换
def test_a_a_signed_manuscript_replaces_the_hard_to_prove_path(tmp_path):
    st, b, sid = _fixture(tmp_path)
    _signed_manuscript(st, sid)
    got = _apply(st, b, sid)
    problems = _fill_problems(st, sid, got)
    assert problems == [], problems
    # 回执里的号也必须是 1（落点与盘面同号，不靠读盘猜）。
    assert int((got.get("path_group") or {}).get("path_group") or 0) == 1, got
    assert str(got.get("refused") or "") == "", got


# ============================================================ a2：另一条入口同口径
def test_a2_inline_registration_fills_the_same_vacant_path(tmp_path):
    st, b, sid = _fixture(tmp_path, "inline")
    _signed_manuscript(st, sid)
    got = b.register_statement(**OWN, proof_text=P_FORMAL, proof_manuscript=REL_NEW)
    problems = _fill_problems(st, sid, got)
    assert problems == [], problems


# ============================================================ b：正控（仍可放弃）
def _put_refuting_experiment(st: Store, eid: str = "000001") -> None:
    """一行"真的证否了它"的实验（既有放弃档 `counterexample` 的证据）。"""
    row = {
        "experiment_id": eid, "claim": PROP, "claim_key": "p 阶元",
        "method": "numeric", "evidence_kind": "cross_check", "result": "refutes",
        "negation_kind": "disproved",
        "counterexample": {"kind": "counterexample", "n": 7,
                           "value": "G=S_3、p=3 时没有 3 阶元"},
        "code_path": "code/probe.py", "code_hash": "0" * 16,
        "observations": {}, "certificate": None, "search_bound": {},
        "exit_code": 0, "runtime_sec": 0.1,
        "created_at": S.now_iso(), "created_by": "夹具",
    }
    S.Experiment(**{k: v for k, v in row.items()
                    if k in S.Experiment.__dataclass_fields__}).validate()
    with st.tx("experiments", actor="夹具") as tx:
        tx.upsert("experiments", row)


def test_b_a_hard_to_prove_statement_can_still_be_abandoned(tmp_path):
    st, _b, sid = _fixture(tmp_path)
    _put_refuting_experiment(st)
    got = Secretary("B", root=st.root, store=st).amend_statement_meta(
        sid, {"status": "abandoned", "abandon_kind": "counterexample",
              "abandon_basis": "S_3 这一组参数让结论为假（不存在 3 阶元）",
              "experiment_id": "000001"}, role="B")
    assert got.get("checked") is True and got.get("amended") is True, got
    assert str(_row(st, sid).get("status") or "") == "abandoned", _row(st, sid)


# ============================================================ c：反真空①
def test_c_reading_the_vacant_path_as_occupied_turns_a_red(tmp_path, monkeypatch):
    """把「空号」读法打桩成"没有空号" ⇒ a 必须被 `proof_same_kind` 拒。

    这条钉的是"承重"：a 之所以绿，是因为空号那条路径不进同种证明的比较；
    读法一旦退化成"它也是已有证明"，正式的 V 签稿就会被"已有证明"挡在门外 ——
    正是业主裁定的那个异常场景。
    """
    # 正控：不打桩 ⇒ a 全绿（否则下面测的是桩本身）。
    st_ok, b_ok, sid_ok = _fixture(tmp_path, "control")
    _signed_manuscript(st_ok, sid_ok)
    assert _fill_problems(st_ok, sid_ok, _apply(st_ok, b_ok, sid_ok)) == []

    real = MP.vacant_path_reading

    def _no_vacancy(row):
        return {"checked": True, "groups": [], "entries": {},
                "why": "打桩：这一行没有空号（全按普通已有证明处置）"}

    monkeypatch.setattr(MP, "vacant_path_reading", _no_vacancy)
    st, b, sid = _fixture(tmp_path, "stubbed")
    _signed_manuscript(st, sid)
    before = _row(st, sid)
    got = _apply(st, b, sid)
    assert got.get("ok") is False, got
    assert str(got.get("refused") or "") == "proof_same_kind", got
    after = _row(st, sid)
    assert str(after.get("proof_text") or "") == str(before.get("proof_text") or ""), (
        "被拒之后正文不许动")
    assert EB.hard_to_prove_by_proof(after), "被拒之后「难以自证」记录不许动"
    monkeypatch.setattr(MP, "vacant_path_reading", real)


# ============================================================ d：反真空②（原子性）
def test_d_replacing_only_the_manuscript_without_the_sign_turns_a_red(
        tmp_path, monkeypatch):
    """替换只做一半（只换稿、不换签）⇒ a 的判据必须红。

    打桩点取"认签"的唯一口（`vsigns.bits_after_sign`）：它自称成功、却一个位都不写 ——
    这正是"稿换了、V 签 / 引文状态还是占位"的那半笔。判据 a 必须能把它读出来。
    """
    real = VS.bits_after_sign

    def _half_signed(bits, **kw):
        return dict(bits or {}), {"checked": True, "applied": True,
                                  "state": "signed", "why": "打桩：只换稿不换签"}

    monkeypatch.setattr(VS, "bits_after_sign", _half_signed)
    st, b, sid = _fixture(tmp_path, "half")
    _signed_manuscript(st, sid)
    got = _apply(st, b, sid)
    problems = _fill_problems(st, sid, got)
    assert problems, ("替换只做了一半（只换稿不换签）而判据 a 仍然全绿 ⇒ "
                      "这一组判据判不出半笔")
    assert any(("reviewed" in p) or ("签" in p) for p in problems), problems
    monkeypatch.setattr(VS, "bits_after_sign", real)


# ============================================================ e：三态（fail-closed）
@pytest.mark.parametrize("bad", [
    "读不出来的形状（不是映射）",
    {"1": {"at": "2026-11-13T10:00:00+08:00"}},           # 有条目、没有理由
    {"一号": {"basis": "路径号读不出"}},                    # 键不是路径号
])
def test_e_unreadable_hard_to_prove_is_not_a_vacant_number(tmp_path, bad):
    """「难以自证」那一格读不出来 ⇒ 不许当空号：按普通「已有证明」处置（拒）并给读数。"""
    st, b, sid = _fixture(tmp_path, "bad", hard=bad)
    _signed_manuscript(st, sid)
    got = _apply(st, b, sid)
    assert got.get("ok") is False, (
        f"「难以自证」那一格读不出来（{bad!r}）却照收了 ⇒ 三态被折平了：{got}")
    assert str(got.get("refused") or "") == "proof_same_kind", got
    why = str(got.get("reason") or "")
    assert "读不出来" in why, f"拒信没有带读数（那一格读不出来）：{why[:200]!r}"
    # 盘面：一个字节没动（正文仍是引文占位、空号读数还是那条坏记录）。
    row = _row(st, sid)
    assert str(row.get("proof_text") or "") == P_CITE, row.get("proof_text")
    assert MP.vacant_path_reading(row).get("checked") is False, (
        MP.vacant_path_reading(row))

# -*- coding: utf-8 -*-
"""判据：签名这件事在读数上永远不许说谎（多证明签名链审计"最危险的一批"）。

## 这一份在治什么

`%TEMP%\\audit_ms\\` 那批探针量出的五种"签名说谎"形态，每一条都能让一次
没有落地的签名以 `signed_bit3=True` 出现在返回值里，而盘上没有凭据：

| 条 | 形态（改前读数） | 修完之后要读到什么 |
|---|---|---|
| ① 撤回 | 存量 `proof_review` 行的 canonical 未签，V 签 `#p2` ⇒ 写入期闸拒收、撤回抹掉台账那一行，而返回仍 `checked=True verdict='成立' signed_bit3=True`、台账 0 字节、R10=0 | 要么真的签住（台账有行、`#p2` 位翻、R10=1），要么 `checked=False` 并说明；不许返回说 sign 而盘上 0 字节 |
| ② 号与正文解耦 | `verify_proof(proof_no=2)` 不给正文 ⇒ 送进提示词的是 `#p1` 的正文，sha 却记在 `#p2` 上 | 提示词与 `proof_sha256` 都来自 `#p2`；`#p1` 不被牵连 |
| ③ 正文与号错配 | 给正文、漏 `proof_no` ⇒ 记到 `#p1` 上，而 sha 是 `#p2` 的 | 拒绝（或记到 `#p1` 且 sha 与 `#p1` 一致）；不许 sha 与号错配 |
| ④ 坏证明号 | `proof_no=0` / `'abc'` / `2.0` 被 `or 1` 静默折成 `#p1` ⇒ 签错一份证明 | 拒绝（不落台账、`checked=False`），`reason`/`detail` 点名"证明号认不出" |
| ⑤ 没签过 vs 没查成 | `state='unsigned'`（台账读得出、只是没签过）被报成 `checked=False`「台账读不出来（没查成）」 | `checked=True`、`state='unsigned'`；文案不许写"没查成" |
| ⑥ 追加失败 | 台账路径写不进去 ⇒ `writeback.reason` 说"台账那一行留着（签名确实发生过）"（而盘上 0 字节） | 三态 `append_state='failed'`、`written=False`、`re_sign_required=True`，理由串明说没写成；返回 `checked=False` |

## 三态纪律

这六条里最危险的不是"没签上"，而是"没签上却被读成签住了"：下游（论文档位、
收工门 R10、报告里的强度声明）全部读那一格。所以每条判据都断言"盘上有没有凭据"
与"返回值怎么说"这两件事必须一致，而不是只断言其中一边。

全部 tmp 工作区、零模型调用（V 的模型缝是一个只回一行 JSON 的假缝，成本 0）。
不读写 `projects/`，不跑 `run-agent`。
"""
from __future__ import annotations

import json
import pathlib
import sys

# 与 `tests/conftest.py` 同一个注入方式（这一份也要能在一棵临时源码树上单独跑：
# "改前红"就是把 `git show HEAD:…` 的旧文件铺到临时树的 `src/` 里、再跑这一份）。
_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agentflow import closing as CL
from agentflow import conductor as CND
from agentflow import evidencebits as EB
from agentflow import schema as S
from agentflow import verifications as VR
from agentflow import vsigns as VS
from agentflow.agent_v import AgentV

from _proof_manuscript_fixture import write_proof_manuscript
from agentflow.store import Store

TS = "2026-10-22T00:00:00+08:00"
SID = S.format_id(0)
#: 两份证明的正文（含各自独有的字样，好判"提示词里到底是哪一份"）。
P1 = "1. 由定义直接得到。\n2. 由 1 与假设 n >= 3 得结论。"
P2 = "另一条路线：\n1. 先证引理。\n2. 由引理得结论。"
P1_MARK = "由定义直接得到"
P2_MARK = "先证引理"
FULL = "设 G 是 3-正则群；则弦长函数不是常值。"
SHORT = "弦长函数不是常值"

_OK = {"verdict": "成立", "findings": []}
_BAD = {"verdict": "有毛病", "defect_step": 2, "why": "第 2 步没有依据",
        "findings": [{"level": "error", "step": 2, "kind": "无依据的步骤",
                      "detail": "第 2 步直接用了结论"}]}


# ------------------------------------------------------------------ 小工具

class _Seam:
    """零成本模型缝：把提示词收下来，回一行固定 JSON。"""

    def __init__(self, payload: dict | None = None) -> None:
        self.payload = payload if payload is not None else dict(_OK)
        self.prompts: list[str] = []

    def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return json.dumps(self.payload, ensure_ascii=False)


def _ws(path: pathlib.Path) -> Store:
    st = Store(path / "ws")
    st.init()
    return st


def _row(*, proof_text: str = P1, proofs: list | None = None,
         evidence_kind: str = "heuristic") -> dict:
    row = {
        "stmt_id": SID, "origin": "own_result", "kind": "theorem",
        "label": SHORT, "statement_full": FULL, "statement_text": SHORT,
        "proof_text": proof_text, "evidence_kind": evidence_kind, "status": "active",
        "quote_verified": None,
        "quote_reason": "我方自产命题，没有外部引文要比对",
        "created_at": TS, "created_by": "test",
        "bits": EB.bits_of(proof=True, proof_process=proof_text, kind="theorem"),
    }
    if proofs is not None:
        row[VR.PROOFS_KEY] = proofs
    return row


def _put(store: Store, **kw) -> dict:
    row = _row(**kw)
    with store.tx("statements", actor="test") as tx:
        tx.upsert("statements", row)
    return row


def _get(store: Store) -> dict:
    return dict(next(r for r in store.rows("statements")
                     if str(r.get("stmt_id")) == SID))


def _make_stock_proof_review(store: Store) -> None:
    """造一条"存量 `proof_review` 行"：canonical 未签，而档位已经写成 proof_review。

    写入期闸不允许新造这种行（它正是那道闸要拦的形态），所以照真机 mp1 的来路：
    先按 heuristic 落盘，再把 `data/statements.json` 上那一格改成 proof_review
    （`rebuild` 与读侧都照读存量，审计期由 `verify._check_13` 点名）。
    """
    path = store.data / "statements.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    hit = next(r for r in doc["rows"] if str(r.get("stmt_id")) == SID)
    hit["evidence_kind"] = "proof_review"
    path.write_bytes(json.dumps(doc, ensure_ascii=False).encode("utf-8"))


def _ledger_bytes(store: Store) -> int:
    path = VR.verification_ledger_path(store.root, SID)
    return path.stat().st_size if path.is_file() else 0


def _ledger_rows(store: Store) -> list[dict]:
    rows, problems = VR.list_verifications(store.root, statement_id=SID, limit=None)
    assert problems == [], problems
    return rows


def _per_proof(store: Store) -> dict:
    return EB.reviewed_by_proof(_get(store))


def _r10(store: Store) -> tuple[int, dict]:
    return CL._leg_reading(store, "reviewed_proof_rows", store.root)


def _v(store: Store, seam: _Seam) -> AgentV:
    return AgentV(store, workspace_root=store.root, llm=seam)


def _v_secretary(store: Store):
    """V 的秘书（离线替身缝：判 clean、判签发）。

    2026-10-29 的追加口径之后，发签权在秘书手上：`verify_proof` 只落台账，
    翻位那一步由 `Secretary.decide_sign_issuance` 调 `sign_statement` 落地。
    所以这一批判据要"真的签住"，就必须把秘书接上（而不是只调三次 verify_proof）。
    替身缝的答案取自 `test_v_sign_gate_streak`（同一份夹具，不抄第二份）。
    """
    from agentflow import secretary as SEC

    from test_v_sign_gate_streak import _Seam as _GateSeam
    from test_v_sign_gate_streak import _axis

    seam = _GateSeam({"v_reply_defect": [_axis(SEC.V_REPLY_CLEAN)],
                      "sign_issuance": [_axis(SEC.SIGN_ISSUE)]})
    return SEC.Secretary("V", root=store.root, store=store, seam=seam,
                         enable_model=True)


def _v_rounds(store: Store, *, proof_no: Any = 1, proof_text: str = "",
              times: int = 1) -> dict:
    """跑 `times`（缺省 1）次 `verify_proof`，返回最后一次的返回值。

    为什么缺省从 `SIGN_STREAK_NEED` 改成 1：2026-10-30 起一次 `verify_proof` 会自己
    连判到门槛为止（业主口径：「连续 3 次没问题」是 V 判完接着再判，不是 F 交三次）
    ⇒ 一次调用就是"一整趟攒票"，再跑三次只会让台账多出六行，而这一族判据要读的是
    "这一签真的签住"那一刻的返回值。
    """
    agent = AgentV(store, workspace_root=store.root, llm=_Seam(),
                   secretary=_v_secretary(store))
    no = int(proof_no or 1)
    body = proof_text or (P2 if no == 2 else P1)
    # 2026-11-04（甲）：在册送审必须带按号手稿；p2 走 `f-proof-<号>-p2.md`。
    rel = write_proof_manuscript(store.root, SID, body, statement_full=FULL, proof_no=no)
    out: dict = {}
    with CND.calling_as("t-v-000001", "V", parent_task_id="t-f-000001",
                        parent_role="F"):
        for _i in range(max(1, int(times))):
            kw = {"proof_no": proof_no, "proof_manuscript": rel}
            if proof_text:
                kw["proof_text"] = proof_text
            out = agent.verify_proof(SID, **kw)
    return out


# ============================================================ ① 撤回

#: p247：轴只由秘书给。这些夹具量的是写入口 / 盘点，不是秘书，故给 clean。
_CLEAN_JUDGE = {"checked": True, "axis": "clean", "decision": "没问题", "reason": "夹具"}
_vr_record = VR.record_verification
_vr_pending = VR.record_pending_sign


def _record(*args, **kwargs):
    kwargs.setdefault("secretary_judge", _CLEAN_JUDGE)
    return _vr_record(*args, **kwargs)


def _pending(*args, **kwargs):
    kwargs.setdefault("secretary_judge", _CLEAN_JUDGE)
    return _vr_pending(*args, **kwargs)


def test_a_rolled_back_signature_is_never_reported_as_signed(tmp_path: pathlib.Path) -> None:
    """① 存量 `proof_review` 行 + V 签 `#p2` ⇒ 真签住，或 `checked=False` 并说明。

    改前读数（`%TEMP%\\audit_ms\\p9.py`）：`writeback.rolled_back=True`、台账 0 字节、
    R10=0，而返回是 `checked=True verdict='成立' signed_bit3=True` —— 撤回把权威记录
    抹掉了，而调用方读到的每一个字都说"签住了"。

    修法有两半，这条判据同时钉住：写入期闸改读"任一份 signed 即放行"（`#p2` 签完
    这一行就够格），且返回只看"台账那一行有没有落地"。

    2026-10-29 追加口径之后，"签住"要多跑两次（连续 3 次「成立」）并且由 V 的秘书翻位
    ⇒ 取数口从"一次 `verify_proof`"换成 `_v_rounds`（第 3 次那一趟的返回值）。
    2026-10-30 起那两次不再由调用方跑：一次 `verify_proof` 自己连判三次（业主口径
    「V 判没问题后连续再判，不是 F 提交 3 次」）⇒ `_v_rounds` 的缺省次数回到 1，
    而断言的意思一个字没变：要么真签住（位翻了、R10 数得到），要么如实说没签住。
    """
    st = _ws(tmp_path)
    _put(st, proofs=[{"proof_no": 2, "proof_text": P2}])
    _make_stock_proof_review(st)
    assert _get(st)["evidence_kind"] == "proof_review"
    assert _ledger_bytes(st) == 0, "夹具前提：这一行一次都没签过"

    out = _v_rounds(st, proof_no=2)
    size = _ledger_bytes(st)

    # 不许出现"返回说签住、盘上 0 字节"（改前正是这个读数）。
    assert not (out["checked"] and out["signed_bit3"] and size == 0), (
        "返回说签住了第 3 位，而台账是 0 字节：" + json.dumps(out, ensure_ascii=False))
    assert out["proof_sha256"] == VR.text_sha(P2), out

    # 2026-11-08（V 只对手稿负责）：V 不再翻命题位，所以"签住了"这件事只由稿上那一格
    # 回答；返回值绝不许把 `signed_bit3` 说成真，也绝不许把 statements 写一个字。
    assert out["checked"] is True, out
    rows = _ledger_rows(st)
    assert len(rows) == VR.SIGN_STREAK_NEED and rows[-1]["proof_no"] == 2, rows
    assert rows[-1]["proof_sha256"] == VR.text_sha(P2), rows[-1]
    assert out["signed_bit3"] is False, out
    assert out["review_write"].get("manuscript_signed") is True, out["review_write"]
    assert out["review_write"].get("written") is False, out["review_write"]
    assert out["sign_issuance"]["issued"] is True, out["sign_issuance"]
    # statements 一个字节都没动：逐份位是空的（不是 {1: False, 2: True}）。
    assert _per_proof(st) == {}, _per_proof(st)
    assert _get(st)["bits"]["reviewed"] is False, _get(st)["bits"]
    assert size > 0, "三转的台账一行都没落"


def test_the_write_gate_lets_through_a_row_where_any_proof_is_signed(
        tmp_path: pathlib.Path) -> None:
    """① 的另一半（写入期闸用的复数版）：任一份 signed ⇒ `proof_review_gaps` 返回空列表。

    `evidence_kind` 是命题级的声明，而每份证明各自有第 3 位：存量行（`#p1` 未签、
    `#p2` 已成立）再交一次时，闸不许整笔拒收 —— 否则"如实登记"这条路本身被堵死，
    而拒收之后的撤回还会把台账那一行抹掉（本批审计第 1 条的两半）。
    反真空：一份都没签时，同一个函数必须把它点出来（否则"放行"可能只是恒真）。
    """
    st = _ws(tmp_path)
    _put(st, proofs=[{"proof_no": 2, "proof_text": P2}])
    _make_stock_proof_review(st)
    probe = dict(_get(st), evidence_kind="proof_review")

    # 反真空：一份都没签 ⇒ 闸点名它。
    before_gap = VR.proof_review_gap(st.root, probe)
    assert before_gap["ok"] is False, before_gap
    assert [g["statement_id"] for g in VR.proof_review_gaps(st.root, [probe])] == [SID]

    # 连续 3 次「成立」才签住（业主 2026-10-29）：一次就放行等于没有这道门槛。
    for _i in range(VR.SIGN_STREAK_NEED):
        _record(st.root, statement_id=SID, proof_text=P2, verdict=dict(_OK),
                               verifier="agent-V", store=st, proof_no=2)
    signed = dict(_get(st), evidence_kind="proof_review")
    assert VR.proof_review_gap(st.root, signed)["ok"] is True, VR.proof_review_gap(st.root, signed)
    assert VR.proof_review_gaps(st.root, [signed]) == [], "任一份 signed 仍然整笔拒收"
    # 而逐条读数仍然说清"canonical 那一份没签"（放行不等于读成 signed）。
    reading = VR.statement_review_reading(st.root, signed)
    assert reading["proofs"][0]["state"] == "unsigned", reading["proofs"][0]
    assert reading["proofs"][1]["state"] == "signed", reading["proofs"][1]


def test_the_rolled_back_row_itself_reports_not_landed(tmp_path: pathlib.Path) -> None:
    """① 的同族（写入口那一侧）：撤回之后 `record_verification` 的返回行 `checked=False`。

    这一条直接调写入口（不经模型缝），并用"提交时写入期闸拒收"造一次真实的回滚
    （`sign_statement` 的 `except` 分支：`_rollback_append` 把刚追加的那一行撤掉）。
    改前它返回的是原样那一份 `verdict=成立` 的记录，没有任何一格说"没落地"。
    """
    from agentflow import store as ST

    st = _ws(tmp_path)
    _put(st, proofs=[{"proof_no": 2, "proof_text": P2}])
    _make_stock_proof_review(st)

    def _refuse(*_a, **_k):
        raise ValueError(f"{VR.CODE_WRITE}：夹具：让这一笔提交失败，好测撤回那一支")

    # 先攒够两票（连续闸要求第 3 次才翻位）⇒ 第 3 次才会走到事务提交那一步，
    # 撤回那一支才被真的撞上。改前只需一次（一次成立就翻位）。
    for _i in range(VR.SIGN_STREAK_NEED - 1):
        _record(st.root, statement_id=SID, proof_text=P2,
                               verdict=dict(_OK), verifier="agent-V", flip=False,
                               proof_no=2)
    original = ST._refuse_fake_proof_review
    ST._refuse_fake_proof_review = _refuse
    try:
        row = _record(st.root, statement_id=SID, proof_text=P2,
                                     verdict=dict(_OK), verifier="agent-V",
                                     store=st, proof_no=2)
    finally:
        ST._refuse_fake_proof_review = original

    wb = row["statement_writeback"]
    assert wb["append_state"] == "appended", wb
    assert wb["rolled_back"] is True, wb
    assert row["checked"] is False, row
    assert "台账那一行被撤回" in row["reason"], row["reason"]
    assert _ledger_bytes(st) > 0, "夹具前提没造对：撤回之后台账该只剩前两票"
    assert len(_ledger_rows(st)) == VR.SIGN_STREAK_NEED - 1, "撤回没能只撤我们那一行"
    assert _get(st)["bits"]["reviewed"] is False, _get(st)["bits"]
    # V 那一侧不许把"被撤回"读成"签住了"。
    assert not (wb["written"] and row["checked"]), wb


# ============================================================ ② 号与正文绑定

def test_proof_no_binds_the_text_that_reaches_the_model(tmp_path: pathlib.Path) -> None:
    """② `verify_proof(proof_no=2)` 不给正文 ⇒ 提示词与 sha 都来自 `#p2`，`#p1` 不被牵连。

    改前（`p1.py`）：送进提示词的是 `#p1` 的正文（`hit["proof_text"]`），却把
    `#p2` 记在台账行上 —— 于是一条"审过了 #p2"的假证据，加上 `#p1` 被读成
    "签过一份它没被审的正文"。
    """
    st = _ws(tmp_path)
    _put(st, proofs=[{"proof_no": 2, "proof_text": P2}])
    seam = _Seam()
    agent = AgentV(st, workspace_root=st.root, llm=seam, secretary=_v_secretary(st))
    rel2 = write_proof_manuscript(st.root, SID, P2, statement_full=FULL, proof_no=2)
    with CND.calling_as("t-v-000001", "V", parent_task_id="t-f-000001",
                        parent_role="F"):
        for _i in range(VR.SIGN_STREAK_NEED):
            out = agent.verify_proof(SID, proof_no=2, proof_manuscript=rel2)

    assert seam.prompts, "没有问过模型 ⇒ 这条判据没有对象"
    assert seam.prompts[0], seam.prompts
    for prompt in seam.prompts:
        assert P2_MARK in prompt, "提示词里没有 #p2 的正文（给了别的证明的正文）"
        assert P1_MARK not in prompt, "提示词里混进了 #p1 的正文（号与正文解耦）"
    # 2026-11-11：`proof_no` 从 V 的顶层读数退役 ⇒ 号仍从台账那一行读（同一份事实）。
    assert int(_ledger_rows(st)[0]["proof_no"]) == 2, _ledger_rows(st)[0]
    assert out["proof_sha256"] == VR.text_sha(P2), (
        f"sha 不是 #p2 那一份的（{out['proof_sha256'][:12]}… vs {VR.text_sha(P2)[:12]}…）")
    assert _ledger_rows(st)[0]["proof_sha256"] == VR.text_sha(P2), _ledger_rows(st)[0]
    # 2026-11-08：载体是稿，"号与正文绑定"由稿本身保证：签只落在交给 V 的那一份稿上，
    # statements 一个字节不动（`#p1` 不会被牵连，也不会被借用）。
    assert out["signed_bit3"] is False, out
    assert out["review_write"].get("manuscript_signed") is True, out["review_write"]
    assert _per_proof(st) == {}, _per_proof(st)
    from agentflow import depsection as _DS
    from agentflow import vsigns as _VS

    _p2_text = (pathlib.Path(st.root) / rel2).read_text(encoding="utf-8")
    _p2_sign = _VS.manuscript_sign_standing(
        _p2_text, proof_sha=VR.text_sha(_DS.proof_body(_p2_text)),
        manuscript_path=rel2)
    assert _p2_sign["found"] is True and _p2_sign["signed"] is True, _p2_sign
    assert _p2_sign["proof_sha256"] == VR.text_sha(P2), _p2_sign


def test_a_proof_number_alone_cannot_carry_a_sign(tmp_path: pathlib.Path) -> None:
    """② 的反面（2026-11-08 新契约）：号不是载体，稿才是。

    - 只给 `proof_no=3`、不给稿 ⇒ 受控拒（`proof_text_needs_a_manuscript`），一行都不落；
    - 给了一份稿（正文是 P2）、号写 3 ⇒ V 审 / 签的是这份稿的正文（提示词里是 P2），
      台账回执里的号只是送审方给的标签；分配归 B 收录（`_proof_no_from_delivery`）。
    """
    st = _ws(tmp_path)
    _put(st, proofs=[{"proof_no": 2, "proof_text": P2}])
    seam = _Seam()
    out = _v(st, seam).verify_proof(SID, proof_no=3)
    assert out["checked"] is False and out["reason"] == "proof_text_needs_a_manuscript", out
    assert seam.prompts == [], "没有稿却问了模型（号不能顶替正文）"
    assert _ledger_bytes(st) == 0, "没审却落了台账行"

    rel = write_proof_manuscript(st.root, SID, P2, statement_full=FULL, proof_no=2)
    agent = AgentV(st, workspace_root=st.root, llm=seam,
                   secretary=_v_secretary(st))
    with CND.calling_as("t-v-000001", "V", parent_task_id="t-f-000001",
                        parent_role="F"):
        got = agent.verify_proof(SID, proof_no=3, proof_manuscript=rel)
    assert got["checked"] is True, got
    assert got["proof_sha256"] == VR.text_sha(P2), got
    assert seam.prompts and P2_MARK in seam.prompts[-1], (
        "给了稿却按号去取别的正文 ⇒ 「只对手稿负责」没落地")
    assert got["review_write"].get("manuscript_signed") is True, got["review_write"]
    assert _per_proof(st) == {}, _per_proof(st)


# ============================================================ ③ 正文与号错配

def test_text_without_proof_no_never_mismatches_the_recorded_number(
        tmp_path: pathlib.Path) -> None:
    """③ 给了 `#p2` 的正文却漏 `proof_no` ⇒ 拒绝（或记到 `#p1` 且 sha 与 `#p1` 一致）。

    改前（`p12.py`）：记到 `#p1`，而 `proof_sha256` 是 `#p2` 那一份的 —— 号与 sha
    各说一件事，读侧"这一签盖住的是哪一份"从此无解。
    """
    st = _ws(tmp_path)
    _put(st, proofs=[{"proof_no": 2, "proof_text": P2}])
    seam = _Seam()
    rel1 = write_proof_manuscript(st.root, SID, P1, statement_full=FULL)
    out = _v(st, seam).verify_proof(SID, proof_text=P2, proof_manuscript=rel1)

    if out["checked"]:
        # 记到 #p1 那一支：sha 必须是 #p1 的，否则就是错配。
        # 2026-11-11：`proof_no` 从 V 的顶层读数退役 ⇒ 号仍从台账那一行读。
        assert int(_ledger_rows(st)[-1]["proof_no"]) == 1, _ledger_rows(st)[-1]
        assert out["proof_sha256"] == VR.text_sha(P1), (
            f"记到 #p1 上，sha 却是别的证明的（{out['proof_sha256'][:12]}…）")
    else:
        # 拒绝那一支：说清是哪一格不符，且台账里没有这一签。
        assert out["reason"] == "proof_text_mismatch", out
        assert "sha" in out["detail"] and "proof_no" in out["detail"], out["detail"]
        assert _ledger_bytes(st) == 0, "拒了却落了台账行"
        assert out["signed_bit3"] is False, out


# ============================================================ ④ 坏证明号

def test_a_bad_proof_number_is_refused_not_folded_to_p1(tmp_path: pathlib.Path) -> None:
    """④ `proof_no=0` / `'abc'` / `2.0` ⇒ 拒绝（不落台账、`checked=False`），理由点名。

    改前（`p3.py`）：`as_proof_no(x) or 1` 把三个坏号都折成 `#p1`，于是"号给错了"
    变成"签了 canonical"，而台账上写着 `verdict=成立`。
    """
    for bad in (0, "abc", 2.0):
        st = _ws(tmp_path / f"bad_{str(bad).replace('.', '_')}")
        _put(st, proofs=[{"proof_no": 2, "proof_text": P2}])
        seam = _Seam()
        out = _v(st, seam).verify_proof(SID, proof_text=P1, proof_no=bad)
        assert out["checked"] is False, (bad, out)
        assert out["signed_bit3"] is False, (bad, out)
        assert "证明号认不出" in (str(out["reason"]) + str(out["detail"])), (bad, out)
        assert seam.prompts == [], (bad, "号认不出却问了模型")
        assert _ledger_bytes(st) == 0, (bad, "号认不出却落了台账行")

    # 写入口那一侧同样是拒绝（不是折成 #p1）：`record_verification` 抛 VerificationError。
    st = _ws(tmp_path / "write_side")
    _put(st)
    for bad in (0, "abc", 2.0):
        try:
            _record(st.root, statement_id=SID, proof_text=P1,
                                   verdict=dict(_OK), verifier="agent-V",
                                   store=st, proof_no=bad)
        except VR.VerificationError as exc:
            assert "证明号认不出" in str(exc), (bad, str(exc))
        else:
            raise AssertionError(f"坏证明号 {bad!r} 被接受了（折成了 #p1）")
    assert _ledger_bytes(st) == 0, "坏号被拒之后台账里仍有行"
    # 正控（防真空）：合法号照旧写得进去。
    _record(st.root, statement_id=SID, proof_text=P1,
                           verdict=dict(_OK), verifier="agent-V", store=st, proof_no=1)
    assert len(_ledger_rows(st)) == 1, _ledger_rows(st)


# ============================================================ ⑤ unsigned 不是没查成

def test_unsigned_is_a_checked_conclusion_not_an_unchecked_ledger(
        tmp_path: pathlib.Path) -> None:
    """⑤ 台账读得出、只是没签过 ⇒ `checked=True`；文案不许写"没查成"。

    改前（`p8.py`）：`state='unsigned'` 与 `state='unreadable'` 一起掉进最后那一段，
    于是"查过了、没签过"（处置：派 V）被报成"台账读不出来"（处置：查 I/O）。
    """
    st = _ws(tmp_path)
    _put(st, proofs=[{"proof_no": 2, "proof_text": P2}])
    # 让台账存在、读得出、但 canonical 一次都没签：只在 #p2 上落一签"有毛病"。
    _record(st.root, statement_id=SID, proof_text=P2, verdict=dict(_BAD),
                           verifier="agent-V", store=st, proof_no=2)
    assert VR.verification_ledger_path(st.root, SID).is_file()

    gap = VR.proof_review_gap(st.root, dict(_get(st), evidence_kind="proof_review"))
    assert gap["checked"] is True, gap
    assert gap["state"] == "unsigned", gap
    assert gap["ok"] is False, gap
    text = str(gap["why"]) + "".join(str(c.get("detail") or "") for c in gap["checklist"])
    assert "没查成" not in text, f"没签过被写成了「没查成」：{text}"
    assert "一次都没签" in text or "没有" in text, text
    # 对照：真正的坏行仍然是 checked=False（三态的另一半不许被这条修法顺手折平）。
    path = VR.verification_ledger_path(st.root, SID)
    path.write_bytes(path.read_bytes() + b"{broken line\n")
    gap2 = VR.proof_review_gap(st.root, dict(_get(st), evidence_kind="proof_review"))
    assert gap2["checked"] is False and gap2["problems"], gap2


# ============================================================ ⑥ 追加失败

def test_a_failed_append_says_so_and_never_claims_the_signature_happened(
        tmp_path: pathlib.Path) -> None:
    """⑥ 台账只读（追加失败）⇒ `append_state='failed'`、`re_sign_required=True`、`checked=False`。

    改前（`p6.py`）：`before = -1` 既是"追加前的字节数"又是"到底试没试过"，于是
    追加本身抛错时理由串照样写"台账那一行留着（签名确实发生过）"—— 而盘上 0 字节。

    造法：台账文件先落成空文件、再置只读（`open(..., "a")` 在 Windows 上抛
    `PermissionError`，POSIX 上抛 `EACCES`）；读它照旧成功，于是失败点正好落在
    "追加"这一格里。收尾前恢复可写，让 tmp 目录能删干净。
    """
    import os
    import stat

    def _make_readonly(store: Store) -> pathlib.Path:
        path = VR.verification_ledger_path(store.root, SID)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"")
        os.chmod(path, stat.S_IREAD)
        return path

    def _make_writable(path: pathlib.Path) -> None:
        if path.exists() and path.is_file():
            os.chmod(path, stat.S_IWRITE)

    st = _ws(tmp_path)
    _put(st)
    path = _make_readonly(st)
    try:
        row = _record(st.root, statement_id=SID, proof_text=P1,
                                     verdict=dict(_OK), verifier="agent-V",
                                     store=st, proof_no=1)
        wb = row["statement_writeback"]
        assert wb["append_state"] == "failed", wb
        assert wb["written"] is False, wb
        assert wb["re_sign_required"] is True, wb
        assert "没写成" in wb["reason"], wb["reason"]
        assert "签名确实发生过" not in wb["reason"], (
            "追加本身失败了，理由串却说「签名确实发生过」：" + str(wb["reason"]))
        assert row["checked"] is False, row
        # V 那一侧：同一个失败必须读成 `checked=False`，不许报"签住了第 3 位"。
        agent = AgentV(st, workspace_root=st.root, llm=_Seam(),
                       secretary=_v_secretary(st))
        out = agent.verify_proof(SID, proof_text=P1, proof_no=1, proof_manuscript=write_proof_manuscript(st.root, SID, P1, statement_full=FULL))
        assert out["checked"] is False, out
        assert out["signed_bit3"] is False, out
        assert "台账那一行" in out["reason"], out["reason"]
        assert out["review_write"]["append_state"] == "failed", out["review_write"]
        assert out["review_write"]["re_sign_required"] is True, out["review_write"]
    finally:
        _make_writable(path)

    # 正控（防真空）：台账恢复可写之后，同一签必须写得进去（上面的红不是恒红）。
    # 连续闸要求三次，所以这里跑三次、看最后一次：`written=True`（位翻了）。
    ok_row: dict = {}
    for _i in range(VR.SIGN_STREAK_NEED):
        ok_row = _record(st.root, statement_id=SID, proof_text=P1,
                                        verdict=dict(_OK), verifier="agent-V",
                                        store=st, proof_no=1)
        assert ok_row["statement_writeback"]["append_state"] == "appended", ok_row
    assert ok_row["statement_writeback"]["written"] is True, ok_row
    assert ok_row["checked"] is True, ok_row


# ============================================================ 判据 ⑦：pending 那一路同一条闸
#
# 2026-10-27 收口。改前 `_gap_from_pending` 的判据是 `verdict == "成立"` 这一个词，
# 而它自己的 docstring 写着"判据与台账那一路同一条（`signs_bit3`）"。`pending_sign`
# 当时只回四格，`unresolved_errors` / `citation_checks` / `citation_gate` 全被丢掉 ⇒
# 同一行内容：放进 `verifications/<命题号>.jsonl` 被拒（`rejected`），
# 放进 `verifications/pending/<sha>.jsonl` 就签住了（`signed`）。

def _gap_for(root: pathlib.Path) -> dict:
    """按 `proof_review_gap` 读这一条命题的凭据（命题台账不在盘上 ⇒ 走 pending 那一路）。"""
    return VR.proof_review_gap(root, {"stmt_id": SID, "kind": "theorem",
                                      "evidence_kind": "proof_review",
                                      "proof_text": P1})


def test_a_pending_sign_that_cannot_sign_bit3_is_not_a_signature(
        tmp_path: pathlib.Path) -> None:
    """判据 ⑦：`pending` 那一签也必须过 `signs_bit3`（同一份证据、两个落点、同一套判定）。

    四档一起判（改前全部读成 `signed`）：

    | 那一行的内容 | 改前 | 改后 |
    |---|---|---|
    | 成立 + 零 error | signed | signed（正控，防真空） |
    | 成立 + 2 条未解决 error | signed | rejected，第 3 条点名"未解决的 error 2 条" |
    | 成立 + 引用核实 `unknown` | signed | rejected，点名被引命题与那一档 |
    | 成立 + `citation_gate.problem` | signed | rejected，点名"引用核实没查成" |
    """
    root = tmp_path
    clean = _pending(root, proof_text=P1, verdict=dict(_OK))
    # 改前断言 → 改后断言（为什么）：`signs_bit3(那一行) is True` →
    # `row_signable(那一行) is True` 且 `signs_bit3(那一行) is False`。
    # pending 那一签按对象 sha 认领，它审的时候命题还没登记 ⇒ 没有命题台账可数
    # 连续次数，业主 2026-10-29 的"连续 3 次"闸在这一档结构上不适用（见
    # `verifications._gap_from_pending` 与 `numericproof` 的同一段注释）。
    # 所以这里判的是行局部那一半；而"不递 streak 就签不住"这条 fail-closed 纪律
    # 在同一行上照样成立（第二句）。
    assert VR.row_signable(dict(clean, verdict="成立")) is True
    assert VR.signs_bit3(dict(clean, verdict="成立")) is False
    gap = _gap_for(root)
    assert gap["ok"] is True and gap["state"] == "signed", gap

    errs = {"verdict": "成立",
            "findings": [{"level": "error", "step": 2, "kind": "无依据的步骤",
                          "detail": "第 2 步直接用了结论"}]}
    _pending(root, proof_text=P1, verdict=errs)
    gap = _gap_for(root)
    assert gap["ok"] is False and gap["state"] == "rejected", gap
    assert "未解决的 error 1 条" in gap["why"], gap["why"]
    assert "结论写了「成立」但签不住" in gap["why"], gap["why"]

    # 引用核实判不了（`unknown` 在 `CITATION_BLOCKING` 里）——同一行内容放进命题台账
    # 会被 `signs_bit3` 拒，pending 这边必须同样拒。
    cite = {"verdict": "成立", "findings": [],
            "citation_checks": [{"stmt_id": S.format_id(1), "verdict": "unknown",
                                 "quote_verbatim": False, "note": "判不了"}]}
    _pending(root, proof_text=P1, verdict=cite)
    gap = _gap_for(root)
    assert gap["ok"] is False and gap["state"] == "rejected", gap
    assert "引用核实挡住" in gap["why"], gap["why"]

    # 引用核实没查成（依赖台账读不出来）：改前这一格也读成签住了。
    gate_problem = _pending(root, proof_text=P1, verdict=dict(_OK))
    assert gate_problem.get("verdict") == "成立"
    path = VR.pending_ledger_path(root, VR.text_sha(P1))
    rows, problems = VR.JF.read_jsonl(path)
    assert problems == [], problems
    rows[-1]["citation_gate"] = {"ok": False, "problem": "依赖台账读不出来", "why": "读不出来"}
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
                    encoding="utf-8")
    gap = _gap_for(root)
    assert gap["ok"] is False and gap["state"] == "rejected", gap
    assert "引用核实没查成" in gap["why"], gap["why"]


def test_the_third_party_gate_reads_the_pending_route_with_the_same_bar(
        tmp_path: pathlib.Path) -> None:
    """判据 ⑦ 的另一半：B 的入库闸（`third_party_problems`）走 pending 那一路时同一条闸。

    改前 `latest_third_party_sign` 的 pending 分支只看 `verdict` 那个词 ⇒ 一条
    "成立 + 未解决 error" 的 pending 签能给 `proof` 盖章。正控（干净那一签）必须通过，
    否则这条判据只是恒红。
    """
    from agentflow import numericproof as NP

    root = tmp_path
    _pending(root, proof_text=P1, verdict=dict(_OK))
    assert NP.third_party_problems(P1, root=root) == []

    _pending(root, proof_text=P1, verdict={
        "verdict": "成立",
        "findings": [{"level": "error", "step": 1, "kind": "缝", "detail": "这一步没有依据"}]})
    problems = NP.third_party_problems(P1, root=root)
    assert problems, "一条成立 + 未解决 error 的 pending 签被当成第三方签字了"
    assert "签不住" in problems[0] or "未解决的 error" in problems[0], problems[0]


# ============================================================ 判据 ⑦（N1）：块不许比台账多票
#
# D268 附录 D 的规格。这一族的前六条各管一种"签名说谎"，唯独没有一条管票数：
# 手稿块（以及它的文件版）可以自称 `连续=3/3`，而台账上只有 1 条 clean 行。
# 批 1 只加只读读口 `sign_reading`；批 2 起 B 的 `bits_after_sign` 也改读它，所以这一条
# 判据判两件事：
#
#   a) 唯一读口看穿它（`state != signed`、`(votes, need) == (1, 3)`）；
#   b) B 的认签也看穿它（`applied is False`，设计 §6.2 第 2 条）。

def _n1_workspace(root: pathlib.Path) -> tuple[str, str, str]:
    """D268 附录 D 的夹具：一块手写 3/3 + 台账只 1 条 clean + 无签文件。"""
    rel = "reports/b-proof-000001.md"
    text = ("# 证明手稿（夹具）\n\n"
            "- 命题号：stmt:000001\n- 证明号：1\n\n"
            f"## 命题\n\n设 G 是 3-正则群；则弦长函数不是常值。\n\n"
            f"## 证明\n\n{P1}\n\n"
            "## 依赖\n\n| 依赖 | 类型 | 状态 | 说明 |\n|---|---|---|---|\n")
    (root / "reports").mkdir(parents=True)
    (root / "verifications").mkdir(parents=True)
    (root / rel).write_text(text, encoding="utf-8")
    sha = VS._sign_sha(VS.manuscript_proof_body(text))
    row = {"verification_id": "v-000001", "statement_id": "000001",
           "stmt_id": "000001", "proof_no": 1, "proof_sha256": sha,
           "verdict": "成立",
           "secretary_judge": {"axis": "clean", "checked": True},
           "unresolved_errors": 0, "findings": [],
           "manuscript": rel, "at": TS,
           "review_call": "call-1", "review_pass": 1}
    (root / "verifications" / "000001.jsonl").write_text(
        json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
    stamped = VS.stamp_manuscript_sign(
        text, proof_sha=sha, streak=3, need=3, verdict="成立",
        signer="secretary:B", at=TS,
        ledger="verifications/000001.jsonl#v-000001",
        statement_id="000001", manuscript_id="000001")
    (root / rel).write_text(stamped, encoding="utf-8")
    return rel, stamped, sha


def test_a_block_cannot_claim_more_votes_than_the_ledger_has(
        tmp_path: pathlib.Path) -> None:
    """N1 判据：块自称 3/3、台账只 1 票 ⇒ 唯一读口 `state != signed`、votes 1/3。"""
    rel, stamped, sha = _n1_workspace(tmp_path)
    assert VS.sign_of(tmp_path, sha)["found"] is False
    assert VS.manuscript_sign_standing(
        stamped, proof_sha=sha, manuscript_path=rel)["state"] == "signed"

    got = VS.sign_reading(tmp_path, statement_id="000001", proof_text=P1, proof_no=1)
    assert got["state"] != "signed", got
    assert got["state"] == "holding", got
    assert (got["votes"], got["need"]) == (1, 3), got
    assert "3/3" in got["why"], got["why"]
    assert got["body_state"] == "present"

    # 对照：今天已经读成 holding 的那一格（不是本批新翻的）。
    assert VR.review_standing(tmp_path, statement_id="000001",
                              proof_text=P1, proof_no=1)["state"] == "holding"

    # 批 2 的翻面：B 的闸已改读 `sign_reading` ⇒ 这一块不再被认（N1 的阻断级断言）。
    _bits, reading = VS.bits_after_sign(
        {}, root=tmp_path, proof_text=P1, statement_id="000001", proof_no=1,
        manuscript_text=stamped, manuscript_path=rel)
    assert reading["applied"] is False, reading
    assert reading["state"] == "holding"
    assert "3/3" in str(reading.get("why") or "")


def test_three_votes_from_one_call_are_a_sign(tmp_path: pathlib.Path) -> None:
    """N1 正控：三票同源 + `issue` 写签 ⇒ `signed`、`applied=True`（判据不许退化成"一律不签"）。"""
    rel = "reports/b-proof-000001.md"
    text = ("# 证明手稿（夹具）\n\n"
            "- 命题号：stmt:000001\n- 证明号：1\n\n"
            f"## 命题\n\n夹具命题。\n\n## 证明\n\n{P1}\n\n"
            "## 依赖\n\n| 依赖 | 类型 | 状态 | 说明 |\n|---|---|---|---|\n")
    (tmp_path / "reports").mkdir(parents=True)
    (tmp_path / "verifications").mkdir(parents=True)
    (tmp_path / rel).write_text(text, encoding="utf-8")
    sha = VS._sign_sha(VS.manuscript_proof_body(text))
    rows = [{"verification_id": f"v-{n:06d}", "statement_id": "000001",
             "stmt_id": "000001", "proof_no": 1, "proof_sha256": sha,
             "verdict": "成立",
             "secretary_judge": {"axis": "clean", "checked": True},
             "unresolved_errors": 0, "findings": [], "manuscript": rel,
             "at": TS, "review_call": "call-1", "review_pass": n}
            for n in (1, 2, 3)]
    (tmp_path / "verifications" / "000001.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
        encoding="utf-8")
    passes = [{"verification_id": r["verification_id"], "at": r["at"],
               "proof_sha256": sha, "review_call": "call-1",
               "review_pass": r["review_pass"]} for r in rows]
    issued = VS.issue(tmp_path, artifact_sha=sha, streak=3, need=3,
                      ledger="verifications/000001.jsonl#v-000003",
                      statement_id="000001", proof_no=1, passes=passes,
                      at=TS, by="secretary:B")
    assert issued["written"] is True, issued
    got = VS.sign_reading(tmp_path, statement_id="000001", proof_text=P1, proof_no=1)
    assert got["state"] == "signed", got
    assert (got["votes"], got["need"]) == (3, 3)
    stamped = VS.stamp_manuscript_sign(
        text, proof_sha=sha, streak=3, need=3, verdict="成立",
        signer="secretary:B", at=TS,
        ledger="verifications/000001.jsonl#v-000003",
        statement_id="000001", manuscript_id="000001")
    (tmp_path / rel).write_text(stamped, encoding="utf-8")
    assert VS.manuscript_sign_standing(
        stamped, proof_sha=sha, manuscript_path=rel)["state"] == "signed"
    _bits, reading = VS.bits_after_sign(
        {}, root=tmp_path, proof_text=P1, statement_id="000001", proof_no=1,
        manuscript_text=stamped, manuscript_path=rel)
    assert reading["applied"] is True, reading

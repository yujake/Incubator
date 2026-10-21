# -*- coding: utf-8 -*-
"""判据：V 签了的那一份证明，必须能被读成「审过」—— 且只对签的那一份算数。

## 这一份在治什么（`projects/p3-verify2` 的活证据）
V 真的签了字：`verifications/000004.jsonl` 里两行 `verdict=成立`、
`unresolved_errors=0`、`proof_sha256=d814fb48…` 与现行正文相符；而
`data/statements.json` 里 `000004` 那一行的 `bits.reviewed` 是 `false`、等级现算成
`conjecture` ⇒ 收工读数 R10（`closing._leg_reading` 的 `reviewed_proof_rows`）恒 0。
那是一处结构性的写口缺失：第 3 位的唯一写者是 B 的 `register_statement`，而它按
`evidencebits.BIT_OWNERS` 不替 V 签字；V 自己的写口（`verifications.record_verification`）
当时只写台账那个文件，从来不碰 `statements`。

## 判据（每条都带能红的反面）
| 判据 | 它要证明的事 |
|---|---|
| ① 正控：签现行那一份 | 命题行的第 3 位被翻真、R10 计数 = 1、签名行带 `(stmt_id, proof_no, proof_sha256)` |
| ② 负控一：签完再改 `proof_text` | 改稿这个写入本身必须成功；R10 = 0 且 `stale_ids` 里点名（哈希是读数，不是拒绝理由） |
| ③ 负控二：新证明出现 | 写入成功、可以继续干活；新那一份读成未签（或覆盖旧正文时读成 stale），不是"被拒" |
| ④ 负控三：正文排版不同 | 不影响 R10、不影响入正文（S2 的三条不因排版差异报错） |
| ⑤ 负控四：`verdict != 成立` | 位不动、R10 不算；它既不是 stale 也不是"没签过" |
| ⑥ 反真空：一次签名都没有 | `reviewed=False` 且 `stale_ids` 为空（"没签过"与"签过过期"必须分得开） |
| ⑦ 不许借光（多证明） | 证明 #1 签过、#2 没签 ⇒ #2 读成未签、它的档位不许被 #1 的签抬起来 |
| ⑧ 向后兼容（老数据） | 不带 `proof_no` 的签名行 / 没有证明清单的命题行 / 只写了第 3 位的旧行，读数逐字不变 |

全部 tmp 工作区、零模型调用（V 的签名路径在这里不经模型，直接调它的写入口）。
"""
from __future__ import annotations

import json
import pathlib
import sys

# 与 `tests/conftest.py` 同一个注入方式（这一份也要能在一棵临时源码树上单独跑：
# "改前红"就是把 `git show HEAD:…` 的旧文件铺到临时树里、再跑这一份）。
_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agentflow import closing as CL
from agentflow import evidencebits as EB
from agentflow import schema as S
from agentflow import verifications as VR
from agentflow.store import Store

TS = "2026-10-22T00:00:00+08:00"
SID = S.format_id(1)
PROOF1 = "1. 由定义直接得到。\n2. 由 1 与假设 n ≥ 3 得结论。"
PROOF2 = "另一条路线：\n1. 先证引理。\n2. 由引理得结论。"
STATEMENT = "设 G 是 3-正则群；则弦长函数不是常值。"
STATEMENT_TEXT = "弦长函数不是常值"

_OK = {"verdict": "成立", "findings": []}
_BAD = {"verdict": "有毛病", "defect_step": 2, "why": "第 2 步没有依据",
        "findings": [{"level": "error", "step": 2, "kind": "无依据的步骤",
                      "detail": "第 2 步直接用了结论"}]}


# ------------------------------------------------------------------ 小工具

def _ws(path: pathlib.Path) -> Store:
    st = Store(path / "ws")
    st.init()
    return st


def _statement_row(*, proof_text: str = PROOF1, bits: dict | None = None,
                   proofs: list | None = None, kind: str = "theorem",
                   evidence_kind: str = "heuristic") -> dict:
    row = {
        "stmt_id": SID, "origin": "own_result", "kind": kind,
        "label": "弦长函数非常值", "statement_full": STATEMENT,
        "statement_text": STATEMENT_TEXT, "proof_text": proof_text,
        "evidence_kind": evidence_kind, "status": "active",
        "quote_verified": None,
        "quote_reason": "我方自产命题，没有外部引文要比对",
        "created_at": TS, "created_by": "test",
        "bits": bits if bits is not None
                else EB.bits_of(proof=True, proof_process=proof_text, kind=kind),
    }
    if proofs is not None:
        row[VR.PROOFS_KEY] = proofs
    return row


def _put(store: Store, **kw) -> dict:
    """落一条命题行（走真正的写入路径）。"""
    row = _statement_row(**kw)
    with store.tx("statements", actor="test") as tx:
        tx.upsert("statements", row)
    return row


def _rewrite(store: Store, **patch) -> dict:
    """改盘上那一行（模拟"签完之后正文又改了" / "多了一份证明"）。

    走的是正常的 `store.tx`：它必须成功 —— 哈希是读数，不是拒收理由。
    """
    row = dict(store.rows("statements")[0])
    row.update(patch)
    with store.tx("statements", actor="test") as tx:
        tx.upsert("statements", row)
    return row


def _row(store: Store) -> dict:
    return dict(store.rows("statements")[0])


def _sign(store: Store, *, text: str = PROOF1, proof_no: int = 1,
          verdict: dict | None = None) -> dict:
    """V 的签名写入口（`verify.verify_proof` 走的就是它；这里不经模型）。"""
    return VR.record_verification(store.root, statement_id=SID, proof_text=text,
                                  verdict=verdict or _OK, verifier="agent-V",
                                  store=store, proof_no=proof_no)


def _r10(store: Store) -> tuple[int, dict]:
    """收工读数 R10（`reviewed_proof_rows`）与它的 detail。"""
    return CL._leg_reading(store, "reviewed_proof_rows", store.root)


def _read(store: Store, row: dict | None = None) -> dict:
    return VR.statement_review_reading(store.root, row or _row(store))


def _proof_of(reading: dict, proof_no: int) -> dict:
    hit = [p for p in reading["proofs"] if p["proof_no"] == proof_no]
    assert hit, reading["proofs"]
    return hit[0]


# ============================================================ ① 正控

def test_signing_the_current_proof_reaches_the_statement_row(tmp_path: pathlib.Path):
    """① 正控：签现行那一份 ⇒ 命题行第 3 位为真、R10 计数 = 1。

    改前这一条是红的：位停在 `False`、等级现算成 `conjecture`、R10 = 0 —— 而台账上
    明明有一行 `verdict=成立`、sha 与现行正文相符（p3-verify2 的形态）。
    """
    st = _ws(tmp_path)
    _put(st)
    assert _row(st)["bits"]["reviewed"] is False, "夹具前提：还没签"

    signed = _sign(st)
    # 签名行必须带 (stmt_id, proof_no, proof_sha256) —— 三者合起来回答"复核过的是哪一份"。
    assert signed["stmt_id"] == SID and signed["statement_id"] == SID, signed
    assert signed["proof_no"] == 1, signed
    assert signed["proof_sha256"] == VR.proof_sha(PROOF1), signed
    # 同一次写把第 3 位翻上去（写回读数也要看得见）
    wb = signed["statement_writeback"]
    assert wb["written"] is True and wb["rolled_back"] is False, wb
    row = _row(st)
    assert row["bits"]["reviewed"] is True, row["bits"]
    assert row["bits"]["grade"] == "pre_theorem", row["bits"]
    by = row["bits"]["evidence"]["reviewed_by"]
    assert by["proof_no"] == 1 and by["proof_sha256"] == VR.proof_sha(PROOF1), by
    assert by["verification_id"] == signed["verification_id"], by

    n, detail = _r10(st)
    assert n == 1, detail
    assert detail["review_states"]["signed"] == 1, detail
    assert detail["stale_ids"] == [] and detail["proofs_stale"] == [], detail
    assert [c["stmt_id"] for c in detail["counted"]] == [SID], detail


# ============================================================ ② 负控一

def test_editing_the_proof_after_signing_is_allowed_and_reads_stale(tmp_path: pathlib.Path):
    """② 负控一：签完再改 `proof_text` ⇒ 改稿成功、R10 = 0、`stale_ids` 点名。

    关键是"改稿这条动作本身必须成功"：哈希只回答"这份稿在你签完之后有没有被改过"，
    它是读数（in-sync / stale / 未签），不是授权凭证 —— 任何写入路径都不因 sha 不符拒写。
    """
    st = _ws(tmp_path)
    _put(st)
    _sign(st)
    assert _r10(st)[0] == 1

    edited = PROOF1 + "\n3. 补上一步（这一句是签完之后才加的）。"
    row = _rewrite(st, proof_text=edited)          # 必须成功，不许被拒
    assert row["proof_text"] == edited, row
    # 位还停在 True 上（写侧不再翻它），而读侧必须把它读成"没审过"。
    assert _row(st)["bits"]["reviewed"] is True, "夹具前提：位没有被写侧改回去"
    assert EB.bits_from_row(_row(st))["reviewed"] is False, "读侧必须判成过期"

    n, detail = _r10(st)
    assert n == 0, detail
    assert detail["review_states"]["stale"] == 1, detail
    assert detail["stale_ids"] == [SID], detail
    assert detail["proofs_stale"] == [f"{SID}#p1"], detail
    assert detail["counted"] == [], detail


# ============================================================ ③ 负控二

def test_a_new_proof_is_writable_and_reads_unreviewed_not_refused(tmp_path: pathlib.Path):
    """③ 负控二：新证明出现 ⇒ 写入成功、可以继续干活；状态只标成待复核。

    两半各是一个形态：
    (a) 新增一份证明（`#p2`）⇒ 写入成功；#p1 的旧签不否决它、也不替它背书 ⇒ #p2 读成未签；
    (b) 覆盖 `#p1` 的正文（不重签）⇒ 写入成功；读数变成 stale（不是"被拒"）。
    """
    st = _ws(tmp_path)
    _put(st)
    _sign(st)

    # (a) 新增 #p2
    _rewrite(st, **{VR.PROOFS_KEY: [{"proof_no": 2, "proof_text": PROOF2}]})
    assert [no for no, _ in VR.proof_list(_row(st))] == [1, 2]
    reading = _read(st)
    assert reading["reviewed"] is True, reading          # #p1 仍签着（新证明不否决旧签名）
    assert reading["proofs_unreviewed"] == [f"{SID}#p2"], reading
    p2 = _proof_of(reading, 2)
    assert p2["state"] == "unsigned" and p2["reviewed"] is False, p2
    assert p2["grade"] == "conjecture", p2
    n, detail = _r10(st)
    assert n == 1, detail                                # 命题仍有一条被审过的证明
    assert detail["proofs_unreviewed"] == [f"{SID}#p2"], detail

    # (b) 覆盖 #p1 的正文（不重签）
    _rewrite(st, proof_text=PROOF1 + "\n4. 换了一种写法。")
    n2, d2 = _r10(st)
    assert n2 == 0, d2
    assert d2["stale_ids"] == [SID], d2
    assert d2["proofs_stale"] == [f"{SID}#p1"], d2


# ============================================================ ④ 负控三

def test_a_differently_typeset_paper_does_not_touch_the_review_reading(tmp_path: pathlib.Path):
    """④ 负控三：正文排版与 `proof_text` 逐字不同 ⇒ 不影响 R10、不影响入正文。

    正文与台账是两份表示（业主口径第 3 条）：正文侧只查"这条定理在台账里有行、完整
    证明可查"（S2 的三条），与 sha 无关。所以这里造一份 tex：定理环境的正文与台账
    逐字一致（排版层允许不同），而证明段的写法与 `proof_text` 完全不是同一串字。
    另加一条正控：定理在那条台账里找不到时 S2 必须报错 —— 否则"排版不报错"
    可能只是因为判据什么都没查（真空通过）。
    """
    st = _ws(tmp_path)
    _put(st)
    _sign(st)
    n_before, d_before = _r10(st)
    assert n_before == 1, d_before

    paper = st.root / "out" / "paper"
    paper.mkdir(parents=True, exist_ok=True)
    tex = ("\\documentclass{article}\n\\begin{document}\n"
           "\\begin{theorem}" + STATEMENT_TEXT + "\\end{theorem}\n"
           "\\begin{proof}换一套排版写出来的一整段（与台账里的 proof_text 逐字不同）："
           "先取定义，再用假设 n $\\ge$ 3 收尾。\\end{proof}\n"
           "\\end{document}\n")
    (paper / "main.tex").write_text(tex, encoding="utf-8")
    assert CL.paper_proof_scaffolding_problems(st.root) == [], "排版差异不许被读成缺证明"

    n_after, d_after = _r10(st)
    assert n_after == n_before == 1, (n_before, n_after, d_after)
    assert d_after["review_states"] == d_before["review_states"], (d_before, d_after)

    # 正控（防止上一条是真空通过）：同一条判据在同一条台账上必须能报错 ——
    # 把定理正文换成台账里没有的一句，S2 就必须点名"没有对应行"。
    (paper / "main.tex").write_text(tex.replace(STATEMENT_TEXT, "这一句台账里没有"), encoding="utf-8")
    problems = CL.paper_proof_scaffolding_problems(st.root)
    assert problems and "没有对应行" in problems[0], problems


# ============================================================ ⑤ 负控四

def test_a_rejecting_verdict_leaves_the_bit_alone_and_is_not_counted(tmp_path: pathlib.Path):
    """⑤ 负控四：`verdict != 成立` ⇒ 位不动、R10 不算；也不是 stale / 不是没签过。"""
    st = _ws(tmp_path)
    _put(st)
    signed = _sign(st, verdict=_BAD)
    assert signed["verdict"] == "有毛病", signed
    wb = signed["statement_writeback"]
    assert wb["written"] is False and "签不住" in wb["reason"], wb
    assert _row(st)["bits"]["reviewed"] is False, _row(st)["bits"]

    n, detail = _r10(st)
    assert n == 0, detail
    assert detail["review_states"]["rejected"] == 1, detail
    assert detail["rejected_ids"] == [SID], detail
    # 签的就是这一份、结论是没过 ⇒ 不是"签过过期"，也不许折成"没签过"
    assert detail["stale_ids"] == [] and detail["proofs_stale"] == [], detail
    assert detail["proofs_unreviewed"] == [], detail


# ============================================================ ⑥ 反真空

def test_no_signature_at_all_is_unsigned_not_stale(tmp_path: pathlib.Path):
    """⑥ 反真空：一条签名都没有 ⇒ `reviewed=False` 且 `stale_ids` 为空。

    "没签过"与"签过过期"是两件事：前者要派 V，后者要重签现在这一版。折成一件事
    之后，`stale_ids` 这一档读数会被所有没审过的命题灌满，于是没人再看它。
    """
    st = _ws(tmp_path)
    _put(st)
    assert _row(st)["bits"]["reviewed"] is False, _row(st)["bits"]

    n, detail = _r10(st)
    assert n == 0, detail
    assert sum(detail["review_states"].values()) == 0, detail["review_states"]
    assert detail["review_ledger_rows"] == 0, detail
    assert detail["stale_ids"] == [] and detail["proofs_stale"] == [], detail
    assert detail["proofs_unreviewed"] == [], detail
    assert detail["counted"] == [], detail


# ============================================================ ⑦ 不许借光

def test_proof_two_cannot_borrow_proof_ones_signature(tmp_path: pathlib.Path):
    """⑦ 不许借光：证明 #1 的签不替 #2 背书（两个方向都判）。

    (a) 只签 #1 ⇒ 命题级算"有一条被审过的证明"，但 #2 自己读成未签、档位仍是猜想；
    (b) 只签 #2 ⇒ #1 自己读成未签、档位仍是猜想（反向也不许借）。
    """
    st = _ws(tmp_path / "a")
    _put(st, proofs=[{"proof_no": 2, "proof_text": PROOF2}])
    signed = _sign(st)                                  # 只签 #p1
    wb = signed["statement_writeback"]
    assert wb["written"] is True and wb["proof_no"] == 1, wb
    reading = _read(st)
    assert reading["reviewed"] is True and reading["grade"] == "pre_theorem", reading
    p1, p2 = _proof_of(reading, 1), _proof_of(reading, 2)
    assert p1["state"] == "signed" and p1["grade"] == "pre_theorem", p1
    assert p2["state"] == "unsigned" and p2["reviewed"] is False, p2
    assert p2["grade"] == "conjecture", "#p2 借了 #p1 的签"
    assert reading["proofs_unreviewed"] == [f"{SID}#p2"], reading
    assert reading["proofs_stale"] == [], reading

    # (b) 反向：只签 #p2
    st2 = _ws(tmp_path / "b")
    _put(st2, proofs=[{"proof_no": 2, "proof_text": PROOF2}])
    _sign(st2, text=PROOF2, proof_no=2)
    reading2 = _read(st2)
    assert reading2["reviewed"] is True, reading2
    q1, q2 = _proof_of(reading2, 1), _proof_of(reading2, 2)
    assert q2["state"] == "signed" and q2["grade"] == "pre_theorem", q2
    assert q1["state"] == "unsigned" and q1["grade"] == "conjecture", "#p1 借了 #p2 的签"
    # 写回只翻被签的那一份：清单里 #p2 被标上，而 #p1 的位（canonical 的 `bits.reviewed`）
    # 是命题级汇总，不许被当成"#p1 被审过"来读 —— 逐条读数里它仍是 unsigned。
    assert _row(st2)["proofs"][0]["reviewed"] is True, _row(st2)["proofs"]


# ============================================================ ⑧ 向后兼容

def test_old_data_without_proof_no_reads_exactly_as_before(tmp_path: pathlib.Path):
    """⑧ 向后兼容：不带 `proof_no` 的签名行 / 没有证明清单的命题行，读数逐字不变。

    三种老形态都要照旧：
    (a) 老签名行（只有 `statement_id` + `proof_sha256`，没有 `stmt_id` / `proof_no`）；
    (b) 老判据（`verifications.proof_review_gap` 对同一行仍判 `ok=True`、sha 相符）；
    (c) 只有第 3 位、台账里一次都没有的老命题行 —— 仍按位读，不由新读侧折成 0。
    """
    st = _ws(tmp_path)
    _put(st)
    path = VR.verification_ledger_path(st.root, SID)
    path.parent.mkdir(parents=True, exist_ok=True)
    old_row = {"verification_id": "v-000001", "statement_id": SID, "verifier": "V",
               "verdict": "成立", "findings": [], "unresolved_errors": 0,
               "proof_sha256": VR.proof_sha(PROOF1), "proof_chars": len(PROOF1),
               "round": 1, "at": TS}
    path.write_text(json.dumps(old_row, ensure_ascii=False) + "\n", encoding="utf-8")

    n, detail = _r10(st)
    assert n == 1, detail
    assert detail["review_states"]["signed"] == 1, detail
    assert detail["stale_ids"] == [] and detail["proofs_unreviewed"] == [], detail
    gap = VR.proof_review_gap(st.root, {"stmt_id": SID, "proof_text": PROOF1,
                                        "evidence_kind": "proof_review"})
    assert gap["ok"] is True and gap["sha_matches"] is True, gap
    # 没有证明清单 ⇒ 只有 #p1 一条，编号与正文都不变
    assert VR.proof_list(_row(st)) == [(1, PROOF1)], VR.proof_list(_row(st))

    # (c) 只有第 3 位、台账里一次都没有：老读法照旧（那一行就是它的唯一读数）
    st2 = _ws(tmp_path / "b")
    legacy = EB.bits_of(proof=True, proof_process=PROOF1, reviewed=True,
                        reviewed_by={"round": "V-0001", "verdict": "no_defect"},
                        kind="theorem")
    _put(st2, bits=legacy)
    n2, d2 = _r10(st2)
    assert n2 == 1, d2
    assert d2["review_ledger_rows"] == 0, d2
    assert d2["stale_ids"] == [], d2

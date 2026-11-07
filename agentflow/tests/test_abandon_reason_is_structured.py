# -*- coding: utf-8 -*-
"""换号（放弃命题）必须带结构化理由 —— 业主 2026-11-07 裁定。

业主原话（逐字，这就是本文件的验收标准）：

> 「换号需给清理由：1.命题有实质数学错误；2.证明过程中遇到难以逾越的困难。
>   对于1，需在换号理由中指出错误；对于2，需指出困难，并将原先证明中可取之处拆出落成引理。」

## 改前 / 改后的真实形态（98 的读数）

`projects/paper-rewrite-98/data/statements.json` 里 15 条 `kind=conjecture` 的命题全部
`status=abandoned`，而 `quote_reason` 都是自由文本：

| 号 | 理由（改前的原文，节选） |
|---|---|
| 000040–000048 | 「无干净依据：verifications/ 下不存在 0000NN.jsonl」（九条，同一秒 21:19:52 批量） |
| 000049 | 「V 已在 verifications/000049.jsonl 判「有毛病」…」（自由文本，读不出 `defect_step`） |
| 000050 | 「000050 是 000049 同一缺陷件的重登记：label 同为 lem:cancel…」 |
| 000036 / 000037 / 000039 | 「本行不是数学命题，而是 F 一方的作业/验收规格」 |

⇒ 改前：这些行都写进去了（`status=abandoned` + 一段散文），而"同一 label 再登记"
（000049 → 000050）在盘上没有任何结构化读写得出"前一件的理由齐不齐"。

## 本文件守的六件事

| 编号 | 判据 | 用例 |
|---|---|---|
| a | 自由文本换号 ⇒ 受控拒（缺 kind/basis），一个字节都不写 | `test_a_*` |
| b | math_error：真的判「有毛病」+ 点名步号 ⇒ 过；引用不存在 / 判成立的行 ⇒ 拒 | `test_b_*` |
| c | difficulty：`salvaged` 空 ⇒ 拒；active 引理 ⇒ 过；abandoned 引理 ⇒ 拒 | `test_c_*` |
| d | 同一 label 换号两次 ⇒ `relabeled` 里能看到 2 次 | `test_d_*` |
| e | 反真空：摘掉 salvaged / defect_ref 校验 ⇒ 对应那条红 | `test_e_*` |
| f | 概念行不是命题 ⇒ 放弃它不被这道闸拦 | `test_f_*` |
"""

from __future__ import annotations

import pathlib

from agentflow import closing as CL
from agentflow import conductor as CND
from agentflow import secretary as SEC
from agentflow import statementabandon as SA
from agentflow import verifications as VR
from agentflow.store import Store

TS = "2026-11-07T09:00:00+08:00"
SID = "000001"
LEMMA = "000002"
FULL = "设 f 在 [0,1] 上连续，则 f 一致连续。"
PROOF = "取 δ=ε，逐点验证：|x-y|<δ ⇒ |f(x)-f(y)|<ε。"
DEFECT = "verifications/000001.jsonl#v-000001"


def _ws(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _put(st: Store, sid: str = SID, *, kind: str = "theorem",
         label: str = "", status: str = "active",
         quote_reason: str = "夹具：自产命题") -> dict:
    row = {
        "stmt_id": sid, "origin": "own_result", "kind": kind,
        "label": label or f"探针命题 {sid}", "statement_full": FULL,
        "statement_text": FULL, "proof_text": PROOF,
        "evidence_kind": "heuristic", "status": status,
        "quote_verified": None, "quote_reason": quote_reason,
        "created_at": TS, "created_by": "test", "bits": {},
    }
    with st.tx("statements", actor="test") as tx:
        tx.upsert("statements", row)
    return row


def _verify(st: Store, sid: str = SID, *, verdict: str = "有毛病",
            fault: bool = True, step: int | None = 5) -> dict:
    findings = ([{"detail": "夹具：第 5 步的断言不成立", "level": "error", "step": step}]
                if verdict == "有毛病" else [])
    return VR.record_verification(
        st.root, statement_id=sid, proof_text=PROOF,
        verdict={"verdict": verdict, "defect_step": step, "findings": findings},
        secretary_judge={"axis": "fault" if fault else "clean", "checked": True,
                         "reason": "夹具：秘书的语义判定"},
        flip=False)


def _registry(st: Store):
    from agentflow.tools import table_tools
    from agentflow.tools.base import ToolRegistry

    reg = ToolRegistry(name="tables")
    reg.bound_role = "B"
    table_tools.register(reg, store=st)
    return reg


def _abandon(st: Store, sid: str = SID, **kw):
    """走生产的通用写口（`table.update`）放弃一条命题。"""
    reg = _registry(st)
    with CND.calling_as("t-b1", "B"):
        return reg.call("table.update", table="statements", id=sid, **kw)


def _row(st: Store, sid: str = SID) -> dict:
    return next(dict(r) for r in st.rows("statements") if str(r.get("stmt_id")) == sid)


def _count(st: Store) -> int:
    return len(list(st.rows("statements")))


def _abandoned(st: Store) -> dict:
    return CL.statements_abandoned_reading(st)


MATH = dict(abandon_kind="math_error",
            abandon_basis="第 5 步直接用了结论：那一步的界对不上，命题本身的断言不成立")


# ---------------------------------------------------------------- a 自由文本换号 ⇒ 受控拒

def test_a_free_text_abandonment_is_refused_and_writes_nothing(tmp_path):
    """a：98 那种形状（只要 status + 一段散文）⇒ 受控拒，盘上一个字节都没改。

    反例逐字取自 98 的 000040（九条同一秒批量放弃的那一批）：
    `无干净依据：verifications/ 下不存在 000040.jsonl`。
    """
    st = _ws(tmp_path)
    _put(st)
    _verify(st)
    before = _row(st)
    before_n = _count(st)
    res = _abandon(st, patch={"status": "abandoned",
                              "quote_reason": SA.abandon_marker(
                                  at=TS, reason="无干净依据：verifications/ 下不存在 000001.jsonl")})
    assert res.ok is False, res
    got = dict(res.meta or {})
    assert got.get("kind") == "abandon_reason_missing", got
    assert "abandon_kind" in str(res.error or ""), res.error
    after = _row(st)
    assert after == before, "受控拒必须一个字节都不写"
    assert _count(st) == before_n, "不得多出/少掉任何一行"
    assert _abandoned(st)["count"] == 0, _abandoned(st)


def test_a_direct_call_without_kind_or_basis_is_refused(tmp_path):
    """a 的第二条路：直接调写口（不经工具面）也必须拒。"""
    st = _ws(tmp_path)
    _put(st)
    _verify(st)
    got = SA.apply_abandonment(st, statement_id=SID, reason="无干净依据", at=TS)
    assert got["checked"] is False, got
    assert got["refused"] == "abandon_reason_missing", got
    assert _row(st)["status"] == "active", _row(st)


def test_a_kind_outside_the_two_values_is_refused(tmp_path):
    """a：第三档不接受（业主只裁了两档）。"""
    st = _ws(tmp_path)
    _put(st)
    _verify(st)
    got = SA.apply_abandonment(st, statement_id=SID, reason="理由", at=TS,
                               abandon_kind="not_a_proposition",
                               abandon_basis="这一行不是命题")
    assert got["refused"] == "abandon_kind_not_allowed", got
    assert _row(st)["status"] == "active", _row(st)


# ---------------------------------------------------------------- b math_error 档

def test_b_math_error_with_a_real_defect_ref_passes(tmp_path):
    """b 正控：`defect_ref` 真的存在、判「有毛病」、理由点名那一步 ⇒ 过。"""
    st = _ws(tmp_path)
    _put(st)
    _verify(st)
    res = _abandon(st, patch={"status": "abandoned"}, **MATH, defect_ref=DEFECT)
    assert res.ok is True, (res.error, res.data)
    row = _row(st)
    assert row["status"] == "abandoned", row
    parsed = SA.parse_abandon(row["quote_reason"])
    assert parsed["checked"] is True, parsed
    structured = SA.parse_abandon_reason(row["quote_reason"])
    assert structured["structured"] is True and structured["complete"] is True, structured
    assert structured["abandon_kind"] == "math_error", structured
    assert structured["defect_ref"] == DEFECT, structured
    # 行上读得回来（读数一个口）
    read = _abandoned(st)
    assert read["count"] == 1 and read["rows"][0]["abandon_kind"] == "math_error", read


def test_b_a_defect_ref_that_does_not_exist_is_refused(tmp_path):
    """b 负控①：引一行不存在的判词 ⇒ 拒。"""
    st = _ws(tmp_path)
    _put(st)
    _verify(st)
    got = SA.apply_abandonment(st, statement_id=SID, reason="理由", at=TS,
                               abandon_kind="math_error",
                               abandon_basis="第 5 步错了", defect_ref=DEFECT)
    # 上面的 DEFECT 是真的存在的那一条 ⇒ 先证正控可过，再用一个假的
    assert got["checked"] is True, got

    _put(st, "000003", label="第二条")
    missing = SA.apply_abandonment(st, statement_id="000003", reason="理由", at=TS,
                                   abandon_kind="math_error", abandon_basis="第 5 步错了",
                                   defect_ref="verifications/000003.jsonl#v-000009")
    assert missing["checked"] is False, missing
    assert missing["refused"] == "abandon_defect_ref_unreadable", missing
    assert _row(st, "000003")["status"] == "active", _row(st, "000003")


def test_b_a_clean_verdict_row_cannot_be_the_defect_ref(tmp_path):
    """b 负控②：拿一行「成立」当 defect_ref ⇒ 拒（它不是"命题有数学错误"的依据）。"""
    st = _ws(tmp_path)
    _put(st)
    _verify(st, verdict="成立", fault=False, step=None)
    got = SA.apply_abandonment(st, statement_id=SID, reason="理由", at=TS,
                               abandon_kind="math_error",
                               abandon_basis="第 5 步错了",
                               defect_ref=DEFECT)
    assert got["checked"] is False, got
    assert got["refused"] == "abandon_defect_ref_not_fault", got
    assert _row(st)["status"] == "active", _row(st)


def test_b_basis_must_name_the_step_the_defect_ref_points_at(tmp_path):
    """b：理由里没点名 `defect_step` 那一步 ⇒ 拒（"错在哪一步"对不上）。"""
    st = _ws(tmp_path)
    _put(st)
    _verify(st)
    got = SA.apply_abandonment(st, statement_id=SID, reason="理由", at=TS,
                               abandon_kind="math_error",
                               abandon_basis="这条命题是错的（没说哪一步）",
                               defect_ref=DEFECT)
    assert got["checked"] is False, got
    assert got["refused"] == "abandon_defect_step_mismatch", got
    # 点名了就过（正控与负控是同一条判据的两侧）
    ok = SA.apply_abandonment(st, statement_id=SID, reason="理由", at=TS,
                              abandon_kind="math_error",
                              abandon_basis="Step 5 的界对不上", defect_ref=DEFECT)
    assert ok["checked"] is True, ok


def test_b_missing_defect_ref_is_refused(tmp_path):
    """b：math_error 而不给 defect_ref ⇒ 拒（说不出错在哪一行）。"""
    st = _ws(tmp_path)
    _put(st)
    _verify(st)
    got = SA.apply_abandonment(st, statement_id=SID, reason="理由", at=TS,
                               abandon_kind="math_error", abandon_basis="第 5 步错了")
    assert got["refused"] == "abandon_defect_ref_required", got


# ---------------------------------------------------------------- c difficulty 档

DIFF = dict(abandon_kind="difficulty",
            abandon_basis="这一步的界对不上：缺一条关于 K 的速降假设，现有工具补不出来",
            difficulty="缺一条 K 在 Re u>=1 的速降假设；试过三条路都绕不过去")


def test_c_empty_salvaged_is_refused(tmp_path):
    """c 负控①：`salvaged` 为空 ⇒ 受控拒（业主原话：将可取之处拆出落成引理）。"""
    st = _ws(tmp_path)
    _put(st)
    _put(st, LEMMA, kind="lemma", label="引理 A")
    res = _abandon(st, patch={"status": "abandoned"}, salvaged=[], **DIFF)
    assert res.ok is False, res
    got = dict(res.meta or {})
    assert got.get("kind") == "abandon_salvaged_missing", got
    assert _row(st)["status"] == "active", _row(st)


def test_c_an_active_lemma_passes(tmp_path):
    """c 正控：给一条在册、active、kind=lemma 的引理 ⇒ 过。"""
    st = _ws(tmp_path)
    _put(st)
    _put(st, LEMMA, kind="lemma", label="引理 A：K 的速降")
    res = _abandon(st, patch={"status": "abandoned"},
                   salvaged=[{"label": "引理 A：K 的速降", "stmt_id": LEMMA}], **DIFF)
    assert res.ok is True, (res.error, res.data)
    row = _row(st)
    structured = SA.parse_abandon_reason(row["quote_reason"])
    assert structured["complete"] is True, structured
    assert structured["abandon_kind"] == "difficulty", structured
    assert structured["salvaged"][0]["stmt_id"] == LEMMA, structured
    assert structured["difficulty"], structured
    # 那条引理本身没被动（拆出来的引理是它的证据，不是它的替身）
    assert _row(st, LEMMA)["status"] == "active", _row(st, LEMMA)


def test_c_an_abandoned_lemma_is_refused(tmp_path):
    """c 负控②：拿一条已 abandoned 的引理当"可取之处" ⇒ 拒。"""
    st = _ws(tmp_path)
    _put(st)
    _put(st, LEMMA, kind="lemma", label="引理 A", status="abandoned",
         quote_reason=SA.abandon_marker(at=TS, reason="这条引理也不要了"))
    got = SA.apply_abandonment(st, statement_id=SID, reason="理由", at=TS,
                               salvaged=[{"label": "引理 A", "stmt_id": LEMMA}], **DIFF)
    assert got["checked"] is False, got
    assert got["refused"] == "abandon_salvaged_not_active", got
    assert _row(st)["status"] == "active", _row(st)


def test_c_a_non_lemma_kind_is_refused(tmp_path):
    """c 负控③：`salvaged` 只认引理类（拆出来的是"引理"，不是定理/猜想）。"""
    st = _ws(tmp_path)
    _put(st)
    _put(st, LEMMA, kind="theorem", label="另一条定理")
    got = SA.apply_abandonment(st, statement_id=SID, reason="理由", at=TS,
                               salvaged=[{"label": "另一条定理", "stmt_id": LEMMA}], **DIFF)
    assert got["checked"] is False, got
    assert got["refused"] == "abandon_salvaged_kind_not_lemma", got


def test_c_a_lemma_that_is_not_registered_is_refused(tmp_path):
    """c 负控④：`stmt_id` 不在册 ⇒ 拒。"""
    st = _ws(tmp_path)
    _put(st)
    got = SA.apply_abandonment(st, statement_id=SID, reason="理由", at=TS,
                               salvaged=[{"label": "编的引理", "stmt_id": "000099"}], **DIFF)
    assert got["checked"] is False, got
    assert got["refused"] == "abandon_salvaged_not_registered", got


def test_c_difficulty_without_the_difficulty_cell_is_refused(tmp_path):
    """c 负控⑤：说清难在哪那一格空着 ⇒ 拒（"做不动了"不是指出困难）。"""
    st = _ws(tmp_path)
    _put(st)
    _put(st, LEMMA, kind="lemma", label="引理 A")
    got = SA.apply_abandonment(st, statement_id=SID, reason="理由", at=TS,
                               abandon_kind="difficulty", abandon_basis="做不动了",
                               salvaged=[{"label": "引理 A", "stmt_id": LEMMA}])
    assert got["refused"] == "abandon_difficulty_required", got


# ---------------------------------------------------------------- d 换号读数

def test_d_relabeled_shows_two_relabels_for_the_same_label(tmp_path):
    """d：同一 label 下放弃两次 ⇒ `relabeled` 里能看到 2 次（读数，不拦门）。"""
    st = _ws(tmp_path)
    _put(st, SID, kind="conjecture", label="lem:cancel")
    _put(st, LEMMA, kind="lemma", label="引理 A")
    _verify(st)
    first = SA.apply_abandonment(st, statement_id=SID, reason="理由", at=TS,
                                 abandon_kind="math_error",
                                 abandon_basis="第 5 步直接用了结论", defect_ref=DEFECT)
    assert first["checked"] is True, first
    # 同一个 label 再登记一条（换号），然后它也被放弃
    _put(st, "000003", kind="conjecture", label="lem:cancel")
    second = SA.apply_abandonment(st, statement_id="000003", reason="理由", at=TS,
                                  **DIFF, salvaged=[{"label": "引理 A", "stmt_id": LEMMA}])
    assert second["checked"] is True, second

    read = _abandoned(st)
    relabeled = read["relabeled"]
    assert relabeled["checked"] is True, relabeled
    one = next(x for x in relabeled["labels"] if x["label"] == "lem:cancel")
    assert one["relabels"] == 2, one
    assert one["repeated"] is True, one
    assert [e["stmt_id"] for e in one["events"]] == [SID, "000003"], one
    assert [e["abandon_kind"] for e in one["events"]] == ["math_error", "difficulty"], one
    assert all(e["has_evidence"] for e in one["events"]), one
    assert "lem:cancel" in relabeled["reason"], relabeled
    # 不拦门：收工门那两格读数照旧（`statements_abandoned` 不是 blocker）
    assert read["count"] == 2, read


def test_d_legacy_rows_report_no_evidence_without_blocking(tmp_path):
    """d 的反真空：历史行（自由文本）在 `relabeled` 里 `has_evidence` 为假 —— 但它照样是放弃。"""
    st = _ws(tmp_path)
    _put(st, SID, kind="conjecture", label="lem:cancel")
    with st.tx("statements", actor="test") as tx:
        row = next(dict(r) for r in tx.rows("statements"))
        row["status"] = "abandoned"
        row["quote_reason"] = SA.abandon_marker(at=TS, reason="无干净依据")
        tx.upsert("statements", row)
    read = _abandoned(st)
    one = next(x for x in read["relabeled"]["labels"] if x["label"] == "lem:cancel")
    assert one["relabels"] == 1 and one["repeated"] is False, one
    assert one["events"][0]["has_evidence"] is False, one
    assert one["events"][0]["abandon_kind"] == "", one
    assert read["rows"][0]["structured"] is False, read["rows"][0]


# ---------------------------------------------------------------- e 反真空

def test_e_removing_the_salvaged_check_makes_c_red(tmp_path, monkeypatch):
    """e-①：把 `salvaged` 校验摘掉 ⇒ c（空 salvaged ⇒ 拒）当场变红。

    摘掉的方式是"让判据对空数组放行"（不是改测试）：判据一旦不拦，`abandon_salvaged_missing`
    这条码就再也产生不出来 —— 那正是反真空要证的那件事。
    """
    st = _ws(tmp_path)
    _put(st)
    real = SA.check_abandon_reason

    def lenient(store, **kw):
        got = real(store, **kw)
        if got.get("refused", "").startswith("abandon_salvaged"):
            return {"checked": True, "refused": "", "why": "（探针：摘掉校验）",
                    "abandon_kind": "difficulty", "abandon_basis": "x",
                    "defect_ref": "", "difficulty": "d", "salvaged": [], "detail": {}}
        return got

    monkeypatch.setattr(SA, "check_abandon_reason", lenient)
    got = SA.apply_abandonment(st, statement_id=SID, reason="理由", at=TS,
                               salvaged=[], **DIFF)
    assert got["checked"] is True, (
        "反真空失效：摘掉 salvaged 校验之后仍然拒 ⇒ 这条用例证明不了校验在起作用")
    monkeypatch.undo()
    again = SA.apply_abandonment(st, statement_id=SID, reason="理由", at=TS,
                                 salvaged=[], **DIFF)
    assert again["checked"] is True, "这一行已经被上面那一笔标成 abandoned（幂等）"
    _put(st, "000004", label="再来一条")
    fresh = SA.apply_abandonment(st, statement_id="000004", reason="理由", at=TS,
                                 salvaged=[], **DIFF)
    assert fresh["refused"] == "abandon_salvaged_missing", fresh


def test_e_removing_the_defect_ref_check_makes_b_red(tmp_path, monkeypatch):
    """e-②：把 `defect_ref` 的判据摘掉 ⇒ b（判成立的行不能当 defect_ref）变红。"""
    st = _ws(tmp_path)
    _put(st)
    _verify(st, verdict="成立", fault=False, step=None)
    real = SA._defect_refusal

    def lenient(store, root, ref, basis):
        detail, code, _why = real(store, root, ref, basis)
        return detail, "", ""

    monkeypatch.setattr(SA, "_defect_refusal", lenient)
    got = SA.apply_abandonment(st, statement_id=SID, reason="理由", at=TS,
                               abandon_kind="math_error",
                               abandon_basis="第 5 步错了", defect_ref=DEFECT)
    assert got["checked"] is True, (
        "反真空失效：摘掉 defect_ref 校验之后仍然拒 ⇒ 这条用例证明不了校验在起作用")
    monkeypatch.undo()


# ---------------------------------------------------------------- f 概念行不受这道闸管

def test_f_a_concept_is_not_a_proposition_so_it_is_not_gated(tmp_path):
    """f：`concept` 不是命题（没有"条件 ⇒ 结论"）⇒ 放弃它不该被这道闸拦。

    判据来源：`secretary.NOT_APPLICABLE_KINDS`（`secretary.py:235` =
    ("concept", "definition")）与 `secretary.PROPOSITION_KINDS`（`secretary.py:1367`）
    是同一件事的两半；`schema.Statement.kind` 自己没有词表（`schema.py:2363`）。
    """
    st = _ws(tmp_path)
    _put(st, "000010", kind="concept", label="概念：K 的速降")
    res = _abandon(st, "000010", patch={"status": "abandoned",
                                        "quote_reason": SA.abandon_marker(
                                            at=TS, reason="这个概念不收了")})
    assert res.ok is True, (res.error, res.data)
    row = _row(st, "000010")
    assert row["status"] == "abandoned", row
    assert SA.parse_abandon(row["quote_reason"])["checked"] is True, row
    # 而命题类同一条路仍然拒（正控：闸真的还在）
    _put(st, "000011", kind="conjecture", label="猜想 X")
    refused = _abandon(st, "000011", patch={"status": "abandoned"})
    assert refused.ok is False, refused
    assert dict(refused.meta or {}).get("kind") == "abandon_reason_missing", \
        refused.meta


# ---------------------------------------------------------------- ② 换号读数（不拦）

def test_supersedes_is_reported_but_never_blocks(tmp_path):
    """②：同 label 换号 ⇒ 原件理由齐时带 `supersedes`；不齐时只标 `superseded_without_reason`。

    业主 2026-11-07 的口径：不拦（历史工作区里已有一批没有结构化理由的行，
    拦它们只会把 B 卡死）。
    """
    st = _ws(tmp_path)
    _put(st, LEMMA, kind="lemma", label="引理 A")
    _put(st, SID, kind="conjecture", label="lem:cancel")
    _verify(st)
    assert SA.apply_abandonment(st, statement_id=SID, reason="理由", at=TS,
                                abandon_kind="math_error",
                                abandon_basis="第 5 步直接用了结论",
                                defect_ref=DEFECT)["checked"] is True
    sec = SEC.Secretary("B", root=st.root, store=st)
    got = sec.record_statement({
        "origin": "own_result", "kind": "conjecture", "label": "lem:cancel",
        "statement_full": "设 g 在 [0,1] 上可微，则 g 一致连续。",
        "statement_text": "设 g 在 [0,1] 上可微，则 g 一致连续。",
        "evidence_kind": "heuristic",
        "quote_verified": None, "quote_reason": "夹具：自产命题",
    }, role="B")
    assert got.get("created") is True, got
    supersedes = got.get("supersedes") or []
    assert [one["stmt_id"] for one in supersedes] == [SID], got
    assert supersedes[0]["abandon_kind"] == "math_error", supersedes
    assert supersedes[0]["basis"], supersedes


def test_a_legacy_prior_is_reported_as_superseded_without_reason_and_not_blocked(tmp_path):
    """②的负控：原件没有结构化理由（历史行）⇒ 只标一格，不拒。"""
    st = _ws(tmp_path)
    _put(st, SID, kind="conjecture", label="lem:cancel")
    with st.tx("statements", actor="test") as tx:
        row = next(dict(r) for r in tx.rows("statements"))
        row["status"] = "abandoned"
        row["quote_reason"] = SA.abandon_marker(at=TS, reason="无干净依据")
        tx.upsert("statements", row)
    sec = SEC.Secretary("B", root=st.root, store=st)
    got = sec.record_statement({
        "origin": "own_result", "kind": "conjecture", "label": "lem:cancel",
        "statement_full": "设 h 在 [0,1] 上可微，则 h 有界变差。",
        "statement_text": "设 h 在 [0,1] 上可微，则 h 有界变差。",
        "evidence_kind": "heuristic",
        "quote_verified": None, "quote_reason": "夹具：自产命题",
    }, role="B")
    assert got.get("created") is True, got
    assert got.get("supersedes") in (None, []), got
    legacy = got.get("superseded_without_reason") or []
    assert [one["stmt_id"] for one in legacy] == [SID], got


def test_a_legacy_abandoned_row_is_still_idempotent(tmp_path):
    """幂等重放不受新闸影响：历史行（只有自由文本）仍能被重放（关板项那条路）。"""
    st = _ws(tmp_path)
    _put(st, SID, kind="conjecture", label="lem:cancel")
    with st.tx("statements", actor="test") as tx:
        row = next(dict(r) for r in tx.rows("statements"))
        row["status"] = "abandoned"
        row["quote_reason"] = SA.abandon_marker(at=TS, reason="无干净依据")
        tx.upsert("statements", row)
    got = SA.apply_abandonment(st, statement_id=SID, reason="无干净依据", at=TS)
    assert got["checked"] is True and got["already"] is True, got
    assert got["changes"] == [], got

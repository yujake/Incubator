# -*- coding: utf-8 -*-
"""判据：V 的在册闸认「稿号」，不认「命题号」（业主 2026-11-10 裁定）。

## 这一条堵的是什么（结构洞，两条 lane 各自撞到）

`agent_v/core.py::_registered_manuscript_body` 改前要求「稿名里的号 == statement_id」。
而业主 2026-11-10 的裁定是「稿号与命题号是两个号段」：F 的稿自建号源（六位稿号），
命题号由 B 收录时现取。于是 F 的稿被 B 收录之后，「在册」这一档再也认不出它是
这一条命题的稿 ⇒ 「改了证明再重签」这条生产路结构上不可达（未在册签不受影响）。

现场：`tests/test_d_to_b_carried_road.py` 的端到端判据为此把次序改成"先签再收录"
才跑通 —— 那是夹具绕开，不是修好（次序本身合法，但它不能是唯一走得通的次序）。

## 修法（按业主口径，不是绕）

B 收录那一笔把稿号写进 `statements` 行的 `manuscript_id`（
`register_statement.py::_attach_proofs`）。所以「这一份稿是不是这条命题的稿」改成：

```
稿名里认出的稿号 == 该命题行上记的 manuscript_id
```

行上没有 `manuscript_id`（老盘 / 收录那一笔还没写这一格）⇒ 退回老口径
「号名 == statement_id」，并把退回理由写进读数 `manuscript_identity`
（`fallback=True` + `why`）—— 不许静默退回。

保留不动的三样：正文 sha 与签相符、载体合法（`sign_carrier_reading`）、
「不许借光」（别条命题的签不算 —— 读签那一侧按命题号认凭据）。

## 判据（每条都两向）

| # | 造什么 | 期望 |
|---|---|---|
| a | 在册 + 行上 `manuscript_id=000123`（≠ 命题号 000001）+ 稿 `reports/f-proof-000123.md` | `checked=True`、`manuscript_identity.matched_by="manuscript_id"`、无 `bad_manuscript_name`；稿上签块 `signed`、`statement_id=000001` / `manuscript_id=000123`；`sign_reading.state="signed"` |
| b | 同上，而行上 `manuscript_id=000999`（稿 000123 不是这一条的稿） | `checked=False`、`kind=bad_manuscript_name`、detail 说"不是这一条的稿"；零模型、零台账、零签块 |
| c | 老盘行（没有 `manuscript_id`）+ 稿名里的号 == 命题号 | 仍认（`identity.fallback=True`、`matched_by="statement_id"`、`why` 写退回理由） |
| d | 反真空：把"认稿号"摘掉（只留号名 == statement_id） | a 的同一现场必须红 —— a 的绿来自这一格 |
| e | 端到端「改了证明再重签」：F 落稿（稿号 000123）→ V 未在册签 → B 按稿号收录（行上 `manuscript_id=000123`）→ F 同稿号改写 `## 证明` → V 在册重签 | 新签落下来：签块 sha == 新正文、`sign_reading.state="signed"`、稿名与稿号一个字节没变 |
| f | ③ 的三处之外顺手核出来的第四处：被引命题的稿按它自己的稿号命名（`f-proof-000789.md`），行上 `manuscript_id=000789`；反真空把那一格摘掉 | 有稿号 ⇒ 引用闸读得到（`manuscript_missing=False`、`grade=pre_theorem`、签落下）；摘掉 ⇒ 按命题号拼名找不到、引用闸挡签（这一格的绿来自"先读行上稿号"） |

零模型钱：V 的审阅缝与秘书缝全是预置读数，不联网。
"""
from __future__ import annotations

import contextlib
import json
import pathlib

import pytest

from agentflow import conductor as CND
from agentflow import depsection as DS
from agentflow import manuscriptform as MF
from agentflow import proofregistry as PR
from agentflow import schema as S
from agentflow import verifications as VR
from agentflow import vsigns as VS
from agentflow.agent_b import AgentB
from agentflow.agent_v import AgentV
from agentflow.store import Store

from test_agent_v_exhaustion_review import _v_secretary

CLEAN = json.dumps({"verdict": "成立", "findings": []}, ensure_ascii=False)
FULL = "设 f 在 [0,1] 上连续；则 f 在该区间上一致连续。"
PROOF = "1. 由定义直接得到。\n2. 于是结论成立。"
PROOF_V2 = ("1. 取 delta 使 |x-y|<delta 蕴含 |f(x)-f(y)|<eps。\n"
            "2. 于是结论成立。")

SID = "000001"
MID = "000123"
REL = f"reports/f-proof-{MID}.md"


class _CleanSeam:
    """只记调用次数、永远回 clean 的 V 审阅缝。"""

    def __init__(self) -> None:
        self.prompts: list[str] = []

    def ask(self, prompt: str = "", **_kw):
        from types import SimpleNamespace

        self.prompts.append(prompt)
        return SimpleNamespace(text=CLEAN, problem="")


def _ws(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _manuscript(*, proof: str = PROOF, statement_id: str = SID) -> str:
    """三节齐全的 F 稿（稿头写「还没落号」那一档：F 的稿本来没有命题号）。"""
    return ("# F 的证明手稿：一致连续\n\n"
            f"- 命题号：stmt:{statement_id}\n- 计划：0000\n\n"
            "## 命题\n\n" + FULL + "\n\n## 证明\n\n" + proof + "\n\n"
            + DS.render_dependency_section([]) + "\n")


def _put_row(st: Store, *, sid: str = SID, manuscript_id: str = MID,
             proof: str = PROOF) -> dict:
    """铺一行「B 收录之后」的命题行（`manuscript_id` 就是 B 收录时写的那一格）。"""
    row = {
        "stmt_id": sid, "origin": "own_result", "kind": "theorem",
        "label": "一致连续", "statement_full": FULL, "statement_text": "一致连续",
        "proof_text": proof, "proof_sha256": PR.proof_sha(proof), "proof_no": 1,
        "evidence_kind": "heuristic", "status": "active",
        "quote_verified": None, "quote_reason": "自产命题",
        "created_at": "2026-11-10T00:00:00+08:00", "created_by": "test",
    }
    if manuscript_id:
        row["manuscript_id"] = manuscript_id
    with st.tx("statements", actor="test") as tx:
        tx.upsert("statements", row)
    return row


def _write(st: Store, rel: str, text: str) -> pathlib.Path:
    p = pathlib.Path(st.root) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


@contextlib.contextmanager
def _submitted_by_f(tag: str = "t-v-000001"):
    with CND.calling_as(tag, "V", parent_task_id=f"t-f-{tag[-6:]}",
                        parent_role="F"):
        yield


def _agent(st: Store, seam: _CleanSeam) -> AgentV:
    return AgentV(st, workspace_root=st.root, llm=seam, secretary=_v_secretary(st))


def _side_effects(st: Store, rel: str) -> dict:
    text = (pathlib.Path(st.root) / rel).read_text(encoding="utf-8")
    signs = pathlib.Path(st.root) / VS.SIGNS_DIR
    return {
        "block": bool(VS.manuscript_sign_reading(text, manuscript_path=rel)["signed"]),
        "ledger": len(VR.list_verifications(st.root, statement_id=SID)[0]),
        "sign_files": len(list(signs.glob("*.json"))) if signs.is_dir() else 0,
    }


# ====================================================================== a 正控
def test_a_a_manuscript_with_its_own_id_is_signed_in_register(
        tmp_path: pathlib.Path) -> None:
    """稿号 000123 ≠ 命题号 000001，行上记着 000123 ⇒ 在册重签落下来。

    「第 3 位」在 V 这一侧自 2026-11-08 起不由 V 翻（业主：「V 现在只对手稿负责，
    不该看台账了」）—— 所以这里用两条更硬的独立读数断"签真的落了"：
    `vsigns.sign_reading.state=="signed"`（可复算凭据 + 三票同源）与稿上九格块的
    `signed`。`signed_bit3` 照现行契约恒为 False，单独钉住，免得有人把它读回来。
    """
    st = _ws(tmp_path)
    _put_row(st)
    _write(st, REL, _manuscript())
    seam = _CleanSeam()
    v = _agent(st, seam)
    with _submitted_by_f():
        got = v.verify_proof(SID, proof_manuscript=REL)

    assert got.get("checked") is True, got
    assert str(got.get("kind") or "") != "bad_manuscript_name", got
    identity = dict(got.get("manuscript_identity") or {})
    assert identity.get("matched_by") == "manuscript_id", identity
    assert identity.get("fallback") is False, identity
    assert identity.get("manuscript_id") == MID, identity
    assert identity.get("row_manuscript_id") == MID, identity
    assert len(seam.prompts) == VR.SIGN_STREAK_NEED, len(seam.prompts)
    assert got.get("review_write", {}).get("manuscript_signed") is True, got["review_write"]
    # V 不翻命题位（2026-11-08 口径）；签的落点与凭据在下面两格。
    assert got.get("signed_bit3") is False, got.get("sign_issuance")

    text = (pathlib.Path(st.root) / REL).read_text(encoding="utf-8")
    block = VS.manuscript_sign_reading(text, manuscript_path=REL)
    assert block["signed"] is True, block
    assert block["statement_id"] == SID, block
    assert block["manuscript_id"] == MID, block
    reading = VS.sign_reading(st.root, statement_id=SID, proof_text=PROOF,
                              proof_no=1, store=st)
    assert reading.get("state") == "signed", reading
    assert int(reading.get("votes") or 0) == int(VR.SIGN_STREAK_NEED), reading
    filing = VS.sign_filing_reading(st.root, manuscript_path=REL,
                                    statement_id=SID, store=st)
    assert filing.get("manuscript_signed") is True, filing


# ====================================================================== b 反向：不是这一条的稿
def test_b_a_manuscript_of_another_id_is_refused_before_any_write(
        tmp_path: pathlib.Path) -> None:
    """行上记的是 000999，送来 000123 ⇒ 受控拒，码说"不是这一条的稿"。"""
    st = _ws(tmp_path)
    _put_row(st, manuscript_id="000999")
    _write(st, REL, _manuscript())
    seam = _CleanSeam()
    v = _agent(st, seam)
    with _submitted_by_f():
        got = v.verify_proof(SID, proof_manuscript=REL)

    assert got.get("checked") is False, got
    assert got.get("kind") == "bad_manuscript_name", got
    assert got.get("reason") == "bad_manuscript_name", got
    detail = str(got.get("detail") or "")
    assert "不是这一条命题的稿" in detail, detail
    assert MID in detail and "000999" in detail, detail
    identity = dict(got.get("manuscript_identity") or {})
    assert identity.get("matched_by") == "manuscript_id", identity
    assert identity.get("manuscript_id") == MID, identity
    assert identity.get("row_manuscript_id") == "000999", identity
    assert seam.prompts == [], f"被拒之后还问了 {len(seam.prompts)} 次模型"
    assert _side_effects(st, REL) == {"block": False, "ledger": 0, "sign_files": 0}, (
        _side_effects(st, REL))


# ====================================================================== c 退回口径
def test_c_without_the_row_cell_the_old_statement_id_rule_still_admits(
        tmp_path: pathlib.Path) -> None:
    """老盘行没有 `manuscript_id` + 稿名里的号 == 命题号 ⇒ 仍认，退回理由进读数。"""
    st = _ws(tmp_path)
    _put_row(st, sid="000000", manuscript_id="")
    old_rel = "reports/f-proof-000000.md"
    _write(st, old_rel, _manuscript(statement_id="000000"))
    seam = _CleanSeam()
    v = _agent(st, seam)
    with _submitted_by_f("t-v-000002"):
        got = v.verify_proof("000000", proof_manuscript=old_rel)

    assert got.get("checked") is True, got
    identity = dict(got.get("manuscript_identity") or {})
    assert identity.get("fallback") is True, identity
    assert identity.get("matched_by") == "statement_id", identity
    assert identity.get("row_manuscript_id") == "", identity
    why = str(identity.get("why") or "")
    assert "退回老口径" in why, why
    assert "manuscript_id" in why, why
    assert len(seam.prompts) == VR.SIGN_STREAK_NEED, len(seam.prompts)
    text = (pathlib.Path(st.root) / old_rel).read_text(encoding="utf-8")
    assert VS.manuscript_sign_reading(text, manuscript_path=old_rel)["signed"] is True


# ====================================================================== d 反真空
def test_d_taking_the_manuscript_id_rule_out_turns_a_red(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """反真空：把「认稿号」摘掉（行上稿号读成空）⇒ a 的同一现场必须红。

    打桩点就是这一格的实现（`AgentV._statement_manuscript_reading`）：它一空，
    在册闸只剩老口径「号名 == statement_id」，a 的 000123 稿立刻被拒 —— 证明 a 的绿
    来自"认稿号"这一格，不是来自别的门（载体 / sh a / 载体合法都还开着）。
    """
    monkeypatch.setattr(
        AgentV, "_statement_manuscript_reading",
        lambda self, statement_id: {
            "checked": True, "statement_id": str(statement_id), "found": True,
            "manuscript_id": "",
            "problem": "反真空：把「认稿号」摘掉（假装行上没有 manuscript_id）"})
    st = _ws(tmp_path)
    _put_row(st)
    _write(st, REL, _manuscript())
    seam = _CleanSeam()
    v = _agent(st, seam)
    with _submitted_by_f("t-v-000003"):
        got = v.verify_proof(SID, proof_manuscript=REL)

    assert got.get("checked") is False, (
        "把认稿号摘掉之后 a 的同一现场仍然绿 ⇒ a 量不到这一格：", got)
    assert got.get("kind") == "bad_manuscript_name", got
    identity = dict(got.get("manuscript_identity") or {})
    assert identity.get("fallback") is True, identity
    assert seam.prompts == [], f"被拒之后还问了 {len(seam.prompts)} 次模型"
    assert _side_effects(st, REL) == {"block": False, "ledger": 0, "sign_files": 0}, (
        _side_effects(st, REL))


# ====================================================================== e 改了证明再重签
def _form_gate(**_kw):
    """F 秘书形态闸的离线替身（这条判据量的不是形态闸）。"""
    return {"checked": True, "well_formed": True, "submittable": True,
            "problems": [], "reason": "夹具：形态闸通过"}


def test_e_rewriting_the_proof_and_resigning_in_register_lands_the_new_sign(
        tmp_path: pathlib.Path) -> None:
    """端到端：已收录的稿（稿号 000123）→ 改 `## 证明` → F 同稿号改写 → V 在册重签。

    次序就是真机次序：F 落稿（稿号 000123）→ V 在未在册档签 → B 按稿号收录
    （行上 `manuscript_id=000123`，命题号 000000 由 B 现取）→ F 改写同一份稿
    （`proofregistry.register_or_rewrite`，mode=rewritten、proof_no 2；这就是
    `_hand_proof` 调的那一处）→ V 在册重签。

    改前这一条走不通：在册闸拿 000123 去比命题号 000000 ⇒ `bad_manuscript_name`。
    现在新签落回同一份稿、盖住新正文，稿名与稿号一个字节没变。
    """
    st = _ws(tmp_path)
    # ---- ① F 落稿：登记条目 + 稿号（F 自己的号源；命题号此刻还不存在） ----------
    first = PR.register_or_rewrite(
        st.root, family=MF.FAMILY_F, label="F 攻坚 0000 子目标 s1",
        proposition=FULL, proof_text=PROOF, manuscript_id=MID,
        kind="conjecture", gate=_form_gate)
    assert first.get("ok") is True, first
    assert first.get("mode") == "registered", first
    rel = str(first.get("manuscript_path") or "")
    assert rel == REL, rel

    # ---- ② V 在「还没被 B 收录」这一档把签盖回稿（真三转） ----------------------
    seam = _CleanSeam()
    v = _agent(st, seam)
    with _submitted_by_f("t-v-000004"):
        pre = v.verify_proof("", proof_manuscript=rel)
    assert pre.get("checked") is True, pre
    assert pre.get("kind") == "proof_unregistered_signed", pre
    old_block = VS.manuscript_sign_reading(
        (pathlib.Path(st.root) / rel).read_text(encoding="utf-8"), manuscript_path=rel)
    assert old_block["signed"] is True, old_block

    # ---- ③ B 按稿号收录：行上记 F 的稿号，命题号由 B 现取 ----------------------
    b = AgentB(st, extractor=None, extract_text=None, config={})
    ing = b.ingest_manuscript(manuscript=rel, mode="register",
                              cells=["statement_full", "proof_text", "dependencies"])
    assert ing.get("ok") is True, ing
    row = next(dict(r) for r in st.rows("statements"))
    sid = str(row.get("stmt_id") or "")
    assert sid and sid != MID, (
        "夹具撞名：B 现取的命题号恰好等于 F 的稿号（这一条就量不到两个号段）", row)
    assert str(row.get("manuscript_id") or "") == MID, row

    # ---- ④ F 改写同一份稿：只换 `## 证明`，稿号/稿名不动 ----------------------
    second = PR.register_or_rewrite(
        st.root, family=MF.FAMILY_F, label="F 攻坚 0000 子目标 s1",
        proposition=FULL, proof_text=PROOF_V2, manuscript_id=MID,
        kind="conjecture", gate=_form_gate)
    assert second.get("ok") is True, second
    assert second.get("mode") == "rewritten", second
    assert second.get("manuscript_path") == rel, second
    assert int(second.get("proof_no") or 0) == 2, second
    body_now = DS.proof_body((pathlib.Path(st.root) / rel).read_text(
        encoding="utf-8")).strip("\n")
    assert body_now == PROOF_V2, body_now
    assert second.get("sha256") == PR.proof_sha(PROOF_V2), second

    # ---- ⑤ V 在册重签：认稿号，把新签盖回同一份稿 ----------------------------
    with _submitted_by_f("t-v-000005"):
        got = v.verify_proof(sid, proof_manuscript=rel)
    assert got.get("checked") is True, got
    assert str(got.get("kind") or "") != "bad_manuscript_name", got
    identity = dict(got.get("manuscript_identity") or {})
    assert identity.get("matched_by") == "manuscript_id", identity
    assert identity.get("manuscript_id") == MID, identity
    assert identity.get("statement_id") == sid, identity

    new_block = VS.manuscript_sign_reading(
        (pathlib.Path(st.root) / rel).read_text(encoding="utf-8"), manuscript_path=rel)
    assert new_block["signed"] is True, new_block
    assert new_block["proof_sha256"] == VR.text_sha(PROOF_V2), new_block
    assert new_block["proof_sha256"] != old_block["proof_sha256"], (
        "签块还盖着改写之前那一份正文", new_block, old_block)
    assert new_block["statement_id"] == sid, new_block
    assert new_block["manuscript_id"] == MID, new_block
    reading = VS.sign_reading(st.root, statement_id=sid, proof_text=PROOF_V2,
                              proof_no=1, store=st)
    assert reading.get("state") == "signed", reading
    # 稿名与稿号一个字节没变（改写不换稿）。
    assert pathlib.Path(st.root, rel).is_file()
    assert [p.name for p in (pathlib.Path(st.root) / "reports").glob("f-proof-*.md")] == [
        pathlib.Path(rel).name]

# ====================================================================== f 被引命题的稿
CITED = "000002"
CITED_MID = "000789"
CITED_FULL = "引理乙：每个有限群都有极大子群。"
CITED_PROOF = "1. 取阶最大的真子群即为极大子群。"


def _clean_with_a_citation() -> str:
    """V 的审阅缝：成立 + 对 stmt:000002 给一条 consistent 的引用核实。"""
    return json.dumps({
        "verdict": "成立", "defect_step": None, "why": "", "findings": [],
        "citation_checks": [{"stmt_id": CITED, "verdict": "consistent",
                             "quote_verbatim": False,
                             "note": "由引理乙那一步，用法一致"}]}, ensure_ascii=False)


def _cited_manuscript_with_a_real_sign(st: Store, *, mid: str) -> str:
    """被引命题的稿：按它自己的稿号命名，盖一枚真签（pending 台账 + 九格块）。

    与 `tests/test_d_to_b_carried_road.py::_cited_manuscript_with_a_real_sign` 同一
    口径（那一份按命题号命名；这一份按稿号命名 —— 正是本判据要量的差别）。
    """
    rel = f"reports/f-proof-{mid}.md"
    text = ("# F 的证明手稿（被引命题）\n\n"
            f"- 命题号：stmt:{CITED}\n\n"
            "## 命题\n\n" + CITED_FULL + "\n\n"
            "## 证明\n\n" + CITED_PROOF + "\n\n"
            + DS.render_dependency_section([]) + "\n")
    _write(st, rel, text)
    row = VR.record_pending_sign(
        st.root, proof_text=CITED_PROOF, verdict={"verdict": "成立", "findings": []},
        verifier="agent-V", object_path=rel,
        secretary_judge={"checked": True, "axis": "clean", "decision": "没问题",
                         "reason": "夹具：clean"})
    key = str(row.get("object_sha256") or row.get("proof_sha256") or "")
    anchor = (f"{VR.VERIFICATIONS_DIR}/{VR.PENDING_DIR_NAME}/{key}.jsonl"
              f"#{row.get('verification_id')}")
    wrote = VS.write_manuscript_sign(
        st.root, rel, proof_sha=VR.text_sha(CITED_PROOF),
        streak=int(VR.SIGN_STREAK_NEED), need=int(VR.SIGN_STREAK_NEED),
        verdict="成立", signer="V", at=S.now_iso(), ledger=anchor,
        statement_id=CITED, signed=True)
    assert wrote.get("state") == "written", wrote
    return rel


def _target_manuscript_citing(*, proof: str = "") -> str:
    proof = proof or ("1. 由引理乙直接得到（依据：stmt:000002）。\n"
                      "2. 于是结论成立。")
    deps = ("| 引用（F 的原话） | 命题号（stmt:NNNNNN） | 用在哪一步 | 路径号（第几条证明） |\n"
            "|---|---|---|---|\n"
            f"| 引理乙 | stmt:{CITED} | 1 | 1 |\n")
    return ("# F 的证明手稿：定理甲\n\n"
            f"- 命题号：stmt:{SID}\n\n"
            "## 命题\n\n" + FULL + "\n\n"
            "## 证明\n\n" + proof + "\n\n## 依赖\n\n" + deps)


class _CitationSeam:
    """只答"成立 + 一条 consistent 引用核实"的 V 审阅缝。"""

    def __init__(self) -> None:
        self.prompts: list[str] = []

    def ask(self, prompt: str = "", **_kw):
        from types import SimpleNamespace

        self.prompts.append(prompt)
        return SimpleNamespace(text=_clean_with_a_citation(), problem="")


def test_f_a_cited_manuscript_is_found_by_the_cited_rows_manuscript_id(
        tmp_path: pathlib.Path) -> None:
    """被引命题的稿按它自己的稿号命名时，引用闸仍读得到它（V 才签得下去）。

    同一条结构洞的第四处（③ 的三处之外，顺手核出来的）：`_cited_manuscripts` 改前
    只按被引命题号拼名。稿号与命题号是两个号段 ⇒ 被引命题的稿叫
    `reports/f-proof-<它的稿号>.md`，按命题号找不到 ⇒ 引用闸判 `inadmissible`
    ⇒ 正文没问题也签不下去。现在先读被引行上记的 `manuscript_id`。

    两向都在这一条里：行上有稿号 ⇒ 找到（签落下来）；同一个现场把那一格摘掉
    （老盘形态）⇒ 仍按命题号拼名，找不到 ⇒ 引用闸挡签。后者是这一格的反真空：
    它证明前者的绿来自"先读行上稿号"。
    """
    for label, with_mid in (("pos", True), ("vacuum", False)):
        st = _ws(tmp_path / label)
        _put_row(st, sid=CITED, manuscript_id=(CITED_MID if with_mid else ""),
                 proof="")
        _put_row(st)
        _cited_manuscript_with_a_real_sign(st, mid=CITED_MID)
        _write(st, REL, _target_manuscript_citing())
        seam = _CitationSeam()
        v = _agent(st, seam)  # type: ignore[arg-type]
        with _submitted_by_f(f"t-v-00000{6 if with_mid else 7}"):
            got = v.verify_proof(SID, proof_manuscript=REL)
        cited = dict((got.get("citations") or [{}])[0])
        if with_mid:
            assert got.get("checked") is True, got
            assert cited.get("manuscript_missing") is False, cited
            assert cited.get("grade") == "pre_theorem", cited
            assert cited.get("admissible") is True, cited
            assert str(got.get("kind") or "") != "bad_manuscript_name", got
            text = (pathlib.Path(st.root) / REL).read_text(encoding="utf-8")
            assert VS.manuscript_sign_reading(text, manuscript_path=REL)["signed"] is True
        else:
            assert cited.get("manuscript_missing") is True, cited
            assert cited.get("admissible") is False, cited
            # 审阅照跑完（checked=True），但引用闸挡下这一签：issue/issued 都是假，
            # 稿上也没有块 —— 这才是"这一格在挡签"的读数（不是"没查成"）。
            assert dict(got.get("sign_issuance") or {}).get("issue") is False, got
            assert dict(got.get("sign_issuance") or {}).get("issued") is False, got
            text = (pathlib.Path(st.root) / REL).read_text(encoding="utf-8")
            assert VS.manuscript_sign_reading(text, manuscript_path=REL)["signed"] is False

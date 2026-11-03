# -*- coding: utf-8 -*-
"""颁发与落签拆成两步：`issue()` 与 `land()`（业主 2026-11-02）。

## 口径（逐字）

```text
V 只颁发：`out/vsigns/<sha>.json` 由颁发工具自动写（合规）；手稿块与台账位由收方秘书落。
```

- `issue()` = 颁发：写 `<sha>.json`（证据）+ `issued.json`（派生归档）+ 信封（写给收方秘书）；
- `land()` = 落签：盖手稿块（第 9 格 = 裸稿号）+ 落台账位（`bits.evidence.reviewed_by_proof`）；
- `by=` 必填，且只认 `secretary:<F|B>`：别的值 ⇒ 受控拒绝 `not_a_secretary`、零字节；
- 签文件里的 `written_by` 从笼统的 `"secretary"` 改成 `"secretary:F"` / `"secretary:B"`。

## 为什么要拆

"颁发"是 V 的动作，"落"是收方的动作。合在一个函数里，V 的调用就等于自己把签盖进
别人的稿、翻别人的位 —— 而"自己给自己签"正是这一层要结构上排除的那件事
（业主：「防止F自己给自己签」）。

## 判据

| # | 造什么 | 期望 |
|---|---|---|
| a | `issue(by="secretary:F")` | 两份文件都在；`envelope.to == secretary:F`；`written_by` 是它；稿一个字节没动 |
| b | `land(by="secretary:F")` | 块盖进稿（9 格）、`manuscript_write.state=written`；台账位翻真 |
| c | `land(by="agent-F")` | `not_a_secretary`、零字节（块没有、签文件逐字节不变、位不动） |
| d | 信封写给 F，却由 `secretary:B` 来落 | `addressed_to_another_secretary`，零字节 |
| e | `issue(by="agent-F")` | `not_a_secretary`、零字节（`out/vsigns/` 都不建） |
| f | 稿的正文 != 被签的那一份 | `body_mismatch`：不盖块、不翻位、签文件不动 |
| g | 反真空：被拒之后再按规矩落 | 落成（两次拒绝不是"什么都拒"） |
"""
from __future__ import annotations

import json
import pathlib

from agentflow import conductor as CND
from agentflow import evidencebits as EB
from agentflow import secretary as SEC
from agentflow import verifications as VR
from agentflow import vsigns as VS
from agentflow.store import Store

PROOF = ("1. 取 δ=ε：对任意 x,y∈[0,1]，|x-y|<δ ⇒ |f(x)-f(y)|<ε。\n"
         "2. 第 1 步的 δ 只依赖 ε、不依赖点 ⇒ 按定义即一致连续。")
SHA = VR.proof_sha(PROOF)
REL = "reports/f-proof-000000.md"
SID = "000000"
FULL = "设 f 在 [0,1] 上连续；则 f 在该区间上一致连续。"
MANUSCRIPT = ("# F 的证明手稿：一致连续\n\n"
              "- 命题号：stmt:000000\n"
              "- 计划：0000 · 子目标：s1\n\n"
              "## 命题\n\n"
              f"{FULL}\n\n"
              "## 证明\n\n"
              f"{PROOF}\n\n"
              "## 依赖\n\n"
              "（这一份证明没有引用任何在册命题 —— 空表就是声明。）\n")
TS = "2026-11-02T16:43:01+08:00"


def _ws(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    path = pathlib.Path(st.root) / REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(MANUSCRIPT, encoding="utf-8")
    with st.tx("statements", actor="test") as tx:
        tx.upsert("statements", {
            "stmt_id": SID, "origin": "own_result", "kind": "theorem",
            "label": "一致连续", "statement_full": FULL,
            "statement_text": "一致连续", "proof_text": PROOF,
            "evidence_kind": "heuristic", "status": "active",
            "quote_verified": None, "quote_reason": "自产命题",
            "created_at": TS, "created_by": "test",
            "bits": EB.bits_of(proof=True, proof_process=PROOF, kind="theorem"),
        })
    return st


def _issue(st: Store, *, by: str = "secretary:F") -> dict:
    return VS.issue(
        st.root, artifact_sha=SHA, streak=3, need=3, artifact_path=REL,
        ledger=f"verifications/{SID}.jsonl#v-000010", statement_id=SID,
        proof_no=1, at=TS, by=by)


def _land(st: Store, *, by: str = "secretary:F") -> dict:
    return VS.land(
        st.root, artifact_sha=SHA, by=by, manuscript_path=REL, store=st,
        statement_id=SID, proof_no=1)


def _row(st: Store) -> dict:
    return dict(st.rows("statements")[0])


def _sign_doc(st: Store) -> dict:
    return json.loads(VS.sign_path(st.root, SHA).read_text(encoding="utf-8"))


def _bits(st: Store) -> dict:
    return dict(_row(st).get("bits") or {})


# ====================================================================== a 颁发
def test_a_issue_writes_the_sign_and_the_envelope_only(tmp_path: pathlib.Path) -> None:
    """`issue()` 只写签与归档 + 信封：稿一个字节不动。"""
    st = _ws(tmp_path)
    before = (pathlib.Path(st.root) / REL).read_bytes()

    got = _issue(st)
    assert got["written"] is True, got
    assert VS.sign_path(st.root, SHA).is_file(), got
    assert VS.index_path(st.root).is_file(), "归档没有写"
    doc = _sign_doc(st)
    assert doc["written_by"] == "secretary:F", doc["written_by"]
    assert doc["envelope"]["to"] == "secretary:F", doc.get("envelope")
    assert got["envelope"]["to"] == "secretary:F", got.get("envelope")
    assert VS.SIGN_MARK not in (pathlib.Path(st.root) / REL).read_text(encoding="utf-8")
    assert (pathlib.Path(st.root) / REL).read_bytes() == before, "颁发把稿写动了"


# ====================================================================== b 落签
def test_b_land_stamps_the_block_and_flips_the_ledger_bit(tmp_path: pathlib.Path) -> None:
    """`land()` = 手稿块 + 台账位；`manuscript_write` 落进签文件。"""
    st = _ws(tmp_path)
    assert _issue(st)["written"] is True
    assert _bits(st).get("reviewed") is False

    got = _land(st)
    assert got["landed"] is True, got
    assert got["manuscript_write"]["state"] == "written", got["manuscript_write"]
    text = (pathlib.Path(st.root) / REL).read_text(encoding="utf-8")
    block = VS.manuscript_sign_reading(text, manuscript_path=REL)
    assert block["found"] and block["signed"] is True, block
    assert block["manuscript_id"] == "000000", block
    assert block["identity_state"] == "resolved", block
    doc = _sign_doc(st)
    assert doc["manuscript_write"]["state"] == "written", doc.get("manuscript_write")
    assert doc["written_by"] == "secretary:F", doc["written_by"]
    bits = _bits(st)
    assert bits.get("reviewed") is True, bits
    ev = dict(bits.get("evidence") or {})
    assert (ev.get("reviewed_by_proof") or {}).get("1") is True, ev
    assert (ev.get("reviewed_sha_by_proof") or {}).get("1") == SHA, ev


# ====================================================================== c 非秘书
def test_c_a_non_secretary_cannot_land_and_writes_zero_bytes(tmp_path: pathlib.Path) -> None:
    """`land(by="agent-F")` ⇒ `not_a_secretary`、零字节（块没有、签文件不变、位不动）。"""
    st = _ws(tmp_path)
    assert _issue(st)["written"] is True
    sign_before = VS.sign_path(st.root, SHA).read_bytes()
    text_before = (pathlib.Path(st.root) / REL).read_bytes()

    got = _land(st, by="agent-F")
    assert got["landed"] is False, got
    assert got["code"] == "not_a_secretary", got
    assert got["by"] == "agent-F", got
    assert VS.SIGN_MARK not in (pathlib.Path(st.root) / REL).read_text(encoding="utf-8")
    assert (pathlib.Path(st.root) / REL).read_bytes() == text_before, "被拒的落签写动了稿"
    assert VS.sign_path(st.root, SHA).read_bytes() == sign_before, "被拒的落签写动了签文件"
    assert _bits(st).get("reviewed") is False, "被拒的落签翻了台账位"
    # 空值与它同档（不许把"没给 by"折成"随便谁都能落"）。
    empty = _land(st, by="")
    assert empty["code"] == "not_a_secretary", empty


# ====================================================================== d 信封
def test_d_the_envelope_names_who_may_land(tmp_path: pathlib.Path) -> None:
    """信封写给 `secretary:F`，`secretary:B` 来落 ⇒ `addressed_to_another_secretary`，零字节。"""
    st = _ws(tmp_path)
    assert _issue(st, by="secretary:F")["written"] is True
    text_before = (pathlib.Path(st.root) / REL).read_bytes()
    got = _land(st, by="secretary:B")
    assert got["landed"] is False, got
    assert got["code"] == "addressed_to_another_secretary", got
    assert (pathlib.Path(st.root) / REL).read_bytes() == text_before


# ====================================================================== e 颁发也要秘书
def test_e_issue_also_refuses_a_non_secretary(tmp_path: pathlib.Path) -> None:
    """`issue(by="agent-F")` ⇒ `not_a_secretary`、零字节（连 `out/vsigns/` 都不建）。"""
    st = _ws(tmp_path)
    got = _issue(st, by="agent-F")
    assert got["written"] is False, got
    assert got["code"] == "not_a_secretary", got
    assert not VS.signs_dir(st.root).exists(), "被拒的颁发建了签目录"
    # `secretary:V` 也不行：V 不是收方秘书（它是颁发方）。
    bad = _issue(st, by="secretary:V")
    assert bad["code"] == "not_a_secretary", bad
    assert not VS.signs_dir(st.root).exists()


# ====================================================================== f body
def test_f_land_refuses_a_manuscript_that_is_not_the_signed_one(tmp_path: pathlib.Path) -> None:
    """稿的「## 证明」不是被签的那一份 ⇒ `body_mismatch`：不盖块、不翻位、签文件不动。"""
    st = _ws(tmp_path)
    assert _issue(st)["written"] is True
    sign_before = VS.sign_path(st.root, SHA).read_bytes()
    path = pathlib.Path(st.root) / REL
    path.write_text(MANUSCRIPT.replace("取 δ=ε", "取 δ=2ε"), encoding="utf-8")
    edited = path.read_bytes()

    got = _land(st)
    assert got["landed"] is False and got["code"] == "body_mismatch", got
    assert got["body_mismatch"] is True, got
    assert path.read_bytes() == edited, "被拒的落签把稿写动了"
    assert VS.sign_path(st.root, SHA).read_bytes() == sign_before, "被拒的落签写动了签文件"
    assert _bits(st).get("reviewed") is False, "被拒的落签翻了台账位"


# ====================================================================== g 反真空
def test_g_a_refusal_does_not_poison_the_legitimate_landing(tmp_path: pathlib.Path) -> None:
    """先被拒两次（非秘书 + 信封错人），再按规矩落 ⇒ 落成。"""
    st = _ws(tmp_path)
    assert _issue(st)["written"] is True
    assert _land(st, by="agent-F")["code"] == "not_a_secretary"
    assert _land(st, by="secretary:B")["code"] == "addressed_to_another_secretary"
    ok = _land(st, by="secretary:F")
    assert ok["landed"] is True, ok
    assert VS.manuscript_sign_reading(
        (pathlib.Path(st.root) / REL).read_text(encoding="utf-8"),
        manuscript_path=REL)["signed"] is True


# ====================================================================== h 直调那档
def test_h_the_direct_path_issues_but_cannot_land_by_itself(tmp_path: pathlib.Path) -> None:
    """`issue(by="")`（直调/夹具）记 `sign_statement(direct)`，且它自己不落块。"""
    st = _ws(tmp_path)
    got = _issue(st, by="")
    assert got["written"] is True, got
    doc = _sign_doc(st)
    assert doc["written_by"] == VS.WRITTEN_BY_DIRECT, doc["written_by"]
    assert doc.get("envelope", {}).get("to") == "", doc.get("envelope")
    assert VS.SIGN_MARK not in (pathlib.Path(st.root) / REL).read_text(encoding="utf-8")
    assert _bits(st).get("reviewed") is False


# ====================================================================== i 秘书落未在册
def _unregistered_issue(st: Store) -> dict:
    """未在册那一档的签：没有命题号，落点只有手稿（`statement_id=""`）。"""
    return VS.issue(
        st.root, artifact_sha=SHA, streak=3, need=3, artifact_path=REL,
        ledger=f"{REL}#V签", statement_id="", proof_no=1, at=TS,
        by="secretary:F")


def test_i_the_secretary_lands_an_unregistered_envelope(tmp_path: pathlib.Path) -> None:
    """`Secretary.land_unregistered_sign()` = 未在册那一签的落签口（块落、台账位不翻）。

    V 只把 `issue()` 的返回交过来；落点由秘书判：块落签文件里的 `artifact_path`，
    没有命题行 ⇒ `ledger_bit=False`（不造一格）。
    """
    st = _ws(tmp_path)
    issued = _unregistered_issue(st)
    assert issued["written"] is True, issued
    sec = SEC.Secretary("V", root=st.root, store=st)
    with CND.calling_as("t-v-000001", "V", parent_task_id="t-f-000001",
                        parent_role="F"):
        got = sec.land_unregistered_sign(issued)

    assert got["landed"] is True, got
    assert got["by"] == "secretary:F", got
    assert got["artifact_sha"] == SHA, got
    assert got["ledger_bit"] == "not_attempted", got
    text = (pathlib.Path(st.root) / REL).read_text(encoding="utf-8")
    block = VS.manuscript_sign_reading(text, manuscript_path=REL)
    assert block["found"] and block["signed"] is True, block
    assert block["signer"] == "secretary:F", block
    # 未在册没有命题行可翻：位仍是 false（不许在秘书这一侧造一格）。
    assert _bits(st).get("reviewed") is False, _bits(st)


# ====================================================================== j 非收方
def test_j_the_secretary_method_still_refuses_a_non_recipient(tmp_path: pathlib.Path) -> None:
    """没有收方身份（V 的 parent 读不到）⇒ `not_a_secretary`、零字节（校验没被绕过）。"""
    st = _ws(tmp_path)
    issued = _unregistered_issue(st)
    assert issued["written"] is True, issued
    text_before = (pathlib.Path(st.root) / REL).read_bytes()
    sec = SEC.Secretary("V", root=st.root, store=st)
    got = sec.land_unregistered_sign(issued)  # 没有 calling_as ⇒ 没有收方

    assert got["landed"] is False, got
    assert got["code"] == VS.NOT_A_SECRETARY, got
    assert (pathlib.Path(st.root) / REL).read_bytes() == text_before, "被拒的落签写动了稿"


# ====================================================================== k 旧签的信封
def test_k_an_old_sign_without_an_envelope_still_lands(tmp_path: pathlib.Path) -> None:
    """2026-11-02 之前的签没有 `envelope` 那一格 ⇒ 不凭这一点收紧（与 `land` 同一判据）。"""
    st = _ws(tmp_path)
    issued = _unregistered_issue(st)
    path = VS.sign_path(st.root, SHA)
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc.pop("envelope", None)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    sec = SEC.Secretary("V", root=st.root, store=st)
    with CND.calling_as("t-v-000001", "V", parent_task_id="t-f-000001",
                        parent_role="F"):
        got = sec.land_unregistered_sign({**issued, "sign": doc})

    assert got["landed"] is True, got
    assert got["envelope_to"] == "", got
    assert VS.manuscript_sign_reading(
        (pathlib.Path(st.root) / REL).read_text(encoding="utf-8"),
        manuscript_path=REL)["signed"] is True

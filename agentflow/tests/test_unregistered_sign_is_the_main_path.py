# -*- coding: utf-8 -*-
"""「无号先签」是正统主路 —— 判据 a–f（业主 2026-11-05 晚）。

业主逐字（这一批的总口径）：

    「V 就不能假定有号，全签在稿上，B 侧录入时从稿拿签。这是已有口径」

真机 `projects/R-mk-infinite-90/reports` 上五块签的读数把"真假"钉在两件事上：

| 稿 | 签块里的台账 | 判定 |
|---|---|---|
| `f-proof-000013.md` | `verifications/000013.jsonl#v-000009` | 真签 |
| `f-proof-000017.md` | `verifications/000017.jsonl#v-000006` | 真签 |
| `f-proof-000019.md` | `verifications/000019.jsonl#v-000007`、`命题号=未在册` | 真签（没号是正常形态） |
| `b-proof-000016.md` | `reports/b-proof-000016.md#V签` | 假签（自引、没有那份台账） |
| `f-proof-plan-000011.md` | `reports/f-proof-plan-000011.md#V签`、载体是计划稿 | 假签 |

## 判据（先红后绿 + 反真空）

| # | 造什么 | 期望 | 改前 |
|---|---|---|---|
| a | 未在册命题 + 正式手稿 + 三转干净 | 写出 `verifications/pending/<正文sha>.jsonl`，三转三行、行行三票齐全；签落稿上 | 红（`statement_id_missing` 挡死，盘上零文件） |
| b | 有号命题 | 仍写 `verifications/<号>.jsonl#v-*`（老路不变） | 绿 |
| c1 | 自引台账（`b-proof-000016` 的形状） | B 认签拒：`sign_without_ledger` | 红（改前 `applied=True`） |
| c2 | 三票有空（`passes` 少一格） | 颁发拒：`passes_incomplete` | 绿 |
| c3 | 计划稿载体（`f-proof-plan-000011` 的形状） | 认签拒 + 颁发拒（不是签的载体） | 红（改前身份 `resolved`） |
| d | 登记出号后按 sha 认领 | 认领成功；`proof_review_gap` 认 pending 那一行 ⇒ `evidence_kind` 到 `proof_review` | 绿 |
| d2 | sha 不一致 | 认领失败（受控拒，不是"没有签"） | 绿 |
| e | 再认一次 | 幂等（同一号）/ `bound_elsewhere`（别的号），盘上不出现第二份 | 绿 |
| f | 反真空：把 pending 写口关掉 | a 红（V 报 `ledger_unwritable`、稿上无签块） | —— |

零模型调用（a / f 用预置回复的三转缝）；不读写 `projects/`。
"""
from __future__ import annotations

import json
import pathlib

import pytest
from agentflow import conductor as CND
from agentflow import depsection as _DS
from agentflow import evidencebits as EB
from agentflow import schema as S
from agentflow import secretary as SEC
from agentflow import verifications as VR
from agentflow import vsigns as VS
from agentflow.agent_v import AgentV
from agentflow.store import Store

from conftest import seed_statement_row
from test_v_reviews_three_times_before_signing import CLEAN_REPLY, _ReviewSeam, _Seam, _axis

FULL = "设 f 在 [0,1] 上连续；则 f 在该区间上一致连续。"
MANUSCRIPT = ("# F 的证明手稿：一致连续\n\n"
              "- 命题号：stmt:（还没落号）\n"
              "- 计划：0000 · 子目标：s1\n\n"
              "## 命题\n\n"
              f"{FULL}\n\n"
              "## 证明\n\n"
              "1. 取 δ=ε：对任意 x,y∈[0,1]，|x-y|<δ ⇒ |f(x)-f(y)|<ε。\n"
              "2. 第 1 步的 δ 只依赖 ε、不依赖点 ⇒ 按定义即一致连续。\n\n"
              + _DS.render_dependency_section([]))
PROOF = _DS.proof_body(MANUSCRIPT).strip("\n")
SHA = VR.text_sha(PROOF)
REL = "reports/f-proof-000000.md"
SID = "000000"
OK = {"verdict": "成立", "findings": []}
PASSES = [{"verification_id": f"v-{i:06d}", "at": f"2026-11-05T00:00:0{i}+08:00",
           "proof_sha256": SHA, "why": "这一转判「成立」"} for i in (1, 2, 3)]


def _ws(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _clean_secretary(st: Store):
    """V 的秘书（p247：轴由秘书给；这一支量的是未在册签的落地）。"""
    seam = _Seam({"v_reply_defect": [_axis(SEC.V_REPLY_CLEAN)],
                  "sign_issuance": [_axis(SEC.SIGN_ISSUE)]})
    return SEC.Secretary("V", root=st.root, store=st, seam=seam, enable_model=True)


def _put(st: Store, rel: str, text: str) -> pathlib.Path:
    path = pathlib.Path(st.root) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _pending_rows(st: Store) -> list[dict]:
    base = pathlib.Path(st.root) / "verifications" / "pending"
    if not base.is_dir():
        return []
    return [json.loads(ln) for p in sorted(base.glob("*.jsonl"))
            for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]


def _pending_ref(row: dict) -> str:
    key = str(row.get("object_sha256") or row.get("proof_sha256") or "")
    return f"verifications/pending/{key}.jsonl#{row.get('verification_id')}"


def _claim(st: Store, *, proof: str = PROOF, statement_id: str = "") -> tuple[dict, dict]:
    """B 那样"从稿拿签"：没有稿正文这一格时按正文 sha 去 pending 认领。"""
    bits = EB.bits_of(origin="own_result", proof=True, proof_process=proof)
    return VS.bits_after_sign(bits, root=st.root, proof_text=proof,
                              statement_id=statement_id, store=None)


def _block(ledger: str, *, sid: str = "", mid: str = "000000") -> str:
    return VS.render_manuscript_sign(
        proof_sha=SHA, streak=3, need=3, verdict="成立", signer="secretary:B",
        at="2026-11-05T00:00:00+08:00", ledger=ledger, statement_id=sid,
        manuscript_id=mid)


# ============================================================ a 正统路打开
def test_a_unregistered_manuscript_lands_a_pending_ledger_with_three_tickets(tmp_path):
    """a：未在册 + 正式手稿 + 三转干净 ⇒ `pending/<正文sha>.jsonl` 三行、三票齐全。

    改前这一条是红的：`vsigns.sign_object_gate` 的 `statement_id_missing` 挡在
    `issue` 前面，盘上零文件（`temp/pending-mainpath-20261105/before.txt` ①）。
    """
    st = _ws(tmp_path)
    _put(st, REL, MANUSCRIPT)
    seam = _ReviewSeam([CLEAN_REPLY])
    v = AgentV(st, workspace_root=st.root, llm=seam, secretary=_clean_secretary(st))
    with CND.calling_as("t-v-000001", "V", parent_task_id="t-f-000001", parent_role="F"):
        got = v.verify_proof(proof_manuscript=REL)

    assert got.get("kind") == "proof_unregistered_signed", got
    assert got.get("verdict") == "成立", got

    rows = _pending_rows(st)
    assert len(rows) == int(VR.SIGN_STREAK_NEED), rows
    for row in rows:
        for key in ("verification_id", "at", "proof_sha256"):
            assert str(row.get(key) or "").strip(), (key, row)
        assert row["proof_sha256"] == SHA, row
    # 文件按正文 sha 命名（`verifications.pending_ledger_path` 的口径）。
    pending_file = (pathlib.Path(st.root) / "verifications" / "pending"
                    / f"{SHA}.jsonl")
    assert pending_file.is_file(), sorted(
        p.name for p in (pathlib.Path(st.root) / "verifications" / "pending").glob("*.jsonl"))

    # 签落稿上：命题号=未在册 是合法形态。
    block = VS.manuscript_sign_reading(
        (pathlib.Path(st.root) / REL).read_text(encoding="utf-8"), manuscript_path=REL)
    assert block["signed"] is True and block["statement_id"] == "", block
    assert block["ledger"] == _pending_ref(rows[-1]), block

    # 签文件的三票就是那三行，台账指 pending（不是稿自己）。
    doc = json.loads(VS.sign_path(st.root, SHA).read_text(encoding="utf-8"))
    assert [p["verification_id"] for p in doc["passes"]] == [
        r["verification_id"] for r in rows], doc["passes"]
    assert doc["ledger"] == _pending_ref(rows[-1]), doc


# ============================================================ b 有号那一档不变
def test_b_a_registered_statement_still_signs_into_its_own_ledger(tmp_path):
    """b：有号命题 ⇒ 仍写 `verifications/<号>.jsonl#v-*`；pending 台账一份都不许有。"""
    st = _ws(tmp_path)
    sid = str(seed_statement_row(
        st, proof_text=PROOF, statement_full=FULL, statement_text="一致连续",
        kind="theorem", label="uniform-continuity", origin="own_result",
        evidence_kind="heuristic", bits={})["stmt_id"])
    rel = f"reports/f-proof-{sid}.md"
    _put(st, rel, MANUSCRIPT.replace("- 命题号：stmt:（还没落号）", f"- 命题号：stmt:{sid}"))
    for _ in range(int(VR.SIGN_STREAK_NEED)):
        VR.record_verification(str(st.root), statement_id=sid, proof_text=PROOF,
                               verdict=dict(OK), verifier="agent-V", store=st,
                               proof_no=1, manuscript=rel, secretary_judge={"checked": True, "axis": "clean", "decision": "没问题", "reason": "夹具：秘书判 clean"})

    rows, problems = VR.list_verifications(st.root, statement_id=sid, limit=None)
    assert not problems, problems
    assert len(rows) == int(VR.SIGN_STREAK_NEED), rows
    assert all(str(r["verification_id"]).startswith("v-") for r in rows), rows
    doc = json.loads(VS.sign_path(st.root, SHA).read_text(encoding="utf-8"))
    assert doc["statement_id"] == sid, doc
    assert doc["ledger"] == f"verifications/{sid}.jsonl#{rows[-1]['verification_id']}", doc
    assert _pending_rows(st) == [], "有号那一档不该往 pending 台账落行"


# ============================================================ c1 自引台账
def test_c1_a_self_referential_ledger_is_a_fake_sign(tmp_path):
    """c1：`b-proof-000016` 的形状（`台账=reports/b-proof-000016.md#V签`）⇒ 认签拒。

    那块签在真机上换到了第 3 位（改前 `bits_after_sign` 只看稿号与正文 sha）；
    业主的口径是：台账指向稿自己、盘上又没有那一份台账 ⇒ 假签。
    """
    st = _ws(tmp_path)
    b_rel = f"reports/b-proof-{SID}.md"
    text = VS.stamp_manuscript_sign(
        MANUSCRIPT, proof_sha=SHA, streak=3, need=3, verdict="成立",
        signer="secretary:B", at="2026-11-05T00:00:00+08:00",
        ledger=f"{b_rel}#V签", statement_id=SID, manuscript_id=SID)
    _put(st, b_rel, text)
    # 形状自检：块真的盖上了、台账那一格逐字是稿头自述。
    assert VS.manuscript_sign_reading(text, manuscript_path=b_rel)["ledger"] == f"{b_rel}#V签"

    bits = EB.bits_of(origin="own_result", proof=True, proof_process=PROOF)
    new, reading = VS.bits_after_sign(bits, root=st.root, proof_text=PROOF,
                                      statement_id="", manuscript_text=text,
                                      manuscript_path=b_rel, store=None)
    assert reading.get("applied") is False, reading
    # 块不是签：唯一的读口读不出这一版有任何凭据。
    assert VS.sign_reading(st.root, statement_id="", proof_text=PROOF)["state"] != "signed"
    assert dict(new).get("reviewed") is not True, new
    # 颁发那一侧同样拒（同一个形状，`issue` 是写签的唯一入口）。
    wrote = VS.issue(st.root, artifact_sha=SHA, streak=3, need=3,
                     artifact_path=b_rel, ledger=f"{b_rel}#V签", statement_id=SID,
                     passes=PASSES, by="secretary:B")
    assert wrote["written"] is False, wrote
    assert wrote["code"] == VS.LEDGER_NOT_VERIFICATION, wrote


# ============================================================ c2 三票有空
def test_c2_passes_with_a_hole_are_not_three_votes(tmp_path):
    """c2：`passes` 里少一格 `at` ⇒ `passes_incomplete`（三票有空/不齐就不算签）。"""
    st = _ws(tmp_path)
    holed = [dict(PASSES[0]), dict(PASSES[1]), dict(PASSES[2], at="")]
    wrote = VS.issue(st.root, artifact_sha=SHA, streak=3, need=3,
                     artifact_path=REL, ledger=f"verifications/{SID}.jsonl#v-000003",
                     statement_id=SID, passes=holed, by="secretary:B")
    assert wrote["written"] is False, wrote
    assert wrote["code"] == VS.PASSES_INCOMPLETE, wrote
    assert "缺 ['at']" in wrote["reason"], wrote["reason"]
    assert not VS.sign_path(st.root, SHA).exists()


# ============================================================ c3 计划稿载体
def test_c3_a_plan_manuscript_carries_no_sign(tmp_path):
    """c3：`f-proof-plan-000011` 的形状（计划稿载体 + 自引）⇒ 认签拒 + 颁发拒。

    计划稿仍是合法的落稿名（`parse_manuscript_name` 照旧认 `plan-000011`），
    只是不是签的载体（业主 2026-11-05）。
    """
    st = _ws(tmp_path)
    plan_rel = f"reports/f-proof-plan-{SID}.md"
    text = VS.stamp_manuscript_sign(
        MANUSCRIPT, proof_sha=SHA, streak=3, need=3, verdict="成立",
        signer="secretary:B", at="2026-11-05T00:00:00+08:00",
        ledger=f"{plan_rel}#V签", statement_id="", manuscript_id=f"plan-{SID}")
    _put(st, plan_rel, text)
    # 落稿名这一半照旧
    assert VS.parse_manuscript_name(plan_rel)["manuscript_id"] == f"plan-{SID}"
    assert VS.is_sign_carrier(plan_rel) is False

    bits = EB.bits_of(origin="own_result", proof=True, proof_process=PROOF)
    _new, reading = VS.bits_after_sign(bits, root=st.root, proof_text=PROOF,
                                       statement_id="", manuscript_text=text,
                                       manuscript_path=plan_rel, store=None)
    assert reading.get("applied") is False, reading
    # 计划稿从来不是签的载体：新读口也读不出签（块只是视图）。
    assert VS.sign_reading(st.root, statement_id="", proof_text=PROOF,
                           manuscript_path=plan_rel)["state"] != "signed"

    wrote = VS.issue(st.root, artifact_sha=SHA, streak=3, need=3,
                     artifact_path=plan_rel, ledger=f"verifications/pending/{SHA}.jsonl#u-000003",
                     statement_id="", passes=PASSES, by="secretary:B")
    assert wrote["written"] is False, wrote
    assert wrote["code"] == VS.MANUSCRIPT_NAME_PLAN, wrote


# ============================================================ d 认领 ⇒ proof_review
def test_d_the_claim_reaches_proof_review(tmp_path):
    """d：登记出号后按正文 sha 认领成功，等级到 `pre_theorem`（历史列反算 `proof_review`）。

    判据本体只有一处：`verifications.proof_review_gap`（写入期闸 / 审计 / 收工门同源）。
    它认 pending 那一行 —— 所以"先签后登记"与"先登记后签"是同一件事。
    """
    st = _ws(tmp_path)
    _put(st, REL, MANUSCRIPT)
    row = VR.record_pending_sign(st.root, proof_text=PROOF,
                                 verdict={"verdict": "成立", "findings": []},
                                 verifier="agent-V", object_path=REL, secretary_judge={"checked": True, "axis": "clean", "decision": "没问题", "reason": "夹具：秘书判 clean"})
    new, reading = _claim(st, statement_id="")     # B 新建那一档：还没有号
    assert reading.get("applied") is True, reading
    assert reading.get("claim"), reading
    assert dict(reading["claim"]).get("ledger") == _pending_ref(row), reading["claim"]
    assert dict(new).get("reviewed") is True, new

    # 登记拿到号之后：那一行的凭据面（`pre_theorem` 的写入口）。
    gap = VR.proof_review_gap(st.root, {"stmt_id": SID, "kind": "conjecture",
                                        "proof_text": PROOF,
                                        "evidence_kind": VR.PROOF_REVIEW_KIND})
    assert gap.get("ok") is True, gap
    assert gap.get("state") == "signed", gap
    assert gap.get("ledger") == _pending_ref(row), gap
    # 按通道重算到 `pre_theorem`（同一份实现：签发 / 收录两边共用）。
    # 等级的现算入参是五元位：认领回来的 `new` 就是这一行的第 3 位。
    recomputed = VR._grade_recomputed_from_signature(
        {"stmt_id": SID, "kind": "conjecture", "proof_text": PROOF,
         "evidence_kind": "heuristic", "bits": dict(new)},
        root=str(st.root))
    reading_now = recomputed.get("reading") or {}
    assert reading_now.get("to") == "pre_theorem", recomputed
    # 历史列只是反算读数（不再由这一格写盘）：`pre_theorem` ⇔ `proof_review`。
    assert reading_now.get("to_kind") == VR.PROOF_REVIEW_KIND, recomputed
    assert EB.kind_from_grade(reading_now.get("to")) == VR.PROOF_REVIEW_KIND, recomputed


# ============================================================ d2 sha 不一致
def test_d2_a_different_body_sha_cannot_claim(tmp_path):
    """d2：正文改一个字 ⇒ 认领失败（不是"没有签"，是"有签但不是这一版"）。"""
    st = _ws(tmp_path)
    _put(st, REL, MANUSCRIPT)
    row = VR.record_pending_sign(st.root, proof_text=PROOF,
                                 verdict={"verdict": "成立", "findings": []},
                                 verifier="agent-V", object_path=REL, secretary_judge={"checked": True, "axis": "clean", "decision": "没问题", "reason": "夹具：秘书判 clean"})
    other = PROOF + "改动一个字。"
    _new, reading = _claim(st, proof=other)
    assert reading.get("applied") is False, reading
    assert reading.get("found") is False, reading
    assert row["proof_sha256"] != VR.text_sha(other)

    # 行在、但锚点写的是另一份正文 ⇒ 背书判据点名 sha 不一致（受控拒）。
    backing = VS.sign_ledger_backing(
        st.root, f"verifications/pending/{VR.text_sha(other)}.jsonl#u-000001",
        proof_sha256=VR.text_sha(other))
    assert backing.get("ok") is False, backing
    assert backing.get("code") == VS.LEDGER_ROW_MISSING, backing

    # 同一份台账、同一行，却拿别的正文来认 ⇒ `ledger_sha_mismatch`。
    wrong = VS.sign_ledger_backing(
        st.root, _pending_ref(row), proof_sha256=VR.text_sha(other))
    assert wrong.get("ok") is False, wrong
    assert wrong.get("code") == VS.LEDGER_SHA_MISMATCH, wrong


# ============================================================ e 只能认领一次
def test_e_a_pending_sign_is_claimed_exactly_once(tmp_path):
    """e：同一份签只认领一次 —— 同一号再来是幂等（`already`），别的号是 `bound_elsewhere`。

    两种结局必须分得清（业主：同一份正文只认领一次；登记不产生第二份签）：
    - 同一号第二次 ⇒ `bound=True, already=True`，一个字节都不写；
    - 另一条命题来认 ⇒ `bound=False, bound_elsewhere=<先认的那个号>`，不覆盖。
    """
    st = _ws(tmp_path)
    _put(st, REL, MANUSCRIPT)
    row = VR.record_pending_sign(st.root, proof_text=PROOF,
                                 verdict={"verdict": "成立", "findings": []},
                                 verifier="agent-V", object_path=REL, secretary_judge={"checked": True, "axis": "clean", "decision": "没问题", "reason": "夹具：秘书判 clean"})
    claim = {"ledger": _pending_ref(row), "verification_id": row["verification_id"],
             "proof_sha256": row["proof_sha256"]}
    first = VS.bind_pending_claim(st.root, claim=claim, statement_id=SID)
    assert first.get("bound") is True and first.get("already") is False, first

    again = VS.bind_pending_claim(st.root, claim=claim, statement_id=SID)
    assert again.get("bound") is True, again
    assert again.get("already") is True, again          # 幂等，不是第二次认领
    assert "一个字节都没写" in str(again.get("why") or ""), again

    other = VS.bind_pending_claim(st.root, claim=claim, statement_id="000001")
    assert other.get("bound") is False, other
    assert other.get("bound_elsewhere") == SID, other

    # 盘上仍只有那一行、仍然只认给第一个号。
    rows = _pending_rows(st)
    assert len(rows) == 1, rows
    assert rows[0]["statement_id"] == SID and rows[0]["stmt_id"] == SID, rows[0]
    # 认领之后再认领（B 侧认签面）：这一签已经认给别人 ⇒ 不再给第 3 位。
    bits = EB.bits_of(origin="own_result", proof=True, proof_process=PROOF)
    _new, reading = VS.bits_after_sign(bits, root=st.root, proof_text=PROOF,
                                       statement_id="", store=None)
    assert reading.get("applied") is False, reading
    assert reading.get("code") == "already_claimed", reading


# ============================================================ f 反真空
def test_f_closing_the_pending_write_port_turns_a_red(tmp_path, monkeypatch):
    """f 反真空：把 pending 写口关掉 ⇒ a 当场红（V 报 `ledger_unwritable`、稿上无签块）。

    这一条量的是"a 的那三票真的来自 pending 台账"：写口一关，签就没有落点，
    V 必须报失败而不是照样盖块（盖了就说明块与三票不是同一件事）。
    """
    st = _ws(tmp_path)
    _put(st, REL, MANUSCRIPT)

    def _closed(*_a, **_kw):
        raise OSError("夹具：pending 写口关掉")

    monkeypatch.setattr(VR, "record_pending_sign", _closed)
    seam = _ReviewSeam([CLEAN_REPLY])
    v = AgentV(st, workspace_root=st.root, llm=seam, secretary=_clean_secretary(st))
    with CND.calling_as("t-v-000001", "V", parent_task_id="t-f-000001", parent_role="F"):
        got = v.verify_proof(proof_manuscript=REL)

    assert got.get("checked") is False, got
    assert got.get("reason") == "ledger_unwritable", got
    assert _pending_rows(st) == [], "写口关掉了却落了 pending 行"
    assert not VS.sign_path(st.root, SHA).exists(), "没有三票却产出了签文件"
    block = VS.manuscript_sign_reading(
        (pathlib.Path(st.root) / REL).read_text(encoding="utf-8"), manuscript_path=REL)
    assert block["found"] is False, block


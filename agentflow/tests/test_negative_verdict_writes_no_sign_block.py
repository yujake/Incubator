# -*- coding: utf-8 -*-
"""负判不是签：V 判「有毛病」不往手稿里写 `- V 签：` 块（甲口径，2026-11-03）。

## 为什么这一组存在

`draft/178` 的边界逐字：

    手稿块 → 父代理的秘书落；台账位 → 父代理的秘书落。
    「V不编辑命题台账的V签，只颁发给送审的父代理，父代理不直接编辑命题台账V签或手稿V签，由秘书落签」
    「V 不写手稿里的签块（`- V 签：` 那一行）」

而 86 真机的 `reports/f-proof-plan-000000.md` 上出现了一块
`已签=false；判词=有毛病；…；签名者=agent-V；命题号=未在册` —— 它是 V 在
`agent_v/core.py::_review_unregistered_prose` 的「判出有毛病」那一支直接写上去的。
负判不是签：写块会把「审过、没过」读成「签过一次（未成功）」，与 178 的
「V 只颁发、块只由收方秘书落」正面冲突。

## 甲（本组钉的口径）

负判「不写块」：
- 在册那一路：只落 `verifications/<命题号>.jsonl` 那一行，并把「未通过」的回执投给
  送审方（`out/vreceipts/outbox.jsonl`）—— 这两件改前就有，这一组只钉「手稿上不出现块」；
- 未在册那一路：没有命题号可落，判词随 `verify_proof` 的返回值给 F（F 把它落进
  `v_sign.state=未通过` 的 history）；不新造 pending 台账（那会是第二个写口）。

为什么不是乙（负判也写块、走秘书 + 第 9 格）：`已签=false` 的块仍然是一行
`- V 签：`，F / B 的读侧与「签过一次但没成」共用同一个落点；而 178 的边界是
「V 不写块」。乙还会把「签名者」从「谁签（V）」改成「谁写（秘书）」，与
`render_manuscript_sign` 的语义和其他读侧冲突。

## 判据（先红后绿）

| # | 造什么 | 期望 |
|---|---|---|
| a1 | 未在册手稿 + 第 2 转判「有毛病」 | 手稿逐字未动（没有 `- V 签：`）；仍返回 `kind=proof_unregistered_rejected`、判词/缺陷步/findings |
| a2 | 在册命题 + V 判「有毛病」（手稿在盘上） | 手稿上没有块；台账恰好 1 行（有毛病）；`signed_bit3=False`；回执 intent 在 outbox |
| b | 反真空：未在册手稿 + 三转全干净 | 签必须颁发（判据不是「永远没有签」）：`kind=proof_unregistered_signed`、`out/vsigns/<sha>.json` 在盘上、pending 三行三票；块由收方秘书落（落块正控在 `test_v_unregistered_manuscript_review.py::test_g`） |
| c | 84 的旧 8 格块 / 85 形状的 9 格块 / 86 的 `已签=false` 块 | 前两者仍读成 `signed`（84 是 `legacy`）；86 那一档读成 `rejected`（不许读成 signed） |

a1 在改前红（块被写上），a2 改前就绿（在册那一路本来就不写块 —— 见
`agent_v/core.py::_review_pass` 的终局分支），b/c 是反真空与读侧兼容的守卫。

2026-11-10（业主裁定）：「F 的稿自己维护一套号源，不依赖命题号和计划号」「计划不拥有
稿件」⇒ 老盘计划名（`f-proof-plan-*`）是只读兼容的签载体，与数字名同等。b 那一档因此
翻成正控（三转干净 ⇒ 块真的出现），c 里 85 / 86 那两块第 9 格读到 `resolved`（计划名
不再被载体判据排除）—— 这两条判据此前还钉着 2026-11-05 的旧口径。
"""
from __future__ import annotations

import contextlib
import json
import pathlib

from agentflow import conductor as CND
from agentflow import depsection as _DS
from agentflow import verifications as VR
from agentflow import vsigns as VS
from agentflow import vreceipts as VRC
from agentflow.agent_v import AgentV
from agentflow.store import Store

from test_v_reviews_three_times_before_signing import (
    CLEAN_REPLY, FULL, PROOF, SID, _put, _ReviewSeam, _ws,
)

REJECT_REPLY = json.dumps({"verdict": "有毛病", "defect_step": 2,
                           "quote": "第 1 步直接取 δ=ε",
                           "why": "对一般连续函数 δ=ε 不成立",
                           "findings": [{"level": "error", "step": 2,
                                         "kind": "无依据的步骤",
                                         "detail": "第 1 步没有给出推导"}]},
                          ensure_ascii=False)

#: 与 `agent_f/manuscript.py::proof_manuscript` 同一个形状（V 只读 `## 证明` 那一节）。
#: `## 依赖` 必须是可解析的四列空表（表头在、0 行）—— 只有一句"空表就是声明"的散文
#: 会被 `_registered_manuscript_body` 读成 `dependency_section_unreadable`（空表也是声明，
#: 但声明要写成表）。渲染走唯一实现，夹具不手抄表头。
MANUSCRIPT = ("# F 的证明手稿：弦长函数\n\n"
              "- 命题号：stmt:（还没落号）\n"
              "- 计划：0000 · 子目标：s1\n\n"
              "## 命题\n\n"
              f"{FULL}\n\n"
              "## 证明\n\n"
              f"{PROOF}\n\n"
              + _DS.render_dependency_section([]))
PROOF_BODY = _DS.proof_body(MANUSCRIPT).strip("\n")
REL = "reports/f-proof-plan-0000.md"


def _manuscript_file(st: Store, rel: str = REL, text: str = MANUSCRIPT) -> pathlib.Path:
    path = pathlib.Path(st.root) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


class _JudgeStub:
    """p247 的秘书替身：轴由秘书给，不再由 V 的判词字面推。

    替身自己的判据是"V 的回复里写没写有毛病" —— 这是替身的语义判定，不是生产代码
    在按字面折档（生产里 `Secretary.judge_v_reply` 读的是模型对回复的语义分析）。
    """

    def judge_v_reply(self, *, reply="", verdict="", defect_step=None, **_kw):
        bad = "有毛病" in str(verdict) or "有毛病" in str(reply)
        return {"checked": True, "axis": "fault" if bad else "clean",
                "decision": "有缺陷要指出" if bad else "没问题",
                "reason": "夹具：秘书语义判定", "basis": ["夹具"],
                "defect_step": (defect_step if isinstance(defect_step, int) else 2)
                if bad else None}

    def wash_v_reply(self, **_kw):
        return {"checked": True, "washed": True, "text": "（夹具：无需洗稿）",
                "findings": [], "dropped": [], "refused": ""}


def _v(st: Store, replies: list[str]) -> tuple[AgentV, _ReviewSeam]:
    seam = _ReviewSeam(list(replies))
    #: p247：每一转的轴由秘书给；不装这一名，第一转就落 `unjudged`（不是负判）。
    return AgentV(st, workspace_root=st.root, llm=seam, secretary=_JudgeStub()), seam


@contextlib.contextmanager
def _submitted_by_f():
    with CND.calling_as("t-v-000001", "V", parent_task_id="t-f-000001",
                        parent_role="F"):
        yield


def _outbox(st: Store) -> list[dict]:
    path = VRC.outbox_path(st.root)
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


# ============================================================ a1 未在册负判
def test_a1_an_unregistered_rejection_writes_no_block(tmp_path):
    """未在册 + 第 2 转判「有毛病」⇒ 稿上一个字节都不写，判词随返回值给 F。"""
    st = _ws(tmp_path)
    path = _manuscript_file(st)
    before = path.read_text(encoding="utf-8")
    v, seam = _v(st, [CLEAN_REPLY, REJECT_REPLY])

    got = v.verify_proof(proof_manuscript=REL)

    assert seam.asked() == 2, f"判出有毛病之后还接着问（{seam.asked()} 次）"
    assert got.get("checked") is True, got
    assert got.get("kind") == "proof_unregistered_rejected", got
    assert got.get("verdict") == "有毛病", got
    assert got.get("defect_step") == 2, got
    assert got.get("findings"), got
    # 判据 a：手稿里没有 `- V 签：` 块，而且整份稿逐字未动。
    after = path.read_text(encoding="utf-8")
    assert after == before, "负判改动了手稿（应一个字节都不写）"
    assert VS.SIGN_MARK not in after, after
    # 甲：负判只落台账（未在册 ⇒ `verifications/pending/<正文sha>.jsonl`）+ 通知。
    assert got.get("verification_id"), got
    assert f"{VR.VERIFICATIONS_DIR}/{VR.PENDING_DIR_NAME}/" in str(got.get("ledger") or ""), got
    rows, bad = VR.pending_rows(st.root)
    assert not bad, bad
    assert len(rows) == 1, rows
    assert rows[0]["verdict"] == "有毛病", rows[0]
    assert rows[0]["defect_step"] == 2, rows[0]
    assert rows[0]["verification_id"] == got.get("verification_id"), (rows[0], got)


# ============================================================ a2 在册负判
def test_a2_a_registered_rejection_lands_the_ledger_row_but_no_block(tmp_path):
    """在册 + V 判「有毛病」⇒ 台账那一行在、回执在、手稿上仍然没有块。"""
    st = _ws(tmp_path)
    _put(st)
    rel = f"reports/f-proof-{SID}.md"
    path = _manuscript_file(st, rel=rel,
                            text=MANUSCRIPT.replace("- 命题号：stmt:（还没落号）\n",
                                                    f"- 命题号：stmt:{SID}\n"))
    before = path.read_text(encoding="utf-8")
    v, seam = _v(st, [REJECT_REPLY])

    # 2026-11-04（业主裁定 甲）：在册命题送审必须带手稿 —— 这份稿就是 a2 要判的
    # "负判不写字"的载体（`rel` 上面已经落好，正文与 PROOF 逐字一致）。
    got = v.verify_proof(SID, proof_text=PROOF, proof_manuscript=rel)

    assert seam.asked() == 1, seam.asked()
    assert got.get("checked") is True, got
    assert got.get("verdict") == "有毛病", got
    assert got.get("kind") != "proof_unregistered_rejected", got
    # 台账那一行（甲：负判只落台账 + 通知）。
    rows, bad = VR.list_verifications(st.root, statement_id=SID, limit=None)
    assert not bad, bad
    assert len(rows) == 1, rows
    assert rows[0]["verdict"] == "有毛病", rows[0]
    assert rows[0]["verification_id"] == got.get("verification_id"), (rows[0], got)
    # 回执意图落盘（送审方读不到时是 undelivered，但"要投"这件事必须有账）。
    intents = _outbox(st)
    assert any(str(x.get("verification_id") or "") == str(got.get("verification_id"))
               for x in intents), intents
    # 不签第 3 位；手稿逐字未动、没有块。
    assert got.get("signed_bit3") is False, got
    assert (got.get("sign_issuance") or {}).get("issued") is False, got.get("sign_issuance")
    after = path.read_text(encoding="utf-8")
    assert after == before, "在册那一路的负判改动了手稿（应一个字节都不写）"
    assert VS.SIGN_MARK not in after, after


# ============================================================ b 反真空（正判出块）
def test_b_three_clean_passes_stamp_the_plan_manuscript(tmp_path):
    """三转全干净 ⇒ 读数成立；计划名（老盘只读兼容）与数字名同等 ⇒ 签落稿上。

    ## 改前钉什么 / 改后钉什么

    改前（业主 2026-11-05）：计划稿是合法落稿名，但不是签的载体 ⇒ 三转照判、
    `kind=proof_reviewed_not_signed`、不写块、不落 pending。

    2026-11-10 业主裁定：「F 的稿自己维护一套号源，不依赖命题号和计划号」「计划不拥有
    稿件」⇒ 老盘计划名是只读兼容的签载体，与数字名同等 ⇒ 这一档不再落到「看过、没签」：
    签真的颁发（签文件一份、pending 三行三票）。块由收方秘书落 —— 这一组的秘书替身
    没有落签面，落块的正控在 `test_v_unregistered_manuscript_review.py::test_g`。
    反向断言：第 8 格仍是「未在册」、盘上零 statements 行、稿名不改。
    """
    st = _ws(tmp_path)
    path = _manuscript_file(st)
    v, seam = _v(st, [CLEAN_REPLY])

    with _submitted_by_f():
        got = v.verify_proof(proof_manuscript=REL)

    assert seam.asked() == 3, seam.asked()
    assert got.get("kind") == "proof_unregistered_signed", got
    assert got.get("verdict") == "成立", got
    # 反真空：签真的颁发了（这一条量的是"干净就该签"，不是"永远没有签"）。
    # 这一组的秘书替身没有落签面（块的正控在
    # `test_v_unregistered_manuscript_review.py::test_g`），所以这里钉的是颁发那一半：
    # 签文件在盘上、pending 三行三票、载体就是这份计划名。
    assert VS.sign_path(st.root, VR.text_sha(PROOF_BODY)).exists(), (
        "三转干净却没有签文件：计划名又被当成「不是签的载体」了")
    rows, bad = VR.pending_rows(st.root)
    assert not bad, bad
    assert len(rows) == int(VR.SIGN_STREAK_NEED), rows
    for row in rows:
        assert row["object_path"] == REL, row
    # 反向：载体合法 ≠ 计划成了命题 / ≠ 改出一份按数字名的稿。
    assert st.rows("statements") == [], st.rows("statements")
    assert not (pathlib.Path(st.root) / "reports" / "f-proof-0000.md").exists(), (
        "签这一趟把计划名转正了（2026-11-10：计划不拥有稿件，稿名不改）")


# ============================================================ c 读侧兼容
def test_c_legacy_and_signed_blocks_keep_reading_as_signed(tmp_path):
    """84 的旧 8 格块仍 `signed` + `legacy`；85 形状的 9 格块仍 `signed` + `resolved`。"""
    st = _ws(tmp_path)
    sha = VR.text_sha(PROOF_BODY)
    # 84 的块形状（2026-11-02 之前写的）：只有 8 格，没有「手稿号」。
    legacy = (f"{VS.SIGN_MARK}已签=true；判词=成立；连续=3/3；正文sha={sha}；"
              "时间=2026-11-02T16:43:01+08:00；签名者=V；"
              "台账=verifications/000000.jsonl#v-000010；命题号=000000")
    legacy_text = MANUSCRIPT.replace("- 计划：0000 · 子目标：s1\n",
                                     "- 计划：0000 · 子目标：s1\n" + legacy + "\n")
    reading = VS.manuscript_sign_reading(legacy_text, manuscript_path=REL)
    assert reading["found"] is True and reading["signed"] is True, reading
    assert reading["identity_state"] == "legacy", reading
    assert VS.manuscript_sign_standing(legacy_text, proof_sha=sha,
                                       manuscript_path=REL)["state"] == "signed"
    # 85 的形状：9 格、手稿号与稿名相同。计划名 2026-11-10 起是合法载体（老盘只读
    # 兼容）⇒ 身份 `resolved`；改前 2026-11-05 的旧口径只到 `unmatched`。
    fresh = VS.stamp_manuscript_sign(
        MANUSCRIPT, proof_sha=sha, streak=3, need=3, verdict="成立", signer="V",
        at="2026-11-02T21:53:55+08:00", ledger="verifications/000004.jsonl#v-000004",
        statement_id="000004", manuscript_id="plan-0000")
    got = VS.manuscript_sign_reading(fresh, manuscript_path=REL)
    assert got["signed"] is True and got["identity_state"] == "resolved", got
    assert "与这一份稿相同" in str(got.get("identity_why") or ""), got
    assert VS.manuscript_sign_standing(fresh, proof_sha=sha,
                                       manuscript_path=REL)["state"] == "signed"


def test_c2_an_unsigned_block_is_not_read_as_signed(tmp_path):
    """86 的形状（`已签=false`）读成 `rejected`，绝不许读成 signed/legacy。"""
    sha = VR.text_sha(PROOF_BODY)
    unsigned = VS.stamp_manuscript_sign(
        MANUSCRIPT, proof_sha=sha, streak=0, need=3, verdict="有毛病", signer="agent-V",
        at="2026-11-03T04:46:31+08:00", ledger=f"{REL}#V签", statement_id="",
        manuscript_id="plan-0000", signed=False)
    reading = VS.manuscript_sign_reading(unsigned, manuscript_path=REL)
    assert reading["found"] is True and reading["signed"] is False, reading
    # 2026-11-10：计划名也是合法载体，第 9 格对得上 ⇒ `resolved`；「未签」是
    # `已签=false` 那一格的事，与身份那一格无关。
    assert reading["identity_state"] == "resolved", reading
    assert reading["verdict"] == "有毛病", reading
    standing = VS.manuscript_sign_standing(unsigned, proof_sha=sha, manuscript_path=REL)
    assert standing["state"] == "rejected", standing

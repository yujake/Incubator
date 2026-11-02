# -*- coding: utf-8 -*-
"""V 对「还没在册」的一份散文手稿的审校入口（业主 2026-11-02）。

## 这一组守什么

业主逐字（2026-11-01，`vsigns.py` 的模块头也引着）：

    「V 签不直接进台账，进手稿，随 B 侧将手稿中的定理或命题收录时读到。」

改前 `verify_proof` 只认在册命题（`statement_id` 必填、不在册 ⇒ `statement_missing`），
散文证明必须先让 B 登记才拿得到签 —— F 的交差因此挂在 B 的动作上。2026-11-02 业主把
入口定成「F 直接派 V」+「签进手稿」：`verify_proof` 多了 `proof_manuscript` 这一条
（不给 `statement_id`），V 读稿审、三转干净就把签块盖回那一份稿。

## 判据（先红后绿）

| # | 造什么 | 期望 |
|---|---|---|
| ① | 未在册手稿 + 三转干净 | 手稿里出现签块（`已签=true；连续=3/3；正文sha=…`），V 返回 checked=True |
| ② | 三转里有一转拿不到合法结论（缺材料） | `checked=False`、一个字节都不写（稿上没有签块） |
| ③ | 同一份正文再送一次 | 不再问模型、不再写（`already`），块仍是一行 |
| ④ | 反真空：把稿上的签块删掉 | F 的读数从「已签」回落到「待签」 |
| ⑤ | 第 2 转判「有毛病」 | 只问 2 次就停；不写块（甲口径，2026-11-03：负判不是签），判词随返回值给 F |

零模型调用：V 的审阅缝交出预置回复并计数（与三连判判据共用同一套替身）。
"""
from __future__ import annotations

import contextlib
import json
import pathlib

import pytest
from agentflow import conductor as CND
from agentflow import depsection as _DS
from agentflow import verifications as VR
from agentflow import vsigns as VS
from agentflow.agent_f import vsign as FVS
from agentflow.agent_v import AgentV
from agentflow.store import Store

from test_v_reviews_three_times_before_signing import CLEAN_REPLY, _ReviewSeam

#: 未在册那一支的判定面是 V 自己的两态结论（没有秘书那一层：pending / 手稿这条血脉
#: 一直只认 `row_signable`，见 `agent_v/core.py::_review_unregistered_prose` 的说明）。
#: 所以这一组用"结论就是有毛病"的回复，而不是"判词写成立、秘书读出缺陷"那一招。
REJECT_REPLY = json.dumps({"verdict": "有毛病", "defect_step": 2,
                           "quote": "第 1 步直接取 δ=ε",
                           "why": "对一般连续函数 δ=ε 不成立",
                           "findings": [{"level": "error", "step": 2,
                                         "kind": "无依据的步骤",
                                         "detail": "第 1 步没有给出推导"}]},
                          ensure_ascii=False)

FULL = "设 f 在 [0,1] 上连续；则 f 在该区间上一致连续。"
#: 与 `agent_f/manuscript.py::proof_manuscript` 同一个形状（V 只读 `## 证明` 那一节）。
MANUSCRIPT = ("# F 的证明手稿：一致连续\n\n"
              "- 命题号：stmt:（还没落号）\n"
              "- 计划：0000 · 子目标：s1\n\n"
              "## 命题\n\n"
              f"{FULL}\n\n"
              "## 证明\n\n"
              "1. 取 δ=ε：对任意 x,y∈[0,1]，|x-y|<δ ⇒ |f(x)-f(y)|<ε。\n"
              "2. 第 1 步的 δ 只依赖 ε、不依赖点 ⇒ 按定义即一致连续。\n\n"
              "## 依赖\n\n"
              "（这一份证明没有引用任何在册命题 —— 空表就是声明。）\n")
#: 被签的那一份正文 = 手稿里「## 证明」那一节（`depsection.proof_body` 的口径）：
#: 签的 sha 按这一段算（`vsigns.ARTIFACT_SHA_RULE`），所以测试也从这里取，不另抄一份。
PROOF = _DS.proof_body(MANUSCRIPT).strip("\n")
REL = "reports/f-proof-plan-0000.md"


def _ws(tmp_path: pathlib.Path, *, text: str = MANUSCRIPT) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    path = pathlib.Path(st.root) / REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return st


def _v(st: Store, replies: list[str]) -> tuple[AgentV, _ReviewSeam]:
    seam = _ReviewSeam(list(replies))
    return AgentV(st, workspace_root=st.root, llm=seam), seam


@contextlib.contextmanager
def _submitted_by_f():
    """V 这一趟是 F 派出来的（2026-11-03 件一：收方 = V 的 parent 那一侧）。"""
    with CND.calling_as("t-v-000001", "V", parent_task_id="t-f-000001",
                        parent_role="F"):
        yield


def _manuscript_text(st: Store) -> str:
    return (pathlib.Path(st.root) / REL).read_text(encoding="utf-8")


# ============================================================ ① 三转干净 ⇒ 签块
def test_a_three_clean_rounds_stamp_a_sign_block_into_the_manuscript(tmp_path):
    """① 未在册手稿 + 三转干净 ⇒ 稿上出现签块；V 不再要求命题号。"""
    st = _ws(tmp_path)
    v, seam = _v(st, [CLEAN_REPLY])
    with _submitted_by_f():
        got = v.verify_proof(proof_manuscript=REL)

    assert seam.asked() == 3, f"只问了 {seam.asked()} 次 ⇒ 不是连判三轮"
    assert got.get("checked") is True, got
    assert got.get("kind") == "proof_unregistered_signed", got
    assert got.get("signed_bit3") is False, "未在册没有第 3 位可翻，这里必须诚实为假"
    block = VS.manuscript_sign_reading(_manuscript_text(st))
    assert block["found"] and block["signed"] is True, block
    assert (block["streak"], block["need"]) == (3, 3), block
    assert block["proof_sha256"] == VR.proof_sha(PROOF), block
    assert block["statement_id"] == "", block
    # F 的读数：已签（渠道 = 手稿签块）。
    reading = FVS.delivery_reading(st.root, proof_text=PROOF, manuscript_paths=(REL,))
    assert reading["state"] == FVS.STATE_SIGNED, reading
    assert reading["channel"] == FVS.CHANNEL_MANUSCRIPT, reading
    # 2026-11-03 件一：块是收方秘书落的（V 只颁发），签名者点名是哪一位秘书。
    assert block["signer"].startswith("secretary:"), block
    assert block["signer"] == "secretary:F", block
    doc = json.loads(VS.sign_path(st.root, VR.proof_sha(PROOF)).read_text(encoding="utf-8"))
    assert doc["written_by"] == "secretary:F", doc["written_by"]
    assert doc["envelope"]["to"] == "secretary:F", doc.get("envelope")


# ============================================================ ② 缺材料 ⇒ 不落
def test_b_no_usable_reply_writes_nothing(tmp_path):
    """② 拿不到合法结论 ⇒ checked=False，稿上不留签块（缺材料不落签）。"""

    class _Broken(_ReviewSeam):
        def ask(self, prompt: str = "", **_kw):
            call = super().ask(prompt, **_kw)
            call.ok = False
            call.text = ""
            call.problem = "fixture: 这一转没拿到回复"
            return call

    st = _ws(tmp_path)
    seam = _Broken([CLEAN_REPLY])
    v = AgentV(st, workspace_root=st.root, llm=seam)
    with _submitted_by_f():
        got = v.verify_proof(proof_manuscript=REL)

    assert got.get("checked") is False, got
    assert "没查成" in str(got.get("detail") or ""), got
    assert VS.manuscript_sign_reading(_manuscript_text(st))["found"] is False, _manuscript_text(st)
    # 读数跟着回落：没签就是待签（不是"已签"）。
    assert FVS.delivery_reading(st.root, proof_text=PROOF,
                                manuscript_paths=(REL,))["state"] == FVS.STATE_WAITING


# ============================================================ ③ 只签一次
def test_c_the_same_body_is_not_signed_twice(tmp_path):
    """③ 同一份正文再送一次 ⇒ 不再问模型、不再写（块仍是一行）。"""
    st = _ws(tmp_path)
    v, seam = _v(st, [CLEAN_REPLY])
    with _submitted_by_f():
        first = v.verify_proof(proof_manuscript=REL)
    assert first.get("checked") is True, first
    asked_once = seam.asked()
    assert asked_once == 3, asked_once
    before = _manuscript_text(st)

    with _submitted_by_f():
        again = v.verify_proof(proof_manuscript=REL)
    assert again.get("checked") is True, again
    assert "不重复" in str(again.get("reason") or ""), again
    assert seam.asked() == asked_once, "第二次送审又问模型了（同一份正文不重复判）"
    assert _manuscript_text(st) == before, "第二次送审又写了一行签块"
    assert _manuscript_text(st).count(VS.SIGN_MARK) == 1, _manuscript_text(st)


# ============================================================ ④ 反真空
def test_d_deleting_the_block_falls_back(tmp_path):
    """④ 反真空：把稿上的签块删掉 ⇒ F 的读数回落成待签。"""
    st = _ws(tmp_path)
    v, _seam = _v(st, [CLEAN_REPLY])
    with _submitted_by_f():
        v.verify_proof(proof_manuscript=REL)
    assert FVS.delivery_reading(st.root, proof_text=PROOF,
                                manuscript_paths=(REL,))["state"] == FVS.STATE_SIGNED

    text = _manuscript_text(st)
    stripped = "\n".join(ln for ln in text.split("\n")
                         if not ln.strip().startswith(VS.SIGN_MARK))
    (pathlib.Path(st.root) / REL).write_text(stripped, encoding="utf-8")
    after = FVS.delivery_reading(st.root, proof_text=PROOF, manuscript_paths=(REL,))
    assert after["state"] == FVS.STATE_WAITING, after
    assert after["delivered"] is False, after


# ============================================================ ④之二 反真空（land）
def test_d2_without_land_the_block_is_absent_and_f_reads_waiting(tmp_path, monkeypatch):
    """反真空（件一 b）：把 `vsigns.land` 摘掉 ⇒ 块不存在、F 的读数回落待签。

    这一条量的是"块真的由 land 写"：V 仍然颁发（签文件在），但没有收方秘书落块
    就不能当作已签。`delivery_reading` 也不许拿未在册的侧文件替块作证。
    """
    st = _ws(tmp_path)
    v, seam = _v(st, [CLEAN_REPLY])
    called = {"n": 0}

    def _refuse(*_a, **_kw):
        called["n"] += 1
        return {"landed": False, "state": "refused", "code": "land_removed",
                "reason": "夹具：把 land 摘掉", "manuscript_write": {},
                "ledger_bit": "not_attempted"}

    monkeypatch.setattr(VS, "land", _refuse)
    with _submitted_by_f():
        got = v.verify_proof(proof_manuscript=REL)

    assert seam.asked() == 3, seam.asked()
    assert called["n"] == 1, called
    assert got.get("checked") is True, got
    assert VS.manuscript_sign_reading(_manuscript_text(st))["found"] is False, _manuscript_text(st)
    after = FVS.delivery_reading(st.root, proof_text=PROOF, manuscript_paths=(REL,))
    assert after["state"] == FVS.STATE_WAITING, after
    assert after["delivered"] is False, after


# ============================================================ ⑤ 有毛病那一转
def test_e_a_fault_on_round_two_stops_and_writes_no_block(tmp_path):
    """第 2 转判「有毛病」⇒ 只问 2 次就停，稿上不写块（甲口径：负判不是签）。

    改前这里写一块 `已签=false；判词=有毛病`（`签名者=agent-V`）—— 那是 V 直接写手稿，
    与 `draft/178` 的「V 不写手稿里的签块、块只由收方秘书落」冲突，也会让读侧把
    「审过、没过」与「签过一次但没成」混在同一个落点。现在判词只随返回值给 F；
    手稿一个字节都不写。
    """
    st = _ws(tmp_path)
    before = _manuscript_text(st)
    v, seam = _v(st, [CLEAN_REPLY, REJECT_REPLY])
    with _submitted_by_f():
        got = v.verify_proof(proof_manuscript=REL)

    assert seam.asked() == 2, f"判出有毛病之后还接着问（{seam.asked()} 次）"
    assert got.get("checked") is True, got
    assert got.get("kind") == "proof_unregistered_rejected", got
    assert got.get("verdict") == "有毛病", got
    assert got.get("defect_step") == 2, got
    assert got.get("findings"), got
    assert _manuscript_text(st) == before, "负判改动了手稿（应一个字节都不写）"
    assert VS.manuscript_sign_reading(_manuscript_text(st))["found"] is False, _manuscript_text(st)
    assert FVS.delivery_reading(st.root, proof_text=PROOF,
                                manuscript_paths=(REL,))["state"] == FVS.STATE_REJECTED


# ============================================================ 入口守卫
def test_f_only_f_proof_manuscripts_are_accepted(tmp_path):
    """入口只认 F 那一份手稿的命名（不按任意路径读盘）。"""
    st = _ws(tmp_path)
    v, seam = _v(st, [CLEAN_REPLY])
    got = v.verify_proof(proof_manuscript="data/statements.json")
    assert got.get("checked") is False, got
    assert got.get("reason") == "bad_manuscript_path", got
    assert seam.asked() == 0, "路径被拒之后还问了模型"



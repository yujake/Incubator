# -*- coding: utf-8 -*-
"""业主 2026-10-29 的「V 签门槛」：连续 3 次没问题 + V 秘书语义判定 + 洗稿转达。

口径逐字（`draft/125` §二 A/B/C → 业主追加四条）：

```text
V 签门槛 = 连续 3 次"没问题" + V 秘书语义判定 + 洗稿转达
追加：① 签字能力转交秘书：V 不再自己发签，V 只产出审稿意见；由 V 的秘书判定并落盘
      （`Secretary.decide_sign_issuance` → 满足"连续 3 次 clean"才调
       `verifications.sign_statement` 翻 `bits.evidence`）。
      ② V 不知道秘书洗稿的存在（提示词与技能手册里不出现洗稿/清洗）。
      ③ 思考默认 High 是已有设计（加判据钉住，不新写一套）。
      ④ temperature：业主 2026-10-29 改口径为「1.0（正常对话的数值）」，只给 V 的
         审阅调用；别的角色仍是 0.2（c6/v10）。
```

## 判据表（每条都带"它能怎么红"）

| 编号 | 它要证明的事 | 它能怎么红 |
|---|---|---|
| a1/v2 | 连续 3 次「成立」且同一份正文才翻位 | 把 `streak_ok` 打成恒真 ⇒ 第 1 次就翻 |
| a2 | 中途一次非成立 ⇒ 归零、不翻位 | 不看 verdict ⇒ 三次里有毛病也翻 |
| a3 | 正文变了（sha 变）⇒ 归零 | 不按 sha 分段 ⇒ 旧稿的两票算到新稿头上 |
| a4/v3 | 第 1、2 次只落台账、不翻位 | 写侧提前翻位 / 台账只落一行 |
| a5 | `signs_bit3` 没有连续读数 ⇒ 不签（fail-closed） | 缺省放行 ⇒ 门被静默绕开 |
| a6 | 发签那一步由秘书调 `sign_statement` 落地 | 退回 V 自己翻位 ⇒ 秘书只在旁边看 |
| a7/v7 | 装配缺失 ⇒ 秘书判定 `checked=False` 且不发签（主路径，不是边角） | 没秘书也翻位 ⇒ 门槛在装配层不存在 |
| a8/v8 | 签只能经秘书：`sign_statement` 的调用者只许是 `_land_sign_issuance`；V 这一路每次落台账都是 `flip=False` | V 自己补一刀 / 落台账顺手翻位 ⇒ 调用者名单里出现 `verify_proof` |
| a9/v8 负控 | 秘书"判了签发但不落盘" ⇒ 位一次都不许翻（V 不许替它落） | V 拿 `issue=True` 自己翻位 ⇒ 三次 clean 之后位就翻上去了 |
| a10/v7 正面 | 工具路径那种构造（只有 store + root）会自己装配秘书；装配给出没缝的秘书 ⇒ `checked=False` 且不发签 | 惰性装配坏了 / 没秘书也签 ⇒ 工具路径上门槛不存在 |
| b1/v1 | 三档不许折平：fault 清零 / clean +1 / unsure 不清零不计入 | 折成一档 ⇒ 先夸后刺被当成 clean |
| b2 | 题面逐字带着三条判定规则 | 题面丢了规则 ⇒ 模型只能猜 |
| b3/v4 | 秘书不看证明：材料里塞 F 正文必须被拒 | 收了但没用 ⇒ 盘上查不出"看过" |
| b4 | 词表外结论不采信（归 unsure，不归 clean） | 采信自由文本 ⇒ 第八种写法进台账 |
| c1/v5 | 洗稿：交付给 F 的 detail ≠ V 原文；findings 逐字可回溯 | 直接转发原文 ⇒ 洗稿等于没做 |
| c2 | 洗不出来 ⇒ 受控拒绝、不输出原文 | 拒绝时顺手回原文 ⇒ 泄露 |
| c3 | C 段交付面：板项 detail 用洗过的文本（kind/expects 不变） | 新增一档 kind ⇒ 命中冻结面 |
| c4 | V 的可见文本不出现洗稿类字眼，且「转达」只留在共用段那两句 | 在冷启动/手册里写「你的意见会被转达/清洗」⇒ 违反口径 ② |
| c8/v9 | V 的可见文本说清「你只产意见、签由秘书」「你看不到审阅之外」，且 draft/122 清单接进来并注明「这是嘱托，不是门」 | 删掉其中任一句 / 清单没接进来 / 没注明它是嘱托 ⇒ 红 |
| c5 | V 的思考强度默认 High（既有设计） | 缺省被改成 low ⇒ 钉不住 |
| c6/v10 | V 的审阅请求体 `temperature==1.0`；别的角色与秘书那一档仍是 0.2 | 摘掉 `AgentV._ask` 里的温度 ⇒ 请求体回到 0.2 |
| c7/S6 | V 的思考强度默认 High 是既有默认（`modelgw.DEFAULT_REASONING_EFFORT` → `ModelSpec` → `spec_for`/`spec_from_env` → 请求体），读数是活的 | 把 `AGENTFLOW_MODEL_REASONING_EFFORT=low` 灌进同一道梯子 ⇒ 读数与请求体不跟着变 = 判据在量常量 |
| z1/z2 | 反真空：把 streak 闸 / judge 摘掉 ⇒ a1 / b1 红 | 判据自己不能红 = 没测到东西 |

全部 tmp 工作区、零真模型调用（V 的审阅与秘书的判断都用离线替身缝）。
"""
from __future__ import annotations

import json
import pathlib
import sys

import pytest

from agentflow import agent_loop as AL
from agentflow import agent_prompts as AP
from agentflow import agent_skills as SK
from agentflow import evidencebits as EB
from agentflow import modelgw as G
from agentflow import secretary as SEC
from agentflow import verifications as VR
from agentflow.agent_v import AgentV
from agentflow.store import Store
from agentflow.tools import build_registry

TS = "2026-10-29T00:00:00+08:00"
SID = "000007"
PROOF = "1. 取 G = C_n（n ≥ 3）：它是 2-正则、围长为 n。\n2. 由第 1 步直接得到结论。"
PROOF_B = PROOF + "\n3. 补上一步（改稿之后才有的那一句）。"
FULL = "设 G 是 3-正则群；则弦长函数不是常值。"
#: V 的回复正文里那一句"独特"的话：洗稿之后不许再出现在递给 F 的 detail 里。
RAW_SENTENCE = "整体很好，只是有一个缺陷需要指出：第 2 步的记号没有定义。"

_OK = {"verdict": "成立", "findings": []}


# ------------------------------------------------------------------ 夹具

def _ws(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _put(store: Store, *, proof: str = PROOF, sid: str = SID) -> dict:
    """落一条在册命题（走真事务；夹具只造这一行）。"""
    row = {
        "stmt_id": sid, "origin": "own_result", "kind": "theorem",
        "label": "弦长函数非常值", "statement_full": FULL,
        "statement_text": "弦长函数不是常值", "proof_text": proof,
        "evidence_kind": "heuristic", "status": "active",
        "quote_verified": None, "quote_reason": "自产命题，没有外部引文要比对",
        "created_at": TS, "created_by": "test",
        "bits": EB.bits_of(proof=True, proof_process=proof, kind="theorem"),
    }
    with store.tx("statements", actor="test") as tx:
        tx.upsert("statements", row)
    return row


def _row(store: Store) -> dict:
    return dict(store.rows("statements")[0])


def _sign(store: Store, *, verdict: dict | None = None, text: str = PROOF,
          judge: dict | None = None) -> dict:
    """一条 V 的审校行（台账 + 连续闸那一半；默认 `flip=True`）。

    这一支是"直调写入口"的夹具（`record_verification` 的兼容门）：它量的是连续闸
    本身（a1–a5）。生产路径那一条（V 只落台账、秘书翻位）在 a6/a7 用 `AgentV` 走真路。
    """
    return VR.record_verification(store.root, statement_id=SID, proof_text=text,
                                  verdict=verdict or _OK, verifier="agent-V",
                                  store=store, proof_no=1, secretary_judge=judge)


_BAD = {"verdict": "有毛病", "defect_step": 2, "why": "第 2 步没有依据",
        "findings": [{"level": "error", "step": 2, "kind": "无依据的步骤",
                      "detail": "第 2 步直接用了结论"}]}


class _Call:
    """`llmseam.SeamCall` 的替身：`judge()` 只读 ok / problem / detail。"""

    ok = True
    problem = ""
    detail = ""
    text = ""
    model = "fake"
    prompt_version = "t"
    prompt_sha256 = "0" * 64


class _Seam:
    """离线替身缝：按 `note`（`secretary:<kind>`）回一份预置 JSON，并记住问过什么。"""

    wired = True

    def __init__(self, answers: dict[str, list] | None = None) -> None:
        self.answers = {k: list(v) for k, v in (answers or {}).items()}
        self.seen: list[tuple[str, str, str]] = []

    def ask_json(self, prompt: str, *, system: str = "", task_id: str = "",
                 note: str = "") -> tuple[dict | None, _Call]:
        self.seen.append((note, prompt, system))
        kind = note.split(":", 1)[-1]
        queue = self.answers.get(kind) or [{}]
        doc = queue.pop(0) if len(queue) > 1 else queue[0]
        return dict(doc), _Call()

    def asked(self, kind: str) -> int:
        return sum(1 for note, _p, _s in self.seen if note.endswith(f":{kind}"))

    def material(self, kind: str) -> str:
        return "\n".join(p + s for note, p, s in self.seen if note.endswith(f":{kind}"))


def _sec(st: Store, seam: _Seam | None = None, **kw) -> SEC.Secretary:
    return SEC.Secretary("V", root=st.root, store=st, seam=seam,
                         enable_model=seam is not None, **kw)


class _ReviewSeam:
    """V 自己那条缝（只用来喂 `verify_proof` 的审阅结论，不是秘书）。"""

    def __init__(self, text: str) -> None:
        self.text = text
        #: 真递出去的那份提示词（c8 用它判"可见面"，而不是自己拼一份）。
        self.prompts: list[str] = []

    def ask(self, prompt: str = "", **_kw) -> _Call:
        self.prompts.append(prompt)
        call = _Call()
        call.text = self.text
        call.ok = True
        return call


def _agent(st: Store, secretary=None, *, reply: str = "",
           verdict: dict | None = None) -> AgentV:
    payload = verdict or dict(_OK)
    text = reply or json.dumps(payload, ensure_ascii=False)
    return AgentV(st, workspace_root=st.root, llm=_ReviewSeam(text),
                  secretary=secretary)


def _axis(answer: str, *, checked: bool = True) -> dict:
    """秘书那一路的判定（`judge` 的返回形状：checked + decision）。"""
    return {"checked": checked, "decision": answer, "reason": "夹具：照规则判",
            "basis": ["夹具"]}


# ============================================================ a1 / v2：三次

def test_a1_three_consecutive_holds_flip_the_evidence_bit(tmp_path):
    """v2 正控：三次「成立」且同一份正文 ⇒ 第 3 次才翻 `bits.evidence`。

    判据同时钉住"前两次不翻"：改前一次成立就翻（那就是这一条要取消的口径）。
    """
    st = _ws(tmp_path)
    _put(st)
    for i in (1, 2):
        got = _sign(st)
        assert got["checked"] is True, got
        assert _row(st)["bits"]["reviewed"] is False, f"第 {i} 次就翻位了"
        assert VR.consecutive_holds(st.root, SID)["streak"] == i
    third = _sign(st)
    assert third["checked"] is True, third
    assert _row(st)["bits"]["reviewed"] is True, _row(st)["bits"]
    holds = VR.consecutive_holds(st.root, SID)
    assert holds["checked"] is True and holds["streak"] == 3, holds
    assert holds["streak_ok"] is True and holds["need"] == VR.SIGN_STREAK_NEED, holds
    standing = VR.review_standing(st.root, statement_id=SID, proof_text=PROOF)
    assert standing["state"] == "signed" and standing["ok"] is True, standing
    assert standing["streak"] == 3 and standing["streak_ok"] is True, standing


def test_a2_a_non_hold_in_the_middle_zeroes_the_streak(tmp_path):
    """v2 负控一：中途一次「有毛病」⇒ 连续次数归零，位一次都不许翻。"""
    st = _ws(tmp_path)
    _put(st)
    _sign(st)
    _sign(st)
    assert VR.consecutive_holds(st.root, SID)["streak"] == 2
    _sign(st, verdict=_BAD)
    assert VR.consecutive_holds(st.root, SID)["streak"] == 0, "fault 之后没有归零"
    assert _row(st)["bits"]["reviewed"] is False, _row(st)["bits"]
    # 再攒两次仍然不够（归零意味着从零开始）
    _sign(st)
    _sign(st)
    assert VR.consecutive_holds(st.root, SID)["streak"] == 2
    assert _row(st)["bits"]["reviewed"] is False, "归零之后两次就该够 ⇒ 说明归零没发生"


def test_a3_editing_the_proof_restarts_the_streak(tmp_path):
    """v2 负控二：F 改稿（sha 变）⇒ 归零；旧稿上的两票不许算到新稿头上。"""
    st = _ws(tmp_path)
    _put(st)
    _sign(st)
    _sign(st)
    assert VR.consecutive_holds(st.root, SID)["streak"] == 2
    _sign(st, text=PROOF_B)
    holds = VR.consecutive_holds(st.root, SID)
    assert holds["streak"] == 1, holds
    assert _row(st)["bits"]["reviewed"] is False, "改稿之后旧票还在算 ⇒ sha 那一段没接上"


# ============================================================ a4 / v3：第 1、2 次

def test_a4_the_first_two_holds_land_rows_but_do_not_flip(tmp_path):
    """v3：第 1、2 次「成立」⇒ 台账有行、`bits` 一个字节不变。

    它防的正是"位上说签了、台账只签一次"：位与台账必须是同一次写。
    """
    st = _ws(tmp_path)
    _put(st)
    before_bits = json.dumps(_row(st)["bits"], sort_keys=True, ensure_ascii=False)
    for i in (1, 2):
        _sign(st)
        rows, bad = VR.list_verifications(st.root, statement_id=SID, limit=None)
        assert not bad and len(rows) == i, (i, rows, bad)
        assert json.dumps(_row(st)["bits"], sort_keys=True,
                          ensure_ascii=False) == before_bits, f"第 {i} 次动了位"
        standing = VR.review_standing(st.root, statement_id=SID, proof_text=PROOF)
        assert standing["state"] == "holding", standing
        assert "还差" in standing["why"], standing["why"]
    # 命题级读数也必须分开："签过、还差次数"不是"一次都没签"
    reading = VR.statement_review_reading(st.root, _row(st))
    assert reading["state"] == "holding" and reading["proofs_holding"] == [f"{SID}#p1"], reading
    assert reading["proofs_unreviewed"] == [], reading


def test_a5_signs_bit3_without_a_streak_reading_does_not_sign(tmp_path):
    """行局部谓词 + 连续读数才签；没有连续读数 ⇒ 不签（fail-closed）。

    反真空：同一个 row 给 `streak=3` 必须签 —— 否则"不签"可能只是这一行本来就不合格。
    """
    st = _ws(tmp_path)
    _put(st)
    row = _sign(st)
    assert row["verdict"] == "成立" and VR.row_signable(row) is True, row
    assert VR.signs_bit3(row) is False, "没有连续读数却签了 ⇒ 门被静默绕开"
    assert VR.bit3_payload(row) == {}, VR.bit3_payload(row)
    assert VR.signs_bit3(row, streak=3) is True
    assert VR.bit3_payload(row, streak=3).get("reviewed") is True
    # 读不成（checked=False）不是 0 次、更不是"够"
    broken = {"checked": False, "streak": 3, "streak_ok": True}
    assert VR.signs_bit3(row, streak=broken) is False, "没查成被当成了够"
    assert VR.signs_bit3(row, streak={"checked": True, "streak": 2}) is False


# ============================================================ a6 / a7：秘书持有发签权

def test_a6_the_secretary_performs_the_flip(tmp_path):
    """追加口径 ①：V 只落台账；翻位那一步由秘书调 `sign_statement` 落地。

    三次审阅 ⇒ 第三次之后 `bits.reviewed` 才为真，而前两次的
    `statement_writeback.deferred_to` 都是 `"secretary"`（V 没自己翻）。
    """
    st = _ws(tmp_path)
    _put(st)
    seam = _Seam({"sign_issuance": [_axis(SEC.SIGN_ISSUE)],
                  "v_reply_defect": [_axis(SEC.V_REPLY_CLEAN)]})
    sec = _sec(st, seam)
    agent = _agent(st, sec)
    for i in (1, 2):
        got = agent.verify_proof(SID, proof_text=PROOF)
        assert got["checked"] is True, got
        assert got["sign_issuance"]["issue"] is False, got["sign_issuance"]
        assert got["sign_issuance"]["checked"] is True, got["sign_issuance"]
        assert _row(st)["bits"]["reviewed"] is False, f"第 {i} 次就翻位了"
    third = agent.verify_proof(SID, proof_text=PROOF)
    assert third["sign_issuance"]["issue"] is True, third["sign_issuance"]
    assert third["sign_issuance"]["issued"] is True, third["sign_issuance"]
    assert third["signed_bit3"] is True and third["bits"]["reviewed"] is True, third["bits"]
    assert _row(st)["bits"]["reviewed"] is True, _row(st)["bits"]
    # 发签决定落进了秘书那本账（不是只留在返回值里）
    ledger = sec.decisions_path()
    assert ledger.is_file(), "发签决定没有落台账"
    text = ledger.read_text(encoding="utf-8")
    assert "sign_issuance" in text and SEC.SIGN_ISSUE in text, text[:800]


def test_a7_no_secretary_means_no_signature_at_all(tmp_path):
    """v7（正面用例，主路径）：秘书不在场 ⇒ 判定 `checked=False` 且不发签。

    发签权在秘书手上 ⇒ "这一趟没有秘书"就等于"不能发签"。三趟审阅之后台账有三行
    （意见照留），而第 3 位一次都没翻。
    """
    st = _ws(tmp_path)
    _put(st)
    # (a) 一条"本来会发签"的签：台账已经连续 2 次 clean ⇒ 地板过了，只剩秘书那一层。
    clean = {"checked": True, "axis": "clean", "decision": SEC.V_REPLY_CLEAN}
    _sign(st, judge=clean)
    _sign(st, judge=clean)
    assert VR.consecutive_holds(st.root, SID)["streak"] == 2
    bare = _sec(st, None)          # 装配缺失：没有缝的秘书
    decided = bare.decide_sign_issuance(statement_id=SID, proof_text=PROOF, proof_no=1,
                                        verdict=_OK)
    assert decided["checked"] is False and decided["issue"] is False, decided
    assert decided["issued"] is False, decided
    assert "没查成" in decided["reason"], decided["reason"]
    assert decided["streak_ok"] is True, "地板没过 ⇒ 这一条没测到秘书那一层"
    # (b) 端到端：AgentV 手里没有秘书（`for_role_wired` 在这台机器上没有秘书 key）
    agent = _agent(st, None)
    agent._secretary_tried = True          # 夹具：不让它去现造（没 key ⇒ 现造也是 None）
    agent.secretary_problem = "夹具：这一趟没有 V 的秘书"
    for i in (1, 2, 3):
        got = agent.verify_proof(SID, proof_text=PROOF)
        assert got["checked"] is True, got
        assert got["secretary_judge"]["checked"] is False, got["secretary_judge"]
        assert got["secretary_judge"]["axis"] == "unsure", got["secretary_judge"]
        assert got["sign_issuance"]["checked"] is False, got["sign_issuance"]
        assert got["sign_issuance"]["issued"] is False, got["sign_issuance"]
        assert _row(st)["bits"]["reviewed"] is False, f"第 {i} 次在没有秘书的情况下翻了位"
    rows, _bad = VR.list_verifications(st.root, statement_id=SID, limit=None)
    assert len(rows) == 5, f"意见没有落台账（{len(rows)} 行）"
    # 秘书没判过的那三签是 `unsure`：不清零、也不计入 ⇒ 连续次数停在 2
    assert VR.consecutive_holds(st.root, SID)["streak"] == 2, (
        "秘书没判过的签被算成了 clean（或把已有的两票清零了）⇒ unsure 那一档没接上")


# ============================================================ a8–a10 / v8 与 v7

def _spy_signing(monkeypatch):
    """给两个写口各包一层：记下 `sign_statement` 的调用者函数名与每次落台账的 `flip`。

    为什么量"调用者函数名"而不是"源码里有没有那个字符串"：本仓反复踩过"判据读源码文本"
    的坑（`test_model_calls_are_deterministic` 那条就是）。运行时栈是行为，不是措辞：
    谁真的调了签，就一定在名单里。
    """
    callers: list[str] = []
    flips: list[object] = []
    real_sign = VR.sign_statement
    real_record = VR.record_verification

    def _sign(store, **kw):
        callers.append(str(sys._getframe(1).f_code.co_name))
        return real_sign(store, **kw)

    def _record(root, **kw):
        flips.append(kw.get("flip", True))
        return real_record(root, **kw)

    monkeypatch.setattr(VR, "sign_statement", _sign)
    monkeypatch.setattr(VR, "record_verification", _record)
    return callers, flips


def test_a8_only_the_secretary_calls_the_signing_writer(tmp_path, monkeypatch):
    """v8：V 的代码路径里没有自己签的调用；`sign_statement` 只能由秘书调。

    两条腿缺一条就只是"读起来像"：
    ① 运行时调用栈：三次发签里，每一个调用者都必须是 `_land_sign_issuance`（秘书落地那一步）；
       `verify_proof` / `_finish_numeric` / `record_verification` 一次都不许出现；
    ② 落台账那一步：V 这一路每一次 `record_verification` 都必须 `flip=False`
       （V 只落台账，翻位不是它的事）。

    反真空：这一趟必须真的发生过发签（`callers` 非空），否则"没有自己签"只是没签。
    """
    st = _ws(tmp_path)
    _put(st)
    seam = _Seam({"sign_issuance": [_axis(SEC.SIGN_ISSUE)],
                  "v_reply_defect": [_axis(SEC.V_REPLY_CLEAN)]})
    agent = _agent(st, _sec(st, seam))
    callers, flips = _spy_signing(monkeypatch)
    for i in (1, 2, 3):
        got = agent.verify_proof(SID, proof_text=PROOF)
        assert got["checked"] is True, got
        assert got["signed_bit3"] is (i == 3), (i, got["signed_bit3"], got["sign_issuance"])
    assert callers, "三趟 clean 里一次发签都没有发生 ⇒ 这一条没测到'签'（判据真空）"
    assert set(callers) == {"_land_sign_issuance"}, (
        f"`sign_statement` 被这些调用者调过：{sorted(set(callers))} ⇒ "
        "发签没有唯一落在秘书那一侧（V 或别的路径还在自己签）")
    assert "verify_proof" not in callers and "_finish_numeric" not in callers, callers
    assert flips and all(f is False for f in flips), (
        f"V 这一路有 `record_verification` 没带 flip=False：{flips} ⇒ "
        "V 把「落台账」与「翻位」合成了一步")
    assert _row(st)["bits"]["reviewed"] is True, _row(st)["bits"]


class _LazyButApproving:
    """一个"判了签发、却不去落盘"的秘书（夹具）。

    它把「决定」与「落地」分开：`decide_sign_issuance` 说签发，但从不调 `sign_statement`。
    业主口径把落地也交给秘书（`Secretary._land_sign_issuance`）—— 若 V 在拿到
    `issue=True` 之后自己补一刀，这一条就会红。
    """

    seam = "fake-wired"
    model_source = "夹具：判了但不落盘"

    def judge_v_reply(self, **_kw):
        return {"checked": True, "axis": "clean", "decision": SEC.V_REPLY_CLEAN,
                "reason": "夹具：照规则判 clean", "basis": []}

    def decide_sign_issuance(self, **_kw):
        return {"checked": True, "issue": True, "issued": False,
                "streak": VR.SIGN_STREAK_NEED, "projected": VR.SIGN_STREAK_NEED,
                "need": VR.SIGN_STREAK_NEED, "streak_ok": True,
                "decision": SEC.SIGN_ISSUE, "landed": True, "writeback": {},
                "reason": "夹具：判签发，但一个字都不写盘"}

    def wash_v_reply(self, **_kw):
        return {"checked": False, "washed": False, "text": "", "findings": [],
                "dropped": [], "refused": "secretary_unavailable", "reason": "夹具"}


def test_a9_a_secretary_that_decides_but_does_not_land_cannot_sign(tmp_path):
    """v8 负控：秘书"判了签发但不落盘" ⇒ 位一次都不许翻。

    这是"签只能经秘书"的反面证明：如果 V 拿到 `issue=True` 就自己补一刀，
    或者不看落地结果就报 `signed_bit3=True`，三次 clean 之后位就会翻上去。
    断言同时钉住"票数够"（`streak_ok=True`）—— 于是红只可能来自"谁落的地"。
    """
    st = _ws(tmp_path)
    _put(st)
    agent = _agent(st, _LazyButApproving())
    for i in (1, 2, 3):
        got = agent.verify_proof(SID, proof_text=PROOF)
        assert got["sign_issuance"]["issue"] is True, got["sign_issuance"]
        assert got["sign_issuance"]["streak_ok"] is True, got["sign_issuance"]
        assert got["sign_issuance"]["issued"] is False, got["sign_issuance"]
        assert got["signed_bit3"] is False, (
            f"第 {i} 趟 V 把'秘书决定签发'读成了'位已经签上'：{got['bits']}")
        assert _row(st)["bits"]["reviewed"] is False, _row(st)["bits"]
    rows, _bad = VR.list_verifications(st.root, statement_id=SID, limit=None)
    assert len(rows) == 3, f"三趟审阅应当落三行台账（意见照留），实得 {len(rows)}"


def test_a10_the_tool_path_assembles_its_own_secretary_or_reports_checked_false(
        tmp_path, monkeypatch):
    """v7 正面用例之二：工具路径那种构造（只有 store + root）也要有自己的秘书。

    `tools/verify_tools.py:_agent_v` 是 FC-27（prover-bridge），只给 store 与工作区根，
    造不出秘书 ⇒ 装配必须落在 `AgentV` 这一层（`draft/125` §三 的缺口）。
    这一条把 `secretary.for_role_wired` 换成"造得出来、但没有判断面"（真机形态：没有配
    秘书那一档 key），于是走的是 `AgentV._secretary()` 的真实那条路 ——
    不是夹具里手动把 `_secretary_tried` 打成 True（a7 那样做测不到"有没有去装配"）。
    """
    st = _ws(tmp_path)
    _put(st)
    made: list[object] = []

    def _factory(role, *, root, store=None, **_kw):
        got = SEC.Secretary(str(role), root=pathlib.Path(root), store=store,
                            seam=None, enable_model=False)
        made.append(got)
        return got

    monkeypatch.setattr(SEC, "for_role_wired", _factory)
    clean = {"checked": True, "axis": "clean", "decision": SEC.V_REPLY_CLEAN}
    _sign(st, judge=clean)
    _sign(st, judge=clean)                      # 地板先过：只剩"有没有人发签"
    assert VR.consecutive_holds(st.root, SID)["streak"] == 2
    agent = AgentV(st, workspace_root=st.root,
                   llm=_ReviewSeam(json.dumps(_OK, ensure_ascii=False)))
    got = agent.verify_proof(SID, proof_text=PROOF)
    assert made, "AgentV 没有去装配秘书 ⇒ 工具路径那一侧的缺口仍然没补上"
    assert got["checked"] is True, got
    assert got["secretary_judge"]["checked"] is False, got["secretary_judge"]
    assert got["sign_issuance"]["checked"] is False, got["sign_issuance"]
    assert got["sign_issuance"]["issue"] is False, got["sign_issuance"]
    assert got["signed_bit3"] is False and got["bits"]["reviewed"] is False, got["bits"]
    assert _row(st)["bits"]["reviewed"] is False, _row(st)["bits"]
    # 没判过的那一签是 unsure：不清零、也不计入 ⇒ 连续次数停在 2
    assert VR.consecutive_holds(st.root, SID)["streak"] == 2


# ============================================================ b1 / v1：三档

def test_b1_the_three_states_are_not_flattened(tmp_path):
    """v1：先夸后刺 ⇒ fault（不计入）；反例尝试全失败 ⇒ clean（+1）；
    理由面错位 ⇒ unsure（不清零、也不计入）。"""
    st = _ws(tmp_path)
    _put(st)
    # 三次 clean ⇒ 攒够三票
    seam = _Seam({"v_reply_defect": [_axis(SEC.V_REPLY_CLEAN)]})
    sec = _sec(st, seam)
    clean = sec.judge_v_reply(reply="我试了几种反例构造都失败、未发现问题。",
                              verdict="成立", statement_id=SID)
    assert clean["checked"] is True and clean["axis"] == "clean", clean
    assert clean["answer"] == SEC.V_REPLY_CLEAN
    # 先夸后刺：同一套机制、不同结论 ⇒ fault
    seam_fault = _Seam({"v_reply_defect": [_axis(SEC.V_REPLY_FAULT)]})
    fault = _sec(st, seam_fault).judge_v_reply(reply=RAW_SENTENCE, verdict="成立",
                                              statement_id=SID)
    assert fault["checked"] is True and fault["axis"] == "fault", fault
    # 理由面错位 ⇒ unsure
    seam_unsure = _Seam({"v_reply_defect": [_axis(SEC.V_REPLY_UNSURE)]})
    unsure = _sec(st, seam_unsure).judge_v_reply(reply="文献 [16] 那条我查不到。",
                                                verdict="成立", statement_id=SID)
    assert unsure["checked"] is True and unsure["axis"] == "unsure", unsure
    # ---- 三档在台账上的效果（这才是"不许折平"）
    _sign(st, judge=fault)                      # 1 票都不算
    assert VR.consecutive_holds(st.root, SID)["streak"] == 0, "fault 被计入了"
    _sign(st, judge=clean)
    _sign(st, judge=clean)
    assert VR.consecutive_holds(st.root, SID)["streak"] == 2
    _sign(st, judge=unsure)                     # 不清零、也不计入
    holds = VR.consecutive_holds(st.root, SID)
    assert holds["streak"] == 2, f"unsure 把票数改了（{holds['streak']}）"
    assert _row(st)["bits"]["reviewed"] is False
    _sign(st, judge=clean)                      # 第三票到
    assert VR.consecutive_holds(st.root, SID)["streak"] == 3
    assert _row(st)["bits"]["reviewed"] is True, "第三票到了却没翻位"


def test_b2_the_question_carries_the_three_state_rules():
    """题面必须逐字带着业主那几条判定规则（否则模型只能猜，三档必然折平）。"""
    system = SEC._judge_system("v_reply_defect")
    for phrase in ("整体很好，只是有一个缺陷需要指出",
                   "思路没问题，但是有一个记号问题需要强调",
                   "我找不到反例，但某对象似乎没有定义",
                   "我觉得没问题但我没逐行验证",
                   "我试了几种反例构造都失败",
                   "文献", "实验数值", "排版"):
        assert phrase in system, f"题面里缺这一条判定规则：{phrase!r}"
    # 三档词表逐字出现在题面里（`judge()` 的校验与题面同源）
    for word in SEC.V_REPLY_VERDICTS:
        assert word in system, (word, system[:400])
    # 它与审美轴是两张表（不许复用 STATEMENT_VERDICTS）
    assert SEC.JUDGE_VERDICTS["v_reply_defect"] is SEC.V_REPLY_VERDICTS
    assert SEC.JUDGE_VERDICTS["v_reply_defect"] is not SEC.STATEMENT_VERDICTS


def test_b3_the_secretary_never_gets_the_proof_text(tmp_path):
    """v4：材料里塞 F 的证明正文 ⇒ 必须被拒（不是"收了但没用"）。"""
    st = _ws(tmp_path)
    seam = _Seam({"v_reply_defect": [_axis(SEC.V_REPLY_CLEAN)]})
    sec = _sec(st, seam)
    refused = sec.judge_v_reply(reply=RAW_SENTENCE, verdict="成立", statement_id=SID,
                                proof_text="F 的证明正文：第 1 步由定义直接得到。")
    assert refused["checked"] is False, refused
    assert refused["refused"] == "proof_text_not_allowed", refused
    assert seam.asked("v_reply_defect") == 0, "被拒的那一次仍然发了模型调用"
    assert "F 的证明正文" not in json.dumps(refused["material"], ensure_ascii=False)
    # 正控：不塞证明 ⇒ 判了，且材料里只有回复 + 那一行
    ok = sec.judge_v_reply(reply=RAW_SENTENCE, verdict="有毛病", defect_step=2,
                           statement_id=SID)
    assert ok["checked"] is True, ok
    material = json.dumps(ok["material"], ensure_ascii=False, sort_keys=True)
    assert set(ok["material"]) == {"v_reply", "ledger_row"}, ok["material"]
    assert RAW_SENTENCE in material


def test_b4_a_conclusion_outside_the_vocabulary_is_not_taken(tmp_path):
    """词表外的结论不采信，且归 unsure（不是 clean —— 那会把没判成当没问题）。"""
    st = _ws(tmp_path)
    seam = _Seam({"v_reply_defect": [_axis("成立")]})       # 另一根轴的词
    got = _sec(st, seam).judge_v_reply(reply=RAW_SENTENCE, verdict="成立",
                                       statement_id=SID)
    assert got["checked"] is False, got
    assert got["axis"] == "unsure", got
    assert "不采信" in got["reason"] or "词表" in got["reason"], got["reason"]


# ============================================================ c1–c3 / v5：洗稿

def _washed(text: str = "记号未定义：第 2 步的符号缺公式级定义。请补定义后重交。",
            quotes: list[str] | None = None) -> dict:
    quotes = quotes or ["第 2 步的记号没有定义"]
    return {"text": text, "step": 2,
            "findings": [{"quote": q, "why": "这一处需要补"} for q in quotes]}


def test_c1_washing_rewrites_the_reply_and_grounds_every_finding(tmp_path):
    """v5 正控：洗过的文本 ≠ V 原文；findings 逐字落回原文。"""
    st = _ws(tmp_path)
    doc = _washed()
    seam = _Seam({"wash_v_reply": [doc]})
    got = _sec(st, seam).wash_v_reply(reply=RAW_SENTENCE, verdict="有毛病",
                                      defect_step=2, statement_id=SID)
    assert got["checked"] is True and got["washed"] is True, got
    assert got["text"] and got["text"] != RAW_SENTENCE, got["text"]
    assert RAW_SENTENCE not in got["text"], "洗过的文本里还带着原文整句"
    assert got["findings"], got
    for finding in got["findings"]:
        assert finding["quote"] in RAW_SENTENCE, finding
    assert got["refused"] == "", got


def test_c2_unwashable_replies_are_refused_without_the_original(tmp_path):
    """v5 负控：洗不出来 ⇒ 受控拒绝、不输出原文。

    两条路各判一次：① 没有缝（装配缺失）；② 模型给的 findings 一条都引不回原文。
    """
    st = _ws(tmp_path)
    bare = _sec(st, None).wash_v_reply(reply=RAW_SENTENCE, verdict="有毛病",
                                       defect_step=2, statement_id=SID)
    assert bare["checked"] is False and bare["washed"] is False, bare
    assert bare["refused"] == "secretary_unavailable", bare
    assert bare["text"] == "", "拒绝时把 V 的原文递出去了"
    fabricated = {"text": "改写后的一句话。",
                  "findings": [{"quote": "第 4 步的引理用错了", "why": "夹具：原文里没有"}]}
    seam = _Seam({"wash_v_reply": [fabricated]})
    got = _sec(st, seam).wash_v_reply(reply=RAW_SENTENCE, verdict="有毛病",
                                      defect_step=2, statement_id=SID)
    assert got["checked"] is False and got["washed"] is False, got
    assert got["refused"] == "findings_not_grounded", got
    assert got["text"] == "", "引不回的 findings 也把改写文本递出去了"


class _Cond:
    """`conductor` 的替身：只实现 `deliver_v_verdicts` 用到的那三件。"""

    def __init__(self) -> None:
        self.items: list[dict] = []

    def _board_rows(self) -> list[dict]:
        return [dict(r) for r in self.items]

    def open_item(self, **kw) -> str:
        item_id = f"t-{len(self.items) + 1}"
        self.items.append({"item_id": item_id, **kw})
        return item_id

    def set_item_detail(self, item_id: str, body: str) -> None:
        for row in self.items:
            if row["item_id"] == item_id:
                row["detail"] = body


def test_c3_the_notice_carries_the_washed_text_not_the_raw_reply(tmp_path):
    """C 段交付面：板项 detail 用洗过的文本（`kind="notice"` / `expects="ack"` 不变）。

    这条同时钉住"洗过的文本从哪来"：台账那一行的 `washed_relay.text`（不是调用方现编）。
    """
    st = _ws(tmp_path)
    _put(st)
    washed_text = "记号未定义：第 2 步的符号缺公式级定义。请补定义后重交。"
    row = VR.record_verification(st.root, statement_id=SID, proof_text=PROOF,
                                 verdict=_BAD, verifier="agent-V", store=st,
                                 proof_no=1, flip=False,
                                 secretary_judge={"checked": True, "axis": "fault",
                                                  "decision": "有缺陷要指出"},
                                 washed_relay={"washed": True, "text": washed_text,
                                               "findings": [{"quote": "第 2 步的记号没有定义",
                                                             "why": "缺定义"}]})
    assert row.get("washed_relay", {}).get("text") == washed_text, row.get("washed_relay")
    text, details, _problems = AL.v_rejections_digest(st.root, [_row(st)])
    assert details and details[0]["washed"] == washed_text, details
    assert "V 的原话" not in text, text
    cond = _Cond()
    out = AL.deliver_v_verdicts(cond, task_id="t-000000000001", depth=1,
                                role="F", details=details)
    assert out["checked"] is True and len(out["opened"]) == 1, out
    item = cond.items[0]
    assert item["kind"] == "notice" and item["expects"] == "ack", item
    detail = str(item.get("detail") or "")
    assert washed_text[:20] in detail, detail
    assert "洗过的转达" in detail, detail
    assert RAW_SENTENCE not in detail, "递出去的是 V 的原文，不是洗过的文本"


# ============================================================ c4 / c5：业主追加口径 ②③

def _v_visible() -> dict[str, str]:
    reg = build_registry().registry
    return {"system_prompt": AP.system_prompt("V", registry=reg),
            "cold_start": VR.cold_start_prompt(FULL, PROOF, readonly_facts="- 夹具"),
            "skills": "\n".join(s.body for s in SK.skills_for("V"))}


def test_c4_vs_visible_surfaces_do_not_mention_washing(tmp_path):
    """v9 的否定半边：V 不知道秘书洗稿的存在。

    判据四半（第 3、4 半是 2026-10-29 S5 补的：`draft/126` §三 把"转达"也列进了禁词）：
    1. 硬禁词 `洗稿` / `清洗` 在 V 的三处可见面里 0 次；
    2. `wash` 这个拼写只允许出现在"派活先过秘书"那一句里（它指的是 `delegate`
       返回里的 `wash` 栏 —— 秘书给委托洗格式，与"V 的意见被洗"不是一件事）。
       数量与上下文都钉住：再多一处、或搬出那一句，这条就红；
    3. V 自己写的那两份文本（冷启动提示词 + 技能手册）里 `洗` / `转达` 都是 0 次：
       "你的意见之后会怎样"不许出现在它的可见面上；
    4. 系统提示词里 `转达` 只允许是共用段那两句（交给父代理转达 / 收工自查还没转达）——
       那是全仓十一个角色共用的转达链，与"意见被处理"无关，`tests/test_agent_prompts.py`
       也钉着它。这两句之外多出一处 `转达` ⇒ 红。

    另有正控：同一个 `wash_v_reply` 的措辞确实在别处（免得判据扫错了对象）。
    """
    visible = _v_visible()
    for name, text in visible.items():
        assert text, f"{name} 是空的 ⇒ 判据扫不到东西（假绿）"
        for word in ("洗稿", "清洗"):
            assert word not in text, (name, word)
    # ③ V 自己写的那两份：连"洗"与"转达"都不许有
    for name in ("cold_start", "skills"):
        for word in ("洗", "转达"):
            assert word not in visible[name], (
                f"{name} 里出现了 {word!r} ⇒ V 从自己的可见面上就会想到"
                "「我的意见之后会被处理」，而它不该知道这件事")
    # ④ 系统提示词：`转达` 只剩共用段那两句（逐字核上下文）
    system = visible["system_prompt"]
    assert system.count("转达") == 2, (
        f"V 的系统提示词里 `转达` 出现 {system.count('转达')} 次（期望 2：共用段那两句）"
        "⇒ 请核一遍新加的那一处是不是在说『你的意见会被转达』")
    for shared in ("由父在步边界转达", "还没转达"):
        assert shared in system, shared
    hits = [m for m in ("wash",) if m in system]
    assert hits == ["wash"], f"`wash` 在 V 的提示词里出现 {len(hits)} 种写法：{hits}"
    assert system.count("wash") == 1, "`wash` 出现了不止一处：请核一遍它是不是新加的"
    at = system.find("wash")
    around = system[max(0, at - 200):at + 120]
    assert "派活先过秘书" in around, (
        "唯一那一处 `wash` 不在『派活先过秘书』那一句里 ⇒ 它可能是在说『V 的意见会被洗』："
        + around)
    # 正控：这一条不是"全文都没有 wash"那种假绿
    assert "wash_v_reply" in json.dumps(
        {k: str(v) for k, v in SEC.Secretary.__dict__.items()}), "洗稿那个方法不见了"


def test_c8_vs_prompt_and_manual_say_the_signature_belongs_to_the_secretary(tmp_path):
    """v9 的肯定半边：V 的可见文本说清「你只产意见、签由秘书」与「你看不到审阅之外」。

    "可见"取最硬的那个定义：真的递给模型的那份提示词（`AgentV.verify_proof` 实际发出去的
    prompt，由替身缝抄一份），加上 V 的技能手册正文（`skills/V/` 落盘的那几份的正文）。
    断言五类：
      ① 签由秘书：两份都写「签由你的秘书……」；
      ② 你看不到审阅之外（洗稿那件事对它是不可见面）；
      ③ 审阅清单接进来了：H-1…H-5 / T-1…T-8 / N-1…N-4 / C-1…C-4 与"不归 F"都点名；
      ④ 清单被注明"这是嘱托，不是门"，并指向 `docs/DEVELOPMENT-SPEC.md` §13；
      ⑤ V 的提示词索引里点得到那份手册（`skills/V/产出-只产意见-签在秘书.md`）。
    """
    st = _ws(tmp_path)
    _put(st)
    seam = _ReviewSeam(json.dumps(_OK, ensure_ascii=False))
    agent = AgentV(st, workspace_root=st.root, llm=seam, secretary=_LazyButApproving())
    agent.verify_proof(SID, proof_text=PROOF)
    sent = seam.prompts[0] if seam.prompts else ""
    assert sent, "这一趟没有提示词 ⇒ 判据扫不到可见面（假绿）"
    body = "\n".join(s.body for s in SK.skills_for("V"))

    def _missing(text: str) -> list[str]:
        """这一份可见文本缺了哪几条必须出现的句子（空列表 = 齐了）。"""
        need = ["秘书判定并落盘", "发不发签", "你看不到审阅之外的任何东西",
                "这是嘱托，不是门", "DEVELOPMENT-SPEC.md", "§13",
                "H-1", "H-5", "T-1", "T-8", "N-1", "N-4", "C-1", "C-4", "不归 F"]
        return [p for p in need if p not in text]

    for name, text in (("冷启动提示词", sent), ("技能手册", body)):
        assert not _missing(text), (name, "缺了这些句子/条目：", _missing(text))
    # 负控（§13.2「没有负控的判据不算判据」）：把「签由秘书」那一句从同一份提示词里挖掉，
    # 上面那个算式必须当场看见 —— 否则它量的只是"文本很长"，而不是那几句话在不在。
    stripped = sent.replace("秘书判定并落盘", "")
    assert _missing(stripped), "负控失效：挖掉『签由秘书』之后同一个算式仍然说齐了"
    assert "秘书判定并落盘" in _missing(stripped)
    # ⑤ 索引里点得到那份手册（正文按需读，索引是唯一入口）
    system = AP.system_prompt("V", registry=build_registry().registry)
    idx = SK.skill_path("V", "产出-只产意见-签在秘书")
    assert idx in system, idx
    # 反真空：这一份手册真的在 V 的手册清单里（不是只在别处写过一句话）
    assert any(s.slug == "产出-只产意见-签在秘书" for s in SK.skills_for("V"))


def test_c5_vs_thinking_default_is_high(tmp_path):
    """业主追加口径 ③：思考强度默认 High 是既有设计，这里只钉住它。

    真身：`modelgw.DEFAULT_REASONING_EFFORT`（`modelgw.py`）+ `ModelSpec` 的缺省
    + `settings.MODEL_KEYS` 里有 `reasoning_effort`。既有的逐角色判据是
    `tests/test_every_agent_can_think.py::test_every_role_asks_with_the_same_thinking_setting`
    —— 这一条只把 V 那一条出口单独钉一次（发签门槛改的是 V，它的思考强度不许被
    顺手改掉）。
    """
    assert G.DEFAULT_REASONING_EFFORT == "high", G.DEFAULT_REASONING_EFFORT
    assert G.ModelSpec(api_key="k").reasoning_effort == "high"
    from agentflow import settings as SET

    assert "reasoning_effort" in SET.MODEL_KEYS, SET.MODEL_KEYS
    bodies: list[dict] = []

    def _transport(_url, _headers, data, _timeout):
        bodies.append(json.loads(data.decode("utf-8")))
        return 200, json.dumps({"choices": [{"message": {"content": "{}"}}]})

    gw = G.ModelGateway(G.ModelSpec(api_key="k"), transport=_transport,
                        sleep=lambda _s: None, clock=lambda: 0.0)
    from agentflow import llmseam as LS

    seam = LS.LlmSeam.for_role("V", session_root=tmp_path, gateway=gw)
    seam.ask("夹具：审一遍", task_id="t-wire")
    assert bodies and bodies[-1].get("reasoning_effort") == "high", bodies[-1:]


def test_c6_vs_review_call_asks_at_temperature_one(tmp_path):
    """v10：V 的审阅请求体里 `temperature==1.0`；别的角色不受影响（仍是 0.2）。

    业主 2026-10-29：「temperature = 1.0（正常对话的数值）」——只给 V 的审阅调用。
    读的是真请求体（`modelgw.ModelGateway._payload` 组出来的那个 JSON，transport
    替身抄一份），不是 `to_dict()` 的读数，也不是源码文本里的字面量：改前那条假绿
    正是 grep 了一个从没进过网线的常量（见 `tests/test_model_calls_are_deterministic.py`）。

    负控：把 `AgentV._ask` 里那个 `temperature=` 摘掉 ⇒ body 回到 0.2，这一条当场红。
    """
    from agentflow import llmseam as LS

    st = _ws(tmp_path)
    _put(st)
    bodies: list[dict] = []

    def _transport(_url, _headers, data, _timeout):
        bodies.append(json.loads(data.decode("utf-8")))
        return 200, json.dumps({"choices": [{"message": {
            "content": json.dumps(_OK, ensure_ascii=False)}}]}, ensure_ascii=False)

    gw = G.ModelGateway(G.ModelSpec(api_key="k"), transport=_transport,
                        sleep=lambda _s: None, clock=lambda: 0.0)
    seam = LS.LlmSeam.for_role("V", session_root=st.root, gateway=gw)
    # 秘书用"判了不落盘"的替身：这一条只量请求体，不让它写盘、也不让它联网
    agent = AgentV(st, workspace_root=st.root, llm=seam, secretary=_LazyButApproving())
    got = agent.verify_proof(SID, proof_text=PROOF)
    assert got["checked"] is True and got["verdict"] == "成立", got
    assert bodies, "V 的审阅一次请求都没发 ⇒ 这一条没测到请求体"
    assert bodies[-1]["temperature"] == 1.0, (
        "V 的审阅请求体不是 1.0（业主 2026-10-29 的正常对话口径）："
        f"{bodies[-1].get('temperature')!r}")
    # 负控：同一个缝、同一条网关配置，不显式给温度时 body 是 0.2 ——
    # 于是"1.0"只可能来自 `AgentV._ask` 里那一格，而不是这条夹具的配置。
    LS.LlmSeam.for_role("V", session_root=st.root, gateway=gw).ask("夹具：不给温度")
    assert bodies[-1]["temperature"] == G.DEFAULT_TEMPERATURE == 0.2, bodies[-1]
    # 别的角色不受影响：同一条网关配置下，F 那一档仍然是缺省 0.2
    other: list[dict] = []

    def _t2(_url, _headers, data, _timeout):
        other.append(json.loads(data.decode("utf-8")))
        return 200, json.dumps({"choices": [{"message": {"content": "{}"}}]})

    gw2 = G.ModelGateway(G.ModelSpec(api_key="k"), transport=_t2,
                         sleep=lambda _s: None, clock=lambda: 0.0)
    LS.LlmSeam.for_role("F", session_root=st.root, gateway=gw2).ask("夹具：别的角色")
    assert other and other[-1]["temperature"] == G.DEFAULT_TEMPERATURE == 0.2, other[-1:]
    # 秘书那一档也不动（它的判断调用走 `ask_json`，没有显式温度）
    LS.LlmSeam.for_secretary(owner_role="V", session_root=st.root,
                             gateway=gw2).ask("夹具：秘书")
    assert other[-1]["temperature"] == 0.2, other[-1]


def test_c7_vs_thinking_effort_high_is_a_live_reading(tmp_path):
    """S6 核实：V 的思考强度默认 High 落在哪几处，且这是一条活读数。

    落点（都是现算，不读源码文本；行号会漂，符号名不会）：
      · `modelgw.DEFAULT_REASONING_EFFORT = "high"` —— 唯一来源；
      · `ModelSpec.reasoning_effort` 的缺省就是它（构造即过
        `normalize_reasoning_effort`，词表外当场抛）；
      · `spec_for` / `spec_from_env` 的第三档 = `effort or DEFAULT_REASONING_EFFORT`
        （梯子：环境变量 > `settings.json` 的 `model.reasoning_effort` > 它）；
      · `settings.MODEL_KEYS` 里有 `reasoning_effort`（面板那一格能写）；
      · `specs/v.py` 里没有任何 thinking / reasoning / effort 的文句 —— V 不是"单独一档
        High"，它是跟着机器这一档走。所以这条钉的是"机器那一档的默认读数"，不是 V 的 policy。
    另：`llmseam.LlmSeam.reasoning_effort` 把它转抄进 `SeamCall`，
    `modelgw.reasoning_body_fields` 把它序列化进请求体 —— 两处都是"如实转抄"，不另立缺省。

    判据两半：
      ① 读数：空环境 + 空设置下 `spec_for("V")` 是 high，且 V 的审阅请求体里是 high；
      ② 负控：把 `AGENTFLOW_MODEL_REASONING_EFFORT=low` 灌进同一道梯子 ⇒ V 的读数与
         请求体都跟着变 low。若这条判据量的只是"仓库某处写着 high"，这一半会红。
    """
    from agentflow import llmseam as LS
    from agentflow import settings as SET

    # ① 读数：默认档（不读真设置文件；只灌一把假 key，好让请求真的发出去）
    spec, where = G.spec_for("V", path=tmp_path / "none.json", env={G.ENV_KEY: "k"})
    assert where == "" and spec.reasoning_effort == "high", (where, spec.redacted())
    assert "reasoning_effort" in SET.MODEL_KEYS, SET.MODEL_KEYS
    bodies: list[dict] = []

    def _transport(_url, _headers, data, _timeout):
        bodies.append(json.loads(data.decode("utf-8")))
        return 200, json.dumps({"choices": [{"message": {"content": "{}"}}]})

    gw = G.ModelGateway(spec, transport=_transport, sleep=lambda _s: None, clock=lambda: 0.0)
    LS.LlmSeam.for_role("V", session_root=tmp_path, gateway=gw).ask("夹具：审一遍")
    assert bodies and bodies[-1].get("reasoning_effort") == "high", bodies[-1:]
    # ② 负控：同一条梯子，环境变量压上来 ⇒ 读数与请求体一起变（证明它不是常量）
    low, _ = G.spec_for("V", path=tmp_path / "none.json",
                        env={G.ENV_KEY: "k", G.ENV_EFFORT: "low"})
    assert low.reasoning_effort == "low", low.redacted()
    bodies2: list[dict] = []

    def _t2(_url, _headers, data, _timeout):
        bodies2.append(json.loads(data.decode("utf-8")))
        return 200, json.dumps({"choices": [{"message": {"content": "{}"}}]})

    gw2 = G.ModelGateway(low, transport=_t2, sleep=lambda _s: None, clock=lambda: 0.0)
    LS.LlmSeam.for_role("V", session_root=tmp_path, gateway=gw2).ask("夹具：审一遍")
    assert bodies2 and bodies2[-1].get("reasoning_effort") == "low", bodies2[-1:]


# ============================================================ z：反真空（v6）

def test_z1_removing_the_streak_gate_makes_the_first_hold_flip(tmp_path, monkeypatch):
    """v6 上半：把连续闸摘掉 ⇒ a1 的"第 1 次不翻位"当场变红。

    做法是把 `streak_ok` 打成恒真（那正是"没有连续约束"的世界），于是第 1 次就翻位
    —— 这一条证明 a1 量的是那道闸，而不是别的什么。
    """
    st = _ws(tmp_path)
    _put(st)
    monkeypatch.setattr(VR, "streak_ok", lambda *_a, **_k: True)
    _sign(st)
    assert _row(st)["bits"]["reviewed"] is True, (
        "把连续闸摘掉之后第 1 次仍然没翻位 ⇒ a1 不是被这道闸拦住的（判据瞄错了对象）")
    monkeypatch.undo()
    st2 = _ws(tmp_path / "clean")
    _put(st2)
    _sign(st2)
    assert _row(st2)["bits"]["reviewed"] is False, "摘掉闸与不摘掉闸结论一样 ⇒ a1 没量到闸"


def test_z2_ignoring_the_secretary_axis_makes_a_fault_row_count(tmp_path, monkeypatch):
    """v6 下半：把 judge 那一格摘掉（`secretary_axis` 恒返回空串）⇒ b1 的
    "fault 不计入"当场变红。"""
    st = _ws(tmp_path)
    _put(st)
    fault = {"checked": True, "axis": "fault", "decision": "有缺陷要指出"}
    monkeypatch.setattr(VR, "secretary_axis", lambda _row: "")
    for _i in range(3):
        _sign(st, judge=fault)
    assert _row(st)["bits"]["reviewed"] is True, (
        "摘掉 judge 之后三次 fault 仍然没签 ⇒ b1 的'fault 不计入'不是 judge 干的")
    monkeypatch.undo()
    st2 = _ws(tmp_path / "clean")
    _put(st2)
    for _i in range(3):
        _sign(st2, judge=fault)
    assert _row(st2)["bits"]["reviewed"] is False, "judge 接上了而 fault 仍然计入"

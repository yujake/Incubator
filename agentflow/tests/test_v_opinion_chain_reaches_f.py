# -*- coding: utf-8 -*-
"""业主验收清单 (E) 的接线小模拟：V 的意见怎么以板项形式到达 F。

## 这一条链（`draft/126` §二 的 C 段与 B 段）

```text
AgentV.verify_proof（V 的真入口）
  -> 秘书 judge_v_reply（语义三档：clean / fault / unsure）
  -> fault 才 wash_v_reply（洗稿；洗不出来就不输出原文）
  -> verifications/<命题号>.jsonl 那一行的 washed_relay（洗过的转达文本）
  -> agent_loop.v_rejections_digest（读侧）
  -> agent_loop.deliver_v_verdicts（板项：kind=notice / expects=ack）
  -> F 的收件板
```

## 判据表（e1–e5），每条都带"它能怎么红"

| 编号 | 它要证明的事 | 它能怎么红 |
|---|---|---|
| e1 | fault 才洗：V 的回复"整体很好，只是有一个记号问题需要强调"⇒ 秘书判 fault ⇒ 洗 ⇒ 板项 detail 不是 V 原文，且逐字带着 V 指出的那个问题 | 同一份回复、只把秘书判成 clean ⇒ 洗稿一次都不许发生（本用例里当场跑一遍）；fault 却不洗 / 洗了但没递 ⇒ 板项读不到洗过的文本 |
| e2 | clean 不打扰 F：V 说"我试了几种反例构造都失败，未发现问题"⇒ 不发意见、streak +1 | 把 clean 当 fault（洗了/递了）或不计入（streak 不涨）⇒ 红 |
| e3 | unsure 不冒充：V 的回复含糊（无尝试痕迹）⇒ 不计入、不清零、也不给 F 发意见 | 折成 clean（streak 变 2）或折成 fault（streak 归零/洗稿）⇒ 红 |
| e4 | F 收不到 V 原文：板项 detail 与 V 原文不相等、且第一人称那句不在里面；kind/expects 不许新造（只能是 notice/ack） | 直接转发原文 ⇒ 红；新造一档 kind/expects ⇒ 冻结面被改 |
| e5 | 端到端的顺序：先喂 V 的意见、再断言 F 看得到；中间不许手工改盘绕过秘书 | 没有 V 那一签（空工作区）却能在板上开到项 ⇒ 红；板项文本不是台账那一格的字节 ⇒ 红 |

## 哪些是真入口、哪些是打桩（不许假装）

- 真入口：`AgentV.verify_proof`（V 的审阅与落台账）、真装配的 `Secretary`（`judge_v_reply`
  / `wash_v_reply` / `decide_sign_issuance` 都是本尊）、`v_rejections_digest`、
  `deliver_v_verdicts`；板项的 `open_item` / `set_item_detail` 用的是 conductor 的最小替身
  （与 `tests/test_v_verdict_reaches_f.py` 的 conductor 替身同一条既有做法：真 conductor
  要整台主控）。
- 打桩：V 的审阅回复与秘书的三次语义判定都由离线替身缝给（`ask` / `ask_json`）。
  也就是说，这一份判据验的是"接线"，不是"模型的语义判断对不对"——秘书那三档的
  题面规则由 `tests/test_v_sign_gate_streak.py::test_b2` 钉着，模型的真实判断力
  今天没有任何判据能端到端验（`draft/126` §三 已登记）。

## (C) 那一半

`ToolRegistry.call("verify.verify_proof")` 的真工具入口，把返回键与 `returns=` 声明
逐个比对。已知缺口（FC-27 的 `tools/verify_tools.py`，本轮不许改）：声明里没有
`secretary_judge` / `sign_issuance` 两个键。本文件只把读数钉住，不动那个文件。
"""
from __future__ import annotations

import json
import pathlib

import pytest

from agentflow import agent_loop as AL
from agentflow import agent_v as AV
from agentflow import evidencebits as EB
from agentflow import schema as S
from agentflow import secretary as SEC
from agentflow import verifications as VR
from agentflow.agent_v import AgentV
from agentflow.store import Store
from agentflow.tools import build_registry
from test_tools_audit_fixes import declared_keys

TS = "2026-10-29T00:00:00+08:00"
SID = "000007"
PROOF = "1. 取 G = C_n（n ≥ 3）：它是 2-正则、围长为 n。\n2. 由第 1 步直接得到结论。"
FULL = "设 G 是 3-正则群；则弦长函数不是常值。"

#: V 指出的那个具体问题（逐字）：它必须逐字出现在 V 的回复里（可回溯），
#: 也必须逐字出现在 F 收到的板项 detail 里（转达没有把问题洗掉）。
DEFECT = "第 2 步的记号没有定义"
#: V 的回复正文里那一句第一人称的"先夸"，洗过之后不许再出现在递给 F 的 detail 里。
FRAME = "整体很好，只是有一个记号问题需要强调"
#: V 的原始回复（`why` 就是 FRAME + DEFECT）。V 自己的结论词写的是「成立」——
#: 这正是秘书语义判定存在的理由：判定词是 V 的自述，三档判定看的是它到底说了什么。
RAW = f"{FRAME}：{DEFECT}。"
REPLY_HOLDS = json.dumps({
    "verdict": "成立", "defect_step": None, "why": RAW,
    "findings": [{"level": "warning", "step": 2, "kind": "记号未定义", "detail": DEFECT}],
}, ensure_ascii=False)
REPLY_CLEAN = json.dumps({"verdict": "成立", "why": "我试了几种反例构造都失败，未发现问题。",
                          "findings": []}, ensure_ascii=False)
REPLY_UNSURE = json.dumps({"verdict": "成立", "why": "我觉得没问题。", "findings": []},
                          ensure_ascii=False)

#: 秘书洗过的那一份转达文本（替身缝给的那一段）。它必须：
#: 1) 与 V 的原文不相等（`wash_v_reply` 自己会拒"逐字相同"）；
#: 2) 逐字带着 DEFECT（F 要知道补哪一处，这是"洗稿"不是"删稿"）；
#: 3) 不带 FRAME 那句第一人称。
WASHED = f"{DEFECT}：请给这个记号一个公式级定义之后再重交（其余步骤这一趟没有发现问题）。"


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
    """离线替身缝：按 `note`（`secretary:<kind>`）回预置 JSON，并记住问过什么。"""

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


def _axis(answer: str) -> dict:
    """秘书那一路的判定（`judge` 的返回形状：checked + decision）。"""
    return {"checked": True, "decision": answer, "reason": "夹具：照规则判",
            "basis": ["夹具"]}


def _wash_doc(*, quote: str = DEFECT) -> dict:
    """洗稿的替身答案：`text` 是转达文本，`findings` 里每一条都要能引回原文。"""
    return {"text": WASHED, "step": 2,
            "findings": [{"quote": quote, "why": "这一处需要补"}]}


def _sec(st: Store, seam: _Seam | None = None) -> SEC.Secretary:
    return SEC.Secretary("V", root=st.root, store=st, seam=seam,
                         enable_model=seam is not None)


class _ReviewSeam:
    """V 自己那条缝（只用来喂 `verify_proof` 的审阅结论，不是秘书）。"""

    def __init__(self, *replies: str) -> None:
        self.replies = list(replies)
        self.prompts: list[str] = []

    def ask(self, prompt: str = "", **_kw) -> _Call:
        self.prompts.append(prompt)
        call = _Call()
        call.text = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        return call


class _Cond:
    """`conductor` 的替身：只实现 `deliver_v_verdicts` 用到的那三件。

    与既有判据（`tests/test_v_sign_gate_streak.py::_Cond`）同形；`opened_by` 记下是谁开的项
    —— e5 用它证明这一项不是测试自己写进板里的。
    """

    def __init__(self) -> None:
        self.items: list[dict] = []
        self.opened_by: list[str] = []

    def _board_rows(self) -> list[dict]:
        return [dict(r) for r in self.items]

    def open_item(self, **kw) -> str:
        item_id = f"t-{len(self.items) + 1}"
        self.items.append({"item_id": item_id, **kw})
        self.opened_by.append(item_id)
        return item_id

    def set_item_detail(self, item_id: str, body: str) -> None:
        for row in self.items:
            if row["item_id"] == item_id:
                row["detail"] = body


def _ask_v(st: Store, seam: _Seam, *replies: str) -> tuple[AgentV, dict, dict]:
    """走 V 的真入口一次（`AgentV.verify_proof`，秘书是真装配的那个对象）。"""
    sec = _sec(st, seam)
    agent = AgentV(st, workspace_root=st.root, llm=_ReviewSeam(*replies), secretary=sec)
    got = agent.verify_proof(SID, proof_text=PROOF)
    return agent, got, sec


def _deliver(st: Store) -> tuple[str, list[dict], list[str], _Cond, dict]:
    """读侧 + 投递（F 侧那两步的真入口）。返回 `(文本, 明细, 问题, conductor, 投递读数)`。"""
    text, details, problems = AL.v_rejections_digest(st.root, [_row(st)])
    cond = _Cond()
    out = AL.deliver_v_verdicts(cond, task_id="t-000000000001", depth=1, role="F",
                                details=details)
    return text, details, problems, cond, out


def _ledger_row(st: Store) -> dict:
    rows, bad = VR.list_verifications(st.root, statement_id=SID, limit=None)
    assert not bad, bad
    assert rows, "这一签没有落台账"
    return dict(rows[-1])


# ============================================================ e1：fault 才洗

def test_e1_fault_washes_and_the_washed_opinion_is_what_f_gets(tmp_path):
    """e1：V 说"整体很好，只是有一个记号问题需要强调" ⇒ 秘书判 fault ⇒ 洗 ⇒ F 收到洗过的。

    断言六件事（缺一件这条链就只"看起来"通了）：
      1. 秘书真的判了，且判的是 fault；
      2. 洗稿调用真的发生了，且洗出来的文本不等于、也不包含 V 的原文；
      3. 台账那一行的 `washed_relay.text` 就是洗出来的那一份（递送的唯一来源）；
      4. 读侧（`v_rejections_digest`）真的把这一条读出来了，`washed` 就是那一份；
      5. 板上真的开出了项，且 `detail` 逐字带着 V 指出的那个问题（DEFECT 在 V 原文里也在
         detail 里 —— 逐字可回溯）；
      6. 反面：同一份回复、只把秘书判成 clean ⇒ 洗稿一次都不许发生，也不许递。
    """
    st = _ws(tmp_path)
    _put(st)
    seam = _Seam({"v_reply_defect": [_axis(SEC.V_REPLY_FAULT)],
                  "wash_v_reply": [_wash_doc()]})
    _agent, got, _sec_obj = _ask_v(st, seam, REPLY_HOLDS)

    # 1. 语义判定真的发生了（材料里就是 V 的回复原文），档是 fault
    assert got["checked"] is True, got
    judge = dict(got["secretary_judge"])
    assert judge.get("checked") is True and judge.get("axis") == "fault", judge
    assert seam.asked("v_reply_defect") == 1, "秘书没有被问过一次"
    assert DEFECT in seam.material("v_reply_defect"), "秘书没拿到 V 的回复原文 ⇒ 判定没有对象"

    # 2. 洗稿：调用一次，文本不等于原文、也不含原文那句第一人称
    assert seam.asked("wash_v_reply") == 1, "fault 却没洗"
    wash = dict(got.get("wash_v_reply") or {})
    assert wash.get("checked") is True and wash.get("washed") is True, wash
    assert wash.get("text") == WASHED, wash
    assert WASHED != RAW and RAW not in WASHED and FRAME not in WASHED, WASHED

    # 3. 洗过的文本落在台账那一行（递送从盘上读，不从返回值读）
    sign = _ledger_row(st)
    assert (sign.get("washed_relay") or {}).get("text") == WASHED, sign.get("washed_relay")

    # 4. 读侧读出来了
    text, details, problems, cond, out = _deliver(st)
    assert not problems, problems
    assert len(details) == 1, (text[:400], details)
    assert details[0].get("washed") == WASHED, details[0]

    # 5. F 侧：一项 notice/ack，detail 带着那个具体问题（逐字可回溯）
    assert out["checked"] is True and len(out["opened"]) == 1, out
    item = cond.items[0]
    detail = str(item.get("detail") or "")
    assert DEFECT in RAW and DEFECT in detail, detail
    assert WASHED in detail, f"洗过的那一份没有完整转到板上（detail 被截了？）：{detail}"

    # 6. 反面（负控）：同一份回复，秘书判 clean ⇒ 不洗、不递
    st2 = _ws(tmp_path / "clean")
    _put(st2)
    seam2 = _Seam({"v_reply_defect": [_axis(SEC.V_REPLY_CLEAN)]})
    _agent2, got2, _s2 = _ask_v(st2, seam2, REPLY_HOLDS)
    assert got2["secretary_judge"]["axis"] == "clean", got2["secretary_judge"]
    assert seam2.asked("wash_v_reply") == 0, "秘书判的是 clean，却仍然洗了稿"
    assert not (got2.get("wash_v_reply") or {}), got2.get("wash_v_reply")
    _text2, details2, _p2, cond2, out2 = _deliver(st2)
    assert details2 == [], details2
    assert out2["opened"] == [] and cond2.items == [], cond2.items


# ============================================================ e2：clean 不打扰 F

def test_e2_clean_does_not_touch_f_and_bumps_the_streak(tmp_path):
    """e2：V 说"我试了几种反例构造都失败，未发现问题" ⇒ 不发意见给 F；streak +1。

    两次 clean 各跑一次：0 -> 1 -> 2（`+1` 是这两次之间的差，不是"第一次就是 1"）。
    现有设计里没有"已通过"那一档板项（`deliver_v_verdicts` 只投"要 F 改"的意见），
    所以这一条的读数是"F 侧一个字节都没多"。
    """
    st = _ws(tmp_path)
    _put(st)
    seam = _Seam({"v_reply_defect": [_axis(SEC.V_REPLY_CLEAN)]})
    for i in (1, 2):
        _agent, got, _sec_obj = _ask_v(st, seam, REPLY_CLEAN)
        assert got["secretary_judge"]["axis"] == "clean", got["secretary_judge"]
        assert not (got.get("wash_v_reply") or {}), got.get("wash_v_reply")
        holds = VR.consecutive_holds(st.root, SID)
        assert holds["checked"] is True and holds["streak"] == i, holds
        text, details, problems, cond, out = _deliver(st)
        assert not problems, problems
        assert details == [], details
        assert out["checked"] is True and out["opened"] == [], out
        assert cond.items == [], cond.items
        # 文本是"名下没有被 V 判有毛病的证明"那一句（没有逐条行）；不按字面匹配整句，
        # 免得把措辞改一下也判红 —— 这一条量的是"没有明细行"。
        assert "- " not in text, text
    assert seam.asked("wash_v_reply") == 0


# ============================================================ e3：unsure 不冒充

def test_e3_unsure_is_neither_counted_nor_zeroed_and_never_reaches_f(tmp_path):
    """e3：V 的回复含糊（无尝试痕迹）⇒ 秘书判 unsure ⇒ 不计入、不清零、也不给 F 发意见。

    先攒一票 clean，再喂一条含糊的"成立"：连续次数必须停在 1。
    折成 clean ⇒ 2（冒充了一票）；折成 fault ⇒ 0（把已有的一票作废）。两个方向都被这一条钉住。
    """
    st = _ws(tmp_path)
    _put(st)
    seam = _Seam({"v_reply_defect": [_axis(SEC.V_REPLY_CLEAN), _axis(SEC.V_REPLY_UNSURE)]})
    agent = AgentV(st, workspace_root=st.root,
                   llm=_ReviewSeam(REPLY_CLEAN, REPLY_UNSURE), secretary=_sec(st, seam))
    first = agent.verify_proof(SID, proof_text=PROOF)
    assert first["secretary_judge"]["axis"] == "clean", first["secretary_judge"]
    assert VR.consecutive_holds(st.root, SID)["streak"] == 1
    second = agent.verify_proof(SID, proof_text=PROOF)
    assert second["checked"] is True, second
    assert second["secretary_judge"]["axis"] == "unsure", second["secretary_judge"]
    holds = VR.consecutive_holds(st.root, SID)
    assert holds["checked"] is True and holds["streak"] == 1, (
        f"unsure 改了票数（{holds['streak']}）⇒ 它被折成了 clean（2）或 fault（0）")
    # 台账上那一行照落（意见留痕），但没有洗稿、没有递送
    sign = _ledger_row(st)
    assert sign["verdict"] == "成立" and (sign.get("washed_relay") or {}) == {}, sign
    assert seam.asked("wash_v_reply") == 0
    _text, details, _problems, cond, out = _deliver(st)
    assert details == [] and out["opened"] == [] and cond.items == [], (details, cond.items)


# ============================================================ e4：F 收不到 V 原文

def test_e4_the_board_item_cannot_be_the_raw_reply_and_keeps_the_frozen_shape(tmp_path):
    """e4：板项 detail 与 V 原文不相等（洗稿的最低要求）；kind/expects 不许新造。

    同时钉住"洗过"与"没洗过"的读法：洗过的那一项必须写明它是洗过的转达；
    另一条（洗不出来）必须不写这句 —— 否则一次洗稿失败会静默变成一次转达。
    """
    st = _ws(tmp_path)
    _put(st)
    seam = _Seam({"v_reply_defect": [_axis(SEC.V_REPLY_FAULT)],
                  "wash_v_reply": [_wash_doc()]})
    _agent, got, _sec_obj = _ask_v(st, seam, REPLY_HOLDS)
    assert got["secretary_judge"]["axis"] == "fault", got["secretary_judge"]
    _text, details, _problems, cond, out = _deliver(st)
    assert out["opened"], out
    item = cond.items[0]
    detail = str(item.get("detail") or "")
    assert detail != RAW, "F 收到的就是 V 的原文"
    assert RAW not in detail, detail
    assert FRAME not in detail, f"第一人称那句被原样转达了：{detail}"
    assert DEFECT in detail, detail
    # 冻结面：kind / expects 只能是既有词表里的那两档，这一档不许新造
    assert item.get("kind") == "notice" and item.get("expects") == "ack", item
    assert item["kind"] in S.ITEM_KINDS and item["expects"] in S.ITEM_EXPECTS, item
    assert {str(r.get("kind") or "") for r in cond.items} <= {"notice"}, cond.items
    assert {str(r.get("expects") or "") for r in cond.items} <= {"ack"}, cond.items
    # "洗过"这件事在板上读得出来（不是长得像没洗过）
    assert "秘书洗过的转达" in detail, detail
    # 反真空：同一条链、洗不出来（findings 引不回原文）⇒ 不许递、更不许把原文递出去
    st2 = _ws(tmp_path / "refused")
    _put(st2)
    bad = {"text": WASHED,
           "findings": [{"quote": "第 4 步的引理用错了", "why": "夹具：原文里没有这一句"}]}
    seam2 = _Seam({"v_reply_defect": [_axis(SEC.V_REPLY_FAULT)], "wash_v_reply": [bad]})
    _a2, got2, _s2 = _ask_v(st2, seam2, REPLY_HOLDS)
    assert got2["secretary_judge"]["axis"] == "fault", got2["secretary_judge"]
    assert not (got2.get("wash_v_reply") or {}).get("washed"), got2.get("wash_v_reply")
    _t2, details2, problems2, cond2, out2 = _deliver(st2)
    assert details2 == [], details2
    assert problems2, "洗不出来这件事必须在读侧留一句（不是静默不投递）"
    assert out2["opened"] == [] and cond2.items == [], cond2.items


# ============================================================ e5：端到端的顺序

def test_e5_order_v_first_then_f_sees_the_washed_opinion(tmp_path):
    """e5：先喂 V 的意见，再断言 F 看得到；中间不许手工改盘绕过秘书。

    顺序在读数上分三段：
      ① V 那一签之前：板 0 项；
      ② `AgentV.verify_proof` 之后、投递之前：板仍然是 0 项（V 不写 F 的板）；
      ③ 读侧 + 投递之后：板 1 项，detail 里的那段文本与台账那一格的字节相同。
    反面：同样的命题、同样有证明、但没有 V 那一签 ⇒ 板上开不出项（这一项不可能
    凭空存在，它只能来自 V 的意见）。
    """
    st = _ws(tmp_path)
    _put(st)
    seam = _Seam({"v_reply_defect": [_axis(SEC.V_REPLY_FAULT)],
                  "wash_v_reply": [_wash_doc()]})
    cond = _Cond()          # 从第一刻起就在（V 那一步之后也还是它）
    assert cond.items == []

    # ① -> ②
    _agent, got, _sec_obj = _ask_v(st, seam, REPLY_HOLDS)
    assert got["checked"] is True, got
    assert cond.items == [], "V 那一步自己往 F 的板上写了东西"
    # ② 与 ③ 之间只做两件事：读侧（读台账）+ 投递（开板项）
    text, details, problems = AL.v_rejections_digest(st.root, [_row(st)])
    assert not problems, problems
    assert len(details) == 1, (text[:400], details)
    out = AL.deliver_v_verdicts(cond, task_id="t-000000000001", depth=1, role="F",
                                details=details)
    # ③
    assert out["checked"] is True and len(out["opened"]) == 1, out
    assert cond.opened_by == out["opened"], (cond.opened_by, out["opened"])
    sign = _ledger_row(st)
    item = cond.items[0]
    detail = str(item.get("detail") or "")
    assert (sign.get("washed_relay") or {}).get("text") == WASHED
    assert WASHED in detail, detail
    assert item.get("called_by") == "V", item.get("called_by")
    assert str(item.get("input_key") or "").startswith(AL.V_VERDICT_ITEM_PREFIX), item
    # 反面：没有 V 那一签 ⇒ 读侧没有明细，板上开不出项
    st2 = _ws(tmp_path / "no_v")
    _put(st2)
    _t2, details2, problems2 = AL.v_rejections_digest(st2.root, [_row(st2)])
    assert details2 == [] and not problems2, (details2, problems2)
    cond2 = _Cond()
    out2 = AL.deliver_v_verdicts(cond2, task_id="t-000000000001", depth=1, role="F",
                                 details=details2)
    assert out2["checked"] is True and out2["opened"] == [] and cond2.items == [], out2


# ============================================================ (C)：真工具入口

def test_c_tool_entry_reports_keys_its_declaration_does_not_promise(tmp_path, monkeypatch):
    """(C) 读数：`ToolRegistry.call("verify.verify_proof")` 的返回键 vs `returns=` 声明。

    已知缺口（`tools/verify_tools.py` 在 FC-27，本轮不许改）：声明里没有
    `secretary_judge` / `sign_issuance`。判据因此红的是
    `tests/test_tools_returns_declaration.py::test_no_tool_returns_a_top_level_key_it_does_not_declare`
    —— 它逐工具比对"实跑给了、声明没提"的顶层键。

    这一条把那个读数钉死：差集必须逐字等于那几格（下面三档各自写死）。等 FC-27 由人
    补上声明之后这里会红 —— 那时把三处断言改成各自应为的差集，这条钉子的使命就完成了。

    三档读数（都在同一个工具入口上取）：
      1. 没接线（`judge_not_wired` 那一支）⇒ 差集 = 秘书那两格；
      2. 接线、秘书判 clean 且票数不够 ⇒ 差集仍是那两格，而两格都带上了真读数
         （`secretary_judge.axis=clean`、`sign_issuance.checked=True`）；
      3. 接线、秘书判 fault ⇒ 差集多一格 `wash_v_reply`（那一格是 fault 支才写的，
         所以它只在实跑这一支上才看得见 —— 见 e1）。
    """
    st = _ws(tmp_path)
    _put(st)
    reg = build_registry(store=st, workspace_root=st.root, roles=("V",)).registry
    spec = reg.get("verify.verify_proof")
    declared = declared_keys(spec.returns)
    assert declared, "这条判据抽不到声明 ⇒ 差集永远是空集（真空通过）"
    got = reg.call("verify.verify_proof",
                   {"statement_id": SID, "proof_text": PROOF}, role="V")
    assert got.ok is True, got.error
    data = dict(got.data or {})
    keys = sorted(data)
    extra = [k for k in keys if k not in declared]
    # 三态：这一趟没有模型缝 ⇒ 走"没查成"那一支；键集合仍然完整（这是它能被比对的前提）
    assert data.get("checked") is False and data.get("reason") == "judge_not_wired", data
    assert extra == ["secretary_judge", "sign_issuance"], (
        f"返回键 {keys}；声明 {sorted(declared)}；差集 {extra}")

    # ---- 2. 接线之后：那两格带上真读数（活字段，不是空占位）
    def _factory(seam):
        def _make(role, *, root, store=None, **_kw):
            # `AgentV._secretary` 会把本工作区的 store 递进来（真装配的那条路）。
            return SEC.Secretary(str(role), root=pathlib.Path(root), store=store,
                                 seam=seam, enable_model=True)
        return _make

    st2 = _ws(tmp_path / "wired")
    _put(st2)
    reg2 = build_registry(store=st2, workspace_root=st2.root, roles=("V",)).registry
    clean_seam = _Seam({"v_reply_defect": [_axis(SEC.V_REPLY_CLEAN)]})
    monkeypatch.setattr(AV, "default_llm", lambda: _ReviewSeam(REPLY_CLEAN))
    monkeypatch.setattr(SEC, "for_role_wired", _factory(clean_seam))
    got2 = reg2.call("verify.verify_proof",
                     {"statement_id": SID, "proof_text": PROOF}, role="V")
    assert got2.ok is True, got2.error
    data2 = dict(got2.data or {})
    keys2 = sorted(data2)
    assert data2.get("checked") is True, data2
    assert data2["secretary_judge"].get("axis") == "clean", data2["secretary_judge"]
    assert data2["sign_issuance"].get("checked") is True, data2["sign_issuance"]
    assert [k for k in keys2 if k not in declared] == ["secretary_judge", "sign_issuance"], (
        f"返回键 {keys2}；声明 {sorted(declared)}")

    # ---- 3. fault 那一支：多一格 wash_v_reply（同一份声明缺口，只在实跑这一支可见）
    st3 = _ws(tmp_path / "fault")
    _put(st3)
    reg3 = build_registry(store=st3, workspace_root=st3.root, roles=("V",)).registry
    fault_seam = _Seam({"v_reply_defect": [_axis(SEC.V_REPLY_FAULT)],
                        "wash_v_reply": [_wash_doc()]})
    monkeypatch.setattr(AV, "default_llm", lambda: _ReviewSeam(REPLY_HOLDS))
    monkeypatch.setattr(SEC, "for_role_wired", _factory(fault_seam))
    got3 = reg3.call("verify.verify_proof",
                     {"statement_id": SID, "proof_text": PROOF}, role="V")
    assert got3.ok is True, got3.error
    data3 = dict(got3.data or {})
    keys3 = sorted(data3)
    assert data3.get("checked") is True, data3
    assert data3["secretary_judge"].get("axis") == "fault", data3["secretary_judge"]
    assert data3.get("wash_v_reply", {}).get("washed") is True, data3.get("wash_v_reply")
    assert [k for k in keys3 if k not in declared] == [
        "secretary_judge", "sign_issuance", "wash_v_reply"], (
        f"返回键 {keys3}；声明 {sorted(declared)}")

def test_e6_a_secretary_fault_still_names_the_step(tmp_path):
    """e6（2026-10-29 第 12 轮）：秘书判 fault 那一档，板上"第几步"不许写"步号没读到"。

    为什么会有这一条：V 的结论词写「成立」⇒ 台账行上没有 `defect_step`；而若 V 这次
    findings 是空的（只在那句 `why` 里点名"第 2 步"），读侧原本只能写"步号没读到"——
    可步号就在秘书洗过的文本里。这条钉兜底：读洗过的文本，不读模型的自觉。
    """
    st = _ws(tmp_path)
    _put(st)
    seam = _Seam({"v_reply_defect": [_axis(SEC.V_REPLY_FAULT)],
                  "wash_v_reply": [_wash_doc()]})
    reply = json.dumps({"verdict": "成立", "defect_step": None, "why": RAW,
                        "findings": []}, ensure_ascii=False)
    _ask_v(st, seam, reply)
    row = _ledger_row(st)
    assert row["verdict"] == "成立", row
    assert not (row.get("findings") or []), row
    _text, details, _problems = AL.v_rejections_digest(st.root, [_row(st)])
    faulted = [d for d in details if d.get("via") == "secretary_fault"]
    assert faulted, details
    assert faulted[0].get("defect_step") == 2, faulted[0]

# -*- coding: utf-8 -*-
"""业主 2026-10-30：「连续 3 次没问题」是 V 判完接着再判，不是 F 提交三次。

口径逐字（第一次，2026-10-30 上午）：

    「V 所谓连续 3 次『没问题』，是 V 判没问题后连续再判，不是 F 提交 3 次 V 过 3 次。
      毕竟没问题的判决没必要给 F。有毛病要给 F 知道叫它改正。这块 V 秘书要做好」

## 2026-10-30 第二次裁定（本次唯一权威，逐字）

    「没有什么『还没够』，连判里面如果判出一回秘书语义分析认为是『有毛病』的，
      则直接打回了，连判终止」

于是连判的终局只有两种，没有第三种：

1. 连续 `VR.SIGN_STREAK_NEED` 转 clean ⇒ 秘书发签（现状已对）；
2. 任一转秘书语义判定判出 `fault`（有毛病）⇒ 「立刻终止」：这一转就是终局，台账那
   一行就是打回给 F 的那一条（`via=secretary_fault`，递的是洗过的转达）。`unsure`
   （判不了）同样终止并打回，理由码与 fault 分开（`via=secretary_unsure`，读数里写
   "需要补材料或重交"）；V 自己的结论不是「成立」那一档也立刻停（本身就是打回）。

"循环跑完而既没签也没打回"不是一条终局：只可能是配置病态（门槛被改成 0 / 负数），
那时返回值报内部不一致（`checked=False` + 明确 reason），不许写成"次数没到"。
上界因此「动态等于门槛」（`VR.SIGN_STREAK_NEED` 现读）：要么签、要么打回，逻辑上必然命中。

五条要求 → 五条判据（全部先红后绿）：

| 编号 | 它要证明的事 | 改前怎么红 | 什么改动会让它红回去 |
|---|---|---|---|
| t1 | 一次 `verify_proof` 自己判三次 clean ⇒ 台账恰好 3 行、秘书发签、位翻上去；F 那一侧一条都没有 | 一次调用只问一次模型（台账 1 行、不签） | 把循环摘掉 / 让 clean 也开板项 |
| t2 | 第 2 次判 fault ⇒ 立刻停（2 行、不签），洗过的那一份能读出 `via=secretary_fault` | fault 那一转之后还接着问第三问 | fault 之后接着判 / 洗稿没落进台账 |
| t3 | 上界动态等于门槛：门槛 1 ⇒ 判 1 次就签；门槛 5 ⇒ 判满 5 次、第 5 次签上 | 上界是导入期的常量（门槛 5 时判到 3 就停、如实不签 = 业主否掉的终局） | 上界与门槛又分成两个数 / 判不满也签 |
| t4 | 第 2 转判 `unsure` ⇒ 2 行、不签、立刻停，读侧是「另一档」明细（`via=secretary_unsure`） | unsure 之后不进读侧明细（或与 fault 混成一档） | 把 unsure 折成 clean / 折成 fault / 留成"次数没到" |
| t5 | `agent_v/core.py` 与 `verifications.py` 的返回值/读数/docstring 里"还没够 / 还不够 / 未达门槛"一处都不剩 | 那三种措辞还留在连判读数与 `sign_issuance.reason` 里 | 任何一处重新写回这类终局 |

## 为什么"F 那一侧一条都没有"要读 `v_rejections_digest`

`verify_proof` 这条链不经过 conductor（立法与洗稿都在秘书侧，投递才用板），
所以"有没有打扰 F"只能从读侧量：那一格是 F 唯一会看到的入口
（`agent_loop.deliver_v_verdicts` 拿的就是它的明细）。t1 两条都断言：
digest 的明细为空，且投递那一步一个板项都不开（替身只记 `open_item`）。

## 这些替身各自量的是什么（别把它们当成"真模型跑过"）

V 的审阅缝（`_ReviewSeam`）逐个交出预置回复并按次数计数；秘书的缝（`_Seam`）
按 `note` 分类回预置 JSON。它们证明的是"这条链会不会自己再问一次、每一问落在哪个
分支"，不证明模型的判断质量。真模型那一路在本文件里一次都不发。
"""
from __future__ import annotations

import json
import pathlib

from agentflow import agent_loop as AL
from agentflow import evidencebits as EB
from agentflow import secretary as SEC
from agentflow import verifications as VR
from agentflow.agent_v import AgentV
from agentflow.store import Store

TS = "2026-10-30T00:00:00+08:00"
SID = "000007"
PROOF = "1. 取 G = C_n（n ≥ 3）：它是 2-正则、围长为 n。\n2. 由第 1 步直接得到结论。"
FULL = "设 G 是 3-正则群；则弦长函数不是常值。"

#: 一次 clean 的审阅回复（三档里「没问题」那一档的原料：结论写成立、没指出缺陷）。
CLEAN_REPLY = json.dumps({"verdict": "成立", "why": "试了几种反例构造都失败，未发现问题。",
                          "findings": []}, ensure_ascii=False)
#: 第 2 次的回复：结论词仍写「成立」，但正文里点出了一处缺陷（秘书那一档才判得出 fault）。
FAULT_REPLY = json.dumps({"verdict": "成立", "why": "整体能走通；只是第 2 步的记号没有定义。",
                          "findings": []}, ensure_ascii=False)
#: 洗过的那一份（转达给 F 的唯一形态）：它必须能逐字落回 V 的回复，且点名第 2 步。
WASHED = "第 2 步的记号没有定义：请补上记号说明之后再送 V 重签。"


# ------------------------------------------------------------------ 夹具

def _ws(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _put(store: Store) -> dict:
    """落一条在册命题（走真事务；夹具只造这一行）。"""
    row = {
        "stmt_id": SID, "origin": "own_result", "kind": "theorem",
        "label": "弦长函数非常值", "statement_full": FULL,
        "statement_text": "弦长函数不是常值", "proof_text": PROOF,
        "evidence_kind": "heuristic", "status": "active",
        "quote_verified": None, "quote_reason": "自产命题，没有外部引文要比对",
        "created_at": TS, "created_by": "test",
        "bits": EB.bits_of(proof=True, proof_process=PROOF, kind="theorem"),
    }
    with store.tx("statements", actor="test") as tx:
        tx.upsert("statements", row)
    return row


def _stmt_row(store: Store) -> dict:
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


class _ReviewSeam:
    """V 自己的审阅缝：按顺序交出预置回复，并记下每一次真的问过的提示词。"""

    wired = True

    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)
        self.prompts: list[str] = []

    def ask(self, prompt: str = "", **_kw) -> _Call:
        self.prompts.append(prompt)
        text = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        call = _Call()
        call.text = text
        call.ok = True
        return call

    def asked(self) -> int:
        return len(self.prompts)


class _Seam:
    """秘书的缝：按 `note`（`secretary:<kind>`）回一份预置 JSON，并记下问过什么。"""

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


def _axis(answer: str) -> dict:
    """秘书那一路的判定（`judge` 的返回形状：checked + decision）。"""
    return {"checked": True, "decision": answer, "reason": "夹具：照规则判",
            "basis": ["夹具"]}


def _secretary(st: Store, seam: _Seam) -> SEC.Secretary:
    return SEC.Secretary("V", root=st.root, store=st, seam=seam, enable_model=True)


class _BoardDouble:
    """只记 `open_item` 的 conductor 替身：断言"一条板项都没开"用它量。"""

    def __init__(self) -> None:
        self.opened: list[dict] = []
        self.details: list[dict] = []

    def open_item(self, *args, **kwargs):
        self.opened.append({"args": args, "kwargs": kwargs})
        return {"item_id": "i-000001"}

    def set_item_detail(self, *args, **kwargs):
        self.details.append({"args": args, "kwargs": kwargs})
        return True

    def _board_rows(self) -> list:
        return []

    def open_items_of(self, task_id: str) -> list:
        return []


def _rows(st: Store) -> list[dict]:
    rows, bad = VR.list_verifications(st.root, statement_id=SID, limit=None)
    assert not bad, bad
    return [dict(r) for r in rows]


# ============================================================ t1：一次调用判三次

def test_t1_one_call_reviews_three_times_then_the_secretary_signs(tmp_path):
    """一次 `verify_proof`：三次 clean ⇒ 台账恰好 3 行、秘书发签、位翻上去、F 零打扰。

    反真空：三次都是真的问过模型（`asked() == 3`），且三次盖的是同一份正文
    （同一个 `proof_sha256` / 同一个 `proof_no`）；三次的提示词逐字同前缀
    （"第几次"只加在末尾，不改稳定前缀）。
    """
    st = _ws(tmp_path)
    _put(st)
    review = _ReviewSeam([CLEAN_REPLY])
    sec_seam = _Seam({"v_reply_defect": [_axis(SEC.V_REPLY_CLEAN)],
                      "sign_issuance": [_axis(SEC.SIGN_ISSUE)]})
    agent = AgentV(st, workspace_root=st.root, llm=review,
                   secretary=_secretary(st, sec_seam))

    got = agent.verify_proof(SID, proof_text=PROOF)

    # 这一次调用真的自己问了三次模型（不是 F 又提交了三次）。
    assert review.asked() == 3, (
        f"一次 `verify_proof` 只问了 {review.asked()} 次模型 ⇒ "
        "「连续 3 次」还是靠 F 反复提交")
    passes = got.get("review_passes") or []
    assert [p["pass"] for p in passes] == [1, 2, 3], passes
    assert [p["axis"] for p in passes] == ["clean"] * 3, passes
    assert [p["streak"] for p in passes] == [1, 2, 3], passes
    assert [p["decision"] for p in passes] == [SEC.SIGN_WITHHOLD,
                                               SEC.SIGN_WITHHOLD,
                                               SEC.SIGN_ISSUE], passes
    # 稳定前缀：第 2、3 次只是把提示词接在前面那一次后面，system/前缀一个字节没动。
    assert review.prompts[1].startswith(review.prompts[0]), (
        "第 2 次的提示词把前面的稳定前缀改了（次数被写进了前缀）")
    assert review.prompts[2].startswith(review.prompts[0]), review.prompts[2][:200]

    rows = _rows(st)
    assert len(rows) == 3, f"台账应当恰好 3 行（三次真正的审阅），实得 {len(rows)}"
    assert {r["proof_sha256"] for r in rows} == {VR.proof_sha(PROOF)}, (
        "三次判的不是同一份正文 ⇒ sha 段漂了")
    assert {VR.proof_no_of(r) for r in rows} == {1}, rows
    assert len({r["verification_id"] for r in rows}) == 3, rows

    assert got["signed_bit3"] is True, got["sign_issuance"]
    assert got["bits"]["reviewed"] is True, got["bits"]
    assert got["sign_issuance"]["issued"] is True, got["sign_issuance"]
    assert _stmt_row(st)["bits"]["reviewed"] is True, _stmt_row(st)["bits"]

    # clean 那一档一条都不许递到 F：读侧明细为空，投递那一步一个板项都不开。
    text, details, problems = AL.v_rejections_digest(st.root, [_stmt_row(st)])
    assert problems == [], problems
    assert details == [], f"clean 的三签读出了要递到 F 的明细：{details}"
    board = _BoardDouble()
    delivered = AL.deliver_v_verdicts(board, task_id="t-000001", depth=0,
                                      details=details)
    assert board.opened == [], f"clean 那一档开了板项：{board.opened}"
    assert delivered.get("opened") == [], delivered
    assert "没有被 V 判" in text, text


# ============================================================ t2：第 2 次 fault 就停

def test_t2_a_fault_on_the_second_pass_stops_and_is_washed_to_f(tmp_path):
    """第 2 次判 fault ⇒ 立刻停：台账 2 行、不签、洗过的那份读得出 `via=secretary_fault`。

    它同时钉住两件事：① fault 之后不许再问第三次（否则会把"停"变成"再给一次机会"，
    而缺陷已经点名了）；② 洗稿那一份必须真的落进台账——不然读侧要么读不到（F 收不到），
    要么只能读到 V 的原文（洗稿等于没做）。
    """
    st = _ws(tmp_path)
    _put(st)
    review = _ReviewSeam([CLEAN_REPLY, FAULT_REPLY])
    sec_seam = _Seam({"v_reply_defect": [_axis(SEC.V_REPLY_CLEAN),
                                         _axis(SEC.V_REPLY_FAULT)],
                      "wash_v_reply": [{"text": WASHED, "step": 2,
                                        "findings": [{"quote": "第 2 步的记号没有定义",
                                                      "why": "记号没有定义就没法核这一步"}]}],
                      "sign_issuance": [_axis(SEC.SIGN_ISSUE)]})
    agent = AgentV(st, workspace_root=st.root, llm=review,
                   secretary=_secretary(st, sec_seam))

    got = agent.verify_proof(SID, proof_text=PROOF)

    assert review.asked() == 2, (
        f"第 2 次已经判了 fault，却又问了 {review.asked()} 次模型 ⇒ 「立刻停」没做到")
    passes = got.get("review_passes") or []
    assert [p["axis"] for p in passes] == ["clean", "fault"], passes
    assert [p["streak"] for p in passes] == [1, 0], passes
    rows = _rows(st)
    assert len(rows) == 2, f"台账应当 2 行，实得 {len(rows)}"
    assert got["secretary_judge"]["axis"] == "fault", got["secretary_judge"]
    assert got["signed_bit3"] is False and got["bits"].get("reviewed") is not True, got
    assert got["sign_issuance"]["issued"] is False, got["sign_issuance"]
    assert _stmt_row(st)["bits"]["reviewed"] is False, _stmt_row(st)["bits"]
    # 洗稿真的问过一次，且洗过的那一份落进了台账那一行。
    assert sec_seam.asked("wash_v_reply") == 1, sec_seam.seen
    assert rows[-1]["washed_relay"]["text"] == WASHED, rows[-1].get("washed_relay")
    # 这一转就是终局：连判在它这里断掉（不是"再给一次机会"），读数里说得出来。
    assert passes[-1].get("terminal") == "fault", passes
    assert "终局" in got["sign_issuance"]["reason"], got["sign_issuance"]["reason"]
    assert "还差" not in got["sign_issuance"]["reason"], got["sign_issuance"]["reason"]

    _text, details, _problems = AL.v_rejections_digest(st.root, [_stmt_row(st)])
    faults = [d for d in details if d.get("via") == "secretary_fault"]
    assert len(faults) == 1, f"读侧没有读出那条 fault 明细：{details}"
    assert faults[0]["washed"] == WASHED, faults[0]
    assert faults[0]["verdict"] == "成立", (
        "这一档 V 自己的结论词就是「成立」，不许被读成「V 判有毛病」")
    assert faults[0]["steps"] == [2], faults[0]
    # 递到 F 的那一项里写的是洗过的那份，不是 V 的原文。
    board = _BoardDouble()
    delivered = AL.deliver_v_verdicts(board, task_id="t-000001", depth=0,
                                      details=faults)
    assert delivered.get("problems") == [], delivered
    assert len(board.opened) == 1, board.opened
    assert FAULT_REPLY not in json.dumps(board.opened, ensure_ascii=False), (
        "递到 F 的板项里出现了 V 的原文（洗过的那一份没被用）")


# ============================================================ t3：上界 = 门槛

def test_t3_the_pass_bound_is_the_threshold_itself(tmp_path, monkeypatch):
    """门槛 1 ⇒ 判 1 次就签；门槛 5 ⇒ 判满 5 次、第 5 次签上。

    这一条是负控：把门槛临时打成别的数，看"判几次"是不是真的跟着门槛走。
    - 门槛 1：第一问就够 ⇒ 只许问 1 次（多问就是白花钱，也说明停的条件没接上）；
    - 门槛 5：一次调用的上界「动态等于门槛」（`VR.SIGN_STREAK_NEED` 现读）⇒ 判满
      5 次、台账 5 行、第 5 次签上。

    改前（上一版）这里断言的是"判到上界（3）停住、如实不签"——那条断言的终局正是
    业主本次裁定否掉的东西（逐字：「没有什么『还没够』」），所以跟着掉头：
    "判到上界停住" 与 "判满门槛签上" 之间，现在只剩后者。
    """
    # (a) 门槛 1：一问即够。
    st = _ws(tmp_path / "a")
    _put(st)
    review = _ReviewSeam([CLEAN_REPLY])
    sec_seam = _Seam({"v_reply_defect": [_axis(SEC.V_REPLY_CLEAN)],
                      "sign_issuance": [_axis(SEC.SIGN_ISSUE)]})
    agent = AgentV(st, workspace_root=st.root, llm=review,
                   secretary=_secretary(st, sec_seam))
    monkeypatch.setattr(VR, "SIGN_STREAK_NEED", 1)
    got = agent.verify_proof(SID, proof_text=PROOF)
    assert review.asked() == 1, (
        f"门槛 1 时问了 {review.asked()} 次模型 ⇒ 停的条件没跟着门槛走")
    assert len(got.get("review_passes") or []) == 1, got.get("review_passes")
    assert len(_rows(st)) == 1, _rows(st)
    assert got["sign_issuance"]["issued"] is True, got["sign_issuance"]
    assert got["signed_bit3"] is True, got["bits"]
    # (b) 门槛 5：上界跟着门槛走 ⇒ 判满 5 次、第 5 次签上（不是判到 3 就停）。
    st2 = _ws(tmp_path / "b")
    _put(st2)
    review2 = _ReviewSeam([CLEAN_REPLY])
    sec_seam2 = _Seam({"v_reply_defect": [_axis(SEC.V_REPLY_CLEAN)],
                       "sign_issuance": [_axis(SEC.SIGN_ISSUE)]})
    agent2 = AgentV(st2, workspace_root=st2.root, llm=review2,
                    secretary=_secretary(st2, sec_seam2))
    monkeypatch.setattr(VR, "SIGN_STREAK_NEED", 5)
    got2 = agent2.verify_proof(SID, proof_text=PROOF)
    passes = got2.get("review_passes") or []
    assert len(passes) == 5, f"门槛 5 时判了 {len(passes)} 次 ⇒ 上界没有等于门槛"
    assert review2.asked() == 5, (review2.asked(), passes)
    assert [p["streak"] for p in passes] == [1, 2, 3, 4, 5], passes
    assert [p["issue"] for p in passes] == [False, False, False, False, True], passes
    assert len(_rows(st2)) == 5, f"台账应当 5 行（每一转各一行），实得 {len(_rows(st2))}"
    assert got2["sign_issuance"]["streak_ok"] is True, got2["sign_issuance"]
    assert got2["sign_issuance"]["issued"] is True, got2["sign_issuance"]
    assert got2["signed_bit3"] is True and got2["bits"]["reviewed"] is True, got2
    assert _stmt_row(st2)["bits"]["reviewed"] is True, _stmt_row(st2)["bits"]
    # 终局是"签上"，不是"次数没到"：两格读数都这么说。
    assert passes[-1].get("terminal") == "signed", passes
    assert "还差" not in got2["sign_issuance"]["reason"], got2["sign_issuance"]
    # (c) 病态配置：门槛打成 0 ⇒ 连判一转都跑不了、既没签也没打回 ⇒ 内部不一致
    #     （不是"次数没到"那种收尾，也不是"审过了"）。这是那条兜底分支的唯一判据。
    st3 = _ws(tmp_path / "c")
    _put(st3)
    review3 = _ReviewSeam([CLEAN_REPLY])
    sec_seam3 = _Seam({"v_reply_defect": [_axis(SEC.V_REPLY_CLEAN)],
                       "sign_issuance": [_axis(SEC.SIGN_ISSUE)]})
    agent3 = AgentV(st3, workspace_root=st3.root, llm=review3,
                    secretary=_secretary(st3, sec_seam3))
    monkeypatch.setattr(VR, "SIGN_STREAK_NEED", 0)
    got3 = agent3.verify_proof(SID, proof_text=PROOF)
    assert review3.asked() == 0, (
        f"门槛 0 时仍然问了 {review3.asked()} 次模型 ⇒ 上界没有跟着门槛走")
    assert got3["review_passes"] == [], got3["review_passes"]
    assert _rows(st3) == [], "门槛 0 时落了台账行 ⇒ 判据前提被破坏"
    assert got3["checked"] is False, got3
    assert str(got3["reason"]).startswith("internal_inconsistency"), got3["reason"]
    assert "还差" not in str(got3["reason"]), got3["reason"]
    assert got3["signed_bit3"] is False and got3["bits"] == {}, got3
    assert _stmt_row(st3)["bits"]["reviewed"] is False, _stmt_row(st3)["bits"]


# ============================================================ t4：unsure 也终止并打回

#: 第 2 转的回复：含糊（没有尝试痕迹），秘书那一档才判得出「判不了」。
UNSURE_REPLY = json.dumps({"verdict": "成立", "why": "我觉得没问题。", "findings": []},
                          ensure_ascii=False)


def test_t4_an_unsure_pass_ends_the_run_and_goes_back_as_unsure(tmp_path):
    """第 2 转秘书判「判不了」（unsure）⇒ 2 行、不签、立刻停，读侧是另一档明细。

    口径（业主 2026-10-30 本次裁定第三条）：unsure 既不是 clean 也不是 fault，但也不许
    被写成"次数没到"——它同样终止连判并打回 F：板项/读数里如实写"秘书判不了这一条
    （需要补材料或重交）"，理由码与 fault 那一档「分开」（`via=secretary_unsure`，
    fault 是"有毛病"，unsure 是"没判出来"；两种都要 F 知道，但理由码不同）。

    反真空（本用例同时钉住"分开"这件事）：`via` 必须是 `secretary_unsure` 而不是
    `secretary_fault`；板项措辞必须说"判不了"，而不是"V 判有毛病"。
    """
    st = _ws(tmp_path)
    _put(st)
    # 第 3 问的回复故意还留着（含糊那份）——若实现没停，它会真的被问第三次。
    review = _ReviewSeam([CLEAN_REPLY, UNSURE_REPLY])
    sec_seam = _Seam({"v_reply_defect": [_axis(SEC.V_REPLY_CLEAN),
                                         _axis(SEC.V_REPLY_UNSURE)]})
    agent = AgentV(st, workspace_root=st.root, llm=review,
                   secretary=_secretary(st, sec_seam))

    got = agent.verify_proof(SID, proof_text=PROOF)

    assert review.asked() == 2, (
        f"第 2 转已经判不了，却又问了 {review.asked()} 次模型 ⇒ 「立刻终止」没做到")
    passes = got.get("review_passes") or []
    assert [p["axis"] for p in passes] == ["clean", "unsure"], passes
    # unsure 不清零、也不计入：第 2 转的连续次数仍是第 1 转的 1（不是 2、也不是 0）。
    assert [p["streak"] for p in passes] == [1, 1], passes
    assert passes[-1].get("terminal") == "unsure", passes
    rows = _rows(st)
    assert len(rows) == 2, f"台账应当 2 行，实得 {len(rows)}"
    assert rows[-1]["secretary_judge"]["axis"] == "unsure", rows[-1]["secretary_judge"]
    assert got["secretary_judge"]["axis"] == "unsure", got["secretary_judge"]
    assert got["signed_bit3"] is False and got["bits"].get("reviewed") is not True, got
    assert got["sign_issuance"]["issued"] is False, got["sign_issuance"]
    assert "终局" in got["sign_issuance"]["reason"], got["sign_issuance"]["reason"]
    assert "还差" not in got["sign_issuance"]["reason"], got["sign_issuance"]["reason"]
    # 判不了不洗稿：洗过的那一格没有内容（洗稿只属于 fault 那一档）。
    assert not (rows[-1].get("washed_relay") or {}), rows[-1].get("washed_relay")
    assert _stmt_row(st)["bits"]["reviewed"] is False, _stmt_row(st)["bits"]

    # 读侧：一条明确的明细，理由码与 fault 分开。
    text, details, problems = AL.v_rejections_digest(st.root, [_stmt_row(st)])
    assert problems == [], problems
    assert len(details) == 1, (text[:400], details)
    detail = details[0]
    assert detail["via"] == "secretary_unsure", detail
    assert detail["via"] != "secretary_fault", detail
    assert "判不了" in text, text
    assert "判「有毛病」" not in text, text

    # 板项：一项，措辞是"判不了 / 需要补材料或重交"，不是"V 判有毛病"。
    board = _BoardDouble()
    delivered = AL.deliver_v_verdicts(board, task_id="t-000001", depth=0,
                                      details=details)
    assert delivered.get("checked") is True, delivered
    assert delivered.get("problems") == [], delivered
    assert len(board.opened) == 1, board.opened
    summary = str(board.opened[0]["kwargs"].get("summary") or "")
    assert "判不了" in summary, summary
    assert "判「有毛病」" not in summary, summary
    body = str(board.details[0]["args"][1]) if board.details else ""
    assert "判不了" in body, body
    assert "秘书洗过的转达" not in body, (
        "判不了那一档没有洗过的文本 ⇒ 板项不许长得像「洗过的转达」")


# ============================================================ t5：措辞判据（防回归）

#: 业主 2026-10-30 否掉的终局措辞：这三种写法只描述"还差多少次"，而连判的终局只有
#: 两种（签 / 打回）—— 它们一旦回到返回值、读数或 docstring 里，读者就会把「打回」
#: 读成「再多判几次就好」，而这正是本次裁定取消的东西。
NOT_ENOUGH_WORDING = ("还没够", "还不够", "未达门槛")
#: 允许的历史注释白名单。「刻意为空」：这一条量的是"这三个词一处都不剩"；白名单一旦
#: 有内容，判据就退化成"只剩白名单外的那几处"（而历史注释正是最容易被整批豁免的一档）。
NOT_ENOUGH_ALLOWED: tuple[tuple[str, str], ...] = ()


def test_t5_no_not_enough_wording_survives_in_the_readings():
    """`agent_v/core.py` 与 `verifications.py` 里那三种"还差次数"的终局措辞一处不留。

    为什么扫源码而不是只扫返回值：返回值只覆盖跑得到的分支，而措辞最容易留在
    docstring / 注释里（那正是下一次改动会照着抄的模板）。
    """
    src = pathlib.Path(VR.__file__).resolve().parent
    targets = {"agent_v/core.py": src / "agent_v" / "core.py",
               "verifications.py": src / "verifications.py"}
    assert NOT_ENOUGH_ALLOWED == (), "白名单只许为空（见上面的理由）"
    scanned: dict[str, str] = {}
    for name, path in targets.items():
        assert path.is_file(), f"{name} 不在盘上：{path}"
        text = path.read_text(encoding="utf-8")
        assert text.strip(), f"{name} 是空的 ⇒ 判据扫不到东西（假绿）"
        scanned[name] = text
    # 反真空：这两份源码确实带着本批改过的那几格（扫错文件会假绿）。
    assert "verify_proof" in scanned["agent_v/core.py"], "扫的不是 V 的实现"
    assert "consecutive_holds" in scanned["verifications.py"], "扫的不是台账读数"
    hits = [f"{name}:{i}:{word}:{line.strip()[:80]}"
            for name, text in scanned.items()
            for word in NOT_ENOUGH_WORDING
            for i, line in enumerate(text.splitlines(), start=1)
            if word in line]
    assert hits == [], (
        "连判的终局只剩「签 / 打回」两种，这几种措辞不许再出现：\n" + "\n".join(hits))


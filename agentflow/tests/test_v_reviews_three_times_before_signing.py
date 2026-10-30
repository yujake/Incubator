# -*- coding: utf-8 -*-
"""业主 2026-10-30：「连续 3 次没问题」是 V 判完接着再判，不是 F 提交三次。

口径逐字（本次唯一权威）：

    「V 所谓连续 3 次『没问题』，是 V 判没问题后连续再判，不是 F 提交 3 次 V 过 3 次。
      毕竟没问题的判决没必要给 F。有毛病要给 F 知道叫它改正。这块 V 秘书要做好」

三条要求 → 三条判据（全部先红后绿）：

| 编号 | 它要证明的事 | 改前怎么红 | 什么改动会让它红回去 |
|---|---|---|---|
| t1 | 一次 `verify_proof` 自己判三次 clean ⇒ 台账恰好 3 行、秘书发签、位翻上去；F 那一侧一条都没有 | 一次调用只问一次模型（台账 1 行、不签） | 把循环摘掉 / 让 clean 也开板项 |
| t2 | 第 2 次判 fault ⇒ 立刻停（2 行、不签），洗过的那一份能读出 `via=secretary_fault` | 一次调用没有第 2 次 | fault 之后接着判 / 洗稿没落进台账 |
| t3 | 门槛打到 1 ⇒ 只判 1 次就签；打到 5 ⇒ 在上界之内停住、如实不签 | 「判几次」与门槛无关（恒 1 次） | 上界跟着门槛长 / 不够也签 |

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


# ============================================================ t3：上界与门槛分开

def test_t3_the_threshold_and_the_pass_bound_are_two_different_numbers(tmp_path,
                                                                     monkeypatch):
    """门槛 1 ⇒ 判 1 次就签；门槛 5 ⇒ 在"上界"之内停住，如实不签（不许假装签上）。

    这一条是负控：把门槛临时打成别的数，看"判几次"是不是还老实。
    - 门槛 1：第一问就够 ⇒ 只许问 1 次（多问就是白花钱，也说明停的条件没接上）；
    - 门槛 5：一次调用有一个上界（不是"追到够为止"）⇒ 问到上界就停、台账如数落行、
      发签那几格如实说"不够"，位一个字节都不许动。
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
    # (b) 门槛 5：一次调用判不到 5 次 clean，于是它必须停在某个上界并如实说"不够"。
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
    assert 1 < len(passes) <= VR.SIGN_STREAK_NEED, (
        f"门槛 5 时判了 {len(passes)} 次 ⇒ 要么没继续判，要么上界跟着门槛长")
    assert review2.asked() == len(passes), (review2.asked(), passes)
    assert len(_rows(st2)) == len(passes), (
        f"台账 {len(_rows(st2))} 行 ≠ 判了 {len(passes)} 次 ⇒ 有一问没落行")
    assert got2["sign_issuance"]["streak_ok"] is False, got2["sign_issuance"]
    assert got2["sign_issuance"]["issued"] is False, got2["sign_issuance"]
    assert got2["signed_bit3"] is False and got2["bits"].get("reviewed") is not True, got2
    assert _stmt_row(st2)["bits"]["reviewed"] is False, _stmt_row(st2)["bits"]
    assert "还差" in got2["sign_issuance"]["reason"], got2["sign_issuance"]["reason"]

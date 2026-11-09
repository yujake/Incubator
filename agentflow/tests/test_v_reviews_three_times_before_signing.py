# -*- coding: utf-8 -*-
"""业主 2026-10-30：「连续 3 次没问题」是 V 判完接着再判，不是 F 提交三次。

口径逐字（第一次，2026-10-30 上午）：

    「V 所谓连续 3 次『没问题』，是 V 判没问题后连续再判，不是 F 提交 3 次 V 过 3 次。
      毕竟没问题的判决没必要给 F。有毛病要给 F 知道叫它改正。这块 V 秘书要做好」

## 2026-10-30 第二次裁定（仍有效，逐字）

    「没有什么『还没够』，连判里面如果判出一回秘书语义分析认为是『有毛病』的，
      则直接打回了，连判终止」

于是连判的终局只有两种，没有第三种：

1. 连续 `VR.SIGN_STREAK_NEED` 转 clean ⇒ 秘书发签；
2. 任一转秘书语义判定判出 `fault`（有毛病）⇒ 「立刻终止」：这一转就是终局，台账那
   一行就是打回给 F 的那一条（`via=secretary_fault`，递的是洗过的转达）；V 自己的
   结论不是「成立」那一档也立刻停（本身就是打回）。

"循环跑完而既没签也没打回"不是一条终局：只可能是配置病态（门槛被改成 0 / 负数），
那时返回值报内部不一致（`checked=False` + 明确 reason），不许写成"次数没到"。
上界因此「动态等于门槛」（`VR.SIGN_STREAK_NEED` 现读）：要么签、要么打回，逻辑上必然命中。

## 2026-10-30 第三次裁定（推翻"判不了"那一档，逐字）

    「不可能有判不了。你告诉我啥叫判不了？只要不是完全没毛病都叫有毛病」

于是：① 秘书的语义判定只有两档（clean / fault），拿不准、只挑出一处小记号问题、
只说"我没逐行验证"——统统算 fault（题面只给两档；词表里也只有两格，模型若仍答历史
那一格就按"不采信"处理 ⇒ `checked=False`，不会被折成第三种结论）；
② 历史台账行里的 unsure 只作历史兼容读（读得出、新产生的一律没有它）；
③ 「没查成」不是判定：秘书问不出来 / 输出不合法 / 台账写不进去 ⇒ 终止 + `checked=False`
+ 明确 reason，不许当成 fault 打回，也不许说"次数没到"。

六条要求 → 六条判据（全部先红后绿）：

| 编号 | 它要证明的事 | 改前怎么红 | 什么改动会让它红回去 |
|---|---|---|---|
| t1 | 一次 `verify_proof` 自己判三次 clean ⇒ 台账恰好 3 行、秘书发签、位翻上去；F 那一侧一条都没有 | 一次调用只问一次模型（台账 1 行、不签） | 把循环摘掉 / 让 clean 也开板项 |
| t2 | 第 2 次判 fault ⇒ 立刻停（2 行、不签），洗过的那一份能读出 `via=secretary_fault` | fault 那一转之后还接着问第三问 | fault 之后接着判 / 洗稿没落进台账 |
| t3 | 上界动态等于门槛：门槛 1 ⇒ 判 1 次就签；门槛 5 ⇒ 判满 5 次、第 5 次签上；门槛 0 ⇒ 内部不一致 | 上界是导入期的常量（门槛 5 时判到 3 就停、如实不签 = 业主否掉的终局） | 上界与门槛又分成两个数 / 判不满也签 |
| t4 | 第 2 转是含糊的一段话 ⇒ 判成 `fault`（不是 unsure、不是 clean）⇒ 立刻停、打回、洗过的意见到 F；答历史那一格 ⇒ 不采信（没有第三种结论） | 题面又给三档 / 把"判不了"折成一种结论 / 含糊被折成 clean | 题面或词表里出现第三格 / 不采信被折成 fault 或 clean |
| t5 | 秘书问不出来（缝 `ok=False`）⇒ `checked=False`、终止、不签、不打回，reason 说清没查成 | 把"没查成"当成 fault 打回，或当成 clean 放过去 | 没查成那一档又折回任何一档判定 |
| t6 | `src/` 里：三种"还差次数"的终局措辞一处不剩（V 那一链的四份源码）；`unsure` 每一处都写明「只作历史兼容读」，且写侧结构上产生不出它 | 那三种措辞还在连判读数里；或"判不了"又被当成一种结论写进台账 | 任何一处写回这类终局 / 写侧又能产生 unsure |

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
from agentflow import conductor as CND
from agentflow import evidencebits as EB
from agentflow import secretary as SEC
from agentflow import verifications as VR
from agentflow import vsigns as VS
from agentflow.agent_v import AgentV
from agentflow.store import Store

from _proof_manuscript_fixture import write_proof_manuscript

TS = "2026-10-30T00:00:00+08:00"
SID = "000007"
PROOF = "1. 取 G = C_n（n ≥ 3）：它是 2-正则、围长为 n。\n2. 由第 1 步直接得到结论。"
#: 2026-11-04（甲）：在册送审要带的那一份按号手稿。
REL = f"reports/f-proof-{SID}.md"
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


def _put(store: Store, *, proof_text: str = PROOF) -> dict:
    """落一条在册命题（走真事务；夹具只造这一行）。

    `proof_text` 可换（改稿那一档要用另一份正文：sha 变了签才该作废）。
    """
    row = {
        "stmt_id": SID, "origin": "own_result", "kind": "theorem",
        "label": "弦长函数非常值", "statement_full": FULL,
        "statement_text": "弦长函数不是常值", "proof_text": proof_text,
        "evidence_kind": "heuristic", "status": "active",
        "quote_verified": None, "quote_reason": "自产命题，没有外部引文要比对",
        "created_at": TS, "created_by": "test",
        "bits": EB.bits_of(proof=True, proof_process=proof_text, kind="theorem"),
    }
    with store.tx("statements", actor="test") as tx:
        tx.upsert("statements", row)
    write_proof_manuscript(store.root, SID, proof_text, statement_full=FULL)
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


def _axis(answer: str, *, defect_kind: str = "", report_gap: str = "") -> dict:
    """秘书那一路的判定（`judge` 的返回形状：checked + decision）。

    D3 批 2：`judge()` 现在还会解析两格（`defect_kind` / `report_gap`）—— 夹具要用
    "程序性"那一档就必须显式给；不给 = 分类没做 ⇒ 写行处按 `math` 兜底
    （既有夹具因此逐字不变：它们测的是"缺 kind ⇒ 继续锁"那条保守默认）。
    """
    out = {"checked": True, "decision": answer, "reason": "夹具：照规则判",
           "basis": ["夹具"]}
    if defect_kind:
        out["defect_kind"] = defect_kind
    if report_gap:
        out["report_gap"] = report_gap
    return out


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


def _as_submitter():
    """一次真实送审的挂点：V 的 parent = F（收方秘书 = `secretary:F`）。

    2026-11-08 起签只落在稿上，而落块只能由收方秘书做（`vsigns.land` 的 `by` 只认
    `secretary:F|B`）。直调 V 不挂 parent 时 `by=""` ⇒ 能颁发签文件、不能落块 ——
    那是既有语义，不是失败。要量"稿上已签"的判据必须造出真实送审的挂点。
    """
    return CND.calling_as("t-v-000001", "V",
                          parent_task_id="t-f-000001", parent_role="F")


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

    with _as_submitter():
        got = agent.verify_proof(SID, proof_text=PROOF, proof_manuscript=REL)
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
    assert {r["proof_sha256"] for r in rows} == {VR.text_sha(PROOF)}, (
        "三次判的不是同一份正文 ⇒ sha 段漂了")
    assert {VR.proof_no_of(r) for r in rows} == {1}, rows
    assert len({r["verification_id"] for r in rows}) == 3, rows

    # 2026-11-08：签落在稿上（侧文件 + 九格块），命题行的第 3 位归 B 收录时认领。
    # 三转 clean ⇒ 秘书判发 ⇒ 签真的落地（issuance.issued + 稿上签块），
    # 而 statements 一个字节都不动（这是新契约的另一半）。
    assert got["signed_bit3"] is False, got["sign_issuance"]
    assert got["bits"].get("reviewed") is not True, got["bits"]
    assert got["sign_issuance"]["issued"] is True, got["sign_issuance"]
    assert got["review_write"].get("manuscript_signed") is True, got["review_write"]
    _block = VS.manuscript_sign_standing(
        (pathlib.Path(st.root) / REL).read_text(encoding="utf-8"),
        proof_sha=VR.text_sha(PROOF), manuscript_path=REL)
    assert _block["state"] == "signed", _block
    assert _stmt_row(st)["bits"]["reviewed"] is False, _stmt_row(st)["bits"]

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

    got = agent.verify_proof(SID, proof_text=PROOF, proof_manuscript=REL)

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
    assert passes[-1].get("terminal") == "rejected", passes
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
    with _as_submitter():
        got = agent.verify_proof(SID, proof_text=PROOF, proof_manuscript=REL)
    assert review.asked() == 1, (
        f"门槛 1 时问了 {review.asked()} 次模型 ⇒ 停的条件没跟着门槛走")
    assert len(got.get("review_passes") or []) == 1, got.get("review_passes")
    assert len(_rows(st)) == 1, _rows(st)
    assert got["sign_issuance"]["issued"] is True, got["sign_issuance"]
    assert got["signed_bit3"] is False and got["bits"].get("reviewed") is not True, got
    assert got["review_write"].get("manuscript_signed") is True, got["review_write"]
    # (b) 门槛 5：上界跟着门槛走 ⇒ 判满 5 次、第 5 次签上（不是判到 3 就停）。
    st2 = _ws(tmp_path / "b")
    _put(st2)
    review2 = _ReviewSeam([CLEAN_REPLY])
    sec_seam2 = _Seam({"v_reply_defect": [_axis(SEC.V_REPLY_CLEAN)],
                       "sign_issuance": [_axis(SEC.SIGN_ISSUE)]})
    agent2 = AgentV(st2, workspace_root=st2.root, llm=review2,
                    secretary=_secretary(st2, sec_seam2))
    monkeypatch.setattr(VR, "SIGN_STREAK_NEED", 5)
    with _as_submitter():
        got2 = agent2.verify_proof(SID, proof_text=PROOF, proof_manuscript=REL)
    passes = got2.get("review_passes") or []
    assert len(passes) == 5, f"门槛 5 时判了 {len(passes)} 次 ⇒ 上界没有等于门槛"
    assert review2.asked() == 5, (review2.asked(), passes)
    assert [p["streak"] for p in passes] == [1, 2, 3, 4, 5], passes
    assert [p["issue"] for p in passes] == [False, False, False, False, True], passes
    assert len(_rows(st2)) == 5, f"台账应当 5 行（每一转各一行），实得 {len(_rows(st2))}"
    assert got2["sign_issuance"]["streak_ok"] is True, got2["sign_issuance"]
    assert got2["sign_issuance"]["issued"] is True, got2["sign_issuance"]
    assert got2["signed_bit3"] is False and got2["bits"].get("reviewed") is not True, got2
    assert got2["review_write"].get("manuscript_signed") is True, got2["review_write"]
    assert _stmt_row(st2)["bits"]["reviewed"] is False, _stmt_row(st2)["bits"]
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
    got3 = agent3.verify_proof(SID, proof_text=PROOF, proof_manuscript=REL)
    assert review3.asked() == 0, (
        f"门槛 0 时仍然问了 {review3.asked()} 次模型 ⇒ 上界没有跟着门槛走")
    assert got3["review_passes"] == [], got3["review_passes"]
    assert _rows(st3) == [], "门槛 0 时落了台账行 ⇒ 判据前提被破坏"
    assert got3["checked"] is False, got3
    assert str(got3["reason"]).startswith("internal_inconsistency"), got3["reason"]
    assert "还差" not in str(got3["reason"]), got3["reason"]
    assert got3["signed_bit3"] is False and got3["bits"].get("reviewed") is not True, got3
    assert _stmt_row(st3)["bits"]["reviewed"] is False, _stmt_row(st3)["bits"]


# ============================================================ t4：含糊就是 fault

#: 第 2 转的回复：含糊（没有尝试痕迹）。业主 2026-10-30 第三次裁定：「只要不是完全没毛病
#: 都叫有毛病」⇒ 这一段必须判成 fault（不是 clean，也不再有一种"判不了"的结论）。
VAGUE_REPLY = json.dumps({"verdict": "成立", "why": "我觉得没问题，但我没逐行验证。",
                          "findings": []}, ensure_ascii=False)
#: 洗过的那一份（含糊那一转的转达文本）。它的 findings 必须能逐字引回 V 的回复。
WASHED_VAGUE = "V 没有逐行验证：请把每一步的依据补齐之后再送 V 重审。"


def test_t4_a_vague_reply_is_a_fault_not_an_unsure(tmp_path):
    """第 2 转是含糊的一段话 ⇒ 判成 `fault`（不是 unsure、不是 clean），类别是程序性。

    业主 2026-10-30 第三次裁定逐字：「不可能有判不了。你告诉我啥叫判不了？只要不是完全
    没毛病都叫有毛病」。三半都钉住：

    ① 题面与词表：只有两档，并逐字写着"判不了不是一种结论"（题面又给三档，模型迟早
       会把那一档答回来）；含糊的几种写法在题面里明文算「有缺陷要指出」；
    ② 链路（D3 批 2 翻转，业主裁定 ③④⑥）：含糊那一转秘书判 fault、类别 `procedural`
       ⇒ 连判立刻停（2 行、不签），但不是打回：`terminal="report"`、不洗稿、
       不进 F 的改稿明细；这一份正文没有被指出数学缺陷 ⇒ 同一 sha 可原样再送。
    ③ 反真空：秘书若仍答历史那一格（"判不了"）⇒ 它不是一种结论：不采信、
       `checked=False`、没有轴（既不是 clean 也不是 fault）。
    """
    # ---- ① 题面与词表：两档，且"判不了"被明文否掉
    system = SEC._judge_system("v_reply_defect")
    assert "「判不了」不是一种结论" in system, system[-400:]
    assert "只有两档" in system, system[-400:]
    assert SEC.V_REPLY_VERDICTS == (SEC.V_REPLY_CLEAN, SEC.V_REPLY_FAULT), SEC.V_REPLY_VERDICTS
    assert set(SEC.V_REPLY_AXIS.values()) == {"clean", "fault"}, SEC.V_REPLY_AXIS
    # 含糊的这几种写法逐字在题面里算「有缺陷要指出」（否则模型只会猜）。
    for phrase in ("我没逐行验证", "拿不准", "只挑出一处小记号问题"):
        assert phrase in system, (phrase, system[-600:])

    # ---- ② 链路：含糊那一转判成 fault（procedural）⇒ 立刻停，但不是打回
    #
    # D3 批 2（业主裁定 ③④⑥）：`我没逐行验证` 是程序性（V 没有做出判定），不是数学缺陷。
    # 这一转仍然停（再跑也到不了门槛），但终局是 `terminal="report"`：不锁 sha、不洗稿、
    # 不递 F 的改稿清单；同一份正文可以原样再送（新的一趟从 0 起算）。
    st = _ws(tmp_path)
    _put(st)
    review = _ReviewSeam([CLEAN_REPLY, VAGUE_REPLY])
    sec_seam = _Seam({"v_reply_defect": [_axis(SEC.V_REPLY_CLEAN),
                                         _axis(SEC.V_REPLY_FAULT,
                                               defect_kind="procedural")],
                      "wash_v_reply": [{"text": WASHED_VAGUE, "step": 2,
                                        "findings": [{"quote": "我没逐行验证",
                                                      "why": "没验证过就不是没问题"}]}]})
    agent = AgentV(st, workspace_root=st.root, llm=review,
                   secretary=_secretary(st, sec_seam))

    got = agent.verify_proof(SID, proof_text=PROOF, proof_manuscript=REL)

    assert review.asked() == 2, (
        f"第 2 转已经判成 fault，却又问了 {review.asked()} 次模型 ⇒ 「立刻终止」没做到")
    passes = got.get("review_passes") or []
    assert [p["axis"] for p in passes] == ["clean", "fault"], passes
    # fault 清零：第 2 转的连续次数是 0（不是 1 —— 那会是"不清零"的旧 unsure 口径）。
    assert [p["streak"] for p in passes] == [1, 0], passes
    assert passes[-1].get("terminal") == "report", passes
    assert passes[-1].get("fault_kind") == "procedural", passes
    rows = _rows(st)
    assert len(rows) == 2, f"台账应当 2 行，实得 {len(rows)}"
    assert rows[-1]["secretary_judge"]["axis"] == "fault", rows[-1]["secretary_judge"]
    assert rows[-1]["secretary_judge"]["fault_kind"] == "procedural", rows[-1]
    assert rows[-1]["secretary_judge"]["fault_cause"] == "self_declared", rows[-1]
    assert got["secretary_judge"]["axis"] == "fault", got["secretary_judge"]
    assert got["secretary_judge"]["fault_kind"] == "procedural", got["secretary_judge"]
    assert got["signed_bit3"] is False and got["bits"].get("reviewed") is not True, got
    assert got["sign_issuance"]["issued"] is False, got["sign_issuance"]
    assert "原样再送" in got["sign_issuance"]["reason"], got["sign_issuance"]["reason"]
    assert "终局" not in got["sign_issuance"]["reason"], got["sign_issuance"]["reason"]
    assert "还差" not in got["sign_issuance"]["reason"], got["sign_issuance"]["reason"]
    # 程序性那一档不洗稿：洗过的文本一个字都不该出现在台账行上。
    assert sec_seam.asked("wash_v_reply") == 0, sec_seam.seen
    assert "washed_relay" not in rows[-1], rows[-1]
    assert _stmt_row(st)["bits"]["reviewed"] is False, _stmt_row(st)["bits"]
    # 反真空：新写的台账行里没有任何一格写着 unsure（新判定不再产生它）。
    assert all("unsure" not in json.dumps(r, ensure_ascii=False) for r in rows), rows

    # 读侧：程序性不进 F 的改稿明细（它不是对证明的判断）；但也不许静默消失 ——
    # 读数里点名"另 N 条只是报告层面、可原样再送"。
    text, details, problems = AL.v_rejections_digest(st.root, [_stmt_row(st)])
    assert problems == [], problems
    assert details == [], (text[:400], details)
    assert "可原样再送" in text, text
    assert "报告层面" in text, text

    # ---- ③ 历史那一格不再是一种结论：秘书答它 ⇒ 不采信（没有轴、checked=False）
    st2 = _ws(tmp_path / "legacy-answer")
    _put(st2)
    legacy_answer = _secretary(st2, _Seam({"v_reply_defect": [_axis("判不了")]}))
    judge = legacy_answer.judge_v_reply(reply="我觉得没问题，但我没逐行验证。",
                                        verdict="成立", statement_id=SID)
    assert judge["checked"] is False, judge
    assert judge["axis"] == "", judge
    assert "不采信" in judge["reason"] or "不在" in judge["reason"], judge["reason"]
    assert judge["answer"] != "判不了", (
        "历史那一格被当成一种结论写进了返回值的 `answer`：" + str(judge))


# ============================================================ t5：问不出来 ⇒ 没查成

class _DeadSeam:
    """秘书的缝：这一问没答上来（`ok=False` / 没有回音）。t5 用它量"没查成"。"""

    wired = True

    def __init__(self) -> None:
        self.seen: list[tuple[str, str, str]] = []
        self.calls = 0

    def ask_json(self, prompt: str, *, system: str = "", task_id: str = "",
                 note: str = "") -> tuple[dict | None, _Call]:
        self.seen.append((note, prompt, system))
        self.calls += 1
        call = _Call()
        call.ok = False
        call.problem = "timeout"
        call.detail = "夹具：这一问没有回音"
        return None, call


def test_t5_a_secretary_that_cannot_answer_is_not_a_verdict(tmp_path):
    """秘书问不出来（缝返回 `ok=False`）⇒ `checked=False`、终止、不签、也不打回。

    口径（业主 2026-10-30 第三次裁定第 3 条）：「没查成」不是判定 —— 秘书问不出来 /
    模型输出不合法 / 台账写不进去 ⇒ 框架失败：终止 + `checked=False` + 明确 reason；
    不许当成 fault 打回，也不许说"次数没到"。
    """
    st = _ws(tmp_path)
    _put(st)
    review = _ReviewSeam([CLEAN_REPLY])
    dead = _DeadSeam()
    agent = AgentV(st, workspace_root=st.root, llm=review,
                   secretary=SEC.Secretary("V", root=st.root, store=st, seam=dead,
                                           enable_model=True))

    got = agent.verify_proof(SID, proof_text=PROOF, proof_manuscript=REL)

    # 连判在第一转就停了（V 问了一次模型、秘书问了一次）。
    assert review.asked() == 1, review.asked()
    assert dead.calls == 1, dead.calls
    rows = _rows(st)
    assert len(rows) == 1, f"V 的审阅是真的 ⇒ 台账那一行照落，实得 {len(rows)}"
    assert rows[0]["secretary_judge"]["checked"] is False, rows[0]["secretary_judge"]
    assert rows[0]["secretary_judge"]["axis"] == "", rows[0]["secretary_judge"]
    assert got["checked"] is False, got
    assert str(got["reason"]).startswith("secretary_unjudged"), got["reason"]
    assert "没查成" in str(got["reason"]), got["reason"]
    assert "timeout" in str(got["detail"]), got["detail"]
    assert got["secretary_judge"]["checked"] is False, got["secretary_judge"]
    assert got["sign_issuance"]["checked"] is False, got["sign_issuance"]
    assert got["signed_bit3"] is False and got["bits"].get("reviewed") is not True, got
    assert _stmt_row(st)["bits"]["reviewed"] is False, _stmt_row(st)["bits"]
    # 不打回：读侧一条明细都没有，板上一个项都不开（没查成不是"有毛病"）。
    text, details, problems = AL.v_rejections_digest(st.root, [_stmt_row(st)])
    assert details == [], (text[:400], details)
    board = _BoardDouble()
    delivered = AL.deliver_v_verdicts(board, task_id="t-000001", depth=0,
                                      details=details)
    assert board.opened == [], board.opened
    assert delivered.get("opened") == [], delivered


# ============================================================ t6：措辞判据（防回归）

#: 业主 2026-10-30 否掉的终局措辞：这三种写法只描述"还差多少次"，而连判的终局只有
#: 两种（签 / 打回）—— 它们一旦回到返回值、读数或 docstring 里，读者就会把「打回」
#: 读成「再多判几次就好」，而这正是裁定取消的东西。
NOT_ENOUGH_WORDING = ("还没够", "还不够", "未达门槛")
#: V 那一根轴的历史轴名（2026-10-30 之前写下的台账行里出现过它）。
#:
#: 这一条不是"这个词决不允许出现"—— 读侧必须留着它（老台账要读得出）；它量的是
#: "不许再作为一种判定结论出现"。两件事分开量（见下面 ② 与 ③）。
LEGACY_AXIS = "unsure"
#: 只读、不许改的那一处（FC-27 禁改区）：`tools/verify_tools.py` 的 returns 说明里有一句
#: 旧的三档描述。它不在本批写权里，所以扫描时显式排除并登记原因 —— 为了变绿去改
#: 禁改区，等于把"判据变绿"换成"权限越界"。
FC27_OUT_OF_SCOPE = ("tools/verify_tools.py",)
#: 「只作历史兼容读」这句话的写法 —— 2026-11-02 起反向用：那一档连兼容读也不留，
#: 所以判据要的是"每一处都写着它已经取消/已经删掉"，而不是"每一处都写着怎么兼容读它"。
LEGACY_RETIRED_NOTES = ("已取消", "删了", "删掉", "不再")


def test_t6_no_not_enough_wording_and_no_unsure_as_a_conclusion(tmp_path):
    """`src/` 里：终局措辞一处不剩；`unsure` 只作历史兼容读、写侧产生不出它。

    业主 2026-10-30 的两次裁定各管一半：第二次否掉"还差次数"那类终局措辞，第三次
    否掉"判不了"这一档结论。两个方向都扫源码：返回值只覆盖跑得到的分支，而措辞
    最容易留在 docstring / 注释里 —— 那正是下一次改动会照着抄的模板。

    为什么 ① 只扫 V 那一链的四份源码：那三种措辞在别的模块里有完全不同的意思
    （`specs/*` 的长句、`tools/doc_tools.py` 的引文覆盖面），全仓扫描会把它们误判成本条
    口径的终局措辞 —— 那是判据量错了对象。② 反过来是全 `src/` 扫的：`unsure` 只可能在
    这几处出现，漏一处就等于漏了一条"它还是一种结论"的暗门。
    """
    src = pathlib.Path(VR.__file__).resolve().parent
    v_chain = {"agent_v/core.py": src / "agent_v" / "core.py",
               "verifications.py": src / "verifications.py",
               "secretary.py": src / "secretary.py",
               "agent_loop.py": src / "agent_loop.py"}
    scanned: dict[str, str] = {}
    for name, path in v_chain.items():
        assert path.is_file(), f"{name} 不在盘上：{path}"
        text = path.read_text(encoding="utf-8")
        assert text.strip(), f"{name} 是空的 ⇒ 判据扫不到东西（假绿）"
        scanned[name] = text
    # 反真空：这四份源码确实带着本批改过的那几格（扫错文件会假绿）。
    assert "verify_proof" in scanned["agent_v/core.py"], "扫的不是 V 的实现"
    assert "consecutive_holds" in scanned["verifications.py"], "扫的不是台账读数"
    assert "judge_v_reply" in scanned["secretary.py"], "扫的不是秘书的判定面"
    assert "v_rejections_digest" in scanned["agent_loop.py"], "扫的不是读侧"

    # ① 三种"还差次数"的终局措辞：一处都不许有（白名单刻意为空）。
    wording = [f"{name}:{i}:{word}:{line.strip()[:70]}"
               for name, text in scanned.items()
               for i, line in enumerate(text.splitlines(), start=1)
               for word in NOT_ENOUGH_WORDING if word in line]
    assert wording == [], (
        "连判的终局只剩「签 / 打回」两种，这几种措辞不许再出现：\n" + "\n".join(wording))

    # ② `unsure`：全 `src/` 扫。2026-11-02（业主：「这一档连历史兼容读也不留」）之后，
    #    那一档连"兼容读"都不许有 —— 每一处都必须在"它已经取消/已经删掉"的语境里
    #    （FC-27 除外）。改前这一条量的是"每一处都写着只作历史兼容读"；裁定变了，
    #    量的方向跟着翻（不是放宽：改前允许"读得出、不计票"，现在连那句话都不许留）。
    every_py = {p.relative_to(src).as_posix(): p for p in sorted(src.rglob("*.py"))}
    assert "agent_v/core.py" in every_py and "tools/verify_tools.py" in every_py, sorted(every_py)
    unannotated: list[str] = []
    seen = 0
    for rel, path in every_py.items():
        if rel in FC27_OUT_OF_SCOPE:
            continue
        lines = path.read_text(encoding="utf-8").splitlines()
        for i, line in enumerate(lines):
            if LEGACY_AXIS not in line:
                continue
            seen += 1
            window = lines[max(0, i - 6): i + 7]
            if not any(note in w for note in LEGACY_RETIRED_NOTES for w in window):
                unannotated.append(f"{rel}:{i + 1}:{line.strip()[:80]}")
    assert seen >= 4, f"全 src/ 只扫到 {seen} 处 `{LEGACY_AXIS}` ⇒ 扫错了对象（假绿）"
    assert unannotated == [], (
        f"`{LEGACY_AXIS}` 只许出现在「这一档已经取消」的语境里（业主 2026-11-02："
        "连历史兼容读也不留）；这几处没写明：\n" + "\n".join(unannotated))

    # ③ 写侧结构上产生不出它，读侧也不再认它：词表 / 轴表 / 落盘口 / 历史轴表各断言一次。
    assert SEC.V_REPLY_VERDICTS == (SEC.V_REPLY_CLEAN, SEC.V_REPLY_FAULT), SEC.V_REPLY_VERDICTS
    assert set(SEC.V_REPLY_AXIS.values()) == {"clean", "fault"}, SEC.V_REPLY_AXIS
    assert VR.SECRETARY_JUDGE_AXES == ("clean", "fault"), VR.SECRETARY_JUDGE_AXES
    assert not hasattr(VR, "SECRETARY_JUDGE_HISTORICAL_AXES"), (
        "历史轴表的常量还在 ⇒ 那一档的兼容机制没有整段删掉")
    st = _ws(tmp_path)
    _put(st)
    ok = VR.parse_verdict(CLEAN_REPLY)
    first = VR.record_verification(
        st.root, statement_id=SID, proof_text=PROOF, verdict=ok, verifier="agent-V",
        store=st, proof_no=1,
        secretary_judge={"checked": True, "axis": "clean", "decision": SEC.V_REPLY_CLEAN})
    assert first["secretary_judge"]["axis"] == "clean", first["secretary_judge"]
    assert VR.consecutive_holds(st.root, SID)["streak"] == 1
    # 落盘口：把历史那一格塞给 `record_verification` ⇒ 落成空轴（写不进来）。
    tried = VR.record_verification(
        st.root, statement_id=SID, proof_text=PROOF, verdict=ok, verifier="agent-V",
        store=st, proof_no=1,
        secretary_judge={"checked": True, "axis": LEGACY_AXIS, "decision": "判不了"})
    assert tried["secretary_judge"]["axis"] == "", tried["secretary_judge"]
    assert VR.consecutive_holds(st.root, SID)["streak"] == 1
    # 读侧：手写一条 2026-10-30 之前那一版写下的行 ⇒ 那个轴名不再是词表里的一格
    # （2026-11-02 业主：「这一档连历史兼容读也不留」）：读出来是空轴，连续计数里
    # 没有一条分支认它（不计入、也不清零 —— 与"问过、没判成"同一条通用纪律）。
    VR._append_verification(VR.verification_ledger_path(st.root, SID), {
        **{k: first[k] for k in ("statement_id", "stmt_id", "proof_no", "verifier", "verdict",
                                 "defect_step", "quote", "why", "findings",
                                 "unresolved_errors", "citation_checks", "proof_sha256",
                                 "proof_chars", "submission_id", "at")},
        "verification_id": "v-legacy-0001",
        "round": 2,
        "secretary_judge": {"axis": LEGACY_AXIS, "checked": True, "decision": "判不了"},
    })
    legacy_rows = [r for r in _rows(st) if r["verification_id"] == "v-legacy-0001"]
    assert len(legacy_rows) == 1, _rows(st)
    assert VR.secretary_axis(legacy_rows[0]) == "", legacy_rows[0]
    assert VR.consecutive_holds(st.root, SID)["streak"] == 1, (
        "老行上那个轴名改了票数：它读出来是空轴（不计入、也不清零），"
        "而「不算票」这句话不再是给那一档留的豁免位 —— 它只是通用纪律的结果")
    last = VR.record_verification(
        st.root, statement_id=SID, proof_text=PROOF, verdict=ok, verifier="agent-V",
        store=st, proof_no=1,
        secretary_judge={"checked": True, "axis": "clean", "decision": SEC.V_REPLY_CLEAN})
    assert last["secretary_judge"]["axis"] == "clean", last["secretary_judge"]
    assert VR.consecutive_holds(st.root, SID)["streak"] == 2, (
        "老行那一格把连续次数清零了（它读出来是没有轴，不清零）")
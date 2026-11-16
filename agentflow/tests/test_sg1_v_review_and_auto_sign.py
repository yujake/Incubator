# -*- coding: utf-8 -*-
"""SG1：发签 = V 的秘书；第 3 轮 clean 自动发签并交稿；有毛病 ⇒ 落 V 稿给被审者。

业主 2026-11-16 逐条裁定（原文见本次施工单）：

```text
① 发签 = V 的秘书，签直接签进稿里
② 第 3 轮秘书判没问题 ⇒ 系统自动发签，并把签好的稿交出去
③ 去掉死词表 SIGN_ISSUANCE_VERDICTS 与那次"模型点头"
④ 两态：不存在「看不出来」，把这一档删干净
⑤ 有毛病 ⇒ 落 V 稿（给被审者的审阅报告）
⑥ 落盘 verifications/reviews/v-review-NNNNNN.md + index.jsonl；号源 = 索引 max+1
⑦ 交付：conductor.open_item notice，不要求 ack
⑧ 三轮累积与互斥：到 3 次发签；任一次有毛病 ⇒ 落 V 稿并停止；同一轮不许既有签又有 V 稿
```

本文件每一条判据都量一个具体读数；反真空写在 `test_z_anti_vacuum_*` 里。
"""
from __future__ import annotations

import json
import pathlib

from agentflow import agent_loop as AL
from agentflow import conductor as CND
from agentflow import evidencebits as EB
from agentflow import exhaustionreport as ER
from agentflow import manuscriptfamily as MF
from agentflow import papermapping as PM
from agentflow import secretary as SEC
from agentflow import verifications as VR
from agentflow import vreviews as VRV
from agentflow.agent_v import AgentV
from agentflow.store import Store

from _proof_manuscript_fixture import write_proof_manuscript

TS = "2026-11-16T00:00:00+08:00"
SID = "000007"
PROOF = "1. 取 G = C_n（n ≥ 3）：它是 2-正则、围长为 n。\n2. 由第 1 步直接得到结论。"
REL = f"reports/f-proof-{SID}.md"
FULL = "设 G 是 3-正则群；则弦长函数不是常值。"

CLEAN_REPLY = json.dumps(
    {"verdict": "成立", "why": "试了几种反例构造都失败，未发现问题。", "findings": []},
    ensure_ascii=False)
#: 第 2 轮的回复：结论词仍写「成立」，findings 里有一条 warning（业主 6 的前半：
#: warning 也算有毛病；⑤：V 稿要把 warning 与程序性 fault 都写进去）。
#: 这一条刻意不带 error / 步号：带数学证据时写侧护栏会把 procedural 折回 math
#: （只往更严的方向折），而本判据要量的是"程序性 fault 也落 V 稿"。
FAULT_REPLY = json.dumps(
    {"verdict": "成立", "why": "整体能走通；第 2 步的记号没有定义。",
     "findings": [
         {"level": "warning", "step": 2, "kind": "记号一致性",
          "detail": "第 2 步的记号没有定义；同一步里同一个对象用了两种记号"},
     ]},
    ensure_ascii=False)


# ------------------------------------------------------------------ 夹具

def _ws(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _put(store: Store, *, proof_text: str = PROOF) -> dict:
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


class _Call:
    ok = True
    problem = ""
    detail = ""
    text = ""
    model = "fake"
    prompt_version = "t"
    prompt_sha256 = "0" * 64


class _ReviewSeam:
    wired = True

    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)
        self.prompts: list[str] = []

    def ask(self, prompt: str = "", **_kw) -> _Call:
        self.prompts.append(prompt)
        text = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        call = _Call()
        call.text = text
        return call

    def asked(self) -> int:
        return len(self.prompts)


class _Seam:
    """秘书的缝：按 `note` 回预置 JSON；不提供 `sign_issuance` 的答案。"""

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


def _axis(answer: str, *, defect_kind: str = "") -> dict:
    out = {"checked": True, "decision": answer, "reason": "夹具：照规则判",
           "basis": ["夹具"]}
    if defect_kind:
        out["defect_kind"] = defect_kind
    return out


def _secretary(st: Store, seam: _Seam) -> SEC.Secretary:
    return SEC.Secretary("V", root=st.root, store=st, seam=seam, enable_model=True)


def _agent(st: Store, review: _ReviewSeam, seam: _Seam) -> AgentV:
    return AgentV(st, workspace_root=st.root, llm=review,
                  secretary=_secretary(st, seam))


def _submit(role: str = "F"):
    return CND.calling_as("t-v-000001", "V",
                          parent_task_id=f"t-{role.lower()}-000001", parent_role=role)


class _BoardDouble:
    """只记 `open_item` / `set_item_detail` 的 conductor 替身。"""

    def __init__(self) -> None:
        self.opened: list[dict] = []
        self.details: list[tuple[str, str]] = []
        self.rows: list[dict] = []

    def open_item(self, *args, **kwargs):
        item_id = f"i-{len(self.opened) + 1:06d}"
        self.opened.append({"item_id": item_id, "args": args, "kwargs": kwargs})
        self.rows.append({"task_id": item_id,
                          "input_key": str(kwargs.get("input_key") or ""),
                          "role": str(kwargs.get("role") or "")})
        return item_id

    def set_item_detail(self, item_id: str, detail: str):
        self.details.append((item_id, detail))
        return (True, "")

    def _board_rows(self) -> list:
        return list(self.rows)


def _reviews(root) -> list[pathlib.Path]:
    return sorted((pathlib.Path(root) / VRV.REVIEWS_DIR).glob(f"{VRV.PREFIX}*.md"))


def _index(root) -> list[dict]:
    path = VRV.reviews_index_path(root)
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


# ============================================================ ①③②：自动发签

def test_auto_sign_on_round_three_without_a_model_nod(tmp_path):
    """三轮 clean ⇒ 秘书按地板自动发签；`sign_issuance` 那一问一次都不问模型。"""
    st = _ws(tmp_path)
    _put(st)
    review = _ReviewSeam([CLEAN_REPLY])
    seam = _Seam({"v_reply_defect": [_axis(SEC.V_REPLY_CLEAN)]})  # 没有 sign_issuance
    with _submit():
        got = _agent(st, review, seam).verify_proof(
            SID, proof_text=PROOF, proof_manuscript=REL)

    assert seam.asked("sign_issuance") == 0, seam.seen
    assert got["sign_issuance"]["issued"] is True, got["sign_issuance"]
    assert got["review_write"].get("manuscript_signed") is True, got["review_write"]
    # ⑧ 互斥：签上的那一轮没有 V 稿。
    assert _reviews(st.root) == [], "签上的那一轮也落了 V 稿（同一轮两样都出）"
    assert got["review_write"].get("v_review", {}) == {}, got["review_write"]
    block = (pathlib.Path(st.root) / REL).read_text(encoding="utf-8")
    assert "- V 签：" in block and "已签=true" in block, block[-500:]
    assert not hasattr(SEC, "SIGN_ISSUANCE_VERDICTS"), (
        "死词表还在：`SIGN_ISSUANCE_VERDICTS` 必须删掉")
    assert "sign_issuance" not in SEC.JUDGE_VERDICTS, SEC.JUDGE_VERDICTS


def test_signed_manuscript_is_delivered_without_ack(tmp_path, monkeypatch):
    """②/⑦：签好的稿按 notice 交出去，`expects=""`，不进 ACK_REQUIRED 前缀。"""
    st = _ws(tmp_path)
    _put(st)
    board = _BoardDouble()
    monkeypatch.setattr(VRV, "_conductor_for", lambda _store: board)
    review = _ReviewSeam([CLEAN_REPLY])
    seam = _Seam({"v_reply_defect": [_axis(SEC.V_REPLY_CLEAN)]})
    with _submit("F"):
        got = _agent(st, review, seam).verify_proof(
            SID, proof_text=PROOF, proof_manuscript=REL)

    assert got["sign_issuance"]["issued"] is True, got["sign_issuance"]
    assert len(board.opened) == 1, board.opened
    item = board.opened[0]["kwargs"]
    assert item["kind"] == "notice", item
    assert item.get("expects", "") == "", item
    assert str(item.get("input_key") or "").startswith(VRV.SIGNED_PREFIX), item
    key = str(item["input_key"])
    assert not any(key.startswith(p) for p in CND.ACK_REQUIRED_ITEM_PREFIXES), key
    assert item["role"] == "F" and item["parent_task_id"] == "t-f-000001", item
    assert board.details and REL in board.details[0][1], board.details


# ============================================================ ④：两态

def test_exhaustion_review_has_no_third_state(tmp_path):
    """④：缺材料 ⇒ `checked=False`，不再产出 `看不出来` 那一档。"""
    assert not hasattr(ER, "VERDICT_UNKNOWN"), "会审的第三态常量还在"
    assert "看不出来" not in ER.__dict__.get("VERDICTS", ())
    got = ER.review(workspace_root=tmp_path, statement={"proof_text": "程序：code/x.py"},
                    experiments=(), experiment_row=None)
    assert got.get("checked") is False, got
    assert got.get("verdict") == "", got
    assert got.get("missing"), got


def test_no_live_three_state_word_in_the_verdict_lists():
    """④：判定词表里没有那一档；它不是 `VERDICTS` 的一格，也没有第四张词表。"""
    assert "看不出来" not in VR.VERDICTS, VR.VERDICTS
    assert not hasattr(VR, "LEGACY_VERDICTS"), (
        "`LEGACY_VERDICTS` 还在：那一档的词表必须删掉")
    en = PM._LEDGER_CELL_TEXT[PM.PAPER_LANGUAGE_EN]["verdicts"]
    assert "看不出来" not in en, en


# ============================================================ ⑤⑥⑦：有毛病 ⇒ V 稿

def test_a_fault_writes_one_review_and_delivers_it_without_ack(tmp_path, monkeypatch):
    """第 2 轮有毛病 ⇒ 落一份 V 稿（族+号+sha / findings 含 warning / 程序性 fault），
    并按 notice 交给被审者（F），不要求 ack；这一轮没有签。"""
    st = _ws(tmp_path)
    _put(st)
    board = _BoardDouble()
    monkeypatch.setattr(VRV, "_conductor_for", lambda _store: board)
    review = _ReviewSeam([CLEAN_REPLY, FAULT_REPLY])
    seam = _Seam({"v_reply_defect": [_axis(SEC.V_REPLY_CLEAN),
                                     _axis(SEC.V_REPLY_FAULT,
                                           defect_kind="procedural")]})
    with _submit("F"):
        got = _agent(st, review, seam).verify_proof(
            SID, proof_text=PROOF, proof_manuscript=REL)

    assert got["sign_issuance"]["issue"] is False, got["sign_issuance"]
    assert "已签=true" not in (pathlib.Path(st.root) / REL).read_text(encoding="utf-8")
    files = _reviews(st.root)
    assert len(files) == 1, files
    assert files[0].name == "v-review-000001.md", files
    text = files[0].read_text(encoding="utf-8")
    assert "f-proof" in text and SID in text, text
    sha = VR.text_sha(PROOF)
    assert sha in text, "V 稿没写被审正文的 sha"
    assert "warning" in text, "V 稿没把 warning 写进去"
    assert "procedural" in text, "V 稿没写程序性 fault"
    assert "第 2 步的记号没有定义" in text, text
    index = _index(st.root)
    assert len(index) == 1, index
    assert index[0]["review_id"] == "v-review-000001", index
    assert index[0]["manuscript_family"] == "f-proof", index
    assert index[0]["manuscript_id"] == SID, index
    assert index[0]["proof_sha256"] == sha, index
    assert index[0]["verification_id"].startswith("v-"), index
    assert index[0]["ledger"] == f"verifications/{SID}.jsonl", index

    assert len(board.opened) == 1, board.opened
    item = board.opened[0]["kwargs"]
    assert item["kind"] == "notice" and item.get("expects", "") == "", item
    assert str(item["input_key"]).startswith(VRV.REVIEW_PREFIX), item
    assert not any(str(item["input_key"]).startswith(p)
                   for p in CND.ACK_REQUIRED_ITEM_PREFIXES), item
    assert board.details and files[0].name in board.details[0][1], board.details


def test_review_ids_come_from_index_max_plus_one_and_are_idempotent(tmp_path):
    """⑥：号源 = 索引 max+1；同一台账锚点重复调用只回旧那一份。"""
    root = tmp_path / "ws"
    root.mkdir()
    base = dict(statement_id=SID, manuscript=REL, manuscript_family="f-proof",
                manuscript_id=SID, proof_sha256="a" * 64, verdict="有毛病",
                defect_step=2, findings=[{"level": "error", "step": 2,
                                          "kind": "k", "detail": "d"}],
                reason="r", fault_kind="math", fault_cause="")
    first = VRV.record_review(root, ledger=f"verifications/{SID}.jsonl",
                              verification_id="v-000001", at=TS, **base)
    second = VRV.record_review(root, ledger=f"verifications/{SID}.jsonl",
                               verification_id="v-000002", at=TS, **base)
    again = VRV.record_review(root, ledger=f"verifications/{SID}.jsonl",
                              verification_id="v-000001", at=TS, **base)
    assert first["review_id"] == "v-review-000001", first
    assert second["review_id"] == "v-review-000002", second
    assert again["review_id"] == "v-review-000001", again
    assert again["idempotent"] is True and again["written"] is False, again
    assert [p.name for p in _reviews(root)] == [
        "v-review-000001.md", "v-review-000002.md"]


def test_unregistered_fault_uses_the_pending_ledger_anchor(tmp_path, monkeypatch):
    """⑧/⑥：未在册（没有 review_call）也认台账锚点：pending 路径 + verification_id。"""
    st = _ws(tmp_path)
    _put(st)  # 手稿在盘上；但这一次送审不带命题号 ⇒ 走未在册支
    review = _ReviewSeam([CLEAN_REPLY, FAULT_REPLY])
    seam = _Seam({"v_reply_defect": [_axis(SEC.V_REPLY_CLEAN),
                                     _axis(SEC.V_REPLY_FAULT,
                                           defect_kind="math")]})
    with _submit("F"):
        got = _agent(st, review, seam).verify_proof(
            "", proof_text=PROOF, proof_manuscript=REL)

    index = _index(st.root)
    assert len(index) == 1, index
    assert index[0]["ledger"].startswith("verifications/pending/"), index
    assert index[0]["verification_id"].startswith("u-"), index
    assert index[0]["review_call"] == "", index
    assert got.get("review_write", {}).get("v_review", {}).get("review_id") \
        == index[0]["review_id"], got.get("review_write")


# ============================================================ 反真空

def test_z_anti_vacuum_fault_hook_is_load_bearing(tmp_path, monkeypatch):
    """把「有毛病就落 V 稿」的判据打桩成恒假 ⇒ ⑤ 的判据必红（没有稿）。"""
    st = _ws(tmp_path)
    _put(st)
    review = _ReviewSeam([CLEAN_REPLY, FAULT_REPLY])
    seam = _Seam({"v_reply_defect": [_axis(SEC.V_REPLY_CLEAN),
                                     _axis(SEC.V_REPLY_FAULT)]})
    monkeypatch.setattr(AgentV, "_v_review_should_be_written",
                        lambda self, judgment: False)
    with _submit():
        got = _agent(st, review, seam).verify_proof(
            SID, proof_text=PROOF, proof_manuscript=REL)
    assert got["secretary_judge"]["axis"] == "fault", got["secretary_judge"]
    assert _reviews(st.root) == [], "判据被打桩成恒假，V 稿却还是落了"
    assert got.get("review_write", {}).get("v_review", {}).get("review_id", "") == "", (
        got.get("review_write"))

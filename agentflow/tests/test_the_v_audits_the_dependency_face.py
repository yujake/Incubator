# -*- coding: utf-8 -*-
"""V 是引用纪律的第一道防线（业主 2026-11-06 逐字：「引用未在册命题应该在 V 审阅时
就被打回，轮不到 B」）。

## 六项逐条核（业主补的口径）

```
① 正文里每个 `stmt:<号>` 都能在 `statements` 里找到（在册）
② 每个被引号的等级 ≥ pre_theorem（准定理级及以上）
③ 手稿 `## 依赖` 表里每一行点名的号，同样满足 ① 与 ②
④ 表与正文的引用集合一致：正文点了而表里没有的、表里有而正文没点的，都要点名
⑤ 被引命题的 proof_no / 正文 sha 与手稿里引用它的那一步对得上（可核时）
⑥ 引用强度：不得把被引命题的结论写强（已有的那一档，本文件不重复钉）
```

任一项不成立 ⇒ `verdict=有毛病`、`defect_step` 指到那一步、`detail` 点名是哪个号
⇒ 不签发。全部满足 ⇒ 成立、照常走三转发签（不许把好稿挡住）。

## 判据（g–k，先红后绿 + 反真空）

| 编号 | 它要证明的事 | 改前怎么红 |
|---|---|---|
| g | 正文点一个不在册的号 ⇒ 有毛病 + defect_step + detail 点名 ⇒ 不签发 | V 放行并签上（引用材料只看依赖台账，不看手稿正文） |
| h | 正文点一个在册但 `conjecture` 的号 ⇒ 有毛病 + detail 写"等级 conjecture < 门槛" | 同上 |
| i | 表里有行、正文没点它 ⇒ 有毛病、detail 点名那个号 | 同上 |
| j | 反真空：把 ①② 的判据打桩成恒真 ⇒ g/h 必红（回到"签上"） | —— |
| k | 全部满足 ⇒ 成立、签发（不许把好稿挡住） | —— |

## 这些替身量的是什么

`_ReviewSeam` 逐个交出预置回复（本文件一律交「成立」—— 缺陷不是模型找到的，而是
V 自己那条机械依赖面审计找到的）；`_Seam` 给秘书的两档判定与发签决定。
"""
from __future__ import annotations

import json
import pathlib

from _proof_manuscript_fixture import write_proof_manuscript
from agentflow import conductor as CND
from agentflow import depsection as DS
from agentflow import evidencebits as EB
from agentflow import secretary as SEC
from agentflow import verifications as VR
from agentflow import vsigns as VS
from agentflow.agent_v import AgentV
from agentflow.store import Store

TS = "2026-11-06T00:00:00+08:00"
SID = "000007"
LEMMA = "000008"
UNKNOWN = "000099"
FULL = "主命题：这一份手稿的依赖面要被 V 逐条核。"
LEMMA_FULL = "上下文引理：被引用的那一条。"
#: 表的引用那一格（`render_dependency_section` 的固定四列）。
HEAD = ("| 引用（F 的原话） | 命题号（stmt:NNNNNN） | 用在哪一步 | "
        "路径号（第几条证明） |\n|---|---|---|---|")

#: 一次 clean 的审阅回复：模型说成立（缺陷由 V 的机械审计找，不靠模型）。
CLEAN_REPLY = json.dumps({"verdict": "成立", "why": "重读一遍，未发现问题。",
                          "findings": []}, ensure_ascii=False)


def _clean_with_check(sid: str) -> str:
    """clean + 对 `sid` 给出 `consistent`（依赖面干净那一档：引用核实也要有结论）。"""
    return json.dumps({
        "verdict": "成立", "why": "重读一遍，未发现问题。", "findings": [],
        "citation_checks": [{"stmt_id": sid, "verdict": "consistent",
                             "quote_verbatim": False, "note": "夹具：用法一致"}],
    }, ensure_ascii=False)


def _ws(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _put(store: Store, sid: str, *, full: str, bits: dict, label: str,
         proof_text: str = "") -> dict:
    """铺一条在册命题（`bits` 决定它的等级；本文件据此造"够格 / 不够格"两档）。"""
    row = {
        "stmt_id": sid, "origin": "own_result", "kind": "theorem",
        "label": label, "statement_full": full, "statement_text": full[:24],
        "proof_text": str(proof_text), "evidence_kind": "heuristic",
        "status": "active", "quote_verified": None,
        "quote_reason": "夹具：自产命题", "created_at": TS, "created_by": "test",
        "bits": dict(bits),
    }
    with store.tx("statements", actor="test") as tx:
        tx.upsert("statements", row)
    return row


def _bits(*, reviewed: bool = False) -> dict:
    """`reviewed=True` ⇒ 现算出 `pre_theorem`；`False` ⇒ `conjecture`（两档都由真口径算）。"""
    return EB.bits_of(proof=True, proof_process="夹具正文", reviewed=reviewed,
                      reviewed_by=({"verification_id": "v-0001"} if reviewed else None),
                      kind="theorem")


def _manuscript(store: Store, *, body: str, rows: list[dict]) -> str:
    """写这一条命题的按号手稿，返回工作区相对路径。"""
    return write_proof_manuscript(store.root, SID, body, statement_full=FULL,
                                  deps_rows=rows)


def _lemma_manuscript(store: Store, *, full: str = LEMMA_FULL,
                      signed: bool = True) -> str:
    """被引命题自己的手稿（2026-11-08：可引资格从这一份稿上的 V 签读）。

    `signed=True` ⇒ 盖一块 3/3 的签（够格）；`False` ⇒ 只有正文、没有签（不够格）。
    不再靠 `statements.bits.reviewed` —— V 不读册。
    """
    rel = write_proof_manuscript(store.root, LEMMA, "1. 引理正文（夹具）。",
                                 statement_full=full)
    if signed:
        raw = (pathlib.Path(store.root) / rel).read_text(encoding="utf-8")
        stamped = VS.stamp_manuscript_sign(
            raw, proof_sha=VR.proof_sha("1. 引理正文（夹具）。"), streak=3, need=3,
            verdict="成立", signer="secretary:F", at=TS,
            ledger=f"verifications/{LEMMA}.jsonl#v-000001",
            statement_id=LEMMA, manuscript_id=LEMMA)
        (pathlib.Path(store.root) / rel).write_text(stamped, encoding="utf-8")
    return rel


def _submit():
    return CND.calling_as("t-v-000001", "V", parent_task_id="t-f-000001",
                          parent_role="F")


def _row(sid: str, quote: str, step: str = "第 1 步") -> dict:
    return {"quote": quote, "stmt_id": sid, "step": step, "path_group": 1}


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
    wired = True

    def __init__(self, answers: dict[str, list] | None = None) -> None:
        self.answers = {k: list(v) for k, v in (answers or {}).items()}

    def ask_json(self, prompt: str, *, system: str = "", task_id: str = "",
                 note: str = "") -> tuple[dict | None, _Call]:
        kind = note.split(":", 1)[-1]
        queue = self.answers.get(kind) or [{}]
        doc = queue.pop(0) if len(queue) > 1 else queue[0]
        return dict(doc), _Call()


def _axis(answer: str) -> dict:
    return {"checked": True, "decision": answer, "reason": "夹具：照规则判",
            "basis": ["夹具"]}


def _agent(store: Store, replies: list[str] | None = None) -> tuple[AgentV, _ReviewSeam]:
    review = _ReviewSeam(replies or [CLEAN_REPLY])
    seam = _Seam({"v_reply_defect": [_axis(SEC.V_REPLY_CLEAN)],
                  "sign_issuance": [_axis(SEC.SIGN_ISSUE)]})
    sec = SEC.Secretary("V", root=store.root, store=store, seam=seam,
                        enable_model=True)
    return AgentV(store, workspace_root=store.root, llm=review, secretary=sec), review


def _problems(got: dict) -> list[dict]:
    return [f for f in (got.get("findings") or [])
            if isinstance(f, dict) and str(f.get("level")) == "error"]


def _details(got: dict) -> str:
    return "；".join(str(f.get("detail") or "") for f in _problems(got))


def _expect_fault(got: dict, sid: str, *, step: int = 1) -> None:
    """一条"V 判有毛病、不签发、点名那个号"的判据（g / h / i 共用）。"""
    assert got.get("checked") is True, got
    assert got.get("verdict") == "有毛病", got
    assert got.get("defect_step") == step, got
    assert got.get("signed_bit3") is False, got
    assert sid in _details(got), got
    # 连判在第一转就停：判出有毛病就是终局（业主 2026-10-30：「直接打回」）。
    assert len(got.get("review_passes") or []) == 1, got.get("review_passes")


# ============================================================ g 不在册
def test_g_a_citation_of_an_unregistered_statement_is_a_defect(tmp_path):
    """g：正文点 `stmt:000099`（不在册）⇒ 有毛病、defect_step=1、detail 点名 ⇒ 不签发。

    改前红：V 的引用材料只读 `dependencies` 台账（这时 0 行），手稿 `## 依赖` 表与
    正文里的号一个字都不核 ⇒ 三转「成立」、签照样落。
    """
    st = _ws(tmp_path)
    body = (f"1. 由 stmt:{UNKNOWN} 直接推出结论。\n2. 于是主命题成立。")
    _put(st, SID, full=FULL, bits=_bits(), label="主命题", proof_text=body)
    rel = _manuscript(st, body=body, rows=[_row(UNKNOWN, "某条不存在的引理")])
    agent, _review = _agent(st)

    got = agent.verify_proof(SID, proof_text=body, proof_manuscript=rel)

    _expect_fault(got, UNKNOWN)
    assert "盘上没有" in _details(got), got
    assert "手稿" in _details(got), got
    # 判据是"这一签没落地"：台账那一行在（它是打回的凭据），但没有签块。
    rows, bad = VR.list_verifications(st.root, statement_id=SID, limit=None)
    assert not bad, bad
    assert [dict(r).get("verdict") for r in rows] == ["有毛病"], rows


# ============================================================ h 等级不够
def test_h_a_citation_below_the_floor_is_a_defect(tmp_path):
    """h：正文点一条在册但 `conjecture` 的号 ⇒ 有毛病，detail 写等级与门槛 ⇒ 不签发。"""
    st = _ws(tmp_path)
    body = (f"1. 由 stmt:{LEMMA} 的结论直接推出。\n2. 于是主命题成立。")
    _put(st, SID, full=FULL, bits=_bits(), label="主命题", proof_text=body)
    lemma = _put(st, LEMMA, full=LEMMA_FULL, bits=_bits(reviewed=False), label="猜想引理")
    assert DS.statement_grade(lemma) == "conjecture", lemma
    _lemma_manuscript(st, signed=False)   # 稿在、没有 V 签 ⇒ 低于门槛
    rel = _manuscript(st, body=body, rows=[_row(LEMMA, "上下文引理")])
    agent, _review = _agent(st)

    got = agent.verify_proof(SID, proof_text=body, proof_manuscript=rel)

    _expect_fault(got, LEMMA)
    detail = _details(got)
    assert "V 签" in detail, got
    assert DS.CITATION_MIN_LEVEL in detail, got
    assert got.get("signed_bit3") is False, got


# ============================================================ i 表与正文不一致
def test_i_a_table_row_the_body_never_cites_is_a_defect(tmp_path):
    """i：表里点了 `stmt:000008`，正文一步都没点它 ⇒ 有毛病、detail 点名 ⇒ 不签发。"""
    st = _ws(tmp_path)
    body = "1. 由定义直接计算。\n2. 于是主命题成立。"
    _put(st, SID, full=FULL, bits=_bits(), label="主命题", proof_text=body)
    lemma = _put(st, LEMMA, full=LEMMA_FULL, bits=_bits(reviewed=True), label="上下文引理")
    assert DS.statement_grade(lemma) == "pre_theorem", lemma
    _lemma_manuscript(st, signed=True)
    rel = _manuscript(st, body=body, rows=[_row(LEMMA, "表里多出来的那一行")])
    agent, _review = _agent(st)

    got = agent.verify_proof(SID, proof_text=body, proof_manuscript=rel)

    _expect_fault(got, LEMMA)
    assert "没有点" in _details(got), got
    assert got.get("signed_bit3") is False, got


# ============================================================ j 反真空
def test_j_stubbing_the_pool_check_lets_g_and_h_through_red(monkeypatch, tmp_path):
    """j：把可引资格判据打桩成恒真 ⇒ g 与 h 必须回到"放行并签上"。

    这证明 g/h 的绿来自那一条判据，而不是"恰好别处也走不通"。

    2026-11-08：可引资格的判据落点从册子换成手稿，唯一制造器是
    `depsection.manuscript_uncitable_finding`（六格）。把它打桩成恒 `{}` ⇒
    两个"不可引"的现场都必须放行。
    """
    monkeypatch.setattr(DS, "manuscript_uncitable_finding",
                        lambda sid, cited, **_kw: {})
    # 可引资格还有第二道：引用闸（`_citation_admissibility` 同一格）。审计松开之后，
    # 这一道也要松开 —— 否则"打桩恒真"只松开了半条链，判据量到的不是同一个东西。
    monkeypatch.setattr(AgentV, "_citation_admissibility", lambda self, grade: True)

    st = _ws(tmp_path / "g")
    body = (f"1. 由 stmt:{UNKNOWN} 直接推出结论。\n2. 于是主命题成立。")
    _put(st, SID, full=FULL, bits=_bits(), label="主命题", proof_text=body)
    rel = _manuscript(st, body=body, rows=[_row(UNKNOWN, "某条不存在的引理")])
    agent, _review = _agent(st, [_clean_with_check(UNKNOWN)])
    with _submit():
        got = agent.verify_proof(SID, proof_text=body, proof_manuscript=rel)
    assert got.get("review_write", {}).get("manuscript_signed") is True, (
        f"打桩成恒真之后 g 仍然被拒 ⇒ g 的绿不是 ① 给的：{got}")

    st2 = _ws(tmp_path / "h")
    body2 = (f"1. 由 stmt:{LEMMA} 的结论直接推出。\n2. 于是主命题成立。")
    _put(st2, SID, full=FULL, bits=_bits(), label="主命题", proof_text=body2)
    _put(st2, LEMMA, full=LEMMA_FULL, bits=_bits(reviewed=False), label="猜想引理")
    _lemma_manuscript(st2, signed=False)
    rel2 = _manuscript(st2, body=body2, rows=[_row(LEMMA, "上下文引理")])
    agent2, _review2 = _agent(st2, [_clean_with_check(LEMMA)])
    with _submit():
        got2 = agent2.verify_proof(SID, proof_text=body2, proof_manuscript=rel2)
    assert got2.get("review_write", {}).get("manuscript_signed") is True, (
        f"打桩成恒真之后 h 仍然被拒 ⇒ h 的绿不是 ② 给的：{got2}")


# ============================================================ k 正面
def test_k_a_clean_dependency_face_still_gets_signed(tmp_path):
    """k：在册 + `pre_theorem` + 表与正文一致 ⇒ V 判成立并签发（不许把好稿挡住）。"""
    st = _ws(tmp_path)
    body = (f"1. 由 stmt:{LEMMA} 的结论直接推出。\n2. 于是主命题成立。")
    _put(st, SID, full=FULL, bits=_bits(), label="主命题", proof_text=body)
    lemma = _put(st, LEMMA, full=LEMMA_FULL, bits=_bits(reviewed=True), label="上下文引理")
    assert DS.statement_grade(lemma) == "pre_theorem", lemma
    assert LEMMA in DS.citable_pool([lemma]), DS.citable_pool([lemma])
    _lemma_manuscript(st, signed=True)
    rel = _manuscript(st, body=body, rows=[_row(LEMMA, "上下文引理")])
    agent, review = _agent(st, [_clean_with_check(LEMMA)])

    with _submit():
        got = agent.verify_proof(SID, proof_text=body, proof_manuscript=rel)

    assert got.get("checked") is True, got
    assert got.get("verdict") == "成立", got
    assert got.get("signed_bit3") is False, got
    assert got.get("review_write", {}).get("manuscript_signed") is True, got["review_write"]
    assert _problems(got) == [], got.get("findings")
    assert review.asked() == 3, review.asked()

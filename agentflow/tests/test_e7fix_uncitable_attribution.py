# -*- coding: utf-8 -*-
"""E7 判据：V 读手稿时，「这一条不进可引池」与「等级读不出来」是两件事、两个码。

## 现场（本案要修的那一条）

`projects/lp-ball-12/verifications/reviews/v-review-000002.md`（2026-11-20T04:09:29）第 2 步：

    [error] 第 2 步 · citation_level_unreadable：`stmt:000030`…
    类别：等级读不出来（判不了）（`citation_level_unreadable`）
    期望：盘上有一份这一条命题的手稿（`reports/f-proof-<号>.md`…）

而 `stmt:000030` 是 `kind=concept` / `origin=external_lit`（见该工作区
`data/statements.json`），盘上从来没有、也不会有 `reports/f-proof-000030.md`。
`evidencebits.derive_grade` 对 `kind=concept` 短路成 `not_applicable` ⇒ 它不进等级链，
所以"盘上没有它的稿"是结构，不是"读不到"；旧读数把这两件事并进同一个码，
还让 fix 去叫 F 给一条概念写证明稿。

## 三档（凑齐，不许再共用）

| 编号 | 现场 | 该读到 |
|---|---|---|
| a | 在册的 `kind=concept`（引文侧 `origin=external_lit`）命题被引、盘上无稿 | 新码 `citation_not_in_citable_pool`（「不进可引池」） |
| b | 在册的普通命题被引、盘上无稿（该有稿而没读到） | 照旧 `citation_level_unreadable`（负控：别把两件事合成一个新的模糊码） |
| c | 有稿、稿上没有盖住正文的签 | 照旧 `citation_below_proof_review` |

`d` 钉"三档三码、都仍然拦得住"；`f` 是正控（有稿有签的照旧可引 ⇒ 门槛没被这一改收紧）；
`e` 是反真空（把 a 的新归因打桩回旧码 ⇒ a 必红）。

判据对象是 `depsection.manuscript_uncitable_finding`（V 那一档的唯一制造器），
它经由 `AgentV.verify_proof` 的机械依赖面审计落到 `verdict=有毛病`。
"""
from __future__ import annotations

import json
import pathlib

import pytest

from _proof_manuscript_fixture import write_proof_manuscript
from agentflow import depsection as DS
from agentflow import evidencebits as EB
from agentflow import secretary as SEC
from agentflow import verifications as VR
from agentflow import vsigns as VS
from agentflow.agent_v import AgentV
from agentflow.store import Store

TS = "2026-11-20T04:09:29+08:00"
SID = "000007"
LEMMA = "000008"
CONCEPT = "000030"
FULL = "主命题：这一份手稿的依赖面要被 V 逐条核。"
LEMMA_FULL = "上下文引理：被引用的那一条。"
CONCEPT_FULL = "ℓp 球 K_p：由范数诱导的凸体。"

CLEAN_REPLY = json.dumps({"verdict": "成立", "why": "重读一遍，未发现问题。",
                          "findings": []}, ensure_ascii=False)


def _clean_with_check(sid: str) -> str:
    return json.dumps({
        "verdict": "成立", "why": "重读一遍，未发现问题。", "findings": [],
        "citation_checks": [{"stmt_id": sid, "verdict": "consistent",
                             "quote_verbatim": False, "note": "夹具：用法一致"}],
    }, ensure_ascii=False)


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


def _ws(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _put(store: Store, sid: str, *, full: str, kind: str = "theorem",
         origin: str = "own_result", bits: dict | None = None, label: str = "") -> dict:
    """铺一条在册命题（`kind` / `origin` 正是这一判据要分的那两根轴）。

    `origin="external_lit"` 必须带出处（`schema.Statement.validate` 的硬口径），
    所以这一档顺手补一个文献号 + 页码范围 —— 与现场 `stmt:000030` 同形。
    """
    row = {
        "stmt_id": sid, "origin": origin, "kind": kind,
        "label": label or full[:12], "statement_full": full, "statement_text": full[:24],
        "proof_text": "", "evidence_kind": "heuristic",
        "status": "active", "quote_verified": None,
        "quote_reason": "夹具：这一条是铺出来的", "created_at": TS, "created_by": "test",
        "bits": dict(bits or {}),
    }
    if origin == "external_lit":
        row.update(source_lit_id="000000", page_range={"start": 1})
    with store.tx("statements", actor="test") as tx:
        tx.upsert("statements", row)
    return row


def _bits(*, reviewed: bool = False) -> dict:
    return EB.bits_of(proof=True, proof_process="夹具正文", reviewed=reviewed,
                      reviewed_by=({"verification_id": "v-0001"} if reviewed else None),
                      kind="theorem")


def _row(sid: str, quote: str, step: str = "第 1 步") -> dict:
    return {"quote": quote, "stmt_id": sid, "step": step, "path_group": 1}


def _manuscript(store: Store, *, body: str, rows: list[dict]) -> str:
    return write_proof_manuscript(store.root, SID, body, statement_full=FULL,
                                  deps_rows=rows)


def _cited_manuscript(store: Store, sid: str, *, full: str, body: str,
                      signed: bool) -> str:
    """被引命题自己的稿（`signed=False` ⇒ 只有正文、没有签）。"""
    rel = write_proof_manuscript(store.root, sid, body, statement_full=full)
    if not signed:
        return rel
    raw = (pathlib.Path(store.root) / rel).read_text(encoding="utf-8")
    stamped = VS.stamp_manuscript_sign(
        raw, proof_sha=VR.text_sha(body), streak=3, need=3,
        verdict="成立", signer="secretary:F", at=TS,
        ledger=f"verifications/{sid}.jsonl#v-000001",
        statement_id=sid, manuscript_id=sid)
    (pathlib.Path(store.root) / rel).write_text(stamped, encoding="utf-8")
    return rel


def _agent(store: Store, replies: list[str] | None = None) -> AgentV:
    review = _ReviewSeam(replies or [CLEAN_REPLY])
    seam = _Seam({"v_reply_defect": [_axis(SEC.V_REPLY_CLEAN)],
                  "sign_issuance": [_axis(SEC.SIGN_ISSUE)]})
    sec = SEC.Secretary("V", root=store.root, store=store, seam=seam,
                        enable_model=True)
    return AgentV(store, workspace_root=store.root, llm=review, secretary=sec)


def _finding(got: dict, sid: str) -> dict:
    for item in got.get("findings") or []:
        if not isinstance(item, dict) or str(item.get("level")) != "error":
            continue
        if f"stmt:{sid}" in str(item.get("detail") or ""):
            return item
    raise AssertionError(
        f"没找到点名 stmt:{sid} 的那条 error finding：{got.get('findings')}")


def _expect_code(got: dict, sid: str, code: str) -> dict:
    """这一条被引号必须落到 `code` 那一档（并仍然拦得住这一签）。"""
    assert got.get("checked") is True, got
    assert got.get("verdict") == "有毛病", got
    assert got.get("signed_bit3") is False, got
    item = _finding(got, sid)
    assert item["kind"] == code, item
    assert DS.CITATION_KIND_LABELS[code] in item["detail"], item["detail"]
    return item


def _scene(tmp_path: pathlib.Path, tier: str) -> dict:
    """三档现场各铺一次（a / b / c），返回 `(V 的读数, 被引号, 该档的码)`。"""
    st = _ws(tmp_path / tier)
    _put(st, SID, full=FULL, bits=_bits(reviewed=True))
    if tier == "a":
        body = f"1. 由 stmt:{CONCEPT} 的定义直接展开。\n2. 于是主命题成立。"
        _put(st, CONCEPT, full=CONCEPT_FULL, kind="concept", origin="external_lit",
             label="ℓp 球 K_p")
        cited, code = CONCEPT, DS.REFUSED_NOT_IN_POOL
        rows = [_row(CONCEPT, "ℓp 球 K_p 的定义")]
    elif tier == "b":
        body = f"1. 由 stmt:{LEMMA} 的结论直接推出。\n2. 于是主命题成立。"
        # 这一条"该有稿而盘上没有"：故意不落 `reports/f-proof-000008.md`。
        _put(st, LEMMA, full=LEMMA_FULL, kind="lemma", bits=_bits())
        cited, code = LEMMA, DS.REFUSED_LEVEL_UNREADABLE
        rows = [_row(LEMMA, "上下文引理")]
    elif tier == "c":
        body = f"1. 由 stmt:{LEMMA} 的结论直接推出。\n2. 于是主命题成立。"
        _put(st, LEMMA, full=LEMMA_FULL, kind="lemma", bits=_bits())
        _cited_manuscript(st, LEMMA, full=LEMMA_FULL,
                          body="1. 引理正文（夹具）。", signed=False)
        cited, code = LEMMA, DS.REFUSED_LEVEL_TOO_LOW
        rows = [_row(LEMMA, "上下文引理")]
    else:  # pragma: no cover —— 参数由下面的用例固定
        raise AssertionError(tier)
    rel = _manuscript(st, body=body, rows=rows)
    got = _agent(st).verify_proof(SID, proof_text=body, proof_manuscript=rel)
    return {"got": got, "sid": cited, "code": code, "store": st, "body": body,
            "rel": rel, "tier": tier}


# ============================================================ a 不进可引池
def test_a_a_cited_concept_row_is_read_as_not_in_the_pool(tmp_path):
    """a：引一条在册的 `kind=concept`（`origin=external_lit`）、盘上无稿的命题。

    改前红：它落到 `citation_level_unreadable`（"等级读不出来（判不了）"），
    而 fix 还在叫 F 给一条概念写证明稿 —— 与 v-review-000002 第 2 步同形。
    改后：`citation_not_in_citable_pool`，且这一签照样签不下来（门槛不动）。
    """
    scene = _scene(tmp_path, "a")
    item = _expect_code(scene["got"], scene["sid"], scene["code"])

    assert item["kind"] != DS.REFUSED_LEVEL_UNREADABLE, item
    # 归因分开了：这一档说的不是"判不了"，而是"它本来就不在池子里"。
    assert "不进可引池" in item["detail"], item["detail"]
    # 台账那一行的 `kind` 逐字进实得（读报告的人据此知道"为什么它不该被引"）；
    # 台账那一行的格式由 `verifications.parse_verdict` 钉成四格，所以这里读人话那一格。
    assert "kind=concept" in item["detail"], item["detail"]
    # 这一条被引的概念本身不许被读成"错"：它仍是 active、等级仍是 not_applicable
    # （概念没有真值可言 —— 既不进等级链，也不该被这条判据改写）。
    rows = {str(r.get("stmt_id")): dict(r) for r in scene["store"].rows("statements")}
    concept_row = rows[CONCEPT]
    assert str(concept_row.get("status")) == "active", concept_row
    assert DS.statement_grade(concept_row) == EB.GRADE_NOT_APPLICABLE, concept_row
    assert DS.statement_grade(concept_row) != EB.GRADE_ERROR, concept_row
    # 也不许反过来说人家"不在册"（V 读到的是台账那一行）。
    assert "不在册" not in item["detail"], item["detail"]


# ============================================================ b 负控
def test_b_a_registered_row_without_a_manuscript_stays_level_unreadable(tmp_path):
    """b（负控）：在册的普通命题被引、盘上没有它的稿 ⇒ 仍是 `citation_level_unreadable`。

    这一档与 a 的区别是"该有稿而没读到"：给它补一份稿、让 V 签，它就能进池
    （见 f）—— 所以它不许被并进 a 那个新码，否则读的人拿不到那句正确的下一步。
    """
    scene = _scene(tmp_path, "b")
    item = _expect_code(scene["got"], scene["sid"], scene["code"])

    assert "盘上没有" in item["detail"], item["detail"]
    assert "不进可引池" not in item["detail"], item["detail"]


# ============================================================ c 第三档
def test_c_a_manuscript_without_a_sign_is_the_third_tier(tmp_path):
    """c：稿在盘上、正文也对，但没有盖住它的 V 签 ⇒ `citation_below_proof_review`。"""
    scene = _scene(tmp_path, "c")
    item = _expect_code(scene["got"], scene["sid"], scene["code"])

    assert "V 签" in item["detail"], item["detail"]
    assert DS.CITATION_MIN_LEVEL in item["detail"], item["detail"]


# ============================================================ d 三档三码
@pytest.mark.parametrize("tier", ["a", "b", "c"])
def test_d_the_three_tiers_are_three_codes_and_all_three_still_block(
        tmp_path, tier: str):
    """d：三档凑齐 ⇒ 一档一码；每一档都仍然"拒 + 不签发"（门槛不在这一改的射程里）。"""
    scene = _scene(tmp_path, tier)
    item = _expect_code(scene["got"], scene["sid"], scene["code"])
    assert scene["got"].get("defect_step") == 1, scene["got"]
    # 三档的码两两不等 —— 且都不是"一句模糊话"：码各自有类别名，名字也不许共用。
    others = {"a": DS.REFUSED_LEVEL_UNREADABLE, "b": DS.REFUSED_NOT_IN_POOL,
              "c": DS.REFUSED_NOT_IN_POOL}[tier]
    assert item["kind"] != others, item
    labels = {DS.CITATION_KIND_LABELS[code] for code in
              (DS.REFUSED_NOT_IN_POOL, DS.REFUSED_LEVEL_UNREADABLE,
               DS.REFUSED_LEVEL_TOO_LOW)}
    assert len(labels) == 3, labels


# ============================================================ e 反真空
def test_e_stubbing_the_new_attribution_back_to_the_old_code_turns_a_red(
        monkeypatch, tmp_path):
    """e：把 a 的新归因打桩回旧码 ⇒ a 必红（证明 a 的绿来自这一条判据本身）。"""
    scene = _scene(tmp_path, "a")
    agent = _agent(scene["store"])

    monkeypatch.setattr(DS, "_out_of_pool_reason", lambda item: "")
    got = agent.verify_proof(SID, proof_text=scene["body"], proof_manuscript=scene["rel"])
    with pytest.raises(AssertionError):
        _expect_code(got, scene["sid"], scene["code"])
    # 打桩之后它回到旧码 —— 这一句同时说明"旧读数就是那个样子"。
    assert _finding(got, scene["sid"])["kind"] == DS.REFUSED_LEVEL_UNREADABLE

    monkeypatch.undo()
    good = agent.verify_proof(SID, proof_text=scene["body"], proof_manuscript=scene["rel"])
    _expect_code(good, scene["sid"], scene["code"])


# ============================================================ f 正控
def test_f_a_signed_manuscript_is_still_citable(tmp_path):
    """f（正控）：同一条引理、稿上盖着 V 签 ⇒ 照旧可引、照常签上（门槛没被收紧）。"""
    st = _ws(tmp_path)
    body = f"1. 由 stmt:{LEMMA} 的结论直接推出。\n2. 于是主命题成立。"
    _put(st, SID, full=FULL, bits=_bits(reviewed=True))
    _put(st, LEMMA, full=LEMMA_FULL, kind="lemma", bits=_bits())
    _cited_manuscript(st, LEMMA, full=LEMMA_FULL,
                      body="1. 引理正文（夹具）。", signed=True)
    rel = _manuscript(st, body=body, rows=[_row(LEMMA, "上下文引理")])

    got = _agent(st, [_clean_with_check(LEMMA)]).verify_proof(
        SID, proof_text=body, proof_manuscript=rel)

    assert got.get("checked") is True, got
    assert got.get("verdict") == "成立", got
    assert [f for f in (got.get("findings") or [])
            if str(f.get("level")) == "error"] == [], got.get("findings")

"""R3 组 9（EE-07 / F-01）：`bits` 的产出方 —— `B.register_statement` 同事务写五元位。

判据是"同一份读数从 0 变成 >0"：`statements` 行里 `bits` 是非空 mapping。
改前真机读数（`temp/_r3_baseline.py`）：138 行命题、带 bits 0 行。

三态（不许折叠）：

- 算得出 ⇒ 与命题那一行同一次事务写进去（事件里那一条 upsert 的 row 里就有 bits）；
- 算不出 ⇒ 如实记（`kind="bits_compute_failed"`，带异常类型与原文），不写空 bits
  —— 盘上一个空 bits 读出来是"五位全空"，与"我们没算"长得一模一样；
- 形状不合规 ⇒ `kind="bad_bits"` + `problems` 逐条，整笔不写。

判据只用 `evidencebits`（`bits_shape_problems` / `bit_problems`），这里不抄第二份口径。
"""
from __future__ import annotations

import json

from agentflow import evidencebits as EB
from agentflow import schema as S
from agentflow.agent_b import AgentB

from conftest import add_literature, write_library_file

CREATED = "2026-01-01T00:00:00+08:00"


def _agent(store) -> AgentB:
    return AgentB(store, extractor=None, extract_text=None, config={})


def _lit(store, lid: str = "0000") -> str:
    write_library_file(store, f"{lid}/a.txt", "正文")
    add_literature(store, lid, title="A", path=f"{lid}/a.txt")
    return lid


def _external(**over) -> dict:
    row = {"statement_full": "设 G 是有限群。",
           "origin": "external_lit", "page_range": {"start": 1},
           "proof_text": "Proof. 逐字摘录。", "quote_verified": True}
    row.update(over)
    return row


def _bits_rows(store) -> list[dict]:
    """盘上有 bits 的行（口径与 `temp/_r3_baseline.py` 逐字一致：非空 mapping 才算有）。"""
    return [r for r in store.rows("statements") if isinstance(r.get("bits"), dict) and r.get("bits")]


def _statement_events(store) -> list[dict]:
    """events.jsonl 里 `statements` 的 upsert 事件（用来证明 bits 是同一次事务写的）。"""
    out = []
    for line in store.events_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        ev = json.loads(line)
        if ev.get("op") == "upsert" and ev.get("table") == "statements":
            out.append(ev)
    return out


# --------------------------------------------------------------- 算得出（产出方落地）

def test_external_lit_with_verbatim_quote_lands_bits_in_the_same_transaction(store):
    """正控：逐字核过的引用命题 ⇒ 第 2+3 位由 `bits_of` 按「引用」点亮，等级现算。"""
    lid = _lit(store)
    res = _agent(store).register_statement(source_lit_id=lid, **_external())

    assert res["ok"] is True, res
    rows = _bits_rows(store)
    assert len(rows) == 1, f"产出方必须把 bits 写进盘里（改前：带 bits 0 行）：{store.rows('statements')}"
    bits = rows[0]["bits"]
    assert bits["proof"] is True and bits["reviewed"] is True, bits
    assert bits["evidence"]["proof_source"] == "citation", bits["evidence"]
    assert bits["evidence"]["reviewed_by"]["evidence"] == f"lit:{lid}", bits["evidence"]
    assert bits["grade"] == "pre_theorem", bits
    assert EB.bit_problems(bits) == [] and EB.bits_shape_problems(bits) == [], bits
    assert EB.bits_from_row(rows[0])["grade"] == bits["grade"], "读侧与写侧必须现算出同一个等级"

    events = _statement_events(store)
    assert len(events) == 1, f"这次登记应当只有一条 upsert 事件：{events}"
    assert events[0]["row"]["bits"], (
        "bits 不在那一条 upsert 的 row 里 ⇒ 它是事务外补写的（改前那种『先写行、回头再补』"
        "正是这条要求要堵的形态）"
    )


def test_own_result_proof_text_lights_bit_two_but_decides_no_grade(store):
    """自产命题写了证明摘录 ⇒ 第 2 位为真；但第 3 位（V 的审）不在这一跳 ⇒ 仍是猜想。"""
    _lit(store)
    res = _agent(store).register_statement(
        statement_full="对每个 m ≥ 5，k = 3 都有无穷多个例子。",
        origin="own_result", doc_id="0000", proof_text="证明：逐步论证。",
        quote_reason="自有结果，没有引文可比对（三态里的那一句『为什么』）")

    assert res["ok"] is True, res
    bits = _bits_rows(store)[0]["bits"]
    assert bits["proof"] is True and bits["evidence"]["proof_source"] == "own", bits
    assert bits["reviewed"] is False, "登记这一刻没有 V 的结论 ⇒ 不许替 V 签"
    assert bits["grade"] == "conjecture", bits
    assert EB.bit_problems(bits) == [], bits


def test_own_result_without_proof_is_an_honest_conjecture_with_bits(store):
    """F-05 那一档（缺 proof_text）不许被这次接线改掉：仍然入库、仍然如实降级。"""
    _lit(store)
    b = _agent(store)
    res = b.register_statement(statement_full="我们猜：对每个素数 p 都有 …。",
                               origin="own_result", doc_id="0000",
                               quote_reason="证明还没做完 / 未核到")

    assert res["ok"] is True, res
    assert res["pending"] and res["pending"][0]["kind"] == "missing_proof", res
    bits = _bits_rows(store)[0]["bits"]
    assert bits["proof"] is False and bits["grade"] == "conjecture", bits
    assert EB.bit_problems(bits) == [], bits


# --------------------------------------------------------------- 负控（三条）

def test_negative_control_bad_bits_shape_writes_nothing(store, monkeypatch):
    """负控 ①：形状不合规 ⇒ 整笔不写（与其余几级硬校验同一条契约）。"""
    lid = _lit(store)
    monkeypatch.setattr(EB, "bits_of", lambda **kw: {
        "numeric": "verified",              # verified 没带凭据
        "grade": "theorem",                 # 自报等级，与五位现算不符
        "拼错的键": 1,                       # 不认识的键
    })
    res = _agent(store).register_statement(source_lit_id=lid, **_external())

    assert res["ok"] is False and res["kind"] == "bad_bits", res
    assert "拼错的键" in res["error"] and "grade" in res["error"], res["error"]
    assert store.rows("statements") == [], "形状不合规必须整笔不写，不许留下半行"


def test_negative_control_compute_failure_is_recorded_not_written_as_empty(store, monkeypatch):
    """负控 ②：算不出 ⇒ 如实记（带异常原文），不写空 bits 冒充「五位全空」。"""
    lid = _lit(store)

    def boom(**kw):
        raise RuntimeError("evidencebits 炸了")

    monkeypatch.setattr(EB, "bits_of", boom)
    res = _agent(store).register_statement(source_lit_id=lid, **_external())

    assert res["ok"] is False and res["kind"] == "bits_compute_failed", res
    assert "RuntimeError" in res["error"] and "evidencebits 炸了" in res["error"], res["error"]
    assert store.rows("statements") == [], "算不出时写一行空 bits，等于把『没算』记成『五位全空』"


def test_negative_control_the_read_side_is_not_the_producer(store):
    """负控 ③（顺序）：读侧在产出方之后 —— 盘上没有 bits 时，读侧再怎么读也变不出这一栏。

    旧行（无 bits）本来就有读数：`bits_from_row` 对「逐字核过的引用命题」有那条例外
    （第 2+3 位由文献代号点亮）。可 R3 的判据数的是盘上那一栏 ⇒ 只改读侧不会让
    138 行里的任何一行变成「带 bits」。这一条把两者钉开，免得有人拿读侧的绿当产出方的绿。
    """
    lid = _lit(store)
    old = S.Statement(stmt_id="0000", origin="external_lit", statement_full="旧行：设 G 是有限群。",
                      proof_text="Proof. 旧行的逐字摘录。", source_lit_id=lid,
                      quote_verified=True, created_at=CREATED, created_by="legacy")
    old.validate()
    with store.tx("statements", actor="legacy") as tx:
        tx.upsert("statements", old.to_dict(), note="legacy_row")

    rows = store.rows("statements")
    assert rows and not rows[0].get("bits"), "旧行的盘上形状就是没有 bits（改前的 138 行同形）"
    assert EB.bits_from_row(rows[0])["grade"] == "pre_theorem", (
        "读侧对『逐字核过的引用命题』那条例外本来就在（这不是本次接线的功劳）"
    )
    assert _bits_rows(store) == [], "读侧读出什么都不改变这一栏：0 还是 0"

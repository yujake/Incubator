# -*- coding: utf-8 -*-
"""判据（FIXJUDGE，2026-11-19 业主口径）：同一份材料只判一次，判过必留痕。

## 业主的设计口径（逐字）

```
「为什么会被判两次？第一次录入时会经 B 秘书，优化表达后是直接登记，多路径时是各路径
  自己有非平凡度，设计上不可能撞车」
```

⇒ 同一份材料（同一 `judged_body_sha`）只能判一次：录入经 B 秘书判一次；之后优化表达
走直接登记不再判；多路径时是各路径各有非平凡度（路径号不同才允许各判一次）。
撞车 = 缺陷。

## 现场（`projects/lp-ball-11`，见 `temp/r11n/R11N-REPORT.md`）

| 时刻 | 谁 | 做了什么 | 盘上读数 |
|---|---|---|---|
| 17:50:27 | 真录入（经 B 秘书） | 判档一次 | `out/secretary/nontriviality.jsonl` 第 11 行（T0） |
| 17:59:35 | D 的 `own.write_report` 内联调 B 的收录口（`agent_d/write_report.py:487→:988`） | 同一份材料又判一次 | `B.jsonl#6`（T1，$0.002274），档位台账没有新行 |
| 同一刻 | `register_statement.py:4625-4649`「收方读稿登记」成功早退 | 在落行（`:5533`）之前 `return` | `_finish_filing_nontriviality:3587` 只在 `out.ok is not True` 时补留痕 ⇒ 两本账都沉默 |

两次的 `judged_body_sha` 逐字相同（`b1a02806bde9…`）。

## 本文件的判据

| # | 硬约束 | 判据 |
|---|---|---|
| a | 同一材料第二次交 ⇒ 不判（调用数不增、决定台账不增） | A |
| b | 多路径（`path_group` 不同）⇒ 各判一次（正控） | B |
| c | 材料变了（sha 不同）⇒ 重判（正控） | C |
| d | 判了但落不了行 ⇒ 决定台账有「判过未落」+ `fail_open=true` | D |
| e | 反真空：打桩掉 ① 的短路 ⇒ A 的读数变红；打桩掉 ③ 的记录臂 ⇒ D 的读数变红；把短路写宽（不看 sha/路径）⇒ B、C 变红 | E1 / E2 / E3 |

零模型钱：秘书的 `judge` 全部打桩（只数"判了几次"），工作区全在 `tmp_path`。
"""
from __future__ import annotations

import json
import pathlib
import sys
from typing import Any

import pytest

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agentflow import depsection as DS  # noqa: E402
from agentflow import schema as S  # noqa: E402
from agentflow import secretary as SEC  # noqa: E402
from agentflow.agent_b import AgentB  # noqa: E402
from agentflow.store import Store  # noqa: E402

_TEXT = "设 S 是有限集；则 S 的子集个数为 2^|S|。"
_PROOF = "证明：对每个元素决定在与不在，共 2^|S| 种。"
_PROOF_2 = "证明：用归纳法。|S|=n+1 时拆出一个元素，由 2^n 乘 2 得 2^(n+1)。"
_REL = "reports/f-proof-000000.md"


# ---------------------------------------------------------------- 夹具

def _ws(tmp_path: pathlib.Path, *, proof: str = _PROOF) -> Store:
    """一个带签名手稿的空工作区（签按证明正文 sha 认领，与真机同一条路）。"""
    from conftest import sign_before_registration

    store = Store(tmp_path / "ws")
    store.init()
    book = store.root / _REL
    book.parent.mkdir(parents=True, exist_ok=True)
    book.write_text(
        "## 命题\n" + _TEXT + "\n\n## 证明\n" + proof + "\n\n"
        + DS.render_dependency_section([]), encoding="utf-8")
    sign_before_registration(store.root, proof_text=str(proof))
    return store


def _b(store: Store, *, calls: list[str] | None = None) -> tuple[AgentB, SEC.Secretary]:
    """B + 它的秘书；秘书的 `judge` 打桩（只记"判了几次"，零模型钱）。"""
    def _judge(kind: str, context: Any, task_id: str = "", note: str = "") -> dict:
        if calls is not None:
            calls.append(str(kind))
        return {"checked": True, "decision": "T0", "nontriviality": 0,
                "nontriviality_basis": "一行推导", "reason": "一行推导",
                "cost": {"ledger": "", "reason": "夹具"}}

    sec = SEC.Secretary("B", root=store.root, store=store)
    sec.judge = _judge  # type: ignore[assignment]  —— 实例属性不绑 self，签名与调用点同形
    return AgentB(store, extractor=None, extract_text=None, secretary=sec), sec


def _register(b: AgentB) -> dict:
    """第一次录入（经 B 秘书）：与 `tests/test_nontriviality_is_per_path.py` 的 P2 同形。"""
    return b.register_statement(
        statement_full=_TEXT, statement_text=_TEXT, origin="own_result",
        derived_from=["999999"], kind="conjecture", label="S 的子集个数",
        proof_text=_PROOF, evidence_kind="heuristic", proof_manuscript=_REL,
        doc_id=S.format_id(0), line_range={"label": _REL},
        quote_verified=False,
        quote_reason="own_result：我方推导，没有第二份文本可比对")


def _deliver_same(b: AgentB, stmt_id: str) -> dict:
    """D 的 `own.write_report` 那条路（`write_report.py:487→:988`）：只递指针。"""
    return b.register_statement(proof_manuscript=_REL,
                                line_range={"label": f"stmt:{stmt_id}"})


def _ledger(root: pathlib.Path) -> list[dict[str, Any]]:
    path = SEC.nontriviality_path(root)
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def _decisions(sec: SEC.Secretary) -> list[dict[str, Any]]:
    path = sec.decisions_path()
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def _has_judged_trace(sec: SEC.Secretary, root: pathlib.Path) -> bool:
    """③ 的不变式：判过一次 ⇒ 档位台账多一行或决定台账多一行「判过未落」。"""
    if _ledger(root):
        return True
    return any(str(r.get("decision") or "") == "判过未落" for r in _decisions(sec))


# ================================================================ a）同一材料不重判

def test_a_the_second_delivery_of_the_same_material_is_not_judged(
        tmp_path: pathlib.Path) -> None:
    """a：同一份材料第二次交（D 内联递同一份稿）⇒ 不判，两本账都不增。

    改前红（lp-ball-11 17:59:35 的真机形态）：`judge` 被调第二次（$0.002274），
    `B.jsonl` 多一行决定，而档位台账一笔都不增 —— 钱花了、读数没落地。

    ## 第二次为什么换一个 B 实例

    `Secretary._statement_verdicts` 只是本趟进程内的缓存（真机那次判档发生在 D 的
    另一趟 run 里，缓存是空的 ⇒ 真花了第二次钱）。所以这里也必须用新实例：拿同一实例
    去测，"不判"会被那个缓存冒充，判据就分辨不出"持久层真的不重判"。
    """
    store = _ws(tmp_path)
    calls: list[str] = []
    first_b, sec = _b(store, calls=calls)
    first = _register(first_b)
    assert first.get("ok") is True, first
    sid = str(first["stmt_id"])
    rows = _ledger(store.root)
    assert len(rows) == 1, rows
    assert rows[0]["stmt_id"] == sid and int(rows[0]["path_group"]) >= 1, rows[0]
    decisions_before = _decisions(sec)

    second_b, sec2 = _b(store, calls=calls)   # 另一趟 run：本趟缓存是空的
    second = _deliver_same(second_b, sid)
    assert second.get("ok") is True, second
    assert second.get("new_row") is False, second
    # ① 不判：模型调用数不增
    assert len(calls) == 1, f"同一份材料被判了 {len(calls)} 次（应只判 1 次）：{calls}"
    # ① 不写决定台账（两趟都读同一个 `out/secretary/B.jsonl`）
    assert _decisions(sec2) == decisions_before, _decisions(sec2)[len(decisions_before):]
    # 档位台账也不许多一行（幂等：同一材料不追加）
    assert len(_ledger(store.root)) == 1, _ledger(store.root)
    # 读数没有丢：回执里仍然带着那一档（读给调用方看）
    rec = dict(second.get("nontriviality_record") or {})
    assert rec.get("reused") is True and rec.get("recorded") is False, rec
    assert (second.get("statement_tier") or {}).get("tier") == "T0", second.get("statement_tier")


# ================================================================ b）多路径各判一次

def test_b_a_second_path_is_judged_once_per_path(tmp_path: pathlib.Path) -> None:
    """b：`path_group` 不同 ⇒ 各判一次（正控：不许把多路径一起挡掉）。

    路径号是这一问的一部分（业主：「多路径时是各路径自己有非平凡度」）。同一份材料
    在第 1 条路径上已判过 ⇒ 不判；第 2 条路径 ⇒ 判一次；第 2 条路径再交一次 ⇒ 不判。
    """
    store = Store(tmp_path / "ws")
    store.init()
    sid = "000005"
    SEC.append_nontriviality(
        store.root, statement_full=_TEXT, level=0, stmt_id=sid, path_group=1,
        judged_body_sha256=SEC._judged_body_sha(_TEXT, _PROOF), basis="路径 1 的读数")
    calls: list[str] = []
    b, sec = _b(store, calls=calls)

    same_path = b._judge_filing_nontriviality(
        statement_full=_TEXT, proof_text=_PROOF, stmt_id=sid, path_group=1)
    assert same_path.get("reused") is True, same_path
    assert calls == [], f"同一路径同一材料又判了一次：{calls}"

    other_path = b._judge_filing_nontriviality(
        statement_full=_TEXT, proof_text=_PROOF, stmt_id=sid, path_group=2)
    assert calls == ["statement_aesthetic"], f"第 2 条路径没有各判一次：{calls}"
    assert other_path.get("reused") is not True, other_path

    sec.record_nontriviality(
        other_path, stmt_id=sid, path_group=2, statement_full=_TEXT,
        judged_body_sha256=SEC._judged_body_sha(_TEXT, _PROOF))
    again = b._judge_filing_nontriviality(
        statement_full=_TEXT, proof_text=_PROOF, stmt_id=sid, path_group=2)
    assert again.get("reused") is True, again
    assert len(calls) == 1, f"第 2 条路径被判了两次：{calls}"


# ================================================================ c）材料变了要重判

def test_c_changed_material_is_judged_again(tmp_path: pathlib.Path) -> None:
    """c：同一命题换了证明正文（sha 不同）⇒ 重新判一次（正控）。"""
    store = Store(tmp_path / "ws")
    store.init()
    sid = "000006"
    SEC.append_nontriviality(
        store.root, statement_full=_TEXT, level=0, stmt_id=sid, path_group=1,
        judged_body_sha256=SEC._judged_body_sha(_TEXT, _PROOF), basis="旧材料")
    calls: list[str] = []
    b, _sec = _b(store, calls=calls)

    changed = b._judge_filing_nontriviality(
        statement_full=_TEXT, proof_text=_PROOF_2, stmt_id=sid, path_group=1)
    assert calls == ["statement_aesthetic"], f"材料变了却没有重判：{calls}"
    assert changed.get("reused") is not True, changed


# ================================================================ d）判过未落要留痕

def test_d_a_judged_but_unlanded_reading_leaves_a_decision_row(
        tmp_path: pathlib.Path) -> None:
    """d：判了、但回执里没有档位行（号/路径号缺）⇒ 决定台账有「判过未落」+ `fail_open=true`。

    改前红：`_finish_filing_nontriviality:3587` 只在 `out.ok is not True` 时补留痕 ⇒
    成功早退这一支（`ok=True`、没有 `record` 键）两本账都沉默（lp-ball-11 17:59:35）。
    """
    store = Store(tmp_path / "ws")
    store.init()
    b, sec = _b(store)
    reading = {"checked": True, "decision": "T1", "nontriviality": 1,
               "nontriviality_tri": "computed", "nontriviality_basis": "判过了",
               "effort": {}, "text_truncated": False,
               "statement_full": _TEXT, "proof_text": _PROOF}
    out = {"ok": True, "stmt_id": "000005"}
    got = b._finish_filing_nontriviality(out, reading)
    rec = dict(got.get("nontriviality_record") or {})
    assert rec.get("tri") == "unrecorded", got
    # 档位台账没有多行（没有号就没法落"一个路径一行"），但决定台账必须留痕。
    assert _ledger(store.root) == [], _ledger(store.root)
    hit = [r for r in _decisions(sec) if str(r.get("decision") or "") == "判过未落"]
    assert len(hit) == 1, _decisions(sec)
    assert hit[0].get("fail_open") is True, hit[0]
    assert "unrecorded" in (hit[0].get("basis") or []), hit[0]
    assert _has_judged_trace(sec, store.root), "判过了，两本账都沉默"


# ================================================================ f）判了就得落行

def test_f_a_successful_early_return_lands_the_tier_row(tmp_path: pathlib.Path) -> None:
    """f（③ 的正控）：判了、成功早退 ⇒ 档位台账真的多一行（不是只留「判过未落」）。

    现场：命题在册、证明与在册那一版逐字相同（收方读稿登记那条早退支路），但台账里
    还没有它的档位行（例如上一次判档没落成）。这一笔判完之后，收尾那一臂必须凭
    `(stmt_id, path_group)` 把那一行落下来 —— 路径号从在册那一行的 `proof_no` 兜底
    （`_receipt_path_group`：这一支本来就是"正文与在册那一版没有不同"那一档）。
    """
    store = _ws(tmp_path)
    calls: list[str] = []
    b, _sec = _b(store, calls=calls)
    first = _register(b)
    assert first.get("ok") is True, first
    sid = str(first["stmt_id"])
    # 把档位台账清掉：等价于"命题在册，但这一份材料还没有档位行"。
    SEC.nontriviality_path(store.root).unlink()

    b2, sec2 = _b(store, calls=calls)   # 另一趟 run：本趟缓存是空的
    got = _deliver_same(b2, sid)
    assert got.get("ok") is True, got
    assert len(calls) == 2, f"材料没判过（台账是空的）却没有判：{calls}"
    rows = _ledger(store.root)
    assert len(rows) == 1, f"判了、成功早退，档位台账仍没有行：{rows}"
    assert rows[0]["stmt_id"] == sid, rows[0]
    assert int(rows[0]["path_group"]) >= 1, rows[0]
    rec = dict(got.get("nontriviality_record") or {})
    assert rec.get("recorded") is True, got
    assert _has_judged_trace(sec2, store.root), "判过了，两本账都沉默"


# ================================================================ e）反真空

def test_e1_without_the_shortcut_the_same_material_is_judged_twice(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """e-①：把「同一材料已判过 ⇒ 不再判」的短路打桩掉 ⇒ A 的那条读数必红。

    这里把短路打桩成恒 `None`（= 改前：每次都判），断言确实会判第二次 ——
    于是 `test_a` 的 `len(calls) == 1` 不可能靠"反正只判一次"通过。
    """
    store = _ws(tmp_path)
    calls: list[str] = []
    b, _sec = _b(store, calls=calls)
    monkeypatch.setattr(AgentB, "_prior_filing_nontriviality",
                        lambda self, **kw: None, raising=True)
    first = _register(b)
    sid = str(first["stmt_id"])
    _deliver_same(_b(store, calls=calls)[0], sid)   # 另一趟 run（缓存空）
    assert len(calls) == 2, (
        f"短路打桩掉之后仍只判 {len(calls)} 次 ⇒ a 的绿不是短路给的：{calls}")


def test_e2_without_the_record_arm_a_judged_reading_leaves_no_trace(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """e-③：把记录臂打桩掉（只返回一个空 record，不写任何台账）⇒ D 的不变式必红。"""
    store = Store(tmp_path / "ws")
    store.init()
    b, sec = _b(store)
    monkeypatch.setattr(
        AgentB, "_record_filing_nontriviality",
        lambda self, reading, **kw: {"recorded": False, "tri": "unrecorded",
                                     "reason": "夹具：记录臂被打桩掉"},
        raising=True)
    reading = {"checked": True, "decision": "T1", "nontriviality": 1,
               "nontriviality_tri": "computed", "nontriviality_basis": "判过了",
               "effort": {}, "text_truncated": False,
               "statement_full": _TEXT, "proof_text": _PROOF}
    out = b._finish_filing_nontriviality({"ok": True, "stmt_id": "000005"}, reading)
    assert (out.get("nontriviality_record") or {}).get("tri") == "unrecorded", out
    assert _has_judged_trace(sec, store.root) is False, (
        "记录臂打桩掉之后仍留下了判过痕迹 ⇒ d 的绿不是记录臂给的")


def test_e3_a_blanket_shortcut_turns_the_positive_controls_red(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """e-补：把短路打桩成"这条命题判过一次就跳过"（不看 sha、不看路径号）⇒ b/c 必红。

    这一条守的是另一种改坏的方式：短路写得太宽（只要有行就跳过）会把多路径与"材料
    变了"一起挡掉。断言这种打桩下 b（第 2 条路径）与 c（材料变了）都不再判。
    """
    def _blanket(self, *, stmt_id: str = "", statement_full: str = "",
                 proof_text: str = "", path_group: int = 0) -> dict | None:
        got = SEC.nontriviality_rows(getattr(self.store, "root", ""), stmt_id=stmt_id)
        if not got.get("checked") or not (got.get("rows") or []):
            return None
        return {"checked": True, "decision": "T0", "nontriviality": 0,
                "nontriviality_tri": "computed", "reused": True,
                "statement_full": statement_full, "proof_text": proof_text,
                "stmt_id": stmt_id, "path_group": int(path_group or 1),
                "record": {"recorded": False, "reused": True}}

    store = Store(tmp_path / "ws")
    store.init()
    sid = "000007"
    SEC.append_nontriviality(
        store.root, statement_full=_TEXT, level=0, stmt_id=sid, path_group=1,
        judged_body_sha256=SEC._judged_body_sha(_TEXT, _PROOF), basis="路径 1")
    calls: list[str] = []
    b, _sec = _b(store, calls=calls)
    monkeypatch.setattr(AgentB, "_prior_filing_nontriviality", _blanket, raising=True)

    other_path = b._judge_filing_nontriviality(
        statement_full=_TEXT, proof_text=_PROOF, stmt_id=sid, path_group=2)
    changed = b._judge_filing_nontriviality(
        statement_full=_TEXT, proof_text=_PROOF_2, stmt_id=sid, path_group=1)
    assert other_path.get("reused") is True, "打桩没生效"
    assert changed.get("reused") is True, "打桩没生效"
    assert calls == [], (
        "一刀切的短路把第 2 条路径 / 改了的材料也挡掉了 ⇒ b、c 必红（它们要的就是"
        f"这两个各判一次）；实际 calls={calls}")

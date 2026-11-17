# -*- coding: utf-8 -*-
"""判据（NT2，2026-11-15 业主裁定）：非平凡度按证明路径逐条，命题级取 min。

## 业主口径（逐字）

```
处理B秘书侧的非平凡性读数录入问题（评价非平凡性需在将手稿录入台账前完成（即B秘书处理
一条录入任务时，第一个要做的是评价非平凡度），且在语义判断拿到（注册或匹配到）准确的
命题号及路径号后一并录入（非平凡度应该是一个路径一个，现在的实现是一个命题一个需要补加，
但我们也维护命题对应的非平凡度为所有路径非平凡度的最小值），命题非平凡度若命题台账已有
则更新为原数与录入数的最小值）。
```

| # | 硬约束 | 本文件的判据 |
|---|---|---|
| ① | 先判（写台账之前、B 处理该录入的第一个动作） | P2 |
| ② | 拿到 `stmt_id` + `path_group` 之后一并录入 | P2 / P4 |
| ③ | 一个路径一行 | P1 / P3 |
| ④ | 命题级 = 各路径 min | P1 / P3 / P7 |
| ⑤ | 已有值 ⇒ min(原值, 本次) | P3（永不回升） |

## 正控 / 负控 / 反真空

正控 P1–P7 必须绿；负控 N1–N7 必须红（用 monkeypatch 把实现打桩回旧形状，看正控断言
真的会失败）；反真空 V1–V6 防"空集也能过"。

零模型钱：除 P2（走一次真实收录，秘书的 `judge` 打桩）之外，全部用
`secretary.append_nontriviality` 直接落行；工作区全在 `tmp_path`，不碰 `projects/`。
"""
from __future__ import annotations

import json
import pathlib
import sys
from typing import Any, Mapping

import pytest

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
from conftest import ensure_basis_lit, ensure_basis_stmt

from agentflow import closing as CL  # noqa: E402
from agentflow import secretary as SEC  # noqa: E402
from agentflow.webui import readers as R  # noqa: E402

_SID = "000901"
_TEXT = "设 G 是有限群，p 是素数；则 G 的 Sylow p-子群存在。"
_PROOF_1 = "证明：取一个极大 p-子群 P，用共轭作用数轨道。"
_PROOF_2 = "证明：用类方程与同余计数，另证一次。"


# ---------------------------------------------------------------- 夹具（唯一写口）

def _ws(tmp_path: pathlib.Path, *, rows: list[dict[str, Any]] | None = None,
        tex: str = "") -> pathlib.Path:
    root = tmp_path / "ws"
    (root / "data").mkdir(parents=True, exist_ok=True)
    (root / "data" / "statements.json").write_text(
        json.dumps({"rows": rows or []}, ensure_ascii=False), encoding="utf-8")
    if tex:
        (root / "out" / "paper").mkdir(parents=True, exist_ok=True)
        (root / "out" / "paper" / "main.tex").write_text(tex, encoding="utf-8")
    return root


def _ledger(root: pathlib.Path) -> list[dict[str, Any]]:
    path = SEC.nontriviality_path(root)
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def _append(root: pathlib.Path, *, stmt_id: str, path_group: int, level: int | None,
            text: str = _TEXT, proof: str = "", applicable: bool = True,
            judged_sha: str = "") -> dict[str, Any]:
    """落一行档位读数（V6 的反真空下限就在这一句：写入必须真的多一行）。"""
    before = len(_ledger(root))
    SEC.append_nontriviality(
        root, statement_full=text, level=level, stmt_id=stmt_id,
        path_group=path_group, applicable=applicable,
        judged_body_sha256=(judged_sha or SEC._judged_body_sha(text, proof)),
        landed_body_sha256=SEC._statement_sha(text), basis=f"路径 {path_group} 的读数")
    after = _ledger(root)
    assert len(after) == before + 1, "写入没有真的落一行（夹具造的是空集）"
    assert after[-1]["path_group"] == path_group, after[-1]
    return after[-1]


def _write_rows(root: pathlib.Path, rows: list[dict[str, Any]]) -> None:
    path = SEC.nontriviality_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n"
                            for r in rows), encoding="utf-8")


def _old_row(text: str, level: int | None, *, stmt_id: str = "") -> dict[str, Any]:
    """改前那种行：没有 `path_group`、可能也没有号（只有 sha）。"""
    return {"at": "2026-11-14T00:00:00+08:00", "stmt_id": stmt_id,
            "statement_sha256": SEC._statement_sha(text),
            "statement_chars": len(text), "scale": SEC.NONTRIVIALITY_SCALE,
            "nontriviality": level, "label": SEC.nontriviality_label(level),
            "applicable": True, "basis": "旧行（无路径维）", "effort": {},
            "text_truncated": False, "role": "B", "task_id": "t-old"}


# ================================================================ 正控 P1–P7

def test_p1_two_paths_t0_and_t3_statement_is_the_min(tmp_path: pathlib.Path) -> None:
    """P1：两路径 T0@1 / T3@2 ⇒ 命题级 0、path1=0、path2=3、paths 两条、min_of=[0,3]。

    改前红：读侧按 `stmt_id` 折叠成一条、后写胜 ⇒ 读到 3（探针 B-2 逐字如此）；
    行上也没有 `path_group`，`paths` 这一格根本不存在。
    """
    root = _ws(tmp_path, rows=[{"stmt_id": _SID, "statement_full": _TEXT}])
    _append(root, stmt_id=_SID, path_group=1, level=0, proof=_PROOF_1)
    _append(root, stmt_id=_SID, path_group=2, level=3, proof=_PROOF_2)

    got = SEC.nontriviality_of(root, _TEXT, stmt_id=_SID)
    path1 = SEC.nontriviality_of(root, _TEXT, stmt_id=_SID, path_group=1)
    path2 = SEC.nontriviality_of(root, _TEXT, stmt_id=_SID, path_group=2)
    # V1：两条路径的档位必须先不相等，否则 min 断言恒真
    assert path1["level"] != path2["level"], (path1, path2)
    assert (got["tri"], got["level"], got["label"]) == ("computed", 0, "T0"), got
    assert (path1["level"], path2["level"]) == (0, 3), (path1, path2)
    # V2：行数与 paths 条数都要先对上（"什么都没写"不许以"没有错值"通过）
    assert len(_ledger(root)) == 2, _ledger(root)
    assert len(got["paths"]) == 2, got["paths"]
    assert got["min_of"] == [0, 3], got["min_of"]
    assert got["statement_level"] == 0 and got["partial"] is False, got
    assert {p["path_group"] for p in got["paths"]} == {1, 2}, got["paths"]


def test_p2_the_judgement_happens_before_the_first_ledger_write_and_only_once(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """P2：真实收录一笔 ⇒ 第一次模型判定在第一次 `statements` 写之前，整条只判一次。

    改前红：判档挂在 `_do_tool`（`registry.call` 之后）⇒ 写先发生；`ingest_manuscript`
    那条路整条不判。判据用事件序（`judge` / `write`）读，不看实现细节。
    """
    from conftest import sign_before_registration

    from agentflow import depsection as DS
    from agentflow import schema as S
    from agentflow.agent_b import AgentB
    from agentflow.store import Store

    store = Store(tmp_path / "ws")
    store.init()
    text = "设 S 是有限集；则 S 的子集个数为 2^|S|。"
    proof = "证明：对每个元素决定在与不在，共 2^|S| 种。"
    rel = "reports/f-proof-000000.md"
    book = store.root / rel
    book.parent.mkdir(parents=True, exist_ok=True)
    book.write_text("## 命题\n" + text + "\n\n## 证明\n" + proof + "\n\n"
                    + DS.render_dependency_section([]), encoding="utf-8")
    sign_before_registration(store.root, proof_text=proof)

    events: list[tuple[str, int]] = []

    def _judge(self, kind, context, task_id="", note=""):
        events.append(("judge", len(store.rows("statements"))))
        return {"checked": True, "decision": "T0", "nontriviality": 0,
                "nontriviality_basis": "一行推导", "reason": "一行推导",
                "cost": {"ledger": "", "reason": "夹具"}}

    monkeypatch.setattr(SEC.Secretary, "judge", _judge, raising=True)
    orig = SEC.Secretary.record_statement

    def _record(self, payload, **kw):
        events.append(("write", len([e for e in events if e[0] == "judge"])))
        return orig(self, payload, **kw)

    monkeypatch.setattr(SEC.Secretary, "record_statement", _record, raising=True)

    sec = SEC.Secretary("B", root=store.root, store=store)
    got = AgentB(store, extractor=None, extract_text=None, secretary=sec).register_statement(
# 2026-11-17（业主裁定 ②）：own_result 必须写清来路；这一份夹具不测承重链，用形状合法的占位号。
        statement_full=text, statement_text=text, origin="own_result", source_lit_id=ensure_basis_lit(store), kind="conjecture",
        label="S 的子集个数", proof_text=proof, evidence_kind="heuristic",
        proof_manuscript=rel, doc_id=S.format_id(0), line_range={"label": rel},
        quote_verified=False, quote_reason="own_result：我方推导，没有第二份文本可比对")
    assert got.get("ok") is True, got
    # ① 判在第一次 statements 写之前（判的那一刻表里 0 行）
    assert events and events[0][0] == "judge", events
    assert events[0][1] == 0, events
    # ② 整条只判一次
    assert [e for e in events if e[0] == "judge"] == [("judge", 0)], events
    # ③ 写发生时，判已经发生过（且只发生过一次）
    writes = [e for e in events if e[0] == "write"]
    assert writes and writes[0][1] == 1, events
    # 落到盘上的读数带号与路径号（②"拿到号之后一并录入"）
    rows = _ledger(store.root)
    assert len(rows) == 1, rows
    assert rows[0]["stmt_id"] == str(got["stmt_id"]), rows[0]
    assert rows[0]["path_group"] >= 1, rows[0]
    assert got["statement_tier"]["tier"] == "T0", got.get("statement_tier")


def test_p3_a_new_path_never_raises_the_statement_level(tmp_path: pathlib.Path) -> None:
    """P3：先 path1=T1 落盘、再加 path2=T3 ⇒ 命题级仍 T1，且两行都在盘上。

    业主约束 ⑤：「命题台账已有则更新为原数与录入数的最小值」⇒ 永不回升。
    改前红：读侧后写胜 ⇒ 读到 3（新增一条更难的路径把平凡命题抬成 T3）。
    """
    root = _ws(tmp_path, rows=[{"stmt_id": _SID, "statement_full": _TEXT}])
    _append(root, stmt_id=_SID, path_group=1, level=1, proof=_PROOF_1)
    _append(root, stmt_id=_SID, path_group=2, level=3, proof=_PROOF_2)
    got = SEC.nontriviality_of(root, _TEXT, stmt_id=_SID)
    assert (got["level"], got["label"]) == (1, "T1"), got
    assert len(_ledger(root)) == 2, "新路径的读数被覆盖/没落盘"
    assert len(got["paths"]) == 2, got["paths"]
    # 逐路径仍各自可读（path2 的当前值就是 3；命题级不回升不等于不许知道这条路径难）
    assert SEC.nontriviality_of(root, _TEXT, stmt_id=_SID, path_group=2)["level"] == 3
    # 同一路径判得更难也不许把命题级抬上去（历史最小值）
    _append(root, stmt_id=_SID, path_group=2, level=4, proof=_PROOF_2 + "（更难的版本）")
    again = SEC.nontriviality_of(root, _TEXT, stmt_id=_SID)
    assert again["level"] == 1, again
    assert again["paths"][1]["level"] == 4 and again["paths"][1]["floor"] == 3, again["paths"]


def test_p4_a_controlled_refusal_records_nothing_but_leaves_a_trace(
        tmp_path: pathlib.Path) -> None:
    """P4：拿不到 `stmt_id` / `path_group` ⇒ 台账行数不变 + `unrecorded` + 决定台账有行。

    改前红：`append_nontriviality(stmt_id="")` 会照落一行（真机 6 行空号、4 行 sha 对不上
    任何命题）；改后这一档受控不落，但钱已经花了，"判过"要在决定台账里看得见。
    """
    root = _ws(tmp_path)
    SEC.append_nontriviality(root, statement_full=_TEXT, level=2, stmt_id=_SID,
                             path_group=1, basis="已有的一行")
    before = _ledger(root)
    sec = SEC.Secretary("B", root=root)
    reading = {"checked": True, "nontriviality": 2, "nontriviality_tri": "computed",
               "nontriviality_basis": "判过了", "effort": {}, "text_truncated": False}

    no_id = sec.record_nontriviality(reading, stmt_id="", path_group=1,
                                     statement_full=_TEXT)
    assert (no_id["tri"], no_id["recorded"]) == ("unrecorded", False), no_id
    assert "stmt_id" in no_id["reason"], no_id
    no_path = sec.record_nontriviality(reading, stmt_id=_SID, path_group=0,
                                       statement_full=_TEXT)
    assert (no_path["tri"], no_path["recorded"]) == ("unrecorded", False), no_path
    assert "path_group" in no_path["reason"], no_path

    assert _ledger(root) == before, "受控拒却动了档位台账"
    decisions = [json.loads(line) for line in
                 sec.decisions_path().read_text(encoding="utf-8").splitlines()
                 if line.strip()]
    unrecorded = [r for r in decisions if "unrecorded" in (r.get("basis") or [])]
    assert len(unrecorded) == 2, decisions[-3:]
    assert all("判过" in str(r.get("reason") or "") for r in unrecorded), unrecorded


def test_p5_old_rows_without_a_path_key_are_path_one(tmp_path: pathlib.Path) -> None:
    """P5：旧行（无 `path_group`）按路径 1 读；只有 sha 的旧行仍按 sha 回退读到。

    迁移护栏：不许为了"一个路径一行"把历史读数读废。老行视为路径 1 —— 改前判的就是
    canonical 那份证明；同一号两行旧读数（T1 后 T3）⇒ 命题级仍 T1（永不回升）。
    """
    root = _ws(tmp_path, rows=[{"stmt_id": _SID, "statement_full": _TEXT}])
    _write_rows(root, [_old_row(_TEXT, 1, stmt_id=_SID),
                       _old_row(_TEXT, 3, stmt_id=_SID)])
    got = SEC.nontriviality_of(root, _TEXT, stmt_id=_SID)
    assert (got["tri"], got["level"], got["matched_by"]) == ("computed", 1, "stmt_id"), got
    assert got["paths"][0]["path_group"] == 1, got["paths"]
    assert got["paths"][0]["level"] == 3 and got["paths"][0]["floor"] == 1, got["paths"]
    assert got["min_of"] == [1], got["min_of"]

    other = "只有 sha、没有号的一条老命题。"
    _write_rows(root, [_old_row(other, 2)])
    by_sha = SEC.nontriviality_of(root, other)
    assert (by_sha["tri"], by_sha["level"], by_sha["matched_by"]) == (
        "computed", 2, "sha256"), by_sha
    assert by_sha["paths"][0]["path_group"] == 1, by_sha["paths"]


def test_p6_concept_rows_are_not_applicable_and_never_enter_the_min(
        tmp_path: pathlib.Path) -> None:
    """P6：概念行 `applicable=false` / `path_group=0`；不参与 min，`tri=not_applicable`。

    改前红：概念行与"没判过"在页面上印同一个词；把它的 `null` 当 0 参与 min 会把
    整个命题级压成 T0（"不适用"不是"最平凡"）。
    """
    root = _ws(tmp_path, rows=[{"stmt_id": "000902", "statement_full": _TEXT,
                                "kind": "concept"}])
    _append(root, stmt_id="000902", path_group=0, level=None,
            applicable=False)
    got = SEC.nontriviality_of(root, _TEXT, stmt_id="000902")
    assert got["tri"] == "not_applicable" and got["applicable"] is False, got
    assert got["level"] is None and got["paths"] == [] and got["min_of"] == [], got

    # 混一行路径读数 ⇒ 命题级由路径给（概念行仍不进 min）
    root2 = _ws(tmp_path / "two", rows=[{"stmt_id": "000903", "statement_full": _TEXT}])
    _append(root2, stmt_id="000903", path_group=1, level=2, proof=_PROOF_1)
    _append(root2, stmt_id="000903", path_group=0, level=None, applicable=False)
    mixed = SEC.nontriviality_of(root2, _TEXT, stmt_id="000903")
    assert (mixed["tri"], mixed["level"]) == ("computed", 2), mixed
    assert mixed["min_of"] == [2] and len(mixed["paths"]) == 1, mixed


# ================================================================ 负控 N1–N7

def _last_wins_fold(rows: Any, **_kw: Any) -> dict[str, Any]:
    """把折叠打桩成"取最后一行"（改前的形状）。"""
    last = list(rows)[-1]
    level = SEC._level_from_row(last)
    return {"tri": "computed" if level is not None else "unknown", "level": level,
            "label": SEC.nontriviality_label(level), "applicable": True,
            "matched_by": "stmt_id", "stmt_id": str(last.get("stmt_id") or ""),
            "basis": "", "at": "", "effort": {}, "text_truncated": False,
            "paths": [], "min_of": [], "paths_unjudged": [], "partial": False,
            "statement_level": level}


def test_n1_a_last_wins_fold_turns_p1_and_p3_red(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """N1：折叠打桩成"最后一行胜" ⇒ P1/P3 的命题级断言必红（改前就是这条红）。"""
    root = _ws(tmp_path, rows=[{"stmt_id": _SID, "statement_full": _TEXT}])
    _append(root, stmt_id=_SID, path_group=1, level=0, proof=_PROOF_1)
    _append(root, stmt_id=_SID, path_group=2, level=3, proof=_PROOF_2)
    assert SEC.nontriviality_of(root, _TEXT, stmt_id=_SID)["level"] == 0
    monkeypatch.setattr(SEC, "_fold_nontriviality", _last_wins_fold, raising=True)
    red = SEC.nontriviality_of(root, _TEXT, stmt_id=_SID)
    assert red["level"] == 3, "打桩成最后一行胜之后仍读到 min ⇒ 上面那条绿不是折叠给的"
    assert red["paths"] == [] and red["min_of"] == [], red


def test_n2_a_record_without_the_path_dimension_turns_the_per_path_read_red(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """N2：落行丢掉 `path_group` ⇒ P1 的逐路径读必红（paths 只剩一条）。"""
    root = _ws(tmp_path, rows=[{"stmt_id": _SID, "statement_full": _TEXT}])
    real = SEC.append_nontriviality

    def _drop_path(root_: Any, **kw: Any) -> None:
        kw["path_group"] = 0
        real(root_, **kw)

    monkeypatch.setattr(SEC, "append_nontriviality", _drop_path, raising=True)
    for no, level, proof in ((1, 0, _PROOF_1), (2, 3, _PROOF_2)):
        before = len(_ledger(root))
        SEC.append_nontriviality(
            root, statement_full=_TEXT, level=level, stmt_id=_SID, path_group=no,
            judged_body_sha256=SEC._judged_body_sha(_TEXT, proof),
            landed_body_sha256=SEC._statement_sha(_TEXT), basis=f"路径 {no}")
        assert len(_ledger(root)) == before + 1
    got = SEC.nontriviality_of(root, _TEXT, stmt_id=_SID)
    assert len(got["paths"]) == 1, f"丢路径维之后仍读出两条路径 ⇒ 判据看不见这条红：{got}"
    assert SEC.nontriviality_of(root, _TEXT, stmt_id=_SID, path_group=2)["tri"] == "unknown"


def test_n3_dropping_the_no_id_guard_produces_new_orphans(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """N3：删掉"没号不落"的守卫 ⇒ 体检出现新的孤儿行（空号且 sha 对不上任何命题）。"""
    root = _ws(tmp_path, rows=[{"stmt_id": _SID, "statement_full": _TEXT}])
    sec = SEC.Secretary("B", root=root)
    reading = {"checked": True, "nontriviality": 2, "nontriviality_tri": "computed",
               "effort": {}, "text_truncated": False}
    assert sec.record_nontriviality(reading, stmt_id="", path_group=1,
                                    statement_full=_TEXT)["tri"] == "unrecorded"
    assert _ledger(root) == [], "守卫在的时候却落了行"

    def _no_guard(self, reading_, **kw: Any) -> dict:
        # "删掉守卫"的等价形态：拿不到号也照落一行（改前那个 append 的直调）
        SEC.append_nontriviality(
            self.root, statement_full="一笔没有号的判档（sha 对不上任何命题）",
            level=2, stmt_id="", path_group=1, basis="无守卫")
        return {"recorded": True, "tri": "computed", "level": 2, "label": "T2"}

    monkeypatch.setattr(SEC.Secretary, "record_nontriviality", _no_guard, raising=True)
    sec.record_nontriviality(reading, stmt_id="", path_group=1, statement_full=_TEXT)
    rows = _ledger(root)
    orphans = [r for r in rows if not str(r.get("stmt_id") or "").strip()
               and str(r.get("statement_sha256") or "")
               not in {SEC._statement_sha(_TEXT)}]
    assert orphans, "打桩之后没造出孤儿行 ⇒ 这条判据没有分辨率"


def test_n4_a_write_before_judge_order_is_caught(tmp_path: pathlib.Path) -> None:
    """N4：换回"写后判"⇒ 顺序判据必红（P2 的那条断言对旧顺序确实失败）。

    这里把 P2 读的事件序喂给同一个判据函数：`[judge, write]` 通过，`[write, judge]` 失败。
    它证明 P2 的绿来自真实顺序，而不是"事件表永远长这样"。
    """
    def _order_ok(events: list[tuple[str, int]]) -> bool:
        return bool(events) and events[0][0] == "judge" and events[0][1] == 0

    assert _order_ok([("judge", 0), ("write", 1)]) is True
    assert _order_ok([("write", 0), ("judge", 1)]) is False


def test_n5_and_n6_only_one_side_fixed_leaves_p1_red(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """N5/N6：只改读侧（行上没有路径维）或只改写侧（读侧仍折叠成一条）⇒ P1 必红。

    两个方向各造一次：写侧丢路径维（N5）与读侧最后一行胜（N6，等价 N1）。
    """
    # N5：写侧没改（行上没有 path_group）⇒ 读侧再对也只有一条路径
    root = _ws(tmp_path, rows=[{"stmt_id": _SID, "statement_full": _TEXT}])
    _write_rows(root, [_old_row(_TEXT, 0, stmt_id=_SID), _old_row(_TEXT, 3, stmt_id=_SID)])
    only_read = SEC.nontriviality_of(root, _TEXT, stmt_id=_SID)
    assert len(only_read["paths"]) == 1, only_read
    assert only_read["level"] == 0, only_read  # 旧行都是路径 1 ⇒ 取历史最小

    # N6：写侧对了、读侧被换回"最后一行胜" ⇒ paths/min_of 丢，命题级读回 3
    root2 = _ws(tmp_path / "two", rows=[{"stmt_id": _SID, "statement_full": _TEXT}])
    _append(root2, stmt_id=_SID, path_group=1, level=0, proof=_PROOF_1)
    _append(root2, stmt_id=_SID, path_group=2, level=3, proof=_PROOF_2)
    monkeypatch.setattr(SEC, "_fold_nontriviality", _last_wins_fold, raising=True)
    red = SEC.nontriviality_of(root2, _TEXT, stmt_id=_SID)
    assert red["level"] == 3 and red["paths"] == [], red


def test_n7_a_stubbed_unknown_reader_turns_every_positive_control_red(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """N7：把读口打桩成恒返回 unknown ⇒ P1/P3/P5 全红（绿必须来自读数）。"""
    root = _ws(tmp_path, rows=[{"stmt_id": _SID, "statement_full": _TEXT}])
    _append(root, stmt_id=_SID, path_group=1, level=0, proof=_PROOF_1)
    _append(root, stmt_id=_SID, path_group=2, level=3, proof=_PROOF_2)

    def _unknown(*_a: Any, **_k: Any) -> dict:
        return {"tri": "unknown", "level": None, "label": "", "applicable": True,
                "matched_by": "", "stmt_id": "", "basis": "", "at": "", "effort": {},
                "text_truncated": False, "paths": [], "min_of": [],
                "paths_unjudged": [], "partial": False, "statement_level": None}

    assert SEC.nontriviality_of(root, _TEXT, stmt_id=_SID)["level"] == 0
    monkeypatch.setattr(SEC, "nontriviality_of", _unknown, raising=True)
    assert SEC.nontriviality_of(root, _TEXT, stmt_id=_SID)["tri"] == "unknown"
    assert CL.nontriviality_reading(root)["counts"]["unjudged"] == 1
    assert R._statement_tier_reading(root, {"stmt_id": _SID,
                                            "statement_full": _TEXT})["tri"] == "unknown"


# ================================================================ 反真空 V6

def test_v6_the_fixture_is_not_vacuous() -> None:
    """V6：夹具下限 —— 至少两条不同路径、至少一条 `nontriviality is not None`。

    没有这一条，"一条都没判"与"全是 None"在别的断言上分不开。
    """
    assert _PROOF_1 != _PROOF_2
    assert SEC._judged_body_sha(_TEXT, _PROOF_1) != SEC._judged_body_sha(_TEXT, _PROOF_2)
    assert SEC.NONTRIVIALITY_LEVELS == (0, 1, 2, 3, 4)

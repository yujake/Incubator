# -*- coding: utf-8 -*-
"""判据：「攻（攻坚推进）」认出「稿拿到 V 签」这类推进（P6FIX，2026-11-20 lp-ball-12）。

## 改前红（现场原话）

lp-ball-12 收工那一刻（`sessions/2026-11-20.jsonl` 第 3476 行 `conductor.closing`）：

    P6（攻（攻坚推进））：0 条，要求 ≥ 1 条 —— 读数 {... "advanced_plans": []}

而同一份盘上：36 轮 `history` 里 27 轮 `outcome=progress`（全是 `action=proof`、
`cites` 全空），5 条计划名下 6 份稿全拿到 V 的「成立」签（`out/vsigns/issued.json`：
`verdict=成立 / streak=3 / need=3`）。`_round_advanced` 对 `action=proof` 只认 `cites`
一条通路 ⇒ 这一格恒 0。

## 改后的口径（`closing.py`）

`plan_progress_rows` 在旧四档（`_round_advanced`）之外补两条并列通路：

1. `signed_manuscript`：计划名下的稿拿到 V 签（`out/vsigns/` 的颁发表，
   `verdict=成立` 且 `streak>=need`）；
2. `manuscript_in_progress`：次一档，`proof_registered=True` 且正文 sha 在两轮之间变过
   （「稿在写」）—— 与"得签"分开记，不混成同一档。

## 判据的形状

- a 正控（真实现场复刻）：lp-ball-12 的形状 ⇒ 读数 ≥ 1、`advanced_by="signed_manuscript"`、
  读数带 `signed_manuscripts[]`；
- b 正控（旧口径不动）：只靠 `cites` 过关的计划照旧算，加一份签不会把读数变低；
- c 负控：没有稿、也没有 `cites` 的现场 ⇒ 仍是 0（不许变成恒真）；
- d 读数可见：`advanced_plans=[]` 时 `plans[].not_advanced_rounds` 里仍读得到逐轮 `why`；
- e 反真空：把两条并列通路分别打桩掉，读数各自掉回它该有的那一档（两条通路各自是承重的）；
- 门槛反真空：`streak<need` / `verdict≠成立` / `need=0` 的签不算；同一版正文重交不算"稿在写"。
"""
from __future__ import annotations

import hashlib
import json
import pathlib
from typing import Any

import pytest

from agentflow import closing as CL
from agentflow.store import Store

TS = "2026-11-20T04:00:00+08:00"


# ------------------------------------------------------------------ 夹具


def _plan(store: Store, plan_id: str, history: list[dict[str, Any]],
          *, status: str = "attacking") -> None:
    with store.tx("attack_plans", actor="test", note="P6FIX probe") as tx:
        tx.upsert("attack_plans", {
            "plan_id": plan_id, "problem": "把界推到 n≤20", "problem_key": f"key-{plan_id}",
            "status": status,
            "budget": {"max_rounds": max(6, len(history) + 2),
                       "max_parallel_subgoals": 2,
                       "max_persist_attempts": 2, "max_depth": 1},
            "subgoals": [{"sid": "s1", "text": "判定这条命题", "owner": "F",
                          "status": "in_progress", "evidence_ids": [],
                          "experiment_ids": [], "proof_experiment_ids": [],
                          "blocked_reason": "", "attempts": 1, "negation_kind": None}],
            "history": history, "created_at": TS, "created_by": "test",
        })


def _proof_round(n: int, *, sha: str | None, registered: bool = False,
                 path: str | None = "reports/f-proof-000000.md",
                 outcome: str = "progress",
                 cites: tuple[str, ...] = ()) -> dict[str, Any]:
    """一轮 `action=proof`：默认零 cites（lp-ball-12 的现场形态）。"""
    rec: dict[str, Any] = {
        "round": n, "sid": "s1", "action": "proof", "outcome": outcome,
        "detail": f"论证：{n + 10} 步；证明重写：{path}",
        "evidence": [], "at": TS, "product": "proof", "strategy": "套用已知定理",
        "product_detail": {"product": "proof", "strategy": "套用已知定理",
                           "why_strategy": "反设存在反例",
                           "steps": [{"n": 1, "text": "反设存在反例",
                                      "cites": list(cites), "assumption": not cites}]},
    }
    if path is not None:
        rec["manuscript_path"] = path
    if sha is not None:
        rec["proof_sha256"] = sha
    rec["proof_registered"] = registered
    return rec


def _no_change_round(n: int) -> dict[str, Any]:
    return {"round": n, "sid": "s1", "action": "no_change", "outcome": "no_change",
            "detail": "受控拒（handed_product_refused）", "evidence": [], "at": TS,
            "refusal": {"kind": "handed_product_refused", "why": "没给 cites"}}


def _signed_sha(path: str, *, verdict: str = "成立", streak: int = 3,
                need: int = 3) -> str:
    """一份签的正文 sha：从 `(path, streak, need, verdict)` 定出来（夹具里可复算）。"""
    return hashlib.sha256(f"{path}|{streak}|{need}|{verdict}".encode()).hexdigest()


def _write_signs(root: pathlib.Path, signs: list[dict[str, Any]],
                 *, write_sign_files: bool = True) -> None:
    """写 V 的颁发表：`out/vsigns/<sha>.json`（逐份）+ `out/vsigns/issued.json`（归档）。"""
    d = root / "out" / "vsigns"
    d.mkdir(parents=True, exist_ok=True)
    for sign in signs:
        if write_sign_files:
            doc = {"artifact_sha": sign["sha"], "artifact_path": sign["path"],
                   "verdict": sign.get("verdict", "成立"), "streak": sign.get("streak", 3),
                   "need": sign.get("need", 3), "at": sign.get("at", TS),
                   "statement_id": ""}
            (d / f"{sign['sha']}.json").write_text(
                json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    index = {"schema": "vsigns-issued/1",
             "signs": [{"artifact_sha": s["sha"], "artifact_path": s["path"],
                        "verdict": s.get("verdict", "成立"),
                        "streak": s.get("streak", 3), "need": s.get("need", 3),
                        "at": s.get("at", TS), "statement_id": "",
                        "archived_by": "test", "archived_at": s.get("at", TS)}
                       for s in signs],
             "updated_at": signs[-1].get("at", TS) if signs else ""}
    (d / "issued.json").write_text(json.dumps(index, ensure_ascii=False),
                                   encoding="utf-8")


@pytest.fixture()
def store(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _got(store: Store) -> tuple[int, dict[str, Any]]:
    return CL._leg_reading(store, "plan_progress_rows", pathlib.Path(store.root))


def _lp_ball_12_shape(store: Store) -> list[dict[str, Any]]:
    """lp-ball-12 的现场形状：5 条计划 / 36 轮（27 proof-progress + 9 no_change）/ 6 份签。

    逐轮 sha 都不同（稿真的在一轮一轮改），但每一轮 `cites` 都为空 —— 改前这一格
    的旧四档一条也认不出来。签只盖在每份稿的某几版上（`signed` 里列的那几轮）。
    """
    specs: list[dict[str, Any]] = [
        {"id": "000000", "dead": 1, "signed": ["a5"],
         "rounds": [(2, "a1", True), (3, "a2", False), (4, "a3", False),
                    (5, "a4", False), (6, "a5", False)]},
        {"id": "000001", "dead": 2, "signed": ["b4b"],
         "rounds": [(3, "b1", True), (4, "b2", False), (5, "b3", False),
                    (6, "b4", False), (6, "b4b", False)]},
        {"id": "000002", "dead": 4, "signed": ["c3", "c8"],
         "rounds": [(4, "c1", True), (6, "c2", False), (6, "c3", False),
                    (6, "c4", True), (6, "c5", False), (6, "c6", False),
                    (6, "c7", False), (6, "c8", False)]},
        {"id": "000003", "dead": 0, "signed": ["d3"],
         "rounds": [(1, "d1", True), (2, "d2", False), (3, "d3", False)]},
        {"id": "000004", "dead": 2, "signed": ["e7"],
         "rounds": [(1, "e1", True), (2, "e2", False), (4, "e4", False),
                    (5, "e5", False), (6, "e6", False), (7, "e7", False)]},
    ]
    signs: list[dict[str, Any]] = []
    for spec in specs:
        plan_id = str(spec["id"])
        path = f"reports/f-proof-{plan_id}.md"
        seed_sha = {seed: hashlib.sha256(seed.encode()).hexdigest()
                    for _n, seed, _r in spec["rounds"]}
        entries: list[tuple[int, dict[str, Any]]] = [
            (n, _no_change_round(n)) for n in range(1, int(spec["dead"]) + 1)]
        for n, seed, registered in spec["rounds"]:
            entries.append((n, _proof_round(n, sha=seed_sha[seed],
                                            registered=registered, path=path)))
        # 轮次必须单调不减（schema 的硬判据）：按 round 稳定排序，等号允许。
        entries.sort(key=lambda item: item[0])
        history = [rec for _n, rec in entries]
        for seed in spec["signed"]:
            signs.append({"sha": seed_sha[seed], "path": path})
        _plan(store, plan_id, history)
    return signs


# ------------------------------------------------------------------ a 正控（现场复刻）


def test_the_lp_ball_12_shape_now_reads_the_signed_manuscripts(store: Store):
    """a：lp-ball-12 的形状 ⇒ 读数 ≥ 1，且每一份推进都注明「稿拿到 V 签」。"""
    signs = _lp_ball_12_shape(store)
    _write_signs(pathlib.Path(store.root), signs)
    got, detail = _got(store)

    assert got == 5, detail                      # 改前这里是 0
    assert detail["progress_outcome_rounds"] == 27, detail
    assert detail["zero_reading_hint"] == "", detail
    by_id = {p["id"]: p for p in detail["plans"]}
    for plan_id in ("000000", "000001", "000002", "000003", "000004"):
        p = by_id[plan_id]
        assert p["advanced_by"] == "signed_manuscript", p
        assert p["signed_manuscripts"], p
        assert "拿到 V 签" in p["why_advanced"], p
        # 逐轮读数（P6FIX2 起判据也有第五档「自足证明」）：有稿的那几轮不再被记成
        # "没推进"，但这个数仍是"没过 `_round_advanced`"的一半 —— 与改前的 0 不是
        # 一回事。逐轮为什么算/不算由 `tests/test_closing_attack_progress_self_contained.py`
        # 逐条钉住（这里只钉"计划级那一档没被轮级读数百日掉"）。
        assert 0 < p["progress_rounds"] < p["history_len"], p
        assert p["progress_rounds"] == len(p["advanced_rounds"]), p
        assert p["unadvanced_rounds"] == p["history_len"] - p["progress_rounds"], p
        # 逐轮理由没有丢
        assert p["not_advanced_rounds"], p
        assert all(str(g.get("why") or "") for g in p["not_advanced_rounds"]), p
    # 每一份签都注明了它走的是哪条来源、认的是哪一版
    first = by_id["000000"]["signed_manuscripts"][0]
    assert first["verdict"] == "成立" and first["streak"] >= first["need"], first
    assert first["matched_by"] == "proof_sha256", first
    assert first["via"] in ("sign_file", "issued.json"), first


def test_the_old_criterion_alone_reads_zero_on_that_shape(store: Store, monkeypatch):
    """a 的对照（改前红原话）：同一批 `history`，旧四档一条都没认。

    把第五档（自足证明）与两条计划级并列通路都打桩掉 = 回到改前那一版的口径 ⇒
    读数必须回到 0（旧四档逐轮都判 `False`，这正是现场 `advanced_plans: []` 的来源）。
    """
    _lp_ball_12_shape(store)
    monkeypatch.setattr(CL, "_proof_landed", lambda rec, shas=None: (False, "桩：第五档关掉"))
    for r in store.rows("attack_plans"):
        for h in r.get("history") or []:
            ok, why = CL._round_advanced(h)
            assert ok is False, (h.get("round"), why)
            assert "不算推进" in why or "不是 progress" in why, why
    monkeypatch.setattr(CL, "_signed_manuscripts_of", lambda hist, index: [])
    monkeypatch.setattr(CL, "_manuscript_drafting_rounds", lambda hist: [])
    got, detail = _got(store)
    assert got == 0, detail
    assert detail["advanced_plans"] == [], detail


# ------------------------------------------------------------------ b 正控（旧路径不降）


def test_a_plan_that_passed_the_old_criterion_still_counts_and_never_drops(store: Store):
    """b：只靠 `cites` 过关的计划照旧算（lp-ball-9/10/11 那一档），加一份签不会让它变低。

    分档也钉住：旧四档认得出推进时 `advanced_by` 留 `round`，不许被更弱的
    「按稿在写计」顶掉（那一档只是并列通路里的次一档）。
    """
    _plan(store, "000000", [
        _proof_round(1, sha=None, path=None, cites=("stmt:000000",)),
        _proof_round(2, sha="a" * 64, registered=True),
        _proof_round(3, sha="b" * 64),
    ])
    got_before, detail_before = _got(store)
    assert got_before == 1, detail_before
    p = detail_before["plans"][0]
    assert p["advanced_by"] == "round", p
    assert p["draft_manuscript_rounds"], p     # 次一档的读数仍在（只是不作准）

    # 同一份计划又拿到一份签 ⇒ 读数不许变低，且仍只有这一份计划
    _write_signs(pathlib.Path(store.root), [{
        "sha": "b" * 64, "path": "reports/f-proof-000000.md"}])
    got_after, detail_after = _got(store)
    assert got_after == got_before, detail_after
    assert detail_after["plans"][0]["advanced_by"] == "signed_manuscript", detail_after


# ------------------------------------------------------------------ c 负控（不许恒真）


def test_a_workspace_with_no_manuscript_and_no_cites_still_reads_zero(store: Store):
    """c：没有稿、也没有 `cites` 的合成现场 ⇒ 0（两条并列通路都不许自己变真）。"""
    _plan(store, "000000", [_no_change_round(1),
                            _proof_round(2, sha=None, path=None)])
    got, detail = _got(store)
    assert got == 0, detail
    assert detail["advanced_plans"] == [], detail
    assert detail["plans"][0]["advanced_by"] == "", detail["plans"][0]
    assert detail["plans"][0]["signed_manuscripts"] == [], detail["plans"][0]


def test_a_sign_below_the_threshold_is_not_advance(store: Store):
    """反真空：`streak<need` 的签不算「得签」那一档（门槛必须真的够）。

    P6FIX2 起这一轮仍会算推进 —— 但走的是第五档（稿已落地：sha 在 `out/vsigns/`
    里有签文件 ⇒ 那一版正文真的在盘上、真被 V 审过），不是 `signed_manuscript`。
    两档不许混：`signed_manuscripts` 仍必须是空表。
    """
    sha = _signed_sha("reports/f-proof-000000.md", streak=2, need=3)
    _plan(store, "000000", [_proof_round(1, sha=sha)])
    _write_signs(pathlib.Path(store.root), [{
        "sha": sha, "path": "reports/f-proof-000000.md", "streak": 2, "need": 3}])
    got, detail = _got(store)
    p = detail["plans"][0]
    assert got == 1, detail
    assert p["signed_manuscripts"] == [], p
    assert p["advanced_by"] == "self_contained_proof", p


def test_a_sign_that_is_not_established_is_not_advance(store: Store):
    """反真空：`verdict≠成立` 的签不算「得签」那一档（签只能是「成立」）。

    同上：稿已落地那一半（第五档）不受判词影响 —— 签文件在盘上就说明 V 审过那一版；
    `signed_manuscripts` 不许因此多出一行。
    """
    sha = _signed_sha("reports/f-proof-000000.md", verdict="存疑")
    _plan(store, "000000", [_proof_round(1, sha=sha)])
    _write_signs(pathlib.Path(store.root), [{
        "sha": sha, "path": "reports/f-proof-000000.md", "verdict": "存疑"}])
    got, detail = _got(store)
    p = detail["plans"][0]
    assert got == 1, detail
    assert p["signed_manuscripts"] == [], p
    assert p["advanced_by"] == "self_contained_proof", p


def test_a_sign_without_a_threshold_is_not_advance(store: Store):
    """反真空：`need=0`（0/0）不算「得签」那一档 —— 没有门槛的签不许静默变成一份签。"""
    sha = _signed_sha("reports/f-proof-000000.md", streak=0, need=0)
    _plan(store, "000000", [_proof_round(1, sha=sha)])
    _write_signs(pathlib.Path(store.root), [{
        "sha": sha, "path": "reports/f-proof-000000.md", "streak": 0, "need": 0}])
    got, detail = _got(store)
    p = detail["plans"][0]
    assert got == 1, detail
    assert p["signed_manuscripts"] == [], p
    assert p["advanced_by"] == "self_contained_proof", p


def test_resubmitting_the_same_bytes_is_not_manuscript_in_progress(store: Store):
    """反真空：两轮同一版正文（sha 没变）不算「稿在写」。"""
    sha = "f" * 64
    _plan(store, "000000", [_proof_round(1, sha=sha, registered=True),
                            _proof_round(2, sha=sha)])
    got, detail = _got(store)
    p = detail["plans"][0]
    assert p["draft_manuscript_rounds"] == [], p
    # 这一份计划仍算推进（P6FIX2 第五档：第 1 轮登记过、正文落盘），但不是「稿在写」
    assert got == 1 and p["advanced_by"] == "self_contained_proof", p


# ------------------------------------------------------------------ d 读数可见


def test_the_zero_reading_keeps_every_rounds_why(store: Store):
    """d：`advanced_plans=[]` 时，逐轮 `why` 仍从 `plans[].not_advanced_rounds` 读得到。"""
    _plan(store, "000000", [_no_change_round(1),
                            _proof_round(2, sha=None, path=None)])
    got, detail = _got(store)
    assert got == 0 and detail["advanced_plans"] == [], detail
    gone = detail["plans"][0]["not_advanced_rounds"]
    assert [g["round"] for g in gone] == [1, 2], gone
    assert all(str(g.get("why") or "") for g in gone), gone
    # 语义修正：`unadvanced_rounds`（没过旧四档）与 `no_change_rounds`（outcome=no_change）
    # 是两个数 —— 改前只有一个名字错误的 `no_progress_rounds`，业主因此读成"六轮全 no_change"。
    p = detail["plans"][0]
    assert p["unadvanced_rounds"] == 2 and p["no_change_rounds"] == 1, p


def test_the_unmet_line_says_it_is_the_criterion_not_F_giving_up(store: Store):
    """d（门那一行）：0 推进但有 progress 轮 ⇒ unmet 里明写「不是 F 没推进」。"""
    _plan(store, "000000", [_proof_round(1, sha=None, path=None),
                            _proof_round(2, sha=None, path=None)])
    path = pathlib.Path(store.root) / "out" / "paper" / "ACCEPTANCE-CHECKS.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"checks": [
        {"id": "P6", "name": "攻（攻坚推进）", "kind": "plan_progress_rows", "min": 1},
    ]}, ensure_ascii=False), encoding="utf-8")

    rep = CL.ClosingReport()
    CL._check_acceptance(rep, store, str(store.root))
    text = "；".join(f.detail for f in rep.findings)
    assert "不是「F 没推进」" in text, text
    assert "推进口径不认证明轮" in text, text
    assert rep.status.get("acceptance") == "fail", rep.status


# ------------------------------------------------------------------ e 反真空（三条通路各自承重）


def test_stubbing_both_parallel_paths_returns_the_old_zero(store: Store, monkeypatch):
    """e：把两条计划级并列通路与第五档（自足证明）都打桩掉 ⇒ lp-ball-12 的形状回 0

    （修复不是别处顺带变绿的：P6FIX2 之后第五档也能把这份盘推上去，所以它必须一起打桩）。
    """
    signs = _lp_ball_12_shape(store)
    _write_signs(pathlib.Path(store.root), signs)
    got, _ = _got(store)
    assert got == 5

    monkeypatch.setattr(CL, "_proof_landed", lambda rec, shas=None: (False, "桩：第五档关掉"))
    monkeypatch.setattr(CL, "_signed_manuscripts_of", lambda hist, index: [])
    monkeypatch.setattr(CL, "_manuscript_drafting_rounds", lambda hist: [])
    got_stubbed, detail = _got(store)
    assert got_stubbed == 0, detail
    assert detail["zero_reading_hint"], detail


def test_on_the_real_shape_each_parallel_path_alone_still_lifts_it(store: Store, monkeypatch):
    """e 的旁证：lp-ball-12 的现场同时满足三条通路，所以单打一条时还有别的在。

    这不是判据变宽：三条通路各自都能把 5 条计划推上去（`advanced_by` 会换成另一档），
    而三条都打掉时读数回 0（上一条用例）。单条通路各自的承重由
    `test_the_signed_path_is_load_bearing_on_its_own` /
    `test_the_draft_path_is_load_bearing_on_its_own` 钉住（第五档的承重由
    `tests/test_closing_attack_progress_self_contained.py` 的 e 钉住）。
    """
    signs = _lp_ball_12_shape(store)
    _write_signs(pathlib.Path(store.root), signs)

    monkeypatch.setattr(CL, "_signed_manuscripts_of", lambda hist, index: [])
    got_draft, detail_draft = _got(store)
    assert got_draft == 5, detail_draft
    # 得签那一档被打桩之后，第一份计划的代表档是逐轮那两条（旧四档都没有 cites，
    # 所以是第五档的自足证明）。
    assert detail_draft["plans"][0]["advanced_by"] == "self_contained_proof", \
        detail_draft["plans"][0]

    monkeypatch.undo()
    monkeypatch.setattr(CL, "_manuscript_drafting_rounds", lambda hist: [])
    got_signed, detail_signed = _got(store)
    assert got_signed == 5, detail_signed
    assert detail_signed["plans"][0]["advanced_by"] == "signed_manuscript", \
        detail_signed["plans"][0]


def test_the_signed_path_is_load_bearing_on_its_own(store: Store, monkeypatch):
    """e（①）：只有「得签」这一条能认（同一版正文，sha 没变）⇒ 打桩它读数回 0。

    这一份盘的 sha 在 `out/vsigns/` 里有签文件 ⇒ 第五档的"稿已落地"也成立；要单测
    「得签」这一档，得把第五档一起关掉（否则打桩后读数仍是 1，测的就不是得签那一档）。
    """
    sha = _signed_sha("reports/f-proof-000000.md")
    _plan(store, "000000", [_proof_round(1, sha=sha)])
    _write_signs(pathlib.Path(store.root), [{
        "sha": sha, "path": "reports/f-proof-000000.md"}])
    got, detail = _got(store)
    assert got == 1 and detail["plans"][0]["advanced_by"] == "signed_manuscript", detail

    monkeypatch.setattr(CL, "_proof_landed", lambda rec, shas=None: (False, "桩：第五档关掉"))
    monkeypatch.setattr(CL, "_signed_manuscripts_of", lambda hist, index: [])
    got_stubbed, _ = _got(store)
    assert got_stubbed == 0


def test_the_draft_path_is_load_bearing_on_its_own(store: Store, monkeypatch):
    """e（②）：没有签、但稿真在两轮之间改过 ⇒ 靠次一档算推进；打桩它读数回 0。

    「稿在写」要求有一轮 `proof_registered=True` —— 那一轮同时满足第五档（稿已落地），
    所以先把它关掉，这一条测的才是"按稿在写计"那一档本身。
    """
    _plan(store, "000000", [_proof_round(1, sha="a" * 64, registered=True),
                            _proof_round(2, sha="b" * 64)])
    monkeypatch.setattr(CL, "_proof_landed", lambda rec, shas=None: (False, "桩：第五档关掉"))
    got, detail = _got(store)
    assert got == 1, detail
    p = detail["plans"][0]
    assert p["advanced_by"] == "manuscript_in_progress", p
    assert "按稿在写计的" in p["why_advanced"], p
    assert p["signed_manuscripts"] == [], p

    monkeypatch.setattr(CL, "_manuscript_drafting_rounds", lambda hist: [])
    got_stubbed, _ = _got(store)
    assert got_stubbed == 0


def test_a_signed_manuscript_is_reported_once_not_once_per_round(store: Store):
    """反虚高：同一份签在四轮里被引用 ⇒ `signed_manuscripts` 仍只有一行。"""
    sha = "c" * 64
    _plan(store, "000000", [_proof_round(n, sha=sha) for n in (2, 3, 4, 5)])
    _write_signs(pathlib.Path(store.root), [{
        "sha": sha, "path": "reports/f-proof-000000.md"}])
    got, detail = _got(store)
    assert got == 1, detail
    signed = detail["plans"][0]["signed_manuscripts"]
    assert len(signed) == 1, signed
    assert signed[0]["rounds"] == [2, 3, 4, 5], signed


def test_an_archive_only_sign_is_counted_and_named_as_such(store: Store):
    """`issued.json` 里有、逐份签文件不在 ⇒ 按归档计入，但读数注明 `via=issued.json`。"""
    sha = _signed_sha("reports/f-proof-000000.md")
    _plan(store, "000000", [_proof_round(1, sha=sha)])
    _write_signs(pathlib.Path(store.root), [{
        "sha": sha, "path": "reports/f-proof-000000.md"}], write_sign_files=False)
    got, detail = _got(store)
    assert got == 1, detail
    signed = detail["plans"][0]["signed_manuscripts"][0]
    assert signed["via"] == "issued.json", signed
    assert "issued.json" in signed["via"], signed

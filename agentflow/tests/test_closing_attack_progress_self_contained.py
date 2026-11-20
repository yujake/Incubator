# -*- coding: utf-8 -*-
"""判据：`_round_advanced` 的第五档 —— 自足证明（P6FIX2，2026-11-20 lp-ball-12）。

## 业主裁定（逐字，2026-11-20）

    「自足证明是几乎唯一的生产方式」

⇒ 判据必须承认它：「`## 依赖` 空表 + 稿已落地」的 proof 轮，就是「往前走了一步」。

## 改前红（现场原话）

P6FIX 把"稿拿到 V 签"补成了计划级的并列通路（lp-ball-12 的 P6 0 → 5），但轮级
判据一个字没动 ⇒ 同一份盘上，36 轮里 27 轮 `outcome=progress` 的 `action=proof`
仍全部躺在 `plans[].not_advanced_rounds` 里，逐轮 `why` 写的是"既没有 cites、也没有
新子目标/新实验"。读数因此误导人：计划那一格绿了，逐轮读数却说"这 27 轮一步没走"。

## 第五档（三条同时成立）

1. `action == "proof"`；
2. 该轮产物的 `## 依赖` 是空表（`## 依赖` 由 `steps[].cites` 现渲染 ⇒ 全部步的
   `cites` 都为空；`attackround._clean_step` 保证"有 cites"与"`assumption: true`"必居
   其一，所以自足轮就是"每步都声明成前提"的那种轮）；
3. 稿已落地：`proof_registered=True` 且 `proof_sha256` 非空；或该 sha 命中
   `out/vsigns/` 的颁发表（真机上"签了但没登记"的那几轮走这一支）。

档名独立：`advanced_by="self_contained_proof"`。不与 `round`（旧四档，含 `cites`）混档，
也不与 `signed_manuscript` 混档 —— 它说的是"这一轮交了一份不欠别人的证明"，
不是"这一轮引到了在册命题"，也不是"这一份稿拿到了签"。

## 判据的形状

- a 正控：lp-ball-12 的 27 轮 proof（全部零 `cites`）里凡有稿的（12 轮：6 轮登记 +
  6 轮签了但没登记）逐轮 `advanced_by="self_contained_proof"`；其余 15 轮仍记 0 且
  `why` 说得出"为什么"；
- b 负控：合成现场（`action=proof` + 空依赖 + 没有稿、没有 sha）⇒ 仍 0；
- c 正控（旧四档不动）：`cites` 引到在册命题的轮 ⇒ `advanced_by="round"`，
  `why` 仍是原来那句"产物引到 N 个在册 id"；
- d 不重复计涨：同一份盘上 P6 的 `got` 与 P6FIX 的结果一致（5）—— 第五档不另加 1；
  把第五档打桩掉，`got` 不变（计划级已由 `signed_manuscript` 覆盖）；
- e 反真空：把 `_proof_landed` 打桩成恒真 ⇒ b 必红（第五档不是恒真的一档）。
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
    with store.tx("attack_plans", actor="test", note="P6FIX2 probe") as tx:
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
                 cites: tuple[str, ...] = (), outcome: str = "progress",
                 steps: int = 2, assumption: bool | None = None) -> dict[str, Any]:
    """一轮 `action=proof`：默认零 cites + 每步 `assumption=True`（= 自足、`## 依赖` 空表）。

    `cites` 给值时只挂在第 1 步（旧四档那一档：引到在册命题）。
    `assumption` 显式给值时覆盖默认（负控用它造"零 cites 却没声明成前提"的形态）。
    """
    marked = (not cites) if assumption is None else bool(assumption)
    rows = [{"n": i + 1, "text": f"前提步 {i + 1}",
             "cites": list(cites) if i == 0 else [], "assumption": marked}
            for i in range(steps)]
    rec: dict[str, Any] = {
        "round": n, "sid": "s1", "action": "proof", "outcome": outcome,
        "detail": f"论证：{n + 10} 步；证明重写：{path}",
        "evidence": [], "at": TS, "product": "proof", "strategy": "套用已知定理",
        "product_detail": {"product": "proof", "strategy": "套用已知定理",
                           "why_strategy": "反设存在反例", "steps": rows},
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


def _sha_of(seed: str) -> str:
    """夹具里的正文 sha：从 seed 定出来（可复算，不读盘）。"""
    return hashlib.sha256(seed.encode()).hexdigest()


def _write_signs(root: pathlib.Path, shas: list[str], *,
                 path: str = "reports/f-proof-000000.md") -> None:
    """写 V 的颁发表：`out/vsigns/<sha>.json`（逐份）+ `out/vsigns/issued.json`（归档）。"""
    d = root / "out" / "vsigns"
    d.mkdir(parents=True, exist_ok=True)
    for sha in shas:
        doc = {"artifact_sha": sha, "artifact_path": path, "verdict": "成立",
               "streak": 3, "need": 3, "at": TS, "statement_id": ""}
        (d / f"{sha}.json").write_text(json.dumps(doc, ensure_ascii=False),
                                       encoding="utf-8")
    index = {"schema": "vsigns-issued/1",
             "signs": [{"artifact_sha": sha, "artifact_path": path,
                        "verdict": "成立", "streak": 3, "need": 3,
                        "at": TS, "statement_id": "",
                        "archived_by": "test", "archived_at": TS} for sha in shas],
             "updated_at": TS}
    (d / "issued.json").write_text(json.dumps(index, ensure_ascii=False),
                                   encoding="utf-8")


@pytest.fixture()
def store(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _got(store: Store) -> tuple[int, dict[str, Any]]:
    return CL._leg_reading(store, "plan_progress_rows", pathlib.Path(store.root))


def _rounds(p: dict[str, Any]) -> list[dict[str, Any]]:
    """一份计划的逐轮读数（第五档之后 `plans[]` 里也直接给）。"""
    return [dict(x) for x in (p.get("advanced_rounds") or [])]


def _lp_ball_12_shape(store: Store) -> list[str]:
    """lp-ball-12 的现场形状（36 轮 / 27 轮 proof / 5 份计划），逐轮复刻真机。

    真机读数（`data/attack_plans.json`，2026-11-20）：5 条计划 / 36 轮
    （27 轮 `action=proof` + 9 轮 `no_change`）/ 27 轮全部零 `cites`、每步
    `assumption=True`；其中 12 轮"有稿"：6 轮 `proof_registered=True`（登记那一刻
    落的那一版）+ 6 轮 `proof_sha256` 命中 `out/vsigns/`（签了、但 `proof_registered`
    是 False —— 这是真机上"签了没登记"的那几轮）；另有 2 轮 sha 为空。

    返回那 6 个"签了但没登记"的 sha（调用方写颁发表用）。
    """
    #: (plan_id, no_change 轮数, [(轮号, seed, registered), …], [签了但没登记的 seed, …])
    specs: list[tuple[str, int, list[tuple[int, str, bool]], list[str]]] = [
        ("000000", 1,
         [(2, "a2", True), (3, "a3", False), (4, "a4", False),
          (5, "a5", False), (6, "a6", False)], ["a6"]),
        ("000001", 2,
         [(3, "b3", True), (4, "b4", False), (5, "b5", False),
          (6, "b6", False), (6, "", False)], ["b6"]),
        ("000002", 4,
         [(4, "c4", True), (6, "c6a", False), (6, "c6b", False), (6, "c6c", False),
          (6, "c6d", True), (6, "c6e", False), (6, "c6f", False), (6, "c6g", False)],
         ["c6e", "c6g"]),
        ("000003", 0,
         [(1, "d1", True), (2, "d2", False), (3, "d3", False)], ["d3"]),
        ("000004", 2,
         [(1, "e1", True), (2, "e2", False), (4, "e4", False), (5, "e5", False),
          (6, "e6", False), (7, "", False)], ["e6"]),
    ]
    signed: list[str] = []
    for plan_id, dead, rounds, signed_seeds in specs:
        path = f"reports/f-proof-{plan_id}.md"
        entries: list[tuple[int, dict[str, Any]]] = [
            (n, _no_change_round(n)) for n in range(1, dead + 1)]
        for n, seed, registered in rounds:
            entries.append((n, _proof_round(
                n, sha=(_sha_of(seed) if seed else ""),
                registered=registered, path=path)))
        entries.sort(key=lambda item: item[0])          # 轮次单调不减（schema 硬判据）
        _plan(store, plan_id, [rec for _n, rec in entries])
        signed += [_sha_of(seed) for seed in signed_seeds]
    return signed


# ------------------------------------------------------------------ a 正控（现场复刻）


def test_the_27_self_contained_proof_rounds_read_as_advanced(store: Store):
    """a：27 轮 proof 里凡有稿的（12 轮）⇒ 逐轮 `advanced_by="self_contained_proof"`。"""
    _write_signs(pathlib.Path(store.root), _lp_ball_12_shape(store))
    got, detail = _got(store)

    # 计划级：与 P6FIX 一致（5 条计划都被「稿拿到 V 签」那条通路认下）
    assert got == 5, detail
    assert detail["progress_outcome_rounds"] == 27, detail
    by_id = {p["id"]: p for p in detail["plans"]}
    advanced_by_plan = {pid: len(_rounds(p)) for pid, p in by_id.items()}
    # 真机上"有稿"的 12 轮：2 / 2 / 4 / 2 / 2
    assert advanced_by_plan == {"000000": 2, "000001": 2, "000002": 4,
                                "000003": 2, "000004": 2}, advanced_by_plan
    total = 0
    for pid, p in by_id.items():
        assert p["advanced_by"] == "signed_manuscript", p      # 计划级仍是得签那一档
        for row in _rounds(p):
            assert row["advanced_by"] == "self_contained_proof", (pid, row)
            assert row["action"] == "proof", (pid, row)
            assert "自足" in str(row.get("why") or ""), (pid, row)
            total += 1
    assert total == 12, total
    # 逐轮总数 = 27 轮 proof + 9 轮 no_change
    assert sum(p["history_len"] for p in by_id.values()) == 36
    assert sum(p["progress_rounds"] for p in by_id.values()) == 12
    assert sum(p["unadvanced_rounds"] for p in by_id.values()) == 24
    # 15 轮"没有落地的稿"仍记 0，且为什么仍读得到
    for p in by_id.values():
        for row in (p["not_advanced_rounds"] or []):
            assert str(row.get("why") or ""), row


def test_a_proof_round_landed_only_by_a_sign_counts_too(store: Store):
    """a 的一支：签了但没登记（`proof_registered=False`）的轮也算 —— 真机的 6 轮形态。"""
    sha = _sha_of("signed-only")
    _plan(store, "000000", [_proof_round(1, sha=sha, registered=False)])
    _write_signs(pathlib.Path(store.root), [sha])
    got, detail = _got(store)
    assert got == 1, detail
    row = _rounds(detail["plans"][0])[0]
    assert row["advanced_by"] == "self_contained_proof", row
    assert "out/vsigns/" in str(row.get("why") or ""), row


def test_a_round_with_cites_is_still_the_old_tier_not_the_new_one(store: Store):
    """c 正控（旧四档照旧）：`cites` 引到在册命题 ⇒ `advanced_by="round"`，不混进第五档。"""
    _plan(store, "000000", [_proof_round(1, sha="a" * 64, registered=True,
                                         cites=("stmt:000000",))])
    got, detail = _got(store)
    assert got == 1, detail
    p = detail["plans"][0]
    assert p["advanced_by"] == "round", p
    row = _rounds(p)[0]
    assert row["advanced_by"] == "round", row
    assert "产物引到 1 个在册 id" in str(row.get("why") or ""), row
    # 同一轮单独判：why 与改前逐字相同（第五档没动到 cites 那一档的语义）
    ok, why = CL._round_advanced(store.rows("attack_plans")[0]["history"][0])
    assert ok is True and why == "产物引到 1 个在册 id", why


# ------------------------------------------------------------------ b/c 负控


def test_a_proof_round_without_a_manuscript_still_reads_zero(store: Store):
    """b 负控：`action=proof` + 空依赖 + 没有稿、没有 sha ⇒ 仍 0（不许恒真）。"""
    _plan(store, "000000", [_proof_round(1, sha=None, path=None),
                            _no_change_round(2)])
    got, detail = _got(store)
    assert got == 0, detail
    p = detail["plans"][0]
    assert p["advanced_by"] == "", p
    assert p["advanced_rounds"] == [], p
    assert p["self_contained_proof_rounds"] == 0, p
    gone = p["not_advanced_rounds"]
    assert [g["round"] for g in gone] == [1, 2], gone
    assert "稿" in str(gone[0].get("why") or ""), gone[0]


def test_a_registered_flag_without_a_sha_is_not_landed(store: Store):
    """b 负控（门槛的一半）：`proof_registered=True` 而 `proof_sha256` 空 ⇒ 不算落地。"""
    _plan(store, "000000", [_proof_round(1, sha="", registered=True)])
    got, detail = _got(store)
    assert got == 0, detail
    assert detail["plans"][0]["advanced_by"] == "", detail["plans"][0]


def test_empty_cites_without_an_assumption_declaration_is_not_self_contained(store: Store):
    """b 负控（门槛的另一半）：零 `cites` 却没声明成前提 ⇒ 第五档不许成立。"""
    _plan(store, "000000", [_proof_round(1, sha="b" * 64, registered=True,
                                         assumption=False)])
    got, detail = _got(store)
    assert got == 0, detail
    p = detail["plans"][0]
    assert p["advanced_by"] == "", p
    assert p["self_contained_proof_rounds"] == 0, p


def test_a_non_proof_round_never_takes_the_new_tier(store: Store):
    """b 负控：`action` 不是 `proof` 的轮即使"零依赖 + 稿落地"也不进第五档。"""
    rec = {"round": 1, "sid": "s1", "action": "reduction", "outcome": "progress",
           "detail": "归约", "evidence": [], "at": TS, "product": "reduction",
           "manuscript_path": "reports/f-proof-000000.md",
           "proof_sha256": "c" * 64, "proof_registered": True,
           "product_detail": {"product": "reduction",
                              "steps": [{"n": 1, "text": "前提步",
                                         "cites": [], "assumption": True}]}}
    ok, why = CL._round_advanced(rec)
    assert ok is False and "自足" not in why, why
    assert "action=reduction" in why, why


# ------------------------------------------------------------------ d 不重复计涨


def test_the_plan_level_got_does_not_grow_again(store: Store):
    """d：P6 的 `got` 与 P6FIX 的结果一致 —— 第五档不把计划级读数再抬一次。"""
    _write_signs(pathlib.Path(store.root), _lp_ball_12_shape(store))
    got, detail = _got(store)
    assert got == 5, detail                      # ← P6FIX 落盘那一刻的读数

    # 把第五档打桩掉 = 只有 P6FIX 那两条并列通路 ⇒ got 不变（它没在承重）
    real = CL._proof_landed
    try:
        CL._proof_landed = lambda rec, shas=None: (False, "桩：第五档关掉")
        got_stubbed, detail_stubbed = _got(store)
    finally:
        CL._proof_landed = real
    assert got_stubbed == 5, detail_stubbed
    assert {p["advanced_by"] for p in detail_stubbed["plans"]} == {"signed_manuscript"}
    # 而逐轮读数确实回落（第五档是承重的，只是计划级已有别的通路）
    assert sum(p["progress_rounds"] for p in detail_stubbed["plans"]) == 0
    assert sum(p["self_contained_proof_rounds"] for p in detail["plans"]) == 12


# ------------------------------------------------------------------ e 反真空


def test_stubbing_the_landed_check_turns_the_negative_control_red(store: Store):
    """e：把「稿已落地」打桩成恒真 ⇒ b 的合成现场从 0 变成 1（负控因此必红）。"""
    _plan(store, "000000", [_proof_round(1, sha=None, path=None)])
    got, _detail = _got(store)
    assert got == 0

    real = CL._proof_landed
    try:
        CL._proof_landed = lambda rec, shas=None: (True, "桩：稿已落地恒真")
        got_stubbed, detail = _got(store)
    finally:
        CL._proof_landed = real
    assert got_stubbed == 1, detail
    assert detail["plans"][0]["advanced_by"] == "self_contained_proof", detail["plans"][0]
    # 打桩撤掉之后立刻回 0（这一格不是一次性的）
    got_back, _ = _got(store)
    assert got_back == 0


def test_the_deps_check_is_load_bearing_on_its_own(store: Store):
    """e 的一支：把「`## 依赖` 为空」打桩成恒非空 ⇒ 12 轮落地稿全掉回 0。

    这条钉住"三条门槛各自承重"：只把"稿已落地"那条关掉，读数会掉（上一条）；
    只把"依赖为空"那条关掉，读数同样要掉 —— 否则自足那一档就只由"有稿"一条撑着。
    """
    _write_signs(pathlib.Path(store.root), _lp_ball_12_shape(store))
    got, detail = _got(store)
    assert sum(p["self_contained_proof_rounds"] for p in detail["plans"]) == 12, detail

    real = CL._round_dependency_empty
    try:
        CL._round_dependency_empty = lambda product: (False, "桩：依赖恒非空")
        got_stubbed, detail_stubbed = _got(store)
    finally:
        CL._round_dependency_empty = real
    assert got_stubbed == 5, detail_stubbed          # 计划级仍由「得签」认下
    assert sum(p["progress_rounds"] for p in detail_stubbed["plans"]) == 0, detail_stubbed
    assert sum(p["self_contained_proof_rounds"]
               for p in detail_stubbed["plans"]) == 0, detail_stubbed
    assert len(detail_stubbed["plans"][0]["not_advanced_rounds"]) == \
        detail_stubbed["plans"][0]["history_len"], detail_stubbed["plans"][0]

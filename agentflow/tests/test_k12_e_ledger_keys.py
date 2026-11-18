# -*- coding: utf-8 -*-
"""K12 判据：E 侧台账的键是「实例 + 实验身份」，不是「整张 experiments 表 + code_path」。

## 缺口（`AUDIT-E` 已钉）

撤销、复用、progress、会审认行都以「整张 experiments 表 + code_path」为键，认不到身份就
兜底挑一行。双实例实测（探针 p8 ②）：E-1 落 `exp 000000` 之后，E-2 把同一份
`code/probe.py` 改一行再跑 ⇒ 000000 当场 `status=voided`、`voided_by='agent-E-2'`；
E-2 自己那条的 notes 里还写着「[progress] 同 claim 历史 1 条（最近一条 000000…）」——
它读的正是 E-1 的行。会审那一侧（`exhaustionreport.review`）在钉不到实验时按 ③ 正文 /
程序路径在整张表里挑一条（`find_signed_exhaustion` 更是「先到先得」）。

## 这一组守什么

| # | 造什么 | 期望 | 改前读数 |
|---|---|---|---|
| c | 两个 E 实例，同一 `code_path`，各跑一条 | 互不撤销（两条都 `active`、`voided_by` 空）；同一实例改脚本重跑仍撤自己那条（正控） | E-1 那条被 E-2 撤掉（`voided_by='agent-E-2'`） |
| c′ | 同一实例的 progress note | 只说自己的历史（`同 claim 历史 1 条` 只出现在它自己那一趟的 notes 里） | 跨实例读（探针 p8 ②） |
| d | 会审钉不到实验身份（两条行共用 `code_path`、没给号） | `checked=False` + `missing` 点名「实验行」，不许挑一条 | 按程序路径挑第一条 |
| d′ | 会审给了号 | 认到那一条（`missing` 里不再点实验行） | —— |
| h | 反真空：把「只看本写者名下的行」打桩掉（`scope_rows` 恒返回全表） | c 必须红（E-1 那条又被撤） | —— |

边界：全部 `tmp_path` 工作区、零真实模型调用、不碰 `projects/`。
"""
from __future__ import annotations

import pathlib
import sys

import pytest

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from conftest import e_form_gate_ok  # noqa: E402
from agentflow import exhaustionreport as ER  # noqa: E402
from agentflow.agent_e import AgentE  # noqa: E402
from agentflow.store import Store  # noqa: E402

import agentflow.agent_e.run_experiment as RX  # noqa: E402

SCRIPT_REL = "code/probe.py"
CLAIM = "网格 n<=3 上 Spec K(m)=[-m,m]"
CLAIM_KEY = "SpecK(m)=[-m,m]"

PROBE_V1 = """
import json
print("REPRO_RESULT: " + json.dumps({
    "result": "supports",
    "evidence_kind": "cross_check",
    "observations": {"points": 3},
    "counterexample": None,
    "negation_kind": "not_proved",
    "bound": {"n": 3},
}))
"""
PROBE_V2 = PROBE_V1 + "\n# 另一个实例改过这一份脚本\n"
PROBE_V3 = PROBE_V2 + "\n# 同一个实例又改了一次\n"


def _store(root: pathlib.Path) -> Store:
    st = Store(root)
    st.init()
    return st


def _write(store: Store, body: str, rel: str = SCRIPT_REL) -> str:
    path = pathlib.Path(store.root) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body.encode("utf-8"))
    return rel


def _e(store: Store, instance: str) -> AgentE:
    """一个指名到实例的 E（`actor=agent-E-<名>` 是装配期的同一条格式）。"""
    return e_form_gate_ok(AgentE(store, config={}, workspace_root=store.root,
                                 actor=f"agent-E-{instance}"))


def _run(store: Store, instance: str) -> dict:
    return _e(store, instance).run_experiment(CLAIM, CLAIM_KEY, SCRIPT_REL, method="numeric")


def _rows(store: Store) -> dict[str, dict]:
    return {str(r.get("experiment_id")): dict(r) for r in store.rows("experiments")}


# ============================================================ c：互不撤销


def test_c_two_e_instances_do_not_void_each_other(tmp_path):
    """c：同一 `code_path`、两个实例各跑一条 ⇒ 互不撤销（改前 red：E-1 那条被撤）。"""
    st = _store(tmp_path / "ws")
    _write(st, PROBE_V1)
    first = _run(st, "E1")
    _write(st, PROBE_V2)
    second = _run(st, "E2")

    rows = _rows(st)
    e1 = rows[str(first["experiment_id"])]
    e2 = rows[str(second["experiment_id"])]
    assert e1["status"] == "active", ("E-1 那条被 E-2 撤销了（改前的形态）", e1)
    assert e1["voided_by"] == "", e1
    assert e2["status"] == "active", e2
    assert e1["owner_instance"] == "E1", e1
    assert e2["owner_instance"] == "E2", e2

    # 正控：同一个实例改脚本重跑 ⇒ 它自己那条照旧被撤（撤销没被这次修法关掉）。
    _write(st, PROBE_V3)
    third = _run(st, "E1")
    rows = _rows(st)
    assert rows[str(first["experiment_id"])]["status"] == "voided", rows
    assert rows[str(first["experiment_id"])]["voided_by"] == "agent-E-E1", rows
    assert rows[str(third["experiment_id"])]["status"] == "active", rows
    assert rows[str(second["experiment_id"])]["status"] == "active", rows


# ============================================================ c′：progress 只读自己


def test_c2_progress_note_reads_only_my_own_rows(tmp_path):
    """c′：E-2 的 notes 不许把 E-1 那条当自己的历史（改前 red：「同 claim 历史 1 条」）。"""
    st = _store(tmp_path / "ws")
    _write(st, PROBE_V1)
    first = _run(st, "E1")
    # 同一个 claim_key 再跑一次，但换实例 ⇒ E-2 名下一行历史都没有。
    second = _run(st, "E2")
    note_e2 = str(second["notes"])
    assert f"同 claim 历史 1 条（最近一条 {first['experiment_id']}" not in note_e2, (
        "E-2 的 progress note 读到了 E-1 的行（改前的形态）", note_e2)

    # 正控：同一实例再跑一次，它自己的历史读得到。
    third = _run(st, "E1")
    assert "同 claim 历史 1 条" in str(third["notes"]), third["notes"]


# ============================================================ d：认不到身份 ⇒ 缺材料


def _exhaustion_column() -> str:
    from agentflow import numericproof as NP

    return NP.compose_proof_column(enumeration="枚举全部 2^36 个染色，无一遗漏")


def _two_rows_same_script() -> list[dict]:
    """两条实验行共用同一份程序（真机常态：lp-ball-8 有 4 组这样）。"""
    sig = {"signed_by": "V", "proof_authors": ["E"], "proof_reason": "exhaustion",
           "enumeration": "枚举全部 2^36 个染色，无一遗漏"}
    base = {
        "experiment_id": "000000", "claim": "C", "claim_key": "k", "method": "exhaustive_search",
        "evidence_kind": "proof", "result": "supports", "code_path": "code/enum.py",
        "code_hash": "a" * 64, "search_bound": {"n": 3},
        "observations": {"enumeration": "枚举全部 2^36 个染色，无一遗漏",
                         "design": "逐层枚举", "e_signature": dict(sig)},
    }
    second = {**base, "experiment_id": "000001", "claim": "C2", "claim_key": "k2",
              "observations": {"enumeration": "另一段论证", "design": "逐层枚举",
                               "e_signature": dict(sig, enumeration="另一段论证")}}
    return [dict(base), dict(second)]


def _legacy_column(enumeration: str = "另一段论证") -> str:
    """旧形态的证明栏（`程序：` 那一段还在）：改前「按程序路径认行」那一支走的就是它。"""
    return ("程序：code/enum.py\n"
            "① 程序设计思路：逐层枚举\n"
            "② 搜索空间：n<=3\n"
            f"③ 穷举论证：{enumeration}")


def test_d_exhaustion_review_refuses_to_pick_a_row_by_script(tmp_path):
    """d：钉不到实验身份 ⇒ `checked=False` + `missing` 点名，不许按程序路径挑一条。

    改前读数（`2d6f6655` 上同一份输入）：`review` 按 `程序：code/enum.py` 在整张表里
    认到了一条（`reviewed["missing"]` 里没有「与这条证明栏对应的实验行」这一块），
    而这份证明栏的 ③ 正文属于另一条行 —— 「认到了」是对的那条还是错的那条，盘上分不出。
    """
    reviewed = ER.review(workspace_root=tmp_path,
                         statement={"proof_text": _legacy_column()},
                         experiments=_two_rows_same_script())
    assert reviewed["checked"] is False, ("认不到实验身份却给出了结论", reviewed)
    assert reviewed["verdict"] == "", reviewed
    assert any("实验行" in str(m) for m in reviewed["missing"]), reviewed["missing"]
    # 程序路径这条读数仍然给（第 1 项检查要读它），但它不再用来认行。
    assert reviewed.get("program") == "code/enum.py", reviewed

    # d′：给了号 ⇒ 认到那一条（不再写「缺实验行」这一块）。
    pinned = ER.review(workspace_root=tmp_path,
                       statement={"proof_text": _legacy_column()},
                       experiments=_two_rows_same_script(),
                       experiment_id="000001")
    assert not any("与这条证明栏对应的实验行" == str(m) for m in pinned["missing"]), pinned
    assert pinned.get("program") == "code/enum.py", ("没认到点名那一条的实验行", pinned)


def test_d2_find_signed_exhaustion_does_not_pick_the_first_of_many():
    """d 的另一半：同一程序路径 / 同一段 ③ 正文命中多条 ⇒ 认不到（不是「先到先得」）。"""
    from agentflow import numericproof as NP

    rows = _two_rows_same_script()
    assert NP.find_signed_exhaustion(rows, "code/enum.py") is None, (
        "同一程序路径命中多条，仍然挑了一条（改前的形态）")
    # 正控：只有一条时照旧认得到。
    assert NP.find_signed_exhaustion(rows[:1], "code/enum.py") is not None

    # 两行共用逐字相同的 ③ 正文时，按正文认也认不到（改前按优先级返回第一条）。
    same_text = [dict(rows[0]), dict(rows[1], observations={
        **rows[1]["observations"], "enumeration": rows[0]["observations"]["enumeration"],
        "e_signature": {**rows[1]["observations"]["e_signature"],
                        "enumeration": rows[0]["observations"]["enumeration"]}})]
    assert NP.find_signed_exhaustion_for_column(
        same_text, "枚举全部 2^36 个染色，无一遗漏") is None, (
        "同一段 ③ 正文命中两条，仍然挑了一条（改前的形态）")
    # 正控：正文唯一时照旧认得到（认的还是对的那一条）。
    got = NP.find_signed_exhaustion_for_column(rows, "另一段论证")
    assert got is not None and got["experiment_id"] == "000001", got


# ============================================================ h：反真空


def test_h_stubbing_the_writer_scope_turns_c_red(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """h：把「只看本写者名下的行」与「只撤我这一支笔的行」两条判据一起打桩掉 ⇒ c 必红。

    K12 的键由两处合成：读面收窄（`rowscope.scope_rows`）与撤销前的写者判据
    （`rowscope.same_writer`）。只打桩其中一处，另一处仍然拦着 —— 那正是「两处都指着
    同一件事」的读数；把两处都打桩，E-1 那条就又被 E-2 撤掉，于是 c 的绿归这两处。
    """
    monkeypatch.setattr(RX._RS, "scope_rows",
                        lambda table, rows, **k: [dict(r) for r in rows])
    monkeypatch.setattr(RX._RS, "same_writer", lambda row, **k: True)
    st = _store(tmp_path / "ws")
    _write(st, PROBE_V1)
    first = _run(st, "E1")
    _write(st, PROBE_V2)
    _run(st, "E2")
    rows = _rows(st)
    assert rows[str(first["experiment_id"])]["status"] == "voided", (
        "两条判据都打桩掉之后 E-1 那条仍是 active ⇒ c 的绿不是这两处给的", rows)
    assert rows[str(first["experiment_id"])]["voided_by"] == "agent-E-E2", rows

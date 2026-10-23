# -*- coding: utf-8 -*-
"""判据：V 会审穷举型证据（三态），以及 E -> V 那条边（业主 2026-10-23 晚）。

业主原话（逐字）：「E 写的报告要能落下来，且 V 也要会审这种东西，加 E 派 V 的边」，
随后更正：「签字仍由 V 签（不是 E）。E 只是 ②③（程序设计 / 穷举论证）的原作者。」

## 这一组守六条

1. 穷举型证据（证明栏第 ① 段是数值实验程序）走 V 的会审：七项检查逐项给读数，
   全部通过 ⇒ `成立`、签第 3 位、台账落一行；
2. 把 ③ 的穷尽说明改坏（说成抽样、代码里也有抽样构造）⇒ `有毛病` 并点名那一项
   （不是一句"看起来不太行"）；
3. 搜索空间与代码对不上（③ 报了一个代码里没有的数）⇒ `有毛病`，点名那一项；
4. 报告没落地（缺材料）⇒ `看不出来`，点名缺什么，且不许判 `成立`；
5. `E -> V` 的边是真的：`conductor.summon("V", ..., by="E")` 被受理；
   其它角色到 V 的边一条都没多（负控：by="G" 仍被拒 `forbidden_edge`）；
6. 边表逐角色清单与总数钉住（多开一条边 ⇒ 这一条红）。

全部用例在 `tmp_path` 里自建工作区，一个模型调用都不发（会审是机械判据）。
"""
from __future__ import annotations

import json
import pathlib
import sys

import pytest

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from conftest import add_literature  # noqa: E402
from agentflow import capabilities as C  # noqa: E402
from agentflow import exhaustionreport as ER  # noqa: E402
from agentflow import numericproof as NP  # noqa: E402
from agentflow import schema as S  # noqa: E402
from agentflow.agent_b import AgentB  # noqa: E402
from agentflow.agent_e import AgentE  # noqa: E402
from agentflow.agent_v import AgentV  # noqa: E402
from agentflow.store import Store  # noqa: E402

TS = "2026-10-23T00:00:00+08:00"
SCRIPT_REL = "code/enum_ramsey34.py"

#: 一个真的穷举脚本（数字在代码里出现、剪枝在报告里解释）。
EXHAUSTIVE_PROBE = """
import json
N = 9
SPACE = 2 ** 36
TOTAL = 68719476736
print("REPRO_RESULT: " + json.dumps({
    "result": "supports", "evidence_kind": "cross_check",
    "observations": {
        "exhaustive": True,
        "design": "把 R(3,4)=9 的上界归约成 K_9 的二染色穷举：按 4-子集布尔赋值编码逐点检查",
        "enumeration": ("枚举 K_9 全部 2^36 = 68719476736 个二染色；先按顶点置换取 canonical form "
                        "去掉对称性重数，再按 3-子集/4-子集的对称性剪枝；每个染色都落在枚举里，"
                        "无一遗漏；边界：n=9 是上界侧的全部，n<=8 由 witness 覆盖"),
        "search_space": {"graph": "K_9", "colourings": 68719476736},
    },
    "counterexample": None, "negation_kind": "not_proved",
    "bound": {"n": 9}, "strategy": "canonical form + symmetry breaking",
}))
"""

#: 一个"抽样"脚本：它自己报了 exhaustive=true（E 的判据拿它签了 proof），
#: 但代码里是随机抽样、③ 也写着抽样 —— V 必须判"有毛病"。
SAMPLING_PROBE = """
import json, random
N = 9
TOTAL = 100000
picks = [random.randrange(2 ** 36) for _ in range(TOTAL)]
print("REPRO_RESULT: " + json.dumps({
    "result": "supports", "evidence_kind": "cross_check",
    "observations": {
        "exhaustive": True,
        "design": "在 K_9 的二染色空间里抽查",
        "enumeration": "随机抽取 100000 个二染色逐点检查，覆盖率很高；边界 n=9",
        "search_space": {"graph": "K_9", "colourings": 100000},
    },
    "counterexample": None, "negation_kind": "not_proved",
    "bound": {"n": 9},
}))
"""

#: 一个"搜索空间报大了"的脚本：③ 说 2^40，而代码里只有 2^36（V 必须点名这个数）。
OVERCLAIM_SPACE_PROBE = """
import json
N = 9
SPACE = 2 ** 36
TOTAL = 68719476736
print("REPRO_RESULT: " + json.dumps({
    "result": "supports", "evidence_kind": "cross_check",
    "observations": {
        "exhaustive": True,
        "design": "把 R(3,4)=9 归约成二染色穷举",
        "enumeration": "枚举全部 2^40 = 1099511627776 个二染色，无一遗漏；边界 n=9",
        "search_space": {"graph": "K_9", "colourings": 1099511627776},
    },
    "counterexample": None, "negation_kind": "not_proved",
    "bound": {"n": 9},
}))
"""


def _store(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _write(store: Store, rel: str, body: str) -> str:
    path = pathlib.Path(store.root) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return rel


def _chain(tmp_path: pathlib.Path, body: str = EXHAUSTIVE_PROBE,
           rel: str = SCRIPT_REL) -> dict:
    """整条链真跑一次：E 跑穷举实验（并落 ②③）→ B 原样登记命题 → 交给 V 会审的原料。

    B 这一笔按 `kind="conjecture"` 登记（而不是直接 `evidence_kind="proof"`）：
    2026-10-23 晚的第三方签字闸（`numericproof.filing_problems`）要求 proof 那一档必须
    有 V 的会审签名，而 V 只审在册的命题 ⇒ 正路的顺序是"先按猜想落库（这一步不受阻）、
    交给 V 会审、签完之后再升成定理级"。这条链在 V 会审之前就停下，所以只能是猜想那一档。
    """
    store = _store(tmp_path)
    add_literature(store, S.format_id(0))
    _write(store, rel, body)
    out = AgentE(store, config={}, workspace_root=store.root).run_experiment(
        "R(3,4)=9（K_9 的二染色穷举）", "ramsey34=9", rel, method="numeric")
    row = store.rows("experiments")[-1]
    column = NP.proof_column(row)
    filed = AgentB(store, extractor=None, extract_text=None).register_statement(
        origin="own_result", kind="conjecture", label="R(3,4)=9",
        statement_full="对任意正整数 n，R(3,4)=9。", statement_text="R(3,4)=9",
        proof_text=column, evidence_kind="cross_check", doc_id=S.format_id(0),
        line_range={"start": 1}, quote_verified=False,
        quote_reason="own_result：我方推导")
    assert filed.get("ok") is True, filed
    statement = store.rows("statements")[-1]
    return {"store": store, "out": out, "row": row, "column": column,
            "statement": statement, "v": AgentV(store, workspace_root=store.root)}


# ------------------------------------------------------------------ ③ 三态


def test_4a_an_exhaustive_evidence_that_holds_is_signed_by_v(tmp_path: pathlib.Path) -> None:
    """③-1 成立：七项检查全过 ⇒ `成立`、签第 3 位、台账落一行；②③ 的作者仍是 E。"""
    env = _chain(tmp_path)
    got = env["v"].verify_proof(env["statement"]["stmt_id"], proof_text=env["column"])
    assert got["checked"] is True, got
    assert got["kind"] == "numeric_evidence", got
    assert got["verdict"] == ER.VERDICT_OK, (got["verdict"], got.get("findings"))
    assert got["signed_bit3"] is True, got
    checks = {str(c["name"]): c["ok"] for c in got["checks"]}
    for name in (ER.CHECK_PROGRAM, ER.CHECK_REPORT, ER.CHECK_SPACE, ER.CHECK_SYMMETRY,
                 ER.CHECK_BOUNDARY, ER.CHECK_EXHAUSTIVE, ER.CHECK_SLOT):
        assert checks.get(name) is True, (name, got["checks"])
    assert got["report_path"] == ER.report_relpath(env["out"]["experiment_id"])
    assert got["proof_authors"] == ["E"], got
    ledger = env["v"].list_verifications(env["statement"]["stmt_id"])["items"]
    assert [r["verdict"] for r in ledger] == [ER.VERDICT_OK], ledger


def test_4b_a_broken_exhaustive_note_is_faulty_and_named(tmp_path: pathlib.Path) -> None:
    """③-2 把穷尽说明改坏（说成抽样、代码里也有抽样）⇒ `有毛病`，点名那一项。"""
    env = _chain(tmp_path, SAMPLING_PROBE, "code/sample_ramsey34.py")
    got = env["v"].verify_proof(env["statement"]["stmt_id"], proof_text=env["column"])
    assert got["checked"] is True, got
    assert got["verdict"] == ER.VERDICT_BAD, (got["verdict"], got.get("findings"))
    assert got["defect_step"] == 6, got["defect_step"]
    kinds = [str(f.get("kind")) for f in got["findings"]]
    assert ER.CHECK_EXHAUSTIVE in kinds, kinds
    assert "抽样" in json.dumps(got["findings"], ensure_ascii=False)
    assert got["signed_bit3"] is False, "有毛病不许签第 3 位"


def test_4c_a_search_space_that_the_code_does_not_support_is_faulty(
        tmp_path: pathlib.Path) -> None:
    """③-3 搜索空间与代码对不上（③ 报 2^40，代码里只有 2^36）⇒ `有毛病`，点名那个数。"""
    env = _chain(tmp_path, OVERCLAIM_SPACE_PROBE, "code/overclaim_ramsey34.py")
    got = env["v"].verify_proof(env["statement"]["stmt_id"], proof_text=env["column"])
    assert got["verdict"] == ER.VERDICT_BAD, (got["verdict"], got.get("findings"))
    assert got["defect_step"] == 3, got["defect_step"]
    kinds = [str(f.get("kind")) for f in got["findings"]]
    assert ER.CHECK_SPACE in kinds, kinds
    assert "1099511627776" in json.dumps(got["findings"], ensure_ascii=False), got["findings"]


def test_4d_a_missing_report_is_unknown_and_never_holds(tmp_path: pathlib.Path) -> None:
    """③-4 报告没落地（缺材料）⇒ `看不出来`，点名缺什么；台账照样留一行（那是"判不了"）。"""
    env = _chain(tmp_path)
    report = pathlib.Path(env["store"].root) / env["out"]["report_path"]
    assert report.is_file()
    report.unlink()
    got = env["v"].verify_proof(env["statement"]["stmt_id"], proof_text=env["column"])
    assert got["checked"] is True, got
    assert got["verdict"] == ER.VERDICT_UNKNOWN, (got["verdict"], got.get("findings"))
    assert got["verdict"] != ER.VERDICT_OK, "报告没了却判成立 ⇒ 这一档形同虚设"
    assert got["signed_bit3"] is False
    reviewed = got["exhaustion_review"]
    text = json.dumps({"why": reviewed["why"], "findings": reviewed["findings"],
                       "missing": reviewed["missing"]}, ensure_ascii=False)
    assert "缺" in text and ("报告" in text or "落盘" in text), text
    ledger = env["v"].list_verifications(env["statement"]["stmt_id"])["items"]
    assert [r["verdict"] for r in ledger] == [ER.VERDICT_UNKNOWN], ledger


def test_4e_a_proof_column_without_any_experiment_is_unknown(tmp_path: pathlib.Path) -> None:
    """③-5 只有一份"写着程序的证明栏"、台账里没有对应的实验 ⇒ `看不出来`（缺 ②③）。"""
    store = _store(tmp_path)
    add_literature(store, S.format_id(0))
    _write(store, SCRIPT_REL, EXHAUSTIVE_PROBE)
    statement = {
        "stmt_id": S.format_id(0), "claim_key": "ramsey34=9",
        "statement_full": "对任意正整数 n，R(3,4)=9。",
        "proof_text": NP.compose_proof_column(
            script_path=SCRIPT_REL, design="把上界归约成二染色穷举",
            enumeration="枚举全部 2^36 个染色，无一遗漏"),
    }
    reviewed = ER.review(workspace_root=store.root, statement=statement, experiments=[])
    assert reviewed["verdict"] == ER.VERDICT_UNKNOWN, reviewed
    assert reviewed["missing"], reviewed
    assert any("实验" in str(m) for m in reviewed["missing"]), reviewed["missing"]
    # 缺材料时不许出现"成立"：这是这一档最容易糊过去的地方
    assert ER.verdict_of(reviewed)["verdict"] != ER.VERDICT_OK


# ------------------------------------------------------------------ ④ E -> V 的边


def test_4f_the_edge_from_e_to_v_is_real_and_the_others_are_unchanged(
        tmp_path: pathlib.Path) -> None:
    """④ 边：`E -> V` 在真表里；summon 被受理；其它角色到 V 的边一条都不多。"""
    # ---- 静态那一半：逐角色清单与总数（多开一条 ⇒ 这里红）
    assert C.ALLOWED_EDGES["E"] == frozenset({"B", "D", "V"}), C.ALLOWED_EDGES["E"]
    assert sorted(C.ALLOWED_EDGES["A"]) == ["B"]
    assert sorted(C.ALLOWED_EDGES["B"]) == ["C", "D", "H", "L", "V"]
    assert sorted(C.ALLOWED_EDGES["C"]) == []
    assert sorted(C.ALLOWED_EDGES["D"]) == ["A", "B", "C", "E", "F"]
    assert sorted(C.ALLOWED_EDGES["F"]) == ["A", "B", "C", "D", "E", "V"]
    assert sorted(C.ALLOWED_EDGES["G"]) == ["A", "D", "E", "F"]
    assert sorted(C.ALLOWED_EDGES["H"]) == ["A", "E", "G"]
    assert sorted(C.ALLOWED_EDGES["V"]) == ["F"]
    assert sorted(C.ALLOWED_EDGES["L"]) == ["C"]
    assert sorted(C.ALLOWED_EDGES["M"]) == ["A", "B", "C", "D", "E", "G", "H"]
    inbound_v = sorted(role for role, tos in C.ALLOWED_EDGES.items() if "V" in tos)
    assert inbound_v == ["B", "E", "F"], inbound_v
    assert sum(len(tos) for tos in C.ALLOWED_EDGES.values()) == 36

    # ---- 动态那一半：真起一个主控，E 派 V 会审穷举证据，并且拿得到判决
    from agentflow.host import wired_conductor
    from agentflow.tools.conductor_tools import reset_cache

    reset_cache()
    env = _chain(tmp_path)
    sid = env["statement"]["stmt_id"]
    cond = wired_conductor(env["store"], workspace_root=str(env["store"].root))
    got = cond.summon("V", "verify_proof",
                      {"statement_id": sid, "proof_text": env["column"]}, by="E")
    assert got.status == "done", (got.status, got.outcome, getattr(got, "detail", ""))
    assert str(got.outcome) != "refused", (got.outcome, getattr(got, "refusal_reason", ""))
    payload = dict(getattr(got, "payload", None) or {})
    assert payload.get("verdict") == ER.VERDICT_OK, payload
    assert payload.get("signed_bit3") is True, payload
    assert payload.get("kind") == "numeric_evidence", payload
    assert payload.get("verification_id"), payload
    # 负控：没这条边的角色派 V 仍然被拒（否则上面那条"受理"只是空转）
    bad = cond.summon("V", "list_verifications", {}, by="G")
    assert str(bad.outcome) == "refused", bad
    blob = json.dumps({k: str(v) for k, v in vars(bad).items()}, ensure_ascii=False)
    assert "forbidden_edge" in blob, blob

# -*- coding: utf-8 -*-
"""收录时按语义查一圈"是不是在册的同一条"，并把数值实验记成纯追加的流水。

## 业主口径（逐字）

> 「普通数值实验原则上不许自称thereom或lemma，只许叫conjecture」
> 「现在执行的收录时"是不是同一条命题只按规范化正文逐字相等判，这是错误的！应该按照语义判定」
> 「B秘书要学会在命题台账里按关键词搜索」
> 「应该没有same和different读数，只有秘书查了一圈没查到一样的就注册新的，查到就更新那条命题的状态」
> 「所以数值实验录入就是一个纯追加的过程」
> 「语义判定同一不只是对数值实验位更新奏效，还关系着单命题多证明路径收录等」

## 这一份钉的判据

| # | 判据 | 改前为什么红 |
|---|---|---|
| a | 同义不同措辞 ⇒ `found` 命中、不新增行、那一行 numeric 位与等级更新 | 改前只按 normalize 全等，措辞不同会新注册 |
| b | 条件强化 / 弱化 ⇒ `found` 为空、新登记一行（两行并存） | 同上 |
| c | 逐字相同 ⇒ `found` 命中且模型调用 0 次 | 改前也要走完整登记链 |
| d | 普通数值交 kind=theorem ⇒ 落盘 kind=conjecture，无拒收、无 downgrade 读数 | 改前静默压回并记 `kind_downgraded` |
| e | 关键词没提取成 / 判定没成 ⇒ 不新注册、受控拒、台账一行 | 改前没有这一问，照样新注册 |
| f | 候选 0 条 ⇒ 新登记，读数写明"查过、0 条" | 改前没有这一格读数 |
| g | 反真空：退回逐字全等 ⇒ a 新注册两行；把"没判成"折成"没查到" ⇒ e 新注册一行 | 判据自身要能红 |
| j | 关键词共享但措辞不同 ⇒ `found` 命中（贴 keywords / hits_named） | 改前没有关键词检索 |
| k | 反真空：摘掉关键词检索 ⇒ j 变红（新注册两行） | 判据自身要能红 |
| p | 同一命题用两个不同程序各跑一次 ⇒ 两条（script 不同）、等级不变 | 改前只存单份 |
| q | 同一个程序再递一次、读数不同 ⇒ 条数不变、该条读数换成后一次的 | 追加会变 2 条；忽略会留旧读数 |
| q2 | 同一个程序再递一次、读数相同 ⇒ 条数不变、读数相同（幂等） | 同上 |
| q3 | 两个不同程序、读数恰好相同 ⇒ 仍是两条 | 按读数去重会把两个程序压成一条 |
| r | 反真空：改成追加 ⇒ q 变 2 条（红）；改成忽略 ⇒ q 留旧读数（红） | 判据自身要能红 |
| l | 同一命题的第二条证明（措辞不同、来源不同）⇒ found 命中、走既有在册分支、`proofs` +1、号递增 | 改前措辞不同会新注册 |
| m | 同一份正文重复递交 ⇒ `proofs` 长度不变（既有幂等） | 既有实现自带，接入后不许被打破 |
| n | 等级不回退：先有 V 签证明（pre_theorem）再来普通数值 ⇒ 仍是 pre_theorem | 普通数值不许把等级读成定理 |
| o | 反真空：摘掉语义 found ⇒ l 变成新注册两行 | 判据自身要能红 |

为零模型调用：所有模型缝都是打桩的。不读写 `projects/`。
"""
from __future__ import annotations

import json
import pathlib
import sys
from typing import Mapping

import pytest

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from conftest import seed_proposition_form_ok, seed_statement_row, sign_before_registration  # noqa: E402
from agentflow import evidencebits as EB  # noqa: E402
from agentflow import schema as S  # noqa: E402
from agentflow import secretary as SEC  # noqa: E402
from agentflow import verifications as VR  # noqa: E402
from agentflow.agent_b import AgentB  # noqa: E402
from agentflow.agent_e import AgentE  # noqa: E402
from agentflow.store import Store  # noqa: E402

CLAIM = "设 n<=10，则 P(n) 对 n=1..10 都成立。"
PARAPHRASE = "对所有不超过 10 的正整数 n，P(n) 成立。"
STRONGER = "设 n<=5，则 P(n) 对 n=1..5 都成立。"

P1 = "1. 由定义直接得到。\n2. 由 1 与假设 n >= 3 得结论。"
P2 = "另一条路线：\n1. 先证引理。\n2. 由引理得结论。"
S1 = "设 G 是 3-正则群；则弦长函数不是常值。"
S2 = "对每个 3-正则群 G，弦长函数取不到同一个值。"


class Seam:
    """秘书判断面的打桩缝：形态 / 挑词 / 认定三问都按脚本回。"""

    class _Call:
        ok = True
        problem = ""
        detail = ""
        text = ""
        model = "fake"
        prompt_version = "t"
        prompt_sha256 = "0" * 64

    def __init__(self, *, keywords=("P(n)",), found="", judge_bad=False,
                 keyword_bad=False):
        self.calls: list[str] = []
        self.keywords = list(keywords)
        self.found = str(found or "")
        self.judge_bad = bool(judge_bad)
        self.keyword_bad = bool(keyword_bad)

    def ask_json(self, prompt, *, system: str = "", task_id: str = "",
                 note: str = ""):
        self.calls.append(str(note))
        if str(note).endswith("proposition_form"):
            return ({"well_formed": True, "conditions": "n<=10",
                     "conclusion": "P(n)", "problems": [], "decision": "ok"},
                    self._Call())
        if str(note).endswith("statement_keywords"):
            if self.keyword_bad:
                return None, self._Call()
            return ({"keywords": list(self.keywords),
                     "why": "这几个数学词能把同义的那条捞出来"}, self._Call())
        if str(note).endswith("statement_same"):
            if self.judge_bad:
                return None, self._Call()
            return ({"found": self.found, "why": "条件与结论同一"}, self._Call())
        if str(note).endswith("proposition_identity"):
            return ({"decision": "different", "same_as": "", "canonical_name": "",
                     "condition": "", "conclusion": "", "basis": [], "reason": "不同"},
                    self._Call())
        return ({}, self._Call())


# ------------------------------------------------------------------ 夹具

def _store(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _agent(store: Store, seam=None, *, enable: bool = True) -> AgentB:
    sec = SEC.Secretary("B", root=store.root, store=store, seam=seam,
                        enable_model=bool(enable and seam is not None))
    return AgentB(store, extractor=None, extract_text=None, secretary=sec)


def _register(store: Store, seam, manuscript: str, *, kind: str = "conjecture",
              statement_full: str = "") -> dict:
    return _agent(store, seam).register_statement(
        origin="own_result", kind=kind, label="scan",
        statement_full=statement_full, statement_text="", proof_text="",
        evidence_kind="cross_check", proof_manuscript=manuscript,
        quote_verified=False, quote_reason="own_result：E 的实验读数")


def _register_proof(store: Store, seam, statement: str, manuscript: str) -> dict:
    return _agent(store, seam).register_statement(
        origin="own_result", kind="conjecture", label="弦长函数",
        statement_full=statement, statement_text="", proof_text="",
        proof_manuscript=manuscript, evidence_kind="heuristic",
        line_range={"label": manuscript},
        quote_verified=False, quote_reason="own_result：F 的证明稿")


def _numeric(store: Store, claim: str, key: str, script: str,
             observations: dict) -> dict:
    body = ("import json\nprint('REPRO_RESULT: ' + json.dumps({"
            "'result': 'supports', 'evidence_kind': 'cross_check', "
            f"'observations': {json.dumps(observations)}, "
            "'counterexample': None, 'negation_kind': 'not_proved'}))\n")
    path = pathlib.Path(store.root) / script
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return AgentE(store, config={}, workspace_root=store.root).run_experiment(
        claim, key, script, method="numeric")


def _numeric_with_params(store: Store, claim: str, key: str, script: str,
                         observations: dict) -> dict:
    """脚本字节不变、只换同目录的 `params.json`（程序身份 = script + code_hash）。

    这样两次运行共享同一个 `code_hash`，而 `range` / `n_cases` 可以不同 ——
    正是"同一个程序换参数再跑"的形态。
    """
    params_rel = "code/params.json"
    params_abs = (pathlib.Path(store.root) / params_rel).resolve()
    params_abs.parent.mkdir(parents=True, exist_ok=True)
    params_abs.write_text(json.dumps(observations, ensure_ascii=False),
                          encoding="utf-8")
    # 参数文件的绝对路径写死在脚本里 ⇒ 两次运行的脚本字节完全相同（`code_hash` 相同），
    # 换的只是那个文件的内容。
    body = ("import json, pathlib\n"
            f"obs = json.loads(pathlib.Path({params_abs.as_posix()!r})"
            ".read_text(encoding='utf-8'))\n"
            "print('REPRO_RESULT: ' + json.dumps({"
            "'result': 'supports', 'evidence_kind': 'cross_check', "
            "'observations': obs, 'counterexample': None, "
            "'negation_kind': 'not_proved'}))\n")
    path = pathlib.Path(store.root) / script
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return AgentE(store, config={}, workspace_root=store.root).run_experiment(
        claim, key, script, method="numeric")


def _rows(store: Store) -> list[dict]:
    return [dict(r) for r in store.rows("statements")]


def _first_numeric(store: Store) -> tuple[dict, str]:
    out = _numeric(store, CLAIM, "k1", "code/scan1.py",
                   {"range": "n<=10", "points": 10})
    seed_proposition_form_ok(store.root, CLAIM, kind="conjecture", role="B")
    got = _register(store, Seam(found=""), out["numeric_manuscript"])
    assert got.get("ok") is True, got
    return out, str(_rows(store)[0]["stmt_id"])


# ================================================================== a 同义改写
def test_a_a_paraphrase_updates_the_registered_row_instead_of_a_second_one(tmp_path):
    """a：同义不同措辞 ⇒ found 命中、不新增行、numeric 位与等级更新。"""
    store = _store(tmp_path)
    _first, sid = _first_numeric(store)
    second = _numeric(store, PARAPHRASE, "k2", "code/scan2.py",
                      {"range": "n<=10", "points": 10, "n_cases": 10})
    seed_proposition_form_ok(store.root, PARAPHRASE, kind="conjecture", role="B")
    seam = Seam(keywords=["P(n)", "n<=10"], found=sid)
    got = _register(store, seam, second["numeric_manuscript"])
    assert got.get("ok") is True, got
    assert got.get("found") == sid, got
    rows = _rows(store)
    assert len(rows) == 1, rows
    assert rows[0]["bits"]["numeric"] == "verified", rows[0]["bits"]
    assert EB.bits_from_row(rows[0])["grade"] == "strong_conjecture"
    updated = dict(got.get("updated_statement") or {})
    assert updated.get("entries_total") == 2, updated
    assert updated.get("grade_before") == "strong_conjecture", updated
    assert "secretary:statement_keywords" in seam.calls, seam.calls
    assert "secretary:statement_same" in seam.calls, seam.calls


# ================================================================== b 条件强弱
def test_b_a_strengthened_condition_is_registered_as_a_second_proposition(tmp_path):
    """b：条件强化 / 弱化 ⇒ found 为空、新登记一行（两行并存）。"""
    store = _store(tmp_path)
    _first_numeric(store)
    second = _numeric(store, STRONGER, "k2", "code/scan2.py",
                      {"range": "n<=5", "points": 5})
    seed_proposition_form_ok(store.root, STRONGER, kind="conjecture", role="B")
    got = _register(store, Seam(keywords=["P(n)"], found=""),
                    second["numeric_manuscript"])
    assert got.get("ok") is True, got
    assert got.get("found") == "", got
    rows = _rows(store)
    assert len(rows) == 2, rows
    assert {str(r.get("statement_full") or "") for r in rows} == {CLAIM, STRONGER}


# ================================================================== c 逐字命中免模型
def test_c_a_verbatim_candidate_is_found_without_any_model_call(tmp_path):
    """c：逐字相同 ⇒ found 命中且模型调用 0 次。"""
    store = _store(tmp_path)
    out, sid = _first_numeric(store)
    no_seam = _agent(store, None, enable=False)
    got = no_seam.register_statement(
        origin="own_result", kind="conjecture", label="scan",
        statement_full="", statement_text="", proof_text="",
        evidence_kind="cross_check",
        proof_manuscript=out["numeric_manuscript"],
        quote_verified=False, quote_reason="own_result：E 的实验读数")
    assert got.get("ok") is True, got
    assert got.get("found") == sid, got
    searched = dict(got.get("searched") or {})
    assert searched.get("model_calls") == 0, searched
    assert len(_rows(store)) == 1


# ================================================================== d 不写 kind
def test_d_a_numeric_manuscript_lands_as_conjecture_even_if_kind_is_theorem(tmp_path):
    """d：普通数值交 kind=theorem ⇒ 落盘 conjecture，无拒收、无 downgrade 读数。"""
    store = _store(tmp_path)
    out = _numeric(store, CLAIM, "k1", "code/scan.py",
                   {"range": "n<=10", "points": 10})
    seed_proposition_form_ok(store.root, CLAIM, kind="theorem", role="B")
    got = _register(store, Seam(found=""), out["numeric_manuscript"],
                    kind="theorem")
    assert got.get("ok") is True, got
    assert _rows(store)[0]["kind"] == "conjecture", _rows(store)[0]
    assert "kind_downgraded" not in json.dumps(got, ensure_ascii=False)


# ================================================================== e fail-closed
def test_e_a_failed_judgement_refuses_and_leaves_a_ledger_row(tmp_path):
    """e：判定没成 ⇒ 不新注册、受控拒、台账一行。"""
    store = _store(tmp_path)
    _first_numeric(store)
    second = _numeric(store, PARAPHRASE, "k2", "code/scan2.py",
                      {"range": "n<=10", "points": 10})
    seed_proposition_form_ok(store.root, PARAPHRASE, kind="conjecture", role="B")
    got = _register(store, Seam(keywords=["P(n)"], judge_bad=True),
                    second["numeric_manuscript"])
    assert got.get("ok") is False, got
    assert got.get("kind") == "same_statement_unjudged", got
    assert len(_rows(store)) == 1, _rows(store)
    ledger = SEC.statement_same_rows(store.root)
    assert any((not row.get("checked")) and str(row.get("stage") or "") == "judge"
               for row in ledger), ledger


def test_e2_a_failed_keyword_extraction_also_refuses(tmp_path):
    """e 的第二档：关键词没提取成 ⇒ 同样不新注册、台账一行。"""
    store = _store(tmp_path)
    _first_numeric(store)
    second = _numeric(store, PARAPHRASE, "k2", "code/scan2.py",
                      {"range": "n<=10", "points": 10})
    seed_proposition_form_ok(store.root, PARAPHRASE, kind="conjecture", role="B")
    got = _register(store, Seam(keyword_bad=True), second["numeric_manuscript"])
    assert got.get("ok") is False, got
    assert got.get("kind") == "same_statement_unjudged", got
    assert len(_rows(store)) == 1
    ledger = SEC.statement_same_rows(store.root)
    assert any((not row.get("checked"))
               and str(row.get("stage") or "") == "keywords" for row in ledger), ledger


# ================================================================== f 候选 0 条
def test_f_no_keyword_hit_registers_with_a_zero_hit_reading(tmp_path):
    """f：候选 0 条 ⇒ 新登记，读数写明"查过、0 条"。"""
    store = _store(tmp_path)
    seed_statement_row(store, statement_full="设 m 是正整数；则 Q(m) 对 m=1..3 成立。",
                       kind="conjecture", label="Q(m) 的界")
    out = _numeric(store, CLAIM, "k1", "code/scan.py",
                   {"range": "n<=10", "points": 10})
    seed_proposition_form_ok(store.root, CLAIM, kind="conjecture", role="B")
    got = _register(store, Seam(keywords=["P(n)"]), out["numeric_manuscript"])
    assert got.get("ok") is True, got
    assert got.get("found") == "", got
    searched = dict(got.get("searched") or {})
    assert searched.get("checked") is True, searched
    assert searched.get("hits_total") == 0, searched
    assert searched.get("judged") is False, searched
    assert len(_rows(store)) == 2, _rows(store)


# ================================================================== j / k 关键词检索
def _seed_paraphrase(store: Store) -> str:
    seeded = seed_statement_row(
        store, statement_full=PARAPHRASE, kind="conjecture",
        label="P(n) 的界")
    return str(seeded["stmt_id"])


def test_j_keyword_search_lands_a_differently_worded_proposition(tmp_path):
    """j：关键词共享但措辞不同 ⇒ found 命中（贴 keywords / hits_named）。"""
    store = _store(tmp_path)
    sid = _seed_paraphrase(store)
    out = _numeric(store, CLAIM, "k1", "code/scan.py",
                   {"range": "n<=10", "points": 10})
    seed_proposition_form_ok(store.root, CLAIM, kind="conjecture", role="B")
    got = _register(store, Seam(keywords=["P(n)", "n<=10"], found=sid),
                    out["numeric_manuscript"])
    assert got.get("ok") is True, got
    assert got.get("found") == sid, got
    searched = dict(got.get("searched") or {})
    assert searched.get("keywords") == ["P(n)", "n<=10"], searched
    assert int(searched.get("hits_total") or 0) >= 1, searched
    named = list(searched.get("hits_named") or [])
    assert named and named[0].get("stmt_id") == sid, searched
    assert len(_rows(store)) == 1, _rows(store)
    assert _rows(store)[0]["bits"]["numeric"] == "verified"


def test_k_without_keyword_retrieval_j_would_register_a_second_row(tmp_path, monkeypatch):
    """k：反真空 —— 摘掉关键词检索 ⇒ j 变成新注册两行（红）。"""
    store = _store(tmp_path)
    sid = _seed_paraphrase(store)
    out = _numeric(store, CLAIM, "k1", "code/scan.py",
                   {"range": "n<=10", "points": 10})
    seed_proposition_form_ok(store.root, CLAIM, kind="conjecture", role="B")
    monkeypatch.setattr(
        AgentB, "_numeric_same_candidates",
        lambda self, **kw: {"checked": True, "hits": [], "reason": "",
                            "checked_rows": 1})
    got = _register(store, Seam(keywords=["P(n)", "n<=10"], found=sid),
                    out["numeric_manuscript"])
    assert got.get("ok") is True, got
    assert got.get("found") == "", got
    assert len(_rows(store)) == 2, (
        "反真空失效：摘掉关键词检索之后 j 仍然只落一行 ⇒ 检索这一步不是承重的", _rows(store))


# ================================================================== p / q / r 纯追加
def test_p_two_different_programs_append_two_entries(tmp_path):
    """p：同一命题用两个不同的程序各跑一次 ⇒ 两条（script 不同）、等级不变。"""
    store = _store(tmp_path)
    _first_numeric(store)
    sid = str(_rows(store)[0]["stmt_id"])
    second = _numeric(store, PARAPHRASE, "k2", "code/scan2.py",
                      {"range": "n<=10", "points": 10, "n_cases": 10})
    seed_proposition_form_ok(store.root, PARAPHRASE, kind="conjecture", role="B")
    got = _register(store, Seam(keywords=["P(n)", "n<=10"], found=sid),
                    second["numeric_manuscript"])
    assert got.get("ok") is True, got
    updated = dict(got.get("updated_statement") or {})
    entries = list(updated.get("entries") or [])
    assert len(entries) == 2, entries
    expected_keys = set(S.NUMERIC_EVIDENCE_KEYS) | {"code_hash", "exp"}
    assert all(set(entry) == expected_keys for entry in entries), entries
    assert entries[0]["script"] == "code/scan1.py", entries
    assert entries[1]["script"] == "code/scan2.py", entries
    assert updated.get("appended") == 1, updated
    for banned in ("proof_no", "created_at", "seq", "order", "index"):
        assert banned not in json.dumps(entries, ensure_ascii=False), (banned, entries)
    assert updated.get("grade_before") == "strong_conjecture", updated
    assert updated.get("grade") == "strong_conjecture", updated


def test_q_the_same_program_replaces_the_previous_readings(tmp_path):
    """q：同一程序再递一次、读数不同 ⇒ 条数不变，该条读数换成后一次的。"""
    store = _store(tmp_path)
    first = _numeric_with_params(store, CLAIM, "k1", "code/paramscan.py",
                                 {"range": "n<=10", "points": 100})
    seed_proposition_form_ok(store.root, CLAIM, kind="conjecture", role="B")
    made = _register(store, Seam(found=""), first["numeric_manuscript"])
    assert made.get("ok") is True, made
    sid = str(_rows(store)[0]["stmt_id"])
    before = dict((_rows(store)[0]["bits"]["evidence"]["numeric"]["entries"][0]))
    rerun = _numeric_with_params(store, CLAIM, "k2", "code/paramscan.py",
                                 {"range": "n<=20", "points": 200})
    got = _register(store, None, rerun["numeric_manuscript"])
    assert got.get("ok") is True, got
    assert got.get("found") == sid, got
    updated = dict(got.get("updated_statement") or {})
    entries = list(updated.get("entries") or [])
    assert updated.get("same_program") is True, updated
    assert updated.get("replaced") is True, updated
    assert updated.get("appended") == 0, updated
    assert updated.get("entries_total") == 1, updated
    assert len(entries) == 1, entries
    # 替换前 / 后：旧读数不保留。
    assert before["n_cases"] == 100 and before["range"] == "n<=10", before
    assert entries[0]["n_cases"] == 200 and entries[0]["range"] == "n<=20", entries


def test_q2_the_same_program_with_the_same_readings_is_idempotent(tmp_path):
    """q2：同一个程序再递一次、读数相同 ⇒ 条数不变、读数相同（幂等）。"""
    store = _store(tmp_path)
    first = _numeric_with_params(store, CLAIM, "k1", "code/paramscan.py",
                                 {"range": "n<=10", "points": 10})
    seed_proposition_form_ok(store.root, CLAIM, kind="conjecture", role="B")
    made = _register(store, Seam(found=""), first["numeric_manuscript"])
    assert made.get("ok") is True, made
    rerun = _numeric_with_params(store, CLAIM, "k2", "code/paramscan.py",
                                 {"range": "n<=10", "points": 10})
    got = _register(store, None, rerun["numeric_manuscript"])
    assert got.get("ok") is True, got
    updated = dict(got.get("updated_statement") or {})
    entries = list(updated.get("entries") or [])
    assert updated.get("same_program") is True, updated
    assert updated.get("replaced") is True, updated
    assert updated.get("entries_total") == 1, updated
    assert len(entries) == 1, entries
    assert entries[0]["n_cases"] == 10 and entries[0]["range"] == "n<=10", entries


def test_q3_two_different_programs_with_the_same_counts_are_still_two_entries(tmp_path):
    """q3：两个不同程序、读数（range/n_cases/反例数）恰好相同 ⇒ 仍是两条。"""
    store = _store(tmp_path)
    _first_numeric(store)
    sid = str(_rows(store)[0]["stmt_id"])
    other = _numeric(store, PARAPHRASE, "k2", "code/other.py",
                     {"range": "n<=10", "points": 10})
    seed_proposition_form_ok(store.root, PARAPHRASE, kind="conjecture", role="B")
    got = _register(store, Seam(keywords=["P(n)"], found=sid),
                    other["numeric_manuscript"])
    assert got.get("ok") is True, got
    updated = dict(got.get("updated_statement") or {})
    entries = list(updated.get("entries") or [])
    assert len(entries) == 2, entries
    assert entries[0]["script"] != entries[1]["script"], entries
    assert entries[0]["range"] == entries[1]["range"], entries
    assert entries[0]["n_cases"] == entries[1]["n_cases"], entries
    assert entries[0]["n_counterexamples"] == entries[1]["n_counterexamples"], entries
    assert updated.get("appended") == 1, updated


def _q_scenario(store: Store) -> tuple[dict, dict]:
    """q 的场景：同一个程序、先 100 例后 200 例。返回（替换前那一条, 后一次的返回）。"""
    first = _numeric_with_params(store, CLAIM, "k1", "code/paramscan.py",
                                 {"range": "n<=10", "points": 100})
    seed_proposition_form_ok(store.root, CLAIM, kind="conjecture", role="B")
    made = _register(store, Seam(found=""), first["numeric_manuscript"])
    assert made.get("ok") is True, made
    before = dict(_rows(store)[0]["bits"]["evidence"]["numeric"]["entries"][0])
    rerun = _numeric_with_params(store, CLAIM, "k2", "code/paramscan.py",
                                 {"range": "n<=20", "points": 200})
    got = _register(store, None, rerun["numeric_manuscript"])
    assert got.get("ok") is True, got
    return before, got


def test_r_appending_instead_of_replacing_turns_q_red(tmp_path, monkeypatch):
    """r 的第一档：把"替换"改成"追加" ⇒ q 的条数变 2（红）。"""
    original = AgentB._merge_numeric_evidence

    def _append_only(self, old, green):
        merged = original(self, old, green)
        entry = self._numeric_entry(green)
        old_entries = [x for x in ((old or {}).get("entries") or [])
                       if isinstance(x, Mapping)]
        if any(self._same_numeric_program(x, entry) for x in old_entries):
            merged["entries"] = list(merged.get("entries") or []) + [entry]
        return merged

    monkeypatch.setattr(AgentB, "_merge_numeric_evidence", _append_only)
    store = _store(tmp_path)
    _before, got = _q_scenario(store)
    updated = dict(got.get("updated_statement") or {})
    assert updated.get("entries_total") == 2, (
        "反真空失效：改成追加之后条数没有变 2 ⇒ q 的绿不是替换给的", updated)


def test_r2_ignoring_instead_of_replacing_turns_q_red(tmp_path, monkeypatch):
    """r 的第二档：把"替换"改成"忽略" ⇒ q 的读数还是旧的（红）。"""
    original = AgentB._merge_numeric_evidence

    def _ignore(self, old, green):
        merged = original(self, old, green)
        entry = self._numeric_entry(green)
        old_entries = [dict(x) for x in ((old or {}).get("entries") or [])
                       if isinstance(x, Mapping)]
        old_hit = next((x for x in old_entries
                        if self._same_numeric_program(x, entry)), None)
        if old_hit is not None:
            merged["entries"] = [
                (dict(old_hit) if self._same_numeric_program(x, entry) else x)
                for x in (merged.get("entries") or [])]
        return merged

    monkeypatch.setattr(AgentB, "_merge_numeric_evidence", _ignore)
    store = _store(tmp_path)
    _before, got = _q_scenario(store)
    updated = dict(got.get("updated_statement") or {})
    entries = list(updated.get("entries") or [])
    assert updated.get("entries_total") == 1, updated
    assert entries and entries[0]["n_cases"] == 100, (
        "反真空失效：改成忽略之后读数仍然变成了后一次的 ⇒ q 的绿不是替换给的",
        entries)


# ================================================================== l / m / n / o 多证明
def _proof_manuscript(store: Store, *, sid: str, proof_no: int,
                      proof_text: str, proposition: str) -> str:
    rel = f"reports/f-proof-{sid}.md"
    path = pathlib.Path(store.root) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"# F 的证明手稿（夹具）\n\n- 命题号：stmt:{sid}\n- 证明号：{proof_no}\n"
        "- 依赖面洗稿：已洗=true；执行者=secretary:F\n\n"
        f"## 命题\n\n{proposition}\n\n## 证明\n\n{proof_text}\n\n"
        "## 依赖\n\n| 引用（F 的原话） | 命题号（stmt:NNNNNN） | 用在哪一步 | 路径号（第几条证明） |\n"
        "|---|---|---|---|\n\n（这一份证明没有引用任何在册命题 —— 空表就是声明。）\n",
        encoding="utf-8")
    return rel


def _sign_proof_pending(store: Store, *, proof_no: int, proof_text: str) -> None:
    """命题还没在册时 V 审过的那一签（pending，按正文 sha 认领），号改成 `proof_no`。"""
    sign_before_registration(store.root, proof_text=proof_text)
    for pend in (pathlib.Path(store.root) / "verifications" / "pending").glob("*.jsonl"):
        text = pend.read_text(encoding="utf-8").replace(
            '"proof_no": 1', f'"proof_no": {int(proof_no)}')
        pend.write_text(text, encoding="utf-8", newline="\n")


def _sign_proof(store: Store, *, sid: str, proof_no: int, proof_text: str) -> None:
    for _ in range(int(VR.SIGN_STREAK_NEED)):
        VR.record_verification(
            store.root, statement_id=sid, proof_text=proof_text,
            verdict={"verdict": "成立", "findings": []},
            verifier="agent-V", store=store, proof_no=proof_no,
            secretary_judge={"checked": True, "axis": "clean",
                             "decision": "没问题", "reason": "夹具：clean"})


def _first_proof(store: Store) -> str:
    sign_before_registration(store.root, proof_text=P1)
    got = _register_proof(store, Seam(keywords=["弦长函数"], found=""),
                          S1, "reports/f-proof-999999.md")
    assert got.get("ok") is True, got
    rows = _rows(store)
    assert len(rows) == 1, rows
    return str(rows[0]["stmt_id"])


def test_l_a_second_proof_of_the_same_proposition_appends_a_proof_path(tmp_path):
    """l：同一命题第二条证明 ⇒ found 命中、不新增行、proofs +1、号递增。"""
    store = _store(tmp_path)
    sid = _first_proof(store)
    _sign_proof(store, sid=sid, proof_no=2, proof_text=P2)
    rel = _proof_manuscript(store, sid=sid, proof_no=2, proof_text=P2,
                            proposition=S1)
    got = _register_proof(store, Seam(keywords=["弦长函数"], found=sid), S2, rel)
    assert got.get("ok") is True, got
    assert got.get("found") == sid, got
    rows = _rows(store)
    assert len(rows) == 1, rows
    listed = VR.proof_list(rows[0])
    assert [int(no) for no, _text in listed] == [1, 2], listed
    assert VR.proof_sha(VR.proof_text_of(rows[0], 1)) == VR.proof_sha(P1)
    assert VR.proof_sha(VR.proof_text_of(rows[0], 2)) == VR.proof_sha(P2)
    assert got.get("merged") is True, got
    assert int(got.get("proof_no") or 0) == 2, got


def test_m_resubmitting_the_same_proof_body_does_not_grow_the_list(tmp_path):
    """m：同一份正文重复递交 ⇒ proofs 长度不变（既有幂等）。"""
    store = _store(tmp_path)
    sid = _first_proof(store)
    _sign_proof(store, sid=sid, proof_no=2, proof_text=P2)
    rel = _proof_manuscript(store, sid=sid, proof_no=2, proof_text=P2,
                            proposition=S1)
    first = _register_proof(store, Seam(keywords=["弦长函数"], found=sid), S2, rel)
    assert first.get("ok") is True, first
    before = [int(no) for no, _text in VR.proof_list(_rows(store)[0])]
    again = _register_proof(store, Seam(keywords=["弦长函数"], found=sid), S2, rel)
    assert again.get("ok") is True, again
    after = [int(no) for no, _text in VR.proof_list(_rows(store)[0])]
    assert after == before == [1, 2], (before, after)


def test_n_a_plain_numeric_experiment_does_not_raise_a_pre_theorem(tmp_path):
    """n：先有 V 签证明（pre_theorem）再来普通数值 ⇒ 等级仍是 pre_theorem。"""
    store = _store(tmp_path)
    sid = _first_proof(store)
    grade_before = EB.bits_from_row(_rows(store)[0])["grade"]
    assert grade_before == "pre_theorem", grade_before
    out = _numeric(store, S2, "k1", "code/scan.py",
                   {"range": "n<=10", "points": 10})
    seed_proposition_form_ok(store.root, S2, kind="conjecture", role="B")
    got = _register(store, Seam(keywords=["弦长函数"], found=sid),
                    out["numeric_manuscript"])
    assert got.get("ok") is True, got
    row = _rows(store)[0]
    assert row["bits"]["numeric"] == "verified", row["bits"]
    assert EB.bits_from_row(row)["grade"] == "pre_theorem", row["bits"]
    updated = dict(got.get("updated_statement") or {})
    assert updated.get("grade_before") == "pre_theorem", updated
    assert updated.get("grade") == "pre_theorem", updated


def test_g_a_if_semantic_were_removed_a_would_register_two_rows(tmp_path, monkeypatch):
    """g 的第一半：反真空 —— 退回"逐字全等"⇒ a 的同义改写变成新注册两行。"""
    def _exact_only(self, *, full, label="", kind="conjecture", task_id=""):
        row = self._existing_statement_for(full)
        return {"checked": True, "found": str((row or {}).get("stmt_id") or ""),
                "why": "夹具：只认逐字全等", "keywords": [], "keyword_checked": True,
                "hits_total": 0, "hits_named": [], "judged": False,
                "model_calls": 0, "problems": [], "refused": "",
                "_row": dict(row or {})}

    monkeypatch.setattr(AgentB, "_resolve_same_statement", _exact_only)
    store = _store(tmp_path)
    _first_numeric(store)
    second = _numeric(store, PARAPHRASE, "k2", "code/scan2.py",
                      {"range": "n<=10", "points": 10})
    seed_proposition_form_ok(store.root, PARAPHRASE, kind="conjecture", role="B")
    got = _register(store, Seam(found=""), second["numeric_manuscript"])
    assert got.get("ok") is True, got
    assert got.get("found") == "", got
    assert len(_rows(store)) == 2, (
        "反真空失效：退回逐字全等之后 a 仍然只落一行 ⇒ 语义查一圈不是承重的",
        _rows(store))


def test_g_e_if_unjudged_were_treated_as_not_found_e_would_register(tmp_path, monkeypatch):
    """g 的第二半：反真空 —— 把"没判成"折成"没查到" ⇒ e 会新注册一行。"""
    monkeypatch.setattr(
        SEC.Secretary, "judge_statement_same",
        lambda self, **kw: {"checked": True, "found": "",
                            "why": "夹具：把没判成当成没查到"})
    store = _store(tmp_path)
    _first_numeric(store)
    second = _numeric(store, PARAPHRASE, "k2", "code/scan2.py",
                      {"range": "n<=10", "points": 10})
    seed_proposition_form_ok(store.root, PARAPHRASE, kind="conjecture", role="B")
    got = _register(store, Seam(keywords=["P(n)"], judge_bad=True),
                    second["numeric_manuscript"])
    assert got.get("ok") is True, got
    assert got.get("found") == "", got
    assert len(_rows(store)) == 2, (
        "反真空失效：把没判成折成没查到之后 e 仍然没有新注册 ⇒ "
        "fail-closed 不是承重的", _rows(store))


def test_o_without_semantic_found_l_would_register_a_second_proposition(tmp_path, monkeypatch):
    """o：反真空 —— 摘掉语义 found ⇒ l 变成新注册两行（红）。"""
    store = _store(tmp_path)
    sid = _first_proof(store)
    _sign_proof_pending(store, proof_no=2, proof_text=P2)
    # 稿名 / 稿头不能点名在册那一行：这一条测的是"摘掉语义 found 之后会新注册"。
    rel = _proof_manuscript(store, sid="999998", proof_no=2, proof_text=P2,
                            proposition=S1)
    monkeypatch.setattr(
        AgentB, "_resolve_same_statement",
        lambda self, **kw: {"checked": True, "found": "", "why": "夹具：摘掉语义",
                            "keywords": [], "keyword_checked": True,
                            "hits_total": 0, "hits_named": [], "judged": False,
                            "model_calls": 0, "problems": [], "refused": "",
                            "_row": {}})
    got = _register_proof(store, Seam(keywords=["弦长函数"], found=sid), S2, rel)
    assert got.get("ok") is True, got
    assert got.get("found") == "", got
    assert len(_rows(store)) == 2, (
        "反真空失效：摘掉语义 found 之后仍然只落一行 ⇒ 语义查一圈不是承重的", _rows(store))


if __name__ == "__main__":          # pragma: no cover - 手动跑这一份时用
    raise SystemExit(pytest.main([__file__, "-q"]))

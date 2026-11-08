# -*- coding: utf-8 -*-
"""业主三裁定的验收判据：E 普通数值手稿 + B 绿色通道 + 穷举档证明栏。

## 业主原话（逐字，这就是本文件的验收标准）

> 「D对命题台账只有只读权限，D向B提交要登记的命题时都是有证明或数值实验的（即E和F的成果），
>  D侧若想提交强猜想，我们更正E侧口径为普通数值实验也需写报告，即命题+数值实验结果，
>  和F侧命题+证明一致，E侧普通数值实验不用过V，D侧呈递时一样引用E侧手稿提交强猜想
>  （即有数值实验支持的猜想），B侧做好适配（应该在手稿里找命题和数值实验程序，不录入其它内容；
>  对比穷举式数值证明要看命题+程序+穷举论证+V签）。这样就能做到D的提交物都有E或F侧背书」
> 「甲：分，不然B侧可能会拦无V签内容入台账，专门给普通数值实验开绿色通道就行。乙：空着。」
> 「穷举式的proof_test应该是填穷举论证，实验栏填相对路径」
> 「乙」（= ② 程序设计挪进 `experiments.observations["design"]`，`proof_text` 只剩 ③）

## 判据（每条都对着一个"改前必红"）

| # | 判据 | 改前为什么红 |
|---|---|---|
| a | 普通数值实验（numeric）⇒ 落 `reports/e-num-<号>.md`，且 `e-proof-*` 不出现 | E 只在 `_wants_proof` 时落稿 ⇒ 普通数值实验一条手稿都没有 |
| b | 穷举实验仍落 `e-proof-*`；`proof_text` 只有 ③（不含"程序："/"程序设计："），程序在 `code_path`、设计在 `observations["design"]` | 改前三段式证明栏 |
| c | B 收 `e-num-*` ⇒ statements 一行、`proof_text` 空、档位 `cross_check`、等级 `strong_conjecture`、V 台账 0 行也收 | 改前 B 只认 F 的证明稿；普通数值证据没有入口 |
| d | B 收穷举 `e-proof-*` ⇒ 仍要求 V 签（无 V ⇒ 拒） | 这一条是 c 的边界：绿色通道不许把穷举档也放过去 |
| e | 绿色通道不吃其它内容：手稿里塞"审查意见""后续计划"⇒ 不被录进 statements | 改前没有任何"按节取内容"的实现 |
| f | 反真空：摘掉绿色通道 ⇒ c 红；把 `parse_proof_column` 改回三段式 ⇒ b 红 | 判据自身要能红 |

全部用例在 `tmp_path` 里自建工作区，一个模型调用都不发（形态闸读预置缓存）。
"""
from __future__ import annotations

import json
import pathlib
import sys

import pytest

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from conftest import e_form_gate_ok, seed_proposition_form_ok  # noqa: E402
from agentflow import evidencebits as EB  # noqa: E402
from agentflow import exhaustionreport as ER  # noqa: E402
from agentflow import numericproof as NP  # noqa: E402
from agentflow import secretary as SEC  # noqa: E402
from agentflow.agent_b import AgentB  # noqa: E402
from agentflow.agent_e import AgentE  # noqa: E402
from agentflow.store import Store  # noqa: E402

CLAIM = "设 n<=10，则扫描全部 100 个点都满足 P(n)。"
CLAIM_KEY = "scan=100"
SCRIPT_REL = "code/scan.py"
CLAIM_EXHAUSTIVE = "设 K_9，则 R(3,4)=9。"
EXHAUSTIVE_REL = "code/enum_ramsey34.py"

PARTIAL_PROBE = """
import json
print("REPRO_RESULT: " + json.dumps({
    "result": "supports", "evidence_kind": "cross_check",
    "observations": {"points": 100, "grid": 10},
    "counterexample": None, "negation_kind": "not_proved",
}))
"""

EXHAUSTIVE_PROBE = """
import json
N = 9
SPACE = 2 ** 36
TOTAL = 68719476736
print("REPRO_RESULT: " + json.dumps({
    "result": "supports", "evidence_kind": "cross_check",
    "observations": {
        "exhaustive": True,
        "design": "把 R(3,4)=9 的上界归约成 K_9 的二染色穷举",
        "enumeration": ("枚举 K_9 全部 2^36 个二染色；按顶点置换取规范形去掉重数；"
                        "每个染色都落在枚举里，无一遗漏；边界：n=9 是上界侧的全部"),
        "search_space": {"graph": "K_9", "colourings": 68719476736},
    },
    "bound": {"n": 9}, "counterexample": None, "negation_kind": "not_proved",
}))
"""


# ------------------------------------------------------------------ 夹具

def _store(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _write(store: Store, rel: str, body: str) -> str:
    path = pathlib.Path(store.root) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return rel


def _e(store: Store) -> AgentE:
    # 形态闸本身由 `test_e_side_proposition_form_gate.py` 覆盖；这里钉"合格"。
    return e_form_gate_ok(AgentE(store, config={}, workspace_root=store.root))


def _run_numeric(store: Store) -> dict:
    _write(store, SCRIPT_REL, PARTIAL_PROBE)
    return _e(store).run_experiment(CLAIM, CLAIM_KEY, SCRIPT_REL, method="numeric")


def _run_exhaustive(store: Store) -> dict:
    _write(store, EXHAUSTIVE_REL, EXHAUSTIVE_PROBE)
    return _e(store).run_experiment(CLAIM_EXHAUSTIVE, "ramsey34=9", EXHAUSTIVE_REL,
                                    method="numeric")


def _rows(store: Store, table: str) -> list[dict]:
    return [dict(r) for r in store.rows(table)]


def _b(store: Store) -> AgentB:
    return AgentB(store, extractor=None, extract_text=None)


def _file(store: Store, *, proof_manuscript: str, statement_full: str = "",
          kind: str = "conjecture", evidence_kind: str = "cross_check",
          origin: str = "own_result", proof_text: str = "") -> dict:
    """B 的入库正路；这一批的调用方是 D（只递给手稿 + 命题不出处）。"""
    seed_proposition_form_ok(store.root, statement_full or CLAIM, kind=kind, role="B")
    return _b(store).register_statement(
        origin=origin, kind=kind, label="scan",
        statement_full=statement_full, statement_text="",
        proof_text=proof_text, evidence_kind=evidence_kind,
        proof_manuscript=proof_manuscript,
        quote_verified=False, quote_reason="own_result：E 的实验读数，没有第二份文本")


# ================================================================== a 普通数值也落稿
def test_a_a_plain_numeric_experiment_lands_an_e_num_manuscript(tmp_path):
    """a：普通数值实验 ⇒ `reports/e-num-<号>.md`；`e-proof-*` 一条都不出现。"""
    store = _store(tmp_path)
    out = _run_numeric(store)
    rel = str(out["numeric_manuscript"])
    assert rel == ER.numeric_manuscript_relpath(out["experiment_id"]), out
    assert rel.startswith("reports/e-num-"), rel
    assert out["proof_manuscript"] == "", out["proof_manuscript"]
    reports = sorted(p.name for p in (pathlib.Path(store.root) / "reports").glob("*"))
    assert reports == [rel.rsplit("/", 1)[-1]], reports
    assert not list((pathlib.Path(store.root) / "reports").glob("e-proof-*"))
    read = ER.read_numeric_manuscript(store.root, rel)
    assert read["ok"] is True, read
    assert read["statement"] == CLAIM, read["statement"]
    assert "算了什么" not in read["text"] or True  # 结果节的存在由下一行核
    assert "## 数值结果" in read["text"] and "## 命题" in read["text"], read["text"]
    row = next(r for r in _rows(store, "experiments")
               if r["experiment_id"] == out["experiment_id"])
    assert row["code_path"] == SCRIPT_REL, row["code_path"]
    assert "见实验行" in read["text"], "程序路径只许引用 code_path 那一格"
    assert SCRIPT_REL not in read["text"], "程序路径不许被抄进手稿正文"


# ================================================================== b 穷举档只剩 ③
def test_b_an_exhaustive_experiment_keeps_the_old_family_and_a_single_part_column(tmp_path):
    """b：穷举实验仍落 `e-proof-*`；证明栏只有 ③，程序/设计各归其位。"""
    store = _store(tmp_path)
    out = _run_exhaustive(store)
    assert out["evidence_kind"] == "proof", out
    rel = str(out["proof_manuscript"])
    assert rel == ER.proof_manuscript_relpath(out["experiment_id"]), rel
    assert not list((pathlib.Path(store.root) / "reports").glob("e-num-*")), \
        "穷举那一档不许同时落普通数值那一族（两族不重叠）"
    row = next(r for r in _rows(store, "experiments")
               if r["experiment_id"] == out["experiment_id"])
    column = NP.proof_column(row)
    parts = NP.parse_proof_column(column, code_path=row["code_path"])
    assert parts["problems"] == [], parts
    assert "程序：" not in column and "程序设计：" not in column, column
    assert parts["design"] == "", parts
    assert parts["enumeration"].strip(), parts
    assert parts["script"] == row["code_path"] == EXHAUSTIVE_REL, parts
    assert str((row.get("observations") or {}).get("design") or "").strip(), row
    manuscript = ER.read_proof_manuscript(store.root, rel)
    assert manuscript["ok"] is True, manuscript
    assert manuscript["proof_body"] == column, (manuscript["proof_body"], column)


# ================================================================== c 绿色通道
def test_c_b_collects_the_e_num_proposition_without_a_v_signature(tmp_path):
    """c：B 收 `e-num-*` ⇒ 一行、`proof_text` 空、`cross_check`、`strong_conjecture`、无 V 签。"""
    store = _store(tmp_path)
    out = _run_numeric(store)
    got = _file(store, proof_manuscript=str(out["numeric_manuscript"]))
    assert got.get("ok") is True, got
    rows = _rows(store, "statements")
    assert len(rows) == 1, rows
    row = rows[0]
    assert row["proof_text"] == "", row["proof_text"]
    assert row["evidence_kind"] == NP.SUPPORTED_ONLY_KIND, row["evidence_kind"]
    assert row["statement_full"] == CLAIM, row["statement_full"]
    grade = EB.bits_from_row(row)["grade"]
    assert grade == "strong_conjecture", (grade, row.get("bits"))
    assert (row.get("bits") or {}).get("numeric") == "verified", row.get("bits")
    channel = dict(got.get("numeric_channel") or {})
    assert channel.get("experiment_id") == out["experiment_id"], channel
    assert channel.get("code_path") == SCRIPT_REL, channel
    # V 台账 0 行也能收（业主：「E侧普通数值实验不用过V」）
    ledger = pathlib.Path(store.root) / "verifications"
    assert not ledger.is_dir() or not list(ledger.rglob("*.jsonl")), list(
        ledger.rglob("*.jsonl") if ledger.is_dir() else [])


def test_c2_the_plain_numeric_proposition_is_refused_when_the_form_is_bad(tmp_path):
    """c 的边界：手稿里的命题不过形态闸 ⇒ 受控拒，一行都不落。"""
    store = _store(tmp_path)
    out = _run_numeric(store)
    # 这一笔没有预置缓存（E 的普通数值路不过形态闸）⇒ B 的判定就是那一问本身：
    # 秘书回"不是命题" ⇒ 受控拒。

    class _BadSeam:
        class _Call:
            ok = True
            problem = ""
            detail = ""
            text = ""
            model = "fake"
            prompt_version = "t"
            prompt_sha256 = "0" * 64

        def ask_json(self, prompt, *, system="", task_id="", note=""):
            return ({"well_formed": False, "conditions": "", "conclusion": "",
                     "problems": ["这是流程要求，不是数学命题"],
                     "decision": "不是命题"}, self._Call())

    agent = AgentB(store, extractor=None, extract_text=None,
                   secretary=SEC.Secretary("B", root=store.root, store=store,
                                           seam=_BadSeam(), enable_model=True))
    got = agent.register_statement(
        origin="own_result", kind="conjecture", label="scan", statement_full="",
        proof_text="", evidence_kind="cross_check",
        proof_manuscript=str(out["numeric_manuscript"]),
        quote_verified=False, quote_reason="own_result：E 的实验读数")
    assert got.get("ok") is False, got
    assert got.get("kind") == "proposition_form_refused", got
    assert _rows(store, "statements") == [], _rows(store, "statements")
    rows = SEC.proposition_form_rows(store.root)
    assert rows and rows[-1]["role"] == "B" and rows[-1]["well_formed"] is False, rows


# ================================================================== d 穷举档仍要 V
def test_d_the_exhaustive_manuscript_still_needs_the_v_signature(tmp_path):
    """d：B 收穷举 `e-proof-*` ⇒ 仍要求 V 签（无 V ⇒ 拒）—— 绿色通道不许吃掉这一闸。"""
    store = _store(tmp_path)
    out = _run_exhaustive(store)
    row = next(r for r in _rows(store, "experiments")
               if r["experiment_id"] == out["experiment_id"])
    column = NP.proof_column(row)
    got = _file(store, proof_manuscript=str(out["proof_manuscript"]),
                statement_full=CLAIM_EXHAUSTIVE, kind="theorem",
                evidence_kind="proof", proof_text=column)
    assert got.get("ok") is False, got
    assert got.get("kind") == "proof_needs_third_party_signature", got
    error = str(got.get("error") or "")
    assert "缺 V 的会审签名" in error, error
    assert _rows(store, "statements") == [], _rows(store, "statements")


# ================================================================== e 不吃其它内容
def test_e_the_green_channel_does_not_eat_other_sections(tmp_path):
    """e：手稿里塞"审查意见""后续计划"⇒ 不被录进 statements。"""
    store = _store(tmp_path)
    out = _run_numeric(store)
    path = pathlib.Path(store.root) / str(out["numeric_manuscript"])
    extra = ("\n## 审查意见\n\n建议再加一条 n=11 的验证。\n\n"
             "## 后续计划\n\n下周把脚本改成增量枚举。\n\n"
             "- 备注：这一行不是命题，也不该进台账。\n")
    path.write_text(path.read_text(encoding="utf-8") + extra, encoding="utf-8",
                    newline="\n")
    got = _file(store, proof_manuscript=str(out["numeric_manuscript"]))
    assert got.get("ok") is True, got
    row = _rows(store, "statements")[0]
    blob = json.dumps(row, ensure_ascii=False)
    for bad in ("审查意见", "后续计划", "下周", "备注"):
        assert bad not in blob, (bad, blob)
    assert row["statement_full"] == CLAIM, row["statement_full"]
    assert row["proof_text"] == "", row["proof_text"]
    assert len(_rows(store, "statements")) == 1, _rows(store, "statements")


# ================================================================== f 反真空
def test_f1_removing_the_green_channel_makes_c_red(tmp_path, monkeypatch):
    """f-1：把绿色通道摘掉 ⇒ 同一笔不再拿到 `strong_conjecture`（c 红）。"""
    store = _store(tmp_path)
    out = _run_numeric(store)
    monkeypatch.setattr(AgentB, "_numeric_manuscript_channel",
                        lambda self, **kw: {"checked": False, "ok": False, "path": "",
                                            "experiment_id": "", "code_path": "",
                                            "method": "", "statement": "",
                                            "result_text": "", "manuscript": {},
                                            "problems": []})
    got = _file(store, proof_manuscript=str(out["numeric_manuscript"]))
    rows = _rows(store, "statements")
    ok = bool(got.get("ok")) and bool(rows) and \
        EB.bits_from_row(rows[0])["grade"] == "strong_conjecture"
    assert not ok, (
        "反真空失效：摘掉绿色通道之后这一笔仍然拿到了 strong_conjecture ⇒ "
        f"c 的绿不是这条通道给的：ok={got.get('ok')} kind={got.get('kind')} rows={rows}")


def test_f2_a_three_part_parser_makes_b_red(tmp_path, monkeypatch):
    """f-2：把 `parse_proof_column` 改回三段式 ⇒ b 的形态判据红。"""
    store = _store(tmp_path)
    _run_exhaustive(store)
    row = _rows(store, "experiments")[0]
    column = NP.proof_column(row)

    def _three_part(text, *, code_path=""):
        """改前那一版的口径：证明栏必须含 程序 / 程序设计 / 穷举论证 三段。"""
        raw = str(text or "")
        problems = [f"缺第 {no} 段" for no, label in
                    ((1, "程序"), (2, "程序设计"), (3, "穷举论证"))
                    if f"{label}：" not in raw]
        return {"problems": problems, "raw": raw}

    monkeypatch.setattr(NP, "parse_proof_column", _three_part)
    with pytest.raises(AssertionError):
        assert NP.parse_proof_column(column, code_path=row["code_path"])["problems"] == []


if __name__ == "__main__":          # pragma: no cover - 手动跑这一份时用
    raise SystemExit(pytest.main([__file__, "-q"]))

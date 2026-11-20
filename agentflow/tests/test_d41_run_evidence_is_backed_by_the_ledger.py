# -*- coding: utf-8 -*-
"""G8 的覆盖判据只认 `experiments` 台账，不再读任何"回执"文件。

## 现场（AH2b，`projects/lp-ball-2`）

`out/review/RUN-EVIDENCE.json` 被 `closing.run_evidence_reading` 当成证据：
文件不在 ⇒ `unbacked`（blocker），文件在且 `checked: true` ⇒ 也算证据。可全仓
没有任何写者：`specs/m.py` 只教「把这四个键凑成 `run_evidence` 交给 H」，
而 H 在那一趟从未被召唤。那份文件既不是证据也不是产物，是一句可伪造的自述。

## 这一组钉什么

`closing.numeric_conclusions` 本来就能从「成稿引了哪些 `exp:` 号」现算出分母与
分子所需的台账行。这一组把覆盖判据整个搬到台账上：

| # | 判据 | 改前为什么是红的 |
|---|---|---|
| a | 成稿引 6 条数值结论、台账 6 行齐全（有 `code_hash` 与整数 `exit_code`）⇒ `backed` | 改前要求盘上有 `RUN-EVIDENCE.json`；没有 ⇒ `unbacked` |
| b | 引到台账里没有的 `exp:` 号 ⇒ `unbacked` | 改前 `numeric_conclusions` 把不存在的号静默跳过，回执也只需覆盖"存在的那些" |
| c | 台账行缺 `exit_code` ⇒ `unbacked` | 改前只看回执自己写的 `exit_code`，台账那一格漏掉也能过 |
| d | 台账读不出来 ⇒ `unreadable` | 改前"读不出来"只发生在回执文件上；台账那一半没有这一态 |
| e | 成稿没引数值/穷举结论 ⇒ `not_applicable` | 改前同（这一条是负控，不许误伤） |
| f | 反真空：把台账行的 `exit_code` 抹掉 ⇒ a 的 `backed` 必变红 | 改前抹掉台账字段不影响判据（判据读的是回执） |
| g | M 的验收表 `run_evidence_backed_rows` 也按台账现算 | 改前它经 `run_evidence_reading` 同样依赖那份回执 |
| h | `RUN-EVIDENCE.json` 这个路径名不再出现在产品代码里；盘上留着它也不影响读数 | 改前常量与读侧都在 |

「不降低强度」那一条：改前要求"至少有一条 `exit_code` 对得上"，新口径把它换成
"台账行自己必须有整数 `exit_code`" —— 证据来源从回执自述变成台账行本身，判据没有放松。
"""
from __future__ import annotations

import inspect
import json
import pathlib

from conftest import TS, sync_counters
from agentflow import closing as CL
from agentflow import schema as S
from agentflow.store import Store

#: 两个格子的收工门（其余那几格在只做这件事的夹具里本来就成立）。
CHECKS: tuple[str, ...] = ("acceptance", "substance")

#: 台账里那几行的脚本身份（每行一份，故意不同：分母数结论条数，不数脚本个数）。
SCRIPT = "code/r34_exhaustive.py"
HASH = "4f6ea689cbfacb7a"


def _experiment(store: Store, *, exp_id: str = "000000", exit_code: int | None = 0,
                kind: str = "cross_check", method: str = "numeric") -> dict:
    """落一行数值实验。`exit_code=None` 时不写这个键（模拟缺格的历史行）。"""
    row = S.Experiment(
        experiment_id=exp_id, claim="R(3,4)=9 的穷举读数", claim_key="stmt:000007",
        method=method, evidence_kind=kind, result="supports", negation_kind="not_proved",
        code_path=f"code/r34_{exp_id}.py", code_hash=f"{HASH}{exp_id}",
        exit_code=exit_code, created_at=TS)
    payload = row.to_dict()
    if exit_code is None:
        payload.pop("exit_code", None)
    with store.tx("experiments", actor="test") as tx:
        tx.upsert("experiments", payload)
    sync_counters(store)
    return payload


def _paper(store: Store, citations: list[str], *, kind: str = "cross_check",
           doc_id: str = "0000") -> None:
    """一份引着那些实验的稿件（`cross_check` 必须自带 disclaimer —— schema 强制）。"""
    claim: dict = {"claim_id": "claim-2", "text": "R(3,4) ≥ 9 由穷举复核",
                   "citations": citations, "evidence_kind": kind, "section": "§3"}
    if kind == "cross_check":
        claim["disclaimer"] = "数值交叉验证，不构成证明"
    doc = S.Document(doc_id=doc_id, kind="paper", title="t", status="in_review",
                     claims=[claim], created_at=TS)
    doc.validate()
    with store.tx("documents", actor="test") as tx:
        tx.upsert("documents", doc.to_dict())
    sync_counters(store)


def _workspace(tmp_path: pathlib.Path, *, numeric: bool = True) -> tuple[Store, pathlib.Path]:
    root = tmp_path / "ws"
    st = Store(root)
    st.init(force=True)
    if numeric:
        _experiment(st)
        _paper(st, ["exp:000000"])
    else:
        _paper(st, ["lit:000000"])
    return st, root


def _report(st: Store, root: pathlib.Path) -> CL.ClosingReport:
    return CL.check_closing(st, project_dir=str(root), checks=CHECKS)


def _findings(rep: CL.ClosingReport) -> list[CL.Finding]:
    return [f for f in rep.findings if f.check == CL.RUN_EVIDENCE_READING]


# ============================================================ a 六条结论 + 台账齐全 ⇒ backed
def test_six_cited_conclusions_with_a_complete_ledger_are_backed(tmp_path: pathlib.Path):
    """a：成稿引 6 条 `exp:`，台账 6 行都有 `code_hash` 与整数 `exit_code` ⇒ `backed`。

    改前为什么红：这一份工作区盘上没有 `out/review/RUN-EVIDENCE.json`
    ⇒ 旧读数恒 `unbacked`，判据的分母/分子根本没轮到台账。
    """
    st, root = _workspace(tmp_path)
    ids = [f"{i:06d}" for i in range(6)]
    for eid in ids[1:]:
        _experiment(st, exp_id=eid)
    _paper(st, [f"exp:{eid}" for eid in ids])

    rep = _report(st, root)
    reading = rep.readings[CL.RUN_EVIDENCE_READING]
    assert reading["state"] == "backed", reading
    assert reading["required"] == 6 and reading["covered"] == 6, reading
    assert reading["backed_experiments"] == ids, reading
    assert reading["missing_conclusions"] == [], reading
    assert _findings(rep) == [], [f.to_dict() for f in rep.findings]
    # 2026-11-20（EMPTYCELL）：这个夹具没有验收表、也没有 research_questions ⇒
    # acceptance 记 `na`（没有可判对象），不是 `pass`；旧口径的 machine_pass（八格全 pass）
    # 因此为假 —— G8 这条 reading 不受影响，这一条判的就是它。
    assert rep.status["acceptance"] == "na", rep.to_dict()
    assert rep.machine_pass is False, rep.to_dict()


def test_a_ledger_row_must_carry_a_code_hash(tmp_path: pathlib.Path, monkeypatch):
    """a 的补半：行上有 `exit_code` 但没有 `code_hash` ⇒ 不是一条可复跑证据。

    这一行只能由读侧构造：写入期 schema 不允许"有 `code_path` 而没有 `code_hash`"，
    而历史盘上（schema 收紧之前落的）确实可能有这种行 —— 读侧必须把它们判成没背书，
    而不是"有退出码就算跑过"。
    """
    st, root = _workspace(tmp_path)
    rows = [dict(r) for r in st.rows("experiments")]
    rows[0]["code_hash"] = ""
    monkeypatch.setattr(CL, "_experiment_rows", lambda _store: rows)
    reading = CL.run_evidence_reading(st, root)
    assert reading["state"] == "unbacked", reading
    assert reading["missing_conclusions"] == ["000000"], reading
    assert "code_hash" in str(reading.get("why")), reading


# ============================================================ b 引到台账没有的号
def test_a_citation_to_an_experiment_missing_from_the_ledger_is_unbacked(
        tmp_path: pathlib.Path):
    """b：成稿引 `exp:000000`（有）与 `exp:999999`（台账没有）⇒ `unbacked`。

    改前为什么红：`numeric_conclusions` 对不存在的号 `continue` 掉，回执只要覆盖
    000000 就判 `backed` —— 一条指向不存在实验的断言在 G8 上没有读数。
    """
    st, root = _workspace(tmp_path)
    _paper(st, ["exp:000000", "exp:999999"])
    rep = _report(st, root)
    reading = rep.readings[CL.RUN_EVIDENCE_READING]
    assert reading["state"] == "unbacked", reading
    assert reading["missing_conclusions"] == ["999999"], reading
    assert any("999999" in str(reading.get("why")) for _ in [0]), reading
    assert [f.code for f in _findings(rep)] == [CL.RUN_EVIDENCE_UNBACKED_CODE]
    assert rep.status["acceptance"] == "fail", rep.to_dict()


# ============================================================ c 行缺 exit_code
def test_a_ledger_row_without_an_integer_exit_code_is_unbacked(tmp_path: pathlib.Path):
    """c：台账行没有整数 `exit_code` ⇒ `unbacked`（分不出跑过没有、绿还是红）。

    改前为什么红：旧判据只读回执自己的 `exit_code`；台账那一格漏掉时，
    回执写 0 就照样 `backed` —— 证据的来源不是台账。
    """
    st, root = _workspace(tmp_path)
    _experiment(st, exit_code=None)
    rep = _report(st, root)
    reading = rep.readings[CL.RUN_EVIDENCE_READING]
    assert reading["state"] == "unbacked", reading
    assert reading["missing_conclusions"] == ["000000"], reading
    assert "exit_code" in str(reading.get("why")), reading
    assert [f.code for f in _findings(rep)] == [CL.RUN_EVIDENCE_UNBACKED_CODE]


# ============================================================ d 台账读不出来
def test_an_unreadable_ledger_is_unreadable_not_pass(tmp_path: pathlib.Path, monkeypatch):
    """d：台账读不出来 ⇒ `unreadable`（没查成，不是"对不上"也不是"通过"）。"""
    st, root = _workspace(tmp_path)

    def _boom(_store):                     # noqa: ANN001 —— 打桩：台账读不出来
        raise RuntimeError("ledger is gone")

    monkeypatch.setattr(CL, "_experiment_rows", _boom)
    reading = CL.run_evidence_reading(st, root)
    assert reading["state"] == "unreadable", reading
    assert "ledger is gone" in str(reading.get("why")), reading


# ============================================================ e 负控：没有数值结论
def test_a_manuscript_without_numeric_conclusions_is_not_applicable(
        tmp_path: pathlib.Path):
    """e：成稿没有引到 proof / cross_check 的实验 ⇒ `not_applicable`（负控，不许误伤）。"""
    st, root = _workspace(tmp_path, numeric=False)
    rep = _report(st, root)
    reading = rep.readings[CL.RUN_EVIDENCE_READING]
    assert reading["state"] == "not_applicable", reading
    assert _findings(rep) == [], [f.to_dict() for f in rep.findings]
    # 2026-11-20（EMPTYCELL）：这个夹具没有验收表、也没有 research_questions ⇒
    # acceptance 记 `na`（没有可判对象），不是 `pass`；旧口径的 machine_pass（八格全 pass）
    # 因此为假 —— G8 这条 reading 不受影响，这一条判的就是它。
    assert rep.status["acceptance"] == "na", rep.to_dict()
    assert rep.machine_pass is False, rep.to_dict()


# ============================================================ f 反真空
def test_erasing_the_ledger_exit_code_turns_backed_red_again(tmp_path: pathlib.Path):
    """f：反真空 —— 同一条结论、同一行台账，抹掉 `exit_code` 之后 `backed` 必须变红。

    两段都做：先证真读数是 `backed`，再把台账那一格抹掉、证它变 `unbacked`，
    最后补回去、证它回到 `backed`。只做第一段的话，"恒 backed"这一种坏法测不出来。
    """
    st, root = _workspace(tmp_path)
    before = _report(st, root).readings[CL.RUN_EVIDENCE_READING]
    assert before["state"] == "backed", before

    row = dict(st.rows("experiments")[0])
    row.pop("exit_code", None)
    with st.tx("experiments", actor="test") as tx:
        tx.upsert("experiments", row)
    erased = _report(st, root).readings[CL.RUN_EVIDENCE_READING]
    assert erased["state"] == "unbacked", erased
    assert erased["missing_conclusions"] == ["000000"], erased

    row["exit_code"] = 0
    with st.tx("experiments", actor="test") as tx:
        tx.upsert("experiments", row)
    after = _report(st, root).readings[CL.RUN_EVIDENCE_READING]
    assert after["state"] == "backed", after


# ============================================================ g M 的验收表那一行
def _g8_table(root: pathlib.Path) -> None:
    p = root / "out" / "paper" / "ACCEPTANCE-CHECKS.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"checks": [{"id": "P10", "name": "可复跑（G8）",
                                         "kind": CL.RUN_EVIDENCE_LEG_KIND}]},
                            ensure_ascii=False), encoding="utf-8", newline="\n")


def _leg_row(rep: CL.ClosingReport) -> dict:
    rows = {str(r.get("id") or ""): r for r in rep.readings["acceptance"]["rows"]}
    return rows["P10"]


def test_the_g8_acceptance_row_is_computed_from_the_ledger(tmp_path: pathlib.Path):
    """g：`run_evidence_backed_rows` 的 `got/min` 从台账现算；缺格 ⇒ 那一行不成立。"""
    st, root = _workspace(tmp_path)
    _g8_table(root)
    _experiment(st, exit_code=None)
    missing = _report(st, root)
    row = _leg_row(missing)
    assert (row["got"], row["min"]) == (0, 1), row
    assert row["ok"] is False, row
    assert row["detail"]["missing_conclusions"] == ["000000"], row["detail"]
    assert missing.status["acceptance"] == "fail", missing.to_dict()
    assert CL.RUN_EVIDENCE_LEG_KIND not in [f.code for f in missing.blockers], \
        "这一行红的时候不该冒出 blocker 级：它是 M 的表里一行（读数不是判决）"

    _experiment(st, exit_code=0)
    ok = _report(st, root)
    row = _leg_row(ok)
    assert (row["got"], row["min"]) == (1, 1), row
    assert row["ok"] is True, row
    assert ok.status["acceptance"] == "pass", ok.to_dict()


def test_the_g8_acceptance_row_is_not_applicable_without_numeric_conclusions(
        tmp_path: pathlib.Path):
    """g 的负控：没有数值结论时那一行 `not_applicable`、`min=0`，不往表上加红。"""
    st, root = _workspace(tmp_path, numeric=False)
    _g8_table(root)
    rep = _report(st, root)
    row = _leg_row(rep)
    assert row["state"] == "not_applicable" and row["ok"] is None, row
    assert rep.status["acceptance"] == "pass", rep.to_dict()


# ============================================================ h 文件那条路已经没了
def test_the_receipt_file_path_is_gone_from_the_product_code(tmp_path: pathlib.Path):
    """h：「回执文件」这条路整体退场 —— 常量、读取、错误文案都不许再提它。

    另一半：盘上就算留着一份 `out/review/RUN-EVIDENCE.json`，读数也必须逐字节不变
    （它不再是任何判据的输入）。这一半防的是"常量删了、读侧还在某处偷偷读它"。
    """
    assert not hasattr(CL, "RUN_EVIDENCE_NAME"), "回执文件的常量还在"
    source = inspect.getsource(CL)
    assert "RUN-EVIDENCE" not in source, "产品代码里还留着回执文件的路径名"

    st, root = _workspace(tmp_path, numeric=False)
    before = CL.run_evidence_reading(st, root)
    stale = root / "out" / "review" / "RUN-EVIDENCE.json"
    stale.parent.mkdir(parents=True, exist_ok=True)
    stale.write_text(json.dumps({"checked": True, "commands": [
        {"claim_id": "claim-2", "command": "python code/r34_exhaustive.py",
         "exit_code": 0, "output_tail": "ok"}]}), encoding="utf-8", newline="\n")
    after = CL.run_evidence_reading(st, root)
    assert before["state"] == after["state"] == "not_applicable", (before, after)
    assert before["required"] == after["required"] == 0, (before, after)

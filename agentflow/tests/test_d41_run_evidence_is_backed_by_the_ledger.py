# -*- coding: utf-8 -*-
"""D-41（2026-10-24 真机 r34d）：G8 的回执必须有 `experiments` 台账行背书。

## 现场（硬读数）

`ACCEPTANCE.md` 自己写着"本轮没有把 `code/r34_exhaustive.py`、`code/r34_k8_independent.py`
用 `verify.run_experiment` 重跑并交出 `run_evidence`"，而盘上有
`out/review/RUN-EVIDENCE.json`：`{checked: true, generated_by: "E (code/e_g8_recheck.py)"}`。
那份回执是 E 的旁路脚本自己写的 —— 收工门与验收表此前都只问"那个文件在不在"，
于是"文件在、内容是自己写的"与"文件在、内容有台账背书"在读数上同形，`machine_pass`
照样是 true。

## 这一组钉什么

| # | 判据 | 改前为什么是红的 |
|---|---|---|
| ① | 回执在盘上而没有台账背书 ⇒ blocker `run_evidence_unbacked`、`machine_pass=False` | 门里没有这一档：没有任何 finding，两格全 pass |
| ② | 台账背书齐（脚本 + `exit_code` 都对上）⇒ 放行，不误报 | 读数里根本没有 `run_evidence` 这一格 |
| ③ | 只有 `cross_check` 而没有数值结论 ⇒ `not_applicable`（负控，不许误伤） | 同上（没有这一格 ⇒ 读不出"不适用"） |
| ④ | 反真空：把"对上台账"的判定打桩恒真 ⇒ ① 必须不再红 | ① 的判据依赖真实的比对 |

另加 ⑤–⑩（业主 2026-10-24 裁"做成全形"）：M 的验收表里有了一档可写的受控档
`run_evidence_backed_rows`（`closing.LEG_CHECK_KINDS` ＋ M 的 brief 清单两处同步），
语义是"被台账背书、且成稿引用的数值结论覆盖到的结论条数"，缺省阈值 = 本轮成稿引用的
数值结论条数 —— 0 条而正文引了数值结论 ⇒ 那一行不成立。⑤⑥ 钉现算的验收表读数
（`readings["acceptance"]["run_evidence_row"]`），⑦⑧ 钉受控档本身，⑨⑩ 钉"无背书 ⇒ fail"
与它的反真空。改前这些格全都不存在（KeyError / 词表外 `kind`）。
"""
from __future__ import annotations

import json
import pathlib

from conftest import TS, sync_counters
from agentflow import closing as CL
from agentflow import schema as S
from agentflow.store import Store

#: 两个格子的收工门（不跑论文 / 报告那几格：这一组问的是 G8 那一档，
#: 而 `substance` 在只做这件事的夹具里本来就成立 —— 用它们两格才看得出
#: `machine_pass` 的翻转是这一档造成的）。
CHECKS: tuple[str, ...] = ("acceptance", "substance")

#: 台账里那一次运行：脚本 `code/r34_exhaustive.py`，exit 0。
SCRIPT = "code/r34_exhaustive.py"
HASH = "4f6ea689cbfacb7a"


def _experiment(store: Store, *, exp_id: str = "000000", exit_code: int = 0,
                kind: str = "cross_check") -> None:
    """一行数值实验（`cross_check`：不是 T3，但仍然是"成稿引着的数值结论"）。"""
    row = S.Experiment(experiment_id=exp_id, claim="R(3,4)=9 的穷举读数",
                       claim_key="stmt:000007", method="numeric", evidence_kind=kind,
                       result="supports", negation_kind="not_proved",
                       code_path=SCRIPT, code_hash=HASH, exit_code=exit_code,
                       created_at=TS)
    row.validate()
    with store.tx("experiments", actor="test") as tx:
        tx.upsert("experiments", row.to_dict())
    sync_counters(store)


def _paper(store: Store, citations: list[str], *, kind: str = "cross_check") -> None:
    """一份引着那些实验的稿件（`cross_check` 必须自带 disclaimer —— schema 强制）。"""
    claim: dict = {"claim_id": "claim-2", "text": "R(3,4) ≥ 9 由穷举复核",
                   "citations": citations, "evidence_kind": kind, "section": "§3"}
    if kind == "cross_check":
        claim["disclaimer"] = "数值交叉验证，不构成证明"
    doc = S.Document(doc_id="0000", kind="paper", title="t", status="in_review",
                     claims=[claim], created_at=TS)
    doc.validate()
    with store.tx("documents", actor="test") as tx:
        tx.upsert("documents", doc.to_dict())
    sync_counters(store)


def _receipt(root: pathlib.Path, commands: list[dict]) -> pathlib.Path:
    """写一份 G8 回执（落点与真实工作区同一个：`out/review/RUN-EVIDENCE.json`）。"""
    p = root / "out" / "review" / "RUN-EVIDENCE.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {"checked": True, "generated_by": "E (code/e_g8_recheck.py)",
               "commands": commands, "problems": []}
    p.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8", newline="\n")
    return p


def _workspace(tmp_path: pathlib.Path, *, numeric: bool = True) -> tuple[Store, pathlib.Path]:
    root = tmp_path / "ws"
    st = Store(root)
    st.init(force=True)
    if numeric:
        _experiment(st)
        _paper(st, ["exp:000000"])
    else:
        # 只有 cross_check 那一档的断言、而它没有引任何数值实验 ⇒ 没有"数值结论"
        _paper(st, ["lit:000000"])
    return st, root


def _report(st: Store, root: pathlib.Path) -> CL.ClosingReport:
    return CL.check_closing(st, project_dir=str(root), checks=CHECKS)


def _run_evidence_findings(rep: CL.ClosingReport) -> list[CL.Finding]:
    return [f for f in rep.findings if f.check == CL.RUN_EVIDENCE_READING]


# ============================================================ ① 自述文件没有台账背书
def test_a_self_written_receipt_without_a_ledger_row_blocks_the_gate(
        tmp_path: pathlib.Path):
    """① 回执在盘上，而台账里没有这次运行 ⇒ blocker `run_evidence_unbacked`，不判 pass。

    这正是 r34d 的形态：文件在、`checked` 也是 true，但把它逐条拿去对台账时，
    没有任何一条带 `exit_code` 的运行对上它。
    """
    st, root = _workspace(tmp_path)
    _receipt(root, [{"claim_id": "stmt:000007",
                     "command": "python code/make_evidence.py",   # 台账里没有这个脚本
                     "exit_code": 0, "output_tail": "REPRO_RESULT: {}"}])
    rep = _report(st, root)
    codes = [f.code for f in _run_evidence_findings(rep)]
    assert codes == [CL.RUN_EVIDENCE_UNBACKED_CODE], codes
    assert [f.level for f in _run_evidence_findings(rep)] == ["blocker"]
    assert rep.status["acceptance"] == "fail", rep.to_dict()
    assert not rep.machine_pass, rep.to_dict()
    reading = rep.readings[CL.RUN_EVIDENCE_READING]
    assert reading["state"] == "unbacked", reading
    assert reading["covered"] == 0 and reading["missing_scripts"] == [SCRIPT], reading


def test_a_receipt_with_the_wrong_exit_code_is_not_backed(tmp_path: pathlib.Path):
    """①的半条负控：脚本对得上、`exit_code` 对不上 ⇒ 同样没有背书。

    为什么单列：只比路径的话，"跑过而且红了"与"跑过而且绿了"在回执上可以随便写 ——
    退出码是这两件事唯一的机器读数（`gates.G8_RECEIPT_KEYS` 里它排第三）。
    """
    st, root = _workspace(tmp_path)
    _receipt(root, [{"claim_id": "stmt:000007", "command": "python " + SCRIPT,
                     "exit_code": 1, "output_tail": "boom"}])
    rep = _report(st, root)
    assert [f.code for f in _run_evidence_findings(rep)] == [CL.RUN_EVIDENCE_UNBACKED_CODE]
    assert rep.status["acceptance"] == "fail", rep.to_dict()
    assert "exit_code" in rep.readings[CL.RUN_EVIDENCE_READING]["why"]


# ============================================================ ② 台账背书齐 ⇒ 放行
def test_a_receipt_backed_by_the_ledger_does_not_block(tmp_path: pathlib.Path):
    """② 每条命令都对上了台账行（脚本 + `exit_code`）⇒ 放行，且读数说得出来对上了谁。

    改前为什么红：`readings["run_evidence"]` 这一格根本不存在（门里没有这一档）。
    """
    st, root = _workspace(tmp_path)
    _receipt(root, [{"claim_id": "stmt:000007", "command": "python " + SCRIPT,
                     "exit_code": 0, "output_tail": "REPRO_RESULT: {}"}])
    rep = _report(st, root)
    assert _run_evidence_findings(rep) == [], [f.to_dict() for f in rep.findings]
    reading = rep.readings[CL.RUN_EVIDENCE_READING]
    assert reading["state"] == "backed", reading
    assert reading["covered"] == reading["required"] == 1, reading
    assert reading["backed_experiments"] == ["000000"], reading
    assert rep.status["acceptance"] == "pass", rep.to_dict()
    assert rep.machine_pass, rep.to_dict()


def test_the_receipt_can_identify_the_run_by_code_hash(tmp_path: pathlib.Path):
    """②的另一种身份：回执给 `code_hash`（不给脚本路径）也能对上同一行台账。"""
    st, root = _workspace(tmp_path)
    _receipt(root, [{"claim_id": "stmt:000007", "command": "python whatever.py",
                     "code_hash": HASH, "exit_code": 0, "output_tail": "ok"}])
    rep = _report(st, root)
    reading = rep.readings[CL.RUN_EVIDENCE_READING]
    assert reading["state"] == "backed", reading
    assert reading["backed_experiments"] == ["000000"], reading


# ============================================================ ③ 负控：没有数值结论
def test_a_cross_check_claim_without_a_numeric_experiment_is_not_applicable(
        tmp_path: pathlib.Path):
    """③ 负控：稿件里只有 `cross_check` 那一档的断言、没有引任何数值实验 ⇒ 不适用。

    这一条防的是"误伤"：没有数值/穷举结论的交付本来就不欠 G8 的回执，
    给它记 blocker 等于把"没有这一档"读成"没做这一档"。
    """
    st, root = _workspace(tmp_path, numeric=False)
    rep = _report(st, root)
    reading = rep.readings[CL.RUN_EVIDENCE_READING]
    assert reading["state"] == "not_applicable", reading
    assert _run_evidence_findings(rep) == [], [f.to_dict() for f in rep.findings]
    assert rep.status["acceptance"] == "pass", rep.to_dict()
    assert rep.machine_pass, rep.to_dict()


# ============================================================ ④ 反真空
def test_stubbing_the_ledger_match_makes_the_blocker_disappear(
        tmp_path: pathlib.Path, monkeypatch):
    """④ 反真空：把"对上台账"的判定打桩恒真 ⇒ ① 那一条必须不再红。

    这一条钉的是"①的红来自真实的比对，而不是来自一条恒真的判据"。
    打桩点是唯一的：`closing.match_run_evidence_entry`（读侧只在这一处比对）。
    """
    real = CL.match_run_evidence_entry

    def _always(entry, rows):        # noqa: ANN001 —— 打桩：恒真
        return {"experiment_id": "999999", "code_path": SCRIPT,
                "code_hash": HASH, "exit_code": 0}, ""

    st, root = _workspace(tmp_path)
    _receipt(root, [{"claim_id": "stmt:000007",
                     "command": "python code/make_evidence.py",
                     "exit_code": 0, "output_tail": "ok"}])
    monkeypatch.setattr(CL, "match_run_evidence_entry", _always)
    stubbed = _report(st, root)
    assert [f.code for f in _run_evidence_findings(stubbed)] == [], \
        "打桩成恒真之后仍然红 ⇒ 这一档的判据不在比对那一处"
    assert stubbed.readings[CL.RUN_EVIDENCE_READING]["state"] == "backed"
    # 反真空的另一半：把真实的比对放回去 ⇒ 同一条命令重新被判成没有背书
    monkeypatch.setattr(CL, "match_run_evidence_entry", real)
    restored = _report(st, root)
    assert [f.code for f in _run_evidence_findings(restored)] == \
        [CL.RUN_EVIDENCE_UNBACKED_CODE], restored.readings[CL.RUN_EVIDENCE_READING]


# ============================================================ ⑤ M 的验收表：G8 那一行
def _acceptance_row(root: pathlib.Path, row: dict) -> None:
    p = root / "out" / "paper" / "ACCEPTANCE-CHECKS.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"checks": [row]}, ensure_ascii=False),
                 encoding="utf-8", newline="\n")


def test_the_g8_row_in_ms_acceptance_reading_is_judged_by_the_ledger(
        tmp_path: pathlib.Path):
    """⑤ M 的验收表里「G8 那一行」按回执有没有台账背书给结论，不按"文件在不在"。

    这一行由收工门现算（`readings["acceptance"]["run_evidence_row"]`）：受控档位
    （`LEG_CHECK_KINDS`）加一档要连着改 M 的 brief（提示词正文，跟着 `PROMPT_VERSION`
    与十一格摘要一起动），那是本趟禁止的面 —— 所以先让它以"验收表读数"的形态机判，
    形状与表上的行同形（`id` / `kind` / `state` / `got` / `min` / `ok`）。

    两半都要有：回执缺 ⇒ 那一行 `ok=False`、`got=0 < min=1`、整格 `fail`；
    回执有背书 ⇒ 那一行 `ok=True`、`got == min`、整格回到好读数。
    """
    st, root = _workspace(tmp_path)
    _acceptance_row(root, {"id": "P1", "name": "结论正确", "kind": "document_rows",
                           "min": 1})
    missing = _report(st, root)
    acceptance = missing.readings["acceptance"]
    row = acceptance["run_evidence_row"]
    assert row["kind"] == CL.RUN_EVIDENCE_READING and row["id"] == "G8", row
    assert row["state"] == "unbacked" and row["ok"] is False, row
    assert (row["got"], row["min"]) == (0, 1), row
    assert row["missing_scripts"] == [SCRIPT], row
    assert missing.status["acceptance"] == "fail", missing.to_dict()

    _receipt(root, [{"claim_id": "claim-2", "command": "python " + SCRIPT,
                     "exit_code": 0, "output_tail": "ok"}])
    backed = _report(st, root)
    row = backed.readings["acceptance"]["run_evidence_row"]
    assert row["state"] == "backed" and row["ok"] is True, row
    assert (row["got"], row["min"]) == (1, 1), row
    assert row["backed_experiments"] == ["000000"], row


def test_a_project_without_numeric_conclusions_does_not_get_a_g8_row_object(
        tmp_path: pathlib.Path):
    """⑤的负控：没有数值结论时那一行是 `not_applicable` —— 不往表上加一条红。

    "这一档不适用"与"这一档没做"必须分得开：前者 `ok=True`（不误伤），
    `min=0`（不欠任何东西），`why` 里写清为什么。
    """
    st, root = _workspace(tmp_path, numeric=False)
    _acceptance_row(root, {"id": "P1", "name": "结论正确", "kind": "document_rows",
                           "min": 1})
    rep = _report(st, root)
    row = rep.readings["acceptance"]["run_evidence_row"]
    assert row["state"] == "not_applicable" and row["ok"] is True, row
    assert row["min"] == 0 and row["got"] == 0, row
    assert rep.status["acceptance"] == "pass", rep.to_dict()


# ============================================================ ⑨ 全形：受控档（可写）
def _g8_table(root: pathlib.Path) -> pathlib.Path:
    """M 的验收表里就写这一行（受控档 `run_evidence_backed_rows`）。"""
    p = root / "out" / "paper" / "ACCEPTANCE-CHECKS.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"checks": [{"id": "P10", "name": "可复跑（G8）",
                                         "kind": CL.RUN_EVIDENCE_LEG_KIND}]},
                            ensure_ascii=False), encoding="utf-8", newline="\n")
    return p


def _leg_row(rep: CL.ClosingReport) -> dict:
    rows = {str(r.get("id") or ""): r for r in rep.readings["acceptance"]["rows"]}
    return rows["P10"]


def test_the_g8_controlled_kind_passes_with_backing_and_fails_without_it(
        tmp_path: pathlib.Path):
    """⑨ 全形：M 在验收表里写 `run_evidence_backed_rows`，这一行按台账背书判。

    两半：
    - 正文引了数值结论、一条回执都没有 ⇒ 那一行 `got=0 < min=1`、`ok=False`、整格 `fail`，
      读数逐条点名缺的是哪一条结论（`missing_conclusions`）；
    - 回执对上台账 ⇒ `got == min == 1`、`ok=True`、整格 pass。
    """
    st, root = _workspace(tmp_path)
    _g8_table(root)
    missing = _report(st, root)
    row = _leg_row(missing)
    assert row["kind"] == CL.RUN_EVIDENCE_LEG_KIND, row
    assert row["state"] == "computed" and row["ok"] is False, row
    assert (row["got"], row["min"]) == (0, 1), row
    assert row["detail"]["missing_conclusions"] == ["000000"], row["detail"]
    assert missing.status["acceptance"] == "fail", missing.to_dict()
    assert "run_evidence_backed_rows" not in [f.code for f in missing.blockers], \
        "这一行红的时候不该冒出 blocker 级：它是 M 的表里一行（读数不是判决）"

    _receipt(root, [{"claim_id": "claim-2", "command": "python " + SCRIPT,
                     "exit_code": 0, "output_tail": "ok"}])
    backed = _report(st, root)
    row = _leg_row(backed)
    assert row["state"] == "computed" and row["ok"] is True, row
    assert (row["got"], row["min"]) == (1, 1), row
    assert row["detail"]["missing_conclusions"] == [], row["detail"]
    assert backed.status["acceptance"] == "pass", backed.to_dict()


def test_the_g8_controlled_kind_counts_every_cited_conclusion(
        tmp_path: pathlib.Path):
    """⑨的第二半：分母是成稿引用的数值结论条数，不是"回执行数"。

    成稿引两条结论（同一脚本，两条实验行）而回执只覆盖了一条 ⇒ `got=1 < min=2` 不成立。
    """
    st, root = _workspace(tmp_path)
    _experiment(st, exp_id="000001")
    _paper(st, ["exp:000000", "exp:000001"])
    _g8_table(root)
    _receipt(root, [{"claim_id": "claim-2", "command": "python " + SCRIPT,
                     "exit_code": 0, "output_tail": "ok"}])
    rep = _report(st, root)
    row = _leg_row(rep)
    assert (row["got"], row["min"]) == (2, 2), row
    assert row["detail"]["missing_conclusions"] == [], row["detail"]
    # 一份回执（一个脚本）覆盖两条结论 ⇒ 两处都算覆盖到：这是"结论条数"口径的关键
    assert row["ok"] is True, row


# ============================================================ ⑩ 反真空（全形那一档）
def test_stubbing_the_ledger_match_makes_the_g8_row_pass_anyway(
        tmp_path: pathlib.Path, monkeypatch):
    """⑩ 反真空：把"对上台账"的判定打桩恒真 ⇒ ⑨ 的 fail 必须不再出现。

    不这么做，⑨ 的"无背书 ⇒ fail"无法排除"那一档恒红"这一种可能。
    """
    real = CL.match_run_evidence_entry

    def _always(entry, rows):        # noqa: ANN001 —— 打桩：恒真
        return {"experiment_id": "999999", "code_path": SCRIPT,
                "code_hash": HASH, "exit_code": 0}, ""

    st, root = _workspace(tmp_path)
    _g8_table(root)
    _receipt(root, [{"claim_id": "claim-2", "command": "python code/make_evidence.py",
                     "exit_code": 0, "output_tail": "ok"}])
    monkeypatch.setattr(CL, "match_run_evidence_entry", _always)
    stubbed = _report(st, root)
    row = _leg_row(stubbed)
    assert row["ok"] is True and row["got"] == row["min"] == 1, row
    monkeypatch.setattr(CL, "match_run_evidence_entry", real)
    restored = _report(st, root)
    assert _leg_row(restored)["ok"] is False, _leg_row(restored)


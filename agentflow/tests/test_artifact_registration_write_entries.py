# -*- coding: utf-8 -*-
"""每个内容产物写入口都要在 `ARTIFACTS.jsonl` 里留下一条可核的归属。

## 这一组判据补的是什么

`artifact_ledger` 那一格只核"已登记行还对不对"，从不核"覆盖"：真机上
`out/tasks/*.json` 27 条全 ok，而内容产物 46 件一件登记都没有（全 `unowned`），
两件事同时成立。这一组判据钉的是后半句：产物落到盘上 ⇒ 台账里有一行，
那行的 sha256 与盘上逐字节一致。

## 每条判据都配一条反真空

正控只证明"现在绿了"；它不证明"红压在这一步"。所以每条入口都再跑一遍
把 `artifacts.record` 打桩成"不写"的负控 —— 打桩之后必须读不到那一条归属。
打桩只改一格的写入行为，判据其余部分一个字不动；它变红就说明红确实压在
"登记这一步"，而不是压在别的什么地方。
"""
from __future__ import annotations

import pathlib

import pytest

from agentflow import artifacts as A
from agentflow import exhaustionreport as ER
from agentflow import manuscriptform as MF
from agentflow import manuscriptopen as MO
from agentflow import proofregistry as PR
from agentflow import statusreport as SR
from agentflow.agent_loop import write_note
from agentflow.store import Store

#: 夹具工作区（每个入口一份，互不污染）。
PROPOSITION = "设 n≥3，则 c(G) ≤ 1。"
PROOF_TEXT = "由归纳法可得。"


def _ws(tmp_path: pathlib.Path, name: str) -> tuple[pathlib.Path, Store]:
    root = tmp_path / name
    store = Store(root)
    store.init()
    return root, store


def _surfaced_problem(entry_out: dict, *keys: str) -> str:
    """入口自己的读数里"没登记成"那句话（空串 = 它没报）。"""
    for key in keys:
        got = entry_out.get(key)
        if isinstance(got, str) and got.strip():
            return got
        if isinstance(got, (list, tuple)) and got:
            return "；".join(str(x) for x in got)
    return ""


# ---------------------------------------------------------------- 入口清单
#
# 每个 runner 在给定工作区里真的产出一件产物，返回
# `{"rel": 产物路径, "kind": 期望的 kind, "producer": 期望的生产者,
#   "problem": 入口自己报的"没登记成"（空串 = 没报）}`。
# `problem` 在正控里必须为空 —— 它是"登记失败被点名"那一侧的读数。

def _outcome(got: dict, *, rel: str, kind: str, producer: str,
             keys: tuple[str, ...] = ("why", "problems")) -> dict:
    """把入口的返回收成判据要的那几格（失败读数原样带出来，不在这里改写）。"""
    return {"ok": bool(got.get("ok")), "rel": str(rel or ""), "kind": kind,
            "producer": producer, "problem": _surfaced_problem(got, *keys)}


def _run_commit_manuscript(root: pathlib.Path, store: Store) -> dict:
    got = MF.commit_manuscript(root, family="F", manuscript_id="000001",
                               proposition=PROPOSITION, proof_text=PROOF_TEXT)
    return _outcome(got, rel=str(got.get("path") or ""), kind="f-proof-manuscript",
                    producer="F")


def _run_open_manuscript(root: pathlib.Path, store: Store) -> dict:
    got = MO.open_manuscript(root, role="F", family="f-proof", proposition=PROPOSITION,
                             form_reading={"checked": True, "well_formed": True})
    return _outcome(got, rel=str(got.get("path") or ""), kind="f-proof-manuscript",
                    producer="F")


def _run_write_section(root: pathlib.Path, store: Store) -> dict:
    opened = MO.open_manuscript(root, role="F", family="f-proof", proposition=PROPOSITION,
                                form_reading={"checked": True, "well_formed": True})
    rel = str(opened.get("path") or "")
    got = MO.write_section(root, role="F", rel=rel, section="证明", body=PROOF_TEXT)
    return _outcome(got, rel=rel, kind="f-proof-manuscript", producer="F")


def _run_register_or_rewrite(root: pathlib.Path, store: Store) -> dict:
    got = PR.register_or_rewrite(root, family="F", label="试命题", manuscript_id="000001",
                                 proposition=PROPOSITION, proof_text=PROOF_TEXT)
    return _outcome(got, rel=str(got.get("manuscript_path") or ""),
                    kind="f-proof-manuscript", producer="F")


def _run_land_report(root: pathlib.Path, store: Store) -> dict:
    got = ER.land_report(root, experiment_id="000000", claim=PROPOSITION,
                         claim_key="k", script_path="code/x.py",
                         design="全枚举 n≤20", enumeration="逐 n 枚举")
    return _outcome(got, rel=str(got.get("path") or ""), kind="experiment-report",
                    producer="E", keys=("problems", "why"))


def _run_land_manuscript(root: pathlib.Path, store: Store) -> dict:
    got = ER.land_manuscript(root, experiment_id="000000", claim=PROPOSITION,
                             claim_key="k", script_path="code/x.py", design="d",
                             enumeration="e", result="supports", evidence_kind="proof",
                             form_reading={"checked": True, "well_formed": True})
    return _outcome(got, rel=str(got.get("path") or ""), kind="e-proof-manuscript",
                    producer="E", keys=("problems", "why"))


def _run_land_numeric_manuscript(root: pathlib.Path, store: Store) -> dict:
    got = ER.land_numeric_manuscript(root, experiment_id="000001", claim=PROPOSITION,
                                     claim_key="k", script_path="code/x.py",
                                     method="numeric", params={}, observations={},
                                     result="supports", exit_code=0, runtime_sec=1.0,
                                     evidence_kind="cross_check",
                                     form_reading={"checked": True, "well_formed": True})
    return _outcome(got, rel=str(got.get("path") or ""), kind="e-num-manuscript",
                    producer="E", keys=("problems", "why"))


def _run_write_note(root: pathlib.Path, store: Store) -> dict:
    path, problem = write_note(root, "D", "第 1 条判断")
    return {"ok": not problem, "rel": "notes/D.md", "kind": "note", "producer": "D",
            "problem": str(problem or "")}


def _run_status_report(root: pathlib.Path, store: Store) -> dict:
    rel = "out/review/STATUS-20260101-0000.md"
    try:
        _report, md, _js = SR.write_status_report(store, root, stamp="20260101-0000")
    except RuntimeError as exc:                     # 登记失败那一档：入口自己抛
        return {"ok": False, "rel": rel, "kind": "status-report", "producer": "M",
                "problem": str(exc)}
    return {"ok": True, "rel": md.relative_to(root).as_posix(),
            "kind": "status-report", "producer": "M", "problem": ""}


ENTRIES = {
    "commit_manuscript": _run_commit_manuscript,
    "open_manuscript": _run_open_manuscript,
    "write_section": _run_write_section,
    "register_or_rewrite": _run_register_or_rewrite,
    "land_report": _run_land_report,
    "land_manuscript": _run_land_manuscript,
    "land_numeric_manuscript": _run_land_numeric_manuscript,
    "write_note": _run_write_note,
    "status_report": _run_status_report,
}


def _rows_of(root: pathlib.Path, rel: str) -> list[dict]:
    return [r for r in A.read_ledger(root)[0] if str(r.get("path") or "") == rel]


# ---------------------------------------------------------------- 正控（a）

@pytest.mark.parametrize("name", sorted(ENTRIES))
def test_each_write_entry_lands_a_row_whose_sha_is_the_disk_bytes(
        name: str, tmp_path: pathlib.Path) -> None:
    """造一件产物 ⇒ 台账里出现一行，路径/sha256 与盘上一致，kind/producer 分得清。"""
    root, store = _ws(tmp_path, name)
    got = ENTRIES[name](root, store)
    rel = str(got["rel"])
    assert rel, f"{name} 没有给出产物路径 ⇒ 这条判据自己接错了"
    assert got["ok"], f"{name} 连产物都没产出（{got.get('problem')}）"
    assert (root / rel).is_file(), f"{name} 声称产出了 {rel}，盘上没有"

    rows = _rows_of(root, rel)
    assert rows, f"{name} 的产物 {rel} 没有进台账（unowned）"
    last = rows[-1]
    assert last.get("sha256") == A.sha256_of(root / rel), (
        f"{name} 台账里的 sha256 不是盘上那份字节的：{last.get('sha256')} vs "
        f"{A.sha256_of(root / rel)}")
    assert int(last.get("bytes") or 0) == (root / rel).stat().st_size, last
    assert str(last.get("kind") or "") == got["kind"], last
    assert str(last.get("producer") or "") == got["producer"], last
    # 正控的另一半：入口自己没有报"没登记成"。
    assert not str(got.get("problem") or ""), got


# ---------------------------------------------------------------- 反真空（b）

@pytest.mark.parametrize("name", sorted(ENTRIES))
def test_stubbing_the_recorder_makes_that_criterion_red(
        name: str, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """把 `artifacts.record` 打桩成"不写" ⇒ 同一条判据必须读不到归属（红）。

    这是"红压在这一步"的证明：除登记行为之外什么都没改，而判据从绿变红。
    """
    root, store = _ws(tmp_path, name + "-stub-noop")
    monkeypatch.setattr(A, "record", lambda *a, **k: {})
    got = ENTRIES[name](root, store)
    rel = str(got["rel"])
    assert rel and (root / rel).is_file(), "打桩只该改登记行为，产物照样要落盘"
    assert _rows_of(root, rel) == [], (
        f"{name}：`record` 已经不写了，却仍读得到 {rel} 的归属 ⇒ 判据不压在登记这一步")


@pytest.mark.parametrize("name", sorted(ENTRIES))
def test_a_registration_failure_is_named_by_the_entry_not_swallowed(
        name: str, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """登记失败（台账写不进去）⇒ 入口的读数里必须点名，或让这次落盘按失败报。"""
    root, store = _ws(tmp_path, name + "-stub-raise")

    def _boom(*a, **k):
        raise A.ArtifactError("注入：台账写不进去")

    monkeypatch.setattr(A, "record", _boom)
    got = ENTRIES[name](root, store)
    # 产物若真的落了盘，它必须还在（"写成了、没归属"与"没写成"是两件事）；
    # 有的入口在这一档会选择"干脆不落盘"（受控拒）—— 那也是 fail-closed，允许。
    if str(got.get("rel") or ""):
        assert (root / str(got["rel"])).is_file() or not got.get("ok")
    # 而"没登记成"必须出现在这个入口自己的读数里（或让它按失败报）。
    assert str(got.get("problem") or ""), (
        f"{name}：登记失败被吞掉了 —— 它的读数里一个字都没有")


def test_every_entry_gets_covered_by_both_directions() -> None:
    """反真空的元判据：上面两组参数化覆盖的是同一批入口（不许只测正控）。"""
    assert set(ENTRIES) == {
        "commit_manuscript", "open_manuscript", "write_section",
        "register_or_rewrite", "land_report", "land_manuscript",
        "land_numeric_manuscript", "write_note", "status_report",
    }

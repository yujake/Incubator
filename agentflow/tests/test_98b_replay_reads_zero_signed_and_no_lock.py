# -*- coding: utf-8 -*-
"""98b 重放（D268 附录 E；随仓判据）：0 signed / 3 retry_report / 2 stale / 0 rejected。

## 为什么是"复制一份再跑"

`projects/` 是运行数据面（git 忽略），干净克隆里没有它；判据要能在任何机器上跑，
所以 5 份手稿 + 7 行台账 + statements 冻在 `tests/fixtures/98b_replay/`（2026-11-10
从 `projects/paper-rewrite-98b` 只读复制）。每次跑都复制到 `tmp_path`，不碰真工作区。

## 四格与两条"不许"

- 0 signed：五条都没有可复算的凭据（98b 没有 `out/vsigns/`）；
- 3 retry_report：停因全是 `report_gap`（程序性，不是数学缺陷）⇒ 同一 sha 原样再送；
- 2 stale：000002 / 000004 的现行正文没有台账行（旧版审过）；
- 0 rejected：math 的两条落在旧版正文上，不在现行正文的判定链里；
- 不许读成 unsigned：有台账行 ⇒ 永远不是"从未送审"；
- 不许锁 sha：retry_report 不是 rejected（D3 的程序性 fault 可原样再送）。
"""
from __future__ import annotations

import json
import pathlib
import shutil

from agentflow import vsigns as VS

FIXTURE = pathlib.Path(__file__).resolve().parent / "fixtures" / "98b_replay"
MANUSCRIPTS = {
    "000000": "reports/b-proof-000000.md",
    "000001": "notes/b-proof-000001.md",
    "000002": "notes/b-proof-000002.md",
    "000003": "notes/b-proof-000003.md",
    "000004": "notes/b-proof-000004.md",
}


def _copy(tmp_path: pathlib.Path) -> pathlib.Path:
    ws = tmp_path / "ws"
    shutil.copytree(FIXTURE, ws)
    return ws


def test_98b_replay_is_zero_signed_three_retry_two_stale_and_no_lock(
        tmp_path: pathlib.Path) -> None:
    ws = _copy(tmp_path)
    counts: dict[str, int] = {}
    for sid, rel in MANUSCRIPTS.items():
        got = VS.sign_reading(ws, statement_id=sid, proof_no=1, manuscript_path=rel)
        assert got["checked"] is True, got
        assert got["body_state"] == "present", (sid, got)
        counts[got["state"]] = counts.get(got["state"], 0) + 1
    assert counts == {"retry_report": 3, "stale": 2}, counts
    assert counts.get("signed", 0) == 0
    assert counts.get("rejected", 0) == 0
    assert counts.get("unsigned", 0) == 0

    # 三条 retry_report 的票数与点回那一行（可打开核对）
    got1 = VS.sign_reading(ws, statement_id="000001", proof_no=1,
                           manuscript_path=MANUSCRIPTS["000001"])
    assert (got1["state"], got1["votes"], got1["need"]) == ("retry_report", 1, 3), got1
    assert got1["evidence"]["last_row"]["verification_id"] == "v-000003", got1
    # 五份手稿的正文 sha 与设计附录 E 逐字相同（前 12 位）
    sha = {sid: VS.sign_reading(ws, statement_id=sid, proof_no=1,
                                manuscript_path=rel)["sha"][:12]
           for sid, rel in MANUSCRIPTS.items()}
    assert sha == {"000000": "05f49cf675fa", "000001": "97157c1d0795",
                   "000002": "14fbe9272592", "000003": "367a3ff23070",
                   "000004": "a1243e597539"}, sha
    # "不许锁 sha"：retry_report 不是 rejected（程序性停因，原样再送）
    for sid in ("000000", "000001", "000003"):
        got = VS.sign_reading(ws, statement_id=sid, proof_no=1,
                              manuscript_path=MANUSCRIPTS[sid])
        assert got["state"] != "rejected", (sid, got)
        assert got["credential"]["found"] is False, (sid, got)


def test_the_fixture_really_is_the_frozen_98b_ledger() -> None:
    """反真空：夹具不是空目录（5 份手稿 + 7 行台账，缺一条就说明夹具坏了）。"""
    rows = 0
    files = 0
    for path in (FIXTURE / "verifications").glob("*.jsonl"):
        files += 1
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                json.loads(line)
                rows += 1
    assert files == 5 and rows == 7, (files, rows)
    doc = json.loads((FIXTURE / "data" / "statements.json").read_text(encoding="utf-8"))
    assert len(doc.get("rows") or []) == 5
    assert len(list((FIXTURE / "reports").glob("*.md"))) == 1
    assert len(list((FIXTURE / "notes").glob("*.md"))) == 4
    # 夹具里没有凭据（0 signed 的原因不是"读不到签文件"）
    assert not (FIXTURE / "out").exists()

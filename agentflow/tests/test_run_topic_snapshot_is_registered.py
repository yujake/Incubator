# -*- coding: utf-8 -*-
"""`tests/golden/run_topic_snapshot.json` 的台账登记判据（AU2b 乙组·⑦）。

## 为什么

这份冻结快照 2026-11-06 之后就没再登记过：台账里钉的是 `04d96875fbc8`，盘上是
`8db0a45c952f`，`noai_gate --check-approvals` 一直判 `stale` —— 而 stale 与
`unregistered` 在读数上必须分得开（前者是「登记过、版本漂了」，后者是「从没登记」）。
本判据只钉「台账钉的那一版就是盘上这一版」；`reviewers` 仍为空是刻意的
（`--baseline` 登记 ≠ 批准，走查记录只能由人 `--approve` 追加），所以这里**不**断言它为空。
"""
from __future__ import annotations

import hashlib
import json
import pathlib

REPO = pathlib.Path(__file__).resolve().parents[1]
LEDGER = REPO / ".noai-approvals.json"
SNAPSHOT = REPO / "tests" / "golden" / "run_topic_snapshot.json"
REL = "tests/golden/run_topic_snapshot.json"


def test_the_run_topic_snapshot_is_registered_at_its_current_hash() -> None:
    assert SNAPSHOT.is_file(), f"{SNAPSHOT} 不在盘上"
    assert LEDGER.is_file(), f"{LEDGER} 不在盘上"
    ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
    entries = {row["path"]: row for row in ledger.get("entries") or ()}
    assert REL in entries, f"台账里没有 {REL} 的条目 ⇒ 快照又回到「没登记」"
    entry = entries[REL]
    current = hashlib.sha256(SNAPSHOT.read_bytes()).hexdigest()
    assert entry["sha256"] == current, (
        f"台账钉的是 {entry['sha256'][:12]}，盘上是 {current[:12]} ⇒ stale；"
        "跑 `python scripts/noai_gate.py --baseline --paths tests/golden/run_topic_snapshot.json` 补登记")
    assert entry["category"] == "eval-criteria"
    assert isinstance(entry.get("reviewers"), list)

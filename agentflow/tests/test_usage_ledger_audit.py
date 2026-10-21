"""`scripts/usage_ledger_audit.py`（存量重复账审计与清洗）的测试。

## 这个文件真正在钉的是什么

不是"脚本能跑"，而是两件容易同时看起来正确的事：

1. 不可判定 ≠ 干净。没有幂等键的行不是"没重复"，是"看不出来"。
   把两者折叠成一个 `clean`，正是本项目反复踩的坑。
2. 只改快照的清洗会在下一次 `rebuild` 时被复活。
   `usage_ledger.json` 只是快照，`events.jsonl` 才是可重放的真源；
   `Store.rebuild()` 会把删掉的行原样装回来。所以本文件里有一条测试
   直接调用真的 `Store.rebuild()` 来断言"清洗之后不会复活" ——
   这是唯一能证明清洗是持久的办法。
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from agentflow import schema as S
from agentflow.store import Store

TS = "2026-01-01T00:00:00+00:00"


def _load_audit():
    """按路径加载脚本（它不在 `tests/` 下，也不是一个可 import 的包成员）。"""
    p = Path(__file__).resolve().parents[1] / "scripts" / "usage_ledger_audit.py"
    spec = importlib.util.spec_from_file_location("usage_ledger_audit", p)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _row(uid: str, key: str, *, tokens: int = 1500, scope: str = "reason") -> dict:
    """一条合法的 `UsageEntry` 行，`note` 里带一个幂等键 token。"""
    return {
        "usage_id": uid,
        "scope": scope,
        "role": "modelgw",
        "task_id": "t-x",
        "tokens_in": 1000,
        "tokens_out": tokens - 1000,
        "tokens_total": tokens,
        "usd": 0.00082,
        "attempts": 1,
        "at": TS,
        "note": f"modelgw;call_index=0;outcome=ok；{key}",
    }


def _write_ws(root: Path, rows: list[dict], *, with_events: bool = True) -> Store:
    """造一个工作区，快照 + 事件流都如实写上（模拟修复前留下的存量数据）。"""
    st = Store(root)
    st.init()
    (root / "data" / "usage_ledger.json").write_text(
        # 版本号写当前契约（`schema.SCHEMA_VERSION`），不写死一个数字：
        # 这一格原先是 `1`，S1r 并表把契约升到 2 之后它就成了一份"按定义读不进来"的
        # 快照（读期 fail-closed）⇒ 判据在第一行 `st.rows("usage_ledger")` 就炸了。
        # 这个夹具要模拟的是"修复前留下的重复账"，不是"旧磁盘格式"。
        json.dumps({"schema_version": S.SCHEMA_VERSION, "rows": rows},
                   ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    if with_events:
        lines = [
            json.dumps({"seq": i + 1, "ts": TS, "op": "upsert", "table": "usage_ledger",
                        "row": r, "actor": "test", "note": ""}, ensure_ascii=False)
            for i, r in enumerate(rows)
        ]
        (root / "data" / "events.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return st


# ------------------------------------------------------------------ 审计口径


def test_audit_finds_duplicate_keys_and_counts_wasted_tokens(tmp_path: Path):
    """同一个键的 3 行必须被认出是 2 行多余，并算出重复扣掉的 token。"""
    mod = _load_audit()
    root = tmp_path / "ws"
    _write_ws(root, [
        _row("0000", "idem-aaaaaaaaaaaa"),
        _row("0001", "idem-aaaaaaaaaaaa"),
        _row("0002", "idem-aaaaaaaaaaaa"),
        _row("0003", "idem-bbbbbbbbbbbb"),
    ])
    a = mod.audit(mod.load_rows(root))
    assert len(a["duplicates"]) == 1
    assert a["duplicate_rows"] == 2, "3 行同一个键 ⇒ 2 行是多余的"
    assert a["wasted_tokens"] == 3000, "重复扣掉的是 2 笔 × 1500"
    assert a["single"] == 1
    assert a["unmarked"] == []


def test_rows_without_a_key_are_undecidable_not_clean(tmp_path: Path):
    """没有幂等键的行不是"没重复"，是"看不出来" —— 必须报 requires_action。

    这些行来自直接调用 `TokenMeter.charge` 的路径（没有键可依据）。
    把它们算进 `clean` 就是把"没检查"当成了"检查过了没问题"。
    """
    mod = _load_audit()
    root = tmp_path / "ws"
    unmarked = _row("0000", "idem-aaaaaaaaaaaa")
    unmarked["note"] = "tokenmeter 直接入账，没有键"
    _write_ws(root, [unmarked])

    code, res = mod.run(root, apply=False, backup_dir=None, force=False)
    assert res["unmarked_rows"] == 1
    assert res["verdict"] == "requires_action", res
    assert code == mod.EXIT_REQUIRES_ACTION


def test_empty_ledger_is_clean(tmp_path: Path):
    """真空表是 clean（这一条与上面那条构成一对，防"一律报警"）。"""
    mod = _load_audit()
    root = tmp_path / "ws"
    _write_ws(root, [])
    code, res = mod.run(root, apply=False, backup_dir=None, force=False)
    assert res["verdict"] == "clean"
    assert code == mod.EXIT_CLEAN


def test_missing_ledger_is_unknown_not_clean(tmp_path: Path):
    """读不到必须报 unknown(2)，绝不降级成 clean(0)。"""
    mod = _load_audit()
    with pytest.raises(mod.UnknownError):
        mod.load_rows(tmp_path / "does-not-exist")
    code = mod.main(["--root", str(tmp_path / "does-not-exist")])
    assert code == mod.EXIT_UNKNOWN


# ------------------------------------------------------------------ 清洗


def test_apply_removes_duplicates_and_compacts_events(tmp_path: Path):
    """`--apply` 同时改快照与事件流，并给出回放自证。"""
    mod = _load_audit()
    root = tmp_path / "ws"
    _write_ws(root, [
        _row("0000", "idem-aaaaaaaaaaaa"),
        _row("0001", "idem-aaaaaaaaaaaa"),
        _row("0002", "idem-bbbbbbbbbbbb"),
    ])
    backup_dir = tmp_path / "backup"

    code, res = mod.run(root, apply=True, backup_dir=backup_dir, force=False)
    assert code == mod.EXIT_CLEAN, res
    assert res["removed_rows"] == 1
    assert res["removed_usage_ids"] == ["0001"], "保留 usage_id 最小的那一行"
    assert res["replay_check"] == "事件流与快照一致"
    assert res["events"]["dropped_events"] == 1

    rows = mod.load_rows(root)
    assert [r["usage_id"] for r in rows] == ["0000", "0002"]
    assert sorted(p.name for p in backup_dir.iterdir()) == ["counters.json", "events.jsonl", "usage_ledger.json"]


def test_cleaning_survives_a_real_rebuild(tmp_path: Path):
    """直接调用真的 `Store.rebuild()`：删掉的行不许复活。

    这是整件事的要点。`usage_ledger.json` 是快照，`events.jsonl` 是可重放的真源；
    只改快照的话，用户按文档跑一次 `rebuild` 就会把重复账装回来 ——
    而那时脚本早就"成功"退出了。
    """
    mod = _load_audit()
    root = tmp_path / "ws"
    st = _write_ws(root, [
        _row("0000", "idem-aaaaaaaaaaaa"),
        _row("0001", "idem-aaaaaaaaaaaa"),
        _row("0002", "idem-bbbbbbbbbbbb"),
    ])
    before = len(st.rows("usage_ledger"))
    assert before == 3

    code, res = mod.run(root, apply=True, backup_dir=tmp_path / "backup", force=False)
    assert code == mod.EXIT_CLEAN, res

    st.rebuild(backup=False)
    after = st.rows("usage_ledger")
    assert [r["usage_id"] for r in after] == ["0000", "0002"], (
        f"rebuild 之后重复账复活了：{[r['usage_id'] for r in after]}"
    )
    assert sum(int(r["tokens_total"]) for r in after) == 3000, "清洗后只应剩 2 笔"


def test_snapshot_only_cleanup_would_be_undone_by_rebuild(tmp_path: Path):
    """陷阱的可执行证据：只改快照、不动事件流 ⇒ rebuild 把删掉的行装回来。

    这条测试故意做错那件事，用来证明上面那条测试的断言不是空的
    （否则"rebuild 之后还是 2 行"可能只是因为 rebuild 什么也没做）。
    """
    mod = _load_audit()
    root = tmp_path / "ws"
    st = _write_ws(root, [
        _row("0000", "idem-aaaaaaaaaaaa"),
        _row("0001", "idem-aaaaaaaaaaaa"),
    ])
    # 只改快照（这正是"顺手删掉重复行"的直觉做法）
    mod.write_ledger(root, [r for r in mod.load_rows(root) if r["usage_id"] != "0001"])
    assert [r["usage_id"] for r in mod.load_rows(root)] == ["0000"]

    st.rebuild(backup=False)
    assert [r["usage_id"] for r in st.rows("usage_ledger")] == ["0000", "0001"], (
        "只改快照的清洗本应被 rebuild 复活 —— 若这里没复活，"
        "说明上面那条'清洗能扛住 rebuild'的测试没有在验证任何东西"
    )


def test_apply_refuses_without_backup_dir(tmp_path: Path):
    """`--apply` 不给 `--backup-dir` 必须拒绝（本仓库不是 git 仓库，没有第二道后悔药）。"""
    mod = _load_audit()
    root = tmp_path / "ws"
    _write_ws(root, [_row("0000", "idem-aaaaaaaaaaaa"), _row("0001", "idem-aaaaaaaaaaaa")])

    code, res = mod.run(root, apply=True, backup_dir=None, force=False)
    assert code == mod.EXIT_REQUIRES_ACTION
    assert "backup-dir" in res["note"]
    assert len(mod.load_rows(root)) == 2, "拒绝时不许改动任何东西"


def test_apply_refuses_conflicting_rows_unless_forced(tmp_path: Path):
    """同一个键的多行 token 数不一致 ⇒ 拒绝自动清洗。

    同一个键意味着同一次调用，token 数不一致说明还有别的缺陷在起作用；
    此时"保留哪一行"不是一个可以机械决定的问题，交给人裁决。
    """
    mod = _load_audit()
    root = tmp_path / "ws"
    _write_ws(root, [
        _row("0000", "idem-aaaaaaaaaaaa", tokens=1500),
        _row("0001", "idem-aaaaaaaaaaaa", tokens=3000),
    ])
    code, res = mod.run(root, apply=True, backup_dir=tmp_path / "backup", force=False)
    assert code == mod.EXIT_REQUIRES_ACTION
    assert res["conflicting_keys"] == ["idem-aaaaaaaaaaaa"]
    assert len(mod.load_rows(root)) == 2, "拒绝时不许改动任何东西"

    # --force 之后才清（并如实记录用了 force）
    code2, res2 = mod.run(root, apply=True, backup_dir=tmp_path / "backup2", force=True)
    assert code2 == mod.EXIT_CLEAN, res2
    assert res2["removed_rows"] == 1


def test_dry_run_never_writes(tmp_path: Path):
    """默认（不带 `--apply`）必须一个字节都不改。"""
    mod = _load_audit()
    root = tmp_path / "ws"
    _write_ws(root, [_row("0000", "idem-aaaaaaaaaaaa"), _row("0001", "idem-aaaaaaaaaaaa")])
    ledger_before = (root / "data" / "usage_ledger.json").read_bytes()
    events_before = (root / "data" / "events.jsonl").read_bytes()

    code, res = mod.run(root, apply=False, backup_dir=None, force=False)
    assert code == mod.EXIT_REQUIRES_ACTION
    assert res["plan"]["keep"] == ["0000"] and res["plan"]["drop"] == ["0001"]
    assert (root / "data" / "usage_ledger.json").read_bytes() == ledger_before
    assert (root / "data" / "events.jsonl").read_bytes() == events_before


def test_settle_keys_from_conductor_are_recognized(tmp_path: Path):
    """`conductor` 写的 `settle-<hash>` 键与 `modelcost` 的 `idem-<hash>` 同等对待。"""
    mod = _load_audit()
    root = tmp_path / "ws"
    r = _row("0000", "settle-0123456789ab")
    r2 = _row("0001", "settle-0123456789ab")
    _write_ws(root, [r, r2])
    a = mod.audit(mod.load_rows(root))
    assert list(a["duplicates"]) == ["settle-0123456789ab"]


def test_a_bare_word_that_looks_like_a_key_is_not_a_key(tmp_path: Path):
    """键必须是独立 token 且形状严格：正文里出现 `idem-...` 不算键。

    否则自由文本的 `note` 会让判重指向另一行 —— 那会造成静默少记一笔账。
    """
    mod = _load_audit()
    root = tmp_path / "ws"
    r = _row("0000", "idem-aaaaaaaaaaaa")
    r["note"] = "modelgw;说明里提到 idem-aaaaaaaaaaaa 这个词但整段是一个 token"
    _write_ws(root, [r])
    a = mod.audit(mod.load_rows(root))
    assert a["duplicates"] == {}
    assert len(a["unmarked"]) == 1, "整段是一个 token ⇒ 不算带键，应当不可判定"

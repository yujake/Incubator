"""共享存储的并发与原子性 —— 本设计的核心主张（DESIGN.md §2）。

真并发验证方式：用 ``multiprocessing``（spawn，真进程，filelock 是进程级锁）
起 4 个子进程，各自对 statements 表做 20 次"单事务分配 ID + 追加行"。
子进程通过文件回报结果（不返回值）：本沙箱禁止创建命名管道，
``multiprocessing.Queue/Value/Lock`` 会以 WinError 5 失败，而 ``Process`` 可用。

## S1r 并表（`SCHEMA_VERSION=2`）之后的改动

本文件守的是并发与原子性判据（无丢失更新 / 同事务唯一发号 / 用尽 fail-closed /
校验失败整笔回滚 / 原子写不留残渣 / 锁超时）,行只是标本：并表把 `concepts`
表真删 ⇒ 标本换成 `statements` 的一行（`kind="stmt"` / 主键 `stmt_id`）。
`test_atomic_write_leaves_no_tmp_residue` 里那句用来构造"非法行"的
`related_concepts` 未升序，换成同一张表上的 `derived_from` 未升序
（同一张表的另一个集合字段，判据仍是"集合字段必须升序去重"）。
"""

from __future__ import annotations

import json
import multiprocessing as mp
import time
from pathlib import Path
from typing import Any

import pytest

from agentflow import schema as S
from agentflow.store import MAX_ID, Store, StoreError

from conftest import read_data_bytes

RESULTS_DIR = "_worker_results"

#: 固定时间戳：夹具行不许依赖当前时间（与 `tests/conftest.py` 同口径）。
TS = "2026-01-01T00:00:00+00:00"


def _stmt_row(sid: str, label: str, *, derived_from: list | None = None) -> dict:
    """一条合法的 `statements` 行（形状与 `schema.Statement.validate` 对齐）。

    `derived_from` 是这张表上声明为 `set` 的集合字段 —— 需要构造"集合违规"的
    用例（升序去重 / 混类型）时用它，与原先用 `concepts.related_concepts` 同一判据。
    """
    return {"stmt_id": sid, "origin": "own_result", "kind": "theorem", "label": label,
            "statement_full": f"{label} 的命题正文（夹具）",
            "derived_from": list(derived_from or []),
            "quote_verified": None, "quote_reason": "自产结果（测试夹具）",
            "created_at": TS}


def _clean_data_files() -> list[str]:
    """`init()` 之后 `data/` 里应当恰好有的文件（判据由 schema 派生，不另抄一张名单）。

    `tests/conftest.py` 的 `DATA_FILES` 是另一处落位（逐字节快照要用它）；
    这里按 `schema.TABLES` 现推，于是"某张表的文件该不该在盘上"只有一个来源。
    并表之后 `concepts.json` 不该再出现 —— 这正是本函数要守的那一格。
    """
    return sorted({spec["file"] for spec in S.TABLES.values()} | {"counters.json", "events.jsonl"})


# --------------------------------------------------------------------------- worker
# 注意：spawn 要求 target 是可 pickle 的模块级函数，所以 worker 全部放在顶层。


def _stmt_appender(root: str, tag: str, n: int) -> None:
    """子进程 worker：在 root 工作区里做 n 次「单事务 alloc_id + upsert 命题行」。"""
    import traceback

    out_dir = Path(root) / RESULTS_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {"tag": tag, "ids": [], "error": None}
    try:
        st = Store(root)
        for i in range(n):
            with st.tx("statements", actor=tag, note=f"append-{i}") as tx:
                sid = tx.alloc_id("stmt")
                tx.upsert("statements", _stmt_row(sid, f"{tag}-{i}"))
                report["ids"].append(sid)
    except BaseException:
        report["error"] = traceback.format_exc()
    (out_dir / f"{tag}.json").write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")


def _lock_holder(root: str, ready: str, seconds: float) -> None:
    """子进程 worker：持住 literature 表的排他锁若干秒，并写 ready 文件以示就绪。"""
    from filelock import FileLock

    lock_path = Path(root) / "data" / ".locks" / "literature.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with FileLock(str(lock_path)):
        Path(ready).write_text("held", encoding="utf-8")
        time.sleep(seconds)


def _run_processes(target, args_list, timeout: float = 180.0) -> list[Any]:
    """并发启动若干子进程并等待退出，返回各进程的 exitcode 列表。"""
    ctx = mp.get_context("spawn")
    procs = [ctx.Process(target=target, args=args) for args in args_list]
    for p in procs:
        p.start()
    deadline = time.time() + timeout
    for p in procs:
        p.join(max(1.0, deadline - time.time()))
    codes = [p.exitcode for p in procs]
    for p in procs:
        if p.is_alive():
            p.terminate()
            p.join(10)
    return codes


# --------------------------------------------------------------------------- 用例


def test_no_lost_update_across_four_processes(tmp_path: Path) -> None:
    """4 个真进程各追加 20 行 → 最终恰好 80 行且 ID 连续无重复（不存在丢失更新）。"""
    root = tmp_path / "ws"
    Store(root).init()

    codes = _run_processes(
        _stmt_appender,
        [(str(root), f"p{i}", 20) for i in range(4)],
    )
    assert codes == [0, 0, 0, 0], f"子进程异常退出：{codes}"

    reports = [
        json.loads((root / RESULTS_DIR / f"p{i}.json").read_text(encoding="utf-8"))
        for i in range(4)
    ]
    assert [r["error"] for r in reports] == [None, None, None, None]

    st = Store(root)
    ids = sorted(r["stmt_id"] for r in st.rows("statements"))
    assert len(ids) == 80, f"期望 80 行，实际 {len(ids)} 行（有更新被覆盖丢失）"
    assert ids == [S.format_id(i) for i in range(80)], "ID 必须从当前宽度起连续且无重复"
    allocated = [i for r in reports for i in r["ids"]]
    assert len(set(allocated)) == 80, "同一个 ID 被发给了两个进程"
    assert st.read("counters")["counters"]["stmt"] == 80


def test_alloc_id_is_unique_within_a_single_tx(store: Store) -> None:
    """同一事务内连续 alloc_id 5 次必须得到 5 个不同 ID（曾经同一事务重复发同一个号）。"""
    with store.tx("statements", actor="test") as tx:
        ids = [tx.alloc_id("stmt") for _ in range(5)]
    assert ids == [S.format_id(0), S.format_id(1), S.format_id(2), S.format_id(3), S.format_id(4)]
    assert store.read("counters")["counters"]["stmt"] == 5


def test_alloc_id_fails_closed_when_space_exhausted(store: Store) -> None:
    """4 位编号用尽必须显式报错，而不是静默进位到 5 位（§0.1 C4）。"""
    (store.data / "counters.json").write_text(
        json.dumps({"schema_version": S.SCHEMA_VERSION, "counters": {"stmt": MAX_ID + 1}}),
        encoding="utf-8",
    )
    with pytest.raises(StoreError):
        with store.tx("statements") as tx:
            tx.alloc_id("stmt")


def test_failed_validation_rolls_back_whole_tx(store: Store) -> None:
    """校验失败必须整笔回滚：磁盘上的所有快照与事件日志逐字节不变。"""
    before = read_data_bytes(store)
    with pytest.raises(ValueError):
        with store.tx("statements", actor="test") as tx:
            good = _stmt_row("0000", "群")
            tx.upsert("statements", good)
            # 非法形态：集合字段 `derived_from` 未升序去重（`schema._set_problems` 判它）
            tx.upsert("statements", _stmt_row("0001", "环", derived_from=["0009", "0002"]))
    after = read_data_bytes(store)
    assert after == before, "回滚不彻底：磁盘上有文件被改动了"
    assert store.rows("statements") == []


def test_failed_validation_rolls_back_literature_and_counters(store: Store) -> None:
    """跨表事务里任一行非法（含受控词表违规）时，literature 与 counters 都不得落盘。"""
    before = read_data_bytes(store)
    with pytest.raises(ValueError):
        with store.tx("literature", actor="test") as tx:
            tx.alloc_id("lit")
            tx.upsert(
                "literature",
                S.Literature(
                    lit_id="0000", title="T", type="XX", summary="", path=None
                ).to_dict(),
            )
    assert read_data_bytes(store) == before
    assert store.rows("literature") == []
    assert store.read("counters")["counters"] == {}


def test_atomic_write_leaves_no_tmp_residue(store: Store) -> None:
    """os.replace 原子写不得在目录里留下 *.tmp 半成品（成功与失败路径都不能）。"""
    with store.tx("statements", actor="test") as tx:
        tx.upsert("statements", _stmt_row(tx.alloc_id("stmt"), "群"))
    with pytest.raises(ValueError):
        with store.tx("statements", actor="test") as tx:
            tx.upsert("statements", _stmt_row("0001", "环", derived_from=["0005", "0003"]))
    assert list(store.data.glob("*.tmp")) == []
    # 判据与原先同字面（`data/` 下"恰好是这些文件"）——列出来的名单由 schema 现推，
    # 于是并表之后 `concepts.json` 的缺席也在这条断言里（不另抄一张名单，见 `_clean_data_files`）。
    assert sorted(p.name for p in store.data.iterdir() if p.is_file()) == _clean_data_files()
    assert "concepts.json" not in _clean_data_files(), "并表之后老表文件不该再出现在盘上"


def test_lock_timeout_raises_store_error(tmp_path: Path) -> None:
    """另一个进程持锁时，极短 timeout 的事务必须抛 StoreError（而不是静默穿透）。"""
    root = tmp_path / "ws"
    st = Store(root)
    st.init()
    ready = tmp_path / "lock-held.txt"

    ctx = mp.get_context("spawn")
    holder = ctx.Process(target=_lock_holder, args=(str(root), str(ready), 30.0))
    holder.start()
    try:
        deadline = time.time() + 30
        while not ready.exists() and time.time() < deadline:
            time.sleep(0.05)
        assert ready.exists(), "持锁子进程未就绪，无法验证锁超时"

        started = time.time()
        with pytest.raises(StoreError):
            with st.tx("literature", timeout=0.3) as tx:
                tx.rows("literature")
        assert time.time() - started < 10, "锁超时没有及时生效"
    finally:
        holder.terminate()
        holder.join(10)


def test_failed_tx_does_not_leak_id_allocation(store: Store) -> None:
    """§2.5：分配与建行必须同事务 —— 失败事务回滚后计数器不得泄漏（否则留空洞/撞号）。

    这条断言在实现有 bug 时会失败：``Store.tx`` 只在成功提交后清空
    ``self._dirty_counters``（store.py:268），异常路径下不清理，于是下一次
    alloc_id 会从一个"磁盘上并不存在"的计数继续发号。
    """
    with pytest.raises(ValueError):
        with store.tx("statements", actor="test") as tx:
            tx.alloc_id("stmt")              # 发出 0000，但整笔会失败
            tx.upsert("statements", _stmt_row("0001", "环", derived_from=["0009", "0002"]))
    assert store.read("counters")["counters"].get("stmt", 0) == 0, "磁盘计数器应保持回滚后的值"

    with store.tx("statements", actor="test") as tx:
        sid = tx.alloc_id("stmt")
        tx.upsert("statements", _stmt_row(sid, "群"))
    assert sid == S.format_id(0), f"回滚后重新分配应仍从 0000 开始，实际拿到 {sid}（ID 空洞）"

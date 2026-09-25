"""共享存储的并发与原子性 —— 本设计的核心主张（DESIGN.md §2）。

真并发验证方式：用 ``multiprocessing``（spawn，真进程，filelock 是进程级锁）
起 4 个子进程，各自对 concepts 表做 20 次"单事务分配 ID + 追加行"。
子进程通过文件回报结果（不返回值）：本沙箱禁止创建命名管道，
``multiprocessing.Queue/Value/Lock`` 会以 WinError 5 失败，而 ``Process`` 可用。
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

from conftest import DATA_FILES, read_data_bytes

RESULTS_DIR = "_worker_results"


# --------------------------------------------------------------------------- worker
# 注意：spawn 要求 target 是可 pickle 的模块级函数，所以 worker 全部放在顶层。


def _concept_appender(root: str, tag: str, n: int) -> None:
    """子进程 worker：在 root 工作区里做 n 次「单事务 alloc_id + upsert 概念行」。"""
    import traceback

    out_dir = Path(root) / RESULTS_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {"tag": tag, "ids": [], "error": None}
    try:
        st = Store(root)
        for i in range(n):
            with st.tx("concepts", actor=tag, note=f"append-{i}") as tx:
                cid = tx.alloc_id("concept")
                row = S.Concept(
                    concept_id=cid,
                    name=f"{tag}-{i}",
                    definition="",
                    normalized_name=f"{tag}-{i}",
                )
                row.validate()
                tx.upsert("concepts", row.to_dict())
                report["ids"].append(cid)
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
        _concept_appender,
        [(str(root), f"p{i}", 20) for i in range(4)],
    )
    assert codes == [0, 0, 0, 0], f"子进程异常退出：{codes}"

    reports = [
        json.loads((root / RESULTS_DIR / f"p{i}.json").read_text(encoding="utf-8"))
        for i in range(4)
    ]
    assert [r["error"] for r in reports] == [None, None, None, None]

    st = Store(root)
    ids = sorted(r["concept_id"] for r in st.rows("concepts"))
    assert len(ids) == 80, f"期望 80 行，实际 {len(ids)} 行（有更新被覆盖丢失）"
    assert ids == [f"{i:04d}" for i in range(80)], "ID 必须从 0000 起连续且无重复"
    allocated = [i for r in reports for i in r["ids"]]
    assert len(set(allocated)) == 80, "同一个 ID 被发给了两个进程"
    assert st.read("counters")["counters"]["concept"] == 80


def test_alloc_id_is_unique_within_a_single_tx(store: Store) -> None:
    """同一事务内连续 alloc_id 5 次必须得到 5 个不同 ID（曾经同一事务重复发同一个号）。"""
    with store.tx("concepts", actor="test") as tx:
        ids = [tx.alloc_id("concept") for _ in range(5)]
    assert ids == ["0000", "0001", "0002", "0003", "0004"]
    assert store.read("counters")["counters"]["concept"] == 5


def test_alloc_id_fails_closed_when_space_exhausted(store: Store) -> None:
    """4 位编号用尽必须显式报错，而不是静默进位到 5 位（§0.1 C4）。"""
    (store.data / "counters.json").write_text(
        json.dumps({"schema_version": S.SCHEMA_VERSION, "counters": {"concept": MAX_ID + 1}}),
        encoding="utf-8",
    )
    with pytest.raises(StoreError):
        with store.tx("concepts") as tx:
            tx.alloc_id("concept")


def test_failed_validation_rolls_back_whole_tx(store: Store) -> None:
    """校验失败必须整笔回滚：磁盘上的所有快照与事件日志逐字节不变。"""
    before = read_data_bytes(store)
    with pytest.raises(ValueError):
        with store.tx("concepts", actor="test") as tx:
            good = S.Concept(concept_id="0000", name="群", definition="合法的行")
            tx.upsert("concepts", good.to_dict())
            bad = S.Concept(
                concept_id="0001",
                name="环",
                definition="非法：related_concepts 未升序",
                related_concepts=["0009", "0002"],
            )
            tx.upsert("concepts", bad.to_dict())
    after = read_data_bytes(store)
    assert after == before, "回滚不彻底：磁盘上有文件被改动了"
    assert store.rows("concepts") == []


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
    with store.tx("concepts", actor="test") as tx:
        row = S.Concept(concept_id=tx.alloc_id("concept"), name="群", definition="")
        tx.upsert("concepts", row.to_dict())
    with pytest.raises(ValueError):
        with store.tx("concepts", actor="test") as tx:
            tx.upsert(
                "concepts",
                S.Concept(
                    concept_id="0001", name="环", definition="", related_concepts=["0005", "0003"]
                ).to_dict(),
            )
    assert list(store.data.glob("*.tmp")) == []
    assert sorted(p.name for p in store.data.iterdir() if p.is_file()) == sorted(DATA_FILES)


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
        with store.tx("concepts", actor="test") as tx:
            tx.alloc_id("concept")           # 发出 0000，但整笔会失败
            tx.upsert(
                "concepts",
                S.Concept(
                    concept_id="0001", name="环", definition="",
                    related_concepts=["0009", "0002"],
                ).to_dict(),
            )
    assert store.read("counters")["counters"].get("concept", 0) == 0, "磁盘计数器应保持回滚后的值"

    with store.tx("concepts", actor="test") as tx:
        cid = tx.alloc_id("concept")
        tx.upsert("concepts", S.Concept(concept_id=cid, name="群", definition="").to_dict())
    assert cid == "0000", f"回滚后重新分配应仍从 0000 开始，实际拿到 {cid}（ID 空洞）"

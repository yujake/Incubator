"""`F-1` / `F-2` / `F-3` 的回归判据：提交顺序、发号守卫、原子写。

三处都在 `src/agentflow/store.py`（FC-27 禁改区），2026-09-26 修，改前备份在
`temp/zone-backup-r3-src_agentflow_store.py`。

## 三条各自的"改前必红"在哪

| 条目 | 负控（改前必红） |
|---|---|
| `F-1` 提交顺序 | `test_a_half_written_batch_is_reported_not_silently_dropped`：造一条"快照里有、事件里没有提交标记"的行 ⇒ rebuild 必须报出不完整批次（改前 `batches_incomplete` 这个键根本不存在，且它会安静地丢掉那一行） |
| `F-2` 发号守卫 | `test_alloc_id_without_the_target_table_declared_raises`（在同目录的 `test_store_alloc_guard.py` 里，与本文件的 `test_alloc_id_...` 成对） |
| `F-3` 原子写 | `test_concurrent_atomic_writers_do_not_collide`：两个真进程各写 30 次同一个文件 ⇒ 零 `OSError`、最终文件是合法 JSON、不留 `.tmp`（改前固定临时名会抛 `PermissionError [WinError 32]`） |

## 一条容易写错的判据（我第一版就写错了）

"崩在事件追加"这个注入，在新顺序下不是缺陷：事件先落、快照后落，
事件追加失败 ⇒ 快照还是上一版、日志里什么都没有 ⇒ 磁盘状态是一致的，
这一次提交就是"没发生"。
真正的缺陷形态是"快照超前于日志"，而那正是旧顺序（先快照后事件）的产物。
所以判据必须打在"快照里有、日志里没有提交标记"这个状态上，
而不是打在"某一次注入有没有丢行"上 —— 后者会把一次正确的"提交没发生"读成缺陷。

## `R3-3`：上面那句话在 2026-09-26 之前只是"一半"被判据覆盖

"快照超前于日志"有两个形态：

1. 日志里有一批没有提交标记的事件 —— 由 `batches_incomplete` 覆盖
   （`test_a_half_written_batch_is_reported_not_silently_dropped`）；
2. 快照里有一行日志里根本没有过（旧顺序崩在两者之间，或有人手工往
   `<表>.json` 加行）—— 这一档当时没有任何判据：`rebuild` 只看 `op=commit`
   标记，那一行被静默丢掉而计数为 0。
   现在由 `snapshot_rows_not_in_log` / `snapshot_ahead` 覆盖
   （`test_rebuild_reports_rows_that_are_in_the_snapshot_but_not_in_the_log`，
   以及"半批不算偏离"的对照 `test_a_half_batch_is_not_counted_as_a_snapshot_deviation`）。
"""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys

import pytest

from agentflow import schema as S
from agentflow.store import Store, StoreError

_WRITER = """
import json, pathlib, sys
sys.path.insert(0, r"{src}")
from agentflow.store import Store
st = Store(pathlib.Path(r"{root}"))
st.init()
target = st.data / "literature.json"
errs = []
for i in range({n}):
    doc = {{"schema_version": 1,
           "rows": [{{"lit_id": f"{{i:04d}}-{{j:03d}}", "title": "t", "type": "J",
                     "summary": "s", "path": None, "processed": True,
                     "added_at": "2026-01-01T00:00:00+00:00"}}
                    for j in range(30)]}}
    try:
        st._atomic_write(target, doc)
    except Exception as e:
        errs.append(f"{{type(e).__name__}}: {{e}}")
print(json.dumps({{"errors": errs}}))
"""


def _lit(i: str, title: str) -> dict:
    return S.Literature(lit_id=i, title=title, type="J", summary="s", path=None,
                        processed=True, added_at=S.now_iso()).to_dict()


# ============================================================ F-1


def test_a_normal_commit_is_replayable_by_rebuild(store: Store) -> None:
    """正控：正常提交后 rebuild 必须能原样重建（含 counters），且批次都算完整。"""
    store.init()
    with store.tx("literature", actor="t", note="a") as tx:
        tx.upsert("literature", _lit("0000", "第一条"))
    with store.tx("literature", actor="t", note="b") as tx:
        tx.upsert("literature", _lit("0001", "第二条"))

    r = store.rebuild(backup=False)
    assert sorted(x["lit_id"] for x in store.rows("literature")) == ["0000", "0001"]
    assert r["batches_incomplete"] == 0, r
    assert r["batches_applied"] == 2, r


def test_the_event_log_carries_a_commit_marker_per_batch(store: Store) -> None:
    """判据的接口面：每一批事件后面必须有一条 `op="commit"` 标记。

    没有这一条，"只重放完整批次"这件事就没有可判定的输入。
    """
    store.init()
    with store.tx("literature", actor="t", note="a") as tx:
        tx.upsert("literature", _lit("0000", "第一条"))
    evs = store.read_events()
    upserts = [e for e in evs if e.get("op") == "upsert"]
    commits = [e for e in evs if e.get("op") == "commit"]
    assert upserts and commits, evs
    assert {e["batch"] for e in upserts} == {e["batch"] for e in commits}
    assert commits[0]["rows"] == len(upserts)


def test_a_half_written_batch_is_reported_not_silently_dropped(store: Store) -> None:
    """负控（核心）：造出"快照里有、日志里没有提交标记"⇒ rebuild 必须报出来。

    这正是旧顺序（先快照、后事件）崩一次留下的状态。改前 `rebuild()` 会安静地
    丢掉那一行并返回 `{'applied': 1, ...}`，没有任何字段提示"少了一批"。
    """
    store.init()
    with store.tx("literature", actor="t", note="ok") as tx:
        tx.upsert("literature", _lit("0000", "已提交"))

    # 手工造一条"没有提交标记"的半批事件（模拟"事件追加崩在半路"）
    with open(store.events_path, "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps({
            "seq": 99, "ts": S.now_iso(), "batch": "HALF-BATCH",
            "op": "upsert", "table": "literature",
            "row": _lit("0001", "崩在半批里的那一行"),
        }, ensure_ascii=False) + "\n")

    r = store.rebuild(backup=False)
    assert r["batches_incomplete"] == 1, r
    assert sorted(x["lit_id"] for x in store.rows("literature")) == ["0000"], r
    # 那一行没有被重放（半批不算数），但报告里必须看得见这件事
    assert "batches_incomplete" in r


def test_a_legacy_event_without_a_batch_is_still_replayed(store: Store) -> None:
    """兼容口径的正控：历史事件没有 `batch` 字段 ⇒ 一律当完整批次重放。

    为什么必须有这一条：把老事件当"半批"会丢掉整个历史，那比它要防的风险大得多。
    """
    store.init()
    with open(store.events_path, "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps({
            "seq": 1, "ts": S.now_iso(), "op": "upsert", "table": "literature",
            "row": _lit("0000", "旧版写下的一行"),
        }, ensure_ascii=False) + "\n")
    r = store.rebuild(backup=False)
    assert [x["lit_id"] for x in store.rows("literature")] == ["0000"]
    assert r["batches_incomplete"] == 0, r


def test_an_injected_snapshot_failure_does_not_lose_the_commit(store: Store) -> None:
    """负控 2：崩在快照写（新顺序下事件已经落盘）⇒ rebuild 必须把它重放回来。

    这一条钉住"事件先落"这个方向：它是"崩在提交块中间"时唯一不会丢数据的方向。
    """
    store.init()
    with store.tx("literature", actor="t", note="ok") as tx:
        tx.upsert("literature", _lit("0000", "第一次提交"))

    real_write = store._atomic_write

    def boom(path: pathlib.Path, doc: dict) -> None:
        if any(str(r.get("lit_id")) == "0001" for r in (doc.get("rows") or [])):
            raise OSError("注入的崩溃：快照写失败")
        real_write(path, doc)

    store._atomic_write = boom  # type: ignore[method-assign]
    try:
        # `G4-R2`（第 50 轮）：`tx()` 现在把落盘的 `OSError` 翻成 `StoreError`
        # （并把 errno 与目标文件带进消息）—— 落盘层其它失败路径本来就抛它
        # （`init` / 重试耗尽那一支）。所以这里断言 `StoreError`，
        # 并且要求 `__cause__` 是那条原始 `OSError`（诊断信息不许在翻译时丢掉）。
        with pytest.raises(StoreError) as ei:
            with store.tx("literature", actor="t", note="crash") as tx:
                tx.upsert("literature", _lit("0001", "崩在快照写的那一次"))
    finally:
        store._atomic_write = real_write  # type: ignore[method-assign]

    assert isinstance(ei.value.__cause__, OSError), ei.value.__cause__
    assert "注入的崩溃" in str(ei.value), ei.value

    assert sorted(x["lit_id"] for x in store.rows("literature")) == ["0000"], "快照不该有 0001"
    r = store.rebuild(backup=False)
    assert sorted(x["lit_id"] for x in store.rows("literature")) == ["0000", "0001"], r
    assert r["batches_incomplete"] == 0, r


# ============================================================ F-2


def test_alloc_id_requires_the_target_table_to_be_declared(store: Store) -> None:
    """`F-2` 负控：只声明 `counters` 的事务里 `alloc_id("lit")` 必须抛 `StoreError`。"""
    store.init()
    store._atomic_write(store.data / "counters.json",
                        {"schema_version": S.SCHEMA_VERSION, "counters": {"lit": 0}})
    with store.tx("literature", actor="t") as tx:
        tx.upsert("literature", _lit("0000", "已占用"))

    with pytest.raises(StoreError) as ei:
        with store.tx("counters", actor="t") as tx:
            tx.alloc_id("lit")
    assert "literature" in str(ei.value) and "声明" in str(ei.value), str(ei.value)
    # 被拒的事务不许推进 counters
    assert (store.read("counters") or {}).get("counters", {}) == {"lit": 0}


def test_alloc_id_skips_the_occupied_id_when_the_table_is_declared(store: Store) -> None:
    """`F-2` 正控：声明了目标表 ⇒ 跳过已占用的 0000，发 0001（判据没被做成"一律抛"）。"""
    store.init()
    store._atomic_write(store.data / "counters.json",
                        {"schema_version": S.SCHEMA_VERSION, "counters": {"lit": 0}})
    with store.tx("literature", actor="t") as tx:
        tx.upsert("literature", _lit(S.format_id(0), "已占用"))
    with store.tx("literature", actor="t") as tx:
        nid = tx.alloc_id("lit")
        tx.upsert("literature", _lit(nid, "新的"))
    assert nid == S.format_id(1), nid
    rows = {r["lit_id"]: r["title"] for r in store.rows("literature")}
    assert rows == {S.format_id(0): "已占用", S.format_id(1): "新的"}, rows


# ============================================================ F-3


def test_the_temp_name_is_unique_per_writer(store: Store, monkeypatch: pytest.MonkeyPatch) -> None:
    """行为判据（`R3-7` 的修法）：真的观察 `os.replace` 的源路径，而不是读源码找子串。

    这是 `WinError 32` 的直接来源：旧版固定名 `<file>.tmp`，两个写者互抢。
    改前的判据是"读 `store.py` 的文本，断言里面含 `os.getpid()` 与
    `threading.get_ident()`"——它连一行注释都能满足（重审实测：
    把临时名换回固定名、只在注释里写上这两个子串，这条 passes，
    而端到端那条 `test_concurrent_atomic_writers_do_not_collide` failed）。
    一个能被注释满足的判据是判据真空：它不制造覆盖缺口（同文件有端到端判据），
    但会让人以为"临时名唯一"这件事被测住了。

    现在改成行为判据：monkeypatch `os.replace`，从两个不同的写者
    （主线程 + 一个真线程，线程 id 不同）各写一次，断言"实际用过的临时名不同"
    且都带 pid。固定名会让两次相同 ⇒ 这条红。
    """
    import threading

    store.init()
    target = store.data / "literature.json"
    seen: list[str] = []
    real_replace = os.replace

    def spy(src, dst, *a, **kw):
        seen.append(pathlib.Path(src).name)
        return real_replace(src, dst, *a, **kw)

    monkeypatch.setattr(os, "replace", spy, raising=True)

    store._atomic_write(target, {"schema_version": 1, "rows": []})
    t = threading.Thread(target=store._atomic_write,
                         args=(target, {"schema_version": 1, "rows": []}))
    t.start()
    t.join(timeout=30.0)
    assert not t.is_alive(), "第二个写者没有结束"

    assert len(seen) == 2, f"两次落盘各应有一次 os.replace，实际 {seen}"
    assert seen[0] != seen[1], (
        f"两个写者必须用不同的临时名（固定名会在并发下互抢、抛 WinError 32）：{seen}"
    )
    assert all(name.endswith(".tmp") for name in seen), seen
    assert all(f".{os.getpid()}-" in name for name in seen), (
        f"临时名必须带 pid（否则跨进程的两个写者仍会撞名）：{seen}"
    )


def test_concurrent_atomic_writers_do_not_collide(tmp_path: pathlib.Path) -> None:
    """负控（端到端）：两个真进程各写 30 次同一个文件。

    改前：固定临时名 ⇒ 两进程互抢 ⇒ 抛 `PermissionError [WinError 32]`。
    改后：零 `OSError`、最终文件是合法 JSON、不留 `.tmp`。
    """
    work = tmp_path / "ws"
    work.mkdir()
    store = Store(work)
    store.init()
    script = tmp_path / "writer.py"
    script.write_text(_WRITER.format(src=str(pathlib.Path(__file__).resolve().parents[1] / "src"),
                                     root=str(work), n=30), encoding="utf-8")
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    procs = [subprocess.Popen([sys.executable, str(script)], stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, text=True, encoding="utf-8", env=env)
             for _ in range(2)]
    outs = [p.communicate() for p in procs]
    assert [p.returncode for p in procs] == [0, 0], outs
    for out, err in outs:
        data = json.loads(out.strip().splitlines()[-1])
        assert data["errors"] == [], f"并发写者抛了 OSError：{data['errors'][:2]} / {err[:300]}"
    target = work / "data" / "literature.json"
    doc = json.loads(target.read_text(encoding="utf-8"))
    assert len(doc["rows"]) == 30, "最终文件必须是某一个完整写入（不是两个的半成品）"
    leftovers = sorted(p.name for p in (work / "data").glob("*.tmp"))
    assert leftovers == [], f"不许留下临时文件：{leftovers}"


# ============================================================ `R3-3` / `R3-10`


def test_rebuild_reports_rows_that_are_in_the_snapshot_but_not_in_the_log(store: Store) -> None:
    """`R3-3` 负控（核心）：快照超前于日志必须被报出来，而不是静默丢掉那一行。

    改前 `rebuild` 只看日志里有没有 `op=commit` 标记、从不比对快照与日志：
    正常提交之后手工往 `literature.json` 多塞一行（日志无痕）⇒ 返回
    `applied=1 / batches_incomplete=0`，那一行被丢掉而计数为 0
    （重审实测 `temp/reauditR3-A5-f1-probe.txt` 场景 D）。
    "`batches_incomplete == 0`"因此会被读成"库里没有丢过提交"，而那是错的。
    """
    store.init()
    with store.tx("literature", actor="t", note="ok") as tx:
        tx.upsert("literature", _lit("0000", "已提交"))

    doc = json.loads((store.data / "literature.json").read_text(encoding="utf-8"))
    doc["rows"].append(_lit("0001", "只存在于快照里（日志无痕）"))
    store._atomic_write(store.data / "literature.json", doc)

    r = store.rebuild(backup=False)
    assert r["snapshot_rows_not_in_log"] == 1, r
    assert r["snapshot_ahead"] == {"literature": ["0001"]}, r
    assert [x["lit_id"] for x in store.rows("literature")] == ["0000"], "日志是权威"
    # 正控对照：没有偏离时这个计数必须是 0，否则它恒正、等于没有
    r2 = store.rebuild(backup=False)
    assert r2["snapshot_rows_not_in_log"] == 0, r2
    assert r2["snapshot_ahead"] == {}, r2


def test_a_half_batch_is_not_counted_as_a_snapshot_deviation(store: Store) -> None:
    """对照（`R3-3` 别误报）：半批事件里的行不算"快照超前于日志"。

    那一形态由 `batches_incomplete` 负责。两个计数各说一件事，
    混在一起会让"日志里有未提交批次"被读成"快照被手工改过"。
    """
    store.init()
    with store.tx("literature", actor="t", note="ok") as tx:
        tx.upsert("literature", _lit("0000", "已提交"))
    with open(store.events_path, "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps({
            "seq": 99, "ts": S.now_iso(), "batch": "HALF-BATCH",
            "op": "upsert", "table": "literature",
            "row": _lit("0001", "崩在半批里的那一行"),
        }, ensure_ascii=False) + "\n")

    r = store.rebuild(backup=False)
    assert r["batches_incomplete"] == 1, r
    assert r["snapshot_rows_not_in_log"] == 0, r
    assert r["snapshot_ahead"] == {}, r


def test_the_backoff_comment_matches_the_measured_wait(store: Store,
                                                       monkeypatch: pytest.MonkeyPatch) -> None:
    """`R3-10` 判据：注释里的总等待必须与实测同量级（差 <20%）。

    改前注释写 ≈0.62s（0.02+0.04+0.08+0.16+0.32），实测 1.27s ——
    差的那 0.64s 是"第 6 次失败之后还 sleep 了一觉"，而这段代码在写者锁内，
    那一觉会原样叠加到持锁时长上。修法：最后一次失败后不 sleep，
    让代码与注释一致（总等待 = `_REPLACE_BACKOFF_S * (2**(N-1) - 1)`）。
    """
    import time as _time

    from agentflow import store as ST

    store.init()

    def always_fail(src, dst, *a, **kw):
        raise PermissionError(32, "注入：目标文件被另一个进程持有着")

    monkeypatch.setattr(os, "replace", always_fail, raising=True)
    t0 = _time.monotonic()
    with pytest.raises(StoreError):
        store._atomic_write(store.data / "literature.json",
                            {"schema_version": 1, "rows": []})
    elapsed = _time.monotonic() - t0

    expected = ST._REPLACE_BACKOFF_S * (2 ** (ST._REPLACE_ATTEMPTS - 1) - 1)
    assert expected == pytest.approx(0.62, abs=1e-9), expected
    assert elapsed == pytest.approx(expected, rel=0.2), (
        f"实测 {elapsed:.3f}s 与注释/公式给的 {expected:.3f}s 差得太多 —— "
        "退避的 sleep 次数与注释不一致（`R3-10`）"
    )

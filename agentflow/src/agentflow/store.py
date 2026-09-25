"""共享存储：跨进程锁、原子写、事务、事件日志、ID 分配、重建。

这是 A/B 两个智能体唯一的交汇点，因此把三件事集中在这里做对：

1. **不存在"部分写入"** —— 一律"写临时文件 → os.replace"，且**先校验后落盘**。
   校验失败就整笔放弃，快照不会被污染成半成品。
2. **不存在"丢失更新"** —— 任何读-改-写都在同一把排他锁内完成。A 追加文献、
   B 改 `processed`，两者并发时若各自"读全表→改一行→写全表"，后写的一方会
   把先写的一方覆盖掉。锁是这里唯一正确的解法。
3. **不存在"说不清谁改了什么"** —— 每次落盘同时追加事件到 `events.jsonl`。
   事件里带的是**整行 upsert**（而不是 diff），于是 `rebuild()` 只需按主键折叠
   就能重建快照；这让"快照损坏/手工改坏"永远可恢复。

多表事务按**固定顺序**加锁（见 `LOCK_ORDER`），这是避免死锁的标准做法。
"""

from __future__ import annotations

import json
import os
import shutil
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

from filelock import FileLock, Timeout

from . import schema as S

#: 加锁的固定顺序。任何多表事务都必须按这个顺序取锁，否则两个事务可能互相等待。
#: 新增表一律**追加在 counters 之前**（counters 永远是最后一把，因为任何 alloc 都要它）。
LOCK_ORDER: tuple[str, ...] = (
    "search_requests",
    "literature",
    "concepts",
    "relations",
    "analysis_reports",
    "research_questions",
    "reprocess_requests",
    "experiments",
    "attack_plans",
    "documents",
    "dependencies",
    "review_findings",
    "tasks",
    "usage_ledger",
    "eval_results",
    "counters",
)

#: 4 位 ID 的上限。用满即 fail-closed（DESIGN.md §0.1 C4）。
MAX_ID = 9999


class StoreError(RuntimeError):
    pass


class IdExhausted(StoreError):
    """4 位编号空间用尽。宁可显式失败，也不静默升位宽。"""


def _now() -> str:
    return S.now_iso()


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def lease_expired(lease_until: str | None) -> bool:
    """租约是否已过期。空租约视为"无人持有"。"""
    dt = _parse_iso(lease_until)
    if dt is None:
        return True
    return datetime.now(timezone.utc) >= dt


def make_lease(seconds: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).replace(microsecond=0).isoformat()


class Tx:
    """一次事务。通过 `tx.rows(t)` 拿行、`tx.mark_dirty(t)` 声明要写回。"""

    def __init__(self, store: "Store", tables: tuple[str, ...], actor: str, note: str = ""):
        self._store = store
        self.tables = tables
        self.actor = actor
        self.note = note
        self._rows: dict[str, list[dict]] = {}
        self._dirty: set[str] = set()
        self._events: list[dict] = []

    # ---- 读
    def rows(self, table: str) -> list[dict]:
        if table not in self.tables:
            raise StoreError(f"事务未声明表 {table}（声明了 {self.tables}）")
        if table not in self._rows:
            self._rows[table] = [dict(r) for r in self._store._load(table)["rows"]]
        return self._rows[table]

    def find(self, table: str, **eq: Any) -> dict | None:
        for r in self.rows(table):
            if all(r.get(k) == v for k, v in eq.items()):
                return r
        return None

    # ---- 写
    def upsert(self, table: str, row: dict, note: str = "") -> None:
        """按主键插入或整行替换一条记录。"""
        if table not in self.tables:
            raise StoreError(f"事务未声明表 {table}")
        id_field = S.TABLES[table]["id_field"]
        key = row.get(id_field)
        if key is None:
            raise StoreError(f"{table} 的行缺少主键 {id_field}")
        rows = self.rows(table)
        for i, r in enumerate(rows):
            if r.get(id_field) == key:
                rows[i] = dict(row)
                break
        else:
            rows.append(dict(row))
        self._dirty.add(table)
        self._record(table, row, note)

    def append(self, table: str, row: dict, note: str = "") -> None:
        self.upsert(table, row, note=note)  # upsert 语义已足够（按主键去重）

    def insert_unique(self, table: str, row: dict, key_field: str, note: str = "",
                      id_kind: str | None = None) -> bool:
        """**`INSERT … ON CONFLICT DO NOTHING`** 在本栈里的等价物。

        返回 `True` = 真的插进去了；`False` = 这个键**已经有一行**，本次什么都没写。

        ⚠️ **它不自己加锁，唯一性只在"读与写同一个临界区"内成立。**
        由 `store.tx` 持有该表排他锁来保证：`tx.rows()` 在锁内读的是
        **前一个进程刚提交的那一版**，所以后到者一定看得见先到者。
        在 `store.tx` **之外**调用它 = 把"先读后写"的窗口原样搬回来，
        而代码看起来像加了约束 —— 这是本方法唯一危险的误用方式。

        为什么空键要抛而不是"当作不冲突"：空键要么让每一行都冲突
        （唯一性变成"全表只能有一行"），要么让唯一性完全失效 ——
        两种都不是调用方想要的，所以不给它一个静默的解释。

        `id_kind` 是本实现对提案的一处**最小附加**（见本提案 §2.3 的
        "冲突时不调 alloc_id ⇒ 重放不消耗号"）：给了它，主键就在**判重之后**
        才分配，于是重复调用不会在计数器上留下永久空洞。不给则沿用提案原样的
        "主键由调用方填好"语义。
        """
        if table not in self.tables:
            raise StoreError(f"事务未声明表 {table}（声明了 {self.tables}）")
        key = str(row.get(key_field) or "").strip()
        if not key:
            raise StoreError(
                f"insert_unique({table}) 的 {key_field} 为空 —— "
                "空键在唯一性语义下没有定义（见 docstring）"
            )
        for r in self.rows(table):
            if str(r.get(key_field) or "") == key:
                return False
        if id_kind is not None:
            id_field = S.TABLES[table]["id_field"]
            row = dict(row)
            row[id_field] = self.alloc_id(id_kind)
        self.upsert(table, row, note=note)
        return True

    def mark_dirty(self, table: str) -> None:
        """声明"这张表被就地改过了，提交时要写回"。

        为什么需要这个公开方法：`tx.rows(t)` 返回的是**可变列表**，调用方可以直接
        改里面的 dict 或 `del` 掉一项（删行就是这么做的）。那种情况下 `upsert` 不会被调用，
        于是没有任何东西把这张表标成脏 —— 提交时它会被静默跳过，**改动凭空消失**。
        （此前 docstring 提到过 `mark_dirty` 但它并不存在，调用方只能去摸 `tx._dirty`
        这个私有属性，这是文档与实现对不上。）
        """
        if table not in self.tables:
            raise StoreError(f"事务未声明表 {table}（声明了 {self.tables}）")
        self._dirty.add(table)

    # ---- ID 分配（锁内进行，与建行同事务）
    def alloc_id(self, kind: str) -> str:
        """分配一个 4 位 ID。

        ## 为什么必须在这里**跳过已被占用的号**（一次真实缺陷的修复）

        `counters.json` 是 ID 分配器的**缓存**，它的真源是各张表里已经用掉的号。
        两者一旦漂移（手工建行、从台账恢复、外部脚本写入、旧版 `rebuild`），
        分配器就会发出一个**已经被占用**的号 —— 而 `upsert` 是按主键替换，
        于是新行会**静默覆盖**掉旧行：不报重复 ID、不报错、旧数据凭空消失。

        实测教训：D 的 `adjudicate` 建矛盾问题时，新建的 (0002,0004) 问题被
        已存在的 0000 顶掉，`new_question_ids` 还返回 `["0000"]` ——
        调用方看到"新建成功"，而知识库里少了一条问题。

        所以这里做三件事（任何一条单独都不够）：

        1. **在已声明的事务表里查一遍**该号是否已被占用，占用就往后跳；
        2. 跳完之后把 `counters` 推到**最终号 + 1**，于是这个缓存会
           **自愈**（下次 `verify` 不会再报 `counter_behind`）；
        3. 越界（超过 :data:`MAX_ID`）时抛 :class:`IdExhausted`，不静默升位宽。

        为什么用"跳过"而不是"抛异常"：漂移是**既成事实**（数据已经在表里），
        此时让整个智能体崩掉并不能修好它；往后跳一位既能继续工作，
        又保证了"不会覆盖"。真正的失序仍然由 `verify` 的 `counter_behind`
        与 `id_gap` 报出来 —— **这里负责不破坏数据，`verify` 负责报告失序**。
        """
        if kind not in S.ID_COUNTERS:
            raise StoreError(f"未知 ID 类别：{kind}")
        if "counters" not in self.tables:
            raise StoreError("分配 ID 的事务必须声明 counters 表")
        # ⚠️ 必须优先用**本事务内已改过**的 counters，而不是重新从磁盘读。
        # 否则同一事务里连续 alloc 会反复读到同一个初值，把同一个 ID 发出去多次
        # —— 表现为"多行拿到同一个 lit_id"，而按主键 upsert 会静默互相覆盖。
        c = self._store._dirty_counters
        if c is None:
            c = self._store._load("counters")
            self._store._dirty_counters = c
        counters = c.setdefault("counters", {})
        nxt = int(counters.get(kind, 0))

        # ---- [1] 跳过已被占用的号（只在目标表已被本事务声明时才能查）
        field = S.ID_COUNTERS[kind]
        table = next((t for t, spec in S.TABLES.items() if spec["id_field"] == field), None)
        jumped = 0
        if table is not None and table in self.tables:
            used = {str(r.get(field)) for r in self.rows(table) if r.get(field) is not None}
            while f"{nxt:04d}" in used:
                nxt += 1
                jumped += 1
                if nxt > MAX_ID:
                    raise IdExhausted(
                        f"{kind} 的 4 位编号空间已用尽（上限 {MAX_ID}）。"
                        "请勿静默升位宽 —— 那会破坏所有历史 ID 的解析（DESIGN.md §0.1 C4/§9.7）。"
                    )

        if nxt > MAX_ID:
            raise IdExhausted(
                f"{kind} 的 4 位编号空间已用尽（上限 {MAX_ID}）。"
                "请勿静默升位宽 —— 那会破坏所有历史 ID 的解析（DESIGN.md §0.1 C4/§9.7）。"
            )
        counters[kind] = nxt + 1
        self._dirty.add("counters")
        self._record("counters", {"kind": kind, "allocated": f"{nxt:04d}"}, note="alloc_id")
        if jumped:
            # 跳过号这件事必须**可见**：它是"计数器和表已经漂移"的直接证据。
            self.info(
                "alloc_id_skipped_occupied",
                kind=kind,
                table=table,
                jumped=jumped,
                allocated=f"{nxt:04d}",
                note=(
                    "计数器落后于表：已跳过被占用号以免 upsert 静默覆盖旧行。"
                    "建议跑 `agentflow verify`（会报 counter_behind）与 `agentflow rebuild`。"
                ),
            )
        return f"{nxt:04d}"

    # ---- 事件
    def _record(self, table: str, row: dict, note: str = "") -> None:
        self._events.append(
            {"op": "upsert", "table": table, "row": row, "actor": self.actor, "note": note or self.note}
        )

    def info(self, message: str, **extra: Any) -> None:
        """只记日志、不改状态。"""
        self._events.append({"op": "info", "message": message, "actor": self.actor, **extra})


class Store:
    """一个 data 目录 + 一个 library 目录。"""

    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        self.data = self.root / "data"
        self.library = self.root / "library"
        self.locks = self.data / ".locks"
        self.events_path = self.data / "events.jsonl"
        self._dirty_counters: dict | None = None

    # ---------------------------------------------------------------- 初始化
    def init(self, force: bool = False) -> None:
        self.data.mkdir(parents=True, exist_ok=True)
        self.library.mkdir(parents=True, exist_ok=True)
        self.locks.mkdir(parents=True, exist_ok=True)
        for table, spec in S.TABLES.items():
            p = self.data / spec["file"]
            if force or not p.exists():
                self._atomic_write(p, S.empty_table())
        cp = self.data / "counters.json"
        if force or not cp.exists():
            self._atomic_write(cp, {"schema_version": S.SCHEMA_VERSION, "counters": {}})
        self.events_path.touch(exist_ok=True)

    def exists(self) -> bool:
        return all((self.data / s["file"]).exists() for s in S.TABLES.values())

    # ---------------------------------------------------------------- 低级 IO
    @staticmethod
    def _dump(doc: dict) -> str:
        return json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=False) + "\n"

    def _atomic_write(self, path: Path, doc: dict) -> None:
        """写临时文件 → fsync → os.replace。同目录替换在 Windows 上也是原子的。"""
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        payload = self._dump(doc)
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)

    def _load(self, table: str) -> dict:
        if table == "counters":
            p = self.data / "counters.json"
            if not p.exists():
                return {"schema_version": S.SCHEMA_VERSION, "counters": {}}
            return json.loads(p.read_text(encoding="utf-8"))
        spec = S.TABLES.get(table)
        if spec is None:
            raise StoreError(f"未知表：{table}")
        p = self.data / spec["file"]
        if not p.exists():
            return S.empty_table()
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise StoreError(
                f"{spec['file']} 不是合法 JSON（{e}）。可用 `agentflow rebuild` 从 events.jsonl 重建。"
            ) from e

    def read(self, table: str) -> dict:
        """无锁快照读。仅用于展示/统计；要改数据必须走 `tx`。"""
        return self._load(table)

    def rows(self, table: str) -> list[dict]:
        return self.read(table)["rows"]

    # ---------------------------------------------------------------- 事务
    @contextmanager
    def tx(self, *tables: str, actor: str = "unknown", note: str = "", timeout: float = 30.0) -> Iterator[Tx]:
        """多表事务。按 LOCK_ORDER 固定顺序加锁；任一表校验失败则整笔不落盘。"""
        unknown = [t for t in tables if t not in LOCK_ORDER]
        if unknown:
            raise StoreError(f"未知表：{unknown}")
        ordered = tuple(sorted(set(tables) | {"counters"}, key=LOCK_ORDER.index))
        held: list[FileLock] = []
        try:
            self.locks.mkdir(parents=True, exist_ok=True)
            for t in ordered:
                lk = FileLock(str(self.locks / f"{t}.lock"))
                try:
                    lk.acquire(timeout=timeout)
                except Timeout as e:
                    raise StoreError(
                        f"获取 {t} 的锁超时（{timeout}s）。可能有另一个智能体持有该锁；"
                        "若进程已死，锁文件是可安全删除的（filelock 用 OS 锁，不含内容）。"
                    ) from e
                held.append(lk)

            t = Tx(self, ordered, actor, note)
            yield t

            # ---- 提交：先全部校验，再全部落盘。任一失败 => 什么都不写。
            to_write: list[tuple[Path, dict]] = []
            for table in sorted(t._dirty, key=LOCK_ORDER.index):
                if table == "counters":
                    doc = self._dirty_counters or self._load("counters")
                    to_write.append((self.data / "counters.json", doc))
                    continue
                spec = S.TABLES[table]
                doc = {"schema_version": S.SCHEMA_VERSION, "rows": t.rows(table)}
                S.validate_table(table, doc)
                to_write.append((self.data / spec["file"], doc))

            for path, doc in to_write:
                self._atomic_write(path, doc)

            if t._events:
                self._append_events(t._events)
        finally:
            # ⚠️ 无论成功还是失败都必须清空事务内的计数器缓存。
            # 只在提交成功时清，会让**失败事务**把改过的计数留在内存里：下一次
            # alloc_id 会基于一个磁盘上并不存在的值发号，轻则产生 ID 空洞，
            # 重则与另一个进程发出的号**真撞号**，而按主键 upsert 会静默覆盖。
            self._dirty_counters = None
            for lk in reversed(held):
                try:
                    lk.release()
                except Exception:  # noqa: BLE001
                    # 释放锁失败**刻意不向上抛**：这段在 `finally` 里，抛出去会**掩盖
                    # 真正的失败原因**（事务里那个异常才是要报的）。而且 filelock 用的是
                    # OS 锁，进程退出时由内核回收，锁文件可安全删除 —— 泄漏的代价是有限的，
                    # 而掩盖原始异常会让"为什么这笔事务失败"永远查不出来。
                    pass

    # ---------------------------------------------------------------- 事件日志
    def _append_events(self, events: list[dict]) -> None:
        self.events_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.events_path, "a", encoding="utf-8", newline="\n") as f:
            for e in events:
                e = {"seq": self._next_seq(), "ts": _now(), **e}
                f.write(json.dumps(e, ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())

    def _next_seq(self) -> int:
        if not hasattr(self, "_seq"):
            n = 0
            if self.events_path.exists():
                with open(self.events_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            n += 1
            self._seq = n
        self._seq += 1
        return self._seq

    def read_events(self) -> list[dict]:
        out = []
        if not self.events_path.exists():
            return out
        with open(self.events_path, "r", encoding="utf-8") as f:
            for i, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    # 半行（崩溃时可能产生）——记录但不中断重建
                    out.append({"seq": i, "op": "corrupt", "raw": line[:200]})
        return out

    def rebuild(self, backup: bool = True) -> dict:
        """从 events.jsonl 重建全部快照。

        因为事件里存的是**整行 upsert**，折叠逻辑就是"按主键 last-write-wins"。
        """
        if backup:
            bdir = self.data / f".backup-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
            bdir.mkdir(parents=True, exist_ok=True)
            for spec in S.TABLES.values():
                src = self.data / spec["file"]
                if src.exists():
                    shutil.copy2(src, bdir / spec["file"])
            if (self.data / "counters.json").exists():
                shutil.copy2(self.data / "counters.json", bdir / "counters.json")

        state: dict[str, dict[str, dict]] = {t: {} for t in S.TABLES}
        order: dict[str, list[str]] = {t: [] for t in S.TABLES}
        counters: dict[str, int] = {}
        applied = skipped = 0

        for e in self.read_events():
            if e.get("op") != "upsert":
                continue
            table = e.get("table")
            row = e.get("row") or {}
            if table == "counters":
                kind = row.get("kind")
                alloc = row.get("allocated")
                if kind and alloc is not None:
                    counters[kind] = max(counters.get(kind, 0), int(alloc) + 1)
                applied += 1
                continue
            if table not in S.TABLES:
                skipped += 1
                continue
            try:
                obj = S.row_from_dict(table, row)
                obj.validate()
            except Exception:
                skipped += 1
                continue
            key = getattr(obj, S.TABLES[table]["id_field"])
            if key not in state[table]:
                order[table].append(key)
            # 合并而非替换：schema 字段用**校验后的规范值**，其它键（`_keys`、
            # `_quote_check` 这类诊断/扩展字段）原样保留。
            # 早先这里只存 obj，导致 rebuild 后诊断字段全部丢失 —— 虽然判重靠
            # `doi`/`dedup_key` 兜底仍然可用，但"能重建"就不该"重建出更少的信息"。
            canonical = obj.to_dict()
            merged = {k: v for k, v in row.items() if k not in canonical}
            merged.update(canonical)
            state[table][key] = merged
            applied += 1

        for table in S.TABLES:
            rows = [state[table][k] for k in order[table]]
            doc = {"schema_version": S.SCHEMA_VERSION, "rows": rows}
            S.validate_table(table, doc)
            self._atomic_write(self.data / S.TABLES[table]["file"], doc)
        self._atomic_write(self.data / "counters.json", {"schema_version": S.SCHEMA_VERSION, "counters": counters})
        return {"applied": applied, "skipped": skipped, "counters": counters}

    # ---------------------------------------------------------------- 路径工具
    def library_path(self, rel: str | None) -> Path | None:
        """把表里的相对路径解析为绝对路径，并**强制**它仍在 library/ 内。

        这是防路径穿越的最后一道闸：即使有人手工把 `path` 改成 `../../etc/passwd`，
        这里也会拒绝，而不是去读那个文件。
        """
        if not rel:
            return None
        candidate = (self.library / rel).resolve()
        try:
            candidate.relative_to(self.library.resolve())
        except ValueError:
            raise StoreError(f"文献路径越出 library/：{rel!r}")
        return candidate

    def stats(self) -> dict:
        out: dict[str, Any] = {"root": str(self.root)}
        for t, spec in S.TABLES.items():
            rows = self.rows(t)
            out[t] = {"count": len(rows)}
            if t == "search_requests":
                out[t]["done"] = sum(1 for r in rows if r.get("done"))
                out[t]["pending"] = sum(1 for r in rows if not r.get("done"))
            if t == "literature":
                out[t]["processed"] = sum(1 for r in rows if r.get("processed"))
                out[t]["downloaded"] = sum(1 for r in rows if r.get("path"))
            if t == "relations":
                by_status: dict[str, int] = {}
                for r in rows:
                    by_status[r.get("status", "?")] = by_status.get(r.get("status", "?"), 0) + 1
                out[t]["by_status"] = by_status
                out[t]["quote_verified"] = sum(1 for r in rows if r.get("quote_verified") is True)
                out[t]["quote_unverified"] = sum(1 for r in rows if r.get("quote_verified") is False)
                out[t]["quote_unknown"] = sum(1 for r in rows if r.get("quote_verified") is None)
        out["events"] = {"appended": len(self.read_events())}
        return out
